"""Sons d'animation rejoués au rebouclage juste avant un changement d'animation.

Défaut (mesuré le 2026-09-28, Gatekeeper de Bianco, tools/watch_gatekeeper.py
et une trace échantillonnée plusieurs fois par image)
=========================================================================
Signalement communauté : « le Gatekeeper crie deux fois à chaque coup ». Le
cri 0x2891 est l'événement 0 (trame 0, sans restriction de boucle) de la
table de sons de son animation de dégât (animation 3, 120 trames, en boucle).

    image 72048  trame 119,5 -> 0,0, drapeau « rebouclée » (02)
    image 72049  le nerf de dégât voit la fin et passe la main au nerf
                 suivant ; le système de sons voit le rebouclage (boucles
                 0 -> 1) et rejoue l'événement de la trame 0 : 2e cri
    image 72050  le nouveau nerf lance l'animation 17 (reset des sons)

Deux sous-pas séparent la fin d'une animation du changement (détecter, puis
changer). À 30 FPS, le son n'est évalué qu'une fois tous les 4 sous-pas
(passe d'animation, drapeau 0x2) : le changement arrive toujours avant, le
rebouclage n'est jamais vu. À 120 FPS, le son est évalué à chaque sous-pas et
le voit. Motif générique : tout acteur qui quitte une animation en boucle à
sa fin peut rejouer ses sons de début de boucle.
Écarté par mesure : modules sound et soundsets (double cri présent sans eux),
son de fonte des blobs 0x2802 (coupé : double cri présent).

Correctif
=========
JAIAnimeSound::setAnimSoundActor (0x8030019C), mode « avant » : à 0x8030038C
(`b 0x803003A8`, entrée de la boucle de lecture des événements), détour. Si
l'on vient de reboucler — trame préc. (+0x88) == trame courante (f30),
compteur de boucles (+0x84) ≠ 0, index (+0x80) == départ (+0x7C), état que
seul le chemin de rebouclage produit — la lecture est sautée pour cette
évaluation (saut à 0x803005CC, fin normale). L'état reste prêt : à
l'évaluation suivante, la boucle rejoue les événements de début avec une
image de retard (8 ms), sauf si l'animation a changé entre-temps
(initActorAnimSound remet tout à zéro) — comme à 30 FPS.
Actif seulement au-dessus de 30 FPS (littéral 0x804167B8 > 0,5, constante
0x80415A94) : boot, logos et jeu d'origine inchangés. Registres touchés :
r0, r3, r12, f0, f1, cr0 — volatils, non vivants à cet endroit.

Validé en jeu par l'auteur (2026-09-28, profil 1502 mots) : un seul cri par
coup, autres sons d'animation normaux. Validation à l'oreille, pas de relevé
après correctif.

Faux positif possible : animation figée (débit 0) exactement au départ d'une
boucle déjà rebouclée — ses sons de début attendent qu'elle reparte.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE = 0x80001DA4              # 0x80001DA4–0x80001DFF vérifié nul en MEM1
CAVE_END = 0x80001E00          # widescreen commence en 0x80001E00
SITE = 0x8030038C
ORIGINAL = {SITE: 0x4800001C}  # b 0x803003A8
PLAY_LOOP = 0x803003A8
FUNC_END = 0x803005CC
TARGETS = (PLAY_LOOP, FUNC_END)  # internes à setAnimSoundActor, relues au listing

SRC = f"""
    lis    r12, 0x8041
    lfs    f0, 0x67B8(r12)
    lfs    f1, 0x5A94(r12)
    fcmpu  cr0, f0, f1
    ble    {CAVE + 0x40:#x}
    lfs    f0, 0x88(r24)
    fcmpu  cr0, f0, f30
    bne    {CAVE + 0x40:#x}
    lwz    r0, 0x84(r24)
    cmpwi  r0, 0
    beq    {CAVE + 0x40:#x}
    lwz    r0, 0x80(r24)
    lwz    r3, 0x7c(r24)
    cmpw   r0, r3
    bne    {CAVE + 0x40:#x}
    b      {FUNC_END:#x}
    b      {PLAY_LOOP:#x}
"""


def build() -> list[tuple[int, int]]:
    code = assemble(SRC, CAVE)
    assert CAVE + len(code) <= CAVE_END
    return words(CAVE, code) + words(SITE, assemble(f"b {CAVE:#x}", SITE))


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X}"
    print(listing(CAVE, assemble(SRC, CAVE)))
    print(listing(SITE, assemble(f"b {CAVE:#x}", SITE)))
    print(len(build()), "mots")
