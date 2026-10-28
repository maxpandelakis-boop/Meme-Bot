# The big search for better coin choice: report (fake money only)

Pre-registration: research/bigsearch/PREREG-BIGSEARCH-2026-10-28.md (commit 050f05b, pushed 28 Oct ~14:01 UTC, before any data
from 22 Oct on was fetched). Candidates frozen in research/bigsearch/CANDIDATES-2026-10-28.json (commit 9a51ec7, 14:42 UTC, before
S1 was read). Research only: no live rule, account, shadow or bot changed.

## Result in one paragraph

[Certain] Nothing holds. 0 of the 20 frozen candidates passed the bar on the sealed days S1 (pump.fun graduations of 22 Oct 00:00 -
26 Oct 12:00 UTC, judged once on 28 Oct 20:14 UTC); none survives Holm at 5 %. Together they made 553 trades and lost 1,577.50 EUR
after the allowance (-2.85 EUR a trade). Only 6 candidates reached 40 trades; the best of those (P SHRUNK-FREQ) made +0.57 EUR a
trade with a 1 %/20 lower bound of -5.47 and -69.10 without its best trade. In hindsight, the best searched rule with >= 40 S1
trades made +45.04 EUR a trade (family U): that is the size of luck when the rule is chosen after the look. [Likely] The result
repeats every earlier search on these coins: being best on past months does not carry into new days. S2 (22 Oct - 21 Nov, from
24 Nov) judges the same 20 again with about six times the data; nothing is offered as a shadow rule now.

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

### Data and coverage

- [Certain] S1 = 2,661 graduations with start SOL side >= 10 (22 Oct 00:00 - 26 Oct 12:00 UTC), all with GeckoTerminal 5-minute
  candles of their first 48 h (191,849 candles); launch facts for 3,253 mints of 21 Oct - 26 Oct 12:00 (name for all, creator for 3,248), X/link
  facts for 98.8 % of S1 coins. Picture facts were not built for S1 (exploration only, not used by any candidate).
- [Certain] Graduations a day with start SOL side >= 10: 22 Oct 611, 23 Oct 688, 24 Oct 593, 25 Oct 501, 26 Oct 500 (full day),
  against 559-852 a day in w5. Entry rows per family match w5's rate: P 60 coins (w5 at the same rate: ~64), U 564 (~622),
  R 676 (~661), S 1,117 (~1,145).
- [Certain] The first fetch (public RPC, transaction version 0 only) lost the migrations sent as version-1 transactions
  ("rpc -32015", ~14 % of the migration account's transactions; 123 of w5's 151 graduations of 21 Oct 00:00-06:00 found).
  This was found from counts only, before any S1 price or result was looked at (prereg amendment, 18:30 UTC). Two repair passes
  (runs 40745607675 and 40754235738) asked those transactions again with version 1 and added 766 S1 pools (29 % of S1); in the second pass 68
  of the 71 graduations recovered were version-1 transactions, 3 of 307 transactions stayed unanswered. 21 Oct 00:00-06:00 is
  taken from w5's Helius list.

### The judgement (research/bigsearch/results/JUDGE-S1-2026-10-28.json, trades per coin listed there)

| family | picker | buy rule | sell rule | S1 trades | mean after allowance | 1 % / 20 lower bound | total | without best | holds |
|---|---|---|---|---|---|---|---|---|---|
| P | ROBUST | last hour's share of 24 h volume at most 0.009893 AND 5 min change at least 0 AND share of rising candles, last hour at least 0.5833 | -20% / no target / 6 h | 11 | -12.15 | -33.45 | -133.7 | -142.3 | no |
| P | SHRUNK | 6 h change at least 0.3114 AND minutes since the last trade at least 3.033 AND description length at most 0 | no stop / 3x / 12 h | 6 | -20.61 | -46.41 | -123.7 | -141.5 | no |
| P | ROBUST-FREQ | 5 min change at least 0 AND SOL 1 h change at least 0 AND minutes on the bonding curve at least 0 | -10% / 1.5x / 1 h | 48 | -1.88 | -5.37 | -90.4 | -113.2 | no |
| P | SHRUNK-FREQ | 30 min change at least 0.003647 AND last hour volume / hour before at least 0.9928 AND creator's graduations in 30 days at least 0 | -10% / 3x / 1 h | 48 | +0.57 | -5.47 | +27.1 | -69.1 | no |
| P | ML | LightGBM top 10 % | -30% / 5x / 1 h | 25 | +0.12 | -14.23 | +2.9 | -111.6 | no |
| U | ROBUST | 24 h change at least 3.764 AND log10 last hour volume at most 4.077 AND 30 min change at most -0.0159 | no stop / 11x / 6 h | 7 | -0.32 | -7.95 | -2.2 | -11.0 | no |
| U | SHRUNK | 5 min change at most -0.009749 AND log10 last hour volume at most 3.749 AND rise from the low at least 6.206 | no stop / 3x / 24 h | 2 | +23.03 | -50.20 | +46.1 | -50.2 | no |
| U | ROBUST-FREQ | last hour's share of 24 h volume at most 0.0309 AND 1 h change at most -0.1426 AND rise from the low at least 0.7228 | -50% / no target / 2 h | 38 | -0.71 | -9.17 | -26.8 | -99.7 | no |
| U | SHRUNK-FREQ | last hour's share of 24 h volume at most 0.0309 AND 5 min change at most -0.009749 AND 6-hour block (UTC) = 1 | -30% / 5x / 1 h | 51 | -1.88 | -7.68 | -96.0 | -144.2 | no |
| U | ML | LightGBM top 2 % | -20% / 3x / 6 h | 4 | +11.78 | -50.85 | +47.1 | -49.1 | no |
| R | ROBUST | share of rising candles, last hour at most 0.4167 AND rise from the low at least 3.937 AND same-theme graduations 24 h at least 1 | -20% / no target / 12 h | 18 | -6.60 | -11.74 | -118.7 | -126.2 | no |
| R | SHRUNK | 24 h change at most 0.3773 AND log10 last hour volume at least 5.028 AND number of links = 0 | -50% / 5x / 6 h | 7 | -0.50 | -21.23 | -3.5 | -78.0 | no |
| R | ROBUST-FREQ | 1 h change at most -0.009544 AND last hour volume / hour before at most 1.02 AND hour (UTC) at most 11 | -10% / no target / 1 h | 45 | -3.60 | -6.37 | -162.0 | -175.8 | no |
| R | SHRUNK-FREQ | hours since graduation at least 4.5 AND 1 h change at most 0.01458 AND SOL 1 h change at most 0 | -10% / 3x / 1 h | 74 | -3.30 | -4.96 | -244.4 | -248.0 | no |
| R | ML | LightGBM top 5 % | -30% / 11x / 6 h | 16 | -1.11 | -6.26 | -17.8 | -37.3 | no |
| S | ROBUST | 24 h volume / market cap at least 0.7622 AND 1 h volatility at most 0.1342 AND number of links = 0 | trailing 30% / 24 h | 15 | +7.44 | -13.05 | +111.6 | -4.4 | no |
| S | SHRUNK | 24 h volume / market cap at most 0.001038 AND 5 min change at least 0.01042 AND number of links = 1 | -70% / 2x / 6 h | 0 | - | - | - | - | no |
| S | ROBUST-FREQ | 24 h volume / market cap at least 0.7622 AND creator's graduations in 30 days at most 0 AND number of links = 0 | trailing 20% / 24 h | 55 | -7.28 | -15.53 | -400.3 | -537.6 | no |
| S | SHRUNK-FREQ | distance from the high at least -0.1361 AND share of rising candles, last hour at most 0.6667 AND hour (UTC) at most 12 | -10% / 5x / 1 h | 68 | -4.67 | -7.97 | -317.4 | -351.6 | no |
| S | ML | LightGBM top 5 % | -30% / 11x / 6 h | 15 | -5.03 | -15.00 | -75.4 | -103.3 | no |

- [Certain] 14 of 20 candidates have fewer than 40 S1 trades, so they fail point 1 on S1 and are judged on S2 only, as
  pre-registered. Of the 6 with >= 40 trades, 5 lost money and the sixth was +0.57 a trade with -69.10 without its best trade.
- [Certain] The positive ones with few trades rest on one or two coins: S ROBUST +111.6 EUR total on 15 trades is -4.4 without its
  best trade; U SHRUNK is 2 trades, U ML 4.
- [Certain] Walk-forward "best ML" (U, LightGBM top 2 %, +6.20 on the test windows): 4 S1 trades, +11.78 each, -49.1 without the best.

### The size of luck (research/bigsearch/results/LUCK-S1-2026-10-28.json)

Among the same S1-allowed filters (evaluated on S1 with all 225 sell rules, only filters with >= 40 S1 trades):

| family | filters with >= 40 S1 trades | of those with a positive best sell rule | best mean in hindsight (EUR/trade) |
|---|---|---|---|
| P | 1,438 | 880 | +8.04 (40 trades) |
| U | 157,463 | 41,248 | +45.04 (41 trades) |
| R | 89,570 | 6,974 | +13.18 (40 trades) |
| S | 203,358 | 10,072 | +20.55 (40 trades) |

[Likely] Picking the best of ~850 million (filter, sell rule) pairs after seeing S1 would show a "winner" in every family; the
pre-chosen candidates made -2.85 a trade. That gap is the luck any after-the-fact rule carries.

## Next

- [Certain] Nothing is built into the bots and no shadow rule is proposed: no candidate held. The live Pick account, Radar
  account, Learning Pick and Rocket seeker keep their rules (frozen until the 4 Nov review).
- S2: on or after 24 Nov 2026 the same 20 candidates are judged on 22 Oct 00:00 - 21 Nov 23:59 UTC (bs_fetch.py with the
  version-1 fix and the S2 window, then `bs_build.py rows ... s1`-style build and `bs_search.py judge`), same bar, nothing re-picked.
  A candidate must hold on S2 before it could even be offered as a shadow rule.
- Not testable for free, with cost [Guessing: prices as of 2025, may have changed]: wallet histories for the sealed days need a
  paid Solana RPC/indexer (e.g. a Helius paid plan, from roughly $50 a month); X followers/likes/views need the paid X API (Basic
  was about $200 a month) and today's counts would leak which coins rose; bundles/snipers/every curve trade need paid Dune or
  Bitquery tiers. The wallet lead (w3 -> w4: -4.33 against -6.34 a trade) is the only one that might justify such a cost, and only
  after a costed pre-registered test.
- [Likely] More rules would not change this: 1.39 billion pairs already cover every threshold of every free variable we have.
