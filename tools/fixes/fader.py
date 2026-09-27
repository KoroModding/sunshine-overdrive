"""TSMSFader group — application black/white fades (BSE fps.cpp l. 418-439).

Convention: M = 2 x f32[0x804167B8], re-read at run time (1 at 30 FPS, 2 at 60, 4 at 120).
Code cave range: 0x80002000 - 0x800021FF (no state word: everything is recomputed on each call).

TSMSFader layout (read from the disassembly, GMSE01)
----------------------------------------------------
    +0x10 u16  fade duration in frames        (written by requestWipe, 0x8013F978 etc.)
    +0x12 u16  elapsed frame counter          (update: lhz/addi 1/sth, 0x8013FEF0 / 0x8013FF30)
    +0x14 f32  fader "frames per second"      (ctor 0x80140080: stfs f31, 0x14(r31))
    +0x24      pending request {u32 kind, f32 speed(s), f32 delay(s)} (startWipe 0x8013F860)
    +0x2C f32  remaining delay (seconds)
    +0x30/+0x34 copy of the active request's kind / delay

Evidence for "once per rendered frame": TApplication::gameLoop calls mFader->update()
directly through the vtable (slot +0x24 of __vt__9TSMSFader 0x803BFFC8 = 0x8013FE24):
    802A6288  lwz r3, 0x34(r31) / lwz r12, 0(r3) / lwz r12, 0x24(r12) / blrl
once per gameLoop iteration, outside the substep accumulator of TMarDirector::direct.

Fix 1 — fade duration (replaces BSE's 4 SMS_PATCH_BL, adjustFaderFrameRate)
----------------------------------------------------------------------------
requestWipe computes  8013F8B4 lfs f1,4(r4) ; 8013F8B8 lfs f0,0x14(r29) ; 8013F8C0 fmuls f0,f1,f0
                      8013F8C8 fctiwz ; 8013F8D0 lwz r31,0x14(r1)      -> r31 = (int)(speed*rate)
then, for fades (kind 0xE/0x10 -> 0x8013F94C, kind 0xF/0x11 -> 0x8013F9A8):
    state 0/1 (idle):  sth r31, 0x10(r29)                      (8013F978 / 8013F9D4)
    state 3/2 (reversal mid-fade):
        8013F994 mullw r0, r31, r0 ; 8013F998 divw r0, r0, r3 ; 8013F99C sth r0, 0x12(r29)
        8013F9A0 sth r31, 0x10(r29)                            (same at 8013F9F0..8013F9FC)
update() advances the counter by one per frame and finishes when +0x12 > +0x10; at 120 FPS
the fade is therefore 4x shorter. Fix: multiply r31 by M.
DISAGREEMENT with BSE: BSE only replaces the 4 `sth r31, 0x10(r29)` with _10 = speed*rate*M,
but in the "reversal" branch the +0x12 counter has already been recomputed with r31 NOT
multiplied (8013F994): the reversed fade restarts from a wrong position (opacity jump). Here
r31 is recomputed at the head of both fade branches: `lwz r0, 0x20(r29)` at 0x8013F94C and
0x8013F9A8 becomes `bl fader_dur`, which does r31 = (int)(fmuls(speed, rate) * M) then
executes the replaced lwz. The product is identical to the original multiplied by M
(M is a power of 2, exact in f32).
r31 is non-volatile, but here it is requestWipe's local variable (saved in its prologue):
modifying it is exactly the point. The cave reuses the temporary slot 0x10(r1) that
requestWipe already uses for its own fctiwz (8013F8CC stfd f0, 0x10(r1)).
The HX branch (kind outside 0xE-0x11, 8013FA04 `mr r4, r31` -> Hx_StartWipe) is NOT touched:
it belongs to the "HX transitions" group (as in BSE).

Fix 2 — delay before the fade (replaces SMS_PATCH_B 0x8013F860, trickFaderDelayToBeCorrect)
--------------------------------------------------------------------------------------------
update():   8013FE44 lfs f1, 1.0 ; 8013FE48 lfs f0, 0x14(r31) ; 8013FE4C lfs f2, 0x2c(r31)
            8013FE50 fdivs f1, f1, f0 ; 8013FE58 fsubs f2, f2, f1 ; ... stfs f2, 0x2c(r31)
The delay (seconds) decreases by 1/rate per rendered frame -> 4x too fast at 120 FPS.
BSE multiplies the delay by M in startWipe (and by the "game over" multiplier if kind == 0xD,
which is also M in our convention: the distinction disappears). Here the fix is applied at
consumption rather than at write time: `lfs f0, 0x14(r31)` at 0x8013FE48 becomes
`bl fader_delay`, which loads f0 = rate * M. Equivalent, but it covers every writer of +0x2C
and follows M if the rate changes between the request and its expiry. f1 (1.0, already
loaded) is preserved: the cave only uses f0, f3 and r12 (not live in update).

Fix 3 — application fader rate frozen at 30 (not in BSE, found while reading)
------------------------------------------------------------------------------
TApplication::initialize constructs mFader with the current rate:
    802A7730 bl SMSGetVSyncTimesPerSec   ; f1 = 60 * f32[0x804167B8]  (802A7C94/802A7C9C)
    802A776C bl TSMSFader::TSMSFader(TColor, float, const char*)   (f1 unchanged in between)
    80140080 stfs f31, 0x14(r31)
Under BSE, the literal is 0.5 at that point (the BSE callback only runs from gameLoop on),
so +0x14 = 30. Here, if Dolphin has already applied the profile (literal = 2.0) before
initialize, +0x14 = 120 and fades would ALREADY be correct — Fix 1/2 would then slow them
down 4x too much. NOT VERIFIED: the order "first PatchEngine pass / TApplication::initialize".
To be deterministic, the bl is redirected to fader_init, which returns
SMSGetVSyncTimesPerSec() / M = 60*lit / (2*lit) = 30 (25 in PAL), i.e. the original value
whenever the profile gets applied. If the profile is not yet applied at initialize, neither
this bl nor the literal is: the result is 30 as well. Consistent with the assumptions of BSE,
which the HX group adopts (Hx_UpdateWipe receives f1 = fader+0x14, 8013FDDC).

Counters seen but NOT fixed
---------------------------
- TShineFader (vtable 0x803C10F0, update 0x8017D8D4): counter +0x12 per update, duration +0x10
  and wait +0x38 set by registFadeout, called from TMarDirector::updateGameMode (80297BAC..
  80297BD8: 1.0*rate and 5.333*rate, rate = +0x14 = 60.0 constant, 8029D9E4). This fader is
  in the scene (TMarNameRefGen), run by the director's perform lists: NOT VERIFIED whether it
  runs per substep (then correct) or per frame (then 4x too fast at 120). BSE does not touch
  it. Measure it (fade after collecting a Shine) before any fix.
- TSmplFader (vtable 0x803C111C): shares TSMSFader::update, so it benefits from Fix 1/2 if it
  receives requests; rate = 60.0 constant (8029D978), not affected by Fix 3.
- HX branch of requestWipe / Hx_UpdateWipe: HX group.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002000
CAVE_END = 0x800021FF

FADER_DUR = 0x80002000
FADER_DELAY = 0x80002040
FADER_INIT = 0x80002060

SMS_GET_VSYNC = 0x802A7C48

# Call sites: (address, expected original word, bl target)
SITES = [
    (0x8013F94C, 0x801D0020, FADER_DUR),    # lwz r0, 0x20(r29)   fade branch 0xE/0x10
    (0x8013F9A8, 0x801D0020, FADER_DUR),    # lwz r0, 0x20(r29)   fade branch 0xF/0x11
    (0x8013FE48, 0xC01F0014, FADER_DELAY),  # lfs f0, 0x14(r31)   delay countdown
    (0x802A7730, 0x48000519, FADER_INIT),   # bl SMSGetVSyncTimesPerSec (mFader ctor)
]

SRC_DUR = """
    lfs     f1, 4(r30)
    lfs     f0, 0x14(r29)
    fmuls   f0, f1, f0
    lis     r12, 0x8041
    lfs     f1, 0x67B8(r12)
    fadds   f1, f1, f1
    fmuls   f0, f0, f1
    fctiwz  f0, f0
    stfd    f0, 0x10(r1)
    lwz     r31, 0x14(r1)
    lwz     r0, 0x20(r29)
    blr
"""

SRC_DELAY = """
    lfs     f0, 0x14(r31)
    lis     r12, 0x8041
    lfs     f3, 0x67B8(r12)
    fadds   f3, f3, f3
    fmuls   f0, f0, f3
    blr
"""

SRC_INIT = f"""
    mflr    r0
    stw     r0, 4(r1)
    stwu    r1, -0x10(r1)
    bl      {SMS_GET_VSYNC:#x}
    lis     r12, 0x8041
    lfs     f0, 0x67B8(r12)
    fadds   f0, f0, f0
    fdivs   f1, f1, f0
    lwz     r0, 0x14(r1)
    addi    r1, r1, 0x10
    mtlr    r0
    blr
"""

CAVES = [(FADER_DUR, SRC_DUR), (FADER_DELAY, SRC_DELAY), (FADER_INIT, SRC_INIT)]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    ends = []
    for addr, src in CAVES:
        code = assemble(src, addr)
        ends.append((addr, addr + len(code)))
        out += words(addr, code)
    ends.sort()
    for (_, e), (s, _) in zip(ends, ends[1:]):
        assert e <= s, "caves qui se chevauchent"
    for site, _orig, target in SITES:
        out.append((site, _bl(site, target)))
    return out


if __name__ == "__main__":
    import capstone
    from dol import Dol

    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    root = Path(__file__).resolve().parents[2]
    dol = Dol(root / "work" / "dol" / "GMSE01.dol")

    def dis(addr: int, word: int) -> str:
        ins = list(cs.disasm(word.to_bytes(4, "big"), addr))
        return f"{ins[0].mnemonic} {ins[0].op_str}" if ins else f".long {word:#010x}"

    pairs = build()
    site_addrs = {s for s, _, _ in SITES}
    print("== Caves ==")
    for addr, word in pairs:
        if addr in site_addrs:
            continue
        assert CAVE_START <= addr and addr + 3 <= CAVE_END, f"{addr:#x} hors plage"
        print(f"  {addr:08X}  {word:08X}  {dis(addr, word)}")
    print("== Sites ==")
    for addr, word in pairs:
        if addr not in site_addrs:
            continue
        orig = dol.u32(addr)
        expected = next(o for s, o, _ in SITES if s == addr)
        assert orig == expected, f"{addr:#x}: DOL {orig:#010x} != attendu {expected:#010x}"
        print(f"  {addr:08X}  {orig:08X} {dis(addr, orig):<28} -> {word:08X} {dis(addr, word)}")
    print(f"{len(pairs)} mots, caves dans [{CAVE_START:#x}, {CAVE_END:#x}]")
