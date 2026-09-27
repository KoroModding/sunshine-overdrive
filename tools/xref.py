"""Références croisées : qui lit, écrit ou appelle une adresse donnée.

Le DOL n'a ni relocations ni table de symboles : il n'existe aucun index des
références. Ce module reconstruit celui-ci en balayant les sections exécutables
et en décodant les trois façons dont le code PowerPC produit par CodeWarrior
désigne une adresse.

1. **Forme D relative aux petites données** — `lfs f0, -0x3e8(r2)`.
   L'adresse visée est `base(rA) + déplacement-signé`, où r2 et r13 sont des
   bases fixées une fois pour toutes par `__init_registers`. C'est la forme
   utilisée pour tous les littéraux flottants, donc la seule qui compte pour ce
   projet. Détection exacte, sans faux positifs.

2. **Paire lis/addi ou lis/ori** — `lis r3, 0x8041 ; addi r3, r3, 0x4904`.
   Utilisée pour les adresses hors portée des petites données. La détection
   n'examine que des paires adjacentes travaillant sur le même registre ; un
   compilateur qui intercale des instructions entre les deux moitiés échappe à
   l'analyse. Toute paire trouvée est donc certaine, mais la liste peut être
   incomplète — un résultat vide ne prouve rien.

3. **Branchements** — `bl fonction`. Portée relative au PC sur 26 ou 16 bits.

Usage en ligne de commande
--------------------------
    python xref.py <dol> <map> <adresse-ou-symbole>
    python xref.py work/dol/GMSE01.dol work/maps/us.map 0x80414904

Voir docs/03-outillage.md.
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

# Opcodes de forme D (déplacement signé 16 bits + registre de base) qui
# accèdent à la mémoire ou calculent une adresse.
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
    """Une référence trouvée vers l'adresse recherchée."""

    address: int  # où se trouve l'instruction référençante
    kind: str  # « sdata », « lis+lo » ou « branche »
    detail: str


def _sign16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def find_xrefs(dol: Dol, symbols: SymbolTable, target: int) -> list[Xref]:
    """Toutes les références à `target` trouvées dans les sections exécutables."""
    bases = AnnotatedDisassembler(dol, symbols)
    small_data = {2: bases.r2, 13: bases.r13}

    found: list[Xref] = []

    for section in dol.sections:
        if section.kind != "text":
            continue
        blob = dol.data[section.file_offset : section.file_offset + section.size]

        # État de la dernière `lis` vue, par registre : permet de reconnaître la
        # paire haute/basse à l'instruction suivante.
        pending: dict[int, tuple[int, int]] = {}  # reg -> (adresse, moitié haute)

        for offset in range(0, len(blob) - 3, 4):
            (word,) = struct.unpack_from(">I", blob, offset)
            here = section.address + offset
            opcode = word >> 26

            # --- branchements ---------------------------------------------
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

            if opcode == 16:  # bc : branchement conditionnel
                displacement = word & 0xFFFC
                if displacement & 0x8000:
                    displacement -= 0x10000
                if (displacement if word & 2 else here + displacement) == target:
                    found.append(Xref(here, "branche", "bc"))
                continue

            # --- lis : mémorise la moitié haute ---------------------------
            # lis rD, imm est addis rD, r0, imm : opcode 15 avec rA = 0.
            if opcode == 15 and ((word >> 16) & 0x1F) == 0:
                pending[(word >> 21) & 0x1F] = (here, (word & 0xFFFF) << 16)
                continue

            # --- forme D --------------------------------------------------
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
                    # `ori` combine par OU logique (moitié basse non signée),
                    # `addi` par addition signée : les deux formes existent.
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

            # Toute écriture dans le registre invalide la `lis` en attente.
            # On n'invalide que pour les formes D, seules décodées ici ; une
            # instruction de forme X écrivant le registre passerait inaperçue,
            # d'où l'avertissement d'incomplétude en tête de module.
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
