# The Time Machine against the trained odds: result (fake money only)

The pre-registered check (research/PREREG-TIMEMACHINE-2026-10-21.md, commit 5f49f189, written before any forecast) run with
`python3 research/check_timemachine.py <memesnapres> <memerec>` on the big-test export of 2026-10-21 06:29 UTC (738,140 look-alike
rows) and the tip record of the branch "results" (378 tips of the 2h profile with odds and a priced horizon; 363 with their own
big-test row and at least 1,000 earlier rows).

Added after the first run, not a change of the test: the script's first version read the horizon result from `outs["out"]` and found
no tips; the tip record keeps it at the top level (`out`). Fixed in the reader only; the forecast was not touched.

## Result (Brier score, lower is better)

| | tips | profit: Time Machine | profit: trained | profit: base rate | zero: Time Machine | zero: trained | zero: base rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 363 | **0.1577** | 0.1621 | 0.1919 | 0.0423 | **0.0418** | 0.0399 |
| first half | 181 | **0.1751** | 0.1789 | 0.2182 | 0.0670 | 0.0661 | 0.0688 |
| second half | 182 | **0.1403** | 0.1453 | 0.1658 | 0.0177 | 0.0176 | 0.0112 |

Calibration in five bins (forecast -> what happened):
- Time Machine profit: 0.03->0.01, 0.10->0.22, 0.16->0.26, 0.19->0.25, 0.25->0.27
- trained profit: 0.19->0.08, 0.19->0.26, 0.20->0.24, 0.20->0.27, 0.20->0.16 (nearly the same number for every tip)
- Time Machine zero: 0.04->0.01, 0.07->0.03, 0.08->0.03, 0.11->0.05, 0.15->0.08
- trained zero: 0.07->0.03, 0.09->0.05, 0.09->0.03, 0.10->0.03, 0.12->0.07

**Decision: KEEP the trained odds.** The Time Machine forecasts profit better, in both halves, but not zero (0.0423 against 0.0418), and
the rule needs both. Neither beats the plain base rate on zero: with 15 zeros in 363 tips there is little to forecast.

## Reading it (not deciding)

- The trained profit chance says about 19% to 20% for every tip, so it carries almost no information. The Time Machine separates:
  its lowest fifth of tips (forecast 3%) ended in profit 1% of the time, the rest 22% to 27%.
- Both zero forecasts are too high (they say 4% to 15%, it happened 1% to 8%).
- A Time Machine for the profit chance alone would be a new hypothesis. It has to be written down first and judged on tips that
  come after it, not on these.
