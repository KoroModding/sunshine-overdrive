"""Sound effects: speed passed to animation sounds, and a diagnostic log.

1. Speed passed to animation sounds, MAnmSound::animeLoop, 0x80012E9C
   Every actor (TLiveActor::updateAnmSound, TMario::animSound, TYoshi,
   TKoopa, TEnemyManager…) passes MAnmSound::animeLoop the animation speed of
   its frame controller (J3DFrameCtrl+0xC, mFrameRate), which is
   ~SMSGetAnmFrameRate(): 2.0 at 30 FPS, 0.5 at 120 FPS. JAIAnimeSound uses it
   to modulate the pitch and volume of each animation sound:
       pitch  = base + unk15 × (speed − 1) / 32
       volume = base + 2 × unk18 × (speed − 1)
   (Graffito-Decomp, JAIAnimation.cpp: setSpeedModifySound, playActorAnimSound).
   At 120 FPS every modulated animation sound therefore came out lower and
   quieter. The routine multiplies the speed by M before the call, restoring
   the 30 FPS value. Side effect: the look-ahead window at the animation loop
   wrap (mCurrentTime + speed) is again the original game's in animation
   frames, i.e. 4 calls instead of one at 120 FPS; a loop-start sound may fire
   ≤ 1.5 animation frames (~25 ms) early. NOT VERIFIED by ear.

2. Sound start log, DIAGNOSTIC, JAIBasic::startSoundBasic
   Single entry point: startSoundActor, startSoundDirectID,
   startSoundIndirectID and startSoundActorReturnHandle all end up there.
   The entry (mflr r0) is redirected to a routine that writes (sound id, JAI
   pass counter JAIBasic+0x20) into a 64-entry ring:
       0x80002C00  u32  next index (state)
       0x80002C08  64 × (u32 id, u32 frame)
   Read by tools/watch_se_rates.py. The profile writes no state.

Range: 0x80002A00 – 0x80002AFF (code); ring 0x80002C00 – 0x80002E07.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_ANM = 0x80002A00
CAVE_LOG = 0x80002A40
RING = 0x80002C00
RING_ENTRIES = 64

MARIO_RETURN = 0x80285824      # return address of bl animeLoop in TMario::animSound
SPEED_PROBE = 0x80002A30       # f32, last speed passed (state, diagnostic)
SITE_ANM = 0x80012E9C          # bl JAIAnimeSound::setAnimSoundVec
SET_ANIM_SOUND_VEC = 0x80300164
SITE_LOG = 0x803020AC          # mflr r0, entry of startSoundBasic

ORIGINAL = {SITE_ANM: 0x482ED2C9, SITE_LOG: 0x7C0802A6}

# Entry: setAnimSoundVec arguments (f1 = animation frame, f2 = speed). Tail
# jump: LR still points into animeLoop. Clobbers r11, r12, f0, cr0.
# Return address of animeLoop's caller: 0xC(r1) (animeLoop saved LR at
# 4(entry r1), then did stwu r1, -8(r1)).
ASM_ANM = f"""
    lwz    r12, 0xC(r1)
    lis    r11, {MARIO_RETURN >> 16:#x}
    ori    r11, r11, {MARIO_RETURN & 0xFFFF:#x}
    cmplw  r12, r11
    beq    probe
    lis    r12, 0x8041
    lfs    f0, 0x67B8(r12)
    fadds  f0, f0, f0
    fmuls  f2, f2, f0
probe:
    lis    r12, 0x8000
    stfs   f2, {SPEED_PROBE & 0xFFFF:#x}(r12)
    b      {SET_ANIM_SOUND_VEC:#x}
"""

# startSoundBasic entry: r3 = JAIBasic*, r4 = id; r3–r10 preserved.
# Clobbers r0 (rewritten by mflr before resuming), r11, r12, cr0.
ASM_LOG = f"""
    lis    r12, 0x8000
    lwz    r11, 0x2C00(r12)
    addi   r0, r11, 1
    andi.  r0, r0, {RING_ENTRIES - 1}
    stw    r0, 0x2C00(r12)
    rlwinm r11, r11, 3, 0, 28
    add    r11, r11, r12
    stw    r4, 0x2C08(r11)
    lwz    r0, 0x20(r3)
    stw    r0, 0x2C0C(r11)
    mflr   r0
    b      {SITE_LOG + 4:#x}
"""


def build(with_log: bool = False) -> list[tuple[int, int]]:
    anm = assemble(ASM_ANM, CAVE_ANM)
    log = assemble(ASM_LOG, CAVE_LOG)
    assert CAVE_ANM + len(anm) <= SPEED_PROBE, len(anm) and CAVE_LOG + len(log) <= 0x80002B00
    patches = words(CAVE_ANM, anm)
    if with_log:
        patches += words(CAVE_LOG, log)
    patches += words(SITE_ANM, assemble(f"bl {CAVE_ANM:#x}", SITE_ANM))
    if with_log:
        patches += words(SITE_LOG, assemble(f"b {CAVE_LOG:#x}", SITE_LOG))
    return patches


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(CAVE_ANM, assemble(ASM_ANM, CAVE_ANM)))
    print(listing(CAVE_LOG, assemble(ASM_LOG, CAVE_LOG)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
