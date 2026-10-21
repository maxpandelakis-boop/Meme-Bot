"""Long-history data build, part 2 (fake money only): the graduated pump.fun coins of 10 August to 8 October 2026, the bot's own
period, from every PumpSwap swap in the CC-BY-4.0 Pumpfun dataset on Hugging Face (Slinky21/Pumpfun_v2_dataset; "Data provided by
[Slink21]. Pumpfun Solana Dataset (2026)."). It turns them into rows like part 1's (research/history_build.py): a coin at whole
hours after its graduation with the numbers a screener showed then (price, market cap, liquidity, volume, buys and sells, buyers,
price changes) and what the price did afterwards (1.7 hours later, as the 2h profile measures, and the path over 6 hours for exit
rules). It runs in GitHub Actions (history-build.yml with part 2, started by hand only) because the cloud session cannot reach
Hugging Face. Nothing is bought, no wallet and no credential is used.

Three steps, so the 258 GB of swaps can be shared out over several runners:
  meta  <out>                    file list, graduations (mint, pool, start reserves), names, SOL/USD by hour
  shard <meta> <i> <n> <out>     swap files i, i+n, ...: one at a time, downloaded, cut to the graduated coins' pools as
                                 one-minute bars, then deleted
  final <meta> <shards> <out>    the bars joined into the hourly rows; the result goes to the branch "history2"
SRC_DIR=<dir> reads the files from a local copy instead of Hugging Face (for the self test).

How the numbers are made (none of them is in the data as such):
  price      SOL per token of each swap (the SOL side over the token side); a bar's open, close, high and low use swaps of at
             least 0.01 SOL, so dust swaps cannot fake a spike
  mc         price times the fixed pump.fun supply of one billion tokens, in USD
  liquidity  2 x the pool's SOL side, from the constant product the pool started with: SOL side = sqrt(sol0 x tok0 x price);
             fees and any liquidity moves are left out
  rug        the first bar whose close is under 1% of the coin's first PumpSwap price
  gaps       minutes in which the whole data set holds (almost) no swap of any coin: an outage of the recorder, not a quiet
             market. Rows whose windows touch one are flagged (gap_pre, gap_1, gap_6) so a test can leave them out.
"""
import concurrent.futures, glob, json, math, os, shutil, sys, time, urllib.parse, urllib.request

SRC = "Slinky21/Pumpfun_v2_dataset"
ATTRIBUTION = "Data provided by [Slink21]. Pumpfun Solana Dataset (2026). https://huggingface.co/datasets/Slinky21/Pumpfun_v2_dataset (CC BY 4.0)"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SUPPLY = 1_000_000_000.0   # every pump.fun coin
AGES_H = range(1, 49)      # sample points: whole hours after the graduation
EVAL_H = 1.7               # the 2h profile's price check (memebot PROFILES["2h"]["EVAL_H"])
PATH_H = 6.0               # the paper account's time limit (memebot HOLD_MAX_H)
KEEP_H = AGES_H[-1] + PATH_H + 1.0      # bars kept after a graduation
MIN_SOL = 0.01             # swaps smaller than this do not set prices
BARS_MAX_MB = 500         # the one-minute bars go to the branch only below this size
MIN = 60_000
HOUR = 3_600_000
SWAP_COLS = ["block_time", "dex", "trader", "pool", "input_mint", "output_mint", "input_amount", "output_amount",
             "input_decimals", "output_decimals", "is_atomic"]
UA = {"User-Agent": "memebot-history-build"}


def get_json(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, Accept="application/json")), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("get %s failed (%s), retry %d" % (url[:120], type(e).__name__, i + 1))
            time.sleep(10 * (i + 1))
    raise SystemExit("could not get " + url)


def fetch(path, out):
    """One data set file to the local path out (or a hard link to the local copy under SRC_DIR)."""
    if os.environ.get("SRC_DIR"):
        shutil.copyfile(os.path.join(os.environ["SRC_DIR"], path), out)
        return os.path.getsize(out)
    url = "https://huggingface.co/datasets/%s/resolve/main/%s" % (SRC, urllib.parse.quote(path))
    for i in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, open(out, "wb") as f:
                n = 0
                while True:
                    b = r.read(8 << 20)
                    if not b:
                        break
                    f.write(b)
                    n += len(b)
            return n
        except Exception as e:
            print("fetch %s failed (%s %s), retry %d" % (path, type(e).__name__, str(e)[:120], i + 1), flush=True)
            time.sleep(15 * (i + 1))
    raise SystemExit("could not fetch " + path)


def ms_of(arr):
    """A pyarrow timestamp array as int64 epoch milliseconds, whatever its unit."""
    import pyarrow as pa, pyarrow.compute as pc
    unit = {"s": 1000, "ms": 1, "us": 0.001, "ns": 0.000001}[arr.type.unit]
    v = pc.cast(arr, pa.int64()).to_numpy(zero_copy_only=False)
    return (v * unit).astype("int64") if unit >= 1 else (v // int(round(1 / unit))).astype("int64")


# ---------------------------------------------------------------------------------------------------------------- meta

def list_files():
    if os.environ.get("SRC_DIR"):
        base = os.environ["SRC_DIR"]
        return [{"path": os.path.relpath(p, base), "size": os.path.getsize(p)} for p in sorted(glob.glob(os.path.join(base, "**", "*.parquet"), recursive=True))]
    js = get_json("https://huggingface.co/api/datasets/%s?blobs=true" % SRC)
    return [{"path": s["rfilename"], "size": s.get("size") or 0} for s in js.get("siblings") or [] if s.get("rfilename", "").endswith(".parquet")]


def table_of(path):
    parts = path.split("/")
    return parts[-2] if len(parts) > 1 else ""


def solusd_coinbase(t0, t1):
    """Hourly SOL/USD closes from Coinbase's public candles (no key), {hour start ms: close}."""
    out, s = {}, t0 - t0 % HOUR
    while s < t1:
        e = min(t1, s + 290 * HOUR)
        url = "https://api.exchange.coinbase.com/products/SOL-USD/candles?granularity=3600&start=%s&end=%s" % (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s / 1000)), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e / 1000)))
        try:
            for row in get_json(url, tries=3):
                out[int(row[0]) * 1000] = float(row[4])
        except SystemExit:
            print("coinbase candles missing for %s" % url)
        s = e
        time.sleep(0.5)
    return out


def meta(out):
    import pandas as pd, pyarrow.parquet as pq
    os.makedirs(out, exist_ok=True)
    files = list_files()
    by = {}
    for f in files:
        by.setdefault(table_of(f["path"]), []).append(f)
    for k, v in sorted(by.items()):
        print("table %-10s %4d files %8.1f GB" % (k, len(v), sum(f["size"] for f in v) / 1e9))
    swaps = sorted(by.get("swap", []), key=lambda f: f["path"])
    json.dump(swaps, open(os.path.join(out, "swap_files.json"), "w"), indent=0)

    tmp = os.path.join(out, "tmp.parquet")
    grads, names = [], []
    for f in sorted(by.get("graduate", []), key=lambda f: f["path"]):
        fetch(f["path"], tmp)
        t = pq.read_table(tmp, columns=["block_time", "mint", "pool", "mint_amount", "sol_amount", "pool_migration_fee"])
        d = t.drop(["block_time"]).to_pandas()
        d["grad_ms"] = ms_of(t.column("block_time").combine_chunks())
        grads.append(d)
    for f in sorted(by.get("create", []), key=lambda f: f["path"]):
        fetch(f["path"], tmp)
        t = pq.read_table(tmp, columns=["block_time", "mint", "symbol", "token_name", "creator"])
        d = t.drop(["block_time"]).to_pandas()
        d["created_ms"] = ms_of(t.column("block_time").combine_chunks())
        names.append(d)
    if os.path.exists(tmp):
        os.remove(tmp)
    g = pd.concat(grads, ignore_index=True).sort_values("grad_ms").drop_duplicates("mint", keep="first").drop_duplicates("pool", keep="first")
    print("graduations: %d rows, %d mints, %d pools, %s to %s UTC" % (sum(len(x) for x in grads), g["mint"].nunique(), g["pool"].nunique(),
          pd.to_datetime(g["grad_ms"].min(), unit="ms"), pd.to_datetime(g["grad_ms"].max(), unit="ms")))
    g["sol0"] = g["sol_amount"] / 1e9
    g["tok0"] = g["mint_amount"] / 1e6
    print("start reserves (median): %.2f SOL, %.0f tokens, migration fee %.3f SOL; start price %.3g SOL per token" % (
        g["sol0"].median(), g["tok0"].median(), g["pool_migration_fee"].median() / 1e9, (g["sol0"] / g["tok0"]).median()))
    if names:
        n = pd.concat(names, ignore_index=True).drop_duplicates("mint", keep="first")
        g = g.merge(n, on="mint", how="left")
        print("names found for %d of %d graduated coins" % (int(g["symbol"].notna().sum()), len(g)))
    g.to_parquet(os.path.join(out, "grads.parquet"), index=False)
    sol = {} if os.environ.get("SRC_DIR") else solusd_coinbase(int(g["grad_ms"].min()) - 2 * 24 * HOUR, int(g["grad_ms"].max()) + 4 * 24 * HOUR)
    pd.DataFrame({"hour_ms": list(sol), "usd": list(sol.values())}).sort_values("hour_ms").to_parquet(os.path.join(out, "solusd.parquet"), index=False)
    print("SOL/USD hours from Coinbase: %d%s" % (len(sol), (", %.2f to %.2f" % (min(sol.values()), max(sol.values()))) if sol else ""))


# --------------------------------------------------------------------------------------------------------------- shard

def cut_file(local, pools, grad, mints):
    """One swap file -> (one-minute bars of the graduated pools, buyers by age hour, swaps per minute over the whole data set,
    SOL/USD minute prices from SOL-USDC swaps, counts for the log)."""
    import numpy as np, pandas as pd, pyarrow as pa, pyarrow.compute as pc, pyarrow.parquet as pq
    pf = pq.ParquetFile(local)
    pool_set = pa.array(sorted(pools))
    keep, minutes, usd, cnt = [], {}, [], {"rows": 0, "kept": 0, "dex": {}, "nosol": 0, "wrongmint": 0, "late": 0}
    for b in pf.iter_batches(batch_size=1 << 20, columns=SWAP_COLS):
        cnt["rows"] += b.num_rows
        tms = ms_of(b.column("block_time"))
        mi, c = np.unique(tms // MIN, return_counts=True)
        for m, k in zip(mi.tolist(), c.tolist()):
            minutes[m] = minutes.get(m, 0) + k
        for v in pc.value_counts(b.column("dex")).to_pylist():
            cnt["dex"][str(v["values"])] = cnt["dex"].get(str(v["values"]), 0) + v["counts"]
        # SOL in dollars from the data itself, as a check on the Coinbase hours
        im, om = b.column("input_mint"), b.column("output_mint")
        su = pc.or_(pc.and_(pc.equal(im, WSOL), pc.equal(om, USDC)), pc.and_(pc.equal(im, USDC), pc.equal(om, WSOL)))
        if pc.any(su).as_py():
            u = b.filter(su).to_pandas()
            u["t"] = tms[su.to_numpy(zero_copy_only=False)]
            sol_in = u["input_mint"] == WSOL
            sol = np.where(sol_in, u["input_amount"], u["output_amount"]) / 1e9
            dol = np.where(sol_in, u["output_amount"], u["input_amount"]) / 1e6
            ok = sol >= 0.1
            usd.append(pd.DataFrame({"m": u["t"][ok] // MIN, "p": dol[ok] / sol[ok]}))
        sel = pc.is_in(b.column("pool"), value_set=pool_set)
        if not pc.any(sel).as_py():
            continue
        d = b.filter(sel).to_pandas().drop(columns=["block_time", "dex"])
        d["t"] = tms[sel.to_numpy(zero_copy_only=False)]
        keep.append(d)
    if not keep:
        return None, None, minutes, usd, cnt
    d = pd.concat(keep, ignore_index=True)
    buy = d["input_mint"] == WSOL
    sell = d["output_mint"] == WSOL
    cnt["nosol"] = int((~buy & ~sell).sum())
    d = d[buy | sell].copy()
    buy = (d["input_mint"] == WSOL).to_numpy()
    d["buy"] = buy
    d["sol"] = np.where(buy, d["input_amount"], d["output_amount"]) / 1e9
    tok_amt = np.where(buy, d["output_amount"], d["input_amount"]).astype("float64")
    tok_dec = np.where(buy, d["output_decimals"], d["input_decimals"]).astype("float64")
    d["tok"] = tok_amt / np.power(10.0, tok_dec)
    tok_mint = np.where(buy, d["output_mint"], d["input_mint"])
    right = tok_mint == d["pool"].map(mints).to_numpy()
    cnt["wrongmint"] = int((~right).sum())
    d = d[right & (d["tok"].to_numpy() > 0)]
    gm = d["pool"].map(grad).to_numpy()
    late = d["t"].to_numpy() > gm + int(KEEP_H * HOUR)
    cnt["late"] = int(late.sum())
    d = d[~late].sort_values(["pool", "t"], kind="stable")
    cnt["kept"] = len(d)
    d["px"] = np.where(d["sol"] >= MIN_SOL, d["sol"] / d["tok"], np.nan)
    d["m"] = d["t"] // MIN * MIN
    d["sb"] = np.where(d["buy"], d["sol"], 0.0)
    d["ss"] = np.where(d["buy"], 0.0, d["sol"])
    d["atomic"] = d["is_atomic"].fillna(False).astype(bool)
    gb = d.groupby(["pool", "m"], sort=False)
    bars = gb.agg(t_first=("t", "first"), t_last=("t", "last"), p_open=("px", "first"), p_close=("px", "last"), p_hi=("px", "max"),
                  p_lo=("px", "min"), sol_buy=("sb", "sum"), sol_sell=("ss", "sum"), n_buy=("buy", "sum"), n_swap=("t", "size"),
                  n_atomic=("atomic", "sum")).reset_index()
    bars["n_sell"] = bars["n_swap"] - bars["n_buy"]
    bars = bars.drop(columns=["n_swap"])
    # buyers per hour of age (hour 0 is the first hour after the graduation), and the biggest buyer's share of the buying
    d["ah"] = (d["t"] - d["pool"].map(grad)) // HOUR
    bt = d[d["buy"]].groupby(["pool", "ah", "trader"], sort=False)["sol"].sum().reset_index()
    who = bt.groupby(["pool", "ah"]).agg(buyers=("trader", "size"), buy_sol=("sol", "sum"), top_buy=("sol", "max")).reset_index()
    st = d[~d["buy"]].groupby(["pool", "ah"])["trader"].nunique().rename("sellers").reset_index()
    who = who.merge(st, on=["pool", "ah"], how="outer")
    return bars, who, minutes, usd, cnt


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
    pool_ex = concurrent.futures.ThreadPoolExecutor(1)
    loc = lambda k: os.path.join(work, "f%d.parquet" % (k % 2))
    nxt = pool_ex.submit(fetch, files[0]["path"], loc(0)) if files else None
    t0 = time.time()
    for k, f in enumerate(files):
        size = nxt.result()
        here = loc(k)
        nxt = pool_ex.submit(fetch, files[k + 1]["path"], loc(k + 1)) if k + 1 < len(files) else None
        t1 = time.time()
        bars, who, minutes, usd, cnt = cut_file(here, pools, grad, mints)
        os.remove(here)
        stem = os.path.basename(f["path"]).rsplit(".", 1)[0]
        if bars is not None:
            bars.to_parquet(os.path.join(out, "bars_%s.parquet" % stem), index=False, compression="zstd")
            who.to_parquet(os.path.join(out, "who_%s.parquet" % stem), index=False, compression="zstd")
        pd.DataFrame({"m": list(minutes), "n": list(minutes.values())}).to_parquet(os.path.join(out, "minutes_%s.parquet" % stem), index=False)
        if usd:
            pd.concat(usd).groupby("m")["p"].median().reset_index().to_parquet(os.path.join(out, "usd_%s.parquet" % stem), index=False)
        mn, mx = (min(minutes), max(minutes)) if minutes else (0, 0)
        print("%s: %.2f GB, %d swaps (%s to %s), kept %d in %d bars; no SOL side %d, other mint %d, too late %d; dex %s; %.0f s (%.0f s in all)" % (
            stem, size / 1e9, cnt["rows"], pd.to_datetime(mn * MIN, unit="ms"), pd.to_datetime(mx * MIN, unit="ms"), cnt["kept"],
            0 if bars is None else len(bars), cnt["nosol"], cnt["wrongmint"], cnt["late"], json.dumps(cnt["dex"])[:300], time.time() - t1,
            time.time() - t0), flush=True)
    pool_ex.shutdown()
    os.rmdir(work)


# --------------------------------------------------------------------------------------------------------------- final

def last_at(m_end, x):
    """Index of the last bar that ended at or before x (m_end sorted), -1 if none."""
    import numpy as np
    return int(np.searchsorted(m_end, x, side="right")) - 1


def coin_rows(c, b, solusd, gaps, who):
    """The hourly rows of one graduated coin from its bars b (sorted by minute)."""
    import numpy as np
    m = b["m"].to_numpy()
    end = m + MIN
    close = b["p_close"].to_numpy()
    # a bar without a priced swap (only dust) keeps the last price
    if np.isnan(close).any():
        idx = np.where(~np.isnan(close), np.arange(len(close)), -1)
        np.maximum.accumulate(idx, out=idx)
        close = np.where(idx >= 0, close[np.maximum(idx, 0)], np.nan)
    hi = np.where(np.isnan(b["p_hi"].to_numpy()), close, b["p_hi"].to_numpy())
    lo = np.where(np.isnan(b["p_lo"].to_numpy()), close, b["p_lo"].to_numpy())
    vol = (b["sol_buy"] + b["sol_sell"]).to_numpy()
    cvol = np.concatenate([[0.0], np.cumsum(vol)])
    nb = np.concatenate([[0], np.cumsum(b["n_buy"].to_numpy())])
    ns = np.concatenate([[0], np.cumsum(b["n_sell"].to_numpy())])
    na = np.concatenate([[0], np.cumsum(b["n_atomic"].to_numpy())])
    first = next((p for p in b["p_open"].to_numpy() if p == p), None)
    if not first:
        return []
    g = int(c["grad_ms"])
    k = float(c["sol0"]) * float(c["tok0"])
    rug = np.nonzero(close < 0.01 * first)[0]
    rug_ms = int(end[rug[0]]) if len(rug) else None
    cum = lambda arr, x: arr[int(np.searchsorted(end, x, side="right"))]
    rows = []
    for h in AGES_H:
        x = g + h * HOUR
        i = last_at(end, x)
        if i < 0 or not (close[i] > 0):
            continue
        p0, usd = close[i], solusd(x)
        if not usd:
            continue
        rec = {"mint": c["mint"], "pool": c["pool"], "symbol": c.get("symbol"), "name": c.get("token_name"), "h": h, "ts": x, "grad_ms": g,
               "age_h": float(h), "last_trade_s": round((x - int(b["t_last"].iat[i])) / 1000.0), "sol_usd": usd,
               "price_sol": p0, "price_usd": p0 * usd, "market_cap_usd": p0 * SUPPLY * usd, "fdv": p0 * SUPPLY * usd,
               "liquidity_usd": 2.0 * math.sqrt(k * p0) * usd if k > 0 else None}
        for w, name in ((5 * MIN, "5m"), (HOUR, "1h"), (6 * HOUR, "6h"), (24 * HOUR, "24h")):
            a = x - w
            rec["volume_" + name] = (cum(cvol, x) - cum(cvol, a)) * usd
            rec["buys_" + name] = int(cum(nb, x) - cum(nb, a))
            rec["sells_" + name] = int(cum(ns, x) - cum(ns, a))
            j = last_at(end, a)
            ref = close[j] if j >= 0 else first     # a window that starts before the pool: since the pool's first price
            rec["price_change_" + name] = (p0 / ref - 1.0) * 100.0 if ref > 0 else None
        rec["atomic_1h"] = int(cum(na, x) - cum(na, x - HOUR))
        wr = who.get(h - 1)
        rec["buyers_1h"], rec["sellers_1h"], rec["top_buyer_share_1h"] = (
            (int(wr[0]), int(wr[1]), float(wr[2])) if wr is not None else (0, 0, None))
        x1 = x + EVAL_H * HOUR
        j = last_at(end, x1)
        rec["px1"] = float(close[j]) * solusd(x1) if j >= 0 and close[j] > 0 and solusd(x1) else None
        rec["px1_sol"] = float(close[j]) if j >= 0 else None
        rec["mult1"] = float(close[j] / p0) if j >= 0 else None      # in SOL: the coin's own move, without SOL's
        rec["dt1_s"] = round((x1 - int(b["t_last"].iat[j])) / 1000.0) if j >= 0 else None
        rec["liq1"] = 2.0 * math.sqrt(k * close[j]) * (solusd(x1) or usd) if j >= 0 and k > 0 else None
        rec["rug_ms"] = rug_ms
        rec["rug_by_1"] = bool(rug_ms is not None and x < rug_ms <= x1)
        s, e = int(np.searchsorted(m, x)), int(np.searchsorted(m, x + PATH_H * HOUR))
        if e > s:
            ph, pl, tk = hi[s:e] / p0, lo[s:e] / p0, (m[s:e] + MIN - x) / 60000.0
            rec.update(hi6=float(np.nanmax(ph)), lo6=float(np.nanmin(pl)), n6=e - s, last6=float(close[e - 1] / p0),
                       last6_dt_s=round((int(b["t_last"].iat[e - 1]) - x) / 1000.0))
            for name, thr in (("stop20", 0.80), ("stop30", 0.70)):
                q = np.nonzero(pl <= thr)[0]
                rec[name + "_min"] = float(tk[q[0]]) if len(q) else None
                rec[name + "_x"] = float(pl[q[0]]) if len(q) else None
            for name, thr in (("tp2", 2.0), ("tp3", 3.0), ("tp11", 11.0)):
                q = np.nonzero(ph >= thr)[0]
                rec[name + "_min"] = float(tk[q[0]]) if len(q) else None
        else:
            rec.update(hi6=None, lo6=None, n6=0, last6=1.0, last6_dt_s=None)
            for name in ("stop20_min", "stop20_x", "stop30_min", "stop30_x", "tp2_min", "tp3_min", "tp11_min"):
                rec[name] = None
        rec["gap_pre"] = gaps(x - HOUR, x)
        rec["gap_1"] = gaps(x, x1)
        rec["gap_6"] = gaps(x, x + PATH_H * HOUR)
        rows.append(rec)
    return rows


def final(meta_dir, shard_dir, out):
    import numpy as np, pandas as pd
    hist = os.path.join(out, "history2")
    os.makedirs(os.path.join(hist, "bars"), exist_ok=True)
    g = pd.read_parquet(os.path.join(meta_dir, "grads.parquet"))
    find = lambda pat: sorted(glob.glob(os.path.join(shard_dir, "**", pat), recursive=True))
    # recorder outages: minutes with almost no swap of any coin
    mins = pd.concat([pd.read_parquet(f) for f in find("minutes_*.parquet")]).groupby("m")["n"].sum()
    full = pd.Series(0, index=pd.RangeIndex(int(mins.index.min()), int(mins.index.max()) + 1)).add(mins, fill_value=0)
    base = full.rolling(24 * 60, center=True, min_periods=60).median()
    gap_m = full.index[(full < 0.1 * base) | (full == 0)].to_numpy() * MIN
    print("swaps per minute: median %.0f; %d of %d minutes are gaps (%.2f%%)" % (full.median(), len(gap_m), len(full), 100.0 * len(gap_m) / len(full)))
    runs = np.split(gap_m, np.nonzero(np.diff(gap_m) > MIN)[0] + 1) if len(gap_m) else []
    for r in sorted(runs, key=len, reverse=True)[:15]:
        print("  gap %s, %d minutes" % (pd.to_datetime(r[0], unit="ms"), len(r)))
    gaps = lambda a, z: bool(np.searchsorted(gap_m, z, side="right") > np.searchsorted(gap_m, a, side="left"))
    # SOL/USD by hour: Coinbase, else the median of the data's own SOL-USDC swaps
    cb = pd.read_parquet(os.path.join(meta_dir, "solusd.parquet"))
    cbh = dict(zip(cb["hour_ms"].astype("int64"), cb["usd"]))
    uf = find("usd_*.parquet")
    own = pd.concat([pd.read_parquet(f) for f in uf]) if uf else pd.DataFrame({"m": [], "p": []})
    ownh = own.assign(h=own["m"] * MIN // HOUR * HOUR).groupby("h")["p"].median().to_dict() if len(own) else {}
    both = [(cbh[h], ownh[h]) for h in cbh if h in ownh]
    if both:
        r = np.array([b / a for a, b in both])
        print("SOL/USD: %d Coinbase hours, %d own hours; own/Coinbase median %.4f (10%% %.4f, 90%% %.4f)" % (
            len(cbh), len(ownh), np.median(r), np.percentile(r, 10), np.percentile(r, 90)))
    hours = dict(ownh)
    hours.update(cbh)
    hk = np.array(sorted(hours))
    hv = np.array([hours[h] for h in hk])

    def solusd(x):
        if not len(hk):
            return None
        i = int(np.searchsorted(hk, x, side="right")) - 1
        return float(hv[i]) if i >= 0 and x - hk[i] <= 3 * HOUR else None

    bars = pd.concat([pd.read_parquet(f) for f in find("bars_*.parquet")], ignore_index=True)
    dup = bars.duplicated(["pool", "m"], keep=False)
    if dup.any():      # a minute split over two files
        one = bars[dup].sort_values(["pool", "m", "t_first"]).groupby(["pool", "m"], sort=False).agg(
            t_first=("t_first", "first"), t_last=("t_last", "last"), p_open=("p_open", "first"), p_close=("p_close", "last"),
            p_hi=("p_hi", "max"), p_lo=("p_lo", "min"), sol_buy=("sol_buy", "sum"), sol_sell=("sol_sell", "sum"),
            n_buy=("n_buy", "sum"), n_sell=("n_sell", "sum"), n_atomic=("n_atomic", "sum")).reset_index()
        bars = pd.concat([bars[~dup], one], ignore_index=True)
    bars = bars.sort_values(["pool", "m"]).reset_index(drop=True)
    print("bars: %d for %d pools" % (len(bars), bars["pool"].nunique()))
    wf = find("who_*.parquet")
    who = pd.concat([pd.read_parquet(f) for f in wf]).groupby(["pool", "ah"]).agg(
        buyers=("buyers", "sum"), sellers=("sellers", "sum"), buy_sol=("buy_sol", "sum"), top_buy=("top_buy", "max")).reset_index()
    who["top"] = who["top_buy"] / who["buy_sol"]
    whom = {}
    for r in who.itertuples(index=False):
        whom.setdefault(r.pool, {})[int(r.ah)] = (r.buyers if r.buyers == r.buyers else 0, r.sellers if r.sellers == r.sellers else 0, r.top)

    # the start price check: the first priced swap against the pool's start reserves
    gi = g.set_index("pool")
    fp = bars.dropna(subset=["p_open"]).groupby("pool")["p_open"].first()
    ratio = (fp / (gi["sol0"] / gi["tok0"]).reindex(fp.index)).dropna()
    print("first PumpSwap price / start-reserve price: median %.3f (10%% %.3f, 90%% %.3f) over %d pools" % (
        ratio.median(), ratio.quantile(0.1), ratio.quantile(0.9), len(ratio)))

    rows, t0 = [], time.time()
    starts = np.r_[0, np.nonzero(bars["pool"].to_numpy()[1:] != bars["pool"].to_numpy()[:-1])[0] + 1, len(bars)]
    pools = bars["pool"].to_numpy()
    for a, z in zip(starts[:-1], starts[1:]):
        pool = pools[a]
        if pool not in gi.index:
            continue
        c = dict(gi.loc[pool])
        c["pool"] = pool
        rows += coin_rows(c, bars.iloc[a:z], solusd, gaps, whom.get(pool, {}))
    df = pd.DataFrame(rows)
    print("built %d rows from %d coins in %.0f s" % (len(df), df["mint"].nunique() if len(df) else 0, time.time() - t0))
    if not len(df):
        return
    df["month"] = pd.to_datetime(df["ts"], unit="ms").dt.strftime("%Y-%m")
    for mo, part in df.groupby("month"):
        p = os.path.join(hist, "hourly_%s.parquet" % mo)
        part.drop(columns=["month"]).to_parquet(p, compression="zstd", index=False)
        print("  %s: %d rows, %.1f MB" % (os.path.basename(p), len(part), os.path.getsize(p) / 1e6))
    df = df.drop(columns=["month"])
    # the bars themselves, for later exit studies, by graduation day (32-bit floats keep them small)
    gday = pd.to_datetime(bars["pool"].map(gi["grad_ms"]), unit="ms").dt.strftime("%Y-%m-%d")
    for c in ("p_open", "p_close", "p_hi", "p_lo", "sol_buy", "sol_sell"):
        bars[c] = bars[c].astype("float32")
    big = 0
    for day, part in bars.groupby(gday):
        p = os.path.join(hist, "bars", "bars_%s.parquet" % day)
        part.to_parquet(p, compression="zstd", index=False)
        if os.path.getsize(p) > 95e6:
            big += 1
            os.remove(p)
            print("  bars of %s left out: over 95 MB" % day)
    bar_mb = sum(os.path.getsize(f) for f in glob.glob(os.path.join(hist, "bars", "*.parquet"))) / 1e6
    print("bars: %.0f MB" % bar_mb)
    if bar_mb > BARS_MAX_MB:      # too big for the branch: they stay with the run as an artifact only
        shutil.move(os.path.join(hist, "bars"), os.path.join(out, "bars"))
        print("  bars kept out of the branch (over %d MB); they are in the run's artifact" % BARS_MAX_MB)
    g.to_parquet(os.path.join(hist, "coins.parquet"), compression="zstd", index=False)
    summ = {"source": "https://huggingface.co/datasets/%s" % SRC, "licence": "CC-BY-4.0", "attribution": ATTRIBUTION,
            "rows": len(df), "coins": int(df["mint"].nunique()), "with_px1": int(df["px1"].notna().sum()),
            "rows_without_gaps": int((~df["gap_pre"] & ~df["gap_1"]).sum()), "from": int(df["ts"].min()), "to": int(df["ts"].max()),
            "gap_minutes": int(len(gap_m)), "ages_h": [min(AGES_H), max(AGES_H)], "eval_h": EVAL_H, "path_h": PATH_H,
            "min_sol": MIN_SOL, "bar_days_left_out": big, "bars_in_branch": bar_mb <= BARS_MAX_MB, "columns": list(df.columns)}
    json.dump(summ, open(os.path.join(hist, "summary.json"), "w"), indent=1)
    np.save(os.path.join(hist, "gap_minutes.npy"), gap_m)
    open(os.path.join(hist, "README.md"), "w").write(
        "# Long-history rows for the Meme-Bot, part 2 (fake money only)\n\n"
        "%s\n\nDerived (changed) from that data set by research/history_build2.py: every PumpSwap swap of the coins that graduated "
        "from pump.fun between 10 August and 8 October 2026, made into one-minute bars (bars/, by graduation day) and into rows at "
        "whole hours after each graduation (hourly_*.parquet) with screener-like numbers, the price %.1f hours later and the path "
        "over %.0f hours. Market cap, liquidity and the rug time are computed, not recorded; see the script's header. Rows whose "
        "windows touch a recorder outage are flagged (gap_pre, gap_1, gap_6).\n" % (ATTRIBUTION, EVAL_H, PATH_H))
    print(json.dumps({k: v for k, v in summ.items() if k != "columns"}))
    ok = df[~df["gap_pre"] & ~df["gap_1"] & df["px1"].notna()]
    print("rows without gaps and with a price 1.7 h later: %d; their move in SOL: median %.3f, under 0.02x %.1f%%, 2x or more %.2f%%" % (
        len(ok), ok["mult1"].median(), 100 * (ok["mult1"] < 0.02).mean(), 100 * (ok["mult1"] >= 2).mean()))
    print(df.describe(percentiles=[0.1, 0.5, 0.9]).T.to_string(max_rows=200, max_colwidth=40)[:20000])


def main():
    cmd, a = sys.argv[1], sys.argv[2:]
    {"meta": meta, "shard": shard, "final": final}[cmd](*a)


if __name__ == "__main__":
    main()
