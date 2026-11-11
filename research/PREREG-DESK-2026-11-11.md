# Pre-registration: the Trading Desk's sell rules on stored candle paths (fake money only)

Written 2026-11-11 before any replay of this rule was run. The user asked (thread "Trench-Bot", decision card of 2026-11-11):
"Erst prüfen, ob er Gewinn macht", then let the desk run around the clock.

## The rule (fixed by the user's second video, nothing is tuned)

Desk rule D, on minute closes from the entry minute (`tpFrom`) on, filled the way `research/check_exits.py` fills:

1. Before 2x ever printed: a close at or below 0.92 of the entry sells everything at min(0.92, close) (hard stop -8%).
2. The first close at or above 2.0: sells the share 1/2 of the position at 2.0 (the entry comes back); the rest stays.
3. After that: the rest follows the highest close since the entry; a close at or below 0.90 of that high sells the rest at
   min(0.90 x high, close) (trailing 10%).
4. No exit in the window: the rest is sold at the window's end multiple.

Each sale pays its own fee.

## Data

`git archive origin/results db/memerec db/memeyoung`: every result with a candle path (`cv` >= 2, `tpFrom` set), as in
`research/check_exits.py`. memerec = the bot's tips, memeyoung = listed new launches under an hour old; windows 1 h and 24 h.
The Trencher's Scout buys coins from trending lists, not these tips: this measures what the SELL rules do on real meme coin
paths, not the Scout's coin choice.

## Metric and pass bar

- Main metric: EUR per ticket after fees, ticket 20, fee 0.5% with a 0.81 minimum per sale (project standard).
  Also shown: the desk's own size, ticket 8 with a 0.50 minimum (FOMO, the Trencher's sim).
- Primary cell: memerec, 24 h window.
- 95% bootstrap interval by day (tip day, UTC), 2000 resamples; share of days positive.
- Baselines on the same tips: hold to the window end; the live paper rule (-30% / +1000%); trailing 20% (best older rule
  in check_exits). Paired difference D minus each baseline, interval by day.
- "Brings profit" (PASS) only if, in the primary cell: the mean of D is above 0 AND its interval lies above 0 AND the newest
  third of tip days (the holdout, read once) also has a mean above 0.
- "Better than holding" only if the paired difference's interval lies above 0.
- Trap checks reported in any case: without the single best tip; by DEX; by day; rows vs coins (one tip per coin, the first).

## What happens with the answer

- PASS: the 24/7 desk runs with rule D as it is.
- FAIL: the user is told plainly that the desk's sell rules lose money on these paths; the 24/7 desk is still built (the user
  chose it) and shows that result. No other rule is picked from these same numbers and called a winner.
