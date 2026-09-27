"""Groupe « contextes forcés à 30 FPS » — port de BSE fps.cpp l. 34-65 (updateFPS) et l. 509-514 (QFSync).

Principe
========
Le littéral f32 0x804167B8 (lu par SMSGetVSyncTimesPerSec = 60 x lit, et par
SMSGetAnmFrameRate) et TDisplay::mRetraceCount (+0x4C) ne sont plus posés par
[OnFrame] : une routine en caverne les écrit selon le contexte courant de
TApplication, avant la mise en place de chaque directeur ET au début de chaque
image. Les autres groupes relisent M = 2 x lit à l'exécution, donc tous leurs
correctifs suivent (M = 1 en contexte forcé, 4 sinon).

    contexte (gpApplication.mAppState, u8 +0x08)   littéral   mRetraceCount   cadence
    0..4  (LOAD_LOOP, MAIN_LOOP, BOOT, LOGO, INTRO)  0.5f        5              29,97
    5..9  (STAGE, MOVIE, SHUTDOWN, SELECT, MENU)     2.0f        2             119,88

LIGNES [OnFrame] EXISTANTES À RETIRER / CONSERVER (deliver/GMSE01.ini)
======================================================================
  * À RETIRER impérativement :  0x804167B8:dword:0x40000000
      Sinon le PatchEngine réécrit 2.0f à chaque champ VI, au milieu d'une image
      forcée à 0.5f : horloge logique et M incohérents d'un champ à l'autre.
      Sans cette ligne, le mot vaut 0.5f (valeur du DOL) jusqu'au premier
      passage de la routine — c'est la valeur voulue pour l'amorçage.
  * À CONSERVER :  0x802FCB24:dword:0x60000000  (les comptes 2 et 5 ci-dessous
      supposent l'attente finale de waitForRetrace neutralisée).
  * Aucune autre ligne existante n'est touchée.
  * Outils : tools/keep120.py (réécrit 0x804167B8 = 2.0 et +0x4C par données)
    ne doit plus être lancé avec ce profil ; tools/validate_120.py signalera
    [NON] sur le littéral pendant boot / logo / intro — c'est attendu.

Adresses et offsets (preuves)
=============================
  gpApplication = 0x803E9700  (us.map ; et proc 802A639C lis r4,0x803F / 802A63B4 addi r26,r4,-0x6900)
  mAppState  +0x08 u8   gameLoop 802A60A0 lbz r0,8(r31) ; cmplwi r0,2 (BOOT)
                        proc 802A67C8 lbz r0,8(r31) ; 802A6794 stb r30,8(r31)
  mDisplay   +0x1C      gameLoop 802A5F98 lwz r3,0x1c(r31) puis appel virtuel startRendering
  mRetraceCount +0x4C   endRendering 802F80E8 lhz r4,0x4c(r31) ; 802F80EC bl waitForRetrace
  TMarDirector::mCurState +0x64 u8  direct 802999D8 lbz r0,0x64(r26) ; ctor 80297124 stb r30,0x64(r29)

Énumération des contextes — BSE (SunshineHeaderInterface, Application.hxx) :
LOAD_LOOP 0, MAIN_LOOP 1, GAME_BOOT 2, GAME_BOOT_LOGO 3, GAME_INTRO 4, DIRECT_STAGE 5,
DIRECT_MOVIE 6, GAME_SHUTDOWN 7, SHINE_SELECT 8, LEVEL_SELECT 9. Recoupé avec la décompilation
(APP_STATE_WAIT 0 … MENU 9) et la table de sauts de proc en 0x803DF424 lue dans le DOL :
  2 -> 802A63E4 SMSSetupGCLogoRenderingInfo seul                (BOOT)
  3 -> 802A63F0 TGCLogoDir::setup                               (LOGO Nintendo)
  4 -> 802A65D8 mMovie = 9, mNextArea = 15, puis TMovieDirector (INTRO)
  5 -> 802A64A0 checkAdditionalMovie / TMarDirector::setup       (STAGE)
  6 -> 802A65F4 TMovieDirector                                  (MOVIE)
  8 -> 802A6580 TSelectDir::setup ; 9 -> 802A6428 TMenuDirector::setup ; 0,1,7 -> 802A6644 (rien)
0 et 1 ne sont jamais la valeur de mAppState en pratique (gameLoop boucle tant que
nextState <= 1, 802A635C cmplwi r29,1 / ble) ; ils sont inclus comme chez BSE, sans effet.

mRetraceCount pour 30 FPS = 5 (et non 2 comme chez BSE)
--------------------------------------------------------
waitForRetrace, avec 802FCB24 (bl VIWaitForRetrace final) remplacé par nop :
  802FC9C8 bl VIWaitForRetrace / 802FC9CC bl VIGetRetraceCount / 802FC9D0 lwz r0,0x84(r30)
  802FC9D4 subf r0,r3,r0 / 802FC9D8 cmpwi r0,1 / 802FC9DC bgt 802FC9C8   -> attend next - count <= 1
  802FCB30 bl VIGetRetraceCount / 802FCB34 clrlwi r0,r31,16 / 802FCB38 add / 802FCB3C stw r0,0x84(r30)
  -> next = count + mRetraceCount. En régime permanent : mRetraceCount - 1 champs par image.
  120 FPS : 2 -> 1 champ (119,88/s). 30 FPS : 4 champs voulus -> mRetraceCount = 5.
BSE écrit 2 / 1 / 0 parce que son attente finale est intacte (champs = max(1, mRetraceCount)).
Aucun écrivain de +0x4C dans SMSSetup{Movie,Game,Title,GCLogo}RenderingInfo (lus jusqu'au blr).

Fix 1 — sélection du contexte (updateFPS de BSE)
================================================
Routine « core » (r31 = &gpApplication aux deux sites) : lit mAppState ; si <= 4 écrit
0.5f dans 0x804167B8 et 5 dans mDisplay->mRetraceCount, sinon 2.0f et 2. Les deux
valeurs du littéral sont des constantes de la caverne (0x80002800 / 0x80002804) :
changer le palier « normal » se fait là. Deux sites d'appel :

  a) 0x802A63C4  proc+0x2C  « cmplwi r0, 9 » (tête du switch, cible unique : 802A67D0 bne)
     -> bl entry_proc, qui appelle core puis refait lbz r0,8(r31) / cmplwi r0,9 (cr0 lu
     par 802A63D0 bgt ; li r30 / li r29 intermédiaires ne touchent pas cr0).
     Pourquoi ici : c'est AVANT la construction du directeur du nouveau contexte. Chez
     BSE, updateFPS tourne juste avant direct() (hook 0x802A616C), donc le setup d'un
     directeur voit encore le littéral du contexte précédent (ex. TMarDirector::setup
     après l'intro à 30). Ici le setup voit le littéral de son propre contexte :
     setup de stage à 2.0 comme dans le profil 120 déjà mesuré, TGCLogoDir (ctor
     802963C0 bl SMSGetVSyncTimesPerSec ; 802963CC stfs f1,0x28) à 30 comme l'original.
     DÉSACCORD mineur avec BSE, volontaire.
  b) 0x802A5F98  gameLoop+0x48  « lwz r3, 0x1c(r31) » (tête de boucle d'image, cible
     unique : 802A6360 ble) -> bl entry_frame, qui appelle core puis exécute le lwz.
     r0/r4-r6/r11 sont morts à ce point (802A5F9C lwz r12,0(r3) ; r0 réécrit en
     802A5FC4). Redondant avec (a) tant que rien d'autre n'écrit +0x4C ou le littéral ;
     garde-fou à coût négligeable, et couvre BOOT/LOGO que le hook BSE (0x802A616C,
     branche « else » de gameLoop) ne couvre pas.
  Ordre dans l'image : core -> startRendering -> direct() -> endRendering/waitForRetrace :
  le littéral et mRetraceCount valent pour l'image entière.

Fix 2 — QFSync : 30 « vsync/s » dans TMarDirector::direct pendant STATE_INTRO_INIT
=================================================================================
Site 0x80299850 direct+0x18 « bl SMSGetVSyncTimesPerSec » (r3 = this, 8029984C mr r26,r3)
-> bl qfsync : si this->mCurState (+0x64) == 0 (STATE_INTRO_INIT, SunshineHeaderInterface
MarDirector.hxx) renvoie f1 = 30.0f, sinon saut terminal vers SMSGetVSyncTimesPerSec
(lr intact -> retour en 80299854). Effet : vsyncRate = 600/30 = 20 -> 4 sous-pas pour la
première image du stage, comme le jeu d'origine, avant le premier dessin.
BSE teste aussi mContext == DIRECT_STAGE et mDirector != 0 : implicite ici, un TMarDirector
n'existe qu'en contexte 5 (802A6550 bl __ct__12TMarDirector, seul cas de la table) et
direct() reçoit this.
Durée : changeState a un seul appelant (xref : 80299D0C), DANS la boucle de sous-pas
(80299D20 b 8029994C, retour en tête de boucle) ; son cas 0 (80298EC4…) choisit l'état
suivant sans compteur. L'état 0 est donc quitté dès le premier sous-pas, mais vsyncRate a
déjà été calculé (20) en tête de direct() : la première image « pleine » du stage fait 4
sous-pas, les suivantes 1. Les images où le thread de setup n'a pas fini sortent en
80299890, AVANT l'accumulateur (80299938-80299944), et ne comptent pas.
NON VÉRIFIÉ : le bogue exact que BSE corrige ainsi (probablement des objets qui doivent avoir
reçu plusieurs sous-pas avant le premier dessin). Port fidèle, coût borné (3 sous-pas de plus,
25 ms de simulation, une fois par entrée de stage).

Accumulateur (TMarDirector +0x54) aux changements de contexte
=============================================================
80299938-80299944 : unk54 += 600/(int)SMSGetVSyncTimesPerSec() ; la boucle retire 5 par
sous-pas et s'arrête dès unk54 < 5 (80299980 cmpwi r0,5), donc le reste est toujours dans
[0,5). Un changement de vsyncRate (5 <-> 20) ne peut ni créer de rafale ni de dette : il
change seulement le nombre de sous-pas de l'image suivante (1 ou 4). De plus le littéral
ne change qu'entre deux directeurs (mAppState n'est écrit qu'en 802A6794, hors gameLoop),
et chaque TMarDirector repart de unk54 = 0 (ctor 802970A4 stw r30,0x54(r29) ; r30 = 0
NON VÉRIFIÉ formellement, même registre que mCurState = 0). Le seul changement en cours
de stage est QFSync, borné ci-dessus.

Dépendances / effets sur les autres groupes
===========================================
  * Tous les groupes lisent M = 2 x f32[0x804167B8] : M = 1 en boot/logo/intro, 4 sinon.
  * Fader (fader.py, Fix 3) : TApplication::initialize (802A7730) construit mFader AVANT
    proc, donc avec le littéral du DOL (0.5 -> taux 30), puisque la ligne [OnFrame] du
    littéral est retirée. Cohérent avec l'hypothèse « +0x14 = 30 » de ce groupe et de BSE.
  * TMenuDirector (ctor 802A4250) et TMovieDirector::direct (802B6388) voient 120 :
    inchangé par rapport au profil actuel. Les films THP (contexte 6, et 5 si
    checkAdditionalMovie) restent à 120 comme chez BSE — NON VÉRIFIÉ à l'écran.
  * drawDVDErr (802A5EFC) lit le même littéral : centrage correct du message en
    contexte forcé seulement (effet de bord déjà connu du profil).
  * Le PatchEngine réécrit les mots de la caverne et des sites à chaque champ : écritures
    idempotentes, aucun état mutable dans la caverne.

NON VÉRIFIÉ (global) : comportement en exécution — rien n'a été lancé dans Dolphin.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002800
CAVE_END = 0x80002C00  # exclu

# Données (constantes, réécrites par le profil sans dommage)
LIT_FAST = 0x80002800   # 2.0f  littéral hors contexte forcé (palier 120)
LIT_SLOW = 0x80002804   # 0.5f  littéral en contexte forcé (30 FPS)
QF_CONST = 0x80002808   # 30.0f valeur QFSync
CODE = 0x80002810
DEBUG_FORCE30 = 0x80002BFC  # u32, diagnostic : non nul = 30 FPS partout (état, jamais écrit par le profil)

RC_FAST = 2   # mRetraceCount palier 120 (1 champ, attente finale neutralisée)
RC_SLOW = 5   # mRetraceCount 30 FPS (4 champs)
MAX_FORCED_STATE = 4  # contextes 0..4 forcés

LITERAL = 0x804167B8
SMS_GET_VSYNC = 0x802A7C48

SITE_PROC = 0x802A63C4    # cmplwi r0, 9
SITE_FRAME = 0x802A5F98   # lwz r3, 0x1c(r31)
SITE_QFSYNC = 0x80299850  # bl SMSGetVSyncTimesPerSec

ORIGINAL = {
    SITE_PROC: 0x28000009,
    SITE_FRAME: 0x807F001C,
    SITE_QFSYNC: 0x4800E3F9,
}


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def _core_source() -> str:
    return f"""
    lis    r4, 0x8000
    lwz    r3, {DEBUG_FORCE30 - 0x80000000:#x}(r4)
    cmpwi  r3, 0
    bne    forced
    lbz    r3, 8(r31)
    cmplwi r3, {MAX_FORCED_STATE}
    ble    forced
    lwz    r5, {LIT_FAST - 0x80000000:#x}(r4)
    li     r6, {RC_FAST}
    b      store
forced:
    lwz    r5, {LIT_SLOW - 0x80000000:#x}(r4)
    li     r6, {RC_SLOW}
store:
    lis    r4, {LITERAL >> 16:#x}
    stw    r5, {LITERAL & 0xFFFF:#x}(r4)
    lwz    r3, 0x1c(r31)
    cmplwi r3, 0
    beq    done
    sth    r6, 0x4c(r3)
done:
    blr
"""


def build_blocks() -> dict[str, tuple[int, bytes]]:
    core_addr = CODE
    core = assemble(_core_source(), core_addr)

    frame_addr = core_addr + len(core)
    frame = assemble(f"""
    mflr   r11
    bl     {core_addr:#x}
    mtlr   r11
    lwz    r3, 0x1c(r31)
    blr
""", frame_addr)

    proc_addr = frame_addr + len(frame)
    proc = assemble(f"""
    mflr   r11
    bl     {core_addr:#x}
    mtlr   r11
    lbz    r0, 8(r31)
    cmplwi r0, 9
    blr
""", proc_addr)

    qf_addr = proc_addr + len(proc)
    qf = assemble(f"""
    lbz    r0, 0x64(r3)
    cmplwi r0, 0
    beq    intro
    b      {SMS_GET_VSYNC:#x}
intro:
    lis    r4, 0x8000
    lfs    f1, {QF_CONST - 0x80000000:#x}(r4)
    blr
""", qf_addr)

    return {
        "core": (core_addr, core),
        "entry_frame": (frame_addr, frame),
        "entry_proc": (proc_addr, proc),
        "qfsync": (qf_addr, qf),
    }


def build() -> list[tuple[int, int]]:
    blocks = build_blocks()
    patches: list[tuple[int, int]] = [
        (LIT_FAST, _f32(2.0)),
        (LIT_SLOW, _f32(0.5)),
        (QF_CONST, _f32(30.0)),
    ]
    for addr, code in blocks.values():
        patches += words(addr, code)
    # Sites d'appel en dernier.
    patches += words(SITE_QFSYNC, assemble(f"bl {blocks['qfsync'][0]:#x}", SITE_QFSYNC))
    patches += words(SITE_PROC, assemble(f"bl {blocks['entry_proc'][0]:#x}", SITE_PROC))
    patches += words(SITE_FRAME, assemble(f"bl {blocks['entry_frame'][0]:#x}", SITE_FRAME))
    return patches


def _listing(address: int, code: bytes) -> str:
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    return "\n".join(
        f"  {i.address:08X}  {int.from_bytes(i.bytes, 'big'):08X}  {i.mnemonic:<8}{i.op_str}"
        for i in cs.disasm(code, address)
    )


def main() -> int:
    blocks = build_blocks()
    patches = build()
    sites = set(ORIGINAL)

    for name, (addr, code) in blocks.items():
        print(f"; {name} @ {addr:08X}")
        print(_listing(addr, code))
        print()

    print("; sites (avant -> après)")
    for addr, value in patches:
        if addr in sites:
            before = _listing(addr, ORIGINAL[addr].to_bytes(4, "big"))
            after = _listing(addr, value.to_bytes(4, "big"))
            print(before)
            print(after)
            print()

    # Vérification des valeurs d'origine aux sites, si le DOL est disponible.
    root = Path(__file__).resolve().parents[2]
    dol_path = root / "work" / "dol" / "GMSE01.dol"
    if dol_path.exists():
        from dol import Dol
        dol = Dol(dol_path)
        for addr, orig in ORIGINAL.items():
            got = dol.u32(addr)
            assert got == orig, f"{addr:08X}: DOL {got:08X} != attendu {orig:08X}"
        assert dol.u32(LITERAL) == _f32(0.5), "littéral DOL != 0.5f"
        print("; valeurs d'origine des sites vérifiées dans le DOL")

    for addr, _ in patches:
        if addr in sites:
            continue
        assert CAVE_START <= addr and addr + 4 <= CAVE_END, f"{addr:08X} hors de la caverne"
    end = max(a for a, _ in patches if a not in sites) + 4
    print(f"; caverne {CAVE_START:08X}-{end - 1:08X} dans {CAVE_START:08X}-{CAVE_END - 1:08X}")
    print(f"; {len(patches)} mots")
    print()
    for addr, value in patches:
        print(f"0x{addr:08X}:dword:0x{value:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
