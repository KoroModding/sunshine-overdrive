"""Assemble the profile's routines and emit their [OnFrame] lines.

TMarioParticleManager::perform calls JPAEmitterManager::calc()
(int)SMSGetAnmFrameRate() times per frame: 2, 1, then 0 at 120 FPS. The
truncation is replaced by an accumulator, which needs state that survives from
one frame to the next, hence a few instructions outside the original code:
    acc += SMSGetAnmFrameRate();  n = integer part of acc;  acc -= n
i.e. 2 / 1 / alternating 0 and 1: 60 calls per second at every frame rate,
exactly like the original game.

JAI port commands: JAISystemInterface::setSeqPortargsU32 (flags)
   The JAI layer writes a port command's "parameters to apply" flags by
   overwriting them (stw), then forces a requeue (marker +0x2C cleared before
   addPortCmdOnce). If the command is still queued (a much more frequent
   window at 120 Hz), its pending flags are lost. Measured case: the initial
   outerInit command (0xff, tempo included) overwritten by 0x01; tempo never
   applied, multiplier stuck at 0, music frozen.
   Fix: OR the flags if the command is still queued, overwrite otherwise
   (original semantics), with interrupts masked during the read-modify-write;
   and remove the marker clear at both sites so a queued command is not
   chained twice.

Audio routine removed (2026-09-22, session 6): it capped MSound::mainLoop at
30 Hz to fix frozen music. A/B listening test: it dropped Mario animation
sounds (0x1969, sliding on water), and the music loops fine without it. See
docs/00-journal.md, session 6.

Location: 0x80002F00, end of the 0x80001800-0x80003000 area that the game
does not use and Dolphin reserves for the Gecko codehandler. No Gecko code is
active with this profile; the area was measured all-zero in game.

    0x80002F00  f32  particle accumulator   (state, never written by the profile)
    0x80002F04  f32  1.0f                   (constant, written by the profile)
    0x80002F10  code particle routine
    0x80002F40  code JAI port flag merge

The accumulator must NOT be in [OnFrame]: the PatchEngine rewrites its values
every VI field, which would keep resetting it. It starts at zero because
Dolphin clears RAM at boot.

Usage
-----
    python tools/build_caves.py          print the [OnFrame] lines and the listing
"""

from __future__ import annotations

import re
import struct

import capstone
import keystone

DATA = 0x80002F00
CAVE_PARTICLES = 0x80002F10

SITE_PARTICLES = 0x802887B0     # lwz r23, 0x94(r1)   -> bl CAVE_PARTICLES
CAVE_PORTFLAGS = 0x80002F40
SITE_PORTFLAGS = 0x8030D344     # setSeqPortargsU32 : stw r6, 4(r3) -> b CAVE_PORTFLAGS
NOP = 0x60000000
SITES_REQUEUE = (               # clear of the "queued" marker -> nop
    0x80307CF0,                 # JAIBasic::checkPlayingSeq      stwx r0, r4, r3
    0x8030669C,                 # JAIBasic::sendSeAllParameter   stw  r5, 0x2c(r3)
)

# In: f1 = SMSGetAnmFrameRate() (still intact after fctiwz/stfd).
# Out: r23 = number of JPAEmitterManager::calc() calls for this frame.
# Clobbers r12, f0, f2, cr0 (all volatile) and r23, which perform() saved
# (stmw r23) and uses as its loop counter.
ASM_PARTICLES = """
    lis    r12, 0x8000
    lfs    f0, 0x2F00(r12)
    lfs    f2, 0x2F04(r12)
    fadds  f0, f0, f1
    li     r23, 0
loop:
    fcmpu  cr0, f0, f2
    blt    done
    fsubs  f0, f0, f2
    addi   r23, r23, 1
    b      loop
done:
    stfs   f0, 0x2F00(r12)
    blr
"""
# In (setSeqPortargsU32, index 1): r3 = track entry + 4, r6 = flags.
# Flags at r3+4, TPortCmd "queued" marker at r3+0x28.
# Clobbers r0, r6, r7, r8, cr0 (all volatile).
ASM_PORTFLAGS = """
    mfmsr  r7
    rlwinm r8, r7, 0, 17, 15
    mtmsr  r8
    lwz    r0, 0x28(r3)
    cmpwi  cr0, r0, 0
    beq    store
    lwz    r0, 4(r3)
    or     r6, r6, r0
store:
    stw    r6, 4(r3)
    mtmsr  r7
    blr
"""


def assemble(source: str, address: int) -> bytes:
    # Keystone uses LLVM syntax: registers without prefix ("12", not "r12").
    source = re.sub(r"\b(?:r|f|cr)(\d+)\b", r"\1", source)
    ks = keystone.Ks(keystone.KS_ARCH_PPC, keystone.KS_MODE_PPC32 + keystone.KS_MODE_BIG_ENDIAN)
    encoding, _ = ks.asm(source, address)
    return bytes(encoding)


def words(address: int, code: bytes) -> list[tuple[int, int]]:
    return [(address + i, struct.unpack(">I", code[i:i + 4])[0]) for i in range(0, len(code), 4)]


def listing(address: int, code: bytes) -> str:
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    return "\n".join(
        f"  {i.address:08X}  {int.from_bytes(i.bytes, 'big'):08X}  {i.mnemonic:<8}{i.op_str}"
        for i in cs.disasm(code, address)
    )


def build() -> tuple[list[tuple[int, int]], dict[int, bytes]]:
    particles = assemble(ASM_PARTICLES, CAVE_PARTICLES)
    portflags = assemble(ASM_PORTFLAGS, CAVE_PORTFLAGS)
    assert CAVE_PARTICLES + len(particles) <= CAVE_PORTFLAGS, "routine particules trop longue"
    assert CAVE_PORTFLAGS + len(portflags) <= 0x80003000, "routine drapeaux déborde de la zone"

    patches: list[tuple[int, int]] = [(DATA + 4, struct.unpack(">I", struct.pack(">f", 1.0))[0])]
    patches += words(CAVE_PARTICLES, particles)
    patches += words(CAVE_PORTFLAGS, portflags)
    # Call sites last: the PatchEngine applies lines in order, so the routines
    # are in place before they become reachable.
    patches += words(SITE_PARTICLES, assemble(f"bl {CAVE_PARTICLES:#x}", SITE_PARTICLES))
    patches += words(SITE_PORTFLAGS, assemble(f"b {CAVE_PORTFLAGS:#x}", SITE_PORTFLAGS))
    patches += [(a, NOP) for a in SITES_REQUEUE]
    return patches, {CAVE_PARTICLES: particles, CAVE_PORTFLAGS: portflags}


def main() -> int:
    patches, caves = build()
    for address, code in caves.items():
        print(f"; {address:08X}")
        print(listing(address, code))
    print()
    for address, value in patches:
        print(f"0x{address:08X}:dword:0x{value:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
