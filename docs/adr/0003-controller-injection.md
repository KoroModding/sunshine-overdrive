# ADR 0003 — Inject controller inputs into memory, not through the keyboard

- **Date**: 2026-09-15
- **Status**: accepted

## Context

Half of the regression battery requires inputs: jump, triple jump,
dive, run, slide, hover. Without a way to produce them from a script,
these tests require a human operator at each tier — hence
different inputs on each trial, hence worthless comparisons.

The initial plan called for Dolphin's `.dtm` recording (Movie → Record Input)
to replay the same inputs at each tier. It is the correct solution on
paper; it nonetheless requires recording by hand, loading the
file through the UI, and restarting the game on each trial.

## Options

| Option | Why it was rejected, or chosen |
|---|---|
| **physical controller** | not scriptable; different inputs on each trial |
| **`.dtm`** | correct, but goes through the UI on each trial and cannot be driven from the script that measures |
| **keystrokes** (`SendInput`) | **impossible** — see below |
| **injection into `TMarioGamePad`** | **chosen** |

## The keyboard does not work in this context

Measured on 2026-09-15: `SendInput` does not reach the interactive desktop from a
command-line agent. Even `GetAsyncKeyState`, called in the process
that just injected the keystroke, does not see it. Neither forcing focus
(`AttachThreadInput` + `SetForegroundWindow`), nor the choice of window —
render or main — changes anything.

This is a limitation of the execution context, not a defect of Dolphin. All
keyboard automation is therefore excluded from the project.

## Decision

Write directly into the `TMarioGamePad` object, resolved through `TMario + 0x4FC`,
with a background thread that hammers the values continuously.

Offsets and evidence: [`../02-addresses.md`](../02-addresses.md).

## What this decision costs

It is a **race**, not a lock. The game rewrites the object every frame
from the real controller, then reads it a little later; the injection only
wins if a write lands between the two. At ~400 000 writes per
second against one read per frame, the race is won by a very wide margin —
but not always.

Three consequences, all paid for in wrong measurements before being understood:

1. **A test must check that the action took place, and retry.** Without that, a
   lost trial reads as a physics discrepancy. Measured: one failure in three
   with a 50 ms edge window, none with 200 ms.
2. **A few frames of neutral are needed before a press.** The game keeps its
   own memory of the previous state to detect edges; without a prior
   neutral, the injected press is not one. It is the difference between
   a jump and nothing at all.
3. **The edge must be bounded in time.** Replaying the edge every frame
   amounts to pressing A again as soon as Mario lands: Mario chains double and
   triple jumps. Measured with a permanent edge, the height of the same jump
   varied from 73.79 to 140.0 and the initial `vy` jumped between 41, 42 and 52 —
   three different jump types in a single reading.

And one consequence of principle: **a measurement must bear on an outcome**
(height reached, distance travelled, velocity profile), never on
the assumption that a specific frame saw the input.

## What this decision enables

It has a reach that `.dtm` does not: it works **in the menus**,
where Mario does not exist yet — the controllers are then found through their
vtable pointer (`0x803DF44C`). This is what makes a Dolphin instance
drivable from the logos all the way into gameplay without any intervention, and it is the
only reason `second_instance.py` is possible.
