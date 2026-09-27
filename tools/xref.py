"""Cross-references: who reads, writes or calls a given address.

The DOL has no relocations and no symbol table, so there is no reference
index. This module rebuilds one by scanning the executable sections and
decoding the three ways CodeWarrior-generated PowerPC code names an address.

1. Small-data D-form: `lfs f0, -0x3e8(r2)`.
   The target is `base(rA) + signed displacement`, where r2 and r13 are bases
   set once by `__init_registers`. All float literals use this form, so it is
   the one that matters for this project. Exact detection, no false positives.

2. lis/addi or lis/ori pair: `lis r3, 0x8041 ; addi r3, r3, 0x4904`.
   Used for addresses outside small-data range. Only adjacent pairs on the
   same register are examined; if the compiler interleaves instructions
   between the two halves, the reference is missed. Every pair found is
   certain, but the list may be incomplete: an empty result proves nothing.

3. Branches: `bl function`. PC-relative, 26 or 16 bits.

Command line
------------
    python xref.py <dol> <map> <address-or-symbol>
    python xref.py work/dol/GMSE01.dol work/maps/us.map 0x80414904

See docs/03-outillage.md.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dol import Dol  # noqa: E402
from disasm import AnnotatedDisassembler, resolve  # noqa: E402
from symbols import SymbolTable  # noqa: E402

# D-form opcodes (signed 16-bit displacement + base register) that access
# memory or compute an address.
_D_FORM = {
    14: "addi", 24: "ori",
    32: "lwz", 33: "lwzu", 34: "lbz", 35: "lbzu",
    36: "stw", 37: "stwu", 38: "stb", 39: "stbu",
    40: "lhz", 41: "lhzu", 42: "lha", 43: "lhau",
    44: "sth", 45: "sthu",
    48: "lfs", 49: "lfsu", 50: "lfd", 51: "lfdu",
    52: "stfs", 53: "stfsu", 54: "stfd", 55: "stfdu",
}


@dataclass(frozen=True)
class Xref:
    """A reference to the searched address."""

    address: int  # address of the referencing instruction
    kind: str  # "sdata", "lis+lo" or "branche"
    detail: str


def _sign16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def find_xrefs(dol: Dol, symbols: SymbolTable, target: int) -> list[Xref]:
    """All references to `target` in the executable sections."""
    bases = AnnotatedDisassembler(dol, symbols)
    small_data = {2: bases.r2, 13: bases.r13}

    found: list[Xref] = []

    for section in dol.sections:
        if section.kind != "text":
            continue
        blob = dol.data[section.file_offset : section.file_offset + section.size]

        # Last `lis` seen per register, to match the high/low pair on the next
        # instruction.
        pending: dict[int, tuple[int, int]] = {}  # reg -> (address, high half)

        for offset in range(0, len(blob) - 3, 4):
            (word,) = struct.unpack_from(">I", blob, offset)
            here = section.address + offset
            opcode = word >> 26

            if opcode == 18:  # b / bl / ba / bla
                displacement = word & 0x03FFFFFC
                if displacement & 0x02000000:
                    displacement -= 0x04000000
                absolute = word & 2
                destination = displacement if absolute else here + displacement
                if destination == target:
                    found.append(
                        Xref(here, "branche", "bl" if word & 1 else "b")
                    )
                continue

            if opcode == 16:  # bc: conditional branch
                displacement = word & 0xFFFC
                if displacement & 0x8000:
                    displacement -= 0x10000
                if (displacement if word & 2 else here + displacement) == target:
                    found.append(Xref(here, "branche", "bc"))
                continue

            # lis rD, imm is addis rD, r0, imm: opcode 15 with rA = 0.
            if opcode == 15 and ((word >> 16) & 0x1F) == 0:
                pending[(word >> 21) & 0x1F] = (here, (word & 0xFFFF) << 16)
                continue

            if opcode in _D_FORM:
                rA = (word >> 16) & 0x1F
                displacement = _sign16(word & 0xFFFF)

                if rA in small_data:
                    if small_data[rA] + displacement == target:
                        found.append(
                            Xref(
                                here,
                                "sdata",
                                f"{_D_FORM[opcode]} …, {displacement:#x}(r{rA})",
                            )
                        )
                elif rA in pending:
                    high_address, high = pending[rA]
                    # `ori` combines by OR (unsigned low half), `addi` by
                    # signed addition: both forms occur.
                    combined = (high | (word & 0xFFFF)) if opcode == 24 else (high + displacement)
                    if combined == target:
                        found.append(
                            Xref(
                                high_address,
                                "lis+lo",
                                f"lis r{rA}, {high >> 16:#06x} ; {_D_FORM[opcode]} "
                                f"r{rA}, {word & 0xFFFF:#06x}",
                            )
                        )

            # Any write to the register invalidates the pending `lis`. Only
            # D-forms are decoded here; an X-form write to the register goes
            # unnoticed, hence the incompleteness warning in the module
            # docstring.
            if opcode in _D_FORM and opcode not in (36, 38, 44, 52, 54):
                pending.pop((word >> 21) & 0x1F, None)

    return found


def _main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2

    dol = Dol(Path(argv[1]))
    symbols = SymbolTable.load(Path(argv[2]))
    target = resolve(symbols, argv[3])

    print(f"Références à 0x{target:08X}  ({symbols.label(target)})")
    try:
        raw = dol.u32(target)
        (as_float,) = struct.unpack(">f", struct.pack(">I", raw))
        print(f"Contenu : 0x{raw:08X}   f32 {as_float!r}")
    except ValueError as exc:
        print(f"Contenu : {exc}")
    print()

    refs = find_xrefs(dol, symbols, target)
    if not refs:
        print("Aucune référence trouvée. Attention : l'analyse des paires lis/lo")
        print("est incomplète par construction — un résultat vide ne prouve rien.")
        return 0

    for ref in refs:
        print(f"0x{ref.address:08X}  {ref.kind:<8}  {ref.detail}")
        print(f"            dans {symbols.label(ref.address)}")

    print()
    print(f"{len(refs)} référence(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
