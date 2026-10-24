"""Data for the tests over months (fake money only; research/PREREG-MONTHS-2026-10-23.md): five-minute USD candles of the first
48 hours after each pump.fun graduation, the same format for every month we can get for free.

  plan <out dir>                         the graduations of 25 Apr-24 May, 25 Jun-24 Jul (Helius lists on branch callsdata) and
                                         9-21 Oct (branch backfill's list), start SOL side >= 10, oldest first, minus the pools
                                         already on branch monthsdata; SOL/USD and BTC/USD by hour from Binance (Apr-Oct)
  shard <plan.json> <i> <n> <out.json.gz>  pools i, i+n, ...: GeckoTerminal 5-minute candles up to 48 h after the graduation
                                         (one call per pool, free API = the last 6 months, so the oldest go first); the file is
                                         rewritten every 100 pools, so a shard stopped at the job limit keeps what it has
  final <dir with shard files> <old monthsdata dir or -> <out dir>   joins old and new candles into parquet by month window
  h2 <history2 bars dir> <coins.parquet> <SOLUSDT.jsonl> <out dir>   the history2 one-minute SOL bars (artifact "bars" of
                                         history-build run 39668736908, 10 Aug-8 Oct) as the same five-minute USD candles

Run 1 (23 Oct, 19:48-01:14 UTC) fetched 20,041 of 25,754 pools at about 3,700 calls an hour; a second run (a push of this
file) fetches the rest. Candles: pool, t (ms, start of the 5-minute bar, clock-aligned), o, h, l, c (USD per token), v (USD). A bar without a trade is
missing, as on GeckoTerminal. Env GT_GAP = seconds between GeckoTerminal calls, SHARD_MINUTES = a shard stops after this long."""
import collections, datetime as dt, glob, gzip, json, os, random, sys, time, urllib.error, urllib.request

GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/%s/ohlcv/minute?aggregate=5&limit=1000&currency=usd&token=base&before_timestamp=%d"
BN = "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h&startTime=%d&limit=1000"
MIN, H, BAR = 60_000, 3_600_000, 300_000
KEEP_H = 48
GT_GAP = float(os.environ.get("GT_GAP") or 2.2)
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))


def ms(day):
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def window(t):
    for name, a, b in WINDOWS:
        if ms(a) <= t < ms(b):
            return name
    return None


def log(*a):
    print(*a, flush=True)


_last = {}


def get(url, gap=0.0, tries=4):
    host = url.split("/")[2]
    w = _last.get(host, 0) + gap - time.time()
    if w > 0:
        time.sleep(w)
    for i in range(tries):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "memebot-research"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                _last[host] = time.time()
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (i + 1))
                continue
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def klines(sym, t0, t1):
    out, s = [], t0
    while s < t1:
        j = get(BN % (sym, s), gap=0.3)
        if not isinstance(j, list) or not j:
            break
        out += [[int(r[0]), float(r[4])] for r in j]
        s = int(j[-1][0]) + H
    return out


def cmd_plan(out):
    os.makedirs(out, exist_ok=True)
    allg = {}
    for f in sorted(glob.glob("g/gradlists/*.json")):
        for g in json.load(open(f)).get("grads") or []:
            if g.get("pool") and (g.get("sol0") or 0) >= 10 and window(g["t"]) in ("w1", "w2", "w5"):
                allg.setdefault(g["pool"], g)
    have = set()
    for f in glob.glob("old/meta_*.json"):
        have |= {g["pool"] for g in json.load(open(f)) if g.get("bars")}
    gs = sorted((g for p, g in allg.items() if p not in have), key=lambda g: g["t"])
    by = collections.Counter(window(g["t"]) for g in gs)
    log("graduations", len(allg), "already fetched", len(have), "to fetch", len(gs), dict(by))
    json.dump({"grads": gs}, open(os.path.join(out, "plan.json"), "w"))
    t0, t1 = ms("2026-04-20"), int(time.time() * 1000)
    mk = {s: klines(s, t0, t1) for s in ("SOLUSDT", "BTCUSDT")}
    log("binance hours", {s: len(v) for s, v in mk.items()})
    json.dump(mk, open(os.path.join(out, "market.json"), "w"))


def save(out, res, meta, k, n):
    tmp = out + ".tmp"
    with gzip.open(tmp, "wt") as fh:
        json.dump({"pools": res, "meta": meta, "done": k, "planned": n}, fh)
    os.replace(tmp, out)


def cmd_shard(plan, i, n, out):
    gs = json.load(open(plan))["grads"][i::n]
    res, meta, miss = {}, [], 0
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 300))
    t_start = time.time()
    for k, g in enumerate(gs):
        if time.time() > stop:
            log("shard", i, "time budget used at", k, "of", len(gs))
            break
        j = get(GT % (g["pool"], g["t"] // 1000 + KEEP_H * 3600), gap=GT_GAP)
        rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(j, dict) else None
        if rows is None:
            miss += 1
            meta.append(dict(g, bars=0, missing=True))
        else:
            rows = sorted([int(r[0]) * 1000] + [float(x) for x in r[1:6]] for r in rows if isinstance(r, list) and len(r) >= 6)
            rows = [r for r in rows if g["t"] - BAR <= r[0] < g["t"] + KEEP_H * H]
            res[g["pool"]] = rows
            meta.append(dict(g, bars=len(rows)))
        if k % 100 == 99:
            save(out, res, meta, k + 1, len(gs))
            log("shard", i, k + 1, "of", len(gs), "missing", miss, "%.1f s per call" % ((time.time() - t_start) / (k + 1)))
    save(out, res, meta, len(meta), len(gs))
    log("shard", i, "done", len(res), "missing", miss)


def cmd_final(src, old, out):
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    frames, metas = [], []
    if old != "-":
        for f in sorted(glob.glob(os.path.join(old, "bars_*.parquet"))):
            frames.append(pd.read_parquet(f))
        for f in sorted(glob.glob(os.path.join(old, "meta_*.json"))):
            metas += json.load(open(f))
    for f in sorted(glob.glob(os.path.join(src, "**", "gt_*.json.gz"), recursive=True)):
        d = json.load(gzip.open(f))
        metas += d["meta"]
        rows = [[p] + r for p, rs in d["pools"].items() for r in rs]
        if rows:
            frames.append(pd.DataFrame(rows, columns=["pool", "t", "o", "h", "l", "c", "v"]))
        log(os.path.basename(f), "pools", len(d["pools"]), "done", d["done"], "of", d["planned"])
    b = pd.concat(frames, ignore_index=True).drop_duplicates(["pool", "t"]).sort_values(["pool", "t"])
    for c in "ohlcv":
        b[c] = b[c].astype("float32")
    seen = {}
    for g in metas:
        if g["pool"] not in seen or (g.get("bars") and not seen[g["pool"]].get("bars")):
            seen[g["pool"]] = g
    metas = sorted(seen.values(), key=lambda g: g["t"])
    w_of = {g["pool"]: window(g["t"]) for g in metas}
    b["w"] = b["pool"].map(w_of)
    for w, part in b.groupby("w"):
        part.drop(columns=["w"]).to_parquet(os.path.join(out, "bars_%s.parquet" % w), index=False, compression="zstd")
        log(w, "pools", part["pool"].nunique(), "bars", len(part), "%.1f MB" % (os.path.getsize(os.path.join(out, "bars_%s.parquet" % w)) / 1e6))
    for w in sorted({x for x in w_of.values() if x}):
        json.dump([g for g in metas if w_of[g["pool"]] == w], open(os.path.join(out, "meta_%s.json" % w), "w"))
    log("meta", collections.Counter((w_of[g["pool"]], bool(g.get("bars"))) for g in metas))


def cmd_h2(bars_dir, coins_file, sol_file, out):
    import numpy as np, pandas as pd
    os.makedirs(out, exist_ok=True)
    co = pd.read_parquet(coins_file).drop_duplicates("pool")
    co = co[co["sol0"] >= 10].set_index("pool")
    k = [json.loads(l) for l in open(sol_file)]
    sol_t, sol_c = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])
    files = sorted(glob.glob(os.path.join(bars_dir, "**", "bars_*.parquet"), recursive=True))
    log(len(files), "bar files")
    meta = {}
    for f in files:
        b = pd.read_parquet(f, columns=["pool", "m", "p_open", "p_close", "p_hi", "p_lo", "sol_buy", "sol_sell"])
        b = b[b["pool"].isin(co.index)]
        gm = b["pool"].map(co["grad_ms"]).astype("int64")
        b = b[(b["m"] >= gm) & (b["m"] < gm + KEEP_H * H)].copy()
        usd = sol_c[np.clip(np.searchsorted(sol_t, b["m"].to_numpy(), side="right") - 1, 0, len(sol_c) - 1)]
        b["t"] = b["m"] // BAR * BAR
        b["v"] = (b["sol_buy"] + b["sol_sell"]) * usd
        for c in ("p_open", "p_close", "p_hi", "p_lo"):
            b[c] = b[c] * usd
        b = b.sort_values(["pool", "m"])
        g = b.groupby(["pool", "t"], sort=False).agg(o=("p_open", "first"), h=("p_hi", "max"), l=("p_lo", "min"), c=("p_close", "last"),
                                                       v=("v", "sum")).reset_index().dropna(subset=["c"])
        for c in "ohlcv":
            g[c] = g[c].astype("float32")
        name = os.path.basename(f)
        g.to_parquet(os.path.join(out, name), index=False, compression="zstd")
        for p in g["pool"].unique():
            meta[p] = 1
        log(name, "pools", g["pool"].nunique(), "bars", len(g), "%.1f MB" % (os.path.getsize(os.path.join(out, name)) / 1e6))
    c = co.reset_index()
    c = c[["pool", "mint", "grad_ms", "sol0", "tok0"]].rename(columns={"grad_ms": "t"})
    c["bars"] = c["pool"].map(lambda p: meta.get(p, 0))
    c.to_parquet(os.path.join(out, "meta_h2.parquet"), index=False)
    log("coins", len(c), "with bars", int(c["bars"].sum()))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "plan":
        cmd_plan(a[1])
    elif a[0] == "shard":
        cmd_shard(a[1], int(a[2]), int(a[3]), a[4])
    elif a[0] == "final":
        cmd_final(a[1], a[2], a[3])
    elif a[0] == "h2":
        cmd_h2(a[1], a[2], a[3], a[4])
