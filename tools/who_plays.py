"""Who plays this sound? Waits for a given sound to start, then finds in MEM1
the animation sound object (JAIAnimeSound / MAnmSound, vtable at +0x94) with a
slot (8 x 0xC: +0 active, +4 JAISound*, +8 event*) pointing at the instance,
and the actor that owns it (pointer at +0x80 of a TLiveActor).

    python tools/who_plays.py [id-hex] [secondes]      (défaut 2832, 120)
"""
from __future__ import annotations
import struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402
from symbols import SymbolTable  # noqa: E402
from watch_se import snapshot  # noqa: E402

SYMS = SymbolTable.load(Path(__file__).resolve().parent.parent / "work" / "maps" / "us.map")
ANM_VTS = {0x803AC460: "MAnmSound", 0x803E24B0: "JAIAnimeSound",
           0x803AC440: "MAnmSoundNPC", 0x803AC450: "MAnmSoundMario"}
JAI = 0x8040E430


def refs(raw: bytes, value: int) -> list[int]:
    key, out = struct.pack(">I", value), []
    i = raw.find(key)
    while i != -1:
        if i % 4 == 0:
            out.append(0x80000000 + i)
        i = raw.find(key, i + 1)
    return out


def vt_name(d: Dolphin, obj: int) -> str:
    vt = d.u32(obj)
    s = SYMS.at(vt)
    return s.name.replace("__vt__", "") if s else f"vt {vt:08X}"


def main(argv: list[str]) -> int:
    sid = int(argv[1], 16) if len(argv) > 1 else 0x2832
    dur = float(argv[2]) if len(argv) > 2 else 120.0
    d = Dolphin()
    prev = set(snapshot(d))
    t0 = time.perf_counter()
    seen = 0
    while time.perf_counter() - t0 < dur and seen < 12:
        cur = snapshot(d)
        new = [k for k in cur.keys() - prev if k[1] == sid]
        prev = set(cur)
        if not new:
            time.sleep(0.001)
            continue
        raw = d.read(0x80000000, 0x01800000)
        img = d.u32(d.u32(JAI) + 0x20)
        for js, _ in new:
            seen += 1
            print(f"[{time.perf_counter() - t0:7.3f}s img {img}] son {sid:08X} @{js:08X}", flush=True)
            for r in refs(raw, js):
                for k in range(8):
                    base = r - (k * 0xC + 4)
                    vt = d.u32(base + 0x94) if 0x80000000 <= base < 0x817FFF00 else 0
                    if vt in ANM_VTS:
                        ev = d.u32(base + k * 0xC + 8)
                        table = d.u32(base + 0x90)
                        n = (ev - table - 8) // 0x20 if table else -1
                        f0, f1 = struct.unpack(">ff", d.read(ev + 4, 8)) if d.is_valid_pointer(ev) else (0, 0)
                        owners = [a - 0x80 for a in refs(raw, base)]
                        who = ", ".join(f"{o:08X} {vt_name(d, o)}" for o in owners) or "aucun acteur trouvé"
                        print(f"    {ANM_VTS[vt]} @{base:08X} empl.{k} év.{n} trames {f0:g}..{f1:g} "
                              f"boucles {d.u32(base + 0x84)} ; porté par : {who}", flush=True)
                        break
                else:
                    continue
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
