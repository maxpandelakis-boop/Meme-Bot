#!/usr/bin/env python3
"""shadow.py: the Pick's shadow rules ("Shadow rules", German "Schatten-Regeln"). Fake money only: nothing here buys, signs or sends anything, nothing the
trader, the training or the big test reads comes from here, and nothing here is advice. The Pick's own sell rule (memebot.PAPER_RULE:
-30 % stop, 11x, 6 h) and its paper account are not touched: this file reads the positions and their exits and writes only its own
docs (db/memeshadow).

The question (the user, 22 Oct 2026): which sell rule would hold for the Pick? Every real Pick buy (grp "hold" in the paper account,
bought from SINCE on) is mirrored in four shadow accounts. Each sells the same coin, bought at the same minute for the same ticket with
the same paper fees, by its own rule. After about two weeks the accounts say which rule did best on the same buys.

The rules (RULES, fixed when the test started on SINCE; another rule would be a new test with its own start, never an edit):
  K  the fixed rule replayed (-30 %, 11x, 6 h; the Pick's own rule until the chart exit of 24 Oct): the control. A shadow rule is
     compared with K (the same prices, the same method); the real account's own result on the same buys stands beside it.
  X  the chart exit replayed (memebot.chart_hit: 15 % under the high once it reached 1.5x, -15 % in 30 minutes, -50 %, 11x, 6 h; the
     Pick's own rule since 24 Oct, added then): X against K on the same buys is the review's question; the real account against X
     shows the gap between the replay and the real fills.
  A  stop -20 %, target 3x, 6 h       the exit replay's best on the live Pick account (exit_grid.py on 95 trades to 22 Oct: -3.30 EUR
                                      per trade against -6.05 for the real rule replayed)
  B  no stop, target 2x, 12 h         the best on the training days of the longer-hold test (research/winlose/WINLOSE-2026-10-22.md,
                                      addendum 4: -1.85 per 20 on unseen days against -3.00 for the real rule)
  C  half at 2x, the rest as the real rule (-30 %, 11x, 6 h)   a partial sale (the 134-exit test's "1/2 at 2x, rest rule A")
  D  a stop 30 % under the best close so far, 6 h, no target    a trailing stop (the 134-exit test's "trail 30% at once, 6 h")

The prices: one 12-hour minute path per buy (entryAt to entryAt + 12 h), asked for once its 12 hours have passed, in the peaks job
after peak.py (one GeckoTerminal request per buy on peak.py's client and pacing, peak.gt_get), and put through peak.py's own glitch
filter (peak.peak_of: a rug exit, the liquidity floor and a collapse end the pool's life; peak.path_of keeps every close over cpx with
its volume): db/memeshadow/<pid>.json. A path that GeckoTerminal does not have (no one-minute candles reaching back to the entry after
MAX_TRIES runs, a pool it does not know, candles in another unit, or still nothing GIVE_UP_H after the end) leaves the buy out of every
account alike ("none"); a buy whose 12 hours have not passed yet is open in every account.

The replay (replay(), pure): closes only, in time order, over cpx (the first close at or after the entry minute, as memebot books); a
close on dust volume (under peak.DUST_VOL) or over memebot.CANDLE_MAX_X sells nothing and moves no trailing stop; the target is looked
at first (exit_grid.replay's order), then the stop: a target sells what is left at exactly the target, a stop at min(close, level)
(memebot's own booking), the half sale half at exactly 2x. A buy from memebot.LIVE_SELL_AT on (the Pick sells on the live chart since
then) is replayed the way the Pick now sells, every rule alike: each minute's low and high (the path's "w", memebot.hold_wicks) instead
of its close, the stop first (at that low, never above its level), then the target and the half sale on the high (its close when the
high is over CANDLE_MAX_X); the trailing stop still follows the best close. At the time limit what is left goes at the lower of the last clean close and
the last close by then (peak's value at 6 h), at the target when that is at or above it. A pool that died sells what is left at 0 without
a stop or after a rug exit (no price to sell into), else at half the stop level (exit_grid's default fill for a dead pool). Every sale
pays the paper fees on the position itself (memebot.pos_value), so K and the real account differ only where the replay's prices do.

Usage:
  python3 shadow.py run --dir mb [--now ms] [--deadline-s 90] [--mock URL]   ask for the due paths; one JSON line; exit 0 always
  python3 shadow.py summary --dir mb [--now ms]                               the accounts as JSON (the page and the daily report read
                                                                              summary() itself)
"""
import argparse, json, os, re, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: positions, in_account, pos_value, the paper rule, CANDLE_MAX_X
import fetch as F        # the HTTP client (pacing, cooldowns, circuit breaker)
import peak as P         # read only: gt_get, ohlcv_rows, covers, peak_of, path_of, rug_ok_at, ds_for, context, DUST_VOL

V = 1
SINCE = 1792684800000      # Thu 22 Oct 2026 16:00 UTC (18:00 Berlin): buys from here on are mirrored. Never edit after it has passed.
H, MIN = 3_600_000, 60_000
PATH_H = 12.0              # hours of minute path per buy: the longest rule's hold
SETTLE_MS = P.SETTLE_MS    # a path is asked for once now >= entryAt + PATH_H + 2 min
MAX_TRIES = 3              # empty answers (no candles, or none reaching back to the entry) before a buy is left out
GIVE_UP_H = 72.0           # a buy still without a path this long after its end is left out (GeckoTerminal keeps minutes about 4 days)
MAX_ITEMS = 24             # paths one run asks for, oldest first
DEAD_FILL = 0.5            # a stop rule in a pool that died gets this share of its stop level (exit_grid.FILL_DEFAULT["dead"])
DOC_DIR = ("db", "memeshadow")
STATES = ("ok", "none")    # settled: never asked again

# id, the page's name and words, and the rule. stop: the fraction under cpx (None: no stop); target: the multiple (None: none); half: the
# multiple at which half is sold; trail: the stop follows the best close at this fraction under it (it starts at 1 - trail); hours.
RULES = (
    {"id": "K", "name": "Old fixed rule", "text": "stop −30%, target 11x, 6 h (the Pick's rule until Oct 24)", "stop": 0.30, "target": 11.0, "hours": 6.0},
    {"id": "A", "name": "Tight stop", "text": "stop −20%, target 3x, 6 h", "stop": 0.20, "target": 3.0, "hours": 6.0},
    {"id": "B", "name": "Longer, no stop", "text": "no stop, target 2x, 12 h", "stop": None, "target": 2.0, "hours": 12.0},
    {"id": "C", "name": "Half at 2x", "text": "half at 2x, rest −30% / 11x / 6 h", "stop": 0.30, "target": 11.0, "half": 2.0, "hours": 6.0},
    {"id": "D", "name": "Trailing stop", "text": "stop 30% under the best price, 6 h", "stop": 0.30, "target": None, "trail": 0.30, "hours": 6.0},
    {"id": "X", "name": "Chart exit, replayed", "text": "the Pick's rule since Oct 24: 15% under the high from 1.5x, −15% in 30 min, −50%, 11x, 6 h",
     "stop": M.CHART_STOP, "target": 1.0 + M.HOLD_TP, "chart": True, "hours": M.HOLD_MAX_H},
)
CONTROL = "K"
assert (RULES[0]["stop"], RULES[0]["target"], RULES[0]["hours"]) == (M.HOLD_STOP, 1.0 + M.HOLD_TP, M.HOLD_MAX_H)   # K is the real rule
assert max(r["hours"] for r in RULES) <= PATH_H


def num(v):
    return M.num(v)


def log(s):
    print(s, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- the buys
def trades(d, pos=None, since=None):
    """The mirrored buys: the paper account's Pick positions (grp "hold", in the account since its restart) bought at or after since
    (SINCE), oldest first -> [(pid, position)] (positions as memebot.positions gives them, with _exits and _left)."""
    pos = M.positions(d) if pos is None else pos
    since = SINCE if since is None else since
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    acct = num(state.get("paperSince")) if isinstance(state, dict) else None
    out = [(pid, p) for pid, p in pos.items() if isinstance(p, dict) and p.get("grp") == "hold" and M.in_account(p, acct)
           and (num(p.get("t")) or 0) >= since and num(p.get("px")) and p.get("pair")]
    return sorted(out, key=lambda kv: (entry_of(kv[1]), kv[0]))


def entry_of(p):
    return int(num(p.get("entryAt")) or num(p.get("t")) or 0)


def safe_id(pid):
    pid = str(pid)
    return pid if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$", pid) and ".." not in pid else None


def doc_path(d, pid):
    return os.path.join(d, *DOC_DIR, pid + ".json")


def load_doc(d, pid):
    doc = M.load_json(doc_path(d, pid), None) if safe_id(pid) else None
    return doc if isinstance(doc, dict) and doc.get("v") == V else None


def write_doc(d, pid, doc):
    """db/memeshadow/<pid>.json whole or not at all (a temp file outside the synced folder, then a rename)."""
    tmp_dir = os.path.join(d, ".shadowtmp")
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(os.path.join(d, *DOC_DIR), exist_ok=True)
    tmp = os.path.join(tmp_dir, pid + ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, doc_path(d, pid))


def due(d, now, pos=None):
    """The buys whose 12-hour path is due this run: the 12 hours (and SETTLE_MS) passed, no settled doc yet; oldest first, at most
    MAX_ITEMS -> [(pid, position, doc or None)]."""
    out = []
    for pid, p in trades(d, pos):
        if not safe_id(pid) or now < entry_of(p) + int(PATH_H * H) + SETTLE_MS:
            continue
        doc = load_doc(d, pid)
        if doc and doc.get("state") in STATES:
            continue
        out.append((pid, p, doc))
    return out[:MAX_ITEMS]


# ---------------------------------------------------------------- the paths
def gt_url(pool, end):
    """One-minute candles up to 2 minutes past the end: limit 1000 reaches back about 16.6 h, so one request covers the 12 hours."""
    return F.GT + "/networks/solana/pools/%s/ohlcv/minute?aggregate=1&limit=1000&before_timestamp=%d&currency=usd&token=base" % (
        urllib.parse.quote(str(pool), safe=""), P.gt_before(end))


def book(ctx, pid, p, status, rows, old, now):
    """The doc of one buy from one answer: "ok" with the path, "waiting" (ask again next run), "none" (left out), or None (nothing
    learned: the old doc, if any, stays)."""
    entry = entry_of(p)
    end = entry + int(PATH_H * H)
    tries = int(num((old or {}).get("tries")) or 0)
    doc = {"v": V, "pid": pid, "sym": str(p.get("sym") or "?")[:24], "addr": p.get("addr"), "pair": p.get("pair"), "t": num(p.get("t")),
           "entryAt": entry, "end": end, "upd": int(now), "tries": tries}
    late = now >= end + GIVE_UP_H * H
    if status == "ok":
        if rows and P.covers(rows, entry, 1):
            r = P.peak_of(rows, entry, end, num(p.get("px")), P.rug_ok_at(ctx, p), P.ds_for(ctx, pid, p), liq0=num(p.get("liq")), mc0=num(p.get("mc")), res=1)
            if r.get("state") == "ok":
                path = P.path_of(rows, entry, end, r, "pos", "hold", pid)
                if path and path.get("c"):
                    return dict(doc, state="ok", cpx=path["cpx"], dead=path["dead"], c=path["c"], w=wicks(rows, entry, end, path["cpx"]))
            if r.get("state") == "unit":
                return dict(doc, state="none", why="candles in another unit than the paid price")
        status = "empty"                       # no candles, or none that reach back to the entry
    if status == "empty":                      # an answer without candles that reach back to the entry (or a pool GeckoTerminal does not know)
        tries += 1
        if tries >= MAX_TRIES or late:
            return dict(doc, state="none", tries=tries, why="no one-minute candles from the entry on")
        return dict(doc, state="waiting", tries=tries)
    if late:                                   # failed requests only (5xx, timeouts) for days: left out
        return dict(doc, state="none", why="GeckoTerminal gave no answer for %d hours" % GIVE_UP_H)
    return None


def wicks(rows, entry, end, cpx):
    """The path's minute highs and lows over cpx (memebot.hold_wicks: a wick more than CANDLE_WICK_X beyond its close is the close), row for
    row as peak.path_of's "c": [[seconds after the entry, high, low], ...]. The replay sells on them for a buy from LIVE_SELL_AT on."""
    out = []
    for c in P._rows(rows):
        if c[0] >= entry - MIN and c[0] + MIN <= end:
            hi, lo = M.hold_wicks(c)
            out.append([int((c[0] - entry) // 1000), P.sig(hi / cpx), P.sig(lo / cpx)])
    return out


def run(d, now, deadline_s=90.0, mock=None):
    """Ask GeckoTerminal for each due buy's 12-hour path, one after another, until the deadline -> the summary line (dict). Never
    raises: an error is logged and the docs written so far stay."""
    t0 = time.time()
    out = {"ok": True, "due": 0, "paths": 0, "waiting": 0, "none": 0, "why": "nothing due"}
    try:
        items = due(d, now)
        out["due"] = len(items)
        if not items:
            return out
        ctx = P.context(d)
        http = F.Http(mock, pause=0, log=log)
        until, why = t0 + float(deadline_s), "all asked"
        for pid, p, old in items:
            if P.GT_HOST in http.dead:
                why = P.GT_GONE
                break
            end = entry_of(p) + int(PATH_H * H)
            st, j = P.gt_get(http, gt_url(p["pair"], end), until)
            if st in ("deadline", "limited", "dead", "share"):
                why = {"deadline": "deadline", "limited": "GeckoTerminal rate limit", "dead": P.GT_GONE, "share": P.GT_SHARE}[st]
                break
            rows = P.ohlcv_rows(j, P.gt_before(end), 1) if st == "ok" else []
            if st == "shape" or (st == "ok" and rows is None):
                st, rows = "error", []
            doc = book(ctx, pid, p, st, rows or [], old, now)
            if doc is None:
                continue
            write_doc(d, pid, doc)
            key = {"ok": "paths", "waiting": "waiting", "none": "none"}[doc["state"]]
            out[key] += 1
        out["why"] = why
    except Exception as e:      # a report: the peaks job must go on to push what it has
        out.update(ok=False, err="%s: %s" % (type(e).__name__, str(e)[:200]))
        log("shadow: %s (the docs written so far stay)" % out["err"])
    out["secs"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------- the replay (pure)
def replay(doc, rule):
    """One rule on one buy's path -> {"sales": [[ms, frac, mult, why], ...], "why": the last sale's reason} or None (not replayable: no
    close on real volume by the rule's time limit in a pool that did not die). mult is over the entry price (memebot books entry x
    level); why: "tp", "half", "stop", "trail", "time", "rug" (a dead pool without a stop or after a rug exit), "dead" (a dead pool,
    a stop rule: DEAD_FILL of its level)."""
    entry, cpx = int(num(doc.get("entryAt")) or 0), num(doc.get("cpx"))
    if not entry or not cpx or not isinstance(doc.get("c"), list):
        return None
    horizon = entry + int(rule["hours"] * H)
    dead = doc.get("dead") if isinstance(doc.get("dead"), dict) else None
    dead_at = num(dead.get("at")) if dead else None
    wk = None                                  # the live chart (memebot.LIVE_SELL_AT): {seconds: (high, low)} over cpx
    if entry >= M.live_sell_at() and isinstance(doc.get("w"), list):
        wk = {int(num(r[0])): (num(r[1]), num(r[2])) for r in doc["w"] if isinstance(r, (list, tuple)) and len(r) >= 3 and num(r[0]) is not None
              and (num(r[1]) or 0) > 0 and (num(r[2]) or 0) > 0}
    atoms, clean, anyv = [], [], []
    for row in doc["c"]:
        if not isinstance(row, (list, tuple)) or len(row) < 2 or num(row[0]) is None or not num(row[1]) or num(row[1]) <= 0:
            continue
        t, x = entry + int(num(row[0])) * 1000, num(row[1])
        vol = num(row[2]) if len(row) > 2 else None
        if t >= horizon or (dead_at is not None and t >= dead_at):
            continue
        ok = vol is None or vol >= P.DUST_VOL
        if t + MIN <= horizon:
            anyv.append(x)
            if ok:
                clean.append(x)
        if ok:
            hl = wk.get(int(num(row[0]))) if wk is not None else None
            atoms.append((t, x, (max(hl[0], x), min(hl[1], x)) if hl else (x, x)))
    died = dead_at is not None and dead_at <= horizon
    if not died and not clean:
        return None
    stop, target, half, trail = rule.get("stop"), rule.get("target"), rule.get("half"), rule.get("trail")
    left, best, sales = 1.0, 1.0, []
    if rule.get("chart"):                      # the chart exit (memebot.chart_hit) on the same clean minutes, their low and high as above
        hc = M.chart_hit([(t, x, hl[0], hl[1], x) for t, x, hl in atoms], entry, None, 1.0)
        if hc["hit"]:
            return {"sales": [[int(hc["hit"]), 1.0, hc["mult"], hc["why"]]], "why": hc["why"]}
        stop = 1.0 - (hc["lvl"] or 1.0 - stop)      # a pool that died: DEAD_FILL of the level it stood at, as the stop rules
        atoms = []                                  # no sale on the way: only the pool's death or the time limit below

    def level():
        if trail:
            return best * (1.0 - trail)
        return (1.0 - stop) if stop is not None else None

    for t, x, (hi, lo) in atoms:
        if wk is not None:                     # the live chart: the low first (the safe side), then the high
            L, hx = level(), hi if hi <= M.CANDLE_MAX_X else x
            if L is not None and lo <= L:
                sales.append([t, left, min(lo, L), "trail" if trail else "stop"])
                return {"sales": sales, "why": sales[-1][3]}
            if target is not None and target <= hx <= M.CANDLE_MAX_X:
                sales.append([t, left, target, "tp"])
                return {"sales": sales, "why": "tp"}
            if half and left > 0.5 and half <= hx <= M.CANDLE_MAX_X:
                sales.append([t, 0.5, half, "half"])
                left = 0.5
            if x <= M.CANDLE_MAX_X:
                best = max(best, x)
            continue
        if x > M.CANDLE_MAX_X:                 # a glitch close: no sale, no new best
            continue
        L = level()
        if target is not None and x >= target:
            sales.append([t, left, target, "tp"])
            return {"sales": sales, "why": "tp"}
        if L is not None and x <= L:
            sales.append([t, left, min(x, L), "trail" if trail else "stop"])
            return {"sales": sales, "why": sales[-1][3]}
        if half and left > 0.5 and x >= half:
            sales.append([t, 0.5, half, "half"])
            left = 0.5
        best = max(best, x)
    if died:
        L = level()
        rug = L is None or str(dead.get("why") or "") == "rug exit"
        sales.append([int(max(dead_at, entry)), left, 0.0 if rug else DEAD_FILL * L, "rug" if rug else "dead"])
        return {"sales": sales, "why": sales[-1][3]}
    x_end = min(clean[-1], anyv[-1])
    if target is not None and target <= x_end <= M.CANDLE_MAX_X:
        sales.append([horizon, left, target, "tp"])
    else:
        sales.append([horizon, left, x_end, "time"])
    return {"sales": sales, "why": sales[-1][3]}


def money(p, sales):
    """What a buy made under one rule's sales: what came back after the paper fees (memebot.pos_value on the position) minus the ticket."""
    back = sum(M.pos_value(p, frac, mult) for _, frac, mult, _ in sales)
    return round(back - (num(p.get("ticket")) or 0.0), 2)


def real_result(p):
    """The real account's result of a buy: what came back minus the ticket once it is sold, else None."""
    if (num(p.get("_left")) or 0.0) > 1e-9:
        return None
    back = sum(num(e.get("eur")) or 0.0 for e in p.get("_exits") or [] if isinstance(e, dict))
    return round(back - (num(p.get("ticket")) or 0.0), 2)


def summary(d, now=None, pos=None):
    """The shadow accounts on the buys whose path is in: per rule the result in euros, per buy, how many buys ended in profit, the
    3x sales and the reasons; the real account on the same buys; the open and the left-out buys; the trades newest first. Every rule
    counts the same buys (a buy that one rule cannot replay is left out of all). Reads only."""
    now = int(now or time.time() * 1000)
    rows, n_open, n_out = [], 0, 0
    for pid, p in trades(d, pos):
        doc = load_doc(d, pid) if safe_id(pid) else None
        st = (doc or {}).get("state")
        row = {"pid": pid, "sym": str(p.get("sym") or "?")[:24], "t": entry_of(p), "real": real_result(p), "res": {}, "state": "open"}
        if st == "none":
            row["state"] = "none"
            n_out += 1
        elif st == "ok" and row["real"] is None:      # the real account has not sold it yet (a price missing once): open
            n_open += 1
        elif st == "ok":
            res = {r["id"]: replay(doc, r) for r in RULES}
            if any(v is None for v in res.values()):
                row["state"] = "none"
                n_out += 1
            else:
                row["state"] = "ok"
                row["res"] = {k: {"eur": money(p, v["sales"]), "why": v["why"], "top": max(s[2] for s in v["sales"])} for k, v in res.items()}
        else:
            n_open += 1
        rows.append(row)
    done = [r for r in rows if r["state"] == "ok"]
    ticket = num(getattr(M, "TOP_TICKET", None)) or 50.0

    def acct(vals, whys=(), tops=()):
        n = len(vals)
        why = {}
        for w in whys:
            why[w] = why.get(w, 0) + 1
        return {"eur": round(sum(vals), 2), "per": round(sum(vals) / n, 2) if n else None, "won": sum(1 for v in vals if v > 0.004),
                "n": n, "x3": sum(1 for v in tops if v >= 3.0), "why": why}
    accts = []
    for r in RULES:
        a = acct([x["res"][r["id"]]["eur"] for x in done], [x["res"][r["id"]]["why"] for x in done], [x["res"][r["id"]]["top"] for x in done])
        a.update(id=r["id"], name=r["name"], text=r["text"])
        a["vsK"] = None
        accts.append(a)
    k = next(a for a in accts if a["id"] == CONTROL)
    for a in accts:
        if a["id"] != CONTROL and done:
            a["vsK"] = round(a["eur"] - k["eur"], 2)
    real = acct([x["real"] for x in done])
    real.update(id="real", name="Real Pick account", text="the chart exit (rule X) · really booked")
    shadows = [a for a in accts if a["id"] != CONTROL]
    lead = max(shadows, key=lambda a: a["eur"]) if done else None     # the best shadow (the first of equals); ahead: better than K
    return {"v": V, "t": now, "since": SINCE, "ticket": ticket, "pathH": PATH_H, "n": len(done), "open": n_open, "out": n_out,
            "real": real, "accts": accts, "leader": lead["id"] if lead else None, "ahead": bool(lead and lead["vsK"] > 0.004),
            "trades": sorted(rows, key=lambda r: (-r["t"], r["pid"]))}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the Pick's shadow rules: other sell rules on the same buys (fake money, hindsight)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ask for the due 12-hour paths and write db/memeshadow")
    r.add_argument("--dir", default="mb")
    r.add_argument("--now", type=int, default=None, help="ms; default: the wall clock")
    r.add_argument("--deadline-s", type=float, default=90.0)
    r.add_argument("--mock", default=None, help="rewrite every URL to <mock>/<host>/<path> (selftest)")
    s = sub.add_parser("summary", help="the shadow accounts as JSON")
    s.add_argument("--dir", default="mb")
    s.add_argument("--now", type=int, default=None)
    a = ap.parse_args(argv)
    now = a.now if a.now is not None else int(time.time() * 1000)
    if a.cmd == "run":
        print(json.dumps(run(a.dir, now, a.deadline_s, a.mock)), flush=True)
    else:
        print(json.dumps(summary(a.dir, now)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
