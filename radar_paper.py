#!/usr/bin/env python3
"""radar_paper.py: the radar account. Fake money only: nothing is ever bought, and nothing the trader, the training or the big test
reads comes from here (the paper account of memebot.py and its docs db/memepos, db/memeexit stay exactly as they are).

What it does: the best 5 of the radar's first round in each UTC hour are bought on paper for TICKET (3 EUR) each, at the price the
radar saw, at the round's time, and so is every coin the radar listed as good in any round (good among that round's best 5; the radar
makes a round every 2 minutes, and every round's best 5 would be 25 or more buys an hour, more than the peaks job can price). A coin is bought at most once (in its first
such round; a coin bought before is skipped, no digging deeper). Each buy is marked green when the radar rated it good in that round.
Two accounts are summed from the same buys: "all 5" and "green only". That is rule 1 (v1), for radar rounds before the switch
(memebot.switch_at()); it is history now and outside the three paper traders (traders.py).

Rule 2 (v2), from the switch on: every coin the radar rates good and push-worthy while its pool is under 10 minutes old is bought on paper
for RADAR_TICKET (10 EUR), at its first such rating (that rating's time and price), once (its own one-coin-one-buy set: a v1 buy of the
same coin never blocks it). Its doc carries rule 2, an id ending "-g", the rating's points and upside, the first sight and whether the
green came later ("late"), and "feat": the signs it had at the buy (feat_of: traps flags on the first-sight signals sig0 and the six
signs of the user's rug complaint, a1_of), copied so they outlive the 30 days the radar records are kept. A v2 take-profit is booked at
exactly 11x (as memebot books it), v2 windows are priced before the v1 backlog, and each priced v2 window also gets its minute path
(peak.write_path, db/memepath). The learning trader reads only buy-time fields (never later, out, peak60, mom or push).

Where the buys come from: the radar's hour docs db/memeradar/<UTC hour>.json (launch_radar.py; the scan's step A imports them into
the results branch, which keeps 30 days). A record with "top" was among a round's best 5 at least once; its ratings rt
[[round time, verdict, points, push, price, upside], ...] (older records: the first four) say in which rounds it was rated. A round
is one rating time. Its best 5: the records with "top" rated at that time while their pool was under 10 minutes old (30 s of clock
slack), in launch_radar.rank's order as far as a record keeps it: that round's verdict (good, watch, trap), then its points (fewer
first), then the liquidity at first sight (more first), then the address. The upside score (older records lack it) and the liquidity
at that round (no record keeps it) are not used, so two good coins of one round, or two coins with the same points at places 5 and 6,
can stand in another order than on the radar's list.
The price: the record's px (DexScreener at first sight) when the buy round is the coin's first sight, else none (then the minute
candle's close is the price paid). Once a coin has a doc here, the doc is the buy: a later run never moves it to another round.

How a buy is sold (the paper account's rules, memebot.HOLD_STOP / HOLD_TP / HOLD_MAX_H, replayed on GeckoTerminal minute candles of
the coin's pool from the entry, through peak.py's glitch rules):
  - the price paid: peak.py's base, max(first close, radar price) when they are within 3x of each other, else the first close
    (it never flatters)
  - stop: the first minute whose close is at or below 0.70x; a close the next real close within 5 minutes took back counts only
    down to that next close (one glitch print sells nothing), a close no real close followed within 5 minutes stands; booked at
    that level
  - take-profit: the first level of 11x or more that peak.py's filter accepts (a close confirmed by the next close within 5
    minutes, a jump over 3x or a level over 30x or a $100M market cap only with support); booked at that level (the close, not 11x)
  - whichever comes first; else sold at the close at 6 hours (peak.py's x6: a dust print can lower it, never raise it)
  - closes only, never wicks; a candle under $25 of volume is no price; a pool that died inside the window (collapse, liquidity
    floor, a later DexScreener point that found it gone) before a sale is a total loss at that time (why "rug")
  - the money: memebot.pos_value on a young paper position of TICKET: both paper fees (1%, at least 0.10 each)
Next to the result each doc keeps peak.py's best within 6 h (x and its euros) and the raw best close (rawX, unfiltered, with the cut
list): hindsight, never part of the account.

Doc states (db/memeradarpaper/<id>.json, one per buy; written whole by a rename; kept by bot.py prune, synced to the results branch):
  open     inside its 6 hours (nothing to price yet)
  waiting  its 6 hours are over, not priced yet ("tries" counts the empty answers)
  closed   priced: why "stop" | "tp" | "time" | "rug", x (the sale over the price paid), eur (what came back), pnl
  void     not priced and never will be: why "unit" (the candles are in another unit than DexScreener's price) or "nodata" (no
           candles after MAX_TRIES empty answers, and nothing showed the pool died)
A closed or void doc is never rewritten unless RP_V changes. A failed request (5xx, timeout, 429s) never settles a window under
EST_AFTER_H past its end; an older one counts it as a try.

The budget: this runs inside the peaks job, from peak.run, before peak.py's own windows and on its GeckoTerminal client (the 10 s
gap and what each 429 adds to it, the cooldowns and a host given up stay in force), at most MAX_ITEMS windows a run, oldest first,
until its share of the deadline (peak.radar_until: 40%, at most 240 s) or of the run's 429s (peak.RADAR_MAX_429: 3 of the 8 after
which GeckoTerminal is given up) is used; then peak.py's windows get the rest. The window the last 429 met waits for a later run
like one not asked (no try counted). With nothing to price it asks nothing and takes no time from them.

Usage:
  python3 radar_paper.py run --dir mb [--now <ms>] [--deadline-s 150] [--mock URL]   -> one JSON line (the run's summary)
  python3 radar_paper.py summary --dir mb [--now <ms>]                                -> the accounts (rule 1: all 5, green; rule 2) as JSON
"""
import argparse, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: paper fees (pos_value), the paper rules, load_docs, slug, switch_at
import peak as P         # read only: the candle fetch and its pacing, peak_of (the glitch rules), load_candles, dead_of, write_path
import traps             # read only: flag and load_weights (the signs a v2 buy copies at the buy)

RP_V = 1                    # the doc version: a closed or void doc is priced again only when this changes
COLL = "memeradarpaper"
TICKET = M.YOUNG_TICKET     # 3 EUR, the new-launch ticket of the paper account (rule 1, before the switch)
RADAR_TICKET = 10.0         # rule 2 (from the switch): 10 EUR on every coin rated good and push-worthy
BEST_N = 5                  # launch_radar.BEST_N: a round's best 5
MIN, H = 60_000, 3_600_000
WINDOW_MS = int(M.HOLD_MAX_H * H)
SETTLE_MS = P.SETTLE_MS     # a window counts once now >= end + 2 min
STOP_X = 1.0 - M.HOLD_STOP  # 0.70
TP_X = 1.0 + M.HOLD_TP      # 11.0
AGE_MAX_MS = int(10 * MIN)     # launch_radar.MAX_AGE_MIN: a pool under 10 minutes is on the radar (a later rating is for the record only)
MAX_ITEMS = 15              # windows a run asks GeckoTerminal for (oldest first), before peak.py's own
MAX_TRIES = P.MAX_TRIES     # empty answers before a window is estimated
EST_AFTER_H = P.EST_AFTER_H
VRANK = {"good": 0, "watch": 1, "trap": 2}
STATES = ("open", "waiting", "closed", "void")
WHYS = ("stop", "tp", "time", "rug")
DOC_KEYS = ("v", "id", "addr", "sym", "name", "pair", "round", "entryAt", "end", "upd", "px", "liq", "mc", "green", "verdict", "pts", "rank",
            "ticket", "state", "src", "res", "tries", "base", "why", "exitAt", "x", "eur", "pnl", "best", "bestAt", "eurBest", "rawX", "eurRaw",
            "x6", "dead", "cut", "n", "rule", "first", "late", "up", "feat", "pushAt")
# the traps flags a v2 buy copies from the record's first-sight signals (sig0), frozen with the learning trader's T3_V = 1
RADAR_FEATS = ("no_socials", "bot_volume", "pumping_5m", "young_5m", "x_and_paid", "tweet", "lists3", "creator_5pct", "mc_500k", "liq_15pct",
               "dev_dead", "dev_young", "x_copied", "tweet_shared", "sniped30", "bundle_slot", "fresh_holders", "fund_cluster", "staircase10")
# the six signs of the user's rug complaint (15 Oct, the spec's A1), read at the green rating (a1_of); A1's no_socials (no socials and no
# X link) takes the place of the traps flag of that name in "feat"
RADAR_A1 = ("creator_holds", "serial_dev", "falling", "no_socials", "was_trap", "long_curve")
A1_CREATOR_PCT, A1_DEV_N, A1_FALL_M5, A1_CURVE_S = 5.0, 100, -10.0, 24 * 3600
LATE_MS = 60_000            # a green more than a minute after first sight is "late" (no traps found only after first sight)


def paper(ticket):
    """The fee model of a buy of this ticket (memebot.pos_value): a young paper position."""
    return {"ticket": ticket, "grp": "young", "paper": M.PAPER_RULE}


PAPER = paper(TICKET)       # the fee model of a rule-1 buy


def num(v):
    return M.num(v)


def value(x, ticket=TICKET):
    """What a buy of this ticket (3 EUR under rule 1, 10 under rule 2) brings back sold at x times the price paid, after both paper fees."""
    return round(M.pos_value(paper(ticket), 1.0, x), 2) if x is not None else None


def _tri(v):
    return v if isinstance(v, bool) else None


def a1_of(rec, t):
    """The six signs of A1 for a buy at rating time t, {name: True | False | None (unknown)}, from buy-time fields only: the signals of
    the green rating (sigG, which launch_radar keeps from the first push-worthy good rating on, with its time sigGt) when that rating was
    at or before t, else those of first sight (sig0, before the buy too: a rule-1 green bought before its first push-worthy rating, a
    record without sigGt), and the ratings before t. Never sig, later, out, peak60, mom or push.
      creator_holds  the creator still held over 5%        serial_dev  the creator launched 100 coins or more
      falling        DexScreener's 5-minute change at -10% or lower
      no_socials     no socials and no X link              was_trap    a rating "trap" before the green one
      long_curve     more than 24 h from the mint to the pool"""
    rec = rec if isinstance(rec, dict) else {}
    gt = num(rec.get("sigGt"))
    s = rec.get("sigG") if isinstance(rec.get("sigG"), dict) and gt is not None and gt <= t else rec.get("sig0")
    s = s if isinstance(s, dict) else {}
    n = lambda k: num(s.get(k))
    cp, dev, m5, soc, mtp, x = n("creatorPct"), n("devN"), n("m5"), n("socN"), n("mintToPoolS"), s.get("x")
    if isinstance(x, str) and x:
        nosoc = False                       # an X link is a social
    elif soc is None or not isinstance(x, str):
        nosoc = None
    else:
        nosoc = soc <= 0
    rt = [e for e in (rec.get("rt") if isinstance(rec.get("rt"), list) else []) if isinstance(e, (list, tuple)) and len(e) >= 2 and num(e[0]) is not None]
    return {"creator_holds": None if cp is None else cp > A1_CREATOR_PCT, "serial_dev": None if dev is None else dev >= A1_DEV_N,
            "falling": None if m5 is None else m5 <= A1_FALL_M5, "no_socials": nosoc, "was_trap": any(num(e[0]) < t and e[1] == "trap" for e in rt),
            "long_curve": None if mtp is None else mtp > A1_CURVE_S}


def feat_of(rec, t, W=None):
    """The signs a v2 buy at rating time t copies into its doc: {name: True | False | None} for the traps flags of RADAR_FEATS on the
    record's first-sight signals (sig0; all None without them), then the six of A1 (a1_of)."""
    W = W or traps.load_weights()
    s0 = rec.get("sig0") if isinstance(rec, dict) and isinstance(rec.get("sig0"), dict) else None
    out = {k: (_tri(traps.flag(k, s0, W)) if s0 is not None else None) for k in RADAR_FEATS}
    out.update(a1_of(rec, t))
    return out


def signs(feat, pts, late):
    """The learning trader's radar signs of one buy (traders.SKIP_FLAGS["radar"], launch_radar's push check), from what the buy stored:
    "feat:<name>" for each traps flag of RADAR_FEATS (A1's no_socials stands under its own name), the six of A1, "pts2" (2 or more
    warning points at the buy rating) and "late" (the green came more than a minute after first sight). None: unknown."""
    f = feat if isinstance(feat, dict) else {}
    out = {"feat:" + k: _tri(f.get(k)) for k in RADAR_FEATS if k not in RADAR_A1}
    out.update({k: _tri(f.get(k)) for k in RADAR_A1})
    out["pts2"] = None if num(pts) is None else num(pts) >= 2
    out["late"] = _tri(late)
    return out


def buy_id(t, sym, addr):
    """<UTC minute of the round>-<ticker>-<first 8 address characters>: a file name, and in time order."""
    return "%s-%s-%s" % (time.strftime("%Y-%m-%dT%H%M", time.gmtime(int(t) // 1000)), M.slug(sym, 12), re.sub(r"[^A-Za-z0-9]", "", str(addr))[:8] or "X")


# ---------------------------------------------------------------- the buys (pure)
def records(d):
    """Every radar record of the hour docs, in file name order (a record of an unexpected shape is skipped)."""
    out = []
    for _, doc in sorted(M.load_docs(d, "memeradar").items()):
        coins = doc.get("coins") if isinstance(doc, dict) else None
        if isinstance(coins, dict):
            out += [rec for _, rec in sorted(coins.items()) if isinstance(rec, dict) and isinstance(rec.get("addr"), str) and rec["addr"]]
    return out


def rounds_of(recs):
    """{round time ms: [candidate, ...]}: the records with "top" rated in that round while their pool was under 10 minutes old.
    A candidate: (verdict rank, points, -liquidity, addr, verdict, record)."""
    out = {}
    for rec in recs:
        if not rec.get("top") or not isinstance(rec.get("rt"), list):
            continue
        pool = num(rec.get("pool"))
        liq = num(rec.get("liq")) or 0.0
        for e in rec["rt"]:
            if not isinstance(e, (list, tuple)) or len(e) < 2 or not num(e[0]):
                continue
            t = int(num(e[0]))
            if pool and t - pool >= AGE_MAX_MS:
                continue                    # rated for the record after it left the radar (a pending check): not in that round's list
            v = e[1] if e[1] in VRANK else "watch"
            pts = num(e[2]) if len(e) > 2 else None
            out.setdefault(t, []).append((VRANK[v], 99.0 if pts is None else pts, -liq, rec["addr"], v, rec))
    return out


def ranked(cands):
    """A round's candidates in the radar's order, each coin once."""
    out, seen = [], set()
    for c in sorted(cands, key=lambda c: c[:4]):
        if c[3] not in seen:
            seen.add(c[3])
            out.append(c)
    return out


def counted(t, first_of_hour):
    """Whether all of round t's best 5 are bought: the first round of its UTC hour (else only its coins rated good)."""
    return first_of_hour.get(int(t // H)) == t


def buys_of(recs, have=(), switch=None, have2=()):
    """The buys of both rules. Rule 1, {addr: buy}, rounds before the switch only (switch: ms, default memebot.switch_at()): every coin
    among the best 5 of the first round of a UTC hour and every coin rated good among a round's best 5, in its first such round, except
    the coins in have (they already have a rule-1 doc). A buy: id, addr, sym, name, pair, round, entryAt, end, px (the radar's price when
    the round is its first sight), liq, mc, green, verdict, pts, rank (1 to 5 in its round), ticket, rule, and _rec (the record, for its
    later DexScreener points). Rule 2, {id: buy}, from the switch: buys_v2 (have2: the coins with a rule-2 doc)."""
    switch = M.switch_at() if switch is None else int(switch)
    rounds, out, have, hour_first = rounds_of(recs), {}, set(have), {}
    for t in sorted(rounds):
        hour_first.setdefault(int(t // H), t)
    for t in sorted(rounds):
        if t >= switch:
            break                           # rule 1 ends at the switch: a round after it buys nothing here (a v1 doc of old code stays history)
        every = counted(t, hour_first)
        for rank, (_, _, _, a, v, rec) in enumerate(ranked(rounds[t])[:BEST_N], 1):
            if a in out or a in have or not (every or v == "good"):
                continue
            first = num(rec.get("first"))
            out[a] = {"id": buy_id(t, rec.get("sym"), a), "addr": a, "sym": str(rec.get("sym") or "?")[:24], "name": str(rec.get("name") or "")[:48],
                      "pair": rec.get("pair") if isinstance(rec.get("pair"), str) and rec.get("pair") else None, "round": t, "entryAt": t,
                      "end": t + WINDOW_MS, "px": num(rec.get("px")) if first is not None and int(first) == t else None, "liq": num(rec.get("liq")),
                      "mc": num(rec.get("mc")), "green": v == "good", "verdict": v, "pts": next((num(e[2]) for e in rec["rt"] if isinstance(e, (list, tuple))
                                                                                                  and len(e) > 2 and num(e[0]) == t), None),
                      "rank": rank, "ticket": TICKET, "rule": 1, "_rec": rec}
    out.update(buys_v2(recs, have2, switch))
    return out


def buys_v2(recs, have2=(), switch=None):
    """{id: buy} of rule 2: per coin (its records grouped by address, their ratings merged in time order) the first rating at or after the
    switch that is good, push-worthy (rt[3] == 1) and made while the pool was under 10 minutes old (an unknown pool counts), unless the
    coin has a rule-2 doc (have2). The buy is at that rating's time and price (none: the first candle's close, as in rule 1), for
    RADAR_TICKET, with its points and upside, the record's first sight and first-sight liquidity and market cap, late (the green more than
    a minute after first sight), feat (feat_of, buy-time fields only) and pushAt (when the phone heard of it: information, never a sign)."""
    switch = M.switch_at() if switch is None else int(switch)
    have2, by = set(have2), {}
    for rec in recs:
        if isinstance(rec.get("rt"), list):
            by.setdefault(rec["addr"], []).append(rec)
    out, W = {}, None
    for a in sorted(by):
        if a in have2:
            continue
        rows = sorted(((int(num(e[0])), i, e, rec) for i, rec in enumerate(by[a]) for e in rec["rt"]
                       if isinstance(e, (list, tuple)) and len(e) >= 2 and num(e[0])), key=lambda q: (q[0], q[1]))
        hit = None
        for t, _, e, rec in rows:
            pool = num(rec.get("pool"))
            if t >= switch and e[1] == "good" and len(e) >= 4 and int(num(e[3]) or 0) == 1 and (not pool or t - pool < AGE_MAX_MS):
                hit = (t, e, rec)
                break
        if hit is None:
            continue
        t, e, rec = hit
        W = W or traps.load_weights()
        merged = dict(rec, rt=[q[2] for q in rows])           # the coin's ratings from all its records, for "was_trap"
        first = num(rec.get("first"))
        b = {"id": buy_id(t, rec.get("sym"), a) + "-g", "addr": a, "sym": str(rec.get("sym") or "?")[:24], "name": str(rec.get("name") or "")[:48],
             "pair": rec.get("pair") if isinstance(rec.get("pair"), str) and rec.get("pair") else None, "round": t, "entryAt": t, "end": t + WINDOW_MS,
             "px": num(e[4]) if len(e) > 4 else None, "liq": num(rec.get("liq")), "mc": num(rec.get("mc")), "green": True, "verdict": "good",
             "pts": num(e[2]) if len(e) > 2 else None, "rank": None, "ticket": RADAR_TICKET, "rule": 2, "first": first,
             "late": first is not None and t - first > LATE_MS, "up": num(e[5]) if len(e) > 5 else None, "feat": feat_of(merged, t, W),
             "pushAt": num(rec.get("push")), "_rec": rec}
        out[b["id"]] = b
    return out


def later_points(rec):
    """A record's DexScreener observations as peak.peak_of's ds_points [(ms, price or None, liquidity or None)]: the first sight and
    the later prices; a pool found gone is (ms, None, 0), so the glitch filter and dead_of see a dead pool."""
    if not isinstance(rec, dict):
        return []
    out = []
    if num(rec.get("first")):
        out.append((int(num(rec["first"])), num(rec.get("px")), num(rec.get("liq"))))
    for o in (rec.get("later") or {}).values() if isinstance(rec.get("later"), dict) else ():
        if isinstance(o, dict) and num(o.get("t")):
            out.append((int(num(o["t"])), None, 0.0) if o.get("gone") else (int(num(o["t"])), num(o.get("px")), num(o.get("liq"))))
    return sorted(out, key=lambda q: (q[0], -1.0 if q[1] is None else q[1], -1.0 if q[2] is None else q[2]))


# ---------------------------------------------------------------- the sale (pure)
def exit_of(r, cands, entry_at, end, levels, res=1, exact_tp=False):
    """The paper rules on one window, after peak.peak_of (r, state ok, with levels: the levels its filter accepted). exact_tp (rule 2): a
    take-profit is booked at exactly TP_X, as memebot books it (rule 1 keeps the accepted level).
    -> {"why": "stop" | "tp" | "time" | "rug", "x": the sale over the price paid (peak's base), "exitAt": ms, "note": text or ""}"""
    base = r["base"]
    dead_at = r["dead"]["at"] if isinstance(r.get("dead"), dict) else None
    R = int(res or 1) * MIN
    gap = max(P.CONFIRM_MIN, int(res or 1)) * MIN
    win = [c for c in P._rows(cands) if c[0] >= entry_at - R and c[0] + R <= end and (dead_at is None or c[0] < dead_at)]
    clean = [c for c in win if c[5] is None or c[5] >= P.DUST_VOL]
    stop = None
    for j, c in enumerate(clean):
        lv = c[4] / base
        nxt = clean[j + 1] if j + 1 < len(clean) else None
        if nxt is not None and nxt[0] - c[0] <= gap:
            lv = max(lv, nxt[4] / base)         # one print the next real close took back is no stop
        if lv <= STOP_X + 1e-12:
            stop = (int(c[0]), lv)
            break
    tp = next(((int(t), lv) for t, lv in levels or () if lv >= TP_X - 1e-12 and (dead_at is None or t < dead_at)), None)
    hits = sorted([(h[0], k, h[1]) for k, h in (("stop", stop), ("tp", tp)) if h is not None])
    if hits:
        t, why, lv = hits[0]
        if exact_tp and why == "tp":
            lv = TP_X
        return {"why": why, "x": P.sig(lv), "exitAt": max(int(t), int(entry_at)), "note": ""}
    if dead_at is not None:
        return {"why": "rug", "x": 0.0, "exitAt": int(dead_at), "note": ""}
    if r.get("x6") is None:                     # candles, but none with $25 of volume in 6 hours: nothing could be sold
        return {"why": "rug", "x": 0.0, "exitAt": int(end), "note": "no minute with $%g of volume" % P.DUST_VOL}
    return {"why": "time", "x": P.sig(r["x6"]), "exitAt": int(end), "note": ""}


def price(cands, b, res=1):
    """One buy on its candles: {"state": "closed" | "void", ...} or None when no candle lies inside the window."""
    levels = []
    rec = b.get("_rec")
    r = P.peak_of(cands, b["entryAt"], b["end"], b.get("px"), None, later_points(rec), liq0=b.get("liq"), mc0=b.get("mc"), res=res, levels=levels)
    if r["state"] == "waiting":
        return None
    out = {"base": r.get("base"), "cpx": r.get("cpx"), "rawX": r.get("rawX"), "cut": list(r.get("cut") or [])[:8], "n": int(r.get("n") or 0), "res": int(res or 1)}
    if r["state"] == "unit":
        return dict(out, state="void", why="unit")
    ex = exit_of(r, cands, b["entryAt"], b["end"], levels, res, exact_tp=(b.get("rule") == 2))
    if ex["note"]:
        out["cut"] = (out["cut"] + [ex["note"]])[:8]
    return dict(out, state="closed", why=ex["why"], x=ex["x"], exitAt=ex["exitAt"], best=r.get("x"), bestAt=r.get("at"), x6=r.get("x6"), dead=r.get("dead"))


def estimate(b):
    """No candles after MAX_TRIES (or an empty answer EST_AFTER_H after the end): a total loss when the radar's own later prices
    found the pool dead inside the window (gone, or liquidity under peak.py's floor), else void: never priced."""
    dead = P.dead_of(b["entryAt"], b["end"], None, later_points(b.get("_rec")), b.get("liq"))
    if dead is not None:
        return {"state": "closed", "why": "rug", "x": 0.0, "exitAt": int(dead[0]), "cut": [dead[2]], "base": b.get("px"), "n": 0,
                "dead": {"at": int(dead[0]), "why": dead[1]}}
    return {"state": "void", "why": "nodata", "cut": [], "n": 0}


# ---------------------------------------------------------------- the docs
def doc_of(b, now, state, tries=0, src=None, r=None):
    """The doc of one buy in DOC_KEYS order; r: the result of price() or estimate()."""
    r = r or {}
    ticket = num(b.get("ticket")) or TICKET
    x = r.get("x") if state == "closed" else None
    eur = value(x, ticket) if x is not None else None
    best = r.get("best") if state == "closed" else None
    raw = r.get("rawX")
    doc = {"v": RP_V, "id": b["id"], "addr": b["addr"], "sym": b.get("sym"), "name": b.get("name"), "pair": b.get("pair"), "round": b["round"],
           "entryAt": b["entryAt"], "end": b["end"], "upd": int(now), "px": b.get("px"), "liq": b.get("liq"), "mc": b.get("mc"),
           "green": bool(b.get("green")), "verdict": b.get("verdict"), "pts": b.get("pts"), "rank": b.get("rank"), "ticket": ticket,
           "state": state, "src": src, "res": r.get("res") if src in ("m1", "m15") else None, "tries": int(tries),
           "base": r.get("base"), "why": r.get("why") if state in ("closed", "void") else None, "exitAt": r.get("exitAt") if state == "closed" else None,
           "x": x, "eur": eur, "pnl": round(eur - ticket, 2) if eur is not None else None, "best": best,
           "bestAt": r.get("bestAt") if best is not None else None, "eurBest": value(best, ticket) if best is not None else None,
           "rawX": raw, "eurRaw": value(raw, ticket) if raw is not None and state == "closed" else None, "x6": r.get("x6") if state == "closed" else None,
           "dead": r.get("dead") if state == "closed" else None, "cut": list(r.get("cut") or [])[:8], "n": int(r.get("n") or 0),
           "rule": 2 if b.get("rule") == 2 else 1, "first": b.get("first"), "late": b.get("late"), "up": b.get("up"),
           "feat": b.get("feat") if isinstance(b.get("feat"), dict) else None, "pushAt": b.get("pushAt")}
    return {k: doc.get(k) for k in DOC_KEYS}


def load_docs(d):
    """The radar account's docs {id: doc}, the readable ones only (an id, an address, a known state, a round time)."""
    out = {}
    for key, doc in M.load_docs(d, COLL).items():
        if isinstance(doc, dict) and isinstance(doc.get("addr"), str) and doc["addr"] and doc.get("state") in STATES and num(doc.get("round")):
            out[key] = doc
    return out


def settled(doc):
    return isinstance(doc, dict) and doc.get("v") == RP_V and doc.get("state") in ("closed", "void")


def write_doc(d, key, doc):
    """db/memeradarpaper/<id>.json, written whole or not at all (a temp file outside the synced folder, then a rename)."""
    tmp_dir, out_dir = os.path.join(d, ".rptmp"), os.path.join(d, "db", COLL)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(tmp_dir, key + ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, os.path.join(out_dir, key + ".json"))


def all_buys(d, switch=None):
    """(buys {id: buy}, docs {id: doc}): the docs' buys (a doc is the buy; its record joined by address for the later prices) plus
    the new ones from the records (buys_of; switch as there). One coin, one buy per rule: a rule-1 doc never blocks a rule-2 buy."""
    recs, docs = records(d), load_docs(d)
    by_addr = {}
    for rec in recs:
        by_addr.setdefault(rec["addr"], rec)
    buys, have = {}, {1: set(), 2: set()}
    for key, doc in sorted(docs.items(), key=lambda kv: (num(kv[1].get("round")), kv[0])):
        rule = 2 if doc.get("rule") == 2 else 1
        if doc["addr"] in have[rule]:
            continue                        # one coin, one buy: a second doc of the same coin (and rule) is ignored
        have[rule].add(doc["addr"])
        t = int(num(doc["round"]))
        buys[key] = {"id": key, "addr": doc["addr"], "sym": str(doc.get("sym") or "?")[:24], "name": str(doc.get("name") or "")[:48],
                     "pair": doc.get("pair") if isinstance(doc.get("pair"), str) and doc.get("pair") else None, "round": t,
                     "entryAt": int(num(doc.get("entryAt")) or t), "end": int(num(doc.get("end")) or t + WINDOW_MS), "px": num(doc.get("px")),
                     "liq": num(doc.get("liq")), "mc": num(doc.get("mc")), "green": doc.get("green") is True, "verdict": doc.get("verdict"),
                     "pts": num(doc.get("pts")), "rank": num(doc.get("rank")), "ticket": num(doc.get("ticket")) or (RADAR_TICKET if rule == 2 else TICKET),
                     "rule": rule, "first": num(doc.get("first")), "late": doc.get("late") if isinstance(doc.get("late"), bool) else None,
                     "up": num(doc.get("up")), "feat": doc.get("feat") if isinstance(doc.get("feat"), dict) else None, "pushAt": num(doc.get("pushAt")),
                     "_rec": by_addr.get(doc["addr"])}
    for b in buys_of(recs, have[1], switch, have[2]).values():
        buys[b["id"]] = b
    return buys, docs


def items(buys, docs, now):
    """The windows to price this run: closed windows without a settled doc and with fewer than MAX_TRIES empty answers, rule 2 first,
    oldest first within a rule, at most MAX_ITEMS. -> [peak.fetch item]"""
    todo = []
    for key, b in buys.items():
        if now < b["end"] + SETTLE_MS or settled(docs.get(key)):
            continue
        old = docs.get(key)
        tries = int(num(old.get("tries")) or 0) if isinstance(old, dict) and old.get("v") == RP_V and old.get("state") == "waiting" else 0
        if tries >= MAX_TRIES:
            continue
        todo.append({"pid": key, "pool": b.get("pair") or "", "key": "rp%d" % (b["entryAt"] // MIN), "entryAt": b["entryAt"], "end": b["end"], "tries": tries,
                     "rule": 2 if b.get("rule") == 2 else 1})
    todo.sort(key=lambda it: (0 if it["rule"] == 2 else 1, it["entryAt"], it["pid"]))     # rule 2 first, then the rule-1 backlog
    return todo[:MAX_ITEMS]


def book(d, b, info, now, old):
    """The doc of one asked window from this run's fetch result; None when nothing was learned (a failed fetch of a window under
    EST_AFTER_H past its end: its doc stays)."""
    same = isinstance(old, dict) and old.get("v") == RP_V and old.get("state") == "waiting"
    tries = int(num(old.get("tries")) or 0) if same else 0
    status = (info or {}).get("status")
    old_w = now >= b["end"] + EST_AFTER_H * H
    if status not in ("ok", "empty", "nopool", "error") or (status == "error" and not old_w):
        return None
    if status == "ok":
        res = int(info.get("res") or 1)
        cands = P.load_candles(d, b.get("pair"), info["key"])
        r = price(cands, b, res)
        if r is not None:
            if res == 1 and r["state"] == "closed":
                try:                        # the minute path for exact replays (db/memepath, written once; it never fails the booking)
                    P.write_path(d, "radar", b["id"], cands, b["entryAt"], b["end"], r)
                except Exception as e:
                    print("radar account: no path for %s (%s)" % (b["id"], type(e).__name__), file=sys.stderr)
            return doc_of(b, now, r["state"], tries, "m15" if res == 15 else "m1", r)
        status = "empty"
    tries = MAX_TRIES if status == "nopool" else tries + 1
    if tries >= MAX_TRIES or (old_w and status == "empty"):
        r = estimate(b)
        return doc_of(b, now, r["state"], tries, "est", r)
    return doc_of(b, now, "waiting", tries)


def run(d, now, http=None, mock=None, until=None, log=None, max_items=None, max_429=None):
    """The buys of the radar rounds -> open and waiting docs, then GeckoTerminal minute candles for at most MAX_ITEMS closed windows
    (oldest first) until `until` (epoch s) or max_429 more 429s (peak.fetch: peak.run passes RADAR_MAX_429; None, as on its own
    command line: up to fetch.Http's limit) -> closed or void docs. -> the summary dict."""
    t0 = time.time()
    log = log or (lambda s: print(s, file=sys.stderr, flush=True))
    until = t0 + 150.0 if until is None else until
    buys, docs = all_buys(d)
    its = items(buys, docs, now)[:MAX_ITEMS if max_items is None else max_items]
    fetched, why = {}, "no window to price"
    counts = {"closed": 0, "void": 0, "waiting": 0, "open": 0}
    if its:
        if http is None:
            http = P.F.Http(mock, pause=0, log=log)
        log("radar account: %d bought in all, %d closed windows to price (oldest first, at most %d a run), %.0f s left" % (
            len(buys), len(its), MAX_ITEMS, max(0.0, until - time.time())))
        fetched, why = P.fetch(http, d, its, until, {}, max_429=max_429)
    written = set()
    for key, info in sorted(fetched.items()):
        old = docs.get(key)
        if settled(old):
            continue
        doc = book(d, buys[key], info, now, old)
        if doc is None:
            continue
        write_doc(d, key, doc)
        docs[key] = doc
        written.add(key)
        counts[doc["state"]] += 1
    for key, b in sorted(buys.items()):     # the other buys without a settled doc: open inside their 6 hours, waiting after them
        old = docs.get(key)
        if key in written or settled(old):
            continue
        state = "open" if now < b["end"] + SETTLE_MS else "waiting"
        same = isinstance(old, dict) and old.get("v") == RP_V and old.get("state") == state
        if same:
            continue
        tries = int(num(old.get("tries")) or 0) if isinstance(old, dict) and old.get("v") == RP_V and old.get("state") == "waiting" else 0
        write_doc(d, key, doc_of(b, now, state, tries))
        counts[state] += 1
    out = {"buys": len(buys), "items": len(its), "closed": counts["closed"], "void": counts["void"], "waiting": counts["waiting"], "open": counts["open"],
           "why": why, "secs": round(time.time() - t0, 1)}
    log("radar account: %d bought, %d priced now (%d void), %d new open, %d waiting; %s (%.0f s)" % (
        out["buys"], counts["closed"], counts["void"], counts["open"], counts["waiting"], why, out["secs"]))
    return out


# ---------------------------------------------------------------- the two accounts (for the page)
def stats(rows):
    """One account over buy rows: invested, back and P/L over the sold ones, won, lost, the win rate, n sold, open (inside 6 h),
    pricing (6 h over, not priced yet), void, the best and worst trade, and the same buys in hindsight: sold at the best within
    6 h (hind) and at the raw best close (raw; rawCut: how many of them peak.py's filter did not accept)."""
    sold = [r for r in rows if r["state"] == "closed" and r.get("eur") is not None]
    inv = round(sum(r["ticket"] for r in sold), 2)
    back = round(sum(r["eur"] for r in sold), 2)
    won = sum(1 for r in sold if r["eur"] > r["ticket"])
    key = lambda r: (r["eur"] - r["ticket"], r["entryAt"], r["id"])
    hind = [r for r in sold if r.get("eurBest") is not None]
    raw = lambda r: r["eurRaw"] if r.get("eurRaw") is not None and r["eurRaw"] >= r["eurBest"] else r["eurBest"]
    return {"n": len(sold), "invested": inv, "back": back, "pnl": round(back - inv, 2), "won": won, "lost": len(sold) - won,
            "winRate": won / len(sold) if sold else None, "open": sum(1 for r in rows if r["state"] == "open"),
            "pricing": sum(1 for r in rows if r["state"] == "pricing"), "void": sum(1 for r in rows if r["state"] == "void"), "all": len(rows),
            "best": max(sold, key=key) if sold else None, "worst": min(sold, key=key) if sold else None,
            "hindN": len(hind), "hind": round(sum(r["eurBest"] - r["ticket"] for r in hind), 2) if hind else None,
            "raw": round(sum(raw(r) - r["ticket"] for r in hind), 2) if hind else None,
            "rawCut": sum(1 for r in hind if raw_cut(r))}


def raw_cut(r):
    """Whether a sold buy's raw best close is more than 5% over the best peak.py's filter accepted (it was not sellable there)."""
    raw, best = num(r.get("rawX")), num(r.get("best"))
    return raw is not None and best is not None and raw > 1.05 * best


def account(d, now, switch=None):
    """The radar account for the page: {"rows" (rule 1, newest first), "all" and "green" (stats over rule 1: the 3 EUR history),
    "v2" (stats over rule 2: 10 EUR on the greens from the switch), "rows2" (rule 2, newest first), "rounds" (radar rounds in the
    records), "lastRound" (ms or None), "err"}. Each row carries its ticket, rule, late, feat and pushAt. Reads only; never raises (an
    error leaves empty accounts with "err")."""
    try:
        return _account(d, now, switch)
    except Exception as e:      # the page must never fail on this block
        return {"rows": [], "all": stats([]), "green": stats([]), "v2": stats([]), "rows2": [], "rounds": 0, "lastRound": None,
                "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _account(d, now, switch=None):
    buys, docs = all_buys(d, switch)
    rows = []
    for key, b in buys.items():
        doc = docs.get(key) if isinstance(docs.get(key), dict) and docs[key].get("v") == RP_V else None
        st = doc.get("state") if doc else None
        if st not in ("closed", "void"):
            st = "open" if now < b["end"] + SETTLE_MS else "pricing"
        g = lambda k: num(doc.get(k)) if doc else None
        eur = g("eur") if st == "closed" else None
        if st == "closed" and (eur is None or eur < 0 or doc.get("why") not in WHYS):
            st = "pricing"                  # an unreadable result is never booked
            eur = None
        ticket = num(b.get("ticket")) or TICKET
        rows.append({"id": key, "addr": b["addr"], "sym": b["sym"], "name": b["name"], "green": bool(b.get("green")), "verdict": b.get("verdict"),
                     "rank": b.get("rank"), "round": b["round"], "entryAt": b["entryAt"], "end": b["end"], "ticket": ticket, "state": st,
                     "rule": 2 if b.get("rule") == 2 else 1, "late": b.get("late"), "feat": b.get("feat"), "pushAt": b.get("pushAt"),
                     "why": doc.get("why") if doc and st in ("closed", "void") else None, "exitAt": g("exitAt") if st == "closed" else None,
                     "x": g("x") if st == "closed" else None, "eur": eur, "pnl": round(eur - ticket, 2) if eur is not None else None,
                     "best": g("best") if st == "closed" else None, "eurBest": g("eurBest") if st == "closed" else None,
                     "rawX": g("rawX") if st == "closed" else None, "eurRaw": g("eurRaw") if st == "closed" else None,
                     "src": doc.get("src") if doc else None, "cut": [str(c)[:120] for c in doc.get("cut") or [] if isinstance(c, (str, int, float))][:8]
                     if doc and isinstance(doc.get("cut"), list) else []})
    rows.sort(key=lambda r: (-r["entryAt"], r["id"]))
    rows2 = [r for r in rows if r["rule"] == 2]
    rows = [r for r in rows if r["rule"] != 2]
    times = {int(num(e[0])) for rec in records(d) for e in (rec.get("rt") if isinstance(rec.get("rt"), list) else [])
             if isinstance(e, (list, tuple)) and e and num(e[0])}
    live = M.load_json(os.path.join(d, "radar_live.json"), None)
    t_live = num(live.get("t")) if isinstance(live, dict) and live.get("kind") == "radar" else None
    last = max([t for t in times] + ([int(t_live)] if t_live else []), default=None)
    return {"rows": rows, "all": stats(rows), "green": stats([r for r in rows if r["green"]]), "v2": stats(rows2), "rows2": rows2, "rounds": len(times),
            "lastRound": last, "err": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the radar account: 3 EUR on each launch-radar round's best 5, sold by the paper rules (fake money)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="write the buys' docs and price the closed windows (db/memeradarpaper)")
    r.add_argument("--dir", default="mb")
    r.add_argument("--now", type=int, default=None, help="ms; default: the wall clock")
    r.add_argument("--deadline-s", type=float, default=150.0)
    r.add_argument("--mock", default=None, help="rewrite every URL to <mock>/<host>/<path> (selftest)")
    s = sub.add_parser("summary", help="print the two accounts as JSON")
    s.add_argument("--dir", default="mb")
    s.add_argument("--now", type=int, default=None)
    a = ap.parse_args(argv)
    now = a.now if a.now is not None else int(time.time() * 1000)
    if a.cmd == "run":
        print(json.dumps(run(a.dir, now, mock=a.mock, until=time.time() + a.deadline_s)), flush=True)
        return 0
    acc = account(a.dir, now)
    slim = lambda st: dict(st, best=(st["best"] or {}).get("id"), worst=(st["worst"] or {}).get("id"))
    print(json.dumps({"all": slim(acc["all"]), "green": slim(acc["green"]), "v2": slim(acc["v2"]), "rounds": acc["rounds"], "lastRound": acc["lastRound"],
                      "n": len(acc["rows"]), "n2": len(acc["rows2"]), "err": acc["err"]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
