# Pre-registration: does the Time Machine forecast the tips better than the trained odds? (fake money only)

Written on 2026-10-21 before any Time Machine forecast was computed. Nothing below may change after the first look; anything added
later is labelled as added later.

## The idea

The video the user sent (a "day-trader-skill" with a Time Machine that simulates a trade 10,000 times as random paths) gave the idea.
For meme coins a random walk misses the rugs. The Time Machine here replays real coins instead: for a coin at scan time it takes the
K most similar coins from the big test that were already priced at that time, one row per coin, and reads their real results at
the horizon. Its forecast is the share of those look-alikes that ended in profit after fees, and the share that went to zero.

If it forecasts better, it replaces the trained profit chance ("up") and zero chance ("zp") on the pick card. If not, they stay
and the Time Machine is not built into the page.

## Data

- Tips: every pick of the 2h profile in the tip record (branch "results", db/memerec, rule m9-2h) with up and zp set and a priced
  horizon result (outs "out": eur, gone). The outcome: profit = eur > 0; zero = gone, or a multiple under 0.02.
- Look-alikes: big-test rows (branch "bigtest", rule m9-2h, scored at or after harness.LEARN_FROM) whose result time is before the
  tip's time (walk-forward: nothing the tip could not have known), with liquidity at least $10k and market cap $30k to $5M.
- The tip's own features: its big-test row of the same scan (same address, snapshot within 30 minutes of the tip). Tips without
  that row are dropped from both sides.

## The forecast (fixed now)

Features: log10(age in hours), log10(market cap), liquidity / market cap, log10(1 + volume / market cap), 1-hour and 6-hour price
change (clipped to -100..+300), buy share. Each feature scaled by its pool median and interquartile range; a missing feature
adds the pool's average squared distance for it. Euclidean distance; the nearest row per coin; K = 100. The forecast is the
share of the K with eur > 0 and the share gone or under 0.02, each shrunk toward the pool's base rate with 10 pseudo-coins.

## Decision

Brier score (mean squared error of the forecast against 0/1) for profit and for zero, Time Machine against the trained odds, on the
same tips:

- **REPLACE** if the Time Machine's Brier is lower for profit AND for zero, AND lower for profit in both halves of the tips (split
  at the median tip time).
- **KEEP the trained odds** otherwise.

Reported beside it, not deciding: the base-rate forecast's Brier (the pool's shares, no neighbours), a calibration table in five
bins, and the number of tips.
