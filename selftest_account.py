"""Selftest checks of the paper account block (page_account.py; fake money only): U1, U2 and U7 of the spec, plus the hooks in
report.py (and their fallback when page_account.py is missing), robustness against broken memepeak docs, escaping and, when
Playwright and a Chromium are installed, the layout at 390 and 1280 px in light and dark: the four orders, the short phone view
(strip figures and feed rows 7-20 behind folds), tap targets of 44 px, long tickers, the selected order's contrast and the live line.
U11 checks the block "Without the stop-loss" (max profit and max loss within 6 h, from the docs' x/eur and lo/eurLo): the stop and
take-profit tiles, the all-trades line, the per-trade list and its folds, the empty and partial states, escaping, the layout.
U12 checks the raw peak beside the filtered best (peak.py's rawX, its euros after fees and the short cut reason) in the all-trades line
and per trade.

The memepeak docs here are a stand-in written in the frozen doc shape (SPEC 5 WP2), so the checks need no peak.py.

    python3 selftest_account.py            runs the checks alone (ends ALL PASS or "N checks failed")
    selftest.main: account_checks(check, SKIPS)
"""
import glob, hashlib, html, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import report as R
import page_account as PA

T0 = 1791655866812          # the paper account's restart in the results data (2026-10-10 18:11:06 UTC)
MIN, H = 60_000, 3_600_000
XSS = "<img src=x onerror=alert(1)>"         # a coin name
XSS2 = "<img src=x onerror=alert(2)>"        # an exit reason
LONG = "SUPERLONGNAMECOINWITHNOSPACES2026"   # a ticker with no place to wrap


def _dump(d, coll, key, doc):
    os.makedirs(os.path.join(d, "db", coll), exist_ok=True)
    with open(os.path.join(d, "db", coll, key + ".json"), "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))


def fixture(d, peaks=True):
    """A recommend-mode db with paper positions since the restart (open and sold by every rule), one position before the restart,
    the curve, the marks and (peaks=True) one memepeak doc per closed window in every state, plus broken docs. The open position
    with the long ticker is marked at 15x, so its open P/L is above every sold one (the "Best trade" tile counts sold ones only)."""
    now = T0 + 9 * H
    pos = {
        "y-stop": dict(grp="young", sym="STOPPY", name="Stop Coin", t=T0 + 10 * MIN, entryAt=T0 + 11 * MIN, px=1.0, ticket=3.0),
        "y-tp": dict(grp="young", sym="MOON", name="Moon Coin", t=T0 + 20 * MIN, entryAt=T0 + 20 * MIN, px=2.0, ticket=3.0),
        "y-time": dict(grp="young", sym="SLOW", name="Slow Coin", t=T0 + 30 * MIN, entryAt=T0 + 30 * MIN, px=1.0, ticket=3.0),
        "y-rug": dict(grp="young", sym="DOGGO", name="Doggo", t=T0 + 40 * MIN, entryAt=T0 + 40 * MIN, px=1.0, ticket=3.0),
        "h-time": dict(grp="hold", sym="TOPPY", name="Top Pick", t=T0 + 50 * MIN, entryAt=T0 + 52 * MIN, px=1.0, ticket=50.0),
        "y-xss": dict(grp="young", sym=XSS, name="<b>bold</b>", t=T0 + 60 * MIN, entryAt=T0 + 60 * MIN, px=1.0, ticket=3.0),
        "y-nan": dict(grp="young", sym="NANPK", name="Nan Peak", t=T0 + 70 * MIN, entryAt=T0 + 70 * MIN, px=1.0, ticket=3.0),
        "y-path": dict(grp="young", sym="PATHY", name="Path Coin", t=T0 + 80 * MIN, entryAt=T0 + 80 * MIN, px=1.0, ticket=3.0),
        "y-open": dict(grp="young", sym=LONG, name="Long Name", t=T0 + 8 * H, entryAt=T0 + 8 * H, px=1.0, ticket=3.0),
        "h-open": dict(grp="hold", sym="NOPX", name="No Price", t=T0 + 8 * H + 5 * MIN, entryAt=T0 + 8 * H + 5 * MIN, px=1.0, ticket=50.0),
        "old-1": dict(grp="hold", sym="OLDIE", name="Old Coin", t=T0 - 30 * H, px=1.0, ticket=20.0, rule=M.RULE, tp=0.4),
    }
    for pid, p in pos.items():
        p.setdefault("addr", (hashlib.sha1(pid.encode()).hexdigest() * 2)[:44])
        p.setdefault("pair", "P" + p["addr"][:20])
        if pid != "old-1":
            p["paper"] = M.PAPER_RULE
        _dump(d, "memepos", pid, p)
    sells = {"y-stop": (0.68, "stop", T0 + 40 * MIN, True), "y-tp": (22.0, "tp", T0 + 2 * H, True), "y-time": (1.3, "time", T0 + 6.5 * H, False),
             "y-rug": (0.0, "rug", T0 + 3 * H, False), "h-time": (1.4, "time", T0 + 7 * H, False), "y-xss": (0.6, XSS2, T0 + 90 * MIN, True),
             "y-nan": (0.7, "stop", T0 + 100 * MIN, True), "y-path": (0.65, "stop", T0 + 150 * MIN, True), "old-1": (1.2, "time", T0 - 2 * H, False)}
    for pid, (px_, why, t, at) in sells.items():
        p = pos[pid]
        e = {"pos": pid, "t": t, "px": px_, "frac": 1.0, "why": why, "eur": round(M.pos_value(p, 1.0, px_ / p["px"]), 2), "grp": p["grp"]}
        if at:
            e["at"] = t - 3 * MIN                   # the candle that sold it, before the run that booked it
        _dump(d, "memeexit", pid + "-1", e)
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    marks = {"t": now, "px": {"y-open": 15.0}, "liq": {}, "miss": {}, "chk": {}, "cpx": {}}
    json.dump(marks, open(os.path.join(d, "db", "memebot", "marks.json"), "w"))
    json.dump({"rule": M.RULE, "horizon": "24h", "paperSince": T0, "paperRule": M.PAPER_RULE, "lastRun": now, "runs": 10}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    json.dump({"t": now, "rule": M.RULE, "picks": [], "young": [], "youngOf": 0}, open(os.path.join(d, "db", "memebot", "recommend.json"), "w"))
    for i, v in enumerate((0.0, -1.2, -3.5, 2.0, -6.1)):
        _dump(d, "memecurve", "c%d" % i, {"t": T0 + (i * 2 + 1) * H, "equity": M.BUDGET, "paper": {"invested": 10.0, "back": 0.0, "open": 0.0, "pnl": v, "n": 3}})
    if peaks:
        P = lambda pid, **k: dict({"v": 1, "pos": pid, "grp": pos[pid]["grp"], "sym": pos[pid]["sym"], "addr": pos[pid]["addr"], "pair": pos[pid]["pair"],
                                   "ticket": pos[pid]["ticket"], "t": pos[pid]["t"], "entryAt": pos[pid]["entryAt"], "end": pos[pid]["entryAt"] + 6 * H,
                                   "upd": now, "tries": 0, "px": pos[pid]["px"], "cpx": pos[pid]["px"], "base": pos[pid]["px"], "dead": None, "cut": [], "n": 300}, **k)
        val = lambda pid, x: round(M.pos_value(pos[pid], 1.0, x), 2)
        lo = lambda pid, x, m: dict(v=2, lo=x, loAt=pos[pid]["entryAt"] + m * MIN, eurLo=val(pid, x))
        _dump(d, "memepeak", "y-stop", P("y-stop", state="ok", src="m1", res=1, x=1.8, at=pos["y-stop"]["entryAt"] + 47 * MIN, rawX=1.9, x6=0.4,
                                       eur=val("y-stop", 1.8), eur6=val("y-stop", 0.4), **lo("y-stop", 0.35, 180)))
        _dump(d, "memepeak", "y-tp", P("y-tp", state="ok", src="m1", res=1, x=12.5, at=pos["y-tp"]["entryAt"] + 100 * MIN, rawX=12.5, x6=3.0,
                                     eur=val("y-tp", 12.5), eur6=val("y-tp", 3.0), **lo("y-tp", 0.9, 5)))
        _dump(d, "memepeak", "y-time", P("y-time", state="est", src="est", res=None, tries=3, x=1.2, at=None, rawX=None, x6=1.3,
                                       eur=val("y-time", 1.2), eur6=val("y-time", 1.3), **lo("y-time", 0.8, 360)))
        _dump(d, "memepeak", "y-rug", P("y-rug", state="ok", src="m1", res=1, x=1.0, at=pos["y-rug"]["entryAt"] + MIN, rawX=59257.0, x6=0.0,
                                      eur=val("y-rug", 1.0), eur6=0.0, dead={"at": T0 + 2 * H, "why": "rug"}, cut=["rug exit", "dust 59257.00x"], **lo("y-rug", 0.0, 80)))
        _dump(d, "memepeak", "h-time", P("h-time", state="ok", src="m15", res=15, x=2.0, at=pos["h-time"]["entryAt"] + 3 * H, rawX=2.0, x6=1.5,
                                       eur=val("h-time", 2.0), eur6=val("h-time", 1.5), cut=["unconfirmed <script>4.00x</script>"]))
        _dump(d, "memepeak", "y-path", P("y-path", state="est", src="est", res=None, tries=3, x=1.5, at=None, rawX=None, x6=None,      # an estimate from stored
                                       eur=val("y-path", 1.5), eur6=None, **lo("y-path", 0.65, 67)))                               # path closes: x6 unknown
        _dump(d, "memepeak", "y-xss", P("y-xss", state="unit", src="m1", res=1, rawX=3.0))
        _dump(d, "memepeak", "y-nan", P("y-nan", state="ok", src="m1", x="NaN", x6=None, eur=None, eur6=None))
        _dump(d, "memepeak", "nobody", P("y-stop", pos="nobody", state="ok", src="m1", x=99.0, eur=999.0))      # a doc of no known position
        _dump(d, "memepeak", "broken", "{not json")
        _dump(d, "memepeak", "weird", {"state": "glitch", "x": 5})
    return now, pos


def _text(h):
    h = re.sub(r"<style>.*?</style>|<script>.*?</script>", " ", h, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", h))


def _pane(page, key):
    m = re.search(r'<div class="pane %s" data-pa-sort="%s">(.*?)</table></div></div>' % (key, key), page, re.S)
    return m.group(1) if m else ""


def _syms(pane):
    return [html.unescape(s) for s in re.findall(r'<td class="c"><strong>(.*?)</strong>', pane)]


def _row(pane, sym):
    """The <tr> of one coin in a pane."""
    m = re.search(r'<tr><td class="c"><strong>%s</strong>.*?</tr>' % re.escape(html.escape(sym)), pane, re.S)
    return m.group(0) if m else ""


def _cat(st, key):
    m = re.search(r'<div class="pa-cat [a-z]+" data-pa="%s">.*?</details></div>' % key, st, re.S)
    return m.group(0) if m else ""


def _feed_rows(fd):
    """[(classes, time, BOUGHT|SOLD, symbol, amount)] of every feed row, in page order."""
    return re.findall(r'<li class="pa-ev ([^"]*)"><span class="tm">([^<]*)</span><i></i><span class="tx"><b class="act">(BOUGHT|SOLD)</b> <b>(.*?)</b>.*?'
                      r'<span class="am">([^<]*)</span>', fd)


def _tree(d):
    return {os.path.relpath(f, d): open(f, "rb").read() for f in glob.glob(os.path.join(d, "**", "*"), recursive=True)
            if os.path.isfile(f) and os.path.basename(f) != "report.html"}


def account_checks(check, skips=None):
    print("== the paper account block: survival header, three categories, activity feed, trades in four orders (page_account.py)")
    d = tempfile.mkdtemp(prefix="memebot-acct-")
    try:
        _checks(check, d, skips if skips is not None else [])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _checks(check, d, skips):
    now, pos = fixture(d)
    before = _tree(d)
    out = R.build(d, os.path.join(d, "report.html"), now=now)
    page = open(out, encoding="utf-8").read()
    check(_tree(d) == before and "could not be rendered" not in page and "could not be loaded" not in page,
          "the account block reads only: every db file is byte-identical after the page build, and every part rendered")
    D = R.collect(d, now)
    A = D["paper"]["acct2"]
    P = M.positions(d)
    marks = json.load(open(os.path.join(d, "db", "memebot", "marks.json")))
    acct = M.paper_account(P, T0, marks["px"])
    n_acct = sum(1 for p in P.values() if M.in_account(p, T0))

    # U1: the survival header is paper_account's numbers; "Best trade" is the best sold one, never an open position
    hdr = PA.header(D, A)
    rate = acct["pnl"] / acct["invested"]
    closed = [(pid, p) for pid, p in P.items() if M.in_account(p, T0) and p["_left"] <= 1e-9]
    best_pid, best_p = max(closed, key=lambda kv: sum(e["eur"] for e in kv[1]["_exits"]) - kv[1]["ticket"])
    best_pnl = round(sum(e["eur"] for e in best_p["_exits"]) - best_p["ticket"], 2)
    open_pnl = M.pos_value(P["y-open"], 1.0, marks["px"]["y-open"] / P["y-open"]["px"]) - P["y-open"]["ticket"]
    tile = lambda k: (re.search(r'<div class="pa-tile" data-pa-tile="%s">(.*?)</div>' % k, hdr, re.S) or re.match("", "")).group(0)
    want = [PA.eur(acct["pnl"], True), PA.pct1(rate), "%.1f%%" % (100.0 * acct["won"] / acct["nClosed"]), "%d<small> closed</small>" % acct["nClosed"],
            "%d open · " % acct["nOpen"], html.escape(PA.eur(best_pnl, True)), html.escape(best_p["sym"]), html.escape(PA.eur(acct["open"]))]
    check({k: v for k, v in A["stop"].items() if k != "winRate"} == acct and all(w in hdr for w in want) and "P/L since Oct 10" in hdr
          and 'class="pa-line bad"' in hdr and "pa-line-empty" not in hdr and open_pnl > best_pnl and LONG not in tile("best-trade"),
          "U1 the survival header is paper_account's numbers: %s, %s, win rate %s, %d closed, %d open, best sold trade %s %s (not the open one at %s), open value %s, the balance line" % (
              PA.eur(acct["pnl"], True), PA.pct1(rate), want[2], acct["nClosed"], acct["nOpen"], PA.eur(best_pnl, True), best_p["sym"], PA.eur(open_pnl, True), PA.eur(acct["open"])))
    check(A["noPx"] == D["paper"]["noPx"] == 1 and "if all sold now · 1 with no price yet, counted at 0" in tile("open-value"),
          "the Open value tile says how many open positions have no price yet and count 0 (%d)" % A["noPx"])
    ev = []
    for pid, p in P.items():
        if not M.in_account(p, T0):
            continue
        ev.append((p.get("entryAt") or p["t"], 1, "buy", p["sym"], None))
        for e in p["_exits"]:
            ev.append((e.get("at") or e["t"], 0, "sell", p["sym"], round(e["eur"] - p["ticket"] * e["frac"], 2)))
    ev.sort(key=lambda x: (-x[0], x[1]))
    fd = PA.feed(D, A)
    rows = [r for r in _feed_rows(fd) if " ph" not in " " + r[0]]
    got = [("buy" if k == "BOUGHT" else "sell", html.unescape(s)) for _, _, k, s, _ in rows]
    signs = [am[0] for _, _, k, _, am in rows if k == "SOLD"]
    want_signs = [("+" if v > 0 else ("−" if v < 0 else "0")) for _, _, k, _, v in ev if k == "sell"]
    days = re.findall(r'<li class="pa-day[^"]*">([^<]*)</li>', fd)
    check(got == [(k, s) for _, _, k, s, _ in ev] and signs == want_signs and len(rows) == len(A["feed"]) == A["feedN"] == n_acct + 8
          and [R.local(t).strftime("%H:%M") for t, *_ in ev] == [tm for _, tm, _, _, _ in rows] and "updated each scan · newest " + R.local(ev[0][0]).strftime("%H:%M") in fd,
          "U1 the feed is every buy (at entryAt) and every sale (at the candle's time, else the run's) since the restart, newest first, with its sign; "
          "the head names the newest event's time (%d rows)" % len(rows))
    check(days and set(days) == {"Sun Oct 11", "Sat Oct 10"} and "Today" not in fd and "Yesterday" not in fd,
          "the feed's day headers are dates (%s), never a 'Today' fixed at the build" % ", ".join(sorted(set(days))))
    big_feed = {"since": T0, "feedN": 330, "feed": [{"t": T0 + i * MIN, "k": "buy", "id": "x%d" % i, "sym": "S%d" % i, "grp": "young", "ticket": 3.0} for i in range(300, 0, -1)]}
    fd_big = PA.feed(dict(D, state={"lastRun": now}), big_feed)
    main_, fold_ = fd_big.split('<details', 1)
    cls_main = [c for c, *_ in _feed_rows(main_)]
    cls_fold = [c for c, *_ in _feed_rows(fold_)]
    check(len(cls_main) == PA.FEED_SHOWN == 20 and sum(1 for c in cls_main if c.endswith(" ex")) == 14 and len(cls_fold) == 14 + 280
          and all(c.endswith(" ph") for c in cls_fold[:14]) and not any(c.endswith((" ph", " ex")) for c in cls_fold[14:]) and len(cls_main) + 280 == PA.FEED_MAX == 300
          and "All since Oct 10 (330, newest 300 here)" in fd_big and 'class="fold-lite pa-more pa-f">' in fd_big,
          "U1 the feed shows the newest 20 (6 on a phone, rows 7-20 open the phone's fold) and folds the rest, at most 300 (330 events: the fold says so)")
    big = {}
    for i in range(160):                                  # 160 sold positions = 320 events through load itself
        pid = "b%03d" % i
        big[pid] = {"grp": "young", "sym": "B%d" % i, "t": T0 + i * MIN, "entryAt": T0 + i * MIN, "px": 1.0, "ticket": 3.0, "paper": M.PAPER_RULE, "_id": pid, "_left": 0.0,
                    "_exits": [{"pos": pid, "t": T0 + i * MIN + 30 * MIN, "px": 0.7, "frac": 1.0, "why": "stop", "eur": 2.05}]}
    A_big = PA.load(d, now, pos=big, px={}, since=T0)
    check(A_big["err"] is None and len(A_big["feed"]) == PA.FEED_MAX and A_big["feedN"] == 320 and A_big["feed"][0]["t"] == T0 + 159 * MIN + 30 * MIN
          and [f["t"] for f in A_big["feed"]] == sorted((f["t"] for f in A_big["feed"]), reverse=True),
          "load keeps the newest 300 of 320 feed events and counts all of them (the page never carries the whole history)")
    pct = {}
    for pid, p in P.items():
        if M.in_account(p, T0):
            back = sum(e["eur"] for e in p["_exits"])
            if p["_left"] > 1e-9:
                last = marks["px"].get(pid)
                if not last:
                    continue
                back += M.pos_value(p, p["_left"], last / p["px"])
            pct[p["sym"]] = (back / p["ticket"] - 1, p["t"])
    top_want = [s for s, _ in sorted(pct.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))]
    worst_want = [s for s, _ in sorted(pct.items(), key=lambda kv: (kv[1][0], -kv[1][1]))]
    new_want = [p["sym"] for _, p in sorted(((pid, p) for pid, p in P.items() if M.in_account(p, T0)), key=lambda kv: -kv[1]["t"])]
    best_want = [pos[pid]["sym"] for pid in ("y-tp", "h-time", "y-stop", "y-path", "y-time", "y-rug")]
    check(_syms(_pane(page, "top")) == top_want and _syms(_pane(page, "worst")) == worst_want and _syms(_pane(page, "new")) == new_want
          and _syms(_pane(page, "best")) == best_want and 'id="pa-s-new" checked' in page,
          "U1 the four orders: top %% %s, worst %% from %s, newest first, best in 6 h by its multiple (the position without a price has no %%)" % (
              [s[:12] for s in top_want[:3]], worst_want[0]))

    # U2: three strips, the hindsight chip, priced N of M, the filtered chip, the closed-row columns
    st = PA.strips(D, A)
    booked = {pid: json.load(open(os.path.join(d, "db", "memepeak", pid + ".json"))) for pid in ("y-stop", "y-tp", "y-time", "y-rug", "h-time", "y-path")}
    sixed = {pid: doc for pid, doc in booked.items() if doc["x6"] is not None}
    b_pnl = round(sum(doc["eur"] - pos[pid]["ticket"] for pid, doc in booked.items()), 2)
    s6_pnl = round(sum(doc["eur6"] - pos[pid]["ticket"] for pid, doc in sixed.items()), 2)
    rule_on = lambda pids: round(sum(sum(e["eur"] for e in P[pid]["_exits"]) - P[pid]["ticket"] for pid in pids), 2)
    same_b, same_6 = rule_on(booked), rule_on(sixed)
    priced = "priced 6 of %d · %d waiting · 2 estimated · 1 on 15-min candles · 1 not booked (price unit)" % (n_acct, n_acct - 6 - 1)
    same_line = lambda n, v: "same %d trades under the stop-loss rule: <b class=\"%s\">%s</b>" % (n, PA.tone(v), html.escape(PA.eur(v, True)))
    c_peak, c_six = _cat(st, "peak"), _cat(st, "six")
    check(all('data-pa="%s"' % k in st for k in ("stop", "peak", "six")) and st.count("hindsight, not a trading rule") == 2
          and html.escape(priced) in c_peak and html.escape(PA.eur(b_pnl, True)) in c_peak and html.escape(PA.eur(s6_pnl, True)) in c_six
          and same_line(6, same_b) in c_peak and same_line(5, same_6) in c_six and same_b != same_6
          and A["best"]["n"] == 6 and A["six"]["n"] == 5 == len(sixed) and "5 of %d trades" % n_acct in c_six and A["counts"]["open"] == 2,
          "U2 three strips: best within 6 h %s over 6 booked, held 6 h %s over the 5 whose 6-hour price is known (an estimate without it is left out, not "
          "counted 0), each with the stop-loss result of exactly its trades (%s, %s), '%s'" % (PA.eur(b_pnl, True), PA.eur(s6_pnl, True), PA.eur(same_b, True), PA.eur(same_6, True), priced))
    c_stop = _cat(st, "stop")
    won_w = 100.0 * acct["won"] / (acct["won"] + acct["lost"])
    figs = ['<dd>%s</dd>' % html.escape(PA.eur(acct[k])) for k in ("invested", "back", "open")]
    check(html.escape(PA.eur(acct["pnl"], True)) in c_stop and html.escape("%s on %s invested" % (PA.pct1(rate), PA.eur(acct["invested"]))) in c_stop
          and c_stop.count(figs[0]) == c_stop.count(figs[1]) == c_stop.count(figs[2]) == 2 and "%d won · %d lost" % (acct["won"], acct["lost"]) in c_stop
          and 'style="width:%.1f%%"' % won_w in c_stop and html.escape(PA.eur(b_pnl, True)) not in c_stop and 'class="det"' in c_stop and 'class="ph"' in c_stop,
          "the stop-loss strip holds its own numbers: P/L %s, %s on %s invested, back %s, open %s, %d won · %d lost and its bar (%.1f%% won)" % (
              PA.eur(acct["pnl"], True), PA.pct1(rate), PA.eur(acct["invested"]), PA.eur(acct["back"]), PA.eur(acct["open"]), acct["won"], acct["lost"], won_w))
    newp = _pane(page, "new")
    r_stop, r_path = _row(newp, "STOPPY"), _row(newp, "PATHY")
    cell = lambda r, k: (re.search(r'<td class="h %s">(.*?)</td>' % k, r, re.S) or re.match("", "")).group(0)
    check('<span class="chip warn" data-pa="filtered">59,257x ignored: pool dead</span>' in newp and "filtered: not confirmed by the next close" in newp
          and "<th>best in 6 h (hindsight)</th><th>at 6 h (hindsight)</th>" in newp and "at 47 min · +" in newp and " · 15-min candles" in newp and " · estimate" in newp
          and newp.count("window open") == 4 and "not booked" in newp and "price unit mismatch" in newp and "<script>4.00x" not in page
          and "1.80x" in cell(r_stop, "h1") and "0.40x" in cell(r_stop, "h2") and "1.80x" not in cell(r_stop, "h2") and "unknown" in cell(r_path, "h2"),
          "U2 the closed rows carry best in 6 h (multiple, when, P/L) and at 6 h (STOPPY 1.80x, then 0.40x at 6 h; an estimate without it 'unknown'), "
          "the filtered chip with its first reason (59,257x ignored: pool dead), estimate, 15-min, unit, window open")
    i_trades, i_card = page.find('data-pa="trades"'), page.find('class="card pos hold"')
    check("Top trades · 8 closed · 2 open" in page and "Before the restart (1 trade)" in page and "bought before the paper account restarted on " in page
          and "profit/loss since the restart on " in page and 'class="acct"' not in page and 'data-pa="header"' in page and page.count("<style>%s</style>" % PA.CSS) == 1
          and 0 < i_trades < i_card,
          "the hooks: the account block replaces the old strip; 'Top trades · N closed · N open' comes before the open positions; the trades before "
          "the restart and the curve fold stay")
    cv = PA.curve(D, A)
    ends = sorted(doc["end"] for doc in booked.values())
    tv = cv.split("<summary>Table view</summary>", 1)[-1]
    check('class="line s2 dash"' in cv and "best within 6 h (hindsight), by window end" in cv and "dashed: best within 6 h (hindsight), 6 windows" in cv
          and A["peakPts"][-1][1] == b_pnl and [t for t, _ in A["peakPts"]] == ends and "break-even 0.00" not in cv and '<span class="pa-zleg">break-even (0)</span>' in cv
          and "<th>window end</th><th class=\"n\">best within 6 h (hindsight)</th>" in tv and tv.count("<tr><td>") == 5 + len(ends),
          "the curve fold carries the dashed hindsight line, cumulative by each window's end (ends at %s); the 'break-even' text the dashed line would "
          "cross is left out and named in the legend; the table view lists both lines" % PA.eur(b_pnl, True))
    one = PA.curve(D, dict(A, peakPts=[]))
    check("break-even 0.00" in one and "pa-zleg" not in one and "<th>window end</th>" not in one,
          "with the stop-loss line alone the curve keeps its 'break-even 0.00' label and one table")
    y_open = [r for r in PA.load(d, T0 + 14 * H + MIN)["rows"] if r["id"] == "y-open"]
    y_late = [r for r in PA.load(d, T0 + 14 * H + 3 * MIN)["rows"] if r["id"] == "y-open"]
    check(y_open and y_open[0]["windowOpen"] and y_late and not y_late[0]["windowOpen"],
          "a 6-hour window counts as closed only 2 minutes after its end, as in peak.py (window open at end + 1 min, closed at end + 3 min)")

    # U7: honest words, every hindsight number labelled
    new_ui = "".join(f(D, A) for f in (PA.header, PA.strips, PA.feed, PA.trades, PA.curve))
    words = _text(new_ui)
    hits = re.findall(r"(?i)\b(safe|safely|guaranteed?|buy|buys|buying)\b", words)
    h_cells = re.findall(r'<td class="h h[12]">', new_ui)
    tables = re.findall(r"<table>.*?</table>", PA.trades(D, A), re.S)
    check(not hits and "\u2014" not in words and h_cells and all("(hindsight)</th>" in t for t in tables if 'class="h h1"' in t)
          and 'content:"best in 6 h (hindsight)"' in PA.CSS and 'content:"at 6 h (hindsight)"' in PA.CSS
          and all("hindsight" in c for c in (c_peak, c_six)),
          "U7 no 'safe', 'guaranteed' or 'buy' and no em dash in the new text; every hindsight number sits under a hindsight label (%d cells)" % len(h_cells))

    # robustness: no memepeak docs, nothing bought, a broken load, a missing module, escaping
    d2 = tempfile.mkdtemp(prefix="memebot-acct0-")
    try:
        fixture(d2, peaks=False)
        D2 = R.collect(d2, now)
        A2 = D2["paper"]["acct2"]
        st2 = PA.strips(D2, A2)
        check(A2["best"]["n"] == 0 and html.escape("priced 0 of %d · %d waiting · 0 estimated · 0 on 15-min candles" % (n_acct, n_acct)) in st2
              and '<div class="v muted">–</div>' in st2 and A2["stop"] == A["stop"],
              "without memepeak docs: priced 0 of %d, the hindsight strips show a dash, the stop-loss account is unchanged" % n_acct)
    finally:
        shutil.rmtree(d2, ignore_errors=True)
    A0 = PA.load(d, now, pos={}, px={}, since=T0)
    h0 = PA.header(dict(D, curve=[]), A0)
    check(A0["err"] is None and "<span>nothing bought yet</span>" in h0 and " on 0.00" not in h0 and "nothing bought yet" in PA.strips(D, A0),
          "with nothing bought yet the header says so instead of a rate on 0.00 invested")
    bad = PA.load(d, now, pos={"x": "not a position"}, px={}, since=T0)
    sec_bad = PA.section(dict(D, paper=dict(D["paper"], acct2=bad)))
    check(bad.get("err") and "could not be read this time" in sec_bad and "could not be rendered" not in sec_bad,
          "a load that fails leaves a note and empty categories; the page still renders (%s)" % (bad.get("err") or "")[:60])
    saved = sys.modules.get("page_account")
    sys.modules["page_account"] = None            # what a missing or broken page_account.py looks like to report.py
    try:
        out_fb = R.build(d, os.path.join(d, "report-fb.html"), now=now)
        page_fb = open(out_fb, encoding="utf-8").read()
    except Exception as e:
        page_fb = "build failed: %s" % e
    finally:
        sys.modules["page_account"] = saved
        if os.path.exists(os.path.join(d, "report-fb.html")):
            os.remove(os.path.join(d, "report-fb.html"))
    check('class="acct"' in page_fb and re.search(r"could not be loaded this time \((?:ModuleNotFound|Import)Error\)", page_fb) and "could not be rendered" not in page_fb
          and "Profit/loss over time" in page_fb and 'data-pa="header"' not in page_fb,
          "without page_account.py the page still builds: the plain account strip, the open positions, the trades and the curve as before, with a note")
    check(XSS not in page and html.escape(XSS) in page and "<b>bold</b>" not in page and XSS2 not in page and html.escape(XSS2) + " (1)" in PA.trades(D, A)
          and html.escape(XSS2) in fd and A["counts"]["unit"] == 1 and not any(r["pk"] and r["pk"]["state"] in PA.BOOKED for r in A["rows"] if r["id"] == "y-nan"),
          "coin names, exit reasons (in the feed and the 'N sold: ...' line) and filter reasons are escaped; a booked doc without a finite multiple is not "
          "booked; docs of unknown positions and broken files are skipped")
    cuts = {"pool dead: rug exit, last healthy scan 40 min after the buy": "pool dead", "pool dead: liquidity $310 at minute 12": "pool dead",
            "collapse: under 10% at minute 30, no recovery within 30 min": "pool dead", "dust: 59,257x on $3 volume": "too little volume",
            "unconfirmed: 4.00x held for one candle only": "not confirmed by the next close", "jump: 1 level over 3x the previous close without support": "not confirmed",
            "cap: 1 level over 30x or a $100M market cap without support": "not confirmed (over 30x or $100M cap)",
            "unit: candles 5.0x away from DexScreener's price at minute 3": "price unit mismatch", "rug exit": "pool dead"}
    got_cuts = {k: PA.cut_reason([k]) for k in cuts}
    check(got_cuts == cuts, "every peak.py cut text maps to its plain reason; a cap cut names both limits (over 30x or $100M cap)")

    # the balance line's "break-even" label goes where the line does not pass
    W, Hh = 600.0, 102.0
    y0 = 51.0
    rising = [(0, 90.0), (480, 90.0), (600, 20.0)]            # flat below zero, crossing it in the last fifth
    falling = [(0, 51.0), (300, 70.0), (600, 96.0)]            # ends far below zero: the right end above the zero line is free
    zigzag = [(i * 50.0, 20.0 if i % 2 else 80.0) for i in range(13)]   # up and down through zero all along: every place is taken
    lab = PA.zero_label(rising, y0, W, Hh)
    side_ok = lab and lab[0] == "left" and not PA._crosses(rising, 0, 0.26 * W, lab[1] - 1, lab[1] + 14) and PA.zero_label(falling, y0, W, Hh) == ("right", 36)
    D_cross = dict(D, curve=[{"t": T0 + i * H, "paper": {"pnl": v}} for i, v in enumerate((-5.0, -5.0, -5.0, -5.0, 0.5, 5.0))])
    bl = PA.balance_line(D_cross, A)
    D_flat = dict(D, curve=[{"t": T0 + i * H, "paper": {"pnl": 5.0 if i % 2 else -5.0}} for i in range(13)])
    check(side_ok and PA.zero_label(zigzag, y0, W, Hh) is None and 'class="zl" style="left:0;top:36px"' in bl and 'class="zl"' not in PA.balance_line(D_flat, A),
          "the balance line's 'break-even' label sits where the line does not pass: the right end when it is free, the left end when the line crosses zero "
          "at the right, none when the line runs up and down through zero all along")

    _noloss_checks(check, d, D, A, P, pos, page, now)
    _browser(check, page, skips)


def _noloss_checks(check, d, D, A, P, pos, page, now):
    """U11: the block "Without the stop-loss" (hindsight): every number from the docs, the states, escaping."""
    nl = PA.noloss(D, A)
    docs = {pid: json.load(open(os.path.join(d, "db", "memepeak", pid + ".json"))) for pid in ("y-stop", "y-tp", "y-time", "y-rug", "h-time", "y-path")}
    with_lo = {pid: doc for pid, doc in docs.items() if doc.get("lo") is not None}
    real = lambda pid: round(sum(e["eur"] for e in P[pid]["_exits"]) - P[pid]["ticket"], 2)
    pc = lambda v: html.escape(PA.pct_f(v))
    tile = lambda k: (re.search(r'<div class="nl-tile %s" data-nl="%s">.*?</div></div>(?=<div class="nl-tile|</div><div class="nl-all|</div><details)' % (k, k), nl, re.S)
                      or re.match("", "")).group(0)
    vals = lambda h: dict(re.findall(r'data-nl-v="(\w+)">([^<]*)<', h))
    ts, tt = tile("stop"), tile("tp")
    s_ids = ("y-stop", "y-path")                       # sold at the stop and priced; y-nan (stop, a doc without a number) is not
    s_best = round(sum(docs[k]["eur"] - pos[k]["ticket"] for k in s_ids), 2)
    s_worst = round(sum(docs[k]["eurLo"] - pos[k]["ticket"] for k in s_ids), 2)
    s_real = round(sum(real(k) for k in s_ids), 2)
    s_bp = max(docs[k]["eur"] / pos[k]["ticket"] - 1 for k in s_ids)
    s_lp = min(docs[k]["eurLo"] / pos[k]["ticket"] - 1 for k in s_ids)
    st = A["noloss"]["stop"]
    check(st["of"] == 3 and st["n"] == 2 and (st["best"], st["worst"], st["real"]) == (s_best, s_worst, s_real) and st["back"] == 1
          and vals(ts) == {"worst": PA.eur(s_worst, True), "best": PA.eur(s_best, True), "real": PA.eur(s_real, True)}
          and "worst trade %s" % pc(s_lp) in ts and "best trade %s" % pc(s_bp) in ts and "priced 2 of 3" in ts and "1 of 2 back above the entry" in ts
          and "Sold at −30% (stop)" in ts,
          "U11 the stop tile: 2 of 3 stop trades priced (one doc has no number); max profit %s (best trade %s), max loss %s (worst trade %s), the stop "
          "made %s with the same trades; 1 of 2 back above the entry after the stop (the other's best has no time)" % (
              PA.eur(s_best, True), PA.pct_f(s_bp), PA.eur(s_worst, True), PA.pct_f(s_lp), PA.eur(s_real, True)))
    t_best, t_worst = round(docs["y-tp"]["eur"] - 3.0, 2), round(docs["y-tp"]["eurLo"] - 3.0, 2)
    tp = A["noloss"]["tp"]
    check(tp["of"] == tp["n"] == 1 and tp["back"] == 1 and vals(tt) == {"worst": PA.eur(t_worst, True), "best": PA.eur(t_best, True), "real": PA.eur(real("y-tp"), True)}
          and "best trade %s" % pc(docs["y-tp"]["eur"] / 3.0 - 1) in tt and "1 trade<" in tt and "1 of 1 rose further" in tt and "Sold at +1,000% (take-profit)" in tt
          and t_best > real("y-tp") > 0 > t_worst,
          "U11 the take-profit tile: how high it went within 6 h (12.5x: %s) and its low (0.9x: %s) against what the take-profit made (%s); its best "
          "came after the sale, so it rose further" % (PA.eur(t_best, True), PA.eur(t_worst, True), PA.eur(real("y-tp"), True)))
    al = A["noloss"]["all"]
    ids = sorted(with_lo)
    a_best = round(sum(docs[k]["eur"] - pos[k]["ticket"] for k in ids), 2)
    a_worst = round(sum(docs[k]["eurLo"] - pos[k]["ticket"] for k in ids), 2)
    a_real = round(sum(real(k) for k in ids), 2)
    line = (re.search(r'<div class="nl-all" data-nl="all">.*?</div>', nl, re.S) or re.match("", "")).group(0)
    eraw = lambda k: round(M.pos_value(pos[k], 1.0, docs[k]["rawX"]), 2) if k in ("y-stop", "y-rug") else docs[k]["eur"]    # rawX over 1.05x the best
    a_raw = round(sum(eraw(k) - pos[k]["ticket"] for k in ids), 2)
    check(ids == ["y-path", "y-rug", "y-stop", "y-time", "y-tp"] and (al["n"], al["of"]) == (5, 8) and (al["best"], al["worst"], al["real"]) == (a_best, a_worst, a_real)
          and vals(line) == {"best": PA.eur(a_best, True), "worst": PA.eur(a_worst, True), "real": PA.eur(a_real, True), "raw": PA.eur(a_raw, True)}
          and "All 5 priced trades, sold each" in line and al["raw"] == a_raw and al["rawN"] == 2 and "2 not sellable there" in line
          and "priced 5 of 8 · 2 inside their 6 h" in nl and docs["y-rug"]["eurLo"] == 0.0 and A["noloss"]["open"] == 2,
          "U11 the all-trades line over the 5 trades with both ends priced (a doc without a low, the unit doc and the unreadable one wait): every trade "
          "sold at its best %s, at the raw top %s (2 not sellable there), at its lowest %s (a dead pool at 0), what the stop-loss rule made %s; "
          "'priced 5 of 8 · 2 inside their 6 h'" % (PA.eur(a_best, True), PA.eur(a_raw, True), PA.eur(a_worst, True), PA.eur(a_real, True)))
    r_dog = (re.search(r'<tr><td class="c"><strong>DOGGO</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    r_sto = (re.search(r'<tr><td class="c"><strong>STOPPY</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    r_moon = (re.search(r'<tr><td class="c"><strong>MOON</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    raw_cases = {("collapse: under 10% at minute 279, no recovery within 30 min", "unconfirmed: 303x held for one candle only", 303.437, 3.77): "one candle",
                 ("pool dead: rug exit, last healthy scan 40 min after the entry", "dust: 59,257x on $3 volume", 59257.0, 1.0): "dust volume",
                 ("cap: 1 level over 30x or a $100M market cap without support", "", 80.0, 5.0): "over the cap",
                 ("jump: 1 level over 3x the previous close without support", "", 12.0, 2.0): "jump not held",
                 ("collapse: under 10% at minute 30, no recovery within 30 min", "", 9.0, 1.2): "pool died",
                 ("collapse: under 10% at minute 93, no recovery within 30 min", "", 2.68, 2.16): "one candle",
                 ("", "", 1.9, 1.85): "", ("", "", None, 1.2): ""}
    got_raw = {k: PA.raw_reason({"cut": [c for c in k[:2] if c], "rawX": k[2], "x": k[3]}) for k in raw_cases}
    check(got_raw == raw_cases and "raw top 59,257x %s · pool died" % html.escape(PA.eur(eraw("y-rug") - 3.0, True)) in r_dog
          and "raw top 1.90x %s · one candle" % html.escape(PA.eur(eraw("y-stop") - 3.0, True)) in r_sto and "raw top" not in r_moon
          and r_dog.find("data-nl-raw") > r_dog.find('<td class="hi">') and r_dog.find("data-nl-raw") < r_dog.find('<td class="lo">'),
          "U12 the raw peak beside the filtered best: per trade under its max profit (DOGGO's 59,257x print would have been %s, the pool died; "
          "STOPPY's 1.90x top one candle), none where they agree (MOON); the reason in two words from peak.py's cut: the rule that names the raw "
          "multiple (one candle, dust volume), else over the cap, jump not held, pool died (ZPAD's 303x on the results branch: one candle)" % PA.eur(eraw("y-rug") - 3.0, True))
    rows_nl = re.findall(r'<tr><td class="c"><strong>(.*?)</strong>.*?</tr>', nl, re.S)
    r_stop = (re.search(r'<tr><td class="c"><strong>STOPPY</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    r_rug = (re.search(r'<tr><td class="c"><strong>DOGGO</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    r_ht = (re.search(r'<tr><td class="c"><strong>TOPPY</strong>.*?</tr>', nl, re.S) or re.match("", "")).group(0)
    want_order = [html.escape(p["sym"]) for _, p in sorted(((k, p) for k, p in P.items() if M.in_account(p, T0) and k not in ("y-open", "h-open")), key=lambda kv: -kv[1]["t"])]
    check(rows_nl == want_order and pc(docs["y-stop"]["eur"] / 3 - 1) + "</span><small>at 47 min" in r_stop and pc(docs["y-stop"]["eurLo"] / 3 - 1) + "</span><small>at 3.0 h" in r_stop
          and "−100%</span><small>at 80 min" in r_rug and r_ht.count("waiting") == 2 and "estimate" in (re.search(r"<strong>PATHY</strong>.*?</tr>", nl, re.S) or re.match("", "")).group(0)
          and "Per trade (8)" in nl and "Older trades" not in nl and "max profit</th><th class=\"n\">max loss</th>" in nl,
          "U11 the per-trade list: the 8 trades whose 6 hours are over, newest first, each with its real result, max profit and max loss in %% after "
          "fees and when (STOPPY %s at 47 min, %s at 3.0 h; DOGGO −100%% where the pool died), 'waiting' for a doc without a low, 'estimate' marked" % (
              PA.pct_f(docs["y-stop"]["eur"] / 3 - 1), PA.pct_f(docs["y-stop"]["eurLo"] / 3 - 1)))
    check(XSS not in nl and html.escape(XSS) in nl and XSS2 not in nl and html.escape(XSS2) in nl and "<b>bold</b>" not in nl
          and not re.findall(r"(?i)\b(safe|safely|guaranteed?|buy|buys|buying)\b", _text(nl)) and "\u2014" not in _text(nl)
          and _text(nl).lower().count("hindsight") == 2 and "Fake money, nothing is bought for real." in _text(nl) and 'data-pa="noloss"' in page
          and page.find('data-pa="noloss"') > page.find('data-pa="six"') and page.find('data-pa="noloss"') < page.find('data-pa="feed"'),
          "U11 the block sits right under the three category cards; coin names and exit reasons are escaped; the hindsight label once (and in the ⓘ), "
          "the fake-money note in the ⓘ, no 'safe', 'guaranteed' or 'buy' and no em dash")
    # states: no docs at all, nothing bought yet, a long history
    A_empty = PA.load(d, now, pos=dict(P), px={}, since=T0)
    for r in A_empty["rows"]:
        r["pk"] = None
    e_nl = PA.noloss(D, dict(A_empty, noloss=PA.noloss_data(A_empty["rows"])))
    A0 = PA.load(d, now, pos={}, px={}, since=T0)
    z_nl = PA.noloss(D, A0)
    check("priced 0 of 8 · 2 inside their 6 h" in e_nl and e_nl.count("priced after the next scans") == 2 and "priced 0 of 3" in e_nl and 'data-nl="all"' not in e_nl
          and "waiting" in e_nl and "no 6 hours over yet" in z_nl and "no trade sold at the stop yet" in z_nl and "no trade sold at the take-profit yet" in z_nl
          and "Per trade" not in z_nl and A0["err"] is None,
          "U11 the states: nothing priced yet ('priced 0 of 8', each tile 'priced after the next scans', no all-trades line, the list waits); nothing "
          "bought yet ('no 6 hours over yet', no list)")
    big = {}
    for i in range(330):
        pid = "b%03d" % i
        big[pid] = {"grp": "young", "sym": "B%d" % i, "t": T0 + i * MIN, "entryAt": T0 + i * MIN, "px": 1.0, "ticket": 3.0, "paper": M.PAPER_RULE, "_id": pid, "_left": 0.0,
                    "_exits": [{"pos": pid, "t": T0 + i * MIN + 30 * MIN, "px": 0.7, "frac": 1.0, "why": "stop", "eur": 2.05}]}
    A_big = PA.load(d, T0 + 30 * H, pos=big, px={}, since=T0)
    b_nl = PA.noloss(D, A_big)
    first, inner = b_nl.split("<summary>Older trades", 1) if "<summary>Older trades" in b_nl else (b_nl, "")
    check(A_big["noloss"]["listN"] == 330 and len(A_big["noloss"]["list"]) == PA.NL_MAX == 300 and first.count("<tr><td") == PA.NL_SHOWN == 50
          and inner.count("<tr><td") == 250 and "Older trades (280)" in b_nl and "The newest 300 are here; 30 older ones are not shown." in b_nl
          and re.findall(r"<strong>(B\d+)</strong>", first)[:2] == ["B329", "B328"],
          "U11 a long history: the newest 50 in the list, the next 250 in a fold inside it, the 30 oldest named but left out (the page stays small)")


# in the page: what the phone view shows, tap targets, a long ticker, the selected order's contrast
PROBE = r"""
() => {
  const sec = document.querySelector('section[data-app="account"]');
  const vis = (e) => e.checkVisibility ? e.checkVisibility({visibilityProperty: true}) : !!e.offsetParent;
  const n = (sel) => Array.from(sec.querySelectorAll(sel)).filter(vis).length;
  const small = [];
  sec.querySelectorAll('details.pa-i > summary, details.pa-f > summary, .pa-tt .bar label').forEach((e) => {
    if (!vis(e)) return; const r = e.getBoundingClientRect(); if (r.height < 44 - 0.5) small.push(e.textContent.trim().slice(0, 30) + ' ' + Math.round(r.height)); });
  const over = [];
  sec.querySelectorAll('.pa-tbl tr').forEach((tr) => { const c = tr.querySelector('td.c strong'), p = tr.querySelector('td.p'); if (!c || !p || !vis(c)) return;
    const rg = document.createRange(); rg.selectNodeContents(c); const pr = p.getBoundingClientRect(), tr_ = tr.getBoundingClientRect();
    for (const r of rg.getClientRects()) { const ix = Math.min(r.right, pr.right) - Math.max(r.left, pr.left), iy = Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top);
      if ((ix > 1 && iy > 1) || r.right > tr_.right + 1) over.push(c.textContent.slice(0, 16)); } });
  sec.querySelectorAll('details.hold > summary .who').forEach((w) => { if (!vis(w)) return; const card = w.closest('details').getBoundingClientRect();
    const rg = document.createRange(); rg.selectNodeContents(w); for (const r of rg.getClientRects()) if (r.right > card.right + 1) over.push('card ' + w.textContent.slice(0, 16)); });
  const rgb = (c) => { let m = c.match(/^rgba?\(([^)]+)\)/); if (m) return m[1].split(/[\s,\/]+/).filter(Boolean).slice(0, 3).map(Number);
    m = c.match(/^color\(srgb ([^)]+)\)/); return m ? m[1].split(/[\s\/]+/).filter(Boolean).slice(0, 3).map((v) => 255 * Number(v)) : null; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const lab = Array.from(sec.querySelectorAll('.pa-tt .bar label')).find((l) => document.getElementById(l.htmlFor).checked);
  let contrast = 0;
  if (lab) { const cs = getComputedStyle(lab), a = rgb(cs.color), b = rgb(cs.backgroundColor); if (a && b) { const l1 = lum(a), l2 = lum(b); contrast = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); } }
  const cats = sec.querySelector('.pa-cats').getBoundingClientRect().height;
  const nlb = sec.querySelector('[data-pa="noloss"]'), nlt = Array.from(sec.querySelectorAll('.nl-tile')).map((e) => e.getBoundingClientRect());
  const nlOver = Array.from(sec.querySelectorAll('[data-pa="noloss"] *')).filter((e) => vis(e) && e.getBoundingClientRect().right > nlb.getBoundingClientRect().right + 1).length;
  return {feed: n('[data-pa="feed"] > ol .pa-ev'), feedAll: n('[data-pa="feed"] .pa-ev'), det: n('.pa-cat .det'), ph: n('.pa-cat .ph'), same: n('.pa-cat .same'),
          small: small, over: over, contrast: Math.round(contrast * 100) / 100, cats: Math.round(cats), iw: innerWidth, sw: document.documentElement.scrollWidth,
          nlH: nlb ? Math.round(nlb.getBoundingClientRect().height) : -1, nlTops: nlt.map((r) => Math.round(r.top)), nlW: nlt.map((r) => Math.round(r.width)), nlOver: nlOver};
}
"""


def _browser(check, page_html, skips):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the browser checks of the paper account (no Playwright)")
        print("  SKIP the browser checks of the paper account: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    url = "https://some-owner.github.io/Meme-Bot/"
    wide, errs, live, views = [], [], [], {}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            for w, h in ((390, 844), (1280, 900)):
                for scheme in ("light", "dark"):
                    phone = {"is_mobile": True, "has_touch": True, "device_scale_factor": 2} if w == 390 else {}
                    ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, **phone)
                    pg = ctx.new_page()
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.route("**/*", lambda r: r.fulfill(status=200, body=page_html, headers={"Content-Type": "text/html; charset=utf-8"})
                             if r.request.url.startswith(url) else r.abort())
                    pg.goto(url)
                    closed = pg.evaluate(PROBE)
                    pg.evaluate("document.querySelectorAll('section[data-app=\"account\"] details').forEach(function(x){x.open=true;})")
                    for k in ("new", "top", "worst", "best"):
                        pg.locator('label[for="pa-s-%s"]' % k).click()
                        vis = pg.evaluate("Array.from(document.querySelectorAll('[data-pa-sort]')).filter(function(e){return e.offsetParent!==null;}).map(function(e){return e.getAttribute('data-pa-sort');})")
                        sw = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                        wide.append((w, scheme, k, vis == [k], sw[0] <= sw[1] == w))
                    pg.locator('label[for="pa-s-top"]').click()
                    views[(w, scheme)] = (closed, pg.evaluate(PROBE))
                    if w == 390 and scheme == "light":
                        hidden0 = pg.evaluate("document.querySelector('[data-acct-live]').hidden")
                        pg.evaluate("window.dispatchEvent(new CustomEvent('memebot-live',{detail:{state:'live',via:'github',status:{agents:[{id:'trader',status:'running',"
                                    "lines:['first','bought <b>X</b> for 3 €']}]}}}))")
                        on = pg.evaluate("[document.querySelector('[data-acct-live]').hidden, document.querySelector('[data-acct-live] span').textContent, "
                                         "document.querySelectorAll('[data-acct-live] b').length]")
                        pg.evaluate("window.dispatchEvent(new CustomEvent('memebot-live',{detail:{state:'paused',status:{agents:[{id:'trader',status:'running',lines:['x']}]}}}))")
                        off = pg.evaluate("document.querySelector('[data-acct-live]').hidden")
                        live.append((hidden0, on, off))
                    ctx.close()
            br.close()
    except Exception as e:
        check(False, "the browser checks of the paper account ran (%s)" % str(e)[:160])
        return
    n_ev = 18                                                  # the fixture's feed events
    check(wide and all(v and s for *_, v, s in wide),
          "in Chromium at 390 (phone emulation) and 1280 px, light and dark, with every fold open: each of the four orders shows alone and nothing "
          "scrolls sideways or widens the phone's layout (%d views)" % len(wide))
    ph_c, ph_o = views[(390, "light")]
    dt_c, dt_o = views[(1280, "light")]
    check(ph_c["feed"] == PA.FEED_PHONE and ph_c["det"] == 0 and ph_c["ph"] == 0 and ph_c["same"] == 2 and ph_o["ph"] == 3 and ph_o["det"] == 0 and ph_o["feedAll"] == n_ev
          and dt_c["feed"] == min(n_ev, PA.FEED_SHOWN) and dt_c["det"] == 3 and dt_o["ph"] == 0 and dt_o["feedAll"] == n_ev and ph_c["cats"] <= 640,
          "a phone shows the short view: each strip keeps its P/L, rate and 'same trades' line (figures in its fold), 6 feed rows (the other %d open the fold); "
          "a wide screen shows the figures and %d rows (strips %d px high on the phone)" % (n_ev - PA.FEED_PHONE, min(n_ev, PA.FEED_SHOWN), ph_c["cats"]))
    small = [s for (w, _), vv in views.items() if w == 390 for v in vv for s in v["small"]]
    check(not small, "at 390 px every ⓘ, fold and order chip of the account block is at least 44 px high, folds closed and open (%s)" % (small[:4] or "all"))
    over = [s for (w, _), vv in views.items() if w == 390 for v in vv for s in v["over"]]
    check(not over, "at 390 px a %d-letter ticker wraps inside its cell and its open-position card, never over the %% cell or past the edge (%s)" % (len(LONG), over[:3] or "none"))
    con = {k: v[1]["contrast"] for k, v in views.items()}
    check(all(c >= 4.5 for c in con.values()), "the selected order chip's text has at least 4.5:1 contrast in light and dark (%s)" % ", ".join(
        "%d %s %.2f" % (k[0], k[1], c) for k, c in sorted(con.items())))
    nl_ph, nl_dt = [views[(390, sc)] for sc in ("light", "dark")], [views[(1280, sc)] for sc in ("light", "dark")]
    check(all(len(c["nlTops"]) == 2 and c["nlTops"][1] > c["nlTops"][0] + 100 and c["nlH"] <= 820 for c, _ in nl_ph)
          and all(len(c["nlTops"]) == 2 and c["nlTops"][0] == c["nlTops"][1] and min(c["nlW"]) >= 400 for c, _ in nl_dt)
          and all(v["nlOver"] == 0 for vv in views.values() for v in vv),
          "U11 in Chromium the stop and take-profit tiles stand side by side at 1280 px and stack on a 390 px phone, where the folded block is %d px "
          "high (at most 820); nothing in it reaches past its edge, folds closed or open, light and dark" % nl_ph[0][0]["nlH"])
    check(live == [(True, [False, "Trader now: bought <b>X</b> for 3 €", 0], True)] and not errs,
          "the live line shows the trader's latest line only while the live doc says a scan runs, as text; no script error (%s; %s)" % (live, errs[:2]))


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    account_checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d skipped: %s)" % (len(skips), "; ".join(skips)) if skips else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
