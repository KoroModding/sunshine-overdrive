"""Test de régression « chute libre » — la physique dépend-elle de la cadence ?

C'est le test le plus décisif de la batterie du plan de départ, et le seul qui
puisse invalider d'un coup toute la démarche. Si l'accumulateur de sous-pas
fait son travail, la simulation tourne à 120 Hz quelle que soit la cadence
d'affichage, et **une chute doit durer exactement le même temps réel à 30 et à
60 FPS**.

Si la durée change, la physique est couplée à l'affichage. Dans ce cas —
et le plan de départ insiste sur ce point — il ne faut surtout pas corriger en
retouchant `TJumpParams` ou les `.prm` : c'est la cause qu'il faut chercher.

Méthode
-------
Aucune entrée manette n'est nécessaire, ce qui rend le test entièrement
automatisable : on téléporte Mario en hauteur par écriture directe de sa
position, puis on sonde son altitude jusqu'à ce qu'elle cesse de décroître.

    Mario + 0x10  f32  position X
    Mario + 0x14  f32  position Y
    Mario + 0x18  f32  position Z

Deux grandeurs sont relevées :

- **durée réelle de la chute** — doit être identique entre cadences ;
- **nombre de valeurs distinctes de Y** — c'est le nombre d'intégrations de la
  physique. Il doit valoir ~120 par seconde de chute dans les deux cas, ce qui
  recoupe indépendamment la mesure de `measure_substeps.py`.

La position d'origine est restaurée dans tous les cas, y compris en cas
d'erreur.

Usage
-----
    python test_freefall.py [hauteur] [palier…]
    python test_freefall.py 3000 30 60
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import patch  # noqa: E402
from dolphin import Dolphin  # noqa: E402

GP_MARIO = 0x8040E0E8
OFF_POS_Y = 0x14

# Au-delà de cette durée sans décroissance de Y, on considère la chute finie.
SETTLE_SECONDS = 0.35
TIMEOUT_SECONDS = 15.0


def drop(dolphin: Dolphin, mario: int, height: float) -> dict:
    """Téléporte Mario `height` unités plus haut et mesure sa chute."""
    y_address = mario + OFF_POS_Y
    start_y = dolphin.f32(y_address)
    dolphin.write_f32(y_address, start_y + height)

    samples: list[tuple[float, float]] = []
    distinct: list[float] = []
    previous = None
    last_decrease = time.perf_counter()
    start = last_decrease

    while True:
        now = time.perf_counter()
        y = dolphin.f32(y_address)

        if y != previous:
            distinct.append(y)
            samples.append((now - start, y))
            if previous is not None and y < previous:
                last_decrease = now
            previous = y

        if now - last_decrease > SETTLE_SECONDS:
            break
        if now - start > TIMEOUT_SECONDS:
            break

    # La chute proprement dite s'arrête au dernier instant où Y décroissait.
    duration = last_decrease - start
    descending = [s for s in samples if s[0] <= duration]

    return {
        "duration": duration,
        "updates": len(descending),
        "start_y": start_y + height,
        "end_y": distinct[-1] if distinct else start_y,
        "rate": len(descending) / duration if duration else 0.0,
    }


def _main(argv: list[str]) -> int:
    height = float(argv[1]) if len(argv) > 1 else 3000.0
    tiers = [int(a) for a in argv[2:]] or [30, 60]

    dolphin = Dolphin()
    mario = dolphin.u32(GP_MARIO)
    if not dolphin.is_valid_pointer(mario):
        print(f"gpMarioOriginal invalide (0x{mario:08X}) — le jeu est-il dans un niveau ?")
        return 1

    y_address = mario + OFF_POS_Y
    original_y = dolphin.f32(y_address)
    print(f"Mario 0x{mario:08X}, Y d'origine {original_y:g}, chute de {height:g} unités")
    print()
    print(f"{'palier':>7}  {'durée réelle':>13}  {'intégrations':>13}  "
          f"{'par seconde':>12}  {'chute':>10}")
    print("-" * 64)

    results = {}
    try:
        for fps in tiers:
            patch.apply(dolphin, fps, gate=False)
            time.sleep(0.6)
            # Remettre Mario au sol avant de le relâcher, pour partir du même
            # état dans chaque essai.
            dolphin.write_f32(y_address, original_y)
            time.sleep(0.6)

            result = drop(dolphin, mario, height)
            results[fps] = result
            print(f"{fps:>5} FPS  {result['duration']:>11.3f} s  "
                  f"{result['updates']:>13}  {result['rate']:>10.1f}/s  "
                  f"{result['start_y'] - result['end_y']:>10.1f}")
    finally:
        patch.restore(dolphin)
        time.sleep(0.4)
        dolphin.write_f32(y_address, original_y)
        print()
        print("Position et correctifs restaurés.")

    if len(results) >= 2:
        a, b = list(results)[0], list(results)[-1]
        da, db = results[a]["duration"], results[b]["duration"]
        drift = abs(da - db) / da * 100 if da else 0
        print()
        print(f"Écart de durée {a} FPS vs {b} FPS : {drift:.2f} %")
        if drift < 5:
            print("=> la physique est INDÉPENDANTE de la cadence. "
                  "L'accumulateur fait son travail.")
        else:
            print("=> la physique DÉPEND de la cadence. Ne pas corriger les .prm : "
                  "chercher la cause.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
