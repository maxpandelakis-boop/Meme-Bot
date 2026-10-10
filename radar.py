#!/usr/bin/env python3
"""radar.py: the launch spotter. Fake money only: it lists coins for the page, it never buys anything, and the paper trader never
reads what it writes.

About four minutes into each hourly scan, right after the sources step, bot.py starts `radar.py early` in the background, next to the
price desk. It lists the coins under an hour old that the scan's sources found, for the New launches tab, about 20 minutes before the
scored list is out:

  a. sandbox   the sources' files are copied into <dir>/radar/in (no network). The spotter never writes pairs/, risk/, pairs.json,
               universe.json or any db doc the trader reads, so the trader's results are byte for byte the same with it on or off.
  b. pick      the addresses the keyword searches have no full pair for: the previous early list first (for its price about an hour
               later), then pump.fun's graduated coins, GeckoTerminal, pump.fun's new and live coins, Jupiter's 1-hour lists, the
               DexScreener, RugCheck and LaunchLab lists and pump.fun's biggest (about 940, at most EARLY_MAX_ADDRS).
  c. fetch     DexScreener tokens/v1, 30 addresses a request, EARLY_DS_PAUSE apart. The desk shares the runner's address but not its
               rate-limit counter, so the first 429 stops the spotter's DexScreener calls at once (no wait). No Jupiter fallback.
  d. build     memebot's own gather, scan and new-launches filter (young_rows) on the sandbox, ages at the spotter's clock
               -> young_early.json, RugCheck still pending. bot.py's live view pushes it within seconds.
  e. RugCheck  reports for the listed coins (EARLY_RC_S at most) -> the list again, re-ranked, with RugCheck's words.
  f. prev      the previous early list's prices now -> radar/prev.json for the record. The previous list is the record 45 to 90
               minutes old that is closest to an hour, so a scan that runs half an hour after another never fills the hour price.
               A coin counts as gone only when DexScreener answered the request that asked about it and had no pair for it.

`radar.py check` runs after the trader: one DexScreener request (one try) prices the early list again (about minute 24) and the
record db/memeearly/<run id>.json says which coins made the scored list and were paper-bought, and why the others did not.

Writes only <dir>/radar/, <dir>/young_early.json and <dir>/db/memeearly/. Budget per scan: about 31 DexScreener requests (at most 45:
the previous list's coins count inside EARLY_MAX_ADDRS), at most 20 RugCheck reports (40 with the summary fallback), and 1 DexScreener
request for the check.

Usage:
  python3 radar.py early --dir mb --now <cycle now ms> --t0 <cycle start ms> --horizon 2h [--mock URL]
  python3 radar.py check --dir mb --now <cycle now ms> --t0 <cycle start ms> --horizon 2h [--mock URL]
Each prints one JSON object on stdout; its progress lines go to stderr (bot.py files them under the agent "spotter").
"""
import argparse, contextlib, datetime as dt, glob, io, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import fetch as F

EARLY_MAX = 20            # coins in the file (the scored tab shows 12; median 9 qualify per scan)
EARLY_MAX_ADDRS = 1350    # DexScreener addresses at most (45 requests)
EARLY_DS_PAUSE = 0.6      # s between DexScreener requests (the desk runs beside it on the same address)
EARLY_TIMEOUT = 10        # s per request (fetch.TIMEOUT is 25)
EARLY_RC_S = float(os.environ.get("MEMEBOT_EARLY_RC_S") or 45)   # s for all RugCheck reports (the selftest shortens it)
EARLY_DEADLINE_S = 180    # the whole step; DexScreener stops early enough to leave the RugCheck time inside it
EARLY_PREV_MIN_AGE = 45   # min: the previous early list is priced again (its p60) when it is at least this old,
EARLY_PREV_MAX_AGE = 90   # and at most this old; of several, the one closest to an hour
KEEP_EARLY_DAYS = 30      # db/memeearly docs are pruned after this (bot.py prune)
DS_HOST, RC_HOST = "api.dexscreener.com", "api.rugcheck.xyz"
SKIP_DIRS = ("pairs", "risk", "candles")      # pairs: only the keyword searches are copied; risk: the spotter fetches its own reports
SKIP_FILES = ("fresh.json",)
LIST_KEYS = ("profiles", "boostLatest", "boostTop", "ads", "cto", "rcNew", "llNew", "llHot")
RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}$")
H = 3_600_000


def say(s):
    print("spotter: " + s, file=sys.stderr, flush=True)


def ms():
    return int(time.time() * 1000)


def run_id(t):
    """The run's id, as memeyoung and memerec name it: UTC %Y-%m-%dT%H%M of the cycle's now."""
    return dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")


class SpotHttp(F.Http):
    """fetch's pacing, counters and circuit breaker with the spotter's own request rules (fetch's get stays as the scan uses it):
      - at most `tries` tries a request (2 in the early step, 1 in check); only a request that got no answer at all is tried again;
      - a 429 on any try gives the host up for the run at once, with no wait (the desk shares the address, not this counter);
      - the pause after every answer, a 5xx or a 404 too, so a host that answers with errors is not asked 45 times in a second;
      - no request outlasts the step's deadline (until, epoch s): each try's timeout is what is left of it, and none starts after it.
    ok: the last request got a JSON answer. heard: the URLs that got a real answer (JSON, or a 404: RugCheck's "no report"; a 401, 403,
    410, 451, 429 or 5xx says nothing about the coin). tried: the URLs asked at all."""

    def __init__(self, mock=None, pause=EARLY_DS_PAUSE, tries=2):
        F.Http.__init__(self, mock, pause)
        self.tries, self.until, self.ok, self.late = tries, None, None, False
        self.heard, self.tried = set(), set()

    def get(self, u, kind="json", headers=None, tries=4):
        self.ok = False
        host = urllib.parse.urlsplit(u).netloc
        hdr = {"User-Agent": F.UA, "Accept": "application/json, text/xml, */*"}
        hdr.update(headers or {})
        n = max(1, min(tries, self.tries))
        for i in range(n):
            if host in self.dead:
                return None
            left = (self.until - time.time()) if self.until else EARLY_TIMEOUT
            if left < 0.5:
                self.late = True
                return None
            self._pace(host)
            self.tried.add(u)
            try:
                with urllib.request.urlopen(urllib.request.Request(self.url(u), headers=hdr), timeout=min(EARLY_TIMEOUT, left)) as r:
                    raw, status = r.read(), getattr(r, "status", "?")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    self.log("  ! 429 rate limited by %s" % host)     # no "waiting": the spotter never waits (the office counts this line)
                    self._limited(host)
                    with self.lock:
                        self.dead.add(host)
                    return None
                self.log("  ! %s %s" % (e.code, u[:110]))
                if e.code == 404:            # a real answer: RugCheck has no report; a 401, 403, 410, 451 or 5xx is no answer about the coin
                    self.heard.add(u)
                if e.code in (401, 403, 404, 410, 451):
                    self._fail(host, hard=e.code != 404)
                time.sleep(self.pause)
                return None
            except Exception as e:       # no answer: a timeout, a refused or reset connection
                self.log("  ! %s %s" % (str(e)[:60], u[:110]))
                if i + 1 < n and (not self.until or self.until - time.time() > 1.5):     # tried again only with time left for it
                    time.sleep(1.0)
                    continue
                self._fail(host, hard=True)
                if host not in self.dead:
                    time.sleep(self.pause)
                return None
            with self.lock:
                self.fails[host] = 0
            time.sleep(self.pause)
            text = raw.decode("utf-8", "replace")
            if kind != "json":
                self.ok = True
                self.heard.add(u)
                return text
            try:
                out = json.loads(text)
            except ValueError:
                with self.lock:
                    self.nonjson[host] = k = self.nonjson.get(host, 0) + 1
                if k <= 2:
                    self.log("  ! %s answered with something that is not JSON (HTTP %s): %r" % (host, status, raw[:100].decode("utf-8", "replace")))
                return None
            self.ok = True
            self.heard.add(u)
            return out
        return None


def setup(horizon, mock, tries=2):
    """The profile's rules (as memebot's main sets them) and this process's own client (SpotHttp): DexScreener and RugCheck are given up
    at their first 429 (HOST_MAX_429 1, so the office reads "giving up" with one wait), and the spotter never waits on a rate limit."""
    M.apply_profile(horizon)
    F.TIMEOUT = EARLY_TIMEOUT
    F.HOST_MAX_429[DS_HOST] = 1
    F.HOST_MAX_429[RC_HOST] = 1
    pause = EARLY_DS_PAUSE
    if mock:       # against the selftest's mock the pause of the test run (MEMEBOT_PAUSE) applies, not the real one
        try:
            pause = float(os.environ.get("MEMEBOT_PAUSE", EARLY_DS_PAUSE))
        except ValueError:
            pass
    return SpotHttp(mock, pause, tries)


def write_json(path, doc):
    """A doc written whole and then swapped in, so a reader (bot.py's live view, the page build) never sees half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)


# ---------------------------------------------------------------- early
def sandbox(d):
    """<d>/radar/in made fresh: the keyword searches' pair files and every other source folder and file of this scan (plain copies, no
    links). The desk writes pairs/tokens_* at the same time; those are not copied, so the spotter's input is the sources step's output."""
    ind = os.path.join(d, "radar", "in")
    shutil.rmtree(ind, ignore_errors=True)
    os.makedirs(os.path.join(ind, "pairs"))
    n = 0
    for fn in sorted(glob.glob(os.path.join(d, "pairs", "search_*.txt"))):
        shutil.copy2(fn, os.path.join(ind, "pairs"))
        n += 1
    for sub in F.SOURCE_DIRS:
        if sub not in SKIP_DIRS and os.path.isdir(os.path.join(d, sub)):
            shutil.copytree(os.path.join(d, sub), os.path.join(ind, sub))
    for name in F.SOURCE_FILES:
        if name not in SKIP_FILES and os.path.isfile(os.path.join(d, name)):
            shutil.copy2(os.path.join(d, name), os.path.join(ind, name))
    return ind, n


def prev_doc(d, now):
    """The early-list record of an earlier scan to price again for its hour price (p60): of those EARLY_PREV_MIN_AGE to EARLY_PREV_MAX_AGE
    minutes old, the one closest to an hour (a scan half an hour after another prices neither), or None."""
    best = None
    for fn in glob.glob(os.path.join(d, "db", "memeearly", "*.json")):
        doc = M.load_json(fn, None)
        t = M.num(doc.get("t")) if isinstance(doc, dict) else None
        if t and EARLY_PREV_MIN_AGE * 60_000 <= now - t <= EARLY_PREV_MAX_AGE * 60_000 and (best is None or abs(now - t - H) < abs(now - best["t"] - H)):
            best = doc
    return best


def pick(ind, prev=()):
    """The addresses to ask DexScreener about, in this order, without repeats and without the ones a keyword search already priced in
    full (gather's own rule): the previous early list, pump.fun graduated, GeckoTerminal, pump.fun new and live, Jupiter's 1-hour lists,
    the DexScreener, RugCheck and LaunchLab lists, pump.fun's biggest. At most EARLY_MAX_ADDRS. Returns (addresses, full count)."""
    lists = M.load_lists(ind)
    best, _, _ = M.merge_pairs(ind)
    full = {a for a, p in best.items() if not p.get("px_only") and p.get("dexId") != "jupiter" and not p.get("gt_only") and not p.get("gm_only")}
    pf, ptags = M.load_side(ind, "pf", M.PF_COLS)
    gt, _ = M.load_side(ind, "gt", M.GT_COLS)
    jup, jtags = M.load_side(ind, "jup", M.JUP_COLS)
    of = lambda rows, tags, tag: [a for a in rows if tag in tags.get(a, ())]
    order = (list(prev) + of(pf, ptags, "pf:graduated") + list(gt) + of(pf, ptags, "pf:new") + of(pf, ptags, "pf:live")
             + of(jup, jtags, "jup:trending1h") + of(jup, jtags, "jup:traded1h") + of(jup, jtags, "jup:organic1h")
             + [a for k in LIST_KEYS for a in lists.get(k, [])] + of(pf, ptags, "pf:top"))
    out, seen = [], set()
    for a in order:
        if a in seen or a in full or not M.B58.match(str(a)):
            continue
        seen.add(a)
        out.append(a)
    return out[:EARLY_MAX_ADDRS], len(full)


def ds_chunk(http, d, addrs, name):
    """One DexScreener tokens/v1 request for up to 30 addresses -> <d>/pairs/<name> (no file without a pair). Returns the number of pairs,
    or None when the request got no proper answer: then nothing is known about these coins, not even that they are gone."""
    data = http.get(F.DS + "/tokens/v1/solana/" + ",".join(addrs))
    pairs = data if isinstance(data, list) else ((data.get("pairs") or []) if isinstance(data, dict) and "pairs" in data else None)
    if not isinstance(pairs, list):
        return None
    return F.write_rows(d, "pairs", name, [r for r in (F.ds_row(p) for p in pairs) if r])


def fetch_pairs(http, ind, addrs, until):
    """DexScreener tokens/v1 for addrs, 30 a request, into <ind>/pairs/radar_NNN.txt. It stops when the host is given up (the first 429,
    or three requests without an answer) or the deadline is near. Returns (why it stopped early or missed some, or None; the addresses
    whose request was answered)."""
    http.until, http.late = until, False
    answered, total, failed = set(), 0, 0
    for i in range(0, len(addrs), 30):
        if DS_HOST in http.dead:
            break
        if time.time() > until - 2:
            http.late = True
            break
        got = ds_chunk(http, ind, addrs[i:i + 30], "radar_%03d.txt" % (i // 30))
        if got is None:
            failed += 1
        else:
            answered.update(addrs[i:i + 30])
            total += got
    http.until = None
    http.log("  dexscreener radar: %d pairs for %d addresses%s" % (total, len(addrs), (", %d request%s without an answer" % (failed, "" if failed == 1 else "s")) if failed else ""))
    if DS_HOST in http.dead:
        why = "DexScreener rate limit" if http.limited_by.get(DS_HOST) else "DexScreener did not answer"
    elif http.late:
        why = "DexScreener time limit"
    else:
        why = ("%d DexScreener request%s without an answer" % (failed, "" if failed == 1 else "s")) if failed else None
    return why, answered


def gather(ind, at):
    """memebot's gather on the sandbox at the spotter's clock: it writes <ind>/pairs.json and <ind>/universe.json only."""
    with contextlib.redirect_stdout(io.StringIO()) as s:
        M.cmd_gather(ind, at)
    try:
        return json.loads(s.getvalue())
    except ValueError:
        return {}


def weights(d, horizon):
    """The score weights: the last trader's (db/memebot/spotter.json) when they are of this rule and profile, else the prior. Never
    blended_weights(): that takes over half a minute on a big history."""
    sp = M.load_json(os.path.join(d, "db", "memebot", "spotter.json"), None)
    if isinstance(sp, dict) and sp.get("rule") == M.RULE and sp.get("horizon") == horizon and isinstance(sp.get("w"), dict):
        w = {str(k): M.num(v) for k, v in sp["w"].items() if M.num(v) is not None}
        if w:
            return w, "the last scan's weights"
    return dict(M.PRIOR), "the prior weights"


def coin(r, k, at, risk, paper):
    """One listed coin as young_early.json holds it (k: its place in score order)."""
    pr, b, a = r["pr"], r["basic"], r["a"]
    born = M.num(pr.get("pairCreatedAt"))
    if not born or born < 1e12:
        born = at - b["age_h"] * H         # the age came from pump.fun's createdAt (gather's own fallback)
    minted = M.parse_ms((pr.get("pf") or {}).get("createdAt")) or M.parse_ms((pr.get("ll") or {}).get("createdAt"))
    return {"addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48], "pair": pr.get("pairAddress") or None,
            "dex": str(pr.get("dexId") or "")[:24] or None, "launchpad": M.launchpad_of(pr, risk.get(a))[0], "born": int(born),
            "minted": int(minted) if minted else None, "ageMin": int(60 * b["age_h"]), "px": b["price"], "mc": b["mc"], "liq": b["liq"],
            "vol1": M.num(pr.get("volH1")), "vol": b["vol24"], "chgM5": M.num(pr.get("chgM5")), "chgH1": M.num(pr.get("chgH1")),
            "buysH1": M.num(pr.get("buysH1")), "sellsH1": M.num(pr.get("sellsH1")), "x": M.x_link(pr), "src": [str(t)[:24] for t in (pr.get("tags") or [])[:6]],
            "score": round(r["sc"], 1), "k": k, "held": a in paper, "rc": None}


def listing(d, ind, at, w):
    """memebot's scan of the sandbox at clock `at` and its new-launches filter, exactly as the tab's: (coins, how many qualified, risk).
    The positions are the real ones, read only: a coin the paper account holds is listed and marked, a pick-mode coin is left out."""
    pairs = M.load_pairs(ind)
    pos = M.positions(d)
    rows, _, held, recent, risk = M.scan(ind, pos, pairs, at, w)
    young = M.young_rows(rows, held, recent)
    paper = {p.get("addr") for p in pos.values() if p.get("grp") in M.PAPER_GROUPS and p["_left"] > 1e-9}
    return [coin(r, k, at, risk, paper) for k, r in enumerate(young[:EARLY_MAX], 1)], len(young), risk


def rc_word(http, a, rk):
    """RugCheck's words for one listed coin: its report's (rc_of), "no RugCheck report" only when RugCheck really answered without one
    (a 404), else whether it did not answer (a 401, 403, 410, 451, 5xx or a timeout) or was not asked (the time cap, or a coin the
    re-ranking brought in)."""
    urls = [F.RC + "/tokens/%s/report%s" % (a, s) for s in ("", "/summary")]
    if isinstance(rk, dict) or any(u in http.heard for u in urls):
        return rc_of(rk)
    return {"level": "none", "text": "RugCheck did not answer" if any(u in http.tried for u in urls) else "RugCheck: not checked"}


def rc_of(rk):
    """RugCheck's words for one coin, from memebot's own reading of the report (risk_view). A clean report never says 'safe'."""
    ok, text = M.risk_view(rk)
    if ok is None:
        out = {"level": "none", "text": "no RugCheck report"}
    elif ok is False:
        out = {"level": "danger" if "danger" in text.lower() else "warn", "text": text[:120]}
    else:
        out = {"level": "clean", "text": "RugCheck: no danger flags"}
    if isinstance(rk, dict):
        out["top1"], out["lp"] = M.num(rk.get("top1Pct")), M.num(rk.get("lpLocked"))
    return out


def short_why(e):
    """An error as a short reason for the page: no URL, at most 120 characters."""
    return re.sub(r"\s+", " ", re.sub(r"\w+://\S+", "(address)", "%s: %s" % (type(e).__name__, e)))[:120]


def cmd_early(d, now, t0, horizon, mock):
    T = time.time()
    clock = lambda: now + (ms() - t0)        # the cycle's clock: the wall clock in production (now == t0), the fake one in tests
    secs = {}
    out_path = os.path.join(d, "young_early.json")
    doc = {"v": 1, "t": now, "id": run_id(now), "at": None, "rcAt": None, "state": "failed", "why": "", "rcState": "pending", "partial": False,
           "rule": None, "horizon": horizon, "minLiq": M.YOUNG_MIN_LIQ, "maxAgeMin": int(round(60 * M.YOUNG_MAX_AGE_H)),
           "asked": 0, "requests": 0, "dsWaits": 0, "pairs": 0, "universe": 0, "n": 0, "coins": []}
    res = {"state": "failed", "n": 0, "shown": 0, "asked": 0, "requests": 0, "dsWaits": 0, "partial": False, "rcGot": 0, "at": None, "secs": secs}
    written = False
    try:
        http = setup(horizon, mock)
        doc["rule"] = M.RULE
        ind, nsearch = sandbox(d)
        prev = prev_doc(d, now)
        prev_addrs = [str(c.get("addr")) for c in ((prev or {}).get("coins") or []) if isinstance(c, dict) and M.B58.match(str(c.get("addr") or ""))][:EARLY_MAX]
        addrs, nfull = pick(ind, prev_addrs)
        secs["pick"] = round(time.time() - T, 1)
        say("%d addresses to DexScreener (%d coins already priced by %d keyword searches%s)" % (
            len(addrs), nfull, nsearch, (", the %d of the early list from %s first" % (len(prev_addrs), prev.get("id"))) if prev_addrs else ""))
        t_ds, n0 = time.time(), http.n
        stopped, answered = fetch_pairs(http, ind, addrs, T + EARLY_DEADLINE_S - EARLY_RC_S - 15)
        at = clock()
        secs["ds"] = round(time.time() - t_ds, 1)
        doc.update(at=at, asked=len(addrs), requests=http.n - n0, dsWaits=http.limited_by.get(DS_HOST, 0), partial=bool(stopped))
        if stopped:
            say("%s: the list is built from what came back" % stopped)
        t_b = time.time()
        gather(ind, at)
        pairs = M.load_pairs(ind)
        dex_n = M.dex_rows(pairs)
        doc.update(pairs=dex_n, universe=len(pairs))
        w, w_from = weights(d, horizon)
        if dex_n < M.MIN_SCAN_FOR_REC:
            doc.update(state="small", rcState="done", why="DexScreener gave only %d pairs (a rate limit or an outage)" % dex_n)
            secs["build"] = round(time.time() - t_b, 1)
            write_json(out_path, doc)
            written = True
            say("only %d DexScreener pairs: no early list (the scan's own guard is %d)" % (dex_n, M.MIN_SCAN_FOR_REC))
        else:
            coins, n, _ = listing(d, ind, at, w)
            doc.update(state="listed" if coins else "empty", n=n, coins=coins, rcState="pending" if coins else "done",
                       why=("%s: some coins may be missing" % stopped) if stopped else "")
            secs["build"] = round(time.time() - t_b, 1)
            write_json(out_path, doc)
            written = True
            say("%d new launch%s under an hour old at minute %.1f (%d shown, %s; %s DexScreener pairs)" % (
                n, "" if n == 1 else "es", (at - now) / 60000.0, len(coins), w_from, "{:,}".format(dex_n)))
            if coins:
                t_rc = time.time()
                until = min(time.time() + EARLY_RC_S, T + EARLY_DEADLINE_S - 5)
                http.until = until
                F.rc_reports(http, ind, [c["addr"] for c in coins], until=until)
                http.until = None
                coins2, n2, risk = listing(d, ind, at, w)       # the same pairs; scan reads the reports from <ind>/risk
                for c in coins2:
                    c["rc"] = rc_word(http, c["addr"], risk.get(c["addr"]))
                got = sum(1 for c in coins2 if c["rc"]["level"] != "none")
                heard = sum(1 for c in coins2 if c["rc"]["level"] != "none" or c["rc"]["text"] == "no RugCheck report")
                rcs = "done" if heard == len(coins2) else ("down" if heard == 0 else "partial")
                doc.update(coins=coins2, n=n2, state="listed" if coins2 else "empty", rcState=rcs, rcAt=clock())
                secs["rc"] = round(time.time() - t_rc, 1)
                write_json(out_path, doc)
                res["rcGot"] = got
                say("RugCheck: %d of %d reports (%s), the list re-ranked with them" % (got, len(coins2), rcs))
        if prev_addrs:
            pc = {}
            for a in prev_addrs:
                p = pairs.get(a)
                px = M.num((p or {}).get("priceUsd"))
                if p and px and px > 0:
                    pc[a] = {"px": px, "liq": M.num(p.get("liquidityUsd"))}
                elif p is not None or a in answered:    # a pair with no price (a keyword search's too), or DexScreener answered for it with no pair:
                    pc[a] = {"gone": True}              # gone; a coin it did not answer for and no search priced is unknown, not gone
            write_json(os.path.join(d, "radar", "prev.json"), {"id": prev.get("id"), "t": prev.get("t"), "at": at, "coins": pc})
            say("the early list of %s priced again: %d of %d still have a price, %d gone" % (
                prev.get("id"), sum(1 for v in pc.values() if not v.get("gone")), len(prev_addrs), sum(1 for v in pc.values() if v.get("gone"))))
        secs["all"] = round(time.time() - T, 1)
        res.update(state=doc["state"], n=doc["n"], shown=len(doc["coins"]), asked=doc["asked"], requests=doc["requests"], dsWaits=doc["dsWaits"],
                   partial=doc["partial"], at=doc["at"], why=stopped or "")
        print(json.dumps(res))
        return 0
    except Exception as e:      # the list is lost, never the cycle: bot.py goes on, and the page says why
        doc["why"] = short_why(e)
        if not written or doc.get("state") not in ("listed", "empty"):
            doc.update(state="failed", coins=[], n=0)
        elif doc.get("rcState") == "pending":
            doc.update(rcState="partial", rcWhy="RugCheck did not finish: the launch spotter failed")
        try:
            write_json(out_path, doc)
        except Exception:
            pass
        say("failed: %s" % doc["why"])
        secs["all"] = round(time.time() - T, 1)
        res.update(state=doc["state"], why=doc["why"])
        print(json.dumps(res))
        return 1


# ---------------------------------------------------------------- check
def cmd_check(d, now, t0, horizon, mock):
    """After the trader: the early list priced again (one DexScreener request, one try: this runs on the scan's critical path) and its
    record, db/memeearly/<run id>.json, with each coin's fate on the scored list; the previous record gets its price about an hour later
    from radar/prev.json (a p60 already there is replaced only by one closer to an hour)."""
    clock = lambda: now + (ms() - t0)
    doc = M.load_json(os.path.join(d, "young_early.json"), None)
    if not isinstance(doc, dict) or doc.get("t") != now or doc.get("state") not in ("listed", "empty"):
        print(json.dumps({"state": "none"}))
        return 0
    http = setup(horizon, mock, tries=1)
    rec = M.load_json(os.path.join(d, "db", "memebot", "recommend.json"), {}) or {}
    rec = rec if isinstance(rec, dict) and rec.get("t") == now else {}
    final = {}
    for k, y in enumerate([y for y in (rec.get("young") or []) if isinstance(y, dict) and y.get("addr")], 1):
        final.setdefault(y["addr"], (k, y.get("bought")))
    pairs = M.load_pairs(d)          # the trader's last gather, after the refresh
    coins = [c for c in (doc.get("coins") or []) if isinstance(c, dict) and M.B58.match(str(c.get("addr") or ""))][:EARLY_MAX]
    addrs = [c["addr"] for c in coins]
    p2 = {}
    if addrs:
        chk = os.path.join(d, "radar", "check")
        shutil.rmtree(chk, ignore_errors=True)
        os.makedirs(os.path.join(chk, "pairs"))
        http.until = time.time() + EARLY_TIMEOUT
        if ds_chunk(http, chk, addrs, "tokens_000.txt") is not None:
            best, _, _ = M.merge_pairs(chk)
            t2 = clock()
            for a in addrs:
                p = best.get(a)
                px = M.num((p or {}).get("priceUsd"))
                p2[a] = {"t": t2, "px": px, "liq": M.num(p.get("liquidityUsd"))} if p and px and px > 0 else {"t": t2, "gone": True}
    out_coins, born_after = [], 0
    for c in coins:
        a = c["addr"]
        k, b = final.get(a, (None, None))
        why = None
        if k is None:
            p = pairs.get(a)
            px = M.num((p or {}).get("priceUsd"))
            born = M.num(c.get("born"))
            if born and born > now:
                why, born_after = "born after the scan started", born_after + 1
            elif not p or p.get("px_only") or not px or px <= 0:
                why = "no price at the trader step"
            elif (M.num(p.get("liquidityUsd")) or 0) < M.YOUNG_MIN_LIQ:
                why = "liquidity under $%dk at the trader step" % round(M.YOUNG_MIN_LIQ / 1000)
            else:
                why = "not on the scored list (a gate or below the %d shown)" % M.YOUNG_N
        rc = c.get("rc")
        out_coins.append({"addr": a, "sym": c.get("sym"), "pair": c.get("pair"), "dex": c.get("dex"), "born": c.get("born"), "minted": c.get("minted"),
                          "ageMin": c.get("ageMin"), "px": c.get("px"), "liq": c.get("liq"), "mc": c.get("mc"), "score": c.get("score"), "k": c.get("k"),
                          "rc": rc.get("level") if isinstance(rc, dict) else None, "held": bool(c.get("held")), "p2": p2.get(a), "p60": None,
                          "final": k, "bought": b, "out": why})
    early = set(addrs)
    rid = run_id(now)
    record = {"v": 1, "t": now, "id": rid, "rule": doc.get("rule"), "horizon": doc.get("horizon"), "at": doc.get("at"), "rcAt": doc.get("rcAt"),
              "state": doc.get("state"), "partial": bool(doc.get("partial")), "n": doc.get("n"), "coins": out_coins,
              "finalOnly": [y["addr"] for y in (rec.get("young") or []) if isinstance(y, dict) and y.get("addr") and y["addr"] not in early][:M.YOUNG_N]}
    write_json(os.path.join(d, "db", "memeearly", rid + ".json"), record)
    upd = 0
    pv = M.load_json(os.path.join(d, "radar", "prev.json"), None)
    if isinstance(pv, dict) and RUN_ID.match(str(pv.get("id") or "")) and isinstance(pv.get("coins"), dict):
        fn = os.path.join(d, "db", "memeearly", pv["id"] + ".json")
        old = M.load_json(fn, None)
        off = lambda t_: abs(t_ - M.num(old.get("t")) - H) if isinstance(t_, (int, float)) and M.num(old.get("t")) else float("inf")   # from an hour
        if isinstance(old, dict) and old.get("id") == pv["id"]:
            for c in old.get("coins") or []:
                v = pv["coins"].get(c.get("addr")) if isinstance(c, dict) else None
                if isinstance(v, dict) and (not isinstance(c.get("p60"), dict) or off(pv.get("at")) < off(c["p60"].get("t"))):
                    c["p60"] = dict({k2: v[k2] for k2 in ("px", "liq", "gone") if k2 in v}, t=pv.get("at"))
                    upd += 1
            if upd:
                write_json(fn, old)
    on_final = sum(1 for c in out_coins if c["final"])
    say("record %s: %d of %d early coins on the scored list, %d born after the scan started, %d priced again%s" % (
        rid, on_final, len(out_coins), born_after, sum(1 for v in p2.values() if not v.get("gone")),
        (", %d coins of %s priced an hour later" % (upd, pv.get("id"))) if upd else ""))
    print(json.dumps({"state": doc.get("state"), "n": len(out_coins), "onFinal": on_final, "bornAfter": born_after, "p2Got": len(p2), "prevUpdated": upd}))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):      # coin names carry emoji
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["early", "check"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--now", type=float, default=None, help="the cycle's clock (ms)")
    ap.add_argument("--t0", type=float, default=None, help="the cycle's start on the wall clock (ms); default: this process's start")
    ap.add_argument("--horizon", default=os.environ.get("MEMEBOT_HORIZON", "24h"), choices=sorted(M.PROFILES))
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    a = ap.parse_args()
    t0 = int(a.t0 or ms())
    now = int(a.now or t0)
    if a.cmd == "early":
        sys.exit(cmd_early(a.dir, now, t0, a.horizon, a.mock))
    sys.exit(cmd_check(a.dir, now, t0, a.horizon, a.mock))


if __name__ == "__main__":
    main()
