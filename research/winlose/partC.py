"""Addendum 2 of research/winlose/PREREG-WINLOSE-2026-10-22.md (fake money only): A few losers, B rockets, C expected profit, on
the 15-minute grid (grid.py). usage: python3 research/winlose/partC.py <scratch> [--holdout]"""
import json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy.stats import ttest_1samp

S = sys.argv[1]
G = pd.read_pickle(os.path.join(S, "grid.pkl")).sort_values("ts").reset_index(drop=True)
HOLD, DAY = 1790294400000, 86_400_000
META = {"pool", "mint", "ts", "grad_ms", "E", "eur", "mult", "hi6", "lo6", "win", "rocket", "hit3", "gday"}
NUM = [c for c in G.columns if c not in META]
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)
CUTS = (0.005, 0.01, 0.02, 0.05)


def scores(tr, te):
    out_tr, out_te = {}, {}
    for name, y in (("A", "win"), ("B", "rocket")):
        m = lgb.LGBMClassifier(**P).fit(tr[NUM], tr[y])
        out_tr[name], out_te[name] = m.predict_proba(tr[NUM])[:, 1], m.predict_proba(te[NUM])[:, 1]
    m = lgb.LGBMRegressor(**P).fit(tr[NUM], tr["eur"])
    out_tr["C"], out_te["C"] = m.predict(tr[NUM]), m.predict(te[NUM])
    return out_tr, out_te


def summary(p):
    if not len(p):
        return {"coins": 0}
    v = p["eur"].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": len(p), "avg": round(float(v.mean()), 3), "lo95": round(float(bs[50]), 3), "hi95": round(float(bs[1949]), 3),
            "in_profit_of10": round(10 * float((v > 0).mean()), 1), "hit3": round(100 * float(p["hit3"].mean()), 1),
            "rocket10x": round(100 * float(p["rocket"].mean()), 1), "zero": round(100 * float((p["mult"] < 0.02).mean()), 1),
            "best": round(float(v.max()), 1), "p": float(ttest_1samp(v, 0, alternative="greater").pvalue) if len(v) > 2 else 1.0}


def picks(te, s, cut):
    return te[s >= cut].drop_duplicates("mint")


def better(var, a, b):
    if b is None:
        return True
    if var == "A":
        return (a["in_profit_of10"], a["avg"]) > (b["in_profit_of10"], b["avg"])
    return a["avg"] > b["avg"]


dev = G[G["grad_ms"] < HOLD]
if "--holdout" not in sys.argv:
    acc = {(v, c): [] for v in "ABC" for c in CUTS}
    base = []
    for st in np.arange(G["grad_ms"].min() + 14 * DAY, HOLD, 7 * DAY):
        tr = dev[dev["grad_ms"] < st - 2 * DAY]
        te = dev[(dev["grad_ms"] >= st) & (dev["grad_ms"] < min(st + 7 * DAY, HOLD))]
        if not len(te):
            continue
        s_tr, s_te = scores(tr, te)
        for v in "ABC":
            for c in CUTS:
                acc[(v, c)].append(picks(te, s_te[v], np.quantile(s_tr[v], 1 - c)))
        base.append(te.drop_duplicates("mint"))
        print("fold", pd.to_datetime(st, unit="ms").date(), len(tr), len(te), flush=True)
    print("first universe point per coin:", summary(pd.concat(base)))
    choice, res = {}, {}
    for (v, c), lst in acc.items():
        sm = summary(pd.concat(lst))
        res["%s_%g" % (v, c)] = sm
        print(v, c, sm)
        if sm["coins"] >= 100 and better(v, sm, choice.get(v, (None, None))[1]):
            choice[v] = (c, sm)
    print("CHOICES", {v: (c, s["avg"], s["in_profit_of10"]) for v, (c, s) in choice.items()})
    json.dump({"choice": {v: c for v, (c, _) in choice.items()}, "dev": res, "dev_base": summary(pd.concat(base))},
              open(os.path.join(S, "choiceC.json"), "w"), default=float)
else:
    ch = json.load(open(os.path.join(S, "choiceC.json")))
    hold = G[G["grad_ms"] >= HOLD]
    s_tr, s_te = scores(dev, hold)
    out = {"base": summary(hold.drop_duplicates("mint"))}
    for v in "ABC":
        for c in CUTS:
            out["%s_%g" % (v, c)] = summary(picks(hold, s_te[v], np.quantile(s_tr[v], 1 - c)))
    ps = sorted((o["p"], k) for k, o in out.items() if k != "base" and o.get("coins"))
    prev = 0
    for i, (p, k) in enumerate(ps):
        prev = max(prev, min(1, (len(ps) - i) * p)); out[k]["p_holm"] = round(prev, 4)
    for k, o in out.items():
        print(k, o)
    verdict = {}
    for v, c in ch["choice"].items():
        o = out["%s_%g" % (v, c)]
        ok = o["coins"] >= 50 and o["avg"] > 0 and (o["in_profit_of10"] >= 6 if v == "A" else o["lo95"] > 0)
        verdict[v] = {"cut": c, "result": o, "passes": bool(ok)}
        print("CHOICE", v, c, "PASSES" if ok else "FAILS")
    json.dump({"holdout": out, "verdict": verdict}, open(os.path.join(S, "holdoutC.json"), "w"), default=float)
    # the picks themselves, for the shared simulation
    for v, c in ch["choice"].items():
        picks(hold, s_te[v], np.quantile(s_tr[v], 1 - c))[["mint", "ts", "mult", "eur"]].to_pickle(os.path.join(S, "picks_%s.pkl" % v))
