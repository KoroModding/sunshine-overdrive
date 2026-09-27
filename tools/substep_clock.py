"""Substep clock: time measurements against the simulation, not the wall clock.

Why
---
Comparing display rates with wall-clock timing is a trap. "For 2.5 s" does not
cover the same number of rendered frames at 30 and 60 FPS, and input injection
(see `pad.py`) is a race whose success rate depends on the frame count. The
differences then measure the instrumentation, not the game.

The simulation runs at a constant 120 Hz whatever the rate, so indexing on
substeps removes the display variable: "state after 60 substeps" is comparable
between tiers, "state after 0.5 s" is not.

How
---
The accumulator at `TMarDirector + 0x54` loses exactly 5 per substep and gains
`vsyncRate` at the start of each frame. Counting its decrements counts
substeps, with no breakpoint or hook.

A poll takes ~2.5 us against 2.1 ms per substep, so no transition is missed.
The method is self-validating: any decrement other than 5 means polling fell
behind, and `wait` reports it instead of returning a wrong count.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MAR_DIRECTOR = 0x8040E178
OFF_ACCUMULATOR = 0x54
QUANTUM = 5


class SubstepClock:
    """Substep counter based on the director's accumulator."""

    def __init__(self, dolphin: Dolphin) -> None:
        self.dolphin = dolphin
        director = dolphin.u32(GP_MAR_DIRECTOR)
        if not dolphin.is_valid_pointer(director):
            raise RuntimeError("TMarDirector introuvable")
        self.address = director + OFF_ACCUMULATOR

    def wait(self, count: int, timeout: float = 20.0) -> tuple[int, bool]:
        """Wait for `count` substeps.

        Returns (substeps counted, polling valid). The flag goes false if a
        decrement other than 5 is seen: at least one substep was skipped and
        the measurement must not be used.
        """
        seen = 0
        valid = True
        previous = self.dolphin.s32(self.address)
        deadline = time.perf_counter() + timeout

        while seen < count and time.perf_counter() < deadline:
            value = self.dolphin.s32(self.address)
            if value < previous:
                step = previous - value
                if step != QUANTUM:
                    valid = False
                seen += step // QUANTUM
            previous = value

        return seen, valid

    def sample_while(self, count: int, probe, timeout: float = 20.0):
        """Sample `probe()` for `count` substeps.

        Returns (values, polling valid). `probe` is called as fast as possible;
        only the end bound is synchronized with the simulation.
        """
        values = []
        seen = 0
        valid = True
        previous = self.dolphin.s32(self.address)
        deadline = time.perf_counter() + timeout

        while seen < count and time.perf_counter() < deadline:
            value = self.dolphin.s32(self.address)
            if value < previous:
                step = previous - value
                if step != QUANTUM:
                    valid = False
                seen += step // QUANTUM
            previous = value
            values.append(probe())

        return values, valid


def _main(argv: list[str]) -> int:
    count = int(argv[1]) if len(argv) > 1 else 120
    dolphin = Dolphin()
    clock = SubstepClock(dolphin)

    start = time.perf_counter()
    seen, valid = clock.wait(count)
    elapsed = time.perf_counter() - start

    print(f"{seen} sous-pas en {elapsed:.3f} s -> {seen / elapsed:.2f} Hz")
    print("sondage valide" if valid else "SONDAGE PRIS EN DÉFAUT — mesure à rejeter")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
