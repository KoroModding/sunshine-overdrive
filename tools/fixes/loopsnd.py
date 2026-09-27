"""Animation sounds replayed at the loop wrap just before an animation change.

Defect (measured on 2026-09-28, Bianco Gatekeeper, tools/watch_gatekeeper.py
and a trace sampled several times per frame)
=========================================================================
Community report: "the Gatekeeper cries twice on every hit". Cry 0x2891 is
event 0 (animation frame 0, no loop restriction) of the sound table of its
damage animation (animation 3, 120 animation frames, looping).

    frame 72048  animation frame 119.5 -> 0.0, "wrapped" flag (02)
    frame 72049  the damage nerve sees the end and hands over to the next
                 nerve; the sound system sees the loop wrap (loops 0 -> 1)
                 and replays the animation frame 0 event: 2nd cry
    frame 72050  the new nerve starts animation 17 (sounds reset)

Two substeps separate the end of an animation from the change (detect, then
change). At 30 FPS the sound is evaluated only once every 4 substeps
(animation pass, flag 0x2): the change always comes first and the loop wrap is
never seen. At 120 FPS the sound is evaluated every substep and sees it.
Generic pattern: any actor that leaves a looping animation at its end can
replay its loop-start sounds.
Ruled out by measurement: sound and soundsets modules (double cry present
without them), blob melt sound 0x2802 (muted: double cry present).

Fix
===
JAIAnimeSound::setAnimSoundActor (0x8030019C), "forward" mode: at 0x8030038C
(`b 0x803003A8`, entry of the event read loop), detour. If the loop has just
wrapped (prev. animation frame (+0x88) == current animation frame (f30), loop
counter (+0x84) ≠ 0, index (+0x80) == start (+0x7C), a state only the wrap
path produces), the read is skipped for this evaluation (jump to 0x803005CC,
normal exit). The state stays ready: on the next evaluation the loop replays
the start events one frame late (8 ms), unless the animation changed in the
meantime (initActorAnimSound resets everything), as at 30 FPS.
Active only above 30 FPS (literal 0x804167B8 > 0.5, constant 0x80415A94):
boot, logos and original game unchanged. Registers clobbered: r0, r3, r12,
f0, f1, cr0, volatile and not live at this point.

Validated in game by the author (2026-09-28, 1502-word profile): a single cry
per hit, other animation sounds normal. Validated by ear, no reading taken
after the fix.

Possible false positive: an animation frozen (rate 0) exactly at the start of
an already wrapped loop; its start sounds wait until it resumes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE = 0x80001DA4              # 0x80001DA4–0x80001DFF checked zero in MEM1
CAVE_END = 0x80001E00          # widescreen starts at 0x80001E00
SITE = 0x8030038C
ORIGINAL = {SITE: 0x4800001C}  # b 0x803003A8
PLAY_LOOP = 0x803003A8
FUNC_END = 0x803005CC
TARGETS = (PLAY_LOOP, FUNC_END)  # inside setAnimSoundActor, checked on the listing

SRC = f"""
    lis    r12, 0x8041
    lfs    f0, 0x67B8(r12)
    lfs    f1, 0x5A94(r12)
    fcmpu  cr0, f0, f1
    ble    {CAVE + 0x40:#x}
    lfs    f0, 0x88(r24)
    fcmpu  cr0, f0, f30
    bne    {CAVE + 0x40:#x}
    lwz    r0, 0x84(r24)
    cmpwi  r0, 0
    beq    {CAVE + 0x40:#x}
    lwz    r0, 0x80(r24)
    lwz    r3, 0x7c(r24)
    cmpw   r0, r3
    bne    {CAVE + 0x40:#x}
    b      {FUNC_END:#x}
    b      {PLAY_LOOP:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, CAVE)
    assert CAVE + len(code) <= CAVE_END
    return words(CAVE, code) + words(SITE, assemble(f"b {CAVE:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X}"
    print(listing(CAVE, assemble(SRC, CAVE)))
    print(listing(SITE, assemble(f"b {CAVE:#x}", SITE)))
    print(len(build()), "mots")
