"""The sealed days of the big search (fake money only; research/bigsearch/PREREG-BIGSEARCH-2026-10-28.md): every pump.fun
graduation from 21 Oct 2026 on, and for those of S1 (22 Oct 00:00 - 26 Oct 12:00 UTC) the same data as the fit windows have.
Runs in GitHub Actions (.github/workflows/bigsearch-data.yml), because the cloud session reaches no market API.

  sigs  <out dir>                          the migration account's transactions from T_FROM on: with Helius (getTransactionsForAddress,
                                           if the free key answers) the graduations themselves -> grads_helius.json; otherwise the
                                           public RPC's signature list -> sigs.json (one call a page of 1,000)
  tx    <sigs.json> <i> <n> <out.json>     signatures i, i+n, ...: getTransaction on the public RPC -> the graduations among them
  plan  <dir with grads files> <out dir>   grads.json (all, deduplicated), plan.json (S1 pools with start SOL side >= 10, for
                                           research/months_fetch.py shard), mints.json (their mints and 21 Oct's, for
                                           research/rockets/meta_chain.py shard), market.json (Binance SOL/BTC by hour from 15 Oct)
  final <candle shards dir> <chain dir> <plan dir> <out dir>
                                           bars_s1.parquet + meta_s1.json (as monthsdata's bars_w5 / meta_w5), grads.json, market.json
                                           and a coverage summary (summary.json)

The graduation is the PumpSwap create_pool in a migration transaction: pool, mint, time, start SOL and token side (the same
parsing as research/winlose/backfill.py). Env HK = Helius key (never printed), PGAP = seconds between public RPC calls."""
import collections, datetime as dt, glob, gzip, json, os, sys, time, urllib.error, urllib.request

MIG = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
BN = "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h&startTime=%d&limit=1000"


def ms(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


T_FROM = ms("2026-10-21 00:00")
S1 = (ms("2026-10-22 00:00"), ms("2026-10-26 12:00"))
MIN_SOL = 10.0
PGAP = float(os.environ.get("PGAP") or 0.3)


def log(*a):
    print(*a, flush=True)


_last = {}


def post(url, body, gap, tries=5):
    host = url.split("/")[2]
    for i in range(tries):
        w = _last.get(host, 0) + gap - time.time()
        if w > 0:
            time.sleep(w)
        _last[host] = time.time()
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "User-Agent": "memebot-research"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            return e.code, None
        except Exception as e:
            time.sleep(2 * (i + 1))
            code = type(e).__name__
    return "gave up", None


def rpc(url, method, params, gap):
    st, j = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, gap)
    if not isinstance(j, dict):
        return st, None
    if "error" in j:
        return "rpc %s" % (j["error"] or {}).get("code"), None
    return st, j.get("result")


# ------------------------------------------------------------------------------------------- parsing (research/winlose/backfill.py)
def keys(tx):
    m = (tx.get("transaction") or {}).get("message") or {}
    ks = [k if isinstance(k, str) else k.get("pubkey") for k in m.get("accountKeys") or []]
    lw = (tx.get("meta") or {}).get("loadedAddresses") or {}
    return ks + list(lw.get("writable") or []) + list(lw.get("readonly") or [])


def balances(tx, owner):
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


# ------------------------------------------------------------------------------------------------------------- steps
def cmd_sigs(out):
    os.makedirs(out, exist_ok=True)
    t_to = int(time.time())
    k = os.environ.get("HK") or ""
    if k:
        url = "https://mainnet.helius-rpc.com/?api-key=" + k
        o = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "transactionDetails": "full", "sortOrder": "asc",
             "limit": 100, "filters": {"blockTime": {"gte": T_FROM // 1000, "lt": t_to}}}
        st, res = rpc(url, "getTransactionsForAddress", [MIG, o], 0.5)
        if isinstance(res, dict):
            log("helius answers: graduations from Helius")
            grads, pages = {}, 0
            while True:
                for tx in res.get("data") or []:
                    g = migration(tx)
                    if g and g["mint"] not in grads:
                        grads[g["mint"]] = g
                pages += 1
                tok = res.get("paginationToken")
                if not tok or not res.get("data") or pages >= 2000:
                    break
                st, res = rpc(url, "getTransactionsForAddress", [MIG, dict(o, paginationToken=tok)], 0.5)
                if not isinstance(res, dict):
                    log("helius stopped answering at page", pages, st)
                    grads = None
                    break
                if pages % 20 == 0:
                    log("page", pages, "graduations", len(grads))
            if grads is not None:
                json.dump({"grads": sorted(grads.values(), key=lambda g: g["t"]), "source": "helius", "to": t_to},
                          open(os.path.join(out, "grads_helius.json"), "w"))
                json.dump({"sigs": [], "source": "helius"}, open(os.path.join(out, "sigs.json"), "w"))
                log("graduations", len(grads), "pages", pages)
                return
        log("helius does not answer (%s): public RPC" % st)
    sigs, before, calls = [], None, 0
    while True:
        o = {"limit": 1000}
        if before:
            o["before"] = before
        for k in range(8):
            st, res = rpc(PUBLIC_RPC, "getSignaturesForAddress", [MIG, o], PGAP)
            if isinstance(res, list):
                break
            log("signature page failed (%s), try %d" % (st, k + 1))
            time.sleep(10 * (k + 1))
        calls += 1
        if not isinstance(res, list):
            log("signature list stopped (%s) after %d calls" % (st, calls))
            if calls > 1 and sigs:
                break
            sys.exit(2)
        if not res:
            break
        for s in res:
            bt = s.get("blockTime") or 0
            if bt * 1000 >= T_FROM and not s.get("err"):
                sigs.append([s["signature"], bt])
        before = res[-1]["signature"]
        if (res[-1].get("blockTime") or 0) * 1000 < T_FROM:
            break
        if calls % 10 == 0:
            log("signature pages", calls, "kept", len(sigs), "at", dt.datetime.utcfromtimestamp(res[-1].get("blockTime") or 0))
    day = collections.Counter(dt.datetime.utcfromtimestamp(b).strftime("%m-%d") for _, b in sigs)
    log("signatures", len(sigs), "pages", calls, "per day", dict(sorted(day.items())))
    json.dump({"sigs": sigs, "source": "public", "to": t_to}, open(os.path.join(out, "sigs.json"), "w"))


def cmd_tx(sigf, i, n, out):
    """Env TX_FROM / TX_TO (UTC "YYYY-MM-DD HH:MM") limit the signatures by time; OLD/grads.json (an earlier run's graduations)
    skips the signatures whose second already gave a graduation. Transactions newer than version 0 are asked again with the
    version the RPC names (the first run asked for version 0 only and lost them as "rpc -32015")."""
    import concurrent.futures, re, threading
    sigs = json.load(open(sigf))["sigs"]
    lo = ms(os.environ["TX_FROM"]) if os.environ.get("TX_FROM") else 0
    hi = ms(os.environ["TX_TO"]) if os.environ.get("TX_TO") else 1 << 62
    sigs = [s for s in sigs if lo <= s[1] * 1000 < hi]
    old = os.path.join(os.environ.get("OLD") or "-", "grads.json")
    if os.path.exists(old):
        known = {g["t"] // 1000 for g in json.load(open(old))["grads"]}
        n0 = len(sigs)
        sigs = [s for s in sigs if s[1] not in known]
        log("signatures in the window", n0, "after skipping the seconds of known graduations", len(sigs))
    sigs = sigs[int(i)::int(n)]
    grads, miss, ver, lock = {}, collections.Counter(), collections.Counter(), threading.Lock()
    notes = []

    def one(s):
        v, enc = 0, "jsonParsed"
        for _ in range(4):
            st, j = post(PUBLIC_RPC, {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                                      "params": [s[0], {"encoding": enc, "maxSupportedTransactionVersion": v}]}, PGAP)
            if not isinstance(j, dict):
                return s, st, None
            e = j.get("error")
            if not e:
                return s, st, j.get("result")
            msg = str(e.get("message"))
            m = re.search(r"version \(?(\d+)\)?", msg)
            with lock:
                if len(notes) < 8 and msg[:60] not in [x[:60] for x in notes]:
                    notes.append(msg[:200])
            if e.get("code") == -32015 and m and int(m.group(1)) != v:
                v = int(m.group(1))
                continue
            if e.get("code") == -32602 and enc == "jsonParsed":
                enc = "json"
                continue
            return s, "rpc %s" % e.get("code"), None
        return s, "retries", None

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        for k, (s, st, tx) in enumerate(ex.map(one, sigs)):
            if not isinstance(tx, dict):
                miss[str(st)] += 1
                continue
            g = migration(tx)
            ver[str(tx.get("version"))] += 1
            if g:
                grads[g["mint"]] = g
                ver["grad v%s" % tx.get("version")] += 1
            if k % 500 == 499:
                log("tx", k + 1, "of", len(sigs), "graduations", len(grads), "missing", dict(miss), "versions", dict(ver),
                    "%.2f s each" % ((time.time() - t0) / (k + 1)))
    json.dump({"grads": list(grads.values()), "missing": dict(miss), "asked": len(sigs), "versions": dict(ver)}, open(out, "w"))
    log("done", len(sigs), "graduations", len(grads), "missing", dict(miss), "versions", dict(ver))
    for x in notes:
        log("rpc said:", x)


def klines(sym, t0, t1):
    out, s = [], t0
    while s < t1:
        st, j = None, None
        for _ in range(4):
            try:
                with urllib.request.urlopen(BN % (sym, s), timeout=30) as r:
                    j = json.loads(r.read())
                break
            except Exception:
                time.sleep(3)
        if not isinstance(j, list) or not j:
            break
        out += [[int(r[0]), float(r[4])] for r in j]
        s = int(j[-1][0]) + 3_600_000
    return out


def cmd_plan(src, out):
    """With env OLD (the branch bigsearchdata of an earlier run): its graduations are merged in, and plan.json / mints.json hold only
    the S1 pools and mints that run has no candles / launch facts for (final then merges both)."""
    os.makedirs(out, exist_ok=True)
    grads, info = {}, {}
    od = os.environ.get("OLD") or "-"
    if os.path.exists(os.path.join(od, "grads.json")):
        for g in json.load(open(os.path.join(od, "grads.json")))["grads"]:
            if g.get("pool") and g.get("t", 0) >= T_FROM:
                grads.setdefault(g["pool"], g)
        info["old"] = {"grads": len(grads)}
    for f in sorted(glob.glob(os.path.join(src, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "grads" not in d:
            continue
        info[os.path.basename(f)] = {k: d.get(k) for k in ("missing", "asked", "source")}
        for g in d["grads"]:
            if g.get("pool") and g.get("t", 0) >= T_FROM:
                grads.setdefault(g["pool"], g)
    gs = sorted(grads.values(), key=lambda g: g["t"])
    day = collections.Counter(dt.datetime.utcfromtimestamp(g["t"] / 1000).strftime("%m-%d") for g in gs)
    day10 = collections.Counter(dt.datetime.utcfromtimestamp(g["t"] / 1000).strftime("%m-%d") for g in gs if g["sol0"] >= MIN_SOL)
    log("graduations", len(gs), "per day", dict(sorted(day.items())), "with SOL side >= 10", dict(sorted(day10.items())))
    s1 = [g for g in gs if S1[0] <= g["t"] < S1[1] and g["sol0"] >= MIN_SOL]
    mints = [g["mint"] for g in gs if g["t"] < S1[1] and g["sol0"] >= MIN_SOL]
    if os.path.exists(os.path.join(od, "meta_s1.json")):
        import pandas as pd
        have = {g["pool"] for g in json.load(open(os.path.join(od, "meta_s1.json"))) if g.get("bars")}
        hm = set(pd.read_parquet(os.path.join(od, "chain_s1.parquet"), columns=["mint"])["mint"])
        log("S1 pools", len(s1), "of which new", sum(1 for g in s1 if g["pool"] not in have), "mints", len(mints),
            "of which new", sum(1 for m in mints if m not in hm))
        s1 = [g for g in s1 if g["pool"] not in have]
        mints = [m for m in mints if m not in hm]
    json.dump({"grads": gs, "files": info}, open(os.path.join(out, "grads.json"), "w"))
    json.dump({"grads": s1}, open(os.path.join(out, "plan.json"), "w"))
    json.dump({"mints": mints}, open(os.path.join(out, "mints.json"), "w"))
    t0 = ms("2026-10-15 00:00")
    mk = {s: klines(s, t0, int(time.time() * 1000)) for s in ("SOLUSDT", "BTCUSDT")}
    json.dump(mk, open(os.path.join(out, "market.json"), "w"))
    log("S1 pools", len(s1), "mints for launch facts", len(mints), "binance hours", {s: len(v) for s, v in mk.items()})


def cmd_final(candles, chain, plan, out):
    """With env OLD (see plan): the earlier run's candles, pools and launch facts are kept and the new ones added."""
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    od = os.environ.get("OLD") or "-"
    old = os.path.exists(os.path.join(od, "meta_s1.json"))
    frames, metas = [], []
    if old:
        frames.append(pd.read_parquet(os.path.join(od, "bars_s1.parquet")))
        metas += json.load(open(os.path.join(od, "meta_s1.json")))
    for f in sorted(glob.glob(os.path.join(candles, "**", "gt_*.json.gz"), recursive=True)):
        d = json.load(gzip.open(f))
        metas += d["meta"]
        rows = [[p] + r for p, rs in d["pools"].items() for r in rs]
        if rows:
            frames.append(pd.DataFrame(rows, columns=["pool", "t", "o", "h", "l", "c", "v"]))
        log(os.path.basename(f), "pools", len(d["pools"]), "done", d["done"], "of", d["planned"])
    b = pd.concat(frames, ignore_index=True).drop_duplicates(["pool", "t"]).sort_values(["pool", "t"])
    for c in "ohlcv":
        b[c] = b[c].astype("float32")
    b.to_parquet(os.path.join(out, "bars_s1.parquet"), index=False, compression="zstd")
    seen = {}
    for g in metas:
        if g["pool"] not in seen or (g.get("bars") and not seen[g["pool"]].get("bars")):
            seen[g["pool"]] = g
    planned = json.load(open(os.path.join(plan, "plan.json")))["grads"]
    if old:
        po = {g["pool"] for g in planned}
        planned = [g for g in json.load(open(os.path.join(od, "meta_s1.json"))) if g["pool"] not in po] + planned
        planned.sort(key=lambda g: g["t"])
    meta = [seen.get(g["pool"], dict(g, bars=0, missing=True)) for g in planned]
    json.dump(meta, open(os.path.join(out, "meta_s1.json"), "w"))
    for f in ("grads.json", "market.json"):
        os.replace(os.path.join(plan, f), os.path.join(out, f))
    if old:
        mk, mo = json.load(open(os.path.join(out, "market.json"))), json.load(open(os.path.join(od, "market.json")))
        if any(len(mk.get(k) or []) < len(mo.get(k) or []) for k in mo):
            os.replace(os.path.join(od, "market.json"), os.path.join(out, "market.json"))
    ch = os.path.join(chain, "chain.parquet")
    summ = {"planned": len(planned), "with candles": sum(1 for g in meta if g.get("bars")), "bars": int(len(b))}
    cs = [pd.read_parquet(ch)] if os.path.exists(ch) else []
    if old:
        summ["repair"] = {"new pools": len(json.load(open(os.path.join(plan, "plan.json")))["grads"]),
                          "new launch mints": int(len(cs[0])) if cs else 0}
        cs.append(pd.read_parquet(os.path.join(od, "chain_s1.parquet")))
    if cs:
        c = pd.concat(cs, ignore_index=True).drop_duplicates("mint")
        for col in c.columns:
            if c[col].dtype == object:
                c[col] = c[col].astype(object).where(c[col].notna(), None)
        c.to_parquet(os.path.join(out, "chain_s1.parquet"), index=False)
        summ["launch facts"] = {k: int(c[k].notna().sum()) for k in ("curve_creator", "created_s", "symbol", "f_keys") if k in c}
        summ["launch mints"] = int(len(c))
    if os.path.exists(os.path.join(chain, "wiki_top.json")):
        os.replace(os.path.join(chain, "wiki_top.json"), os.path.join(out, "wiki_top.json"))
    elif old and os.path.exists(os.path.join(od, "wiki_top.json")):
        os.replace(os.path.join(od, "wiki_top.json"), os.path.join(out, "wiki_top.json"))
    json.dump(summ, open(os.path.join(out, "summary.json"), "w"), indent=1)
    log("summary", summ)


if __name__ == "__main__":
    a = sys.argv[1:]
    {"sigs": lambda: cmd_sigs(a[1]), "tx": lambda: cmd_tx(a[1], a[2], a[3], a[4]), "plan": lambda: cmd_plan(a[1], a[2]),
     "final": lambda: cmd_final(a[1], a[2], a[3], a[4])}[a[0]]()
