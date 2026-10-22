# Pre-registration: the video's "10,000 replays" as a radar forecast (fake money only)

Written on 2026-10-22 before any replay forecast was computed. Nothing below may change after the first look; anything added later is
labelled as added later.

## Why this is a new test

The user sent the "day-trader-skill" video again (11 skills; the "Time-Machine-Skill" plays a trade 10,000 times as random price
paths and shows the spread of the possible end prices with stop, entry and target). On 2026-10-21 the random paths were NOT tested:
research/PREREG-TIMEMACHINE-2026-10-21.md replaced them with look-alike coins ("a random walk misses the rugs"), and that look-alike
idea later became forecast.py. So the video's own method, replaying the coin's own past moves, has never been checked. This does it.

## The forecast (fixed now)

- The coin's own past hourly moves: log(p_h / p_(h-1)) for its last up to 24 whole hours before and at the scan.
  - history2: consecutive hourly rows of the same coin (h and h-1 both present, price > 0); the row h=1 adds its 1-hour change.
  - the bot's scans (branch "bigtest", memesnapres, rule m9-2h): market cap at the coin's earlier scans; one step per pair of
    neighbouring scans 30 to 120 minutes apart, used as one hour.
- At least 5 moves, otherwise no forecast (the coin is left out of every comparison and counted as "too young").
- 10,000 replays per coin (numpy, seed 7): the 1.7-hour multiple is exp(r_a + 0.7 r_b) with r_a, r_b drawn with replacement from
  the coin's own moves. Profit chance = share of replays with memebot.tip_net(multiple) > 0 (same fees as the tip record: 0.5%,
  at least 0.81 per trade); zero chance = share under 0.02.

## Tests

1. Forecast quality, history2: the exact rows of forecast_build.py's backtest (first row through the bot's 2h gates of every coin
   graduated from 15 September, no recorder gap). Brier of the replay profit chance against (a) the base rate of the pre-15-September
   reference and (b) the look-alike forecast (forecast_build.py's reference built before 15 September), on the rows where the replay
   forecast exists. Same for the bot's gate passers in the big test (first scan per coin, 1.7-hour result), look-alike = full
   reference as in forecast_build.py.
2. Picker, history2: the threshold T in {0.20, 0.25, ..., 0.80} is chosen on coins graduated BEFORE 15 September (first gate row per
   coin with replay profit chance >= T; best average per 20 held 1.7 h with at least 100 coins). Then on coins from 15 September:
   coins, share in profit, average per 20 and its 95% bootstrap interval, 3x share.
3. Picker, the bot's own scans: the same T on the big-test gate passers (first scan per coin where the chance >= T).

## Decision

- **BUILD IN as a radar filter** only if test 2 AND test 3 each have at least 30 coins, at least 60% of them in profit (the user's
  target "6 of 10") and an average per 20 above 0, with test 2's 95% interval above 0.
- Otherwise, **SHOW ONLY** the replay chance next to the look-alike forecast if its Brier beats the look-alike forecast in test 1 on
  both data sets.
- Otherwise **nothing is built**; the result is written to research/REPLAYS-2026-10-22.md.
- The sell rule is not touched in any case.
