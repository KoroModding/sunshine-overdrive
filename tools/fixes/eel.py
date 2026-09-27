"""Boss anguille (TBossEel, Eely-Mouth) : débit d'animation constant 0,5 par sous-pas.

Extrait seul de tools/fixes/actors.py (groupe 3), mêmes sites, même routine
CONST2 que tools/fixes/birds.py (constante 2,0 en 0x80002400, code en
0x80002410 — mots identiques, le contrôle de conflit de build_profile les
accepte).

Défaut (DOL US, audit 2026-09-27, trois sites relus à la main)
=============================================================
19 sites, tous dans des TNerveBossEel*::execute ou ExecBackNerve_Sub, de forme
    bl SMSGetAnmFrameRate ; lfs f0, 0.25 (0x80410D5C) ; li r4, 0 ;
    lwz r3, 0x74(r31) ; fmuls f31, f0, f1 ; bl MActor::getFrameCtrl ;
    stfs f31, 0xC(r3)
L'animation principale (+0x74) avance PAR SOUS-PAS : seul calcAnm du boss en
0x800D37C0, sous `clrlwi. r0, r30, 31` (flag 0x1, 0x800D3710). Débit 0,25 ×
anmRate = 0,5 par sous-pas à 30 FPS (60 trames/s), 0,125 à 120 FPS (15
trames/s) : toutes les phases réglées sur la fin d'une animation (apparition,
bouche ouverte, aspiration, mort…) 4× trop longues.

Correctif : les 19 `bl SMSGetAnmFrameRate` → `bl CONST2` (2,0) : débit 0,5 par
sous-pas à toute cadence, bit à bit celui du jeu d'origine. Même choix que BSE
(getBossEelAnmFrameRate).

Sans défaut (même audit) : TBossEelTooth, TBEelTears, TBEelTearsDrop, vortex,
pièce-cœur. Non corrigé, cosmétique : fondu des yeux (0x800D641C, −0,01 par
image) 4× trop rapide.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import birds  # noqa: E402
from birds import ANM_RATE, CONST2, K_2, _bl  # noqa: E402

SITES = [
    0x800D059C, 0x800D07A0, 0x800D0898, 0x800D0B60, 0x800D0E0C, 0x800D1128, 0x800D12F0,
    0x800D147C, 0x800D15C0, 0x800D1C98, 0x800D1D68, 0x800D207C, 0x800D2364, 0x800D2438,
    0x800D24F8, 0x800D2710, 0x800D2AD8, 0x800D2F8C, 0x800D3350,
]


def build() -> list[tuple[int, int]]:
    shared = [(a, v) for a, v in birds.build() if a == K_2 or CONST2 <= a < CONST2 + 0x10]
    return shared + [(s, _bl(s, CONST2)) for s in SITES]


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for s in SITES:
        assert dol.u32(s) == _bl(s, ANM_RATE), f"{s:08X} : pas un bl SMSGetAnmFrameRate"
        assert dol.u32(s + 4) == 0xC002A1BC, f"{s:08X} : lfs 0.25 absent"
    import actors
    ref = dict(actors.build())
    for a, v in build():
        assert ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    print(len(build()), "mots — 19 sites vérifiés, identiques à actors.py")
