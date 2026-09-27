"""Status and switches of the smoothed-goop module (tools/fixes/goop), game running.

    python tools/goop_ctl.py                 status: config, layers, memory
    python tools/goop_ctl.py smooth on|off   show the smoothed copy or not
    python tools/goop_ctl.py soft on|off     soft edge or not
    python tools/goop_ctl.py model on|off    recompute areas around model tasks or not
The switches live in RAM (0x80002F84 / 0x80002F85 / 0x80002F98, 0 = enabled):
they take effect on the next frame and are lost on restart.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

CFG, ROOTS = 0x80002F80, 0x80002FA0


def main(argv: list[str]) -> int:
    d = Dolphin()
    if len(argv) >= 3 and argv[1] in ("smooth", "soft", "model"):
        off = {"smooth": 4, "soft": 5, "model": 24}[argv[1]]
        d.write(CFG + off, bytes([0 if argv[2] == "on" else 1]))
    magic, ns, nf, nl, free, need, fails, upd = struct.unpack(">IBBHIIII", d.read(CFG, 24))
    print(f"magic={magic:08X} ({'actif' if magic == 0x474F4F50 else 'jamais initialisé'})  "
          f"lissage={'OFF' if ns else 'on'}  bord fondu={'OFF' if nf else 'on'}  "
          f"zones modèle={'OFF' if d.u8(CFG + 24) else 'on'}")
    print(f"couches préparées (cumul)={nl}  échecs={fails}  mises à jour={upd}  "
          f"dernier libre={free/1024:.0f} Ko pour {need/1024:.0f} Ko demandés")
    for i in range(16):
        s = d.u32(ROOTS + 4 * i)
        if not s:
            continue
        layer, mask, disp, tex, orig, new = struct.unpack(">6I", d.read(s, 24))
        w, h, cur = struct.unpack(">3H", d.read(s + 24, 6))
        idx, mfr = d.u8(s + 50), d.u8(s + 48)
        arr = d.u32(tex + 4) if d.is_valid_pointer(tex) else 0
        print(f"  [{i}] couche {layer:08X} idx={idx} {w}x{h} masque={mask:08X} copie={disp:08X} "
              f"curseur={cur} zone-modèle={mfr} texture→{'copie' if arr == new else 'origine' if arr == orig else hex(arr)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
