# Rocket hunter: live vs test (23 Oct 2026, fake money only)

**Question.** The Radar account (rocket hunter, top 0.5 % cut, rule A) bought nothing in its first 104 rounds with the model of
22 Oct (22 Oct 13:43 UTC to 23 Oct 17:22 UTC): 1,185 scored checks of 195 coins, best score 0.0366 (McNugget), 52 % of the cut 0.0699.
Is that a strict rule or does the live account score coins differently from the test?

## What is the same
- The arithmetic: `selftest_rocket` R1/R1b (rocket.py chart numbers = features.py chart_feats on the same bars, 0 of 17,103 values
  differ) and R2 (the JSON trees = LightGBM's probabilities, largest gap 4e-16) pass.
- The rebuilt training grid (early_grid.py LIVEHL=1, rows from 30 min) is the model's grid: 69,647 rows, 5,829 coins, 349 rows (0.501 %)
  at or over the cut.

## What differs: the trades the model sees
The live account gets each pool's trades from GeckoTerminal, which gives the **last 300 trades** only. The training grid counted
**every** trade of the hour (history2 bars: buys and sells per minute; wallets: every first buy of the last hour). Busy young coins
trade 40 to 500 times a minute, so live the 300 trades reach back:

| | median reach | coins 30-60 min old |
|---|---|---|
| live log (`reach`, 1,185 checks) | 14 min | 1 min |
| the grid with only the last 300 trades (`features.live_view`) | 52 min | 1 min |

So trades_60, active_min_60, buy_imb_*, buys_trend_30, avg_trade_sol_60 and the r_* wallet numbers (r_sol is the model's second
strongest number) were trained on a full hour and fed a minute or two live. Scores drop most where the buys were (30-60 min old:
p99 0.041 with every trade, 0.013 with the last 300).

## Walk-forward (rocket_model.py weeks, seeds 1/2/3/5/7; research/winlose/live_check.py)

| top 0.5 % | buys (of 4,595 test coins) | per 20 € | 10x | buys expected in the 1,185 live checks | P(0 buys) |
|---|---|---|---|---|---|
| A trained and tested with every trade (the test of 22 Oct) | 74 (1.6 %) | -2.22 | 2.4 % | 2.7 | 7 % |
| B trained with every trade, fed the last 300 (live until 23 Oct) | 26 (0.6 %) | -5.33 | 0 % | 0.8 | 45 % |
| C trained and fed the last 300 (live since 23 Oct) | 76 (1.7 %) | -6.27 | 1.1 % | 2.7 | 7 % |

(A here is the same test as the 22 Oct fold, 71 buys / -3.25; the gap is seed and row-order noise.)

**Verdict.** Not broken in the code, but the live account was not running the tested strategy: with live inputs the model of 22 Oct
buys about 60 % fewer coins, and 0 buys in 104 rounds is ordinary for it (45 %). Retrained on the last 300 trades only (C), it buys
as often as the test again, but its honest look back is worse than the one shown since 22 Oct: -6.27 per 20 € instead of -3.25,
10x in 1.1 % of buys, 3 of 100 simulations in profit. The earlier number leaned on trades the live account never sees.

## Changed
- `features.live_view` (the last 300 trades as rocket.dense), `wallet_recent` with a `reach` column, `early_grid.py LIVETR=300`.
- `rocket_model.json` re-exported from that grid (cut 0.0739, top 0.5 % as before; sell rule A unchanged). The Radar account has no
  trades yet, so nothing restarts.
- `rocket_tests.json` "history" (the Radar tab's fold) shows C's look back.

Left as is (small): live `rocket.wallets` counts any buyer of 0.1 SOL or more in the trades, the grid only first buys; the live
wallet memory is the whole Aug-Oct record, the grid's is as of each row.
