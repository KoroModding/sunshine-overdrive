"""Driving the Dolphin host: save states and relaunch with configuration.

Why this module exists
----------------------
The 120 FPS tier needs the emulated VI to deliver more than 59.94 fields per
second. That is Dolphin's **VBI Frequency Override** setting
(`Dolphin.Core.VIOverclock`). It lives in the host, not in MEM1: no memory
write reaches it, and Dolphin does not reread its config file mid-game.

The only route that needs nobody's help is: save state, relaunch Dolphin with
the setting passed on the command line, reload the state.

Dolphin command line
--------------------
Read from the binary (`Dolphin.exe`):

    --exec / -e        <chemin>                       image to launch
    --save_state / -s  <chemin>                       state to load on startup
    --config / -C      <Système>.<Section>.<Clé>=<Valeur>

Relevant keys:

    Dolphin.Core.VIOverclockEnable = True
    Dolphin.Core.VIOverclock       = 2.0

`-C` feeds a "command line" config layer that is **not written** to
`Dolphin.ini`: relaunching without the option restores the initial state; the
user's configuration is never modified.

Saving state -- dead end
------------------------
Dolphin cannot create a state from the command line: it has to receive its
hotkey (Shift+F1 by default). Its input goes through DirectInput, so
`PostMessage` is not enough -- it needs system-level injection (`SendInput`),
hence briefly giving focus to its window.

**This does not work from a command-line agent.** Measured 2026-09-15:
`SendInput` does not reach the interactive desktop from this context -- even
`GetAsyncKeyState`, called in the process that just injected the keystroke,
does not see it. Neither forced focus nor the choice of window (render or
main) changes anything.

`savestate` is kept because it works again in a session started by hand by
the user, and because it reports its failure instead of hiding it. Nothing in
the project may depend on it.

The route that worked for the same need is
[`second_instance.py`](second_instance.py): an isolated instance, driven by
the same memory injection as the rest of the project, with no keyboard
dependency.

Usage
-----
    python dolphin_host.py savestate [emplacement]
    python dolphin_host.py relaunch [--vi 2.0] [--state <chemin>]
"""

from __future__ import annotations

import ctypes
import os
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

# Local paths come from environment variables, else defaults:
#   DOLPHIN_EXE       Dolphin executable      (default: "Dolphin.exe" on PATH)
#   DOLPHIN_USER_DIR  Dolphin user directory  (default: %APPDATA%/Dolphin Emulator)
#   SMS_ISO           GMSE01 game image       (no default, must be provided)
_APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
DOLPHIN_EXE = Path(os.environ.get("DOLPHIN_EXE", "Dolphin.exe"))
USER_DIR = Path(os.environ.get("DOLPHIN_USER_DIR", _APPDATA / "Dolphin Emulator"))
STATE_DIR = USER_DIR / "StateSaves"
ISO = Path(os.environ.get("SMS_ISO", "GMSE01.iso"))

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

VK_SHIFT = 0x10
VK_F1 = 0x70
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
SW_RESTORE = 9


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def force_foreground(hwnd: int) -> bool:
    """Give focus to `hwnd` despite the Windows foreground lock.

    Windows refuses `SetForegroundWindow` to a process that is not already in
    the foreground -- measured here: the direct call returns 0 and does
    nothing. The usual workaround is to temporarily attach the calling
    thread's input queue to the thread owning the active window, so both
    count as one "input context" and the restriction is lifted. The
    attachment is undone right after.
    """
    current = _user32.GetForegroundWindow()
    if current == hwnd:
        return True

    target_thread = _user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = _kernel32.GetCurrentThreadId()
    foreground_thread = _user32.GetWindowThreadProcessId(current, None) if current else 0

    for thread in {t for t in (target_thread, foreground_thread) if t and t != current_thread}:
        _user32.AttachThreadInput(current_thread, thread, True)
    try:
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
        _user32.SetActiveWindow(hwnd)
        _user32.SetFocus(hwnd)
    finally:
        for thread in {t for t in (target_thread, foreground_thread) if t and t != current_thread}:
            _user32.AttachThreadInput(current_thread, thread, False)

    time.sleep(0.3)
    return _user32.GetForegroundWindow() == hwnd


def _send_key(vk: int, up: bool) -> None:
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)
    _user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))


def find_window(pid: int) -> int | None:
    """Main visible window of process `pid`."""
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append((hwnd, buffer.value))
        return True

    _user32.EnumWindows(callback, 0)
    if not found:
        return None
    # The render window is the one whose title carries the game ID; the others
    # (game list, settings dialogs) do not receive hotkeys.
    for hwnd, title in found:
        if "(" in title and ")" in title and "|" in title:
            return hwnd
    return found[0][0]


def dolphin_pid() -> int | None:
    output = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    for line in output.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("dolphin"):
            return int(parts[1])
    return None


def save_state(slot: int = 1, timeout: float = 12.0) -> Path | None:
    """Send Shift+F<slot> to Dolphin and wait for the state file to appear.

    Returns the path of the created state, or None if nothing appeared.
    """
    pid = dolphin_pid()
    if pid is None:
        raise RuntimeError("Dolphin n'est pas lancé")
    window = find_window(pid)
    if window is None:
        raise RuntimeError("fenêtre Dolphin introuvable")

    before = {p: p.stat().st_mtime for p in STATE_DIR.glob("*.s??")}
    previous_focus = _user32.GetForegroundWindow()

    if not force_foreground(window):
        raise RuntimeError(
            "impossible de donner le focus à la fenêtre de rendu de Dolphin ; "
            "une boîte de dialogue modale la bloque peut-être"
        )
    time.sleep(0.5)
    _send_key(VK_SHIFT, False)
    _send_key(VK_F1 + slot - 1, False)
    time.sleep(0.08)
    _send_key(VK_F1 + slot - 1, True)
    _send_key(VK_SHIFT, True)

    deadline = time.perf_counter() + timeout
    result = None
    while time.perf_counter() < deadline:
        for path in STATE_DIR.glob("*.s??"):
            if path not in before or path.stat().st_mtime > before[path]:
                result = path
                break
        if result:
            break
        time.sleep(0.25)

    if previous_focus:
        _user32.SetForegroundWindow(previous_focus)
    # Let Dolphin finish writing the file before declaring it usable.
    time.sleep(1.0)
    return result


def kill_dolphin(timeout: float = 15.0) -> None:
    pid = dolphin_pid()
    if pid is None:
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, check=False)
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline and dolphin_pid() is not None:
        time.sleep(0.3)


def launch(iso: Path, state: Path | None = None,
           vi_overclock: float | None = None) -> int:
    """Relaunch Dolphin, optionally with a VI overclock and a state to load."""
    command = [str(DOLPHIN_EXE), "-e", str(iso)]
    if state is not None:
        command += ["-s", str(state)]
    if vi_overclock is not None:
        command += [
            "-C", "Dolphin.Core.VIOverclockEnable=True",
            "-C", f"Dolphin.Core.VIOverclock={vi_overclock}",
        ]
    subprocess.Popen(command, creationflags=subprocess.DETACHED_PROCESS)

    deadline = time.perf_counter() + 30.0
    while time.perf_counter() < deadline:
        pid = dolphin_pid()
        if pid is not None:
            return pid
        time.sleep(0.4)
    raise RuntimeError("Dolphin n'a pas démarré")


def wait_for_game(timeout: float = 90.0):
    """Wait until MEM1 can be located and a level is loaded."""
    sys.path.insert(0, str(Path(__file__).parent))
    from dolphin import Dolphin  # late import: the process must exist

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            emulator = Dolphin()
            director = emulator.u32(0x8040E178)
            mario = emulator.u32(0x8040E0E8)
            if emulator.is_valid_pointer(director) and emulator.is_valid_pointer(mario):
                return emulator
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError("le jeu n'a pas atteint un état jouable")


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    if argv[1] == "savestate":
        slot = int(argv[2]) if len(argv) > 2 else 1
        path = save_state(slot)
        if path:
            print(f"état sauvegardé : {path}")
            return 0
        print("aucun état créé — le raccourci n'a pas été reçu.")
        print("Attendu hors d'une session interactive : voir l'en-tête du "
              "module, et second_instance.py pour la voie qui marche.")
        return 1

    if argv[1] == "relaunch":
        # Relaunches the user's instance: this **destroys** the current game
        # if no state was saved beforehand.
        options = argv[2:]
        vi = None
        state = None
        while options:
            flag = options.pop(0)
            if flag == "--vi":
                vi = float(options.pop(0))
            elif flag == "--state":
                state = Path(options.pop(0))
            else:
                print(f"option inconnue : {flag}")
                return 2

        if state is not None and not state.exists():
            print(f"état introuvable : {state}")
            return 1

        print("arrêt de l'instance en cours…")
        kill_dolphin()
        pid = launch(ISO, state=state, vi_overclock=vi)
        print(f"relancé, PID {pid}"
              + (f", VIOverclock = {vi}" if vi is not None else
                 ", configuration d'origine"))
        emulator = wait_for_game()
        print(f"jeu prêt — {emulator.game_id}")
        return 0

    print(f"commande inconnue : {argv[1]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
