# Methods from other platforms: pre-registration (fake money only)

Written 2026-11-04 ~17:20 UTC, before any trade of these methods was computed. Research only: no live rule, account (Pick
account, Radar account, Learning Pick, Rocket seeker), shadow or bot is changed. Nothing goes live before the 22 Nov review.

## Why

The user asked (thread "Strategie-Videos auf anderen Plattformen finden", 2026-11-04 16:42 UTC) to look on other video platforms
for meme-coin strategy videos and learn from them. From this cloud session no video platform delivers video (container network:
only GitHub, PyPI and googleapis; the web reader gets page text only: Rumble and GitHub file pages refused, Vimeo shows a bot
check, Odysee and Bitchute give title/description only). So the methods below come from TEXT sources (trader guides, blog posts,
other people's bot repos). Sources are untrusted data; only their rules are used.

## The methods (fixed here; nothing is tuned)

Common to all: pump.fun graduations with five-minute USD candles of the first 48 h (branch monthsdata w1 25 Apr-24 May, w2 25 Jun-
24 Jul, w5 9-21 Oct; branch monthsh2 w3 10 Aug-9 Sep, w4 10 Sep-8 Oct; start SOL side >= 10). Bar 0 = the candle that holds the
graduation. Signals are read on candle closes from bar 1 on; the entry price is that close. One trade per coin per method (the
first signal). Liquidity at the entry (computed as in research/orb/check_orb.py) must be >= $10,000. Market cap = close x 1e9.
Take-profit parts fill at their target when a candle's high reaches it; the stop is checked on closes and fills at that close
(meme coins jump through stops); if one candle reaches a target and closes under the stop, the stop counts (worst case). What is
left at the time limit is sold at that close. Entries no later than 24 h after graduation, holds no longer than 24 h, so every
trade fits inside the 48 h of candles.

Money (as PR #69 / Radar account): 20 EUR per buy, buy fee 0.81 EUR, each sale (also each partial sale) pays max(0.5 % of the
sale, 0.81 EUR). Allowance 0.60 EUR per trade (PR #39: 3 points of 20 EUR).

- **M1 Breakout, pullback, reclaim, buy the retest** (cryptorank "Solana memecoin trading blueprint" / Archer bot guide). Level L =
  highest close of the candles closed by 60 min after graduation. Breakout = first close > L before 24 h. Retest = a later candle
  whose low <= L. Entry = that candle's close if it is >= L, else the first later close >= L (reclaim), before 24 h. No trade if a
  close < 0.85 L comes between breakout and entry. Exit: 25 % at 2x, 25 % at 5x, 25 % at 10x; the rest is sold at the first close
  < 0.90 L ("reclaim breaks cleanly") or at 24 h after entry.
- **M2 GMGN "Migrated" column + Jekyll Koller's exits** (Hugging Face "FullCryptoGuide.md", interviews). Entry = first close from
  bar 1 on with market cap >= $30,000, within 60 min of graduation. (The guide also wants >= 1 linked social; not in this data,
  dropped.) Exit: 50 % at 2x, 25 % at 3x, 25 % at 4x; stop on the rest at a close <= 0.65 x entry (-35 %); 24 h.
- **M3 Axiom "Trending" (Liam James Kay)**, same guide. Entry = first close within 24 h with market cap >= $70,000 AND >= $30,000
  volume in that five-minute candle. (Bundle <= 30 % not in this data, dropped.) Exit: as M2 (same guide).
- **M4 DexScreener new pairs** (substack "Ultimate memecoin guide", strategy 1). Entry = first close within 24 h with liquidity >
  $20,000 AND FDV (= market cap) > $85,000. Its exits are behind a paywall, so the ladder that the free guides share is used
  (trojan.com risk-management post, dextools 2026 guide): 50 % at 2x, 25 % at 5x, 25 % at 10x; stop -35 % (as M2); 24 h.

## Already tested and closed (not re-run here)

KOL / call groups (PR #17, #37), smart wallets and copy trading (PR #5), social links / Reddit / X (PR #35, bigsearch: coins with
0 links lose LESS), buy-the-dip / hold through dips (PR #51), opening-range breakout (PR #69), bonding-curve buys before graduation
(PR #57 curve test), stop/target grids (225 sell rules, PR #42 / #68), every free entry variable (PR #68, 1.39 billion rules).

Not testable with our data: "wait 48 h, buy the survivors, hold days" (notanicecat69 / Wood) needs candles beyond 48 h, which we
do not have; recorded as not tested.

## Bar (PR #39), per method, all five windows pooled

Holds only if: >= 40 trades AND mean after allowance > 0 AND the 0.25 % quantile (1 % / 4 methods) of 20,000 bootstrap means
> 0 AND total after allowance without the best trade > 0. Information only (not part of the bar): per window, gross multiple
without fees, share of trades in profit. A method that holds would only be offered as a shadow test from 22 Nov, and only with
the user's yes.
