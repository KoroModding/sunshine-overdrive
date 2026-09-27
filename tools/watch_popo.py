"""Poink (TPopo, vtable 0x803BA558) : remplissage sur la buse, lancement, vol,
explosion. Pour trancher « explose tout de suite et ne dépasse pas 2 m ».

Lu dans le DOL (GMSE01) :
- TPopo::checkTrigger 0x800E8898, appelé par le nerf PossessedNozzle :
  gâchette R = (u8) *(*(gpMarioOriginal + 0x4FC) + 0xB4) ; > 0x14 : remplissage
  +0x198 += R × prm+0x42C, plafonné à prm+0x404 ; relâchée (< 0x14) et
  remplissage > prm+0x440 (ou +0x1CC) -> lancement.
- TNervePopoFly 0x800E6078, pas 0 : vitesse = prm+0x3B4 × (+0x198 / prm+0x404)
  × axe de la buse ; drapeau « en l'air » +0xF0 & 0x80. Dès qu'il retombe à 0
  (contact) -> Explosion.
- TPopo::flyBehavior 0x800E6AD0 : +0x19C compteur de vol, > prm+0x3DC ->
  Explosion ; +0x198 *= 0,999 par exécution.

Nerf courant = *(*(+0x8C) + 0x14) (objet statique, sa vtable en tête) ; pas du
nerf = *(+0x8C) + 0x20.

    python tools/watch_popo.py [secondes]      (défaut 180)
"""
from __future__ import annotations
import math, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402
from symbols import SymbolTable  # noqa: E402

SYMS = SymbolTable.load(Path(__file__).parent.parent / "work" / "maps" / "us.map")

VT_POPO = 0x803BA558
NERVES = {
    0x803BA4F8: "Thrown", 0x803BA508: "Wait", 0x803BA518: "Explosion",
    0x803BA528: "Fly", 0x803BA538: "Attack", 0x803BA548: "PossessedNozzle",
}
LIT = 0x804167B8          # 0.5 à 30 FPS, 2.0 au profil 120 ; M = 2 × lit
JAI = 0x8040E430          # JAIBasic::basic, compteur d'images en +0x20
MARIO = 0x8040E0E8        # gpMarioOriginal


def find(d: Dolphin) -> list[int]:
    raw = d.read(0x80000000, 0x01800000)
    key = struct.pack(">I", VT_POPO)
    out, i = [], raw.find(key)
    while i != -1:
        if i % 4 == 0:
            out.append(0x80000000 + i)
        i = raw.find(key, i + 4)
    return out


def nerve(d: Dolphin, p: int) -> tuple[str, int]:
    sp = d.u32(p + 0x8C)
    if not d.is_valid_pointer(sp):
        return "?", -1
    n = d.u32(sp + 0x14)
    vt = d.u32(n) if d.is_valid_pointer(n) else 0
    return NERVES.get(vt, f"{vt:08X}"), struct.unpack(">i", d.read(sp + 0x20, 4))[0]


def trigger(d: Dolphin) -> int:
    m = d.u32(MARIO)
    if not d.is_valid_pointer(m):
        return -1
    pad = d.u32(m + 0x4FC)
    if not d.is_valid_pointer(pad):
        return -1
    return int(d.f32(pad + 0xB4)) & 0xFF


def frame(d: Dolphin) -> int:
    return d.u32(d.u32(JAI) + 0x20)


def hits(d: Dolphin, p: int) -> list[str]:
    """Liste de collisions du THitActor : +0x44 THitActor**, +0x48 u16 nombre."""
    lst, n = d.u32(p + 0x44), d.u16(p + 0x48)
    if not d.is_valid_pointer(lst) or n == 0 or n > 16:
        return []
    out = []
    for k in range(n):
        a = d.u32(lst + 4 * k)
        vt = d.u32(a) if d.is_valid_pointer(a) else 0
        sym = SYMS.at(vt)
        name = sym.name.replace("__vt__", "") if sym else f"{vt:08X}"
        if a == d.u32(MARIO):
            name += " (Mario)"
        out.append(f"{a:08X} {name}")
    return out


def track(d: Dolphin, p: int) -> None:
    """Boucle serrée sur un Poink en vol : touches du Poink et de sa boîte
    TPopoCollision (+0x23C), écart boîte / Poink, jusqu'à la fin du vol."""
    col = d.u32(p + 0x23C)
    print(f"      suivi serré de {p:08X}, boîte {col:08X}", flush=True)
    seen, t0 = set(), time.perf_counter()
    while time.perf_counter() - t0 < 2.0:
        name, step = nerve(d, p)
        if name != "Fly":
            print(f"      fin du suivi : {name} au pas {step}", flush=True)
            return
        pp = struct.unpack(">3f", d.read(p + 0x10, 12))
        cp = struct.unpack(">3f", d.read(col + 0x10, 12))
        key = (step, d.u32(p + 0x64) & 1, d.u32(col + 0x64) & 1)
        if key not in seen:
            seen.add(key)
            print(f"      pas {step:3d}  collision off : poink {key[1]} boîte {key[2]}  "
                  f"écart boîte-poink {math.dist(pp, cp):6.1f} u", flush=True)
        for who, a in (("poink", p), ("boîte", col)):
            for h in hits(d, a):
                if (who, h, step) not in seen:
                    seen.add((who, h, step))
                    print(f"      pas {step:3d}  {who} touche {h}", flush=True)


def params(d: Dolphin, p: int) -> str:
    prm = d.u32(p + 0x194)
    if not d.is_valid_pointer(prm):
        return "prm introuvable"
    f = lambda o: d.f32(prm + o)
    t = struct.unpack(">i", d.read(prm + 0x3DC, 4))[0]
    return (f"vitesse 0x3B4={f(0x3B4):g}  max 0x404={f(0x404):g}  débit 0x42C={f(0x42C):g}  "
            f"seuil 0x440={f(0x440):g}  mult 0x454={f(0x454):g}  vol max 0x3DC={t}")


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 180.0
    d = Dolphin()
    lit = d.f32(LIT)
    print(f"littéral 0x804167B8 = {lit}  (M = {2 * lit:g})", flush=True)
    print("en attente d'un TPopo en MEM1…", flush=True)
    while not (popos := find(d)):
        time.sleep(2)
    time.sleep(2)
    popos = find(d)
    print(f"{len(popos)} TPopo {[hex(p) for p in popos]}", flush=True)
    print(f"  {params(d, popos[0])}", flush=True)

    last = {p: None for p in popos}
    fly = {}                     # p -> (t0, img0, pas-compteur, pos0, maxstep)
    trig_last, t_start = None, time.perf_counter()
    while time.perf_counter() - t_start < dur:
        now, img = time.perf_counter(), frame(d)
        tr = trigger(d)
        for p in popos:
            name, step = nerve(d, p)
            fill = d.f32(p + 0x198)
            if name != last[p]:
                pos = struct.unpack(">3f", d.read(p + 0x10, 12))
                vel = struct.unpack(">3f", d.read(p + 0xAC, 12))
                air = bool(d.u32(p + 0xF0) & 0x80)
                msg = (f"[{now - t_start:7.2f}s img {img}] {p:08X} {last[p]} -> {name}  pas {step}  "
                       f"remplissage {fill:.3f}  R={tr}  en l'air={air}")
                if name == "Fly":
                    fly[p] = (now, img, pos, 0, 0.0)
                    track(d, p)
                elif p in fly:
                    t0, i0, p0, maxstep, _ = fly.pop(p)
                    flown = d.u32(p + 0x19C)
                    msg += (f"\n      vol : {now - t0:.3f} s, {img - i0} images, pas max {maxstep}, "
                            f"compteur 0x19C={flown}, distance horiz. "
                            f"{math.dist((p0[0], p0[2]), (pos[0], pos[2])):.0f} u, "
                            f"dy {pos[1] - p0[1]:.0f} u, vitesse finale ({vel[0]:.1f}, {vel[1]:.1f}, {vel[2]:.1f})")
                print(msg, flush=True)
                last[p] = name
            if name == "Fly" and p in fly:
                t0, i0, p0, maxstep, v = fly[p]
                vel = struct.unpack(">3f", d.read(p + 0xAC, 12))
                if step <= 2 and v == 0.0:
                    print(f"      lancement : vitesse ({vel[0]:.1f}, {vel[1]:.1f}, {vel[2]:.1f})  "
                          f"|v|={math.hypot(*vel):.1f}  remplissage {fill:.3f}", flush=True)
                    v = 1.0
                for h in hits(d, p):
                    print(f"      pas {step} : touche {h}", flush=True)
                fly[p] = (t0, i0, p0, max(maxstep, step), v)
            if name == "PossessedNozzle" and tr != trig_last:
                print(f"      buse : R={tr}  remplissage {fill:.3f}  pas {step}", flush=True)
        trig_last = tr
        time.sleep(0.002)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
