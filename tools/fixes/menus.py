"""120 FPS fixes: Shine select screen and dialogue box timer.

Port of the BetterSunshineEngine ``src/patches/fps.cpp`` sections at lines 149-166 (dialogue
box) and 444-507 (Shine select, credits theAzack9). Reserved code range:
0x80002200-0x800023FF.

Convention: M = 2 x f32@0x804167B8 (1 at 30 FPS, 2 at 60, 4 at 120), re-read on EVERY call.
A frame count is multiplied by M, a per-frame speed is divided by M.

Rate (evidence): ``TSelectDir::direct`` (0x80175EC4) calls ``JDrama::TDirector::direct``
(bl 0x802f7d28 @ 0x80175FE8) once per frame, with no substep accumulator; everything
below therefore runs once per rendered frame, i.e. 4x too fast at 120 FPS.

----------------------------------------------------------------------------------------------
1. Shine carousel rotation — TSelectShineManager::startDecrease / startIncrease
----------------------------------------------------------------------------------------------
Disassembly (startDecrease; startIncrease is identical with -0x28 and +0xA4) ::

    80178680  1C040028  mulli  r0, r4, 0x28        ; 40 * n   (n = index offset)
    80178684..80178698  mulhw 0x66666667 / srawi 2 ; / 10  -> 4n
    801786AC  98A300A5  stb    r5, 0xa5(r3)        ; "rotation in progress" flag
    801786C0  D00300A0  stfs   f0, 0xa0(r3)        ; step = (float)(40n/10)
    801787C4  D00300A0  stfs   f0, 0xa0(r3)        ; (startIncrease, step = -4n)

``perform`` (0x80178158) adds it to the integer angle once per frame, then clamps to the target ::

    80178210  lfs  f0, 0xa0(r25) / 80178224 fadds f0,f1,f0 / fctiwz / 80178234 stw r0,0x9c(r25)
    8017824C  mulli r0, r0, -0x28 ; target = -40 * index ; bge/ble -> stw target, stb 0 -> end

0xA0 is therefore a SPEED (degree-ish units per frame, 10 frames for 40 units) -> divided by M.
The mulli's "40" is NOT a frame count but the angular gap between two Shines; the
target (8017824C, 80178278) is not touched.

Fix: ``stfs f0,0xa0(r3)`` -> ``b cave``; the cave does f0 /= M, ``stfs``, then ``b``
back. ``b`` and not ``bl``: startDecrease/startIncrease are leaf functions (no
mflr/stw lr, epilogue ``addi r1,r1,0x30 / blr`` @ 80178724), a ``bl`` would clobber LR.
f1 (0x4330.. constant loaded at 801786B4) is dead after the fsubs: used as scratch.
For n=1: step 4/M = 1.0 at 120 FPS -> 40 frames instead of 10, exact sum. For M=3 the step
1.333 is truncated by fctiwz (integer angle) -> 40 frames instead of 30, end clamped.

Agreement with BSE: BSE does ``newFrames = 40 / frameScalar`` and rewrites the mulli immediate
(0x1C04FFD8 -> 0x1C04FFF6 for -10, 0x1C040028 -> 0x1C04000A). The NAME is misleading (it is
not a frame count) but the MEANING is right: it is a speed and it is divided. Our
version divides the float instead of the integer immediate (same result for M = 1, 2, 4).
Minor disagreement: BSE's static ``SMS_WRITE_32`` (0x80178784 = 0x1C04FFEC = -20,
0x80178680 = 0x1C040014 = +20) freeze the default 60 FPS value; they are overwritten by its
overrides on every call, so they have no real effect. Not ported.

----------------------------------------------------------------------------------------------
2. Title panel fade — ±25.5f literals (0x80412398 / 0x8041239C)
----------------------------------------------------------------------------------------------
Read only in TSelectMenu::perform (xref: 801737EC, 80173B90 for +25.5; 80173888,
80173C10 for -25.5), each stored immediately ::

    801737EC  C002B7F8  lfs   f0, -0x4808(r2)   ; 25.5
    801737F0  D0050048  stfs  f0, 0x48(r5)      ; TExPane: per-frame alpha step
              (+0x44 current alpha 0 or 255, +0x4C target 0xFF or 0, +0x50 active = 1)

TExPane::update (0x8013EAB0.. ; 8013EDC8 lfs f1,0x44 / 8013EDCC lfs f0,0x48 / fadds /
8013EDD4 stfs f0,0x44) adds 0x48 to the alpha once per frame: 255/25.5 = 10 frames.
It is a SPEED -> divided by M. Agreement with BSE (25.5f / frameScalar).

Fix: the literals are not rewritten (the PatchEngine would re-impose them, and they would
have to follow M); the 4 ``stfs f0,0x48(r5)`` (801737F0, 8017388C, 80173B94, 80173C14)
become ``bl cave_alpha``, which does f0 /= M then the stfs. TSelectMenu::perform is not a
leaf (prologue 80172C90 ``mflr r0 / stw r0,4(r1)``): bl is safe. Scratch r12 and f12:
f12/f13 appear nowhere in TSelectMenu::perform (grep over 0x80172C90..+1900 instr.), r12
is reloaded (``lwz r12,0(r3)``) before any further use. 25.5/4 = 6.375 = 51/8, exact in
binary -> 40 steps reach 255 / 0 exactly.

----------------------------------------------------------------------------------------------
3. Text slide — TCoord2D::setValue (4 BSE calls)
----------------------------------------------------------------------------------------------
TCoord2D::setValue(long n, f1..f4) @ 0x8013EB58 ::

    8013EB5C  cmpwi r4, 0          ; n <= 0 -> speed 0
    8013EB94  fsubs f3, f1, f3     ; (start - end)
    8013EBB8  fdivs f2, f3, f2     ; / (float)n
    8013EBC0  stfs  f2, 0x10(r3)   ; per-frame speed, consumed by TCoord2D::update
                                   ; (CLBChaseGeneralConstantSpecifySpeed, via TExPane::update)

r4 is a FRAME COUNT (``li r4,0xa`` at 801737C8, 80173864, 80173B68, 80173BEC, not
modified up to the bl) -> multiplied by M. Agreement with BSE (``speed * frameScalar``: the
parameter is called "speed" in BSE but it really is a duration, so multiplying is correct).

Fix: the 4 ``bl 0x8013EB58`` (8017383C, 801738C8, 80173BC8, 80173C54) -> ``bl
cave_coord``, which does r4 *= (int)M (floor 1) then ``b 0x8013EB58`` (tail call, LR
still points to the caller). f0 is used as scratch: setValue overwrites it anyway.

Note (beyond BSE, NOT fixed here, NOT VERIFIED in game): TSelectMenu has 7 other
calls to setValue (startOpenWindow 80172A80/80172B30/80172B90, perform 80172D88/801733FC/
80173560/801735BC) whose durations come from variables (r24/r25, fctiwz(20*f[0x14C])). They
animate the window opening and probably also speed up at 120 FPS.

----------------------------------------------------------------------------------------------
4. Dialogue box entry timer — TTalk2D2 +0x251
----------------------------------------------------------------------------------------------
TTalk2D2::perform @ 0x80151C88 (r28 = this, ``addi r28,r3,0`` at 80151CA0) ::

    80151D30  38000014  li   r0, 0x14
    80151D34  981C0251  stb  r0, 0x251(r28)     ; timer = 20
    80151D38  38000003  li   r0, 3              ; state 3
    ...
    80151ED8  887C0251  lbz  r3, 0x251(r28)     ; state 3: per-frame decrement
    80151EDC  3803FFFF  addi r0, r3, -1
    80151EE8  7C000775  extsb. r0, r0           ; < 0 -> state 4
    8015489C  991F0251  stb  r8, 0x251(r31)     ; (constructor)

FRAME COUNT -> 20 x M. Clamped to 127 because it is re-read with ``extsb`` (signed): 20 x 4 = 80 fits.
Fix: ``stb r0,0x251(r28)`` -> ``bl cave_talk`` (r0 *= M, clamp, stb, blr). perform
is not a leaf (80151C88 mflr/stw). The cave creates a stack frame for fctiwz and saves f0.
r0 is rewritten by ``li r0,3`` right after; cr0 is recomputed at 80151E94 (``rlwinm.``).
Agreement with BSE (20/40/80). NOT VERIFIED: that TTalk2D2 is in a per-frame perform list
and not a per-substep one — this relies on BSE's empirical finding (entry 2x too fast at 60).

Dependencies: none other than 0x804167B8 (base profile). If another group switches this
literal at run time, the caves follow since they re-read it on every call.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

RANGE_LO, RANGE_HI = 0x80002200, 0x80002400

LOAD_M = """
    lis   r12, 0x8041
    lfs   {f}, 0x67B8(r12)
    fadds {f}, {f}, {f}
"""

CAVE_SHINE_DEC = 0x80002200
CAVE_SHINE_INC = 0x80002220
CAVE_ALPHA = 0x80002240
CAVE_COORD = 0x80002260
CAVE_TALK = 0x800022A0

SITE_SHINE_DEC = 0x801786C0   # stfs f0, 0xa0(r3)  -> b cave, return to 0x801786C4
SITE_SHINE_INC = 0x801787C4   # stfs f0, 0xa0(r3)  -> b cave, return to 0x801787C8
SITES_ALPHA = (0x801737F0, 0x8017388C, 0x80173B94, 0x80173C14)   # stfs f0, 0x48(r5)
SITES_COORD = (0x8017383C, 0x801738C8, 0x80173BC8, 0x80173C54)   # bl TCoord2D::setValue
SITE_TALK = 0x80151D34        # stb r0, 0x251(r28)
SETVALUE = 0x8013EB58

ORIGINAL = {
    SITE_SHINE_DEC: 0xD00300A0, SITE_SHINE_INC: 0xD00300A0,
    **{a: 0xD0050048 for a in SITES_ALPHA},
    SITE_TALK: 0x981C0251,
}


def _shine(ret: int) -> str:
    return LOAD_M.format(f="f1") + f"""
    fdivs f0, f0, f1
    stfs  f0, 0xa0(r3)
    b     {ret:#x}
"""


ASM_ALPHA = LOAD_M.format(f="f12") + """
    fdivs f0, f0, f12
    stfs  f0, 0x48(r5)
    blr
"""

ASM_COORD = """
    stwu   r1, -0x10(r1)
""" + LOAD_M.format(f="f0") + f"""
    fctiwz f0, f0
    stfd   f0, 8(r1)
    lwz    r12, 12(r1)
    addi   r1, r1, 0x10
    cmpwi  r12, 1
    bge    coord_ok
    li     r12, 1
coord_ok:
    mullw  r4, r4, r12
    b      {SETVALUE:#x}
"""

ASM_TALK = """
    stwu   r1, -0x20(r1)
    stfd   f0, 0x10(r1)
""" + LOAD_M.format(f="f0") + """
    fctiwz f0, f0
    stfd   f0, 8(r1)
    lwz    r12, 12(r1)
    lfd    f0, 0x10(r1)
    addi   r1, r1, 0x20
    cmpwi  r12, 1
    bge    talk_m_ok
    li     r12, 1
talk_m_ok:
    mullw  r0, r0, r12
    cmpwi  r0, 127
    ble    talk_store
    li     r0, 127
talk_store:
    stb    r0, 0x251(r28)
    blr
"""


def caves() -> dict[int, bytes]:
    out = {
        CAVE_SHINE_DEC: assemble(_shine(SITE_SHINE_DEC + 4), CAVE_SHINE_DEC),
        CAVE_SHINE_INC: assemble(_shine(SITE_SHINE_INC + 4), CAVE_SHINE_INC),
        CAVE_ALPHA: assemble(ASM_ALPHA, CAVE_ALPHA),
        CAVE_COORD: assemble(ASM_COORD, CAVE_COORD),
        CAVE_TALK: assemble(ASM_TALK, CAVE_TALK),
    }
    starts = sorted(out)
    for i, a in enumerate(starts):
        end = a + len(out[a])
        limit = starts[i + 1] if i + 1 < len(starts) else RANGE_HI
        assert RANGE_LO <= a and end <= limit, f"cave {a:#x} déborde ({end:#x} > {limit:#x})"
    return out


def sites() -> list[tuple[int, int]]:
    p: list[tuple[int, int]] = []
    p += words(SITE_SHINE_DEC, assemble(f"b {CAVE_SHINE_DEC:#x}", SITE_SHINE_DEC))
    p += words(SITE_SHINE_INC, assemble(f"b {CAVE_SHINE_INC:#x}", SITE_SHINE_INC))
    for a in SITES_ALPHA:
        p += words(a, assemble(f"bl {CAVE_ALPHA:#x}", a))
    for a in SITES_COORD:
        p += words(a, assemble(f"bl {CAVE_COORD:#x}", a))
    p += words(SITE_TALK, assemble(f"bl {CAVE_TALK:#x}", SITE_TALK))
    return p


def build() -> list[tuple[int, int]]:
    patches: list[tuple[int, int]] = []
    for a, code in caves().items():
        patches += words(a, code)
    # Call sites last: the routines are in place before they become reachable.
    patches += sites()
    return patches


if __name__ == "__main__":
    import capstone

    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)

    def dis(addr: int, word: int) -> str:
        ins = next(cs.disasm(word.to_bytes(4, "big"), addr), None)
        return f"{ins.mnemonic} {ins.op_str}" if ins else ".long"

    for a, code in caves().items():
        print(f"; cave {a:08X} ({len(code)} octets)")
        for addr, w in words(a, code):
            print(f"  {addr:08X}  {w:08X}  {dis(addr, w)}")
    print("; sites")
    for addr, w in sites():
        old = ORIGINAL.get(addr)
        if old is None:  # bl TCoord2D::setValue: recomputed
            old = int.from_bytes(assemble(f"bl {SETVALUE:#x}", addr), "big")
        print(f"  {addr:08X}  {old:08X} {dis(addr, old):<28} -> {w:08X}  {dis(addr, w)}")
    all_p = build()
    for addr, _ in all_p:
        assert (RANGE_LO <= addr < RANGE_HI) or addr in ORIGINAL or addr in SITES_COORD, hex(addr)
    print(f"; {len(all_p)} mots")
