# A chart-driven sell rule for the Pick account (24 Oct 2026)

Fake money only. Pre-registration: research/PREREG-CHARTEXIT-2026-10-24.md (pushed before any variant was run). Code:
research/chartexit/check_chartexit.py (paths, grid, test) and calib_minute.py (one-minute check). Results: result.json,
calib_minute.json. The live code is memebot.chart_hit (the scan and the minute watch), checked against the tested replay in
selftest_chartexit.py C2.

## Verdict

- **The chart exit loses less than the fixed rule, on months it was not chosen on.** Chosen on 25 Apr-9 Sep, it beat the fixed rule
  K (-30 % / 11x / 6 h) on the whole unseen month 10 Sep-8 Oct by +2.16 EUR per 50 EUR trade (95 % CI +0.46 to +3.81) and on
  9-21 Oct by +2.50 (+0.02 to +4.85). That is the pre-registered bar, and it holds with both fill models.
- **It still loses money.** -1.95 to -4.22 EUR per trade in every window. Not profitable, only less bad.
- **It costs the big hits.** Of 1,852 trades, K had 20 that ended at 3x or more; the chart exit has 2. Its whole gain comes from
  cutting the losers earlier (285 trades lost 20 EUR or more under K, 107 under the chart exit).
- **On one-minute candles (as live) the lead is smaller**: +0.83 EUR per trade on 868 coins of Aug-Oct (95 % CI -1.06 to +2.40).
- **On the 10 real Pick buys of 22-24 Oct it would have done worse** (-55.05 EUR against -2.19 for K), because it would have sold
  the one big winner (ヤギ, +53.89 under K) early. Ten trades are not a test, but they show the trade-off.

## The rule (what goes live)

On each minute candle of the position's pool, over the candles' own entry price, in this order:

1. the minute's low at -50 % or lower: stop (the floor), booked at that low;
2. the minute's high at 11x: take-profit at exactly 11x;
3. once the highest price since the entry has reached 1.5x: a low 15 % under that highest price sells (trailing stop, booked at that
   low; a minute that closes under the line right after a new high, at its close);
4. a close 15 % or more under the close 30 minutes before (the entry price in the first 30 minutes): sells at that close;
5. 6 hours after the entry: sells at that minute's price.

It was the WORST pick (the best worst-window difference to K) among 8,424 variants: hard stop 20/30/40/50 %, trailing stop
none or 15-40 % armed at 1.0-2.0x, break-even lock, stale exit, fade exits (drop, volume), 3/6/12 h. The same rule was picked
on w1-w3 and on all five windows.

## Main test (five-minute candles, "low" fill: a stop booked at the candle's low)

| window | coins | K | chart exit | difference | 95 % CI |
|---|---|---|---|---|---|
| w1 25 Apr-24 May | 348 | -6.17 | -4.22 | +1.96 | -2.02 to +4.99 |
| w2 25 Jun-24 Jul | 394 | -5.13 | -2.34 | +2.78 | +0.47 to +4.98 |
| w3 10 Aug-9 Sep | 569 | -2.81 | -1.95 | +0.86 | -1.86 to +3.03 |
| w4 10 Sep-8 Oct | 356 | -5.33 | -3.17 | +2.16 | +0.46 to +3.81 |
| w5 9-21 Oct | 185 | -6.47 | -3.97 | +2.50 | +0.02 to +4.85 |

EUR per 50 EUR trade after the paper fees. K on closes only reproduces research/MONTHS-2026-10-23.md exactly (-4.64, -3.95,
-2.50, -4.34, -4.85); on lows (as the Pick sells since 24 Oct 13:00) K is 0.3-1.6 EUR worse, because wicks now stop it out.

"level" fill (a stop booked at its level), the same rule against K: +1.01, +2.34, +0.39, +2.02 (one-sided 5 % bound +0.68), +2.25
(bound +0.14).

Walk-forward (fit on the windows before, judge on the next): WORST +1.15 (w2), +0.13 (w3), +2.16 (w4), +2.50 (w5);
MEAN +1.15, 0.00, +1.96, +3.84. None of the eight steps lost against K.

How common a better exit is: 493 chart-driven variants beat K in every window, 80 % of them beat it pooled. K is a poor exit
for these coins; the chart exit is the best of many that are better, not a lucky one-off.

## One-minute check (w3/w4, history2's minute bars)

868 coins whose 6 hours lie inside the first 25 hours: K -2.65, chart exit -1.82 (difference +0.83, CI -1.06 to +2.40); on the
same coins' five-minute candles +1.27. With the "level" fill the minute lead shrinks to +0.34 (w3 slightly negative). Exits on
minute candles: 6 h limit 382, drop 380, trail 67, floor 39. The live code (memebot.chart_hit) gives the same result as this
replay on 493 of 494 coins checked (mean -1.47 against -1.44).

## The trade-off

| | K | chart exit |
|---|---|---|
| mean per trade (1,852) | -4.78 | -2.90 |
| in profit | 34.6 % | 35.6 % |
| ended at 2x or more | 53 | 17 |
| ended at 3x or more | 20 | 2 |
| lost 20 EUR or more | 285 | 107 |
| best 2 % of trades, sum | 5,273 | 2,450 |

On the trades where K made 20 EUR or more (157), the chart exit made 21.24 on average against K's 59.90. Exploratory, not
pre-registered: no chart variant that keeps at least 80 % of K's 3x trades beats K in every window (0 of 8,424). Losing less and
catching big winners pull in opposite directions here.

## Real Pick buys (sanity check, not a test)

The 10 Pick buys of 22-24 Oct with a 12 h minute path (db/memeshadow), replayed: K -2.19 EUR, chart exit -55.05. ヤギ K +53.89 /
chart exit -9.02, McRib +15.65 / -8.44 (both sold by the drop rule on a dip); the three K stops (-23 to -24) became -8 to -11.

## What changes live

- The Pick sells by this rule from the first scan after the merge (memebot.PAPER_RULE v3). That scan restarts the Pick account:
  open positions of the fixed rule are closed at its price ("reset"), the account counts from it.
- The fixed rule keeps running as shadow rule K on the same buys (shadow.py), next to X (the chart exit replayed the same way),
  so the 4 Nov and 22 Nov reviews can compare them on the same trades.
- The Radar account and the Learning Pick are unchanged (they keep memebot.HOLD_STOP / HOLD_TP / HOLD_MAX_H).
