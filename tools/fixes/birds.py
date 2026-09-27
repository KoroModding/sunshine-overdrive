"""Birds (TAnimalBird): flight, landing and ground-walk speed.

Extracted on its own from tools/fixes/actors.py (group 2), same addresses and
same code, so it can be installed independently (one fix at a time).

Defect (read in the DOL, symptom confirmed by the author on 2026-09-27:
"the birds are very slow, their animation is normal but they don't fly
fast")
==========================================================================
Five sites multiply a speed parameter by SMSGetAnmFrameRate():

    8000CD50  doLanding+0x48            (0x174 × 0xB8) × anmRate   initial landing speed
    8000CEB0  doLanding+0x1A8           param 0x194 × anmRate
    8000D1D8  doFlyToCurPathNode+0x10C  (0x174 × 0xB8) × anmRate   flight speed
    8000D1F8  doFlyToCurPathNode+0x12C  param 0xCC × anmRate
    8000BEB0  TNerveAnimalBirdWalkOnGround::execute+0x168  param 0x1A8 × anmRate

These functions are only called by nerves (vt+0xD0 moveObject → vt+0xC8
control), so **per substep**: the anmRate factor (2.0 at 30 FPS) is a tuning
constant there, not a frame-rate compensation. At 120 FPS it is 0.5: movement
4× too slow, animation (advanced per frame) unchanged, exactly the symptom.

Fix
===
The 5 `bl SMSGetAnmFrameRate` → `bl CONST2`, which returns 2.0 (original value
at 30 FPS) whatever M is. Same choice as BSE (getAnimalBirdSpeed), extended to
8000CD50 and 8000BEB0, which BSE missed. CONST2 only touches r12 and f1,
volatile across a call.

NOT VERIFIED at the time of writing: per-substep execution is established by
static reading (call chain); the expected measurement after installation is a
flight speed multiplied by exactly 4.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

ANM_RATE = 0x802A7BD8            # SMSGetAnmFrameRate__Fv
K_2 = 0x80002400                 # f32 2.0, same address as actors.py
CONST2 = 0x80002410              # same address as actors.py
SITES = [0x8000CEB0, 0x8000D1D8, 0x8000D1F8, 0x8000CD50, 0x8000BEB0]

SRC = """
    lis   r12, 0x8000
    lfs   f1, 0x2400(r12)
    blr
"""


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    k2 = struct.unpack(">I", struct.pack(">f", 2.0))[0]
    return ([(K_2, k2)] + words(CONST2, assemble(SRC, CONST2))
            + [(s, _bl(s, CONST2)) for s in SITES])


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
    print(listing(CONST2, assemble(SRC, CONST2)))
    import actors
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
