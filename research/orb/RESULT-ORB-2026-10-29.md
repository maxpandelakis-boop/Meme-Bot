# The video's opening-range breakout on pump.fun graduations: result (fake money only)

Pre-registration: research/orb/PREREG-ORB-2026-10-29.md (commit bc3e9d23, before any breakout trade was computed). Frozen choice:
research/orb/FROZEN-ORB-2026-10-29.json (commit 2f9cbf19, before the holdout was read). Code: research/orb/check_orb.py. Research
only: no live rule, account, shadow or bot changed.

## Result

**Fails. Nothing is built.** Every one of the 24 variants loses on the fit windows and on the holdout.

| | trades | per 20 EUR trade after allowance | in profit | 1 % lower bound | without best trade | holds |
|---|---:|---:|---:|---:|---:|---|
| fit w1 + w2 (frozen variant) | 2,320 | -4.46 | 45.6 % | | | |
| holdout w5 + S1 (judged once) | 1,599 | **-6.02** | 39.5 % | -6.65 | -9,641.4 | **no** |
| of which w5 (9-21 Oct) | 1,252 | -5.69 | 40.6 % | | | |
| of which S1 (22-26 Oct) | 347 | -7.22 | 35.7 % | | | |
| one candle later (information) | 1,599 | -5.62 | 37.3 % | | | |

Frozen variant: range 60 min, wait up to 6 h for a close above the range high, stop at the range midpoint, target 1R, 6 h limit.

- Fit, all 24 variants: -4.46 to -5.27 EUR per trade, every variant negative in both w1 and w2.
- Holdout, all 24 variants: -5.76 to -8.60 EUR per trade, none survives Holm at 5 % (all bootstrap lower bounds below -6).
- On w1 the frozen variant's sale multiple had median 0.83: 28 % of the trades ended under half the buy price (stops are checked
  on five-minute closes, and a meme coin's close jumps far below the stop), 38 % reached the 1R target (about +40 % to +60 %).

## Reading it (not deciding)

- A breakout entry buys after the first hour's pump; the range of a fresh graduation is wide, so the midpoint stop is far away and
  is often passed by a single candle. The wins (1R) are smaller than the losses that go through the stop.
- The README's own example of this setup on TSLA was "close to a coin flip" (13 targets, 15 stops in 33 signals). On meme coins it
  is worse than a coin flip after fees.
- With this, every element of the video is closed for meme coins: the Time Machine (research/TIMEMACHINE-2026-10-21.md,
  research/REPLAYS-2026-10-22.md), the stop/target planner (225 sell rules, PR #42 and PR #68), news/earnings/congress trades (no
  such data for meme coins; social, KOL and wallet copies failed in PRs #5, #17, #35, #37), and now the scanner's breakout.
