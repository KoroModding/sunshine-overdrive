"""Jeux de sons MSSetSound (FLUDD, graffiti, goop, colonnes) : horloge à 30 Hz.

Défaut
======
MSound::mainLoop appelle, une fois par passage JAI (= par image rendue, 120/s à
120 FPS), la méthode virtuelle frameLoopDyna de chaque MSSetSound et
MSSetSoundGrp (0x80014E00 / 0x80014E28, entrée +0x14 de la vtable secondaire).
Elle fait :
    if (+0x58) +0x54 += 1        horloge du jeu de sons
    +0xB8 = 0                    verrou « un départ par passage »
Les paramètres des 9 jeux (MSSetSound::init : impact du jet de FLUDD 0x6800 /
0x6801, nettoyage de graffiti 0x6809, goop, colonnes de feu et électriques,
séchage 0x804, impact 0x6802, cri de la raie 0x899B) sont en passages à 30 Hz :
intervalle minimal, durée d'un son unitaire, durée de modulation, écart de
continuité, durée maximale de continuité. À 120 FPS l'horloge avance 4× trop
vite et le verrou se rouvre 4× plus souvent : ces sons repartent jusqu'à 4×
plus souvent, et leurs modulations s'écoulent 4× trop vite.

Second chronomètre, le principal : l'ÂGE du son précédent, JAISound+0x14,
incrémenté lui aussi à chaque passage JAI (~120/s). startSoundSetDyna le
compare à l'intervalle minimal (+0x1D, + aléa +0x1E), à la durée unitaire
(+0x1F), aux seuils des membres de groupe (+0x18 f32), à la durée de
modulation (+0x28) et à l'écart de continuité (+0x3C). C'est lui qui fixe la
cadence de répétition du son d'impact du jet (0x6800 : écart de continuité
0, donc l'horloge +0x54 n'y est jamais active).

Correctifs
==========
1. Âge ramené en passages à 30 Hz : les 4 lectures `lwz rD, 0x14(rA)` de
   chaque instance de startSoundSetDyna (MSSetSound 0x8001B454, MSSetSoundGrp
   0x8001BE24, même code décalé de 0x9D0) sont détournées vers
   `bl SHIFT ; lwz rD, 0x14(rA) ; srw rD, rD, r12 ; b site+4`.
   Fonctions non feuilles (LR sauvé au prologue, restauré depuis la pile) :
   le bl en milieu de fonction est sans conséquence. r11/r12 n'y sont jamais
   utilisés (vérifié sur tout le listing).

2. frameLoopDyna n'est exécutée qu'un passage sur M (M = 2 × littéral 0x804167B8,
lu à l'exécution) : quand (JAIBasic::basic+0x20) & (M − 1) == 0. Ce compteur
est incrémenté par JAIBasic::processFrameWork (0x80301D84), une fois par
passage — relevé en jeu : 119,99/s. Il est incrémenté APRÈS les frameLoopDyna
du même passage, la phase est donc stable. Si JAIBasic::basic est nul, la
méthode s'exécute normalement.

Routines (zone 0x80001C00 – 0x80001DFF, libre : hx s'arrête vers 0x80001ACC) :
    SHIFT  r12 = log2(M) ; touche r12.
    GATE   cr0.eq = « exécuter ce passage » ; touche r11, r12, cr0.
    stub   (fonction feuille, LR à garder) : mflr r10 ; bl GATE ; mtlr r10 ;
           bnelr ; lbz r0, 0x58(r3) (instruction d'origine) ; b site+4.
           r10 est volatil et n'est pas un argument (seul r3 l'est).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_START = 0x80001C00
CAVE_END = 0x80001E00          # exclusif
GATE = 0x80001C00
JAIBASIC_BASIC = 0x8040E430    # JAIBasic::basic (us.map), lu en jeu : 0x805F39D8

SITES = (
    0x80016014,                # MSSetSoundTL<MSSetSoundGrp>::frameLoopDyna
    0x8001604C,                # MSSetSoundTL<MSSetSound>::frameLoopDyna
)
LBZ_R0_58 = 0x88030058         # lbz r0, 0x58(r3)
DYNA_GRP_DELTA = 0x9D0         # startSoundSetDyna<Grp> - startSoundSetDyna<MSSetSound>
AGE_READS = {                  # site (instance MSSetSound) : lecture de JAISound+0x14
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
