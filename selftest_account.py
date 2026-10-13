"""Selftest checks of the paper account block (page_account.py; fake money only): U1, U2 and U7 of the spec, plus the hooks in
report.py, robustness against broken memepeak docs, escaping and, when Playwright and a Chromium are installed, the layout at 390
and 1280 px in light and dark, the four orders and the live line.

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
XSS = "<img src=x onerror=alert(1)>"


def _dump(d, coll, key, doc):
    os.makedirs(os.path.join(d, "db", coll), exist_ok=True)
    with open(os.path.join(d, "db", coll, key + ".json"), "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))


def fixture(d, peaks=True):
    """A recommend-mode db with paper positions since the restart (open and sold by every rule), one position before the restart,
    the curve, the marks and (peaks=True) one memepeak doc per closed window in every state, plus broken docs."""
    now = T0 + 9 * H
    pos = {
        "y-stop": dict(grp="young", sym="STOPPY", name="Stop Coin", t=T0 + 10 * MIN, entryAt=T0 + 11 * MIN, px=1.0, ticket=3.0),
        "y-tp": dict(grp="young", sym="MOON", name="Moon Coin", t=T0 + 20 * MIN, entryAt=T0 + 20 * MIN, px=2.0, ticket=3.0),
        "y-time": dict(grp="young", sym="SLOW", name="Slow Coin", t=T0 + 30 * MIN, entryAt=T0 + 30 * MIN, px=1.0, ticket=3.0),
        "y-rug": dict(grp="young", sym="DOGGO", name="Doggo", t=T0 + 40 * MIN, entryAt=T0 + 40 * MIN, px=1.0, ticket=3.0),
        "h-time": dict(grp="hold", sym="TOPPY", name="Top Pick", t=T0 + 50 * MIN, entryAt=T0 + 52 * MIN, px=1.0, ticket=50.0),
        "y-xss": dict(grp="young", sym=XSS, name="<b>bold</b>", t=T0 + 60 * MIN, entryAt=T0 + 60 * MIN, px=1.0, ticket=3.0),
        "y-nan": dict(grp="young", sym="NANPK", name="Nan Peak", t=T0 + 70 * MIN, entryAt=T0 + 70 * MIN, px=1.0, ticket=3.0),
        "y-open": dict(grp="young", sym="FRESH", name="Fresh Coin", t=T0 + 8 * H, entryAt=T0 + 8 * H, px=1.0, ticket=3.0),
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
             "y-rug": (0.0, "rug", T0 + 3 * H, False), "h-time": (1.4, "time", T0 + 7 * H, False), "y-xss": (0.6, "stop", T0 + 90 * MIN, True),
             "y-nan": (0.7, "stop", T0 + 100 * MIN, True), "old-1": (1.2, "time", T0 - 2 * H, False)}
    for pid, (px_, why, t, at) in sells.items():
        p = pos[pid]
        e = {"pos": pid, "t": t, "px": px_, "frac": 1.0, "why": why, "eur": round(M.pos_value(p, 1.0, px_ / p["px"]), 2), "grp": p["grp"]}
        if at:
            e["at"] = t - 3 * MIN                   # the candle that sold it, before the run that booked it
        _dump(d, "memeexit", pid + "-1", e)
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    marks = {"t": now, "px": {"y-open": 1.5}, "liq": {}, "miss": {}, "chk": {}, "cpx": {}}
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
        _dump(d, "memepeak", "y-stop", P("y-stop", state="ok", src="m1", res=1, x=1.8, at=pos["y-stop"]["entryAt"] + 47 * MIN, rawX=1.9, x6=0.4,
                                       eur=val("y-stop", 1.8), eur6=val("y-stop", 0.4)))
        _dump(d, "memepeak", "y-tp", P("y-tp", state="ok", src="m1", res=1, x=12.5, at=pos["y-tp"]["entryAt"] + 95 * MIN, rawX=12.5, x6=3.0,
                                     eur=val("y-tp", 12.5), eur6=val("y-tp", 3.0)))
        _dump(d, "memepeak", "y-time", P("y-time", state="est", src="est", res=None, tries=3, x=1.2, at=None, rawX=None, x6=1.3,
                                       eur=val("y-time", 1.2), eur6=val("y-time", 1.3)))
        _dump(d, "memepeak", "y-rug", P("y-rug", state="ok", src="m1", res=1, x=1.0, at=pos["y-rug"]["entryAt"] + MIN, rawX=59257.0, x6=0.0,
                                      eur=val("y-rug", 1.0), eur6=0.0, dead={"at": T0 + 2 * H, "why": "rug"}, cut=["rug exit", "dust 59257.00x"]))
        _dump(d, "memepeak", "h-time", P("h-time", state="ok", src="m15", res=15, x=2.0, at=pos["h-time"]["entryAt"] + 3 * H, rawX=2.0, x6=1.5,
                                       eur=val("h-time", 2.0), eur6=val("h-time", 1.5), cut=["unconfirmed <script>4.00x</script>"]))
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
    check(_tree(d) == before and "could not be rendered" not in page,
          "the account block reads only: every db file is byte-identical after the page build, and every part rendered")
    D = R.collect(d, now)
    A = D["paper"]["acct2"]
    P = M.positions(d)
    marks = json.load(open(os.path.join(d, "db", "memebot", "marks.json")))
    acct = M.paper_account(P, T0, marks["px"])

    # U1: the survival header is paper_account's numbers
    hdr = PA.header(D, A)
    rate = acct["pnl"] / acct["invested"]
    closed = [(pid, p) for pid, p in P.items() if M.in_account(p, T0) and p["_left"] <= 1e-9]
    best_pid, best_p = max(closed, key=lambda kv: sum(e["eur"] for e in kv[1]["_exits"]) - kv[1]["ticket"])
    best_pnl = round(sum(e["eur"] for e in best_p["_exits"]) - best_p["ticket"], 2)
    want = [PA.eur(acct["pnl"], True), PA.pct1(rate), "%.1f%%" % (100.0 * acct["won"] / acct["nClosed"]), "%d<small> closed</small>" % acct["nClosed"],
            "%d open · " % acct["nOpen"], html.escape(PA.eur(best_pnl, True)), html.escape(best_p["sym"]), html.escape(PA.eur(acct["open"]))]
    check({k: v for k, v in A["stop"].items() if k != "winRate"} == acct and all(w in hdr for w in want) and "P/L since 10.10." in hdr
          and 'class="pa-line bad"' in hdr and "pa-line-empty" not in hdr,
          "U1 the survival header is paper_account's numbers: %s, %s, win rate %s, %d closed, %d open, best %s %s, open value %s, and the balance line" % (
              PA.eur(acct["pnl"], True), PA.pct1(rate), want[2], acct["nClosed"], acct["nOpen"], PA.eur(best_pnl, True), best_p["sym"], PA.eur(acct["open"])))
    ev = []
    for pid, p in P.items():
        if not M.in_account(p, T0):
            continue
        ev.append((p.get("entryAt") or p["t"], 1, "buy", p["sym"], None))
        for e in p["_exits"]:
            ev.append((e.get("at") or e["t"], 0, "sell", p["sym"], round(e["eur"] - p["ticket"] * e["frac"], 2)))
    ev.sort(key=lambda x: (-x[0], x[1]))
    fd = PA.feed(D, A)
    rows = re.findall(r'<li class="pa-ev (b|s)[^"]*"><span class="tm">([^<]*)</span><i></i><span class="tx"><b class="act">(?:BOUGHT|SOLD)</b> <b>(.*?)</b>.*?<span class="am">([^<]*)</span>', fd)
    got = [("buy" if k == "b" else "sell", html.unescape(s)) for k, _, s, _ in rows]
    signs = [am[0] for k, _, _, am in rows if k == "s"]
    want_signs = [("+" if v > 0 else ("−" if v < 0 else "0")) for _, _, k, _, v in ev if k == "sell"]
    check(got == [(k, s) for _, _, k, s, _ in ev] and signs == want_signs and len(rows) == len(A["feed"]) == A["feedN"] == 9 + 7
          and [R.local(t).strftime("%H:%M") for t, *_ in ev] == [tm for _, tm, _, _ in rows] and "last scan " + R.local(now).strftime("%H:%M") in fd,
          "U1 the feed is every buy (at entryAt) and every sale (at the candle's time, else the run's) since the restart, newest first, with its sign (%d rows)" % len(rows))
    big_feed = {"since": T0, "feedN": 330, "feed": [{"t": T0 + i * MIN, "k": "buy", "id": "x%d" % i, "sym": "S%d" % i, "grp": "young", "ticket": 3.0} for i in range(300, 0, -1)]}
    fd_big = PA.feed(dict(D, state={"lastRun": now}), big_feed)
    check(fd_big.split('<details', 1)[0].count('<li class="pa-ev') == PA.FEED_SHOWN == 20 and fd_big.count('<li class="pa-ev') == PA.FEED_MAX == 300
          and "All since 10.10. (330, newest 300 here)" in fd_big,
          "U1 the feed shows the newest 20 and folds the rest, at most 300 (330 events: 20 + 280, the fold says so)")
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
    best_want = [pos[pid]["sym"] for pid in ("y-tp", "h-time", "y-stop", "y-time", "y-rug")]
    check(_syms(_pane(page, "top")) == top_want and _syms(_pane(page, "worst")) == worst_want and _syms(_pane(page, "new")) == new_want
          and _syms(_pane(page, "best")) == best_want and 'id="pa-s-new" checked' in page,
          "U1 the four orders: top %% %s, worst %% from %s, newest first, best in 6 h by its multiple (the position without a price has no %%)" % (
              top_want[:3], worst_want[0]))

    # U2: three strips, the hindsight chip, priced N of M, the filtered chip, the closed-row columns
    st = PA.strips(D, A)
    booked = {pid: json.load(open(os.path.join(d, "db", "memepeak", pid + ".json"))) for pid in ("y-stop", "y-tp", "y-time", "y-rug", "h-time")}
    b_pnl = round(sum(doc["eur"] - pos[pid]["ticket"] for pid, doc in booked.items()), 2)
    s6_pnl = round(sum(doc["eur6"] - pos[pid]["ticket"] for pid, doc in booked.items()), 2)
    n_acct = sum(1 for p in P.values() if M.in_account(p, T0))
    same_b = round(sum(sum(e["eur"] for e in P[pid]["_exits"]) - P[pid]["ticket"] for pid in booked), 2)
    priced = "priced 5 of %d · %d waiting · 1 estimated · 1 15-min · 1 not booked (price unit)" % (n_acct, n_acct - 5 - 1)
    check(all('data-pa="%s"' % k in st for k in ("stop", "peak", "six")) and st.count("hindsight, not a trading rule") == 2
          and html.escape(priced) in st and html.escape(PA.eur(b_pnl, True)) in st and html.escape(PA.eur(s6_pnl, True)) in st
          and "same 5 trades under the stop-loss rule: <b class=\"%s\">%s</b>" % (PA.tone(same_b), html.escape(PA.eur(same_b, True))) in st
          and A["best"]["n"] == 5 and A["six"]["n"] == 5 and A["counts"]["open"] == 2,
          "U2 three strips: the rule %s, best within 6 h %s and held 6 h %s (both hindsight), '%s', same trades under the rule %s" % (
              PA.eur(acct["pnl"], True), PA.eur(b_pnl, True), PA.eur(s6_pnl, True), priced, PA.eur(same_b, True)))
    newp = _pane(page, "new")
    check('<span class="chip warn" data-pa="filtered">59,257x ignored: pool dead</span>' in newp and "filtered: not confirmed by the next close" in newp
          and "<th>best in 6 h (hindsight)</th><th>at 6 h (hindsight)</th>" in newp and "at 47 min · +" in newp and " · 15-min candles" in newp and " · estimate" in newp
          and newp.count("window open") == 4 and "not booked" in newp and "price unit mismatch" in newp and "<script>4.00x" not in page,
          "U2 the closed rows carry best in 6 h (multiple, when, P/L) and at 6 h, the filtered chip with its first reason (59,257x ignored: pool dead), estimate, 15-min, unit, window open")
    check("Closed trades (7) · 2 open" in page and "Before the restart (1 trade)" in page and "bought before the paper account restarted on " in page
          and "profit/loss since the restart on " in page and 'class="acct"' not in page and 'data-pa="header"' in page and page.count("<style>%s</style>" % PA.CSS) == 1,
          "the hooks: the account block replaces the old strip, keeps 'Closed trades (N)', the trades before the restart and the curve fold")
    cv = PA.curve(D, A)
    check('class="line s2 dash"' in cv and "best within 6 h (hindsight), by window end" in cv and "dashed: best within 6 h (hindsight), 5 windows" in cv
          and A["peakPts"][-1][1] == b_pnl and [t for t, _ in A["peakPts"]] == sorted(t for t, _ in A["peakPts"]),
          "the curve fold carries the dashed hindsight line, cumulative by window end (ends at %s)" % PA.eur(b_pnl, True))

    # U7: honest words, every hindsight number labelled
    new_ui = "".join(f(D, A) for f in (PA.header, PA.strips, PA.feed, PA.trades, PA.curve))
    words = _text(new_ui)
    hits = re.findall(r"(?i)\b(safe|safely|guaranteed?|buy|buys|buying)\b", words)
    h_cells = re.findall(r'<td class="h h[12]">', new_ui)
    tables = re.findall(r"<table>.*?</table>", PA.trades(D, A), re.S)
    check(not hits and "\u2014" not in words and h_cells and all("(hindsight)</th>" in t for t in tables if 'class="h h1"' in t)
          and 'content:"best in 6 h (hindsight)"' in PA.CSS and 'content:"at 6 h (hindsight)"' in PA.CSS
          and all("hindsight" in c for c in re.findall(r'<div class="pa-cat (?:peak|six)".*?</details></div>', st, re.S)),
          "U7 no 'safe', 'guaranteed' or 'buy' and no em dash in the new text; every hindsight number sits under a hindsight label (%d cells)" % len(h_cells))

    # robustness: no memepeak docs, a broken load, escaping
    d2 = tempfile.mkdtemp(prefix="memebot-acct0-")
    try:
        fixture(d2, peaks=False)
        D2 = R.collect(d2, now)
        A2 = D2["paper"]["acct2"]
        st2 = PA.strips(D2, A2)
        check(A2["best"]["n"] == 0 and html.escape("priced 0 of %d · %d waiting · 0 estimated · 0 15-min" % (n_acct, n_acct)) in st2
              and '<div class="v muted">–</div>' in st2 and A2["stop"] == A["stop"],
              "without memepeak docs: priced 0 of %d, the hindsight strips show a dash, the stop-loss account is unchanged" % n_acct)
    finally:
        shutil.rmtree(d2, ignore_errors=True)
    bad = PA.load(d, now, pos={"x": "not a position"}, px={}, since=T0)
    sec_bad = PA.section(dict(D, paper=dict(D["paper"], acct2=bad)))
    check(bad.get("err") and "could not be read this time" in sec_bad and "could not be rendered" not in sec_bad,
          "a load that fails leaves a note and empty categories; the page still renders (%s)" % (bad.get("err") or "")[:60])
    check(XSS not in page and html.escape(XSS) in page and "<b>bold</b>" not in page and A["counts"]["unit"] == 1
          and not any(r["pk"] and r["pk"]["state"] in PA.BOOKED for r in A["rows"] if r["id"] == "y-nan"),
          "coin names and filter reasons are escaped; a booked doc without a finite multiple is not booked; docs of unknown positions and broken files are skipped")

    _browser(check, page, skips)


def _browser(check, page_html, skips):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the browser checks of the paper account (no Playwright)")
        print("  SKIP the browser checks of the paper account: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    url = "https://some-owner.github.io/Meme-Bot/"
    wide, errs, live = [], [], []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            for w, h in ((390, 844), (1280, 900)):
                for scheme in ("light", "dark"):
                    ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                    pg = ctx.new_page()
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.route("**/*", lambda r: r.fulfill(status=200, body=page_html, headers={"Content-Type": "text/html; charset=utf-8"})
                             if r.request.url.startswith(url) else r.abort())
                    pg.goto(url)
                    pg.evaluate("document.querySelectorAll('section[data-app=\"account\"] details').forEach(function(x){x.open=true;})")
                    for k in ("new", "top", "worst", "best"):
                        pg.locator('label[for="pa-s-%s"]' % k).click()
                        vis = pg.evaluate("Array.from(document.querySelectorAll('[data-pa-sort]')).filter(function(e){return e.offsetParent!==null;}).map(function(e){return e.getAttribute('data-pa-sort');})")
                        sw = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                        wide.append((w, scheme, k, vis == [k], sw[0] <= sw[1]))
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
    check(wide and all(v and s for *_, v, s in wide),
          "in Chromium at 390 and 1280 px, light and dark, with every fold open: each of the four orders shows alone and nothing scrolls sideways (%d views)" % len(wide))
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
