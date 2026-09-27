"""Seconde instance de Dolphin, isolée, pour les réglages qui exigent un
redémarrage.

Le problème
-----------
Le palier 120 FPS exige que le VI émulé délivre plus de 59,94 champs par
seconde, c'est-à-dire le **VBI Frequency Override** de Dolphin. Ce réglage vit
dans l'hôte, pas dans la MEM1 : aucune écriture mémoire ne l'atteint, et
Dolphin ne relit pas sa configuration en cours de partie.

Deux voies ont été écartées avant celle-ci :

- **Envoyer le raccourci de sauvegarde d'état à Dolphin puis le relancer.**
  Impossible : `SendInput` n'atteint pas le bureau interactif depuis ce
  contexte — vérifié, même `GetAsyncKeyState` dans le processus appelant ne
  voit pas la frappe injectée. Toute automatisation clavier est exclue.
- **Modifier la configuration de Dolphin et le relancer.** Cela détruirait la
  session en cours de l'utilisateur.

La solution retenue
-------------------
Lancer une **seconde instance** avec son propre répertoire utilisateur
(`--user`), son propre réglage d'overclock (`--config`) et une copie de la
carte mémoire. L'instance de l'utilisateur n'est jamais touchée : ni sa
configuration, ni sa sauvegarde, ni sa partie en cours.

La navigation dans les menus se fait par la même injection mémoire que le reste
du projet (`pad.py`) — qui, elle, ne dépend pas du clavier. Il n'y a même pas de
séquence à minuter : marteler A et START jusqu'à ce que `gpMarDirector` et
`gpMarioOriginal` deviennent valides suffit à traverser logos, intro, écran
titre et sélection de fichier.

État — voie en attente
----------------------
Le mécanisme est complet et **vérifié jusqu'à l'entrée en jeu** : instance
lancée avec `VIOverclock = 2.0`, logos, intro, écran titre et sélection de
fichier traversés sans intervention, arrivée stable en jeu en 92,6 s (relevé du
2026-09-15, [`docs/00-journal.md`](../docs/00-journal.md)). La mesure du palier
120 elle-même n'a **pas** été faite : la session s'est arrêtée là.

Sur décision de l'auteur du projet (2026-09-17), **ce module ne doit pas être
lancé sans accord explicite**. Deux instances de Dolphin côte à côte se
disputent le GPU et faussent toute mesure de cadence de l'instance de
l'utilisateur. Il est conservé complet pour le jour où la mesure sera reprise.

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

# Chemins locaux : variables d'environnement, sinon valeurs par défaut.
#   DOLPHIN_EXE       exécutable de Dolphin            (défaut : « Dolphin.exe » dans le PATH)
#   DOLPHIN_USER_DIR  répertoire utilisateur de Dolphin (défaut : %APPDATA%/Dolphin Emulator)
#   SMS_ISO           image du jeu GMSE01              (défaut : aucun, à fournir)
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
    """Répertoire utilisateur isolé, avec la configuration et la carte mémoire
    de l'utilisateur recopiées.

    La configuration est copiée pour que la seconde instance rende dans les
    mêmes conditions que la première (même backend, mêmes réglages graphiques) :
    une comparaison de framerate n'aurait pas de sens sinon. La carte mémoire
    est copiée pour pouvoir charger une partie existante plutôt que d'avoir à
    traverser l'introduction complète.
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
    """Lance l'instance et retourne son PID."""
    before = running_pids()
    command = [
        str(DOLPHIN_EXE), "-u", str(user_dir), "-e", str(ISO), "-b",
        "-C", "Dolphin.DSP.Volume=0",  # ne pas doubler le son de l'utilisateur
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
    """Instances de `TMarioGamePad`, repérées par leur pointeur de vtable.

    Le passage par la vtable est nécessaire ici : la résolution habituelle
    (`TMario + 0x4FC`) suppose que Mario existe, ce qui n'est pas le cas dans
    les menus.
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
    """Traverse logos, intro, titre et sélection de fichier jusqu'au jeu.

    Aucune séquence minutée : on alterne A et START sur toutes les manettes
    trouvées jusqu'à ce qu'un niveau soit chargé. Les menus de Sunshine ne
    demandent rien d'autre, et cette approche est insensible aux durées
    d'écran qui varient avec la cadence.

    Le critère d'arrêt exige une **stabilité dans la durée**, et ce n'est pas
    une précaution superflue : l'écran titre de Sunshine lance une démo
    d'attraction au bout de quelques secondes. Pendant celle-ci, `gpMarDirector`
    et `gpMarioOriginal` sont parfaitement valides — un test instantané conclut
    donc à tort qu'on est en jeu, puis la démo s'arrête et l'on se retrouve
    devant le titre. Constaté avant que ce garde-fou n'existe.
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
            # Ne rien injecter tant que l'état tient : marteler A pendant une
            # partie déclencherait sauts et dialogues.
            time.sleep(0.2)
            continue
        stable_since = None

        if not pads:
            pads = find_pads(emulator)

        # Alterner pression et relâchement : un bouton maintenu en permanence
        # ne produit aucun front, et c'est le front que les menus attendent.
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
        # `stop` arrête **toutes** les instances trouvées, y compris celle de
        # l'utilisateur : les PID ne disent pas laquelle est laquelle, et se
        # tromper de cible a déjà eu lieu (journal du 2026-09-15). À n'utiliser
        # que quand aucune session personnelle ne tourne.
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
            # Refus délibéré. Deux instances se partagent le GPU ; la cadence
            # mesurée dans l'une dépend alors de la charge de l'autre, ce qui
            # ôte tout sens à la mesure. Voir l'en-tête du module.
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
