"""Fish schools and other flocks (TBoidLeader): movement at the 30 FPS speed.

Group 1 of tools/fixes/actors.py extracted on its own (same sites, same
routines, same addresses), to be installed independently. Never installed
before 2026-09-28.

Defect (read in the DOL, then measured on 2026-09-28 at Gelato Beach, episode 6
"Red Coins in the Coral Reef", tools/watch_boids.py, 1502-word profile)
=========================================================================
TBoidLeader::perform (0x80005D14) runs the leader's move and calcBoids only
under flag 0x2, i.e. once per rendered frame, with a per-frame step that does
not depend on the frame rate:
    leader: 80005DFC lfs f2, 0.9 ; 80005E08 fmuls f1, f2, (this+0x20) ;
            80005E2C..80005E58 pos (+0x74) += dir * f1
    boids:  800066E0 bl TVec3::dot ; 800066E4 bl TUtil<f>::sqrt ;
            80006770..8000679C pos += step
Report: "the fish are too fast, I can't catch them, some go through walls".

    measured at 120 FPS: 8 active leaders, 3.57-3.60 u per frame whatever
                         the frame rate (116-124 frames/s), i.e. 414-445 u/s
    calculated at 30 FPS: same 3.6 u per frame x 30 = 108 u/s -> 4x too fast

Fix
===
800066E4 bl sqrt -> bl BOID: f1 = dot / M^2, then tail call to sqrt, so the
boid step is sqrt(dot) / M (same as BSE's sqrtf(dot) * 30 / fps).
80005DFC lfs f2, -0x7fcc(r2) (0.9) -> bl LEADER: f2 = 0.9 / M. Without it the
leader keeps its 4x speed while the boids slow down, and they fall behind
(not in BSE). TBoidLeader::perform is non-leaf (LR saved in its prologue);
f0 is reloaded right after the site; r12 is volatile.
M = 2 x literal 0x804167B8, read at run time (1 at 30 FPS): no change at 30 FPS.
Not covered: boid orientation smoothing stays per frame, so boids turn faster
(visual only). NOT VERIFIED. All flocks share this code (fish, butterflies…).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_caves import assemble, words, listing  # noqa: E402
import actors  # noqa: E402

BOID, LEADER, SQRT = actors.BOID, actors.LEADER, actors.SQRT
BOID_SITE, LEADER_SITE = 0x800066E4, 0x80005DFC
ORIGINAL = {LEADER_SITE: 0xC0428034}   # lfs f2, -0x7fcc(r2)


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    return (words(BOID, assemble(actors.SRC_BOID, BOID))
            + words(LEADER, assemble(actors.SRC_LEADER, LEADER))
            + [(BOID_SITE, _bl(BOID_SITE, BOID)), (LEADER_SITE, _bl(LEADER_SITE, LEADER))])


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    assert dol.u32(BOID_SITE) == _bl(BOID_SITE, SQRT), f"{BOID_SITE:08X}: not a bl sqrt"
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X}: {dol.u32(a):08X}"
    print(listing(BOID, assemble(actors.SRC_BOID, BOID)))
    print(listing(LEADER, assemble(actors.SRC_LEADER, LEADER)))
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X}: differs from actors.py"
    print(len(build()), "words — identical to actors.py")
