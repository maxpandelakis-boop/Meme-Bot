# Pre-registration: which 2h gates separate nothing, on June and July 2026 (fake money only)

Written on 2026-10-21 before any June/July row was split by these gates (branch "history", research/history_build.py; the only
earlier look at those rows is research/HISTORY-2026-10-21.md, the liquidity-share veto). Nothing below may change after the
first look; anything added later is labelled as added later.

## Why

The user asked to replace old parts with new ones instead of adding more. A gate that throws coins away without them doing worse
is an old part that costs coins and gives nothing back. A first pass on the big test (2h profile, 6 to 21 October, per coin, the
coins that failed only that one gate against the gate passers; the discovery data, already searched by the study of
2026-10-21) gave, per 20 after fees:

| gate | coins | vetoed minus passers | 95% coin bootstrap |
|---|---:|---:|---|
| young (under 6 h) | 206 | -6.70 | -8.78 to -4.28 |
| liq (under $15k) | 153 | -15.39 | -16.38 to -14.41 |
| old (over 24 h) | 776 | -0.17 | -1.00 to +0.73 |
| mc (outside $100k to $2M) | 663 | -0.07 | -1.05 to +0.80 |
| copy | 120 | +0.26 | -1.18 to +1.74 |
| crash | 145 | +0.54 | -1.09 to +2.35 |
| spike | 128 | -1.03 | -2.39 to +0.22 |
| wash | 69 | -1.80 | -3.75 to +0.15 |
| vol (under $15k a day) | 93 | -1.08 | -2.45 to +0.23 |

That is a hint, not a result: these rows were searched before. June/July decides.

## Data and population

The rows of research/check_history_veto.py (PumpSwap pair, whole hours after the graduation, a price 1.7 hours later or a rug
before then, the same outcome: what 20 became after the bot's fees, clipped to -20..+60, a rug or under 2% of the entry is -20).
Pools at 0.9 to 1.1 times liquidity to market cap (FluxBeam-like) are left out throughout.

The 2h gate as a screener shows it (ages 6 to 24 h; market cap $100k to $2M; liquidity and 24-hour volume at least $15k; crash:
1-hour change -10% or less, 6-hour -50% or less, 24-hour -70% or less; spike: 1-hour +200% or more, 6-hour +90% or more; wash:
24-hour volume over memebot's 2h GATE_MAX_VOLMC times the market cap). Holder, RugCheck, source-list, copy and liquidity-share
checks are not part of it.

For each gate G of crash, spike, wash, mc, vol and old: the "vetoed" rows fail G and pass every other gate of the list above;
the "kept" rows pass all of them. For "old" the age window of the vetoed rows is 24 to 48 hours (the data ends at 48). For "mc"
both sides of the band count. liq and young are not tested (they separate strongly in October and are cheap insurance); copy
cannot be rebuilt (no ticker in the data) and stays.

## Decision per gate (each coin's mean over its rows, as in the earlier check; coin bootstrap of the difference, 2,000 resamples, seed 7)

- **REMOVE** if the 95% interval of (vetoed minus kept) lies wholly above -1.00 per 20 (the gate is shown to save less than 1 per
  coin) AND the vetoed coins went to zero (any row 98% down or a rug) at most 5 points more often than the kept coins.
- **KEEP** otherwise.
- **UNDECIDED, KEEP** with fewer than 20 vetoed coins.

The liquidity-share veto (GATE_MAX_LIQMC) already failed its own pre-registered check (research/HISTORY-2026-10-21.md) and is
proposed for removal on that result alone.

## Reported beside it, not deciding

Per row; the first and second half of the population (split at the median time); the base rate of all kept coins.

## What follows

Only gates marked REMOVE in June/July may be taken out of the 2h profile, and only with the user's word (asked for on 2026-10-21 for
gates that fail this test). The change goes to the user as a pull request; the forward check of 4 November (research/check_liqmc.py)
keeps running on whatever stays.
