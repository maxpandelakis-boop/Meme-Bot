# Rocket separator and rocket-only buys: results (26 Oct 2026)

Fake money only. Research only: nothing here is switched on, no bot, account or rule changes. The plan and the bar were pushed
before any outcome was split by the new facts (research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md, commit 94c4dec; amendment 1
in 66958ab). Result files: research/rocketsep/results/. German report for the user:
https://claude.ai/artifact/DH7QnMg7reJTKizLJrMQH2. All money is per 50-EUR buy, after the paper fees; "after cost" also
takes off the 0.75 EUR real-cost allowance.

## Verdict

Nothing holds. No buy rule, hold rule, council or jury passes the pre-registered bar on the unseen month (w4), and none of the
family-A candidates is positive on w5 either. The facts the earlier studies lacked (holders, trade flow, wallets, creator
launches, the rocket study's launch and picture facts) do separate rockets from zeros well when both are known (AUC 0.70-0.96),
and the buy models do raise the rocket share 2-5x. But a profitable rocket-only rule needs the rocket share 5-30x above the
base, and a profitable hold needs a perfect separator plus a top exit in hindsight. Even the ceiling is thin: a perfect
separator on the Pick's sales with a realistic hold plan lifts -2.90 to +0.78/+0.84 EUR per trade, about zero after the
allowance.

The best rules in hindsight make +120 to +415 EUR per trade on 40-54 in-sample trades, each carried by one or two coins, and lose
8-39 EUR per trade on the unseen month.

## Data (how many coins each result rests on)

| What | Count |
|---|---|
| Buys (all roles, 5 windows, PR #53 build) | 61,909 buys from the 71,978 graduated coins of the five windows; w1 9,708 / w2 10,274 / w3 20,720 / w4 15,090 / w5 6,117 |
| Pick buys with the Sell bot sale (frame A, role P) | 1,852 (w4 356, w5 185) |
| Learning Pick buys with its sale (frame B, role L) | 8,747 (w4 1,942, w5 914) |
| Buys with holder, flow and wallet facts (family B, w3/w4 only) | 35,810 (57.8 %) |
| Wallet first buys used for the wallet facts | 19,950,348 wallet-coin pairs over 50,930 coins |
| Launches (pump.fun, w3 + w4) | 1,561,122 (821,715 + 739,407); graduated 42,568; with a price path 35,273 |
| Full rockets among the launches (graduated, then 10x within 24 h) | 407 (210 + 197) = 2.6 per 10,000 launches |
| Rule-plan pairs searched for the best rule | 25,544-137,416 per group with 40+ in-sample trades |

## Part 1: the ceiling

Hold side (what a perfect separator at the sale would be worth):

| Frame | Buys | Rockets after the sale | Rule mean | Perfect + H24 | Perfect + hold to end | Perfect + best exit within 24 h |
|---|---|---|---|---|---|---|
| A Pick, Sell bot | 1,852 | 21 (11.3 per 1,000) | -2.90 | +0.78 | +0.84 | +6.09 |
| B Learning Pick, -20 %/2x/2h | 8,747 | 217 (24.8 per 1,000) | -8.91 | -2.14 | -2.47 | +18.29 |

On w4 alone frame A: rule -3.17, perfect + H24 +1.54, perfect + best exit +5.27.

Buy side (what share of rockets a rocket-only buyer needs to break even): Pick role base 1.11 % rockets, break-even 5.59 % with
hold-to-end and 5.43 % with R24 (-50 % floor, 10x, 24 h), 11.54 % with the Sell bot; wide role A base 1.69 %, break-even 7.66 %
(R24) and 9.48 % (hold to end); Learning-Pick role base 2.48 %, break-even 7.39 % (R24). A rocket held to the end averages
+381 EUR, a non-rocket -21.77 EUR.

## Part 0: what rockets have in common

Every launch of w3/w4 (1.56 million): the rate of full rockets per 10,000 launches by fact (w3 / w4; base 2.6):

| Fact | Rate per 10k | Ratio vs the rest |
|---|---|---|
| Creator's first launch in 30 days | 3.8 / 3.9 | 1.9 / 2.6 |
| Creator with 3+ graduations in 30 days | | 2.2 / 2.1 |
| X profile or community link | | 2.1 / 1.7 |
| Two links | | 1.7 / 2.5 |
| Person photo as picture | | 0.27 / 0.41 |

A LightGBM on all launch facts, fit on w3 and judged on w4: AUC 0.681. Top 0.1 % (739 launches) holds 3 rockets (40.6 per
10,000, 15x the base); top 1 % (7,394) holds 11; top 5 % holds 24 of 197. No launch fact gives a buyable share: the best slice
is 1 rocket in about 250.

At the Pick's sale (frame A), rockets-after-sale against zeros (472 vs 8,652 in w1-w3; 134 vs 3,833 in w4), AUC in-sample /
w4: the price at the sale 0.94/0.96 (rockets were sold at 1.2x, zeros at 0.00x: a coin that already rugged does not come back),
wallets so far 0.83/0.86 (median 1,515 vs 84), top first-buy share 0.19/0.18 (lower for rockets), wallets' prior log return
0.74/0.81, bonding-curve minutes 0.73/0.80 (median 3.6 vs 0 minutes), SOL from new wallets in 60 min 0.71/0.79. These separate
the two extremes; they do not separate rockets from the large middle that neither rockets nor dies, which is where the money is
decided.

## Part 2: buy only rocket-like coins

Models trained on rocket against zero (bRZ) and on rocket against the rest (bR), test AUC: family A w4 0.75-0.77, w5 0.59-0.60;
family B w4 0.74. Family-A models fit on GeckoTerminal months (w1/w2) transfer badly to history2 (w3 AUC 0.42-0.47).

Chosen candidates on the unseen month (w4), after cost:

| Family / frame | Trades | Mean | Rocket share (base) | 1 % bound | Without best | w5 | Holds |
|---|---|---|---|---|---|---|---|
| A / Pick (bR, top 20 %, K) | 30 | +3.58 | 7.1 % (1.5 %) | -12.4 | -108.61 | 8 trades, -3.50 | no (n < 40) |
| A / Learning Pick | 372 | -4.86 | 2.2 % (2.1 %) | -7.58 | | 177, -6.25 | no |
| A / wide | 648 | -10.41 | 2.7 % (1.3 %) | -15.18 | | 313, -13.19 | no |
| B / Pick | no candidate (fewer than 20 choose-window trades) | | | | | | no |
| B / Learning Pick | 138 | -5.42 | 4.7 % | -10.68 | | | no |
| B / wide | 166 | -6.84 | 5.2 % (1.3 %) | -11.41 | | | no |

Among all 80-160 candidates per frame and family with 40+ trades, even picked in hindsight on w4, none is positive after cost
(best: -0.66 to -3.69).

## Part 3a: hold-through-dip separators

AUC 0.70-0.84 on w4. Chosen holds: family A frame A 7 holds, -0.94 per trade against the Sell bot; frame A family B 41 holds,
-0.19; frame B family A 0 holds; frame B family B 315 holds, -3.86. Best in hindsight on w4: frame A +0.54 (break-even plan,
18 holds, 0 rockets), frame B +0.03 (hold to end, 56 holds, 5 of 41 rockets). All fail.

## Part 3b: the councils (100 and 130 checkers)

| Council | Frame | Chosen | w4 holds | vs rule | Level-fill vs rule | Bar | Holds |
|---|---|---|---|---|---|---|---|
| A (100) | A Pick | chair, gain > 10 | 1 | +0.14 | +0.14 | no (1 hold) | no |
| A (100) | B Learning Pick | 20 % of round 1 | 1,012 | +0.72 (w5 +1.01) | -1.39 (w5 -0.97) | paired yes | no |
| B (130) | A Pick | chair, gain > 5 | 36 | -0.71 | -0.69 | no | no |
| B (130) | B Learning Pick | 20 % of round 1 | 609 | +0.79 | -0.39 | paired yes | no |

The Learning-Pick councils beat its rule only because its -20 % stop fills at the candle's low; when the stop fills at its level
they lose. This is PR #53's stop-fill finding again, not a rocket separator: 807 of the 1,012 holds use the plan RS (a Sell-bot-like exit: floor at half, 15 % trail after 1.5x, 6 h), none
ended at 10x, and the total stays at -9.46 to -9.54 per trade.

## Part 4: the jury of ten Claude reviewers

120 w4 cases (60 taken by the family-B wide rule, 60 random), cards with information at the buy only. Ten fixed roles, round 1
alone, round 2 after reading all round-1 votes and reasons; BUY = 6 of 10.

| Round | BUYs | Mean after cost | Rockets bought (of 3) | AUC profit | AUC rocket |
|---|---|---|---|---|---|
| 1 | 5 | -3.63 | 0 | 0.54 | 0.62 |
| 2 | 3 | +5.68 | 0 | 0.54 | 0.61 |

Round 2 bought cases 14 (+45.13), 93 (-9.58, nine of ten votes) and 97 (-16.26). The three rockets on the cards got no vote in
round 2 (one between them in round 1). Fewer than 10 buys: fails. The rule's 60 picks on the cards: -3.91 per trade; the 60 random: -13.17.

Amendment 1: the first cards showed one five-minute close from after the buy. Five reviewers pointed it out; those answers were
set aside unscored (jury/invalid_lookahead/), the cards were rebuilt and round 1 was run again with all ten.

## Part 5: the best rule regardless of luck (in-sample, labelled so)

| Group | Rule (plan) | In-sample | Without its best trade | w4 | w5 |
|---|---|---|---|---|---|
| A / wide | picture object/scene AND 6 h return lowest fifth (hold to end) | 41 trades, +413.77 | -439.68 | 22, -35.06 | 14, -24.77 |
| A / Pick | curve 1-6 h AND 6 h return 4th fifth (hold to end) | 40, +119.71 | -69.01 | 11, -10.78 | 6, -35.38 |
| A / Learning Pick | X post link AND 1 h return middle fifth (hold to end) | 40, +142.17 | +863.74 | 19, -8.84 | 11, -21.57 |
| B / Pick | liquidity/mcap middle AND top buyer share 2nd fifth (R6) | 45, +21.78 | +491.96 | 30, -14.73 | |
| B / Learning Pick | 1 h return 4th fifth AND experienced-wallet share middle (hold to end) | 44, +165.80 | +2,472.32 | 32, -39.20 | |
| B / wide | curve 1-10 min AND distance from low middle (hold to end) | 54, +123.56 | +1,849.27 | 68, -39.86 | |

The A / wide winner is MANIFEST: one coin at 356x on 17 May, +17,405 EUR on paper, which is more than the rule's whole total.
The coins of every best rule (buy, sale, multiple, EUR) are in results/best.json (coins_ins, coins_w4, coins_w5).

The best rule on w4 in hindsight was mostly negative before: A / Pick +17.96 on w4 vs -21.46 in-sample; A / Learning Pick +62.33
vs -23.53; B / wide +66.37 vs -21.45. One exception: A / wide "1 h volume middle fifth AND turnover top fifth, TR2", in-sample
101 trades +31.83, w4 40 trades +75.13, w5 10 trades -29.67.

### Exploration (not pre-registered): do in-sample winners stay winners?

Rule-plan pairs with 40+ in-sample and 20+ w4 trades. Share positive on w4 after cost:

| Group | Pairs | Positive in-sample | Of those, positive on w4 | All pairs positive on w4 | w5 positive: all / in-sample winners / winners on both |
|---|---|---|---|---|---|
| A / Pick | 17,112 | 466 | 9.4 % | 5.5 % | 11.1 % / 22.2 % / 12 of 43 |
| A / Learning Pick | 31,648 | 792 | 6.9 % | 2.7 % | 4.2 % / 7.9 % / 2 of 42 |
| A / wide | 38,960 | 573 | 3.7 % | 1.6 % | 4.7 % / 4.5 % / 4 of 21 |
| B / Pick | 37,488 | 1,558 | 5.4 % | 4.1 % | |
| B / Learning Pick | 95,160 | 2,039 | 8.6 % | 2.8 % | |
| B / wide | 134,064 | 1,213 | 5.7 % | 1.2 % | |

A rule that won in-sample is 1.3-4.8x more likely to win on w4 than a random rule, so there is a weak trace of persistence, but
more than 90 % of the in-sample winners lose on w4. In the Pick group a dozen rule-plan pairs are positive on all three periods,
e.g. "name-picture fit lowest fifth AND turnover 2nd fifth, R24": 47 trades +6.68, w4 21 trades +27.59, w5 9 trades +21.76; they
take 10-25 trades a month, so one month cannot confirm any of them by the 40-trade bar. (A first count of this table divided
pairs by rules and showed the opposite; it was corrected before this report.)

## What follows

Nothing is changed in the bots. The ceiling says the hold side cannot pay at the Pick's prices even with a perfect separator; the
buy side needs a 5-30x rocket enrichment and gets 2-5x. The 22 Nov live review stays the next decision point.

## Follow-up (26 Oct, after the user's "prüfe mehr bis du was findest")

No new search over the same months. Two things instead:

1. The 12 Pick rule-plan pairs that were positive in all three periods are frozen with their cut values
   (NOV-RULES-2026-10-26.json, rs_nov.py) and pre-registered for the unseen month 22 Oct-21 Nov (PREREG-NOV-2026-10-26.md).
   Together they were positive in every past window (+0.30 to +6.25 per trade, 55-173 trades), but their 1 % bound is -6 to -9 in
   every window; at their spread a single month passes the bar only with a mean near +10.
2. Exploration (rs_curve_feas.py, results/curve_feas.json): could the launch model's top picks be bought on the bonding curve? Of
   its top 0.1 % of w4 launches (739), 216 graduated (29 %, base 3 %), but 123 of those within the first minute (gone before an
   outsider can buy). 93 graduated after a minute or more: 12.6 % of the picks against 0.94 % of all launches (13x); 56 after five
   minutes or more (7.6 % vs 0.63 %). Top 1 %: 409 of 7,394 after a minute or more (5.5 %, 6x). Whether that can be bought cheaply
   enough is unknown: we have no curve trades, so no buy price. That is the one new data source with a large ratio behind it.
3. The curve-buy test of that lead (pre-registered in PREREG-CURVE-2026-10-26.md before any curve price was fetched; rs_curve.py;
   GeckoTerminal one-minute curve candles in SOL, branch rocketscurve; results/curve_top01.json). **It fails.**
   - Data: 714 of the 739 picks have curve candles (graduated 208 of 216 = 96.3 %, never graduated 506 of 523 = 96.7 %, so the
     source is fair to both). 134 graduated before the entry minute, 7 were nearly full at the entry, 25 had no candles: 573 buys.
   - Primary plan (buy in the first minute starting 60 s after the launch at the larger of open and close, stop at half, sell on the
     curve at 90 % of its completion price, else 24 h; 1.25 % fee each way and the 0.75 EUR allowance): 573 trades, -3.90 EUR per
     trade, total -2,234, 1 % bound -7.44, without the best trade -2,715. Both halves of the month negative (-4.38, -3.42).
   - Every other sale is negative too: sold the minute before completion -6.05, at the final curve price -4.86, no stop -5.15,
     stop 0.7 -4.63, stop 0.5 with a 2x take -4.97, entry at the candle high -4.92.
   - Why: the 53 buys that graduated while held made +3,191 EUR (+60 each), the other 520 lost 5,425 (-10.43 each). The coins that
     went on to graduate were already at a median 7.0x the curve's start price one to two minutes after the launch (quartiles
     4.6x-9.9x), so selling near completion (13.2x the start) gave only about 2x. The picks that were still near the start price at
     the entry (281 within 1.2x) had no graduation at all. The model's signal is real, but it is visible in the first minute's
     buying too, and by the time an outsider can act that buying has taken the gain.
   - By entry price (exploration): within 1.2x of the start 281 trades -3.26 each; 1.2-2x 47 trades +1.29 (small, not a rule);
     2-4x 93, -3.38; 4-8x 106, -5.54; above 8x 46, -10.37.
   - The top 1 % (secondary, reported only) is still being fetched; it will be added here.
