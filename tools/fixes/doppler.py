"""Effet Doppler des sons 3D : intensité et durée de transition.

Défaut
======
JAISound::setPositionDopplarCommon (0x8030AB68) calcule le facteur de hauteur
à partir du rapprochement caméra–source ENTRE DEUX PASSAGES JAI :
    len  = |caméra − source| maintenant
    len2 = |(caméra − source) + (Δcaméra − Δsource)|     Δ = depuis le passage précédent
    hauteur = 1 / (1 − (len − len2) / (dopplarParameter / k²))   bornée [0,1 ; 2]
(Graffito-Decomp JAISound.cpp.) À 120 passages/s le déplacement par passage
est 4× plus petit : le décalage de hauteur est 4× trop faible.
Diviseur : JAIGlobalParameter::dopplarParameter, 0x8040CD8C = 3200.0, lu en
un seul point (0x8030ACE4, lfs f3, -0x7434(r13)), aucun setter dans la carte.
Il sert aux effets (setSePositionDopplar) comme aux séquences
(checkPlayingSeqTrack) : les deux chemins passent par cette fonction.

La transition vers la nouvelle hauteur dure JAIGlobalParameter::dopplarMoveTime
= 15 passages (0x8040CD64), lu à deux endroits :
  - checkPlayingSeqTrack 0x8030707C -> setSeqInterPitch -> initMoveParameter :
    déjà multiplié par M par fades.py ;
  - setSePositionDopplar 0x8030C6B0, transition INLINÉE (r31 = 15, ou 1 au
    premier passage), non couverte par fades.py.
D'où : ne pas multiplier la donnée dopplarMoveTime (double effet sur les
séquences) ; multiplier r31 dans setSePositionDopplar seulement.

Correctifs
==========
1. 0x8040CD8C : 3200.0 -> 800.0 (= 3200 / M, M = 4). DONNÉE fixe : suppose le
   littéral 0x804167B8 à 2.0 (profil 120, posé par la base). build() vérifie
   la présence de cette écriture dans la base.
2. 0x8030C730 (cmplwi r31, 0 — début de la transition inlinée) -> b routine :
   r31 <<= log2(M) (lu à l'exécution) ; cmplwi r31, 0 ; b 0x8030C734.
   Fonction non feuille ; r12 n'est plus lu après 0x8030C6F0 (appel virtuel)
   jusqu'à l'épilogue — vérifié sur le listing.

Zone : 0x80002EC0 – 0x80002EDF (reste libre de la zone de fades.py).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE = 0x80002EC0
CAVE_END = 0x80002EE0
DOPPLAR_PARAMETER = 0x8040CD8C
SITE_MOVE = 0x8030C730
M = 4
ORIGINAL = {DOPPLAR_PARAMETER: 0x45480000, SITE_MOVE: 0x281F0000}

ASM_MOVE = f"""
    lis    r12, 0x8041
    lwz    r12, 0x67B8(r12)
    rlwinm r12, r12, 9, 24, 31
    addi   r12, r12, -126
    slw    r31, r31, r12
    cmplwi r31, 0
    b      {SITE_MOVE + 4:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(ASM_MOVE, CAVE)
    assert CAVE + len(code) <= CAVE_END
    param = struct.unpack(">I", struct.pack(">f", 3200.0 / M))[0]
    return (words(CAVE, code) + [(DOPPLAR_PARAMETER, param)]
            + words(SITE_MOVE, assemble(f"b {CAVE:#x}", SITE_MOVE)))


if __name__ == "__main__":
    from dol import Dol
    from build_profile import BASE  # noqa: F401  (le littéral est posé dans collect())
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(CAVE, assemble(ASM_MOVE, CAVE)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
