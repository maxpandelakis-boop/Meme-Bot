#!/usr/bin/env python3
"""selftest_office.py: the checks of the office page parts (page_office.py, WP5c): SPEC 11 U6 (the radar desk on top of the Office tab, agent
cards, office.json unchanged, the radar's floor desk untouched by the office poll and moved by the radar event, 8 departments, the next-scan
estimate from memeruns), U9 (the daily overview names an hour only when it stands out), U7 and U10 for the new text, U8 for the office and
pick tabs (320, 390 and 1280 px, light and dark). Fake money only: the fixtures are hand-made docs, nothing is fetched.

  python3 selftest_office.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  selftest.main: office_checks(check, SKIPS) after spotter_checks (WP6 hooks it in)

node and Playwright follow selftest.py's rules: a missing one is a skipped group, named on the last line.
"""
import datetime as dt, glob, json, os, random, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PY = sys.executable
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
H, MIN = 3_600_000, 60_000
NOW = int(dt.datetime(2026, 10, 13, 18, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)    # 20:30 Berlin
PAGES = "https://some-owner.github.io/Meme-Bot/"
REPO = "Some-Owner/Meme-Bot"
AGENTS = ("dispatch", "trainer", "scouts", "candles", "market", "analyst", "safety", "refresh", "trader", "reporter")
XSS = "<img src=x onerror=alert(1)>"
LONG_OUT = "fresh prices for 14 candidates from DexScreener, 2 of them moved more than 30% since the gates ran"
RADAR_AGENT = ("Launch radar", "rates every coin whose pool is under 10 minutes old in one quick round after each scan, in its own job; only coins without traps are shown and pushed",
               ("DexScreener", "pump.fun", "GeckoTerminal", "Jupiter", "RugCheck", "Solana RPC", "LaunchLab"))     # SPEC 5 WP5c, verbatim


def b58(rng):
    return "".join(rng.choice(ALPH) for _ in range(40)) + "pump"


def wj(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)


def radar_doc(t, state="running", **kw):
    """radar.json as Appendix A has it (the parts the office reads, and some it does not)."""
    doc = {"v": 1, "kind": "radar", "t": t, "next": t + 150_000, "run": {"id": 7, "start": t - 30 * MIN, "end": t + 25 * MIN, "cycle": 14, "source": "chain"},
           "state": state, "why": "", "secs": 63.2, "model": {"from": "prior", "n": 212, "need": 300}, "counts": {"seen": 7, "good": 1, "pushed": 0, "seenAgeMed": 3.1},
           "coins": [], "others": [], "lastGood": None, "recent": [], "record": {"calls": 37},
           "hosts": {"dexscreener": "ok", "rugcheck": "limited", "pump.fun": "ok", "geckoterminal": "ok", "rpc": "ok", "jupiter": "ok", "launchlab": "ok"},
           "notes": ["RugCheck limited: 2 coins not fully checked"], "lines": ["cycle 14: 7 seen, 1 without traps, 0 pushed (63 s)"]}
    doc.update(kw)
    return doc


def desk_doc(t, rng=None, **kw):
    """radar.json of a round with the desk's numbers: discovery counts (src), the live feed, one coin pushed this round, six with traps or
    unchecked (red flags: creator sold 3 times, RugCheck danger twice), a coin in both lists (counted once)."""
    rng = rng or random.Random(4)
    good = {"addr": b58(rng), "sym": "PEPE2", "v": "good", "hard": [], "push": t}
    others = [{"addr": b58(rng), "sym": "T%d" % i, "v": v, "hard": h} for i, (v, h) in enumerate((
        ("trap", ["creator_sold", "rc_danger"]), ("trap", ["creator_sold"]), ("trap", ["rugger_wallets", "creator_sold", "creator_sold"]), ("trap", ["rc_danger"]),
        ("watch", []), ("watch", [])))]
    return radar_doc(t, **dict({"next": t + 120_000, "counts": {"seen": 7, "good": 1, "pushed": 1, "seenAgeMed": 2.0}, "coins": [good, others[4]], "others": others,
                                "src": {"gt:new": 40, "pf:graduated": 180, "jup:recent": 30, "pf:new": 30, "list:profiles": 12},
                                "hosts": {"dexscreener": "ok", "rugcheck": "ok", "pumpportal": "ok"}, "lastGood": {"addr": good["addr"], "sym": "PEPE2", "at": t}}, **kw))


def round_doc(t, **kw):
    """radar.json after one round of the hourly radar (launch_radar.py round): state done, the next round in 55 minutes, run.mode round."""
    return radar_doc(t, **dict({"state": "done", "next": t + 55 * MIN, "hourly": t, "run": {"id": 8, "start": t - 2 * MIN, "end": None, "cycle": 1, "source": "hourly", "mode": "round"}}, **kw))


def mk_db(d, now=NOW, radar=None, run_min=(41, 42, 40, 43, 39, 41), agents=AGENTS, spotter=False):
    """A recommend-mode db with an office.json of the last run, its memeruns and (optional) mb/radar_live.json."""
    import memebot as M
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    runs = []
    for k, m in enumerate(run_min):          # the newest first: the run that made this page started at minute run_min[0]
        t = int(dt.datetime.fromtimestamp(now / 1000 - k * 3600, dt.timezone.utc).replace(minute=m, second=12, microsecond=0).timestamp() * 1000)
        t = t if t <= now else t - H
        runs.append(t)
        wj(os.path.join(d, "db", "memeruns", dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M") + ".json"), {"t": t, "mode": "pick", "rule": M.RULE})
    t0 = runs[0] if runs else now - 25 * MIN
    wj(os.path.join(d, "db", "memebot", "state.json"), {"lastRun": t0, "runs": 12})
    wj(os.path.join(d, "db", "memebot", "recommend.json"), {"t": t0, "rule": M.RULE, "picks": [], "reason": "nothing passed the gates"})
    ags, s = [], t0
    for i, a in enumerate(list(agents) + (["spotter"] if spotter else [])):
        bg = a in ("trainer", "candles", "spotter")
        e = s + (40 + 13 * i) * 1000
        ags.append({"id": a, "start": s, "end": e, "status": "done", "bg": bg, "lines": ["%s line one" % a, "%s: 12 of 40 done" % a], "out": "%s result <b>%d</b>" % (a, i)})
        if a == "market":         # no result line, its latest telling line a warning: the card shows it without the "! " mark
            ags[-1].update(out="", lines=["market line one", "! DexScreener slow: 3 of 40 pairs retried", "saved 4 docs"])
        if a == "refresh":        # a result longer than a card's one line
            ags[-1]["out"] = LONG_OUT
        s = s if bg else e
    ags[-1]["end"], ags[-1]["status"] = None, "running"          # the reporter writes this page
    wj(os.path.join(d, "db", "memebot", "office.json"), {"v": 1, "t": t0, "end": s + 5000, "mode": "full", "agents": ags})
    wj(os.path.join(d, "db", "memebot", "train.json"), {"rows": 185627, "scans": 158, "zeros": 1300})
    if radar is not None:
        wj(os.path.join(d, "radar_live.json"), radar)
    return runs


def mk_launches(d, now, standout=False, seed=5, n14=6):
    """Seven days of early-list records (db/memeearly), 6 coins an hour, 40% dead within the hour; with standout, 14:00 Berlin has none dead
    (n14 coins at 14:00)."""
    import report as R
    rng = random.Random(seed)
    start = now - 7 * 24 * H + H
    t = start - start % H
    k = 0
    while t + 10 * MIN <= now - 2 * H:            # every hour of the week that has its 1 h price
        hb = R.local(t).hour
        coins = []
        for j in range(n14 if hb == 14 else 6):
            dead = (j in (0, 1) or (j == 2 and k % 2 == 0)) and not (standout and hb == 14)     # 2.5 of 6 = 42%
            coins.append({"addr": b58(rng), "sym": "C%d" % j, "px": 1.0, "liq": 20000.0, "born": t + j * MIN, "ageMin": 5,
                          "p60": {"px": 0.04 if dead else 1.3, "liq": 300.0 if dead else 21000.0, "t": t + H}})
        rid = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")
        wj(os.path.join(d, "db", "memeearly", rid + ".json"), {"v": 1, "t": t + 10 * MIN, "id": rid, "coins": coins})
        t += H
        k += 1


def build(d, now=NOW, repo=None):
    env = dict(os.environ)
    env.pop("GITHUB_REPOSITORY", None)
    if repo:
        env["GITHUB_REPOSITORY"] = repo
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", d, "--now", str(now)], capture_output=True, text=True, env=env)
    return open(os.path.join(d, "report.html"), encoding="utf-8").read() if r.returncode == 0 else "EXIT %d %s" % (r.returncode, r.stderr[-800:])


def plat(page, key):
    """The first (wide) floor plan's platform of a department, up to the next platform."""
    i = page.find('<g class="plat k-%s"' % key)
    return page[i:page.find('<g class="plat', i + 10)] if i >= 0 else ""


def cut(page, start, end):
    i = page.find(start)
    j = page.find(end, i + len(start)) if i >= 0 else -1
    return page[i:j + len(end)] if i >= 0 and j >= 0 else ""


def office_checks(check, skips=None):
    skips = skips if skips is not None else []
    import memebot as M
    import report as R
    import page_office as PO
    tmp = tempfile.mkdtemp(prefix="memebot-office5c-")
    utc = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M")
    try:
        # ---------------------------------------------------------------- U6: the radar desk first, one card per agent, office.json unchanged
        d1 = os.path.join(tmp, "o1")
        mk_db(d1, radar=radar_doc(NOW - 26 * MIN))
        off_before = open(os.path.join(d1, "db", "memebot", "office.json"), "rb").read()
        page = build(d1)
        off_after = open(os.path.join(d1, "db", "memebot", "office.json"), "rb").read()
        cards = re.findall(r'<label class="ocard( ext)?" for="od-([a-z]+)" data-agent="([a-z]+)"', page)
        D1 = R.collect(d1, NOW)
        info = R.office_data(D1)
        pane_o = page[page.find('<div class="pane" id="pane-office">'):]
        check(off_before == off_after and [c[2] for c in cards] == list(AGENTS) and not any(c[0] for c in cards) and 'data-agent="radar"' not in cut(page, '<div class="ocards"', "</div>")
              and [a["id"] for a in info["agents"]] == list(AGENTS) and [a["id"] for a in info["ext"]] == ["radar"] and "could not be rendered" not in page
              and R.OFFICE_AGENTS["radar"] == RADAR_AGENT and (info["ext"][0]["name"], info["ext"][0]["job"], tuple(info["ext"][0]["tools"])) == RADAR_AGENT
              and pane_o.startswith('<div class="pane" id="pane-office"><style>') and pane_o.find("</style>") + 8 == pane_o.find('<label class="odesk" for="tab-young" data-po-desk')
              and -1 < pane_o.find('<label class="odesk"') < pane_o.find("<h2>Agent office</h2>") < pane_o.find('<div class="ocards"') < pane_o.find('<div class="office">')
              and page.count('<label class="odesk"') == 1 and "data-ext-stat" not in page and "ocard ext" not in page + PO.CSS,
              "U6 office: the Launch radar's desk is the first block of the Office tab (before its heading and the grid); one card per agent of office.json "
              "in run order and no card for the radar any more; the radar's name, job and tools are the spec's words; office.json is not written (%d cards)" % len(cards))
        card_dept = dict((c[2], c[1]) for c in cards)
        card_line = lambda aid: R.html.unescape(re.search(r'<label class="ocard[^"]*" for="od-[a-z]+" data-agent="%s".*?<span class="ocl"[^>]*>(.*?)</span>' % aid, page, re.S).group(1))
        lines_ = {aid: card_line(aid) for aid in ("refresh", "market", "candles")}
        check(card_dept.get("trainer") == "brain" and card_dept.get("dispatch") == "ops" and card_dept.get("safety") == "safety" and card_dept.get("deep") is None
              and "result &lt;b&gt;3" in page and "result <b>3" not in page and 'data-live-chip="analyst"' in cut(page, '<div class="ocards"', '</div>')
              and 'data-live-chip="radar"' not in page and lines_["candles"] == "candles result <b>3</b>"
              and len(lines_["refresh"]) <= 60 and lines_["refresh"] == PO.clip(LONG_OUT, 60) and lines_["refresh"].endswith("…") and LONG_OUT.startswith(lines_["refresh"][:-1])
              and lines_["market"] == "DexScreener slow: 3 of 40 pairs retried"
              and len(re.findall(r'data-live-line="[a-z]+" data-live-max="60"', cut(page, '<div class="ocards"', '</label></div>'))) == len(AGENTS),
              "U6 office: each card is the label of its department, carries the live hooks (not the radar's, the live line capped at 60), its text escaped, "
              "one line of at most 60 characters, a warning without its '! ' mark (%s)" % lines_)
        # the GROKBOT + JEV layout (wp8b): the cards and the paper account's line on top, no intro paragraph there, everything else of the
        # office in ONE Details fold that is closed in the HTML (the counts, the note, the floor plan, the legend, the panels with the daily
        # overview, the team timeline); the line is the paper account's P/L after every run, the number now on top
        f0 = page.find('<details class="fold ofold" data-po-fold')
        top_ = page[page.find('<h2>Agent office</h2>'):f0]
        fold_ = cut(page, '<details class="fold ofold" data-po-fold', "</section>")
        inside = ("data-static-strip", "Tap a department to see what its agents did.", '<div class="office">', 'class="chart-svg ofl"', 'class="legend olegend"',
                  '<div class="card opanel k-analysts">', '<div class="oday">', "<h3>Team timeline</h3>", '<div class="oagent oext" data-agent="radar" data-ext="radar">')
        dB = os.path.join(tmp, "bal")
        mk_db(dB, radar=radar_doc(NOW - 26 * MIN))
        for k_, (dh, v_) in enumerate(((-3, -2.0), (-2, 5.0), (-1, 3.5))):
            wj(os.path.join(dB, "db", "memecurve", "c%d.json" % k_), {"t": NOW + dh * H, "bot": 0.0, "paper": {"invested": 50.0, "back": 0.0, "open": 50.0 + v_, "pnl": v_, "n": 1}})
        DB = R.collect(dB, NOW)
        bal, bal0 = PO.balance(DB, R), PO.balance(D1, R)
        pageB = build(dB)
        bal_d = re.search(r'<path class="l" d="([^"]*)"', bal)
        check(f0 > 0 and page[f0:page.find(">", f0) + 1] == '<details class="fold ofold" data-po-fold>' and page.count('<details class="fold ofold" data-po-fold') == 1
              and '<div class="otop"><div class="ocards"' in top_ and top_.find('<div class="ocards"') < top_.find('<div class="obal') and '<p class="note"' not in top_
              and all(x_ in fold_ and page.find(x_) > f0 for x_ in inside) and fold_.count('<label class="ocard') == 0
              and "<summary><span class=\"t\">Details</span>" in fold_,
              "office layout: the cards and the paper account's line on top with no intro paragraph; the counts, the note, the floor plan, the "
              "legend, the panels (the radar's desk, the daily overview) and the team timeline in ONE Details fold, closed in the HTML")
        check(bal_d and bal_d.group(1).count("L") == 2 and bal_d.group(1).startswith("M0.0 ") and "Paper account" in bal and PO._eur(DB["paper"]["acct"]["pnl"], True) in bal
              and 'class="obal ' in pageB and pageB.find('<div class="ocards"') < pageB.find('<div class="obal') < pageB.find('<details class="fold ofold" data-po-fold') and "the line starts after two runs" in bal0
              and PO._eur(-633.14, True) == "\u2212633.14\u00a0€" and PO._eur(5, True) == "+5.00\u00a0€" and PO.balance(dict(DB, rec=None), R) == "",
              "office balance line: the paper account's P/L after every run since the restart (3 runs: 3 points), the number now on top, under the "
              "cards and above the fold; before two runs a short note; none outside recommend mode")
        # the radar is never in a light, the timeline, the counts or "at once": the same office with no agent in its own job at all (ext_agents
        # returns nothing, not even the radar's "not started yet") has the same timeline, run line, head and lights; "at once" is also counted here
        d0 = os.path.join(tmp, "o0")
        mk_db(d0)
        page0 = build(d0)
        tl = lambda p: cut(p, "<h3>Team timeline</h3>", "</details>")
        strip_ = lambda p: cut(p, '<div class="ostrip" data-lv data-static-strip>', "</div>")
        head = lambda p: cut(p, '<div class="sec-head"><h2>Agent office</h2>', "</div>")
        ext_fn = PO.ext_agents
        PO.ext_agents = lambda *a_, **k_: []
        try:
            info_x, sec_x = R.office_data(D1), R.office_section(D1)
        finally:
            PO.ext_agents = ext_fn
        o_ags = json.load(open(os.path.join(d1, "db", "memebot", "office.json")))
        ev = sorted([(x["start"], 1) for x in o_ags["agents"]] + [(x["end"] or o_ags["end"], -1) for x in o_ags["agents"]])
        at_once = max(sum(k for _, k in ev[:i + 1]) for i in range(len(ev)))
        lights = lambda inf: [(x["key"], x["light"], x["word"]) for x in inf["depts"] + [inf["brain"]]]
        an1, an0 = plat(page, "analysts"), plat(page0, "analysts")
        check(tl(page) == tl(sec_x) != "" and strip_(page) == strip_(sec_x) != "" and head(page) == head(sec_x) != "" and "Launch radar" not in tl(page)
              and info["peak"] == info_x["peak"] == at_once > 1 and "%d agents · " % len(AGENTS) in head(page) and "up to %d at work at once" % at_once in head(page)
              and lights(info) == lights(info_x) and next(x for x in info["depts"] if x["key"] == "analysts")["light"] == "done"
              and an1.count('class="desk') == 2 and an0.count('class="desk') == 2 and 'data-agents="analyst"' in an1,
              "U6 office: the radar's desk sits on Analysts (2 desks) and never changes the timeline, the counts (%d agents, up to %d at once), the run "
              "line or a department's light: the same as with no agent in its own job" % (len(AGENTS), at_once))
        rings = re.findall(r'<g class="plat k-([a-z]+)"', cut(page, '<div class="wide"><div class="ofloor">', "</svg>"))
        rings_n = re.findall(r'<g class="plat k-([a-z]+)"', cut(page, '<div class="narrow"><div class="ofloor">', "</svg>"))
        d2 = os.path.join(tmp, "o2")
        mk_db(d2, radar=radar_doc(NOW - 26 * MIN), spotter=True)
        page2 = build(d2)
        check(len(info["depts"]) == 8 and len(rings) == 8 and len(rings_n) == 8 and plat(page2, "scouts").count('class="desk') == 3
              and re.search(r'<g class="plat hub k-brain"', page) and 'data-agent="radar" data-ext="radar"' in page,
              "U6 office: the ring keeps exactly 8 departments (wide and phone), Scouts keep 3 desks with the spotter, the radar's desk is marked data-ext")
        desk = re.search(r'<g class="desk( off)?" data-agent="radar" data-ext="radar">.*?</g>', page, re.S)
        check(desk and not desk.group(1) and "own job" in desk.group(0) and "beside" not in desk.group(0) and 'class="scr "' in desk.group(0)
              and ">running<" in page and "on watch" not in page and "7 seen · 1 without traps · 0 pushed" in page and ">checked %s<" % R.local(NOW - 26 * MIN).strftime("%H:%M") in page
              and "RugCheck · limited" in page and "RugCheck limited: 2 coins not fully checked" in page
              and '<span class="odk-dot running" data-pd-dot aria-hidden="true"></span><b>Launch radar</b><span class="odk-w" data-pd-word>running</span>' in page
              and '>every 2.5 min · last %s · next %s<' % (R.local(NOW - 26 * MIN).strftime("%H:%M"), R.local(NOW - 26 * MIN + 150_000).strftime("%H:%M")) in page,
              "U6 office: a radar loop that ran at the start of this scan is 'running' with its counts, hosts and notes on its floor desk and panel (its pill reads "
              "'own job'), and on the desk on top with its cadence, last and next round")
        # its state at the scan's start (the copy is made then; the page comes about 25 minutes later), as MB.radarState names them
        sts = []
        for age, kw in ((5 * MIN, {}), (7 * MIN, {}), (20 * MIN, {}), (60_000, {"state": "off"}), (60_000, {"state": "hours", "next": NOW + H}),
                        (90 * MIN, {"state": "hours", "next": NOW - 70 * MIN})):
            dd = os.path.join(tmp, "st%d" % len(sts))
            wj(os.path.join(dd, "radar_live.json"), radar_doc(NOW - age, **kw))
            sts.append(PO.radar_state(PO.radar_doc(dd), NOW))
        check(sts == ["running", "late", "stopped", "off", "hours", "stopped"] and PO.radar_state(None, NOW) == "none",
              "U6 radar desk states at a time: running, late, stopped, off, hours (and stopped once past its next start), none (%s)" % sts)
        l5 = [PO.radar_state({"t": NOW - a_ * MIN, "next": NOW - (a_ - 5) * MIN, "state": "running"}, NOW) for a_ in (8, 12, 16)]
        check(l5 == ["running", "late", "stopped"],
              "U6 radar desk, the loop every 5 minutes: running for 2 of its own cycles and a minute (8 min old), late to 15, then stopped, as the New tab (%s)" % l5)
        # the hourly radar's rounds: done until doc.next + 30 min (an hour after the round without a next), late one more hour, then stopped;
        # a failed round (degraded) is done too, never a loop's 'running' or 'stopped' after 15 minutes
        rsts = [PO.radar_state(PO.radar_clean(doc_), NOW) for doc_ in (round_doc(NOW - 50 * MIN), round_doc(NOW - 84 * MIN), round_doc(NOW - 86 * MIN), round_doc(NOW - 146 * MIN),
                                                                       round_doc(NOW - 80 * MIN, next=None), round_doc(NOW - 20 * MIN, state="degraded"), radar_doc(NOW - 20 * MIN, state="done", next=NOW + 35 * MIN))]
        check(rsts == ["done", "done", "late", "stopped", "done", "done", "done"],
              "U6 radar desk, the hourly radar: done from doc.next until 30 min past it (an hour after the round without a next), late for an hour more, "
              "then stopped; a failed round is done too (%s)" % rsts)
        lr = PO.look("done", PO.radar_clean(round_doc(NOW - 20 * MIN)), utc)
        ld = PO.look("done", PO.radar_clean(round_doc(NOW - 20 * MIN, state="degraded")), utc)
        check((lr["light"], lr["word"], lr["line"], lr["checked"], lr["until"], lr["here"]) == ("done", "done", "7 seen · 1 without traps · 0 pushed", "last round %s" % utc(NOW - 20 * MIN),
                                                                                            " · next about %s" % utc(NOW + 35 * MIN), True)
              and (ld["light"], ld["word"]) == ("fallback", "last round had errors") and ld["line"].startswith("checks failing · ") and PO.CHIP["done"] == "good",
              "U6 radar card and panel between rounds: done (green) with its counts, 'last round HH:MM · next about HH:MM'; a failed round amber, 'last round had errors' (%s)" % [lr, ld["word"]])
        # the next round after a round, at a time: past doc.next it is due since then; a round with next null (a round by hand long after the scan's
        # last one, radar-data on 14.10) names the full scan that starts the next one (the strip's estimate), else the next full scan
        rn0 = PO.radar_clean(round_doc(NOW - 20 * MIN, next=None))
        uw = [PO.look("done", PO.radar_clean(round_doc(NOW - 70 * MIN)), utc, NOW)["until"], PO.look("done", rn0, utc, NOW, NOW + 30 * MIN)["until"],
              PO.look("done", rn0, utc, NOW, NOW - 80 * MIN)["until"], PO.look("done", rn0, utc, NOW)["until"], PO.look("late", rn0, utc, NOW, NOW + 30 * MIN)["until"]]
        check(uw == [" · next due since %s" % utc(NOW - 15 * MIN), " · next after the %s scan" % utc(NOW + 30 * MIN), " · next after the %s scan" % utc(NOW - 20 * MIN),
                     " · next after the next full scan", ""],
              "U6 radar card between rounds: once doc.next has passed 'next due since HH:MM'; with next null the full scan that starts the next round "
              "(the strip's estimate, an hour on once that scan should be over), else 'next after the next full scan'; late says nothing of a next (%s)" % uw)
        # what the card and the panel say in each state: a late or stopped radar leads with that word (its counts are its last check's) in the
        # Radar tab's colours (amber, red), a degraded one says checks fail, one that never ran is "not started yet"
        rd = PO.radar_clean(radar_doc(NOW - 20 * MIN))
        lk = {s_: PO.look(s_, rd, utc) for s_ in ("running", "late", "stopped")}
        lk["degraded"] = PO.look("running", PO.radar_clean(radar_doc(NOW, state="degraded")), utc)
        lk["none"] = PO.look("none", None, utc)
        check([(v["light"], v["line"]) for v in lk.values()] == [
            ("running", "7 seen · 1 without traps · 0 pushed"), ("fallback", "late · 7 seen, 1 without traps"),
            ("failed", "stopped · 7 seen, 1 without traps"), ("fallback", "checks failing · 7 seen · 1 without traps · 0 pushed"),
            ("skipped", "not started yet")] and lk["stopped"]["stat"] == utc(NOW - 20 * MIN) and lk["stopped"]["checked"] == "checked %s" % utc(NOW - 20 * MIN) and lk["none"]["stat"] == "own job" and lk["late"]["until"] == ""
              and lk["stopped"]["until"] == "" and PO.CHIP["failed"] == "bad",
              "U6 radar card: late and stopped lead with that word (amber, red: the radar's colours), degraded says checks fail, none is 'not started yet', no 'this run until' (%s)" % (
                  [v["line"] for v in lk.values()],))
        # switched off (or outside its hours, or never started): the panel drops the last check's notes and services, the wiring stays
        panels = {}
        for k_, doc_ in (("off", radar_doc(NOW - 60_000, state="off")), ("run", round_doc(NOW - 60_000))):
            dd = os.path.join(tmp, "pn-" + k_)
            wj(os.path.join(dd, "radar_live.json"), doc_)
            panels[k_] = PO.ext_panel(PO.ext_agents({"dir": dd, "runs": D1["runs"], "now": NOW}, R.office_meta, R)[0], R)
        check("omsg warn" not in panels["off"] and 'data-ext-hosts="radar" hidden></div>' in panels["off"] and '<p class="note" data-ext-wired="radar">Wired to DexScreener' in panels["off"]
              and "RugCheck limited: 2 coins" in panels["run"] and "RugCheck · limited" in panels["run"] and 'data-ext-wired="radar" hidden>' in panels["run"]
              and 'data-ext-until="radar"> · next about %s</span> · one round after each scan</p>' % R.local(NOW + 54 * MIN).strftime("%H:%M") in panels["run"]
              and '>last round %s<' % R.local(NOW - 60_000).strftime("%H:%M") in panels["run"] and 'data-ext-until="radar"></span>' in panels["off"]
              and not any(x_ in panels["run"] + panels["off"] for x_ in ("2½", "this run until", "on watch")) and 'for="tab-young">Open the radar</label>' in panels["run"],
              "U6 radar panel: switched off, it shows no old notes or service chips (the wiring instead) and no next round; between rounds, its notes, services, "
              "'last round HH:MM · next about HH:MM · one round after each scan' and the link to the radar on New")
        bad = os.path.join(tmp, "bad")
        wj(os.path.join(bad, "radar_live.json"), {"kind": "radar", "t": "soon", "counts": {"seen": "x"}})
        wj(os.path.join(bad, "x", "radar_live.json"), dict(radar_doc(NOW), counts={"seen": float("inf"), "good": "2", "pushed": None}, lines=[XSS, 5, None], hosts={"a" * 90: "ok", "rpc": 3}))
        wj(os.path.join(bad, "y", "radar_live.json"), dict(radar_doc(NOW), next=1e300, run={"end": -5, "start": "x"}))
        wild = PO.radar_doc(os.path.join(bad, "y"))
        weird = PO.radar_doc(os.path.join(bad, "x"))
        check(PO.radar_doc(bad) is None and PO.radar_doc(os.path.join(tmp, "nowhere")) is None and weird["counts"]["seen"] is None and weird["lines"] == [XSS]
              and list(weird["hosts"]) == ["a" * 40] and wild["next"] is None and wild["run"]["end"] is None and PO.radar_clean(dict(radar_doc(NOW), t=1e19)) is None,
              "a malformed radar_live.json is dropped (no time, or a wild one) or cut to finite numbers, times that are times, strings and the known keys")
        # ---------------------------------------------------------------- the radar desk on top of the Office tab
        dk_t = NOW - 26 * MIN
        dk = PO.radar_clean(desk_doc(dk_t))
        v_run = PO.desk_look("running", dk, dk_t + 60_000, utc)
        check(v_run["st"] == [["src", "Sources", [["", "292"]], "live feed on · pf:graduated 180 · gt:new 40 · jup:recent 30"],
                              ["chk", "Checks", [["", "7"]], "red flags: creator sold 3 · RugCheck danger 2"],
                              ["vd", "Verdicts", [["good", "1"], ["warn", "2"], ["bad", "4"]], "no trap · watch · trap"], ["push", "Push", [["", "1"]], "PEPE2 pushed"]]
              and (v_run["light"], v_run["word"], v_run["meta"], v_run["quiet"], v_run["dim"]) == ("running", "running", "every 2 min · last %s · next %s" % (utc(dk_t), utc(dk_t + 120_000)), False, False),
              "radar desk stations: Sources = all the discovery lists' coins (292) with the live feed and the top 3 lists (a tie by name), Checks = the coins "
              "checked with the round's 2 most frequent red flags in words (a flag twice on one coin counts once), Verdicts no trap / watch / trap (a coin in "
              "both lists once), Push = the coin pushed this round; the line 'every 2 min · last · next' (%s)" % v_run)
        dsk = lambda st_, doc_, at: PO.desk_look(st_, PO.radar_clean(doc_) if doc_ else None, at, utc)
        rd_ = round_doc(NOW - 20 * MIN)
        words = [(x["light"], x["word"], x["meta"], x["quiet"], x["dim"]) for x in (
            dsk("running", desk_doc(dk_t), dk_t + 120_000 + 10_000), dsk("running", desk_doc(dk_t), dk_t + 120_000 + 11_000), dsk("running", desk_doc(dk_t), dk_t + 120_000 + 181_000),
            dsk("late", desk_doc(dk_t), dk_t + 8 * MIN), dsk("stopped", desk_doc(dk_t), dk_t + 20 * MIN), dsk("done", rd_, NOW), dsk("done", rd_, rd_["next"] + 60_000),
            dsk("done", rd_, rd_["next"] + 5 * MIN), dsk("hours", radar_doc(NOW, state="hours", next=NOW + 5 * H), NOW), dsk("off", radar_doc(NOW, state="off"), NOW),
            dsk("none", None, NOW), dsk("running", desk_doc(dk_t, state="degraded"), dk_t + 60_000), dsk("done", round_doc(NOW - 20 * MIN, state="degraded"), NOW))]
        check(words == [("running", "running", "every 2 min · last %s · next %s" % (utc(dk_t), utc(dk_t + 120_000)), False, False),
                        ("running", "round in progress", "every 2 min · last %s" % utc(dk_t), False, False), ("running", "running", "every 2 min · last %s · next %s" % (utc(dk_t), utc(dk_t + 120_000)), False, False),
                        ("fallback", "late", "every 2 min · last %s" % utc(dk_t), False, True), ("failed", "stopped", "last %s" % utc(dk_t), False, True),
                        ("done", "sleeping until %s" % utc(NOW + 35 * MIN), "last %s" % utc(NOW - 20 * MIN), False, False), ("running", "round in progress", "last %s" % utc(NOW - 20 * MIN), False, False),
                        ("done", "sleeping", "last %s" % utc(NOW - 20 * MIN), False, False), ("skipped", "sleeping until %s" % utc(NOW + 5 * H), "last %s" % utc(NOW), True, False),
                        ("skipped", "off", "last %s" % utc(NOW), True, False), ("skipped", "not started yet", "", True, False),
                        ("fallback", "rounds failing", "every 2 min · last %s · next %s" % (utc(dk_t), utc(dk_t + 120_000)), False, True),
                        ("fallback", "last round failed", "last %s · next %s" % (utc(NOW - 20 * MIN), utc(NOW + 35 * MIN)), False, True)],
              "radar desk states: running; 'round in progress' from 10 s past the doc's next round for 3 minutes (then the radar's own rules again); late and "
              "stopped show the last round dimmed; a round between rounds 'sleeping until HH:MM'; outside its hours, off and never started hide the stations; "
              "failing rounds amber and dimmed (%s)" % words)
        # the doc the radar really writes while its cycles fail (launch_radar.degraded: finish_from drops the list and the counts)
        import launch_radar as LR
        deg = LR.finish_from(desk_doc(dk_t - 120_000), "degraded", dk_t, "3 cycles in a row failed", "7", dk_t - 30 * MIN, dk_t + 25 * MIN, "chain", (7, 24))
        deg.update(next=dk_t + 120_000, notes=["3 cycles in a row failed: the list is not current"])
        deg["run"].update(cycle=14, mode="loop")
        deg_r = LR.finish_from(round_doc(NOW - 80 * MIN), "degraded", NOW - 20 * MIN, "the round failed: boom", "8", NOW - 21 * MIN, None, "hourly", (7, 24))
        deg_r.update(next=NOW + 35 * MIN)
        deg_r["run"].update(cycle=0, mode="round")
        v_deg, v_degr = dsk("running", deg, dk_t + 60_000), dsk("done", deg_r, NOW)
        check((v_deg["light"], v_deg["word"], v_deg["dim"], v_deg["quiet"]) == ("fallback", "rounds failing", True, False)
              and v_deg["st"][:3] == [["src", "Sources", [["", "–"]], "no counts yet"], ["chk", "Checks", [["", "–"]], "not checked: rounds failing"],
                                      ["vd", "Verdicts", [["good", "–"], ["warn", "–"], ["bad", "–"]], "no trap · watch · trap"]]
              and v_deg["st"][3] == ["push", "Push", [["", "0"]], "last without traps: PEPE2, 3 min ago"]
              and (v_degr["word"], v_degr["dim"], v_degr["st"][1][3]) == ("last round failed", True, "not checked: last round failed")
              and not any("no coin under 10 min" in x[3] for x in v_deg["st"] + v_degr["st"]),
              "radar desk on launch_radar's real degraded doc (no list, no counts): amber 'rounds failing' (a round: 'last round failed'), the stations "
              "dimmed and 'not checked', never 'no coin under 10 min' (%s | %s)" % (v_deg["st"], v_degr["word"]))
        chips = PO.host_chips({"pumpportal": "limited", "rugcheck": "ok"})
        check("live feed · limited" in chips and "pumpportal" not in chips and dict(PO.HOSTS).get("pumpportal") == "live feed",
              "the radar panel names the pump.fun feed 'live feed', as the desk does (%s)" % chips)
        old = desk_doc(dk_t, coins=[dict(desk_doc(dk_t)["coins"][0], push=dk_t - 34 * MIN)], hosts={"pumpportal": "limited"}, lastGood={"addr": desk_doc(dk_t)["coins"][0]["addr"], "sym": "PEPE2", "at": dk_t - 34 * MIN})
        old.pop("src")
        v_old, v_empty = dsk("running", old, dk_t + 60_000), dsk("running", radar_doc(dk_t, coins=[], others=[], counts={"seen": 0, "good": 0, "pushed": 0}, lastGood=None), dk_t + 60_000)
        check(v_old["st"][0] == ["src", "Sources", [["", "–"]], "live feed limited"] and v_old["st"][3] == ["push", "Push", [["", "0"]], "last without traps: PEPE2, 35 min ago"]
              and dsk("running", dict(old, hosts={}), dk_t)["st"][0][3] == "no counts yet"
              and v_empty["st"][1:] == [["chk", "Checks", [["", "0"]], "no coin under 10 min"], ["vd", "Verdicts", [["good", "0"], ["warn", "0"], ["bad", "0"]], "no trap · watch · trap"],
                                        ["push", "Push", [["", "0"]], "no push"]]
              and dsk("running", desk_doc(dk_t, others=[dict(x, hard=[]) for x in desk_doc(dk_t)["others"]]), dk_t)["st"][1][3] == "no red flags",
              "radar desk with an older radar.json (no src): Sources shows only the live feed's state, else 'no counts yet'; no push this round: the last coin "
              "without traps and how long ago; an empty round: no coin, no push (%s | %s)" % (v_old["st"], v_empty["st"]))
        pd = os.path.join(tmp, "desk")
        mk_db(pd, radar=desk_doc(dk_t))
        pdh = os.path.join(tmp, "deskh")
        mk_db(pdh, radar=radar_doc(NOW - 30 * MIN, state="hours", next=NOW + 5 * H))
        page_d, page_h = build(pd), build(pdh)
        desk_ = lambda p: cut(p, '<label class="odesk"', "</label>")
        strip_tags = lambda h: re.sub(r"\s+", " ", R.html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
        check(strip_tags(desk_(page_d)) == "Launch radar running every 2 min · last %s · next %s Sources 292 live feed on · pf:graduated 180 · gt:new 40 · jup:recent 30 Checks 7 "
                                               "red flags: creator sold 3 · RugCheck danger 2 Verdicts 1 2 4 no trap · watch · trap Push 1 PEPE2 pushed" % (
                                                   R.local(dk_t).strftime("%H:%M"), R.local(dk_t + 120_000).strftime("%H:%M"))
              and '<span class="odk-g" data-pd-g>' in desk_(page_d) and '<span class="odk-g" data-pd-g hidden>' in desk_(page_h) and "sleeping until %s" % R.local(NOW + 5 * H).strftime("%H:%M") in desk_(page_h)
              and 'title="Open the radar on the New tab (fake money only)"' in desk_(page_d)
              and strip_tags(desk_(page0)).startswith("Launch radar not started yet ") and '<span class="odk-g" data-pd-g hidden>' in desk_(page0),
              "radar desk on the page: built from mb/radar_live.json with the same words; outside its hours 'sleeping until HH:MM' without stations; "
              "no radar.json at all: 'not started yet' (%s)" % strip_tags(desk_(page_d)))
        d3 = os.path.join(tmp, "o3")
        mk_db(d3, radar=radar_doc(NOW - 26 * MIN, lines=["cycle 9: " + XSS], notes=[XSS], hosts={XSS: "down"}, why=XSS))
        page3 = build(d3)
        check(XSS not in page3 and "cycle 9: &lt;img src=x onerror=alert(1)&gt;" in page3 and "could not be rendered" not in page3,
              "U10 office: the radar's lines, notes and host names are escaped on the desk's panel")
        # the next-scan estimate: the median start minute of the last 6 runs, the cron minute with fewer than 3
        mk_ms = lambda ms_: [{"t": int(dt.datetime(2026, 10, 13, h_, m_, 5, tzinfo=dt.timezone.utc).timestamp() * 1000)} for h_, m_ in ms_]
        est = [PO.scan_minute(mk_ms([(18, 41), (17, 42), (16, 40), (15, 43), (14, 39), (13, 58), (12, 10)]), 10),
               PO.scan_minute(mk_ms([(18, 58), (17, 59), (16, 1), (15, 2), (14, 0)]), 10), PO.scan_minute(mk_ms([(18, 41), (17, 42)]), 10), PO.scan_minute([], 10)]
        page_live = build(d1, repo=REPO)
        nxt = R.next_scan_ms(NOW, D1["runs"])
        m_nxt = re.search(r'data-next-scan="(\d+)"', page_live)
        hint = "(next: about %s %s)" % (R.local(nxt + 5 * MIN).strftime("%H:%M"), R.TZ_NAME)
        check(est == [41, 0, 10, 10] and nxt == int(dt.datetime(2026, 10, 13, 18, 41, tzinfo=dt.timezone.utc).timestamp() * 1000) and m_nxt and int(m_nxt.group(1)) == nxt
              and "next ≈ %s" % R.local(nxt).strftime("%H:%M") in page and 'data-next="%d"' % nxt in page and "next scan starts about" not in page
              and re.search(r'<div class="meta">updated [^<·]+</div></header>', page)
              and hint in page_live and R.next_scan_ms(NOW) == R.next_scan_ms(NOW, []) == int(dt.datetime(2026, 10, 13, 19, 10, tzinfo=dt.timezone.utc).timestamp() * 1000),
              "U6 next scan: the median start minute of the last 6 memeruns (:41; :58 to :02 wraps to :00) times data-next-scan, the strip and "
              "the early list's hint %s (the header says only when the page was updated: the strip is the one place for the next start); fewer than 3 runs "
              "keep SCAN_MINUTE_UTC (%s)" % (hint, est))
        sstrip = lambda p: cut(p, '<div class="sstrip"', "</details></div>")
        check(sstrip(page) and sstrip(page) == sstrip(page_live) and "last %s" % R.local(D1["runs"][0]["t"]).strftime("%H:%M") in sstrip(page)
              and "Scan now ↗" in sstrip(page) and "data-ss-now" in sstrip(page) and " hidden><span>" in sstrip(page) and "href=" not in sstrip(page)
              and page.find('<div class="sstrip"') < page.find('id="pane-young"'),
              "pick tab: the full scan's strip (last, next, Scan now) sits on the Pick tab and is the same with and without GITHUB_REPOSITORY (the script adds the link)")
        # report.py without page_office.py next to it (selftest.py's spotter stand-in folder copies only bot, memebot, fetch and report): the page as before
        code = os.path.join(tmp, "code")
        os.makedirs(code)
        for n in sorted(os.listdir(HERE)):         # the code (and the other page modules, once merged) without page_office.py
            if n.endswith((".py", ".json")) and n != "page_office.py" and not n.startswith("selftest") and os.path.isfile(os.path.join(HERE, n)):
                shutil.copy(os.path.join(HERE, n), code)
        r = subprocess.run([PY, "-I", os.path.join(code, "report.py"), "--dir", d1, "--out", os.path.join(tmp, "nopo.html"), "--now", str(NOW)], capture_output=True, text=True)
        nopo = open(os.path.join(tmp, "nopo.html"), encoding="utf-8").read() if r.returncode == 0 else ""
        m_old = re.search(r'<div class="meta">updated [^<·]+ · next scan starts about ([^<·]*?)</div>', nopo)     # no strip: the header keeps the next start
        check(nopo and "could not be rendered" not in nopo and 'class="ocard' not in nopo and '<div class="sstrip"' not in nopo and "Daily overview" not in nopo
              and 'data-po-fold open>' in nopo and 'class="otop"' not in nopo
              and 'data-ext="radar"' not in nopo and 'class="odesk"' not in nopo and "<style></style>" not in nopo and 'data-agents="analyst"' in nopo
              and m_old and m_old.group(1) == R.fmt_when(R.next_scan_ms(NOW, []), NOW),
              "report.py without page_office.py builds the page as before it: no cards, strip, overview or radar desk (the office's fold stands open), the "
              "header names the next scan at the cron minute, as the strip is not there (%s)" % (
                  r.stderr[-200:] if r.returncode else m_old and m_old.group(1)))
        names = json.loads(R.html.unescape(re.search(r'data-names="([^"]*)"', page_live).group(1)))
        check("radar" not in names and set(AGENTS) <= set(names) and "all('[data-agent]:not([data-ext])')" in R.OFFICE_LIVE_JS and "all('[data-agent]').forEach" not in R.OFFICE_LIVE_JS,
              "U6 live view: the office poll skips [data-ext] desks and does not count the radar as a scan agent that is 'waiting'")

        # ---------------------------------------------------------------- U9: the daily overview
        d4 = os.path.join(tmp, "flat")
        mk_db(d4)
        mk_launches(d4, NOW)
        x4 = PO.day_data(d4, NOW, R)
        s4 = PO.day_sentence(x4)
        d5 = os.path.join(tmp, "sep")
        mk_db(d5)
        mk_launches(d5, NOW, standout=True)
        x5 = PO.day_data(d5, NOW, R)
        s5 = PO.day_sentence(x5)
        check(s4[1] == "No hour of the day stands out yet." and all(h["side"] is None for h in x4["hours"]) and x4["n7"] > 900
              and s5[1].startswith("Best hour so far: 14:00 (0% dead within an hour; 7-day: ") and [h["h"] for h in x5["hours"] if h["side"]] == [14]
              and "Worst" not in s5[1],
              "U9 daily overview: an even week -> 'No hour of the day stands out yet.'; a week where 14:00 differs in both halves -> that hour is named (%s | %s)" % (s4[1], s5[1]))
        # one more step: a strong hour in only one half of the week is not named
        d6 = os.path.join(tmp, "half")
        mk_db(d6)
        mk_launches(d6, NOW, standout=True)
        for f in glob.glob(os.path.join(d6, "db", "memeearly", "*.json")):
            doc = json.load(open(f))
            if doc["t"] < NOW - 3.5 * 24 * H and R.local(doc["t"]).hour == 14:
                for c in doc["coins"][:3]:
                    c["p60"] = {"px": 0.01, "liq": 100.0, "t": doc["t"] + H}
                json.dump(doc, open(f, "w"))
        x6 = PO.day_data(d6, NOW, R)
        s6 = PO.day_sentence(x6)
        check(s6[1] == "No hour of the day stands out yet." and x6["hours"][14]["rate"] - x6["p7"] < -0.15 and PO._band(x6["hours"][14], x6["p7"]) == "g1",
              "U9 daily overview: an hour that stands out in one half of the week only is not named, and its cell stays light green though it is %d points "
              "under the week (%s)" % (round(100 * (x6["p7"] - x6["hours"][14]["rate"])), s6[1]))
        # an hour needs at least 30 results: 14:00 with none dead in both halves but only 28 results is not named (it would be with no minimum)
        d6b = os.path.join(tmp, "few14")
        mk_db(d6b)
        mk_launches(d6b, NOW, standout=True, n14=4)
        x6b = PO.day_data(d6b, NOW, R)
        min_n = PO.HOUR_MIN_N
        PO.HOUR_MIN_N = 0
        try:
            s6b0 = PO.day_sentence(PO.day_data(d6b, NOW, R))
        finally:
            PO.HOUR_MIN_N = min_n
        check(min_n == 30 and x6b["hours"][14]["n"] == 28 and x6b["hours"][14]["dead"] == 0 and PO.day_sentence(x6b)[1] == "No hour of the day stands out yet."
              and s6b0[1].startswith("Best hour so far: 14:00"),
              "U9 daily overview: an hour is named only with at least 30 results (14:00 with 28, none dead in both halves: not named; %s with no minimum)" % s6b0[1][:30])
        # today's sentence from all three sources, each coin once: dead by any source in any order, the scored list's 0.1x, the early list's $1k
        # pool, the scored list's results matched to their own picks (two picks with one symbol), today against the week, the radar's calls once
        # per coin (two coins that turned good in one cycle share its ms)
        d7 = os.path.join(tmp, "today")
        mk_db(d7)
        rng = random.Random(9)
        a = [b58(rng) for _ in range(13)]
        ty = NOW - 3 * H
        yp = [("A", a[0], 20), ("B", a[1], 30), ("C", a[2], 5), ("D", a[6], 10), ("DUP", a[10], 15), ("DUP", a[11], 16)]
        wj(os.path.join(d7, "db", "memeyoung", "y1.json"), {"t": ty, "rule": M.RULE, "picks": [{"sym": s_, "addr": ad, "ageMin": am, "px": 1.0} for s_, ad, am in yp]
                                                          + [{"sym": "Z", "addr": a[12], "ageMin": 8}],          # no price: memebot.py writes no result for it
                                                          "outs": {"1": {"t": ty + H, "h": 1.0, "picks": [{"sym": "A", "mult": 0.05, "gone": False}, {"sym": "B", "mult": 1.6},
                                                                                                          {"sym": "C", "waiting": True}, {"sym": "D", "mult": 0.3},
                                                                                                          {"sym": "DUP", "mult": 1.4}, {"sym": "DUP", "mult": 0.0, "gone": True}]}}})
        wj(os.path.join(d7, "db", "memeearly", "e1.json"), {"v": 1, "t": ty, "coins": [{"addr": a[1], "px": 1.0, "born": ty - 31 * MIN, "p60": {"gone": True, "t": ty + H}},
                                                                                       {"addr": a[0], "px": 1.0, "born": ty - 19 * MIN, "p60": {"px": 1.3, "liq": 20000.0, "t": ty + H}},
                                                                                       {"addr": a[7], "px": 1.0, "born": ty, "p60": {"px": 1.2, "liq": 500.0, "t": ty + H}},
                                                                                       {"addr": "0xNOT<b>", "px": 1.0, "born": ty, "p60": {"gone": True}}]})
        wj(os.path.join(d7, "db", "memeearly", "e0.json"), {"v": 1, "t": NOW - 30 * H, "coins": [{"addr": a[8], "px": 1.0, "born": NOW - 30 * H - 5 * MIN, "p60": {"px": 1.1, "liq": 9000.0}}]})
        g_ms = NOW - 76 * MIN
        wj(os.path.join(d7, "db", "memeradar", "2026-10-13T17.json"), {"v": 1, "hour": "2026-10-13T17", "t": NOW - 90 * MIN, "coins": {
            a[3]: {"addr": a[3], "pool": NOW - 80 * MIN, "first": NOW - 78 * MIN, "good": g_ms, "out": {"rug1h": False, "win1h": True, "x60": 2.1}},
            a[9]: {"addr": a[9], "pool": NOW - 75 * MIN, "first": NOW - 78 * MIN, "good": g_ms, "out": None},
            a[4]: {"addr": a[4], "pool": NOW - 70 * MIN, "first": NOW - 69 * MIN, "good": None, "out": None},
            a[5]: {"addr": a[5], "pool": NOW - 9 * 24 * H, "first": NOW - 9 * 24 * H, "good": NOW - 9 * 24 * H, "out": {"rug1h": True}}}})
        wj(os.path.join(d7, "db", "memeradar", "2026-10-01T10.json"), {"v": 1, "coins": {b58(rng): {"pool": NOW - 2 * H, "good": NOW - H, "out": {"rug1h": True}}}})   # 12 days old: not read
        x7 = PO.day_data(d7, NOW, R)
        s7 = PO.day_sentence(x7)
        page7 = build(d7)
        coins7 = PO.launches(d7, NOW)[0]
        check(s7[0] == "Today: 11 new launches checked · 4 of 7 with a 1 h result dead within an hour · radar: 2 calls without traps." and x7["n7"] == 8 and x7["p7"] == 0.5
              and [coins7[a[i]]["dead"] for i in (0, 1, 6, 10, 11, 7, 2, 12)] == [True, True, False, False, True, True, None, None]
              and PO.day_sentence(PO.day_data(d4, NOW, R))[0].endswith("radar: no records yet.") and R.E(s7[0]) in page7,
              "U9 daily overview: today's launches once per coin (scored list, early list, radar), dead by any source, the 0.1x and $1k rules, results "
              "matched to their own pick, the week's rate apart from today's, the radar's calls once per coin; docs older than the week are not read (%s)" % s7[0])
        nums7 = re.findall(r"<div><b>([^<]*)</b><span>([^<]*)</span>", cut(page7, '<div class="odn">', '<p class="odsum">'))
        check(nums7 == [("11", "launches today"), ("4 of 7", "dead within 1 h"), ("2", "radar calls without traps")]
              and page7.find('<div class="odn">') < page7.find('<p class="odsum">') < page7.find('<div class="ohb-bar"'),
              "U9 daily overview: three big numbers lead (launches today, dead within 1 h, radar calls), then the sentences and the bar (%s)" % nums7)
        bar = cut(page7, '<div class="ohb-bar"', "</div>")
        cells = re.findall(r'<label for="ohb-(\d+)" class="([a-z0-9 ]+)"', bar)
        hb = R.local(NOW).hour
        nx = 100.0 * (hb + R.local(NOW).minute / 60.0) / 24
        check(len(cells) == 24 and all("few" in c for _, c in cells) and sum(h["today"] for h in x7["hours"]) == 11 and "today: 7 checked, 3 dead" in page7
              and 'id="ohb-%d" checked' % hb in page7 and re.search(r'class="ohb-day" style="width:%.3f%%".*?class="ohb-now" style="left:%.3f%%"' % (nx, nx), page7)
              and len(re.findall(r'<p class="r\d+">', page7)) == 24 and "#ohb-23:checked ~ .ohb-read .r23" in PO.CSS,
              "U9 hour bar: 24 Berlin hours, hatched under 20 results, today so far outlined, the marker at now, a readout per hour with today's count (CSS, no script)")
        page5 = build(d5)
        bar5 = cut(page5, '<div class="ohb-bar"', "</div>")
        cls5 = dict((int(h_), c.split()) for h_, c in re.findall(r'<label for="ohb-(\d+)" class="([a-z0-9 ]+)"', bar5))
        cls4 = [c.split()[0] for _, c in re.findall(r'<label for="ohb-(\d+)" class="([a-z0-9 ]+)"', cut(build(d4), '<div class="ohb-bar"', "</div>"))]
        check(cls5.get(14, [""])[0] == "g2" and "low" in cls5[14] and all(c[0] in ("mid", "g1", "b1") for h_, c in cls5.items() if h_ != 14)
              and all(("few" in cls5[h["h"]]) == (h["n"] < 20) for h in x5["hours"]) and any(h["n"] >= 20 for h in x5["hours"])
              and len(cls4) == 24 and not set(cls4) & {"g2", "b2"} and "Best hour so far: 14:00" in page5 and '<th class="n">dead 1 h</th>' in page5,
              "U9 hour bar: only an hour the sentence names gets the strong colour and an arrow (14:00 green, ↓); the others stay light or grey, an even week "
              "has no strong cell; hatched exactly where under 20 results; a table view comes with it")

        # ---------------------------------------------------------------- U7: honest words in the new parts
        new_text = " ".join([cut(page, '<div class="ocards"', "</label></div>"), cut(pageB, '<div class="obal', "</svg></div></div>"), cut(page_d, '<label class="odesk"', "</label>"), cut(page, "<summary><span class=\"t\">Details", "</summary>"), cut(page, '<div class="oagent oext"', "Open the radar"), cut(page7, '<div class="oday">', "</details></div>"),
                             sstrip(page), PO.JS, R.OFFICE_AGENTS["radar"][1]]).lower()
        words = [w for w in (r"\bsafe\b", r"\bsafely\b", "guarantee", r"\bbuy\b", "\u2014") if re.search(w, new_text)]
        check(not words and new_text.count("dead within") >= 2, "U7 the new office text never says safe, guaranteed or buy, and has no em dash (%s)" % (words or "none"))

        # ---------------------------------------------------------------- node: the script's decisions, the same words as at build time
        node = shutil.which("node")
        if not node:
            skips.append("the office script's decisions in node (no node)")
            print("  SKIP the office script's decisions in node: node is not installed")
        else:
            cases = [("running", radar_doc(NOW - 60_000)), ("running", radar_doc(NOW - 60_000, state="degraded")), ("late", radar_doc(NOW - 5 * MIN)),
                     ("stopped", radar_doc(NOW - 40 * MIN)), ("off", radar_doc(NOW, state="off")), ("hours", radar_doc(NOW, state="hours", next=NOW + 5 * H)),
                     ("hours", radar_doc(NOW, state="hours", next=None)), ("none", None), ("running", dict(radar_doc(NOW), counts=None)),
                     ("done", round_doc(NOW - 20 * MIN)), ("done", round_doc(NOW - 20 * MIN, state="degraded")), ("late", round_doc(NOW - 100 * MIN)), ("done", round_doc(NOW - 20 * MIN, next=None))]
            cases = [c_ + (None, None) for c_ in cases] + [("done", round_doc(NOW - 70 * MIN), NOW, None), ("done", round_doc(NOW - 20 * MIN, next=None), NOW, NOW + 30 * MIN),
                                                           ("done", round_doc(NOW - 20 * MIN, next=None), NOW, NOW - 80 * MIN), ("done", round_doc(NOW - 20 * MIN, next=None), NOW, None)]
            py = [PO.look(s_, PO.radar_clean(doc_) if doc_ else None, utc, n_, sc_) for s_, doc_, n_, sc_ in cases]
            # the desk on top: the page's doc (radar_clean) and the doc the radar's event carries (page_radar's whitelist) give the build's words
            import page_radar as PRd
            rd0 = round_doc(NOW - 20 * MIN)
            dcases = [("running", desk_doc(dk_t), dk_t + 60_000), ("running", desk_doc(dk_t), dk_t + 131_000), ("late", desk_doc(dk_t), dk_t + 8 * MIN), ("stopped", desk_doc(dk_t), dk_t + 20 * MIN),
                      ("done", rd0, NOW), ("done", rd0, rd0["next"] + 60_000), ("done", round_doc(NOW - 20 * MIN, state="degraded"), NOW), ("hours", radar_doc(NOW, state="hours", next=NOW + 5 * H), NOW),
                      ("off", radar_doc(NOW, state="off"), NOW), ("none", None, NOW), ("running", old, dk_t + 60_000), ("running", radar_doc(dk_t, coins=[], others=[], lastGood=None), dk_t + 60_000),
                      ("running", desk_doc(dk_t, state="degraded"), dk_t + 60_000), ("running", deg, dk_t + 60_000), ("done", deg_r, NOW), ("running", radar_doc(dk_t), dk_t + 30_000)]
            dpy = [PO.desk_look(s_, PO.radar_clean(doc_) if doc_ else None, n_, utc) for s_, doc_, n_ in dcases]
            dj = [[s_, PO.radar_clean(doc_) if doc_ else None, PRd.clean_doc(doc_) if doc_ else None, n_] for s_, doc_, n_ in dcases]
            jd = os.path.join(tmp, "js")
            os.makedirs(jd)
            with open(os.path.join(jd, "t.js"), "w", encoding="utf-8") as f:
                f.write("var L=[];global.window={addEventListener:function(k,f){L.push(k);}};global.document={readyState:'complete',addEventListener:function(k){L.push('doc:'+k);},querySelector:function(){return null;},querySelectorAll:function(){return [];}};\n"
                        + PO.JS + "\nvar O=window.MemebotOffice,f=function(ms){return new Date(ms).toISOString().slice(11,16);},C=%s,o={look:[],scan:[]};\n" % json.dumps(cases)
                        + "C.forEach(function(c){o.look.push(O.look(c[0],c[1],f,c[2],c[3]));});var t=Date.UTC(2026,9,13,18,0),d={t:t,updated:t+600000};\n"
                        + "o.scan=[O.scan('live',d,t-60000,f),O.scan('paused',d,t-60000,f),O.scan('done',d,t-60000,f),O.scan('stopped',d,t-60000,f),O.scan('live',d,t,f),O.scan('hide',d,t-60000,f),O.scan('live',null,0,f)];\n"
                        + "o.next=[O.next(t,t-1,f),O.next(t,t,f),O.next(t,t+3600000,f),O.next(0,t,f)];\n"
                        + "var DK=%s;o.desk=DK.map(function(c){return [O.desk(c[0],c[1],c[3],f),O.desk(c[0],c[2],c[3],f)];});\n" % json.dumps(dj)
                        + "o.events=L;o.hosts=O.hosts;O.radar({state:'off',doc:null});console.log(JSON.stringify(o));\n")
            r = subprocess.run([node, os.path.join(jd, "t.js")], capture_output=True, text=True, timeout=60)
            o = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
            same = o.get("look") == py
            check(same and o.get("scan") == [{"dot": "run", "text": "running now · started 18:00"}, {"dot": "late", "text": "started 18:00 · no update since 18:10"},
                                             {"dot": "ok", "text": "finished 18:10 · new page on its way"}, {"dot": "bad", "text": "stopped 18:10"}, None, None, None]
                  and o.get("next") == ["next ≈ 18:00", "due now (≈ 18:00)", "due now (≈ 18:00)", None]
                  and sorted(o.get("events") or []) == ["doc:click", "memebot-live", "memebot-radar"],
                  "node: the office script says what the page said at build time for every radar state (line, light, a round's 'next about'), the scan strip's live "
                  "words and its 'due now' once the expected start has passed (%s)" % (
                      "same" if same else "%s vs %s" % (o.get("look"), py) if o else r.stderr[-300:]))
            same_d = o.get("desk") == [[x, x] for x in dpy]
            check(same_d and len(dpy) == 16 and dpy[-1]["meta"].startswith("every 2.5 min · ") and o.get("hosts") == [list(x) for x in PO.HOSTS],
                  "node: the desk on top says in the browser what the page said at build time, for every state and doc (launch_radar's degraded docs too), from "
                  "the page's doc and from the radar event's (page_radar's whitelist); the script's host names are the page's (%s)" % (
                      "same" if same_d else "%s vs %s" % (o.get("desk"), dpy) if o else r.stderr[-300:]))

        # ---------------------------------------------------------------- the page in Chromium: live poll, radar event, overflow
        browser_checks(check, skips, d1, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def browser_checks(check, skips, d1, tmp):
    """The office tab in Chromium, served at the website's address; the GitHub API answers a live scan whose doc also names a 'radar' agent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the office's browser checks (no Playwright)")
        print("  SKIP the office's browser checks: Playwright is not installed")
        return
    import report as R
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    page_live = build(d1, repo=REPO)
    # every agent the office knows (the longest names: Launch spotter, Deep searcher, Safety officers), the radar and a week of launches
    dw = os.path.join(tmp, "wide")
    mk_db(dw, radar=radar_doc(NOW - 26 * MIN), agents=AGENTS[:3] + ("deep",) + AGENTS[3:], spotter=True)
    mk_launches(dw, NOW, standout=True)
    page_plain = build(dw)
    dk = os.path.join(tmp, "deskw")
    mk_db(dk, radar=desk_doc(NOW - 26 * MIN, hosts={"pumpportal": "limited"}, others=[dict(x, hard=["holder_cluster", "rugger_wallets", "fund_cluster"])
                                                                                       for x in desk_doc(NOW)["others"]]))
    page_desk = build(dk)
    # "Open the radar" goes to the New tab, where the radar sits on top (the Radar tab is merged into New): one radio of that id, none for Radar
    page_rt = page_plain
    check(page_rt.count('id="tab-young"') == 1 and 'id="tab-radar"' not in page_rt and page_rt.count("data-radar ") == 1,
          "U6 the page has one New tab radio, no Radar tab, and the radar on New (%d)" % page_rt.count('id="tab-young"'))
    t0 = R.office_data(R.collect(d1, NOW))["t0"]
    calls, dialogs, errs = [], [], []
    long_line = "gates: 40 of 900 coins checked against the liquidity, holder and creator rules so far"
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def open_(html_, w=390, h=844, dark=False, live=None):
                ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark" if dark else "light")
                # the live doc is newer than this page's run: the office goes live; Date.now is the page's own clock
                ctx.add_init_script("(function(){var r=Date.now.bind(Date),d=r()-%d;Date.now=function(){return r()-d;};})();" % (NOW + 2 * MIN))

                def handler(route):
                    u = route.request.url
                    if u.startswith(PAGES):
                        route.fulfill(status=200, body=html_, headers={"Content-Type": "text/html; charset=utf-8"})
                    elif u.startswith("https://api.github.com/") and live:
                        calls.append(u)
                        route.fulfill(status=200, body=json.dumps(live), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
                    else:
                        route.abort()
                ctx.route("**/*", handler)
                pg = ctx.new_page()
                pg.on("dialog", lambda d_: (dialogs.append(d_.message), d_.dismiss()))
                pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                pg.goto(PAGES)
                return ctx, pg
            live = {"t": t0 + H, "live": True, "updated": NOW + 2 * MIN - 10_000, "agents": [{"id": "dispatch", "status": "done"}, {"id": "analyst", "status": "running", "lines": [long_line]},
                                                                                         {"id": "radar", "status": "failed"}]}
            ctx, pg = open_(page_live, live=live)
            link = pg.evaluate("(document.querySelector('[data-ss-now]')||{}).href||''")
            # the strip's controls are 44 px tap targets; the ⓘ keeps its place at the right edge when it opens
            taps = pg.evaluate("""() => { const r = e => e.getBoundingClientRect(), a = document.querySelector('[data-ss-now]'), sm = document.querySelector('.sinfo > summary'),
                strip = document.querySelector('.sstrip'), g = () => { const rg = document.createRange(); rg.selectNodeContents(sm); return rg.getBoundingClientRect().right; },
              x0 = g(), h0 = r(strip).height; sm.click(); const x1 = g(); sm.click();
                return [Math.round(r(a).height), Math.round(r(a).width), Math.round(r(sm).height), Math.round(r(sm).width), Math.round(x1 - x0), Math.round(h0)]; }""")
            pg.click('label[for="tab-office"]')
            pg.wait_for_function("!!document.querySelector('.office[data-live]')", timeout=10000)
            got = pg.evaluate("""() => { const q = s => document.querySelector(s), cs = e => getComputedStyle(e);
              return { desk: q('g[data-ext="radar"]').getAttribute('data-live'), card: q('label[data-po-desk]').getAttribute('data-live'),
                panel: q('.oext').getAttribute('data-live'), an: q('g.desk[data-agent="analyst"]').getAttribute('data-live'),
                acard: q('label.ocard[data-agent="analyst"]').getAttribute('data-live'), achip: (q('label.ocard[data-agent="analyst"] [data-live-chip]')||{}).textContent,
                aline: (q('label.ocard[data-agent="analyst"] [data-live-line]')||{}).textContent, pline: (q('.opanel [data-live-line="analyst"]')||{}).textContent,
                astatic: cs(q('label.ocard[data-agent="analyst"] > .ocl:not([data-live-line])')).display, aliveshow: cs(q('label.ocard[data-agent="analyst"] [data-live-line]')).display,
                wait: [q('label.ocard[data-agent="trainer"]').getAttribute('data-live'), cs(q('label.ocard[data-agent="trainer"]')).opacity],
                strip: q('[data-ss-state]').textContent, nexthid: q('[data-ss-next]').hidden,
                fold: q('details[data-po-fold]').open, ashown: q('label.ocard[data-agent="analyst"]').getClientRects().length > 0,
                rline: q('[data-ext-line="radar"]').textContent, rst: window.MemebotRadar && MemebotRadar.last ? String(MemebotRadar.last.state) : null, waiting: Array.from(document.querySelectorAll('[data-live-strip] span')).map(s => s.textContent) }; }""")
            # the radar card's line follows the Radar tab's verdict when that tab's script runs (WP5b: an embedded doc this old is 'stopped'),
            # and the page's own line without it
            rline_for = {None: "7 seen · 1 without traps · 0 pushed", "running": "7 seen · 1 without traps · 0 pushed",
                         "late": "late · 7 seen, 1 without traps", "stopped": "stopped · 7 seen, 1 without traps"}
            check(got["desk"] is None and got["card"] is None and got["panel"] is None and got["an"] == "work" and got["acard"] == "work" and got["achip"] == "at work now"
                  and got["pline"] == "Now: " + long_line and 50 < len(got["aline"]) <= 60 and got["aline"].endswith("…") and ("Now: " + long_line).startswith(got["aline"][:-1])
                  and got["astatic"] == "none" and got["aliveshow"] != "none" and got["wait"] == ["wait", "0.55"] and got["fold"] is False and got["ashown"]
                  and got["rline"] == rline_for.get(got["rst"], "?") and "Waiting %d" % (len(set(R.OFFICE_AGENTS) - {"radar"}) - 2) in got["waiting"]
                  and got["strip"].startswith("running now · started ") and got["nexthid"] and link == "https://github.com/%s/actions/workflows/scan.yml" % REPO,
                  "U6 browser: the office poll marks the scan's desks and cards live but never the radar's (even when the live doc names one); a card at work "
                  "in the grid on top (the Details fold stays closed) shows its live line (at most 60 characters) instead of last run's, a waiting card is faded; the radar's card follows the Radar tab's state when "
                  "that tab runs; the strip says the scan runs now and links to "
                  "the scan's page (%s, %s)" % (got, link))
            # the card at work pulses, but not for a reader who asked for less motion
            pulse = lambda: pg.evaluate("getComputedStyle(document.querySelector('label.ocard[data-agent=\"analyst\"] .olt')).animationName")
            anim = [pulse()]
            pg.emulate_media(reduced_motion="reduce")
            anim.append(pulse())
            pg.emulate_media(reduced_motion="no-preference")
            check(anim == ["opulse", "none"], "U6 browser: the light of a card at work pulses, and stands still with reduced motion (%s)" % anim)
            check(taps[0] >= 44 and taps[1] >= 44 and taps[2] >= 44 and taps[3] >= 44 and abs(taps[4]) <= 2 and taps[5] <= 80,
                  "U8 pick tab: Scan now and the strip's ⓘ are 44 px tap targets in a strip of at most two short rows at 390 px; the ⓘ keeps its place when it opens "
                  "(Scan now %dx%d, ⓘ %dx%d, moved %d px, strip %d px)" % tuple(taps))
            # the Radar tab's script reports: off, then late with new counts, notes and its run's end (and a hostile line), then stopped
            pg.evaluate("""() => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'off', via: 'github', doc: {kind: 'radar', t: Date.now() - 30000, state: 'off',
              notes: ['radar switched off'], hosts: {rugcheck: 'ok'}}}}))""")
            off = pg.evaluate("""() => { const q = s => document.querySelector(s);
              return [q('g[data-ext="radar"]').getAttribute('class'), q('[data-ext-line="radar"]').textContent, q('[data-ext-word="radar"]').textContent,
                q('[data-pd-dot]').getAttribute('class'), q('[data-ext-hosts="radar"]').hidden, q('[data-ext-wired="radar"]').hidden,
                q('[data-ext-notes="radar"]').textContent, q('[data-ext-until="radar"]').textContent]; }""")
            pg.evaluate("""x => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'late', via: 'raw', doc: {kind: 'radar', t: Date.now() - 400000, state: 'running',
              counts: {seen: 9, good: 2, pushed: 1}, lines: ['cycle 20: ' + x], notes: ['RugCheck limited: 4 coins not fully checked'], run: {end: Date.now() + 1200000},
              hosts: {rugcheck: 'down', dexscreener: 'ok'}}}}))""", XSS)
            on = pg.evaluate("""() => { const p = document.querySelector('.oext');
              return [document.querySelector('g[data-ext="radar"]').getAttribute('class'), document.querySelector('g[data-ext="radar"] .scr').getAttribute('class'),
                document.querySelector('[data-ext-line="radar"]').textContent, p.querySelectorAll('img').length, p.querySelector('[data-ext-lines]').textContent,
                p.querySelector('[data-ext-hosts]').textContent, document.querySelector('[data-ext-chip="radar"]').className, p.querySelector('[data-ext-notes]').textContent,
                p.querySelector('[data-ext-until]').textContent, p.querySelector('[data-ext-hosts]').hidden, p.querySelector('[data-ext-wired]').hidden]; }""")
            pg.evaluate("""() => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'stopped', via: 'github', doc: {kind: 'radar', t: Date.now() - 2400000, state: 'running',
              counts: {seen: 4, good: 0, pushed: 0}}}}))""")
            stop = pg.evaluate("""() => [document.querySelector('[data-pd-dot]').getAttribute('class'), document.querySelector('[data-ext-chip="radar"]').className,
              document.querySelector('g[data-ext="radar"] .scr').getAttribute('class'), document.querySelector('[data-ext-line="radar"]').textContent,
              document.querySelector('[data-ext-notes="radar"]').textContent]""")
            # ... and a round (the hourly radar): done, green, its last round and the next one
            pg.evaluate("""() => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'done', via: 'github', good: 0, doc: {kind: 'radar', t: Date.now() - 1200000, state: 'done',
              next: Date.now() + 2100000, run: {mode: 'round', end: null}, counts: {seen: 6, good: 1, pushed: 1}}}}))""")
            done = pg.evaluate("""() => [document.querySelector('g[data-ext="radar"]').getAttribute('class'), document.querySelector('[data-pd-dot]').getAttribute('class'),
              document.querySelector('[data-ext-chip="radar"]').className, document.querySelector('[data-ext-word="radar"]').textContent, document.querySelector('[data-ext-line="radar"]').textContent,
              document.querySelector('[data-ext-checked="radar"]').textContent.replace(/\d\d:\d\d/, 'HH:MM'), document.querySelector('[data-ext-until="radar"]').textContent.replace(/\d\d:\d\d/, 'HH:MM')]""")
            check(off == ["desk off", "switched off on GitHub", "switched off", "odk-dot skipped", True, False, "", ""]
                  and on[:3] == ["desk", "scr fallback", "late · 9 seen, 2 without traps"] and on[3] == 0 and XSS in on[4] and on[5] == "RugCheck · downDexScreener · ok"
                  and on[6] == "chip warn" and on[7] == "RugCheck limited: 4 coins not fully checked" and on[8] == "" and on[9:] == [False, True]
                  and stop == ["odk-dot failed", "chip bad", "scr failed", "stopped · 4 seen, 0 without traps", ""]
                  and done == ["desk", "odk-dot done", "chip good", "done", "6 seen · 1 without traps · 1 pushed", "last round HH:MM", " · next about HH:MM"] and not dialogs,
                  "U6/U10 browser: the radar event moves the desk on top, the floor desk and the panel: off is dark without old notes or services; late is amber with its "
                  "counts and notes (no run end any more); stopped is red; a round between rounds is green, 'last round HH:MM · next about HH:MM'; its lines are "
                  "text, never markup (%s | %s | %s | %s)" % (off, on[:3] + on[6:9], stop, done))
            # the desk on top follows the same event (its numbers from the doc, as the page builds them), says 'round in progress' once the next
            # round is 10 s due without a newer doc (its own clock moves on between two events), and hides its stations when switched off
            read = """() => { const q = s => document.querySelector(s);
              return [q('[data-pd-word]').textContent, q('[data-pd-meta]').textContent.replace(/\\d\\d:\\d\\d/g, 'HH:MM'), q('[data-pd-g]').hidden, q('[data-pd-g]').className,
                Array.from(document.querySelectorAll('[data-pd-g] .odk-s')).map(e => [e.querySelector('.k').textContent, e.querySelector('b').textContent, e.querySelector('.l').textContent])]; }"""
            send = """([st, d, age]) => { const n = Date.now(); d.t = n - age; d.next = d.t + 120000; d.coins[0].push = d.t; d.lastGood.at = d.t;
              window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: st, via: 'github', doc: d, now: n}})); }"""
            pg.evaluate(send, ["running", desk_doc(0), 60_000])
            d_run = pg.evaluate(read)
            pg.evaluate(send, ["running", desk_doc(0), 129_500])
            d_due = pg.evaluate(read)
            pg.wait_for_function("document.querySelector('[data-pd-word]').textContent === 'round in progress'", timeout=15000)
            d_prog = pg.evaluate(read)
            pg.evaluate(send, ["late", desk_doc(0), 8 * MIN])
            d_late = pg.evaluate(read)
            pg.evaluate(send, ["off", dict(desk_doc(0), state="off"), 60_000])
            d_off = pg.evaluate(read)
            check(d_run == ["running", "every 2 min · last HH:MM · next HH:MM", False, "odk-g", [["Sources", "292", "live feed on · pf:graduated 180 · gt:new 40 · jup:recent 30"],
                            ["Checks", "7", "red flags: creator sold 3 · RugCheck danger 2"], ["Verdicts", "124", "no trap · watch · trap"], ["Push", "1", "PEPE2 pushed"]]]
                  and d_due[0] == "running" and d_prog[:2] == ["round in progress", "every 2 min · last HH:MM"] and d_late[:4] == ["late", "every 2 min · last HH:MM", False, "odk-g dim"]
                  and d_off[:3] == ["off", "last HH:MM", True] and not errs,
                  "U6 browser: the desk on top follows the radar event: running with its four stations; 'round in progress' once the next round is 10 s due "
                  "(the desk's own clock moves on); late dims the last round; switched off hides the stations (%s | %s | %s | %s)" % (d_run, d_prog[:2], d_late[:4], d_off[:3]))
            ctx.close()
            # 390 and 1280, light and dark, every fold on the Pick and Office tabs open and every department in turn: nothing wider than the screen;
            # the cards row scrolls inside itself on a phone, wraps on a desktop with whole names; the hour cells are 44 px tall
            sizes = []
            for w, h in ((390, 844), (1280, 900)):
                for dark in (False, True):
                    ctx, pg = open_(page_plain, w, h, dark)
                    m = pg.evaluate("""() => { const over = () => document.documentElement.scrollWidth - innerWidth, s = document.querySelector('.sstrip').getBoundingClientRect();
                      document.getElementById('tab-office').click();
                      const cs = Array.from(document.querySelectorAll('.ocard')), fd = document.querySelector('details[data-po-fold]'), st = e => getComputedStyle(e);
                      const one = c => { const ls = Array.from(c.querySelectorAll(':scope > .ocl')).filter(e => st(e).display !== 'none');
                        return ls.length === 1 && ls[0].getBoundingClientRect().height <= 1.6 * parseFloat(st(ls[0]).fontSize) && st(ls[0]).whiteSpace === 'nowrap' && st(ls[0]).textOverflow === 'ellipsis'; };
                      const dflt = [fd.open, over(), Math.round(fd.getBoundingClientRect().height) < 130 && !document.querySelector('.ofl').checkVisibility() ? 0 : 1, new Set(cs.map(e => Math.round(e.getBoundingClientRect().left))).size,
                        cs.filter(c => !one(c)).map(c => c.getAttribute('data-agent')), cs.length,
                        Math.round(document.querySelector('.obal').getBoundingClientRect().top - document.querySelector('.ocards').getBoundingClientRect().bottom)];
                      document.getElementById('tab-pick').click();
                      document.querySelectorAll('#pane-pick details, #pane-office details').forEach(d => { d.open = true; });
                      const a = over(); let b = 0, folds = 0;
                      document.getElementById('tab-office').click();
                      document.querySelectorAll('input[name="odept"]').forEach(r => { r.checked = true; b = Math.max(b, over()); });
                      document.getElementById('od-brain').checked = true; folds = document.querySelectorAll('#pane-pick details[open], #pane-office details[open]').length;
                      const oday = document.querySelector('.oday details[open] table'), row = document.querySelector('.ocards'), r = row.getBoundingClientRect(),
                        bar = document.querySelector('.ohb-bar').getBoundingClientRect(), cell = document.querySelector('.ohb-bar label').getBoundingClientRect();
                      const cut = Array.from(document.querySelectorAll('.ocard .ocn')).filter(e => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1).map(e => e.textContent);
                      oday.style.minWidth = '1500px'; const wideT = over(), tb = oday.closest('.tbl'), inBox = tb.scrollWidth > tb.clientWidth; oday.style.minWidth = '';    // a wider table scrolls in its box
                      return [a, b, folds, row.scrollWidth - row.clientWidth, Math.round(r.right - innerWidth), Math.round(s.right - innerWidth), Math.round(bar.width),
                              getComputedStyle(document.body).backgroundColor, !!oday, Math.round(cell.height), cut, wideT, inBox, dflt]; }""")
                    sizes.append((w, dark, m))
                    ctx.close()
            ok = all(m[0] <= 0 and m[1] <= 0 and m[2] >= 3 and m[4] <= 0 and m[5] <= 0 and m[6] > 200 and m[8] and m[9] >= 44 and m[11] <= 0 and m[12] for _, _, m in sizes)
            phone = [m for w, _, m in sizes if w == 390]
            desk = [m for w, _, m in sizes if w == 1280]
            check(ok and all(m[3] <= 0 and not m[10] for m in phone + desk) and sizes[0][2][7] != sizes[1][2][7],
                  "U8 office and pick tabs at 390 and 1280 px, light and dark, every fold open (the daily overview's table too, also made 1500 px wide: it "
                  "scrolls in its box) and every department: no page scroll; the cards grid never scrolls inside itself and cuts no name; hour cells 44 px "
                  "tall (%s)" % [(w, "dark" if dk else "light", m[:4] + m[8:13]) for w, dk, m in sizes])
            n_cards = len(AGENTS) + 2
            check(all(m[13][:3] == [False, 0, 0] and m[13][4] == [] and m[13][5] == n_cards and m[13][6] >= 0 for _, _, m in sizes)
                  and all(m[13][3] == 2 for m in phone) and all(m[13][3] == 4 for m in desk),
                  "office default view at 390 and 1280 px, light and dark: the Details fold is closed (the floor plan is not drawn), no sideways scroll, the "
                  "%d cards in 2 columns on a phone and 4 on a desktop, each with exactly one line cut to one line, the paper account's line under "
                  "them (%s)" % (n_cards, [(w, "dark" if dk else "light", m[13]) for w, dk, m in sizes]))
            # a tap on an hour shows its numbers (CSS radios); on a phone a tap on a card opens its department and brings its panel (the radar: its block) into view
            ctx, pg = open_(page_plain)
            pg.click('label[for="tab-office"]')
            pg.evaluate("scrollTo(0, 0)")
            pg.click('label.ocard[data-agent="safety"]')
            pg.wait_for_timeout(900)
            tap = pg.evaluate("[document.getElementById('od-safety').checked, Math.round(document.querySelector('.opanel.k-safety').getBoundingClientRect().top), innerHeight, "
                              "document.querySelector('details[data-po-fold]').open]")
            pg.evaluate("scrollTo(0, 0)")
            pg.click('label[data-po-desk]')
            pg.wait_for_timeout(300)
            tap_r = pg.evaluate("[document.getElementById('tab-young').checked, Math.round(document.querySelector('[data-radar]').getBoundingClientRect().top), innerHeight, "
                                "!!(document.querySelector('[data-po-radar]')||{}).hidden, !!document.getElementById('tab-young') && !!document.querySelector('[data-radar]')]")
            pg.reload()
            pg.wait_for_timeout(300)
            kept = pg.evaluate("document.querySelector('details[data-po-fold]').open")
            ctx.close()
            ctx, pg = open_(page_plain, 1280, 900)
            fresh = pg.evaluate("document.querySelector('details[data-po-fold]').open")
            pg.click('label[for="tab-office"]')
            pg.click('label.ocard[data-agent="trader"]')
            pg.wait_for_timeout(900)
            tap_d = pg.evaluate("[document.getElementById('od-trading').checked, Math.round(document.querySelector('.ogrid').getBoundingClientRect().top), innerHeight, "
                                "document.querySelector('details[data-po-fold]').open, getComputedStyle(document.querySelector('.opanel.k-trading')).display]")
            check(tap[0] and 0 <= tap[1] < tap[2] / 2 and tap[3] and tap_r[0] and 0 <= tap_r[1] < tap_r[2] / 2 and tap_r[3] == (not tap_r[4]) and kept and fresh is False
                  and tap_d[0] and 0 <= tap_d[1] < tap_d[2] / 2 and tap_d[3] and tap_d[4] != "none",
                  "U6 browser: a tap on an agent's card opens the Details fold at its department and brings it into view (a phone: its panel; a desktop: "
                  "the floor plan with the panel beside it), a tap on the radar desk opens New with the radar in view; the fold stays open across the page's reload in that tab and is "
                  "closed in a new one; the link to the radar is hidden exactly when the page has no radar on New (%s, %s, %s, %s, %s)" % (tap, tap_r, tap_d, kept, fresh))
            pg.evaluate("document.getElementById('tab-office').click(); document.getElementById('od-brain').checked = true;")
            pg.click('label[for="ohb-3"]')
            shown = pg.evaluate("Array.from(document.querySelectorAll('.ohb-read p')).filter(p => p.getClientRects().length).map(p => p.textContent)")
            check(len(shown) == 1 and shown[0].startswith("03:00 to 04:00 · ") and not errs, "U9 browser: a tap on an hour of the bar shows that hour's numbers, one at a time (%s)" % (shown[:1], ))
            ctx.close()
            # "Open the radar" and the desk on top: in a browser the label checks the New tab's radio; in the installed app it sets #tab-radar so the
            # app's tab bar follows (New, at its top)
            res = []
            for sel in ('[data-po-radar] label', 'label[data-po-desk]'):
                for app in (False, True):
                    ctx, pg = open_(page_rt)
                    pg.evaluate("document.getElementById('tab-office').click(); document.querySelector('details[data-po-fold]').open = true; "
                                "document.getElementById('od-analysts').checked = true;" + (" document.documentElement.classList.add('app');" if app else ""))
                    pg.evaluate("window._hc = 0; window.addEventListener('hashchange', () => { window._hc++; });")
                    lab = pg.locator(sel)
                    hgt = round(lab.bounding_box()["height"]) if lab.is_visible() else 0
                    lab.click()
                    pg.wait_for_timeout(100)
                    res.append(pg.evaluate("[document.getElementById('tab-young').checked, location.hash, window._hc]") + [hgt])
                    ctx.close()
            check(all(r_[:3] == [True, "", 0] for r_ in res[0::2]) and all(r_[:3] == [False, "#tab-radar", 1] for r_ in res[1::2]) and all(r_[3] >= 44 for r_ in res),
                  "U6 browser: 'Open the radar' and the desk on top (44 px targets at least) open New in a browser and go through the app's hash link in the installed app (%s)" % res)
            # the desk on a phone (320 and 390 px) and a desktop, light and dark: no sideways scroll, a short block (a state line and two rows of
            # stations, each line at most 2 lines), page tokens in both themes
            dsz = []
            for w, dark in ((320, False), (320, True), (390, False), (390, True), (1280, False), (1280, True)):
                ctx, pg = open_(page_desk, w, 844, dark)
                pg.evaluate("document.getElementById('tab-office').click()")
                dsz.append(pg.evaluate("""() => { const k = document.querySelector('.odesk'), r = k.getBoundingClientRect(), h = document.querySelector('#pane-office h2').getBoundingClientRect(),
                    ls = Array.from(k.querySelectorAll('.odk-s .l')), cols = new Set(Array.from(k.querySelectorAll('.odk-s')).map(e => Math.round(e.getBoundingClientRect().left))).size;
                  return [document.documentElement.scrollWidth - innerWidth, Math.round(r.right - innerWidth), k.scrollWidth - k.clientWidth, Math.round(r.height), r.top < h.top,
                    ls.filter(l => l.getBoundingClientRect().height > 2 * parseFloat(getComputedStyle(l).lineHeight) + 1).length, cols,
                    getComputedStyle(k).backgroundColor, Array.from(k.querySelectorAll('.odk-s .k')).filter(e => e.scrollWidth > e.clientWidth + 1).length]; }"""))
                ctx.close()
            check(all(m[0] <= 0 and m[1] <= 0 and m[2] <= 0 and m[4] and m[5] == 0 and m[8] == 0 for m in dsz) and all(m[3] <= 220 and m[6] == 2 for m in dsz[:2]) and all(m[3] <= 200 and m[6] == 2 for m in dsz[2:4])
                  and dsz[4][6] == 4 and dsz[4][3] <= 130 and dsz[0][7] != dsz[1][7] and dsz[2][7] != dsz[3][7],
                  "U8 the radar desk at 320, 390 and 1280 px, light and dark: above the office's heading, no sideways scroll, station names whole, each "
                  "station line at most 2 lines, 2 x 2 on a phone (at most 200 px tall at 390 px) and one row on a desktop, its own colours in the dark theme (%s)" % dsz)
            br.close()
    except Exception as e:
        check(False, "office browser checks ran (%s)" % str(e)[:300])
    if errs:
        print("  page errors: %s" % errs[:3])


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    for k in ("GITHUB_REPOSITORY", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"):
        os.environ.pop(k, None)
    office_checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d check group%s skipped: %s)" % (len(skips), "" if len(skips) == 1 else "s", "; ".join(skips)) if skips else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
