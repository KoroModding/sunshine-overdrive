"""État et interrupteurs du module goop lissée (tools/fixes/goop), jeu en cours.

    python tools/goop_ctl.py                 état : config, couches, mémoire
    python tools/goop_ctl.py smooth on|off   copie lissée affichée ou non
    python tools/goop_ctl.py soft on|off     bord fondu ou non
Les interrupteurs vivent en RAM (0x80002F84 / 0x80002F85, 0 = actif) :
effet à l'image suivante, perdus au redémarrage.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

CFG, ROOTS = 0x80002F80, 0x80002FA0


def main(argv: list[str]) -> int:
    d = Dolphin()
    if len(argv) >= 3 and argv[1] in ("smooth", "soft"):
        d.write(CFG + (4 if argv[1] == "smooth" else 5), bytes([0 if argv[2] == "on" else 1]))
    magic, ns, nf, nl, free, need, fails, upd = struct.unpack(">IBBHIIII", d.read(CFG, 24))
    print(f"magic={magic:08X} ({'actif' if magic == 0x474F4F50 else 'jamais initialisé'})  "
          f"lissage={'OFF' if ns else 'on'}  bord fondu={'OFF' if nf else 'on'}")
    print(f"couches préparées (cumul)={nl}  échecs={fails}  mises à jour={upd}  "
          f"dernier libre={free/1024:.0f} Ko pour {need/1024:.0f} Ko demandés")
    for i in range(8):
        s = d.u32(ROOTS + 4 * i)
        if not s:
            continue
        layer, mask, disp, tex, orig, new = struct.unpack(">6I", d.read(s, 24))
        w, h, cur = struct.unpack(">3H", d.read(s + 24, 6))
        idx = d.u8(s + 39)
        arr = d.u32(tex + 4) if d.is_valid_pointer(tex) else 0
        print(f"  [{i}] couche {layer:08X} idx={idx} {w}x{h} masque={mask:08X} copie={disp:08X} "
              f"curseur={cur} texture→{'copie' if arr == new else 'origine' if arr == orig else hex(arr)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
