"""Free-fall regression test: does physics depend on the frame rate?

The most decisive test of the suite, and the only one that could invalidate
the whole approach at once. If the substep accumulator works, the simulation
runs at 120 Hz whatever the display rate, and a fall must take exactly the same
real time at 30 and 60 FPS. If it does not, physics is coupled to the display:
find the cause, do not edit `TJumpParams` or the `.prm` files.

Method
------
No controller input is needed, so the test is fully automatic: Mario is
teleported upward by writing his position directly, then his height is polled
until it stops decreasing.

    Mario + 0x10  f32  position X
    Mario + 0x14  f32  position Y
    Mario + 0x18  f32  position Z

Two quantities are measured:

- real fall duration: must match between rates;
- number of distinct Y values, i.e. physics integrations: should be ~120 per
  second of fall in both cases, an independent cross-check of
  `measure_substeps.py`.

The original position is restored in all cases, including on error.

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

# The fall is considered over after this long without Y decreasing.
SETTLE_SECONDS = 0.35
TIMEOUT_SECONDS = 15.0


def drop(dolphin: Dolphin, mario: int, height: float) -> dict:
    """Teleport Mario `height` units up and measure the fall."""
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

    # The fall itself ends at the last instant Y was decreasing.
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
            # Put Mario back on the ground so every drop starts from the same state.
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
