#!/usr/bin/env python3
"""bot.py: one command runs a whole paper-trading cycle. Fake money only, nothing is ever bought for real.

A cycle:
  1. memebot.py mode      what this run needs (a full scan, a light one, or only prices for the open positions)
  2. fetch.py sources     ~1000 coins from DexScreener, RugCheck, GeckoTerminal, CoinGecko, Jupiter, pump.fun, GMGN, news
  3. memebot.py gather    merge everything; fetch full DexScreener data for the addresses that still lack it; gather again
  4. memebot.py shortlist RugCheck reports (and GMGN top buyers) for the best candidates
  5. memebot.py train     the training programs on the scored snapshots: walk-forward test, zero model, tuned limits (db/memebot/train)
     radar.py early      (recommend mode, full scan) the launch spotter, beside the steps above from the end of the sources step: the
                          coins under an hour old for the New launches tab about five minutes into the scan, before they are scored
                          (young_early.json, pushed with the live view; MEMEBOT_EARLY=0 switches it off). It never changes a buy.
  6. memebot.py run       exits on the open positions, then the 2 best clean coins at 20 each out of the 40 bankroll (pick mode); with
                          --recommend the two best coins go to the page and the paper account buys the top pick for 50 and the first
                          5 new launches for 3 each (fake money, no budget; sold at +1000%, -30% or after 6 hours)
  7. apply out/*.json into db/ (positions, exits, snapshots, learned weights, state); radar.py check records the early list's fate
     (db/memeearly) and db/memebot/spotter.json keeps the trader's weights for the next scan's spotter
  8. report.py        renders mb/report.html, the analysis page (open it in a browser)

Usage:
  python3 bot.py cycle   [--dir mb] [--force] [--offline]   one cycle (--force: pick now even inside the 3h gap; --offline: reuse the files in --dir)
  python3 bot.py cycle --rescan                             full scan of the whole universe now, saved for the big test (buys only if a slot is free)
  python3 bot.py loop --every 60 --recommend --push         never buy: each cycle rescans everything and puts the two best clean coins on the page
  python3 bot.py loop --every 30 --recommend --push --horizon 2h   the same with the 2-hour profile: early, small, accelerating coins, re-priced 2h later
  (the loop git-pulls before each cycle and restarts itself when new code arrived; --no-update turns that off)
  python3 bot.py loop    [--every 30]                       cycles forever, every N minutes (Ctrl-C to stop)
  python3 bot.py status                                     bankroll, paper account, open positions with their last price, closed trades, last note
  python3 bot.py report                                     render mb/report.html from the current db/ without a cycle
  python3 bot.py sell --all | --coin SYMBOL [--push]        close positions by hand at the last known price; the money returns to the bankroll
  python3 bot.py sync    [--remote URL] [--branch results]  push mb/report.html and the small db docs to a git branch (default:
                                                            the "results" branch of this repository's origin), so the page and
                                                            the picks can be read elsewhere; cycle/loop --push does it after each cycle
  python3 bot.py reset                                      wipe db/ (positions, history, learned weights) and start again with 40

MEMEBOT_LIVE=1 (the scan workflow sets it): while a cycle runs, its Agent office record goes to the one-commit branch "live" of
the results remote (--remote, else RESULTS_URL, else the origin) about every 45 s when it changed and at least once a minute,
for the website's live view (class Live). The launch spotter's early list rides along in live.json as "young" and is pushed within
seconds of being written (the kick).

The iPhone app (app.py, supabase/setup.sql, README "iPhone app"): with SUPABASE_URL and SUPABASE_SECRET_KEY set as well, the same live
record also goes to the app's live store every 5 s while it changes (class AppFeed, beside the git pushes), the scan sends a push
notification when the pick is made (app.notify_pick after the trader step) and when the early New launches list is first published
(young_published), and bot.py site puts the store's address and publishable key (SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY) into the page.
Without those variables nothing of it runs and nothing touches the network (and without MEMEBOT_LIVE=1 only the pick notification goes
out: no live store, no "new coins" notification). Child processes (fetch.py, memebot.py, radar.py, git) never get SUPABASE_SECRET_KEY.
The launch spotter's list reaches both live views through two hooks: the live view's watcher (Live.watch_early, on a thread of its
own) checks each new young_early.json (early_doc) and hands it to live_put("young", doc), so live.json and the app's live store (row
current, and its count and newest age in row status) carry it, both at once; the first write of the app's live store that carries a
listed list (the first git push when there is no live store) calls young_published(doc), which sends the "new coins" notification
once per cycle, only with MEMEBOT_PUSH_YOUNG=1 (off by default: the launch radar pushes only coins without a trap found).
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, threading, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "python3"


def log(s, agent=None):
    """A progress line on stderr; the Agent office record files it under agent (default: the step at work)."""
    print(s, file=sys.stderr, flush=True)
    OFFICE.line(s, agent)


def ms():
    return int(time.time() * 1000)


def commas(v):
    return "{:,}".format(int(v))


class Office:
    """Who did what in one cycle, for the Agent office tab (db/memebot/office.json): per worker step (agent) its start and end,
    its progress lines, its rate-limit waits per host, the hosts it gave up on and one result phrase. It only watches: every
    method swallows its own errors, so the record never changes or stops a cycle. Office() without a folder records nothing."""

    def __init__(self, d=None, t=None, horizon=None):
        self.d, self.t, self.horizon, self.rule, self.mode, self.cur, self.agents = d, t, horizon, None, None, None, {}
        self.rev, self.lock = 0, threading.RLock()     # rev counts the changes (the live view pushes a changed record only); the lock serves the threads that file and read it
        try:
            if d:
                if HERE not in sys.path:
                    sys.path.insert(0, HERE)
                import memebot as M
                self.rule = (M.PROFILES.get(horizon) or {}).get("RULE") or M.RULE
        except Exception:
            pass

    def begin(self, aid, bg=False):
        """aid starts now; a background one works beside the step at work. An agent that ran before works again (a background
        job redone in the foreground) and keeps its start and lines."""
        try:
            with self.lock:
                if self.d and aid:
                    a = self.agents.setdefault(aid, {"id": aid, "start": ms(), "end": None, "status": "running", "bg": bg, "lines": [], "waits": {}, "blocked": [], "out": ""})
                    if not bg:
                        if a["bg"]:      # its background run failed: the foreground redo is what held up the pick
                            a.update(bg=False, start=ms(), end=None, status="running")
                        self.cur = aid
                    self.rev += 1
        except Exception:
            pass

    def line(self, s, aid=None):
        """A progress line of aid (default: the step at work), with the rate-limit waits and the hosts given up on that it names.
        The first 30 and the last 30 lines are kept; the counts see every line."""
        try:
            with self.lock:
                a = self.agents.get(aid or self.cur)
                s = " ".join(s.split()) if isinstance(s, str) else ""
                if not a or not s:
                    return
                a["lines"].append(s[:200])
                if len(a["lines"]) > 90:
                    del a["lines"][30:-30]
                self.rev += 1
                m = re.search(r"! 429 rate limited by ([^\s,]+)", s)
                if m:
                    a["waits"][m.group(1)] = a["waits"].get(m.group(1), 0) + 1
                m = re.search(r"giving up on ([^\s,:]+)", s)
                if m:
                    host = m.group(1)
                    k = re.search(r"rate limited (\d+) times", s)
                    if k:                # a host that waits too often is dropped: its waits, not a block (POST waits print no line of their own)
                        a["waits"][host] = max(a["waits"].get(host, 0), int(k.group(1)))
                    elif host not in a["blocked"]:
                        a["blocked"].append(host)
        except Exception:
            pass

    def result(self, aid, out):
        """aid's result phrase: text, or a function that builds it from the step's JSON (a slip there costs only the phrase)."""
        try:
            if aid in self.agents:
                said = str(out() if callable(out) else out)[:200]
                with self.lock:
                    self.agents[aid]["out"] = said
                    self.rev += 1
        except Exception:
            pass

    def done(self, aid, out=None, status="done", end=None):
        """aid finished (end: when its process really exited, for a background job); status done, failed, skipped or fallback."""
        try:
            with self.lock:
                a = self.agents.get(aid)
                if not a:
                    return
                a["end"], a["status"] = int(end or ms()), status
                if self.cur == aid:
                    self.cur = None
                self.rev += 1
        except Exception:
            return
        if out is not None:
            self.result(aid, out)

    def fail(self):
        """The step at work failed and the cycle stops: the record says so, for the background jobs still at work too (their tails stop
        first, so the record saved here is the one the cycle ends with)."""
        stop_tails()
        self.done(self.cur, status="failed")
        for aid, a in list(self.agents.items()):
            if a.get("status") == "running":
                self.done(aid, status="failed")
        self.save()

    def doc(self):
        """The record as office.json holds it, copied under the lock (the live view adds two keys to it)."""
        with self.lock:
            agents = [dict(a, lines=list(a["lines"]) if len(a["lines"]) <= 60 else a["lines"][:30] + a["lines"][-30:], waits=dict(a["waits"]), blocked=list(a["blocked"]))
                      for a in self.agents.values()]
            return {"v": 1, "t": self.t, "end": ms(), "horizon": self.horizon, "rule": self.rule, "mode": self.mode, "agents": agents}

    def save(self):
        """db/memebot/office.json, written whole and then swapped in; it travels with the other db/memebot docs on sync."""
        try:
            if not self.d:
                return
            doc = self.doc()
            path = os.path.join(self.d, "db", "memebot", "office.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(doc, f, separators=(",", ":"))
            os.replace(path + ".tmp", path)
        except Exception:
            try:
                os.remove(os.path.join(self.d, "db", "memebot", "office.json.tmp"))
            except Exception:
                pass


OFFICE = Office()    # the cycle at work puts its own record here (log() files the lines under its steps)
LIVE_FIRST, LIVE_EVERY, LIVE_BEAT, LIVE_WAIT = 10, 45, 60, 20   # the live view (s): the first push after the start, the least gap between two
# pushes, a heartbeat push of an unchanged record once the last good push is this old (the page tells a quiet step from a scan that died),
# and the most one push may take (also the most the end of a cycle waits for the last writes and notifications)
LIVE_KICK = 5        # s: a new early list from the spotter ("spotter", radar.py early) is pushed at once, at most this often
EARLY = {"t": None, "doc": None, "rev": 0, "sig": None}   # this cycle's early list as both live views carry it ("young", live_put): the
EARLY_LOCK = threading.Lock()                             # cycle's now, the checked doc, its revision and the file signature it came from
APP_FIRST, APP_EVERY, APP_BEAT = 2, 5, 30   # the app's live store (s): the first write after the start, the least gap between two writes of a
# changed record, a heartbeat once the last good write is this old (failed writes back off: APP_EVERY doubled per failure, at most 80 s)
LIVE_EXTRA, LIVE_EXTRA_LOCK, LIVE_EXTRA_REV = {}, threading.Lock(), [0]   # extra keys of this cycle's live record (live_put)
APP_JOBS = []         # this cycle's notifications on their way (app_bg): the end of the cycle waits for them, LIVE_WAIT s at most
YOUNG_SENT = {"t": None}   # the cycle whose "new coins" notification went out (young_published sends one per cycle)
EARLY_MAX_BYTES = 24000     # an early list bigger than this is not pushed (20 coins take about 10 KB)
CHECK_LIMIT_S = 30          # radar.py check runs after the trader, on the scan's critical path: killed after this (it takes about 1 s)
# the trader waits for the training beside the scan until this long after the cycle began (s); then it is stopped and the runs read
# the last train.json. The scan job's limit is 55 min: about 2 before the cycle, 8 for the run after the training, 1 after the cycle
# (on 2026-10-16 the training took 23 to 27 min and was already the last thing the trader waited for)
TRAIN_WAIT_S = float(os.environ.get("MEMEBOT_TRAIN_WAIT_S") or 36 * 60)


def last_training(d, rule):
    """After a cycle whose training did not finish: which training the runs read, in words for the office. When train.json is another
    profile's (a 24h run between 2h runs), this profile's own last one (train-<rule>.json, kept at each swap) goes back in its place,
    so the runs do not fall back to the defaults while the trainings keep being stopped."""
    path = os.path.join(d, "db", "memebot", "train.json")
    doc = load_doc(path)
    own = os.path.join(d, "db", "memebot", "train-%s.json" % re.sub(r"[^A-Za-z0-9_.-]+", "-", str(rule)))
    if rule and str(doc.get("rule") or "") != str(rule) and os.path.exists(own):
        shutil.copyfile(own, path + ".tmp")
        os.replace(path + ".tmp", path)
        doc = load_doc(path)
    if not doc.get("t"):
        return "no training yet: the runs read the defaults"
    when = dt.datetime.fromtimestamp(doc["t"] / 1000, dt.timezone.utc).strftime("%d %b %H:%M UTC")
    return ("the runs read the training of %s" % when) + ("" if not rule or str(doc.get("rule") or "") == str(rule) else " (another profile's: the runs read the defaults)")


def keep_own(d, rule):
    """This profile's newest training, kept beside train.json (train-<rule>.json) for last_training."""
    try:
        if rule and str(load_doc(os.path.join(d, "db", "memebot", "train.json")).get("rule") or "") == str(rule):
            own = os.path.join(d, "db", "memebot", "train-%s.json" % re.sub(r"[^A-Za-z0-9_.-]+", "-", str(rule)))
            shutil.copyfile(os.path.join(d, "db", "memebot", "train.json"), own + ".tmp")
            os.replace(own + ".tmp", own)
    except OSError as e:
        log("training copy not kept: %s" % e)


def load_doc(path):
    """A JSON object from path, or {} (missing, broken or not an object)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}
EARLY_STATES = ("listed", "empty", "small", "failed", "off")
B58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
X_RE = re.compile(r"^https://(www\.)?(x|twitter)\.com/[A-Za-z0-9_]{1,30}(/status/\d{1,25})?/?$")
EARLY_NUMS = ("born", "minted", "ageMin", "px", "mc", "liq", "vol1", "vol", "chgM5", "chgH1", "buysH1", "sellsH1", "score", "k")
EARLY_TOP = ("at", "rcAt", "minLiq", "maxAgeMin", "asked", "requests", "dsWaits", "pairs", "universe", "n")


CHILD_HIDE = ("SUPABASE_SECRET_KEY",)    # only bot.py itself uses it (app.py is imported, never run as a child): no child process gets it


def child_env(**extra):
    """The environment for a child process (fetch.py, memebot.py, radar.py, git): this process's without CHILD_HIDE, plus extra."""
    env = {k: v for k, v in os.environ.items() if k not in CHILD_HIDE}
    env.update(extra)
    return env


def early_num(v):
    """A finite number, else None (bools are not numbers here)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def early_doc(path, now):
    """The spotter's early list (young_early.json) checked for the page: a dict of version 1 for this cycle (t == now) in a known state,
    at most 20 coins with known keys only, strings cut, addresses and X links that match their patterns (a coin with a bad address is
    dropped), finite numbers. The clean doc, or None (missing, wrong, or over EARLY_MAX_BYTES). It never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or raw.get("v") != 1 or now is None or raw.get("t") != now or isinstance(raw.get("t"), bool) or raw.get("state") not in EARLY_STATES:
            return None
        txt = lambda v, n: (str(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else "")[:n]
        doc = {"v": 1, "t": raw["t"], "id": txt(raw.get("id"), 20), "state": raw["state"], "why": txt(raw.get("why"), 120),
               "rcState": raw.get("rcState") if raw.get("rcState") in ("pending", "done", "partial", "down") else None, "rcWhy": txt(raw.get("rcWhy"), 120),
               "partial": raw.get("partial") is True, "rule": txt(raw.get("rule"), 24), "horizon": txt(raw.get("horizon"), 8)}
        for k in EARLY_TOP:
            doc[k] = early_num(raw.get(k))
        coins = []
        for c in (raw.get("coins") if isinstance(raw.get("coins"), list) else [])[:20]:
            if not isinstance(c, dict) or not isinstance(c.get("addr"), str) or not B58_RE.match(c["addr"]):
                continue
            o = {"addr": c["addr"], "sym": txt(c.get("sym"), 24), "name": txt(c.get("name"), 48),
                 "pair": c["pair"] if isinstance(c.get("pair"), str) and B58_RE.match(c["pair"]) else None,
                 "dex": txt(c.get("dex"), 24), "launchpad": txt(c.get("launchpad"), 24),
                 "x": c["x"] if isinstance(c.get("x"), str) and X_RE.match(c["x"]) else "",
                 "src": [txt(s, 24) for s in (c.get("src") if isinstance(c.get("src"), list) else []) if isinstance(s, str)][:6], "held": c.get("held") is True}
            for k in EARLY_NUMS:
                o[k] = early_num(c.get(k))
            rc = c.get("rc")
            o["rc"] = ({"level": rc["level"], "text": txt(rc.get("text"), 120), "top1": early_num(rc.get("top1")), "lp": early_num(rc.get("lp"))}
                       if isinstance(rc, dict) and rc.get("level") in ("danger", "warn", "clean", "none") else None)
            coins.append(o)
        doc["coins"] = coins
        if len(json.dumps(doc, separators=(",", ":"))) > EARLY_MAX_BYTES:
            return None
        return doc
    except Exception:
        return None


def live_put(key, value):
    """HOOK for extra top-level keys of this cycle's live record, e.g. live_put("young", doc) for the launch spotter's early New launches
    list: live.json on the branch "live" and the app's live store (row current; row status gets its count and newest age) carry it from
    their next write on, which comes within APP_EVERY s. None removes the key. A cycle starts with none. The value is copied (as JSON)
    at once, so the caller may change its own object afterwards; a value that is not strict JSON (an object JSON cannot hold, a loop, NaN
    or infinity, which the live store would refuse) is left out and False returned."""
    try:
        value = None if value is None else json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        return False
    with LIVE_EXTRA_LOCK:
        if value is None:
            LIVE_EXTRA.pop(key, None)
        else:
            LIVE_EXTRA[key] = value
        LIVE_EXTRA_REV[0] += 1
    return True


def live_sig():
    """What the live views compare to see a changed record: the office record's revision and the extras' revision."""
    return OFFICE.rev, LIVE_EXTRA_REV[0]


def live_record(live):
    """(signature, record): the office record (office.json's keys) with the extras of live_put, "live" and "updated" (ms). Both live views
    send this record; the launch spotter's list rides in it as "young"."""
    with OFFICE.lock:
        rev, doc = OFFICE.rev, OFFICE.doc()
    with LIVE_EXTRA_LOCK:
        sig, extra = (rev, LIVE_EXTRA_REV[0]), dict(LIVE_EXTRA)
    doc.update(extra)
    doc.update(live=live, updated=ms())
    return sig, doc


def app_mod():
    """app.py when the app's live store is set up (SUPABASE_URL and SUPABASE_SECRET_KEY), else None: without them it is not even imported."""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY")):
        return None
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import app as A
        return A if A.enabled() else None
    except Exception:
        return None


def app_bg(name, *args):
    """app.<name>(*args) (a notification) on a daemon thread beside the cycle; the cycle's end waits for it (LIVE_WAIT s at most). Nothing
    without the app's live store."""
    A = app_mod()
    if not A:
        return None
    try:
        t = threading.Thread(target=lambda: getattr(A, name)(*args), daemon=True)
        t.start()
        APP_JOBS.append(t)
        return t
    except Exception:
        return None


def early_set(t, doc):
    """This cycle's early list (doc of cycle t; None removes it) for both live views: it goes to live_put("young", doc), so live.json and
    the app's live store carry it from their next push or write on (the git push at once: the kick). A list of another cycle is
    ignored. True when it was taken."""
    with EARLY_LOCK:
        if t is None or EARLY["t"] != t:
            return False
        EARLY["doc"] = doc
        EARLY["rev"] += 1
        live_put("young", doc)        # under EARLY_LOCK: an older list never overtakes a newer one on its way to the live record
        return True


RC_UNFINISHED = "RugCheck did not finish: the launch spotter was stopped"


def early_unfinished(d, t, why=RC_UNFINISHED):
    """A list of this cycle still waiting for RugCheck when its spotter is gone (killed, or the cycle ended) says so: rcState "partial"
    with the reason (rcWhy) in young_early.json and in the live views, so the page never shows "checking..." for the rest of the hour.
    True when it marked one. It never raises."""
    try:
        path = os.path.join(d, "young_early.json")
        doc = early_doc(path, t) if os.path.exists(path) else None
        with EARLY_LOCK:
            live = EARLY["doc"] if EARLY["t"] == t else None
        doc = doc or live
        if not isinstance(doc, dict) or doc.get("rcState") != "pending":
            return False
        doc = dict(doc, rcState="partial", rcWhy=str(why)[:120])
        if os.path.exists(path):
            raw = read_json(path)
            if isinstance(raw, dict) and raw.get("t") == t and raw.get("rcState") == "pending":
                raw.update(rcState="partial", rcWhy=doc["rcWhy"])
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(raw, f, separators=(",", ":"))
                os.replace(path + ".tmp", path)
        early_set(t, doc)
        return True
    except Exception:
        return False


def read_json(path):
    """A JSON file's content, or None (missing or not JSON)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def young_published(doc):
    """HOOK for the launch spotter: called once the early New launches list of this cycle is first published (the doc both live views
    carry as "young"): by AppFeed after its first write that carries a listed list (the app reads its own rows, so a tap on the
    notification finds the list there), and by the live view's git push only when there is no AppFeed. It sends
    the "new coins" push notification (app.notify_young) beside the cycle, once per cycle (later versions of the list, e.g. with
    RugCheck, send nothing), and only for a list with coins (state "listed" when the doc names one) of this cycle. It never raises;
    without the app's live store it does nothing. Off by default: this list is not filtered for traps, and only the launch radar's
    coins without a trap found are pushed; MEMEBOT_PUSH_YOUNG=1 (the repository variable, passed by the scan workflow) brings it back."""
    if os.environ.get("MEMEBOT_PUSH_YOUNG") != "1":
        return False
    try:
        if not isinstance(doc, dict) or not [c for c in (doc.get("coins") or []) if isinstance(c, dict)] or doc.get("state", "listed") != "listed":
            return False
        with EARLY_LOCK:
            et = EARLY["t"]
        if et is not None and doc.get("t") != et:       # a list of another cycle
            return False
        with LIVE_EXTRA_LOCK:
            if YOUNG_SENT["t"] == OFFICE.t:
                return False
            YOUNG_SENT["t"] = OFFICE.t
        return app_bg("notify_young", doc) is not None
    except Exception:
        return False


def pick_brief(rec, now):
    """This cycle's top recommendation in a few keys for the live record ("pick"), or None (no pick, or the recommendation of an earlier run)."""
    if not isinstance(rec, dict) or rec.get("t") != now or not isinstance(rec.get("picks"), list) or not rec["picks"] or not isinstance(rec["picks"][0], dict):
        return None
    p = rec["picks"][0]
    return {"t": now, "sym": str(p.get("sym") or "?")[:24], "name": str(p.get("name") or "")[:48], "score": p.get("score") if isinstance(p.get("score"), (int, float)) else None,
            "tier": p.get("tier"), "addr": str(p.get("addr") or "")[:64]}


def redact(s):
    """A remote URL (or a message naming one) without the credentials in it."""
    return re.sub(r"(https?://)[^/@\s]*@", r"\1", str(s))


def origin_url():
    """This code folder's git origin ('' when there is none): where sync and the live view push by default."""
    p = subprocess.run(["git", "-C", HERE, "remote", "get-url", "origin"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=child_env())
    return p.stdout.strip() if p.returncode == 0 else ""


class Live:
    """The office record pushed while a cycle runs, for the page's live view; only with MEMEBOT_LIVE=1, which the scan workflow sets.
    It force-pushes a branch "live" that holds one commit with one file, live.json (office.json's keys plus "live": true, false on the
    last one, and "updated", ms): about 10 s after the start, then every 45 s when the record changed, a heartbeat with a fresh "updated"
    when the last good push is a minute old (a step can go minutes without a new line), and once more at the end. It pushes from a git
    folder of its own (<dir>/live.git, made fresh each cycle) and only watches: the pushes run on a daemon thread (the early list's file
    watcher on another, so a push that hangs never holds up the list on its way to the app's live store), a push is killed
    after 20 s, the end cuts a push still running short and waits at most 20 s for the last one, the first error is printed (never
    filed in the record) and every error is swallowed. The record is live_record's (the office record plus the extras of live_put).
    With the app's live store set up (app_mod) an AppFeed writes the same record there on a thread of its own; without a remote the
    git pushes stay off and only the AppFeed runs."""

    def __init__(self, d, remote, app=None):
        self.git_dir, self.remote = os.path.join(os.path.abspath(d), "live.git"), remote
        self.stop, self.cut = threading.Event(), threading.Event()    # stop: the loop ends; cut: only the last snapshot may still go out
        self.lock, self.plock = threading.Lock(), threading.Lock()   # lock: one push at a time; plock: the git process now running
        self.proc, self.pushed, self.said = None, None, False
        self.t0, self.tried, self.ok = time.time(), None, None        # the start, the last push begun, the last good push begun
        self.d, self.early_pushed = os.path.abspath(d), None          # the cycle's folder (young_early.json) and the early list's revision last sent
        self.feed = AppFeed(app) if app else None                    # the app's live store, on a thread of its own
        if remote:
            shutil.rmtree(self.git_dir, ignore_errors=True)
        self.watcher = threading.Thread(target=self.watch, daemon=True)  # the early list for both live views, on a thread of its own: a git push
        self.watcher.start()                                             # that hangs for 20 s never holds up the app's copy of the list
        self.thread = threading.Thread(target=self.loop, daemon=True)    # the git pushes, only with a remote
        if remote:
            self.thread.start()

    @staticmethod
    def start(d, remote=None):
        """The live view of this cycle, or None: MEMEBOT_LIVE is not 1, or neither a remote (--remote, else RESULTS_URL, else the origin)
        nor the app's live store (app_mod) is known."""
        try:
            if os.environ.get("MEMEBOT_LIVE") != "1":
                return None
            remote = remote or os.environ.get("RESULTS_URL") or origin_url()
            A = app_mod()
            if not remote and not A:
                print("live view: off, no remote to push to", file=sys.stderr, flush=True)
                return None
            if remote:
                print("live view: the office goes to branch live of %s every %d s while it changes, at least every %d s" % (redact(remote), LIVE_EVERY, LIVE_BEAT),
                      file=sys.stderr, flush=True)
            if A:
                print("live view: the app's live store gets it every %d s while it changes, at least every %d s" % (APP_EVERY, APP_BEAT), file=sys.stderr, flush=True)
            return Live(d, remote, A)
        except Exception:
            return None

    def due(self, now):
        """Whether the loop pushes now: the first push soon after the start, so the page sees the scan begin; then a changed record at
        most every LIVE_EVERY s, and an unchanged one (a heartbeat) once the last good push is LIVE_BEAT s old. A new early list from the
        spotter goes out at once (the kick), LIVE_KICK s after the last push at the earliest."""
        if not OFFICE.d:
            return False
        with EARLY_LOCK:
            kick = EARLY["doc"] is not None and EARLY["rev"] != self.early_pushed
        if kick and (self.tried is None or now - self.tried >= LIVE_KICK):
            return True
        if self.tried is None:
            return now - self.t0 >= min(LIVE_FIRST, LIVE_EVERY)
        if now - self.tried < min(LIVE_EVERY, LIVE_BEAT):
            return False
        return live_sig() != self.pushed or self.ok is None or now - self.ok >= LIVE_BEAT

    def watch_early(self):
        """Looks at <dir>/young_early.json (about once a second): a new file of this cycle is checked (early_doc) and becomes the early
        list both live views carry (live_put("young", doc)): the next git push (at once: the kick) and the app's next write."""
        try:
            st = os.stat(os.path.join(self.d, "young_early.json"))
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return
        with EARLY_LOCK:
            t, seen = EARLY["t"], EARLY["sig"]
        if sig == seen or t is None:
            return
        doc = early_doc(os.path.join(self.d, "young_early.json"), t)
        with EARLY_LOCK:
            if EARLY["t"] != t:          # a new cycle began meanwhile: this file is not its list
                return
            EARLY["sig"] = sig
            if doc is not None:
                EARLY["doc"] = doc
                EARLY["rev"] += 1
                live_put("young", doc)

    def watch(self):
        while not self.stop.wait(min(1.0, LIVE_EVERY / 4.0)):
            try:
                self.watch_early()
            except Exception:
                pass

    def loop(self):
        while not self.stop.wait(min(1.0, LIVE_EVERY / 4.0)):
            try:
                if self.remote and self.due(time.time()):
                    self.push(True)
            except Exception:
                pass

    @staticmethod
    def kill(p):
        try:
            os.killpg(p.pid, 9)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def git(self, until, *a, stdin=None, cut_ok=True):
        """One git command on the live folder, killed with its children when the push's time is up (or by finish, unless cut_ok is
        False: the last push); its output, or an error."""
        with self.plock:
            if cut_ok and self.cut.is_set():
                raise RuntimeError("cut short by the end of the cycle")
            p = subprocess.Popen(["git", "--git-dir", self.git_dir] + list(a), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=child_env(GIT_TERMINAL_PROMPT="0"), start_new_session=True)
            self.proc = p
        try:
            out, err = p.communicate(stdin, timeout=max(0.1, until - time.time()))
        except subprocess.TimeoutExpired:
            self.kill(p)
            try:
                p.wait(2)
            except Exception:
                pass
            raise RuntimeError("git %s took longer than %d s" % (a[0], LIVE_WAIT))
        finally:
            with self.plock:
                if self.proc is p:
                    self.proc = None
        if cut_ok and self.cut.is_set():
            raise RuntimeError("cut short by the end of the cycle")
        if p.returncode != 0:
            raise RuntimeError("git %s: %s" % (a[0], (err or out).decode("utf-8", "replace").strip()[-300:]))
        return out.decode("utf-8", "replace").strip()

    def push(self, live):
        with self.lock:      # one push at a time, so the last one always lands last
            if live and self.cut.is_set():
                return
            try:
                o = OFFICE
                if not o.d:
                    return
                t = self.tried = time.time()
                with EARLY_LOCK:
                    erev = EARLY["rev"]
                rev, doc = live_record(live)      # the office record with this cycle's early list ("young", live_put); office.json never carries it
                self.early_pushed = erev          # tried: a push that fails is not kicked again (the regular pushes carry the list)
                until = t + LIVE_WAIT
                if not os.path.isdir(self.git_dir):
                    self.git(until, "init", "-q", "--bare", cut_ok=live)
                blob = self.git(until, "hash-object", "-w", "--stdin", stdin=json.dumps(doc, separators=(",", ":")).encode("utf-8"), cut_ok=live)
                tree = self.git(until, "mktree", stdin=("100644 blob %s\tlive.json\n" % blob).encode("utf-8"), cut_ok=live)
                commit = self.git(until, "-c", "user.name=memebot", "-c", "user.email=memebot@localhost", "commit-tree", tree, "-m", "live office " + ("at work" if live else "done"), cut_ok=live)
                self.git(until, "push", "-q", "--force", self.remote, commit + ":refs/heads/live", cut_ok=live)
                self.pushed, self.ok = rev, t
                if isinstance(doc.get("young"), dict) and not self.feed:
                    young_published(doc["young"])     # (with the app's live store, its AppFeed sends it once the app's own rows carry the list)
            except Exception as e:
                if live and self.cut.is_set():       # cut short so the last snapshot goes out at once: not an error
                    return
                if not self.said:
                    self.said = True
                    print("live view: push failed, the cycle goes on (%s)" % redact(" ".join(str(e).split()))[:300], file=sys.stderr, flush=True)

    def finish(self, until=None):
        """The last snapshot ("live": false): a push still running is killed first (it would hold the last one up), then the last one
        goes out off the main thread, beside the app's last write; both waited for until `until` (LIVE_WAIT s from now) and the push
        killed after that."""
        try:
            until = until or time.time() + LIVE_WAIT
            self.stop.set()
            self.cut.set()
            jobs = [self.feed.finish()] if self.feed else []
            if self.remote:
                with self.plock:
                    p = self.proc
                if p:
                    self.kill(p)
                t = threading.Thread(target=self.push, args=(False,), daemon=True)
                t.start()
                jobs.append(t)
            for t in jobs:
                t.join(max(0.0, until - time.time()))
            if self.remote and jobs[-1].is_alive():
                with self.plock:
                    p = self.proc
                if p:
                    self.kill(p)
        except Exception:
            pass


class AppFeed:
    """The live record (live_record) written to the app's live store (app.sink: Supabase rows status and current) while a cycle runs, on a
    daemon thread of its own beside the git pushes of Live: about APP_FIRST s after the start, then every APP_EVERY s while the record
    changes, a new early list at once, a heartbeat once the last good write is APP_BEAT s old, and the last one ("live": false) at the
    end (finish, which cuts a write still on its way short). After its first write it makes sure the VAPID keys exist (app.prepare: the
    app can subscribe before the first notification), and after a write of a record that first carries a listed early New launches
    list it sends the "new coins" notification (young_published). app.sink cuts each request off after a few seconds, prints its first
    failure and never raises; app.prepare runs on a daemon thread of its own."""

    def __init__(self, A):
        self.A, self.stop, self.lock = A, threading.Event(), threading.Lock()
        self.t0, self.tried, self.ok, self.sent, self.fails, self.early_sent = time.time(), None, None, None, 0, None
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def due(self, now):
        """Whether the loop writes now: the first write APP_FIRST s after the start; a new early list at once (the kick: the "new coins"
        notification waits for this write, so a tap finds the list in the app); then a changed record every APP_EVERY s, an unchanged one
        once the last good write is APP_BEAT s old, longer apart after failures."""
        if not OFFICE.d:
            return False
        with EARLY_LOCK:
            kick = EARLY["doc"] is not None and EARLY["rev"] != self.early_sent
        if kick and self.fails == 0:
            return True
        if self.tried is None:
            return now - self.t0 >= APP_FIRST
        if now - self.tried < min(80, APP_EVERY * 2 ** min(self.fails, 4)):
            return False
        return live_sig() != self.sent or self.ok is None or now - self.ok >= APP_BEAT

    def loop(self):
        prepared = False
        while not self.stop.wait(1.0):
            try:
                if self.due(time.time()):
                    self.write(True)
                if self.tried is not None and not prepared and not self.stop.is_set():
                    prepared = True          # on a thread of its own: up to five store requests, the status writes go on meanwhile (the end does not wait for it)
                    threading.Thread(target=self.A.prepare, daemon=True).start()
            except Exception:
                pass

    def write(self, live):
        with self.lock:
            with EARLY_LOCK:
                self.early_sent = EARLY["rev"]
            sig, doc = live_record(live)
            t = self.tried = time.time()
            ok = self.A.sink(doc)
            if ok:
                self.sent, self.ok, self.fails = sig, t, 0
            else:
                self.fails += 1
        if ok and isinstance(doc.get("young"), dict):
            young_published(doc["young"])

    def finish(self):
        """The last write ("live": false) on a thread of its own (Live.finish waits for it); the loop stops first, and a write still on its
        way is cut off (app.end_sink), so a slow store never holds the last one up past the end's LIVE_WAIT s."""
        self.stop.set()
        try:
            self.A.end_sink()
        except Exception:
            pass
        t = threading.Thread(target=self.write, args=(False,), daemon=True)
        t.start()
        return t


def run(args, d, now=None, expect_json=True, soft=False, limit=None):
    """A child command in the foreground: its progress lines are logged as they come, its JSON result returned. A failure stops the
    cycle (the office records it), unless soft: then it is logged in one line and None comes back. limit (s): the child is killed once it
    runs this long (a stalled name lookup is not covered by a request's own timeout), which counts as a failure."""
    cmd = [PY, os.path.join(HERE, args[0])] + args[1:] + ["--dir", d]
    if now and args[0] in ("memebot.py", "radar.py"):
        cmd += ["--now", str(now)]
    env = child_env(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    # the child's progress lines (stderr) are shown as they happen; its result (stdout) is collected
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
    cut = []
    timer = None
    if limit:
        def stop():
            if p.poll() is None:
                cut.append(1)
                try:
                    p.kill()
                except Exception:
                    pass
        timer = threading.Timer(limit, stop)
        timer.daemon = True
        timer.start()
    out = []
    t = threading.Thread(target=lambda: out.append(p.stdout.read()))
    t.start()
    for line in p.stderr:
        log(line.rstrip())
    t.join()
    p.wait()
    if timer:
        timer.cancel()
    stdout = out[0] if out else ""
    if soft and p.returncode != 0:
        log("%s %s, the cycle goes on: %s" % (" ".join(args[:2]), ("stopped after %g s" % limit) if cut else "failed (exit %s)" % p.returncode,
                                             " ".join(stdout.split())[-300:]))
        return None
    if p.returncode != 0:
        OFFICE.fail()
        raise SystemExit("%s failed:\n%s" % (" ".join(cmd[1:3]), stdout[-2000:]))
    if not expect_json:
        return stdout
    try:
        return json.loads(stdout)
    except ValueError:
        if soft:
            log("%s printed no JSON, the cycle goes on" % " ".join(args[:2]))
            return None
        OFFICE.fail()
        raise SystemExit("%s printed no JSON:\n%s" % (args[0], stdout[-2000:]))


def start_bg(args, d, now=None, agent=None, on_exit=None):
    """A child command started beside the rest of the cycle: its progress lines (stderr) and its result (stdout) go to files
    and are read when it is awaited (finish_bg), so the cycle's own log stays in order. A waiter thread notes when the process
    really exits (job["end"], ms), for the Agent office record of agent, and then calls on_exit(job) (its errors are swallowed)."""
    cmd = [PY, os.path.join(HERE, args[0])] + args[1:] + ["--dir", d]
    if now and args[0] in ("memebot.py", "radar.py"):
        cmd += ["--now", str(now)]
    base = os.path.join(d, "bg-" + re.sub(r"[^a-z0-9]+", "-", " ".join(args[:2]).lower()).strip("-"))
    out, err = open(base + ".out", "w", encoding="utf-8"), open(base + ".err", "w", encoding="utf-8")
    p = subprocess.Popen(cmd, stdout=out, stderr=err, text=True, encoding="utf-8", errors="replace", env=child_env(PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    job = {"p": p, "out": out, "err": err, "t0": time.time(), "name": " ".join(args[:2]), "agent": agent, "filed": 0, "lock": threading.Lock(), "stop": threading.Event()}
    BG_JOBS.append(job)
    OFFICE.begin(agent, bg=True)
    try:
        def wait():
            p.wait()
            job.update(end=ms())
            if on_exit:
                try:
                    on_exit(job)
                except Exception:
                    pass
        job["waiter"] = threading.Thread(target=wait, daemon=True)
        job["waiter"].start()
        job["tail"] = threading.Thread(target=tail_bg, args=(job, OFFICE), daemon=True)
        job["tail"].start()
    except Exception:
        pass
    return job


BG_JOBS = []         # the background jobs started and not yet awaited: a cycle that stops early stops their tails (stop_tails)


def tail_bg(job, office):
    """Files each new progress line of a background job under its agent while the job runs, so the live view sees it at work. It splits
    and decodes the lines as finish_bg's read of the whole file does, and finish_bg files the ones it did not reach: the record ends the same.
    It ends once the process exited and the file is read to its end, or when stop_tails (a cycle that stops) or finish_bg stops it."""
    try:
        with open(job["err"].name, "rb") as f:
            buf = b""
            while not job["stop"].is_set():
                exited = job["p"].poll() is not None      # asked before the read: all it wrote before it exited is in the file by then
                got = f.read()
                buf += got or b""
                k = buf.rfind(b"\n") + 1
                if k:                # whole lines only: up to the last \n, so a \r\n is never cut in two
                    lines = [ln for ln in re.split(r"\r\n|\r|\n", buf[:k].decode("utf-8", "replace"))[:-1] if ln.split()]
                    buf = buf[k:]
                    with job["lock"]:
                        if job.get("closed"):
                            return
                        for ln in lines:
                            office.line(ln, job["agent"])
                            job["filed"] += 1
                if not got:
                    if exited:
                        return
                    job["stop"].wait(1)
    except Exception:
        pass


def stop_bg(job, why):
    """Kills a background job if it is still at work (why: its office phrase) and waits until its waiter has filed its result, so the
    record saved next already says so: the launch spotter (its early list is of no use once the scan stops or the trader starts) and
    the trainer at its deadline (TRAIN_WAIT_S)."""
    try:
        if job["p"].poll() is None:
            job["killed"] = why
            job["p"].kill()
        job["p"].wait(5)
        if job.get("waiter"):
            job["waiter"].join(5)
    except Exception:
        pass


def stop_tails():
    """The tails of the background jobs not yet awaited stop filing lines (a cycle that stops early: the record it saves is the one it
    ends with, and no tail outlives its cycle in bot.py loop). The jobs themselves run on as before, except the launch spotter: it is
    killed (Office.fail calls this first, so a cycle that fails in any step stops its spotter too)."""
    while BG_JOBS:
        job = BG_JOBS.pop()
        if job.get("agent") == "spotter":
            stop_bg(job, "stopped when the scan stopped")
        try:
            job["stop"].set()
            with job["lock"]:      # once closed, the tail files nothing more and ends at its next turn (no wait here)
                job["closed"] = True
        except Exception:
            pass


def finish_bg(job):
    """Wait for a background command, log its progress lines now, and return its JSON result (None when it failed)."""
    job["p"].wait()
    if job.get("waiter"):
        job["waiter"].join(5)
    job["end"] = job.get("end") or ms()
    job["out"].close()
    job["err"].close()
    if job in BG_JOBS:
        BG_JOBS.remove(job)
    filed = 0
    if job.get("tail"):
        job["stop"].set()
        job["tail"].join(5)
        with job["lock"]:
            job["closed"], filed = True, job["filed"]
    with open(job["err"].name, encoding="utf-8", errors="replace") as f:
        for line in f:           # the cycle's log gets the job's lines now, in one block; the record gets the ones the tail did not file
            print(line.rstrip(), file=sys.stderr, flush=True)
            if line.split():
                filed -= 1
                if filed < 0:
                    OFFICE.line(line.rstrip(), job["agent"])
    with open(job["out"].name, encoding="utf-8", errors="replace") as f:
        text = f.read()
    job["secs"] = time.time() - job["t0"]
    if job.get("killed"):         # stopped by the cycle (stop_bg): not a failure of its own
        log("%s stopped: %s" % (job["name"], job["killed"]), job["agent"])
        return None
    if job["p"].returncode != 0:
        log("%s failed in the background (exit %s): %s" % (job["name"], job["p"].returncode, text[-500:]), job["agent"])
        return None
    try:
        return json.loads(text)
    except ValueError:
        log("%s printed no JSON in the background: %s" % (job["name"], text[-500:]), job["agent"])
        return None


KEEP_RESULTS_DAYS = 60      # scored snapshot chunks older than this leave the cache (the training does not need older coins)
KEEP_RAW_DAYS = 3           # a raw snapshot chunk that was never scored by then never will be (its coins never got a price)
KEEP_EARLY_DAYS = 30        # the early-list record (db/memeearly, radar.py check)
KEEP_RADAR_DAYS = 30        # the launch radar's records (db/memeradar, imported from the radar-data branch); db/memepeak and db/memeradarpaper are never pruned


def prune(d, now):
    """Keep the Actions cache small: old scored results and raw snapshot chunks that never got scored are deleted. The launch radar's
    hour docs (db/memeradar) leave the results branch after KEEP_RADAR_DAYS; the peak docs (db/memepeak), the radar account's docs
    (db/memeradarpaper, radar_paper.py), the minute paths (db/memepath, peak.write_path) and the learning trader's decisions
    (db/memetrader, traders.py) are never deleted."""
    gone = 0
    for sub, days in (("memesnapres", KEEP_RESULTS_DAYS), ("memesnap", KEEP_RAW_DAYS), ("memeyoung", KEEP_RESULTS_DAYS), ("memeearly", KEEP_EARLY_DAYS),
                      ("memeradar", KEEP_RADAR_DAYS)):
        for fn in glob.glob(os.path.join(d, "db", sub, "*.json")):
            try:
                t = (json.load(open(fn, encoding="utf-8")) or {}).get("t")
                if isinstance(t, (int, float)) and now - t > days * 86_400_000:
                    os.remove(fn)
                    gone += 1
            except (OSError, ValueError):
                continue
    if gone:
        log("pruned %d old snapshot files" % gone)
    return gone


def apply_out(d):
    """out/manifest.json -> db/<collection>/<doc_id>.json"""
    man = os.path.join(d, "out", "manifest.json")
    if not os.path.exists(man):
        return 0
    n = 0
    for w in json.load(open(man, encoding="utf-8")):
        dst_dir = os.path.join(d, "db", w["collection"])
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(w["file"], os.path.join(dst_dir, w["doc_id"] + ".json"))
        n += 1
    return n


def M_DEEP_SCAN_BELOW():
    sys.path.insert(0, HERE)
    import memebot as M
    return M.DEEP_SCAN_BELOW


def M_SWITCH_AT():
    sys.path.insert(0, HERE)
    import memebot as M
    return M.switch_at()


def chunk_addrs(g):
    out = []
    for ch in g.get("chunks") or []:
        out += ch.split(",")
    return [a for a in out if a]


def cycle(d, force=False, offline=False, mock="", now=None, push=False, remote=None, branch="results", rescan=False, recommend=False, horizon="24h"):
    """One cycle (cycle_steps); with MEMEBOT_LIVE=1 its office record is pushed while it runs and once more when it ends, failed or not.
    A cycle that stops early stops the tails of its background jobs first."""
    with EARLY_LOCK:                 # no early list until cycle_steps names this cycle's (the watcher never takes the last cycle's file)
        EARLY.update(t=None, doc=None, sig=None, rev=EARLY["rev"] + 1)
    with LIVE_EXTRA_LOCK:
        LIVE_EXTRA.clear()
        LIVE_EXTRA_REV[0] += 1
    del APP_JOBS[:]
    live = Live.start(d, remote)
    try:
        return cycle_steps(d, force, offline, mock, now, push, remote, branch, rescan, recommend, horizon)
    finally:
        stop_tails()          # a cycle that stops early stops its launch spotter too (the list is of no use without the cycle)
        with EARLY_LOCK:
            et = EARLY["t"]
        early_unfinished(d, et)      # a list still waiting for RugCheck says it did not finish, in the file and in the last push
        until = time.time() + LIVE_WAIT      # the last writes and the notifications on their way: LIVE_WAIT s at most, together
        if live:
            live.finish(until)
        for t in list(APP_JOBS):
            t.join(max(0.0, until - time.time()))


def cycle_steps(d, force=False, offline=False, mock="", now=None, push=False, remote=None, branch="results", rescan=False, recommend=False, horizon="24h"):
    global OFFICE
    os.makedirs(d, exist_ok=True)
    t0 = ms()
    now = int(now or t0)      # one clock for the whole cycle, so gather asks for exactly the coins run() will score
    o = OFFICE = Office(d, t0, horizon)    # who did what, on the real clock: db/memebot/office.json for the Agent office tab
    for old in (os.path.join(d, "young_early.json"), os.path.join(d, "young_early.json.tmp")):   # the last cycle's early list is never this one's
        if os.path.exists(old):
            os.remove(old)
    shutil.rmtree(os.path.join(d, "radar"), ignore_errors=True)
    with EARLY_LOCK:
        EARLY.update(t=now, doc=None, rev=EARLY["rev"] + 1, sig=None)
        live_put("young", None)
    o.begin("dispatch")
    extra = (["--force"] if force else []) + (["--snapshot"] if rescan else []) + (["--recommend"] if recommend else []) + ["--horizon", horizon]
    mode = run(["memebot.py", "mode"] + extra, d, now)
    print("mode: %s" % json.dumps({k: mode[k] for k in ("pick", "room", "why", "scan", "bigTestSaveDue", "bigTestDue", "open")}), file=sys.stderr, flush=True)
    o.line(str(mode.get("why") or ""))
    o.mode = mode.get("scan")
    o.done("dispatch", lambda: " · ".join([{"full": "full scan", "light": "light scan"}.get(mode["scan"], "prices only")] + ["recommend"] * bool(recommend)
                                          + ["%d open positions" % mode["open"]] * bool(mode.get("open")) + ["%s big-test coins due" % commas(mode["bigTestDueCoins"])] * bool(mode.get("bigTestDueCoins"))))
    # the training reads only the scored snapshots and the tip record, which nothing in this cycle writes before the run step:
    # it runs beside the fetching from the start and its doc is swapped in right before the pick, so every step before the pick
    # reads the last run's train.json exactly as when the training ran at the end (the minutes it takes hide behind the network)
    train_out = os.path.join(d, "train.next.json")
    if os.path.exists(train_out):     # left by a cycle that died before its pick: never swap in an old doc
        os.remove(train_out)
    train_job = start_bg(["memebot.py", "train", "--horizon", horizon, "--out", train_out], d, now, "trainer") if (mode["pick"] or mode["bigTestDue"]) else None
    fetch = lambda args, expect_json=True: run(["fetch.py"] + args + (["--mock", mock] if mock else []), d, expect_json=expect_json)
    candle_job = spot = None
    if not offline:
        o.begin("scouts")
        if mode["scan"] in ("full", "light"):
            fetch(["sources"] + (["--light"] if mode["scan"] == "light" else []), expect_json=False)
            o.done("scouts")
        else:
            # only prices: drop the old source files so the gather asks for exactly the open positions and the due big-test coins
            import fetch as F
            F.clear_sources(d, F.SOURCE_DIRS, ("lists.json",))
            o.done("scouts", "only prices this run: no scan", "skipped")
        if (mode["pick"] or mode["bigTestSaveDue"]) and mode.get("candles"):
            # the minute candles of the held coins and of the tips due for a check are known before the scan (memebot.py mode):
            # fetched beside it, after the sources step, which clears the candles folder (the fetch keeps GeckoTerminal's gap to the sources' last request)
            items_file = os.path.join(d, "candles.json")
            with open(items_file, "w", encoding="utf-8") as f:
                json.dump(mode["candles"], f)
            candle_job = start_bg(["fetch.py", "candles", "--items", items_file] + (["--mock", mock] if mock else []), d, agent="candles")
        # the launch spotter: the coins under an hour old for the New launches tab about five minutes into the scan (radar.py). It
        # works in its own folder beside the price desk and never changes what the trader reads; a failure costs only the early list
        # the switch (memebot.switch_at) ends the new launches: from then on the spotter stays off and says when they ended
        switch = M_SWITCH_AT()
        early_env = os.environ.get("MEMEBOT_EARLY", "1") != "0"
        early_on = early_env and now < switch
        if recommend and mode["pick"] and mode["scan"] == "full" and early_on:
            spot = start_bg(["radar.py", "early", "--t0", str(t0), "--horizon", horizon] + (["--mock", mock] if mock else []), d, now, "spotter",
                            on_exit=lambda job: spot_done(o, job, now))
        else:
            early_set(now, {"v": 1, "t": now, "state": "off", "coins": [], "why": "early list switched off" if not early_env else (
                "new launches ended on " + time.strftime("%b %d", time.gmtime(switch // 1000))) if not early_on else (
                "light scan" if mode["scan"] == "light" else ("no scan this run, only prices" if mode["scan"] != "full" else "not a recommend scan"))})
    o.begin("market")
    g = run(["memebot.py", "gather"], d, now)
    if not offline and mode["scan"] in ("full", "light"):
        o.result("scouts", lambda: "%s coins found" % commas(g["coins"]))
    need = chunk_addrs(g)
    asked = set(need)                                      # DexScreener was asked about these once; the deep pass asks only about new addresses
    if need and not offline:
        log("gather: %d coins, %d still need DexScreener data" % (g["coins"], len(need)))
        need_file = os.path.join(d, "need.json")          # thousands of addresses do not fit on a command line
        with open(need_file, "w", encoding="utf-8") as f:
            json.dump({"chunks": [",".join(need[i:i + 30]) for i in range(0, len(need), 30)]}, f)
        fetch(["tokens", "--from-gather", need_file])
        g = run(["memebot.py", "gather"], d, now)
    log("gather: %d coins (%d with full DEX data), coverage %.0f%%, lists %s" % (g["coins"], g["fullData"], 100 * g["coverage"], g["lists"]))
    o.done("market", lambda: "%s coins, coverage %.0f%%" % (commas(g["coins"]), 100 * g["coverage"]))
    if spot and spot["p"].poll() is not None:      # the spotter is done long before the market step: its lines go to the log in one block
        finish_bg(spot)
        spot = None
    if mode["pick"] or mode["bigTestSaveDue"]:
        o.begin("analyst")
        s = run(["memebot.py", "shortlist"] + extra, d, now)
        log("shortlist: %d of %d gated coins get a RugCheck report; best: %s" % (s["n"], s["gated"], ", ".join(str(x) for x in s["pick"][:6])))
        o.done("analyst", lambda: "%s coins passed the gates; best: %s" % (commas(s["gated"]), ", ".join(str(x) for x in s["pick"][:3]) or "none"))
        if mode["pick"] and mode["scan"] == "full" and not offline and s["gated"] < M_DEEP_SCAN_BELOW():
            o.begin("deep")
            log("only %d coins passed the gates: searching deeper" % s["gated"])
            fetch(["deep"])
            g = run(["memebot.py", "gather"], d, now)
            need = [a for a in chunk_addrs(g) if a not in asked]   # the 1,200 addresses DexScreener had no pair for minutes ago are not asked again (that cost 80 s a run for 1 to 12 pairs)
            if need:
                with open(os.path.join(d, "need.json"), "w", encoding="utf-8") as f:
                    json.dump({"chunks": [",".join(need[i:i + 30]) for i in range(0, len(need), 30)]}, f)
                fetch(["tokens", "--from-gather", os.path.join(d, "need.json")])
                g = run(["memebot.py", "gather"], d, now)
            s = run(["memebot.py", "shortlist"] + extra, d, now)
            log("after the deep search: %d coins, %d gated; best: %s" % (g["coins"], s["gated"], ", ".join(str(x) for x in s["pick"][:6])))
            o.done("deep", lambda: "%s coins, %s passed the gates" % (commas(g["coins"]), commas(s["gated"])))
        if s["shortlist"] and not offline:
            o.begin("safety")
            meta_file = os.path.join(d, "shortmeta.json")
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(s.get("meta") or {}, f)
            rk = fetch(["risk", "--addrs", ",".join(s["shortlist"]), "--meta", meta_file])
            o.done("safety", lambda: "%d coins checked, %d RugCheck reports" % (len(s["shortlist"]), rk["reports"]))
        if not offline and s.get("candles") and not candle_job:
            # minute candles for the tips and new launches due for their 1 h / 24 h check: the record learns the peak inside the window
            o.begin("candles")
            items_file = os.path.join(d, "candles.json")
            with open(items_file, "w", encoding="utf-8") as f:
                json.dump(s["candles"], f)
            cn = fetch(["candles", "--items", items_file])
            o.done("candles", lambda: "%d of %d pools of minute candles" % (cn["pools"], len(s["candles"])))
        if mode["pick"] and not offline and s.get("refresh"):
            # the market moved during the scan: fresh prices for the candidates, then merge again, then decide
            o.begin("refresh")
            rf = fetch(["refresh", "--addrs", ",".join(s["refresh"])])
            g = run(["memebot.py", "gather"], d, now)
            o.done("refresh", lambda: "%d fresh pairs for %d candidates" % (rf["rows"], len(s["refresh"])))
    if candle_job:
        c = finish_bg(candle_job)
        if c is None:          # the background fetch failed: fetch them now, as before (the held coins' take-profit needs them)
            o.begin("candles")
            c = fetch(["candles", "--items", os.path.join(d, "candles.json")])
            o.done("candles", lambda: "%d of %d pools of minute candles, fetched again after the scan" % (c["pools"], len(mode["candles"])), "fallback")
        else:
            log("candles fetched beside the scan in %.0f s" % candle_job["secs"], "candles")
            o.done("candles", lambda: "%d of %d pools of minute candles" % (c["pools"], len(mode["candles"])), end=candle_job["end"])
    if train_job:
        # the training ran on the scored snapshots beside the fetching: the run reads the zero model and the tuned limits
        deadline = t0 / 1000.0 + TRAIN_WAIT_S
        try:
            train_job["p"].wait(max(0.0, deadline - time.time()))
        except subprocess.TimeoutExpired:      # still at work at the deadline: stopped, the scan must end inside its job's limit
            stop_bg(train_job, "still running %.0f min after the scan began" % (TRAIN_WAIT_S / 60))
        t = finish_bg(train_job)
        train_said = lambda: ("%s coin results from %d scans%s%s" % (commas(t["rows"]), t["scans"], " · zero model" if t.get("zeroModel") else "", " · tuned limits" if t.get("tunedWhy") else "")
                              if t["rows"] else "no scored snapshots yet: nothing to learn from")
        left = deadline - time.time()
        # a training that did not finish is amber (fallback), never failed: the scan goes on with the last training, and a failed agent
        # would make the live view say the scan stopped (report.py MB.state)
        if t is not None and os.path.exists(train_out):
            os.replace(train_out, os.path.join(d, "db", "memebot", "train.json"))
            keep_own(d, o.rule)
            log("training: %s (beside the scan, %.0f s)" % (t["note"], train_job["secs"]), "trainer")
            o.done("trainer", train_said, end=train_job["end"])
        elif train_job.get("killed") or left < 60:
            why = "still running %.0f min after the scan began: stopped" % (TRAIN_WAIT_S / 60) if train_job.get("killed") else "failed beside the scan, no time left to train again"
            why += ", " + last_training(d, o.rule)
            log("training: " + why, "trainer")
            o.done("trainer", why, "fallback", end=train_job["end"])
        else:                  # it failed beside the scan: train now, as before, until the same deadline
            o.begin("trainer")
            t = run(["memebot.py", "train", "--horizon", horizon], d, now, soft=True, limit=int(left))
            if t is None:
                why = "failed beside the scan and again after it, " + last_training(d, o.rule)
                log("training: " + why, "trainer")
                o.done("trainer", why, "fallback")
            else:
                keep_own(d, o.rule)
                log("training: " + t["note"])
                o.done("trainer", train_said, "fallback")
    if spot:
        if spot["p"].poll() is None:      # still at work when the trader starts: stopped, the scan does not wait for it
            stop_bg(spot, "still running at the trader step")
            finish_bg(spot)
            o.done("spotter", "still running at the trader step", "failed")
            path = os.path.join(d, "young_early.json")
            doc = early_doc(path, now) if os.path.exists(path) else None
            with EARLY_LOCK:
                empty = EARLY["doc"] is None and doc is None
            if empty:
                early_set(now, {"v": 1, "t": now, "state": "failed", "why": "the early list did not finish", "coins": []})
            elif not early_unfinished(d, now, "RugCheck did not finish: the launch spotter was still at work when the scoring began"):
                early_set(now, doc)        # its last list, in case the watcher has not taken it yet
        else:
            finish_bg(spot)
        spot = None
    o.begin("trader")
    r = run(["memebot.py", "run", "--mode", "pick" if mode["pick"] else "check"] + extra, d, now)
    for x in re.split(r"(?<=\.)\s+(?=[A-Z])", str(r.get("note") or "") if isinstance(r, dict) else ""):
        o.line(x)            # the run's note, one sentence a line: what it picked, sold and learned
    n = apply_out(d)
    log("saved %d docs" % n)
    if isinstance(r, dict) and isinstance(r.get("weights"), dict):      # the next scan's spotter scores with these (it never trains itself)
        try:
            sys.path.insert(0, HERE)
            import memebot as M
            with open(os.path.join(d, "db", "memebot", "spotter.json"), "w", encoding="utf-8") as f:
                json.dump({"t": now, "rule": (M.PROFILES.get(horizon) or {}).get("RULE") or M.RULE, "horizon": horizon, "w": r["weights"]}, f, separators=(",", ":"))
        except Exception as e:
            log("spotter weights not saved: %s" % e)
    if os.path.exists(os.path.join(d, "young_early.json")):     # the early list's record: its coins priced again, their fate on the scored list
        run(["radar.py", "check", "--t0", str(t0), "--horizon", horizon] + (["--mock", mock] if mock else []), d, now, soft=True, limit=CHECK_LIMIT_S)
    prune(d, now)
    # a scored snapshot's raw copy is not needed anymore (the result doc carries everything the learning reads)
    try:
        for w in json.load(open(os.path.join(d, "out", "manifest.json"), encoding="utf-8")):
            if w["collection"] == "memesnapres":
                raw = os.path.join(d, "db", "memesnap", w["doc_id"] + ".json")
                if os.path.exists(raw):
                    os.remove(raw)
    except (OSError, ValueError):
        pass
    o.done("trader", lambda: trader_said(r))
    if recommend and mode["pick"]:
        # the iPhone app: this scan's pick rides in the live record and goes out as a push notification (app.py; nothing without its secrets)
        try:
            rec = json.load(open(os.path.join(d, "db", "memebot", "recommend.json"), encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        brief = pick_brief(rec, now)
        if brief:
            live_put("pick", brief)
            app_bg("notify_pick", rec)
    o.begin("reporter")
    o.save()                 # the page shows its own builder at work; the copy saved after it is the complete one that syncs
    try:
        import report as R
        log("report: %s" % os.path.basename(R.build(d, now=now, horizon=horizon)))
        o.done("reporter", "this page")
    except Exception as e:   # the page must never break a cycle
        log("report failed: %s" % e)
        o.done("reporter", "no page this run", "failed")
    o.save()
    print(r["note"])
    for p in r["picks"]:
        if p["grp"] == "skipped":
            print("  SKIPPED  " + p["why"]); continue
        held = p["grp"] == "young" and not (isinstance(p.get("bought"), (int, float)) and not isinstance(p.get("bought"), bool))   # a new launch already held
        print("  %s %-10s %-6s score %5.1f  %s" % ("RECOMMEND" if p["grp"] == "recommend" else ("HELD" if held else "BUY "), p["sym"], p["grp"], p["score"], p.get("addr")))
        if p.get("why"):
            print("       " + p["why"])
    for e in r["exits"]:
        print("  SELL %-10s %-6s %-14s %.0f%% at %.2fx -> %.2f back" % (e["sym"], e["grp"], e["why"], 100 * e["frac"], e["mult"], e["eur"]))
    if r["top5"]:
        print("  top 5 gated: " + ", ".join("%s %.0f" % (t["sym"], t["score"]) for t in r["top5"]))
    if push:
        try:
            sync(d, remote, branch)
        except SystemExit as e:   # a failed push must not stop the loop
            log("sync failed: %s" % e)
    return r


def spot_done(o, job, now):
    """The launch spotter's result phrase for the Agent office, when its process exits (called by its waiter thread). A spotter that ended
    by itself without a list of this cycle (none written, or one early_doc refuses) leaves a "failed" list for both live views, so the
    early box says it instead of waiting for the rest of the scan."""
    try:
        with open(job["out"].name, encoding="utf-8", errors="replace") as f:
            j = json.loads(f.read() or "null")
    except (OSError, ValueError):
        j = None
    rc = job["p"].returncode
    if job.get("killed"):          # stopped by the cycle (stop_bg): that is the phrase, whatever it printed
        o.done("spotter", job["killed"], "failed", end=job.get("end"))
        return
    j = j if isinstance(j, dict) else {}
    try:                           # it ended without a list of this cycle (it crashed at its start): the early box says so, not "waiting"
        path = os.path.join(o.d or "", "young_early.json")
        with EARLY_LOCK:
            empty = EARLY["doc"] is None
        if empty and (not os.path.exists(path) or early_doc(path, now) is None):
            early_set(now, {"v": 1, "t": now, "state": "failed", "coins": [],
                            "why": "the launch spotter stopped without a list (%s)" % (str(j.get("why") or "")[:60] or "exit %s" % rc)})
    except Exception:
        pass
    st, mins = j.get("state"), ((j["at"] - now) / 60000.0) if isinstance(j.get("at"), (int, float)) else None
    calls = "%d DexScreener call%s" % (j.get("requests") or 0, "" if j.get("requests") == 1 else "s")
    if st == "listed":
        said = "%d new launch%s at minute %.1f · RugCheck reports for %d of %d · %s" % (j.get("n") or 0, "" if j.get("n") == 1 else "es", mins or 0, j.get("rcGot") or 0, j.get("shown") or 0, calls) + (
            " · %s" % (str(j.get("why") or "") or "DexScreener stopped early")[:60] if j.get("partial") else "")
    elif st == "empty":
        said = "no coin under an hour old with the minimum liquidity at minute %.1f · %s" % (mins or 0, calls)
    elif st == "small":
        said = "too few DexScreener pairs for a list · %s" % calls
    else:
        said = "no early list: %s" % (j.get("why") or "exit %s" % rc)
    o.done("spotter", said, "done" if rc == 0 else "failed", end=job.get("end"))


def trader_said(r):
    """The paper trader's result phrase for the Agent office: what it named or bought, and what it sold."""
    recs = [str(p.get("sym")) for p in r["picks"] if p.get("grp") == "recommend"]
    buys = [p for p in r["picks"] if p.get("grp") not in ("recommend", "skipped", "young")
            or (isinstance(p.get("bought"), (int, float)) and not isinstance(p.get("bought"), bool))]
    said = (["recommended " + ", ".join(recs)] if recs else []) + (["%d bought" % len(buys)] if buys else []) + (["%d sold" % len(r["exits"])] if r["exits"] else [])
    return " · ".join(said) or "no pick, nothing sold"


SYNC_IGNORE = """# written by bot.py sync: only the page and the small docs travel; the big snapshots stay local
*
!.gitignore
!report.html
!db/
!db/memepos/
!db/memepos/**
!db/memeexit/
!db/memeexit/**
!db/memecurve/
!db/memecurve/**
!db/memeruns/
!db/memeruns/**
!db/memeweights/
!db/memeweights/**
!db/memebot/
!db/memebot/**
!db/memerec/
!db/memerec/**
!db/memeyoung/
!db/memeyoung/**
!db/memeearly/
!db/memeearly/**
!db/memepeak/
!db/memepeak/**
!db/memeradar/
!db/memeradar/**
!db/memeradarpaper/
!db/memeradarpaper/**
!db/memepath/
!db/memepath/**
!db/memetrader/
!db/memetrader/**
!db/memeshadow/
!db/memeshadow/**
"""


def sync(d, remote=None, branch="results"):
    """mb/ keeps its own small git repository (the bot's code repo ignores mb/). Each sync commits report.html and the small
    docs and pushes them to <remote> on <branch>; the default remote is this code repository's origin."""
    mb = os.path.abspath(d)
    os.makedirs(mb, exist_ok=True)
    env = child_env(GIT_TERMINAL_PROMPT="0")

    def git(*a, check=False):
        p = subprocess.run(["git", "-C", mb] + list(a), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if check and p.returncode != 0:
            raise SystemExit(redact("git %s failed: %s" % (a[0], (p.stderr or p.stdout).strip()[-800:])))
        return p

    if not os.path.isdir(os.path.join(mb, ".git")):
        git("init", "-q", check=True)
        git("symbolic-ref", "HEAD", "refs/heads/" + branch, check=True)
    if not remote:
        remote = origin_url()
        if not remote:
            raise SystemExit("no --remote given and this folder has no git origin to reuse")
    if git("remote", "get-url", "origin").returncode != 0:
        git("remote", "add", "origin", remote, check=True)
    else:
        git("remote", "set-url", "origin", remote, check=True)
    with open(os.path.join(mb, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(SYNC_IGNORE)
    git("add", "-A", check=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c = git("-c", "user.name=memebot", "-c", "user.email=memebot@localhost", "commit", "-q", "-m", "results " + stamp)
    changed = c.returncode == 0
    p = git("push", "-q", "-u", "origin", "HEAD:" + branch)
    if p.returncode != 0:
        # another machine pushed to the same branch: take the remote history and put this state on top of it
        git("fetch", "-q", "origin", branch)
        if git("merge-base", "HEAD", "FETCH_HEAD").returncode != 0 and git("rev-parse", "-q", "--verify", "HEAD~0").returncode == 0 \
                and git("rev-list", "--count", "FETCH_HEAD").stdout.strip() not in ("", "0"):
            # this state never came from the remote branch (a start without its history): putting it on top would replace what is there
            raise RuntimeError("sync refused: the local state does not come from %s's history (a fresh start beside an existing branch)" % branch)
        git("-c", "user.name=memebot", "-c", "user.email=memebot@localhost", "merge", "-q", "-s", "ours", "--allow-unrelated-histories", "-m", "merge results", "FETCH_HEAD")
        git("push", "-q", "-u", "origin", "HEAD:" + branch, check=True)
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    log("sync: %s -> %s %s (%s)" % ("new commit" if changed else "nothing new", redact(remote), branch, head))
    return head


def sell(d, which, now=None):
    """Close open positions by hand at their last known price (fake money): --all or a coin symbol. The money returns to the
    bankroll, so the next pick run can buy again."""
    sys.path.insert(0, HERE)
    import memebot as M
    now = int(now or time.time() * 1000)
    pos = M.positions(d)
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    done = []
    for pid, p in sorted(pos.items()):
        if p["_left"] <= 1e-9:
            continue
        if which != "all" and str(p.get("sym", "")).lower() != which.lower():
            continue
        entry = M.num(p.get("px"))
        last = M.num((marks.get("px") or {}).get(pid))
        if not last or not entry:
            log("%s: no price known yet, run a cycle first" % p.get("sym"))
            continue
        cash = M.pos_value(p, p["_left"], last / entry)        # the position's own fees: paper fees for the paper account
        doc = {"pos": pid, "t": now, "px": last, "frac": round(p["_left"], 6), "why": "manual", "eur": round(cash, 2), "grp": p.get("grp"), "rule": M.RULE}
        os.makedirs(os.path.join(d, "db", "memeexit"), exist_ok=True)
        with open(os.path.join(d, "db", "memeexit", "%s-%d.json" % (pid, len(p["_exits"]) + 1)), "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        done.append((p.get("sym"), last / entry, cash))
        print("  SOLD %-10s %.0f%% at %.2fx -> %.2f back" % (p.get("sym"), 100 * p["_left"], last / entry, cash))
    if not done:
        print("nothing sold" + ("" if which == "all" else " (no open position called %s)" % which))
    try:
        import report as R
        R.build(d)
    except Exception as e:
        log("report failed: %s" % e)
    return done


def summary(d):
    """Markdown with the last recommendations (and open positions): what GitHub Actions shows on a run's page."""
    sys.path.insert(0, HERE)
    import memebot as M
    import report as R
    rec = M.load_json(os.path.join(d, "db", "memebot", "recommend.json"), {}) or {}
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    out = []
    stamp = lambda t: dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if t else "?"
    t_rec, t_run = M.num(rec.get("t")), M.num(state.get("lastRun"))
    profile = state.get("horizon") or ("2h" if "2h" in str(state.get("rule") or "") else "24h")
    out.append("## Meme-Bot %s (%s profile, fake money)" % (stamp(t_run or t_rec), profile))
    if state.get("note"):
        out.append("Last run: " + md(state["note"]))
        out.append("")
    if rec.get("picks"):
        if t_rec and t_run and t_run - t_rec > 60_000:
            out.append("The picks below are from the earlier run at %s; this run found nothing new." % stamp(t_rec))
        out.append("Scanned %s coins, %s passed the gates.%s%s" % (rec.get("scanned", "?"), rec.get("passed", "?"), " Candidates ranked by trained odds." if rec.get("pickBy") == "odds" else "",
                                                             (" Prices of the candidates refreshed at %s, right before the pick." % stamp(M.num(rec["pricedAt"]))) if M.num(rec.get("pricedAt")) else ""))
        for p in rec["picks"]:
            links = " · ".join("[%s](%s)" % (n, u) for n, u in R.coin_links(p.get("addr"), p.get("pair"), p.get("x")) if u.startswith("https://") and ")" not in u and " " not in u)
            tier = {"weak": " · weak, best available", "fallback": " · fallback, momentum rules relaxed", "risky": " · risky, nothing clean this scan", "watch": " · watch only, not a pick: the odds say a loss"}.get(p.get("tier"), "")
            out.append("### %d. %s (%s) — score %.0f%s" % (M.num(p.get("rank")) or 0, md(p.get("sym")), md(p.get("name")), M.num(p.get("score")) or 0, tier))
            if p.get("tier") == "risky":
                out.append("- no coin had a clean safety report this scan: this is the tradable coin with the best trained odds, not a clean pick" + ("; it also failed: " + md("; ".join(str(x) for x in p["relaxed"])) if p.get("relaxed") else ""))
            elif p.get("relaxed"):
                out.append("- named only because nothing cleaner passed every gate; it failed: " + md("; ".join(str(x) for x in p["relaxed"])))
            odds = [("%d%% chance of a profit" % round(100 * M.num(p["upP"]))) if M.num(p.get("upP")) is not None else "", ("%d%% chance of going to zero" % round(100 * M.num(p["zeroP"]))) if M.num(p.get("zeroP")) is not None else ""]
            if any(odds):
                out.append("- trained odds: " + ", ".join(x for x in odds if x) + (" (low odds: named because the page always names the best, not because the record likes it)" if p.get("lowOdds") else ""))
            out.append("- market cap $%s, liquidity $%s, 24h volume $%s" % tuple(fmt_money(M.num(p.get(k))) for k in ("mc", "liq", "vol")))
            if p.get("why"):
                out.append("- " + md(p["why"]))
            if p.get("safety"):
                out.append("- " + md(p["safety"]))
            out.append("- " + links)
        if rec.get("runnersUp"):
            out.append("")
            out.append("Runners-up: " + ", ".join("%s (%.0f)" % (md(r.get("sym")), M.num(r.get("score")) or 0) for r in rec["runnersUp"]))
        if rec.get("young"):
            out.append("")
            out.append("New launches under an hour old (shown on their own tab, never picked): " + ", ".join(
                "%s (%d min, score %.0f%s)" % (md(y.get("sym")), M.num(y.get("ageMin")) or 0, M.num(y.get("score")) or 0, (", %d%% profit chance" % round(100 * M.num(y["upP"]))) if M.num(y.get("upP")) is not None else "")
                for y in rec["young"][:6]))
    else:
        out.append("No recommendation" + (" this time: %s." % md(rec["reason"]) if rec.get("reason") else " yet."))
        if rec.get("scanned"):
            out.append("Scanned %s coins, %s passed the gates." % (rec.get("scanned", "?"), rec.get("passed", "?")))
        near = [r for r in (rec.get("runnersUp") or []) if isinstance(r, dict)]
        if near:
            out.append("")
            out.append("Closest, and why not: " + "; ".join("%s (%.0f) %s" % (md(r.get("sym")), M.num(r.get("score")) or 0, md(r.get("safety") or "")) for r in near[:5]))
    rule_now = str(state.get("rule") or M.RULE)      # the page counts the active profile's tips only; so does this
    docs = [doc for doc in M.load_docs(d, "memerec").values() if isinstance(doc, dict) and str(doc.get("rule") or M.RULE) == rule_now]
    lines = []
    for h in M.TIP_CHECKS:
        outs = [o for doc in docs for o in M.settled((doc.get("outs") or {}).get(str(int(h))), h)]
        if outs:
            up = sum(1 for o in outs if (M.num(o.get("eur")) or 0) > 0)
            lines.append("%d h later: %d tips priced again, %d went up, average %+.2f per 20" % (h, len(outs), up, sum(M.num(o.get("eur")) or 0 for o in outs) / len(outs)))
    if lines:
        out.append("")
        out.append("Track record (fake money, 20 per tip): " + "; ".join(lines) + ".")
        one = [o for doc in docs for o in M.settled((doc.get("outs") or {}).get("1"), 1.0) if M.num(o.get("eur")) is not None]
        if one:
            tot = sum(M.num(o["eur"]) for o in one)
            out.append("Is the bot making money? %s: %+.2f together on %d tips sold 1 h later (%.0f staked, fake money, after fees)." % ("Yes, so far" if tot > 0 else "No, not so far", tot, len(one), len(one) * M.TICKET))
        chain = R.compound_chain(docs)
        if chain["n"]:
            out.append("20 put into every tip one after the other (sold after 1 h, after fees) would be %.2f now after %d tips." % (chain["equity"], chain["n"]))
    train = M.load_json(os.path.join(d, "db", "memebot", "train.json"), {}) or {}
    if isinstance(train, dict) and train.get("note"):
        out.append("")
        out.append("Training: " + md(train["note"]) + (" (trained %s)" % stamp(train["t"]) if isinstance(train.get("t"), (int, float)) else ""))
        for why in train.get("tunedWhy") or []:
            out.append("- " + md(why))
    pos = [(pid, p) for pid, p in M.positions(d).items() if p["_left"] > 1e-9]
    if pos:
        marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
        out.append("### Open positions")
        for pid, p in sorted(pos, key=lambda kv: kv[1].get("t") or 0):
            last, entry = M.num((marks.get("px") or {}).get(pid)), M.num(p.get("px"))
            out.append("- %s: in %.0f, now %s" % (md(p.get("sym")), M.num(p.get("ticket")) or M.TICKET, ("%.2fx" % (last / entry)) if last and entry else "no price yet"))
    text = "\n".join(out) + "\n"
    print(text)
    return text


def md(v):
    """Coin names and notes as plain Markdown text: no line breaks, no link or emphasis syntax."""
    return re.sub(r"[\[\]*_`#<>|]", "", re.sub(r"\s+", " ", str(v if v is not None else ""))).strip()


def fmt_money(v):
    if v is None:
        return "?"
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(v) >= div:
            return "%.1f%s" % (v / div, unit)
    return "%.0f" % v


SITE_NOTICE = ('<div class="live"><span><strong>Live</strong> · rebuilt after every scan, every hour</span>'
               '<a class="btn" href="%s" target="_blank" rel="noopener">Scan now</a>'
               '<small>The page reloads itself. Scan now opens GitHub: tap “Run workflow” there and come back in about ten minutes.</small></div>')
SITE_TAGS = ('<meta name="theme-color" content="#070a14">\n<link rel="manifest" href="manifest.webmanifest">\n'
             '<link rel="icon" href="icon.svg" type="image/svg+xml">\n<link rel="apple-touch-icon" sizes="180x180" href="icon-180.png">\n'
             '<meta name="apple-mobile-web-app-capable" content="yes">\n<meta name="apple-mobile-web-app-title" content="Meme-Bot">\n'
             '<meta name="apple-mobile-web-app-status-bar-style" content="default">\n')
# the page reloads itself every 15 minutes in a browser tab (as the meta refresh did before) but not in the installed app, where a
# reload would cut the tab and the scroll position and can interrupt the notifications prompt: the app shows the scan live instead,
# and the live script reloads it once a newer report is out; both reload when the page comes back after 5 minutes away
SITE_SCRIPT = ('<script>(function(){var t=Date.now(),app=navigator.standalone===true||!!(window.matchMedia&&matchMedia('
               '"(display-mode: standalone), (display-mode: fullscreen), (display-mode: minimal-ui)").matches);'
               'function go(){window.MEMEBOT_RELOADING=Date.now();location.reload();}'   # the flag (when): the radar's poll stops (page_radar.py)
               'if(!app)setTimeout(go,900000);document.addEventListener("visibilitychange",function(){'
               'if(!document.hidden&&Date.now()-t>300000)go();});})();</script>')
SITE_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#2a78d6"/>'
             '<rect x="20" y="55" width="14" height="25" rx="3" fill="#fff"/><rect x="43" y="40" width="14" height="40" rx="3" fill="#fff"/>'
             '<rect x="66" y="25" width="14" height="55" rx="3" fill="#fff"/></svg>')


def site_store():
    """(url, publishable key) of the app's live store for the page, from SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY, or None. Only a
    publishable key (sb_publishable_...) goes into the page; a secret key or a JWT is refused and the log says why, never the key."""
    raw, key = (os.environ.get("SUPABASE_URL") or "").strip(), (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not raw and not key:
        return None
    sys.path.insert(0, HERE)
    import app as A
    if not raw or not key:
        log("site: the app's live store stays off: SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are both needed (%s is missing)" % ("SUPABASE_URL" if not raw else "SUPABASE_PUBLISHABLE_KEY"))
        return None
    verdict, why = A.page_key_verdict(key)
    if verdict != "ok":
        log("site: SUPABASE_PUBLISHABLE_KEY is NOT put in the page: %s" % why)
        return None
    url, problem = A.store_url(raw)
    if url is None or not url.startswith("https://"):
        log("site: the app's live store stays off: SUPABASE_URL is not an address like https://<ref>.supabase.co (%s)" % (problem or "plain http"))
        return None
    if problem:
        log("site: SUPABASE_URL read with a fix (%s): better put the project's address https://<ref>.supabase.co in the repository setting" % problem)
    return url, key


def site(d, out="site", repo=None):
    """A folder for a static web host (GitHub Pages): the page as index.html with the tags that let a phone put it on the home
    screen like an app, an auto-refresh, a "Scan now" link to the Actions page, a web-app manifest, icons and sw.js (the installed
    app's service worker: notifications). With SUPABASE_URL and a publishable SUPABASE_PUBLISHABLE_KEY the page also reads the app's
    live store (data-sb-url and data-sb-key on <html>); in the installed app PAGE_JS (app.py) adds the bottom tab bar and notifications."""
    sys.path.insert(0, HERE)
    import app as A
    page = os.path.join(d, "report.html")
    if not os.path.exists(page):
        import report as R
        R.build(d)
    h = open(page, encoding="utf-8").read()
    repo = re.sub(r"^(https?://)[^/@]*@", r"\1", (repo or origin_url()).strip())   # no credentials in the link
    repo = repo[:-4] if repo.endswith(".git") else repo
    st = site_store()
    if st:
        import html as H
        h = h.replace('<html lang="en">', '<html lang="en" data-sb-url="%s" data-sb-key="%s">' % (H.escape(st[0], True), H.escape(st[1], True)), 1)
    elif (os.environ.get("SUPABASE_URL") or "").strip() and not str(A.store_url(os.environ["SUPABASE_URL"])[0] or "").startswith("https://"):
        h = h.replace('<html lang="en">', '<html lang="en" data-sb-why="url">', 1)      # the Account card says the address has the wrong form
    h = h.replace("</title>", "</title>\n" + SITE_TAGS, 1)
    h = h.replace("</head>", "<style>%s</style>\n</head>" % A.PAGE_CSS, 1)
    if repo:
        h = h.replace('<div class="wrap">', '<div class="wrap">' + SITE_NOTICE % (repo + "/actions/workflows/scan.yml"), 1)
    h = h.replace("</body>", SITE_SCRIPT + "<script>%s</script>" % A.PAGE_JS + "</body>", 1)
    m = re.match(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/?$", repo or "")
    scope = "/" if m and m.group(2).lower() == m.group(1).lower() + ".github.io" else "/%s/" % (m.group(2) if m else "Meme-Bot")
    os.makedirs(out, exist_ok=True)
    files = {"index.html": h, "icon.svg": SITE_ICON, ".nojekyll": "", "sw.js": A.SW_JS,
             "manifest.webmanifest": json.dumps({"id": scope, "name": "Meme-Bot Ledger", "short_name": "Meme-Bot", "start_url": "./", "scope": "./",
                                                 "display": "standalone", "background_color": "#070a14", "theme_color": "#070a14",
                                                 "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                                                           {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                                                           {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}]})}
    for name, text in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)
    for n in (180, 192, 512):
        with open(os.path.join(out, "icon-%d.png" % n), "wb") as f:
            f.write(icon_png(n, opaque=n == 180))      # the apple-touch-icon: a full square (iOS paints see-through corners black and rounds it itself)
    log("site: %s (%d files, scan link %s, app live store %s)" % (out, len(files) + 3, "yes" if repo else "none: no git origin and no --repo", "on" if st else "off"))
    return out


def icon_png(n, opaque=False):
    """The icon as a PNG without any image library: a blue rounded square with three white bars, n x n pixels (opaque: a full square)."""
    import struct, zlib
    bg, fg = (42, 120, 214), (255, 255, 255)
    bars = [(0.20, 0.55, 0.34, 0.80), (0.43, 0.40, 0.57, 0.80), (0.66, 0.25, 0.80, 0.80)]   # x0, y0, x1, y1 as fractions of n
    r = 0.22 * n
    rows = []
    for y in range(n):
        row = bytearray([0])   # PNG filter byte: none
        for x in range(n):
            cx = min(max(x + 0.5, r), n - r); cy = min(max(y + 0.5, r), n - r)
            if not opaque and (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 > r * r:   # outside the rounded corners: transparent
                row += b"\0\0\0\0"; continue
            px = bg
            for x0, y0, x1, y1 in bars:
                if x0 * n <= x < x1 * n and y0 * n <= y < y1 * n:
                    px = fg; break
            row += bytes(px) + b"\xff"
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def self_update():
    """git pull in the code folder; True when the code changed (the loop then restarts itself with the new code)."""
    git = lambda *x: subprocess.run(["git", "-C", HERE] + list(x), capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    env=child_env(GIT_TERMINAL_PROMPT="0"))
    before = git("rev-parse", "HEAD").stdout.strip()
    if not before:
        return False
    p = git("pull", "--ff-only", "-q")
    if p.returncode != 0:
        log("self-update skipped: %s" % (p.stderr.strip().splitlines() or ["?"])[-1][:120])
        return False
    after = git("rev-parse", "HEAD").stdout.strip()
    return bool(after) and after != before


def status(d):
    sys.path.insert(0, HERE)
    import memebot as M
    pos = M.positions(d)
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    cash = M.bankroll(pos)
    print("bankroll: %.2f free of %.0f  (spent %.2f, came back %.2f, %d open)" % (cash["free"], cash["budget"], cash["spent"], cash["back"], cash["open"]))
    if state.get("paperRule"):
        a = M.paper_account(pos, M.num(state.get("paperSince")), marks.get("px") or {})
        print("paper account since the restart (%s): invested %.2f, came back %.2f, open %.2f, %+.2f  (%d open: %d top pick, %d new launch%s; %d closed: %d won, %d lost)" % (
            state["paperRule"], a["invested"], a["back"], a["open"], a["pnl"], a["nOpen"], a["nTop"], a["nYoung"], "" if a["nYoung"] == 1 else "es", a["nClosed"], a["won"], a["lost"]))
    equity = cash["free"]
    for pid, p in sorted(pos.items(), key=lambda kv: kv[1].get("t") or 0):
        ticket, entry = M.num(p.get("ticket")) or M.TICKET, M.num(p.get("px"))
        back = sum(M.num(e.get("eur")) or 0 for e in p["_exits"])
        last = M.num((marks.get("px") or {}).get(pid))
        when = dt.datetime.fromtimestamp((M.num(p.get("t")) or 0) / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
        if p["_left"] > 1e-9:
            val = None
            if last and entry:
                val = M.pos_value(p, p["_left"], last / entry)
                if p.get("grp") in M.BANK_GROUPS:
                    equity += val
            print("  OPEN   %s %-10s %-5s in %.0f  now %s  %s%s" % (when, p.get("sym"), p.get("grp"), ticket,
                                                                     ("%.2fx" % (last / entry)) if last and entry else "?",
                                                                     ("worth %.2f" % val) if val is not None else "no price yet",
                                                                     (" (+%.2f already sold)" % back) if back else ""))
        else:
            print("  CLOSED %s %-10s %-5s in %.0f  out %.2f  %+.2f  (%s)" % (when, p.get("sym"), p.get("grp"), ticket, back, back - ticket,
                                                                            ", ".join(e.get("why", "?") for e in p["_exits"])))
    print("equity if everything were sold now: %.2f (%+.2f)" % (equity, equity - cash["budget"]))
    if state.get("note"):
        print("last run: " + state["note"])


def main():
    for stream in (sys.stdout, sys.stderr):      # coin names carry emoji; a redirected Windows console would otherwise crash
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cycle", "loop", "status", "reset", "report", "sync", "sell", "summary", "site"])
    ap.add_argument("--all", action="store_true", help="sell: close every open position")
    ap.add_argument("--coin", default="", help="sell: the symbol of the one position to close")
    ap.add_argument("--push", action="store_true", help="after each cycle, push report.html and the small docs to the results branch")
    ap.add_argument("--rescan", action="store_true", help="cycle: scan the whole universe now and save it for the big test, even if the last full scan is recent")
    ap.add_argument("--recommend", action="store_true", help="cycle/loop: never buy; write the two best clean coins of each full scan to the page")
    ap.add_argument("--horizon", default=os.environ.get("MEMEBOT_HORIZON", "24h"), choices=["24h", "2h"], help="rule profile: 24h (survive a day) or 2h (pump in the next two hours)")
    ap.add_argument("--no-update", action="store_true", help="loop: do not git pull and restart when new code is pushed")
    ap.add_argument("--remote", default=None, help="git URL for sync/--push (default: this repository's origin)")
    ap.add_argument("--branch", default="results", help="branch for sync/--push")
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--out", default="site", help="site: folder to write the website into")
    ap.add_argument("--repo", default=None, help="site: the GitHub repository URL for the Scan-now link (default: this folder's origin)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--every", type=float, default=30.0, help="minutes between cycles in loop mode")
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    ap.add_argument("--now", type=float, default=None, help="fake clock in ms (tests)")
    a = ap.parse_args()
    if a.cmd == "status":
        status(a.dir)
        print("page: %s" % os.path.abspath(os.path.join(a.dir, "report.html")))
    elif a.cmd == "report":
        import report as R
        print(R.build(a.dir, now=a.now))
    elif a.cmd == "reset":
        shutil.rmtree(os.path.join(a.dir, "db"), ignore_errors=True)
        shutil.rmtree(os.path.join(a.dir, "out"), ignore_errors=True)
        print("db/ wiped: fresh bankroll")
    elif a.cmd == "sync":
        print(sync(a.dir, a.remote, a.branch))
    elif a.cmd == "summary":
        summary(a.dir)
    elif a.cmd == "site":
        site(a.dir, a.out, a.repo)
    elif a.cmd == "sell":
        if not a.all and not a.coin:
            raise SystemExit("say what to sell: --all or --coin SYMBOL")
        sell(a.dir, "all" if a.all else a.coin, a.now)
        if a.push:
            sync(a.dir, a.remote, a.branch)
    elif a.cmd == "cycle":
        cycle(a.dir, a.force, a.offline, a.mock, a.now, a.push, a.remote, a.branch, a.rescan, a.recommend, a.horizon)
    else:
        while True:
            if not a.no_update and self_update():
                log("new code pulled, restarting the loop")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            try:
                cycle(a.dir, a.force, a.offline, a.mock, push=a.push, remote=a.remote, branch=a.branch, recommend=a.recommend, horizon=a.horizon)
            except SystemExit as e:
                log("cycle failed: %s" % e)
            log("next cycle in %.0f minutes" % a.every)
            time.sleep(a.every * 60)


if __name__ == "__main__":
    main()
