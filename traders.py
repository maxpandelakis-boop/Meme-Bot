#!/usr/bin/env python3
"""traders.py: three paper traders on one buy stream. Fake money only: nothing here buys, signs or sends anything, nothing the scan,
the training or the big test reads comes from here, and nothing here is advice: it is a record of what three ways of selling did with
the same coins, and of how a rule that learns from finished trades chooses its next small step.

The buy stream (stream(), the same for all three): each scan's top pick for memebot.TOP_TICKET (50 EUR, the paper account since
paperSince, grp "hold"); the new launches for memebot.YOUNG_TICKET (3 EUR, from paperSince to the switch, memebot.switch_at(): history
now); and from the switch every coin the launch radar rates good and push-worthy for radar_paper.RADAR_TICKET (10 EUR, radar_paper's
rule 2). The radar's 3 EUR test before the switch (rule 1) is outside the three traders; its greens only train the learning trader's
radar group (the user's rug complaint, the spec's A1).

  T1, the stop-loss trader: the real paper account (memebot.paper_account, never reset) plus radar_paper's rule-2 results. It sells at
      -30%, at 11x or after 6 h (memebot.PAPER_LABEL).
  T2, the best-price trader: each coin sold at its highest close within 6 h, read from the stored docs (peak.py's memepeak, the radar
      doc's best); prints on dust volume or after the pool died are left out, anything over memebot.CANDLE_MAX_X counts at 30x unless
      peak.py's filter confirmed more. Looking back only: not possible in reality.
  T3, the learning trader: T1's rule until it has learned something, then one small step at a time, per group (pick, radar, young),
      each group from its own trades only. Once a day (00:00 UTC, the first peaks job after it) it may move one notch on one axis of
      the pre-registered grid T3_V = 1 (stop -20/-30/-40%, target 2x/3x/11x, hold 6 h or 2 h; or back to T1's rule), or add or drop
      one skip sign. A step needs MIN_N finished trades (MIN_HALF in each time half), a lead in both halves and overall under every
      reading of coarse prices (exit_grid's fitted fill, fill at the level, fill at the low, the stop first where the order is
      unclear), a paired bootstrap whose 2.5% end is above 0 and a lead without its single best trade. A skip sign needs SKIP_MIN coins
      with and without it (SKIP_MIN_HALF with it in each half), a loss in both halves, a bootstrap whose 97.5% end is below 0,
      Benjamini-Hochberg at SKIP_Q over the signs tested, at most SKIP_MAX signs and SKIP_SHARE of the coins; it is dropped when it no
      longer passes a loose bar (p < SKIP_DROP_P). At most one change of any kind per group and day.
      Its trades are valued by the delta method: T1's real result plus the replayed difference between its rule and T1's on the same
      prices (exit_grid.replay; a minute path from db/memepath when there is one), so T3 equals T1 exactly until a first change, and a
      skipped coin counts 0 (what T1 made on it is shown apart).

Walk-forward, never look-ahead: a decision at D trains only on trades whose 6 h window and its last 15-minute candle ended by D
(entryAt + 6 h + TRAIN_GAP_MS <= D) and that T1 had sold by D; the fill model of a decision is fitted on those trades only; the skip
signs read buy-time fields only (never later, out, peak60, mom, push or any result); a minute path starts at the candle holding the
entry. Every decision is a frozen file db/memetrader/v1/<YYYY-MM-DD>-<group>.json, written once and never again ("made" is its only
time-dependent field); its bootstraps are seeded from sha256, so the same inputs give the same bytes in any process. Days before the
switch are "replay" (worked out afterwards); from the switch on "live". Only the live part says whether learning helps.

Usage:
  python3 traders.py run --dir mb [--now <ms>]        -> writes the missing decisions and db/memebot/traders.json, one JSON line; exit 0
  python3 traders.py summary --dir mb [--now <ms>]    -> load() without "trades" and "feed", as JSON
  python3 traders.py skipfeed --dir mb --out <file>    -> the radar group's current skip signs for the radar job (radar-feed; no file
                                                         before the first radar decision)
"""
import argparse, hashlib, json, math, os, random, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M          # read only: positions, in_account, paper_account, pos_value, switch_at, the paper rule
import peak as P             # read only: context (positions, peak docs, tip docs), DUST_VOL
import exit_grid as EG       # read only: paper_evidence, radar_evidence, replay, money, fill_at, fill_fit
import radar_paper as RP     # read only: all_buys (both rules), paper, signs, records, RADAR_TICKET
from page_account import raw_reason, eur as _eur    # pure helpers: why a raw top was not booked; 1,234.56 € with a real minus

V = 1
T3_V = 1
H, MIN, DAY = 3_600_000, 60_000, 86_400_000
TICKETS = {"pick": M.TOP_TICKET, "young": M.YOUNG_TICKET, "radar": RP.RADAR_TICKET}
GROUPS = ("pick", "radar", "young")                  # page order
START = (0.30, 11.0, 6.0)                            # T1's rule: stop, target multiple, hours
assert START == (M.HOLD_STOP, 1 + M.HOLD_TP, M.HOLD_MAX_H)
STOPS3, TARGETS3, HOLDS3 = (0.20, 0.30, 0.40), (2.0, 3.0, 11.0), (6.0, 2.0)
MIN_N, MIN_HALF = 80, 40
TRAIN_GAP_MS = 20 * MIN                              # a trade trains decision D only if entryAt + 6 h + 20 min <= D (covers 15-min candle closes and the 2-min settle)
BOOT_N = 400
READINGS = ("pt", "atLevel", "atLow", "stopFirst")
SKIP_MIN, SKIP_MIN_HALF, SKIP_Q, SKIP_MAX, SKIP_SHARE, SKIP_DROP_P = 30, 10, 0.10, 2, 0.40, 0.20
DIR = ("db", "memetrader", "v%d" % T3_V)             # one frozen doc per group and day: <YYYY-MM-DD>-<group>.json
SUMMARY = ("db", "memebot", "traders.json")
RUN_DEADLINE_S = 100
SETTLE_MS = P.SETTLE_MS                              # a window counts once now >= end + 2 min
WINDOW_MS = 6 * H
FEED_MAX = 400
EPS = 1e-9
PAPER_FLAGS = ("risky", "low_score", "few_lists", "low_liq", "pumped_1h", "other_pad")
SKIP_FLAGS = {"pick": PAPER_FLAGS + ("zero_odds",), "young": PAPER_FLAGS, "radar": tuple(RP.signs({}, None, None))}   # pre-registered (T3_V 1)
# plain words of every skip sign; the radar's feat:* follow page_radar.LABELS (copied: no page import), "3,000+ buys" as "purchases"
FEAT_TEXT = {"no_socials": "no socials", "bot_volume": "3,000+ purchases already", "pumping_5m": "big rise in 5 min", "young_5m": "pool under 5 min",
             "x_and_paid": "X link and DEX paid", "tweet": "launched off a tweet", "lists3": "on 3+ source lists", "creator_5pct": "creator holds over 5%",
             "mc_500k": "market cap over $500k", "liq_15pct": "liquidity under 15% of market cap", "dev_dead": "dev's earlier launches",
             "dev_young": "fresh dev wallet", "x_copied": "X account used by older coins", "tweet_shared": "coins off the same tweet",
             "sniped30": "sniped in the first 30 s", "bundle_slot": "wallets in the launch block", "fresh_holders": "fresh top holders",
             "fund_cluster": "top holders funded by one wallet", "staircase10": "staircase chart"}
FLAG_TEXT = dict({"risky": "risky pick", "low_score": "score under 50", "few_lists": "seen on 2 lists or fewer", "low_liq": "liquidity under $50k",
                  "pumped_1h": "up more than 50% in the last hour", "zero_odds": "zero chance over 25%", "other_pad": "launchpad not pump.fun, Bonk or Bags",
                  "pts2": "2 or more warning points", "late": "no traps found only after first sight",
                  "creator_holds": "creator still holds over 5%", "serial_dev": "creator with 100+ launches", "falling": "price down 10% or more in 5 min",
                  "no_socials": "no socials and no X link", "was_trap": "rated a trap before", "long_curve": "over 24 h from mint to pool"},
                 **{"feat:" + k: v for k, v in FEAT_TEXT.items()})
GROUP_WORD = {"pick": "Picks", "radar": "Radar", "young": "New launches"}
MINUS = "−"


def num(v):
    return M.num(v)


def seed(*parts):
    """A bootstrap seed from sha256 (never hash()): the same in every process."""
    return int(hashlib.sha256("|".join(map(str, (T3_V,) + parts)).encode()).hexdigest()[:12], 16)


def day(D):
    return time.strftime("%Y-%m-%d", time.gmtime(int(D) // 1000))


def floor_day(ms):
    return int(ms) // DAY * DAY


def ceil_day(ms):
    return -(-int(ms) // DAY) * DAY


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(v, n=4):
    return round(v, n) if isinstance(v, (int, float)) and math.isfinite(v) else None


# ---------------------------------------------------------------- rules and words
def rule_key(r):
    return "%g/%g/%g" % tuple(r)


def rule_dict(r):
    return {"stop": r[0], "target": r[1], "hours": r[2]}


def rule_of(x):
    """A stored rule {"stop", "target", "hours"} -> the grid's tuple, or None when it is not one of T3_V's rules."""
    if not isinstance(x, dict):
        return None
    r = (num(x.get("stop")), num(x.get("target")), num(x.get("hours")))
    return r if r[0] in STOPS3 and r[1] in TARGETS3 and r[2] in HOLDS3 else None


def rule_text(stop, target, hours):
    """"stop −30% · 3x · 6 h"."""
    return "stop %s%d%% · %gx · %g h" % (MINUS, round(100 * stop), target, hours)


def flag_text(f):
    return FLAG_TEXT.get(f, str(f).replace("feat:", "").replace("_", " "))


def sgn2(v):
    """+0.16 / −0.01 (two decimals, a real minus)."""
    return ("+" if v > 0 else (MINUS if v < 0 else "")) + "%.2f" % abs(v) if v is not None else "n/a"


def sgn_lo(v):
    """The low end of a range that passed the bar (above 0): sgn2, or "just above 0" where two decimals would show +0.00."""
    return "just above 0" if v is not None and v > 0 and "%.2f" % v == "0.00" else sgn2(v)


def neighbours(r):
    """One notch on one axis: the stop's or the target's neighbour in the grid, or the other hold time."""
    s, tg, h = r
    out = set()
    i, j = STOPS3.index(s), TARGETS3.index(tg)
    for di in (-1, 1):
        if 0 <= i + di < len(STOPS3):
            out.add((STOPS3[i + di], tg, h))
        if 0 <= j + di < len(TARGETS3):
            out.add((s, TARGETS3[j + di], h))
    out.add((s, tg, 2.0 if h == 6.0 else 6.0))
    return out


# ---------------------------------------------------------------- the trades
class Trade(object):
    """One buy of the stream. ev(hours): its replay evidence for a hold of that many hours (exit_grid's timeline), cached; None when
    the stored prices cannot carry one. Plain attributes: id, group, sym, addr, entryAt, end, ticket, p (the fee model), state, t1,
    closedAt, t1why, t2, t2why, flags (the skip signs, buy-time fields only), hist (a rule-1 radar green: training only). A test may
    hand in pathdoc (its minute path) or evf (evidence(trade, hours) of its own)."""

    def __init__(self, world, **kw):
        self.t1 = self.t2 = self.t3 = self.t3rule = self.closedAt = self.doc = self.pk = None
        self.t1why = self.t2why = ""
        self.skipped, self.open, self.openValue, self.exits = False, False, 0.0, []
        self.state, self.hist, self.flags, self.pid = "running", False, {}, None
        self.__dict__.update(kw)
        self._w, self._ev, self._path = world, {}, False

    def path(self):
        """db/memepath/<id>.json (peak.write_path) when there is a readable one, else None."""
        if self._path is False:
            self._path = self.__dict__.get("pathdoc")
            if self._path is None and self.id in self._w.get("paths", ()):
                doc = M.load_json(os.path.join(self._w["dir"], "db", "memepath", self.id + ".json"), None)
                if isinstance(doc, dict) and isinstance(doc.get("c"), list) and num(doc.get("cpx")) and num(doc.get("entryAt")) is not None:
                    self._path = doc
        return self._path

    def ev(self, hours):
        k = float(hours)
        if k not in self._ev:
            try:
                self._ev[k] = (self.__dict__.get("evf") or evidence)(self, k)
            except Exception:       # an odd doc is a trade without evidence, never a failed decision
                self._ev[k] = None
        return self._ev[k]


def has_path(t):
    return t.path() is not None


def path_ev(path, t, hours):
    """A minute path as exit_grid's evidence for a hold of `hours`: an "m1" atom per candle with $25 of volume (or unknown volume) that
    starts before the pool died and before the horizon; levels over cpx for pick and young (memebot books against cpx), over the price
    paid (base) for the radar; x6 the lower of the last clean close and the last close by the horizon (peak's rule), 0 when the pool died
    by then (its "dead" atom then ends the timeline). None (not replayable) when no close by the horizon had $25 of volume in a pool that
    did not die: its value then is unknown (peak's x6 None), not a total loss."""
    entry = int(t.entryAt)
    cpx, base = num(path.get("cpx")), num(path.get("base"))
    k = 1.0 if t.group != "radar" else (cpx / base if cpx and base else None)
    if not cpx or k is None:
        return None
    horizon = entry + int(hours * H)
    dead = path.get("dead") if isinstance(path.get("dead"), dict) else None
    dead_at = num(dead.get("at")) if dead else None
    atoms, clean, anyv = [], [], []
    for row in path["c"]:
        if not isinstance(row, (list, tuple)) or len(row) < 2 or num(row[0]) is None or not num(row[1]) or num(row[1]) <= 0:
            continue
        t0 = entry + int(num(row[0])) * 1000
        lv, vol = num(row[1]) * k, num(row[2]) if len(row) > 2 else None
        if t0 >= horizon or (dead_at is not None and t0 >= dead_at):
            continue
        ok = vol is None or vol >= P.DUST_VOL
        if t0 + MIN <= horizon:
            anyv.append(lv)
            if ok:
                clean.append(lv)
        if ok:
            atoms.append((t0, t0 + MIN, lv, lv, lv, "m1", ""))
    died = dead_at is not None and dead_at <= horizon
    if not died and not clean:
        return None
    x6 = 0.0 if died else min(clean[-1], anyv[-1])
    if died:
        t_d = max(int(dead_at), entry)
        atoms.append((t_d, t_d, 0.0, 0.0, 0.0, "dead", str(dead.get("why") or "")))
    return {"pid": t.id, "grp": t.group, "t": entry, "p": t.p, "atoms": atoms, "x6": max(0.0, x6), "src": "path", "actual": t.t1 or 0.0,
            "why": t.t1why or "", "stopFill": None, "low": None}


def evidence(t, hours):
    """The path first (any hold), else for 6 h only exit_grid's evidence: the peak doc and the tip paths (pick, young) or the radar doc."""
    path = t.path()
    if path is not None:
        return path_ev(path, t, hours)
    if hours != 6.0:
        return None
    if t.group == "radar":
        ev, _ = EG.radar_evidence(t.doc) if isinstance(t.doc, dict) else (None, "")
        if ev is not None:
            ev["p"] = t.p                    # a rule-1 green trains the radar group at the radar's 10 EUR
        return ev
    ev, _ = EG.paper_evidence(t._w["ctx"], t.pid, t.p)
    return ev


def best_mult(doc, radar=False):
    """T2's multiple of one finished trade and why: (m, "" | "est" | "capped" | "left out"). doc: the memepeak doc (pick, young; x, rawX,
    state) or the radar doc (best, rawX, src; its x is the exit, never read here)."""
    x, raw = num(doc.get("best" if radar else "x")), num(doc.get("rawX"))
    est = doc.get("src") == "est" if radar else doc.get("state") == "est"
    if x is None:
        return 1.0, "est"                    # a radar estimate without candles: the entry itself
    if est:
        return x, "est"                      # a lower bound
    w = raw_reason({"x": x, "rawX": raw, "cut": doc.get("cut")})
    if raw and w == "pool died" and raw <= 1.05:            # the entry minute's own close before the pool died: a close like any other
        return max(x, raw), ""
    if raw is None or w in ("dust volume", "pool died"):     # a spike left out (dust, or after the pool died)
        return x, ("left out" if raw and raw > 1.05 * x and raw > 1.05 else "")
    if raw > M.CANDLE_MAX_X:                 # over 30x only what the filter confirmed (FLOYD: 93.4x, not its raw 102.5x)
        return (M.CANDLE_MAX_X, "capped") if x < M.CANDLE_MAX_X else (x, "")
    return max(x, raw), ""


def radar_v1_best(rows):
    """The radar's old 3 EUR test (rule 1; radar_paper.account's "rows") sold the T2 way, looking back: each priced row (state closed with
    a readable eur, the ones its "all" stats count) at best_mult's multiple after both fees, summed, and the T2 counts (est, capped,
    left out). {"t2": None while none is priced, "est", "capped", "leftOut"}."""
    sold = [r for r in rows if r.get("state") == "closed" and num(r.get("eur")) is not None]
    tot, why = 0.0, {"est": 0, "capped": 0, "left out": 0}
    for r in sold:
        ticket = num(r.get("ticket")) or RP.TICKET
        m, w = best_mult(r, radar=True)
        tot += M.pos_value(RP.paper(ticket), 1.0, m) - ticket
        if w in why:
            why[w] += 1
    return {"t2": round(tot, 2) if sold else None, "est": why["est"], "capped": why["capped"], "leftOut": why["left out"]}


def paper_flags(p, recs):
    """The skip signs of a paper position, from what it carried when it was bought (and its tip's odds in memerec)."""
    f = p.get("f") if isinstance(p.get("f"), dict) else {}
    g = lambda k: num(f.get(k))
    tier, score, liq = p.get("tier"), num(p.get("score")), num(p.get("liq"))
    out = {"risky": tier in ("risky", "fallback") if isinstance(tier, str) and tier else None, "low_score": None if score is None else score < 50,
           "few_lists": None if g("srcN") is None else g("srcN") <= 2, "low_liq": None if liq is None else liq < 50_000,
           "pumped_1h": None if g("c1") is None else g("c1") > 50,
           "other_pad": True if g("lp.other") == 1 else (False if g("lp.trusted") == 1 else None)}
    if p.get("grp") == "hold":
        doc = recs.get(p.get("rec")) if isinstance(p.get("rec"), str) else None
        q = next((q for q in (doc.get("picks") if isinstance(doc, dict) and isinstance(doc.get("picks"), list) else [])
                  if isinstance(q, dict) and q.get("addr") == p.get("addr")), None)
        zp = num(q.get("zp")) if q else None
        out["zero_odds"] = None if zp is None else zp > 0.25
    return out


def flag(t, f):
    """One skip sign of a trade: True, False or None (unknown: on neither side, never skipped)."""
    v = t.flags.get(f) if isinstance(t.flags, dict) else None
    return v if isinstance(v, bool) else None


def _world(d, now, switch=None):
    """Everything load and run read, once: the stream (pick, young, radar rule 2), the radar's rule-1 greens (training only), the paper
    account, the radar docs and the paths on disk."""
    switch = M.switch_at() if switch is None else int(switch)
    ctx = P.context(d)
    since = ctx["since"]
    marks = ctx["marks"] if isinstance(ctx.get("marks"), dict) else {}
    px = marks.get("px") if isinstance(marks.get("px"), dict) else {}
    pdir = os.path.join(d, "db", "memepath")
    paths = {f[:-5] for f in os.listdir(pdir) if f.endswith(".json")} if os.path.isdir(pdir) else set()
    w = {"dir": d, "ctx": ctx, "paths": paths, "switch": switch, "since": since, "now": int(now)}
    recs = M.load_docs(d, "memerec")
    trades = []
    for pid, p in sorted(ctx["pos"].items()):
        if not isinstance(p, dict) or not M.in_account(p, since):
            continue
        entry = int(num(p.get("entryAt")) or num(p.get("t")) or 0)
        ticket = num(p.get("ticket")) or 0.0
        exits = [e for e in p.get("_exits") or [] if isinstance(e, dict)]
        left = num(p.get("_left"))
        left = 1.0 if left is None else left
        back = sum(num(e.get("eur")) or 0.0 for e in exits)
        last, epx = num(px.get(pid)), num(p.get("px"))
        opn = left > 1e-9
        val = M.pos_value(p, left, last / epx) if opn and last and epx else 0.0
        t = Trade(w, id=pid, pid=pid, group="pick" if p.get("grp") == "hold" else "young", sym=str(p.get("sym") or "?")[:24], addr=p.get("addr"),
                  entryAt=entry, end=entry + WINDOW_MS, ticket=ticket, p=p, t1=back + val - ticket, closedAt=None if opn or not exits else num(exits[-1].get("t")),
                  t1why=str(exits[-1].get("why") or "") if exits and not opn else "", flags=paper_flags(p, recs), open=opn, openValue=val, exits=exits)
        pk = ctx["docs"].get(pid)
        t.pk = pk if isinstance(pk, dict) else None
        st = (t.pk or {}).get("state")
        if now < t.end + SETTLE_MS:
            t.state = "running"
        elif opn:
            t.state = "selling"
        elif st in ("ok", "est") and num((t.pk or {}).get("x")) is not None:
            t.state = "finished"
            m, why = best_mult(t.pk)
            t.t2, t.t2why = M.pos_value(p, 1.0, m) - ticket, why
        elif st == "unit":
            t.state = "noprice"
        else:
            t.state = "waiting"
        trades.append(t)
    buys, docs = RP.all_buys(d, switch)
    hist, v1 = [], []
    W = None
    for key, b in sorted(buys.items()):
        doc = docs.get(key) if isinstance(docs.get(key), dict) and docs[key].get("v") == RP.RP_V else None
        if b.get("rule") != 2:
            v1.append(key)
            if b.get("green") and doc and doc.get("state") == "closed":      # A1: the rule-1 greens train the radar group (at 10 EUR)
                rec = b.get("_rec")
                if W is None:
                    W = RP.traps.load_weights()
                feat = RP.feat_of(rec, b["entryAt"], W) if isinstance(rec, dict) else None
                first = num(rec.get("first")) if isinstance(rec, dict) else None
                late = (b["entryAt"] - first > RP.LATE_MS) if first is not None else None
                ht = _radar_trade(w, key, b, doc, now, RP.RADAR_TICKET, RP.signs(feat, b.get("pts"), late))
                if ht.state == "finished":
                    ht.hist = True
                    hist.append(ht)
            continue
        trades.append(_radar_trade(w, key, b, doc, now, num(b.get("ticket")) or RP.RADAR_TICKET, RP.signs(b.get("feat"), b.get("pts"), b.get("late"))))
    trades.sort(key=lambda t: (t.entryAt, t.id))
    hist.sort(key=lambda t: (t.entryAt, t.id))
    w.update(trades=trades, hist=hist, buys=buys, docs=docs, v1=v1)
    return w


def _radar_trade(w, key, b, doc, now, ticket, flags):
    entry = int(b["entryAt"])
    t = Trade(w, id=key, group="radar", sym=str(b.get("sym") or "?")[:24], addr=b.get("addr"), entryAt=entry, end=entry + WINDOW_MS, ticket=ticket,
              p=RP.paper(ticket), flags=flags, doc=doc, buy=b)
    st = doc.get("state") if doc else None
    eur = num(doc.get("eur")) if doc else None
    readable = st == "closed" and eur is not None and eur >= 0 and doc.get("why") in RP.WHYS
    if readable:
        x = num(doc.get("x"))           # a rule-1 green (3 EUR) is counted at the ticket asked for (the radar group's 10 EUR)
        t.t1 = (eur if num(doc.get("ticket")) == ticket or x is None else RP.value(x, ticket)) - ticket
        t.closedAt, t.t1why = num(doc.get("exitAt")), str(doc.get("why") or "")
    if now < t.end + SETTLE_MS:
        t.state = "running"
    elif readable:
        t.state = "finished"
        m, why = best_mult(doc, radar=True)
        t.t2, t.t2why = M.pos_value(t.p, 1.0, m) - ticket, why
    elif st == "void":
        t.state = "noprice"
    else:
        t.state = "waiting"
    return t


def stream(d, now, switch=None):
    """The buy stream: [Trade] sorted by (entryAt, id): pick and young paper positions in the account, the radar's rule-2 buys."""
    return _world(d, now, switch)["trades"]


# ---------------------------------------------------------------- the replay
def vals(evs, rule, fill):
    """{reading: [EUR per trade]} of one rule on these timelines: pt (the fitted fill), atLevel, atLow, stopFirst (wf.py's vals)."""
    s, tg = rule[0], rule[1]
    out = {k: [] for k in READINGS}
    for ev in evs:
        r = EG.replay(ev, s, tg)
        rs = EG.replay(ev, s, tg, stop_first=True)
        out["pt"].append(EG.money(ev, EG.fill_at(r[0], fill)))
        out["atLevel"].append(EG.money(ev, EG.fill_at(r[0], EG.FILL_LEVEL)))
        out["atLow"].append(EG.money(ev, EG.fill_at(r[0], EG.FILL_LOW)))
        out["stopFirst"].append(EG.money(ev, EG.fill_at(rs[0], fill)))
    return out


def boot_ci(xs, sd):
    """The 2.5% and 97.5% of BOOT_N paired resamples' means (trade indices drawn with replacement, seeded)."""
    n = len(xs)
    rng = random.Random(sd)
    means = sorted(sum(rng.choices(xs, k=n)) / n for _ in range(BOOT_N))
    return means[int(0.025 * (BOOT_N - 1))], means[int(0.975 * (BOOT_N - 1))]


def trained(t, D):
    """Whether a trade trains the decision at D: its window and last 15-minute candle over by D, sold by T1 by D, usable evidence."""
    return t.entryAt + 6 * H + TRAIN_GAP_MS <= D and t.closedAt is not None and t.closedAt <= D and t.ev(6) is not None


SPANS = ("overall", "in the older half", "in the newer half")


def _cand(c, inc, sub, fill, D, group):
    """One candidate rule against the incumbent on the same trades (sub): the bars of the module doc."""
    n, h = len(sub), len(sub) // 2
    row = {"rule": rule_dict(c), "n": n}
    if n < MIN_N or h < MIN_HALF or n - h < MIN_HALF:
        return dict(row, status="few", passed=False)
    vc = vals([t.ev(c[2]) for t in sub], c, fill)
    vi = vals([t.ev(inc[2]) for t in sub], inc, fill)
    spans = ((0, n), (0, h), (h, n))
    m = {k: ([mean(vc[k][a:b]) for a, b in spans], [mean(vi[k][a:b]) for a, b in spans]) for k in READINGS}
    better = all(mc > mi + EPS for k in READINGS for mc, mi in zip(*m[k]))
    dlt = [x - y for x, y in zip(vc["pt"], vi["pt"])]
    lo, hi = boot_ci(dlt, seed(day(D), group, rule_key(c)))
    loo = (sum(dlt) - max(dlt)) / (n - 1)
    fails = ["was not better " + SPANS[i] for i in range(3) if not m["pt"][0][i] > m["pt"][1][i] + EPS]
    if not fails and not better:
        fails.append("was not better with every price reading")
    if lo <= 0:
        fails.append("could be chance (likely %s to %s \u20ac per trade)" % (sgn2(lo), sgn2(hi)))
    if loo <= 0:
        fails.append("was carried by its single best trade")
    return dict(row, status="tested", diff=mean(dlt), ci=[lo, hi], loo=loo, means={k: {"cand": [_r(v) for v in m[k][0]], "inc": [_r(v) for v in m[k][1]]} for k in READINGS},
                passed=bool(better and lo > 0 and loo > 0), fails=fails)


def skip_tests(train, rule, fill, flags, D, group):
    """Every skip sign of the group on the training trades under the rule of the day: {flag: test}."""
    sub = [t for t in train if t.ev(rule[2]) is not None]
    v = vals([t.ev(rule[2]) for t in sub], rule, fill)["pt"] if sub else []
    h = len(sub) // 2
    out = {}
    for f in flags:
        w = [i for i, t in enumerate(sub) if flag(t, f) is True]
        wo = [i for i, t in enumerate(sub) if flag(t, f) is False]
        row = {"nWith": len(w), "nWithout": len(wo), "status": "few", "strict": False, "loose": False}
        if len(w) < SKIP_MIN or len(wo) < SKIP_MIN or sum(i < h for i in w) < SKIP_MIN_HALF or sum(i >= h for i in w) < SKIP_MIN_HALF:
            out[f] = row
            continue
        vw, vwo = [v[i] for i in w], [v[i] for i in wo]
        diff = mean(vw) - mean(vwo)
        side = lambda ix, old: [v[i] for i in ix if (i < h) == old]
        hs = [(mean(side(w, o)), mean(side(wo, o))) for o in (True, False)]
        halves = all(a is not None and b is not None and a < b for a, b in hs)
        rng = random.Random(seed(day(D), group, f))
        bd = [mean(rng.choices(vw, k=len(vw))) - mean(rng.choices(vwo, k=len(vwo))) for _ in range(BOOT_N)]
        hi = sorted(bd)[int(0.975 * (BOOT_N - 1))]
        p = (1 + sum(1 for x in bd if x >= 0)) / (BOOT_N + 1)
        out[f] = dict(row, status="tested", diff=diff, mWith=mean(vw), mWithout=mean(vwo), halves=halves, hi=hi, p=p,
                      strict=bool(diff < 0 and halves and mean(vw) < 0 and hi < 0), loose=bool(diff < 0 and p < SKIP_DROP_P))
    return out


def bh_pass(tests, q):
    """Benjamini-Hochberg at q over the signs that were tested: the ones that pass."""
    tested = sorted((t["p"], f) for f, t in tests.items() if t.get("status") == "tested")
    m, k = len(tested), 0
    for i, (p, _) in enumerate(tested, 1):
        if p <= q * i / m:
            k = i
    return [f for _, f in tested[:k]]


def share(train, flags):
    return sum(1 for t in train if any(flag(t, f) is True for f in flags)) / len(train) if train else 0.0


def decide(group, D, trades, S, prev, now, switch=None):
    """The decision of one group at D (00:00 UTC), from the trades that finished before it only. prev: the decision before (None: T1's
    rule, no skip). Pure and deterministic (no clock: "made" is set by run)."""
    switch = M.switch_at() if switch is None else int(switch)
    inc = (rule_of(prev.get("rule")) if isinstance(prev, dict) else None) or START
    skip = [f for f in (prev.get("skip") if isinstance(prev, dict) and isinstance(prev.get("skip"), list) else []) if f in SKIP_FLAGS.get(group, ())]
    train = sorted([t for t in trades if trained(t, D)], key=lambda t: (t.entryAt, t.id))
    fill = EG.fill_fit([t.ev(6) for t in S if t.group in ("pick", "young") and not t.hist and trained(t, D)])
    out = {"v": V, "t3v": T3_V, "day": day(D), "group": group, "asOf": int(D), "made": None, "mode": "live" if D >= switch else "replay",
           "rule": rule_dict(inc), "prev": rule_dict(inc), "changed": None, "skip": list(skip), "prevSkip": list(skip)}
    # 1. the exit rule: one notch on one axis, or back to T1's rule
    cands = sorted((neighbours(inc) | {START}) - {inc})
    rows = []
    for c in cands:
        sub = train if c[2] == 6.0 and inc[2] == 6.0 else [t for t in train if has_path(t) and t.ev(c[2]) is not None and t.ev(inc[2]) is not None]
        rows.append(_cand(c, inc, sub, fill, D, group))
    win = [(r, c) for r, c in zip(rows, cands) if r["passed"]]
    rule = inc
    if win:
        best, rule = max(win, key=lambda rc: (rc[0]["diff"], -cands.index(rc[1])))
        out["rule"], out["changed"] = rule_dict(rule), "rule"
    # 2. the skip signs: only when the exit rule did not change today (at most one change per group and day)
    tests = skip_tests(train, rule, fill, SKIP_FLAGS.get(group, ()), D, group)
    if not out["changed"]:
        drop = [f for f in skip if not tests.get(f, {}).get("loose")]
        if drop:
            out["skip"].remove(drop[0])
            out["changed"] = "skip-drop"
        elif len(skip) < SKIP_MAX:
            new = [f for f in bh_pass(tests, SKIP_Q) if f not in skip and tests[f]["strict"]]
            new.sort(key=lambda f: (tests[f]["p"], f))
            for f in new[:1]:
                if share(train, skip + [f]) <= SKIP_SHARE:
                    out["skip"].append(f)
                    out["changed"] = "skip-add"
    n, h = len(train), len(train) // 2
    rnd = lambda v: _r(v) if isinstance(v, float) else v
    clean = lambda r: {k: ([rnd(x) for x in v] if isinstance(v, list) else rnd(v)) for k, v in r.items()}
    out["evidence"] = {"n": n, "nOld": h, "nNew": n - h, "nPath": sum(1 for t in train if has_path(t)), "fill": {k: v for k, v in fill.items() if k != "check"},
                       "cands": [clean(r) for r in rows], "skipTests": {f: clean(t) for f, t in sorted(tests.items())}}
    out["why"] = plain_why(out, rows, tests, inc)
    return out


def plain_why(out, rows=None, tests=None, inc=None):
    """One plain sentence for the decision log (English, no advice)."""
    rows = rows if rows is not None else (out.get("evidence") or {}).get("cands") or []
    tests = tests if tests is not None else (out.get("evidence") or {}).get("skipTests") or {}
    inc = inc or rule_of(out.get("prev")) or START
    n = (out.get("evidence") or {}).get("n", 0)
    if out.get("changed") == "skip-add":
        f = out["skip"][-1]
        t = tests.get(f) or {}
        return "Skips coins with %s: they lost %s more per trade in both halves (%d of %d trades)." % (
            flag_text(f), _eur(abs(t.get("diff") or 0.0)), t.get("nWith", 0), n)
    if out.get("changed") == "skip-drop":
        f = next((x for x in out.get("prevSkip") or [] if x not in out.get("skip") or []), None)
        t = tests.get(f) or {}
        return "No longer skips coins with %s: the loss with it is no longer clear (%d of %d trades)." % (flag_text(f), t.get("nWith", 0), n)
    if out.get("changed") == "rule":
        new = rule_of(out["rule"])
        r = next((r for r in rows if rule_of(r.get("rule")) == new), {})
        if new == START:
            what = "Back to the stop-loss trader's rule (%s)" % rule_text(*START)
        else:
            parts = []
            if new[0] != inc[0]:
                parts.append("Stop %s%d%% → %s%d%%" % (MINUS, round(100 * inc[0]), MINUS, round(100 * new[0])))
            if new[1] != inc[1]:
                parts.append("Target %gx → %gx" % (inc[1], new[1]))
            if new[2] != inc[2]:
                parts.append("Time limit %g h → %g h" % (inc[2], new[2]))
            what = ", ".join(parts)
            what = what[:1].upper() + what[1:]
        ci = r.get("ci") or [None, None]
        return "%s: better in both halves and with every price reading, %s per trade (likely %s to %s), %d trades." % (
            what, _eur(r.get("diff") or 0.0, True), sgn_lo(ci[0]), sgn2(ci[1]), r.get("n", n))
    tested = [r for r in rows if r.get("status") == "tested"]
    if not tested:
        return "Learning: %d of %d finished trades." % (n, MIN_N)
    best = max(tested, key=lambda r: r.get("diff") if r.get("diff") is not None else -1e9)
    br = rule_of(best.get("rule")) or START
    why = (best.get("fails") or ["was not better"])[0]
    return "Kept: the best other rule (%s) %s." % (rule_text(*br), why)


# ---------------------------------------------------------------- the frozen decisions
def days(group, now, switch, since):
    """The decision days of a group: [first, first + DAY, ..., last] (ms at 00:00 UTC). pick and young start at the first 00:00 after
    paperSince, the radar at the switch's day (its 00:00, or the next one); young's last day is the switch's (it governs the trades up
    to the switch), the others' today."""
    if group == "radar":
        first = ceil_day(switch)
    else:
        if since is None:
            return []
        first = floor_day(since) + DAY
    last = floor_day(now)
    if group == "young":
        last = min(last, floor_day(int(switch) - 1))
    return list(range(first, last + 1, DAY)) if last >= first else []


def dec_path(d, D, group):
    return os.path.join(d, *DIR) + os.sep + "%s-%s.json" % (day(D), group)


def load_decisions(d):
    """{group: [decision, ...] by asOf}: the readable frozen docs of this T3_V (a broken file is skipped)."""
    out = {g: [] for g in GROUPS}
    folder = os.path.join(d, *DIR)
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not fn.endswith(".json"):
            continue
        doc = M.load_json(os.path.join(folder, fn), None)
        if not isinstance(doc, dict) or doc.get("t3v") != T3_V or doc.get("group") not in out or num(doc.get("asOf")) is None or rule_of(doc.get("rule")) is None:
            continue
        if fn != "%s-%s.json" % (day(num(doc["asOf"])), doc["group"]):
            continue
        doc["skip"] = [f for f in doc.get("skip") or [] if f in SKIP_FLAGS[doc["group"]]] if isinstance(doc.get("skip"), list) else []
        out[doc["group"]].append(doc)
    for g in out:
        out[g].sort(key=lambda x: num(x["asOf"]))
    return out


def decision_at(decs, t):
    """The latest decision with asOf <= t (None before the first)."""
    best = None
    for doc in decs:
        if num(doc["asOf"]) <= t:
            best = doc
        else:
            break
    return best


def write_once(d, fn, doc):
    """Written whole once: a temp file outside db/, then a rename; never over a file that is there (frozen)."""
    if os.path.exists(fn):
        return False
    tmp_dir = os.path.join(d, ".trtmp")
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    tmp = os.path.join(tmp_dir, os.path.basename(fn))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    if os.path.exists(fn):
        os.remove(tmp)
        return False
    os.replace(tmp, fn)
    return True


def run(d, now, switch=None, deadline_s=RUN_DEADLINE_S, log=None):
    """The peaks job's daily step: every missing decision of every group, oldest first (frozen files are never rewritten; past the
    deadline the next run goes on), then db/memebot/traders.json. Never raises. -> the summary line (dict)."""
    t0 = time.time()
    log = log or (lambda s: print(s, file=sys.stderr, flush=True))
    out = {"ok": True, "written": [], "secs": None}
    try:
        switch = M.switch_at() if switch is None else int(switch)
        w = _world(d, now, switch)
        S = w["trades"]
        for group in ("young", "pick", "radar"):
            prev = None
            trades = [t for t in S if t.group == group] + (w["hist"] if group == "radar" else [])
            for D in days(group, now, switch, w["since"]):
                fn = dec_path(d, D, group)
                if os.path.exists(fn):
                    doc = M.load_json(fn, None)
                    prev = doc if isinstance(doc, dict) and rule_of(doc.get("rule")) else prev
                    continue
                if time.time() - t0 > deadline_s:
                    out["why"] = "deadline: the next run goes on"
                    break
                doc = decide(group, D, trades, S, prev, now, switch)
                doc["made"] = int(now)
                if write_once(d, fn, doc):
                    out["written"].append(os.path.basename(fn))
                    log("traders: %s %s %s: %s" % (day(D), group, doc["mode"], doc["why"]))
                prev = M.load_json(fn, doc)
        L = load(d, now, switch)
        decs = load_decisions(d)
        summ = {"v": V, "t3v": T3_V, "t": int(now), "err": L.get("err"),
                "same": {k: L["same"].get(k) for k in ("n", "invested", "t1", "t2", "t3")},
                "groups": {g: ({k: decs[g][-1].get(k) for k in ("day", "asOf", "mode", "rule", "skip", "changed", "why")} if decs[g] else None) for g in GROUPS},
                "secs": round(time.time() - t0, 2)}
        fn = os.path.join(d, *SUMMARY)
        tmp_dir = os.path.join(d, ".trtmp")
        os.makedirs(tmp_dir, exist_ok=True)
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with open(os.path.join(tmp_dir, "traders.json"), "w", encoding="utf-8") as f:
            json.dump(summ, f, separators=(",", ":"), allow_nan=False)
        os.replace(os.path.join(tmp_dir, "traders.json"), fn)
        out.update(same=summ["same"], err=L.get("err"))
    except Exception as e:      # the peaks job must go on to push the docs it priced
        out.update(ok=False, err="%s: %s" % (type(e).__name__, str(e)[:200]))
        log("traders: %s (the decisions written so far stay)" % out["err"])
    out["secs"] = round(time.time() - t0, 2)
    return out


# ---------------------------------------------------------------- load: everything the page shows
def _empty(now, err=None):
    z = {"n": 0, "invested": 0.0, "t1": 0.0, "t2": 0.0, "t3": 0.0}
    sw = M.switch_at()
    return {"v": V, "t3v": T3_V, "now": int(now) if num(now) is not None else 0, "err": err, "switchAt": sw, "since": None, "tickets": dict(TICKETS),
            "ruleText": M.PAPER_LABEL, "same": dict(z, groups={g: dict(z) for g in GROUPS}),
            "t1": {"account": 0.0, "invested": 0.0, "open": {"n": 0, "value": 0.0}, "radar": {"running": 0, "waiting": 0, "noprice": 0, "worst": 0.0},
                   "won": 0, "lost": 0},
            "t2": {"median": None, "noBest": 0.0, "best": None, "est": 0, "capped": 0, "leftOut": 0},
            "t3": {"groups": {g: {"rule": rule_dict(START), "ruleText": rule_text(*START), "skip": [], "changes": 0, "lastChange": None,
                                  "learning": {"n": 0, "need": MIN_N}, "ended": g == "young" and num(now) is not None and now >= sw} for g in GROUPS},
                   "skipped": {"n": 0, "t1": 0.0}, "vsT1": {"diff": 0.0, "ci": [0.0, 0.0], "n": 0, "range": [0.0, 0.0]},
                   "live": {"diff": 0.0, "ci": [0.0, 0.0], "n": 0}, "notReplayable": 0},
            "counts": {"running": 0, "selling": 0, "waiting": 0, "noprice": 0, "finished": 0},
            "series": {"t1": [], "t2": [], "t3": []}, "trades": [], "feed": [], "feedN": 0, "decisions": [],
            "radarV1": {"n": 0, "priced": 0, "pnl": 0.0, "t2": None, "est": 0, "capped": 0, "leftOut": 0}, "radarHist": 0}


def load(d, now, switch=None):
    """The three traders for the page, recomputed from the db (the decisions read from DIR, never written). Pure: reads only, never
    raises (an error gives the same keys, empty, with "err"). The schema is the contract with the page (page_traders.py)."""
    try:
        return _load(d, int(now), switch)
    except Exception as e:
        return _empty(now, "%s: %s" % (type(e).__name__, str(e)[:160]))


def _sum_ci(xs, sd):
    """The 95% range of the sum of xs (BOOT_N resamples of the per-trade values)."""
    if not xs:
        return [0.0, 0.0]
    n = len(xs)
    rng = random.Random(sd)
    sums = sorted(sum(rng.choices(xs, k=n)) for _ in range(BOOT_N))
    return [round(sums[int(0.025 * (BOOT_N - 1))], 2), round(sums[int(0.975 * (BOOT_N - 1))], 2)]


def _load(d, now, switch=None):
    switch = M.switch_at() if switch is None else int(switch)
    w = _world(d, now, switch)
    trades, ctx = w["trades"], w["ctx"]
    out = _empty(now)
    out.update(switchAt=switch, since=w["since"])
    decs = load_decisions(d)
    # T1: the paper account (open positions at the last mark) plus rule 2's closed results
    acct = M.paper_account(ctx["pos"], w["since"], (ctx["marks"] or {}).get("px") if isinstance(ctx["marks"], dict) else None)
    radar = [t for t in trades if t.group == "radar"]
    r_closed = [t for t in radar if t.t1 is not None]
    noprice = [t for t in radar if t.state == "noprice"]
    out["t1"] = {"account": round(acct["pnl"] + sum(t.t1 for t in r_closed), 2), "invested": round(acct["invested"] + sum(t.ticket for t in radar), 2),
                 "open": {"n": acct["nOpen"], "value": acct["open"]},
                 "radar": {"running": sum(1 for t in radar if t.state == "running"), "waiting": sum(1 for t in radar if t.state == "waiting"),
                           "noprice": len(noprice), "worst": round(0.0 - sum(t.ticket for t in noprice), 2)}, "won": 0, "lost": 0}
    fin = [t for t in trades if t.state == "finished"]
    # T3: the decisions in force at each entry, the delta method
    fill_box = {}

    def fill_val():
        if "f" not in fill_box:
            fill_box["f"] = EG.fill_fit([t.ev(6) for t in fin if t.group in ("pick", "young") and t.ev(6) is not None])
        return fill_box["f"]
    diffs, live, skipped, nrep = [], [], [], 0
    rng_sum = {"pt": 0.0, "atLevel": 0.0, "atLow": 0.0}
    for t in fin:
        doc = decision_at(decs[t.group], t.entryAt)
        r = rule_of(doc.get("rule")) if doc else START
        s = doc.get("skip") if doc else []
        t.t3rule, t.skipped = r, False
        if any(flag(t, f) is True for f in s):
            t.t3, t.skipped = 0.0, True
            skipped.append(t)
            for k in rng_sum:
                rng_sum[k] += -t.t1
        elif r == START:
            t.t3 = t.t1
        elif t.ev(r[2]) is None or t.ev(6) is None:
            t.t3 = t.t1
            nrep += 1
        else:
            vr, vs = vals([t.ev(r[2])], r, fill_val()), vals([t.ev(6)], START, fill_val())
            t.t3 = t.t1 + vr["pt"][0] - vs["pt"][0]
            for k in rng_sum:
                rng_sum[k] += vr[k][0] - vs[k][0]
        diffs.append(t.t3 - t.t1)
        if t.entryAt >= switch:
            live.append(t.t3 - t.t1)
    for t in trades:
        if t.state != "finished":
            t.t3, t.t3rule, t.skipped = None, None, False
    # the same finished trades for all three
    def block(ts):
        return {"n": len(ts), "invested": round(float(sum(t.ticket for t in ts)), 2), "t1": round(float(sum(t.t1 for t in ts)), 2),
                "t2": round(float(sum(t.t2 for t in ts)), 2), "t3": round(float(sum(t.t3 for t in ts)), 2)}
    out["same"] = dict(block(fin), groups={g: block([t for t in fin if t.group == g]) for g in GROUPS})
    out["t1"]["won"] = sum(1 for t in fin if t.t1 > 0)
    out["t1"]["lost"] = len(fin) - out["t1"]["won"]
    t2s = [t.t2 for t in fin]
    if fin:
        bt = max(fin, key=lambda t: (t.t2, -t.entryAt))
        out["t2"] = {"median": round(statistics.median(t2s), 2),
                     "noBest": round(sum(t2s) - bt.t2, 2), "best": {"sym": bt.sym, "eur": round(bt.t2, 2)},
                     "est": sum(1 for t in fin if t.t2why == "est"), "capped": sum(1 for t in fin if t.t2why == "capped"),
                     "leftOut": sum(1 for t in fin if t.t2why == "left out")}
    groups = {}
    for g in GROUPS:
        last = decs[g][-1] if decs[g] else None
        r = rule_of(last.get("rule")) if last else START
        ch = [x for x in decs[g] if x.get("changed")]
        groups[g] = {"rule": rule_dict(r), "ruleText": rule_text(*r), "skip": [{"flag": f, "text": flag_text(f)} for f in (last.get("skip") if last else [])],
                     "changes": len(ch), "lastChange": int(num(ch[-1]["asOf"])) if ch else None,
                     "learning": {"n": int(num(((last or {}).get("evidence") or {}).get("n")) or 0) if last else 0, "need": MIN_N},
                     "ended": g == "young" and now >= switch}
    out["t3"] = {"groups": groups, "skipped": {"n": len(skipped), "t1": round(float(sum(t.t1 for t in skipped)), 2)},
                 "vsT1": {"diff": round(float(sum(diffs)), 2), "ci": _sum_ci(diffs, seed("value", len(diffs))), "n": len(diffs),
                          "range": [round(min(rng_sum.values()), 2), round(max(rng_sum.values()), 2)]},
                 "live": {"diff": round(float(sum(live)), 2), "ci": _sum_ci(live, seed("value", len(live))), "n": len(live)}, "notReplayable": nrep}
    out["counts"] = {k: sum(1 for t in trades if t.state == k) for k in ("running", "selling", "waiting", "noprice", "finished")}
    # cumulative over the finished trades by window end, the last point of each hour
    series = {"t1": [], "t2": [], "t3": []}
    cum = {"t1": 0.0, "t2": 0.0, "t3": 0.0}
    for t in sorted(fin, key=lambda t: (t.end, t.id)):
        hr = t.end // H * H + H
        for k in cum:
            cum[k] += getattr(t, k)
            pt = [hr, round(cum[k], 2)]
            if series[k] and series[k][-1][0] == hr:
                series[k][-1] = pt
            else:
                series[k].append(pt)
    out["series"] = series
    out["trades"] = [{"id": t.id, "group": t.group, "sym": t.sym, "addr": t.addr, "entryAt": t.entryAt, "end": t.end, "ticket": t.ticket, "state": t.state,
                      "t1": round(t.t1, 2) if t.t1 is not None else None, "t2": round(t.t2, 2) if t.t2 is not None else None,
                      "t3": round(t.t3, 2) if t.t3 is not None else None, "skipped": bool(t.skipped), "t1why": t.t1why or "", "t2why": t.t2why or "",
                      "move": _move(t), "t3rule": rule_text(*t.t3rule) if t.t3rule else None} for t in sorted(trades, key=lambda t: (-t.entryAt, t.id))]
    feed = _feed(trades)
    out["feed"], out["feedN"] = feed[:FEED_MAX], len(feed)       # the page shows the newest FEED_MAX and says how many there are
    out["decisions"] = [{"day": x.get("day"), "group": g, "mode": x.get("mode"), "changed": x.get("changed"), "rule": x.get("rule"), "prev": x.get("prev"),
                         "skip": list(x.get("skip") or []), "why": str(x.get("why") or ""), "n": int(num((x.get("evidence") or {}).get("n")) or 0)}
                        for g in GROUPS for x in decs[g]]
    out["decisions"].sort(key=lambda x: (x["day"] or "", GROUPS.index(x["group"])), reverse=True)
    A = RP.account(d, now, switch)
    out["radarV1"] = dict({"n": len(A["rows"]), "priced": A["all"]["n"], "pnl": A["all"]["pnl"]}, **radar_v1_best(A["rows"]))
    out["radarHist"] = len(w["hist"])
    return out


def _move(t):
    """The price move of a trade's (last) sale against its entry: a radar doc's exit multiple x - 1, a sold paper position's last exit price
    over its entry price - 1; None while it is open or unknown. The page reads the stop's gap from it (a stop booked below -35%)."""
    if t.group == "radar":
        x = num(t.doc.get("x")) if t.t1 is not None and isinstance(t.doc, dict) else None
        return round(x - 1, 4) if x is not None else None
    ep, entry = (num(t.exits[-1].get("px")) if t.exits and not t.open else None), num(t.p.get("px"))
    return round(ep / entry - 1, 4) if ep is not None and entry else None


def _feed(trades):
    """Every buy and sale of the stream, newest first, all of them (load keeps the newest FEED_MAX; page_account's feed shape)."""
    feed = []
    for t in trades:
        grp = "radar" if t.group == "radar" else ("hold" if t.group == "pick" else "young")
        feed.append({"t": t.entryAt, "k": "buy", "id": t.id, "sym": t.sym, "grp": grp, "ticket": t.ticket})
        if t.group == "radar":
            if t.t1 is not None:
                feed.append({"t": t.closedAt or t.end, "k": "sell", "id": t.id, "sym": t.sym, "grp": grp, "ticket": t.ticket, "why": t.t1why or "?",
                             "move": _move(t), "eur": round(t.t1, 2), "half": False})
            continue
        entry = num(t.p.get("px"))
        for e in t.exits:
            ep, frac = num(e.get("px")), num(e.get("frac"))
            frac = 1.0 if frac is None else frac
            feed.append({"t": num(e.get("at")) or num(e.get("t")) or 0, "k": "sell", "id": t.id, "sym": t.sym, "grp": grp, "ticket": t.ticket,
                         "why": str(e.get("why") or "?"), "move": (ep / entry - 1) if ep is not None and entry else None,
                         "eur": round((num(e.get("eur")) or 0) - t.ticket * frac, 2), "half": frac < 0.999})
    feed.sort(key=lambda f: (-(f["t"] or 0), 0 if f["k"] == "sell" else 1, f["id"]))
    return feed


# ---------------------------------------------------------------- the radar job's skip list (A1: the push follows T3)
def skip_feed(d):
    """The radar group's current skip signs for the radar job: {"v", "t3v", "day", "asOf", "skip": [sign], "texts": [words]} from the
    latest frozen radar decision; an empty list without one. Never raises."""
    out = {"v": 1, "t3v": T3_V, "day": None, "asOf": None, "skip": [], "texts": []}
    try:
        decs = load_decisions(d)["radar"]
        if decs:
            last = decs[-1]
            out.update(day=last.get("day"), asOf=int(num(last["asOf"])), skip=list(last["skip"]), texts=[flag_text(f) for f in last["skip"]])
    except Exception:
        pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="three paper traders on one buy stream (fake money, looking back, no advice)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--dir", default="mb")
        s.add_argument("--now", type=int, default=None, help="ms; default: the wall clock")
    s = sub.add_parser("skipfeed", help="write the radar group's current skip signs (the radar job reads them from radar-feed)")
    s.add_argument("--dir", default="mb")
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "skipfeed":
        try:
            doc = skip_feed(a.dir)
            if doc["day"] is not None:       # no radar decision yet: no file (the radar pushes as before)
                with open(a.out, "w", encoding="utf-8") as f:
                    json.dump(doc, f, sort_keys=True)
            print(json.dumps(doc, sort_keys=True))
        except Exception as e:
            print("traders: skip feed not written (%s)" % type(e).__name__, file=sys.stderr)
        return 0
    now = a.now if a.now is not None else int(time.time() * 1000)
    if a.cmd == "run":
        print(json.dumps(run(a.dir, now), separators=(",", ":")), flush=True)
        return 0
    L = load(a.dir, now)
    L.pop("trades", None)
    L.pop("feed", None)
    print(json.dumps(L, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
