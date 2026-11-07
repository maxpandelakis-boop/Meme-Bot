# Pre-registration: big, established meme coins on Binance spot as a new hunting ground (fake money only)

Written on 2026-10-26 between 09:00 and 09:30 UTC, before a single price of the coins below was downloaded or looked at.
Nothing below may change after the first look; anything added later is labelled "added later" with its time and reason.
Research only: the bot, its accounts, its results branch and its app are not touched. No new live or paper account is started
without the user's own yes.

## Why

Every study on the bot's hunting ground (fresh pump.fun coins) failed: the Pick loses about 4 to 5 EUR per 50 in every month
(research/MONTHS-2026-10-23.md, PR #42), 1.5M rules held nowhere, and the venue itself loses (RESULTS-2026-10-15). The user's
goal (2026-10-26 08:50 UTC) is a result good enough to copy-trade with real money. Big, established meme coins on a large
exchange are a different game: deep order books, 0.1% fees instead of ~1-1.2% per side, years of free hourly data, and signals a
human can copy once a day. This study asks one question:

**Can a simple rule that a person can copy by hand once a day, trading established meme coins on Binance spot (long only, no
leverage), make money after real costs on months it was not chosen on?**

## What Claude already knows (the bias this design has to beat)

Claude's training covers market history up to about June 2026, so it knows roughly how meme coins moved in 2021 to mid-2026.
Three guards against that hindsight: (1) only fixed, generic textbook rule families with a small grid written down here, (2)
rule choice by a mechanical walk-forward, never by hand, (3) a sealed holdout of 1 July to 25 October 2026, months Claude has
never seen, opened once, after the procedure is locked by a commit.

## Data

- Binance spot, USDT pairs, one-hour candles from data.binance.vision (monthly files, daily files for October 2026), from each
  pair's first month to 2026-10-25 23:00 UTC. That mirror keeps the files of delisted pairs, so coins that died stay in.
  BTCUSDT the same way (for the BTC filter).
- Fetched by research/bigmemes/fetch.py in GitHub Actions (data-api/data.binance.vision is blocked from the Claude session) and
  pushed as plain data to the branch "bigmemes". Timestamps in microseconds (files from 2025 on) are converted to milliseconds.

## The universe (fixed by rule before any price is seen)

A Binance spot pair XXXUSDT is in the universe when its coin is a meme coin by either of:
1. CoinGecko's category "meme-token" (snapshot taken by fetch.py): for pairs Binance lists now, matched by CoinGecko's own
   Binance ticker list (coin id, so no symbol mix-up); for pairs that no longer trade, matched by symbol (prefixes "1000",
   "1000000" and "1M" stripped, e.g. 1000SATS -> SATS, 1MBABYDOGE -> BABYDOGE);
2. the fixed hand list: DOGE SHIB PEPE FLOKI BONK WIF BOME MEME PEOPLE 1000SATS NEIRO TURBO PNUT ACT DOGS 1MBABYDOGE TRUMP
   PENGU MUBARAK BROCCOLI714 TST BANANAS31 1000CHEEMS 1000CAT PUMP.

The only allowed manual change: a symbol-matched pair (rule 1, delisted case) is dropped when its Binance coin is clearly a
different, non-meme project with the same ticker. The list with each decision is written to research/bigmemes/UNIVERSE.md
from names only, before the analysis reads a price.

**Eligible on day d** (point in time, no look-ahead): the pair has candles at least 30 days before d, and the median of its
last 30 UTC-day quote volumes (days d-30 to d-1) is at least 5 million USDT. A position is only held in an eligible coin; a coin
that turns ineligible is sold at the next fill. A pair whose data ends (delisted) is sold at its last close.

## Execution and costs (what a person can copy)

- Signals use daily closes at 00:00 UTC (data up to the end of day d-1). Orders fill at the open of the 08:00 UTC candle of
  day d (09:00/10:00 Berlin): the person reads the signal in the morning and copies it. All returns run from fill to fill.
- Cost per side: 0.10% Binance fee + 0.15% spread and slippage = 0.25%; a round trip costs 0.50%.
- Stress: 0.50% per side (1% round trip) AND the fill at the 14:00 UTC open instead.
- For information only: the fill at 00:00 UTC (no delay).
- Long only, spot, no leverage. Account of 1,000 EUR (results in %; EUR = USDT for this purpose, the exchange-rate move is ignored).
- Sizing: per-coin rules (F1, F2, F5, F6) buy equity / max(5, number of eligible coins) per new position (limited by cash);
  top-K rules (F3, F4) buy equity / K per new position. Positions are not rebalanced while held (they drift with price), so
  turnover is only real buys and sells. A day with no fill price at 08:00 uses the next candle of that day.

## The rules (fixed grid, 213 rules)

C = daily close, SMA_N = mean of the last N closes, "return over L days" = C[d-1] / C[d-1-L] - 1.

- F1 trend (5): hold a coin while C > SMA_N, N in {10, 20, 50, 100, 200}.
- F2 breakout (6): buy when C > highest close of the previous N days, sell when C < lowest close of the previous M days;
  (N, M) in {(10,5), (20,5), (20,10), (55,5), (55,10), (55,20)}.
- F3 momentum rotation (12): every Monday hold the K eligible coins with the highest return over L days; L in {7, 14, 30, 60},
  K in {1, 3, 5}. A coin that stays in the top K is kept (no cost).
- F4 short-term reversal (18): every H days hold the K eligible coins with the lowest return over L days; L in {1, 3, 7},
  H in {1, 3, 7}, K in {1, 3}.
- F5 volume spike (12): buy when a day's quote volume is at least X times the median of the 30 days before it and the day
  closed at least R up; sell H days later; X in {3, 5}, R in {+10%, +20%}, H in {1, 3, 7}.
- F6 dip in an uptrend (18): buy when C > SMA_100 and C is at least D below the highest close of the last 20 days; sell H days
  later, or at the next fill after a close at least S below the buy price; D in {15%, 25%, 35%}, H in {3, 7, 14},
  S in {none, 20%}.
- Every rule in three versions: G0 no filter, G1 only while BTC's close is above its SMA_50, G2 only while an equal-weight index
  of the eligible coins is above its SMA_20. Filter off = sell everything, buy nothing.

71 rules x 3 filters = 213. A rule needs the full indicator history of a coin (N closes) before it can trade that coin.

Benchmarks (never candidates): B1 equal weight of all eligible coins, rebalanced on the first fill of each month; B2 BTC
buy and hold; B3 DOGE buy and hold; B4 cash.

## Test 1, main: walk-forward (WF)

Test months: January 2022 to June 2026 (54 months). At the first fill of each test month, every rule is scored on the 24
months before it (at least 180 days of the rule's own account history and at least 20 closed trades in that window): score =
mean / standard deviation of its daily net account returns. The best score is traded for that month; no rule qualifies -> cash.
WF's month = the chosen rule's account return in that month, minus the cost of switching from last month's holdings to this
rule's holdings (0.25% per side of the turnover). WF's trades = the chosen rule's trades opened in that month, followed to
their exit under that rule.

## Test 2: fixed textbook defaults (FD), no choice at all

F1 SMA_50 G0, F2 20/10 G0, F3 L30 K3 G0, F4 L3 H3 K3 G0, F5 X5 R+20% H3 G0, F6 D25% H7 no stop G0, each over the same 54
test months (they start trading as soon as their history allows).

## When something HOLDS (all of these, base costs, test months only)

1. At least 40 closed trades.
2. Mean net return per trade > 0.
3. 1% one-sided bootstrap lower bound > 0 for BOTH (a) the mean per trade (10,000 draws of trades) and (b) the mean monthly
   account return (10,000 draws of whole months; trades in the same weeks move together, so (b) is the honest one). Seed 7.
   Holm correction over the 7 candidates (WF + 6 FD) at 1% family-wise.
4. Still > 0 without the best trade, and the monthly mean still > 0 without the best month.
5. Monthly mean > 0 in at least 2 of the 3 thirds: Jan 2022-Jun 2023, Jul 2023-Dec 2024, Jan 2025-Jun 2026.
6. Mean per trade and monthly mean > 0 under the stress costs and the 14:00 fill.
7. The sealed holdout (1 July to 25 October 2026), opened once after 1-6 are committed: the locked procedure's account return
   over the holdout > 0 after base costs. Too few months for significance, so this is a sign check that can only veto.

Reported for every candidate, deciding nothing: total return, worst month, maximum drawdown, trades per week, average holding
days, coins held at once, the benchmarks, the hindsight-best rule over all test months (the size of luck), and a random-rule
baseline (each month a random qualifying rule, 1,000 seeds).

## What follows

- Something holds: it is a candidate, not money. Next step only with the user's yes: a paper shadow in the app from November,
  judged on at least 4 forward weeks with the PR #39 bar. Real money is the user's own decision and not advised on a backtest.
- Nothing holds: the user is told plainly, with the numbers, that established meme coins on Binance with simple daily rules
  did not beat costs on unseen months either, and nothing is built.
