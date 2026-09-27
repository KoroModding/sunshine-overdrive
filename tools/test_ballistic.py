"""Gravity measurement: imposed ballistic arc, no input and no ground contact.

Why
---
Measuring jump height by pressing A is misleading. The result then depends on
three things unrelated to physics: input injection (a race with a variable
success rate), which jump fires (single, double, triple, identifiable by their
initial `vy`), and the terrain under Mario. Observed: the same jump gave 73.79
then 96.60 depending on where Mario stood, with the exact same initial impulse
(`vy` = 42.0).

This test removes all three. Mario is placed high up, his vertical speed is
written directly, and the arc is observed. Only the integrator remains.

Measured
--------
- per-substep vertical speed sequence (gravity itself; two tiers must produce
  the same sequence);
- number of integrations up to the apex;
- apex height.

All three are independent of terrain and display. If they match between tiers,
physics is decoupled from the frame rate and no change to `TJumpParams` or the
`.prm` files is justified.

Usage
-----
    python test_ballistic.py [impulsion] [palier…]
    python test_ballistic.py 42 30 60
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import patch  # noqa: E402
from dolphin import Dolphin  # noqa: E402
from substep_clock import SubstepClock  # noqa: E402

GP_MARIO = 0x8040E0E8
OFF_POS = 0x10
OFF_VEL = 0xA4

LAUNCH_HEIGHT = 2500.0  # high enough for the whole arc to happen in the air


def arc(dolphin: Dolphin, clock: SubstepClock, mario: int,
        home: tuple[float, float, float], impulse: float, substeps: int):
    """Impose a vertical speed high up and record the resulting arc."""
    launch = (home[0], home[1] + LAUNCH_HEIGHT, home[2])
    dolphin.write(mario + OFF_POS, struct.pack(">fff", *launch))
    dolphin.write(mario + OFF_VEL, struct.pack(">fff", 0.0, 0.0, 0.0))
    time.sleep(0.35)

    # Reposition right before launch: the fall started during the wait.
    dolphin.write(mario + OFF_POS, struct.pack(">fff", *launch))
    dolphin.write(mario + OFF_VEL, struct.pack(">fff", 0.0, impulse, 0.0))

    def probe():
        raw = dolphin.read(mario + OFF_POS, 12)
        vel = dolphin.read(mario + OFF_VEL, 12)
        return struct.unpack(">f", raw[4:8])[0], struct.unpack(">f", vel[4:8])[0]

    samples, valid = clock.sample_while(substeps, probe)

    # Polling is far faster than the simulation and sees each value hundreds
    # of times; keep one entry per change.
    speeds: list[float] = []
    for _, vy in samples:
        if not speeds or vy != speeds[-1]:
            speeds.append(round(vy, 4))
    heights = [y for y, _ in samples]

    rising = 0
    for value in speeds:
        if value <= 0:
            break
        rising += 1

    return {
        "speeds": speeds,
        "peak": max(heights) - launch[1],
        "rising_steps": rising,
        "valid": valid,
    }


def _main(argv: list[str]) -> int:
    impulse = float(argv[1]) if len(argv) > 1 else 42.0
    tiers = [int(a) for a in argv[2:]] or [30, 60]

    dolphin = Dolphin()
    clock = SubstepClock(dolphin)
    mario = dolphin.u32(GP_MARIO)
    if not dolphin.is_valid_pointer(mario):
        print("Mario introuvable — le jeu est-il dans un niveau ?")
        return 1
    home = struct.unpack(">fff", dolphin.read(mario + OFF_POS, 12))

    print(f"Mario 0x{mario:08X} — impulsion verticale imposée : {impulse:g}")
    print(f"lâcher à {LAUNCH_HEIGHT:g} unités au-dessus de "
          f"({home[0]:g}, {home[1]:g}, {home[2]:g})")
    print()

    results: dict[int, dict] = {}
    try:
        for fps in tiers:
            patch.apply(dolphin, fps, gate=False)
            time.sleep(0.8)
            results[fps] = arc(dolphin, clock, mario, home, impulse, 90)
            row = results[fps]
            print(f"{fps:>3} FPS  sommet {row['peak']:8.2f}   "
                  f"{row['rising_steps']:>3} intégrations en montée   "
                  f"{len(row['speeds']):>3} vitesses distinctes   "
                  f"{'sondage OK' if row['valid'] else 'SONDAGE EN DÉFAUT'}")
    finally:
        patch.restore(dolphin)
        time.sleep(0.4)
        dolphin.write(mario + OFF_POS, struct.pack(">fff", *home))
        dolphin.write(mario + OFF_VEL, struct.pack(">fff", 0.0, 0.0, 0.0))
        print()
        print("Correctifs et position restaurés.")

    if len(results) >= 2:
        first, last = list(results)[0], list(results)[-1]
        a, b = results[first]["speeds"], results[last]["speeds"]
        print()
        print(f"suite vy à {first} FPS : {a[:18]}")
        print(f"suite vy à {last} FPS : {b[:18]}")
        print()
        n = min(len(a), len(b))
        if a[:n] == b[:n]:
            print(f"=> suites IDENTIQUES sur {n} intégrations. "
                  "La gravité ne dépend pas de la cadence.")
        else:
            index = next(i for i in range(n) if a[i] != b[i])
            print(f"=> DIVERGENCE à l'intégration {index} : "
                  f"{first} FPS = {a[index]}, {last} FPS = {b[index]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
