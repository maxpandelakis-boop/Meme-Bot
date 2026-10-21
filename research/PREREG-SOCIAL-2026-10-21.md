# Pre-registration: do social signals pick the coins that rise? (fake money only)

Written on 2026-10-21 before any outcome of these signals was looked at. Only row counts and the spread of pf.replies and
kwN on the fit half were seen (to fix the cut-offs below). The script `research/check_social.py` follows this text.

## Data

The big test (`sh research/get_data.sh`, bigtest export bcea13f of 2026-10-21 06:29 UTC), profile m9-2h, loaded with
`harness.load` (learnable coins only: liquidity at least $15k, market cap $50k to $2M at scan time). 341 scans,
7 Oct 11:02 to 21 Oct 04:00 UTC.

- **Fit half:** scans before 2026-10-14 00:00 UTC (199 scans, 4,540 coins, 102 of them gate passers).
- **Check half:** scans from 2026-10-14 00:00 UTC (142 scans, 3,749 coins, 85 gate passers).
- **One entry per coin and half:** its first scan in that half (the bot buys a coin once).
- **Result:** the price multiple at the check about 2 hours later (`mult`), turned into profit on 20 EUR with a realistic
  2% round trip (1% each side): `19.602 * mult - 20`, clipped to -20..+60. Also shown at 1% and 3%.
- **To zero:** `gone`. **3x hit:** `mult >= 3`.

## The signals (what the bot already collects, free sources)

| id | source | signal is on when |
|---|---|---|
| x | Dexscreener profile | `x > 0` (an X/Twitter link) |
| web | Dexscreener profile | `web > 0` (a website) |
| tweet | Dexscreener + X | `vt.tweet == 1` (the X link points to one tweet, not an account) |
| tg | pump.fun | `pf.telegram == 1` (only coins with pump.fun data) |
| replies | pump.fun comments | `pf.replies >= 422` (top 30% on the fit half; only coins with pump.fun data) |
| boost | Dexscreener boosts | `boosts > 0` or src `list:boostTop` / `list:boostLatest` |
| paid | Dexscreener paid profile | `ds.paid == 1` (only where known) |
| news | news headlines | `news.hits > 0` |
| reddit | Reddit search | `rd.posts > 0` |
| kw | keyword search hits | `kwN >= 1` |
| trend | Jupiter/GeckoTerminal trending lists | src has `jup:trending1h`, `jup:trending`, `gt:trending1h` or `gt:trending` |
| count | all of the above together | the number of the 11 signals on is at least K; K (1 to 6) chosen on the fit half by the best average |

Too few rows for a test (listed in the result, not tested): Telegram/StockTwits/RugCheck community votes (`cm.*`, under
2,200 rows), viral-tweet likes (`vt.likes`, 392 rows), smart wallets (`sw.*`, a wallet idea, not social).

## The tests

For every signal, in two groups of coins: **all** learnable coins and the **gate passers** (the coins the bot may pick):
coins with the signal on against coins with it off. Reported: coins, average per 20, to zero, 3x hits, and the 95% interval
of the difference (on minus off) by a coin bootstrap (1,000 draws).

## What counts (decided now)

A signal becomes a new bot in the filter team only if, on the **check half**:

1. **Buy signal:** among the gate passers with the signal on, the average per 20 after 2% fees is above zero, the
   interval of (on minus off) lies wholly above zero in the all-coins group, the 3x share with the signal is at least the
   share without, and the difference had the same sign on the fit half.
2. **Or veto:** the interval of (on minus off) lies wholly below zero (or wholly above, then "off" is the veto) in the
   all-coins group on BOTH halves, and keeping only the better side does not lower the 3x share of the gate passers.
   A veto bot is reported as "fewer bad coins", never as "profitable".

12 signals x 2 groups: about one false hit on the fit half is expected by chance; that is why the check half decides.
If no signal passes: nothing is built into the bot, and the result names which sources lack history so a live log can
collect it.

## Part 2 (added 2026-10-21 after part 1, before any data exists): pump.fun comment speed, checked 4 Nov 2026

Part 1 failed (research/SOCIAL-2026-10-21.md). The user chose to log the one untested free signal: how fast people comment.
From the merge on, `fetch.pf_comment_speed` reads the newest 200 replies of up to 30 shortlisted pump.fun coins per scan
and the bot stores `pc.n1h` (replies in the last hour), `pc.n6h`, `pc.users1h` (distinct commenters in the last hour) and
`pc.newestMin` with every scored coin. Measured only: no weight, no gate, no effect on picks.

Run on 4 Nov 2026: `python3 -I research/check_social.py <memesnapres> --speed`.

- Rows: profile m9-2h, coins with `pc.n1h` known. Fit half: scans before the middle scan time of these rows; check half: the rest.
- Signals: `speed` = `pc.n1h` at least the 70th percentile of the fit half; `people` = `pc.users1h` at least the 70th
  percentile of the fit half; `fresh` = `pc.newestMin <= 10`.
- Same fees, same one-entry-per-coin, same verdict rules as part 1.
- If fewer than 300 coins with `pc.n1h` exist on either half, the answer is "not enough data yet", not a verdict;
  if the logger read no comments at all (pump.fun blocks the runner), that is reported and the logger is taken out again.
