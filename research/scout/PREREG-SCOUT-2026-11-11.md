# Does the video's coin choice pick better coins? Pre-registration (fake money only)

Written on 2026-11-11 before any outcome of these rules was computed. Only the data probe (schema, file list) ran before.
Nothing is bought: paper money, past data.

## What the video shows (Trading Desk TikTok, read frame by frame)

- The terminal says "Grok Bot picks every click via the xAI API; X via x_search": an LLM chooses, with X search. No formula.
- X Scout log: 6.4x posts / 98 real, 5.1x / 64, 5.8x / 77, 5.6x: "size check", bought. 4.4x / 52, 4.2x / 41, 3.9x / 37,
  3.1x / 22: "wait" (three of them bought a few minutes later). So the visible bar is about 5x the normal post rate.
- Buys at $14.2K, $18.4K and $27.6K market cap (one 1 h 12 min old): pump.fun coins still on the bonding curve.
- X posts have no free history. Stand-in: the same shape on the chain, buys instead of posts, distinct wallets instead of
  "real accounts".

## Data

Slinky21/Pumpfun_v2_dataset (CC BY 4.0), table "trade": every pump.fun bonding-curve trade, with wallet and time. The newest
14 full UTC days that have trade files: the older 7 are the dev days, the newer 7 the holdout. SOL/USD hourly from Coinbase.
Price of a trade = SOL amount / token amount; market cap = price x 1e9 tokens x SOL/USD.

## Rules (each coin is bought at most once per rule: its first signal)

Checked at every whole minute t, on trades before t only.

- **V1 Scout (the video's shape).** Buys in the last 5 minutes at least 5 times the coin's normal rate (its buys per 5 minutes
  from launch to t-5 min, floor 2), at least 50 distinct buyer wallets of 0.05 SOL or more in those 5 minutes (creator not
  counted), coin at least 10 minutes old, market cap $10K to $60K.
- **V2 Fresh (Maxim).** The coin at 5 minutes of age, if it has at least 20 distinct buyer wallets of 0.05 SOL or more so far
  and a market cap of $10K to $60K.
- **V3 Bottom (Maxim).** Coin at least 30 minutes old, price at least 50% under its high so far, the lowest price of the last
  30 minutes reached at least 5 minutes before t, price now at least 20% above that low, at least 20 distinct buyer wallets in
  the last 5 minutes, market cap $10K to $60K.
- **Rug filter R** (free, from the trades): the creator has sold nothing before t, and the 10 largest net holders (wallets,
  creator included, bonding curve excluded) hold under 35% of the supply. Mint and freeze authority are revoked on every
  pump.fun coin and the curve has no LP to lock, so those checks say nothing here and are left out.

Primary cells: V1, V2+R, V3+R. Secondary (information only): V1+R, V2, V3, and V1 with 3x / 10x, 25 / 100 wallets.

## Trade

Entry at the first trade 30 seconds or more after t (FOMO's delay), price +1% slippage. Sell rules of the video, unchanged:
-8% hard stop while 2x was never reached; at 2x sell enough to get the stake back; the rest sells 10% under its high; end after
24 h or at the coin's last curve trade (graduation or death) at that price. Every sell at the trade price that crossed the line,
-1% slippage. Ticket 20 $, FOMO fee 0.5% per trade, at least 0.50 $ (the half sale is its own trade); also shown with the
memebot minimum 0.81.

## Baselines (same days)

- **Matched control:** for every buy, one random other coin of the same rule window: market cap $10K to $60K, at least
  10 minutes old (5 for V2), a trade in the last 5 minutes, at the same minute; bought and sold the same way.
- For reference only (other coins, other days): the desk rules on the bot's 840 tips, -2.34 per 20 (research/DESK-2026-11-11.md
  on trencher-extension), and on new launches, -5.63.

## Pass bar (per primary cell, on the 7 holdout days)

PASS only if all hold: at least 30 trades; average per 20 after fees above 0; the 95% bootstrap interval by day of
(rule minus matched control) above 0; the average without the single best trade still above 0.
"Picks better, still loses": the interval vs control above 0 but the average 0 or below.
Otherwise FAIL. Three primary cells are tested, so one pass among them is weaker evidence than it looks; a pass on the
holdout that points the other way on the dev days is noise. Nothing is re-tuned on the holdout. Losses are reported like wins.

## Trap checks (reported)

Without the best trade; one day removed at a time (largest day); share of trades ending at -8%, at a total loss (98% down),
at graduation; trades per day; the max-2-open portfolio of the video replayed on the holdout for information.
