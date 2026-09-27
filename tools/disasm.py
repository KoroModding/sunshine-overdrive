"""Annotated DOL disassembly: symbols, branch targets, literals.

A raw Capstone listing is unreadable for this project: calls are bare
addresses and, above all, float constants show up as `lfs f0, -0x3e8(r2)`
without the address or the value. The Sunshine framerate work is precisely
about those literals.

Three annotations are added:

1. Symbols: each instruction is prefixed by the current symbol, and `b` / `bl`
   targets are resolved to demangled names.

2. Small data: `r2`- and `r13`-relative accesses are resolved to an absolute
   address, and the value there is shown as hex, float and integer. Both
   registers are set once by `__init_registers` and never change; their
   values are read from the DOL rather than hardcoded, which keeps the module
   region-independent.

   PowerPC EABI:
       r2  base of `.sdata2`: read-only small data (literals)
       r13 base of `.sdata`:  read/write small data

3. Function bounds: the listing stops at the next symbol, or after a `blr`
   not followed by reachable code, depending on the mode.

Command line
------------
    python disasm.py <dol> <map> <function-or-address> [num-instructions]

    python disasm.py work/dol/GMSE01.dol work/maps/us.map SMSGetVSyncTimesPerSec__Fv
    python disasm.py work/dol/GMSE01.dol work/maps/us.map 0x802FC9A4 80

See docs/03-outillage.md.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dol import Dol  # noqa: E402
from symbols import SymbolTable, demangle  # noqa: E402

# Instructions whose memory operand targets small data when the base register
# is r2 or r13.
_SDATA_LOADS = {
    "lfs", "lfd", "lwz", "lhz", "lha", "lbz", "stw", "sth", "stb", "stfs", "stfd",
    "addi", "lwzu", "stwu",
}

# Branches whose single operand is an absolute address (Capstone already
# applies the PC-relative displacement).
_BRANCHES = {"b", "bl", "ba", "bla", "beq", "bne", "bge", "ble", "bgt", "blt", "bdnz"}


class AnnotatedDisassembler:
    """Annotated listing of a DOL range."""

    def __init__(self, dol: Dol, symbols: SymbolTable) -> None:
        self.dol = dol
        self.symbols = symbols
        self.r2, self.r13 = self._read_sdata_bases()

    def _init_registers_address(self) -> int:
        """Address of `__init_registers`.

        Taken from the map when present. Otherwise derived from the entry
        point, whose first instruction is `bl __init_registers`. The fallback
        allows analysing a DOL with no map (PAL, or any uncovered revision).
        """
        address = self.symbols.address_of("__init_registers")
        if address is not None:
            return address

        (word,) = struct.unpack(">I", self.dol.read(self.dol.entry_point, 4))
        if (word >> 26) != 18 or not (word & 1):  # expected: bl (opcode 18, LK=1)
            raise ValueError(
                f"le point d'entrée 0x{self.dol.entry_point:08X} ne commence pas "
                "par un « bl » : impossible de localiser __init_registers"
            )
        displacement = word & 0x03FFFFFC
        if displacement & 0x02000000:
            displacement -= 0x04000000
        return self.dol.entry_point + displacement

    def _read_sdata_bases(self) -> tuple[int, int]:
        """Read r2 and r13 from `__init_registers`.

        Each base is loaded with the canonical `lis rX, hi ; ori rX, rX, lo`
        pair. Decoding them instead of hardcoding the addresses makes the tool
        work on PAL and JP DOLs too.
        """
        address = self._init_registers_address()
        blob = self.dol.read(address, 0x20)
        bases: dict[int, int] = {}
        for i in range(0, len(blob) - 4, 4):
            (word,) = struct.unpack_from(">I", blob, i)
            (nxt,) = struct.unpack_from(">I", blob, i + 4)
            # lis rD, imm  == addis rD, r0, imm  -> opcode 15, rA = 0
            if (word >> 26) != 15 or ((word >> 16) & 0x1F) != 0:
                continue
            reg = (word >> 21) & 0x1F
            # ori rD, rD, imm -> opcode 24, source == destination == reg
            if (nxt >> 26) != 24 or ((nxt >> 21) & 0x1F) != reg or ((nxt >> 16) & 0x1F) != reg:
                continue
            bases[reg] = ((word & 0xFFFF) << 16) | (nxt & 0xFFFF)

        if 2 not in bases or 13 not in bases:
            raise ValueError(
                f"bases r2/r13 introuvables dans __init_registers @ 0x{address:08X} "
                f"(décodé : {bases})"
            )
        return bases[2], bases[13]

    def _describe_value(self, address: int) -> str:
        """Describe the data at `address` as hex, float and signed int.

        All three are shown because nothing in the instruction says which is
        right: `lwz` on a float is common in copy code.
        """
        try:
            raw = self.dol.u32(address)
        except ValueError as exc:
            return f"-> 0x{address:08X}  ({exc})"

        (as_float,) = struct.unpack(">f", struct.pack(">I", raw))
        signed = raw - (1 << 32) if raw & 0x80000000 else raw
        label = self.symbols.at(address)
        name = f"  {label.name}" if label else ""
        return f"-> 0x{address:08X} = 0x{raw:08X}  f32 {as_float:<14.9g} i32 {signed}{name}"

    def _annotate(self, address: int, mnemonic: str, operands: str) -> str:
        """Comment for an instruction, or an empty string."""
        if mnemonic in _BRANCHES and operands.startswith("0x"):
            try:
                target = int(operands.split(",")[-1].strip(), 16)
            except ValueError:
                return ""
            return f"-> {self.symbols.label(target)}"

        if mnemonic in _SDATA_LOADS:
            for register, base in (("r2", self.r2), ("r13", self.r13)):
                marker = f"({register})"
                if operands.endswith(marker):
                    displacement = operands.rsplit(",", 1)[-1][: -len(marker)].strip()
                    try:
                        offset = int(displacement, 0)
                    except ValueError:
                        return ""
                    return self._describe_value(base + offset)
        return ""

    def listing(self, start: int, count: int | None = None, stop_at_symbol: bool = True) -> str:
        """Annotated listing from `start`.

        If `count` is None, disassemble up to the next symbol, i.e. the whole
        function when the map is complete.
        """
        if count is None:
            following = [a for a in self.symbols._addresses if a > start]
            end = following[0] if following else start + 0x400
            count = min((end - start) // 4, 4096)

        lines: list[str] = []
        current = self.symbols.at(start)
        if current:
            lines.append(f"; {demangle(current.name)}")
            lines.append(f"; {current.name}  @ 0x{current.address:08X}")
            lines.append("")

        for address, raw, mnemonic, operands in self.dol.disassemble(start, count):
            entry = self.symbols.at(address)
            if entry and address != start:
                if stop_at_symbol:
                    break
                lines.append("")
                lines.append(f"; {demangle(entry.name)}")

            comment = self._annotate(address, mnemonic, operands)
            text = f"{address:08X}  {raw.hex().upper():<8}  {mnemonic:<9} {operands}"
            lines.append(f"{text:<50}  ; {comment}" if comment else text)

        return "\n".join(lines)


def resolve(symbols: SymbolTable, target: str) -> int:
    """Turn a command-line argument into an address.

    Accepts an address ("0x802FC9A4"), an exact mangled symbol, or a name
    substring if it matches exactly one symbol.
    """
    try:
        return int(target, 0)
    except ValueError:
        pass

    if (symbol := symbols.by_name(target)) is not None:
        return symbol.address

    matches = symbols.search(target)
    if len(matches) == 1:
        return matches[0].address
    if not matches:
        raise SystemExit(f"aucun symbole ne correspond à « {target} »")
    raise SystemExit(
        f"« {target} » est ambigu ({len(matches)} correspondances) :\n"
        + "\n".join(f"  0x{m.address:08X}  {m.name}" for m in matches[:20])
    )


def _main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2

    dol = Dol(Path(argv[1]))
    symbols = SymbolTable.load(Path(argv[2]))
    start = resolve(symbols, argv[3])
    count = int(argv[4], 0) if len(argv) > 4 else None

    print(AnnotatedDisassembler(dol, symbols).listing(start, count))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
