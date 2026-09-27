# ADR 0004 — Measure in substeps, and judge on profiles

- **Date**: 2026-09-15, revised on 2026-09-17
- **Status**: accepted

## Context

The whole project rests on a comparison: *should the same quantity, measured at 30 and
at 60 FPS, change?* The validity of the answer depends entirely on
how the measurement is framed.

The first comparisons were framed by the wall clock — "record
for 0.5 second". Result: 15 % discrepancies on a jump height,
which measured nothing other than the instrumentation.

## Decision 1 — the unit of measurement is the substep

| Unit | Flaw |
|---|---|
| second | does not cover the same number of frames depending on the rate, and the success rate of input injection varies with that number |
| rendered frame | it is precisely the variable being changed |
| VI field | stable, but says nothing about the number of integrations executed |
| **substep** | **constant 120 Hz by construction, whatever the rate** |

"The state after 40 substeps" is a quantity comparable between tiers.
"The state after 0.5 s" is not.

The count is made without a breakpoint, by observing the decrements of
the accumulator `TMarDirector + 0x54`: it loses exactly 5 units per
substep. The measurement remains self-validating — any decrement other than 5
signals a failed poll, and the measurement is rejected
(see [`0002-instrumentation.md`](0002-instrumentation.md)).

## Decision 2 — the verdict bears on profiles, not on scalars

A corollary discovered through failure, on 2026-09-15.

Once the unit was corrected, the test still reported a discrepancy: jump height
96.60 versus 81.59, reproducible, even though the initial impulse was
identical (`vy` = 42) at both tiers. Three hypotheses were ruled out by
measurement — randomness of the injection, different jump type, resolution of the
release of A.

The explanation lay in the **scenery**: a free arc from `vy` = 42 peaks at
225.75; the two jumps topped out much lower because Mario was hitting an
overhang. The measurement was correct, the quantity was poorly chosen.

An apex height and a distance travelled are **output**
quantities: they aggregate the integrator *and* the level geometry. What
distinguishes the two tiers must be sought in a quantity that depends
only on the integrator:

- the **sequence of velocities**, substep by substep;
- the **number of integrations** up to a given event.

Two decoupled tiers produce the same sequence, identically. This is verified:
90 identical integrations between 30 and 60 FPS
([`../04-tests.md`](../04-tests.md)).

## Consequences

- `tools/substep_clock.py` provides the unit; the whole battery uses it.
- `tools/test_ballistic.py` is the reference measurement: impulse imposed at
  altitude, neither input nor contact, nothing but the integrator.
- `tools/test_physics.py` keeps heights and distances but no longer has them
  carry the verdict. **This revision has not yet been re-run** on a
  running Dolphin.
- General rule going forward: **before concluding there is a physics discrepancy,
  measure the intra-tier variance.** A discrepancy between tiers means nothing
  as long as the measurement already varies from one trial to the next within a single tier.
