"""Correctifs 120 FPS : écran de sélection des Shines et minuterie des boîtes de dialogue.

Port des sections de BetterSunshineEngine ``src/patches/fps.cpp`` lignes 149-166 (boîte de
dialogue) et 444-507 (sélection des Shines, crédits theAzack9). Zone de code réservée :
0x80002200-0x800023FF.

Convention : M = 2 x f32@0x804167B8 (1 à 30 FPS, 2 à 60, 4 à 120), relu à CHAQUE appel.
Un nombre d'images est multiplié par M, une vitesse par image est divisée par M.

Cadence (preuve) : ``TSelectDir::direct`` (0x80175EC4) appelle une seule fois
``JDrama::TDirector::direct`` (bl 0x802f7d28 @ 0x80175FE8) par image, sans accumulateur de
sous-pas ; tout ce qui suit tourne donc une fois par image rendue, soit 4x trop vite à 120 FPS.

----------------------------------------------------------------------------------------------
1. Rotation du carrousel de Shines — TSelectShineManager::startDecrease / startIncrease
----------------------------------------------------------------------------------------------
Désassemblage (startDecrease, startIncrease identique avec -0x28 et +0xA4) ::

    80178680  1C040028  mulli  r0, r4, 0x28        ; 40 * n   (n = décalage d'index)
    80178684..80178698  mulhw 0x66666667 / srawi 2 ; / 10  -> 4n
    801786AC  98A300A5  stb    r5, 0xa5(r3)        ; drapeau "rotation en cours"
    801786C0  D00300A0  stfs   f0, 0xa0(r3)        ; pas = (float)(40n/10)
    801787C4  D00300A0  stfs   f0, 0xa0(r3)        ; (startIncrease, pas = -4n)

``perform`` (0x80178158) l'ajoute à l'angle entier une fois par image, puis borne à la cible ::

    80178210  lfs  f0, 0xa0(r25) / 80178224 fadds f0,f1,f0 / fctiwz / 80178234 stw r0,0x9c(r25)
    8017824C  mulli r0, r0, -0x28 ; cible = -40 * index ; bge/ble -> stw cible, stb 0 -> fin

0xA0 est donc une VITESSE (degrés-ish par image, 10 images pour 40 unités) -> divisée par M.
Le « 40 » du mulli n'est PAS un nombre d'images mais l'écart angulaire entre deux Shines ; la
cible (8017824C, 80178278) n'est pas touchée.

Correctif : ``stfs f0,0xa0(r3)`` -> ``b cave`` ; la cave fait f0 /= M, ``stfs``, puis ``b``
retour. ``b`` et non ``bl`` : startDecrease/startIncrease sont des fonctions feuilles (pas de
mflr/stw lr, épilogue ``addi r1,r1,0x30 / blr`` @ 80178724), un ``bl`` écraserait LR.
f1 (constante 0x4330.. chargée en 801786B4) est morte après le fsubs : utilisée comme scratch.
Pour n=1 : pas 4/M = 1.0 à 120 FPS -> 40 images au lieu de 10, somme exacte. Pour M=3 le pas
1.333 est tronqué par fctiwz (angle entier) -> 40 images au lieu de 30, fin bornée par le clamp.

Accord avec BSE : BSE fait ``newFrames = 40 / frameScalar`` et réécrit l'immédiat du mulli
(0x1C04FFD8 -> 0x1C04FFF6 pour -10, 0x1C040028 -> 0x1C04000A). Le NOM est trompeur (ce n'est
pas un nombre d'images) mais le SENS est juste : c'est une vitesse et elle est divisée. Notre
version divise le float au lieu de l'immédiat entier (même résultat pour M = 1, 2, 4).
Désaccord mineur : les ``SMS_WRITE_32`` statiques de BSE (0x80178784 = 0x1C04FFEC = -20,
0x80178680 = 0x1C040014 = +20) figent la valeur 60 FPS par défaut ; ils sont écrasés par ses
overrides à chaque appel, donc sans effet réel. Non portés.

----------------------------------------------------------------------------------------------
2. Fondu des panneaux de titre — littéraux ±25.5f (0x80412398 / 0x8041239C)
----------------------------------------------------------------------------------------------
Lus uniquement dans TSelectMenu::perform (xref : 801737EC, 80173B90 pour +25.5 ; 80173888,
80173C10 pour -25.5), chacun immédiatement stocké ::

    801737EC  C002B7F8  lfs   f0, -0x4808(r2)   ; 25.5
    801737F0  D0050048  stfs  f0, 0x48(r5)      ; TExPane : pas d'alpha par image
              (+0x44 alpha courant 0 ou 255, +0x4C cible 0xFF ou 0, +0x50 actif = 1)

TExPane::update (0x8013EAB0.. ; 8013EDC8 lfs f1,0x44 / 8013EDCC lfs f0,0x48 / fadds /
8013EDD4 stfs f0,0x44) ajoute 0x48 à l'alpha une fois par image : 255/25.5 = 10 images.
C'est une VITESSE -> divisée par M. Accord avec BSE (25.5f / frameScalar).

Correctif : on ne réécrit pas les littéraux (le PatchEngine les réimposerait, et ils devraient
suivre M) ; les 4 ``stfs f0,0x48(r5)`` (801737F0, 8017388C, 80173B94, 80173C14) deviennent
``bl cave_alpha`` qui fait f0 /= M puis le stfs. TSelectMenu::perform n'est pas feuille
(prologue 80172C90 ``mflr r0 / stw r0,4(r1)``) : bl sûr. Scratch r12 et f12 : f12/f13 ne
figurent nulle part dans TSelectMenu::perform (grep sur 0x80172C90..+1900 instr.), r12 est
rechargé (``lwz r12,0(r3)``) avant tout usage suivant. 25.5/4 = 6.375 = 51/8, exact en
binaire -> 40 pas atteignent 255 / 0 exactement.

----------------------------------------------------------------------------------------------
3. Glissement des textes — TCoord2D::setValue (4 appels BSE)
----------------------------------------------------------------------------------------------
TCoord2D::setValue(long n, f1..f4) @ 0x8013EB58 ::

    8013EB5C  cmpwi r4, 0          ; n <= 0 -> vitesse 0
    8013EB94  fsubs f3, f1, f3     ; (start - end)
    8013EBB8  fdivs f2, f3, f2     ; / (float)n
    8013EBC0  stfs  f2, 0x10(r3)   ; vitesse par image, consommée par TCoord2D::update
                                   ; (CLBChaseGeneralConstantSpecifySpeed, via TExPane::update)

r4 est un NOMBRE D'IMAGES (``li r4,0xa`` en 801737C8, 80173864, 80173B68, 80173BEC, non
modifié jusqu'aux bl) -> multiplié par M. Accord avec BSE (``speed * frameScalar`` : le
paramètre s'appelle « speed » chez BSE mais c'est bien une durée, multiplier est correct).

Correctif : les 4 ``bl 0x8013EB58`` (8017383C, 801738C8, 80173BC8, 80173C54) -> ``bl
cave_coord`` qui fait r4 *= (int)M (plancher 1) puis ``b 0x8013EB58`` (appel terminal, LR
pointe toujours vers l'appelant). f0 sert de scratch : setValue l'écrase de toute façon.

Remarque (au-delà de BSE, NON corrigé ici, NON VÉRIFIÉ en jeu) : TSelectMenu a 7 autres
appels à setValue (startOpenWindow 80172A80/80172B30/80172B90, perform 80172D88/801733FC/
80173560/801735BC) dont les durées viennent de variables (r24/r25, fctiwz(20*f[0x14C])). Ils
animent l'ouverture de la fenêtre et accélèrent probablement aussi à 120 FPS.

----------------------------------------------------------------------------------------------
4. Minuterie d'entrée des boîtes de dialogue — TTalk2D2 +0x251
----------------------------------------------------------------------------------------------
TTalk2D2::perform @ 0x80151C88 (r28 = this, ``addi r28,r3,0`` en 80151CA0) ::

    80151D30  38000014  li   r0, 0x14
    80151D34  981C0251  stb  r0, 0x251(r28)     ; minuterie = 20
    80151D38  38000003  li   r0, 3              ; état 3
    ...
    80151ED8  887C0251  lbz  r3, 0x251(r28)     ; état 3 : décrément par image
    80151EDC  3803FFFF  addi r0, r3, -1
    80151EE8  7C000775  extsb. r0, r0           ; < 0 -> état 4
    8015489C  991F0251  stb  r8, 0x251(r31)     ; (constructeur)

NOMBRE D'IMAGES -> 20 x M. Borné à 127 car relu en ``extsb`` (signé) : 20 x 4 = 80 tient.
Correctif : ``stb r0,0x251(r28)`` -> ``bl cave_talk`` (r0 *= M, clamp, stb, blr). perform
n'est pas feuille (80151C88 mflr/stw). La cave se crée une frame pour fctiwz et sauvegarde f0.
r0 est réécrit par ``li r0,3`` juste après ; cr0 est recalculé en 80151E94 (``rlwinm.``).
Accord avec BSE (20/40/80). NON VÉRIFIÉ : que TTalk2D2 soit dans une liste perform par image
et non par sous-pas — on s'appuie sur le constat empirique de BSE (entrée 2x trop rapide à 60).

Dépendances : aucune autre que 0x804167B8 (profil de base). Si un autre groupe fait basculer ce
littéral à l'exécution, les caves suivent car elles le relisent à chaque appel.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

RANGE_LO, RANGE_HI = 0x80002200, 0x80002400

LOAD_M = """
    lis   r12, 0x8041
    lfs   {f}, 0x67B8(r12)
    fadds {f}, {f}, {f}
"""

CAVE_SHINE_DEC = 0x80002200
CAVE_SHINE_INC = 0x80002220
CAVE_ALPHA = 0x80002240
CAVE_COORD = 0x80002260
CAVE_TALK = 0x800022A0

SITE_SHINE_DEC = 0x801786C0   # stfs f0, 0xa0(r3)  -> b cave, retour 0x801786C4
SITE_SHINE_INC = 0x801787C4   # stfs f0, 0xa0(r3)  -> b cave, retour 0x801787C8
SITES_ALPHA = (0x801737F0, 0x8017388C, 0x80173B94, 0x80173C14)   # stfs f0, 0x48(r5)
SITES_COORD = (0x8017383C, 0x801738C8, 0x80173BC8, 0x80173C54)   # bl TCoord2D::setValue
SITE_TALK = 0x80151D34        # stb r0, 0x251(r28)
SETVALUE = 0x8013EB58

ORIGINAL = {
    SITE_SHINE_DEC: 0xD00300A0, SITE_SHINE_INC: 0xD00300A0,
    **{a: 0xD0050048 for a in SITES_ALPHA},
    SITE_TALK: 0x981C0251,
}


def _shine(ret: int) -> str:
    return LOAD_M.format(f="f1") + f"""
    fdivs f0, f0, f1
    stfs  f0, 0xa0(r3)
    b     {ret:#x}
"""


ASM_ALPHA = LOAD_M.format(f="f12") + """
    fdivs f0, f0, f12
    stfs  f0, 0x48(r5)
    blr
"""

ASM_COORD = """
    stwu   r1, -0x10(r1)
""" + LOAD_M.format(f="f0") + f"""
    fctiwz f0, f0
    stfd   f0, 8(r1)
    lwz    r12, 12(r1)
    addi   r1, r1, 0x10
    cmpwi  r12, 1
    bge    coord_ok
    li     r12, 1
coord_ok:
    mullw  r4, r4, r12
    b      {SETVALUE:#x}
"""

ASM_TALK = """
    stwu   r1, -0x20(r1)
    stfd   f0, 0x10(r1)
""" + LOAD_M.format(f="f0") + """
    fctiwz f0, f0
    stfd   f0, 8(r1)
    lwz    r12, 12(r1)
    lfd    f0, 0x10(r1)
    addi   r1, r1, 0x20
    cmpwi  r12, 1
    bge    talk_m_ok
    li     r12, 1
talk_m_ok:
    mullw  r0, r0, r12
    cmpwi  r0, 127
    ble    talk_store
    li     r0, 127
talk_store:
    stb    r0, 0x251(r28)
    blr
"""


def caves() -> dict[int, bytes]:
    out = {
        CAVE_SHINE_DEC: assemble(_shine(SITE_SHINE_DEC + 4), CAVE_SHINE_DEC),
        CAVE_SHINE_INC: assemble(_shine(SITE_SHINE_INC + 4), CAVE_SHINE_INC),
        CAVE_ALPHA: assemble(ASM_ALPHA, CAVE_ALPHA),
        CAVE_COORD: assemble(ASM_COORD, CAVE_COORD),
        CAVE_TALK: assemble(ASM_TALK, CAVE_TALK),
    }
    starts = sorted(out)
    for i, a in enumerate(starts):
        end = a + len(out[a])
        limit = starts[i + 1] if i + 1 < len(starts) else RANGE_HI
        assert RANGE_LO <= a and end <= limit, f"cave {a:#x} déborde ({end:#x} > {limit:#x})"
    return out


def sites() -> list[tuple[int, int]]:
    p: list[tuple[int, int]] = []
    p += words(SITE_SHINE_DEC, assemble(f"b {CAVE_SHINE_DEC:#x}", SITE_SHINE_DEC))
    p += words(SITE_SHINE_INC, assemble(f"b {CAVE_SHINE_INC:#x}", SITE_SHINE_INC))
    for a in SITES_ALPHA:
        p += words(a, assemble(f"bl {CAVE_ALPHA:#x}", a))
    for a in SITES_COORD:
        p += words(a, assemble(f"bl {CAVE_COORD:#x}", a))
    p += words(SITE_TALK, assemble(f"bl {CAVE_TALK:#x}", SITE_TALK))
    return p


def build() -> list[tuple[int, int]]:
    patches: list[tuple[int, int]] = []
    for a, code in caves().items():
        patches += words(a, code)
    # Sites d'appel en dernier : les routines sont en place avant d'être atteignables.
    patches += sites()
    return patches


if __name__ == "__main__":
    import capstone

    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)

    def dis(addr: int, word: int) -> str:
        ins = next(cs.disasm(word.to_bytes(4, "big"), addr), None)
        return f"{ins.mnemonic} {ins.op_str}" if ins else ".long"

    for a, code in caves().items():
        print(f"; cave {a:08X} ({len(code)} octets)")
        for addr, w in words(a, code):
            print(f"  {addr:08X}  {w:08X}  {dis(addr, w)}")
    print("; sites")
    for addr, w in sites():
        old = ORIGINAL.get(addr)
        if old is None:  # bl TCoord2D::setValue : recalculé
            old = int.from_bytes(assemble(f"bl {SETVALUE:#x}", addr), "big")
        print(f"  {addr:08X}  {old:08X} {dis(addr, old):<28} -> {w:08X}  {dis(addr, w)}")
    all_p = build()
    for addr, _ in all_p:
        assert (RANGE_LO <= addr < RANGE_HI) or addr in ORIGINAL or addr in SITES_COORD, hex(addr)
    print(f"; {len(all_p)} mots")
