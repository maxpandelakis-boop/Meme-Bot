#!/usr/bin/env python3
"""exit_grid.py: the exit what-if test of the paper account. Hindsight on past trades, fake money only, a report and nothing else:
nothing here buys, signs or sends anything, and nothing the trader, the training or the big test reads comes from here. The paper
trader keeps its rule (memebot.py PAPER_RULE: -30% stop, 11x take-profit, 6 hours); this file only asks how other stops and targets
would have done on the same trades, measured as honestly as the stored prices allow.

The question: the scan paper account loses money and most new-launch trades end at the -30% stop, often within half an hour. Is the
stop inside normal meme-coin noise (a wider stop or none would have done better), or does it cut real crashes short? A grid of rules
is replayed on every closed paper trade since the restart: stops STOPS x targets TARGETS (None = no stop / no target), each with the
time exit at 6 hours after the entry.

The prices (what is stored on the results branch; the minute candle files are not kept there):
  - the peak doc of the position (db/memepeak/<pid>.json, peak.py, state "ok" with a low, PEAK_V 2): from the pool's minute candles
    over the whole 6 hours, the best close x at "at", the lowest close lo at "loAt", the close at 6 hours x6, and whether and when the
    pool died. Coarse: between those points the replay only knows that every close lay between lo and x.
  - the tip record's candle paths of the same coin and run (memebot.candle_path, kept with the tip's 1 h, 24 h and horizon checks in
    db/memeyoung and db/memerec, linked to the position as peak.paths_for does): one-minute candles for the first hour or two after
    the tip, 15-minute candles to 24 hours. Where a path covers a stretch it replaces the peak doc's coarse bounds there. The peak
    doc's two exact minute closes (its low and its best) stay inside 15-minute candles as well: a candle only bounds its minutes, the
    doc's close at its minute is finer (the candle is split there); inside one-minute candles the path itself is exact.
  - the radar account's priced docs (db/memeradarpaper, radar_paper.py, state "closed"): no low is stored, so its own exit (the same
    paper rule replayed on the candles) is the evidence: no confirmed close at or below 0.70x before it, the exit level at it. An
    estimated one (src "est": no candles, a loss from the radar's own later prices) stays out.
  Estimated peak docs ("est": partly made from the paper exits themselves) and windows in another price unit are left out, unless a
  path covers the whole window. Every group reports how many trades each source covers and why the others stay out.

The replay (memebot.cmd_run / hold_check, the live rule, read off the code): the levels are minute CLOSES against cpx, the first close
at or after the entry minute (never wicks); the first close at 1 - stop or below is a stop, booked at min(close / cpx, 1 - stop) x the
entry price (a crash through the level fills at the crash close, never better); the first close at the target or above (up to
memebot.CANDLE_MAX_X, a glitch above it) is a take-profit booked at exactly the target; else the time exit at 6 hours after the entry
(the peak doc's x6, the last close by 6 hours; a trade with a path only: the last path close by 6 hours), over cpx like the levels;
that last close is a close inside the window too, so one at the target or above (up to CANDLE_MAX_X) is that target's take-profit,
never a sale above it (a best close over CANDLE_MAX_X can hide every earlier crossing, the close at 6 hours still shows one), and one
at the stop or under it after a stretch that allowed the stop is that stop (a radar doc stores no low); a pool that died is worth 0.
The live trader checks the candles every scan (hourly) but books the minute the candle crossed, so the cadence does not move a fill;
only its 6-hour exit is the first scan after 5 h 45 min, at that scan's price (the calibration shows what that costs). The paper fees
are memebot's (pos_value on the position itself: 1% a side, at least 0.10).
Where the stored prices cannot tell the minute (a coarse stretch, inside a 15-minute candle), each trade gets a point estimate and a
range. The range ("lo", "hi") takes every possible stop at the lowest close the stretch allows and skips every possible target (worst
case), or the other way round (best case). The point estimate assumes no crossing until a stored close shows one and fills a stop seen
only coarsely at lo + r x (level - lo), lo being the lowest close the stretch allows; r is fitted on the live rule's own stop sales
(fill_fit: the minute-candle stops of the paper account against their peak doc's low, apart for pools that died), and checked against
the stops a one-minute path shows exactly at every level ("fill"."check" in the doc). A pool found dead by its rug exit (no price any
more) is 0 for every rule, in the range as well: no stop saw a price to sell at.
The order: when a coarse stretch allowed the stop and the next stored close shows the target, the stored prices cannot tell which came
first. The point estimate takes the target (a stored close shows it, the stop only might have been); the stop-first replay
(replay(..., stop_first=True)) takes the stop in every such case, a 15-minute candle that closed at the target with a low under the
stop included. Rules with low targets gain most from that order, so a rule beats the current one only if it does in both.

Calibration: the current rule (CURRENT) is replayed exactly like every other row and set against what the paper account really got
with the same trades ("actual" vs the replay, the gap per trade and per exit reason, how many real results lie inside their replayed
range). Rules are compared with the replayed current rule: the same prices and the same method on both sides.

Honesty: the trades of a group are split by entry time into an older and a newer half. A rule "beats" the current one only when its
result per trade is higher in the older half, in the newer half and overall, with at least MIN_HALF trades in each half (else the
group says "few"), and that holds with every fill model (the fitted one, every coarse stop at its level, every coarse stop at the
lowest close allowed) and with the stop first wherever the order is unclear: a lead that only the fill model or the order makes is no
lead. For the rules shown (up to SHOW_N that beat it, and the no-stop row) a bootstrap over the trades (BOOT_N paired resamples, a
fixed seed) gives a 95% range of the difference per trade. Nothing here is advice: it is hindsight on a sample of past trades.

The doc: db/memebot/exitgrid.json (travels to the results branch with the other db/memebot docs; page_exits.py shows it on the
Account page). {"v", "t", "rule": {"stop", "target", "hours", "text"}, "grid": {"stops", "targets"}, "minHalf", "fill", "time",
"groups": {"young" | "hold" | "radar": {"n", "all", "src", "out", "split", "nOld", "nNew", "actual", "calib", "rows", "cur", "best",
"noStop", "verdict"}}, "secs"}. verdict: "beat" (a rule beat the current one), "none", "few" (a half under MIN_HALF), "empty". A row:
{"stop", "target", "pt" (EUR per trade, fitted fills), "old", "new" (the halves), "atLevel", "atLow" (overall with the other two fill
models), "stopFirst" (overall, fitted fills, the stop first where the order is unclear), "ord" (trades whose result that order
changes), "lo", "hi" (worst and best case per trade), "amb" (trades whose result the stored prices cannot pin down), "why" (exit
counts of the point estimate), "beats"}; "best" and "noStop" rows add "diff" (per trade against the current rule), "ci" (its 95%
range) and "sfDiff" (the difference with the stop first on both sides).

Usage:
  python3 exit_grid.py run --dir mb [--now <ms>]   -> writes db/memebot/exitgrid.json, prints one JSON line; never fails the job
                                                     (an error is logged to stderr, the last good doc stays, exit code 0)
"""
import argparse, json, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: the paper rule, the fees (pos_value), load_docs, in_account
import peak as P         # read only: context (positions, peak docs, tip docs by run), _tip_picks (a position's tip results)

V = 1
MIN, H = 60_000, 3_600_000
DOC = ("db", "memebot", "exitgrid.json")
STOPS = (None, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)      # None: no stop
TARGETS = (2.0, 3.0, 5.0, 11.0, None)                  # multiples of the entry price; None: no target
CURRENT = (M.HOLD_STOP, 1.0 + M.HOLD_TP)               # the rule that really runs: -30%, 11x
WINDOW_MS = int(M.HOLD_MAX_H * H)                      # the time exit: 6 hours after the entry
MIN_HALF = 100           # trades a half needs before a rule can count as better (else "too few")
SHOW_N = 3               # rules shown per group among those that beat the current one
BOOT_N = 400             # bootstrap resamples for the 95% range of the difference per trade
BOOT_SEED = 7
FIT_MIN = 20             # stop sales a fill fraction needs before it replaces its default
FILL_CLASSES = ("alive", "dead", "candle")    # a coarse stop seen by the peak doc's low in a pool that lived, in a pool that died, inside a 15-minute candle
FILL_DEFAULT = {"alive": 1.0, "dead": 0.5, "candle": 0.5}   # without enough sales: at the level, else halfway (a crash or a slide)
FILL_LEVEL = {k: 1.0 for k in FILL_CLASSES}    # every coarse stop at its level (the kindest fill)
FILL_LOW = {k: 0.0 for k in FILL_CLASSES}      # every coarse stop at the lowest close the stored prices allow (the harshest)
CHECK_LEVELS = (0.8, 0.7, 0.6, 0.5)           # the fill check: levels whose crossings a one-minute path shows exactly
GROUPS = ("young", "hold", "radar")
WHYS = ("stop", "tp", "time", "rug")
EPS = 1e-9


def num(v):
    return M.num(v)


def rule_text(stop, target):
    """"-30% stop, 11x" / "no stop, 3x" / "-50% stop, no target": plain words for the run's line."""
    return "%s, %s" % ("no stop" if stop is None else "-%d%% stop" % round(100 * stop), "no target" if target is None else "%gx" % target)


# ---------------------------------------------------------------- the stored prices of one trade
def summary(doc):
    """A memepeak doc reduced to what the replay reads, the levels in multiples of cpx (the live rule's own reference), or None when
    the doc cannot carry a replay: not "ok" (an estimate is partly made from the paper exits themselves, "unit" is another price
    unit, "waiting" has nothing), no low (PEAK_V 1), no cpx or base, or no value at 6 hours in a pool that did not die."""
    if not isinstance(doc, dict) or doc.get("state") != "ok":
        return None
    cpx, base = num(doc.get("cpx")), num(doc.get("base"))
    lo, x, x6 = num(doc.get("lo")), num(doc.get("x")), num(doc.get("x6"))
    lo_t, x_t = num(doc.get("loAt")), num(doc.get("at"))
    if not cpx or not base or cpx <= 0 or base <= 0 or lo is None or x is None or lo_t is None or x_t is None or lo < 0:
        return None
    dead = doc.get("dead") if isinstance(doc.get("dead"), dict) else None
    dead_t = num(dead.get("at")) if dead else None
    if dead_t is None and (x6 is None or x6 < 0):
        return None
    k = base / cpx
    return {"cpx": cpx, "lo": lo * k, "loAt": int(lo_t), "x": x * k, "at": int(x_t), "x6": 0.0 if dead_t is not None else x6 * k,
            "dead": int(dead_t) if dead_t is not None else None, "deadWhy": str(dead.get("why") or "") if dead else "",
            "res": int(num(doc.get("res")) or 1)}


def tip_paths(ctx, p):
    """The tip record's candle paths of the position's coin and run, absolute: ({1: [...], 15: [...]}, {1: (start, end), ...}), the
    candles as (ms, low, high, close) in time order and the stretch each resolution covers. A path covers its check's window from the
    tip (key "1": one hour, "24": a day, "out": up to the check): GeckoTerminal sends no candle for a minute without trades, so inside
    the window the price between two candles is the earlier close (no trade, no crossing). The resolution is the window's, as
    fetch.candles asked for it (one-minute candles up to 3 hours, else 15-minute ones), not the smallest step: a coin that traded
    every 12 minutes still has a one-minute path. A path cut at memebot.PATH_MAX candles covers up to its last candle only."""
    coll = "memeyoung" if p.get("grp") == "young" else "memerec"
    t = num(p.get("t"))
    rows, cover = {1: {}, 15: {}}, {}
    for doc in ctx["tips"].get((coll, int(t or 0)), []):
        q, outs = P._tip_picks(doc, p)
        px0 = num((q or {}).get("px"))
        if not px0:
            continue
        for k, (t_chk, o) in sorted(outs.items()):
            path = sorted(([num(v) for v in r[:5]] for r in (o.get("path") if isinstance(o.get("path"), list) else [])
                           if isinstance(r, list) and len(r) >= 5 and all(num(v) is not None for v in r[:5])), key=lambda r: r[0])
            if len(path) < 2:
                continue
            if min(b[0] - a[0] for a, b in zip(path, path[1:])) <= 0:
                continue
            end = t + 24 * H if k == "24" else (t + H if k == "1" else max(t, num(t_chk) or t))
            res = 1 if end - t <= 3 * H else 15      # fetch.candles: one-minute candles up to a 3-hour window (a sparse path is no 15-minute one)
            if len(path) >= M.PATH_MAX:
                end = min(end, t + (path[-1][0] + res) * MIN)
            if end <= t:
                continue
            for r in path:
                ms = int(t + r[0] * MIN)
                rows[res].setdefault(ms, (ms, r[3] * px0, r[2] * px0, r[4] * px0))
            a, b = cover.get(res, (t, t))
            cover[res] = (min(a, t), max(b, end))
    return {res: sorted(v.values()) for res, v in rows.items()}, cover


def _minus(span, cuts):
    """[a, b) minus the stretches in cuts: what is left, in time order."""
    out = [span]
    for c0, c1 in cuts:
        nxt = []
        for a, b in out:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if a < c0:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        out = nxt
    return [(a, b) for a, b in out if b > a]


def split15(cands, pts):
    """15-minute candles (t0, t1, lo, hi, close) as "m15" atoms, each split at the peak doc's exact closes inside it (pts: (ms, level)):
    the part before a close keeps the candle's bounds but no close (its minutes are not known), the close is a "pt" atom noted "m15"
    (a stop it shows fills like one inside the candle), the last part keeps the candle's close at its end. A close at the candle's
    first minute comes before it whole. A close in no candle (the path had no trade in those minutes) stands alone."""
    out, used = [], set()
    for a0, a1, lo, hi, cl in cands:
        cur = a0
        for t, v in sorted((t, v) for t, v in pts if a0 <= t < a1):
            used.add(t)
            if t > cur:
                out.append((cur, t, lo, hi, None, "m15", ""))
            out.append((t, t, v, v, v, "pt", "m15"))
            cur = t
        out.append((cur, a1, lo, hi, cl, "m15", ""))
    return out + [(t, t, v, v, v, "pt", "") for t, v in pts if t not in used]


def paper_evidence(ctx, pid, p):
    """One closed paper trade as the replay's timeline, or (None, why it stays out).

    The timeline: atoms (t0, t1, lo, hi, close, kind, note) in time order, every level a multiple of cpx:
      "m1"   a one-minute candle: its close is the only minute close (lo = hi = close)
      "m15"  a 15-minute candle (or the part of one before or after a "pt"): every minute close inside lay between its low and high;
             close: the close at its end (None for a part before a "pt")
      "gap"  a stretch no path covers: every close lay between the peak doc's lo and x (close None)
      "pt"   a close the peak doc saw at its minute (the low at loAt, the best at "at") inside a gap or a 15-minute candle (note "m15");
             a pool that died has its low at the death, which is no close (the "dead" atom stands for it)
      "dead" the pool died (peak doc: a rug exit, a collapse or the liquidity floor); note: peak.py's reason. A candle that starts
             before the death keeps its close (a trade that happened, often the crash itself); a gap is cut at the death
    -> ({"pid", "grp", "t", "p", "atoms", "x6", "src", "actual", "why", "stopFill", "low"}, None)"""
    entry = int(num(p.get("entryAt")) or num(p.get("t")) or 0)
    px = num(p.get("px"))
    if not entry or not px:
        return None, "no entry price"
    end = entry + WINDOW_MS
    sm = summary(ctx["docs"].get(pid))
    rows, cover = tip_paths(ctx, p)
    c1 = cover.get(1)
    m1 = [r for r in rows[1] if c1 and entry - MIN <= r[0] < min(c1[1], end)]
    cpx = sm["cpx"] if sm else next((r[3] for r in m1 if r[3] > 0), None) or px
    # the peak doc's exact closes inside the window; a pool that died has its low at the death (no close, the "dead" atom below)
    alive_to = max(sm["dead"], entry) if sm and sm["dead"] is not None else end
    pts = sorted((t, v) for t, v in ((sm["loAt"], sm["lo"]), (sm["at"], sm["x"])) if entry <= t < alive_to) if sm else []
    atoms, cuts = [], []
    if c1 and c1[1] > entry:
        cuts.append(c1)
        atoms += [(r[0], r[0] + MIN, r[3] / cpx, r[3] / cpx, r[3] / cpx, "m1", "") for r in m1]
    s15 = max(entry, c1[1]) if c1 else entry
    c15 = cover.get(15)
    if c15 and c15[1] > s15:
        cuts.append((max(c15[0], s15), c15[1]))
        # a peak doc of minute candles splits the 15-minute candles at its closes; one of 15-minute candles (res 15) has no finer close
        in15 = [(t, v) for t, v in pts if max(c15[0], s15) <= t < c15[1]] if sm and sm["res"] == 1 else []
        atoms += split15([(max(r[0], s15), r[0] + 15 * MIN, r[1] / cpx, r[2] / cpx, r[3] / cpx) for r in rows[15]
                          if r[0] + 15 * MIN > s15 and r[0] < min(end, c15[1])], in15)
    gaps = _minus((entry, end), cuts)
    if gaps and not sm:
        st = (ctx["docs"].get(pid) or {}).get("state") if isinstance(ctx["docs"].get(pid), dict) else None
        return None, "peak doc %s" % st if st in ("est", "unit", "waiting") else "no usable peak doc"
    for a, b in gaps:
        cur = a
        for t, v in (q for q in pts if a <= q[0] < b):
            if t > cur:
                atoms.append((cur, t, sm["lo"], sm["x"], None, "gap", ""))
            atoms.append((t, t, v, v, v, "pt", ""))
            cur = t
        if b > cur:
            atoms.append((cur, b, sm["lo"], sm["x"], None, "gap", ""))
    atoms.sort(key=lambda a: (a[0], a[1]))
    if sm and sm["dead"] is not None and sm["dead"] <= end:
        t_d = max(sm["dead"], entry)
        atoms = [a if a[5] != "gap" or a[1] <= t_d else (a[0], t_d) + a[2:] for a in atoms if a[0] < t_d]
        atoms.append((t_d, t_d, 0.0, 0.0, 0.0, "dead", sm["deadWhy"]))
    if sm:
        x6 = sm["x6"]
    else:
        last = [r for res in (1, 15) for r in rows[res] if r[0] < end and cover.get(res, (0, 0))[1] >= end]
        if not last:
            return None, "path ends before 6 h"
        x6 = max(last, key=lambda r: r[0])[3] / cpx
    kinds = {a[5] for a in atoms}
    src = "+".join(k for k, ok in (("m1", "m1" in kinds), ("m15", "m15" in kinds), ("peak", bool(sm))) if ok)
    exits = [e for e in p.get("_exits") or [] if isinstance(e, dict)]
    last_e = exits[-1] if exits else {}
    actual = sum(num(e.get("eur")) or 0.0 for e in exits) - (num(p.get("ticket")) or 0.0)
    stop_fill = (num(last_e.get("px")) or 0.0) / px if last_e.get("why") == "stop" and num(last_e.get("at")) else None
    return {"pid": pid, "grp": p.get("grp"), "t": entry, "p": p, "atoms": atoms, "x6": max(0.0, x6), "src": src, "actual": actual,
            "why": str(last_e.get("why") or ""), "stopFill": stop_fill, "low": (sm["lo"], sm["dead"] is not None, sm["deadWhy"]) if sm else None}, None


def radar_evidence(doc):
    """One priced buy of the radar account (radar_paper.py, state "closed") as a timeline, or (None, why it stays out). No low is
    stored, so the doc's own exit (the paper rule replayed by radar_paper on the pool's minute candles through peak.py's filter) is the
    evidence: before it no confirmed close at 0.70x or below (and none at 11x or above), at it the exit level; after a stop or a
    take-profit only the best close bounds the rest, down to 0. Levels are multiples of the doc's base (the price the account paid).
    An estimated doc (src "est": no candles, a total loss from the radar's own later prices, no best) stays out, as estimated peak
    docs do: its bounds would be made up."""
    if not isinstance(doc, dict) or doc.get("state") != "closed" or doc.get("why") not in WHYS:
        return None, "not priced"
    if doc.get("src") == "est":         # radar_paper.estimate: no candles, a loss from the radar's own later prices (no best, no x6)
        return None, "estimated"
    entry, end = int(num(doc.get("entryAt")) or 0), int(num(doc.get("end")) or 0)
    x, x6, eur = num(doc.get("x")), num(doc.get("x6")), num(doc.get("eur"))
    if not entry or end <= entry or x is None or eur is None:
        return None, "unreadable"
    why = doc["why"]
    t_ex = min(max(int(num(doc.get("exitAt")) or end), entry), end)
    best = max(num(doc.get("best")) or 1.0, x if why == "tp" else 0.0)
    t_best = num(doc.get("bestAt"))
    dead = doc.get("dead") if isinstance(doc.get("dead"), dict) else None
    t_dead = num(dead.get("at")) if dead else None
    floor = 1.0 - M.HOLD_STOP + EPS

    def stretch(a, b, lo):
        """A gap [a, b) bounded by lo and the best, split at the best's minute when it lies inside."""
        out, cur = [], a
        if t_best is not None and a < t_best < b:
            out += [(a, int(t_best), lo, best, None, "gap", ""), (int(t_best), int(t_best), best, best, best, "pt", "")]
            cur = int(t_best)
        return out + ([(cur, b, lo, best, None, "gap", "")] if b > cur else [])
    if why == "time":
        atoms = stretch(entry, end, floor)
    elif why == "rug":                  # radar_paper never sells at the close that ended the pool: no stop saw a price, as a rug exit
        t_d = min(max(int(t_dead if t_dead is not None else t_ex), entry), end)
        atoms = stretch(entry, t_d, floor) + [(t_d, t_d, 0.0, 0.0, 0.0, "dead", "rug exit")]
    else:
        alive_to = int(t_dead) if t_dead is not None and t_ex < t_dead <= end else end
        atoms = stretch(entry, t_ex, floor) + [(t_ex, t_ex, x, x, x, "pt", "")] + stretch(t_ex, alive_to, 0.0)
        if alive_to < end:
            atoms.append((alive_to, alive_to, 0.0, 0.0, 0.0, "dead", str(dead.get("why") or "")))
    ticket = num(doc.get("ticket")) or M.YOUNG_TICKET
    return {"pid": str(doc.get("id") or ""), "grp": "radar", "t": entry, "p": {"grp": "young", "paper": M.PAPER_RULE, "ticket": ticket},
            "atoms": atoms, "x6": 0.0 if t_dead is not None or x6 is None else max(0.0, x6), "src": "radar", "actual": eur - ticket,
            "why": why, "stopFill": None, "low": None}, None


# ---------------------------------------------------------------- the replay
def fill_at(spec, fill):
    """The sale of a point estimate: a multiple, or a stop the stored prices show only coarsely, spec = (lo, level, class): somewhere
    between the lowest close the stretch allows and the level, at lo + r x (level - lo), r of the fill model for its class
    (FILL_CLASSES)."""
    if not isinstance(spec, tuple):
        return spec
    lo, level, cls = spec
    lo = max(0.0, min(lo, level))
    return lo + fill[cls] * (level - lo)


def replay(ev, stop, target, stop_first=False):
    """One rule on one trade's timeline -> (point, worst, best, why): the point estimate's sale (a multiple of the entry price, or a
    coarse stop spec for fill_at), the worst and the best case where the stored prices allow more than one outcome (fills at the
    stretch's lowest close / at the level), and why the point estimate sold ("stop", "tp", "time", "rug"). Closes only, in time order;
    the stop books min(close, level) on a close it sees (memebot's own booking), the target exactly the target; a close over
    memebot.CANDLE_MAX_X is a glitch and sells nothing. The close at 6 hours (x6) is the window's last close: at the target or above it
    is a take-profit at the target, never a time exit above it; at the stop or under it after a coarse stretch that allowed the stop it
    is that stop (a coarse fill from the stretch's lowest close), never a time exit under it.
    stop_first: where a coarse stretch since the last stored close allowed the stop (or the 15-minute candle that closed at the target
    had a low under the stop) and a stored close then shows the target, the stop is taken (a coarse fill from that stretch's lowest
    close); the point estimate takes the target there. The range covers both orders either way."""
    L = 1.0 - stop if stop is not None else None
    T = target
    atoms, x6 = ev["atoms"], ev["x6"]
    end_tp = T is not None and T <= x6 <= M.CANDLE_MAX_X

    def flags(a):
        lo, hi, cl = a[2], a[3], a[4]
        return (L is not None and cl is not None and cl <= L, T is not None and cl is not None and T <= cl <= M.CANDLE_MAX_X,
                L is not None and lo <= L, T is not None and hi >= T)

    cls = lambda a: "candle" if a[5] == "m15" or a[6] == "m15" else "alive"   # the fill class of a coarse stop its close shows
    # the point estimate, forward: a crossing counts from the first stored close that shows it
    point = why = None
    pend = None                      # the lowest close a coarse stretch since the last close above the level allows
    for a in atoms:
        kind = a[5]
        if kind == "dead":
            if L is None or a[6] == "rug exit":
                point, why = 0.0, "rug"
            else:
                point, why = (0.0, L, "dead"), "stop"
            break
        must_s, must_t, can_s, _ = flags(a)
        if must_t and stop_first and (pend is not None or (kind == "m15" and can_s)):
            low = min(v for v in (pend, a[2] if kind == "m15" and can_s else None) if v is not None)
            point, why = (low, L, cls(a)), "stop"
            break
        if must_t:
            point, why = T, "tp"
            break
        if must_s:
            if kind in ("m1", "pt") and pend is None:
                point = min(a[4], L)
            else:
                point = (min(a[2], pend if pend is not None else a[2]), L, cls(a))
            why = "stop"
            break
        if a[4] is not None:
            pend = None
        elif can_s:
            pend = a[2] if pend is None else min(pend, a[2])
    if why is None:
        if end_tp and stop_first and pend is not None:
            point, why = (pend, L, "alive"), "stop"
        elif end_tp:
            point, why = T, "tp"
        elif L is not None and pend is not None and 0 < x6 <= L:
            # the close at 6 hours is the first stored close at or under the stop after a stretch that allowed it (a radar doc stores
            # no low): a coarse stop from that stretch, as a stored close would show it, not a time exit at the 6-hour close
            point, why = (min(pend, x6), L, "alive"), "stop"
        else:
            point, why = x6, ("time" if x6 > 0 else "rug")
    # the range, backward: every outcome the stored prices allow
    lo_v = hi_v = T if end_tp else x6
    for a in reversed(atoms):
        kind = a[5]
        if kind == "dead":
            lo_v, hi_v = (0.0, 0.0) if L is None or a[6] == "rug exit" else (0.0, L)
            continue
        must_s, must_t, can_s, can_t = flags(a)
        if kind in ("m1", "pt"):
            if must_s:
                lo_v = hi_v = min(a[4], L)
            elif must_t:
                lo_v = hi_v = T
            continue
        lows, highs = [], []
        if can_s:
            lows.append(max(0.0, min(a[2], L)))
            highs.append(L)
        if can_t:
            lows.append(T)
            highs.append(T)
        if not (must_s or must_t):
            lows.append(lo_v)
            highs.append(hi_v)
        lo_v, hi_v = min(lows), max(highs)
    pts = [fill_at(point, f) for f in (FILL_LOW, FILL_LEVEL)]
    return point, min([lo_v] + pts), max([hi_v] + pts), why


def money(ev, mult):
    """The euros a trade made sold at mult times its entry price: memebot.pos_value on the position itself (its paper fees) minus
    the ticket."""
    return M.pos_value(ev["p"], 1.0, mult) - (num(ev["p"].get("ticket")) or 0.0)


def fill_fit(evs):
    """The fill model of the point estimate, per class (FILL_CLASSES), fitted on the live rule's own stops: every trade the paper
    account sold at the stop on a minute candle (exit "at", its fill known) whose replay of the current rule also ends in a coarse
    stop of that class gives (lo, real fill); r = sum(fill - lo) / sum(0.70 - lo), so the coarse stops of the current rule fill on
    average what the real ones did (the calibration of the current rule is therefore exact on those fills by construction; its gap
    shows everything else). Fewer than FIT_MIN sales in a class keep FILL_DEFAULT.
    "check": per level of CHECK_LEVELS, the trades of pools that lived whose first close at or below the level a one-minute path shows
    exactly: [n, the real fills' mean, the "alive" model's mean on the same trades from the peak doc's low]: whether the fit, made
    at -30%, carries over to the other levels."""
    sums = {k: [0, 0.0, 0.0] for k in FILL_CLASSES}
    for ev in evs:
        if ev.get("stopFill") is None:
            continue
        spec = replay(ev, *CURRENT)[0]
        if isinstance(spec, tuple) and spec[1] - spec[0] > 0.01:
            s = sums[spec[2]]
            s[0] += 1
            s[1] += max(0.0, min(spec[1], ev["stopFill"]) - spec[0])
            s[2] += spec[1] - spec[0]
    out = {}
    for k in FILL_CLASSES:
        n, num_, den = sums[k]
        out[k] = round(max(0.0, min(1.0, num_ / den)), 3) if n >= FIT_MIN and den > 0 else FILL_DEFAULT[k]
        out["n" + k.capitalize()] = n
    out["fitted"] = all(sums[k][0] >= FIT_MIN for k in FILL_CLASSES)
    check = {}
    for level in CHECK_LEVELS:
        real, model = [], []
        for ev in evs:
            if not ev.get("low") or ev["low"][1]:
                continue
            hit = next((a for a in ev["atoms"] if a[5] == "m1" and a[4] <= level), None)
            if hit is not None and not any(a[5] != "m1" and a[0] < hit[0] for a in ev["atoms"]):
                real.append(min(hit[4], level))
                model.append(fill_at((ev["low"][0], level, "alive"), out))
        check["%g" % level] = [len(real), _r(_mean(real)), _r(_mean(model))]
    out["check"] = check
    return out


# ---------------------------------------------------------------- the grid of one group
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(v, n=3):
    return round(v, n) if v is not None else None


def boot_range(diffs, idx):
    """The 95% range of the mean difference per trade over the bootstrap resamples idx (lists of trade indices)."""
    if not diffs or not idx:
        return None
    means = sorted(sum(diffs[i] for i in ix) / len(ix) for ix in idx)
    return [_r(means[int(0.025 * (len(means) - 1))]), _r(means[int(0.975 * (len(means) - 1))])]


def group_block(evs, fill, n_all, out_why):
    """Every rule of the grid on the trades of one group, the halves, the calibration and the verdict (see the module doc)."""
    evs = sorted(evs, key=lambda e: (e["t"], e["pid"]))
    n, half = len(evs), len(evs) // 2
    src = {}
    for e in evs:
        src[e["src"]] = src.get(e["src"], 0) + 1
    blk = {"n": n, "all": n_all, "src": src, "out": dict(out_why), "split": evs[half]["t"] if n else None, "nOld": half, "nNew": n - half,
           "actual": None, "calib": None, "rows": [], "cur": None, "best": [], "noStop": None, "verdict": "empty" if not n else "few"}
    if not n:
        return blk
    enough = half >= MIN_HALF and n - half >= MIN_HALF
    fills = (("pt", fill), ("atLevel", FILL_LEVEL), ("atLow", FILL_LOW))
    res = {(s, t): [replay(e, s, t) for e in evs] for s in STOPS for t in TARGETS}
    first = {k: [replay(e, k[0], k[1], stop_first=True) for e in evs] for k in res}
    # every way of reading the coarse prices a lead must survive: the three fill models and the stop first (with the fitted fills)
    vals = {k: dict({fk: [money(e, fill_at(r[0], fv)) for e, r in zip(evs, rs)] for fk, fv in fills},
                    stopFirst=[money(e, fill_at(r[0], fill)) for e, r in zip(evs, first[k])]) for k, rs in res.items()}
    tests = [fk for fk, _ in fills] + ["stopFirst"]
    means = lambda v: (_mean(v), _mean(v[:half]), _mean(v[half:]))
    cur = {fk: means(vals[CURRENT][fk]) for fk in tests}
    for (s, t), rs in res.items():
        v = vals[(s, t)]
        pt, old, new = means(v["pt"])
        why = {}
        for r in rs:
            why[r[3]] = why.get(r[3], 0) + 1
        better = lambda fk: all(a > b + EPS for a, b in zip(means(v[fk]), cur[fk]))
        blk["rows"].append({"stop": s, "target": t, "pt": _r(pt), "old": _r(old), "new": _r(new), "atLevel": _r(_mean(v["atLevel"])),
                            "atLow": _r(_mean(v["atLow"])), "stopFirst": _r(_mean(v["stopFirst"])),
                            "ord": sum(1 for a, b in zip(rs, first[(s, t)]) if a[3] != b[3] or a[0] != b[0]),
                            "lo": _r(_mean([money(e, r[1]) for e, r in zip(evs, rs)])),
                            "hi": _r(_mean([money(e, r[2]) for e, r in zip(evs, rs)])), "amb": sum(1 for r in rs if r[2] - r[1] > 1e-6),
                            "why": why, "beats": bool(enough and (s, t) != CURRENT and all(better(fk) for fk in tests))})
    rows = {(r["stop"], r["target"]): r for r in blk["rows"]}
    blk["cur"] = dict(rows[CURRENT])
    actual = [e["actual"] for e in evs]
    replayed = vals[CURRENT]["pt"]
    by = {}
    for e, r, v in zip(evs, res[CURRENT], replayed):
        k = e["why"] if e["why"] in WHYS else "other"
        b = by.setdefault(k, [0, 0.0, 0.0, 0])
        b[0] += 1
        b[1] += e["actual"]
        b[2] += v
        b[3] += r[3] == e["why"]
    inside = sum(1 for e, r in zip(evs, res[CURRENT]) if money(e, r[1]) - 0.011 <= e["actual"] <= money(e, r[2]) + 0.011)
    blk["actual"] = {"pt": _r(_mean(actual)), "old": _r(_mean(actual[:half])), "new": _r(_mean(actual[half:])), "pnl": _r(sum(actual), 2)}
    blk["calib"] = {"replay": blk["cur"]["pt"], "actual": blk["actual"]["pt"], "gap": _r(_mean(replayed) - _mean(actual)),
                    "gapSum": _r(sum(replayed) - sum(actual), 2), "inside": inside,
                    "byWhy": {k: {"n": b[0], "actual": _r(b[1], 2), "replay": _r(b[2], 2), "same": b[3]} for k, b in sorted(by.items())}}
    beat = sorted((r for r in blk["rows"] if r["beats"]), key=lambda r: (-r["pt"], -r["old"], -r["new"], str(r["stop"]), str(r["target"])))
    rng = random.Random(BOOT_SEED)
    idx = [[rng.randrange(n) for _ in range(n)] for _ in range(BOOT_N)]
    base, base_sf = vals[CURRENT]["pt"], vals[CURRENT]["stopFirst"]

    def shown(r):
        v = vals[(r["stop"], r["target"])]
        d = [a - b for a, b in zip(v["pt"], base)]
        return dict(r, diff=_r(_mean(d)), ci=boot_range(d, idx), sfDiff=_r(_mean(v["stopFirst"]) - _mean(base_sf)))
    blk["best"] = [shown(r) for r in beat[:SHOW_N]]
    # the no-stop row: the same entry when it is one of the rules shown (listed once), else its own
    ns = next((b for b in blk["best"] if b["stop"] is None and b["target"] == CURRENT[1]), None)
    blk["noStop"] = ns or shown(rows[(None, CURRENT[1])])
    blk["verdict"] = "few" if not enough else ("beat" if beat else "none")
    return blk


# ---------------------------------------------------------------- the run
def collect(d):
    """The trades of every group: {grp: (evidence list, closed trades in all, {why left out: n})} and the fill model. The paper
    groups are the closed positions of the account since the paper rule's start (memebot.in_account from paperRuleSince: the Pick's fresh
    start of Oct 22 kept the rule, so its trades before it still count here; all of the position sold); the radar
    group is every settled radar account doc (closed or void)."""
    ctx = P.context(d)
    out = {g: ([], 0, {}) for g in GROUPS}
    for pid, p in sorted(ctx["pos"].items()):
        if not M.in_account(p, ctx.get("ruleSince") or ctx["since"]) or (num(p.get("_left")) or 0.0) > 1e-9:
            continue
        evs, n_all, why = out[p["grp"]]
        ev, w = paper_evidence(ctx, pid, p)
        if ev:
            evs.append(ev)
        else:
            why[w] = why.get(w, 0) + 1
        out[p["grp"]] = (evs, n_all + 1, why)
    evs, n_all, why = [], 0, {}
    for _, doc in sorted(M.load_docs(d, "memeradarpaper").items()):
        if not isinstance(doc, dict) or doc.get("state") not in ("closed", "void"):
            continue
        n_all += 1
        ev, w = radar_evidence(doc)
        if ev:
            evs.append(ev)
        else:
            why[w] = why.get(w, 0) + 1
    out["radar"] = (evs, n_all, why)
    return out, fill_fit(out["young"][0] + out["hold"][0])


def build(d, now):
    """The whole doc (see the module doc). Reads only."""
    t0 = time.time()
    groups, fill = collect(d)
    doc = {"v": V, "t": int(now), "rule": {"stop": CURRENT[0], "target": CURRENT[1], "hours": M.HOLD_MAX_H, "text": M.PAPER_RULE},
           "grid": {"stops": list(STOPS), "targets": list(TARGETS)}, "minHalf": MIN_HALF, "fill": fill, "time": "6h", "groups": {}}
    for g in GROUPS:
        evs, n_all, why = groups[g]
        doc["groups"][g] = group_block(evs, fill, n_all, why)
    doc["secs"] = round(time.time() - t0, 2)
    return doc


def write_doc(d, doc):
    """db/memebot/exitgrid.json, written whole or not at all (a temp file outside the synced folder, then a rename: a reader never sees
    half a doc, and a step killed mid-write leaves nothing for the results branch)."""
    tmp_dir, fn = os.path.join(d, ".egtmp"), os.path.join(d, *DOC)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    tmp = os.path.join(tmp_dir, DOC[-1])
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, fn)
    return fn


def line(doc):
    """The run's one-line summary: per group the trades, the current rule replayed and real per trade, the verdict and the rules
    that beat it."""
    out = {"ok": True, "t": doc["t"], "secs": doc.get("secs"), "fill": {k: doc["fill"].get(k) for k in ("alive", "dead")}}
    for g, blk in doc["groups"].items():
        out[g] = {"n": blk["n"], "verdict": blk["verdict"], "cur": (blk["cur"] or {}).get("pt"), "actual": (blk["actual"] or {}).get("pt"),
                  "best": [rule_text(r["stop"], r["target"]) for r in blk["best"]]}
    return out


def run(d, now):
    """Build and write the doc; never raises: an error is logged, the last good doc stays. -> the summary line (dict)."""
    try:
        doc = build(d, now)
        write_doc(d, doc)
        return line(doc)
    except Exception as e:      # a report: the peaks job must go on to push the docs it priced
        msg = "%s: %s" % (type(e).__name__, str(e)[:200])
        print("exit_grid: %s (the last doc stays)" % msg, file=sys.stderr)
        return {"ok": False, "err": msg}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the exit what-if test of the paper account (hindsight, fake money only)")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--now", type=int, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(run(a.dir, a.now or int(time.time() * 1000)), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
