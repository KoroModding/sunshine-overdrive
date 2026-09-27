# Address register

> Every address used by the project is recorded here with **its level of
> proof** and **the command that reproduces it**. An address missing from this
> register has not been verified and must not be written into code.

Target: `GMSE01` (NTSC-U, revision 0).
Reference DOL: SHA-1 `a6782903ef79d4196c8489ecb1b57decb5b3728f`.

## Levels of proof

| Level | Meaning |
|---|---|
| **M** | read in the machine code — the instruction itself demonstrates it |
| **S** | taken from a symbol table, cross-checked against the machine code |
| **T** | taken from a symbol table alone, not cross-checked |
| **H** | hypothesis — taken from a third-party source, never verified here |

Never write a fix on the strength of an **H**.

---

## Register bases

Set once and for all by `__init_registers` @ `0x80005364`, never
modified afterwards (PowerPC EABI ABI).

| Register | Value | Role | Proof |
|---|---|---|---|
| `r2` | `0x80416BA0` | `.sdata2` base, read-only small data | **M** |
| `r13` | `0x804141C0` | `.sdata` base, read/write small data | **M** |

```sh
python tools/dol.py dis work/dol/GMSE01.dol 0x80005364 6
```

All of the game's float literals are addressed as `displacement(r2)`. A
displacement alone means nothing without this base — which is why
`tools/disasm.py` resolves it automatically.

---

## Functions

| Symbol | Address | Proof | Note |
|---|---|---|---|
| `gpApplication` | `0x803E9700` | **M** | **the object itself**, not a pointer to it |
| `gpMarioPos` | `0x8040E10C` | **M** | pointer to `TMario + 0x10` |
| `gpMarioSpeedX/Y/Z` | `0x8040E11C`…`0x8040E124` | **M** | pointers to `TMario + 0xA4/0xA8/0xAC` |
| `__vt__13TMarioGamePad` | `0x803DF44C` | **T** | used to locate the controllers by scanning, outside a level |
| `gpMarDirector` | `0x8040E178` | **M** | pointer; was `0x80902A40` during a session |
| `gpMarioOriginal` | `0x8040E0E8` | **M** | pointer; was `0x81322DA0` during a session |
| `__vt__10TModelGate` | `0x803D3F9C` | **T** | used to locate the instances by scanning |
| `TMarioParticleManager::perform` | `0x80288780` | **S** | contains the loop of calls to `JPAEmitterManager::calc()` |
| `JPAEmitterManager::calc` | `0x80324F0C` | **S** | advances the particle system by one step |
| `gpMarioParticleManager` | `0x8040E150` | **M** | read by `lwz r3,-0x6070(r13)` |
| `TMapObjWaterSpray::calc` | `0x801C12D4` | **S** | water jets — emits through `TMarioParticleManager::emit` |
| `TMario::warpInEffect` | `0x802637A0` | **S** | graffiti entry — entirely JPA, callback `TWarpInCallBack` |
| `__start` | `0x8000522C` | **M** | entry point, read in the DOL header |
| `__init_registers` | `0x80005364` | **M** | |
| `direct__12TMarDirectorFv` | `0x80299838` | **M** | end `0x80299D48` |
| `changeState__12TMarDirectorFv` | `0x80298E80` | **S** | called at `0x80299D0C` |
| `setupObjects__12TMarDirectorFv` | `0x802B76F4` | **S** | called at `0x802998B8` |
| `SMSGetAnmFrameRate__Fv` | `0x802A7BD8` | **M** | |
| `SMSGetVSyncTimesPerSec__Fv` | `0x802A7C48` | **M** | |
| `waitForRetrace__Q26JDrama6TVideoFUs` | `0x802FC9A4` | **M** | end `0x802FCB5C` |
| `perform__10TModelGateFUlPQ26JDrama9TGraphics` | `0x801EB014` | **M** | |
| `SMS_SetMarioAccessParams__Fv` | `0x80273A0C` | **M** | publishes the offsets of `TMario` — see below |
| `setGamePad__6TMarioFP13TMarioGamePad` | `0x802765EC` | **M** | `stw r4, 0x4fc(r3)`, two instructions in all |
| `checkController__6TMarioFPQ26JDrama9TGraphics` | `0x80251494` | **M** | reads the stick at `0xA8`/`0xAC` of the controller |
| `updateMeaning__13TMarioGamePadFv` | `0x802A80E0` | **M** | reads `0x18`, `0x2C`, writes `0xDC`/`0xDE` |
| `update__10JUTGamePadFv` | `0x802C8F70` | **M** | copies the controller state block |
| `loadAfter__10TModelGateFv` | `0x801EC048` | **M** | |
| `screenBlur__10TModelGateFPQ26JDrama9TGraphics` | `0x801EBD84` | **T** | |
| `VIWaitForRetrace` | `0x8034F684` | **M** | target of the `bl` at `0x802FCB24` |
| `VIGetRetraceCount` | `0x803504EC` | **M** | |
| `VIConfigure` | `0x8034FB4C` | **M** | |
| `VIFlush` | `0x803502E8` | **M** | |
| `VISetBlack` | `0x80350470` | **M** | |
| `VISetNextFrameBuffer` | `0x80350404` | **M** | |
| `VIGetTvFormat` | `0x8035069C` | **M** | called by `SMSGetVSyncTimesPerSec` |
| `OSGetTick` | `0x803494F0` | **M** | |
| `IsEqualRenderModeVIParams__6JDrama…` | `0x802FB808` | **M** | |
| `gameLoop__12TApplicationFv` | `0x802A5F50` | **T** | taken from the initial plan, not cross-checked |
| `proc__12TApplicationFv` | `0x802A6398` | **T** | same |
| `initialize__12TApplicationFv` | `0x802A73C4` | **T** | same |
| `startRendering__Q26JDrama8TDisplayFv` | `0x802F7FD8` | **T** | same |
| `endRendering__Q26JDrama8TDisplayFv` | `0x802F80D0` | **T** | same |
| `SMSSetupGameRenderingInfo__FPQ26JDrama8TDisplayb` | `0x802A5010` | **T** | same |

---

## Literals — `.sdata2` pool

| Address | Value | Role | Proof |
|---|---|---|---|
| `0x804167B8` | `0.5f` | multiplicand of `SMSGetVSyncTimesPerSec` | **M** |
| `0x804167D8` | `60.0f` | NTSC / MPAL / EURGB60 rate | **M** |
| `0x804167DC` | `50.0f` | PAL rate | **M** |
| `0x80414900` | `1000.0f` | `TModelGate` — far radius | **M** |
| `0x80414904` | `0.01f` | `TModelGate` — slow fade rate | **M** |
| `0x80414908` | `1.0f` | `TModelGate` — fade bound | **M** |
| `0x8041490C` | `0.0f` | `TModelGate` — initial value | **M** |
| `0x80414964` | `0.02f` | `TModelGate` — fast fade rate | **M** |
| `0x8041496C` | `500.0f` | `TModelGate` — near radius | **M** |

```sh
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x804167B8
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x80414904
```

### Consumers of `0x804167B8`

Three, and not two as the initial plan implies:

| Site | Function |
|---|---|
| `0x802A5EFC` | `TApplication::drawDVDErr()+0x3B8` |
| `0x802A7C24` | `SMSGetAnmFrameRate()+0x4C` |
| `0x802A7C94` | `SMSGetVSyncTimesPerSec()+0x4C` |

The patch therefore also affects the disc error screen. A side effect of a
shared constant pool, with no expected consequence under emulation.

---

## Fix points

| Address | Original content | Role of the patch | Proof |
|---|---|---|---|
| `0x804167B8` | `3F000000` (`0.5f`) | `→ 3F800000`: logic clock at 60 Hz **and** animation rate realigned | **M** |
| `0x802FCB24` | `48052B61` (`bl VIWaitForRetrace`) | `→ 60000000` (`nop`): one field per call. **No effect live** — see below | **M** |
| `TDisplay + 0x4C` | `2` | `→ 1`: one field per frame. **Preferred route** — it is data | **M** |
| `0x80414904` | `3C23D70A` (`0.01f`) | `→ 3CA3D70A` (`0.02f`): `TModelGate` fade. **Doubtful rationale**, see [`01-mechanisms.md` § 4.3](01-mechanisms.md) | **M** for the identity, **H** for the rationale |
| `0x802887B0` | `80010094` (`lwz r23,0x94(r1)`) | `→ 3AE00001` (`li r23,1`): unfreezes the particle system. **Compensation, not an exact fix** — see [`01-mechanisms.md` § 5](01-mechanisms.md) | **M** |
| `0x800066EC` | ASM hook | `TBoidLeader` area — flock speed | **H** |
| `0x80C28028` | ASM hook | not analysed | **H** |

The `600` in `direct()` is an **immediate** (`li r3, 0x258` @ `0x8029985C`),
not a literal in memory: it cannot be modified by a simple write.
Only the divisor can, indirectly via `0x804167B8`.

### Data versus code — mandatory rule

An external write to an **instruction** has no effect as long as Dolphin
executes the already-compiled JIT block. Verified on 2026-09-15: `nop` written at
`0x802FCB24`, read-back confirming `0x60000000`, and **no change in
behaviour**.

A write to **data** takes effect immediately.

| Point | Nature | Usable live |
|---|---|---|
| `0x804167B8` | f32 literal | **yes** |
| `0x80414904` | f32 literal | **yes** |
| `TDisplay + 0x4C` | u16 field | **yes** |
| `0x802FCB24` | instruction | **no** |

`mRetraceCount = 1` and the `nop` produce the same effect; **they cannot be
combined with impunity** — once neutralised, `waitForRetrace` consumes `count - 1`
fields per call, hence zero with `count = 1`, and the game runs away. Any tool
that sets the count must read `0x802FCB24` first.

**The "code: no" rule only applies to external writes.** Dolphin's
PatchEngine — the `[OnFrame]` section of a per-game profile — applies its
writes at boot, before the JIT compiles the block: an instruction fix
takes effect there. This is the route chosen for delivery.
See [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md) and
[`adr/0005-gecko-or-data.md`](adr/0005-gecko-or-data.md).

### JAI audio — fade durations (session 7, `tools/fixes/fades.py`)

Reproduce: `python tools/fixes/fades.py` (checks every original word in
the DOL, then prints the listing), `python tools/disasm.py work/dol/GMSE01.dol
work/maps/us.map <symbol>`.

| Address | Symbol | Original content | Role | Proof |
|---|---|---|---|---|
| `0x8030A3B0` | `JAISound::initMoveParameter` | `9421FFE0` (`stwu r1,-0x20(r1)`) | duration in `r5`; sequences and streams | **S** |
| `0x8030B700` | `JAISound::setSeInterVolume` | `7C0802A6` (`mflr r0`) | duration in `r5` (`addi r30,r5,0`), `setSeInterMovePara` inlined | **S** |
| `0x8030B8C8` | `JAISound::setSeInterPan` | `7C0802A6` | same | **S** |
| `0x8030BA90` | `JAISound::setSeInterFxmix` | `7C0802A6` | same | **S** |
| `0x8030BC58` | `JAISound::setSeInterDolby` | `7C0802A6` | same | **S** |
| `0x8030BE20` | `JAISound::setSeInterPitch` | `7C0802A6` | same (`addi r30,r5,0`) | **S** |
| `0x8030C690` | `JAISound::setSePositionDopplar` | — | inlined Doppler transition, duration `dopplarMoveTime`; **not fixed** | **S** |
| `0x8040CD64` | `JAIGlobalParameter::dopplarMoveTime` | `0000000F` (15) | read by `setSePositionDopplar` **and** `checkPlayingSeqTrack` (via `setSeqInterPitch`): do not multiply it as data | **S** |
| `0x8040CD8C` | `JAIGlobalParameter::dopplarParameter` | `45480000` (3200.0) | Doppler divisor, a single read (`0x8030ACE4`) | **S** |
| `0x8001604C` | `MSSetSoundTL<MSSetSound>::frameLoopDyna` | — | `+0x54` clock of the FLUDD sound sets, +1 per JAI pass; **not fixed** | **S** |
| `0x8001D67C` | `MSModBgm::loop` | — | counter `+0x4` (thresholds 5 and 180); **not fixed** | **S** |

`JAIMoveParaSet`: target `+0`, current `+4`, step `+8`, counter `+0xC` (u32).
`JAISound + 0x38` → `JAISeqParameter`: 309 `JAIMoveParaSet` from `+0x04` to
`+0x1353` (Graffito-Decomp, `JAIParameters.hpp`, **T** for the layout).

---

## `SMS_SetMarioAccessParams()` — the function that proves the offsets of `TMario`

Twenty-five instructions, no calls: it takes `gpMarioOriginal` and publishes a
dozen pointers into the interior of the object. Each of these pointers is
a **machine proof** of the corresponding offset, without having to dig through
the game code.

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map SMS_SetMarioAccessParams__Fv
```

```
80273A0C  lwz   r8, -0x60d8(r13)   ; r8 = gpMarioOriginal
80273A18  addi  r9, r8, 0xa4       ; r9 = &mSpeed.x
80273A1C  addi  r4, r8, 0x10       ; r4 = &mPosition.x
80273A30  addi  r7, r9, 4          ; &mSpeed.y
80273A34  addi  r6, r9, 8          ; &mSpeed.z
80273A50  stw   r9, -0x60a4(r13)   ; -> gpMarioSpeedX
```

| Global | Address | Value | Proven offset |
|---|---|---|---|
| `gpMarioAddress` | `0x8040E108` | `mario + 0` | — |
| `gpMarioPos` | `0x8040E10C` | `mario + 0x10` | position X/Y/Z |
| `gpMarioAngleX/Y/Z` | `0x8040E110`…`0x8040E118` | `mario + 0x94`, `+0x96`, `+0x98` | angles (s16) |
| `gpMarioSpeedX/Y/Z` | `0x8040E11C`…`0x8040E124` | `mario + 0xA4`, `+0xA8`, `+0xAC` | **velocity X/Y/Z** |
| `gpMarioLightID` | `0x8040E128` | `mario + 0xF8` | |
| `gpMarioFlag` | `0x8040E12C` | `mario + 0x118` | |
| `gpMarioThrowPower` | `0x8040E130` | `mario + 0x820` | |
| `gpMarioGroundPlane` | `0x8040E134` | `mario + 0xE0` | |

This is what moves `TMario + 0xA4` from a session deduction to an
address of level **M**. `tools/test_physics.py` and `tools/test_ballistic.py`
write the velocity at this offset.

---

## Structure offsets

| Structure | Offset | Field | Proof |
|---|---|---|---|
| `TMarDirector` | `0x4C` | flags (`0x2000` first substep, `0x4000` last) | **M** |
| `TMarDirector` | `0x54` | substep accumulator | **M** |
| `TMarDirector` | `0x34` | perform list — animations, last substep | **M** |
| `TMarDirector` | `0x38`, `0x3C`, `0x40` | perform lists — drawing | **M** |
| `TMarDirector` | `0x260` | "objects initialised" boolean | **M** |
| `JDrama::TVideo` | `0x80` | `OSGetTick()` of the last retrace | **M** |
| `JDrama::TVideo` | `0x84` | target retrace counter | **M** |
| `JDrama::TDisplay` | `0x4C` | `mRetraceCount` (u16) | **M** — read as 2 in live memory, and its law verified experimentally |
| `TApplication` | `0x1C` | `mDisplay` | **M** — `lwz r3, 0x1c(r31)` in `gameLoop` |
| `TMario` | `0x10`/`0x14`/`0x18` | position X / Y / Z (f32) | **M** — read in live memory |
| `TMario` | `0x24`…`0x2C` | scale (1,1,1) | **M** |
| `TMario` | `0x94`/`0x96`/`0x98` | angles X / Y / Z (s16) | **M** — `SMS_SetMarioAccessParams` |
| `TMario` | `0xA4`/`0xA8`/`0xAC` | velocity X / Y / Z (f32) | **M** — `SMS_SetMarioAccessParams` |
| `TMario` | `0x4FC` | `mGamePad` | **M** — `stw r4, 0x4fc(r3)` in `setGamePad` |
| `TMarioGamePad` | `0x18` | **held** buttons (u32) | **M** — block copied by `JUTGamePad::update`, read by `updateMeaning` |
| `TMarioGamePad` | `0x1C` | **newly pressed** buttons (u32) | **M** for the field, **experimental** for the meaning — see below |
| `TMarioGamePad` | `0x2C` | analog trigger (f32) | **M** — `lfs f1, 0x2c(r30)` in `updateMeaning` |
| `TMarioGamePad` | `0xA8`/`0xAC` | main stick X / Y (f32, `[-1,1]`) | **M** — `lfs f0, 0xa8(r4)` in `checkController` |
| `TMarioGamePad` | `0xDC`/`0xDE` | current / previous "meaning" (u16) | **M** — `sth` in `updateMeaning` |
| `TModelGate` | `0xD0` | fade progress, `[0,1]` | **M** |
| `TModelGate` | `0xC8` / `0xCA` | state / previous state | **M** |
| `TModelGate` | `0xE4`…`0xF4` | fade parameter block | **M** |


---

## Held versus edge — `TMarioGamePad + 0x18` and `+ 0x1C`

`JUTGamePad::update()` @ `0x802C8F70` copies a 0x30-byte block from the
static array `0x80404484 + port × 0x30` to `pad + 0x18`. The first two
words of this block therefore land at `+0x18` and `+0x1C` — the
"held buttons / newly pressed buttons" pair of `JUTGamePad::CButton`.

The **meaning** of the two fields was settled experimentally on 2026-09-15, by
injection into a running game:

| Write | Effect on Mario |
|---|---|
| `+0x18` alone = `A` | **nothing** (dY = 0.00) |
| `+0x1C` alone = `A` | **jump** (dY = 73.79) |
| `+0xA8` = 1.0 | run (dX = 717.04) |
| `+0xAC` = 1.0 | run (dZ = 933.20) |

The jump is therefore triggered on the **edge**, not on the hold. Practical
consequence, written into `tools/pad.py`: replaying the edge on every frame
amounts to pressing A again as soon as Mario lands, which chains jumps and makes
any height measurement unusable.

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map update__10JUTGamePadFv
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map updateMeaning__13TMarioGamePadFv
```
