# Radar account: still no buy (25 Oct 2026, fake money only)

**Question.** After the fix of 23 Oct (LIVE-CHECK-2026-10-23.md, model retrained on the last 300 trades, cut 0.0739) the Radar account
(rocket hunter) bought nothing again. Broken, or strict?

## What runs
- rocket.yml: every quarter-hour since 23 Oct 19:34 UTC, 150 rounds to 25 Oct 08:17 UTC, no gap over 25 minutes. The "cancelled"
  runs are the queued duplicates the concurrency group drops; every run that ran ended green.
- 1,720 scores of 235 coins (4 to 22 a round). Best: YouTube 0.0537 (73 % of the cut, 25 Oct 01:38 UTC), gary 0.0520, GTA 0.0380.
- The app's Radar tab shows the account, the last round and its candidates correctly (screenshot app-design/9-radar-tab-25oct.png).

## Test vs live
The training grid rebuilt from the branches (early_grid.py LIVEHL=1 LIVETR=300): 69,647 rows, 5,829 coins, 349 rows at or over the
cut, exactly the model's. Walk-forward out-of-sample scores (rocket_model.py weeks, seed 7) as a share of each week's cut:

| coins whose best check reaches | ≥ 25 % of the cut | ≥ 50 % | ≥ 100 % (a buy) |
|---|---|---|---|
| test, 3,752 coins (24 Aug to 8 Oct) | 11.9 % | 5.4 % | 1.9 % |
| test, weakest week (24-30 Aug) | 2.8 % | 1.4 % | 0.5 % |
| live, 235 coins (23-25 Oct) | 7.2 % | 1.7 % | 0 % |

Medians and the 90th percentile match; the top tail is missing live (99th percentile at 30-45 minutes: test 1.19, live 0.47 of the cut).
At the test's rate 0 buys in 235 coins has a chance of about 1 to 2 %; at the weakest week's, about 30 %.

## Why the tail is thinner
1. **Many more tiny trades live.** GeckoTerminal's last 300 trades reach back much less far than the training data's 300 did (median
   reach at 120-240 min: test 16, live 6 minutes; at 240-480 min: 60 vs 13). The radar probe (radar_probe.py, branch radarprobe) shows
   why: on several coins 280-290 of the last 300 trades are under $5 (bot volume), so the trade numbers cover one or two minutes.
   Emulated on the grid (the same coins with only the last 100 trades, about 3x the trade density): coins reaching the cut fall from
   1.92 % to 1.23 %, coins reaching half of it from 5.4 % to 3.5 %. That explains about a third of the gap.
2. **A quiet market.** The scores that reach the cut lean on wild charts (vola_60, max_jump_1m_60, first hour) and on BTC/SOL's last
   24 h; both are average now. The test's weeks ranged from 0.5 % to 4.4 % of coins bought; live is at or below the weakest week.
3. Smaller: the wallet memory ends 8 Oct, so fewer of today's buyers are known (r_known_share at the 15th percentile in the probe).

## Verdict
No fault in the code: the arithmetic is the tested one (selftest_rocket), the rounds run, the app shows them. The model is strict and,
in today's market and with today's bot trades, stricter than in its test. Nothing changed. A lower line is the user's call: on the
live scores since 23 Oct, the top 1 % line (0.0360) would have bought 4 coins (about 2.6 a day: DONNA, GTA, gary, YouTube), top 2 %
(0.0203) 16 coins (about 10 a day). In the look back both lose money (top 1 %: -7.36 per 20 €, top 2 %: -5.95).
