"""Group "contexts forced to 30 FPS" — port of BSE fps.cpp l. 34-65 (updateFPS) and l. 509-514 (QFSync).

Principle
=========
The f32 literal 0x804167B8 (read by SMSGetVSyncTimesPerSec = 60 x lit, and by
SMSGetAnmFrameRate) and TDisplay::mRetraceCount (+0x4C) are no longer set by
[OnFrame]: a code cave routine writes them according to the current TApplication
context, before each director is set up AND at the start of each frame. The
other groups re-read M = 2 x lit at run time, so all their fixes follow
(M = 1 in a forced context, 4 otherwise).

    context (gpApplication.mAppState, u8 +0x08)    literal   mRetraceCount   rate
    0..4  (LOAD_LOOP, MAIN_LOOP, BOOT, LOGO, INTRO)  0.5f        5              29.97
    5..9  (STAGE, MOVIE, SHUTDOWN, SELECT, MENU)     2.0f        2             119.88

EXISTING [OnFrame] LINES TO REMOVE / KEEP (deliver/GMSE01.ini)
==============================================================
  * MUST REMOVE:  0x804167B8:dword:0x40000000
      Otherwise the PatchEngine rewrites 2.0f on every VI field, in the middle
      of a frame forced to 0.5f: logic clock and M inconsistent from one field
      to the next. Without this line, the word is 0.5f (DOL value) until the
      routine's first pass — the desired value for boot.
  * KEEP:  0x802FCB24:dword:0x60000000  (the counts 2 and 5 below assume the
      final wait of waitForRetrace is neutralised).
  * No other existing line is touched.
  * Tools: tools/keep120.py (rewrites 0x804167B8 = 2.0 and +0x4C as data)
    must no longer be run with this profile; tools/validate_120.py will report
    [NON] on the literal during boot / logo / intro — that is expected.

Addresses and offsets (evidence)
================================
  gpApplication = 0x803E9700  (us.map; and proc 802A639C lis r4,0x803F / 802A63B4 addi r26,r4,-0x6900)
  mAppState  +0x08 u8   gameLoop 802A60A0 lbz r0,8(r31) ; cmplwi r0,2 (BOOT)
                        proc 802A67C8 lbz r0,8(r31) ; 802A6794 stb r30,8(r31)
  mDisplay   +0x1C      gameLoop 802A5F98 lwz r3,0x1c(r31) then virtual call startRendering
  mRetraceCount +0x4C   endRendering 802F80E8 lhz r4,0x4c(r31) ; 802F80EC bl waitForRetrace
  TMarDirector::mCurState +0x64 u8  direct 802999D8 lbz r0,0x64(r26) ; ctor 80297124 stb r30,0x64(r29)

Context enumeration — BSE (SunshineHeaderInterface, Application.hxx):
LOAD_LOOP 0, MAIN_LOOP 1, GAME_BOOT 2, GAME_BOOT_LOGO 3, GAME_INTRO 4, DIRECT_STAGE 5,
DIRECT_MOVIE 6, GAME_SHUTDOWN 7, SHINE_SELECT 8, LEVEL_SELECT 9. Cross-checked with the
decompilation (APP_STATE_WAIT 0 … MENU 9) and proc's jump table at 0x803DF424 read in the DOL:
  2 -> 802A63E4 SMSSetupGCLogoRenderingInfo only                (BOOT)
  3 -> 802A63F0 TGCLogoDir::setup                               (Nintendo LOGO)
  4 -> 802A65D8 mMovie = 9, mNextArea = 15, then TMovieDirector (INTRO)
  5 -> 802A64A0 checkAdditionalMovie / TMarDirector::setup       (STAGE)
  6 -> 802A65F4 TMovieDirector                                  (MOVIE)
  8 -> 802A6580 TSelectDir::setup ; 9 -> 802A6428 TMenuDirector::setup ; 0,1,7 -> 802A6644 (nothing)
0 and 1 are never the value of mAppState in practice (gameLoop loops while
nextState <= 1, 802A635C cmplwi r29,1 / ble); they are included as in BSE, with no effect.

mRetraceCount for 30 FPS = 5 (not 2 as in BSE)
-----------------------------------------------
waitForRetrace, with 802FCB24 (final bl VIWaitForRetrace) replaced by nop:
  802FC9C8 bl VIWaitForRetrace / 802FC9CC bl VIGetRetraceCount / 802FC9D0 lwz r0,0x84(r30)
  802FC9D4 subf r0,r3,r0 / 802FC9D8 cmpwi r0,1 / 802FC9DC bgt 802FC9C8   -> waits until next - count <= 1
  802FCB30 bl VIGetRetraceCount / 802FCB34 clrlwi r0,r31,16 / 802FCB38 add / 802FCB3C stw r0,0x84(r30)
  -> next = count + mRetraceCount. In steady state: mRetraceCount - 1 fields per frame.
  120 FPS: 2 -> 1 field (119.88/s). 30 FPS: 4 fields wanted -> mRetraceCount = 5.
BSE writes 2 / 1 / 0 because its final wait is intact (fields = max(1, mRetraceCount)).
No writer of +0x4C in SMSSetup{Movie,Game,Title,GCLogo}RenderingInfo (read up to the blr).

Fix 1 — context selection (BSE updateFPS)
=========================================
"core" routine (r31 = &gpApplication at both sites): reads mAppState; if <= 4 writes
0.5f to 0x804167B8 and 5 to mDisplay->mRetraceCount, otherwise 2.0f and 2. The two
literal values are code cave constants (0x80002800 / 0x80002804): the "normal"
tier is changed there. Two call sites:

  a) 0x802A63C4  proc+0x2C  "cmplwi r0, 9" (switch head, single target: 802A67D0 bne)
     -> bl entry_proc, which calls core then redoes lbz r0,8(r31) / cmplwi r0,9 (cr0 read
     by 802A63D0 bgt; the li r30 / li r29 in between do not touch cr0).
     Why here: it is BEFORE the new context's director is constructed. In BSE,
     updateFPS runs just before direct() (hook 0x802A616C), so a director's setup
     still sees the previous context's literal (e.g. TMarDirector::setup after the
     intro at 30). Here setup sees its own context's literal: stage setup at 2.0 as
     in the already measured 120 profile, TGCLogoDir (ctor 802963C0 bl
     SMSGetVSyncTimesPerSec ; 802963CC stfs f1,0x28) at 30 like the original.
     Minor DISAGREEMENT with BSE, deliberate.
  b) 0x802A5F98  gameLoop+0x48  "lwz r3, 0x1c(r31)" (frame loop head, single
     target: 802A6360 ble) -> bl entry_frame, which calls core then executes the lwz.
     r0/r4-r6/r11 are dead at this point (802A5F9C lwz r12,0(r3); r0 rewritten at
     802A5FC4). Redundant with (a) as long as nothing else writes +0x4C or the literal;
     a negligible-cost safeguard, and it covers BOOT/LOGO, which the BSE hook
     (0x802A616C, "else" branch of gameLoop) does not.
  Order within the frame: core -> startRendering -> direct() -> endRendering/waitForRetrace:
  the literal and mRetraceCount hold for the whole frame.

Fix 2 — QFSync: 30 "vsync/s" in TMarDirector::direct during STATE_INTRO_INIT
============================================================================
Site 0x80299850 direct+0x18 "bl SMSGetVSyncTimesPerSec" (r3 = this, 8029984C mr r26,r3)
-> bl qfsync: if this->mCurState (+0x64) == 0 (STATE_INTRO_INIT, SunshineHeaderInterface
MarDirector.hxx) returns f1 = 30.0f, otherwise tail jump to SMSGetVSyncTimesPerSec
(lr intact -> returns to 80299854). Effect: vsyncRate = 600/30 = 20 -> 4 substeps for the
stage's first frame, as in the original game, before the first draw.
BSE also tests mContext == DIRECT_STAGE and mDirector != 0: implicit here, a TMarDirector
only exists in context 5 (802A6550 bl __ct__12TMarDirector, the only case in the table) and
direct() receives this.
Duration: changeState has a single caller (xref: 80299D0C), INSIDE the substep loop
(80299D20 b 8029994C, back to the loop head); its case 0 (80298EC4…) picks the next
state without a counter. State 0 is therefore left on the first substep, but vsyncRate
has already been computed (20) at the top of direct(): the stage's first "full" frame
has 4 substeps, the following ones 1. Frames where the setup thread has not finished
exit at 80299890, BEFORE the accumulator (80299938-80299944), and do not count.
NOT VERIFIED: the exact bug BSE fixes this way (probably objects that must have
received several substeps before the first draw). Faithful port, bounded cost (3 extra
substeps, 25 ms of simulation, once per stage entry).

Accumulator (TMarDirector +0x54) on context changes
===================================================
80299938-80299944: unk54 += 600/(int)SMSGetVSyncTimesPerSec(); the loop subtracts 5 per
substep and stops as soon as unk54 < 5 (80299980 cmpwi r0,5), so the remainder is always
in [0,5). A vsyncRate change (5 <-> 20) can create neither a burst nor a debt: it only
changes the substep count of the next frame (1 or 4). Moreover the literal only changes
between two directors (mAppState is only written at 802A6794, outside gameLoop), and each
TMarDirector starts from unk54 = 0 (ctor 802970A4 stw r30,0x54(r29); r30 = 0 NOT formally
VERIFIED, same register as mCurState = 0). The only mid-stage change is QFSync, bounded
above.

Dependencies / effects on other groups
======================================
  * All groups read M = 2 x f32[0x804167B8]: M = 1 in boot/logo/intro, 4 otherwise.
  * Fader (fader.py, Fix 3): TApplication::initialize (802A7730) constructs mFader BEFORE
    proc, hence with the DOL literal (0.5 -> rate 30), since the [OnFrame] line for the
    literal is removed. Consistent with the "+0x14 = 30" assumption of this group and of BSE.
  * TMenuDirector (ctor 802A4250) and TMovieDirector::direct (802B6388) see 120:
    unchanged from the current profile. THP movies (context 6, and 5 if
    checkAdditionalMovie) stay at 120 as in BSE — NOT VERIFIED on screen.
  * drawDVDErr (802A5EFC) reads the same literal: the message is centred correctly only in
    a forced context (side effect already known in the profile).
  * The PatchEngine rewrites the code cave and site words on every field: idempotent
    writes, no mutable state in the code cave.

NOT VERIFIED (global): run-time behaviour — nothing was run in Dolphin.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002800
CAVE_END = 0x80002C00  # exclusive

# Data (constants, safe for the profile to rewrite)
LIT_FAST = 0x80002800   # 2.0f  literal outside forced contexts (120 tier)
LIT_SLOW = 0x80002804   # 0.5f  literal in forced contexts (30 FPS)
QF_CONST = 0x80002808   # 30.0f QFSync value
CODE = 0x80002810
DEBUG_FORCE30 = 0x80002BFC  # u32, diagnostic: non-zero = 30 FPS everywhere (state, never written by the profile)

RC_FAST = 2   # mRetraceCount for the 120 tier (1 field, final wait neutralised)
RC_SLOW = 5   # mRetraceCount for 30 FPS (4 fields)
MAX_FORCED_STATE = 4  # contexts 0..4 are forced

LITERAL = 0x804167B8
SMS_GET_VSYNC = 0x802A7C48

SITE_PROC = 0x802A63C4    # cmplwi r0, 9
SITE_FRAME = 0x802A5F98   # lwz r3, 0x1c(r31)
SITE_QFSYNC = 0x80299850  # bl SMSGetVSyncTimesPerSec

ORIGINAL = {
    SITE_PROC: 0x28000009,
    SITE_FRAME: 0x807F001C,
    SITE_QFSYNC: 0x4800E3F9,
}


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def _core_source() -> str:
    return f"""
    lis    r4, 0x8000
    lwz    r3, {DEBUG_FORCE30 - 0x80000000:#x}(r4)
    cmpwi  r3, 0
    bne    forced
    lbz    r3, 8(r31)
    cmplwi r3, {MAX_FORCED_STATE}
    ble    forced
    lwz    r5, {LIT_FAST - 0x80000000:#x}(r4)
    li     r6, {RC_FAST}
    b      store
forced:
    lwz    r5, {LIT_SLOW - 0x80000000:#x}(r4)
    li     r6, {RC_SLOW}
store:
    lis    r4, {LITERAL >> 16:#x}
    stw    r5, {LITERAL & 0xFFFF:#x}(r4)
    lwz    r3, 0x1c(r31)
    cmplwi r3, 0
    beq    done
    sth    r6, 0x4c(r3)
done:
    blr
"""


def build_blocks() -> dict[str, tuple[int, bytes]]:
    core_addr = CODE
    core = assemble(_core_source(), core_addr)

    frame_addr = core_addr + len(core)
    frame = assemble(f"""
    mflr   r11
    bl     {core_addr:#x}
    mtlr   r11
    lwz    r3, 0x1c(r31)
    blr
""", frame_addr)

    proc_addr = frame_addr + len(frame)
    proc = assemble(f"""
    mflr   r11
    bl     {core_addr:#x}
    mtlr   r11
    lbz    r0, 8(r31)
    cmplwi r0, 9
    blr
""", proc_addr)

    qf_addr = proc_addr + len(proc)
    qf = assemble(f"""
    lbz    r0, 0x64(r3)
    cmplwi r0, 0
    beq    intro
    b      {SMS_GET_VSYNC:#x}
intro:
    lis    r4, 0x8000
    lfs    f1, {QF_CONST - 0x80000000:#x}(r4)
    blr
""", qf_addr)

    return {
        "core": (core_addr, core),
        "entry_frame": (frame_addr, frame),
        "entry_proc": (proc_addr, proc),
        "qfsync": (qf_addr, qf),
    }


def build() -> list[tuple[int, int]]:
    blocks = build_blocks()
    patches: list[tuple[int, int]] = [
        (LIT_FAST, _f32(2.0)),
        (LIT_SLOW, _f32(0.5)),
        (QF_CONST, _f32(30.0)),
    ]
    for addr, code in blocks.values():
        patches += words(addr, code)
    # Call sites last.
    patches += words(SITE_QFSYNC, assemble(f"bl {blocks['qfsync'][0]:#x}", SITE_QFSYNC))
    patches += words(SITE_PROC, assemble(f"bl {blocks['entry_proc'][0]:#x}", SITE_PROC))
    patches += words(SITE_FRAME, assemble(f"bl {blocks['entry_frame'][0]:#x}", SITE_FRAME))
    return patches


def _listing(address: int, code: bytes) -> str:
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    return "\n".join(
        f"  {i.address:08X}  {int.from_bytes(i.bytes, 'big'):08X}  {i.mnemonic:<8}{i.op_str}"
        for i in cs.disasm(code, address)
    )


def main() -> int:
    blocks = build_blocks()
    patches = build()
    sites = set(ORIGINAL)

    for name, (addr, code) in blocks.items():
        print(f"; {name} @ {addr:08X}")
        print(_listing(addr, code))
        print()

    print("; sites (avant -> après)")
    for addr, value in patches:
        if addr in sites:
            before = _listing(addr, ORIGINAL[addr].to_bytes(4, "big"))
            after = _listing(addr, value.to_bytes(4, "big"))
            print(before)
            print(after)
            print()

    root = Path(__file__).resolve().parents[2]
    dol_path = root / "work" / "dol" / "GMSE01.dol"
    if dol_path.exists():
        from dol import Dol
        dol = Dol(dol_path)
        for addr, orig in ORIGINAL.items():
            got = dol.u32(addr)
            assert got == orig, f"{addr:08X}: DOL {got:08X} != attendu {orig:08X}"
        assert dol.u32(LITERAL) == _f32(0.5), "littéral DOL != 0.5f"
        print("; valeurs d'origine des sites vérifiées dans le DOL")

    for addr, _ in patches:
        if addr in sites:
            continue
        assert CAVE_START <= addr and addr + 4 <= CAVE_END, f"{addr:08X} hors de la caverne"
    end = max(a for a, _ in patches if a not in sites) + 4
    print(f"; caverne {CAVE_START:08X}-{end - 1:08X} dans {CAVE_START:08X}-{CAVE_END - 1:08X}")
    print(f"; {len(patches)} mots")
    print()
    for addr, value in patches:
        print(f"0x{addr:08X}:dword:0x{value:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
