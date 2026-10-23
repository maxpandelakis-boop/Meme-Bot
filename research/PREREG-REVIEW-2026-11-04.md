# Pre-registration: the review of 4 November 2026 (fake money only)

Written on 2026-10-23 at about 07:30 UTC, before the review. Nothing below may change after this date; anything added later is
labelled as added later. Research only: no bot, account, rule or page changes with this file.

## Why this file

On 4 November seven paper accounts or rules are looked at at once: the Pick account, the Radar account 🚀, the Learning Pick and
the four shadow rules A-D on the Pick's buys. With seven candidates and two weeks of trades, one of them can look good by luck
alone. This file fixes now, before the numbers are in, what counts as "holds", so the review cannot pick the lucky one afterwards.

## What was looked at before writing

- The Pick's own record before its fresh start (paper rule v2, 50 EUR, 10-22 Oct, db/memepos + db/memeexit on branch results):
  103 closed trades, -612.88 EUR, -11.9 % per trade, standard deviation 34 %, 37 % in profit, 95 % bootstrap range -18.4 % to
  -5.2 % per trade. Exits: 47 stops, 2 take-profits (11x), the rest at the time limit. 2 of 13 days ended in profit.
- Since the fresh start (22 Oct 10:08 UTC) to 23 Oct 07:00 UTC: 5 closed Pick trades, +46.09 EUR, of which one coin (ヤギ) +44.39.
  Radar account: 0 buys.
- research/RESULTS-2026-10-15.md: a random coin per scan (-1.95 per 20) did not lose more than the bot's top pick (-2.35); every
  scan's all-coin average was negative (0 of 203).
- The rocket hunter's out-of-sample replay (12,084 unseen coins): every tier negative, the strictest -7.84 per 20.

## The trades that count

Closed trades only, each account from its own start: Pick and Radar from 22 Oct 10:08 UTC (memebot.FRESH_AT), the shadow rules
from 22 Oct 16:00 UTC (shadow.SINCE), the Learning Pick from its first live buy (22 Oct 21:58 UTC). The last buy that counts is
before 3 Nov 18:00 UTC, so every 6- and 12-hour window has closed by the review. Nothing is left out after the fact (no "that was
a glitch" unless the bot's own glitch filter already removed it).

## The measure

Per trade: (EUR back - ticket) / ticket, after the account's own paper fees, then minus a real-cost allowance for what paper does
not charge: 1.5 points per round trip for the 50 EUR accounts (Pick, Learning Pick, shadow rules), 3 points for the Radar's 20 EUR
buys. The allowance is an assumption, not a measurement: the DEX pool fee (about 0.25 % each way), a priority fee or tip per
transaction (a fixed amount that weighs more on a small ticket) and a minute of delay between the signal and a real fill (worse
for a coin that is already flying).

## "Holds" (all four must be true)

1. At least 40 closed trades. Fewer: "too few to judge", no verdict either way (likely for the Radar).
2. The mean after the allowance is above 0.
3. The one-sided bootstrap lower bound is above 0: the 1st percentile of 10,000 re-draws of the account's trades (1 % instead of
   5 % because seven candidates are looked at at once).
4. Without its single best trade, the total is still above 0 (one lucky coin is not a strategy).

With about 40 trades and a spread like the Pick's (34 %), point 3 needs a mean of about +13 % per trade. A small real edge would
not show in two weeks: "does not hold" on 4 November means "not proven", and the longer record above says the Pick lost.

## The shadow rules A-D

Two questions, kept apart:
- Better than K (the real rule replayed on the same buys): paired per buy, at least 40 buys, the 1st percentile of 10,000 paired
  re-draws of (rule - K) above 0.
- Profitable: the four points above on the rule's own trades.
A rule that is better than K but not profitable only loses less. A change of the Pick's sell rule restarts the Pick account and
needs the user's explicit OK either way.

## What follows

- Nothing holds (the expected result, given the record above): the review says so plainly. The user chooses: keep the paper
  accounts running for more trades, change what the bot hunts, or pause. No real money.
- Something holds: it runs two more weeks on paper, unchanged, and is judged again by the same four points before anything is
  switched. Never real money from this review alone.
