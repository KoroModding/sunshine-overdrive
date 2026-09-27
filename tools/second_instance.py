"""Isolated second Dolphin instance, for settings that require a restart.

Problem
-------
The 120 FPS tier needs the emulated VI to deliver more than 59.94 fields per
second, i.e. Dolphin's **VBI Frequency Override**. That setting lives in the
host, not in MEM1: no memory write reaches it, and Dolphin does not reread
its configuration mid-game.

Two routes were ruled out first:

- **Send the save-state hotkey to Dolphin, then relaunch it.** Impossible:
  `SendInput` does not reach the interactive desktop from this context --
  verified, even `GetAsyncKeyState` in the calling process does not see the
  injected keystroke. Keyboard automation is out.
- **Edit Dolphin's configuration and relaunch it.** That would destroy the
  user's running session.

Chosen approach
---------------
Start a **second instance** with its own user directory (`--user`), its own
overclock setting (`--config`) and a copy of the memory card. The user's
instance is never touched: not its configuration, save or running game.

Menu navigation uses the same memory injection as the rest of the project
(`pad.py`), which does not depend on the keyboard. No timed sequence is
needed: hammering A and START until `gpMarDirector` and `gpMarioOriginal`
become valid gets through logos, intro, title screen and file select.

Status -- on hold
-----------------
The mechanism is complete and **verified up to entering the game**: instance
started with `VIOverclock = 2.0`, logos, intro, title screen and file select
passed unattended, stable in-game arrival after 92.6 s (measured 2026-09-15,
[`docs/00-journal.md`](../docs/00-journal.md)). The 120 tier measurement
itself was **not** done: the session stopped there.

By decision of the project author (2026-09-17), **this module must not be run
without explicit agreement**. Two Dolphin instances side by side compete for
the GPU and skew any frame rate measurement of the user's instance. It is
kept complete for when the measurement resumes.

Usage
-----
    python second_instance.py start [--vi 2.0] [--user <répertoire>]
    python second_instance.py stop
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

# Local paths come from environment variables, else defaults:
#   DOLPHIN_EXE       Dolphin executable      (default: "Dolphin.exe" on PATH)
#   DOLPHIN_USER_DIR  Dolphin user directory  (default: %APPDATA%/Dolphin Emulator)
#   SMS_ISO           GMSE01 game image       (no default, must be provided)
_APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
DOLPHIN_EXE = Path(os.environ.get("DOLPHIN_EXE", "Dolphin.exe"))
ISO = Path(os.environ.get("SMS_ISO", "GMSE01.iso"))
HOST_USER_DIR = Path(os.environ.get("DOLPHIN_USER_DIR", _APPDATA / "Dolphin Emulator"))

GP_MAR_DIRECTOR = 0x8040E178
GP_MARIO = 0x8040E0E8
VT_MARIO_GAMEPAD = 0x803DF44C

OFF_HELD = 0x18
BUTTON_A = 0x0100
BUTTON_START = 0x1000


def running_pids() -> set[int]:
    output = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    pids = set()
    for line in output.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("dolphin"):
            pids.add(int(parts[1]))
    return pids


def prepare_user_dir(target: Path) -> Path:
    """Isolated user directory with the user's configuration and memory card
    copied in.

    The configuration is copied so the second instance renders under the same
    conditions as the first (same backend, same graphics settings); otherwise
    a frame rate comparison would be meaningless. The memory card is copied to
    load an existing save instead of going through the whole intro.
    """
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    (target / "Config").mkdir(parents=True, exist_ok=True)
    (target / "GC/USA/Card A").mkdir(parents=True, exist_ok=True)
    (target / "StateSaves").mkdir(parents=True, exist_ok=True)

    shutil.copytree(HOST_USER_DIR / "Config", target / "Config", dirs_exist_ok=True)
    for source in (HOST_USER_DIR / "GC").glob("SRAM.raw"):
        shutil.copy2(source, target / "GC")
    for source in (HOST_USER_DIR / "GC/USA/Card A").glob("*.gci"):
        shutil.copy2(source, target / "GC/USA/Card A")
    return target


def launch(user_dir: Path, vi_overclock: float | None = None,
           timeout: float = 60.0) -> int:
    """Start the instance and return its PID."""
    before = running_pids()
    command = [
        str(DOLPHIN_EXE), "-u", str(user_dir), "-e", str(ISO), "-b",
        "-C", "Dolphin.DSP.Volume=0",  # don't double the user's audio
    ]
    if vi_overclock is not None:
        command += [
            "-C", "Dolphin.Core.VIOverclockEnable=True",
            "-C", f"Dolphin.Core.VIOverclock={vi_overclock}",
        ]
    subprocess.Popen(command, creationflags=subprocess.DETACHED_PROCESS)

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        new = running_pids() - before
        if new:
            return new.pop()
        time.sleep(0.5)
    raise RuntimeError("la seconde instance n'a pas démarré")


def wait_for_memory(pid: int, timeout: float = 120.0) -> Dolphin:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            return Dolphin(pid)
        except Exception:
            time.sleep(1.5)
    raise RuntimeError("MEM1 introuvable dans la seconde instance")


def find_pads(emulator: Dolphin) -> list[int]:
    """`TMarioGamePad` instances, found by their vtable pointer.

    The vtable is needed here: the usual resolution (`TMario + 0x4FC`)
    assumes Mario exists, which is not the case in menus.
    """
    pattern = struct.pack(">I", VT_MARIO_GAMEPAD)
    found = []
    base, size, chunk = 0x80000000, 0x1800000, 0x100000
    for offset in range(0, size, chunk):
        blob = emulator.read(base + offset, min(chunk, size - offset))
        index = 0
        while (index := blob.find(pattern, index)) != -1:
            address = base + offset + index
            if address % 4 == 0:
                found.append(address)
            index += 4
    return found


def navigate_to_game(emulator: Dolphin, timeout: float = 300.0,
                     stable_seconds: float = 8.0) -> bool:
    """Go through logos, intro, title and file select until in-game.

    No timed sequence: alternate A and START on every controller found until a
    level is loaded. Sunshine's menus need nothing else, and this is immune to
    screen durations that vary with frame rate.

    The stop condition requires **stability over time**: the title screen
    starts an attract demo after a few seconds, during which `gpMarDirector`
    and `gpMarioOriginal` are perfectly valid. An instantaneous check wrongly
    concludes we are in game, then the demo ends and we are back at the
    title. Observed before this guard existed.
    """
    deadline = time.perf_counter() + timeout
    pads: list[int] = []
    phase = 0
    stable_since: float | None = None

    while time.perf_counter() < deadline:
        director = emulator.u32(GP_MAR_DIRECTOR)
        mario = emulator.u32(GP_MARIO)
        in_game = (emulator.is_valid_pointer(director)
                   and emulator.is_valid_pointer(mario))

        if in_game:
            now = time.perf_counter()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_seconds:
                for pad in pads:
                    emulator.write(pad + OFF_HELD, struct.pack(">II", 0, 0))
                return True
            # Inject nothing while the state holds: hammering A in game would
            # trigger jumps and dialogs.
            time.sleep(0.2)
            continue
        stable_since = None

        if not pads:
            pads = find_pads(emulator)

        # Alternate press and release: a permanently held button produces no
        # edge, and menus wait for the edge.
        phase += 1
        button = BUTTON_A if (phase // 8) % 2 == 0 else BUTTON_START
        value = button if (phase % 8) < 4 else 0
        for pad in pads:
            try:
                emulator.write(pad + OFF_HELD, struct.pack(">II", value, value))
            except Exception:
                pads = []
                break
        time.sleep(0.03)

    return False


def stop(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, check=False)


DEFAULT_USER_DIR = Path(__file__).parent.parent / "work" / "dolphin-user"


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    if argv[1] == "stop":
        # `stop` kills **every** instance found, including the user's: PIDs
        # don't tell which is which, and hitting the wrong target already
        # happened (journal, 2026-09-15). Only use when no personal session
        # is running.
        pids = running_pids()
        if not pids:
            print("aucune instance de Dolphin en cours")
        for pid in pids:
            print(f"arrêt du PID {pid}")
            stop(pid)
        return 0

    if argv[1] == "start":
        options = argv[2:]
        vi = None
        user_dir = DEFAULT_USER_DIR
        while options:
            flag = options.pop(0)
            if flag == "--vi":
                vi = float(options.pop(0))
            elif flag == "--user":
                user_dir = Path(options.pop(0))
            else:
                print(f"option inconnue : {flag}")
                return 2

        existing = running_pids()
        if existing:
            # Deliberate refusal: two instances share the GPU, so the frame
            # rate measured in one depends on the other's load. See the
            # module docstring.
            print(f"Dolphin tourne déjà (PID {sorted(existing)}).")
            print("Lancer une seconde instance fausserait toute mesure de "
                  "cadence — refus.")
            return 1

        print(f"répertoire utilisateur isolé : {user_dir}")
        prepare_user_dir(user_dir)
        pid = launch(user_dir, vi_overclock=vi)
        print(f"instance lancée, PID {pid}"
              + (f", VIOverclock = {vi}" if vi is not None else ""))

        emulator = wait_for_memory(pid)
        print(f"MEM1 localisée, jeu {emulator.game_id}")
        print("navigation vers le jeu…")
        if not navigate_to_game(emulator):
            print("le jeu n'a pas été atteint dans le délai imparti")
            return 1

        director = emulator.u32(GP_MAR_DIRECTOR)
        mario = emulator.u32(GP_MARIO)
        print(f"en jeu — gpMarDirector 0x{director:08X}, Mario 0x{mario:08X}")
        print(f"arrêter avec : python {Path(__file__).name} stop")
        return 0

    print(f"commande inconnue : {argv[1]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
