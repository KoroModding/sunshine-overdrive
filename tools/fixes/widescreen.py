"""Écran large 16:9 — code Gecko « Widescreen [gamemasterplc] » converti en [OnFrame].

Source : Sys/GameSettings/GMSE01.ini livré avec Dolphin (E:/Dolphin/Dolphin-x64),
section [Gecko], recopié tel quel ci-dessous. Pas de retouche du contenu.

Pourquoi une conversion
=======================
La section [Gecko] n'a jamais chargé sur ce poste (docs/00-journal.md), et le
gestionnaire de codes Gecko s'installe en 0x80001800–0x80003000 — la zone où
vivent les routines du profil : l'activer les écraserait. Le code n'utilise
que deux types, tous deux exprimables en écritures [OnFrame] :
    04AAAAAA VVVVVVVV   écriture 32 bits de VVVVVVVV en 0x80AAAAAA ;
    C2AAAAAA NNNNNNNN   insertion : N lignes de 8 octets d'assembleur, dont le
                        dernier mot (00000000) reçoit le retour ; l'instruction
                        en 0x80AAAAAA devient un saut vers le bloc.
Le bloc C2 est posé dans la zone 0x80001E00–0x80001FFF (relevée nulle en jeu),
son dernier mot remplacé par `b 0x80AAAAAA+4`. Les branchements internes des
blocs sont relatifs et restent justes (bloc recopié d'un seul tenant).

Vérifié dans le DOL (2026-09-26) : aux 12 sites C2, l'instruction d'origine
figure dans le bloc (le code la réexécute) ; les littéraux visés valent 600.0
(largeurs → 800 / 700) et 4/3 en 0x80412408 (→ 16/9). Le code vise donc bien
GMSE01. Effet visuel NON vérifié par nous : c'est le code de référence de
Dolphin, repris à l'identique.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_caves import assemble, words, listing  # noqa: E402

CAVE_START = 0x80001E00
CAVE_END = 0x80002000          # exclusif ; fader commence en 0x80002000

GECKO = """
04416758 44480000
044123E8 442F0000
04416620 442F0000
04176AA4 C002B83C
0429B974 C002B83C
04176C40 C002B83C
04176FF4 C002B83C
04177198 C002B83C
04412408 3FE38E39
04416B74 3F9A7643
0429610C 380002EA
042960A0 3860FF96
C214EF74 00000002
3B20FFA9 93380004
931F0140 00000000
C214EE24 00000002
3B20FFA9 93380004
931F0108 00000000
C214F09C 00000002
3860FFA9 90780004
931F0160 00000000
C214F308 00000002
3BA00251 93B80004
931F02F8 00000000
C214F70C 00000002
3860FFA9 90780004
931F0400 00000000
C214F830 00000002
3860FFA9 90780004
931F042C 00000000
C214F93C 00000002
3860FFA9 90780004
931F0450 00000000
C214D8EC 00000002
38800251 9081056C
807F02A0 00000000
0414E7D4 3880023C
C22CB330 00000004
2C00019F 40820008
38000203 2C00018D
40820008 380001F1
901F0014 00000000
C2156004 00000004
809F0018 38A0EC78
90A40014 7CA500D0
90A4001C 38800000
60000000 00000000
C214F114 00000002
3BA00258 93B80004
931F01C4 00000000
C2363138 00000009
80ED8D08 800701E8
540C24B6 2C030000
41820030 7C032A14
7C006000 41820024
5580F87E 7C601850
1C630003 1CA50003
7C631670 54A5F0BE
7C630194 7C630214
60000000 00000000
"""


def parse() -> tuple[list[tuple[int, int]], list[tuple[int, list[int]]]]:
    """(écritures 04, insertions C2 (site, mots du bloc))."""
    vals = [int(x, 16) for x in GECKO.split()]
    writes, inserts = [], []
    i = 0
    while i < len(vals):
        head, arg = vals[i], vals[i + 1]
        kind, addr = head >> 24, 0x80000000 | (head & 0x01FFFFFF)
        i += 2
        if kind == 0x04:
            writes.append((addr, arg))
        elif kind == 0xC2:
            body = vals[i:i + 2 * arg]
            assert body[-1] == 0, f"bloc C2 {addr:08X} : dernier mot non nul"
            inserts.append((addr, body))
            i += 2 * arg
        else:
            raise ValueError(f"type Gecko {kind:02X} non pris en charge")
    return writes, inserts


def blocks() -> list[tuple[int, bytes, int]]:
    _, inserts = parse()
    out, addr = [], CAVE_START
    for site, body in inserts:
        code = b"".join(w.to_bytes(4, "big") for w in body[:-1])
        code += assemble(f"b {site + 4:#x}", addr + len(code))
        out.append((addr, code, site))
        addr += len(code)
    return out


def build() -> list[tuple[int, int]]:
    writes, _ = parse()
    patches: list[tuple[int, int]] = []
    sites: list[tuple[int, int]] = []
    for addr, code, site in blocks():
        assert addr + len(code) <= CAVE_END, "blocs hors zone"
        patches += words(addr, code)
        sites += words(site, assemble(f"b {addr:#x}", site))
    return patches + writes + sites


if __name__ == "__main__":
    from dol import Dol
    dol = Dol(Path(__file__).resolve().parents[2] / "work" / "dol" / "GMSE01.dol")
    for addr, code, site in blocks():
        orig = dol.u32(site)
        body = [int.from_bytes(code[i:i + 4], "big") for i in range(0, len(code), 4)]
        assert orig in body, f"{site:08X} : instruction d'origine {orig:08X} absente du bloc"
        print(f"; bloc pour {site:08X} (origine {orig:08X})")
        print(listing(addr, code))
    print(len(build()), "mots")
