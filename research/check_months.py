"""Tests over months (fake money only): research/PREREG-MONTHS-2026-10-23.md. The bots' rules and about 1.5 million rules,
walk-forward over five windows of pump.fun graduations (25 Apr-21 Oct 2026), on five-minute candles of every window.

  rows  <monthsdata dir> <monthsh2 dir> <gap_minutes.npy> <out dir>   entry rows of the three families -> rows_P/U/R.pkl
  part1 <out dir>                                                     the Pick's gates and the shadow rules per window
  part2 <out dir>                                                     the walk-forward search -> months.json
<monthsdata dir> may be "-" (only history2's windows, for a dry run). Nothing is bought; no network."""
import glob, itertools, json, math, multiprocessing as mp, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BAR, MIN, H = 300_000, 60_000, 3_600_000
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))
WN = [w for w, _, _ in WINDOWS]
LABEL = {"w1": "25 Apr-24 May", "w2": "25 Jun-24 Jul", "w3": "10 Aug-9 Sep", "w4": "10 Sep-8 Oct", "w5": "9-21 Oct"}
FEATS = ["age_h", "lmc", "liqmc", "volmc", "vol1s", "r5", "r1h", "r6h", "r24h", "rgrad", "ddath", "hath", "vola1h", "act1h",
         "mlast", "lvol1", "up1h"]


def ms(day):
    return int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)


W_MS = [(w, ms(a), ms(b)) for w, a, b in WINDOWS]


def window(t):
    for w, a, b in W_MS:
        if a <= t < b:
            return w
    return None


# ------------------------------------------------------------------------------------------------ sell rules and money
STOPS = (None, 0.10, 0.20, 0.30, 0.50, 0.70)
TARGETS = (1.2, 1.5, 2.0, 3.0, 5.0, 11.0, None)
TIMES = (1, 2, 6, 12, 24)
RULES = [("fix", s, x, t) for s in STOPS for x in TARGETS for t in TIMES]
RULES += [("trail", tr, None, t) for tr in (0.20, 0.30, 0.50) for t in (6, 12, 24)]
RULES += [("half", 2.0, "K", 6), ("half", 1.5, "K", 6), ("half", 2.0, "free", 24)]
RULE_IX = {r: i for i, r in enumerate(RULES)}
K = RULE_IX[("fix", 0.30, 11.0, 6)]
NAMED = {"K": K, "A": RULE_IX[("fix", 0.20, 3.0, 6)], "B": RULE_IX[("fix", None, 2.0, 12)], "C": RULE_IX[("half", 2.0, "K", 6)],
         "D": RULE_IX[("trail", 0.30, None, 6)]}


def rule_name(r):
    kind, a, b, t = r
    if kind == "fix":
        return "%s / %s / %d h" % ("no stop" if a is None else "-%d%%" % round(100 * a), "no target" if b is None else "%gx" % b, t)
    if kind == "trail":
        return "trailing %d%% / %d h" % (round(100 * a), t)
    return "half at %gx, rest %s" % (a, "by K" if b == "K" else "no stop / 24 h")


def sell_pick(v):
    """A paper sale of value v (50 EUR account): 1 %, at least 0.10."""
    return v - max(0.01 * v, 0.10) if v > 0 else 0.0


def sell_radar(v):
    return v - max(0.005 * v, 0.81) if v > 0 else 0.0


MONEY = {"pick": (50.0, 49.5, sell_pick), "radar": (20.0, 20.0 - 0.81, sell_radar)}


def outcomes(P, n_t):
    """P: closes after the entry / entry price (dense, ffilled), n_t: {hours: bars in the time limit}. -> 222 multiples, each a
    list of (share, multiple) pieces."""
    out = []
    n24 = n_t[24]
    P = P[:n24]
    first = lambda cond, n: (np.argmax(cond[:n]) if cond[:n].any() else None)
    for kind, a, b, t in RULES:
        n = n_t[t]
        if n <= 0 or not len(P):
            out.append([(1.0, 1.0)])
            continue
        last = P[min(n, len(P)) - 1]
        if kind == "fix":
            i_s = first(P <= 1 - a, n) if a is not None else None
            i_t = first(P >= b, n) if b is not None else None
            if i_s is not None and (i_t is None or i_s <= i_t):
                out.append([(1.0, min(P[i_s], 1 - a))])
            elif i_t is not None:
                out.append([(1.0, b)])
            else:
                out.append([(1.0, last)])
        elif kind == "trail":
            M = np.maximum.accumulate(np.maximum(P[:n], 1.0))
            i = first(P[:n] <= (1 - a) * M, n)
            out.append([(1.0, min(P[i], (1 - a) * M[i]))] if i is not None else [(1.0, last)])
        else:
            nK = n_t[6]
            i_s, i_t = first(P <= 0.70, nK), first(P >= 11.0, nK)
            if i_s is not None and (i_t is None or i_s <= i_t):
                iK, mK = i_s, min(P[i_s], 0.70)
            elif i_t is not None:
                iK, mK = i_t, 11.0
            else:
                iK, mK = min(nK, len(P)) - 1, P[min(nK, len(P)) - 1]
            i_h = first(P >= a, nK if b == "K" else n24)
            if b == "K":
                out.append([(0.5, a), (0.5, mK)] if i_h is not None and i_h <= iK else [(1.0, mK)])
            else:
                rest = P[min(n24, len(P)) - 1]
                out.append([(0.5, a), (0.5, rest)] if i_h is not None else [(1.0, rest)])
    return out


def money(pieces, kind):
    ticket, inv, sell = MONEY[kind]
    return sum(sell(inv * s * max(0.0, m)) for s, m in pieces) - ticket


# --------------------------------------------------------------------------------------------------------- rows
SOL = None
GAPS = None


def solusd(t):
    i = np.searchsorted(SOL[0], t, side="right") - 1
    return SOL[1][np.clip(i, 0, len(SOL[1]) - 1)]


def coin_rows(c, b):
    """All entry rows of one coin. c: pool, mint, t (graduation ms), sol0, tok0, w; b: its candles (t, o, h, l, c, v) sorted."""
    t0 = int(c["t"]) // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return []
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n); has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; op[j] = b["o"].to_numpy()[keep]; v[j] = b["v"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cl[~has] = np.nan
    cf = pd.Series(cl).ffill().to_numpy()
    hf = np.where(has, np.fmax(hi, cl), cf)
    p_first = op[np.argmax(has)] if np.isfinite(op[np.argmax(has)]) and op[np.argmax(has)] > 0 else cl[np.argmax(has)]
    cv = np.r_[0, np.cumsum(v)]
    kk = float(c["sol0"]) * float(c["tok0"])
    gm = int(c["t"])
    rows = []
    for E in sorted(set(range(30, 721, 30)) | set(range(60, 1441, 60))):
        te = gm + E * MIN
        jl = (te - t0) // BAR - 1          # the last candle closed before the entry
        if jl < 0 or jl + 1 + 12 >= n or not np.isfinite(cf[jl]):
            continue
        p0 = cf[jl]
        if not has[:jl + 1].any():
            continue
        usd = float(solusd(te))
        mc = p0 * 1e9
        liq = 2 * math.sqrt(kk * p0 / usd) * usd
        v24 = cv[jl + 1] - cv[max(0, jl + 1 - 288)]
        v1 = cv[jl + 1] - cv[max(0, jl + 1 - 12)]

        def px(back_bars):
            k = jl - back_bars
            return cf[k] if k >= 0 and np.isfinite(cf[k]) else p_first

        lr = np.diff(np.log(cf[max(0, jl - 12):jl + 1]))
        lr = lr[np.isfinite(lr)]
        hb = has[max(0, jl - 11):jl + 1]
        ups = (cl[max(0, jl - 11):jl + 1] > op[max(0, jl - 11):jl + 1])[hb]
        ia = int(np.nanargmax(hf[:jl + 1]))
        lastb = int(np.nonzero(has[:jl + 1])[0][-1])
        f = {"age_h": E / 60, "lmc": math.log10(mc), "liqmc": liq / mc, "volmc": v24 / mc, "vol1s": v1 / v24 if v24 > 0 else 0.0,
             "r5": p0 / px(1) - 1, "r1h": p0 / px(12) - 1, "r6h": p0 / px(72) - 1, "r24h": p0 / px(288) - 1, "rgrad": p0 / p_first - 1,
             "ddath": p0 / hf[ia] - 1, "hath": (jl - ia) * 5 / 60, "vola1h": float(lr.std()) if len(lr) >= 3 else 0.0,
             "act1h": int(hb.sum()), "mlast": (te - (t0 + (lastb + 1) * BAR)) / MIN, "lvol1": math.log10(v1 + 1),
             "up1h": float(ups.mean()) if len(ups) else np.nan}
        hourly = E % 60 == 0
        fam = []
        if hourly and 6 <= E / 60 <= 24 and 100_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 >= 15_000 \
                and not (f["r1h"] <= -0.10 or f["r6h"] <= -0.50 or f["r24h"] <= -0.70) and not (f["r1h"] >= 2.0 or f["r6h"] >= 0.90) \
                and v24 / mc <= 8:
            fam.append("P")
        if hourly and liq >= 15_000 and v24 >= 15_000 and mc >= 50_000:
            fam.append("U")
        if E <= 720 and liq >= 15_000 and v24 >= 15_000 and 100_000 <= mc <= 5_000_000 and f["r1h"] > -0.10 and f["r6h"] > -0.50:
            fam.append("R")
        if not fam:
            continue
        if GAPS is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((GAPS[:, 1] >= a) & (GAPS[:, 0] <= z)).any():
                continue
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in TIMES}     # candles after the entry candle, ending by the limit
        P = cf[jl + 2: jl + 2 + jt[24]] / p0
        if len(P) < jt[24]:
            continue                                                        # not 24 h of candles left in the 48 h
        H6 = hf[jl + 2: jl + 2 + jt[6]] / p0
        oc = outcomes(P, jt)
        row = dict(pool=c["pool"], w=c["w"], E=E, te=te, grad=gm, fam="".join(fam), hi6=float(np.nanmax(H6)) if len(H6) else 1.0,
                   **f)
        row["oc"] = oc
        rows.append(row)
    return rows


def _work(args):
    path, meta = args
    b = pd.read_parquet(path)
    out = []
    for pool, g in b.groupby("pool", sort=False):
        c = meta.get(pool)
        if c is None:
            continue
        out += coin_rows(c, g.sort_values("t"))
    return out


def cmd_rows(md, h2, gapf, out):
    global SOL, GAPS
    os.makedirs(out, exist_ok=True)
    mk = json.load(open(os.path.join(md, "market.json"))) if md != "-" else None
    if mk:
        s = np.array(mk["SOLUSDT"], dtype=float)
    else:
        s = np.array([[r[0], float(r[4])] for r in map(json.loads, open(os.path.join(h2, "..", "SOLUSDT.jsonl")))], dtype=float)
    SOL = (s[:, 0], s[:, 1])
    g = np.sort(np.load(gapf))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    GAPS = np.c_[st[big], en[big]]
    meta, jobs, planned = {}, [], {}
    m2 = pd.read_parquet(os.path.join(h2, "meta_h2.parquet"))
    for r in m2.to_dict("records"):
        r["w"] = window(int(r["t"]))
        if r["w"]:
            meta[r["pool"]] = r
            planned[r["w"]] = planned.get(r["w"], 0) + 1
    jobs += [(f, None) for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    if md != "-":
        for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
            for r in json.load(open(f)):
                r["w"] = window(int(r["t"]))
                if r["w"]:
                    meta[r["pool"]] = r
                    planned[r["w"]] = planned.get(r["w"], 0) + 1
        jobs += [(f, None) for f in sorted(glob.glob(os.path.join(md, "bars_w*.parquet")))]
    jobs = [(f, meta) for f, _ in jobs]
    with mp.get_context("fork").Pool(4) as pool:
        parts = pool.map(_work, jobs, chunksize=1)
    rows = [r for p in parts for r in p]
    print("rows", len(rows), flush=True)
    fetched = {}
    for p, r in meta.items():
        if r.get("bars"):
            fetched[r["w"]] = fetched.get(r["w"], 0) + 1
    for fam, kind in (("P", "pick"), ("U", "pick"), ("R", "radar")):
        rs = [r for r in rows if fam in r["fam"]]
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "oc"} for r in rs])
        O = np.array([[money(pc, kind) for pc in r["oc"]] for r in rs], dtype=np.float32)
        Mx = np.array([[sum(s * m for s, m in pc) for pc in r["oc"]] for r in rs], dtype=np.float32)
        order = np.lexsort((df["E"].to_numpy(), df["pool"].to_numpy()))
        df = df.iloc[order].reset_index(drop=True)
        pd.to_pickle({"df": df, "O": O[order], "M": Mx[order], "planned": planned, "fetched": fetched}, os.path.join(out, "rows_%s.pkl" % fam))
        print(fam, len(df), "rows", df["pool"].nunique(), "coins", df.groupby("w")["pool"].nunique().to_dict(), flush=True)


# --------------------------------------------------------------------------------------------------------- stats
def summ(v):
    v = np.asarray(v, float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "mean": round(float(v.mean()), 2), "total": round(float(v.sum()), 1),
            "inProfit": round(100 * float((v > 0).mean()), 1)}


def boot_lo(v, q, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for k in range(0, draws, 2000):
        means[k:k + 2000] = v[rng.integers(0, len(v), (2000, len(v)))].mean(1)
    return float(np.quantile(means, q)), float((means <= 0).mean())


def first_per_coin(mask, pool_codes):
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return idx
    pc = pool_codes[idx]
    return idx[np.r_[True, pc[1:] != pc[:-1]]]


def load_rows(out, fam):
    d = pd.read_pickle(os.path.join(out, "rows_%s.pkl" % fam))
    d["codes"] = pd.factorize(d["df"]["pool"])[0]
    d["wi"] = d["df"]["w"].map({w: i for i, w in enumerate(WN)}).to_numpy()
    return d


def cmd_part1(out):
    d = load_rows(out, "P")
    df, O, M = d["df"], d["O"], d["M"]
    sel = first_per_coin(np.ones(len(df), bool), d["codes"])
    res = {"planned": d["planned"], "fetched": d["fetched"], "windows": {}}
    for w in WN:
        s = sel[df["w"].to_numpy()[sel] == w]
        if not len(s):
            continue
        r = {"coins": int(len(s))}
        for nm, ix in NAMED.items():
            r[nm] = summ(O[s, ix])
        r["K"]["x3"] = round(100 * float((df["hi6"].to_numpy()[s] >= 3).mean()), 1)
        r["K"]["x11"] = round(100 * float((df["hi6"].to_numpy()[s] >= 11).mean()), 1)
        r["K"]["stopped"] = round(100 * float((M[s, K] <= 0.7001).mean()), 1)
        rows_w = np.nonzero(df["w"].to_numpy() == w)[0]
        hour = (df["te"].to_numpy()[rows_w] // H)
        g = pd.DataFrame({"h": hour, "v": O[rows_w, K]}).groupby("h")["v"].mean()
        r["hoursWithCoin"] = int(len(g))
        r["randomPerHour"] = round(float(g.mean()), 2) if len(g) else None
        res["windows"][w] = r
        print(w, LABEL[w], json.dumps(r), flush=True)
    json.dump(res, open(os.path.join(out, "part1.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- part 2
def conditions(df, fit_rows):
    conds = []
    for f in FEATS:
        x = df[f].to_numpy(float)
        q = np.nanquantile(x[fit_rows], [0.20, 0.33, 0.67, 0.80])
        conds += [(f, "<=", q[0], x <= q[0]), (f, "<=", q[1], x <= q[1]), (f, ">=", q[2], x >= q[2]), (f, ">=", q[3], x >= q[3])]
    return conds


def scan_filters(d, fit_w, conds):
    """Per filter: per-window coin counts and sums of all 222 rules (first entry per coin)."""
    df, O = d["df"], d["O"]
    wi, codes = d["wi"], d["codes"]
    n = len(df)
    filt = [("base", None, None)] + [(i, None, None) for i in range(len(conds))] + \
           [(i, j, None) for i, j in itertools.combinations(range(len(conds)), 2) if conds[i][0] != conds[j][0]]
    cnt = np.zeros((len(filt), len(WN)), np.int32)
    sums = np.zeros((len(filt), len(WN), len(RULES)), np.float64)
    for k, (a, b, _) in enumerate(filt):
        if a == "base":
            m = np.ones(n, bool)
        elif b is None:
            m = conds[a][3]
        else:
            m = conds[a][3] & conds[b][3]
        s = first_per_coin(m, codes)
        if not len(s):
            continue
        ws = wi[s]
        cnt[k] = np.bincount(ws, minlength=len(WN))
        for x in np.unique(ws):
            sums[k, x] = O[s[ws == x]].sum(0)
    return filt, cnt, sums


def filt_name(f, conds):
    a, b, _ = f
    if a == "base":
        return "base"
    if a == "clf":
        return "rocket classifier, top %g%% of its fit scores" % (100 * b)
    t = lambda i: "%s %s %.4g" % (conds[i][0], conds[i][1], conds[i][2])
    return t(a) if b is None else t(a) + " and " + t(b)


def pick(cnt, sums, fit_ix, min_n=30):
    """MEAN and WORST pickers over (filter, rule): eligible if >= min_n coins in every fit window."""
    c = cnt[:, fit_ix]
    ok = (c >= min_n).all(1)
    pooled = sums[:, fit_ix].sum(1) / np.maximum(c.sum(1), 1)[:, None]
    per = sums[:, fit_ix] / np.maximum(c, 1)[:, :, None]
    worst = per.min(1)
    pooled[~ok] = -np.inf
    worst[~ok] = -np.inf
    out = {}
    for name, sc in (("MEAN", pooled), ("WORST", worst)):
        k, r = np.unravel_index(np.argmax(sc), sc.shape)
        out[name] = (int(k), int(r), float(sc[k, r]))
    return out, pooled


def selected(d, f, conds):
    a, b, sel = f
    if a == "clf":
        return sel
    n = len(d["df"])
    m = np.ones(n, bool) if a == "base" else (conds[a][3] if b is None else conds[a][3] & conds[b][3])
    return first_per_coin(m, d["codes"])


def judge(v, allowance, k_cand=6):
    v = np.asarray(v, float)
    if not len(v):
        return {"n": 0, "holds": False}
    va = v - allowance
    lo, p = boot_lo(va, 0.01 / k_cand)
    best = np.argmax(v)
    r = {"n": int(len(v)), "mean": round(float(v.mean()), 2), "meanAfterAllowance": round(float(va.mean()), 2),
         "lowerBound": round(lo, 2), "pBoot": round(p, 4), "totalWithoutBest": round(float(va.sum() - va[best]), 1),
         "inProfit": round(100 * float((v > 0).mean()), 1)}
    r["holds"] = bool(r["n"] >= 40 and r["meanAfterAllowance"] > 0 and lo > 0 and r["totalWithoutBest"] > 0)
    return r


def classifier_scores(d, fit_ix, test_i):
    """LightGBM rocket classifier on the 17 numbers: out-of-window scores on the fit windows (trained on the other fit windows),
    and scores on the test window from a model of all fit windows. Returns (score array over all rows, cut quantiles)."""
    import lightgbm as lgb
    df = d["df"]
    X = df[FEATS].to_numpy(float)
    y = (df["hi6"].to_numpy() >= 10).astype(int)
    P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
             colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)
    wi = d["wi"]
    sc = np.full(len(df), np.nan)
    fit_rows = np.isin(wi, fit_ix)
    m_all = lgb.LGBMClassifier(**P).fit(X[fit_rows], y[fit_rows])
    s_fit_all = m_all.predict_proba(X[fit_rows])[:, 1]
    sc[wi == test_i] = m_all.predict_proba(X[wi == test_i])[:, 1]
    cuts = {q: float(np.quantile(s_fit_all, 1 - q)) for q in (0.0025, 0.005, 0.01, 0.02, 0.05)}
    oof = {}
    if len(fit_ix) >= 2:
        for x in fit_ix:
            tr = np.isin(wi, [i for i in fit_ix if i != x])
            m = lgb.LGBMClassifier(**P).fit(X[tr], y[tr])
            s_tr = m.predict_proba(X[tr])[:, 1]
            sc[wi == x] = m.predict_proba(X[wi == x])[:, 1]
            oof[x] = {q: float(np.quantile(s_tr, 1 - q)) for q in cuts}
    return sc, cuts, oof


def cmd_part2(out):
    res = {"rules": len(RULES), "families": {}}
    allowance = {"P": 0.75, "U": 0.75, "R": 0.60}       # 1.5 points of 50 EUR, 3 points of 20 EUR
    for fam in ("P", "U", "R"):
        d = load_rows(out, fam)
        df, O = d["df"], d["O"]
        present = [i for i, w in enumerate(WN) if (d["wi"] == i).any()]
        fr = {"rows": int(len(df)), "coins": {WN[i]: int(df.loc[d["wi"] == i, "pool"].nunique()) for i in present}, "steps": {}}
        for s in range(1, len(WN)):
            test_i = s
            fit_ix = [i for i in range(s) if i in present]
            if test_i not in present or not fit_ix:
                continue
            fit_rows = np.isin(d["wi"], fit_ix)
            conds = conditions(df, fit_rows)
            filt, cnt, sums = scan_filters(d, fit_ix, conds)
            clf_info = None
            if fam == "R" and len(fit_ix) >= 2:
                sc, cuts, oof = classifier_scores(d, fit_ix, test_i)
                add_f, add_c, add_s, clf_info = [], [], [], {}
                for q in cuts:
                    m = (d["wi"] == test_i) & (sc >= cuts[q])
                    for x in fit_ix:
                        m |= (d["wi"] == x) & (sc >= oof[x][q])
                    sl = first_per_coin(m, d["codes"])
                    ws = d["wi"][sl]
                    c = np.bincount(ws, minlength=len(WN)).astype(np.int32)
                    su = np.zeros((len(WN), len(RULES)))
                    for x in np.unique(ws):
                        su[x] = O[sl[ws == x]].sum(0)
                    add_f.append(("clf", q, sl)); add_c.append(c); add_s.append(su)
                    clf_info["top %g%%" % (100 * q)] = {WN[x]: summ(O[sl[ws == x], K]) for x in fit_ix + [test_i]}
                filt = filt + add_f
                cnt = np.vstack([cnt, np.array(add_c)])
                sums = np.concatenate([sums, np.array(add_s)])
            picks, pooled = pick(cnt, sums, fit_ix)
            step = {"fit": [WN[i] for i in fit_ix], "test": WN[test_i], "filters": len(filt), "combos": int(np.isfinite(pooled).sum()),
                    "eligible": int((pooled > -np.inf).sum())}
            for nm, (k, r, sc) in picks.items():
                if not np.isfinite(sc):
                    step[nm] = None
                    continue
                sl = selected(d, filt[k], conds)
                per = {WN[i]: summ(O[sl[d["wi"][sl] == i], r]) for i in present}
                tv = O[sl[d["wi"][sl] == test_i], r]
                step[nm] = {"filter": filt_name(filt[k], conds), "rule": rule_name(RULES[r]), "fitScore": round(sc, 2),
                            "test": judge(tv, allowance[fam]), "perWindow": per}
            # the 20 best fit rules (MEAN) on the test window, Holm at 5 %
            flat = np.argsort(-pooled, axis=None)[:20]
            top = []
            for z in flat:
                k, r = np.unravel_index(z, pooled.shape)
                if not np.isfinite(pooled[k, r]):
                    break
                sl = selected(d, filt[k], conds)
                tv = O[sl[d["wi"][sl] == test_i], r] - allowance[fam]
                p = boot_lo(tv, 0.05, draws=4000)[1] if len(tv) else 1.0
                top.append({"filter": filt_name(filt[k], conds), "rule": rule_name(RULES[r]), "fit": round(float(pooled[k, r]), 2),
                            "testN": int(len(tv)), "testMean": round(float(tv.mean() + allowance[fam]), 2) if len(tv) else None, "p": p})
            ps = sorted(range(len(top)), key=lambda i: top[i]["p"])
            surv = 0
            for rank, i in enumerate(ps):
                if top[i]["p"] <= 0.05 / (len(top) - rank) and top[i]["testN"] >= 40:
                    surv += 1
                else:
                    break
            step["top20"] = top
            step["top20PositiveOnTest"] = sum(1 for t in top if (t["testMean"] or -1) > 0)
            step["holmSurvivors"] = surv
            # hindsight: the best rule picked on the test window itself (shows how big luck looks), >= 40 coins
            ct = cnt[:, test_i]
            mt = sums[:, test_i] / np.maximum(ct, 1)[:, None]
            mt[ct < 40] = -np.inf
            k, r = np.unravel_index(np.argmax(mt), mt.shape)
            step["hindsight"] = {"filter": filt_name(filt[k], conds), "rule": rule_name(RULES[r]), "coins": int(ct[k]),
                                 "mean": round(float(mt[k, r]), 2)}
            if clf_info:
                step["classifierRuleK"] = clf_info
            fr["steps"][WN[test_i]] = step
            print(fam, "step", WN[test_i], json.dumps({k: v for k, v in step.items() if k not in ("top20", "classifierRuleK")}), flush=True)
        res["families"][fam] = fr
    json.dump(res, open(os.path.join(out, "months.json"), "w"), indent=1, default=float)


def cmd_calib(out, dpkl):
    """1a for w3/w4 on history2's own hourly rows: the same coins and hours, K from one-minute bars with the stop on the minute's
    low (check_history2.py), to show what five-minute closes change."""
    d = load_rows(out, "P")
    df, O = d["df"], d["O"]
    sel = first_per_coin(np.ones(len(df), bool), d["codes"])
    e = df.iloc[sel][["pool", "E", "w"]].assign(h=lambda x: (x["E"] // 60).astype(int), k5=O[sel, K])
    h = pd.read_pickle(dpkl)[["pool", "h", "stop30_min", "stop30_x", "tp11_min", "last6", "gap_pre", "gap_6"]]
    m = e.merge(h, on=["pool", "h"], how="inner")
    st, tp = m["stop30_min"].to_numpy(), m["tp11_min"].to_numpy()
    mult = np.where(~np.isnan(st) & (np.isnan(tp) | (st <= tp)), m["stop30_x"], np.where(~np.isnan(tp), 11.0, m["last6"]))
    ok = np.isfinite(mult)
    m = m[ok].assign(k1=[money([(1.0, x)], "pick") for x in mult[ok]])
    res = {w: {"coins": int(len(g)), "K5min": round(float(g["k5"].mean()), 2), "K1min": round(float(g["k1"].mean()), 2)}
           for w, g in m.groupby("w")}
    print(json.dumps(res))
    p1 = json.load(open(os.path.join(out, "part1.json")))
    p1["calib1min"] = res
    json.dump(p1, open(os.path.join(out, "part1.json"), "w"), indent=1)


def cmd_radar(scratch, out):
    """1b: the live Radar model's design (rocket_model.py walk-forward on the last-300-trades grid, PR #41), its buys by month."""
    import lightgbm as lgb
    G = pd.read_pickle(os.path.join(scratch, "grid_early_live_tr300.pkl"))
    G = G[G["E"] >= 30].sort_values("ts").reset_index(drop=True)
    NUM = json.load(open(os.path.join(HERE, "..", "rocket_model.json")))["features"]
    DAY = 86_400_000
    cuts = (0.0025, 0.005, 0.01, 0.02, 0.05)
    weeks = np.arange(G["grad_ms"].min() + 14 * DAY, G["grad_ms"].max() + 1, 7 * DAY)
    picks = {c: [] for c in cuts}
    for seed in (1, 2, 3, 5, 7):
        P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
                 colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=seed)
        for st in weeks:
            tr = G[G["grad_ms"] < st - 2 * DAY]
            te = G[(G["grad_ms"] >= st) & (G["grad_ms"] < st + 7 * DAY)]
            if not len(te):
                continue
            m = lgb.LGBMClassifier(**P).fit(tr[NUM], tr["rocket"])
            s_tr, s_te = m.predict_proba(tr[NUM])[:, 1], m.predict_proba(te[NUM])[:, 1]
            for c in cuts:
                pk = te[s_te >= np.quantile(s_tr, 1 - c)].drop_duplicates("mint").copy()
                pk["seed"] = seed
                picks[c].append(pk)
        print("seed", seed, flush=True)
    res = {"src": "grid_early_live_tr300 rows from 30 min (69,647), weeks from 24 Aug, seeds 1/2/3/5/7, rule K at 20 EUR", "cuts": {}}
    for c in cuts:
        p = pd.concat(picks[c])
        p["month"] = pd.to_datetime(p["ts"], unit="ms").dt.strftime("%Y-%m")
        r = {}
        for mo, g in list(p.groupby("month")) + [("all", p)]:
            r[mo] = {"buysPerSeed": round(len(g) / 5, 1), "mean": round(float(g["eur"].mean()), 2), "inProfit": round(100 * float((g["eur"] > 0).mean()), 1),
                     "x10": round(100 * float(g["rocket"].mean()), 1), "x3": round(100 * float(g["hit3"].mean()), 1),
                     "totalPerSeed": round(float(g["eur"].sum()) / 5, 1)}
        res["cuts"]["%g%%" % (100 * c)] = r
        print("top %g%%" % (100 * c), json.dumps(r), flush=True)
    json.dump(res, open(os.path.join(out, "radar.json"), "w"), indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "rows":
        cmd_rows(a[1], a[2], a[3], a[4])
    elif a[0] == "part1":
        cmd_part1(a[1])
    elif a[0] == "part2":
        cmd_part2(a[1])
    elif a[0] == "calib":
        cmd_calib(a[1], a[2])
    elif a[0] == "radar":
        cmd_radar(a[1], a[2])
