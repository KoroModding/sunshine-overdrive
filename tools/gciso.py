"""Lecture d'une image disque GameCube (GCM/ISO) : en-tête, FST, extraction du DOL.

Format documenté par YAGCD (Yet Another GameCube Documentation), chapitre 13.
Tout est big-endian.

Disposition de l'image
----------------------
    0x000  bootinfo   : identifiants du disque
    0x400  bi2        : paramètres de boot (« bi2.bin »)
    0x420  u32        : offset du fichier main.dol dans l'image
    0x424  u32        : offset de la FST (File String Table)
    0x428  u32        : taille de la FST
    0x42C  u32        : taille maximale de la FST (multi-disque)

Usage en ligne de commande
--------------------------
    python gciso.py header <iso>          affiche l'en-tête
    python gciso.py dol    <iso> <sortie> extrait main.dol
    python gciso.py fst    <iso>          liste l'arborescence des fichiers
    python gciso.py extract <iso> <chemin-dans-iso> <sortie>

Voir docs/03-outillage.md pour le rôle de ce module dans le projet.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# Constante placée en 0x1C de tout disque GameCube valide. Sert de garde-fou :
# elle distingue une image GCM d'une image Wii (magic 0x5D1C9EA3 en 0x18) ou
# d'un fichier quelconque.
GAMECUBE_MAGIC = 0xC2339F3D

# Décalages fixes de l'en-tête disque.
OFF_GAME_ID = 0x000
OFF_MAGIC = 0x01C
OFF_TITLE = 0x020
OFF_DOL_OFFSET = 0x420
OFF_FST_OFFSET = 0x424
OFF_FST_SIZE = 0x428


@dataclass(frozen=True)
class DiscHeader:
    """En-tête d'une image disque GameCube."""

    game_id: str  # p.ex. « GMSE01 » : GMS = Sunshine, E = NTSC-U, 01 = Nintendo
    maker: str
    version: int
    title: str
    dol_offset: int
    fst_offset: int
    fst_size: int

    @property
    def region(self) -> str:
        """Région déduite du 4e caractère de l'identifiant de jeu."""
        return {
            "E": "NTSC-U (Amérique du Nord)",
            "P": "PAL (Europe)",
            "J": "NTSC-J (Japon)",
            "U": "PAL (Australie)",
        }.get(self.game_id[3:4], "inconnue")


@dataclass(frozen=True)
class FstEntry:
    """Une entrée de la File String Table : fichier ou répertoire."""

    path: str
    is_dir: bool
    offset: int  # offset dans l'image (fichiers uniquement)
    size: int  # taille en octets (fichiers uniquement)


def read_header(iso: Path) -> DiscHeader:
    """Lit et valide l'en-tête d'une image disque.

    Lève ValueError si le magic GameCube est absent — mieux vaut échouer ici
    que produire silencieusement des offsets absurdes plus loin.
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
    """Calcule la taille du main.dol.

    L'en-tête disque ne la stocke pas : il faut la déduire en prenant le plus
    grand (offset + taille) parmi les 18 sections déclarées dans l'en-tête DOL.
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
    """Extrait main.dol de l'image vers `out`. Retourne la taille écrite."""
    header = read_header(iso)
    size = dol_size(iso, header.dol_offset)

    with iso.open("rb") as f:
        f.seek(header.dol_offset)
        data = f.read(size)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return len(data)


def read_fst(iso: Path) -> list[FstEntry]:
    """Décode la FST et retourne la liste à plat des fichiers et répertoires.

    Structure d'une entrée (12 octets) :
        +0  u8   type : 0 = fichier, 1 = répertoire
        +1  u24  offset du nom dans la table de chaînes
        +4  u32  fichier -> offset des données ; répertoire -> index du parent
        +8  u32  fichier -> taille ; répertoire -> index de la 1re entrée suivante

    La table de chaînes commence juste après les `count` entrées ; `count` est
    lu dans le champ +8 de l'entrée racine (index 0).
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
    # Pile des répertoires ouverts : (chemin, index de fin). Une entrée de
    # répertoire déclare l'index auquel son contenu s'arrête, ce qui permet de
    # reconstruire l'arborescence en une seule passe linéaire.
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
    """Extrait un fichier de l'image par son chemin FST (p.ex. « /default.dol »)."""
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
