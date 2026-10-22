"""Rocket hunter replay on the days after the history (fake money only): the pump.fun graduations of 9-21 Oct 2026, which the
model never saw (its data ends 8 Oct), replayed the way the live account (rocket_watch.py) sees a coin.

  grads <out.json>                       every graduation (mint, PumpSwap pool, time, start reserves) from Helius
  shard <grads.json> <i> <n> <out.json>  graduations i, i+n, ...: GeckoTerminal 15-minute candles -> the universe every 15 minutes
                                         from 30 min to 18 h (market cap, liquidity, 24 h volume, 1 h / 6 h change); for coins inside it
                                         the minute candles, and at each such point Helius' last 300 pool transactions before it (as
                                         GeckoTerminal's last 300 trades live) -> rocket.features -> rocket.score; a buy at the cut,
                                         rule A on the minute candles after it (stop first, 11x, 6 h), as the live account every 15 min
  final <out dir> <shard files...>       joins the shards: coins bought, euro per 20, x of 10 in profit, 3x/10x, per day, 10,000
                                         simulations, the same at the looser cuts (top 1 / 2 %), and the credits used

The model, cut, memory and rule are the live ones (rocket_model.json, rocket_memory.json.gz, rocket.py); nothing is fitted here.
Numbers made like history_build2.py: mc = price x 1e9, liquidity = 2 x SOL side from the start reserves' constant product.
Env HK = Helius key (never printed), BUDGET = Helius credits a shard may use (10 per 100 transactions)."""
import collections, datetime as dt, gzip, json, math, os, random, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import rocket as R

K = os.environ.get("HK") or ""
RPC = "https://mainnet.helius-rpc.com/?api-key=" + K
GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
BN = "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h&startTime=%d&limit=1000"
MIG = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
T_FROM = int(dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc).timestamp())
T_TO = int(dt.datetime(2026, 10, 21, 6, tzinfo=dt.timezone.utc).timestamp())     # 18 h of entries + 6 h hold end before now
MIN, H = 60_000, 3_600_000
GT_GAP = float(os.environ.get("GT_GAP") or 2.2)
HL_GAP = float(os.environ.get("HL_GAP") or 0.5)
CUTS = {"0.5%": None, "1%": None, "2%": None}          # filled from the model's training scores (cutTop 0.5 % is the live one)
calls = collections.Counter()
ERRORS = []


def log(*a):
    print(*a, flush=True)


_last = {}


def get(url, data=None, gap=0.0, tries=4):
    host = url.split("/")[2]
    w = _last.get(host, 0) + gap - time.time()
    if w > 0:
        time.sleep(w)
    for i in range(tries):
        req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "memebot-research"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                _last[host] = time.time()
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def helius(address, opts):
    calls["helius"] += 1
    j = get(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [address, opts]}, HL_GAP)
    res = (j or {}).get("result") if isinstance(j, dict) else None
    if res is None and len(ERRORS) < 30:
        e = (j or {}).get("error") if isinstance(j, dict) else None
        ERRORS.append({"opts": {k: v for k, v in opts.items() if k != "paginationToken"}, "error": e if e else ("no answer" if j is None else str(j)[:200])})
        log("helius error", ERRORS[-1])
    if isinstance(res, dict):
        n = len(res.get("data") or [])
        calls["credits"] += 10 if opts.get("transactionDetails") == "signatures" else max(10, 10 * math.ceil(n / 100))
    return res


def keys(tx):
    m = (tx.get("transaction") or {}).get("message") or {}
    ks = [k if isinstance(k, str) else k.get("pubkey") for k in m.get("accountKeys") or []]
    lw = (tx.get("meta") or {}).get("loadedAddresses") or {}
    return ks + list(lw.get("writable") or []) + list(lw.get("readonly") or [])


def balances(tx, owner):
    """{mint: (pre, post)} of the token accounts the owner holds in this transaction."""
    meta = tx.get("meta") or {}
    out = {}
    for side, k in (("preTokenBalances", 0), ("postTokenBalances", 1)):
        for b in meta.get(side) or []:
            if b.get("owner") != owner:
                continue
            v = float(((b.get("uiTokenAmount") or {}).get("uiAmount")) or 0.0)
            p = out.setdefault(b.get("mint"), [0.0, 0.0])
            p[k] += v
    return out


def migration(tx):
    """mint, pool and start reserves (SOL, tokens) of a PumpSwap create_pool in a migration transaction, or None."""
    if (tx.get("meta") or {}).get("err"):
        return None
    ks = keys(tx)
    m = (tx.get("transaction") or {}).get("message") or {}
    ins = list(m.get("instructions") or [])
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        ins += inner.get("instructions") or []
    for ix in ins:
        pid = ix.get("programId") or (ks[ix["programIdIndex"]] if isinstance(ix.get("programIdIndex"), int) and ix["programIdIndex"] < len(ks) else None)
        if pid != AMM:
            continue
        acc = [a if isinstance(a, str) else (ks[a] if isinstance(a, int) and a < len(ks) else None) for a in ix.get("accounts") or []]
        if len(acc) < 5:
            continue
        pool, mint = acc[0], acc[3]
        bal = balances(tx, pool)
        tok, sol = (bal.get(mint) or [0, 0])[1], (bal.get(WSOL) or [0, 0])[1]
        if tok > 0 and sol > 0:
            return {"mint": mint, "pool": pool, "t": int(tx.get("blockTime") or 0) * 1000, "sol0": sol, "tok0": tok}
    return None


def swap(tx, pool, mint):
    """GeckoTerminal's trade shape {t, buy, sol, who} from a pool transaction (the pool's own token balances decide the side)."""
    if (tx.get("meta") or {}).get("err"):
        return None
    bal = balances(tx, pool)
    s, k = bal.get(WSOL), bal.get(mint)
    if not s or not k:
        return None
    ds, dk = s[1] - s[0], k[1] - k[0]
    if abs(ds) < 1e-9 or ds * dk >= 0:
        return None
    ks = keys(tx)
    return {"t": int(tx.get("blockTime") or 0) * 1000, "buy": ds > 0, "sol": abs(ds), "who": ks[0] if ks else None}


# ------------------------------------------------------------------------------------------------- step 1: the graduations
VARIANTS = [
    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "filters": {"blockTime": {"gte": T_FROM, "lt": T_TO}}},
    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "filters": {"blockTime": {"gte": T_FROM, "lte": T_TO}}},
    {"encoding": "json", "maxSupportedTransactionVersion": 0, "filters": {"blockTime": {"gte": T_FROM, "lt": T_TO}}},
    {"maxSupportedTransactionVersion": 0, "filters": {"blockTime": {"gte": T_FROM}}},
    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
]
OPTS = {}


def cmd_grads(out):
    grads, tok, pages = {}, None, 0
    for v in VARIANTS:
        if helius(MIG, dict(v, transactionDetails="full", sortOrder="asc", limit=100)) is not None:
            OPTS.update(v); log("helius options that work:", v); break
    else:
        json.dump({"grads": [], "errors": ERRORS, "calls": dict(calls)}, open(out, "w")); log("no option set works"); return
    while pages < 600:
        o = dict(OPTS, transactionDetails="full", sortOrder="asc" if "filters" in OPTS else "desc", limit=100)
        if tok:
            o["paginationToken"] = tok
        res = helius(MIG, o)
        pages += 1
        if not res:
            log("grads: no answer at page", pages); break
        for tx in res.get("data") or []:
            if not T_FROM <= (tx.get("blockTime") or 0) < T_TO:
                calls["outside"] += 1
                continue
            g = migration(tx)
            if g and g["mint"] not in grads:
                grads[g["mint"]] = g
        if "filters" not in OPTS and res.get("data") and (res["data"][-1].get("blockTime") or 0) < T_FROM:
            break
        if "filters" in OPTS and pages == 1 and res.get("data") and calls["outside"] == len(res["data"]):
            log("grads: the blockTime filter was not applied (first page all outside 9-21 Oct)"); sys.exit(2)
        tok = res.get("paginationToken")
        if not tok or not res.get("data"):
            break
        if pages % 20 == 0:
            log("grads page", pages, len(grads))
    day = collections.Counter(dt.datetime.fromtimestamp(g["t"] / 1000, dt.timezone.utc).strftime("%m-%d") for g in grads.values())
    log("graduations", len(grads), "pages", pages, "per day", dict(sorted(day.items())), "calls", dict(calls))
    json.dump({"from": T_FROM, "to": T_TO, "opts": OPTS, "grads": sorted(grads.values(), key=lambda g: g["t"]), "calls": dict(calls), "errors": ERRORS}, open(out, "w"))


# ------------------------------------------------------------------------------------------------- step 2: one shard
def gt_ohlcv(pool, res, agg, before_s, limit):
    calls["gt"] += 1
    j = get(GT + "%s/ohlcv/%s?aggregate=%d&limit=%d&currency=usd&token=base&before_timestamp=%d" % (pool, res, agg, limit, before_s), gap=GT_GAP)
    rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(j, dict) else None
    if rows is None:
        return None
    return sorted([[int(r[0]) * 1000] + [float(x) for x in r[1:6]] for r in rows if isinstance(r, list) and len(r) >= 6])


def klines(sym, t0, t1):
    out, s = [], t0
    while s < t1:
        j = get(BN % (sym, s, ), gap=0.3)
        if not isinstance(j, list) or not j:
            break
        out += [[int(r[0]), float(r[4])] for r in j]
        s = int(j[-1][0]) + H
    return out


def market_at(kl, t):
    """rocket_watch.market at time t: the last 26 hourly rows up to the open hour; 1 h and 24 h change of the last closed hour."""
    m, sol = {}, None
    for k, rows in kl.items():
        c = [px for ot, px in rows if ot <= t][-26:]
        if len(c) >= 26:
            m[k + "_1h"] = c[-2] / c[-3] - 1
            m[k + "_24h"] = c[-2] / c[-26] - 1
            if k == "sol":
                sol = c[-1]
    return m, sol


def screen(g, c15, sol_at):
    """The universe points (age in minutes) from the 15-minute candles: mc, liq, vol24, 1 h / 6 h change at each 15-minute step."""
    pts = []
    t0 = g["t"]
    k = g["sol0"] * g["tok0"]
    for age in range(R.START_MIN, R.END_MIN + 1, R.STEP_MIN):
        t = t0 + age * MIN
        past = [r for r in c15 if r[0] + 15 * MIN <= t]
        if not past:
            continue
        px = past[-1][4]
        sol = sol_at(t)
        if not sol or px <= 0:
            continue
        mc = px * 1e9
        liq = 2 * math.sqrt(k * px / sol) * sol if k > 0 else 0.0
        vol = sum(r[5] for r in past if r[0] >= t - 24 * H)
        ref = lambda back: next((r[4] for r in reversed(past) if r[0] + 15 * MIN <= t - back), past[0][1])
        c1 = (px / ref(H) - 1) * 100 if ref(H) else None
        c6 = (px / ref(6 * H) - 1) * 100 if ref(6 * H) else None
        if R.universe(age, mc, liq, vol, c1, c6):
            pts.append({"age": age, "t": t, "mc": mc, "liq": liq, "vol": vol})
    return pts


LIMIT = [300]


def last_trades(pool, mint, t, sol):
    """The pool's last 300 transactions before t (one request of 300, or three of 100 if the method allows only 100)."""
    o = {"transactionDetails": "full", "sortOrder": "desc", "limit": LIMIT[0], "encoding": OPTS.get("encoding", "jsonParsed"),
         "maxSupportedTransactionVersion": 0, "filters": {"blockTime": {"lt": int(t // 1000)}}}
    data, res = [], helius(pool, o)
    if res is None and LIMIT[0] == 300:
        LIMIT[0] = 100
        log("limit 300 refused, using 3 x 100")
        return last_trades(pool, mint, t, sol)
    while res is not None:
        data += res.get("data") or []
        if len(data) >= 300 or not res.get("paginationToken") or not res.get("data"):
            break
        res = helius(pool, dict(o, paginationToken=res["paginationToken"]))
    if res is None and not data:
        return None
    out = []
    for tx in data[:300]:
        if (tx.get("blockTime") or 0) * 1000 >= t:
            calls["late"] += 1
            continue
        s = swap(tx, pool, mint)
        if s:
            out.append({"t": s["t"], "buy": s["buy"], "usd": s["sol"] * sol, "who": s["who"]})
    return out


def hold(cm, t_buy, px):
    """Rule A every 15 minutes on the minute candles after the buy, as rocket_watch: the window's high and low, the last close."""
    b = R.Book()
    b.buy("x", "x", px, t_buy, 1.0, 0.0, "p")
    t = t_buy
    while "x" in b.open:
        t += R.STEP_MIN * MIN
        w = [r for r in cm if t - R.STEP_MIN * MIN - MIN <= r[0] < t]
        hi = max((r[2] for r in w), default=None)
        lo = min((r[3] for r in w), default=None)
        last = [r for r in cm if r[0] < t]
        out = b.update("x", t, hi=hi, lo=lo, px=last[-1][4] if last else px)
        if out:
            return out
        if t - t_buy > R.HOLD_MS + H:
            return b._close("x", t, (last[-1][4] if last else px) / px, "6h")


def cmd_shard(fn, i, n, out):
    i, n = int(i), int(n)
    GD = json.load(open(fn))
    OPTS.update({k: v for k, v in (GD.get("opts") or {}).items() if k in ("encoding", "maxSupportedTransactionVersion")})
    G = GD["grads"][i::n]
    if os.environ.get("MAX_COINS"):
        G = G[::max(1, len(G) // int(os.environ["MAX_COINS"]))][:int(os.environ["MAX_COINS"])]
    model = json.load(open(os.path.join(ROOT, "rocket_model.json")))
    cuts = {"0.5%": model["cut"]}
    cuts.update({k: v for k, v in json.load(open(os.path.join(HERE, "backfill_cuts.json"))).items() if k.endswith("%")})
    mem_fn = os.environ.get("MEMORY") or "rocket_memory.json.gz"
    with gzip.open(mem_fn, "rt") as f:
        memory = json.load(f)
    budget = int(os.environ.get("BUDGET") or 60000)
    kl = {"btc": klines("BTCUSDT", (T_FROM - 2 * 86400) * 1000, (T_TO + 2 * 86400) * 1000),
          "sol": klines("SOLUSDT", (T_FROM - 2 * 86400) * 1000, (T_TO + 2 * 86400) * 1000)}
    sol_at = lambda t: market_at(kl, t)[1]
    log("shard", i, "of", n, "coins", len(G), "memory", len(memory), "klines", {k: len(v) for k, v in kl.items()}, "cuts", cuts)
    rows, coins, t_start = [], [], time.time()
    for gi, g in enumerate(G):
        if calls["credits"] >= budget:
            log("budget reached at coin", gi); break
        c15 = gt_ohlcv(g["pool"], "minute", 15, int((g["t"] + 19 * H) // 1000), 100)
        if c15 is None:
            coins.append({"mint": g["mint"], "gt": "none"}); continue
        pts = screen(g, c15, sol_at)
        rec = {"mint": g["mint"], "pool": g["pool"], "t": g["t"], "pts": len(pts)}
        coins.append(rec)
        if not pts:
            continue
        cm = []
        before = int((g["t"] + 25 * H) // 1000)
        for _ in range(2):
            r = gt_ohlcv(g["pool"], "minute", 1, before, 1000) or []
            cm = sorted(cm + r)
            if not r or r[0][0] <= g["t"]:
                break
            before = r[0][0] // 1000 - 1
        bought = {}
        for p in pts:
            if len(bought) == len(cuts):
                break
            mkt, sol = market_at(kl, p["t"])
            tr = last_trades(g["pool"], g["mint"], p["t"], sol)
            if tr is None:
                rec["helius"] = "none"; break
            cs = [r for r in cm if r[0] < p["t"] - MIN + 1]
            f = R.features(cs, tr, g["t"], p["t"], sol, p["mc"], p["liq"], p["vol"], mkt, memory)
            sc = R.score(model, f)
            if sc is None:
                continue
            row = {"mint": g["mint"], "age": p["age"], "t": p["t"], "score": round(sc, 5), "reach": f.get("_reach"), "ntr": len(tr)}
            px = cs[-1][4] if cs else None
            for name, cut in cuts.items():
                if name not in bought and sc >= cut and px:
                    o = hold([r for r in cm if r[0] >= p["t"] - MIN], p["t"], px)
                    if o:
                        bought[name] = {"cut": name, "mint": g["mint"], "t": p["t"], "age": p["age"], "score": round(sc, 5),
                                        "mult": o["mult"], "eur": o["eur"], "why": o["why"], "hi": round(o.get("hi") or 0, 3)}
            rows.append(row)
        rec["bought"] = list(bought.values())
        if gi % 100 == 0:
            log("coin %d/%d  universe coins %d  points %d  bought %d  calls %s  %.0f s" % (
                gi, len(G), sum(1 for c in coins if c.get("pts")), len(rows), sum(len(c.get("bought") or []) for c in coins), dict(calls), time.time() - t_start))
    json.dump({"shard": i, "n": n, "coins": coins, "rows": rows, "calls": dict(calls), "cuts": cuts, "errors": ERRORS}, open(out, "w"))
    log("done", dict(calls))


# ------------------------------------------------------------------------------------------------- step 3: the result
def sim(eur_by_day, runs=10_000, seed=7):
    """filter_search.simulate in small: days drawn with replacement, an extra 0-1.5 % fee a side and 0-4 % slippage a day."""
    rng = random.Random(seed)
    days = list(eur_by_day.values())
    if not days:
        return None
    tot = []
    for _ in range(runs):
        s = 0.0
        for _ in days:
            d = rng.choice(days)
            fee, slip = rng.uniform(0, 0.015), rng.uniform(0, 0.04)
            s += sum(e - 20 * (2 * fee + slip) for e in d)
        tot.append(s / max(1, sum(len(d) for d in days)))
    tot.sort()
    return {"pProfit": round(100 * sum(1 for x in tot if x > 0) / runs, 1), "median": round(tot[runs // 2], 2),
            "p5": round(tot[runs // 20], 2), "p95": round(tot[-runs // 20], 2)}


def cmd_final(outdir, *files):
    coins, rows, cr = [], [], collections.Counter()
    for fn in files:
        d = json.load(open(fn))
        coins += d["coins"]; rows += d["rows"]
        cr.update(d.get("calls") or {})
    res = {"made": int(time.time() * 1000), "graduations": len(coins), "gtMissing": sum(1 for c in coins if c.get("gt") == "none"),
           "universeCoins": sum(1 for c in coins if c.get("pts")), "points": len(rows), "calls": dict(cr), "cuts": {},
           "errors": [e for fn in files for e in (json.load(open(fn)).get("errors") or [])[:5]]}
    for name in ("0.5%", "1%", "2%"):
        b = [x for c in coins for x in c.get("bought") or [] if x["cut"] == name]
        if not b:
            res["cuts"][name] = {"n": 0}; continue
        eur = [x["eur"] for x in b]
        by = collections.defaultdict(list)
        for x in b:
            by[dt.datetime.fromtimestamp(x["t"] / 1000, dt.timezone.utc).strftime("%m-%d")].append(x["eur"])
        res["cuts"][name] = {"n": len(b), "eurPer20": round(sum(eur) / len(eur), 2), "sum": round(sum(eur), 2),
                             "inProfitOf10": round(10 * sum(1 for e in eur if e > 0) / len(eur), 1),
                             "x10": sum(1 for x in b if x["why"] == "11x"), "x3": sum(1 for x in b if x["hi"] >= 3),
                             "stops": sum(1 for x in b if x["why"] == "stop"),
                             "perDay": {k: [len(v), round(sum(v), 2)] for k, v in sorted(by.items())}, "sim": sim(by),
                             "coins": sorted(b, key=lambda x: x["t"])}
    os.makedirs(outdir, exist_ok=True)
    json.dump(res, open(os.path.join(outdir, "backfill.json"), "w"), indent=1)
    lines = ["graduations %d (GeckoTerminal missing %d), universe coins %d, scored points %d, calls %s" % (
        res["graduations"], res["gtMissing"], res["universeCoins"], res["points"], res["calls"])]
    for name, r in res["cuts"].items():
        if r["n"]:
            lines.append("top %s: %d coins, %+.2f per 20, %.1f of 10 in profit, 10x %d, 3x %d, stops %d, sim %s" % (
                name, r["n"], r["eurPer20"], r["inProfitOf10"], r["x10"], r["x3"], r["stops"], r["sim"]))
            lines.append("   per day " + json.dumps(r["perDay"]))
        else:
            lines.append("top %s: 0 coins" % name)
    open(os.path.join(outdir, "summary.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"grads": cmd_grads, "shard": cmd_shard, "final": cmd_final}[a[0]](*a[1:])
