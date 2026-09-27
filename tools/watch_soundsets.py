"""Mesure l'horloge des jeux de sons MSSetSound / MSSetSoundGrp (tools/fixes/soundsets.py).

Parcourt les deux listes que MSound::mainLoop itère (0x8040CF20 : MSSetSound,
0x8040CF14 : MSSetSoundGrp ; nœud : objet +0, suivant +0xC — lu dans
mainLoop 0x80014E00…0x80014E44) et relève, pour chaque objet, l'horloge +0x54
et son drapeau d'activité +0x58 sur une fenêtre de mesure.

L'horloge n'avance que pendant qu'un jeu est actif (+0x58 non nul) ; la
cadence est rapportée au seul temps d'activité.

Compte aussi les DÉPARTS de son de chaque jeu : l'indice de tampon +0x59
tourne d'un cran à chaque départ ; sondé toutes les ~2 ms. C'est la grandeur
qui s'entend (répétitions du son d'impact du jet). Le nombre de départs dépend
du geste ; l'ÉCART entre deux départs consécutifs, non : pour 0x6800,
intervalle minimal 7 passages + aléa 0–6, soit 58–108 ms sans correctif
(passages à 120/s) et 233–433 ms avec (30/s). Seuls les écarts < 1 s comptent
(rafales continues).

Horloge — attendu : ~30 incréments/s pour tout jeu actif avec le correctif, ~120/s sans
lui (une fois par passage JAI). Un jeu inactif (+0x58 = 0) ne bouge pas : c'est
normal, rien à juger.

Usage
-----
    python tools/watch_soundsets.py [secondes]      (défaut 20) — pendant la mesure, arroser le sol avec FLUDD
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

LISTS = {"MSSetSound": 0x8040CF20, "MSSetSoundGrp": 0x8040CF14}
SITES = (0x80016014, 0x8001604C)


def objects(d: Dolphin) -> list[tuple[str, int]]:
    out = []
    for name, head in LISTS.items():
        node = d.u32(head)
        for _ in range(64):
            if not d.is_valid_pointer(node):
                break
            out.append((name, d.u32(node)))
            node = d.u32(node + 0xC)
    return out


def main(argv: list[str]) -> int:
    secs = float(argv[1]) if len(argv) > 1 else 20.0
    d = Dolphin()
    hooked = [d.u32(a) >> 26 == 18 for a in SITES]
    print("Correctif :", "posé" if all(hooked) else "ABSENT" if not any(hooked) else "partiel")
    objs = objects(d)
    last = {o: (d.u32(o + 0x54), d.u8(o + 0x58)) for _, o in objs}
    ticks = {o: 0 for _, o in objs}
    starts = {o: 0 for _, o in objs}
    stamps: dict[int, list[float]] = {o: [] for _, o in objs}
    slot = {o: d.u8(o + 0x59) for _, o in objs}
    last_clock_poll = 0.0
    active_s = {o: 0.0 for _, o in objs}
    t = time.perf_counter()
    end = t + secs
    while time.perf_counter() < end:
        time.sleep(0.002)
        now = time.perf_counter()
        for _, o in objs:
            sl = d.u8(o + 0x59)
            if sl != slot[o]:
                starts[o] += 1
                stamps[o].append(now)
                slot[o] = sl
        if now - last_clock_poll < 0.05:
            continue
        last_clock_poll = now
        for _, o in objs:
            clock, act = d.u32(o + 0x54), d.u8(o + 0x58)
            if act and last[o][1]:
                ticks[o] += (clock - last[o][0]) & 0xFFFFFFFF
                active_s[o] += now - t
            last[o] = (clock, act)
        t = now
    dt = secs
    for name, o in objs:
        clock = (f"horloge {ticks[o] / active_s[o]:6.2f} /s sur {active_s[o]:4.1f} s"
                 if active_s[o] >= 0.2 else "horloge inactive")
        gaps = sorted(b - a for a, b in zip(stamps[o], stamps[o][1:]) if b - a < 1.0)
        gap = (f"écart min {gaps[0] * 1000:4.0f} ms, médian {gaps[len(gaps) // 2] * 1000:4.0f} ms"
               if len(gaps) >= 5 else "écarts : trop peu")
        print(f"  {name:<14} son {d.u32(o + 0x10):04X}  départs {starts[o]:4d}  {gap}  {clock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
