# Which free filters make the fresh-coin Scout pick better coins? Pre-registration (fake money only)

Written on 2026-11-11 before any outcome of these filters was computed. Nothing is bought: paper money, past data.
Asked by Maxim: "pick what fits best from the repo search and make the Scout better", and "look whether there are better
coin filters in general".

## What is tested

The live fresh-coin desk (trencher/scout.js `freshOk` on trencher-extension, v0.9.2) buys pump.fun coins a few minutes old.
The question: among the coins that Scout would buy, does a filter that is free to compute keep the better ones, after
FOMO's fees?

## Data

Slinky21/Pumpfun_v2_dataset (CC BY 4.0): every pump.fun bonding-curve trade with wallet, slot and time, the create table
(creator, symbol) and the graduate table. Launch days 2026-08-17 to 2026-10-06 (51 days; the 7 days before the first are the
look-back for the creator's history; 7 Oct is cut by the data end and left out). SOL/USD hourly from Coinbase.

- **Discovery:** launch days 17 Aug to 12 Sep (27 days). Filters may be searched and fitted here.
- **Holdout:** launch days 13 Sep to 6 Oct (24 days). Not opened until the rules are frozen in an amendment below.
  The day jobs write every day's rows to the branch `scoutfilters`; the discovery script reads only discovery days.
- Known from the earlier study (research/scout/SCOUT-2026-11-11.md, other rules, 24 Sep to 7 Oct and 11 Aug to 23 Sep): every
  rule lost after fees; the old rug filter R (creator sold nothing, top 10 under 35%) changed the result by about +0.15 per 20.
  None of the features below was looked at there except R's two parts.

## The base signal (the live Scout, replayed)

Checked at every whole minute t from 1 to 60 minutes of age, on trades before t only. A coin's first hit is its one trade.

- market cap $8K to $250K (curve price x supply x SOL/USD),
- last 5 minutes: at least 15 different buying wallets, buys at least 1.5 times the sells, price above the price 5 minutes
  ago (or the start price when younger).
- Not replayable: the $3K liquidity floor (GeckoTerminal's own number) and the RugCheck call (no history). Mayhem-mode coins
  are left out (other curve).

## Trade

Bought 30 seconds after t at the curve's price then (the price after the last trade before it), +1% slippage; a coin with no
later trade is held at that price. Ticket 20 $, FOMO fee tiers per buy and per sell (under 5 $: 0.10; 5 to 47.50: 2%; 47.50 to
190: 0.95; from 190: 0.5%), every sell -1% slippage.

- **Judged exit (the desk's live rules):** -8% hard stop until 2x; at 2x sell the stake; rest sells 10% under its high; end
  after 24 h or at the coin's last curve trade.
- **Second exit (must not contradict):** hold until the curve completes (sold 10% under the last curve price) or 24 h.
- Information: quick in-and-out (+20% / -10% / 10 min), a Jupiter-like fee case, price 10 and 30 minutes after the buy.

The curve path ends at graduation, which cuts the biggest runners short (as in the earlier study).

## Features (all from trades before t, the create table and the graduate table before the launch)

Creator: coins launched by the same creator in the 24 h and 7 days before, how many of those graduated; creator's buy (SOL),
share of supply held, share of own tokens sold. Launch: different non-creator buyers in the first 10 seconds; non-creator buys
in the create slot and within 4 slots (snipers), their share of supply; most different wallets buying in one slot (bundles).
Holders: top 1 and top 10 net holders' share of supply. Buyers: different buyers and sellers (5 min and all), buys per buyer,
buyers of 0.05 SOL or more, median buy size, share of the 5-minute buy volume from the 3 largest buyers, share of wallets
that bought and sold, how many other coins of the day the median buyer entered before (serial wallets). Flow: buys / sells,
SOL volume and net inflow of 5 minutes. Shape: age, market cap, SOL in the curve, SOL per minute since launch ("slow" vs
"fast" curve), share of the curve's SOL that came in the first 60 seconds, 5-minute price change, price vs the high so far.
Ticker: other launches with the same symbol in the 24 h before. Hour of day (UTC).

## Filters fixed now (thresholds a priori, judged on the holdout)

- **F1 launch factory (rug-radar):** skip when the creator launched 3 or more other coins in the 24 h before.
- **F2 no early demand (rug-radar):** skip when no wallet but the creator bought in the first 10 seconds.
- **F3 dev dumped (rug-radar):** skip when the creator sold 90% or more of the tokens they bought.
- **F4:** skip when any of F1 to F3 fires.
- **F5 slow curve (the qlo idea, moved to the curve):** keep the coins whose SOL per minute since launch is below the discovery
  median. qlo's own claim is about coins after graduation (PumpSwap); that needs the swap table and is a separate check.

## Filters found on discovery (frozen in an amendment before the holdout is opened)

- **D1 to D3:** at most three single-feature filters (one threshold each, keeping at least 25% of the base signals), chosen on
  the discovery days by walk-forward (threshold fitted on earlier days, judged on later ones).
- **M:** one score from all features (logistic regression on "the judged exit ended above 0", fitted on discovery), keeping the
  top 30% of each day by a threshold fixed on discovery.

## Pass bar (holdout, per filter)

- **Helps:** kept coins keep at least 25% of the base signals and at least 30 trades; average per 20 of the kept coins minus the
  average of all base signals of the same days: 95% bootstrap interval by day above 0 with the judged exit; the second exit
  points the same way; same sign on discovery.
- **Profit:** additionally the kept coins' average per 20 is above 0 with its interval by day above 0, and still above 0 without
  the best trade.
- Nine filters are judged (F1 to F5, D1 to D3, M), so one pass at 95% is weak evidence: it is reported as such, and a filter is
  only called solid when its interval also clears 0 at 99.4% (Bonferroni).
- A filter that fails is dead; nothing is re-tuned on the holdout. Losses are reported like wins.

## Trap checks (reported)

Without the best trade; per day and the share of days where the kept coins beat the base; largest day removed; per coin = per
row here (one trade per coin); by hour and by age band; how many signals a day remain (a filter that leaves the desk idle is
said so); whether the filter can be computed live without a key (a filter that cannot is information only).

## What gets built

A filter that "helps" and is computable live for free goes into the fresh Scout (paper desk only). RugCheck and GoPlus values
have no history: they can only be logged by the live desk next to each candidate's later price and judged later.
The real-money switch stays off and untouched.

## Amendment 1 (2026-11-11): the freeze, written after discovery and before the holdout was opened

Discovery (27 days, 23,478 base signals, 870 a day; research/filters/discovery.txt): the base Scout loses 1.35 per 20 with the
desk exits (9.1% of trades in profit, 77% end at the -8% stop; median coin 1.4 minutes old at $10.8K), 5.76 held to completion,
0.66 without FOMO's fee. Fees and slippage alone are about 1.20 per 20.

Frozen (research/filters/frozen.json, made by discover.py; the selection rule was in the code before the data came: walk-forward
interval above 0, direction never flipped, second exit agrees, not the same coins as an earlier pick):

- **F5** median: 22.36 SOL per minute (frozen.json `f5_median`).
- **D1** share of supply bought by other wallets in the create slot >= 26.46%.
- **D2** share of the curve's SOL that came in the first 60 seconds <= 0.583.
- **D3** creator launched no other coin in the 24 h before.
- **M** the logistic score with the weights and threshold in frozen.json (walk-forward on discovery it showed no lift:
  +0.02, interval -0.31..+0.41; it is judged anyway, as registered).

Extras, information only, found by looking at discovery tables (so weaker than D1 to D3; three more tests, 12 in all, Bonferroni
level 99.6% is approximated by the 99.4% interval already computed):

- **X1 no whale:** skip when the largest holder (creator included) holds 20% of the supply or more. On discovery those coins
  (13% of the signals) lose 3.5 to 4.7 per 20: one sale drops the price far through the -8% stop.
- **X2:** creator bought at most 1 SOL and launched no other coin in the 24 h before (discovery: -0.62 per 20, 24% kept).
- **X3:** creator bought at most 1 SOL (the best single feature for the desk exit, +0.79 walk-forward, but the hold exit did not
  agree, so the selection rule left it out of D1 to D3).

Seen on discovery and worth saying: rug-radar's "dev dumped" sign points the other way for the desk exit here. Coins whose
creator had already sold 90% or more did better (-1.10) than coins whose creator had sold nothing (-1.97): a creator who still
holds is the dump that is still to come.
