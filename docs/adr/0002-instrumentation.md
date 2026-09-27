# ADR 0002 — Instrument through external memory access, not through the debugger

- **Date**: 2026-09-15
- **Status**: accepted

## Context

The initial plan describes phase 0 in terms of the Dolphin debugger: enable
*Debugging* mode, load `us.map`, set a memory breakpoint on write on
`TMarDirector + 0x54` or on Mario's `mVel.y`, and count the
hits.

This method assumes a human operator in front of the UI for each
measurement. Yet the useful measurements are numerous and repetitive: three tiers ×
several quantities, plus the before/after-fix comparisons. Each
round trip with an operator costs time and introduces variations that
pollute the comparison.

## Decision

Instrument from a third-party process, reading and writing the emulated
MEM1 directly through `ReadProcessMemory` / `WriteProcessMemory`.

## Reasons

1. **Automatable end to end.** A campaign across the three tiers with
   restoration runs in a single command.
2. **Valid comparisons.** The same script, the same sampling duration and
   the same starting state for each tier.
3. **Fast.** ~405 000 reads per second, i.e. a period of 2.5 µs. A
   substep lasts 2.1 ms: the margin is three orders of magnitude, no
   transition is missed.
4. **Self-validating.** See below — this is the decisive argument.
5. **No interaction with the emulator.** No breakpoint, no pause, no
   slowdown: the game runs normally during the measurement.

## Self-validation replaces the certainty of the breakpoint

A breakpoint misses nothing by construction; polling can. This is
the serious objection to this approach, and it is addressed through the very structure
of the observed quantity.

The accumulator changes in only two ways: `+vsyncRate` at the start of a frame,
`-5` at each substep. If the polling misses a transition, the observed difference
is no longer 5 but 10 or 15. **The script therefore checks that every decrement is
exactly 5 and that every increment is exactly the same value**; if a
single abnormal transition appears, the measurement is rejected instead of being
reported.

In practice, out of 750 transitions recorded at 30 FPS, the 600 decrements were
all 5 and the 150 increments all 20.

## Major consequence: data yes, code no

The measurement uncovered a limitation that must be known before writing
the slightest fix.

Dolphin compiles PowerPC code into native code and caches the blocks. An
external write to an **instruction** does not invalidate the cache:

> Writing `nop` at `0x802FCB24` does modify MEM1 (confirmed by re-reading) but
> **changes nothing in the behaviour** — the game keeps presenting 30 frames
> per second.

A write to a **data** value takes effect immediately, since the game
re-reads it on every execution.

This **rules out** the `gamemasterplc` fix (`042FCB24 60000000`) for any
live use, and requires going through `mRetraceCount`, which is a data value at
`TDisplay + 0x4C` and produces exactly the same effect (demonstrated in § 3.1 of
[`../01-mechanisms.md`](../01-mechanisms.md), then verified experimentally).

This is also the route BetterSunshineEngine takes — which itself runs
inside the game and therefore does not have this problem. The convergence is reassuring.

## Scope and limitations

- **Fixes applied this way do not survive** a restart of the game,
  and do not constitute a distributable mod. The purpose is measurement, not
  delivery. A real mod will go through Kuribo / BetterSunshineEngine.
- **Object addresses are dynamic.** `TDisplay`, `TMarDirector` and
  Mario are on the heap; their addresses change from one session to the next. Everything
  is therefore resolved at runtime from the globals `gpApplication`,
  `gpMarDirector` and `gpMarioOriginal`, never hard-coded.
- **Dolphin's host settings remain out of reach.** The VBI Frequency
  Override, needed for the 120 FPS tier, is not in MEM1. Another
  route will be needed.
- **Windows only.** `tools/dolphin.py` relies on the Win32 API.

## Rejected alternative

**Inject PowerPC code** into the free Gecko area (`0x80001800`–`0x80003000`,
verified to be entirely zero) to place exact counters, in the manner of a
`C2` code. Rejected: it runs into the same JIT cache as any write to
code, and self-validated polling already gives exact results without modifying
the game.
