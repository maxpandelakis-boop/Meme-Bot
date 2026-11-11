# Ten bots with 100 EUR each (25 Oct 2026)

Fake money only, research only: no bot, account or rule changed. Pre-registration: research/tournament/PREREG-TOURNAMENT-2026-10-25.md
(pushed in 2d91e67 before any run). Code: research/tournament/check_tournament.py (rows, run). Result: result.json.

## Verdict

- **No bot made money. Not one of the 50 bot-months (10 bots x 5 windows) ended above 100 EUR.**
- **The training winner is the quick flipper** (sells 5-10 minutes after the buy): 44.53 EUR on average over the three training
  months, 39.51 EUR on the unseen month w4, 95.20 EUR on w5. It wins because it is hardly in the market: it loses about the fees
  (2 % a round trip) and a little more, -2.6 % a trade. **It does not hold** (pre-registered bar): w4 under 100 EUR, -5.03 % a trade
  after the real-cost allowance, 1 % bootstrap bound -6.81 %.
- **Second everywhere: the Sell bot, the Pick's live rule since 24 Oct** (15.17 / 17.50 / 31.80 EUR). Of the bots that really hold a
  coin, it loses least, on the training months and on both unseen windows. That matches research/chartexit (PR #46).
- **The ranking held on the unseen windows** (Spearman 0.94 on w4 and w5; training top 3 = w4 ranks 1, 2, 4 and w5 ranks 1, 2, 3).
  It is not luck, but what it mostly ranks is how quickly a bot gets out. On every Pick-gate coin (no 100 EUR account, each coin
  once), mean per trade over the training months and the median time in the coin: flipper -2.6 % (8 min), Sell bot -5.7 % (2.2 h),
  shadow B -7.8 % (12 h, the one exception: no stop, and 2x is often reached), K -9.4 %, A -9.5 %, C -9.5 % (about 6 h), D -11.1 %
  (4 h), diamond hands -32.2 % (24 h). On young coins the Learning Pick's rule (-16.5 %) and the rocket hunter (-31.4 %) lose a lot
  although they are out within 15-25 minutes on median: those coins crash.
- 8 of 10 bots ran down to the 10 EUR floor (where a 10 % stake is under 1 EUR and nothing more is bought) in every training month,
  in 2 to 31 days, and ended about where the random monkey ended (median 9.2-9.5 EUR). The rocket hunter was broke after
  2-6 days every month (-15 % to -67 % a trade: young coins that went +50 % in an hour mostly crash).

## The table (end balance in EUR from 100 EUR; mean result per trade in %)

| train rank | bot | w1 | w2 | w3 | training mean | w4 (unseen) | w4 rank | w4 per trade | w5 | w5 rank |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Quick flipper | 50.39 | 41.29 | 41.90 | 44.53 | 39.51 | 1 | -3.53 % | 95.20 | 1 |
| 2 | Sell bot (Pick live) | 9.94 | 10.68 | 24.89 | 15.17 | 17.50 | 2 | -5.78 % | 31.80 | 2 |
| 3 | Shadow A (-20 % / 3x / 6 h) | 9.97 | 9.89 | 9.98 | 9.95 | 9.63 | 4 | -8.76 % | 25.18 | 3 |
| 4 | Shadow C (half at 2x) | 9.96 | 9.77 | 9.95 | 9.89 | 9.49 | 5 | -8.20 % | 22.50 | 4 |
| 5 | Learning Pick's rule | 9.73 | 9.56 | 9.80 | 9.70 | 9.71 | 3 | -31.06 % | 9.86 | 7 |
| 6 | Old Pick rule K | 9.70 | 9.37 | 9.93 | 9.67 | 9.48 | 6 | -8.78 % | 21.79 | 5 |
| 7 | Rocket hunter | 9.23 | 9.75 | 9.68 | 9.55 | 9.02 | 8 | -67.24 % | 9.37 | 8 |
| 8 | Shadow D (trailing 30 %) | 9.56 | 8.98 | 9.37 | 9.30 | 9.48 | 7 | -9.26 % | 20.53 | 6 |
| 9 | Shadow B (no stop, 2x, 12 h) | 7.56 | 6.73 | 9.30 | 7.86 | 8.61 | 9 | -16.08 % | 6.61 | 9 |
| 10 | Diamond hands (24 h) | 6.55 | 5.34 | 5.75 | 5.88 | 4.48 | 10 | -42.35 % | 6.03 | 10 |
| - | the monkey (median of 200) | 9.52 | 9.49 | 9.17 | 9.39 | 8.89 | - | -39.6 % | 9.44 | - |
| - | do nothing | 100 | 100 | 100 | 100 | 100 | - | 0 | 100 | - |

Ranks 3-8 sit at the 10 EUR floor, so their order among themselves says little (the mean per trade says more; its rank correlation
training vs w4 is 0.85, added after the run). With 5 % stakes (floor 20 EUR) the order is the same at the top: flipper 71.4 / 64.8 /
65.0 / 63.2 / 97.7, Sell bot 25.8 / 33.8 / 52.1 / 44.6 / 57.7, everyone else 13-53.

## The check

The Pick-type coins and the replay of K and the chart exit reproduce research/chartexit/result.json exactly (coins 348 / 394 / 569 /
356 / 185; K -6.17 / -5.13 / -2.81 / -5.33 / -6.47 EUR per 50 EUR trade; chart exit -4.22 / -2.34 / -1.95 / -3.17 / -3.97), so the
Pick-gate bots are the coins and fills of PRs #42 and #46.

## Notes

- Each coin is a candidate once (its first pass through a bot's filter); a coin that came when the hour's buy was already taken is
  not bought later. One buy per clock hour, as an hourly scan.
- The Learning Pick bot has its universe and its sell rule, not its brain (which cannot be rebuilt for old months); the rocket hunter
  has the Radar's universe and rule A, not its model. They say how the rules do on plain coins of that kind, not how the live bots do.
- Fees: 1 % a side, no minimum. Real costs are higher (slippage, priority fees), which the bar's 1.5 % allowance stands for; the
  flipper, which pays them most often, is hurt most by them.
- "Brokenness" (brokeAfterDays in result.json) was added after the run: the first moment a bot's money at cost was under 10 EUR.

## What it means for the bots

Nothing changes. The two things the tournament adds: the live Sell bot is the least bad of the real rules on unseen months as well,
and in general the sooner a bot gets out of these coins and the less often it trades, the less it loses (shadow B is the one
exception). It does not show
a way to make money: even the flipper, in a coin for minutes, loses after its fees in every window.
