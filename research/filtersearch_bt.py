"""The pre-registered big filter search, part 2: the bot's own big test (research/PREREG-SEARCH-2026-10-21.md; fake money only).
usage: python3 research/filtersearch_bt.py <memesnapres dir>      (sh research/get_data.sh <dir> unpacks it; numpy; ~6 min, 6 GB)

Every number the scan stores for many coins (91 of them: price, volume, holders, RugCheck, creator, pump.fun, social, smart wallets,
the trade sample), each at its quartiles, alone or (for the 33 widely known ones) in pairs, in 6 windows (the bot's gates among them).
Chosen on train (scans 7 to 14 Oct) and check (15 to 17 Oct), the choice tested once on the holdout (from 18 Oct).
"""
import itertools, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import filter_search as FS

ALL = ('ageH','logMc','liqMc','volMc','vol1Share','vol6Share','c1','c6','c24','m5','buyShare','buyRatio1h','buyRatio6h','buys1','buys24','srcN','kwN','boosts','x','web','socN','nDex','nPairs','fdvMc','logLiq','vt.tweet','theme.animal','news.hits','soc.match','lp.trusted','lp.other','mkt.sol24','mkt.fng','rd.posts','cmc.search',
       'jup.organic','jup.verified','jup.holders','jup.top10Pct','jup.mcPerHolder','jup.traders24','jup.buyVolShare','jup.netBuyers24','jup.holderChg24','jup.devMints','jup.netBuyers1',
       'pf.live','pf.twitter','pf.website','pf.telegram','pf.athRatio','pf.replies','gt.buyers24','gt.sellers24','gt.trend','gt.buyerRatio','gt.buysPerBuyer',
       'dev.sold','dev.authOff','dev.txs3h','dev.pct','ds.paid','ds.ads','ds.cto','cm.rcUp','cm.rcDown','cm.rcNet','rc.score','rc.top1','rc.top10','rc.holders','rc.insiders','rc.danger','rc.warn','rc.mutable','rc.creator','rc.lp','sw.n','sw.avg','sw.wins',
       'fl.rate1h','fl.buyers','fl.sellers','fl.flip','fl.buyerRatio','fl.netShare','fl.netUsd','fl.topBuyer','vt.likes','vt.replies','vt.fresh')
PAIRF = set(FS.FEATURES) | {'vol6Share','buyRatio6h','buys24','kwN','boosts','x','web','socN','nDex','logLiq','jup.mcPerHolder','jup.traders24','jup.buyVolShare'}
P1, P2 = 1792022400000, 1792281600000      # 2026-10-15, 2026-10-18 00:00 UTC (by scan)
MIN_N = 40


def main():
    R = FS.load(sys.argv[1], features=ALL)
    per = np.where(R["scan"] < P1, 0, np.where(R["scan"] < P2, 1, 2))
    conds = []
    for k in ALL:
        v = R[k][per == 0]
        v = v[~np.isnan(v)]
        if len(v) >= 300:
            for q in sorted(set(np.quantile(v, (0.25, 0.5, 0.75)).tolist())):
                conds += [[k, "<=", q], [k, ">=", q]]
    cm = [FS.cond_mask(R, c) for c in conds]
    pi = [i for i in range(len(conds)) if conds[i][0] in PAIRF]
    combos = [()] + [(i,) for i in range(len(conds))] + [(i, j) for i, j in itertools.combinations(pi, 2) if conds[i][0] != conds[j][0]]
    print("rows %d; %d conditions; %d combinations" % (len(per), len(conds), len(combos) * len(FS.WINDOWS)))
    for name, m in (("gates", R["pass"]), ("new launches", FS.window_mask(R, "new"))):
        for p in range(3):
            print("  %-13s %s %s" % (name, ("train", "check", "holdout")[p], FS.stats(R, FS.entries(R, m & (per == p)))))
    cand = []
    for w in FS.WINDOWS:
        sub = np.flatnonzero(FS.window_mask(R, w) & (per < 2))
        S = {k: R[k][sub] for k in ("coin", "r", "hit3")}
        ps, cms = per[sub], [c[sub] for c in cm]
        for combo in combos:
            m = None
            for i in combo:
                m = cms[i] if m is None else m & cms[i]
            out = []
            for p in (0, 1):
                ix = FS.entries(S, (ps == p) if m is None else (ps == p) & m)
                if len(ix) < MIN_N:
                    break
                r = S["r"][ix]
                out.append((len(ix), float(r.mean()), float(S["hit3"][ix].mean()), float(r.std() / math.sqrt(len(ix)))))
            if len(out) == 2:
                cand.append((min(out[0][1], out[1][1]), w, combo, out, 0.5 * (1 - math.erf((out[1][1] / out[1][3]) / math.sqrt(2))) if out[1][3] > 0 else 1.0))
    pv = sorted(c[4] for c in cand)
    holm = next((i for i, p in enumerate(pv) if p > 0.05 / (len(pv) - i)), len(pv))
    cand.sort(key=lambda c: -c[0])
    txt = lambda w, combo: "%s: %s" % (w, " & ".join("%s%s%.3g" % tuple(conds[i]) for i in combo) or "(no filter)")
    print("candidates %d; positive on train and check %d; Holm survivors at 5%%: %d" % (len(cand), sum(1 for c in cand if c[3][0][1] > 0 and c[3][1][1] > 0), holm))
    for c in cand[:10]:
        print("  %-70s train %+.2f (n %d) check %+.2f (n %d)" % (txt(c[1], c[2]), c[3][0][1], c[3][0][0], c[3][1][1], c[3][1][0]))
    best = cand[0]
    m = FS.window_mask(R, best[1])
    for i in best[2]:
        m = m & FS.cond_mask(R, conds[i])
    print("\nTHE CHOICE: %s; the holdout once:" % txt(best[1], best[2]))
    for p in range(3):
        print("  choice %-8s %s" % (("train", "check", "HOLDOUT")[p], FS.stats(R, FS.entries(R, m & (per == p)))))
        print("  gates  %-8s %s" % (("train", "check", "HOLDOUT")[p], FS.stats(R, FS.entries(R, R["pass"] & (per == p)))))


if __name__ == "__main__":
    main()
