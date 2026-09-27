"""Bosses and scenery: fixes from the 2026-09-27 audit (docs/00-journal.md).

Every site was re-read in the US DOL before writing (original instruction
checked by `python tools/fixes/bosses.py`). M = 2 × literal 0x804167B8, read at
run time, except where marked "M = 4 fixed" (hard-coded value, 120 profile
only, like doppler.py).

Groups (enabled individually via GROUPS)
========================================
shadow   Shadow Mario, signature pose (TEnemyMario +0x42F0). The animation
         advances PER SUBSTEP (0x8003FAB4 bl MActor::calcAnm, under flag 0x1) at
         a rate of SMSGetAnmFrameRate (0x800427CC, also the default rate of the
         setBck of state 0x12): 4× too slow, and the state only ends with the
         animation. Fix: 0x8003FAB4 → bl SHADOW, which resets frame ctrl 0's
         rate to 2.0 **only if it is exactly SMSGetAnmFrameRate()**
         (rate × literal == 1), then jumps to calcAnm. A zero rate or one set
         otherwise is left alone; at 30 FPS this is a no-op.
koopajr  Bowser Jr's submarine: TKoopaJrSubmarine::moveSwing (0x801190F8),
         called once per FRAME (0x801195BC, block of flag 0x2 tested at
         0x801194B4). Six per-frame increments divided by M: decay 0x190
         (0x80119174), phase +0x180 (0x801191E0), rise 0x198 ×2 (0x8011928C,
         0x801192DC), decay 0x198 (0x80119320), phase +0x130 (0x8011938C).
         The spray impulse (0x80119130, one per message) is left alone: message
         frequency not measured.
grip     Bathtub pedestals (TBathtubGrip): collapse animation advanced per
         substep (calcAnm in control) AND per frame (TLiveActor::perform).
         0x801FBBC4 bl SMSGetAnmFrameRate → bl JCCHAR (actors.py):
         f1 = 10/(4+M) → same animation frames per second as at 30 FPS
         (5 advances/frame × 2.0 = 2 advances/frame × 1.25 × 4).
         MEDIUM confidence: the per-frame advance is inferred, not measured; if
         it does not happen, 2.0 (CONST2) would be needed.
wiggler  Wiggler: raw floor of the walk rate (0x800F2680 fmr f31, f0;
         f0 = mSLWalkBckRateMin, per-frame anim) → bl WIGGLER: f31 = f0 / M.
petey    Petey's head (calcHeadDir, per frame): sMaxRotationStep /
         sMinRotationStep 0x8040C2F0 / 0x8040C2F4: ±1.0 → ±0.25 (M = 4 fixed;
         only readers: calcHeadDir+0x2D0/+0x2E8, xref checked).
eeleye   Eel's eyes: fade −0.01 per frame (0x800D6414 lfs f1) →
         bl EELEYE: f1 = 0.01 / M.
gooper   Gooper Blooper: particle trail after eye damage, 5 frames
         (0x800750D0 li r0, 5) → li r0, 20 (M = 4 fixed).
mecha    Mecha-Bowser, flame scale ±0.05 per frame (0x800A1510 and
         0x800A1538 lfs f0) → bl FLAME: f0 = 0.05 / M.
bbill    Bathtub Bullet Bills: blink +0x1F8 per frame
         (0x80132328 lfs f0, 0x1F8(r30)) → bl BBILL: f0 = increment / M.
         The smoke (interval 0x1D4) is not fixed.
pinna    Pinna Park scenery, per-substep code × SMSGetAnmFrameRate × 0.25
         (same pattern as the birds): Ferris wheel (0x801D6998, 0x801D69C8,
         initMapObj 0x801D690C) and roller-coaster rail (0x801D4114) →
         bl CONST2 (2.0). The cart (double update, inferred) is not fixed.

Left out for lack of measurement: King Boo (genAttacker), fire Chomp (carrier
block), manta (blendWave, one site not located; shadow), Gooper Blooper G1,
Wiggler (tumble transition).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402
import birds  # noqa: E402

CALC_ANM = 0x80239878
ANM_RATE = 0x802A7BD8
CONST2 = birds.CONST2            # 0x80002410, f1 = 2.0
K_2 = birds.K_2                  # 0x80002400
K_5 = 0x80002404                 # 5.0, actors.py
JCCHAR = 0x80002420              # actors.py: f1 = 5 / (2 + lit) = 10 / (4 + M)

CAVE = 0x800024C0
CAVE_END = 0x80002800
K_1 = 0x800024C0                 # 1.0
CODE = 0x800024D0

GROUPS = ["shadow", "koopajr", "grip", "wiggler", "petey", "eeleye", "gooper",
          "mecha", "bbill", "pinna"]

LOAD_M = """
    lis   r12, 0x8041
    lfs   f12, 0x67B8(r12)
    fadds f12, f12, f12
"""

# (name, source), assembled back to back from CODE.
ROUTINES: list[tuple[str, str]] = [
    ("SHADOW", f"""
    lwz    r12, 0x28(r3)
    cmplwi r12, 0
    beq    go
    lwz    r12, 0(r12)
    cmplwi r12, 0
    beq    go
    lis    r11, 0x8041
    lfs    f0, 0x67B8(r11)
    lfs    f1, 0x10(r12)
    fmuls  f1, f1, f0
    lis    r11, 0x8000
    lfs    f0, {K_1 & 0xFFFF:#x}(r11)
    fcmpu  cr0, f1, f0
    bne    go
    lfs    f0, {K_2 & 0xFFFF:#x}(r11)
    stfs   f0, 0x10(r12)
go:
    b      {CALC_ANM:#x}
"""),
    ("KJ_SCALE", LOAD_M + """
    fdivs  f0, f0, f12
    blr
"""),
    ("KJ_A", "lfs f0, -0x5274(r2)\nb {KJ_SCALE}"),
    ("KJ_B", "lfs f0, 0x180(r3)\nb {KJ_SCALE}"),
    ("KJ_C", "lfs f0, -0x5270(r2)\nb {KJ_SCALE}"),
    ("KJ_D", "lfs f0, -0x526c(r2)\nb {KJ_SCALE}"),
    ("KJ_E", "lfs f0, 0x130(r3)\nb {KJ_SCALE}"),
    ("WIGGLER", LOAD_M + """
    fdivs  f31, f0, f12
    blr
"""),
    ("EELEYE", "lfs f1, -0x5de4(r2)\n" + LOAD_M + """
    fdivs  f1, f1, f12
    blr
"""),
    ("FLAME", "lfs f0, -0x6528(r2)\nb {KJ_SCALE}"),
    ("BBILL", "lfs f0, 0x1f8(r30)\nb {KJ_SCALE}"),
]

# (group, site, expected original word, target: routine name | address | ("mot", value))
SITES: list[tuple[str, int, int, object]] = [
    ("shadow", 0x8003FAB4, 0x481F9DC5, "SHADOW"),
    ("koopajr", 0x80119174, 0xC002AD8C, "KJ_A"),
    ("koopajr", 0x801191E0, 0xC0030180, "KJ_B"),
    ("koopajr", 0x8011928C, 0xC002AD90, "KJ_C"),
    ("koopajr", 0x801192DC, 0xC002AD90, "KJ_C"),
    ("koopajr", 0x80119320, 0xC002AD94, "KJ_D"),
    ("koopajr", 0x8011938C, 0xC0030130, "KJ_E"),
    ("grip", 0x801FBBC4, 0x480AC015, JCCHAR),
    ("wiggler", 0x800F2680, 0xFFE00090, "WIGGLER"),
    ("petey", 0x8040C2F0, 0x3F800000, ("mot", 0x3E800000)),
    ("petey", 0x8040C2F4, 0xBF800000, ("mot", 0xBE800000)),
    ("eeleye", 0x800D6414, 0xC022A21C, "EELEYE"),
    ("gooper", 0x800750D0, 0x38000005, ("mot", 0x38000014)),
    ("mecha", 0x800A1510, 0xC0029AD8, "FLAME"),
    ("mecha", 0x800A1538, 0xC0029AD8, "FLAME"),
    ("bbill", 0x80132328, 0xC01E01F8, "BBILL"),
    ("pinna", 0x801D6998, 0x480D1241, CONST2),
    ("pinna", 0x801D69C8, 0x480D1211, CONST2),
    ("pinna", 0x801D690C, 0x480D12CD, CONST2),
    ("pinna", 0x801D4114, 0x480D3AC5, CONST2),
]

# Reused verbatim from actors.py (same addresses, same words).
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


def _f32(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def _bl(src: int, dst: int) -> int:
    off = dst - src
    assert -0x2000000 <= off < 0x2000000 and off % 4 == 0
    return 0x48000001 | (off & 0x03FFFFFC)


def _routines() -> tuple[dict[str, int], list[tuple[int, int]]]:
    addrs: dict[str, int] = {}
    out: list[tuple[int, int]] = []
    a = CODE
    for name, src in ROUTINES:
        src = src.format(**{k: hex(v) for k, v in addrs.items()})
        code = assemble(src, a)
        addrs[name] = a
        out += words(a, code)
        a += len(code)
        a = (a + 0xF) & ~0xF
    assert a <= CAVE_END, f"caverne débordée : {a:#x}"
    return addrs, out


def build(groups: list[str] | None = None) -> list[tuple[int, int]]:
    groups = GROUPS if groups is None else groups
    addrs, code = _routines()
    out = list(code) + [(K_1, _f32(1.0))]
    out += birds.build()[:1] + [w for w in birds.build() if CONST2 <= w[0] < CONST2 + 0x10]
    out += [(K_5, _f32(5.0))] + words(JCCHAR, assemble(SRC_JCCHAR, JCCHAR))
    for grp, site, _orig, tgt in SITES:
        if grp not in groups:
            continue
        if isinstance(tgt, tuple):
            out.append((site, tgt[1]))
        else:
            dst = addrs[tgt] if isinstance(tgt, str) else tgt
            out.append((site, _bl(site, dst)))
    return out


if __name__ == "__main__":
    from dol import Dol
    import actors
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for grp, site, orig, _ in SITES:
        got = dol.u32(site)
        assert got == orig, f"{grp} {site:08X} : DOL {got:08X} != attendu {orig:08X}"
    ref = dict(actors.build())
    for a in (K_5, *range(JCCHAR, JCCHAR + 0x20, 4)):
        v = dict(build()).get(a)
        assert v is None or ref.get(a) == v, f"{a:08X} : divergence avec actors.py"
    addrs, code = _routines()
    for name, a in addrs.items():
        print(f"== {name} @ {a:08X}")
    print(listing(CODE, b"".join(v.to_bytes(4, "big") for _, v in code)))
    print(len(build()), "mots ;", len(SITES), "sites vérifiés au DOL")
