"""Controller input injection by writing into the `TMarioGamePad` object.

Drives Mario from a script without a physical controller, without sending
keystrokes to Dolphin's window and without stealing its focus. This is what
makes the test suite fully automatable.

`TMarioGamePad` layout (derived from `JUTGamePad`)
--------------------------------------------------
Offsets read from the code, not guessed:

    +0x18  u32  **held** buttons         (`updateMeaning` tests the D-pad here)
    +0x1C  u32  **newly pressed** buttons (edge)
    +0x2C  f32  analog trigger
    +0xA8  f32  main stick X, in [-1, 1]   (`checkController`, x128)
    +0xAC  f32  main stick Y, in [-1, 1]
    +0xDC  u16  "meaning" -- interpretation computed by the game

Verified experimentally: writing only `+0x18` does **nothing**, writing
`+0x1C` makes Mario jump. The jump triggers on the edge, not the hold, which
confirms which field is which.

Why hammering
-------------
The game rewrites the object every frame from the real controller
(`TMarioGamePad::read`), so a single write would be overwritten before being
read. A background thread rewrites the values continuously: at ~400,000
writes per second against one reread per frame, the injected values are in
place when `TMario::checkController` reads them.

It is a race, not a lock: won by a wide margin, but still a race. Tests must
measure an outcome (height reached, distance covered) rather than assume a
given frame saw the input.

Usage
-----
    with Pad(dolphin) as pad:
        pad.stick(0.0, 1.0)      # full forward
        time.sleep(1.0)
        pad.tap("A")             # jump
        pad.neutral()
"""

from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MARIO = 0x8040E0E8
OFF_MARIO_GAMEPAD = 0x4FC  # TMario::mGamePad -- `stw r4, 0x4fc(r3)` in setGamePad

OFF_HELD = 0x18
OFF_PRESSED = 0x1C
OFF_ANALOG = 0x2C
OFF_STICK_X = 0xA8
OFF_STICK_Y = 0xAC

# GameCube controller button masks (SDK PAD_BUTTON_*).
BUTTONS = {
    "LEFT": 0x0001,
    "RIGHT": 0x0002,
    "DOWN": 0x0004,
    "UP": 0x0008,
    "Z": 0x0010,
    "R": 0x0020,
    "L": 0x0040,
    "A": 0x0100,
    "B": 0x0200,
    "X": 0x0400,
    "Y": 0x0800,
    "START": 0x1000,
}

# Press edge duration.
#
# Hammering is a race: every frame the game resets the pad from the real
# controller, then reads it a little later. Injection only "wins" if a write
# lands in between. A one-frame window gives only one or two chances, which is
# not enough -- measured: a 50 ms edge does not trigger the jump reliably.
#
# 200 ms covers 6 frames at 30 FPS and 12 at 60 FPS, making a miss unlikely.
# Extra edges are harmless: Mario is already airborne and the game ignores
# the input.
PRESS_WINDOW = 0.200


def mask_of(buttons: str | int | None) -> int:
    """Convert "A", "A+B" or an int to a button mask."""
    if buttons is None:
        return 0
    if isinstance(buttons, int):
        return buttons
    total = 0
    for name in buttons.replace(" ", "").split("+"):
        if name:
            total |= BUTTONS[name.upper()]
    return total


class Pad:
    """Virtual controller hammered into game memory."""

    def __init__(self, dolphin: Dolphin | None = None) -> None:
        self.dolphin = dolphin or Dolphin()
        mario = self.dolphin.u32(GP_MARIO)
        if not self.dolphin.is_valid_pointer(mario):
            raise RuntimeError("Mario introuvable — le jeu est-il dans un niveau ?")
        self.address = self.dolphin.u32(mario + OFF_MARIO_GAMEPAD)
        if not self.dolphin.is_valid_pointer(self.address):
            raise RuntimeError(f"TMarioGamePad invalide (0x{self.address:08X})")

        self._held = 0
        self._pressed = 0
        self._pressed_until = 0.0
        self._stick = (0.0, 0.0)
        self._analog = 0.0
        self._stop = threading.Event()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Pad":
        """Start hammering and **wait** until it actually writes.

        Locating MEM1 requires scanning the process regions, which takes
        longer than a press edge lasts. Without the wait, a command issued
        right after `start()` would be lost.
        """
        if self._thread is None:
            self._stop.clear()
            self._running.clear()
            self._thread = threading.Thread(target=self._hammer, daemon=True)
            self._thread.start()
            if not self._running.wait(timeout=10.0):
                raise RuntimeError("le fil de martèlement n'a pas démarré")
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        # Hand control back to the real controller: reset to neutral once.
        self.dolphin.write(self.address + OFF_HELD, struct.pack(">II", 0, 0))
        self.dolphin.write(self.address + OFF_STICK_X, struct.pack(">ff", 0.0, 0.0))

    def __enter__(self) -> "Pad":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _hammer(self) -> None:
        # Separate connection: sharing the Win32 handle is safe, but one
        # instance per thread avoids interleaved state. Constructing it
        # rescans the process regions, hence the start signal, set only after
        # the first write.
        dolphin = Dolphin(self.dolphin.pid)
        base = self.address
        dolphin.write(base + OFF_HELD, struct.pack(">II", 0, 0))
        self._running.set()
        while not self._stop.is_set():
            pressed = self._pressed if time.perf_counter() < self._pressed_until else 0
            dolphin.write(base + OFF_HELD, struct.pack(">II", self._held, pressed))

            # Stick and trigger are only rewritten when in use: a shorter loop
            # hammers faster, improving the odds of winning the race on
            # buttons.
            x, y = self._stick
            if x or y:
                dolphin.write(base + OFF_STICK_X, struct.pack(">ff", x, y))
            if self._analog:
                dolphin.write(base + OFF_ANALOG, struct.pack(">f", self._analog))

    def hold(self, buttons: str | int) -> None:
        """Hold buttons (no edge)."""
        self._held = mask_of(buttons)

    def press(self, buttons: str | int, window: float = PRESS_WINDOW) -> None:
        """Emit a bounded press edge, then keep the buttons held.

        The edge only lasts `window`; after that only the hold remains. This
        matters: repeating the edge every frame means pressing A again as
        soon as Mario lands, which chains double/triple jumps. Measured: with
        a permanent edge, the height of the same jump varied from 73.79 to
        140.0 between runs, and `vy max` jumped between three discrete values
        (41, 42, 52) matching three different jump types.
        """
        mask = mask_of(buttons)
        self._pressed = mask
        self._pressed_until = time.perf_counter() + window
        self._held |= mask

    def tap(self, buttons: str | int, window: float = PRESS_WINDOW) -> None:
        """Press edge, then immediate release."""
        self.press(buttons, window)
        time.sleep(window)
        self.release(buttons)

    def release(self, buttons: str | int | None = None) -> None:
        self._held = 0 if buttons is None else self._held & ~mask_of(buttons)

    def stick(self, x: float, y: float) -> None:
        """Main stick, components in [-1, 1]. Positive Y = forward."""
        self._stick = (float(x), float(y))

    def analog(self, value: float) -> None:
        """Analog trigger, in [0, 1]."""
        self._analog = float(value)

    def neutral(self) -> None:
        self._held = 0
        self._pressed = 0
        self._pressed_until = 0.0
        self._stick = (0.0, 0.0)
        self._analog = 0.0

    def settle(self, duration: float = 0.8) -> None:
        """Reset everything to neutral and let the game notice.

        Required before a press: the game keeps its own copy of the previous
        controller state to detect edges. Without a few neutral frames, a
        press injected right after hammering starts is not seen as an edge --
        verified experimentally, it is the difference between a jump and
        nothing.
        """
        self.neutral()
        time.sleep(duration)


def _main(argv: list[str]) -> int:
    """Demo: make Mario jump and report the height reached."""
    dolphin = Dolphin()
    mario = dolphin.u32(GP_MARIO)
    y_address = mario + 0x14

    with Pad(dolphin) as pad:
        print(f"TMarioGamePad 0x{pad.address:08X}")
        pad.settle()
        base = dolphin.f32(y_address)
        pad.press("A")
        peak = base
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            peak = max(peak, dolphin.f32(y_address))
        pad.settle(0.2)
        print(f"Y de départ {base:g}, sommet {peak:g}, hauteur {peak - base:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
