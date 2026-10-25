"""A checker for the first -20 % touch after a buy (fake money only): research/dipcheck/PREREG-DIPCHECK-2026-10-25.md.

  build <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <chain.parquet> <out dir>   buys, 24 h paths, dip events, features
  q1 <out dir>                       Question 1: how often a dipped coin comes back (base rates per window) -> q1.json
  q23 <out dir>                      Questions 2 and 3: the computing checker (choose on w3, test on w4/w5) -> q23.json
  cards <out dir> <cards dir>        the committee's case cards (w4/w5 P, D0 information only) and the answer key (kept apart)
  final <out dir> <cards dir>        the committee, the ensembles and the bar -> final.json

The buys are research/mlexit/check_mlexit.py's coin_entries (PR #48) line by line, the path kept for 24 h, with two more roles
(A1, L). Nothing is bought; no network. Needs pandas, pyarrow, numba, lightgbm, scikit-learn."""
import glob, json, math, os, sys, zlib
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mlexit"))
import check_mlexit as M                                      # noqa: E402  features, entries, the v3 / K replays
X = M.X                                                       # check_chartexit: windows, fees, the bootstrap

BAR, MIN, H = X.BAR, X.MIN, X.H
WN = X.WN
NB2 = 288                     # five-minute candles kept after the buy (24 h)
HOURS = X.HOURS               # (1, 2, 3, 6, 12)
SEED = 7
FRAMES = {                    # name: (level, take profit, hours, the hold branch's floor)
    "S20": (0.20, 11.0, 6, 0.50),
    "S30": (0.30, 11.0, 6, 0.50),
    "LP20": (0.20, 2.0, 2, 0.50),
}
DFEATS = M.COIN_F + M.POS_F + M.LAUNCH_F + ["level"]


# --------------------------------------------------------------------------------------------------------- build
def pos_feats(C, Hh, Ll, upto, v60_now, v1, E):
    """The position numbers after path candles 0..upto-1 (upto = 0: at the buy)."""
    if upto > 0:
        hs, ls = Hh[:upto], Ll[:upto]
        hi = max(1.0, float(hs.max()))
        lo = min(1.0, float(ls.min()))
        ret = float(C[upto - 1])
        ih = int(np.nonzero(hs >= hi - 1e-12)[0][-1]) + 1 if hs.max() >= 1.0 else 0
        since_hi = (upto - ih) * 5.0
    else:
        hi = lo = ret = 1.0
        since_hi = 0.0
    return [upto * 5.0, ret, hi, lo, ret / hi, since_hi, math.log1p(v60_now) - math.log1p(v1), E / 60.0]


def first_touch(Ll, Hh, level, tp, nT):
    """The first candle k < nT whose low is at or under 1 - level, with no high at or over tp before it (-1: none)."""
    lv = 1.0 - level
    for k in range(nT):
        if Ll[k] <= lv:
            return k
        if Hh[k] >= tp:
            return -1
    return -1


def coin_entries(c, b):
    """One coin: check_mlexit.coin_entries' entries (P, W1, X, Y) and the new roles A1 and L, with 24 h paths and dip events."""
    mkt, gaps, lf = M.CTX["mkt"], M.CTX["gaps"], M.CTX["launch"]
    t0 = int(c["t"]) // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return [], []
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n)
    has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]; op[j] = b["o"].to_numpy()[keep]
    v[j] = b["v"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cl[~has] = np.nan
    vf = np.where(has, np.nan_to_num(v), 0.0)
    cf = pd.Series(cl).ffill().to_numpy()
    i0 = int(np.argmax(has))
    if not has[i0]:
        return [], []
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
        isA = 30_000 <= mc <= 10_000_000 and liq >= 8_000 and v1 > 0
        isL = 50_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 / mc >= 0.1
        if not (isP or isW or isA or isL):
            continue
        gap24 = False
        if gaps is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((gaps[:, 1] >= a) & (gaps[:, 0] <= z)).any():
                continue
            gap24 = bool(((gaps[:, 1] >= te) & (gaps[:, 0] <= te + 24 * H)).any())
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in HOURS + (24,)}
        if len(cf[jl + 2: jl + 2 + jt[24]]) < jt[24]:
            break
        cands.append(dict(E=E, te=te, jl=jl, p0=p0, v1=v1, mc=mc, liq=liq, v24=v24, r1h=r1h, r6h=r6h, r24h=r24h, gap24=gap24,
                          nb=[int(min(M.NB, jt[t])) for t in HOURS], n24=int(min(NB2, jt[24])),
                          isP=isP, isW=isW, isA=isA, isL=isL))
    if not cands:
        return [], []
    # check_mlexit's draw, line by line (the same random entries)
    firstP = next((x for x in cands if x["isP"]), None)
    Ws = [x for x in cands if x["isW"]]
    firstW = Ws[0] if Ws else None
    rest = [x for x in Ws if x is not firstP]
    rng = np.random.default_rng((M.SEED, zlib.crc32(c["pool"].encode())))
    extra = [rest[i] for i in sorted(rng.choice(len(rest), size=min(M.N_EXTRA, len(rest)), replace=False))] if rest else []
    taken = {x["E"] for x in [firstP, firstW] + extra if x is not None}
    restA = [x for x in cands if x["isA"] and x["E"] not in taken]
    extraA = [restA[i] for i in sorted(rng.choice(len(restA), size=min(M.N_EXTRA, len(restA)), replace=False))] if restA else []
    firstA = next((x for x in cands if x["isA"]), None)
    firstL = next((x for x in cands if x["isL"]), None)
    pick = {}
    for x, role in ([(firstP, "P"), (firstW, "W1")] + [(x, "X") for x in extra] + [(x, "Y") for x in extraA]
                    + [(firstA, "A"), (firstL, "L")]):
        if x is not None:
            pick.setdefault(x["E"], [x, set()])[1].add(role)
    CF = M.coin_features(cf, hi, lo, op, cl, has, vf, p_first, kk, t0, gm, mkt)
    LF = lf.get(c["mint"], np.full(len(M.LAUNCH_F), np.nan, np.float32))
    v60 = M.roll_sum(vf, 12)
    ents, evs = [], []
    for E, (x, roles) in sorted(pick.items()):
        jl, p0 = x["jl"], x["p0"]
        s = slice(jl + 2, jl + 2 + NB2)
        C = cf[s] / p0
        hs = has[s]
        Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
        Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
        O = np.where(hs & np.isfinite(op[s]) & (op[s] > 0), op[s], np.r_[cf[jl + 1], cf[jl + 2: jl + 1 + NB2]]) / p0
        Hh = np.where(Hh <= X.WICK_X * C, Hh, C)
        Ll = np.where(Ll >= C / X.WICK_X, Ll, C)
        O = np.clip(O, Ll, Hh)
        V = v[s] * hs
        nb = np.array(x["nb"], np.int64)
        # the reference replays on the first 150 candles exactly as check_mlexit (K and v3 must match PR #46)
        lab = {key: M.sim(C[:M.NB], Hh[:M.NB], Ll[:M.NB], O[:M.NB], V[:M.NB], nb, x["v1"], M.pvec(P)) for key, P in (("K", M.KR), ("V3", M.V3))}
        eid = "%s:%d" % (c["pool"], E)
        ents.append(dict(eid=eid, pool=c["pool"], mint=c["mint"], w=c["w"], E=E, te=x["te"], gm=gm, roles="".join(sorted(roles)),
                         nb=nb.tolist(), n24=x["n24"], gap24=x["gap24"], v1=float(x["v1"]), mc=x["mc"], liq=x["liq"], v24=x["v24"],
                         r1h=x["r1h"], r6h=x["r6h"], r24h=x["r24h"],
                         K_m=lab["K"][0], K_k=lab["K"][1], V3_m=lab["V3"][0], V3_k=lab["V3"][1], V3_why=lab["V3"][2],
                         C=C.astype(np.float32), H=Hh.astype(np.float32), L=Ll.astype(np.float32), O=O.astype(np.float32),
                         V=V.astype(np.float32),
                         # the card's raw view: 36 closes and volumes before the buy's path start (jl + 1 back), in buy multiples
                         preC=(cf[max(0, jl + 2 - 36): jl + 2] / p0).astype(np.float32), preV=vf[max(0, jl + 2 - 36): jl + 2].astype(np.float32)))
        for fr, (level, tp, hrs, _) in FRAMES.items():
            nT = int(nb[HOURS.index(hrs)])
            k = first_touch(Ll, Hh, level, tp, nT)
            if k < 0:
                continue
            i0d, i1d = jl + 1 + k, jl + 2 + k
            f0 = np.concatenate([CF[i0d], pos_feats(C, Hh, Ll, k, v60[i0d], x["v1"], E), LF, [level]]).astype(np.float32)
            f1 = np.concatenate([CF[i1d], pos_feats(C, Hh, Ll, k + 1, v60[i1d], x["v1"], E), LF, [level]]).astype(np.float32)
            evs.append(dict(eid=eid, frame=fr, k=k, F0=f0, F1=f1))
    return ents, evs


def _work(args):
    path, k, n, dest = args
    b = pd.read_parquet(path)
    if n > 1:
        pools = np.sort(b["pool"].unique())[k::n]
        b = b[b["pool"].isin(pools)]
    ents, evs = [], []
    for pool, g in b.groupby("pool", sort=False):
        c = M.CTX["meta"].get(pool)
        if c is None:
            continue
        e, ev = coin_entries(c, g.sort_values("t"))
        ents += e
        evs += ev
    if not ents:
        return dest, 0, 0
    arr = {q: np.stack([r[q] for r in ents]) for q in ("C", "H", "L", "O", "V")}
    pre = np.full((len(ents), 36), np.nan, np.float32)
    prev = np.full((len(ents), 36), np.nan, np.float32)
    for i, r in enumerate(ents):
        pre[i, 36 - len(r["preC"]):] = r["preC"]
        prev[i, 36 - len(r["preV"]):] = r["preV"]
    meta = pd.DataFrame([{q: r[q] for q in r if q not in ("C", "H", "L", "O", "V", "preC", "preV")} for r in ents])
    ev = pd.DataFrame([{q: r[q] for q in ("eid", "frame", "k")} for r in evs])
    F0 = np.stack([r["F0"] for r in evs]) if evs else np.zeros((0, len(DFEATS)), np.float32)
    F1 = np.stack([r["F1"] for r in evs]) if evs else np.zeros((0, len(DFEATS)), np.float32)
    np.savez(dest, preC=pre, preV=prev, F0=F0, F1=F1, **arr)
    meta.to_parquet(dest.replace(".npz", "_e.parquet"))
    ev.to_parquet(dest.replace(".npz", "_d.parquet"))
    return dest, len(ents), len(evs)


def cmd_build(md, h2, gapf, chainf, out):
    import multiprocessing as mp
    os.makedirs(os.path.join(out, "shards"), exist_ok=True)
    s = np.array(json.load(open(os.path.join(md, "market.json")))["SOLUSDT"], dtype=float)
    X.SOL = (s[:, 0], s[:, 1])
    g = np.sort(np.load(gapf))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    M.CTX["gaps"] = np.c_[st[big], en[big]]
    M.CTX["mkt"] = M.Market(os.path.join(md, "market.json"))
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
    M.CTX["meta"] = meta
    M.CTX["launch"] = M.launch_facts(allm, pd.read_parquet(chainf))
    print("coins in windows", len(meta), "launch facts", len(M.CTX["launch"]), flush=True)
    jobs = [(f, 0, 1, os.path.join(out, "shards", "h2_" + os.path.basename(f).replace(".parquet", ".npz")))
            for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    jobs += [(f, k, 6, os.path.join(out, "shards", "gt_%s_%d.npz" % (os.path.basename(f)[5:7], k)))
             for f in sorted(glob.glob(os.path.join(md, "bars_w*.parquet"))) for k in range(6)]
    te = tv = 0
    with mp.get_context("fork").Pool(3) as pool:
        for dest, ne, nv in pool.imap_unordered(_work, jobs, chunksize=1):
            te += ne; tv += nv
            print(os.path.basename(dest), ne, nv, "total", te, tv, flush=True)


# --------------------------------------------------------------------------------------------------------- load
def load(out):
    """Every shard -> buys (one row each, 24 h paths) and dip events (features D0 / D1); a pool in two sources counts once (the
    source with the earlier P buy; without one, the earlier buy), as check_mlexit.load."""
    metas, A, evs = [], {q: [] for q in ("C", "H", "L", "O", "V", "preC", "preV")}, []
    F0s, F1s = [], []
    for f in sorted(glob.glob(os.path.join(out, "shards", "*.npz"))):
        m = pd.read_parquet(f.replace(".npz", "_e.parquet"))
        d = pd.read_parquet(f.replace(".npz", "_d.parquet"))
        z = np.load(f)
        m["shard"] = len(metas)
        d["shard"] = len(metas)
        m["row"] = np.arange(len(m))
        d["frow"] = np.arange(len(d))
        metas.append(m); evs.append(d)
        for q in A:
            A[q].append(z[q])
        F0s.append(z["F0"]); F1s.append(z["F1"])
    Mt = pd.concat(metas, ignore_index=True)
    hasP = Mt["roles"].str.contains("P")
    fp = Mt[hasP].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    fo = Mt[~Mt["pool"].isin(fp["pool"])].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    Mt = Mt.merge(pd.concat([fp, fo]).rename(columns={"shard": "keep"}), on="pool")
    Mt = Mt[Mt["shard"] == Mt["keep"]].drop(columns="keep")
    Mt = Mt.sort_values(["te", "pool", "E"]).reset_index(drop=True)
    P = {q: np.stack([A[q][s][r] for s, r in zip(Mt["shard"], Mt["row"])]).astype(np.float64) for q in A}
    D = pd.concat(evs, ignore_index=True)
    ix = pd.Series(np.arange(len(Mt)), index=Mt["eid"] + "|" + Mt["shard"].astype(str))
    key = D["eid"] + "|" + D["shard"].astype(str)
    D = D[key.isin(ix.index)].copy()
    D["e"] = ix[key[key.isin(ix.index)]].to_numpy()
    D = D.reset_index(drop=True)
    F0 = np.concatenate([F0s[s][r][None] for s, r in zip(D["shard"], D["frow"])]) if len(D) else None
    F1 = np.concatenate([F1s[s][r][None] for s, r in zip(D["shard"], D["frow"])]) if len(D) else None
    return Mt, P, D, F0.astype(np.float32), F1.astype(np.float32)


# --------------------------------------------------------------------------------------------------------- the rules
def _kern():
    import numba

    @numba.njit(parallel=True, cache=False)
    def run(C, Hh, L, O, start, nT, lvl, tp, level_fill, out):
        """From candle start[i] on: out at lvl (the candle's low, or the level unless it opened under it), at tp, else the close
        of candle nT[i] - 1. The stop is checked before the take profit in a candle, as check_chartexit."""
        for i in numba.prange(C.shape[0]):
            res = C[i, nT[i] - 1]
            for k in range(start[i], nT[i]):
                if L[i, k] <= lvl:
                    res = min(O[i, k], lvl) if level_fill else L[i, k]
                    break
                if Hh[i, k] >= tp:
                    res = tp
                    break
            out[i] = res
    return run


_RUN = None


def run_rule(P, rows, start, nT, lvl, tp, level_fill=False):
    global _RUN
    if _RUN is None:
        _RUN = _kern()
    out = np.zeros(len(rows))
    _RUN(P["C"][rows], P["H"][rows], P["L"][rows], P["O"][rows], np.asarray(start, np.int64), np.asarray(nT, np.int64),
         float(lvl), float(tp), bool(level_fill), out)
    return out


def money(m):
    return X.to_money(np.asarray(m, float))


def boot_p(d, draws=20000, seed=SEED):
    """One-sided bootstrap: (5 % lower bound, 95 % interval, share of re-draw means at or under 0) as check_chartexit.boot."""
    d = np.asarray(d, float)
    rng = np.random.default_rng(seed)
    m = np.empty(draws)
    for k in range(0, draws, 2000):
        m[k:k + 2000] = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    return float(np.quantile(m, 0.05)), [float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))], float((m <= 0).mean())


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 2), round(100 * (c + h), 2)]


class Frame:
    """One frame's outcomes per buy: the plain stop (S), the always-hold branch from the touch (Hd), the touch candle k (-1: none),
    both fills; D1's sell at the touch candle's close."""

    def __init__(self, Mt, P, D, fr):
        level, tp, hrs, floor = FRAMES[fr]
        self.fr, self.level, self.tp = fr, level, tp
        n = len(Mt)
        nb = np.stack(Mt["nb"].to_numpy())
        self.nT = nb[:, HOURS.index(hrs)].astype(np.int64)
        d = D[D["frame"] == fr]
        self.k = np.full(n, -1, np.int64)
        self.k[d["e"].to_numpy()] = d["k"].to_numpy()
        self.ev = np.full(n, -1, np.int64)                   # the row in D
        self.ev[d["e"].to_numpy()] = d.index.to_numpy()
        rows = np.arange(n)
        z = np.zeros(n, np.int64)
        has = self.k >= 0
        ks = np.where(has, self.k, 0)
        for fill in (False, True):
            S = run_rule(P, rows, z, self.nT, 1.0 - level, tp, fill)
            Hd = run_rule(P, rows, ks, self.nT, 1.0 - floor, tp, fill)
            Hd = np.where(has, Hd, S)                         # no touch: the same as the plain stop
            if fill:
                self.S_lv, self.H_lv = S, Hd
            else:
                self.S, self.H = S, Hd
        # D1: at the touch candle's close (unless the floor took it in that candle)
        Lk = P["L"][rows, ks]
        Ck = P["C"][rows, ks]
        self.S_c = np.where(has, np.where(Lk <= 1.0 - floor, Lk, Ck), self.S)
        self.has = has

    def rule(self, hold, fill="low", d1=False):
        """The checker's rule: hold (bool per buy, only read where a touch happened) -> mult per buy"""
        if fill == "level":
            S, Hd = self.S_lv, self.H_lv
        else:
            S, Hd = (self.S_c if d1 else self.S), self.H
        return np.where(self.has & hold, Hd, S)


# --------------------------------------------------------------------------------------------------------- Question 1
def after_touch(P, Mt, k, upto=None):
    """Per buy with a touch at k: the highest high after the touch candle and the lowest low from it, up to 24 h (or upto)."""
    n24 = Mt["n24"].to_numpy() if upto is None else upto
    mx = np.full(len(k), np.nan)
    mn = np.full(len(k), np.nan)
    for i in np.nonzero(k >= 0)[0]:
        a, z = k[i], int(n24[i])
        mx[i] = P["H"][i, a + 1:z].max() if z > a + 1 else P["C"][i, a]
        mn[i] = P["L"][i, a:z].min()
    return mx, mn


def role_rows(Mt, role, w=None):
    s = Mt["roles"].str.contains(role).to_numpy().copy()
    if w is not None:
        s &= np.isin(Mt["w"].to_numpy(), w if isinstance(w, (list, tuple)) else [w])
    return s


def cmd_q1(out):
    Mt, P, D, _, _ = load(out)
    res = {"buys": {}, "rates": {}}
    ok24 = ~Mt["gap24"].to_numpy().astype(bool)
    n24 = Mt["n24"].to_numpy()
    allmx = np.array([P["H"][i, :n24[i]].max() for i in range(len(Mt))])
    allmn = np.array([P["L"][i, :n24[i]].min() for i in range(len(Mt))])
    nT6 = np.stack(Mt["nb"].to_numpy())[:, HOURS.index(6)]
    for fr in ("S20", "S30"):
        F = Frame(Mt, P, D, fr)
        mx, mn = after_touch(P, Mt, F.k)
        mx6, _ = after_touch(P, Mt, F.k, nT6)
        for role in ("P", "A", "L"):
            for w in WN + ["w1-w3", "w4-w5", "all"]:
                ws = {"w1-w3": ["w1", "w2", "w3"], "w4-w5": ["w4", "w5"], "all": WN}.get(w, [w])
                base = role_rows(Mt, role, ws) & ok24
                t = base & F.has
                nb_, nt = int(base.sum()), int(t.sum())
                r = {"buys": nb_, "touched": nt, "touchedPct": round(100 * nt / max(nb_, 1), 1)}
                for lab, cond in (("back1x", mx >= 1.0), ("x2", mx >= 2.0), ("x5", mx >= 5.0), ("x10", mx >= 10.0),
                                  ("x2in6h", mx6 >= 2.0), ("x5in6h", mx6 >= 5.0), ("x10in6h", mx6 >= 10.0), ("zero", mn <= 0.1)):
                    kk = int((t & cond).sum())
                    r[lab] = {"n": kk, "pct": round(100 * kk / max(nt, 1), 2), "ci": wilson(kk, nt)}
                for lab, cond in (("x2", allmx >= 2.0), ("x5", allmx >= 5.0), ("x10", allmx >= 10.0), ("zero", allmn <= 0.1)):
                    kk = int((base & cond).sum())
                    r["all_" + lab] = {"n": kk, "pct": round(100 * kk / max(nb_, 1), 2), "ci": wilson(kk, nb_)}
                if fr == "S20":
                    r["launchLikePer1000"] = round(1000 * int((t & (mx >= 10.0)).sum()) / max(nb_, 1), 2)
                res["rates"].setdefault(fr, {}).setdefault(role, {})[w] = r
    for role in ("P", "A", "L", "W1", "X", "Y"):
        res["buys"][role] = {w: int(role_rows(Mt, role, w).sum()) for w in WN}
    res["gap24_left_out"] = {w: int((~ok24 & (Mt["w"] == w).to_numpy()).sum()) for w in WN}
    # the check against PR #46 (research/chartexit/result.json): P buys and K / v3 per window
    ref = json.load(open(os.path.join(HERE, "..", "chartexit", "result.json")))
    res["check"] = {w: {"n": int(role_rows(Mt, "P", w).sum()), "ref_n": ref["coins"][w],
                        "K": round(float(money(Mt["K_m"].to_numpy()[role_rows(Mt, "P", w)]).mean()), 2), "ref_K": ref["low"]["K"][w],
                        "V3": round(float(money(Mt["V3_m"].to_numpy()[role_rows(Mt, "P", w)]).mean()), 2),
                        "ref_V3": ref["low"]["live"]["byWindow"][w]["mean"]} for w in WN}
    F30 = Frame(Mt, P, D, "S30")
    res["check_S30_vs_K"] = int((np.abs(F30.S - Mt["K_m"].to_numpy()) > 1e-6).sum())
    json.dump(res, open(os.path.join(out, "q1.json"), "w"), indent=1)
    print(json.dumps(res["check"], indent=0), "S30 vs K mismatches", res["check_S30_vs_K"])
    for fr in ("S20", "S30"):
        for role in ("P", "A", "L"):
            r = res["rates"][fr][role]["all"]
            print(fr, role, r["buys"], r["touched"], r["touchedPct"], {q: r[q]["pct"] for q in ("back1x", "x2", "x5", "x10", "x2in6h", "zero")},
                  {q: r["all_" + q]["pct"] for q in ("x2", "x5", "x10", "zero")})


# --------------------------------------------------------------------------------------------------------- Questions 2 and 3
LGB = dict(learning_rate=0.05, num_leaves=31, min_data_in_leaf=200, feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1,
           lambda_l2=10.0, seed=SEED, num_threads=3, verbose=-1)
CANDS = [("V", m) for m in (0.0, 0.03, 0.06, 0.10)] + [(f, q) for f in ("C2", "C1") for q in (5, 10, 20, 40)]
ORDER = {"V": 0, "C2": 1, "C1": 2}


def fit(F, y, gt, objective):
    import lightgbm as lgb
    cut = np.quantile(np.unique(gt), 0.85)
    va = gt >= cut
    p = dict(LGB, objective=objective)
    if objective == "binary":
        p["metric"] = "binary_logloss"
    dtr = lgb.Dataset(F[~va], y[~va], free_raw_data=True)
    dva = lgb.Dataset(F[va], y[va], reference=dtr, free_raw_data=True)
    return lgb.train(p, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])


def pred(b, F):
    return b.predict(F, num_iteration=b.best_iteration).astype(np.float64)


class Events:
    """One frame's dip events with their labels (rows of D)."""

    def __init__(self, Mt, P, D, F0, F1, fr, d1=False):
        self.Fr = Frame(Mt, P, D, fr)
        d = D[D["frame"] == fr]
        self.row = d.index.to_numpy()
        self.e = d["e"].to_numpy()
        self.F = (F1 if d1 else F0)[self.row]
        Sx = self.Fr.S_c if d1 else self.Fr.S
        self.yV = self.Fr.H[self.e] - Sx[self.e]
        mx, mn = after_touch(P, Mt, self.Fr.k)
        self.mx, self.mn = mx[self.e], mn[self.e]
        self.ok24 = ~Mt["gap24"].to_numpy().astype(bool)[self.e]
        self.w = Mt["w"].to_numpy()[self.e]
        self.gm = Mt["gm"].to_numpy()[self.e]
        self.pool = Mt["pool"].to_numpy()[self.e]
        self.k = self.Fr.k[self.e]
        self.d1 = d1

    def lab(self, name):
        return {"C2": self.mx >= 2.0, "C1": self.mx >= 1.0, "Z": self.mn <= 0.1}[name].astype(float)

    def sel(self, ws):
        return np.isin(self.w, ws)


def fit_all(ev, tr, shuffle=False):
    """The checker's models on the training events tr (bool): V, C2, C1 (Z as a diagnostic), and the C thresholds."""
    out = {}
    y = ev.yV[tr]
    if shuffle:                                             # the placebo: labels shuffled among events with the same k
        rng = np.random.default_rng(SEED)
        kk = ev.k[tr]
        idx = np.arange(tr.sum())
        perm = idx.copy()
        for kv in np.unique(kk):
            s_ = idx[kk == kv]
            perm[s_] = rng.permutation(s_)
    out["V"] = fit(ev.F[tr], y if not shuffle else y[perm], ev.gm[tr], "regression")
    for name in ("C2", "C1", "Z"):
        t2 = tr & ev.ok24
        yy = ev.lab(name)[t2]
        if shuffle:
            rng = np.random.default_rng(SEED + 1)
            kk = ev.k[t2]
            for kv in np.unique(kk):
                s_ = np.nonzero(kk == kv)[0]
                yy[s_] = yy[rng.permutation(s_)]
        out[name] = fit(ev.F[t2], yy, ev.gm[t2], "binary")
    thr = {}
    for name in ("C2", "C1"):
        p_in = pred(out[name], ev.F[tr])
        for q in (5, 10, 20, 40):
            thr[(name, q)] = float(np.quantile(p_in, 1 - q / 100))
    out["thr"] = thr
    return out


def decide(models, cand, F):
    fam, x = cand
    p = pred(models[fam], F)
    return p > x if fam == "V" else p >= models["thr"][(fam, x)]


def hold_vector(ev, n, models, cand, rows_ev):
    """hold per buy (n buys) from the events rows_ev (bool over ev)"""
    h = np.zeros(n, bool)
    h[ev.e[rows_ev]] = decide(models, cand, ev.F[rows_ev])
    return h


def judge(diff):
    lo5, ci, p = boot_p(diff)
    return {"n": int(len(diff)), "diff": round(float(np.mean(diff)), 3), "lo5": round(lo5, 3), "ci95": [round(ci[0], 3), round(ci[1], 3)],
            "p": round(p, 5)}


def report(Mt, P, ev, rows, hold, mx6=None):
    """rows: buys (bool); hold: per buy. Money per 50-EUR trade of S, always-hold, V3 and the checker; the paired differences."""
    Fr = ev.Fr
    S = Fr.S_c if ev.d1 else Fr.S
    mS, mH, mV3 = money(S[rows]), money(Fr.H[rows]), money(Mt["V3_m"].to_numpy()[rows])
    c = Fr.rule(hold, d1=ev.d1)
    mC = money(c[rows])
    c_lv = Fr.rule(hold, fill="level")
    t = Fr.has[rows]
    h = hold[rows] & t
    out = {"buys": int(rows.sum()), "touched": int(t.sum()), "held": int(h.sum()),
           "mean": {"S": round(float(mS.mean()), 2), "alwaysHold": round(float(mH.mean()), 2), "V3": round(float(mV3.mean()), 2),
                    "checker": round(float(mC.mean()), 2)},
           "vsS": judge(mC - mS), "vsV3": judge(mC - mV3), "alwaysHoldVsS": judge(mH - mS),
           "vsS_level": judge(money(c_lv[rows]) - money(Fr.S_lv[rows])),
           "inProfit": round(100 * float((mC > 0).mean()), 1)}
    hb = Fr.H[rows]
    out["heldEnded"] = {"x2+": int((h & (hb >= 2)).sum()), "x5+": int((h & (hb >= 5)).sum()), "lost40+": int((h & (money(hb) <= -40)).sum()),
                        "meanHeldGain": round(float((money(hb) - mS)[h].mean()), 2) if h.any() else None}
    out["missed"] = {"x2+": int((t & ~hold[rows] & (hb >= 2)).sum()), "x5+": int((t & ~hold[rows] & (hb >= 5)).sum())}
    return out


def auc_ci(y, p, groups, draws=2000):
    from sklearn.metrics import roc_auc_score
    if y.min() == y.max():
        return None
    a = roc_auc_score(y, p)
    ug, gi = np.unique(groups, return_inverse=True)
    rng = np.random.default_rng(SEED)
    bs = []
    members = [np.nonzero(gi == g)[0] for g in range(len(ug))]
    for _ in range(draws):
        pick = rng.integers(0, len(ug), len(ug))
        ix = np.concatenate([members[g] for g in pick])
        if y[ix].min() != y[ix].max():
            bs.append(roc_auc_score(y[ix], p[ix]))
    return {"auc": round(float(a), 4), "ci95": [round(float(np.quantile(bs, 0.025)), 4), round(float(np.quantile(bs, 0.975)), 4)],
            "n": int(len(y)), "pos": int(y.sum())}


def diag(ev, models, te, Mt):
    from scipy.stats import spearmanr
    out = {}
    for name in ("C1", "C2", "Z"):
        t2 = te & ev.ok24
        y = ev.lab(name)[t2]
        p = pred(models[name], ev.F[t2])
        r = auc_ci(y, p, ev.pool[t2])
        if r is not None:
            top = p >= np.quantile(p, 0.9)
            r["base"] = round(100 * float(y.mean()), 2)
            r["top10"] = round(100 * float(y[top].mean()), 2)
        out[name] = r
    y = ev.yV[te]
    p = pred(models["V"], ev.F[te])
    q = pd.qcut(p, 10, labels=False, duplicates="drop")
    dec = pd.DataFrame({"q": q, "p": p, "y": y}).groupby("q").agg(pred=("p", "mean"), real=("y", "mean"), n=("y", "size"))
    out["V"] = {"events": int(len(y)), "R2": round(float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 4),
                "spearman": round(float(spearmanr(p, y).statistic), 4), "realMean": round(float(y.mean()), 4),
                "deciles": [{k2: (round(float(v), 4) if k2 != "n" else int(v)) for k2, v in r.items()} for r in dec.to_dict("records")]}
    return out


TESTS = [("w4", "P"), ("w5", "P"), ("w4", "L"), ("w5", "L"), ("w4", "A"), ("w5", "A"), ("w4", "W1"), ("w5", "W1")]


def run_frame(Mt, P, D, F0, F1, fr, d1=False, log=print):
    ev = Events(Mt, P, D, F0, F1, fr, d1)
    n = len(Mt)
    res = {"frame": fr, "decision": "D1" if d1 else "D0", "events": {w: int((ev.w == w).sum()) for w in WN}}
    # choice: fitted on w1+w2, judged on w3's P, W1, A1 and L buys (each once)
    tr = ev.sel(["w1", "w2"])
    models = fit_all(ev, tr)
    w3 = (Mt["w"].to_numpy() == "w3") & Mt["roles"].str.contains("P|W1|A|L").to_numpy()
    S = ev.Fr.S_c if d1 else ev.Fr.S
    rows_ev = ev.sel(["w3"])
    ch = []
    for cand in CANDS:
        hold = hold_vector(ev, n, models, cand, rows_ev)
        d = money(ev.Fr.rule(hold, d1=d1)[w3]) - money(S[w3])
        ch.append({"family": cand[0], "x": cand[1], "diff": round(float(d.mean()), 4), "held": int((hold & w3 & ev.Fr.has).sum())})
    res["choose_w3"] = {"buys": int(w3.sum()), "touched": int((w3 & ev.Fr.has).sum()), "candidates": ch,
                        "alwaysHold": round(float((money(ev.Fr.H[w3]) - money(S[w3])).mean()), 4)}
    best = max(ch, key=lambda r: (round(r["diff"], 6), -ORDER[r["family"]], r["x"] if r["family"] == "V" else -r["x"]))
    cand = (best["family"], best["x"])
    res["chosen"] = best
    log(fr, "D1" if d1 else "D0", "chosen", best)
    # test: fitted on w1-w3, judged on w4 / w5
    tr = ev.sel(["w1", "w2", "w3"])
    models = fit_all(ev, tr)
    res["trees"] = {k2: int(v.best_iteration) for k2, v in models.items() if k2 != "thr"}
    hold_all = hold_vector(ev, n, models, cand, ev.sel(["w4", "w5"]))
    res["test"] = {}
    for w, role in TESTS:
        rows = role_rows(Mt, role, w)
        res["test"]["%s_%s" % (w, role)] = report(Mt, P, ev, rows, hold_all)
        r = res["test"]["%s_%s" % (w, role)]
        log(fr, w, role, r["buys"], r["touched"], r["held"], r["mean"], "vsS", r["vsS"]["diff"], r["vsS"]["lo5"], "vsV3", r["vsV3"]["diff"])
    res["diag_w4_all"] = diag(ev, models, ev.sel(["w4"]), Mt)
    pe = np.isin(ev.e, np.nonzero(role_rows(Mt, "P", "w4"))[0])
    res["diag_w4_P"] = diag(ev, models, pe, Mt)
    # walk-forward w1-w4 -> w5
    m4 = fit_all(ev, ev.sel(["w1", "w2", "w3", "w4"]))
    h5 = hold_vector(ev, n, m4, cand, ev.sel(["w5"]))
    res["walk_w5_P"] = report(Mt, P, ev, role_rows(Mt, "P", "w5"), h5)
    # the placebo: shuffled labels, the same candidate
    mp_ = fit_all(ev, tr, shuffle=True)
    hp = hold_vector(ev, n, mp_, cand, ev.sel(["w4", "w5"]))
    res["placebo"] = {"w4_P": report(Mt, P, ev, role_rows(Mt, "P", "w4"), hp), "diag_w4_all": diag(ev, mp_, ev.sel(["w4"]), Mt)}
    imp = pd.Series(models["V"].feature_importance("gain"), index=DFEATS).sort_values(ascending=False)
    res["top_features_V"] = {k3: round(float(v / max(imp.sum(), 1e-12)), 4) for k3, v in imp.head(12).items()}
    imp = pd.Series(models["C2"].feature_importance("gain"), index=DFEATS).sort_values(ascending=False)
    res["top_features_C2"] = {k3: round(float(v / max(imp.sum(), 1e-12)), 4) for k3, v in imp.head(12).items()}
    return res, hold_all, ev


def cmd_q23(out):
    Mt, P, D, F0, F1 = load(out)
    res = {}
    keep = {}
    for fr, d1 in (("S20", False), ("S30", False), ("LP20", False), ("S20", True)):
        tag = fr + ("_D1" if d1 else "")
        r, hold, ev = run_frame(Mt, P, D, F0, F1, fr, d1, log=lambda *a: print(tag, *a, flush=True))
        res[tag] = r
        if tag == "S20":
            keep = hold
            # exploratory: always hold up to 24 h (floor -50 %, 11x)
            Fr = ev.Fr
            n24 = Mt["n24"].to_numpy()
            rows = np.arange(len(Mt))
            H24 = run_rule(P, rows, np.where(Fr.has, Fr.k, 0), n24, 0.5, 11.0)
            res["S20"]["alwaysHold24h"] = {"%s_%s" % (w, role): judge(money(np.where(Fr.has, H24, Fr.S)[role_rows(Mt, role, w)])
                                                                  - money(Fr.S[role_rows(Mt, role, w)])) for w, role in TESTS[:4]}
        json.dump(res, open(os.path.join(out, "q23.json"), "w"), indent=1, default=float)
    pd.DataFrame({"eid": Mt["eid"], "hold": keep}).to_parquet(os.path.join(out, "hold_S20.parquet"))


# --------------------------------------------------------------------------------------------------------- the committee
def fnum(x, nd=0):
    return "?" if x is None or not np.isfinite(x) else ("%%.%df" % nd) % x


def card(cid, r, Pp, i, k, f):
    """One case card with D0 information only (nothing of the touch candle or later); no name, address, date or clock time."""
    g = dict(zip(DFEATS, f))
    seqC = np.r_[Pp["preC"][i], Pp["C"][i, :k]]
    seqV = np.r_[Pp["preV"][i], Pp["V"][i, :k]]
    buy_at = len(Pp["preC"][i]) - 1                        # the candle in which the buy happened
    seqC, seqV = seqC[-36:], seqV[-36:]
    buy_pos = buy_at - (len(np.r_[Pp["preC"][i], Pp["C"][i, :k]]) - 36)
    now = seqC[-1]
    hi_s = max(1.0, float(Pp["H"][i, :k].max())) if k else 1.0
    lo_s = min(1.0, float(Pp["L"][i, :k].min())) if k else 1.0
    hi_s, lo_s = max(hi_s, float(now)), min(lo_s, float(now))   # the close of the candle in which the buy happened is known too
    closes = " ".join("?" if not np.isfinite(c) else "%d" % round(100 * c) for c in seqC)
    vols = " ".join("?" if not np.isfinite(v) else "%.1f" % (v / 1e3) for v in seqV)
    def link(x):
        return "unknown" if not np.isfinite(x) else ("yes" if x > 0 else "no")
    curve = math.expm1(g["l_curve"]) if np.isfinite(g["l_curve"]) else float("nan")
    lines = [
        "=== CASE %s ===" % cid,
        "Coin age at the buy: %d h after it left the bonding curve. The price touched -20%% about %d-%d min after the buy." % (r["E"] // 60, 5 * k, 5 * k + 10),
        "At the buy: market cap $%sk, liquidity $%sk, volume last 24 h $%sk, last 1 h $%sk; price change before the buy: 1 h %s%%, 6 h %s%%, 24 h %s%%."
        % (fnum(r["mc"] / 1e3), fnum(r["liq"] / 1e3), fnum(r["v24"] / 1e3), fnum(r["v1"] / 1e3), fnum(100 * r["r1h"]), fnum(100 * r["r6h"]), fnum(100 * r["r24h"])),
        "Since the buy (before the touch): highest %d%%, lowest %d%%, last close %d%% of the buy price." % (round(100 * hi_s), round(100 * lo_s), round(100 * now)),
        "Last %d five-minute closes in %% of the buy price, oldest first (the buy happened in candle #%d): %s" % (len(seqC), buy_pos + 1, closes),
        "Their volumes in thousand USD: %s" % vols,
        "Five-minute candles without any trade in the last hour: %d of 12. Price now vs the highest since graduation: %d%%; vs the lowest since graduation: %d%%."
        % (round(12 * g["nt12"]), round(100 * g["ath"]), round(100 * g["atl"])),
        "Market: SOL %s%% (1 h), %s%% (24 h); BTC %s%% (24 h)." % (fnum(100 * g["sol1h"], 1), fnum(100 * g["sol24h"], 1), fnum(100 * g["btc24h"], 1)),
        "Launch: X link %s, Telegram %s, website %s, video %s, description %s characters, creator's graduations in the 30 days before: %s, time on the bonding curve: %s min."
        % (link(g["l_x"]), link(g["l_tg"]), link(g["l_web"]), link(g["l_video"]), fnum(g["l_desc"]), fnum(g["l_prev30"]), fnum(curve)),
        "Hours left until the forced sale at 6 h after the buy: about %.1f." % max(0.0, 6 - (5 * k) / 60),
        "",
    ]
    return "\n".join(lines)


def cmd_cards(out, cdir):
    Mt, P, D, F0, F1 = load(out)
    os.makedirs(cdir, exist_ok=True)
    Fr = Frame(Mt, P, D, "S20")
    rows = np.nonzero(Fr.has & (role_rows(Mt, "P", "w4") | role_rows(Mt, "P", "w5")))[0]
    rng = np.random.default_rng(SEED)
    if len(rows) > 400:
        rows = np.sort(rng.choice(rows, 400, replace=False))
    order = rng.permutation(len(rows))
    rows = rows[order]
    ids = ["%04d" % x for x in rng.choice(10000, len(rows), replace=False)]
    key = []
    texts = []
    for cid, i in zip(ids, rows):
        r = Mt.iloc[i]
        e = int(Fr.ev[i])
        texts.append(card(cid, r, P, i, int(Fr.k[i]), F0[e]))
        key.append({"id": cid, "eid": r["eid"], "w": r["w"], "k": int(Fr.k[i]), "sell": float(Fr.S[i]), "hold": float(Fr.H[i]),
                    "sell_lv": float(Fr.S_lv[i]), "hold_lv": float(Fr.H_lv[i])})
    parts = np.array_split(np.arange(len(texts)), 3)
    for q, ix in enumerate(parts):
        open(os.path.join(cdir, "cases_part%d.txt" % (q + 1)), "w").write("\n".join(texts[j] for j in ix))
    pd.DataFrame(key).to_parquet(os.path.join(out, "committee_key.parquet"))
    # the base rates of the training windows (w1-w3, Pick-type buys) for the reviewers
    tr = role_rows(Mt, "P", ["w1", "w2", "w3"]) & Fr.has
    ok = tr & ~Mt["gap24"].to_numpy().astype(bool)
    mx, mn = after_touch(P, Mt, Fr.k)
    nT6 = np.stack(Mt["nb"].to_numpy())[:, HOURS.index(6)]
    mx6, _ = after_touch(P, Mt, Fr.k, nT6)
    dm = money(Fr.H[tr]) - money(Fr.S[tr])
    base = {"touched": int(tr.sum()), "back1x_24h": round(100 * float((mx[ok] >= 1).mean()), 1), "x2_6h": round(100 * float((mx6[tr] >= 2).mean()), 1),
            "x2_24h": round(100 * float((mx[ok] >= 2).mean()), 1), "x10_24h": round(100 * float((mx[ok] >= 10).mean()), 1),
            "zero_24h": round(100 * float((mn[ok] <= 0.1).mean()), 1), "holdMinusSellEUR": round(float(dm.mean()), 2),
            "holdBetterPct": round(100 * float((dm > 0).mean()), 1), "sellMeanEUR": round(float(money(Fr.S[tr]).mean()), 2),
            "holdMeanEUR": round(float(money(Fr.H[tr]).mean()), 2)}
    json.dump(base, open(os.path.join(cdir, "base_rates_w1_w3.json"), "w"), indent=1)
    print(len(rows), "cases", {w: int((Mt["w"].to_numpy()[rows] == w).sum()) for w in ("w4", "w5")}, base)


REVIEWERS = {"A": "chart reader", "B": "flow reader", "C": "sceptic"}


def read_answers(cdir, rnd):
    """The reviewers' answers of a round -> {reviewer: DataFrame(id, p, vote, why)}"""
    out = {}
    for r in REVIEWERS:
        rows = []
        for f in sorted(glob.glob(os.path.join(cdir, "..", "committee", "%s_%s_part*.json" % (rnd, r)))):
            rows += json.load(open(f))
        if rows:
            d = pd.DataFrame(rows)
            d["id"] = d["id"].astype(str).str.zfill(4)
            d["vote"] = d["vote"].str.upper().str.strip()
            out[r] = d.drop_duplicates("id").set_index("id")
    return out


def cmd_debate(out, cdir):
    """Round 2's input: per reviewer, the other two's round-1 votes and reasons on every case (and its own)."""
    r1 = read_answers(cdir, "r1")
    key = pd.read_parquet(os.path.join(out, "committee_key.parquet"))
    for me in REVIEWERS:
        lines = []
        for cid in key["id"]:
            bits = []
            for r in REVIEWERS:
                a = r1[r].loc[cid]
                who = "YOU (round 1)" if r == me else "%s (%s)" % (r, REVIEWERS[r])
                bits.append("%s: %s p=%.2f, \"%s\"" % (who, a["vote"], float(a["p"]), a["why"]))
            lines.append("CASE %s | " % cid + " | ".join(bits))
        open(os.path.join(cdir, "..", "committee", "debate_for_%s.txt" % me), "w").write("\n".join(lines) + "\n")
    print({r: {"answers": len(d), "hold": int((d["vote"] == "HOLD").sum())} for r, d in r1.items()})


def cmd_final(out, cdir):
    """The committee, the ensembles and the bar (Holm over the four checkers on the w4 P buys)."""
    Mt, P, D, F0, F1 = load(out)
    Fr = Frame(Mt, P, D, "S20")
    key = pd.read_parquet(os.path.join(out, "committee_key.parquet"))
    comp = pd.read_parquet(os.path.join(out, "hold_S20.parquet")).set_index("eid")["hold"]
    eix = pd.Series(np.arange(len(Mt)), index=Mt["eid"])
    r1, r2 = read_answers(cdir, "r1"), read_answers(cdir, "r2")
    res = {"cases": int(len(key)), "answers": {}}
    votes = {}
    for rnd, ans in (("r1", r1), ("r2", r2)):
        V = pd.DataFrame({r: (ans[r].reindex(key["id"])["vote"] == "HOLD").to_numpy() for r in REVIEWERS}, index=key["id"])
        Pp = pd.DataFrame({r: pd.to_numeric(ans[r].reindex(key["id"])["p"], errors="coerce").to_numpy() for r in REVIEWERS}, index=key["id"])
        votes[rnd] = (V, Pp)
        res["answers"][rnd] = {r: {"missing": int(ans[r].reindex(key["id"])["vote"].isna().sum()), "hold": int(V[r].sum())} for r in REVIEWERS}
    n = len(Mt)
    rows_c = eix[key["eid"]].to_numpy()

    def per_buy(x):
        h = np.zeros(n, bool)
        h[rows_c] = x
        return h

    V2, P2 = votes["r2"]
    V1, _ = votes["r1"]
    hc = comp.reindex(Mt["eid"]).fillna(False).to_numpy().astype(bool)
    committee = per_buy((V2.sum(1) >= 2).to_numpy())
    checkers = {"computing": hc, "committee": committee, "AND": hc & committee, "OR": hc | committee}
    extra = {"committee_unanimous": per_buy((V2.sum(1) == 3).to_numpy()), "committee_round1": per_buy((V1.sum(1) >= 2).to_numpy())}
    for r in REVIEWERS:
        extra["reviewer_" + r] = per_buy(V2[r].to_numpy())
    res["test"] = {}
    for name, h in list(checkers.items()) + list(extra.items()):
        res["test"][name] = {}
        for w in ("w4", "w5"):
            rows = role_rows(Mt, "P", w)
            S, mV3 = money(Fr.S[rows]), money(Mt["V3_m"].to_numpy()[rows])
            c = money(Fr.rule(h)[rows])
            c_lv = money(Fr.rule(h, fill="level")[rows])
            t = Fr.has[rows]
            hold_better = (money(Fr.H[rows]) > S)
            res["test"][name][w] = {"held": int((h[rows] & t).sum()), "touched": int(t.sum()), "mean": round(float(c.mean()), 2),
                                    "S": round(float(S.mean()), 2), "V3": round(float(mV3.mean()), 2),
                                    "vsS": judge(c - S), "vsS_level": judge(c_lv - money(Fr.S_lv[rows])), "vsV3": judge(c - mV3),
                                    "hitRate": round(100 * float(hold_better[h[rows] & t].mean()), 1) if (h[rows] & t).any() else None,
                                    "baseHoldBetter": round(100 * float(hold_better[t].mean()), 1)}
    # the bar: Holm over the four checkers on w4 P (one-sided bootstrap p), level fill not negative, w5 not negative
    ps = sorted(((res["test"][k]["w4"]["vsS"]["p"], k) for k in checkers))
    holm, alive = {}, True
    for j, (p_, k) in enumerate(ps):
        ok = alive and p_ <= 0.05 / (len(ps) - j) and res["test"][k]["w4"]["vsS"]["diff"] > 0
        alive = ok
        holm[k] = ok
    res["bar"] = {k: {"holm": holm[k], "w4_level_ok": res["test"][k]["w4"]["vsS_level"]["diff"] >= 0, "w5_ok": res["test"][k]["w5"]["vsS"]["diff"] >= 0,
                      "beatsV3": res["test"][k]["w4"]["vsV3"]["lo5"] > 0 and res["test"][k]["w5"]["vsV3"]["diff"] >= 0} for k in checkers}
    for k in checkers:
        b = res["bar"][k]
        b["HOLDS"] = bool(b["holm"] and b["w4_level_ok"] and b["w5_ok"])
    # how good are the reviewers' probabilities? (AUC of p for "HOLD ends with more money")
    from sklearn.metrics import roc_auc_score
    y = (money(key["hold"].to_numpy()) > money(key["sell"].to_numpy())).astype(int)
    res["auc_p"] = {}
    for rnd in ("r1", "r2"):
        _, Pp = votes[rnd]
        for r in REVIEWERS:
            pr = Pp[r].to_numpy()
            ok = np.isfinite(pr)
            res["auc_p"]["%s_%s" % (rnd, r)] = round(float(roc_auc_score(y[ok], pr[ok])), 4)
        pm = Pp.mean(1).to_numpy()
        res["auc_p"]["%s_mean" % rnd] = round(float(roc_auc_score(y, pm)), 4)
    res["auc_p"]["groups"] = auc_ci(y, P2.mean(1).to_numpy(), key["eid"].to_numpy())
    res["agree"] = {"r1_unanimous": round(100 * float(((V1.sum(1) == 0) | (V1.sum(1) == 3)).mean()), 1),
                    "r2_unanimous": round(100 * float(((V2.sum(1) == 0) | (V2.sum(1) == 3)).mean()), 1),
                    "changed_votes": int((V1 != V2).to_numpy().sum())}
    json.dump(res, open(os.path.join(out, "final.json"), "w"), indent=1, default=float)
    print(json.dumps({"answers": res["answers"], "bar": res["bar"], "auc_p": res["auc_p"], "agree": res["agree"]}, indent=1, default=float))
    for k, v in res["test"].items():
        print(k, {w: (v[w]["held"], v[w]["mean"], v[w]["vsS"]["diff"], v[w]["vsS"]["lo5"], v[w]["vsV3"]["diff"], v[w]["hitRate"]) for w in ("w4", "w5")})


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"build": cmd_build, "q1": cmd_q1, "q23": cmd_q23, "cards": cmd_cards, "debate": cmd_debate, "final": cmd_final}[cmd](*args)
