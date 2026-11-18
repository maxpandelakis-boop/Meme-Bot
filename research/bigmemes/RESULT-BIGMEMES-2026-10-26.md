# Result: big meme coins on Binance spot as a new hunting ground (fake money only)

Pre-registration: research/bigmemes/PREREG-BIGMEMES-2026-10-26.md (commit 7a07685, before any price was fetched).
Universe: research/bigmemes/UNIVERSE.md (35 pairs, frozen from names in commit 8109782). Numbers: RESULT.json (test months,
commit 02ce522, before the holdout was opened) and RESULT-HOLDOUT.json (1 July to 25 October 2026, opened once, 15f5f6c).
Code: check_bigmemes.py; checked on zero-drift random data (nothing passes) and with a wipe-the-future test (0 of 213 rules
look ahead).

## Verdict

**Nothing holds.** No candidate passes the pre-registered bar, and the closest one lost on the sealed months. Not a basis for
copy-trading with real money.

## Test months, January 2022 to June 2026 (54 months, base costs 0.25% per side, fill at 08:00 UTC)

| candidate | closed trades | mean per trade | mean month | p (trades / months) | 1,000 becomes | max drawdown | passes 1-6 |
|---|---|---|---|---|---|---|---|
| WF (walk-forward pick) | 134 | +2.78% | +2.37% | 0.31 / 0.33 | 202 | -98% | no (3, 4, 5) |
| F1 SMA 50 | 441 | -0.91% | +0.54% | 0.73 / 0.42 | 695 | -75% | no |
| F2 breakout 20/10 | 275 | +1.17% | +1.05% | 0.33 / 0.28 | 1,203 | -59% | no (3, 4, 5) |
| F3 momentum L30 K3 | 156 | -0.04% | -1.08% | 0.54 / 0.61 | 47 | -98% | no |
| F4 reversal L3 H3 K3 | 708 | -0.55% | -3.84% | 0.85 / 0.86 | 20 | -98% | no |
| F5 volume spike X5 +20% H3 | 80 | +3.53% | +0.76% | 0.095 / 0.104 | 1,431 | -14% | no (3 only) |
| F6 dip D25% H7 | 94 | -3.83% | -0.25% | 0.99 / 0.75 | 854 | -33% | no |
| B1 meme basket (benchmark) | - | - | -2.92% | - | 41 | -96% | - |
| B2 BTC hold (benchmark) | - | - | +1.60% | - | 1,268 | -67% | - |

The Holm bar at 1% needs p <= 0.0014 for the best candidate; the best p was 0.095. The walk-forward's arithmetic month mean is
positive only because of a few huge months (+168% March 2024, +98% November 2024, +92% December 2023); its median month is
-1.5% and it compounds to -80%. It beat 93% of random monthly rule choices, which shows how bad the field is, not an edge.

Whole grid (information): 96 of 213 rules have a positive mean month, median rule -0.15% a month. Families: breakouts (F2) and
volume spikes (F5) are positive in every parameter set (18/18 and 36/36), reversal (F4) negative in every set (0/54). Variants of
one family share most trades, so this is one weak signal per family, not dozens. Hindsight best rule: F3 L14 K1 with the BTC
filter, +7.1% a month: the size of luck when choosing after the fact.

Stress (0.5% per side, fill 14:00 UTC): same picture; F5 +5.7% per trade (p 0.03 trades, 0.09 months), still far from the bar.

## Sealed holdout, 1 July to 25 October 2026 (months Claude had never seen)

| candidate | trades | total |
|---|---|---|
| WF (picked F5 variants every month) | 7 | +2.2% |
| F1 SMA 50 | 17 | +32.5% |
| F2 breakout 20/10 | 15 | +11.2% |
| F3 momentum | 11 | -30.4% |
| F4 reversal | 51 | +50.8% |
| F5 volume spike (closest on test months) | 4 | -11.9% |
| F6 dip | 9 | -10.9% |
| B1 meme basket | - | +44.1% |
| B2 BTC | - | +36.7% |

A broad rally (August +55% for the basket, October -19%). Rules that were invested gained with it, none beat simply holding the
basket, and the closest candidate lost. Only 3 to 6 coins were eligible (>= $5M daily volume: DOGE, PEPE, PUMP, PENGU, TRUMP,
TUT, 币安人生); WIF, BONK, SHIB and FLOKI had fallen to $1-4M a day on Binance spot (median daily volume, Jul-Sep 2026).

## Why it fails, in one line each

- Binance lists meme coins near their peak: the equal-weight basket of eligible coins lost 96% over the 54 months.
- Daily rules either ride that decline (trend, momentum) or pay costs chasing noise (reversal); breakouts and volume spikes lose
  less, but their edge is within chance.
- The two years that made money (2024, and the 2026 holdout rally) were market-wide rallies; a rule that held anything gained.

## Limits

- Long only, spot, Binance, USDT pairs, daily signals. Shorts, futures, intraday rules and other exchanges were not tested.
- Survivorship is small but not zero: only one delisted meme pair (GHST) was found; coins that died before a Binance listing never
  enter (they could never have been copied here).
- 2022 to mid-2023 had only 2 to 3 eligible coins (DOGE, SHIB, PEOPLE, then PEPE), so those months test little; the most coins
  were eligible in 2024-2025 (up to 18).
