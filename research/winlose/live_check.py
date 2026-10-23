"""Live vs test check of the rocket hunter (fake money only; LIVE-CHECK-2026-10-23.md): the Radar account bought nothing in its first
104 rounds with the model of 22 Oct. Does the live account see the numbers the model was tested on?
  full  <scratch>/grid_live_full.pkl  early_grid.py LIVEHL=1, rows from 30 min: every trade of the hour (the model of 22 Oct)
  live  <scratch>/grid_live.pkl       early_grid.py LIVEHL=1 LIVETR=300, rows from 30 min: the last 300 trades only, as live
Walk-forward as rocket_model.py (every week from 14 days on, trained on coins graduated 2+ days before, the cut at the training
scores' top 0.5/1/2 %), seeds 1, 2, 3, 5, 7:
  A  trained full, tested full   (the test of 22 Oct)
  B  trained full, tested live   (what the live account ran from 22 Oct)
  C  trained live, tested live   (the model since 23 Oct)
and, for each, the buys expected in the live account's scored rows (rocket-data log/*.jsonl since the model of 22 Oct, by age band).
usage: python3 research/winlose/live_check.py <scratch> <rocket-data dir>  -> <scratch>/live_check.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb

S, RK = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
NUM = json.load(open(os.path.join(HERE, "..", "..", "rocket_model.json")))["features"]
F = pd.read_pickle(os.path.join(S, "grid_live_full.pkl"))
L = pd.read_pickle(os.path.join(S, "grid_live.pkl"))
G = F.merge(L[["pool", "E"] + NUM], on=["pool", "E"], suffixes=("", "_L")).sort_values("ts").reset_index(drop=True)
assert len(G) == len(F) == len(L), (len(G), len(F), len(L))
LNUM = [k + "_L" for k in NUM]
DAY = 86_400_000
CUTS = (0.005, 0.01, 0.02)
SEEDS = (1, 2, 3, 5, 7)
BANDS = ((30, 45), (60, 90), (105, 240), (255, 1080))
MODEL_22 = 1792676400000 + 40 * 60_000          # 22 Oct 13:40 UTC: the first round with the model of 22 Oct (cut 0.0699)


def P(seed):
    return dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
                colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=seed)


def X(df, cols):
    x = df[cols].copy()
    x.columns = NUM
    return x


live = [json.loads(l) for f in sorted(glob.glob(os.path.join(RK, "log", "*.jsonl"))) for l in open(f)]
live = [r for r in live if not r.get("closed") and r.get("t", 0) >= MODEL_22]
ages = pd.Series([r["age"] for r in live])
weeks = np.arange(G["grad_ms"].min() + 14 * DAY, G["grad_ms"].max() + 1, 7 * DAY)
res = {}
for seed in SEEDS:
    picks = {(v, c): [] for v in "ABC" for c in CUTS}
    rows_e, ntest = [], 0
    for st in weeks:
        tr = G[G["grad_ms"] < st - 2 * DAY]
        te = G[(G["grad_ms"] >= st) & (G["grad_ms"] < st + 7 * DAY)]
        if not len(te):
            continue
        ntest += te["mint"].nunique()
        rows_e.append(te["E"])
        mf = lgb.LGBMClassifier(**P(seed)).fit(tr[NUM], tr["rocket"])
        ml = lgb.LGBMClassifier(**P(seed)).fit(X(tr, LNUM), tr["rocket"])
        sf, sl = mf.predict_proba(tr[NUM])[:, 1], ml.predict_proba(X(tr, LNUM))[:, 1]
        sc = {"A": (mf.predict_proba(te[NUM])[:, 1], sf), "B": (mf.predict_proba(X(te, LNUM))[:, 1], sf),
              "C": (ml.predict_proba(X(te, LNUM))[:, 1], sl)}
        for v, (s_te, s_tr) in sc.items():
            for c in CUTS:
                picks[(v, c)].append(te[s_te >= np.quantile(s_tr, 1 - c)].drop_duplicates("mint"))
    rows_e = pd.concat(rows_e)
    for (v, c), ps in picks.items():
        p = pd.concat(ps)
        lam = 0.0
        for lo, hi in BANDS:
            n_rows = ((rows_e >= lo) & (rows_e <= hi)).sum()
            n_buys = ((p["E"] >= lo) & (p["E"] <= hi)).sum()
            n_live = ((ages >= lo - 7) & (ages <= hi + 7)).sum()
            lam += n_buys / n_rows * n_live
        res.setdefault("%s %g" % (v, c), []).append({"coins": len(p), "testCoins": ntest, "avg": p["eur"].mean(), "x10": p["rocket"].mean(),
                                                     "inProfitOf10": 10 * (p["eur"] > 0).mean(), "liveExpected": lam})
    print("seed", seed, flush=True)
out = {"liveRows": len(live), "liveCoins": len({r["addr"] for r in live}), "liveMax": max(r["score"] for r in live), "res": {}}
for k, r in res.items():
    d = pd.DataFrame(r).mean()
    out["res"][k] = {"coins": round(float(d["coins"]), 1), "pctOfCoins": round(float(100 * d["coins"] / d["testCoins"]), 2), "avg": round(float(d["avg"]), 2),
                     "x10": round(float(100 * d["x10"]), 1), "inProfitOf10": round(float(d["inProfitOf10"]), 1),
                     "liveExpected": round(float(d["liveExpected"]), 2), "pZero": round(100 * float(np.exp(-d["liveExpected"])))}
    print(k, out["res"][k])
json.dump(out, open(os.path.join(S, "live_check.json"), "w"), indent=1)
