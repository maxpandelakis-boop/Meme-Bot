# Pre-registration: the "100% winrate" call channel of the third video (22 Oct 2026, fake money only)

Written before any outcome of this test was computed (only the entry side was looked at: how many pools, their start reserves,
where the data ends). Check script: research/check_calls.py.

## The video (TikTok @onlyplus4us, 25.6 s, music only, no speech)
A phone films a monitor with a Discord channel "inner-circle-calls" ("Every call instantly, live signal, entry zone, trade
plan"). A bot "Only Plus Bot" posts "INNER CIRCLE CALL" cards and "SMART WALLET BUYING" alerts. The caption says "100% winrate".
Each card shows:
- Score n/100 (69 to 84 on the cards seen), "called at $23k to $88k MC", "PumpSwap, 2 / 5 / 10 min old" (a pump.fun coin minutes
  after its graduation), RugCheck, X post, website.
- "Entry zone" of about the call's market cap -10% to +10%, "only on a dip".
- Safety: mint and freeze revoked, LP 100% locked, top 10 holders 18-25%, dev 0%, insiders 1-7%; sometimes "n smart wallets holding".
- "Bot trade plan, quick trade": TP1 +30-40% -> take 50% profit; TP2 1.2x-1.6x possible; stop -30% = out.
- A result tile "+72% ... +791%, peak since the call".

What the cards themselves say: of the 16 calls in the video, 12 can be read clearly; 10 of those show "LIVE · Stop hit – get out"
with the market cap now 37% to 90% below the call (for example $HUMANOID: called at $46.5k, peak $414k = 8.9x, now $23.5k;
$SACTII: called at $33.4k, peak 1.98x, now $6.8k; $GENESIS: $23.4k, peak 1.53x, now $3.9k), 2 show "Too late – don't chase"
and were still far up ($JONATHAN: $86.7k, peak 5.3x, now $384k; $4: $38.9k, peak 5.5x). The "+%" on the tiles is the highest
price after the call, not a sale. "100% winrate" therefore means "every coin shown went above the call price at some moment".
One card ($GENESIS) names "pump.fun, 23 min old", a coin before its graduation; those are not in this data (PumpSwap swaps only).

## Already tested here (not run again)
Copying smart wallets / insiders (21 Oct), copying KOL wallets (KOL-2026-10-22.md, -6.24 per 20), the rocket hunter at 5 to 30
minutes with 134 exits whose smallest target was 2x (winlose/EARLY-EXIT-2026-10-22.md), 213k filter rules (SEARCH, HISTORY2).
The channel's score and its holder numbers (top 10, dev, insiders) cannot be rebuilt from swaps; on PumpSwap every graduated
pump.fun coin already has mint and freeze revoked and its LP burned, so those checks pass for every coin anyway.

## New here, and tested
1. The entry: every graduated coin at 2, 5 or 10 minutes after the graduation, inside the cards' $20k-$90k market cap.
2. The quick-trade exit with a +30% first target (never tested: the smallest target so far was 2x).
3. How often a "peak since the call" of the sizes shown happens at all, and how often the same coin also hits the -30% stop.

## Data
history2 (Slinky21 Pumpfun dataset, CC BY 4.0) coins.parquet and one-minute bars of the first 25 hours (branch chartbars),
SOL/USD hourly (marketctx). Coins: pump.fun migrations with start reserves of 80 to 90 SOL (the normal 85 SOL migration; about
10% of the pools have under 1 SOL and are not real migrations), graduated 10 Aug 00:00 to 7 Oct 20:00 UTC (the data ends 8 Oct
03:30). Bars as the live code builds them (features.dense fill_hl=False: a minute without a trade has high = low = the last
close). A coin is left out when a recorder outage minute (gap_minutes.npy) falls between its graduation and the end of its path.

## Variants (3 x 2 x 3 = 18, plus rule A for reference)
- Call minute C: 2, 5, 10. Call price = the close of minute C-1. Market cap at the call (price x 1e9 x SOL/USD) must be $20k-$90k.
- Entry: "call" = buy at the call price, the path starts at minute C. "dip" = a limit buy at 0.95 x the call price, valid 30
  minutes; it fills in the first minute whose low reaches it (at that price), the path starts the minute after; no fill = no trade.
- Exit (all with a -30% stop on what is still held and a 6 h limit at the last close):
  X1 the video's plan: 1/2 at 1.30x, the rest at 1.60x (top of "TP2 1.2x-1.6x").
  X2: 1/2 at 1.30x, the rest at 1.40x.
  X3: all at 1.30x.
  A (reference only): -30% stop, 11x, 6 h (the rocket hunter's rule A).
- Fills as rocket_exits.walk: a stop sells at the low of the minute that crosses it, a target at its level, a stop and a target
  in the same minute count as the stop; a pool without more bars keeps its last price.

## Outcome and when a variant holds
Per 20 after memebot's fees: the buy and every sale each pay 0.5%, at least 0.81 (a partial sale pays its own fee), not clipped.
Early weeks = graduations before 25 Sep, late weeks = from 25 Sep.

**A variant holds** when all are true: (a) per 20 above 0 in the early weeks and in the late weeks; (b) over all weeks the 95%
range of the mean per 20 (bootstrap over days, 2,000 draws) is above 0; (c) at least 90% of filter_search.simulate's 10,000 runs
(blended price multiple, fee 0.5-2% per side, slippage 0-4% per day) end in profit.
Several hold: the one with the best early-weeks per 20. That one is then checked once more on the graduations of 9-21 Oct
(backfill grads.json, one-minute candles fetched in a workflow) with (a) above 0 there and (c); only if it holds there too is it
offered to the user as a bot change. Nothing switches without the user's word; the Pick account and its sell rule are untouched.
None holds: nothing is built, and the 9-21 Oct fetch is not needed.

## For information (decides nothing)
- The "winrate" of the calls: share whose highest price within 24 h after the call reaches +30%, +72% (the smallest tile seen),
  +100%, +200%; of those, the share that also falls to -30% within the 24 h, and the share below the call price 24 h later.
- The same 18 variants with the stop filled at its level (kinder), with targets first in a shared minute (kinder), with 1% per
  sale and no minimum (a bigger ticket, still without slippage), and with no fees at all (the raw edge).
- Per week per 20 for the variants, coins, in profit of 10, sold at least half at +30%.

## Addendum, 22 Oct ~16:45 UTC: more data, as the user asked (written after the history2 run, before any new data was fetched)
The history2 run is done (research/calls/calls-check-2026-10-22.json): no variant holds, so by the rules above nothing is built
and the extra data cannot change that decision. The user asked (22 Oct, 16:24 UTC) for as much data as possible, "years if
available". What exists for free: pump.fun started in January 2024, its graduations went to Raydium until March 2025 and to
PumpSwap since; GeckoTerminal's free API serves candles of the last 6 months only (older needs a paid plan); the public
Hugging Face sets found today hold bonding-curve trades or a few days, no longer post-graduation price paths than history2.
So the extra data is the free part: research/calls_fetch.py (workflow calls-history.yml) lists the graduations of 25 Apr to
9 Aug 2026 and 9 to 21 Oct 2026 with Helius and fetches each pool's one-minute candles of its first 1000 minutes from
GeckoTerminal (USD prices). 25 Apr to 9 Aug: a random sample of at most 300 graduations per day (seed 7); 9-21 Oct: all.
The same 18 variants and rule A are replayed on it (check_calls.py ext) with these differences, fixed now:
- "Normal migration": start reserves within 5% of the period's most common start reserves (85 SOL in history2; the backfill
  list of 9-21 Oct shows 67.4 SOL, so pump.fun changed it between 8 and 9 Oct).
- Market cap = GeckoTerminal's USD price x 1e9 (pump.fun supply). A minute without a candle: high = low = the last close. No
  recorder outages exist here; a pool GeckoTerminal does not know is left out.
- The "winrate" numbers use 16 h after the call (1000 minutes of candles), not 24 h.
Reported per period (25 Apr-9 Aug, 9-21 Oct) and together, with the same columns. It decides nothing new: a variant would only
count if it held here AND in history2.

## Addendum 2, 22 Oct ~18:45 UTC (before any candle of the extra days was fetched)
Helius' migration account carries far more transactions than graduations from late May on (25 May-25 Jun: 11,250 pages of 100
transactions held only 4,838 graduations when the 2 h limit stopped the job), so the lists of 25 May-24 Jun and 25 Jul-9 Aug
did not finish; listing them again would cost several hundred thousand more Helius credits. The extra days are therefore
25 Apr-24 May, 25 Jun-24 Jul and 9-21 Oct (36,373 graduations listed). To spend the GeckoTerminal calls on coins the test can
use, the daily sample of at most 300 is now drawn among the normal migrations only (the rule of addendum 1: start reserves
within 5% of the most common ones before / from 9 Oct, 85.0 and 67.4 SOL), instead of among all graduations. Nothing else changes.
Seen on the lists (no outcome): from about 22 Jul a second kind of migration with 67.4 SOL appears next to the 85 SOL one, and
from 9 Oct only 67.4 SOL; before 9 Oct the 67.4 SOL coins are left out by the rule.
