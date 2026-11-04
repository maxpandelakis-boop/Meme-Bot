# Live-data rule search, 4 Nov 2026: result

Pre-registration: PREREG-LIVESEARCH-2026-11-04.md (commit 6f4b9b5, authored 4 Nov 16:23 UTC, before any rule was scored). Candidates frozen in
CANDIDATES-2026-11-04.json (commit 13e39bf, authored 4 Nov 16:30 UTC, before going live). Scripts: ls_build.py, ls_sell.py (F1), ls_skip.py (F2), ls_buy.py
(F3), ls_freeze.py. Live from 5 Nov 2026 00:00 UTC as the "New rules test 🧪" (newrules.py, page_newrules.py); judged once on
22 Nov 2026 (newrules.judge, PR #39 bar).

## Data

- Big test (branch bigtest, export 4 Nov 06:12 UTC): 777,075 coin rows from 298 hourly scans, 22 Oct 10:08 UTC to 4 Nov ~03 UTC.
- Pick account: 132 buys, 113 with a 12-hour minute path (FIT 79 before 31 Oct 00:00 UTC, CHECK 34).
- Learning Pick: 294 buys, 276 with a 6-hour path (cross-check only).

## Result per family (EUR per 50 EUR trade after the paper fees)

| Family | Rules scored | Rank corr. FIT -> CHECK | 50 best on FIT: share > 0 on CHECK | all rules | 50 best, w/o best trade > 0 |
|---|---|---|---|---|---|
| F1 sell rules on Pick buys | 2,846 | 0.17 | 100 % | 78 % | 70 % (all: 40 %) |
| F2 Pick buys to leave out | 6,553 | -0.04 | 60 % | 68 % | 34 % (all: 44 %) |
| F3 buy filters on the big test | 38,701 | 0.62 (windows) | 14 % | 4 % | 0 % (all: 0.6 %) |

- F1: the only family with some persistence. The CHECK days were a good market (78 % of all sell rules positive), so most of the
  lead is market, not rule. Common thread of the leaders: the Sell bot lets winners go too early (the 6-hour limit and the 15 % "drop");
  a 30 % drop, the trail armed only at 2x and up to 12 h did better. Of N1's lead, +47 EUR comes from X's 63 drop sales, the rest
  from longer holds (MOONX: X -1.44 at 6 h, N1 +89.98; ANTS: X drop -10.43, N1 trail +74.95). The Pick re-buys the same coin often
  (ANTS 8x, INVERSE 5x), so the trades are not independent and the bootstrap is, if anything, too kind. N1 vs the real Sell bot (X replayed) on all 113 buys: +3.87 EUR a trade (+437 EUR), paired
  1 % bound -1.38, 4.5 % of re-draws <= 0. Even on the data it was chosen on, N1 does NOT pass the PR #39 bar (1 % bound -4.34).
  On the Learning Pick's coins every sell rule loses (-3 to -4 a trade): the sell rule cannot rescue bad buys.
- F2: no signal at all (the 50 best on FIT did worse on CHECK than the average rule). Its 3 candidates are expected to fail.
- F3: everything loses after the 2-hour price; the gate passers -2.40 (FIT) and -4.22 (CHECK). Every rule positive on CHECK is so
  because of one coin (0 % of the 50 best stay positive without their best coin). The nightly filter search found the same for two
  weeks: its 10 rules frozen 21-30 Oct all lost afterwards (-1.12 to -2.87 per 20).

## Frozen candidates (live from 5 Nov)

- N1-N3: Sell bot variants (arm 2x, drop 30 % in 30 or 15 min, trail 15 % or 10 %, floor -50 %, 11x, 12 h). CHECK +8.3 to +8.8.
- P1-P3: buys/sells 1h >= 1.116 and (buys 1h <= 635 | top 10 <= 26.85 % | liquidity <= $70.4k). CHECK +1.3 to +3.2.
- B1-B3: (1 h-3 d universe, last hour <= 2.8 % of the day's volume, holders +4,932 in 24 h) / (1-6 h, buys/sells 1h <= 1.417, net
  buyers 24 h >= 1,190) / (1 h-3 d universe, last hour <= 2.8 %, organic >= 64.465). CHECK +2.8 to +7.0, all negative w/o best.

## What the sample can show by 22 Nov

Per-trade spread of the Pick's trades is about 28 EUR per 50 EUR. With ~150 buys by 21 Nov the 1 % bound sits about 5.4 EUR under
the mean: only a rule that earns more than ~5.5 EUR a trade after the allowance (11 % a trade) can pass on 22 Nov. A real edge of
+2 EUR a trade would need roughly 1,100 trades (about 4 months at ~9 buys a day) to show. A fail on 22 Nov therefore does not prove a rule worthless,
and a pass of one of 9 has about a 1-in-10 chance by luck.

## Clean-up (same change)

Learning Pick and Rocket seeker 🔭: no new buys from 4 Nov 18:00 UTC (open trades still sold, data kept); the Learning Pick's
nightly training left filtersearch.yml; shadow rule D retired (shadow.RETIRED); 10 dead research workflows deleted (8 winlose-*
triggers on an old branch, probe-keys, history-probe). Untouched: the Pick account, the Sell bot, the Radar account 🚀.
