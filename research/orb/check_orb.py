"""The video's opening-range breakout on pump.fun graduations (fake money only): research/orb/PREREG-ORB-2026-10-29.md.

  fit   <data dir>   w1 + w2 only: the 24 variants, the frozen choice -> research/orb/FROZEN-ORB-2026-10-29.json, FIT-ORB-2026-10-29.json
  judge <data dir>   w5 + S1, once: the frozen variant against the PR #39 bar, all variants as information -> JUDGE-ORB-2026-10-29.json

<data dir> holds bars_w1/w2/w5.parquet, meta_w1/w2/w5.json, market.json (branch monthsdata) and bars_s1.parquet, meta_s1.json
(branch bigsearchdata) with that branch's market.json saved as market_s1.json. Nothing is bought; no network. Needs pyarrow."""
import itertools, json, math, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BAR, MIN, H = 300_000, 60_000, 3_600_000
FIT, HOLD = ("w1", "w2"), ("w5", "s1")
GRID = [dict(N=n, W=w, R=r, T=t) for n, w, r, t in itertools.product((15, 30, 60), (2, 6), (1, 2), (6, 24))]
LIQ_MIN, ALLOW = 10_000, 0.60
FROZEN = os.path.join(HERE, "FROZEN-ORB-2026-10-29.json")


def vname(v):
    return "range %d min, wait %d h, target %dR, %d h" % (v["N"], v["W"], v["R"], v["T"])


def sell_radar(v):
    return v - max(0.005 * v, 0.81) if v > 0 else 0.0


def money(m):
    """20 EUR buy (fee 0.81), sale at multiple m of the entry price."""
    return sell_radar((20.0 - 0.81) * max(0.0, m)) - 20.0


def load(d, w):
    meta = {r["pool"]: r for r in json.load(open(os.path.join(d, "meta_%s.json" % w)))}
    mk = json.load(open(os.path.join(d, "market_s1.json" if w == "s1" else "market.json")))
    s = np.array(mk["SOLUSDT"], dtype=float)
    return meta, pd.read_parquet(os.path.join(d, "bars_%s.parquet" % w)), (s[:, 0], s[:, 1])


def exit_mult(P, s, x):
    hit = np.nonzero((P <= s) | (P >= x))[0]
    if not len(hit):
        return float(P[-1])
    i = hit[0]
    return float(min(P[i], s)) if P[i] <= s else float(x)


def coin_trades(c, b, sol):
    """All variants' trades of one coin: {variant index: (pnl, pnl with one candle delay)}."""
    g = int(c["t"])
    t0 = g // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return {}
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cf = pd.Series(np.where(has, cl, np.nan)).ffill().to_numpy()
    kk = float(c["sol0"]) * float(c["tok0"])
    out = {}
    for vi, v in enumerate(GRID):
        jN = (g + v["N"] * MIN - t0) // BAR - 1          # the last candle closed by g + N minutes
        rng = has[:jN + 1]
        if jN < 1 or rng.sum() < 2:
            continue
        r_hi = np.fmax(hi[:jN + 1], cl[:jN + 1])[rng]
        r_lo = np.fmin(lo[:jN + 1], cl[:jN + 1])[rng]
        Hr, Lr = float(np.nanmax(r_hi)), float(np.nanmin(r_lo))
        if not (Hr > 0 and Lr > 0):
            continue
        ks = np.arange(jN + 1, jN + 1 + v["W"] * 12)
        brk = ks[has[ks] & (cl[ks] > Hr)]
        if not len(brk):
            continue
        k = int(brk[0])
        p0 = float(cl[k])
        te = t0 + (k + 1) * BAR
        i = np.searchsorted(sol[0], te, side="right") - 1
        usd = float(sol[1][int(np.clip(i, 0, len(sol[1]) - 1))])
        if 2 * math.sqrt(kk * p0 / usd) * usd < LIQ_MIN:
            continue
        nT = v["T"] * 12
        if k + 2 + nT > n:
            continue
        S = (Hr + Lr) / 2
        P = cf[k + 1:k + 1 + nT] / p0
        m = exit_mult(P, S / p0, 1 + v["R"] * (1 - S / p0))
        p1 = float(cf[k + 1])                              # one candle later (information only)
        if p1 <= S:
            m1 = 1.0
        else:
            m1 = exit_mult(cf[k + 2:k + 2 + nT] / p1, S / p1, 1 + v["R"] * (1 - S / p1))
        out[vi] = (money(m), money(m1), m)
    return out


def trades(d, windows):
    T = {vi: {"w": [], "pnl": [], "pnl1": [], "m": []} for vi in range(len(GRID))}
    for w in windows:
        meta, bars, sol = load(d, w)
        nc = 0
        for pool, b in bars.groupby("pool", sort=False):
            c = meta.get(pool)
            if c is None:
                continue
            nc += 1
            for vi, (p, p1, m) in coin_trades(c, b.sort_values("t"), sol).items():
                T[vi]["w"].append(w); T[vi]["pnl"].append(p); T[vi]["pnl1"].append(p1); T[vi]["m"].append(m)
        print(w, "coins with candles", nc, flush=True)
    return {vi: {k: np.array(x) for k, x in t.items()} for vi, t in T.items()}


def boot_lo(v, q, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for k in range(0, draws, 2000):
        means[k:k + 2000] = v[rng.integers(0, len(v), (2000, len(v)))].mean(1)
    return float(np.quantile(means, q)), float((means <= 0).mean())


def judge(v, k_cand=1):
    v = np.asarray(v, float)
    if not len(v):
        return {"n": 0, "holds": False}
    va = v - ALLOW
    lo, p = boot_lo(va, 0.01 / k_cand)
    best = int(np.argmax(v))
    r = {"n": int(len(v)), "mean": round(float(v.mean()), 2), "meanAfterAllowance": round(float(va.mean()), 2),
         "lowerBound": round(lo, 2), "pBoot": round(p, 4), "totalWithoutBest": round(float(va.sum() - va[best]), 1),
         "inProfit": round(100 * float((v > 0).mean()), 1), "bestTrade": round(float(v[best]), 2)}
    r["holds"] = bool(r["n"] >= 40 and r["meanAfterAllowance"] > 0 and lo > 0 and r["totalWithoutBest"] > 0)
    return r


def summ(v):
    v = np.asarray(v, float)
    if not len(v):
        return {"n": 0}
    va = v - ALLOW
    return {"n": int(len(v)), "meanAfterAllowance": round(float(va.mean()), 2), "total": round(float(va.sum()), 1),
            "inProfit": round(100 * float((v > 0).mean()), 1)}


def cmd_fit(d):
    T = trades(d, FIT)
    rows = []
    for vi, v in enumerate(GRID):
        t = T[vi]
        rows.append(dict(v, name=vname(v), all=summ(t["pnl"]), **{w: summ(t["pnl"][t["w"] == w]) for w in FIT},
                         delay=summ(t["pnl1"])))
    ok = [r for r in rows if r["all"]["n"] >= 200]
    ok.sort(key=lambda r: (-r["all"]["meanAfterAllowance"], r["N"], r["W"], r["R"], r["T"]))
    ch = ok[0]
    json.dump({"variants": rows}, open(os.path.join(HERE, "FIT-ORB-2026-10-29.json"), "w"), indent=1)
    json.dump({"frozen": {k: ch[k] for k in ("N", "W", "R", "T")}, "name": ch["name"], "fit": ch["all"]},
              open(FROZEN, "w"), indent=1)
    for r in rows:
        print("%-40s n %5d  mean %7.2f  w1 %7.2f  w2 %7.2f  delay %7.2f" % (r["name"], r["all"]["n"], r["all"].get("meanAfterAllowance", 0),
              r["w1"].get("meanAfterAllowance", 0), r["w2"].get("meanAfterAllowance", 0), r["delay"].get("meanAfterAllowance", 0)))
    print("FROZEN", ch["name"], ch["all"])


def holm(ps, alpha=0.05):
    order = np.argsort(ps)
    rej = np.zeros(len(ps), bool)
    for r, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - r):
            rej[i] = True
        else:
            break
    return rej


def cmd_judge(d):
    fz = json.load(open(FROZEN))["frozen"]
    fvi = next(i for i, v in enumerate(GRID) if all(v[k] == fz[k] for k in ("N", "W", "R", "T")))
    T = trades(d, HOLD)
    t = T[fvi]
    res = {"frozen": dict(fz, name=vname(GRID[fvi])), "holdout": judge(t["pnl"]),
           **{w: summ(t["pnl"][t["w"] == w]) for w in HOLD}, "delay": summ(t["pnl1"])}
    info = []
    for vi, v in enumerate(GRID):
        tv = T[vi]
        j = judge(tv["pnl"], k_cand=len(GRID)) if len(tv["pnl"]) else {"n": 0, "pBoot": 1.0}
        info.append(dict(v, name=vname(v), **{k: j.get(k) for k in ("n", "meanAfterAllowance", "lowerBound", "pBoot", "inProfit")},
                         w5=summ(tv["pnl"][tv["w"] == "w5"]), s1=summ(tv["pnl"][tv["w"] == "s1"])))
    rej = holm(np.array([r["pBoot"] if r["pBoot"] is not None else 1.0 for r in info]))
    for r, x in zip(info, rej):
        r["holm"] = bool(x)
    res["allVariants"] = info
    json.dump(res, open(os.path.join(HERE, "JUDGE-ORB-2026-10-29.json"), "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("frozen", "holdout", "w5", "s1", "delay")}, indent=1))
    for r in info:
        print("%-40s n %5d  mean %7.2f  lo %7.2f  holm %s" % (r["name"], r["n"], r["meanAfterAllowance"] or 0, r["lowerBound"] or 0, r["holm"]))


if __name__ == "__main__":
    {"fit": cmd_fit, "judge": cmd_judge}[sys.argv[1]](sys.argv[2])
