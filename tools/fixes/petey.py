"""Petey Piranha (TBossPakkun): vomit animation 0x15 at the right speed.

Extracted on its own from tools/fixes/actors.py (group 5), same addresses and
same code, so it can be installed independently (session 7, one fix at a time).

Defect (read in the DOL)
========================
TBossPakkun::changeBck (0x8009548C) sets the new animation's rate to
SMSGetAnmFrameRate() (0x80095594/98: 2.0 at 30 FPS, 0.5 at 120; correct, as
the controller advances once per rendered frame), THEN, for animation 0x15
only (0x8009559C cmpwi r31, 0x15), overwrites it with a raw parameter:
    0x800955C0 lfs f31, 0x16C(param) ; 0x800955C8 bl getFrameCtrl ;
    0x800955CC stfs f31, 0xC(r3)
tuned for 30 FPS and never rescaled: at 120 FPS animation 0x15 plays 4× too
fast. Yet TNerveBPVomit::execute (0x8009327C) times the whole vomit phase on
this animation: changeBck(0x15), animation frame window 25–165 (0x800932E4 /
0x800932F0), transition on curAnmEndsNext. Symptom reported by the author
(2026-09-26): "he vomits right away, no time to fill his stomach".

Fix
===
0x800955CC stfs f31, 0xC(r3) -> bl PETEY, which stores f31 / M (M = 2 ×
literal 0x804167B8, read at run time): identical to the original game at
30 FPS, whatever the parameter. changeBck is non-leaf (LR saved in the
prologue); r12 and f0 are volatile and the site directly follows a bl
(getFrameCtrl): no live value is destroyed.

Difference from BSE: BSE forces 0.8 × SMSGetAnmFrameRate(), which assumes the
parameter equals 1.6 (NOT VERIFIED) and otherwise changes the game at 30 FPS.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

PETEY = 0x80002480             # same address as actors.py
SITE = 0x800955CC
ORIGINAL = {SITE: 0xD3E3000C}  # stfs f31, 0xC(r3)

SRC = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fdivs f0, f31, f0
    stfs  f0, 0xc(r3)
    blr
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, PETEY)
    assert PETEY + len(code) <= 0x800024A0
    return words(PETEY, code) + words(SITE, assemble(f"bl {PETEY:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(PETEY, assemble(SRC, PETEY)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    import actors
    same = [(a, v) for a, v in actors.build() if PETEY <= a < 0x800024A0 or a == SITE]
    assert sorted(same) == sorted(build()), "divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
