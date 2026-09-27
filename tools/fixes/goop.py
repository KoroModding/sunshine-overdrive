"""Smoothed goop: profile module built from tools/fixes/goop/goop.c.

The C code (see its header) is compiled for the Gekko with the PowerPC clang
shipped by BetterSunshineEngine (`compiler/` folder), linked at fixed addresses
into free ranges of the code cave, then turned into [OnFrame] words.

    zone D 0x80001AE0–0x80001C00   trampoline, live
    zone A 0x80001F20–0x80002400   goop_init, goop_mark, goop_mark_model
    zone C 0x800025F0–0x80002A00   set_soft, goop_perform, slot_of
    zone B 0x80002A40–0x80002E40   smooth_rows, mark_rect, model trampoline
    zone E 0x80001CFC–0x80001D80   patch_dl (frozen display lists)
    state  0x80002F80 goop_cfg (32 B), 0x80002FA0 goop_roots (8 pointers)
           outside the profile, zero at boot; 0x80002FFC (HLE hook) is not
           reached.

Sites:
    0x801A0EB8  bl initTexImage              -> bl goop_init      (layer load)
    0x801A12C8  bl TJointModel::perform      -> bl goop_perform   (every pass)
    0x8019ABAC  lwz r9, 8(r3) (pushTask)     -> b goop_push_tramp (every stamp)
    0x8019B120  lhz r0, 0x28(r3) (pushModelStampTask)    -> b goop_model_tramp
                (model tasks: area around the stamp model)

Compiler: environment variable PPC_CLANG_DIR (folder containing clang.exe,
ld.lld.exe, powerpc-eabi-objcopy.exe). Without a compiler, the module reuses
the last built binary (tools/fixes/goop/*.bin).

    python tools/fixes/goop.py          builds, checks, prints the listing
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "goop"
SRC = HERE / "goop.c"

REGIONS = {                         # section -> (start, end exclusive)
    ".text_d": (0x80001AE0, 0x80001C00),
    ".text_a": (0x80001F20, 0x80002400),
    ".text_c": (0x800025F0, 0x80002A00),
    ".text_b": (0x80002A40, 0x80002E40),
    ".text_e": (0x80001CFC, 0x80001D80),     # unused part of the soundsets area; poink at 0x80001D80
}
LDS = """
SECTIONS {
  .text_d 0x80001AE0 : { *(.text) *(.text.live) }
  .text_a 0x80001F20 : { *(.text.goop_init) *(.text.goop_mark) *(.text.goop_mark_model) }
  .text_c 0x800025F0 : { *(.text.set_soft) *(.text.goop_perform) *(.text.slot_of) }
  .text_e 0x80001CFC : { *(.text.patch_dl) }
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
    "modelTask_resume": 0x8019B124,
    "goop_cfg": 0x80002F80,
    "goop_roots": 0x80002FA0,
    "memcpy": 0x800031F4,
    "memset": 0x80003100,
}
SITES = [                           # (site, original word, target symbol, bl?)
    (0x801A0EB8, 0x480001FD, "goop_init", True),
    (0x801A12C8, 0x4BFE6E01, "goop_perform", True),
    (0x8019ABAC, 0x81230008, "goop_push_tramp", False),
    (0x8019B120, 0xA0030028, "goop_model_tramp", False),   # lhz r0, 0x28(r3)
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
        return                                        # cached binaries
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
    """Linked function addresses: read from goop.map after compiling and kept in
    goop_symbols.json (versioned), so the module builds without a compiler."""
    import json
    js = HERE / "goop_symbols.json"
    mp = HERE / "goop.map"
    if mp.exists() and (not js.exists() or mp.stat().st_mtime >= js.stat().st_mtime):
        out: dict[str, int] = {}
        for line in mp.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[-1] in ("goop_init", "goop_perform", "goop_mark",
                                                    "goop_push_tramp", "smooth_rows", "set_soft", "live",
                                                    "goop_mark_model", "goop_model_tramp", "patch_dl", "mark_rect", "slot_of"):
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
