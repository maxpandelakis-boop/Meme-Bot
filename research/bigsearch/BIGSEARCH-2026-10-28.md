# The big search for better coin choice: report (fake money only)

Pre-registration: research/bigsearch/PREREG-BIGSEARCH-2026-10-28.md (commit 050f05b, pushed 28 Oct ~14:01 UTC, before any data
from 22 Oct on was fetched). Candidates frozen in research/bigsearch/CANDIDATES-2026-10-28.json (commit 9a51ec7, 14:42 UTC, before
S1 was read). Research only: no live rule, account, shadow or bot changed.

## Result in one paragraph

S1_RESULT

## What was searched

[Certain] 1,389,262,725 (filter, sell rule) pairs and 64 LightGBM fits on every free variable of the five fit windows (w1 25 Apr-24
May, w2 25 Jun-24 Jul, w3 10 Aug-9 Sep, w4 10 Sep-8 Oct, w5 9-21 Oct 2026; ~70,000 graduations).

| family | entries | money | coins w1-w5 | filters | pairs |
|---|---|---|---|---|---|
| P (Pick gates, 6-24 h, hourly) | first hourly entry passing the filter | 50 EUR | 1,852 | 1,706,455 | 383,952,375 |
| U (wide, 1-24 h, hourly) | same | 50 EUR | 16,496 | 1,491,865 | 335,669,625 |
| R (Radar conditions, <= 12 h, every 30 min) | same | 20 EUR | 12,520 | 1,575,243 | 354,429,675 |
| S (seeker-style, 30/60 min after graduation, liq >= $10k) | same | 20 EUR | 28,878 | 1,400,938 | 315,211,050 |

- 54 variables: 23 chart, 14 launch facts (curve minutes, creator history, same ticker, CJK name, graduations in 24 h, links, X
  link type, X post age, theme, picture reused, launched off pump.fun, video, description length, Wikipedia top), 5 time/market +
  6-hour block, 4 picture facts (exploration only), 7 wallet facts (w3/w4 only, exploration only).
- Conditions at the 10/20/30/50 % ("at most") and 50/70/80/90 % ("at least") quantiles, category levels; singles, pairs, beam
  triples (2,000 best pairs per scheme x every third condition).
- 225 sell rules (check_months.py's 222 + three Rocket holds). Costs: the paper accounts' fees plus an allowance of 0.75 EUR
  (50 EUR) / 0.60 EUR (20 EUR) per trade.
- LightGBM per family: targets rule K, rule A, the family's best base rule, Rocket hold; cuts top 1/2/5/10 %.

## Walk-forward (fit on older windows, test on the next one)

[Certain] 43 of the 48 walk-forward picks (4 families x 4 pickers x 3 steps, S1-allowed variables) lost money on the next window.

| family | picks positive next window | trade-weighted next-window mean (EUR/trade) | top-100 positive | all positive | best ML (target, cut), mean over 3 test windows |
|---|---|---|---|---|---|
| P | 2 of 12 | -4.02 (1,655 trades) | 7.6 % | 3.2 % | -1.22 |
| U | 2 of 12 | -15.06 (4,007 trades) | 5.6 % | 1.4 % | +6.20 (99 trades; +4.33, +15.60, -1.31) |
| R | 0 of 12 | -8.16 (3,380 trades) | 3.8 % | 0.4 % | -1.62 |
| S | 1 of 12 | -4.58 (2,284 trades) | 7.6 % | 0.8 % | -0.59 |

- [Certain] The 5 positive picks had 11-37 test trades except one (U, 150 trades, +0.19).
- [Certain] Ranking carries a little: the top 100 rules stay positive more often than all rules, and in U/R/S the fit-window rank
  correlates with the next window (0.44-0.51, scheme C, SHRUNK score). The best decile still loses 2.40-3.95 EUR a trade.
- [Likely] One can select what loses less, not what wins.

Details per scheme and picker: research/bigsearch/results/WALKFORWARD-2026-10-28.json; ML per (target, cut):
research/bigsearch/results/ml_<F>.json.

## Exploration (not allowed in sealed candidates)

- [Certain] Wallets (w3 -> w4 only): picks with wallet variables lost -4.33 EUR a trade in w4 against -6.34 without (16 picks
  each, ~2,000 trades). 2 of 16 wallet picks positive (R +29.48 on 36 trades, S +26.73 on 25) against 1 of 16 without.
- [Guessing] A lead at best: one test window, small counts, and not testable on the sealed days for free (every swap of every
  S1 coin is needed; the free Helius key answered one page then 429 on 28 Oct).
- [Certain] Coins with no links lose less than coins with links in all four families (e.g. R best base rule -3.10 against -4.51),
  but they still lose; 5 of the 20 candidates require no links or no description.
- Not testable for free: X followers/likes/views (X API, paid; today's counts leak the outcome), Telegram (user's own API key),
  pump.fun replies (login), bundles/snipers/every curve trade (paid RPC, Dune, Bitquery).

## The 20 frozen candidates

[Certain] All 8 FREQ candidates (>= 8 trades a day in every fit window) are negative even in-sample: no rule with enough trades for
real money was positive on the fit windows. S SHRUNK only trades in w3/w4 (a history2 data artifact). See
research/bigsearch/CANDIDATES-2026-10-28.json for every threshold.

## S1: the sealed days, judged once

S1_TABLE

## Next

NEXT_STEPS
