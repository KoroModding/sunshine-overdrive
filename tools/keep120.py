"""Maintien du palier 120 FPS sur un Dolphin en cours d'exécution.

Pourquoi un processus résident plutôt qu'un code Gecko
-----------------------------------------------------
Le profil `deliver/GMSE01.ini` ne porte que la moitié hôte du réglage —
l'overclock VI. La moitié côté jeu passe par deux écritures dans la MEM1, pas
par la section `[Gecko]` de Dolphin.

Ce n'est pas un choix d'élégance, c'est un constat : le 2026-09-22, un
`[Gecko]` en règle dans le profil par jeu **n'a pas été chargé** — Dolphin
n'avait injecté aucun codehandler (0x80001800 entièrement nul) alors que le
`[Core]` du même fichier, lui, avait bien pris effet. Cause non élucidée.

Les écritures de données, elles, sont éprouvées depuis la session 2 et ne se
heurtent pas au cache JIT, contrairement au `nop` de `gamemasterplc` :

    0x804167B8        f32   0.5f -> 2.0f   horloge logique à 120 Hz
    TDisplay + 0x4C   u16   2    -> 1      un champ VI par image présentée

Ce que ce module surveille
--------------------------
Il ne se contente pas d'écrire une fois. Il vérifie en boucle que les deux
valeurs tiennent, et les repose si elles dérivent — au redémarrage du jeu, ou
si `TDisplay` est réalloué. L'adresse de `TDisplay` est résolue à chaque tour
par `gpApplication + 0x1C` : elle vit sur le tas et change d'une session à
l'autre.

Il applique le réglage **dès que `TDisplay` existe**, c'est-à-dire bien avant
l'entrée dans un niveau. C'est voulu : tant qu'il n'est pas posé et que le VI
tourne à 2×, le jeu s'exécute à double vitesse.

Ce qu'il ne fait pas
--------------------
Aucune correction d'objet. Les nuées d'oiseaux, le boss anguille, les minuteurs
de dialogue, les transitions et les fondus restent non corrigés — voir
`deliver/README.md`.

Il ne touche pas non plus au littéral `0x80414904` (fondu `TModelGate`) :
l'anomalie du § 4.3 de `docs/01-mecanismes.md` n'est pas tranchée.

Usage
-----
    python keep120.py            # résident, Ctrl+C pour rendre la main
    python keep120.py --once     # une seule passe
    python keep120.py --restore  # remet 30 FPS (0.5f, 2 champs)
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

LITERAL_VSYNC = 0x804167B8
GP_APPLICATION = 0x803E9700
OFF_DISPLAY = 0x1C
OFF_RETRACE_COUNT = 0x4C

PATCH_SITE_RETRACE = 0x802FCB24  # bl VIWaitForRetrace, final de waitForRetrace
NOP = 0x60000000

# (littéral, mRetraceCount). Le compte suppose l'attente finale INTACTE ; si
# elle a été neutralisée par `deliver/GMSE01.ini`, `target_count` le corrige.
PROFILES = {
    30: (0.5, 2),
    60: (1.0, 1),
    120: (2.0, 1),
}


def target_count(dolphin: Dolphin, count: int) -> int:
    """Corrige le compte si l'attente finale a été neutralisée à l'amorçage.

    Les deux correctifs se cumulent, et leur cumul est dangereux. Le § 3.1 de
    docs/01-mecanismes.md le dit : neutralisée, `waitForRetrace` consomme
    `count - 1` champs par appel. Avec `count = 1` cela fait **zéro** — plus
    aucune attente de balayage, le jeu s'emballe à la vitesse de l'hôte.

    Quand le `nop` est là, il porte déjà à lui seul la présentation par champ :
    le compte doit rester à sa valeur NTSC de 2.
    """
    if dolphin.u32(PATCH_SITE_RETRACE) == NOP:
        return count + 1
    return count


def display_address(dolphin: Dolphin) -> int | None:
    """`JDrama::TDisplay`, ou None tant qu'il n'est pas construit."""
    display = dolphin.u32(GP_APPLICATION + OFF_DISPLAY)
    return display if dolphin.is_valid_pointer(display) else None


def read_state(dolphin: Dolphin) -> tuple[float, int] | None:
    display = display_address(dolphin)
    if display is None:
        return None
    return dolphin.f32(LITERAL_VSYNC), dolphin.u16(display + OFF_RETRACE_COUNT)


def enforce(dolphin: Dolphin, fps: int) -> tuple[bool, str]:
    """Pose le palier si besoin. Retourne (une écriture a eu lieu, message)."""
    literal, count = PROFILES[fps]
    count = target_count(dolphin, count)
    state = read_state(dolphin)
    if state is None:
        return False, "TDisplay pas encore construit"

    current_literal, current_count = state
    if abs(current_literal - literal) < 1e-6 and current_count == count:
        return False, f"en place ({current_literal:g}f, {current_count} champ)"

    dolphin.write_f32(LITERAL_VSYNC, literal)
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT, struct.pack(">H", count)
    )
    return True, (
        f"posé : {current_literal:g}f/{current_count} -> {literal:g}f/{count}"
    )


def _main(argv: list[str]) -> int:
    fps = 30 if "--restore" in argv else 120
    once = "--once" in argv or "--restore" in argv

    try:
        dolphin = Dolphin()
    except (RuntimeError, OSError) as error:
        # En résident, l'absence de jeu n'est pas une erreur : c'est l'état
        # normal quand on lance le mainteneur avant de démarrer la partie.
        if once:
            print(error)
            return 1
        print("Aucun jeu démarré — en attente.")
        dolphin = None

    if dolphin is not None:
        print(f"Dolphin PID {dolphin.pid}, jeu {dolphin.game_id}")
        if dolphin.game_id[:6] != "GMSE01":
            print(
                f"  ATTENTION : profil prévu pour GMSE01, jeu chargé "
                f"{dolphin.game_id}"
            )

    if once:
        written, message = enforce(dolphin, fps)
        print(f"palier {fps} : {message}")
        return 0 if written or "en place" in message else 1

    print(f"Maintien du palier {fps} FPS. Ctrl+C pour rendre la main.")
    last_message = ""
    try:
        while True:
            try:
                if dolphin is None:
                    raise RuntimeError("pas encore rattaché")
                written, message = enforce(dolphin, fps)
            except (RuntimeError, OSError):
                # Le jeu a été arrêté, ou redémarré. Dans le second cas la MEM1
                # est reprojetée ailleurs et le handle mis en cache ne vaut
                # plus rien : on se rattache plutôt que d'abandonner. C'est le
                # cas normal d'un redémarrage pour appliquer le profil hôte.
                written = False
                try:
                    dolphin = Dolphin()
                    message = f"rattaché à {dolphin.game_id}"
                except (RuntimeError, OSError):
                    message = "en attente d'un jeu démarré…"
            if written or message != last_message:
                print(f"  [{time.strftime('%H:%M:%S')}] {message}")
                last_message = message
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nArrêt. Le palier reste posé ; `--restore` pour revenir à 30 FPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
