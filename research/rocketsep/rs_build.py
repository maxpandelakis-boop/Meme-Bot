"""The council build of PR #53 (research/council/check_council.py) line by line, with two more outputs (fake money only;
research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md): the features at the buy moment (FE) and each sale moment's decision time.
Generated from check_council.py's coin_entries and _work; the additions are marked "# rs:".

  python3 research/rocketsep/rs_build.py <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <chain.parquet> <out dir>"""
import os, sys, zlib, math
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "council"))
import check_council as CC                                    # noqa: E402
from check_council import (DC, M, X, BAR, MIN, H, HOURS, NP, INTRA_A, INTRA_B, v3_sale, lp_sale)   # noqa: E402,F401


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
        fe = np.concatenate([CF[jl], DC.pos_feats(C, Hh, Ll, 0, v60[jl], x["v1"], E), LF]).astype(np.float32)      # rs: at the buy
        ents.append(dict(eid=eid, pool=c["pool"], mint=c["mint"], w=c["w"], E=E, te=x["te"], gm=gm, roles="".join(sorted(roles)),
                         jl=int(jl), t0=int(t0), FE=fe,
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
            evs.append(dict(eid=eid, frame=fr, k=int(k_), intra=bool(intra), why=int(why), p=float(m_), F=f,
                            tdec=int(t0 + (ic + 1) * BAR)))                # rs: the decision time (the seen close's candle end)
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
    meta = pd.DataFrame([{q: r[q] for q in r if q not in ("C", "H", "L", "O", "V", "preC", "preV", "FE")} for r in ents])
    ev = pd.DataFrame([{q: r[q] for q in ("eid", "frame", "k", "intra", "why", "p", "tdec")} for r in evs])
    F = np.stack([r["F"] for r in evs])
    FE = np.stack([r["FE"] for r in ents])
    np.savez(dest, preC=pre, preV=prev, F=F, FE=FE, **arr)
    meta.to_parquet(dest.replace(".npz", "_e.parquet"))
    ev.to_parquet(dest.replace(".npz", "_d.parquet"))
    return dest, len(ents), len(evs)



CC.coin_entries = coin_entries
CC._work = _work

if __name__ == "__main__":
    CC.cmd_build(*sys.argv[1:6])
