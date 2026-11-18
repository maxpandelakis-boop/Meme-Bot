# Pre-registration: the Pick rules that were positive in all three periods, judged on 22 Oct-21 Nov (26 Oct 2026, ~09:30 UTC)

Fake money only. Research only: nothing here is switched on, no bot, account or rule changes, no shadow in the live bots.
Written and pushed before any of the data it will be judged on exists (the window starts after the last data used here, 21 Oct).

## Why

The rocket separator study (ROCKETSEP-2026-10-26.md) found nothing that holds. The user (26 Oct 08:41 UTC): "prüfe mehr bis du
was findest wo man nur solche coins erkennt". Searching the same five months again until something works is how the +414
EUR/trade rule of that study came about, so no new search is run. Instead the one trace of persistence that study found (an
exploration, rs_persist.py) is frozen now and judged on a month no one has seen.

## The rules (frozen in research/rocketsep/NOV-RULES-2026-10-26.json by rs_nov.py freeze)

Family-A rule-plan pairs of check_rs.py best, role P (the Pick's gates), with 40+ trades and a mean above the 0.75 EUR allowance in
w1-w3, 20+ trades and a positive mean after it on w4, and 5+ trades and a positive mean after it on w5. 12 of the 17,112 pairs
searched pass that; they are 8 distinct conditions with one to three sale plans each. Each condition is stored with its cut values
(quintile edges from w1-w3), so nothing is refitted.

| Rule | Plan | w1-w3 trades, EUR | w4 | w5 |
|---|---|---|---|---|
| name-picture fit q1 AND turnover q2 | R24 | 47, +6.68 | 21, +27.59 | 9, +21.76 |
| X post up to 1 h old AND no description | R6 | 83, +5.82 | 22, +7.37 | 10, +13.81 |
| 6 h return q4 AND turnover q2 | K | 71, +2.35 | 21, +12.60 | 14, +3.76 |
| bonding curve 1-10 min AND liquidity/mcap q2 | R6 | 55, +4.99 | 23, +2.21 | 7, +7.09 |
| X post up to 1 h old AND no description | R24 | 83, +4.44 | 22, +13.64 | 10, +1.91 |
| X post up to 1 h old AND launched outside pump.fun | R6 | 88, +3.71 | 25, +1.85 | 10, +11.16 |
| 6 h return q4 AND turnover q2 | R6 | 71, +1.81 | 21, +11.99 | 14, +3.15 |
| graduations in 24 h q4 AND 6 h return q4 | K | 62, +1.33 | 21, +7.90 | 9, +17.73 |
| no description AND turnover q2 | K | 76, +5.38 | 25, +4.15 | 14, +0.41 |
| graduations in 24 h q4 AND 6 h return q4 | R6 | 62, +0.28 | 21, +7.61 | 9, +16.90 |
| no description AND 6 h return q4 | R6 | 91, +0.22 | 30, +0.56 | 12, +2.85 |
| no description AND turnover q2 | R6 | 76, +5.17 | 25, +4.10 | 14, +0.04 |

All of them together (a buy taken when any rule takes it, sold by the plan of the first rule in the file that takes it), after the
allowance, per trade (rs_nov.py judge): w1 96 trades +1.31, w2 126 +3.92, w3 173 +0.30, w4 124 +2.56, w5 55 +6.25. Positive in
every window, which is close to built in (each pair was picked for being positive there); the 1 % bootstrap bound is between -6.1
and -8.9 in every window and the total without the best trade is negative in four of five.

## The test window and the data

w6 = Pick-gate buys of the pump.fun graduations of 22 Oct 00:00 - 21 Nov 23:59 UTC, built exactly as w5: graduation list,
GeckoTerminal five-minute candles of the first 48 hours (research/months_fetch.py), the rocket-study launch, metadata and picture
facts (research/rockets/meta_chain.py, images.py), then rs_build.py, rs_facts.py and check_rs.py ceiling (buyplans.npy). It can be
built from 24 Nov (the last coins need their 48 hours). Then: `python3 research/rocketsep/rs_nov.py judge <out dir> w6`.

## The bar (the same as everywhere: research/PREREG-REVIEW-2026-11-04.md)

The set together HOLDS if on w6: (1) 40+ trades, (2) mean per trade after the 0.75 EUR allowance above 0, (3) the 1st percentile of
10,000 bootstrap re-draws above 0, (4) the total without its single best trade above 0. Each rule alone is reported with the same
four points; with 10-30 trades a month a single rule cannot pass point 1, so the set is the test.

Said now, before the result: the trades of these rules scatter about 47 EUR around their mean (w4). At about 120 trades a month,
point 3 needs a mean of about +10 EUR per trade. A true edge of +2.5 EUR per trade would need about 2,000 trades (well over a year)
to pass point 3. So a fail on w6 cannot rule out a small edge, and a pass would be a strong surprise.

## What follows from it

Nothing switches on by itself. A pass is reported to the user with the numbers; any live use needs his explicit yes (a Pick rule
change restarts the paper account).
