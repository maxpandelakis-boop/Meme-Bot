# Pre-registration: a checker for the moment a position first falls 20 % (25 Oct 2026, 20:45 UTC)

Fake money only. Research only: nothing here is switched on, no bot or rule changes. Written and pushed before any dip event,
outcome, feature or model below was computed on any data.

## Why

Learning Pick bought LAUNCH on 25 Oct (13:54 UTC); its -20 % stop sold it within the hour and the coin then went about 14x. The
user asks how the bot can learn to recognise such coins and check, case by case, whether loosening the stop makes sense; then
(20:10 UTC) to test every feasible way to build such a "checker" (Prüfer), including several checkers that talk to each other and
debate, so the bot gets a second opinion.

Known before (not repeated naively): PR #42: wider stops and "no stop" (shadow rule B) lost in all five month windows; PR #48: a
learned per-moment value of holding is noise out of sample (R2 -0.03), the gain of every exit is "getting out". What is new here:
the question is asked only at one moment, the first touch of -20 % (and -30 %) after the buy, and the checker decides once, for
that case, between "sell as the stop says" and "loosen the stop".

Note (from the live config, before any data): Learning Pick's rule is stop -20 %, target 2x, 2 h (lernpick.json S20-T2-H2), so even a
loosened stop would have sold LAUNCH at 2x at most. One coin proves nothing either way.

## Data

Exactly as research/mlexit/PREREG-MLEXIT-2026-10-24.md (PR #48): the five windows w1 25 Apr-24 May, w2 25 Jun-24 Jul (GeckoTerminal,
branch monthsdata), w3 10 Aug-9 Sep, w4 10 Sep-8 Oct (history2 as five-minute candles, branch monthsh2; windows touching a recorder
outage dropped), w5 9-21 Oct (GeckoTerminal); five-minute USD candles of the first 48 h after graduation, wicks beyond 5x the close
count as the close; SOL/BTC by hour (market.json, only finished hours); launch facts from rocketschain chain.parquet. Holders, buyer
and seller counts are not in the candles for all windows and are not used (said in the report).

w4 and w5 have been used before for other rules (exits K and v3 per window are known from PR #46). No outcome conditioned on a dip
has been looked at on any window before this file.

## Buys (entries)

check_mlexit.coin_entries line by line (entry at a whole hour after graduation, price = the last finished candle's close, the path
starts with the first candle that starts after the buy), with the path kept for 288 five-minute candles (24 h) instead of 150, and
two more roles:
- P: the Pick-type entry (the Pick's gates as far as candles hold them, whole hours 6-24 h), one per coin; expected w4 356, w5 185.
- W1, X, Y as in PR #48 (first wide entry; up to 3 random further wide entries; up to 3 random further "ALL" entries).
- A1 (new): each coin's first whole hour 1-24 h in the ALL universe (market cap 30k-10M, liquidity >= 8k, a trade in the hour before).
- L (new, Learning-Pick-like): each coin's first whole hour 1-24 h with market cap 50k-2M, liquidity >= 15k, 24 h volume / market
  cap >= 0.1 (lernpick.UNIVERSE as far as candles hold it; its 72 h age limit is cut to 24 h by the data).

## The dip event

For a level d (0.20 main, 0.30 second): the first path candle k within the first 6 h after the buy (k < the 6 h candle count) whose
low is at or under 1 - d times the buy price, with no 11x high before it. (Learning-Pick frame: within 2 h and no 2x before.)

The checker decides at the touch: it sees everything up to the close of the candle before the touch (candle k-1; for k = 0 the
candle in which the buy happened) and the fact that the price has now touched 1 - d. Nothing of candle k or later. ("D0", main.)
Second, exploratory ("D1"): it decides at the close of the touch candle, sees that candle too, and a "sell" is booked at that close.

## Rules compared (money: 50 EUR ticket, paper fees 1 % a side, at least 0.10; check_chartexit.to_money)

- S20 (plain stop, main baseline): stop -20 %, take profit 11x, sell after 6 h. S30: the same with -30 % = the Pick's old rule K.
- V3: the Pick's live chart exit ("Sell bot", PR #46).
- L50 (always loosen): floor -50 %, 11x, 6 h. L50-24h (exploratory, always loosen and hold up to 24 h).
- C20 (the checker): S20 until the touch; at the touch the checker says SELL (booked as the stop: at the touch candle's low,
  "low fill") or HOLD (from the touch candle on: floor -50 % at the low, 11x, sell at 6 h after the buy). C30 likewise on S30.
- Learning-Pick frame (second): S20LP = stop -20 %, 2x, 2 h; C20LP = at the touch HOLD means floor -50 %, 2x, 2 h.
- Fills: the stop and floor at the candle's low (main, as PR #42/#46/#48); at the level unless the candle opened below it ("level
  fill", a check). D1: the plain baseline is S20c = always sell at the touch candle's close.

## Question 1: how often does a dipped coin come back? (base rates, no model)

Per window, for P, A1 and L buys and d = 0.20 / 0.30: how many buys touch; of those, the share whose high after the touch candle
(candles k+1 .. 24 h after the buy) reaches 1x (back to the buy price), 2x, 5x, 10x of the buy price, and the share whose low falls
to 0.1x or under (about zero) within 24 h of the buy; Wilson 95 % intervals. Next to it the same reach rates for all buys (not
conditioned on a dip). The number of "LAUNCH-like" cases (touch -20 % within 6 h, then 10x within 24 h) per 1,000 buys.

## Question 2: can anything at that moment predict a recovery? (the computing checker)

Features at the decision (D0: candle k-1; D1: candle k): check_mlexit's coin numbers (returns over 5 min-6 h, the last 24 five-minute
returns, volatility, place in the 1 h / 4 h range, distance to the high and low since graduation, up-candle share, falling run,
candle body and wicks, volume 5 min-1 h and its change, candles without trades, up-candle volume share, volume / market cap,
market cap, liquidity, age, SOL 1 h / 6 h / 24 h, BTC 24 h, hour, weekday), the position numbers (minutes since the buy, price /
buy, high and low since the buy, distance to that high, minutes since that high, volume now / at the buy, hour of the buy), the
launch facts (links, description, video, name lengths, CJK name, creator's graduations in 30 days, curve time, signatures), and
the level d. About 85 numbers.

Training events: every dip event of every buy (P, W1, X, Y, A1, L; a buy with several roles counts once) in the training windows.
LightGBM, fixed settings: learning rate 0.05, 31 leaves, at least 200 events per leaf, feature fraction 0.7, bagging 0.7, L2 10,
at most 1,500 trees, early stop after 100 on the last 15 % of training coins by graduation time, seed 7, 3 threads.

Models: (V) regression on the money of holding minus selling, in buy multiples (hold outcome under the rule's HOLD branch minus the
stop's sale); (C2) classifier "reaches 2x of the buy price within 24 h"; (C1) classifier "gets back to the buy price within 24 h";
(Z) classifier "falls to 0.1x within 24 h" (diagnostic only).

Diagnostics on w4 (fitted on w1-w3): AUC with a bootstrap 95 % interval by coin for C1, C2, Z on all w4 events and on w4 P events;
the hit rate in the top 10 % of predictions against the base rate; V's R2, rank correlation and deciles. Placebo: the same fits with
labels shuffled among events with the same k; expected AUC about 0.5.

## Question 3: does "hold only when the checker says so" make more money? (the bar)

Candidate decision rules of the computing checker (12): V with "hold if predicted gain > m", m in {0, 0.03, 0.06, 0.10}; C2 and C1
with "hold if the prediction is in the top q of the training events' predictions", q in {5, 10, 20, 40} %. Choice: all 12 fitted on
w1+w2, judged on w3's P, W1, A1 and L buys (each buy once) by the mean money difference to S20 per trade; the best is chosen (ties:
V before C2 before C1, the stricter setting). The chosen one is fitted again on w1-w3 and tested on w4 and w5. Walk-forward
w1-w4 -> w5 also reported. The same procedure for C30 (vs S30 = K) and C20LP (vs S20LP) and D1 (vs S20c): reported, not the bar.

The checker committee (LLM, the user's "several checkers that talk and debate"): three Claude reviewers with fixed roles, (a) the
chart reader (price shape before and since the buy), (b) the flow reader (volume, trade gaps, liquidity, market cap, the market),
(c) the sceptic (base rates, fees, how often a -20 % touch turns into a recovery). Each case is a text card with D0 information only:
no name, ticker, address, date or clock time; the buy numbers, the path since the buy, the last 3 h of five-minute closes (relative
to the buy price) and volumes, the coin's age, SOL/BTC changes, the launch facts, the two choices (SELL now as the stop; HOLD with
floor -50 %, 11x, sell at 6 h) with fees. The reviewers are also given the Question 1 base rates of w1-w3 (training data). Round 1:
each reviewer votes alone (HOLD or SELL, a probability that HOLD makes more money, a reason of a few words). Round 2 (debate): each
reviewer sees the other two's votes and reasons on every case and gives a final vote. Committee = majority of the final votes
(2 of 3); also reported: unanimous HOLD, round-1 majority. No API key is in this container, so the reviewers are Claude sub-agents
of this session, told to read only their case file and run nothing. Cases: every D0 -20 % dip event of the w4 and w5 P buys (if
more than 400, a seeded sample of 400 and the money scaled to the sample). The committee is not tuned: its prompts are fixed here
before any case is built.

Ensembles: AND (hold only if the computing checker and the committee both say hold) and OR (either).

**The bar (the user's: a rule counts only if it holds a whole unseen month). Four checkers are judged: computing checker (C20),
committee, AND, OR. A checker HOLDS if on the w4 P buys (10 Sep-8 Oct) its mean money difference to S20 per 50-EUR trade is above
0 with a one-sided bootstrap p-value (20,000 draws, seed 7) that survives Holm over the four at 5 %, the level-fill difference
on w4 P is not negative, and on w5 P the difference is not negative.** It is useful for the Pick only if it also beats V3 on w4 P
the same way (one-sided 5 %) and on w5 P is not worse than V3. Profitable (mean per trade above 0) is a separate question.

Also reported: per window means of S20, S30, L50, V3, C20; the share of HOLD decisions and how they ended; the 2x / 5x / 10x
trades the checker kept and the ones it missed; the best 2 % of trades; LAUNCH-like cases kept.

## If it holds / if it fails

If a checker holds, it is built as a SHADOW rule on live buys (Learning Pick if it holds in the Learning-Pick frame, Pick if it also
beats V3): it is replayed beside the real rule and shown, nothing is sold by it. Changing a live sell rule needs the user's explicit
yes (a Pick sell-rule change restarts the Pick account); a live committee would also need an API key as a repository secret. If no
checker holds, the report says so plainly and nothing is built.

Compute: this container only (4 cores, at most 3 worker processes); no GitHub Actions runner, so the live scans are not touched.
