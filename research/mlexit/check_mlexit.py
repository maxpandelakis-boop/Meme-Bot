"""A learned sell decision for the Pick account (fake money only): research/mlexit/PREREG-MLEXIT-2026-10-24.md.

  build <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <chain.parquet> <out dir>   entries, paths, labels, features
  check <out dir>                                       the rules against research/chartexit/result.json, the no-future check
  choose <out dir>                                      24 configurations fitted on w1+w2, judged on w3's P coins -> choose.json
  test <out dir>                                        the chosen one fitted on w1-w3, judged on w4/w5; diagnostics -> result.json

The Pick-type coins (family P) and their entry are research/chartexit/check_chartexit.py's coin_path, repeated here line by line
(the check command compares the counts and K / v3 per window with research/chartexit/result.json). Nothing is bought; no network.
Needs pandas, pyarrow, numba, lightgbm."""
import glob, json, math, os, sys, zlib
import numpy as np, pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chartexit"))
import check_chartexit as X                                   # noqa: E402  windows, fees, the bootstrap

BAR, MIN, H = X.BAR, X.MIN, X.H
WN = X.WN
NB = X.NB                     # 150 five-minute candles after the entry
N_EXTRA = 3                   # random further entries per coin
CAP = 6_000_000               # states per fit at most
SEED = 7
HOURS = X.HOURS               # (1, 2, 3, 6, 12)
V3 = dict(stop=0.50, trail=0.15, arm=1.5, lock=0.0, stale_h=0, stale_g=0.0, fade="drop", T=6)
KR = dict(stop=0.30, trail=0.0, arm=0.0, lock=0.0, stale_h=0, stale_g=0.0, fade="none", T=6)
B0 = dict(stop=0.50, trail=0.0, arm=0.0, lock=0.0, stale_h=0, stale_g=0.0, fade="none", T=12)


def pvec(v):
    return np.array([v["stop"], v["trail"], v["arm"], v["lock"], v["stale_h"], v["stale_g"], X.FADES.index(v["fade"]), v["T"]], float)


# ------------------------------------------------------------------------------------------------------------- features
LAGS = (1, 2, 3, 6, 12, 24, 48, 72)              # five-minute candles: 5 min .. 6 h
SEQ = 24
COIN_F = (["lr%d" % (5 * n) for n in LAGS] + ["seq%d" % q for q in range(SEQ)]
          + ["vol30", "vol60", "vol180", "rng1h", "rng4h", "ath", "atl", "up12", "downrun", "body", "wick_up", "wick_lo",
             "v5", "v15", "v60", "v60_prev", "v60_ratio", "nt12", "nt36", "upvol", "turnover", "lmc", "lliq", "liqmc",
             "age", "sol1h", "sol6h", "sol24h", "btc24h", "hour", "wday"])
POS_F = ["held", "ret", "hi_since", "lo_since", "dd", "since_hi", "v60_entry", "entry_h"]
LAUNCH_F = ["l_x", "l_tg", "l_web", "l_desc", "l_video", "l_name", "l_sym", "l_cjk", "l_prev30", "l_curve", "l_sigs"]
FEATS = COIN_F + POS_F + LAUNCH_F


def roll_sum(x, n):
    c = np.r_[0.0, np.cumsum(x)]
    i = np.arange(len(x))
    return c[i + 1] - c[np.maximum(0, i + 1 - n)]


def roll_ext(x, n, fn):
    """fn (np.maximum / np.minimum) over the last n values, the start padded with the first value."""
    pad = np.r_[np.full(n - 1, x[0]), x]
    w = np.lib.stride_tricks.sliding_window_view(pad, n)
    return fn.reduce(w, axis=1)


def roll_std(x, n):
    pad = np.r_[np.full(n - 1, np.nan), x]
    w = np.lib.stride_tricks.sliding_window_view(pad, n)
    with np.errstate(all="ignore"):
        return np.nanstd(w, axis=1)


def coin_features(cf, hi, lo, op, cl, has, v, p_first, kk, t0, gm, mkt):
    """Every coin number at every five-minute candle i, from candles 0..i only (the decision at candle i's close). -> (600, n)"""
    n = len(cf)
    c = np.where(np.isfinite(cf), cf, p_first)
    lc = np.log(c)
    F = {}
    for q in LAGS:
        prev = np.r_[np.full(q, math.log(p_first)), lc[:-q]]
        F["lr%d" % (5 * q)] = lc - prev
    r1 = F["lr5"]
    for q in range(SEQ):
        F["seq%d" % q] = np.r_[np.full(q, 0.0), r1[:n - q]]
    F["vol30"], F["vol60"], F["vol180"] = roll_std(r1, 6), roll_std(r1, 12), roll_std(r1, 36)
    hh = np.where(has, np.fmax(hi, cl), c)
    ll = np.where(has, np.fmin(lo, cl), c)
    hh = np.where(hh <= X.WICK_X * c, hh, c)
    ll = np.where(ll >= c / X.WICK_X, ll, c)
    for lab, q in (("rng1h", 12), ("rng4h", 48)):
        mx, mn = roll_ext(hh, q, np.maximum), roll_ext(ll, q, np.minimum)
        F[lab] = np.where(mx > mn, (c - mn) / np.maximum(mx - mn, 1e-30), 0.5)
    F["ath"] = c / np.maximum.accumulate(hh)
    F["atl"] = c / np.minimum.accumulate(ll)
    up = np.r_[0.0, (np.diff(c) > 0).astype(float)]
    dn = np.r_[0.0, (np.diff(c) < 0).astype(float)]
    F["up12"] = roll_sum(up, 12) / 12
    run = np.zeros(n)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if dn[i] else 0
    F["downrun"] = run
    o = np.where(has & np.isfinite(op) & (op > 0), op, c)
    F["body"] = np.where(has, c / o - 1, 0.0)
    F["wick_up"] = np.where(has, (hh - np.maximum(o, c)) / c, 0.0)
    F["wick_lo"] = np.where(has, (np.minimum(o, c) - ll) / c, 0.0)
    v15, v60 = roll_sum(v, 3), roll_sum(v, 12)
    v60p = np.r_[np.zeros(12), v60[:-12]]
    F["v5"], F["v15"], F["v60"], F["v60_prev"] = np.log1p(v), np.log1p(v15), np.log1p(v60), np.log1p(v60p)
    F["v60_ratio"] = np.log1p(v60) - np.log1p(v60p)
    F["nt12"] = 1 - roll_sum(has.astype(float), 12) / 12
    F["nt36"] = 1 - roll_sum(has.astype(float), 36) / 36
    F["upvol"] = np.where(v60 > 0, roll_sum(v * up, 12) / np.maximum(v60, 1e-9), 0.5)
    mc = c * 1e9
    td = t0 + (np.arange(n) + 1) * BAR                        # the decision time: candle i's end
    sol_px = mkt.px("SOLUSDT", td, 0)                         # the last finished hour (no look-ahead)
    liq = 2 * np.sqrt(kk * c / sol_px) * sol_px
    F["turnover"] = np.log1p(v60) - np.log(mc)
    F["lmc"], F["lliq"], F["liqmc"] = np.log(mc), np.log(liq), liq / mc
    F["age"] = (td - gm) / MIN
    F["sol1h"] = sol_px / mkt.px("SOLUSDT", td, 1) - 1
    F["sol6h"] = sol_px / mkt.px("SOLUSDT", td, 6) - 1
    F["sol24h"] = sol_px / mkt.px("SOLUSDT", td, 24) - 1
    F["btc24h"] = mkt.px("BTCUSDT", td, 0) / mkt.px("BTCUSDT", td, 24) - 1
    dt = pd.to_datetime(td, unit="ms", utc=True)
    F["hour"], F["wday"] = dt.hour.to_numpy().astype(float), dt.weekday.to_numpy().astype(float)
    return np.stack([F[k] for k in COIN_F], 1).astype(np.float32)


class Market:
    def __init__(self, path):
        m = json.load(open(path))
        self.d = {k: np.array(v, float) for k, v in m.items()}

    def px(self, sym, td, back):
        a = self.d[sym]
        i = np.searchsorted(a[:, 0] + H, td, side="right") - 1 - back      # the hour that closed at or before td, back hours earlier
        return a[np.clip(i, 0, len(a) - 1), 1]


# --------------------------------------------------------------------------------------------------------- the replays
def sim(C, Hh, L, O, V, nb, v1, P):
    """check_chartexit.replay_np, also returning the candle the sale happened in. -> (mult "low" fill, candle, why)"""
    stop, trail, arm, lock, stale_h, stale_g, fade, T = P
    nT = nb[HOURS.index(int(T))]
    nS = nb[HOURS.index(int(stale_h))] if stale_h else -1
    hi, armed_t, armed_l = 1.0, trail > 0 and arm <= 1.0, False
    for k in range(nT):
        c, h, l = C[k], Hh[k], L[k]
        lvl = 1.0 - stop
        if armed_l:
            lvl = max(lvl, 1.03)
        if armed_t:
            lvl = max(lvl, (1.0 - trail) * hi)
        if l <= lvl:
            return min(l, lvl), k, "stop" if lvl <= 1.0 - stop + 1e-12 else "trail"
        if h >= 11.0:
            return 11.0, k, "tp"
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
            return c, k, "trail"
        if k == nS - 1 and hi < stale_g:
            return c, k, "stale"
        if fade == 1:
            ref = C[k - 6] if k >= 6 else 1.0
            if c <= 0.85 * ref:
                return c, k, "drop"
        if fade == 2 and k >= 11 and v1 > 0 and V[k - 11:k + 1].sum() < 0.25 * v1:
            return c, k, "vol"
    return C[nT - 1], nT - 1, "time"


def _policy_kernel():
    import numba

    @numba.njit(parallel=True, cache=False)
    def kern(C, Hh, L, nT, start, pred, base_v3, m, cad, out_m, out_k, out_why):
        """The ML policies on n entries. The base: B0 (floor -50 %, 11x, nT) or v3 (+ trail 15 % once 1.5x, drop -15 % in 30 min).
        At a decision candle k ((k + 1) % cad == 0, k < nT - 1) after the base's own checks: sell at the close when pred < 1 - m.
        pred[start[e] + k] is entry e's prediction at candle k (NaN: no state). why: 0 time, 1 floor, 2 tp, 3 trail, 4 drop, 5 model"""
        n = C.shape[0]
        for e in numba.prange(n):
            hi = 1.0
            armed = False
            res_m, res_k, res_w = C[e, nT[e] - 1], nT[e] - 1, 0
            for k in range(nT[e]):
                c, h, l = C[e, k], Hh[e, k], L[e, k]
                lvl = 0.5
                if base_v3 and armed and lvl < 0.85 * hi:
                    lvl = 0.85 * hi
                if l <= lvl:
                    res_m, res_k, res_w = min(l, lvl), k, (3 if lvl > 0.5 + 1e-12 else 1)
                    break
                if h >= 11.0:
                    res_m, res_k, res_w = 11.0, k, 2
                    break
                if h > hi:
                    hi = h
                if base_v3:
                    if (not armed) and hi >= 1.5:
                        armed = True
                    lvl2 = 0.5
                    if armed and lvl2 < 0.85 * hi:
                        lvl2 = 0.85 * hi
                    if c <= lvl2:
                        res_m, res_k, res_w = c, k, 3
                        break
                    ref = C[e, k - 6] if k >= 6 else 1.0
                    if c <= 0.85 * ref:
                        res_m, res_k, res_w = c, k, 4
                        break
                if k < nT[e] - 1 and (k + 1) % cad == 0:
                    p = pred[start[e] + k]
                    if p == p and p < 1.0 - m:
                        res_m, res_k, res_w = c, k, 5
                        break
            out_m[e], out_k[e], out_why[e] = res_m, res_k, res_w
    return kern


KERN = None


def run_policy(E, pred, base_v3, m, cad):
    """E: the entries' arrays (C, H, L, nT, start); pred: one value per stored state. -> (mult, candle, why) per entry"""
    global KERN
    if KERN is None:
        KERN = _policy_kernel()
    n = len(E["nT"])
    om, ok, ow = np.zeros(n), np.zeros(n, np.int64), np.zeros(n, np.int64)
    KERN(E["C"], E["H"], E["L"], E["nT"], E["start"], pred.astype(np.float64), base_v3, float(m), int(cad), om, ok, ow)
    return om, ok, ow


# --------------------------------------------------------------------------------------------------------- build
CTX = {}


def launch_facts(meta_all, chain):
    """Per mint: the launch numbers (LAUNCH_F); the creator's graduations in the 30 days before (over every window's table)."""
    ch = chain.set_index("mint")
    t_of = {r["mint"]: int(r["t"]) for r in meta_all}
    rows = {}
    by_creator = {}
    for mint, cr in ch["curve_creator"].dropna().items():
        if mint in t_of:
            by_creator.setdefault(cr, []).append(t_of[mint])
    for cr in by_creator:
        by_creator[cr] = np.sort(np.array(by_creator[cr]))
    cjk = lambda s: float(any("぀" <= x <= "鿿" or "가" <= x <= "힯" for x in s))
    for mint, r in ch.iterrows():
        if mint not in t_of:
            continue
        t = t_of[mint]
        read = isinstance(r["f_keys"], str)

        def link(k):
            if not read:
                return np.nan
            s = r[k]
            return float(isinstance(s, str) and len(s.strip()) > 0)
        cr = r["curve_creator"]
        if isinstance(cr, str) and cr in by_creator:
            a = by_creator[cr]
            prev = float(np.sum((a < t) & (a >= t - 30 * 24 * H)))
        else:
            prev = np.nan
        name, sym = r["name"] if isinstance(r["name"], str) else "", r["symbol"] if isinstance(r["symbol"], str) else ""
        cs = r["created_s"]
        rows[mint] = np.array([link("f_twitter"), link("f_telegram"), link("f_website"),
                               float(r["f_desc_len"]) if read and r["f_desc_len"] == r["f_desc_len"] else np.nan,
                               link("f_video"), float(len(name)), float(len(sym)), cjk(name), prev,
                               math.log1p(max(0.0, (t / 1000 - cs) / 60)) if cs == cs and cs is not None else np.nan,
                               math.log1p(r["curve_sigs"]) if r["curve_sigs"] == r["curve_sigs"] and r["curve_sigs"] is not None else np.nan],
                              np.float32)
    return rows


def coin_entries(c, b):
    """One coin: its P entry (check_chartexit.coin_path's gates, line by line) and its W entries, with paths, labels, features."""
    mkt, gaps, lf = CTX["mkt"], CTX["gaps"], CTX["launch"]
    t0 = int(c["t"]) // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return []
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n)
    has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]; op[j] = b["o"].to_numpy()[keep]
    v[j] = b["v"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cl[~has] = np.nan
    vf = np.where(has, np.nan_to_num(v), 0.0)              # the features' volume (coin_path's gates keep v as it is)
    cf = pd.Series(cl).ffill().to_numpy()
    i0 = int(np.argmax(has))
    if not has[i0]:
        return []
    p_first = op[i0] if np.isfinite(op[i0]) and op[i0] > 0 else cl[i0]
    cv = np.r_[0, np.cumsum(v)]
    kk = float(c["sol0"]) * float(c["tok0"])
    gm = int(c["t"])
    cands = []
    for E in range(60, 1441, 60):
        te = gm + E * MIN
        jl = (te - t0) // BAR - 1
        if jl < 0 or jl + 1 + 12 >= n or not np.isfinite(cf[jl]) or not has[:jl + 1].any():
            continue
        p0 = cf[jl]
        usd = float(X.solusd(te))
        mc = p0 * 1e9
        liq = 2 * math.sqrt(kk * p0 / usd) * usd
        v24 = cv[jl + 1] - cv[max(0, jl + 1 - 288)]
        v1 = cv[jl + 1] - cv[max(0, jl + 1 - 12)]

        def px(back):
            k = jl - back
            return cf[k] if k >= 0 and np.isfinite(cf[k]) else p_first

        r1h, r6h, r24h = p0 / px(12) - 1, p0 / px(72) - 1, p0 / px(288) - 1
        isP = (E >= 360 and 100_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 >= 15_000 and not (r1h <= -0.10 or r6h <= -0.50 or r24h <= -0.70)
               and not (r1h >= 2.0 or r6h >= 0.90) and v24 / mc <= 8)
        isW = E >= 360 and 50_000 <= mc <= 5_000_000 and liq >= 10_000 and v24 >= 5_000
        isA = 30_000 <= mc <= 10_000_000 and liq >= 8_000 and v1 > 0           # amendment 1: the ALL universe
        if not (isP or isW or isA):
            continue
        if gaps is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((gaps[:, 1] >= a) & (gaps[:, 0] <= z)).any():
                continue
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in HOURS + (24,)}
        if len(cf[jl + 2: jl + 2 + jt[24]]) < jt[24]:
            break                              # not 24 h of candles left (coin_path: no entry; the later hours fail too)
        cands.append(dict(E=E, te=te, jl=jl, p0=p0, v1=v1, nb=[int(min(NB, jt[t])) for t in HOURS], isP=isP, isW=isW, isA=isA))
    if not cands:
        return []
    firstP = next((x for x in cands if x["isP"]), None)
    Ws = [x for x in cands if x["isW"]]
    firstW = Ws[0] if Ws else None
    rest = [x for x in Ws if x is not firstP]
    rng = np.random.default_rng((SEED, zlib.crc32(c["pool"].encode())))
    extra = [rest[i] for i in sorted(rng.choice(len(rest), size=min(N_EXTRA, len(rest)), replace=False))] if rest else []
    taken = {x["E"] for x in [firstP, firstW] + extra if x is not None}
    restA = [x for x in cands if x["isA"] and x["E"] not in taken]
    extraA = [restA[i] for i in sorted(rng.choice(len(restA), size=min(N_EXTRA, len(restA)), replace=False))] if restA else []
    pick = {}
    for x, role in [(firstP, "P"), (firstW, "W1")] + [(x, "X") for x in extra] + [(x, "Y") for x in extraA]:
        if x is not None:
            pick.setdefault(x["E"], [x, set()])[1].add(role)
    CF = coin_features(cf, hi, lo, op, cl, has, vf, p_first, kk, t0, gm, mkt)
    LF = lf.get(c["mint"], np.full(len(LAUNCH_F), np.nan, np.float32))
    v60 = roll_sum(vf, 12)
    out = []
    for E, (x, roles) in sorted(pick.items()):
        jl, p0 = x["jl"], x["p0"]
        s = slice(jl + 2, jl + 2 + NB)
        C = cf[s] / p0
        hs = has[s]
        Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
        Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
        O = np.where(hs & np.isfinite(op[s]) & (op[s] > 0), op[s], np.r_[cf[jl + 1], cf[jl + 2: jl + 1 + NB]]) / p0
        Hh = np.where(Hh <= X.WICK_X * C, Hh, C)
        Ll = np.where(Ll >= C / X.WICK_X, Ll, C)
        O = np.clip(O, Ll, Hh)
        V = v[s] * hs
        nb = np.array(x["nb"], np.int64)
        lab = {}
        for key, P in (("K", KR), ("V3", V3), ("B0", B0)):
            mlt, k, why = sim(C, Hh, Ll, O, V, nb, x["v1"], pvec(P))
            lab[key] = (float(mlt), int(k), why)
        # the states: candles 0 .. min(tau_B0, nT12 - 1) - 1 (B0 still holds after the candle's close, not the last candle)
        nT12 = nb[HOURS.index(12)]
        ns = min(lab["B0"][1], nT12 - 1)
        k = np.arange(ns)
        ix = jl + 2 + k
        himax = np.maximum.accumulate(Hh[:ns]) if ns else np.zeros(0)
        lomin = np.minimum.accumulate(Ll[:ns]) if ns else np.zeros(0)
        since_hi = k - np.maximum.accumulate(np.where(Hh[:ns] >= himax - 1e-12, k, 0)) if ns else np.zeros(0)
        PF = np.stack([(k + 1) * 5.0, C[:ns], himax, lomin, C[:ns] / np.maximum(himax, 1e-30), since_hi * 5.0,
                       np.log1p(v60[ix]) - math.log1p(x["v1"]), np.full(ns, E / 60.0)], 1).astype(np.float32) if ns else np.zeros((0, len(POS_F)), np.float32)
        F = np.concatenate([CF[ix], PF, np.repeat(LF[None, :], ns, 0)], 1).astype(np.float32)
        out.append(dict(pool=c["pool"], w=c["w"], E=E, te=x["te"], roles="".join(sorted(roles)), nb=nb, v1=float(x["v1"]),
                        C=C.astype(np.float32), H=Hh.astype(np.float32), L=Ll.astype(np.float32), O=O.astype(np.float32),
                        K=lab["K"], V3=lab["V3"], B0=lab["B0"], F=F))
    return out


def _work(args):
    path, k, n, dest = args
    b = pd.read_parquet(path)
    if n > 1:
        pools = np.sort(b["pool"].unique())[k::n]
        b = b[b["pool"].isin(pools)]
    rows = []
    for pool, g in b.groupby("pool", sort=False):
        c = CTX["meta"].get(pool)
        if c is None:
            continue
        rows += coin_entries(c, g.sort_values("t"))
    if not rows:
        return dest, 0
    meta = pd.DataFrame([{k2: r[k2] for k2 in ("pool", "w", "E", "te", "roles", "v1")} | {
        "nb": r["nb"].tolist(), "K_m": r["K"][0], "K_k": r["K"][1], "K_why": r["K"][2], "V3_m": r["V3"][0], "V3_k": r["V3"][1],
        "V3_why": r["V3"][2], "B0_m": r["B0"][0], "B0_k": r["B0"][1], "B0_why": r["B0"][2], "ns": len(r["F"])} for r in rows])
    np.savez(dest, C=np.stack([r["C"] for r in rows]), H=np.stack([r["H"] for r in rows]), L=np.stack([r["L"] for r in rows]),
             O=np.stack([r["O"] for r in rows]), F=np.concatenate([r["F"] for r in rows]).astype(np.float16))
    meta.to_parquet(dest.replace(".npz", ".parquet"))
    return dest, len(rows)


def cmd_build(md, h2, gapf, chainf, out):
    import multiprocessing as mp
    os.makedirs(os.path.join(out, "shards"), exist_ok=True)
    s = np.array(json.load(open(os.path.join(md, "market.json")))["SOLUSDT"], dtype=float)
    X.SOL = (s[:, 0], s[:, 1])
    g = np.sort(np.load(gapf))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    CTX["gaps"] = np.c_[st[big], en[big]]
    CTX["mkt"] = Market(os.path.join(md, "market.json"))
    meta, allm = {}, []
    for r in pd.read_parquet(os.path.join(h2, "meta_h2.parquet")).to_dict("records"):
        allm.append(r)
        r["w"] = X.window(int(r["t"]))
        if r["w"]:
            meta[r["pool"]] = r
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        for r in json.load(open(f)):
            allm.append(r)
            r["w"] = X.window(int(r["t"]))
            if r["w"]:
                meta[r["pool"]] = r
    CTX["meta"] = meta
    CTX["launch"] = launch_facts(allm, pd.read_parquet(chainf))
    print("coins in windows", len(meta), "launch facts", len(CTX["launch"]), flush=True)
    jobs = [(f, 0, 1, os.path.join(out, "shards", "h2_" + os.path.basename(f).replace(".parquet", ".npz")))
            for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    jobs += [(f, k, 6, os.path.join(out, "shards", "gt_%s_%d.npz" % (os.path.basename(f)[5:7], k)))
             for f in sorted(glob.glob(os.path.join(md, "bars_w*.parquet"))) for k in range(6)]
    tot = 0
    with mp.get_context("fork").Pool(3) as pool:
        for dest, nr in pool.imap_unordered(_work, jobs, chunksize=1):
            tot += nr
            print(os.path.basename(dest), nr, "total", tot, flush=True)


# --------------------------------------------------------------------------------------------------------- load
def load(out, windows=None):
    """Every shard -> entries (one row each, the paths as arrays) and the states' features; a pool in two sources counts once
    (the earlier entry first, as coin_path)."""
    metas, Fs, Cs, Hs, Ls = [], [], [], [], []
    for f in sorted(glob.glob(os.path.join(out, "shards", "*.npz"))):
        m = pd.read_parquet(f.replace(".npz", ".parquet"))
        if windows is not None and not m["w"].isin(windows).any():
            continue
        z = np.load(f)
        m["shard"] = len(metas)
        m["row"] = np.arange(len(m))
        m["s0"] = np.r_[0, np.cumsum(m["ns"].to_numpy())[:-1]]
        metas.append(m); Fs.append(z["F"]); Cs.append(z["C"]); Hs.append(z["H"]); Ls.append(z["L"])
    M = pd.concat(metas, ignore_index=True)
    # one source per pool, as coin_path: the source with the earlier P entry; without one, the earlier entry
    hasP = M["roles"].str.contains("P")
    fp = M[hasP].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    fo = M[~M["pool"].isin(fp["pool"])].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    M = M.merge(pd.concat([fp, fo]).rename(columns={"shard": "keep"}), on="pool")
    M = M[M["shard"] == M["keep"]].drop(columns="keep")
    if windows is not None:
        M = M[M["w"].isin(windows)]
    M = M.sort_values(["te", "pool", "E"]).reset_index(drop=True)
    C = np.stack([Cs[s][r] for s, r in zip(M["shard"], M["row"])]).astype(np.float64)
    Hh = np.stack([Hs[s][r] for s, r in zip(M["shard"], M["row"])]).astype(np.float64)
    L = np.stack([Ls[s][r] for s, r in zip(M["shard"], M["row"])]).astype(np.float64)
    F = np.concatenate([Fs[s][a:a + n] for s, a, n in zip(M["shard"], M["s0"], M["ns"])]).astype(np.float32) if len(M) else None
    start = np.r_[0, np.cumsum(M["ns"].to_numpy())[:-1]].astype(np.int64)
    return M, dict(C=C, H=Hh, L=L, start=start), F


# --------------------------------------------------------------------------------------------------------- states, fits
LGB = dict(objective="regression", learning_rate=0.05, num_leaves=63, min_data_in_leaf=2000, feature_fraction=0.7,
           bagging_fraction=0.7, bagging_freq=1, lambda_l2=10.0, seed=SEED, num_threads=3, verbose=-1)
UNIVERSES = ("W", "ALL")
FAMILIES = ("A1", "A2", "B")
MARGINS = (0.0, 0.03, 0.06, 0.10)
CADS = (1, 3)                 # every five-minute candle, every third (15 min)


def in_universe(M, u):
    r = M["roles"]
    return (r.str.contains("P") | r.str.contains("X")) if u == "W" else pd.Series(True, index=M.index)


def nstates(M, base):
    """States per entry: B0 keeps every stored state; v3 those before its own sale."""
    return M["ns"].to_numpy() if base == "B0" else np.minimum(M["V3_k"].to_numpy(), M["ns"].to_numpy())


def states(M, E, rows, base):
    """-> (index into F, entry, candle) of every state of the given entries under the base rule"""
    ns = nstates(M, base)[rows]
    ent = np.repeat(rows, ns)
    k = np.arange(ent.size) - np.repeat(np.r_[0, np.cumsum(ns)[:-1]], ns)
    return E["start"][ent] + k, ent, k


def label(M, E, ent, k, base):
    m = M["B0_m"].to_numpy() if base == "B0" else M["V3_m"].to_numpy()
    return m[ent] / E["C"][ent, k]


def gtime(M):
    return (M["te"] - M["E"] * MIN).to_numpy()


def fit(F, idx, y, gt_state, objective="regression"):
    """LightGBM with the fixed settings; early stop on the last 15 % of the training coins by graduation time."""
    import lightgbm as lgb
    cut = np.quantile(np.unique(gt_state), 0.85)
    va = gt_state >= cut
    p = dict(LGB, objective=objective)
    if objective == "binary":
        p["metric"] = "binary_logloss"
    dtr = lgb.Dataset(F[idx[~va]], y[~va], free_raw_data=True)
    dva = lgb.Dataset(F[idx[va]], y[va], reference=dtr, free_raw_data=True)
    b = lgb.train(p, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    return b


def predict(b, F, idx):
    return b.predict(F[idx], num_iteration=b.best_iteration).astype(np.float64)


def full_pred(nF, idx, p):
    out = np.full(nF, np.nan)
    out[idx] = p
    return out


def entries_of(E, rows):
    return {k: E[k][rows] for k in ("C", "H", "L")} | {"start": E["start"][rows]}


def policy(M, E, rows, pred_full, fam, m, cad):
    """The ML policy on the given entries -> (mult, candle, why)"""
    sub = entries_of(E, rows)
    nb = np.stack(M["nb"].to_numpy()[rows])
    sub["nT"] = (nb[:, HOURS.index(12)] if fam != "B" else nb[:, HOURS.index(6)]).astype(np.int64)
    return run_policy(sub, pred_full, fam == "B", m, cad)


def continuation(M, E, rows, pred_full, m, cad):
    """A2's label: for every B0 state of the entries, what holding is worth when A1's policy (pred_full, m, cad) decides from the
    next candle on, over the price now. -> (index into F, G)"""
    out_i, out_g = [], []
    nb = np.stack(M["nb"].to_numpy()[rows])
    for q, e in enumerate(rows):
        ns, nT, st = int(M["ns"].iat[e]), int(nb[q, HOURS.index(12)]), int(E["start"][e])
        tau, mB = int(M["B0_k"].iat[e]), float(M["B0_m"].iat[e])
        j = np.arange(ns)
        p = pred_full[st:st + ns]
        sell = j[((j + 1) % cad == 0) & (j < nT - 1) & (p < 1.0 - m)]
        C = E["C"][e]
        nxt = np.searchsorted(sell, j, side="right")             # the first sale after candle k
        js = np.where(nxt < len(sell), sell[np.minimum(nxt, len(sell) - 1)], 10 ** 9)
        val = np.where(js < tau, C[np.minimum(js, len(C) - 1)], mB)
        out_i.append(st + j); out_g.append(val / C[:ns])
    return np.concatenate(out_i), np.concatenate(out_g)


def money_of(mult):
    return X.to_money(np.asarray(mult, float))


def judge(d, base=None):
    lo5, lo, hi = X.boot(d)
    return {"n": int(len(d)), "diff": round(float(np.mean(d)), 2), "lo5": round(lo5, 2), "ci95": [round(lo, 2), round(hi, 2)]}


def trade_stats(mon, mult):
    srt = np.sort(mon)[::-1]
    return {"mean": round(float(mon.mean()), 2), "inProfit": round(100 * float((mon > 0).mean()), 1),
            "x2": int((mult >= 2).sum()), "x3": int((mult >= 3).sum()), "lost20": int((mon <= -20).sum()),
            "best2pct": round(float(srt[:max(1, len(srt) // 50)].sum()), 1)}


def train_family(M, E, F, train_rows, fam, configs, log=print):
    """Fits for one family on the training entries -> {(m, cad): predictor} (A1 and B: one model for all margins)."""
    base = "V3" if fam == "B" else "B0"
    idx, ent, k = states(M, E, train_rows, base)
    y = label(M, E, ent, k, base)
    gt = gtime(M)[ent]
    b1 = fit(F, idx, y, gt)
    log("  %s fit on %d states, %d trees" % (fam, len(idx), b1.best_iteration))
    if fam != "A2":
        return {c: b1 for c in configs}, b1
    # A2: A1's predictions out of fold (4 folds by coin), A1's policy per (m, cad), the second model on its value
    fold = np.array([zlib.crc32(pl.encode()) % 4 for pl in M["pool"].to_numpy()])
    oof = np.full(len(F), np.nan)
    for f in range(4):
        tr = train_rows[fold[train_rows] != f]
        te = train_rows[fold[train_rows] == f]
        i2, e2, k2 = states(M, E, tr, base)
        bf = fit(F, i2, label(M, E, e2, k2, base), gtime(M)[e2])
        it, _, _ = states(M, E, te, base)
        oof[it] = predict(bf, F, it)
    out = {}
    for c in configs:
        m, cad = c
        i3, g3 = continuation(M, E, train_rows, oof, m, cad)
        gt3 = np.repeat(gtime(M)[train_rows], M["ns"].to_numpy()[train_rows])
        b2 = fit(F, i3, g3, gt3)
        log("  A2 m=%.2f cad=%d: second model %d trees" % (m, cad, b2.best_iteration))
        out[c] = b2
    return out, b1


def evaluate(M, E, F, rows, fam, model, m, cad):
    base = "V3" if fam == "B" else "B0"
    idx, _, _ = states(M, E, rows, "B0")           # every stored state gets a prediction (the policy reads what it needs)
    pf = full_pred(len(F), idx, predict(model, F, idx))
    return policy(M, E, rows, pf, fam, m, cad)


# --------------------------------------------------------------------------------------------------------- commands
def cmd_check(out, *_):
    """The rules against research/chartexit/result.json; the kernel against the plain replays; no feature looks ahead."""
    M, E, F = load(out)
    ref = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chartexit", "result.json")))
    P = M["roles"].str.contains("P").to_numpy()
    res = {"P": {}, "ref": {}}
    for w in WN:
        s = P & (M["w"] == w).to_numpy()
        res["P"][w] = {"n": int(s.sum()), "K": round(float(money_of(M["K_m"][s]).mean()), 2), "V3": round(float(money_of(M["V3_m"][s]).mean()), 2)}
        res["ref"][w] = {"n": ref["coins"][w], "K": ref["low"]["K"][w], "V3": ref["low"]["live"]["byWindow"][w]["mean"]}
    rows = np.nonzero(P)[0]
    nan = np.full(len(F), np.nan)
    a, ka, _ = policy(M, E, rows, nan, "B", 0.0, 1)
    b, kb, _ = policy(M, E, rows, nan, "A1", 0.0, 1)
    res["kernel_v3_mismatch"] = int((np.abs(a - M["V3_m"].to_numpy()[rows]) > 1e-6).sum() + (ka != M["V3_k"].to_numpy()[rows]).sum())
    res["kernel_B0_mismatch"] = int((np.abs(b - M["B0_m"].to_numpy()[rows]) > 1e-6).sum() + (kb != M["B0_k"].to_numpy()[rows]).sum())
    res["states"] = int(len(F))
    if len(sys.argv) > 4:
        res["nofuture"] = nofuture(sys.argv[3], sys.argv[4])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(out, "check.json"), "w"), indent=1)


def nofuture(md, h2, ncoins=150):
    """Changing every candle after candle i changes no number at candle i (coin_features), on coins of both sources."""
    s = np.array(json.load(open(os.path.join(md, "market.json")))["SOLUSDT"], dtype=float)
    X.SOL = (s[:, 0], s[:, 1])
    mkt = Market(os.path.join(md, "market.json"))
    rng = np.random.default_rng(SEED)
    bad = tested = 0
    for f in (sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))[30], os.path.join(md, "bars_w2.parquet")):
        b = pd.read_parquet(f)
        pools = b["pool"].unique()
        for pool in rng.choice(pools, size=min(ncoins, len(pools)), replace=False):
            g = b[b["pool"] == pool].sort_values("t")
            t0 = int(g["t"].iat[0]) // BAR * BAR
            j = ((g["t"].to_numpy() - t0) // BAR).astype(int)
            k = (j >= 0) & (j < 600)
            j = j[k]
            A = {q: np.full(600, np.nan) for q in "ohlc"}
            for q in "ohlc":
                A[q][j] = g[q].to_numpy()[k]
            v = np.zeros(600); v[j] = np.nan_to_num(g["v"].to_numpy()[k])
            has = np.isfinite(A["c"]) & (A["c"] > 0)
            cf = pd.Series(np.where(has, A["c"], np.nan)).ffill().to_numpy()
            if not has.any():
                continue
            pf = A["c"][int(np.argmax(has))]
            full = coin_features(cf, A["h"], A["l"], A["o"], A["c"], has, v, pf, 85.0 * 2.069e8, t0, t0, mkt)
            for i in rng.integers(72, 450, 3):
                cut = {q: np.where(np.arange(600) <= i, A[q], rng.uniform(0.1, 9) * np.nanmean(A[q])) for q in "ohlc"}
                hs2 = np.where(np.arange(600) <= i, has, True)
                v2 = np.where(np.arange(600) <= i, v, 1e6)
                cf2 = pd.Series(np.where(hs2, cut["c"], np.nan)).ffill().to_numpy()
                part = coin_features(cf2, cut["h"], cut["l"], cut["o"], cut["c"], hs2, v2, pf, 85.0 * 2.069e8, t0, t0, mkt)
                same = np.isclose(full[i], part[i], rtol=1e-5, atol=1e-6, equal_nan=True)
                bad += int((~same).sum())
                tested += 1
    return {"tested": tested, "numbers_changed": bad}


def cmd_choose(out):
    M, E, F = load(out)
    res = {"configs": []}
    P = M["roles"].str.contains("P").to_numpy()
    val = np.nonzero(P & (M["w"] == "w3").to_numpy())[0]
    mV3 = money_of(M["V3_m"].to_numpy()[val]); mK = money_of(M["K_m"].to_numpy()[val])
    res["w3"] = {"n": int(len(val)), "V3": round(float(mV3.mean()), 2), "K": round(float(mK.mean()), 2)}
    configs = [(m, c) for m in MARGINS for c in CADS]
    for u in UNIVERSES:
        tr = np.nonzero(in_universe(M, u).to_numpy() & M["w"].isin(["w1", "w2"]).to_numpy())[0]
        print(u, "training entries", len(tr), flush=True)
        for fam in FAMILIES:
            models, _ = train_family(M, E, F, tr, fam, configs, log=lambda s: print(s, flush=True))
            for (m, cad) in configs:
                mult, _, why = evaluate(M, E, F, val, fam, models[(m, cad)], m, cad)
                mon = money_of(mult)
                r = dict(universe=u, family=fam, m=m, cad=cad, mean=round(float(mon.mean()), 3), diffV3=round(float((mon - mV3).mean()), 3),
                         diffK=round(float((mon - mK).mean()), 3), modelSells=int((why == 5).sum()))
                res["configs"].append(r)
                print(r, flush=True)
    order = {"A1": 0, "A2": 1, "B": 2}
    best = max(res["configs"], key=lambda r: (round(r["diffV3"], 6), -UNIVERSES.index(r["universe"]), -order[r["family"]], r["m"], r["cad"]))
    res["chosen"] = best
    json.dump(res, open(os.path.join(out, "choose.json"), "w"), indent=1)
    print("chosen", best)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"build": cmd_build, "check": cmd_check, "choose": cmd_choose}[cmd](*args)
