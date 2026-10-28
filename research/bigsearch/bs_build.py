"""Big search, step 1 (fake money only, no network): research/bigsearch/PREREG-BIGSEARCH-2026-10-28.md.

  coins   <md> <h2> <hist> <chain> <meta> <img> <s1 or -> <out>   one row per graduation with its launch facts -> coins.parquet
  rows    <md> <h2> <hist> <s1 or -> <out> [<only window>]         entry rows of the four families (chart, time and market
                                                                   variables, the 225 sell-rule outcomes) -> rows_<F>.pkl
  wallets <wallets dir> <kol csv or -> <out>                       wallet variables of the w3/w4 rows -> wal_<F>.npz

<md> = branch monthsdata (w1, w2, w5), <h2> = branch monthsh2 (w3, w4), <hist> = history2's coins.parquet + gap_minutes.npy,
<chain> = branch rocketschain, <meta> = branch rocketsmeta, <img> = branch rocketsimages, <s1> = branch bigsearchdata (the sealed
days; "-" while they are not fetched). Entries, sell rules and money as research/check_months.py (PR #42), plus the S family and
three Rocket holds. Needs pyarrow; rows about 6 GB with 3 workers."""
import glob, json, math, multiprocessing as mp, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "rockets"))
import check_months as CM                       # noqa: E402  windows, sell rules, money

BAR, MIN, H, DAY = 300_000, 60_000, 3_600_000, 86_400_000
WINDOWS = CM.WINDOWS + (("s1", "2026-10-22", "2026-10-26T12:00"),)
W_MS = [(w, int(pd.Timestamp(a, tz="UTC").timestamp() * 1000), int(pd.Timestamp(b, tz="UTC").timestamp() * 1000)) for w, a, b in WINDOWS]
FAMS = ("P", "U", "R", "S")
MONEY_OF = {"P": "pick", "U": "pick", "R": "radar", "S": "radar"}
ROCKET = ((0.5, 2.0, 0.6), (0.7, 1.5, 0.7), (0.5, 3.0, 0.5))      # floor, arm, keep share of the best; 24 h
RULES = list(CM.RULES) + [("rocket", f, a, k) for f, a, k in ROCKET]
CHART = CM.FEATS + ["r30m", "vacc", "rlow", "actall", "c_ret30", "c_peak30"]
TIMEMKT = ["hour", "weekend", "sol1h", "sol24h", "btc24h"]


def window(t):
    for w, a, b in W_MS:
        if a <= t < b:
            return w
    return None


def rule_name(r):
    if r[0] == "rocket":
        return "Rocket hold: %gx floor, after %gx sell at %d%% of the best, 24 h" % (r[1], r[2], round(100 * r[3]))
    return CM.rule_name(r)


def rocket_hold(P, floor, arm, keep):
    hi = 1.0
    for x in P:
        if x <= floor:
            return x
        if x > hi:
            hi = x
        if hi >= arm and x <= keep * hi:
            return x
    return P[-1] if len(P) else 1.0


def outcomes(P, n_t):
    out = CM.outcomes(P, n_t)
    P24 = P[:n_t[24]]
    for f, a, k in ROCKET:
        out.append([(1.0, rocket_hold(P24, f, a, k))])
    return out


# --------------------------------------------------------------------------------------------------------- rows
SOL = BTC = GAPS = META = None


def hourly(series, t, back):
    """Change over `back` hours of the last closed hour before t."""
    ts, cs = series
    i = np.searchsorted(ts, t - H, side="right") - 1
    if i - back < 0 or i >= len(cs):
        return np.nan
    return cs[i] / cs[i - back] - 1


def coin_rows(c, b):
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
    i0 = int(np.argmax(has))
    p_first = op[i0] if np.isfinite(op[i0]) and op[i0] > 0 else cl[i0]
    cv = np.r_[0, np.cumsum(v)]
    kk = float(c["sol0"]) * float(c["tok0"])
    gm = int(c["t"])
    rows = []
    for E in sorted(set(range(30, 721, 30)) | set(range(60, 1441, 60))):
        te = gm + E * MIN
        jl = (te - t0) // BAR - 1
        if jl < 0 or jl + 1 + 12 >= n or not np.isfinite(cf[jl]):
            continue
        p0 = cf[jl]
        if not has[:jl + 1].any():
            continue
        usd = float(CM.solusd(te))
        mc = p0 * 1e9
        liq = 2 * math.sqrt(kk * p0 / usd) * usd
        v24 = cv[jl + 1] - cv[max(0, jl + 1 - 288)]
        v1 = cv[jl + 1] - cv[max(0, jl + 1 - 12)]
        v1p = cv[max(0, jl + 1 - 12)] - cv[max(0, jl + 1 - 24)]

        def px(back_bars):
            k = jl - back_bars
            return cf[k] if k >= 0 and np.isfinite(cf[k]) else p_first

        lr = np.diff(np.log(cf[max(0, jl - 12):jl + 1]))
        lr = lr[np.isfinite(lr)]
        hb = has[max(0, jl - 11):jl + 1]
        ups = (cl[max(0, jl - 11):jl + 1] > op[max(0, jl - 11):jl + 1])[hb]
        ia = int(np.nanargmax(hf[:jl + 1]))
        lastb = int(np.nonzero(has[:jl + 1])[0][-1])
        lo = np.nanmin(cf[i0:jl + 1])
        f = {"age_h": E / 60, "lmc": math.log10(mc), "liqmc": liq / mc, "volmc": v24 / mc, "vol1s": v1 / v24 if v24 > 0 else 0.0,
             "r5": p0 / px(1) - 1, "r1h": p0 / px(12) - 1, "r6h": p0 / px(72) - 1, "r24h": p0 / px(288) - 1, "rgrad": p0 / p_first - 1,
             "ddath": p0 / hf[ia] - 1, "hath": (jl - ia) * 5 / 60, "vola1h": float(lr.std()) if len(lr) >= 3 else 0.0,
             "act1h": int(hb.sum()), "mlast": (te - (t0 + (lastb + 1) * BAR)) / MIN, "lvol1": math.log10(v1 + 1),
             "up1h": float(ups.mean()) if len(ups) else np.nan,
             "r30m": p0 / px(6) - 1, "vacc": v1 / v1p if v1p > 0 else (10.0 if v1 > 0 else np.nan),
             "rlow": p0 / lo - 1 if lo > 0 else np.nan, "actall": float(has[i0:jl + 1].mean()),
             "c_ret30": cf[min(5, jl)] / p_first - 1, "c_peak30": float(np.nanmax(hf[:min(5, jl) + 1])) / p_first}
        hourly_e = E % 60 == 0
        fam = []
        if hourly_e and 6 <= E / 60 <= 24 and 100_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 >= 15_000 \
                and not (f["r1h"] <= -0.10 or f["r6h"] <= -0.50 or f["r24h"] <= -0.70) and not (f["r1h"] >= 2.0 or f["r6h"] >= 0.90) \
                and v24 / mc <= 8:
            fam.append("P")
        if hourly_e and liq >= 15_000 and v24 >= 15_000 and mc >= 50_000:
            fam.append("U")
        if E <= 720 and liq >= 15_000 and v24 >= 15_000 and 100_000 <= mc <= 5_000_000 and f["r1h"] > -0.10 and f["r6h"] > -0.50:
            fam.append("R")
        if E in (30, 60) and liq >= 10_000:
            fam.append("S")
        if not fam:
            continue
        if GAPS is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((GAPS[:, 1] >= a) & (GAPS[:, 0] <= z)).any():
                continue
        jt = {t: (te + t * H - t0) // BAR - 1 - (jl + 1) for t in CM.TIMES}
        P = cf[jl + 2: jl + 2 + jt[24]] / p0
        if len(P) < jt[24]:
            continue
        H6 = hf[jl + 2: jl + 2 + jt[6]] / p0
        oc = outcomes(P, jt)
        f.update(hour=float((te // H) % 24), weekend=float(pd.Timestamp(te, unit="ms").dayofweek >= 5),
                 sol1h=hourly(SOL, te, 1), sol24h=hourly(SOL, te, 24), btc24h=hourly(BTC, te, 24))
        row = dict(pool=c["pool"], w=c["w"], E=E, te=te, grad=gm, fam="".join(fam), hi6=float(np.nanmax(H6)) if len(H6) else 1.0,
                   mx24=float(np.nanmax(P)) if len(P) else 1.0, **f)
        kinds = {MONEY_OF[x] for x in fam}
        if "pick" in kinds:
            row["Op"] = np.array([CM.money(pc, "pick") for pc in oc], np.float32)
        if "radar" in kinds:
            row["Or"] = np.array([CM.money(pc, "radar") for pc in oc], np.float32)
        rows.append(row)
    return rows


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
        out += coin_rows(c, g.sort_values("t"))
    return out


def load_market(md, s1):
    mk = json.load(open(os.path.join(md, "market.json")))
    if s1 != "-" and os.path.exists(os.path.join(s1, "market.json")):
        m2 = json.load(open(os.path.join(s1, "market.json")))
        for k in mk:
            d = dict(map(tuple, mk[k]))
            d.update(dict(map(tuple, m2.get(k) or [])))
            mk[k] = sorted([t, c] for t, c in d.items())
    arr = lambda k: (np.array([r[0] for r in mk[k]], np.int64), np.array([r[1] for r in mk[k]], float))
    return arr("SOLUSDT"), arr("BTCUSDT")


def cmd_rows(md, h2, hist, s1, out, only=None):
    global SOL, BTC, GAPS, META
    os.makedirs(out, exist_ok=True)
    SOL, BTC = load_market(md, s1)
    CM.SOL = SOL
    g = np.sort(np.load(os.path.join(hist, "gap_minutes.npy")))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    GAPS = np.c_[st[big], en[big]]
    meta, jobs, planned = {}, [], {}
    m2 = pd.read_parquet(os.path.join(h2, "meta_h2.parquet"))
    for r in m2.to_dict("records"):
        r["w"] = window(int(r["t"]))
        if r["w"] in ("w3", "w4"):
            meta[r["pool"]] = r
            planned[r["w"]] = planned.get(r["w"], 0) + 1
    if only in (None, "w3", "w4"):
        jobs += [(f, 0, 1) for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    srcs = [(f, os.path.join(md, "bars_%s.parquet" % os.path.basename(f)[5:-5])) for f in sorted(glob.glob(os.path.join(md, "meta_w*.json")))]
    if s1 != "-":
        srcs.append((os.path.join(s1, "meta_s1.json"), os.path.join(s1, "bars_s1.parquet")))
    for mf, bf in srcs:
        for r in json.load(open(mf)):
            r["w"] = window(int(r["t"]))
            if r["w"] in ("w1", "w2", "w5", "s1"):
                meta[r["pool"]] = r
                planned[r["w"]] = planned.get(r["w"], 0) + 1
        wname = os.path.basename(mf)[5:-5]
        if only in (None, wname):
            jobs += [(bf, k, 12) for k in range(12)]
    META = meta
    rows = []
    with mp.get_context("fork").Pool(3) as pool:
        for part in pool.imap_unordered(_work, jobs, chunksize=1):
            if only:
                part = [r for r in part if r["w"] == only]
            rows += part
    print("rows", len(rows), flush=True)
    fetched = {}
    for p, r in meta.items():
        if r.get("bars"):
            fetched[r["w"]] = fetched.get(r["w"], 0) + 1
    for fam in FAMS:
        key = "Op" if MONEY_OF[fam] == "pick" else "Or"
        rs = [r for r in rows if fam in r["fam"]]
        if not rs:
            continue
        df = pd.DataFrame([{k: v for k, v in r.items() if k not in ("Op", "Or")} for r in rs])
        O = np.stack([r[key] for r in rs])
        order = np.lexsort((df["E"].to_numpy(), df["pool"].to_numpy()))
        df = df.iloc[order].reset_index(drop=True)
        for c in CHART + TIMEMKT:
            df[c] = df[c].astype(np.float32)
        suffix = "" if not only else "_" + only
        pd.to_pickle({"df": df, "O": O[order], "planned": planned, "fetched": fetched}, os.path.join(out, "rows_%s%s.pkl" % (fam, suffix)))
        print(fam, len(df), "rows", df["pool"].nunique(), "coins", df.groupby("w")["pool"].nunique().to_dict(), flush=True)


# --------------------------------------------------------------------------------------------------------- coins
LAUNCH = ["f_curve_min", "f_creator_prior", "f_dup7", "f_cjk", "f_grads24", "f_nlinks", "f_xtype", "f_post_age", "f_theme24",
          "f_img_reused", "f_launch_other", "f_video", "f_desc_len", "f_news"]
PICTURE = ["f_group", "f_animated", "f_lookalike", "f_name_fit"]


def cmd_coins(md, h2, hist, chain, meta_dir, img, s1, out):
    import check_rockets as CR
    os.makedirs(out, exist_ok=True)
    rows = []
    for r in pd.read_parquet(os.path.join(h2, "meta_h2.parquet")).to_dict("records"):
        rows.append(dict(pool=r["pool"], mint=r["mint"], t=int(r["t"]), sol0=r["sol0"], tok0=r["tok0"]))
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        for r in json.load(open(f)):
            rows.append(dict(pool=r["pool"], mint=r["mint"], t=int(r["t"]), sol0=r["sol0"], tok0=r["tok0"]))
    chain_dirs = [chain]
    wiki = json.load(open(os.path.join(chain, "wiki_top.json"))) if os.path.exists(os.path.join(chain, "wiki_top.json")) else {}
    if s1 != "-":
        for r in json.load(open(os.path.join(s1, "grads.json")))["grads"]:
            if r["sol0"] >= 10:
                rows.append(dict(pool=r["pool"], mint=r["mint"], t=int(r["t"]), sol0=r["sol0"], tok0=r["tok0"]))
        if os.path.exists(os.path.join(s1, "wiki_top.json")):
            wiki.update({d: v for d, v in json.load(open(os.path.join(s1, "wiki_top.json"))).items() if v})
    c = pd.DataFrame(rows).drop_duplicates("pool").sort_values("t").reset_index(drop=True)
    c["w"] = c["t"].map(window)
    names = pd.read_parquet(os.path.join(hist, "coins.parquet"), columns=["pool", "symbol", "token_name", "creator", "created_ms"])
    names = names.drop_duplicates("pool").set_index("pool")
    for k in ("symbol", "token_name", "creator", "created_ms"):
        c[k] = c["pool"].map(names[k])
    c["created_ms"] = pd.to_numeric(c["created_ms"], errors="coerce")
    tmpchain = os.path.join(out, "chain_all")
    os.makedirs(tmpchain, exist_ok=True)
    ch = pd.read_parquet(os.path.join(chain, "chain.parquet"))
    if s1 != "-" and os.path.exists(os.path.join(s1, "chain_s1.parquet")):
        ch2 = pd.read_parquet(os.path.join(s1, "chain_s1.parquet"))
        ch = pd.concat([ch2, ch[~ch["mint"].isin(set(ch2["mint"]))]], ignore_index=True)
    for col in ch.columns:
        if ch[col].dtype == object:
            ch[col] = ch[col].astype(object).where(ch[col].notna(), None)
    ch.to_parquet(os.path.join(tmpchain, "chain.parquet"), index=False)
    lf = CR.launch_facts(c, None, meta_dir, tmpchain, wiki or None)
    lf = CR.picture_facts(lf, img if img != "-" else None)
    keep = ["pool", "mint", "t", "w", "sol0", "creator", "symbol", "token_name", "src_links", "src_created"] + LAUNCH + PICTURE
    lf = lf[[k for k in keep if k in lf.columns]]
    lf.to_parquet(os.path.join(out, "coins.parquet"), index=False)
    cov = lf.groupby("w")[[k for k in LAUNCH + PICTURE if k in lf.columns]].apply(lambda g: g.notna().mean().round(3)).T
    print(cov.to_string(), flush=True)
    print("coins by window", lf["w"].value_counts(dropna=False).to_dict(), flush=True)


# --------------------------------------------------------------------------------------------------------- wallets
WALLET = ["w_n", "w_sol", "w_fresh", "w_whale", "w_smart", "w_smartsh", "w_kol"]


def cmd_wallets(wd, kol, out):
    """Per w3/w4 row: buyers (first buy >= 0.1 SOL) before the entry, their SOL, share of first-time wallets, whales (first buy >=
    5 SOL), smart buyers (3+ earlier coins whose 48 h ended before this coin's graduation, mean ROI > 1) and their share, KOL
    wallets. A wallet's record uses only coins that ended 48 h before this coin's graduation (no look-ahead)."""
    files = sorted(glob.glob(os.path.join(wd, "pairs", "*.parquet")))
    cols = ["t_q", "sol_q", "wid", "coin", "grad_ms", "roi"]
    p = pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)
    print("pairs", len(p), flush=True)
    wc = pd.read_parquet(os.path.join(wd, "coins.parquet"))
    pool_of = dict(zip(wc["coin"], wc["pool"]))
    kol_ids = set()
    if kol != "-" and os.path.exists(kol):
        kc = pd.read_csv(kol)
        kl = set(kc["address"] if "address" in kc else kc.iloc[:, 0]).copy()
        kl = {str(x).strip() for x in kl}
        wl = pd.read_parquet(os.path.join(wd, "wallets.parquet"))
        kol_ids = set(wl.loc[wl["address"].astype(str).isin(kl), "wid"])
        print("KOL wallets found", len(kol_ids), flush=True)
    # each pair's wallet record before its coin
    o = np.lexsort((p["grad_ms"].to_numpy(), p["wid"].to_numpy()))
    wid = p["wid"].to_numpy()[o].astype(np.int64)
    gm = p["grad_ms"].to_numpy()[o].astype(np.int64)
    roi = np.nan_to_num(p["roi"].to_numpy()[o].astype(np.float64), nan=0.0, posinf=0.0)
    key = wid * (1 << 42) + gm
    first = np.r_[0, np.cumsum(np.r_[1, (wid[1:] != wid[:-1]).astype(np.int64)])[:-1]]
    seg_start = np.zeros(len(wid), np.int64)
    starts = np.r_[0, np.nonzero(wid[1:] != wid[:-1])[0] + 1]
    seg_start[starts] = starts
    seg_start = np.maximum.accumulate(seg_start)
    cr = np.r_[0.0, np.cumsum(roi)]
    j48 = np.searchsorted(key, wid * (1 << 42) + gm - 2 * DAY, side="left")
    jany = np.searchsorted(key, wid * (1 << 42) + gm, side="left")
    prior_n = j48 - seg_start
    prior_roi = np.where(prior_n > 0, (cr[j48] - cr[seg_start]) / np.maximum(prior_n, 1), np.nan)
    fresh = (jany - seg_start) == 0
    smart = (prior_n >= 3) & (prior_roi > 1.0)
    del first, key, cr, j48, jany
    P2 = pd.DataFrame({"coin": p["coin"].to_numpy()[o], "t_q": p["t_q"].to_numpy()[o], "sol": p["sol_q"].to_numpy()[o].astype(np.float32),
                       "fresh": fresh, "smart": smart, "whale": p["sol_q"].to_numpy()[o] >= 5, "kol": np.isin(wid, list(kol_ids))})
    del p
    P2 = P2.sort_values(["coin", "t_q"], kind="stable")
    byc = {}
    cv = P2["coin"].to_numpy()
    br = np.r_[0, np.nonzero(cv[1:] != cv[:-1])[0] + 1, len(cv)]
    tq = P2["t_q"].to_numpy()
    cs = {k: np.r_[0, np.cumsum(P2[k].to_numpy().astype(np.float64))] for k in ("sol", "fresh", "smart", "whale", "kol")}
    for a, z in zip(br[:-1], br[1:]):
        byc[pool_of.get(int(cv[a]))] = (a, z)
    for fam in FAMS:
        f = os.path.join(out, "rows_%s.pkl" % fam)
        if not os.path.exists(f):
            continue
        d = pd.read_pickle(f)["df"]
        W = np.full((len(d), len(WALLET)), np.nan, np.float32)
        for i, (pool, te, w) in enumerate(zip(d["pool"], d["te"], d["w"])):
            if w not in ("w3", "w4"):
                continue
            ab = byc.get(pool)
            if ab is None:
                W[i] = [0, 0, np.nan, 0, 0, np.nan, 0]
                continue
            a, z = ab
            k = a + np.searchsorted(tq[a:z], te, side="left")
            nb = k - a
            g = lambda col: cs[col][k] - cs[col][a]
            W[i] = [nb, g("sol"), g("fresh") / nb if nb else np.nan, g("whale"), g("smart"), g("smart") / nb if nb else np.nan, g("kol")]
        np.savez_compressed(os.path.join(out, "wal_%s.npz" % fam), W=W)
        print(fam, "wallet rows", int(np.isfinite(W[:, 0]).sum()), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "rows":
        cmd_rows(a[1], a[2], a[3], a[4], a[5], a[6] if len(a) > 6 else None)
    elif a[0] == "coins":
        cmd_coins(*a[1:8], a[8])
    elif a[0] == "wallets":
        cmd_wallets(a[1], a[2], a[3])
