# Pre-registration: rule search on the bots' own live data (4 Nov 2026)

Written 4 Nov 2026 ~16:50 UTC, pushed before any rule below was scored. The user, 4 Nov 2026 16:14 UTC (thread "Neue Regeln aus den
Live-Daten suchen"): "kannst du nicht sachen anpassen und neue regeln suchen aufgrund der neuen daten und auch löschen was nicht
relevant ist du kannst so viel probiern ich will plus sehen".

## What stays untouched

The Pick account (its buys and the Sell bot), the Radar account 🚀 and the Rocket seeker 🔭 keep their rules: the user chose "keep
running" for the 22 Nov full-month review (4 Nov 16:09 UTC), and the seeker is judged once on 27 Nov by its own pre-registration.
Every rule found here runs NEXT to them as a paper test account. Nothing here touches real money.

## What is already known (do not re-run)

- 1.39 billion filter x sell-rule pairs on pump.fun history (PR #68): 0 of 20 frozen candidates held on sealed days.
- 1.5 million rules walk-forward (PR #42), 213k rules, ML exit (PR #48), chart exit search (PR #46): all failed out of sample.
- The nightly filter search (filter_search.py) has mined the big test every night since 21 Oct: 10 rules frozen 21-30 Oct, all
  negative on the days after their freeze (-1.12 to -2.87 per 20, 0-8 % winners).

So the prior is: a rule that looks good on 13 days of data is most likely luck. This search is honest only if its candidates are
frozen now and judged on days nobody has seen yet.

## Data (the bots' own live records, 22 Oct 10:08 UTC to 4 Nov 2026)

- bt: the big test, every coin of every hourly scan snapshot (branch bigtest, export of 4 Nov 06:12 UTC: scans up to 4 Nov ~03 UTC),
  liquidity >= $5k, market cap >= $10k, no hard block, with the scan's factors and the price about 2 h later.
- pick: the Pick account's buys with buy-time factors, the booked result and the 12-hour minute path of the shadow job.
- lern: the Learning Pick's buys with its 6-hour minute path (closes).

Split by buy/scan time: FIT = before 31 Oct 2026 00:00 UTC (1793404800000); CHECK = from then to the end of the data.

## Families

- F1 sell rules on the Pick's buys (shadow.replay, the Pick's paper fees, 50 EUR): stop {none, 10, 15, 20, 25, 30, 40, 50 %} or a
  trailing stop from the start {10, 15, 20, 30 %}, target {1.3, 1.5, 2, 2.5, 3, 5, 11x, none}, hours {1, 2, 3, 4, 6, 8, 12}, half at
  {none, 1.5x, 2x}; plus chart-exit variants (arm {1.2, 1.3, 1.5, 2x} x trail {10, 15, 20, 25 %} x drop {none, 10, 15, 20, 30 %} x
  drop window {15, 30, 60 min} x floor {-30, -50 %} x hours {3, 6, 12}). Every rule sells the same buys. Cross-check (report only):
  the same rules (hours <= 6) on the Learning Pick's paths.
- F2 skip filters on the Pick's buys: keep only buys whose buy-time factor is <= or >= the FIT buys' 33 %, 50 % or 67 % point (one
  factor, or two), keeping >= 40 % of the FIT buys; result per buy = the Sell bot (rule X) replayed on its path.
- F3 buy filters on the big test: an age window or universe (filter_search.WINDOWS, plus the Learning Pick's universe) and one or
  two of filter_search.FEATURES above or below a FIT quartile; one entry per coin and day (the first scan it passes); result = the
  2-hour price, 1 % fee per side, capped at 11x, per 50 EUR; >= 60 FIT entries. Plus F3r: per scan the gate passer ranked first by
  one factor (up or down).

## Selection and freeze (per family)

Rank by the FIT mean per trade after costs. A candidate is a rule among the 50 best on FIT whose CHECK mean is above zero and above
the family's yardstick on CHECK (F1: rule X and rule K; F2: all Pick buys under X; F3: the gate passers). At most 3 per family,
best FIT rank first; if none qualifies, the family yields NOTHING and the report says so. The luck test is reported with it: how
the 50 best FIT rules did on CHECK against all rules (share above zero, rank correlation).

The candidates are written to research/livesearch/CANDIDATES-2026-11-04.json and committed BEFORE they go live.

## Forward test and judgement

Live as paper test accounts from 5 Nov 2026 00:00 UTC (1793836800000): F1 and F2 on the Pick's real buys (12-hour paths of the
shadow job), F3 as frozen challengers of the nightly filter search. Judged ONCE on 22 Nov 2026 with buys from 5 Nov 00:00 UTC to
21 Nov 12:00 UTC (1795262400000), by the PR #39 bar: >= 40 trades, mean > 0 after the allowance (1.5 points per 50 EUR), 1 % of
10,000 bootstrap means > 0, total > 0 without the best trade. F1/F2 also have to beat the real Pick account on the same buys
(paired). With up to 9 candidates, about one in ten would pass by luck alone if none were real: a pass is a reason to keep testing,
not to use real money.

## Clean-up ("löschen was nicht relevant ist")

- Learning Pick: no new buys from this change on (proven negative on 4 Nov: 275 trades, -897.62 EUR, all 10,000 re-draws <= 0); its
  open positions are still sold by its rule; its data stays on the results branch; the nightly training step goes.
- Shadow rule D (trailing 30 %, -317.80 EUR against K on 4 Nov): off the page; its paths stay.
