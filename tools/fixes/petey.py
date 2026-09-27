"""Petey Piranha (TBossPakkun) : animation de vomissement 0x15 à la bonne vitesse.

Extrait seul de tools/fixes/actors.py (groupe 5), mêmes adresses et même code,
pour être installé indépendamment (session 7, un correctif à la fois).

Défaut (lu dans le DOL)
=======================
TBossPakkun::changeBck (0x8009548C) règle le débit de la nouvelle animation à
SMSGetAnmFrameRate() (0x80095594/98 : 2,0 à 30 FPS, 0,5 à 120 — correct, le
contrôleur avançant une fois par image rendue), PUIS, pour l'animation 0x15
seulement (0x8009559C cmpwi r31, 0x15), l'écrase par un paramètre brut :
    0x800955C0 lfs f31, 0x16C(param) ; 0x800955C8 bl getFrameCtrl ;
    0x800955CC stfs f31, 0xC(r3)
calibré pour 30 FPS et jamais remis à l'échelle : à 120 FPS l'animation 0x15
défile 4× trop vite. Or TNerveBPVomit::execute (0x8009327C) règle toute la
phase de vomissement sur cette animation : changeBck(0x15), fenêtre de trames
25–165 (0x800932E4 / 0x800932F0), enchaînement à curAnmEndsNext. Symptôme
rapporté par l'auteur (2026-09-26) : « il vomit direct, pas le temps de
remplir son estomac ».

Correctif
=========
0x800955CC stfs f31, 0xC(r3) -> bl PETEY, qui stocke f31 / M (M = 2 × littéral
0x804167B8, lu à l'exécution) : identique au jeu d'origine à 30 FPS, quel que
soit le paramètre. changeBck est non feuille (LR sauvé au prologue) ; r12 et f0
sont volatils et le site suit immédiatement un bl (getFrameCtrl) : aucune
valeur vivante n'y est détruite.

Écart avec BSE : BSE force 0,8 × SMSGetAnmFrameRate(), ce qui suppose le
paramètre égal à 1,6 (NON VÉRIFIÉ) et modifie sinon le jeu à 30 FPS.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

PETEY = 0x80002480             # même adresse que actors.py
SITE = 0x800955CC
ORIGINAL = {SITE: 0xD3E3000C}  # stfs f31, 0xC(r3)

SRC = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fdivs f0, f31, f0
    stfs  f0, 0xc(r3)
    blr
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, PETEY)
    assert PETEY + len(code) <= 0x800024A0
    return words(PETEY, code) + words(SITE, assemble(f"bl {PETEY:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(PETEY, assemble(SRC, PETEY)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    import actors
    same = [(a, v) for a, v in actors.build() if PETEY <= a < 0x800024A0 or a == SITE]
    assert sorted(same) == sorted(build()), "divergence avec actors.py"
    print(len(build()), "mots — identiques à actors.py")
