#!/usr/bin/env python3
"""peak.py: the hindsight category "best price within 6 h" of the paper account. Fake money only: nothing is ever bought.

For every paper position (since the restart, and the few bought before it, shown apart), open or sold, once its 6-hour window has
closed, this books the highest minute-candle CLOSE of the bought pool within 6 hours after the paper buy, through a glitch filter, the
LOWEST close within the same 6 hours (the most it could have lost without the stop-loss), and what selling at exactly 6 hours would
have given. One doc per position: db/memepeak/<pid>.json. It is hindsight, not a
trading rule: the stop-loss account (memebot.py) is the paper account that really runs, and it is not touched. Nothing here is read
by the trader, the training or the big test; this file only imports memebot (paper fees, positions) and fetch (the HTTP client).

The window: from the minute candle holding the entry (candle start >= entryAt - 60 s) to entryAt + 6 h; it counts once
now >= end + 2 min. Measured on the bought pool (the position's "pair") only.
The money: cpx = the first close at or after the entry minute; base = max(cpx, px) when px/cpx is between 1/3 and 3, else cpx (it
never flatters); x = best accepted close / base; x6 = the last close by the end / base (the lower of the last close on real volume
and the last close of any volume: a dust print can lower it, never raise it), 0 when the pool died inside the window; x >= x6 (the
last close is a price inside the window too, so it is the best when the price rose into the end; a jump or cap there still needs
support; in the estimate and in an older version's doc kept by keep_better as well); eur and eur6
are memebot.pos_value(p, 1.0, x) and (..., x6): the paper fees.
The low: lo = the lowest level the pool held inside the window / base, at loAt; eurLo = memebot.pos_value(p, 1.0, lo). Closes only;
a dust candle is no price (it can be neither the best nor the low); a close that the next real close within 5 minutes took back
counts only down to that next close (one glitch print is no low), a close no real close followed within 5 minutes stands (the price
stayed there); the entry counts (its close, or the base when that candle was dust), so lo <= 1; the value at 6 h counts, so
lo <= x6; a pool that died inside the window (rug exit, liquidity floor, collapse) is a real loss: lo = 0 at the time it died. The
candles of another unit (state "unit") book no low either.

The glitch filter, in this order (every rule that fires is written into "cut", the first words naming the rule):
  1. closes only, never wicks
  2. dead pool: the window ends at a rug exit's last healthy scan (okAt: the latest db/memeruns doc before the rug exit, never
     before the entry), and at the first DexScreener point inside the window with liquidity under max($1,000, 10% of the entry's)
  3. collapse: a close under 10% of the confirmed level the pool held (the best accepted level of the last 30 minutes, else the
     latest one; the entry counts) that no later close brings back to 20% of it within 30 minutes ends the window (a close on dust
     volume counts as a recovery only up to 3x the level; the 2 minutes after the end that the fetch returns count too); a slow
     fall in a live pool is no collapse
  4. dust: a candle with less than $25 of volume is ignored as a level (it cannot be the best close or confirm one)
  5. confirmation: a level counts only up to what the next close within 5 min also held
  6. jump and cap: a level more than 3x above the previous close and the best so far, or over 30x base, or with an implied market
     cap over $100M, needs support: 5 closes from it at half of it or more with $1,000 of volume each, or a DexScreener point with
     liquidity of $10,000 or more at a third of it or more within 60 min; otherwise the best supported level stands
  7. unit: a DexScreener point with $10,000 of liquidity or more, more than 3x away from that minute's close: state "unit", not booked

States: "ok" (src "m1", or "m15" when GeckoTerminal had only 15-minute candles: a lower bound), "est" (after 3 empty fetches, or
an empty answer 48 h after the end: from a take-profit exit (11x), a time exit (x6) and the tip record's stored candle paths of the
same coin and run; x >= 1.0; lo from the same paths, the paper exits' prices and the DexScreener points inside the window, x6 and a
dead pool: an upper bound of the real low), "unit", "waiting" (the fetch came back empty; "tries" counts). ok, est and unit docs are
never rewritten unless PEAK_V changes. When PEAK_V changes, a doc of the older version is priced again, but never made worse: when
this run gets a lesser source than the old doc had (15-minute candles or an estimate where it had minute candles, e.g. because
GeckoTerminal no longer keeps that day's minutes), the old doc's best and value at 6 h stay and only the low of this run is added
(rebased onto the old doc's base); an empty answer leaves the old doc as it is for a later run. A failed request (a 5xx, a timeout,
429s through the whole wait ladder) never settles a window: a window under 48 h past its end keeps its doc as it was, an older one gets a waiting doc with one more try (an estimate only after
3). A 5xx or a timeout three times in a row, or one answer that is not GeckoTerminal's OHLCV shape (a block page), switches
GeckoTerminal off for the rest of the run. Docs are written every SETTLE_EVERY windows, so a step killed at its timeout keeps them.

Usage:
  python3 peak.py run --dir mb [--now <ms>] [--deadline-s 600] [--mock http://127.0.0.1:8765]
      -> prints one JSON line {"items","ok","m15","est","unit","waiting","radar","secs","why"}; progress goes to stderr
         ("radar": radar_paper.py's summary; the radar account is priced on what is left of the deadline, see radar_account)
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M      # read only: positions, paper fees, PAPER_GROUPS
import fetch as F        # read only: Http (pacing, cooldowns, circuit breaker), GT, HOST_GAP, HOST_429, row

PEAK_V = 2                  # the doc version: a settled doc is recomputed only when this changes (2: the low within 6 h, lo/loAt/eurLo)
MIN = 60_000
WINDOW_H = 6.0              # hours after the entry
SETTLE_MS = 2 * MIN         # a window counts once now >= end + 2 min
PEAK_MAX_ITEMS = 60         # windows one run asks GeckoTerminal for (10 s apart: about 10 minutes)
RECENT_N, RECENT_H = 10, 3.0  # up to this many windows that closed in the last hours go first, then the backlog oldest first
MAX_TRIES = 3               # empty fetches (or, for a window older than EST_AFTER_H, failed ones) before a window is estimated
EST_AFTER_H = 48.0          # an empty answer this long after the end is estimated at once (GeckoTerminal keeps minutes >= 106 h: WP0)
COVER_MIN = {1: 10, 15: 30}  # the answer must reach back to within this many minutes after the entry, else GT's history was cut
DUST_VOL = 25.0             # dollars of volume a candle needs to count
CONFIRM_MIN = 5             # the next close must come within this many minutes to confirm a level
COLLAPSE, RECOVER, RECOVER_MIN = 0.10, 0.20, 30
RECOVER_DUST_X = 3.0        # a close on dust volume counts as a recovery only between RECOVER and this many times the held level
JUMP_X = 3.0
CAP_X, MAX_MC = 30.0, 100e6
CAP_RUN, CAP_VOL, CAP_LIQ, CAP_NEAR_MIN = 5, 1_000.0, 10_000.0, 60
LIQ_FLOOR, LIQ_REL = 1_000.0, 0.10
UNIT_X = 3.0
TP_X = 1.0 + M.HOLD_TP      # a take-profit exit is booked at exactly 11x the entry price
SETTLED = ("ok", "est", "unit")
MIN_REQ_S = 2.0             # no request is started with less time than this left before the deadline
GT_429_LADDER_S = (15, 30, 60)   # WP0 probe: on a 429 wait 15, 30, then 60 s and ask the same window again; then it waits for a later run
SETTLE_EVERY = 10           # the docs are written after every this many windows (a step killed at its timeout keeps them)
MAX_ANSWER = 4_000_000      # bytes: a bigger answer is no OHLCV answer
GT_HOST = urllib.parse.urlsplit(F.GT).netloc
GT_GONE = "GeckoTerminal given up for this run"
GT_SHAPE = "GeckoTerminal answered in an unknown shape"
DOC_KEYS = ("v", "pos", "grp", "sym", "addr", "pair", "ticket", "t", "entryAt", "end", "upd", "state", "src", "res", "tries",
            "px", "cpx", "base", "x", "at", "rawX", "x6", "eur", "eur6", "lo", "loAt", "eurLo", "dead", "cut", "n")
SRC_RANK = {"m1": 3, "m15": 2, "est": 1}   # how good a settled doc's source is: an older version's doc is never replaced by a lesser one


def num(v):
    return M.num(v)


def sig(v, n=6):
    """A multiple or a price with n significant digits (a dead pool's 5.7e-08 stays readable, 38.5712345 becomes 38.5712)."""
    return None if v is None else float("%.*g" % (n, v))


def money(v):
    return "$" + ("{:,.0f}".format(v) if v >= 1 or v == 0 else "%.2f" % v)


def mult_text(v):
    return ("{:,.0f}x".format(v) if v >= 100 else ("%.1fx" % v if v >= 10 else "%.2fx" % v)) if v is not None else "?"


def window(p):
    """(entryAt, end) of a position: the buy (entryAt, else the run's t) and 6 hours later."""
    entry = int(num(p.get("entryAt")) or num(p.get("t")) or 0)
    return entry, entry + int(WINDOW_H * 3_600_000)


def pool_key(p):
    """The candle file key of a position: pk<entry minute>, so two positions in one pool keep their own windows."""
    return "pk%d" % (window(p)[0] // MIN)


def safe_pool(pool):
    return re.sub(r"[^A-Za-z0-9]", "", str(pool or ""))[:64]


# ---------------------------------------------------------------- the glitch filter (pure)
def dead_of(entry_at, end, rug_ok_at=None, ds_points=(), liq0=None):
    """The first time the pool is known dead inside the window, from the rug exit (okAt, never before the entry) and the
    DexScreener points under the liquidity floor: (ms, why, cut text) or None."""
    out = []
    if rug_ok_at is not None:
        t = max(int(rug_ok_at), int(entry_at))
        if t <= end:
            out.append((t, "rug exit", "pool dead: rug exit, " + ("last healthy scan %d min after the entry" % ((t - entry_at) // MIN) if t > entry_at
                                                               else "no healthy scan after the entry")))
    floor = max(LIQ_FLOOR, LIQ_REL * (num(liq0) or 0.0))
    for t, _, liq in _points(ds_points):
        if entry_at <= t <= end and liq is not None and liq < floor:
            out.append((int(t), "liquidity", "pool dead: liquidity %s at minute %d" % (money(liq), (t - entry_at) // MIN)))
            break
    return min(out) if out else None


def _points(ds_points):
    """DexScreener points as (ms, price or None, liquidity or None), the unreadable ones dropped, in time order (then price and
    liquidity): the result never depends on the order the docs were read in."""
    out = []
    for q in ds_points or ():
        try:
            t, px, liq = q[0], q[1], q[2]
        except (TypeError, IndexError, KeyError):
            continue
        t = num(t)
        if t is not None:
            out.append((t, num(px), num(liq)))
    key = lambda v: -1.0 if v is None else v
    return sorted(out, key=lambda q: (q[0], key(q[1]), key(q[2])))


def _rows(cands):
    """Candles as [ms, open, high, low, close, volume or None], positive finite closes only, oldest first."""
    out = []
    for c in cands or ():
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        t, cl = num(c[0]), num(c[4])
        if t is None or not cl or cl <= 0:
            continue
        vol = num(c[5]) if len(c) > 5 else None
        out.append([int(t), num(c[1]), num(c[2]), num(c[3]), cl, vol])
    out.sort(key=lambda c: c[0])
    return out


def peak_of(cands, entry_at, end, px, rug_ok_at=None, ds_points=(), liq0=None, mc0=None, res=1, levels=None):
    """The best confirmed close of a pool inside [entry_at, end] after the glitch filter, relative to the entry, and the close at
    the end. Pure: no clock, no files.

    cands: candles [ms, open, high, low, close, volume] (any order; volume None = unknown: not dust, but no support either).
    px: the entry price the paper account paid (DexScreener). rug_ok_at: okAt of a rug exit (ms) or None. ds_points: DexScreener
    observations of the same pool [(ms, priceUsd or None, liquidityUsd or None)]; a point with liquidity 0 and no price is a pool
    found gone. liq0, mc0: liquidity and market cap at the entry. res: the candles' minutes (1, or 15 for GT's 15-minute candles).
    Candles after the end are used only to see whether a low close at the very end recovered (up to SETTLE_MS after the end: what
    the fetch asks for), never as a level or as the value at 6 h.
    levels: a list that gets every level the filter accepted, in time order, as (ms, level relative to base) (the entry not among
    them): radar_paper.py's take-profit is the first of them at 11x or more. The result does not depend on it.
    -> {"state": "ok" | "unit" | "waiting" (no candle inside the window), "res", "px", "cpx", "base", "x", "at", "rawX", "x6",
        "lo", "loAt", "dead": None | {"at", "why"}, "cut": [...], "n"}"""
    R = int(res or 1) * MIN
    rows = _rows(cands)
    win = [c for c in rows if c[0] >= entry_at - R and c[0] + R <= end]
    out = {"state": "waiting", "res": int(res or 1), "px": num(px), "cpx": None, "base": None, "x": None, "at": None, "rawX": None,
           "x6": None, "lo": None, "loAt": None, "dead": None, "cut": [], "n": len(win)}
    if not win:
        return out
    cpx = win[0][4]
    pxn = num(px)
    base = max(cpx, pxn) if pxn and 1.0 / 3 <= pxn / cpx <= 3.0 else cpx
    out.update(cpx=cpx, base=base, rawX=sig(max(c[4] for c in win) / base))
    pts = _points(ds_points)
    cut_dead, cut_coll, dust, unconf, n_jump, n_cap = [], [], [], [], 0, 0
    dead = dead_of(entry_at, end, rug_ok_at, pts, liq0)
    if dead:
        cut_dead.append(dead[2])
    live = [c for c in win if dead is None or c[0] < dead[0]]
    reach = [c for c in rows if c[0] >= win[0][0] and c[0] <= end + SETTLE_MS and (dead is None or c[0] < dead[0])]
    clean = lambda c: c[5] is None or c[5] >= DUST_VOL
    first = cpx / base
    gap = max(CONFIRM_MIN, int(res or 1)) * MIN

    def supported(i, lv, t):
        run = live[i:i + CAP_RUN]
        if len(run) == CAP_RUN and all(d[4] / base >= lv / 2 and d[5] is not None and d[5] >= CAP_VOL for d in run):
            return True
        return any(liq is not None and liq >= CAP_LIQ and p and p / base >= lv / 3 and abs(tt - t) <= CAP_NEAR_MIN * MIN for tt, p, liq in pts)

    best, best_t, prev, coll = 0.0, None, None, None
    held = [(win[0][0], first)]         # the accepted levels with their minutes; the entry counts as the first

    def level_now(t):
        """The level the pool held up to t: the best accepted level of the last RECOVER_MIN minutes, else the latest one."""
        recent = [lv for tt, lv in held if t - tt <= RECOVER_MIN * MIN]
        return max(recent) if recent else held[-1][1]

    for i, c in enumerate(live):
        x = c[4] / base
        ref = level_now(c[0])
        if x < COLLAPSE * ref:          # 3. a collapse: the liquidity was pulled unless a later close recovers within 30 minutes
            back = [d for d in reach if c[0] < d[0] <= c[0] + RECOVER_MIN * MIN and d[4] / base >= RECOVER * ref
                    and (clean(d) or d[4] / base <= RECOVER_DUST_X * ref)]
            if not back:
                coll = c[0]
                cut_coll.append("collapse: under %d%% at minute %d, no recovery within %d min" % (round(100 * COLLAPSE), (c[0] - entry_at) // MIN, RECOVER_MIN))
                break
        if not clean(c):                # 4. dust
            if x > 1.5 * max(best, first):
                dust.append((x, c[5]))
            continue
        nxt = next((d for d in live[i + 1:] if clean(d)), None)
        if nxt is None or nxt[0] - c[0] > gap:   # 5. nothing confirms this close
            if x > 1.5 * max(best, first):
                unconf.append(x)
            prev = x
            continue
        lv = min(x, nxt[4] / base)
        if x > 1.5 * lv and x > 1.5 * max(best, first):
            unconf.append(x)
        if lv > best:
            jump = prev is not None and lv > JUMP_X * max(prev, best)
            big = lv > CAP_X or (num(mc0) and num(mc0) * lv > MAX_MC)
            if (jump or big) and not supported(i, lv, c[0]):   # 6. jump or cap without support
                if big:
                    n_cap += 1
                else:
                    n_jump += 1
                prev = x
                continue
            best, best_t = lv, c[0]
        held.append((c[0], lv))
        prev = x
    if levels is not None:
        levels.extend(held[1:])
    if coll is not None and (dead is None or coll < dead[0]):
        dead = (coll, "collapse", "")
    shown = [c for c in live if coll is None or c[0] < coll]
    if best_t is None:                  # no confirmed level: the first close (about the entry) is the best
        best, best_t = first, win[0][0]
    t6 = None
    if dead is not None and dead[0] <= end:
        x6 = 0.0
    else:                               # the last close on real volume, lowered (never raised) by a later dust print
        full = [c for c in shown if clean(c)]
        x6 = min(full[-1][4], shown[-1][4]) / base if full else None
        t6 = (shown[-1] if shown[-1][4] <= full[-1][4] else full[-1])[0] if full else None
    if x6 is not None and t6 is not None and x6 > best:
        # the value at 6 h is a price inside the window too, so the best within 6 h is never below it (the last close has no next
        # close to confirm it, so the loop never took it as a level); a jump or a cap level at the very end still needs support
        big = x6 > CAP_X or (num(mc0) and num(mc0) * x6 > MAX_MC)
        if not ((x6 > JUMP_X * max(best, first) or big) and not supported(len(live) - 1, x6, t6)):
            best, best_t = x6, t6
    if dead is not None and dead[0] <= end:     # a pool that died inside the window is a real loss: everything, at the time it died
        lo, lo_t = 0.0, dead[0]
    else:
        lo, lo_t = low_of(shown, base, first if clean(win[0]) else 1.0, win[0][0], gap, clean)
        if x6 is not None and x6 < lo:          # the value at 6 h is a price inside the window too
            lo, lo_t = x6, t6
    cut = cut_dead + cut_coll
    if dust:
        x_, v_ = max(dust)
        cut.append("dust: %s on %s volume%s" % (mult_text(x_), money(v_ or 0.0), (" (%d candles)" % len(dust)) if len(dust) > 1 else ""))
    if unconf:
        cut.append("unconfirmed: %s held for one candle only%s" % (mult_text(max(unconf)), (" (%d times)" % len(unconf)) if len(unconf) > 1 else ""))
    if n_jump:
        cut.append("jump: %d level%s over %gx the previous close without support" % (n_jump, "" if n_jump == 1 else "s", JUMP_X))
    if n_cap:
        cut.append("cap: %d level%s over %gx or a $%gM market cap without support" % (n_cap, "" if n_cap == 1 else "s", CAP_X, MAX_MC / 1e6))
    out.update(state="ok", x=sig(best), at=int(max(best_t, entry_at)), x6=sig(x6) if x6 is not None else None,
               lo=sig(lo), loAt=int(max(lo_t, entry_at)), dead={"at": int(dead[0]), "why": dead[1]} if dead is not None and dead[0] <= end else None, cut=cut)
    for tt, p, liq in pts:              # 7. the candles' scale against a liquid DexScreener price of the same minutes
        if liq is None or liq < CAP_LIQ or not p or not (entry_at <= tt <= end) or (dead is not None and tt >= dead[0]):
            continue
        near = [c for c in win if abs(c[0] - tt) <= 2 * R]
        if near:
            c = min(near, key=lambda c: abs(c[0] - tt))
            r = c[4] / p
            if not (1.0 / UNIT_X <= r <= UNIT_X):
                out.update(state="unit", x=None, at=None, x6=None, lo=None, loAt=None)
                out["cut"] = cut + ["unit: candles %s away from DexScreener's price at minute %d" % (mult_text(max(r, 1 / r)), (tt - entry_at) // MIN)]
                break
    return out


def low_of(cands, base, entry_lv, entry_t, gap, clean):
    """The lowest level a pool held (relative to base) and its minute: (lo, ms). Closes only; a candle that is not clean (dust) is no
    price; a close that the next clean close within gap (ms) took back counts only down to that next close (one glitch print is no
    low); a close that no clean close followed within gap stands (the price stayed there until the next trade). The entry level
    (entry_lv at entry_t) counts first, so the low is never above it. Pure."""
    lo, lo_t = entry_lv, entry_t
    cl = [c for c in cands if clean(c)]
    for j, c in enumerate(cl):
        lv = c[4] / base
        nxt = cl[j + 1] if j + 1 < len(cl) else None
        if nxt is not None and nxt[0] - c[0] <= gap:
            lv = max(lv, nxt[4] / base)
        if lv < lo:
            lo, lo_t = lv, c[0]
    return lo, lo_t


def filtered_text(doc):
    """The page's "filtered" chip for a memepeak doc, e.g. "59,257x ignored: pool dead" (the raw best close and the first rule that
    fired), or "" when no filter lowered the result: nothing cut, nothing booked (unit, waiting), or the booked multiple within 5%
    of the raw best close."""
    if not isinstance(doc, dict) or not isinstance(doc.get("cut"), list) or not doc["cut"]:
        return ""
    raw, x = num(doc.get("rawX")), num(doc.get("x"))
    if raw is None or x is None or raw <= 1.05 * x:
        return ""
    return "%s ignored: %s" % (mult_text(raw), str(doc["cut"][0]).split(":")[0])


# ---------------------------------------------------------------- what the db holds
def _docs(d, coll):
    """A collection's docs in file name order (glob order differs between machines; nothing may depend on it)."""
    return [doc for _, doc in sorted(M.load_docs(d, coll).items())]


def _list(v):
    return v if isinstance(v, list) else []


def context(d):
    """Everything settle needs from the db, read once: the positions with their exits, paperSince, the memepeak docs, the scan
    times (memeruns), the DexScreener points of the spotter's record (memeearly) and of the open positions (marks.json), and the
    tip record's docs (memeyoung for new launches, memerec for top picks) by run time. A doc or field of an unexpected shape is
    skipped, never fatal."""
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {})
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {})
    runs = sorted(int(t) for t in (num(doc.get("t")) for doc in _docs(d, "memeruns")) if t)
    early = {}
    for doc in _docs(d, "memeearly"):
        t0 = num(doc.get("at")) or num(doc.get("t"))
        for c in _list(doc.get("coins")):
            if not isinstance(c, dict) or not isinstance(c.get("addr"), str) or not c["addr"]:
                continue
            pair = c.get("pair")
            if pair is not None and not isinstance(pair, str):
                continue
            pts = [(t0, num(c.get("px")), num(c.get("liq")))] if t0 else []
            pts += [(num(o.get("t")), num(o.get("px")), num(o.get("liq"))) for o in (c.get(k) for k in ("p2", "p60")) if isinstance(o, dict) and num(o.get("t"))]
            early.setdefault(c["addr"], []).append((pair, pts))
    tips = {}
    for coll in ("memeyoung", "memerec"):
        for doc in _docs(d, coll):
            t0 = num(doc.get("t"))
            if t0:
                tips.setdefault((coll, int(t0)), []).append(doc)
    return {"pos": M.positions(d), "since": num((state if isinstance(state, dict) else {}).get("paperSince")), "docs": M.load_docs(d, "memepeak"),
            "runs": runs, "early": early, "tips": tips, "marks": marks if isinstance(marks, dict) else {}}


def rug_ok_at(ctx, p):
    """okAt of the position's rug exit: the time of the latest scan (db/memeruns) before it, never before the entry; None without one."""
    rugs = [num(e.get("t")) for e in _list(p.get("_exits")) if isinstance(e, dict) and e.get("why") == "rug" and num(e.get("t"))]
    if not rugs:
        return None
    t_rug = min(rugs)
    ok = max([t for t in ctx["runs"] if t < t_rug] or [None], key=lambda v: v or 0)
    return max(int(ok or 0), window(p)[0])


def _tip_picks(doc, p):
    """The pick of the position's coin in a tip doc and its result rows per check key: (pick, {key: result})."""
    picks = [q for q in _list(doc.get("picks")) if isinstance(q, dict)]
    mine = [q for q in picks if q.get("addr") == p.get("addr") and (not q.get("pair") or not p.get("pair") or q.get("pair") == p.get("pair"))]
    if not mine:
        return None, {}
    q = mine[0]
    priced = [x for x in picks if num(x.get("px"))]
    outs = {}
    checks = dict(doc.get("outs") or {}) if isinstance(doc.get("outs"), dict) else {}
    if isinstance(doc.get("out"), dict):
        checks["out"] = doc["out"]
    for k, v in checks.items():
        res = [o for o in _list(v.get("picks")) if isinstance(o, dict)] if isinstance(v, dict) else []
        if len(res) == len(priced) and q in priced:            # the results follow the priced picks in order
            o = res[priced.index(q)]
        else:                                                  # else by symbol, only when it is unique in the doc
            same = [o for o in res if o.get("sym") == q.get("sym")]
            o = same[0] if len(same) == 1 and sum(1 for x in picks if x.get("sym") == q.get("sym")) == 1 else None
        if o is not None and o.get("sym") == q.get("sym"):
            outs[k] = (num(v.get("t")), o)
    return q, outs


def ds_for(ctx, pid, p):
    """The DexScreener points of the position's pool: the spotter's record (list time, +2 min, +60 min), the last marks, and the
    tip record's checks that found the coin gone (liquidity 0)."""
    pts, addr = [], p.get("addr")
    for pair, ps in ctx["early"].get(addr, []) if isinstance(addr, str) else []:
        if not pair or not p.get("pair") or pair == p.get("pair"):
            pts += ps
    mk = ctx["marks"]
    mpx, mliq = (mk.get(k) if isinstance(mk.get(k), dict) else {} for k in ("px", "liq"))
    if num(mpx.get(pid)) and num(mk.get("t")):
        pts.append((num(mk["t"]), num(mpx[pid]), num(mliq.get(pid))))
    for docs in ctx["tips"].values():
        for doc in docs:
            _, outs = _tip_picks(doc, p)
            pts += [(t, None, 0.0) for t, o in outs.values() if t and o.get("gone") is True]
    return pts


def paths_for(ctx, p):
    """The tip record's stored candle paths of the same coin and run (memeyoung for a new launch, memerec for a top pick), as
    absolute candles: [(res, [[ms, o, h, l, c, None], ...]), ...]. A path is [[minutes after the tip, o, h, l, c], ...] relative
    to the tip's price."""
    out = []
    coll = "memeyoung" if p.get("grp") == "young" else "memerec"
    t = num(p.get("t"))
    for doc in ctx["tips"].get((coll, int(t or 0)), []):
        q, outs = _tip_picks(doc, p)
        px0 = num((q or {}).get("px"))
        if not px0:
            continue
        for k, (_, o) in sorted(outs.items()):
            path = [[num(v) for v in r[:5]] for r in _list(o.get("path")) if isinstance(r, list) and len(r) >= 5 and all(num(v) is not None for v in r[:5])]
            if len(path) < 2:
                continue
            step = min(b[0] - a[0] for a, b in zip(path, path[1:])) or 1
            res = 15 if step >= 10 else 1
            out.append((res, [[int(t + r[0] * MIN), r[1] * px0, r[2] * px0, r[3] * px0, r[4] * px0, None] for r in path]))
    return out


def priced(p):
    """Whether a position gets its best within 6 h: every paper position, the ones bought before the restart too (the user asked for
    them; the page shows them apart, outside the account since the restart)."""
    return isinstance(p, dict) and p.get("grp") in M.PAPER_GROUPS


def items(d, now, ctx=None):
    """The windows to price this run: paper positions (priced(): since the restart and before it) whose window has closed, without a settled doc (ok, est, unit of this
    PEAK_V) and with fewer than MAX_TRIES empty fetches; up to RECENT_N that closed in the last RECENT_H hours first, then the
    backlog oldest first; at most PEAK_MAX_ITEMS. -> [{"pid", "pool", "key", "entryAt", "end", "tries"}]"""
    ctx = ctx or context(d)
    todo = []
    for pid, p in ctx["pos"].items():
        if not priced(p):
            continue
        entry, end = window(p)
        if not entry or now < end + SETTLE_MS:
            continue
        doc = ctx["docs"].get(pid)
        same_v = isinstance(doc, dict) and doc.get("v") == PEAK_V
        if same_v and doc.get("state") in SETTLED:
            continue
        tries = int(num(doc.get("tries")) or 0) if same_v else 0
        if tries >= MAX_TRIES:
            continue
        todo.append({"pid": pid, "pool": str(p.get("pair") or ""), "key": pool_key(p), "entryAt": entry, "end": end, "tries": tries})
    todo.sort(key=lambda it: (it["end"], it["pid"]))
    recent = [it for it in todo if now - it["end"] <= RECENT_H * 3_600_000][:RECENT_N]
    first = {it["pid"] for it in recent}
    return (recent + [it for it in todo if it["pid"] not in first])[:PEAK_MAX_ITEMS]


# ---------------------------------------------------------------- GeckoTerminal
def gt_before(end):
    """The before_timestamp (epoch s) asked for a window that ends at end (ms): 2 minutes past it."""
    return int(end // 1000) + 120


def gt_url(pool, end, agg=1):
    lim = 400 if agg == 1 else 30
    return F.GT + "/networks/solana/pools/%s/ohlcv/minute?aggregate=%d&limit=%d&before_timestamp=%d&currency=usd&token=base" % (
        urllib.parse.quote(str(pool), safe=""), agg, lim, gt_before(end))


def ohlcv_rows(j, before=None, agg=1):
    """GeckoTerminal's OHLCV answer -> [[ms, o, h, l, c, vol], ...] oldest first; [] when it holds no candle (or only closes of 0);
    None when it is not the expected shape: no ohlcv_list, or a non-empty one in which no row is a list [seconds, o, h, l, c, vol]
    with a close that is a number (rows as objects, timestamps in ms or as text, closes null or text such as "1e-05 USD"). Only the
    structure decides, never a close's value: a close of 0 is a number, so a pool whose closes are all 0 is an answer, not a changed
    shape. A timestamp counts as seconds from 1e9 up to before (epoch s, the request's before_timestamp) plus one candle of agg
    minutes, or below 1e10 without before; a row outside that is not read."""
    if not isinstance(j, dict):
        return None
    lst = ((j.get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(j.get("data"), dict) else None
    if not isinstance(lst, list):
        return None
    hi = before + agg * 60 if before else 1e10
    good = [c for c in lst if isinstance(c, list) and len(c) >= 5 and 1e9 <= (num(c[0]) or 0) <= hi and num(c[4]) is not None]
    if lst and not good:
        return None
    return _rows([[num(c[0]) * 1000] + list(c[1:6]) for c in good])


def covers(rows, entry_at, res):
    """Whether candles reach back to the entry (within COVER_MIN minutes after it): a cut history gives no result."""
    return bool(rows) and rows[0][0] <= entry_at + COVER_MIN.get(res, 10) * MIN


class _Late(Exception):
    """The deadline passed while an answer was still coming in."""


def _read(r, until):
    """The whole answer, a chunk at a time, cut off at the deadline: a server that sends its answer a few bytes at a time cannot
    hold the run past it (the socket timeout only bounds the wait for each chunk)."""
    out = bytearray()
    while True:
        if time.time() > until:
            raise _Late()
        b = r.read1(65536)
        if not b:
            return bytes(out)
        out += b
        if len(out) > MAX_ANSWER:
            raise ValueError("answer over %d bytes" % MAX_ANSWER)


def gt_get(http, u, until):
    """One GeckoTerminal request on fetch.Http's pacing (10 s gap, cooldowns, circuit breaker) inside the deadline (epoch s).
    -> (status, json): "ok"; "empty" (404/410: the pool is unknown); "error" (this window failed: a 5xx, a timeout, another HTTP
    error, or 429s through the whole GT_429_LADDER_S); "shape" (an answer that is not JSON: a block or maintenance page);
    "limited" (429s used up for this run: fetch.Http gives the host up); "dead" (the host was given up before: three 5xx, timeouts
    or 401/403/451 in a row, a changed shape, or the 429s); "deadline" (not enough time left for this request or its answer).
    A 5xx or a timeout counts as a hard failure of the host (three in a row and it is off for the run), as a 401/403/451 does."""
    host = urllib.parse.urlsplit(u).netloc
    ladder = tuple(GT_429_LADDER_S)
    for i in range(len(ladder) + 1):
        if host in http.dead:
            return "dead", None
        gap = 0.0 if http.mock else F.HOST_GAP.get(host, 0.0)
        wait = max(http.cooldown.get(host, 0) - time.time(), (http.last_at[host] + gap - time.time()) if host in http.last_at else 0.0, 0.0)
        if time.time() + wait + MIN_REQ_S > until:
            return "deadline", None
        http._pace(host)
        left = until - time.time()
        if left < MIN_REQ_S:
            return "deadline", None
        try:
            req = urllib.request.Request(http.url(u), headers={"User-Agent": F.UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=min(F.TIMEOUT, left)) as r:
                raw = _read(r, until)
            with http.lock:
                http.fails[host] = 0
            try:
                return "ok", json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return "shape", None
        except _Late:
            return "deadline", None
        except urllib.error.HTTPError as e:
            if e.code == 429:            # WP0's ladder: wait 15, 30, then 60 s and ask again; 8 in a run and fetch.Http gives the host up
                if http._limited(host):
                    return "limited", None
                pause = ladder[min(i, len(ladder) - 1)] if ladder else 0
                with http.lock:
                    http.cooldown[host] = time.time() + pause
                if i >= len(ladder):
                    http.log("  ! 429 rate limited by %s %d times for one window: it waits for a later run, the next window waits %ds" % (host, i + 1, pause))
                    return "error", None
                http.log("  ! 429 rate limited by %s, waiting %ds" % (host, pause))
                if time.time() + pause + MIN_REQ_S > until:
                    return "deadline", None
                time.sleep(pause)
                continue
            if e.code in (404, 410):     # a proper answer of a working host: the run of hard failures starts again
                with http.lock:
                    http.fails[host] = 0
                return "empty", None
            http.log("  ! %s from %s" % (e.code, host))
            if e.code in (401, 403, 451) or e.code >= 500:
                http._fail(host, hard=True)
            return "error", None
        except Exception as e:      # timeout, refused, reset, an answer too big
            if until - time.time() < MIN_REQ_S:
                return "deadline", None
            http.log("  ! %s %s" % (type(e).__name__, host))
            http._fail(host, hard=True)
            return "error", None
    return "error", None


def write_candles(d, pool, key, rows):
    os.makedirs(os.path.join(d, "candles"), exist_ok=True)
    with open(os.path.join(d, "candles", "%s_%s.txt" % (safe_pool(pool), key)), "w", encoding="utf-8") as f:
        f.write("\n".join(F.row(int(c[0]), c[1], c[2], c[3], c[4], c[5]) for c in rows) + "\n")


def load_candles(d, pool, key):
    """candles/<pool>_pk<minute>.txt -> [[ms, o, h, l, c, vol or None], ...] (memebot.load_candles drops the volume)."""
    out = []
    try:
        with open(os.path.join(d, "candles", "%s_%s.txt" % (safe_pool(pool), key)), encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 5:
                    out.append([num(x) for x in parts[:6]] + ([None] if len(parts) < 6 else []))
    except OSError:
        pass
    return _rows(out)


def fetch(http, d, items_, until, done=None):
    """GeckoTerminal minute candles for each window, one after another on fetch.Http (10 s apart), until the deadline (epoch s):
    candles/<pool>_pk<entry minute>.txt rows ms|o|h|l|c|vol. An empty answer (or one that does not reach back to the entry) is
    asked once more as 15-minute candles. Two windows of one pool with the same entry minute share one request (done: the answers
    so far, shared between calls of one run). An answer that is not GeckoTerminal's OHLCV shape (a block page, a changed API,
    candle rows it cannot read) before any answer of the run was readable switches GeckoTerminal off for the run, logged once; that
    window gets no result (SPEC 10: the first answer of each run). After a readable answer, one such answer is a failed fetch of
    that window (one pool answered oddly; the run goes on), and the third in a row switches GeckoTerminal off.
    -> ({pid: {"status": "ok" | "empty" | "error" | "nopool", "res", "key", "n"}}, why the loop ended)"""
    fetched, why = {}, "all asked"
    done = {} if done is None else done
    for it in items_:
        pid, pool, key = it["pid"], it["pool"], it["key"]
        if not pool:
            fetched[pid] = {"status": "nopool", "key": key}
            continue
        if (pool, key) in done:
            fetched[pid] = dict(done[(pool, key)])
            continue
        if GT_HOST in http.dead:
            why = GT_GONE
            break
        info, stop = None, None
        for agg in (1, 15):
            st, j = gt_get(http, gt_url(pool, it["end"], agg), until)
            if st in ("deadline", "limited", "dead"):
                stop = {"deadline": "deadline", "limited": "GeckoTerminal rate limit", "dead": GT_GONE}[st]
                break
            rows = ohlcv_rows(j, gt_before(it["end"]), agg) if st == "ok" else []
            if st == "shape" or (st == "ok" and rows is None):
                what = "with something that is not JSON" if st == "shape" else "without an ohlcv_list of [seconds, o, h, l, c, vol] rows"
                http.gt_odd = getattr(http, "gt_odd", 0) + 1
                if not getattr(http, "gt_read", False) or http.gt_odd >= 3:
                    http.log("  ! GeckoTerminal answered %s: off for the rest of this run" % what)
                    with http.lock:
                        http.dead.add(GT_HOST)
                    stop = GT_SHAPE
                    break
                http.log("  ! GeckoTerminal answered one pool %s: that window waits for a later run" % what)
                info = {"status": "error", "key": key}
                break
            if st == "ok":
                http.gt_read, http.gt_odd = True, 0
            if st == "error":
                info = {"status": "error", "key": key}
                break
            if covers(rows, it["entryAt"], agg):
                write_candles(d, pool, key, rows)
                info = {"status": "ok", "res": agg, "key": key, "n": len(rows)}
                break
            info = {"status": "empty", "key": key}
        if stop:
            why = stop
            break
        done[(pool, key)] = info
        fetched[pid] = dict(info)
    return fetched, why


# ---------------------------------------------------------------- the docs
def book(d, ctx, pid, p, info, now, old=None):
    """The memepeak doc of one position from this run's fetch result (and the doc before it, for tries); None when nothing was
    learned: a failed fetch of a window under EST_AFTER_H past its end (its doc, if any, stays), or no result at all. A failed fetch
    never settles a window at once: past EST_AFTER_H it counts as a try (a waiting doc), and the estimate comes after MAX_TRIES.
    A settled doc of an older PEAK_V is never made worse (keep_better)."""
    return keep_better(_book(d, ctx, pid, p, info, now, old), old, p, now)


def _book(d, ctx, pid, p, info, now, old=None):
    entry, end = window(p)
    same_v = isinstance(old, dict) and old.get("v") == PEAK_V
    tries = int(num((old or {}).get("tries")) or 0) if same_v else 0
    doc = {"v": PEAK_V, "pos": pid, "grp": p.get("grp"), "sym": p.get("sym"), "addr": p.get("addr"), "pair": p.get("pair"),
           "ticket": num(p.get("ticket")), "t": num(p.get("t")), "entryAt": entry, "end": end, "upd": int(now)}
    rug = rug_ok_at(ctx, p)
    ds = ds_for(ctx, pid, p)
    px, liq0, mc0 = num(p.get("px")), num(p.get("liq")), num(p.get("mc"))
    status = (info or {}).get("status")
    old_w = now >= end + EST_AFTER_H * 3_600_000
    if status not in ("ok", "empty", "nopool", "error") or (status == "error" and not old_w):
        return None                                        # nothing learned: the doc (if any) stays as it is
    if status == "ok":
        r = peak_of(load_candles(d, p.get("pair"), info["key"]), entry, end, px, rug, ds, liq0=liq0, mc0=mc0, res=info.get("res") or 1)
        if r["state"] in ("ok", "unit"):
            return _finish(doc, p, r, src="m15" if r["res"] == 15 else "m1", tries=tries)
        status = "empty"                                   # candles, but none inside the window
    tries = MAX_TRIES if status == "nopool" else tries + 1   # an old window's failed fetch counts as a try: an outage never estimates it at once
    if tries >= MAX_TRIES or (old_w and status == "empty"):
        return estimate(doc, ctx, p, rug, ds, tries)
    return _finish(doc, p, {"state": "waiting", "res": None, "px": px, "cpx": None, "base": None, "x": None, "at": None, "rawX": None,
                            "x6": None, "lo": None, "loAt": None, "dead": None, "cut": [], "n": 0}, src=None, tries=tries)


def keep_better(new, old, p, now):
    """The doc to write when an older PEAK_V's settled doc exists: the new one when its source is as good (SRC_RANK: minute candles,
    15-minute candles, estimate); None (the old doc stays, asked again next run) when the new one is only waiting; else the old doc's
    best, value at 6 h and everything else, in this version, with this run's low rebased onto the old doc's base (the price, not the
    multiple, is what this run learned), never above the old doc's entry level or its value at 6 h, and 0 when it found the pool dead;
    an old best below the old value at 6 h (a pool alive at the end) is raised to it. Any other case: new as it is."""
    if new is None or not isinstance(old, dict) or old.get("v") == PEAK_V or old.get("state") not in SETTLED:
        return new
    rank = lambda doc: SRC_RANK.get(doc.get("src"), 0) if doc.get("state") in SETTLED else 0
    if rank(new) >= rank(old):
        return new
    if new.get("state") not in SETTLED:
        return None
    out = {k: old.get(k) for k in DOC_KEYS}
    out.update({k: new.get(k) for k in ("v", "pos", "grp", "sym", "addr", "pair", "ticket", "t", "entryAt", "end", "upd")})
    ox, ox6 = num(old.get("x")), num(old.get("x6"))
    if ox is not None and ox6 is not None and ox6 > ox and not old.get("dead"):   # an older doc's best below its value at 6 h: at least that
        out.update(x=ox6, at=out.get("end") or old.get("at"), eur=round(M.pos_value(p, 1.0, ox6), 2))
    lo, lo_t = None, None
    nb, ob = num(new.get("base")), num(old.get("base"))
    if num(new.get("lo")) is not None and nb and ob and old.get("state") in ("ok", "est") and num(old.get("x")) is not None:
        lo, lo_t = num(new["lo"]) * nb / ob, num(new.get("loAt"))
        top = num(old.get("cpx")) / ob if num(old.get("cpx")) else 1.0
        if top < lo:
            lo, lo_t = top, num(old.get("entryAt"))
        if num(old.get("x6")) is not None and num(old["x6"]) < lo:
            lo, lo_t = num(old["x6"]), num(old.get("end"))
        dead = old.get("dead") if isinstance(old.get("dead"), dict) else None
        if dead and num(dead.get("at")) is not None:
            lo, lo_t = 0.0, num(dead["at"])
    out.update(lo=sig(lo) if lo is not None else None, loAt=int(lo_t) if lo is not None and lo_t is not None else None,
               eurLo=round(M.pos_value(p, 1.0, lo), 2) if lo is not None else None)
    return {k: out.get(k) for k in DOC_KEYS}


def _finish(doc, p, r, src, tries):
    booked = r["state"] in ("ok", "est")
    x, x6, lo = (r.get("x"), r.get("x6"), r.get("lo")) if booked else (None, None, None)
    doc.update({"state": r["state"], "src": src, "res": r.get("res") if src in ("m1", "m15") else None, "tries": tries,
                "px": num(p.get("px")), "cpx": r.get("cpx"), "base": r.get("base"), "x": x, "at": r.get("at") if booked else None,
                "rawX": r.get("rawX"), "x6": x6, "eur": round(M.pos_value(p, 1.0, x), 2) if x is not None else None,
                "eur6": round(M.pos_value(p, 1.0, x6), 2) if x6 is not None else None, "lo": lo, "loAt": r.get("loAt") if lo is not None else None,
                "eurLo": round(M.pos_value(p, 1.0, lo), 2) if lo is not None else None, "dead": r.get("dead"), "cut": list(r.get("cut") or [])[:8],
                "n": int(r.get("n") or 0)})
    return {k: doc.get(k) for k in DOC_KEYS}


def estimate(doc, ctx, p, rug, ds, tries):
    """A lower bound without minute candles of our own (state est): the entry itself (1.0x), a take-profit exit (11x at its
    minute), the tip record's stored closes of the same coin and run (rebased to the entry, through the same filter); x6 from a
    dead pool (0), a time exit (its multiple) or a stored path that reaches the end. The low is an upper bound of the real one: the
    entry (1.0x), the stored paths' lows, the price of every paper exit and every DexScreener point inside the window (before the
    pool died), x6, and 0 when the pool died inside the window."""
    entry, end = window(p)
    px, liq0, mc0 = num(p.get("px")), num(p.get("liq")), num(p.get("mc"))
    dead = dead_of(entry, end, rug, ds, liq0)
    x, at, raw, cut, n, x6, x6_at = 1.0, entry, None, [], 0, None, end
    lo, lo_at = 1.0, entry
    for res, cs in paths_for(ctx, p):
        r = peak_of(cs, entry, end, px, rug, ds, liq0=liq0, mc0=mc0, res=res)
        if r["state"] != "ok" or not px or not (1.0 / 3 <= px / r["cpx"] <= 3.0):
            continue            # no stored close inside the window, or the path is in another unit than the entry price
        n += r["n"]
        raw = max(raw or 0.0, r["rawX"] or 0.0) or None
        cut += [c for c in r["cut"] if c not in cut]
        if r["dead"] and (dead is None or r["dead"]["at"] < dead[0]):
            dead = (r["dead"]["at"], r["dead"]["why"], "")
        if r["x"] is not None and r["x"] > x:    # relative to max(cpx, px) >= px: a lower bound, never flattering
            x, at = r["x"], r["at"]
        if r["lo"] is not None and r["lo"] < lo:
            lo, lo_at = r["lo"], r["loAt"]
        last = [c for c in _rows(cs) if c[0] + res * MIN <= end]
        if r["x6"] is not None and last and last[-1][0] + res * MIN >= end - 30 * MIN:
            x6, x6_at = r["x6"], last[-1][0]
    for e in _list(p.get("_exits")):
        if not isinstance(e, dict):
            continue
        t_e = num(e.get("at")) or num(e.get("t"))
        if e.get("why") == "tp" and t_e and (dead is None or t_e < dead[0]) and TP_X > x:
            x, at = TP_X, int(t_e)
        if e.get("why") == "time" and px and num(e.get("px")) is not None and x6 is None:
            x6, x6_at = num(e["px"]) / px, int(t_e or end)
        if px and num(e.get("px")) is not None and t_e and entry <= t_e <= end and (dead is None or t_e < dead[0]) and num(e["px"]) / px < lo:
            lo, lo_at = num(e["px"]) / px, int(t_e)
    for t_p, p_p, _ in _points(ds):             # DexScreener's prices of the pool inside the window
        if px and p_p and entry <= t_p <= end and (dead is None or t_p < dead[0]) and p_p / px < lo:
            lo, lo_at = p_p / px, int(t_p)
    if x6 is not None and x6 < lo:
        lo, lo_at = x6, end
    if dead is not None and dead[0] <= end:
        x6 = 0.0
        lo, lo_at = 0.0, int(dead[0])
        if dead[2] and dead[2] not in cut:
            cut.insert(0, dead[2])
    elif x6 is not None and x6 > x:             # the value at 6 h is a price inside the window: the best is never below it
        x, at = x6, int(min(max(x6_at, entry), end))
    r = {"state": "est", "res": None, "cpx": None, "base": px, "x": sig(max(1.0, x)), "at": int(at), "rawX": sig(raw) if raw else None,
         "x6": sig(x6) if x6 is not None else None, "lo": sig(lo), "loAt": int(max(lo_at, entry)),
         "dead": {"at": int(dead[0]), "why": dead[1]} if dead is not None and dead[0] <= end else None, "cut": cut, "n": n}
    return _finish(doc, p, r, src="est", tries=tries)


def write_doc(d, pid, doc):
    """db/memepeak/<pid>.json, written whole or not at all (a temp file outside the synced folder, then a rename)."""
    tmp_dir, out_dir = os.path.join(d, ".peaktmp"), os.path.join(d, "db", "memepeak")
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(tmp_dir, pid + ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(out_dir, pid + ".json"))


def settle(d, now, fetched, ctx=None):
    """Writes the docs of the windows fetch() asked (a window it did not reach keeps its doc). A settled doc of this PEAK_V is never
    rewritten. -> {"ok", "m15", "est", "unit", "waiting"}: docs written this run by state"""
    ctx = ctx or context(d)
    counts = {"ok": 0, "m15": 0, "est": 0, "unit": 0, "waiting": 0}
    for pid, info in sorted(fetched.items()):
        p = ctx["pos"].get(pid)
        old = ctx["docs"].get(pid)
        if p is None or not priced(p) or (isinstance(old, dict) and old.get("v") == PEAK_V and old.get("state") in SETTLED):
            continue
        doc = book(d, ctx, pid, p, info, now, old)
        if doc is None:
            continue
        write_doc(d, pid, doc)
        ctx["docs"][pid] = doc
        counts["m15" if doc["state"] == "ok" and doc["src"] == "m15" else doc["state"]] += 1
    return counts


def run(d, now, deadline_s=600.0, mock=None, log=None):
    """items -> fetch until the deadline -> settle, the docs written after every SETTLE_EVERY windows. -> the summary dict the CLI
    prints."""
    t0 = time.time()
    log = log or (lambda s: print(s, file=sys.stderr, flush=True))
    ctx = context(d)
    its = items(d, now, ctx)
    counts, why = {"ok": 0, "m15": 0, "est": 0, "unit": 0, "waiting": 0}, "no window to price"
    http = None
    if its:
        http = F.Http(mock, pause=0, log=log)
        log("peaks: %d windows to price (%d closed in the last %g h), deadline %ds" % (
            len(its), sum(1 for it in its if now - it["end"] <= RECENT_H * 3_600_000), RECENT_H, deadline_s))
        done, step = {}, max(1, int(SETTLE_EVERY))
        for k in range(0, len(its), step):
            part, why = fetch(http, d, its[k:k + step], t0 + deadline_s, done)
            for st, n in settle(d, now, part, ctx).items():
                counts[st] += n
            if why != "all asked":
                break
            if k + step < len(its):
                log("  peaks: %d of %d windows asked, their docs written" % (k + step, len(its)))
    out = dict({"items": len(its)}, **counts)
    out["radar"] = radar_account(d, now, http, mock, t0 + deadline_s, log)
    out.update(secs=round(time.time() - t0, 1), why=why)
    log("peaks: %d priced from minute candles, %d from 15-minute candles, %d estimated, %d not booked (unit), %d waiting; %s (%.0f s)" % (
        counts["ok"], counts["m15"], counts["est"], counts["unit"], counts["waiting"], why, out["secs"]))
    return out


def radar_account(d, now, http, mock, until, log):
    """The radar account (radar_paper.py: 3 EUR on each launch-radar round's best 5, sold by the paper rules) on what is left of
    this run's deadline, after the windows above: the same GeckoTerminal client (its 10 s gap, cooldowns and a host given up stay
    in force), at most radar_paper.MAX_ITEMS windows. It never fails this run: an error is logged and returned as {"err"}."""
    try:
        import radar_paper as RP
        return RP.run(d, now, http=http, mock=mock, until=until, log=log)
    except Exception as e:
        log("radar account: not priced this run (%s: %s)" % (type(e).__name__, str(e)[:160]))
        return {"err": type(e).__name__}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the hindsight category: best price within 6 h of every paper position (fake money)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="price the closed 6 h windows and write db/memepeak")
    r.add_argument("--dir", default="mb")
    r.add_argument("--now", type=int, default=None, help="ms; default: the wall clock")
    r.add_argument("--deadline-s", type=float, default=600.0)
    r.add_argument("--mock", default=None, help="rewrite every URL to <mock>/<host>/<path> (selftest)")
    r.add_argument("--max-items", type=int, default=None, help="windows this run may ask for (default PEAK_MAX_ITEMS; the backfill run asks more)")
    a = ap.parse_args(argv)
    if a.max_items and a.max_items > 0:
        global PEAK_MAX_ITEMS
        PEAK_MAX_ITEMS = min(int(a.max_items), 600)
    now = a.now if a.now is not None else int(time.time() * 1000)
    out = run(a.dir, now, a.deadline_s, a.mock)
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
