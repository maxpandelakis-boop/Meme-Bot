# Research brief: which rule picks better coins?

Data: `DATA_DIR/memesnapres/*.json`, the bot's "big test": every coin it scanned (about 12,000 per hourly scan, about
25 scans so far), with the factors it saw at scan time and what a 20 ticket (after fees: 0.5%, minimum 0.81 per trade)
became about 2 hours later. Fake money. `harness.py` (same directory as this file) loads it:

    import sys; sys.path.insert(0, "RESEARCH_DIR"); import harness as H
    rows, scans = H.load("DATA_DIR/memesnapres", rule="m9-2h")   # rows = learnable coins only (liq >= 15k, mc 50k..2M at scan time)
    H.report(rows, scans)                                          # the baselines: all coins, gate passers, the bot's own top-1, random

Row fields: scan (snapshot time, ms), h (hours to the price check), a (address), s (symbol), f (dict of factors, None = unknown),
pass (passed every gate), sc (bot score 0..100), rank (the bot's rank among passers, None otherwise), why (list of gate fails:
"young", "liq", "mc", "vol", "copy", "crash", "spike", "notmeme" ...), mc, liq (at scan time), mult (price multiple at the check),
eur (profit of 20, clipped to -20..+60), eurRaw, gone (to zero: no price or under 2% of entry), rc (RugCheck summary dict or
None), src (source list tags).

Factor keys you will find in f (None when unknown): c1 c6 c24 m5 (price change %), ageH, buyShare, buyRatio1h, buyRatio6h,
buys1, buys24, liqMc, volMc, vol1Share, vol6Share, logMc, srcN, kwN, boosts, nDex, x, web, rc.* (RugCheck: lp, top1, top10,
insiders, holders, warn, score, mutable), dev.* (creator: sold, pct, authOff, txs3h), jup.* (holders, holderChg24, top10Pct,
organic, netBuyers1, netBuyers24, buyVolShare, mcPerHolder), gt.* (GeckoTerminal: buyerRatio, buysPerBuyer, sellers24, trend),
gp.* (GoPlus), cm.* (community), news.*, rd.* (reddit), sw.* (smart wallets), ds.paid / ds.ads / ds.cto, lp.trusted / lp.other,
vt.* (viral tweet), theme.animal, pf.* (pump.fun), cgm.*, cmc.*. Most side-table factors exist only for shortlisted coins
(about 20 per scan); the price/volume/holder factors exist for nearly all rows.

A rule is `rule(rows_of_one_scan, history_rows) -> chosen rows (ordered best first)`. `H.evaluate(rows, scans, rule, k=1)` runs
it walk-forward (history = earlier scans only; a rule may fit on history, never on the scan it picks from) and returns
(stats, per_scan). `H.bootstrap_ci(per_scan)` gives the 95% interval of the average per pick by resampling scans;
`H.scan_consistency(per_scan)` counts the scans with a positive average.

New since 2026-10-08 12:10 UTC: the shortlisted coins (about 20 a scan) carry fl.* factors from a public-RPC trade sample
(fl.rate1h swaps in the last hour, fl.buyers, fl.sellers, fl.buyerRatio, fl.flip = share of wallets on both sides,
fl.topBuyer = biggest buyer's share of the buying, fl.netUsd, fl.netShare; the sampled buyer wallets are stored per coin as
"flb"). The first run (2026-10-08 12:11 UTC) used an earlier decoder: ignore its fl rows (fl.netSol instead of fl.netUsd)
and its holders, which then still included the sampled buyers. They have no prior weight; the question
for this family is whether they separate the coins that rise from those that crash among ACTIVE coins (the first study
found buy share, buyer counts and momentum identical for both). The tips and new launches also keep their candle paths (cv 2, oldest first):
run research/check_exits.py on the results branch for the exit rules.

Gate history (the pass flag and the why tags of a row follow the gate of its scan time, not today's):
- until 2026-10-07 21:26 UTC: 2h profile ages 3 to 12 h, the momentum gates "nobuyers" and "novol1h" active
- from 2026-10-07 21:26 UTC: ages 3 to 24 h, the momentum gates became scored factors
- from 2026-10-08 12:10 UTC (commit d8548bc): ages 6 to 24 h, market cap $100k to $2M (was $50k)
Reconstruct a gate from the why tags plus ageH and mc when you compare across these dates. The first study's results are in
research/RESULTS-2026-10-08.md; compare against them.

Rules of evidence (the bot will only adopt a rule that passes them):
1. Compare against the baselines on the same scans: the bot's top-1, all gate passers, random top-1. A rule must beat the
   bot's top-1 on average per 20 AND have a lower or equal zero rate.
2. Report the bootstrap 95% interval and the positive-scan count; say plainly when the interval includes the baseline.
3. Split check: evaluate on the first half of the scans and the second half separately; a rule that only works on one
   half is noise. Say so.
4. Prefer few parameters. A grid over thousands of filter combinations will always find a winner by chance; if you grid,
   say how many combinations you tried and apply that to your reading of the result.
5. k matters: the bot names one coin per scan (k=1), sometimes two. Report k=1 and k=3.
6. Never evaluate a rule on rows it was fitted on.
7. Coverage: a rule that picks nothing in half of the scans is worth less; report covered scans.

Output: the structured result the task asks for, with for every candidate rule its exact definition (a few lines of Python
over the row fields), stats for k=1 and k=3 (n, avg, win %, zero %, ci95, positive scans, first-half avg, second-half avg),
and your honest verdict (adopt / maybe / noise).
