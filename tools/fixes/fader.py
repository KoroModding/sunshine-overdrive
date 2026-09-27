"""Groupe TSMSFader — fondus noirs/blancs de l'application (BSE fps.cpp l. 418-439).

Convention : M = 2 x f32[0x804167B8], relu à l'exécution (1 à 30 FPS, 2 à 60, 4 à 120).
Plage de caves : 0x80002000 - 0x800021FF (aucun mot d'état : tout est recalculé à chaque appel).

Structure TSMSFader (lue au désassembleur, GMSE01)
--------------------------------------------------
    +0x10 u16  durée du fondu en images      (écrit par requestWipe, 0x8013F978 etc.)
    +0x12 u16  compteur d'images écoulées    (update : lhz/addi 1/sth, 0x8013FEF0 / 0x8013FF30)
    +0x14 f32  « images par seconde » du fader (ctor 0x80140080 : stfs f31, 0x14(r31))
    +0x24      requête en attente {u32 kind, f32 speed(s), f32 delay(s)} (startWipe 0x8013F860)
    +0x2C f32  délai restant (secondes)
    +0x30/+0x34 copie de kind / delay de la requête active

Preuve « une fois par image rendue » : TApplication::gameLoop appelle directement
mFader->update() par la vtable (slot +0x24 de __vt__9TSMSFader 0x803BFFC8 = 0x8013FE24) :
    802A6288  lwz r3, 0x34(r31) / lwz r12, 0(r3) / lwz r12, 0x24(r12) / blrl
une seule fois par tour de gameLoop, hors de l'accumulateur de sous-pas de TMarDirector::direct.

Fix 1 — durée du fondu (remplace les 4 SMS_PATCH_BL de BSE, adjustFaderFrameRate)
------------------------------------------------------------------------------------
requestWipe calcule   8013F8B4 lfs f1,4(r4) ; 8013F8B8 lfs f0,0x14(r29) ; 8013F8C0 fmuls f0,f1,f0
                      8013F8C8 fctiwz ; 8013F8D0 lwz r31,0x14(r1)      -> r31 = (int)(speed*rate)
puis, pour les fondus (kind 0xE/0x10 -> 0x8013F94C, kind 0xF/0x11 -> 0x8013F9A8) :
    état 0/1 (repos) :  sth r31, 0x10(r29)                     (8013F978 / 8013F9D4)
    état 3/2 (inversion en cours de fondu) :
        8013F994 mullw r0, r31, r0 ; 8013F998 divw r0, r0, r3 ; 8013F99C sth r0, 0x12(r29)
        8013F9A0 sth r31, 0x10(r29)                            (idem 8013F9F0..8013F9FC)
update() avance le compteur d'une unité par image et termine quand +0x12 > +0x10 ; à 120 FPS le
fondu dure donc 4x moins longtemps. Correction : multiplier r31 par M.
DÉSACCORD avec BSE : BSE remplace seulement les 4 `sth r31, 0x10(r29)` par _10 = speed*rate*M, mais
dans la branche « inversion » le compteur +0x12 a déjà été recalculé avec r31 NON multiplié
(8013F994) : le fondu inversé repart d'une position fausse (saut d'opacité). Ici on recalcule r31
en tête des deux branches fondu : `lwz r0, 0x20(r29)` en 0x8013F94C et 0x8013F9A8 devient
`bl fader_dur`, qui fait r31 = (int)(fmuls(speed, rate) * M) puis exécute le lwz remplacé.
Le produit est identique à l'original multiplié par M (M puissance de 2, exact en f32).
r31 est non volatil mais c'est ici la variable locale de requestWipe (sauvée dans son prologue) :
la modifier est exactement le but. Le cave réutilise l'emplacement temporaire 0x10(r1) que
requestWipe emploie déjà pour son propre fctiwz (8013F8CC stfd f0, 0x10(r1)).
La branche HX (kind hors 0xE-0x11, 8013FA04 `mr r4, r31` -> Hx_StartWipe) n'est PAS touchée :
elle relève du groupe « transitions HX » (comme chez BSE).

Fix 2 — délai avant fondu (remplace SMS_PATCH_B 0x8013F860, trickFaderDelayToBeCorrect)
-----------------------------------------------------------------------------------------
update() :  8013FE44 lfs f1, 1.0 ; 8013FE48 lfs f0, 0x14(r31) ; 8013FE4C lfs f2, 0x2c(r31)
            8013FE50 fdivs f1, f1, f0 ; 8013FE58 fsubs f2, f2, f1 ; ... stfs f2, 0x2c(r31)
Le délai (secondes) décroît de 1/rate par image rendue -> 4x trop vite à 120 FPS.
BSE multiplie le délai par M dans startWipe (et par le multiplicateur « game over » si kind == 0xD,
qui vaut aussi M dans notre convention : la distinction disparaît). Ici on corrige à la
consommation plutôt qu'à l'écriture : `lfs f0, 0x14(r31)` en 0x8013FE48 devient `bl fader_delay`,
qui charge f0 = rate * M. Équivalent, mais couvre tout écrivain de +0x2C et suit M si le taux
change entre la requête et son échéance. f1 (1.0 déjà chargé) est préservé : le cave n'utilise
que f0, f3 et r12 (non vivants dans update).

Fix 3 — taux du fader d'application figé à 30 (hors BSE, trouvé à la lecture)
-------------------------------------------------------------------------------
TApplication::initialize construit mFader avec le taux courant :
    802A7730 bl SMSGetVSyncTimesPerSec   ; f1 = 60 * f32[0x804167B8]  (802A7C94/802A7C9C)
    802A776C bl TSMSFader::TSMSFader(TColor, float, const char*)   (f1 inchangé entre les deux)
    80140080 stfs f31, 0x14(r31)
Sous BSE, le littéral vaut 0.5 à ce moment (le callback BSE ne tourne qu'à partir de gameLoop)
donc +0x14 = 30. Chez nous, si Dolphin a déjà appliqué le profil (littéral = 2.0) avant
initialize, +0x14 = 120 et les fondus seraient DÉJÀ corrects — le Fix 1/2 les ralentirait alors
4x de trop. NON VÉRIFIÉ : l'ordre « premier passage PatchEngine / TApplication::initialize ».
Pour être déterministe, le bl est redirigé vers fader_init qui renvoie
SMSGetVSyncTimesPerSec() / M = 60*lit / (2*lit) = 30 (25 en PAL), c.-à-d. la valeur d'origine
quelle que soit l'heure d'application du profil. Si le profil n'est pas encore appliqué à
initialize, ni ce bl ni le littéral ne le sont : résultat 30 aussi. Cohérent avec les hypothèses
de BSE, que le groupe HX reprend (Hx_UpdateWipe reçoit f1 = fader+0x14, 8013FDDC).

Compteurs vus mais NON corrigés
-------------------------------
- TShineFader (vtable 0x803C10F0, update 0x8017D8D4) : compteur +0x12 par update, durée +0x10 et
  attente +0x38 posées par registFadeout, appelé depuis TMarDirector::updateGameMode (80297BAC..
  80297BD8 : 1.0*rate et 5.333*rate, rate = +0x14 = 60.0 constant, 8029D9E4). Ce fader est
  dans la scène (TMarNameRefGen), exécuté par les perform lists du directeur : NON VÉRIFIÉ s'il
  tourne par sous-pas (alors correct) ou par image (alors 4x trop rapide à 120). BSE n'y touche
  pas. À mesurer (fondu après obtention d'un Shine) avant toute correction.
- TSmplFader (vtable 0x803C111C) : partage TSMSFader::update, donc profite des Fix 1/2 s'il
  reçoit des requêtes ; rate = 60.0 constant (8029D978), non affecté par le Fix 3.
- Branche HX de requestWipe / Hx_UpdateWipe : groupe HX.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002000
CAVE_END = 0x800021FF

FADER_DUR = 0x80002000
FADER_DELAY = 0x80002040
FADER_INIT = 0x80002060

SMS_GET_VSYNC = 0x802A7C48

# Sites d'appel : (adresse, mot d'origine attendu, cible du bl)
SITES = [
    (0x8013F94C, 0x801D0020, FADER_DUR),    # lwz r0, 0x20(r29)   branche fondu 0xE/0x10
    (0x8013F9A8, 0x801D0020, FADER_DUR),    # lwz r0, 0x20(r29)   branche fondu 0xF/0x11
    (0x8013FE48, 0xC01F0014, FADER_DELAY),  # lfs f0, 0x14(r31)   décompte du délai
    (0x802A7730, 0x48000519, FADER_INIT),   # bl SMSGetVSyncTimesPerSec (ctor de mFader)
]

SRC_DUR = """
    lfs     f1, 4(r30)
    lfs     f0, 0x14(r29)
    fmuls   f0, f1, f0
    lis     r12, 0x8041
    lfs     f1, 0x67B8(r12)
    fadds   f1, f1, f1
    fmuls   f0, f0, f1
    fctiwz  f0, f0
    stfd    f0, 0x10(r1)
    lwz     r31, 0x14(r1)
    lwz     r0, 0x20(r29)
    blr
"""

SRC_DELAY = """
    lfs     f0, 0x14(r31)
    lis     r12, 0x8041
    lfs     f3, 0x67B8(r12)
    fadds   f3, f3, f3
    fmuls   f0, f0, f3
    blr
"""

SRC_INIT = f"""
    mflr    r0
    stw     r0, 4(r1)
    stwu    r1, -0x10(r1)
    bl      {SMS_GET_VSYNC:#x}
    lis     r12, 0x8041
    lfs     f0, 0x67B8(r12)
    fadds   f0, f0, f0
    fdivs   f1, f1, f0
    lwz     r0, 0x14(r1)
    addi    r1, r1, 0x10
    mtlr    r0
    blr
"""

CAVES = [(FADER_DUR, SRC_DUR), (FADER_DELAY, SRC_DELAY), (FADER_INIT, SRC_INIT)]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def build() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    ends = []
    for addr, src in CAVES:
        code = assemble(src, addr)
        ends.append((addr, addr + len(code)))
        out += words(addr, code)
    ends.sort()
    for (_, e), (s, _) in zip(ends, ends[1:]):
        assert e <= s, "caves qui se chevauchent"
    for site, _orig, target in SITES:
        out.append((site, _bl(site, target)))
    return out


if __name__ == "__main__":
    import capstone
    from dol import Dol

    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    root = Path(__file__).resolve().parents[2]
    dol = Dol(root / "work" / "dol" / "GMSE01.dol")

    def dis(addr: int, word: int) -> str:
        ins = list(cs.disasm(word.to_bytes(4, "big"), addr))
        return f"{ins[0].mnemonic} {ins[0].op_str}" if ins else f".long {word:#010x}"

    pairs = build()
    site_addrs = {s for s, _, _ in SITES}
    print("== Caves ==")
    for addr, word in pairs:
        if addr in site_addrs:
            continue
        assert CAVE_START <= addr and addr + 3 <= CAVE_END, f"{addr:#x} hors plage"
        print(f"  {addr:08X}  {word:08X}  {dis(addr, word)}")
    print("== Sites ==")
    for addr, word in pairs:
        if addr not in site_addrs:
            continue
        orig = dol.u32(addr)
        expected = next(o for s, o, _ in SITES if s == addr)
        assert orig == expected, f"{addr:#x}: DOL {orig:#010x} != attendu {expected:#010x}"
        print(f"  {addr:08X}  {orig:08X} {dis(addr, orig):<28} -> {word:08X} {dis(addr, word)}")
    print(f"{len(pairs)} mots, caves dans [{CAVE_START:#x}, {CAVE_END:#x}]")
