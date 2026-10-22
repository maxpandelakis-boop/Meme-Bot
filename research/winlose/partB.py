"""Part B of research/winlose/PREREG-WINLOSE-2026-10-22.md: a gradient-boosting score, walk-forward on dev, then the holdout
once (fake money only).  usage: python3 research/winlose/partB.py <scratch> [--holdout]"""
import json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy.stats import ttest_1samp

S = sys.argv[1]
HOLDOUT = "--holdout" in sys.argv
F = pd.read_pickle(os.path.join(S, "feat.pkl")).sort_values("ts")
HOLD, DAY = 1790294400000, 86_400_000
META = {"mint", "pool", "ts", "grad_ms", "h", "gday", "day", "eur_A", "eur_hold", "hit3", "lose80", "zero", "gates", "lo6", "hi6"}
NUM = [c for c in F.columns if c not in META]
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)
CUTS = (0.02, 0.05, 0.10, 0.20)


def fit_scores(tr, te):
    X, Xt = tr[NUM], te[NUM]
    reg = lgb.LGBMRegressor(**P).fit(X, tr["eur_A"])
    cw = lgb.LGBMClassifier(**P).fit(X, tr["hit3"])
    cl = lgb.LGBMClassifier(**P).fit(X, tr["lose80"])
    s_tr = {"reg": reg.predict(X), "wml": cw.predict_proba(X)[:, 1] - cl.predict_proba(X)[:, 1]}
    s_te = {"reg": reg.predict(Xt), "wml": cw.predict_proba(Xt)[:, 1] - cl.predict_proba(Xt)[:, 1]}
    return s_tr, s_te, reg


def picks(te, score, cut):
    m = te[score >= cut]
    return m.drop_duplicates("mint")          # rows are in time order: the first hour that passes


def summary(p):
    if not len(p):
        return {"coins": 0}
    v = p["eur_A"].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort([v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)])
    return {"coins": len(p), "avg": round(v.mean(), 3), "lo95": round(bs[50], 3), "hi95": round(bs[1949], 3),
            "in_profit_of10": round(10 * (v > 0).mean(), 1), "hit3": round(100 * p["hit3"].mean(), 1),
            "lose80": round(100 * p["lose80"].mean(), 1), "p": float(ttest_1samp(v, 0, alternative="greater").pvalue)}


def gates(te):
    return te[te["gates"]].drop_duplicates("mint")


dev = F[F["grad_ms"] < HOLD]
if not HOLDOUT:
    starts = np.arange(F["grad_ms"].min() + 14 * DAY, HOLD, 7 * DAY)      # weekly folds; the first from 24 Aug
    acc = {(s, c): [] for s in ("reg", "wml") for c in CUTS}
    base, gp = [], []
    imp = None
    for st in starts:
        tr = dev[dev["grad_ms"] < st - 2 * DAY]
        te = dev[(dev["grad_ms"] >= st) & (dev["grad_ms"] < min(st + 7 * DAY, HOLD))]
        if not len(te):
            continue
        s_tr, s_te, reg = fit_scores(tr, te)
        for s in ("reg", "wml"):
            for c in CUTS:
                cut = np.quantile(s_tr[s], 1 - c)
                acc[(s, c)].append(picks(te, s_te[s], cut))
        base.append(te.drop_duplicates("mint")); gp.append(gates(te))
        imp = pd.Series(reg.feature_importances_, NUM) if imp is None else imp + pd.Series(reg.feature_importances_, NUM)
        print("fold from", pd.to_datetime(st, unit="ms").date(), "train", tr["mint"].nunique(), "test", te["mint"].nunique(), flush=True)
    sb, sg = summary(pd.concat(base)), summary(pd.concat(gp))
    print("\nall coins, first universe hour:", sb)
    print("bot gates:", sg)
    best = None
    for k, v in acc.items():
        sm = summary(pd.concat(v))
        print(k, sm)
        if sm["coins"] >= 150 and (best is None or sm["avg"] > best[1]["avg"]):
            best = (k, sm)
    print("\nTHE CHOICE (dev walk-forward):", best)
    print("\nimportance (splits, regression):")
    print(imp.sort_values(ascending=False).head(25).to_string())
    json.dump({"choice": [best[0][0], best[0][1]], "dev": best[1], "dev_gates": sg, "dev_base": sb,
               "importance": imp.sort_values(ascending=False).head(15).to_dict()}, open(os.path.join(S, "choice.json"), "w"))
else:
    ch = json.load(open(os.path.join(S, "choice.json")))
    hold = F[F["grad_ms"] >= HOLD]
    s_tr, s_te, _ = fit_scores(dev, hold)
    out = {"base": summary(hold.drop_duplicates("mint")), "gates": summary(gates(hold))}
    for s in ("reg", "wml"):
        for c in CUTS:
            out["%s_%g" % (s, c)] = summary(picks(hold, s_te[s], np.quantile(s_tr[s], 1 - c)))
    ps = sorted((v["p"], k) for k, v in out.items() if k not in ("base", "gates") and v.get("coins"))
    m = len(ps); prev = 0
    for i, (p, k) in enumerate(ps):
        prev = max(prev, min(1, (m - i) * p)); out[k]["p_holm"] = round(prev, 4)
    for k, v in out.items():
        print(k, v)
    key = "%s_%g" % (ch["choice"][0], ch["choice"][1])
    c, g = out[key], out["gates"]
    ok = c["coins"] >= 100 and c["avg"] > 0 and c["lo95"] > 0 and c["avg"] > g.get("avg", -99) and c["hit3"] >= g.get("hit3", 0)
    print("\nchoice", key, "->", "PASSES" if ok else "FAILS")
    json.dump(out, open(os.path.join(S, "holdout.json"), "w"))
