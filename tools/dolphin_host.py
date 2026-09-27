"""Pilotage de l'hôte Dolphin : save states et relance avec configuration.

Pourquoi ce module existe
-------------------------
Le palier 120 FPS exige que le VI émulé délivre plus de 59,94 champs par
seconde. C'est le réglage **VBI Frequency Override** de Dolphin
(`Dolphin.Core.VIOverclock`). Or ce réglage vit dans l'hôte, pas dans la MEM1 :
aucune écriture mémoire ne l'atteint, et Dolphin ne relit pas son fichier de
configuration en cours de partie.

La seule voie qui ne demande rien à personne est donc : sauvegarder l'état,
relancer Dolphin avec le réglage passé en ligne de commande, recharger l'état.

Ce que la ligne de commande de Dolphin offre
--------------------------------------------
Relevé dans le binaire (`Dolphin.exe`) :

    --exec / -e        <chemin>                       image à lancer
    --save_state / -s  <chemin>                       état à charger au démarrage
    --config / -C      <Système>.<Section>.<Clé>=<Valeur>

Les clés utiles :

    Dolphin.Core.VIOverclockEnable = True
    Dolphin.Core.VIOverclock       = 2.0

`-C` alimente une couche « ligne de commande » qui **n'est pas écrite** dans
`Dolphin.ini` : relancer sans l'option suffit à revenir à l'état initial, la
configuration de l'utilisateur n'est jamais modifiée.

La sauvegarde d'état — impasse constatée
----------------------------------------
Dolphin ne sait pas créer un état depuis la ligne de commande : il faut lui
envoyer son raccourci (Maj+F1 par défaut). Ses entrées passant par DirectInput,
un `PostMessage` ne suffit pas — il faut une injection au niveau du système
(`SendInput`), donc donner brièvement le focus à sa fenêtre.

**Cette voie ne fonctionne pas depuis un agent en ligne de commande.** Mesuré
le 2026-09-15 : `SendInput` n'atteint pas le bureau interactif depuis ce
contexte — même `GetAsyncKeyState`, appelé dans le processus qui vient
d'injecter la frappe, ne la voit pas. Ni le focus forcé, ni le choix de la
fenêtre (rendu ou principale) n'y changent quoi que ce soit.

`savestate` est conservé parce qu'il redevient utilisable dans une session
lancée à la main par l'utilisateur, et parce qu'il rapporte honnêtement son
échec plutôt que de le masquer. Mais rien dans le projet ne doit en dépendre.

La voie qui a fonctionné pour le même besoin est
[`second_instance.py`](second_instance.py) : une instance isolée, pilotée par
la même injection mémoire que le reste du projet, qui ne dépend d'aucun
clavier.

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

# Chemins locaux : variables d'environnement, sinon valeurs par défaut.
#   DOLPHIN_EXE       exécutable de Dolphin            (défaut : « Dolphin.exe » dans le PATH)
#   DOLPHIN_USER_DIR  répertoire utilisateur de Dolphin (défaut : %APPDATA%/Dolphin Emulator)
#   SMS_ISO           image du jeu GMSE01              (défaut : aucun, à fournir)
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
    """Donne le focus à `hwnd` malgré le verrou de premier plan de Windows.

    Windows refuse `SetForegroundWindow` à un processus qui n'est pas déjà au
    premier plan — mesuré ici : l'appel direct renvoie 0 et ne change rien.
    La parade classique est de rattacher temporairement la file d'entrée du
    thread appelant à celle du thread propriétaire de la fenêtre active, ce qui
    fait considérer les deux comme un même « contexte d'entrée » et lève la
    restriction. Le rattachement est défait aussitôt après.
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
    """Fenêtre principale visible du processus `pid`."""
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
    # La fenêtre de rendu est celle dont le titre porte l'identifiant du jeu ;
    # les autres (liste de jeux, boîtes de réglages) n'ont pas les raccourcis.
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
    """Déclenche Maj+F<slot> dans Dolphin et attend l'apparition du fichier.

    Retourne le chemin de l'état créé, ou None si rien n'est apparu.
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
    # Laisser Dolphin finir d'écrire le fichier avant de le déclarer utilisable.
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
    """Relance Dolphin, éventuellement avec un overclock VI et un état à charger."""
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
    """Attend que la MEM1 soit localisable et qu'un niveau soit chargé."""
    sys.path.insert(0, str(Path(__file__).parent))
    from dolphin import Dolphin  # import tardif : le processus doit exister

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
        # Relance de l'instance de l'utilisateur : elle **détruit** la partie
        # en cours si aucun état n'a été sauvegardé au préalable. À n'appeler
        # qu'en connaissance de cause.
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
