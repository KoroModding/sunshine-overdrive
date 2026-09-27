"""Mesure la fréquence de déclenchement de chaque effet sonore, à 30 puis 120 FPS.

S'appuie sur le journal posé par tools/fixes/sound.py dans
JAIBasic::startSoundBasic (anneau de 64 entrées en 0x80002C00) et sur
l'interrupteur de diagnostic de tools/fixes/contexts.py (0x80002BFC non nul =
30 FPS partout). Ni l'un ni l'autre n'est écrit par le profil : ce script les
lit et bascule l'interrupteur, rien d'autre.

Principe : pendant la même activité de jeu, un son déclenché par du code
cadencé en sous-pas garde la même fréquence en déclenchements par seconde aux
deux cadences ; un son déclenché par du code exécuté une fois par image rendue
est déclenché ~4× plus souvent à 120 FPS. Tout rapport 120/30 hors de
[0,5 ; 2] sur un effectif suffisant est signalé.

Usage
-----
    python tools/watch_se_rates.py ab [secondes-par-mode]     (défaut 60)
        mode 30 FPS puis mode 120 FPS, même durée, puis comparaison ; laisse
        le jeu à 120 FPS. Rapport dans work/se_rates.txt
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

RING = 0x80002C00
ENTRIES = 64
FORCE30 = 0x80002BFC
REPORT = Path(__file__).resolve().parent.parent / "work" / "se_rates.txt"


def record(d: Dolphin, seconds: float) -> tuple[Counter, float, int]:
    counts: Counter = Counter()
    idx = d.u32(RING)
    lost = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        new = d.u32(RING)
        n = (new - idx) % ENTRIES
        if n > ENTRIES - 8:
            lost += 1                         # l'anneau a peut-être débordé
        for k in range(n):
            e = RING + 8 + ((idx + k) % ENTRIES) * 8
            counts[d.u32(e)] += 1
        idx = new
        time.sleep(0.002)
    return counts, time.perf_counter() - t0, lost


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "ab":
        print(__doc__)
        return 2
    secs = float(argv[2]) if len(argv) > 2 else 60.0
    d = Dolphin()
    if d.u32(0x803020AC) >> 26 != 18:
        print("Journal absent : 0x803020AC n'est pas détourné (profil pas chargé ?)")
        return 1
    try:
        print(f"MODE 30 FPS pendant {secs:.0f} s — joue normalement", flush=True)
        d.write_u32(FORCE30, 1)
        time.sleep(1.0)
        c30, t30, l30 = record(d, secs)
        print(f"MODE 120 FPS pendant {secs:.0f} s — refais la même chose", flush=True)
        d.write_u32(FORCE30, 0)
        time.sleep(1.0)
        c120, t120, l120 = record(d, secs)
    finally:
        d.write_u32(FORCE30, 0)

    lines = [f"30 FPS : {sum(c30.values())} déclenchements en {t30:.1f} s (débordements possibles : {l30})",
             f"120 FPS : {sum(c120.values())} déclenchements en {t120:.1f} s (débordements possibles : {l120})",
             "", f"{'id':>10} {'/s à 30':>9} {'/s à 120':>9} {'rapport':>8}  verdict"]
    rows = []
    for sid in set(c30) | set(c120):
        r30, r120 = c30[sid] / t30, c120[sid] / t120
        ratio = (r120 / r30) if r30 else float("inf")
        enough = c30[sid] + c120[sid] >= 6
        suspect = enough and (ratio > 2.0 or ratio < 0.5)
        rows.append((not suspect, -abs(r120 - r30), sid, r30, r120, ratio, suspect, enough))
    for _, _, sid, r30, r120, ratio, suspect, enough in sorted(rows):
        verdict = "SUSPECT" if suspect else ("ok" if enough else "trop rare")
        lines.append(f"{sid:10X} {r30:9.2f} {r120:9.2f} {ratio:8.2f}  {verdict}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\nRapport complet : {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
