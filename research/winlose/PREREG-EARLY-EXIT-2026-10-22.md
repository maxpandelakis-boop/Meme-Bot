# Pre-registration: the rocket hunter, earlier entry and its own exit (22 Oct 2026, fake money only)

Written before any number of these tests was compared with an outcome (the early rows were still being built by early_grid.py).
The user asked (22 Oct, about 12:09 UTC): can the rocket hunter buy earlier than 30 minutes after the graduation, and does another
exit than rule A (-30% stop, 11x target, 6 h) do better for its buys? Only the rocket hunter's paper account can change. The Pick
account and its sell rule are not touched by anything here.

Data: history2 (Slink21 Pumpfun dataset, CC BY 4.0), graduations 10 Aug to 8 Oct 2026, one-minute bars of the first 25 hours
(branch chartbars) and 55 hours (chartbars55), the wallet pairs (wallets), BTC/SOL hourly candles (marketctx). The holdout of the
winner/loser study (from 25 Sep) has been seen for this model (addendum 2 B), so here the second half of the weeks is called
"late weeks", not a holdout.

## Test 1: an earlier first check (research/winlose/early_entry.py, rows from early_grid.py)
Rows: every coin at 5, 10, 15, 20, 25 minutes and every 15 minutes from 30 minutes to 18 hours after its graduation, with the
universe filters of grid.py (liquidity and 24 h volume at least $15k, market cap $100k to $5M, not -10% in 1 h, not -50% in 6 h,
no recorder outage in the hour before or the 6 h after). The live watcher checks a coin every 15 minutes from its first age, so:

| variant | checks (minutes after the graduation) |
|---|---|
| V30 (today) | 30, 45, 60, ... 1080 |
| V20 | 20, then V30 |
| V15 | 15, then V30 |
| V10 | 10, 25, then V30 |
| V5 | 5, 20, then V30 |

Model: the live model's 60 numbers (unchanged list) and parameters, target "the price reaches 10x within 6 h", trained per variant
on that variant's rows. Walk-forward as rocket_model.py: every week from 24 Aug to 8 Oct, each week trained only on coins that
graduated two days or more before it. Cut: the top 0.5% of the training rows' scores (the live tier); one buy per coin, at the
first check that reaches the cut. Outcome: rule A from that minute, per 20 after fees (memebot.tip_net), not clipped.
Five LightGBM seeds (7, 11, 23, 42, 99): the same model already swings from +3 to +10 per 20 across seeds.

Reported per variant and seed: coins, per 20 with the bootstrap 95% range, in profit of 10, 10x rate (the price reached 10x within
6 h), 3x, to zero, per week, and the share of filter_search.simulate's 10,000 runs in profit. Top 1% and 2% for information.

**A variant holds** when all of these are true: (a) its seed-mean per 20 is above V30's; (b) it beats V30 in at least 4 of the 5
seeds; (c) its seed-mean beats V30's in the early weeks (starting before 25 Sep) and in the late weeks (from 25 Sep); (d) its
seed-mean share of the 10,000 runs in profit is not below V30's; (e) its seed-mean per 20 is above 0. Several hold: the one with
the best seed-mean per 20. None holds: the hunter keeps its first check at 30 minutes.
If one holds, the live model is exported again with that variant's rows (seed 7, as today) and rocket.py's first check moves to
that age; nothing else changes.

## Test 2: the rocket buys' own exit (research/winlose/rocket_exits.py)
Picks: the walk-forward picks (seed 7, the live model's seed) of the entry variant that is live after test 1, at the top 0.5%
(live), 1% and 2%. Path: the one-minute bars of the first 55 hours from the entry minute; the buy price is the close of the minute
before (as grid.py). Fills: a stop sells at the low of the minute that crosses it, a target at its level; a stop and a target in
the same minute count as the stop; a trailing stop follows the highest high up to the minute before; at the time limit the last
close; a pool without more bars keeps its last price.

| family | rules |
|---|---|
| F fixed | stop none/-30/-50/-70% x target 3x/5x/11x/20x/none x time limit 2/6/12/24 h = 80 (rule A = -30%, 11x, 6 h) |
| T trailing | trail 30/40/50/60% below the highest price x active at once/from 2x/from 3x (before: -30% stop) x 6/24 h = 24, no target |
| P partial | sell 1/2 or 1/3 at 2x/3x/5x (before: -30% stop); the rest under rule A (from the buy) or a 40/50% trail with 6/24 h = 30 |

134 rules. Per 20 after fees, each sale paying its own fee (0.5%, at least 0.81), not clipped. The 10,000 runs use the blended
multiple without the 11x cap. Early weeks (before 25 Sep) choose, late weeks check.

**THE choice**: the best early-weeks average per 20 at the top 2% (most coins) among the rules that beat rule A in the early weeks
at all three tiers. **It holds** when (a) it beats rule A in the late weeks at the top 0.5% and at the top 2%; (b) the per-coin
difference to rule A at the top 2% in the late weeks has a bootstrap 95% lower bound above 0; (c) over all weeks at the top 0.5%,
its share of the 10,000 runs in profit is not below rule A's. Also reported: the share of picks that sold at least a part at 10x
or more, coins, per 20, in profit of 10, for every tier and both halves.
If it holds, every rocket buy from then on carries that rule (stored with the position; positions bought before keep rule A) and
the app names it. If not, rule A stays.

## Live checks after a change
The paper account's own live results are the forward test; the fixed check on 4 Nov 2026 (radar account against pick account)
reports them with the coin count.

## Addendum, 22 Oct ~12:45 UTC: a data error in the outcomes (written before the corrected numbers were run)
Test 1 ran (V15 passed all five checks, V5/V10/V20 did not). Test 2's replay of rule A on the 55 h bars then disagreed with the
grid on 6 of 993 picks, among them the two biggest winners. Cause: features.dense forward-fills each minute's HIGH and LOW into the
following minutes without a trade, so a dead pool's last wick counts again in every quiet minute after it (one coin: last trade
minute with a high 238x its close, then no trade; the grid booked 11x on every entry after it). The live code never did this
(rocket.dense and Book.update use the close for a minute without a trade). wick_check.py recomputes every grid row's outcome and
10x label the live way: 55 rows of 3 coins lose the 10x label, rule A's result changes on 182 rows.
Both tests are therefore run again with the corrected outcome and label (FIX=1; the model trained on the corrected label), with the
same variants, seeds, rules and pass checks as above. **The corrected run decides**; the first run is reported next to it. The
chart numbers keep features.dense as it is (the trees were trained on them; the live code is checked against them by selftest R1).
