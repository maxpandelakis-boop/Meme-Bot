"""Big search, step 2 (fake money only, no network): research/bigsearch/PREREG-BIGSEARCH-2026-10-28.md.

  search <work dir> <F>       conditions, every single / pair / beam triple x 225 sell rules on w1-w5 -> search_<F>.npz, conds_<F>.json
  ml     <work dir> <F>       LightGBM per family: walk-forward (w3, w4, w5) and the final refit on w1-w5 -> ml_<F>.json, model_<F>.txt
  freeze <work dir> <out json>   the sealed candidates (chosen on w1-w5 only) -> CANDIDATES-2026-10-28.json
  report <work dir> <out json>   walk-forward and exploration tables -> WALKFORWARD-2026-10-28.json
  judge  <work dir> <candidates json> <out json>   S1 (rows_<F>_s1.pkl, coins_s1.parquet), once
  luck   <work dir> <out json>   the best rule in hindsight on S1 (the size of luck, not a candidate)

<work dir> holds bs_build.py's rows_<F>.pkl, coins.parquet and wal_<F>.npz. Needs numba, lightgbm, pyarrow."""
import itertools, json, math, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import bs_build as BB                                    # noqa: E402

T0 = time.time()
FIT = ["w1", "w2", "w3", "w4", "w5"]
NW = len(FIT)
DAYS = np.array([30.0, 30.0, 31.0, 29.0, 12.25])        # w5's graduation list ends 21 Oct 06:00 UTC
ALLOW = {"P": 0.75, "U": 0.75, "R": 0.60, "S": 0.60}
# schemes: (name, fit windows, test window)
SCHEMES = (("A", (0, 1), 2), ("B", (0, 1, 2), 3), ("C", (0, 1, 2, 3), 4), ("D", (0, 1, 2, 3, 4), -1), ("W", (2,), 3))
PICKERS = ("ROBUST", "SHRUNK", "ROBUST-FREQ", "SHRUNK-FREQ")
MIN_WIN, MIN_POOLED, FREQ_DAY = 30, 100, 8.0
BEAM = 2000
QLO, QHI = (0.10, 0.20, 0.30, 0.50), (0.50, 0.70, 0.80, 0.90)
SEALED_VARS = BB.CHART + BB.TIMEMKT + ["hblock"] + BB.LAUNCH
EXPLORE_VARS = BB.PICTURE + BB.WALLET
NAMES = {"age_h": "hours since graduation", "lmc": "log10 market cap", "liqmc": "liquidity / market cap", "volmc": "24 h volume / market cap",
         "vol1s": "last hour's share of 24 h volume", "r5": "5 min change", "r1h": "1 h change", "r6h": "6 h change", "r24h": "24 h change",
         "rgrad": "change since graduation", "ddath": "distance from the high", "hath": "hours since the high", "vola1h": "1 h volatility",
         "act1h": "candles with trades, last hour", "mlast": "minutes since the last trade", "lvol1": "log10 last hour volume",
         "up1h": "share of rising candles, last hour", "r30m": "30 min change", "vacc": "last hour volume / hour before",
         "rlow": "rise from the low", "actall": "share of candles with trades", "c_ret30": "first 30 min change",
         "c_peak30": "first 30 min high (x)", "hour": "hour (UTC)", "weekend": "weekend", "sol1h": "SOL 1 h change",
         "sol24h": "SOL 24 h change", "btc24h": "BTC 24 h change", "hblock": "6-hour block (UTC)",
         "f_curve_min": "minutes on the bonding curve", "f_creator_prior": "creator's graduations in 30 days",
         "f_dup7": "same ticker in 7 days", "f_cjk": "Chinese/Japanese/Korean name", "f_grads24": "graduations in the 24 h before",
         "f_nlinks": "number of links", "f_xtype": "X link (0 none, 1 post, 2 profile)", "f_post_age": "X post age (0 none, 1 <1 h, 2 <24 h, 3 older)",
         "f_theme24": "same-theme graduations 24 h", "f_img_reused": "picture reused", "f_launch_other": "launched outside pump.fun",
         "f_video": "video coin", "f_desc_len": "description length", "f_news": "name in yesterday's Wikipedia top",
         "f_group": "picture group", "f_animated": "animated picture", "f_lookalike": "look-alike picture", "f_name_fit": "name-picture fit",
         "w_n": "wallets bought before", "w_sol": "SOL of those buys", "w_fresh": "share of first-time wallets", "w_whale": "whale buyers",
         "w_smart": "smart buyers", "w_smartsh": "share of smart buyers", "w_kol": "KOL buyers"}


def log(*a):
    print("[%5.0fs]" % (time.time() - T0), *a, flush=True)


# --------------------------------------------------------------------------------------------------------- data
def load(work, fam, part=""):
    d = pd.read_pickle(os.path.join(work, "rows_%s%s.pkl" % (fam, part)))
    df, O = d["df"], d["O"]
    cf = os.path.join(work, "coins%s.parquet" % part)
    co = pd.read_parquet(cf).drop_duplicates("pool").set_index("pool")
    for k in BB.LAUNCH + BB.PICTURE:
        df[k] = df["pool"].map(co[k]).astype(np.float32) if k in co else np.float32(np.nan)
    df["hblock"] = (df["hour"] // 6).astype(np.float32)
    wf = os.path.join(work, "wal_%s.npz" % fam)
    if not part and os.path.exists(wf):
        W = np.load(wf)["W"]
        for i, k in enumerate(BB.WALLET):
            df[k] = W[:, i]
    else:
        for k in BB.WALLET:
            df[k] = np.float32(np.nan)
    codes = pd.factorize(df["pool"])[0].astype(np.int32)
    assert (np.diff(codes) >= 0).all(), "rows must be grouped by coin"
    return df, O.astype(np.float32), codes


def make_conditions(df, fit_rows):
    conds = []
    for v in SEALED_VARS + EXPLORE_VARS:
        x = df[v].to_numpy(np.float64)
        xf = x[fit_rows]
        xf = xf[np.isfinite(xf)]
        if len(xf) < 100:
            continue
        lv = np.unique(xf)
        if len(lv) <= 6:
            for a in lv:
                conds.append((v, "==", float(a)))
            continue
        seen = set()
        for q in QLO:
            t = float(np.quantile(xf, q))
            if ("<=", t) not in seen:
                seen.add(("<=", t)); conds.append((v, "<=", t))
        for q in QHI:
            t = float(np.quantile(xf, q))
            if (">=", t) not in seen:
                seen.add((">=", t)); conds.append((v, ">=", t))
    return conds


def cond_matrix(df, conds):
    B = np.zeros((len(conds), len(df)), np.uint8)
    cache = {}
    for i, (v, op, t) in enumerate(conds):
        if v not in cache:
            cache[v] = df[v].to_numpy(np.float64)
        x = cache[v]
        with np.errstate(invalid="ignore"):
            m = (x <= t) if op == "<=" else ((x >= t) if op == ">=" else (x == t))
        B[i] = m & np.isfinite(x)
    return B


def cond_text(c):
    v, op, t = c
    return "%s %s %s" % (NAMES.get(v, v), {"<=": "at most", ">=": "at least", "==": "="}[op], ("%.4g" % t))


# --------------------------------------------------------------------------------------------------------- kernel
def kernel():
    import numba

    @numba.njit(parallel=True, cache=False)
    def run(F, B, rowsof, rstart, rlen, coin, widx, O, nw, fitm, testw, days, allow, min_win, min_pooled, freq_day,
            score, ex, tmean, tn, cnt_out):
        nf = F.shape[0]
        R = O.shape[1]
        S = fitm.shape[0]
        for f in numba.prange(nf):
            a, b, c = F[f, 0], F[f, 1], F[f, 2]
            cnt = np.zeros(nw, np.int64)
            s = np.zeros((nw, R))
            q = np.zeros((nw, R))
            last = -1
            if a < 0:
                n_scan = O.shape[0]
            else:
                n_scan = rlen[a]
            for k in range(n_scan):
                r = k if a < 0 else rowsof[rstart[a] + k]
                cr = coin[r]
                if cr == last:
                    continue
                if b >= 0 and B[b, r] == 0:
                    continue
                if c >= 0 and B[c, r] == 0:
                    continue
                last = cr
                w = widx[r]
                if w < 0 or w >= nw:
                    continue
                cnt[w] += 1
                for e in range(R):
                    o = O[r, e]
                    s[w, e] += o
                    q[w, e] += o * o
            for w in range(nw):
                cnt_out[f, w] = cnt[w]
            for si in range(S):
                tw = testw[si]
                tn[f, si] = cnt[tw] if tw >= 0 else 0
                ok_win = True
                ok_freq = True
                ntot = 0
                for w in range(nw):
                    if fitm[si, w]:
                        ntot += cnt[w]
                        if cnt[w] < min_win:
                            ok_win = False
                        if cnt[w] < freq_day * days[w]:
                            ok_freq = False
                for p in range(4):
                    score[f, si, p] = -1e9
                    ex[f, si, p] = -1
                    tmean[f, si, p] = np.nan
                if ntot == 0:
                    continue
                for e in range(R):
                    worst = 1e9
                    st = 0.0
                    sq = 0.0
                    for w in range(nw):
                        if fitm[si, w]:
                            st += s[w, e]
                            sq += q[w, e]
                            if cnt[w] > 0:
                                m = s[w, e] / cnt[w] - allow
                                if m < worst:
                                    worst = m
                            else:
                                worst = -1e9
                    mean = st / ntot
                    var = sq / ntot - mean * mean
                    if var < 0:
                        var = 0.0
                    shr = mean - allow - 2.0 * math.sqrt(var / ntot)
                    vals = (worst if ok_win else -1e9, shr if ntot >= min_pooled else -1e9,
                            worst if (ok_win and ok_freq) else -1e9, shr if (ntot >= min_pooled and ok_freq) else -1e9)
                    for p in range(4):
                        if vals[p] > score[f, si, p]:
                            score[f, si, p] = vals[p]
                            ex[f, si, p] = e
                for p in range(4):
                    e = ex[f, si, p]
                    if e >= 0 and tw >= 0 and cnt[tw] > 0:
                        tmean[f, si, p] = s[tw, e] / cnt[tw] - allow
    return run


_RUN = None


def evaluate(F, B, codes, widx, O, allow, fitm=None, testw=None, nw=NW, days=DAYS):
    global _RUN
    if _RUN is None:
        _RUN = kernel()
    if fitm is None:
        fitm = np.zeros((len(SCHEMES), nw), np.bool_)
        for i, (_, fw, _) in enumerate(SCHEMES):
            fitm[i, list(fw)] = True
        testw = np.array([t for _, _, t in SCHEMES], np.int64)
    C, n = B.shape
    rows = [np.nonzero(B[i])[0].astype(np.int64) for i in range(C)]
    rlen = np.array([len(r) for r in rows], np.int64)
    rstart = np.r_[0, np.cumsum(rlen)[:-1]].astype(np.int64)
    rowsof = np.concatenate(rows) if C else np.zeros(0, np.int64)
    # scan the rarest condition of each filter
    F = F.copy()
    for k in range(F.shape[0]):
        idx = [x for x in F[k] if x >= 0]
        if len(idx) > 1:
            idx.sort(key=lambda x: rlen[x])
            F[k] = idx + [-1] * (3 - len(idx))
    S = fitm.shape[0]
    nf = F.shape[0]
    score = np.zeros((nf, S, 4), np.float32)
    ex = np.zeros((nf, S, 4), np.int16)
    tmean = np.zeros((nf, S, 4), np.float32)
    tn = np.zeros((nf, S), np.int32)
    cnt = np.zeros((nf, nw), np.int32)
    _RUN(F.astype(np.int64), B, rowsof, rstart, rlen, codes.astype(np.int64), widx.astype(np.int64), O, nw, fitm, testw,
         days.astype(np.float64), float(allow), MIN_WIN, MIN_POOLED, FREQ_DAY, score, ex, tmean, tn, cnt)
    return {"score": score, "ex": ex, "tmean": tmean, "tn": tn, "cnt": cnt, "F": F}


# --------------------------------------------------------------------------------------------------------- search
def cmd_search(work, fam):
    df, O, codes = load(work, fam)
    widx = df["w"].map({w: i for i, w in enumerate(FIT)}).fillna(-1).to_numpy(np.int64)
    fit_rows = widx >= 0
    conds = make_conditions(df, fit_rows)
    B = cond_matrix(df, conds)
    var = [c[0] for c in conds]
    log(fam, "rows", len(df), "coins", int(codes.max()) + 1, "conditions", len(conds))
    singles = [(i, -1, -1) for i in range(len(conds))]
    pairs = [(i, j, -1) for i, j in itertools.combinations(range(len(conds)), 2) if var[i] != var[j]]
    F1 = np.array([(-1, -1, -1)] + singles + pairs, np.int64)
    r1 = evaluate(F1, B, codes, widx, O, ALLOW[fam])
    log(fam, "base + singles + pairs", len(F1))
    # beam: the BEAM best pairs (ROBUST) of every scheme, extended by every condition of a third variable
    beam = set()
    npair = len(pairs)
    off = 1 + len(singles)
    for si in range(len(SCHEMES)):
        sc = r1["score"][off:, si, 0]
        top = np.argsort(-sc)[:BEAM]
        top = top[sc[top] > -1e8]
        beam |= {pairs[k][:2] for k in top}
    log(fam, "beam pairs", len(beam))
    trip = set()
    for i, j in beam:
        for k in range(len(conds)):
            if var[k] != var[i] and var[k] != var[j]:
                trip.add(tuple(sorted((i, j, k))))
    F3 = np.array(sorted(trip), np.int64).reshape(-1, 3)
    r3 = evaluate(F3, B, codes, widx, O, ALLOW[fam])
    log(fam, "beam triples", len(F3))
    out = {k: np.concatenate([r1[k], r3[k]]) for k in ("score", "ex", "tmean", "tn", "cnt")}
    Fall = np.concatenate([F1, F3])
    np.savez_compressed(os.path.join(work, "search_%s.npz" % fam), F=Fall, **out)
    json.dump({"conds": conds, "rules": [list(map(lambda x: x if x is None or isinstance(x, str) else float(x), r)) for r in BB.RULES],
               "nRows": int(len(df)), "nCoins": int(codes.max()) + 1, "nFilters": int(len(Fall)), "nPairs": len(pairs),
               "nTriples": int(len(F3)), "beamPairs": len(beam)},
              open(os.path.join(work, "conds_%s.json" % fam), "w"))
    log(fam, "filters", len(Fall), "x", len(BB.RULES), "sell rules =", len(Fall) * len(BB.RULES), "rules")


def filter_vars(F, conds):
    return [[conds[x][0] for x in f if x >= 0] for f in F]


def sealed_mask(F, conds):
    ok = np.array([all(conds[x][0] in SEALED_VARS for x in f if x >= 0) for f in F])
    return ok


def filter_text(f, conds):
    xs = [x for x in f if x >= 0]
    return "base (every coin of the family)" if not xs else " AND ".join(cond_text(conds[x]) for x in xs)


# --------------------------------------------------------------------------------------------------------- ML
ML_CUTS = (0.01, 0.02, 0.05, 0.10)
ML_PARAMS = dict(objective="regression", learning_rate=0.05, num_leaves=31, min_data_in_leaf=200, feature_fraction=0.8,
                 bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, seed=7, num_threads=4, verbose=-1)
ML_ROUNDS = 300


def ml_targets(df, O, fam):
    rules = BB.RULES
    tg = {"K": rules.index(("fix", 0.30, 11.0, 6)), "A": rules.index(("fix", 0.20, 3.0, 6)), "ROCKET": len(rules) - 3}
    fit = df["w"].isin(FIT).to_numpy()
    codes = pd.factorize(df["pool"])[0]
    first = np.r_[True, codes[1:] != codes[:-1]] & fit
    tg["BASE"] = int(np.argmax(O[first].mean(0)))
    return tg


def first_sel(mask, codes):
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return idx
    pc = codes[idx]
    return idx[np.r_[True, pc[1:] != pc[:-1]]]


def cmd_ml(work, fam):
    import lightgbm as lgb
    df, O, codes = load(work, fam)
    feats = SEALED_VARS
    X = df[feats].to_numpy(np.float32)
    w = df["w"].to_numpy()
    tg = ml_targets(df, O, fam)
    ticket = 50.0 if fam in ("P", "U") else 20.0
    res = {"features": feats, "targets": {k: BB.rule_name(BB.RULES[v]) for k, v in tg.items()}, "walk": {}, "final": None}
    allow = ALLOW[fam]
    for tname, e in tg.items():
        y = np.clip(O[:, e], -ticket, 5 * ticket)
        for sname, fw, tw in SCHEMES[:3]:
            tr = np.isin(w, [FIT[i] for i in fw])
            te = w == FIT[tw]
            m = lgb.train(ML_PARAMS, lgb.Dataset(X[tr], y[tr]), ML_ROUNDS)
            ptr, pte = m.predict(X[tr]), m.predict(X[te])
            for cut in ML_CUTS:
                thr = float(np.quantile(ptr, 1 - cut))
                mask = np.zeros(len(df), bool)
                mask[np.nonzero(te)[0][pte >= thr]] = True
                s = first_sel(mask, codes)
                v = O[s, e] - allow
                res["walk"]["%s|%g|%s" % (tname, cut, sname)] = {"n": int(len(s)), "mean": float(v.mean()) if len(s) else None}
            log(fam, "ml", tname, sname)
    best, bs = None, -1e9
    for tname in tg:
        for cut in ML_CUTS:
            ms = [res["walk"]["%s|%g|%s" % (tname, cut, s)] for s, _, _ in SCHEMES[:3]]
            if any(x["n"] < 10 for x in ms):
                continue
            sc = float(np.mean([x["mean"] for x in ms]))
            if sc > bs:
                best, bs = (tname, cut), sc
    res["chosen"] = {"target": best[0], "cut": best[1], "walkMean": bs} if best else None
    if best:
        tname, cut = best
        e = tg[tname]
        y = np.clip(O[:, e], -ticket, 5 * ticket)
        tr = np.isin(w, FIT)
        m = lgb.train(ML_PARAMS, lgb.Dataset(X[tr], y[tr]), ML_ROUNDS)
        ptr = m.predict(X[tr])
        thr = float(np.quantile(ptr, 1 - cut))
        m.save_model(os.path.join(work, "model_%s.txt" % fam))
        mask = np.zeros(len(df), bool)
        mask[np.nonzero(tr)[0][ptr >= thr]] = True
        s = first_sel(mask, codes)
        perw = {ww: float((O[s[w[s] == ww], e] - allow).mean()) if (w[s] == ww).any() else None for ww in FIT}
        res["final"] = {"target": tname, "rule": e, "ruleName": BB.rule_name(BB.RULES[e]), "cut": cut, "thr": thr,
                        "inSample": {"n": int(len(s)), "perWindow": perw}}
    json.dump(res, open(os.path.join(work, "ml_%s.json" % fam), "w"), indent=1)
    log(fam, "ml chosen", res["chosen"])


# --------------------------------------------------------------------------------------------------------- freeze
def cmd_freeze(work, out):
    cands = []
    for fam in BB.FAMS:
        p = os.path.join(work, "search_%s.npz" % fam)
        if not os.path.exists(p):
            continue
        z = np.load(p)
        meta = json.load(open(os.path.join(work, "conds_%s.json" % fam)))
        conds = [tuple(c) for c in meta["conds"]]
        F = z["F"]
        ok = sealed_mask(F, conds)
        si = [s for s, _, _ in SCHEMES].index("D")
        for pi, pk in enumerate(PICKERS):
            sc = np.where(ok, z["score"][:, si, pi], -1e9)
            k = int(np.argmax(sc))
            if sc[k] <= -1e8:
                cands.append({"family": fam, "picker": pk, "empty": True})
                continue
            e = int(z["ex"][k, si, pi])
            cnt = z["cnt"][k].tolist()
            cands.append({"family": fam, "picker": pk, "filter": [int(x) for x in F[k]],
                          "conds": [list(conds[x]) for x in F[k] if x >= 0], "text": filter_text(F[k], conds),
                          "rule": e, "ruleSpec": list(BB.RULES[e]), "ruleName": BB.rule_name(BB.RULES[e]),
                          "fitScore": round(float(sc[k]), 3), "fitTrades": cnt, "allowance": ALLOW[fam]})
        mlp = os.path.join(work, "ml_%s.json" % fam)
        if os.path.exists(mlp):
            ml = json.load(open(mlp))
            if ml.get("final"):
                f = ml["final"]
                cands.append({"family": fam, "picker": "ML", "model": "model_%s.txt" % fam, "features": ml["features"],
                              "thr": f["thr"], "cut": f["cut"], "rule": f["rule"], "ruleSpec": list(BB.RULES[f["rule"]]),
                              "ruleName": f["ruleName"], "walkMean": ml["chosen"]["walkMean"], "inSample": f["inSample"],
                              "allowance": ALLOW[fam]})
    live = [c for c in cands if not c.get("empty")]
    json.dump({"written": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "K": len(live), "candidates": cands},
              open(out, "w"), indent=1)
    log("candidates", len(live))


# --------------------------------------------------------------------------------------------------------- report
def cmd_report(work, out):
    rep = {"families": {}}
    for fam in BB.FAMS:
        p = os.path.join(work, "search_%s.npz" % fam)
        if not os.path.exists(p):
            continue
        z = np.load(p)
        meta = json.load(open(os.path.join(work, "conds_%s.json" % fam)))
        conds = [tuple(c) for c in meta["conds"]]
        F = z["F"]
        ok = sealed_mask(F, conds)
        nvars = np.array([sum(1 for x in f if x >= 0) for f in F])
        has_w = np.array([any(conds[x][0] in BB.WALLET for x in f if x >= 0) for f in F])
        has_p = np.array([any(conds[x][0] in BB.PICTURE for x in f if x >= 0) for f in F])
        fr = {"nFilters": int(len(F)), "nRules": int(len(F)) * len(BB.RULES), "nConds": len(conds), "walk": {}, "explore": {}}
        for si, (sn, fw, tw) in enumerate(SCHEMES):
            if tw < 0:
                continue
            for pi, pk in enumerate(PICKERS):
                for label, m in (("sealedVars", ok & ~has_w & ~has_p), ("withPictures", has_p), ("withWallets", has_w)):
                    if sn == "W" and label != "withWallets" and label != "sealedVars":
                        continue
                    if sn != "W" and label == "withWallets":
                        continue
                    sc = np.where(m, z["score"][:, si, pi], -1e9)
                    elig = sc > -1e8
                    if not elig.any():
                        continue
                    k = int(np.argmax(sc))
                    top = np.argsort(-sc)[:100]
                    top = top[sc[top] > -1e8]
                    tm = z["tmean"][:, si, pi]
                    tn = z["tn"][:, si]
                    good = elig & np.isfinite(tm) & (tn >= 10)
                    fr["walk" if label != "withWallets" else "explore"]["%s|%s|%s" % (sn, pk, label)] = {
                        "picked": filter_text(F[k], conds), "rule": BB.rule_name(BB.RULES[int(z["ex"][k, si, pi])]),
                        "fitScore": round(float(sc[k]), 2), "test": FIT[tw], "testTrades": int(tn[k]),
                        "testMean": None if not np.isfinite(tm[k]) else round(float(tm[k]), 2),
                        "top100PositiveShare": round(float((tm[top][tn[top] >= 10] > 0).mean()), 3) if (tn[top] >= 10).any() else None,
                        "top100MeanTest": round(float(np.nanmean(tm[top][tn[top] >= 10])), 2) if (tn[top] >= 10).any() else None,
                        "allPositiveShare": round(float((tm[good] > 0).mean()), 3) if good.any() else None,
                        "allMeanTest": round(float(np.nanmean(tm[good])), 2) if good.any() else None,
                        "eligible": int(elig.sum())}
        # rank persistence: fit score vs test mean over all eligible sealed filters (scheme C, ROBUST)
        si = 2
        sc = z["score"][:, si, 1]
        tm = z["tmean"][:, si, 1]
        g = (sc > -1e8) & np.isfinite(tm) & (z["tn"][:, si] >= 20) & ok
        if g.sum() > 100:
            fr["rankCorrC_SHRUNK"] = round(float(pd.Series(sc[g]).corr(pd.Series(tm[g]), method="spearman")), 3)
            dec = pd.qcut(pd.Series(sc[g]).rank(method="first"), 10, labels=False)
            fr["decilesC_SHRUNK"] = pd.Series(tm[g]).groupby(dec.values).mean().round(2).tolist()
        rep["families"][fam] = fr
        mlp = os.path.join(work, "ml_%s.json" % fam)
        if os.path.exists(mlp):
            fr["ml"] = json.load(open(mlp))
    rep["totalRules"] = int(sum(f["nRules"] for f in rep["families"].values()))
    json.dump(rep, open(out, "w"), indent=1)
    log("total (filter, sell rule) pairs", rep["totalRules"])


# --------------------------------------------------------------------------------------------------------- judge
def boot(v, alpha, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for k in range(0, draws, 1000):
        means[k:k + 1000] = v[rng.integers(0, len(v), (1000, len(v)))].mean(1)
    return float(np.quantile(means, alpha)), float((means <= 0).mean())


def holm(ps, alpha=0.05):
    order = np.argsort(ps)
    rej = np.zeros(len(ps), bool)
    for r, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - r):
            rej[i] = True
        else:
            break
    return rej


def selected_trades(c, df, O, codes, work):
    if c["picker"] == "ML":
        import lightgbm as lgb
        m = lgb.Booster(model_file=os.path.join(work, c["model"]))
        p = m.predict(df[c["features"]].to_numpy(np.float32))
        mask = p >= c["thr"]
    else:
        mask = np.ones(len(df), bool)
        for v, op, t in c["conds"]:
            x = df[v].to_numpy(np.float64)
            with np.errstate(invalid="ignore"):
                mask &= np.isfinite(x) & ((x <= t) if op == "<=" else ((x >= t) if op == ">=" else (x == t)))
    s = first_sel(mask, codes)
    return s, O[s, c["rule"]] - c["allowance"]


def cmd_judge(work, candf, out):
    cd = json.load(open(candf))
    live = [c for c in cd["candidates"] if not c.get("empty")]
    K = len(live)
    res, data = [], {}
    for c in live:
        fam = c["family"]
        if fam not in data:
            data[fam] = load(work, fam, "_s1")
        df, O, codes = data[fam]
        s, va = selected_trades(c, df, O, codes, work)
        r = {k: c[k] for k in ("family", "picker", "ruleName") if k in c}
        r["text"] = c.get("text", "LightGBM top %g%%" % (100 * c.get("cut", 0)))
        r["n"] = int(len(va))
        if len(va):
            lo, p = boot(va, 0.01 / K)
            best = int(np.argmax(va))
            r.update(meanAfter=round(float(va.mean()), 2), lowerBound=round(lo, 2), pBoot=round(p, 4),
                     totalWithoutBest=round(float(va.sum() - va[best]), 1), total=round(float(va.sum()), 1),
                     inProfit=round(100 * float((va + c["allowance"] > 0).mean()), 1),
                     coins=[{"pool": df["pool"].iat[i], "E": int(df["E"].iat[i]), "eur": round(float(v), 2)} for i, v in zip(s, va)])
            r["holds"] = bool(r["n"] >= 40 and r["meanAfter"] > 0 and lo > 0 and r["totalWithoutBest"] > 0)
        else:
            r.update(holds=False, pBoot=1.0)
        res.append(r)
    rej = holm(np.array([r["pBoot"] for r in res]))
    for r, h in zip(res, rej):
        r["holm5"] = bool(h)
    fam_n = {f: {"rows": int(len(d[0])), "coins": int(d[2].max()) + 1 if len(d[2]) else 0} for f, d in data.items()}
    json.dump({"K": K, "judged": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "s1": fam_n, "results": res,
               "anyHolds": any(r["holds"] for r in res)}, open(out, "w"), indent=1)
    for r in res:
        log(r["family"], r["picker"], r["n"], r.get("meanAfter"), r.get("lowerBound"), r.get("totalWithoutBest"), "HOLDS" if r["holds"] else "fails")


def cmd_luck(work, out):
    """The best (filter, sell rule) in hindsight on S1 with the same conditions: the size of luck."""
    res = {}
    for fam in BB.FAMS:
        p = os.path.join(work, "search_%s.npz" % fam)
        if not os.path.exists(p):
            continue
        meta = json.load(open(os.path.join(work, "conds_%s.json" % fam)))
        conds = [tuple(c) for c in meta["conds"]]
        z = np.load(p)
        F = z["F"]
        ok = sealed_mask(F, conds)
        df, O, codes = load(work, fam, "_s1")
        B = cond_matrix(df, conds)
        widx = np.zeros(len(df), np.int64)
        fitm = np.ones((1, 1), np.bool_)
        r = evaluate(F[ok], B, codes, widx, O, ALLOW[fam], fitm=fitm, testw=np.array([-1], np.int64), nw=1, days=np.array([4.5]))
        k = int(np.argmax(r["score"][:, 0, 1]))
        k2 = int(np.argmax(r["score"][:, 0, 0]))
        res[fam] = {"bestShrunk": {"filter": filter_text(F[ok][k], conds), "rule": BB.rule_name(BB.RULES[int(r["ex"][k, 0, 1])]),
                                   "score": round(float(r["score"][k, 0, 1]), 2), "n": int(r["cnt"][k, 0])},
                    "bestMean30": {"filter": filter_text(F[ok][k2], conds), "rule": BB.rule_name(BB.RULES[int(r["ex"][k2, 0, 0])]),
                                   "meanAfter": round(float(r["score"][k2, 0, 0]), 2), "n": int(r["cnt"][k2, 0])},
                    "searched": int(ok.sum()) * len(BB.RULES)}
        log(fam, res[fam])
    json.dump(res, open(out, "w"), indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    {"search": lambda: cmd_search(a[1], a[2]), "ml": lambda: cmd_ml(a[1], a[2]), "freeze": lambda: cmd_freeze(a[1], a[2]),
     "report": lambda: cmd_report(a[1], a[2]), "judge": lambda: cmd_judge(a[1], a[2], a[3]), "luck": lambda: cmd_luck(a[1], a[2])}[a[0]]()
