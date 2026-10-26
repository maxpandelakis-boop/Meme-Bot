#!/usr/bin/env python3
"""selftest_live.py: the Start tab's live panel (page_live.py, the user's wish of Oct 25: the app clean and "cool zum live zugucken").
Fake money only: the fixtures are hand-made docs, nothing is fetched; the browser checks answer the live store's two rows themselves.

  L1 the feed (page_live.events): newest first, the last 24 h only; every line names its bot and its account (a sell bot sale "Pick
     account", the fixed rule's sale "PICK ACCOUNT", "Radar account 🚀", the Learning Pick's shadow account), results in € with their sign,
     the Radar's round with its best coin and its share of the buy line, the scans; coin names escaped
  L2 what a scan did (page_live.scan_words): bought, picked a coin the Pick account already holds, picked without a buy, no coin
  L3 the lanes (page_live.section): PICK BOT, SELL BOT 🤖, RADAR 🚀, LEARNING PICK, each with its clock; the open coins as chips with
     their change since the buy; the page alone never says "late" (its rocket.json is as old as the scan); the data for the script
  L4 where it sits: on the Start tab under the accounts, before "Right now"; the old status lines and the tiles that repeated the tab
     bar are gone; the script reads the two live rows (versions first, a row only when it moved) while Start is in front, text only;
     the Pick tab's rule text sits behind "How it sells"
  L5 in a browser (Playwright; skipped without it): the live rows move the chips, a sale of the sell bot and a new Radar round slide into
     the feed once, the LIVE badge lights up, a look 20 minutes old turns the sell bot's lane amber, no script error, nothing wider than
     the phone; a running scan in the PICK BOT lane with its pick; a tap on a lane opens its bot's tab

  python3 selftest_live.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  selftest.main: checks(check, SKIPS) after the live sell checks
"""
import datetime as dt, html, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MIN, H = 60_000, 3_600_000
NOW = int(dt.datetime(2026, 10, 25, 21, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
EVIL = '<img src=x onerror=alert(1)>'


def fixture(tmp):
    """A page's data (D) with the Pick account's positions, rocket.json, the sell bot's last look and the Learning Pick's trades."""
    import memebot as M
    chart = lambda t, **k: dict({"grp": "hold", "paper": M.PAPER_RULE, "t": t - 20 * MIN, "entryAt": t}, **k)
    rows = [
        {"id": "pA", "sym": "AAA", "ticket": 50.0, "t": NOW - 80 * MIN, "tBuy": NOW - 60 * MIN, "open": True, "pnl": 10.0, "pct": 0.2, "exitT": None, "status": [],
         "p": chart(NOW - 60 * MIN, addr="AddrA", tier="strong", _id="pA", sym="AAA")},
        {"id": "pB", "sym": "BBB", "ticket": 50.0, "t": NOW - 5 * H, "tBuy": NOW - 5 * H + 20 * MIN, "open": False, "pnl": 20.74, "pct": 0.4148, "exitT": NOW - 2 * H,
         "status": [{"why": "trail"}], "p": chart(NOW - 5 * H + 20 * MIN, addr="AddrB", _id="pB")},
        {"id": "pC", "sym": EVIL, "ticket": 50.0, "t": NOW - 20 * H, "tBuy": NOW - 20 * H, "open": False, "pnl": -9.97, "pct": -0.1994, "exitT": NOW - 14 * H,
         "status": [{"why": "time"}], "p": {"grp": "hold", "paper": M.OLD_PAPER_RULE, "t": NOW - 20 * H, "addr": "AddrC", "_id": "pC"}},
        {"id": "pOld", "sym": "OLDY", "ticket": 50.0, "t": NOW - 40 * H, "tBuy": NOW - 40 * H, "open": False, "pnl": 1.0, "pct": 0.02, "exitT": NOW - 30 * H,
         "status": [{"why": "time"}], "p": chart(NOW - 40 * H, addr="AddrO", _id="pOld")},
    ]
    book = {"bal": 21.77, "closed": 3, "open": 1, "win": 6.7, "x3": 0, "x10": 0, "pts": [1.0, -8.97, 11.77], "rows": rows, "ticket": 50.0}
    os.makedirs(os.path.join(tmp, "db", "memebot"), exist_ok=True)
    top = [{"addr": "RkTopAddr1", "sym": "TOPCOIN", "score": 0.0296, "age": 51, "buy": False}, {"addr": "RkTopAddr2", "sym": "NEXT", "score": 0.005, "age": 80, "buy": False}]
    rk = {"v": 1, "t": NOW - 3 * H, "cut": 0.074, "round": {"candidates": 936, "scored": 13, "bought": 0}, "top": top,
          "book": {"open": {"RkOpen": {"addr": "RkOpen", "sym": "ROCK", "t": NOW - 4 * H, "px": 1.0, "now": 1.25}},
                   "closed": [{"addr": "RkSold", "sym": "GONE", "t": NOW - 9 * H, "out": NOW - 7 * H, "eur": -6.0, "why": "stop", "mult": 0.7}],
                   "summary": {"trades": 1, "open": 1, "eur": -6.0, "openEur": 5.0}}}
    json.dump(rk, open(os.path.join(tmp, "db", "memebot", "rocket.json"), "w"))
    json.dump({"v": 1, "t": NOW - 30_000, "pos": {"pA": {"sym": "AAA", "cpx": 1.0, "now": 1.2}}, "sold": {}}, open(os.path.join(tmp, M.LIVE_WATCH_ROW + ".json"), "w"))
    S = {"ticket": 50.0, "me": {"open": 1, "sold": 1, "closedPnl": -10.8},
         "trades": [{"pid": "l1", "sym": "LPOPEN", "t": NOW - 30 * MIN, "state": "open", "_now": 0.9},
                    {"pid": "l2", "sym": "LPSOLD", "t": NOW - 8 * H, "out": NOW - 7 * H, "state": "sold", "eur": -10.8, "why": "stop"}]}
    runs = [{"t": NOW - 80 * MIN, "scanned": 11640, "passed": 1, "picks": [{"sym": "AAA", "addr": "AddrA", "bought": 50.0, "tier": "strong"}]},
            {"t": NOW - 20 * MIN, "scanned": 11500, "passed": 1, "picks": [{"sym": "AAA", "addr": "AddrA", "bought": 0}]}]
    runs.sort(key=lambda r: -r["t"])
    opn = [{"id": "pA", "p": rows[0]["p"], "entry": 1.0, "last": 1.2, "cpx": 1.0}]
    D = {"now": NOW, "dir": tmp, "runs": runs, "open": opn, "paper": {"since": NOW - 30 * H}, "rec": {}}
    return D, book, S


class Patch:
    """page_home.pick_book and page_live.lp_summary answer from the fixture (their own tests live in selftest_fresh and selftest_lernpick)."""
    def __init__(self, book, S):
        import page_home as PH, page_live as PL
        self.PH, self.PL, self.book, self.S = PH, PL, book, S

    def __enter__(self):
        self.old = (self.PH.pick_book, self.PL.lp_summary)
        self.PH.pick_book = lambda D: self.book
        self.PL.lp_summary = lambda D: self.S
        return self

    def __exit__(self, *a):
        self.PH.pick_book, self.PL.lp_summary = self.old


def text(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h)).replace("\xa0", " ")


def l1(check, D, book, S):
    import page_live as PL, report as R
    print("== live L1: the feed")
    with Patch(book, S):
        ev = PL.events(D, R)
        lis = [PL.ev_li(R, e, NOW) for e in ev]
    keys = [e["k"] for e in ev]
    check([e["t"] for e in ev] == sorted((e["t"] for e in ev), reverse=True) and "buy:pOld" not in keys and "sell:pOld" not in keys and len(ev) <= PL.FEED_MAX,
          "L1 newest first, nothing older than 24 h (%s)" % keys)
    by = {e["k"]: (e, text(li), li) for e, li in zip(ev, lis)}
    sb, acct, rb, rs, lb, ls = (by.get(k) for k in ("sell:pB", "sell:pC", "rbuy:RkOpen", "rsell:RkSold", "lbuy:l1", "lsell:l2"))
    check(sb and sb[0]["who"] == "sell" and "SELL BOT 🤖" in sb[1] and "sold BBB · Pick account · profit lock · +41%" in sb[1] and "+20.74 €" in sb[1],
          "L1 a sale of the sell bot names the bot, the Pick account, why and the result (%s)" % (sb and sb[1]))
    check(acct and acct[0]["who"] == "acct" and "PICK ACCOUNT" in acct[1] and "after 6 h" in acct[1] and "−9.97 €" in acct[1]
          and "<img" not in acct[2] and "&lt;img src=x" in acct[2], "L1 a sale of the fixed rule says PICK ACCOUNT; a coin name is escaped (%s)" % (acct and acct[1]))
    check(by.get("buy:pA") and "PICK BOT" in by["buy:pA"][1] and "bought AAA for the Pick account · strong pick" in by["buy:pA"][1] and "50 €" in by["buy:pA"][1],
          "L1 a Pick buy: PICK BOT, the coin, the Pick account, 50 €")
    check(rb and rs and "bought ROCK for the Radar account 🚀" in rb[1] and "20 €" in rb[1] and "sold GONE from the Radar account 🚀 · stop −30% · −30%" in rs[1] and "−6.00 €" in rs[1],
          "L1 the Radar account's buy and sale say Radar account 🚀 (%s | %s)" % (rb and rb[1], rs and rs[1]))
    rr = next((x for k, x in by.items() if k.startswith("rround:")), None)
    check(rr and rr[0]["k"] == "rround:" + PL.rk_sig(json.load(open(os.path.join(D["dir"], "db", "memebot", "rocket.json")))["top"])
          and "round · 936 coins watched · best TOPCOIN at 40% of the buy line · no buy" in rr[1] and rr[0]["dim"],
          "L1 the Radar's round: coins watched, its best coin and its share of the buy line (%s)" % (rr and rr[1]))
    check(lb and ls and "LEARNING PICK" in lb[1] and "bought LPOPEN for its shadow account" in lb[1] and "sold LPSOLD · stop · −22%" in ls[1] and "−10.80 €" in ls[1],
          "L1 the Learning Pick's buy and sale (%s | %s)" % (lb and lb[1], ls and ls[1]))
    sc = by.get("scan:%d" % (NOW - 20 * MIN))
    check(sc and sc[0]["dim"] and "SCAN" in sc[1] and "11,500 coins looked at · 1 passed every filter · picked AAA again, already held" in sc[1],
          "L1 a scan line, dimmed (%s)" % (sc and sc[1]))


def l2(check, book):
    import page_live as PL
    print("== live L2: what a scan did")
    rows = book["rows"]
    w = lambda picks, t=NOW - 20 * MIN: text(PL.scan_words({"t": t, "picks": picks}, rows))
    check(w([{"sym": "AAA", "addr": "AddrA", "bought": 50.0}]) == "bought AAA for the Pick account", "L2 bought")
    check(w([{"sym": "AAA", "addr": "AddrA", "bought": 0}]) == "picked AAA again, already held", "L2 a pick the account holds is not bought twice")
    check(w([{"sym": "BBB", "addr": "AddrB", "bought": 0}], NOW - H) == "picked BBB, not bought" and w([{"sym": "BBB", "addr": "AddrB"}], NOW - 3 * H) == "picked BBB again, already held",
          "L2 held means held at that scan (BBB sold 2 h ago)")
    check(w([]) == "no coin was clean enough, nothing bought", "L2 no pick")


def l3(check, D, book, S):
    import page_live as PL, report as R
    print("== live L3: the lanes")
    with Patch(book, S):
        h = PL.section(D, R)
    lanes = re.findall(r'data-lv-lane="(\w+)"', h)
    check(lanes == ["pick", "sell", "radar", "lp"] and all(x in h for x in (">PICK BOT<", ">SELL BOT 🤖<", ">RADAR 🚀<", ">LEARNING PICK<")),
          "L3 four lanes in the Start cards' words (%s)" % lanes)
    check('data-lv-lane="sell" for="tab-pick" data-go="pick" data-open="sell-bot"' in h and 'data-lv-lane="radar" for="tab-young" data-go="young">' in h
          and 'data-lv-lane="lp" for="tab-pick" data-go="pick" data-open="learning-pick"' in h, "L3 a tap on a lane opens its bot: the sell bot's card, the Radar tab, the Learning Pick's fold")
    cds = dict(zip(lanes, re.findall(r"<b data-lv-cd>([^<]*)</b>", h)))
    check(re.match(r"^in \d+:\d\d$", cds.get("pick", "")) and cds.get("sell") == "in 0:30" and cds.get("radar") == "every 15 min" and re.match(r"^in \d+ h \d\d min$", cds.get("lp", "")),
          "L3 the clocks: next scan, next look, the Radar's rhythm (its round is 3 h old on the page), next training (%s)" % cds)
    check("lv-late" not in h.split("<style>")[0] and "late" not in cds.values(), "L3 the page alone never says late")
    chips = re.findall(r'data-lv-chip="([^"]+)"[^>]*><b>([^<]*)</b><i>([^<]*)</i>', h)
    check(("p:pA", "AAA", "+20%") in chips and ("r:RkOpen", "ROCK", "+25%") in chips and ("l:l1", "LPOPEN", "−10%") in chips,
          "L3 the open coins as chips with their change since the buy (%s)" % chips)
    data = json.loads(html.unescape(re.search(r'data-lv="([^"]*)"', h).group(1)))
    feed = re.findall(r'<li class="lv-ev[^"]*" data-k="([^"]*)"', h)
    check(data["keys"] == [html.unescape(k) for k in feed] and data["pick"]["pA"]["px"] == 1.0 and data["rkSig"] == "RkTopA:2960|RkTopA:500" and data["row"] == "pickwatch",
          "L3 the script's data: the feed's keys, the Pick positions' buy prices, the round's signature")
    check('data-lv-more hidden>Show all (' in h if len(feed) <= PL.FEED_SHOWN else 'data-lv-more>Show all (%d)' % len(feed) in h, "L3 'Show all' only with more than %d lines" % PL.FEED_SHOWN)
    return h


def l4(check, D, book, S):
    import page_home as PH, page_live as PL, report as R
    print("== live L4: on the Start tab")
    with Patch(book, S):
        h = PH.section(D, R)
    i, j, k = h.find('class="hm-hero"'), h.find('id="live"'), h.find("Right now")
    check(0 < i < j < k, "L4 the panel sits under the accounts, before Right now")
    check("hm-nav" not in h and "hm-status" not in h and "Pick scan last" not in h, "L4 the old status lines and the tiles that repeated the tab bar are gone")
    js = PL.LV_JS
    check("select=id,ver&id=in.('+D.row+',rocket)" in js and "select=id,ver,doc&id=in.('+due.join(',')+')" in js and "innerHTML" not in js
          and "getElementById('tab-home')" in js and "apikey:key" in js, "L4 the script: versions first, a row only when it moved, while Start is in front, text only")
    home = open(os.path.join(HERE, "page_home.py"), encoding="utf-8").read()
    check('<details class="pk-how"><summary>How it sells</summary>' in home and "live_panel(D, R)" in home, "L4 the Pick tab's rule text behind 'How it sells'")


def page_for(h):
    """A page around the panel: the Start radio checked, the live store's attributes, the theme's colours."""
    import report as R
    return ('<!doctype html><html lang="en" data-sb-url="https://demo.supabase.co" data-sb-key="sb_publishable_test"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><style>%s</style></head><body><div class="wrap">'
            '<input type="radio" name="tab" id="tab-home" checked><input type="radio" name="tab" id="tab-pick">%s</div></body></html>') % (R.CSS + R.THEME_CSS, h)


def l5(check, skips, h):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the live panel's browser checks (no Playwright)")
        print("  SKIP the live panel's browser checks: Playwright is not installed")
        return
    import memebot as M
    print("== live L5: in a browser")
    h = re.sub(r'data-lv="([^"]*)"', lambda m: 'data-lv="%s"' % html.escape(json.dumps(dict(json.loads(html.unescape(m.group(1))), every=400)), True), h, count=1)
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    errs, asked = [], {"ver": 0, "doc": 0}
    rows = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        ctx = br.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")

        def handler(route):
            u = route.request.url
            if u.startswith("https://page.test/"):
                return route.fulfill(status=200, body=page_for(h), headers={"Content-Type": "text/html; charset=utf-8"})
            if u.startswith("https://demo.supabase.co/rest/v1/live?"):
                q = __import__("urllib.parse").parse.unquote(u)
                ids = re.search(r"id=in\.\(([^)]*)\)", q).group(1).split(",")
                full = "select=id,ver,doc" in q
                asked["doc" if full else "ver"] += 1
                out = [dict({"id": i, "ver": rows[i][0]}, **({"doc": rows[i][1]} if full else {})) for i in ids if i in rows]
                return route.fulfill(status=200, body=json.dumps(out), headers={"Content-Type": "application/json"})
            route.abort()
        ctx.route("**/*", handler)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        now = int(__import__("time").time() * 1000)
        rows[M.LIVE_WATCH_ROW] = (1, {"v": 1, "t": now - 10_000, "pos": {"pA": {"sym": "AAA", "cpx": 1.0, "now": 1.5}}, "sold": {}})
        rows["rocket"] = (1, {"v": 1, "t": now - 60_000, "cut": 0.074, "open": [{"addr": "RkOpen", "sym": "ROCK", "t": NOW - 4 * H, "now": 1.1}], "closed": [],
                              "top": [{"addr": "RkTopAddr1", "sym": "TOPCOIN", "score": 0.0296}, {"addr": "RkTopAddr2", "sym": "NEXT", "score": 0.005}]})
        pg.goto("https://page.test/")
        pg.wait_for_timeout(1500)
        st = """(function(){var b=document.querySelector('[data-lv]');function lane(k){var l=b.querySelector('[data-lv-lane="'+k+'"]');
          return {cd:l.querySelector('[data-lv-cd]').textContent,late:l.classList.contains('lv-late'),say:l.querySelector('[data-lv-say]').textContent,
          chips:[].map.call(l.querySelectorAll('[data-lv-chip]'),function(c){return c.textContent;})};}
          return {badge:b.querySelector('[data-lv-badge]').classList.contains('on'),clock:b.querySelector('[data-lv-clock]').textContent,
          sell:lane('sell'),radar:lane('radar'),keys:[].map.call(b.querySelectorAll('li.lv-ev'),function(l){return l.getAttribute('data-k');}),
          first:(b.querySelector('li.lv-ev')||{}).textContent,news:b.querySelectorAll('li.lv-new').length,sw:document.documentElement.scrollWidth};})()"""
        s1 = pg.evaluate(st)
        check(s1["badge"] and re.match(r"^\d\d:\d\d:\d\d$", s1["clock"]) and s1["sell"]["chips"] == ["AAA+50%"] and s1["radar"]["chips"] == ["ROCK+10%"]
              and re.match(r"^in 0:\d\d$", s1["sell"]["cd"]) and not s1["news"], "L5 the live rows: LIVE on, the clock, the chips move, the next look counts down, no event yet (%s)" % s1)
        n_doc = asked["doc"]
        pg.wait_for_timeout(1200)
        check(asked["ver"] >= 3 and asked["doc"] == n_doc, "L5 unchanged versions: no row read again (%s)" % asked)
        rows[M.LIVE_WATCH_ROW] = (2, {"v": 1, "t": now, "pos": {}, "sold": {"pA": {"at": now - 5000, "why": "trail", "mult": 1.46, "sym": "AAA", "pnl": 23.0, "eur": 73.0}}})
        rows["rocket"] = (2, dict(rows["rocket"][1], t=now - 10_000, top=[{"addr": "RkNewAddr", "sym": EVIL, "score": 0.037}]))
        pg.wait_for_timeout(1500)
        s2 = pg.evaluate(st)
        sig = "rround:RkNewA:3700"
        check(s2["keys"][:2] == ["sell:pA", sig] and "SELL BOT 🤖" in s2["first"] and "sold AAA · profit lock · +46%" in s2["first"] and "+23.00\xa0€" in s2["first"]
              and s2["news"] == 2 and s2["sell"]["chips"] == [] and EVIL[:14] in s2["radar"]["say"],
              "L5 a sale of the sell bot and a new Radar round slide in at the top, the name as text (%s)" % {k: s2[k] for k in ("keys", "first", "news", "sell", "radar")})
        pg.wait_for_timeout(1200)
        check(pg.evaluate(st)["keys"].count("sell:pA") == 1, "L5 an event comes once")
        rows[M.LIVE_WATCH_ROW] = (3, {"v": 1, "t": now - 20 * MIN, "pos": {"pA": {"sym": "AAA", "cpx": 1.0, "now": 1.1}}, "sold": {}})
        pg.wait_for_timeout(1500)
        s3 = pg.evaluate(st)
        check(s3["sell"]["late"] and s3["sell"]["cd"] == "late" and s3["sw"] <= 390, "L5 a look 20 minutes old with the store answering: amber, 'late'; nothing wider than 390 px (%s)" % s3["sell"])
        rows[M.LIVE_WATCH_ROW] = (4, {"v": 1, "t": now, "pos": {"pA": {"sym": "AAA", "cpx": 85.0, "now": 1.2}}, "sold": {}})
        pg.wait_for_timeout(1500)
        s4 = pg.evaluate(st)
        check(s4["sell"]["chips"] == ["AAA…"], "L5 candles of the pool's other coin (cpx 85x the buy price, memebot.UNIT_X): the chip shows '…', no made-up change (%s)" % s4["sell"]["chips"])
        scan = pg.evaluate("""(function(){function ev(d){window.dispatchEvent(new CustomEvent('memebot-live',{detail:d}));}
          var l=document.querySelector('[data-lv-lane="pick"]');
          ev({state:'live',status:{t:Date.now()-5*60000,agents:[{id:'scouts',status:'done'},{id:'deep',status:'running',lines:['a','412 of 900 coins']}],pick:{sym:'NEWPICK'}}});
          var a={run:l.classList.contains('lv-run'),cd:l.querySelector('[data-lv-cd]').textContent,say:l.querySelector('[data-lv-say]').textContent};
          ev({state:'done',status:{t:Date.now(),agents:[]}});
          a.after=l.classList.contains('lv-run');a.cdk=l.querySelector('[data-lv-cdk]').textContent;return a;})()""")
        check(scan["run"] and scan["cd"] == "5 min" and "Scanning now · Deep search: 412 of 900 coins. This scan's pick: NEWPICK." in scan["say"] and not scan["after"] and scan["cdk"] == "next scan",
              "L5 a running scan (the status row's event): PICK BOT shows the helper at work and the scan's pick, then the next scan again (%s)" % scan)
        pg.locator('[data-lv-lane="sell"]').click()
        check(pg.evaluate("document.getElementById('tab-pick').checked"), "L5 a tap on the sell bot's lane opens the Pick tab (its card: data-open sell-bot)")
        ctx.close()
        br.close()
    check(not errs, "L5 no script errors (%s)" % errs[:3])


def checks(check, skips=None):
    import memebot as M
    skips = skips if skips is not None else []
    tmp = tempfile.mkdtemp(prefix="mb-live-")
    # the real switch to the live chart (selftest.py's main pins MEMEBOT_LIVE_SELL_AT a month ahead for its fixed-rule checks)
    old = os.environ.get("MEMEBOT_LIVE_SELL_AT")
    os.environ["MEMEBOT_LIVE_SELL_AT"] = str(M.LIVE_SELL_AT)
    try:
        D, book, S = fixture(tmp)
        l1(check, D, book, S)
        l2(check, book)
        h = l3(check, D, book, S)
        l4(check, D, book, S)
        l5(check, skips, h)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is None:
            os.environ.pop("MEMEBOT_LIVE_SELL_AT", None)
        else:
            os.environ["MEMEBOT_LIVE_SELL_AT"] = old


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d check group%s skipped: %s)" % (len(skips), "" if len(skips) == 1 else "s", "; ".join(skips)) if skips else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
