"""Phase 0 — mesure du compte de sous-pas par sondage de l'accumulateur.

Principe
--------
`TMarDirector::direct()` maintient en `this+0x54` un accumulateur en virgule
fixe : il y ajoute `vsyncRate` une fois par image rendue, puis lui soustrait 5
à chaque sous-pas jusqu'à passer sous 5.

    +vsyncRate   -> début d'une image rendue
    -5           -> un sous-pas

Sonder cette seule valeur assez vite suffit donc à compter les deux. À 30 FPS
un sous-pas dure ~2,1 ms alors que le sondage tourne à ~2,5 µs : la marge est
de trois ordres de grandeur.

Auto-validation
---------------
C'est ce qui rend la mesure fiable sans injecter de code. Si le sondage rate
une transition, l'écart observé n'est plus 5 mais 10 ou 15. Le script vérifie
donc que **tout décrément vaut exactement 5** et que **tout incrément vaut
exactement la même valeur**. Si une seule transition anormale apparaît, la
mesure est déclarée non valide plutôt que rapportée.

Cette approche ne demande ni point d'arrêt, ni hook, ni modification du code —
donc rien qui puisse se heurter au cache JIT de Dolphin.

Usage
-----
    python measure_substeps.py [durée-en-secondes]
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MAR_DIRECTOR = 0x8040E178
OFF_ACCUMULATOR = 0x54
OFF_FLAGS = 0x4C

LITERAL_VSYNC = 0x804167B8  # 0.5f -> horloge logique
LITERAL_60HZ = 0x804167D8
PATCH_SITE_RETRACE = 0x802FCB24  # bl VIWaitForRetrace


def sample(dolphin: Dolphin, address: int, duration: float):
    """Sonde `address` pendant `duration` secondes.

    Retourne la liste des transitions (instant, ancienne valeur, nouvelle
    valeur) et le nombre total de lectures effectuées.
    """
    transitions = []
    reads = 0
    previous = dolphin.s32(address)
    start = time.perf_counter()
    deadline = start + duration

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break
        value = dolphin.s32(address)
        reads += 1
        if value != previous:
            transitions.append((now - start, previous, value))
            previous = value

    return transitions, reads, time.perf_counter() - start


def analyse(transitions, elapsed: float) -> dict:
    """Classe les transitions et vérifie la cohérence de l'échantillonnage."""
    decrements = [t for t in transitions if t[2] < t[1]]
    increments = [t for t in transitions if t[2] > t[1]]

    steps_down = Counter(t[1] - t[2] for t in decrements)
    steps_up = Counter(t[2] - t[1] for t in increments)

    # Un sondage complet ne voit que des décréments de 5 et des incréments
    # tous égaux à vsyncRate.
    valid = set(steps_down) <= {5} and len(steps_up) <= 1

    return {
        "substeps": len(decrements),
        "frames": len(increments),
        "steps_down": steps_down,
        "steps_up": steps_up,
        "vsync_rate": next(iter(steps_up), None) if len(steps_up) == 1 else None,
        "valid": valid,
        "elapsed": elapsed,
        "values": Counter(t[2] for t in transitions),
    }


def _main(argv: list[str]) -> int:
    duration = float(argv[1]) if len(argv) > 1 else 5.0
    dolphin = Dolphin()

    director = dolphin.u32(GP_MAR_DIRECTOR)
    if not dolphin.is_valid_pointer(director):
        print(f"gpMarDirector invalide (0x{director:08X}) — le jeu est-il dans un niveau ?")
        return 1

    literal = dolphin.f32(LITERAL_VSYNC)
    base_hz = dolphin.f32(LITERAL_60HZ)
    logical_hz = base_hz * literal
    expected_rate = int(600 / logical_hz) if logical_hz else 0
    retrace = dolphin.u32(PATCH_SITE_RETRACE)

    print(f"TMarDirector        0x{director:08X}")
    print(f"littéral vsync      {literal!r}  ->  horloge logique {logical_hz:g} Hz")
    print(f"vsyncRate attendu   600 / {logical_hz:g} = {expected_rate}")
    print(f"0x802FCB24          0x{retrace:08X} "
          f"({'nop — présentation par champ' if retrace == 0x60000000 else 'bl VIWaitForRetrace — intact'})")
    print()
    print(f"Sondage de 0x{director + OFF_ACCUMULATOR:08X} pendant {duration:g} s…")

    transitions, reads, elapsed = sample(
        dolphin, director + OFF_ACCUMULATOR, duration
    )
    result = analyse(transitions, elapsed)

    print(f"{reads:,} lectures, {len(transitions):,} transitions".replace(",", " "))
    print()

    if not transitions:
        print("Aucune transition : le jeu est en pause, ou dans un état sans simulation.")
        return 1

    print(f"Décréments observés : {dict(result['steps_down'])}")
    print(f"Incréments observés : {dict(result['steps_up'])}")
    print()

    if not result["valid"]:
        print("MESURE NON VALIDE — des transitions inattendues ont été observées.")
        print("Le sondage a probablement manqué des étapes, ou le modèle est faux.")
        return 1

    substeps = result["substeps"]
    frames = result["frames"]
    print(f"vsyncRate mesuré       {result['vsync_rate']}   "
          f"(attendu {expected_rate})")
    print(f"images rendues         {frames}      -> {frames / elapsed:6.2f} /s")
    print(f"sous-pas               {substeps}      -> {substeps / elapsed:6.2f} /s")
    if frames:
        print(f"sous-pas / image       {substeps / frames:.3f}")
    print()
    print(f"valeurs prises par l'accumulateur : "
          f"{sorted(result['values'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
