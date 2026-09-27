"""Poinks (TPopo, « Popo ») : ne plus exploser sur leur propre boîte de collision.

Défaut (lu dans le DOL, puis mesuré le 2026-09-27 à Bianco, épisode de Petey,
tools/watch_popo.py, profil 1324 mots, 120 images/s)
=========================================================================
Le Poink possède une seconde boîte de collision, TPopoCollision (+0x23C, son
propriétaire en +0x68). TPopo::calcRootMatrix (0x800E7604) la place sur un
joint du modèle, depuis les matrices de l'image PRÉCÉDENTE ; il n'est appelé
que dans la passe d'animation de TLiveActor::perform (drapeau 0x2, avec
MActor::frameUpdate et MActor::calc), donc une fois par image rendue.

Au lancement (TNervePopoFly 0x800E6078), la collision du Poink et celle de la
boîte sont coupées, puis rétablies au pas 6. Pendant le vol, dès que les deux
se touchent, TPopo::isCollidMove (0x800E6C94) envoie le message 0 à la boîte,
qui le relaie au Poink : réponse vraie -> nerf Explosion.

    mesuré à 120 FPS : boîte 150–210 u derrière le Poink (≈ 2 pas de vitesse,
                       45–100 u/pas) ; 20 lancers : 19 explosés 7 à 10 pas
                       (< 0,1 s) après le lancement, à 380–880 u, 1 au pas 2 ;
                       les 8 lancers suivis par la sonde de collision : contact
                       avec SA boîte au premier checkActorsHit après le pas 5
    calculé à 30 FPS : même retard d'une image = 4 sous-pas de plus, soit
                       500 u et plus : pas de contact, le Poink part au loin

Correctif
=========
Le contact se traite dans les deux sens, et les deux mènent à isCollidMove :
- le Poink touche sa boîte : isCollidMove(Poink, boîte) ;
- la boîte touche le Poink : TPopo::bind (0x800E6FC0) appelle
  TSmallEnemy::behaveToHitOthers(Poink, Poink), qui appelle par la vtable
  (+0x17C) isCollidMove(Poink, Poink).
Première version (autre == boîte seulement) installée puis mesurée le
2026-09-27 : aucun effet, 9 lancers sur 9 explosés au pas 7–10 par le second
chemin.

0x800E6C94 mflr r0 -> b POINK : si l'acteur touché est le Poink lui-même ou sa
boîte (autre == this ou autre == this+0x23C), renvoyer 0 (pas de collision),
sinon reprendre la fonction. isCollidMove renvoie toujours 0 et n'agit qu'en vol : le correctif
ne retire que l'auto-collision en vol, qui n'existe pas dans le jeu d'origine.
r12 est volatil à l'entrée d'une fonction. Renvoyer 0 supprime aussi la
poussée de behaveToHitOthers (+0x94), appliquée seulement sur réponse vraie.
Les touches du Poink et de sa boîte sur les autres acteurs (Petey, Mario,
ennemis) sont inchangées.

Mesuré après (profil 1334 mots) : vol de 54 pas (0,45 s), 4630 u, explosion
sur TBPNavel (nombril de Petey), qui se réveille. Validé par l'auteur. Un
seul lancer mesuré.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

POINK = 0x80001D80             # zone de soundsets, qui s'arrête à 0x80001CF8 ;
POINK_END = 0x80001DC0         # 0x80001CFC–0x80001DFF vérifié nul en MEM1
SITE = 0x800E6C94              # TPopo::isCollidMove, prologue
ORIGINAL = {SITE: 0x7C0802A6}  # mflr r0

SRC = f"""
    cmplw r3, r4
    beq   {POINK + 0x14:#x}
    lwz   r12, 0x23c(r3)
    cmplw r12, r4
    bne   {POINK + 0x1C:#x}
    li    r3, 0
    blr
    mflr  r0
    b     {SITE + 4:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, POINK)
    assert POINK + len(code) <= POINK_END
    return words(POINK, code) + words(SITE, assemble(f"b {POINK:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} au lieu de {v:08X}"
    print(listing(POINK, assemble(SRC, POINK)))
    print(listing(SITE, assemble(f"b {POINK:#x}", SITE)))
    print(len(build()), "mots")
