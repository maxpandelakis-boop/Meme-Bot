#!/usr/bin/env python3
"""selftest_learn.py: the winner patterns and the learned win order (traps.win_label, compare, win_fit, win_score and their use in
launch_radar.py), fake money only.

  python3 selftest_learn.py      -> PASS/FAIL per check, "LEARN ALL PASS" at the end, exit code 1 on any failure

selftest.py calls checks(check, env) right after selftest_traps. L1-L6 are pure (planted records, no network); L7-L9 run the radar in
this process on selftest_radar's mock hosts, fake clock and local git remote (its helpers are only imported, never changed).
"""
import copy, json, os, random, re, shutil, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import traps as T          # noqa: E402

H, MIN, DAY = 3_600_000, 60_000, 86_400_000
NOW = 1_792_000_000_000            # a fixed clock (2026-10-14 UTC)
HOUR0 = NOW - NOW % H              # its UTC hour: planted hour tables start on an hour
NAME = re.compile(r"^[A-Za-z0-9_.]{1,32}$")       # page_radar's signal names
LEVELS = ("bad", "warn", "ok", "info")
ON = {"x": ({"x": "https://x.com/a"}, {"x": ""}), "creator_sold": ({"creatorSold": True}, {"creatorSold": False}),
      "dev_dead": ({"devN": 10.0, "devDead": 10.0}, {"devN": 1.0, "devDead": 0.0}), "sniped30": ({"snip30": 0.5}, {"snip30": 0.0}),
      "bundle_slot": ({"slotN": 5.0}, {"slotN": 0.0}), "rc_danger": ({"rcDanger": ["Freeze authority"]}, {"rcDanger": []})}


def S0(**kw):
    """First-sight signals with no flag set: every check known and passed, no good sign, pool 6 min old."""
    S = T.blank_signals()
    S.update(rcReport=True, rcDanger=[], rcWarn=[], cluster=False, mintToPoolS=240.0, instantPool=False, wmChecked=True, wmState="ok",
             rugHolders=0, swAvg=-1.0, brand=False, buys=400.0, socN=2.0, m5=6.0, creatorSold=False, ageMin=6.0, x="", paid=False,
             tweet=False, lists=1.0, mc=60_000.0, liq=22_000.0, creatorPct=1.0, pumpswap=True, devN=1.0, devDead=0.0)
    S.update(kw)
    return S


def rec(a, first, y, sig0=None, **kw):
    """A radar record with its outcome (traps.outcome): y 1 = 2.5x at 30 min on liquidity grown like the price, 0 = rugged at 60 min,
    None = flat (1.1x)."""
    later = {"60": {"t": first + H, "px": 0.05, "liq": 500.0}} if y == 0 else {"60": {"t": first + H, "px": 1.1, "liq": 21_000.0}}
    if y == 1:
        later["30"] = {"t": first + 30 * MIN, "px": 2.5, "liq": 32_000.0}
    r = {"addr": a, "sym": a[:8], "dex": "pumpswap", "first": first, "pool": first - 2 * MIN, "px": 1.0, "liq": 20_000.0, "mc": 60_000.0,
         "later": later, "peak60": None}
    if sig0 is not None:
        r["sig0"] = sig0
    r.update(kw)
    r["out"] = T.outcome(r) if "60" in r["later"] else None
    return r


def table(hours, flags, start, tag="T"):
    """Records from hour tables: hours = [(winners, losers)], flags = {signal: [(a, c) per hour]}: the first a winners and the first c
    losers of the hour have the flag, the rest do not."""
    out = []
    for h, (nw, nl) in enumerate(hours):
        for y, n in ((1, nw), (0, nl)):
            for i in range(n):
                kw = {}
                for name, ac in flags.items():
                    kw.update(ON[name][0] if i < ac[h][0 if y else 1] else ON[name][1])
                out.append(rec("%s%02d%d%03dpump" % (tag, h, y, i), start + h * H + 60_000 * i + 1000 * y, y, S0(**kw)))
    return out


def by_sig(rep):
    return {r["signal"]: r for r in rep["rows"]}


def checks(check, env=None):
    W = T.load_weights()
    _labels(check)
    _compare(check, W)
    _why(check, W)
    _win_fit(check, W)
    _fuzz(check, W)
    _speed(check, W)
    _radar(check, W)


# ---------------------------------------------------------------- L1
def _labels(check):
    print("== learn L1: win_label (winner, loser, neither)")
    t = NOW - 5 * H

    def lab(later, **kw):
        r = dict(rec("L1pump", t, None, **kw), later=later)
        return T.win_label(dict(r, out=T.outcome(r) if "60" in later else None))
    rug = lab({"60": {"px": 0.05, "liq": 500.0}})
    win = lab({"30": {"px": 2.5, "liq": 32_000.0}, "60": {"px": 1.4, "liq": 24_000.0}})
    meteora = dict(addr="M" * 44, dex="meteora", liq=20_000.0, mc=11_100.0)          # liquidity 1.8x the market cap
    sp_win = lab({"30": {"px": 2.5, "liq": 32_000.0}, "60": {"px": 1.4, "liq": 24_000.0}}, **meteora)
    sp_rug = lab({"60": {"px": 0.05, "liq": 500.0}}, **meteora)
    pump_hi = lab({"60": {"px": 0.05, "liq": 500.0}}, liq=20_000.0, mc=11_100.0, dex="raydium")      # a pump.fun mint: never self-priced
    flat = lab({"30": {"px": 1.3, "liq": 22_000.0}, "60": {"px": 1.1, "liq": 21_000.0}})
    no60 = lab({"15": {"px": 2.5, "liq": 32_000.0}, "30": {"px": 2.6, "liq": 32_000.0}})
    dump = lab({"15": {"px": 2.2, "liq": 30_000.0}, "60": {"px": 0.05, "liq": 600.0}})
    peak = lab({"60": {"px": 1.1, "liq": 21_000.0}}, peak60={"x": 2.6, "at": t + 20 * MIN})
    fake = lab({"30": {"px": 3.0, "liq": 8_000.0}, "60": {"px": 1.1, "liq": 21_000.0}})
    big = lab({"30": {"px": 40.0, "liq": 130_000.0}, "60": {"px": 1.1, "liq": 21_000.0}})
    gone30 = lab({"30": {"gone": True}, "60": {"px": 1.1, "liq": 21_000.0}})
    pk_out = T.outcome(dict(rec("L1pump", t, None), later={"60": {"px": 1.1, "liq": 21_000.0}}, peak60={"x": 2.6}))
    check(rug == 0 and win == 1 and pump_hi == 0, "rugged at 60 min -> 0; 2.5x at 30 min on liquidity grown like the price, no rug -> 1 (%s, %s)" % (rug, win))
    check(sp_win is None and sp_rug is None, "a self-priced Meteora pool (liquidity 1.8x the market cap) is in neither class (%s, %s); a pump.fun mint is" % (sp_win, sp_rug))
    check(flat is None and no60 is None and dump == 0, "flat -> None; no 60-minute price yet -> None (%s); 2.2x at 15 min, rugged at 60 -> 0" % no60)
    check(peak is None and pk_out["win1h"] is True and fake is None and big is None and gone30 is None,
          "peak60 alone never makes a winner (outcome counts it as win1h, the label does not); 3x on thin liquidity, 40x or a gone pool at 30 min -> None")


# ---------------------------------------------------------------- L2
def _compare(check, W):
    print("== learn L2: compare (the same UTC hours, Cochran-Mantel-Haenszel, Benjamini-Hochberg)")
    start = HOUR0 - 30 * H
    hours = [(30, 10) if h % 2 else (10, 30) for h in range(20)]
    conf = table(hours, {"x": [(27, 9) if h % 2 else (1, 3) for h in range(20)]}, start, "C")
    rc = by_sig(T.compare(conf, W, NOW))["x"]
    xs = lambda rs, y: sum(1 for r in rs if T.win_label(r) == y and r["sig0"]["x"]) / float(sum(1 for r in rs if T.win_label(r) == y))
    check(rc["verdict"] == "none" and rc["p"] == 1.0 and rc["or"] == 1.0 and xs(conf, 1) == 0.7 and xs(conf, 0) == 0.3,
          "an hour confounder (X link in 70%% of winners vs 30%% of losers overall, the same share within every hour) is no pattern: %s, p %s, OR %s"
          % (rc["verdict"], rc["p"], rc["or"]))
    flags = {"x": [(6, 7)] * 20, "creator_sold": [(5, 8)] * 20, "dev_dead": [(5, 10)] * 20, "sniped30": [(5, 10)] * 20, "bundle_slot": [(5, 10)] * 20}
    recs = table([(10, 20)] * 20, flags, start, "E")
    extra = [rec("E001000pump", start + 3 * H, 0, S0(**ON["x"][0])),                                        # the same coin again, later
             rec("OLDpump", NOW - (T.STUDY_DAYS + 1) * DAY, 1, S0()), rec("FLATpump", start, None, S0()),
             rec("M" * 44, start, 1, S0(), dex="meteora", liq=20_000.0, mc=11_000.0)] + \
        [rec("NOSIG%dpump" % i, start + i * H, i % 2) for i in range(7)]
    rep = T.compare(recs + extra, W, NOW)
    rs = by_sig(rep)
    x, cs = rs["x"], rs["creator_sold"]
    tested = [r for r in rep["rows"] if r["p"] is not None]
    nulls = [rs[k] for k in ("dev_dead", "sniped30", "bundle_slot")]
    check(x["verdict"] == "pattern" and x["q"] < T.STUDY_Q and x["dir"] == 1 and 2.5 < x["or"] < 3.1 and all(h > 1 for h in x["halves"])
          and (x["wk"], x["wn"], x["lk"], x["ln"]) == (120, 200, 140, 400),
          "a 3x effect inside every hour (6 of 10 winners vs 7 of 20 losers) is a pattern: OR %s, halves %s, q %s" % (x["or"], x["halves"], x["q"]))
    check(len(tested) == 5 and cs["p"] < 0.05 < cs["q"] and abs(cs["q"] - cs["p"] * 5 / 2) < 0.002 and cs["verdict"] == "hint"
          and all(r["verdict"] == "none" and r["p"] == 1.0 for r in nulls) and [r["verdict"] for r in rep["rows"][:2]] == ["pattern", "hint"],
          "Benjamini-Hochberg over the 5 tested signals: creator sold p %s -> q %s, a hint (could be chance), not a pattern; no effect -> none"
          % (cs["p"], cs["q"]))
    check(rep["n"] == 600 and rep["noSig0"] == 7 and rep["w"] == 200 and rep["l"] == 400 and rep["hrs"] == 20 and rep["since"] == start
          and rep["need"] == T.STUDY_MIN_WIN and all(r["verdict"] == "too few" and r["p"] is None for r in rep["rows"] if r["signal"] in ("tweet", "staircase10")),
          "one row per coin (the earliest), 14 days, labelled only: %d rows, %d without first-sight signals not used, %d hours; constant flags are 'too few'"
          % (rep["n"], rep["noSig0"], rep["hrs"]))
    wins, loss = [3, 3, 3, 2, 2, 2, 2, 2, 2, 2], [11] * 6 + [12] * 4
    sparse = table(list(zip(wins, loss)), {"dev_dead": [(0, 1 if h < 2 else 0) for h in range(10)]}, start, "S")
    sd = by_sig(T.compare(sparse, W, NOW))["dev_dead"]
    check((sd["wk"], sd["wn"], sd["lk"], sd["ln"]) == (0, 23, 2, 114) and sd["verdict"] == "too few" and sd["p"] is None and sd["q"] is None,
          "the sparse case of the real data (dev dead: 0 of 23 winners vs 2 of 114 losers) is 'too few', never tested")
    half = table([(10, 20)] * 20, {"x": [(6, 5)] * 10 + [(3, 7)] * 10}, start, "O")
    oh = by_sig(T.compare(half, W, NOW))["x"]
    check(oh["p"] < 0.05 and oh["q"] < 0.05 and oh["halves"][0] > 1 > oh["halves"][1] and oh["verdict"] == "hint",
          "an effect in the older half of the hours only (halves %s, p %s) is a hint, not a pattern" % (oh["halves"], oh["p"]))
    check(len(json.dumps(rep)) < 12_000 and len(rep["rows"]) == len(T._study_cands(W)) == 28,
          "the report is small (%d bytes, a row for each of the 28 signals)" % len(json.dumps(rep)))
    # the winner share and the flag's frequency both swing hour by hour: pooled, the X link looks commoner in rugged coins, hour by hour it is
    # commoner in doubled ones; record.pat carries that hour-matched direction for the page
    import launch_radar as LR
    alt = table([(30, 10) if h % 2 else (5, 30) for h in range(20)], {"x": [(6, 1) if h % 2 else (4, 18) for h in range(20)]}, start, "A")
    arep = T.compare(alt, W, NOW)
    ax, arow = by_sig(arep)["x"], next((r for r in (LR.pat_of(arep, W) or {}).get("rows") or [] if r[0] == "x"), None)
    check(ax["verdict"] == "pattern" and ax["dir"] == 1 and arow == ["x", 190, 400, 100, 350, True, "ok", 1] and 190 / 400.0 > 100 / 350.0,
          "hours that swing (30 doubled/10 rugged, then 5/30): a pattern with OR %s, more often in doubled coins hour by hour while the pooled "
          "shares say 48%% of rugged vs 29%% of doubled; record.pat's row carries the direction 1 (%s)" % (ax["or"], arow))


# ---------------------------------------------------------------- L3
def _why(check, W):
    print("== learn L3: the per-coin why (descriptive, with counts)")
    h0 = HOUR0 - 2 * H
    S = lambda *names, **kw: S0(**dict({k: v for n in names for k, v in ON[n][0].items()}, **kw))
    recs = [rec("W1pump", h0 + MIN, 1, S("x", "rc_danger")), rec("W2pump", h0 + 2 * MIN, 1, S("x")), rec("W3pump", h0 + 3 * MIN, 1, S()),
            rec("RUGTOPpump", h0 + 10 * MIN, 0, S("x", "rc_danger", "creator_sold"), top=1, sym="RUGTOP"),
            rec("RUGLOWpump", h0 + 11 * MIN, 0, S("creator_sold"), sym="RUGLOW"),                      # neither top nor green
            rec("ONEWpump", h0 + H + MIN, 1, S()), rec("RUG1pump", h0 + H + 5 * MIN, 0, S("creator_sold"), good=h0 + H + 6 * MIN, sym="RUG1"),
            rec("OW1pump", h0 - 6 * H, 1, S()), rec("OW2pump", h0 - 6 * H + MIN, 1, S()),
            rec("OLDTOPpump", h0 - 6 * H + 5 * MIN, 0, S("creator_sold"), top=1, sym="OLDTOP")]
    coins = T.compare(recs, W, NOW)["coins"]
    check(coins == [["RUGTOP", h0 + 10 * MIN, 3, [["rc_danger", 1, 3], ["creator_sold", 0, 3]]]],
          "a rugged top coin in an hour with 3 winners: its flags that at most a third of them had, with counts (%s); X link (2 of 3) is not "
          "listed; none for a coin neither top nor green, an hour with one winner or a coin over 6 h old" % coins)
    # RugCheck still pending at first sight (rc_danger unknown): such a winner never counts as 'did not have it'
    pend = dict(rcReport=None, rcDanger=None)
    h1, h2, h3 = HOUR0 - 3 * H, HOUR0 - 4 * H, HOUR0 - 5 * H
    recs = [rec("P1pump", h1 + MIN, 1, S(**pend)), rec("P2pump", h1 + 2 * MIN, 1, S(**pend)), rec("P3pump", h1 + 3 * MIN, 1, S(**pend)),
            rec("RUGPENDpump", h1 + 10 * MIN, 0, S("rc_danger"), top=1, sym="RUGPEND"),                    # no winner known: no line
            rec("Q1pump", h2 + MIN, 1, S("rc_danger")), rec("Q2pump", h2 + 2 * MIN, 1, S(**pend)), rec("Q3pump", h2 + 3 * MIN, 1, S(**pend)),
            rec("RUGHALFpump", h2 + 10 * MIN, 0, S("rc_danger", "creator_sold"), top=1, sym="RUGHALF"),    # 1 known (had it): not listed
            rec("K1pump", h3 + MIN, 1, S()), rec("K2pump", h3 + 2 * MIN, 1, S()), rec("K3pump", h3 + 3 * MIN, 1, S(**pend)),
            rec("RUGTWOpump", h3 + 10 * MIN, 0, S("rc_danger"), top=1, sym="RUGTWO")]                       # 0 of the 2 known
    coins = T.compare(recs, W, NOW)["coins"]
    check(coins == [["RUGHALF", h2 + 10 * MIN, 3, [["creator_sold", 0, 3]]], ["RUGTWO", h3 + 10 * MIN, 3, [["rc_danger", 0, 2]]]],
          "winners whose flag is unknown are left out of its count: RugCheck pending for all 3 winners gives no line, 1 known (with it) and 2 "
          "pending is too few to list, 2 known without it and 1 pending says '0 of 2' (%s)" % coins)


# ---------------------------------------------------------------- L4
def _plant(rng, days, per_hour, pw, px_w, px_l, start=None, late=None):
    """Random records over `days` before NOW: winner share pw; the X link in px_w of the winners, px_l of the losers (late: these three
    for the last 2 days)."""
    start = start if start is not None else NOW - days * DAY
    out = []
    for h in range(days * 24):
        t0 = start + h * H
        for i in range(per_hour):
            w, a, b = late if late and t0 >= NOW - T.WIN_TEST_DAYS * DAY else (pw, px_w, px_l)
            y = 1 if rng.random() < w else 0
            out.append(rec("P%04d%dpump" % (h, i), t0 + i * 7 * MIN, y, S0(**ON["x"][0 if rng.random() < (a if y else b) else 1])))
    return out


def _win_fit(check, W):
    print("== learn L4: win_fit (walk-forward on the last 2 days)")
    recs = _plant(random.Random(4), 6, 3, 0.4, 0.75, 0.25)
    wm, rep = T.win_fit(recs, W, NOW)
    S1, S2 = S0(**ON["x"][0]), S0()
    check(wm is not None and rep["from"] == "learned" and wm["w"] == {"x": 1} and rep["w"] == {"x": 1} and rep["auc"] >= T.WIN_AUC_MIN
          and rep["aucLo"] > 0.5 and wm["src"] == W["src"] and rep["wTest"] >= 30 and rep["lTest"] >= 30 and rep["nTrain"] >= 150,
          "an effect in the training days and the last 2 days: learned, X link +1, AUC %s (low %s) on %d coins" % (rep["auc"], rep["aucLo"], rep["nTest"]))
    check(T.win_score(S1, wm, W) == 1 and T.win_score(S2, wm, W) == 0 and T.win_score(S1, wm["w"], W) == 1 and T.win_score(S1, None, W) is None
          and T.win_score(S1, {}, W) is None and T.win_score(S1, {"w": {}}, W) is None,
          "win_score: the sum of the weights of the true flags (1 with an X link, 0 without); None without a learned order")
    rv, rrep = T.win_fit(_plant(random.Random(4), 6, 3, 0.4, 0.75, 0.25, late=(0.4, 0.25, 0.75)), W, NOW)
    check(rv is None and rrep["from"] == "none" and rrep["w"] == {"x": 1} and rrep["auc"] < 0.5 and rrep["why"].startswith("walk-forward AUC")
          and rrep["why"].endswith("not learned"), "an effect that reverses in the last 2 days is not learned ('%s')" % rrep["why"])
    few = _plant(random.Random(5), 6, 3, 0.4, 0.75, 0.25, late=(0.08, 0.75, 0.25))
    n_w = sum(1 for r in few if r["first"] >= NOW - 2 * DAY and T.win_label(r) == 1)
    fv, frep = T.win_fit(few, W, NOW)
    check(fv is None and frep["why"] == "walk-forward needs 30 doubled coins in the last 2 days (have %d)" % n_w and n_w < 30,
          "fewer than 30 doubled coins in the last 2 days: none ('%s')" % frep["why"])
    short = [r for r in recs if r["first"] >= NOW - 3 * DAY]
    sv, srep = T.win_fit(short, W, NOW)
    flat = [dict(r, sig0=S0()) for r in recs]
    nv, nrep = T.win_fit(flat, W, NOW)
    check(sv is None and srep["why"].startswith("walk-forward needs 150 coins before the last 2 days (have ") and nv is None
          and nrep["why"].startswith("no pattern in ") and all(len(x["why"]) <= 120 for x in (rep, rrep, frep, srep, nrep)),
          "too few coins before the last 2 days ('%s') or no pattern there ('%s'): none; every why fits the page's 120 characters" % (srep["why"], nrep["why"]))


# ---------------------------------------------------------------- L5
def _fuzz(check, W, n=400):
    print("== learn L5: the win order never touches the rating (fuzz)")
    rng = random.Random(1405)
    W0 = copy.deepcopy(W)
    junk = [None, "", "abc", 0, -1, 1.5, float("nan"), float("inf"), True, [], [1, "x"], {}, {"a": 1}, "https://x.com/a", 10 ** 30]
    cands = T._study_cands(W)
    models = [None, {}, {"w": {"x": 1}}, {"w": {k: rng.choice((1, -1)) for k in cands}}, {k: 1 for k in cands},
              {"nope": 1, "x": "a", "tweet": 5, "young_5m": -1, "creator_sold": float("nan")}]
    errs, diff, bad = [], 0, []
    for i in range(n):
        S = S0(**{k: rng.choice(junk) for k in rng.sample(sorted(T.S_KEYS), rng.randrange(1, 12))})
        try:
            before = json.dumps(T.rate(S, W), sort_keys=True)
            got = [T.win_score(S, m, W) for m in models]
            diff += json.dumps(T.rate(S, W), sort_keys=True) != before
            if got[:2] != [None, None] or any(g is not None and not (isinstance(g, int) and -5 <= g <= 5) for g in got):
                bad.append(got)
        except Exception as e:      # noqa: BLE001 - the point of the check
            errs.append("%s: %s" % (type(e).__name__, str(e)[:60]))
    check(not errs and not diff and not bad and W == W0,
          "%d malformed coins: the rating is the same before and after win_score with %d win orders, W unchanged, the score an integer "
          "-5..5 or None without an order%s" % (n, len(models), "" if not (errs or bad) else " (%s %s)" % (errs[:2], bad[:2])))


# ---------------------------------------------------------------- L6
def _speed(check, W):
    print("== learn L6: speed")
    rng = random.Random(6)
    recs = []
    for i in range(20_000):
        y = 1 if rng.random() < 0.3 else 0
        kw = dict(ON["x"][0 if rng.random() < (0.6 if y else 0.4) else 1], **ON["creator_sold"][0 if rng.random() < 0.3 else 1])
        kw.update(ON["dev_dead"][0 if rng.random() < 0.2 else 1], snip30=rng.choice((None, 0.1, 0.5)), m5=rng.choice((3.0, 30.0)))
        recs.append(rec("Z%06dpump" % i, NOW - 14 * DAY + int(i * (14 * DAY - 2 * H) / 20_000), y, S0(**kw)))
    t0 = time.time()
    rep = T.compare(recs, W, NOW)
    wm, wrep = T.win_fit(recs, W, NOW)
    secs = time.time() - t0
    check(secs < 5 and rep["n"] == 20_000 and wrep["n"] == 20_000, "compare and win_fit on 20,000 records: %.1f s (under 5)" % secs)


# ---------------------------------------------------------------- L7-L9: in the radar
def _results(now):
    """results' db/memeradar for a learning run: 4 coins an hour over 4 days before now, about 40% doubled; the X link in 80% of the
    winners and 20% of the losers, creator sold in half of the losers only; every rugged coin was in a round's best 5."""
    rng = random.Random(7)
    docs = {}
    for h in range(4 * 24 - 2):
        t0 = now - 4 * DAY + h * H
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(t0 / 1000))
        for i in range(4):
            y = 1 if rng.random() < 0.4 else 0
            kw = dict(ON["x"][0 if rng.random() < (0.8 if y else 0.2) else 1], **ON["creator_sold"][0 if not y and rng.random() < 0.5 else 1])
            r = rec("R%03d%d" % (h, i) + "x" * 34 + "pump", t0 + i * 9 * MIN, y, S0(**kw), top=None if y else 1, rt=[[t0 + i * 9 * MIN, "watch", 2, 0]])
            docs.setdefault(hour, {"v": 1, "hour": hour, "t": t0 - t0 % H, "upd": t0, "coins": {}})["coins"][r["addr"]] = r
    return {"db/memeradar/%s.json" % h: d for h, d in docs.items()}


def _radar(check, W):
    import launch_radar as LR
    import selftest_radar as SR
    _, P, _ = SR.modules()
    tmp = tempfile.mkdtemp(prefix="memebot-learn-")
    mock = SR.RadarMock(SR.FIX.values())
    srv = SR.serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    by = {c["name"]: c["a"] for c in SR.FIX.values()}
    try:
        with SR.memebot_rules():
            _learn_run(check, LR, SR, P, url, tmp, by)
            _rank(check, LR)
            _ties(check, LR, SR, P, url, tmp)
            _soft(check, LR, SR, P, tmp)
            _refresh(check, LR, SR, P, tmp)
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


def _rank(check, LR):
    print("== learn L8: rank, the win score only breaks ties of equal points")
    mk = lambda n, v, up, pts, liq, ws: {"addr": n, "sym": n, "v": v, "up": up, "pts": pts, "liq": liq, "ws": ws}
    pool = [mk("g1", "good", 1, 0, 9e3, -2), mk("g2", "good", 1, 0, 1e3, 3), mk("g3", "good", 2, 1, 5e3, -5), mk("w1", "watch", 0, 2, 9e4, -1),
            mk("w2", "watch", 0, 2, 1e3, 2), mk("w3", "watch", 0, 1, 5e3, -3), mk("w4", "watch", 0, 2, 5e3, None), mk("t1", "trap", 3, 4, 1e5, 0),
            mk("t2", "trap", 3, 4, 1e3, 4), mk("t3", "trap", 0, 3, 1e3, 5)]
    random.Random(8).shuffle(pool)
    ids = lambda xs: [x["addr"] for x in xs]
    top, coins, others = LR.rank(pool)
    top0, coins0, others0 = LR.rank([dict(x, ws=None) for x in sorted(pool, key=lambda x: x["addr"])])
    check(ids(coins) == ["g3", "g1", "g2"] and ids(top) == ["g3", "g1", "g2", "w3", "w2"] and ids(others) == ["w3", "w2", "w4", "w1", "t3", "t2", "t1"]
          and ids(coins0) == ["g3", "g1", "g2"] and ids(others0) == ["w3", "w1", "w4", "w2", "t3", "t1", "t2"],
          "equal points: the higher win score first in the fold (%s), good coins by liquidity before it (%s); fewer points always first (w3, t3 "
          "with low or high scores), good coins always first; without scores the old order (%s, %s)" % (ids(others), ids(coins), ids(coins0), ids(others0)))
    # 6 good coins with the same upside and points: liquidity picks the 5 listed (and so pushed), the win score never does
    six = [mk("h%d" % i, "good", 1, 0, (6 - i) * 1e3, i - 3) for i in range(6)] + [mk("h6", "good", 1, 0, 3e3, 5)]      # h6 ties h3 on liquidity
    random.Random(9).shuffle(six)
    top6, coins6, _ = LR.rank(six)
    _, coins6n, _ = LR.rank([dict(x, ws=None) for x in sorted(six, key=lambda x: x["addr"])])
    check(ids(coins6) == ["h0", "h1", "h2", "h6", "h3"] and ids(top6) == ids(coins6) and set(ids(coins6)) == set(ids(coins6n)) and "h5" not in ids(coins6),
          "6+ good coins tied on upside and points: the 5 listed and pushed are the 5 most liquid (%s, h5 with the best win score left out); the "
          "win score only orders an exact liquidity tie (h6 before h3)" % ids(coins6))


def _learn_run(check, LR, SR, P, url, tmp, by):
    print("== learn L7, L9: a radar run with planted results (first-sight signals, model.json cmp and win, radar.json record.pat)")
    now = SR.T0
    rem = os.path.join(tmp, "learn.git")
    SR.git("init", "-q", "--bare", rem)
    SR.put_branch(rem, "results", _results(now), tmp)
    SR.put_branch(rem, "radar-feed", SR.feed_files(T, now), tmp)
    norc, f0 = by["NORC"], now - 2 * MIN                       # a record from before the deploy: no sig0, and none later
    hour = time.strftime("%Y-%m-%dT%H", time.gmtime(f0 / 1000))
    old = {"addr": norc, "sym": "NORC", "name": "Norc Coin", "pair": None, "dex": "pumpswap", "lp": None, "found": [], "mint": None, "pool": now, "first": f0,
           "seenAge": 0.0, "px": 0.00006, "liq": 22_000.0, "mc": 60_000.0, "rt": [[f0, "watch", 4.0, 0]], "good": None, "goodPx": None, "sig": {}, "chk": {},
           "push": None, "later": {}, "peak60": None, "out": None}
    SR.put_branch(rem, "radar-data", {"db/memeradar/%s.json" % hour: {"v": 1, "hour": hour, "t": f0 - f0 % H, "upd": f0, "coins": {norc: old}}}, tmp)
    seen, inrate = {}, []

    def patch(R):
        o_rate, o_sig = R.rate, R.signals

        def rate(r, now_, record_only=False):
            inrate.append(1)
            try:
                return o_rate(r, now_, record_only)
            finally:
                inrate.pop()

        def signals(r, now_):
            S, c = o_sig(r, now_)
            if inrate:
                seen.setdefault(r["a"], []).append((now_, json.loads(json.dumps(LR.sig_of(S, {})))))
            return S, c
        R.rate, R.signals = rate, signals
    code, R, lines, secs = SR.run_radar(T, P, url, rem, os.path.join(tmp, "rdL"), now, minutes=10, notifier=SR.Sink(), patch=patch)
    recs, doc = SR.hour_recs(rem), SR.radar_json(rem)
    mj = json.loads(SR.branch_files(rem, "radar-data").get("model.json") or b"{}")
    live = {a: r for a, r in recs.items() if a in seen and a != norc}
    first_ok = all(r.get("sig0") == seen[a][0][1] and seen[a][0][0] == r["first"] for a, r in live.items())
    moved = [a for a, r in live.items() if len(seen[a]) >= 2 and r["sig"].get("ageMin") == seen[a][-1][1].get("ageMin") != r["sig0"].get("ageMin")]
    nr = recs.get(norc) or {}
    print("  %s" % "\n  ".join(l for l in lines if l.startswith(("winner patterns", "radar model"))))
    check(code == 0 and len(live) >= 8 and first_ok and len(moved) == len(live) and "sig0" not in nr and len(nr.get("rt") or []) >= 3,
          "rec.sig0 is the first rating's signals for each of the %d coins and stays while sig moves on (pool age %s -> %s min); a record "
          "from before the deploy gets none later (%d ratings, %.1f s)" % (len(live), (live.get(by["CLEAN"]) or {}).get("sig0", {}).get("ageMin"),
                                                                            (live.get(by["CLEAN"]) or {}).get("sig", {}).get("ageMin"), len(nr.get("rt") or []), secs))
    cmp, win = mj.get("cmp") or {}, mj.get("win") or {}
    pats = {r["signal"]: r for r in cmp.get("rows") or [] if r.get("verdict") == "pattern"}
    check(len(cmp.get("rows") or []) <= 40 and len(cmp.get("coins") or []) <= 20 and set(pats) >= {"x", "creator_sold"} and pats["creator_sold"]["dir"] == -1
          and win.get("from") == "learned" and win.get("w", {}).get("x") == 1 and win.get("w", {}).get("creator_sold") == -1 and win.get("src") == R.W_prior.get("src")
          and mj.get("from") == "prior" and R.W is R.W_prior,
          "model.json: cmp (%d rows, %d coins; patterns %s) and win (%s, %s, AUC %s); the rug model and its weights untouched (%s)"
          % (len(cmp.get("rows") or []), len(cmp.get("coins") or []), sorted(pats), win.get("from"), win.get("w"), win.get("auc"), mj.get("from")))
    pat, mw = (doc.get("record") or {}).get("pat") or {}, (doc.get("model") or {}).get("win") or {}
    rows, why = pat.get("rows") or [], pat.get("why") or []
    rows_ok = all(len(x) == 8 and NAME.match(x[0]) and x[2] > 0 and x[4] > 0 and isinstance(x[5], bool) and x[6] in LEVELS and x[7] in (-1, 1) for x in rows)
    why_ok = all(len(w) == 4 and isinstance(w[0], str) and len(w[3]) <= 3 and all(NAME.match(s) and isinstance(k, int) and T.WHY_MIN_WIN <= m and 3 * k <= m
                                                                                for s, k, m in w[3]) for w in why)
    lv, dr = {x[0]: x[6] for x in rows}, {x[0]: x[7] for x in rows}
    raw = json.dumps(doc, separators=(",", ":"))
    check(1 <= len(rows) <= LR.PAT_ROWS and len(why) <= LR.PAT_WHY and rows_ok and why_ok and lv.get("x") == "ok" and lv.get("creator_sold") == "warn"
          and dr.get("x") == 1 and dr.get("creator_sold") == -1 and pat.get("need") == 15 and pat.get("w") and pat.get("l") and len(raw) <= LR.DOC_MAX,
          "radar.json record.pat: %d rows %s with the hour-matched direction, %d why lines %s (k of the winners known); %d bytes"
          % (len(rows), [x[0] + ":" + x[6] for x in rows], len(why), [w[0] for w in why], len(raw)))
    wss = {c["addr"]: c.get("ws") for c in (doc.get("coins") or []) + (doc.get("others") or [])}
    sc = lambda a: T.win_score((recs.get(a) or {}).get("sig0"), win, R.W_prior)       # the score of its first-sight signals
    check(mw.get("from") == "learned" and mw.get("n") == win.get("nTrain") < win.get("n") and len(mw.get("why") or "") <= 120 and len(wss) > 2
          and norc in wss and wss[norc] is None and all(isinstance(w, int) and w == sc(a) for a, w in wss.items() if a != norc),
          "radar.json model.win %s (n: the coins it was learned on, not the test days); every coin and fold row carries the win score of its "
          "first-sight signals, the record from before the deploy (no sig0) none (%s)" % (mw, sorted(wss.values(), key=str)))
    fd = LR.finish_from(doc, "hours", now + H, "outside the active hours", "9002", now, None, "manual", (7, 24))
    check(fd["record"].get("pat") == pat and fd["model"].get("win") == mw, "a radar.json in state hours (or off) keeps record.pat and model.win")


def _ties(check, LR, SR, P, url, tmp):
    print("== learn L8: verdicts, points and pushes are the same with and without a win order")
    out = {}
    for name, win in (("none", None), ("win", {"x": 1, "no_socials": -1, "young_5m": 1, "creator_5pct": -1, "tweet": 1})):
        rem = os.path.join(tmp, "ties-%s.git" % name)
        SR.git("init", "-q", "--bare", rem)
        SR.put_branch(rem, "radar-feed", SR.feed_files(T, SR.T0), tmp)
        sink = SR.Sink()

        def patch(R, win=win):
            R.win = win
            R.learn_wins = lambda recs, now: None          # keep this order for the whole run
        code, R, _, _ = SR.run_radar(T, P, url, rem, os.path.join(tmp, "rdT-" + name), SR.T0, minutes=10, notifier=sink, patch=patch)
        doc, files = SR.radar_json(rem), SR.branch_files(rem, "radar-data")
        out[name] = {"code": code, "doc": doc, "sink": sink.got, "pushed": sorted(json.loads(files.get("pushed.json") or b"{}")),
                     "rt": {a: [x[1:] for x in r["rt"]] for a, r in SR.hour_recs(rem).items()}}       # the fake clock's ms jitter aside
    a, b = out["none"], out["win"]
    key = lambda d: (sorted((c["addr"], c["v"], c["pts"], c["up"]) for c in d["coins"]), sorted((c["addr"], c["v"], c["pts"]) for c in d["others"]))
    check(a["code"] == b["code"] == 0 and a["rt"] and a["rt"] == b["rt"] and key(a["doc"]) == key(b["doc"]) and a["sink"] == b["sink"] and a["pushed"] == b["pushed"],
          "every rating's verdict and points, the listed coins, the fold, the notifications and pushed.json are the same with a win order "
          "(%d coins, %d notification(s))" % (len(a["rt"]), len(a["sink"])))
    ws_a = [c.get("ws") for c in a["doc"]["coins"] + a["doc"]["others"]]
    ws_b = [c.get("ws") for c in b["doc"]["coins"] + b["doc"]["others"]]
    check(all(w is None for w in ws_a) and all(isinstance(w, int) for w in ws_b) and a["doc"]["model"]["win"]["from"] == "none"
          and b["doc"]["model"]["win"]["from"] == "learned", "the win score is null without a win order and an integer with one (%s)" % ws_b)


def _soft(check, LR, SR, P, tmp):
    print("== learn L9: fails soft (a broken study, a malformed or foreign model.json)")
    said = []
    R = SR.unit_radar(T, P, tmp, "rdF", log=said.append)

    def boom(*a, **k):
        raise ValueError("planted")
    R.T = types.SimpleNamespace(**dict(vars(T), compare=boom, win_fit=boom, win_score=boom))
    R.model = {"v": 1, "from": "prior"}
    R.learn_wins([], NOW)
    R.win = {"x": 1}
    ws = R.win_score(S0(**ON["x"][0]))
    off = R.win is None and R.win_score(S0()) is None
    bad = [LR.pat_of(x, R.W_prior) for x in (None, [], {"rows": 5}, {"rows": [{"signal": "x"}], "coins": [[1]]}, {"coins": [["A", 1, 2, 3]]})]
    empty = LR.pat_of({"at": NOW, "w": 4, "l": 9, "need": 15, "rows": [], "coins": []}, R.W_prior)
    check(R.model["cmp"] is None and R.model["win"]["from"] == "none" and "planted" in R.model["win"]["why"] and ws is None and off
          and all(b is None for b in bad) and empty["rows"] == empty["why"] == [] and (empty["w"], empty["need"]) == (4, 15)
          and any("winner patterns not compared" in l for l in said) and sum("win order off" in l for l in said) == 1,
          "a failing compare, win_fit or win_score is said once and switched off (cmp none, win '%s'); a malformed report gives no "
          "record.pat" % R.model["win"]["why"])
    R2 = SR.unit_radar(T, P, tmp, "rdG", log=said.append)
    win = {"from": "learned", "w": {"x": 1}, "src": R2.W_prior["src"]}
    got = []
    for m in ({"win": win}, {"win": dict(win, src="another prior")}, {"win": dict(win, **{"from": "none"})}, {"win": "x"}, {"win": dict(win, w={})}):
        R2.model = m
        R2.apply_model()
        got.append(R2.win)
    check(got == [{"x": 1}, None, None, None, None] and R2.W is R2.W_prior,
          "model.json's win order is used only when learned on this study prior (%s)" % got)


def _refresh(check, LR, SR, P, tmp):
    print("== learn L9: the per-coin why stays current between fits (compare again every hour)")
    said = []
    R = SR.unit_radar(T, P, tmp, "rdH", now=NOW, log=said.append)
    for path, doc in _results(NOW).items():
        fp = os.path.join(R.res, *path.split("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
    _, n_out, _ = R.summary(NOW)
    old = {"at": NOW - 7 * H, "coins": [], "rows": []}             # the morning fit's compare: its 6 hours held no rugged coin yet
    R.model = {"v": 1, "from": "prior", "at": NOW - 7 * H, "nOut": n_out, "n": n_out, "cmp": dict(old), "win": {"from": "none"}}
    fits = [R.maybe_fit(NOW)]
    c1 = R.model.get("cmp") or {}
    fits.append(R.maybe_fit(NOW + 10 * MIN))
    c2 = R.model.get("cmp") or {}
    R.T = types.SimpleNamespace(**dict(vars(T), compare=lambda *a, **k: 1 / 0))
    fits += [R.maybe_fit(NOW + 61 * MIN), R.maybe_fit(NOW + 63 * MIN)]
    check(fits == [True, False, False, False] and R.model["at"] == NOW - 7 * H and c1.get("at") == NOW and c1.get("coins") and c2.get("at") == NOW
          and R.model["cmp"] is None and sum("winner patterns not compared" in l for l in said) == 1 and LR.pat_of(c1, R.W_prior)["why"],
          "between fits compare runs again once its report is an hour old (%d coins with a why now, none in the morning's), not before; no fit "
          "(model.at unchanged), but model.json changed (a round publishes it); a failing compare is said once an hour, not every cycle"
          % len(c1.get("coins") or []))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, {})
    print("\n%d checks failed" % len(fails) if fails else "\nLEARN ALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
