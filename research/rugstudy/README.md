# Rug study (2026-10-13): what happens before a new coin is pulled, and can the bot see it earlier?

Fake money only. The bot never buys anything for real; this study only decides which warning signs the launch radar
weighs. Its numbers are frozen into `radar_weights.json` (repository root) and are never recomputed during a build.

Data: the bot's own records on the `results` branch (`db/memeyoung`, `db/memeearly`, `db/memepos`, `db/memeexit`) and the
scored snapshots of the `bigtest` export (`memesnapres`, 10,238 chunks). Read only, no network.

Four groups of coins ("cohorts") are used throughout:

| Cohort | What | Coins | Outcome |
|---|---|---|---|
| L | listed new launches (new-launches tab and early list), first listing per coin, 161 scans, 07.10. 22:20 to 13.10. 19:56 UTC | 1,648 | rug or 2x within 1 h |
| E | the early-list part of L (coins the spotter saw minutes old) | 847 | rug within 1 h |
| S | every scanned coin under 1 h old with $5k+ liquidity, first sighting, 185 scans, 06.10. to 13.10. | 3,222 | rug or 2x within 2 h |
| P | paper new-launch positions since the 10.10. 18:11 UTC restart (3 fake euros each) | 395 | rug at any time |

"Rug" = the pool was gone, under $1,000 of liquidity, or the price fell 90% or more. "2x" = a rise to 2x-30x with liquidity
that grew like a real pool (a dead pool's last price, a self-priced pool or a 30x+ spike never counts). Intervals are 95%
from a bootstrap that resamples whole scans (4,000 draws). "Halves" = the same test on the first and the second half of the
scans.

## T1. Base rates

| Cohort | Rug | 2x | Other |
|---|---|---|---|
| L | 30.1% [27.6-32.6] of 1,646 within 1 h | 8.9% [7.5-10.4] | 61.3% rugged within 24 h |
| E | 41% within 1 h | 9% | |
| S | 54.7% [52.6-56.9] within 2 h | 2.8% [2.2-3.4] | |
| P | 38.4% [32.9-43.5] at any time | 8.9% within 1 h | 74.4% hit the stop or rugged |

Coins under 10 minutes old rug far more often: L 45.6% vs 25.1% for older listings (+20.6 points [+15.2..+26.0]),
S 72.5% vs 38.8%.

## T2. Hard traps, one by one (rug rate with vs without, lift [95%])

| Trap | L, 1 h | E, 1 h | S, 2 h | P |
|---|---|---|---|---|
| pool opened within 60 s of the mint | 60% vs 20%, 2.94 [2.54-3.39] | 60% vs 24%, 2.51 [2.09-3.05] | (no mint times) | 27% vs 11%, 2.37 [1.42-4.05] |
| top holders from rugged coins (wallet memory) | 46% vs 24%, 1.90 [1.60-2.24] | 55% vs 35%, 1.57 [1.31-1.88] | 54% vs 55%, 0.98 [0.86-1.10] | 27% vs 11%, 2.47 [1.62-3.85] |
| brand, AI or celebrity name | 75% vs 24%, 3.08 [2.71-3.51] | 76% vs 35%, 2.15 [1.89-2.43] | 93% vs 50%, 1.86 [1.75-1.95] | 56% vs 12%, 4.51 [2.95-6.71] |
| 3,000+ buys in the first hour | 56% vs 19%, 2.94 [2.50-3.49] | 69% vs 31%, 2.26 [1.94-2.63] | 70% vs 49%, 1.41 [1.31-1.52] | 51% vs 5%, 10.75 [6.39-21.14] |
| RugCheck danger flag | 30% vs 30%, 1.02 [0.78-1.25] | 58% vs 38%, 1.54 [1.25-1.88] | 30% vs 56%, 0.54 [0.43-0.66] | 13% vs 17%, 0.80 [0.35-1.52] |

The RugCheck danger flag only holds in the early list (the radar's own population) and reverses in the 2 h snapshot
cohort; it stays a hard trap because the study's rule D includes it and the radar rates coins of exactly the early-list age.
The staircase chart is in T6.

## T3. Soft warnings, the missing report, and good signs (L, 1 h; S, 2 h)

| Signal | L rug with vs without | lift [95%] | S lift | Weight |
|---|---|---|---|---|
| no socials | 35.3% vs 13.1% | 2.69 [2.07-3.53] | 2.13 [1.86-2.47] | soft, 1 point |
| RugCheck holder cluster (insider network or holder correlation) | 36.0% vs 19.3% | 1.86 [1.52-2.30] | 1.89 [1.56-2.28] | soft, 1 point, blocks the push |
| creator already sold | 35.9% vs 13.8% | 2.61 [2.05-3.40] | 3.36 [2.67-4.31] | soft, 1 point |
| up 20%+ in 5 minutes | 30.8% vs 25.8% | 1.20 [0.96-1.48] | 1.39 [1.30-1.47] | soft, 1 point |
| no RugCheck report yet | 44.1% vs 24.4% | 1.8 (report: 0.55 [0.47-0.64]) | 2.1 | blocks green, 2 points |
| pool under 5 minutes old | 48.6% vs 26.1% | 1.86 [1.59-2.18] | 1.83 [1.70-1.97] | 1 point, ranking only |
| X link (good sign with a paid profile) | 13.4% vs 34.8% | 0.38 [0.29-0.50] | | -1 point with a paid profile |
| paid DexScreener profile | 7.9% vs 32.0% | 0.25 [0.16-0.36] | | (with the X link) |
| launched off a tweet | 12.9% vs 32.5% | 0.40 [0.28-0.53] | | -1 point |
| on 3+ source lists | 24.2% vs 31.3% | 0.77 [0.65-0.91] | | -1 point |

For a 2x within 1 h (L): X link 13.2% vs 7.7%, paid profile 13.0% vs 7.5%, tweet 14.3% vs 8.0%, 3+ lists 14.0% vs 5.2%;
creator holding over 5% 0.0% of 69, market cap $500k+ 4.8% vs 11.0%, holder cluster 4.8% vs 11.2%. These set the
"upside" ranking among coins without traps; nothing in this table turns a trap into a good coin.

## T4. The rules A-E (rug / 2x, first half | second half)

| Rule | L 1 h | E 1 h | S 2 h | P |
|---|---|---|---|---|
| A. any hard trap | 40% [37-43] / 9% (26% / 47%) | 49% / 10% | 60% / 2% | 22% / 10% |
| B. no hard trap, no RugCheck report | 27% [21-32] / 6% | 33% / 7% | 61% / 3% | 25% (n=4) |
| C. no hard trap, checked, 2+ soft warnings | 10% [5-16] / 6% | 13% / 13% | 17% / 4% | 0% (n=19) |
| D. no hard trap, checked, 0-1 soft warning | 3% [1-5] / 14% (3% / 3%) | 4% [0-10] / 11% | 8% [5-12] / 6% | 3% [0-8] / 7% |
| E. D plus a good sign | 3% [1-6] / 16% | 4% / 11% | 9% / 7% | 4% / 8% |
| all | 30% / 9% | 41% / 9% | 55% / 3% | 16% / 9% |

Rule D is the radar's "no trap found". The radar makes it strict: the mint time and the wallet memory must be known too.

## T5. Rule D inside the radar's own population (coins under 10 minutes old)

| Group | L rug 1 h | E rug 1 h | S rug 2 h |
|---|---|---|---|
| any hard trap | 59% [52-65] of 222 | 69% [60-78] of 128 | 78% [73-82] of 388 |
| no hard trap, not checked | 39% [30-48] of 119 | 48% [38-58] of 81 | 74% [71-77] of 1,057 |
| rule D | 7% [0-16] of 42 (2x: 19%) | 12% [0-40] of 8 | 15% [6-26] of 53 |
| all under 10 minutes | 46% [41-51] of 402 | 59% [53-66] of 220 | 72% [70-75] of 1,522 |

Rule D coins under 10 minutes were seen in 36 of 161 scans (L): expect "no clean coin right now" most of the time.

## T6. The staircase chart (nexus_trades), first 10 minutes of 430 listed coins with a full minute path

| Shape in minutes 0-10 | n | -90% after minute 10 | 2x after minute 10 |
|---|---|---|---|
| all | 430 | 17% [13-20] | 14% [11-17] |
| rose 20%+ | 114 | 39% [30-47] | 24% [16-32] |
| staircase: rose 20%+, 70%+ green candles, no 5% pullback | 49 | 63% [50-78] | 37% [22-53] |
| rose 20%+ with a 15%+ pullback (organic) | 43 | 23% [11-37] | 14% [5-26] |
| flat | 214 | 10% [6-15] | 6% [3-9] |

Staircase vs other risers: 63% vs 20% rugged, +43 points [+26..+61]. A hard trap at 10+ candles; with 6-9 candles the radar
shows a grey "staircase so far" only (a pool under 10 minutes rarely has 10 candles).

## T7. The points (hard 3, brand 2, 3,000 buys 2, no report 2, each soft 1, under 5 min 1, good signs -1; pts = max(sum, hard points))

| Cohort | Rug AUC (1st / 2nd half) | 0 or less | 1-2 | 3+ |
|---|---|---|---|---|
| L | 0.807 (0.765 / 0.805) | 3.6% [1.3-6.1] of 253 | 18.4% of 283 | 39.1% of 1,110 |
| E | 0.803 (0.852 / 0.757) | 4.5% of 89 | 23.9% of 138 | 50.0% of 620 |
| S | 0.770 (0.759 / 0.782) | 12.5% of 265 | 32.6% of 552 | 64.4% of 2,405 |
| P | 0.797 (0.776 / 0.843) | 4.5% of 89 | 11.6% of 43 | 21.1% of 261 |

The points separate rugs well but not winners (2x AUC 0.41-0.70, unstable between halves), so they rank and colour, and
never make a coin green on their own. Points fitted on one half and tested on the other (points.txt) gave AUC 0.57-0.65:
the hand-set points above are the study's recommendation (recommend.py).

## T8. Hour of the day (Berlin)

| 4-hour block | L rug 1 h | S rug 2 h |
|---|---|---|
| 00-04 | 27.7% [21.6-33.8] | 52.2% [46.6-57.4] |
| 04-08 | 30.2% [22.5-37.1] | 52.9% [47.6-58.6] |
| 08-12 | 28.3% [21.8-34.0] | 53.8% [48.5-58.9] |
| 12-16 | 32.4% [24.8-39.5] | 57.0% [50.9-62.7] |
| 16-20 | 28.9% [23.3-34.2] | 55.9% [50.8-61.4] |
| 20-24 | 33.2% [27.9-38.4] | 56.3% [52.0-60.7] |

No block stands out: the hour gets no weight, and the office's daily overview names an hour only once its interval clears
the week's rate in both halves.

## T9. The paper account by trap band (375 closed new-launch positions, 3 fake euros each)

| Band | Positions | Result | Each | Exits |
|---|---|---|---|---|
| 0 points or less | 86 | -53.61 fake EUR | -0.62 (-21%) | rug 1, stop 70, time 14, take-profit 1 |
| 1-2 points | 40 | -13.20 | -0.33 (-11%) | stop 29, time 10, take-profit 1 |
| 3+ points | 249 | -299.22 | -1.20 (-40%) | rug 8, stop 171, time 69, take-profit 1 |
| all | 375 | -366.03 | -0.98 (-33%) | |

The 3+ band holds 82% of the paper losses. Hindsight on fake money: it says which coins to avoid, not what to buy.

## Weight 0 (tested here, not used)

Reversed (coins with it rugged less): biggest wallet over 20%, top 10 over 35% or 50%, RugCheck "LP unlocked", "few LP
providers", "mutable metadata", "high market cap per holder", the low-liquidity warning. No effect: RugCheck "creator history
of rugged tokens" (30 coins, lift 0.68 [0.24-1.33]), Jupiter's dev mint count, single holder, under 300 holders, volume over
5x the market cap, DexScreener boosts, the hour of the day, and on coins under 1 h the bot score (out-of-time AUC for
winners 0.42-0.45) and the trained zero odds (AUC for rugs 0.45-0.51). Too rare: RugCheck "copycat" (9 coins). Covered elsewhere: a reused ticker (the bot's copy gate). Unreliable:
Jupiter organic score 0 (known for a third of new coins; paper positions with it lost less). `radar_weights.json` lists each
with its numbers.

Never stored before, so not testable here (the radar measures them from now on and shows them grey, weight 0, until its own
records confirm them): snipers in the first 30 s, wallets in the launch block, the dev wallet's age, the dev's dead launches,
an X account or community reused from an older coin, fresh top-holder wallets, top holders funded by one wallet, the early
staircase.

## Caveats

- 8 days of data, one market regime.
- The points were set after seeing the data: the halves show stability, not an independent test.
- Survivorship: coins that rugged before minute 5 or never left the bonding curve are not in the data.
- RugCheck "clean" on a coin minutes old is no safety sign.
- The radar's own records (every rated coin, with its prices 5/15/30/60 minutes later) are the first forward test. Its
  model (`traps.fit`) only moves a measured signal to soft (at most 2 points) or a soft one to 0, and only after a
  walk-forward check on the last 2 days; hard traps change only by hand.

## How to re-run

```sh
# from the repository root; any scratch folder
sh research/get_data.sh /tmp/rs/big                                   # bigtest export -> /tmp/rs/big/memesnapres
mkdir -p /tmp/rs/res && git fetch -q origin results && git archive origin/results db | tar -x -C /tmp/rs/res
python3 -m venv /tmp/rs/venv && /tmp/rs/venv/bin/pip install numpy
PY=/tmp/rs/venv/bin/python sh research/rugstudy/run_all.sh /tmp/rs/res/db /tmp/rs/big/memesnapres /tmp/rs/out
```

`run_all.sh` writes every table to the out folder plus a fresh `radar_weights.json` there (`make_weights.py`). It never
touches the repository's `radar_weights.json`: replace that file only after a review, since the radar trusts it. The
outputs of the 2026-10-13 run are in `out/` (text tables). New data will give somewhat different numbers.

`make_fixtures.py` (same venv) rebuilds `tests/fixtures/traps/study_rows.json.gz`: 300 study rows with the raw inputs the
radar's rule core reads and the flags `scripts/rules.py` gives them (selftest check T3, study parity).
