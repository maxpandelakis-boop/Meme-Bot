#!/usr/bin/env python3
"""rocket_watch.py: the rocket hunter's round (fake money only: it scores coins and books paper trades in its own account, it never
buys, signs or sends anything). rocket.yml runs one round every 15 minutes in GitHub Actions; rocket.py holds the logic.

One round:
  1. the coins: the launch radar's records of the last 18 hours (branch radar-data, db/memeradar/*.json: address, pool, pool time)
  2. DexScreener tokens/v1 (30 a request): price, market cap, liquidity, 24 h volume, 1 h and 6 h change -> rocket.universe
  3. for each coin in the universe whose last check is 15 minutes old or more (at most MAX_SCORE a round, the oldest check first):
     GeckoTerminal's one-minute candles since the pool opened and its latest trades -> rocket.features -> rocket.score
  4. a score at or over the model's cut buys the coin once on paper (20 at DexScreener's price); every open position gets the
     candles since its last check (its high and low) and the price now, and rule A (-30% / 11x / 6 h) sells it
  5. <dir>/rocket.json (the account, this round's scores, the counts) and <dir>/log/<UTC day>.jsonl (every score, for the
     forward test) go to the branch rocket-data; the scan job copies rocket.json into the app's page
BTC and SOL hourly candles come from Binance's public market-data mirror. The wallet memory (rocket_memory.json.gz on rocket-data:
wallets with 5 or more graduated coins of Aug-Oct 2026 and how they did) is read only.
Between two rounds, `watch` looks at the open positions only, every minute (rule A, a sell at once, the app's live row every look).
usage: python3 rocket_watch.py round --dir rk --radar radar-data-dir [--now ms] [--mock DIR]
       python3 rocket_watch.py watch --dir rk --until unix-seconds
  --mock DIR reads every answer from DIR (selftest_rocket): ds.json, gt_<pool>_ohlcv.json, gt_<pool>_trades.json, binance_<SYM>.json
"""
import argparse, datetime as dt, glob, gzip, json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import rocket as R

DS = "https://api.dexscreener.com/tokens/v1/solana/"
GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
BN = "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h&limit=26"
MODEL = os.path.join(HERE, "rocket_model.json")
MAX_SCORE = 24            # coins scored a round (2 GeckoTerminal calls each)
GT_GAP = 2.2              # s between GeckoTerminal calls (its public limit is about 30 a minute)
DS_GAP = 0.6
CHART_N = 150            # points of a position's price line (chart_add)
WATCH_S = 60              # s between two looks at the open positions between rounds (watch)
UA = {"User-Agent": "memebot rocket hunter (fake money only)", "Accept": "application/json"}
H = 3_600_000


def log(s):
    print(s, file=sys.stderr, flush=True)


class Http:
    def __init__(self, mock=None):
        self.mock, self.last, self.calls = mock, {}, {}

    def get(self, url, key, gap=0.0):
        self.calls[key.split("_")[0]] = self.calls.get(key.split("_")[0], 0) + 1
        if self.mock:
            fn = os.path.join(self.mock, key + ".json")
            return json.load(open(fn)) if os.path.exists(fn) else None
        host = urllib.parse.urlparse(url).hostname
        wait = self.last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        for k in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                    self.last[host] = time.time()
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                self.last[host] = time.time()
                if e.code == 429:
                    time.sleep(10 * (k + 1)); continue
                return None
            except Exception:
                time.sleep(2)
        return None


def candidates(radar_dir, now):
    out = {}
    for fn in sorted(glob.glob(os.path.join(radar_dir, "db", "memeradar", "*.json"))):
        try:
            doc = json.load(open(fn))
        except (OSError, ValueError):
            continue
        for a, rec in (doc.get("coins") or {}).items():
            pool_ms, pair = R.num(rec.get("pool")), rec.get("pair")
            if not pool_ms or not pair:
                continue
            age = (now - pool_ms) / 60_000
            if R.START_MIN <= age <= R.END_MIN + 30:
                out[a] = {"addr": a, "pair": pair, "pool_ms": pool_ms, "sym": rec.get("sym")}
    return out


def ds_pairs(http, addrs):
    got = {}
    for i in range(0, len(addrs), 30):
        j = http.get(DS + ",".join(addrs[i:i + 30]), "ds" if http.mock else "ds_%d" % i, DS_GAP)
        for p in j if isinstance(j, list) else []:
            a = ((p or {}).get("baseToken") or {}).get("address")
            if a:
                got.setdefault(a, []).append(p)
    return got


def pick_pair(pairs, pool):
    for p in pairs or []:
        if p.get("pairAddress") == pool:
            return p
    return max(pairs or [{}], key=lambda p: R.num((p.get("liquidity") or {}).get("usd")) or 0) if pairs else None


def gt_candles(http, pool, since_ms, now):
    """One-minute candles from since_ms to now (two pages when it is more than 1000 minutes)."""
    out, before = [], int(now // 1000)
    for _ in range(2):
        j = http.get(GT + "%s/ohlcv/minute?aggregate=1&limit=1000&currency=usd&token=base&before_timestamp=%d" % (pool, before),
                     "gt_%s_ohlcv" % pool, GT_GAP)
        rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [] if isinstance(j, dict) else []
        rows = [[r[0] * 1000] + list(r[1:6]) for r in rows if isinstance(r, list) and len(r) >= 6]
        out += rows
        if not rows or http.mock:
            break
        oldest = min(r[0] for r in rows)
        if oldest <= since_ms:
            break
        before = int(oldest // 1000) - 1
    return out


def gt_trades(http, pool):
    j = http.get(GT + "%s/trades" % pool, "gt_%s_trades" % pool, GT_GAP)
    out = []
    for d in ((j or {}).get("data") or []) if isinstance(j, dict) else []:
        at = (d or {}).get("attributes") or {}
        try:
            t = dt.datetime.fromisoformat(str(at.get("block_timestamp")).replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            continue
        out.append({"t": t, "buy": at.get("kind") == "buy", "usd": R.num(at.get("volume_in_usd")) or 0.0, "who": at.get("tx_from_address")})
    return out


def market(http):
    m, sol = {}, None
    for sym, k in (("BTCUSDT", "btc"), ("SOLUSDT", "sol")):
        j = http.get(BN % sym, "binance_%s" % sym)
        c = [float(r[4]) for r in j] if isinstance(j, list) and len(j) >= 26 else None
        if c:
            # the last fully closed hour (the open one is the list's last row), as features.market_all
            m[k + "_1h"] = c[-2] / c[-3] - 1
            m[k + "_24h"] = c[-2] / c[-26] - 1
            if k == "sol":
                sol = c[-1]
    return m, sol


def load_memory(d):
    fn = os.path.join(d, "rocket_memory.json.gz")
    try:
        with gzip.open(fn, "rt") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def live_doc(book, now, cut, scored, closed):
    """The small doc of the app's live row "rocket": the account's summary, the open positions (now and high as multiples), the last
    10 sells and the round's best 5 scores. Public data only (coins, prices, fake-money results)."""
    keep = ("addr", "sym", "t", "px", "score", "now", "hi", "lo", "out", "mult", "eur", "why", "chart")
    return {"v": 1, "t": now, "cut": cut, "summary": book.summary(),
            "open": [{k: p.get(k) for k in keep if k in p} for p in book.open.values()],
            "closed": [{k: p.get(k) for k in keep if k in p} for p in book.closed[-10:]],
            "soldNow": [p.get("addr") for p in closed],
            "top": [{k: r.get(k) for k in ("addr", "sym", "score", "age", "buy")} for r in sorted(scored, key=lambda r: -r["score"])[:5]]}


def chart_add(pos, cs, px, now):
    """The position's price line for the app's chart: [minutes since the buy, close as a multiple of the buy price] from the
    one-minute candles of each look (the buy itself is [0, 1]); at most CHART_N points (older ones thinned, the newest kept)."""
    bp, t0 = R.num(pos.get("px")), pos["t"]
    if not bp or bp <= 0:
        return
    pts = {int(m): v for m, v in (pos.get("chart") or [[0, 1.0]]) if isinstance(m, (int, float))}
    for r in cs:
        m = int((r[0] - t0) // 60_000)
        if m >= 0 and R.num(r[4]):
            pts[m] = round(float(r[4]) / bp, 4)
    if px and now > t0:
        pts[max(0, int((now - t0) // 60_000))] = round(px / bp, 4)
    pts.setdefault(0, 1.0)
    ch = sorted([m, v] for m, v in pts.items())
    while len(ch) > CHART_N:
        ch = ch[:1] + ch[1:-40:2] + ch[-40:]             # thin the older part, keep the buy and the last 40 minutes
    pos["chart"] = ch


def slim(book):
    """Only the last 10 sells keep their price line (the app shows those), so rocket.json stays small."""
    for p in book.closed[:-10]:
        p.pop("chart", None)


def check_open(http, book, pairs, now):
    """The open positions: their high and low since the last look (one-minute candles), the price now, rule A. Returns the sells."""
    closed = []
    for a, pos in list(book.open.items()):
        p = pick_pair(pairs.get(a), pos.get("pool"))
        last = R.num(pos.get("seen")) or pos["t"]
        cs = gt_candles(http, pos.get("pool"), last, now) if pos.get("pool") else []
        # from the buy on (the minute before the buy is not the position's; its low could stop it at once), then one minute of
        # overlap between two looks
        cs = [r for r in cs if r[0] >= (last if not pos.get("seen") else last - 60_000)]
        hi = max((float(r[2]) for r in cs), default=None)
        lo = min((float(r[3]) for r in cs), default=None)
        px = R.num((p or {}).get("priceUsd"))
        pos["seen"] = now
        chart_add(pos, cs, px, now)
        out = book.update(a, now, hi=hi, lo=lo, px=px)
        if out:
            closed.append(out)
            log("  paper sell %s x%.2f (%s) %+.2f" % (out.get("sym"), out["mult"], out["why"], out["eur"]))
    return closed


def watch(d, until, mock=None, clock=None, sleep=time.sleep, every=WATCH_S):
    """Between two rounds: every `every` seconds until `until` (ms), only the open positions: DexScreener's price and GeckoTerminal's
    candles since the last look, rule A (the same rule as the round; the candles cover the minutes between two looks, so how often it
    looks changes when a sell is seen, not what it books). A sell goes to rocket.json, the day's log, one push and the live row at
    once; the live row is refreshed every look, so the app's open positions move every minute. Nothing to watch: it returns at once.
    Scoring and buying stay in the 15-minute round (the model was trained on 15-minute steps; 24 coins need 48 GeckoTerminal calls)."""
    clock = clock or (lambda: time.time() * 1000)
    fn = os.path.join(d, "rocket.json")
    looks = sells = 0
    while True:
        try:
            state = json.load(open(fn))
        except (OSError, ValueError):
            return {"looks": looks, "sold": sells, "why": "no state"}
        book = R.Book(state.get("book"))
        if not book.open:
            return {"looks": looks, "sold": sells, "why": "nothing open"}
        now = clock()
        if now >= until:
            return {"looks": looks, "sold": sells, "why": "time"}
        http = Http(mock)
        closed = check_open(http, book, ds_pairs(http, sorted(book.open)), now)
        looks += 1
        sells += len(closed)
        slim(book)
        state["book"] = book.doc()
        with open(fn + ".tmp", "w") as fh:
            json.dump(state, fh, separators=(",", ":"))
        os.replace(fn + ".tmp", fn)
        if closed:
            os.makedirs(os.path.join(d, "log"), exist_ok=True)
            day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
            with open(os.path.join(d, "log", day + ".jsonl"), "a") as fh:
                for r in closed:
                    fh.write(json.dumps(dict(r, closed=True), separators=(",", ":")) + "\n")
        if not mock:
            try:
                import app
                if closed:
                    app.notify_rocket([], book.summary(), closed)
                if app.enabled():
                    app.put_row("rocket", live_doc(book, now, state.get("cut"), state.get("top") or [], closed))
            except Exception as e:
                log("  push or live row failed: %s" % type(e).__name__)
        wait = min(every * 1000, until - clock()) / 1000
        if wait > 0:
            sleep(wait)


def round_(d, radar_dir, now, mock=None):
    http = Http(mock)
    model = json.load(open(MODEL))
    state = {}
    try:
        state = json.load(open(os.path.join(d, "rocket.json")))
    except (OSError, ValueError):
        pass
    book = R.Book(state.get("book"))
    checked = state.get("checked") if isinstance(state.get("checked"), dict) else {}
    memory = load_memory(d)
    mkt, sol_usd = market(http)
    cand = candidates(radar_dir, now)
    addrs = sorted(set(cand) | set(book.open))
    pairs = ds_pairs(http, addrs)
    scored, due = [], []
    for a, c in cand.items():
        p = pick_pair(pairs.get(a), c["pair"])
        if not p:
            continue
        mc = R.num(p.get("marketCap")) or R.num(p.get("fdv"))
        liq = R.num((p.get("liquidity") or {}).get("usd"))
        vol = R.num((p.get("volume") or {}).get("h24"))
        ch = p.get("priceChange") or {}
        age = (now - c["pool_ms"]) / 60_000
        if book.bought(a) or not R.universe(age, mc, liq, vol, R.num(ch.get("h1")), R.num(ch.get("h6"))):
            continue
        if now - (R.num(checked.get(a)) or 0) < (R.STEP_MIN - 1) * 60_000:
            continue
        due.append((R.num(checked.get(a)) or 0, a, c, p, mc, liq, vol))
    due.sort(key=lambda x: x[0])
    for _, a, c, p, mc, liq, vol in due[:MAX_SCORE]:
        pool = p.get("pairAddress") or c["pair"]
        cs = gt_candles(http, pool, c["pool_ms"], now)
        tr = gt_trades(http, pool)
        f = R.features(cs, tr, c["pool_ms"], now, sol_usd, mc, liq, vol, mkt, memory) if sol_usd else None
        sc = R.score(model, f)
        checked[a] = now
        if sc is None:
            continue
        px = R.num(p.get("priceUsd"))
        row = {"t": now, "addr": a, "sym": c.get("sym"), "pool": pool, "age": round((now - c["pool_ms"]) / 60_000), "score": round(sc, 5),
               "mc": round(mc or 0), "px": px, "reach": f.get("_reach"), "buy": False}
        if sc >= model["cut"] and book.buy(a, c.get("sym"), px, now, sc, model["cut"], pool):
            row["buy"] = True
            log("  paper buy %s (%s) score %.4f >= %.4f at %s" % (c.get("sym"), a, sc, model["cut"], px))
        scored.append(row)
    closed = check_open(http, book, pairs, now)
    # one push for the round's paper buys and sells; the account to the app's live store (row "rocket"), so the app can show it
    # between two scans
    buys = [dict(r, cut=model["cut"]) for r in scored if r["buy"]]
    if not mock:
        try:
            import app
            if buys or closed:
                out = app.notify_rocket(buys, book.summary(), closed)
                log("  push: %s" % {k: v for k, v in (out or {}).items() if k in ("sent", "skipped", "failed")})
            if app.enabled():
                app.put_row("rocket", live_doc(book, now, model["cut"], scored, closed))
        except Exception as e:
            log("  push or live row failed: %s" % type(e).__name__)
    for a in [a for a, t in checked.items() if now - (R.num(t) or 0) > 26 * H]:
        checked.pop(a, None)
    scored.sort(key=lambda r: -r["score"])
    slim(book)
    doc = {"v": 1, "t": now, "book": book.doc(), "checked": checked, "round": {"candidates": len(cand), "scored": len(scored),
           "bought": sum(1 for r in scored if r["buy"]), "closed": len(closed), "calls": http.calls, "memory": len(memory)},
           "top": scored[:12], "cut": model["cut"], "model": {"made": model.get("made"), "rows": model.get("rows"), "src": model.get("src")}}
    os.makedirs(os.path.join(d, "log"), exist_ok=True)
    with open(os.path.join(d, "rocket.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    with open(os.path.join(d, "log", day + ".jsonl"), "a") as fh:
        for r in scored:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
        for r in closed:
            fh.write(json.dumps(dict(r, closed=True), separators=(",", ":")) + "\n")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["round", "watch"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--radar")
    ap.add_argument("--until", type=float, help="watch: stop at this Unix time (s)")
    ap.add_argument("--now", type=float)
    ap.add_argument("--mock")
    a = ap.parse_args(argv)
    os.makedirs(a.dir, exist_ok=True)
    if a.cmd == "watch":
        print(json.dumps(watch(a.dir, (a.until or 0) * 1000, a.mock)))
        return
    if not a.radar:
        ap.error("round needs --radar")
    doc = round_(a.dir, a.radar, a.now or time.time() * 1000, a.mock)
    print(json.dumps({"round": doc["round"], "summary": doc["book"]["summary"]}))


if __name__ == "__main__":
    main()
