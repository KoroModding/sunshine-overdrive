"""MSSetSound sound sets (FLUDD, graffiti, goop, pillars): 30 Hz clock.

Defect
======
MSound::mainLoop calls, once per JAI pass (= per rendered frame, 120/s at
120 FPS), the virtual method frameLoopDyna of every MSSetSound and
MSSetSoundGrp (0x80014E00 / 0x80014E28, entry +0x14 of the secondary vtable).
It does:
    if (+0x58) +0x54 += 1        sound set clock
    +0xB8 = 0                    "one start per pass" latch
The parameters of the 9 sets (MSSetSound::init: FLUDD spray impact 0x6800 /
0x6801, graffiti cleaning 0x6809, goop, fire and electric pillars, drying
0x804, impact 0x6802, manta cry 0x899B) are in 30 Hz passes: minimum interval,
single-sound duration, modulation duration, continuity gap, maximum continuity
duration. At 120 FPS the clock runs 4× too fast and the latch reopens 4× as
often: these sounds restart up to 4× as often and their modulations elapse 4×
too fast.

Second timer, the main one: the AGE of the previous sound, JAISound+0x14, also
incremented every JAI pass (~120/s). startSoundSetDyna compares it with the
minimum interval (+0x1D, + random +0x1E), the single-sound duration (+0x1F),
the group member thresholds (+0x18 f32), the modulation duration (+0x28) and
the continuity gap (+0x3C). It sets the repeat rate of the spray impact sound
(0x6800: continuity gap 0, so the +0x54 clock is never active there).

Fixes
=====
1. Age brought back to 30 Hz passes: the 4 `lwz rD, 0x14(rA)` reads in each
   instance of startSoundSetDyna (MSSetSound 0x8001B454, MSSetSoundGrp
   0x8001BE24, same code shifted by 0x9D0) are redirected to
   `bl SHIFT ; lwz rD, 0x14(rA) ; srw rD, rD, r12 ; b site+4`.
   Non-leaf functions (LR saved in the prologue, restored from the stack):
   the bl mid-function is harmless. r11/r12 are never used there (checked
   over the whole listing).

2. frameLoopDyna runs only one pass in M (M = 2 × literal 0x804167B8, read at
   run time): when (JAIBasic::basic+0x20) & (M − 1) == 0. That counter is
   incremented by JAIBasic::processFrameWork (0x80301D84), once per pass,
   measured in game at 119.99/s. It is incremented AFTER the frameLoopDyna
   calls of the same pass, so the phase is stable. If JAIBasic::basic is null,
   the method runs normally.

Routines (range 0x80001C00 – 0x80001DFF, free: hx ends around 0x80001ACC):
    SHIFT  r12 = log2(M); clobbers r12.
    GATE   cr0.eq = "run this pass"; clobbers r11, r12, cr0.
    stub   (leaf function, LR must be kept): mflr r10 ; bl GATE ; mtlr r10 ;
           bnelr ; lbz r0, 0x58(r3) (original instruction) ; b site+4.
           r10 is volatile and not an argument (only r3 is).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_START = 0x80001C00
CAVE_END = 0x80001E00          # exclusive
GATE = 0x80001C00
JAIBASIC_BASIC = 0x8040E430    # JAIBasic::basic (us.map), read in game: 0x805F39D8

SITES = (
    0x80016014,                # MSSetSoundTL<MSSetSoundGrp>::frameLoopDyna
    0x8001604C,                # MSSetSoundTL<MSSetSound>::frameLoopDyna
)
LBZ_R0_58 = 0x88030058         # lbz r0, 0x58(r3)
DYNA_GRP_DELTA = 0x9D0         # startSoundSetDyna<Grp> - startSoundSetDyna<MSSetSound>
AGE_READS = {                  # site (MSSetSound instance): read of JAISound+0x14
    0x8001B504: "lwz r4, 0x14(r4)",
    0x8001B66C: "lwz r23, 0x14(r3)",
    0x8001B750: "lwz r4, 0x14(r4)",
    0x8001B8A4: "lwz r23, 0x14(r3)",
}
AGE_SITES = {**AGE_READS, **{a + DYNA_GRP_DELTA: t for a, t in AGE_READS.items()}}
ORIGINAL = {a: LBZ_R0_58 for a in SITES}
ORIGINAL.update({a: w for a, w in zip(AGE_SITES, [0x80840014, 0x82E30014, 0x80840014, 0x82E30014] * 2)})

ASM_SHIFT = """
    lis    r12, 0x8041
    lwz    r12, 0x67B8(r12)
    rlwinm r12, r12, 9, 24, 31
    addi   r12, r12, -126
    blr
"""

ASM_GATE = f"""
    lis    r12, 0x8041
    lwz    r12, 0x67B8(r12)
    rlwinm r12, r12, 9, 24, 31
    addi   r12, r12, -126
    li     r11, 1
    slw    r11, r11, r12
    addi   r11, r11, -1
    lis    r12, {(JAIBASIC_BASIC + 0x8000) >> 16:#x}
    lwz    r12, {JAIBASIC_BASIC & 0xFFFF if JAIBASIC_BASIC & 0x8000 == 0 else (JAIBASIC_BASIC & 0xFFFF) - 0x10000}(r12)
    cmpwi  r12, 0
    beqlr
    lwz    r12, 0x20(r12)
    and.   r12, r12, r11
    blr
"""


def asm_stub(site: int, original: str) -> str:
    return f"""
    mflr   r10
    bl     {GATE:#x}
    mtlr   r10
    bnelr
    {original}
    b      {site + 4:#x}
"""


def blocks() -> list[tuple[int, bytes, int]]:
    out = [(GATE, assemble(ASM_GATE, GATE), 0)]
    addr = GATE + len(out[0][1])
    for site in SITES:
        code = assemble(asm_stub(site, "lbz r0, 0x58(r3)"), addr)
        out.append((addr, code, site))
        addr += len(code)
    shift = addr
    code = assemble(ASM_SHIFT, shift)
    out.append((shift, code, 0))
    addr += len(code)
    for site, read in AGE_SITES.items():
        dest = read.split(",")[0].split()[1]
        code = assemble(f"""
    bl     {shift:#x}
    {read}
    srw    {dest}, {dest}, r12
    b      {site + 4:#x}
""", addr)
        out.append((addr, code, site))
        addr += len(code)
    return out


def build() -> list[tuple[int, int]]:
    patches: list[tuple[int, int]] = []
    sites: list[tuple[int, int]] = []
    for addr, code, site in blocks():
        assert CAVE_START <= addr and addr + len(code) <= CAVE_END, "routine hors zone"
        patches += words(addr, code)
        if site:
            sites += words(site, assemble(f"b {addr:#x}", site))
    return patches + sites


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    for addr, code, site in blocks():
        print(f"; {'routine' if not site else f'stub {site:08X}'}")
        print(listing(addr, code))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
