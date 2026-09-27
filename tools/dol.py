"""Lecture d'un exécutable DOL GameCube : sections, adresses, désassemblage.

Un DOL est un format de chargement minimal : une table de 18 sections
(7 « text » exécutables, 11 « data ») plus une zone BSS, sans relocations et
sans table de symboles. Chaque section porte son offset dans le fichier, son
adresse de chargement en mémoire virtuelle et sa taille.

En-tête DOL (0x100 octets, big-endian)
--------------------------------------
    0x00  u32[7]   offsets fichier des sections text
    0x1C  u32[11]  offsets fichier des sections data
    0x48  u32[7]   adresses de chargement des sections text
    0x64  u32[11]  adresses de chargement des sections data
    0x90  u32[7]   tailles des sections text
    0xAC  u32[11]  tailles des sections data
    0xD8  u32      adresse du BSS
    0xDC  u32      taille du BSS
    0xE0  u32      point d'entrée

Le DOL n'ayant aucun symbole, toute correspondance adresse -> fonction vient
d'une source externe (voir tools/symbols.py). Ce module ne manipule que des
adresses brutes, ce qui le rend indépendant de la région du jeu.

Usage en ligne de commande
--------------------------
    python dol.py sections <dol>
    python dol.py read     <dol> <adresse> [nb-octets]
    python dol.py dis      <dol> <adresse> [nb-instructions]
    python dol.py f32      <dol> <adresse> [nb-flottants]
    python dol.py find     <dol> <octets-hex>       recherche un motif
    python dol.py findf32  <dol> <valeur>           recherche un flottant

Voir docs/03-outillage.md.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

NUM_TEXT = 7
NUM_DATA = 11
NUM_SECTIONS = NUM_TEXT + NUM_DATA


@dataclass(frozen=True)
class Section:
    """Une section chargée du DOL."""

    index: int
    kind: str  # « text » ou « data »
    file_offset: int
    address: int  # adresse virtuelle de chargement
    size: int

    @property
    def end(self) -> int:
        return self.address + self.size

    def contains(self, address: int) -> bool:
        return self.address <= address < self.end


class Dol:
    """Un exécutable DOL chargé en mémoire, adressable par adresse virtuelle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()

        offsets = struct.unpack_from(f">{NUM_SECTIONS}I", self.data, 0x00)
        addresses = struct.unpack_from(f">{NUM_SECTIONS}I", self.data, 0x48)
        sizes = struct.unpack_from(f">{NUM_SECTIONS}I", self.data, 0x90)

        self.sections = [
            Section(
                index=i,
                kind="text" if i < NUM_TEXT else "data",
                file_offset=offsets[i],
                address=addresses[i],
                size=sizes[i],
            )
            for i in range(NUM_SECTIONS)
            # Une section de taille nulle est un emplacement inutilisé de la
            # table, pas une section vide : on l'écarte.
            if sizes[i]
        ]

        self.bss_address, self.bss_size, self.entry_point = struct.unpack_from(
            ">III", self.data, 0xD8
        )

    # -- correspondance adresse virtuelle <-> offset fichier ----------------

    def section_of(self, address: int) -> Section | None:
        """Section contenant `address`, ou None si l'adresse n'est pas chargée."""
        for section in self.sections:
            if section.contains(address):
                return section
        return None

    def to_file_offset(self, address: int) -> int:
        """Convertit une adresse virtuelle en offset dans le fichier DOL."""
        section = self.section_of(address)
        if section is None:
            in_bss = self.bss_address <= address < self.bss_address + self.bss_size
            hint = (
                " (l'adresse tombe dans le BSS : la valeur n'existe qu'à l'exécution, "
                "pas dans le fichier)"
                if in_bss
                else ""
            )
            raise ValueError(f"adresse 0x{address:08X} hors des sections du DOL{hint}")
        return section.file_offset + (address - section.address)

    # -- lectures typées ---------------------------------------------------

    def read(self, address: int, length: int) -> bytes:
        start = self.to_file_offset(address)
        return self.data[start : start + length]

    def u32(self, address: int) -> int:
        return struct.unpack(">I", self.read(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack(">f", self.read(address, 4))[0]

    def f64(self, address: int) -> float:
        return struct.unpack(">d", self.read(address, 8))[0]

    # -- recherche ---------------------------------------------------------

    def find(self, pattern: bytes, kind: str | None = None) -> list[int]:
        """Adresses virtuelles où `pattern` apparaît, éventuellement restreint
        aux sections de type `kind` (« text » ou « data »)."""
        hits: list[int] = []
        for section in self.sections:
            if kind and section.kind != kind:
                continue
            blob = self.data[section.file_offset : section.file_offset + section.size]
            start = 0
            while (found := blob.find(pattern, start)) != -1:
                hits.append(section.address + found)
                start = found + 1
        return hits

    def find_f32(self, value: float) -> list[int]:
        """Adresses alignées sur 4 octets contenant exactement `value` en f32."""
        pattern = struct.pack(">f", value)
        return [a for a in self.find(pattern, kind="data") if a % 4 == 0]

    # -- désassemblage -----------------------------------------------------

    def disassemble(self, address: int, count: int = 16):
        """Désassemble `count` instructions à partir de `address`.

        Retourne une liste de tuples (adresse, octets, mnémonique, opérandes).
        Capstone ne connaît pas les instructions « paired single » du Gekko
        (psq_l, ps_madd…) : celles-ci ressortent en « .long » plutôt que de
        faire échouer le désassemblage.
        """
        from capstone import CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs

        md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
        md.skipdata = True

        blob = self.read(address, count * 4)
        out = []
        for insn in md.disasm(blob, address, count=count):
            out.append((insn.address, insn.bytes, insn.mnemonic, insn.op_str))
        return out


def _format_dis(rows) -> str:
    lines = []
    for address, raw, mnemonic, operands in rows:
        lines.append(f"{address:08X}  {raw.hex().upper():<8}  {mnemonic:<10} {operands}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    command = argv[1]
    dol = Dol(Path(argv[2]))

    if command == "sections":
        print(f"Point d'entrée : 0x{dol.entry_point:08X}")
        print(f"BSS            : 0x{dol.bss_address:08X}  taille 0x{dol.bss_size:X}")
        print()
        print(f"{'#':>2} {'type':<5} {'offset':>10} {'adresse':>10} {'fin':>10} {'taille':>10}")
        for s in dol.sections:
            print(
                f"{s.index:>2} {s.kind:<5} 0x{s.file_offset:08X} "
                f"0x{s.address:08X} 0x{s.end:08X} 0x{s.size:08X}"
            )

    elif command == "read":
        address = int(argv[3], 0)
        length = int(argv[4], 0) if len(argv) > 4 else 16
        blob = dol.read(address, length)
        for i in range(0, len(blob), 16):
            chunk = blob[i : i + 16]
            hexed = " ".join(f"{b:02X}" for b in chunk)
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"{address + i:08X}  {hexed:<47}  {text}")

    elif command == "dis":
        address = int(argv[3], 0)
        count = int(argv[4], 0) if len(argv) > 4 else 16
        print(_format_dis(dol.disassemble(address, count)))

    elif command == "f32":
        address = int(argv[3], 0)
        count = int(argv[4], 0) if len(argv) > 4 else 1
        for i in range(count):
            a = address + i * 4
            print(f"{a:08X}  0x{dol.u32(a):08X}  {dol.f32(a)!r}")

    elif command == "find":
        pattern = bytes.fromhex(argv[3].replace(" ", ""))
        for hit in dol.find(pattern):
            section = dol.section_of(hit)
            print(f"{hit:08X}  (section {section.index}, {section.kind})")

    elif command == "findf32":
        for hit in dol.find_f32(float(argv[3])):
            section = dol.section_of(hit)
            print(f"{hit:08X}  (section {section.index}, {section.kind})")

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
