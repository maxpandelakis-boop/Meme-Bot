# Pre-registration: the big filter search of 21 Oct 2026 (fake money only)

Written before any result of this search was looked at. Script: research/filtersearch.py.

## Data
1. history2 (62,600 graduated pump.fun coins, 10 Aug to 8 Oct 2026): rows at whole hours 1 to 48 after the graduation, liquidity
   at least $5k, no recorder gap. Split by graduation: **train** before 1 Sep, **check** 1 to 20 Sep, **holdout** from 21 Sep.
   The holdout is not used for any choice.
2. The bot's own big test (every coin of every hourly scan, 7 to 21 Oct 2026, liquidity at least $5k): a second, independent
   holdout for rules that can be written in its numbers, plus its own search over the factors only it has (RugCheck, creator,
   holders, social, smart wallets). Split by scan day: train 7 to 14 Oct, check 15 to 17 Oct, holdout from 18 Oct.

## Outcomes, per 20 EUR, 1% fee per buy and per sell (2% round trip; 3% as a check)
hold 1.7 h (price capped at 11x), exit A (the paper rule: -30% stop, 11x target, 6 h), exit B (-20% stop, 3x target, 6 h).
One entry per coin: the first hour the rule lets it through. 3x hit = the price reached 3x within 6 hours.

## Rules
15 numbers (market cap, liquidity, liquidity/mc, volume/mc, last hour's volume share, change 5 min/1 h/6 h/24 h, buy share,
buyers, biggest buyer's share, bot share, minutes since the last trade, last hour's volume), each at the 20/40/60/80% points of the
train part, "at most" or "at least": 120 conditions, alone or in pairs of different numbers (6,840 rules), times 6 age windows
(1 h = the "new launches", 2-3 h, 4-6 h, 6-24 h = the bot's window, 24-48 h, any), times 3 exits: 123,120 combinations.

## Choice (train + check only)
A candidate needs 200 coins or more on train and 100 or more on check. Score = the lower of its train and check average.
The best score is THE choice. Multiple testing: each candidate's check average gets a one-sided p-value (mean > 0); Holm over all
candidates; the count that survives is reported.

## Pass (holdout, once)
The choice passes only if on the holdout: 100 coins or more, average > 0 with the bootstrap 95% lower bound > 0, better than the
bot's gates (6-24 h, $100k-2M, crash and spike gates) with the same exit, and a 3x share not below the gates'. Otherwise it fails
and nothing changes in the bot. Even a pass changes nothing by itself: it goes to the nightly forward test and to the user.
