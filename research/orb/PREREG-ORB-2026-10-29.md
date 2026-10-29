# Pre-registration: the video's "opening-range breakout" on pump.fun graduations (fake money only)

Written on 2026-10-29 ~12:05 UTC, before any breakout trade was computed on any window. Nothing below may change after the first
look; anything added later is labelled as added later. Research only: no live rule, account, shadow or bot is changed (the live
accounts stay frozen until the 4 Nov review).

## Why this is a new test

On 29 Oct the user sent the "day-trader-skill" video a third time (11 Claude skills for US-stock day trading; repo
Jakeschincariol/day-trader-skill). Its "Time Machine" (10,000 replays from the stock's own candles) was already tested twice and
failed: research/TIMEMACHINE-2026-10-21.md (look-alike replays) and research/REPLAYS-2026-10-22.md (the coin's own moves, the
video's method). News, earnings, congress trades and the broker do not exist for meme coins or were tested as social/KOL/wallet
signals (PRs #5, #17, #35, #37). Exits with stop and target were searched in 225 variants (PR #42, PR #68). Daily breakouts on big
exchange memes failed (PR #59).

Not yet tested: the scanner's own example setup, the intraday opening-range breakout (ORB), as an ENTRY TRIGGER on fresh
graduations: wait for the first candle that closes above the range of the first minutes, then buy, with the README's stop at the
range midpoint and target at 1R. Earlier searches bought at fixed times (30/60 min, hourly); none waited for a breakout.

## Data (all free, already on the data branches)

- GeckoTerminal five-minute USD candles of the first 48 h of pump.fun graduations with start SOL side >= 10.
- FIT: w1 (25 Apr-24 May 2026, 6,830 graduations) and w2 (25 Jun-24 Jul, 10,481), branch monthsdata. All before 8 Oct.
- HOLDOUT (judged once): w5 (9-21 Oct, 8,427 graduations, branch monthsdata) and S1 (22 Oct 00:00 - 26 Oct 12:00 UTC, 2,661,
  branch bigsearchdata). Honest note: these days were used by earlier, different searches (w5 as fit data of PR #68, S1 as its
  sealed judgement), so they are not fresh days in general; they are unseen for this rule family, whose trades have never been
  computed anywhere. The truly fresh test would be the S2 month (22 Oct - 21 Nov), which this pre-registration also fixes (below).
- SOL/USD by hour from Binance (market.json of each branch) for the liquidity estimate.

## The rule (fixed now)

Times relative to the graduation time g; candles are aligned to 5 minutes (t0 = g floored to 5 min), as in research/check_months.py.

1. Opening range: the candles that closed by g + N minutes. High H = max of their highs (and closes), low L = min of their lows
   (and closes), using only candles with data. At least 2 candles with data, else no trade.
2. Entry: the first candle within W hours after the range that has data and closes above H. Entry price p0 = that close.
   One entry per coin (the first breakout only). No entry if the range or the breakout candle is missing.
3. Liquidity at entry (constant-product estimate from the start pool, as check_months.py) >= $10,000; else the coin is skipped.
4. Exit: stop S = (H + L) / 2 (the README's range midpoint); target X = p0 + R x (p0 - S); time limit T hours after the entry.
   Checked on the five-minute closes after the entry candle, as check_months.py: if a close <= S comes first, the sale is booked at
   min(that close, S); if a close >= X comes first, at X; else at the last close by the time limit (ffilled).
5. Money as the Radar account / Rocket seeker: 20 EUR per buy, buy fee 0.81, sale fee max(0.5 %, 0.81) (check_months.py
   sell_radar), plus the allowance of 0.60 EUR per trade (3 points of 20 EUR) used by every earlier judgement.
6. Every trade needs T hours of candles left in the 48 h file (as check_months.py); entries are at most ~7 h after graduation, so
   this never binds for T <= 24.

Grid (24 variants): N in {15, 30, 60} minutes, W in {2, 6} hours, R in {1, 2}, T in {6, 24} hours.

## Choosing on fit data

On w1 + w2 only: the variant with the highest mean EUR per trade after the allowance among variants with >= 200 fit trades. Ties:
fewer parameters is meaningless here, so the smaller N, then smaller W, then smaller R, then smaller T. That ONE variant is frozen
in research/orb/FROZEN-ORB-2026-10-29.json and committed before any holdout trade is computed.

If the chosen variant is negative on the fit data itself, it is still frozen and judged (a negative fit already says "no").

## The bar (research/PREREG-REVIEW-2026-11-04.md, PR #39), judged once on the holdout

The frozen variant HOLDS if all four: (1) >= 40 holdout trades; (2) mean per trade after the allowance > 0; (3) the one-sided
bootstrap lower bound at 1 % (K = 1, 20,000 draws, seed 7) > 0; (4) the total after the allowance without its single best trade > 0.
Reported separately for w5 and S1 as information; the decision is on w5 + S1 together.

Information only (not a decision): all 24 variants on the holdout, with Holm at 5 % over their bootstrap p-values, and a delay
check (entry one candle later, at the next close).

## Decision

- HOLDS on the holdout: it is offered to the user as a shadow rule to watch on the S2 month (22 Oct - 21 Nov, computed from 24 Nov
  with the same code), never as a live rule before S2 holds too and the user says yes.
- Fails: nothing is built. The video's last untested element is closed.

Expectation written now: it fails. Earlier searches found that waiting before buying loses less but still loses, and the README's
own TSLA example of this setup was "close to a coin flip" (13 targets, 15 stops in 33 signals).
