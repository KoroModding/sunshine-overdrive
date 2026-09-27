"""Assemble les routines du profil et émet leurs lignes [OnFrame].

TMarioParticleManager::perform appelle JPAEmitterManager::calc()
(int)SMSGetAnmFrameRate() fois par image : 2, 1, puis 0 au palier 120. On
remplace la troncature par un accumulateur, ce qui demande un état qui survive
d'une image à l'autre, donc quelques instructions hors du code d'origine :
    acc += SMSGetAnmFrameRate();  n = partie entière de acc;  acc -= n
soit 2 / 1 / « 0 et 1 en alternance » — 60 appels par seconde à tous les
paliers, exactement comme le jeu d'origine.

Commandes de port JAI — JAISystemInterface::setSeqPortargsU32 (drapeaux)
   La couche JAI écrit les drapeaux « paramètres à appliquer » d'une commande
   de port par écrasement (stw), puis force sa remise en file (marqueur +0x2C
   remis à zéro avant addPortCmdOnce). Si la commande est encore en file —
   fenêtre bien plus fréquente à 120 Hz — ses drapeaux en attente sont perdus.
   Cas relevé : la commande initiale d'outerInit (0xff, tempo compris) écrasée
   par 0x01 ; tempo jamais appliqué, multiplicateur resté à 0, musique figée.
   Correctif : fusion (or) des drapeaux si la commande est encore en file,
   écrasement sinon (sémantique d'origine), interruptions masquées pendant la
   lecture-écriture ; et suppression de la remise à zéro du marqueur aux deux
   sites, pour qu'une commande en file ne soit pas chaînée deux fois.

Routine audio retirée (2026-09-22, session 6) : elle limitait MSound::mainLoop
à 30 Hz pour corriger une musique figée. Test A/B à l'oreille : elle faisait
perdre des sons d'animation de Mario (0x1969, glissade sur l'eau), et la
musique boucle normalement sans elle. Voir docs/00-journal.md, session 6.

Emplacement : 0x80002F00, fin de la zone 0x80001800–0x80003000 que le jeu
n'utilise pas et que Dolphin réserve au codehandler Gecko. Aucun code Gecko
n'est actif avec ce profil ; la zone est relevée entièrement nulle en jeu.

    0x80002F00  f32  accumulateur particules   (état, jamais écrit par le profil)
    0x80002F04  f32  1.0f                       (constante, écrite par le profil)
    0x80002F10  code routine particules
    0x80002F40  code fusion des drapeaux de port JAI

L'accumulateur ne doit **pas** figurer dans [OnFrame] : le PatchEngine
réécrit ses valeurs à chaque champ VI, ce qui le remettrait à zéro en continu.
Il part de zéro parce que Dolphin efface la RAM à l'amorçage.

Usage
-----
    python tools/build_caves.py          affiche les lignes [OnFrame] et le listing
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
SITES_REQUEUE = (               # remise à zéro du marqueur « en file » -> nop
    0x80307CF0,                 # JAIBasic::checkPlayingSeq      stwx r0, r4, r3
    0x8030669C,                 # JAIBasic::sendSeAllParameter   stw  r5, 0x2c(r3)
)

# Entrée : f1 = SMSGetAnmFrameRate() (encore intact après fctiwz/stfd).
# Sortie : r23 = nombre d'appels à JPAEmitterManager::calc() pour cette image.
# Registres touchés : r12, f0, f2, cr0 — tous volatils, et r23 que perform()
# a sauvegardé (stmw r23) et utilise précisément comme compteur de boucle.
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
# Entrée (setSeqPortargsU32, indice 1) : r3 = entrée de piste + 4, r6 = drapeaux.
# Drapeaux en r3+4, marqueur « en file » de la TPortCmd en r3+0x28.
# Registres touchés : r0, r6, r7, r8, cr0 — tous volatils.
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
    # Keystone suit la syntaxe LLVM : registres sans préfixe (« 12 », pas « r12 »).
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
    # Les sites d'appel en dernier : le PatchEngine applique les lignes dans
    # l'ordre, les routines sont donc en place avant d'être atteignables.
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
