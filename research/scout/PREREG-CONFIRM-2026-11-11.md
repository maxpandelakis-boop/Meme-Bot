# Confirmation test: "bottom bounce + rug filter, hold until the curve completes" (fake money only)

Written on 2026-11-11 after the scout study (research/scout/PREREG-SCOUT-2026-11-11.md, results on branch scoutdata) and before
any coin of the days below was looked at.

## Why

All four pre-registered cells of the scout study failed with the video's sell rules and with quick in-and-out. One information
row stood out: V3+R (bottom bounce with the rug filter) held to the end (24 h, or the curve's completion) made +2.65 per 20 on the
dev days (95% by day -1.9 to +5.6) and +2.26 on the holdout (+0.07 to +5.52), median trade about -13, carried by the ~28% of
coins whose curve completed. It was one of about a dozen hold rows looked at, so it may be luck. It is tested once on days no
analysis has touched.

## Data and rule

- Days: coins launched 11 August to 23 September 2026 (44 UTC days; 10 August is cut at the data start), same data, code and
  universe as the scout study (scout_day.py at this commit).
- Rule: V3+R exactly as pre-registered (coin >= 30 min old, price >= 50% under its high, the 30-minute low >= 5 minutes old,
  price >= 20% above that low, >= 20 distinct buyers of 0.05 SOL+ in 5 minutes, market cap $10K-$60K, creator sold nothing,
  top 10 net holders < 35%). Entry at the first trade 30 s after the signal, +1% slippage.
- Exit (judged, key holdg2): when the curve holds 80 SOL or more (it is completing), sell at that trade's price -1% slippage and
  a further -10% for the move to PumpSwap; otherwise sell at the last curve trade within 24 hours (-1%). FOMO's real fee tiers.
  Ticket 20 $.

## Pass bar

PASS only if all hold: at least 100 trades; average per 20 above 0; 95% bootstrap interval by day above 0; average without the
best 3 trades above 0; at least 4 of the 6 full weeks (Mon-Sun or 7-day blocks from 11 Aug) with a positive average; and the rule
beats its matched controls held the same way (interval of the difference by day above 0). Otherwise FAIL, and nothing is
re-tuned on these days. Also shown: the same with no 10% haircut, and with the Jupiter-like fee.
