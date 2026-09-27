# ADR 0001 — Target GMSE01 (NTSC-U)

- **Date**: 2026-09-15
- **Status**: accepted

## Context

Two images of the game are available in `E:\Jeux Gamecube`:

| Identifier | Region |
|---|---|
| `GMSE01` | NTSC-U |
| `GMSP01` | PAL |

At the start of the session, only the PAL image was present. The US image was
added by the user after the discrepancy with the plan was reported.

The initial plan is written for GMSE01: all its addresses, its
references to BetterSunshineEngine and its reference Gecko code are US.

## Decision

The project targets **GMSE01 (NTSC-U, revision 0)**.

## Reasons

1. **The ecosystem is US.** BetterSunshineEngine only supports GMSE01, and the
   plan requires depending on its exported API rather than reimplementing its
   fixes. Targeting PAL would make that rule impossible to apply.
2. **The symbols are US.** `maps/us.map` (15 107 symbols) and the Corona
   symbols (4 439) cover GMSE01. No equivalent table exists for PAL:
   all the work would be done on bare addresses.
3. **NTSC avoids a clock complication.** In PAL, `VIGetTvFormat()` returns
   `VI_PAL` and the logic clock starts from 50 Hz instead of 60. BSE's literal
   values (`0.5` / `1.0` / `2.0`) do not carry over — it would take
   `0.5` / `1.2` / `2.4`. See [`../05-regions.md`](../05-regions.md).
4. **The 120 FPS tier is cleaner.** 60 Hz × 2 = 120 comes out exactly;
   50 Hz would require a non-integer factor.

## Consequences

- The reference DOL is `work/dol/GMSE01.dol`,
  SHA-1 `a6782903ef79d4196c8489ecb1b57decb5b3728f`.
- The PAL image remains extracted (`work/dol/GMSP01.dol`) **for documentation
  purposes only**: it was used to establish the address mapping that corrects
  the erroneous "JP" attribution found in the plan, and serves as a cross-check
  to validate that the tooling hard-codes no address.
- The tooling nonetheless remains region-independent: the `r2`/`r13` bases
  are read from the analysed DOL, never hard-coded. Later PAL support
  would not require rewriting the tools, only redoing the measurements.
- Any PAL support would constitute a separate ADR.

## Rejected alternative

**Target PAL** to match the image initially provided. Rejected: the cost is
a complete port of the symbols and fixes with no existing base, for
no gain, whereas obtaining the US image removes the problem entirely —
which was done.
