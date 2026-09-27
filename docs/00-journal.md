# Logbook

> Append-only. Each entry states **what was done**, **what came out of it**
> and **what remains open**. Conclusions then migrate to the thematic
> documents; the logbook keeps a record of the path taken, including dead
> ends.

---

## 2026-09-15 — Session 1: setup and static verification

### Done

- Identification of the available images. The image initially provided was
  **PAL (`GMSP01`)** whereas the plan is written for US. Flagged; the US image
  (`GMSE01`) was added. Decision recorded in
  [`adr/0001-target-region.md`](adr/0001-target-region.md).
- Writing of the tooling: `gciso.py`, `dol.py`, `symbols.py`, `disasm.py`,
  `xref.py`. See [`03-tooling.md`](03-tooling.md).
- Extraction of both DOLs, retrieval of `us.map` (15107 symbols, consistent
  with the plan).
- Disassembly and analysis of `TMarDirector::direct()`,
  `SMSGetVSyncTimesPerSec()`, `SMSGetAnmFrameRate()`,
  `JDrama::TVideo::waitForRetrace()`, `TModelGate::perform()` and
  `TModelGate::loadAfter()`.

### Outcome

Five points that the initial plan classified as "not verified" are **resolved**, and
two of its claims are **corrected**.

| Point | Status before | Status after |
|---|---|---|
| identity of `0x804167B8` | deduced from the splits | **verified** — `lfs f0,-0x3e8(r2)` in `SMSGetVSyncTimesPerSec` |
| instruction neutralised by `042FCB24` | not identified | **verified** — `bl VIWaitForRetrace` |
| identity of `0x80414904` | not identified | **verified** — `TModelGate` fade rate |
| accumulator mechanism | pseudo-code not cross-checked | **verified** on the machine code (`li 0x258`, `divw`, `addi -5`) |
| "nop ≡ `mRetraceCount = 1`" | asserted without proof | **demonstrated** by the steady state |

**Corrections made to the plan:**

1. *"the `break` of the last substep makes the draw branch unreachable —
   the decompiled code is self-contradictory"*. The machine code **is not
   contradictory**. The `0x4000` flag survives the return from `direct()` and the
   draw block runs at the start of the next call. It is a loop whose
   entry point is in the middle, which the decompiler renders poorly.
   → [`01-mechanisms.md` § 1.2](01-mechanisms.md)

2. *"`0x8040DD10` and `0x8040BE54`: wrong JP port in BSE"*. These are
   **PAL** addresses, not badly ported JP addresses. Verified in the PAL DOL:
   `0x8040DD10` contains `0.5f` and is loaded by the exact counterpart of
   `SMSGetVSyncTimesPerSec` at `0x8029FC8C`.
   → [`05-regions.md`](05-regions.md)

**Findings not anticipated in the plan:**

- `0x804167B8` has **three** consumers, the third being
  `TApplication::drawDVDErr()`. The patch affects the disc error screen.
- The `600` in `direct()` is an immediate (`li r3, 0x258`), not a memory
  literal: **not patchable** by a simple write. Only the divisor is.
- Patched **and** `count = 1`, `waitForRetrace` no longer waits for any field — a
  way of unlocking presentation that does not go through the VBI Override.
  Not tested.
- In PAL, the "60 FPS" code produces **50 FPS** outside EURGB60 mode.

### Open

- **Phase 0 not executed.** No runtime measurement has been made. The
  substep count remains a static conclusion.
  → [`04-tests.md`](04-tests.md)
- **`0x80414904` anomaly.** BSE and `gamemasterplc` *double* a per-call
  increment where the classification rule says one should either do nothing
  or divide. Three possible explanations, none ruled out. Do not copy
  this Gecko line by imitation before measuring.
  → [`01-mechanisms.md` § 4.3](01-mechanisms.md)
- **Classification of the perform lists.** Undeterminable statically
  (virtual dispatch). Blocks the classification of every object to be
  fixed.
- **ASM hooks not analysed**: `0x800066EC` (`TBoidLeader`) and `0x80C28028`.
- **Dolphin not launched.** No verification under emulation.

---

## 2026-09-15 — Session 2: phase 0 executed, 60 FPS tier validated

Dolphin 2606a running, GMSE01 loaded, Delfino Plaza.

### Done

- Writing of `tools/dolphin.py`: access to the emulated MEM1 from outside,
  via `ReadProcessMemory` / `WriteProcessMemory`. The mapping is located
  by sweeping the process regions and **validated by reading the GameCube disc
  header** — which at the same time confirms which image is loaded.
  Decision recorded in [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).
- `tools/measure_substeps.py`, `tools/patch.py`, `tools/test_freefall.py`.
- Phase 0.A and 0.B executed, measurement campaign at all three tiers, presentation
  law test, free-fall regression test.

### Outcome

**The plan's model is confirmed across the board.** No measurement
contradicts it.

| Measurement | Expected | Obtained |
|---|---|---|
| `vsyncRate` at 30 FPS | 20 | **20** |
| substeps per frame at 30 FPS | 4 | **4.000** |
| substeps per second at 30 FPS | 120 | **120.00** |
| substeps per frame at 60 FPS | 2 | **1.992** |
| frames per second at 60 FPS | 60 | **60.00** |
| simulation speed at 60 FPS | 100 % | **99.6 %** |
| physics integrations, 3000 u fall | identical | **198 at 30 FPS, 198 at 60 FPS** |

The sampling is self-validated: at 30 FPS, over 750 transitions, the 600
decrements are all exactly 5 and the 150 increments all exactly 20.

**Presentation law verified experimentally** — `mRetraceCount = N` gives
59.94/N frames per second:

| N | 1 | 2 | 3 | 4 | 0 |
|---|---|---|---|---|---|
| frames/s measured | 59.67 | 30.00 | 20.00 | 15.00 | 60.00 |
| 59.94/N expected | 59.94 | 29.97 | 19.98 | 14.98 | — |

Including the prediction that `N = 0` and `N = 1` are indistinguishable, derived in
§ 3.1 of [`01-mechanisms.md`](01-mechanisms.md).

**Obstacle found and worked around — the JIT cache.** Writing `nop` at `0x802FCB24`
does modify MEM1 (confirmed by reading back) but **changes nothing**: Dolphin
keeps executing the compiled block. The `gamemasterplc` fix is therefore
not applicable live from outside.

Workaround: `mRetraceCount` is **data**, at `TDisplay + 0x4C`, and
`TDisplay` is reached via `gpApplication + 0x1C`. Writing it produces exactly the
same effect, without touching an instruction. It is also BSE's approach.
→ general rule: **data yes, code no**.

**The 120 FPS tier is blocked by the VI, as expected.** Literal at `2.0f` and
`mRetraceCount = 1` do give 1 substep per frame, but presentation
caps at 60 frames/s (the VI only delivers 59.94 fields/s): the simulation
drops to 60 Hz and the game runs at **half speed**. Dolphin's **VBI Frequency
Override** at 2× is required.

### Open

- **120 FPS tier not demonstrated.** The VBI Frequency Override is a Dolphin host
  setting, absent from MEM1 and not reloadable live from the
  configuration file. It requires either an action in the UI, or
  a restart of Dolphin with the modified configuration.
- **`0x80414904` anomaly still open.** The loaded level contains
  **no** `TModelGate` instance (MEM1 sweep by vtable
  `0x803D3F9C`: 0 results). Timing the fade requires a level that
  contains one. Classification of the perform lists has however progressed
  statically — see § 1.3 of [`01-mechanisms.md`](01-mechanisms.md).
- **Regression battery incomplete.** Only free fall is done. The
  jump, run and slide tests require controller inputs; the
  transition and boss tests require reaching the relevant situations.
- **ASM hooks not analysed**: `0x800066EC` (`TBoidLeader`) and `0x80C28028`.

---

## 2026-09-15 — Session 3: automated inputs, physics settled

Same environment: Dolphin 2606a, GMSE01, Delfino Plaza.

### Done

- `tools/pad.py` — controller input injection by writing into
  `TMarioGamePad`. Decision and limits in
  [`adr/0003-controller-injection.md`](adr/0003-controller-injection.md).
- `tools/substep_clock.py` — counting substeps by observing the
  accumulator, to frame measurements other than by wall-clock time.
  [`adr/0004-substep-measurement.md`](adr/0004-substep-measurement.md).
- `tools/test_physics.py` — short jump, long jump, run, at both tiers.
- `tools/test_ballistic.py` — imposed ballistic arc, with no input or contact.
- `tools/dolphin_host.py`, `tools/second_instance.py` — two attempts to
  reach the host setting on which the 120 tier depends.

### Outcome

**Physics is strictly independent of the frame rate.** The ballistic arc
gives the same sequence of vertical velocities over **90 integrations** at 30 and
60 FPS, the same number of integrations up to the apex (**42**) and the same
apex altitude (**225.75**). Gravity is exactly 1.0 velocity unit
per substep. Together with the 198 free-fall integrations recorded in
session 2, the question is closed.

→ [`04-tests.md`](04-tests.md)

**The `TMario` offsets are proven, not deduced.**
`SMS_SetMarioAccessParams()` @ `0x80273A0C` publishes a dozen pointers
into the object: position at `+0x10`, velocity at `+0xA4`, angles at
`+0x94`. Twenty-five instructions that replace an entire session of memory
searching. → [`02-addresses.md`](02-addresses.md)

**The jump triggers on the edge, not on the hold.** Writing `+0x18`
(hold) does nothing, writing `+0x1C` (edge) makes Mario jump. Cross-checked with
`JUTGamePad::update`, which copies this block from the static array
`0x80404484 + port × 0x30`.

**Three dead ends, kept here because they are expensive to rediscover:**

1. *The keyboard is out of reach.* `SendInput` does not reach the interactive
   desktop from this context — even `GetAsyncKeyState` in the injecting
   process does not see the keystroke. All keyboard automation is ruled out.
   `tools/dolphin_host.py` keeps a record of it.
2. *A permanent edge produces triple jumps.* Replaying the edge on every
   frame amounts to pressing A again on landing. The height of the same jump
   then varied from 73.79 to 140.0, with three distinct initial `vy`
   (41, 42, 52).
3. *The title screen launches an attract demo.* During it
   `gpMarDirector` and `gpMarioOriginal` are perfectly valid: an
   instantaneous test wrongly concludes "in game". The arrival criterion therefore requires
   several seconds of stability.

**An instructive false alarm.** The first reading reported
`ÉCART SIGNIFICATIF`: 96.60 versus 81.59 on the long jump height,
reproducible. Three hypotheses ruled out by measurement (injection randomness, jump
type, release resolution), and the cause was the scenery — Mario was hitting
an overhang. An apex height measures the ceiling as much as gravity.

**Second Dolphin instance controllable end to end.** Isolated user
directory, `VIOverclock = 2.0` passed on the command line, memory card
copied, and a complete run-through — logos, intro, title screen, file
select — by memory injection alone. Stable in-game arrival in **92.6 s**,
with no intervention at all.

### Open

- **120 FPS tier still not measured.** The second instance was in game, the
  VI at 2×, the measurement was about to be launched — the session stopped there.
- **`0x80414904` anomaly** — unchanged, still waiting for a level
  containing a `TModelGate`.
- **Classification of the perform lists (0.C)** — unchanged. It is the only point of
  phase 0 that still requires a breakpoint: counting the executions of a
  function cannot be read from memory.
- **ASM hooks not analysed**: `0x800066EC` (`TBoidLeader`) and `0x80C28028`.

---

## 2026-09-17 — Session 4: consolidation, and the 120 path put on hold

No new measurement: Dolphin was not running, and the instruction received
was **not to launch a second instance**. Clean-up session.

### Done

- Recording of session 3, which had remained entirely outside the documentation:
  logbook, test readings, address register, tooling, and the two ADRs
  above.
- The offsets used by `pad.py`, `test_physics.py` and `test_ballistic.py`
  are now entered in the register with their level of proof. They
  circulated in the code without appearing there, which the project rule forbids.
  All have moved to **M**: `SMS_SetMarioAccessParams` proves the offsets of
  `TMario`, `setGamePad` that of `mGamePad`, `updateMeaning` and
  `checkController` those of the controller.
- **Revision of the `test_physics.py` criterion.** Its verdict was based on
  heights and distances — the quantities that had produced the false
  alarm. It is now based on the per-substep velocity profiles; the
  scalars remain displayed, with no verdict value. The profiles are aligned
  on the event (first non-zero value) and not on the start of polling:
  since the injected input is not seen on the same frame depending on the frame rate, two
  identical profiles would otherwise have seemed to diverge from their first element.
  The three pure functions that carry this computation are verified offline.
- `second_instance.py` and `dolphin_host.py` completed: their documented
  commands now actually exist. `second_instance start` **refuses**
  to start if an instance is already running, since two instances fight over the GPU.
- The keyboard dead end is written at the top of `dolphin_host.py`, instead of
  existing only in a session's history.

### Open

Unchanged from session 3, plus one point:

- **The revision of the `test_physics.py` criterion has not been replayed.** The code
  compiles, its pure functions pass an offline check, but no
  execution has confronted it with the game. The reading in `04-tests.md` is still that of
  the old criterion and says so.

---

## 2026-09-22 — Session 5: 120 FPS tier reached, measured, and two defects found

Dolphin 2606a, GMSE01, Delfino Plaza. First session in which the game actually
runs at 120 FPS.

### Done

- **Delivery**: `deliver/GMSE01.ini` (Dolphin per-game profile),
  `tools/install_profile.py` (reversible installation), `tools/keep120.py`
  (holding the tier by writing data), `tools/validate_120.py`
  (check of both halves + verdict on the simulation speed).
- Measurement campaign at the 120 tier, ballistic regression 30 vs 120, free
  fall at 120.
- Static analysis of `TMarioParticleManager::perform`, `TMapObjWaterSpray::calc`
  and `TMario::warpInEffect` following two reported visual defects.

### Outcome

**The 120 FPS tier is reached and measured.** This had been the open point since
session 3.

| Measurement | Expected | Obtained |
|---|---|---|
| `vsyncRate` | 5 | **5** |
| frames presented | 119.88 /s | **119.87 · 119.80 · 119.80 · 119.80** |
| substeps | 120.00 /s | **119.87 · 119.80 · 119.80 · 120.00** |
| substeps per frame | 1.000 | **1.000** |

Physics unchanged: ballistic arc **identical over 90 integrations** between 30
and 120 FPS, 42 integrations up to the apex, apex at 225.75 — the same
values as at the 30 and 60 tiers in session 3. Free fall of 3000 units in
**1.656 s** versus 1.655 s recorded at 30 FPS in session 2, i.e. **0.06 %**.
The integration count recorded is 199 versus 198: a one-unit difference on an
edge detector, not a difference in physics.

**Dolphin's `[Gecko]` did not load.** The profile initially delivered the two
frame-rate writes in the `[Gecko]` section, modelled on `gamemasterplc`'s
`$60FPS`. With the game started, `0x80001800` was **entirely zero**: no
codehandler injected, no active code — while the `[Core]` section of the
*same file* had indeed taken effect, `EnableCheats = True` being also
set globally. Cause not elucidated.

Intermediate state observed, and instructive: **VI at 2× without a game-side fix
= game at double speed**. This is the row of the table in `deliver/README.md` that
until then had only been deduced.

Workaround adopted: the data writes, proven since session 2.
→ [`adr/0005-gecko-or-data.md`](adr/0005-gecko-or-data.md)

**Two visual defects reported, a single cause.** Plaza water jets
frozen; shrinking animation on entering a graffiti missing — "he
jumps and disappears". Both are JPA, and the cause is exact:

```
802887A4  bl SMSGetAnmFrameRate()        ; 60 / logic clock
802887A8  fctiwz f0, f1                  ; truncation to integer
802887B0  lwz    r23, 0x94(r1)           ; loop counter
802887B8  bl     JPAEmitterManager::calc()
802887C0  addi   r23, r23, -1
802887C8  bgt    802887B8
```

The number of calls to `JPAEmitterManager::calc()` per rendered frame is
`(int)SMSGetAnmFrameRate()`: **2** at 30 FPS, **1** at 60, **0 at 120**. The
particle system no longer advances at all. Since `TMario::warpInEffect()` goes
entirely through `gpMarioParticleManager` (`emitAndBindToMtx`, callback
`TWarpInCallBack`), the "little circle" is emitted but never advanced, hence
invisible.

This is the only place where the 0.5 value of `SMSGetAnmFrameRate()` breaks: everywhere
else it is consumed as a float, and 0.5 is **correct** there.

**BetterSunshineEngine does not fix this point.** Its `src/patches/fps.cpp`,
retrieved and reread, mentions neither JPA nor the particle manager, and its
`case FPS_120` only sets `mRetraceCount = 0`, `0x804167B8 = 2.0f` and
`0x80414904 = 0.04f`. **Its 120 FPS mode therefore has the same defect.**

**A dangerous stacking, found before suffering it.** The `nop` at `0x802FCB24` and
`mRetraceCount = 1` both lead to one field per frame, but they
add up: `count - 1` with the `nop`, i.e. **zero** fields, hence no
wait for the retrace at all. `keep120.py` and `validate_120.py` now read
`0x802FCB24` before deciding on the count.

### Open

- **The particle fix is not verified.** `0x802887B0 → li r23, 1`
  is set in the `[OnFrame]` section of the profile, but **the game has not been
  restarted**: the session stopped there. Two unknowns at once — does the
  fix work, and does Dolphin's `[OnFrame]` apply where
  `[Gecko]` failed. If `[OnFrame]` goes through, the profile fits in a single
  file and `keep120.py` becomes optional.
- **This fix is an imperfect compensation, and acknowledged as such.**
  Forcing the counter to 1 makes the particles advance at 120 Hz instead of the original
  60: twice too fast. The exact fix requires a call every other
  frame, hence state, hence an ASM hook. It is the only line of the
  profile that is not correct by construction.
- **Why `[Gecko]` did not load.** First lead to check: the
  "Enable Cheats" checkbox in Dolphin's configuration, which would gate the
  codehandler without gating `[Core]`.
- **Audio has not been assessed.** The instrumentation reads memory, it hears
  nothing. The VI overclock scales the emulated CPU clock and the AudioDMA period
  derives from it; the initial plan claims that sound is not affected, this remains a
  claim.
- **The host cost is not characterised.** One measurement out of four recorded
  87.5 frames/s instead of 119.8 — and at 87.5 frames the simulation drops to
  72.9 % of the correct speed, that is **the game really
  slows down**. The next three measurements returned to 119.8. Hitch not explained.
- **The rest of the "what still breaks" inventory is untouched**: eel
  boss, dialogue timers, HX transitions, `TSMSFader`, Shine
  select screen, loading loops.
- **`0x80414904` anomaly** — unchanged, still absent from the profile.
- **Classification of the perform lists (0.C)** — unchanged.
- **ASM hooks not analysed**: `0x800066EC` (`TBoidLeader`) and `0x80C28028`.

### To redo when restarting the tooling

`keep120.py` was running in the background and stops with the terminal. After
restarting the game, relaunch:

```sh
python tools/validate_120.py      # waits for the game, then gives a verdict
python tools/keep120.py           # only if [OnFrame] was not applied
```

### Addendum, same session — `[OnFrame]` applies, profile in a single file

The game was restarted before the end of the session. The three writes of the
profile are in memory, read back one by one:

| Address | Value read | Expected |
|---|---|---|
| `0x804167B8` | `40000000` | `2.0f` |
| `0x802FCB24` | `60000000` | `nop` |
| `0x802887B0` | `3AE00001` | `li r23, 1` |

`mRetraceCount` is **2**, its original NTSC value: the `nop` alone
carries per-field presentation, and `keep120.py` detects it and refrains.

Full validation: **119.83 frames/s, simulation at 120.00 Hz, i.e. 100.0 %
of the correct speed.**

Three consequences:

1. **Dolphin's `[OnFrame]` applies where `[Gecko]` failed.** The
   PatchEngine writes before the JIT compiles the block, which makes it possible to
   patch an *instruction* — impossible by a live external write.
   The cause of the `[Gecko]` failure remains unknown, but it is no longer
   blocking.
2. **The profile fits in a single file** and `keep120.py` becomes optional:
   a safety net, no longer the main mechanism.
3. **The dangerous stacking did not occur**, the guard added just before
   having worked on the first try in a real situation.

Tooling bug fixed along the way: `keep120.py` died on `RuntimeError`
when the game stopped, instead of reattaching. It now waits for the game,
survives a restart and remaps itself onto the new MEM1.

**Still to be checked by eye**: that the water jets and the graffiti entry
animation have actually come back, and how much the particles
look twice too fast.

## Session 6 — 2026-09-22 — jets twice too fast, music frozen

Feedback from the author's eye and ear, session 5 profile applied:
**the water jets are twice too fast** (expected: this was the
`li r23, 1` compensation) and **the plaza music does not loop, then no
music at all**.

### Music — memory reading, game running

| Quantity | Value read | Interpretation |
|---|---|---|
| `MSBgm::smBgmInTrack[0]` → handle | `JAISound` sound `80010001`, state 4 | JAI believes it is playing |
| `JAISeqParameter+0x04` (JAI tempo, current) | 1.0 | JAI requests a normal tempo |
| JASystem root 1, `TTrack+0x3B0` (effective tempo) | **0.0** | root 0: 0.2398 |
| root 1, `TOuterParam+0x18` (multiplier) | **0.0**, switch `0x40` set | root 0: 1.0 |
| timers of the 6 child tracks | identical 2 s apart | root 0 counts down |

The tempo requested by JAI never reached the player: multiplier left at
its initialisation value 0.0, zero effective tempo, sequence frozen — silent, and
therefore never returned to the start.

`MSound::mainLoop` — the only caller of `JAIBasic::startFrameInterfaceWork` —
is called once per frame by `TApplication::gameLoop()+0x38C`. The counter
`JAISound+0x14`, incremented on each pass, advances at **~120/s**: the JAI
layer runs four times faster than originally.

**Hypothesis, not demonstrated**: at 120 Hz, JAI chains sequence start and
parameter transmission faster than the audio thread consumes them, and the
tempo transmission gets lost. Consistent with the reading, not proven by it.
Independently of the exact cause, all JAI fades are counted in frames
and were running 4× too fast.

### Fixes — two stateful routines

`tools/build_caves.py` assembles two routines at `0x80002F00` (Gecko
codehandler area, read as entirely zero in game) and emits their
`[OnFrame]` lines:

- **particles**, `0x802887B0 → bl 0x80002F10`: accumulator
  `acc += SMSGetAnmFrameRate()`, one call to `JPAEmitterManager::calc()` per
  whole unit. 2 / 1 / "0 then 1" — 60 calls/s at every tier.
  Correct by construction; replaces the compensation.
- **audio**, `0x802A62DC → bl 0x80002F50`: `MSound::mainLoop` is only called
  every `2 × literal(0x804167B8)` frames — 1 at 30 FPS and in PAL,
  2 at 60, 4 at 120. The JAI layer gets back its original 30 Hz.

Encoding reread in the disassembler (Capstone) and targets of both `bl` recomputed
by hand. **Nothing is measured in game yet**: the profile is reinstalled, the
game must restart.

Consequence to be aware of: the chosen area is that of the Gecko codehandler —
**enabling Gecko codes for GMSE01 would overwrite the routines**.

### To do on restart

```sh
python tools/watch_audio.py 600
```

Reads back the 29 words, measures the JAI rate (expected ~30/s) and flags any
frozen sequence. Detector proven before the fix: it does flag root 1
as frozen. Still to be judged by eye and ear: jet speed, graffiti
entry, plaza music looping.

### Addendum — graffiti portal impassable

Game restarted with the routines: `watch_audio.py` reads 29/29 words, JAI rate
**30.0/s**, no frozen sequence; particle accumulator observed
alternating 0.0 / 0.5. New report from the author: **impossible to enter
the portal**.

Reading on the three `TModelGate` of the plaza (vtable `0x803D3F9C`): Mario at
845 units from the first one, gauge `+0xD0` **alternating 0.00 / 0.01**, opening
counter `+0xCA` at 0. The gauge gains 0.01 per **substep** and loses `+0xD8`
= 0.02 per **rendered frame** as long as the portal is closed:

| Frame rate | gain/s | loss/s | net |
|---|---|---|---|
| 30 | 1.2 | 0.6 | +0.6 — open in ~1.7 s |
| 60 | 1.2 | 1.2 | 0 — never |
| 120 | 1.2 | 2.4 | −1.2 — never |

**The `0x80414904` anomaly (§ 4.3) is settled**: the 0.01 → 0.02 / 0.04 of
`gamemasterplc` and BSE compensates for this per-frame decrement, at the cost of an opening
2× / 4× too fast. It was neither an aesthetic choice nor a sign error,
but a mechanism invisible from the single usage site alone.

Fix: `0x801EC29C`, the load of `+0xD8` in `TModelGate::loadAfter`,
targets `0x80414104` = 0.005f (pre-existing constant, otherwise read only by `TLeanBlock`).
Net +0.6/s, the original dynamics. `+0xEC`, another copy of the 0.02, goes
into `gpAfterEffect+0x50` and is not touched, for lack of knowing whether it is a
speed. Portals already loaded fixed live (`+0xD8` = 0.005).

**Not measured**: the rise of the gauge after the fix — Mario was far from the
portals at the time of the write. Remaining 4× too fast, cosmetic:
closing `+0xDC`, blur smoothing `+0xE8`, opening duration `+0xC8`.

### Addendum — water slide sound missing: A/B test

Diagnostic switch added to the audio routine: `0x80002F0C` non-zero =
`MSound::mainLoop` on every frame (never written by the profile; toggleable
live). Result by the author's ear: **sound missing in mode A (JAI 30 Hz),
present in mode B (JAI 120 Hz)**. The 30 Hz limiting is to blame.

Compared reading of the SEs (45 s per mode, continuous slides): sound `0x1969`
(category 1, bit `0x800`, ~170 ms) starts 6 times in B, **1 time in A**. No
`li` loads it: the id comes from the animation data, it is a
`JAIAnimeSound` sound. Why its triggers get lost at 30 Hz is not
demonstrated.

Consequence: the global limiting is too coarse. In progress: check whether
the music really freezes in mode B (10 min monitoring) before
designing a limiting restricted to sequences.

### Addendum — audio limiting removed

Mode B (JAI at 120 Hz, switch `0x80002F0C` = 1): **the plaza music
loops normally**, by the author's ear; slide sound present.
The 30 Hz limiting is therefore not needed for looping, and it breaks
animation sounds: **removed from the profile** (`build_caves.py` now only generates the
particle routine; `0x802A62DC` is no longer patched).

The freeze of the first attempt remains **unexplained**: a single occurrence observed,
under JAI at 120 Hz, not reproduced since. `watch_audio.py` detects it.
The hypothesis "JAI at 120 Hz loses the tempo transmission" is neither confirmed
nor ruled out: a correct loop does not prove the absence of a race.

### Addendum — sewer music frozen: cause found

Report: no music in the sewers. Live reading: sound
`8001001B`, MSBgm track 2, JASystem root 2 **frozen**, tempo multiplier
0.0 — same symptom as the first freeze, **without** audio limiting (JAI at
120 Hz). The freeze is therefore real and independent of the removed routine.

Mechanism, read in Graffito-Decomp and confirmed in the DOL:

1. `JAISystemInterface::outerInit` (audio thread, sequence-start callback)
   fills the root's port arguments, flags `0xff` (tempo = bit
   `0x80`), then `addPortCmdOnce`.
2. `JAIBasic::checkPlayingSeq` (game thread, every JAI pass) writes the
   current flags by **overwriting** (`setSeqPortargsU32`: `stw`), clears
   the command's "queued" marker (`0x80307CF0`), then relinks it.
3. If the audio callback (`portCmdMain`) has not yet consumed the command, the
   tempo bit is lost; `setPortParameter` only applies the bits present.
   The multiplier stays at its initialisation value 0.0.

At 30 Hz the window is rarely hit; at 120 Hz, often. Same pattern in
`sendSeAllParameter` (`0x8030669C`).

Fix (`build_caves.py`, routine `0x80002F40`): merge the flags if the
command is queued, overwrite otherwise, MSR.EE masked; clears of the
marker replaced by `nop`. Encoding reread; **not measured in game** (profile
reinstalled, restart required). `watch_audio.py --suivi` added: long,
multi-level monitoring, which logs every music track and every freeze in
`work/suivi_audio.log`.

## Session 6, continued — 2026-09-23 — full pass: animations, transitions, sound effects

Author's request: fix music, sound effects and animations in one go.

**Port of the BetterSunshineEngine inventory** (`src/patches/fps.cpp`, cloned
and reread), in five groups analysed in parallel, one module per group in
`tools/fixes/`, each with its own code cave area and the same convention: factor
M = 2 × literal `0x804167B8`, read at runtime (1 at 30 FPS, 4 at 120).

| Module | Words | Content | Differences from BSE |
|---|---|---|---|
| `hx.py` | 179 | HX transitions: Circle, GameOver, Test1/2/2R/4/5, HX_MotionUpdate | + 7 Circle counters; duration of the 1st GameOver bounce (BSE omission); Test5 stateless; logo left as original |
| `fader.py` | 34 | TSMSFader: duration, delay, rate captured at start-up | rate +0x14 **measured at 120.0** in the running game → pinned to 30, M applied elsewhere |
| `menus.py` | 61 | Shine select (rotation, alpha, TCoord2D), dialogue timer | 7 other `setValue` spotted, not fixed |
| `actors.py` | 60 | boids (+ leader, absent from BSE), birds (+2 sites), eel 19 sites, TJointCoin, Petey | TJointCoin 2.5/(4+M) (BSE 6.7 % too high at 120); FireWanwan **disabled**: the BSE filter would freeze the tail 3 frames out of 4 |
| `contexts.py` | 43 | 30 FPS forced at boot, logos, intro, loading loops; QFSync | `mRetraceCount` = 5 (and not 2) because of the `nop`; the literal is no longer written by [OnFrame] |

**Sound effects, generic pass:**

- *Systemic defect found*: all actors pass to `MAnmSound::animeLoop`
  the animation speed (`J3DFrameCtrl+0xC`), 2.0 at 30 FPS and 0.5 at 120 FPS;
  `JAIAnimeSound` derives from it the pitch (`base + k(v−1)/32`) and the volume
  (`base + 2v'(v−1)`) of each animation sound. At 120 FPS they came out lower-pitched
  and quieter. Fixed at a single point (`0x80012E9C`, speed × M).
- *Generic measurement*: log of all sound starts, placed at the single
  entry `JAIBasic::startSoundBasic` (ring `0x80002C00`), and a
  "30 FPS everywhere" switch (`0x80002BFC`). `tools/watch_se_rates.py ab` compares the
  frequency of each sound at both frame rates and flags any ratio outside
  [0.5; 2].

**Tooling bug**: Keystone miscomputes every branch that follows
a `slwi` in the same block (target `0x80304B04` instead of `0x803020B0`).
Replaced by `rlwinm`. `tools/build_profile.py` now assembles the whole
profile and blocks on: address conflict, write identical to the DOL,
branch to a target that is neither written, nor a symbol, nor a site return.

Profile: **426 lines**, installed. **Nothing from this pass is measured in
game yet.**

### Addendum — game at 2 FPS on the save select menu

First start with the full pass: transition in slow motion, menu at ~2 FPS
by eye. Reading: context 5, literal 2.0, `mRetraceCount` 2 — correct
settings — but **14.3 VI fields/s for 14.3 frames/s**: 1.00 field per frame,
the game holds its rate; it is **the emulation** that runs at 12 % of its speed.

Probable cause (not demonstrated): the PatchEngine rewrites every
[OnFrame] line on every field and invalidates the JIT code at the written address; 426
lines, many of them in hot code, cause constant recompilation. Invisible
with the thirty or so lines before.

Fix: **conditional** lines `address:dword:value:comparand`
(syntax used by the INIs shipped with Dolphin, verified in
`Sys/GameSettings`). Comparand = original DOL word, or 0 in a code cave: each
line applies once, then never again. 425 lines (one zero code cave word
omitted). To be measured on restart.

### Addendum — back to the healthy profile

With the conditional lines, the game still does not start correctly
(author's report). **Immediate return to the proven base profile**:
31 unconditional lines — literal, `nop`, portal, particles, JAI
flags — the one with which the sewer music was confirmed.
`build_profile.py` now accepts `--modules` and `--inconditionnel`.

Cause of the slowdown **not established**: the conditional lines were not
enough, so the "JIT invalidation" hypothesis is neither confirmed nor excluded, and
a module may be at fault. The modules of the full pass will only be
reintroduced one at a time, each tested in game.

## 2026-09-26 — Session 7: audio pass, one fix at a time

Author's request: rework music, sound effects and effects; **do not
touch** cutscenes or the screen effects of loading screens (fades to
black). The `hx`, `fader`, `contexts` modules of the full pass are therefore
set aside; `menus` and `actors` remain on hold.

### Analysis — the sound layer counts in passes, and runs 4× more often

JAI has been running at 120 passes/s since the limiter was removed (session 6).
Everything it counts in passes elapses 4× too fast. Reread in
Graffito-Decomp then in the DOL:

| # | Mechanism | Effect at 120 FPS | Fix |
|---|---|---|---|
| 1 | `JAIMoveParaSet`, counter decremented per pass; durations set by `initMoveParameter` and the 5 `setSeInter*` | music fades, tempo changes (`MSModBgm::changeTempo` 5 / 20), music ducking under certain sounds, crossfades, SE fade-outs: **4× too short** | `fades.py`, **installed** |
| 2 | `MSSetSoundTL::frameLoopDyna`: clock `+0x54` and "one start per pass" lock `+0xB8` of the 9 sound sets (FLUDD spray impact, graffiti cleaning, goop, fire / electric pillars, drying, manta cry) — minimum interval, modulation durations, continuity in passes | these sounds restart up to **4× more often** | to do: run `frameLoopDyna` only one pass out of M |
| 3 | `MSModBgm::loop`: counter +1 per pass, thresholds 5 and 180 (music that slows down and fades out) | effect **4× too short** (1.5 s instead of 6) | to do: same guard |
| 4 | Doppler (`setPositionDopplarCommon`): relative displacement **per pass** | pitch shift **4× too weak**; `dopplarMoveTime` transition 4× too short | to do: `dopplarParameter` ÷ M, and inlined duration × M |
| 5 | animation sounds: speed `J3DFrameCtrl+0xC` passed to `JAIAnimeSound` | pitch and volume modulated as at speed 0.5 instead of 2 | `sound.py` part 1 (session 6), to be reintroduced alone |

Checked, no defect: `MSMainProc::entranceDemoLoop` is empty (`blr`) in
GMSE01; the list of dummy position buffers (`checkDummyPositionBuffer`)
is never populated (`getDummyVecPointer` empty); the hold countdown
for looping SEs (`JAISound+0x2`, 10 passes) is refreshed at the
same rate it decreases, once per frame.

### Fix 1 — fade durations (`tools/fixes/fades.py`)

Duration (`r5`) multiplied by M at the entry of the six functions; M derived from
the exponent of the literal `0x804167B8` (`shift = exponent − 126`, no
floating point). 26-word routine at `0x80002E40`, 6 sites. Encoding reread with
Capstone; `build_profile.py`: no conflict, branches resolved. Profile
"base + fades" **63 unconditional lines**, installed. Base profile
copied to `work/GMSE01.base.ini` (identical to the regeneration
`--modules none --inconditionnel`, verified with `diff`).

`tools/watch_fades.py` times in game each background music fade
(counter N, real duration). **Nothing has been measured in game yet.**

### Fix 1 — measured in game: validated

Game restarted by the author. Profile 63/63 words in place; 120.00 frames/s over
two measurements (a first reading at 99.75 coincided with
`watch_audio.py`, not reproduced); JAI 120.0 passes/s; no frozen
sequence. Repeated pauses, `watch_fades.py`:

| Fade (caller, original duration) | N read | real duration | original at 30 Hz | without fix |
|---|---|---|---|---|
| `pauseOn`: music → 0, 60 passes | 239 | **1.996 s** | 2.000 s | 0.50 s |
| `pauseOff`: → 1.0, 10 passes | 39 | **0.328 s** | 0.333 s | 0.08 s |
| volume 1.0 → 0.48, 30 passes (caller not identified) | 120 | **0.993 s** | 1.000 s | 0.25 s |
| 0.48 → 1.0, 15 passes | 60 | **0.493 s** | 0.500 s | 0.13 s |

N read = 4 × original duration (within one pass, missed between two
reads). Four `pauseOn` fades measured shorter (1.14–1.50 s): pause
exited before the end — `pauseOff` rearms the same `JAIMoveParaSet` without going
through 0, the tool merges both into a single reading. No anomaly.

### Fix 2 — FLUDD sound sets (`tools/fixes/soundsets.py`)

`frameLoopDyna` (MSSetSound 0x8001604C, MSSetSoundGrp 0x80016014) is
run only one JAI pass out of M, phase read from `JAIBasic::basic+0x20`
(0x8040E430; counter incremented by `processFrameWork` 0x80301D84, measured
**119.99/s**, after the pass's frameLoopDyna calls). Vtables reread: entry
+0x14 of 0x803AC6F0/0x803AC708 → 0x8001604C, of 0x803AC6A8/0x803AC6C0 →
0x80016014. GATE routine + 2 stubs, 26 words at 0x80001C00 (area read
as zero in game). Profile "base + fades + soundsets": **91 lines**, installed,
awaiting restart.

`tools/watch_soundsets.py`: rate of the `+0x54` clock of each set
while it is active — expected ~120/s before, ~30/s after.

### Fix 2 — completed before any test: the age of the previous sound

Rereading `startSoundSetDyna` (Graffito-Decomp `MSoundStruct.cpp`, then
DOL): the repeat rate does **not** depend on the `+0x54` clock but on
the **age of the previous sound**, `JAISound+0x14`, incremented on every JAI pass.
It is compared with the minimum interval, the unit duration, the group
thresholds, the modulation duration and the continuity gap. For the spray
impact (0x6800), the continuity gap is 0: `+0x54` is never active there.
Guarding `frameLoopDyna` alone would have left the main defect in place.

Added to `soundsets.py`: the 4 reads `lwz rD, 0x14(rA)` of each instance
(MSSetSound 0x8001B504 / B66C / B750 / B8A4, MSSetSoundGrp +0x9D0) are
followed by `srw rD, rD, log2(M)`. Non-leaf functions (LR saved in the
prologue, `mtlr r0` from the stack), `r11`/`r12` absent from the whole listing.
Profile: **136 lines** (`--modules fades,soundsets --inconditionnel`),
installed, awaiting restart.

Reading before the fix (profile base + fades, game running): `+0x54` clock
of sound set 0x804 (drying) **120.14 /s** while active —
expected 30 in the original game.

Reading before the fix, 60 s of free play (uncontrolled input): 0x6800
spray impact 129 starts, 0x804 drying 206 starts (clock **119.89 /s**
over 48.7 s of activity), group 74, 0x6801 6. The number of starts depends on the
input: `watch_soundsets.py` now also records the **gap** between
consecutive starts, independent of the input (expected, calculated and not measured, for
0x6800: 58–108 ms without the fix, 233–433 ms with it).

### 16:9 widescreen — Gecko code converted (`tools/fixes/widescreen.py`)

Author's request: add the widescreen code to the 120 profile. Source: the
"Widescreen [gamemasterplc]" code from Dolphin's `Sys/GameSettings/GMSE01.ini`,
copied verbatim. [Gecko] does not load here, and its handler
would overwrite our routines (same area): conversion to [OnFrame] — 12 direct `04`
writes; 12 `C2` insertions placed at 0x80001E00–0x80001F17 (area
read as zero in game), last word replaced by the return, site replaced by
a jump. Verified in the DOL: at the 12 sites, the original instruction appears
in the block; targeted literals 600.0 (→ 800 / 700) and 4/3 at 0x80412408
(→ 16/9). 95 words. Profile `--modules fades,soundsets,widescreen
--inconditionnel`: **231 lines**, installed, awaiting restart.
Fallback without widescreen: `work/GMSE01.fades-soundsets.ini`.

Fix 2 has been running since the last start: 136/136 words in place,
119.67 frames/s; the author, by ear: "I already find it much better".
Measurement of the gaps between sound starts not done yet (Dolphin closed by
the author during the measurement, to install a texture pack).

### Widescreen — confirmed in game by the author (16:9 picture).

### Author's question: is the heat haze effect in the plaza sped up? — No.

Object: `TShimmer` "陽炎" (Graffito-Decomp `src/Map/Shimmer.cpp`), vtable
0x803C1F70, in-game instance 0x81115554. Its texture animation (BTK) advances
through its own `J3DFrameCtrl` (+0x58) by **1.0 per call** of `perform` with
flag 0x1 — speed not tied to `SMSGetAnmFrameRate`.

Registration read from memory (links `TPerformLink {next, object,
filter}`, decomp. `System/PerformList.hpp`): the object is in the group
"インダイレクトシーン" (0x81115508), itself in the director's lists:

| List | Group filter |
|---|---|
| `+0x24` GXPost | 0x40000008 |
| `+0x28` **Movement** | **0x40003001** — only one carrying bit 0x1 |
| `+0x2C` CalcAnim | 0x40000002 |
| `+0x34` | 0x40000204 |

`direct()` runs `+0x28` in the substep body (0x80299B54), flags
`~r27`: bit 0x1 passes on every substep. Hence 120 animation steps per
second **at both rates** — 4 per frame at 30 FPS, 1 per frame at 120.
Measured at 120 FPS: **119.96 animation frames/s** for 120.00 frames/s.
Original speed; the perceived difference comes from smoothness (at 30 FPS the effect
jumped 4 animation frames per frame).

First time an object's registration in a list has been established by reading memory: the
method (walking the `TPerformList`s, count `+0x10`, head `+0x14`) answers
the "Not verified" of `01-mechanisms.md` § 1.3 for any object.

### Fix 2 — measured in game: validated

Profile 231 lines (fades + soundsets + widescreen), continuous spraying 30 s,
`watch_soundsets.py 30`:

| Sound set | starts | min gap | median gap | +0x54 clock | expected (calculation) |
|---|---|---|---|---|---|
| 0x6800 spray impact | 106 | **233 ms** | 269 ms | inactive | 233–433 ms (7 + random 0–6 passes at 30 Hz); without the fix 58–108 ms |
| 0x804 drying | 344 | 17 ms | 83 ms | **29.90 /s** | clock 30 /s (before: 119.89) |
| group | 15 | 575 ms | 711 ms | inactive | — |

The minimum gap of the impact sound lands exactly on the original value
(7 passes at 30 Hz = 233 ms). For 0x804, the minimum gap of 17 ms is below
the one-start-per-pass lock at 30 Hz (33 ms): a tool limitation —
`time.sleep` on Windows has a granularity of ~15.6 ms, the recorded gaps
are quantized to ±16 ms. Only the median is significant; no reading of
gaps before the fix for this sound (tool added afterwards). The author's
ear: "much better".

### Fix 3 — animation sounds (`tools/fixes/sound.py`, part 1 only)

Author's request: animation sounds, then Doppler. Installed **one at a time**
(project rule). Site reread: `MAnmSound::animeLoop` 0x80012E9C `bl
setAnimSoundVec`, speed in `f2` passed without transformation. The diagnostic
log on `startSoundBasic` is no longer installed by default
(`build(with_log=False)`). Probe added: the speed passed is
copied to 0x80002A30 (f32, state) — expected 2.0 for an animation at normal
speed, 0.5 without the fix. Profile `fades,soundsets,widescreen,sound`:
**239 lines**, installed. Fallback: `work/GMSE01.fades-soundsets-widescreen.ini`.

### Fix 4 — Doppler (`tools/fixes/doppler.py`): ready, NOT installed

`dopplarParameter` 3200 → 800 (data, assumes M = 4); inlined transition in
`setSePositionDopplar` (0x8030C730): `r31 <<= log2(M)`. `dopplarMoveTime`
is NOT modified as data: its read on the sequence side already goes through
`initMoveParameter`, which fades.py multiplies. `r12` not read after 0x8030C6EC
in the function (listing). Full profile dry run: 248 lines, checks
passed.

### Fix 5 — Petey Piranha (`tools/fixes/petey.py`)

Author's report: "Petey throws up right away, no time to fill his
stomach". Cause reread in the DOL: `TBossPakkun::changeBck` overwrites, for
animation 0x15 only, the correct rate with a raw parameter (0x800955CC),
and `TNerveBPVomit::execute` times the whole vomiting phase on this
animation (animation frames 25–165, end of animation): phase 4× too fast at 120 FPS.
Fix = group 5 of actors.py extracted on its own (same 7 words, verified
identical): stored rate divided by M. Installed together with fix 3 — the code
only runs during the fight, so attributing a defect remains
unambiguous. Profile `fades,soundsets,widescreen,sound,petey`: **246 lines**.

### Fix 5 — Petey: validated by the author ("perfect for Petey").

### Fix 3 — animation sounds: wrong premise for Mario, corrected

Author's feedback: footsteps and jumps **too high-pitched**, no more bass. Probe:
speed passed 2.0 (1551 readings over 5 s). Yet `TMario::setAnimation`
sets Mario's rate to the **constant 0.5** (0x80247958 `lfs f0` ←
0x80415A94 = 0.5; 0x80247968 `stfs f0, 0xC(r3)`): his animation advances per
substep, and he was already passing 0.5 in the original game at 30 FPS. The
premise of session 6 ("all actors pass ~SMSGetAnmFrameRate")
was an unverified deduction, wrong for Mario; the ×M pushed it to 2.0.

Correction: the routine reads the return address of animeLoop's caller
(0xC(r1), based on the prologue `stw r0,4(r1)` / `stwu r1,-8(r1)`) and does not
multiply if it is TMario::animSound (0x80285824). Other callers
still multiplied; rate coming from SMSGetAnmFrameRate verified for
TLiveActor only, **not verified** for TYoshi, TKoopa, TCannonDom,
TChorobei, TTamaNokoFlower, TEnemyManager. Profile 246 → 251 lines, installed.

### Fix 3 — animation sounds: validated by the author ("it's perfect for the sounds").

### Author's question: staircase edges on the goop — diagnosis, no fix

Independent of the framerate. Reading in game (Bianco, 5 `TPollutionLayer` layers,
vtable 0x803C2160, model `+0x24`):

- mask = texture 0 of the model (`getTexResource`), **I8, 128×128 to 256×256**
  for a whole area; filtering **already linear** (`ResTIMG+0x14/+0x15` = 1/1)
  — hence the lack of effect of Dolphin's "Force Linear" (tested by
  the author);
- materials (`J3DPEBlockFull`, vt 0x803E0968), all identical: alpha compare
  id 0x00C3 = **GEQUAL 0x80 AND LEQUAL 0xFF**, blend `00 01 00 03` = none
  (opaque);
- `initTexImage` already softens the edge texels (depth − 50 × empty
  neighbours, `TPollutionManager::mEdgeAlpha`).

Threshold at half height on a filtered mask: the contour is the 0.5 isoline of
the bilinear interpolation, hence the diagonal teeth at texel scale.
It is the mask resolution (designed for 480p), not a setting. My
previous hypothesis (threshold at 0 like the layer on the water) is **refuted**
for ground goop. Leads, not pursued: soft edge (blend + alpha remapping
in the TEV, visual only); supersampled display mask
(heavy). Dolphin's MSAA/SSAA does not change the shape of the teeth.

### Fix 4 — Doppler installed; goop added to the plan

Author's decision: leave the goop for now, install the Doppler, add the
goop to the plan (initial plan, section "Chantier hors framerate", on hold).
Profile `fades,soundsets,widescreen,sound,petey,doppler`: **260 lines**,
installed. Fallback: `work/GMSE01.sans-doppler.ini`. Not measured in game.

## 2026-09-27 — Session 8: level entry transitions

Author's request: level entry cutscenes too fast, fades to
black on selection and level entry, Mario falls asleep too early. He
reverses the session 7 decision ("do not touch the transitions").
Mario's sleep: **withdrawn by the author** ("I just extrapolated") — the
decompilation counts it in animation loops, per substep, hence at original
speed; consistent, not measured.

### Reading — `tools/watch_transitions.py` (new)

Samples at ~500 Hz, timestamped in frames by the JAI counter
(`JAIBasic::basic` → +0x20; `0x8040E430` is the **pointer**, not the
counter): director state, camera demo, `TCameraBck`, `TSMSFader`, HX
timer `0x803F43FC`, Mario. Profile 260 lines, entering a level:

| Quantity | Reading at 120 FPS | Original (30 FPS) | Verdict |
|---|---|---|---|
| Demo camera `TCameraBck`: rate / advance | **0.5 animation frame per frame**, end 479 | 2.0 per frame | 60 animation frames/s: **correct** |
| Demo: remaining `+0x14` | 960, −1 per frame → 8.0 s | (479+1)×2 substeps → 8.0 s | **correct** |
| HX exit wipe (director 9) | 24 → 0 in 25 frames = **0.21 s** | 25 frames = 0.83 s | **4× too fast** |
| HX entry wipe (director 1) | 29 → 0 in 30 frames = **0.25 s** | 30 frames = 1.00 s | **4× too fast** |
| `TSMSFader` duration / counter | 120 / 121, **unchanged** during the wipes | — | these fades go through the HX branch |

The recorded demo was interrupted at animation frame 98 (state 1 → 3) — probably skipped
with a button, not confirmed. The perceived "cutscene too fast" is therefore,
according to this reading, the HX wipe that opens it, not the camera.

### Installed — `hx` alone

`--modules fades,soundsets,widescreen,sound,petey,doppler,hx --inconditionnel`:
**439 lines**; checks passed; code cave 0x80001800–0x80001A44 read as zero
in game before installation. Fallback: `work/GMSE01.avant-hx.ini` (260 lines,
identical to the profile installed until then, verified with `diff`).

Known risk: `hx` was part of the 426-line pass that had brought
emulation down to 14 fields/s (cause not established). To watch on the first
start: rate, then wipe duration (expected 100 and 120 frames).
`fader` (TSMSFader outside HX) and `contexts` remain **not installed**.

### `hx` on first start: endless wipe, emulation at 13 fields/s — cause found

Report: launch fade "ultra choppy", closes and reopens
without the game starting, selection screen at ~2 FPS. Live reading:
**13.0 VI fields/s for 13.0 frames/s** (same signature as in session 6),
HX timer `0x803F43FC` = 0x7FFFFxxx (`fctiwz` saturation), active wipe
Hx_Circle (`0x80181AB4`), work variable `0x8000180C` stuck at 0 — but
**`0x8000000C` = 0x19** (= 25, the wipe duration) and `0x80000010` = NaN.

Addressing bug in `tools/fixes/hx.py`: the routines do
`lis r12, 0x8000` then use MAGIC/SCR/SCR_LO/SCR2/T4STATE (0x00–0x18),
which were offsets **within the code cave** and not from 0x80000000. They
were writing into the disc header and taking "GMSE01" as the conversion
constant 0x4330000000000000: duration converted to ±∞, timer saturated, wipe
that never ends. The emulation cost very probably comes from this wipe
drawn continuously with aberrant values — **not demonstrated**, to be confirmed
by the rate at the next start. `hx` was part of the 426-line pass
of session 6: it is the first serious suspect for its collapse
to 14 fields/s, **never explained until now**.

Correction: displacements made absolute from 0x80000000 (0x1800 + offset).
Reread with Capstone: all `d(r12)` accesses land in 0x80001800–0x8000181B.
Check added, passed on the 12 sources (build_caves + 11 modules): no
`d(rX)` access below 0x80001800 after `lis rX, 0x8000` — the detector does
flag the old pattern. Profile 439 lines reinstalled; fallback unchanged
(`work/GMSE01.avant-hx.ini`).

### `hx` corrected: the game starts, level entry wipes validated by the author

"The cutscenes and the level entry fades are perfect." Still
choppy: the fade at game launch and on return to the plaza (circle).

### Choppy circle — cause found: Dolphin HLE hook at 0x800018A8

`tools/watch_wipe.py` (new: VI fields/s and frames/s per quarter
second, timer and wipe routine). All **Hx_Circle** wipes
(`0x80181AB4`, closing circle, ~100 frames = 25 × 4) run at
**8 fields/s for 8 frames/s**; all `0x8017E46C` wipes (level
entry) at 120. Before `hx` (first reading of the session), both circles
(25 and 30) ran at 120: the cost comes from `hx`. Circle variables
reread afterwards (radius 0x8040DE2C, rings DE30–DE44, movement): sane,
no NaN.

Cause: Dolphin places, in the Gecko handler area and **even without any Gecko
code**, the HLE hook `GeckoCodehandler` at `Gecko::ENTRY_POINT` =
**0x800018A8** (and `GeckoHandlerReturnTrampoline` at 0x80002FFC). Executing an
instruction at this address triggers `HLE_Misc::GeckoCodeHandlerICacheFlush`:
increment of word 0x80001800 and **full flush of the JIT cache**. The
`INT_STEP` routine of `hx` had an instruction at 0x800018A8 (`lis r12, 0x8000`);
Hx_Circle calls it 3 times per frame (opacity of the three rings), Test5
never — hence the difference between wipes. Source: Dolphin code (HLE.cpp,
HLE_Misc.cpp, GeckoCode.h), quoted from memory, **not reread in this session**;
the address and the effect match the reading.

This is very probably also the cause of the collapse to 14 fields/s of the
full pass (session 6), `hx` being part of it with the same layout.

Fix: `hx` code moved to 0x800018B0–0x80001AD8 (0x8000181C–0x800018AF
left empty). `build_profile.py` now refuses any word at 0x800018A8 or
0x80002FFC (check proven on the old placement). Profile 439 lines
reinstalled.

Noticed in passing, **not fixed**: ordinary `TSMSFader` fades
(counter +0x12, durations 48 and 120 frames) elapse in 0.4 s and 1 s, i.e. 4×
too fast — belongs to the `fader` module, not installed.

### Circle: validated by the author ("it is indeed perfect").

Profile 439 lines (`fades,soundsets,widescreen,sound,petey,doppler,hx`): launch,
return to the plaza, level entry, cutscenes — validated by eye.

### Slow birds, wall slides and pachinko — author's report

"The birds are very slow, their animation is normal but they don't fly
fast"; wall slides possibly slower; pachinko launch
"not controllable" (impressions, not quantified).

**Birds** — predicted by group 2 of `actors.py` (session 6): 5 sites of
`TAnimalBird` multiply a speed by `SMSGetAnmFrameRate()` in code
run per substep (nerves) — 0.5 instead of 2.0, i.e. 4× too slow. Sites
reread in the DOL. `tools/fixes/birds.py`: group 2 extracted on its own (9 words,
identical to actors.py, verified). Reference before the fix
(`tools/watch_birds.py`, new, sweep of instances by vtable
0x803ABE78): **median 300.9 u/s** over 8 birds in flight, 17 instances,
119.7 frames/s. Expected after the fix: ×4, ~1200 u/s. Profile
`…,hx,birds`: **448 lines**, installed. Fallback: `work/GMSE01.avant-birds.ini`.

**Wall slides, pachinko** — no mechanism identified: among the ~215
calls to `SMSGetAnmFrameRate`, none in Mario's physics (only
`initModel`, effects, `TMarioGamePad::reset`). The pachinko in the decompilation
contains only nails (`MapObjPachinkoNail`, collision). Nothing is
asserted: `tools/watch_mario.py` (new) logs Mario frame by frame and
summarizes speed in u/s per action, for an original 30 FPS /
120 FPS comparison on the same input.

### Birds: validated by the author ("they fly normally") and measured

Reread in memory: `0x8000D1D8` = `bl 0x80002410`, routine in place, constant
2.0. `tools/watch_birds.py`, six 2 s windows: birds in cruising flight
**1159–1169 u/s** (other values: turns, landings, take-offs), versus
a plateau of **296–311 u/s** before the fix. Ratio ≈ 3.9, consistent with ×4
(straight-line distance underestimates a curved flight). Profile 448 lines.

### Boss audit (4 agents, read-only, sites reread in the US DOL by each agent)

No **blocking** defect found. Ranking of defects ("verified" = site and
instruction reread in the DOL; the per-substep / per-frame rate is sometimes
deduced from the decompilation, flagged):

| Boss | Defect | Effect at 120 FPS | Severity | Confidence | Status |
|---|---|---|---|---|---|
| Eel (TBossEel) | 19 sites, anim per substep at 0.25×anmRate (pattern c) | all phases 4× too long | strongly annoying | high, 3 sites reread by hand | `tools/fixes/eel.py` ready (23 words), not installed |
| Shadow Mario (TEnemyMario) | painting anim state 0x13 per substep, 800427CC (c) | stays painting 4× longer | annoying | high | to write |
| Bathtub, pedestals (TBathtubGrip) | 801FBBC4, anim at mixed rate (c) | collapse ~2.5× (or 4×) too slow | annoying | medium (factor) | to measure |
| Bowser Jr, submarine | moveSwing per frame, 801195BC (d) | pitching 4× too fast, balance altered | annoying | high (mechanism) | to write |
| King Boo | genAttacker called 5×/spit at 30 FPS, 2× at 120 | fewer bubbles / Boos | annoying? | high (mechanism), effect not verified | to measure |
| Fire Chomp | "carrier" block without flag, 8008C5D0 | Mario pulled ×1.6–2 on the tail | annoying? | medium (K unknown) | to measure |
| Giant caterpillar | raw rate floor 800F2680 (e) | legs 2–4× too fast when slowed | cosmetic | high | — |
| Petey | calcHeadDir ±1°/frame (d) | head 4× livelier | cosmetic | high | — |
| Squid, manta, eel (eyes), Bullet Bills, Mecha-Bowser (flame) | per-frame counters (d/e) | effects 4× faster | cosmetic | high | — |

No defect: Bowser (TKoopa), bathtub outside pedestals, Pianta Chomp, guardian
plant, TBPTornado, eel teeth and tears, Shadow Mario replay
(one entry per substep).

Outside bosses, noticed in passing (verified in the DOL): Pinna Park Ferris wheel
4× too slow (b), scenery roller coaster rail 4× too slow (c);
`MSound::gateCheck` accepts certain sounds only once per frame (120×/s instead
of 30) — not heard; `TMario::initModel`+0x920 sets frame ctrl 2 of
Mario's model to anmRate — to audit.

### Boss fixes installed as a block (explicit request from the author)

"Go ahead and install all of them, I'll tell you if something's off." Deliberate deviation from the
"one fix at a time" rule: each group only runs in its
own fight or its own scenery, so attributing a defect remains
unambiguous.

- `tools/fixes/eel.py` (23 words): eel, group 3 of actors.
- `tools/fixes/bosses.py` (81 words, code cave 0x800024C0–0x800025E7, + JCCHAR
  from actors at 0x80002420, + shared CONST2): Shadow Mario (setting the
  signature), Bowser Jr's submarine (6 per-frame increments ÷ M), bathtub
  pedestals (10/(4+M), medium confidence), Caterpillar (floor ÷ M), Petey's
  head (±0.25, M = 4 hard-coded), eel eyes, squid trail (5 → 20, M = 4
  hard-coded), Mecha-Bowser flame, Bullet Bill blinking, Pinna Park Ferris wheel and
  roller coaster rail (CONST2).
- 20 sites reread in the DOL by the module itself; words reread with Capstone at their
  real address; `r12` never read after a site (sweep), `f12`/`f13`
  absent from the host functions.
- Correction of an audit report: the 3rd Ferris wheel site is not
  0x801D6A38 (`fadds`) but `initMapObj` 0x801D690C.

Profile **552 lines** (including identical duplicates of K_2/CONST2), installed.
Fallback: `work/GMSE01.avant-boss.ini` (448 lines, last validated profile).
Not installed, for lack of measurement: King Boo, Fire Chomp, manta, squid G1,
Caterpillar tumble, Bullet Bill smoke, roller coaster car.

### Author's question: compatible with Super Mario Eclipse? — No, not as it stands.

Reread in the JoshuaMKW/Super-Mario-Eclipse repository: Kuribo module compiled against
BetterSunshineEngine (submodule `lib/BetterSunshineEngine`, US map).
BSE ships its own rate fixes (fps.cpp) which write every
frame the literal 0x804167B8 and mRetraceCount according to its 30/60/120 setting, and
hook several of the same sites as this profile (fader, HX, birds,
eel…). The two would fight each other. Memory location of the Kuribo loader and
Eclipse game ID: not verified.

### Bosses: validated by the author ("everything is perfect for now")

Profile 552 lines (`fades,soundsets,widescreen,sound,petey,doppler,hx,birds,eel,bosses`).

### Release — "Sunshine Overdrive"

Project renamed **Sunshine Overdrive** for its release (public GitHub
repository). Patch name `$120FPS [Sunshine Overdrive]` (in `[OnFrame]` **and**
`[OnFrame_Enabled]` — keep them identical, otherwise Dolphin does not enable the
patch); `install_profile.py` recognizes both the old and the new name.

Preparation: personal paths removed from the tools (`DOLPHIN_EXE`,
`DOLPHIN_USER_DIR`, `SMS_ISO`, default `%APPDATA%`); references to the initial plan
(unpublished) reworded; `work/` excluded entirely (game DOL, map, measurement
logs); main README rewritten (how it works, installation, limitations);
`requirements.txt`.

## 2026-09-27 — Session 8, continued: the staircase goop

**Mapping** (agent, verified in the DOL, tool `tools/goop_inspect.py`):
the material's display list is **rebuilt on every draw** from the J3D blocks
(unlocked packets, btk present) → modifying the blocks takes effect on the next
frame. Material (9 Bianco materials, identical): stage 0 alpha = mask
(+ light rim if mask < 160), stage 1 alpha = (a+0.5)×0.5, alpha test
≥ 128, opaque. Texel = **32 units** (area of 8192 over 256).

**Live soft edge** (`tools/goop_soft.py`, K = 4 then 2): better, but
the steps remain — they are the size of a texel. The author's texture pack
replaces the masks (`pollution_maps`, 8192², BC7) but **not** those
of this area: XXH64 hashes recomputed, absent from the pack (formula
validated on the goop's CMPR texture, found). Simulation on the real mask
(binary 0/255 at that spot): bilinear reproduces the steps seen in
game; a 3×3 tent filter makes them continuous (`work/goop-lissage-simulation.png`).

**`goop` module** (`tools/fixes/goop/goop.c`, compiled with BSE's PowerPC clang,
`tools/fixes/goop.py`): smoothed display copy per layer, allocated
in the level heap (512 KB guard, otherwise nothing); J3DTexture rewired to
a copy of the ResTIMG whose "mask" entry points to the copy — the
gameplay (unk54, unk58, PollutionCount) is never touched. Update:
stamp areas (`pushTask`), 4 background lines per pass, low-order
bit of texel (0,0) toggled so that Dolphin sees the change. Soft edge
K = 4 applied by the module. Switches in RAM (`tools/goop_ctl.py`).
Sites: 0x801A0EB8, 0x801A12C8, 0x8019ABAC. Code in 4 free areas
(0x80001AE0, 0x80001F20, 0x800025F0, 0x80002A40), state at 0x80002F80.
Profile **1349 lines**, installed. Fallback: `work/GMSE01.avant-goop.ini`.
**Nothing has been tested in game yet.**

### Smoothed goop: validated by the author ("it's legit perfect") and measured

Reading (`tools/goop_ctl.py`): 5 layers prepared, 0 failures, the 5 J3DTextures
rewired to the copy; level heap: **3981 KB free** for 64 KB
requested (512 KB guard comfortably met). Rate: **119.7 VI fields/s,
120.0 frames/s** with the 1349-line profile. ~820 line updates
per second (background + stamp areas).

Note: in levels where the author's texture pack replaced the
original masks (`pollution_maps`), the display now reads the smoothed
copy, whose hash differs: the pack's replacement no longer applies
there. Not verified level by level.

### Goop: cleaning displayed several seconds late, depending on the location

Report: sprayed goop takes several seconds to disappear on screen
(the gameplay itself is up to date: no goop-walking animation), and not
everywhere. `tools/goop_probe.py` (new): copy in RAM **identical** to
tent(mask) (difference 0) — the delay is in Dolphin. On layer 1, a
stamp is pushed **every frame** even without spraying (area x162–205 over
the full height, `dframes` stuck at 3): two updates per frame, hence
two toggles of the bit of texel (0,0), which stayed frozen (`D00 = 1`). Dolphin
only reloaded the texture if the cleaning touched a sampled word.

Fix: marker written **once per pass**, counter modulo 3 in the
2 low bits of texel (0,0); window of marked areas extended to 8 passes.
`set_soft` rewritten with 32-bit accesses (unaligned, supported by the 750)
to fit in the code cave. Profile reinstalled. **To be retested.**

### Goop: validated by the author ("it's perfect, everything is perfect")

Cleaning displayed without delay after the marker fix. Profile 1309
lines. `goop.py` keeps the addresses of the linked functions in
`goop_symbols.json`: the profile can be rebuilt without a compiler, **identical
byte for byte** (verified with `diff` against the validated profile).

## 2026-09-27 — Windows installer

`installer/SunshineOverdrive.iss` (Inno Setup 6.7.3): detection of the Dolphin
user folder (registry `HKCU\Software\Dolphin Emulator\UserConfigPath`,
then `%APPDATA%`, then Documents), choice page (portable Dolphin), check of
`Config\Dolphin.ini`, backup of a foreign `GMSE01.ini` and restoration on
uninstall, no administrator rights, French / English,
`/DOLPHINDIR=` for silent installation.

Tested locally (compiler extracted in portable mode, Pyrsys signature
verified), in a fake Dolphin folder:
- installation: profile identical to `deliver/GMSE01.ini`, old file
  backed up, key `HKCU\Software\Sunshine Overdrive`, "Apps" entry;
- uninstallation: original file restored identically, key, entry and
  program folder removed;
- double installation on a clean Dolphin: no spurious backup;
  uninstallation: empty folder.

Release: `.github/workflows/installateur.yml` builds the Setup on every
`v*` tag (Inno Setup downloaded, signature verified) and publishes it as a Release.

## 2026-09-27 — Sand bird (TJointCoin)

Author's report: "the sand bird is too slow", with a
reservation ("it may just be an impression"). DOL reading:
`TSandBird` inherits from `TJointCoin` (vtable 0x803CF2B4: `loadAfter`
0x801F761C inherited, `control` calls 0x801F79C4). `TJointCoin::control`, per
substep, advances MActor +0x138 and copies the translation of its root joint
into the position. `loadAfter` sets the rates to 0.25 × anmRate
(0x801F76A8 → +0x74, 0x801F76C4 → +0x138). Group 4 of `actors.py`, which
fixes it, had never been installed.

`tools/watch_sandbird.py` (new): rate and animation frame of frame ctrl 0 of both
MActors, anim frames/s, flight speed. Gelato, 5 windows of 2 s, 120 frames/s:

| | before (profile 1309) | after (`jointcoin`) | target, calculated at 30 FPS |
|---|---|---|---|
| rate +0x138 / +0x74 | 0.125 / 0.125 | 0.5 / 0.3125 | 0.5 / 0.5 |
| trajectory, animation frames/s | 15.0 | 59.8–60.1 | 60 |
| wings, animation frames/s | 30.0 | 74.7–75.1 | 75 |
| flight | 88 u/s | 351–353 u/s | ~350 u/s |
| 9000-animation-frame loop | ~600 s | ~150 s | 150 s |

Module `tools/fixes/jointcoin.py`: the two sites alone (→ JCCHAR, → CONST2),
routines identical to `actors.py`. Profile 1324 words, fallback
`work/GMSE01.avant-jointcoin.ini`. 30 FPS column **calculated**, not measured.
Other `TJointCoin`s in the game (none in this level): **not verified**.
Released as v1.1.0 at the author's request.

## 2026-09-27 — Poinks (TPopo): self-collision in flight

Author's report: the Poinks ("little pink pigs" to throw at
Petey, Bianco) "explode instantly and don't go past 2 m". Class
`TPopo` (Japanese name Popo), vtable 0x803BA558; secondary collision box
`TPopoCollision` at +0x23C (owner at +0x68).

`tools/watch_popo.py` (new): nerves, fill +0x198, R trigger,
launch speed, flight duration and distance, hits of the Poink and of its
box, box ↔ Poink distance. Measured at 120 frames/s, 1 step per frame:

- 20 throws: 19 exploded 7 to 10 steps after launch (< 0.1 s, 380–880 u),
  1 at step 2. Flight timer (+0x19C, limit prm+0x3DC = 1000) never
  reached; "airborne" flag still raised: neither landing nor timer.
- 8 throws tracked: contact of the Poink with **its own box** at the first
  `checkActorsHit` (every 4 substeps, `unk58`) after collision is re-enabled
  at step 6 (`TNervePopoFly`); box 150–210 u behind the Poink.

Cause read in the DOL: `TPopo::calcRootMatrix` places the box on a joint,
from the previous frame's matrices, and is only called in the animation
pass (`TLiveActor::perform`, flag 0x2): one-frame lag. At 120
FPS, one frame = 1 substep, the box sticks to the Poink; at 30 FPS, 4 more
substeps, ≥ 500 u (**calculated**), no contact.

Two paths to the explosion, both through `TPopo::isCollidMove`
(0x800E6C94): Poink → box (`isCollidMove(Poink, box)`) and box → Poink
(`TPopo::bind` → `TSmallEnemy::behaveToHitOthers(Poink, Poink)` → vtable
+0x17C = `isCollidMove(Poink, Poink)`). First version (box only):
installed, measured, **no effect** (9 throws out of 9 exploded at step 7–10).

Module `tools/fixes/poink.py`: detour at the prologue of `isCollidMove`, returns 0
if the other object is the Poink or its box. Routine at 0x80001D80 (nominal area of
soundsets, unused beyond 0x80001CF8, verified zero). Profile 1334
words, fallback `work/GMSE01.avant-poink.ini`.

After: the Poink flies 54 steps (0.45 s), 4630 u, and explodes on `TBPNavel`
(Petey's navel), which wakes up. Validated by the author ("they fly
normally"). Only one throw measured after the fix.

## 2026-09-27 — Pink goop (Bianco) and Petey's puddles

Author's report: the pink goop still has staircase edges; the goop
spat by Petey is displayed "in 3 frames", "sometimes normal, sometimes not".

**Three causes, recorded in game** (`tools/goop_ctl.py`, `tools/goop_inspect.py`):

1. **9 layers** in the pink goop episode (7 on walls, 2 on the ground) for
   `MAXL = 8` slots: the 9th (128×128) was not processed. MAXL → 16
   (`goop_roots` 0x80002FA0–0x80002FDF).
2. **Frozen display lists**: the 2 large ground layers have a
   locked `J3DMatPacket` (+0x10 bit 0); their BP 0x94 (TX_IMAGE3 map0)
   stays on the mask, rewiring the J3DTexture changes nothing there. Proof:
   smoothing switched off live, no change on screen; word rewritten by
   hand in both buffers (+5) → "smooth!". Module: `patch_dl`, every
   16 passes, only writes a word that already holds the mask or the copy.
   All copies reread: difference 0 with tent(mask).
3. **"Model" tasks** (`TPollutionCounterLayer::pushModelStampTask`,
   called by `stampModel`: `TBPPolDrop`, `TBPVomit`, `TBossGesso`,
   `TEnemyMario`, `TPolluterBase`…) outside the tracked `pushTask` stamps:
   caught up only by the background sweep (4 lines/pass).
   `tools/watch_poldrop.py`: spreading 0.5 animation frame/frame, 79 animation frames in 156
   frames = **60 animation frames/s, original speed** (2.0 × 30) — the slow spreading
   is normal. `tools/watch_goop_growth.py`: on the arena layer
   (512×512), the copy only caught up with the mask every ~16 frames, in
   jumps (+77, +100 texels) — depending on the position of the sweep.
   Puddle measured: ~600 u around the stamp (scale 2), 2 puddles.
   Module: hook 0x8019B120 → `goop_model_tramp` → `goop_mark_model`:
   square area of radius 400 u × scale around the model's translation,
   recomputed for 8 passes, renewed on every task; area separate from that
   of the stamps. Switch `goop_ctl.py model on|off`.

Intermediate attempt abandoned: fast sweep of the whole layer (32
lines/pass) after a model task — insufficient on 512 lines (16
passes per round); `pushJointObjStampTask` hook removed along with it (space).
Oversight fixed along the way: `burst` field not initialized in
`goop_init` (heap values read: 81, 108).

Space: `patch_dl` in area E 0x80001CFC–0x80001D80 (132 B, full);
`goop_mark_model` in area A, `slot_of` in area C, `mark_rect` and the
trampoline in area B. Profile **1484 words**, fallback
`work/GMSE01.avant-goop2.ini`. Validated by the author: "everything is smooth, it
spreads fluidly". Released as v1.3.0.

## 2026-09-28 — Gatekeeper: double cry on every hit (community feedback)

Report (Discord, Eclipse music co-lead): at 120 FPS the Gatekeeper
(Proto Piranha, `TBiancoGateKeeper`) cries twice on every water hit.

**Measured eliminations** (test profiles, one change at a time):
original game 30 FPS: no double cry; 120 FPS without `sound`: double cry;
without `soundsets`: double cry; blob melting sound `0x2802`
(`TNameKuri::setMeltAnm`, call cut with `nop`): double cry.
**False leads corrected along the way**: `0x2832` (sounds of `TAmenbo` /
`THamuKuri`, not the Gatekeeper) and `0x2802` (blob melting) — identified with
`tools/who_plays.py`, which traces back from a JAISound instance to the animation sound
object and to the actor carrying it.

**Cause** (`tools/watch_gatekeeper.py` + trace sampled several times
per frame): the cry `0x2891` is event 0 (animation frame 0, no loop
restriction) of the table of the damage animation (no. 3, 120 animation frames, looping).
Frame 72048: animation frame 119.5 → 0.0, "wrapped" flag. Frame 72049: the damage
nerve sees the end and hands over; the sound system sees the loop wrap
(loops 0 → 1) and replays the cry. Frame 72050: the next nerve starts
animation 17. Two substeps are needed between the end of an animation and the
change; at 30 FPS, the sound is only evaluated one substep out of four and never
sees this loop wrap. Generic pattern.

**Fix** `tools/fixes/loopsnd.py`: detour at the entry of the playback loop
of `JAIAnimeSound::setAnimSoundActor` (0x8030038C); right after a
loop wrap (prev. animation frame == animation frame, loops ≠ 0, index == start), playback
deferred by one evaluation (8 ms) — dropped if the animation changes in the
meantime. Active only above 30 FPS. Code cave 0x80001DA4–0x80001DE7.
`build_profile.py` now accepts internal branch targets
declared by a module (`TARGETS`). Profile **1502 words**, fallback
`work/GMSE01.avant-loopsnd.ini`. Validated by the author by ear: "only
one cry now", other sounds normal.

## 2026-09-28 — Fish schools 4× too fast (Gelato, red coins in the coral reef)

Report: in Gelato Beach episode 6 ("Red Coins in the Coral Reef"), the fish
are too fast to catch and some go through walls.

The fish are boids (`TFishoid`, each embedding a `TBoidLeader`). Group 1 of
`tools/fixes/actors.py` already described the defect but had never been
installed: `TBoidLeader::perform` (0x80005D14) runs the leader's move and
`calcBoids` only under flag 0x2, once per rendered frame, with a
frame-rate-independent step.

`tools/watch_boids.py` (new), leader position at +0x74 (read from the add at
0x80005E2C..0x80005E58):

| | before (1502-word profile) | after (`boids`) | 30 FPS, calculated |
|---|---|---|---|
| step | 3.57–3.60 u per frame at 116–124 frames/s | 0.90 u per frame | 3.6 u per frame |
| speed | 414–445 u/s | 107.5–107.9 u/s | 108 u/s |

Module `tools/fixes/boids.py`: the two group-1 sites alone (0x800066E4 →
BOID, sqrt(dot)/M; 0x80005DFC → LEADER, 0.9/M), routines identical to
`actors.py` at their original addresses 0x80002440 / 0x80002460 (verified
empty). Profile **1516 words**, fallback `work/GMSE01.avant-boids.ini`.
Validated by the author: "much more manageable", Shine completed.

Going through walls remains: read in the DOL, the boid code (`calcBoids`,
`calcForces`, `calcGoalForce`, `TBoidLeader::perform`) makes no map
collision call at all — schools follow a graph and flocking forces, so they
cross walls in the original game too, just 4× less visibly. Not checked in
game at 30 FPS. Boid orientation smoothing still runs per frame (faster
turning, visual only): NOT VERIFIED.
