# Pre-registration: two Pick buy filters, judged on the real Pick buys of 26 Oct - 22 Nov 2026

Written 25 Oct 2026 around 23:15 UTC, before any of the judged buys exist. Research only: the bot, the Pick account and its rule
stay as they are. Nothing is switched on from this test without the user's yes.

## Why

On the Pick's 142 closed trades of 11-25 Oct (branch `results`, db/memepos + db/memeexit, grp "hold", 50 EUR each, after the paper
fees) these are the numbers seen so far, the reason for the test and NOT part of it:

| group | trades | per trade | won | 90 % bootstrap range |
|---|---|---|---|---|
| all | 142 | -4.96 | 39 % | -7.35 .. -2.49 |
| first buy of a coin | 91 | -4.21 | 40 % | -6.97 .. -1.26 |
| re-buy of a coin sold before | 51 | -6.30 | 37 % | -10.32 .. -2.15 |
| tier "strong" | 25 | -3.00 | 48 % | -8.92 .. +2.80 |
| tier "weak" | 84 | -5.77 | 38 % | -9.03 .. -2.32 |
| tier "risky" | 33 | -4.38 | 33 % | -7.62 .. -1.29 |

The ranges overlap: nothing is proven. Example of the pattern: on 25 Oct the Pick bought REACHY at 07:11, 07:58 and 11:53 UTC; the
Sell bot sold all three by its 30-minute drop rule at -16 % to -22 % (about -30 EUR together). memebot.HOLD_COOL_H is 0 (no pause
after a sale), and when no coin passes the gates the Pick still buys a "risky" coin (25 Oct 20:52 UTC).

## Data that is judged

Every real Pick buy (grp "hold", paperRule v3 "chart exit") whose scan time `t` is from 2026-10-26 00:00 UTC to 2026-11-22 00:00
UTC, closed by 2026-11-22 12:00 UTC, with its real booked sales. Result per trade = sum of the sales' euros minus the 50 EUR ticket
(the paper fees are already in it). Cost allowance as in PR #39: 0.75 EUR per trade (1.5 points per round trip).

## The two filters (each drops some of the same real trades; nothing is replayed)

- **F1 no quick re-buy:** drop a buy when the same coin (`addr`) had a Pick sale (exit `at`, else `t`) within the 6 hours before
  the buy's `t`.
- **F2 gates only:** drop a buy whose `tier` is "risky" or "fallback" (no coin passed every gate and the strict check).

## Decision (fixed now)

For each filter: kept = trades it keeps, dropped = trades it drops.

1. **Better than the Pick** when there are at least 20 dropped and 40 kept trades and the one-sided 95 % bootstrap lower bound of
   mean(kept) - mean(dropped) is above 0 (10,000 re-draws of each group, seed 7). Two filters: Holm at 5 % (the smaller p must be
   under 2.5 %, the other under 5 %).
2. **Worth switching on** only when 1 holds AND the kept trades also meet the PR #39 bar: at least 40 trades, mean above 0 after
   the 0.75 EUR allowance, 1 % one-sided bootstrap lower bound above 0, still above 0 without the best trade.
3. Otherwise: report the numbers, switch nothing.

Expected outcome, said now: with about 270 buys and a spread of about 17 EUR per trade, a difference of about 2 EUR per trade
(what was seen so far) is too small to prove; "not proven" is the most likely result. Trading less does lose less while every
trade loses on average; that alone is not an edge and does not count.

Numbers may be shown while they come in; the verdict is taken once, on 22 Nov, with `check_pickfilters.py`.
