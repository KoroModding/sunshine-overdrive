"""Goop growth, gameplay mask versus displayed copy.

Every ~5 ms, for each layer tracked by the goop module: goop texels (> 127)
in the mask and in the smoothed copy, with the game's frame counter. Only
changes are logged, showing whether the mask grows in steps (the game) or the
copy lags behind it (the module).

    python tools/watch_goop_growth.py [secondes]      (défaut 120)
"""
from __future__ import annotations
import struct, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

ROOTS = 0x80002FA0
JAI = 0x8040E430


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 120.0
    d = Dolphin()
    slots = []
    for i in range(16):
        s = d.u32(ROOTS + 4 * i)
        if s:
            layer, mask, disp = struct.unpack(">3I", d.read(s, 12))
            w, h = struct.unpack(">2H", d.read(s + 24, 4))
            slots.append((i, mask, disp, w * h))
    print(f"{len(slots)} couches suivies", flush=True)
    last = {}
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < dur:
        img = d.u32(d.u32(JAI) + 0x20)
        now = time.perf_counter() - t0
        for i, mask, disp, n in slots:
            m = int((np.frombuffer(d.read(mask, n), np.uint8) > 127).sum())
            c = int((np.frombuffer(d.read(disp, n), np.uint8) > 127).sum())
            if last.get(i) != (m, c):
                if i in last:
                    print(f"[{now:7.3f}s img {img}] couche {i} : masque {m:5d} ({m - last[i][0]:+d})  "
                          f"copie {c:5d} ({c - last[i][1]:+d})  écart {m - c:+d}", flush=True)
                last[i] = (m, c)
        time.sleep(0.005)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
