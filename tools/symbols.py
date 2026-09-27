"""Symbol table: .map file loading and CodeWarrior demangling.

The DOL has no symbols. Names come from external tables in "name=0xADDRESS"
format, one entry per line (the format of the maps published by
BetterSunshineEngine and Corona).

Names are mangled by CodeWarrior/MetroWerks, not the Itanium scheme
(GCC/Clang), so `c++filt` cannot read them. The scheme is:

    name__<scope><return-type-and-arguments>

    direct__12TMarDirectorFv
    └─ direct   method name
       12       length of the class name that follows
       TMarDirector
       F        "function", starts the argument list
       v        void

    waitForRetrace__Q26JDrama6TVideoFUs
       Q2       namespace nested 2 levels deep
       6JDrama 6TVideo
       F Us     function taking an unsigned short

The demangling is deliberately partial: it aims at readable listings, not
exact C++ signatures. When in doubt, the raw mangled name is kept.

Command line
------------
    python symbols.py lookup   <map> <address>     symbol containing the address
    python symbols.py find     <map> <pattern>     search by name
    python symbols.py demangle <mangled-name>

See docs/03-outillage.md.
"""

from __future__ import annotations

import bisect
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^(?P<name>[^=\s]+)=0x(?P<address>[0-9A-Fa-f]+)\s*$")

# CodeWarrior base type codes seen in signatures.
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
    """Symbols sorted by address, queryable by address or by name.

    A map only gives start addresses, never sizes: a symbol's upper bound is
    taken as the next symbol's address. Good enough to annotate a listing, but
    it overestimates the last symbol of each section, so do not rely on it to
    delimit a function with certainty.
    """

    def __init__(self, symbols: list[Symbol]) -> None:
        self._symbols = sorted(symbols, key=lambda s: s.address)
        self._addresses = [s.address for s in self._symbols]
        self._by_name = {s.name: s for s in self._symbols}

    @classmethod
    def load(cls, *paths: Path) -> "SymbolTable":
        """Load one or more maps. On conflict, the first one wins."""
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
        """Symbol starting exactly at `address`."""
        index = bisect.bisect_left(self._addresses, address)
        if index < len(self._symbols) and self._addresses[index] == address:
            return self._symbols[index]
        return None

    def containing(self, address: int) -> tuple[Symbol, int] | None:
        """Symbol preceding `address`, as (symbol, delta) where delta is the
        offset from its start, e.g. "direct__12TMarDirectorFv+0x1C4".
        """
        index = bisect.bisect_right(self._addresses, address) - 1
        if index < 0:
            return None
        symbol = self._symbols[index]
        return symbol, address - symbol.address

    def label(self, address: int, demangled: bool = True) -> str:
        """Readable label for an address, or its hex form."""
        found = self.containing(address)
        if found is None:
            return f"0x{address:08X}"
        symbol, delta = found
        name = demangle(symbol.name) if demangled else symbol.name
        return name if delta == 0 else f"{name}+0x{delta:X}"

    def search(self, pattern: str) -> list[Symbol]:
        """Symbols whose mangled or demangled name contains `pattern`
        (case-insensitive)."""
        needle = pattern.lower()
        return [
            s
            for s in self._symbols
            if needle in s.name.lower() or needle in demangle(s.name).lower()
        ]


def _read_length_prefixed(text: str, pos: int) -> tuple[str, int]:
    """Read a length-prefixed identifier ("12TMarDirector")."""
    start = pos
    while pos < len(text) and text[pos].isdigit():
        pos += 1
    if pos == start:
        return "", start
    length = int(text[start:pos])
    return text[pos : pos + length], pos + length


def _parse_scope(text: str, pos: int) -> tuple[list[str], int]:
    """Read a scope: either a single identifier, or "Q<n>" followed by n
    nested identifiers."""
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
    """Read an argument type. Handles the P (pointer), R (reference),
    C (const) and U (unsigned) qualifiers that prefix the base type."""
    prefixes = []
    while pos < len(text) and text[pos] in "PRC":
        prefixes.append(text[pos])
        pos += 1

    # "U" is a qualifier only before an integer type; otherwise it starts a
    # length-prefixed class name.
    if text.startswith("U", pos) and pos + 1 < len(text) and text[pos + 1] in "csilx":
        base = _BASE_TYPES.get(text[pos : pos + 2], text[pos : pos + 2])
        pos += 2
    elif pos < len(text) and text[pos] in _BASE_TYPES and not text[pos].isdigit():
        base = _BASE_TYPES[text[pos]]
        pos += 1
    else:
        parts, pos = _parse_scope(text, pos)
        base = "::".join(parts) if parts else "?"
        # Template arguments ("TVec3<f>") are part of the name itself, already
        # covered by the length prefix.

    for prefix in reversed(prefixes):
        base = {"P": base + "*", "R": base + "&", "C": "const " + base}[prefix]
    return base, pos


def demangle(name: str) -> str:
    """Demangle a CodeWarrior symbol.

    Returns the name unchanged if it is not mangled or parsing fails: a
    partially demangled listing is still usable, a wrong one is not.
    """
    if "__" not in name:
        return name

    base, _, rest = name.partition("__")
    if not rest:
        return name

    try:
        scope, pos = _parse_scope(rest, 0)
        qualified = "::".join([*scope, base]) if scope else base

        # A "C" between the scope and the "F" marks a const method.
        is_const = rest.startswith("CF", pos)
        if is_const:
            pos += 1

        if pos >= len(rest) or rest[pos] != "F":
            # No "F": data member or static symbol, not a function.
            return qualified

        pos += 1
        args: list[str] = []
        while pos < len(rest):
            arg, new_pos = _parse_type(rest, pos)
            if new_pos == pos:  # no progress: parser stuck
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
