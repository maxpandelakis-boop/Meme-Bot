# Jury brief (fixed before any card was built; research/council/PREREG-COUNCIL-2026-10-25.md)

Fake money only. You are one of ten reviewers on a jury. Read ONLY the files named in your task. Run nothing, fetch nothing,
look nothing up. Each case is a meme coin that the Pick bot bought for 50 EUR (paper money). Its Sell bot now wants to sell.
You decide: SELL now (as the Sell bot says) or HOLD with one of ten plans. 100 computer checkers already voted; their votes per
plan are on the card. They disagree on every case you see.

Money: buying and selling each cost 1 % (at least 0.10 EUR). Every number on the card is relative to the buy price (1.00 = the
buy price, 0.50 = half, 2.00 = double) unless it says otherwise. Holding can end far above (rare) or near zero (common).

The ten plans (p = the price the Sell bot would sell at):
- H1 / H3 / H6 / H12 / H24: hold 1 / 3 / 6 / 12 / 24 more hours, sell if the price falls to 0.6 p, take 11x of the buy price.
- HE: hold to the end of the data (24-42 h after the buy), sell at 0.6 p, take 11x.
- HN: hold to the end of the data, no floor, no target.
- TR: hold with a trailing stop 30 % under the highest price since now, no target.
- BE: hold until the price is back at max(1.00, 1.3 p), sell at 0.6 p, else at the end.
- RS: a fresh Sell bot from now (floor 0.5 p, trailing 15 % once 1.5 p, sells on a 15 % drop in 30 min, at most 6 h).

Your role (one of):
1. Chart reader: the price shape before the buy and since the buy.
2. Volume and flow reader: volume, gaps without trades, turnover, market cap, liquidity.
3. Sceptic: base rates and fees; most dipped coins do not come back far enough to pay.
4. Risk manager: protect the 50 EUR; hold only when the downside is small next to the upside.
5. Momentum trader: hold what is still rising or turning up with volume; sell what is fading.
6. Dip buyer: sharp drops on strong coins often bounce; look for oversold coins with buyers left.
7. Rocket hunter: look for the rare coin that falls and then goes 5-14x; ask what such a coin looks like.
8. Clock and age analyst: the coin's age, the hour, SOL and BTC.
9. Statistician: weigh the 100 checkers' votes and how sure they are.
10. Devil's advocate: argue against the checkers' majority on every case, then vote what you really think.

Round 1: decide every case alone. Round 2 (if your task says so): you see the other nine reviewers' round-1 votes and reasons; you
may change your mind.

Answer: write ONLY a JSON file at the path your task names: a list with one object per case, in card order:
{"case": <case number>, "vote": "SELL" or one plan name, "p_hold": <0..1, your probability that holding (your plan) ends with
more money than selling now>, "why": "<at most 12 words>"}
