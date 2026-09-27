# The timing mechanisms, verified against the machine code

> Status: **verified statically, then confirmed at runtime** on `GMSE01`
> (NTSC-U, revision 0, DOL SHA-1 `a6782903ef79d4196c8489ecb1b57decb5b3728f`).
> The measurements are in [`04-tests.md`](04-tests.md); none of them contradicts
> the analysis below.
> For the points it covers, this document replaces the hypotheses of the
> initial plan. Every claim comes with the address needed to
> reproduce it. See [`00-journal.md`](00-journal.md) for the chronology and
> [`02-addresses.md`](02-addresses.md) for the address register.

To reproduce any listing in this document:

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map <address-or-symbol>
```

---

## 1. The substep accumulator — `TMarDirector::direct()`

`direct__12TMarDirectorFv` @ `0x80299838`, length `0x510`.

### 1.1 Computing the quantum

```
80299850  bl     SMSGetVSyncTimesPerSec()   ; f1 = 30.0 in NTSC
80299854  fctiwz f0, f1                     ; conversion to integer
8029985C  li     r3, 0x258                  ; 600
80299864  stfd   f0, 0x160(r1)              ; FPR -> GPR transfer through the stack
80299868  lwz    r0, 0x164(r1)              ; low word of the fctiwz result
8029986C  divw   r25, r3, r0                ; r25 = 600 / 30 = 20
```

Confirms the initial plan's pseudo-code word for word:

```c
int vsyncRate = 600 / (int)SMSGetVSyncTimesPerSec();
```

The `600` is a hard-coded immediate (`li r3, 0x258`), not a literal in memory:
**it cannot be patched by a simple-write Gecko code.** Only the
divisor — the return value of `SMSGetVSyncTimesPerSec()` — can be modified,
and only indirectly, through the literal `0x804167B8` (§ 2).

### 1.2 Actual structure of the loop

This is the point the initial plan warned about: "the `break` of the last
substep makes the draw branch unreachable — the decompiled code is
self-contradictory at this spot". **The machine code is not
contradictory.** The decompilation renders poorly a loop whose entry point
lies in the middle.

```c
s32 TMarDirector::direct() {            // called once per rendered frame
    /* one-time initialisation, guarded by the boolean this+0x260 */

    unk54 += vsyncRate;                 // 0x80299938 — budget of the frame

loop:                                   // 0x8029994C
    if (unk4C & 0x4000) {               // leftover from the previous call
        perform(+0x40); perform(+0x38); perform(+0x3C);   // 0x80299C28 — DRAW
        GXInvalidateTexAll();                             // 0x80299D04
        goto after;
    }

    if (++i == 1)      unk4C |= 0x2000; // 0x80299964 — first substep
    unk54 -= 5;                         // 0x80299974 — quantum
    if (unk54 < 5)     unk4C |= 0x4000; // 0x8029998C — last substep

    /* ... SIMULATION perform lists: movement() ... */

    if (unk4C & 0x4000) {               // 0x80299BF4
        perform(+0x34);                 // 0x80299C00 — animations
        return status;                  // 0x80299C24 — returns control
    }

after:                                  // 0x80299D08
    status = changeState();             // 0x80299D0C
    unk4C &= ~(0x2000 | 0x4000);        // 0x80299D18 — rlwinm r0,r0,0,0x13,0x10
    goto loop;                          // 0x80299D20
}
```

The key point: **the `0x4000` flag survives the function return.** The last
substep sets it, then returns control to `TApplication::gameLoop()` for
presentation; on the next call, the test at the head of the loop still sees it set
and runs the draw block. Drawing is therefore *deferred to the start of the next
call*, which explains both the structure and the decompiler's failure.

### 1.3 Consequence: the classification rule

This is the rule that tells what breaks when the framerate is unlocked.

| Location | Frequency | Effect of going from 30 → 60 FPS |
|---|---|---|
| simulation perform lists (body of the substep) | **per substep**, constant 120 Hz | none — automatically correct |
| list `+0x34` (animations, last substep) | **per rendered frame** | doubled |
| lists `+0x40`, `+0x38`, `+0x3C` (draw) | **per rendered frame** | doubled |

An object whose `perform` is registered in a simulation list never
needs to be rescaled. This is why BSE never touches
`TJumpParams` or `TRunParams`.

The lists are distributed as follows, by the offsets loaded in each region:

| Region of `direct()` | Lists (offsets from `TMarDirector`) |
|---|---|
| body of the substep — **simulation** | `+0x18`, `+0x28`, `+0x2C`, `+0x30`, `+0x34`, `+0x44`, `+0x48`, `+0x58`, `+0x5C` |
| draw block — **per rendered frame** | `+0x1C`, `+0x20`, `+0x24`, `+0x38`, `+0x3C`, `+0x40` |
| last substep — animations | `+0x34` |

`+0x34` appears in the first two: the list is walked at every
substep for movement, then once more on the last substep for
animations.

**Not verified:** which list a given object registers in. The lists are
populated at runtime and walked through virtual dispatch
(`lwz r12, 0(r3) ; lwz r12, 0x20(r12) ; blrl`): only an in-situ measurement
will tell. See 0.C in [`04-tests.md`](04-tests.md).

### 1.4 Runtime confirmation

Measured by polling the accumulator (`tools/measure_substeps.py`):

| Tier | `vsyncRate` | frames/s | substeps/s | substeps/frame |
|---|---|---|---|---|
| 30 FPS | **20** | **30.00** | **120.00** | **4.000** |
| 60 FPS | **10** | **60.00** | 119.50 | **1.992** |
| 120 FPS (without VI overclock) | **5** | 60.00 | 60.00 | **1.000** |

And through an entirely independent path — counting the position
integrations during a free fall of 3000 units
(`tools/test_freefall.py`): **198 integrations at 30 FPS, 198 at 60 FPS**, for
a real duration of 1.655 s versus 1.635 s (1.2 % difference, scheduling
noise). Physics does not depend on the display rate.

---

## 2. The logic clock — `SMSGetVSyncTimesPerSec()`

`SMSGetVSyncTimesPerSec__Fv` @ `0x802A7C48`.

```
802A7C58  lfs    f31, -0x3c8(r2)   ; 0x804167D8 = 60.0f   (default value)
802A7C5C  bl     VIGetTvFormat
802A7C60  cmpwi  r3, 2             ; VI_MPAL
...
802A7C88  lfs    f31, -0x3c8(r2)   ; 0x804167D8 = 60.0f   NTSC / MPAL / EURGB60
802A7C90  lfs    f31, -0x3c4(r2)   ; 0x804167DC = 50.0f   PAL
802A7C94  lfs    f0,  -0x3e8(r2)   ; 0x804167B8 = 0.5f
802A7C9C  fmuls  f1, f31, f0       ; 60.0 * 0.5 = 30.0
```

`r2 = 0x80416BA0`, read in `__init_registers` @ `0x80005364`
(`lis r2,-0x7fbf ; ori r2,r2,0x6ba0`). The tooling decodes this pair instead of
hard-coding the base, which makes it valid on every DOL of the game.

**The identity of `0x804167B8` is now verified, not inferred.** It is the
`0.5f` multiplied into the result. The initial plan classified it as "not verified,
attributed through the decompilation splits"; the instruction gives it
directly.

The compiler did emit the reciprocal: the source writes `/ 2.0f`, the machine
code multiplies by `0.5f`.

### 2.1 `SMSGetAnmFrameRate()`

`SMSGetAnmFrameRate__Fv` @ `0x802A7BD8`. Recomputes the rate inline rather
than calling `SMSGetVSyncTimesPerSec()`:

```
802A7C24  lfs    f0, -0x3e8(r2)    ; 0.5f          <- same literal
802A7C28  lfs    f1, -0x3c8(r2)    ; 60.0f
802A7C2C  fmuls  f0, f31, f0       ; vsync = 60.0 * 0.5 = 30.0
802A7C30  fdivs  f1, f1, f0        ; 60.0 / 30.0 = 2.0
```

Confirms `SMSGetAnmFrameRate() == 60.0f / SMSGetVSyncTimesPerSec()`. The two
functions share the literal `0x804167B8`, which is precisely the reason
the Gecko code realigns the logic clock and the animation rate
with a single write.

### 2.2 A third consumer, not documented elsewhere

```sh
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x804167B8
```

gives **three** references, not two:

| Address | Function |
|---|---|
| `0x802A5EFC` | `TApplication::drawDVDErr()+0x3B8` |
| `0x802A7C24` | `SMSGetAnmFrameRate()+0x4C` |
| `0x802A7C94` | `SMSGetVSyncTimesPerSec()+0x4C` |

Patching `0x804167B8` therefore also modifies the disc read error screen.
No consequence expected under emulation, but worth knowing: it is a side
effect of a literal shared through the constant pool, not of an intent.

---

## 3. Presentation — `JDrama::TVideo::waitForRetrace(u16)`

`waitForRetrace__Q26JDrama6TVideoFUs` @ `0x802FC9A4`, end `0x802FCB5C`.

Full reconstruction:

```c
void JDrama::TVideo::waitForRetrace(u16 count) {
    while ((s32)(mTargetRetrace - VIGetRetraceCount()) > 1)   // 0x802FC9C8..CDC
        VIWaitForRetrace();

    if (!IsEqualRenderModeVIParams(this, &this->mNextMode)) { // 0x802FC9E8
        VIConfigure(&mNextMode);                              // 0x802FC9F8
        /* ... VISetBlack, VIFlush, and up to 60 VIWaitForRetrace
           if the interlacing changes (0x802FCA5C..A6C) ... */
    }
    /* ... copies mNextMode -> mMode, fields 0x3C..0x7C -> 0x00..0x38 ... */

    VIWaitForRetrace();                                       // 0x802FCB24  <-- patched
    mLastTick      = OSGetTick();                             // 0x802FCB2C  -> +0x80
    mTargetRetrace = VIGetRetraceCount() + count;             // 0x802FCB3C  -> +0x84
}
```

All the called functions were confirmed in the map:
`VIWaitForRetrace` `0x8034F684`, `VIGetRetraceCount` `0x803504EC`,
`VIConfigure` `0x8034FB4C`, `VIFlush` `0x803502E8`, `VISetBlack` `0x80350470`,
`OSGetTick` `0x803494F0`, `IsEqualRenderModeVIParams` `0x802FB808`.

### 3.1 Why neutralising `0x802FCB24` is equivalent to `mRetraceCount = 1`

The initial plan asserted it without proof. Here is the steady state.

Let `c = VIGetRetraceCount()` and `t = mTargetRetrace` on entry. The wait
loop at the head exits as soon as `t - c <= 1`, so at `c = t - 1` if it has
run.

**Unpatched**, with `count = N`: the loop brings `c` to `t-1`, the
final `VIWaitForRetrace` brings it to `t`, then `t := t + N`.
→ **N fields consumed per call.**

**Patched** (the final `bl` replaced by `nop`), with `count = N`: the loop
brings `c` to `t-1`, there is no final wait any more, then `t := (t-1) + N`.
The gap `t - c` is then `N`, and the loop on the next round performs `N-1`
waits.
→ **N−1 fields consumed per call**, in steady state.

With the NTSC value `count = 2`, the patch therefore gives exactly 1 field per
call, i.e. the behaviour of `mRetraceCount = 1`. **The equivalence is
proven**, and it is a stable fixed point, not a coincidence of the starting state.

Two useful corollaries:

- Patched **and** `count = 1` → 0 fields per call: no retrace wait
  at all. Not testable live, since the `nop` is blocked by the JIT cache.
- Unpatched, `count = 0` and `count = 1` are indistinguishable (1 field per
  call in both cases). BSE's `mRetraceCount = 0` at the 120 FPS tier therefore
  does not by itself produce 120 presented frames: the VI must run
  at 120 Hz, which Dolphin's VI overclock provides.

### 3.2 Presentation law, verified experimentally

`mRetraceCount = N` should give 59.94/N frames per second. Measured by writing
`TDisplay + 0x4C` directly, with the literal left at `0.5f` to isolate
presentation:

| N | 1 | 2 | 3 | 4 | 0 |
|---|---|---|---|---|---|
| frames/s **measured** | 59.67 | 30.00 | 20.00 | 15.00 | 60.00 |
| 59.94/N expected | 59.94 | 29.97 | 19.98 | 14.98 | — |
| difference | 0.5 % | 0.1 % | 0.1 % | 0.1 % | — |

The law holds, **including the prediction that `N = 0` behaves like `N = 1`**.

### 3.3 The `nop` cannot be applied live

Writing `0x60000000` at `0x802FCB24` does modify the emulated MEM1 — a read-back
confirms the value — but **changes nothing in the behaviour**: Dolphin
keeps executing the compiled JIT block. The `gamemasterplc` fix
therefore cannot be applied through an external memory write.

`mRetraceCount = 1` produces exactly the same effect and **is data**.
That is the path to take, and it is BetterSunshineEngine's.
See [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).

---

## 4. `0x80414904` — the plan's "unidentified" literal

Identified. Two references, both in `TModelGate` (the screen-blur
portals):

| Address | Function |
|---|---|
| `0x801EB16C` | `TModelGate::perform(unsigned long, JDrama::TGraphics*)+0x158` |
| `0x801EC41C` | `TModelGate::loadAfter()+0x3D4` |

### 4.1 Use site — `perform` @ `0x801EB16C`

```c
f32 d = JGeometry::TUtil<f>::sqrt(dx*dx + dy*dy + dz*dz);  // 0x801EB144..158
if (d < 1000.0f) {                 // 0x80414900 = 1000.0f
    this->m0xD0 += 0.01f;          // 0x80414904   <-- the patched literal
    if (this->m0xD0 > 1.0f) {      // 0x80414908 = 1.0f
        this->m0xD0 = 1.0f;
        this->mState = this->mPrevState;   // lha +0xC8 -> sth +0xCA
    }
}
```

`m0xD0` is a normalised progression in `[0, 1]`, reached in 100 calls,
triggered by the player's proximity. It feeds
`TModelGate::screenBlur(JDrama::TGraphics*)` @ `0x801EBD84`.

### 4.2 Initialisation site — `loadAfter` @ `0x801EC414`

The literal belongs to a contiguous parameter block copied into the object:

| Destination | Source | Value |
|---|---|---|
| `+0xE4` | `0x8041490C` | `0.0f` |
| `+0xE8` | `0x80414904` | `0.01f` ← patched |
| `+0xEC` | `0x80414964` | `0.02f` |
| `+0xF0` | `0x8041496C` | `500.0f` |
| `+0xF4` | `0x80414900` | `1000.0f` |

One pair (slow rate, fast rate) and one pair (near radius, far radius).
The DOL **already** contains `0.02f` at `0x80414964` — exactly the value
`3CA3D70A` that the Gecko writes to `0x80414904`. The patch therefore aligns the slow
rate with the fast rate.

### 4.3 Anomaly: the direction of the scaling is doubtful

> **Do not reuse without measurement.** This point is a divergence noted against
> the reference implementation, not a conclusion.

`gamemasterplc` and BSE both scale this literal up with the rate:
`0.01` at 30 FPS, `0.02` at 60, `0.04` at 120.

Yet `m0xD0 += k` is a **per-call** increment. According to the rule of § 1.3,
when going from 30 to 60 FPS:

- if `TModelGate::perform` is in a **simulation** list, it is called
  120 times per second in both cases → **no correction is
  needed**;
- if it is in a **per-rendered-frame** list, the call frequency *doubles* →
  `k` would have to be **divided** by two, not multiplied.

Under both readings, doubling `k` speeds up the fade. At 60 FPS with `0.02`,
the effect would be four times faster than at 30 FPS with `0.01`.

Three possible explanations, none ruled out at this stage:

1. a deliberate aesthetic choice ("make the portals more responsive");
2. a sign error carried over from `gamemasterplc` into BSE;
3. a mechanism that static analysis does not see.

**Decisive experiment** — time a portal's fade at 30 then at 60 FPS,
with the literal patched then unpatched. Four measurements, protocol in
[`04-tests.md`](04-tests.md). Until they are done, do not reuse
this Gecko line by imitation.

---

## 5. The truncation that freezes particles — `TMarioParticleManager::perform`

A fourth timing mechanism, absent from the initial plan and, it seems, from
all the literature on the subject. It is the only known place where the 120 tier
breaks something **through a mechanism of its own**, and not through the general rule of
§ 1.3.

`perform__21TMarioParticleManagerFUlPQ26JDrama9TGraphics` @ `0x80288780`:

```
802887A4  bl     SMSGetAnmFrameRate()     ; 60 / logic clock
802887A8  fctiwz f0, f1                   ; float -> integer conversion, by truncation
802887AC  stfd   f0, 0x90(r1)
802887B0  lwz    r23, 0x94(r1)            ; r23 = the loop counter
802887B4  b      802887C4
802887B8  lwz    r3, 0x3b8(r25)
802887BC  bl     JPAEmitterManager::calc()
802887C0  addi   r23, r23, -1
802887C4  cmpwi  r23, 0
802887C8  bgt    802887B8
```

The particle system is advanced `(int)SMSGetAnmFrameRate()` times per rendered
frame:

| Tier | `SMSGetAnmFrameRate()` | `(int)` | Calls to `calc()` | JPA rate |
|---|---|---|---|---|
| 30 FPS | 2.0 | 2 | 2 per frame | 60 Hz |
| 60 FPS | 1.0 | 1 | 1 per frame | 60 Hz |
| **120 FPS** | **0.5** | **0** | **none** | **0 Hz — frozen** |

JPA is therefore authored at 60 Hz, like the J3D animations, and the loop
realigns it correctly — as long as the factor is an integer. At 120 FPS it would be 0.5,
and an integer loop cannot do half a turn.

**This is not a defect of `SMSGetAnmFrameRate()`.** Its value of 0.5 is
*right*: the 215 other call sites consume it as a float, as the animation advance
rate, and 0.5 animation frames per game frame is exactly
what is needed at 120 FPS. Only this truncation is wrong.

### 5.1 What this freezes

Everything that is JPA, which goes well beyond "effects" in the decorative sense:

- the water jets of Delfino Plaza (`TMapObjWaterSpray::calc` @ `0x801C12D4`,
  which emits through `TMarioParticleManager::emit`);
- **the graffiti entry animation** — `TMario::warpInEffect()` @
  `0x802637A0` goes entirely through `gpMarioParticleManager`
  (`emitAndBindToMtx`, callback `TWarpInCallBack` set at `+0x114`). The
  shrinking of Mario into a "little circle" is emitted, but never advanced: Mario
  jumps and disappears.

The particles are emitted normally; they are neither born, nor advance, nor
die. Depending on the effect, this gives a frozen ribbon or a complete absence.

### 5.2 BetterSunshineEngine does not fix this point

`src/patches/fps.cpp`, reread on 2026-09-22: no mention of JPA or of the
particle manager, and a `case FPS_120` that is limited to
`mRetraceCount = 0`, `0x804167B8 = 2.0f`, `0x80414904 = 0.04f`.
**BSE's 120 FPS mode therefore has the same defect.**

### 5.3 The fix applied, and why it is not exact

`0x802887B0`: `lwz r23, 0x94(r1)` → `li r23, 1`. The counter is 1 whatever
the rate.

At 120 FPS this gives **one** call per rendered frame, i.e. 120 Hz of JPA instead
of the original 60 Hz: **twice too fast**. It is a compensation, not a
correction.

The exact fix requires a call **every other frame** — hence a state
persisting between two frames, hence an ASM hook with its own variable, not a
one-word write. It has not been written.

Unfrozen is better than frozen, but the distinction must stay legible: it is the
only line of the shipped profile that is not correct by construction.
