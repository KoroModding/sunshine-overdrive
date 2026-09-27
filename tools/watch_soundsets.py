"""Measures the clock of the MSSetSound / MSSetSoundGrp sound sets (tools/fixes/soundsets.py).

Walks the two lists MSound::mainLoop iterates (0x8040CF20: MSSetSound,
0x8040CF14: MSSetSoundGrp; node: object +0, next +0xC, read in
mainLoop 0x80014E00..0x80014E44) and records, for each object, the clock +0x54
and its active flag +0x58 over a measurement window.

The clock only advances while a set is active (+0x58 non-zero); the rate is
computed over active time only.

Also counts sound STARTS per set: the buffer index +0x59 advances by one on
each start; polled every ~2 ms. This is what you hear (repeats of the spray
impact sound). The number of starts depends on what the player does; the GAP
between two consecutive starts does not: for 0x6800, minimum interval 7 passes
+ random 0-6, i.e. 58-108 ms without the fix (passes at 120/s) and 233-433 ms
with it (30/s). Only gaps < 1 s count (continuous bursts).

Clock, expected: ~30 ticks/s for any active set with the fix, ~120/s without
(once per JAI pass). An inactive set (+0x58 = 0) does not move; that is
normal.

Usage
-----
    python tools/watch_soundsets.py [secondes]      (défaut 20); spray the ground with FLUDD while it measures
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
