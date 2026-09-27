"""Installation réversible du profil 120 FPS dans le répertoire utilisateur de
Dolphin.

Ce que ce module fait
---------------------
Il recopie `deliver/GMSE01.ini` dans `<user>/GameSettings/GMSE01.ini`. Dolphin
lit ce fichier **au démarrage du jeu**, et ses sections s'ajoutent à celles de
`Sys/GameSettings/GMSE01.ini` — l'INI livré avec Dolphin n'est jamais modifié.

Ce que ce module NE fait PAS
----------------------------
Il ne touche pas `Config/Dolphin.ini`. Le réglage d'overclock VI est porté par
le profil par jeu, pas par la configuration globale : hors Sunshine, rien ne
change.

Il ne prend pas effet sur une partie déjà lancée. `VIOverclock` est un réglage
d'hôte lu à l'amorçage, et les lignes Gecko sont posées avant que le jeu ne
tourne. **Il faut démarrer le jeu après l'installation**, pas avant.

Limite connue
-------------
Si Dolphin est ouvert et que l'utilisateur édite les propriétés du jeu par
l'interface, Dolphin réécrit ce fichier et peut perdre les commentaires. Le
contenu fonctionnel, lui, survit : Dolphin conserve les clés qu'il comprend.

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

MARKERS = ("Sunshine Overdrive", "Framerate Sunshine")   # nom actuel, ancien nom


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

    # Un GMSE01.ini préexistant est mis de côté une seule fois : réinstaller
    # par-dessus le profil ne doit pas écraser la sauvegarde d'origine.
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
