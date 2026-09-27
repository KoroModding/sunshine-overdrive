"""Effets sonores : vitesse des sons d'animation, et journal de diagnostic.

1. Vitesse transmise aux sons d'animation — MAnmSound::animeLoop, 0x80012E9C
   Tous les acteurs (TLiveActor::updateAnmSound, TMario::animSound, TYoshi,
   TKoopa, TEnemyManager…) passent à MAnmSound::animeLoop la vitesse
   d'animation du contrôleur de trame (J3DFrameCtrl+0xC, mFrameRate), qui
   vaut ~SMSGetAnmFrameRate() : 2.0 à 30 FPS, 0.5 à 120 FPS. JAIAnimeSound
   s'en sert pour moduler la hauteur et le volume de chaque son d'animation :
       hauteur = base + unk15 × (vitesse − 1) / 32
       volume  = base + 2 × unk18 × (vitesse − 1)
   (Graffito-Decomp, JAIAnimation.cpp : setSpeedModifySound, playActorAnimSound).
   À 120 FPS, tous les sons d'animation à modulation sortaient donc plus
   graves et moins forts. La routine multiplie la vitesse par M avant
   l'appel : la vitesse retrouve sa valeur à 30 FPS. Effet secondaire : la
   fenêtre d'anticipation au rebouclage d'animation (mCurrentTime + vitesse)
   redevient celle du jeu d'origine en trames d'animation, soit 4 appels au
   lieu d'un à 120 FPS — un son de début de boucle peut partir ≤ 1,5 trame
   d'animation (~25 ms) plus tôt. NON VÉRIFIÉ à l'oreille.

2. Journal des démarrages de sons — DIAGNOSTIC, JAIBasic::startSoundBasic
   Point d'entrée unique : startSoundActor, startSoundDirectID,
   startSoundIndirectID et startSoundActorReturnHandle y aboutissent tous.
   L'entrée (mflr r0) est détournée vers une routine qui écrit (id du son,
   compteur de passages JAI JAIBasic+0x20) dans un anneau de 64 entrées :
       0x80002C00  u32  index suivant (état)
       0x80002C08  64 × (u32 id, u32 trame)
   Lu par tools/watch_se_rates.py. Aucun état n'est écrit par le profil.

Zone : 0x80002A00 – 0x80002AFF (code) ; anneau 0x80002C00 – 0x80002E07.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_ANM = 0x80002A00
CAVE_LOG = 0x80002A40
RING = 0x80002C00
RING_ENTRIES = 64

MARIO_RETURN = 0x80285824      # retour de bl animeLoop dans TMario::animSound
SPEED_PROBE = 0x80002A30       # f32, dernière vitesse transmise (état, diagnostic)
SITE_ANM = 0x80012E9C          # bl JAIAnimeSound::setAnimSoundVec
SET_ANIM_SOUND_VEC = 0x80300164
SITE_LOG = 0x803020AC          # mflr r0, entrée de startSoundBasic

ORIGINAL = {SITE_ANM: 0x482ED2C9, SITE_LOG: 0x7C0802A6}

# Entrée : arguments de setAnimSoundVec (f1 = trame, f2 = vitesse). Saut
# terminal : LR pointe toujours dans animeLoop. Touchés : r11, r12, f0, cr0.
# Adresse de retour de l'appelant d'animeLoop : 0xC(r1) (animeLoop a sauvé LR
# en 4(r1 d'entrée) puis fait stwu r1, -8(r1)).
ASM_ANM = f"""
    lwz    r12, 0xC(r1)
    lis    r11, {MARIO_RETURN >> 16:#x}
    ori    r11, r11, {MARIO_RETURN & 0xFFFF:#x}
    cmplw  r12, r11
    beq    probe
    lis    r12, 0x8041
    lfs    f0, 0x67B8(r12)
    fadds  f0, f0, f0
    fmuls  f2, f2, f0
probe:
    lis    r12, 0x8000
    stfs   f2, {SPEED_PROBE & 0xFFFF:#x}(r12)
    b      {SET_ANIM_SOUND_VEC:#x}
"""

# Entrée de startSoundBasic : r3 = JAIBasic*, r4 = id ; r3–r10 préservés.
# Touchés : r0 (réécrit par mflr avant de reprendre), r11, r12, cr0.
ASM_LOG = f"""
    lis    r12, 0x8000
    lwz    r11, 0x2C00(r12)
    addi   r0, r11, 1
    andi.  r0, r0, {RING_ENTRIES - 1}
    stw    r0, 0x2C00(r12)
    rlwinm r11, r11, 3, 0, 28
    add    r11, r11, r12
    stw    r4, 0x2C08(r11)
    lwz    r0, 0x20(r3)
    stw    r0, 0x2C0C(r11)
    mflr   r0
    b      {SITE_LOG + 4:#x}
"""


def build(with_log: bool = False) -> list[tuple[int, int]]:
    anm = assemble(ASM_ANM, CAVE_ANM)
    log = assemble(ASM_LOG, CAVE_LOG)
    assert CAVE_ANM + len(anm) <= SPEED_PROBE, len(anm) and CAVE_LOG + len(log) <= 0x80002B00
    patches = words(CAVE_ANM, anm)
    if with_log:
        patches += words(CAVE_LOG, log)
    patches += words(SITE_ANM, assemble(f"bl {CAVE_ANM:#x}", SITE_ANM))
    if with_log:
        patches += words(SITE_LOG, assemble(f"b {CAVE_LOG:#x}", SITE_LOG))
    return patches


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for a, v in ORIGINAL.items():
        assert dol.u32(a) == v, f"{a:08X} : {dol.u32(a):08X} != {v:08X}"
    print(listing(CAVE_ANM, assemble(ASM_ANM, CAVE_ANM)))
    print(listing(CAVE_LOG, assemble(ASM_LOG, CAVE_LOG)))
    for a, v in build():
        if a in ORIGINAL:
            print(f"  {a:08X}  {ORIGINAL[a]:08X} -> {v:08X}")
    print(len(build()), "mots")
