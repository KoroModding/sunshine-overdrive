"""JAI fade durations: music, tempo, streams, sound effects.

Defect
======
The JAI layer (MSound::mainLoop -> JAIBasic::startFrameInterfaceWork) runs once
per rendered frame: 30 times per second in the original game, 120 at 120 FPS
(measured in session 6: JAISound+0x14 counter at ~120/s). Every parameter
transition there is counted in passes: JAIMoveParaSet {target +0, current +4,
step +8, counter +0xC}, decremented by one each pass by
JAIData::moveParameter / JAIData::setSeMovePara. A duration written for 30 Hz
therefore elapses 4× too fast at 120 FPS: music fades on area changes and
level exit, tempo speed-up (MSModBgm::changeTempo, 5 and 20 passes), music
ducking during some sounds (seqMuteMoveSpeedSePlay = 3), MSBgmXFade
crossfades (2), sound effect fade-outs (stop with duration), sound fade-in
(JAISound+0x10).

All these paths end up in two places (Graffito-Decomp, JAISound.cpp, re-read in
the DOL):
  - JAISound::initMoveParameter(set, target, duration)   0x8030A3B0: sequences
    (setSeqInterVolume/Pan/Pitch/Fxmix/Dolby, setSeqTempoProportion, port
    data) and streams (setStreamInterVolume/Pitch/Pan);
  - setSeInterMovePara(set, duration), INLINED in the five effect setters:
    setSeInterVolume 0x8030B700, Pan 0x8030B8C8, Fxmix 0x8030BA90,
    Dolby 0x8030BC58, Pitch 0x8030BE20. Duration in r5 on entry to all six.

Only known exception, NOT handled here: JAISound::setSePositionDopplar
(0x8030C690) inlines its own Doppler pitch transition with
JAIGlobalParameter::dopplarMoveTime (15). See docs/00-journal.md, session 7.

Fix
===
Duration multiplied by M on entry to the six functions, M = 2 × literal
0x804167B8 (1 at 30 FPS, 2 at 60, 4 at 120), read at run time. M is a power of
two, so it is derived from the literal's exponent, without floating point:
    shift = exponent(literal) − 126       0.5f -> 0, 1.0f -> 1, 2.0f -> 2
    duration <<= shift
Duration 0 (immediate) unchanged. Duration 1: initMoveParameter special-cases
it as "step = full delta"; ×4 sends it through the division, same real
duration.

Routines (range 0x80002E40 – 0x80002EA7):
    SCALE   r5 <<= shift; clobbers r12. Called with bl.
    SE stub (×5): mflr r0 (original instruction) ; bl SCALE ; b site+4.
        The original LR is already in r0, which the setter saves right after.
    initMoveParameter stub: leaf function, LR must be preserved; r11
        (volatile, not an argument) holds LR around the bl.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_START = 0x80002E40
CAVE_END = 0x80002EA8          # exclusive; 0x80002EA8–0x80002EFF free
SCALE = 0x80002E40

SITE_INIT = 0x8030A3B0         # initMoveParameter: stwu r1, -0x20(r1)
SITES_SE = (
    0x8030B700,                # setSeInterVolume: mflr r0
    0x8030B8C8,                # setSeInterPan
    0x8030BA90,                # setSeInterFxmix
    0x8030BC58,                # setSeInterDolby
    0x8030BE20,                # setSeInterPitch
)
MFLR_R0 = 0x7C0802A6
ORIGINAL = {SITE_INIT: 0x9421FFE0, **{a: MFLR_R0 for a in SITES_SE}}

ASM_SCALE = """
    lis    r12, 0x8041
    lwz    r12, 0x67B8(r12)
    rlwinm r12, r12, 9, 24, 31
    addi   r12, r12, -126
    slw    r5, r5, r12
    blr
"""


def asm_stub_se(site: int) -> str:
    return f"""
    mflr   r0
    bl     {SCALE:#x}
    b      {site + 4:#x}
"""


ASM_STUB_INIT = f"""
    mflr   r11
    bl     {SCALE:#x}
    mtlr   r11
    stwu   r1, -0x20(r1)
    b      {SITE_INIT + 4:#x}
"""


def blocks() -> list[tuple[int, bytes, int]]:
    """(routine address, code, hooked site or 0)."""
    out = [(SCALE, assemble(ASM_SCALE, SCALE), 0)]
    addr = SCALE + len(out[0][1])
    for site in SITES_SE:
        code = assemble(asm_stub_se(site), addr)
        out.append((addr, code, site))
        addr += len(code)
    out.append((addr, assemble(ASM_STUB_INIT, addr), SITE_INIT))
    return out


def build() -> list[tuple[int, int]]:
    patches: list[tuple[int, int]] = []
    sites: list[tuple[int, int]] = []
    for addr, code, site in blocks():
        assert CAVE_START <= addr and addr + len(code) <= CAVE_END, "routine hors zone"
        patches += words(addr, code)
        if site:
            sites += words(site, assemble(f"b {addr:#x}", site))
    # Sites last: routines are in place before they become reachable.
    return patches + sites


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    for addr, code, site in blocks():
        print(f"; {'SCALE' if not site else f'stub {site:08X}'}")
        print(listing(addr, code))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
