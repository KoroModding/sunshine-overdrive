"""Petey's goop drops (TBPPolDrop, vtable 0x803B493C): puddle spreading speed,
to settle "spreads in slow motion".

Read in the DOL (GMSE01):
- TBPPolDrop::perform 0x80098498: +0x80 state (1 airborne, 2 landed), +0x84
  pass counter (flag 0x1); in state 2 the "stamp" MActor +0x7C is advanced
  by MActor::calcAnm (flag 0x2, once per rendered frame), then drawn into the
  mask by TPollutionManager::stampModel (flag 0x200).
- TBPPolDrop::move 0x8009870C: setBck on the stamp at landing, without
  setFrameRate.

Frame ctrl 0 = *(*(MActor + 0x28)) + 4; J3DFrameCtrl: +0x6 start s16,
+0x8 end s16, +0xC rate f32, +0x10 frame f32.

    python tools/watch_poldrop.py [secondes]      (défaut 300)
"""
from __future__ import annotations
import struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

VT = 0x803B493C
LIT = 0x804167B8
JAI = 0x8040E430


def find(d: Dolphin) -> list[int]:
    raw = d.read(0x80000000, 0x01800000)
    key = struct.pack(">I", VT)
    out, i = [], raw.find(key)
    while i != -1:
        if i % 4 == 0:
            out.append(0x80000000 + i)
        i = raw.find(key, i + 4)
    return out


def ctrl(d: Dolphin, actor: int) -> int | None:
    m = d.u32(actor + 0x7C)
    if not d.is_valid_pointer(m):
        return None
    tab = d.u32(m + 0x28)
    if not d.is_valid_pointer(tab):
        return None
    c = d.u32(tab)
    return c + 4 if d.is_valid_pointer(c) else None


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 300.0
    d = Dolphin()
    print(f"littéral 0x804167B8 = {d.f32(LIT)}", flush=True)
    print("en attente de TBPPolDrop en MEM1…", flush=True)
    while not (drops := find(d)):
        time.sleep(2)
    print(f"{len(drops)} TBPPolDrop", flush=True)
    t0 = time.perf_counter()
    last = {p: None for p in drops}
    spread = {}                    # p -> (t, frame, anim frame, max anim frame) on entering state 2
    while time.perf_counter() - t0 < dur:
        img = d.u32(d.u32(JAI) + 0x20)
        now = time.perf_counter() - t0
        for p in drops:
            st = d.u32(p + 0x80)
            c = ctrl(d, p)
            if c is None:
                continue
            s, e = struct.unpack(">hh", d.read(c + 6, 4))
            rate, fr = struct.unpack(">2f", d.read(c + 0xC, 8))
            if st != last[p]:
                print(f"[{now:7.2f}s img {img}] {p:08X} état {last[p]} -> {st}  "
                      f"tampon : débit {rate:.3f} trame {fr:.1f} / {e}", flush=True)
                if st == 2:
                    spread[p] = (now, img, fr, fr)
                last[p] = st
            if st == 2 and p in spread:
                ts, i0, f0, fmax = spread[p]
                if fr > fmax:
                    spread[p] = (ts, i0, f0, fr)
                elif fr < fmax or fr >= e - 0.01:          # end or loop wrap
                    dt, di = now - ts, img - i0
                    print(f"      étalement : trames {f0:.1f} -> {fmax:.1f} en {dt:.2f} s, {di} images "
                          f"-> {(fmax - f0) / dt if dt else 0:.1f} trames/s, "
                          f"{(fmax - f0) / di if di else 0:.3f} trame/image, débit {rate:.3f}", flush=True)
                    spread.pop(p)
        time.sleep(0.002)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
