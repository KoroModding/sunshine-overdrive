# ADR 0005 — Deliver the 120 tier through `[OnFrame]`, not through `[Gecko]` nor through live writes

- **Date**: 2026-09-22
- **Status**: accepted

## Context

The 120 FPS tier requires three writes, two of which target
**instructions**:

| Address | Nature | Role |
|---|---|---|
| `0x804167B8` | data (f32) | logic clock at 120 Hz |
| `0x802FCB24` | **instruction** | one VI field per presented frame |
| `0x802887B0` | **instruction** | unfreezes the particle system |

Yet [ADR 0002](0002-instrumentation.md) established that an external write to
an instruction **has no effect**: Dolphin keeps executing the JIT block
already compiled. Code fixes are therefore out of reach of
`tools/dolphin.py`, however useful they may be.

Three routes were open.

## Routes tried

### 1. `[Gecko]` section of the per-game profile — failure

The two rate lines were first delivered in `[Gecko]`, on the model
of `gamemasterplc`'s `$60FPS`, with the name repeated in `[Gecko_Enabled]`.

With the game started, `0x80001800` was **entirely zero**: no codehandler
injected, hence no active code. The `[Core]` section of the *same file* had
nonetheless taken effect — the VI overclock was in force, the game was running at
double speed. `EnableCheats = True` was set globally.

**Cause not elucidated.** Unverified lead: the "Enable Cheats" checkbox of
the UI, which would gate the codehandler without gating `[Core]`.

### 2. Live data writes — works, but incomplete

`tools/keep120.py` sets `0x804167B8 = 2.0f` and `mRetraceCount = 1`, which
gives the correct rate without touching an instruction. **Measured: 119.80
frames/s, 119.80 substeps/s.**

But this route cannot unfreeze the particles, which require a code
fix. And it requires a resident process.

### 3. `[OnFrame]` section of the per-game profile — chosen

Dolphin's PatchEngine applies these writes **at boot, before the
JIT compiles the block concerned**: an instruction fix therefore takes
effect there, unlike an external write.

Verified on 2026-09-22: the three values re-read in memory after restart,
and validation at **119.83 frames/s, simulation at 120.00 Hz, 100.0 % of the
correct speed**.

## Decision

Deliver the profile in the `[OnFrame]` section of the file
`GameSettings/GMSE01.ini` in Dolphin's user directory.

Keep `tools/keep120.py` as a **safety net** — it sets the rate
through data writes if the host profile does not apply — and not as the
main mechanism.

## The stacking to avoid

The `nop` at `0x802FCB24` and `mRetraceCount = 1` both lead to one field per
frame, **but they add up**: once neutralized, `waitForRetrace` consumes
`count - 1` fields per call (§ 3.1 of [`../01-mechanisms.md`](../01-mechanisms.md)).
With `count = 1`, that makes **zero** — no more waiting for the scan, the game
races at the host's speed.

`keep120.py` and `validate_120.py` therefore read `0x802FCB24` before deciding on
the expected count. The guard worked the first time in a real situation.

## What the decision costs

- **The profile only takes effect at boot.** Changing tier requires a
  restart of the game, whereas data writes were immediate. For
  comparative measurement campaigns, `patch.py` and `keep120.py` remain the
  right tools.
- **One line of the profile is not correct by construction**:
  `0x802887B0 → li r23, 1` advances the particles at 120 Hz instead of 60.
  See [`../01-mechanisms.md`](../01-mechanisms.md) and the § on the profile.
