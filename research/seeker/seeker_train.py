"""The Rocket seeker's model (fake money only; research/seeker/PREREG-SEEKER-2026-10-26.md): a rocket score at 30 minutes after
a pump.fun graduation from the launch facts the launch radar reads live and the first 30 minutes of the chart.

  python3 research/seeker/seeker_train.py <rockets dir> <work dir> <history2 dir> <market.json> <rocketsmeta dir> <rocketschain dir> <out dir>

<rockets dir> holds PR #55's research/rockets/{build_paths,base,check_rockets}.py (branch claude/project-thread-5blkl3, commit
2688ca59); <work dir> their paths.npz, coins.parquet, entries.parquet. Writes <out>/backtest.json (fit w1-w3, scored w4/w5),
<out>/seeker_model.json (refit on w1-w5, plain JSON trees, the live cut) and <out>/parity.json (rows + LightGBM's own scores,
for selftest_seeker). No network."""
import json, math, os, sys
import numpy as np, pandas as pd

SEED = 7
E = 30
TOP = 0.02
ALLOW = 0.60
BAR, MIN, H, DAY = 300_000, 60_000, 3_600_000, 86_400_000
LAUNCH_F = ["f_curve_min", "f_creator_prior", "f_xtype", "f_post_age", "f_theme24", "f_cjk"]
CHART_F = ["c_ret", "c_peak", "c_vol", "c_act", "c_r5", "c_r15", "c_mc"]
FEATS = LAUNCH_F + CHART_F
PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, seed=SEED, num_threads=3, verbose=-1)
ROUNDS = 400
FLOOR, ARM, KEEP, HOLD_BARS = 0.5, 2.0, 0.6, 288          # Rocket hold: close <= 0.5x; after a close >= 2x, a close <= 0.6x the best


def rocket_hold(P):
    """Rocket hold on a path of closes as multiples of the entry (the first is the first close after the entry)."""
    hi = 1.0
    last = 1.0
    for x in P:
        if not (x == x):
            continue
        last = x
        if x <= FLOOR:
            return x
        hi = max(hi, x)
        if hi >= ARM and x <= KEEP * hi:
            return x
    return last


def rows(rk, work, hist, market, meta_dir, chain_dir):
    sys.path.insert(0, rk)
    import check_rockets as CR
    z = np.load(os.path.join(work, "paths.npz"))
    cl, hi, v, has = z["cl"], z["hi"], z["v"], z["has"]
    coins = pd.read_parquet(os.path.join(work, "coins.parquet"))
    ent = pd.read_parquet(os.path.join(work, "entries.parquet"))
    c = CR.launch_facts(coins, hist, meta_dir, chain_dir, None)
    row_of = {p: i for i, p in enumerate(coins["pool"])}
    g = np.sort(np.load(os.path.join(hist, "gap_minutes.npy")))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    gaps = np.c_[st[big], en[big]]
    sol = np.array(json.load(open(market))["SOLUSDT"], float)
    e = ent[(ent["E"] == E) & ent["ok"]].copy()
    e = e.merge(c[["pool", "mint", "sol0", "tok0", "symbol", "token_name", "creator", "t", "created_ms", "tw"] + LAUNCH_F], on="pool",
                how="left")
    te = e["te"].to_numpy(np.int64)
    bad = np.zeros(len(e), bool)
    h2w = e["w"].isin(["w3", "w4"]).to_numpy()
    for a, b in gaps:
        bad |= h2w & (a <= te + 6 * H) & (b >= te - H)
    i = np.clip(np.searchsorted(sol[:, 0], te - H, side="right") - 1, 0, None)
    e["liq0"] = 2 * np.sqrt(e["sol0"] * e["tok0"] * e["p0"] * sol[i, 1])
    bad |= ~(e["liq0"] >= 10_000)
    e = e[~bad].reset_index(drop=True)
    r = e["pool"].map(row_of).to_numpy()
    jl = ((e["te"].to_numpy(np.int64) - (e["t"].to_numpy(np.int64) // BAR * BAR)) // BAR - 1).astype(int)
    p0 = e["p0"].to_numpy(float)
    feats = {k: np.full(len(e), np.nan) for k in CHART_F}
    rh, k3 = np.empty(len(e)), np.empty(len(e))
    for n, (ri, j, p) in enumerate(zip(r, jl, p0)):
        f = chart_feats(cl[ri, :j + 1], hi[ri, :j + 1], v[ri, :j + 1], has[ri, :j + 1])
        for k in CHART_F:
            feats[k][n] = f[k]
        P = cl[ri, j + 1: j + 1 + HOLD_BARS] / p
        rh[n] = CR.money(rocket_hold(P))
        k3[n] = CR.money(CR.rule_mult(P, 0.30, 11.0, 6))
    for k in CHART_F:
        e[k] = feats[k]
    e["m_rh"], e["m_k"] = rh, k3
    for k in FEATS:
        e[k] = e[k].astype(float)
    return e


def chart_feats(cl, hi, v, has):
    """The chart at the entry from five-minute bars 0..entry bar (cl: closes, ffilled, NaN before the first trade; hi: highs, NaN
    without a trade; v: USD volume; has: a trade in the bar). seeker.chart computes the same live (selftest_seeker checks it)."""
    cl, hi, v, has = (np.asarray(x, float) for x in (cl, hi, v, has))
    n = len(cl)
    p0 = cl[-1]
    out = {k: float("nan") for k in CHART_F}
    if n == 0 or not np.isfinite(p0) or p0 <= 0:
        return out
    tr = np.nonzero(has > 0)[0]
    first = cl[tr[0]] if len(tr) else float("nan")
    out["c_ret"] = math.log(p0 / first) if np.isfinite(first) and first > 0 else float("nan")
    hh = hi[np.isfinite(hi)]
    out["c_peak"] = float(hh.max() / p0) if len(hh) else float("nan")
    out["c_vol"] = math.log10(1.0 + float(np.nansum(v)))
    out["c_act"] = float((has > 0).mean())
    for k, b in (("c_r5", 1), ("c_r15", 3)):
        q = cl[n - 1 - b] if n - 1 - b >= 0 else float("nan")
        out[k] = math.log(p0 / q) if np.isfinite(q) and q > 0 else float("nan")
    out["c_mc"] = math.log10(p0 * 1e9)
    return out


def blank_mint(X):
    """Prereg: a seeded 20 % of the training rows lose their mint time (f_curve_min and f_post_age missing)."""
    X = X.copy()
    m = np.random.default_rng(SEED).random(len(X)) < 0.20
    X.loc[m, ["f_curve_min", "f_post_age"]] = np.nan
    return X


def fit(X, y):
    import lightgbm as lgb
    return lgb.train(PARAMS, lgb.Dataset(blank_mint(X), label=y.astype(int)), num_boost_round=ROUNDS)


def boot_lo(v, q=0.01, n=10_000):
    rng = np.random.default_rng(SEED)
    return float(np.quantile(rng.choice(v, (n, len(v))).mean(1), q)) if len(v) > 1 else float("nan")


def judge(u, base):
    out = {"n": int(len(u)), "rockets": int(u["rocket"].sum()), "rocketPct": round(100 * float(u["rocket"].mean()), 2) if len(u) else None,
           "basePct": round(100 * float(base["rocket"].mean()), 2), "x3Pct": round(100 * float(u["x3"].mean()), 2) if len(u) else None}
    for k in ("m_rh", "m_k"):
        x = u[k].to_numpy() - ALLOW
        out[k] = {"mean": round(float(x.mean()), 2) if len(x) else None, "lo1": round(boot_lo(x), 2) if len(x) > 1 else None,
                  "woBest": round(float((x.sum() - x.max()) / max(1, len(x) - 1)), 2) if len(x) > 1 else None,
                  "basemean": round(float(base[k].mean() - ALLOW), 2)}
    return out


def dump(booster, cut, feats, meta):
    d = booster.dump_model()
    trees = []

    def node(n):
        if "leaf_value" in n:
            return {"leaf_value": n["leaf_value"]}
        return {"split_feature": n["split_feature"], "threshold": n["threshold"], "default_left": n["default_left"],
                "missing_type": n.get("missing_type", "None"), "decision_type": n.get("decision_type", "<="),
                "left_child": node(n["left_child"]), "right_child": node(n["right_child"])}
    for t in d["tree_info"]:
        trees.append(node(t["tree_structure"]))
    return dict(meta, features=feats, cut=float(cut), trees=trees)


def main(rk, work, hist, market, meta_dir, chain_dir, out):
    from sklearn.metrics import roc_auc_score
    os.makedirs(out, exist_ok=True)
    e = rows(rk, work, hist, market, meta_dir, chain_dir)
    e.drop(columns=["tw"]).to_parquet(os.path.join(out, "rows_E30.parquet"), index=False)
    cov = {k: {w: round(float(g[k].notna().mean()), 3) for w, g in e.groupby("w")} for k in FEATS}
    res = {"rows": {w: int(n) for w, n in e["w"].value_counts().sort_index().items()},
           "rockets": {w: int(n) for w, n in e.groupby("w")["rocket"].sum().items()}, "coverage": cov,
           "xtype": {w: g["f_xtype"].value_counts(dropna=False).to_dict() for w, g in e.groupby("w")}}
    y = e["rocket"].astype(int)
    # backtest: fit w1-w3, cut from three blocked out-of-fold folds, score w4 / w5
    fitm = e["w"].isin(["w1", "w2", "w3"]).to_numpy()
    F = e[fitm].sort_values("te")
    blocks = np.array_split(F.index.to_numpy(), 3)
    oof = pd.Series(np.nan, index=F.index)
    for b in blocks:
        tr = F.index.difference(b)
        oof[b] = fit(e.loc[tr, FEATS], y[tr]).predict(e.loc[b, FEATS])
    cut = float(np.quantile(oof, 1 - TOP))
    bm = fit(e.loc[fitm, FEATS], y[fitm])
    s = bm.predict(e.loc[~fitm, FEATS])
    U = e[~fitm].assign(score=s)
    bt = {"cut": cut, "oofTopShare": round(float((oof >= cut).mean()), 4)}
    for w in ("w4", "w5"):
        u = U[U["w"] == w]
        bt[w] = {"auc": round(float(roc_auc_score(u["rocket"], u["score"])), 3), "days": round((u["te"].max() - u["te"].min()) / DAY, 1),
                 "top": judge(u[u["score"] >= cut], u), "all": judge(u, u)}
        bt[w]["top"]["perDay"] = round(bt[w]["top"]["n"] / bt[w]["days"], 2)
    bt["gain"] = dict(sorted(zip(FEATS, bm.feature_importance("gain").round(1).tolist()), key=lambda x: -x[1]))
    res["backtest"] = bt
    # the live model: leave-one-window-out scores for the cut, refit on everything
    lowo = pd.Series(np.nan, index=e.index)
    for w in ("w1", "w2", "w3", "w4", "w5"):
        m = (e["w"] == w).to_numpy()
        lowo[m] = fit(e.loc[~m, FEATS], y[~m]).predict(e.loc[m, FEATS])
    live_cut = float(np.quantile(lowo, 1 - TOP))
    final = fit(e[FEATS], y)
    res["live"] = {"cut": live_cut, "lowoAuc": {w: round(float(roc_auc_score(y[e["w"] == w], lowo[e["w"] == w])), 3) for w in
                                                   ("w1", "w2", "w3", "w4", "w5")},
                   "lowoTop": {w: judge(e[(e["w"] == w) & (lowo >= live_cut)], e[e["w"] == w]) for w in ("w1", "w2", "w3", "w4", "w5")},
                   "gain": dict(sorted(zip(FEATS, final.feature_importance("gain").round(1).tolist()), key=lambda x: -x[1]))}
    meta = {"made": "2026-10-26", "rows": int(len(e)), "E": E, "top": TOP, "src": "research/seeker/seeker_train.py (PREREG-SEEKER-2026-10-26.md)",
            "rule": "Rocket hold: close <= 0.5x; after a close >= 2x the first close <= 0.6x the best close; 24 h"}
    json.dump(dump(final, live_cut, FEATS, meta), open(os.path.join(out, "seeker_model.json"), "w"), separators=(",", ":"))
    # parity rows for the plain-Python scorer: real rows, some with the mint time blanked, and LightGBM's own scores
    rng = np.random.default_rng(SEED)
    pick = rng.choice(len(e), 60, replace=False)
    P = e.loc[pick, FEATS].copy()
    P.iloc[::3, [FEATS.index("f_curve_min"), FEATS.index("f_post_age")]] = np.nan
    Q = np.array(P.to_numpy(float), copy=True)
    Q[1::3][rng.random(Q[1::3].shape) < 0.3] = np.nan          # any input missing (a missing_type None split counts it as 0)
    P = pd.DataFrame(Q, columns=FEATS)
    # ... and real five-minute bars with the chart numbers seeker_train computes, for seeker.chart
    z = np.load(os.path.join(work, "paths.npz"))
    row_of = {p: i for i, p in enumerate(pd.read_parquet(os.path.join(work, "coins.parquet"))["pool"])}
    bars = []
    for k in rng.choice(len(e), 20, replace=False):
        ri = row_of[e.at[k, "pool"]]
        j = int((int(e.at[k, "te"]) - int(e.at[k, "t"]) // BAR * BAR) // BAR - 1)
        b = {n: [None if not np.isfinite(x) else float(x) for x in z[n][ri, :j + 1]] for n in ("cl", "hi", "v")}
        b["has"] = [int(x) for x in z["has"][ri, :j + 1]]
        f = chart_feats(z["cl"][ri, :j + 1], z["hi"][ri, :j + 1], z["v"][ri, :j + 1], z["has"][ri, :j + 1])
        bars.append({"bars": b, "chart": {n: None if not np.isfinite(x) else float(x) for n, x in f.items()}})
    json.dump({"features": FEATS, "rows": [[None if not np.isfinite(x) else float(x) for x in r] for r in P.to_numpy()],
               "scores": [float(x) for x in final.predict(P)], "bars": bars}, open(os.path.join(out, "parity.json"), "w"))
    json.dump(res, open(os.path.join(out, "backtest.json"), "w"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main(*sys.argv[1:8])
