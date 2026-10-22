#!/usr/bin/env python3
"""selftest_shadow.py: the Pick's shadow rules (shadow.py, page_shadow.py) and the evening report (daily.py, daily.yml, the app's
"Tagesbericht" switch) on made-up data. Fake money only: nothing is bought, nothing is sent (a local mock stands in for GeckoTerminal,
stand-ins for the live store and the push).

  python3 selftest_shadow.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                import selftest_shadow; selftest_shadow.checks(check)

SH1 the replay of every rule on hand-made paths: a stop (booked at min(close, level)), a target, the half sale, the trailing stop,
    the time limits (6 h and 12 h), dust and glitch closes that sell nothing, a pool that died (with and without a stop, a rug exit),
    a path without a close on real volume (not replayable); the euros after the paper fees (memebot.pos_value per sale)
SH2 the plain stop/target rules give exit_grid.replay's sale (with its default fill) on traders.path_ev's evidence of the same path,
    on 400 random paths (dust, glitches, dead pools)
SH3 shadow.py run against a mock GeckoTerminal: only the Pick buys from SINCE whose 12 hours have passed are asked, one request
    each (limit 1000, before the end + 2 min); a path is written once with peak.py's filter (a collapse ends it) and never asked again;
    an empty answer waits and is left out after MAX_TRIES runs; a pool the mock does not know is left out the same way; the deadline
    holds; the paper account's own docs are byte for byte the same; nothing is written outside db/memeshadow
SH4 the Pick's own rule is untouched: memebot's paper rule and its constants are what they were, K is that rule, the summary counts
    every rule on the same buys, open and left-out buys apart, the real account's results from its own exits
SH5 the fold on the Pick tab: before the first buy, with buys (escaped symbols, the leader marked, every rule), its place under the
    hour grid, German words; memeshadow travels to the results branch (bot.SYNC_IGNORE)
SH6 the evening report's words: both accounts today (buys, sales, open, balance), the shadow line, the filter search line, within
    the notification's limits, German, never buy, safe or clean, a missing doc says "–"
SH7 when it goes out: from 21:00 Berlin (summer and winter), once a Berlin day (the live store's row "daily"), never when the store
    does not answer, dry sends nothing
SH8 the app: kind "daily" (its own Topic Apple accepts), the phone's switch (prefs, else the subscription's memebot.daily; none = on),
    the page's third switch and where it saves it, setup.sql unchanged in what it keeps
SH9 the workflows: daily.yml (19 and 20 UTC, read only, no push to any branch, the secrets only where needed) and the peaks job's
    shadow step (after the exit replay, before the push, soft, without the token)
"""
import glob, json, os, random, re, shutil, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("MEMEBOT_PAUSE", "0")
MIN, HOUR = 60_000, 3_600_000


def _pos(d, pid, t, pool, px=1e-5, grp="hold", sym="AAA", exits=(), paper=True):
    import memebot as M
    doc = {"grp": grp, "ticket": 50.0 if grp == "hold" else 3.0, "t": t, "entryAt": t, "px": px, "pair": pool, "addr": "ADDR" + pool, "sym": sym,
           "liq": 50_000.0, "mc": 500_000.0}
    if paper:
        doc["paper"] = M.PAPER_RULE
    os.makedirs(os.path.join(d, "db", "memepos"), exist_ok=True)
    json.dump(doc, open(os.path.join(d, "db", "memepos", pid + ".json"), "w"))
    for k, (et, frac, eur, why) in enumerate(exits, 1):
        os.makedirs(os.path.join(d, "db", "memeexit"), exist_ok=True)
        json.dump({"pos": pid, "t": et, "px": px, "frac": frac, "why": why, "eur": eur, "grp": grp}, open(os.path.join(d, "db", "memeexit", "%s-%d.json" % (pid, k)), "w"))


def _db(d, since):
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    import memebot as M
    json.dump({"paperSince": since, "paperRule": M.PAPER_RULE}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    json.dump({"t": since, "px": {}, "liq": {}}, open(os.path.join(d, "db", "memebot", "marks.json"), "w"))


def path(entry, rows, dead=None):
    """A shadow doc from [(minute, close over cpx, volume), ...]."""
    return {"v": 1, "state": "ok", "entryAt": entry, "cpx": 1.0, "dead": dead, "c": [[int(m * 60 - 19), x, v] for m, x, v in rows]}


def flat(n, x=1.0, v=500):
    return [(m, x, v) for m in range(n)]


def checks(check):
    tmp = tempfile.mkdtemp(prefix="memebot-shadow-")
    try:
        _sh1(check)
        _sh2(check)
        _sh3_sh4(check, tmp)
        _sh5(check, tmp)
        _sh6_sh7(check, tmp)
        _sh8(check)
        _sh9(check)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- SH1
def _sh1(check):
    import shadow as S, memebot as M
    print("== shadow SH1: the replay of every rule")
    R = {r["id"]: r for r in S.RULES}
    T = 1_800_000_000_000
    sale = lambda doc, k: (S.replay(doc, R[k]) or {}).get("sales")
    # a slide: 0.85 at minute 10, 0.75 at 20, 0.65 at 30, then flat at 0.65 to 12 h
    slide = path(T, [(0, 1.0, 900), (10, 0.85, 900), (20, 0.75, 900), (30, 0.65, 900)] + [(m, 0.65, 900) for m in range(31, 721)])
    k, a, b, c, dd = (sale(slide, x) for x in "KABCD")
    check(k == [[T + 30 * MIN - 19000, 1.0, 0.65, "stop"]] and a == [[T + 20 * MIN - 19000, 1.0, 0.75, "stop"]]
          and b == [[T + 12 * HOUR, 1.0, 0.65, "time"]] and c == k and dd[0][2] == 0.65 and dd[0][3] == "trail",
          "SH1 a slide: K stops at the 0.65 close (min(close, 0.70)), A at the first close under 0.80 (0.75), B (no stop) sells at 12 h, "
          "C as K, D's trailing stop starts at 0.70")
    # a run to 2.5x at minute 60, back to 1.2 by minute 120 and flat to 12 h
    up = [(0, 1.0, 900)] + [(m, 1.0 + 1.5 * (m / 60.0), 900) for m in range(1, 61)] + [(m, 2.5 - 1.3 * ((m - 60) / 60.0), 900) for m in range(61, 121)] \
        + [(m, 1.2, 900) for m in range(121, 721)]
    upd = path(T, up)
    k, a, b, c, dd = (sale(upd, x) for x in "KABCD")
    t2 = next(T + m * MIN - 19000 for m, x, _ in up if x >= 2.0)
    t_d = next(T + m * MIN - 19000 for m, x, _ in up if m > 60 and x <= 2.5 * 0.7)
    x_d = next(x for m, x, _ in up if m > 60 and x <= 2.5 * 0.7)
    check(k == [[T + 6 * HOUR, 1.0, 1.2, "time"]] and a == k and b == [[t2, 1.0, 2.0, "tp"]]
          and c == [[t2, 0.5, 2.0, "half"], [T + 6 * HOUR, 0.5, 1.2, "time"]] and dd == [[t_d, 1.0, min(x_d, 2.5 * 0.7), "trail"]],
          "SH1 a run to 2.5x and back to 1.2: K and A sell at 6 h, B at its 2x target, C half at 2x and the rest at 6 h, D when a close "
          "falls 30%% under the best (2.5x: at %.3f)" % x_d)
    p = {"grp": "hold", "paper": M.PAPER_RULE, "ticket": 50.0}
    want = round(M.pos_value(p, 0.5, 2.0) + M.pos_value(p, 0.5, 1.2) - 50.0, 2)
    check(S.money(p, c) == want and S.money(p, k) == round(M.pos_value(p, 1.0, 1.2) - 50.0, 2),
          "SH1 the euros: each sale after the paper fees on the position (two fees for the half sale), minus the ticket: C %.2f, K %.2f" % (S.money(p, c), S.money(p, k)))
    # dust and glitch closes sell nothing
    noise = path(T, [(0, 1.0, 900), (5, 5.0, 10), (6, 1.0, 900), (7, 40.0, 900), (8, 1.0, 900), (9, 0.5, 5)] + [(m, 1.05, 900) for m in range(10, 721)])
    k, a, b, dd = (sale(noise, x) for x in "KABD")
    check(k == [[T + 6 * HOUR, 1.0, 1.05, "time"]] and a == k and b == [[T + 12 * HOUR, 1.0, 1.05, "time"]] and dd == k,
          "SH1 a 5x close on $10 of volume, a 40x glitch close (over CANDLE_MAX_X) and a 0.5 close on dust sell nothing and move no trailing stop")
    # a pool that died at minute 30 (collapse) and one with a rug exit
    dead = path(T, flat(30, 1.0), dead={"at": T + 30 * MIN, "why": "collapse"})
    rug = path(T, flat(30, 1.0), dead={"at": T + 30 * MIN, "why": "rug exit"})
    check(sale(dead, "K") == [[T + 30 * MIN, 1.0, 0.35, "dead"]] and sale(dead, "B") == [[T + 30 * MIN, 1.0, 0.0, "rug"]]
          and sale(dead, "D")[0][2] == 0.35 and sale(rug, "K") == [[T + 30 * MIN, 1.0, 0.0, "rug"]],
          "SH1 a pool that died: a stop rule gets half its level (exit_grid's default fill), no stop and a rug exit get 0")
    # 12 hours: a 2x at hour 8 is B's target, the 6-hour rules sell at 6 h
    late = path(T, flat(480, 1.1) + [(480, 2.1, 900)] + [(m, 1.5, 900) for m in range(481, 721)])
    check(sale(late, "B") == [[T + 480 * MIN - 19000, 1.0, 2.0, "tp"]] and sale(late, "K") == [[T + 6 * HOUR, 1.0, 1.1, "time"]],
          "SH1 B holds 12 h (its 2x at hour 8), the 6-hour rules sell at 6 h")
    only_dust = path(T, [(m, 1.0, 5) for m in range(0, 721)])
    check(all(S.replay(only_dust, r) is None for r in S.RULES) and S.replay({"entryAt": T, "cpx": None, "c": []}, R["K"]) is None,
          "SH1 a path without one close on real volume (or without cpx) is not replayable")


# ---------------------------------------------------------------- SH2
def _sh2(check):
    import shadow as S, exit_grid as EG, traders as TR, types
    print("== shadow SH2: the plain rules against exit_grid.replay")
    rnd, T, bad, n = random.Random(11), 1_800_000_000_000, [], 0
    for i in range(400):
        x, rows = 1.0, []
        for m in range(0, 721):
            if rnd.random() < 0.15:
                continue                               # a minute without trades
            x *= math_exp(rnd.gauss(0, 0.035))
            v = 5 if rnd.random() < 0.05 else 900
            rows.append((m, round(40.0 if rnd.random() < 0.003 else x, 6), v))
        dead = {"at": T + rnd.randint(10, 700) * MIN, "why": rnd.choice(("collapse", "rug exit", "liquidity"))} if rnd.random() < 0.2 else None
        doc = path(T, rows, dead)
        doc["id"] = "r%d" % i
        p = {"grp": "hold", "ticket": 50.0}
        t = types.SimpleNamespace(entryAt=T, group="pick", id=doc["id"], p=p, t1=0.0, t1why="")
        for r in S.RULES:
            if r.get("half") or r.get("trail"):
                continue
            ev = TR.path_ev(doc, t, r["hours"])
            mine = S.replay(doc, r)
            if ev is None or mine is None:
                if (ev is None) != (mine is None):
                    bad.append((i, r["id"], "none"))
                continue
            pt, _, _, why = EG.replay(ev, r["stop"], r["target"])
            m = EG.fill_at(pt, EG.FILL_DEFAULT) if isinstance(pt, tuple) else pt
            n += 1
            if abs(m - mine["sales"][-1][2]) > 1e-9 or why != {"dead": "stop"}.get(mine["why"], mine["why"]):
                bad.append((i, r["id"], m, why, mine["sales"][-1]))
    check(n > 800 and not bad, "SH2 K, A and B give exit_grid.replay's sale (default fill) on traders.path_ev's evidence of the same path: %d of %d agree%s"
          % (n - len(bad), n, (" (first: %s)" % (bad[0],)) if bad else ""))


def math_exp(v):
    import math
    return math.exp(v)


# ---------------------------------------------------------------- SH3 and SH4
class _GT:
    """A mock GeckoTerminal OHLCV endpoint: pools[pool] = fn(ms) -> close over 1e-5 (or None: no trade); "EMPTY" answers an empty list,
    an unknown pool 404. Every request is noted (pool, limit, before_timestamp)."""

    def __init__(self, pools):
        self.pools, self.asked = pools, []
        me = self

        class Hd(BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                m = re.match(r"^/api\.geckoterminal\.com/api/v2/networks/solana/pools/([^/]+)/ohlcv/minute$", u.path)
                q = urllib.parse.parse_qs(u.query)
                if not m:
                    return self._send(404, b"{}")
                pool = m.group(1)
                lim, before = int(q["limit"][0]), int(q["before_timestamp"][0])
                me.asked.append((pool, lim, before, int(q["aggregate"][0])))
                if pool == "EMPTY":
                    return self._send(200, json.dumps({"data": {"attributes": {"ohlcv_list": []}}}).encode())
                if pool not in me.pools:
                    return self._send(404, b'{"errors":[{"status":"404"}]}')
                lst, top = [], before // 60 * 60
                for i in range(lim):
                    ts = top - (i + 1) * 60
                    x = me.pools[pool](ts * 1000)
                    if x is not None:
                        lst.append([ts, 1e-5 * x, 1e-5 * x, 1e-5 * x, 1e-5 * x, 900.0])
                self._send(200, json.dumps({"data": {"attributes": {"ohlcv_list": lst}}}).encode())

            def _send(self, code, raw):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()


def _tree(d, sub):
    return {os.path.relpath(f, d): open(f, "rb").read() for f in glob.glob(os.path.join(d, sub, "**", "*"), recursive=True) if os.path.isfile(f)}


def _sh3_sh4(check, tmp):
    import shadow as S, memebot as M
    print("== shadow SH3: shadow.py run against a mock GeckoTerminal")
    d = os.path.join(tmp, "db3")
    T = S.SINCE + 2 * HOUR
    now = T + 13 * HOUR
    _db(d, S.SINCE - 24 * HOUR)
    e1 = (T + 30 * MIN, 1.0, 34.3, "stop")
    _pos(d, "p1", T, "POOLA", sym="AAA", exits=[e1])                          # due: its 12 hours passed
    _pos(d, "p2", now - 2 * HOUR, "POOLB", sym="BBB")                          # bought 2 hours ago: open
    _pos(d, "p3", S.SINCE - HOUR, "POOLA", sym="OLD", exits=[(S.SINCE, 1.0, 40.0, "stop")])   # before SINCE: not mirrored
    _pos(d, "p4", T, "POOLA", grp="young", sym="YNG", exits=[(T + HOUR, 1.0, 2.0, "stop")])  # a new launch: not a Pick buy
    _pos(d, "p5", T + 10 * MIN, "EMPTY", sym="EEE", exits=[(T + 6 * HOUR, 1.0, 45.0, "time")])   # GeckoTerminal has no candles
    _pos(d, "p6", T + 20 * MIN, "GONE", sym="<b>x</b>", exits=[(T + 6 * HOUR, 1.0, 45.0, "time")])  # a pool GeckoTerminal does not know
    _pos(d, "p7", T + 40 * MIN, "POOLC", sym="DIE", exits=[(T + 2 * HOUR, 1.0, 15.0, "stop")])  # collapses at hour 2
    curve = lambda ms: 1.0 if ms < T + 20 * MIN else (0.75 if ms < T + 40 * MIN else 0.9)
    die = lambda ms: 1.0 if ms < T + 40 * MIN + 2 * HOUR else 0.001
    gt = _GT({"POOLA": curve, "POOLB": curve, "POOLC": die})
    keep = {k: v for k, v in _tree(d, "db").items() if not k.startswith("db/memeshadow")}
    try:
        out1 = S.run(d, now, 30, gt.url)
        asked1 = list(gt.asked)
        doc1 = S.load_doc(d, "p1")
        out2 = S.run(d, now + HOUR, 30, gt.url)
        asked2 = gt.asked[len(asked1):]
        out3 = S.run(d, now + 2 * HOUR, 30, gt.url)
        n_before = len(gt.asked)
        out4 = S.run(d, now + 3 * HOUR, 0.5, gt.url)
        _pos(d, "p8", T + 50 * MIN, "POOLA", sym="LATE")
        out5 = S.run(d, now + 3 * HOUR, 0.5, gt.url)                           # a deadline too short for a request
    finally:
        gt.close()
    pools1 = sorted(a[0] for a in asked1)
    end1 = T + 12 * HOUR
    check(pools1 == ["EMPTY", "GONE", "POOLA", "POOLC"] and all(a[1] == 1000 and a[3] == 1 for a in asked1)
          and any(a[0] == "POOLA" and a[2] == end1 // 1000 + 120 for a in asked1) and out1["due"] == 4,
          "SH3 only the Pick buys from SINCE whose 12 hours passed are asked (not the open one, not the one before SINCE, not a new launch), "
          "one request each: one-minute candles, limit 1000, up to 2 minutes past the end (%s)" % pools1)
    c = (doc1 or {}).get("c") or []
    check(doc1 and doc1["state"] == "ok" and doc1["cpx"] == 1e-5 and len(c) >= 715 and c[0][0] <= 0 and c[-1][0] <= 12 * 3600
          and abs(c[25][1] - 0.75) < 1e-9 and doc1["dead"] is None,
          "SH3 the path is written whole: 12 hours of minute closes over cpx with their volume (%d rows)" % len(c))
    d7 = S.load_doc(d, "p7") or {}
    check(d7.get("state") == "ok" and (d7.get("dead") or {}).get("why") == "collapse" and S.replay(d7, S.RULES[0])["sales"][-1][3] == "dead",
          "SH3 peak.py's filter ends a pool that collapsed (dead at its collapse; K gets half its stop level)")
    d5, d6 = S.load_doc(d, "p5") or {}, S.load_doc(d, "p6") or {}
    check(sorted(a[0] for a in asked2) == ["EMPTY", "GONE"] and (S.load_doc(d, "p5") or {}).get("state") == "none" and d6.get("state") == "none"
          and d5.get("tries") == 3 and out3["none"] == 2 and len(gt.asked) == n_before,
          "SH3 a settled path is never asked again; an empty answer and an unknown pool wait and are left out after %d runs" % S.MAX_TRIES)
    check(out4["due"] == 0 and out5["due"] == 1 and out5["why"] == "deadline" and S.load_doc(d, "p8") is None,
          "SH3 nothing due asks nothing; a deadline too short for a request writes nothing (%s)" % out5.get("why"))
    after = {k: v for k, v in _tree(d, "db").items() if not k.startswith("db/memeshadow")}
    extra = [f for f in glob.glob(os.path.join(d, "**", "*"), recursive=True) if os.path.isfile(f) and not re.search(r"/db/(memeshadow|memepos|memeexit|memebot)/|/\.shadowtmp/", f)]
    after.pop(os.path.join("db", "memepos", "p8.json"), None)              # the test's own late buy
    check(after == keep and not extra, "SH3 the paper account's own docs are byte for byte the same; nothing is written outside db/memeshadow (%s)" % extra[:3])

    print("== shadow SH4: the Pick's own rule is untouched")
    check(M.PAPER_RULE == "v2: top 50 / young 3 / +1000% / -30% / 6h" and (M.HOLD_STOP, M.HOLD_TP, M.HOLD_MAX_H, M.TOP_TICKET) == (0.30, 10.0, 6.0, 50.0)
          and (S.RULES[0]["id"], S.RULES[0]["stop"], S.RULES[0]["target"], S.RULES[0]["hours"]) == ("K", 0.30, 11.0, 6.0) and not S.RULES[0].get("half")
          and not S.RULES[0].get("trail") and [r["id"] for r in S.RULES] == ["K", "A", "B", "C", "D"],
          "SH4 memebot's paper rule (-30 %, 11x, 6 h, 50 a pick) is what it was; K is that rule; A to D are the four shadow rules")
    src = open(os.path.join(HERE, "shadow.py"), encoding="utf-8").read()
    check("memepos" not in src and "memeexit" not in src and "state.json\"), {}" in src and src.count("open(") == 1 and "json.dump(" in src
          and src.count("os.replace(") == 1,
          "SH4 shadow.py opens one file for writing (its own doc, through a temp file) and names no position or exit folder")
    sm = S.summary(d, now + 3 * HOUR)
    by = {r["pid"]: r for r in sm["trades"]}
    k = next(a for a in sm["accts"] if a["id"] == "K")
    check(sm["n"] == 2 and sm["open"] == 2 and sm["out"] == 2 and set(by) == {"p1", "p2", "p5", "p6", "p7", "p8"}
          and by["p1"]["real"] == round(34.3 - 50.0, 2) and by["p2"]["state"] == "open" and by["p5"]["state"] == "none"
          and all(a["n"] == 2 for a in sm["accts"]) and sm["real"]["n"] == 2 and k["vsK"] is None
          and all(a["vsK"] == round(a["eur"] - k["eur"], 2) for a in sm["accts"] if a["id"] != "K")
          and sm["leader"] == "C" and sm["ahead"] is False and [r["pid"] for r in sm["trades"]][0] == "p2",
          "SH4 the summary: every rule on the same 2 buys, 2 open, 2 left out, the real result from the account's own exits, each shadow "
          "against K, the best shadow (the first of equals; none ahead of K here), newest first")
    _sh3_state[0] = d


_sh3_state = [None]


# ---------------------------------------------------------------- SH5
def _sh5(check, tmp):
    import page_shadow as PS, report as R, shadow as S, bot as B
    print("== shadow SH5: the fold on the Pick tab")
    empty = os.path.join(tmp, "empty")
    _db(empty, S.SINCE - HOUR)
    h0 = PS.section({"dir": empty, "now": S.SINCE + HOUR}, R)
    d = _sh3_state[0]
    h1 = PS.section({"dir": d, "now": S.SINCE + 20 * HOUR}, R)
    check("Schatten-Regeln" in h0 and "startet mit dem nächsten Pick-Kauf" in h0 and "<script" not in h0,
          "SH5 before the first mirrored buy the fold says it starts with the next pick buy")
    check(all(x in h1 for x in ("Echtes Pick-Konto", "K · Echte Regel, nachgerechnet", "A · Enger Stop", "B · Länger, ohne Stop", "C · Hälfte bei 2x",
                                "D · Mitlaufender Stop", "gegen K", "Die Käufe einzeln", "ohne Minutenkerzen", "gleiche 50 €",
                                "keine besser als die echte Regel"))
          and 'class="sh-chip"' not in h1 and "&lt;b&gt;x&lt;/b&gt;" in h1 and "<b>x</b>" not in h1 and "<script" not in h1 and 'id="schatten"' in h1,
          "SH5 with buys: the real account, K and A to D on the same buys, each buy, symbols escaped, no script; no rule ahead of K, none marked")
    # the same buys, but p1 falls on to 0.6 after its dip: A's tight stop (sold at 0.75) is now ahead of K (stopped at 0.6)
    d2 = os.path.join(tmp, "db5b")
    shutil.copytree(d, d2)
    f = os.path.join(d2, "db", "memeshadow", "p1.json")
    doc = json.load(open(f, encoding="utf-8"))
    doc["c"] = [[r[0], 0.6 if abs(r[1] - 0.9) < 1e-9 else r[1]] + list(r[2:]) for r in doc["c"]]
    json.dump(doc, open(f, "w", encoding="utf-8"))
    s2 = S.summary(d2, S.SINCE + 20 * HOUR)
    h2 = PS.section({"dir": d2, "now": S.SINCE + 20 * HOUR}, R)
    check(s2["leader"] == "A" and s2["ahead"] is True and h2.count('class="sh-chip"') == 1 and "vorn: A Enger Stop" in h2
          and re.search(r'<tr class="lead"><td><b>A · Enger Stop</b><i class="sh-chip">vorn</i>', h2),
          "SH5 a rule ahead of K is marked \"vorn\" in the summary line and in its row")
    src = open(os.path.join(HERE, "report.py"), encoding="utf-8").read()
    i_pick = src.find("pane_pick = (")
    check(i_pick > 0 and 'safe("shadow rules", lambda: shadow_block(D))' in src[i_pick:i_pick + 400] and "Schatten-Regeln" in R.shadow_block({"dir": d, "now": S.SINCE + 20 * HOUR}),
          "SH5 the fold sits on the Pick tab under the hour grid (report.shadow_block)")
    check({"!db/memeshadow/", "!db/memeshadow/**"} <= set(B.SYNC_IGNORE.splitlines()), "SH5 db/memeshadow travels to the results branch (bot.SYNC_IGNORE)")


# ---------------------------------------------------------------- SH6 and SH7
def _sh6_sh7(check, tmp):
    import daily as DY, app as A, shadow as S, memebot as M
    print("== shadow SH6: the evening report's words")
    d = os.path.join(tmp, "db6")
    now = 1_792_696_800_000                                       # Thu 22 Oct 2026 19:20 UTC = 21:20 Berlin (summer time)
    start = DY.day_start(now)
    _db(d, start - 5 * 24 * HOUR)
    _pos(d, "y1", start - 3 * HOUR, "P1", sym="OLD", exits=[(start + HOUR, 1.0, 40.0, "stop")])    # bought yesterday, sold today: -10
    _pos(d, "t1", start + 2 * HOUR, "P2", sym="NEW", exits=[(start + 3 * HOUR, 1.0, 60.0, "time")])   # bought and sold today: +10
    _pos(d, "t2", start + 4 * HOUR, "P3", sym="OPN")                                                 # bought today, open
    _pos(d, "y2", start - 30 * HOUR, "P4", sym="OLD2", exits=[(start - 25 * HOUR, 1.0, 20.0, "stop")])  # yesterday's: only the balance
    marks = {"t": now, "px": {"t2": 2e-5}, "liq": {}}
    json.dump(marks, open(os.path.join(d, "db", "memebot", "marks.json"), "w"))
    rk = {"book": {"open": {"a": {"t": start + HOUR, "sym": "R1"}}, "closed": [{"t": start - HOUR, "out": start + 30 * MIN, "eur": 5.5},
                                                                             {"t": start - 9 * HOUR, "out": start - 8 * HOUR, "eur": -3.0}],
                   "summary": {"eur": 2.5, "openEur": -1.0}}}
    fs = {"data": {"rows": 1}, "t": now - HOUR, "leader": None}
    pk = DY.pick_day(d, now)
    open_val = M.pos_value({"grp": "hold", "paper": M.PAPER_RULE, "ticket": 50.0}, 1.0, 2.0)
    check(pk == {"buys": 2, "sold": 2, "soldEur": 0.0, "open": 1, "bal": round(-10 + 10 - 30 + open_val - 50, 2)},
          "SH6 Pick today: 2 bought, 2 sold (one bought yesterday), 1 open, the balance with the open one at its last price (%s)" % pk)
    check(DY.rocket_day(rk, now) == {"buys": 1, "sold": 1, "soldEur": 5.5, "open": 1, "bal": 1.5} and DY.rocket_day(None, now) is None,
          "SH6 Radar today from rocket.json's book (open is a dict, closed a list), None without the doc")
    title, body = DY.words(d, now, rk, fs)
    t2, b2 = DY.words(d, now, None, None)
    check(title.startswith("Tagesbericht 22.10.: Pick 0,00 €, Radar +5,50 €") and "Pick: 2 Käufe, 2 verkauft (0,00 €), 1 offen, Konto" in body
          and "Radar: 1 Kauf, 1 verkauft (+5,50 €), 1 offen, Konto +1,50 €" in body and "Filtersuche: noch keine Regel besser als die Gates" in body
          and "Schatten-Regeln: noch kein Kauf" in body and body.endswith("Nur Papiergeld.") and len(title) <= A.TITLE_MAX and len(body) <= A.BODY_MAX
          and not A.NO_ADVICE.search(title + " " + body) and "Radar: –" in b2 and "Filtersuche: kein Ergebnis" in b2 and "Radar –" in t2,
          "SH6 the words: both accounts, the shadow and the filter lines, within the limits, German, no advice words; a missing doc says –")
    long_d = os.path.join(tmp, "db6b")
    shutil.copytree(d, long_d)
    for i in range(40):
        _pos(long_d, "z%02d" % i, start + HOUR + i * MIN, "Q%d" % i, sym="Z", exits=[(start + 2 * HOUR, 1.0, 12345.678, "tp")])
    tl, bl = DY.words(long_d, now, {"book": {"open": {}, "closed": [], "summary": {"eur": -12345678.9, "openEur": 0}}}, {"data": {}, "t": 0, "leader": {"x": 1}})
    check(len(bl) <= A.BODY_MAX and bl.startswith("Pick: 42 Käufe") and bl.endswith("Nur Papiergeld."),
          "SH6 a body that would run over the limit drops its last parts first; the accounts stay (%d chars)" % len(bl))

    print("== shadow SH7: when it goes out")
    from zoneinfo import ZoneInfo
    import datetime as dt
    ms = lambda y, mo, da, h, mi: int(dt.datetime(y, mo, da, h, mi, tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)
    check(not DY.time_to_send(ms(2026, 10, 22, 20, 59)) and DY.time_to_send(ms(2026, 10, 22, 21, 0)) and DY.time_to_send(ms(2026, 10, 27, 21, 5))
          and not DY.time_to_send(ms(2026, 10, 27, 20, 55)) and DY.berlin(ms(2026, 10, 27, 21, 5)).hour == 21,
          "SH7 from 21:00 Berlin, in summer time and after the clocks go back (27 Oct)")
    sent, rows, put = [], [{"doc": {"day": "2026-10-21"}}], []
    saved = (A.enabled, A.call, A.notify_daily, A.put_row)
    try:
        A.enabled = lambda: True
        A.call = lambda method, p, body=None, **k: list(rows) if method == "GET" and "id=eq.daily" in p else None
        A.notify_daily = lambda t, b: (sent.append((t, b)) or {"kind": "daily", "sent": 1})
        A.put_row = lambda rid, doc, track=None: (put.append((rid, doc)), rows.__setitem__(0, {"doc": doc}))
        early = DY.run(d, ms(2026, 10, 22, 20, 10), None, None, "auto")
        dry = DY.run(d, now, None, None, "dry")
        first = DY.run(d, now, None, None, "auto")
        second = DY.run(d, now + 30 * MIN, None, None, "auto")
        by_hand = DY.run(d, now + 40 * MIN, None, None, "send")
        rows[0] = {"doc": {"day": "2026-10-22"}}
        A.call = lambda *a, **k: (_ for _ in ()).throw(A.StoreError("HTTP 500"))
        down = DY.run(d, ms(2026, 10, 23, 21, 10), None, None, "auto")
    finally:
        A.enabled, A.call, A.notify_daily, A.put_row = saved
    check(not early["sent"] and not dry["sent"] and first["sent"] and not second["sent"] and second["why"] == "already sent today"
          and not by_hand["sent"] and not down["sent"] and len(sent) == 1 and put and put[0][0] == "daily" and put[0][1]["day"] == "2026-10-22"
          and "never twice" in down["why"],
          "SH7 before 21:00 nothing, dry nothing, then once: the row \"daily\" keeps the day (a second run and a run by hand that evening send "
          "nothing), and a store that does not answer sends nothing")
    check(DY.run(d, now, None, None, "auto").get("why", "").startswith("no live store") or not A.enabled(),
          "SH7 without the Supabase secrets nothing is sent")


# ---------------------------------------------------------------- SH8
def _sh8(check):
    import app as A
    print("== shadow SH8: the app's switch")
    check(A.KINDS.get("daily") == (21600, "normal", 60) and re.fullmatch(r"[A-Za-z0-9_-]{8}", A.TOPIC.get("daily") or "")
          and len(set(A.TOPIC.values())) == len(A.TOPIC) and "daily" not in A.PREF_OF,
          "SH8 kind daily: 6 h to live, normal urgency, its own 8-letter Topic, its own switch")
    sub = lambda extra=None: dict({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "B", "auth": "a"}}, **({"memebot": extra} if extra is not None else {}))
    rows = [({"prefs": {"young": True, "pick": True}, "sub": sub()}, True), ({"prefs": {"young": True, "pick": True, "daily": False}, "sub": sub({"daily": True})}, False),
            ({"prefs": {"young": True, "pick": True}, "sub": sub({"daily": False})}, False), ({"prefs": {"young": False, "pick": False}, "sub": sub({"daily": True})}, True),
            ({"prefs": None, "sub": "junk"}, True), ({"prefs": {"young": True}, "sub": sub({"daily": "no"})}, True)]
    check(all(A.wants(r, "daily") is w for r, w in rows) and A.wants({"prefs": {"young": False}, "sub": sub({"daily": True})}, "radar") is False
          and A.wants({"prefs": {"pick": True}, "sub": sub({"pick": False})}, "pick") is True,
          "SH8 the phone's switch: prefs.daily, else the subscription's memebot.daily, else on; the other kinds read their own settings as before")
    src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    pj = A.PAGE_JS
    check("if kind != \"test\" and not wants(row, kind):" in src and "prefs={young:true,pick:true,daily:true}" in pj and "['young','pick','daily'].forEach" in pj
          and "j.memebot={daily:prefs.daily!==false};" in pj and "['daily','Tagesbericht um 21 Uhr'" not in pj
          and "['young','Radar 🚀: the rocket hunter buys on paper'" in pj and "['pick','Pick: bought on paper ('" in pj and "Only paper purchases notify:" in pj
          and "These apply once notifications are on." in pj,
          "SH8 the page: two switches, the two buy notifications (the Tagesbericht's switch is gone while app.QUIET keeps it off; its pref is still saved)")
    old = os.environ.pop("MEMEBOT_PUSH_ALL", None)
    try:
        quiet = {k: A.notify(k, "t", "b") for k in ("young", "radar", "curve", "daily")}
        pick_no = [A.notify_pick({"t": 1, "picks": [dict(sym="P1", bought=b)]}) for b in (None, "held", "watch coin", True, 0)]
        rk_sell = A.notify_rocket([], {"trades": 1}, [{"sym": "R1", "mult": 0.7, "eur": -6.0, "why": "stop"}])
        on = A.buy_only() and A.bought_now({"bought": 50.0}) and not A.bought_now({"bought": True})
    finally:
        if old is not None:
            os.environ["MEMEBOT_PUSH_ALL"] = old
    check(on and all(v.get("skipped") == "off: only buy notifications" for v in quiet.values()) and all(v.get("skipped") == "pick not bought" for v in pick_no)
          and rk_sell.get("skipped") == "no buys" and set(A.QUIET) == {"young", "radar", "curve", "daily"},
          "SH8 only buy notifications (the user, Oct 22): new coins, launch radar, curve, Tagesbericht skipped; a pick push only when the scan bought it; "
          "a rocket round with sells only stays quiet")
    sql = open(os.path.join(HERE, "supabase", "setup.sql"), encoding="utf-8").read()
    check("'young', case when jsonb_typeof(p_prefs->'young')" in sql and "'daily', case" not in sql and "length(sub::text) <= 4096" in sql,
          "SH8 setup.sql is unchanged in what it keeps (the switch rides in the subscription, which it stores whole): nothing to run again in Supabase")
    rs = []
    saved = A.notify
    try:
        A.notify = lambda kind, t, b, url=None: rs.append((kind, t, b, url)) or {"kind": kind, "sent": 1}
        ok = A.notify_daily("Tagesbericht 22.10.", "Pick: 1 Kauf · Nur Papiergeld.")
        bad = A.notify_daily("Tagesbericht", "safe buy now")
        none = A.notify_daily("", "x")
    finally:
        A.notify = saved
    check(rs == [("daily", "Tagesbericht 22.10.", "Pick: 1 Kauf · Nur Papiergeld.", "#tab-home")] and bad.get("skipped") and none.get("skipped"),
          "SH8 notify_daily opens the Start tab and never sends advice words or an empty message")


# ---------------------------------------------------------------- SH9
def _sh9(check):
    import yaml
    print("== shadow SH9: the workflows")
    raw = open(os.path.join(HERE, ".github", "workflows", "daily.yml"), encoding="utf-8").read()
    y = yaml.safe_load(raw)
    on = y.get(True) or y.get("on") or {}
    job = y["jobs"]["report"]
    steps = job["steps"]
    get = next(s for s in steps if "Get the accounts" in str(s.get("name")))
    send = next(s for s in steps if "daily.py run" in str(s.get("run")))
    inst = next(s for s in steps if "Install the push sender" in str(s.get("name")))
    rocket = open(os.path.join(HERE, ".github", "workflows", "rocket.yml"), encoding="utf-8").read()
    core = lambda t: [l.strip() for l in t.splitlines() if l.strip().startswith(("opts=", "if python3 -m venv", "elif timeout 60", "\"https://files.pythonhosted.org", "&& echo \"8c6ab"))]
    check(on.get("schedule") == [{"cron": "0 19,20 * * *"}] and "workflow_dispatch" in on and y["permissions"] == {"contents": "read"}
          and "git push" not in raw and "--force" not in raw and job.get("timeout-minutes", 99) <= 10
          and "secrets.GITHUB_TOKEN" in str(get.get("env")) and "SUPABASE" not in str(get.get("env"))
          and set((send.get("env") or {})) == {"SUPABASE_URL", "SUPABASE_SECRET_KEY", "MODE"} and "GITHUB_TOKEN" not in str(send)
          and inst.get("continue-on-error") is True and (inst.get("env") or {}).get("RESULTS_URL") == "" and core(inst["run"]) == core(rocket) and len(core(rocket)) == 5,
          "SH9 daily.yml: 19 and 20 UTC, read only (no push to any branch), the token only to read, the Supabase secrets only in the report "
          "step, the push sender installed exactly as rocket.yml does it")
    scan = yaml.safe_load(open(os.path.join(HERE, ".github", "workflows", "scan.yml"), encoding="utf-8"))
    pk = scan["jobs"]["peaks"]
    runs = [str(s.get("run") or "") for s in pk["steps"]]
    i_xg = next(i for i, r in enumerate(runs) if "exit_grid.py run" in r)
    i_sh = next((i for i, r in enumerate(runs) if r.strip().startswith("python3 shadow.py run --dir mb")), -1)
    i_up = next(i for i, s in enumerate(pk["steps"]) if str(s.get("name", "")).startswith("Push the peak docs"))
    st = pk["steps"][i_sh] if i_sh >= 0 else {}
    check(i_xg < i_sh < i_up and st.get("continue-on-error") is True and 0 < int(st.get("timeout-minutes") or 0) <= 2
          and st.get("if") == "steps.restore.outputs.ok == 'true'" and not st.get("env") and "--deadline-s 90" in st["run"]
          and int(pk["timeout-minutes"]) <= 19,
          "SH9 the peaks job asks for the shadow paths after the exit replay and before the push: soft, 2 minutes at most, without the token")


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
