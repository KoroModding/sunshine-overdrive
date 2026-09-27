"""Oiseaux (TAnimalBird) : vitesse de vol, d'atterrissage et de marche au sol.

Extrait seul de tools/fixes/actors.py (groupe 2), mêmes adresses et même code,
pour être installé indépendamment (un correctif à la fois).

Défaut (lu dans le DOL, symptôme confirmé par l'auteur le 2026-09-27 :
« les oiseaux sont très lents, leur animation est normale mais ils ne volent
pas vite »)
==========================================================================
Cinq sites multiplient un paramètre de vitesse par SMSGetAnmFrameRate() :

    8000CD50  doLanding+0x48            (0x174 × 0xB8) × anmRate   vitesse initiale d'atterrissage
    8000CEB0  doLanding+0x1A8           param 0x194 × anmRate
    8000D1D8  doFlyToCurPathNode+0x10C  (0x174 × 0xB8) × anmRate   vitesse de vol
    8000D1F8  doFlyToCurPathNode+0x12C  param 0xCC × anmRate
    8000BEB0  TNerveAnimalBirdWalkOnGround::execute+0x168  param 0x1A8 × anmRate

Ces fonctions ne sont appelées que par des nerfs (vt+0xD0 moveObject → vt+0xC8
control), donc **par sous-pas** : le facteur anmRate (2,0 à 30 FPS) y est une
constante de réglage, pas une compensation de cadence. À 120 FPS il vaut 0,5 :
déplacement 4× trop lent, animation (avancée par image) inchangée — exactement
le symptôme.

Correctif
=========
Les 5 `bl SMSGetAnmFrameRate` → `bl CONST2`, qui renvoie 2,0 (valeur d'origine
à 30 FPS) quel que soit M. Même choix que BSE (getAnimalBirdSpeed), étendu à
8000CD50 et 8000BEB0, oubliés par BSE. CONST2 ne touche que r12 et f1, volatils
au retour d'un appel.

NON VÉRIFIÉ au moment de l'écriture : l'exécution par sous-pas est établie par
lecture statique (chaîne d'appel) ; la mesure attendue après installation est
une vitesse de vol multipliée par 4 exactement.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

ANM_RATE = 0x802A7BD8            # SMSGetAnmFrameRate__Fv
K_2 = 0x80002400                 # f32 2.0 — même adresse que actors.py
CONST2 = 0x80002410              # même adresse que actors.py
SITES = [0x8000CEB0, 0x8000D1D8, 0x8000D1F8, 0x8000CD50, 0x8000BEB0]

SRC = """
    lis   r12, 0x8000
    lfs   f1, 0x2400(r12)
    blr
"""


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    k2 = struct.unpack(">I", struct.pack(">f", 2.0))[0]
    return ([(K_2, k2)] + words(CONST2, assemble(SRC, CONST2))
            + [(s, _bl(s, CONST2)) for s in SITES])


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
    print(listing(CONST2, assemble(SRC, CONST2)))
    import actors
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
