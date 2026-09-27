"""Reversible application of the frame rate fixes to a running Dolphin.

Writes directly into emulated MEM1. Each fix records the original value and
can restore it, so measurements at several frame rates can be chained without
restarting the game.

What this module does NOT do
----------------------------
It applies **none** of the per-object fixes (boids, bosses, transitions,
fades) listed in the initial plan. It only makes the two writes that define
the frame rate itself, plus the `TModelGate` literal as an experiment. This is
deliberate: the goal is to measure the foundation, not ship a playable mod.

The JIT cache trap -- and why the `nop` is not used
---------------------------------------------------
Dolphin compiles PowerPC code to native code and caches the blocks. An
external write to an **instruction** has no effect until the block is
recompiled, whereas a write to **data** takes effect immediately since the
game rereads it every time.

Measured 2026-09-15: writing `nop` at `0x802FCB24` does change emulated MEM1
(confirmed by reading back) but **changes nothing in behavior** -- the game
keeps presenting 30 frames per second. The compiled JIT block wins.

This module works around it by writing **data** only:

    0x804167B8        f32 literal    logic clock + animation rate
    TDisplay + 0x4C   u16            mRetraceCount, fields per present

`mRetraceCount = 1` has exactly the same effect as `gamemasterplc`'s `nop`
(shown in docs/01-mecanismes.md section 3.1) without touching a single
instruction. It is also the route BetterSunshineEngine takes.

`TDisplay` is reached through `gpApplication + 0x1C`, resolved on every call:
the object is heap-allocated and its address changes between sessions.

Usage
-----
    python patch.py status
    python patch.py apply   <30|60|120>
    python patch.py restore
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

# Original values are persisted on disk so they can be restored even after the
# script that applied the fix has exited.
BACKUP = Path(__file__).parent.parent / "work" / "patch-backup.json"

LITERAL_VSYNC = 0x804167B8  # 0.5f -- logic clock and animation rate
LITERAL_GATE = 0x80414904  # 0.01f -- TModelGate fade

GP_APPLICATION = 0x803E9700  # gpApplication IS the object, not a pointer to it
OFF_DISPLAY = 0x1C  # TApplication::mDisplay
OFF_RETRACE_COUNT = 0x4C  # JDrama::TDisplay::mRetraceCount (u16)

# Per-tier values. The literal is `rate / 60`: it sets both the return value of
# SMSGetVSyncTimesPerSec and, in turn, the number of substeps per frame
# (600 / rate). `retrace_count` sets the VI fields consumed per presented frame.
PROFILES = {
    30: {"literal": 0.5, "retrace_count": 2, "gate": 0.01},
    60: {"literal": 1.0, "retrace_count": 1, "gate": 0.02},
    120: {"literal": 2.0, "retrace_count": 1, "gate": 0.04},
}


def display_address(dolphin: Dolphin) -> int:
    """Address of the `JDrama::TDisplay` object, resolved on every call."""
    display = dolphin.u32(GP_APPLICATION + OFF_DISPLAY)
    if not dolphin.is_valid_pointer(display):
        raise RuntimeError(
            f"mDisplay invalide (0x{display:08X}) — le jeu est-il démarré ?"
        )
    return display


def read_state(dolphin: Dolphin) -> dict:
    return {
        "literal": dolphin.f32(LITERAL_VSYNC),
        "retrace_count": dolphin.u16(display_address(dolphin) + OFF_RETRACE_COUNT),
        "gate": dolphin.f32(LITERAL_GATE),
    }


def save_original(dolphin: Dolphin) -> dict:
    """Record the original state, once."""
    if BACKUP.exists():
        return json.loads(BACKUP.read_text())
    state = read_state(dolphin)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(state, indent=2))
    return state


def apply(dolphin: Dolphin, fps: int, gate: bool = True) -> dict:
    """Apply a tier. Returns the state read back after writing."""
    if fps not in PROFILES:
        raise ValueError(f"palier inconnu : {fps} (attendu {sorted(PROFILES)})")
    save_original(dolphin)
    profile = PROFILES[fps]

    dolphin.write_f32(LITERAL_VSYNC, profile["literal"])
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT,
        struct.pack(">H", profile["retrace_count"]),
    )
    if gate:
        dolphin.write_f32(LITERAL_GATE, profile["gate"])
    return read_state(dolphin)


def restore(dolphin: Dolphin) -> dict:
    """Restore the original values recorded on the first `apply`."""
    if not BACKUP.exists():
        raise RuntimeError("aucune sauvegarde : rien à restaurer")
    original = json.loads(BACKUP.read_text())
    dolphin.write_f32(LITERAL_VSYNC, original["literal"])
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT,
        struct.pack(">H", original["retrace_count"]),
    )
    dolphin.write_f32(LITERAL_GATE, original["gate"])
    return read_state(dolphin)


def describe(state: dict) -> str:
    logical = 60.0 * state["literal"]
    count = state["retrace_count"]
    quantum = int(600 / logical) if logical else "?"
    return (
        f"  littéral 0x804167B8   {state['literal']:<5g} horloge logique {logical:g} Hz, "
        f"{quantum} unités par sous-pas\n"
        f"  mRetraceCount +0x4C   {count:<5} {count} champ(s) VI par image présentée\n"
        f"  littéral 0x80414904   {state['gate']:<5g} fondu TModelGate"
    )


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    dolphin = Dolphin()
    command = argv[1]

    if command == "status":
        print(f"Jeu : {dolphin.game_id}")
        print(describe(read_state(dolphin)))
        if BACKUP.exists():
            print(f"\nSauvegarde présente : {BACKUP}")

    elif command == "apply":
        fps = int(argv[2])
        state = apply(dolphin, fps)
        print(f"Palier {fps} FPS appliqué :")
        print(describe(state))

    elif command == "restore":
        state = restore(dolphin)
        print("État d'origine restauré :")
        print(describe(state))

    else:
        print(f"commande inconnue : {command}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
