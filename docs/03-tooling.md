# Tooling

Fifteen Python modules, in two families:

- **offline**, on the DOL file — `gciso`, `dol`, `symbols`, `disasm`, `xref`;
- **live**, on a running Dolphin — `dolphin`,
  `measure_substeps`, `patch`, `substep_clock`, `pad`, `test_freefall`,
  `test_physics`, `test_ballistic`, `dolphin_host`, `second_instance`.

Only external dependency: `capstone` (disassembler), installed with
`python -m pip install capstone`.

No tool hard-codes a region-specific address: the `r2`/`r13` bases
are read from the analysed DOL, and the game objects are resolved from the
globals. The offline commands therefore work on `GMSE01`, `GMSP01` and
`GMSJ01`.

---

# Offline tools

---

## `tools/gciso.py` — disc image

Reading a GCM/ISO image: header, FST, file extraction.

```sh
python tools/gciso.py header  <iso>
python tools/gciso.py dol     <iso> <output>
python tools/gciso.py fst     <iso>
python tools/gciso.py extract <iso> <path-in-iso> <output>
```

The size of `main.dol` is not stored in the disc header: it is
deduced from the largest `offset + size` among the 18 declared sections.

The GameCube magic (`0xC2339F3D` at `0x1C`) is checked on every read. A
Wii, RVZ or CISO image is rejected explicitly rather than producing absurd
offsets.

---

## `tools/dol.py` — DOL executable

Section table, virtual address ↔ file offset mapping, typed
reads, pattern search, raw disassembly.

```sh
python tools/dol.py sections <dol>
python tools/dol.py read     <dol> <address> [bytes]
python tools/dol.py dis      <dol> <address> [instructions]
python tools/dol.py f32      <dol> <address> [count]
python tools/dol.py find     <dol> <hex-bytes>
python tools/dol.py findf32  <dol> <value>
```

An address falling in the BSS produces an explicit message: the value
only exists at runtime, not in the file. This is the classic trap when
following a pointer chain from a listing.

Capstone does not know the Gekko's *paired single* instructions (`psq_l`,
`ps_madd`…). They come out as `.byte` instead of making the
disassembly fail — a `.byte` in a listing signals a Gekko instruction, not
a read error.

---

## `tools/symbols.py` — symbol table and demangling

```sh
python tools/symbols.py lookup   <map> <address>
python tools/symbols.py find     <map> <pattern>
python tools/symbols.py demangle <mangled-name>
```

Accepted map format: `name=0xADDRESS`, one entry per line. It is the format of the
maps published by BetterSunshineEngine and Corona.

Names are mangled by **CodeWarrior**, not by the Itanium scheme of
GCC/Clang — `c++filt` cannot read them. The demangler implemented here covers
nested scopes (`Q2`), templates, the `P`/`R`/`C` qualifiers and
const methods. It is deliberately partial: when in doubt it returns the
raw mangled name, because a partially demangled listing remains usable
whereas a wrong listing does not.

**Limitation to be aware of:** a map only gives start addresses, never
sizes. `SymbolTable.containing()` bounds a symbol at the address of the next one,
which overestimates the last symbol of each section. Do not use it to
delimit a function with certainty.

---

## `tools/disasm.py` — annotated disassembly

The main tool. Depends on `dol.py` and `symbols.py`.

```sh
python tools/disasm.py <dol> <map> <function-or-address> [instructions]

python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map SMSGetVSyncTimesPerSec__Fv
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map 0x802FC9A4 80
```

Three annotations are added to the raw listing:

1. **branch targets** resolved to demangled symbols;
2. **small-data accesses** — `lfs f0, -0x3e8(r2)` becomes
   `-> 0x804167B8 = 0x3F000000  f32 0.5  i32 1056964608`. This is the annotation
   that makes this project workable: without it, no float literal is
   identifiable in a listing;
3. **function bounds** — the listing stops at the next symbol when no
   instruction count is given.

The argument can be an address, an exact mangled symbol, or a substring
if it matches only one symbol.

Without a usable map, `__init_registers` is found by following the first `bl`
of the entry point. Passing an empty file as the map is therefore enough to analyse a
DOL without symbols:

```sh
: > work/maps/empty.map
python tools/disasm.py work/dol/GMSP01.dol work/maps/empty.map 0x8029FC8C 20
```

---

## `tools/xref.py` — cross-references

```sh
python tools/xref.py <dol> <map> <address-or-symbol>
```

The DOL has neither relocations nor a symbol table: no index of references
exists. The tool rebuilds it by scanning the executable sections.

Three forms detected:

| Form | Example | Reliability |
|---|---|---|
| D-form relative to `r2`/`r13` | `lfs f0, -0x3e8(r2)` | **exact** — no false positives, nothing missed |
| `lis` + `addi`/`ori` pair | `lis r3, 0x8041 ; addi r3, r3, 0x4904` | certain but **incomplete** |
| branch | `bl fonction` | **exact** |

> **Read the warning.** Detection of `lis`/`lo` pairs only examines
> **adjacent** instructions operating on the same register. A compiler that
> inserts code between the two halves escapes it, and the invalidation of the
> pending register does not cover X-form instructions. Every
> reference found is therefore true, but **an empty result proves nothing**.

In practice this limitation does not hinder the project: all float literals
go through the D-form relative to `r2`, for which detection is exact.

---

# Runtime tools

The five modules above work on the DOL, offline. The next ten
target a **running Dolphin**. They are
Windows-only (Win32 API) and require neither Dolphin's debugger, nor a
breakpoint, nor any action in the user interface.

Rationale and limits of the approach: [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).

## `tools/dolphin.py` — emulated memory

```sh
python tools/dolphin.py info
python tools/dolphin.py read  <address> [bytes]
python tools/dolphin.py u32   <address> [count]
python tools/dolphin.py f32   <address> [count]
python tools/dolphin.py write <address> <hex-bytes>
python tools/dolphin.py deref <address> [offset…]
```

The MEM1 mapping is located by scanning the process's regions,
then **validated by reading the GameCube disc header** (identifier at
`0x80000000`, magic `0xC2339F3D` at `0x8000001C`). This validation distinguishes
the real MEM1 from any other mapping and confirms which image is loaded.

Measured rate: ~405,000 4-byte reads per second, i.e. 2.5 µs per
read.

> **Data yes, code no.** Writing to an **instruction** has no effect:
> Dolphin keeps executing the already-compiled JIT block. Writing to
> **data** takes effect immediately. Verified experimentally.

## `tools/measure_substeps.py` — phase 0

```sh
python tools/measure_substeps.py [duration-seconds]
```

Probes the `TMarDirector + 0x54` accumulator and derives frames/s, substeps/s and
substeps per frame from it.

The measurement is **self-validating**: the accumulator only changes by
`+vsyncRate` and `-5`. If the polling missed a transition, the observed difference would
no longer be 5. The script checks that every decrement is exactly 5 and that
every increment is exactly the same value, and **rejects** the measurement otherwise
instead of reporting it.

## `tools/patch.py` — reversible fixes

```sh
python tools/patch.py status
python tools/patch.py apply <30|60|120>
python tools/patch.py restore
```

Writes only **data**: the literal `0x804167B8`, `mRetraceCount` at
`TDisplay + 0x4C` and the literal `0x80414904`. The original values are
saved in `work/patch-backup.json`, which makes it possible to restore even
after the script has stopped.

`TDisplay` is resolved at runtime through `gpApplication + 0x1C`: the object is
on the heap, its address changes with every session.

This module **applies none** of the object fixes listed in
the initial plan. It lays the rate foundation, not a playable mod.

## `tools/test_freefall.py` — physics regression

```sh
python tools/test_freefall.py [height] [tier…]
python tools/test_freefall.py 3000 30 60
```

Teleports Mario upward by writing `Mario + 0x14`, probes his altitude,
and counts the position integrations as well as the real duration of the fall.
No controller input is needed, so the test is fully
automatable. The position is restored in every case.

It is the strictest check in the whole project: if the physics depended
on the rate, it would show it immediately.

## `tools/substep_clock.py` — counting substeps

```sh
python tools/substep_clock.py [substep-count]
```

Waits for a number of simulation substeps, by counting the decrements of
the `TMarDirector + 0x54` accumulator. Serves as the **unit of measurement** for the whole
test suite: "after 40 substeps" is comparable between tiers, "after 0.5 s"
is not, since the number of frames covered changes with the rate.

Polling at ~2.5 µs versus 2.1 ms per substep: no transition is missed.
The method is **self-validating** — any decrement other than 5 signals a
failed poll, and the measurement is then rejected, never reported.

> **What it cannot do.** It does not see the substeps *during* a
> scene transition: `gpMarDirector` can be null, and the address is
> resolved once and for all at construction. A rebuilt object invalidates
> the clock without anything signalling it.

## `tools/pad.py` — controller input injection

```sh
python tools/pad.py        # demonstration: makes Mario jump
```

Writes directly into `TMarioGamePad` (resolved through `TMario + 0x4FC`), which
makes it possible to drive Mario without a physical controller, without keystrokes and without
stealing focus from Dolphin. This is what makes the test suite automatable.

The game rewrites the object on every frame from the real controller: a background
thread therefore hammers the values continuously, at ~400,000 writes per
second versus one read-back per frame.

> **What it cannot do.** It is a **race**, not a lock. It is
> won by a very wide margin but not always — measured: one attempt lost out of three
> with a 50 ms edge window, none with 200 ms. A test must therefore
> check that the action took place and retry (`test_physics.attempt`), never
> assume that a specific frame saw the input.
>
> Two traps, both paid for in wrong measurements before being understood:
> **a few frames of neutral** are needed before a press, otherwise the game does not
> see an edge; and the edge must be **bounded in time**, otherwise
> Mario presses A again on landing and chains jumps.

## `tools/test_physics.py` — jump and run

```sh
python tools/test_physics.py [tier…]
python tools/test_physics.py 30 60
```

Short jump, long jump and sustained run, at each tier, with automatic choice
of a clear direction (eight azimuths tried, the longest kept).

The verdict is based on the **per-substep profiles** — sequence of vertical
velocities, sequence of running speeds — and not on the heights and
distances, which depend on the terrain as much as on the integrator.

> **What it cannot do.** It cannot tell a physics discrepancy
> from an obstacle. A test that diverges must be confirmed by
> `test_ballistic.py`, which has neither input nor ground contact.
>
> The profile-based criterion dates from 2026-09-17 and **has not yet been replayed**
> on a running Dolphin.

## `tools/test_ballistic.py` — the integrator alone

```sh
python tools/test_ballistic.py [impulse] [tier…]
python tools/test_ballistic.py 42 30 60
```

Places Mario 2500 units above the ground, imposes a vertical velocity on him and
records the arc, substep by substep. No controller input, no scenery, no jump
type: only gravity remains.

This is the project's reference measurement for the question "does the physics
depend on the rate?". The three quantities it produces — sequence of
velocities, number of integrations up to the apex, altitude of the apex — are
independent of everything that is not the integrator.

## `tools/dolphin_host.py` — host control

```sh
python tools/dolphin_host.py savestate [slot]
python tools/dolphin_host.py relaunch [--vi 2.0] [--state <path>]
```

Relaunches Dolphin with a setting passed on the command line (`-C`), which is
the only way to reach the **VBI Frequency Override** on which the 120 tier
depends: this setting lives in the host, not in MEM1, and Dolphin does not reread its
configuration during a game. `-C` writes nothing to `Dolphin.ini`.

> **What it cannot do.** `savestate` **does not work** from a
> command-line agent: `SendInput` does not reach the interactive desktop
> in that context — verified, even `GetAsyncKeyState` called in the injector
> process does not see the keystroke. Without a saved state, `relaunch` **destroys**
> the game in progress.

## `tools/second_instance.py` — isolated instance

```sh
python tools/second_instance.py start [--vi 2.0] [--user <directory>]
python tools/second_instance.py stop
```

Launches a second Dolphin instance with its own user directory,
its own VI overclock and a copy of the memory card, then makes it enter
the game **by itself** — logos, intro, title screen and file selection
passed through by hammering A and START via memory injection. The
user's session is never touched.

Verified on 2026-09-15: stable arrival in game in 92.6 s, without intervention.

> **What it cannot do.** It cannot measure a rate while
> another instance is running: the two compete for the GPU. This is the
> reason this route is **on hold** and must not be launched
> without explicit agreement — see [`00-journal.md`](00-journal.md), session 4.
>
> Its in-game arrival criterion requires several seconds of stability: the
> title screen's attract demo makes `gpMarDirector` valid
> intermittently, and an instantaneous test concludes wrongly.
>
> `stop` stops **all** instances found, including the
> user's.

---

## Rebuilding the environment

```sh
python -m pip install capstone

python tools/gciso.py dol "E:/Jeux Gamecube/Super Mario Sunshine (2002)(Nintendo)(US).iso" \
                      work/dol/GMSE01.dol

curl -sSL -o work/maps/us.map \
  https://raw.githubusercontent.com/DotKuribo/BetterSunshineEngine/master/maps/us.map
```

Expected integrity check:

| File | SHA-1 |
|---|---|
| `work/dol/GMSE01.dol` | `a6782903ef79d4196c8489ecb1b57decb5b3728f` |
| `work/dol/GMSP01.dol` | `a2edfa86880845f663f6f3b49e27cc9409d202bf` |

`work/` only contains regenerable artefacts — extracted DOLs, downloaded
maps, listings. Nothing in it needs to be kept or versioned.
