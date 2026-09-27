"""Relève en continu les effets sonores (SE) présents dans la couche JAI.

Sert à diagnostiquer un son qui ne se fait plus entendre : on voit s'il est
demandé (présent dans la liste), dans quel état il est, et combien de temps il
y reste. Chaque changement est journalisé avec un horodatage.

Chemin des données (Graffito-Decomp, JAIBasic.hpp / JAIData.hpp / JAISound.hpp) :
    gpMSound (0x8040E17C) : MSound, qui hérite de JAIBasic
    JAIBasic+0x00         : JAIData*
    JAIData+0x1E8         : JAILinkBuffer[catégories], 0xC octets chacun ;
                            +0x4 = tête de la liste des SE actifs
    JAISound+0x30         : suivant ; +0x1 état ; +0x2 durée de vie ; +0x8 id
    nombre de catégories  : *(*(0x8040E430)) + 0x89   (getParamSeCategoryMax)

Usage
-----
    python tools/watch_se.py [durée-en-secondes]      (défaut 60)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MSOUND = 0x8040E17C


def snapshot(d: Dolphin) -> dict[tuple[int, int], tuple[int, int, int]]:
    """{(adresse JAISound, id): (catégorie, état, durée de vie)}"""
    data = d.u32(d.u32(GP_MSOUND))
    buffers = d.u32(data + 0x1E8)
    categories = d.u8(d.u32(d.u32(0x8040E430)) + 0x89)
    out = {}
    for cat in range(categories):
        it = d.u32(buffers + 0xC * cat + 4)
        for _ in range(64):                         # garde-fou contre une liste corrompue
            if not d.is_valid_pointer(it):
                break
            out[(it, d.u32(it + 8))] = (cat, d.u8(it + 1), d.u8(it + 2))
            it = d.u32(it + 0x30)
    return out


def main(argv: list[str]) -> int:
    duration = float(argv[1]) if len(argv) > 1 else 60.0
    d = Dolphin()
    t0 = time.perf_counter()
    previous: dict = {}
    print(f"Relevé des SE pendant {duration:.0f} s (changements seulement)")
    while (now := time.perf_counter() - t0) < duration:
        current = snapshot(d)
        for key in current.keys() - previous.keys():
            cat, state, life = current[key]
            print(f"{now:7.3f}  +  id {key[1]:08X}  cat {cat}  état {state}  vie {life}  @{key[0]:08X}")
        for key in previous.keys() - current.keys():
            print(f"{now:7.3f}  -  id {key[1]:08X}")
        for key in current.keys() & previous.keys():
            if current[key][1] != previous[key][1]:
                print(f"{now:7.3f}  ~  id {key[1]:08X}  état {previous[key][1]} -> {current[key][1]}")
        previous = current
        time.sleep(0.004)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
