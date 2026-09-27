"""TJointCoin / TSandBird: animation rate set by TJointCoin::loadAfter.

Extracted on its own from tools/fixes/actors.py (group 4), same sites, same
routines and same addresses, so it can be installed independently (one fix at
a time).

Defect (read in the DOL, then measured on 2026-09-27 on the Gelato sand bird,
tools/watch_sandbird.py, 1309-line profile, 120 frames/s)
=========================================================================
TSandBird inherits from TJointCoin (same loadAfter, its control calls
TJointCoin's). loadAfter sets frame ctrl 0's rate to 0.25 × anmRate:

    801F76A8  bl SMSGetAnmFrameRate ; ×0.25 -> +0x74  "character" (wings)
    801F76C4  bl SMSGetAnmFrameRate ; ×0.25 -> +0x138 "movement" (path)

TJointCoin::control (per substep) advances +0x138 then copies its root joint's
translation into the position: path at 120 advances/s whatever M is. +0x74 is
also advanced once per frame (TLiveActor::perform).

    measured at 120 FPS: rate 0.125; path 15.0 animation frames/s, wings 30.0,
                         flight 88 u/s, one lap (9000 animation frames) in ~600 s
    computed at 30 FPS:  path 60 animation frames/s, wings 75; lap in 150 s

Fix
===
801F76C4 -> bl CONST2 (2.0): constant rate 0.5, 60 animation frames/s at any M.
801F76A8 -> bl JCCHAR (10 / (4 + M)): rate 2.5 / (4 + M), 75 animation
frames/s at any M.
Both routines are those of birds.py and bosses.py, rewritten here identically
so the module stands alone.

Caveat: the rate is frozen at load time with the M of that moment; leave and
re-enter the level after installing. The game's other TJointCoin users share
this code: NOT VERIFIED.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_caves import assemble, words, listing  # noqa: E402
import actors  # noqa: E402

ANM_RATE = 0x802A7BD8            # SMSGetAnmFrameRate__Fv
K_2, K_5 = actors.K_2, actors.K_5
CONST2, JCCHAR = actors.CONST2, actors.JCCHAR
SITES = [(0x801F76A8, JCCHAR), (0x801F76C4, CONST2)]


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    return ([(K_2, _f32(2.0)), (K_5, _f32(5.0))]
            + words(CONST2, assemble(actors.SRC_CONST2, CONST2))
            + words(JCCHAR, assemble(actors.SRC_JCCHAR, JCCHAR))
            + [(s, _bl(s, t)) for s, t in SITES])


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s, _ in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
    print(listing(JCCHAR, assemble(actors.SRC_JCCHAR, JCCHAR)))
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
