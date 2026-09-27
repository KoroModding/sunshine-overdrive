"""Poinks (TPopo, "Popo"): no longer explode on their own collision box.

Defect (read in the DOL, then measured on 2026-09-27 in Bianco, Petey episode,
tools/watch_popo.py, 1324-word profile, 120 frames/s)
=========================================================================
The Poink has a second collision box, TPopoCollision (+0x23C, its owner at
+0x68). TPopo::calcRootMatrix (0x800E7604) places it on a model joint, from
the PREVIOUS frame's matrices; it is only called in the animation pass of
TLiveActor::perform (flag 0x2, alongside MActor::frameUpdate and MActor::calc),
so once per rendered frame.

On launch (TNervePopoFly 0x800E6078), the collision of the Poink and of the
box are disabled, then restored at step 6. In flight, as soon as the two touch,
TPopo::isCollidMove (0x800E6C94) sends message 0 to the box, which relays it
to the Poink: true reply -> Explosion nerve.

    measured at 120 FPS: box 150–210 u behind the Poink (≈ 2 speed steps,
                         45–100 u/step); 20 throws: 19 exploded 7 to 10 steps
                         (< 0.1 s) after launch, at 380–880 u, 1 at step 2;
                         the 8 throws tracked by the collision probe: contact
                         with ITS box at the first checkActorsHit after step 5
    computed at 30 FPS:  same one-frame lag = 4 more substeps, i.e. 500 u or
                         more: no contact, the Poink flies away

Fix
===
Contact is handled in both directions, and both lead to isCollidMove:
- the Poink touches its box: isCollidMove(Poink, box);
- the box touches the Poink: TPopo::bind (0x800E6FC0) calls
  TSmallEnemy::behaveToHitOthers(Poink, Poink), which calls through the vtable
  (+0x17C) isCollidMove(Poink, Poink).
First version (other == box only) installed then measured on 2026-09-27: no
effect, 9 throws out of 9 exploded at step 7–10 through the second path.

0x800E6C94 mflr r0 -> b POINK: if the actor hit is the Poink itself or its box
(other == this or other == this+0x23C), return 0 (no collision), otherwise
resume the function. isCollidMove always returns 0 and only acts in flight:
the fix only removes self-collision in flight, which does not exist in the
original game. r12 is volatile on function entry. Returning 0 also removes the
push from behaveToHitOthers (+0x94), applied only on a true reply. Hits by the
Poink and its box on other actors (Petey, Mario, enemies) are unchanged.

Measured after (1334-word profile): 54-step flight (0.45 s), 4630 u, explosion
on TBPNavel (Petey's navel), who wakes up. Validated by the author. Only one
throw measured.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

POINK = 0x80001D80             # in soundsets' range, which ends at 0x80001CF8;
POINK_END = 0x80001DC0         # 0x80001CFC–0x80001DFF checked zero in MEM1
SITE = 0x800E6C94              # TPopo::isCollidMove, prologue
ORIGINAL = {SITE: 0x7C0802A6}  # mflr r0

SRC = f"""
    cmplw r3, r4
    beq   {POINK + 0x14:#x}
    lwz   r12, 0x23c(r3)
    cmplw r12, r4
    bne   {POINK + 0x1C:#x}
    li    r3, 0
    blr
    mflr  r0
    b     {SITE + 4:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, POINK)
    assert POINK + len(code) <= POINK_END
    return words(POINK, code) + words(SITE, assemble(f"b {POINK:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} au lieu de {v:08X}"
    print(listing(POINK, assemble(SRC, POINK)))
    print(listing(SITE, assemble(f"b {POINK:#x}", SITE)))
    print(len(build()), "mots")
