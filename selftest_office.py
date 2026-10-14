#!/usr/bin/env python3
"""selftest_office.py: the checks of the office page parts (page_office.py, WP5c): SPEC 11 U6 (agent cards, office.json unchanged, the
radar's desk untouched by the office poll and moved by the radar event, 8 departments, the next-scan estimate from memeruns), U9 (the daily
overview names an hour only when it stands out), U7 and U10 for the new text, U8 for the office and pick tabs (390 and 1280 px, light and
dark). Fake money only: the fixtures are hand-made docs, nothing is fetched.

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
RADAR_AGENT = ("Launch radar", "rates every coin whose pool is under 10 minutes old, every 2½ minutes, in its own job; only coins without traps are shown and pushed",
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
        # ---------------------------------------------------------------- U6: one card per agent plus the radar card, office.json unchanged
        d1 = os.path.join(tmp, "o1")
        mk_db(d1, radar=radar_doc(NOW - 26 * MIN))
        off_before = open(os.path.join(d1, "db", "memebot", "office.json"), "rb").read()
        page = build(d1)
        off_after = open(os.path.join(d1, "db", "memebot", "office.json"), "rb").read()
        cards = re.findall(r'<label class="ocard( ext)?" for="od-([a-z]+)" data-agent="([a-z]+)"', page)
        D1 = R.collect(d1, NOW)
        info = R.office_data(D1)
        check(off_before == off_after and [c[2] for c in cards] == list(AGENTS) + ["radar"] and cards[-1][0] == " ext" and cards[-1][1] == "analysts"
              and [a["id"] for a in info["agents"]] == list(AGENTS) and [a["id"] for a in info["ext"]] == ["radar"] and "could not be rendered" not in page
              and R.OFFICE_AGENTS["radar"] == RADAR_AGENT and (info["ext"][0]["name"], info["ext"][0]["job"], tuple(info["ext"][0]["tools"])) == RADAR_AGENT
              and -1 < page.find('<div class="ocards"') < page.find("Tap a department to see what its agents did.") < page.find('<div class="office">'),
              "U6 office: one card per agent of office.json in run order plus the Launch radar's card (dashed, opens Analysts), above the intro note; the "
              "radar's name, job and tools are the spec's words; office.json is not written (%d cards)" % len(cards))
        card_dept = dict((c[2], c[1]) for c in cards)
        card_line = lambda aid: R.html.unescape(re.search(r'<label class="ocard[^"]*" for="od-[a-z]+" data-agent="%s".*?<span class="ocl"[^>]*>(.*?)</span>' % aid, page, re.S).group(1))
        lines_ = {aid: card_line(aid) for aid in ("refresh", "market", "candles", "radar")}
        check(card_dept.get("trainer") == "brain" and card_dept.get("dispatch") == "ops" and card_dept.get("safety") == "safety" and card_dept.get("deep") is None
              and "result &lt;b&gt;3" in page and "result <b>3" not in page and 'data-live-chip="analyst"' in cut(page, '<div class="ocards"', '</div>')
              and 'data-live-chip="radar"' not in page and lines_["candles"] == "candles result <b>3</b>"
              and len(lines_["refresh"]) <= 60 and lines_["refresh"] == PO.clip(LONG_OUT, 60) and lines_["refresh"].endswith("…") and LONG_OUT.startswith(lines_["refresh"][:-1])
              and lines_["market"] == "DexScreener slow: 3 of 40 pairs retried"
              and len(re.findall(r'data-live-line="[a-z]+" data-live-max="60"', cut(page, '<div class="ocards"', '</label></div>'))) == len(AGENTS),
              "U6 office: each card is the label of its department, carries the live hooks (not the radar's, the live line capped at 60), its text escaped, "
              "one line of at most 60 characters, a warning without its '! ' mark (%s)" % lines_)
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
              and ">on watch<" in page and "7 seen · 1 without traps · 0 pushed" in page and 'data-ext-stat="radar">checked %s</span>' % R.local(NOW - 26 * MIN).strftime("%H:%M") in page
              and "RugCheck · limited" in page and "RugCheck limited: 2 coins not fully checked" in page,
              "U6 office: a radar that ran at the start of this scan is 'on watch' with its counts, hosts and notes; its pill reads 'own job'")
        # its state at the scan's start (the copy is made then; the page comes about 25 minutes later), as MB.radarState names them
        sts = []
        for age, kw in ((5 * MIN, {}), (7 * MIN, {}), (20 * MIN, {}), (60_000, {"state": "off"}), (60_000, {"state": "hours", "next": NOW + H}),
                        (40 * MIN, {"state": "hours", "next": NOW - 20 * MIN})):
            dd = os.path.join(tmp, "st%d" % len(sts))
            wj(os.path.join(dd, "radar_live.json"), radar_doc(NOW - age, **kw))
            sts.append(PO.radar_state(PO.radar_doc(dd), NOW))
        check(sts == ["running", "late", "stopped", "off", "hours", "stopped"] and PO.radar_state(None, NOW) == "none",
              "U6 radar desk states at a time: running, late, stopped, off, hours (and stopped once past its next start), none (%s)" % sts)
        # what the card and the panel say in each state: a late or stopped radar leads with that word (its counts are its last check's) in the
        # Radar tab's colours (amber, red), a degraded one says checks fail, one that never ran is "not started yet"
        rd = PO.radar_clean(radar_doc(NOW - 20 * MIN))
        lk = {s_: PO.look(s_, rd, utc) for s_ in ("running", "late", "stopped")}
        lk["degraded"] = PO.look("running", PO.radar_clean(radar_doc(NOW, state="degraded")), utc)
        lk["none"] = PO.look("none", None, utc)
        check([(v["light"], v["line"]) for v in lk.values()] == [
            ("running", "7 seen · 1 without traps · 0 pushed"), ("fallback", "late · 7 seen, 1 without traps"),
            ("failed", "stopped · 7 seen, 1 without traps"), ("fallback", "checks failing · 7 seen · 1 without traps · 0 pushed"),
            ("skipped", "not started yet")] and lk["stopped"]["stat"] == "checked %s" % utc(NOW - 20 * MIN) and lk["late"]["until"].startswith(" · this run until ")
              and lk["stopped"]["until"] == "" and PO.CHIP["failed"] == "bad",
              "U6 radar card: late and stopped lead with that word (amber, red: the Radar tab's colours), degraded says checks fail, none is 'not started yet' (%s)" % (
                  [v["line"] for v in lk.values()],))
        # switched off (or outside its hours, or never started): the panel drops the last check's notes and services, the wiring stays
        panels = {}
        for k_, kw in (("off", {"state": "off"}), ("run", {})):
            dd = os.path.join(tmp, "pn-" + k_)
            wj(os.path.join(dd, "radar_live.json"), radar_doc(NOW - 60_000, **kw))
            panels[k_] = PO.ext_panel(PO.ext_agents({"dir": dd, "runs": D1["runs"], "now": NOW}, R.office_meta, R)[0], R)
        check("omsg warn" not in panels["off"] and 'data-ext-hosts="radar" hidden></div>' in panels["off"] and '<p class="note" data-ext-wired="radar">Wired to DexScreener' in panels["off"]
              and "RugCheck limited: 2 coins" in panels["run"] and "RugCheck · limited" in panels["run"] and 'data-ext-wired="radar" hidden>' in panels["run"]
              and 'data-ext-until="radar"> · this run until ' in panels["run"] and 'data-ext-until="radar"></span>' in panels["off"],
              "U6 radar panel: switched off, it shows no old notes or service chips (the wiring instead) and no 'this run until'; running, it shows them")
        bad = os.path.join(tmp, "bad")
        wj(os.path.join(bad, "radar_live.json"), {"kind": "radar", "t": "soon", "counts": {"seen": "x"}})
        wj(os.path.join(bad, "x", "radar_live.json"), dict(radar_doc(NOW), counts={"seen": float("inf"), "good": "2", "pushed": None}, lines=[XSS, 5, None], hosts={"a" * 90: "ok", "rpc": 3}))
        wj(os.path.join(bad, "y", "radar_live.json"), dict(radar_doc(NOW), next=1e300, run={"end": -5, "start": "x"}))
        wild = PO.radar_doc(os.path.join(bad, "y"))
        weird = PO.radar_doc(os.path.join(bad, "x"))
        check(PO.radar_doc(bad) is None and PO.radar_doc(os.path.join(tmp, "nowhere")) is None and weird["counts"]["seen"] is None and weird["lines"] == [XSS]
              and list(weird["hosts"]) == ["a" * 40] and wild["next"] is None and wild["run"]["end"] is None and PO.radar_clean(dict(radar_doc(NOW), t=1e19)) is None,
              "a malformed radar_live.json is dropped (no time, or a wild one) or cut to finite numbers, times that are times, strings and the known keys")
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
              and "next ≈ %s" % R.local(nxt).strftime("%H:%M") in page and 'data-next="%d"' % nxt in page and "next scan starts about %s" % R.fmt_when(nxt, NOW) in page
              and hint in page_live and R.next_scan_ms(NOW) == R.next_scan_ms(NOW, []) == int(dt.datetime(2026, 10, 13, 19, 10, tzinfo=dt.timezone.utc).timestamp() * 1000),
              "U6 next scan: the median start minute of the last 6 memeruns (:41; :58 to :02 wraps to :00) times data-next-scan, the strip, the header and "
              "the early list's hint %s; fewer than 3 runs keep SCAN_MINUTE_UTC (%s)" % (hint, est))
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
        m_old = re.search(r"next scan starts about ([^<]*?) · ", nopo)
        check(nopo and "could not be rendered" not in nopo and 'class="ocard' not in nopo and "sstrip" not in nopo and "Daily overview" not in nopo
              and 'data-ext="radar"' not in nopo and "<style></style>" not in nopo and 'data-agents="analyst"' in nopo
              and m_old and m_old.group(1) == R.fmt_when(R.next_scan_ms(NOW, []), NOW),
              "report.py without page_office.py builds the page as before it: no cards, strip, overview or radar desk, the cron minute for the next scan (%s)" % (
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
        new_text = " ".join([cut(page, '<div class="ocards"', "</label></div>"), cut(page, '<div class="oagent oext"', "Open the Radar tab"), cut(page7, '<div class="oday">', "</details></div>"),
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
                     ("hours", radar_doc(NOW, state="hours", next=None)), ("none", None), ("running", dict(radar_doc(NOW), counts=None))]
            py = [PO.look(s_, PO.radar_clean(doc_) if doc_ else None, utc) for s_, doc_ in cases]
            jd = os.path.join(tmp, "js")
            os.makedirs(jd)
            with open(os.path.join(jd, "t.js"), "w", encoding="utf-8") as f:
                f.write("var L=[];global.window={addEventListener:function(k,f){L.push(k);}};global.document={readyState:'complete',addEventListener:function(k){L.push('doc:'+k);},querySelector:function(){return null;},querySelectorAll:function(){return [];}};\n"
                        + PO.JS + "\nvar O=window.MemebotOffice,f=function(ms){return new Date(ms).toISOString().slice(11,16);},C=%s,o={look:[],scan:[]};\n" % json.dumps(cases)
                        + "C.forEach(function(c){o.look.push(O.look(c[0],c[1],f));});var t=Date.UTC(2026,9,13,18,0),d={t:t,updated:t+600000};\n"
                        + "o.scan=[O.scan('live',d,t-60000,f),O.scan('paused',d,t-60000,f),O.scan('done',d,t-60000,f),O.scan('stopped',d,t-60000,f),O.scan('live',d,t,f),O.scan('hide',d,t-60000,f),O.scan('live',null,0,f)];\n"
                        + "o.next=[O.next(t,t-1,f),O.next(t,t,f),O.next(t,t+3600000,f),O.next(0,t,f)];\n"
                        + "o.events=L;O.radar({state:'off',doc:null});console.log(JSON.stringify(o));\n")
            r = subprocess.run([node, os.path.join(jd, "t.js")], capture_output=True, text=True, timeout=60)
            o = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
            same = o.get("look") == py
            check(same and o.get("scan") == [{"dot": "run", "text": "running now · started 18:00"}, {"dot": "late", "text": "started 18:00 · no update since 18:10"},
                                             {"dot": "ok", "text": "finished 18:10 · new page on its way"}, {"dot": "bad", "text": "stopped 18:10"}, None, None, None]
                  and o.get("next") == ["next ≈ 18:00", "due now (≈ 18:00)", "due now (≈ 18:00)", None]
                  and sorted(o.get("events") or []) == ["doc:click", "memebot-live", "memebot-radar"],
                  "node: the office script says what the page said at build time for every radar state (line, light, 'this run until'), the scan strip's live "
                  "words and its 'due now' once the expected start has passed (%s)" % (
                      "same" if same else "%s vs %s" % (o.get("look"), py) if o else r.stderr[-300:]))

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
    # the same page with the Radar tab's radio (WP5b's tab), so "Open the Radar tab" has its target
    office_radio = '<input type="radio" name="tab" id="tab-office">'
    page_rt = page_plain.replace(office_radio, office_radio + '<input type="radio" name="tab" id="tab-radar">', 1)
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
              return { desk: q('g[data-ext="radar"]').getAttribute('data-live'), card: q('label[data-ext="radar"]').getAttribute('data-live'),
                panel: q('.oext').getAttribute('data-live'), an: q('g.desk[data-agent="analyst"]').getAttribute('data-live'),
                acard: q('label.ocard[data-agent="analyst"]').getAttribute('data-live'), achip: (q('label.ocard[data-agent="analyst"] [data-live-chip]')||{}).textContent,
                aline: (q('label.ocard[data-agent="analyst"] [data-live-line]')||{}).textContent, pline: (q('.opanel [data-live-line="analyst"]')||{}).textContent,
                astatic: cs(q('label.ocard[data-agent="analyst"] > .ocl:not([data-live-line])')).display, aliveshow: cs(q('label.ocard[data-agent="analyst"] [data-live-line]')).display,
                wait: [q('label.ocard[data-agent="trainer"]').getAttribute('data-live'), cs(q('label.ocard[data-agent="trainer"]')).opacity],
                strip: q('[data-ss-state]').textContent, nexthid: q('[data-ss-next]').hidden,
                rline: q('[data-ext-line="radar"]').textContent, waiting: Array.from(document.querySelectorAll('[data-live-strip] span')).map(s => s.textContent) }; }""")
            check(got["desk"] is None and got["card"] is None and got["panel"] is None and got["an"] == "work" and got["acard"] == "work" and got["achip"] == "at work now"
                  and got["pline"] == "Now: " + long_line and 50 < len(got["aline"]) <= 60 and got["aline"].endswith("…") and ("Now: " + long_line).startswith(got["aline"][:-1])
                  and got["astatic"] == "none" and got["aliveshow"] != "none" and got["wait"] == ["wait", "0.55"]
                  and got["rline"] == "7 seen · 1 without traps · 0 pushed" and "Waiting %d" % (len(set(R.OFFICE_AGENTS) - {"radar"}) - 2) in got["waiting"]
                  and got["strip"].startswith("running now · started ") and got["nexthid"] and link == "https://github.com/%s/actions/workflows/scan.yml" % REPO,
                  "U6 browser: the office poll marks the scan's desks and cards live but never the radar's (even when the live doc names one); a card at work "
                  "shows its live line (at most 60 characters) instead of last run's, a waiting card is faded; the strip says the scan runs now and links to "
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
              return [q('g[data-ext="radar"]').getAttribute('class'), q('label[data-ext="radar"] .ocl').textContent, q('[data-ext-word="radar"]').textContent,
                q('[data-ext-lt="radar"]').getAttribute('class'), q('[data-ext-hosts="radar"]').hidden, q('[data-ext-wired="radar"]').hidden,
                q('[data-ext-notes="radar"]').textContent, q('[data-ext-until="radar"]').textContent]; }""")
            pg.evaluate("""x => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'late', via: 'raw', doc: {kind: 'radar', t: Date.now() - 400000, state: 'running',
              counts: {seen: 9, good: 2, pushed: 1}, lines: ['cycle 20: ' + x], notes: ['RugCheck limited: 4 coins not fully checked'], run: {end: Date.now() + 1200000},
              hosts: {rugcheck: 'down', dexscreener: 'ok'}}}}))""", XSS)
            on = pg.evaluate("""() => { const p = document.querySelector('.oext');
              return [document.querySelector('g[data-ext="radar"]').getAttribute('class'), document.querySelector('g[data-ext="radar"] .scr').getAttribute('class'),
                document.querySelector('label[data-ext="radar"] .ocl').textContent, p.querySelectorAll('img').length, p.querySelector('[data-ext-lines]').textContent,
                p.querySelector('[data-ext-hosts]').textContent, document.querySelector('[data-ext-chip="radar"]').className, p.querySelector('[data-ext-notes]').textContent,
                p.querySelector('[data-ext-until]').textContent, p.querySelector('[data-ext-hosts]').hidden, p.querySelector('[data-ext-wired]').hidden]; }""")
            pg.evaluate("""() => window.dispatchEvent(new CustomEvent('memebot-radar', {detail: {state: 'stopped', via: 'github', doc: {kind: 'radar', t: Date.now() - 2400000, state: 'running',
              counts: {seen: 4, good: 0, pushed: 0}}}}))""")
            stop = pg.evaluate("""() => [document.querySelector('[data-ext-lt="radar"]').getAttribute('class'), document.querySelector('[data-ext-chip="radar"]').className,
              document.querySelector('g[data-ext="radar"] .scr').getAttribute('class'), document.querySelector('label[data-ext="radar"] .ocl').textContent,
              document.querySelector('[data-ext-notes="radar"]').textContent]""")
            check(off == ["desk off", "switched off on GitHub", "switched off", "olt skipped", True, False, "", ""]
                  and on[:3] == ["desk", "scr fallback", "late · 9 seen, 2 without traps"] and on[3] == 0 and XSS in on[4] and on[5] == "RugCheck · downDexScreener · ok"
                  and on[6] == "chip warn" and on[7] == "RugCheck limited: 4 coins not fully checked" and on[8].startswith(" · this run until ") and on[9:] == [False, True]
                  and stop == ["olt failed", "chip bad", "scr failed", "stopped · 4 seen, 0 without traps", ""] and not dialogs,
                  "U6/U10 browser: the radar event moves the radar's desk, card and panel: off is dark without old notes or services; late is amber with its "
                  "counts, notes and run end; stopped is red; its lines are text, never markup (%s | %s | %s)" % (off, on[:3] + on[6:9], stop))
            ctx.close()
            # 390 and 1280, light and dark, every fold on the Pick and Office tabs open and every department in turn: nothing wider than the screen;
            # the cards row scrolls inside itself on a phone, wraps on a desktop with whole names; the hour cells are 44 px tall
            sizes = []
            for w, h in ((390, 844), (1280, 900)):
                for dark in (False, True):
                    ctx, pg = open_(page_plain, w, h, dark)
                    m = pg.evaluate("""() => { const over = () => document.documentElement.scrollWidth - innerWidth, s = document.querySelector('.sstrip').getBoundingClientRect();
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
                              getComputedStyle(document.body).backgroundColor, !!oday, Math.round(cell.height), cut, wideT, inBox]; }""")
                    sizes.append((w, dark, m))
                    ctx.close()
            ok = all(m[0] <= 0 and m[1] <= 0 and m[2] >= 3 and m[4] <= 0 and m[5] <= 0 and m[6] > 200 and m[8] and m[9] >= 44 and m[11] <= 0 and m[12] for _, _, m in sizes)
            phone = [m for w, _, m in sizes if w == 390]
            desk = [m for w, _, m in sizes if w == 1280]
            check(ok and all(m[3] > 0 for m in phone) and all(m[3] <= 0 and not m[10] for m in desk) and sizes[0][2][7] != sizes[1][2][7],
                  "U8 office and pick tabs at 390 and 1280 px, light and dark, every fold open (the daily overview's table too, also made 1500 px wide: it "
                  "scrolls in its box) and every department: no page scroll; the cards row scrolls inside itself on a phone, wraps on a desktop with no name "
                  "cut; hour cells 44 px tall (%s)" % [
                      (w, "dark" if dk else "light", m[:4] + m[8:]) for w, dk, m in sizes])
            # a tap on an hour shows its numbers (CSS radios); on a phone a tap on a card opens its department and brings its panel (the radar: its block) into view
            ctx, pg = open_(page_plain)
            pg.click('label[for="tab-office"]')
            pg.evaluate("scrollTo(0, 0)")
            pg.click('label.ocard[data-agent="safety"]')
            pg.wait_for_timeout(900)
            tap = pg.evaluate("[document.getElementById('od-safety').checked, Math.round(document.querySelector('.opanel.k-safety').getBoundingClientRect().top), innerHeight]")
            pg.evaluate("scrollTo(0, 0)")
            pg.click('label.ocard[data-agent="radar"]')
            pg.wait_for_timeout(900)
            tap_r = pg.evaluate("[document.getElementById('od-analysts').checked, Math.round(document.querySelector('.oext').getBoundingClientRect().top), innerHeight, "
                                "!!(document.querySelector('[data-po-radar]')||{}).hidden]")
            check(tap[0] and 0 <= tap[1] < tap[2] / 2 and tap_r[0] and 0 <= tap_r[1] < tap_r[2] / 2 and tap_r[3],
                  "U6 browser: on a phone a tap on an agent's card opens its department and scrolls its panel into view, the radar's card its own block; "
                  "without a Radar tab its link is hidden (%s, %s)" % (tap, tap_r))
            pg.evaluate("document.getElementById('tab-office').click(); document.getElementById('od-brain').checked = true;")
            pg.click('label[for="ohb-3"]')
            shown = pg.evaluate("Array.from(document.querySelectorAll('.ohb-read p')).filter(p => p.getClientRects().length).map(p => p.textContent)")
            check(len(shown) == 1 and shown[0].startswith("03:00 to 04:00 · ") and not errs, "U9 browser: a tap on an hour of the bar shows that hour's numbers, one at a time (%s)" % (shown[:1], ))
            ctx.close()
            # "Open the Radar tab": in a browser the label checks the tab's radio; in the installed app it sets #tab-radar so the app's tab bar follows
            res = []
            for app in (False, True):
                ctx, pg = open_(page_rt)
                pg.evaluate("document.getElementById('tab-office').click(); document.getElementById('od-analysts').checked = true;" + (" document.documentElement.classList.add('app');" if app else ""))
                pg.evaluate("window._hc = 0; window.addEventListener('hashchange', () => { window._hc++; });")
                lab = pg.locator('[data-po-radar] label')
                hgt = round(lab.bounding_box()["height"]) if lab.is_visible() else 0
                lab.click()
                pg.wait_for_timeout(100)
                res.append(pg.evaluate("[document.getElementById('tab-radar').checked, location.hash, window._hc]") + [hgt])
                ctx.close()
            check(res[0][:3] == [True, "", 0] and res[1][:3] == [False, "#tab-radar", 1] and res[0][3] >= 44 and res[1][3] >= 44,
                  "U6 browser: 'Open the Radar tab' (a 44 px target) opens the tab in a browser and goes through the app's hash link in the installed app (%s)" % res)
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
