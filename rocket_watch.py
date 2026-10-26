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
From memebot.LIVE_SELL_AT on it also looks at the Pick account's open positions every minute (the scan's list, memebot.LIVE_OPEN_ROW in
the app's live store): the Pick's own rule judged by memebot.chart_hit (the chart exit, since 24 Oct; memebot.hold_hit for a position
of the fixed rule before it) on the minute's low and high (a pool without candles on
DexScreener's price), the 6-hour limit at that minute's candle price (memebot.hold_x6); it buys and books nothing in the Pick account itself: its sales go to <dir>/pick_live.json, picklog/<UTC day>.jsonl and the live
row memebot.LIVE_WATCH_ROW, and the next scan books each at its minute. No push for them (sells are silent).
usage: python3 rocket_watch.py round --dir rk --radar radar-data-dir [--now ms] [--mock DIR]
       python3 rocket_watch.py watch --dir rk --until unix-seconds
  --mock DIR reads every answer from DIR (selftest_rocket): ds.json, gt_<pool>_ohlcv.json, gt_<pool>_trades.json, binance_<SYM>.json
"""
import argparse, datetime as dt, glob, gzip, json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import rocket as R
import memebot as M      # read only: the Pick account's rule (hold_hit, hold_end, pos_value) and its live-store row names

DS = "https://api.dexscreener.com/tokens/v1/solana/"
GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
BN = "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h&limit=26"
MODEL = os.path.join(HERE, "rocket_model.json")
MAX_SCORE = 24            # coins scored a round (2 GeckoTerminal calls each)
GT_GAP = 2.2              # s between GeckoTerminal calls (its public limit is about 30 a minute)
DS_GAP = 0.6
CHART_N = 150            # points of a position's price line (chart_add)
WATCH_S = 60              # s between two looks at the open positions between rounds (watch)
PICK_FILE = "pick_live.json"   # the Pick account's minute watch (memebot.LIVE_SELL_AT): the positions it watches and its sales
PICK_LOG = "picklog"      # ... and every sale it saw, one line each (picklog/<UTC day>.jsonl), for the review
PICK_KEEP_MS = 24 * 3_600_000   # a sale stays in the view this long after the scan stopped listing its position (it booked it)
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


def gt_candles(http, pool, since_ms, now, side="base"):
    """One-minute candles from since_ms to now (two pages when it is more than 1000 minutes); side: the pool's token they price (base,
    or quote for a pool whose base token is the other coin: memebot.UNIT_X)."""
    out, before = [], int(now // 1000)
    for _ in range(2):
        j = http.get(GT + "%s/ohlcv/minute?aggregate=1&limit=1000&currency=usd&token=%s&before_timestamp=%d" % (pool, side, before),
                     "gt_%s_ohlcv" % pool + ("" if side == "base" else "_" + side), GT_GAP)
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


def pick_list(mock=None):
    """The Pick account's open positions as the last scan left them (memebot.live_open: the live store's row memebot.LIVE_OPEN_ROW; with
    mock, <mock>/pickopen.json), or None when they cannot be read (then the watch keeps its own list)."""
    if mock:
        try:
            doc = json.load(open(os.path.join(mock, M.LIVE_OPEN_ROW + ".json")))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None
    try:
        import app
        return app.get_row(M.LIVE_OPEN_ROW) if app.enabled() else None
    except Exception as e:
        log("  the Pick's open positions not read: %s" % type(e).__name__)
        return None


def pick_load(d):
    """<dir>/pick_live.json: {"pos": {pid: the position as the scan listed it, plus "chk" (where the next look starts), "cpx", "now",
    "lo", "hi" (multiples of cpx), "seen"}, "sold": {pid: {"at", "why", "mult" (over the entry price, as booked), "eur", "pnl", ...}}}."""
    try:
        st = json.load(open(os.path.join(d, PICK_FILE)))
    except (OSError, ValueError):
        st = {}
    st = st if isinstance(st, dict) else {}
    for k in ("pos", "sold"):
        st[k] = {str(a): v for a, v in (st.get(k) or {}).items() if isinstance(v, dict)} if isinstance(st.get(k), dict) else {}
    return st


def pick_merge(st, src, now):
    """The scan's list (src) into the watch: a position it lists and the watch has not sold is watched (with the scan's candle entry price
    and last checked minute when it has them); one it no longer lists the scan has booked: it leaves the watch, and the watch's sale of
    it stays PICK_KEEP_MS for the app. No list (None): the watch keeps its own."""
    if not isinstance(src, dict) or not isinstance(src.get("open"), list):
        return
    ids = set()
    for r in src["open"]:
        if not isinstance(r, dict) or not r.get("id") or not r.get("pair") or not R.num(r.get("px")):
            continue
        pid = str(r["id"])
        ids.add(pid)
        if pid in st["sold"] and (st["sold"][pid].get("rule") == "chart") != M.is_chart(r):
            st["sold"].pop(pid)       # a sale by the other rule (a watch of older code saw it): the next scan would not book it, look again
        if pid in st["sold"]:
            continue                  # sold on the live chart: the next scan books it
        w = st["pos"].setdefault(pid, {})
        w.update({k: r.get(k) for k in ("sym", "addr", "pair", "px", "t", "entryAt", "ticket", "grp", "paper", "left")})
        if (R.num(r.get("cpx")) or 0) > 0 and not M.unit_off(r["cpx"], r.get("px")):
            w["cpx"] = R.num(r["cpx"])
        if (R.num(r.get("chk")) or 0) > (R.num(w.get("chk")) or 0):
            w["chk"] = R.num(r["chk"])
    for pid in [a for a in st["pos"] if a not in ids]:
        st["pos"].pop(pid)
    for pid, x in list(st["sold"].items()):
        if pid in ids:
            x.pop("booked", None)
        elif now - x.setdefault("booked", now) > PICK_KEEP_MS:
            st["sold"].pop(pid)
    st["list"] = R.num(src.get("t"))


def pick_candles(http, w, t0, entry, now):
    """A watched Pick position's minute candles since its entry, sorted: of the pool's side that prices its own coin (memebot.unit_ok
    against the entry price; w["tok"] remembers it), none when neither side does (then it is judged as a pool without candles). A cpx,
    last checked minute and high, low and level of the other coin's candles (watched before UNIT_X) are dropped: its own start over."""
    if M.unit_off(w.get("cpx"), entry):
        for k in ("cpx", "chk", "now", "hi", "lo", "lvl"):
            w.pop(k, None)
        log("  %s: the candles watched so far were another coin's, starting over on its own" % w.get("sym"))
    first = w.get("tok") if w.get("tok") in M.GT_SIDES else "base"
    for side in [first] + [x for x in M.GT_SIDES if x != first]:
        cs = sorted(tuple(float(R.num(x) or 0.0) for x in r[:5]) for r in gt_candles(http, w["pair"], t0 - 60_000, now, side))
        if not cs or M.unit_ok(cs, R.num(w.get("t")) or t0, entry):
            if cs:
                w["tok"] = side
            return cs
    w.pop("tok", None)
    return []


def check_pick(http, st, pairs, now):
    """One look at the Pick account's open positions on the live chart (from memebot.LIVE_SELL_AT on): GeckoTerminal's minute candles
    since the entry, memebot.hold_hit from where the last look ended (the Pick's own rule as the scan judges it: the low at -30%, the
    high at 11x, the stop first), else the 6-hour limit (memebot.hold_end) at that minute's candle price (memebot.hold_x6; without
    candles DexScreener's price now). A pool without candles (GeckoTerminal
    has none for some pools) is judged on DexScreener's price of the minute instead, as the scan judges it on its own price then. A sale is
    kept for the next scan, which books it at its minute. A position of the chart exit (memebot.is_chart: the Pick's rule since 24 Oct)
    is judged by memebot.chart_hit on the candles since the entry instead (its stop, trail and drop, booked at chart_hit's price, "rule":
    "chart"); without candles by its floor, 11x and its trail under the best DexScreener price seen ("dshi"). Returns the sales."""
    out = []
    if now < M.live_sell_at():
        return out
    for pid, w in sorted(st["pos"].items()):
        t0, entry = R.num(w.get("entryAt")) or R.num(w.get("t")), R.num(w.get("px"))
        if pid in st["sold"] or not t0 or not entry or not w.get("pair"):
            continue
        chart = M.is_chart(w)
        cs = pick_candles(http, w, t0, entry, now)
        hc = (M.chart_hit if chart else M.hold_hit)(cs, t0, R.num(w.get("chk")), R.num(w.get("cpx")))
        px = R.num((pick_pair(pairs.get(w.get("addr")), w["pair"]) or {}).get("priceUsd"))
        w["seen"] = now
        if hc["cpx"]:
            w["cpx"] = hc["cpx"]
        if hc["fresh"]:
            w["chk"] = cs[-1][0]       # the last minute may still run: the next look starts with it again
            mid = [c for c in cs if c[0] >= t0 - 60_000]
            w["now"] = round(cs[-1][4] / hc["cpx"], 4)
            w["hi"] = round(max([R.num(w.get("hi")) or 0.0] + [M.hold_wicks(c)[0] / hc["cpx"] for c in mid]), 4)
            w["lo"] = round(min([R.num(w.get("lo")) or 1e9] + [M.hold_wicks(c)[1] / hc["cpx"] for c in mid]), 4)
            if chart and hc.get("lvl"):
                w["lvl"] = hc["lvl"]
        end = M.hold_end(t0)
        x6 = M.hold_x6(cs, t0, hc["cpx"], True) if end and now >= end else None
        floor = 1.0 - (M.CHART_STOP if chart else M.HOLD_STOP)
        if chart and not hc["fresh"] and px:
            w["dshi"] = round(max(R.num(w.get("dshi")) or 1.0, px / entry), 4)
        if hc["hit"]:
            sale = {"at": int(hc["hit"]), "why": hc["why"], "mult": hc["mult"] if chart else (1.0 + M.HOLD_TP if hc["why"] == "tp" else min(hc["mult"], floor))}
        elif not hc["fresh"] and px and (px >= (1.0 + M.HOLD_TP) * entry or px <= floor * entry):
            # no candle came in: both levels on DexScreener's price of this minute (memebot.cmd_run's no-candle check, every minute)
            sale = {"at": int(now), "why": "tp" if px > entry else "stop", "mult": 1.0 + M.HOLD_TP if px > entry else px / entry}
        elif chart and not hc["fresh"] and px and w["dshi"] >= M.CHART_ARM and px <= (1.0 - M.CHART_TRAIL) * w["dshi"] * entry:
            sale = {"at": int(now), "why": "trail", "mult": px / entry}       # the trail on DexScreener's prices (a pool without candles)
        elif x6 or (end and now >= end and px):
            # at the minute of the limit at its candle's price (as the scan books it: a look can come a few minutes late, after a round);
            # a pool without candles at DexScreener's price now
            sale = {"at": int(end), "why": "time", "mult": x6} if x6 else {"at": int(now), "why": "time", "mult": px / entry}
        else:
            continue
        if chart:
            sale["rule"] = "chart"
        left = R.num(w.get("left")) or 1.0
        eur = M.pos_value(w, left, sale["mult"])
        sale.update(sym=w.get("sym"), t=int(now), eur=round(eur, 2), pnl=round(eur - (R.num(w.get("ticket")) or 0.0) * left, 2), entryAt=int(t0))
        st["sold"][pid] = sale
        out.append(dict(sale, id=pid))
        log("  Pick sell on the live chart %s x%.2f (%s) %+.2f" % (w.get("sym"), sale["mult"], sale["why"], sale["pnl"]))
    return out


def pick_doc(st, now):
    """The live row memebot.LIVE_WATCH_ROW: the last look, each watched position (where its next look starts, cpx, now / high / low as
    multiples of cpx) and the sales the scan has not booked yet or booked within PICK_KEEP_MS. Public data only."""
    keep = ("sym", "t", "entryAt", "chk", "cpx", "now", "hi", "lo", "lvl", "seen")
    return {"v": 1, "t": now, "since": M.live_sell_at(), "list": st.get("list"),
            "pos": {a: {k: w.get(k) for k in keep if k in w} for a, w in st["pos"].items() if a not in st["sold"]}, "sold": st["sold"]}


def pick_save(d, st, sold, now, mock=None):
    """The Pick watch's state to <dir>/pick_live.json (whole or not at all), its new sales to picklog/<UTC day>.jsonl and its view to the
    live row memebot.LIVE_WATCH_ROW (the app's Pick tab and the next scan read it; never in a mocked look)."""
    fn = os.path.join(d, PICK_FILE)
    with open(fn + ".tmp", "w") as fh:
        json.dump(st, fh, separators=(",", ":"))
    os.replace(fn + ".tmp", fn)
    if sold:
        os.makedirs(os.path.join(d, PICK_LOG), exist_ok=True)
        day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        with open(os.path.join(d, PICK_LOG, day + ".jsonl"), "a") as fh:
            for r in sold:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    if not mock:
        try:
            import app
            if app.enabled():
                app.put_row(M.LIVE_WATCH_ROW, pick_doc(st, now))
        except Exception as e:
            log("  the Pick watch's live row failed: %s" % type(e).__name__)


def watch(d, until, mock=None, clock=None, sleep=time.sleep, every=WATCH_S):
    """Between two rounds: every `every` seconds until `until` (ms), only the open positions: DexScreener's price and GeckoTerminal's
    candles since the last look, rule A (the same rule as the round; the candles cover the minutes between two looks, so how often it
    looks changes when a sell is seen, not what it books). A sell goes to rocket.json, the day's log, one push and the live row at
    once; the live row is refreshed every look, so the app's open positions move every minute. From memebot.LIVE_SELL_AT on the Pick
    account's open positions too (pick_list, check_pick, pick_save: the Pick's own rule, its sales for the next scan to book, no push).
    Nothing to watch in either account: it returns at once. Scoring and buying stay in the 15-minute round (the model was trained on
    15-minute steps; 24 coins need 48 GeckoTerminal calls)."""
    clock = clock or (lambda: time.time() * 1000)
    fn = os.path.join(d, "rocket.json")
    looks = sells = picks = 0
    while True:
        try:
            state = json.load(open(fn))
        except (OSError, ValueError):
            state = None
        book = R.Book((state or {}).get("book"))
        now = clock()
        pk = pick_load(d) if now >= M.live_sell_at() else None
        if pk is not None:
            pick_merge(pk, pick_list(mock), now)
        pk_open = bool(pk) and any(a not in pk["sold"] for a in pk["pos"])
        if not book.open and not pk_open:
            if pk is not None and (pk["pos"] or pk["sold"] or os.path.exists(os.path.join(d, PICK_FILE))):
                pick_save(d, pk, [], now, mock)          # the list the scan left (a booked sale, nothing open any more) for the app
            out = {"looks": looks, "sold": sells, "why": "no state" if state is None else "nothing open"}
            return dict(out, pick=picks) if picks else out
        if now >= until:
            out = {"looks": looks, "sold": sells, "why": "time"}
            return dict(out, pick=picks) if picks else out
        http = Http(mock)
        addrs = set(book.open) | ({w.get("addr") for w in pk["pos"].values() if w.get("addr")} if pk_open else set())
        pairs = ds_pairs(http, sorted(addrs))
        had = bool(book.open)
        closed = check_open(http, book, pairs, now) if had else []
        looks += 1
        sells += len(closed)
        if had and state is not None:
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
        if pk_open:
            sold = check_pick(http, pk, pairs, now)
            picks += len(sold)
            pick_save(d, pk, sold, now, mock)
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
