"""TJointCoin / TSandBird : débit des animations posé par TJointCoin::loadAfter.

Extrait seul de tools/fixes/actors.py (groupe 4), mêmes sites, mêmes routines
et mêmes adresses, pour être installé indépendamment (un correctif à la fois).

Défaut (lu dans le DOL, puis mesuré le 2026-09-27 sur l'oiseau de sable de
Gelato, tools/watch_sandbird.py, profil 1309 lignes, 120 images/s)
=========================================================================
TSandBird hérite de TJointCoin (même loadAfter, control appelle celui de
TJointCoin). loadAfter pose le débit du frame ctrl 0 à 0,25 × anmRate :

    801F76A8  bl SMSGetAnmFrameRate ; ×0,25 -> +0x74  « character » (ailes)
    801F76C4  bl SMSGetAnmFrameRate ; ×0,25 -> +0x138 « movement » (trajectoire)

TJointCoin::control (par sous-pas) avance +0x138 puis copie la translation de
son joint racine dans la position : trajectoire à 120 avances/s quel que soit
M. +0x74 avance en plus une fois par image (TLiveActor::perform).

    mesuré à 120 FPS : débit 0,125 ; trajectoire 15,0 trames/s, ailes 30,0,
                       vol 88 u/s, un tour (9000 trames) en ~600 s
    calculé à 30 FPS : trajectoire 60 trames/s, ailes 75 ; tour en 150 s

Correctif
=========
801F76C4 -> bl CONST2 (2,0) : débit 0,5 constant, 60 trames/s à tout M.
801F76A8 -> bl JCCHAR (10 / (4 + M)) : débit 2,5 / (4 + M), 75 trames/s à tout M.
Les deux routines sont celles de birds.py et bosses.py, réécrites ici à
l'identique pour que le module tienne seul.

Réserve : débit figé au chargement avec le M du moment ; ressortir et rentrer
dans le niveau après installation. Les autres TJointCoin du jeu partagent ce
code : NON VÉRIFIÉS.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_caves import assemble, words, listing  # noqa: E402
import actors  # noqa: E402

ANM_RATE = 0x802A7BD8            # SMSGetAnmFrameRate__Fv
K_2, K_5 = actors.K_2, actors.K_5
CONST2, JCCHAR = actors.CONST2, actors.JCCHAR
SITES = [(0x801F76A8, JCCHAR), (0x801F76C4, CONST2)]


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    return ([(K_2, _f32(2.0)), (K_5, _f32(5.0))]
            + words(CONST2, assemble(actors.SRC_CONST2, CONST2))
            + words(JCCHAR, assemble(actors.SRC_JCCHAR, JCCHAR))
            + [(s, _bl(s, t)) for s, t in SITES])


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s, _ in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
    print(listing(JCCHAR, assemble(actors.SRC_JCCHAR, JCCHAR)))
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
