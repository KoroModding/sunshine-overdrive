"""Volets HX (transitions d'écran) — portage de BetterSunshineEngine fps.cpp, l. 168–414.

Contexte
--------
Les volets HX sont dessinés par TSMSFader::draw -> Hx_UpdateWipe (0x8013FDE0
``bl Hx_UpdateWipe``), qui appelle la routine du volet via ``blrl`` entre deux
``GXDrawDone`` (0x80181F80 / 0x80181F90). Ces routines émettent des commandes
GX (GXBegin, écritures 0xCC008000) : elles tournent **une fois par image
rendue**. Tout ce qu'elles comptent en « images » va donc M fois trop vite, avec
M = 2 × f32@0x804167B8 (1 à 30 FPS, 2 à 60, 4 à 120), relu à **chaque** appel.

État partagé des volets : bloc à 0x803F43C0 (``lis r3,0x803F ; addi 0x43C0``),
dont le compte à rebours à +0x3C = **0x803F43FC** (Hx_TimerCountDown :
``lwz r3,0x3c(r3) ; addi r0,r3,-1 ; stw r0,0(r4)``) — même adresse que BSE
``HX_SetTimer``.

Principe des correctifs (tous sans état sauf TEST4)
---------------------------------------------------
* Durées entières : chaque ``stw rX, 0x3c(r31|r30)`` qui arme le compte à
  rebours devient ``bl TIMER_Rx`` qui écrit (int)(rX × M) dans 0x803F43FC.
* Incréments flottants par image : l'instruction ``fadds/fsubs fD, fA, fB``
  est remplacée par ``bl`` vers un bouchon qui refait la même opération avec
  l'incrément divisé par M. On garde ainsi la sémantique exacte de chaque site
  (y compris quand M change en cours de volet) sans toucher aux littéraux
  partagés du pool .sdata2.
* Incréments entiers par image : ``addi r0, r3, imm`` devient ``bl`` vers
  ``li r0, imm ; b INT_STEP`` qui calcule r0 = r3 + imm / (int)M.
* Hx_MotionUpdate (0x80181D74) est remplacée intégralement (``b MOTION``,
  comme SMS_PATCH_B de BSE) par la même intégration d'Euler au pas 1/M :
  temps += 1/M, vitesse += accel/M, position += vitesse/M.

Registres : les bouchons n'utilisent que r12, f12, f13 (+ r0 en sortie pour
INT_STEP). Aucune des fonctions Hx_Circle, Hx_GameOver, Hx_Test1, Hx_Test2,
Hx_Test2R, Hx_Test4, Hx_Test5 ne mentionne r11, r12, f12 ni f13 (vérifié par
grep sur leur désassemblage complet). Aucun bouchon ne modifie cr0 (aucune
instruction à Rc=1, pas de comparaison), ce qui compte à 0x80181C7C..C8C où
cr0 et r3 sont vivants.

Sites (instruction d'origine -> effet) — confiance
---------------------------------------------------
CIRCLE (Hx_Circle)
  0x80181B54  stw r0,0x3c(r31)   (li r0,0x19)  -> TIMER_R0      [BSE] haute
  0x80181B78  stw r0,0x3c(r31)   (li r0,0x1E)  -> TIMER_R0      [BSE] haute
  0x80181BBC  fadds f1,f2,f1     DE44 += 1/15 (fondu FrBufferMorf, borné à 1)
                                 -> f1 = f2 + f1/M  ; f0 = 1.0 vivant, intact
                                                                [AJOUT] haute
  0x80181C7C  fadds f0,f1,f0     DE30 += 0.05  -> f0 = f1 + f0/M  [AJOUT] haute
  0x80181C8C  addi r0,r3,0x180   u16 DE3C (alpha anneau 1)  -> r3+0x180/M [AJOUT]
  0x80181CE0  fadds f0,f1,f0     DE34 += 0.12                     [AJOUT]
  0x80181CF0  addi r0,r3,0xC0    u16 DE3E                         [AJOUT]
  0x80181D44  fadds f0,f1,f0     DE38 += 0.25                     [AJOUT]
  0x80181D54  addi r0,r3,0x80    u16 DE40                         [AJOUT]
  Ces 7 accumulateurs par image (anneaux d'étoiles de Hxs2_Circle et fondu du
  tampon) ne sont PAS traités par BSE : désaccord signalé, corrigés ici.

GAMEOVER (Hx_GameOver ; r29 = 0x803C1278, table (delta, durée) à +0x70)
  0x801804B0  stw r0,0x3c(r31)  (0x32)  -> TIMER_R0            [BSE] haute
  0x801804E8  stw r0,0x3c(r31)  (0x0A)  -> TIMER_R0            [BSE] haute
  0x801804F8  fadds f0,f1,f0    C6BC(mag) += 0.074 (f1) -> f0 = f0 + f1/M
              (BSE : 0x801804EC, retour 0.074/M ; même effet)   haute
  0x80180510  fadds f0,f2,f0    DE4C(fondu) += 5.1 (f2) -> f0 = f0 + f2/M
              (BSE : 0x80180514)                                haute
  0x80180548  stw r3,DE54       1re durée de la table (6.0) -> GO_TIMER_R3
              **Absent de BSE** : BSE divise le 1er delta (0x80180538) mais
              laisse sa durée à 6 images -> le 1er rebond n'atteint qu'1/M de
              son amplitude et décale tous les suivants. Désaccord.   haute
  0x80180558  fsubs f0,f1,f0    C6BC -= 0.1 (f0) -> f0 = f1 - f0/M
              (BSE : 0x8018055C)                                haute
  0x801805BC  stw r3,DE54       durées suivantes -> GO_TIMER_R3 [BSE] haute
  0x801805E0  stw r3,0x3c(r31)  (0x20) -> TIMER_R3 ; r0 = 0xFF vivant (stb
              suivant), non touché. BSE réécrit 0x801805E0/E4 pour le même
              résultat.                                          haute
  0x801805F4  fadds f0,f1,f0    C6BC += DE58 (delta de table, f0) -> f1 + f0/M
              Remplace les trois SMS_WRITE_32 de BSE (0x8018059C/A8/AC) et ses
              deux divisions du delta (0x80180538, 0x801805B0) : on divise
              l'incrément à l'endroit où il est appliqué, DE58 garde la valeur
              de la table. Un seul site au lieu de cinq.         haute
  0x80180610  stw r0,0x3c(r31)  (0x64) -> TIMER_R0             [BSE] haute
  0x80180624  addi r0,r3,8      alpha u8 DE5C += 8 -> r3 + 8/M
              (BSE : 0x80180628, 8/(u8)M ; identique). Sur 0x20×M images la
              somme vaut toujours 256 : l'alpha repart de 0xFF, boucle une fois
              et revient à 0xFF, comme à 30 FPS.                 haute
  0x80180500  bl Hx_MotionUpdate : couvert par le remplacement global.

TEST1   0x8017F5BC  stw r0,0x3c(r30) (0x19) -> TIMER_R0         [BSE] haute
TEST2   0x8017EFA0 / F014 / F0D0 / F1C0  stw r0,0x3c(r31) -> TIMER_R0 [BSE]
TEST2R  0x8017EB74 / EC90 / ED90 / EE5C  stw r0,0x3c(r31) -> TIMER_R0 [BSE]
        Aux 8 sites, r3 (argument de Hx_MotionSet qui suit) est vivant : les
        bouchons ne le touchent pas.                             haute

TEST4 (Hx_Test4)
  DE88 (u32, nb de segments) = cvt(DE88 + DE90) chaque image, DE90 = ±5 ;
  DE84 += DE8C (±0.15). L'entier perdrait les fractions de 5/M : comme BSE on
  garde un accumulateur flottant (T4STATE, état propre, hors [OnFrame]).
  0x8017E50C / 0x8017E530  stw r0,DE88 (0 ou 230) -> T4INIT : même stw, puis
              T4STATE = (float)r0. f0/f1/f2 (stockés juste après) intacts.
              (BSE : 0x8017E518 / 0x8017E53C.)
  0x8017E544  stw r0,0x3c(r31) (0x26) -> TIMER_R0              [BSE]
  0x8017E578  bl __cvt_fp2unsigned -> bl T4ACC : T4STATE += f0/M (f0 = DE90
              chargé en 0x8017E564), puis saut terminal vers
              __cvt_fp2unsigned(T4STATE) — qui renvoie 0 pour un négatif
              (compare à 0.0 @0x803AA8E8), d'où le Max(0,·) de BSE.
  0x8017E588  fadds f0,f1,f0  DE84 += DE8C -> f0 = f1 + f0/M
              (BSE divise DE8C à l'armement ; ici à l'application.)
  Confiance haute.

TEST5 (Hx_Test5)
  BSE ne décrémente le compteur qu'une image sur M (alternateur u8 jamais remis
  à zéro -> phase arbitraire, animation en marches d'escalier). Ici : durée
  20×M (0x8017E07C stw r0 -> TIMER_R0) et diviseur 20.0 -> 20×M
  (0x8017E14C ``lfs f1,-0x4614(r2)`` = 20.0 -> bl T5DIV, f1 = 20×M ; f0 est
  rechargé en 0x8017E15C, r0 déjà stocké en 0x8017E148). Le rapport
  timer/20 = f3 (0x8017E164–E174) décrit la même courbe, en 20×M pas au lieu
  de 20. Pas d'état. Le littéral 20.0 @0x8041258C est partagé (Hx_Circle, etc.) :
  on ne le modifie pas. Désaccord avec BSE (volontaire).       haute

MOTION (Hx_MotionUpdate 0x80181D74, feuille, f0/f1/r3 seulement)
  ``b MOTION`` sur la 1re instruction ; appelée par ``bl`` depuis 14 sites
  (xref), donc r12/f13 volatils selon l'ABI. fcmpo -> fcmpu (seule différence :
  pas d'exception sur NaN). Pour une motion trapézoïdale de Hx_MotionSet
  (2/8/1 images, Test2), la distance finale reste 9,5 × vmax à M = 1, 2 et 4
  (vérifié à la main) : les volets arrivent au même endroit.
  Hx_Door n'a pas de compte à rebours (fin sur la position) : correct avec le
  seul remplacement de Motion.
  **Hx_Logo** (0x8017FACC) : ses durées viennent d'une table et ne sont pas
  mises à l'échelle (ni par BSE, qui force 30 FPS pendant le logo). Pour ne pas
  désynchroniser mouvement et durée si M ≠ 1 pendant le logo, cet appel est
  redirigé vers MOTION_ORIG (instruction d'origine + ``b 0x80181D78``) : le
  logo garde son comportement d'origine, cohérent mais M fois trop rapide.

NON VÉRIFIÉ
-----------
* Que TSMSFader::draw (appel virtuel, aucun xref direct) soit bien appelé une
  fois par image rendue et non par sous-pas. Indices forts : Hx_UpdateWipe
  encadre l'appel de GXDrawDone, et les volets émettent des primitives GX.
  Même hypothèse que BSE.
* Rien n'a été exécuté dans Dolphin (interdit par le brief) : ni la durée
  réelle des volets à 120 FPS, ni le rendu des anneaux de Hx_Circle.
* Hx_Logo reste non corrigé (M fois trop rapide si M ≠ 1 pendant le logo).
  Dépendance : l'agent qui remet le jeu à 30 FPS en boot/logo/intro.

Disposition de la cave (0x80001800–0x80001FFF)
----------------------------------------------
  0x80001800  f64  MAGIC  0x43300000_00000000       constante (profil)
  0x80001808  u32  0x43300000                        constante (profil)
  0x8000180C  u32  SCR_LO  entrée entière            état, HORS profil
  0x80001810  f64  SCR2    sortie fctiwz             état, HORS profil
  0x80001818  f32  T4STATE accumulateur TEST4        état, HORS profil
  0x8000181C–0x800018AF  libre (0x800018A8 = crochet HLE de Dolphin, jamais exécuter)
  0x800018B0  code
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

RANGE = (0x80001800, 0x80002000)

BASE = 0x80001800
# Déplacements par rapport à r12 = 0x80000000 (« lis r12, 0x8000 » dans toutes
# les routines), donc ABSOLUS dans la page basse : 0x1800 + décalage dans la
# cave. Jusqu'au 2026-09-27 ils valaient 0x00–0x18 : les routines écrivaient
# dans l'en-tête disque (0x8000000C…) et lisaient 0x80000000 comme constante de
# conversion — minuteur HX saturé, volet sans fin, émulation à 13 champs/s.
LOW = 0x80000000
MAGIC = BASE - LOW + 0x00     # f64 0x4330000000000000
SCR = BASE - LOW + 0x08       # f64 : hi 0x43300000 (constante), lo = entrée (état)
SCR_LO = BASE - LOW + 0x0C
SCR2 = BASE - LOW + 0x10      # f64 : sortie de fctiwz (état)
T4STATE = BASE - LOW + 0x18   # f32 : accumulateur TEST4 (état)
# Le code commence APRÈS 0x800018A8 : Dolphin y pose le crochet HLE
# « GeckoCodehandler » (Gecko::ENTRY_POINT). Toute instruction exécutée à cette
# adresse incrémente le mot 0x80001800 et vide TOUT le cache JIT
# (HLE_Misc::GeckoCodeHandlerICacheFlush → iCache.Reset). Jusqu'au 2026-09-27
# le code partait de 0x80001820 et INT_STEP tombait sur 0x800018A8 : trois
# vidages par image pendant Hx_Circle, émulation à 8 champs/s.
CODE = 0x800018B0

TIMER_ADDR = 0x803F43FC
CVT_FP2UNSIGNED = 0x8033829C
MOTION_FN = 0x80181D74

# M = 2 × f32@0x804167B8 dans f13 (r12 écrasé).
LOAD_M = """
    lis    r12, 0x8041
    lfs    f13, 0x67B8(r12)
    fadds  f13, f13, f13
"""

# ---------------------------------------------------------------- routines
# Chaque entrée : (nom, source). Les sources peuvent référencer {nom} d'une
# routine précédente (adresse résolue à l'assemblage).


def _timer_core(dest: str) -> str:
    """SCR_LO contient l'entier non signé x ; écrit (int)(x × M) à dest."""
    return f"""
    lfd    f13, {SCR}(r12)
    lfd    f12, {MAGIC}(r12)
    fsub   f12, f13, f12
    {LOAD_M}
    fmul   f12, f12, f13
    fctiwz f12, f12
    {dest}
    blr
"""


TIMER_DEST_HX = f"""
    lis    r12, {TIMER_ADDR >> 16:#x}
    ori    r12, r12, {TIMER_ADDR & 0xFFFF:#x}
    stfiwx f12, 0, r12
"""
TIMER_DEST_GO = """
    li     r12, -0x636C
    stfiwx f12, r13, r12
"""


def _fstep(op: str, dst: str, old: str, inc: str) -> str:
    """Refait « op dst, old, inc » avec inc / M."""
    return f"""
    {LOAD_M}
    fdivs  f13, {inc}, f13
    {op}   {dst}, {old}, f13
    blr
"""


def _int_stub(imm: int) -> str:
    return f"""
    li     r0, {imm:#x}
    b      {{INT_STEP}}
"""


ROUTINES: list[tuple[str, str]] = [
    # --- compte à rebours HX (0x803F43FC) -----------------------------------
    ("TIMER_R0", f"""
    lis    r12, 0x8000
    stw    r0, {SCR_LO:#x}(r12)
""" + _timer_core(TIMER_DEST_HX)),
    ("TIMER_R3", f"""
    lis    r12, 0x8000
    stw    r3, {SCR_LO:#x}(r12)
    b      {{TIMER_R0}}+8
"""),
    # --- durée de segment GameOver (DE54) -----------------------------------
    ("GO_TIMER_R3", f"""
    lis    r12, 0x8000
    stw    r3, {SCR_LO:#x}(r12)
""" + _timer_core(TIMER_DEST_GO)),
    # --- r0 = r3 + r0 / (int)M ---------------------------------------------
    ("INT_STEP", f"""
    {LOAD_M}
    fctiwz f13, f13
    lis    r12, 0x8000
    stfd   f13, {SCR2:#x}(r12)
    lwz    r12, {SCR2 + 4:#x}(r12)
    divwu  r0, r0, r12
    add    r0, r3, r0
    blr
"""),
    # --- Hx_MotionUpdate au pas 1/M -----------------------------------------
    ("MOTION", f"""
    {LOAD_M}
    lfs    f0, 0(r3)
    lfs    f1, 0x1c(r3)
    fcmpu  cr0, f0, f1
    ble    decel
    lfs    f1, 0x18(r3)
    lfs    f0, 0xc(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x18(r3)
    b      tick
decel:
    lfs    f0, 4(r3)
    fcmpu  cr0, f0, f1
    cror   2, 0, 2
    bne    tick
    lfs    f1, 0x18(r3)
    lfs    f0, 0x14(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x18(r3)
tick:
    lfs    f1, 0x1c(r3)
    lfs    f0, -0x460c(r2)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x1c(r3)
    lfs    f1, 0x20(r3)
    lfs    f0, 0x18(r3)
    fdivs  f0, f0, f13
    fadds  f0, f1, f0
    stfs   f0, 0x20(r3)
    lfs    f1, 0x20(r3)
    blr
"""),
    # Version d'origine pour Hx_Logo : 1re instruction écrasée, puis la suite.
    ("MOTION_ORIG", f"""
    lfs    f0, 0(r3)
    b      {MOTION_FN + 4:#x}
"""),
    # --- TEST4 ----------------------------------------------------------------
    ("T4INIT", f"""
    stw    r0, -0x6338(r13)
    lis    r12, 0x8000
    stw    r0, {SCR_LO:#x}(r12)
    lfd    f13, {SCR:#x}(r12)
    lfd    f12, {MAGIC:#x}(r12)
    fsub   f13, f13, f12
    frsp   f13, f13
    stfs   f13, {T4STATE:#x}(r12)
    blr
"""),
    ("T4ACC", f"""
    {LOAD_M}
    fdivs  f13, f0, f13
    lis    r12, 0x8000
    lfs    f1, {T4STATE:#x}(r12)
    fadds  f1, f1, f13
    stfs   f1, {T4STATE:#x}(r12)
    b      {CVT_FP2UNSIGNED:#x}
"""),
    # --- TEST5 : diviseur 20.0 -> 20 × M --------------------------------------
    ("T5DIV", f"""
    {LOAD_M}
    lfs    f1, -0x4614(r2)
    fmuls  f1, f1, f13
    blr
"""),
    # --- incréments flottants par image -------------------------------------
    ("F_CIRCLE_DE44", _fstep("fadds", "f1", "f2", "f1")),
    ("F_A1_PLUS_F0", _fstep("fadds", "f0", "f1", "f0")),   # f0 = f1 + f0/M
    ("F_F0_PLUS_F1", _fstep("fadds", "f0", "f0", "f1")),   # f0 = f0 + f1/M
    ("F_F0_PLUS_F2", _fstep("fadds", "f0", "f0", "f2")),   # f0 = f0 + f2/M
    ("F_F1_MINUS_F0", _fstep("fsubs", "f0", "f1", "f0")),  # f0 = f1 - f0/M
    # --- incréments entiers par image ---------------------------------------
    ("I_0x180", _int_stub(0x180)),
    ("I_0xC0", _int_stub(0xC0)),
    ("I_0x80", _int_stub(0x80)),
    ("I_0x8", _int_stub(0x8)),
]

# (site, routine, instruction d'origine attendue, commentaire)
SITES: list[tuple[int, str, int, str]] = [
    # CIRCLE
    (0x80181B54, "TIMER_R0", 0x901F003C, "Circle timer 0x19"),
    (0x80181B78, "TIMER_R0", 0x901F003C, "Circle timer 0x1E"),
    (0x80181BBC, "F_CIRCLE_DE44", 0xEC22082A, "Circle DE44 += 1/15 (ajout)"),
    (0x80181C7C, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE30 += 0.05 (ajout)"),
    (0x80181C8C, "I_0x180", 0x38030180, "Circle DE3C += 0x180 (ajout)"),
    (0x80181CE0, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE34 += 0.12 (ajout)"),
    (0x80181CF0, "I_0xC0", 0x380300C0, "Circle DE3E += 0xC0 (ajout)"),
    (0x80181D44, "F_A1_PLUS_F0", 0xEC01002A, "Circle DE38 += 0.25 (ajout)"),
    (0x80181D54, "I_0x80", 0x38030080, "Circle DE40 += 0x80 (ajout)"),
    # GAMEOVER
    (0x801804B0, "TIMER_R0", 0x901F003C, "GameOver timer 0x32"),
    (0x801804E8, "TIMER_R0", 0x901F003C, "GameOver timer 0x0A"),
    (0x801804F8, "F_F0_PLUS_F1", 0xEC01002A, "GameOver C6BC += 0.074"),
    (0x80180510, "F_F0_PLUS_F2", 0xEC02002A, "GameOver DE4C += 5.1"),
    (0x80180548, "GO_TIMER_R3", 0x906D9C94, "GameOver DE54 1re durée (ajout)"),
    (0x80180558, "F_F1_MINUS_F0", 0xEC010028, "GameOver C6BC -= 0.1"),
    (0x801805BC, "GO_TIMER_R3", 0x906D9C94, "GameOver DE54 durées"),
    (0x801805E0, "TIMER_R3", 0x907F003C, "GameOver timer 0x20"),
    (0x801805F4, "F_A1_PLUS_F0", 0xEC01002A, "GameOver C6BC += DE58"),
    (0x80180610, "TIMER_R0", 0x901F003C, "GameOver timer 0x64"),
    (0x80180624, "I_0x8", 0x38030008, "GameOver alpha DE5C += 8"),
    # TEST1 / TEST2 / TEST2R
    (0x8017F5BC, "TIMER_R0", 0x901E003C, "Test1 timer 0x19"),
    (0x8017EFA0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0B"),
    (0x8017F014, "TIMER_R0", 0x901F003C, "Test2 timer 0x0B"),
    (0x8017F0D0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0A"),
    (0x8017F1C0, "TIMER_R0", 0x901F003C, "Test2 timer 0x0C"),
    (0x8017EB74, "TIMER_R0", 0x901F003C, "Test2R timer 0x0B"),
    (0x8017EC90, "TIMER_R0", 0x901F003C, "Test2R timer 0x0B"),
    (0x8017ED90, "TIMER_R0", 0x901F003C, "Test2R timer 0x0A"),
    (0x8017EE5C, "TIMER_R0", 0x901F003C, "Test2R timer 0x0C"),
    # TEST4
    (0x8017E50C, "T4INIT", 0x900D9CC8, "Test4 DE88 = 0 / état"),
    (0x8017E530, "T4INIT", 0x900D9CC8, "Test4 DE88 = 230 / état"),
    (0x8017E544, "TIMER_R0", 0x901F003C, "Test4 timer 0x26"),
    (0x8017E578, "T4ACC", None, "Test4 bl __cvt_fp2unsigned -> accumulateur"),
    (0x8017E588, "F_A1_PLUS_F0", 0xEC01002A, "Test4 DE84 += DE8C"),
    # TEST5
    (0x8017E07C, "TIMER_R0", 0x901F003C, "Test5 timer 0x14"),
    (0x8017E14C, "T5DIV", 0xC022B9EC, "Test5 diviseur 20.0"),
    # MOTION (Logo d'abord redirigé vers l'original, puis la fonction elle-même)
    (0x8017FACC, "MOTION_ORIG", None, "Hx_Logo bl Hx_MotionUpdate -> original"),
]
SITE_MOTION = (MOTION_FN, "MOTION", 0xC0030000, "Hx_MotionUpdate -> b MOTION")


def _assemble_all() -> dict[str, tuple[int, bytes]]:
    out: dict[str, tuple[int, bytes]] = {}
    addr = CODE
    for name, src in ROUTINES:
        resolved = src
        for other, (a, _) in out.items():
            resolved = resolved.replace("{" + other + "}", f"{a:#x}")
        code = assemble(resolved, addr)
        assert code, name
        out[name] = (addr, code)
        addr += (len(code) + 3) & ~3
    return out


def _data() -> list[tuple[int, int]]:
    """Constantes seulement ; SCR_LO, SCR2, T4STATE sont de l'état, exclus."""
    return [
        (LOW + MAGIC, 0x43300000),
        (LOW + MAGIC + 4, 0x00000000),
        (LOW + SCR, 0x43300000),
    ]


def build() -> list[tuple[int, int]]:
    caves = _assemble_all()
    patches = _data()
    for addr, code in caves.values():
        patches += words(addr, code)
    for site, name, _orig, _c in SITES:
        target = caves[name][0]
        patches += words(site, assemble(f"bl {target:#x}", site))
    site, name, _orig, _c = SITE_MOTION
    patches += words(site, assemble(f"b {caves[name][0]:#x}", site))
    return patches


def main() -> int:
    import capstone

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dol import Dol

    root = Path(__file__).resolve().parents[2]
    dol = Dol(root / "work" / "dol" / "GMSE01.dol")
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)

    def dis(addr: int, raw: bytes) -> str:
        rows = [f"{i.mnemonic:<8}{i.op_str}" for i in cs.disasm(raw, addr)]
        return rows[0] if rows else f".word {raw.hex()}"

    caves = _assemble_all()
    for name, (addr, code) in caves.items():
        print(f"; {name} @ {addr:08X}")
        for i in range(0, len(code), 4):
            w = code[i:i + 4]
            print(f"  {addr + i:08X}  {w.hex().upper()}  {dis(addr + i, w)}")
    print()

    patches = build()
    cave_end = max(a + len(c) for a, c in caves.values())
    print(f"cave : {CODE:08X}–{cave_end:08X}  ({cave_end - RANGE[0]} octets sur {RANGE[1] - RANGE[0]})")
    for a, _ in patches:
        if RANGE[0] <= a < RANGE[1]:
            assert a not in (LOW + SCR_LO, LOW + SCR2, LOW + SCR2 + 4, LOW + T4STATE), hex(a)
    assert cave_end <= RANGE[1]

    print("\n; sites (avant -> après)")
    site_words = dict(patches)
    for site, name, orig, comment in SITES + [SITE_MOTION]:
        before = dol.u32(site)
        if orig is not None:
            assert before == orig, f"{site:08X}: {before:08X} != {orig:08X}"
        after = site_words[site]
        print(f"  {site:08X}  {before:08X} {dis(site, before.to_bytes(4, 'big')):<28} -> "
              f"{after:08X} {dis(site, after.to_bytes(4, 'big')):<16} ; {comment}")

    # Tout ce qui n'est pas un site doit être dans la plage de la cave.
    sites = {s for s, *_ in SITES} | {SITE_MOTION[0]}
    for a, _ in patches:
        assert a in sites or RANGE[0] <= a < RANGE[1], hex(a)
    print(f"\n{len(patches)} mots ; [OnFrame] :")
    for a, v in patches:
        print(f"0x{a:08X}:dword:0x{v:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
