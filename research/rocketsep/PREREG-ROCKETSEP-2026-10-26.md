# Pre-registration: buy only rocket-like coins and hold them through the dip (26 Oct 2026, 07:40 UTC)

Fake money only. Research only: nothing here is switched on, no bot, account or rule changes. Written and pushed before any
outcome was split by any of the new facts below (holders, wallets, the rocket study's launch and picture facts, the creator's
launches) and before any model, rule or council of this file was fitted.

## Why

Learning Pick bought LAUNCH on 25 Oct, its -20 % stop sold it within the hour, and the coin then went about 14x. The user (26 Oct
06:56-07:06 UTC): the bot must separate dips that turn into rockets from dips that go to zero; research as much as possible with
all data and as many coins as possible; adjust the rules so only rockets or rocket-like coins are bought (fewer buys is fine) and
then held, not sold too early; checkers that go over it a hundred times and confer; show the rule that made the most money
regardless of luck and the coins it picked; the goal is a rule with a big profit.

Known before and not repeated as they were: PR #42 (1.5M rules over five months, nothing holds), PR #48 (learned exit, holding is
noise), PR #51 (checker at the first -20 % touch, AUC 0.53 committee, nothing holds), PR #53 (100-checker council at the live
sales, every hold plan loses, nothing holds), PR #54 (ten bots), PR #55 (rocket facts raise the rocket rate 2-3x, no money rule).
What is new here: (1) the facts those studies did not have at the decision: holder and trade-flow numbers and wallet numbers at
the moment (w3/w4), the rocket study's launch, media and picture facts, the creator's launches of the 30 days before; (2)
separators trained only on the extreme cases (rocket against zero); (3) the buy side and the hold side together, with hold plans
made for rockets; (4) a hundred-plus checkers with the new views; (5) the best rule in hindsight shown with its coins next to its
unseen-month result.

## Data (exact sources; nothing new is downloaded)

- Buys, paths and the live sale moments: research/council/check_council.py build (PR #53) line by line: the five windows w1 25
  Apr-24 May, w2 25 Jun-24 Jul (GeckoTerminal, branch monthsdata), w3 10 Aug-9 Sep, w4 10 Sep-8 Oct (history2 five-minute
  candles, branch monthsh2), w5 9-21 Oct (GeckoTerminal); buys at whole hours 1-24 h after the graduation with the roles P (the
  Pick's gates), W1, X, Y, A (first hour in the wide universe: market cap 30k-10M, liquidity >= 8k, a trade in the hour before),
  L (Learning-Pick universe); five-minute paths to graduation + 48 h; frame A = the Sell bot's (v3) sale, frame B = the Learning
  Pick's sale (stop -20 %, 2x, 2 h). Recorder outages as there. Expected 61,909 buys.
- Added to the build (same code, more output): the features at the buy moment (the last finished candle before the buy; check_
  mlexit's coin numbers, position numbers at the buy, the 11 chain launch facts) and the decision time of each sale moment.
- Rocket-study facts per graduated coin (research/rockets/check_rockets.py launch_facts + picture_facts, PR #55, branches
  rocketschain, rocketsmeta, rocketsimages; names, creator and creation time from history2's coins.parquet first): F1 creator's
  graduations in 30 days, F3 bonding-curve minutes, F4 copycat ticker in 7 days, F5 CJK name, F8 graduations in the 24 h
  before, F10 number of links, F11 X link type, F12 news word, F13 theme heat, F14 X post age, F15 picture reused, F16 launched
  outside pump.fun, F17 video, F18 description length, F19 picture group, F20 animated picture, F21 look-alike picture, F22
  name fits the picture. All look only backwards from the graduation. F2 (creator's earlier rocket) is left out (it needs the
  outcomes of other coins).
- Creator launches (w3/w4 graduations only; branch rocketslaunches, Slinky21/Pumpfun_v2_dataset, CC-BY-4.0, "Data provided by
  [Slink21]"): the creator's launches and graduations in the 30 days before the coin's own launch (L-F1, L-F1b).
- Holder and trade-flow numbers (w3/w4 only; history2 hourly rows): at the latest whole hour after the graduation at or before
  the decision: buyers, sellers, buys and sells in the hour before, the top buyer's share, atomic (same-block) trades, buys and
  sells in 24 h; log ratios buyers/sellers and buys/sells; the same ratios' change since the buy hour; minutes since that row.
- Wallet numbers (w3/w4 only; branch wallets: every wallet's first PumpSwap buy of at least 0.1 SOL within 48 h of the
  graduation, its SOL in and out): at the decision time, the wallets so far, new wallets in the 15 and 60 minutes before, their
  SOL; for each such wallet its earlier coins that ended at least 72 h before (graduation + 72 h before this buy): how many,
  their mean log return, whether one returned 3x or more; the shares of experienced wallets (5 or more such coins) and of winner
  wallets (one 3x or more) among all wallets so far and among the new ones of the hour; the largest first buy's share of all.
- Every launch of w3/w4 (1.56 million, branch rocketslaunches) for the similarity tables (Part 0), with the graduation's price
  path from history2.

Fact family A = everything that exists in all five windows (coin, position, chain launch facts, the rocket-study facts).
Family B = A plus creator launches, holders and wallets (w3/w4 only).

## Outcomes

- Rocket at a buy: the high reaches 10x the buy price within 24 h after the buy. Zero at a buy: the low reaches 0.1x within 24 h
  and the high stays under 2x.
- Rocket after a sale: after the sale the high reaches 10x the buy price within 24 h. Zero after a sale: the low reaches 0.1x
  the buy price within 24 h and the high after the sale never gets back to the buy price.
- Buys with a recorder outage within 24 h after the buy (w3/w4) are left out of the labels; money as PR #53 (a plan still
  holding when an outage starts sells at the last close before it).
- Money: 50 EUR tickets, paper fees 1 % a side (check_chartexit.to_money); the PR #39 allowance of 0.75 EUR per round trip is
  taken off where "profitable" is asked.

## Part 0: what rockets have in common (description, no money)

(a) Every launch of w3 and w4: "full rocket" = the coin graduated and, from its price 30 minutes after the graduation, its high
within the next 24 h reaches 10x that price (history2 candles). Per cheap launch fact (creator's launches and
graduations in 30 days, CJK name, hour, weekend, launches in the hour before, name and ticker length) and per metadata/picture fact
where read (flagged "maybe biased" as in PR #55): the full-rocket rate with and without, the ratio, on w3 and on w4 separately.
(b) The sale moments of frames A and B: rocket-after-sale against zero-after-sale cases: per fact the median in each group and
the single-fact AUC, on w1-w3 and on w4 (family B facts on w3 and w4).

## Part 1: the ceiling (description)

(a) A perfect separator at the live sales: hold exactly the rocket-after-sale cases with each council plan (PR #53's ten) and with
a hindsight exit (the highest high within 24 h after the sale); per frame (A on P buys, B on L buys) and window: EUR per 1,000
buys and the resulting mean per trade against the rule's own. (b) The oracle "hold whenever the plan beats the sale", per plan.
(c) Buy side: the mean money of rocket and non-rocket buys per frame and buy plan, and the rocket share a buy filter would need to
break even (s* = -m_non / (m_rocket - m_non), assuming its non-rockets are average); against the base share.

## Part 2: the buy side ("Rocket Pick")

Frames: P (the Pick's own type of buy), L (Learning-Pick type), A (the wide universe's first hour). Training rows: every buy of
every role in the fit windows (each buy once; outage-flagged buys left out).
Models (LightGBM binary, fixed): bR = rocket against all others; bRZ = rocket against zero (other buys not used). Learning rate
0.05, 15 leaves, at least 100 rows per leaf, feature fraction 0.7, bagging 0.8 (every round), L2 10, at most 1,000 trees, early
stop after 100 on the last 15 % of training rows by graduation time (AUC), seed 7.
Threshold: three blocked folds by graduation time over the fit windows give out-of-fold scores; the cut for "top q" is the
(1 - q) quantile of the out-of-fold scores of the frame's rows; the model refitted on all fit rows buys when its score is at or
above the cut.
Buy plans (from the buy): V3 the live Sell bot; K -30 % / 11x / 6 h; LP -20 % / 2x / 2 h; R6 floor -50 % / 11x / 6 h; R24 floor -50
% / 10x / 24 h; TR trailing 30 % under the highest high since the buy (starts at 0.7x), to the end of the data; TR2 floor -50 %,
after 2x a trailing 40 % under the highest high, to the end of the data; HN hold to the end of the data. Floors and trails fill at
the candle's low (main) or the level (check); targets at the target; the end at the last close.
Candidates per frame and family: {bR, bRZ} x q in {1, 2, 5, 10, 20} % x the 8 plans = 80.
Choice: the highest mean money per trade on the choose window with at least 20 trades there (ties: fewer trades, table order).
Family A: fit w1+w2, choose on w3; refit w1-w3, test on w4 and w5. Family B: fit on w3 graduations before 30 Aug 00:00 UTC,
choose on w3 from 30 Aug; refit on all of w3, test on w4.

## Part 3: the hold side at the live sales

(a) The separator: LightGBM binary (settings as Part 2) on the sale-moment features (PR #53's 85 numbers + sale context) plus the
family's new facts at the decision time; sR = rocket-after-sale against all, sRZ = rocket-after-sale against zero-after-sale.
Candidates per frame and family: {sR, sRZ} x q in {1, 2, 5, 10} % (top q of the out-of-fold scores, as Part 2) x PR #53's ten
plans = 80. Choice: the highest mean gain against the sale per judged buy on the choose window with at least 5 holds there.
Frames, windows and fits as PR #53 (A judged on P buys, B on L buys; training on every buy of the frame), families as Part 2.
(b) The council: PR #53's ten views x ten plans, round 1, debate round 2, chair, its 14 candidates and its choice rule, with
family A's rocket-study facts added to the views V6 (Start-Fakten), V7 and V8 (100 checkers). Family B: the same plus three
views, V11 Halter-Leser (holder and flow numbers), V12 Wallet-Leser (wallet numbers), V13 Raketen-Fakten (rocket-study facts and
creator launches), each LightGBM: 13 x 10 = 130 checkers, fit/choose/test as family B above.

## Part 4: the jury (ten Claude reviewers on the buy side)

On w4 frame-A buys: every buy the chosen family-B Part 2 rule of frame A takes (a seeded sample of 60 if more) and 60 seeded
random frame-A buys it does not take, as cards with information at the buy only (no name, ticker, address, date or clock time;
the coin, launch, holder and wallet numbers; the chosen plan with fees; the w3 base rates). Ten reviewers with PR #53's fixed
roles vote BUY or SKIP alone (round 1), then see the others' votes and reasons and vote again (round 2); BUY = 6 of 10 in round 2.
They are sub-agents of this session (no API key in the container), told to read only their card file and run nothing. Judged:
the money of the jury's buys with the chosen plan, and whether it separates (rocket share and money of its BUY vs SKIP). Skipped,
and said so, if the rule takes fewer than 10 w4 buys.

## Part 5: the best rule regardless of luck (the user's ask; in-sample, labelled so)

A grid on frames P, L and A: every Part 2 candidate, plus simple rules = one or two conditions from {each bucket of the rocket
facts F1-F22 (PR #55's buckets), each quintile of lr60, lr360, vol60, v60_ratio, turnover, lmc, lliq, liqmc, ath, atl, age (cuts
from w1-w3)} x the 8 buy plans. The rule with the highest mean money per trade on w1-w3 together with at least 40 trades is shown
with every coin it bought (buy time, price, sale time, reason, result), then the same rule's w4 and w5 results and coins. Also
the best rule on w4 in hindsight (at least 40 trades) and its w1-w3 result, to show the size of luck. For family B facts: the same
with w3 as in-sample and w4 as the check. This part decides nothing.

## The bar

Judged: the chosen candidates of Part 2 (3 frames x 2 families), Part 3a (2 x 2), Part 3b (2 x 2), the jury (1).
A buy rule HOLDS if on w4 (a full unseen month): (1) at least 40 trades, (2) mean per trade after the 0.75 EUR allowance above 0,
(3) the 1st percentile of 10,000 bootstrap re-draws of its trades above 0, (4) the total without its single best trade above 0
(the four points of research/PREREG-REVIEW-2026-11-04.md), and for family A (5) its w5 mean after the allowance not below 0 (if
it has at least 10 w5 trades; fewer: "too few", which is not a pass).
A hold rule HOLDS if on w4: at least 40 judged buys and at least 10 holds, its paired difference to the live rule per buy has a
mean above 0, a 1st percentile of 10,000 paired re-draws above 0, a total above 0 without its single best difference, a level-fill
difference not below 0; family A also w5 difference not below 0. Profitable (the four points on its own trades) is a separate
question, also reported. Holm over the 15 one-sided p-values is reported too.

## If something holds / if nothing holds

If a rule holds, it is built as a SHADOW on live buys (shown, nothing bought or sold by it) only after the user's explicit yes, and
judged again on the fresh month after 22 Nov before anything else; a Pick rule change restarts the Pick account and needs the
user's yes either way. If nothing holds, the report says so plainly with the numbers and nothing is built.

Compute: this container only (4 cores, at most 3 worker processes); no GitHub Actions runner, so the live scans are not touched.

## Amendment 1 (26 Oct, ~08:20 UTC; before any jury vote was scored)

The first jury cards showed 36 five-minute closes before the buy, the last of which was the close of the candle in which the buy
falls, i.e. up to five minutes AFTER the buy (a look-ahead; the computing rules were not affected: their buy features use the
last candle that finished before the buy). Five reviewers pointed it out in their round-1 replies. All round-1 answers were set
aside unscored (kept in research/rocketsep/jury/invalid_lookahead/), the cards were rebuilt with the 35 closes and volumes up to
the last finished candle (the same 120 seeded cases), and round 1 was started again with all ten reviewers.
