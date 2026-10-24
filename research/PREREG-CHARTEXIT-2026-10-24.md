# Pre-registration: a chart-driven sell rule for the Pick account (24 Oct 2026)

Fake money only. Written before any variant below was run on any data.

## Why

The user asked for a Pick exit that "analyses the live chart and sells when it thinks it is smartest" and, told that a new Pick
sell rule restarts the Pick account and that the AI exit of PR #21 lost, said "Okay dann Bau das" (24 Oct, 15:59 UTC). So a
chart-driven exit WILL be built and switched on. This test decides WHICH one, and says honestly whether it beats the fixed rule
K (-30 % / 11x / 6 h) on months it was not chosen on.

## Data

The Pick-type coins of research/MONTHS-2026-10-23.md (family P: the Pick's gates as far as candles hold them, whole hours 6-24 h
after graduation, one entry per coin: its first hour through the gates), five windows w1 25 Apr-24 May, w2 25 Jun-24 Jul,
w3 10 Aug-9 Sep, w4 10 Sep-8 Oct, w5 9-21 Oct. Five-minute USD candles (branches monthsdata, monthsh2), entry at the close of the
last finished candle, the path starts with the first candle wholly after the entry (as check_months.py). 50 EUR ticket, the
paper fees (1 % a side, at least 0.10).

A sanity check, not a test: the real Pick buys with a 12 h one-minute path in db/memeshadow (11 at the time of writing), replayed
with the live code itself.

## The exits (8,424 variants, K among them)

Every variant keeps a hard stop and the 11x take-profit. On each candle, in this order:

1. the candle's low at or under the stop level from the candles before it: sold (the level: the hard stop, raised by the trail and
   the break-even lock once they are armed);
2. its high at 11x: sold at 11x;
3. the running high takes the candle's high; the trail and the break-even lock arm when the high reaches their level;
4. the close at or under the (new) level: sold;
5. at the close: the stale exit, the fade exit, then the time limit.

A wick more than 5x beyond the candle's close counts as the close (memebot.hold_wicks).

| part | values |
|---|---|
| hard stop | -20 %, -30 %, -40 %, -50 % |
| trailing stop under the running high | none, or 15 / 20 / 25 / 30 / 40 % under it, armed once the high reached 1.0 / 1.15 / 1.3 / 1.5 / 2.0x the entry |
| break-even lock | none, or the stop rises to 1.03x (fees covered) once the high reached 1.3x / 1.6x |
| stale exit | none, or sell at 2 h when the high never reached 1.10x, or at 3 h when it never reached 1.20x |
| fade exit | none; "drop": the close 15 % or more under the close 30 min before; "vol": from 1 h on, the last hour's volume under a quarter of the hour before the entry |
| time limit | 3, 6, 12 h (24 h left out: the minute watch fetches every open position every minute and GeckoTerminal allows about 30 calls a minute, shared with the Radar) |

4 x 26 x 3 x 3 x 3 x 3 = 8,424. K = -30 %, no trail, no lock, no stale, no fade, 6 h. A variant is "chart-driven" when it uses at
least one of trail, lock, stale, fade; only those can be chosen.

Fills. "low" (the main one, like the live Pick books a stop at the minute's low): a stop seen on the low is booked at that low
(never above the level); "level": at the level (at the open when the candle opened under it). A sale seen on the close is booked
at the close ("low") or at the level ("level"). Five-minute lows are lower than the one-minute low of the minute that crossed, so
"low" is pessimistic for every rule that stops often.

## Choosing and testing

Per coin: the variant's money minus K's money on the same coin (paired).

- Picker WORST (main): the chart-driven variant with the best worst-window mean difference to K over the fit windows. Picker MEAN
  (second): the best pooled mean difference. Ties: fewer parts, then the earlier variant.
- Walk-forward: step s = 2..5 fits on w1..w(s-1) and judges the pick on ws (mean, difference to K, 95 % paired bootstrap).
- The user's bar (a rule counts only if it holds on a whole unseen month): the pick fitted on w1-w3 HOLDS if on w4 its mean
  difference to K is above 0 with the 5 % one-sided bootstrap bound above 0, and on w5 the difference is not negative, with
  both fills.
- What goes live (the user decided to build it either way): the WORST pick fitted on all five windows, with the "low" fill. If
  the w4 test above fails, it goes live anyway as the least bad chart-driven exit, and the report says so in plain words.
- Profitable is a separate question: the mean per trade above 0. Not expected (K loses 2.50-4.85 EUR per trade in every window).
