# Pre-registration: the liquidity-share veto on June and July 2026 (fake money only)

Written on 2026-10-21 before the June/July rows (branch "history", research/history_build.py) were looked at. Nothing below
may change after the first look; anything added later is labelled as added later.

## Data

The post-graduation snapshots of the Pumpfun Memecoin Corpus (Slinky21, Hugging Face, 5 June to 14 July 2026), PumpSwap pair
only, sampled at whole hours after each coin's graduation (research/history_build.py). A third period: no row of it was part
of the study of 2026-10-21 (7 to 20 October).

## Population (the 2h profile's gate, as far as a screener shows it)

Rows with age 6 to 24 hours after the graduation, a price 1.7 hours later or a rug before then, and: market cap $100k to $2M,
liquidity at least $15k, 24-hour volume at least $15k, not crashed (1-hour change -10% or less, 6-hour -50% or less, 24-hour
-70% or less), not spiked (1-hour change +200% or more, 6-hour +90% or more). The holder, RugCheck and source-list gates are
not in this data and are left out. Pools at 0.9 to 1.1 times liquidity to market cap (the FluxBeam-like family) are left out.

## Outcome

What a 20 ticket became 1.7 hours later after the bot's fees (memebot.tip_net of the price multiple), clipped to -20..+60. A
rug before the check (the corpus's rug time) or a price under 2% of the entry counts as -20. Rows without a price at the check
and without a rug are dropped (the collector stopped looking, nothing is known).

## Hypothesis H1 (the one that decides)

Vetoed rows: liquidity at 20% of the market cap or more. Each coin's mean result over its rows in the population, vetoed and
kept separately. H1 holds if the vetoed coins average worse than the kept coins AND the 95% interval of that difference from
a coin bootstrap (2,000 resamples, seed 7) lies wholly below zero. With fewer than 20 vetoed coins H1 is undecided.

## Reported beside it, not deciding

- The same per row, per half (split at the median scan time) and per week; the share that went to zero (98% down or a rug).
- A market-cap floor of $200k instead of the veto, the same way (the study found the veto close to such a floor).
- The paper account's exits on the same rows (stop -30%, 11x, 6 hours) from the 6-hour path, as a baseline only.
- All coins of the population without any veto: the base rate a rule has to beat.

## What follows from it

If H1 holds, the veto stays and the 4 November check still runs. If H1 fails, I report that to the user and propose taking
the veto out; nothing is changed without the user's word.
