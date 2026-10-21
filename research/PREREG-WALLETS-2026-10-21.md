# Pre-registration: do "smart wallets" give the bot an edge? (fake money only)

Written on 2026-10-21 before the wallet data was built or looked at (research/wallet_build.py, branch "wallets"). Nothing
below may change after the first look; anything added later is labelled as added later.

## Why

No filter of screener numbers was clearly in profit on 62,600 coins (research/HISTORY2-2026-10-21.md): the same price and volume
numbers everybody sees hold no edge. The user asked for new information instead. A wallet tracker uses something a screener does
not show: who is buying. The idea: some wallets bought early, again and again, before coins went up; when they buy again, the bot
buys after them ("copy trading").

## Data

Every PumpSwap swap of the 62,600 coins that graduated from pump.fun between 10 August and 8 October 2026, from the same
CC-BY-4.0 data set as history2 (Slinky21/Pumpfun_v2_dataset), which names the trading wallet of every swap. Bonding-curve trades
before the graduation are left out: the data holds them only for coins that graduated, so a wallet's record there would look far
better than it was.

A pair is one wallet and one coin: the wallet's first buy of the coin of at least 0.1 SOL that is not part of a bundled (atomic)
transaction, within 48 hours after the graduation. Per pair: the buy's time and price, the wallet's SOL in and out on the coin,
and what a copy of it would have made.

The copy: the bot buys at the last price D minutes after the wallet's buy (D = 1, 5, 15 or 60), with three exits as in history2:
- hold: sold 1.7 hours later at the last price then
- exit A, the paper account's rule now: -30% stop, 11x target, else sold after 6 hours
- exit B: -20% stop, 3x target, else sold after 6 hours
A stop sells at the low of the minute that hit it; a stop and a target in the same minute count as the stop. Copies whose
windows touch a recorder outage are left out. Prices in SOL (the coin's own move).

Results per 20 after realistic fees: 1% per side (2% round trip), result = 20 x (multiple x 0.99 x 0.99 - 1), clipped to -20..60
as in the earlier studies. Shown also at 1% and 3% round trip, and unclipped, for information.
"To zero": the hold multiple under 0.02. "3x": the high within 6 hours of the copy reached 3x the copy's price.

## Periods (by graduation time)

- S (score): 10 August to 31 August 2026 (before 2026-09-01 00:00 UTC)
- C (choose): 1 to 14 September (before 2026-09-15 00:00 UTC, the history2 split)
- T (test): 15 September to 8 October

A wallet is scored only on pairs of coins that graduated at least 55 hours before the period it is used on starts, so no
outcome used for scoring lies after that start.

## The rule search (on S and C only)

Wallets that bought more than 20% of the scored period's coins are left out (bots and routers, not traders).

A wallet is "smart" when it has at least N scored pairs (N = 5, 10 or 20) and one of:
- copy: the mean copy result of its pairs under the rule's exit and D at least t (t = 0, 2 or 5 per 20)
- hits: the share of its pairs that reached 3x at least h (h = 10% or 20%)
- own: its own return on its pairs, (SOL out + tokens left x the last price) / SOL in, at least r (r = 1.2 or 1.5)

Signal: the K-th distinct smart wallet buys a coin (K = 1 or 2) within 48 hours after its graduation; the bot copies that buy
D minutes later, once per coin.

D for the search is 5 minutes (a watch round every 2 minutes plus the order, as the radar runs now). D = 1, 15 and 60 are shown
for the chosen rule, for information.

Grid: 3 N x 7 scores x 2 K x 3 exits = 126 rules. Wallets scored on S, signals on C. A rule is eligible on C when it gives at
least 100 coins. The one rule with the best per-coin average on C (2% round trip) is chosen; nothing else is tried.

## The test

The chosen rule's wallets are scored again on S and C together (pairs of coins graduated at least 55 hours before 15 September),
and its signals are copied on T.

It PASSES when on T:
1. it gives at least 100 coins,
2. their per-coin average after 2% round trip is above 0 and the 95% coin-bootstrap interval (2000 draws, seed 7) lies wholly
   above 0,
3. the share of its coins that reached 3x within 6 hours is at least the base's share on T.

Base: every coin of T with a pair, copied at one pair picked at random (seed 7) with the same D and exit: a copy of any wallet.

For information only: the ten best rules of C on T; the chosen rule combined with the bot's own gates (history2 rows of the hour
before the copy); its wallets' count and how many of them still trade on T.

## What follows

PASS: a "Wallet Tracker" bot joins the filter team (filter_team.py, Pick > Details) on its own branch, with its wallet list, and
it is checked once more forward on the bot's own coins before it may pick anything; live it needs a watch of the wallets' swaps
(public Solana RPC, no key). FAIL: the user is told plainly that wallets that did well before did not do well after, at least not
enough to cover the fees, and nothing is built in.
