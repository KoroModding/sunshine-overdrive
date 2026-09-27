"""Durées des fondus JAI : musique, tempo, flux, effets sonores.

Défaut
======
La couche JAI (MSound::mainLoop -> JAIBasic::startFrameInterfaceWork) passe une
fois par image rendue : 30 fois par seconde dans le jeu d'origine, 120 à 120 FPS
(relevé session 6 : compteur JAISound+0x14 à ~120/s). Toute transition de
paramètre y est comptée en passages : JAIMoveParaSet {cible +0, courant +4,
pas +8, compteur +0xC}, décrémenté d'une unité par passage par
JAIData::moveParameter / JAIData::setSeMovePara. Une durée écrite pour 30 Hz
s'écoule donc 4× trop vite à 120 FPS : fondus de musique aux changements de
zone et à la sortie de niveau, accélération du tempo (MSModBgm::changeTempo,
5 et 20 passages), atténuation de la musique pendant certains sons
(seqMuteMoveSpeedSePlay = 3), fondus croisés MSBgmXFade (2), fondus de sortie
des effets sonores (stop avec durée), fondu d'entrée des sons (JAISound+0x10).

Tous ces chemins aboutissent à deux points (Graffito-Decomp, JAISound.cpp,
relu dans le DOL) :
  - JAISound::initMoveParameter(set, cible, durée)   0x8030A3B0 — séquences
    (setSeqInterVolume/Pan/Pitch/Fxmix/Dolby, setSeqTempoProportion, données
    de port) et flux (setStreamInterVolume/Pitch/Pan) ;
  - setSeInterMovePara(set, durée), INLINÉ dans les cinq setters d'effets :
    setSeInterVolume 0x8030B700, Pan 0x8030B8C8, Fxmix 0x8030BA90,
    Dolby 0x8030BC58, Pitch 0x8030BE20. Durée en r5 à l'entrée des six.

Seule exception connue, NON traitée ici : JAISound::setSePositionDopplar
(0x8030C690) inline sa propre transition de hauteur Doppler avec
JAIGlobalParameter::dopplarMoveTime (15). Voir docs/00-journal.md, session 7.

Correctif
=========
Durée multipliée par M à l'entrée des six fonctions, M = 2 × littéral
0x804167B8 (1 à 30 FPS, 2 à 60, 4 à 120), lu à l'exécution. M est une
puissance de deux : on l'obtient par l'exposant du littéral, sans flottant,
    décalage = exposant(littéral) − 126       0.5f -> 0, 1.0f -> 1, 2.0f -> 2
    durée <<= décalage
Durée 0 (immédiat) inchangée. Durée 1 : chez initMoveParameter, cas spécial
« pas = écart total » ; ×4 la fait passer par la division, même durée réelle.

Routines (zone 0x80002E40 – 0x80002EA7) :
    SCALE   r5 <<= décalage ; touche r12. Appelée par bl.
    stub SE (×5) : mflr r0 (instruction d'origine) ; bl SCALE ; b site+4.
        LR d'origine déjà dans r0, que le setter sauve juste après.
    stub initMoveParameter : fonction feuille, LR à préserver — r11 (volatil,
        pas un argument) garde LR autour du bl.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_START = 0x80002E40
CAVE_END = 0x80002EA8          # exclusif ; 0x80002EA8–0x80002EFF libres
SCALE = 0x80002E40

SITE_INIT = 0x8030A3B0         # initMoveParameter : stwu r1, -0x20(r1)
SITES_SE = (
    0x8030B700,                # setSeInterVolume  : mflr r0
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
    """(adresse de la routine, code, site détourné ou 0)."""
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
    # Sites en dernier : les routines sont en place avant d'être atteignables.
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
