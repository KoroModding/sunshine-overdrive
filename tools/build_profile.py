"""Assemble toutes les écritures du profil 120 FPS et régénère deliver/GMSE01.ini.

Sources :
    tools/build_caves.py     particules, drapeaux de port JAI
    tools/fixes/*.py         hx, fader, menus, actors, contexts, sound
    ci-dessous               nop 0x802FCB24, portails TModelGate

Contrôles, tous bloquants :
    - aucun mot aux adresses des crochets HLE de Dolphin (0x800018A8, 0x80002FFC) ;
    - aucune adresse écrite deux fois avec des valeurs différentes ;
    - chaque site hors grottes contient dans le DOL un mot différent de l'écriture
      (sinon l'écriture serait sans effet — signe d'une erreur d'adresse) ;
    - chaque branchement écrit vise soit une adresse écrite par le profil, soit un
      symbole de la carte, soit l'instruction qui suit un site détourné. Garde-fou
      contre le bogue de Keystone : après un `slwi`, les branchements suivants du
      même bloc étaient calculés depuis une mauvaise base (2026-09-23).

Chaque ligne est CONDITIONNELLE (`adresse:dword:valeur:comparant`) : Dolphin
n'écrit que si la mémoire contient encore le comparant — le mot d'origine du
DOL, ou 0 dans les grottes. Sans cela, le PatchEngine réécrit toutes les lignes
à chaque champ VI et invalide à chaque fois le code JIT correspondant : avec
426 lignes dont beaucoup dans du code chaud, l'émulation est tombée à 14 champs
par seconde au lieu de 120 (relevé 2026-09-23 : 14,3 champs/s, 1,00 champ par
image — le jeu n'était pas en cause). Les mots nuls des grottes sont omis.

Le littéral 0x804167B8 n'est plus écrit par le profil : tools/fixes/contexts.py
le pose à chaque image selon le contexte (30 FPS au boot, logos, intro).

Usage
-----
    python tools/build_profile.py            vérifie et affiche le bloc [OnFrame]
    python tools/build_profile.py --write    vérifie et réécrit deliver/GMSE01.ini
    python tools/build_profile.py --write --modules hx,fader
        seulement ces modules de tools/fixes (défaut : tous) ; « --modules none »
        = profil de base. « --inconditionnel » : lignes sans comparant, comme
        avant le 2026-09-23 (réécrites à chaque champ VI). Sans le module contexts, le littéral 0x804167B8 est
        posé à 2.0f par [OnFrame] comme avant la passe complète.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "fixes"))

import build_caves  # noqa: E402
from dol import Dol  # noqa: E402

INI = ROOT / "deliver" / "GMSE01.ini"
MAP = ROOT / "work" / "maps" / "us.map"
DOL = ROOT / "work" / "dol" / "GMSE01.dol"

BASE = [
    (0x802FCB24, 0x60000000),   # waitForRetrace : bl VIWaitForRetrace -> nop
    (0x801EC29C, 0xC002D564),   # TModelGate::loadAfter : +0xD8 <- 0.005f (0x80414104)
]
MODULES = ["hx", "fader", "menus", "actors", "contexts", "sound", "fades", "soundsets", "widescreen", "doppler", "petey", "birds", "eel", "bosses", "goop", "jointcoin"]
CAVES = (0x80001800, 0x80003000)


def collect(modules: list[str] = MODULES) -> list[tuple[str, int, int]]:
    out = [("base", a, v) for a, v in BASE]
    if "contexts" not in modules:
        out.insert(0, ("base", 0x804167B8, 0x40000000))
    out += [("build_caves", a, v) for a, v in build_caves.build()[0]]
    for name in modules:
        out += [(name, a, v) for a, v in importlib.import_module(name).build()]
    return out


def symbol_starts() -> set[int]:
    starts = set()
    for line in MAP.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=0x" in line:
            try:
                starts.add(int(line.rsplit("=", 1)[1], 16))
            except ValueError:
                pass
    return starts


def check(entries: list[tuple[str, int, int]]) -> list[str]:
    errors = []
    seen: dict[int, tuple[str, int]] = {}
    for mod, a, v in entries:
        if a in seen and seen[a][1] != v:
            errors.append(f"conflit {a:08X} : {seen[a][0]}={seen[a][1]:08X} / {mod}={v:08X}")
        seen[a] = (mod, v)

    # Crochets HLE que Dolphin pose dans la zone du gestionnaire Gecko, actifs
    # même sans code Gecko : y placer une instruction fait exécuter du code
    # d'émulateur. 0x800018A8 (Gecko::ENTRY_POINT) vide tout le cache JIT à
    # chaque passage — 8 champs/s pendant Hx_Circle, 2026-09-27 ;
    # 0x80002FFC (HLE_TRAMPOLINE_ADDRESS) rétablit LR/SP/PC.
    for a in (0x800018A8, 0x80002FFC):
        if a in seen:
            errors.append(f"{a:08X} ({seen[a][0]}) : adresse de crochet HLE de Dolphin, interdite")

    dol = Dol(DOL)
    sites = {a for _, a, _ in entries if not CAVES[0] <= a < CAVES[1]}
    for a in sites:
        try:
            if dol.u32(a) == seen[a][1]:
                errors.append(f"{a:08X} ({seen[a][0]}) : écriture identique au DOL, sans effet")
        except Exception:
            pass                                    # données hors fichier (BSS)

    starts = symbol_starts()
    returns = {a + 4 for a in sites}
    cs = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 + capstone.CS_MODE_BIG_ENDIAN)
    for a, (mod, v) in seen.items():
        op = v >> 26
        if op == 18:                                # b / bl
            off = v & 0x03FFFFFC
            if off & 0x02000000:
                off -= 0x04000000
            target = (off if v & 2 else a + off) & 0xFFFFFFFF
        elif op == 16:                              # bc
            off = v & 0xFFFC
            if off & 0x8000:
                off -= 0x10000
            target = (off if v & 2 else a + off) & 0xFFFFFFFF
        else:
            continue
        if target in seen or target in starts or target in returns:
            continue
        ins = next(cs.disasm(v.to_bytes(4, "big"), a), None)
        text = f"{ins.mnemonic} {ins.op_str}" if ins else f"{v:08X}"
        errors.append(f"{a:08X} ({mod}) : {text} vise {target:08X}, ni écrit, ni symbole, ni retour")
    return errors


def comparand(dol: Dol, a: int) -> int:
    if CAVES[0] <= a < CAVES[1]:
        return 0
    return dol.u32(a)


def onframe_block(entries, conditional: bool = True) -> str:
    dol = Dol(DOL)
    lines = ["$120FPS [Sunshine Overdrive]"]
    for _, a, v in entries:
        if not conditional:
            lines.append(f"0x{a:08X}:dword:0x{v:08X}")
            continue
        c = comparand(dol, a)
        if v == c:
            continue                                # grotte : mot nul déjà en place
        lines.append(f"0x{a:08X}:dword:0x{v:08X}:0x{c:08X}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    modules = MODULES
    if "--modules" in argv:
        arg = argv[argv.index("--modules") + 1]
        modules = [] if arg == "none" else arg.split(",")
    entries = collect(modules)
    errors = check(entries)
    per_mod: dict[str, int] = {}
    for mod, _, _ in entries:
        per_mod[mod] = per_mod.get(mod, 0) + 1
    print("Mots par source :", ", ".join(f"{k} {v}" for k, v in per_mod.items()), f"— total {len(entries)}")
    if errors:
        print(f"{len(errors)} ERREUR(S) :")
        for e in errors:
            print("  " + e)
        return 1
    print("Contrôles : aucun conflit, aucune écriture sans effet, tous les branchements résolus")
    if "--write" in argv:
        s = INI.read_text(encoding="utf-8")
        i = s.index("[OnFrame]\n") + len("[OnFrame]\n")
        j = s.index("\n[OnFrame_Enabled]")
        s = s[:i] + onframe_block(entries, "--inconditionnel" not in argv) + s[j:]
        INI.write_text(s, encoding="utf-8")
        print(f"{INI} réécrit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
