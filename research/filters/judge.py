"""The holdout verdict of the filter study: applies frozen.json (from discover.py) to the holdout days, once. Fake money only.
usage: python3 research/filters/judge.py <rows dir> <frozen.json> <out dir>"""
import json, os, sys
import numpy as np
from lib import *

fz = json.load(open(sys.argv[2]))
out = sys.argv[3]; os.makedirs(out, exist_ok=True)
res = {}
L = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
for which in ("discovery", "holdout"):
    rows = load(sys.argv[1], which)
    v = col(rows, JUDGED)
    ud = sorted(set(r["day"] for r in rows))
    p("\n==== %s: %d days %s to %s, base signals %d (%.0f a day)" % (which, len(ud), ud[0], ud[-1], len(rows), len(rows) / len(ud)))
    base = judge(rows, np.ones(len(rows), bool))
    p("base (every Scout signal): desk %+.3f %s | hold %+.3f | quick %+.3f | desk without FOMO fee %+.3f | in profit %.1f%% | days in profit %d/%d | completes %.1f%%" % (
        base["avg"], base["ci"], col(rows, SECOND).mean(), col(rows, "scal_fomo").mean(), col(rows, "desk_jup").mean(), base["in_profit"], base["days_pos"], len(ud),
        np.mean([r["grad"] for r in rows]) * 100))
    filt = dict(fixed_filters(rows, fz["f5_median"]))
    for i, pk in enumerate(fz["picks"]):
        x = col(rows, pk["feat"])
        filt["D%d %s %s %.4g" % (i + 1, pk["feat"], ">=" if pk["dir"] == 1 else "<=", pk["cut"])] = (x >= pk["cut"]) if pk["dir"] == 1 else (x <= pk["cut"])
    # extras named in amendment 1 (information; frozen before the holdout was opened)
    filt["X1 no whale (largest holder under 20% of supply)"] = col(rows, "top1_pct") < 20
    filt["X2 small dev buy (<= 1 SOL) and creator's only coin in 24 h"] = (col(rows, "dev_buy_sol") <= 1) & (col(rows, "cr_24h") == 0)
    filt["X3 small dev buy (<= 1 SOL)"] = col(rows, "dev_buy_sol") <= 1
    m = fz["model"]
    Z, _ = shape(rows, (np.array(m["mean"]), np.array(m["std"])))
    sc = Z @ np.array(m["w"])
    filt["M score (top 30% by the discovery threshold)"] = sc >= m["thr"]
    res[which] = {}
    for name, keep in filt.items():
        j = judge(rows, keep); j2 = judge(rows, keep, SECOND); j3 = judge(rows, keep, "desk_jup")
        res[which][name] = dict(desk=j, hold=j2, jup=j3)
        if not j.get("n"):
            p(name, "| keeps nothing"); continue
        verdict = ""
        if which == "holdout":
            d = res["discovery"].get(name, {}).get("desk", {})
            helps = j["share"] >= 0.25 and j["n"] >= 30 and j["lift_ci"][0] > 0 and j2["lift"] > 0 and d.get("lift", 0) > 0
            profit = helps and j["avg"] > 0 and j["ci"][0] > 0 and (j["without_best"] or 0) > 0
            verdict = " => " + ("PROFIT" if profit else ("HELPS (solid)" if helps and j["lift_ci99"][0] > 0 else "HELPS (weak: one of 12 tests)" if helps else "FAIL"))
            res[which][name]["verdict"] = verdict[4:]
        p("%s\n    kept %.0f%% (%d, %.0f a day) | desk %+.3f %s | lift %+.3f %s (99.4%%: %s) | days better %d/%d | without best %+.3f | in profit %.1f%% | hold %+.3f lift %+.3f %s | no FOMO fee %+.3f%s" % (
            name, j["share"] * 100, j["n"], j["per_day"], j["avg"], j["ci"], j["lift"], j["lift_ci"], j["lift_ci99"], j["days_beat"][0], j["days_beat"][1],
            j["without_best"], j["in_profit"], j2["avg"], j2["lift"], j2["lift_ci"], j3["avg"], verdict))
    if which == "holdout":
        p("\nscore M by band (holdout):")
        for lo, hi in [(0, 30), (30, 50), (50, 70), (70, 90), (90, 100), (97, 100)]:
            a, b = np.percentile(sc, lo), np.percentile(sc, hi)
            mk = (sc >= a) & (sc <= b)
            p("  pct %d-%d: n %d desk %+.3f hold %+.3f in profit %.1f%% completes %.1f%%" % (lo, hi, mk.sum(), v[mk].mean(), col(rows, SECOND)[mk].mean(), (v[mk] > 0).mean() * 100,
              np.mean([r["grad"] for r, k in zip(rows, mk) if k]) * 100))
json.dump(res, open(os.path.join(out, "holdout.json"), "w"), indent=1)
open(os.path.join(out, "holdout.txt"), "w").write("\n".join(L) + "\n")
