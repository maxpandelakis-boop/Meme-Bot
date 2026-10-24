"""A chart-driven sell rule for the Pick account (fake money only): research/PREREG-CHARTEXIT-2026-10-24.md.

  paths <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <out dir>   the Pick-type coins' five-minute paths -> paths.pkl
  grid <out dir>                                                               8,424 exits x every coin, both fills -> grid.npz
  test <out dir>                                                               walk-forward, the w4 test, the live pick -> result.json

The Pick-type coins (family P) and their entry are research/check_months.py's (PR #42): the Pick's gates as far as candles hold
them, whole hours 6-24 h after graduation, one entry per coin (its first hour through the gates). Nothing is bought; no network.
Needs pandas, pyarrow, numba."""
import glob, json, math, os, sys
import numpy as np, pandas as pd

BAR, MIN, H = 300_000, 60_000, 3_600_000
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))
WN = [w for w, _, _ in WINDOWS]
W_MS = [(w, int(pd.Timestamp(a, tz="UTC").timestamp() * 1000), int(pd.Timestamp(b, tz="UTC").timestamp() * 1000)) for w, a, b in WINDOWS]
WICK_X = 5.0             # memebot.CANDLE_WICK_X: a wick further than this from the close is the close
HOURS = (1, 2, 3, 6, 12)
NB = 150                 # five-minute candles kept after the entry (12 h = 144)


def window(t):
    for w, a, b in W_MS:
        if a <= t < b:
            return w
    return None


# ------------------------------------------------------------------------------------------------ the variants
STOPS = (0.20, 0.30, 0.40, 0.50)
TRAILS = [(0.0, 0.0)] + [(w, a) for w in (0.15, 0.20, 0.25, 0.30, 0.40) for a in (1.0, 1.15, 1.3, 1.5, 2.0)]
LOCKS = (0.0, 1.3, 1.6)
STALES = ((0, 0.0), (2, 1.10), (3, 1.20))
FADES = ("none", "drop", "vol")
TIMES = (3, 6, 12)
VARIANTS = [dict(stop=s, trail=w, arm=a, lock=b, stale_h=sh, stale_g=sg, fade=f, T=t)
            for s in STOPS for (w, a) in TRAILS for b in LOCKS for (sh, sg) in STALES for f in FADES for t in TIMES]
K = next(i for i, v in enumerate(VARIANTS) if v == dict(stop=0.30, trail=0.0, arm=0.0, lock=0.0, stale_h=0, stale_g=0.0, fade="none", T=6))


def chart_driven(v):
    return v["trail"] > 0 or v["lock"] > 0 or v["stale_h"] > 0 or v["fade"] != "none"


def parts(v):
    return (v["trail"] > 0) + (v["lock"] > 0) + (v["stale_h"] > 0) + (v["fade"] != "none")


def name(v):
    bits = ["stop -%d%%" % round(100 * v["stop"])]
    if v["trail"]:
        bits.append("trail %d%% under the high%s" % (round(100 * v["trail"]), "" if v["arm"] <= 1.0 else " once it reached %gx" % v["arm"]))
    if v["lock"]:
        bits.append("break-even once %gx" % v["lock"])
    if v["stale_h"]:
        bits.append("out at %d h unless %gx seen" % (v["stale_h"], v["stale_g"]))
    if v["fade"] == "drop":
        bits.append("out on -15%% in 30 min")
    if v["fade"] == "vol":
        bits.append("out when the hour's volume < 1/4 of the entry hour")
    bits.append("11x / %d h" % v["T"])
    return ", ".join(bits)


def sell_pick(v):
    return v - max(0.01 * v, 0.10) if v > 0 else 0.0


def money(m):
    return sell_pick(49.5 * max(0.0, m)) - 50.0


# --------------------------------------------------------------------------------------------------------- paths
SOL = GAPS = META = None


def solusd(t):
    i = np.searchsorted(SOL[0], t, side="right") - 1
    return SOL[1][np.clip(i, 0, len(SOL[1]) - 1)]


def coin_path(c, b):
    """The first Pick-type entry of one coin and its path (check_months.coin_rows' gates and entry), or None."""
    t0 = int(c["t"]) // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return None
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n)
    has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]; op[j] = b["o"].to_numpy()[keep]
    v[j] = b["v"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cl[~has] = np.nan
    cf = pd.Series(cl).ffill().to_numpy()
    hf = np.where(has, np.fmax(hi, cl), cf)
    i0 = int(np.argmax(has))
    p_first = op[i0] if np.isfinite(op[i0]) and op[i0] > 0 else cl[i0]
    cv = np.r_[0, np.cumsum(v)]
    kk = float(c["sol0"]) * float(c["tok0"])
    gm = int(c["t"])
    for E in range(360, 1441, 60):
        te = gm + E * MIN
        jl = (te - t0) // BAR - 1
        if jl < 0 or jl + 1 + 12 >= n or not np.isfinite(cf[jl]) or not has[:jl + 1].any():
            continue
        p0 = cf[jl]
        usd = float(solusd(te))
        mc = p0 * 1e9
        liq = 2 * math.sqrt(kk * p0 / usd) * usd
        v24 = cv[jl + 1] - cv[max(0, jl + 1 - 288)]
        v1 = cv[jl + 1] - cv[max(0, jl + 1 - 12)]

        def px(back):
            k = jl - back
            return cf[k] if k >= 0 and np.isfinite(cf[k]) else p_first

        r1h, r6h, r24h = p0 / px(12) - 1, p0 / px(72) - 1, p0 / px(288) - 1
        if not (100_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 >= 15_000 and not (r1h <= -0.10 or r6h <= -0.50 or r24h <= -0.70)
                and not (r1h >= 2.0 or r6h >= 0.90) and v24 / mc <= 8):
            continue
        if GAPS is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((GAPS[:, 1] >= a) & (GAPS[:, 0] <= z)).any():
                continue
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in HOURS + (24,)}
        if len(cf[jl + 2: jl + 2 + jt[24]]) < jt[24]:
            return None                       # not 24 h of candles left in the 48 h (check_months: no row; the next hours fail too)
        s = slice(jl + 2, jl + 2 + NB)
        C = cf[s] / p0
        hs = has[s]
        Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
        Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
        O = np.where(hs & np.isfinite(op[s]) & (op[s] > 0), op[s], np.r_[cf[jl + 1], cf[jl + 2: jl + 1 + NB]]) / p0
        Hh = np.where(Hh <= WICK_X * C, Hh, C)
        Ll = np.where(Ll >= C / WICK_X, Ll, C)
        O = np.clip(O, Ll, Hh)
        return dict(pool=c["pool"], w=c["w"], E=E, te=te, v1=float(v1), nb={t: int(jt[t]) for t in HOURS},
                    C=C.astype(np.float64), H=Hh.astype(np.float64), L=Ll.astype(np.float64), O=O.astype(np.float64),
                    V=(v[s] * hs).astype(np.float64))
    return None


def _work(args):
    path, k, n = args
    b = pd.read_parquet(path)
    if n > 1:
        pools = np.sort(b["pool"].unique())[k::n]
        b = b[b["pool"].isin(pools)]
    out = []
    for pool, g in b.groupby("pool", sort=False):
        c = META.get(pool)
        if c is None:
            continue
        r = coin_path(c, g.sort_values("t"))
        if r is not None:
            out.append(r)
    return out


def cmd_paths(md, h2, gapf, out):
    global SOL, GAPS, META
    import multiprocessing as mp
    os.makedirs(out, exist_ok=True)
    s = np.array(json.load(open(os.path.join(md, "market.json")))["SOLUSDT"], dtype=float)
    SOL = (s[:, 0], s[:, 1])
    g = np.sort(np.load(gapf))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    GAPS = np.c_[st[big], en[big]]
    meta = {}
    for r in pd.read_parquet(os.path.join(h2, "meta_h2.parquet")).to_dict("records"):
        r["w"] = window(int(r["t"]))
        if r["w"]:
            meta[r["pool"]] = r
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        for r in json.load(open(f)):
            r["w"] = window(int(r["t"]))
            if r["w"]:
                meta[r["pool"]] = r
    META = meta
    jobs = [(f, 0, 1) for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    jobs += [(f, k, 6) for f in sorted(glob.glob(os.path.join(md, "bars_w*.parquet"))) for k in range(6)]
    rows = []
    with mp.get_context("fork").Pool(3) as pool:
        for part in pool.imap_unordered(_work, jobs, chunksize=1):
            rows += part
    rows.sort(key=lambda r: (r["te"], r["pool"]))
    seen, uniq = set(), []
    for r in rows:                       # a pool in two sources (the window edges) counts once
        if r["pool"] not in seen:
            seen.add(r["pool"]); uniq.append(r)
    pd.to_pickle(uniq, os.path.join(out, "paths.pkl"))
    print("coins", len(uniq), pd.Series([r["w"] for r in uniq]).value_counts().sort_index().to_dict(), flush=True)


# --------------------------------------------------------------------------------------------------------- the replay
def arrays(rows):
    n = len(rows)
    A = {k: np.ones((n, NB)) for k in ("C", "H", "L", "O")}
    A["V"] = np.zeros((n, NB))
    nb = np.zeros((n, len(HOURS)), np.int64)
    for i, r in enumerate(rows):
        for k in ("C", "H", "L", "O", "V"):
            x = r[k][:NB]
            A[k][i, :len(x)] = x
            if len(x) < NB and k != "V":
                A[k][i, len(x):] = x[-1]
        nb[i] = [min(NB, r["nb"][t]) for t in HOURS]
    v1 = np.array([r["v1"] for r in rows])
    return A, nb, v1


def var_array():
    P = np.array([[v["stop"], v["trail"], v["arm"], v["lock"], v["stale_h"], v["stale_g"], FADES.index(v["fade"]), v["T"]] for v in VARIANTS])
    return P


def replay_np(C, Hh, L, O, V, nb, v1, P, closes_only=False):
    """The numba kernel's reference in plain Python (one coin, one variant) -> (mult with the "low" fill, mult with the "level"
    fill, why)."""
    stop, trail, arm, lock, stale_h, stale_g, fade, T = P
    nT = nb[HOURS.index(int(T))]
    nS = nb[HOURS.index(int(stale_h))] if stale_h else -1
    hi, armed_t, armed_l = 1.0, trail > 0 and arm <= 1.0, False
    for k in range(nT):
        c = C[k]
        h, l, o = (c, c, c) if closes_only else (Hh[k], L[k], O[k])
        lvl = 1.0 - stop
        if armed_l:
            lvl = max(lvl, 1.03)
        if armed_t:
            lvl = max(lvl, (1.0 - trail) * hi)
        if l <= lvl:
            return min(l, lvl), min(o, lvl), "stop" if lvl <= 1.0 - stop + 1e-12 else ("trail" if armed_t and (1.0 - trail) * hi >= lvl - 1e-12 else "lock")
        if h >= 11.0:
            return 11.0, 11.0, "tp"
        hi = max(hi, h)
        if trail > 0 and not armed_t and hi >= arm:
            armed_t = True
        if lock > 0 and not armed_l and hi >= lock:
            armed_l = True
        lvl2 = 1.0 - stop
        if armed_l:
            lvl2 = max(lvl2, 1.03)
        if armed_t:
            lvl2 = max(lvl2, (1.0 - trail) * hi)
        if c <= lvl2:
            return c, lvl2, "trail" if armed_t and (1.0 - trail) * hi >= lvl2 - 1e-12 else "lock"
        if k == nS - 1 and hi < stale_g:
            return c, c, "stale"
        if fade == 1:
            ref = C[k - 6] if k >= 6 else 1.0
            if c <= 0.85 * ref:
                return c, c, "drop"
        if fade == 2 and k >= 11 and v1 > 0 and V[k - 11:k + 1].sum() < 0.25 * v1:
            return c, c, "vol"
    return C[nT - 1], C[nT - 1], "time"


def run_grid(A, nb, v1, P, closes_only=False):
    import numba

    @numba.njit(parallel=True, cache=False)
    def kern(C, Hh, L, O, V, nb, v1, P, hours, closes_only, out):
        n, m = C.shape[0], P.shape[0]
        for i in numba.prange(n):
            for j in range(m):
                stop, trail, arm, lock, stale_h, stale_g, fade, T = P[j, 0], P[j, 1], P[j, 2], P[j, 3], P[j, 4], P[j, 5], P[j, 6], P[j, 7]
                nT, nS = 0, -1
                for q in range(hours.shape[0]):
                    if hours[q] == T:
                        nT = nb[i, q]
                    if stale_h > 0 and hours[q] == stale_h:
                        nS = nb[i, q]
                hi = 1.0
                armed_t = trail > 0 and arm <= 1.0
                armed_l = False
                f_low, f_lvl = C[i, nT - 1], C[i, nT - 1]
                for k in range(nT):
                    c = C[i, k]
                    if closes_only:
                        h, l, o = c, c, c
                    else:
                        h, l, o = Hh[i, k], L[i, k], O[i, k]
                    lvl = 1.0 - stop
                    if armed_l and lvl < 1.03:
                        lvl = 1.03
                    if armed_t and lvl < (1.0 - trail) * hi:
                        lvl = (1.0 - trail) * hi
                    if l <= lvl:
                        f_low, f_lvl = min(l, lvl), min(o, lvl)
                        break
                    if h >= 11.0:
                        f_low, f_lvl = 11.0, 11.0
                        break
                    if h > hi:
                        hi = h
                    if trail > 0 and (not armed_t) and hi >= arm:
                        armed_t = True
                    if lock > 0 and (not armed_l) and hi >= lock:
                        armed_l = True
                    lvl2 = 1.0 - stop
                    if armed_l and lvl2 < 1.03:
                        lvl2 = 1.03
                    if armed_t and lvl2 < (1.0 - trail) * hi:
                        lvl2 = (1.0 - trail) * hi
                    if c <= lvl2:
                        f_low, f_lvl = c, lvl2
                        break
                    if k == nS - 1 and hi < stale_g:
                        f_low, f_lvl = c, c
                        break
                    if fade == 1:
                        ref = C[i, k - 6] if k >= 6 else 1.0
                        if c <= 0.85 * ref:
                            f_low, f_lvl = c, c
                            break
                    if fade == 2 and k >= 11 and v1[i] > 0:
                        s = 0.0
                        for q in range(k - 11, k + 1):
                            s += V[i, q]
                        if s < 0.25 * v1[i]:
                            f_low, f_lvl = c, c
                            break
                out[i, j, 0] = f_low
                out[i, j, 1] = f_lvl

    out = np.zeros((len(v1), len(P), 2), np.float32)
    kern(A["C"], A["H"], A["L"], A["O"], A["V"], nb, v1, P.astype(np.float64), np.array(HOURS, np.float64), closes_only, out)
    return out


def to_money(M):
    v = 49.5 * np.maximum(M, 0.0)
    return v - np.maximum(0.01 * v, 0.10) * (v > 0) - 50.0


def cmd_grid(out):
    rows = pd.read_pickle(os.path.join(out, "paths.pkl"))
    A, nb, v1 = arrays(rows)
    P = var_array()
    M = run_grid(A, nb, v1, P)
    Mc = run_grid(A, nb, v1, P[[K]], closes_only=True)
    # the kernel against the plain reference on a sample
    rng = np.random.default_rng(1)
    bad = 0
    for _ in range(3000):
        i, j = rng.integers(len(rows)), rng.integers(len(P))
        a, b, _ = replay_np(A["C"][i], A["H"][i], A["L"][i], A["O"][i], A["V"][i], nb[i], v1[i], P[j])
        bad += abs(a - M[i, j, 0]) > 1e-4 * max(1, abs(a)) or abs(b - M[i, j, 1]) > 1e-4 * max(1, abs(b))
    print("kernel vs reference mismatches:", bad, "of 3000", flush=True)
    np.savez_compressed(os.path.join(out, "grid.npz"), M=M, Mc=Mc, w=np.array([r["w"] for r in rows]))
    print("grid", M.shape, flush=True)


# --------------------------------------------------------------------------------------------------------- the test
def boot(d, draws=20000, seed=7):
    d = np.asarray(d, float)
    rng = np.random.default_rng(seed)
    m = np.empty(draws)
    for k in range(0, draws, 2000):
        m[k:k + 2000] = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def pick(D, wv, fit, cand, how):
    """The chosen variant on the fit windows: WORST = best worst-window mean difference to K, MEAN = best pooled mean difference.
    Ties: fewer parts, then the earlier variant."""
    if how == "MEAN":
        sel = np.isin(wv, fit)
        score = D[sel].mean(0)
    else:
        score = np.min(np.stack([D[wv == w].mean(0) for w in fit]), axis=0)
    score = np.where(cand, score, -np.inf)
    best = score.max()
    tied = np.nonzero(score >= best - 1e-9)[0]
    j = min(tied, key=lambda x: (parts(VARIANTS[x]), x))
    return int(j), float(best)


def judge(Mon, D, wv, j, w):
    s = wv == w
    lo5, lo, hi = boot(D[s, j])
    return {"n": int(s.sum()), "mean": round(float(Mon[s, j].mean()), 2), "K": round(float(Mon[s, K].mean()), 2),
            "diff": round(float(D[s, j].mean()), 2), "lo5": round(lo5, 2), "ci95": [round(lo, 2), round(hi, 2)],
            "inProfit": round(100 * float((Mon[s, j] > 0).mean()), 1)}


def why_counts(rows, A, nb, v1, j):
    P = var_array()[j]
    out = {}
    for i in range(len(rows)):
        _, _, why = replay_np(A["C"][i], A["H"][i], A["L"][i], A["O"][i], A["V"][i], nb[i], v1[i], P)
        out[why] = out.get(why, 0) + 1
    return out


def cmd_test(out):
    g = np.load(os.path.join(out, "grid.npz"))
    M, Mc, wv = g["M"], g["Mc"], g["w"]
    cand = np.array([chart_driven(v) for v in VARIANTS])
    res = {"coins": {w: int((wv == w).sum()) for w in WN}, "variants": len(VARIANTS), "chartDriven": int(cand.sum()), "K": VARIANTS[K]}
    res["Kcloses"] = {w: round(float(to_money(Mc[wv == w, 0, 0]).mean()), 2) for w in WN}
    for fi, fill in enumerate(("low", "level")):
        Mon = to_money(M[:, :, fi])
        D = Mon - Mon[:, [K]]
        r = {"K": {w: round(float(Mon[wv == w, K].mean()), 2) for w in WN}}
        # walk-forward
        for how in ("WORST", "MEAN"):
            steps = []
            for s in range(2, 6):
                fit = WN[:s - 1]
                j, sc = pick(D, wv, fit, cand, how)
                steps.append(dict(step=s, fit=fit, test=WN[s - 1], j=j, rule=name(VARIANTS[j]), fitScore=round(sc, 2),
                                  **judge(Mon, D, wv, j, WN[s - 1])))
            r["walk_" + how] = steps
        # the user's bar: fitted on w1-w3, a whole unseen month (w4), then w5
        for how in ("WORST", "MEAN"):
            j, sc = pick(D, wv, WN[:3], cand, how)
            a, b = judge(Mon, D, wv, j, "w4"), judge(Mon, D, wv, j, "w5")
            r["bar_" + how] = dict(j=j, rule=name(VARIANTS[j]), fitScore=round(sc, 2), w4=a, w5=b,
                                   holds=bool(a["diff"] > 0 and a["lo5"] > 0 and b["diff"] >= 0))
        # the live pick: WORST on all five windows
        j, sc = pick(D, wv, WN, cand, "WORST")
        r["live"] = dict(j=j, rule=name(VARIANTS[j]), v=VARIANTS[j], fitScore=round(sc, 2),
                         byWindow={w: judge(Mon, D, wv, j, w) for w in WN}, all=dict(zip(("mean", "K", "diff"), (
                             round(float(Mon[:, j].mean()), 2), round(float(Mon[:, K].mean()), 2), round(float(D[:, j].mean()), 2)))))
        # how many chart-driven variants beat K in every window, and in pooled terms
        per_w = np.stack([D[wv == w].mean(0) for w in WN])
        r["beatAllWindows"] = int(((per_w > 0).all(0) & cand).sum())
        r["bestPooledHindsight"] = name(VARIANTS[int(np.argmax(np.where(cand, D.mean(0), -np.inf)))])
        r["share_pooled_better"] = round(100 * float(((D.mean(0) > 0) & cand).sum() / cand.sum()), 1)
        res[fill] = r
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float)[:6000])


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"paths": cmd_paths, "grid": cmd_grid, "test": cmd_test}[cmd](*args)
