"""Fish schools / flocks (TBoidLeader and subclasses): movement speed, to settle
"the red-coin fish are too fast and go through walls".

Read in the DOL (GMSE01): TBoidLeader::perform (0x80005D14) runs calcBoids and
the leader's own move only under flag 0x2, i.e. once per rendered frame; the
per-frame displacement does not depend on the frame rate, so the school moves
M times faster at 120 FPS (M = 2 x literal 0x804167B8). Prediction: 4x the
30 FPS speed.

For every leader found in MEM1 (vtables of TBoidLeader and its subclasses),
prints its speed over fixed windows, in game units per second and per frame.

    python tools/watch_boids.py [windows] [seconds]      (défaut 5 × 2 s)
"""
from __future__ import annotations
import math, re, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

MAP = Path(__file__).resolve().parent.parent / "work" / "maps" / "us.map"
LIT = 0x804167B8
JAI = 0x8040E430
CLASSES = ("TBoidLeader",)   # TFishoid/TButterfloid embed their own TBoidLeader
POS = 0x74          # leader position: TBoidLeader::perform 0x80005E2C..0x80005E58
HEAP = 0x80430000   # past the DOL sections and BSS: skips vtable constants in code/data


def vtables() -> dict[int, str]:
    out = {}
    for line in MAP.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"__vt__\d+(\w+)=0x([0-9A-Fa-f]+)", line)
        if m and m.group(1) in CLASSES:
            out[int(m.group(2), 16)] = m.group(1)
    return out


def find(d: Dolphin, vts: dict[int, str]) -> list[tuple[int, str]]:
    raw = d.read(0x80000000, 0x01800000)
    out = []
    for vt, name in vts.items():
        key, i = struct.pack(">I", vt), 0
        i = raw.find(key)
        while i != -1:
            if i % 4 == 0 and 0x80000000 + i >= HEAP:
                out.append((0x80000000 + i, name))
            i = raw.find(key, i + 4)
    return out


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 else 5
    dur = float(argv[2]) if len(argv) > 2 else 2.0
    d = Dolphin()
    print(f"littéral 0x804167B8 = {d.f32(LIT)}  (M = {2 * d.f32(LIT):g})", flush=True)
    vts = vtables()
    print("en attente d'un banc en MEM1…", flush=True)
    while not (leaders := find(d, vts)):
        time.sleep(2)
    print(f"{len(leaders)} meneur(s) : " + ", ".join(f"{a:08X} {c}" for a, c in leaders), flush=True)
    for w in range(n):
        p0 = {a: struct.unpack(">3f", d.read(a + POS, 12)) for a, _ in leaders}
        dist = {a: 0.0 for a, _ in leaders}
        last = dict(p0)
        f0, t0 = d.u32(d.u32(JAI) + 0x20), time.perf_counter()
        while time.perf_counter() - t0 < dur:
            time.sleep(0.01)
            for a, _ in leaders:
                p = struct.unpack(">3f", d.read(a + POS, 12))
                dist[a] += math.dist(last[a], p)
                last[a] = p
        dt, frames = time.perf_counter() - t0, d.u32(d.u32(JAI) + 0x20) - f0
        print(f"fenêtre {w + 1}/{n} : {dt:.2f} s, {frames / dt:.1f} images/s", flush=True)
        for a, c in leaders:
            print(f"    {a:08X} {c:12} : {dist[a] / dt:8.1f} u/s  {dist[a] / frames if frames else 0:7.2f} u/image"
                  f"  pos ({last[a][0]:.0f}, {last[a][1]:.0f}, {last[a][2]:.0f})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
