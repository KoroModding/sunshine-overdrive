"""Bird speed (TAnimalBird, vtable 0x803ABE78): scans MEM1 for instances, then
measures their displacement (position +0x10) over a window, in units per
second and per rendered frame.

    python tools/watch_birds.py [secondes]     (défaut 3)
"""
from __future__ import annotations
import math, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

VT = 0x803ABE78


def find(d: Dolphin) -> list[int]:
    raw = d.read(0x80000000, 0x01800000)
    key = struct.pack(">I", VT)
    out, i = [], raw.find(key)
    while i != -1:
        if i % 4 == 0:
            out.append(0x80000000 + i)
        i = raw.find(key, i + 4)
    return out


def pos(d: Dolphin, o: int) -> tuple[float, ...]:
    return struct.unpack(">3f", d.read(o + 0x10, 12))


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 3.0
    d = Dolphin()
    birds = find(d)
    jai = d.u32(0x8040E430) + 0x20
    p0 = {o: pos(d, o) for o in birds}
    f0, t0 = d.u32(jai), time.perf_counter()
    time.sleep(dur)
    p1 = {o: pos(d, o) for o in birds}
    f1, t1 = d.u32(jai), time.perf_counter()
    imgs, dt = f1 - f0, t1 - t0
    print(f"littéral={d.f32(0x804167B8)}  {len(birds)} oiseaux  {imgs / dt:.1f} images/s")
    speeds = []
    for o in birds:
        dist = math.dist(p0[o], p1[o])
        speeds.append(dist / dt)
        print(f"  {o:08X}  {dist / dt:8.1f} u/s  {dist / max(imgs, 1):7.3f} u/image")
    moving = sorted(s for s in speeds if s > 1)
    if moving:
        print(f"en mouvement : {len(moving)}, médiane {moving[len(moving) // 2]:.1f} u/s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
