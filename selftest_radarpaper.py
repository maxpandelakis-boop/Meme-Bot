#!/usr/bin/env python3
"""selftest_radarpaper.py: checks RA1 to RA10 of the radar account (radar_paper.py, page_radarpaper.py; fake money only, nothing is
bought). Synthetic radar records and minute candles; GeckoTerminal is a local mock.

  python3 selftest_radarpaper.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                    import selftest_radarpaper; selftest_radarpaper.checks(check)

RA1  the buys from the radar records: each round's best 5 in the radar's order (good, watch, trap; then points, liquidity), a coin
     once (in its first round among the best 5, no digging deeper), the green flag of that round, no coin without "top", no rating
     after the pool turned 10 minutes, the radar's price only at first sight, a doc is the buy (never moved to another round)
RA2  the sale on synthetic minute candles: stop at the confirmed level, a glitch low print sells nothing, take-profit at the first
     accepted level (the close, not 11x), a one-candle 300x and a dust print are no price, a dead pool (collapse, a later point that
     found it gone) is a total loss at that time, the time exit, the earlier of stop and take-profit, a supported run to 300x
RA3  the paper fees: eur == memebot.pos_value on a 3 EUR young paper position, by hand too
RA4  radar_paper run against the mock: open docs inside 6 h (no request), oldest first and at most MAX_ITEMS a run, closed and
     void docs, empty answers -> waiting -> estimate (rug when a later price found the pool gone, else void), a 5xx under 48 h
     settles nothing, a second run rewrites nothing
RA5  the GeckoTerminal budget inside peak.py run: peak.py's own windows first, then at most 15 radar windows, oldest first, on
     what is left of the same deadline; with no time left the radar asks nothing and peak.py's own result is unchanged
RA6  the trader's files are byte for byte the same; the radar account writes only db/memeradarpaper and candles/*_rp<minute>.txt
RA7  the docs survive bot.py prune and travel with bot.py sync (and the candles do not)
RA8  the two accounts (all 5, green only): invested, back, P/L, win rate, n, open, the best and worst trade, the hindsight sums
RA9  the page block: numbers from the docs, escaped names, the states (no round, rounds without a coin, all inside 6 h, pricing,
     an unreadable account), the fake-money note once, no em dash, its place in the account block (after "Without the stop-loss")
RA10 Chromium at 390 and 1280 px, light and dark: no sideways scroll, tiles stacked on the phone and side by side wide, 44 px
     folds, nothing past the block's edge; screenshots
"""
import contextlib, glob, html, json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import peak as P
import radar_paper as RP

MIN, H = 60_000, 3_600_000
TA = 1791983760000                  # a round at a whole minute (2026-10-14 13:16 UTC)
TB, TC = TA + H, TA + H + 3 * MIN   # the next hourly round and a round started by hand 3 minutes later
XSS = "<img src=x onerror=alert(1)>"
SHOTS = os.environ.get("MEMEBOT_SHOTS") or os.path.join(tempfile.gettempdir(), "radarpaper-shots")


# ---------------------------------------------------------------- fixtures
def rec(addr, sym, first, rt, top=True, px=1e-5, liq=20000.0, mc=60000.0, pool=None, later=None, name=""):
    """A radar record as launch_radar.new_rec writes it, rated rt = [(time, verdict, points), ...]."""
    out = {"addr": addr, "sym": sym, "name": name or sym, "pair": "RP" + addr, "dex": "pumpswap", "lp": "Pump.Fun", "found": ["pf:graduated"], "mint": None,
           "pool": pool if pool is not None else first - 5 * MIN, "first": first, "seenAge": 5.0, "px": px, "liq": liq, "mc": mc,
           "rt": [[t, v, pts, 0] for t, v, pts in rt], "good": next((t for t, v, _ in rt if v == "good"), None), "goodPx": None, "sig": {}, "chk": {},
           "push": None, "later": later or {}, "peak60": None, "out": None}
    if top:
        out["top"] = 1
    return out


def write_records(d, recs):
    by = {}
    for r in recs:
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(r["first"] // 1000))
        by.setdefault(hour, {"v": 1, "hour": hour, "t": int(time.mktime(time.strptime(hour, "%Y-%m-%dT%H"))) * 1000, "upd": r["first"], "coins": {}})["coins"][r["addr"]] = r
    os.makedirs(os.path.join(d, "db", "memeradar"), exist_ok=True)
    for hour, doc in by.items():
        json.dump(doc, open(os.path.join(d, "db", "memeradar", hour + ".json"), "w"))


def round_recs():
    """Round A (7 coins rated: a8 too old, a7 never in a top 5), round B (6 rated, b1 sixth), round C (b1 good, bought there)."""
    later_gone = {"60": {"t": TA + 60 * MIN, "gone": True}}
    return [rec("a1", "GOODONE", TA, [(TA, "good", 1.0)], liq=10000.0),
            rec("a2", "GOODTWO", TA, [(TA, "good", 0.0), (TB, "good", 0.0)]),
            rec("a3", "WATCHY", TA, [(TA, "watch", 2.0)]),
            rec("a4", "TRAPPY", TA, [(TA, "trap", 3.0)]),
            rec("a5", "GONER", TA, [(TA, "trap", 5.0)], later=later_gone),
            rec("a6", "SIXTH", TA, [(TA, "trap", 9.0)]),
            rec("a7", "NOTOP", TA, [(TA, "good", 0.0)], top=False),
            rec("a8", "TOOOLD", TA, [(TA, "good", 0.0)], pool=TA - 11 * MIN),
            rec("bad", "BROKEN", TA, []) | {"rt": [["x"], None, [None, "good"]]},
            rec("b1", "LATEGOOD", TB, [(TB, "trap", 9.0), (TC, "good", 0.0)], pool=TB - 4 * MIN),
            rec("b2", "SPIKE", TB, [(TB, "trap", 1.0)]),
            rec("b3", "DUSTY", TB, [(TB, "trap", 2.0)]),
            rec("b4", "FLAT", TB, [(TB, "trap", 3.0)]),
            rec("b5", XSS, TB, [(TB, "trap", 4.0)]),
            rec("b6", "NOCANDLE", TB, [(TB, "trap", 5.0)])]


def series(t0, mults, vol=2000.0, px=1e-5):
    """Minute candles [ms, o, h, l, c, vol] from the minute holding t0, these closes (times px)."""
    s = t0 // MIN * MIN
    return [[s + i * MIN, px * m, px * m, px * m, px * m, vol(i) if callable(vol) else vol] for i, m in enumerate(mults)]


def pool_candles():
    """The mock's candles per pool (whole 6 hours and a bit)."""
    flat = lambda t, f=lambda i: 1.0 + 0.001 * i: series(t, [f(i) for i in range(372)])
    return {"RPa1": series(TA, [1.0] * 10 + [0.9, 0.8, 0.65, 0.6] + [0.6] * 358),                    # stop at 0.65 (minute 12)
            "RPa2": series(TA, [1.0] * 10 + [2, 4, 8, 15, 15, 16] + [16] * 356),                      # take-profit at 15x (minute 13)
            "RPa3": flat(TA),                                                                        # time: the close at 6 h
            "RPa4": series(TA, [1.0] * 10 + [1.3, 1.2, 0.01] + [0.01] * 359),                         # a collapse: total loss
            # RPa5: no candles (404) -> estimate: its record found the pool gone at 60 min -> rug
            "RPb2": series(TB, [1.0] * 10 + [300.0] + [1.1] * 361),                                  # one candle at 300x: no price
            "RPb3": series(TB, [1.0] * 10 + [300.0] + [1.2] * 361, vol=lambda i: 3.0 if i == 10 else 2000.0),   # a dust print
            "RPb4": flat(TB, lambda i: 0.95),
            "RPb5": flat(TB, lambda i: 1.4),
            # RPb6: no candles and no sign of a dead pool -> void after 3 empty answers
            "RPb1": "500"}                                                                          # a 5xx: settles nothing under 48 h


class GT:
    """A mock GeckoTerminal: OHLCV of the pools it knows (newest first, as GT sends them), 404 for others, 500 for "500"; every request
    is noted as (pool, aggregate); an optional delay per answer."""

    def __init__(self, pools, delay=0.0):
        self.pools, self.delay, self.calls, self.lock = pools, delay, [], threading.Lock()

    def answer(self, path, query):
        m = re.search(r"/pools/([^/]+)/ohlcv/minute", path)
        if not m:
            return 404, {}
        pool = urllib.parse.unquote(m.group(1))
        q = urllib.parse.parse_qs(query)
        before, agg = int(q["before_timestamp"][0]), int(q["aggregate"][0])
        with self.lock:
            self.calls.append((pool, agg))
        if self.delay:
            threading.Event().wait(self.delay)     # a real wait: selftest.main replaces time.sleep with a no-op
        c = self.pools.get(pool)
        if c == "500":
            return 500, {}
        if c is None or agg != 1:
            return 404, {}
        rows = [[r[0] // 1000] + r[1:] for r in c if r[0] // 1000 <= before][-400:]
        return 200, {"data": {"attributes": {"ohlcv_list": list(reversed(rows))}}}


def serve(gt):
    class Hd(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            code, body = gt.answer(u.path, u.query)
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def docs_of(d):
    return {k: v for k, v in M.load_docs(d, RP.COLL).items()}


def raw_docs(d):
    return {os.path.basename(f): open(f, "rb").read() for f in sorted(glob.glob(os.path.join(d, "db", RP.COLL, "*.json")))}


def tree(d, skip=("db/memeradarpaper/", "candles/", ".rptmp/", ".peaktmp/")):
    out = {}
    for f in glob.glob(os.path.join(d, "**", "*"), recursive=True):
        rel = os.path.relpath(f, d)
        if os.path.isfile(f) and not rel.startswith(skip):
            out[rel] = open(f, "rb").read()
    return out


def quiet():
    return contextlib.redirect_stderr(open(os.devnull, "w"))


# ---------------------------------------------------------------- the checks
def checks(check):
    print("== radar account: 3 EUR on each launch-radar round's best 5, sold by the paper rules on minute candles (radar_paper.py, page_radarpaper.py)")
    tmp = tempfile.mkdtemp(prefix="memebot-rp-")
    try:
        _buys(check, tmp)
        _sales(check)
        d, now = _run(check, tmp)
        _budget(check, tmp)
        _sync(check, tmp, d, now)
        _accounts(check, d, now)
        page = _page(check, tmp, d, now)
        _browser(check, page)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _buys(check, tmp):
    recs = round_recs()
    b = RP.buys_of(recs)
    order = lambda t: [x["addr"] for x in sorted(b.values(), key=lambda x: (x["round"], x["rank"])) if x["round"] == t]
    check(order(TA) == ["a2", "a1", "a3", "a4", "a5"] and [b[a]["rank"] for a in order(TA)] == [1, 2, 3, 4, 5] and "a6" not in b and "a7" not in b and "a8" not in b
          and "bad" not in b,
          "RA1 round A's best 5 in the radar's order: the good ones first (fewer points first), then watch, then trap; the sixth, a coin never in a top "
          "5 and a coin rated after its pool turned 10 minutes are not bought, a record with unreadable ratings is skipped (%s)" % order(TA))
    check(order(TB) == ["b2", "b3", "b4", "b5", "b6"] and order(TC) == ["b1"] and b["b1"]["rank"] == 1 and b["b1"]["px"] is None and b["b1"]["green"] is True
          and b["b1"]["entryAt"] == TC and b["a2"]["round"] == TA and len(b) == 11,
          "RA1 a coin once: GOODTWO, rated again in round B, stays bought in round A (no sixth coin moves up); LATEGOOD, sixth in round B, is "
          "bought in round C, where it was good: at that round's time, without the radar's first-sight price (the candle's close is paid)")
    # the radar every 5 minutes: all of the best 5 only in the first round of each UTC hour, in the other rounds only a coin rated good
    TP = TA - 15 * MIN                   # 13:01: the first round of 13 h (round A at 13:16 is not; its coins come from the old rule's test above)
    r5 = [rec("p%d" % i, "PFIRST%d" % i, TP, [(TP, "watch", float(i))]) for i in range(1, 7)]
    r5 += [rec("q1", "QWATCH", TP + 5 * MIN, [(TP + 5 * MIN, "watch", 0.0)]), rec("q2", "QGOOD", TP + 5 * MIN, [(TP + 5 * MIN, "good", 1.0)]),
           rec("r1", "RNEXTHOUR", TP + H, [(TP + H, "trap", 4.0)])]
    b5 = RP.buys_of(r5)
    check(sorted(b5) == ["p1", "p2", "p3", "p4", "p5", "q2", "r1"] and b5["q2"]["entryAt"] == TP + 5 * MIN and b5["q2"]["green"] is True
          and b5["r1"]["entryAt"] == TP + H and RP.counted(TP, {int(TP // H): TP}) and not RP.counted(TP + 5 * MIN, {int(TP // H): TP}),
          "RA1 the radar every 5 minutes: the first round of each UTC hour has its best 5 bought (not the sixth), a later round of that hour only its "
          "coin rated good (QGOOD, not QWATCH), the next hour's first round its best 5 again: about 5 buys an hour plus the greens (%s)" % sorted(b5))
    greens = sorted(a for a, x in b.items() if x["green"])
    check(greens == ["a1", "a2", "b1"] and b["a1"]["px"] == 1e-5 and b["a3"]["verdict"] == "watch" and b["a4"]["pts"] == 3.0
          and b["a2"]["id"] == "2026-10-14T1316-GOODTWO-a2" and b["b5"]["id"].endswith("-imgsrcxonerr-b5") and re.match(r"^[\w-]+$", b["b5"]["id"]),
          "RA1 green = rated good in its round (GOODONE, GOODTWO, LATEGOOD); the radar's price at first sight; ids are file names in time order")
    d = os.path.join(tmp, "ra1")
    write_records(d, recs)
    RP.write_doc(d, "old-b1", RP.doc_of(dict(b["b1"], id="old-b1", round=TB, entryAt=TB, end=TB + 6 * H, px=2e-5), TB, "open"))
    buys, docs = RP.all_buys(d)
    mine = [x for x in buys.values() if x["addr"] == "b1"]
    check(len(mine) == 1 and mine[0]["id"] == "old-b1" and mine[0]["entryAt"] == TB and mine[0]["px"] == 2e-5 and len(buys) == 11 and "old-b1" in docs,
          "RA1 a doc is the buy: a coin with a doc keeps its round and price and is not bought a second time from the records")


def _sales(check):
    e, end = TA, TA + 6 * H
    b = lambda **k: dict({"entryAt": e, "end": end, "px": 1e-5, "liq": 20000.0, "mc": 60000.0, "_rec": None}, **k)
    go = lambda c, **k: RP.price(c, b(**k))
    s = go(series(TA, [1.0] * 10 + [0.9, 0.8, 0.65, 0.6] + [0.6] * 358))
    g = go(series(TA, [1.0] * 10 + [0.2] + [1.0] * 361))
    check(s["state"] == "closed" and s["why"] == "stop" and s["x"] == 0.65 and s["exitAt"] == TA + 12 * MIN and g["why"] == "time" and g["x"] == 1.0,
          "RA2 stop: the first close at or below -30%% that the next close holds, booked at that level (0.65x at minute 12); one glitch print to 0.2x "
          "that the next close took back sells nothing (%s, %s)" % (s["why"], g["why"]))
    t = go(series(TA, [1.0] * 10 + [2, 4, 8, 15, 15, 16] + [16] * 356))
    one = go(series(TA, [1.0] * 10 + [300.0] + [1.1] * 361))
    du = go(series(TA, [1.0] * 10 + [300.0] + [1.2] * 361, vol=lambda i: 3.0 if i == 10 else 2000.0))
    check(t["why"] == "tp" and t["x"] == 15.0 and t["exitAt"] == TA + 13 * MIN and t["best"] == 16.0 and RP.value(t["x"]) > RP.value(RP.TP_X)
          and one["why"] == "time" and one["x"] == 1.1 and one["rawX"] == 300.0 and one["best"] == 1.1 and any(c.startswith("unconfirmed: 300x") for c in one["cut"])
          and du["why"] == "time" and du["rawX"] == 300.0 and du["best"] == 1.2 and any(c.startswith("dust: 300x") for c in du["cut"]),
          "RA2 take-profit at the first level of 11x or more the next close confirms, booked at that close (15x, not 11x); a 300x print for one "
          "candle, or on $3 of volume, is no price: no take-profit, the raw 300x stays only in rawX with its cut")
    dead = go(series(TA, [1.0] * 10 + [1.3, 1.2, 0.01] + [0.01] * 359))
    gone = go(series(TA, [1.0 + 0.001 * i for i in range(372)]), _rec={"first": TA, "px": 1e-5, "liq": 20000.0, "later": {"60": {"t": TA + 60 * MIN, "gone": True}}})
    check(dead["why"] == "rug" and dead["x"] == 0.0 and dead["exitAt"] == TA + 12 * MIN and any(c.startswith("collapse") for c in dead["cut"])
          and gone["why"] == "rug" and gone["x"] == 0.0 and gone["exitAt"] == TA + 60 * MIN and RP.value(0.0) == 0.0,
          "RA2 a dead pool is a total loss at the time it died: a collapse to 1%% (minute 12) and a pool the radar's later price found gone (60 min) "
          "both sell at 0, never at a print after it")
    tm = go(series(TA, [1.0 + 0.001 * i for i in range(372)]))
    both = go(series(TA, [1.0] * 10 + [0.6, 0.6] + [12.0] * 360))
    big = go(series(TA, [1.0] * 10 + [2, 3, 5, 8, 12, 20, 40, 80, 160, 300] + [300] * 352, vol=50000.0))
    allust = go(series(TA, [1.0] * 372, vol=5.0))
    unit = go(series(TA, [1.0] * 372), _rec={"first": TA + MIN, "px": 1e-2, "liq": 50000.0, "later": {}}, px=None)
    check(tm["why"] == "time" and abs(tm["x"] - 1.359) < 1e-9 and tm["exitAt"] == end and both["why"] == "stop" and both["x"] == 0.6
          and big["why"] == "tp" and big["x"] == 12.0 and big["best"] == 300.0 and allust["why"] == "rug" and allust["x"] == 0.0
          and unit["state"] == "void" and unit["why"] == "unit",
          "RA2 time: the close at 6 h (1.359x); the earlier of stop and take-profit wins (a stop at 0.6x before 12x); a supported run to 300x sells "
          "at the first accepted level of 11x or more (12x) while its best within 6 h is 300x; only dust for 6 h is a total loss; candles in "
          "another unit than DexScreener's price are not booked (void)")


def _run(check, tmp):
    d = os.path.join(tmp, "ra4")
    write_records(d, round_recs())
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    json.dump({"paperSince": TA - 10 * H, "paperRule": M.PAPER_RULE}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    os.makedirs(os.path.join(d, "db", "memepos"), exist_ok=True)
    json.dump({"grp": "young", "t": TA - 9 * H, "entryAt": TA - 9 * H, "px": 1.0, "ticket": 3.0, "paper": M.PAPER_RULE, "pair": "PKold", "sym": "OLD"},
              open(os.path.join(d, "db", "memepos", "y-old.json"), "w"))
    gt = GT(pool_candles())
    srv, url = serve(gt)
    lines = []
    try:
        before = tree(d)
        o0 = RP.run(d, TA + 2 * H, mock=url, until=time.time() + 30, log=lines.append)
        n0 = len(gt.calls)
        st0 = sorted({v["state"] for v in docs_of(d).values()})
        n_open = len(docs_of(d))
        # every window over: 4 a run (oldest first) to see the cap and the order, then the rest
        now = TC + 6 * H + 10 * MIN
        saved, RP.MAX_ITEMS = RP.MAX_ITEMS, 4
        try:
            o1 = RP.run(d, now, mock=url, until=time.time() + 30, log=lines.append)
            asked1 = [p for p, _ in gt.calls]
            d1 = docs_of(d)
        finally:
            RP.MAX_ITEMS = saved
        o2 = RP.run(d, now, mock=url, until=time.time() + 30, log=lines.append)
        o3 = RP.run(d, now + MIN, mock=url, until=time.time() + 30, log=lines.append)
        o4 = RP.run(d, now + 2 * MIN, mock=url, until=time.time() + 30, log=lines.append)
        docs = docs_of(d)
        raw4 = raw_docs(d)
        n_calls = len(gt.calls)
        o5 = RP.run(d, now + 3 * MIN, mock=url, until=time.time() + 30, log=lines.append)
        raw5 = raw_docs(d)
        after = tree(d)
        new_files = sorted(os.path.relpath(f, d) for f in glob.glob(os.path.join(d, "**", "*"), recursive=True) if os.path.isfile(f))
    finally:
        srv.shutdown()
        srv.server_close()
    check(o0["buys"] == 11 and o0["items"] == 0 and o0["open"] == 11 and n_open == 11 and st0 == ["open"] and n0 == 0 and o0["why"] == "no window to price",
          "RA4 inside their 6 hours: one open doc per coin (11), no GeckoTerminal request (%s)" % json.dumps(o0))
    first4 = sorted(RP.all_buys(d)[0].values(), key=lambda x: (x["entryAt"], x["id"]))[:4]
    check(o1["items"] == 4 and sorted(set(asked1)) == sorted("RP" + x["addr"] for x in first4) and all(x["round"] == TA for x in first4)
          and sum(1 for v in d1.values() if v["state"] in ("closed", "void")) + sum(1 for v in d1.values() if v["state"] == "waiting" and v["tries"] == 1) >= 4,
          "RA4 at most MAX_ITEMS windows a run, the oldest first (with 4: four coins of round A, %s)" % sorted(set(asked1)))
    s = {v["addr"]: v for v in docs.values()}
    g = lambda a, k: s[a].get(k)
    check([g(a, "why") for a in ("a1", "a2", "a3", "a4", "b2", "b3", "b4", "b5")] == ["stop", "tp", "time", "rug", "time", "time", "time", "time"]
          and g("a1", "x") == 0.65 and g("a2", "x") == 15.0 and g("a4", "x") == 0.0 and all(g(a, "state") == "closed" and g(a, "src") == "m1" for a in ("a1", "a2", "a3", "a4", "b2"))
          and g("a5", "state") == "closed" and g("a5", "why") == "rug" and g("a5", "src") == "est" and g("a5", "tries") == 3
          and g("b6", "state") == "void" and g("b6", "why") == "nodata" and g("b6", "tries") == 3 and g("b1", "state") == "waiting" and g("b1", "tries") == 0
          and g("b2", "rawX") == 300.0 and g("b2", "best") == 1.1 and g("b2", "eurRaw") == RP.value(300.0) and g("a2", "eurBest") == RP.value(16.0),
          "RA4 after the runs: stop, take-profit at 15x, time, a collapse at 0, the one-candle and dust prints sold at 6 h; GONER (no candles, the "
          "radar found its pool gone) a total loss by estimate after 3 empty answers; NOCANDLE void (never priced); LATEGOOD's 5xx settles nothing "
          "under 48 h (waiting, no try counted)")
    check(raw5 == raw4 and o5["closed"] == 0 and o5["void"] == 0 and len(gt.calls) - n_calls == o5["items"] == 1 and o4["why"] == "all asked"
          and all(o["buys"] == 11 for o in (o1, o2, o3, o4, o5)),
          "RA4 a second run rewrites nothing: closed and void docs stay byte for byte, only the waiting window is asked again (%d request)" % (len(gt.calls) - n_calls))
    check(all(k.startswith(("db/memeradarpaper/", "candles/")) for k in set(new_files) - set(before)) and before == {k: v for k, v in after.items() if k in before}
          and all(re.search(r"_rp\d+\.txt$", k) for k in new_files if k.startswith("candles/")) and not any(k.startswith(".rptmp/") and k.endswith(".json") for k in new_files),
          "RA6 the radar account writes only db/memeradarpaper/<id>.json and candles/<pool>_rp<minute>.txt; the radar records, the paper "
          "positions and the trader's state are byte for byte the same")
    p = dict(RP.PAPER)
    hand = lambda x: round(max(0.0, (3.0 - 0.10) * x - max(0.01 * (3.0 - 0.10) * x, 0.10)), 2) if x > 0 else 0.0
    fees = [(a, g(a, "x"), g(a, "eur")) for a in ("a1", "a2", "a3", "a4", "b4")]
    check(all(eur == round(M.pos_value(p, 1.0, x), 2) == hand(x) and g(a, "pnl") == round(eur - 3.0, 2) for a, x, eur in fees) and g("a2", "eur") == 43.06
          and M.pos_fee(dict(p, ticket=3.0)) is M.paper_fee and g("a1", "ticket") == 3.0,
          "RA3 the paper fees on both sides (1%%, at least 0.10): 15x on 3 EUR brings back 43.06 EUR, every doc's eur is memebot.pos_value on a young "
          "paper position of 3 EUR (%s)" % ", ".join("%s %gx %.2f" % f for f in fees))
    return d, now


def _budget(check, tmp):
    d = os.path.join(tmp, "ra5")
    T = TA - 20 * H
    recs = [rec("c%02d" % i, "C%02d" % i, T + (i // 5) * H, [(T + (i // 5) * H, "trap", float(i % 5))]) for i in range(20)]
    write_records(d, recs)
    os.makedirs(os.path.join(d, "db", "memepos"), exist_ok=True)
    for i in range(6):
        json.dump({"grp": "young", "t": T + i * MIN, "entryAt": T + i * MIN, "px": 1e-5, "ticket": 3.0, "paper": M.PAPER_RULE, "pair": "PK%d" % i, "sym": "P%d" % i},
                  open(os.path.join(d, "db", "memepos", "y-p%d.json" % i), "w"))
    pools = {"PK%d" % i: series(T + i * MIN, [1.0] * 372) for i in range(6)}
    pools.update({"RPc%02d" % i: series(T + (i // 5) * H, [1.0] * 372) for i in range(20)})
    gt = GT(pools)
    srv, url = serve(gt)
    now = TA
    try:
        with quiet():
            o = P.run(d, now, deadline_s=60, mock=url)
        calls = [p for p, _ in gt.calls]
        d2 = os.path.join(tmp, "ra5b")
        shutil.copytree(d, d2, ignore=shutil.ignore_patterns("memepeak", "memeradarpaper", "candles", ".peaktmp", ".rptmp"))
        gt2 = GT(pools, delay=1.0)
        srv2, url2 = serve(gt2)
        try:
            with quiet():
                o2 = P.run(d2, now, deadline_s=4.5, mock=url2)
        finally:
            srv2.shutdown()
            srv2.server_close()
    finally:
        srv.shutdown()
        srv.server_close()
    pk = [c for c in calls if c.startswith("PK")]
    rp = [c for c in calls if c.startswith("RP")]
    oldest = sorted(RP.all_buys(d)[0].values(), key=lambda x: (x["entryAt"], x["id"]))[:RP.MAX_ITEMS]
    check(o["ok"] == 6 and o["why"] == "all asked" and len(pk) == 6 and calls[:6] == pk and len(set(rp)) == RP.MAX_ITEMS == 15
          and set(rp) == {"RP" + x["addr"] for x in oldest} and (o.get("radar") or {}).get("items") == 15 and (o["radar"]).get("closed") == 15
          and (o["radar"]).get("waiting") == 5 and len(M.load_docs(d, "memepeak")) == 6,
          "RA5 inside peak.py run: its own 6 windows first, then the radar account's, at most 15 of its 20 (the oldest), on the same client and "
          "deadline; the other 5 wait for the next run (%s)" % json.dumps(o.get("radar")))
    calls2 = [p for p, _ in gt2.calls]
    check(not any(c.startswith("RP") for c in calls2) and (o2.get("radar") or {}).get("why") == "deadline" and (o2.get("radar") or {}).get("closed") == 0
          and o2["why"] == "deadline" and 1 <= len(calls2) <= 4 and (o2.get("radar") or {}).get("waiting") == 20,
          "RA5 when peak.py's own windows use the whole deadline, the radar account asks GeckoTerminal nothing (its windows wait) and peak.py's "
          "budget is untouched (%d requests, all peak.py's; radar %s)" % (len(calls2), json.dumps(o2.get("radar"))))
    def boom(*a, **k):
        raise RuntimeError("radar broke")
    d3 = os.path.join(tmp, "ra5c")
    shutil.copytree(d, d3)
    srv3, url3 = serve(GT(pools))
    lines, orig_run = [], RP.run
    try:
        RP.run = boom
        o3 = P.run(d3, now + H, deadline_s=20, mock=url3, log=lines.append)
    finally:
        RP.run = orig_run
        srv3.shutdown()
        srv3.server_close()
    check(o3.get("radar") == {"err": "RuntimeError"} and any("radar account: not priced this run (RuntimeError" in l for l in lines) and "why" in o3,
          "RA5 a failure in the radar account never fails peak.py run: it is logged and its summary says so")


def _sync(check, tmp, d, now):
    import bot as B
    lines = B.SYNC_IGNORE.splitlines()
    before = raw_docs(d)
    with quiet():
        B.prune(d, now + 400 * 86_400_000)
    kept = raw_docs(d)
    bare = os.path.join(tmp, "ra7.git")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    sd = os.path.join(tmp, "ra7")
    shutil.copytree(d, sd)
    with quiet():
        B.sync(sd, remote=bare)
    ls = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", "results"], capture_output=True, text=True).stdout.split()
    check("!db/memeradarpaper/" in lines and "!db/memeradarpaper/**" in lines and kept == before and len(kept) == 11
          and sorted(x for x in ls if x.startswith("db/memeradarpaper/")) == sorted("db/memeradarpaper/" + k for k in kept)
          and not any(x.startswith(("candles/", ".rptmp/")) for x in ls),
          "RA7 the radar account's docs are never pruned (400 days on) and travel to the results branch with bot.py sync; its candle files do not")


def _accounts(check, d, now):
    A = RP.account(d, now)
    rows = A["rows"]
    sold = [r for r in rows if r["state"] == "closed"]
    gsold = [r for r in sold if r["green"]]
    al, gr = A["all"], A["green"]
    inv, back = 3.0 * len(sold), round(sum(r["eur"] for r in sold), 2)
    won = sum(1 for r in sold if r["eur"] > 3.0)
    best = max(sold, key=lambda r: r["eur"])
    worst = min(sold, key=lambda r: (r["eur"], r["entryAt"], r["id"]))
    check(len(rows) == 11 and al["n"] == len(sold) == 9 and al["invested"] == inv and al["back"] == back and al["pnl"] == round(back - inv, 2)
          and al["won"] == won and al["winRate"] == won / 9 and al["open"] == 0 and al["pricing"] == 1 and al["void"] == 1
          and al["best"]["addr"] == best["addr"] == "a2" and al["worst"]["eur"] == 0.0 and worst["eur"] == 0.0,
          "RA8 all 5: 9 sold of 11 (one waiting for its price, one void), invested %.2f, back %.2f, P/L %.2f, win rate %d of 9, best GOODTWO "
          "(take-profit), worst a total loss" % (inv, back, back - inv, won))
    check(gr["n"] == len(gsold) == 2 and gr["invested"] == 6.0 and gr["back"] == round(sum(r["eur"] for r in gsold), 2) and gr["pricing"] == 1
          and {r["addr"] for r in gsold} == {"a1", "a2"} and gr["best"]["addr"] == "a2" and gr["worst"]["addr"] == "a1",
          "RA8 green only: GOODONE (stop) and GOODTWO (take-profit) sold, LATEGOOD still to be priced")
    hind = round(sum(r["eurBest"] - 3.0 for r in sold if r["eurBest"] is not None), 2)
    raw = round(sum((r["eurRaw"] if r["eurRaw"] is not None and r["eurRaw"] >= r["eurBest"] else r["eurBest"]) - 3.0 for r in sold if r["eurBest"] is not None), 2)
    cut = [r["sym"] for r in sold if r["eurBest"] is not None and r["rawX"] > 1.05 * r["best"]]
    check(al["hind"] == hind and al["raw"] == raw and al["rawCut"] == len(cut) and {"SPIKE", "DUSTY"} <= set(cut) and al["raw"] > al["hind"] > al["pnl"]
          and al["hindN"] == 8,
          "RA8 hindsight on the same coins: sold at the best within 6 h %.2f, at the raw top %.2f (%d of them not sellable there: %s)" % (
              hind, raw, len(cut), ", ".join(cut)))
    e = RP.account(os.path.join(d, "nothing-here"), now)
    check(e["rows"] == [] and e["all"]["n"] == 0 and e["all"]["winRate"] is None and e["all"]["best"] is None and e["rounds"] == 0 and e["err"] is None,
          "RA8 no records and no docs: empty accounts, no error")


def _page(check, tmp, d, now):
    import page_radarpaper as RPP, page_account as PA, report as R
    text = lambda h: html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", h, flags=re.S)))
    A = RP.account(d, now)
    blk = RPP.section({"dir": d, "now": now})
    al, gr = A["all"], A["green"]
    tile = lambda k: (re.search(r'<div class="rp-tile %s" data-rp="%s">.*?</p></div>(?=<div class="rp-tile|</div>)' % (k, k), blk, re.S) or re.match("", "")).group(0)
    ta, tg = tile("all"), tile("green")
    check("Radar account" in blk and "bought within minutes" in blk and html.escape(PA.eur(al["pnl"], True)) in ta and html.escape(PA.eur(gr["pnl"], True)) in tg
          and "9 sold · 1 pricing" in ta and "2 sold · 1 pricing" in tg and ("%.0f%%" % (100 * al["winRate"])) in ta and html.escape(PA.eur(al["invested"])) in ta
          and "raw top" in ta and "(%d not sellable)" % al["rawCut"] in ta and "raw top" not in tg and "best in 6 h" in tg
          and "Last 11 bought" in blk and blk.count("<tr><td") == 11 and "+1,335%" in blk
          and "best <b>GOODTWO</b>" in blk and "take-profit +1,000%" in blk and "pool died" in blk and "6 h over · priced after the next scan" in blk
          and "not priced: no candles" in blk and blk.count('<span class="chip good">green</span>') == 3,
          "RA9 the block: two tiles (all 5, green only) with the P/L, invested, win rate and counts from the docs, the hindsight line with the raw "
          "top where it differs (green only: none), the best trade, the folded list of every coin (green marked, why it sold, still to be priced, "
          "never priced)")
    tx = text(blk)
    check("<img" not in blk and html.escape(XSS[:24]) in blk and tx.lower().count("fake money") == 1 and "\u2014" not in tx
          and not re.findall(r"(?i)\b(safe|safely|guaranteed?|buy|buys|buying)\b", tx),
          "RA9 names are escaped (cut at 24 characters), the fake-money note is there once, no em dash, no 'safe', 'guaranteed' or 'buy'")
    e0 = RPP.section({"dir": os.path.join(tmp, "none"), "now": now})
    d1 = os.path.join(tmp, "ra9-notop")
    write_records(d1, [rec("z1", "ZED", TA, [(TA, "trap", 9.0)], top=False)])
    e1 = RPP.section({"dir": d1, "now": TA + H})
    d2 = os.path.join(tmp, "ra9-open")
    write_records(d2, round_recs())
    e2 = RPP.section({"dir": d2, "now": TA + 2 * H})
    e3 = RPP.section({"dir": d2, "now": TC + 7 * H})
    saved = RP._account
    RP._account = lambda *a: 1 / 0
    try:
        e4 = RPP.section({"dir": d2, "now": TA})
    finally:
        RP._account = saved
    check("No radar round yet" in e0 and "<style>" in e0 and "The radar ran 1 round but listed no coin yet." in e1
          and "first result after" in e2 and "0 sold · 11 open" in e2 and 'data-rp-v="pnl">–<' in e2 and "6 h over: priced after the next scan" in e3
          and "11 pricing" in e3 and "could not be read this time (ZeroDivisionError" in e4,
          "RA9 the states: no radar round yet, rounds without a listed coin, all inside their 6 hours (first result after ...), 6 hours over and "
          "being priced, an unreadable account (a note, the page goes on)")
    # its place in the account block: right under "Without the stop-loss", before the activity feed
    import selftest_account as SA
    pd = os.path.join(tmp, "ra9-page")
    os.makedirs(pd)
    now_p, _ = SA.fixture(pd)
    for f in glob.glob(os.path.join(d, "db", "memeradar", "*.json")) + glob.glob(os.path.join(d, "db", RP.COLL, "*.json")):
        dst = os.path.join(pd, os.path.relpath(f, d))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(f, dst)
    out = R.build(pd, os.path.join(pd, "report.html"), now=now)
    page = open(out, encoding="utf-8").read()
    i_nl, i_rp, i_fd = page.find('data-pa="noloss"'), page.find('data-pa="radarpaper"'), page.find('data-pa="feed"')
    check(0 < i_nl < i_rp < i_fd and "could not be rendered" not in page and page.count('data-pa="radarpaper"') == 1,
          "RA9 page_account.section shows the block right under 'Without the stop-loss', before the activity feed, once")
    src = open(os.path.join(HERE, "page_account.py"), encoding="utf-8").read()
    check('R.safe("radar account", lambda: radar_account(D))' in src and "except ImportError:" in src,
          "RA9 the hook: one line in page_account.section; without page_radarpaper.py the account block renders as before")
    return page


PROBE = r"""
() => {
  const b = document.querySelector('[data-pa="radarpaper"]');
  const vis = (e) => e.checkVisibility ? e.checkVisibility({visibilityProperty: true}) : !!e.offsetParent;
  const r = b.getBoundingClientRect();
  const small = Array.from(b.querySelectorAll('details > summary')).filter(vis).map((e) => e.getBoundingClientRect().height).filter((h) => h < 43.5);
  const over = Array.from(b.querySelectorAll('*')).filter((e) => vis(e) && e.getBoundingClientRect().right > r.right + 1).map((e) => e.className || e.tagName);
  const tiles = Array.from(b.querySelectorAll('.rp-tile')).map((e) => [Math.round(e.getBoundingClientRect().top), Math.round(e.getBoundingClientRect().width)]);
  const pnl = getComputedStyle(b.querySelector('.rp-tile .rp-v')).color;
  return {sw: document.documentElement.scrollWidth, iw: innerWidth, small: small, over: over.slice(0, 5), tiles: tiles, h: Math.round(r.height), pnl: pnl};
}
"""


def _browser(check, page):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  SKIP the browser checks of the radar account: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    url = "https://some-owner.github.io/Meme-Bot/"
    os.makedirs(SHOTS, exist_ok=True)
    views, errs, shots = {}, [], []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            for w, h in ((390, 844), (1280, 900)):
                for scheme in ("light", "dark"):
                    phone = {"is_mobile": True, "has_touch": True, "device_scale_factor": 2} if w == 390 else {}
                    ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, **phone)
                    pg = ctx.new_page()
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.route("**/*", lambda r: r.fulfill(status=200, body=page, headers={"Content-Type": "text/html; charset=utf-8"})
                             if r.request.url.startswith(url) else r.abort())
                    pg.goto(url)
                    closed = pg.evaluate(PROBE)
                    blk = pg.locator('[data-pa="radarpaper"]')
                    f = os.path.join(SHOTS, "radar-account-%d-%s-folded.png" % (w, scheme))
                    blk.screenshot(path=f)
                    shots.append(f)
                    pg.evaluate("document.querySelectorAll('[data-pa=\"radarpaper\"] details').forEach(function(x){x.open=true;})")
                    opened = pg.evaluate(PROBE)
                    f = os.path.join(SHOTS, "radar-account-%d-%s-open.png" % (w, scheme))
                    blk.screenshot(path=f)
                    shots.append(f)
                    nl = pg.locator('[data-pa="noloss"]')
                    pg.evaluate("document.querySelectorAll('[data-pa=\"noloss\"] details').forEach(function(x){x.open=true;})")
                    f = os.path.join(SHOTS, "without-stop-loss-raw-%d-%s.png" % (w, scheme))
                    nl.screenshot(path=f)
                    shots.append(f)
                    views[(w, scheme)] = (closed, opened)
                    ctx.close()
            br.close()
    except Exception as e:
        check(False, "RA10 the browser checks of the radar account ran (%s)" % str(e)[:160])
        return
    ok_sw = all(v["sw"] <= v["iw"] for vv in views.values() for v in vv)
    ph = [views[(390, s)] for s in ("light", "dark")]
    dt = [views[(1280, s)] for s in ("light", "dark")]
    check(ok_sw and all(len(c["tiles"]) == 2 and c["tiles"][1][0] > c["tiles"][0][0] + 60 for c, _ in ph)
          and all(len(c["tiles"]) == 2 and c["tiles"][0][0] == c["tiles"][1][0] and min(w for _, w in c["tiles"]) >= 400 for c, _ in dt)
          and not any(v["small"] or v["over"] for vv in views.values() for v in vv) and not errs and views[(390, "light")][0]["pnl"] != views[(390, "dark")][0]["pnl"],
          "RA10 in Chromium at 390 (phone) and 1280 px, light and dark, folds closed and open: no sideways scroll, the two tiles stacked on the "
          "phone and side by side wide, every fold at least 44 px high, nothing past the block's edge, the P/L colour follows the theme "
          "(folded block %d px on the phone; %d screenshots in %s)" % (ph[0][0]["h"], len(shots), SHOTS))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
