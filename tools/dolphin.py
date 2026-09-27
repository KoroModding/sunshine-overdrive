"""Accès à la mémoire émulée d'un Dolphin en cours d'exécution.

Dolphin projette la MEM1 de la GameCube dans son propre espace d'adressage.
Un processus tiers peut donc la lire et l'écrire par `ReadProcessMemory` /
`WriteProcessMemory`, sans que Dolphin ait à coopérer et sans passer par son
débogueur graphique. C'est le principe de `dolphin-memory-engine`, réimplémenté
ici pour pouvoir scripter les mesures.

Localisation de la MEM1
-----------------------
L'adresse de la projection change à chaque lancement (ASLR) et Dolphin en crée
plusieurs vues alias (« fastmem »). On balaie donc les régions du processus à
la recherche d'une projection assez grande, et on la valide en lisant
**l'en-tête de disque GameCube** qui se trouve toujours en tête de MEM1 :

    0x80000000  identifiant du jeu, 6 octets ASCII — « GMSE01 »
    0x8000001C  magic 0xC2339F3D

Cette validation est décisive : elle distingue la vraie MEM1 de toute autre
projection de taille comparable, et confirme du même coup quelle image est
chargée. Une région qui ne la passe pas est ignorée.

Conventions d'adressage
-----------------------
Les adresses manipulées sont celles vues par le PowerPC : `0x80000000` à
`0x81800000` (24 Mio de MEM1, cachée). Le décalage dans la projection est
l'adresse masquée par `0x01FFFFFF`. Tout est **big-endian**.

Usage en ligne de commande
--------------------------
    python dolphin.py info                         processus, MEM1, jeu chargé
    python dolphin.py read   <adresse> [octets]
    python dolphin.py u32    <adresse> [nombre]
    python dolphin.py f32    <adresse> [nombre]
    python dolphin.py write  <adresse> <octets-hex>
    python dolphin.py deref  <adresse> [offset…]   suit une chaîne de pointeurs

Voir docs/03-outillage.md.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys

# --- API Win32 --------------------------------------------------------------

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

MEM_COMMIT = 0x1000
MEM_MAPPED = 0x40000

# MEM1 de la GameCube : 24 Mio. Dolphin réserve davantage par vue ; on accepte
# donc toute projection au moins aussi grande, la validation par l'en-tête
# faisant le tri.
MEM1_SIZE = 0x1800000
MEM1_BASE = 0x80000000
MEM1_MASK = 0x01FFFFFF

GAMECUBE_MAGIC = 0xC2339F3D


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wt.HANDLE
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.ReadProcessMemory.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_k32.WriteProcessMemory.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_k32.VirtualQueryEx.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION64),
    ctypes.c_size_t,
]


def find_dolphin_pid() -> int:
    """PID du premier processus nommé « Dolphin ». Lève RuntimeError sinon."""
    import subprocess

    output = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    for line in output.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("dolphin"):
            return int(parts[1])
    raise RuntimeError("aucun processus Dolphin.exe трouvé")


class Dolphin:
    """Une instance de Dolphin, avec sa MEM1 localisée et validée."""

    def __init__(self, pid: int | None = None) -> None:
        self.pid = pid if pid is not None else find_dolphin_pid()
        self.handle = _k32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
            | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False, self.pid,
        )
        if not self.handle:
            raise RuntimeError(
                f"OpenProcess a échoué sur le PID {self.pid} "
                f"(erreur {ctypes.get_last_error()}). "
                "Lancer ce script depuis un terminal élevé si Dolphin l'est."
            )
        self.mem1, self.game_id = self._locate_mem1()

    # -- localisation ------------------------------------------------------

    def _raw_read(self, address: int, length: int) -> bytes | None:
        """Lecture brute dans l'espace du processus. None si la lecture échoue."""
        buffer = (ctypes.c_char * length)()
        read = ctypes.c_size_t(0)
        ok = _k32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buffer, length, ctypes.byref(read)
        )
        return buffer.raw[: read.value] if ok and read.value == length else None

    def _locate_mem1(self) -> tuple[int, str]:
        """Balaie les projections et retient celle qui porte un en-tête GameCube.

        Plusieurs vues alias la même mémoire partagée : la première validée
        convient, une écriture dans l'une est visible dans toutes.
        """
        info = MEMORY_BASIC_INFORMATION64()
        address = 0
        candidates: list[tuple[int, str]] = []

        while address < 0x7FFF_FFFF_FFFF:
            if not _k32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(address), ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                break
            if (
                info.State == MEM_COMMIT
                and info.Type == MEM_MAPPED
                and info.RegionSize >= MEM1_SIZE
            ):
                header = self._raw_read(info.BaseAddress, 0x20)
                if header and struct.unpack_from(">I", header, 0x1C)[0] == GAMECUBE_MAGIC:
                    game_id = header[:6].decode("ascii", "replace")
                    candidates.append((info.BaseAddress, game_id))
            address = info.BaseAddress + info.RegionSize

        if not candidates:
            raise RuntimeError(
                "MEM1 introuvable : aucune projection ne porte d'en-tête GameCube. "
                "Un jeu est-il bien démarré (pas seulement la liste de jeux) ?"
            )
        return candidates[0]

    # -- traduction d'adresse ---------------------------------------------

    def _host(self, address: int) -> int:
        """Adresse hôte correspondant à une adresse PowerPC de MEM1."""
        if not (MEM1_BASE <= address < MEM1_BASE + MEM1_SIZE):
            raise ValueError(
                f"0x{address:08X} hors MEM1 "
                f"(0x{MEM1_BASE:08X}–0x{MEM1_BASE + MEM1_SIZE:08X})"
            )
        return self.mem1 + (address & MEM1_MASK)

    # -- lectures ----------------------------------------------------------

    def read(self, address: int, length: int) -> bytes:
        data = self._raw_read(self._host(address), length)
        if data is None:
            raise RuntimeError(f"lecture impossible à 0x{address:08X}")
        return data

    def u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def u16(self, address: int) -> int:
        return struct.unpack(">H", self.read(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack(">I", self.read(address, 4))[0]

    def s32(self, address: int) -> int:
        return struct.unpack(">i", self.read(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack(">f", self.read(address, 4))[0]

    def deref(self, address: int, *offsets: int) -> int:
        """Suit une chaîne de pointeurs : `deref(gp, 0x10, 0x4)`."""
        value = self.u32(address)
        for offset in offsets:
            if not (MEM1_BASE <= value < MEM1_BASE + MEM1_SIZE):
                raise ValueError(f"pointeur nul ou invalide : 0x{value:08X}")
            value = self.u32(value + offset)
        return value

    # -- écritures ---------------------------------------------------------

    def write(self, address: int, data: bytes) -> None:
        written = ctypes.c_size_t(0)
        buffer = (ctypes.c_char * len(data)).from_buffer_copy(data)
        ok = _k32.WriteProcessMemory(
            self.handle, ctypes.c_void_p(self._host(address)), buffer,
            len(data), ctypes.byref(written),
        )
        if not ok or written.value != len(data):
            raise RuntimeError(
                f"écriture impossible à 0x{address:08X} "
                f"(erreur {ctypes.get_last_error()})"
            )

    def write_u32(self, address: int, value: int) -> None:
        self.write(address, struct.pack(">I", value & 0xFFFFFFFF))

    def write_f32(self, address: int, value: float) -> None:
        self.write(address, struct.pack(">f", value))

    def is_valid_pointer(self, value: int) -> bool:
        return MEM1_BASE <= value < MEM1_BASE + MEM1_SIZE


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    command = argv[1]
    dolphin = Dolphin()

    if command == "info":
        print(f"PID        : {dolphin.pid}")
        print(f"MEM1 hôte  : 0x{dolphin.mem1:016X}")
        print(f"Jeu chargé : {dolphin.game_id}")
        title = dolphin.read(0x80000020, 0x40).split(b"\0", 1)[0].decode("latin-1")
        print(f"Titre      : {title}")

    elif command == "read":
        address = int(argv[2], 0)
        length = int(argv[3], 0) if len(argv) > 3 else 32
        blob = dolphin.read(address, length)
        for i in range(0, len(blob), 16):
            chunk = blob[i : i + 16]
            hexed = " ".join(f"{b:02X}" for b in chunk)
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"{address + i:08X}  {hexed:<47}  {text}")

    elif command in ("u32", "f32"):
        address = int(argv[2], 0)
        count = int(argv[3], 0) if len(argv) > 3 else 1
        for i in range(count):
            a = address + i * 4
            print(f"{a:08X}  0x{dolphin.u32(a):08X}  {dolphin.f32(a)!r}")

    elif command == "write":
        address = int(argv[2], 0)
        data = bytes.fromhex(argv[3].replace(" ", ""))
        before = dolphin.read(address, len(data))
        dolphin.write(address, data)
        print(f"0x{address:08X} : {before.hex().upper()} -> {data.hex().upper()}")

    elif command == "deref":
        address = int(argv[2], 0)
        offsets = [int(a, 0) for a in argv[3:]]
        print(f"0x{dolphin.deref(address, *offsets):08X}")

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
