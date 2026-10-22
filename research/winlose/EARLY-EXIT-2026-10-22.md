# The rocket hunter: earlier entry, other exits, a model exit (result, 22 Oct 2026, fake money only)

Pre-registration: research/winlose/PREREG-EARLY-EXIT-2026-10-22.md (commit 32f788b, addenda 1-3 in later commits, each before the
numbers it names were read). Data: history2 (Slink21 Pumpfun dataset, CC BY 4.0), graduations 10 Aug-8 Oct 2026, one-minute bars
(chartbars, chartbars55), wallet pairs (wallets), BTC/SOL (marketctx). Scripts in this folder: early_grid.py, wick_check.py,
early_entry.py, rocket_exits.py, exit_states.py, exit_model.py, rocket_tests_export.py.

## First: a data error, and what it did to the rocket hunter's history
features.dense forward-filled each minute's high and low into the following minutes without a trade. On a dead pool the last
wick then "happened" again in every quiet minute: one coin's last trade minute had a high 238x its close and no trade followed,
and the grid booked 11x on every entry after it; another showed a 299x high while it really rugged to 0.005x. The live code never
did this (rocket.dense and Book.update use the close for a minute without a trade). wick_check.py: 55 grid rows of 3 coins lose
their 10x label, rule A's result changes on 182 rows. The chart numbers carried the same fill (last candles' wicks, support and
resistance, the 4 h low), so the trees had also learned numbers the live watcher never computes.

Corrected (features.dense fill_hl=False, the same as live; early_grid.py LIVEHL=1): the rocket hunter as it runs live (first
check at 30 minutes, then every 15), walk-forward over 7 weeks, mean of 5 seeds:

| tier | coins | per 20 (seeds) | in profit of 10 | 10x | 10,000 runs in profit |
|---|---|---|---|---|---|
| top 0.5% (live) | 71 | **-3.25** (-3.9, -2.6, -1.7, -2.5, -5.6) | 1.2 | 2.2% | 22.6% |
| top 1% | 226 | -2.30 | 1.1 | 3.6% | 25.2% |
| top 2% | 478 | -2.97 | 1.2 | 3.2% | 10.4% |

Before the fix the same run said +5.56 at the top 0.5% (56 coins, 10x 6.5%, 81% of the runs in profit); the stress test of
21-22 Oct said +3 to +10. That edge came mostly from the fake 11x of the dead pools. **The rocket hunter has no edge in the
corrected history.** Its live paper account goes on as the forward test; rocket_model.json is exported again from the corrected
grid (same 60 numbers, seed 7, top 0.5%; cut 0.0699, was 0.0838), so the live model learns what the live code computes.

## Test 1: an earlier first check (corrected run decides)
| variant | coins | per 20 | early weeks | late weeks | runs in profit | 10x | holds |
|---|---|---|---|---|---|---|---|
| V30 (today) | 71 | -3.25 | -0.85 | -8.63 | 22.6% | 2.2% | |
| V20 | 79 | -3.15 | -1.22 | -8.32 | 25.9% | 3.6% | no (b, c, e) |
| V15 | 74 | -2.25 | +1.68 | -9.56 | 34.3% | 6.0% | no (c, e) |
| V10 | 53 | -7.82 | -8.27 | -6.74 | 8.2% | 3.6% | no |
| V5 | 86 | -1.04 | +1.40 | -4.20 | 42.4% | 5.5% | no (e: below 0) |

No variant holds: none is above 0. The first check stays at 30 minutes. (The first run, on the faulty grid, had passed V15 at
+8.88 against +5.56; on the corrected grid both are below 0.)

## Test 2: 134 fixed exits for the rocket buys (V30 picks, seed 7)
No rule beat rule A (-30% stop, 11x, 6 h) in the early weeks at all three tiers, so there is no choice and rule A stays. Even in
hindsight over all weeks no rule is positive at the top 0.5% (best: stop -50%, sell at 3x, 12 h: -1.11 per 20, 72 coins; rule A
-3.89). Partial sells and trailing stops lose the few real 10x moves and do not save the many losers.

## Test 3: a model that decides "stay in or get out" every 15 minutes (one pre-registered candidate)
States: 155,929 (6,406 coins, 15 min to 42 h after the graduation); label P(2x before 0.5x), 37% of the states; stay while it is
1/3 or more; the -30% stop stays; 24 h at most.

| tier | KI exit per 20 | rule A per 20 | runs in profit KI / A | coins |
|---|---|---|---|---|
| top 0.5% | -5.67 | -3.89 | 0.2% / 12.9% | 72 |
| top 1% | -0.03 | -3.71 | 50.1% / 7.6% | 226 |
| top 2% | -2.98 | -5.03 | 18.5% / 0.1% | 478 |

Late weeks top 2%, per coin KI minus rule A: +0.67 (95% range -4.56 to +6.47). Checks: (a) yes, (b) no, (c) no: **does not
hold**. The one real 10x coin of the top 0.5% (ZV3vQ9…) shows the problem the user asked about: rule A sold it at 11x; the model
stayed in (13.3x at its check 15 minutes after the buy), the coin peaked at 16x 25 minutes after the buy and then fell to 0.01x
within two minutes (a rug), where the -30% stop filled. The model is better than rule A on the
looser tiers but not where the live account buys and not with a clear margin anywhere; nothing is switched, and the Pick account
gets no "would hold / would sell" display (a model that does not hold would mislead).

## What changes
- rocket_model.json: exported again from the corrected grid (bug fix, not a variant choice).
- page_rocket.py: the honest line says the corrected history is negative; a fold "Geprüft am 22. Okt" shows the four results
  (rocket_tests.json).
- features.dense(fill_hl=False) for every new grid; selftest_rocket R1b checks the live and research arrays on charts with minutes
  without a trade.
- Not changed: the first check (30 min), rule A for the rocket account, the Pick account and its sell rule.
