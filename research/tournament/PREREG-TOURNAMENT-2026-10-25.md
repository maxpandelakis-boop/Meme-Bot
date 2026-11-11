# Pre-registration: ten bots with 100 EUR each (25 Oct 2026)

Fake money only. Written before any bot below was run on any data. Research only: no bot, account or rule changes.

## Why

The user (25 Oct, 22:28 UTC): "du gibst 10 bots 100 € und guckst was die besten Ergebnisse waren". The best of ten bots on the
months they are ranked on is usually the luckiest, not the best (research/MONTHS-2026-10-23.md: 19 of 24 walk-forward picks lost
on their unseen window). So the ten bots are fixed here, ranked on three training months, and the ranking is then judged on a whole
month none of them was ranked on.

## Data

The five windows of research/MONTHS-2026-10-23.md (branches monthsdata, monthsh2): pump.fun graduations with five-minute USD candles
of their first 48 hours. w1 25 Apr-24 May, w2 25 Jun-24 Jul, w3 10 Aug-9 Sep (training); w4 10 Sep-8 Oct (the unseen month);
w5 9-21 Oct (a second unseen check, 13 days). Every number a bot looks at is computed from the candles closed before its entry
(check_months.coin_rows' features, mc = price x 1e9, liquidity from the pool's start reserves). The entry is at the close of the
last finished candle, the path starts with the first candle wholly after the entry; in w3/w4 an entry is left out when a history2
data gap of 10 minutes or more overlaps the hour before it or the 6 hours after it (as check_months.py). A wick more than 5x beyond
the candle's close counts as the close.

## The money (the same for every bot)

- 100 EUR at the start of each window (w1, w2, w3, w4, w5 separately).
- Each buy: 10 % of the bot's money at cost (free cash plus what its open positions cost), at most the free cash; no buy under 1 EUR.
- Paper fees 1 % on the buy and 1 % on every sale (no minimum; real costs are higher, see the bar below).
- At most one buy per clock hour (the first coin of that hour through the bot's filter), and one buy per coin.
- Every position is sold by the bot's rule, even when that is after the window's end. The end balance is the cash after the last sale.

## Fills (all rules alike)

On each five-minute candle, in this order: the low at or under the stop level sells, booked at that low (never above the level);
the high at the target sells at the target; a half sale at its level on the high; then the close-based parts of a rule (the chart
exit's drop exit, the trailing stop's new best close). At the time limit, the close of the last candle by the limit.

## The ten bots

| # | bot | buys (filter, first time a coin passes it) | sells |
|---|---|---|---|
| 1 | Sell bot (the Pick's live rule since 24 Oct) | Pick gates (family P: 6-24 h after graduation, hourly, mc $100k-2M, liquidity and 24 h volume >= $15k, not -10 % in 1 h / -50 % in 6 h / -70 % in 24 h, not +200 % in 1 h / +90 % in 6 h, 24 h volume <= 8x mc) | chart exit v3: low <= -50 %; high >= 11x; once the high reached 1.5x a low 15 % under the highest high; a close 15 % under the close 30 min before; 6 h (research/chartexit/check_chartexit.py replay_np, the live pick) |
| 2 | Old Pick rule (shadow K) | Pick gates | stop -30 %, target 11x, 6 h |
| 3 | Shadow A | Pick gates | stop -20 %, target 3x, 6 h |
| 4 | Shadow B | Pick gates | no stop, target 2x, 12 h |
| 5 | Shadow C | Pick gates | half at 2x, the rest -30 % / 11x / 6 h |
| 6 | Shadow D | Pick gates | stop 30 % under the best close so far (starts at -30 %), no target, 6 h |
| 7 | Learning Pick's rule | Learning Pick's universe (hourly 1-24 h after graduation, 24 h volume >= 0.1x mc, liquidity >= $15k, mc $50k-2M; without its brain, which cannot be rebuilt for old months) | its learned rule: stop -20 %, target 2x, 2 h |
| 8 | Diamond hands | Pick gates | no stop, no target, sells 24 h after the buy |
| 9 | Rocket hunter (Radar-style, without the Radar's model) | the Radar's universe (rocket.universe: every 15 min from 30 min to 18 h, liquidity and 24 h volume >= $15k, mc $100k-5M, not -10 % in 1 h, not -50 % in 6 h) and a rocket start: +50 % or more in the last hour and the last hour holds at least a quarter of the 24 h volume | the Radar's rule A: stop -30 %, target 11x, 6 h |
| 10 | Quick flipper | Pick gates | sells at the close of the first whole candle after the buy (5-10 minutes) |

Yardsticks (not contestants): "do nothing" (100 EUR stays 100 EUR) and "the monkey": in every clock hour in which a coin passes the
Pick gates, it buys a random coin of that hour from the wide set U (hourly 1-24 h, liquidity and 24 h volume >= $15k, mc >= $50k),
not one it already bought, and sells by the old Pick rule; the same money rules; 200 monkeys, the median end balance.

## The ranking and the test

- Training score: the mean of the end balances of w1, w2, w3. Ranks 1-10 (ties: the higher mean per trade).
- The unseen month: each bot's w4 end balance and rank; w5 the same.
- The training winner HOLDS only if all of:
  1. its w4 end balance is above 100 EUR (it made money);
  2. it beats the median monkey on w4;
  3. on its w4 trades, the bar of research/PREREG-REVIEW-2026-11-04.md: at least 40 trades, mean result per trade above 0 after a
     real-cost allowance of 1.5 % of the stake, the 1 % one-sided bootstrap lower bound of that mean above 0, and still above 0
     without its best trade.
- Also reported: the Spearman rank correlation of the training ranks and the w4 ranks; where the training top 3 land on w4 and w5;
  each bot's trades, share in profit, mean per trade (% of the stake) and best trade; the end balances with 5 % and 20 % stakes
  (sensitivity only, not ranked).
- If the winner does not hold, nothing changes. If it holds, it still goes nowhere without the user's yes, and the full-month live
  review of 22 Nov (research/PREREG-REVIEW-2026-11-04.md) stays the bar for anything live.

## What I expect (written before running)

From research/MONTHS-2026-10-23.md and research/chartexit/CHARTEXIT-2026-10-24.md: every Pick-gate rule loses money per trade in
every window, the chart exit the least. So I expect every bot under 100 EUR in every window, the Sell bot near the top of the Pick-gate
bots, the quick flipper losing about 2-3 % a trade to fees and spread, and the training winner not holding on w4.

## Code

research/tournament/check_tournament.py (rows, run). No network, nothing bought.
