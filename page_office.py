#!/usr/bin/env python3
"""page_office.py: the agent office's newer parts on the page (fake money only: nothing here buys, sells or advises anything).

  radar desk       the Office tab opens with the Launch radar (its own job, radar.yml): one line with its light, its state in words
                   (running, round in progress, rounds failing, sleeping until HH:MM, late, stopped, off) and "every 2 min · last HH:MM ·
                   next HH:MM", then four stations of its last round, 2 x 2 on a phone and in one row on a desktop: Sources (the coins its
                   discovery lists found, the top 3 lists, the live feed's state), Checks (the coins under 10 minutes checked, the round's 2
                   most frequent red flags), Verdicts (no trap / watch / trap) and Push (the coin pushed this round, else the last coin
                   without traps). Drawn from mb/radar_live.json, then kept current by the radar's script on the New tab (memebot-radar
                   event). A tap opens New.
  desk's chat      right under the desk, the same round as a trading desk's group chat where the radar's bots post (desk_chat, at most
                   8 messages, words from radar.json only): Scout found a coin (where from, its pool's age, its liquidity), Checks names
                   what it passed, Skeptic its red flags or what was not checked, the Desk its verdict and whether it went to the phone,
                   for two coins of the round; one Desk line when the round failed, outside its hours or switched off; Scout again for a
                   fresh call of the curve watch ("On the curve: SYM at 82%, 14 min after mint", a paper test); Record the greens'
                   1 h results so far (hindsight: from 20 with a known outcome the counts the push says, "3 of 26 doubled within 1 h,
                   6 rugged"). The script says the same from the radar's event (MemebotOffice.chat).
  agent cards      under the desk (the GROKBOT + JEV layout): a grid of compact cards, 2 columns on a phone and 4 on a desktop, one per
                   agent of the last run. Each card has its icon on a badge in its state colour (done, at work, fallback, failed, skipped),
                   its name, one number (how long it worked) and one line (its result, cut to one line). A tap opens the Details fold at the
                   agent's department. While a scan runs, the office's live script marks the cards through the hooks the panels already
                   have (data-live, data-live-chip, -line).
  balance line     under the cards: the paper account's profit or loss after every run since the restart (memecurve "paper"), compact.
  details fold     everything else of the office (the counts, the floor plan with its departments and legend, the team timeline, the
                   daily overview in the Brain's panel) sits in one fold, closed until it is opened (a tap on a card opens it too).
  radar's panel    the Launch radar runs in its own job (radar.yml), not in the hourly scan: it also has the second desk on the Analysts
                   platform, drawn from mb/radar_live.json (the scan copies the radar's last radar.json there before it starts). It never
                   counts in a department's light, the team timeline, the counts or "at work at once"; office.json is not changed. The
                   radar's script on the New tab (memebot-radar event) keeps its light and its line current on the page. The radar runs
                   one quick round after each full scan: "done" between rounds, "late" or "stopped" when the next round does not come.
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
CYCLE_MS, GRACE_MS, LATE_MS = 150_000, 60_000, 900_000   # a radar loop's cycle; "running" within 2 cycles and a minute, "late" up to 15 minutes
CYCLE_MAX_MS = 600_000      # a loop's own cadence (its next minus its time) counts up to this (the radar's 2 minutes count as 2.5)
HOUR_MS, DONE_GRACE_MS = 3_600_000, 1_800_000             # a radar round: "done" until its next round is due and 30 minutes more, "late" one more hour
SCAN_LEN_MS = 2_700_000              # a full scan's start to the radar round it starts at its end (about 26 to 35 minutes), with room
DAY_MS, WEEK_DAYS = 86_400_000, 7
HOUR_MIN_N = 30                      # an hour is named only with at least this many launches with a 1 h result in the 7 days
HOUR_FEW_N = 20                      # a cell with fewer is hatched
DEAD_LIQ, RUG_X = 1_000.0, 0.10      # dead within an hour (the rug study's rule): gone, a pool under $1k, or 90% down
TODAY_MIN_N = 10                     # today's share is given as a percentage from this many results on
CARD_LINE = 60                       # an agent card's line: at most this many characters (the live view's "Now: ..." line too)
HOSTS = (("curve list", "Curve list (pump.fun)"), ("curve trades", "Curve trades (live feed)"), ("curve watch", "Curve watch"),   # the curve watch's (curve_hosts)
         ("dexscreener", "DexScreener"), ("rugcheck", "RugCheck"), ("pump.fun", "pump.fun"), ("pumpfun", "pump.fun"), ("geckoterminal", "GeckoTerminal"),
         ("rpc", "Solana RPC"), ("jupiter", "Jupiter"), ("launchlab", "LaunchLab"), ("github", "GitHub"), ("supabase", "Supabase"),
         ("pumpportal", "live feed"), ("tweets", "X tweets"))   # the live pump.fun feed (radar_feed.py), named as the desk names it,
                                                                # and X's tweet endpoint (radar_src's host label "x tweets")
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
LOOK = {"running": ("running", "running"), "done": ("done", "done"), "late": ("fallback", "late"), "stopped": ("failed", "stopped"), "off": ("skipped", "switched off"),
        "hours": ("skipped", "outside its hours"), "none": ("skipped", "not started yet")}     # stopped is red, late amber: the radar's colours on the New tab
QUIET = ("off", "hours", "none")     # states whose last check is not news: no notes, no host chips
CHIP = {"running": "neutral", "fallback": "warn", "failed": "bad", "done": "good"}
SOON_MS, ROUND_MS = 10_000, 180_000  # the desk says "round in progress" from 10 s after the doc's next round for up to 3 minutes
SRC = re.compile(r"^[a-z][A-Za-z0-9:_-]{0,23}$")     # a discovery list's name ("gt:new"), as page_radar keeps it
NAME = re.compile(r"^[A-Za-z0-9_.]{1,32}$")
VERDICTS = ("good", "watch", "trap")
FEED = {"ok": "on"}                  # the live pump.fun feed (hosts.pumpportal): "live feed on", else its state (limited, off)
CHAT_MAX = 8                         # the desk's chat: at most this many messages (two coins of the round, a curve call and the record)
CURVE_FRESH_MS = 10 * 60_000         # a curve watch call this recent (by the doc's clock) is news in the chat: Scout names it
CURVE_WORDS = {"ok": "no trap found yet", "risky": "risky", "unknown": "not fully checked"}   # its quick check in words (page_radar.CURVE_VW's);
                                     # a call whose check found a trap is never Scout's news (as the curve push, it stays quiet about it)
CURVE_HOSTS = (("pump.fun", "curve list"), ("trades", "curve trades"))   # the curve block's hosts -> the radar panel's chips (HOSTS names them)
CURVE_HST = re.compile(r"[a-z]{1,12}")   # a curve host's state as page_radar's whitelist keeps it (fullmatch)
HOST_FINE = ("ok", "unavailable")    # host states that are no problem: plain chips, after the problems ("unavailable": the curve trades a client
                                     # without a paid key never gets; the watch reads pump.fun's list, its normal mode)
CHAT_CHIPS = 3                       # a message names this many chips, then "+N more"
TOO_FEW = 20                         # the greens' 1 h prices before the record gives shares (the New tab's Track record: MemebotRadar.TOO_FEW)
# the chat's text from the doc: these become spaces (controls, C1 too, bidi marks, embeddings, overrides and isolates, a BOM), a superset of
# both whitelists' sets (page_radar._str, MemebotRadar.clean's str), so the build and the script show the same text whichever cut it first,
# and no symbol turns the rest of a line around; a chip of nothing but CHAT_BLANK (what Python's strip() or the script's trim() drops) says
# nothing. Regex class bodies, the same in both languages (the script gets them through CH)
CHAT_CTRL = r"\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff"
CHAT_BLANK = r"\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
CHAT_BIG = 1e15                      # a number the chat prints is under this (whole numbers print alike in Python and the script up to 2**53)
WHO = {"scout": "Scout", "checks": "Checks", "skeptic": "Skeptic", "desk": "Desk", "record": "Record"}
# each speaker's badge: strokes in a 16 x 16 box (paths only, so the script draws the same), in its station's colour (DESK_CSS)
AVATAR = {"scout": ["M2.5 7a4.5 4.5 0 1 0 9 0a4.5 4.5 0 1 0-9 0", "M10.4 10.4 14 14"],
          "checks": ["M8 1.8 13.5 4v4c0 3.2-2.3 5.6-5.5 6.5C4.8 13.6 2.5 11.2 2.5 8V4z", "M5.6 8.2l1.7 1.7 3.2-3.4"],
          "skeptic": ["M8 2.2 14.2 13.3H1.8z", "M8 6.6v3.1", "M8 11.5v.2"],
          "desk": ["M2 8a6 6 0 1 0 12 0a6 6 0 1 0-12 0", "M5.2 8a2.8 2.8 0 1 0 5.6 0a2.8 2.8 0 1 0-5.6 0", "M8 8l4.3-4.3"],
          "record": ["M2.5 13.5h11", "M4.5 11V8", "M8 11V5", "M11.5 11V3"]}
try:
    from page_radar import LABELS     # the words for a red flag's name (the radar's own)
except ImportError:                   # a copy of the code without page_radar.py: the names as words
    LABELS = {}
try:
    from page_radar import clean_doc  # the New tab's whitelist: the doc the radar's event carries to the desk's chat
except ImportError:                   # without page_radar.py there is no radar on New and no event: no chat
    clean_doc = None


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
    src = doc.get("src") if isinstance(doc.get("src"), dict) else {}
    lg = doc.get("lastGood") if isinstance(doc.get("lastGood"), dict) and isinstance(doc["lastGood"].get("addr"), str) and B58.match(doc["lastGood"]["addr"]) else None
    whole = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v == int(v) and 0 <= v <= 100_000
    return {"t": int(_ms(doc["t"])), "next": _ms(doc.get("next")), "state": _str(doc.get("state"), 20), "why": _str(doc.get("why"), 160),
            "run": {"start": _ms(run.get("start")), "end": _ms(run.get("end")), "cycle": _num(run.get("cycle")), "mode": run.get("mode") if run.get("mode") in ("round", "loop") else ""},
            "counts": {k: _num(c.get(k)) for k in ("seen", "good", "pushed", "seenAgeMed")} if isinstance(doc.get("counts"), dict) else None,
            "hosts": dict({_str(k, 40): _str(v, 20) for k, v in list(hosts.items())[:12] if isinstance(k, str) and isinstance(v, str)}, **curve_hosts(doc.get("curve"))),
            "notes": [_str(x, 160) for x in (doc.get("notes") or [])[:4] if isinstance(x, str)] if isinstance(doc.get("notes"), list) else [],
            "lines": [_str(x, 200) for x in (doc.get("lines") or [])[-6:] if isinstance(x, str)] if isinstance(doc.get("lines"), list) else [],
            "src": {k: int(v) for k, v in list(src.items())[:12] if isinstance(k, str) and SRC.match(k) and whole(v)},
            "coins": desk_coins(doc.get("coins"), 5), "others": desk_coins(doc.get("others"), 40),
            "lastGood": {"sym": _str(lg.get("sym"), 24), "at": _ms(lg.get("at"))} if lg else None}


def curve_hosts(cv):
    """The curve watch's hosts for the radar panel's chips (after the radar's own twelve): "curve list" (pump.fun's list of coins on their curve)
    and "curve trades" (the followed coins' trades on the live feed) with their states, one "curve watch" off while the watch is off; {}
    without a curve block. The script's draw says the same from the event's doc (MemebotRadar.cleanCurve kept the same)."""
    if not isinstance(cv, dict):
        return {}
    if (cv.get("state") if cv.get("state") in ("on", "limited", "off") else "off") == "off":
        return {"curve watch": "off"}
    hs = cv.get("hosts") if isinstance(cv.get("hosts"), dict) else {}
    return {label: hs[k] for k, label in CURVE_HOSTS if isinstance(hs.get(k), str) and CURVE_HST.fullmatch(hs[k])}


def desk_coins(v, n):
    """A radar.json's coins or others as the desk counts them: address, symbol, verdict, push time and red flags; at most n."""
    out = []
    for c in v if isinstance(v, list) else []:
        if isinstance(c, dict) and isinstance(c.get("addr"), str) and B58.match(c["addr"]):
            hard = c.get("hard") if isinstance(c.get("hard"), list) else []
            out.append({"addr": c["addr"], "sym": _str(c.get("sym"), 24), "v": c.get("v") if c.get("v") in VERDICTS else "watch", "push": _ms(c.get("push")),
                        "hard": [x for x in hard if isinstance(x, str) and NAME.match(x)][:20]})
    return out[:n]


def is_round(doc):
    """A radar.json of one round (launch_radar.py round: state done, or degraded when its cycle failed)."""
    return bool(doc) and (doc.get("state") == "done" or ((doc.get("run") or {}).get("mode") == "round"))


def radar_state(doc, ref):
    """running | done | late | stopped | off | hours | none at the time ref (ms), as the New tab's MemebotRadar.radarState names them: a
    round is done until its next round is due (doc next, else an hour after it) and 30 minutes more, then late for an hour, then stopped."""
    if not doc:
        return "none"
    age = ref - doc["t"]
    if doc.get("state") == "off":
        return "off"
    if doc.get("state") == "hours":
        return "stopped" if doc.get("next") and doc["t"] + age > doc["next"] + HOUR_MS else "hours"     # MemebotRadar.radarState: the first scan starts it
    if is_round(doc):
        over = ref - (doc.get("next") or doc["t"] + HOUR_MS)
        return "done" if over <= DONE_GRACE_MS else ("late" if over <= DONE_GRACE_MS + HOUR_MS else "stopped")
    nx, t = doc.get("next"), doc.get("t")
    cyc = min(CYCLE_MAX_MS, max(CYCLE_MS, nx - t)) if isinstance(nx, (int, float)) and isinstance(t, (int, float)) and nx > t else CYCLE_MS   # MemebotRadar.cycle
    return "running" if age <= 2 * cyc + GRACE_MS else ("late" if age <= LATE_MS else "stopped")


def next_words(doc, now, scan, hhmm):
    """The next round after a round (the New tab's pill says the same: MemebotRadar.nextWords): "next about HH:MM" until doc next, then
    "next due since HH:MM"; without a next (a round by hand more than 3 h after the scan's last one) the next full scan starts one:
    "next after the HH:MM scan" from the scan strip's estimate (scan, ms; an hour later each time that scan should be over by now),
    else "next after the next full scan". now: ms (None: the round's own time)."""
    now = now if now is not None else doc["t"]
    if doc.get("next"):
        return ("next about " if now < doc["next"] else "next due since ") + hhmm(doc["next"])
    if scan:
        s, ref = scan, max(doc["t"], now)
        while s + SCAN_LEN_MS < ref:
            s += HOUR_MS
        return "next after the %s scan" % hhmm(s)
    return "next after the next full scan"


def look(state, doc, hhmm, now=None, scan=None):
    """The desk's light, word, line and number (its card's: the time of its last check) for a radar state at the time now (ms), with the
    full scan's next start (scan, ms: the strip's) for a round that names no next one (the page script's MemebotOffice.look says the same)."""
    light, word = LOOK.get(state, LOOK["none"])
    lead = word if state in ("late", "stopped") else ""
    if state == "running" and doc and doc.get("state") == "degraded":
        light, word, lead = "fallback", "running, some checks failing", "checks failing"
    elif state == "done" and doc and doc.get("state") == "degraded":
        light, word, lead = "fallback", "last round had errors", "checks failing"
    c = (doc or {}).get("counts") or None
    if state == "off":
        line = "switched off on GitHub"
    elif state == "hours":
        line = ("outside its hours · next start %s" % hhmm(doc["next"])) if doc and doc.get("next") else "outside its hours"
    elif state == "none":
        line = "not started yet"
    elif not c:
        line = (lead + " · " if lead else "") + "no counts yet"
    elif lead and state in ("late", "stopped"):        # late or stopped: the counts are its last check's, not news
        line = "%s · %d seen, %d without traps" % (lead, _int(c.get("seen")), _int(c.get("good")))
    else:
        line = (lead + " · " if lead else "") + "%d seen · %d without traps · %d pushed" % (_int(c.get("seen")), _int(c.get("good")), _int(c.get("pushed")))
    checked = ("%s %s" % ("last round" if is_round(doc) else "checked", hhmm(doc["t"]))) if doc and state != "none" else "no check yet"
    until = (" · " + next_words(doc, now, scan, hhmm)) if doc and state == "done" else ""
    return {"light": light, "word": word, "line": line, "stat": hhmm(doc["t"]) if doc and state != "none" else "own job", "checked": checked,     # the time of its last check
            "here": state in ("running", "done", "late"), "until": until, "quiet": state in QUIET}


def radar_ref(D, doc):
    """The time (ms) the radar's state is judged at on the page: the start of the scan that copied its file (the page is built about 25
    minutes later; the script brings it up to date), else now."""
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and _ms(r.get("t"))]
    now = _num(D.get("now")) or 0
    return min(now, max(doc["t"], _ms(runs[0]["t"]))) if doc and runs and now else now


def ext_agents(D, meta, R):
    """The agents that run in their own job, as office_data's agents (never 'ran' in the scan: no seconds, no bar, no count). The radar's
    state is judged at the start of the scan that copied its file (radar_ref)."""
    doc = radar_doc(D.get("dir"))
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and _ms(r.get("t"))]
    now = _num(D.get("now")) or 0
    ref = radar_ref(D, doc)
    st = radar_state(doc, ref)
    lk = look(st, doc, lambda ms: R.local(ms).strftime("%H:%M"), ref, R.next_scan_ms(now, runs) if now else None)   # the strip's next start
    name, job, tools = meta(RADAR)
    return [{"id": RADAR, "ext": True, "dept": EXT_HOME[RADAR], "s": None, "e": None, "st": lk["light"], "bg": False, "out": lk["line"],
             "lines": (doc or {}).get("lines") or [], "waits": {}, "blocked": [], "ran": False, "open": False, "secs": 0.0, "here": lk["here"],
             "name": name, "job": job, "tools": tools, "state": st, "word": lk["word"], "stat": lk["stat"], "checked": lk["checked"], "until": lk["until"], "doc": doc}]


def host_chips(hosts):
    """The radar's hosts as chips (problems first): ok and unavailable plain (HOST_FINE), limited amber, down red."""
    out = []
    for k, v in sorted((hosts or {}).items(), key=lambda kv: (kv[1] in HOST_FINE, kv[0])):
        name = next((n for h, n in HOSTS if h in k.lower()), k)
        cls = "" if v in HOST_FINE else ("warn" if v in ("limited", "slow", "waiting") else "bad")
        out.append('<span class="chip %s">%s · %s</span>' % (cls, _e(name), _e(v)))
    return "".join(out)


def _e(s):
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def ext_panel(a, R):
    """The Launch radar in the Analysts panel: its job, its state now (the radar's script on the New tab updates it), what its last check found,
    its notes, the services it calls and its last lines."""
    doc = a.get("doc") or {}
    quiet = a["state"] in QUIET              # switched off, outside its hours, never ran: its last check's notes and hosts are old news
    until = a.get("until") or ""
    notes = "" if quiet else "".join('<p class="omsg warn">%s</p>' % _e(n) for n in doc.get("notes") or [])
    lines = "".join(R.office_line(ln) for ln in doc.get("lines") or [])
    return ('<div class="oagent oext" data-agent="radar" data-ext="radar"><div class="who"><strong>%s</strong><span class="chip">own job</span>'
            '<span class="chip %s" data-ext-chip="radar" data-ext-word="radar">%s</span></div><p class="job">%s</p>'
            '<p class="clk"><span data-ext-checked="radar">%s</span><span data-ext-until="radar">%s</span> · one round after each scan</p>'
            '<div><span class="olab">Output</span><p class="oout" data-ext-line="radar">%s</p></div><div data-ext-notes="radar">%s</div>'
            '<div><span class="olab">Connected tools</span><div class="chips" data-ext-hosts="radar"%s>%s</div><p class="note" data-ext-wired="radar"%s>Wired to %s.</p></div>'
            '<div><span class="olab">Latest lines</span><ul class="olines" data-ext-lines="radar">%s</ul></div>'
            '<p class="note olinkp" data-po-radar><label class="olinkb" for="tab-young">Open the radar</label></p></div>') % (
        _e(a["name"]), CHIP.get(a["st"], ""), _e(a["word"]), _e(a["job"]), _e(a["checked"]), _e(until), _e(a["out"]), notes,
        " hidden" if quiet else "", "" if quiet else host_chips(doc.get("hosts")), "" if quiet or not doc.get("hosts") else " hidden", _e(", ".join(a["tools"])), lines)


# ---------------------------------------------------------------- the radar desk on top of the Office tab
def ago(ms):
    """'just now' under a minute, else '34 min ago', '3 h ago', '2 days ago' (the New tab's MemebotRadar.ago)."""
    m = ms / 60000.0
    return "just now" if ms < 60_000 else ("%d min" % m if m < 60 else "%d h" % (m / 60) if m < 2880 else "%d days" % (m / 1440)) + " ago"


def desk_look(st, doc, now, hhmm, labels=None):
    """The desk for a radar state (radar_state's, the New tab's MemebotRadar.radarState) at the time now (ms): its light, its state in words,
    the line after it, whether the stations are hidden (quiet: switched off, outside its hours, not started) or the last round's (dim: late,
    stopped, failing), and the four stations [key, name, [[class, number], ...], line]. "round in progress": the doc's next round is 10 s to 3
    minutes due and its doc not here yet. A degraded doc (rounds failing: launch_radar.degraded drops the list) checked nothing: its stations
    are dim and say so. The script's MemebotOffice.desk says the same."""
    d, labels = doc or {}, LABELS if labels is None else labels
    t, nx = d.get("t"), d.get("next")
    if st in ("running", "done") and nx and nx + SOON_MS < now <= nx + ROUND_MS:
        st = "progress"
    err = d.get("state") == "degraded" and st in ("running", "progress", "done")
    light = "fallback" if err else {"running": "running", "progress": "running", "done": "done", "late": "fallback", "stopped": "failed"}.get(st, "skipped")
    sleep = ("sleeping until " + hhmm(nx)) if nx and now < nx else "sleeping"
    word = {"running": "running", "progress": "round in progress", "done": sleep, "hours": sleep, "late": "late", "stopped": "stopped", "off": "off"}.get(st, "not started yet")
    fail = "last round failed" if is_round(doc) else "rounds failing"
    if err and st != "progress":
        word = fail
    every = math.floor((nx - t) / 30000.0 + 0.5) / 2.0 if nx and t and nx > t and not is_round(doc) else 0     # a loop's cadence to half a minute
    meta = (["every %s min" % ("%d" % every if every == int(every) else "%.1f" % every)] if every and st in ("running", "progress", "late") else []) + (["last " + hhmm(t)] if doc and st != "none" else []) \
        + (["next " + hhmm(nx)] if nx and (st == "running" or err and st == "done") else [])
    cs, seen = [], set()
    for c in (d.get("coins") or []) + (d.get("others") or []):      # a coin in both lists counts once
        if c["addr"] not in seen:
            seen.add(c["addr"])
            cs.append(c)
    src, feed = d.get("src") or {}, (d.get("hosts") or {}).get("pumpportal")
    order = lambda kv: (-kv[1], kv[0])
    found = (["live feed " + FEED.get(feed, feed)] if feed else []) + ["%s %d" % kv for kv in sorted(src.items(), key=order)[:3]]
    flags = {}
    for c in cs:
        for h in set(c["hard"]):
            flags[h] = flags.get(h, 0) + 1
    red = " · ".join("%s %d" % (labels.get(h, h.replace("_", " ")), k) for h, k in sorted(flags.items(), key=order)[:2])
    seen_n = (d.get("counts") or {}).get("seen")
    pushed = [c for c in d.get("coins") or [] if c["push"] and t and c["push"] >= t]
    lg = d.get("lastGood") or {}
    push = (", ".join(c["sym"] or "?" for c in pushed[:2]) + " pushed") if pushed else \
        ("last without traps: %s, %s" % (lg.get("sym") or "?", ago(now - lg["at"])) if lg.get("at") else "no push")
    return {"light": light, "word": word, "meta": " · ".join(meta), "quiet": st in QUIET, "dim": st in ("late", "stopped") or err,
            "st": [["src", "Sources", [["", str(sum(src.values())) if src else "–"]], " · ".join(found) or "no counts yet"],
                   ["chk", "Checks", [["", "%d" % math.floor(seen_n + 0.5) if seen_n is not None and not err else "–"]],
                    ("not checked: " + fail) if err else ("red flags: " + red) if red else ("no red flags" if cs else "no coin under 10 min")],
                   ["vd", "Verdicts", [[c, "–" if err else str(sum(1 for x in cs if x["v"] == v))] for c, v in zip(("good", "warn", "bad"), VERDICTS)], "no trap · watch · trap"],
                   ["push", "Push", [["", str(len(pushed))]], push]]}


def desk(D, R):
    """The Launch radar's desk on top of the Office tab: its state line and its four stations (desk_look), from mb/radar_live.json as the scan
    found it (its state judged at that scan's start: radar_ref); the script redraws it from the radar's event. The desk is the label of the
    New tab's radio: a tap opens the radar (the installed app: its hash link, as "Open the radar"). Under it, outside the label (a list is
    no label's content), the desk's chat about the same round (desk_chat), from the doc the radar's event carries (page_radar's whitelist),
    dimmed while the round is old news (late, stopped; a failing radar's one line is news)."""
    doc = radar_doc(D.get("dir"))
    ref = radar_ref(D, doc)
    hhmm = lambda ms: R.local(ms).strftime("%H:%M")
    st = radar_state(doc, ref)
    v = desk_look(st, doc, ref, hhmm)
    part = lambda c, x: '<span%s>%s</span>' % (' class="%s"' % c if c else "", _e(x))
    sts = "".join('<span class="odk-s" data-pd="%s"><span class="k">%s</span><b>%s</b><span class="l" title="%s">%s</span></span>' % (
        k, _e(name), "".join(part(c, x) for c, x in val), _e(line), _e(line)) for k, name, val, line in v["st"])
    try:
        chat = desk_chat(chat_doc(D.get("dir")), ref, hhmm) if doc else []      # no doc the desk counts (none, a wild time): no chat either
    except Exception:                    # the chat is an extra: a doc it cannot read leaves the desk as it is, without a chat
        chat = []
    return ('<style>%s</style><div class="odk-box"><label class="odesk" for="tab-young" data-po-desk data-po-tz="%s" title="Open the radar on the New tab (fake money only)">'
            '<span class="odk-h"><span class="odk-dot %s" data-pd-dot aria-hidden="true"></span><b>Launch radar</b><span class="odk-w" data-pd-word>%s</span>'
            '<span class="odk-m" data-pd-meta%s>%s</span></span><span class="odk-g%s" data-pd-g%s>%s</span></label>%s</div>') % (
        DESK_CSS, "Europe/Berlin" if R.TZ_NAME == "Berlin" else "UTC", v["light"], _e(v["word"]), "" if v["meta"] else " hidden", _e(v["meta"]),
        " dim" if v["dim"] else "", " hidden" if v["quiet"] else "", sts, chat_html(chat, st in ("late", "stopped")))


# ---------------------------------------------------------------- the desk's chat under the radar desk
def chat_doc(d):
    """mb/radar_live.json through the New tab's whitelist (page_radar.clean_doc, the doc MemebotRadar.clean hands the 'memebot-radar' event),
    so the chat at build time reads what the script reads later; None without the file or page_radar.py."""
    return clean_doc(M.load_json(os.path.join(d, "radar_live.json"), None)) if d and clean_doc else None


def _isn(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _at(v):
    """A time in ms between 2001 and 2100 (as _ms, but a number only: the script's typeof test), else None."""
    return v if _isn(v) and 1e12 < v < 4.1e12 else None


def _fin(v):
    """A number the chat may print: finite and under CHAT_BIG either way (1e22 would read '1e+22' in the script)."""
    return _isn(v) and abs(v) < CHAT_BIG


_CTRL, _BLANK = re.compile("[%s]" % CHAT_CTRL), re.compile("^[{0}]+|[{0}]+\\Z".format(CHAT_BLANK))


def _trim(s):
    """CHAT_BLANK off both ends: every space Python's strip() or the script's trim() knows (U+0085 and U+FEFF are one of each only)."""
    return _BLANK.sub("", s)


def _txt(v, n):
    """A string from the doc as the chat shows it, else '': CHAT_CTRL as spaces, cut to n UTF-16 units as the script's slice cuts them (an
    emoji counts 2 there), a half emoji at the end dropped (also when a whitelist's cut left it there). One space for one unit keeps the
    length: the doc from page_radar.clean_doc and the one from MemebotRadar.clean (cut in characters, in units) give the same text."""
    if not isinstance(v, str):
        return ""
    u = _CTRL.sub(" ", v).encode("utf-16-le", "surrogatepass")[:2 * n]
    return re.sub("[\ud800-\udbff]\\Z", "", u.decode("utf-16-le", "surrogatepass"))


def _usd(v):
    """$850, $23k, $1.2M: whole dollars, whole thousands, a tenth of a million (half up, as Math.floor(x + 0.5) rounds in the script)."""
    d, k = math.floor(v + 0.5), math.floor(v / 1e3 + 0.5)
    if d < 1000:
        return "$%d" % d
    if k < 1000:
        return "$%dk" % k
    m = "%.1f" % (math.floor(v / 1e5 + 0.5) / 10.0)
    return "$%sM" % (m[:-2] if m.endswith(".0") else m)


def _few(xs):
    """The first CHAT_CHIPS chips and '+N more' for the rest."""
    return " · ".join(xs[:CHAT_CHIPS]) + (" · +%d more" % (len(xs) - CHAT_CHIPS) if len(xs) > CHAT_CHIPS else "")


def chat_record(r):
    """The Record's line from radar.json record (the greens: calls without traps, their 1 h results; hindsight). With record.known's
    counts (whole numbers it may print, n from TOO_FEW on, neither count above n: app.radar_record's rule) the counts the push says,
    "Greens so far: 3 of 26 doubled within 1 h, 6 rugged (hindsight)". Else '' while it has no calls; shares only from TOO_FEW 1 h
    prices on, as the New tab's Track record (MemebotRadar.recLine); the calls alone when a share is missing (or is no share: outside
    0 to 1)."""
    if not isinstance(r, dict):
        return ""
    k = r.get("known") if isinstance(r.get("known"), dict) else {}
    n, win, rug = (k.get(x) for x in ("n", "win", "rug"))
    if all(_fin(x) and x >= 0 and math.floor(x) == x for x in (n, win, rug)) and n >= TOO_FEW and win <= n and rug <= n:
        return "Greens so far: %d of %d doubled within 1 h, %d rugged (hindsight)" % (win, n, rug)
    if not _fin(r.get("calls")) or r["calls"] < 1:
        return ""
    calls, n60 = math.floor(r["calls"]), math.floor(r["n60"]) if _fin(r.get("n60")) and r["n60"] >= 0 else 0
    share = lambda x: _isn(x) and 0 <= x <= 1
    if n60 >= TOO_FEW and share(r.get("win")) and share(r.get("rug")):
        pc = lambda x: "%d%%" % math.floor(100 * x + 0.5)
        return "Greens so far: %s doubled, %s rugged within 1 h (hindsight, %d of %d call%s)" % (pc(r["win"]), pc(r["rug"]), n60, calls, "" if calls == 1 else "s")
    return "Greens so far: %d call%s" % (calls, "" if calls == 1 else "s") + (", too few with a 1 h price yet (%d of %d)" % (n60, TOO_FEW) if n60 < TOO_FEW else "")


def chat_curve(cv, now):
    """Scout's line about the curve watch's newest call while it is fresh (at most CURVE_FRESH_MS before now, by the doc's clock), its quick
    check in words: "On the curve: SYM at 82%, 14 min after mint, quick check: no trap found yet" (the curve sold and the minutes since the
    mint at the call); a call whose check found a trap is never named (the newest other one is); '' without one. A coin still on its curve,
    called on paper only: the words report it, they never advise (MemebotOffice.chat says the same)."""
    rs = cv.get("recent") if isinstance(cv, dict) and isinstance(cv.get("recent"), list) else []
    best = None
    for r in rs:
        if isinstance(r, dict) and _at(r.get("t")) and r.get("v") != "trap" and (best is None or r["t"] > best["t"]):
            best = r
    if best is None or not 0 <= now - best["t"] <= CURVE_FRESH_MS:
        return ""
    sym, p, a = _trim(_txt(best.get("sym"), 24)) or "?", best.get("prog"), best.get("age")
    return "On the curve: %s" % sym + (" at %d%%" % math.floor(p + 0.5) if _fin(p) and 0 <= p <= 100 else "") + (
        (", under 1 min after mint" if a < 1 else ", %d min after mint" % math.floor(a)) if _fin(a) and a >= 0 else "") + \
        ", quick check: " + CURVE_WORDS.get(best.get("v"), CURVE_WORDS["unknown"])


def chat_coin(c, t, hhmm, labels):
    """One coin of the round in the chat: Scout found it (where from, its pool's age, its liquidity), Checks names what it passed (no line
    without an ok chip), Skeptic its red flags and warnings, else what was not checked, else no objection, and the Desk its verdict
    (trap found, watch only, no trap found and whether it went to the phone). The chip texts are the radar's own (traps.chips); a coin
    without a line (an older doc) falls back to its names in words."""
    sym = _trim(_txt(c.get("sym"), 24)) or "?"           # a symbol of nothing but blanks, controls or direction marks is '?'
    v = c.get("v") if c.get("v") in VERDICTS else "watch"
    found = [x for x in c["found"] if isinstance(x, str)] if isinstance(c.get("found"), list) else []
    lp, age, liq = _trim(_txt(c.get("lp"), 24)), c.get("age"), c.get("liq")
    facts = (["pump.fun graduated"] if "pf:graduated" in found else ["launched on " + lp] if lp else []) \
        + (["pool %d min old" % math.floor(age) if age >= 1 else "pool under 1 min old"] if _fin(age) and age >= 0 else []) \
        + ([_usd(liq) + " liquidity"] if _fin(liq) and liq >= 0 else [])
    line = [[x[0], _txt(x[1], 120)] for x in (c["line"] if isinstance(c.get("line"), list) else [])
            if isinstance(x, list) and len(x) >= 2 and isinstance(x[1], str) and _trim(_txt(x[1], 120))]
    names = lambda k: [x for x in (c[k] if isinstance(c.get(k), list) else []) if isinstance(x, str) and NAME.fullmatch(x)]
    ok = [x for lv, x in line if lv == "ok"]
    bad = [x for lv, x in line if lv in ("bad", "warn")] or [labels.get(h, h.replace("_", " ")) for h in names("hard") + names("soft")]
    unk = [x for lv, x in line if lv == "unk"] or [h.replace("_", " ") + " unknown" for h in names("unknown")]
    push = _at(c.get("push"))
    out = [["scout", "Found %s" % sym + (": " + ", ".join(facts) if facts else "")]]
    if ok:
        out.append(["checks", "%s passed: %s" % (sym, _few(ok))])
    out.append(["skeptic", ("Against %s: %s" % (sym, _few(bad))) if bad else ("Not checked for %s: %s" % (sym, _few(unk))) if unk else "No objection to %s" % sym])
    say = {"trap": "trap found, not listed", "watch": "watch only"}.get(v) or ("no trap found, sent to the phone" if push and push >= t else
                                                                             "no trap found, sent to the phone at " + hhmm(push) if push else "no trap found, listed, no push")
    out.append(["desk", "%s: %s" % (sym, say)])
    return out


def desk_chat(doc, now=None, hhmm=None, labels=None):
    """The desk's chat about the doc's round (the newest one: a loop's last cycle or the hourly round), as a trading desk's group chat where
    the radar's bots post: [[speaker, text], ...], at most CHAT_MAX, plain words from radar.json only (no new request, no model). Two coins
    of the round talk (chat_coin): the one pushed this round, else the first without traps, else the first listed; then the one that
    differs most (another push, else a trap, else another verdict, else the next); the second drops its Checks line when the chat would
    run over. An empty round: Scout says so. A round that failed, outside its hours or switched off: one Desk line instead of coins (an
    hours doc: sleeps until its next start, then waits for the first scan, then stopped, at radar_state's times, so it says what the desk says).
    The Record's line closes it when the record has calls. Never a buy, safe or clean: the desk reports, it does not advise; the record is
    hindsight. hhmm: ms -> 'HH:MM' (UTC without one); now: ms (the doc's time without one). The script's MemebotOffice.chat says the same."""
    d = doc if isinstance(doc, dict) and doc.get("kind") == "radar" and _isn(doc.get("t")) else None
    if not d:
        return []
    hhmm = hhmm or (lambda ms: dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc).strftime("%H:%M"))
    labels = LABELS if labels is None else labels
    t = d["t"]
    nx = _at(d.get("next"))
    now = now if _isn(now) else t
    st, run = d.get("state"), d.get("run") if isinstance(d.get("run"), dict) else {}
    rec = chat_record(d.get("record"))
    cur = chat_curve(d.get("curve"), now)        # a fresh curve call (the curve watch's paper test): Scout names it before the record
    out = []
    if st == "off":
        out.append(["desk", "Radar switched off on GitHub: no rounds"])
    elif st == "hours":     # until the hours begin; then the first full scan inside them starts it (radar_state: up to an hour, then stopped)
        out.append(["desk", "Radar sleeps: outside its hours" if not nx else ("Radar sleeps until %s" % hhmm(nx)) if now < nx else
                    ("Radar sleeps: the next round comes with the first scan after %s" % hhmm(nx)) if now <= nx + HOUR_MS else
                    "Radar stopped: no round since its hours began at %s" % hhmm(nx)])
    elif st == "degraded":
        out.append(["desk", "Last round failed: no coin checked" if run.get("mode") == "round" else "Rounds failing: no coin checked, the list is not current"])
    else:
        cs, seen = [], set()
        for c in (d["coins"] if isinstance(d.get("coins"), list) else []) + (d["others"] if isinstance(d.get("others"), list) else []):
            if isinstance(c, dict) and isinstance(c.get("addr"), str) and c["addr"] not in seen:     # a coin in both lists talks once
                seen.add(c["addr"])
                cs.append(c)
        v = lambda c: c.get("v") if c.get("v") in VERDICTS else "watch"
        pushed = lambda c: bool(_at(c.get("push"))) and c["push"] >= t
        first = lambda f, xs: next((c for c in xs if f(c)), None)
        if not cs:
            n = (d.get("counts") or {}).get("seen") if isinstance(d.get("counts"), dict) else None
            k = math.floor(n) if _fin(n) and n >= 1 else 0
            out.append(["scout", ("Found %d new pool%s under 10 minutes, none kept on the list" % (k, "" if k == 1 else "s")) if k else "No new pools under 10 minutes this round"])
        else:
            lead = first(pushed, cs) or first(lambda c: v(c) == "good", cs) or cs[0]
            rest = [c for c in cs if c is not lead]
            two = first(pushed, rest) or (first(lambda c: v(c) == "trap", rest) if v(lead) != "trap" else None) or first(lambda c: v(c) != v(lead), rest) or (rest[0] if rest else None)
            out = chat_coin(lead, t, hhmm, labels)
            more = chat_coin(two, t, hhmm, labels) if two else []
            room = CHAT_MAX - len(out) - (1 if rec else 0) - (1 if cur else 0)
            out += (more if len(more) <= room else [m for m in more if m[0] != "checks"])[:max(0, room)]
    return (out + ([["scout", cur]] if cur else []) + ([["record", rec]] if rec else []))[:CHAT_MAX]


def avatar(who):
    return '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">%s</svg>' % "".join('<path d="%s"/>' % p for p in AVATAR.get(who, []))


def chat_html(msgs, dim=False):
    """The chat as an ordered list (oldest first, as a chat reads): each message a speaker's badge in its colour, its name and its text,
    every text escaped; hidden while there is nothing to say. The script redraws it from the radar's event (data-pd-chat)."""
    items = "".join('<li class="och k-%s"><span class="och-a">%s</span><span class="och-t"><b>%s</b><span class="sr">: </span>%s</span></li>' % (
        who, avatar(who), _e(WHO.get(who, who)), _e(text)) for who, text in msgs if who in WHO)
    return '<ol class="ochat%s" data-pd-chat aria-label="The radar desk\'s chat about its last round (fake money only)"%s>%s</ol>' % (
        " dim" if dim else "", "" if items else " hidden", items)


# ---------------------------------------------------------------- the agent cards
# each agent's icon: strokes in a 16 x 16 box, drawn in the card's state colour (an agent without one shows its initial)
ICONS = {
    "dispatch": '<path d="M2.5 4h1M6 4h7.5M2.5 8h1M6 8h7.5M2.5 12h1M6 12h7.5"/>',
    "trainer": '<path d="M6 2h4M6.7 2v4.3L3.2 12.6A1.2 1.2 0 0 0 4.3 14.4h7.4a1.2 1.2 0 0 0 1.1-1.8L9.3 6.3V2M4.6 10.2h6.8"/>',
    "scouts": '<circle cx="8" cy="8" r="6"/><path d="M2 8h12M8 2c2.3 2.2 2.3 9.8 0 12M8 2c-2.3 2.2-2.3 9.8 0 12"/>',
    "candles": '<path d="M4 2.5v11M8 1.5v13M12 3.5v9"/><rect x="2.6" y="5" width="2.8" height="5" rx=".5"/><rect x="6.6" y="3.5" width="2.8" height="7" rx=".5"/>'
               '<rect x="10.6" y="6" width="2.8" height="4" rx=".5"/>',
    "spotter": '<path d="M1.5 8s2.4-4.6 6.5-4.6S14.5 8 14.5 8s-2.4 4.6-6.5 4.6S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>',
    "market": '<path d="M2 2.5h5.3l6.2 6.2-4.8 4.8L2.5 7.3z"/><circle cx="5.2" cy="5.6" r="1"/>',
    "analyst": '<path d="M2 3h12L9.5 8.6V13l-3 1.5V8.6z"/>',
    "deep": '<circle cx="7" cy="7" r="4.5"/><path d="M10.4 10.4 14 14"/>',
    "safety": '<path d="M8 1.8 13.5 4v4c0 3.2-2.3 5.6-5.5 6.5C4.8 13.6 2.5 11.2 2.5 8V4z"/><path d="M5.6 8.2l1.7 1.7 3.2-3.4"/>',
    "refresh": '<path d="M13.2 7.2A5.2 5.2 0 0 0 4 4.2M2.8 8.8A5.2 5.2 0 0 0 12 11.8M4 1.7v2.6h2.6M12 14.3v-2.6H9.4"/>',
    "trader": '<path d="M2.5 5.5h10.5l-2.6-2.6M13.5 10.5H3l2.6 2.6"/>',
    "reporter": '<path d="M4 1.8h5.4l2.9 3v9.4H4z"/><path d="M9.2 1.8v3.2h3.1M6 8.6h4.4M6 11.2h4.4"/>',
    "radar": '<circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="2.8"/><path d="M8 8l4.3-4.3"/>'}


def icon(aid, name):
    """The card's icon (inline SVG, no request) or the agent's initial."""
    if aid in ICONS:
        return '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">%s</svg>' % ICONS[aid]
    return '<b aria-hidden="true">%s</b>' % _e((str(name or aid or "?").strip() or "?")[0].upper())


def card_line(a, R):
    """A scan agent's one line on its card: its result, else its most telling line (a warning without its "! " mark, as the panel shows
    it), else its word (skipped, did not run)."""
    latest = R.office_latest(a["lines"])
    return a["out"] or (latest.lstrip("! ") if latest.startswith("!") else latest) or R.office_word(a)


def cards(info, R):
    """The grid under the radar's desk: one card per agent of the last run (in run order; the radar has the desk above), each with its icon
    on a badge in its state colour, its name, one number and one line. A card is the label of its department's radio, so a tap picks that
    department in the Details fold (the script opens the fold and brings the panel into view). Only spans inside a card: the cards are labels."""
    home = {m["id"]: d["key"] for d in info["depts"] + [info["brain"]] for m in d["agents"]}
    out = []
    for a in info["agents"]:
        st = a["st"] if a["st"] in R.OFFICE_ST else "skipped"
        line = card_line(a, R)
        word = R.office_word(a) + (", beside the others" if a["bg"] and a["ran"] else "")
        live = '<span class="chip" data-lv data-live-chip="%s" hidden></span><span class="ocl" data-lv data-live-line="%s" data-live-max="%d" hidden></span>' % (
            _e(a["id"]), _e(a["id"]), CARD_LINE)
        out.append('<label class="ocard" for="od-%s" data-agent="%s" title="%s: %s · %s"><span class="olt %s">%s</span>'
                   '<span class="ocn">%s</span><span class="ocs">%s</span><span class="ocl">%s</span>%s<span class="sr"> %s</span></label>' % (
                       _e(home.get(a["id"], "ops")), _e(a["id"]), _e(a["name"]), _e(word), _e(clip(line, 160)), st, icon(a["id"], a["name"]), _e(a["name"]),
                       _e(R.fmt_secs(a["secs"], True) if a["ran"] else "–"), _e(clip(line, CARD_LINE)), live, _e(word)))
    return ('<div class="ocards" data-po-tz="%s" data-po-tzn="%s" role="group" aria-label="The agents of the last scan: tap one to open its department">%s</div>' % (
        "Europe/Berlin" if R.TZ_NAME == "Berlin" else "UTC", _e(R.TZ_NAME), "".join(out)))


# ---------------------------------------------------------------- the paper account's line under the cards
def _eur(v, signed=False):
    """1,234.56 € with a real minus sign and a no-break space, as the Account card writes it."""
    s = format(abs(v), ",.2f")
    if v < 0 and s.strip("0.,"):
        return "−" + s + " €"
    return ("+" if signed and v > 0 else "") + s + " €"


def balance(D, R):
    """The paper account's profit or loss after every run since the restart (memecurve "paper", the Account card's balance line), compact:
    the number now on top, the line with break-even dashed. Recommend mode only; fake money."""
    P = D.get("paper") if isinstance(D.get("paper"), dict) else None
    if not P or not D.get("rec"):
        return ""
    since = _num(P.get("since")) or 0
    pts = sorted((int(_ms(c.get("t"))), _num(c["paper"].get("pnl"))) for c in D.get("curve") or []
                 if isinstance(c, dict) and _ms(c.get("t")) and _ms(c.get("t")) >= since and isinstance(c.get("paper"), dict) and _num(c["paper"].get("pnl")) is not None)
    now_v = _num((P.get("acct") or {}).get("pnl")) if isinstance(P.get("acct"), dict) else None
    now_v = now_v if now_v is not None else (pts[-1][1] if pts else None)
    tone = "flat" if now_v is None or abs(now_v) < 0.005 else ("good" if now_v > 0 else "bad")
    when = ("since %s" % R.local(since).strftime("%b %d")) if since else "since the restart"
    head = ('<div class="obal-h"><span class="k">Paper account</span><span class="s">P/L %s</span><b class="v">%s</b></div>' % (
        _e(when), _e(_eur(now_v, True) if now_v is not None else "–")))
    if len(pts) < 2:
        return '<div class="obal %s" data-po-bal>%s<p class="obal-e">the line starts after two runs</p></div>' % (tone, head)
    W, Hh, pad = 600.0, 64.0, 4.0
    t0, t1 = pts[0][0], pts[-1][0]
    vs = [v for _, v in pts] + [0.0]
    lo, hi = min(vs), max(vs)
    lo, hi = (lo - 1, hi + 1) if hi - lo < 1e-9 else (lo, hi)
    X = lambda t: (t - t0) / float((t1 - t0) or 1) * W
    Y = lambda v: pad + (hi - v) / (hi - lo) * (Hh - 2 * pad)
    path = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", X(t), Y(v)) for i, (t, v) in enumerate(pts))
    y0 = Y(0.0)
    return ('<div class="obal %s" data-po-bal>%s<div class="obal-c" role="img" aria-label="Paper account profit or loss after every run %s, now %s">'
            '<svg viewBox="0 0 %d %d" preserveAspectRatio="none" aria-hidden="true"><line class="z" x1="0" y1="%.1f" x2="%d" y2="%.1f"/>'
            '<path class="a" d="%s L%.1f %.1f L0 %.1f Z"/><path class="l" d="%s"/></svg></div></div>') % (
        tone, head, _e(when), _e(_eur(now_v, True) if now_v is not None else "–"), W, Hh, y0, W, y0, path, W, y0, y0, path)


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
    calls without traps, once per coin: {addr: the time it was first good}."""
    lo = now - WEEK_DAYS * DAY_MS
    coins, good = {}, {}

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
        picks = [p for p in doc.get("picks") or [] if isinstance(p, dict)]
        for p, o in young_outs(picks, (doc.get("outs") or {}).get("1") if isinstance(doc.get("outs"), dict) else None):
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
            if g and lo <= g <= now and isinstance(addr, str) and B58.match(addr):
                good[addr] = min(int(g), good.get(addr, int(g)))       # one call per coin; coins that turned good in one cycle share its ms
    return coins, good, os.path.isdir(os.path.join(d, "db", "memeradar"))


def young_outs(picks, res):
    """The scored list's picks with their settled 1 h result (or None). memebot.py writes one result per pick that has a price, in pick
    order, so the nth priced pick owns the nth result; a doc where that does not line up (an older shape) is matched by symbol."""
    rows = res.get("picks") if isinstance(res, dict) and isinstance(res.get("picks"), list) else []
    ok = {id(o) for o in (M.settled(res, 1.0) if isinstance(res, dict) else [])}
    priced = [p for p in picks if _num(p.get("px"))]
    if rows and len(priced) == len(rows) and all(isinstance(o, dict) and o.get("sym") == p.get("sym") for p, o in zip(priced, rows)):
        mine = {id(p): o for p, o in zip(priced, rows) if id(o) in ok}
        return [(p, mine.get(id(p))) for p in picks]
    got = {}
    for o in rows:
        if id(o) in ok:
            got.setdefault(o.get("sym"), o)
    return [(p, got.get(p.get("sym"))) for p in picks]


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
            "p7": p7, "hours": hours, "radar": sum(1 for g in good.values() if R.local(g).date() == today) if has_radar else None,
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
    """A cell's colour: strong only for an hour the sentence names (it stands out in both halves of the week), light for a smaller
    difference with at least HOUR_FEW_N results, grey otherwise (a difference over a few results is chance)."""
    if not h["n"] or p7 is None:
        return "none"
    if h["side"]:
        return "g2" if h["side"] == "low" else "b2"
    if h["n"] < HOUR_FEW_N:
        return "mid"
    dv = h["rate"] - p7
    return "g1" if dv <= -0.05 else ("b1" if dv >= 0.05 else "mid")


def _hour_text(h):
    span = "%02d:00 to %02d:00" % (h["h"], (h["h"] + 1) % 24)
    week = ("last 7 days: %d with a 1 h result, %d dead (%d%%)" % (h["n"], h["dead"], round(100 * h["rate"]))) if h["n"] else "last 7 days: no 1 h result"
    today = "today: %d checked%s" % (h["today"], (", %d dead" % h["todayDead"]) if h["todayDead"] else "")
    return "%s · %s · %s" % (span, week, today)


def day_numbers(x):
    """The overview's three big numbers: [(value, label, small line)]."""
    pc = lambda v: "%d%%" % round(100 * v)
    if not x["todayKnown"]:
        dead = ("–", "dead within 1 h", "no 1 h results yet")
    elif x["todayKnown"] < TODAY_MIN_N:
        dead = ("%d of %d" % (x["todayDead"], x["todayKnown"]), "dead within 1 h", "")
    else:
        dead = (pc(x["todayDead"] / float(x["todayKnown"])), "dead within 1 h", "")
    if x["p7"] is not None and x["n7"] >= HOUR_FEW_N:
        dead = dead[:2] + ("7-day: %s" % pc(x["p7"]),)
    radar = ("–", "radar calls without traps", "no records yet") if x["radar"] is None else ("%d" % x["radar"], "radar call%s without traps" % ("" if x["radar"] == 1 else "s"), "")
    return [("%d" % x["today"], "launch%s today" % ("" if x["today"] == 1 else "es"), ""), dead, radar]


def daily(D, R):
    """The daily overview for the Brain's panel: three big numbers, the sentences, the hour bar (tap a cell: its numbers; CSS radios, no
    script) and a fold with the legend's details and a table."""
    x = day_data(D["dir"], D["now"], R) if D.get("dir") else None
    if not x:
        return ""
    first, second = day_sentence(x)
    nums = "".join('<div><b>%s</b><span>%s</span>%s</div>' % (_e(v), _e(lab), ('<small>%s</small>' % _e(sub)) if sub else "") for v, lab, sub in day_numbers(x))
    radios = "".join('<input type="radio" name="ohour" id="ohb-%d"%s aria-label="%02d:00">' % (h["h"], " checked" if h["h"] == x["nowH"] else "", h["h"]) for h in x["hours"])
    cells = "".join('<label for="ohb-%d" class="%s%s%s" title="%s"></label>' % (
        h["h"], _band(h, x["p7"]), " few" if h["n"] < HOUR_FEW_N else "", (" " + h["side"]) if h["side"] else "", _e(_hour_text(h))) for h in x["hours"])
    now_x = 100.0 * (x["nowH"] + x["nowM"] / 60.0) / 24.0
    reads = "".join('<p class="r%d">%s</p>' % (h["h"], _e(_hour_text(h))) for h in x["hours"])
    ticks = "".join('<span style="left:%.3f%%">%02d</span>' % (100.0 * k / 24, k) for k in (0, 6, 12, 18, 24))
    legend = ('<div class="legend ohb-leg"><span style="--c:var(--hb-g2)">fewer dead</span><span style="--c:var(--hb-mid)">same</span>'
              '<span style="--c:var(--hb-b2)">more dead</span></div>')
    rows = "".join('<tr><td>%02d:00</td><td class="n">%d</td><td class="n">%d</td><td class="n">%s</td><td class="n">%d</td></tr>' % (
        h["h"], h["n"], h["dead"], ("%d%%" % round(100 * h["rate"])) if h["n"] else "–", h["today"]) for h in x["hours"])
    more = ('<div class="legend ohb-leg"><span style="--c:var(--hb-g2)">↓ fewer dead than the 7-day rate in both halves of the week (named above)</span>'
            '<span style="--c:var(--hb-g1)">a little fewer, could be chance</span><span style="--c:var(--hb-mid)">about the same, or under %d results</span>'
            '<span style="--c:var(--hb-b1)">a little more</span><span style="--c:var(--hb-b2)">↑ more in both halves</span><span class="few">hatched: under %d results</span>'
            '<span class="tod">outlined: today so far</span><span class="nowk">▼ now</span></div>') % (HOUR_FEW_N, HOUR_FEW_N)
    table = ('<details class="fold-lite"><summary>How it is counted · table</summary>%s<p class="note">New launches the bot checked (scored list, early list and '
             'radar), each coin once, by the hour it launched (%s). Dead: gone, a pool under $1k or 90%% down within the hour. The page counts, it does not advise.</p>'
             '<div class="tbl"><table><thead><tr><th>hour</th><th class="n">7 days</th><th class="n">dead 1 h</th><th class="n">share</th><th class="n">today</th></tr></thead>'
             '<tbody>%s</tbody></table></div><p class="note">7 days: launches with a 1 h result in the last 7 days · today: launches checked today.</p></details>') % (more, _e(R.TZ_NAME), rows)
    return ('<div class="oday"><span class="olab">Daily overview</span><div class="odn">%s</div><p class="odsum">%s</p><p class="note">%s</p>'
            '<div class="ohb">%s<div class="ohb-bar" role="group" aria-label="Share of new launches dead within an hour, by hour of the day (%s), last 7 days">%s'
            '<i class="ohb-day" style="width:%.3f%%" aria-hidden="true"></i><i class="ohb-now" style="left:%.3f%%" aria-hidden="true"></i></div><div class="ohb-ticks" aria-hidden="true">%s</div><div class="ohb-read">%s</div></div>%s'
            '%s</div>') % (
        nums, _e(first), _e(second), radios, _e(R.TZ_NAME), cells, now_x, now_x, ticks, reads, legend, table)


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
            "The next start is estimated from the last scans. Scan now opens its page on GitHub: tap “Run workflow” there and come back in about ten "
            "minutes; a start while a scan runs waits until it ends. The page is rebuilt after every scan and reloads itself (the app when you come "
            "back to it). The launch radar on the New tab runs one quick round right after each scan; each scan can be started on its own, and both "
            "can run at the same time.")
    return ('<style>%s</style><div class="sstrip" data-sstrip data-run-t="%d" data-next="%d" data-po-tz="%s"><span class="sdot%s" data-ss-dot aria-hidden="true"></span>'
            '<b>Full scan</b><span class="sst" data-ss-state>%s</span><span class="sst" data-ss-next>next ≈ %s</span>'
            '<a class="sbtn" data-ss-now target="_blank" rel="noopener" hidden><span>Scan now ↗</span></a>'
            '<details class="sinfo"><summary aria-label="About the full scan">ⓘ</summary><p>%s</p></details></div><script>%s</script>') % (
        STRIP_CSS, last, nxt, "Europe/Berlin" if R.TZ_NAME == "Berlin" else "UTC", " ok" if last else "", _e(state), _e(hm(nxt)), _e(info), JS)


def hour_css():
    return "\n".join('#ohb-{0}:checked ~ .ohb-read .r{0} {{ display:block }} #ohb-{0}:checked ~ .ohb-bar label[for="ohb-{0}"] {{ outline:2px solid var(--fg); outline-offset:1px; z-index:1 }} '
                     '#ohb-{0}:focus-visible ~ .ohb-bar label[for="ohb-{0}"] {{ outline:2px solid var(--accent); outline-offset:2px }}'.format(h) for h in range(24))


STRIP_CSS = r"""
/* the full scan's strip on the Pick tab (page_office.py): the one place for the next start and Scan now, so the website's Live box with its
   own Scan now button goes wherever the strip is on the page (the box stays in the HTML: the strip takes the repository from its link) */
.wrap:has([data-sstrip]) > .live { display:none }
.sstrip { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px; padding:8px 12px; border:1px solid var(--line); border-radius:12px; background:var(--surface);
  font-size:var(--fs-s); color:var(--fg2); position:relative }
.sstrip b { color:var(--fg); font-weight:600 } .sstrip .sst { font-variant-numeric:tabular-nums; white-space:nowrap } .sstrip .sst[hidden] { display:none }
.sstrip .sst + .sst::before, .sstrip b + .sst::before { content:"·"; margin-right:10px; color:var(--muted) }
.sdot { width:9px; height:9px; border-radius:50%; background:var(--muted); flex:none } .sdot.ok { background:var(--good-mark) } .sdot.run { background:var(--accent); animation:opulse 1.2s ease-in-out infinite }
.sdot.late { background:var(--warn-mark) } .sdot.bad { background:var(--bad-mark) }
/* Scan now: a quiet pill (the radar's Start and Stop are pills too) inside a 44 px tap target that does not make the strip taller */
.sbtn { margin:-8px 0 -8px auto; min-height:44px; min-width:44px; display:inline-flex; align-items:center; text-decoration:none; white-space:nowrap }
.sbtn > span { display:inline-flex; align-items:center; min-height:30px; padding:0 12px; border-radius:999px; background:var(--chip); border:1px solid var(--line); color:var(--fg); font-weight:600 }
.sbtn:hover > span, .sbtn:focus-visible > span { border-color:color-mix(in srgb,var(--accent) 55%,var(--line)); color:var(--accent) } .sbtn:hover { text-decoration:none }
.sbtn[hidden] { display:none } .sbtn[hidden] + .sinfo { margin-left:auto }
.sinfo > summary { list-style:none; cursor:pointer; color:var(--muted); min-width:44px; min-height:44px; margin:-8px -8px; display:flex; align-items:center; justify-content:center }
.sinfo > summary::-webkit-details-marker { display:none }
.sinfo[open] { flex-basis:100% } .sinfo[open] > summary { width:44px; margin-left:auto } .sinfo p { margin:4px 0 2px; font-size:var(--fs-s); color:var(--fg2) }
.sstrip[data-ss="run"] { border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) }
@media (prefers-reduced-motion: reduce) { .sdot.run { animation:none } }
"""

DESK_CSS = r"""
/* the Launch radar's desk on top of the Office tab (page_office.desk): a state line and four stations, 2 x 2 on a phone, one row from 700 px */
.odesk { display:grid; gap:8px; padding:10px 12px; border:1px solid var(--line); border-radius:12px; background:var(--surface); cursor:pointer; min-width:0 }
.odesk:hover { border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) } .odesk:active { transform:translateY(1px) }
.odk-h { display:flex; flex-wrap:wrap; align-items:center; gap:2px 8px; min-width:0; font-size:var(--fs-s); color:var(--fg2) }
.odk-h b { color:var(--fg); font-weight:600 } .odk-h b + .odk-w::before { content:"·"; margin-right:8px; color:var(--muted) }
.odk-m { flex-basis:100%; padding-left:17px; color:var(--muted); font-variant-numeric:tabular-nums } .odk-m[hidden], .odk-g[hidden] { display:none }
.odk-dot { width:9px; height:9px; border-radius:50%; background:var(--muted); flex:none } .odk-dot.running { background:var(--good-mark); animation:opulse 2s ease-in-out infinite }
.odk-dot.done { background:var(--good-mark) } .odk-dot.fallback { background:var(--warn-mark) } .odk-dot.failed { background:var(--bad-mark) }
.odk-g { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px } .odk-g.dim { opacity:.6 }
.odk-s { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:baseline; gap:0 6px; min-width:0; padding:6px 8px; border-radius:8px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
.odk-s .k { font-size:var(--fs-xs); color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.odk-s b { font-size:15px; font-weight:600; color:var(--fg); font-variant-numeric:tabular-nums; white-space:nowrap } .odk-s b span + span::before { content:"·"; margin:0 3px; color:var(--muted); font-weight:400 }
.odk-s .good { color:var(--good) } .odk-s .warn { color:var(--warn) } .odk-s .bad { color:var(--bad) }
.odk-s .l { grid-column:1 / -1; font-size:var(--fs-xs); line-height:1.35; color:var(--fg2); overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow-wrap:anywhere }
@media (min-width:700px) { .odk-g { grid-template-columns:repeat(4,minmax(0,1fr)) } .odk-m { flex-basis:auto; padding-left:0 } .odk-w + .odk-m::before { content:"·"; margin-right:8px } }
@media (prefers-reduced-motion: reduce) { .odk-dot.running { animation:none } .odesk:active { transform:none } }
/* the desk's chat right under it (page_office.desk_chat): one row a message, the speaker's badge in its station's colour (Scout blue, Checks
   green, Skeptic red, Desk grey, Record amber), its name and the text wrapping beside it, small as the stations' lines on a phone; dimmed
   while the round is old news (late, stopped): the badges faded, the text in muted colours (no opacity on the text: it stays readable,
   4.5:1 and more in both themes). From 1000 px two columns in reading order: the second coin's thread starts the second one
   (a column break before its Scout line, the Record's line below it); a chat of one thread is balanced over both by height */
.odk-box { display:grid; gap:6px; min-width:0 }
.ochat { list-style:none; margin:0; padding:2px 10px; display:grid; border:1px solid var(--line); border-radius:12px; background:var(--surface); min-width:0 }
.ochat[hidden] { display:none } .ochat.dim .och-a { opacity:.6 } .ochat.dim .och-t { color:var(--muted) } .ochat.dim .och-t b { color:var(--fg2) }
.och { display:grid; grid-template-columns:18px minmax(0,1fr); gap:7px; align-items:start; padding:4px 0; min-width:0; break-inside:avoid } .och + .och { border-top:1px solid var(--line2) }
.och-a { width:18px; height:18px; border-radius:5px; display:grid; place-items:center; color:var(--muted); background:color-mix(in srgb,currentColor 15%,transparent) }
.och-a svg { width:12px; height:12px; fill:none; stroke:currentColor; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round }
.och-t { min-width:0; padding-top:1px; font-size:var(--fs-xs); line-height:1.35; color:var(--fg2); overflow-wrap:anywhere } .och-t b { margin-right:5px; color:var(--fg); font-weight:600 }
.och.k-scout .och-a { color:var(--s1) } .och.k-checks .och-a { color:var(--good-mark) } .och.k-skeptic .och-a { color:var(--bad-mark) }
.och.k-desk .och-a { color:var(--fg2) } .och.k-record .och-a { color:var(--warn-mark) }
@media (min-width:700px) { .ochat { padding:3px 12px } .och { grid-template-columns:22px minmax(0,1fr); gap:8px; padding:5px 0 } .och-a { width:22px; height:22px; border-radius:6px }
  .och-a svg { width:14px; height:14px; stroke-width:1.6 } .och-t { padding-top:2px; font-size:var(--fs-s); line-height:1.4 } .och-t b { margin-right:6px } }
@media (min-width:1000px) { .ochat { display:block; columns:2; column-gap:28px } .och + .och { border-top:0 } .och.k-scout ~ .och.k-scout { break-before:column } }
"""

CSS = r"""
.fold-lite > summary { min-height:44px; display:flex; align-items:center }   /* a 44 px tap target */
/* the office's agent cards, the Launch radar's panel and the daily overview (page_office.py); page tokens only, light and dark */
/* the agent cards: 2 columns on a phone, 4 from 700 px; a card is icon + number, name, one line (phone) or icon, name, number and one line */
.ocards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px }
.ocard { display:grid; grid-template-columns:auto minmax(0,1fr) auto; grid-template-areas:"ic . nu" "nm nm nm" "ln ln ln"; align-items:center; gap:4px 8px; min-width:0;
  padding:9px 10px 8px; border:1px solid var(--line); border-radius:10px; background:var(--surface); cursor:pointer; position:relative }
.ocard:hover { border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) } .ocard:active { transform:translateY(1px) }
.ocard:has(> .olt.failed) { border-color:color-mix(in srgb,var(--bad-mark) 55%,var(--line)) } .ocard:has(> .olt.fallback) { border-color:color-mix(in srgb,var(--warn-mark) 55%,var(--line)) }
.ocard .olt { grid-area:ic; width:26px; height:26px; border-radius:7px; display:grid; place-items:center; color:var(--muted); background:color-mix(in srgb,currentColor 15%,transparent) }
.ocard .olt svg { width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round } .ocard .olt b { font-size:13px; line-height:1 }
.ocard .ocn { grid-area:nm; font-weight:600; font-size:var(--fs-s); line-height:1.25; color:var(--fg); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.ocard .ocs { grid-area:nu; justify-self:end; font-size:15px; font-weight:600; line-height:1.2; color:var(--fg); font-variant-numeric:tabular-nums; white-space:nowrap }
.ocard .ocl { grid-area:ln; font-size:var(--fs-xs); line-height:1.35; color:var(--fg2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.ocard .ocl[hidden], .ocard .chip[data-live-chip] { display:none }
.olt.done { color:var(--good-mark) } .olt.failed { color:var(--bad-mark) } .olt.fallback { color:var(--warn-mark) } .olt.running { color:var(--accent) } .olt.skipped { color:var(--muted) }
/* during a scan (the live view): a card at work pulses and shows its live line instead of last run's, a waiting card is faded as on the floor */
.ocard[data-live="work"] .olt { color:var(--accent); animation:opulse 1.2s ease-in-out infinite } .ocard[data-live="done"] .olt { color:var(--good-mark) }
.ocard[data-live="fail"] .olt { color:var(--bad-mark) } .ocard[data-live="wait"] .olt { color:var(--muted) } .ocard[data-live="wait"] { opacity:.55 }
.ocard:has(> .ocl[data-live-line]:not([hidden])) > .ocl:not([data-live-line]) { display:none }
@media (prefers-reduced-motion: reduce) { .ocard[data-live="work"] .olt { animation:none } .ocard:active { transform:none } }
@media (min-width:700px) { .ocards { grid-template-columns:repeat(4,minmax(0,1fr)) } .ocard { grid-template-areas:"ic nm nu" "ln ln ln"; padding:10px 12px 9px } }
/* the paper account's line under the cards */
.obal { display:grid; gap:4px; padding:10px 12px 8px; border:1px solid var(--line); border-radius:10px; background:var(--surface); min-width:0 }
.obal-h { display:flex; align-items:baseline; gap:4px 10px; flex-wrap:wrap; min-width:0 } .obal-h .k { font-size:var(--fs-xs); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500 }
.obal-h .s { font-size:var(--fs-xs); color:var(--muted) } .obal-h .v { margin-left:auto; font-size:20px; font-weight:600; letter-spacing:-.01em; font-variant-numeric:tabular-nums; white-space:nowrap }
.obal.good .v { color:var(--good) } .obal.bad .v { color:var(--bad) }
.obal-c { position:relative; height:64px; min-width:0 } .obal-c svg { position:absolute; inset:0; width:100%; height:100%; overflow:visible }
.obal .l { fill:none; stroke:var(--muted); stroke-width:2; vector-effect:non-scaling-stroke; stroke-linejoin:round } .obal .a { fill:var(--muted); opacity:.1 }
.obal.good .l { stroke:var(--good-mark) } .obal.good .a { fill:var(--good-mark) } .obal.bad .l { stroke:var(--bad-mark) } .obal.bad .a { fill:var(--bad-mark) }
.obal .z { stroke:var(--muted); stroke-width:1; stroke-dasharray:4 3; vector-effect:non-scaling-stroke } .obal-e { margin:0; font-size:var(--fs-xs); color:var(--muted) }
/* while a scan runs the cards say who is at work: the live box keeps its badge and its counts, its "Right now" list goes */
.olive > div:has(> ul.onow) { display:none }
/* the Details fold: everything else of the office */
details.ofold > .ofold-in { display:grid; gap:16px; min-width:0 } details.ofold > summary { min-height:44px; box-sizing:border-box }
.otop { display:grid; gap:10px; min-width:0 }
.ofl .desk[data-ext].off .who { display:none } .olegend .oj::before { width:22px; height:12px; border-radius:6px; background:color-mix(in srgb,var(--s3) 18%,var(--surface)); border:1px solid var(--s3) } .ofl .pill.own { fill:color-mix(in srgb,var(--s3) 18%,var(--surface)); stroke:var(--s3) }
.oext .olinkb { color:var(--accent); cursor:pointer; text-decoration:underline; display:inline-flex; align-items:center; min-height:44px; margin:-12px 0 }
.oext [hidden] { display:none }
.oday { display:grid; grid-template-columns:minmax(0,1fr); gap:8px; padding-top:12px; border-top:1px solid var(--line2) } .oday p { margin:0 } .oday > * { min-width:0 }
.oday .odsum { color:var(--fg2); overflow-wrap:anywhere }
.odn { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px }
.odn > div { display:grid; gap:1px; align-content:start; min-width:0; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--surface) }
.odn b { font-size:20px; font-weight:600; line-height:1.2; letter-spacing:-.01em; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.odn span { font-size:var(--fs-xs); color:var(--fg2); line-height:1.3 } .odn small { font-size:var(--fs-xs); color:var(--muted) }
.oday { --hb-g2:color-mix(in oklch,var(--good-mark) 78%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 38%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 16%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 38%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 78%,var(--surface));
  --hb-none:var(--line2) }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .oday { --hb-g2:color-mix(in oklch,var(--good-mark) 90%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 40%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 20%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 40%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 90%,var(--surface)) } }
:root[data-theme="dark"] .oday { --hb-g2:color-mix(in oklch,var(--good-mark) 90%,var(--surface)); --hb-g1:color-mix(in oklch,var(--good-mark) 40%,var(--surface));
  --hb-mid:color-mix(in srgb,var(--fg) 20%,var(--surface)); --hb-b1:color-mix(in oklch,var(--bad-mark) 40%,var(--surface)); --hb-b2:color-mix(in oklch,var(--bad-mark) 90%,var(--surface)) }
.ohb { display:grid; gap:4px; min-width:0 } .ohb > input { position:fixed; top:0; left:0; opacity:0; pointer-events:none }
.ohb-bar { position:relative; display:grid; grid-template-columns:repeat(24,minmax(0,1fr)); gap:2px; padding-top:9px }
.ohb-bar label { height:44px; border-radius:3px; background:var(--hb-none); cursor:pointer; position:relative }
.ohb-bar label.g2 { background-color:var(--hb-g2) } .ohb-bar label.g1 { background-color:var(--hb-g1) } .ohb-bar label.mid { background-color:var(--hb-mid) }
.ohb-bar label.b1 { background-color:var(--hb-b1) } .ohb-bar label.b2 { background-color:var(--hb-b2) }
.ohb-bar label.low::after, .ohb-bar label.high::after { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; color:var(--fg) }
.ohb-bar label.low::after { content:"↓" } .ohb-bar label.high::after { content:"↑" }
.ohb-bar label.few, .ohb-leg .few::before { background-image:repeating-linear-gradient(135deg,transparent 0 3px,color-mix(in srgb,var(--surface) 72%,transparent) 3px 5px) }
.ohb-day { position:absolute; left:-3px; top:6px; bottom:-3px; border:1.5px solid color-mix(in srgb,var(--fg) 55%,transparent); border-radius:5px; pointer-events:none; min-width:6px }
.ohb-now { position:absolute; top:0; width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-top:7px solid var(--fg); transform:translateX(-5px) }
.ohb-ticks { position:relative; height:16px; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.ohb-ticks span { position:absolute; top:0; transform:translateX(-50%) } .ohb-ticks span:first-child { transform:none } .ohb-ticks span:last-child { transform:translateX(-100%) }
.ohb-read p { display:none; font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums }
.ohb-leg .few::before { background-color:var(--hb-mid) } .ohb-leg .tod::before { background:none; box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--fg) 55%,transparent) }
.ohb-leg .nowk::before { display:none } .oday details .ohb-leg { margin-bottom:8px } .oday th, .oday td { padding:6px 8px }
""" + hour_css()

# The page script: the Launch radar's desk on top and its floor desk and panel follow the radar's script on the New tab (window event memebot-radar,
# detail {doc, state, via, now}); the full scan's strip follows the office's live script (memebot-live, detail {state, status}) and finds the
# repository for its Scan now link. Text only through textContent; nothing is fetched. MemebotOffice.look, .desk, .scan and .next are the
# decisions (node checks them).
JS = r"""
(function(){
if(window.MemebotOffice)return;
var D=document,last=null,lastAt=0,lastScan=null;
var LOOK={running:['running','running'],done:['done','done'],late:['fallback','late'],stopped:['failed','stopped'],off:['skipped','switched off'],hours:['skipped','outside its hours'],none:['skipped','not started yet']};
var QUIET=['off','hours','none'],CHIP={running:'neutral',fallback:'warn',failed:'bad',done:'good'},SCAN_LEN=2700000,HOUR=3600000;
var SOON=10000,ROUND=180000,FEED={ok:'on'},LABELS=__LABELS__,CH=__CHAT__,VERD=['good','watch','trap'],NM=/^[A-Za-z0-9_.]{1,32}$/,SVG='http://www.w3.org/2000/svg';
var HOSTS=[['curve list','Curve list (pump.fun)'],['curve trades','Curve trades (live feed)'],['curve watch','Curve watch'],['dexscreener','DexScreener'],['rugcheck','RugCheck'],['pump.fun','pump.fun'],['pumpfun','pump.fun'],['geckoterminal','GeckoTerminal'],['rpc','Solana RPC'],['jupiter','Jupiter'],['launchlab','LaunchLab'],['github','GitHub'],['supabase','Supabase'],['pumpportal','live feed'],['tweets','X tweets']];
function isn(v){return typeof v==='number'&&isFinite(v);}
function n(v){return isn(v)?Math.round(v):0;}
function zone(){var b=D.querySelector('[data-po-tz]');return b?b.getAttribute('data-po-tz')||'UTC':'UTC';}
function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:zone()});}catch(e){return new Date(ms).toISOString().slice(11,16);}}
function all(s){return Array.prototype.slice.call(D.querySelectorAll(s));}
function set(e,t){if(e&&e.textContent!==t)e.textContent=t;}
function cls(e,c){if(e.getAttribute('class')!==c)e.setAttribute('class',c);}
function own(o,k){return Object.prototype.hasOwnProperty.call(o,k)?o[k]:undefined;}
function order(a,b){return b[1]-a[1]||(a[0]<b[0]?-1:a[0]>b[0]?1:0);}
function ago(ms){var m=ms/60000;return ms<60000?'just now':(m<60?Math.floor(m)+' min':m<2880?Math.floor(m/60)+' h':Math.floor(m/1440)+' days')+' ago';}
// the desk's chat (page_office.desk_chat and its helpers, word for word): a time 2001 to 2100, a number it may print (under CH.big), a trim
// of CH.blank, a doc's text with CH.ctrl as spaces cut in UTF-16 units without a half emoji (also one MemebotRadar.clean's cut left), $ amounts
// half up, the first chips and '+N more', the verdict, the record's line (record.known's counts as the push says them, else the calls and
// shares), one coin's messages
var CC=new RegExp('['+CH.ctrl+']','g'),TB=new RegExp('^['+CH.blank+']+|['+CH.blank+']+$','g');
function at(v){return isn(v)&&v>1e12&&v<4.1e12?v:null;}
function fin(v){return isn(v)&&Math.abs(v)<CH.big;}
function trim(s){return s.replace(TB,'');}
function txt(v,k){return typeof v!=='string'?'':v.replace(CC,' ').slice(0,k).replace(/[\uD800-\uDBFF]$/,'');}
function usd(v){var d=Math.floor(v+0.5),k=Math.floor(v/1e3+0.5);return d<1000?'$'+d:k<1000?'$'+k+'k':'$'+(Math.floor(v/1e5+0.5)/10).toFixed(1).replace(/\.0$/,'')+'M';}
function few(xs){return xs.slice(0,CH.chips).join(' · ')+(xs.length>CH.chips?' · +'+(xs.length-CH.chips)+' more':'');}
function vd(c){return VERD.indexOf(c.v)>=0?c.v:'watch';}
function isObj(v){return !!v&&typeof v==='object'&&!Array.isArray(v);}
function recLine(r){if(!isObj(r))return '';
  var k=isObj(r.known)?r.known:{},whole=function(x){return fin(x)&&x>=0&&Math.floor(x)===x;};
  if(whole(k.n)&&whole(k.win)&&whole(k.rug)&&k.n>=CH.few&&k.win<=k.n&&k.rug<=k.n)return 'Greens so far: '+k.win+' of '+k.n+' doubled within 1 h, '+k.rug+' rugged (hindsight)';
  if(!fin(r.calls)||r.calls<1)return '';
  var calls=Math.floor(r.calls),n60=fin(r.n60)&&r.n60>=0?Math.floor(r.n60):0,cl=calls+' call'+(calls===1?'':'s'),pc=function(x){return Math.floor(100*x+0.5)+'%';};
  var share=function(x){return isn(x)&&x>=0&&x<=1;};
  return n60>=CH.few&&share(r.win)&&share(r.rug)?'Greens so far: '+pc(r.win)+' doubled, '+pc(r.rug)+' rugged within 1 h (hindsight, '+n60+' of '+cl+')':
    'Greens so far: '+cl+(n60<CH.few?', too few with a 1 h price yet ('+n60+' of '+CH.few+')':'');}
// Scout's line about the curve watch's newest call while it is fresh (page_office.chat_curve): its symbol, the curve sold, minutes since the mint,
// its quick check in words; a call whose check found a trap is never named
function curveTalk(cv,now){var rs=isObj(cv)&&Array.isArray(cv.recent)?cv.recent:[],best=null;
  rs.forEach(function(r){if(isObj(r)&&at(r.t)&&r.v!=='trap'&&(best===null||r.t>best.t))best=r;});
  if(best===null||!(now-best.t>=0&&now-best.t<=CH.fresh))return '';var p=best.prog,a=best.age;
  return 'On the curve: '+(trim(txt(best.sym,24))||'?')+(fin(p)&&p>=0&&p<=100?' at '+Math.floor(p+0.5)+'%':'')+(fin(a)&&a>=0?(a<1?', under 1 min after mint':', '+Math.floor(a)+' min after mint'):'')+
    ', quick check: '+(Object.prototype.hasOwnProperty.call(CH.cw,best.v)?CH.cw[best.v]:CH.cw.unknown);}
// the curve watch's hosts for the radar panel's chips (page_office.curve_hosts): its list and its trades, one 'curve watch' off while it is off
function curveHosts(cv){if(!isObj(cv))return {};if(['on','limited','off'].indexOf(cv.state)<0||cv.state==='off')return {'curve watch':'off'};
  var hs=isObj(cv.hosts)?cv.hosts:{},o={};[['pump.fun','curve list'],['trades','curve trades']].forEach(function(x){var v=own(hs,x[0]);if(typeof v==='string'&&/^[a-z]{1,12}$/.test(v))o[x[1]]=v;});return o;}
function coinTalk(c,t,fmt){
  var sym=trim(txt(c.sym,24))||'?',v=vd(c),found=Array.isArray(c.found)?c.found.filter(function(x){return typeof x==='string';}):[],lp=trim(txt(c.lp,24)),age=c.age,liq=c.liq;
  var facts=(found.indexOf('pf:graduated')>=0?['pump.fun graduated']:lp?['launched on '+lp]:[]).concat(fin(age)&&age>=0?[age>=1?'pool '+Math.floor(age)+' min old':'pool under 1 min old']:[])
    .concat(fin(liq)&&liq>=0?[usd(liq)+' liquidity']:[]);
  var line=(Array.isArray(c.line)?c.line:[]).filter(function(x){return Array.isArray(x)&&x.length>=2&&typeof x[1]==='string'&&!!trim(txt(x[1],120));}).map(function(x){return [x[0],txt(x[1],120)];});
  var names=function(k){return (Array.isArray(c[k])?c[k]:[]).filter(function(x){return typeof x==='string'&&NM.test(x);});};
  var lv=function(ls){return line.filter(function(x){return ls.indexOf(x[0])>=0;}).map(function(x){return x[1];});};
  var ok=lv(['ok']),bad=lv(['bad','warn']),unk=lv(['unk']),push=at(c.push),out=[['scout','Found '+sym+(facts.length?': '+facts.join(', '):'')]];
  if(!bad.length)bad=names('hard').concat(names('soft')).map(function(h){return own(LABELS,h)||h.replace(/_/g,' ');});
  if(!unk.length)unk=names('unknown').map(function(h){return h.replace(/_/g,' ')+' unknown';});
  if(ok.length)out.push(['checks',sym+' passed: '+few(ok)]);
  out.push(['skeptic',bad.length?'Against '+sym+': '+few(bad):unk.length?'Not checked for '+sym+': '+few(unk):'No objection to '+sym]);
  out.push(['desk',sym+': '+(own({trap:'trap found, not listed',watch:'watch only'},v)||(push&&push>=t?'no trap found, sent to the phone':push?'no trap found, sent to the phone at '+fmt(push):'no trap found, listed, no push'))]);
  return out;}
var O=window.MemebotOffice={
  // the radar's light, word, line and small number for its state (page_office.look says the same at build time)
  // a round's next one (page_office.next_words; MemebotRadar.nextWords on the New tab): now and scan (the strip's next start) in ms
  nextWords:function(d,now,scan,fmt){now=isn(now)?now:+d.t;
    if(isn(d.next)&&d.next>0)return (now<d.next?'next about ':'next due since ')+fmt(d.next);
    if(isn(scan)&&scan>0){var s=scan,ref=Math.max(+d.t||0,now);while(s+SCAN_LEN<ref)s+=HOUR;return 'next after the '+fmt(s)+' scan';}
    return 'next after the next full scan';},
  // the radar desk on top of the Office tab (page_office.desk_look says the same at build time): its light, its state in words, the line after
  // it, whether its stations are hidden (quiet) or the last round's (dim), and the stations [key, name, [[class, number], ...], line]
  desk:function(st,doc,now,fmt){var d=doc&&typeof doc==='object'?doc:null,o=d||{},t=o.t,nx=isn(o.next)&&o.next>0?o.next:null;fmt=fmt||hhmm;
    if((st==='running'||st==='done')&&nx&&now>nx+SOON&&now<=nx+ROUND)st='progress';
    var err=o.state==='degraded'&&['running','progress','done'].indexOf(st)>=0,sleep=nx&&now<nx?'sleeping until '+fmt(nx):'sleeping';
    var light=err?'fallback':own({running:'running',progress:'running',done:'done',late:'fallback',stopped:'failed'},st)||'skipped';
    var word=own({running:'running',progress:'round in progress',done:sleep,hours:sleep,late:'late',stopped:'stopped',off:'off'},st)||'not started yet';
    var rnd=!!d&&(d.state==='done'||!!d.run&&typeof d.run==='object'&&d.run.mode==='round'),ev=nx&&isn(t)&&nx>t&&!rnd?Math.round((nx-t)/30000)/2:0,meta=[];
    var fail=rnd?'last round failed':'rounds failing';if(err&&st!=='progress')word=fail;      // a degraded doc checked nothing: dim stations that say so
    if(ev&&['running','progress','late'].indexOf(st)>=0)meta.push('every '+ev+' min');
    if(d&&st!=='none')meta.push('last '+fmt(t));
    if(nx&&(st==='running'||err&&st==='done'))meta.push('next '+fmt(nx));
    var cs=[],by=Object.create(null),arr=function(v){return Array.isArray(v)?v.filter(function(c){return c&&typeof c==='object';}):[];};
    arr(o.coins).concat(arr(o.others)).forEach(function(c){if(!own(by,c.addr)){by[c.addr]=1;cs.push(c);}});     // a coin in both lists counts once
    var sr=o.src&&typeof o.src==='object'?o.src:{},hs=o.hosts&&typeof o.hosts==='object'?o.hosts:{},fd=typeof hs.pumpportal==='string'?hs.pumpportal:'',sum=0;
    var found=(fd?['live feed '+(own(FEED,fd)||fd)]:[]).concat(Object.keys(sr).map(function(k){sum+=sr[k];return [k,sr[k]];}).sort(order).slice(0,3).map(function(x){return x[0]+' '+x[1];}));
    var fl=Object.create(null);cs.forEach(function(c){var u=Object.create(null);(Array.isArray(c.hard)?c.hard:[]).forEach(function(h){if(!own(u,h)){u[h]=1;fl[h]=(own(fl,h)||0)+1;}});});
    var red=Object.keys(fl).map(function(k){return [k,fl[k]];}).sort(order).slice(0,2).map(function(x){return (own(LABELS,x[0])||x[0].replace(/_/g,' '))+' '+x[1];}).join(' · ');
    var cn=o.counts&&typeof o.counts==='object'?o.counts:{},pu=arr(o.coins).filter(function(c){return isn(c.push)&&c.push>0&&isn(t)&&c.push>=t;}),lg=o.lastGood&&typeof o.lastGood==='object'?o.lastGood:{};
    var push=pu.length?pu.slice(0,2).map(function(c){return c.sym||'?';}).join(', ')+' pushed':isn(lg.at)&&lg.at>0?'last without traps: '+(lg.sym||'?')+', '+ago(now-lg.at):'no push';
    return {light:light,word:word,meta:meta.join(' · '),quiet:QUIET.indexOf(st)>=0,dim:st==='late'||st==='stopped'||err,
      st:[['src','Sources',[['',Object.keys(sr).length?String(sum):'–']],found.join(' · ')||'no counts yet'],
        ['chk','Checks',[['',isn(cn.seen)&&!err?String(Math.floor(cn.seen+0.5)):'–']],err?'not checked: '+fail:red?'red flags: '+red:cs.length?'no red flags':'no coin under 10 min'],
        ['vd','Verdicts',[['good','good'],['warn','watch'],['bad','trap']].map(function(x){return [x[0],err?'–':String(cs.filter(function(c){return c.v===x[1];}).length)];}),'no trap · watch · trap'],
        ['push','Push',[['',String(pu.length)]],push]]};},
  // the desk's chat about the doc's round (page_office.desk_chat says the same at build time): [[speaker, text], ...], at most CH.max; two
  // coins (the push of this round, else the first without traps, else the first; then another push, a trap, another verdict, the next),
  // one Desk line for a failed round, outside its hours or switched off, and the Record's line when the record has calls
  chat:function(doc,now,fmt){var d=isObj(doc)&&doc.kind==='radar'&&isn(doc.t)?doc:null;if(!d)return [];fmt=fmt||hhmm;
    var t=d.t,nx=at(d.next),st=d.state,run=isObj(d.run)?d.run:{},rec=recLine(d.record),out=[];now=isn(now)?now:t;var cur=curveTalk(d.curve,now);
    if(st==='off')out.push(['desk','Radar switched off on GitHub: no rounds']);
    else if(st==='hours')out.push(['desk',!nx?'Radar sleeps: outside its hours':now<nx?'Radar sleeps until '+fmt(nx):now<=nx+HOUR?'Radar sleeps: the next round comes with the first scan after '+fmt(nx):
      'Radar stopped: no round since its hours began at '+fmt(nx)]);
    else if(st==='degraded')out.push(['desk',run.mode==='round'?'Last round failed: no coin checked':'Rounds failing: no coin checked, the list is not current']);
    else{var cs=[],by=Object.create(null),ls=function(v){return Array.isArray(v)?v:[];};
      ls(d.coins).concat(ls(d.others)).forEach(function(c){if(isObj(c)&&typeof c.addr==='string'&&!own(by,c.addr)){by[c.addr]=1;cs.push(c);}});     // a coin in both lists talks once
      var pushed=function(c){return !!at(c.push)&&c.push>=t;},first=function(f,xs){for(var i=0;i<xs.length;i++)if(f(xs[i]))return xs[i];return null;};
      if(!cs.length){var sn=isObj(d.counts)?d.counts.seen:null,k=fin(sn)&&sn>=1?Math.floor(sn):0;
        out.push(['scout',k?'Found '+k+' new pool'+(k===1?'':'s')+' under 10 minutes, none kept on the list':'No new pools under 10 minutes this round']);}
      else{var lead=first(pushed,cs)||first(function(c){return vd(c)==='good';},cs)||cs[0],rest=cs.filter(function(c){return c!==lead;});
        var two=first(pushed,rest)||(vd(lead)!=='trap'?first(function(c){return vd(c)==='trap';},rest):null)||first(function(c){return vd(c)!==vd(lead);},rest)||(rest.length?rest[0]:null);
        var more=two?coinTalk(two,t,fmt):[];out=coinTalk(lead,t,fmt);var room=CH.max-out.length-(rec?1:0)-(cur?1:0);
        out=out.concat((more.length<=room?more:more.filter(function(m){return m[0]!=='checks';})).slice(0,Math.max(0,room)));}}
    return out.concat(cur?[['scout',cur]]:[],rec?[['record',rec]]:[]).slice(0,CH.max);},
  look:function(st,doc,fmt,now,scan){var d=doc&&typeof doc==='object'?doc:null,L=LOOK[st]||LOOK.none,light=L[0],word=L[1],c=d&&d.counts&&typeof d.counts==='object'?d.counts:null,line;fmt=fmt||hhmm;
    var lead=st==='late'||st==='stopped'?word:'';
    var rnd=!!d&&(d.state==='done'||!!d.run&&typeof d.run==='object'&&d.run.mode==='round');
    if(st==='running'&&d&&d.state==='degraded'){light='fallback';word='running, some checks failing';lead='checks failing';}
    else if(st==='done'&&d&&d.state==='degraded'){light='fallback';word='last round had errors';lead='checks failing';}
    if(st==='off')line='switched off on GitHub';
    else if(st==='hours')line=d&&isn(d.next)&&d.next>0?'outside its hours · next start '+fmt(d.next):'outside its hours';
    else if(st==='none')line='not started yet';
    else if(!c)line=(lead?lead+' · ':'')+'no counts yet';
    else if(lead&&(st==='late'||st==='stopped'))line=lead+' · '+n(c.seen)+' seen, '+n(c.good)+' without traps';
    else line=(lead?lead+' · ':'')+n(c.seen)+' seen · '+n(c.good)+' without traps · '+n(c.pushed)+' pushed';
    var ck=d&&isn(d.t)&&st!=='none'?(rnd?'last round ':'checked ')+fmt(d.t):'no check yet';
    var until=d&&isn(d.t)&&st==='done'?' · '+O.nextWords(d,now,scan,fmt):'';
    return {light:light,word:word,line:line,stat:d&&isn(d.t)&&st!=='none'?fmt(d.t):'own job',checked:ck,here:st==='running'||st==='done'||st==='late',until:until,quiet:QUIET.indexOf(st)>=0};},
  // the full scan's strip for a live-view state (MemebotLive.state): null keeps the page's own words
  scan:function(st,doc,runT,fmt){var d=doc&&typeof doc==='object'?doc:null,t=d&&isn(+d.t)?+d.t:0,up=d?+(d.updated||d.end)||0:0;fmt=fmt||hhmm;
    if(!d||!(t>runT))return null;
    if(st==='live')return {dot:'run',text:'running now · started '+fmt(t)};
    if(st==='paused')return {dot:'late',text:'started '+fmt(t)+' · no update since '+fmt(up)};
    if(st==='done')return {dot:'ok',text:'finished '+fmt(up)+' · new page on its way'};
    if(st==='stopped')return {dot:'bad',text:'stopped '+fmt(up)};
    return null;},
  // the strip's next start: "next ≈ HH:MM" until that time, then "due now (≈ HH:MM)" (the page is rebuilt only after the next scan)
  next:function(nx,now,fmt){fmt=fmt||hhmm;if(!isn(nx)||nx<=0)return null;return now>=nx?'due now (≈ '+fmt(nx)+')':'next ≈ '+fmt(nx);},
  radar:function(det){if(det&&typeof det==='object'){last=det;lastAt=Date.now();}draw();},
  hosts:HOSTS};
function host(k){k=String(k).toLowerCase();for(var i=0;i<HOSTS.length;i++)if(k.indexOf(HOSTS[i][0])>=0)return HOSTS[i][1];return String(k).slice(0,40);}
// the desk on top: redrawn from the radar's last event, its clock moved on by the time since (a round falls due between two events)
function desk(){
  var box=D.querySelector('[data-po-desk]');if(!box||!last)return;
  var doc=last.doc&&typeof last.doc==='object'&&last.doc.kind==='radar'?last.doc:null,now=isn(last.now)?last.now+Date.now()-lastAt:Date.now(),st=String(last.state||'none');
  var v=O.desk(st,doc,now),c=[];try{c=O.chat(doc,now);}catch(e){}     // the chat is an extra: a doc it cannot read leaves the desk as it is
  var key=JSON.stringify([v,c]);if(box._k===key)return;box._k=key;
  cls(box.querySelector('[data-pd-dot]'),'odk-dot '+v.light);set(box.querySelector('[data-pd-word]'),v.word);
  var m=box.querySelector('[data-pd-meta]'),g=box.querySelector('[data-pd-g]');set(m,v.meta);m.hidden=!v.meta;g.hidden=v.quiet;cls(g,'odk-g'+(v.dim?' dim':''));g.textContent='';
  v.st.forEach(function(x){var s=D.createElement('span'),k=D.createElement('span'),b=D.createElement('b'),l=D.createElement('span');s.className='odk-s';s.setAttribute('data-pd',x[0]);
    k.className='k';k.textContent=x[1];x[2].forEach(function(p){var e=D.createElement('span');if(p[0])e.className=p[0];e.textContent=p[1];b.appendChild(e);});
    l.className='l';l.title=x[3];l.textContent=x[3];s.appendChild(k);s.appendChild(b);s.appendChild(l);g.appendChild(s);});
  // the chat under the desk: rebuilt from the same doc, every text as text, the badges from the fixed paths of CH.av; dimmed while the round
  // is old news (late, stopped)
  var ch=D.querySelector('[data-pd-chat]');if(!ch)return;cls(ch,'ochat'+(st==='late'||st==='stopped'?' dim':''));ch.hidden=!c.length;ch.textContent='';
  c.forEach(function(m){if(!own(CH.who,m[0]))return;var li=D.createElement('li'),a=D.createElement('span'),s=D.createElementNS(SVG,'svg'),tx=D.createElement('span'),b=D.createElement('b'),sr=D.createElement('span');
    li.className='och k-'+m[0];a.className='och-a';s.setAttribute('viewBox','0 0 16 16');s.setAttribute('aria-hidden','true');s.setAttribute('focusable','false');
    (CH.av[m[0]]||[]).forEach(function(p){var e=D.createElementNS(SVG,'path');e.setAttribute('d',p);s.appendChild(e);});a.appendChild(s);
    tx.className='och-t';b.textContent=CH.who[m[0]];sr.className='sr';sr.textContent=': ';tx.appendChild(b);tx.appendChild(sr);tx.appendChild(D.createTextNode(m[1]));
    li.appendChild(a);li.appendChild(tx);ch.appendChild(li);});
}
function draw(){
  if(!last)return;
  try{desk();}catch(e){}
  var st=String(last.state||'none'),doc=last.doc&&typeof last.doc==='object'&&last.doc.kind==='radar'?last.doc:null,sb=D.querySelector('[data-sstrip]');
  var L=O.look(st,doc,null,isn(last.now)?last.now:Date.now(),sb?+sb.getAttribute('data-next')||0:0);     // the radar's clock (its doc's time base), the strip's next scan
  all('g[data-ext="radar"]').forEach(function(g){cls(g,'desk'+(L.here?'':' off'));var s=g.querySelector('.scr');if(s)cls(s,'scr'+(L.light==='fallback'||L.light==='failed'?' '+L.light:''));});
  all('[data-ext-word="radar"]').forEach(function(e){set(e,L.word);});
  all('[data-ext-chip="radar"]').forEach(function(e){cls(e,'chip '+(CHIP[L.light]||''));});
  all('[data-ext-line="radar"]').forEach(function(e){set(e,L.line);});
  all('[data-ext-checked="radar"]').forEach(function(e){set(e,L.checked);});
  all('[data-ext-until="radar"]').forEach(function(e){set(e,L.until);});
  var hs0=doc&&doc.hosts&&typeof doc.hosts==='object'?doc.hosts:null,hs=null,ks=[];
  if(doc){hs={};(hs0?Object.keys(hs0).slice(0,12):[]).forEach(function(k){hs[k]=hs0[k];});var ch=curveHosts(doc.curve);Object.keys(ch).forEach(function(k){hs[k]=ch[k];});ks=Object.keys(hs);if(!ks.length&&!hs0)hs=null;}
  // switched off, outside its hours or never started: the last check's notes and services are old news, so they go (the wiring stays)
  all('[data-ext-hosts="radar"]').forEach(function(box){box.hidden=L.quiet||!ks.length;if(L.quiet||!hs)return;box.textContent='';
    var fine=function(v){return v==='ok'||v==='unavailable';};     // page_office.HOST_FINE: plain chips, after the problems
    ks.sort(function(a,b){return fine(hs[a])-fine(hs[b])||(a<b?-1:a>b?1:0);}).forEach(function(k){
    var v=String(hs[k]).slice(0,20),c=D.createElement('span');c.className='chip '+(fine(v)?'':v==='limited'||v==='slow'||v==='waiting'?'warn':'bad');c.textContent=host(k)+' · '+v;box.appendChild(c);});});
  all('[data-ext-wired="radar"]').forEach(function(e){e.hidden=!L.quiet&&!!ks.length;});
  var ns=!L.quiet&&doc&&Array.isArray(doc.notes)?doc.notes.filter(function(x){return typeof x==='string';}).slice(0,4):[];
  all('[data-ext-notes="radar"]').forEach(function(box){box.textContent='';ns.forEach(function(x){var p=D.createElement('p');p.className='omsg warn';p.textContent=x.slice(0,160);box.appendChild(p);});});
  if(!doc)return;
  var ls=Array.isArray(doc.lines)?doc.lines.filter(function(x){return typeof x==='string';}).slice(-6):null;
  if(ls)all('[data-ext-lines="radar"]').forEach(function(ul){ul.textContent='';ls.forEach(function(x){var li=D.createElement('li'),ic=D.createElement('span'),tx=D.createElement('span'),m=D.createElement('span');
    li.className='oline';ic.className='ic';ic.textContent='›';tx.className='tx';tx.textContent=x.slice(0,200);li.appendChild(ic);li.appendChild(tx);li.appendChild(m);ul.appendChild(li);});});
}
function strip(){
  var box=D.querySelector('[data-sstrip]');if(!box)return;
  var st=box.querySelector('[data-ss-state]'),dot=box.querySelector('[data-ss-dot]'),nx=box.querySelector('[data-ss-next]');if(st._t==null){st._t=st.textContent;dot._c=dot.getAttribute('class');}
  var s=lastScan?O.scan(String(lastScan.state||''),lastScan.status,+box.getAttribute('data-run-t')||0):null;
  set(st,s?s.text:st._t);cls(dot,s?'sdot '+s.dot:dot._c);if(s)box.setAttribute('data-ss',s.dot);else box.removeAttribute('data-ss');
  if(nx){var t=O.next(+box.getAttribute('data-next')||0,Date.now());if(t)set(nx,t);nx.hidden=!!s;}     // while the next scan reports, the strip names it instead
}
function link(){
  var a=D.querySelector('[data-ss-now]');if(!a||a.getAttribute('href'))return;
  var b=D.querySelector('[data-live-src]'),m=b&&/^https:\/\/api\.github\.com\/repos\/([A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/contents\//.exec(b.getAttribute('data-live-src')||''),r=m?'https://github.com/'+m[1]:null;
  if(!r){var btn=D.querySelector('.live a.btn'),k=btn&&/^(https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/actions\/workflows\/scan\.yml$/.exec(btn.getAttribute('href')||'');r=k?k[1]:null;}
  if(r){a.href=r+'/actions/workflows/scan.yml';a.hidden=false;}
}
window.addEventListener('memebot-radar',function(e){O.radar(e&&e.detail);});
D.addEventListener('click',function(e){var t=e.target&&e.target.closest?e.target:null;if(!t)return;
  // "Open the radar" and the desk on top: the browser page checks the New tab's radio (the label); the installed app switches tabs on a hash
  // change (#tab-radar opens New at its top, where the radar is), so its bar follows
  if(t.closest('[data-po-radar] label, label[data-po-desk]')&&D.documentElement.classList.contains('app')){e.preventDefault();try{location.hash='#tab-radar';}catch(x){}return;}
  // a tap on a card picks its department (the card is the radio's label), opens the Details fold and brings the panel into view (on a
  // desktop the panel sits beside the floor plan, on a phone below it)
  var c=t.closest('label.ocard');if(!c)return;
  var f=D.querySelector('details[data-po-fold]');if(f&&!f.open)f.open=true;
  var k=c.getAttribute('for'),p=k&&D.querySelector('.opanel.k-'+k.replace(/^od-/,'').replace(/[^a-z]/g,''));if(!p)return;
  var to=(window.innerWidth>=1080&&p.closest('.ogrid'))||p;
  setTimeout(function(){try{to.scrollIntoView({block:'start',behavior:window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}catch(x){}},30);});
window.addEventListener('memebot-live',function(e){lastScan=e&&e.detail&&typeof e.detail==='object'?e.detail:null;try{strip();}catch(x){}});
// the Details fold stays open across the page's own reloads (a new report) once the reader opened it in this tab; closed on a first visit
function fold(){var f=D.querySelector('details[data-po-fold]');if(!f||f._po)return;f._po=1;
  try{if(sessionStorage.getItem('memebot-office-fold')==='1')f.open=true;}catch(e){}
  f.addEventListener('toggle',function(){try{sessionStorage.setItem('memebot-office-fold',f.open?'1':'0');}catch(e){}});}
function ready(){try{link();}catch(e){}try{fold();}catch(e){}
  try{if(!D.getElementById('tab-young')||!D.querySelector('[data-radar]')){all('[data-po-radar]').forEach(function(e){e.hidden=true;});     // a page without the radar on New: no dead link
    all('label[data-po-desk]').forEach(function(e){e.removeAttribute('for');});}}catch(e){}
  try{if(!last&&window.MemebotRadar&&MemebotRadar.last)O.radar(MemebotRadar.last);else draw();}catch(e){}try{strip();}catch(e){}
  if(D.querySelector('[data-sstrip]'))setInterval(function(){try{strip();}catch(e){}},60000);
  if(D.querySelector('[data-po-desk]'))setInterval(function(){try{desk();}catch(e){}},10000);}
if(D.readyState==='loading')D.addEventListener('DOMContentLoaded',ready);else ready();
})();
""".replace("__LABELS__", json.dumps(LABELS)).replace("__CHAT__", json.dumps({"max": CHAT_MAX, "chips": CHAT_CHIPS, "few": TOO_FEW, "big": CHAT_BIG, "fresh": CURVE_FRESH_MS, "cw": CURVE_WORDS, "ctrl": CHAT_CTRL, "blank": CHAT_BLANK, "who": WHO, "av": AVATAR}))
