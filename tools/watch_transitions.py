"""Times in-game transitions: level-entry camera demo, TSMSFader fades, HX
wipes, and Mario's idle wait until he falls asleep.

Nothing is patched here. At ~500 Hz the tool logs every change of the values
below and stamps each line with two clocks: real time and the JAI pass counter
(JAIBasic::basic 0x8040E430 -> +0x20, one per rendered frame, 120/s in the
120 tier). The `img` column counts frames independently of the `time.sleep`
granularity on Windows (~15.6 ms).

Values logged
-------------
    dir   TMarDirector (gpMarDirector 0x8040E178) +0x64 u8: director state
    cam   gpCamera (0x8040D0A8) +0x50 mode, +0x64 flags (0x200 door,
          0x1000 roller coaster), demo +0x2B4 -> {+0x10 total, +0x14 remaining}
    bck   TCameraBck (+0x2B0) -> MActor -> getFrameCtrl(0): animation frame, rate, end
    fad   gpApplication (0x803E9700) +0x34 TSMSFader: +0x20 state,
          +0x10 duration, +0x12 counter, +0x14 rate, +0x2C delay
    hx    HX wipe countdown, 0x803F43FC
    mar   gpMarioOriginal (0x8040E0E8): +0x7C action, +0x84 substate,
          +0x86 timer

Usage
-----
    python tools/watch_transitions.py [secondes]      (défaut 600)
        journal dans work/transitions.log
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "work" / "transitions.log"

JAI_BASIC = 0x8040E430       # JAIBasic::basic (pointer); pass counter at +0x20
GP_APP = 0x803E9700
GP_DIRECTOR = 0x8040E178
GP_CAMERA = 0x8040D0A8
GP_MARIO = 0x8040E0E8
HX_TIMER = 0x803F43FC


def ptr(d: Dolphin, addr: int) -> int:
    v = d.u32(addr)
    return v if d.is_valid_pointer(v) else 0


def sample(d: Dolphin) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    out["ctx"] = (d.u8(GP_APP + 8),)
    dr = ptr(d, GP_DIRECTOR)
    out["dir"] = (d.u8(dr + 0x64),) if dr else ()
    cam = ptr(d, GP_CAMERA)
    if cam:
        demo = ptr(d, cam + 0x2B4)
        out["cam"] = (d.s32(cam + 0x50), d.u16(cam + 0x64) & 0xFEFE) + (
            (d.s32(demo + 0x10), d.s32(demo + 0x14)) if demo else ())
        bck = ptr(d, cam + 0x2B0)
        act = ptr(d, bck) if bck else 0
        tab = ptr(d, act + 0x28) if act else 0
        anm = ptr(d, tab) if tab else 0
        if anm:
            fc = anm + 4
            out["bck"] = (round(d.f32(fc + 0x10), 2), d.f32(fc + 0xC),
                          d.u16(fc + 8), d.u8(fc + 5))
    fad = ptr(d, GP_APP + 0x34)
    if fad:
        out["fad"] = (d.u32(fad + 0x20), d.u16(fad + 0x10), d.u16(fad + 0x12),
                      d.f32(fad + 0x14), round(d.f32(fad + 0x2C), 3))
    out["hx"] = (d.s32(HX_TIMER),)
    mar = ptr(d, GP_MARIO)
    if mar:
        out["mar"] = (hex(d.u32(mar + 0x7C)), d.u16(mar + 0x84), d.u16(mar + 0x86))
    return out


def main(argv: list[str]) -> int:
    duration = float(argv[1]) if len(argv) > 1 else 600.0
    d = Dolphin()
    t0 = time.perf_counter()
    jai = d.u32(JAI_BASIC) + 0x20
    f0 = d.u32(jai)
    last: dict[str, tuple] = {}
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                  f"littéral={d.f32(0x804167B8)}\n")
        while time.perf_counter() - t0 < duration:
            try:
                cur = sample(d)
                img = d.u32(jai) - f0
            except (OSError, RuntimeError):
                time.sleep(0.5)
                continue
            changed = {k: v for k, v in cur.items() if last.get(k) != v}
            if changed:
                line = f"{time.perf_counter() - t0:9.3f}  img={img:7d}  " + "  ".join(
                    f"{k}={v}" for k, v in changed.items())
                log.write(line + "\n")
                log.flush()
                last = cur
            time.sleep(0.002)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
