# Pre-registration: a council of 100 checkers that may hold a coin as long as it likes (25 Oct 2026, 22:55 UTC)

Fake money only. Research only: nothing here is switched on, no bot, rule or shadow changes. Written and pushed before any
event, outcome, feature or model below was computed on any data.

## Why

PR #51 tested one checker, a three-reviewer committee and two ensembles at the first -20 % touch, with the hold capped at the
old frame (floor -50 %, 11x, 6 h after the buy). All failed. The user (25 Oct, 22:27 UTC) asks again, bigger: the checker may
hold the coin as long as is best, there is no fixed frame; use 100 checkers instead of three; it may run very long.

Known before and not repeated naively: PR #42 (wider stops lose in every window), PR #48 (a learned per-moment value of holding is
noise out of sample), PR #51 (recognition of a recovery exists, money does not; holding to 24 h after the buy lost on w5).
What is new: (1) the question is asked at the moment the live rule actually sells, (2) "hold" is a menu of ten plans up to the
end of the data instead of one fixed frame, (3) one hundred different checkers vote, debate in a second round, a chair weighs them,
and a jury of ten Claude reviewers decides the cases where the checkers disagree.

## Data

Exactly as research/dipcheck/PREREG-DIPCHECK-2026-10-25.md (PR #51): windows w1 25 Apr-24 May, w2 25 Jun-24 Jul (GeckoTerminal,
branch monthsdata), w3 10 Aug-9 Sep, w4 10 Sep-8 Oct (history2 as five-minute candles, branch monthsh2), w5 9-21 Oct
(GeckoTerminal); five-minute USD candles of the first 48 h after graduation; wicks beyond 5x the close count as the close;
SOL/BTC by finished hour; launch facts from rocketschain chain.parquet. The buys are check_dip.coin_entries (roles P, W1, X, Y,
A, L, one row per buy), with one change: the path is kept to the end of the data (the last five-minute candle that starts before
graduation + 48 h) instead of 24 h. Every buy has at least 24 h of path (as before); a P buy (6-24 h after graduation) has 24-42 h.

"No limit" therefore means "until the data ends", 24 to 42 hours after the buy. That is the honest limit of the free data.

Recorder outages (history2, w3/w4, gaps of 10 minutes or more): as before, buys with an outage from 1 h before to 6 h after the
buy are left out. Main: a hold plan that is still holding when a later outage starts sells at the last close before the outage
(flag "cut"). Check: w3/w4 buys whose span from the buy to the end of the data touches an outage are left out (both reported).

## The two frames and the moment of decision

- Frame A (the Pick, main): the live Sell bot v3 (check_mlexit.V3: floor -50 % at the low, 11x, trailing 15 % under the high
  once 1.5x, "drop" when a close is 15 % under the close 30 min earlier, 6 h). Its one sale per buy is the event, whatever the
  reason (floor, trail, drop, time, 11x). The v3 money must equal check_dip's V3_m on every buy.
- Frame B (Learning Pick, the LAUNCH type): its live rule S20-T2-H2 (stop -20 % at the low, 2x, 2 h). Its one sale per buy is
  the event (stop, 2x, time).

The checker decides when the rule sells. It sees everything up to the close of the sale candle k if the sale is at a close
(drop, trail at the close, time), and up to the close of candle k-1 if the sale is at a low or a target inside candle k (floor,
stop, trail at the low, 2x, 11x), plus the sale itself (reason, price as a multiple of the buy price, minutes since the buy).
Nothing later. Features: check_dip's DFEATS (about 85 numbers: coin, position and launch numbers) at that candle, plus the sale
context (reason code, sale multiple, minutes since the buy).

## The ten hold plans (from the veto on; p = the sale price as a multiple of the buy price)

For a sale at a close the plan starts with the next candle. For a sale at a low or target inside candle k, the plan's only check in
candle k is its floor against that candle's low (the order inside the candle is unknown); from candle k+1 on, everything.
Floors and trailing stops fill at the candle's low (main) or at their level unless the candle opened below it (check); targets
fill at the target; time exits at the close; the end of the data at the last close. 11x of the buy price is taken where it applies.

| plan | name | floor | horizon after the veto | target |
|---|---|---|---|---|
| H1 | one more hour | 0.6 p | 1 h | 11x |
| H3 | three hours | 0.6 p | 3 h | 11x |
| H6 | six hours | 0.6 p | 6 h | 11x |
| H12 | half a day | 0.6 p | 12 h | 11x |
| H24 | a day | 0.6 p | 24 h | 11x |
| HE | to the end | 0.6 p | end of data | 11x |
| HN | diamond hands | none | end of data | none |
| TR | let it run | trailing 30 % under the highest high since the veto (starts at 0.7 p) | end of data | none |
| BE | wait for the way back | 0.6 p | end of data | max(1.0, 1.3 p) |
| RS | second chance | a fresh Sell bot from the veto: floor 0.5 p, trailing 15 % once 1.5 p, drop (only closes after the veto as the reference, else p), 6 h | | 11x |

A horizon past the end of the data ends at the end of the data. The gain of plan j for an event = money(plan j) - money(the rule's
sale), per 50-EUR ticket, paper fees 1 % a side (check_chartexit.to_money).

## Question 1 (descriptive, no model): what would holding have done?

Per frame, window, role (P for A, L for B, and all) and sale reason: the mean gain of each plan against the sale, the share of
events where it gained, and how many events ended at 2x / 5x / 10x of the buy price under each plan. "Never sell" (HN applied
to every event) is the user's "hold as long as it goes".

## The 100 checkers

Ten views x ten plans. A checker = (view v, plan j); it predicts the gain of plan j from its view and votes HOLD-j if the
prediction is above 0 EUR, else SELL. Every view also gets the three sale-context numbers.

| view | German name | what it looks at | learner |
|---|---|---|---|
| V1 | Kurz-Chartleser | lr5-lr60, seq0-seq23, vol30, vol60, rng1h, up12, downrun, body, wick_up, wick_lo | LightGBM |
| V2 | Lang-Chartleser | lr180, lr360, rng4h, ath, atl, vol180, age | LightGBM |
| V3 | Volumen-Leser | v5, v15, v60, v60_prev, v60_ratio, nt12, nt36, upvol, turnover, lmc, lliq, liqmc | LightGBM |
| V4 | Positions-Leser | held, ret, hi_since, lo_since, dd, since_hi, v60_entry, entry_h | LightGBM |
| V5 | Markt-und-Uhr | sol1h, sol6h, sol24h, btc24h, hour, wday, age | LightGBM |
| V6 | Start-Fakten | the 11 launch facts, lmc, age | LightGBM |
| V7 | Allrounder | everything | LightGBM |
| V8 | Rechenschieber | everything, rank-transformed (by the training events), NaN as the median | ridge regression, alpha 10 |
| V9 | Zwillingssucher | 12 numbers (lr5, lr30, lr60, lr360, vol60, v60_ratio, turnover, lmc, ath, held, ret, dd) standardised | the mean gain of the 200 nearest training events |
| V10 | Skeptiker | reason x sale-multiple bucket (<0.6, 0.6-0.9, 0.9-1.2, 1.2-2, >=2) x age bucket (<6 h, 6-12 h, >=12 h) | the cell's mean gain, shrunk to the reason's mean with 50 events of weight |

LightGBM (fixed): regression (L2) on the gain clipped to [-60, +250] EUR, learning rate 0.05, 15 leaves, at least 300 events per
leaf, feature fraction 0.8, bagging 0.8, L2 10, at most 400 trees, early stop after 50 on the last 15 % of the training events by
graduation time, seed 7, one thread per fit. Training events: every event of every buy (all roles, each buy once) of the training
windows, per frame.

## Round 1, the debate (round 2), the chair

- Round 1: the 100 votes per event. Council vote share s1 = HOLD votes / 100; the council's plan = the plan with the most HOLD
  votes (ties: the higher mean predicted gain over its ten views, then the shorter plan in the table order).
- Round 2 (debate): every checker is fitted again with two more numbers, the round-1 mean predicted gain of its plan over the
  ten views and s1. On the training events these come from 3 blocked folds by graduation time (out of fold), so no checker
  sees its own training labels through the others. s2, plan as round 1.
- Chair: per plan, a ridge regression (alpha 1) of the gain on the ten views' out-of-fold round-1 predictions; the chair holds
  with the plan of the highest predicted gain if that is above a margin m, else sells.

## Choice and test (the user's bar: a rule counts only if it holds a whole unseen month)

Candidates (14 per frame): majority round 1 and round 2 with s >= tau, tau in {0.20, 0.35, 0.50, 0.65, 0.80}; the chair with
m in {0, 2, 5, 10} EUR. Choice: everything fitted on w1+w2, judged on w3 (frame A: P and W1 buys; frame B: L buys) by the mean
money difference to the rule per trade; the best is chosen (ties: the stricter, i.e. fewer holds). The chosen one is fitted
again on w1-w3 and tested on w4 (main) and w5. Walk-forward w1-w4 -> w5 also reported.

Judged per frame (three named before any result, plus the jury in frame A): (1) the w3-chosen candidate, (2) simple majority after
the debate (round 2, tau 0.50), (3) the chair with m = 0; (4, frame A only) council with jury (below). Holm over all judged
candidates of both frames together at 5 %.

**A candidate HOLDS if on the w4 test buys (frame A: P buys; frame B: L buys) its mean money difference to the live rule (A: v3
Sell bot; B: S20-T2-H2) per 50-EUR trade is above 0 with a one-sided bootstrap p-value (20,000 draws by buy, seed 7) that survives
Holm, the level-fill difference on the same buys is not negative, the outage-check difference is not negative, and on w5
(same role) the difference is not negative.**

Profitable is a separate question (research/PREREG-REVIEW-2026-11-04.md): at least 40 trades, mean above 0 after a 0.75 EUR per
trade cost allowance (1.5 points at 50 EUR), one-sided 1 % bootstrap lower bound above 0, still above 0 without the best trade.

Also reported: per window the means of the rule, every plan always taken, the council; how often the council held, with which
plan, how the holds ended; 2x / 5x / 10x cases kept and missed; the best 2 % of trades; a placebo (round 1 with the gains
shuffled among events of the same reason) that should hold nothing.

## The jury (the "checkers who talk to each other")

Ten Claude reviewers with fixed roles: (1) chart reader, (2) volume and flow reader, (3) sceptic of base rates and fees,
(4) risk manager, (5) momentum trader, (6) dip buyer, (7) rocket hunter looking for LAUNCH-like comebacks, (8) clock and age
analyst, (9) statistician who weighs the 100 checkers' votes, (10) devil's advocate who argues against the majority.

Cases: the frame-A w4 and w5 P events where the round-2 vote share s2 is between 0.20 and 0.80 (contested), at most 120 (a seeded
sample if more; the rest follow the council). A case card shows no name, ticker, address, date or clock time: the buy numbers,
the path since the buy, the last 3 h of five-minute closes and volumes relative to the buy price, the coin's age, SOL/BTC, the
launch facts, the sale (reason, multiple, minutes), the ten plans with fees, and the council's round-2 votes per plan. Each reviewer
also gets the frame-A Question 1 rates of w1-w3 (training data). Round 1: each votes alone (one plan or SELL, a probability that
holding beats selling, a reason of a few words). Round 2: each sees the other nine's votes and reasons on the cases that were not
unanimous and votes again. Jury decision = majority of the final votes (6 of 10 for HOLD, plan = the most voted plan among them);
cases with s2 >= 0.80 hold with the council's plan, s2 < 0.20 sell. No API key is in this container, so the reviewers are Claude
sub-agents of this session, told to read only their card file and run nothing. Prompts fixed in research/council/jury/BRIEF.md
before any card is built. If the jury cannot finish before 06:00 UTC on 26 Oct, it is reported as not run, and the Holm set
shrinks by one.

## If it holds / if it fails

If a candidate holds, nothing is switched on by this work: the user is told and asked whether it may run as a shadow beside the
live rule (a shadow sells nothing). A live sell-rule change needs the user's explicit yes (a Pick sell-rule change restarts the
Pick account); a live jury would need an API key as a repository secret. If nothing holds, the report says so plainly.

Compute: this container only (4 cores, at most 3 worker processes); no GitHub Actions runner, the live scans are not touched.

## Amendment 1 (25 Oct, 23:20 UTC; while writing the council code, before any event, outcome or model was computed)

The LightGBM and ridge targets are clipped to [-250, +250] EUR instead of [-60, +250]: a lower clip at -60 would hide most of the
loss of holding after a high sale (for example a trailing sale at 5x that falls back), which would bias the checkers towards
holding. The nearest-neighbour checker (V9) and the base-rate checker (V10) use the gain as it is (no clip), as written. In round 2
the base-rate checker (V10), which has no numbers to fit, adds the round-1 vote share s1 as a fourth cell key in three buckets
(< 0.2, 0.2-0.5, >= 0.5); the nearest-neighbour checker adds the two numbers, standardised, to its twelve.
