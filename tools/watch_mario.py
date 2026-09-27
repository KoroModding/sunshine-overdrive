"""Journal image par image de l'état de Mario, pour comparer une même action à
30 FPS (jeu d'origine) et à 120 FPS (profil) : glissade murale, propulsions,
etc.

Chaque ligne : temps réel, compteur d'images (JAIBasic::basic → +0x20, un par
image rendue), action (+0x7C), sous-état (+0x84), minuteur (+0x86), vitesse
(+0xA4 x/y/z), vitesse avant (+0xB0), position (+0x10 x/y/z). Une ligne n'est
écrite que si l'image a changé.

En fin d'enregistrement, un résumé par action : durée cumulée, vitesse
verticale moyenne en unités par SECONDE (déplacement de position / temps
d'images, indépendant de la cadence) et vitesse horizontale moyenne.

    python tools/watch_mario.py <étiquette> [secondes]     (défaut 300)
        journal dans work/mario-<étiquette>.log
"""
from __future__ import annotations

import math
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

WORK = Path(__file__).resolve().parent.parent / "work"
GP_MARIO = 0x8040E0E8
JAI_BASIC = 0x8040E430
LIT = 0x804167B8


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    label = argv[1]
    dur = float(argv[2]) if len(argv) > 2 else 300.0
    d = Dolphin()
    jai = d.u32(JAI_BASIC) + 0x20
    log_path = WORK / f"mario-{label}.log"
    fps = 30.0 * 2 * d.f32(LIT)          # images rendues par seconde attendues
    stats: dict[int, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])  # images, dy, dxz
    last_f, last_p, last_a = None, None, None
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# littéral={d.f32(LIT)}  cadence attendue {fps:.0f} images/s\n")
        while time.perf_counter() - t0 < dur:
            try:
                f = d.u32(jai)
                m = d.u32(GP_MARIO)
                if f == last_f or not d.is_valid_pointer(m):
                    time.sleep(0.001)
                    continue
                act = d.u32(m + 0x7C)
                st, tm = d.u16(m + 0x84), d.u16(m + 0x86)
                vx, vy, vz, fwd = struct.unpack(">4f", d.read(m + 0xA4, 16))
                p = struct.unpack(">3f", d.read(m + 0x10, 12))
            except (OSError, RuntimeError):
                time.sleep(0.5)
                continue
            log.write(f"{time.perf_counter() - t0:9.3f} {f:9d} {act:08X} {st:3d} {tm:5d} "
                      f"v=({vx:8.2f},{vy:8.2f},{vz:8.2f}) fwd={fwd:7.2f} "
                      f"p=({p[0]:9.1f},{p[1]:9.1f},{p[2]:9.1f})\n")
            if last_p is not None and last_a == act and last_f is not None:
                n = f - last_f
                s = stats[act]
                s[0] += n
                s[1] += p[1] - last_p[1]
                s[2] += math.hypot(p[0] - last_p[0], p[2] - last_p[2])
            last_f, last_p, last_a = f, p, act
        log.write("\n# action   images   durée(s)   vy moy (u/s)   vxz moy (u/s)\n")
        for act, (n, dy, dxz) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
            if n:
                sec = n / fps
                log.write(f"# {act:08X} {n:7d} {sec:9.2f} {dy / sec:14.1f} {dxz / sec:14.1f}\n")
    print(f"journal : {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
