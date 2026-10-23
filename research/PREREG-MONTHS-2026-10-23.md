# Pre-registration: the bots' rules and every rule we can build, month by month (fake money only)

Written on 2026-10-23 at about 20:00 UTC, while the new months were still being fetched (research/months_fetch.py,
.github/workflows/months-data.yml) and before any of their candles was looked at. Nothing below may change after the first
look; anything added later is labelled as added later. Research only: nothing is built into the bots or switched on from it.

## Why

The user asked for tests "over months, not only days", then for "all possible rules, as many as you can, until you find
something" (23 Oct, 19:32-19:36 UTC). Searching until something turns up always finds something by luck: among hundreds of
thousands of rules the best one on the data it was picked on is always positive. So here a rule counts as found only if it
was picked on older months and then holds on a month it had not seen, after correcting for the number of rules tried. The
earlier searches (research/SEARCH-2026-10-21.md: 213,474 rules on 10 Aug-8 Oct and the bot's own scans) found nothing; the new
thing is more months.

## Data: five windows, one format

| window | graduations | source |
|---|---|---|
| w1 | 25 Apr - 24 May 2026 | GeckoTerminal 5-minute candles, Helius graduation list (branch callsdata) |
| w2 | 25 Jun - 24 Jul 2026 | same |
| w3 | 10 Aug - 9 Sep 2026 | history2 one-minute bars (HF Slinky21/Pumpfun_v2_dataset) made into 5-minute USD candles |
| w4 | 10 Sep - 8 Oct 2026 | same |
| w5 | 9 - 21 Oct 2026 | GeckoTerminal 5-minute candles, Helius list (branch backfill) |

Free data ends there: GeckoTerminal's free API reaches 6 months back (about 24 April), Helius lists for 25 May-24 Jun and
25 Jul-9 Aug did not finish (research/CALLS-2026-10-22.md), and HF's dataset starts 10 August. Every coin with a start SOL side
of 10 or more (liquidity needs it), the first 48 hours after its graduation. If a window's fetch is incomplete when the check
runs, the pools it has are a sample in time order of the window (oldest first); the report says how many of how many.

Numbers, the same for every window, from candles closed before the entry only: price = the last close; market cap = price x 1e9;
liquidity = 2 x SOL side from the start reserves' constant product (sqrt(sol0 x tok0 x price in SOL)) in USD (Binance SOL by
hour); 24 h volume; the last hour's share of it; the price change over 5 min, 1 h, 6 h, 24 h and since the graduation; distance
from the high since the graduation and hours since that high; the spread of 5-minute returns over the last hour; candles with
trades in the last hour (0-12); minutes since the last trade; the last hour's volume; the share of rising candles in the last
hour. 17 numbers. Buys/sells, buyers, wallets and RugCheck numbers are not in the GeckoTerminal months, so no rule uses them.

w3/w4 rows whose window from 1 h before the entry to 6 h after touches a recorder outage of 10 minutes or more of history2 are
left out (as in research/HISTORY2-2026-10-21.md).

## Sell rules (222), on 5-minute closes after the entry candle

As the Pick's live rule on minute closes: a stop sells at the first close at or under its line, booked at that close or the
line, whichever is lower; a target sells at the first close at or over it, booked at the target; otherwise sold at the last
close before the time limit (a coin without trades keeps its last price).
- stop none / -10 / -20 / -30 / -50 / -70 %, target 1.2x / 1.5x / 2x / 3x / 5x / 11x / none, time 1 / 2 / 6 / 12 / 24 h (210)
- trailing stop 20 / 30 / 50 % under the best close since the entry, time 6 / 12 / 24 h (9)
- half at 2x, the rest by K; half at 1.5x, the rest by K; half at 2x, the rest by no stop / 24 h (3)

Named ones: K = -30 % / 11x / 6 h (the Pick and the Radar today), shadow A = -20 % / 3x / 6 h, B = no stop / 2x / 12 h,
C = half at 2x then K, D = trailing 30 % / 6 h (shadow.py).

Money: Pick-type rows 50 EUR with the paper fees (1 %, at least 0.10, per trade; a half sale pays its own fee); Radar-type rows
20 EUR with the Radar's fees (memebot.tip_net: 0.5 %, at least 0.81). Results per trade are not clipped.

## Part 1: the current rules, month by month (information, no verdict)

1a Pick: the Pick's gates as far as candles hold them (age 6-24 h, market cap $100k-2M, liquidity and 24 h volume at least
$15k, no crash (-10 % in 1 h, -50 % in 6 h, -70 % in 24 h), no spike (+200 % in 1 h, +90 % in 6 h), 24 h volume at most 8x the
market cap); RugCheck gates and the bot's ranking are not in the data. A coin enters once, at its first whole hour through the
gates. Per window: coins, mean per 50 EUR under K, A, B, C, D, share in profit, share reaching 3x / 11x in 6 h, share stopped;
the hours with at least one coin through the gates (the Pick buys one coin per hourly scan); and the mean of one random gate
coin per clock hour (the bot's ranking was no better than random, research/RESULTS-2026-10-15.md). w3/w4 also with the hourly
rows' one-minute exit (check_history2.py part 1) to show what 5-minute candles change.

1b Radar: the live model (rocket_model.py walk-forward, trained on the last 300 trades as since PR #41, seeds 1/2/3/5/7, sell
rule K at 20 EUR) needs trades and wallets, which only history2 has: its buys split by calendar month (24 Aug-8 Oct), at the top
0.25 / 0.5 / 1 / 2 / 5 % cuts. 9-21 Oct: the replay already made with the model of 22 Oct morning (rocket_tests.json "replay";
re-scoring with today's model needs Helius credits that are used up), shown as it is.

## Part 2: every rule we can build, walk-forward over the windows

Three families, each a grid of entry filter x sell rule:
- P (Pick-type): the Pick's gates as the base, entries at whole hours 6-24 h, one entry per coin (its first hour through), 50 EUR.
- U (wide): base liquidity and 24 h volume at least $15k and market cap at least $50k, whole hours 1-24 h, one entry per coin, 50 EUR.
- R (Radar-type, chart only): the Radar's universe (liquidity and 24 h volume >= $15k, market cap $100k-5M, 1 h change > -10 %,
  6 h change > -50 %), entries every 30 minutes from 30 min to 12 h, 20 EUR. Its filters as P/U, plus a LightGBM rocket
  classifier (the 17 numbers, target: 10x within 6 h, the rocket_model.py settings, seed 7) trained on the fit windows only,
  at the top 0.25 / 0.5 / 1 / 2 / 5 % of its fit scores, one entry per coin. So the picker below sees honest numbers on the
  fit windows, each fit window is scored by a model trained on the other fit windows (none at step 2, where the classifier
  sits out); the unseen window is scored by a model trained on all fit windows, cut at that model's fit scores.

Filters: the base alone; one condition "number <= its fit 20th / 33rd percentile" or ">= its fit 67th / 80th percentile" (68);
every pair of conditions on two different numbers (2,176). So 2,245 filters x 222 sell rules = 498,390 rules per family, about
1.5 million in all, plus the classifier's 5 cuts x 222. Percentiles come from the fit windows of each step.

Walk-forward, rolling: step s (s = 2 to 5) fits on windows w1 .. w(s-1) and tests on ws. At each step and per family, two
pickers choose one rule among those with at least 30 coins in every fit window:
- MEAN: the best mean per trade over the fit windows' coins,
- WORST: the best worst-window mean (a rule that did well in every month it was picked on).
Each step's pick is shown on its unseen window. Step 5 (fit on w1-w4, test w5, the newest month, which no rule search has used)
decides.

### It holds when (each of the 3 families x 2 pickers = 6 candidates of step 5 judged alone)

1. at least 40 coins on w5,
2. its mean on w5 is above 0 after the fees and after the review's real-cost allowance (1.5 points per round trip at 50 EUR,
   3 points at 20 EUR; research/PREREG-REVIEW-2026-11-04.md),
3. the one-sided bootstrap lower bound on w5 is above 0 at 1 % / 6 (Bonferroni over the 6 candidates; 20,000 re-draws of its
   coins, seed 7),
4. without its single best trade the w5 total is still above 0,
5. its mean is above 0 in at least 4 of the 5 windows (w5 included).

Information only, decides nothing: the picks of steps 2-4 on their unseen window; per family the 20 best fit rules of step 5 on
w5 with Holm at 5 %; the best rule chosen with hindsight on w5 itself (to show how big pure luck looks); the classifier cuts per
window.

## What follows

Something holds: it is a candidate, nothing more. It is frozen as it is and checked forward on the bot's own coins from 22 Oct
on (the 4 Nov review, research/PREREG-REVIEW-2026-11-04.md), and only with the user's OK is anything changed in a bot (a sell
rule change restarts the Pick account).

Nothing holds: the user is told plainly that across about five months and about 1.5 million rules nothing found on older months
held on the newest one. Searching the same months again would only find more luck; new evidence comes from new days (the
nightly filter search and the shadow rules keep testing on them), and the months-data workflow can be run again when new free
days are worth adding.
