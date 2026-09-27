"""Keeps the 120 FPS tier applied on a running Dolphin.

Why a resident process rather than a Gecko code
-----------------------------------------------
The `deliver/GMSE01.ini` profile only carries the host half of the setting --
the VI overclock. The game half goes through two MEM1 writes, not through
Dolphin's `[Gecko]` section.

This is an observation, not a style choice: on 2026-09-22 a valid `[Gecko]`
section in the per-game profile **was not loaded** -- Dolphin had injected no
codehandler (0x80001800 all zeros) while the `[Core]` section of the same
file did take effect. Cause not found.

The data writes have been proven since session 2 and do not hit the JIT
cache, unlike `gamemasterplc`'s `nop`:

    0x804167B8        f32   0.5f -> 2.0f   logic clock at 120 Hz
    TDisplay + 0x4C   u16   2    -> 1      one VI field per presented frame

What it monitors
----------------
It does not just write once. It checks in a loop that both values hold and
rewrites them if they drift -- on game restart, or if `TDisplay` is
reallocated. `TDisplay` is resolved every iteration through
`gpApplication + 0x1C`: it lives on the heap and moves between sessions.

It applies the setting **as soon as `TDisplay` exists**, well before entering
a level. This is intended: until it is applied and while the VI runs at 2x,
the game runs at double speed.

What it does not do
-------------------
No per-object fixes. Bird flocks, the eel boss, dialog timers, transitions
and fades remain unfixed -- see `deliver/README.md`.

It does not touch the `0x80414904` literal (`TModelGate` fade) either: the
anomaly in section 4.3 of `docs/01-mecanismes.md` is unresolved.

Usage
-----
    python keep120.py            # resident, Ctrl+C to stop
    python keep120.py --once     # single pass
    python keep120.py --restore  # back to 30 FPS (0.5f, 2 fields)
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

LITERAL_VSYNC = 0x804167B8
GP_APPLICATION = 0x803E9700
OFF_DISPLAY = 0x1C
OFF_RETRACE_COUNT = 0x4C

PATCH_SITE_RETRACE = 0x802FCB24  # final bl VIWaitForRetrace in waitForRetrace
NOP = 0x60000000

# (literal, mRetraceCount). The count assumes the final wait is INTACT; if
# `deliver/GMSE01.ini` removed it, `target_count` adjusts.
PROFILES = {
    30: (0.5, 2),
    60: (1.0, 1),
    120: (2.0, 1),
}


def target_count(dolphin: Dolphin, count: int) -> int:
    """Adjust the count if the final wait was removed at boot.

    The two fixes stack, and stacking them is dangerous. Per
    docs/01-mecanismes.md section 3.1, with the wait removed `waitForRetrace`
    consumes `count - 1` fields per call. With `count = 1` that is **zero** --
    no retrace wait at all, the game runs as fast as the host allows.

    When the `nop` is present it already gives per-field presentation on its
    own: the count must stay at its NTSC value of 2.
    """
    if dolphin.u32(PATCH_SITE_RETRACE) == NOP:
        return count + 1
    return count


def display_address(dolphin: Dolphin) -> int | None:
    """`JDrama::TDisplay`, or None until it is constructed."""
    display = dolphin.u32(GP_APPLICATION + OFF_DISPLAY)
    return display if dolphin.is_valid_pointer(display) else None


def read_state(dolphin: Dolphin) -> tuple[float, int] | None:
    display = display_address(dolphin)
    if display is None:
        return None
    return dolphin.f32(LITERAL_VSYNC), dolphin.u16(display + OFF_RETRACE_COUNT)


def enforce(dolphin: Dolphin, fps: int) -> tuple[bool, str]:
    """Apply the tier if needed. Returns (whether a write happened, message)."""
    literal, count = PROFILES[fps]
    count = target_count(dolphin, count)
    state = read_state(dolphin)
    if state is None:
        return False, "TDisplay pas encore construit"

    current_literal, current_count = state
    if abs(current_literal - literal) < 1e-6 and current_count == count:
        return False, f"en place ({current_literal:g}f, {current_count} champ)"

    dolphin.write_f32(LITERAL_VSYNC, literal)
    dolphin.write(
        display_address(dolphin) + OFF_RETRACE_COUNT, struct.pack(">H", count)
    )
    return True, (
        f"posé : {current_literal:g}f/{current_count} -> {literal:g}f/{count}"
    )


def _main(argv: list[str]) -> int:
    fps = 30 if "--restore" in argv else 120
    once = "--once" in argv or "--restore" in argv

    try:
        dolphin = Dolphin()
    except (RuntimeError, OSError) as error:
        # In resident mode, no game is not an error: it is the normal state
        # when this is started before the game.
        if once:
            print(error)
            return 1
        print("Aucun jeu démarré — en attente.")
        dolphin = None

    if dolphin is not None:
        print(f"Dolphin PID {dolphin.pid}, jeu {dolphin.game_id}")
        if dolphin.game_id[:6] != "GMSE01":
            print(
                f"  ATTENTION : profil prévu pour GMSE01, jeu chargé "
                f"{dolphin.game_id}"
            )

    if once:
        written, message = enforce(dolphin, fps)
        print(f"palier {fps} : {message}")
        return 0 if written or "en place" in message else 1

    print(f"Maintien du palier {fps} FPS. Ctrl+C pour rendre la main.")
    last_message = ""
    try:
        while True:
            try:
                if dolphin is None:
                    raise RuntimeError("pas encore rattaché")
                written, message = enforce(dolphin, fps)
            except (RuntimeError, OSError):
                # The game was stopped or restarted. On restart MEM1 is mapped
                # elsewhere and the cached handle is stale: reattach instead of
                # giving up. This is the normal case when restarting to apply
                # the host profile.
                written = False
                try:
                    dolphin = Dolphin()
                    message = f"rattaché à {dolphin.game_id}"
                except (RuntimeError, OSError):
                    message = "en attente d'un jeu démarré…"
            if written or message != last_message:
                print(f"  [{time.strftime('%H:%M:%S')}] {message}")
                last_message = message
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nArrêt. Le palier reste posé ; `--restore` pour revenir à 30 FPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
