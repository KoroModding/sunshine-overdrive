"""Désassemblage annoté du DOL : symboles, cibles de branchement, littéraux.

Un listing Capstone brut est illisible pour ce projet : les appels sont des
adresses nues et, surtout, les constantes flottantes apparaissent sous la forme
`lfs f0, -0x3e8(r2)` sans révéler ni l'adresse ni la valeur. Or tout le travail
sur le framerate de Sunshine porte précisément sur ces littéraux.

Ce module ajoute trois annotations :

1. **Symboles** — chaque instruction est préfixée par le symbole courant, et
   les cibles de `b` / `bl` sont résolues en noms démanglés.

2. **Petites données** — les accès relatifs à `r2` et `r13` sont résolus en
   adresse absolue, et la valeur qui s'y trouve est affichée en hexadécimal,
   en flottant et en entier. Les deux registres sont initialisés une fois pour
   toutes par `__init_registers` et ne changent jamais ensuite ; leurs valeurs
   sont lues dans le DOL plutôt que codées en dur, ce qui rend le module
   indépendant de la région.

   ABI PowerPC EABI :
       r2  base de `.sdata2` — petites données en lecture seule (littéraux)
       r13 base de `.sdata`  — petites données en lecture/écriture

3. **Bornes de fonction** — le listing s'arrête au symbole suivant, ou après un
   `blr` non suivi de code atteignable, selon le mode demandé.

Usage en ligne de commande
--------------------------
    python disasm.py <dol> <map> <fonction-ou-adresse> [nb-instructions]

    python disasm.py work/dol/GMSE01.dol work/maps/us.map SMSGetVSyncTimesPerSec__Fv
    python disasm.py work/dol/GMSE01.dol work/maps/us.map 0x802FC9A4 80

Voir docs/03-outillage.md.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dol import Dol  # noqa: E402
from symbols import SymbolTable, demangle  # noqa: E402

# Instructions dont l'opérande mémoire vise les petites données quand le
# registre de base est r2 ou r13.
_SDATA_LOADS = {
    "lfs", "lfd", "lwz", "lhz", "lha", "lbz", "stw", "sth", "stb", "stfs", "stfd",
    "addi", "lwzu", "stwu",
}

# Branchements dont l'opérande unique est une adresse absolue résolue par
# Capstone (il applique déjà le déplacement relatif au PC).
_BRANCHES = {"b", "bl", "ba", "bla", "beq", "bne", "bge", "ble", "bgt", "blt", "bdnz"}


class AnnotatedDisassembler:
    """Produit un listing annoté d'une plage du DOL."""

    def __init__(self, dol: Dol, symbols: SymbolTable) -> None:
        self.dol = dol
        self.symbols = symbols
        self.r2, self.r13 = self._read_sdata_bases()

    def _init_registers_address(self) -> int:
        """Adresse de `__init_registers`.

        Prise dans la map quand elle s'y trouve. Sinon, on la déduit : la
        première instruction du point d'entrée est un `bl __init_registers`.
        Ce repli permet d'analyser un DOL pour lequel aucune map n'existe —
        c'est le cas de PAL et de toute révision non couverte.
        """
        address = self.symbols.address_of("__init_registers")
        if address is not None:
            return address

        (word,) = struct.unpack(">I", self.dol.read(self.dol.entry_point, 4))
        if (word >> 26) != 18 or not (word & 1):  # attendu : bl (opcode 18, LK=1)
            raise ValueError(
                f"le point d'entrée 0x{self.dol.entry_point:08X} ne commence pas "
                "par un « bl » : impossible de localiser __init_registers"
            )
        displacement = word & 0x03FFFFFC
        if displacement & 0x02000000:
            displacement -= 0x04000000
        return self.dol.entry_point + displacement

    def _read_sdata_bases(self) -> tuple[int, int]:
        """Lit r2 et r13 dans `__init_registers`.

        La fonction charge chaque base par la paire canonique
        `lis rX, hi ; ori rX, rX, lo`. On décode ces quatre instructions
        plutôt que de coder les adresses en dur, pour que l'outil fonctionne
        aussi sur les DOL PAL et JP.
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
        """Décrit la donnée à `address` : hexa, flottant et entier signé.

        Les trois interprétations sont montrées côte à côte parce que rien dans
        l'instruction ne dit laquelle est la bonne — `lwz` sur un flottant est
        courant dans du code de copie.
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
        """Commentaire à accoler à une instruction, ou chaîne vide."""
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
        """Listing annoté à partir de `start`.

        Si `count` est None, désassemble jusqu'au symbole suivant — ce qui
        correspond à la fonction entière quand la map est complète.
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
    """Convertit un argument de ligne de commande en adresse.

    Accepte une adresse (« 0x802FC9A4 »), un symbole manglé exact, ou une
    sous-chaîne de nom si elle ne correspond qu'à un seul symbole.
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
