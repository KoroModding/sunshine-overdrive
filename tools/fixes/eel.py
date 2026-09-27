"""Eel boss (TBossEel, Eely-Mouth): constant animation rate 0.5 per substep.

Extracted on its own from tools/fixes/actors.py (group 3), same sites, same
CONST2 routine as tools/fixes/birds.py (constant 2.0 at 0x80002400, code at
0x80002410; identical words, which build_profile's conflict check accepts).

Defect (US DOL, 2026-09-27 audit, three sites re-read by hand)
=============================================================
19 sites, all in TNerveBossEel*::execute or ExecBackNerve_Sub, of the form
    bl SMSGetAnmFrameRate ; lfs f0, 0.25 (0x80410D5C) ; li r4, 0 ;
    lwz r3, 0x74(r31) ; fmuls f31, f0, f1 ; bl MActor::getFrameCtrl ;
    stfs f31, 0xC(r3)
The main animation (+0x74) advances PER SUBSTEP: the boss's only calcAnm is at
0x800D37C0, under `clrlwi. r0, r30, 31` (flag 0x1, 0x800D3710). Rate 0.25 ×
anmRate = 0.5 per substep at 30 FPS (60 animation frames/s), 0.125 at 120 FPS
(15 animation frames/s): every phase timed on the end of an animation
(appearance, mouth open, suction, death…) lasts 4× too long.

Fix: the 19 `bl SMSGetAnmFrameRate` → `bl CONST2` (2.0): rate 0.5 per substep
at any frame rate, bit-identical to the original game. Same choice as BSE
(getBossEelAnmFrameRate).

No defect (same audit): TBossEelTooth, TBEelTears, TBEelTearsDrop, vortex,
heart piece. Not fixed here: eye fade (fsubs at 0x800D641C, −0.01 per frame,
4× too fast) — fixed by bosses.py ("eeleye", the lfs at 0x800D6414).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import birds  # noqa: E402
from birds import ANM_RATE, CONST2, K_2, _bl  # noqa: E402

SITES = [
    0x800D059C, 0x800D07A0, 0x800D0898, 0x800D0B60, 0x800D0E0C, 0x800D1128, 0x800D12F0,
    0x800D147C, 0x800D15C0, 0x800D1C98, 0x800D1D68, 0x800D207C, 0x800D2364, 0x800D2438,
    0x800D24F8, 0x800D2710, 0x800D2AD8, 0x800D2F8C, 0x800D3350,
]


def build() -> list[tuple[int, int]]:
    shared = [(a, v) for a, v in birds.build() if a == K_2 or CONST2 <= a < CONST2 + 0x10]
    return shared + [(s, _bl(s, CONST2)) for s in SITES]


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
        assert dol.u32(s + 4) == 0xC002A1BC, f"{s:08X} : lfs 0.25 absent"
    import actors
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — 19 sites vérifiés, identiques à actors.py")
