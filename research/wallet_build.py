"""Wallet data build (fake money only): who bought the graduated pump.fun coins of 10 August to 8 October 2026, and what a copy of
each buy would have made. For the pre-registered smart-wallet test (research/PREREG-WALLETS-2026-10-21.md). Same source and the
same cut of the swaps as history2 (research/history_build2.py: every PumpSwap swap of the graduated coins, 55 hours after each
graduation); "Data provided by [Slink21]. Pumpfun Solana Dataset (2026)." (CC BY 4.0). It runs in GitHub Actions
(history-build.yml with part 3, started by hand only). Nothing is bought, no wallet and no credential is used.

  meta  <out>                    as history_build2 (file list, graduations, names, SOL/USD)
  shard <meta> <i> <n> <out>     swap files i, i+n, ...: the one-minute bars as history_build2 and, per wallet and coin, what
                                 the wallet bought and sold in that file
  final <meta> <shards> <out>    the pairs joined over the files, the copies priced on the bars; the result goes to the branch
                                 "wallets"

A pair is one wallet and one coin with a qualifying buy: the wallet's first buy of the coin of at least MIN_BUY SOL, not in a
bundled (atomic) transaction, within BUY_H hours after the graduation. The copy of it buys at the last price D minutes after that
buy (D in DELAYS) and is priced like the history2 rows: hold (the last price 1.7 hours later), exit A (-30% stop, 11x target,
else sold after 6 hours), exit B (-20% stop, 3x target, else after 6 hours), the high over those 6 hours, all as multiples of the
copy's price in SOL. A stop sells at the low of the minute that hit it; a stop and a target in one minute count as the stop.
"""
import glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history_build2 as hb

MIN_BUY = 0.1              # SOL: a qualifying buy
BUY_H = 48                 # hours after the graduation in which a qualifying buy counts
KEEP_SOL = 0.05            # a wallet's swaps of a coin in one file below this (in and out together) are not kept (dust)
DELAYS = (1, 5, 15, 60)    # minutes from the wallet's buy to the copy
PATH_MIN = int(hb.PATH_H * 60)
HOLD_MIN = int(round(hb.EVAL_H * 60))
EXITS = (("a", 0.70, 11.0), ("b", 0.80, 3.0))
MIN, HOUR = hb.MIN, hb.HOUR


# --------------------------------------------------------------------------------------------------------------- shard

def pair_parts(trades, grad):
    """The kept swaps of one file -> one row per wallet and pool: what it bought and sold, and its first qualifying buy here."""
    import numpy as np, pandas as pd
    d = pd.concat(trades, ignore_index=True)
    d["sb"] = np.where(d["buy"], d["sol"], 0.0)
    d["tb"] = np.where(d["buy"], d["tok"], 0.0)
    d["ss"] = np.where(d["buy"], 0.0, d["sol"])
    d["ts"] = np.where(d["buy"], 0.0, d["tok"])
    q = d["buy"].to_numpy() & ~d["atomic"].to_numpy() & (d["sol"].to_numpy() >= MIN_BUY) & (
        d["t"].to_numpy() <= d["pool"].map(grad).to_numpy() + BUY_H * HOUR)
    p = d.groupby(["trader", "pool"], sort=False).agg(sol_in=("sb", "sum"), tok_in=("tb", "sum"), sol_out=("ss", "sum"),
                                                       tok_out=("ts", "sum"), n_buy=("buy", "sum"), n_sw=("t", "size")).reset_index()
    first = d[q].sort_values("t", kind="stable").drop_duplicates(["trader", "pool"], keep="first")
    first = first.assign(px_q=first["sol"] / first["tok"]).rename(columns={"t": "t_q", "sol": "sol_q"})[["trader", "pool", "t_q", "sol_q", "px_q"]]
    p = p.merge(first, on=["trader", "pool"], how="left")
    p = p[(p["sol_in"] + p["sol_out"] >= KEEP_SOL) | p["t_q"].notna()]
    p["n_sell"] = p["n_sw"] - p["n_buy"]
    return p.drop(columns=["n_sw"])


def shard(meta_dir, i, n, out):
    import pandas as pd
    i, n = int(i), int(n)
    os.makedirs(out, exist_ok=True)
    files = json.load(open(os.path.join(meta_dir, "swap_files.json")))[i::n]
    g = pd.read_parquet(os.path.join(meta_dir, "grads.parquet"))
    pools = set(g["pool"])
    grad = dict(zip(g["pool"], g["grad_ms"].astype("int64")))
    mints = dict(zip(g["pool"], g["mint"]))
    print("shard %d of %d: %d files, %.1f GB; %d pools" % (i, n, len(files), sum(f["size"] for f in files) / 1e9, len(pools)), flush=True)
    work = os.path.join(out, "dl")
    os.makedirs(work, exist_ok=True)
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(1)
    loc = lambda k: os.path.join(work, "f%d.parquet" % (k % 2))
    nxt = ex.submit(hb.fetch, files[0]["path"], loc(0)) if files else None
    t0 = time.time()
    for k, f in enumerate(files):
        size = nxt.result()
        here = loc(k)
        nxt = ex.submit(hb.fetch, files[k + 1]["path"], loc(k + 1)) if k + 1 < len(files) else None
        trades = []
        bars, _who, minutes, _usd, cnt = hb.cut_file(here, pools, grad, mints, trades)
        os.remove(here)
        stem = os.path.basename(f["path"]).rsplit(".", 1)[0]
        np_ = 0
        if bars is not None:
            bars.to_parquet(os.path.join(out, "bars_%s.parquet" % stem), index=False, compression="zstd")
            p = pair_parts(trades, grad)
            np_ = len(p)
            p.to_parquet(os.path.join(out, "pairs_%s.parquet" % stem), index=False, compression="zstd")
        pd.DataFrame({"m": list(minutes), "n": list(minutes.values())}).to_parquet(os.path.join(out, "minutes_%s.parquet" % stem), index=False)
        print("%s: %.2f GB, %d swaps, kept %d; %d wallet-pool parts (%d with a qualifying buy); %.0f s in all" % (
            stem, size / 1e9, cnt["rows"], cnt["kept"], np_, 0 if not np_ else int(p["t_q"].notna().sum()), time.time() - t0), flush=True)
    ex.shutdown()
    os.rmdir(work)


# --------------------------------------------------------------------------------------------------------------- final

def copies(m, close, hi, lo, ks):
    """For entries at bar-grid minutes ks of one pool (the copy buys at the close of minute k-1): the copy's price p0, the hold,
    exit A, exit B multiples and the 6-hour high. m: the pool's bar minutes (ms, sorted), close/hi/lo their prices (NaN: no
    priced swap). NaN where there is no price yet."""
    import numpy as np
    m0 = int(m[0])
    L = int((m[-1] - m0) // MIN) + 1
    idx = ((m - m0) // MIN).astype("int64")
    c = np.full(L, np.nan)
    c[idx] = close
    h = np.full(L, np.nan)
    h[idx] = hi
    w = np.full(L, np.nan)
    w[idx] = lo
    have = np.where(~np.isnan(c), np.arange(L), -1)
    np.maximum.accumulate(have, out=have)
    c = np.where(have >= 0, c[np.maximum(have, 0)], np.nan)          # a minute without a priced swap keeps the last price
    h = np.where(np.isnan(h), c, h)
    w = np.where(np.isnan(w), c, w)
    pad = PATH_MIN + HOLD_MIN + 2                                       # after the last bar the price stays where it was
    c = np.concatenate([c, np.full(pad, c[-1])])
    h = np.concatenate([h, np.full(pad, c[-1])])
    w = np.concatenate([w, np.full(pad, c[-1])])
    ks = np.asarray(ks, dtype="int64")
    i0 = np.minimum(ks - 1, L - 1)
    ok = i0 >= 0
    p0 = np.where(ok, c[np.maximum(i0, 0)], np.nan)
    s = np.clip(ks, 0, L)                                               # the path: bars from minute k on, 6 hours
    hold = c[np.minimum(ks + HOLD_MIN - 1, L - 1 + pad - 1).clip(0)] / p0
    out = {"p0": p0, "hold": hold}
    cols = np.arange(PATH_MIN)
    res = {k: np.full(len(ks), np.nan) for k in ("a", "b", "hi6")}
    for a in range(0, len(ks), 20000):
        z = min(len(ks), a + 20000)
        g = s[a:z, None] + cols[None, :]
        q = p0[a:z, None]
        H, W = h[g] / q, w[g] / q
        res["hi6"][a:z] = np.nanmax(H, axis=1) if H.size else np.nan
        end = c[s[a:z] + PATH_MIN - 1] / p0[a:z]
        for name, stop, tp in EXITS:
            hs, ht = W <= stop, H >= tp
            fs = np.where(hs.any(1), hs.argmax(1), PATH_MIN)
            ft = np.where(ht.any(1), ht.argmax(1), PATH_MIN)
            fill = W[np.arange(z - a), np.minimum(fs, PATH_MIN - 1)]
            res[name][a:z] = np.where((fs < PATH_MIN) & (fs <= ft), fill, np.where(ft < PATH_MIN, tp, end))
    out.update(res)
    out["last"] = c[L - 1]
    return out


def final(meta_dir, shard_dir, out):
    import numpy as np, pandas as pd, pyarrow as pa, pyarrow.compute as pc, pyarrow.parquet as pq
    dst = os.path.join(out, "wallets")
    os.makedirs(os.path.join(dst, "pairs"), exist_ok=True)
    find = lambda pat: sorted(glob.glob(os.path.join(shard_dir, "**", pat), recursive=True))
    g = pd.read_parquet(os.path.join(meta_dir, "grads.parquet")).sort_values("grad_ms").reset_index(drop=True)
    g["coin"] = np.arange(len(g), dtype="int32")
    coin_of = dict(zip(g["pool"], g["coin"]))
    gap_m = hb.gap_minutes(find)
    t0 = time.time()

    # the wallet-pool parts of all files as one table, wallets as numbers
    tab = pa.concat_tables([pq.read_table(f) for f in find("pairs_*.parquet")], promote_options="default")
    enc = pc.dictionary_encode(tab.column("trader")).combine_chunks()
    addr = enc.dictionary.to_pylist()
    p = tab.drop(["trader"]).to_pandas()
    p["wid"] = enc.indices.to_numpy(zero_copy_only=False).astype("int64")
    del tab, enc
    p["coin"] = p["pool"].map(coin_of)
    p = p.dropna(subset=["coin"]).drop(columns=["pool"])
    p["coin"] = p["coin"].astype("int64")
    print("parts: %d rows, %d wallets (%.0f s)" % (len(p), len(addr), time.time() - t0), flush=True)
    p["key"] = p["wid"] * len(g) + p["coin"]
    q = p[p["t_q"].notna()].sort_values("t_q", kind="stable").drop_duplicates("key", keep="first")[["key", "t_q", "sol_q", "px_q"]]
    s = p.groupby("key", sort=False)[["sol_in", "tok_in", "sol_out", "tok_out", "n_buy", "n_sell"]].sum()
    pairs = q.merge(s, left_on="key", right_index=True, how="left")
    del p, q, s
    pairs["wid"] = pairs["key"] // len(g)
    pairs["coin"] = (pairs["key"] % len(g)).astype("int32")
    pairs = pairs.drop(columns=["key"])
    pairs["t_q"] = pairs["t_q"].astype("int64")
    pairs["grad_ms"] = g["grad_ms"].to_numpy()[pairs["coin"].to_numpy()].astype("int64")
    print("pairs: %d (%d wallets, %d coins) (%.0f s)" % (len(pairs), pairs["wid"].nunique(), pairs["coin"].nunique(), time.time() - t0), flush=True)

    # the copies, priced on the bars
    bars = hb.merged_bars(find)
    bars["coin"] = bars["pool"].map(coin_of)
    bars = bars.dropna(subset=["coin"])
    print("bars: %d for %d pools (%.0f s)" % (len(bars), bars["pool"].nunique(), time.time() - t0), flush=True)
    pairs = pairs.sort_values(["coin", "t_q"]).reset_index(drop=True)
    cols = {"%s%d" % (k, d): np.full(len(pairs), np.nan, dtype="float32") for d in DELAYS for k in ("p", "h", "a", "b", "x")}
    last = np.full(len(pairs), np.nan)
    bc = bars["coin"].to_numpy().astype("int64")
    bstart = np.r_[0, np.nonzero(bc[1:] != bc[:-1])[0] + 1, len(bc)]
    bpos = {int(bc[a]): (a, z) for a, z in zip(bstart[:-1], bstart[1:])}
    pc_ = pairs["coin"].to_numpy()
    pstart = np.r_[0, np.nonzero(pc_[1:] != pc_[:-1])[0] + 1, len(pc_)]
    bm, bcl, bhi, blo = (bars[k].to_numpy() for k in ("m", "p_close", "p_hi", "p_lo"))
    tq = pairs["t_q"].to_numpy()
    for a, z in zip(pstart[:-1], pstart[1:]):
        r = bpos.get(int(pc_[a]))
        if r is None:
            continue
        m = bm[r[0]:r[1]].astype("int64")
        m0 = int(m[0])
        need = {d: (tq[a:z] + d * MIN - m0) // MIN for d in DELAYS}       # the copy's minute on the pool's bar grid
        uk, inv = np.unique(np.concatenate(list(need.values())), return_inverse=True)
        o = copies(m, bcl[r[0]:r[1]].astype("float64"), bhi[r[0]:r[1]].astype("float64"), blo[r[0]:r[1]].astype("float64"), uk)
        for j, d in enumerate(DELAYS):
            ii = inv[j * (z - a):(j + 1) * (z - a)]
            for k, src in (("p", "p0"), ("h", "hold"), ("a", "a"), ("b", "b"), ("x", "hi6")):
                cols["%s%d" % (k, d)][a:z] = o[src][ii]
        last[a:z] = o["last"]
    del bars, bm, bcl, bhi, blo, bc
    for k in list(cols):
        pairs[k] = cols.pop(k)
    print("copies priced (%.0f s)" % (time.time() - t0), flush=True)
    # outages: a copy whose buy-to-sell window touches one is flagged
    lo_i = np.searchsorted(gap_m, tq, side="left")
    for name, span in (("g1", HOLD_MIN), ("g6", PATH_MIN)):
        pairs[name] = np.searchsorted(gap_m, tq + (max(DELAYS) + span) * MIN, side="right") > lo_i
    # the wallet's own result on the coin: SOL out plus the tokens it still held at the last price, over SOL in
    left = np.maximum(pairs["tok_in"] - pairs["tok_out"], 0.0)
    pairs["roi"] = ((pairs["sol_out"] + left * last) / pairs["sol_in"]).astype("float32")
    pairs = pairs.drop(columns=["tok_in", "tok_out"])
    for k in ("sol_q", "px_q", "sol_in", "sol_out"):
        pairs[k] = pairs[k].astype("float32")
    for k in ("n_buy", "n_sell"):
        pairs[k] = pairs[k].astype("int32")
    pairs["wid"] = pairs["wid"].astype("int32")

    # wallets with 3 pairs or more get their address (the others are a number only)
    nw = pairs.groupby("wid").size()
    keep = nw[nw >= 3]
    wl = pd.DataFrame({"wid": keep.index.astype("int32"), "address": [addr[int(w)] for w in keep.index], "pairs": keep.values.astype("int32")})
    wl.to_parquet(os.path.join(dst, "wallets.parquet"), compression="zstd", index=False)
    del wl, addr
    print("wallets: %d with a pair, %d with 3 or more; pairs per wallet median %.0f, 99%% %.0f, max %d" % (
        len(nw), len(keep), nw.median(), nw.quantile(0.99), nw.max()), flush=True)
    # the pairs are sorted by coin, and the coins are numbered in graduation order
    day = (pairs["grad_ms"].to_numpy() // (24 * HOUR)).astype("int64")
    cuts = np.r_[0, np.nonzero(day[1:] != day[:-1])[0] + 1, len(day)]
    for a0, z0 in zip(cuts[:-1], cuts[1:]):    # GitHub takes no file over 100 MB: a day in parts of at most 1.5M pairs
        d_ = time.strftime("%Y-%m-%d", time.gmtime(int(day[a0]) * 86400))
        for j, a in enumerate(range(a0, z0, 1_500_000)):
            pairs.iloc[a:min(z0, a + 1_500_000)].to_parquet(os.path.join(dst, "pairs", "pairs_%s_%d.parquet" % (d_, j)), compression="zstd", index=False)
    sizes = [os.path.getsize(f) for f in glob.glob(os.path.join(dst, "pairs", "*.parquet"))]
    print("pairs/: %d days, %.0f MB, largest %.1f MB" % (len(sizes), sum(sizes) / 1e6, max(sizes) / 1e6))
    g[["coin", "mint", "pool", "grad_ms", "symbol", "token_name"]].to_parquet(os.path.join(dst, "coins.parquet"), compression="zstd", index=False)
    np.save(os.path.join(dst, "gap_minutes.npy"), gap_m)
    summ = {"source": "https://huggingface.co/datasets/%s" % hb.SRC, "licence": "CC-BY-4.0", "attribution": hb.ATTRIBUTION,
            "pairs": len(pairs), "wallets": int(len(nw)), "wallets_3plus": int(len(keep)), "coins": int(pairs["coin"].nunique()),
            "min_buy_sol": MIN_BUY, "buy_h": BUY_H, "delays_min": list(DELAYS), "hold_min": HOLD_MIN, "path_min": PATH_MIN,
            "columns": list(pairs.columns)}
    json.dump(summ, open(os.path.join(dst, "summary.json"), "w"), indent=1)
    open(os.path.join(dst, "README.md"), "w").write(
        "# Wallet pairs for the Meme-Bot's smart-wallet test (fake money only)\n\n%s\n\nDerived (changed) from that data set by "
        "research/wallet_build.py: for every wallet and graduated pump.fun coin of 10 August to 8 October 2026, the wallet's first "
        "PumpSwap buy of at least %.1f SOL within %d hours after the graduation, its SOL in and out on the coin, and what a copy of "
        "that buy %s minutes later would have made (hold 1.7 h: hD; exit A: aD; exit B: bD; the 6-hour high: xD; the copy's price: "
        "pD; multiples in SOL). wallets.parquet names the wallets with 3 pairs or more.\n" % (
            hb.ATTRIBUTION, MIN_BUY, BUY_H, "/".join(str(d) for d in DELAYS)))
    print(json.dumps({k: v for k, v in summ.items() if k != "columns"}))
    ok = pairs[~pairs["g6"] & pairs["p5"].notna()]
    print("copies at 5 min without outages: %d; hold median %.3f, under 0.02x %.1f%%; 3x within 6 h %.1f%%" % (
        len(ok), ok["h5"].median(), 100 * (ok["h5"] < 0.02).mean(), 100 * (ok["x5"] >= 3).mean()))
    print(pairs.sample(min(len(pairs), 500_000), random_state=7).describe(percentiles=[0.1, 0.5, 0.9]).T.to_string()[:12000])


def main():
    cmd, a = sys.argv[1], sys.argv[2:]
    {"meta": hb.meta, "shard": shard, "final": final}[cmd](*a)


if __name__ == "__main__":
    main()
