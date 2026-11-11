# Pre-registration: a learned sell decision for the Pick account (24 Oct 2026, 23:30 UTC)

Fake money only. Research only: nothing here is switched on. Written and pushed before any feature, label or model below was
computed on any data.

## Why

The user (24 Oct, 23:00 UTC): the bot can learn from thousands of coins where a coin is heading and react smartly; it only sees
the coin as it is now and takes its position from that; every factor and aspect has to be used. Then: "Nimm so viel du kannst"
(use as many coins as you can). So: a model trained on every price path we have, which decides for an open Pick position, every
few minutes, "hold or sell now", from everything known at that moment.

Known before (not repeated naively): PR #21 (a model "stay in or get out" every 15 min for the rocket hunter, label 2x before
0.5x) lost against the fixed rule where the account buys; research/winlose: chart numbers predict a big move, hardly its
direction; PR #46: the chart exit v3 (floor -50 %, trail 15 % once 1.5x, out on -15 % in 30 min, 6 h) loses less than the fixed
rule K (-30 % / 11x / 6 h) on unseen months, but still loses in every window and sells the big winners early.

What is new here: (1) the model learns the VALUE of holding (money, not a 2x/0.5x label), so a sell decision is "the expected
rest of the trade is worth less than selling now"; (2) training uses every graduation of the older months, not only the
Pick-like coins; (3) it is judged against the live rule v3, the rule it would replace.

## Data

- The five windows of research/MONTHS-2026-10-23.md / PREREG-CHARTEXIT-2026-10-24.md: w1 25 Apr-24 May, w2 25 Jun-24 Jul
  (GeckoTerminal, branch monthsdata), w3 10 Aug-9 Sep, w4 10 Sep-8 Oct (history2 as five-minute candles, branch monthsh2;
  windows touching a recorder outage dropped as there), w5 9-21 Oct (GeckoTerminal). Five-minute USD candles of the first
  48 h after graduation, wicks beyond 5x the close count as the close (memebot.hold_wicks).
- SOL and BTC by hour (monthsdata market.json, Binance); only hours finished before the decision are used.
- Launch facts from the chain and the metadata files (branch rocketschain, chain.parquet; research/rockets): links (X,
  Telegram, website), description length, video, name and ticker length, CJK letters in the name, the creator's earlier
  graduations in this table (30 days before), the bonding-curve time and signature count where present. Missing stays missing.
- Not available for all five windows and so not used: holders, buyer and seller counts and wallets (GeckoTerminal candles have
  none; history2 has them only for w3/w4, and the live Pick does not see them either). Said in the report.

## Who is traded

- Test buys (main): the Pick-type coins (family P) exactly as research/chartexit/check_chartexit.py coin_path (the Pick's gates as
  far as candles hold them, whole hours 6-24 h after graduation, one entry per coin, entry at the last finished candle's close);
  expected w4 356 and w5 185 coins as in research/chartexit/result.json.
- Test buys (second, more coins): the wide universe W of w4 and w5, one entry per coin: its first whole hour 6-24 h after
  graduation with market cap 50k-5M USD, liquidity >= 10k, 24 h volume >= 5k.
- Training (as many coins as there are): every coin of the training windows with at least one W entry; per coin its P entry if
  it has one and up to 3 further W entries drawn at random (seed 7). Every five-minute candle after the entry while the base rule
  still holds the position is a training state. If a fit would have more than 6 million states, a seeded uniform sample of 6
  million is used (every coin keeps at least its first entry's states).

## What the model sees (all computed from candles up to the decision candle's close; nothing later)

The position: minutes since the entry, price over the entry, highest high and lowest low since the entry, price under that
high, minutes since that high. The coin now: minutes since graduation; log returns over 5, 10, 15, 30, 60, 120, 240, 360 min;
the last 24 five-minute log returns one by one (the shape); volatility of the five-minute returns over 30 / 60 / 180 min; place
in the 1 h and 4 h range; price under the high and over the low since graduation; up-candle share and the run of falling closes;
the last candle's body and wicks; volume (USD) over 5 / 15 / 60 min, the last hour over the hour before and over the entry
hour, share of candles without a trade over the last 1 h / 3 h, volume on up candles over all volume (1 h), volume over market
cap; market cap and liquidity (constant product from the start reserves, as check_months) and their ratio. The market: SOL over
1 h / 6 h / 24 h, BTC over 24 h. The clock: hour of the day (UTC), weekday. The launch facts above. About 80 numbers.

## The models

LightGBM, L2 regression, fixed settings (no tuning on test data): learning rate 0.05, 63 leaves, at least 2,000 states per leaf,
feature fraction 0.7, bagging 0.7, L2 penalty 10, at most 1,500 trees, early stop after 100 on the last 15 % of the training
coins by graduation time, seed 7, 3 threads.

The label is the value of holding: G = (what the position is sold for later, under the given policy from the next candle on)
/ (the price now). Selling now is worth 1 (the sell fee is the same either way). Sell when the model's expected G is below
1 - m.

- A1 "learned exit": base rule B0 = floor -50 % on the lows (booked at the low), 11x take-profit, 12 h limit, nothing else.
  The model learns G under B0; the policy sells at the decision candle's close when the prediction is below 1 - m (the floor
  and 11x stay as safety).
- A2: one more round of policy iteration: G recomputed under A1's policy (A1's predictions out of fold, 4 folds by coin), a
  second model fitted on it, the policy uses the second model.
- B "overlay on the chart exit": base rule v3 as live (floor -50 %, 11x, trail 15 % once the high reached 1.5x, out on a close
  -15 % under the close 30 min before, 6 h). The model learns G under v3; the policy is v3 plus "sell now when the prediction
  is below 1 - m". It can only sell earlier than v3, never hold longer.
- Margins m: 0, 0.03, 0.06, 0.10. Decision every five-minute candle, or only every third (every 15 min). 3 x 4 x 2 = 24
  configurations.

## Choosing and testing

1. Choice (validation): every configuration fitted on w1+w2, judged on w3's P coins; the one with the best mean money
   difference to v3 per 50 EUR trade is chosen (ties: A1 before A2 before B, larger margin, 15 min before 5 min).
2. The chosen configuration is fitted again on w1-w3 (the same way) and judged on w4 and w5: P coins main, W coins second.
3. Money as everywhere: 50 EUR ticket, paper fees (1 % a side, at least 0.10), floor and trail booked at the candle's low,
   other sells at the close. Paired per coin against v3 and K on the same buys; 95 % and one-sided 5 % bootstrap bounds
   (20,000 draws, seed 7, as check_chartexit.boot).

**The user's bar (a rule counts only if it holds a whole unseen month): the model HOLDS if on w4 (10 Sep-8 Oct) its mean
difference to v3 is above 0 with the one-sided 5 % bound above 0, and on w5 the difference to v3 is not negative.** Profitable
is a separate question (mean per trade above 0); reported, not expected.

Also reported (not the bar): the same against K; the W test; walk-forward w1-w4 -> w5; per window in profit share, trades
ending at 2x / 3x or more, trades losing 20 EUR or more, best 2 %; why trades were sold.

## How well can the next move be predicted at all (diagnostics, the user's own question)

On w4, models fitted on w1-w3: (a) the value model's out-of-sample fit (R², rank correlation, the realised G by deciles of the
prediction); (b) a separate LightGBM classifier (same features and settings, binary log loss) for "is the price 30 min from now
lower than now": accuracy and AUC on w4, against the 50 % of a coin flip and the base rate; (c) the hindsight bound: selling every
P coin at the highest high of its 12 h (nobody can do this), to show what is on the table.

Checks against fooling ourselves: a placebo (the chosen configuration with G shuffled among states at the same minute since
the entry) fitted on w1-w3 and judged on w4 must not beat v3; a test that changing candles after the decision does not change
any feature.

## If it holds / if it fails

If it holds: the report says so, and what live would need (five-minute candles for the last 24 h of each open position, the
launch facts at the buy). Nothing is switched: a Pick sell-rule change restarts the Pick account and needs the user's explicit
yes in the project chat. If it fails: the report says plainly why (how little of the next move is predictable), and the live
rule stays v3.

Compute: in this container only (4 cores); no GitHub Actions runner is used, so the live scans are not touched.

## Amendment 1 (25 Oct, 00:05 UTC; after counting entries, before any label, model or result was looked at)

The W universe holds only 5,439 coins over all five windows (3,669 in w1-w3): most graduations fall under 50k market cap within
six hours. The user asked for as many coins as possible ("Nimm so viel du kannst"). So the training universe becomes a choice
of the validation step, with two options:

- W: as above (whole hours 6-24 h, market cap 50k-5M, liquidity >= 10k, 24 h volume >= 5k; the P entry and up to 3 random W
  entries per coin).
- ALL: every coin of the training windows that is still tradeable an hour or more after graduation: whole hours 1-24 h, market
  cap 30k-10M, liquidity >= 8k, at least one trade in the hour before; per coin the P entry, the W entries above and up to 3
  further random ALL entries (seed 7). About 10,900 coins in w1-w3 (16,000 over all windows) instead of 3,669; the minutes since
  graduation are one of the numbers, so the model can tell young from old coins.

Graduations that never come back to 30k market cap after the first hour are not tradeable for the Pick and are left out.
The choice step now has 2 x 24 = 48 configurations (ties: W before ALL). The test buys (P, and W for the second test) do not
change.
