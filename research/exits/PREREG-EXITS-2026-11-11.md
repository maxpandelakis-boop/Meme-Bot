# Pre-registration: do other sell rules make the Trencher desks profitable? (fake money only)

Written 2026-11-11 before any variant below was run. Maxim (project chat, 11 Nov): "mach jetzt alles dass das system perfekt",
and: "testest du auch richtig, oder liegt es daran, dass wir die falschen Tests machen und Sachen übersehen?"

## Hypothesis

A sell rule other than the video's (stop -8% until 2x, entry back at 2x, rest trailing 10%) makes the desk's trades profitable
after FOMO's fees: a wider or no stop, partial or full take-profits, another trail, a time limit.
Prior, written down: unlikely. Earlier work: research/DESK-2026-11-11.md (video rule -2.34 per 20), research/chartexit (8,424
exits on 1,852 graduated coins: the best loses less, still loses), research/scout/SCOUT-2026-11-11.md (no coin rule earns).

## Data

origin/results at 17be2beee: db/memerec (the Meme-Bot's tips: established trending coins, the nearest stored paths to the "Große"
desk's Scout picks) and db/memeyoung (listed launches under an hour old: nearest to the "Frisch" desk). Per tip one path relative
to the entry price, from the entry minute (tpFrom) on: the 1 h result's one-minute candles, then the 24 h result's 15-minute
candles for the minutes after them. Tips need the 24 h result with cv >= 2, tpFrom and a path. Neither set is the desks' own picks
(those have a few live trades only); this measures sell rules on real meme coin paths of the same kind.

## The rules: 480 variants

On each candle close, in this order (closes only, as the live desk sees one price a minute; a wick is no price):

| part | values |
|---|---|
| stop | -8%, -15%, -25%, -40%, none: a close at or under the level sells everything left at that close |
| take-profit | none; entry back at 2x (sell 1/2 of the position at 2.0, the video); half at 1.5x; half at 2x; all at 1.2x; all at 1.5x; all at 2x; all at 3x. Filled at the level, not above |
| trail | none, 10%, 20%, 30% under the highest close since the entry; armed after the partial sale for the three partial take-profits, from the entry otherwise; sells at that close |
| time limit | 1 h, 4 h, 24 h after the entry: the rest is sold at the last close by then |

The video rule D (-8%, entry back at 2x, trail 10%, 24 h) and plain holding (none, none, none, 24 h) are among them.

## Money

Ticket 8.00 $ (40% of the desk's 20 $). FOMO's Solana fee on every buy and every sale, on that sale's amount: under 5 $ flat
0.10; 5 to 47.50 $ 2%; 47.50 to 190 $ flat 0.95; from 190 $ 0.5%. Slippage a side: 0.5% (memerec), 1.0% (memeyoung).
Also shown: ticket 20 $, and the same trades with no fee and no slippage (what the costs take).

## Split, choice, pass bar

- By tip day (UTC): the older two thirds of the days are for choosing, the newest third is the holdout, read once.
  Disclosed: the DESK study already read this holdout for rule D, and printed whole-sample averages of hold, -30%/+1000% and
  trailing 20% at other fees. No other variant has been seen on it.
- Two picks per data set, chosen on the older days only: MEAN (highest average per trade) and ROBUST (the older days cut into
  three blocks of days; the highest worst-block average). Ties: fewer parts.
- PROFIT (the claim Maxim asked for) only if, on the holdout, the pick's average per trade is above 0, its 95% bootstrap interval
  by day (2000 resamples) lies above 0, and it stays above 0 without its best trade and with one tip per coin (the first).
- LESS BAD only if the paired difference to rule D on the holdout has its interval above 0.
- Shown in any case: the share of days in profit, how the trades ended, the ten best trades of each pick (dead-pool prints), and
  a pessimistic fill for the picks (on 15-minute candles a stop or trail triggers on the low and fills at the low).

## What follows

- PROFIT on memerec: the rule is proposed for the "Große" paper desk (paper money only). PROFIT on memeyoung alone (9 days) is a
  lead to re-test, not a result.
- LESS BAD only: reported as that; Maxim decides whether the paper desk should switch.
- Neither: said plainly. No variant is re-tuned on the holdout.

## Method check (asked by Maxim)

research/exits/desk_replay.py (workflow exit-check.yml): the real trades of both 24/7 desks replayed on GeckoTerminal one-minute
candles with the backtest's fill rules; compared sale by sale. Fees: trencher/sim.js against FOMO's table and the two screenshots.
