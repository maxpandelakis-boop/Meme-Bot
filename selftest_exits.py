#!/usr/bin/env python3
"""selftest_exits.py: checks X1 to X14 of the exit what-if test (exit_grid.py, page_exits.py; hindsight, fake money only, nothing is
bought). Synthetic price timelines and a small results-branch fixture; nothing goes to the network.

  python3 selftest_exits.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:               import selftest_exits; selftest_exits.checks(check, SKIPS)

X1  stop against target, in time order on one-minute closes: the earlier one sells; a dip under the stop before a pump is a stop, a pump
    before a crash a take-profit; a close exactly at the level sells; a close over memebot.CANDLE_MAX_X is a glitch, no take-profit;
    the close at 6 h at or over a target sells at the target (a peak doc whose best is a glitch level), never above it
X2  fills: a crash through the stop fills at the crash close (min(close, level), memebot's own booking), never better; a stop seen
    only inside a 15-minute candle or a coarse stretch is a range (its low to the level) with the point at the fill model; a dip inside
    a 15-minute candle that closed above the level sells nothing in the point estimate but widens the range; the order: a target a
    stored close shows after a stretch that allowed the stop is a take-profit in the point estimate and a stop with the stop first
X3  a dead pool: a rug exit is 0 for every rule (its range too); a collapse is 0 without a stop and the dead-pool fill with one; a
    crash close a one-minute path shows before the death fills exactly
X4  the paper fees: money() is memebot.pos_value on the position minus the ticket, by hand for a 3 EUR and a 50 EUR paper position
X5  the fixture (positions, exits, peak docs, tip paths): which trades are replayed and why the others stay out, the sources, and the
    current rule replaying the paper account's own results exactly where the stored prices are exact (the calibration gap is 0)
X6  the honesty rule: a rule better overall but worse in the newer half does not beat the current one; one better in both halves and
    overall does; the order of the best, their difference and its 95% bootstrap range (deterministic), the no-stop row (listed once
    when it is one of the rules that did better)
X7  a lead that only the fill model makes is no lead: equal with every coarse stop at the lowest close means no "beats"; nor one
    that only the order makes: equal with the stop first means no "beats"
X8  too few: under MIN_HALF trades in a half is "few", no rule beats, no best
X9  the fill model: the ratio fit per class on the live rule's own stops, the defaults under FIT_MIN, the check at other levels
X10 the radar account's docs: a stop, a time and a take-profit doc replay to their own results (the take-profit at exactly 11x),
    void docs count in "all" and stay out, so does an estimated doc (no candles, no best); a 6-hour close under a wider stop after a
    stretch that allowed it is that stop (the fill model), not a time sale
X11 the run: run writes db/memebot/exitgrid.json and nothing else, main prints one JSON line and returns 0; an error keeps the last doc,
    logs it, and still returns 0; a write cut off midway leaves its temp file outside the synced folder (nothing half in db/)
X12 the page block: the current rule replayed (what it really made in its small line), the rules that did better in both halves
    (the stop-first difference where the order changed a trade), "No rule beat the current one in both halves.", "Too few trades
    yet", the no-stop row under its own heading, the sample sizes, the sentence that the paper trader keeps its rule; no doc, an
    unreadable doc; the radar card only with priced trades; escaped doc strings, no em dash, no advice words; its place in the
    account block (after the radar account, before the activity feed) and the hook's import guard
X13 Chromium at 390 and 320 px: no sideways scroll, nothing past the block's edge, the info fold at least 44 px; a screenshot at 390 px
X14 the stored prices into timelines (a second fixture): a 24 h check's 15-minute path after the 1 h check's one-minute path, the peak
    doc's closes splitting the 15-minute candles they lie in (not for a peak doc of 15-minute candles), a peak doc with base over cpx
    rebased onto cpx with its best and low in the gap, a path cut at memebot.PATH_MAX, a trade with paths only (its 6-hour close),
    a collapse cutting the timeline
"""
import contextlib, glob, hashlib, html, io, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import exit_grid as X

MIN, H = 60_000, 3_600_000
T0 = 1791655866812                  # the paper account's restart in the results data (2026-10-10 18:11:06 UTC)
XSS = "<img src=x onerror=alert(1)>"
SHOTS = os.environ.get("MEMEBOT_SHOTS") or os.path.join(tempfile.gettempdir(), "exits-shots")
FIT = {"alive": 0.5, "dead": 0.5, "candle": 0.5}


# ---------------------------------------------------------------- synthetic timelines
def m1(points, t0=0):
    """One-minute candles from [(minute, close), ...]: the close is the only minute close."""
    return [(t0 + m * MIN, t0 + (m + 1) * MIN, c, c, c, "m1", "") for m, c in points]


def ev(atoms, x6=1.0, ticket=3.0, grp="young", t=0, actual=0.0, why="time", pid="x", stop_fill=None, low=None):
    return {"pid": pid, "grp": grp, "t": t, "p": {"grp": grp, "paper": M.PAPER_RULE, "ticket": ticket}, "atoms": sorted(atoms, key=lambda a: (a[0], a[1])),
            "x6": x6, "src": "m1", "actual": actual, "why": why, "stopFill": stop_fill, "low": low}


def pt(e, stop, target, fill=FIT):
    p, lo, hi, why = X.replay(e, stop, target)
    return round(X.fill_at(p, fill), 6), round(lo, 6), round(hi, 6), why


# ---------------------------------------------------------------- the fixture on disk
def _dump(d, coll, key, doc):
    os.makedirs(os.path.join(d, "db", coll), exist_ok=True)
    with open(os.path.join(d, "db", coll, key + ".json"), "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))


class Fx:
    """A results-branch db being built: closed paper positions with their exit, peak doc and tip doc (the tip record's checks with
    their candle paths, as memebot stores them: [[minutes after the tip, o, h, l, c], ...] relative to the tip's price, here 1.0),
    written by write(). Every trade has its own run (T0 + k hours) and is bought 20 minutes after it (pricedAt)."""

    def __init__(self):
        self.pos, self.exits, self.peaks, self.tips = {}, {}, {}, {}

    def trade(self, pid, k, path1, x6, sell, why, at_min=None, lo=None, x=None, dead=None, peak_state="ok", grp="young", ticket=3.0,
              lo_at=30, x_at=5, px=1.0, cpx=1.0, res=1, path24=None, out=None):
        """path1: the 1 h check's one-minute closes [(minutes after the entry, close)] or None; path24: the 24 h check's 15-minute
        candles [(minutes after the entry, o, h, l, c)]; out: the horizon check (hours after the tip, [(minutes after the entry,
        close)]). lo, x, x6 of the peak doc are relative to its base (max(cpx, px), peak.py's rule), at lo_at and x_at minutes after
        the entry; dead is minutes after the entry too."""
        t = T0 + k * H
        entry = t + 20 * MIN
        addr = (hashlib.sha1(pid.encode()).hexdigest() * 2)[:44]
        p = {"grp": grp, "sym": pid.upper()[:8], "name": pid, "addr": addr, "pair": "P" + addr[:20], "t": t, "entryAt": entry, "px": px,
             "ticket": ticket, "paper": M.PAPER_RULE}
        self.pos[pid] = p
        e = {"pos": pid, "t": entry + (at_min or 330) * MIN + 5 * MIN, "px": sell, "frac": 1.0, "why": why,
             "eur": round(M.pos_value(p, 1.0, sell / px), 2), "grp": grp}
        if at_min is not None:
            e["at"] = entry + at_min * MIN
        self.exits[pid] = e
        coll = "memeyoung" if grp == "young" else "memerec"
        doc = self.tips.setdefault((coll, t), {"t": t, "rule": M.RULE, "pricedAt": entry, "picks": [], "outs": {}})
        doc["picks"].append({"sym": p["sym"], "addr": addr, "pair": p["pair"], "px": 1.0})
        res_of = lambda rows: {"sym": p["sym"], "mult": rows[-1][4] if rows else 1.0, "eur": 0.0, "path": rows, "cv": 2}
        if path1:
            doc["outs"]["1"] = {"t": t + H, "h": 1.0, "picks": [res_of([[20 + m, c, c, c, c] for m, c in path1])]}
        if path24:
            doc["outs"]["24"] = {"t": t + 24 * H, "h": 24.0, "picks": [res_of([[20 + m, o, h, l, c] for m, o, h, l, c in path24])]}
        if out:
            doc["out"] = {"t": t + int(out[0] * H), "h": out[0], "picks": [res_of([[20 + m, c, c, c, c] for m, c in out[1]])]}
        if peak_state:
            closes = [c for _, c in path1 or [(0, 1.0)]]
            self.peaks[pid] = {"v": 2, "pos": pid, "grp": grp, "state": peak_state, "src": ("m1" if res == 1 else "m15") if peak_state == "ok" else "est",
                               "res": res, "px": px, "cpx": cpx, "base": max(cpx, px), "x": x if x is not None else max(closes), "at": entry + x_at * MIN,
                               "x6": x6, "lo": lo if lo is not None else min(closes), "loAt": entry + lo_at * MIN,
                               "dead": dict(dead, at=entry + dead["at"] * MIN) if dead else None, "entryAt": entry, "end": entry + 6 * H, "cut": []}

    def write(self, d):
        for pid, p in self.pos.items():
            _dump(d, "memepos", pid, p)
            _dump(d, "memeexit", pid + "-1", self.exits[pid])
        for pid, pk in self.peaks.items():
            _dump(d, "memepeak", pid, pk)
        for (coll, t), doc in self.tips.items():
            _dump(d, coll, "tip-%d" % t, doc)
        os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
        with open(os.path.join(d, "db", "memebot", "state.json"), "w", encoding="utf-8") as f:
            json.dump({"paperSince": T0, "paperRule": M.PAPER_RULE}, f)


def fixture(d):
    """A results-branch db: young paper positions since the restart sold by every rule, with their tip docs (one-minute paths for the
    first hour) and peak docs; one with an estimated peak doc only, an open one, one before the restart and a top pick. Every
    replayed trade's stored prices are exact for the current rule, so its replay must equal the real result."""
    now = T0 + 30 * H
    fx = Fx()
    # a crash through the stop inside the one-minute path: the stop fills at the crash close
    fx.trade("y-crash", 1, [(0, 1.0), (1, 1.1), (5, 0.95), (12, 0.45), (30, 0.3)], 0.2, 0.45, "stop", at_min=12, lo=0.2)
    # a slide: the first close at or below 0.70 is 0.69
    fx.trade("y-slide", 2, [(0, 1.0), (3, 0.85), (8, 0.69), (20, 0.6)], 0.5, 0.69, "stop", at_min=8, lo=0.5)
    # held 6 hours: never near the stop (the peak doc's low 0.8), the 6-hour price 1.25
    fx.trade("y-time", 3, [(0, 1.0), (10, 1.3), (39, 1.1)], 1.25, 1.25, "time", lo=0.8, x=1.6)
    # a take-profit on a one-minute close of 11.6: booked at exactly 11x
    fx.trade("y-tp", 4, [(0, 1.0), (10, 3.0), (25, 11.6), (35, 9.0)], 4.0, 11.0, "tp", at_min=25, lo=0.95)
    # a pool gone without a price (rug exit): 0
    fx.trade("y-rug", 5, [(0, 1.0), (10, 0.9)], 0.0, 0.0, "rug", lo=0.0, dead={"at": 30, "why": "rug exit"})
    # an estimated peak doc and no path past the first hour: left out
    fx.trade("y-est", 6, [(0, 1.0), (10, 0.9)], 0.9, 0.9, "time", peak_state="est")
    # no peak doc at all: left out
    fx.trade("y-none", 7, [(0, 1.0)], 1.0, 1.0, "time", peak_state=None)
    # a top pick held 6 hours
    fx.trade("h-time", 8, [(0, 1.0), (30, 1.05)], 1.1, 1.1, "time", lo=0.9, grp="hold", ticket=50.0)
    fx.write(d)
    # an open position and one bought before the restart: neither counts
    _dump(d, "memepos", "y-open", {"grp": "young", "sym": "OPEN", "addr": "o" * 44, "t": T0 + 29 * H, "entryAt": T0 + 29 * H, "px": 1.0, "ticket": 3.0, "paper": M.PAPER_RULE})
    _dump(d, "memepos", "old-1", {"grp": "hold", "sym": "OLD", "addr": "q" * 44, "t": T0 - 30 * H, "px": 1.0, "ticket": 20.0})
    _dump(d, "memeexit", "old-1-1", {"pos": "old-1", "t": T0 - 20 * H, "px": 2.0, "frac": 1.0, "why": "time", "eur": 30.0})
    return now


def candles15(base, changes, n=24, start=40):
    """n 15-minute candles from `start` minutes after the entry, (m, o, h, l, c) = base except where changes {index: (o, h, l, c)}."""
    return [(start + 15 * j,) + tuple(changes.get(j, base)) for j in range(n)]


def fixture_paths(d):
    """The stored prices into timelines: trades whose replay depends on how paper_evidence reads the tip paths and the peak doc.
      y-m15   a 1 h one-minute path and a 24 h 15-minute path; the peak doc's best close 2.1x (minute 105) and low 0.6 (minute 200)
              lie inside two 15-minute candles, which are split there
      y-res15 the same, but a peak doc of 15-minute candles (res 15): its closes are no finer than the candles, nothing is split
      y-gap   a peak doc with base 1.25 over cpx 1.0 (DexScreener paid above the candles); its best (2.4 of base, minute 90) and
              low (0.4 of base, minute 150) lie in the gap after the first hour; the levels must be rebased onto cpx (3.0 and 0.5)
      y-cut   only a horizon check (3 h, one-minute candles) whose path is cut at memebot.PATH_MAX candles: it covers 160 minutes
              from the tip, not 3 hours; the gap after it starts at minute 140 after the entry
      y-only  no peak doc, but the paths cover the whole window: the time exit is the last path close by 6 h (0.85)
      y-coll  a collapse at minute 120 in the gap: the timeline ends with the dead atom there; its best (1.2, minute 70) stays
      y-coll15 a collapse at minute 107 inside the 15-minute candle of the crash (its close 0.08): the candle stays whole with its
              close (the doc's low at the death is no close and splits nothing); its best close at a candle's first minute comes
              before that candle"""
    fx = Fx()
    base24 = (1.1, 1.3, 0.9, 1.1)
    c24 = candles15(base24, {4: (1.1, 2.4, 1.0, 1.5), 10: (1.0, 1.1, 0.55, 0.9)})
    fx.trade("y-m15", 1, [(0, 1.0), (10, 1.2), (39, 1.1)], 0.95, 0.95, "time", lo=0.6, lo_at=200, x=2.1, x_at=105, path24=c24)
    fx.trade("y-res15", 2, [(0, 1.0), (10, 1.2), (39, 1.1)], 0.95, 0.95, "time", lo=0.9, lo_at=190, x=1.5, x_at=100, path24=c24, res=15)
    fx.trade("y-gap", 3, [(0, 1.0), (10, 1.1), (39, 0.95)], 0.8, 0.75, "stop", at_min=150, lo=0.4, lo_at=150, x=2.4, x_at=90, px=1.25)
    fx.trade("y-cut", 4, None, 1.0, 1.0, "time", lo=0.9, lo_at=200, x=1.3, x_at=10, out=(3.0, [(m, 1.05) for m in range(-20, M.PATH_MAX - 20)]))
    fx.trade("y-only", 5, [(0, 1.0), (10, 1.4), (39, 1.2)], None, 0.85, "time", peak_state=None,
             path24=candles15((1.2, 1.3, 1.0, 1.1), {21: (1.0, 1.05, 0.8, 0.85), 22: (0.85, 2.2, 0.85, 2.0)}))
    fx.trade("y-coll", 6, [(0, 1.0), (10, 0.9), (39, 0.8)], 0.0, 0.05, "stop", at_min=121, lo=0.0, lo_at=120, x=1.2, x_at=70,
             dead={"at": 120, "why": "collapse"})
    fx.trade("y-coll15", 7, [(0, 1.0), (10, 0.9), (39, 0.95)], 0.0, 0.1, "stop", at_min=114, lo=0.0, lo_at=107, x=1.2, x_at=70,
             dead={"at": 107, "why": "collapse"}, path24=candles15(base24, {2: (1.1, 1.3, 0.9, 1.2), 4: (1.0, 1.0, 0.05, 0.08)}, n=6))
    fx.write(d)
    return T0 + 30 * H


def tree(d):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        if os.path.isfile(f):
            out[os.path.relpath(f, d)] = hashlib.sha1(open(f, "rb").read()).hexdigest()
    return out


def halves_doc(n_half=110):
    """Synthetic trades for the honesty rule: the older half pumps to 6x and fades to 0.9 by 6 h, the newer half pumps to 2.5x, then
    to 5.5x, and ends at 4x. The current rule (11x) holds both to 6 h; 5x is better in both halves; 3x is better overall but worse in
    the newer half; 2x is worse overall."""
    evs = []
    for i in range(2 * n_half):
        if i < n_half:
            atoms, x6 = m1([(0, 1.0), (10, 6.0), (100, 1.5)]), 0.9
        else:
            atoms, x6 = m1([(0, 1.0), (20, 2.5), (40, 5.5), (100, 4.5)]), 4.0
        evs.append(ev(atoms, x6=x6, t=i * MIN, pid="h%03d" % i, actual=X.money(ev([], ticket=3.0), x6)))
    return evs


def nostop_doc(n_half=110):
    """Synthetic trades where no stop at 11x beats the current rule: every other trade dips to 0.05x (the -30% stop sells there) and
    then closes at 12x, the rest go straight to 12x."""
    paths = ([1.0, 0.9, 0.05, 0.5, 12.0, 1.0], [1.0, 2.0, 6.0, 12.0, 3.0, 1.0])
    return [ev(m1(list(enumerate(paths[i % 2]))), x6=1.0, t=i * MIN, pid="s%03d" % i) for i in range(2 * n_half)]


# ---------------------------------------------------------------- the checks
def checks(check, skips=None):
    tmp = tempfile.mkdtemp(prefix="mb-exits-")
    try:
        _replay(check)
        _fees(check)
        d, doc = _fixture(check, tmp)
        _paths(check, tmp)
        _honesty(check)
        _fill(check)
        _radar(check)
        _run(check, tmp, d)
        page = _page(check, tmp, d)
        _browser(check, page, skips if skips is not None else [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _replay(check):
    a = ev(m1([(0, 1.0), (1, 1.5), (3, 2.2), (6, 0.6), (9, 0.55)]), x6=0.5)
    b = ev(m1([(0, 1.0), (2, 0.65), (5, 3.5), (8, 1.0)]), x6=1.2)
    c = ev(m1([(0, 1.0), (4, 31.0), (5, 1.1)]), x6=1.1)
    e = ev(m1([(0, 1.0), (4, 0.70), (5, 0.9)]), x6=1.0)
    check(pt(a, 0.3, 2.0) == (2.0, 2.0, 2.0, "tp") and pt(a, 0.3, 3.0) == (0.6, 0.6, 0.6, "stop") and pt(a, None, 3.0) == (0.5, 0.5, 0.5, "time")
          and pt(b, 0.3, 3.0) == (0.65, 0.65, 0.65, "stop") and pt(b, 0.4, 3.0) == (3.0, 3.0, 3.0, "tp") and pt(b, None, None) == (1.2, 1.2, 1.2, "time")
          and pt(c, None, 11.0) == (1.1, 1.1, 1.1, "time") and pt(c, None, 2.0) == (1.1, 1.1, 1.1, "time") and pt(e, 0.3, 11.0) == (0.7, 0.7, 0.7, "stop"),
          "X1 stop against target on one-minute closes: the earlier sells (2.2x before 0.6 is a take-profit at 2x, 0.65 before 3.5x a stop), "
          "a close exactly at 0.70 sells at the -30% stop, a 31x close is a glitch (no take-profit at 2x or 11x), else the 6-hour price")
    crash = ev(m1([(0, 1.0), (3, 0.9), (4, 0.42), (6, 0.8)]), x6=0.8)
    c15 = ev([(0, 15 * MIN, 0.3, 1.1, 0.5, "m15", "")], x6=0.9)
    dip = ev([(0, 15 * MIN, 0.6, 1.1, 0.95, "m15", ""), (15 * MIN, 30 * MIN, 0.9, 1.2, 1.0, "m15", "")], x6=1.0)
    gap = ev([(0, 30 * MIN, 0.25, 1.4, None, "gap", ""), (30 * MIN, 30 * MIN, 0.25, 0.25, 0.25, "pt", ""), (30 * MIN, 6 * H, 0.25, 1.4, None, "gap", "")], x6=0.6)
    sc15, sgap = X.replay(c15, 0.3, 11.0)[0], X.replay(gap, 0.3, 11.0)[0]
    check(pt(crash, 0.3, 11.0)[0] == 0.42 and pt(crash, 0.5, 11.0)[0] == 0.42 and pt(crash, 0.6, 11.0)[:2] == (0.8, 0.8)
          and sc15 == (0.3, 0.7, "candle") and pt(c15, 0.3, 11.0) == (0.5, 0.3, 0.7, "stop") and X.fill_at(sc15, X.FILL_LOW) == 0.3 and X.fill_at(sc15, X.FILL_LEVEL) == 0.7
          and pt(dip, 0.3, 11.0) == (1.0, 0.6, 1.0, "time") and sgap == (0.25, 0.7, "alive") and pt(gap, 0.3, 11.0) == (0.475, 0.25, 0.7, "stop")
          and pt(gap, 0.8, 11.0) == (0.6, 0.6, 0.6, "time") and pt(gap, None, 1.2)[2] == 1.2,
          "X2 a crash through the stop fills at the crash close (0.42 at -30% and -50%; -60% holds to 6 h), a stop seen inside a 15-minute "
          "candle is its low to the level (point at the fill model), a dip inside a candle that closed above sells nothing but widens the "
          "range, a coarse stretch fills between the peak doc's low and the level; a stop under the low never sells, a target under the "
          "best may")
    # the close at 6 h is a close inside the window: a peak doc whose best close (36.8x) is a glitch level still shows the take-profit
    glitch = ev([(0, 0, 0.97, 0.97, 0.97, "pt", ""), (0, 90 * MIN, 0.97, 36.8, None, "gap", ""), (90 * MIN, 90 * MIN, 36.8, 36.8, 36.8, "pt", ""),
                 (90 * MIN, 6 * H, 0.97, 36.8, None, "gap", "")], x6=8.66)
    over = dict(glitch, x6=31.0)
    check(all(pt(glitch, s, t) == (t, t, t, "tp") for s in (None, 0.2) for t in (2.0, 3.0, 5.0)) and pt(glitch, 0.2, 11.0) == (8.66, 8.66, 11.0, "time")
          and abs(X.money(glitch, X.replay(glitch, 0.2, 2.0)[0]) - X.money(glitch, 2.0)) < 1e-12 and pt(over, None, 2.0)[::3] == (31.0, "time"),
          "X1 a peak doc with a best close over memebot.CANDLE_MAX_X (36.8x, no take-profit there) and 8.66x at 6 h: a 2x, 3x or 5x "
          "target sells at exactly the target (the 6-hour close shows it), never at 8.66x; 11x holds to 6 h (range up to 11x); a 6-hour "
          "close over CANDLE_MAX_X is a glitch level like any other, no take-profit")
    # the order: a coarse stretch allowed the stop, then a stored close shows the target
    pre = ev([(0, 30 * MIN, 0.6, 3.0, None, "gap", ""), (30 * MIN, 30 * MIN, 2.5, 2.5, 2.5, "pt", ""), (30 * MIN, 6 * H, 0.6, 3.0, None, "gap", "")], x6=1.0)
    cnd = ev([(0, 15 * MIN, 0.5, 2.6, 2.2, "m15", "")], x6=1.0)
    end = ev([(0, 6 * H, 0.6, 3.0, None, "gap", "")], x6=2.5)
    split = ev([(0, 5 * MIN, 0.5, 1.2, None, "m15", ""), (5 * MIN, 5 * MIN, 0.6, 0.6, 0.6, "pt", "m15"), (5 * MIN, 15 * MIN, 0.5, 1.2, 1.0, "m15", "")], x6=1.0)
    sf = lambda e, s, t: X.replay(e, s, t, stop_first=True)
    check(pt(pre, 0.3, 2.0) == (2.0, 0.6, 2.0, "tp") and sf(pre, 0.3, 2.0)[0] == (0.6, 0.7, "alive") and sf(pre, 0.3, 2.0)[3] == "stop"
          and sf(pre, 0.3, 2.0)[1:3] == X.replay(pre, 0.3, 2.0)[1:3] and sf(pre, 0.3, 11.0) == X.replay(pre, 0.3, 11.0)
          and pt(cnd, 0.3, 2.0)[3] == "tp" and sf(cnd, 0.3, 2.0)[0] == (0.5, 0.7, "candle") and sf(cnd, 0.6, 2.0)[3] == "tp"
          and pt(end, 0.3, 2.0) == (2.0, 0.6, 2.0, "tp") and sf(end, 0.3, 2.0)[0] == (0.6, 0.7, "alive")
          and all(sf(e, s, t) == X.replay(e, s, t) for e in (a, b, c) for s in X.STOPS for t in X.TARGETS)
          and X.replay(split, 0.4, 11.0)[0] == (0.5, 0.6, "candle") and X.replay(split, 0.3, 11.0)[0] == (0.5, 0.7, "candle"),
          "X2 the order: after a stretch that allowed the stop, a stored 2.5x close is a take-profit in the point estimate and a stop "
          "(coarse, from the stretch's low) with the stop first, the range the same; a 15-minute candle that closed at the target with a "
          "low under the stop, and a 6-hour close at the target after such a stretch, too; one-minute closes leave no order open; a "
          "peak doc close inside a 15-minute candle fills like the candle")
    rug = ev(m1([(0, 1.0), (3, 0.9)]) + [(10 * MIN, 10 * MIN, 0.0, 0.0, 0.0, "dead", "rug exit")], x6=0.0)
    coll = ev([(0, 30 * MIN, 0.0, 1.3, None, "gap", ""), (30 * MIN, 30 * MIN, 0.0, 0.0, 0.0, "dead", "collapse")], x6=0.0)
    seen = ev(m1([(0, 1.0), (5, 0.02)]) + [(6 * MIN, 6 * MIN, 0.0, 0.0, 0.0, "dead", "collapse")], x6=0.0)
    check(all(pt(rug, s, t) == (0.0, 0.0, 0.0, "rug") for s in X.STOPS for t in X.TARGETS)
          and pt(coll, None, 11.0) == (0.0, 0.0, 0.0, "rug") and X.replay(coll, 0.3, 11.0)[0] == (0.0, 0.7, "dead") and pt(coll, 0.3, 11.0) == (0.35, 0.0, 0.7, "stop")
          and pt(seen, 0.3, 11.0) == (0.02, 0.02, 0.02, "stop") and pt(seen, None, 2.0) == (0.0, 0.0, 0.0, "rug"),
          "X3 a dead pool: a rug exit (no price any more) is 0 for every rule, its range too (no stop saw a price), a collapse is 0 "
          "without a stop and the dead-pool fill with one (between 0 and the level), a crash close a one-minute path shows before the "
          "death fills exactly")


def _fees(check):
    y, h = ev([], ticket=3.0), ev([], ticket=50.0, grp="hold")
    check(abs(X.money(y, 1.0) - (-0.20)) < 1e-9 and abs(X.money(y, 0.0) + 3.0) < 1e-9 and abs(X.money(h, 2.0) - 48.01) < 1e-9
          and abs(X.money(y, 0.7) - (M.pos_value({"grp": "young", "paper": M.PAPER_RULE, "ticket": 3.0}, 1.0, 0.7) - 3.0)) < 1e-12,
          "X4 the paper fees: 3 EUR sold at 1x brings 2.80 (0.10 each side), a dead pool loses the ticket, 50 EUR at 2x brings 98.01; "
          "exactly memebot.pos_value")


def _fixture(check, tmp):
    d = os.path.join(tmp, "x5")
    now = fixture(d)
    doc = X.build(d, now)
    y, h = doc["groups"]["young"], doc["groups"]["hold"]
    cal = y["calib"] or {}
    by = cal.get("byWhy") or {}
    check(y["n"] == 5 and y["all"] == 7 and y["out"] == {"peak doc est": 1, "no usable peak doc": 1} and h["n"] == 1 and h["all"] == 1
          and y["src"] == {"m1+peak": 5} and abs(cal.get("gap")) < 0.005 and abs(cal.get("gapSum")) < 0.025 and cal.get("inside") == 5
          and {k: v["n"] for k, v in by.items()} == {"rug": 1, "stop": 2, "time": 1, "tp": 1} and all(v["same"] == v["n"] for v in by.values())
          and abs(y["actual"]["pnl"] - sum(M.pos_value({"grp": "young", "paper": M.PAPER_RULE, "ticket": 3.0}, 1.0, m) - 3.0 for m in (0.45, 0.69, 1.25, 11.0, 0.0))) < 0.03
          and y["verdict"] == "few" and h["verdict"] == "few" and doc["groups"]["radar"]["verdict"] == "empty" and doc["time"] == "6h",
          "X5 the fixture: five closed new launches replayed (an estimated peak doc and a trade without one stay out, the open one and the one "
          "before the restart do not count), one top pick; the current rule replays the paper account's own results exactly where the "
          "stored prices are exact (a crash fill, a slide fill, the 6-hour price, a take-profit at 11x, a rug; the exit docs keep cents): "
          "gap %s, by exit %s"
          % (cal.get("gap"), {k: (v["actual"], v["replay"]) for k, v in by.items()}))
    return d, doc


def _paths(check, tmp):
    """X14: the stored prices into timelines (fixture_paths): tip paths of both resolutions, the PATH_MAX cut, the peak doc's closes
    in gaps and inside 15-minute candles, the rebase from base to cpx, the death cut, the time exit of a trade with paths only."""
    import peak as P
    d = os.path.join(tmp, "x14")
    now = fixture_paths(d)
    ctx = P.context(d)
    evs = {pid: X.paper_evidence(ctx, pid, p)[0] for pid, p in sorted(ctx["pos"].items())}
    rel = lambda e: [(round((a[0] - e["t"]) / MIN, 3), round((a[1] - e["t"]) / MIN, 3)) + tuple(None if v is None else round(v, 6) for v in a[2:5]) + a[5:]
                     for a in e["atoms"]]
    kinds = lambda e: [a[5] for a in e["atoms"]]
    blk = X.build(d, now)["groups"]["young"]
    m15, r15, gap, cut, only, coll, c15 = (evs.get(k) or {"atoms": [], "t": 0, "x6": None, "src": None, "low": None}
                                           for k in ("y-m15", "y-res15", "y-gap", "y-cut", "y-only", "y-coll", "y-coll15"))
    am = rel(m15)
    check(blk["n"] == 7 and blk["out"] == {} and blk["src"] == {"m1+m15+peak": 3, "m1+peak": 3, "m1+m15": 1}
          and m15["src"] == "m1+m15+peak" and kinds(m15) == ["m1"] * 3 + ["m15"] * 5 + ["pt", "m15"] + ["m15"] * 6 + ["pt", "m15"] + ["m15"] * 11
          and am[3] == (40, 55, 0.9, 1.3, 1.1, "m15", "") and am[7:10] == [(100, 105, 1.0, 2.4, None, "m15", ""), (105, 105, 2.1, 2.1, 2.1, "pt", "m15"),
                                                                          (105, 115, 1.0, 2.4, 1.5, "m15", "")]
          and am[15:18] == [(190, 200, 0.55, 1.1, None, "m15", ""), (200, 200, 0.6, 0.6, 0.6, "pt", "m15"), (200, 205, 0.55, 1.1, 0.9, "m15", "")]
          and am[-1][:2] == (355, 370) and m15["x6"] == 0.95
          and pt(m15, None, 2.0) == (2.0, 2.0, 2.0, "tp") and X.replay(m15, 0.4, 11.0)[0] == (0.55, 0.6, "candle") and pt(m15, None, 11.0)[3] == "time"
          and r15["src"] == "m1+m15+peak" and "pt" not in kinds(r15) and len(r15["atoms"]) == 3 + 22 and pt(r15, None, 2.0)[3] == "time",
          "X14 a 24 h check's 15-minute path after the 1 h check's one-minute path: 3 one-minute and 22 15-minute atoms to 6 h; the peak "
          "doc's best close (2.1x) and low (0.6) split the 15-minute candles they lie in, so 2x sells at the target and -40%% stops "
          "inside the candle; a peak doc of 15-minute candles splits nothing (sources %s)" % blk["src"])
    ag = rel(gap)
    check(gap["src"] == "m1+peak" and ag == [(0, 1, 1.0, 1.0, 1.0, "m1", ""), (10, 11, 1.1, 1.1, 1.1, "m1", ""), (39, 40, 0.95, 0.95, 0.95, "m1", ""),
                                             (40, 90, 0.5, 3.0, None, "gap", ""), (90, 90, 3.0, 3.0, 3.0, "pt", ""), (90, 150, 0.5, 3.0, None, "gap", ""),
                                             (150, 150, 0.5, 0.5, 0.5, "pt", ""), (150, 360, 0.5, 3.0, None, "gap", "")]
          and abs(gap["x6"] - 1.0) < 1e-9 and pt(gap, None, 3.0) == (3.0, 3.0, 3.0, "tp") and X.replay(gap, 0.4, 11.0)[0] == (0.5, 0.6, "alive")
          and X.replay(gap, 0.3, 3.0)[3] == "tp" and X.replay(gap, 0.3, 3.0, stop_first=True)[0] == (0.5, 0.7, "alive")
          and abs(gap["stopFill"] - 0.6) < 1e-9 and gap["low"] == (0.5, False, ""),
          "X14 a peak doc with base 1.25 over cpx 1.0: its best 2.4, low 0.4 and 6-hour 0.8 of base are 3.0, 0.5 and 1.0 of cpx (the "
          "live rule's own reference), at their minutes in the gap after the first hour; 3x sells there (the stop first where the gap "
          "before allowed the stop), -40% stops at the low's minute")
    ac = rel(cut)
    n1 = sum(1 for k in kinds(cut) if k == "m1")
    check(cut["src"] == "m1+peak" and n1 == M.PATH_MAX - 19 and ac[0][:2] == (-1, 0) and ac[n1 - 1][:2] == (139, 140)
          and ac[n1:] == [(140, 200, 0.9, 1.3, None, "gap", ""), (200, 200, 0.9, 0.9, 0.9, "pt", ""), (200, 360, 0.9, 1.3, None, "gap", "")],
          "X14 a horizon check's one-minute path cut at memebot.PATH_MAX (%d) candles covers to its last candle (minute 140 after the "
          "entry), not to the 3-hour check: the peak doc's gap starts there; its best close at minute 10 lies inside the path (exact "
          "there) and is not added" % M.PATH_MAX)
    check(only["src"] == "m1+m15" and abs(only["x6"] - 0.85) < 1e-9 and kinds(only) == ["m1"] * 3 + ["m15"] * 22 and pt(only, None, None) == (0.85, 0.85, 0.85, "time")
          and pt(only, None, 2.0)[3] == "time",
          "X14 a trade without a peak doc whose paths cover the whole window: the time exit is the last path close by 6 h (0.85), not "
          "the 2.0 close of the candle that starts after it")
    ao = rel(coll)
    check(coll["src"] == "m1+peak" and ao[3:] == [(40, 70, 0.0, 1.2, None, "gap", ""), (70, 70, 1.2, 1.2, 1.2, "pt", ""), (70, 120, 0.0, 1.2, None, "gap", ""),
                                                  (120, 120, 0.0, 0.0, 0.0, "dead", "collapse")]
          and coll["x6"] == 0.0 and pt(coll, None, 11.0) == (0.0, 0.0, 0.0, "rug") and X.replay(coll, 0.3, 11.0)[0] == (0.0, 0.7, "dead")
          and coll["low"] == (0.0, True, "collapse"),
          "X14 a collapse at minute 120: the gap ends there with the dead atom (no atom after it, its low at the death is no close); "
          "its best close at minute 70 stays; no stop: 0, with a stop the dead-pool fill")
    a15 = rel(c15)
    check(c15["src"] == "m1+m15+peak" and a15[3:] == [(40, 55, 0.9, 1.3, 1.1, "m15", ""), (55, 70, 0.9, 1.3, 1.1, "m15", ""), (70, 70, 1.2, 1.2, 1.2, "pt", "m15"),
                                                      (70, 85, 0.9, 1.3, 1.2, "m15", ""), (85, 100, 0.9, 1.3, 1.1, "m15", ""), (100, 115, 0.05, 1.0, 0.08, "m15", ""),
                                                      (107, 107, 0.0, 0.0, 0.0, "dead", "collapse")]
          and X.replay(c15, 0.3, 11.0)[0] == (0.05, 0.7, "candle") and pt(c15, None, 11.0) == (0.0, 0.0, 0.0, "rug"),
          "X14 a collapse at minute 107 inside the crash's 15-minute candle: the candle stays whole and keeps its close (0.08: a -30% "
          "stop inside the candle), the dead atom after it; the best close at minute 70 comes before the candle starting there")


def _honesty(check):
    evs = halves_doc()
    blk = X.group_block(evs, FIT, len(evs), {})
    rows = {(r["stop"], r["target"]): r for r in blk["rows"]}
    cur = rows[X.CURRENT]
    r3, r5, r2 = rows[(0.3, 3.0)], rows[(0.3, 5.0)], rows[(0.3, 2.0)]
    blk2 = X.group_block(halves_doc(), FIT, 220, {})
    best = blk["best"]
    check(blk["verdict"] == "beat" and blk["nOld"] == 110 and blk["nNew"] == 110 and r5["beats"] and not r3["beats"] and not r2["beats"]
          and r3["pt"] > cur["pt"] and r3["old"] > cur["old"] and r3["new"] < cur["new"] and r2["pt"] < cur["pt"]
          and len(best) == 3 and all(b["target"] == 5.0 for b in best) and [b["stop"] for b in best] == [0.2, 0.3, 0.4]
          and all(b["ci"][0] <= b["diff"] <= b["ci"][1] for b in best) and blk2["best"] == best and blk2["noStop"] == blk["noStop"]
          and blk["noStop"]["stop"] is None and blk["noStop"]["target"] == 11.0 and not cur["beats"],
          "X6 the honesty rule: 5x (better in both halves and overall) beats the current rule; 3x (better overall, %s against %s, but "
          "worse in the newer half) does not; 2x does not; the best three in a fixed order with their difference inside its 95%% range, the "
          "same twice (fixed seed); the no-stop row beside them" % (r3["pt"], cur["pt"]))
    lead = []
    for i in range(220):                          # a coarse stop at 0.1 below both levels: -20% leads only while the fill is not at the low
        atoms = [(0, 30 * MIN, 0.1, 1.2, None, "gap", ""), (30 * MIN, 30 * MIN, 0.1, 0.1, 0.1, "pt", ""), (30 * MIN, 6 * H, 0.1, 1.2, None, "gap", "")]
        lead.append(ev(atoms, x6=0.3, t=i * MIN, pid="l%03d" % i))
    bl = X.group_block(lead, {"alive": 0.8, "dead": 0.5, "candle": 0.5}, 220, {})
    lr = {(r["stop"], r["target"]): r for r in bl["rows"]}
    check(lr[(0.2, 11.0)]["pt"] > lr[X.CURRENT]["pt"] and lr[(0.2, 11.0)]["atLevel"] > lr[X.CURRENT]["atLevel"]
          and lr[(0.2, 11.0)]["atLow"] == lr[X.CURRENT]["atLow"] and not lr[(0.2, 11.0)]["beats"] and bl["verdict"] == "none",
          "X7 a lead that only the fill model makes is no lead: -20%% is ahead with the fitted fill (%s against %s) and at the level, equal "
          "with every coarse stop at the lowest close, so it does not beat the current rule ('none')" % (lr[(0.2, 11.0)]["pt"], lr[X.CURRENT]["pt"]))
    order = []
    for i in range(220):                          # the peak doc's best 2.5x after a stretch that allowed the low 0.5, the low after it
        atoms = [(0, 30 * MIN, 0.5, 2.5, None, "gap", ""), (30 * MIN, 30 * MIN, 2.5, 2.5, 2.5, "pt", ""), (30 * MIN, 60 * MIN, 0.5, 2.5, None, "gap", ""),
                 (60 * MIN, 60 * MIN, 0.5, 0.5, 0.5, "pt", ""), (60 * MIN, 6 * H, 0.5, 2.5, None, "gap", "")]
        order.append(ev(atoms, x6=0.9, t=i * MIN, pid="o%03d" % i))
    bo = X.group_block(order, FIT, 220, {})
    orow = {(r["stop"], r["target"]): r for r in bo["rows"]}
    o2, oc = orow[(0.3, 2.0)], orow[X.CURRENT]
    check(o2["pt"] > oc["pt"] and o2["old"] > oc["old"] and o2["new"] > oc["new"] and o2["atLevel"] > oc["atLevel"] and o2["atLow"] > oc["atLow"]
          and o2["stopFirst"] == oc["stopFirst"] == oc["pt"] and o2["ord"] == 220 and oc["ord"] == 0 and not o2["beats"]
          and o2["why"] == {"tp": 220} and oc["why"] == {"stop": 220},
          "X7 a lead that only the order makes is no lead: -30%%/2x sells the 2.5x close first in the point estimate (%s against %s, ahead "
          "with every fill model) but the stretch before it allowed the stop; with the stop first it is equal to the current rule "
          "(%s), so it does not beat it; all 220 trades counted as order-unclear" % (o2["pt"], oc["pt"], o2["stopFirst"]))
    few = X.group_block(halves_doc(n_half=99), FIT, 198, {})
    check(few["verdict"] == "few" and few["best"] == [] and not any(r["beats"] for r in few["rows"]) and few["noStop"] is not None
          and X.group_block([], FIT, 3, {"peak doc est": 3})["verdict"] == "empty",
          "X8 too few: 99 trades a half is 'few' (no rule beats, no best, the no-stop row still there); no trade at all is 'empty'")
    bn = X.group_block(nostop_doc(), FIT, 220, {})
    check(bn["verdict"] == "beat" and [(b["stop"], b["target"]) for b in bn["best"]] == [(None, 11.0)] and bn["noStop"] == bn["best"][0]
          and X.line({"t": T0, "fill": FIT, "groups": {"young": bn}})["young"]["best"] == ["no stop, 11x"],
          "X6 the no-stop row as one of the rules that beat the current one: listed once among the best (and in the run's line), the "
          "no-stop entry the same row (%s)" % [(b["stop"], b["target"]) for b in bn["best"]])


def _fill(check):
    evs = []
    for i in range(25):                          # stops inside a 15-minute candle: real fills a third of the way up from the low
        evs.append(ev([(0, 15 * MIN, 0.4, 1.0, 0.5, "m15", "")], x6=0.5, stop_fill=0.4 + 0.1, low=(0.4, False, "")))
    for i in range(5):                           # too few dead-pool stops: their default stays
        evs.append(ev([(0, 10 * MIN, 0.0, 1.0, None, "gap", ""), (10 * MIN, 10 * MIN, 0.0, 0.0, 0.0, "dead", "collapse")], x6=0.0, stop_fill=0.6, low=(0.0, True, "collapse")))
    for i in range(30):                          # one-minute crossings for the check at other levels, in pools that lived
        evs.append(ev(m1([(0, 1.0), (3, 0.78), (6, 0.66), (9, 0.55)]), x6=0.5, low=(0.5, False, "")))
    f = X.fill_fit(evs)
    check(f["candle"] == round(0.1 / 0.3, 3) and f["nCandle"] == 25 and f["dead"] == X.FILL_DEFAULT["dead"] and f["nDead"] == 5
          and f["alive"] == X.FILL_DEFAULT["alive"] and f["fitted"] is False and f["check"]["0.8"] == [30, 0.78, 0.8] and f["check"]["0.5"] == [0, None, None],
          "X9 the fill model: the ratio fit per class on the live rule's own stops (inside a 15-minute candle: 0.1 of 0.3 from the low), "
          "the defaults under %d sales, and the check at other levels from exact one-minute crossings (%s)" % (X.FIT_MIN, f["check"]))


def _radar(check):
    def rdoc(i, why, x, best=1.5, x6=0.8, exit_m=30, dead=None, state="closed"):
        e = T0 + i * H
        eur = round(M.pos_value({"grp": "young", "paper": M.PAPER_RULE, "ticket": 3.0}, 1.0, x), 2)
        return {"v": 1, "id": "r%d" % i, "state": state, "why": why, "entryAt": e, "end": e + 6 * H, "exitAt": e + exit_m * MIN, "x": x, "best": best,
                "bestAt": e + 10 * MIN, "x6": x6, "dead": dead, "eur": eur, "ticket": 3.0, "base": 1.0}
    import radar_paper as RP
    docs = [rdoc(1, "stop", 0.65), rdoc(2, "time", 0.8, exit_m=360), rdoc(3, "tp", 13.0, best=13.0), rdoc(4, "rug", 0.0, dead={"at": T0 + 4 * H + 40 * MIN, "why": "collapse"}),
            {"id": "r5", "state": "void", "why": "unit"}]
    evs = [X.radar_evidence(dc)[0] for dc in docs[:4]]
    got = [round(X.money(e, X.fill_at(X.replay(e, *X.CURRENT)[0], FIT)), 2) for e in evs]
    want = [round(dc["eur"] - 3.0, 2) for dc in docs[:4]]
    tp11 = round(M.pos_value({"grp": "young", "paper": M.PAPER_RULE, "ticket": 3.0}, 1.0, 11.0) - 3.0, 2)
    r_void = X.radar_evidence(docs[4])
    # a stop doc whose 6-hour close (0.1x) lies under a wider stop: no low is stored, so the close at 6 hours is the first stored close
    # under -50% after the stretch from the exit allowed it: that stop (a coarse fill from 0), as the peak doc's low shows it for a
    # paper trade with the same prices, never a time sale at 0.1x; with no stop it is the 6-hour close
    wide = X.radar_evidence(rdoc(6, "stop", 0.65, best=1.2, x6=0.1, exit_m=20))[0]
    w_pts = {k: X.replay(wide, *k) for k in ((0.5, 11.0), (0.7, 11.0), (None, 11.0), X.CURRENT)}
    w_sf = X.replay(wide, 0.5, 11.0, stop_first=True)
    paper = ev([(0, 20 * MIN, 0.65, 1.2, None, "gap", ""), (20 * MIN, 20 * MIN, 0.65, 0.65, 0.65, "pt", ""), (20 * MIN, 359 * MIN, 0.1, 1.2, None, "gap", ""),
                (359 * MIN, 359 * MIN, 0.1, 0.1, 0.1, "pt", ""), (359 * MIN, 6 * H, 0.1, 1.2, None, "gap", "")], x6=0.1)
    # radar_paper.estimate's doc (no candles, the radar's own later prices found the pool dead after a 3x): no best, no 6-hour close
    rec = {"first": T0, "px": 1e-5, "liq": 9000, "later": {"15": {"t": T0 + 15 * MIN, "px": 3e-5, "liq": 20000}, "60": {"t": T0 + 60 * MIN, "gone": True}}}
    b_est = {"id": "r7", "addr": "A" * 44, "sym": "EST", "name": "", "pair": "P" * 44, "round": T0, "entryAt": T0, "end": T0 + 6 * H, "px": 1e-5,
             "liq": 9000, "mc": 20000, "green": True, "verdict": "good", "pts": 0, "rank": 1, "ticket": RP.TICKET, "_rec": rec}
    est = RP.doc_of(b_est, T0 + 60 * H, "closed", RP.MAX_TRIES, "est", RP.estimate(b_est))
    docs.append(est)
    d = tempfile.mkdtemp(prefix="mb-exits-radar-")
    try:
        for dc in docs:
            _dump(d, "memeradarpaper", dc["id"], dc)
        blk = X.build(d, T0 + 40 * H)["groups"]["radar"]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    check(got[0] == want[0] and got[1] == want[1] and got[2] == tp11 and got[3] == -3.0 and r_void == (None, "not priced")
          and blk["n"] == 4 and blk["all"] == 6 and blk["out"] == {"not priced": 1, "estimated": 1} and blk["src"] == {"radar": 4}
          and est["state"] == "closed" and est["src"] == "est" and X.radar_evidence(est) == (None, "estimated")
          and X.fill_at(X.replay(evs[0], 0.5, 11.0)[0], FIT) == 0.8 and X.replay(evs[1], 0.5, 11.0)[1] > 0.7,
          "X10 the radar account's docs: a stop and a time doc replay to their own results, a take-profit at exactly 11x (the doc booked "
          "13x), a pool that died before any stop at 0 (radar_paper never sells at the close that ended it); a void doc counts in 'all' and "
          "stays out, so does radar_paper.estimate's doc (no candles: no best, its bounds would be made up); after a stop only the best "
          "bounds the rest (got %s)" % got)
    fit = lambda r: round(X.fill_at(r[0], FIT), 6)
    check([(fit(w_pts[k]), w_pts[k][3]) for k in ((0.5, 11.0), (0.7, 11.0), (None, 11.0), X.CURRENT)] == [(0.25, "stop"), (0.15, "stop"), (0.1, "time"), (0.65, "stop")]
          and w_pts[(0.5, 11.0)][0] == (0.0, 0.5, "alive") and round(w_pts[(0.5, 11.0)][1], 6) == 0.0 and round(w_pts[(0.5, 11.0)][2], 6) == 0.5
          and w_sf[0] == w_pts[(0.5, 11.0)][0] and X.replay(paper, 0.5, 11.0)[3] == "stop" and X.fill_at(X.replay(paper, 0.5, 11.0)[0], X.FILL_LEVEL) == 0.5
          and X.fill_at(w_pts[(0.5, 11.0)][0], X.FILL_LEVEL) == 0.5,
          "X10 a radar stop doc whose 6-hour close (0.1x) lies under a wider stop: -50%% and -70%% are stop sales filled by the fill model "
          "(0.25x and 0.15x at half way from 0, the level at the kindest fill, as a paper trade with the same prices), not time sales at "
          "0.1x; no stop is the 6-hour close (%s)" % {str(k): (fit(v), v[3]) for k, v in w_pts.items()})


def _run(check, tmp, d):
    before = tree(d)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = X.main(["run", "--dir", d, "--now", str(T0 + 30 * H)])
    after = tree(d)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    lines = out.getvalue().strip().splitlines()
    line = json.loads(lines[-1]) if lines else {}
    fn = os.path.join(d, *X.DOC)
    doc = json.load(open(fn, encoding="utf-8")) if os.path.exists(fn) else {}
    saved = X.build
    X.build = lambda *a, **k: 1 / 0
    try:
        out2, err2 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
            rc2 = X.main(["run", "--dir", d])
    finally:
        X.build = saved
    line2 = json.loads(out2.getvalue().strip().splitlines()[-1])
    check(rc == 0 and len(lines) == 1 and line.get("ok") is True and line["young"]["n"] == 5 and changed == [os.path.join("db", "memebot", "exitgrid.json")]
          and doc.get("v") == X.V and os.path.getsize(fn) < 40_000 and rc2 == 0 and line2 == {"ok": False, "err": "ZeroDivisionError: division by zero"}
          and "the last doc stays" in err2.getvalue() and tree(d) == after,
          "X11 the run writes db/memebot/exitgrid.json and nothing else (%d bytes), prints one JSON line and returns 0; an error is logged, "
          "returns 0 and keeps the last doc" % os.path.getsize(fn))
    # a write cut off midway (json.dump streams: a value it cannot write stops it after the first part, as a killed step would): the
    # half file lies outside the synced folder (bot.py's sync keeps db/memebot/**), the doc in db/ stays whole; a NaN is refused too
    walk = lambda: {os.path.relpath(os.path.join(r, f), d): os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs}
    w0 = walk()
    try:
        X.write_doc(d, {"v": X.V, "pad": "x" * 9000, "bad": object()})
        cut_err = None
    except TypeError as e:
        cut_err = str(e)
    w1 = walk()
    try:
        X.write_doc(d, {"v": X.V, "bad": float("nan")})
        nan_err = None
    except ValueError as e:
        nan_err = str(e)
    new = sorted(k for k in w1 if w1[k] != w0.get(k))
    check(cut_err and new == [os.path.join(".egtmp", "exitgrid.json")] and w1[new[0]] > 9000 and json.load(open(fn, encoding="utf-8")) == doc
          and not [k for k in w1 if k.startswith("db" + os.sep) and k.endswith(".tmp")] and nan_err,
          "X11 a write cut off midway leaves its half file in .egtmp (outside the synced folder, %s), never in db/memebot; the last doc "
          "stays whole" % new)


def _page(check, tmp, d):
    import page_exits as PX, page_account as PA, report as R
    text = lambda h: html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", h, flags=re.S)))
    beat = {"v": 1, "t": T0 + 30 * H, "minHalf": 100, "fill": {"alive": 0.8, "dead": 0.35, "candle": 0.3}, "groups": {
        "young": X.group_block(halves_doc(), FIT, 230, {"peak doc est": 7, XSS: 3}), "hold": X.group_block(halves_doc(n_half=20), FIT, 40, {}),
        "radar": X.group_block([], FIT, 0, {})}}
    beat["groups"]["young"]["best"][0].update(ord=5, sfDiff=0.12)     # one shown rule whose lead the order changes
    none = dict(beat, groups={"young": X.group_block([ev(m1([(0, 1.0)]), x6=1.0, t=i, pid="n%d" % i) for i in range(220)], FIT, 220, {})})
    pd = os.path.join(tmp, "x12")
    os.makedirs(os.path.join(pd, "db", "memebot"))

    def render(doc):
        if doc is None:
            if os.path.exists(os.path.join(pd, *X.DOC)):
                os.remove(os.path.join(pd, *X.DOC))
        else:
            with open(os.path.join(pd, *X.DOC), "w", encoding="utf-8") as f:
                f.write(doc if isinstance(doc, str) else json.dumps(doc))
        return PX.section({"dir": pd, "now": T0 + 31 * H})
    b_beat, b_none, b_empty, b_bad = render(beat), render(none), render(None), render("[1, 2")
    radar_on = dict(beat, groups=dict(beat["groups"], radar=X.group_block(halves_doc(n_half=3), FIT, 6, {})))
    b_radar = render(radar_on)
    t_beat = text(b_beat)
    yb = beat["groups"]["young"]
    check("What if the exits were different" in b_beat and "hindsight" in b_beat and "The paper trader keeps its rule (%s30%% stop, 11x, 6\u00a0h)." % PA.MINUS in t_beat
          and "Current rule (%s30%% stop, 11x, 6\u00a0h)" % PA.MINUS in t_beat and html.escape(PA.eur(yb["actual"]["pt"], True)) in b_beat
          and "Did better per trade in both halves and overall:" in t_beat and t_beat.count("5x target") == 3 and "%s20%% stop, 5x target" % PA.MINUS in t_beat
          and "no stop, 11x target" in t_beat and "220 of 230 trades replayed · 110 older, 110 newer" in t_beat
          and "Too few trades yet: 40 replayed, 100 in each half needed before a rule can count as better." in t_beat
          and "95% range" in t_beat and 'data-xg="radar"' not in b_beat and 'data-xg="radar"' in b_radar
          and "No rule beat the current one in both halves." in text(b_none) and "No replay yet" in b_empty and "could not be read this time" in b_bad,
          "X12 the block: the sentence that the paper trader keeps its rule, per group the current rule (what it really made, the replay "
          "beside it), the three rules that did better in both halves with their halves and 95% range, the no-stop row, the sample sizes; "
          "'too few', 'no rule beat', no doc yet, an unreadable doc; the radar card only once it has priced trades")
    cur_b = re.search(r'<div class="xg-cur">.*?</div>', b_beat, re.S)
    cur_t = text(cur_b.group(0)) if cur_b else ""
    big = re.search(r"<b[^>]*>([^<]*)</b>", cur_b.group(0) if cur_b else "")
    ns_head = "For comparison, without a stop (the same 11x target and 6\u00a0h):"
    young_t = text(re.search(r'<section class="xg-g" data-xg="young">.*?</section>', b_beat, re.S).group(0))
    hold_t = text(re.search(r'<section class="xg-g" data-xg="hold">.*?</section>', b_beat, re.S).group(0))
    check("replayed" in cur_t and big and html.unescape(big.group(1)) == PA.eur(yb["cur"]["pt"], True) + " per trade"
          and "older half %s, newer half %s" % (PA.eur(yb["cur"]["old"], True), PA.eur(yb["cur"]["new"], True)) in cur_t
          and "what the paper account really made with these trades: %s per trade" % PA.eur(yb["actual"]["pt"], True) in cur_t
          and young_t.count(ns_head) == 1 and hold_t.count(ns_head) == 1
          and young_t.index("Did better per trade") < young_t.index(ns_head) < young_t.index("no stop, 11x target")
          and young_t.count("no stop, 11x target") == 1 and young_t.index("%s40%% stop, 5x target" % PA.MINUS) < young_t.index(ns_head)
          and young_t.count("with the stop first where the order is unclear") == 1 and "+0.12\u00a0\u20ac with the stop first where the order is unclear" in young_t
          and "also with the stop first wherever the order is unclear" in t_beat,
          "X12 the card's big figure is the current rule replayed (what the rules are measured against) with its halves, what the paper "
          "account really made in the small line; the no-stop row under its own heading after the rules that did better (in the 'too "
          "few' card too); the stop-first difference only on a rule whose trades the order changed; the info text names the order rule")
    # the no-stop row as one of the rules that did better: listed there once, no comparison heading repeating it
    ns_card = text(PX.group("young", "New launches", X.group_block(nostop_doc(), FIT, 220, {}), 100))
    # the radar account's trades in the sources sentence: their own part, their left-out ones named as the radar account's
    src_t = PX._sources({"groups": {"young": {"src": {"m1+peak": 10, "peak": 5}, "out": {"peak doc est": 2}}, "hold": {},
                                    "radar": {"src": {"radar": 40}, "out": {"not priced": 3, "estimated": 1}}}})
    check(ns_card.count("no stop, 11x target") == 1 and "Did better per trade in both halves and overall:" in ns_card and ns_head not in ns_card
          and young_t.count(ns_head) == 1
          and src_t == ("55 trades replayed: 10 with 1-minute candles of the same coin for the first hour or two, 0 with 15-minute candles, 5 on "
                        "the 6-hour price record alone, 40 radar account trades on their own exit; left out: 3 radar account trades not priced, "
                        "2 estimated, 1 radar account trade estimated."),
          "X12 the no-stop row that did better is listed once, under 'Did better' (no comparison heading then); the sources sentence counts "
          "the radar account's trades as their own part and names its left-out ones (%s)" % src_t)
    tx = text(b_beat)
    check("<img" not in b_beat and html.escape(XSS) in b_beat and "\u2014" not in b_beat + b_none + b_empty + b_bad
          and tx.lower().count("fake money") == 1 and not re.findall(r"(?i)\b(safe|safely|clean|guaranteed?|buy|buys|buying|should|advice)\b", tx.replace("not advice", "")),
          "X12 strings from the doc are escaped, no em dash, the fake-money note once, no 'safe', 'clean', 'buy' or 'should'")
    import selftest_account as SA
    ad = os.path.join(tmp, "x12-page")
    os.makedirs(ad)
    now_p, _ = SA.fixture(ad)
    with open(os.path.join(ad, *X.DOC), "w", encoding="utf-8") as f:
        json.dump(beat, f)
    out = R.build(ad, os.path.join(ad, "report.html"), now=now_p)
    page = open(out, encoding="utf-8").read()
    i_nl, i_rp, i_xg, i_fd = (page.find('data-pa="%s"' % k) for k in ("noloss", "radarpaper", "exitgrid", "feed"))
    src = open(os.path.join(HERE, "page_account.py"), encoding="utf-8").read()
    check(0 < i_nl < i_rp < i_xg < i_fd and page.count('data-pa="exitgrid"') == 1 and "could not be rendered" not in page
          and 'R.safe("exit what-if", lambda: exit_grid(D))' in src and "import page_exits as PX\n    except ImportError:" in src,
          "X12 page_account.section shows the block after the radar account and before the activity feed, once; the hook is one line with "
          "an import guard (without page_exits.py the account block renders as before)")
    return page


PROBE = r"""
() => {
  const b = document.querySelector('[data-pa="exitgrid"]');
  const vis = (e) => e.checkVisibility ? e.checkVisibility({visibilityProperty: true}) : !!e.offsetParent;
  const r = b.getBoundingClientRect();
  const small = Array.from(b.querySelectorAll('details > summary')).filter(vis).map((e) => e.getBoundingClientRect().height).filter((h) => h < 43.5);
  const over = Array.from(b.querySelectorAll('*')).filter((e) => vis(e) && e.getBoundingClientRect().right > r.right + 1).map((e) => e.className || e.tagName);
  return {sw: document.documentElement.scrollWidth, iw: innerWidth, small: small, over: over.slice(0, 5), h: Math.round(r.height), w: Math.round(r.width)};
}
"""


def _browser(check, page, skips):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the browser checks of the exit what-if block (no Playwright)")
        print("  SKIP the browser checks of the exit what-if block: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    url = "https://some-owner.github.io/Meme-Bot/"
    os.makedirs(SHOTS, exist_ok=True)
    views, errs, shot = {}, [], None
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            for w in (390, 320):
                ctx = br.new_context(viewport={"width": w, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.route("**/*", lambda r: r.fulfill(status=200, body=page, headers={"Content-Type": "text/html; charset=utf-8"})
                         if r.request.url.startswith(url) else r.abort())
                pg.goto(url)
                pg.evaluate("document.querySelectorAll('[data-pa=\"exitgrid\"] details').forEach(function(x){x.open=true;})")
                views[w] = pg.evaluate(PROBE)
                if w == 390:
                    shot = os.path.join(SHOTS, "exit-whatif-390.png")
                    pg.locator('[data-pa="exitgrid"]').screenshot(path=shot)
                ctx.close()
            br.close()
    except Exception as e:
        check(False, "X13 the browser checks of the exit what-if block ran (%s)" % str(e)[:160])
        return
    check(all(v["sw"] <= v["iw"] and not v["small"] and not v["over"] for v in views.values()) and not errs and shot and os.path.exists(shot),
          "X13 in Chromium at 390 and 320 px with the info fold open: no sideways scroll, nothing past the block's edge, the fold at least "
          "44 px (block %d px high at 390 px; screenshot %s)" % (views.get(390, {}).get("h", 0), shot))


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (skipped: %s)" % "; ".join(skips) if skips else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
