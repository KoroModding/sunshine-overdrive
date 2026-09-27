"""Correctifs « acteurs / animations » — portage raisonné de BetterSunshineEngine fps.cpp.

Plage de caverne : 0x80002400 – 0x800027FF.  M = 2 × f32@0x804167B8, lu à l'exécution
(1 à 30 FPS, 2 à 60, 4 à 120).

Rappel des drapeaux de perform (TMarDirector::direct, relus dans le DOL)
------------------------------------------------------------------------
    802999C8  ori   r27, r27, 2        ; posé si 0x4000 absent (pas le dernier sous-pas)
    802999FC  ori   r27, r27, 2 / 1    ; états 5, 0xA–0xC du directeur (pause…)
    80299B0C  nor   r31, r27, r27      ; flags = ~r27
    80299B1C  rlwinm r4,r4,0,0x14,0x12 ; unk58 impair  -> 0x1000 retiré   (listes +0x28/+0x44)
    80299B28  rlwinm r4,r4,0,0x13,0x11 ; unk58 & 2     -> 0x2000 retiré
    80299BA4  rlwinm. r0,r27,0,30,30 / bne ; listes +0x2C/+0x48 : dernier sous-pas seulement
  => 0x1 = mouvement, présent à CHAQUE sous-pas (120 Hz fixes) ;
     0x2 = présent au SEUL dernier sous-pas, donc une fois par image rendue (30·M Hz) ;
     0x1000/0x2000 = phases de unk58 (compteur de sous-pas) : 0x3001 == 0x0001 <=> unk58 ≡ 3 mod 4.
  TLiveActor::perform : flag 0x1 -> vt+0xD0 moveObject (80217EF8) -> vt+0xC8 control
  (802181D4) -> nerfs ; flag 0x2 -> MActor::frameUpdate(this+0x74) (80217F04..80217F34).
  Donc : un nerf est exécuté par sous-pas ; l'animation principale avance par image.

1. Nuées (TBoidLeader::calcBoids)                          [BSE + extension]
   800066E0 bl TVec3::dot ; 800066E4 bl TUtil<f>::sqrt ; 800066EC fmr f22,f1 ;
   80006720 fmr f1,f22 ; 80006754 bl TVec3::scale ; 80006770.. pos += vecteur.
   Tout calcBoids est sous le test 0x2 de TBoidLeader::perform (80005D1C rlwinm. r0,r4,0,30,30),
   donc par image : le déplacement quadruple à 120 FPS.
   Site 800066E4 : bl sqrt -> bl BOID, qui fait f1 = dot / M² puis « b sqrt » (appel terminal) :
   sqrt(dot/M²) = sqrt(dot)/M, identique à BSE (sqrtf(dot)·30/fps).
   EXTENSION (absente de BSE) : le meneur avance aussi dans le même bloc par image —
   80005DFC lfs f2,0.9 ; 80005E08 fmuls f1,f2,(this+0x20) ; 80005E34.. pos += dir·f1.
   Site 80005DFC : lfs f2,-0x7fcc(r2) -> bl LEADER (f2 = 0.9/M). Sans cela, le meneur file 4×
   plus vite tandis que BSE ralentit les boids : ils décrochent.
   Non couvert : le lissage d'orientation des boids (matan/MsWrap vers 800065EC..8000664C)
   reste par image, donc les boids tournent plus vite (effet visuel seulement). NON VÉRIFIÉ.
   Le hook Gecko de Sys/GMSE01.ini à 0x800066EC est sans rapport et ignoré.

2. Oiseaux (TAnimalBird)                                    [BSE + 2 sites]
   8000CEB0 (doLanding+0x1A8)          lfs f31,0x194(param) ; bl SMSGetAnmFrameRate ; fmuls f30
   8000D1D8 (doFlyToCurPathNode+0x10C) fmuls f31,(0x174),(0xB8) ; bl ; fmuls f29,f31,f1
   8000D1F8 (doFlyToCurPathNode+0x12C) lfs f31,0xCC(param) ; bl ; fmuls f31,f31,f1
   Ces fonctions ne sont appelées que par des nerfs (PreLanding, Comeback, GraphWander) :
   vt+0xD0 de TAnimalBird = TAnimalBird::moveObject (8000D678) -> TLiveActor::moveObject
   (8000DA1C) -> vt+0xC8 control. Code par sous-pas : la multiplication par le débit
   d'animation (2 à 30 FPS) est une constante de réglage, pas une compensation d'image.
   À 120 FPS elle vaut 0,5 : oiseaux 4× trop lents. Correctif = renvoyer 2.0 (valeur 30 FPS),
   indépendamment de M — même choix que BSE.
   EXTENSION : même motif, oublié par BSE :
   8000CD50 (doLanding+0x48)  fmuls f31,(0x174),(0xB8) ; bl ; fmuls f31,f31,f1 — jumeau exact
            de 8000D1D8, vitesse initiale d'atterrissage ;
   8000BEB0 (TNerveAnimalBirdWalkOnGround::execute+0x168) lfs f31,0x1A8(param) ; bl ;
            fmuls f3 ; fmadds f1,(0x170),f3,(this+0x34) ; stfs -> angle += … par sous-pas.

3. Boss anguille (TBossEel) — 19 sites                      [BSE, vérifié]
   Chaque site est exactement « bl SMSGetAnmFrameRate ; lfs f0,0.25 ; li r4,0 ;
   lwz r3,0x74(r31) ; fmuls f31,f0,f1 ; bl MActor::getFrameCtrl ; stfs f31,0xC(r3) »
   (débit du frame ctrl 0 = 0.25 × anmRate, soit 0,5 à 30 FPS). Le facteur 1/4 = 1/sous-pas
   trahit une avance par sous-pas, confirmée : TBossEel::perform n'appelle
   MActor::calcAnm (-> J3DFrameCtrl::update 802398BC) que dans la branche flag 0x1
   (800D3710 clrlwi. r0,r30,31 ; 800D37C0 bl calcAnm), et jamais frameUpdate.
   Donc débit constant 0,5 à tout M : les 19 bl -> bl CONST2.

4. TJointCoin / TSandBird (loadAfter)                        [BSE revu]
   801F76A8 bl anmRate ; ×0.25 ; 801F76C0 stfs -> frameCtrl(0) de this+0x74 (« character »)
   801F76C4 bl anmRate ; ×0.25 ; 801F76DC stfs -> frameCtrl(0) de this+0x138 (« movement »)
   TJointCoin::control (vt+0xC8, 801F79C4, donc par sous-pas) fait frameUpdate+calc
   sur +0x138 (801F79DC) ET sur +0x74 (801F7A2C). Or TJointCoin::perform =
   TMapObjBase::perform, qui finit par TLiveActor::perform (801AFF50) : +0x74 reçoit en plus
   un frameUpdate par image (flag 0x2 ; seul 801AFE94 le retire, si l'anim est finie).
     +0x138 : 120 avances/s à tout M        -> débit constant 0,5 (comme BSE).
     +0x74  : 120 + 30·M avances/s          -> pour garder 150 × 0,5 = 75 images d'anim/s :
              débit = 75 / (120 + 30·M) = 2,5 / (4 + M)  (0,5 / 0,4167 / 0,3125).
   BSE code en dur 2.0 / 1.667 / 1.333 × 0,25 : ses valeurs 30 et 60 coïncident exactement
   avec la formule, celle de 120 (0,333) est 6,7 % trop haute — extrapolation linéaire.
   Sites : 801F76A8 -> bl JCCHAR (f1 = 10/(4+M) = 5/(2+lit), ×0,25 par le code d'origine) ;
           801F76C4 -> bl CONST2.
   Réserve : débit figé au chargement (loadAfter) avec le M du moment ; voir dépendances.

5. Petey Piranha, vomissement (TBossPakkun::changeBck)       [BSE revu]
   BSE hooke 800932BC (TNerveBPVomit : bl changeBck(0x15)) puis force anmRate × 0,8.
   Lecture du DOL : changeBck règle d'abord le débit à SMSGetAnmFrameRate (80095594/98,
   correct à tout M car +0x74 avance par image via TLiveActor::perform), PUIS, pour l'anim
   0x15 seulement (8009559C cmpwi r31,0x15), l'écrase par un paramètre brut :
   800955C0 lfs f31,0x16C(param) ; 800955C8 bl getFrameCtrl ; 800955CC stfs f31,0xC(r3).
   Ce débit brut n'est pas remis à l'échelle -> vomissement 4× trop rapide à 120 FPS.
   Correctif principiel : 800955CC -> bl PETEY, qui stocke param / M. Identique à 30 FPS
   quel que soit le paramètre, couvre tous les appelants de changeBck(0x15).
   Désaccord BSE : 0,8 × anmRate = 1,6/M suppose param = 1,6 (valeur .prm NON VÉRIFIÉE) ;
   sinon BSE modifie aussi le jeu à 30 FPS.

6. TFireWanwanTailNode::perform — filtre BSE NON ACTIVÉ    [désaccord]
   BSE remonte stwu/stmw (8008D0E8..8008D118) pour libérer 8008D11C et y appeler un filtre
   remplaçant le test « flag 0x2 » (8008D0E8 rlwinm. r0,r4,0,30,30 ; 8008D120 beq) par
   (flags & 0x3001) == 0x0001, soit un sous-pas sur quatre (30 Hz fixes).
   Or le bloc protégé (8008D124..8008D284) ne fait qu'orienter la matrice de chaque nœud à
   partir de positions calculées par performNodes (8008C044, lecture d'un historique rempli
   par movementBody sous flag 0x1) puis J3DModel::calc (vt+0x10 = 802DEBC4) : aucune
   intégration dans le temps, rien qui dépende de la cadence. Le décimer à 30 Hz laisserait
   la queue figée 3 images sur 4 à 120 FPS. Le code est fourni (firewanwan_bse()) pour un
   test A/B, mais ENABLE_FIREWANWAN_BSE = False. Symptôme visé par BSE : NON VÉRIFIÉ.

Dépendances et points NON VÉRIFIÉS
----------------------------------
- Aucune dépendance d'état envers un autre groupe ; seul le littéral 0x804167B8 est lu.
- JointCoin (4) et Petey (5) figent un débit au moment de l'appel : si un autre groupe
  force M = 1 pendant le chargement du niveau (loadAfter), le débit « character » de
  TJointCoin sera celui de 30 FPS en jeu. C'est vrai aussi de tous les setFrameRate
  d'origine faits au chargement : le groupe « contextes » doit rendre M à sa valeur de
  jeu avant la construction des acteurs.
- Chaînes d'appel établies par lecture statique (vtables + désassemblage), pas mesurées.
- Autres appels SMSGetAnmFrameRate non examinés : nerfs FireWanwan, TBossEelTooth,
  TBEelTears, 800C89FC/800C8A40/800CA52C/800CDB14/800DC4C0.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002400
CAVE_END = 0x80002800            # exclusif

ANM_RATE = 0x802A7BD8            # SMSGetAnmFrameRate__Fv
SQRT = 0x800067E8                # JGeometry::TUtil<f>::sqrt(float)

K_2 = 0x80002400                 # f32 2.0
K_5 = 0x80002404                 # f32 5.0
CONST2 = 0x80002410
JCCHAR = 0x80002420
BOID = 0x80002440
LEADER = 0x80002460
PETEY = 0x80002480
WANFILTER = 0x800024A0

# f1 = 2.0 : débit d'animation de 30 FPS, pour du code exécuté par sous-pas.
SRC_CONST2 = """
    lis   r12, 0x8000
    lfs   f1, 0x2400(r12)
    blr
"""

# f1 = 10 / (4 + M) = 5 / (2 + lit) ; le site multiplie ensuite par 0,25.
SRC_JCCHAR = """
    lis   r12, 0x8000
    lfs   f0, 0x2400(r12)
    lfs   f1, 0x2404(r12)
    lis   r12, 0x8041
    lfs   f12, 0x67B8(r12)
    fadds f12, f12, f0
    fdivs f1, f1, f12
    blr
"""

# f1 = dot ; renvoie sqrt(dot / M²) par appel terminal à TUtil<f>::sqrt.
SRC_BOID = f"""
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fmuls f0, f0, f0
    fdivs f1, f1, f0
    b     {SQRT:#x}
"""

# Remplace « lfs f2, -0x7fcc(r2) » (0.9) : f2 = 0.9 / M. f0 est rechargé juste après.
SRC_LEADER = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    lfs   f2, -0x7fcc(r2)
    fdivs f2, f2, f0
    blr
"""

# Remplace « stfs f31, 0xC(r3) » : stocke param / M.
SRC_PETEY = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fdivs f0, f31, f0
    stfs  f0, 0xc(r3)
    blr
"""

# Filtre BSE (désactivé) : cr0.eq <=> (flags & 0x3001) != 0x0001.
SRC_WANFILTER = """
    andi. r4, r4, 0x3001
    xori  r4, r4, 1
    cntlzw r4, r4
    srwi  r4, r4, 5
    cmpwi r4, 0
    blr
"""

CAVES = [
    (CONST2, SRC_CONST2), (JCCHAR, SRC_JCCHAR), (BOID, SRC_BOID),
    (LEADER, SRC_LEADER), (PETEY, SRC_PETEY),
]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


BIRD_SITES = [0x8000CEB0, 0x8000D1D8, 0x8000D1F8]          # BSE
BIRD_SITES_EXTRA = [0x8000CD50, 0x8000BEB0]                # même motif, absents de BSE
EEL_SITES = [
    0x800D059C, 0x800D07A0, 0x800D0898, 0x800D0B60, 0x800D0E0C, 0x800D1128, 0x800D12F0,
    0x800D147C, 0x800D15C0, 0x800D1C98, 0x800D1D68, 0x800D207C, 0x800D2364, 0x800D2438,
    0x800D24F8, 0x800D2710, 0x800D2AD8, 0x800D2F8C, 0x800D3350,
]

# (site, mot d'origine attendu dans le DOL, cible du bl)
SITES: list[tuple[int, int, int]] = (
    [(s, _bl(s, ANM_RATE), CONST2) for s in BIRD_SITES + BIRD_SITES_EXTRA + EEL_SITES]
    + [
        (0x801F76A8, _bl(0x801F76A8, ANM_RATE), JCCHAR),   # TJointCoin +0x74  (character)
        (0x801F76C4, _bl(0x801F76C4, ANM_RATE), CONST2),   # TJointCoin +0x138 (movement)
        (0x800066E4, _bl(0x800066E4, SQRT), BOID),         # boids : bl sqrt
        (0x80005DFC, 0xC0428034, LEADER),                  # meneur : lfs f2,-0x7fcc(r2)
        (0x800955CC, 0xD3E3000C, PETEY),                   # changeBck(0x15) : stfs f31,0xC(r3)
    ]
)

ENABLE_FIREWANWAN_BSE = False

# SMS_WRITE_32 de BSE, recopiés tels quels : (site, attendu DOL, nouveau)
WAN_WRITES = [
    (0x8008D0E8, 0x548007BD, 0x9421FEE0),   # rlwinm. r0,r4,0,30,30 -> stwu r1,-0x120(r1)
    (0x8008D0EC, 0x9421FEE0, 0xBF6100DC),   # stwu                  -> stmw r27,0xdc(r1)
    (0x8008D108, 0xBF6100DC, 0x3BE40000),   # stmw                  -> addi r31,r4,0
    (0x8008D10C, 0x3BE40000, 0x3B630000),   # addi r31,r4           -> addi r27,r3,0
    (0x8008D110, 0x3B630000, 0x3B850000),   # addi r27,r3           -> addi r28,r5,0
    (0x8008D114, 0x3B850000, 0x3BA60000),   # addi r28,r5           -> addi r29,r6,0
    (0x8008D118, 0x3BA60000, 0x3BC70000),   # addi r29,r6           -> addi r30,r7,0
]
WAN_CALL = 0x8008D11C                        # addi r30,r7,0 -> bl WANFILTER (beq suit)


def firewanwan_bse() -> list[tuple[int, int]]:
    out = words(WANFILTER, assemble(SRC_WANFILTER, WANFILTER))
    out += [(a, new) for a, _, new in WAN_WRITES]
    out.append((WAN_CALL, _bl(WAN_CALL, WANFILTER)))
    return out


def build() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = [(K_2, _f32(2.0)), (K_5, _f32(5.0))]
    spans = [(K_2, K_5 + 4)]
    for addr, src in CAVES:
        code = assemble(src, addr)
        spans.append((addr, addr + len(code)))
        out += words(addr, code)
    spans.sort()
    for (_, e), (s, _) in zip(spans, spans[1:]):
        assert e <= s, "caves qui se chevauchent"
    assert spans[-1][1] <= WANFILTER, "routines débordent sur le filtre FireWanwan"
    for site, _orig, target in SITES:
        out.append((site, _bl(site, target)))
    if ENABLE_FIREWANWAN_BSE:
        out += firewanwan_bse()
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

    def in_cave(a: int) -> bool:
        return CAVE_START <= a and a + 4 <= CAVE_END

    pairs = build()
    wan = firewanwan_bse()
    expected = {s: o for s, o, _ in SITES}
    expected.update({a: o for a, o, _ in WAN_WRITES})
    expected[WAN_CALL] = 0x3BC70000

    for title, lst in (("actif", pairs), ("FireWanwan BSE (désactivé)", wan)):
        print(f"== Caves — {title} ==")
        for addr, word in lst:
            if in_cave(addr):
                print(f"  {addr:08X}  {word:08X}  {dis(addr, word)}")
        print(f"== Sites — {title} ==")
        for addr, word in lst:
            if in_cave(addr):
                continue
            orig = dol.u32(addr)
            assert orig == expected[addr], f"{addr:#x}: DOL {orig:#010x} != attendu {expected[addr]:#010x}"
            print(f"  {addr:08X}  {orig:08X} {dis(addr, orig):<30} -> {word:08X} {dis(addr, word)}")

    addrs = [a for a, _ in pairs] + [a for a, _ in wan]
    assert len(set(a for a, _ in pairs)) == len(pairs), "adresse patchée deux fois"
    for a in addrs:
        assert in_cave(a) or a in expected, f"{a:#x} ni en caverne ni site connu"
    print(f"{len(pairs)} mots actifs ({len(SITES)} sites), "
          f"+{len(wan)} mots FireWanwan désactivés ; caves dans [{CAVE_START:#x}, {CAVE_END:#x})")
