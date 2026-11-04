# Quick-flip test (sell after 1-10 minutes when in profit): result, 4 Nov 2026

Pre-registration: research/quickflip/PREREG-QUICKFLIP-2026-11-04.md (commit e496d9e, pushed before any score). Frozen rules:
FROZEN-2026-11-04.json (commit 9ef1ca6, before CHECK was scored). Script: check_quickflip.py. Fake money only; nothing live changed.

**Verdict: nothing holds. 0 of 8 frozen rules pass; 0 of 280 rule cells (35 rules x 4 entries x 2 monies) are above zero on the
unseen CHECK month; 0 of 35 rules are above zero on the Pick account's 100 real buys or on the Learning Pick's 197 buys.**

## Earlier coverage

No earlier test held a coin for under one hour (PR #42 / #68: 1-24 h on 5-minute candles; PR #71: 1-12 h; PR #21: 2-24 h; PR #46:
6 h). So this was new and was run, not looked up.

## Costs used

| money | ticket | fees | allowance | round trip | break-even multiple |
|---|---|---|---|---|---|
| Pick money | 50 EUR | 1 % per side, min 0.10 (memebot.paper_fee) | 0.75 EUR (1.5 pts) | ~3.5 % | 1.0356 |
| Radar money | 20 EUR | max(0.5 %, 0.81 EUR) per side (memebot.tip_net) | 0.60 EUR (3 pts) | ~11 % | 1.1157 |

The ~11 % other projects measured matches the Radar money; the Pick money is the cheap case and still loses everywhere.

## Historical (history2 one-minute bars, FIT = graduations 10 Aug - 9 Sep, CHECK = 10 Sep - 8 Oct 2026)

| entry | money | CHECK trades | frozen rule | mean EUR/trade | % of ticket | 1 % bound | holds | best rule on CHECK | rules > 0 |
|---|---|---|---|---|---|---|---|---|---|
| G0 every graduate, minute 0 | pick | 19,814 | T_1 | -1.93 | -3.9 | -2.15 | no | T_3 -1.21 | 0/35 |
| G0 | radar | 19,814 | T_1 | -2.29 | -11.5 | -2.38 | no | T_3 -2.01 | 0/35 |
| G30 every graduate, 30 min | pick | 7,737 | T_1 | -2.35 | -4.7 | -2.58 | no | T_1 -2.35 | 0/35 |
| G30 | radar | 7,737 | T_1 | -2.45 | -12.2 | -2.54 | no | T_1 -2.45 | 0/35 |
| P Pick candidates | pick | 1,570 | T_2 | -1.86 | -3.7 | -2.19 | no | T_1 -1.77 | 0/35 |
| P | radar | 1,570 | T_2 | -2.26 | -11.3 | -2.39 | no | T_1 -2.23 | 0/35 |
| R Radar candidates | pick | 2,376 | T_1 | -2.04 | -4.1 | -2.40 | no | T_1 -2.04 | 0/35 |
| R | radar | 2,376 | T_1 | -2.33 | -11.7 | -2.47 | no | T_1 -2.33 | 0/35 |

On FIT too, every one of the 35 rules lost in every cell (FIT-TABLE-2026-11-04.json); the frozen picks are simply the shortest pure
time holds, which lose about the round-trip cost and no more.

Why:
- **The price hardly moves in 1-3 minutes.** Gross multiple after 2-3 minutes (no costs): G0 1.008-1.011, G30 0.976-0.981,
  P 0.996-0.998, R 0.982-0.985 on CHECK. The costs decide the result.
- **"Sell when in profit, else wait" wins often and still loses.** The W rules sell in profit in up to 71-72 % of trades (G0,
  G30, R) and still lose 2.9-3.6 EUR per trade: the coins that never come back hit the stop and cost more than all the small wins.
- **Right after the graduation many coins collapse within minutes.** FIT, G0: by minute 5 one coin in ten is at 0.13x or less;
  the median path falls from minute 5 on (0.86x at minute 10).

## Live (the Pick account's real buys 22 Oct 16:00 UTC - 4 Nov 02:16 UTC with the shadow job's minute path)

100 buys (closed, with path). The real Sell bot on the same buys: -0.59 EUR per trade after the allowance (-58.97 in all).

| rule | mean EUR/trade | total | sold in profit | vs real Sell bot per trade |
|---|---|---|---|---|
| T_1 | -1.61 | -161.38 | 7 % | -1.02 |
| T_2 (frozen P/pick) | -1.56 | -156.15 | 14 % | -0.97 |
| T_3 | -1.58 | -158.18 | 13 % | -0.99 |
| T_5 | -1.52 | -152.17 | 21 % | -0.93 |
| W_2_20_60 | -1.68 | -167.78 | 74 % | -1.09 |
| W_3_30_60 (best of 35) | -1.44 | -143.46 | 75 % | -0.84 |

Without its single worst trade W_3_30_60 is still -92.71. After 1 / 2 / 3 minutes the median real buy stood at 1.0005 / 1.0017 /
1.0017x; only 7 / 14 / 13 % were above the Pick money's break-even (1.036x). Learning Pick (197 paths, closes only): 0 of 35 rules
above zero, frozen T_2 -1.60 per trade.

## Copying by hand

Modelled copier: buys at the close of the minute after the bot, sells at the close of the minute after the bot's sale. Results are
the same or worse (CHECK T_2: G0 -0.92, G30 -2.56, P -1.90, R -2.50; live Pick buys T_2 -1.71 vs the bot's -1.56). The model is
kind to the copier: a phone push, opening a wallet app and confirming two swaps inside a 2-3 minute window cannot be done reliably by
hand, and the bots that do trade in seconds are the ones a slower copier sells to or buys from.

## Consequence

As pre-registered: nothing passed, so no paper test account is added. The Pick account, the Sell bot and the Radar account 🚀 stay
as they are until the 22 Nov review. Do not re-run this family on the same months.
