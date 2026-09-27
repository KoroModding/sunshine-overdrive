# Phase 0 and test battery

> The initial plan requires: **phase 0 before any code**, and **write the tests before
> the fixes**. This document is the protocol and the readings.
>
> **Phase 0 executed on 2026-09-15** by external memory instrumentation
> (`tools/dolphin.py`), on Dolphin 2606a, GMSE01, Delfino Plaza. The measurements
> below are real. The tables that are still empty have not been measured.
>
> **Physics battery executed on 2026-09-15** at the same location, with
> input injection (`tools/pad.py`) and measurements indexed on the substep
> (`tools/substep_clock.py`). See also
> [`adr/0003-controller-injection.md`](adr/0003-controller-injection.md) and
> [`adr/0004-substep-measurement.md`](adr/0004-substep-measurement.md).

---

## Phase 0 — confirm the substep count

Static analysis established the *mechanism* of the accumulator
([`01-mechanisms.md` § 1](01-mechanisms.md)). It cannot establish the
*actual count* at runtime, nor whether a given `perform` belongs to a
simulation list or to a per-rendered-frame list: the lists are populated
at runtime and traversed through virtual dispatch.

### 0.A — Watchpoint on the accumulator (direct measurement)

The more direct of the two methods, and the one to do first.

1. Dolphin → View → Debugging Mode, load `work/maps/us.map`.
2. Start the game, reach a stable playable area (Delfino Plaza, Mario
   standing still).
3. Retrieve the `TMarDirector` pointer. Execution breakpoint on
   `0x80299838` (`direct()`): `r3` contains `this`.
4. Memory breakpoint **on write** on `this + 0x54`.
5. Count the hits between two passes at `0x80299938`
   (`unk54 += vsyncRate`), which delimits a rendered frame.

| Rate | Expected `vsyncRate` | Expected substeps/frame | **Measured** `vsyncRate` | **Measured** substeps/frame |
|---|---|---|---|---|
| 30 FPS (unpatched) | 20 | 4 | **20** | **4.000** |
| 60 FPS (patched) | 10 | 2 | **10** | **1.992** |
| 120 FPS (patched) | 5 | 1 | **5** | **1.000** |

Full readings, 4 s of sampling per tier:

| Tier | frames/s | substeps/s | simulation speed |
|---|---|---|---|
| 30 FPS (original) | 30.00 | 120.00 | **100 %** |
| 60 FPS | **60.00** | 119.50 | **99.6 %** |
| 120 FPS without VI overclock | 60.00 | 60.00 | 50 % — **half speed** |

The 120 tier caps out because presentation cannot exceed the VI field
rate (59.94 Hz). It requires Dolphin's **VBI Frequency Override** at
2×. This is not a flaw in the model: it is its confirmation.

The sampling is **self-validated** — out of 750 transitions recorded at 30 FPS,
the 600 decrements are all exactly 5 and the 150 increments all
exactly 20. No transition missed.

Also read the value of `r25` on exiting `0x8029986C`: it must be
exactly 20, 10, then 5.

### 0.B — Watchpoint on Mario's `mVel.y` (cross-check)

Method specified by the initial plan. It serves as an **independent check** of
0.A: it measures the number of executions of `movement()`, not the number of
subtractions from the accumulator. The two must agree.

1. Retrieve `gpMarioOriginal`, derive the address of `mVel.y` from it.
2. Memory breakpoint on write, Mario in free fall (jump from a
   high point) to guarantee one write per substep.
3. Count the hits per VI field, at 30 then at 60 FPS.

Expected: 4, then 2.

**Done differently, and more conclusively**: rather than a breakpoint
on `mVel.y`, the automated free fall (§ *Physics* below) counts the
position integrations. It gives **198 integrations at 30 FPS and 198 at
60 FPS** — an identical figure, i.e. ~120 Hz in both cases. This cross-checks 0.A
through a path entirely independent of the accumulator.

> 0.A and 0.B **agree**. The accumulator model is confirmed.

### 0.C — Classify the perform lists

Determine, for each object to fix, whether it is called per substep or per
rendered frame. This is the measurement that decides everything else.

1. Execution breakpoint on the object's `perform`.
2. Count the hits between two passes at `0x80299938`.

| Result | Classification | Correction needed |
|---|---|---|
| 4 at 30 FPS, 2 at 60 FPS | **simulation** list | none |
| 1 at 30 FPS, 1 at 60 FPS | **per-rendered-frame** list | factor `30 / rate` |

First object to screen: `TModelGate::perform` @ `0x801EB014`, to
settle the anomaly of § 4.3 of [`01-mechanisms.md`](01-mechanisms.md).

---

## Dedicated test — the `0x80414904` anomaly

The literal `0.01f` is a **per-call** increment of the `TModelGate` fade.
BSE and `gamemasterplc` **double** it at each tier. Both possible
readings of the classification rule say that one should either do nothing,
or **divide**. The experiment settles it:

| # | Rate | `0x80414904` | Expected fade duration if the patch is correct | Measured |
|---|---|---|---|---|
| 1 | 30 FPS | `0.01f` (original) | reference | |
| 2 | 60 FPS | `0.01f` (unpatched) | = ref. if simulation list; ½ ref. if per frame | |
| 3 | 60 FPS | `0.02f` (patched) | = ref. | |
| 4 | 120 FPS | `0.04f` (patched) | = ref. | |

Protocol: approach a gate in a straight line at constant speed from
beyond 1000 units, time it in number of VI fields between the
crossing of the threshold and `m0xD0 == 1.0f` (breakpoint on the write at
`0x801EB188`).

**If measurement 2 equals measurement 1**, `TModelGate::perform` is in a
simulation list, no correction is needed, and the `04414904` line
of the Gecko code must be removed.

---

## Regression battery

To be run at each tier, with the same inputs. The plan called for a
`.dtm` recording; the memory injection of `tools/pad.py` turned out to be
more convenient and, above all, scriptable — see
[`adr/0003-controller-injection.md`](adr/0003-controller-injection.md).

Unit of measurement: the **simulation substep**, counted by
`tools/substep_clock.py`. Neither the second nor the frame is suitable:

| Unit | Why it does not work |
|---|---|
| second | the number of frames covered changes with the rate, and the injection success rate with it |
| rendered frame | it is precisely the variable being changed |
| VI field | stable, but says nothing about the number of integrations executed |
| **substep** | **constant 120 Hz by construction — the only quantity common to all tiers** |

The detailed reasoning is in
[`adr/0004-substep-measurement.md`](adr/0004-substep-measurement.md).

### Physics — must never change

A discrepancy here means that the accumulator is not doing its job, and
**forbids** correcting it by editing the `.prm` files: it is the cause that must be
sought, not the symptom.

| Test | Measured quantity | 30 | 60 | 120 |
|---|---|---|---|---|
| **free fall** | **position integrations** | **198** | **198** | |
| **free fall** | **real duration** | **1.655 s** | **1.635 s** (+1.2 %) | |
| **free fall** | **distance travelled** | **3000.0** | **3000.0** | |
| **ballistic arc** (`vy` = 42) | **sequence of vertical velocities** | **identical** | **identical** | |
| **ballistic arc** | **integrations to apex** | **42** | **42** | |
| **ballistic arc** | **apex altitude** | **225.75** | **225.75** | |
| **short jump** (A, 6 substeps) | maximum height | 73.79 | 73.79 | |
| **run** (120 substeps) | maximum speed | 8.91 | 8.91 | |
| run — distance travelled | distance | *165.17* | *160.82* | |
| long jump (A, 40 substeps) | maximum height | *96.60* | *81.59* | |
| triple jump | maximum height | | | |
| dive | distance travelled | | | |
| slide | stopping distance | | | |
| hover (F.L.U.D.D.) | hover fields with a full tank | | | |

*In italics: measurements skewed by the scenery, see below. They are not
results, they are a lesson in method.*

*The running speed, for its part, matches to the decimal between tiers — but at
8.91, which is the value of a Mario pushing against an obstacle; on open
ground it rises towards 32. The automatic choice of direction
(`probe_open_direction`) therefore did not find a clearing from this starting
point. The coincidence remains informative, it is not the intended measurement.*

### The ballistic arc — the decisive measurement

```sh
python tools/test_ballistic.py 42 30 60
```

Mario is placed 2500 units above the ground, his vertical velocity is forced to 42, and
the arc is recorded substep by substep. No input, no contact, no
jump type: only the integrator remains.

```
suite vy à 30 FPS : [42.0, 41.0, 40.0, 39.0, 38.0, 37.0, 36.0, 35.0, 34.0, …]
suite vy à 60 FPS : [42.0, 41.0, 40.0, 39.0, 38.0, 37.0, 36.0, 35.0, 34.0, …]
=> suites IDENTIQUES sur 90 intégrations.
```

**Gravity = exactly 1.0 velocity unit per substep, at both tiers.**
Apex at 225.75 on both sides, 42 integrations to the apex. Together with free
fall, this is the most direct demonstration that the physics is decoupled from
the display rate.

### The long jump false alarm — read before interpreting a discrepancy

The first reading reported `ÉCART SIGNIFICATIF`: 96.60 versus 81.59 on the
long jump height, a 14.66 % discrepancy, perfectly reproducible. Three
hypotheses were ruled out by measurement:

| Hypothesis | Check | Verdict |
|---|---|---|
| input injection is random | intra-tier variance over 6 trials | **ruled out** — 0.00 range at 60 FPS |
| the jump type differs (double, triple) | initial `vy` recorded | **ruled out** — 42.0 at both tiers |
| the release of A is seen later at 30 FPS | sweep from 6 to 150 substeps of holding | **ruled out** — height insensitive to duration |

What remains is the scenery: a free arc from `vy` = 42 peaks at **225.75**, whereas
the two measured jumps topped out at 96.60 and 81.59. Mario was hitting a ceiling
or an overhang near the wall chosen as the "clear" direction. It was not
physics.

**The lesson lies in the tooling.** An apex height and a distance
travelled are *output* quantities: they measure the terrain as much as
the integrator. `tools/test_physics.py` was therefore revised — its verdict now
rests on the **per-substep profiles** (sequence of velocities), with heights and
distances now only indicative. This revision **has not yet been
re-run** on a running Dolphin; the table above is the one
from the old criterion.

### To do at the next measurement session

In this order — each item conditions the next:

1. **Choose a clear starting point** before anything else. Delfino Plaza at the
   foot of the wall skews both the run (8.91 instead of ~32) and the jump
   (ceiling). The beach or a large square are suitable; the test will say so
   itself, since `probe_open_direction` must report a distance clearly
   greater than 165.
2. **Re-run `test_physics.py`** with the profile criterion. It is the only
   part of the project whose code has changed without being re-executed.
3. **Measure the 120 tier** with the VBI Frequency Override at 2×. Everything is
   ready: `second_instance.py start --vi 2.0` launches, navigates and reaches gameplay
   on its own. Do not do it while another instance is running — they
   compete for the GPU and the measured rate no longer means anything.
4. **Fill in the empty rows** of this document: triple jump, dive,
   slide, hover. They require input sequences, not new
   mechanics.

### Timed per rendered frame — designated suspects

These elements are the ones the initial plan lists as broken. Each must be
classified with method 0.C before being fixed.

| Test | Measured quantity | 30 | 60 | 120 |
|---|---|---|---|---|
| dialogue box | display fields (`0x251`: 20 / 40 / 80) | | | |
| `TSMSFader` | fade fields | | | |
| HX Circle transition | fields | | | |
| HX GameOver transition | fields | | | |
| Shine select screen | fields per scroll step | | | |
| intro cutscene | fields, start to end | | | |
| level loading | fields | | | |
| `TModelGate` fade | fields (see above) | | | |

### Objects and enemies

| Test | Measured quantity | 30 | 60 | 120 |
|---|---|---|---|---|
| bird flock (`TBoidLeader`) | fields for one loop lap | | | |
| eel boss | fields per phase | | | |
| Petey Piranha | fields per attack cycle | | | |
| `TJointCoin` / SandBird | animation fields | | | |
| FireWanwan | movement speed | | | |
| scripted enemy (Strollin' Stu) | fields per patrol cycle | | | |

---

## Instrumentation

What the project actually uses:

- **Emulated memory** — `tools/dolphin.py`, reading/writing MEM1 from
  outside. No debugger, no breakpoint, no action in the UI.
- **Reversible fixes** — `tools/patch.py`, which only writes data
  (the JIT ignores writes to code).
- **Inputs** — `tools/pad.py`, injection into `TMarioGamePad`.
- **Clock** — `tools/substep_clock.py`, on the director's accumulator.

What the plan called for, kept in reserve:

- **Breakpoints** — Dolphin, View → Debugging Mode, map loaded from
  `work/maps/us.map`. Still needed for step 0.C: classifying a `perform`
  requires counting its executions, which no memory read provides.
- **RAM search** — `dolphin-memory-engine` (aldelaro5).
- **Field counting** — `VIDEOINTERFACE` log at DEBUG level: `LogField()`
  emits `WPL / STD / EQU / PRB / ACV / PSB` at every field.
- **`.dtm` recording** — replaced by memory injection, which has the advantage
  of being driven from the same script as the measurement.

---

## Recording rule

A measurement row is filled in only if it has been **executed**. A value
expected by calculation is written in the "expected" column, never in
"measured". A half-empty table is information; a table filled with
guesses is a trap for the rest of the project.

---

## 120 FPS tier — readings of 2026-09-22

Dolphin 2606a, GMSE01, Delfino Plaza. Profile `deliver/GMSE01.ini` applied,
VI overclocked to 2×.

### Rate

`measure_substeps.py` and `validate_120.py`, five successive measurements.

| Quantity | Expected | Measured |
|---|---|---|
| `vsyncRate` | 5 | **5** |
| frames presented | 119.88 /s | **119.87 · 119.80 · 119.80 · 119.80 · 119.83** |
| substeps | 120.00 /s | **119.87 · 119.80 · 119.80 · 120.00 · 120.00** |
| substeps per frame | 1.000 | **1.000 · 1.000 · 1.000 · 1.002 · 1.001** |
| simulation speed | 100 % | **99.8 – 100.0 %** |

Sampling self-validated at each measurement: all decrements are
exactly 5, all increments exactly 5.

**One outlier measurement, kept here.** A sixth measurement, taken just after a
scene change, recorded **87.33 frames/s and 87.50 substeps/s**, i.e.
72.9 % of the correct speed. The next four measurements returned to
119.8 without intervention. At 120 FPS, the host has no headroom left: when Dolphin
cannot hold the rate, **the game genuinely slows down** — there is no
catch-up mechanism. The stutter has not been characterized.

### Physics — ballistic arc

`python tools/test_ballistic.py 42 30 120`

| Quantity | 30 FPS | 120 FPS | Verdict |
|---|---|---|---|
| sequence of vertical velocities | reference | **identical over 90 integrations** | ✔ |
| integrations to apex | 42 | **42** | ✔ |
| apex altitude | 225.75 | **225.75** | ✔ |

The same values as at the 30 and 60 tiers recorded in session 3. Gravity is
1.0 velocity unit per substep at all three tiers.

### Physics — free fall

`python tools/test_freefall.py 3000 120`

| Quantity | 30 FPS (session 2) | 120 FPS | Discrepancy |
|---|---|---|---|
| real duration of a 3000 u fall | 1.655 s | **1.656 s** | **0.06 %** |
| integrations | 198 | 199 | 1 |

The real duration is the measurement that matters: it says that the game runs at the correct
speed **in real time**, and not only per substep. The one-unit discrepancy in the
integration count is a side effect of the detector, not a difference in
physics — the ballistic arc, for its part, is exact to floating-point precision.

### What did not pass

| Topic | Status |
|---|---|
| JPA particles | **broken then compensated** — see below |
| audio under VI overclock | **not judged** — the instrumentation hears nothing |
| HX transitions, fades, dialogue timers | **not tested**, and expected to be wrong (×4) |
| bosses, scripted enemies | **not tested** |

### Particles — the defect found in use

Reported by eye, not by a test: frozen water jets, and the entry animation into
a graffiti missing. Cause in [`01-mechanisms.md` § 5](01-mechanisms.md) —
`JPAEmitterManager::calc()` called `(int)SMSGetAnmFrameRate()` times per frame,
i.e. **zero** at 120 FPS.

Fix applied (`0x802887B0 → li r23, 1`): **verified present in memory**,
**not verified by eye**. And it is imperfect by construction — it advances
the particles at 120 Hz instead of 60.

**Test to write**: time the lifetime of a JPA effect at all three
tiers. It is the only way to measure the factor of 2 rather than deduce it.
