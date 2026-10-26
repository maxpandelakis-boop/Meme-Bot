#!/usr/bin/env python3
"""selftest_lernpick.py: the Learning Pick (lernpick.py, page_lernpick.py) on made-up data. Fake money only: nothing is bought, nothing is
sent (a local mock stands in for GeckoTerminal).

  python3 selftest_lernpick.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                  import selftest_lernpick; selftest_lernpick.checks(check)

LP1 the inputs: the universe (age, volume, liquidity, market cap, hard blocks), ranks within a scan (ties averaged, missing at 0.5 with
    its flag), the label (paper fees, the multiple capped at 11x), a filter-search rule as an input
LP2 the buy part learns a planted signal from made-up big-test chunks: the trained brain's top coin per scan beats a random one on scans
    it never saw, its strongest input is the planted factor, and the words say it prefers a higher value
LP3 the exam: a candidate is examined only on scans after its frozenAt (and only once), takes over only when it made more and at least
    80 % of the re-draws agree; a worse or an equal one leaves the champion; the first brain starts without an exam; the sell part starts
    with the Pick's rule and changes only on unseen Pick-like trades; a candidate waiting too long is dropped
LP4 train() end to end: the first night replays the nights before (marked replay), writes strict JSON, the next night goes on from the
    state (no second replay, one new candidate)
LP5 buy(): one coin a scan from this scan's snapshot, in the universe, at the snapshot's price, with a pool address, not one it holds,
    never twice a scan; no brain, a stale snapshot or the switch MEMEBOT_LERNPICK=0 buy nothing; marks for open positions; nothing is
    written outside db/memelern (the Pick's own docs byte for byte the same); buy, run, the summary and the fold without numpy (the scan
    and peaks jobs have none, only the nightly training does)
LP6 run() against a mock GeckoTerminal: a position is asked once its 6 hours have passed (one request), sold by its own rule replayed on
    the path; a pool without candles waits, then is sold at its marks (the first scan price after its hold time, 0 after a rug); the
    deadline holds; nothing outside db/memelern
LP7 summary and the fold: the account, the Pick and the Radar since its first buy, the brain's words, English, escaped symbols, before
    the first brain; its place under the shadow rules on the Pick tab; its row on the Start tab that opens the fold; memelern travels to
    the results branch; no push anywhere
LP8 the workflows: the nightly steps after the filter search (soft, their own branch, no results push), the scan copies the brain before
    the scan and passes the switch, bot.py buys after the trader only in recommend mode (soft, with a time limit)
LP9 an open trade that its rule already ended on the scan prices (LAUNCH, Oct 25: under its stop an hour after the buy, 14x later; the
    Start tab showed +415 € for it) counts at that sale, not at the price after it; the trade list shows buy price → sell price, when
    and why it sold, an open trade's price now and when its rule ends, the ended one marked ≈; display only (no file written)
"""
import glob, json, math, os, random, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("MEMEBOT_PAUSE", "0")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
T0 = 1_791_500_000_000           # 2026-10-09, after memebot.LEARN_FROM


class _no_numpy(object):
    """import numpy fails inside the block, as on the scan and peaks jobs' runners (only filtersearch.yml installs it)."""
    def __enter__(self):
        self.had = sys.modules.get("numpy", False)
        sys.modules["numpy"] = None
    def __exit__(self, *a):
        if self.had is False:
            sys.modules.pop("numpy", None)
        else:
            sys.modules["numpy"] = self.had


def _coin(rnd, i, sig, mult, uni=True, extra=None):
    f = {"ageH": rnd.uniform(2, 48) if uni else 500.0, "volMc": rnd.uniform(0.2, 3.0), "sig": sig, "noise": rnd.random(), "liqMc": rnd.random()}
    f.update(extra or {})
    return {"a": "Cn%sk%s" % (str(i + 1).replace("0", "z"), "k" * 35), "s": "C%d" % i, "pass": False, "sc": 50.0, "why": [], "f": f, "mc": 300_000.0, "liq": 40_000.0,
            "mult": round(mult, 4), "eur": 0.0, "gone": mult < 0.02}


def make_snaps(d, days=9, per=30, seed=3, flip_after=None):
    """Hourly scans for days days: each coin's 2-hour multiple rises with its factor sig (planted), plus noise; 3 coins a scan outside the
    universe (old). flip_after (ms): from then on the signal is reversed (a market that changed)."""
    rnd = random.Random(seed)
    os.makedirs(d, exist_ok=True)
    n = 0
    for h in range(days * 24):
        t0 = T0 + h * HOUR
        coins = []
        for k in range(per):
            sig = rnd.random()
            s = sig if not (flip_after and t0 > flip_after) else 1.0 - sig
            mult = max(0.0, math.exp(rnd.gauss(0.0, 0.25)) * (0.8 + 0.5 * s))
            coins.append(_coin(rnd, n, sig, mult))
            n += 1
        for k in range(3):
            coins.append(_coin(rnd, n, rnd.random(), 1.0, uni=False))
            n += 1
        coins[0]["pass"], coins[0]["rank"] = True, 1
        json.dump({"t": t0 + 2 * HOUR, "t0": t0, "rule": "m9-2h", "n": len(coins), "coins": coins}, open(os.path.join(d, "s%04d-1.json" % h), "w"))
    return n


def path_doc(entry, xs, every=1):
    return {"v": 1, "id": "p%d" % entry, "kind": "pos", "grp": "hold", "entryAt": entry, "end": entry + 6 * HOUR, "res": 1, "cpx": 1.0, "base": 1.0,
            "dead": None, "c": [[m * 60, x, 900] for m, x in enumerate(xs) if m % every == 0]}


def checks(check):
    tmp = tempfile.mkdtemp(prefix="memebot-lernpick-")
    try:
        _lp1(check)
        _lp2_lp3(check, tmp)
        _lp4(check, tmp)
        _lp5_lp6(check, tmp)
        _lp7(check, tmp)
        _lp8(check)
        _lp9(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _lp1(check):
    import numpy as np
    import lernpick as L, memebot as M
    print("== learning pick LP1: the inputs")
    base = {"f": {"ageH": 10.0, "volMc": 0.5}, "liq": 20_000.0, "mc": 200_000.0, "why": []}
    var = lambda **kw: dict(base, **{k: v for k, v in kw.items() if k != "f"}, f=dict(base["f"], **kw.get("f", {})))
    check(L.in_universe(base) and not L.in_universe(var(f={"ageH": 0.5})) and not L.in_universe(var(f={"ageH": 80.0}))
          and not L.in_universe(var(f={"volMc": 0.05})) and not L.in_universe(var(liq=10_000.0)) and not L.in_universe(var(mc=3_000_000.0))
          and not L.in_universe(var(why=["honeypot"])) and not L.in_universe({"f": None}),
          "LP1 the universe: 1 h to 3 days old, 24 h volume at least 10 % of the market cap, liquidity and market cap in range, no hard block")
    P = L.pct_block(np.array([[1.0, 5.0], [2.0, float("nan")], [2.0, 7.0], [3.0, 9.0]]))
    check(np.allclose(P[:, 0], [0.125, 0.5, 0.5, 0.875]) and P[1, 1] == 0.5 and np.allclose(P[[0, 2, 3], 1], [1 / 6, 0.5, 5 / 6]),
          "LP1 ranks within a scan: ties averaged (mid-rank over the count), a missing value at 0.5")
    A = L.design(np.array([[1.0, float("nan")], [2.0, 3.0]]), [np.arange(2)])
    check(A.shape == (2, 5) and list(A[:, 3]) == [1.0, 0.0] and list(A[:, 4]) == [1.0, 1.0], "LP1 the design: ranks, missing flags, a constant")
    rnd = random.Random(7)
    V = [[rnd.choice((float("nan"), 0.0, -0.0, 1.0, 1.0, 2.5, rnd.random())) for _ in range(5)] for _ in range(40)]
    mdl = {"w": [rnd.uniform(-9, 9) for _ in range(5)], "wn": [rnd.uniform(-3, 3) for _ in range(5)], "b": 0.7}
    with _no_numpy():
        s_py, P_py = L.scan_scores(mdl, V)
        s_one, _ = L.scan_scores(mdl, V[:1])
    s_np = L.score(mdl, L.design(np.array(V), [np.arange(len(V))]))
    check(np.allclose(s_py, s_np) and np.allclose(P_py, L.pct_block(np.array(V))) and len(s_one) == 1,
          "LP1 the scan's scores in plain Python (no numpy on the scan's runner) are the trained model's scores (ties, missing values, -0.0)")
    p = dict(L.FEE_POS, ticket=50.0)
    check(L.r_of(1.0) == round(M.pos_value(p, 1.0, 1.0) - 50.0, 2) and L.r_of(40.0) == L.r_of(11.0) and L.r_of(0.0) == -50.0 and L.FEE_POS["paper"] == M.PAPER_RULE,
          "LP1 the label: what 50 € became after the Pick's paper fees, the multiple capped at 11x (a 40x counts as 11x), 0 is the whole ticket")
    rule = {"w": "1-6h", "c": [["liqMc", ">=", 0.2]]}
    check(L.fs_pass(rule, {"ageH": 3.0, "liqMc": 0.3}) == 1.0 and L.fs_pass(rule, {"ageH": 8.0, "liqMc": 0.3}) == 0.0
          and L.fs_pass(rule, {"ageH": 3.0}) == 0.0 and L.fs_pass({"w": "gates", "c": []}, {"ageH": 3.0}) == 0.0 and L.fs_pass(None, {}) == 0.0,
          "LP1 a filter-search rule as an input: its age window and every condition (an unknown number never passes)")


def _lp2_lp3(check, tmp):
    import numpy as np
    import lernpick as L
    print("== learning pick LP2: the buy part learns a planted signal")
    snaps = os.path.join(tmp, "snaps")
    make_snaps(snaps)
    R = L.load_rows(snaps)
    check(len(R.t) == 9 * 24 * 30 and len(R.scans) == 9 * 24 and len(R.pick) == 9 * 24,
          "LP2 the loader keeps the universe coins only (%d rows of %d scans), the Pick's choice per scan apart" % (len(R.t), len(R.scans)))
    upto = T0 + 6 * DAY
    m = L.train_buy(R, upto)
    sl = R.scan_slices(R.scan > upto)
    mine = np.mean(list(L.top1(m, R, sl).values()))
    rnd = random.Random(5)
    rand = np.mean([float(R.r[s][rnd.randrange(s.stop - s.start)]) for _, s in sl])
    top = L.effects(m, 3)
    check(m and top[0][0] == "sig" and top[0][1] > 0 and mine > rand + 3.0 and m["lam"] in L.LAMBDAS and "mkt.x" not in m["feats"],
          "LP2 on scans it never saw its top coin made %.2f € per 50 against %.2f for a random coin; its strongest input is the planted one (%s)" % (mine, rand, top[0]))
    check(L.train_buy(R, T0 + 3 * DAY) is None, "LP2 under %d days of data no brain is trained" % L.MIN_TRAIN_DAYS)
    print("== learning pick LP3: the exam")
    bad = dict(m, w=[-x for x in m["w"]], id="bad")
    cand = {"id": "c1", "frozenAt": upto, "buy": m, "sell": None}
    x = L.exam_buy(R, cand, bad, upto + 3 * DAY)
    check(x and x["n"] == 3 * 24 - 2 and x["diff"] > 0 and x["p"] >= 0.99 and L.won(x) and x["unit"] == "scan",
          "LP3 a better brain wins on the 70 scans after its frozenAt that are scored by then (%s)" % {k: x.get(k) for k in ("n", "new", "old", "p")} if x else "LP3 no exam")
    y = L.exam_buy(R, dict(cand, buy=bad), m, upto + 3 * DAY)
    z = L.exam_buy(R, cand, m, upto + 3 * DAY)
    check(not L.won(y) and not L.won(z) and z["diff"] == 0 and L.exam_buy(R, cand, bad, upto + 20 * HOUR) is None,
          "LP3 a worse brain and an equal one do not win; under %d unseen scans there is no exam yet" % L.EXAM_SCANS)
    # the night: the first brain starts, a later better one takes over, a worse one is kept out, each examined once
    state = {"v": 1, "pending": [], "exams": [], "buy": None, "sell": None}
    L.night(state, R, [], T0 + 6 * DAY, T0 + 6 * DAY + 5 * HOUR)
    first = state["buy"]
    check(first and first.get("start") and state["sell"]["id"] == L.START_SELL["id"] and state["sell"]["cid"] == "start"
          and state["pending"][0]["buyDone"] and L.START_SELL["stop"] == 0.30 and L.START_SELL["target"] == 11.0 and L.START_SELL["hours"] == 6.0,
          "LP3 the first brain starts trading without an exam (nothing to beat); the sell part starts with the Pick's rule (−30 %, 11x, 6 h)")
    state["buy"] = dict(bad, id="bad", frozenAt=T0 + 5 * DAY, since=0)
    state["pending"] = [{"id": "good", "frozenAt": upto, "buy": m, "sell": None}]
    ex1 = L.night(state, R, [], upto + DAY, upto + DAY)                    # 24 scans unseen: too early
    ex2 = L.night(state, R, [], upto + 2 * DAY, upto + 2 * DAY)
    check(ex1 == [] and len(ex2) == 1 and ex2[0]["won"] and state["buy"]["id"] == "good" and state["buy"]["since"] == upto + 2 * DAY
          and ex2[0]["changed"] and ex2[0]["changed"][0][0] == "sig" and not any(c["id"] == "good" for c in state["pending"]),
          "LP3 the candidate waits for %d unseen scans, then wins, takes over (what changed most: %s) and leaves the queue" % (L.EXAM_SCANS, ex2[0]["changed"][:1] if ex2 else "?"))
    state["pending"] = [{"id": "worse", "frozenAt": upto, "buy": dict(bad, feats=m["feats"]), "sell": None}]
    ex3 = L.night(state, R, [], upto + 2 * DAY, upto + 2 * DAY + HOUR)
    check(len(ex3) == 1 and not ex3[0]["won"] and state["buy"]["id"] == "good" and ex3[0]["changed"] == [],
          "LP3 a worse candidate is examined once and kept out: the champion stays")
    state["pending"] = [{"id": "late", "frozenAt": T0 + 9 * DAY, "buy": m, "sell": None}]
    ex4 = L.night(state, R, [], T0 + 9 * DAY, T0 + 9 * DAY + (L.EXAM_MAX_DAYS + 1) * DAY)
    check(len(ex4) == 1 and ex4[0]["won"] is False and "too little" in ex4[0]["why"] and not any(c["id"] == "late" for c in state["pending"]),
          "LP3 a candidate without enough unseen data in %d days is dropped" % L.EXAM_MAX_DAYS)
    # the sell part: the grid rule that made the most; examined on Pick-like trades after the freeze only
    T = T0 + 10 * DAY
    up_paths = [{"id": "u%d" % i, "grp": "hold", "entryAt": T + i * HOUR, "end": T + i * HOUR + 6 * HOUR, "pick": True,
                 "doc": path_doc(T + i * HOUR, [1.0 + 0.05 * m_ for m_ in range(31)] + [max(0.5, 2.5 - 0.05 * m_) for m_ in range(330)])} for i in range(30)]
    rule, avg, n = L.train_sell(up_paths, T + 60 * HOUR)
    check(rule and rule["target"] == 2.0 and n == 30 and L.train_sell(up_paths[:10], T + 60 * HOUR)[0] is None,
          "LP3 the sell part: on paths that rise to 2.5x and crash to 0.5x, a 2x target makes the most (%s); under %d trades no rule" % (rule and rule["id"], L.EXAM_PATHS))
    other = [dict(p, pick=False, id="r" + p["id"]) for p in up_paths]
    c = {"id": "s1", "frozenAt": T - HOUR, "sell": rule}
    xs = L.exam_sell(up_paths + other, c, L.START_SELL, T + 60 * HOUR)
    xs2 = L.exam_sell(other, c, L.START_SELL, T + 60 * HOUR)
    xs3 = L.exam_sell(up_paths, dict(c, frozenAt=T + 20 * HOUR), L.START_SELL, T + 60 * HOUR)
    check(xs and xs["n"] == 30 and L.won(xs) and xs2 is None and xs3 is None,
          "LP3 the sell exam counts only Pick-like trades bought after the candidate's freeze (30 here; the other trades and the earlier ones do not count)")


def _lp4(check, tmp):
    import lernpick as L
    print("== learning pick LP4: train() end to end")
    snaps = os.path.join(tmp, "snaps4")
    make_snaps(snaps, days=11, seed=9)
    res, out = os.path.join(tmp, "res4"), os.path.join(tmp, "out4")
    os.makedirs(os.path.join(res, "db", "memepath"))
    for i in range(30):
        e = T0 + 7 * DAY + i * HOUR
        json.dump(path_doc(e, [1.0 - 0.001 * m for m in range(361)]), open(os.path.join(res, "db", "memepath", "p%d.json" % i), "w"))
    now = T0 + 11 * DAY + 7 * HOUR
    st = L.train(snaps, res, out, now)
    raw = open(os.path.join(out, L.DOC), encoding="utf-8").read()
    doc = json.loads(raw)
    rep = [e for e in doc["exams"] if e.get("replay")]
    check(doc["v"] == 1 and doc["buy"] and doc["sell"] and doc["nights"] >= 4 and rep and "NaN" not in raw and doc["data"]["rows"] == 11 * 24 * 30
          and doc["data"]["paths"] == {"hold": 30} and doc["t"] == now and doc["upto"] <= now,
          "LP4 the first night replays the %d nights before (%d replayed exams), writes strict JSON with the brain, the sell rule and the data counts" % (doc["nights"] - 1, len(rep)))
    n_exams = len(doc["exams"])
    st2 = L.train(snaps, res, out, now + DAY)
    doc2 = json.load(open(os.path.join(out, L.DOC), encoding="utf-8"))
    check(doc2["nights"] == doc["nights"] + 1 and not any(e.get("replay") is False and e["t"] < now for e in doc2["exams"])
          and len([e for e in doc2["exams"] if e.get("replay")]) == len(rep) and len(doc2["pending"]) <= len(doc["pending"]) + 1,
          "LP4 the next night goes on from the state: no second replay, at most one new candidate (no new data here: none)")


def _snapdir(d, t, coins):
    os.makedirs(os.path.join(d, "db", "memesnap"), exist_ok=True)
    json.dump({"t": t, "rule": "m9-2h", "n": len(coins), "coins": coins}, open(os.path.join(d, "db", "memesnap", "run%d-1.json" % t), "w"))


def _tree(d, sub):
    return {os.path.relpath(f, d): open(f, "rb").read() for f in glob.glob(os.path.join(d, sub, "**", "*"), recursive=True) if os.path.isfile(f)}


def _lp5_lp6(check, tmp):
    import lernpick as L
    import selftest_shadow as SS
    print("== learning pick LP5: buy()")
    d = os.path.join(tmp, "mb5")
    os.makedirs(os.path.join(d, "db", "memebot"))
    os.makedirs(os.path.join(d, "db", "memepos"))
    model = {"id": "b1", "feats": ["sig"], "w": [10.0], "wn": [0.0], "b": 0.0}
    json.dump({"v": 1, "buy": model, "sell": dict(L.START_SELL, cid="start"), "pending": []}, open(os.path.join(d, "db", "memebot", L.DOC), "w"))
    rnd = random.Random(1)
    t = T0 + 20 * DAY
    coins = [dict(_coin(rnd, i, s, 1.0), px=0.001 * (i + 1)) for i, s in enumerate((0.1, 0.9, 0.5, 0.95))]
    coins[3]["f"]["ageH"] = 200.0                                      # the best signal, but outside the universe
    coins[0]["s"] = "<b>x</b>"
    pairs = [{"address": c["a"], "pairAddress": "POOL%d" % i, "dexId": "pumpswap", "priceUsd": "0.002", "liquidityUsd": 40000} for i, c in enumerate(coins)]
    json.dump(pairs, open(os.path.join(d, "pairs.json"), "w"))
    json.dump({"grp": "hold", "t": t, "addr": coins[1]["a"], "sym": "C1", "ticket": 50.0}, open(os.path.join(d, "db", "memepos", "pick.json"), "w"))
    mine = ("db/memelern", "db/memesnap", "db/memebot/" + L.DOC)          # its own docs, the scan's snapshot and the brain
    keep = {k: v for k, v in _tree(d, "db").items() if not k.startswith(mine)}
    _snapdir(d, t, coins)
    os.environ["MEMEBOT_LERNPICK"] = "0"
    off = L.buy(d, t)
    os.environ.pop("MEMEBOT_LERNPICK")
    stale = L.buy(d, t + L.SNAP_FRESH_MS + MIN)
    with _no_numpy():
        b1 = L.buy(d, t)
        b1b = L.buy(d, t)
    pos = L.positions(d)
    p1 = pos.get(b1.get("pid")) or {}
    check(off["bought"] is None and "switched off" in off["why"] and stale["bought"] is None and b1["bought"] == "C1" and b1b["bought"] is None
          and p1.get("px") == coins[1]["px"] and p1.get("pair") == "POOL1" and p1.get("ticket") == 50.0 and p1.get("t") == t and p1.get("samePick") is True
          and p1.get("rule", {}).get("id") == L.START_SELL["id"] and p1.get("state") == "open" and p1.get("of") == 3 and len(pos) == 1,
          "LP5 one coin a scan: the brain's best in the universe (not the outside one), at the snapshot's price, with its pool, its sell rule, marked as the "
          "Pick's coin too; never twice a scan; a stale snapshot or MEMEBOT_LERNPICK=0 buys nothing")
    t2 = t + HOUR
    _snapdir(d, t2, coins)
    with _no_numpy():
        b2 = L.buy(d, t2)
    p1 = L.positions(d)[p1["pid"]]
    check(b1.get("ok") is True and b2.get("ok") is True and b2["bought"] == "C2" and p1["marks"][-1] == [t2, 0.002, 40000],
          "LP5 the next scan does not buy what it holds (the next best instead) and notes the scan's price of its open position")
    json.dump({"v": 1, "buy": None, "pending": []}, open(os.path.join(d, "db", "memebot", L.DOC), "w"))
    _snapdir(d, t2 + HOUR, coins)
    nb = L.buy(d, t2 + HOUR)
    check(nb["bought"] is None and "no brain" in nb["why"] and keep == {k: v for k, v in _tree(d, "db").items() if not k.startswith(mine)},
          "LP5 without a brain nothing is bought; the Pick's own docs are byte for byte the same (only db/memelern is written)")

    print("== learning pick LP6: run() against a mock GeckoTerminal")
    pos = L.positions(d)
    pa, pb = sorted(pos.values(), key=lambda p: p["t"])
    A0 = pa["entryAt"]
    k0 = pa["px"] / 1e-5          # the mock's closes are 1e-5 x up(): at the coin's own price (memebot.UNIT_X)
    up = lambda ms: k0 * (1.0 if ms < A0 + 30 * MIN else (12.0 if ms < A0 + 40 * MIN else 1.0))
    gt = SS._GT({"POOL1": up})
    keep6 = {k: v for k, v in _tree(d, "db").items() if not k.startswith("db/memelern")}
    try:
        with _no_numpy():
            early = L.run(d, A0 + 6 * HOUR, 20, gt.url)
            r1 = L.run(d, A0 + 6 * HOUR + 3 * MIN, 20, gt.url)
            asked1 = list(gt.asked)
            sa = L.positions(d)[pa["pid"]]
            pb2 = L.positions(d)[pb["pid"]]
            pb2["marks"] = pb2["marks"] + [[pb2["entryAt"] + 6 * HOUR + 10 * MIN, 0.0025, 30000]]
            L.write_pos(d, pb2)
            outs = [L.run(d, pb["entryAt"] + 6 * HOUR + 3 * MIN + k * HOUR, 20, gt.url) for k in range(3)]
            sb = L.positions(d)[pb["pid"]]
            short = L.run(d, A0 + 30 * HOUR, 0.5, gt.url)
    finally:
        gt.close()
    check(early["due"] == 0 and r1["due"] == 1 and r1["sold"] == 1 and [a[0] for a in asked1] == ["POOL1"] and all(a[1] == 1000 for a in asked1)
          and sa["state"] == "sold" and sa["why"] == "tp" and sa["sales"][0][2] == 11.0 and sa["src"] == "candles" and len(sa["c"]) > 300
          and sa["eur"] == L.money([(1.0, 11.0)]),
          "LP6 a position is asked once its 6 hours (and 2 minutes) passed, one request each; sold by its own rule on the path (the Pick's 11x target here: %s €)" % sa.get("eur"))
    check(sb["state"] == "sold" and sb["src"] == "marks" and sb["why"] == "time" and abs(sb["sales"][0][2] - 0.0025 / sb["px"]) < 1e-9
          and outs[0]["waiting"] == 1 and outs[1]["waiting"] == 1 and outs[2]["marks"] == 1,
          "LP6 a pool GeckoTerminal does not know waits %d runs, then is sold at the first scan price after its hold time" % L.MAX_TRIES)
    m = {"entryAt": 0, "px": 1.0, "rule": {"hours": 2.0}, "marks": [[HOUR, 1.0, 900.0]]}
    check(L.sell_from_marks(m, 3 * HOUR)[1] == "rug" and L.sell_from_marks(dict(m, marks=[]), 3 * HOUR) is None
          and L.sell_from_marks(dict(m, marks=[]), 2 * HOUR + L.GIVE_UP_H * HOUR)[1] == "noprice",
          "LP6 at its marks: liquidity under 1,000 $ is a rug (0), no price for %d hours counts as lost" % L.GIVE_UP_H)
    check(short["due"] == 0 and keep6 == {k: v for k, v in _tree(d, "db").items() if not k.startswith("db/memelern")},
          "LP6 nothing is written outside db/memelern")


def _lp7(check, tmp):
    import lernpick as L, page_lernpick as PL, report as R, bot as B
    print("== learning pick LP7: the summary and the fold")
    d = os.path.join(tmp, "mb5")
    with _no_numpy():
        S = L.summary(d, T0 + 30 * DAY)
    check(S["me"]["n"] == 2 and S["me"]["sold"] == 2 and S["me"]["closedPnl"] == round(sum(p["eur"] for p in L.positions(d).values()), 2)
          and S["since"] == T0 + 20 * DAY and S["pick"]["n"] == 1,
          "LP7 the summary: its account from its own positions; the Pick's buys since its first buy beside it")
    empty = os.path.join(tmp, "empty7")
    os.makedirs(empty)
    h0 = PL.section({"dir": empty, "now": T0}, R)
    json.dump({"v": 1, "t": T0 + 30 * DAY, "buy": {"id": "2026-10-17", "feats": ["sig", "liqMc"], "w": [3.0, -1.0], "wn": [0, 0], "b": 0, "since": T0, "start": True},
               "sell": dict(L.START_SELL, cid="start", since=T0), "pending": [{"id": "2026-10-20", "buy": {"x": 1}, "sell": None}],
               "exams": [{"t": T0 + 30 * DAY, "id": "2026-10-18", "part": "buy", "n": 46, "new": 1.0, "old": -2.0, "diff": 3.0, "p": 0.9, "won": True, "unit": "scan", "replay": False}],
               "data": {"rows": 100, "scans": 10, "paths": {"hold": 3}, "trades": {"pick": 4}}}, open(os.path.join(d, "db", "memebot", L.DOC), "w"))
    L.write_pos(d, {"v": 1, "pid": "x-l-esc", "sym": "<b>x</b>", "addr": "Esc", "pair": "P", "t": T0 + 29 * DAY, "entryAt": T0 + 29 * DAY, "px": 1.0,
                    "ticket": 50.0, "rule": dict(L.START_SELL), "state": "open", "marks": []})
    with _no_numpy():
        h1 = PL.section({"dir": d, "now": T0 + 30 * DAY}, R)
    words = h1.lower()
    check('id="learning-pick"' in h1 and "No brain yet" in h0 and "Learning Pick" in h1 and "learned last night" in h1 and "prefers a higher" in h1 and "avoids a high" in h1 and "Oct 18" in h1
          and "Kauf" not in h1 and "Regel" not in h1 and not any(w in words for w in (" safe ", "buy now", "guaranteed")),
          "LP7 the fold: before the first brain one line, then the tiles, the brain in words (prefers / avoids), the exam, English, symbols escaped")
    check("<b>x</b>" not in h1 and "&lt;b&gt;x&lt;/b&gt;" in h1, "LP7 a coin's symbol is escaped")
    page = open(os.path.join(HERE, "report.py"), encoding="utf-8").read()
    i_sh, i_lp = page.find('safe("shadow rules", lambda: shadow_block(D))'), page.find('safe("learning pick", lambda: lernpick_block(D))')
    check(0 < i_sh < i_lp and "!db/memelern/**" in B.SYNC_IGNORE,
          "LP7 the fold sits under the shadow rules on the Pick tab; db/memelern travels to the results branch")
    import page_home as PH
    with _no_numpy():
        r1, r0 = PH.lern_row({"dir": d, "now": T0 + 30 * DAY}, R), PH.lern_row({"dir": empty, "now": T0}, R)
    home = open(os.path.join(HERE, "page_home.py"), encoding="utf-8").read()
    check('for="tab-pick" data-go="pick" data-open="learning-pick"' in r1 and "LEARNING PICK" in r1 and 'class="hm-bal' in r1
          and "2 sold %s · 1 open" % PH.de_eur(S["me"]["closedPnl"], True) in r1 and "waiting for its first training" in r0 and "lp = lern_row(D, R)" in home and '"Three" if lp else "Two"' in home
          and "getElementById(l.getAttribute('data-open')" in home,
          "LP7 the Start tab without its live panel: a Learning Pick row under the two accounts (balance, the sold trades' result, open), a tap opens the Pick tab with the fold open")
    import page_live as PLV
    with _no_numpy():
        D1 = {"dir": d, "now": T0 + 30 * DAY}
        S1 = PLV.lp_summary(D1)
        box = PLV.accounts(D1, R, None, S1, {"lp": "<i>lane</i>"})
    lp_box = box[box.find('lv-acct lv-a-lp"'):]
    check(lp_box and "<b class=\"lv-an\">Learning Pick</b>" in lp_box and PH.de_eur(S1["me"]["pnl"], True) in lp_box and "<i>lane</i>" in lp_box
          and "%d sold %s · %d open" % (S1["me"]["sold"], PH.de_eur(S1["me"]["closedPnl"], True), S1["me"]["open"]) in lp_box,
          "LP7 the Start tab (since Oct 26): the Learning Pick's own box in the live panel with its balance, the sold trades' result, open, and its bot's lane")
    src = open(os.path.join(HERE, "lernpick.py"), encoding="utf-8").read() + open(os.path.join(HERE, "page_lernpick.py"), encoding="utf-8").read()
    check("import app" not in src and "notify" not in src and "live_put" not in src and "webpush" not in src,
          "LP7 no push: the Learning Pick never imports the app's sender")


def _lp8(check):
    import yaml
    print("== learning pick LP8: the workflows")
    fs = yaml.safe_load(open(os.path.join(HERE, ".github", "workflows", "filtersearch.yml"), encoding="utf-8"))
    st = fs["jobs"]["search"]["steps"]
    names = [str(s.get("name") or "") for s in st]
    i_fs = next(i for i, s in enumerate(st) if "filter_search.py run" in str(s.get("run")))
    i_push = next(i for i, n in enumerate(names) if n.startswith("Push the result to the filtersearch branch"))
    i_get = next(i for i, s in enumerate(st) if s.get("id") == "lpget")
    i_tr = next(i for i, s in enumerate(st) if s.get("id") == "lptrain")
    i_lp = next(i for i, n in enumerate(names) if "lernpick branch" in n)
    raw = open(os.path.join(HERE, ".github", "workflows", "filtersearch.yml"), encoding="utf-8").read()
    pushes = [l.strip() for l in raw.splitlines() if "git push" in l]
    check(i_fs < i_push < i_get < i_tr < i_lp and all(st[i].get("continue-on-error") is True for i in (i_get, i_tr, i_lp))
          and "!cancelled()" in str(st[i_get].get("if")) and "lpget.outcome == 'success'" in str(st[i_tr].get("if"))
          and st[i_tr]["run"].strip() == "python3 lernpick.py train --snaps bt/memesnapres --res res --out lp --fs fs" and int(st[i_tr]["timeout-minutes"]) <= 15
          and "GITHUB_TOKEN" not in str(st[i_tr].get("env")) and len(pushes) == 2 and pushes[1] == 'git push -q "$REPO_URL" HEAD:lernpick'
          and not any("results" in p for p in pushes) and int(fs["jobs"]["search"]["timeout-minutes"]) <= 50,
          "LP8 the nightly steps come after the filter search's push, soft (a failure never touches its result), even after a failed search; "
          "the training without the token; the brain goes to its own branch lernpick, never to results")
    scan = yaml.safe_load(open(os.path.join(HERE, ".github", "workflows", "scan.yml"), encoding="utf-8"))
    job = scan["jobs"]["scan"]
    steps = job["steps"]
    i_cp = next(i for i, s in enumerate(steps) if "FETCH_HEAD:lernpick.json > mb/db/memebot/lernpick.json" in str(s.get("run")))
    i_scan = next(i for i, s in enumerate(steps) if s.get("id") == "scan")
    check(i_cp < i_scan and steps[i_cp].get("continue-on-error") is True and (steps[i_scan].get("env") or {}).get("MEMEBOT_LERNPICK") == "${{ vars.MEMEBOT_LERNPICK || '1' }}",
          "LP8 the scan copies the brain before the scan (soft) and passes the switch MEMEBOT_LERNPICK (on unless the variable is 0)")
    bot = open(os.path.join(HERE, "bot.py"), encoding="utf-8").read()
    i_tr2, i_lp2, i_rep = bot.find('o.begin("trader")'), bot.find('run(["lernpick.py", "buy"], d, now, soft=True, limit=LERN_LIMIT_S)'), bot.find('o.begin("reporter")')
    check(0 < i_tr2 < i_lp2 < i_rep and "    if recommend:\n        run([\"lernpick.py\", \"buy\"]" in bot and '("memebot.py", "radar.py", "lernpick.py")' in bot,
          "LP8 bot.py buys after the trader and before the page, only in recommend mode, soft, with a time limit and the cycle's clock")


def _lp9(check, tmp):
    import lernpick as L, page_lernpick as PL, report as R, page_home as PH
    print("== learning pick LP9: an open trade its rule already ended, and the trade list's prices")
    d = os.path.join(tmp, "mb9")
    rule = L._rule(0.2, 2.0, 2.0)
    t = T0 + 40 * DAY
    base = {"v": 1, "addr": "A9", "pair": "P9", "ticket": 50.0, "rule": rule, "brain": "2026-10-17", "score": 1.0, "of": 30, "samePick": False, "tries": 0}
    L.write_pos(d, dict(base, pid="a-l-LAUNCH", sym="LAUNCH", t=t, entryAt=t, px=0.0002288, state="open",
                        marks=[[t, 0.0002288, 44000.0], [t + HOUR, 0.0001716, 38000.0], [t + 4 * HOUR, 0.00254, 209000.0], [t + 5 * HOUR, 0.00334, 184000.0]]))
    L.write_pos(d, dict(base, pid="b-l-UP", sym="UP", t=t + 4 * HOUR, entryAt=t + 4 * HOUR, px=1.0, state="open", marks=[[t + 4 * HOUR, 1.0, 50000.0], [t + 5 * HOUR, 1.2, 50000.0]]))
    L.write_pos(d, dict(base, pid="c-l-SOLD", sym="SOLD", t=t - DAY, entryAt=t - DAY, px=0.0001, state="sold", why="tp", out=t - DAY + 90 * MIN,
                        sales=[[t - DAY + 90 * MIN, 1.0, 2.0, "tp"]], eur=L.money([(1.0, 2.0)]), top=2.0, marks=[]))
    before = sorted(_tree(d, "db"))
    with _no_numpy():
        S = L.summary(d, t + 5 * HOUR + MIN)
    tr = {p["sym"]: p for p in S["trades"]}
    stop_eur, up_val = L.money([(1.0, 0.8)]), L.money([(1.0, 1.2)]) + 50.0
    check(tr["LAUNCH"]["_ended"]["why"] == "stop" and tr["LAUNCH"]["_ended"]["mult"] == 0.8 and tr["LAUNCH"]["_ended"]["t"] == t + HOUR and tr["UP"].get("_ended") is None
          and abs(S["me"]["openValue"] - (stop_eur + 50.0 + up_val)) < 0.02 and abs(S["me"]["pnl"] - (S["me"]["closedPnl"] + stop_eur + up_val - 50.0)) < 0.03
          and S["me"]["pnl"] < 50,
          "LP9 an open trade under its stop on a scan price counts at the stop (%s), not at the 14.6x it reached after; one still inside its rule at the last price (balance %s)"
          % (tr["LAUNCH"].get("_ended"), S["me"]["pnl"]))
    with _no_numpy():
        h = PL.section({"dir": d, "now": t + 5 * HOUR + MIN}, R)
        row = PH.lern_row({"dir": d, "now": t + 5 * HOUR + MIN}, R)
        import page_live as PLV
        D9 = {"dir": d, "now": t + 5 * HOUR + MIN}
        row += PLV.accounts(D9, R, None, PLV.lp_summary(D9), {})
    trs = h.split("<tr")
    lt = next(x for x in trs if "LAUNCH" in x)
    up = next(x for x in trs if ">UP<" in x)
    sd = next(x for x in trs if ">SOLD<" in x)
    check("$0.0002288 → ≈ $0.0001830" in lt and "stop" in lt and "now 14.60x (after its sale)" in lt and "≈ " + PL.eur(stop_eur) in lt
          and "$1.00 → now $1.20" in up and "its rule ends" in up and ">open<" in up
          and "$0.0001000 → $0.0002000" in sd and "2.00x · sold" in sd and "target" in sd and PL.eur(L.money([(1.0, 2.0)])) in sd
          and h.find('id="learning-pick-trades"') < h.find('class="lp-brain"') and "Its trades: 2 open, 1 sold" in h
          and PH.de_eur(S["me"]["pnl"], True) in row and "+415" not in row,
          "LP9 the trade list (above the brain): buy price → sell price, the multiple, when and why it sold; an open one's price now and its rule's end; "
          "the ended one with ≈; the Start row's balance the same as the summary")
    check(sorted(_tree(d, "db")) == before, "LP9 the summary and the fold write nothing")


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
