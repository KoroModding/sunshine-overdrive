"""Sonde du module goop pendant un nettoyage : la copie d'affichage suit-elle le masque ?

Pour la couche sous Mario, toutes les ~40 ms : nombre de texels où la copie D
en RAM diffère de tente3x3(masque) de plus de 2 (texel (0,0) exclu), nombre de
texels « goop » (> 127) du masque, état de la zone marquée par les tampons
(dframes, rectangle) et octet (0,0) de D. Journal dans work/goop-probe.log.

    python tools/goop_probe.py [secondes]
"""
from __future__ import annotations
import struct, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

ROOTS = 0x80002FA0
LOG = Path(__file__).resolve().parent.parent / "work" / "goop-probe.log"


def detile(buf, w, h):
    a = np.frombuffer(buf, np.uint8).reshape(h // 4, w // 8, 4, 8)
    return a.transpose(0, 2, 1, 3).reshape(h, w).astype(np.int32)


def tent(m):
    p = np.pad(m, 1, mode="edge")
    r = p[:-2] + 2 * p[1:-1] + p[2:]
    return (r[:, :-2] + 2 * r[:, 1:-1] + r[:, 2:] + 8) >> 4


def main(argv):
    dur = float(argv[1]) if len(argv) > 1 else 60
    d = Dolphin()
    t0 = time.perf_counter()
    with LOG.open("w", encoding="utf-8") as log:
        while time.perf_counter() - t0 < dur:
            m = d.u32(0x8040E0E8)
            mx, _, mz = struct.unpack(">3f", d.read(m + 0x10, 12))
            line = f"{time.perf_counter() - t0:7.2f}"
            for i in range(8):
                s = d.u32(ROOTS + 4 * i)
                if not s:
                    continue
                layer, mask, disp = struct.unpack(">3I", d.read(s, 12))
                x0, x1, z0, z1 = [struct.unpack(">f", d.read(layer + o, 4))[0] for o in (0x38, 0x3C, 0x40, 0x44)]
                if not (x0 <= mx < x1 and z0 <= mz < z1):
                    continue
                w, h = struct.unpack(">2H", d.read(s + 24, 4))
                dx0, dx1, dy0, dy1 = struct.unpack(">4H", d.read(s + 30, 8))
                df = d.u8(s + 38)
                M = detile(d.read(mask, w * h), w, h)
                D = detile(d.read(disp, w * h), w, h)
                diff = np.abs(D - tent(M)) > 2
                diff[0, 0] = False
                ys, xs = np.nonzero(diff)
                box = f"x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}" if len(xs) else "-"
                ms, mt = (mx - x0) / (x1 - x0) * w, (mz - z0) / (z1 - z0) * h
                line += (f"  couche{i} mario=({ms:.0f},{mt:.0f}) goop={int((M > 127).sum())} "
                         f"écart={int(diff.sum())} [{box}] marque df={df} x{dx0}-{dx1} y{dy0}-{dy1} D00={D[0,0]}")
            log.write(line + "\n")
            log.flush()
            time.sleep(0.04)
    print("journal :", LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
