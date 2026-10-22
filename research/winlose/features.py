"""Winner/loser study (fake money only): every number a coin showed AT the entry hour, from five kinds of sources.
  chart   one-minute bars of its first 25 hours (branch chartbars): returns, RSI, volume spikes, buy/sell pressure, candles,
          support, trend, volatility, the path since the graduation
  flow    the hourly screener numbers (branch history2) and their change since the hour before
  wallets who bought before the entry (branch wallets): how many, how big, how experienced, how good their earlier coins were
          (only coins whose 48 h result was known three days before the entry)
  market  SOL and BTC over the last 1/24 h (branch marketctx), how many coins graduated in the last 24 h, how coins of 2-3 days
          ago did (known by then)
  pattern look-alikes: built per fold in model.py, not here
Nothing uses a number from after the entry minute.
usage: python3 research/winlose/features.py <scratch dir with d.pkl, pairs.pkl, cb/, w/, mk/>  -> <scratch>/feat.pkl"""
import glob, json, os, sys
import numpy as np, pandas as pd

S = sys.argv[1]
d = pd.read_pickle(os.path.join(S, "d.pkl"))
rows = d[d["univ"] & d["eur_A"].notna()].copy()
pools = set(rows["pool"])


def rsi(close, n=14):
    if len(close) < n + 1:
        return np.nan
    dif = np.diff(close[-(n + 1):])
    up, dn = dif[dif > 0].sum(), -dif[dif < 0].sum()
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


def chart_feats(b, E):
    """b: dense per-minute arrays of one pool (index = minute since graduation); E: entry minute (bars before it only)."""
    c, hi, lo, vb, vs, nb, ns, na = (x[:E] for x in (b["c"], b["hi"], b["lo"], b["vb"], b["vs"], b["nb"], b["ns"], b["na"]))
    if E < 30 or not np.isfinite(c[-1]) or c[-1] <= 0:
        return {}
    lc = np.log(c)
    f = {}
    for k in (5, 15, 30, 60, 120, 240):
        f["ret_%d" % k] = lc[-1] - lc[max(0, E - 1 - k)]
    f["ret_grad"] = lc[-1] - lc[np.argmax(np.isfinite(lc))]
    ath = np.nanmax(hi)
    f["dd_ath"] = c[-1] / ath
    f["min_since_ath"] = E - 1 - int(np.nanargmax(hi))
    f["from_low"] = c[-1] / np.nanmin(lo[max(0, E - 240):])
    f["rsi_1m"] = rsi(c[-15:])
    c5 = c[(E % 5)::5][-30:] if E >= 75 else c[::5]
    f["rsi_5m"] = rsi(c[E - 1::-5][::-1][-15:]) if E >= 75 else np.nan
    f["rsi_15m"] = rsi(c[E - 1::-15][::-1][-15:]) if E >= 225 else np.nan
    v = vb + vs
    v5 = v[-5:].sum()
    v60 = v[-60:].sum() / 12
    f["vol_spike_5"] = v5 / v60 if v60 > 0 else np.nan
    f["vol_spike_15"] = v[-15:].sum() / (v[-120:].sum() / 8) if v[-120:].sum() > 0 else np.nan
    f["vol_trend_60"] = v[-60:].sum() / v[-120:-60].sum() if v[-120:-60].sum() > 0 else np.nan
    for k in (5, 15, 60):
        t = vb[-k:].sum() + vs[-k:].sum()
        f["buy_imb_%d" % k] = (vb[-k:].sum() - vs[-k:].sum()) / t if t > 0 else 0.0
    nb30, nbp = nb[-30:].sum(), nb[-60:-30].sum()
    f["buys_trend_30"] = (nb30 + 1) / (nbp + 1)
    tr60 = nb[-60:].sum() + ns[-60:].sum()
    f["trades_60"] = tr60
    f["avg_trade_sol_60"] = v[-60:].sum() / tr60 if tr60 else np.nan
    f["active_min_60"] = int((nb[-60:] + ns[-60:] > 0).sum())
    f["atomic_60"] = na[-60:].sum() / tr60 if tr60 else np.nan
    r1 = np.diff(lc[-61:])
    r1 = r1[np.isfinite(r1)]
    f["vola_60"] = float(np.std(r1)) if len(r1) > 5 else np.nan
    f["max_drop_1m_60"] = float(r1.min()) if len(r1) else np.nan
    f["max_jump_1m_60"] = float(r1.max()) if len(r1) else np.nan
    # Bollinger position and trend on 5-minute closes of the last 2 hours
    c5 = lc[E - 1::-5][::-1][-24:]
    if len(c5) >= 12:
        m, s = c5[-20:].mean(), c5[-20:].std()
        f["bb_pos"] = (c5[-1] - m) / s if s > 0 else 0.0
        x = np.arange(len(c5))
        p = np.polyfit(x, c5, 1)
        res = c5 - np.polyval(p, x)
        f["trend_slope"] = p[0]
        f["trend_r2"] = 1 - res.var() / c5.var() if c5.var() > 0 else 0.0
    # candles: the last 5-minute and 15-minute candle
    for k in (5, 15):
        o, cl, h, l = c[-k - 1], c[-1], np.nanmax(hi[-k:]), np.nanmin(lo[-k:])
        rng = h - l
        if rng > 0:
            f["body_%d" % k] = (cl - o) / rng
            f["upwick_%d" % k] = (h - max(o, cl)) / rng
            f["lowick_%d" % k] = (min(o, cl) - l) / rng
    # engulfing: last 5-min candle reverses and covers the one before
    if E >= 11:
        o1, c1, o2, c2 = c[-11], c[-6], c[-6], c[-1]
        f["engulf_bull"] = float(c1 < o1 and c2 > o2 and c2 - o2 > o1 - c1)
        f["engulf_bear"] = float(c1 > o1 and c2 < o2 and o2 - c2 > c1 - o1)
    # support: how often the 5-min lows of the last 2 hours came back to within 5% of their minimum, and the distance to it
    l5 = np.array([np.nanmin(lo[max(0, E - 5 * (i + 1)):E - 5 * i]) for i in range(min(24, E // 5))])[::-1]
    if len(l5) >= 6 and np.isfinite(l5).all():
        sup = l5.min()
        f["support_touches"] = int((l5 <= sup * 1.05).sum())
        f["dist_support"] = c[-1] / sup
        res_ = np.array([np.nanmax(hi[max(0, E - 5 * (i + 1)):E - 5 * i]) for i in range(min(24, E // 5))])
        f["resist_touches"] = int((res_ >= res_.max() * 0.95).sum())
        f["dist_resist"] = c[-1] / res_.max()
    # the first hour after the graduation (same for every entry hour of a coin)
    f["first_hour_ret"] = lc[min(59, E - 1)] - lc[np.argmax(np.isfinite(lc))]
    f["first_hour_sol"] = v[:60].sum()
    f["first_hour_maxdd"] = float(np.nanmin(lo[:60]) / np.nanmax(hi[:60]))
    return f


def dense(g):
    n = int(g["mi"].max()) + 1
    out = {k: np.zeros(n) for k in ("vb", "vs", "nb", "ns", "na")}
    for k, col in (("vb", "sol_buy"), ("vs", "sol_sell"), ("nb", "n_buy"), ("ns", "n_sell"), ("na", "n_atomic")):
        out[k][g["mi"].to_numpy()] = g[col].to_numpy()
    for k, col in (("c", "p_close"), ("hi", "p_hi"), ("lo", "p_lo")):
        a = np.full(n, np.nan)
        a[g["mi"].to_numpy()] = g[col].to_numpy()
        out[k] = pd.Series(a).ffill().to_numpy()
    out["hi"] = np.where(np.isnan(out["hi"]), out["c"], out["hi"])
    out["lo"] = np.where(np.isnan(out["lo"]), out["c"], out["lo"])
    return out


def chart_all():
    res = []
    rows["E"] = ((rows["ts"] - rows["grad_ms"]) // 60_000).astype(int)
    by_pool = rows.groupby("pool")
    for f in sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet"))):
        b = pd.read_parquet(f)
        b = b[b["pool"].isin(pools)]
        for pool, g in b.groupby("pool"):
            arr = dense(g.sort_values("mi"))
            for idx, E in by_pool.get_group(pool)["E"].items():
                fe = chart_feats(arr, min(E, len(arr["c"])))
                fe["_idx"] = idx
                res.append(fe)
        print(os.path.basename(f), len(res), flush=True)
    return pd.DataFrame(res).set_index("_idx")


def flow_all():
    x = rows
    tx = x["buys_1h"] + x["sells_1h"]
    f = pd.DataFrame({"age_h": x["age_h"], "mc": np.log10(x["market_cap_usd"]), "liqmc": x["liquidity_usd"] / x["market_cap_usd"],
                      "volmc": x["volume_24h"] / x["market_cap_usd"], "vol1share": x["volume_1h"] / x["volume_24h"],
                      "c5m": x["price_change_5m"], "c1": x["price_change_1h"], "c6": x["price_change_6h"], "c24": x["price_change_24h"],
                      "buyshare_1h": x["buys_1h"] / tx, "buyers_1h": x["buyers_1h"], "sellers_1h": x["sellers_1h"],
                      "buyer_seller_ratio": (x["buyers_1h"] + 1) / (x["sellers_1h"] + 1), "topbuyer": x["top_buyer_share_1h"],
                      "idle_s": x["last_trade_s"]}, index=x.index)
    # change since the hour before, from all hourly rows of the coin (not just universe rows)
    a = d.sort_values(["mint", "h"])
    for col, name in (("buyers_1h", "buyers_chg"), ("volume_1h", "vol1h_chg"), ("market_cap_usd", "mc_chg")):
        prev = a.groupby("mint")[col].shift(1)
        f[name] = ((a[col] + 1) / (prev + 1)).reindex(x.index)
    return f


def wallet_all():
    p = pd.read_pickle(os.path.join(S, "pairs.pkl"))
    wc = pd.read_parquet(os.path.join(S, "w", "coins.parquet"))
    p["mint"] = p["coin"].map(wc.set_index("coin")["mint"])
    p["win"] = (p["roi"] > 1.5).astype("int8")
    p["big"] = (p["roi"] > 3).astype("int8")
    # each wallet's record by the day its coin's result was known (graduation + 3 days)
    p["known"] = p["grad_ms"] + 3 * 86_400_000
    rec = p[["wid", "known", "win", "big", "roi"]].sort_values(["wid", "known"])
    rec["n"] = 1
    rec["lroi"] = np.log(rec["roi"].clip(1e-3, 1e3))
    cum = rec.groupby("wid")[["n", "win", "big", "lroi"]].cumsum()
    rec = pd.concat([rec[["wid", "known"]], cum], axis=1)
    x = rows[["mint", "ts"]].reset_index()
    q = p[p["mint"].isin(set(x["mint"]))][["mint", "wid", "t_q", "sol_q"]]
    q = q.merge(x, on="mint")
    q = q[q["t_q"] < q["ts"]]
    q = q.sort_values("ts")
    rec = rec.sort_values("known")
    q = pd.merge_asof(q, rec.rename(columns={"known": "ts"}), on="ts", by="wid", direction="backward")
    q[["n", "win", "big", "lroi"]] = q[["n", "win", "big", "lroi"]].fillna(0)
    q["exp"] = q["n"] >= 5
    q["smart"] = q["exp"] & (q["win"] / q["n"].clip(lower=1) >= 0.5)
    q["smart_big"] = q["exp"] & (q["big"] >= 2)
    q["fresh"] = q["n"] == 0
    q["recent"] = q["t_q"] >= q["ts"] - 3_600_000
    g = q.groupby("index")
    f = pd.DataFrame({"w_buyers": g.size(), "w_sol": g["sol_q"].sum(), "w_top_share": g["sol_q"].max() / g["sol_q"].sum(),
                      "w_fresh_share": g["fresh"].mean(), "w_exp_share": g["exp"].mean(), "w_smart_n": g["smart"].sum(),
                      "w_smart_share": g["smart"].mean(), "w_smartbig_n": g["smart_big"].sum(),
                      "w_avg_lroi": g.apply(lambda z: (z["lroi"].sum() / z["n"].sum()) if z["n"].sum() else np.nan),
                      "w_recent_share": g["recent"].mean(),
                      "w_recent_smart": q[q["recent"]].groupby("index")["smart"].sum()})
    return f.reindex(rows.index)


def wallet_chunked(G, chunk=400):
    """wallet_all for many rows: the wallet records once, then the buyers before each row, a few hundred coins at a time."""
    global rows
    p = pd.read_pickle(os.path.join(S, "pairs.pkl"))
    wc = pd.read_parquet(os.path.join(S, "w", "coins.parquet"))
    p["mint"] = p["coin"].map(wc.set_index("coin")["mint"])
    p = p[["wid", "mint", "t_q", "sol_q", "grad_ms", "roi"]]
    p["known"] = p["grad_ms"] + 3 * 86_400_000
    rec = p[["wid", "known", "roi"]].sort_values(["wid", "known"])
    rec["n"] = 1
    rec["win"] = (rec["roi"] > 1.5).astype("int32")
    rec["big"] = (rec["roi"] > 3).astype("int32")
    rec["lroi"] = np.log(rec["roi"].clip(1e-3, 1e3)).astype("float32")
    rec = pd.concat([rec[["wid", "known"]], rec.groupby("wid")[["n", "win", "big", "lroi"]].cumsum()], axis=1).sort_values("known")
    mints = G["mint"].unique()
    p = p[p["mint"].isin(set(mints))][["mint", "wid", "t_q", "sol_q"]]
    out = []
    for i in range(0, len(mints), chunk):
        part = set(mints[i:i + chunk])
        rows = G[G["mint"].isin(part)][["mint", "ts"]]
        q = p[p["mint"].isin(part)]
        x = rows.reset_index()
        q = q.merge(x, on="mint")
        q = q[q["t_q"] < q["ts"]].sort_values("ts")
        q = pd.merge_asof(q, rec.rename(columns={"known": "ts"}), on="ts", by="wid", direction="backward")
        q[["n", "win", "big", "lroi"]] = q[["n", "win", "big", "lroi"]].fillna(0)
        q["exp"] = q["n"] >= 5
        q["smart"] = q["exp"] & (q["win"] / q["n"].clip(lower=1) >= 0.5)
        q["smart_big"] = q["exp"] & (q["big"] >= 2)
        q["fresh"] = q["n"] == 0
        q["recent"] = q["t_q"] >= q["ts"] - 3_600_000
        g = q.groupby("index")
        sn = g[["lroi", "n"]].sum()
        out.append(pd.DataFrame({"w_buyers": g.size(), "w_sol": g["sol_q"].sum(), "w_top_share": g["sol_q"].max() / g["sol_q"].sum(),
                                 "w_fresh_share": g["fresh"].mean(), "w_exp_share": g["exp"].mean(), "w_smart_n": g["smart"].sum(),
                                 "w_smart_share": g["smart"].mean(), "w_smartbig_n": g["smart_big"].sum(),
                                 "w_avg_lroi": sn["lroi"] / sn["n"].where(sn["n"] > 0), "w_recent_share": g["recent"].mean(),
                                 "w_recent_smart": q[q["recent"]].groupby("index")["smart"].sum()}))
        print("wallets", i, flush=True)
    return pd.concat(out).reindex(G.index)


def market_all():
    out = pd.DataFrame(index=rows.index)
    for s, name in (("BTCUSDT", "btc"), ("SOLUSDT", "sol")):
        k = [json.loads(l) for l in open(os.path.join(S, "mk", s + ".jsonl"))]
        t = np.array([r[0] for r in k]); c = np.array([float(r[4]) for r in k])
        i = np.searchsorted(t, rows["ts"].to_numpy(), side="right") - 2      # last fully closed hour
        i = i.clip(24, len(c) - 1)
        out[name + "_1h"] = c[i] / c[i - 1] - 1
        out[name + "_24h"] = c[i] / c[i - 24] - 1
    # meme market heat: graduations in the last 24 h; how the universe's coins of 2 to 3 days ago did after 6 h (known by then)
    gt = np.sort(d.drop_duplicates("mint")["grad_ms"].to_numpy())
    ts = rows["ts"].to_numpy()
    out["grads_24h"] = np.searchsorted(gt, ts) - np.searchsorted(gt, ts - 86_400_000)
    first = d[d["univ"] & d["eur_A"].notna()].drop_duplicates("mint")[["ts", "eur_A", "hit3"]].sort_values("ts")
    ft = first["ts"].to_numpy(); cs = np.cumsum(first["eur_A"].to_numpy()); ch = np.cumsum(first["hit3"].to_numpy())
    a, b = np.searchsorted(ft, ts - 3 * 86_400_000), np.searchsorted(ft, ts - 2 * 86_400_000)
    n = (b - a).clip(1)
    cs0, ch0 = np.r_[0, cs], np.r_[0, ch]
    out["regime_eur"] = (cs0[b] - cs0[a]) / n
    out["regime_hit3"] = (ch0[b] - ch0[a]) / n
    return out


if __name__ == "__main__":
    parts = [flow_all(), market_all(), wallet_all(), chart_all()]
    X = pd.concat(parts, axis=1)
    keep = ["mint", "pool", "ts", "grad_ms", "h", "gday", "day", "eur_A", "eur_hold", "hit3", "lose80", "zero", "gates", "lo6", "hi6"]
    out = pd.concat([rows[keep], X], axis=1)
    out.to_pickle(os.path.join(S, "feat.pkl"))
    print(out.shape)
    print(out.isna().mean().round(2).to_string())
