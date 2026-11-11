# Does following wallets that made profit before make money? Pre-registration (fake money only)

Written on 2026-11-11 before any outcome of these rules was computed. Nothing is bought: past data, paper money.
Asked by Maxim ("make the system perfect"); the coordinator's reading: test copy trading of wallets with a proven record on fresh
Solana meme coins, with free on-chain data, and build it into the Scout as a paper option only if it earns after fees.

## What is already known (not repeated here)

- Copying wallets chosen by their own past results on graduated coins, 15 minutes late: FAILS, -3.90 per 20 on 154 coins
  (research/WALLETS-2026-10-21.md on claude/project-thread-8bj1z4). Copying 62 named KOL wallets: FAILS, -6.24 per 20
  (research/KOL-2026-10-22.md).
- Four coin rules on the bonding curve: all FAIL (research/scout/SCOUT-2026-11-11.md on claude/project-thread-0y2vt9).

New here: the bonding curve (where the fresh coins trade), a 30 second delay instead of 15 minutes, the exit copied from the wallet
too ("sell when they sell", Maxim's first video), FOMO's real fee, and wallets chosen by what a COPIER would have earned, not by
what the wallet itself earned.

## Data

Slinky21/Pumpfun_v2_dataset (CC BY 4.0), table "trade": every pump.fun bonding-curve trade with wallet, slot and time,
10 Aug to 8 Oct 2026. One job per launch day L: the coins launched on L (mayhem-mode coins left out, as before) with their curve
trades until L+2 days 04:00 UTC. Trades after the graduation (PumpSwap) are not in it: a path ends at the coin's last curve trade.
Launch days 4 to 7 Sep are left out everywhere (the trade files of 5 Sep 03:08 to 7 Sep 03:10 are a fraction of the usual size).

## Event (the thing that can be copied)

A wallet's first buy of 0.05 SOL or more in a coin; the coin's creator is not counted. One event per wallet and coin.

- **Copy entry:** the coin's first trade 30 seconds or more after the wallet's buy, price +1% slippage. No such trade: no copy.
- **Mirror exit (judged):** the coin's first trade 30 seconds or more after the wallet's first sell that follows its buy, price
  -1% slippage; earlier if the price reaches 10 times the entry (sold at the trade that crosses, the video's take profit); at the
  latest 24 hours after the entry or at the data end, at the last trade before. If the coin has no later trade, the last trade's
  price. If the curve completed (80 SOL or more in the curve) and the path ends before the wallet sold, the last curve price
  minus 10% (the move to PumpSwap, as in the scout study).
- **Result per 20 $ ticket:** 20 x (exit / entry) - 20 - fee(20) - fee(proceeds); FOMO's Solana fee per buy and per sell: under
  5 $ flat 0.10; 5 to 47.50 $ 2%; 47.50 to 190 $ flat 0.95; from 190 $ 0.5%.
- **The wallet's own result on the coin** (for the naive list): SOL from its sells minus SOL of its buys from the event on, what
  it still holds valued at the coin's last curve price in the job's window. pump.fun's own 1% fee is not subtracted (kind to it).

## Wallet lists (walk-forward, nothing fitted on the tested day)

For a test launch day d the lists are built only from the launch days d-23 to d-3 (21 days; the job of d-3 ends at d-1 04:00, so
nothing of day d or later is seen). Events with a copy only.

- **W1 naive winners:** at least 10 events, the wallet itself in profit on at least 50% of them, the 300 wallets with the largest
  own total profit in SOL. This is what "top trader" leaderboards show.
- **W2 copyable:** at least 10 events, the copier's average result (mirror exit, FOMO fee, per 20 $) above 0 with
  average / standard error of at least 2; the 300 wallets with the largest such ratio.
- **W3 two agree:** a coin bought by two different W2 wallets; the trade is the second wallet's event.

Each rule buys a coin once: the first event of a listed wallet (W3: the second listed wallet's event). Parameters (21 days, 10
events, 300 wallets, ratio 2, 30 s, 0.05 SOL) are fixed here and are not tuned.

## Days

Test launch days 2 Sep to 6 Oct 2026 without 4 to 7 Sep. **Dev:** 2 to 19 Sep (14 days). **Holdout:** 20 Sep to 6 Oct (17 days),
printed only by a second run after the dev numbers are written down. The lists are not changed between the two; if the dev days
show a bug (not a bad result), the fix is written here as an amendment before the holdout run.

## Baselines (same launch days)

- **Random wallet:** every event of the day (any wallet), same copy, same exit: the average per launch day.
- **Same coins, other wallets (information):** every event in the coins the rule bought: does the wallet matter, or only the coin?

## Pass bar (per list, on the holdout days)

PASS only if all hold: at least 30 trades; average per 20 $ after FOMO fees above 0; the 95% bootstrap interval by launch day of
that average above 0; the average minus the random-wallet baseline of the same days above 0 in its 95% interval; the average
still above 0 without the single best trade and without the single best wallet. "Picks better, still loses": the interval against
the baseline above 0 but the average 0 or below. Otherwise FAIL. Three lists are tested, so one pass among them is weaker than
it looks; a pass on the holdout that points the other way on the dev days is noise. Losses are reported like wins.

## Reported with it (decides nothing)

- Trades per day, share in profit, median, share of exits by kind (wallet sold / 10x / time or data end / graduation), median
  seconds between the wallet's buy and its sell, share where the wallet sold within 30 seconds.
- Concentration: trades and result of the 5 most active listed wallets; result by market cap at entry (under 10K, 10K to 30K,
  over 30K $) and by coin age at entry (under 2 min, 2 to 15 min, older).
- The same trades with the video desk's sell rules (-8% stop until 2x, stake out at 2x, 10% trail), held 24 h or to the
  graduation, with a 5 second delay instead of 30, and with a Jupiter-like fee (no platform fee, 0.05 $ network per trade).
- How stable the lists are: the share of a day's W2 wallets that are still on the list 7 days later; and the listed wallets'
  result in the list window against their result on the test day (how much of the record is luck).

## Limits

Only the bonding curve: a wallet that earns its money after the graduation is not found, and a sell after the graduation is not
seen. A copier's own buy would move the curve a little (20 $ is about 0.3% of a fresh curve); the 1% slippage a side covers it.
FOMO's delay is taken as 30 seconds; nobody measured it.

## Dev days seen (2026-11-11 13:10 UTC, before the holdout run; walletdata commit 9182ea3)

Per 20 $: W1 -1.38 (47,115 trades, 0 of 14 days), W2 -0.55 (597 trades, 95% -1.46..+0.30), W3 +1.18 (125 trades, 95%
-0.84..+3.29); random wallet -2.59. No bug found, nothing changed: the lists, the exit and the pass bar stay as written above.
Two files had another column type and a few rows had empty fields (fixed in the reader before these numbers; the first start
lacked 13 and 14 Aug and is replaced).
