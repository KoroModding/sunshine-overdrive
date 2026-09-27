"""Read a GameCube disc image (GCM/ISO): header, FST, DOL extraction.

Format documented in YAGCD (Yet Another GameCube Documentation), chapter 13.
Everything is big-endian.

Image layout
------------
    0x000  bootinfo   : disc identifiers
    0x400  bi2        : boot parameters ("bi2.bin")
    0x420  u32        : offset of main.dol in the image
    0x424  u32        : offset of the FST (File String Table)
    0x428  u32        : FST size
    0x42C  u32        : maximum FST size (multi-disc)

Command line
------------
    python gciso.py header <iso>          print the header
    python gciso.py dol    <iso> <output> extract main.dol
    python gciso.py fst    <iso>          list the file tree
    python gciso.py extract <iso> <path-in-iso> <output>

See docs/03-outillage.md for the role of this module in the project.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# Present at 0x1C on every valid GameCube disc. Tells a GCM image apart from a
# Wii image (magic 0x5D1C9EA3 at 0x18) or an arbitrary file.
GAMECUBE_MAGIC = 0xC2339F3D

OFF_GAME_ID = 0x000
OFF_MAGIC = 0x01C
OFF_TITLE = 0x020
OFF_DOL_OFFSET = 0x420
OFF_FST_OFFSET = 0x424
OFF_FST_SIZE = 0x428


@dataclass(frozen=True)
class DiscHeader:
    """GameCube disc image header."""

    game_id: str  # e.g. "GMSE01": GMS = Sunshine, E = NTSC-U, 01 = Nintendo
    maker: str
    version: int
    title: str
    dol_offset: int
    fst_offset: int
    fst_size: int

    @property
    def region(self) -> str:
        """Region derived from the 4th character of the game ID."""
        return {
            "E": "NTSC-U (Amérique du Nord)",
            "P": "PAL (Europe)",
            "J": "NTSC-J (Japon)",
            "U": "PAL (Australie)",
        }.get(self.game_id[3:4], "inconnue")


@dataclass(frozen=True)
class FstEntry:
    """A File String Table entry: file or directory."""

    path: str
    is_dir: bool
    offset: int  # offset in the image (files only)
    size: int  # size in bytes (files only)


def read_header(iso: Path) -> DiscHeader:
    """Read and validate a disc image header.

    Raises ValueError if the GameCube magic is missing, rather than silently
    producing nonsense offsets further down.
    """
    with iso.open("rb") as f:
        raw = f.read(0x440)

    (magic,) = struct.unpack_from(">I", raw, OFF_MAGIC)
    if magic != GAMECUBE_MAGIC:
        raise ValueError(
            f"{iso.name} : magic GameCube absent "
            f"(lu 0x{magic:08X}, attendu 0x{GAMECUBE_MAGIC:08X}). "
            "Image Wii, image compressée (RVZ/CISO) ou fichier corrompu ?"
        )

    game_id = raw[OFF_GAME_ID : OFF_GAME_ID + 4].decode("ascii")
    maker = raw[OFF_GAME_ID + 4 : OFF_GAME_ID + 6].decode("ascii")
    title = raw[OFF_TITLE : OFF_TITLE + 0x60].split(b"\0", 1)[0].decode("latin-1")
    dol_offset, fst_offset, fst_size = struct.unpack_from(">III", raw, OFF_DOL_OFFSET)

    return DiscHeader(
        game_id=game_id + maker,
        maker=maker,
        version=raw[7],
        title=title,
        dol_offset=dol_offset,
        fst_offset=fst_offset,
        fst_size=fst_size,
    )


def dol_size(iso: Path, dol_offset: int) -> int:
    """Size of main.dol.

    The disc header does not store it: it is the largest (offset + size) among
    the 18 sections declared in the DOL header.
    """
    with iso.open("rb") as f:
        f.seek(dol_offset)
        hdr = f.read(0x100)

    offsets = struct.unpack_from(">18I", hdr, 0x00)
    sizes = struct.unpack_from(">18I", hdr, 0x90)
    end = max(
        (off + size for off, size in zip(offsets, sizes) if off and size),
        default=0x100,
    )
    return end


def extract_dol(iso: Path, out: Path) -> int:
    """Extract main.dol to `out`. Returns the number of bytes written."""
    header = read_header(iso)
    size = dol_size(iso, header.dol_offset)

    with iso.open("rb") as f:
        f.seek(header.dol_offset)
        data = f.read(size)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return len(data)


def read_fst(iso: Path) -> list[FstEntry]:
    """Decode the FST into a flat list of files and directories.

    Entry layout (12 bytes):
        +0  u8   type: 0 = file, 1 = directory
        +1  u24  name offset in the string table
        +4  u32  file -> data offset; directory -> parent index
        +8  u32  file -> size; directory -> index of the next entry after it

    The string table starts right after the `count` entries; `count` is read
    from field +8 of the root entry (index 0).
    """
    header = read_header(iso)
    with iso.open("rb") as f:
        f.seek(header.fst_offset)
        fst = f.read(header.fst_size)

    (count,) = struct.unpack_from(">I", fst, 8)
    strings = fst[count * 12 :]

    def name_at(offset: int) -> str:
        return strings[offset : strings.index(b"\0", offset)].decode("latin-1")

    entries: list[FstEntry] = []
    # Stack of open directories: (path, end index). A directory entry declares
    # the index where its contents end, so the tree is rebuilt in one linear
    # pass.
    stack: list[tuple[str, int]] = [("", count)]

    for i in range(1, count):
        flags, name_hi, name_lo, arg1, arg2 = struct.unpack_from(">BBHII", fst, i * 12)
        name_offset = (name_hi << 16) | name_lo
        name = name_at(name_offset)

        while len(stack) > 1 and i >= stack[-1][1]:
            stack.pop()

        path = f"{stack[-1][0]}/{name}"
        if flags & 1:
            entries.append(FstEntry(path, True, 0, 0))
            stack.append((path, arg2))
        else:
            entries.append(FstEntry(path, False, arg1, arg2))

    return entries


def extract_file(iso: Path, disc_path: str, out: Path) -> int:
    """Extract a file from the image by its FST path (e.g. "/default.dol")."""
    wanted = disc_path if disc_path.startswith("/") else "/" + disc_path
    for entry in read_fst(iso):
        if not entry.is_dir and entry.path.lower() == wanted.lower():
            with iso.open("rb") as f:
                f.seek(entry.offset)
                data = f.read(entry.size)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            return len(data)
    raise FileNotFoundError(f"{disc_path} absent de {iso.name}")


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    command, iso = argv[1], Path(argv[2])

    if command == "header":
        h = read_header(iso)
        print(f"Identifiant  : {h.game_id}")
        print(f"Région       : {h.region}")
        print(f"Titre        : {h.title}")
        print(f"Révision     : {h.version}")
        print(f"main.dol     : offset 0x{h.dol_offset:08X}, taille {dol_size(iso, h.dol_offset)} o")
        print(f"FST          : offset 0x{h.fst_offset:08X}, taille 0x{h.fst_size:X}")

    elif command == "dol":
        written = extract_dol(iso, Path(argv[3]))
        print(f"{written} octets écrits dans {argv[3]}")

    elif command == "fst":
        for entry in read_fst(iso):
            if entry.is_dir:
                print(f"     {'':>10}  {entry.path}/")
            else:
                print(f"{entry.offset:#010x} {entry.size:>10}  {entry.path}")

    elif command == "extract":
        written = extract_file(iso, argv[3], Path(argv[4]))
        print(f"{written} octets écrits dans {argv[4]}")

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
