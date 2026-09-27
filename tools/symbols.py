"""Table de symboles : lecture des fichiers .map et démangling CodeWarrior.

Le DOL ne contient aucun symbole. Les noms viennent de tables externes, au
format « nom=0xADRESSE » une entrée par ligne (format des maps publiées par
BetterSunshineEngine et Corona).

Les noms sont manglés par CodeWarrior/MetroWerks, pas par le schéma Itanium
(GCC/Clang) — `c++filt` ne sait donc pas les lire. Le schéma est :

    nom__<portée><type-de-retour-et-arguments>

    direct__12TMarDirectorFv
    └─ direct   nom de la méthode
       12       longueur du nom de classe qui suit
       TMarDirector
       F        « function », introduit la liste d'arguments
       v        void

    waitForRetrace__Q26JDrama6TVideoFUs
       Q2       espace de noms imbriqué sur 2 niveaux
       6JDrama 6TVideo
       F Us     fonction prenant un unsigned short

Le démangling implémenté ici est volontairement partiel : il vise la
lisibilité d'un listing, pas la reconstruction exacte d'une signature C++.
En cas de doute, le nom manglé brut est conservé.

Usage en ligne de commande
--------------------------
    python symbols.py lookup   <map> <adresse>     symbole contenant l'adresse
    python symbols.py find     <map> <motif>       recherche par nom
    python symbols.py demangle <nom-manglé>

Voir docs/03-outillage.md.
"""

from __future__ import annotations

import bisect
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^(?P<name>[^=\s]+)=0x(?P<address>[0-9A-Fa-f]+)\s*$")

# Codes de types de base CodeWarrior rencontrés dans les signatures.
_BASE_TYPES = {
    "v": "void",
    "b": "bool",
    "c": "char",
    "s": "short",
    "i": "int",
    "l": "long",
    "x": "long long",
    "f": "float",
    "d": "double",
    "e": "...",
    "Uc": "unsigned char",
    "Us": "unsigned short",
    "Ui": "unsigned int",
    "Ul": "unsigned long",
    "Ux": "unsigned long long",
    "Sc": "signed char",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    address: int

    def __str__(self) -> str:
        return self.name


class SymbolTable:
    """Symboles triés par adresse, interrogeables par adresse ou par nom.

    Une map ne donne que des adresses de départ, jamais de tailles : la borne
    supérieure d'un symbole est prise comme l'adresse du symbole suivant. Cette
    approximation suffit pour annoter un listing mais surestime la taille du
    dernier symbole de chaque section — ne pas s'en servir pour délimiter une
    fonction avec certitude.
    """

    def __init__(self, symbols: list[Symbol]) -> None:
        self._symbols = sorted(symbols, key=lambda s: s.address)
        self._addresses = [s.address for s in self._symbols]
        self._by_name = {s.name: s for s in self._symbols}

    @classmethod
    def load(cls, *paths: Path) -> "SymbolTable":
        """Charge une ou plusieurs maps. En cas de conflit, la première gagne."""
        seen: dict[str, Symbol] = {}
        for path in paths:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = _LINE.match(line.strip())
                if match and match["name"] not in seen:
                    seen[match["name"]] = Symbol(match["name"], int(match["address"], 16))
        return cls(list(seen.values()))

    def __len__(self) -> int:
        return len(self._symbols)

    def by_name(self, name: str) -> Symbol | None:
        return self._by_name.get(name)

    def address_of(self, name: str) -> int | None:
        symbol = self._by_name.get(name)
        return symbol.address if symbol else None

    def at(self, address: int) -> Symbol | None:
        """Symbole commençant exactement à `address`."""
        index = bisect.bisect_left(self._addresses, address)
        if index < len(self._symbols) and self._addresses[index] == address:
            return self._symbols[index]
        return None

    def containing(self, address: int) -> tuple[Symbol, int] | None:
        """Symbole précédant `address`, avec le déplacement depuis son début.

        Retourne (symbole, delta). Utile pour étiqueter une adresse au milieu
        d'une fonction : « direct__12TMarDirectorFv+0x1C4 ».
        """
        index = bisect.bisect_right(self._addresses, address) - 1
        if index < 0:
            return None
        symbol = self._symbols[index]
        return symbol, address - symbol.address

    def label(self, address: int, demangled: bool = True) -> str:
        """Étiquette lisible pour une adresse, ou sa forme hexadécimale."""
        found = self.containing(address)
        if found is None:
            return f"0x{address:08X}"
        symbol, delta = found
        name = demangle(symbol.name) if demangled else symbol.name
        return name if delta == 0 else f"{name}+0x{delta:X}"

    def search(self, pattern: str) -> list[Symbol]:
        """Symboles dont le nom manglé ou démanglé contient `pattern`
        (insensible à la casse)."""
        needle = pattern.lower()
        return [
            s
            for s in self._symbols
            if needle in s.name.lower() or needle in demangle(s.name).lower()
        ]


def _read_length_prefixed(text: str, pos: int) -> tuple[str, int]:
    """Lit un identifiant préfixé par sa longueur (« 12TMarDirector »)."""
    start = pos
    while pos < len(text) and text[pos].isdigit():
        pos += 1
    if pos == start:
        return "", start
    length = int(text[start:pos])
    return text[pos : pos + length], pos + length


def _parse_scope(text: str, pos: int) -> tuple[list[str], int]:
    """Lit la portée : soit un identifiant simple, soit « Q<n> » suivi de n
    identifiants imbriqués."""
    if text.startswith("Q", pos) and pos + 1 < len(text) and text[pos + 1].isdigit():
        count = int(text[pos + 1])
        pos += 2
        parts = []
        for _ in range(count):
            part, pos = _read_length_prefixed(text, pos)
            parts.append(part)
        return parts, pos
    part, pos = _read_length_prefixed(text, pos)
    return ([part] if part else []), pos


def _parse_type(text: str, pos: int) -> tuple[str, int]:
    """Lit un type d'argument. Gère les qualificatifs P (pointeur), R
    (référence), C (const) et U (unsigned) qui préfixent le type de base."""
    prefixes = []
    while pos < len(text) and text[pos] in "PRC":
        prefixes.append(text[pos])
        pos += 1

    # « U » n'est un qualificatif que s'il précède un type entier ; sinon
    # c'est le début d'un nom de classe préfixé par sa longueur.
    if text.startswith("U", pos) and pos + 1 < len(text) and text[pos + 1] in "csilx":
        base = _BASE_TYPES.get(text[pos : pos + 2], text[pos : pos + 2])
        pos += 2
    elif pos < len(text) and text[pos] in _BASE_TYPES and not text[pos].isdigit():
        base = _BASE_TYPES[text[pos]]
        pos += 1
    else:
        parts, pos = _parse_scope(text, pos)
        base = "::".join(parts) if parts else "?"
        # Argument de template : « TVec3<f> » se termine par le nom lui-même,
        # déjà capturé par la longueur préfixée.

    for prefix in reversed(prefixes):
        base = {"P": base + "*", "R": base + "&", "C": "const " + base}[prefix]
    return base, pos


def demangle(name: str) -> str:
    """Rend lisible un symbole manglé CodeWarrior.

    Retourne le nom d'origine inchangé s'il n'est pas manglé ou si l'analyse
    échoue : un listing partiellement démanglé reste exploitable, un listing
    faux ne l'est pas.
    """
    if "__" not in name:
        return name

    base, _, rest = name.partition("__")
    if not rest:
        return name

    try:
        scope, pos = _parse_scope(rest, 0)
        qualified = "::".join([*scope, base]) if scope else base

        # Un « C » entre la portée et le « F » marque une méthode const.
        is_const = rest.startswith("CF", pos)
        if is_const:
            pos += 1

        if pos >= len(rest) or rest[pos] != "F":
            # Pas de « F » : donnée membre ou symbole statique, pas une fonction.
            return qualified

        pos += 1
        args: list[str] = []
        while pos < len(rest):
            arg, new_pos = _parse_type(rest, pos)
            if new_pos == pos:  # aucune progression : analyse bloquée
                return name
            args.append(arg)
            pos = new_pos

        if args == ["void"]:
            args = []
        return f"{qualified}({', '.join(args)}){' const' if is_const else ''}"
    except (ValueError, IndexError):
        return name


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    command = argv[1]

    if command == "demangle":
        for name in argv[2:]:
            print(f"{name}\n  -> {demangle(name)}")
        return 0

    if len(argv) < 4:
        print(__doc__)
        return 2

    table = SymbolTable.load(Path(argv[2]))

    if command == "lookup":
        address = int(argv[3], 0)
        found = table.containing(address)
        if found is None:
            print(f"0x{address:08X} : aucun symbole antérieur")
        else:
            symbol, delta = found
            print(f"0x{address:08X} = {symbol.name}+0x{delta:X}")
            print(f"            {demangle(symbol.name)}")

    elif command == "find":
        for symbol in table.search(argv[3]):
            print(f"0x{symbol.address:08X}  {symbol.name}")
            print(f"            {demangle(symbol.name)}")

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
