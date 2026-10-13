#!/usr/bin/env python3
"""selftest_peak.py: checks P1 to P7 of the peak category ("best price within 6 h", hindsight; fake money only, nothing is bought).

  python3 selftest_peak.py        -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:              import selftest_peak; selftest_peak.peak_checks(check)

P1  the 10 cases of the peak research's reference tests (spike, dust, rug cut, collapse, cap without and with support, unit,
    confirmation, x6 at the end, x6 = 0 when dead), on peak.peak_of
P2  the named cases (tests/fixtures/peak/named.json): Doggo <= 1.0x, Banana Cat <= 1.91x, Husky <= 1.72x, SpaceX AI rejected,
    HIRE >= 38x kept, hi kept
P3  peak.py run on a copy of the recommend-mode db with the mock's OHLCV: docs only for closed in_account windows, none for open
    ones, /__nocandle -> waiting -> est after 3 runs, a second run changes nothing, pk<minute> keeps two positions in one pool apart
P4  eur == memebot.pos_value(p, 1.0, x) (and eur6 on x6); base never above max(cpx, px)
P5  the trader's docs (memecurve "paper", state "paper", recommend, marks, train.json when there is one, positions, exits) are byte
    for byte the same with and without the memepeak docs and the peak candle files present
P6  memepeak and memeradar reach the results branch through bot.py sync (with a stand-in for WP4's SYNC_IGNORE lines until that
    package is merged; after it, the real lines are required)
P7  the deadline holds: a mock answering in 5 s with --deadline-s 12 ends within 15 s
"""
import glob, json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIX = os.path.join(HERE, "tests", "fixtures", "peak")
MIN, HOUR = 60_000, 3_600_000
WP4_LINES = ("!db/memepeak/", "!db/memepeak/**", "!db/memeradar/", "!db/memeradar/**")


# ---------------------------------------------------------------- candles for the pure checks
def series(t0, mults, vol=2000.0, start=0, px=1e-5):
    """Minute candles from t0 + start minutes with these closes (times px); vol a number or a function of the index."""
    return [[t0 + (start + i) * MIN, px * m, px * m, px * m, px * m, vol(i) if callable(vol) else vol] for i, m in enumerate(mults)]


def expand(case):
    """A named fixture's candle shape -> minute candles: segments [from min, to min, close from, close to, $ volume] after the entry
    minute, geometric between the closes, a later segment winning a shared minute; open = the previous close."""
    t0 = case["entryAt"] // MIN * MIN
    closes = {}
    for m0, m1, x0, x1, vol in case["shape"]:
        for m in range(m0, m1 + 1):
            f = (m - m0) / (m1 - m0) if m1 > m0 else 0.0
            closes[m] = (x0 * (x1 / x0) ** f, vol)
    rows, prev = [], None
    for m in sorted(closes):
        c, v = closes[m]
        c *= case["px"]
        o = prev if prev is not None else c
        rows.append([t0 + m * MIN, o, max(o, c), min(o, c), c, v])
        prev = c
    return rows


def young_pos(ticket=3.0):
    import memebot as M
    return {"grp": "young", "paper": M.PAPER_RULE, "ticket": ticket}


def base_ok(doc):
    """P4: the base is the candles' entry close or the paid price, never above the larger of the two."""
    b, c, p = doc.get("base"), doc.get("cpx"), doc.get("px")
    if b is None:
        return True
    top = max(v for v in (c, p) if v is not None)
    return b <= top * (1 + 1e-12) and (c is None or b >= c * (1 - 1e-12))


# ---------------------------------------------------------------- the checks
def peak_checks(check):
    import memebot as M
    import peak as PK
    import selftest as S
    tmp = tempfile.mkdtemp(prefix="memebot-peak-")
    try:
        _p1(check, PK, M)
        named = _p2(check, PK, M)
        _p3_to_p7(check, PK, M, S, tmp, named)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _p1(check, PK, M):
    print("== peak P1: the reference cases of the glitch filter")
    T0 = 1_791_800_000_000
    end = T0 + 6 * HOUR
    pk = lambda c, px=1e-5, **k: PK.peak_of(c, T0, end, px, **k)
    pos = young_pos()
    res = []
    c = series(T0, [1.0, 1.2, 1.5, 1.9, 1.9, 1.8]) + series(T0, [1e-7, 1e-7], start=6) + series(T0, [59257, 59000, 59300], vol=0.02, start=60)
    r = pk(c, mc0=89_447)
    res.append(("dead pool after the pull, the dust at 59,000x ignored, x6 = 0", r["state"] == "ok" and 1.79 <= r["x"] <= 1.91 and r["x6"] == 0 and r["dead"]
                and r["rawX"] >= 59000 and any(x.startswith("collapse") for x in r["cut"]), r))
    c = series(T0, [1.0, 1.1, 1.2, 8.0, 1.1, 1.15, 1.2] + [1.1] * 300)
    r = pk(c, mc0=50_000)
    res.append(("a one-candle spike in a live pool: only the confirmed level", r["x"] <= 1.21 and any("unconfirmed" in x for x in r["cut"]) and not r["dead"], r))
    up = [38 ** (i / 120) for i in range(121)] + [38 - i * 0.05 for i in range(200)]
    r = pk(series(T0, up, vol=5000), mc0=51_108)
    res.append(("a rocket over the 30x cap with sustained volume counts; x6 is the last close by the end",
                r["x"] >= 37.5 and M.pos_value(pos, 1.0, r["x"]) > 100 and abs(r["x6"] - (38 - 199 * 0.05)) < 1e-6 and not r["cut"], r))
    c = series(T0, [1.0, 1.1, 1.2, 1.3, 500, 480, 1.2, 1.2], vol=30)
    r = pk(c, mc0=89_447)
    res.append(("500x on two thin candles fails the cap", r["x"] <= 1.31 and any(x.startswith("cap") for x in r["cut"]), r))
    r = pk(c, mc0=20_000, ds_points=[(T0 + 4 * MIN, 300 * 1e-5, 150_000.0)])
    res.append(("the same 500x with a DexScreener point at 300x on $150k liquidity counts", r["x"] >= 479, r))
    r = pk([])
    res.append(("no candles: waiting, nothing booked", r["state"] == "waiting" and r["x"] is None and r["n"] == 0, r))
    c = series(T0, [1.0] * 39 + [1.3, 1.3] + [20] * 4)
    r = pk(c, rug_ok_at=T0 + 40 * MIN)
    res.append(("a rug exit ends the window at its last healthy scan: the pump after it is ignored, x6 = 0",
                r["x"] <= 1.01 and r["x6"] == 0 and (r["dead"] or {}).get("why") == "rug exit" and r["cut"][0].startswith("pool dead"), r))
    c = series(T0, [5.0, 5.1, 5.2, 5.0] * 20)
    r = pk(c, px=5e-5, ds_points=[(T0 + 10 * MIN, 0.2 * 1e-5, 50_000.0)])
    res.append(("candles 26x away from a liquid DexScreener price: unit, not booked", r["state"] == "unit" and r["x"] is None and r["cut"][-1].startswith("unit"), r))
    c = series(T0, [1.0, 1.4, 1.5, 1.5, 0.01, 1.5, 1.6, 1.6, 1.6])
    r = pk(c)
    res.append(("one low print in a live pool is no collapse (confirmation of the real closes)", r["x"] >= 1.59 and not r["dead"] and r["x6"] == 1.6, r))
    c = series(T0, [1.0] * 360 + [9.0] * 3)
    r = pk(c)
    res.append(("after 6 h nothing counts", r["x"] <= 1.01 and r["x6"] == 1.0, r))
    for what, ok, r in res:
        check(ok, "P1 %s (%s)" % (what, {k: r.get(k) for k in ("state", "x", "x6", "rawX", "cut")}))
    check(len(res) == 10, "P1 covers the 10 reference cases (%d)" % len(res))


def _p2(check, PK, M):
    print("== peak P2: the named cases (real DexScreener points, synthetic candle shapes)")
    fx = json.load(open(os.path.join(FIX, "named.json"), encoding="utf-8"))
    out = {}
    for case in fx["cases"]:
        r = PK.peak_of(expand(case), case["entryAt"], case["entryAt"] + 6 * HOUR, case["px"], case.get("rugOkAt"), [q[:3] for q in case["ds"]],
                       liq0=case["liq0"], mc0=case["mc0"])
        out[case["name"]] = r
        e = case["expect"]
        ok = r["state"] == "ok" and r["x"] is not None
        ok = ok and ("xMax" not in e or r["x"] <= e["xMax"]) and ("xMin" not in e or r["x"] >= e["xMin"])
        ok = ok and ("x6" not in e or r["x6"] == e["x6"]) and ("x6Min" not in e or (r["x6"] or 0) >= e["x6Min"])
        ok = ok and ("dead" not in e or bool(r["dead"]) == e["dead"]) and ("rawXMin" not in e or (r["rawX"] or 0) >= e["rawXMin"])
        ok = ok and not any(c.startswith(w) for c in r["cut"] for w in e.get("noCut", ()))
        eur = M.pos_value(dict(young_pos(case["ticket"])), 1.0, r["x"]) if ok else None
        chip = PK.filtered_text(r)
        check(ok and (not e.get("dead") or chip.endswith("ignored: pool dead")),
              "P2 %s: %s booked at %sx (raw %sx), 6 h %sx%s%s" % (case["name"], case["kind"], r["x"], r["rawX"], r["x6"],
                                                                  (", 3 -> %.2f" % eur) if eur is not None else "", (", chip '%s'" % chip) if chip else ""))
    check(set(out) == {"Doggo", "Banana Cat", "Husky", "SpaceX AI", "HIRE", "hi"}, "P2 all six named cases are in the fixture (%s)" % sorted(out))
    return out


def _ohlcv_mock(mock, pools, asked):
    """The mock's GeckoTerminal OHLCV answer for the test's pools: pools[pool] = (px, fn(ts_ms) -> multiple or None, mode) where mode
    "m15only" answers only 15-minute requests; other pools get the mock's own answer (its /__nocandle switch included). Every OHLCV
    request is noted in asked as (pool, before_timestamp, aggregate)."""
    orig = mock.handle

    def handle(path, query):
        m = re.match(r"^/api\.geckoterminal\.com/api/v2/networks/solana/pools/([^/]+)/ohlcv/", path)
        if not m:
            return orig(path, query)
        q = urllib.parse.parse_qs(query)
        before, agg, lim = int(q["before_timestamp"][0]), int(q["aggregate"][0]), int(q["limit"][0])
        asked.append((m.group(1), before, agg))
        if m.group(1) not in pools:
            return orig(path, query)
        px, fn, mode = pools[m.group(1)]
        if mode == "none" or (mode == "m15only" and agg == 1):
            return 200, {"data": {"attributes": {"ohlcv_list": []}}}
        lst, top = [], before // (60 * agg) * (60 * agg)
        for i in range(lim):
            ts = top - (i + 1) * 60 * agg
            x = fn(ts * 1000)
            if x is not None:
                lst.append([ts, px * x, px * x * 1.01, px * x * 0.99, px * x, 1000.0])
        return 200, {"data": {"attributes": {"ohlcv_list": lst}}}
    mock.handle = handle


def _run_peak(S, d, url, now, deadline=60):
    t = time.time()
    p = subprocess.run([S.PY, os.path.join(HERE, "peak.py"), "run", "--dir", d, "--mock", url, "--now", str(now), "--deadline-s", str(deadline)],
                       capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, MEMEBOT_PAUSE="0"))
    try:
        out = json.loads((p.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        out = {}
    return p, out, time.time() - t


def _tree(d):
    return {os.path.relpath(f, d): open(f, "rb").read() for f in glob.glob(os.path.join(d, "**", "*"), recursive=True) if os.path.isfile(f) and "/.git/" not in f}


def _p3_to_p7(check, PK, M, S, tmp, named):
    print("== peak P3: peak.py run on a copy of the recommend-mode db with the mock's OHLCV")
    rec = os.path.join(tmp, "rec")
    proc, secs, mock = S.spot_cycle(rec, frozen=True)
    pos0 = M.positions(rec)
    state = json.load(open(os.path.join(rec, "db", "memebot", "state.json"), encoding="utf-8"))
    since = state.get("paperSince")
    hold = [p for p in pos0.values() if p.get("grp") == "hold"]
    young = sorted((p for p in pos0.values() if p.get("grp") == "young"), key=lambda p: p["_id"])
    check(proc.returncode == 0 and len(hold) == 1 and len(young) == 5 and since == S.T0,
          "P3 the recommend cycle bought 1 top pick and 5 new launches (%.1f s), paperSince = the run" % secs)
    if proc.returncode != 0 or len(hold) != 1 or len(young) != 5:
        print(proc.stderr[-2000:])
        return
    d = os.path.join(tmp, "pk")
    shutil.copytree(rec, d)
    T0 = S.T0
    H_, Y0, Y1, Y2, Y3, Y4 = hold[0], young[0], young[1], young[2], young[3], young[4]
    ent = lambda p: int(p.get("entryAt") or p["t"])

    def add_pos(src, tag, t, grp=None):
        doc = {k: v for k, v in src.items() if not k.startswith("_")}
        doc.update(t=t, entryAt=t)
        if grp:
            doc["grp"] = grp
        pid = "%s-%s-%s" % (time.strftime("%Y-%m-%dT%H%M%S", time.gmtime(t / 1000)), "y" if doc["grp"] == "young" else doc["grp"][0], tag)
        json.dump(doc, open(os.path.join(d, "db", "memepos", pid + ".json"), "w"), separators=(",", ":"))
        return pid, dict(doc, _id=pid)
    pid_a, A = add_pos(Y1, "SHAREA-x", T0 + HOUR)               # two more positions in Y1's pool, an hour apart
    pid_b, B = add_pos(Y1, "SHAREB-x", T0 + 2 * HOUR)
    pid_open, _ = add_pos(Y2, "OPEN-x", T0 + 5 * HOUR)          # its window is still open at the run
    pid_old, _ = add_pos(Y3, "OLD-x", T0 - 2 * HOUR)            # bought before the restart: not in the account
    pid_pick, _ = add_pos(H_, "PICK-x", T0 + 10 * MIN, grp="pick")   # pick mode: not in the account
    exits = os.path.join(d, "db", "memeexit")
    os.makedirs(exits, exist_ok=True)
    json.dump({"pos": Y4["_id"], "t": T0 + HOUR, "px": Y4["px"] * 11, "frac": 1.0, "why": "tp", "eur": 31.58, "grp": "young", "rule": M.RULE, "at": ent(Y4) + 50 * MIN},
              open(os.path.join(exits, Y4["_id"] + "-1.json"), "w"))
    json.dump({"pos": Y3["_id"], "t": T0 + 2 * HOUR, "px": 0, "frac": 1.0, "why": "rug", "eur": 0.0, "grp": "young", "rule": M.RULE},
              open(os.path.join(exits, Y3["_id"] + "-1.json"), "w"))
    json.dump({"t": T0 + HOUR, "mode": "pick", "rule": M.RULE}, open(os.path.join(d, "db", "memeruns", "healthy.json"), "w"))   # the scan before the rug exit
    pools, asked = {}, []
    by_pair = {c["a"][:20] + "pair": c for c in mock.coins}
    px_of = lambda p: by_pair[p["pair"]]["px"] * by_pair[p["pair"]]["mult"]
    eH, e0, e3 = ent(H_), ent(Y0), ent(Y3)
    pools[H_["pair"]] = (px_of(H_), lambda t: 2.0 if eH + 60 * MIN <= t < eH + 64 * MIN else 1.0, "")
    pools[Y0["pair"]] = (px_of(Y0), lambda t: 9.0 if e0 + 100 * MIN <= t < e0 + 101 * MIN else 1.0, "")
    pools[Y1["pair"]] = (px_of(Y1), lambda t: 1.0 + 0.1 * (t - T0) / HOUR, "")
    pools[Y2["pair"]] = (px_of(Y2), lambda t: 1.5 if ent(Y2) + 60 * MIN <= t < ent(Y2) + 90 * MIN else 1.0, "m15only")
    pools[Y3["pair"]] = (px_of(Y3), lambda t: 2.0 if e3 + 30 * MIN <= t < e3 + 34 * MIN else (5.0 if e3 + 90 * MIN <= t < e3 + 96 * MIN else 1.0), "")
    _ohlcv_mock(mock, pools, asked)
    srv = S.serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    urllib.request.urlopen(url + "/__nocandle?a=%s&on=1" % by_pair[Y4["pair"]]["a"]).read()     # Y4's pool sends no candles
    now = T0 + 9 * HOUR
    before = _tree(d)
    try:
        r1, o1, _ = _run_peak(S, d, url, now)
        docs1 = M.load_docs(d, "memepeak")
        raw1 = {k: open(os.path.join(d, "db", "memepeak", k + ".json"), "rb").read() for k in docs1}
        after = _tree(d)
        r2, o2, _ = _run_peak(S, d, url, now)
        docs2 = M.load_docs(d, "memepeak")
        r3, o3, _ = _run_peak(S, d, url, now + 5 * MIN)
        docs3 = M.load_docs(d, "memepeak")
        raw3 = {k: open(os.path.join(d, "db", "memepeak", k + ".json"), "rb").read() for k in docs3}
        r4, o4, _ = _run_peak(S, d, url, now + 10 * MIN)
        raw4 = {k: open(os.path.join(d, "db", "memepeak", k + ".json"), "rb").read() for k in M.load_docs(d, "memepeak")}
    finally:
        srv.shutdown()
        srv.server_close()
    closed = {H_["_id"], Y0["_id"], Y1["_id"], Y2["_id"], Y3["_id"], Y4["_id"], pid_a, pid_b}
    check(r1.returncode == 0 and set(docs1) == closed and o1.get("items") == 8 and o1.get("ok") == 6 and o1.get("m15") == 1 and o1.get("waiting") == 1
          and set(o1) == {"items", "ok", "m15", "est", "unit", "waiting", "secs", "why"},
          "P3 docs only for the 8 closed in_account windows: none for the open window, the pre-restart buy or the pick-mode position (%s)" % json.dumps(o1))
    new = set(after) - set(before)
    changed = [k for k in before if k in after and before[k] != after[k]]
    check(not changed and all(k.startswith(("db/memepeak/", "candles/")) for k in new) and all(re.search(r"_pk\d+\.txt$", k) for k in new if k.startswith("candles/")),
          "P3 peak.py writes only db/memepeak/<pid>.json and candles/<pool>_pk<minute>.txt, and changes no file it found (%d new files)" % len(new))
    g = lambda pid: docs1.get(pid) or {}
    near = lambda a, b, tol=0.01: a is not None and abs(a - b) <= tol * abs(b)
    dh, d0, d2, d3, d4 = g(H_["_id"]), g(Y0["_id"]), g(Y2["_id"]), g(Y3["_id"]), g(Y4["_id"])
    check(dh.get("state") == "ok" and dh.get("src") == "m1" and dh.get("res") == 1 and near(dh.get("x"), 2.0) and near(dh.get("x6"), 1.0)
          and 59 <= (dh["at"] - eH) / MIN <= 61 and dh.get("ticket") == 50.0 and dh.get("n", 0) >= 359,
          "P3 the top pick's 4-minute plateau at 2x is booked: %sx at minute %d, 6 h %sx" % (dh.get("x"), (dh.get("at", 0) - eH) // MIN, dh.get("x6")))
    check(near(d0.get("x"), 1.0) and any("unconfirmed" in c for c in d0.get("cut") or []), "P3 a one-minute 9x print is not booked (%sx, %s)" % (d0.get("x"), d0.get("cut")))
    check(d2.get("state") == "ok" and d2.get("src") == "m15" and d2.get("res") == 15 and near(d2.get("x"), 1.5),
          "P3 only 15-minute candles: booked as m15, a lower bound (%sx)" % d2.get("x"))
    check(d3.get("state") == "ok" and near(d3.get("x"), 2.0) and d3.get("x6") == 0 and (d3.get("dead") or {}).get("why") == "rug exit"
          and (d3.get("dead") or {}).get("at") == T0 + HOUR and (d3.get("cut") or [""])[0].startswith("pool dead: rug exit"),
          "P3 a rug exit ends the window at the last healthy scan (memeruns): the 2x before it counts, the 5x after it does not, 6 h = 0 (%sx)" % d3.get("x"))
    da, db_, dy1 = g(pid_a), g(pid_b), g(Y1["_id"])
    files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(d, "candles", Y1["pair"] + "_pk*.txt")))
    befs = sorted({b for p_, b, a_ in asked if p_ == Y1["pair"] and a_ == 1})
    exp = lambda e: (1.0 + 0.1 * (e + 6 * HOUR - T0) / HOUR) / (1.0 + 0.1 * (e - T0) / HOUR)
    check(len(files) == 3 and len(befs) == 3 and files == sorted("%s_pk%d.txt" % (Y1["pair"], ent(p) // MIN) for p in (Y1, A, B))
          and all(near(doc.get("x"), exp(e), 0.005) and doc["entryAt"] == e and doc["end"] == e + 6 * HOUR and e <= doc["at"] <= doc["end"] for doc, e in ((dy1, ent(Y1)), (da, ent(A)), (db_, ent(B)))),
          "P3 pk<minute> keeps three positions in one pool apart: own files, own requests, own windows (%s / %s / %s)" % (dy1.get("x"), da.get("x"), db_.get("x")))
    y4_aggs = [a_ for p_, b, a_ in asked if p_ == Y4["pair"]]
    check(d4.get("state") == "waiting" and d4.get("tries") == 1 and d4.get("x") is None and d4.get("eur") is None and y4_aggs == [1, 15] * 3
          and (docs2.get(Y4["_id"]) or {}).get("tries") == 2 and (docs2.get(Y4["_id"]) or {}).get("state") == "waiting"
          and (docs3.get(Y4["_id"]) or {}).get("state") == "est" and (docs3.get(Y4["_id"]) or {}).get("tries") == 3
          and (docs3.get(Y4["_id"]) or {}).get("src") == "est" and (docs3.get(Y4["_id"]) or {}).get("x") == PK.TP_X
          and (docs3.get(Y4["_id"]) or {}).get("at") == ent(Y4) + 50 * MIN and o2.get("items") == 1 and o3.get("est") == 1,
          "P3 a pool without candles (/__nocandle in the mock): waiting (1 min, then 15 min asked), waiting again, then est from its take-profit after 3 runs (%s)"
          % json.dumps([{k: (x.get(Y4["_id"]) or {}).get(k) for k in ("state", "tries", "src", "x", "at")} for x in (docs1, docs2, docs3)] + [y4_aggs, o2.get("items"), o3.get("est")]))
    check(r2.returncode == r3.returncode == r4.returncode == 0 and all(raw1[k] == raw3[k] for k in raw1 if k != Y4["_id"]) and raw3 == raw4
          and o4.get("items") == 0 and o4.get("why") == "no window to price",
          "P3 a second, third and fourth run change no settled doc (byte for byte), and the fourth finds nothing to price")

    print("== peak P4: euros and base")
    pos3 = M.positions(d)
    allr = [(pid, doc) for pid, doc in docs3.items()]
    eur_ok = all((doc["x"] is None and doc["eur"] is None) or doc["eur"] == round(M.pos_value(pos3[pid], 1.0, doc["x"]), 2) for pid, doc in allr)
    eur6_ok = all((doc["x6"] is None and doc["eur6"] is None) or doc["eur6"] == round(M.pos_value(pos3[pid], 1.0, doc["x6"]), 2) for pid, doc in allr)
    check(eur_ok and eur6_ok and dh.get("eur") == round(M.pos_value(H_, 1.0, dh["x"]), 2) and dh["eur"] > 90,
          "P4 every doc's eur and eur6 are memebot.pos_value(p, 1.0, x) with the paper fees (top pick 50 at 2x -> %s)" % dh.get("eur"))
    check(all(base_ok(doc) for _, doc in allr) and all(base_ok(r) for r in named.values()),
          "P4 base is never above max(cpx, px) (%d run docs, %d named cases)" % (len(allr), len(named)))
    check(list(dh) == list(PK.DOC_KEYS) and dh.get("v") == PK.PEAK_V and dh.get("pos") == H_["_id"] and dh.get("upd") == now,
          "P4 the doc carries the frozen keys in order (%d)" % len(dh))

    print("== peak P5: the trader's docs are the same with and without the memepeak docs")
    wi, wo = os.path.join(tmp, "with"), os.path.join(tmp, "without")
    shutil.copytree(d, wi)
    shutil.copytree(d, wo)
    shutil.rmtree(os.path.join(wo, "db", "memepeak"))
    for f in glob.glob(os.path.join(wo, "candles", "*_pk*.txt")):
        os.remove(f)
    env = S.frozen_env(dict(os.environ, MEMEBOT_PAUSE="0"), tmp)
    runs = [subprocess.run([S.PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", x, "--now", str(now + 20 * MIN), "--recommend", "--offline"],
                           capture_output=True, text=True, encoding="utf-8", env=env) for x in (wi, wo)]
    fa, fb = S.trader_files(wi), S.trader_files(wo)
    raw = lambda f: open(f, "rb").read()
    diffs = sorted(k for k in set(fa) & set(fb) if raw(fa[k]) != raw(fb[k]))
    st = json.load(open(fa.get("db/memebot/state.json") or os.devnull)) if "db/memebot/state.json" in fa else {}
    curves = [k for k in fa if k.startswith("db/memecurve/")]
    check(all(p.returncode == 0 for p in runs) and set(fa) == set(fb) and len(fa) > 15 and not diffs and "paper" in st and curves
          and all("paper" in json.load(open(fa[k])) for k in curves[-1:]),
          "P5 %d trader docs (memecurve 'paper', state 'paper', recommend, marks, positions, exits%s) byte for byte the same with and without memepeak %s"
          % (len(fa), ", train.json" if "db/memebot/train.json" in fa else "; no train.json in this db", diffs or ""))
    src = open(os.path.join(HERE, "peak.py"), encoding="utf-8").read()
    used = set(re.findall(r"\bM\.([A-Za-z_][A-Za-z0-9_]*)", src))
    check(used <= {"num", "load_json", "load_docs", "positions", "in_account", "pos_value", "HOLD_TP"} and not re.search(r"\b(learn|bin_model|blended_weights|cmd_train|train)\(", src)
          and "memepeak" not in open(os.path.join(HERE, "memebot.py"), encoding="utf-8").read(),
          "P5 peak.py reads memebot only through %s; memebot.py never names memepeak (hindsight feeds nothing)" % sorted(used))

    print("== peak P6: memepeak and memeradar reach the results branch through sync")
    import bot as B
    real = all(l in B.SYNC_IGNORE.splitlines() for l in WP4_LINES)
    merged = os.path.exists(os.path.join(HERE, "selftest_scanside.py"))
    os.makedirs(os.path.join(wi, "db", "memeradar"), exist_ok=True)
    json.dump({"v": 1, "hour": "2026-10-13T20", "coins": {}}, open(os.path.join(wi, "db", "memeradar", "2026-10-13T20.json"), "w"))
    bare = os.path.join(tmp, "results.git")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    saved = B.SYNC_IGNORE
    try:
        if not real:
            B.SYNC_IGNORE = saved + "".join(l + "\n" for l in WP4_LINES)      # stand-in for WP4's lines until that package is merged
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            B.sync(wi, remote=bare)
    finally:
        B.SYNC_IGNORE = saved
    ls = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", "results"], capture_output=True, text=True).stdout.split()
    n_pk = sum(1 for x in ls if x.startswith("db/memepeak/") and x.endswith(".json"))
    check((real or not merged) and n_pk == len(docs3) and "db/memeradar/2026-10-13T20.json" in ls and not any(x.startswith(("candles/", ".peaktmp")) for x in ls)
          and "report.html" in ls,
          "P6 sync carries %d memepeak docs and the memeradar hour doc to the results branch, never the peak candle files (%s)"
          % (n_pk, "bot.py's own SYNC_IGNORE" if real else "stand-in for WP4's SYNC_IGNORE lines: WP4 not merged on this branch"))

    print("== peak P7: the deadline holds against a slow GeckoTerminal")
    slow = os.path.join(tmp, "slow")
    shutil.copytree(rec, slow)
    calls = []

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(time.time())
            threading.Event().wait(5.0)            # 5 s an answer (not time.sleep: the main selftest turns that off in its process)
            raw = json.dumps({"data": {"attributes": {"ohlcv_list": []}}}).encode()
            try:
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    srv2 = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    srv2.daemon_threads = True
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        p7, o7, s7 = _run_peak(S, slow, "http://127.0.0.1:%d" % srv2.server_address[1], now, deadline=12)
    finally:
        srv2.shutdown()
        srv2.server_close()
    left = M.load_docs(slow, "memepeak")
    check(p7.returncode == 0 and s7 <= 15.0 and o7.get("why") == "deadline" and o7.get("items") == 6 and 2 <= len(calls) <= 3
          and len(left) == 1 and all(doc["state"] == "waiting" and doc["tries"] == 1 for doc in left.values()),
          "P7 6 windows, 5 s an answer, --deadline-s 12: ended after %.1f s with %d requests, one window asked (waiting), the rest untouched" % (s7, len(calls)))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    peak_checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
