"""Goop lissée : module de profil construit à partir de tools/fixes/goop/goop.c.

Le code C (voir son en-tête) est compilé pour le Gekko avec le clang PowerPC
livré par BetterSunshineEngine (dossier `compiler/`), lié à adresses fixes dans
trois zones libres de la caverne, puis transformé en mots [OnFrame].

    zone D 0x80001AE0–0x80001C00   trampoline, live
    zone A 0x80001F20–0x80002400   goop_init, goop_mark
    zone C 0x800025F0–0x80002A00   set_soft, goop_perform
    zone B 0x80002A40–0x80002E40   smooth_rows, constantes
    état   0x80002F80 goop_cfg (32 o), 0x80002FA0 goop_roots (8 pointeurs)
           — hors profil, zone nulle au démarrage ; 0x80002FFC (crochet HLE)
           n'est pas atteint.

Sites :
    0x801A0EB8  bl initTexImage              -> bl goop_init      (chargement d'une couche)
    0x801A12C8  bl TJointModel::perform      -> bl goop_perform   (chaque passage)
    0x8019ABAC  lwz r9, 8(r3) (pushTask)     -> b goop_push_tramp (chaque tampon)

Compilateur : variable d'environnement PPC_CLANG_DIR (dossier contenant
clang.exe, ld.lld.exe, powerpc-eabi-objcopy.exe). Sans compilateur, le
module réutilise le dernier binaire construit (tools/fixes/goop/*.bin).

    python tools/fixes/goop.py          construit, vérifie, affiche le listing
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "goop"
SRC = HERE / "goop.c"

REGIONS = {                         # section -> (début, fin exclue)
    ".text_d": (0x80001AE0, 0x80001C00),
    ".text_a": (0x80001F20, 0x80002400),
    ".text_c": (0x800025F0, 0x80002A00),
    ".text_b": (0x80002A40, 0x80002E40),
}
LDS = """
SECTIONS {
  .text_d 0x80001AE0 : { *(.text) *(.text.live) }
  .text_a 0x80001F20 : { *(.text.goop_init) *(.text.goop_mark) }
  .text_c 0x800025F0 : { *(.text.set_soft) *(.text.goop_perform) }
  .text_b 0x80002A40 : { *(.text.smooth_rows) *(.text.*) *(.rodata*) *(.sdata2*) *(.data*) *(.sdata*) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.bss*) *(.sbss*) }
}
"""
SYMS = {
    "initTexImage": 0x801A10B4,
    "TJointModel_perform": 0x801880C8,
    "DCStoreRange": 0x803436C0,
    "JKRHeap_sCurrentHeap": 0x8040E294,
    "pushTask_resume": 0x8019ABB0,
    "goop_cfg": 0x80002F80,
    "goop_roots": 0x80002FA0,
    "memcpy": 0x800031F4,
    "memset": 0x80003100,
}
SITES = [                           # (site, mot d'origine, symbole visé, bl ?)
    (0x801A0EB8, 0x480001FD, "goop_init", True),
    (0x801A12C8, 0x4BFE6E01, "goop_perform", True),
    (0x8019ABAC, 0x81230008, "goop_push_tramp", False),
]


def _tool(name: str) -> Path | None:
    d = os.environ.get("PPC_CLANG_DIR")
    if not d:
        return None
    p = Path(d) / name
    return p if p.exists() else None


def compile_() -> None:
    clang, ld, objcopy = _tool("clang.exe"), _tool("ld.lld.exe"), _tool("powerpc-eabi-objcopy.exe")
    if not (clang and ld and objcopy):
        return                                        # binaires en cache
    obj, elf, lds = HERE / "goop.o", HERE / "goop.elf", HERE / "goop.ld"
    lds.write_text(LDS)
    subprocess.run([str(clang), "-target", "powerpc-unknown-eabi", "-mcpu=750", "-Os",
                    "-ffunction-sections", "-fdata-sections", "-ffreestanding", "-fno-builtin",
                    "-nostdlib", "-fno-pic", "-fno-asynchronous-unwind-tables",
                    "-c", str(SRC), "-o", str(obj)], check=True)
    subprocess.run([str(ld), "-T", str(lds), "-e", "goop_init", "-Map", str(HERE / "goop.map"),
                    "-o", str(elf), str(obj)]
                   + [f"--defsym={k}=0x{v:08X}" for k, v in SYMS.items()], check=True)
    for sec in REGIONS:
        subprocess.run([str(objcopy), "-O", "binary", "--only-section=" + sec, str(elf),
                        str(HERE / f"goop{sec.replace('.text', '')}.bin")], check=True)


def _symbols() -> dict[str, int]:
    """Adresses des fonctions liées : relues dans goop.map après compilation et
    conservées dans goop_symbols.json (versionné), pour construire sans compilateur."""
    import json
    js = HERE / "goop_symbols.json"
    mp = HERE / "goop.map"
    if mp.exists() and (not js.exists() or mp.stat().st_mtime >= js.stat().st_mtime):
        out: dict[str, int] = {}
        for line in mp.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[-1] in ("goop_init", "goop_perform", "goop_mark",
                                                    "goop_push_tramp", "smooth_rows", "set_soft", "live"):
                out[parts[-1]] = int(parts[0], 16)
        js.write_text(json.dumps({k: f"0x{v:08X}" for k, v in out.items()}, indent=1))
    return {k: int(v, 16) for k, v in json.loads(js.read_text()).items()}


def build() -> list[tuple[int, int]]:
    compile_()
    words: list[tuple[int, int]] = []
    for sec, (start, end) in REGIONS.items():
        data = (HERE / f"goop{sec.replace('.text', '')}.bin").read_bytes()
        assert start + len(data) <= end, f"{sec} déborde : {start + len(data):#x} > {end:#x}"
        data += bytes(-len(data) % 4)
        words += [(start + i, int.from_bytes(data[i:i + 4], "big")) for i in range(0, len(data), 4)]
    syms = _symbols()
    for site, _orig, target, link in SITES:
        off = syms[target] - site
        assert -0x2000000 <= off < 0x2000000
        words.append((site, (0x48000001 if link else 0x48000000) | (off & 0x03FFFFFC)))
    return words


if __name__ == "__main__":
    import capstone
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dol import Dol
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for site, orig, _t, _l in SITES:
        assert dol.u32(site) == orig, f"{site:08X} : DOL {dol.u32(site):08X} != {orig:08X}"
    words = build()
    bad = []
    for a, w in words:
        i = list(cs.disasm(w.to_bytes(4, "big"), a))
        if i and ("(r2)" in i[0].op_str or "(r13)" in i[0].op_str or "r13" in i[0].op_str.split(", ")[:1]):
            bad.append(f"{a:08X} {i[0].mnemonic} {i[0].op_str}")
    assert not bad, "accès aux petites données : " + "; ".join(bad)
    for sec, (start, end) in REGIONS.items():
        n = len((HERE / f"goop{sec.replace('.text', '')}.bin").read_bytes())
        print(f"{sec}: {start:08X}–{start + n:08X} ({n} o sur {end - start})")
    print("symboles :", {k: hex(v) for k, v in _symbols().items()})
    print(len(words), "mots ; sites vérifiés au DOL ; aucun accès r2/r13")
