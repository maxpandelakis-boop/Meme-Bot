#!/usr/bin/env python3
"""page_office.py: the agent office's newer parts on the page (fake money only: nothing here buys, sells or advises anything).

  agent cards      a row above the floor plan: one card per agent of the last run plus the Launch radar, each with its light, its name,
                   one line (its result, at most 60 characters) and one small number. A card opens its department below. While a scan
                   runs, the office's live script marks the cards through the hooks the panels already have (data-live-chip, -line).
  radar desk       the Launch radar runs in its own job (radar.yml), not in the hourly scan: its desk is the second one on the Analysts
                   platform, drawn from mb/radar_live.json (the scan copies the radar's last radar.json there before it starts). It never
                   counts in a department's light, the team timeline, the counts or "at work at once"; office.json is not changed. The
                   radar tab's script (memebot-radar event) keeps its light and its line current on the page.
  daily overview   in the Brain's panel: one plain sentence about today's new launches (how many were checked, how many were dead within
                   an hour, the radar's calls without traps) and a bar of the 24 hours of the day (Berlin): each hour's share of launches
                   dead within an hour over the last 7 days. An hour is named only when it stands out in both halves of the week.
  scan strip       the Pick tab's line about the full scan: last start, the next one expected (the median start minute of the last runs,
                   which also times the office's live polls) and a link to start it on GitHub (no token: the page only links there).

report.py calls these with itself as R (its formatting helpers and the office's own functions), so this module needs only memebot. All
text that comes from a file is escaped (Python) or set as text (script); the script reads nothing from the network.
"""
import datetime as dt, glob, json, math, os, re

import memebot as M

RADAR = "radar"
EXT_HOME = {RADAR: "analysts"}       # agents that run in their own job -> the department whose platform has their desk
SCAN_RUNS = 6                        # the next-scan estimate: the median start minute of this many latest runs
SCAN_RUNS_MIN = 3                    # with fewer runs the cron minute stands
CYCLE_MS, GRACE_MS, LATE_MS = 150_000, 60_000, 900_000   # the radar's cycle; "running" within 2 cycles and a minute, "late" up to 15 minutes
DAY_MS, WEEK_DAYS = 86_400_000, 7
HOUR_MIN_N = 30                      # an hour is named only with at least this many launches with a 1 h result in the 7 days
HOUR_FEW_N = 20                      # a cell with fewer is hatched
DEAD_LIQ, RUG_X = 1_000.0, 0.10      # dead within an hour (the rug study's rule): gone, a pool under $1k, or 90% down
TODAY_MIN_N = 10                     # today's share is given as a percentage from this many results on
HOSTS = (("dexscreener", "DexScreener"), ("rugcheck", "RugCheck"), ("pump.fun", "pump.fun"), ("pumpfun", "pump.fun"), ("geckoterminal", "GeckoTerminal"),
         ("rpc", "Solana RPC"), ("jupiter", "Jupiter"), ("launchlab", "LaunchLab"), ("github", "GitHub"), ("supabase", "Supabase"))
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
LOOK = {"running": ("running", "on watch"), "late": ("fallback", "late"), "stopped": ("skipped", "stopped"), "off": ("skipped", "switched off"),
        "hours": ("skipped", "outside its hours"), "none": ("skipped", "not started yet")}
CHIP = {"running": "neutral", "fallback": "warn", "failed": "bad", "done": "good"}


def _num(v):
    v = M.num(v)
    return v if v is not None and math.isfinite(v) else None


def _ms(v):
    """A time in ms between 2001 and 2100, else None (a wild number in a file never reaches the clock functions)."""
    v = _num(v)
    return v if v is not None and 1e12 < v < 4.1e12 else None


def _str(v, n):
    return v[:n] if isinstance(v, str) else ""


def _int(v):
    v = _num(v)
    return int(round(v)) if v is not None else 0


def clip(s, n=60):
    """At most n characters, an ellipsis where it was cut."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---------------------------------------------------------------- the next full scan
def scan_minute(runs, default):
    """The minute of the hour the full scan starts at: the circular median of the start minutes (UTC) of the last SCAN_RUNS runs
    (db/memeruns "t", the cycle's clock), so scans that GitHub starts half an hour after the cron minute are expected then. Minutes
    wrap (:58, :59, :01 give :59). With fewer than SCAN_RUNS_MIN runs: default (the cron minute)."""
    ts = sorted({int(t) for t in (_ms(r.get("t")) for r in (runs or []) if isinstance(r, dict)) if t}, reverse=True)[:SCAN_RUNS]
    if len(ts) < SCAN_RUNS_MIN:
        return int(default) % 60
    mins = [(t // 1000 % 3600) / 60.0 for t in ts]
    best = None
    for a in mins:
        dev = sorted(((m - a + 30.0) % 60.0) - 30.0 for m in mins)
        k = len(dev)
        med = dev[k // 2] if k % 2 else (dev[k // 2 - 1] + dev[k // 2]) / 2.0
        cost = sum(abs(x - med) for x in dev)
        if best is None or cost < best[0] - 1e-9:
            best = (cost, (a + med) % 60.0)
    return int(math.floor(best[1] + 1e-9)) % 60


# ---------------------------------------------------------------- the Launch radar's desk
def radar_doc(d):
    """mb/radar_live.json (the radar's radar.json as the scan found it) reduced to what the office shows, or None."""
    return radar_clean(M.load_json(os.path.join(d, "radar_live.json"), None) if d else None)


def radar_clean(doc):
    """A radar.json reduced to what the office shows, or None without a time: numbers finite, strings cut, unknown keys dropped."""
    if not isinstance(doc, dict) or doc.get("kind") != "radar" or not _ms(doc.get("t")):
        return None
    c = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    run = doc.get("run") if isinstance(doc.get("run"), dict) else {}
    hosts = doc.get("hosts") if isinstance(doc.get("hosts"), dict) else {}
    return {"t": int(_ms(doc["t"])), "next": _ms(doc.get("next")), "state": _str(doc.get("state"), 20), "why": _str(doc.get("why"), 160),
            "run": {"start": _ms(run.get("start")), "end": _ms(run.get("end")), "cycle": _num(run.get("cycle"))},
            "counts": {k: _num(c.get(k)) for k in ("seen", "good", "pushed", "seenAgeMed")} if isinstance(doc.get("counts"), dict) else None,
            "hosts": {_str(k, 40): _str(v, 20) for k, v in list(hosts.items())[:12] if isinstance(k, str) and isinstance(v, str)},
            "notes": [_str(x, 160) for x in (doc.get("notes") or [])[:4] if isinstance(x, str)] if isinstance(doc.get("notes"), list) else [],
            "lines": [_str(x, 200) for x in (doc.get("lines") or [])[-6:] if isinstance(x, str)] if isinstance(doc.get("lines"), list) else []}


def radar_state(doc, ref):
    """running | late | stopped | off | hours | none at the time ref (ms), as the Radar tab's MB.radarState names them (SPEC 6.1)."""
    if not doc:
        return "none"
    age = ref - doc["t"]
    if doc.get("state") == "off":
        return "off"
    if doc.get("state") == "hours":
        return "stopped" if doc.get("next") and doc["t"] + age > doc["next"] + LATE_MS else "hours"
    return "running" if age <= 2 * CYCLE_MS + GRACE_MS else ("late" if age <= LATE_MS else "stopped")


def look(state, doc, hhmm):
    """The desk's light, word, line and small number for a radar state (the page script's MemebotOffice.look says the same)."""
    light, word = LOOK.get(state, LOOK["none"])
    if state == "running" and doc and doc.get("state") == "degraded":
        light, word = "fallback", "on watch, some checks failing"
    c = (doc or {}).get("counts") or None
    if state == "off":
        line = "switched off on GitHub"
    elif state == "hours":
        line = ("outside its hours · next start %s" % hhmm(doc["next"])) if doc and doc.get("next") else "outside its hours"
    elif state == "none" or not c:
        line = "starts with the next full scan"
    else:
        line = "%d seen · %d without traps · %d pushed" % (_int(c.get("seen")), _int(c.get("good")), _int(c.get("pushed")))
    checked = ("checked %s" % hhmm(doc["t"])) if doc and state != "none" else "no check yet"
    return {"light": light, "word": word, "line": line, "stat": checked if doc and state != "none" else "own job", "checked": checked,
            "here": state in ("running", "late")}


def ext_agents(D, meta, R):
    """The agents that run in their own job, as office_data's agents (never 'ran' in the scan: no seconds, no bar, no count). The radar's
    state is judged at the start of the scan that copied its file (the page is built about 25 minutes later; the script brings it up to date)."""
    doc = radar_doc(D.get("dir"))
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and _ms(r.get("t"))]
    now = _num(D.get("now")) or 0
    ref = min(now, max(doc["t"], _ms(runs[0]["t"]))) if doc and runs and now else now
    st = radar_state(doc, ref)
    lk = look(st, doc, lambda ms: R.local(ms).strftime("%H:%M"))
    name, job, tools = meta(RADAR)
    return [{"id": RADAR, "ext": True, "dept": EXT_HOME[RADAR], "s": None, "e": None, "st": lk["light"], "bg": False, "out": lk["line"],
             "lines": (doc or {}).get("lines") or [], "waits": {}, "blocked": [], "ran": False, "open": False, "secs": 0.0, "here": lk["here"],
             "name": name, "job": job, "tools": tools, "state": st, "word": lk["word"], "stat": lk["stat"], "checked": lk["checked"], "doc": doc}]


def host_chips(hosts):
    """The radar's hosts as chips (problems first): ok, limited, down."""
    out = []
    for k, v in sorted((hosts or {}).items(), key=lambda kv: (kv[1] == "ok", kv[0])):
        name = next((n for h, n in HOSTS if h in k.lower()), k)
        cls = "" if v == "ok" else ("warn" if v in ("limited", "slow") else "bad")
        out.append('<span class="chip %s">%s · %s</span>' % (cls, _e(name), _e(v)))
    return "".join(out)


def _e(s):
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def ext_panel(a, R):
    """The Launch radar in the Analysts panel: its job, its state now (the Radar tab's script updates it), what its last check found,
    its notes, the services it calls and its last lines."""
    doc = a.get("doc") or {}
    run = doc.get("run") or {}
    until = (" · this run until %s" % R.local(run["end"]).strftime("%H:%M")) if run.get("end") and a["state"] in ("running", "late") else ""
    notes = "".join('<p class="omsg warn">%s</p>' % _e(n) for n in doc.get("notes") or [])
    lines = "".join(R.office_line(ln) for ln in doc.get("lines") or [])
    return ('<div class="oagent oext" data-agent="radar" data-ext="radar"><div class="who"><strong>%s</strong><span class="chip">own job</span>'
            '<span class="chip %s" data-ext-chip="radar" data-ext-word="radar">%s</span></div><p class="job">%s</p>'
            '<p class="clk"><span data-ext-checked="radar">%s</span>%s · every 2½ min</p>'
            '<div><span class="olab">Output</span><p class="oout" data-ext-line="radar">%s</p></div>%s'
            '<div><span class="olab">Connected tools</span><div class="chips" data-ext-hosts="radar">%s</div>%s</div>'
            '<div><span class="olab">Latest lines</span><ul class="olines" data-ext-lines="radar">%s</ul></div>'
            '<p class="note"><label class="olinkb" for="tab-radar">Open the Radar tab</label></p></div>') % (
        _e(a["name"]), CHIP.get(a["st"], ""), _e(a["word"]), _e(a["job"]), _e(a["checked"]), _e(until), _e(a["out"]), notes,
        host_chips(doc.get("hosts")), "" if doc.get("hosts") else '<p class="note">Wired to %s.</p>' % _e(", ".join(a["tools"])), lines)


# ---------------------------------------------------------------- the agent cards
def cards(info, R):
    """One card per agent of the last run (in run order) and one per agent in its own job: light, name, one line, one number. A card is the
    label of its department's radio, so a tap opens that department's panel below (no script needed)."""
    home = {m["id"]: d["key"] for d in info["depts"] + [info["brain"]] for m in d["agents"]}
    out = []
    for a in info["agents"] + (info.get("ext") or []):
        ext = bool(a.get("ext"))
        st = a["st"] if a["st"] in R.OFFICE_ST else "skipped"
        if ext:
            line, stat = a["out"], a["stat"]
        else:
            line = a["out"] or R.office_latest(a["lines"]) or R.office_word(a)
            stat = (R.fmt_secs(a["secs"], True) + (" · beside" if a["bg"] else "")) if a["ran"] else R.office_word(a)
        word = a["word"] if ext else R.office_word(a)
        tag = (' data-ext="%s"' % _e(a["id"])) if ext else ""
        x = (lambda k: ' data-ext-%s="%s"' % (k, _e(a["id"]))) if ext else (lambda k: "")
        live = "" if ext else ('<span class="chip" data-lv data-live-chip="%s" hidden></span><span class="ocl" data-lv data-live-line="%s" hidden></span>' % (_e(a["id"]), _e(a["id"])))
        out.append('<label class="ocard%s" for="od-%s" data-agent="%s"%s title="%s: %s"><span class="och"><span class="olt %s"%s aria-hidden="true">●</span>'
                   '<span class="ocn">%s</span></span><span class="ocl"%s>%s</span>%s<span class="ocs"%s>%s</span></label>' % (
                       " ext" if ext else "", _e(home.get(a["id"], "ops")), _e(a["id"]), tag, _e(a["name"]), _e(word), st, x("lt"), _e(a["name"]),
                       x("line"), _e(clip(line, 60)), live, x("stat"), _e(stat)))
    return ('<div class="ocards" data-po-tz="%s" data-po-tzn="%s" role="group" aria-label="The agents: tap one to open its department">%s</div>' % (
        "Europe/Berlin" if R.TZ_NAME == "Berlin" else "UTC", _e(R.TZ_NAME), "".join(out)))


# ---------------------------------------------------------------- the daily overview
def _dead_early(c):
    p, px0 = c.get("p60"), _num(c.get("px"))
    if not isinstance(p, dict):
        return None
    if p.get("gone"):
        return True
    px1, liq1 = _num(p.get("px")), _num(p.get("liq"))
    if not px0 or px1 is None:
        return None
    return bool((liq1 is not None and liq1 < DEAD_LIQ) or px1 / px0 < RUG_X)


def recent_docs(d, coll, lo):
    """The docs of a collection whose file name (a UTC run id or hour, 2026-10-13T1652 / 2026-10-13T16) is not older than lo less an hour; a
    name that is not a time is read anyway. The radar's hour docs are kept 30 days: the overview reads only its week."""
    out = {}
    for p in glob.glob(os.path.join(d, "db", coll, "*.json")):
        name = os.path.splitext(os.path.basename(p))[0]
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})", name)
        if m:
            try:
                if dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc).timestamp() * 1000 < lo - 2 * 3_600_000:
                    continue
            except ValueError:
                pass
        doc = M.load_json(p, None)
        if isinstance(doc, dict):
            out[name] = doc
    return out


def launches(d, now):
    """Every new launch the bot checked in the last 7 days, once per coin: {addr: {"t": launch time (ms), "dead": True/False/None}}, from
    the scored new launches (db/memeyoung, their 1 h check), the early lists (db/memeearly, their price about an hour later) and the radar's
    records (db/memeradar, their 1 h outcome). Dead = gone, a pool under $1k or 90% down within the hour, by any of them. Also the radar's
    calls without traps: [the time each record was first good]."""
    lo = now - WEEK_DAYS * DAY_MS
    coins, good = {}, []

    def see(addr, t, dead):
        if not isinstance(addr, str) or not B58.match(addr) or not t or not lo <= t <= now:
            return
        c = coins.setdefault(addr, {"t": t, "dead": None})
        c["t"] = min(c["t"], t)
        if dead is not None:
            c["dead"] = bool(dead) or bool(c["dead"])
    for doc in recent_docs(d, "memeyoung", lo).values():
        t0 = _num(doc.get("t")) if isinstance(doc, dict) else None
        if not t0:
            continue
        res = (doc.get("outs") or {}).get("1") if isinstance(doc.get("outs"), dict) else None
        got = {}
        for o in (M.settled(res, 1.0) if isinstance(res, dict) else []):
            got.setdefault(o.get("sym"), o)
        for p in doc.get("picks") or []:
            if isinstance(p, dict):
                o = got.get(p.get("sym"))
                see(p.get("addr"), t0 - (_num(p.get("ageMin")) or 0) * 60_000,
                    None if o is None else bool(o.get("gone") or (_num(o.get("mult")) is not None and _num(o["mult"]) < RUG_X)))
    for doc in recent_docs(d, "memeearly", lo).values():
        t0 = _num(doc.get("t")) if isinstance(doc, dict) else None
        for c in (doc.get("coins") or []) if t0 else []:
            if isinstance(c, dict):
                see(c.get("addr"), _num(c.get("born")) or t0, _dead_early(c))
    for doc in recent_docs(d, "memeradar", lo).values():
        recs = doc.get("coins") if isinstance(doc, dict) and isinstance(doc.get("coins"), dict) else {}
        for addr, r in recs.items():
            if not isinstance(r, dict):
                continue
            out = r.get("out") if isinstance(r.get("out"), dict) else {}
            see(addr, _num(r.get("pool")) or _num(r.get("first")), out.get("rug1h") if isinstance(out.get("rug1h"), bool) else None)
            g = _num(r.get("good"))
            if g and lo <= g <= now:
                good.append(int(g))
    return coins, sorted(set(good)), os.path.isdir(os.path.join(d, "db", "memeradar"))


def wilson(k, n, z=1.96):
    """95% interval of a share k of n."""
    if not n:
        return 0.0, 1.0
    p, zz = k / float(n), z * z
    den = 1 + zz / n
    c, h = (p + zz / (2 * n)) / den, z * math.sqrt(p * (1 - p) / n + zz / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def day_data(d, now, R):
    """The numbers of the daily overview (Berlin days and hours): today's launches and their 1 h results, the 7-day rate, each hour's
    7-day count and share dead, the hours that stand out (the 95% interval excludes the 7-day rate in both halves of the week, n >= 30)."""
    coins, good, has_radar = launches(d, now)
    today = R.local(now).date()
    when = {}
    for c in coins.values():                     # each launch's Berlin hour and day, once
        lt = R.local(c["t"])
        when[c["t"]] = (lt.hour, lt.date() == today)
    hour = lambda t: when[t][0]
    rows = [(c["t"], c["dead"]) for c in coins.values()]
    known = [(t, x) for t, x in rows if x is not None]
    tod = [(t, x) for t, x in rows if when[t][1]]
    tk = [x for _, x in tod if x is not None]
    p7 = (sum(1 for _, x in known if x) / float(len(known))) if known else None
    mid = now - WEEK_DAYS * DAY_MS / 2.0
    hours = []
    for h in range(24):
        hk = [(t, x) for t, x in known if hour(t) == h]
        k = sum(1 for _, x in hk if x)
        side = None
        if p7 is not None and len(hk) >= HOUR_MIN_N:
            sides = []
            for half in ([z for z in hk if z[0] < mid], [z for z in hk if z[0] >= mid]):
                lo_, hi_ = wilson(sum(1 for _, x in half if x), len(half))
                sides.append("low" if half and hi_ < p7 else ("high" if half and lo_ > p7 else None))
            side = sides[0] if sides[0] and sides[0] == sides[1] else None
        hours.append({"h": h, "n": len(hk), "dead": k, "rate": (k / float(len(hk))) if hk else None, "side": side,
                      "today": sum(1 for t, _ in tod if hour(t) == h), "todayDead": sum(1 for t, x in tod if x and hour(t) == h)})
    return {"today": len(tod), "todayKnown": len(tk), "todayDead": sum(1 for x in tk if x), "n7": len(known), "dead7": sum(1 for _, x in known if x),
            "p7": p7, "hours": hours, "radar": sum(1 for g in good if R.local(g).date() == today) if has_radar else None,
            "nowH": R.local(now).hour, "nowM": R.local(now).minute}


def day_sentence(x):
    """The overview in two plain sentences, from the numbers only."""
    pc = lambda v: "%d%%" % round(100 * v)
    parts = ["%d new launch%s checked" % (x["today"], "" if x["today"] == 1 else "es")]
    if not x["todayKnown"]:
        dead = "no 1 h results yet"
    elif x["todayKnown"] < TODAY_MIN_N:
        dead = "%d of %d with a 1 h result dead within an hour" % (x["todayDead"], x["todayKnown"])
    else:
        dead = "%s dead within an hour" % pc(x["todayDead"] / float(x["todayKnown"]))
    if x["p7"] is not None and x["n7"] >= HOUR_FEW_N:
        dead += " (7-day: %s)" % pc(x["p7"])
    parts.append(dead)
    parts.append("radar: no records yet" if x["radar"] is None else "radar: %d call%s without traps" % (x["radar"], "" if x["radar"] == 1 else "s"))
    first = "Today: " + " · ".join(parts) + "."
    low = sorted([h for h in x["hours"] if h["side"] == "low"], key=lambda h: (h["rate"], h["h"]))
    high = sorted([h for h in x["hours"] if h["side"] == "high"], key=lambda h: (-h["rate"], h["h"]))
    named = []
    if low:
        named.append("Best hour so far: %02d:00 (%s dead within an hour; 7-day: %s)." % (low[0]["h"], pc(low[0]["rate"]), pc(x["p7"])))
    if high:
        named.append("Worst hour so far: %02d:00 (%s dead within an hour; 7-day: %s)." % (high[0]["h"], pc(high[0]["rate"]), pc(x["p7"])))
    return first, " ".join(named) if named else "No hour of the day stands out yet."


def _band(h, p7):
    if not h["n"] or p7 is None:
        return "none"
    dv = h["rate"] - p7
    return "g2" if dv <= -0.15 else ("g1" if dv <= -0.05 else ("b2" if dv >= 0.15 else ("b1" if dv >= 0.05 else "mid")))


def _hour_text(h):
    span = "%02d:00 to %02d:00" % (h["h"], (h["h"] + 1) % 24)
    week = ("last 7 days: %d with a 1 h result, %d dead (%d%%)" % (h["n"], h["dead"], round(100 * h["rate"]))) if h["n"] else "last 7 days: no 1 h result"
    today = "today: %d checked%s" % (h["today"], (", %d dead" % h["todayDead"]) if h["todayDead"] else "")
    return "%s · %s · %s" % (span, week, today)


def daily(D, R):
    """The daily overview for the Brain's panel: the sentences, the hour bar (tap a cell: its numbers; CSS radios, no script) and a table."""
    x = day_data(D["dir"], D["now"], R) if D.get("dir") else None
    if not x:
        return ""
    first, second = day_sentence(x)
    radios = "".join('<input type="radio" name="ohour" id="ohb-%d"%s aria-label="%02d:00">' % (h["h"], " checked" if h["h"] == x["nowH"] else "", h["h"]) for h in x["hours"])
    cells = "".join('<label for="ohb-%d" class="%s%s" title="%s"></label>' % (
        h["h"], _band(h, x["p7"]), " few" if h["n"] < HOUR_FEW_N else "", _e(_hour_text(h))) for h in x["hours"])
    now_x = 100.0 * (x["nowH"] + x["nowM"] / 60.0) / 24.0
    reads = "".join('<p class="r%d">%s</p>' % (h["h"], _e(_hour_text(h))) for h in x["hours"])
    ticks = "".join('<span style="left:%.3f%%">%02d</span>' % (100.0 * k / 24, k) for k in (0, 6, 12, 18, 24))
    legend = ('<div class="legend ohb-leg"><span style="--c:var(--hb-g2)">fewer dead than the 7-day rate</span><span style="--c:var(--hb-mid)">about the same</span>'
              '<span style="--c:var(--hb-b2)">more</span><span class="few">hatched: under %d results</span><span class="tod">outlined: today so far</span>'
              '<span class="nowk">▼ now</span></div>') % HOUR_FEW_N
    rows = "".join('<tr><td>%02d:00</td><td class="n">%d</td><td class="n">%d</td><td class="n">%s</td><td class="n">%d</td></tr>' % (
        h["h"], h["n"], h["dead"], ("%d%%" % round(100 * h["rate"])) if h["n"] else "–", h["today"]) for h in x["hours"])
    table = ('<details class="fold-lite"><summary>How it is counted · table</summary><p class="note">New launches the bot checked (scored list, early list and '
             'radar), each coin once, by the hour it launched. Dead: gone, a pool under $1k or 90%% down within the hour. The page counts, it does not advise.</p><div class="tbl"><table><thead><tr><th>hour</th><th class="n">7 days, with a 1 h result</th>'
             '<th class="n">dead within 1 h</th><th class="n">share</th><th class="n">checked today</th></tr></thead><tbody>%s</tbody></table></div></details>') % rows
    return ('<div class="oday"><span class="olab">Daily overview</span><p class="odsum">%s</p><p class="note">%s</p>'
            '<div class="ohb">%s<div class="ohb-bar" role="group" aria-label="Share of new launches dead within an hour, by hour of the day (%s), last 7 days">%s'
            '<i class="ohb-day" style="width:%.3f%%" aria-hidden="true"></i><i class="ohb-now" style="left:%.3f%%" aria-hidden="true"></i></div><div class="ohb-ticks" aria-hidden="true">%s</div><div class="ohb-read">%s</div></div>%s'
            '%s</div>') % (
        _e(first), _e(second), radios, _e(R.TZ_NAME), cells, now_x, now_x, ticks, reads, legend, table)


# ---------------------------------------------------------------- the full scan's strip on the Pick tab
def scan_strip(D, R):
    """`● Full scan · last 20:41 · next ≈ 21:40 · Scan now ↗`: the last start (db/memeruns), the next one expected and a plain link to
    the scan's page on GitHub (the script finds the repository on the page: the office's live box or the website's Scan now button; the
    HTML is the same with and without GITHUB_REPOSITORY). While the office's live view runs, the script says the scan is running now."""
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and _ms(r.get("t"))]
    last = int(_ms(runs[0]["t"])) if runs else 0
    nxt = R.next_scan_ms(D["now"], runs)
    hm = lambda ms: R.local(ms).strftime("%H:%M")
    state = ("last %s" % hm(last)) if last else "no scan yet"
    info = ("The full scan checks every source, names the pick and runs the paper account, about once an hour (about 26 minutes). "
            "The next start is estimated from the last scans. Scan now opens its page on GitHub: tap “Run workflow” there; "
            "a start while a scan runs waits until it ends. The Radar tab is the second, faster scan.")
    return ('<style>%s</style><div class="sstrip" data-sstrip data-run-t="%d" data-po-tz="%s"><span class="sdot%s" data-ss-dot aria-hidden="true"></span>'
            '<b>Full scan</b><span class="sst" data-ss-state>%s</span><span class="sst">next ≈ %s</span>'
            '<a class="sbtn" data-ss-now target="_blank" rel="noopener" hidden>Scan now ↗</a>'
            '<details class="sinfo"><summary aria-label="About the full scan">ⓘ</summary><p>%s</p></details></div><script>%s</script>') % (
        STRIP_CSS, last, "Europe/Berlin" if R.TZ_NAME == "Berlin" else "UTC", " ok" if last else "", _e(state), _e(hm(nxt)), _e(info), JS)


def hour_css():
    return "\n".join('#ohb-{0}:checked ~ .ohb-read .r{0} {{ display:block }} #ohb-{0}:checked ~ .ohb-bar label[for="ohb-{0}"] {{ outline:2px solid var(--fg); outline-offset:1px; z-index:1 }} '
                     '#ohb-{0}:focus-visible ~ .ohb-bar label[for="ohb-{0}"] {{ outline:2px solid var(--accent); outline-offset:2px }}'.format(h) for h in range(24))


STRIP_CSS = r"""
/* the full scan's strip on the Pick tab (page_office.py) */
.sstrip { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px; padding:8px 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface);
  font-size:var(--fs-s); color:var(--fg2); position:relative } .sstrip { border-radius:12px }
.sstrip b { color:var(--fg); font-weight:600 } .sstrip .sst { font-variant-numeric:tabular-nums; white-space:nowrap }
.sstrip .sst + .sst::before, .sstrip b + .sst::before { content:"·"; margin-right:10px; color:var(--muted) }
.sdot { width:9px; height:9px; border-radius:50%; background:var(--muted); flex:none } .sdot.ok { background:var(--good-mark) } .sdot.run { background:var(--accent); animation:opulse 1.2s ease-in-out infinite }
.sdot.late { background:var(--warn-mark) } .sdot.bad { background:var(--bad-mark) }
.sbtn { margin-left:auto; color:var(--accent); font-weight:600; text-decoration:none; white-space:nowrap; padding:2px 4px; min-height:24px; display:inline-flex; align-items:center }
.sbtn[hidden] { display:none } .sbtn:hover { text-decoration:underline }
.sinfo > summary { list-style:none; cursor:pointer; color:var(--muted); padding:0 4px; min-width:24px; text-align:center } .sinfo > summary::-webkit-details-marker { display:none }
.sinfo[open] { flex-basis:100% } .sinfo p { margin:4px 0 2px; font-size:var(--fs-s); color:var(--fg2) }
.sstrip[data-ss="run"] { border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) }
@media (prefers-reduced-motion: reduce) { .sdot.run { animation:none } }
"""

CSS = r"""
/* the office's agent cards, the Launch radar's desk and the daily overview (page_office.py); page tokens only, light and dark */
.ocards { display:flex; gap:8px; overflow-x:auto; scroll-snap-type:x mandatory; overscroll-behavior-x:contain; padding:2px 2px 10px; scrollbar-width:thin; max-width:100% }
.ocard { flex:0 0 152px; scroll-snap-align:start; display:grid; gap:3px; align-content:start; min-width:0; padding:9px 11px; border:1px solid var(--line); border-radius:8px;
  background:var(--surface); cursor:pointer } .ocard:hover { border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) }
.ocard.ext { border-style:dashed; border-color:color-mix(in srgb,var(--s3) 60%,var(--line)) }
.ocard .och { display:flex; align-items:center; gap:6px; min-width:0 } .ocard .ocn { font-weight:600; font-size:var(--fs-s); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.ocard .ocl { font-size:var(--fs-xs); line-height:1.35; color:var(--fg2); overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow-wrap:anywhere }
.ocard .ocs { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.ocard .chip { justify-self:start; font-size:11px; padding:1px 7px }
.olt { font-size:11px; line-height:1; color:var(--muted) } .olt.done { color:var(--good-mark) } .olt.failed { color:var(--bad-mark) } .olt.fallback { color:var(--warn-mark) } .olt.running { color:var(--accent) }
.ocard[data-live="work"] .olt { color:var(--accent); animation:opulse 1.2s ease-in-out infinite } .ocard[data-live="done"] .olt { color:var(--good-mark) }
.ocard[data-live="fail"] .olt { color:var(--bad-mark) } .ocard[data-live="wait"] .olt { color:var(--muted) }
@media (min-width:700px) { .ocards { display:grid; grid-template-columns:repeat(auto-fill,minmax(138px,1fr)); overflow:visible; padding-bottom:2px } }
.ofl .desk[data-ext].off .who { display:none } .olegend .oj::before { width:22px; height:12px; border-radius:6px; background:color-mix(in srgb,var(--s3) 18%,var(--surface)); border:1px solid var(--s3) } .ofl .pill.own { fill:color-mix(in srgb,var(--s3) 18%,var(--surface)); stroke:var(--s3) }
.oext .olinkb { color:var(--accent); cursor:pointer; text-decoration:underline }
.oday { display:grid; gap:8px; padding-top:12px; border-top:1px solid var(--line2) } .oday p { margin:0 } .oday .odsum { font-weight:600; overflow-wrap:anywhere }
.oday { --hb-g2:color-mix(in oklch,var(--good-mark) 78%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 38%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 16%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 38%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 78%,var(--surface));
  --hb-none:var(--line2) }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .oday { --hb-g2:color-mix(in oklch,var(--good-mark) 90%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 55%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 20%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 55%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 90%,var(--surface)) } }
:root[data-theme="dark"] .oday { --hb-g2:color-mix(in oklch,var(--good-mark) 90%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 55%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 20%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 55%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 90%,var(--surface)) }
.ohb { display:grid; gap:4px; min-width:0 } .ohb > input { position:fixed; top:0; left:0; opacity:0; pointer-events:none }
.ohb-bar { position:relative; display:grid; grid-template-columns:repeat(24,minmax(0,1fr)); gap:2px; padding-top:9px }
.ohb-bar label { height:30px; border-radius:3px; background:var(--hb-none); cursor:pointer; position:relative }
.ohb-bar label.g2 { background-color:var(--hb-g2) } .ohb-bar label.g1 { background-color:var(--hb-g1) } .ohb-bar label.mid { background-color:var(--hb-mid) }
.ohb-bar label.b1 { background-color:var(--hb-b1) } .ohb-bar label.b2 { background-color:var(--hb-b2) }
.ohb-bar label.few, .ohb-leg .few::before { background-image:repeating-linear-gradient(135deg,transparent 0 3px,color-mix(in srgb,var(--surface) 72%,transparent) 3px 5px) }
.ohb-day { position:absolute; left:-3px; top:6px; bottom:-3px; border:1.5px solid color-mix(in srgb,var(--fg) 55%,transparent); border-radius:5px; pointer-events:none; min-width:6px }
.ohb-now { position:absolute; top:0; width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-top:7px solid var(--fg); transform:translateX(-5px) }
.ohb-ticks { position:relative; height:16px; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.ohb-ticks span { position:absolute; top:0; transform:translateX(-50%) } .ohb-ticks span:first-child { transform:none } .ohb-ticks span:last-child { transform:translateX(-100%) }
.ohb-read p { display:none; font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums }
.ohb-leg .few::before { background-color:var(--hb-mid) } .ohb-leg .tod::before { background:none; box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--fg) 55%,transparent) }
.ohb-leg .nowk::before { display:none }
""" + hour_css()

# The page script: the Launch radar's desk, card and panel follow the Radar tab's script (window event memebot-radar, detail {doc, state,
# via}); the full scan's strip follows the office's live script (memebot-live, detail {state, status}) and finds the repository for its
# Scan now link. Text only through textContent; nothing is fetched. MemebotOffice.look and .scan are the decisions (node checks them).
JS = r"""
(function(){
if(window.MemebotOffice)return;
var D=document,last=null,lastScan=null;
var LOOK={running:['running','on watch'],late:['fallback','late'],stopped:['skipped','stopped'],off:['skipped','switched off'],hours:['skipped','outside its hours'],none:['skipped','not started yet']};
var HOSTS=[['dexscreener','DexScreener'],['rugcheck','RugCheck'],['pump.fun','pump.fun'],['pumpfun','pump.fun'],['geckoterminal','GeckoTerminal'],['rpc','Solana RPC'],['jupiter','Jupiter'],['launchlab','LaunchLab'],['github','GitHub'],['supabase','Supabase']];
function isn(v){return typeof v==='number'&&isFinite(v);}
function n(v){return isn(v)?Math.round(v):0;}
function zone(){var b=D.querySelector('[data-po-tz]');return b?b.getAttribute('data-po-tz')||'UTC':'UTC';}
function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:zone()});}catch(e){return new Date(ms).toISOString().slice(11,16);}}
function all(s){return Array.prototype.slice.call(D.querySelectorAll(s));}
function set(e,t){if(e&&e.textContent!==t)e.textContent=t;}
function cls(e,c){if(e.getAttribute('class')!==c)e.setAttribute('class',c);}
var O=window.MemebotOffice={
  // the radar's light, word, line and small number for its state (page_office.look says the same at build time)
  look:function(st,doc,fmt){var d=doc&&typeof doc==='object'?doc:null,L=LOOK[st]||LOOK.none,light=L[0],word=L[1],c=d&&d.counts&&typeof d.counts==='object'?d.counts:null,line;fmt=fmt||hhmm;
    if(st==='running'&&d&&d.state==='degraded'){light='fallback';word='on watch, some checks failing';}
    if(st==='off')line='switched off on GitHub';
    else if(st==='hours')line=d&&isn(d.next)&&d.next>0?'outside its hours · next start '+fmt(d.next):'outside its hours';
    else if(st==='none'||!c)line='starts with the next full scan';
    else line=n(c.seen)+' seen · '+n(c.good)+' without traps · '+n(c.pushed)+' pushed';
    var ck=d&&isn(d.t)&&st!=='none'?'checked '+fmt(d.t):'no check yet';
    return {light:light,word:word,line:line,stat:d&&isn(d.t)&&st!=='none'?ck:'own job',checked:ck,here:st==='running'||st==='late'};},
  // the full scan's strip for a live-view state (MemebotLive.state): null keeps the page's own words
  scan:function(st,doc,runT,fmt){var d=doc&&typeof doc==='object'?doc:null,t=d&&isn(+d.t)?+d.t:0,up=d?+(d.updated||d.end)||0:0;fmt=fmt||hhmm;
    if(!d||!(t>runT))return null;
    if(st==='live')return {dot:'run',text:'running now · started '+fmt(t)};
    if(st==='paused')return {dot:'late',text:'started '+fmt(t)+' · no update since '+fmt(up)};
    if(st==='done')return {dot:'ok',text:'finished '+fmt(up)+' · new page on its way'};
    if(st==='stopped')return {dot:'bad',text:'stopped '+fmt(up)};
    return null;},
  radar:function(det){if(det&&typeof det==='object')last=det;draw();},
  hosts:HOSTS};
function host(k){k=String(k).toLowerCase();for(var i=0;i<HOSTS.length;i++)if(k.indexOf(HOSTS[i][0])>=0)return HOSTS[i][1];return String(k).slice(0,40);}
function draw(){
  if(!last)return;
  var doc=last.doc&&typeof last.doc==='object'&&last.doc.kind==='radar'?last.doc:null,L=O.look(String(last.state||'none'),doc);
  all('g[data-ext="radar"]').forEach(function(g){cls(g,'desk'+(L.here?'':' off'));var s=g.querySelector('.scr');if(s)cls(s,'scr'+(L.light==='fallback'?' fallback':''));});
  all('[data-ext-lt="radar"]').forEach(function(e){cls(e,'olt '+L.light);});
  all('[data-ext-word="radar"]').forEach(function(e){set(e,L.word);});
  all('[data-ext-chip="radar"]').forEach(function(e){cls(e,'chip '+({running:'neutral',fallback:'warn'}[L.light]||''));});
  all('[data-ext-line="radar"]').forEach(function(e){set(e,L.line);});
  all('[data-ext-stat="radar"]').forEach(function(e){set(e,L.stat);});
  all('[data-ext-checked="radar"]').forEach(function(e){set(e,L.checked);});
  all('label[data-ext="radar"]').forEach(function(e){var t=e.querySelector('.ocn');e.title=(t?t.textContent:'Launch radar')+': '+L.word;});
  if(!doc)return;
  var hs=doc.hosts&&typeof doc.hosts==='object'?doc.hosts:null,ls=Array.isArray(doc.lines)?doc.lines.filter(function(x){return typeof x==='string';}).slice(-6):null;
  if(hs)all('[data-ext-hosts="radar"]').forEach(function(box){box.textContent='';Object.keys(hs).slice(0,12).sort(function(a,b){return (hs[a]==='ok')-(hs[b]==='ok')||(a<b?-1:a>b?1:0);}).forEach(function(k){
    var v=String(hs[k]).slice(0,20),c=D.createElement('span');c.className='chip '+(v==='ok'?'':v==='limited'||v==='slow'?'warn':'bad');c.textContent=host(k)+' · '+v;box.appendChild(c);});});
  if(ls)all('[data-ext-lines="radar"]').forEach(function(ul){ul.textContent='';ls.forEach(function(x){var li=D.createElement('li'),ic=D.createElement('span'),tx=D.createElement('span'),m=D.createElement('span');
    li.className='oline';ic.className='ic';ic.textContent='›';tx.className='tx';tx.textContent=x.slice(0,200);li.appendChild(ic);li.appendChild(tx);li.appendChild(m);ul.appendChild(li);});});
}
function strip(){
  var box=D.querySelector('[data-sstrip]');if(!box)return;
  var st=box.querySelector('[data-ss-state]'),dot=box.querySelector('[data-ss-dot]');if(st._t==null){st._t=st.textContent;dot._c=dot.getAttribute('class');}
  var s=lastScan?O.scan(String(lastScan.state||''),lastScan.status,+box.getAttribute('data-run-t')||0):null;
  set(st,s?s.text:st._t);cls(dot,s?'sdot '+s.dot:dot._c);if(s)box.setAttribute('data-ss',s.dot);else box.removeAttribute('data-ss');
}
function link(){
  var a=D.querySelector('[data-ss-now]');if(!a||a.getAttribute('href'))return;
  var b=D.querySelector('[data-live-src]'),m=b&&/^https:\/\/api\.github\.com\/repos\/([A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/contents\//.exec(b.getAttribute('data-live-src')||''),r=m?'https://github.com/'+m[1]:null;
  if(!r){var btn=D.querySelector('.live a.btn'),k=btn&&/^(https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/actions\/workflows\/scan\.yml$/.exec(btn.getAttribute('href')||'');r=k?k[1]:null;}
  if(r){a.href=r+'/actions/workflows/scan.yml';a.hidden=false;}
}
window.addEventListener('memebot-radar',function(e){O.radar(e&&e.detail);});
// a tap on a card opens its department; on a phone (one column) the panel is far below the floor plan, so it scrolls into view
D.addEventListener('click',function(e){var c=e.target&&e.target.closest&&e.target.closest('label.ocard');if(!c||window.innerWidth>=1080)return;
  var k=c.getAttribute('for'),p=k&&D.querySelector('.opanel.k-'+k.replace(/^od-/,'').replace(/[^a-z]/g,''));if(!p)return;
  setTimeout(function(){try{p.scrollIntoView({block:'start',behavior:window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}catch(x){}},30);});
window.addEventListener('memebot-live',function(e){lastScan=e&&e.detail&&typeof e.detail==='object'?e.detail:null;try{strip();}catch(x){}});
function ready(){try{link();}catch(e){}try{if(!last&&window.MemebotRadar&&MemebotRadar.last)O.radar(MemebotRadar.last);else draw();}catch(e){}try{strip();}catch(e){}}
if(D.readyState==='loading')D.addEventListener('DOMContentLoaded',ready);else ready();
})();
"""
