"""The new facts at each decision moment (fake money only; research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md).

  python3 research/rocketsep/rs_facts.py <out dir> <data dir>

<data dir> holds the branches as folders: monthsdata, monthsh2, history2 (coins.parquet, hourly/), wallets (coins.parquet, pairs/),
rocketschain, rocketsmeta, rocketsimages, rocketslaunches. <out dir> is rs_build.py's. Writes <out dir>/facts.npz: per buy the
facts at the buy (GE, LE, HE, WE) and per sale event of frames A and B the facts at the decision (HA/WA, HB/WB); G and L facts are
per coin and the same at every moment. Nothing is bought; no network."""
import glob, json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rockets"))
import check_rockets as R                                     # noqa: E402  launch_facts, picture_facts (PR #55)

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
G_F = ["f_creator_prior", "f_curve_min", "f_dup7", "f_cjk", "f_grads24", "f_nlinks", "f_xtype", "f_news", "f_theme24", "f_post_age",
       "f_img_reused", "f_launch_other", "f_video", "f_desc_len", "f_group", "f_animated", "f_lookalike", "f_name_fit"]
L_F = ["l_creator_launches30", "l_creator_grads30"]
H_COLS = ["buyers_1h", "sellers_1h", "buys_1h", "sells_1h", "top_buyer_share_1h", "atomic_1h", "buys_24h", "sells_24h"]
H_F = ["h_" + c for c in H_COLS] + ["h_bs_ratio", "h_trade_ratio", "h_bs_ratio_chg", "h_trade_ratio_chg", "h_row_age"]
W_F = ["w_n", "w_new15", "w_new60", "w_sol60", "w_exp_share", "w_win_share", "w_exp_share60", "w_win_share60", "w_prior_lr60",
       "w_top_share"]
WINDOWS = ("w1", "w2", "w3", "w4", "w5")


def g_facts(dd):
    """F1-F22 (without F2) per pool, as research/rockets/check_rockets.py over the same coins table as build_paths.py."""
    import check_chartexit as X
    meta = []
    for r in pd.read_parquet(os.path.join(dd, "monthsh2", "meta_h2.parquet")).to_dict("records"):
        meta.append(r)
    for f in sorted(glob.glob(os.path.join(dd, "monthsdata", "meta_w*.json"))):
        meta += json.load(open(f))
    m = pd.DataFrame(meta)
    m["w"] = [X.window(int(t)) for t in m["t"]]
    m = m[m["w"].notna() & (m["sol0"] >= 10)].drop_duplicates("pool").reset_index(drop=True)
    names = pd.read_parquet(os.path.join(dd, "history2", "coins.parquet"), columns=["pool", "symbol", "token_name", "creator", "created_ms"])
    m = m.merge(names.drop_duplicates("pool"), on="pool", how="left")
    wiki = json.load(open(os.path.join(dd, "rocketschain", "wiki_top.json")))
    c = R.launch_facts(m, None, os.path.join(dd, "rocketsmeta"), os.path.join(dd, "rocketschain"), wiki)
    c = R.picture_facts(c, os.path.join(dd, "rocketsimages"))
    return c.set_index("pool")


def l_facts(dd, mints):
    """The creator's launches and graduations in the 30 days before the coin's own launch (w3/w4 launch universe)."""
    d = pd.concat([pd.read_parquet(f, columns=["mint", "creator", "t", "grad_t"]) for f in
                   sorted(glob.glob(os.path.join(dd, "rocketslaunches", "L_*.parquet")))], ignore_index=True)
    d = d.drop_duplicates("mint")
    d = d[d["creator"].notna() & (d["creator"].astype(str) != "")]
    code = pd.factorize(d["creator"])[0].astype(np.int64)
    t = d["t"].to_numpy(np.int64) * 1000
    big = np.int64(10 ** 13)
    ev = np.sort(code * big + t)
    gt = pd.to_numeric(d["grad_t"], errors="coerce").to_numpy()
    gok = np.isfinite(gt)
    gscale = 1000 if np.nanmedian(gt) < 1e11 else 1
    evg = np.sort(code[gok] * big + (gt[gok] * gscale).astype(np.int64))
    q = code * big + t
    l30 = np.searchsorted(ev, q, "left") - np.searchsorted(ev, q - 30 * DAY, "left")
    g30 = np.searchsorted(evg, q, "left") - np.searchsorted(evg, q - 30 * DAY, "left")
    out = pd.DataFrame({"mint": d["mint"].to_numpy(), "l_creator_launches30": l30.astype(float), "l_creator_grads30": g30.astype(float)})
    return out[out["mint"].isin(set(mints))].set_index("mint")


def h_facts(dd, mint, gm, tq, tbuy):
    """history2 hourly row at the latest whole hour h >= 1 with gm + h*H <= t; the ratios' change since the buy hour."""
    files = sorted(glob.glob(os.path.join(dd, "history2", "hourly", "hourly_*.parquet")))
    want = set(mint)
    parts = []
    for f in files:
        x = pd.read_parquet(f, columns=["mint", "h"] + H_COLS)
        parts.append(x[x["mint"].isin(want)])
    hr = pd.concat(parts, ignore_index=True).drop_duplicates(["mint", "h"])
    key = {m: i for i, m in enumerate(pd.unique(hr["mint"]))}
    hr["mi"] = hr["mint"].map(key).astype(np.int64)
    hr = hr.sort_values(["mi", "h"]).reset_index(drop=True)
    hk = hr["mi"].to_numpy() * 100 + hr["h"].to_numpy()
    vals = hr[H_COLS].to_numpy(np.float64)

    def row_at(t):
        mi = pd.Series(mint).map(key).to_numpy()
        ok = ~pd.isna(mi)
        h = np.floor((t - gm) / H).astype(np.int64)
        ok &= h >= 1
        mi = np.where(ok, mi, 0).astype(np.int64)
        q = mi * 100 + np.clip(h, 0, 99)
        j = np.searchsorted(hk, q, "right") - 1
        good = ok & (j >= 0)
        jj = np.clip(j, 0, len(hk) - 1)
        good &= (hk[jj] // 100) == mi
        out = np.full((len(t), len(H_COLS)), np.nan)
        out[good] = vals[jj[good]]
        hh = np.where(good, hk[jj] % 100, np.nan)
        return out, hh

    V, hh = row_at(tq)
    Vb, _ = row_at(tbuy)
    br = np.log1p(V[:, 0]) - np.log1p(V[:, 1])
    trr = np.log1p(V[:, 2]) - np.log1p(V[:, 3])
    brb = np.log1p(Vb[:, 0]) - np.log1p(Vb[:, 1])
    trb = np.log1p(Vb[:, 2]) - np.log1p(Vb[:, 3])
    age = (tq - (gm + hh * H)) / MIN
    return np.c_[V, br, trr, br - brb, trr - trb, age].astype(np.float32)


class Wallets:
    """Wallet numbers at any (coin, time) from the wallets branch's first-buy pairs."""

    def __init__(self, dd):
        wc = pd.read_parquet(os.path.join(dd, "wallets", "coins.parquet"))
        cols = ["t_q", "sol_q", "wid", "coin", "grad_ms", "roi"]
        p = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(os.path.join(dd, "wallets", "pairs", "*.parquet")))],
                      ignore_index=True)
        self.mint_of = wc["mint"].to_numpy() if "coin" not in wc.columns else wc.set_index("coin")["mint"]
        if "coin" in wc.columns:
            self.code = {m: int(c) for c, m in self.mint_of.items()}
        else:
            self.code = {m: i for i, m in enumerate(self.mint_of)}
        wid = p["wid"].to_numpy(np.int64)
        tq = p["t_q"].to_numpy(np.int64)
        lr = np.log(np.clip(p["roi"].to_numpy(np.float64), 1e-3, 1e3))
        win = (p["roi"].to_numpy() >= 3.0).astype(np.float64)
        # each pair's wallet record of coins that ended (graduation + 72 h) before this first buy
        S = np.int64(2 ** 31)
        settle = (p["grad_ms"].to_numpy(np.int64) + 72 * H) // 1000
        o = np.lexsort((settle, wid))
        ks = wid[o] * S + settle[o]
        cn = np.r_[0, np.cumsum(np.ones(len(o)))]
        cl = np.r_[0, np.cumsum(lr[o])]
        cw = np.r_[0, np.cumsum(win[o])]
        q = wid * S + tq // 1000
        hi = np.searchsorted(ks, q, "right")
        lo = np.searchsorted(ks, wid * S, "left")
        n_prior = cn[hi] - cn[lo]
        lr_prior = np.where(n_prior > 0, (cl[hi] - cl[lo]) / np.maximum(n_prior, 1), np.nan)
        won = (cw[hi] - cw[lo]) > 0
        exp = n_prior >= 5
        coin = p["coin"].to_numpy(np.int64)
        o2 = np.lexsort((tq, coin))
        self.k = coin[o2] * np.int64(2 ** 42) + tq[o2]
        self.coin_lo = {}
        sq = p["sol_q"].to_numpy(np.float64)[o2]
        self.c1 = np.r_[0, np.cumsum(np.ones(len(o2)))]
        self.csol = np.r_[0, np.cumsum(sq)]
        self.cexp = np.r_[0, np.cumsum(exp[o2].astype(float))]
        self.cwin = np.r_[0, np.cumsum(won[o2].astype(float))]
        lrp = np.where(exp, np.nan_to_num(lr_prior), 0.0)[o2]
        self.clr = np.r_[0, np.cumsum(lrp)]
        cm = pd.Series(sq).groupby(coin[o2]).cummax().to_numpy()
        self.cmax = cm
        print("wallet pairs", len(p), "coins", len(np.unique(coin)), flush=True)

    def at(self, mint, t):
        code = pd.Series(mint).map(self.code)
        ok = code.notna().to_numpy()
        c = np.where(ok, code.fillna(0).to_numpy(), 0).astype(np.int64)
        B = np.int64(2 ** 42)
        t = np.asarray(t, np.int64)
        i0 = np.searchsorted(self.k, c * B, "left")
        i1 = np.searchsorted(self.k, c * B + t, "right")
        i15 = np.searchsorted(self.k, c * B + t - 15 * MIN, "right")
        i60 = np.searchsorted(self.k, c * B + t - 60 * MIN, "right")
        n = self.c1[i1] - self.c1[i0]
        n60 = self.c1[i1] - self.c1[i60]
        n15 = self.c1[i1] - self.c1[i15]
        sol = self.csol[i1] - self.csol[i0]
        sol60 = self.csol[i1] - self.csol[i60]
        e = self.cexp[i1] - self.cexp[i0]
        wn = self.cwin[i1] - self.cwin[i0]
        e60 = self.cexp[i1] - self.cexp[i60]
        w60 = self.cwin[i1] - self.cwin[i60]
        lr60 = self.clr[i1] - self.clr[i60]
        top = np.where(n > 0, self.cmax[np.clip(i1 - 1, 0, len(self.cmax) - 1)] / np.maximum(sol, 1e-9), np.nan)
        dv = lambda a, b: np.where(b > 0, a / np.maximum(b, 1), np.nan)
        out = np.c_[n, n15, n60, sol60, dv(e, n), dv(wn, n), dv(e60, n60), dv(w60, n60), np.where(e60 > 0, lr60 / np.maximum(e60, 1), np.nan), top]
        out[~ok] = np.nan
        return out.astype(np.float32)


def main(out, dd):
    sys.path.insert(0, os.path.join(HERE, "..", "chartexit"))
    shards = sorted(glob.glob(os.path.join(out, "shards", "*_e.parquet")))
    Mt = pd.concat([pd.read_parquet(f, columns=["eid", "pool", "mint", "w", "gm", "te"]) for f in shards], ignore_index=True)
    D = pd.concat([pd.read_parquet(f.replace("_e.parquet", "_d.parquet"), columns=["eid", "frame", "tdec"]) for f in shards],
                  ignore_index=True)
    Mt = Mt.drop_duplicates("eid").reset_index(drop=True)
    D = D.drop_duplicates(["eid", "frame"]).reset_index(drop=True)
    print("buys", len(Mt), "events", len(D), flush=True)
    c = g_facts(dd)
    G = np.array(c.reindex(Mt["pool"])[G_F].to_numpy(np.float32))
    print("G facts", np.isfinite(G).any(1).sum(), "of", len(Mt), flush=True)
    h2w = Mt["w"].isin(["w3", "w4"]).to_numpy()
    Lf = l_facts(dd, Mt.loc[h2w, "mint"].unique())
    L = np.array(Lf.reindex(Mt["mint"])[L_F].to_numpy(np.float32))
    L[~h2w] = np.nan
    print("L facts", np.isfinite(L).any(1).sum(), flush=True)
    mint, gm, te = Mt["mint"].to_numpy(), Mt["gm"].to_numpy(np.int64), Mt["te"].to_numpy(np.int64)
    HE = h_facts(dd, mint, gm, te, te)
    HE[~h2w] = np.nan
    Wl = Wallets(dd)
    WE = Wl.at(mint, te)
    WE[~h2w] = np.nan
    res = dict(eid=Mt["eid"].to_numpy().astype(str), G=G, L=L, HE=HE, WE=WE)
    for fr in ("A", "B"):
        d = D[D["frame"] == fr].set_index("eid").reindex(Mt["eid"])
        tq = d["tdec"].to_numpy(np.float64)
        okq = np.isfinite(tq)
        tqi = np.where(okq, tq, te).astype(np.int64)
        Hq = h_facts(dd, mint, gm, tqi, te)
        Wq = Wl.at(mint, tqi)
        Hq[~(h2w & okq)] = np.nan
        Wq[~(h2w & okq)] = np.nan
        res["H" + fr], res["W" + fr] = Hq, Wq
    for k in ("HE", "WE", "HA", "WA"):
        cov = np.isfinite(res[k][h2w]).any(1).mean()
        print(k, "coverage on w3/w4 buys %.3f" % cov, flush=True)
    np.savez(os.path.join(out, "facts.npz"), **res)
    c[G_F + ["mint", "w", "t", "creator", "symbol", "token_name"]].to_parquet(os.path.join(out, "gfacts.parquet"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
