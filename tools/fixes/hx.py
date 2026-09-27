"""HX wipes (screen transitions) — port of BetterSunshineEngine fps.cpp, l. 168–414.

Context
-------
HX wipes are drawn by TSMSFader::draw -> Hx_UpdateWipe (0x8013FDE0
``bl Hx_UpdateWipe``), which calls the wipe routine through ``blrl`` between two
``GXDrawDone`` (0x80181F80 / 0x80181F90). These routines emit GX commands
(GXBegin, writes to 0xCC008000): they run **once per rendered frame**. Anything
they count in "frames" therefore runs M times too fast, with
M = 2 × f32@0x804167B8 (1 at 30 FPS, 2 at 60, 4 at 120), re-read on **every** call.

Shared wipe state: block at 0x803F43C0 (``lis r3,0x803F ; addi 0x43C0``),
whose countdown at +0x3C = **0x803F43FC** (Hx_TimerCountDown:
``lwz r3,0x3c(r3) ; addi r0,r3,-1 ; stw r0,0(r4)``) — same address as BSE
``HX_SetTimer``.

Fix principles (all stateless except TEST4)
-------------------------------------------
* Integer durations: each ``stw rX, 0x3c(r31|r30)`` that arms the countdown
  becomes ``bl TIMER_Rx``, which writes (int)(rX × M) to 0x803F43FC.
* Per-frame float increments: the ``fadds/fsubs fD, fA, fB`` instruction is
  replaced by a ``bl`` to a stub that redoes the same operation with the
  increment divided by M. This keeps each site's exact semantics (including
  when M changes mid-wipe) without touching the shared .sdata2 pool literals.
* Per-frame integer increments: ``addi r0, r3, imm`` becomes ``bl`` to
  ``li r0, imm ; b INT_STEP``, which computes r0 = r3 + imm / (int)M.
* Hx_MotionUpdate (0x80181D74) is replaced entirely (``b MOTION``,
  like BSE's SMS_PATCH_B) by the same Euler integration with step 1/M:
  time += 1/M, velocity += accel/M, position += velocity/M.

Registers: the stubs only use r12, f12, f13 (+ r0 as output for
INT_STEP). None of Hx_Circle, Hx_GameOver, Hx_Test1, Hx_Test2,
Hx_Test2R, Hx_Test4, Hx_Test5 mentions r11, r12, f12 or f13 (checked by
grep over their full disassembly). No stub modifies cr0 (no Rc=1
instruction, no compare), which matters at 0x80181C7C..C8C where
cr0 and r3 are live.

Sites (original instruction -> effect) — confidence
---------------------------------------------------
CIRCLE (Hx_Circle)
  0x80181B54  stw r0,0x3c(r31)   (li r0,0x19)  -> TIMER_R0      [BSE] high
  0x80181B78  stw r0,0x3c(r31)   (li r0,0x1E)  -> TIMER_R0      [BSE] high
  0x80181BBC  fadds f1,f2,f1     DE44 += 1/15 (FrBufferMorf fade, clamped to 1)
                                 -> f1 = f2 + f1/M  ; f0 = 1.0 live, untouched
                                                                [ADDED] high
  0x80181C7C  fadds f0,f1,f0     DE30 += 0.05  -> f0 = f1 + f0/M  [ADDED] high
  0x80181C8C  addi r0,r3,0x180   u16 DE3C (ring 1 alpha)  -> r3+0x180/M [ADDED]
  0x80181CE0  fadds f0,f1,f0     DE34 += 0.12                     [ADDED]
  0x80181CF0  addi r0,r3,0xC0    u16 DE3E                         [ADDED]
  0x80181D44  fadds f0,f1,f0     DE38 += 0.25                     [ADDED]
  0x80181D54  addi r0,r3,0x80    u16 DE40                         [ADDED]
  These 7 per-frame accumulators (Hxs2_Circle star rings and the stamp
  fade) are NOT handled by BSE: disagreement noted, fixed here.

GAMEOVER (Hx_GameOver ; r29 = 0x803C1278, (delta, duration) table at +0x70)
  0x801804B0  stw r0,0x3c(r31)  (0x32)  -> TIMER_R0            [BSE] high
  0x801804E8  stw r0,0x3c(r31)  (0x0A)  -> TIMER_R0            [BSE] high
  0x801804F8  fadds f0,f1,f0    C6BC(mag) += 0.074 (f1) -> f0 = f0 + f1/M
              (BSE: 0x801804EC, returns 0.074/M; same effect)   high
  0x80180510  fadds f0,f2,f0    DE4C(fade) += 5.1 (f2) -> f0 = f0 + f2/M
              (BSE: 0x80180514)                                high
  0x80180548  stw r3,DE54       1st table duration (6.0) -> GO_TIMER_R3
              **Missing from BSE**: BSE divides the 1st delta (0x80180538) but
              leaves its duration at 6 frames -> the 1st bounce only reaches 1/M
              of its amplitude and shifts all following ones. Disagreement. high
  0x80180558  fsubs f0,f1,f0    C6BC -= 0.1 (f0) -> f0 = f1 - f0/M
              (BSE: 0x8018055C)                                high
  0x801805BC  stw r3,DE54       following durations -> GO_TIMER_R3 [BSE] high
  0x801805E0  stw r3,0x3c(r31)  (0x20) -> TIMER_R3 ; r0 = 0xFF live (next stb),
              untouched. BSE rewrites 0x801805E0/E4 for the same
              result.                                          high
  0x801805F4  fadds f0,f1,f0    C6BC += DE58 (table delta, f0) -> f1 + f0/M
              Replaces BSE's three SMS_WRITE_32 (0x8018059C/A8/AC) and its
              two delta divisions (0x80180538, 0x801805B0): the increment is
              divided where it is applied, DE58 keeps the table value. One site
              instead of five.                                   high
  0x80180610  stw r0,0x3c(r31)  (0x64) -> TIMER_R0             [BSE] high
  0x80180624  addi r0,r3,8      alpha u8 DE5C += 8 -> r3 + 8/M
              (BSE: 0x80180628, 8/(u8)M; identical). Over 0x20×M frames the
              sum is always 256: alpha starts at 0xFF, wraps once and returns
              to 0xFF, as at 30 FPS.                             high
  0x80180500  bl Hx_MotionUpdate: covered by the global replacement.

TEST1   0x8017F5BC  stw r0,0x3c(r30) (0x19) -> TIMER_R0         [BSE] high
TEST2   0x8017EFA0 / F014 / F0D0 / F1C0  stw r0,0x3c(r31) -> TIMER_R0 [BSE]
TEST2R  0x8017EB74 / EC90 / ED90 / EE5C  stw r0,0x3c(r31) -> TIMER_R0 [BSE]
        At all 8 sites, r3 (argument of the following Hx_MotionSet) is live:
        the stubs do not touch it.                               high

TEST4 (Hx_Test4)
  DE88 (u32, segment count) = cvt(DE88 + DE90) every frame, DE90 = ±5;
  DE84 += DE8C (±0.15). The integer would lose the fractions of 5/M: like BSE
  we keep a float accumulator (T4STATE, own state, outside [OnFrame]).
  0x8017E50C / 0x8017E530  stw r0,DE88 (0 or 230) -> T4INIT: same stw, then
              T4STATE = (float)r0. f0/f1/f2 (stored right after) untouched.
              (BSE: 0x8017E518 / 0x8017E53C.)
  0x8017E544  stw r0,0x3c(r31) (0x26) -> TIMER_R0              [BSE]
  0x8017E578  bl __cvt_fp2unsigned -> bl T4ACC: T4STATE += f0/M (f0 = DE90
              loaded at 0x8017E564), then tail jump to
              __cvt_fp2unsigned(T4STATE) — which returns 0 for a negative
              (compares to 0.0 @0x803AA8E8), hence BSE's Max(0,·).
  0x8017E588  fadds f0,f1,f0  DE84 += DE8C -> f0 = f1 + f0/M
              (BSE divides DE8C when arming; here when applying.)
  Confidence high.

TEST5 (Hx_Test5)
  BSE only decrements the counter one frame in M (u8 toggle never reset
  -> arbitrary phase, stair-stepped animation). Here: duration
  20×M (0x8017E07C stw r0 -> TIMER_R0) and divisor 20.0 -> 20×M
  (0x8017E14C ``lfs f1,-0x4614(r2)`` = 20.0 -> bl T5DIV, f1 = 20×M; f0 is
  reloaded at 0x8017E15C, r0 already stored at 0x8017E148). The ratio
  timer/20 = f3 (0x8017E164–E174) follows the same curve, in 20×M steps
  instead of 20. Stateless. The 20.0 literal @0x8041258C is shared
  (Hx_Circle, etc.): it is not modified. Disagreement with BSE
  (deliberate).                                                high

MOTION (Hx_MotionUpdate 0x80181D74, leaf, f0/f1/r3 only)
  ``b MOTION`` on the 1st instruction; called by ``bl`` from 14 sites
  (xref), so r12/f13 are volatile per the ABI. fcmpo -> fcmpu (only
  difference: no exception on NaN). For a trapezoidal Hx_MotionSet motion
  (2/8/1 frames, Test2), the final distance stays 9.5 × vmax at M = 1, 2 and 4
  (checked by hand): wipes end at the same place.
  Hx_Door has no countdown (ends on position): correct with the Motion
  replacement alone.
  **Hx_Logo** (0x8017FACC): its durations come from a table and are not
  scaled (nor by BSE, which forces 30 FPS during the logo). To avoid
  desynchronising motion and duration if M ≠ 1 during the logo, this call is
  redirected to MOTION_ORIG (original instruction + ``b 0x80181D78``): the
  logo keeps its original behaviour, consistent but M times too fast.

NOT VERIFIED
------------
* That TSMSFader::draw (virtual call, no direct xref) is really called once
  per rendered frame and not per substep. Strong hints: Hx_UpdateWipe
  brackets the call with GXDrawDone, and wipes emit GX primitives.
  Same assumption as BSE.
* Nothing was run in Dolphin (forbidden by the brief): neither the actual
  wipe duration at 120 FPS nor the rendering of the Hx_Circle rings.
* Hx_Logo remains unfixed (M times too fast if M ≠ 1 during the logo).
  Dependency: the agent that puts the game back to 30 FPS in boot/logo/intro.

Code cave layout (0x80001800–0x80001FFF)
----------------------------------------
  0x80001800  f64  MAGIC  0x43300000_00000000       constant (profile)
  0x80001808  u32  0x43300000                        constant (profile)
  0x8000180C  u32  SCR_LO  integer input             state, NOT in profile
  0x80001810  f64  SCR2    fctiwz output             state, NOT in profile
  0x80001818  f32  T4STATE TEST4 accumulator         state, NOT in profile
  0x8000181C–0x800018AF  free (0x800018A8 = Dolphin HLE hook, never execute)
  0x800018B0  code
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

RANGE = (0x80001800, 0x80002000)

BASE = 0x80001800
# Offsets from r12 = 0x80000000 ("lis r12, 0x8000" in every routine), hence
# ABSOLUTE within the low page: 0x1800 + offset in the cave. Until 2026-09-27
# they were 0x00–0x18: the routines wrote into the disc header (0x8000000C…)
# and read 0x80000000 as the conversion constant — HX timer saturated, endless
# wipe, emulation at 13 fields/s.
LOW = 0x80000000
MAGIC = BASE - LOW + 0x00     # f64 0x4330000000000000
SCR = BASE - LOW + 0x08       # f64: hi 0x43300000 (constant), lo = input (state)
SCR_LO = BASE - LOW + 0x0C
SCR2 = BASE - LOW + 0x10      # f64: fctiwz output (state)
T4STATE = BASE - LOW + 0x18   # f32: TEST4 accumulator (state)
# Code starts AFTER 0x800018A8: Dolphin puts its "GeckoCodehandler" HLE hook
# there (Gecko::ENTRY_POINT). Any instruction executed at that address
# increments the word at 0x80001800 and flushes the WHOLE JIT cache
# (HLE_Misc::GeckoCodeHandlerICacheFlush → iCache.Reset). Until 2026-09-27
# the code started at 0x80001820 and INT_STEP landed on 0x800018A8: three
# flushes per frame during Hx_Circle, emulation at 8 fields/s.
CODE = 0x800018B0

TIMER_ADDR = 0x803F43FC
CVT_FP2UNSIGNED = 0x8033829C
MOTION_FN = 0x80181D74

# M = 2 × f32@0x804167B8 in f13 (clobbers r12).
LOAD_M = """
    lis    r12, 0x8041
    lfs    f13, 0x67B8(r12)
    fadds  f13, f13, f13
"""

# Each ROUTINES entry: (name, source). A source may reference {name} of an
# earlier routine (address resolved at assembly time).


def _timer_core(dest: str) -> str:
    """SCR_LO holds the unsigned integer x; writes (int)(x × M) to dest."""
    return f"""
    lfd    f13, {SCR}(r12)
    lfd    f12, {MAGIC}(r12)
    fsub   f12, f13, f12
    {LOAD_M}
    fmul   f12, f12, f13
    fctiwz f12, f12
    {dest}
    blr
"""


TIMER_DEST_HX = f"""
    lis    r12, {TIMER_ADDR >> 16:#x}
    ori    r12, r12, {TIMER_ADDR & 0xFFFF:#x}
    stfiwx f12, 0, r12
"""
TIMER_DEST_GO = """
    li     r12, -0x636C
    stfiwx f12, r13, r12
"""


def _fstep(op: str, dst: str, old: str, inc: str) -> str:
    """Redoes "op dst, old, inc" with inc / M."""
    return f"""
    {LOAD_M}
    fdivs  f13, {inc}, f13
    {op}   {dst}, {old}, f13
    blr
"""


def _int_stub(imm: int) -> str:
    return f"""
    li     r0, {imm:#x}
    b      {{INT_STEP}}
"""


ROUTINES: list[tuple[str, str]] = [
    # HX countdown (0x803F43FC)
    ("TIMER_R0", f"""
    lis    r12, 0x8000
    stw    r0, {SCR_LO:#x}(r12)
""" + _timer_core(TIMER_DEST_HX)),
    ("TIMER_R3", f"""
    lis    r12, 0x8000
    stw    r3, {SCR_LO:#x}(r12)
    b      {{TIMER_R0}}+8
"""),
    # GameOver segment duration (DE54)
    ("GO_TIMER_R3", f"""
    lis    r12, 0x8000
    stw    r3, {SCR_LO:#x}(r12)
""" + _timer_core(TIMER_DEST_GO)),
    # r0 = r3 + r0 / (int)M
    ("INT_STEP", f"""
    {LOAD_M}
    fctiwz f13, f13
    lis    r12, 0x8000
    stfd   f13, {SCR2:#x}(r12)
    lwz    r12, {SCR2 + 4:#x}(r12)
    divwu  r0, r0, r12
    add    r0, r3, r0
    blr
"""),
    # Hx_MotionUpdate with step 1/M
    ("MOTION", f"""
    {LOAD_M}
    lfs    f0, 0(r3)
    lfs    f1, 0x1c(r3)
    fcmpu  cr0, f0, f1
    ble    decel
    lfs    f1, 0x18(r3)
    lfs    f0, 0xc(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x18(r3)
    b      tick
decel:
    lfs    f0, 4(r3)
    fcmpu  cr0, f0, f1
    cror   2, 0, 2
    bne    tick
    lfs    f1, 0x18(r3)
    lfs    f0, 0x14(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x18(r3)
tick:
    lfs    f1, 0x1c(r3)
    lfs    f0, -0x460c(r2)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x1c(r3)
    lfs    f1, 0x20(r3)
    lfs    f0, 0x18(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x20(r3)
    lfs    f1, 0x20(r3)
    blr
"""),
    # Original version for Hx_Logo: the overwritten 1st instruction, then the rest.
    ("MOTION_ORIG", f"""
    lfs    f0, 0(r3)
    b      {MOTION_FN + 4:#x}
"""),
    ("T4INIT", f"""
    stw    r0, -0x6338(r13)
    lis    r12, 0x8000
    stw    r0, {SCR_LO:#x}(r12)
    lfd    f13, {SCR:#x}(r12)
    lfd    f12, {MAGIC:#x}(r12)
    fsub   f13, f13, f12
    frsp   f13, f13
    stfs   f13, {T4STATE:#x}(r12)
    blr
"""),
    ("T4ACC", f"""
    {LOAD_M}
    fdivs  f13, f0, f13
    lis    r12, 0x8000
    lfs    f1, {T4STATE:#x}(r12)
    fadds  f1, f1, f13
    stfs   f1, {T4STATE:#x}(r12)
    b      {CVT_FP2UNSIGNED:#x}
"""),
    # TEST5: divisor 20.0 -> 20 × M
    ("T5DIV", f"""
    {LOAD_M}
    lfs    f1, -0x4614(r2)
    fmuls  f1, f1, f13
    blr
"""),
    # Per-frame float increments
    ("F_CIRCLE_DE44", _fstep("fadds", "f1", "f2", "f1")),
    ("F_A1_PLUS_F0", _fstep("fadds", "f0", "f1", "f0")),   # f0 = f1 + f0/M
    ("F_F0_PLUS_F1", _fstep("fadds", "f0", "f0", "f1")),   # f0 = f0 + f1/M
    ("F_F0_PLUS_F2", _fstep("fadds", "f0", "f0", "f2")),   # f0 = f0 + f2/M
    ("F_F1_MINUS_F0", _fstep("fsubs", "f0", "f1", "f0")),  # f0 = f1 - f0/M
    # Per-frame integer increments
    ("I_0x180", _int_stub(0x180)),
    ("I_0xC0", _int_stub(0xC0)),
    ("I_0x80", _int_stub(0x80)),
    ("I_0x8", _int_stub(0x8)),
]

# (site, routine, expected original instruction, comment)
SITES: list[tuple[int, str, int, str]] = [
    # CIRCLE
    (0x80181B54, "TIMER_R0", 0x901F003C, "Circle timer 0x19"),
    (0x80181B78, "TIMER_R0", 0x901F003C, "Circle timer 0x1E"),
    (0x80181BBC, "F_CIRCLE_DE44", 0xEC22082A, "Circle DE44 += 1/15 (ajout)"),
    (0x80181C7C, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE30 += 0.05 (ajout)"),
    (0x80181C8C, "I_0x180", 0x38030180, "Circle DE3C += 0x180 (ajout)"),
    (0x80181CE0, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE34 += 0.12 (ajout)"),
    (0x80181CF0, "I_0xC0", 0x380300C0, "Circle DE3E += 0xC0 (ajout)"),
    (0x80181D44, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE38 += 0.25 (ajout)"),
    (0x80181D54, "I_0x80", 0x38030080, "Circle DE40 += 0x80 (ajout)"),
    # GAMEOVER
    (0x801804B0, "TIMER_R0", 0x901F003C, "GameOver timer 0x32"),
    (0x801804E8, "TIMER_R0", 0x901F003C, "GameOver timer 0x0A"),
    (0x801804F8, "F_F0_PLUS_F1", 0xEC01002A, "GameOver C6BC += 0.074"),
    (0x80180510, "F_F0_PLUS_F2", 0xEC02002A, "GameOver DE4C += 5.1"),
    (0x80180548, "GO_TIMER_R3", 0x906D9C94, "GameOver DE54 1re durée (ajout)"),
    (0x80180558, "F_F1_MINUS_F0", 0xEC010028, "GameOver C6BC -= 0.1"),
    (0x801805BC, "GO_TIMER_R3", 0x906D9C94, "GameOver DE54 durées"),
    (0x801805E0, "TIMER_R3", 0x907F003C, "GameOver timer 0x20"),
    (0x801805F4, "F_A1_PLUS_F0", 0xEC01002A, "GameOver C6BC += DE58"),
    (0x80180610, "TIMER_R0", 0x901F003C, "GameOver timer 0x64"),
    (0x80180624, "I_0x8", 0x38030008, "GameOver alpha DE5C += 8"),
    # TEST1 / TEST2 / TEST2R
    (0x8017F5BC, "TIMER_R0", 0x901E003C, "Test1 timer 0x19"),
    (0x8017EFA0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0B"),
    (0x8017F014, "TIMER_R0", 0x901F003C, "Test2 timer 0x0B"),
    (0x8017F0D0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0A"),
    (0x8017F1C0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0C"),
    (0x8017EB74, "TIMER_R0", 0x901F003C, "Test2R timer 0x0B"),
    (0x8017EC90, "TIMER_R0", 0x901F003C, "Test2R timer 0x0B"),
    (0x8017ED90, "TIMER_R0", 0x901F003C, "Test2R timer 0x0A"),
    (0x8017EE5C, "TIMER_R0", 0x901F003C, "Test2R timer 0x0C"),
    # TEST4
    (0x8017E50C, "T4INIT", 0x900D9CC8, "Test4 DE88 = 0 / état"),
    (0x8017E530, "T4INIT", 0x900D9CC8, "Test4 DE88 = 230 / état"),
    (0x8017E544, "TIMER_R0", 0x901F003C, "Test4 timer 0x26"),
    (0x8017E578, "T4ACC", None, "Test4 bl __cvt_fp2unsigned -> accumulateur"),
    (0x8017E588, "F_A1_PLUS_F0", 0xEC01002A, "Test4 DE84 += DE8C"),
    # TEST5
    (0x8017E07C, "TIMER_R0", 0x901F003C, "Test5 timer 0x14"),
    (0x8017E14C, "T5DIV", 0xC022B9EC, "Test5 diviseur 20.0"),
    # MOTION (Logo redirected to the original first, then the function itself)
    (0x8017FACC, "MOTION_ORIG", None, "Hx_Logo bl Hx_MotionUpdate -> original"),
]
SITE_MOTION = (MOTION_FN, "MOTION", 0xC0030000, "Hx_MotionUpdate -> b MOTION")


def _assemble_all() -> dict[str, tuple[int, bytes]]:
    out: dict[str, tuple[int, bytes]] = {}
    addr = CODE
    for name, src in ROUTINES:
        resolved = src
        for other, (a, _) in out.items():
            resolved = resolved.replace("{" + other + "}", f"{a:#x}")
        code = assemble(resolved, addr)
        assert code, name
        out[name] = (addr, code)
        addr += (len(code) + 3) & ~3
    return out


def _data() -> list[tuple[int, int]]:
    """Constants only; SCR_LO, SCR2 and T4STATE are state and are excluded."""
    return [
        (LOW + MAGIC, 0x43300000),
        (LOW + MAGIC + 4, 0x00000000),
        (LOW + SCR, 0x43300000),
    ]


def build() -> list[tuple[int, int]]:
    caves = _assemble_all()
    patches = _data()
    for addr, code in caves.values():
        patches += words(addr, code)
    for site, name, _orig, _c in SITES:
        target = caves[name][0]
        patches += words(site, assemble(f"bl {target:#x}", site))
    site, name, _orig, _c = SITE_MOTION
    patches += words(site, assemble(f"b {caves[name][0]:#x}", site))
    return patches


def main() -> int:
    import capstone

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dol import Dol

    root = Path(__file__).resolve().parents[2]
    dol = Dol(root / "work" / "dol" / "GMSE01.dol")
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)

    def dis(addr: int, raw: bytes) -> str:
        rows = [f"{i.mnemonic:<8}{i.op_str}" for i in cs.disasm(raw, addr)]
        return rows[0] if rows else f".word {raw.hex()}"

    caves = _assemble_all()
    for name, (addr, code) in caves.items():
        print(f"; {name} @ {addr:08X}")
        for i in range(0, len(code), 4):
            w = code[i:i + 4]
            print(f"  {addr + i:08X}  {w.hex().upper()}  {dis(addr + i, w)}")
    print()

    patches = build()
    cave_end = max(a + len(c) for a, c in caves.values())
    print(f"cave : {CODE:08X}–{cave_end:08X}  ({cave_end - RANGE[0]} octets sur {RANGE[1] - RANGE[0]})")
    for a, _ in patches:
        if RANGE[0] <= a < RANGE[1]:
            assert a not in (LOW + SCR_LO, LOW + SCR2, LOW + SCR2 + 4, LOW + T4STATE), hex(a)
    assert cave_end <= RANGE[1]

    print("\n; sites (avant -> après)")
    site_words = dict(patches)
    for site, name, orig, comment in SITES + [SITE_MOTION]:
        before = dol.u32(site)
        if orig is not None:
            assert before == orig, f"{site:08X}: {before:08X} != {orig:08X}"
        after = site_words[site]
        print(f"  {site:08X}  {before:08X} {dis(site, before.to_bytes(4, 'big')):<28} -> "
              f"{after:08X} {dis(site, after.to_bytes(4, 'big')):<16} ; {comment}")

    sites = {s for s, *_ in SITES} | {SITE_MOTION[0]}
    for a, _ in patches:
        assert a in sites or RANGE[0] <= a < RANGE[1], hex(a)
    print(f"\n{len(patches)} mots ; [OnFrame] :")
    for a, v in patches:
        print(f"0x{a:08X}:dword:0x{v:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
