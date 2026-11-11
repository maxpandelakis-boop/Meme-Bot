"""A council of 100 checkers that may hold a coin as long as it likes (fake money only): research/council/PREREG-COUNCIL-2026-10-25.md.

  build <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <chain.parquet> <out dir>   buys to the end of the data, events, plans
  q1 <out dir>                       Question 1: what each hold plan would have done against the sale -> q1.json
  council <out dir> choose|test|wf|placebo   the 100 checkers, the debate, the chair -> council_<step>.json
  cards <out dir> <jury dir>         the jury's case cards (contested w4/w5 P events) and the answer key (kept apart)
  final <out dir> <jury dir>         the bar over all candidates -> final.json

The buys are research/dipcheck/check_dip.py's coin_entries (PR #51) line by line, the path kept to the end of the data (graduation
+ 48 h). Nothing is bought; no network. Needs pandas, pyarrow, numba, lightgbm, scikit-learn."""
import glob, json, math, os, sys, zlib
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "dipcheck"))
import check_dip as DC                                        # noqa: E402  buys, features, money, the bootstrap
M = DC.M                                                      # check_mlexit
X = DC.X                                                      # check_chartexit

BAR, MIN, H = X.BAR, X.MIN, X.H
WN = X.WN
HOURS = X.HOURS
NP = 590                      # five-minute candles kept after the buy (to graduation + 48 h; padded with the last close)
SEED = 7
CTXF = ["why", "sale_m", "sale_min"]
FEATS = M.COIN_F + M.POS_F + M.LAUNCH_F + CTXF
WHY_A = ["floor", "trail_low", "tp", "trail_close", "drop", "time"]     # v3; the first three inside the candle
WHY_B = ["stop", "x2", "time"]                                          # S20-T2-H2; the first two inside the candle
INTRA_A = {0, 1, 2}
INTRA_B = {0, 1}
# plans: name, floor (x p, 0 none), horizon hours after the veto (-1 to the end), take profit (x buy, 0 none), trail, kind
PLANS = [("H1", 0.6, 1, 11.0, 0.0, 0), ("H3", 0.6, 3, 11.0, 0.0, 0), ("H6", 0.6, 6, 11.0, 0.0, 0), ("H12", 0.6, 12, 11.0, 0.0, 0),
         ("H24", 0.6, 24, 11.0, 0.0, 0), ("HE", 0.6, -1, 11.0, 0.0, 0), ("HN", 0.0, -1, 0.0, 0.0, 0), ("TR", 0.0, -1, 0.0, 0.30, 0),
         ("BE", 0.6, -1, 11.0, 0.0, 1), ("RS", 0.5, 6, 11.0, 0.15, 2)]
PN = [p[0] for p in PLANS]


# --------------------------------------------------------------------------------------------------------- the rules
def v3_sale(C, Hh, L, O, nT, level_fill=False):
    """check_mlexit.sim with V3 line by line, also telling where the sale happened. -> (mult, candle, why index)"""
    hi, armed = 1.0, False
    for k in range(nT):
        c, h, l = C[k], Hh[k], L[k]
        lvl = 0.5
        if armed:
            lvl = max(lvl, 0.85 * hi)
        if l <= lvl:
            f = min(O[k], lvl) if level_fill else min(l, lvl)
            return f, k, (0 if lvl <= 0.5 + 1e-12 else 1)
        if h >= 11.0:
            return 11.0, k, 2
        hi = max(hi, h)
        if not armed and hi >= 1.5:
            armed = True
        lvl2 = 0.5
        if armed:
            lvl2 = max(lvl2, 0.85 * hi)
        if c <= lvl2:
            return c, k, 3
        ref = C[k - 6] if k >= 6 else 1.0
        if c <= 0.85 * ref:
            return c, k, 4
    return C[nT - 1], nT - 1, 5


def lp_sale(C, Hh, L, O, nT, level_fill=False):
    """S20-T2-H2 (check_dip.run_rule with level 0.80, take profit 2x, 2 h)."""
    for k in range(nT):
        if L[k] <= 0.8:
            return (min(O[k], 0.8) if level_fill else L[k]), k, 0
        if Hh[k] >= 2.0:
            return 2.0, k, 1
    return C[nT - 1], nT - 1, 2


def _plan_kernel():
    import numba

    @numba.njit(parallel=True, cache=False)
    def run(C, Hh, L, O, k, intra, p, last, fl, hor, tp, tr, kind, level_fill, out):
        """One plan on n events. Event i: the rule sold at candle k[i] (inside it if intra[i]) at multiple p[i]; the plan holds from
        there to candle last[i] (the end of the data or the last candle before an outage)."""
        for i in numba.prange(C.shape[0]):
            ki, pi = k[i], p[i]
            end = last[i]
            if hor >= 0 and ki + hor * 12 < end:
                end = ki + hor * 12
            if end < ki:
                end = ki
            lvf = fl * pi if fl > 0 else -1.0
            tgt = max(1.0, 1.3 * pi) if kind == 1 else 1e30
            hi = pi
            armed = False
            res = C[i, end]
            for j in range(ki, end + 1):
                c, h, l, o = C[i, j], Hh[i, j], L[i, j], O[i, j]
                if j == ki:
                    if intra[i] and lvf > 0 and l <= lvf:
                        res = min(o, lvf) if level_fill else l
                        break
                    continue
                lv = lvf
                if tr > 0 and kind == 0:
                    lv = max(lv, (1.0 - tr) * hi)
                if kind == 2 and armed:
                    lv = max(lv, (1.0 - tr) * hi)
                if lv > 0 and l <= lv:
                    res = min(o, lv) if level_fill else l
                    break
                if tp > 0 and h >= tp:
                    res = tp
                    break
                if kind == 1 and h >= tgt:
                    res = tgt
                    break
                if h > hi:
                    hi = h
                if kind == 2:
                    if not armed and hi >= 1.5 * pi:
                        armed = True
                    lv2 = lvf
                    if armed:
                        lv2 = max(lv2, (1.0 - tr) * hi)
                    if c <= lv2:
                        res = c
                        break
                    ref = C[i, j - 6] if j - 6 > ki else pi
                    if c <= 0.85 * ref:
                        res = c
                        break
            out[i] = res
    return run


_PLAN = None


def run_plans(P, e, k, intra, p, last, level_fill=False):
    """-> (n, 10) multiples of the buy price, one column per plan"""
    global _PLAN
    if _PLAN is None:
        _PLAN = _plan_kernel()
    out = np.zeros((len(e), len(PLANS)))
    C, Hh, L, O = P["C"][e], P["H"][e], P["L"][e], P["O"][e]
    for j, (_, fl, hor, tp, tr, kind) in enumerate(PLANS):
        o = np.zeros(len(e))
        _PLAN(C, Hh, L, O, np.asarray(k, np.int64), np.asarray(intra, np.bool_), np.asarray(p, np.float64), np.asarray(last, np.int64),
              float(fl), int(hor), float(tp), float(tr), int(kind), bool(level_fill), o)
        out[:, j] = o
    return out


# --------------------------------------------------------------------------------------------------------- build
def coin_entries(c, b):
    """One coin: check_dip.coin_entries' buys (P, W1, X, Y, A, L), the path to the end of the data, both frames' events."""
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
    jend = min(n - 1, -(-(gm + 48 * H - t0) // BAR) - 1)        # the last candle that starts before graduation + 48 h
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
        gapEnd, cut = False, -1
        if gaps is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((gaps[:, 1] >= a) & (gaps[:, 0] <= z)).any():
                continue
            tend = t0 + (jend + 1) * BAR
            later = (gaps[:, 1] >= te) & (gaps[:, 0] <= tend)
            gapEnd = bool(later.any())
            if gapEnd:
                g0 = int(gaps[later, 0].min())
                cut = int((g0 - t0) // BAR - (jl + 2))           # the path candle in which the first later outage starts
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in HOURS + (24,)}
        if len(cf[jl + 2: jl + 2 + jt[24]]) < jt[24]:
            break
        cands.append(dict(E=E, te=te, jl=jl, p0=p0, v1=v1, mc=mc, liq=liq, v24=v24, r1h=r1h, r6h=r6h, r24h=r24h, gapEnd=gapEnd, cut=cut,
                          nb=[int(min(M.NB, jt[t])) for t in HOURS], nEnd=int(jend - (jl + 2) + 1),
                          isP=isP, isW=isW, isA=isA, isL=isL))
    if not cands:
        return [], []
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
        ne = x["nEnd"]
        s = slice(jl + 2, jl + 2 + ne)
        C = cf[s] / p0
        hs = has[s]
        Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
        Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
        O = np.where(hs & np.isfinite(op[s]) & (op[s] > 0), op[s], np.r_[cf[jl + 1], cf[jl + 2: jl + 1 + ne]]) / p0
        Hh = np.where(Hh <= X.WICK_X * C, Hh, C)
        Ll = np.where(Ll >= C / X.WICK_X, Ll, C)
        O = np.clip(O, Ll, Hh)
        V = v[s] * hs
        nb = np.array(x["nb"], np.int64)
        ref = M.sim(C[:M.NB], Hh[:M.NB], Ll[:M.NB], O[:M.NB], V[:M.NB], nb, x["v1"], M.pvec(M.V3))
        nT6, nT2 = int(nb[HOURS.index(6)]), int(nb[HOURS.index(2)])
        a = v3_sale(C, Hh, Ll, O, nT6)
        a_lv = v3_sale(C, Hh, Ll, O, nT6, True)
        bq = lp_sale(C, Hh, Ll, O, nT2)
        b_lv = lp_sale(C, Hh, Ll, O, nT2, True)
        eid = "%s:%d" % (c["pool"], E)

        def pad(z):
            return np.r_[z, np.full(NP - len(z), z[-1])].astype(np.float32)
        ents.append(dict(eid=eid, pool=c["pool"], mint=c["mint"], w=c["w"], E=E, te=x["te"], gm=gm, roles="".join(sorted(roles)),
                         nb=nb.tolist(), nEnd=ne, gapEnd=x["gapEnd"], cut=x["cut"], v1=float(x["v1"]), mc=x["mc"], liq=x["liq"],
                         v24=x["v24"], r1h=x["r1h"], r6h=x["r6h"], r24h=x["r24h"], ref_V3=float(ref[0]),
                         A_m=float(a[0]), A_k=int(a[1]), A_why=int(a[2]), A_lv=float(a_lv[0]),
                         B_m=float(bq[0]), B_k=int(bq[1]), B_why=int(bq[2]), B_lv=float(b_lv[0]),
                         C=pad(C), H=pad(Hh), L=pad(Ll), O=pad(O), V=np.r_[V, np.zeros(NP - len(V))].astype(np.float32),
                         preC=(cf[max(0, jl + 2 - 36): jl + 2] / p0).astype(np.float32), preV=vf[max(0, jl + 2 - 36): jl + 2].astype(np.float32)))
        for fr, (m_, k_, why), intra_set in (("A", a, INTRA_A), ("B", bq, INTRA_B)):
            intra = why in intra_set
            upto = k_ if intra else k_ + 1
            ic = jl + 1 + upto                                   # the coin candle of the last finished close the checker sees
            f = np.concatenate([CF[ic], DC.pos_feats(C, Hh, Ll, upto, v60[ic], x["v1"], E), LF,
                                [float(why), float(m_), (k_ + 1) * 5.0]]).astype(np.float32)
            evs.append(dict(eid=eid, frame=fr, k=int(k_), intra=bool(intra), why=int(why), p=float(m_), F=f))
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
    ev = pd.DataFrame([{q: r[q] for q in ("eid", "frame", "k", "intra", "why", "p")} for r in evs])
    F = np.stack([r["F"] for r in evs])
    np.savez(dest, preC=pre, preV=prev, F=F, **arr)
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
    """-> buys (one row each, as check_dip.load: a pool in two sources counts once), paths, events (both frames), features"""
    metas, A, evs, Fs = [], {q: [] for q in ("C", "H", "L", "O", "V", "preC", "preV")}, [], []
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
        Fs.append(z["F"])
    Mt = pd.concat(metas, ignore_index=True)
    hasP = Mt["roles"].str.contains("P")
    fp = Mt[hasP].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    fo = Mt[~Mt["pool"].isin(fp["pool"])].sort_values(["te", "pool"]).drop_duplicates("pool")[["pool", "shard"]]
    Mt = Mt.merge(pd.concat([fp, fo]).rename(columns={"shard": "keep"}), on="pool")
    Mt = Mt[Mt["shard"] == Mt["keep"]].drop(columns="keep")
    Mt = Mt.sort_values(["te", "pool", "E"]).reset_index(drop=True)
    P = {q: np.stack([A[q][s][r] for s, r in zip(Mt["shard"], Mt["row"])]).astype(np.float64 if q in "CHLO" else np.float32) for q in A}
    D = pd.concat(evs, ignore_index=True)
    ix = pd.Series(np.arange(len(Mt)), index=Mt["eid"] + "|" + Mt["shard"].astype(str))
    key = D["eid"] + "|" + D["shard"].astype(str)
    D = D[key.isin(ix.index)].copy()
    D["e"] = ix[key[key.isin(ix.index)]].to_numpy()
    F = np.concatenate([Fs[s][r][None] for s, r in zip(D["shard"], D["frow"])]).astype(np.float32)
    D = D.reset_index(drop=True)
    return Mt, P, D, F


class Frame:
    """One frame's events (one per buy, in buy order) with the plans' outcomes and gains."""

    def __init__(self, Mt, P, D, F, fr):
        d = D[D["frame"] == fr].sort_values("e")
        assert len(d) == len(Mt) and (d["e"].to_numpy() == np.arange(len(Mt))).all()
        self.fr = fr
        self.F = F[d.index.to_numpy()]
        self.k, self.intra, self.why, self.p = (d[q].to_numpy() for q in ("k", "intra", "why", "p"))
        n = len(Mt)
        e = np.arange(n)
        nEnd = Mt["nEnd"].to_numpy()
        cut = Mt["cut"].to_numpy()
        last = np.where(cut >= 0, np.minimum(nEnd - 1, cut - 1), nEnd - 1)
        self.last = np.maximum(last, self.k)
        self.sale = Mt[fr + "_m"].to_numpy()
        self.sale_lv = Mt[fr + "_lv"].to_numpy()
        self.plan = run_plans(P, e, self.k, self.intra, self.p, self.last)
        self.plan_lv = run_plans(P, e, self.k, self.intra, self.p, self.last, level_fill=True)
        self.gain = DC.money(self.plan) - DC.money(self.sale)[:, None]
        self.gapEnd = Mt["gapEnd"].to_numpy().astype(bool)
        self.w = Mt["w"].to_numpy()
        self.gm = Mt["gm"].to_numpy()
        self.roles = Mt["roles"].to_numpy()

    def rule(self, hold, plan, fill="low"):
        """hold (bool per buy), plan (index per buy) -> the council's multiple per buy"""
        S, Pm = (self.sale_lv, self.plan_lv) if fill == "level" else (self.sale, self.plan)
        pj = np.clip(plan, 0, len(PLANS) - 1)
        return np.where(hold, Pm[np.arange(len(S)), pj], S)


def role_rows(Mt, role, w=None):
    return DC.role_rows(Mt, role, w)


# --------------------------------------------------------------------------------------------------------- Question 1
def cmd_q1(out):
    Mt, P, D, F = load(out)
    res = {"buys": {r: {w: int(role_rows(Mt, r, w).sum()) for w in WN} for r in ("P", "L", "A", "W1", "X", "Y")}}
    ref = json.load(open(os.path.join(HERE, "..", "chartexit", "result.json")))
    mis = int((np.abs(Mt["A_m"].to_numpy() - Mt["ref_V3"].to_numpy()) > 1e-6).sum())
    res["check"] = {"v3_vs_sim_mismatches": mis,
                    "byWindow": {w: {"n": int(role_rows(Mt, "P", w).sum()), "ref_n": ref["coins"][w],
                                     "V3": round(float(DC.money(Mt["A_m"].to_numpy()[role_rows(Mt, "P", w)]).mean()), 2),
                                     "ref_V3": ref["low"]["live"]["byWindow"][w]["mean"]} for w in WN},
                    "gapEnd": {w: int((Mt["gapEnd"].to_numpy().astype(bool) & (Mt["w"] == w).to_numpy()).sum()) for w in WN},
                    "nEnd_hours_P": {q: round(float(np.percentile(Mt["nEnd"].to_numpy()[role_rows(Mt, "P")], q)) / 12, 1) for q in (0, 50, 100)}}
    print(json.dumps(res["check"], indent=0), flush=True)
    for fr, role, whys in (("A", "P", WHY_A), ("B", "L", WHY_B), ("A", "ALL", WHY_A), ("B", "ALL", WHY_B)):
        Fm = Frame(Mt, P, D, F, fr)
        sale_money = DC.money(Fm.sale)
        for w in WN + ["w1-w3", "w4-w5", "all"]:
            ws = {"w1-w3": ["w1", "w2", "w3"], "w4-w5": ["w4", "w5"], "all": WN}.get(w, [w])
            base = (np.isin(Fm.w, ws) & (np.ones(len(Mt), bool) if role == "ALL" else role_rows(Mt, role)))
            r = {"events": int(base.sum()), "rule": round(float(sale_money[base].mean()), 2) if base.any() else None, "plans": {}, "byReason": {}}
            for j, pn in enumerate(PN):
                g = Fm.gain[base, j]
                m = Fm.plan[base, j]
                r["plans"][pn] = {"gain": round(float(g.mean()), 2) if base.any() else None, "planMean": round(float(DC.money(m).mean()), 2) if base.any() else None,
                                  "gainedPct": round(100 * float((g > 0).mean()), 1) if base.any() else None,
                                  "x2": int((m >= 2).sum()), "x5": int((m >= 5).sum()), "x10": int((m >= 10).sum())}
            for wi, wn in enumerate(whys):
                s = base & (Fm.why == wi)
                if s.sum():
                    r["byReason"][wn] = {"n": int(s.sum()), "saleMult": round(float(np.median(Fm.sale[s])), 3),
                                         "gain": {pn: round(float(Fm.gain[s, j].mean()), 2) for j, pn in enumerate(PN)}}
            res.setdefault(fr + "_" + role, {})[w] = r
        print(fr, role, {w: (res[fr + "_" + role][w]["events"], res[fr + "_" + role][w]["rule"],
                             {pn: res[fr + "_" + role][w]["plans"][pn]["gain"] for pn in PN}) for w in ("w1", "w2", "w3")}, flush=True)   # the test windows only in q1.json
    json.dump(res, open(os.path.join(out, "q1.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- the 100 checkers
VIEWS = [
    ("V1", "Kurz-Chartleser", "lgb", ["lr5", "lr10", "lr15", "lr30", "lr60"] + ["seq%d" % q for q in range(24)]
     + ["vol30", "vol60", "rng1h", "up12", "downrun", "body", "wick_up", "wick_lo"]),
    ("V2", "Lang-Chartleser", "lgb", ["lr120", "lr240", "lr360", "rng4h", "ath", "atl", "vol180", "age"]),
    ("V3", "Volumen-Leser", "lgb", ["v5", "v15", "v60", "v60_prev", "v60_ratio", "nt12", "nt36", "upvol", "turnover", "lmc", "lliq", "liqmc"]),
    ("V4", "Positions-Leser", "lgb", list(M.POS_F)),
    ("V5", "Markt-und-Uhr", "lgb", ["sol1h", "sol6h", "sol24h", "btc24h", "hour", "wday", "age"]),
    ("V6", "Start-Fakten", "lgb", list(M.LAUNCH_F) + ["lmc", "age"]),
    ("V7", "Allrounder", "lgb", list(M.COIN_F + M.POS_F + M.LAUNCH_F)),
    ("V8", "Rechenschieber", "ridge", list(M.COIN_F + M.POS_F + M.LAUNCH_F)),
    ("V9", "Zwillingssucher", "knn", ["lr5", "lr30", "lr60", "lr360", "vol60", "v60_ratio", "turnover", "lmc", "ath", "held", "ret", "dd"]),
    ("V10", "Skeptiker", "table", []),
]
NV, NPL = len(VIEWS), len(PLANS)
TAUS = (0.20, 0.35, 0.50, 0.65, 0.80)
MARGINS = (0.0, 2.0, 5.0, 10.0)
CANDS = [("R1", t) for t in TAUS] + [("R2", t) for t in TAUS] + [("CH", m) for m in MARGINS]
CLIP = (-250.0, 250.0)
LGBP = dict(objective="regression", learning_rate=0.05, num_leaves=15, min_data_in_leaf=300, feature_fraction=0.8, bagging_fraction=0.8,
            bagging_freq=1, lambda_l2=10.0, seed=SEED, num_threads=1, verbose=-1)
FI = {f: i for i, f in enumerate(FEATS)}
G = {}                         # the fit workers' shared arrays (set before the fork)


def vcols(v):
    return [FI[f] for f in VIEWS[v][3]] + [FI[f] for f in CTXF]


def lgb_fit_pred(Xtr, y, gt, Xte):
    import lightgbm as lgb
    cut = np.quantile(gt, 0.85)
    va = gt >= cut
    dtr = lgb.Dataset(Xtr[~va], y[~va], free_raw_data=True)
    dva = lgb.Dataset(Xtr[va], y[va], reference=dtr, free_raw_data=True)
    b = lgb.train(LGBP, dtr, num_boost_round=400, valid_sets=[dva], callbacks=[lgb.early_stopping(50, verbose=False)])
    return b.predict(Xte, num_iteration=b.best_iteration).astype(np.float64), int(b.best_iteration)


def _lgb_task(t):
    v, j, tr_key, te_key, extra = t
    Xf, Y, GT = G["F"], G["Y"], G["gm"]
    tr, te = np.asarray(G[tr_key]), np.asarray(G[te_key])
    cols = vcols(v)
    Xtr, Xte = Xf[tr][:, cols], Xf[te][:, cols]
    if extra is not None:
        etr, ete = G[extra + "_tr"][:, j], G[extra + "_te"][:, j]
        str_, ste = G[extra + "_s_tr"], G[extra + "_s_te"]
        Xtr = np.c_[Xtr, etr, str_]
        Xte = np.c_[Xte, ete, ste]
    y = np.clip(Y[tr, j], *CLIP)
    p, it = lgb_fit_pred(Xtr, y, GT[tr], Xte)
    return (v, j, tr_key, te_key, extra), p, it


def rank_tf(Xtr, Xte):
    """Each column -> its quantile among the training values (NaN -> 0.5)."""
    out_tr, out_te = np.empty_like(Xtr, dtype=np.float64), np.empty_like(Xte, dtype=np.float64)
    for c in range(Xtr.shape[1]):
        a = Xtr[:, c].astype(np.float64)
        ok = np.isfinite(a)
        srt = np.sort(a[ok])
        for src, dst in ((Xtr, out_tr), (Xte, out_te)):
            b = src[:, c].astype(np.float64)
            q = np.searchsorted(srt, b, side="right") / max(len(srt), 1) if len(srt) else np.full(len(b), 0.5)
            dst[:, c] = np.where(np.isfinite(b), q, 0.5)
    return out_tr, out_te


def ridge_fit_pred(Xtr, Y, Xte, alpha):
    from sklearn.linear_model import Ridge
    r = Ridge(alpha=alpha).fit(Xtr, Y)
    return r.predict(Xte)


def knn_pred(Xtr, Ytr, Xte, k=200):
    from sklearn.neighbors import NearestNeighbors
    mu = np.nanmean(Xtr, 0)
    sd = np.nanstd(Xtr, 0)
    sd = np.where(sd > 0, sd, 1.0)
    a = np.nan_to_num((Xtr - mu) / sd)
    b = np.nan_to_num((Xte - mu) / sd)
    nn = NearestNeighbors(n_neighbors=k, algorithm="kd_tree", n_jobs=3).fit(a)
    out = np.empty((len(b), Ytr.shape[1]))
    for s in range(0, len(b), 20000):
        _, ix = nn.kneighbors(b[s:s + 20000])
        out[s:s + 20000] = Ytr[ix].mean(1)
    return out


def table_keys(Fm, rows, s1=None):
    why = Fm.F[rows, FI["why"]].astype(int)
    p = Fm.F[rows, FI["sale_m"]]
    pb = np.digitize(p, [0.6, 0.9, 1.2, 2.0])
    age = Fm.F[rows, FI["age"]]
    ab = np.digitize(age, [360.0, 720.0])
    key = why * 100 + pb * 10 + ab
    if s1 is not None:
        key = key * 10 + np.digitize(s1, [0.2, 0.5])
    return why, key


def table_pred(Fm, tr, te, Y, s1_tr=None, s1_te=None, w0=50.0):
    wtr, ktr = table_keys(Fm, tr, s1_tr)
    wte, kte = table_keys(Fm, te, s1_te)
    Ytr = Y[tr]
    out = np.zeros((te.sum(), Y.shape[1]))
    overall = Ytr.mean(0)
    rmean = {r: Ytr[wtr == r].mean(0) for r in np.unique(wtr)}
    cells = {}
    for kk in np.unique(ktr):
        s = ktr == kk
        cells[kk] = (Ytr[s].sum(0), s.sum())
    for i, (r, kk) in enumerate(zip(wte, kte)):
        base = rmean.get(r, overall)
        if kk in cells:
            sm, n = cells[kk]
            out[i] = (sm + w0 * base) / (n + w0)
        else:
            out[i] = base
    return out


def blocked_folds(gm, rows, k=3):
    idx = np.nonzero(rows)[0]
    order = idx[np.argsort(gm[idx], kind="stable")]
    parts = np.array_split(order, k)
    out = []
    for p in parts:
        f = np.zeros(len(gm), bool)
        f[p] = True
        out.append(f)
    return out


def _init_worker(d):
    """A spawned worker (a fork would inherit numba's thread pool and hang LightGBM): the shared arrays from disk, read-only."""
    G.clear()
    for f in glob.glob(os.path.join(d, "*.npy")):
        G[os.path.basename(f)[:-4]] = np.load(f, mmap_mode="r")


def run_lgb_tasks(tasks):
    import multiprocessing as mp, tempfile, shutil
    d = tempfile.mkdtemp(prefix="council_", dir=G.get("_tmp"))
    for k, v in G.items():
        if not k.startswith("_"):
            np.save(os.path.join(d, k + ".npy"), np.asarray(v))
    res = {}
    try:
        with mp.get_context("spawn").Pool(3, initializer=_init_worker, initargs=(d,)) as pool:
            for key, p, it in pool.imap_unordered(_lgb_task, tasks, chunksize=1):
                res[key] = (p, it)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def round_preds(Fm, Y, tr, te, folds, extra=None, log=print):
    """All ten views x ten plans: predictions on te (fitted on tr) and, if folds, out of fold on tr.
    extra: None (round 1) or the round-1 inputs (dict with m_tr, m_te, s_tr, s_te) for round 2. -> (P_te (n_te, NV, NPL), P_oof)"""
    n = len(Y)
    tmp = G.get("_tmp")
    G.clear()
    G.update(F=Fm.F, Y=Y, gm=Fm.gm.astype(np.float64), TR=tr, TE=te, _tmp=tmp)
    keys = [("TR", "TE")]
    if folds:
        for f, fo in enumerate(folds):
            G["TR%d" % f] = tr & ~fo
            G["TE%d" % f] = fo
            keys.append(("TR%d" % f, "TE%d" % f))
    if extra is not None:
        G["X_tr"], G["X_te"], G["X_s_tr"], G["X_s_te"] = extra["m_tr"], extra["m_te"], extra["s_tr"], extra["s_te"]
    tasks = [(v, j, a, b, "X" if extra is not None else None) for v in range(NV) if VIEWS[v][2] == "lgb" for j in range(NPL) for a, b in keys]
    res = run_lgb_tasks(tasks)
    P_te = np.zeros((te.sum(), NV, NPL))
    P_oof = np.zeros((tr.sum(), NV, NPL)) if folds else None
    tr_pos = np.full(n, -1)
    tr_pos[tr] = np.arange(tr.sum())
    iters = []
    for (v, j, a, b, _), (p, it) in res.items():
        iters.append(it)
        if a == "TR":
            P_te[:, v, j] = p
        else:
            P_oof[tr_pos[G[b]], v, j] = p
    log("  lgb fits", len(res), "median trees", int(np.median(iters)), flush=True)
    Yc = np.clip(Y, *CLIP)
    for v in range(NV):
        kind = VIEWS[v][2]
        if kind == "lgb":
            continue
        for a, b in keys:
            ta, tb = G[a], G[b]
            if kind == "ridge":
                cols = vcols(v)
                Xa, Xb = Fm.F[ta][:, cols], Fm.F[tb][:, cols]
                if extra is not None:
                    Xa = np.c_[Xa, np.zeros((len(Xa), 2))]
                    Xb = np.c_[Xb, np.zeros((len(Xb), 2))]
                ra, rb = rank_tf(Xa, Xb)
                pr = np.zeros((tb.sum(), NPL))
                for j in range(NPL):
                    if extra is not None:
                        ea, eb = sub(extra, a, tr, ta, j), sub(extra, b, tr, tb, j, te_side=True)
                        ra[:, -2:], rb[:, -2:] = rank_tf(ea, eb)
                    pr[:, j] = ridge_fit_pred(ra, Yc[ta, j], rb, 10.0)
            elif kind == "knn":
                cols = vcols(v)[:-3] + [FI["sale_m"], FI["sale_min"], FI["why"]]
                Xa, Xb = Fm.F[ta][:, cols].astype(np.float64), Fm.F[tb][:, cols].astype(np.float64)
                if extra is not None:
                    pr = np.zeros((tb.sum(), NPL))
                    for j in range(NPL):
                        ea, eb = sub(extra, a, tr, ta, j), sub(extra, b, tr, tb, j, te_side=True)
                        pr[:, j] = knn_pred(np.c_[Xa, ea], Y[ta][:, [j]], np.c_[Xb, eb])[:, 0]
                else:
                    pr = knn_pred(Xa, Y[ta], Xb)
            else:
                s_a = sub(extra, a, tr, ta, 0)[:, 1] if extra is not None else None
                s_b = sub(extra, b, tr, tb, 0, te_side=True)[:, 1] if extra is not None else None
                pr = table_pred(Fm, ta, tb, Y, s_a, s_b)
            if a == "TR":
                P_te[:, v, :] = pr
            else:
                P_oof[tr_pos[tb], v, :] = pr
    return P_te, P_oof


def sub(extra, key, tr, rows, j, te_side=False):
    """The round-2 inputs (m_j, s) for the rows of a fit: training-side rows read the out-of-fold values, the TE side the full-fit ones."""
    if key == "TE":
        return np.c_[extra["m_te"][:, j], extra["s_te"]]
    pos = np.full(len(tr), -1)
    pos[tr] = np.arange(tr.sum())
    i = pos[rows]
    return np.c_[extra["m_tr"][i, j], extra["s_tr"][i]]


def council_votes(Pr):
    """Pr (n, NV, NPL) -> share of HOLD votes, the council's plan, the mean predicted gain per plan"""
    vote = Pr > 0
    s = vote.reshape(len(Pr), -1).mean(1)
    cnt = vote.sum(1)                                        # (n, NPL) hold votes per plan
    mg = Pr.mean(1)                                          # (n, NPL)
    # most votes, then the higher mean predicted gain, then the earlier plan
    score = cnt * 1e6 + np.clip(mg, -1e5, 1e5) + 1e-9 * (NPL - np.arange(NPL))
    plan = np.argmax(score, 1)
    return s, plan, mg


def chair_fit(P_oof, Y_tr, P_te):
    """Per plan: ridge (alpha 1) of the gain on the ten views' out-of-fold round-1 predictions -> predicted gain (n_te, NPL)"""
    out = np.zeros((len(P_te), NPL))
    coefs = []
    for j in range(NPL):
        from sklearn.linear_model import Ridge
        r = Ridge(alpha=1.0).fit(P_oof[:, :, j], Y_tr[:, j])
        out[:, j] = r.predict(P_te[:, :, j])
        coefs.append([round(float(c), 4) for c in r.coef_])
    return out, coefs


def decisions(cand, R):
    """cand -> (hold bool, plan) over the evaluation rows; R: the step's predictions"""
    fam, x = cand
    if fam in ("R1", "R2"):
        s, plan = R["s" + fam[1]], R["plan" + fam[1]]
        return s >= x - 1e-12, plan
    g = R["chair"]
    plan = np.argmax(g, 1)
    return g[np.arange(len(g)), plan] > x, plan


def run_step(Fm, tr, te, log=print, shuffle=False, round2=True):
    """Round 1 (with out-of-fold), round 2, the chair. -> dict of predictions on te"""
    Y = Fm.gain.copy()
    if shuffle:                                                # the placebo: gains shuffled among training events of the same reason
        rng = np.random.default_rng(SEED)
        idx = np.nonzero(tr)[0]
        for r in np.unique(Fm.why[idx]):
            s_ = idx[Fm.why[idx] == r]
            Y[s_] = Y[rng.permutation(s_)]
    folds = blocked_folds(Fm.gm, tr) if round2 else None
    log(" round 1", flush=True)
    P1, P1o = round_preds(Fm, Y, tr, te, folds, log=log)
    s1, plan1, m1 = council_votes(P1)
    R = dict(P1=P1, s1=s1, plan1=plan1)
    if round2:
        s1o, _, m1o = council_votes(P1o)
        log(" round 2", flush=True)
        P2, _ = round_preds(Fm, Y, tr, te, None, extra=dict(m_tr=m1o, m_te=m1, s_tr=s1o, s_te=s1), log=log)
        s2, plan2, _ = council_votes(P2)
        chair, coefs = chair_fit(P1o, Y[tr], P1)
        R.update(P2=P2, s2=s2, plan2=plan2, chair=chair, chairCoefs=coefs)
    return R


def judge_rows(Fm, rows_te, hold, plan, te):
    """Money per 50-EUR trade on the judged buys (rows_te: bool over te rows)"""
    idx = np.nonzero(te)[0][rows_te]
    h, pl = hold[rows_te], plan[rows_te]
    full_h = np.zeros(len(Fm.sale), bool)
    full_p = np.zeros(len(Fm.sale), np.int64)
    full_h[idx], full_p[idx] = h, pl
    c = Fm.rule(full_h, full_p)[idx]
    c_lv = Fm.rule(full_h, full_p, "level")[idx]
    mR, mC = DC.money(Fm.sale[idx]), DC.money(c)
    d = mC - mR
    d_lv = DC.money(c_lv) - DC.money(Fm.sale_lv[idx])
    ok = ~Fm.gapEnd[idx]
    best = Fm.plan[idx].max(1)
    out = {"buys": int(len(idx)), "held": int(h.sum()), "rule": round(float(mR.mean()), 2), "council": round(float(mC.mean()), 2),
           "vsRule": DC.judge(d), "vsRule_level": round(float(d_lv.mean()), 3),
           "vsRule_noOutage": {"n": int(ok.sum()), "diff": round(float(d[ok].mean()), 3) if ok.any() else None},
           "plans": {PN[j]: int((h & (pl == j)).sum()) for j in range(NPL)},
           "heldEnded": {"x2+": int((h & (c >= 2)).sum()), "x5+": int((h & (c >= 5)).sum()), "x10+": int((h & (c >= 10)).sum()),
                         "gainPerHold": round(float(d[h].mean()), 2) if h.any() else None, "heldWon": int((h & (d > 0)).sum())},
           "missed": {"bestPlan5x+": int((~h & (best >= 5)).sum()), "bestPlan10x+": int((~h & (best >= 10)).sum())}}
    return out, mC, d


def step_rows(Fm, te, ws, roles):
    w = Fm.w[te]
    r = Fm.roles[te]
    sel = np.isin(w, ws)
    rs = np.zeros(len(r), bool)
    for ro in roles:
        rs |= np.char.find(r.astype(str), ro) >= 0
    return sel & rs


def cmd_council(out, step):
    import time
    Mt, P, D, F = load(out)
    G["_tmp"] = out
    res = {"step": step, "frames": {}}
    t_start = time.time()
    log = lambda *a, **k: print("[%5.0fs]" % (time.time() - t_start), *a, **k)
    W = Mt["w"].to_numpy()
    for fr in ("A", "B"):
        Fm = Frame(Mt, P, D, F, fr)
        roles = ("P", "W1") if fr == "A" else ("L",)
        test_role = ("P",) if fr == "A" else ("L",)
        log("frame", fr, step, flush=True)
        if step == "choose":
            tr, te = np.isin(W, ["w1", "w2"]), np.isin(W, ["w3"])
            R = run_step(Fm, tr, te, log)
            rows = step_rows(Fm, te, ["w3"], roles)
            table = []
            for cand in CANDS:
                hold, plan = decisions(cand, R)
                j, _, d = judge_rows(Fm, rows, hold, plan, te)
                table.append({"cand": list(cand), "diff": j["vsRule"]["diff"], "held": j["held"], "buys": j["buys"]})
            best = sorted(table, key=lambda r: (-r["diff"], r["held"]))[0]
            res["frames"][fr] = {"table": table, "chosen": best["cand"], "chairCoefs": R["chairCoefs"]}
            log(fr, "chosen", best, flush=True)
        elif step in ("test", "wf", "placebo"):
            ch = json.load(open(os.path.join(out, "council_choose.json")))["frames"][fr]["chosen"]
            ch = (ch[0], float(ch[1]))
            named = [("chosen", ch), ("majority2", ("R2", 0.50)), ("chair0", ("CH", 0.0))]
            if step == "wf":
                tr, te, tws = np.isin(W, ["w1", "w2", "w3", "w4"]), np.isin(W, ["w5"]), [["w5"]]
            else:
                tr, te, tws = np.isin(W, ["w1", "w2", "w3"]), np.isin(W, ["w4", "w5"]), [["w4"], ["w5"]]
            R = run_step(Fm, tr, te, log, shuffle=(step == "placebo"), round2=(step != "placebo"))
            if step == "placebo":
                named = [("majority1", ("R1", 0.50))] + ([("chosen", ch)] if ch[0] == "R1" else [])
            fres = {"chosen": list(ch), "cands": {}}
            for nm, cand in named:
                hold, plan = decisions(cand, R)
                for ws in tws:
                    for role_set, lab in ((test_role, "test"), (roles, "wide")):
                        rows = step_rows(Fm, te, ws, role_set)
                        j, mC, d = judge_rows(Fm, rows, hold, plan, te)
                        if lab == "test":
                            j["profit"] = profit_check(mC)
                        fres["cands"].setdefault(nm, {})["%s_%s" % (ws[0], lab)] = j
                log(fr, nm, cand, {k: (v["held"], v["vsRule"]["diff"], v["vsRule"]["p"]) for k, v in fres["cands"][nm].items()}, flush=True)
            # every candidate on the test windows (reported, not the bar)
            fres["all"] = {}
            for cand in CANDS if step != "placebo" else [("R1", t) for t in TAUS]:
                hold, plan = decisions(cand, R)
                for ws in tws:
                    rows = step_rows(Fm, te, ws, test_role)
                    j, _, _ = judge_rows(Fm, rows, hold, plan, te)
                    fres["all"]["%s %s %s" % (cand[0], cand[1], ws[0])] = {"held": j["held"], "diff": j["vsRule"]["diff"], "p": j["vsRule"]["p"]}
            # each single checker on the test buys: how often it says hold and what its own holds bring
            if step == "test":
                single = {}
                for ws in tws:
                    rows = step_rows(Fm, te, ws, test_role)
                    idx = np.nonzero(te)[0][rows]
                    G1 = Fm.gain[idx]
                    for v in range(NV):
                        for jj in range(NPL):
                            hv = R["P1"][rows, v, jj] > 0
                            single.setdefault("%s-%s" % (VIEWS[v][0], PN[jj]), {})[ws[0]] = [int(hv.sum()), round(float((G1[:, jj] * hv).mean()), 3)]
                fres["single"] = single
                np.savez(os.path.join(out, "test_%s.npz" % fr), te=te, s1=R["s1"], s2=R["s2"], plan1=R["plan1"], plan2=R["plan2"],
                         chair=R["chair"], P1=R["P1"].astype(np.float32), P2=R["P2"].astype(np.float32))
            res["frames"][fr] = fres
    json.dump(res, open(os.path.join(out, "council_%s.json" % step), "w"), indent=1)


def profit_check(mC, cost=0.75):
    """research/PREREG-REVIEW-2026-11-04.md: >= 40 trades, mean > 0 after the cost allowance, 1 % lower bound > 0, > 0 without the best"""
    m = np.asarray(mC, float) - cost
    if len(m) < 2:
        return {"n": int(len(m)), "holds": False}
    rng = np.random.default_rng(SEED)
    bs = np.array([m[rng.integers(0, len(m), len(m))].mean() for _ in range(20000)])
    lo1 = float(np.quantile(bs, 0.01))
    wob = float(np.sort(m)[:-1].mean())
    ok = len(m) >= 40 and m.mean() > 0 and lo1 > 0 and wob > 0
    return {"n": int(len(m)), "meanAfterCost": round(float(m.mean()), 2), "lo1": round(lo1, 2), "withoutBest": round(wob, 2), "holds": bool(ok)}


# --------------------------------------------------------------------------------------------------------- the jury
WHY_TXT = {0: "floor (the price fell to half the buy price)", 1: "trailing stop (15 % under the highest price, at a low inside the candle)",
           2: "take profit at 11x", 3: "trailing stop (a close 15 % under the highest price)",
           4: "drop (a close 15 % under the close 30 minutes earlier)", 5: "time (6 hours after the buy)"}
LO, HI_ = 0.20, 0.80
NJ = 120


def fmt(a, d=2):
    return " ".join(("%." + str(d) + "f") % x if np.isfinite(x) else "-" for x in a)


def cmd_cards(out, jd):
    Mt, P, D, F = load(out)
    Fm = Frame(Mt, P, D, F, "A")
    z = np.load(os.path.join(out, "test_A.npz"))
    te = z["te"]
    idx_te = np.nonzero(te)[0]
    s2, plan2, P2 = z["s2"], z["plan2"], z["P2"]
    rows = step_rows(Fm, te, ["w4", "w5"], ("P",))
    cont = rows & (s2 >= LO - 1e-12) & (s2 <= HI_ + 1e-12)
    ci = np.nonzero(cont)[0]
    rng = np.random.default_rng(SEED)
    if len(ci) > NJ:
        ci = np.sort(rng.choice(ci, NJ, replace=False))
    order = rng.permutation(len(ci))
    os.makedirs(jd, exist_ok=True)
    q1 = json.load(open(os.path.join(out, "q1.json")))["A_P"]["w1-w3"]
    with open(os.path.join(jd, "base_rates.txt"), "w") as f:
        f.write("Training months only (Apr-May, Jun-Jul, Aug-Sep 2026), Pick-type buys, 50 EUR each, fees included.\n")
        f.write("The Sell bot's own result: %.2f EUR per trade on %d trades.\n" % (q1["rule"], q1["events"]))
        f.write("If every sale had been vetoed and the plan taken instead (gain against selling, EUR per trade; share of cases where it gained):\n")
        for pn in PN:
            r = q1["plans"][pn]
            f.write("  %s: %+.2f EUR, gained in %.1f %%, ended at 2x+ %d, 5x+ %d, 10x+ %d times\n" % (pn, r["gain"], r["gainedPct"], r["x2"], r["x5"], r["x10"]))
        f.write("By the Sell bot's reason (number of cases, median sale price, gain of each plan against selling in EUR per trade):\n")
        for rn, r in q1["byReason"].items():
            f.write("  %s: %d cases, sold at %.2f; %s\n" % (rn, r["n"], r["saleMult"], ", ".join("%s %+.1f" % (k, v) for k, v in r["gain"].items())))
    key, lines = [], []
    for n, oi in enumerate(order):
        i_te = ci[oi]
        e = idx_te[i_te]
        r = Mt.iloc[e]
        k, why, pm = int(Fm.k[e]), int(Fm.why[e]), float(Fm.p[e])
        upto = k if Fm.intra[e] else k + 1
        f = Fm.F[e]
        g = lambda name: float(f[FI[name]])
        votes = (P2[i_te] > 0).sum(0)
        L = ["CASE %d" % (n + 1),
             "Bought: coin age %.0f h since it left the launch curve; market cap %s USD; liquidity %s USD; volume last 24 h %s USD; "
             "change before the buy: 1 h %+.0f %%, 6 h %+.0f %%, 24 h %+.0f %%." % (r["E"] / 60, "{:,.0f}".format(r["mc"]), "{:,.0f}".format(r["liq"]),
                                                                                "{:,.0f}".format(r["v24"]), 100 * r["r1h"], 100 * r["r6h"], 100 * r["r24h"]),
             "3 h before the buy, five-minute closes (x of the buy price, oldest first): " + fmt(P["preC"][e][-36:]),
             "  volumes (USD per five minutes): " + fmt(P["preV"][e][-36:], 0),
             "Since the buy, five-minute closes (x of the buy price): " + (fmt(P["C"][e][:upto]) if upto else "(none finished yet)"),
             "  lows: " + (fmt(P["L"][e][:upto]) if upto else "-"),
             "  highs: " + (fmt(P["H"][e][:upto]) if upto else "-"),
             "  volumes (USD): " + (fmt(P["V"][e][:upto], 0) if upto else "-"),
             "The Sell bot sells now: %s, at %.3f of the buy price, %d minutes after the buy%s." % (
                 WHY_TXT[why], pm, (k + 1) * 5, " (inside the next candle, not shown)" if Fm.intra[e] else ""),
             "Market: SOL last 1 h %+.1f %%, 6 h %+.1f %%, 24 h %+.1f %%; BTC 24 h %+.1f %%." % (100 * g("sol1h"), 100 * g("sol6h"), 100 * g("sol24h"), 100 * g("btc24h")),
             "Launch facts: X link %s, Telegram %s, website %s, description %s characters, video %s, name %s letters, CJK name %s, "
             "creator's graduations in the 30 days before: %s, minutes on the launch curve: %s." % (tuple(
                 ("yes" if g(q) == 1 else "no" if g(q) == 0 else "unknown") for q in ("l_x", "l_tg", "l_web")) + tuple(
                 ("%.0f" % g(q) if np.isfinite(g(q)) else "unknown") for q in ("l_desc",)) + tuple(
                 ("yes" if g(q) == 1 else "no" if g(q) == 0 else "unknown") for q in ("l_video",)) + ("%.0f" % g("l_name"),) + tuple(
                 ("yes" if g(q) == 1 else "no") for q in ("l_cjk",)) + tuple(
                 ("%.0f" % g(q) if np.isfinite(g(q)) else "unknown") for q in ("l_prev30",)) + (
                 "%.0f" % math.expm1(g("l_curve")) if np.isfinite(g("l_curve")) else "unknown",)),
             "The 100 checkers after their debate: HOLD votes per plan (of 10): " + ", ".join("%s %d" % (PN[j], votes[j]) for j in range(NPL))
             + "; together %d of 100 say HOLD." % round(100 * s2[i_te]),
             ""]
        lines += L
        key.append({"case": n + 1, "eid": r["eid"], "w": r["w"], "e": int(e), "i_te": int(i_te), "s2": float(s2[i_te]), "plan2": PN[int(plan2[i_te])],
                    "sale": float(Fm.sale[e]), "plans": {PN[j]: float(Fm.plan[e, j]) for j in range(NPL)},
                    "gain": {PN[j]: round(float(Fm.gain[e, j]), 3) for j in range(NPL)}})
    open(os.path.join(jd, "cards.txt"), "w").write("\n".join(lines))
    json.dump({"contested": int(cont.sum()), "shown": len(ci), "key": key}, open(os.path.join(out, "jury_key.json"), "w"), indent=1)
    print("contested", int(cont.sum()), "cards", len(ci), "lines", len(lines))


ROLES = ["chart reader", "volume and flow reader", "sceptic", "risk manager", "momentum trader", "dip buyer", "rocket hunter",
         "clock and age analyst", "statistician", "devil's advocate"]


def read_votes(jd, rnd):
    out = {}
    for n in range(1, 11):
        f = os.path.join(jd, "r%d_%d.json" % (rnd, n))
        if os.path.exists(f):
            out[n] = {int(v["case"]): v for v in json.load(open(f))}
    return out


def cmd_debate(out, jd):
    """Round 2 files: for every case without a unanimous round 1, the other nine reviewers' votes and reasons."""
    r1 = read_votes(jd, 1)
    assert len(r1) == 10, "round 1 incomplete: %s" % sorted(r1)
    cases = sorted(set().union(*[set(v) for v in r1.values()]))
    split = [c for c in cases if len({r1[n][c]["vote"] for n in r1 if c in r1[n]}) > 1]
    for n in range(1, 11):
        L = ["Round 2. Cases where round 1 was not unanimous: %d of %d. For each: the other nine reviewers' round-1 votes." % (len(split), len(cases)),
             "Your own round-1 votes on the other cases stand.", ""]
        for c in split:
            L.append("CASE %d (your round 1: %s, p_hold %.2f)" % (c, r1[n][c]["vote"], float(r1[n][c]["p_hold"])))
            for m in range(1, 11):
                if m != n and c in r1[m]:
                    v = r1[m][c]
                    L.append("  %s: %s, p_hold %.2f, %s" % (ROLES[m - 1], v["vote"], float(v["p_hold"]), v.get("why", "")))
            L.append("")
        open(os.path.join(jd, "debate_for_%d.txt" % n), "w").write("\n".join(L))
    json.dump({"split": split, "cases": len(cases)}, open(os.path.join(jd, "split.json"), "w"))
    print("cases", len(cases), "split", len(split))


def jury_decision(jd, key):
    """-> {case: (hold, plan index)} from round 2 (round 1 where a reviewer had no round-2 vote on the case)"""
    r1, r2 = read_votes(jd, 1), read_votes(jd, 2)
    dec, detail = {}, {}
    for k in key:
        c = k["case"]
        votes = []
        for n in range(1, 11):
            v = r2.get(n, {}).get(c) or r1.get(n, {}).get(c)
            if v is not None:
                votes.append(v["vote"])
        holds = [v for v in votes if v in PN]
        if len(holds) >= 6:
            cnt = {pn: holds.count(pn) for pn in PN}
            best = max(PN, key=lambda pn: (cnt[pn], -PN.index(pn)))
            dec[c] = (True, PN.index(best))
        else:
            dec[c] = (False, 0)
        detail[c] = {"votes": votes, "r1holds": sum(1 for n in r1 if r1[n].get(c, {}).get("vote") in PN)}
    return dec, detail


def holm(ps):
    """ps: {name: p} -> {name: survives at 5 %}"""
    items = sorted(ps.items(), key=lambda kv: kv[1])
    m = len(items)
    out, ok = {}, True
    for i, (nm, p) in enumerate(items):
        ok = ok and p <= 0.05 / (m - i)
        out[nm] = bool(ok)
    return out


def cmd_final(out, jd):
    Mt, P, D, F = load(out)
    T = json.load(open(os.path.join(out, "council_test.json")))["frames"]
    res = {"candidates": {}}
    for fr in ("A", "B"):
        for nm, c in T[fr]["cands"].items():
            res["candidates"]["%s %s" % (fr, nm)] = {"w4": c["w4_test"], "w5": c["w5_test"]}
    # the jury (frame A)
    jk = os.path.join(out, "jury_key.json")
    r1 = read_votes(jd, 1)
    if len(r1) == 10:
        key = json.load(open(jk))["key"]
        Fm = Frame(Mt, P, D, F, "A")
        z = np.load(os.path.join(out, "test_A.npz"))
        te, s2, plan2 = z["te"], z["s2"], z["plan2"]
        hold = s2 >= HI_ - 1e-12
        hold = hold & ~((s2 >= LO - 1e-12) & (s2 <= HI_ + 1e-12))
        plan = plan2.copy()
        dec, detail = jury_decision(jd, key)
        for k in key:
            h, pj = dec[k["case"]]
            hold[k["i_te"]] = h
            plan[k["i_te"]] = pj
        jr = {}
        for ws in ("w4", "w5"):
            rows = step_rows(Fm, te, [ws], ("P",))
            j, mC, d = judge_rows(Fm, rows, hold, plan, te)
            j["profit"] = profit_check(mC)
            jr[ws] = j
        # how the jury's calls ended on its own cases
        g = np.array([k["gain"][PN[dec[k["case"]][1]]] if dec[k["case"]][0] else 0.0 for k in key])
        best = np.array([max(k["gain"].values()) for k in key])
        jr["cases"] = {"n": len(key), "held": int(sum(dec[k["case"]][0] for k in key)), "gainOnCases": round(float(g.sum()), 2),
                       "anyPlanBeatsSelling": int((best > 0).sum()),
                       "r1HoldVotes": int(sum(d_["r1holds"] for d_ in detail.values())),
                       "r2HoldVotes": int(sum(sum(1 for v in d_["votes"] if v in PN) for d_ in detail.values()))}
        # did the jury's probabilities rank the cases? (AUC of mean p_hold for "the best plan beats selling")
        ph = []
        for k in key:
            vals = [float(r1[n][k["case"]]["p_hold"]) for n in r1 if k["case"] in r1[n]]
            ph.append(np.mean(vals))
        y = np.array([max(k["gain"].values()) > 0 for k in key]).astype(float)
        y_mp = np.array([k["gain"][k["plan2"]] > 0 for k in key]).astype(float)
        from sklearn.metrics import roc_auc_score
        jr["cases"]["aucBestPlan"] = round(float(roc_auc_score(y, ph)), 3) if 0 < y.mean() < 1 else None
        jr["cases"]["aucCouncilPlan"] = round(float(roc_auc_score(y_mp, ph)), 3) if 0 < y_mp.mean() < 1 else None
        res["candidates"]["A jury"] = jr
        res["juryDetail"] = {str(c): v for c, v in detail.items()}
    else:
        res["jury"] = "not run"
    ps = {nm: c["w4"]["vsRule"]["p"] for nm, c in res["candidates"].items()}
    surv = holm(ps)
    for nm, c in res["candidates"].items():
        w4, w5 = c["w4"], c["w5"]
        c["holmSurvives"] = surv[nm]
        c["holds"] = bool(surv[nm] and w4["vsRule"]["diff"] > 0 and w4["vsRule_level"] >= 0 and (w4["vsRule_noOutage"]["diff"] or 0) >= 0
                          and w5["vsRule"]["diff"] >= 0)
        c["profitable"] = bool(w4["profit"]["holds"] and w5["profit"]["holds"])
    res["anyHolds"] = any(c["holds"] for c in res["candidates"].values())
    for f in ("wf", "placebo"):
        q = os.path.join(out, "council_%s.json" % f)
        if os.path.exists(q):
            W = json.load(open(q))["frames"]
            res[f] = {"%s %s" % (fr, nm): {k: {"held": v["held"], "diff": v["vsRule"]["diff"], "p": v["vsRule"]["p"]} for k, v in c.items() if "test" in k}
                      for fr in W for nm, c in W[fr]["cands"].items()}
    json.dump(res, open(os.path.join(out, "final.json"), "w"), indent=1)
    for nm, c in res["candidates"].items():
        print(nm, "w4 held %d diff %+.3f p %.4f lv %+.3f | w5 held %d diff %+.3f | holm %s holds %s profitable %s" % (
            c["w4"]["held"], c["w4"]["vsRule"]["diff"], c["w4"]["vsRule"]["p"], c["w4"]["vsRule_level"], c["w5"]["held"], c["w5"]["vsRule"]["diff"],
            c["holmSurvives"], c["holds"], c["profitable"]))
    print("any holds", res["anyHolds"], res.get("A jury", {}) if False else "")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"build": cmd_build, "q1": cmd_q1, "council": cmd_council, "cards": cmd_cards, "debate": cmd_debate, "final": cmd_final}[cmd](*args)
