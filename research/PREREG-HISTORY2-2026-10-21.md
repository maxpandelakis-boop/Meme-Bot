# Pre-registration: a filter that is clearly in profit, on the August to October 2026 rows (fake money only)

Written on 2026-10-21 while the rows were being built (research/history_build2.py, branch "history2"), before any of them was
looked at. Nothing below may change after the first look; anything added later is labelled as added later.

## Why

The user wants the bot "clearly in profit overall, with a few fat hits". On the bot's own record its 2h picks lose about 2.50 to
3.10 per 20 (research/PUSH-2026-10-21.md), no gate change helped (research/GATES-2026-10-21.md) and no exit rule was positive
(exitgrid.json). The new rows hold every graduated pump.fun coin of the bot's own period (about 67,000), so a filter can be
searched on one part and judged on another with far more coins than before.

## Data

The hourly rows of history2: a coin at whole hours 1 to 48 after its graduation, with screener-like numbers and its outcomes.
Rows whose windows touch a recorder outage are left out (gap_pre or gap_1; for the 6-hour exits also gap_6). A coin enters a rule
once, at its first hour that passes (as the bot names a coin once). Results are per 20 after the bot's fees (memebot.tip_net),
clipped to -20..60, and averaged per coin.

Outcomes, each judged separately:
- hold: sold 1.7 hours later at the last price then (the 2h profile's check), in USD
- exit A, the paper account's rule now: -30% stop, 11x target, else sold after 6 hours
- exit B, the rule the user may switch to: -20% stop, 3x target, else sold after 6 hours
A stop sells at the low of the minute that hit it (worse than the stop line), and when a stop and a target fall in the same
minute the stop counts.

## Part 1: does the data agree with the bot? (information only)

The bot's 2h gates as far as the rows hold them (age 6 to 24 h, market cap $100k to $2M, liquidity and 24h volume at least
$15k, no crash, no spike, no wash, liquidity not 90 to 110% of the market cap). Reported: coins, per-coin average for hold,
exit A and exit B, share to zero, share that reached 3x within 6 hours. Expected near the bot's record (about -2.5 to -3.1 per 20
for hold); if it is far off, the rows are suspect and part 2 is reported but not acted on.

## Part 2: the filter search

Base: rows with liquidity and 24h volume at least $15k. Fit: coins that graduated before 2026-09-15 00:00 UTC. Check: coins that
graduated from then on.

Features (14): age_h, market cap, liquidity / market cap, 24h volume / market cap, 1h volume / 24h volume, price change over
5 min, 1 h, 6 h and 24 h, buys / (buys + sells) in the last hour, buyers in the last hour, the top buyer's share of the last
hour's buying, atomic (bundled) swaps / all swaps in the last hour, seconds since the last trade.

Rules: one or two conditions, each "feature at or under its fit 33rd percentile" or "at or over its fit 67th percentile"
(28 single conditions, every pair of conditions on different features), each with hold, exit A or exit B. A rule is eligible
on the fit part when it lets through at least 300 coins. The one rule with the best per-coin average on the fit part is chosen;
nothing else is tried.

It PASSES when on the check part:
1. it lets through at least 150 coins,
2. their per-coin average is above 0 and the 95% coin-bootstrap interval (2000 draws, seed 7) lies wholly above 0,
3. the share of its coins that reached 3x within 6 hours is at least the base's share on the check part.

The ten best fit rules are also shown on the check part, for information only; they decide nothing.

## What follows

PASS: the rule is a candidate. It is checked once more forward, on the bot's own coins of 22 October to 4 November 2026 (the
fixed check), and only then, with the user's OK, built into the bot. FAIL: the user is told plainly that even with 67,000 coins
no simple filter of these numbers is clearly in profit, and the data stays for other questions.
