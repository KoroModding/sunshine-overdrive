"""Times the JAI background-music fades in-game (tools/fixes/fades.py).

1. **Presence**: reads back every word of the profile (base + fades).
2. **Fades**: for each MSBgm track playing, reads the 309 JAIMoveParaSet of
   its JAISeqParameter (+0x04 .. +0x1353: tempo, port data,
   volume/pan/pitch/fxmix/dolby per track). Whenever a counter (+0xC) goes
   from 0 to some N, the fade is timed until it returns to 0.

Reading the output. The counter drops by one per JAI pass, ~120/s at 120 FPS.
With the fix, N = 4 * the original duration (in 30 Hz passes) and the real
duration is N / 120 s = the original duration. Without it, N is the original
value and the fade is 4x too short. The two useful columns:
    N           expected to be a multiple of 4 (the first reading can miss 1 pass)
    durée       real seconds; "N/120" predicts it

Not measured: sound-effect fades (JAISeParameter, too many and too short for
polling), and how it sounds. A fade shorter than ~3 passes can fall between
two reads.

Usage
-----
    python tools/watch_fades.py [secondes]        (défaut 300)
        journal dans work/fades.log
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_profile import collect  # noqa: E402
from dolphin import Dolphin  # noqa: E402
from watch_audio import SM_BGM_IN_TRACK  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "work" / "fades.log"
FIRST, END = 0x04, 0x1354
GROUPS = [(0x04, "tempo"), (0x14, "port"), (0x114, "volume"), (0x254, "pan"),
          (0x394, "hauteur"), (0x4D4, "fxmix"), (0x614, "dolby"), (0x754, "piste")]


def kind(off: int) -> str:
    name = "?"
    for start, n in GROUPS:
        if off >= start:
            name = f"{n}[{(off - start) // 16}]"
    return name


def main(argv: list[str]) -> int:
    duration = float(argv[1]) if len(argv) > 1 else 300.0
    d = Dolphin()
    words = collect(["fades"])
    wrong = [(a, v, d.u32(a)) for _, a, v in words if d.u32(a) != v]
    print(f"Profil : {len(words) - len(wrong)}/{len(words)} mots en place")
    for a, v, got in wrong:
        print(f"  {a:08X}  attendu {v:08X}  lu {got:08X}")
    if wrong:
        return 1

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"Chronométrage des fondus de musique pendant {duration:.0f} s")
    running: dict[tuple[int, int], tuple[int, float, float, float]] = {}
    end = time.perf_counter() + duration
    count = 0
    while time.perf_counter() < end:
        now = time.perf_counter()
        for track in range(8):
            bgm = d.u32(SM_BGM_IN_TRACK + 4 * track)
            if not d.is_valid_pointer(bgm):
                continue
            snd = d.u32(bgm + 0x14)
            if not d.is_valid_pointer(snd):
                continue
            seq = d.u32(snd + 0x38)
            if not d.is_valid_pointer(seq):
                continue
            block = d.read(seq + FIRST, END - FIRST)
            for i in range(0, len(block), 16):
                target, cur, _, n = struct.unpack(">fffI", block[i:i + 16])
                key = (snd, FIRST + i)
                if n and n < 100000 and key not in running:
                    running[key] = (n, now, cur, target)
                elif not n and key in running:
                    n0, t0, v0, tg = running.pop(key)
                    count += 1
                    log(f"piste {track}  {kind(FIRST + i):<12} N={n0:<5} durée {now - t0:6.3f} s "
                        f"(N/120 = {n0 / 120:6.3f} s)  {v0:.3f} -> {tg:.3f}")
        time.sleep(0.002)
    log(f"Fin : {count} fondu(s) chronométré(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
