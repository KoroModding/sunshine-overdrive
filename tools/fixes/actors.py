"""Actor / animation fixes — reasoned port of BetterSunshineEngine fps.cpp.

Code cave range: 0x80002400 – 0x800027FF.  M = 2 × f32@0x804167B8, read at run time
(1 at 30 FPS, 2 at 60, 4 at 120).

Perform flags recap (TMarDirector::direct, re-read in the DOL)
--------------------------------------------------------------
    802999C8  ori   r27, r27, 2        ; set if 0x4000 absent (not the last substep)
    802999FC  ori   r27, r27, 2 / 1    ; director states 5, 0xA–0xC (pause…)
    80299B0C  nor   r31, r27, r27      ; flags = ~r27
    80299B1C  rlwinm r4,r4,0,0x14,0x12 ; unk58 odd     -> 0x1000 cleared   (lists +0x28/+0x44)
    80299B28  rlwinm r4,r4,0,0x13,0x11 ; unk58 & 2     -> 0x2000 cleared
    80299BA4  rlwinm. r0,r27,0,30,30 / bne ; lists +0x2C/+0x48: last substep only
  => 0x1 = movement, present on EVERY substep (fixed 120 Hz);
     0x2 = present on the last substep ONLY, hence once per rendered frame (30·M Hz);
     0x1000/0x2000 = phases of unk58 (substep counter): 0x3001 == 0x0001 <=> unk58 ≡ 3 mod 4.
  TLiveActor::perform: flag 0x1 -> vt+0xD0 moveObject (80217EF8) -> vt+0xC8 control
  (802181D4) -> nerves; flag 0x2 -> MActor::frameUpdate(this+0x74) (80217F04..80217F34).
  So: a nerve runs once per substep; the main animation advances once per frame.

1. Flocks (TBoidLeader::calcBoids)                          [BSE + extension]
   800066E0 bl TVec3::dot ; 800066E4 bl TUtil<f>::sqrt ; 800066EC fmr f22,f1 ;
   80006720 fmr f1,f22 ; 80006754 bl TVec3::scale ; 80006770.. pos += vector.
   All of calcBoids is under the 0x2 test of TBoidLeader::perform (80005D1C rlwinm. r0,r4,0,30,30),
   so it runs per frame: the displacement quadruples at 120 FPS.
   Site 800066E4: bl sqrt -> bl BOID, which does f1 = dot / M² then "b sqrt" (tail call):
   sqrt(dot/M²) = sqrt(dot)/M, identical to BSE (sqrtf(dot)·30/fps).
   EXTENSION (not in BSE): the leader also moves in the same per-frame block —
   80005DFC lfs f2,0.9 ; 80005E08 fmuls f1,f2,(this+0x20) ; 80005E34.. pos += dir·f1.
   Site 80005DFC: lfs f2,-0x7fcc(r2) -> bl LEADER (f2 = 0.9/M). Without it, the leader runs 4×
   faster while BSE slows the boids down: they fall behind.
   Not covered: boid orientation smoothing (matan/MsWrap around 800065EC..8000664C)
   stays per frame, so boids turn faster (visual effect only). NOT VERIFIED.
   The Gecko hook in Sys/GMSE01.ini at 0x800066EC is unrelated and ignored.

2. Birds (TAnimalBird)                                    [BSE + 2 sites]
   8000CEB0 (doLanding+0x1A8)          lfs f31,0x194(param) ; bl SMSGetAnmFrameRate ; fmuls f30
   8000D1D8 (doFlyToCurPathNode+0x10C) fmuls f31,(0x174),(0xB8) ; bl ; fmuls f29,f31,f1
   8000D1F8 (doFlyToCurPathNode+0x12C) lfs f31,0xCC(param) ; bl ; fmuls f31,f31,f1
   These functions are only called by nerves (PreLanding, Comeback, GraphWander):
   vt+0xD0 of TAnimalBird = TAnimalBird::moveObject (8000D678) -> TLiveActor::moveObject
   (8000DA1C) -> vt+0xC8 control. Per-substep code: the multiplication by the animation
   rate (2 at 30 FPS) is a tuning constant, not a frame compensation.
   At 120 FPS it is 0.5: birds 4× too slow. Fix = return 2.0 (the 30 FPS value),
   independent of M — same choice as BSE.
   EXTENSION: same pattern, missed by BSE:
   8000CD50 (doLanding+0x48)  fmuls f31,(0x174),(0xB8) ; bl ; fmuls f31,f31,f1 — exact twin
            of 8000D1D8, initial landing speed;
   8000BEB0 (TNerveAnimalBirdWalkOnGround::execute+0x168) lfs f31,0x1A8(param) ; bl ;
            fmuls f3 ; fmadds f1,(0x170),f3,(this+0x34) ; stfs -> angle += … per substep.

3. Eel boss (TBossEel) — 19 sites                      [BSE, verified]
   Each site is exactly "bl SMSGetAnmFrameRate ; lfs f0,0.25 ; li r4,0 ;
   lwz r3,0x74(r31) ; fmuls f31,f0,f1 ; bl MActor::getFrameCtrl ; stfs f31,0xC(r3)"
   (frame ctrl 0 rate = 0.25 × anmRate, i.e. 0.5 at 30 FPS). The 1/4 = 1/substep factor
   betrays a per-substep advance, confirmed: TBossEel::perform only calls
   MActor::calcAnm (-> J3DFrameCtrl::update 802398BC) in the flag 0x1 branch
   (800D3710 clrlwi. r0,r30,31 ; 800D37C0 bl calcAnm), and never frameUpdate.
   Hence a constant rate of 0.5 at any M: the 19 bl -> bl CONST2.

4. TJointCoin / TSandBird (loadAfter)                        [BSE revised]
   801F76A8 bl anmRate ; ×0.25 ; 801F76C0 stfs -> frameCtrl(0) of this+0x74 ("character")
   801F76C4 bl anmRate ; ×0.25 ; 801F76DC stfs -> frameCtrl(0) of this+0x138 ("movement")
   TJointCoin::control (vt+0xC8, 801F79C4, hence per substep) does frameUpdate+calc
   on +0x138 (801F79DC) AND on +0x74 (801F7A2C). But TJointCoin::perform =
   TMapObjBase::perform, which ends with TLiveActor::perform (801AFF50): +0x74 also gets
   one frameUpdate per frame (flag 0x2; only 801AFE94 removes it, if the anim is finished).
     +0x138: 120 advances/s at any M        -> constant rate 0.5 (like BSE).
     +0x74 : 120 + 30·M advances/s          -> to keep 150 × 0.5 = 75 animation frames/s:
              rate = 75 / (120 + 30·M) = 2.5 / (4 + M)  (0.5 / 0.4167 / 0.3125).
   BSE hard-codes 2.0 / 1.667 / 1.333 × 0.25: its 30 and 60 values match the formula
   exactly, the 120 one (0.333) is 6.7 % too high — linear extrapolation.
   Sites: 801F76A8 -> bl JCCHAR (f1 = 10/(4+M) = 5/(2+lit), ×0.25 by the original code);
          801F76C4 -> bl CONST2.
   Caveat: rate frozen at load time (loadAfter) with the M of that moment; see dependencies.

5. Petey Piranha, vomit (TBossPakkun::changeBck)       [BSE revised]
   BSE hooks 800932BC (TNerveBPVomit: bl changeBck(0x15)) then forces anmRate × 0.8.
   Reading the DOL: changeBck first sets the rate to SMSGetAnmFrameRate (80095594/98,
   correct at any M since +0x74 advances per frame via TLiveActor::perform), THEN, for anim
   0x15 only (8009559C cmpwi r31,0x15), overwrites it with a raw parameter:
   800955C0 lfs f31,0x16C(param) ; 800955C8 bl getFrameCtrl ; 800955CC stfs f31,0xC(r3).
   This raw rate is not rescaled -> vomit 4× too fast at 120 FPS.
   Principled fix: 800955CC -> bl PETEY, which stores param / M. Identical at 30 FPS
   whatever the parameter, covers all callers of changeBck(0x15).
   Disagreement with BSE: 0.8 × anmRate = 1.6/M assumes param = 1.6 (.prm value NOT VERIFIED);
   otherwise BSE also changes the game at 30 FPS.

6. TFireWanwanTailNode::perform — BSE filter NOT ENABLED    [disagreement]
   BSE moves stwu/stmw up (8008D0E8..8008D118) to free 8008D11C and call a filter there that
   replaces the "flag 0x2" test (8008D0E8 rlwinm. r0,r4,0,30,30 ; 8008D120 beq) with
   (flags & 0x3001) == 0x0001, i.e. one substep in four (fixed 30 Hz).
   But the guarded block (8008D124..8008D284) only orients each node's matrix from
   positions computed by performNodes (8008C044, reading a history filled by movementBody
   under flag 0x1) then J3DModel::calc (vt+0x10 = 802DEBC4): no time integration,
   nothing that depends on the frame rate. Decimating it to 30 Hz would leave
   the tail frozen 3 frames out of 4 at 120 FPS. The code is provided (firewanwan_bse()) for an
   A/B test, but ENABLE_FIREWANWAN_BSE = False. Symptom BSE targets: NOT VERIFIED.

Dependencies and NOT VERIFIED points
------------------------------------
- No state dependency on any other group; only the 0x804167B8 literal is read.
- JointCoin (4) and Petey (5) freeze a rate at call time: if another group
  forces M = 1 while the level loads (loadAfter), TJointCoin's "character" rate
  will be the 30 FPS one in game. The same holds for every original setFrameRate
  done at load time: the "contexts" group must restore M to its in-game value
  before actors are constructed.
- Call chains established by static reading (vtables + disassembly), not measured.
- Other SMSGetAnmFrameRate calls not examined: FireWanwan nerves, TBossEelTooth,
  TBEelTears, 800C89FC/800C8A40/800CA52C/800CDB14/800DC4C0.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_caves import assemble, words  # noqa: E402

CAVE_START = 0x80002400
CAVE_END = 0x80002800            # exclusive

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

# f1 = 2.0: the 30 FPS animation rate, for code executed per substep.
SRC_CONST2 = """
    lis   r12, 0x8000
    lfs   f1, 0x2400(r12)
    blr
"""

# f1 = 10 / (4 + M) = 5 / (2 + lit); the site then multiplies by 0.25.
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

# f1 = dot; returns sqrt(dot / M²) via a tail call to TUtil<f>::sqrt.
SRC_BOID = f"""
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fmuls f0, f0, f0
    fdivs f1, f1, f0
    b     {SQRT:#x}
"""

# Replaces "lfs f2, -0x7fcc(r2)" (0.9): f2 = 0.9 / M. f0 is reloaded right after.
SRC_LEADER = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    lfs   f2, -0x7fcc(r2)
    fdivs f2, f2, f0
    blr
"""

# Replaces "stfs f31, 0xC(r3)": stores param / M.
SRC_PETEY = """
    lis   r12, 0x8041
    lfs   f0, 0x67B8(r12)
    fadds f0, f0, f0
    fdivs f0, f31, f0
    stfs  f0, 0xc(r3)
    blr
"""

# BSE filter (disabled): cr0.eq <=> (flags & 0x3001) != 0x0001.
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
BIRD_SITES_EXTRA = [0x8000CD50, 0x8000BEB0]                # same pattern, missing from BSE
EEL_SITES = [
    0x800D059C, 0x800D07A0, 0x800D0898, 0x800D0B60, 0x800D0E0C, 0x800D1128, 0x800D12F0,
    0x800D147C, 0x800D15C0, 0x800D1C98, 0x800D1D68, 0x800D207C, 0x800D2364, 0x800D2438,
    0x800D24F8, 0x800D2710, 0x800D2AD8, 0x800D2F8C, 0x800D3350,
]

# (site, expected original word in the DOL, bl target)
SITES: list[tuple[int, int, int]] = (
    [(s, _bl(s, ANM_RATE), CONST2) for s in BIRD_SITES + BIRD_SITES_EXTRA + EEL_SITES]
    + [
        (0x801F76A8, _bl(0x801F76A8, ANM_RATE), JCCHAR),   # TJointCoin +0x74  (character)
        (0x801F76C4, _bl(0x801F76C4, ANM_RATE), CONST2),   # TJointCoin +0x138 (movement)
        (0x800066E4, _bl(0x800066E4, SQRT), BOID),         # boids: bl sqrt
        (0x80005DFC, 0xC0428034, LEADER),                  # leader: lfs f2,-0x7fcc(r2)
        (0x800955CC, 0xD3E3000C, PETEY),                   # changeBck(0x15): stfs f31,0xC(r3)
    ]
)

ENABLE_FIREWANWAN_BSE = False

# BSE's SMS_WRITE_32, copied verbatim: (site, expected DOL word, new word)
WAN_WRITES = [
    (0x8008D0E8, 0x548007BD, 0x9421FEE0),   # rlwinm. r0,r4,0,30,30 -> stwu r1,-0x120(r1)
    (0x8008D0EC, 0x9421FEE0, 0xBF6100DC),   # stwu                  -> stmw r27,0xdc(r1)
    (0x8008D108, 0xBF6100DC, 0x3BE40000),   # stmw                  -> addi r31,r4,0
    (0x8008D10C, 0x3BE40000, 0x3B630000),   # addi r31,r4           -> addi r27,r3,0
    (0x8008D110, 0x3B630000, 0x3B850000),   # addi r27,r3           -> addi r28,r5,0
    (0x8008D114, 0x3B850000, 0x3BA60000),   # addi r28,r5           -> addi r29,r6,0
    (0x8008D118, 0x3BA60000, 0x3BC70000),   # addi r29,r6           -> addi r30,r7,0
]
WAN_CALL = 0x8008D11C                        # addi r30,r7,0 -> bl WANFILTER (beq follows)


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
