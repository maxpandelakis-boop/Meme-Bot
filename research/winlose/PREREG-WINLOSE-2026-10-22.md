# Pre-registration: winners against losers (22 Oct 2026, fake money only)

Written after the numbers were built (research/winlose/features.py) and before any of them was compared with an outcome.

## Data
history2 rows of 1 to 24 hours after the graduation that a bot with the kept gates sees (liquidity and 24 h volume at least
$15k, market cap $100k to $5M, crash gate, no recorder gap before the row, a known 6 h path): 24,710 rows of 4,738 coins.
**Development**: graduations before 25 Sep 2026. **Holdout**: graduations from 25 Sep to 8 Oct (1,113 coins), looked at ONCE,
after everything below is fixed. Outcome per 20 after fees (memebot.tip_net, 0.5%/at least 0.81 per trade) with the current
sell rule A (-30% stop, 11x target, 6 h). The sell rule is not changed by this study.
- **winner**: reached 3x within 6 h. **loser**: fell to 20% or less within 6 h without reaching 3x first.

## Numbers (84 + 3 look-alike numbers)
chart (one-minute bars: returns 5 min to 4 h, path since graduation, distance to the high, RSI 1/5/15 min, volume spikes,
buy/sell pressure, trade counts and sizes, bot share, volatility, biggest one-minute moves, Bollinger position, trend slope
and fit, last candles' bodies and wicks, engulfing, support/resistance touches and distance, first hour), flow (screener
numbers and their change since the hour before), wallets (buyers before the entry, size, top share, fresh/experienced/smart
wallets by their EARLIER coins' known results), market (BTC and SOL 1 h/24 h, graduations in 24 h, how coins of 2-3 days ago
did). Look-alikes: the 50 most similar charts (last 2 h, 5-minute path and volume) among coins that graduated 2 or more days
earlier: their winner share, loser share and average result.

## Part A: where winners and losers differ (display only unless part B passes)
Like with like: strata of age (1, 2, 3-5, 6-11, 12-24 h) x market-cap fifth. Per number, the stratified AUC of winners against
losers (0.5 = no difference) on dev-early (before 5 Sep), dev-late (5 to 24 Sep) and the holdout. A number "holds" when its
direction is the same in all three and its holdout p-value survives Holm over all numbers. Also reported: the same for
winners against everything else, and for "big move either way" (winner or loser) against the rest, because danger signals
have been 3x signals before.

## Part B: a score (the only thing that may change a pick)
LightGBM, trained walk-forward on dev (weekly folds from 24 Aug; a fold trains only on coins that graduated at least two days
before it starts). Two scores: (1) the predicted result per 20, (2) P(winner) minus P(loser). Each with a cut at the top 2%,
5%, 10% or 20% of rows (cut points from the training part of each fold): 8 candidates. One entry per coin, the first hour that
passes. THE choice: the candidate with the best dev walk-forward average per 20 among those with 150 coins or more.
**Pass** (holdout, once, final model trained on all dev): 100 coins or more, average per 20 above 0 with the bootstrap 95%
lower bound (by coin) above 0, better than the bot's gates on the holdout, and a 3x share not below the gates'. Holm over the
8 candidates' holdout p-values is reported. Also reported: how many of 10 picks end in profit (the user's goal: 6 of 10).
A pass is built into the pick selection as a score; a fail changes nothing, the top differences go to the app as display only.

## Addendum, 22 Oct 07:25 UTC: all signals together on the bot's own scans (written before this part was run)
The user asked for all tests together. The dev/holder, RugCheck, social, smart-wallet and pump.fun numbers exist only in the
bot's own big test (every coin of every scan from 7 Oct; outcome: held to the 2h check, 1% fee per side, as filter_search.py).
Script: research/winlose/combined_bt.py. All 91 numbers the scan stores, in one LightGBM model (it finds the combinations
itself), and a two-stage score: P(big move: x2 or more, or to 20% or less) times P(up | big move). Walk-forward by scan day
(train on all days before, from 11 Oct); 2 scores x cuts at the top 2/5/10/20% = 8 candidates; THE choice = best dev
average with 100 coins or more. Dev: scans before 18 Oct. Holdout: scans from 18 Oct (earlier used for the 21 Oct rule
search, never for this model), once. Pass and consequence as in part B (above 0 with lower bound above 0, better than the
gates, 3x share not below).
Result of the addendum (run 22 Oct ~07:35 UTC): dev walk-forward choice "predicted result, top 2%" +0.33 per 20 (1,696 coins,
lower bound -0.22); holdout -0.00 per 20 (417 coins, range -0.57 to +0.62; gates -1.38), 3x 0.24%. **FAILS** (not above 0).

## Addendum 2, 22 Oct 07:40 UTC: rocket hunter and "few losers", side by side (written before this part was run)
The user wants (B) the daily exploders found before take-off and (A) hardly any pick in the red. history2 coins, now every
15 minutes from 30 minutes to 18 hours after the graduation (one-minute bars), so a take-off can be caught 5 to 60 minutes
early; the same universe filters, computed from the bars (liquidity, market cap $100k-5M, 24 h volume, crash gate). Numbers:
the chart, wallet and market numbers of features.py at that minute. Outcome: sell rule A from that minute, per 20 after fees,
**not clipped** (what the paper account would really book; 11x is the most rule A can make). Dev/holdout split as before.
- **A, few losers**: P(result > 0). Choice on dev: the cut (top 0.5/1/2/5%) with the most picks in profit among those with
  100 coins or more. Passes on the holdout with 6 or more of 10 in profit AND an average above 0.
- **B, rockets**: P(price reaches 10x within 6 h). Choice on dev: the cut with the best average among those with 100 coins or
  more. Passes on the holdout with an average above 0 and the bootstrap lower bound above 0.
- **C, expected profit**: predicted result (regression). Same choice and pass as B.
Walk-forward weekly on dev as part B; Holm over the 12 holdout p-values reported. A pass is built into the radar's pick
selection only as described before; a fail changes nothing and goes to the app as display.

## Addendum 3, 22 Oct 08:05 UTC: a rocket score the launch radar can compute live (written before it was run)
The user wants the radar to be the rocket hunter. The radar sees a coin about 1 minute after its pool opens and prices it again
5, 15, 30 and 60 minutes after first sight from DexScreener, so the score may only use what a DexScreener pair gives then: age,
market cap, liquidity/market cap, volume 5 min and 1 h over market cap, price change 5 min and 1 h, buys and sells 5 min and 1 h,
buy share, and the price against the first-sight price (minute 1). Rows: every history2 coin with liquidity >= $5k (the radar's
YOUNG_MIN_LIQ) at 5, 15, 30 and 60 minutes after its pool opened (minute bars; no outage within). Target: 10x within 6 h of that
minute; result: sell rule A from that minute, not clipped. Walk-forward weekly on dev, cuts at the top 0.5/1/2/5% of rows; THE
choice: best dev average with 100 coins or more. Holdout (from 25 Sep) once. Pass: average above 0 with the lower bound above 0.
Whatever the result, the score goes into the radar as a displayed and logged number only (no paper buy and no push changes);
the logged live numbers are the forward test.
