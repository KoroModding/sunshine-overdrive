# Regions

> The initial plan sets the rule: **do not confuse the regions**. This document
> establishes the correspondence by proof rather than by the cheat code
> table, and corrects an erroneous attribution noted in the plan.

## Project target

**`GMSE01` — NTSC-U, revision 0.** This is the region covered by
BetterSunshineEngine, by the Corona symbols and by the `us.map` map. All
the addresses in [`02-addresses.md`](02-addresses.md) refer to it.

| Image | Identifier | Region | DOL SHA-1 |
|---|---|---|---|
| `Super Mario Sunshine (2002)(Nintendo)(US).iso` | `GMSE01` | NTSC-U | `a678…728f` |
| `Super Mario Sunshine (Europe) (En,Fr,De,Es,It).iso` | `GMSP01` | PAL | `a2ed…02bf` |

The PAL DOL was extracted and analysed to establish the correspondence below,
but **the project does not target PAL**. See [`adr/0001-target-region.md`](adr/0001-target-region.md).

---

## Correction: `0x8040DD10` and `0x8040BE54` are **PAL** addresses

The initial plan, in the section "Do not confuse the regions", states:

> The JP port of the addresses in BSE seems wrong: `0x8040DD10` and
> `0x8040BE54` land, in the GMSJ01 symbols, on a literal from
> `NpcInitPrg.cpp` and on constants from `s_atan.c`.

The observation is right — these addresses mean nothing in JP — but the
conclusion is only half right. **They are not badly ported JP addresses: they
are the PAL addresses.** They appear as-is in the
`$60FPS [gamemasterplc]` code of `Sys/GameSettings/GMSP01.ini` shipped with Dolphin.

### Proof

`0x8040DD10` contains `3F000000` (`0.5f`) in the PAL DOL, and the function that
loads it is structurally identical to `SMSGetVSyncTimesPerSec`:

```
; GMSP01, 0x8029FC8C
8029FC9C  lfs    f31, -0x548(r2)   ; 0x8040DD38 = 60.0f
8029FCA0  bl     0x803488F8        ; VIGetTvFormat
8029FCA4  cmpwi  r3, 2
...
8029FCD4  lfs    f31, -0x544(r2)   ; 0x8040DD3C = 50.0f
8029FCD8  lfs    f0,  -0x570(r2)   ; 0x8040DD10 = 0.5f
```

Same sequence of comparisons, same three literals, same role. `r2` is
`0x8040E280` in PAL (`lis r2,-0x7fc0 ; ori r2,r2,0xe280` @ `0x8000536C`).

```sh
: > work/maps/empty.map
python tools/disasm.py work/dol/GMSP01.dol work/maps/empty.map 0x8029FC8C 20
python tools/xref.py   work/dol/GMSP01.dol work/maps/empty.map 0x8040DD10
```

BSE therefore labelled a set of `GMSP01` addresses as "JP". To be reported upstream if the
project contributes to that repository.

---

## Correspondence table

| Role | `GMSE01` (US) | `GMSP01` (PAL) | Proof |
|---|---|---|---|
| `r2` base (`.sdata2`) | `0x80416BA0` | `0x8040E280` | **M** |
| `r13` base (`.sdata`) | `0x804141C0` | `0x8040B960` | **M** |
| `SMSGetVSyncTimesPerSec` | `0x802A7C48` | `0x8029FC8C` | **M** |
| literal `0.5f` (logic clock) | `0x804167B8` | `0x8040DD10` | **M** |
| literal `60.0f` | `0x804167D8` | `0x8040DD38` | **M** |
| literal `50.0f` | `0x804167DC` | `0x8040DD3C` | **M** |
| `bl VIWaitForRetrace` in `waitForRetrace` | `0x802FCB24` | `0x802F4CB4` | **H** (taken from the `.ini`, not cross-checked) |
| literal `0.01f` (`TModelGate`) | `0x80414904` | `0x8040BE54` | **M** for the content, **H** for the role |
| `TBoidLeader` hook | `0x800066EC` | `0x800066EC` | **H** |

The two regions share the address of the `TBoidLeader` hook — the leading executable
code is identical. The differences only appear further on:
`0x802A7C48 − 0x8029FC8C = 0x7FBC` for code, `0x804167B8 − 0x8040DD10 = 0x8AA8`
for `.sdata2`. **The offset is not uniform**: never port
an address from one region to the other by subtracting a constant delta.

The number of consumers also differs: the `0.5f` literal has **three**
references in US and **four** in PAL. A mechanical port would miss the
fourth.

---

## PAL: the "60 FPS" code does not give 60

A direct consequence of the reading above, and a point that neither the initial plan nor
Dolphin's `.ini` mentions.

`SMSGetVSyncTimesPerSec()` returns `result × 0.5f`, where `result` depends on
`VIGetTvFormat()`:

| Format | Value | Original return | Return with `0.5f → 1.0f` |
|---|---|---|---|
| `VI_NTSC`, `VI_MPAL`, `VI_EURGB60` | `60.0f` | 30 | **60** |
| `VI_PAL` | `50.0f` | 25 | **50** |

On a console or a Dolphin configuration in PAL 50 Hz, the
`$60FPS [gamemasterplc]` code of `GMSP01.ini` therefore produces **50 FPS**, not 60. Game
speed stays correct — the accumulator brings the simulation back to 120 Hz
(4 5 5 5 5 4 5 5 substeps, average 4.8 at 25 Hz; 2 2 3 2 3 2 2 3, average 2.4 at
50 Hz), but presentation caps at 50.

For real 60 FPS in PAL, **EURGB60** (PAL60 / 480p) is required, which makes
`VIGetTvFormat()` return `VI_EURGB60`. For 120 logical FPS in PAL 50 Hz, the
literal would have to be `2.4f`, not `2.0f` — BSE's values cannot be
transposed as-is.

> **Not verified** — neither of these two conclusions has been tested at
> runtime. They follow from the code as read, and are moot as long as the
> project stays on `GMSE01`.

---

## Decompilations

| Repository | Target | Use here |
|---|---|---|
| `doldecomp/sms` | `GMSJ01` | reading; PAL broken, US not supported |
| `ryanbevins/Graffito-Decomp` | `GMSJ01` | active fork, 0 *NonMatching* units — best base for reading |
| `shibbo/Corona` | `GMSE01` | symbols, archived since 2020 |
| `DotKuribo/BetterSunshineEngine` | `GMSE01` | `maps/us.map`, 15 107 symbols |

The decompilation targets **JP** whereas the project targets **US**. Reading
the decompilation gives the *structure*, never a directly usable
address. Every address must be found again in the US DOL — this is
exactly what `tools/xref.py` does.
