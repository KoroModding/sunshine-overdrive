"""Prototype « bord fondu » de la goop, appliqué EN DIRECT dans la mémoire du jeu.

Le matériau de la goop est reconstruit à partir de ses blocs J3D à chaque
dessin (paquets non verrouillés, J3DJoint::entryIn → makeDisplayList ; voir
tools/goop_inspect.py). Modifier les blocs prend donc effet à l'image suivante,
sans redémarrer : de quoi comparer des réglages à l'œil.

Matériau d'origine (identique sur les 9 matériaux de Bianco, relu) :
    étage 0 alpha : PREV = TEXA (masque)
    étage 1 alpha : PREV = (APREV + 0,5) × 0,5        mot BP C3 31FF80
    étage 2 alpha : PREV = APREV                       mot BP C5 00FF80
    PE : alpha compare GEQUAL 128 AND LEQUAL 255, blend NONE (opaque)
→ seuil net à masque = 0,5 : le contour est l'isoligne 0,5 du masque
  bilinéaire, d'où les marches.

Prototype : rampe d'opacité centrée sur ce même seuil, mélange activé.
    étage 1 alpha : PREV = (APREV − 0,5) × K   sans saturation (K = 2 ou 4)
    étage 2 alpha : PREV = clamp(APREV + 0,5)
    PE : blend SRCALPHA / INVSRCALPHA, alpha compare ref0 = 1
K = 4 : rampe sur masque 96–160 (bord doux étroit) ; K = 2 : 64–192 (large).
Le contour reste l'isoligne 0,5 ; seul son aspect change (piste 1 du plan).
Le masque (données de gameplay) n'est jamais touché.

Usage
-----
    python tools/goop_soft.py status
    python tools/goop_soft.py apply [--k 2|4]     sauvegarde puis applique
    python tools/goop_soft.py restore             remet les octets d'origine
Sauvegarde : work/goop-soft-backup.json (par adresse). Un changement de niveau
recharge les modèles : rien à restaurer dans ce cas.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402

BACKUP = Path(__file__).resolve().parent.parent / "work" / "goop-soft-backup.json"

VT_LAYER = 0x803C2160
VT_TEVBLOCK4 = 0x803E0AB0
VT_PEBLOCK_FULL = 0x803E0968

ST1_ALPHA = 0x29          # TevBlock4 : +0x1D + 8·s + 4, s = 1 (id BP + 3 octets)
ST2_ALPHA = 0x31          # s = 2
ORIG_ST1 = bytes.fromhex("C331FF80")
ORIG_ST2 = bytes.fromhex("C500FF80")
PE_REF0 = 0x0A
PE_BLEND = 0x0C           # type, src, dst, logic
ORIG_BLEND = bytes([0, 1, 0, 3])   # NONE, ONE, ZERO, COPY

SCALE = {1: 0, 2: 1, 4: 2}  # champ scale du mot alpha TEV


def alpha_env(d: int, bias: int, scale: int, clamp: int, a=7, b=7, c=7, op=0, dest=0) -> int:
    return ((dest << 22) | (scale << 20) | (clamp << 19) | (op << 18) | (bias << 16)
            | (a << 13) | (b << 10) | (c << 7) | (d << 4))


def materials(dm: Dolphin) -> list[tuple[int, int, int]]:
    """(matériau, bloc TEV, bloc PE) de toutes les couches TPollutionLayer."""
    raw = dm.read(0x80000000, 0x01800000)
    key = struct.pack(">I", VT_LAYER)
    out, i = [], raw.find(key)
    while i != -1:
        if i % 4 == 0:
            layer = 0x80000000 + i
            mdata = dm.u32(layer + 0x24)
            if dm.is_valid_pointer(mdata):
                n, tab = dm.u16(mdata + 0x24), dm.u32(mdata + 0x28)
                for k in range(n):
                    mat = dm.u32(tab + 4 * k)
                    tev, pe = dm.u32(mat + 0x28), dm.u32(mat + 0x30)
                    if dm.u32(tev) == VT_TEVBLOCK4 and dm.u32(pe) == VT_PEBLOCK_FULL:
                        out.append((mat, tev, pe))
        i = raw.find(key, i + 4)
    return out


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    k = int(argv[argv.index("--k") + 1]) if "--k" in argv else 4
    dm = Dolphin()
    mats = materials(dm)
    print(f"{len(mats)} matériau(x) de goop")
    if cmd == "status":
        for mat, tev, pe in mats:
            s1, s2 = dm.read(tev + ST1_ALPHA, 4), dm.read(tev + ST2_ALPHA, 4)
            state = "origine" if (s1, s2) == (ORIG_ST1, ORIG_ST2) else "MODIFIÉ"
            print(f"  {mat:08X}  ét1={s1.hex().upper()} ét2={s2.hex().upper()} "
                  f"ref0={dm.u8(pe + PE_REF0)} blend={dm.read(pe + PE_BLEND, 4).hex()}  {state}")
        return 0
    if cmd == "apply":
        backup = json.loads(BACKUP.read_text()) if BACKUP.exists() else {}
        st1 = bytes([0xC3]) + alpha_env(d=0, bias=2, scale=SCALE[k], clamp=0).to_bytes(3, "big")
        st2 = bytes([0xC5]) + alpha_env(d=0, bias=1, scale=0, clamp=1).to_bytes(3, "big")
        for mat, tev, pe in mats:
            cur1, cur2 = dm.read(tev + ST1_ALPHA, 4), dm.read(tev + ST2_ALPHA, 4)
            fresh = (cur1, cur2) == (ORIG_ST1, ORIG_ST2)
            if fresh:
                if dm.read(pe + PE_BLEND, 4) != ORIG_BLEND or dm.u8(pe + PE_REF0) != 128:
                    print(f"  {mat:08X} : PE inattendu, ignoré")
                    continue
                backup[f"{tev + ST1_ALPHA:08X}"] = cur1.hex()
                backup[f"{tev + ST2_ALPHA:08X}"] = cur2.hex()
                backup[f"{pe + PE_REF0:08X}"] = "80"
                backup[f"{pe + PE_BLEND:08X}"] = ORIG_BLEND.hex()
            elif f"{tev + ST1_ALPHA:08X}" not in backup:
                print(f"  {mat:08X} : signature TEV inconnue, ignoré")
                continue
            for off, val in ((ST1_ALPHA, st1), (ST2_ALPHA, st2)):
                for j, b in enumerate(val):
                    dm.write(tev + off + j, bytes([b]))
            dm.write(pe + PE_REF0, bytes([1]))
            for j, b in enumerate([1, 4, 5, 3]):        # BLEND, SRCALPHA, INVSRCALPHA, COPY
                dm.write(pe + PE_BLEND + j, bytes([b]))
            print(f"  {mat:08X} : bord fondu K={k}  ét1={st1.hex().upper()} ét2={st2.hex().upper()}")
        BACKUP.parent.mkdir(exist_ok=True)
        BACKUP.write_text(json.dumps(backup, indent=1))
        return 0
    if cmd == "restore":
        if not BACKUP.exists():
            print("pas de sauvegarde")
            return 1
        backup = json.loads(BACKUP.read_text())
        for a, h in backup.items():
            for j, b in enumerate(bytes.fromhex(h)):
                dm.write(int(a, 16) + j, bytes([b]))
        BACKUP.unlink()
        print(f"{len(backup)} zones restaurées")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
