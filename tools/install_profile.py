"""Reversible install of the 120 FPS profile into Dolphin's user directory.

Copies `deliver/GMSE01.ini` to `<user>/GameSettings/GMSE01.ini`. Dolphin reads
this file when the game starts, and its sections are merged with those of
`Sys/GameSettings/GMSE01.ini`; the INI shipped with Dolphin is never modified.

`Config/Dolphin.ini` is not touched. The VI overclock setting lives in the
per-game profile, not the global configuration: nothing changes outside
Sunshine.

It does not affect a game already running. `VIOverclock` is a host setting
read at boot, and the patch lines are applied before the game runs. Start the
game after installing, not before.

Known limitation: if Dolphin is open and the user edits the game properties
through the UI, Dolphin rewrites this file and may drop the comments. The
functional content survives: Dolphin keeps the keys it understands.

Usage
-----
    python install_profile.py status
    python install_profile.py install
    python install_profile.py uninstall
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "deliver" / "GMSE01.ini"
_APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
USER_DIR = Path(os.environ.get("DOLPHIN_USER_DIR", _APPDATA / "Dolphin Emulator"))
TARGET = USER_DIR / "GameSettings" / "GMSE01.ini"
BACKUP = ROOT / "work" / "GMSE01.ini.avant-installation"

MARKERS = ("Sunshine Overdrive", "Framerate Sunshine")   # current name, old name


def installed() -> bool:
    return TARGET.exists() and any(m in TARGET.read_text(encoding="utf-8") for m in MARKERS)


def install() -> None:
    if not SOURCE.exists():
        raise RuntimeError(f"profil introuvable : {SOURCE}")
    if not USER_DIR.exists():
        raise RuntimeError(
            f"répertoire utilisateur de Dolphin introuvable : {USER_DIR}"
        )
    TARGET.parent.mkdir(parents=True, exist_ok=True)

    # A pre-existing GMSE01.ini is backed up only once: reinstalling over the
    # profile must not overwrite the original backup.
    if TARGET.exists() and not installed() and not BACKUP.exists():
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TARGET, BACKUP)
        print(f"INI utilisateur préexistant sauvegardé -> {BACKUP}")

    shutil.copy2(SOURCE, TARGET)
    print(f"Profil 120 FPS installé -> {TARGET}")
    print("Démarrer (ou redémarrer) le jeu pour qu'il prenne effet.")


def uninstall() -> None:
    if not TARGET.exists():
        print("rien à désinstaller")
        return
    if not installed():
        print(f"{TARGET} n'est pas le profil du projet — laissé intact")
        return
    if BACKUP.exists():
        shutil.copy2(BACKUP, TARGET)
        print(f"INI d'origine restauré <- {BACKUP}")
    else:
        TARGET.unlink()
        print(f"Profil retiré : {TARGET}")
    print("Redémarrer le jeu pour revenir à 30 FPS.")


def status() -> None:
    print(f"source     {SOURCE}   {'présente' if SOURCE.exists() else 'ABSENTE'}")
    print(f"cible      {TARGET}")
    if not TARGET.exists():
        print("état       non installé")
    elif installed():
        print("état       INSTALLÉ (profil 120 FPS du projet)")
    else:
        print("état       un autre GMSE01.ini occupe la place")
    if BACKUP.exists():
        print(f"sauvegarde {BACKUP}")


def _main(argv: list[str]) -> int:
    commands = {"status": status, "install": install, "uninstall": uninstall}
    if len(argv) < 2 or argv[1] not in commands:
        print(__doc__)
        return 2
    commands[argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
