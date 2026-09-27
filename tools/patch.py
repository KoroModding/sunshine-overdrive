"""Application réversible des correctifs de framerate à un Dolphin en cours.

Écrit directement dans la MEM1 émulée. Chaque correctif enregistre la valeur
d'origine et sait la restaurer, ce qui permet d'enchaîner des mesures à
plusieurs cadences sans relancer le jeu.

Ce que ce module NE fait PAS
----------------------------
Il n'applique **aucune** des corrections d'objets (boids, boss, transitions,
fondus) recensées dans le plan de départ. Il ne pose que les deux écritures qui
définissent la cadence elle-même, plus le littéral `TModelGate` à titre
expérimental. C'est délibéré : l'objet est de mesurer le socle, pas de livrer
un mod jouable.

Le piège du cache JIT — et pourquoi on n'utilise pas le `nop`
-------------------------------------------------------------
Dolphin compile le code PowerPC en code natif et met les blocs en cache. Une
écriture externe dans une **instruction** reste sans effet tant que le bloc
concerné n'est pas recompilé, alors qu'une écriture dans une **donnée** prend
effet immédiatement puisque le jeu la relit à chaque exécution.

Mesuré le 2026-09-15 : écrire `nop` en `0x802FCB24` modifie bien la MEM1
émulée (relecture confirmée) mais **ne change rien au comportement** — le jeu
continue de présenter 30 images par seconde. Le bloc JIT compilé l'emporte.

Ce module contourne l'obstacle en n'écrivant que des **données** :

    0x804167B8        littéral f32   horloge logique + cadence d'animation
    TDisplay + 0x4C   u16            mRetraceCount, champs par présentation

`mRetraceCount = 1` produit exactement le même effet que le `nop` de
`gamemasterplc` (démontré dans docs/01-mecanismes.md § 3.1), sans toucher une
seule instruction. C'est aussi la voie que prend BetterSunshineEngine.

`TDisplay` est atteint par `gpApplication + 0x1C`, résolu à chaque appel :
l'objet est alloué sur le tas, son adresse change d'une session à l'autre.

Usage
-----
    python patch.py status
    python patch.py apply   <30|60|120>
    python patch.py restore
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

# Fichier de sauvegarde des valeurs d'origine. Persister sur disque permet de
# restaurer même après l'arrêt du script qui a appliqué le correctif.
BACKUP = Path(__file__).parent.parent / "work" / "patch-backup.json"

LITERAL_VSYNC = 0x804167B8  # 0.5f — horloge logique et cadence d'animation
LITERAL_GATE = 0x80414904  # 0.01f — fondu TModelGate

GP_APPLICATION = 0x803E9700  # gpApplication EST l'objet, pas un pointeur vers lui
OFF_DISPLAY = 0x1C  # TApplication::mDisplay
OFF_RETRACE_COUNT = 0x4C  # JDrama::TDisplay::mRetraceCount (u16)

# Valeurs par palier. Le littéral vaut `cadence / 60` : c'est lui qui fixe à la
# fois le retour de SMSGetVSyncTimesPerSec et, par ricochet, le nombre de
# sous-pas par image (600 / cadence). `retrace_count` fixe le nombre de champs
# VI consommés par image présentée.
PROFILES = {
    30: {"literal": 0.5, "retrace_count": 2, "gate": 0.01},
    60: {"literal": 1.0, "retrace_count": 1, "gate": 0.02},
    120: {"literal": 2.0, "retrace_count": 1, "gate": 0.04},
}


def display_address(dolphin: Dolphin) -> int:
    """Adresse de l'objet `JDrama::TDisplay`, résolue à chaque appel."""
    display = dolphin.u32(GP_APPLICATION + OFF_DISPLAY)
    if not dolphin.is_valid_pointer(display):
        raise RuntimeError(
            f"mDisplay invalide (0x{display:08X}) — le jeu est-il démarré ?"
        )
    return display


def read_state(dolphin: Dolphin) -> dict:
    return {
        "literal": dolphin.f32(LITERAL_VSYNC),
        "retrace_count": dolphin.u16(display_address(dolphin) + OFF_RETRACE_COUNT),
        "gate": dolphin.f32(LITERAL_GATE),
    }


def save_original(dolphin: Dolphin) -> dict:
    """Enregistre l'état d'origine, une seule fois."""
    if BACKUP.exists():
        return json.loads(BACKUP.read_text())
    state = read_state(dolphin)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(state, indent=2))
    return state


def apply(dolphin: Dolphin, fps: int, gate: bool = True) -> dict:
    """Applique un palier. Retourne l'état relu après écriture."""
    if fps not in PROFILES:
        raise ValueError(f"palier inconnu : {fps} (attendu {sorted(PROFILES)})")
    save_original(dolphin)
    profile = PROFILES[fps]

    dolphin.write_f32(LITERAL_VSYNC, profile["literal"])
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT,
        struct.pack(">H", profile["retrace_count"]),
    )
    if gate:
        dolphin.write_f32(LITERAL_GATE, profile["gate"])
    return read_state(dolphin)


def restore(dolphin: Dolphin) -> dict:
    """Remet les valeurs d'origine relevées au premier `apply`."""
    if not BACKUP.exists():
        raise RuntimeError("aucune sauvegarde : rien à restaurer")
    original = json.loads(BACKUP.read_text())
    dolphin.write_f32(LITERAL_VSYNC, original["literal"])
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT,
        struct.pack(">H", original["retrace_count"]),
    )
    dolphin.write_f32(LITERAL_GATE, original["gate"])
    return read_state(dolphin)


def describe(state: dict) -> str:
    logical = 60.0 * state["literal"]
    count = state["retrace_count"]
    quantum = int(600 / logical) if logical else "?"
    return (
        f"  littéral 0x804167B8   {state['literal']:<5g} horloge logique {logical:g} Hz, "
        f"{quantum} unités par sous-pas\n"
        f"  mRetraceCount +0x4C   {count:<5} {count} champ(s) VI par image présentée\n"
        f"  littéral 0x80414904   {state['gate']:<5g} fondu TModelGate"
    )


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    dolphin = Dolphin()
    command = argv[1]

    if command == "status":
        print(f"Jeu : {dolphin.game_id}")
        print(describe(read_state(dolphin)))
        if BACKUP.exists():
            print(f"\nSauvegarde présente : {BACKUP}")

    elif command == "apply":
        fps = int(argv[2])
        state = apply(dolphin, fps)
        print(f"Palier {fps} FPS appliqué :")
        print(describe(state))

    elif command == "restore":
        state = restore(dolphin)
        print("État d'origine restauré :")
        print(describe(state))

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
