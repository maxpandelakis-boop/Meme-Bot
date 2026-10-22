"""Selftest checks of the four tabs after the three traders (fake money only): UI1 to UI10 of the spec's 4.9 for page_traders.py, the
Pick heading and paper line (report.py), the Radar tab's paper positions and its card's paper line (page_radar.py), the Office cards
(page_office.py) and the installed app's bar and notifications card (app.py).

The pages are built from selftest_traders.fixture (a small db around the switch: pick and new-launch positions, radar rule-2 buys, minute
paths) with a recommend.json, a radar.json and an office.json of their own (page_db). UI9's layout also runs on a real-data copy when
MEMEBOT_REALDATA names one (a folder with db/ and radar_live.json; the switch is set an hour before its newest run), with the tab heights
of the spec's 4.10; without it that part says it was skipped.

    python3 selftest_traders_ui.py       runs the checks alone (ends ALL PASS or "N checks failed")
    selftest.main: checks(check, SKIPS)
"""
import html, json, os, re, shutil, subprocess, sys, tempfile, time
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import radar_paper as RP
import traders as T
import report as R
import page_account as PA
import page_radar as PR
import page_traders as PT
import selftest_traders as ST

PY = sys.executable
MIN, H, DAY = 60_000, 3_600_000, 86_400_000
SWITCH = 1_792_108_800_000                   # the spec's switch (16 Oct 00:00 UTC); the fixture runs 30 h after it
REPO = "https://github.com/some-owner/Meme-Bot"
BANNED = re.compile(r"(?i)\b(buy|buys|buying|safe|safely|guaranteed?|clean|should)\b")
MONEY = re.compile(r"^[+−]?\d{1,3}(,\d{3})*\.\d{2}\u00a0€$")
TICKET = re.compile(r"^\d+\u00a0€$")
SPOTTER = re.compile(r'<label class="ocard[^"]*" for="od-[a-z]+" data-agent="spotter"')     # the Launch spotter's card (its desk on the floor plan stays)
LIMITS = {"home": 2400, "pick": 2000, "young": 1600, "account": 2400, "office": 2600}     # 4.10: the app at 390 px, folds closed (the radar without a coin); Oct 22: Start, the brain on top of the office
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def addr(i, tail="pump"):
    return ("".join(B58[(i * 7 + k * 3) % 58] for k in range(40)) + tail)[:44]


def radar_doc(t, coins=True):
    """A radar.json as the radar job writes it: two coins without traps (the first bought on paper, pb 1, and skipped by the learning trader:
    t3; the second not bought, pb 0), one coin with a trap, the record with record.known."""
    good = lambda i, sym, pb, t3: {"addr": addr(i), "sym": sym, "name": sym.title(), "v": "good", "pts": 0, "age": 4.0, "liq": 21_000.0, "mc": 64_000.0, "m5": 8.0,
                                   "n": 9, "line": [["ok", "curve 4 min before pool"], ["ok", "no rugger wallets"]], "hard": [], "soft": [], "unknown": [], "info": [],
                                   "plus": [], "pool": t - 4 * MIN, "first": t - 3 * MIN, "push": t - 2 * MIN, "pb": pb, "t3": t3}
    cs = [good(1, "GRNA", 1, ["no socials and no X link"]), good(2, "GRNB", 0, [])] if coins else []
    return {"v": 1, "kind": "radar", "t": t, "next": t + 2 * MIN, "state": "running", "run": {"id": "1", "start": t - 30 * MIN, "cycle": 9, "mode": "loop"},
            "counts": {"seen": 6, "good": len(cs), "pushed": len(cs), "seenAgeMed": 3.0}, "wm": {"t": t - 10 * MIN, "nCoins": 4000},
            "coins": cs, "others": [{"addr": addr(3), "sym": "TRAPX", "v": "trap", "age": 2.0, "line": [["bad", "holders from rugged coins"]], "hard": ["rugger_wallets"]}],
            "recent": [], "record": {"calls": 40, "n60": 33, "rug": 0.15, "win": 0.18, "ci": {"rug": [0.07, 0.3], "win": [0.09, 0.35]},
                                     "known": {"n": 33, "rug": 5, "win": 6}}, "hosts": {}, "notes": [], "lines": []}


def page_db(d, now, switch, pick=None, radar_t=None, spotter=True):
    """selftest_traders.fixture plus what the page needs around it: recommend.json (the open pick bought on paper by this scan, unless pick
    names other fields), radar_live.json (radar_doc at radar_t), office.json (the scan's agents, the Launch spotter among them)."""
    with ST.switch_env(switch):
        fx = ST.fixture(d, now, switch)
    pos = M.positions(d)
    pid = next(k for k, g in sorted(fx["pos"].items()) if g == "hold" and pos[k].get("_left", 0) > 1e-9)
    p = pos[pid]
    c = {"sym": p["sym"], "name": p["name"], "addr": p["addr"], "pair": p["pair"], "px": 1e-5, "mc": 300_000.0, "liq": 40_000.0, "vol": 90_000.0, "score": 61.0,
         "rank": 1, "upP": 0.2, "zeroP": 0.09, "tier": "strong", "f": {"ageH": 12.0, "c6": 7.0}, "risk": {}, "bought": M.TOP_TICKET, "why": "the best score of the scan",
         "ok": True, "safety": "RugCheck: no danger flags"}
    c.update(pick or {})
    peers = [dict(c, sym="RU%d" % i, addr=addr(40 + i)) for i in range(2)]
    ST._w(os.path.join(d, "db", "memebot", "recommend.json"), {"t": now - 20 * MIN, "rule": M.RULE, "picks": [c], "runnersUp": peers, "passed": 3, "scanned": 900,
                                                               "young": [], "youngOf": 0})
    ST._w(os.path.join(d, "db", "memebot", "state.json"), dict(M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}), lastRun=now - 20 * MIN))
    ags, s = [], now - 30 * MIN
    for i, a in enumerate(("dispatch", "scouts", "market", "safety", "trader", "reporter") + (("spotter",) if spotter else ())):
        ags.append({"id": a, "start": s, "end": s + 40_000, "status": "done", "bg": a == "spotter", "lines": ["%s line" % a], "out": "%s result" % a})
        s += 40_000
    ST._w(os.path.join(d, "db", "memebot", "office.json"), {"v": 1, "t": now - 30 * MIN, "end": s, "mode": "full", "agents": ags})
    ST._w(os.path.join(d, "radar_live.json"), radar_doc(radar_t if radar_t is not None else now - MIN))
    return fx


def build(d, now, switch, repo=None):
    """report.py's page of d at now with the switch set (in this process), and its text."""
    old = os.environ.pop("GITHUB_REPOSITORY", None)
    if repo:
        os.environ["GITHUB_REPOSITORY"] = repo.split("github.com/")[-1]
    try:
        with ST.switch_env(switch):
            out = R.build(d, os.path.join(d, "report.html"), now=now)
    finally:
        os.environ.pop("GITHUB_REPOSITORY", None)
        if old is not None:
            os.environ["GITHUB_REPOSITORY"] = old
    return open(out, encoding="utf-8").read()


def site(d, out, switch, env=None):
    """bot.py site of d's report.html (the website and the installed app's shell), as the scan builds it; env adds to the environment (a
    dummy live store's address and publishable key: the app's notifications card as it is once the store is set up)."""
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", d, "--out", out, "--repo", REPO], capture_output=True, text=True,
                       env=dict(os.environ, MEMEBOT_SWITCH_AT=str(switch), PYTHONDONTWRITEBYTECODE="1", **(env or {})))
    return os.path.join(out, "index.html") if r.returncode == 0 else None


def text(h):
    h = re.sub(r"(?s)<style>.*?</style>|<script\b.*?</script>", " ", h)
    return re.sub(r"[ \t\n\r]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))


def pane(page, key):
    """The inner HTML of #pane-<key> (the panes follow each other in this order: home, pick, young, office, account). For "account" (the
    Archiv tab) only its traders fold, the last block of the pane: the research fold before it is the Pick tab's old Details."""
    nxt = {"home": "pick", "pick": "young", "young": "office", "office": "account"}.get(key)
    a = page.find('<div class="pane" id="pane-%s"' % key)
    if a < 0:
        return ""
    a = page.find(">", a) + 1
    b = page.find('<div class="pane" id="pane-%s"' % nxt, a) if nxt else page.find("</div></div><script>", a)
    inner = page[a:b if b > 0 else len(page)]
    t = inner.find('<details class="fold arch-tr">') if key == "account" else -1
    return inner[t:] if t >= 0 else inner


class Classes(HTMLParser):
    """Each start tag whose class names a "pa-" class, and whether a .pane is among its ancestors (void tags kept off the stack)."""
    VOID = {"br", "img", "input", "meta", "link", "hr", "wbr", "source", "col", "path", "circle", "rect", "line", "polyline", "polygon", "stop", "use"}

    def __init__(self):
        super().__init__()
        self.stack, self.out = [], []

    def handle_starttag(self, tag, attrs):
        cls = (dict(attrs).get("class") or "").split()
        if any(c.startswith("pa-") for c in cls):
            self.out.append((tag, " ".join(cls), any("pane" in a for a in self.stack)))
        if tag not in self.VOID:
            self.stack.append(cls)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()


def checks(check, skips=None):
    print("== the five tabs after the reorganisation: Start, Pick, Radar, Gehirn, Archiv in the app and on the website (page_traders.py, UI1-UI10)")
    skips = skips if skips is not None else []
    tmp = tempfile.mkdtemp(prefix="memebot-trui-")
    try:
        _checks(check, tmp, skips)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _checks(check, tmp, skips):
    now = SWITCH + 30 * H
    d = os.path.join(tmp, "fx")
    page_db(d, now, SWITCH)
    page = build(d, now, SWITCH)
    with ST.switch_env(SWITCH):
        L = T.load(d, now, SWITCH)
        D = R.collect(d, now)
    acc, yp, pp, op = pane(page, "account"), pane(page, "young"), pane(page, "pick"), pane(page, "office")

    # the page never holds the big test whole (about 9 GB on 16 Oct shut the scan's runner down): memesnap and memesnapres are read one
    # file at a time, memebot.load_docs is never asked for them, and the numbers are the same as reading them all
    bt = os.path.join(tmp, "bt")
    shutil.copytree(d, bt)
    for coll, docs in (("memesnapres", {"2026-10-16T0100-1": {"t0": now - 3 * H, "t": now - H, "rule": M.RULE, "coins": [
                            {"a": "C1", "eur": 4.0, "pass": True, "rank": 1}, {"a": "C2", "eur": -20.0, "gone": True}, {"a": "C3"}]},
                        "2026-10-16T0100-2": {"t0": now - 3 * H, "t": now - H, "rule": M.RULE, "coins": [{"a": "C4", "eur": -1.5, "rank": 12}]},
                        "2026-10-16T0200-1": {"t0": now - 2 * H, "t": now, "rule": M.RULE, "coins": [{"a": "C1", "eur": 70.0, "pass": True}]}}),
                       ("memesnap", {"2026-10-16T0300-1": {"t": now - H, "n": 50, "coins": [{"a": "S1", "rank": 1}]},
                                     "2026-10-16T0400-1": {"t": now, "n": 40, "coins": [{"a": "S2", "rank": 2}, {"a": "S3"}]},
                                     "2026-10-16T0400-2": {"t": now, "n": 30, "coins": [{"a": "S4", "rank": 1}]}})):
        os.makedirs(os.path.join(bt, "db", coll), exist_ok=True)
        for k, v in docs.items():
            with open(os.path.join(bt, "db", coll, k + ".json"), "w", encoding="utf-8") as f:
                json.dump(v, f)
    asked, orig = [], M.load_docs
    M.load_docs = lambda dd, coll: (asked.append(coll), orig(dd, coll))[1]
    try:
        with ST.switch_env(SWITCH):
            Db = R.collect(bt, now)
    finally:
        M.load_docs = orig
    with ST.switch_env(SWITCH):
        wb = M.blended_weights(bt)
    g = {b["key"]: b for b in Db["big"]}
    check("memesnap" not in asked and "memesnapres" not in asked and Db["seen_coins"] == 4 and [c["a"] for c in Db["cands"]] == ["S4", "S2"]
          and Db["scan_n"] == 70 and g["2026-10-16T0100"]["n"] == 3 and g["2026-10-16T0100"]["passAvg"] == 4.0 and g["2026-10-16T0200"]["passAvg"] == M.EUR_CLIP[1]
          and (Db["weights"], Db["winfo"]["n"]) == (sorted(wb[0].items(), key=lambda kv: (-abs(kv[1]), kv[0]))[:16], wb[1]["n"]),
          "the page reads the big test one file at a time (load_docs never asked for memesnap or memesnapres): its groups, 4 coins seen, the "
          "newest scan's candidates (S4, S2) and its 70 coins, the weights as memebot.blended_weights")

    # UI1: five radios in order, the labels, the Traders content once and inside its pane, no account block outside the panes
    radios = re.findall(r'<input type="radio" name="tab" id="(tab-\w+)"', page)
    labels = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r'<label for="tab-\w+" role="tab">(.*?)</label>', page)]
    cp = Classes()
    cp.feed(page)
    outside = [c for c in cp.out if not c[2]]
    check(radios == ["tab-home", "tab-pick", "tab-young", "tab-office", "tab-account"] and labels == ["Start", "Pick", "Radar", "Gehirn", "Archiv"] and 'id="tab-home" checked' in page
          and page.count('data-tr="compare"') == 1 and 'data-tr="compare"' in acc and page.count("<h2>Three paper traders</h2>") == 1 and "<h2>Three paper traders</h2>" in acc
          and cp.out and not outside and '<div class="pane" id="pane-account" data-app="account"' in page and "could not be rendered" not in page,
          "UI1 the website: five radios in the order home, pick, young, office, account, labelled Start, Pick, Radar, Gehirn, Archiv; the Traders content once, inside "
          "#pane-account (data-app account); no element with a pa- class outside a pane (%d inside, outside: %s)" % (len(cp.out), outside[:3]))

    # UI4: the numbers are traders.load's, parsed from the page; the account total is the paper account plus the closed rule-2 results
    S = L["same"]
    rows = re.findall(r'<tr><td><i class="trdot (t\d)" aria-hidden="true"></i>.*?</td><td class="n">(.*?)</td><td class="n">(.*?)</td><td class="n">(.*?)</td></tr>', acc)
    got_rows = [(k, text(a).strip(), b, c) for k, a, b, c in rows]
    want_rows = [(k, PA.eur(S[k], True), PA.pct1(S[k] / S["invested"]), str(S["n"])) for k in ("t1", "t2", "t3")]
    bigs = dict(re.findall(r'<article class="trcard trader (t\d)".*?<p class="trbig[^"]*">([^<]*)</p>', acc, re.S))
    splits = dict((k, text(v)) for k, v in re.findall(r'<article class="trcard trader (t\d)".*?<p class="trl trsplit">(.*?)</p>', acc, re.S))
    G = S["groups"]
    split_ok = all(PA.eur(G[g][k], True) in splits.get(k, "") for k in ("t1", "t2", "t3") for g in ("pick", "radar", "young") if G[g]["n"])
    st = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {})
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {})
    acct = M.paper_account(M.positions(d), st["paperSince"], marks.get("px"))["pnl"] + sum(
        doc["eur"] - RP.RADAR_TICKET for doc in RP.load_docs(d).values() if doc.get("rule") == 2 and doc.get("state") == "closed" and M.num(doc.get("eur")) is not None)
    t1card = text(re.search(r'<article class="trcard trader t1".*?</article>', acc, re.S).group(0))
    check(got_rows == want_rows and bigs == {k: PA.eur(S[k], True) for k in ("t1", "t2", "t3")} and split_ok and G["radar"]["n"] > 0
          and round(acct, 2) == L["t1"]["account"] and "account total %s" % PA.eur(acct, True) in t1card
          and "on %d finished trades · %s of %s" % (S["n"], PA.pct1(S["t1"] / S["invested"]), PA.eur(S["invested"])) in t1card,
          "UI4 the compare table, the three big numbers and the split lines are traders.load's (%s); the stop-loss card's account total is the paper account "
          "plus the closed rule-2 results (%s)" % ([r[1] for r in got_rows], PA.eur(acct, True)))

    # UI5: words and formats of the new blocks
    rpos = (re.search(r'<section class="trpos" data-tr="radar">.*?</section>', yp, re.S) or re.match("", "")).group(0)
    pick_lines = " ".join(re.findall(r'<h2>[^<]*</h2>|<p class="paper">[^<]*</p>|<p class="pick-note">[^<]*</p>', pp))
    words = text(acc) + " " + text(rpos) + " " + text(pick_lines)
    nosvg = lambda h: re.sub(r"(?s)<svg\b.*?</svg>", " ", h)       # the chart's end labels are whole euros (+1,753 €): UI11
    euros = re.findall(r"[+−-]?[\d][\d,.]*\u00a0€", text(nosvg(acc)) + " " + text(rpos))
    bad_money = [e for e in euros if not MONEY.match(e) and not TICKET.match(e)]
    cells = re.findall(r'<td class="n"[^>]*>(.*?)</td>', (re.search(r'<div class="tbl stack trfin">.*?</table>', acc, re.S) or re.match("", "")).group(0))
    cells += [x[1] for x in rows] + re.findall(r'<span class="st">(.*?)</span></li>', rpos)
    check(rpos and pick_lines and "\u2014" not in words and not BANNED.findall(words) and not bad_money and euros and not any("–" in text(c) for c in cells)
          and not any(TICKET.match(e) and e not in ("50\u00a0€", "10\u00a0€", "3\u00a0€") for e in euros),
          "UI5 the Traders pane, the radar's paper positions and the new pick lines: no em dash, none of the banned words (%s), no '–' in a result cell, "
          "every money string 1,234.56 € (or a ticket: 50 €, 10 €, 3 €) (%d strings%s)" % (BANNED.findall(words)[:3], len(euros), (", wrong: %s" % bad_money[:3]) if bad_money else ""))

    # UI6: the pick: one heading by tier, no banner, the odds inside All numbers, the links wrap, the paper line in its three cases
    heads, bans = {}, []
    for tier in ("strong", "weak", "risky", "fallback", "watch"):
        Dt = dict(D, rec=dict(D["rec"], picks=[dict(D["rec"]["picks"][0], tier=tier, relaxed=["liquidity"])]))
        h = R.rec_section(Dt, embed=False)
        heads[tier] = re.search(r"<h2>(.*?)</h2>", h).group(1)
        bans.append(PR.BANNER in h or "nogood" in h)
    heads["none"] = re.search(r"<h2>(.*?)</h2>", R.rec_section(dict(D, rec=dict(D["rec"], picks=[])), embed=False)).group(1)
    hz = R.horizon_text()
    card = (re.search(r'<article class="card rec">.*?</article>', pp, re.S) or re.match("", "")).group(0)
    nums = (re.search(r'<details class="more nums">.*?</details>', card, re.S) or re.match("", "")).group(0)
    hr = R.paper_rows(D)[D["rec"]["picks"][0]["addr"]]
    pct = R.sgn("%+.1f%%" % (100.0 * hr["pnl"] / hr["ticket"]))
    held = R.paper_line(dict(D["rec"]["picks"][0], bought="held"), R.paper_rows(D))
    other = R.paper_line(dict(D["rec"]["picks"][0], bought="no free slot"), {})
    t_in = R.local(hr["p"]["entryAt"])
    check(heads == {"strong": "The pick for the next " + hz, "weak": "The pick for the next " + hz, "risky": "Risky pick for the next " + hz,
                    "fallback": "Risky pick for the next " + hz, "watch": "No pick this scan", "none": "No pick this scan"} and not any(bans) and PR.BANNER not in pp
          and '<div class="verdicts">' in nums and "Chance of a profit" in nums and "Chance of going to zero" in nums and '<div class="verdicts">' not in card.replace(nums, "")
          and ".card.rec .links { flex-wrap:wrap; overflow:visible }" in R.CSS and "flex-wrap:nowrap" not in R.CSS.split(".card.rec .links", 1)[-1].split("}", 1)[0]
          and '<p class="paper">Bought on paper: 50\u00a0€ at %s · now %s</p>' % (t_in.strftime("%H:%M"), pct) in card
          and held == "Already held since %s · now %s" % (t_in.strftime("%b %d, %H:%M"), pct) and other == "Not bought: no free slot",
          "UI6 the pick: one heading per tier %s, no banner; the score and odds tiles inside All numbers; the link pills wrap; the paper line bought "
          "('Bought on paper: 50 € at HH:MM · now %s'), held (%r) and not bought (%r)" % (heads, pct, held, other))
    risky = R.rec_card(dict(D["rec"]["picks"][0], tier="fallback", relaxed=["liquidity under the floor"]), now, False, [], {})
    same = R.rec_card(D["rec"]["picks"][0], now, False, [dict(D["rec"]["picks"][0], sym="X%d" % i) for i in range(3)], {})
    check("No coin passed every safety check this scan; this is the best of the rest." in risky and "It failed: liquidity under the floor." in risky
          and "The model gives almost every coin the same odds right now, so the score ranks them." in same,
          "UI6 a risky or fallback pick has one amber line under the strip (a fallback keeps what it failed); same odds for every candidate: the honest note inside All numbers")

    # UI7: the radar card's paper line only for pb 1; pb passes the whitelist only as 0 or 1; t3 as a few words
    vals = [1, 0, True, "1", 2, 1.0, None, -1]
    py_pb = [PR.clean_coin({"addr": addr(1), "pb": v})["pb"] for v in vals]
    py_t3 = PR.clean_coin({"addr": addr(1), "t3": ["no socials", "", 5, "a" * 80, "b", "c", "d"]})["t3"]
    js_pb, js_t3 = None, None
    node = shutil.which("node")
    if node:
        f = os.path.join(tmp, "pb.js")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;},getElementById:function(){return null;},addEventListener:function(){}};"
                     "global.navigator={};\n" + PR.JS + "\nvar R=window.MemebotRadar,V=%s;console.log(JSON.stringify([V.map(function(v){return R.clean({kind:'radar',t:1,coins:[{addr:'%s',v:'good',pb:v}]}).coins[0].pb;}),"
                     "R.clean({kind:'radar',t:1,coins:[{addr:'%s',v:'good',t3:['no socials','',5,'%s','b','c','d']}]}).coins[0].t3]));\n" % (json.dumps(vals), addr(1), addr(1), "a" * 80))
        r = subprocess.run([node, f], capture_output=True, text=True)
        try:
            js_pb, js_t3 = json.loads(r.stdout)
        except ValueError:
            js_pb = r.stderr[-200:]
    else:
        skips.append("UI7's script whitelist (no node)")
    check(py_pb == [1, 0, 0, 0, 0, 1, 0, 0] and py_t3 == ["no socials", "a" * 60, "b"] and (js_pb is None or (js_pb == py_pb and js_t3 == py_t3))
          and "if(c.pb===1)sm.appendChild(el('p','rpaper'" in PR.JS and 'data-paper="Bought on paper · 10\u00a0€"' in yp and "'Learning trader skips: '+c.t3.join(', ')" in PR.JS,
          "UI7 the radar card's line 'Bought on paper · 10 €' only for pb === 1; pb passes both whitelists only as 0 or 1 (%s; script %s), t3 as at most "
          "%d words of at most 60 characters (the chip 'Learning trader skips: ...')" % (py_pb, js_pb if js_pb is not None else "not run", PR.T3_MAX))

    # UI8: office: the card lines wrap, no faded radar blocks, no balance chart
    oc = R.CSS + PR.CSS + __import__("page_office").CSS + __import__("page_office").DESK_CSS
    rule = lambda sel, css: " ".join(re.findall(re.escape(sel) + r"\s*\{([^}]*)\}", css))
    check("ellipsis" not in rule(".ocard .ocl", oc) + rule(".ocard .ocn", oc) and "white-space:normal" in rule(".ocard .ocl", oc)
          and not re.search(r"\.dim[^{]*\{[^}]*opacity:\s*\.?[0-9]", oc) and not re.search(r"\.rstats\.dim[^{]*\{[^}]*opacity", oc)
          and not re.search(r"\.odk-g\.dim[^{]*\{[^}]*opacity", oc) and 'data-po-bal' not in page and 'class="obal' not in page
          and '<label class="ocard" for="od-' in op and not SPOTTER.search(op),
          "UI8 office: no text-overflow:ellipsis on .ocl or .ocn (the lines wrap), no opacity on a .dim radar block (the radar's stats, cards, desk "
          "stations, chat), no paper account chart; after the switch no Launch spotter card")

    # UI3: the switch: after it no early list, no new-launches section, no Launch spotter card, the page under 1.2 MB; before it the legacy parts
    d2 = os.path.join(tmp, "pre")
    page_db(d2, now, now + 2 * H)
    pre = build(d2, now, now + 2 * H, repo=REPO)
    post = build(d, now, SWITCH, repo=REPO)
    pre_y, post_y = pane(pre, "young"), pane(post, "young")
    check('<details class="early" data-early' in pre_y and "New launches (until " in pre_y and SPOTTER.search(pane(pre, "office"))
          and "data-early" not in post_y and "New launches (until " not in post and "under an hour old" not in post_y and not SPOTTER.search(post)
          and ".ecards" not in post and len(post.encode()) <= 1_200_000,
          "UI3 the switch: after it (MEMEBOT_SWITCH_AT in the past) no data-early, no new-launches section and no Launch spotter card, the page %d bytes "
          "(at most 1.2 MB); before it the legacy section 'New launches (until ...)', the early box and the spotter's card" % len(post.encode()))
    e_pre = pre_y
    e_post = PT.radar_positions(dict(D, traders=dict(L, trades=[t for t in L["trades"] if t["group"] != "radar"])))
    want_pre = "From %s, %s, every coin the radar finds without traps is bought on paper for 10\u00a0€." % (PA.mday(now + 2 * H), PA.hhmm(now + 2 * H))
    check(html.escape(want_pre, quote=False) in e_pre and "No radar paper position yet." in e_post and "07:00" not in e_post,
          "UI3 the radar's paper positions when there is none: before the switch '%s', after it 'No radar paper position yet.' (the radar runs around the "
          "clock: no hours named)" % want_pre)

    # the radar's paper positions: newest first, ten in view, a state or a result with its exit word, four address characters where symbols repeat
    rows_r = re.findall(r'<li class="trp"><span class="tm">.*?</span><span class="cn"><b>([^<]*)</b>(.*?)</span><span class="st">(.*?)</span></li>', rpos)
    radar_t = [t for t in L["trades"] if t["group"] == "radar"]
    dup = dict(L, trades=[dict(t, sym="SAME") for t in L["trades"]])
    dhtml = PT.radar_positions(dict(D, traders=dup))
    words_r = [text(s_).strip() for _, _, s_ in rows_r]
    check([r[0] for r in rows_r] == [t["sym"] for t in radar_t][:PT.RADAR_SHOWN] and any("running until" in w for w in words_r)
          and any(w.endswith(("stop −30%", "11x target", "6 h limit", "pool gone")) for w in words_r) and any("no price data" in w for w in words_r)
          and all('<small class="ad">' in x for x in re.findall(r'<span class="cn">(.*?)</span>', dhtml)) and '<small class="ad">' not in rpos
          and "(%d coins, %s on %d priced); that test is not part of the three traders." % (L["radarV1"]["n"], PA.eur(L["radarV1"]["pnl"], True), L["radarV1"]["priced"]) in text(rpos),
          "the Radar tab's paper positions: newest first (%s), a state (running until, waiting for a price, no price data) or the result with its exit "
          "word, four address characters when symbols repeat, the radar's old test in one sentence" % [r[0] for r in rows_r])
    # the radar's old test sold at the best price (the Best-price trader's way and notes), never the raw top; none priced: no such line
    v1 = L["radarV1"]
    want_b = "Sold at the best price within 6 h instead, looking back (not possible in reality): %s on the same %d%s." % (
        PA.eur(v1["t2"], True), v1["priced"], "".join(" · " + p for p in PT.t2_notes(v1) if p))
    nob = PT.radar_positions(dict(D, traders=dict(L, radarV1=dict(v1, t2=None))))
    fake = PT.radar_positions(dict(D, traders=dict(L, radarV1=dict(v1, n=v1["priced"] + 5, t2=-1.5, est=1, capped=2, leftOut=3))))
    one = PT.radar_positions(dict(D, traders=dict(L, radarV1=dict(v1, t2=0.0, est=0, capped=1, leftOut=1))))
    check(v1["t2"] is not None and want_b in text(rpos) and "best price within 6 h" not in text(nob) and "that test is not part of the three traders." in text(nob)
          and "(%d coins, " % (v1["priced"] + 5) in text(fake)
          and "−1.50 € on the same %d · 1 estimated (the real best is at least this) · 2 price spikes counted at 30x at most · 3 spikes left out "
              "(no volume or pool already dead)." % v1["priced"] in text(fake) and "—" not in text(fake)
          and "on the same %d · 1 price spike counted at 30x at most · 1 spike left out (no volume or pool already dead)." % v1["priced"] in text(one),
          "the Radar tab: the radar's old test also sold at the best price within 6 h ('%s'); without a priced one no such line" % want_b)

    # UI10: the traders failed: a note, the activity (the paper account's own) and the open positions; no page error
    Df = dict(D, traders={"err": "X"})
    with ST.switch_env(SWITCH):
        pf = R.render(Df)
    accf = pane(pf, "account")
    yf = pane(pf, "young")
    ef = [PT.radar_positions({"now": now, "traders": tf}) for tf in ({"err": "ValueError: boom"}, dict(T._empty(now, "ValueError: boom")))]
    check("The traders could not be computed this time (X). The paper account itself is unaffected." in accf and 'data-tr="feed"' in accf and "Open positions (" in accf
          and 'class="pa-ev ' in accf and 'data-tr="compare"' not in accf and "could not be rendered" not in pf
          and "The radar's paper positions could not be computed this time (X). The paper account itself is unaffected." in text(yf) and "No radar paper position yet" not in yf
          and all("could not be computed this time (ValueError)" in text(h) and "No radar paper position yet" not in h and "From " not in text(h) for h in ef),
          "UI10 traders.load failed (err X): the Traders tab says so in one note and shows the activity (the paper account's own) and the open positions only; "
          "the Radar tab's paper positions say so too, never 'No radar paper position yet' (also with load's empty error shape)")

    _fixes(check, d, now, page, acc, yp, pp, L, D)

    # the decision log folds kept days of one group, changed rows bold, the four paragraphs
    decs = [{"day": "2026-10-1%d" % i, "group": "pick", "mode": "replay", "changed": None, "why": "Learning: %d of 80 finished trades." % (10 * i), "n": 10 * i,
             "rule": T.rule_dict(T.START), "prev": T.rule_dict(T.START), "skip": []} for i in range(1, 5)]
    decs.append({"day": "2026-10-14", "group": "young", "mode": "replay", "changed": "rule", "why": "Target 11x → 3x: better.", "n": 333,
                 "rule": {"stop": 0.3, "target": 3.0, "hours": 6.0}, "prev": T.rule_dict(T.START), "skip": []})
    lg = PT.decide_fold(dict(L, decisions=decs))
    check("Oct 11 to Oct 14" in text(lg) and "Learning: 40 of 80 finished trades." in text(lg) and '<tr class="ch">' in lg and "target 11x → 3x" in lg
          and lg.count("<tr") == 3 and "at most 2 signs and at most 40% of coins skipped" in text(lg) and "Only the live part shows whether learning helps." in text(lg),
          "the learning trader's log: four kept days of one group in one row ('Oct 11 to Oct 14 · Picks · kept · Learning: 40 of 80'), a change in bold with "
          "its words (target 11x → 3x), the four paragraphs")

    _browser(check, tmp, d, now, page, skips)


def _fixes(check, d, now, page, acc, yp, pp, L, D):
    """UI11 to UI16: the final review's findings (the compare chart, the counts, the activity's count, the radar rows, the trader texts, the
    other tabs' touched texts)."""
    # UI11: the compare chart: stop-loss drawn last (on top), no "start 0.00", whole-euro end labels inside the box, the tooltip in the page's formats
    cmp_ = re.search(r'<div class="trcard trcmp" data-tr="compare">.*?<p class="trfoot">', acc, re.S).group(0)
    svgs = re.findall(r"(?s)<svg\b.*?</svg>", cmp_)
    orders = [re.findall(r'<path class="line (t\d)"', g) for g in svgs]
    labels = [html.unescape(x) for g in svgs for x in re.findall(r'<text class="label"[^>]*>([^<]*)</text>', g)]
    fits = [float(x) + 7.4 * len(html.unescape(t)) <= float(w) + 0.5 for g in svgs for w in re.findall(r'<svg class="chart-svg" width="(\d+)"', g)
            for x, t in re.findall(r'<text class="label" x="([\d.]+)"[^>]*>([^<]*)</text>', g)]
    pts = [json.loads(html.unescape(x)) for g in svgs for x in re.findall(r'data-pts="([^"]*)"', g)]
    tips = [v for p_ in pts for e in p_ for v in [e["t"]] + [x[1] for x in e["v"]]]
    one = R.line_chart([("a", "t1", [(0, 1.0), (H, 5.0)]), ("b", "t3", [(0, 1.0), (H, 5.0)])], 0.0, R.NARROW, fmt_v=lambda v: PA.eur(v, True))
    check(len(svgs) == 2 and all(o == ["t3", "t2", "t1"] for o in orders) and "start " not in text(cmp_) and labels
          and all(re.match(r"^[+−]?\d{1,3}(,\d{3})*\u00a0€$", x) for x in labels) and all(fits) and tips
          and not any(re.search(r"\d{4}-\d\d-\d\d", str(v)) for v in tips) and all(isinstance(e["v"][0][1], str) and MONEY.match(e["v"][0][1]) for p_ in pts for e in p_)
          and ".line.t3 { stroke:var(--t3); stroke-width:5 }" in PT.CSS and one.count('class="label"') == 1 and "break-even" not in R.line_chart(
              [("a", "s1", [(0, 1.0), (H, 2.0)])], 0.0, R.NARROW, ref_label=None),
          "UI11 the compare chart: drawn learning, best price, stop-loss (the real account on top; the learning line wider under it), no 'start 0.00' label, "
          "end labels in whole euros (%s) with room inside the chart, the tooltip as 'Oct 16, 05:00' and 1,234.56 € (no ISO date); two lines that end "
          "together get one label" % labels)

    # UI12: the counts say what they count: the footnote's 6-hour count, the card's open positions as the fold counts them
    c = L["counts"]
    foot = text(re.search(r'<p class="trfoot">(.*?)</p>', acc, re.S).group(1))
    t1c = text(re.search(r'<article class="trcard trader t1".*?</article>', acc, re.S).group(0))
    m_open = re.search(r"open now: (\d+) position", t1c)
    m_fold = re.search(r"Open positions \((\d+)\)", text(acc))
    ropen = [t for t in L["trades"] if t["group"] == "radar" and t["state"] == "running" and t["t1"] is None]
    check("still open" not in foot and ("%d still inside their 6 hours" % c["running"]) in foot and m_open and m_fold and m_open.group(1) == m_fold.group(1)
          and int(m_open.group(1)) == L["t1"]["open"]["n"] + len(ropen) and (not ropen or "%d radar" % len(ropen) in t1c)
          and (c["waiting"] or "waiting for a price" not in foot),
          "UI12 the footnote counts the trades inside their 6 hours as such (%r), the stop-loss card's 'open now' equals the fold 'Open positions (%s)': "
          "%d paper and %d radar" % (foot, m_fold.group(1) if m_fold else None, L["t1"]["open"]["n"], len(ropen)))

    # UI13: the activity fold names how many there are, not load's cap; load carries the uncapped count
    many = dict(L, feed=(L["feed"] * 400)[:T.FEED_MAX], feedN=1285)
    big_ = PT.all_activity(D, many)
    small_ = PT.all_activity(D, L)
    check(L["feedN"] >= len(L["feed"]) and len(L["feed"]) <= T.FEED_MAX and (L["feedN"] <= T.FEED_MAX) == (L["feedN"] == len(L["feed"]))
          and "Latest activity (400 of 1,285)" in text(big_) and "the newest 400 bought and sold" in text(big_) and "everything" not in big_
          and (not small_ or "All activity (%d)" % len(L["feed"]) in text(small_)) and T._empty(now)["feedN"] == 0,
          "UI13 the activity fold: 'Latest activity (400 of 1,285)' when load keeps the newest 400 of more (load's feedN: %d events, %d kept), 'All "
          "activity (n)' when it has them all" % (L["feedN"], len(L["feed"])))

    # UI14: a radar stop's gap comes from the trade row, so it survives when its sale has left the newest 400 events
    rad = [t for t in L["trades"] if t["group"] == "radar"]
    fin_r = [t for t in rad if t["t1"] is not None]
    docs = RP.load_docs(d)
    gap = dict(rad[0], state="finished", t1=-6.2, t1why="stop", move=-0.62)
    gp_ = PT.radar_positions(dict(D, traders=dict(L, trades=[gap], feed=[])))
    check(fin_r and all(t["move"] is not None and abs(t["move"] - (docs[t["id"]]["x"] - 1)) < 1e-3 for t in fin_r if M.num((docs.get(t["id"]) or {}).get("x")) is not None)
          and "stop, price gapped to −62%" in text(gp_) and all("move" in t for t in L["trades"]),
          "UI14 the radar's paper positions read a stop's gap from the trade row (load's move: the doc's x - 1 on %d closed radar trades), so a stop at "
          "-62%% says 'price gapped to -62%%' without its sale in the feed" % len(fin_r))

    # UI15: the best-price trader's words (highest minute close; why it can be below the real sale) and the learning trader's replay marker
    fin = [t for t in L["trades"] if t["state"] == "finished"]
    low = dict(L, trades=[dict(fin[0], t1=5.0, t2=1.0)] + [t for t in L["trades"] if t is not fin[0]])
    c2 = PT.cards(low, now)
    t2card = re.search(r'<article class="trcard trader t2".*?</article>', c2, re.S).group(0)
    rp = dict(L, t3=dict(L["t3"], vsT1={"diff": 12.5, "ci": [-3.0, 20.0], "n": 40, "range": [0, 0]}, live={"diff": 0.0, "ci": [0.0, 0.0], "n": 0}))
    lv = dict(L, t3=dict(L["t3"], vsT1={"diff": 12.5, "ci": [3.0, 20.0], "n": 40, "range": [0, 0]}, live={"diff": 12.5, "ci": [3.0, 20.0], "n": 40}))
    part = dict(L, t3=dict(L["t3"], vsT1={"diff": 12.5, "ci": [3.0, 20.0], "n": 40, "range": [0, 0]}, live={"diff": 2.5, "ci": [1.0, 4.0], "n": 10}))
    t3_ = lambda X: text(re.search(r'<article class="trcard trader t3".*?</article>', PT.cards(X, now), re.S).group(0))
    row3 = lambda X: text(re.search(r'<tr><td><i class="trdot t3".*?</tr>', PT.compare(X), re.S).group(0))
    face2 = text(re.sub(r'(?s)<details class="hi">.*?</details>', "", t2card))        # the card without its ⓘ
    n_low = sum(1 for t in low["trades"] if t["state"] == "finished" and t["t2"] < t["t1"])
    check(n_low >= 1 and "Sells each coin at its highest minute close within 6 h" in t2card and "On %d of %d trades the stop-loss trader got more" % (n_low, len(fin)) in text(t2card)
          and "estimated (the real best is at least this)" not in face2 and "spike" not in face2
          and "could be chance · worked out afterwards" in t3_(rp) and "worked out afterwards" not in t3_(lv).split("Live since")[0]
          and "30 of these 40 trades worked out afterwards" in t3_(part) and "worked out afterwards" in row3(rp) and "worked out afterwards" not in row3(lv) + row3(dict(rp, t3=dict(rp["t3"], vsT1=dict(rp["t3"]["vsT1"], diff=0.0))))
          and "before that worked out afterwards" not in t3_(lv),
          "UI15 the best-price trader sells at its highest minute close; its ⓘ says on how many trades the stop-loss trader got more and holds the "
          "estimate and spike counts; the learning trader's comparison says 'worked out afterwards' (all or 'k of these n') until it is all live, and so does its table row")

    # UI16: the touched texts on the other tabs
    with ST.switch_env(SWITCH):
        job_after, job_before = R.office_meta("trader", now)[1], R.office_meta("trader", SWITCH - H)[1]
    rk = {"lpLocked": 95.0, "danger": [], "top1": 3.0, "top10": 20.0, "holdersN": 900, "insiders": 0}
    why_ = R.why_words("66% of trades were buys; biggest buyer 23% of the buying; buy pressure")
    note_ = R.train_section({"train": {"note": "Walk-forward on 188 scans (247249 coin results): fine; 0.0123 and 1234.5 stay", "rows": 1, "scans": 1}})
    hr = R.hold_rule_text()
    check("table and the paper account" not in pp
          and "every coin the launch radar finds without traps for 10\u00a0€" in job_after and M.PAPER_LABEL in job_after and "new launches" not in job_after
          and "the first 5 new launches for 3\u00a0€ each" in job_before and not BANNED.search(job_after + job_before)
          and R.checks_summary(rk).split(" · ")[0].endswith("passed") and "clean" not in R.checks_summary(rk) + R.checklist(rk, "x")
          and why_ == "66% of trades were purchases; biggest buyer 23% of the purchases; purchase pressure" and not BANNED.search(why_)
          and "247,249 coin results" in note_ and "0.0123 and 1234.5 stay" in note_ and "at least 0.10\u00a0€" in hr and "at least 0.81\u00a0€" in hr and "(rug)" not in hr
          and "never buys" not in PR.INFO_TEXT + yp and "New tab" not in text(page) + PR.INFO_TEXT and "Walk-forward test" not in page,
          "UI16 the touched texts: no paper account tile in the tip record (selftest.py checks its fold with tips); the Office trader's job from the switch "
          "(%r) and before it; the safety summary says passed; stored reasons in the page's words (%r); counts with a separator in the training note; the fee "
          "minimums in euros, no '(rug)'; no 'never buys', no 'New tab'" % (job_after, why_))


PROBE = r"""(tab) => {
  const p = document.getElementById('pane-' + tab), out = {h: document.documentElement.scrollHeight, hs: document.documentElement.scrollWidth - innerWidth, clip: []};
  p.querySelectorAll('svg.chart-svg').forEach(s => { const r = s.getBoundingClientRect(); if (r.width < 1) return;     // chart text cut at the chart's edge
    s.querySelectorAll('text').forEach(t => { const b = t.getBoundingClientRect(); if (b.width >= 1 && (b.right > r.right + 0.5 || b.left < r.left - 0.5)) out.clip.push(t.textContent); }); });
  if (tab === 'account') {      // text runs that overlap other text inside the trader cards (shoot.py's check; the text of a closed ⓘ is not shown)
    p.querySelectorAll('details.arch-tr').forEach(d => { d.open = true; });     // the traders' fold on the Archiv tab, opened after the height is read
    const runs = [];
    const shut = e => { for (let a = e; a; a = a.parentElement) { const d = a.parentElement; if (d && d.tagName === 'DETAILS' && !d.open && a.tagName !== 'SUMMARY') return true; } return false; };
    document.querySelectorAll('.trcards *').forEach(e => e.childNodes.forEach(n => { if (n.nodeType === 3 && n.textContent.trim() && !shut(e)) { const rg = document.createRange(); rg.selectNodeContents(n);
      Array.from(rg.getClientRects()).forEach(r => { if (r.width > 1 && r.height > 1) runs.push({e, l: r.left, r: r.right, t: r.top, b: r.bottom}); }); } }));
    out.over = 0;
    for (let i = 0; i < runs.length; i++) for (let j = i + 1; j < runs.length; j++) { const a = runs[i], b = runs[j];
      if (a.e === b.e || a.e.contains(b.e) || b.e.contains(a.e)) continue;
      if (Math.min(a.r, b.r) - Math.max(a.l, b.l) > 2 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 3) out.over++; }
  }
  out.last = p.lastElementChild ? p.lastElementChild.className : '';
  return out; }"""


# the notifications card once the live store is set up and notifications are not on yet (render()'s "off": the state chip, the note, the
# button, the "Which notifications" fold); the probe opens the fold and reads the switches' opacity along their ancestors, and the tab's height
OFF_JS = r"""() => { const a = document.querySelector('#pane-home .appnotif'); if (!a) return null;
  const n = a.querySelector('.nf-note'), b = a.querySelector('.nf-btn'), w = a.querySelector('.nf-which');
  a.querySelector('.chip').textContent = 'Off'; n.hidden = false; n.textContent = 'Get a notification on this iPhone for a coin with no trap found and for each pick.';
  b.hidden = false; b.textContent = 'Turn on notifications'; if (w) w.hidden = false; document.querySelectorAll('details').forEach(d => d.open = false); window.scrollTo(0, 0);
  const h = document.documentElement.scrollHeight; if (!w) return {h, which: false};
  w.open = true; const op = e => { let o = 1; for (let x = e; x && x !== document.body; x = x.parentElement) o *= +getComputedStyle(x).opacity; return o; };
  const txt = Array.from(w.querySelectorAll('.nf-row b, .nf-row small')).map(op);
  return {h, which: true, rows: w.querySelectorAll('.nf-row').length, op: Math.min.apply(null, txt.concat([1])), last: a.parentElement.lastElementChild === a}; }"""


def _browser(check, tmp, d, now, page, skips):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the Traders tab's browser checks (no Playwright)")
        print("  SKIP the browser checks of the five tabs: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    # the radar doc current by the browser's clock: its cards show (a running loop), the app's badge counts them
    ST._w(os.path.join(d, "radar_live.json"), radar_doc(int(time.time() * 1000) - MIN))
    build(d, now, SWITCH)
    idx = site(d, os.path.join(tmp, "site"), SWITCH)
    real = os.environ.get("MEMEBOT_REALDATA")
    ridx = None
    if real and os.path.isdir(os.path.join(real, "db")):
        rd = os.path.join(tmp, "real")
        shutil.copytree(real, rd, ignore=shutil.ignore_patterns("report.html", "memetrader"))
        st = M.load_json(os.path.join(rd, "db", "memebot", "state.json"), {})
        rnow = int(M.num(st.get("lastRun")) or now)
        rsw = rnow - H
        subprocess.run([PY, os.path.join(HERE, "traders.py"), "run", "--dir", rd, "--now", str(rnow)], capture_output=True, text=True,
                       env=dict(os.environ, MEMEBOT_SWITCH_AT=str(rsw)))
        subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", rd, "--out", os.path.join(rd, "report.html"), "--horizon", "2h", "--now", str(rnow)],
                       capture_output=True, text=True, env=dict(os.environ, MEMEBOT_SWITCH_AT=str(rsw)))
        ridx = site(rd, os.path.join(tmp, "site-real"), rsw)
        rpage = open(os.path.join(rd, "report.html"), encoding="utf-8").read() if os.path.exists(os.path.join(rd, "report.html")) else ""
        racc = pane(rpage, "account")
        rwords = BANNED.findall(text(racc))
        check(racc and not rwords and "\u2014" not in text(racc), "UI5 on the real-data copy too: none of the banned words in the Traders pane (%s) and no em dash" % rwords[:5])
    else:
        skips.append("UI9 on a real-data copy (MEMEBOT_REALDATA not set): the layout ran on the fixture only")
    FONT = "document.addEventListener('DOMContentLoaded',function(){var s=document.createElement('style');s.textContent=':root{--sans:\\'Liberation Sans\\',Arial,sans-serif !important}';document.head.appendChild(s);});"
    sbidx = site(rd if ridx else d, os.path.join(tmp, "site-sb"), rsw if ridx else SWITCH,
                 {"SUPABASE_URL": "https://abcref.supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_selftestdummy00"})
    res, errs, app, lay = {}, [], {}, {}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def open_(index, w, standalone, scheme="light", hash_=""):
                ctx = br.new_context(viewport={"width": w, "height": 844}, color_scheme=scheme, service_workers="block")
                ctx.add_init_script(FONT)
                if standalone:
                    ctx.add_init_script("Object.defineProperty(Navigator.prototype,'standalone',{get:function(){return true;}});")
                ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file://") else r.abort())
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                pg.goto("file://" + index + hash_)
                pg.wait_for_timeout(900)
                return ctx, pg
            # UI2: the app's bar, the deep links, the badge, the notifications card at the end of Traders
            ctx, pg = open_(idx, 390, True)
            app["bar"] = pg.evaluate("Array.from(document.querySelectorAll('.appbar button')).map(b => [b.getAttribute('data-tab'), b.querySelector('span:not([class])').textContent])")
            pg.wait_for_function("!!document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt')", timeout=8000)
            app["badge"] = pg.evaluate("(() => { const b = document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt'); return [b.textContent, b.classList.contains('good'), document.querySelectorAll('.appbar .ab-cnt').length]; })()")
            pg.click('.appbar button[data-tab="home"]')
            pg.wait_for_timeout(300)
            app["notif"] = pg.evaluate(PROBE, "home")["last"]
            app["paper"] = pg.evaluate("(() => { return Array.from(document.querySelectorAll('[data-r-cards] .rcard')).map(c => [c.querySelector('.rsym').textContent, (c.querySelector('.rpaper')||{}).textContent || '', Array.from(c.querySelectorAll('.chip.t3')).map(x => x.textContent)]); })()")
            ctx.close()
            app["deep"] = []
            for h in ("#tab-young", "#tab-radar", "#new", "#tab-account"):
                ctx, pg = open_(idx, 390, True, hash_=h)
                app["deep"].append(pg.evaluate("[document.documentElement.getAttribute('data-apptab'), document.querySelector('input[name=\"tab\"]:checked').id]"))
                ctx.close()
            # the website's deep links: #tab-pick, #tab-account and #tab-office open their tab, #tab-radar the Radar tab
            app["web"] = []
            for h in ("#tab-account", "#tab-office", "#tab-pick", "#tab-radar"):
                ctx, pg = open_(idx, 1280, False, hash_=h)
                app["web"].append(pg.evaluate("document.querySelector('input[name=\"tab\"]:checked').id"))
                ctx.close()
            # the notifications card once the store is set up, notifications off: compact, full opacity, the Traders tab within its limit
            if sbidx:
                ctx, pg = open_(sbidx, 390, True)
                pg.click('.appbar button[data-tab="home"]')
                pg.wait_for_timeout(300)
                app["off"] = pg.evaluate(OFF_JS)
                ctx.close()
            # UI9: no sideways scroll at 320, 375, 390 and 1280; no overlap inside the trader cards; the heights (folds closed)
            for name, index in (("fixture", idx), ("real", ridx)):
                if not index:
                    continue
                for w in (320, 375, 390, 1280):
                    for scheme in (("light", "dark") if w in (390, 1280) else ("light",)):
                        ctx, pg = open_(index, w, w != 1280, scheme)
                        for tab in ("home", "pick", "young", "office", "account"):
                            if w != 1280:
                                pg.click('.appbar button[data-tab="%s"]' % tab)
                            else:
                                pg.click('label[for="tab-%s"]' % tab)
                            pg.wait_for_timeout(250)
                            pg.evaluate("window.scrollTo(0,0)")
                            lay[(name, w, scheme, tab)] = pg.evaluate(PROBE, tab)
                        if w == 390 and scheme == "light":       # a stale radar: the dimmed blocks keep full opacity
                            app["dim"] = app.get("dim", 0) + pg.evaluate("Array.from(document.querySelectorAll('.rstats.dim, .rstats.dim *, .rcard.dim, .rcard.dim *, .odk-g.dim, .odk-g.dim *, "
                                                                         ".ochat.dim, .ochat.dim *, details.rfold.dim, details.rfold.dim *')).map(e => getComputedStyle(e).opacity).filter(o => +o < 1).length")
                        ctx.close()
            br.close()
    except Exception as e:
        check(False, "the browser checks of the five tabs ran (%s)" % str(e)[:200])
        return
    check(app["bar"] == [["home", "Start"], ["pick", "Pick"], ["young", "Radar"], ["office", "Gehirn"], ["account", "Archiv"]] and app["badge"] == ["2", True, 1]
          and app["deep"] == [["young", "tab-young"], ["young", "tab-young"], ["young", "tab-young"], ["account", "tab-account"]] and app["notif"] == "appnotif"
          and app["paper"] == [["GRNA", "Bought on paper · 10\u00a0€", ["Learning trader skips: no socials and no X link"]], ["GRNB", "", []]] and not errs,
          "UI2 the app: the bottom bar Start, Pick, Radar, Gehirn, Archiv; #tab-young, #tab-radar and #new open Radar, #tab-account Archiv; the badge is the radar's "
          "count of coins without traps only (2, green); the notifications card is the last block of Start; UI7 in the browser: the paper line on the pb 1 "
          "card only, the learning trader's skip chip on it %s" % ({k: app[k] for k in ("bar", "badge", "deep", "notif")} if errs or app["bar"][2][1] != "Radar" else (errs[:2] or "")))
    off = app.get("off") or {}
    check(app["web"] == ["tab-account", "tab-office", "tab-pick", "tab-young"] and off.get("which") and off.get("rows") == 2 and off.get("op") == 1 and off.get("last")
          and off.get("h", 9e9) <= LIMITS["home"] and ".nf-prefs.dim" not in __import__("app").PAGE_CSS,
          "UI2 the website's deep links #tab-account, #tab-office, #tab-pick and #tab-radar open their tab (%s); the app's notifications card once the live "
          "store is set up and notifications are off: the two switches behind 'Which notifications', at full opacity (%s), the card last, the Start tab "
          "%s px at 390 (at most %d, %s data)" % (app["web"], off.get("op"), off.get("h"), LIMITS["home"], "real" if ridx else "fixture"))
    clip = {k: v["clip"] for k, v in lay.items() if v.get("clip")}
    hs = {k: v["hs"] for k, v in lay.items() if v["hs"] > 0}
    ov = {k: v["over"] for k, v in lay.items() if v.get("over")}
    heights = {(n, t): v["h"] for (n, w, sc, t), v in lay.items() if w == 390 and sc == "light"}
    over_lim = {k: h for k, h in heights.items() if h > LIMITS[k[1]] and not (k[0] == "fixture" and k[1] == "young")}
    check(lay and not hs and not ov and not over_lim and app.get("dim") == 0 and not clip,
          "UI9 the layout (Chromium, fake fonts as the screenshots): no sideways page scroll at 320, 375, 390 and 1280 px on all five tabs (light and dark at 390 "
          "and 1280), no overlapping text in the trader cards, no faded block, no chart label cut at the chart's edge; the app's tabs at 390 px with "
          "folds closed within %s: %s%s" % (LIMITS, {"%s %s" % k: h for k, h in sorted(heights.items())},
                                            (" scroll %s overlap %s over %s clipped %s" % (hs, ov, over_lim, clip)) if hs or ov or over_lim or clip else ""))


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d skipped: %s)" % (len(skips), "; ".join(skips)) if skips else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
