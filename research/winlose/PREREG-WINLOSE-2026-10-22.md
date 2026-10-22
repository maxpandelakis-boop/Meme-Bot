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
