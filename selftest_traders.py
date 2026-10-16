#!/usr/bin/env python3
"""selftest_traders.py: checks TR6 to TR14 of the three paper traders (traders.py; fake money only, nothing is bought, nothing is
advice). A small synthetic db (fixture) and synthetic trades with minute paths; no network.

  python3 selftest_traders.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                 import selftest_traders; selftest_traders.checks(check, SKIPS)

TR6  T1: the account total is memebot.paper_account's P/L plus the closed rule-2 radar results; open, waiting and void radar buys
     count 0 and appear in the counts; the finished trades' T1 is the sum of their real results
TR7  T2: the multiple per case (dust and dead-pool prints left out, a raw 303x counted at 30x, a raw top under 30x counted, an
     estimate at its x, a radar doc's best and never its exit), the paper fees, the median, the sum without the best trade, the counts
TR8  T3 equals T1 exactly while every decision kept T1's rule and skips nothing; a changed rule moves only the trades after it, by the
     replayed difference (the delta method)
TR9  no look-ahead: a decision is the same with future trades added or changed wildly; a window that ended 10 minutes before the
     decision does not train it; the fill model follows a training trade's stop fill, never a future one's; a candle before the entry
     changes no replay
TR10 frozen and deterministic: a second run writes nothing, a third after new trades and changed prices leaves every decision byte for
     byte; the same decision in two processes with different hash seeds gives the same bytes
TR11 the bars: 79 trades learn; better overall but worse in the older half is kept; a lead carried by single trades is kept; a clear
     winner moves one notch; of two winners the larger; never two changes in a day; a 2 h rule is judged on path trades only
TR12 the skip signs: a strong loss with 30/30 (10 a half) is added after Benjamini-Hochberg; not on a day the rule changed; at most 2
     signs and 40% of the coins; a sign that turned harmless is dropped; unknown is never skipped; post-buy fields change no sign
TR13 load() never raises: an empty folder, NaN, infinities and strings in every number, docs that are no objects, a broken decision
     file, no memepath folder: the same keys, lists as lists
TR14 the periods: young decides only for days before the switch, the radar from the switch's day, replay before and live from it

fixture(d, now, switch) and switch_env(ms) are shared with the page's checks (selftest_traders_ui).
"""
import contextlib, glob, json, math, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import peak as P
import exit_grid as EG
import radar_paper as RP
import traders as T

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
PX = 1e-5


@contextlib.contextmanager
def switch_env(ms):
    """MEMEBOT_SWITCH_AT set to ms (memebot.switch_at) inside the block, restored after it (for in-process renders and calls)."""
    old = os.environ.get("MEMEBOT_SWITCH_AT")
    os.environ["MEMEBOT_SWITCH_AT"] = str(int(ms))
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MEMEBOT_SWITCH_AT", None)
        else:
            os.environ["MEMEBOT_SWITCH_AT"] = old


def _w(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))


def _rid(t):
    return time.strftime("%Y-%m-%dT%H%M%S", time.gmtime(t / 1000))


def _closes(mult, n=372, at=30):
    """A minute path from 1.0 to `mult` at minute `at`, held after it (0: a pool that went to almost nothing)."""
    end = mult if mult > 0 else 0.001
    return [1.0 + (end - 1.0) * min(1.0, i / at) for i in range(n)]


# peak doc specs of the closed paper positions: (state, x, rawX, cut); None: no peak doc yet (waiting)
PEAKS = [("ok", 1.8, 1.85, []),
         ("ok", 1.2, 59.0, ["dust: 59.0x on $3 volume"]),                                  # a dust print: left out
         ("ok", 1.5, 4.0, ["pool dead: rug exit, last healthy scan 30 min after the entry"]),   # after the pool died: left out
         ("ok", 3.8, 303.0, ["collapse: under 10% at minute 40, no recovery within 30 min", "cap: 1 level over 30x or a $100M market cap without support"]),
         ("ok", 2.0, 6.0, ["unconfirmed: 6.00x held for one candle only"]),               # a raw top under 30x: counted
         ("est", 1.3, None, []),
         ("ok", 0.9, 0.95, []),
         ("unit", None, 2.0, ["unit: candles 5.00x away from DexScreener's price at minute 3"]),
         None,
         ("ok", 40.0, 45.0, []),                                                          # over 30x, confirmed by the filter
         ("ok", 1.0, 1.0, [])]
EXITS = [("stop", 0.65), ("tp", 11.0), ("time", 1.2), ("rug", 0.0), ("stop", 0.7), ("time", 0.9)]


def fixture(d, now, switch):
    """A small db around the switch: state.json and marks.json; 12 pick and 12 new-launch paper positions with exits (an open pick
    inside its window, an open new launch past it, the rest sold) and their memepeak docs (ok, est, unit, none; a dust spike, a dead
    pool, a raw 303x, a raw top under 30x, a confirmed 40x); 3 radar rule-1 docs (one green); 10 radar rule-2 buys from the switch
    (closed by stop, take-profit, time, rug and estimate, void, waiting, open; feat, pts, late); minute paths for about half of the
    priced windows; hour docs in db/memeradar with green push-worthy and non-push ratings around the switch. Every time is at or
    before now. -> facts {"since", "now", "switch", "pos": {pid: grp}, "radar2": [id], "radar1": [id], "paths": [id]}"""
    now, switch = int(now), int(switch)
    base = min(now, switch)
    S0 = (base - 4 * DAY) // H * H + 11 * MIN
    db = lambda *a: os.path.join(d, "db", *a)
    facts = {"since": S0, "now": now, "switch": switch, "pos": {}, "radar2": [], "radar1": [], "paths": []}
    marks = {"t": now - 10 * MIN, "px": {}, "liq": {}}
    _w(db("memebot", "state.json"), {"paperRule": M.PAPER_RULE, "paperSince": S0, "lastRun": now - 10 * MIN})
    _w(db("memeruns", "r0.json"), {"t": S0 - H})
    rows = []
    for grp, ticket, n, off in (("hold", M.TOP_TICKET, 12, 30 * MIN), ("young", M.YOUNG_TICKET, 12, 50 * MIN)):
        for i in range(n):
            rows.append((grp, ticket, S0 + off + i * 5 * H, i))
    rows.append(("hold", M.TOP_TICKET, now - 2 * H, 99))            # inside its window, open
    rows.append(("young", M.YOUNG_TICKET, base - 7 * H, 98))        # past its window, still open (selling)
    if switch + 9 * H < now:
        rows.append(("hold", M.TOP_TICKET, switch + 2 * H, 12))      # a pick after the switch (the live part)
    for grp, ticket, t, i in rows:
        if t < S0 or t > now:
            continue
        tag = "%s%02d" % ("P" if grp == "hold" else "Y", i)
        pid = "%s-%s-%s-AD%s" % (_rid(t), "h" if grp == "hold" else "y", tag, tag)
        p = {"grp": grp, "addr": "AD" + tag + "x" * 36, "sym": tag, "name": "coin " + tag, "pair": "PA" + tag, "dex": "pumpswap", "t": t, "entryAt": t,
             "px": PX, "mc": 300_000.0, "liq": 30_000.0 + 3_000.0 * i, "vol": 90_000.0, "score": 40.0 + 2 * i, "tier": ("risky" if i % 3 == 0 else "weak") if grp == "hold" else "young",
             "f": {"srcN": float(1 + i % 4), "c1": float(20 * (i % 5)), "lp.other": float(i % 2), "lp.trusted": float(1 - i % 2)}, "ticket": ticket,
             "paper": M.PAPER_RULE, "tp": M.HOLD_TP, "stop": M.HOLD_STOP, "maxH": M.HOLD_MAX_H, "rule": M.RULE, "rec": time.strftime("%Y-%m-%dT%H%M", time.gmtime(t / 1000))}
        _w(db("memepos", pid + ".json"), p)
        facts["pos"][pid] = grp
        if grp == "hold":
            _w(db("memerec", p["rec"] + ".json"), {"t": t, "rule": M.RULE, "picks": [{"sym": tag, "addr": p["addr"], "px": PX, "zp": 0.1 + 0.05 * (i % 6)}]})
        if i >= 98 or (i == 99):
            marks["px"][pid] = PX * 1.3
            continue
        why, mult = EXITS[i % len(EXITS)]
        at = t + (25 + 5 * i) * MIN if why != "time" else t + 6 * H + 3 * MIN
        if at > now:
            marks["px"][pid] = PX * 1.1
            continue
        _w(db("memeexit", pid + "-1.json"), {"pos": pid, "t": at + 2 * MIN, "at": at if why in ("stop", "tp") else None, "px": PX * mult, "frac": 1.0, "why": why,
                                              "eur": round(M.pos_value(p, 1.0, mult), 2), "grp": grp, "rule": M.RULE})
        spec = PEAKS[i % len(PEAKS)]
        end = t + 6 * H
        if spec is None or now < end + 2 * MIN:
            continue
        st, x, raw, cut = spec
        pk = {"v": P.PEAK_V, "pos": pid, "grp": grp, "sym": tag, "addr": p["addr"], "pair": p["pair"], "ticket": ticket, "t": t, "entryAt": t, "end": end,
              "upd": end + 5 * MIN, "state": st, "src": "m1" if st == "ok" else ("est" if st == "est" else "m1"), "res": 1 if st != "est" else None, "tries": 0,
              "px": PX, "cpx": PX if st != "est" else None, "base": PX, "x": x, "at": t + 40 * MIN if x is not None else None, "rawX": raw,
              "x6": min(x, 1.1) if x is not None else None, "eur": round(M.pos_value(p, 1.0, x), 2) if x is not None else None, "eur6": None,
              "lo": 0.6 if x is not None else None, "loAt": t + 20 * MIN if x is not None else None, "eurLo": None,
              "dead": {"at": t + 3 * H, "why": "rug exit"} if "pool dead" in " ".join(cut) else None, "cut": cut, "n": 360}
        _w(db("memepeak", pid + ".json"), pk)
        if st == "ok" and i % 2 == 0:
            r = {"cpx": PX, "base": PX, "dead": pk["dead"], "res": 1}
            if P.write_path(d, "pos", pid, P._rows([[t // MIN * MIN + k * MIN, PX * c, PX * c, PX * c, PX * c, 2000.0] for k, c in enumerate(_closes(max(mult, 0.05)))]),
                            t, end, r, grp):
                facts["paths"].append(pid)
    _w(db("memebot", "marks.json"), marks)
    # the radar: hour docs with ratings around the switch, 3 rule-1 docs, 10 rule-2 buys
    recs, W = [], RP.traps.load_weights()
    sig0 = {"socN": 0.0, "x": "", "buys": 250.0, "m5": -12.0, "ageMin": 1.5, "mc": 60_000.0, "liq": 9_000.0, "creatorPct": 7.0, "devN": 150.0,
            "mintToPoolS": 120_000.0, "lists": 1.0, "tweet": False, "paid": False}
    for i in range(3):
        t = switch - (20 - i) * H
        if t > now:
            continue
        addr = "RV1%02d" % i + "q" * 38
        b = {"id": RP.buy_id(t, "OLD%d" % i, addr), "addr": addr, "sym": "OLD%d" % i, "name": "old radar %d" % i, "pair": "RP1%02d" % i, "round": t, "entryAt": t,
             "end": t + 6 * H, "px": PX, "liq": 20_000.0, "mc": 60_000.0, "green": i == 0, "verdict": "good" if i == 0 else "watch", "pts": float(i), "rank": i + 1,
             "ticket": RP.TICKET, "rule": 1}
        closed = now >= b["end"] + 2 * MIN
        r = {"x": [1.4, 0.65, 0.0][i], "why": ["time", "stop", "rug"][i], "exitAt": t + [6 * H, 50 * MIN, 2 * H][i], "best": [1.6, 1.1, 1.2][i], "bestAt": t + H,
             "rawX": [1.7, 1.1, 9.0][i], "base": PX, "res": 1, "x6": [1.4, 0.9, 0.0][i], "dead": None, "cut": [], "n": 300} if closed else None
        RP.write_doc(d, b["id"], RP.doc_of(b, now, "closed" if closed else "open", 0, "m1" if closed else None, r))
        facts["radar1"].append(b["id"])
        recs.append({"addr": addr, "sym": b["sym"], "name": b["name"], "pair": b["pair"], "pool": t - 3 * MIN, "first": t, "px": PX, "liq": 20_000.0, "mc": 60_000.0,
                     "top": 1, "rt": [[t, b["verdict"], float(i), 1 if i == 0 else 0, PX, 1]], "sig0": dict(sig0), "later": {}, "push": None})
    outcomes = [("closed", "tp", 11.0, 15.0, 16.0), ("closed", "stop", 0.65, 1.3, 1.35), ("closed", "time", 1.4, 2.0, 2.1), ("closed", "rug", 0.0, 1.1, 40.0),
                ("est", "rug", 0.0, None, None), ("void", "nodata", None, None, None), ("waiting", None, None, None, None)]
    for i in range(10):
        t = switch + H + i * 2 * H if i < 7 else now - (10 - i) * H        # seven windows over by switch + 19 h, three inside their 6 h
        if t > now or t < switch:
            continue
        addr = "RV2%02d" % i + "z" * 38
        first = t - (90_000 if i % 3 == 0 else 0)
        rec = {"addr": addr, "sym": "GRN%d" % i, "name": "green %d" % i, "pair": "RP2%02d" % i, "pool": t - 4 * MIN, "first": first, "px": PX, "liq": 15_000.0,
               "mc": 50_000.0, "top": 1, "rt": ([[first, "trap", 3.0, 0, PX, 0]] if i % 3 == 0 else []) + [[t, "good", float(i % 3), 1, PX, 2]],
               "sig0": dict(sig0, m5=-12.0 + 3 * i, creatorPct=float(i), devN=float(40 * i)), "later": {"60": {"t": t + H, "px": PX * 0.5, "liq": 5_000.0}},
               "push": t, "out": {"rug1h": i % 2 == 0, "win1h": False, "x60": 0.5}}
        recs.append(rec)
        b = next(iter(RP.buys_v2([rec], (), switch).values()))
        end = t + 6 * H
        over = now >= end + 2 * MIN
        st, why, x, best, raw = outcomes[i] if i < len(outcomes) and over else ("open" if not over else "waiting", None, None, None, None)
        if st == "est":
            r = {"why": "rug", "x": 0.0, "exitAt": t + H, "cut": ["pool dead: liquidity $500 at minute 60"], "base": PX, "n": 0, "dead": {"at": t + H, "why": "liquidity"}}
            doc = RP.doc_of(b, now, "closed", 3, "est", r)
        elif st == "closed":
            r = {"why": why, "x": x, "exitAt": t + {"tp": 40 * MIN, "stop": 30 * MIN, "time": 6 * H, "rug": 2 * H}[why], "best": best, "bestAt": t + H,
                 "rawX": raw, "base": PX, "cpx": PX, "res": 1, "x6": x if why == "time" else 0.9, "dead": {"at": t + 2 * H, "why": "collapse"} if why == "rug" else None,
                 "cut": ["collapse: under 10% at minute 120, no recovery within 30 min"] if why == "rug" else [], "n": 300}
            doc = RP.doc_of(b, now, "closed", 0, "m1", r)
            if i < 3 and P.write_path(d, "radar", b["id"], [[t // MIN * MIN + k * MIN, PX * c, PX * c, PX * c, PX * c, 2000.0] for k, c in enumerate(_closes(max(x, 0.05)))],
                                      t, end, r):
                facts["paths"].append(b["id"])
        elif st == "void":
            doc = RP.doc_of(b, now, "void", 3, "est", {"why": "nodata", "cut": [], "n": 0})
        else:
            doc = RP.doc_of(b, now, st, 1 if st == "waiting" else 0)
        RP.write_doc(d, b["id"], doc)
        facts["radar2"].append(b["id"])
    # a green that was never push-worthy (no buy) and one past its pool's 10 minutes (no buy)
    for k, (push, age) in enumerate(((0, 2), (1, 12))):
        t = switch + 30 * MIN + k * MIN
        if t <= now:
            recs.append({"addr": "RVN%02d" % k + "n" * 38, "sym": "NOBUY%d" % k, "pair": "RPN%02d" % k, "pool": t - age * MIN, "first": t, "px": PX, "liq": 9_000.0,
                         "mc": 40_000.0, "top": 1, "rt": [[t, "good", 0.0, push, PX, 1]], "sig0": dict(sig0)})
    by = {}
    for rec in recs:
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(rec["first"] // 1000))
        by.setdefault(hour, {"v": 1, "hour": hour, "t": rec["first"] // H * H, "upd": rec["first"], "coins": {}})["coins"][rec["addr"]] = rec
    for hour, doc in by.items():
        _w(db("memeradar", hour + ".json"), doc)
    return facts


# ---------------------------------------------------------------- synthetic trades with minute paths
def ptrade(i, entry, closes, group="young", ticket=3.0, flags=None, closed_after=6 * H + 5 * MIN, path=True, dead=None):
    """A finished trade whose minute path is these closes (over cpx, a minute apart from the entry minute); T1 = its replay of T1's rule."""
    pid = "%s-%04d" % (group, i)
    p = {"ticket": ticket, "grp": "hold" if group == "pick" else "young", "paper": M.PAPER_RULE, "px": 1.0}
    doc = {"v": 1, "id": pid, "kind": "radar" if group == "radar" else "pos", "grp": group if group != "pick" else "hold", "entryAt": entry, "end": entry + 6 * H,
           "res": 1, "cpx": 1.0, "base": 1.0, "dead": dead, "c": [[m * 60, round(c, 6), 2000] for m, c in enumerate(closes[:360])]}
    t = T.Trade({"paths": set(), "dir": "."}, id=pid, group=group, sym="S%d" % i, addr="A%d" % i, entryAt=entry, end=entry + 6 * H, ticket=ticket, p=p,
                closedAt=entry + closed_after, flags=dict(flags or {}), state="finished", pathdoc=doc if path else None)
    if not path:
        t.evf = lambda tr, hours, doc=doc: T.path_ev(doc, tr, hours) if hours == 6.0 else None
    t.t1 = T.vals([t.ev(6)], T.START, EG.FILL_DEFAULT)["pt"][0]
    return t


def pump():             # to 3.2x at minute 30, then down to 0.5x: a 3x target sells at 3x, T1's rule stops at 0.7x
    return [1.0 + 2.2 * min(1, m / 30) if m <= 30 else max(0.5, 3.2 - 0.05 * (m - 30)) for m in range(361)]


def flat(end):          # a slow drift to `end` by 6 h
    return [1.0 + (end - 1.0) * m / 360 for m in range(361)]


def run_up():           # past 3x early, then up to 8x and held: a 3x target sells far too early
    return [1.0 + 2.1 * min(1, m / 10) if m <= 10 else min(8.0, 3.1 + 0.1 * (m - 10)) for m in range(361)]


def rug_after_3x():     # to 3x at minute 20, then the pool dies at minute 200: only a 3x target (or a 2 h hold) gets out
    return [1.0 + 2.0 * min(1, m / 20) if m <= 20 else 3.01 for m in range(200)]


def level(x):           # straight to x after the first minute and held: every rule of the grid sells it at x
    return [1.0] + [x] * 360


def near_3x():          # touches 3.0x, ends at 3.05x: a 3x target costs a little
    return [1.0 + 2.0 * min(1, m / 20) if m <= 20 else 3.05 for m in range(361)]


def group(kinds, t0, group_="young", flags=None, gap=H, path=True, closed_after=6 * H + 5 * MIN):
    """Synthetic finished trades, one per kind (a path function or a list of closes), gap apart from t0."""
    out = []
    for i, k in enumerate(kinds):
        dead = {"at": t0 + i * gap + 200 * MIN, "why": "collapse"} if k is rug_after_3x else None
        out.append(ptrade(i, t0 + i * gap, k() if callable(k) else k, group_, flags=(flags[i] if flags else None), path=path, dead=dead,
                          closed_after=closed_after))
    return out


def dec_core(doc):
    return {k: v for k, v in doc.items() if k != "made"}


# ---------------------------------------------------------------- the checks
def checks(check, skips=None):
    print("== three paper traders (traders.py): T1, T2, T3, no look-ahead, frozen decisions, the bars, the skip signs, load never raises")
    tmp = tempfile.mkdtemp(prefix="memebot-traders-")
    try:
        _tr6_tr7_tr8(check, tmp)
        _tr9(check)
        _tr10(check, tmp)
        _tr11(check)
        _tr12(check, tmp)
        _tr13(check, tmp)
        _tr14(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tr6_tr7_tr8(check, tmp):
    d = os.path.join(tmp, "fx")
    switch = 1_792_108_800_000
    now = switch + 30 * H
    fx = fixture(d, now, switch)
    L = T.load(d, now, switch)
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {})
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {})
    acct = M.paper_account(M.positions(d), state["paperSince"], marks["px"])
    docs = RP.load_docs(d)
    v2 = [x for x in docs.values() if x.get("rule") == 2]
    closed2 = [x for x in v2 if x["state"] == "closed"]
    tr = {x["id"]: x for x in L["trades"]}
    fin = [x for x in L["trades"] if x["state"] == "finished"]
    r1 = L["t1"]["radar"]
    check(L["err"] is None and L["t1"]["account"] == round(acct["pnl"] + sum(x["eur"] - 10.0 for x in closed2), 2) and len(closed2) == 5
          and L["t1"]["invested"] == round(acct["invested"] + 10.0 * len(v2), 2) and L["t1"]["open"] == {"n": acct["nOpen"], "value": acct["open"]}
          and r1["noprice"] == 1 and r1["waiting"] == 1 and r1["running"] == 3 and r1["worst"] == -10.0
          and all(tr[k]["t1"] is None for k in fx["radar2"] if tr[k]["state"] in ("running", "waiting", "noprice")),
          "TR6 T1: the account total %s = paper_account %s + %d closed radar buys at 10 EUR; open (%d), waiting (%d) and void (%d) radar buys count 0 "
          "and appear in the counts" % (L["t1"]["account"], acct["pnl"], len(closed2), r1["running"], r1["waiting"], r1["noprice"]))
    real = {}
    for pid, p in M.positions(d).items():
        if p["_left"] <= 1e-9:
            real[pid] = sum(e["eur"] for e in p["_exits"]) - p["ticket"]
    for x in closed2:
        real[x["id"]] = x["eur"] - 10.0
    check(L["same"]["n"] == len(fin) == L["counts"]["finished"] and L["same"]["t1"] == round(sum(real[x["id"]] for x in fin), 2)
          and L["same"]["invested"] == sum(x["ticket"] for x in fin) and L["same"]["groups"]["radar"]["n"] == 5
          and L["counts"]["selling"] == 1 and L["counts"]["noprice"] >= 2 and L["counts"]["waiting"] >= 2
          and L["t1"]["won"] + L["t1"]["lost"] == len(fin) and L["t1"]["won"] == sum(1 for x in fin if real[x["id"]] > 0),
          "TR6 the same finished trades (%d): their T1 is the sum of their real results (%s); counts %s" % (len(fin), L["same"]["t1"], L["counts"]))
    # TR7: T2 per case
    bm = T.best_mult
    cases = [bm({"state": "ok", "x": 1.2, "rawX": 59.0, "cut": ["dust: 59.0x on $3 volume"]}), bm({"state": "ok", "x": 1.5, "rawX": 4.0, "cut": ["pool dead: rug exit"]}),
             bm({"state": "ok", "x": 3.8, "rawX": 303.0, "cut": ["collapse: under 10%", "cap: 1 level over 30x"]}),
             bm({"state": "ok", "x": 2.0, "rawX": 6.0, "cut": ["unconfirmed: 6.00x held for one candle only"]}), bm({"state": "est", "x": 1.3, "rawX": 9.0}),
             bm({"state": "ok", "x": 40.0, "rawX": 45.0, "cut": []}), bm({"best": 2.0, "x": 1.4, "rawX": None, "src": "m1"}, radar=True),
             bm({"best": None, "x": 0.0, "src": "est"}, radar=True), bm({"best": 1.6, "x": 11.0, "rawX": 1.62, "src": "m1"}, radar=True)]
    check(cases == [(1.2, "left out"), (1.5, "left out"), (30.0, "capped"), (6.0, ""), (1.3, "est"), (40.0, ""), (2.0, ""), (1.0, "est"), (1.62, "")],
          "TR7 T2's multiple: a dust print and a print after the pool died left out (x), a raw 303x counted at 30x, a raw 6x counted, an estimate at its x, "
          "a confirmed 40x kept, a radar doc's best (never its exit 11x), a radar estimate at the entry: %s" % cases)
    pk = M.load_docs(d, "memepeak")
    ok_fee, t2s, whys = True, [], {"est": 0, "capped": 0, "left out": 0}
    for x in fin:
        if x["group"] == "radar":
            doc = docs[x["id"]]
            m, w = bm(doc, radar=True)
            want = M.pos_value(RP.paper(10.0), 1.0, m) - 10.0
        else:
            p = M.positions(d)[x["id"]]
            m, w = bm(pk[x["id"]])
            want = M.pos_value(p, 1.0, m) - p["ticket"]
        ok_fee &= x["t2"] == round(want, 2) and x["t2why"] == w
        t2s.append(want)
        if w in whys:
            whys[w] += 1
    srt = sorted(t2s)
    med = (srt[len(srt) // 2] + srt[(len(srt) - 1) // 2]) / 2
    check(ok_fee and L["same"]["t2"] == round(sum(t2s), 2) and L["t2"]["median"] == round(med, 2) and L["t2"]["noBest"] == round(sum(t2s) - max(t2s), 2)
          and L["t2"]["best"]["eur"] == round(max(t2s), 2) and L["t2"]["est"] == whys["est"] and L["t2"]["capped"] == whys["capped"] == 2
          and L["t2"]["leftOut"] == whys["left out"] and whys["left out"] >= 2 and whys["est"] >= 2,
          "TR7 every finished trade's T2 is memebot.pos_value on its multiple (the paper fees); sum %s, median %s, without the best %s, "
          "%d estimated, %d capped, %d left out" % (L["same"]["t2"], L["t2"]["median"], L["t2"]["noBest"], whys["est"], whys["capped"], whys["left out"]))
    # TR7b: the radar's old 3 EUR test (rule 1) sold the T2 way: from its own docs, the same rows its stop-loss line counts
    v1 = [x for x in docs.values() if x.get("rule") != 2 and x["state"] == "closed"]
    want1 = sum(M.pos_value(RP.paper(RP.TICKET), 1.0, bm(x, radar=True)[0]) - RP.TICKET for x in v1)
    acc = RP.account(d, now, switch)
    check(len(v1) == L["radarV1"]["priced"] == acc["all"]["n"] >= 2 and L["radarV1"]["t2"] == round(want1, 2) and L["radarV1"]["n"] == len(acc["rows"])
          and L["radarV1"]["pnl"] == acc["all"]["pnl"],
          "TR7b the radar's old test at the best price: %s on its %d priced docs (T2's multiple and fees; its stop-loss line %s on the same)"
          % (L["radarV1"]["t2"], len(v1), L["radarV1"]["pnl"]))
    row = lambda best, raw, cut, src="m1", st="closed", eur=1.0: {"state": st, "eur": eur, "ticket": 3.0, "best": best, "rawX": raw, "src": src, "cut": cut}
    junk = [row(1.17, 17436.4, ["pool dead: liquidity $0.03 at minute 15", "dust: 17,436x on $19 volume (2 candles)"]),
            row(2.19, 28021.3, ["pool dead: liquidity $0 at minute 30", "unconfirmed: 28,021x held for one candle only"]),
            row(1.5, None, [], src="est"), row(2.0, 2.0, []), row(9.0, 9.0, [], st="open", eur=None)]
    got = T.radar_v1_best(junk)
    want = sum(M.pos_value(RP.paper(3.0), 1.0, m) - 3.0 for m in (1.17, 30.0, 1.5, 2.0))
    check(got == {"t2": round(want, 2), "est": 1, "capped": 1, "leftOut": 1} and got["t2"] < 100 and T.radar_v1_best([]) == {"t2": None, "est": 0, "capped": 0, "leftOut": 0}
          and T.radar_v1_best([row(2.0, 2.0, [], st="open", eur=None)])["t2"] is None,
          "TR7b junk prints never count: SARWAND's 17,436x on $19 left out at its 1.17x, a one-candle 28,021x at 30x at most, an estimate at its "
          "best, an open row not counted, none priced -> None: %s" % got)
    # TR8: kept decisions everywhere -> T3 == T1 exactly
    for g in T.GROUPS:
        for D in T.days(g, now, switch, fx["since"]):
            doc = {"v": 1, "t3v": T.T3_V, "day": T.day(D), "group": g, "asOf": D, "made": now, "mode": "live" if D >= switch else "replay",
                   "rule": T.rule_dict(T.START), "prev": T.rule_dict(T.START), "changed": None, "skip": [], "prevSkip": [], "evidence": {"n": 0}, "why": "Learning."}
            T.write_once(d, T.dec_path(d, D, g), doc)
    L8 = T.load(d, now, switch)
    check(all(x["t3"] == x["t1"] for x in L8["trades"] if x["state"] == "finished") and L8["same"]["t3"] == L8["same"]["t1"]
          and all(L8["same"]["groups"][g]["t3"] == L8["same"]["groups"][g]["t1"] for g in T.GROUPS) and L8["t3"]["vsT1"]["diff"] == 0.0
          and L8["t3"]["notReplayable"] == 0 and len(L8["decisions"]) == len(glob.glob(os.path.join(d, *T.DIR) + "/*.json")),
          "TR8 every decision kept T1's rule and skipped nothing: T3 equals T1 exactly, per trade and in the sums (%s)" % L8["same"]["t3"])
    # a changed rule from one day on: only the trades after it move, each by the replayed difference
    ys = sorted([x for x in L8["trades"] if x["group"] == "young" and x["state"] == "finished"], key=lambda x: x["entryAt"])
    D1 = T.floor_day(ys[2]["entryAt"]) + DAY
    new = (0.2, 11.0, 6.0)
    for D in T.days("young", now, switch, fx["since"]):
        if D >= D1:                     # the change on D1, the days after it keep the new rule
            fn = T.dec_path(d, D, "young")
            doc = json.load(open(fn))
            os.remove(fn)
            T.write_once(d, fn, dict(doc, rule=T.rule_dict(new), prev=T.rule_dict(T.START if D == D1 else new), changed="rule" if D == D1 else None))
    L9 = T.load(d, now, switch)
    w = T._world(d, now, switch)
    fill = EG.fill_fit([t.ev(6) for t in w["trades"] if t.state == "finished" and t.group in ("pick", "young") and t.ev(6) is not None])
    moved, ok = 0, True
    for t in w["trades"]:
        x = next(y for y in L9["trades"] if y["id"] == t.id)
        if t.state != "finished":
            continue
        if t.group == "young" and t.entryAt >= D1 and t.ev(6) is not None:
            want = t.t1 + T.vals([t.ev(6)], new, fill)["pt"][0] - T.vals([t.ev(6)], T.START, fill)["pt"][0]
            ok &= x["t3"] == round(want, 2) and x["t3rule"] == T.rule_text(*new)
            moved += abs(want - t.t1) > 1e-9
        else:
            ok &= x["t3"] == x["t1"]
    check(ok and moved >= 1 and L9["t3"]["groups"]["young"]["changes"] == 1 and L9["t3"]["groups"]["young"]["lastChange"] == D1
          and abs(L9["t3"]["vsT1"]["diff"] - round(L9["same"]["t3"] - L9["same"]["t1"], 2)) <= 0.011,
          "TR8 the delta method: a decision for a -20%% stop from %s moves only the new launches bought after it (%d moved), each by the replayed "
          "difference between its rule and T1's; T3 - T1 = %s" % (T.day(D1), moved, L9["t3"]["vsT1"]["diff"]))


def _tr9(check):
    D = 1_792_000_000_000 // DAY * DAY
    t0 = D - 5 * DAY
    base = group([pump if i % 3 == 0 else flat(0.9) for i in range(90)], t0)
    doc0 = T.decide("young", D, base, base, None, D, switch=D + DAY)
    later = group([pump] * 8, D - 6 * H, gap=MIN)                          # windows that end after D
    unsold = group([flat(2.0)] * 5, t0 + 100 * H, closed_after=10 * DAY)    # sold after D
    for t in unsold:
        t.id += "u"
    doc1 = T.decide("young", D, base + later + unsold, base + later + unsold, None, D, switch=D + DAY)
    wild = group([[1.0] + [500.0] * 359] * 8, D - 6 * H, gap=MIN)           # the same future trades, changed wildly
    for t in wild + unsold:
        t.pathdoc["cpx"] = 7.0
        t._path, t._ev = False, {}
    doc2 = T.decide("young", D, base + wild + unsold, base + wild + unsold, None, D + 3 * DAY, switch=D + DAY)
    check(dec_core(doc0) == dec_core(doc1) == dec_core(doc2) and doc0["evidence"]["n"] == 90,
          "TR9 a decision is the same with trades whose window ends after it, trades sold after it, and those trades' prices changed wildly (n %d)"
          % doc0["evidence"]["n"])
    edge = ptrade(900, D - 6 * H - 10 * MIN, flat(1.0), closed_after=6 * H + 2 * MIN)
    check(not T.trained(edge, D) and T.trained(edge, D + 10 * MIN) and T.decide("young", D, base + [edge], base, None, D, switch=D)["evidence"]["n"] == 90,
          "TR9 a window that ended 10 minutes before the decision does not train it (the last 15-minute candle and the settle), 10 minutes later it does")

    def coarse(i, entry, fill_x, closed=True):
        ev = {"pid": "c%d" % i, "grp": "young", "t": entry, "p": {"ticket": 3.0, "grp": "young", "paper": M.PAPER_RULE}, "x6": 0.9, "src": "peak",
              "atoms": [(entry, entry + H, 0.4, 1.2, None, "gap", ""), (entry + H, entry + H, 0.6, 0.6, 0.6, "pt", "")], "actual": -1.0,
              "why": "stop", "stopFill": fill_x, "low": (0.4, False, "")}
        t = T.Trade({"paths": set()}, id="c%03d" % i, group="young", sym="C", addr="C", entryAt=entry, end=entry + 6 * H, ticket=3.0, p=ev["p"],
                    closedAt=entry + 6 * H + 5 * MIN if closed else D + DAY, state="finished", evf=lambda tr, h, ev=ev: ev if h == 6.0 else None)
        t.t1 = -1.0
        return t
    tr_ = [coarse(i, t0 + i * H, 0.6) for i in range(25)]
    fut = [coarse(100 + i, D + i * H, 0.6) for i in range(25)]
    f0 = T.decide("young", D, tr_, tr_ + fut, None, D, switch=D)["evidence"]["fill"]
    tr2 = [coarse(i, t0 + i * H, 0.68 if i == 3 else 0.6) for i in range(25)]
    f1 = T.decide("young", D, tr2, tr2 + fut, None, D, switch=D)["evidence"]["fill"]
    fut2 = [coarse(100 + i, D + i * H, 0.69) for i in range(25)]
    f2 = T.decide("young", D, tr_, tr_ + fut2, None, D, switch=D)["evidence"]["fill"]
    check(f0["nAlive"] == 25 and f1["alive"] != f0["alive"] and f2 == f0,
          "TR9 the fill model of a decision is fitted on its training trades only: one training stop fill changed moves it (%s -> %s), 25 "
          "future ones changed leave it (%s)" % (f0["alive"], f1["alive"], f2["alive"]))
    E = 1_791_700_040_000
    body = [[E // MIN * MIN + k * MIN, PX * c, PX * c, PX * c, PX * c, 2000.0] for k, c in enumerate(pump())]
    spike = [[E // MIN * MIN - 2 * MIN, PX * 100, PX * 100, PX * 100, PX * 100, 9000.0]]
    r = {"cpx": PX, "base": PX, "dead": None, "res": 1}
    pa, pb = (P.path_of(c, E, E + 6 * H, r, "pos", "young", "x") for c in (body, spike + body))
    ta, tb = (ptrade(0, E, [1.0] * 360) for _ in range(2))
    ta.pathdoc, tb.pathdoc = pa, pb
    ta._path = tb._path = False
    va = {rl: T.vals([ta.ev(rl[2])], rl, EG.FILL_DEFAULT) for rl in ((0.3, 11.0, 6.0), (0.2, 3.0, 2.0))}
    vb = {rl: T.vals([tb.ev(rl[2])], rl, EG.FILL_DEFAULT) for rl in ((0.3, 11.0, 6.0), (0.2, 3.0, 2.0))}
    check(pa == pb and va == vb and va[(0.3, 11.0, 6.0)]["pt"][0] < 0 < va[(0.2, 3.0, 2.0)]["pt"][0],
          "TR9 a 100x close two minutes before the entry is not in the path and changes no replay (%s)" % {T.rule_key(k): round(v["pt"][0], 2) for k, v in va.items()})


def _tr10(check, tmp):
    d = os.path.join(tmp, "tr10")
    switch = 1_792_108_800_000
    now = switch + 30 * H
    fixture(d, now, switch)
    o1 = T.run(d, now, switch, log=lambda s: None)
    raw1 = {f: open(f, "rb").read() for f in glob.glob(os.path.join(d, *T.DIR) + "/*.json")}
    o2 = T.run(d, now + H, switch, log=lambda s: None)
    # new trades and changed old prices
    for f in glob.glob(os.path.join(d, "db", "memepeak", "*.json")):
        pk = json.load(open(f))
        if pk.get("x") is not None:
            pk["x"], pk["rawX"] = pk["x"] * 3, (pk["rawX"] or 1) * 3
        _w(f, pk)
    for f in glob.glob(os.path.join(d, "db", "memeexit", "*.json")):
        e = json.load(open(f))
        e["eur"] = round(e["eur"] * 0.5, 2)
        _w(f, e)
    fixture(os.path.join(d, "more"), now + 2 * DAY, switch + DAY)
    for f in glob.glob(os.path.join(d, "more", "db", "mem*", "*.json")):
        dst = os.path.join(d, os.path.relpath(f, os.path.join(d, "more")))
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(f, dst)
    o3 = T.run(d, now + 2 * DAY, switch, log=lambda s: None)
    raw3 = {f: open(f, "rb").read() for f in glob.glob(os.path.join(d, *T.DIR) + "/*.json")}
    summ = M.load_json(os.path.join(d, *T.SUMMARY), {})
    check(o1["ok"] and len(o1["written"]) == len(raw1) >= 9 and o2["ok"] and o2["written"] == [] and o3["ok"] and len(o3["written"]) >= 2
          and all(raw3[f] == b for f, b in raw1.items()) and summ.get("t3v") == T.T3_V and set(summ.get("groups") or {}) == set(T.GROUPS)
          and not glob.glob(os.path.join(d, ".trtmp", "*-*.json")),
          "TR10 frozen: the first run writes %d decisions, a second writes none, a third after new trades and changed prices adds %d and leaves "
          "every earlier file byte for byte; db/memebot/traders.json holds the summary" % (len(o1["written"]), len(o3["written"])))
    code = ("import sys, json; sys.path.insert(0, %r); sys.path.insert(0, %r)\nimport selftest_traders as S, traders as T\n"
            "D = 1_792_000_000_000 // S.DAY * S.DAY\nb = S.group([S.pump if i %% 3 == 0 else S.flat(0.9) for i in range(90)], D - 5 * S.DAY, "
            "flags=[{'low_liq': i %% 4 == 0, 'risky': None} for i in range(90)])\n"
            "doc = T.decide('young', D, b, b, None, D, switch=D + S.DAY)\nprint(json.dumps(doc, separators=(',', ':')))\n") % (HERE, HERE)
    outs = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=s)) for s in ("1", "4242")]
    check(outs[0].returncode == outs[1].returncode == 0 and outs[0].stdout == outs[1].stdout and len(outs[0].stdout) > 500
          and json.loads(outs[0].stdout)["changed"] == "rule",
          "TR10 deterministic: the same decision in two processes with different hash seeds gives the same %d bytes" % len(outs[0].stdout))


def _tr11(check):
    D = 1_792_000_000_000 // DAY * DAY
    t0 = D - 6 * DAY
    sw = D + DAY
    few = group([pump] * 79, t0)
    d79 = T.decide("young", D, few, few, None, D, switch=sw)
    check(d79["changed"] is None and T.rule_of(d79["rule"]) == T.START and d79["why"] == "Learning: 79 of 80 finished trades."
          and all(r["status"] == "few" for r in d79["evidence"]["cands"]),
          "TR11 79 finished trades: no change, \"%s\"" % d79["why"])
    halves = group([near_3x] * 40 + [pump] * 40, t0)
    dh = T.decide("young", D, halves, halves, None, D, switch=sw)
    row = next(r for r in dh["evidence"]["cands"] if r["rule"] == T.rule_dict((0.3, 3.0, 6.0)))
    check(dh["changed"] is None and row["status"] == "tested" and row["diff"] > 0 and "was not better in the older half" in row["fails"]
          and dh["why"].startswith("Kept: the best other rule"),
          "TR11 better overall (%+.2f per trade) but worse in the older half: kept (\"%s\")" % (row["diff"], dh["why"]))
    kinds = [near_3x] * 80
    kinds[10], kinds[60] = rug_after_3x, rug_after_3x
    moon = group(kinds, t0)
    dm = T.decide("young", D, moon, moon, None, D, switch=sw)
    rm = next(r for r in dm["evidence"]["cands"] if r["rule"] == T.rule_dict((0.3, 3.0, 6.0)))
    check(dm["changed"] is None and rm["status"] == "tested" and rm["diff"] > 0 and rm["loo"] <= 0 and "was carried by its single best trade" in rm["fails"]
          and not rm["passed"],
          "TR11 better in both halves but carried by single trades (without the best one %+.3f per trade): kept" % rm["loo"])
    clear = group([pump if i % 2 == 0 else flat(1.0) for i in range(100)], t0)
    dc = T.decide("young", D, clear, clear, None, D, switch=sw)
    passed = [T.rule_of(r["rule"]) for r in dc["evidence"]["cands"] if r["passed"]]
    new = T.rule_of(dc["rule"])
    notch = sum(1 for a, b in zip(new, T.START) if a != b)
    check(dc["changed"] == "rule" and new == (0.3, 3.0, 6.0) and notch == 1 and len(passed) == 2 and (0.2, 11.0, 6.0) in passed
          and dc["skip"] == dc["prevSkip"] and dc["why"].startswith("Target 11x → 3x: better in both halves"),
          "TR11 a clear winner moves exactly one notch (%s); of the two winners the larger difference wins (%s); one change only: \"%s\""
          % (T.rule_text(*new), [T.rule_key(r) for r in passed], dc["why"]))
    d2 = T.decide("young", D + DAY, clear, clear, dc, D + DAY, switch=sw)
    check(T.rule_of(d2["prev"]) == (0.3, 3.0, 6.0) and d2["changed"] in (None, "skip-add", "skip-drop")
          and all(sum(1 for a, b in zip(T.rule_of(r["rule"]), (0.3, 3.0, 6.0)) if a != b) == 1 or T.rule_of(r["rule"]) == T.START for r in d2["evidence"]["cands"]),
          "TR11 the next day starts from the new rule and looks only one notch away from it (or back to T1's rule)")
    mixed = group([pump if i % 2 == 0 else flat(1.0) for i in range(100)], t0, path=True)
    for t in mixed[50:]:
        doc = t.pathdoc
        t.pathdoc, t._path, t._ev = None, False, {}
        t.evf = lambda tr, hours, doc=doc: T.path_ev(doc, tr, hours) if hours == 6.0 else None
    dx = T.decide("young", D, mixed, mixed, None, D, switch=sw)
    r2 = next(r for r in dx["evidence"]["cands"] if r["rule"]["hours"] == 2.0)
    r6 = next(r for r in dx["evidence"]["cands"] if r["rule"] == T.rule_dict((0.2, 11.0, 6.0)))
    check(r2["n"] == 50 and r2["status"] == "few" and r6["n"] == 100 and dx["evidence"]["nPath"] == 50,
          "TR11 a 2 h rule is judged only on the trades with a minute path (%d of %d: too few), the 6 h rules on all" % (r2["n"], r6["n"]))
    tt = ptrade(1, t0, [1.0] * 361)
    thin = dict(tt.pathdoc, c=[[m * 60, 1.0, 3 if m < 120 else 2000] for m in range(360)])        # $3 a minute for 2 h, then $2,000
    died = dict(thin, dead={"at": t0 + 90 * MIN, "why": "collapse"})
    e2, e6, ed = T.path_ev(thin, tt, 2.0), T.path_ev(thin, tt, 6.0), T.path_ev(died, tt, 2.0)
    mixed2 = group([flat(1.0)] * 100, t0, path=True)
    for t in mixed2[:30]:
        t.pathdoc, t._path, t._ev = dict(t.pathdoc, c=[[s_, c, 3 if s_ < 7200 else 2000] for s_, c, _ in t.pathdoc["c"]]), False, {}
    dt2 = T.decide("young", D, mixed2, mixed2, None, D, switch=sw)
    r22 = next(r for r in dt2["evidence"]["cands"] if r["rule"]["hours"] == 2.0)
    check(e2 is None and e6 is not None and e6["x6"] == 1.0 and ed is not None and ed["x6"] == 0.0 and ed["atoms"][-1][5] == "dead"
          and r22["n"] == 70 and dt2["evidence"]["n"] == 100,
          "TR11 a path without a close on $25 of volume by 2 h cannot be replayed at 2 h (its value there is unknown, as peak's x6 None, not a "
          "total loss) and is left out of a 2 h rule's trades (%d of 100); at 6 h its value is 1.0x; a pool that died by 2 h is worth 0 there" % r22["n"])
    row_ = {"rule": T.rule_dict((0.3, 3.0, 6.0)), "n": 333, "diff": 0.15, "status": "tested", "passed": True}
    out_ = {"changed": "rule", "rule": T.rule_dict((0.3, 3.0, 6.0)), "prev": T.rule_dict(T.START), "evidence": {"n": 333}}
    w_lo, w_hi = (T.plain_why(out_, [dict(row_, ci=[lo, 0.3112])], {}, T.START) for lo in (0.004, 0.05))
    check("(likely just above 0 to +0.31)" in w_lo and "(likely +0.05 to +0.31)" in w_hi and "+0.00" not in w_lo,
          "TR11 a change's range whose low end passed the bar but is under half a cent reads \"just above 0\", never \"+0.00\": \"%s\"" % w_lo)


def _tr12(check, tmp):
    D = 1_792_000_000_000 // DAY * DAY
    t0 = D - 6 * DAY
    sw = D + DAY
    n = 100
    bad = [i % 3 == 0 for i in range(n)]                       # 34 of 100 flagged, in both halves
    kinds = [level(0.8) if b else level(1.0) for b in bad]
    flags = [{"low_liq": b, "pumped_1h": (i % 2 == 0) if i % 5 else None} for i, b in enumerate(bad)]
    g1 = group(kinds, t0, flags=flags)
    d1 = T.decide("young", D, g1, g1, None, D, switch=sw)
    st = d1["evidence"]["skipTests"]
    check(d1["changed"] == "skip-add" and d1["skip"] == ["low_liq"] and st["low_liq"]["strict"] and st["low_liq"]["nWith"] == 34
          and T.rule_of(d1["rule"]) == T.START and d1["why"].startswith("Skips coins with liquidity under $50k: they lost")
          and st["pumped_1h"]["nWith"] + st["pumped_1h"]["nWithout"] == 80,
          "TR12 a sign with a clear loss (34 with, 66 without, both halves) passes Benjamini-Hochberg and is added: \"%s\"; unknown values are on "
          "neither side (%d of %d tested)" % (d1["why"], st["pumped_1h"]["nWith"] + st["pumped_1h"]["nWithout"], n))
    kinds2 = [pump if i % 2 == 0 else k for i, k in enumerate(kinds)]
    g2 = group(kinds2, t0, flags=flags)
    d2 = T.decide("young", D, g2, g2, None, D, switch=sw)
    check(d2["changed"] == "rule" and d2["skip"] == [],
          "TR12 one change a day: on a day the rule changed no sign is added (%s, skip %s)" % (T.rule_key(T.rule_of(d2["rule"])), d2["skip"]))
    wide = [i % 2 == 0 for i in range(n)]
    g3 = group([level(0.8) if b else level(1.0) for b in wide], t0, flags=[{"low_liq": b} for b in wide])
    d3 = T.decide("young", D, g3, g3, None, D, switch=sw)
    prev2 = dict(d1, skip=["few_lists", "pumped_1h"])
    f4 = [dict(f, few_lists=(i % 3 == 1), pumped_1h=(i % 2 == 0)) for i, f in enumerate(flags)]
    for i in range(n):
        if f4[i]["few_lists"]:
            kinds[i] = level(0.8)
    g4 = group(kinds, t0, flags=f4)
    d4 = T.decide("young", D, g4, g4, prev2, D, switch=sw)
    check(d3["changed"] is None and d3["skip"] == [] and d3["evidence"]["skipTests"]["low_liq"]["strict"]
          and d4["changed"] == "skip-drop" and d4["skip"] == ["few_lists"] and len(d4["skip"]) <= T.SKIP_MAX,
          "TR12 at most 40%% of the coins: a sign on half of them is not added; at most 2 signs; a sign that turned harmless (pumped_1h) is "
          "dropped: \"%s\"" % d4["why"])
    n6 = 150
    f6 = [{"low_liq": i % 5 == 0, "few_lists": i % 5 == 1, "other_pad": i % 5 == 2} for i in range(n6)]
    g6 = group([level(0.8) if i % 5 < 3 else level(1.0) for i in range(n6)], t0 - 3 * DAY, flags=f6)
    d5 = T.decide("young", D, g6, g6, dict(d1, skip=["low_liq", "few_lists"]), D, switch=sw)
    d6 = T.decide("young", D, g6, g6, dict(d1, skip=["low_liq"]), D, switch=sw)
    st6 = d5["evidence"]["skipTests"]
    check(d5["changed"] is None and d5["skip"] == ["low_liq", "few_lists"] and st6["other_pad"]["strict"] and st6["low_liq"]["loose"]
          and d6["changed"] == "skip-add" and len(d6["skip"]) == 2 and T.share(sorted(g6, key=lambda t: t.entryAt), d6["skip"]) <= T.SKIP_SHARE,
          "TR12 with 2 signs active (both still losing) a third that passes is not added; with one active, one more is (%s, %d%% of the coins)"
          % (d6["skip"], round(100 * T.share(g6, d6["skip"]))))
    # valuation: a skipped coin counts 0, an unknown one is never skipped; post-buy fields change no sign
    d = os.path.join(tmp, "tr12")
    switch = 1_792_108_800_000
    now = switch + 30 * H
    fixture(d, now, switch)
    w0 = T._world(d, now, switch)
    sig0 = {t.id: dict(t.flags) for t in w0["trades"] + w0["hist"]}
    for f in glob.glob(os.path.join(d, "db", "memeexit", "*.json")):
        e = json.load(open(f))
        _w(f, dict(e, eur=0.0, why="rug", px=0))
    for f in glob.glob(os.path.join(d, "db", "memepeak", "*.json")) + glob.glob(os.path.join(d, "db", "memeradarpaper", "*.json")):
        doc = json.load(open(f))
        _w(f, dict(doc, x=50.0, best=50.0, rawX=99.0, eur=1.0 if doc.get("eur") is not None else None, pushAt=1, exitAt=doc.get("end")))
    flip = lambda s0: dict(s0, m5=99.0 if s0["m5"] <= -10 else -40.0, creatorPct=0.0 if s0["creatorPct"] > 5 else 40.0, devN=0.0 if s0["devN"] >= 100 else 900.0,
                           socN=5.0, x="https://x.com/later", mintToPoolS=60.0)        # every sign of A1 the other way (no_socials and long_curve: False)
    for f in glob.glob(os.path.join(d, "db", "memeradar", "*.json")):
        doc = json.load(open(f))
        for rec in doc["coins"].values():
            # sigG: the signals of a push-worthy rating 4 minutes after the coin's last stored rating, so after every buy (rule 1 or 2)
            rec.update(later={"5": {"t": 1, "px": 1.0, "liq": 1.0}}, out={"rug1h": True}, push=1, peak60={"x": 9.0}, mom={"x": 3.0},
                       sig=dict(rec.get("sig0") or {}, m5=99.0, creatorPct=0.0, socN=5.0), sigG=flip(rec["sig0"]), sigGt=max(e[0] for e in rec["rt"]) + 4 * MIN)
        _w(f, doc)
    w1 = T._world(d, now, switch)
    sig1 = {t.id: dict(t.flags) for t in w1["trades"] + w1["hist"]}
    check(sig0 == sig1 and len(sig0) >= 30 and any(v is True for fl in sig0.values() for v in fl.values()) and w0["hist"]
          and all(any(t.flags.get(k) is True for k in ("falling", "creator_holds")) for t in w0["hist"]),
          "TR12 the signs read buy-time fields only: exits, peak docs, radar results, later prices, outcomes, momentum, push and the signals of a "
          "push-worthy rating after the buy (sigG, every sign of it flipped; also for the rule-1 greens, %d) changed, every sign of %d trades the same"
          % (len(w0["hist"]), len(sig0)))
    radar = [t for t in w0["trades"] if t.group == "radar" and t.state == "finished"]
    sk = next(f for f in T.SKIP_FLAGS["radar"] if any(flag is True for flag in [T.flag(t, f) for t in radar])
              and any(T.flag(t, f) is None for t in w0["trades"] if t.group == "radar") is False)
    dD = T.floor_day(switch)
    T.write_once(d, T.dec_path(d, dD, "radar"), {"v": 1, "t3v": T.T3_V, "day": T.day(dD), "group": "radar", "asOf": dD, "made": now, "mode": "live",
                                               "rule": T.rule_dict(T.START), "prev": T.rule_dict(T.START), "changed": "skip-add", "skip": [sk], "prevSkip": [],
                                               "evidence": {"n": 0}, "why": "x"})
    L = T.load(d, now, switch)
    rs = [x for x in L["trades"] if x["group"] == "radar" and x["state"] == "finished"]
    hit = [x for x in rs if x["skipped"]]
    tr = {t.id: t for t in T._world(d, now, switch)["trades"]}
    check(hit and all(x["t3"] == 0.0 for x in hit) and all(T.flag(tr[x["id"]], sk) is True for x in hit)
          and all(x["t3"] == x["t1"] for x in rs if not x["skipped"]) and L["t3"]["skipped"]["n"] == len(hit)
          and L["t3"]["skipped"]["t1"] == round(sum(x["t1"] for x in hit), 2) and L["t3"]["groups"]["radar"]["skip"][0]["flag"] == sk,
          "TR12 a skipped coin counts 0 for the learning trader and what T1 made on it is shown apart (%d skipped by %s, T1 %s)"
          % (len(hit), sk, L["t3"]["skipped"]["t1"]))
    tu = ptrade(0, D, flat(0.5), flags={"low_liq": None})
    check(not any(T.flag(tu, f) is True for f in ["low_liq"]) and T.flag(tu, "low_liq") is None and T.flag(tu, "nothing") is None,
          "TR12 an unknown sign (None) is never a reason to skip")


def _tr13(check, tmp):
    keys = set(T._empty(0))
    lists = lambda L: all(isinstance(L[k], list) for k in ("trades", "feed", "decisions")) and all(isinstance(v, list) for v in L["series"].values())
    e0 = T.load(os.path.join(tmp, "nothing-here"), 1_792_100_000_000)
    d = os.path.join(tmp, "tr13")
    switch = 1_792_108_800_000
    now = switch + 30 * H
    fixture(d, now, switch)
    T.run(d, now, switch, log=lambda s: None)
    shutil.rmtree(os.path.join(d, "db", "memepath"))
    good = T.load(d, now, switch)

    def poison(v, k):
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            return [float("nan"), float("inf"), "12x", -float("inf")][k % 4]
        if isinstance(v, dict):
            return {kk: poison(vv, k + i) for i, (kk, vv) in enumerate(v.items())}
        if isinstance(v, list):
            return [poison(x, k + i) for i, x in enumerate(v)]
        return v
    for i, f in enumerate(sorted(glob.glob(os.path.join(d, "db", "*", "*.json")))):
        doc = json.load(open(f))
        with open(f, "w") as fh:
            json.dump(poison(doc, i) if i % 5 else [doc], fh)
    decs = sorted(glob.glob(os.path.join(d, *T.DIR) + "/*.json"))
    with open(decs[0], "w") as fh:
        fh.write("{not json")
    with open(decs[1], "w") as fh:
        json.dump({"v": 1, "t3v": 1, "group": "young", "asOf": "x", "rule": {"stop": "a"}}, fh)
    bad = T.load(d, now, switch)
    odd = T.load(d, "not a time", switch)
    check(e0["err"] is None and set(e0) == keys and lists(e0) and good["err"] is None and set(good) >= keys and lists(good)
          and set(bad) >= keys and lists(bad) and (bad["err"] is None or isinstance(bad["err"], str)) and set(odd) >= keys and isinstance(odd["err"], str)
          and json.dumps(bad, allow_nan=False) and json.dumps(good, allow_nan=False),
          "TR13 load() never raises: an empty folder (no error), no memepath folder (no error), NaN, infinities and strings in every number, "
          "docs that are no objects, a broken decision file (err %r): the same keys, lists as lists, valid JSON" % bad["err"])


def _tr14(check, tmp):
    switch = 1_792_108_800_000
    since = switch - 5 * DAY + 3 * H + 11 * MIN
    now = switch + 2 * DAY + 5 * H
    dy, dp, dr = (T.days(g, now, switch, since) for g in ("young", "pick", "radar"))
    off = T.days("radar", now, switch + 3 * H, since)
    check(dy and dy[0] == T.floor_day(since) + DAY and dy[-1] == switch - DAY and all(D < switch for D in dy) and dp[0] == dy[0] and dp[-1] == T.floor_day(now)
          and dr[0] == switch and dr[-1] == T.floor_day(now) and off[0] == switch + DAY and T.days("pick", switch - 2 * H, switch, since)[-1] == switch - DAY,
          "TR14 young decides for the days before the switch only (%s to %s), pick from the day after paperSince to today, the radar from the "
          "switch's day (a switch at 03:00 starts the radar the next day)" % (T.day(dy[0]), T.day(dy[-1])))
    d = os.path.join(tmp, "tr14")
    now2 = switch + 30 * H
    fixture(d, now2, switch)
    T.run(d, now2, switch, log=lambda s: None)
    decs = T.load_decisions(d)
    modes = {(g, x["day"]): x["mode"] for g in T.GROUPS for x in decs[g]}
    check(all(x["asOf"] < switch for x in decs["young"]) and decs["radar"] and decs["radar"][0]["asOf"] == switch
          and all(m == ("live" if decs[g][[x["day"] for x in decs[g]].index(dd)]["asOf"] >= switch else "replay") for (g, dd), m in modes.items())
          and any(m == "live" for m in modes.values()) and any(m == "replay" for m in modes.values()),
          "TR14 run(): replay before the switch, live from it (%d decisions: %s)" % (len(modes), sorted(set(modes.values()))))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, [])
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
