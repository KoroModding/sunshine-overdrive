"""Frame rate during HX wipes: VI fields/s and frames/s per 0.25 s slice, with
the HX timer (0x803F43FC) and the active wipe routine (0x803F43E0).

    python tools/watch_wipe.py [secondes]      log in work/wipe.log
"""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "work" / "wipe.log"
VI_COUNT = 0x8040E8D0          # VIGetRetraceCount : lwz r3, -0x58f0(r13)
HX_TIMER = 0x803F43FC
HX_FUNC = 0x803F43E0


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 300.0
    d = Dolphin()
    jai = d.u32(0x8040E430) + 0x20
    t0 = time.perf_counter()
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        v, j, t = d.u32(VI_COUNT), d.u32(jai), t0
        while t - t0 < dur:
            time.sleep(0.25)
            try:
                v2, j2, t2 = d.u32(VI_COUNT), d.u32(jai), time.perf_counter()
                hx, fn = d.s32(HX_TIMER), d.u32(HX_FUNC)
            except (OSError, RuntimeError):
                time.sleep(1); continue
            dt = t2 - t
            log.write(f"{t2 - t0:8.2f}  champs/s={(v2 - v) / dt:6.1f}  images/s={(j2 - j) / dt:6.1f}"
                      f"  hx={hx}  fn={fn:#x}\n")
            log.flush()
            v, j, t = v2, j2, t2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
