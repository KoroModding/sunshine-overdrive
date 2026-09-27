"""Doppler effect on 3D sounds: strength and transition duration.

Defect
======
JAISound::setPositionDopplarCommon (0x8030AB68) computes the pitch factor from
how much the camera and source closed in BETWEEN TWO JAI PASSES:
    len  = |camera − source| now
    len2 = |(camera − source) + (Δcamera − Δsource)|     Δ = since the previous pass
    pitch = 1 / (1 − (len − len2) / (dopplarParameter / k²))   clamped to [0.1, 2]
(Graffito-Decomp JAISound.cpp.) At 120 passes/s the per-pass displacement is
4× smaller, so the pitch shift is 4× too weak.
Divisor: JAIGlobalParameter::dopplarParameter, 0x8040CD8C = 3200.0, read in a
single place (0x8030ACE4, lfs f3, -0x7434(r13)), no setter in the map.
It is used by effects (setSePositionDopplar) and sequences
(checkPlayingSeqTrack) alike: both paths go through this function.

The transition to the new pitch lasts JAIGlobalParameter::dopplarMoveTime
= 15 passes (0x8040CD64), read in two places:
  - checkPlayingSeqTrack 0x8030707C -> setSeqInterPitch -> initMoveParameter:
    already multiplied by M by fades.py;
  - setSePositionDopplar 0x8030C6B0, INLINED transition (r31 = 15, or 1 on the
    first pass), not covered by fades.py.
Hence: do not multiply the dopplarMoveTime data (double effect on sequences);
multiply r31 in setSePositionDopplar only.

Fixes
=====
1. 0x8040CD8C: 3200.0 -> 800.0 (= 3200 / M, M = 4). FIXED DATA: assumes
   literal 0x804167B8 is 2.0 (120 profile, set by the base). build() checks
   that this write is present in the base.
2. 0x8030C730 (cmplwi r31, 0, start of the inlined transition) -> b routine:
   r31 <<= log2(M) (read at run time) ; cmplwi r31, 0 ; b 0x8030C734.
   Non-leaf function; r12 is not read after 0x8030C6F0 (virtual call) until
   the epilogue, checked on the listing.

Range: 0x80002EC0 – 0x80002EDF (free remainder of fades.py's range).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE = 0x80002EC0
CAVE_END = 0x80002EE0
DOPPLAR_PARAMETER = 0x8040CD8C
SITE_MOVE = 0x8030C730
M = 4
ORIGINAL = {DOPPLAR_PARAMETER: 0x45480000, SITE_MOVE: 0x281F0000}

ASM_MOVE = f"""
    lis    r12, 0x8041
    lwz    r12, 0x67B8(r12)
    rlwinm r12, r12, 9, 24, 31
    addi   r12, r12, -126
    slw    r31, r31, r12
    cmplwi r31, 0
    b      {SITE_MOVE + 4:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(ASM_MOVE, CAVE)
    assert CAVE + len(code) <= CAVE_END
    param = struct.unpack(">I", struct.pack(">f", 3200.0 / M))[0]
    return (words(CAVE, code) + [(DOPPLAR_PARAMETER, param)]
            + words(SITE_MOVE, assemble(f"b {CAVE:#x}", SITE_MOVE)))


if __name__ == "__main__":
    from dol import Dol
    from build_profile import BASE  # noqa: F401  (the literal is set in collect())
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(CAVE, assemble(ASM_MOVE, CAVE)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
