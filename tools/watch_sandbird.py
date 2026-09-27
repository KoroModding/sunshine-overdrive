"""Sand bird (TSandBird, vtable 0x803CF2B4): rate of its two animations and
flight speed, to settle "too slow, or just an impression".

TSandBird derives from TJointCoin (loadAfter 0x801F761C, control 0x801F79C4):
- +0x138 MActor "movement": advanced by TJointCoin::control, so per
  substep; its root joint translation becomes the position (+0x10).
- +0x74  MActor "character": advanced by control AND by TLiveActor::perform.
Rate (frame ctrl 0, +0xC) set at load: 0.25 * SMSGetAnmFrameRate().

Frame ctrl 0 = *(*(MActor + 0x28)) + 4 (MActor::getFrameCtrl 0x80238F08);
J3DFrameCtrl: +0x6 start s16, +0x8 end s16, +0xC rate f32, +0x10 frame f32.

Waits for a bird to appear in MEM1, then measures over windows:

    python tools/watch_sandbird.py [fenêtres] [secondes]     (défaut 5 × 2 s)
"""
from __future__ import annotations
import math, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

VT_SANDBIRD = 0x803CF2B4
VT_JOINTCOIN = 0x803D61D0
LIT = 0x804167B8                  # 0.5 at 30 FPS, 2.0 in the 120 profile; M = 2 * lit
JAI = 0x8040E430                  # JAIBasic::basic, frame counter at +0x20


def find(d: Dolphin, vt: int) -> list[int]:
    raw = d.read(0x80000000, 0x01800000)
    key = struct.pack(">I", vt)
    out, i = [], raw.find(key)
    while i != -1:
        if i % 4 == 0:
            out.append(0x80000000 + i)
        i = raw.find(key, i + 4)
    return out


def ctrl(d: Dolphin, actor: int, off: int) -> int | None:
    m = d.u32(actor + off)
    if not d.is_valid_pointer(m):
        return None
    tab = d.u32(m + 0x28)
    if not d.is_valid_pointer(tab):
        return None
    c = d.u32(tab)
    return c + 4 if d.is_valid_pointer(c) else None


def state(d: Dolphin, c: int) -> tuple[int, int, float, float]:
    start, end = struct.unpack(">hh", d.read(c + 6, 4))
    rate, frame = struct.unpack(">2f", d.read(c + 0xC, 8))
    return start, end, rate, frame


def pos(d: Dolphin, o: int) -> tuple[float, ...]:
    return struct.unpack(">3f", d.read(o + 0x10, 12))


def window(d: Dolphin, bird: int, dur: float) -> None:
    ctrls = {name: ctrl(d, bird, off) for name, off in (("movement", 0x138), ("character", 0x74))}
    acc = {k: 0.0 for k in ctrls}
    last = {k: state(d, c)[3] for k, c in ctrls.items() if c}
    p0, dist = pos(d, bird), 0.0
    f0, t0 = d.u32(d.u32(JAI) + 0x20), time.perf_counter()
    while time.perf_counter() - t0 < dur:
        time.sleep(0.02)
        for k, c in ctrls.items():
            if not c:
                continue
            start, end, _, fr = state(d, c)
            delta = fr - last[k]
            if delta < 0:                      # animation loop wrap
                delta += end - start
            acc[k] += delta
            last[k] = fr
        p1 = pos(d, bird)
        dist += math.dist(p0, p1)
        p0 = p1
    f1, dt = d.u32(d.u32(JAI) + 0x20), time.perf_counter() - t0
    imgs = f1 - f0
    print(f"  {dt:.2f} s, {imgs / dt:.1f} images/s, vol {dist / dt:.1f} u/s")
    for k, c in ctrls.items():
        if not c:
            print(f"    {k:9} : frame ctrl introuvable")
            continue
        start, end, rate, fr = state(d, c)
        fps = acc[k] / dt
        tour = (end - start) / fps if fps > 0 else float("inf")
        print(f"    {k:9} : débit {rate:.4f}  {fps:6.1f} trames d'anim/s  "
              f"longueur {end - start} trames -> un tour en {tour:.1f} s  (trame {fr:.1f})")


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 else 5
    dur = float(argv[2]) if len(argv) > 2 else 2.0
    d = Dolphin()
    lit = d.f32(LIT)
    print(f"littéral 0x804167B8 = {lit}  (M = {2 * lit:g})", flush=True)
    print("en attente d'un TSandBird en MEM1…", flush=True)
    while not (birds := find(d, VT_SANDBIRD)):
        time.sleep(2)
    time.sleep(3)                                  # let loadAfter run
    birds = find(d, VT_SANDBIRD)
    coins = find(d, VT_JOINTCOIN)
    print(f"{len(birds)} TSandBird {[hex(b) for b in birds]}, {len(coins)} TJointCoin", flush=True)
    for i in range(n):
        for b in birds:
            print(f"fenêtre {i + 1}/{n}, oiseau {b:08X}", flush=True)
            window(d, b, dur)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
