"""Collect every write of the 120 FPS profile and regenerate deliver/GMSE01.ini.

Sources:
    tools/build_caves.py     particles, JAI port flags
    tools/fixes/*.py         hx, fader, menus, actors, contexts, sound
    below                    nop 0x802FCB24, TModelGate portals

Checks, all blocking:
    - no word at Dolphin's HLE hook addresses (0x800018A8, 0x80002FFC);
    - no address written twice with different values;
    - every site outside the code caves holds a DOL word different from the
      write (otherwise the write has no effect, a sign of a wrong address);
    - every written branch targets an address written by the profile, a map
      symbol, or the instruction after a hooked site. Guards against the
      Keystone bug: after a `slwi`, later branches in the same block were
      computed from a wrong base (2026-09-23).

Every line is CONDITIONAL (`address:dword:value:comparand`): Dolphin only
writes if memory still holds the comparand (the original DOL word, or 0 in
the code caves). Otherwise the PatchEngine rewrites every line on each VI
field and invalidates the matching JIT code each time: with 426 lines, many
in hot code, emulation dropped to 14 VI fields per second instead of 120
(measured 2026-09-23: 14.3 fields/s, 1.00 field per frame; the game was not
at fault). Zero words in the code caves are omitted.

The literal 0x804167B8 is no longer written by the profile: tools/fixes/contexts.py
sets it every frame according to context (30 FPS at boot, logos, intro).

Usage
-----
    python tools/build_profile.py            check and print the [OnFrame] block
    python tools/build_profile.py --write    check and rewrite deliver/GMSE01.ini
    python tools/build_profile.py --write --modules hx,fader
        only these tools/fixes modules (default: all); "--modules none"
        = base profile. "--inconditionnel": lines without comparand, as before
        2026-09-23 (rewritten every VI field). Without the contexts module, the
        literal 0x804167B8 is set to 2.0f by [OnFrame] as before the full pass.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "fixes"))

import build_caves  # noqa: E402
from dol import Dol  # noqa: E402

INI = ROOT / "deliver" / "GMSE01.ini"
MAP = ROOT / "work" / "maps" / "us.map"
DOL = ROOT / "work" / "dol" / "GMSE01.dol"

BASE = [
    (0x802FCB24, 0x60000000),   # waitForRetrace: bl VIWaitForRetrace -> nop
    (0x801EC29C, 0xC002D564),   # TModelGate::loadAfter: +0xD8 <- 0.005f (0x80414104)
]
MODULES = ["hx", "fader", "menus", "actors", "contexts", "sound", "fades", "soundsets", "widescreen", "doppler", "petey", "birds", "eel", "bosses", "goop", "jointcoin", "poink", "loopsnd"]
CAVES = (0x80001800, 0x80003000)


def collect(modules: list[str] = MODULES) -> list[tuple[str, int, int]]:
    out = [("base", a, v) for a, v in BASE]
    if "contexts" not in modules:
        out.insert(0, ("base", 0x804167B8, 0x40000000))
    out += [("build_caves", a, v) for a, v in build_caves.build()[0]]
    for name in modules:
        out += [(name, a, v) for a, v in importlib.import_module(name).build()]
    return out


def declared_targets(modules: list[str] = MODULES) -> set[int]:
    """Branch targets inside a game function, declared explicitly by a module
    (TARGETS attribute) and checked against its listing."""
    out: set[int] = set()
    for name in modules:
        out |= set(getattr(importlib.import_module(name), "TARGETS", ()))
    return out


def symbol_starts() -> set[int]:
    starts = set()
    for line in MAP.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=0x" in line:
            try:
                starts.add(int(line.rsplit("=", 1)[1], 16))
            except ValueError:
                pass
    return starts


def check(entries: list[tuple[str, int, int]], extra: set[int] = frozenset()) -> list[str]:
    errors = []
    seen: dict[int, tuple[str, int]] = {}
    for mod, a, v in entries:
        if a in seen and seen[a][1] != v:
            errors.append(f"conflit {a:08X} : {seen[a][0]}={seen[a][1]:08X} / {mod}={v:08X}")
        seen[a] = (mod, v)

    # HLE hooks Dolphin places in the Gecko handler area, active even without
    # Gecko codes: an instruction there runs emulator code. 0x800018A8
    # (Gecko::ENTRY_POINT) flushes the whole JIT cache on every pass, 8 fields/s
    # during Hx_Circle (2026-09-27); 0x80002FFC (HLE_TRAMPOLINE_ADDRESS)
    # restores LR/SP/PC.
    for a in (0x800018A8, 0x80002FFC):
        if a in seen:
            errors.append(f"{a:08X} ({seen[a][0]}) : adresse de crochet HLE de Dolphin, interdite")

    dol = Dol(DOL)
    sites = {a for _, a, _ in entries if not CAVES[0] <= a < CAVES[1]}
    for a in sites:
        try:
            if dol.u32(a) == seen[a][1]:
                errors.append(f"{a:08X} ({seen[a][0]}) : écriture identique au DOL, sans effet")
        except Exception:
            pass                                    # data outside the file (BSS)

    starts = symbol_starts() | set(extra)
    returns = {a + 4 for a in sites}
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    for a, (mod, v) in seen.items():
        op = v >> 26
        if op == 18:                                # b / bl
            off = v & 0x03FFFFFC
            if off & 0x02000000:
                off -= 0x04000000
            target = (off if v & 2 else a + off) & 0xFFFFFFFF
        elif op == 16:                              # bc
            off = v & 0xFFFC
            if off & 0x8000:
                off -= 0x10000
            target = (off if v & 2 else a + off) & 0xFFFFFFFF
        else:
            continue
        if target in seen or target in starts or target in returns:
            continue
        ins = next(cs.disasm(v.to_bytes(4, "big"), a), None)
        text = f"{ins.mnemonic} {ins.op_str}" if ins else f"{v:08X}"
        errors.append(f"{a:08X} ({mod}) : {text} vise {target:08X}, ni écrit, ni symbole, ni retour")
    return errors


def comparand(dol: Dol, a: int) -> int:
    if CAVES[0] <= a < CAVES[1]:
        return 0
    return dol.u32(a)


def onframe_block(entries, conditional: bool = True) -> str:
    dol = Dol(DOL)
    lines = ["$120FPS [Sunshine Overdrive]"]
    for _, a, v in entries:
        if not conditional:
            lines.append(f"0x{a:08X}:dword:0x{v:08X}")
            continue
        c = comparand(dol, a)
        if v == c:
            continue                                # code cave: zero word already in place
        lines.append(f"0x{a:08X}:dword:0x{v:08X}:0x{c:08X}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    modules = MODULES
    if "--modules" in argv:
        arg = argv[argv.index("--modules") + 1]
        modules = [] if arg == "none" else arg.split(",")
    entries = collect(modules)
    errors = check(entries, declared_targets(modules))
    per_mod: dict[str, int] = {}
    for mod, _, _ in entries:
        per_mod[mod] = per_mod.get(mod, 0) + 1
    print("Mots par source :", ", ".join(f"{k} {v}" for k, v in per_mod.items()), f"— total {len(entries)}")
    if errors:
        print(f"{len(errors)} ERREUR(S) :")
        for e in errors:
            print("  " + e)
        return 1
    print("Contrôles : aucun conflit, aucune écriture sans effet, tous les branchements résolus")
    if "--write" in argv:
        s = INI.read_text(encoding="utf-8")
        i = s.index("[OnFrame]\n") + len("[OnFrame]\n")
        j = s.index("\n[OnFrame_Enabled]")
        s = s[:i] + onframe_block(entries, "--inconditionnel" not in argv) + s[j:]
        INI.write_text(s, encoding="utf-8")
        print(f"{INI} réécrit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
