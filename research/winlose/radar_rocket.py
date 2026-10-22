"""Addendum 3 of research/winlose/PREREG-WINLOSE-2026-10-22.md (fake money only): a rocket score from the numbers a DexScreener
pair gives the launch radar 5, 15, 30 and 60 minutes after first sight. Builds the rows from the one-minute bars, tests the score
walk-forward and once on the holdout, and with --export trains on all coins and writes radar_rocket.json (the trees as plain
JSON, read by rocket.py at run time without lightgbm).
usage: python3 research/winlose/radar_rocket.py <scratch> [--holdout] [--export]"""
import glob, json, math, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy.stats import ttest_1samp
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import memebot as M

S = sys.argv[1]
AT = (5, 15, 30, 60)
HOLD, DAY = 1790294400000, 86_400_000
NUM = ["age_min", "mc", "liqmc", "vol5mc", "vol1mc", "c5", "c1", "b5", "s5", "b1", "s1", "bshare5", "bshare1", "vs_first"]
P = dict(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=7)
CUTS = (0.005, 0.01, 0.02, 0.05)


def build():
    coins = pd.read_parquet(os.path.join(S, "h2", "coins.parquet")).drop_duplicates("pool").set_index("pool")
    gap = np.load(os.path.join(S, "h2", "gap_minutes.npy")) // 60000
    k = [json.loads(l) for l in open(os.path.join(S, "mk", "SOLUSDT.jsonl"))]
    st, sc = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])
    rows = []
    for f in sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet"))):
        b = pd.read_parquet(f)
        b = b[b["pool"].isin(coins.index)]
        for pool, g in b.groupby("pool"):
            n = int(g["mi"].max()) + 1
            if n < 6:
                continue
            mi = g["mi"].to_numpy()
            c = np.full(n, np.nan); c[mi] = g["p_close"].to_numpy(); c = pd.Series(c).ffill().to_numpy()
            hi = np.full(n, np.nan); hi[mi] = g["p_hi"].to_numpy(); hi = np.where(np.isnan(hi), c, hi)
            lo = np.full(n, np.nan); lo[mi] = g["p_lo"].to_numpy(); lo = np.where(np.isnan(lo), c, lo)
            v = np.zeros(n); v[mi] = (g["sol_buy"] + g["sol_sell"]).to_numpy()
            nb = np.zeros(n); nb[mi] = g["n_buy"].to_numpy()
            ns = np.zeros(n); ns[mi] = g["n_sell"].to_numpy()
            c0 = coins.loc[pool]
            gm, kk = int(c0["grad_ms"]), float(c0["sol0"]) * float(c0["tok0"])
            first = c[1] if n > 1 and c[1] > 0 else c[0]
            gmin = gm // 60000
            for E in AT:
                if E >= n or not (c[E - 1] > 0) or not (first > 0):
                    continue
                if np.isin(np.arange(gmin, gmin + E + 360), gap).any():
                    continue
                p0 = c[E - 1]
                usd = float(sc[max(0, np.searchsorted(st, gm + E * 60000, side="right") - 1)])
                mc = p0 * 1e9 * usd
                liq = 2 * math.sqrt(kk * p0) * usd
                if liq < 5_000:
                    continue
                w5, w1 = slice(max(0, E - 5), E), slice(max(0, E - 60), E)
                b5, s5, b1, s1 = nb[w5].sum(), ns[w5].sum(), nb[w1].sum(), ns[w1].sum()
                r = {"pool": pool, "mint": c0["mint"], "grad_ms": gm, "ts": gm + E * 60000, "age_min": E, "mc": math.log10(mc), "liqmc": liq / mc,
                     "vol5mc": v[w5].sum() * usd / mc, "vol1mc": v[w1].sum() * usd / mc, "c5": p0 / c[max(0, E - 6)] - 1, "c1": p0 / c[0] - 1,
                     "b5": b5, "s5": s5, "b1": b1, "s1": s1, "bshare5": b5 / (b5 + s5) if b5 + s5 else 0.5, "bshare1": b1 / (b1 + s1) if b1 + s1 else 0.5,
                     "vs_first": p0 / first}
                ph, pl = hi[E:E + 360] / p0, lo[E:E + 360] / p0
                s_ = np.nonzero(pl <= 0.70)[0]; t_ = np.nonzero(ph >= 11.0)[0]
                mult = float(pl[s_[0]]) if len(s_) and (not len(t_) or s_[0] <= t_[0]) else 11.0 if len(t_) else float(c[min(E + 360, n) - 1] / p0)
                r.update(mult=mult, eur=M.tip_net(max(0.0, mult)), hi6=float(np.nanmax(ph)) if len(ph) else 1.0)
                rows.append(r)
        print(os.path.basename(f), len(rows), flush=True)
    G = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    G["rocket"] = G["hi6"] >= 10
    G["hit3"] = G["hi6"] >= 3
    G.to_pickle(os.path.join(S, "radar_rows.pkl"))
    return G


def summary(p):
    if not len(p):
        return {"coins": 0}
    v = p["eur"].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": len(p), "avg": round(float(v.mean()), 3), "lo95": round(float(bs[50]), 3), "hi95": round(float(bs[1949]), 3),
            "in_profit_of10": round(10 * float((v > 0).mean()), 1), "hit3": round(100 * float(p["hit3"].mean()), 1),
            "rocket10x": round(100 * float(p["rocket"].mean()), 1), "zero": round(100 * float((p["mult"] < 0.02).mean()), 1),
            "p": float(ttest_1samp(v, 0, alternative="greater").pvalue) if len(v) > 2 else 1.0}


def picks(te, s, cut):
    return te[s >= cut].drop_duplicates("mint")


path = os.path.join(S, "radar_rows.pkl")
G = pd.read_pickle(path) if os.path.exists(path) else build()
print("rows", len(G), "coins", G["mint"].nunique(), "rocket rows %.2f%%" % (100 * G["rocket"].mean()))
dev = G[G["grad_ms"] < HOLD]
if "--export" in sys.argv:
    m = lgb.LGBMClassifier(**P).fit(G[NUM], G["rocket"])
    s = m.predict_proba(G[NUM])[:, 1]
    dump = m.booster_.dump_model()
    trees = [t["tree_structure"] for t in dump["tree_info"]]
    cuts = {"%g" % c: float(np.quantile(s, 1 - c)) for c in CUTS}
    base = float(G["rocket"].mean())
    json.dump({"v": 1, "made": "2026-10-22", "features": NUM, "init": None, "trees": trees, "cuts": cuts, "baseRocket": base,
               "rows": int(len(G)), "coins": int(G["mint"].nunique()), "src": "history2 10 Aug-8 Oct 2026, research/winlose/radar_rocket.py",
               "check": {"x": G[NUM].head(5).values.tolist(), "p": s[:5].tolist()}},
              open(os.path.join(HERE, "..", "..", "radar_rocket.json"), "w"), separators=(",", ":"))
    print("exported; cuts", cuts)
elif "--holdout" not in sys.argv:
    acc = {c: [] for c in CUTS}
    for st in np.arange(G["grad_ms"].min() + 14 * DAY, HOLD, 7 * DAY):
        tr = dev[dev["grad_ms"] < st - 2 * DAY]
        te = dev[(dev["grad_ms"] >= st) & (dev["grad_ms"] < min(st + 7 * DAY, HOLD))]
        if not len(te):
            continue
        m = lgb.LGBMClassifier(**P).fit(tr[NUM], tr["rocket"])
        s_tr, s_te = m.predict_proba(tr[NUM])[:, 1], m.predict_proba(te[NUM])[:, 1]
        for c in CUTS:
            acc[c].append(picks(te, s_te, np.quantile(s_tr, 1 - c)))
    best = None
    for c, l in acc.items():
        sm = summary(pd.concat(l)); print(c, sm)
        if sm["coins"] >= 100 and (best is None or sm["avg"] > best[1]["avg"]):
            best = (c, sm)
    print("all coins at 5 min:", summary(dev[dev["age_min"] == 5].drop_duplicates("mint")))
    print("THE CHOICE", best)
    json.dump({"choice": best[0] if best else None, "dev": {"%g" % c: summary(pd.concat(l)) for c, l in acc.items()}},
              open(os.path.join(S, "radar_choice.json"), "w"))
else:
    ch = json.load(open(os.path.join(S, "radar_choice.json")))
    hold = G[G["grad_ms"] >= HOLD]
    m = lgb.LGBMClassifier(**P).fit(dev[NUM], dev["rocket"])
    s_tr, s_te = m.predict_proba(dev[NUM])[:, 1], m.predict_proba(hold[NUM])[:, 1]
    out = {"base5": summary(hold[hold["age_min"] == 5].drop_duplicates("mint"))}
    for c in CUTS:
        out["%g" % c] = summary(picks(hold, s_te, np.quantile(s_tr, 1 - c)))
        out["%g" % c]["ix"] = None
    for k, o in out.items():
        print(k, o)
    if ch["choice"] is not None:
        o = out["%g" % ch["choice"]]
        print("CHOICE", ch["choice"], "PASSES" if o["coins"] >= 50 and o["avg"] > 0 and o["lo95"] > 0 else "FAILS")
    json.dump(out, open(os.path.join(S, "radar_holdout.json"), "w"))
