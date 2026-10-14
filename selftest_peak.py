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
P8  each filter rule on its own (jump, market-cap cap, the liquidity floor relative to the entry, the 5-minute confirmation), the
    base, the value at 6 h (a dust print lowers it, never raises it; a glitch print in a quiet live pool is no collapse; a low
    close at the very end can recover after the end), the order of the DexScreener points, the filtered chip
P9  booking without candles: the 2-minute settle wait, the order and cap of items, an empty answer 48 h after the end, a failed
    fetch that never settles a window at once, a position without a pool, the estimate from stored paths (x >= 1.0) and from a
    time exit, where the DexScreener points come from, the rug exit's last healthy scan clamped to the entry, the coverage test,
    malformed docs
P10 GeckoTerminal failing (in-process runs on a copy of the recommend-mode db): 5xx (also between 404s), timeouts, 429s through the wait ladder, a block
    page, a changed shape, candle rows it cannot read (objects, ms, ISO, tiny timestamps or ones newer than asked, closes null or text; numeric strings
    and closes of 0 are still an answer), one pool
    answering oddly after a readable first answer, an answer sent a byte at a time; no doc for windows under 48 h, a waiting doc
    with one more try for older ones, GeckoTerminal off for the run, the next healthy run prices from minute candles, docs written
    as the run goes
P11 the low within 6 h (lo, loAt, eurLo; the max loss without the stop-loss): a staircase down, a dust spike down that is no low, one
    print the next close took back, a dead pool that is a real low (collapse, rug exit, liquidity floor), a slow fall in a live pool,
    a sparse pool, lo <= 1 and lo <= x6 in every case, no low for unit or waiting, eurLo after the paper fees, the estimate's low
    (paper exits and DexScreener prices inside the window), and an older version's doc that is never made worse (keep_better)
P12 the best within 6 h is never below the value at 6 h: a price that rises into the end (the last close has no next close to
    confirm it), a one-candle jump at the very end without support stays cut, the estimate from a time exit above the entry, an
    older version's doc whose best was below its value at 6 h (keep_better), and x >= x6 in every live case and named fixture
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
        _p8(check, PK, M)
        _p9(check, PK, M, tmp)
        _p10(check, PK, M, S, tmp)
        _p11(check, PK, M)
        _p12(check, PK, M)
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
    closed = {H_["_id"], Y0["_id"], Y1["_id"], Y2["_id"], Y3["_id"], Y4["_id"], pid_a, pid_b, pid_old}   # the pre-restart buy too (shown apart)
    check(r1.returncode == 0 and set(docs1) == closed and o1.get("items") == 9 and o1.get("ok") == 7 and o1.get("m15") == 1 and o1.get("waiting") == 1
          and set(o1) == {"items", "ok", "m15", "est", "unit", "waiting", "secs", "why"},
          "P3 docs for the 8 closed in_account windows and the pre-restart buy (shown apart); none for the open window or the pick-mode position (%s)" % json.dumps(o1))
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
    lo_ok = all((doc["lo"] is None and doc["eurLo"] is None and doc["loAt"] is None) if doc["x"] is None else
                (doc["lo"] is not None and 0 <= doc["lo"] <= 1.0 and (doc["x6"] is None or doc["lo"] <= doc["x6"]) and doc["entryAt"] <= doc["loAt"] <= doc["end"]
                 and doc["eurLo"] == round(M.pos_value(pos3[pid], 1.0, doc["lo"]), 2)) for pid, doc in allr)
    check(PK.PEAK_V == 2 and lo_ok and sum(1 for _, doc in allr if doc["lo"] is not None) >= 3,
          "P11 every run doc books its low within 6 h: lo between 0 and the entry, never above x6, loAt inside the window, eurLo = "
          "memebot.pos_value(p, 1.0, lo) after the paper fees; none without a booked best (PEAK_V %d, %d docs with a low)" % (
              PK.PEAK_V, sum(1 for _, doc in allr if doc["lo"] is not None)))

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
    check(used <= {"num", "load_json", "load_docs", "positions", "in_account", "pos_value", "HOLD_TP", "PAPER_GROUPS"} and not re.search(r"\b(learn|bin_model|blended_weights|cmd_train|train)\(", src)
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


def _p8(check, PK, M):
    print("== peak P8: each filter rule on its own, the base, the value at 6 h, the filtered chip (direct peak_of cases)")
    T0 = 1_791_800_000_000
    end = T0 + 6 * HOUR
    pk = lambda c, px=1e-5, **k: PK.peak_of(c, T0, end, px, **k)
    seg = lambda pts: [[T0 + m * MIN, 1e-5 * x, 1e-5 * x, 1e-5 * x, 1e-5 * x, v] for m, x, v in pts]
    flat = lambda m0, m1, x, v=2000.0: [(m, x, v) for m in range(m0, m1 + 1)]
    geo = lambda m0, m1, x0, x1, v=2000.0: [(m, x0 * (x1 / x0) ** ((m - m0) / (m1 - m0)), v) for m in range(m0, m1 + 1)]
    show = lambda r: {k: r.get(k) for k in ("x", "x6", "base", "dead", "cut")}
    starts = lambda r, w: any(str(c).startswith(w) for c in r["cut"])

    r1 = pk(seg(flat(0, 9, 1.0) + flat(10, 11, 4.0) + flat(12, 60, 1.0)))
    r2 = pk(seg(flat(0, 9, 1.0) + flat(10, 30, 4.0) + flat(31, 60, 1.0)))
    check(r1["x"] <= 1.01 and starts(r1, "jump") and not starts(r1, "cap") and 3.99 <= r2["x"] <= 4.01 and not r2["cut"],
          "P8 jump: a two-candle step to 4x (over 3x the previous close) without support is not booked; held for 21 closes on $2,000 it is (%s / %s)"
          % (show(r1), r2["x"]))
    climb = seg(geo(0, 100, 1.0, 6.0, 500.0) + flat(101, 150, 6.0, 500.0) + flat(151, 200, 5.5, 500.0))
    r1, r2 = pk(climb, mc0=20e6), pk(climb, mc0=5e6)
    check(r1["x"] <= 5.0 and starts(r1, "cap") and not starts(r1, "jump") and r2["x"] >= 5.9 and not r2["cut"],
          "P8 market-cap cap: 6x from a $20M entry is over $100M and thin ($500 candles): capped under 5x; from a $5M entry it counts (%s / %s)"
          % (show(r1), r2["x"]))
    c = seg(flat(0, 29, 1.0) + flat(30, 359, 2.5))
    r1 = pk(c, ds_points=[(T0 + 30 * MIN, None, 3_000.0)], liq0=50_000.0)
    r2 = pk(c, ds_points=[(T0 + 30 * MIN, None, 3_000.0)], liq0=5_000.0)
    check(r1["x"] <= 1.01 and r1["x6"] == 0 and (r1["dead"] or {}).get("why") == "liquidity" and r1["cut"][0].startswith("pool dead: liquidity $3,000 at minute 30")
          and r2["x"] >= 2.49 and not r2["dead"],
          "P8 liquidity floor: $3,000 is dead for a pool bought at $50,000 liquidity (10%% of it), alive for one bought at $5,000 ($1,000 floor) (%s / %s)"
          % (show(r1), r2["x"]))
    r1 = pk(seg(flat(0, 9, 1.0) + [(10, 2.5, 2000.0), (20, 2.5, 2000.0)] + flat(21, 60, 1.0)))
    r2 = pk(seg(flat(0, 9, 1.0) + [(10, 2.5, 2000.0), (14, 2.5, 2000.0)] + flat(15, 60, 1.0)))
    check(r1["x"] <= 1.01 and starts(r1, "unconfirmed") and 2.49 <= r2["x"] <= 2.51,
          "P8 confirmation: a close at 2.5x whose next close comes 10 min later is not confirmed; 4 min later it is (%s / %s)" % (show(r1), r2["x"]))
    c = seg(flat(0, 99, 1.0) + flat(100, 110, 2.0) + flat(111, 359, 1.0))
    b = {px: pk(c, px=px) for px in (1.5e-5, 5e-5, 0.25e-5, 0.5e-5)}
    check(b[1.5e-5]["base"] == 1.5e-5 and abs(b[1.5e-5]["x"] - 2.0 / 1.5) < 1e-4 and all(b[px]["base"] == 1e-5 and b[px]["x"] == 2.0 for px in (5e-5, 0.25e-5, 0.5e-5)),
          "P8 base = max(cpx, px) only when px/cpx is between 1/3 and 3: paid 1.5x the candles -> base px (%sx); 5x, 1/4 or 1/2 -> base cpx (%s)"
          % (b[1.5e-5]["x"], [b[px]["x"] for px in (5e-5, 0.25e-5, 0.5e-5)]))
    e1 = pk(seg(geo(0, 59, 1.0, 2.0) + flat(60, 119, 2.0) + geo(120, 359, 2.0, 0.3, 10.0)[1:]))
    e14b = pk(seg(geo(0, 59, 1.0, 1.5) + flat(60, 359, 1.4, 10.0)))
    e14 = pk(seg(geo(0, 59, 1.0, 1.5) + [(m, 0.05 if m == 180 else 1.4, 5.0 if m == 180 else 10.0) for m in range(60, 360)]))
    up = pk(seg(flat(0, 358, 1.0) + [(359, 50.0, 1.0)]))
    check(e1["x"] == 2.0 and e1["x6"] == 0.3 and not e1["dead"] and e14b["x6"] == 1.4 and up["x6"] == 1.0 and starts(up, "dust"),
          "P8 value at 6 h: a fade to 0.3x on $10 candles gives 0.3x (not the last $2,000 close at 2x), a quiet pool at 1.4x gives 1.4x, a $1 print at 50x "
          "at the end leaves it at 1.0x (%s / %s / %s)" % (e1["x6"], e14b["x6"], up["x6"]))
    check(not e14["dead"] and e14["x6"] == 1.4 and not any(starts(e14, w) for w in ("collapse", "pool dead")),
          "P8 a $5 glitch print at 0.05x in a quiet pool trading on $10 candles at 1.4x is no collapse (the small closes count as its recovery) (%s)" % show(e14))
    far = pk(seg(flat(0, 19, 1.0) + [(20, 1e-7, 2000.0)] + flat(25, 30, 5000.0, 0.02)))
    check((far["dead"] or {}).get("why") == "collapse" and far["x6"] == 0 and starts(far, "collapse"),
          "P8 a dust print far above the held level (5,000x on 2 cents) is no recovery: the pool is dead after the pull (%s)" % show(far))
    c = seg(flat(0, 358, 1.0) + [(359, 0.05, 2000.0)] + flat(360, 361, 1.0))
    e6 = pk(c)
    gone = pk(seg(flat(0, 358, 1.0) + [(359, 0.05, 2000.0)] + flat(366, 370, 1.0)))
    check(not e6["dead"] and e6["x6"] == 0.05 and e6["x"] == 1.0 and (gone["dead"] or {}).get("why") == "collapse" and gone["x6"] == 0,
          "P8 a low close in the last minute that recovers in the 2 minutes after the end (what the fetch returns) is no collapse; x6 is that close "
          "(%s); a recovery only later does not count (%s)" % (show(e6), gone["dead"]))
    c = seg(flat(0, 359, 1.0))
    pts = [(T0 + 3 * MIN, 1e-4, 50_000.0), (T0 + 19 * MIN, 2e-4, 60_000.0)]
    ra, rb = pk(c, ds_points=pts), pk(c, ds_points=pts[::-1])
    check(ra == rb and ra["state"] == "unit" and "minute 3" in ra["cut"][-1],
          "P8 the DexScreener points are taken in time order, whatever order the docs were read in (%s)" % ra["cut"])
    ft = PK.filtered_text
    cases = [({"cut": ["jump: 1 level over 3x the previous close without support"], "rawX": 4.0, "x": 4.0}, ""),
             ({"cut": ["unit: candles 26.0x away from DexScreener's price at minute 10"], "rawX": 1.04, "x": None, "state": "unit"}, ""),
             ({"cut": [], "rawX": 9.0, "x": 1.0}, ""),
             ({"cut": ["pool dead: liquidity $40 at minute 25", "dust: 59,257x on $0 volume"], "rawX": 59257.6, "x": 1.0}, "59,258x ignored: pool dead"),
             ({"cut": ["unconfirmed: 9.00x held for one candle only"], "rawX": 9.0, "x": 1.0}, "9.00x ignored: unconfirmed"),
             (None, "")]
    got = [ft(doc) for doc, _ in cases]
    check(got == [want for _, want in cases], "P8 the filtered chip names the raw best close and the first rule only when a filter lowered the result (%s)" % got)


def _jdump(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))


def _p9(check, PK, M, tmp):
    print("== peak P9: booking without candles (items, the 48 h estimate, failed fetches, stored paths, time exits, DexScreener points)")
    d = os.path.join(tmp, "p9")
    db = lambda *a: os.path.join(d, "db", *a)
    S0 = 1_791_600_000_000                                       # paperSince of this small db
    base = {"paper": M.PAPER_RULE, "ticket": 3.0, "px": 1e-5, "liq": 20_000.0, "mc": 100_000.0}
    pos = {}

    def add(tag, grp, t, **k):
        pid = "%s-%s-%s" % (time.strftime("%Y-%m-%dT%H%M%S", time.gmtime(t / 1000)), "y" if grp == "young" else "h", tag)
        doc = dict(base, grp=grp, t=t, entryAt=t + MIN, sym=tag, addr="ADDR" + tag, pair="PAIR" + tag)
        doc.update(k)
        _jdump(db("memepos", pid + ".json"), doc)
        pos[tag] = (pid, doc)
        return pid
    tA, tB, tC, tD, tE, tG = (S0 + h * HOUR for h in (1, 2, 3, 4, 5, 7))
    add("PATHUP", "young", tA)
    add("TIMEX", "young", tB)
    add("PATHLOW", "young", tC)
    add("DSPTS", "hold", tD, ticket=50.0)
    add("RUGGED", "young", tE)
    add("NOPOOL", "young", tG, pair="")
    _jdump(db("memebot", "state.json"), {"paperSince": S0, "paperRule": M.PAPER_RULE})
    up = [[m, x, x, x, x] for m, x in [(m, 1.0 + 2.0 * m / 60) for m in range(0, 61)] + [(m, 3.0) for m in range(61, 121)] + [(m, 2.0) for m in range(121, 401)]]
    low = [[m, 0.5, 0.5, 0.5, 0.5] for m in range(0, 401)]
    for tag, t, path in (("PATHUP", tA, up), ("PATHLOW", tC, low)):
        _jdump(db("memeyoung", "%d.json" % t), {"t": t, "picks": [{"addr": "ADDR" + tag, "pair": "PAIR" + tag, "sym": tag, "px": 1e-5}],
                                                "outs": {"1": {"t": t + 7 * HOUR, "picks": [{"sym": tag, "path": path}]}}})
    _jdump(db("memeexit", pos["TIMEX"][0] + "-1.json"), {"pos": pos["TIMEX"][0], "t": tB + 6 * HOUR + 5 * MIN, "px": 0.8e-5, "frac": 1.0, "why": "time", "grp": "young"})
    eD = tD + MIN
    _jdump(db("memeearly", "a.json"), {"t": eD - 2 * MIN, "coins": [
        {"addr": "ADDRDSPTS", "pair": "PAIRDSPTS", "px": 1e-5, "liq": 30_000.0, "p2": {"t": eD, "px": 1.1e-5, "liq": 29_000.0}, "p60": {"t": eD + 58 * MIN, "px": 1.3e-5, "liq": 28_000.0}},
        {"addr": "ADDRDSPTS", "pair": "PAIROTHER", "px": 9.0, "liq": 1.0}]})
    _jdump(db("memebot", "marks.json"), {"t": eD + 3 * HOUR, "px": {pos["DSPTS"][0]: 2e-5}, "liq": {pos["DSPTS"][0]: 25_000.0}})
    _jdump(db("memerec", "%d.json" % tD), {"t": tD, "picks": [{"addr": "ADDRDSPTS", "pair": "PAIRDSPTS", "sym": "DSPTS", "px": 1e-5}],
                                         "outs": {"24": {"t": eD + 4 * HOUR, "picks": [{"sym": "DSPTS", "gone": True}]}}})
    eE = tE + MIN
    _jdump(db("memeruns", "before.json"), {"t": eE - 10 * MIN})
    _jdump(db("memeexit", pos["RUGGED"][0] + "-1.json"), {"pos": pos["RUGGED"][0], "t": eE + 20 * MIN, "px": 0, "frac": 1.0, "why": "rug", "grp": "young"})
    # malformed docs of every reader: none may stop the run
    _jdump(db("memeearly", "b.json"), {"t": eD, "coins": 7})
    _jdump(db("memeearly", "c.json"), {"t": eD, "coins": [{"addr": ["ADDRDSPTS"]}, {"addr": "ADDRDSPTS", "pair": 5, "px": 1.0, "liq": 2.0}, 7, {"addr": "ADDRDSPTS", "pair": "PAIRZ", "p2": "x"}]})
    _jdump(db("memeyoung", "%d.json" % (tA + 1)), {"t": tA, "picks": 5})
    _jdump(db("memeyoung", "%d.json" % (tA + 2)), {"t": tA, "picks": [{"addr": "ADDRPATHUP", "sym": "PATHUP", "px": 1e-5}], "outs": {"1": 3, "24": {"picks": "x"}, "6": {"picks": [{"sym": "PATHUP", "path": [[0, "a", 1, 1, 1], 5]}]},
                                                                  "12": {"picks": [{"sym": "PATHUP", "path": 5}]}, "48": {"picks": [{"sym": "PATHUP", "path": [["0", "1", "1", "1", "1"], ["1", "1", "1", "1", "1"]]}]}}})
    _jdump(db("memerec", "%d.json" % (tD + 1)), {"t": tD, "outs": [1, 2], "picks": [{"addr": "ADDRDSPTS"}, "x"]})
    try:
        ctx = PK.context(d)
        crash = None
    except Exception as e:                                       # noqa: the check below says what broke
        ctx, crash = None, "%s: %s" % (type(e).__name__, e)
    check(crash is None and len(ctx["pos"]) == 6 and ctx["since"] == S0,
          "P9 malformed docs (coins not a list, an address that is a list, picks not a list, outs not a dict, a path of text or no list) are skipped, never fatal (%s)"
          % (crash or "%d positions read" % len(ctx["pos"])))
    if crash:
        return
    P = {tag: dict(ctx["pos"][pid]) for tag, (pid, _) in pos.items()}
    pid = {tag: v[0] for tag, v in pos.items()}
    end = lambda tag: PK.window(P[tag])[1]
    pts = sorted(PK.ds_for(ctx, pid["DSPTS"], P["DSPTS"]), key=lambda q: (q[0], q[2] or 0))
    want = [(eD - 2 * MIN, 1e-5, 30_000.0), (eD, 1.1e-5, 29_000.0), (eD + 58 * MIN, 1.3e-5, 28_000.0), (eD + 3 * HOUR, 2e-5, 25_000.0), (eD + 4 * HOUR, None, 0.0)]
    check(pts == want, "P9 the DexScreener points of a position: the early list (list time, +2 min, +60 min) of its own pool only, the marks, and a tip "
                       "check that found it gone ($0); none from another pool of the coin (%d points)" % len(pts))
    mk = dict(ctx, marks={"t": eD, "px": ["x"], "liq": "x"})
    check(len(PK.ds_for(mk, pid["DSPTS"], P["DSPTS"])) == 4, "P9 marks.json with px not a dict gives no marks point and no error")
    eRug = PK.window(P["RUGGED"])[0]
    ok1 = PK.rug_ok_at(ctx, P["RUGGED"])
    ok2 = PK.rug_ok_at(dict(ctx, runs=sorted(ctx["runs"] + [eRug + 10 * MIN])), P["RUGGED"])
    dead, dead2 = PK.dead_of(eRug, eRug + 6 * HOUR, ok1), PK.dead_of(eRug, eRug + 6 * HOUR, ok2)
    check(ok1 == eRug and ok2 == eRug + 10 * MIN and dead[2] == "pool dead: rug exit, no healthy scan after the entry"
          and dead2[2] == "pool dead: rug exit, last healthy scan 10 min after the entry",
          "P9 a rug exit's last healthy scan is the latest memeruns doc before it, never before the entry (%s / %s)" % (dead[2], dead2[2]))
    r0 = [[eRug + m * MIN, 1, 1, 1, 1, 100] for m in range(0, 400)]
    check(PK.covers(r0, eRug, 1) and PK.covers(r0[5:], eRug, 1) and not PK.covers(r0[30:], eRug, 1) and not PK.covers([], eRug, 1)
          and PK.covers(r0[20:], eRug, 15) and not PK.covers(r0[45:], eRug, 15),
          "P9 an answer that starts more than 10 min after the entry (30 min for 15-minute candles) is a cut history, not a result")

    now0 = end("PATHUP") + HOUR
    e_up = PK.book(d, ctx, pid["PATHUP"], P["PATHUP"], {"status": "empty"}, end("PATHUP") + 49 * HOUR)
    e_tx = PK.book(d, ctx, pid["TIMEX"], P["TIMEX"], {"status": "empty"}, end("TIMEX") + 49 * HOUR)
    e_lo = PK.book(d, ctx, pid["PATHLOW"], P["PATHLOW"], {"status": "empty"}, end("PATHLOW") + 49 * HOUR)
    check(e_up["state"] == "est" and e_up["src"] == "est" and abs(e_up["x"] - 3.0) < 0.01 and e_up["x6"] == 2.0 and e_up["n"] > 300
          and e_up["eur"] == round(M.pos_value(P["PATHUP"], 1.0, e_up["x"]), 2),
          "P9 an estimate from the tip record's stored minute path of the same coin and run: rebased to the entry, through the filter (%sx, 6 h %sx, %d closes)"
          % (e_up["x"], e_up["x6"], e_up["n"]))
    check(e_tx["state"] == "est" and e_tx["x"] == 1.0 and e_tx["x6"] == 0.8 and e_tx["eur6"] == round(M.pos_value(P["TIMEX"], 1.0, 0.8), 2)
          and e_lo["state"] == "est" and e_lo["x"] == 1.0,
          "P9 an estimate is at least 1.0x (a stored path under the entry gives 1.0x) and takes the value at 6 h from a time exit (%sx / 6 h %sx)" % (e_lo["x"], e_tx["x6"]))
    k = "TIMEX"
    w47 = PK.book(d, ctx, pid[k], P[k], {"status": "empty"}, end(k) + 47 * HOUR)
    e47 = PK.book(d, ctx, pid[k], P[k], {"status": "error"}, end(k) + 47 * HOUR)
    e49 = PK.book(d, ctx, pid[k], P[k], {"status": "error"}, end(k) + 49 * HOUR)
    e49b = PK.book(d, ctx, pid[k], P[k], {"status": "error"}, end(k) + 49 * HOUR, old=dict(e49 or {"v": PK.PEAK_V}, tries=2))
    e100 = PK.book(d, ctx, pid[k], P[k], {"status": "error"}, end(k) + 100 * HOUR)
    unk = [PK.book(d, ctx, pid[k], P[k], i, end(k) + 49 * HOUR) for i in (None, {}, {"status": "deadline"})]
    w47, e49, e49b, e100 = (x or {} for x in (w47, e49, e49b, e100))      # a missing doc fails the checks below, never crashes them
    check(w47.get("state") == "waiting" and w47.get("tries") == 1 and e_tx["state"] == "est" and e_tx["tries"] == 1,
          "P9 an empty answer 47 h after the end waits (tries 1); 49 h after the end it is estimated at once (%s, tries %s)" % (e_tx["state"], e_tx["tries"]))
    check(e47 is None and e49.get("state") == "waiting" and e49.get("tries") == 1 and e49.get("x") is None and e49b.get("state") == "est"
          and e49b.get("tries") == 3 and e100.get("state") == "waiting" and unk == [None, None, None],
          "P9 a failed fetch never settles a window at once: under 48 h no doc, after it a waiting doc with one more try (also 100 h after), the "
          "estimate only at the third (%s, %s/%s, %s/%s)" % (e47, e49.get("state"), e49.get("tries"), e49b.get("state"), e49b.get("tries")))
    np_ = PK.book(d, ctx, pid["NOPOOL"], P["NOPOOL"], {"status": "nopool"}, end("NOPOOL") + 5 * MIN)
    check(np_["state"] == "est" and np_["tries"] == PK.MAX_TRIES and np_["x"] == 1.0, "P9 a position without a pool is estimated at once (tries %s)" % np_["tries"])
    ok_items = lambda now: {it["pid"] for it in PK.items(d, now, ctx)}
    check(pid["NOPOOL"] not in ok_items(end("NOPOOL") + MIN) and pid["NOPOOL"] in ok_items(end("NOPOOL") + 2 * MIN) and len(ok_items(now0 + 10 * HOUR)) == 6,
          "P9 a window counts only 2 minutes after its end (settle wait)")

    now = S0 + 200 * HOUR
    fake = {"since": S0, "docs": {}}
    fpos = {}
    for i in range(15):                                          # closed 10 to 24 min ago
        fpos["r%02d" % i] = {"grp": "young", "t": now - 6 * HOUR - (10 + i) * MIN, "pair": "R%d" % i}
    for i in range(60):                                          # closed 4 h ago and earlier
        fpos["o%02d" % i] = {"grp": "hold", "t": now - 10 * HOUR - i * 17 * MIN, "pair": "O%d" % i}
    fpos["settled"] = {"grp": "young", "t": now - 30 * HOUR, "pair": "S"}
    fpos["tried3"] = {"grp": "young", "t": now - 31 * HOUR, "pair": "T"}
    fpos["prevv"] = {"grp": "young", "t": now - 32 * HOUR, "pair": "V"}
    fpos["pick"] = {"grp": "pick", "t": now - 33 * HOUR, "pair": "K"}
    fpos["before"] = {"grp": "young", "t": S0 - HOUR, "pair": "B"}
    fake["pos"] = fpos
    fake["docs"] = {"settled": {"v": PK.PEAK_V, "state": "est", "tries": 3}, "tried3": {"v": PK.PEAK_V, "state": "waiting", "tries": 3},
                    "prevv": {"v": PK.PEAK_V - 1, "state": "ok", "tries": 0}}
    got = PK.items(None, now, fake)
    ends = lambda xs: [x["end"] for x in xs]
    recent = sorted((k for k in fpos if k.startswith("r")), key=lambda k: fpos[k]["t"])
    rest = sorted([k for k in fpos if k.startswith("o")] + recent[10:] + ["prevv", "before"], key=lambda k: fpos[k]["t"])
    check(len(got) == PK.PEAK_MAX_ITEMS == 60 and [x["pid"] for x in got[:10]] == recent[:10] and [x["pid"] for x in got[10:]] == rest[:50]
          and ends(got[10:]) == sorted(ends(got[10:])) and not {"settled", "tried3", "pick"} & {x["pid"] for x in got} and {"prevv", "before"} <= {x["pid"] for x in got},
          "P9 items: up to 10 windows closed in the last 3 h first, then the backlog oldest first, at most 60; settled docs, 3 tries and pick mode "
          "left out, pre-restart positions and a doc of an older version priced (%d items)" % len(got))


def _p11(check, PK, M):
    print("== peak P11: the low within 6 h (the max loss without the stop-loss)")
    T0 = 1_791_800_000_000
    end = T0 + 6 * HOUR
    pk = lambda c, px=1e-5, **k: PK.peak_of(c, T0, end, px, **k)
    pos = young_pos()
    at_min = lambda r: None if r.get("loAt") is None else (r["loAt"] - T0) // MIN
    stair = [1.0 - 0.05 * i for i in range(15)] + [0.3] * 300
    r = pk(series(T0, stair))
    doc = PK._finish({"v": PK.PEAK_V}, dict(pos, px=1e-5), r, src="m1", tries=0)
    want = round(M.pos_value(pos, 1.0, 0.3), 2)
    check(r["lo"] == 0.3 and at_min(r) == 14 and r["x6"] == 0.3 and doc["lo"] == 0.3 and doc["loAt"] == T0 + 14 * MIN and doc["eurLo"] == want
          and want < 0.9 and doc["eur"] == round(M.pos_value(pos, 1.0, r["x"]), 2),
          "P11 a staircase down: the low is the lowest close (0.3x at minute 14), eurLo %s is 3 EUR at 0.3x after the paper fees (under 0.90)" % doc["eurLo"])
    dust = series(T0, [1.0, 1.1, 1.2, 0.2, 1.2, 1.25] + [1.2] * 300, vol=lambda i: 3.0 if i == 3 else 2000.0)
    real = series(T0, [1.0, 1.1, 1.2, 0.2, 0.2, 1.2, 1.25] + [1.2] * 300)
    rd, rr = pk(dust), pk(real)
    check(rd["lo"] == 1.0 and at_min(rd) == 0 and rr["lo"] == 0.2 and at_min(rr) == 3,
          "P11 a dust spike down ($3 of volume) is no low (%sx at minute %s), the same dip on real volume held for two closes is (%sx at minute %s)" % (
              rd["lo"], at_min(rd), rr["lo"], at_min(rr)))
    r1 = pk(series(T0, [1.0, 1.4, 1.5, 1.5, 0.01, 1.5, 1.6, 1.6, 1.6]))
    sparse = [[T0 + i * 10 * MIN] + [1e-5 * (1 - 0.08 * i)] * 4 + [2000.0] for i in range(10)] + [[T0 + 200 * MIN] + [0.9e-5] * 4 + [2000.0]]
    rs = pk(sparse)
    check(r1["lo"] == 1.0 and not r1["dead"] and abs(rs["lo"] - 0.28) < 1e-9 and at_min(rs) == 90 and rs["x6"] == 0.9,
          "P11 one print at 0.01x that the next close took back is no low (%sx); in a pool that trades every 10 minutes each close stands (low %sx at minute %s, "
          "6 h %sx)" % (r1["lo"], rs["lo"], at_min(rs), rs["x6"]))
    rc = pk(series(T0, [1.0, 1.2, 1.5, 1.9, 1.9, 1.8]) + series(T0, [1e-7, 1e-7], start=6))
    rg = pk(series(T0, [1.0] * 39 + [0.8, 0.9] + [20] * 4), rug_ok_at=T0 + 40 * MIN)
    rq = pk(series(T0, [1.0, 0.9] + [0.8] * 300), liq0=20_000.0, ds_points=[(T0 + 90 * MIN, None, 300.0)])
    slow = pk(series(T0, [1.0 - 0.0025 * i for i in range(361)]))
    dg = PK._finish({"v": PK.PEAK_V}, dict(pos, px=1e-5), rc, src="m1", tries=0)
    check(rc["lo"] == 0.0 and at_min(rc) == 6 and rg["lo"] == 0.0 and at_min(rg) == 40 and rq["lo"] == 0.0 and at_min(rq) == 90 and dg["eurLo"] == 0.0
          and abs(slow["lo"] - slow["x6"]) < 1e-9 and 0.1 < slow["lo"] < 0.11 and not slow["dead"],
          "P11 a pool that really died is a real loss, never filtered away: lo 0 at the collapse (minute %s), at the rug exit's last healthy scan (minute %s) "
          "and at the liquidity floor (minute %s), eurLo 0; a slow fall in a live pool is its lowest close (%sx), not 0" % (at_min(rc), at_min(rg), at_min(rq), slow["lo"]))
    fx = json.load(open(os.path.join(FIX, "named.json"), encoding="utf-8"))
    named = {c["name"]: PK.peak_of(expand(c), c["entryAt"], c["entryAt"] + 6 * HOUR, c["px"], c.get("rugOkAt"), [q[:3] for q in c["ds"]],
                                   liq0=c["liq0"], mc0=c["mc0"]) for c in fx["cases"]}
    p1 = [pk(series(T0, m)) for m in ([1.0, 1.1, 1.2, 8.0, 1.1, 1.15, 1.2] + [1.1] * 300, [1.0] * 360 + [9.0] * 3, [1.0, 1.1, 1.2, 1.3, 500, 480, 1.2, 1.2])]
    allr = list(named.values()) + p1 + [r, rd, rr, r1, rs, rc, rg, rq, slow]
    bad = [(k, v["lo"], v["x6"]) for k, v in list(named.items()) + [("case", v) for v in allr]
           if v["state"] == "ok" and not (v["lo"] is not None and 0 <= v["lo"] <= 1.0 and (v["x6"] is None or v["lo"] <= v["x6"] + 1e-12))]
    dead_named = [k for k, v in named.items() if v["dead"]]
    check(not bad and dead_named and all(named[k]["lo"] == 0.0 for k in dead_named) and named["HIRE"]["lo"] <= 1.0,
          "P11 lo is between 0 and the entry and never above the value at 6 h in every case and named fixture; the named dead pools (%s) are a low of 0 (%s)" % (
              ", ".join(dead_named), bad[:3] or "all fine"))
    ru = pk(series(T0, [5.0, 5.1, 5.2, 5.0] * 20), px=5e-5, ds_points=[(T0 + 10 * MIN, 0.2 * 1e-5, 50_000.0)])
    du = PK._finish({"v": PK.PEAK_V}, dict(pos, px=5e-5), ru, src="m1", tries=0)
    rw = pk([])
    check(ru["state"] == "unit" and ru["lo"] is None and du["lo"] is None and du["eurLo"] is None and du["loAt"] is None and rw["lo"] is None and rw["loAt"] is None,
          "P11 candles in another unit than DexScreener's price book no low either (unit), and no candle means no low (waiting)")
    # the estimate's low: the paper exits and DexScreener's prices inside the window are prices the pool really had
    pe = dict(pos, px=1e-5, t=T0, entryAt=T0, _exits=[{"why": "stop", "px": 0.68e-5, "at": T0 + 40 * MIN, "t": T0 + 50 * MIN}])
    est = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pe, None, [], 3)
    est_ds = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pe, None, [(T0 + 20 * MIN, 0.5e-5, 20_000.0), (end + 30 * MIN, 0.1e-5, 20_000.0)], 3)
    pl = dict(pe, _exits=[{"why": "stop", "px": 0.1e-5, "at": end + 20 * MIN}])
    est_late = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pl, None, [], 3)
    est_rug = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pe, T0 + 30 * MIN, [], 3)
    check(est["lo"] == 0.68 and est["loAt"] == T0 + 40 * MIN and est["eurLo"] == round(M.pos_value(pe, 1.0, 0.68), 2) and est_ds["lo"] == 0.5
          and est_ds["loAt"] == T0 + 20 * MIN and est_late["lo"] == 1.0 and est_rug["lo"] == 0.0 and est_rug["eurLo"] == 0.0,
          "P11 an estimate's low is an upper bound from real prices inside the window: the stop's price (0.68x at its candle), a DexScreener point (0.5x); "
          "a price after the window does not count (1.0x); a rug is 0 (%s / %s / %s / %s)" % (est["lo"], est_ds["lo"], est_late["lo"], est_rug["lo"]))
    # PEAK_V 2 prices every older doc again, but never worse: a lost minute history keeps the old best and adds this run's low
    old = {"v": PK.PEAK_V - 1, "state": "ok", "src": "m1", "res": 1, "tries": 0, "pos": "q", "entryAt": T0, "end": end, "px": 2e-5, "cpx": 2e-5,
           "base": 2e-5, "x": 4.7608, "at": T0 + 4 * HOUR, "rawX": 4.87, "x6": 2.9692, "eur": 90.55, "eur6": 56.17, "dead": None, "cut": [], "n": 360}
    pq = dict(pos, px=2e-5, ticket=20.0, t=T0, entryAt=T0)
    new_est = {"v": PK.PEAK_V, "state": "est", "src": "est", "pos": "q", "upd": end + 99 * HOUR, "base": 1e-5, "x": 1.0, "lo": 0.6, "loAt": T0 + HOUR, "entryAt": T0, "end": end}
    kept = PK.keep_better(dict(new_est), old, pq, end + 99 * HOUR)
    new_m1 = dict(new_est, src="m1", state="ok")
    old_dead = dict(old, x6=0.0, dead={"at": T0 + 5 * HOUR, "why": "collapse"})
    kd = PK.keep_better(dict(new_est), old_dead, pq, end + 99 * HOUR)
    check(kept and kept["v"] == PK.PEAK_V and kept["src"] == "m1" and kept["x"] == 4.7608 and kept["eur"] == 90.55 and kept["x6"] == 2.9692
          and kept["lo"] == 0.3 and kept["loAt"] == T0 + HOUR and kept["eurLo"] == round(M.pos_value(pq, 1.0, 0.3), 2) and list(kept) == list(PK.DOC_KEYS)
          and PK.keep_better(dict(new_est, state="waiting", src=None), old, pq, end) is None and PK.keep_better(new_m1, old, pq, end) is new_m1
          and PK.keep_better(dict(new_est), dict(old, v=PK.PEAK_V), pq, end)["x"] == 1.0 and kd["lo"] == 0.0 and kd["loAt"] == T0 + 5 * HOUR,
          "P11 an older version's doc from minute candles is never made worse: an estimate keeps its best %sx and adds the low rebased onto its base "
          "(0.6x of half the price -> %sx), a waiting answer leaves it for a later run, new minute candles replace it, its dead pool stays a low of 0" % (
              kept and kept["x"], kept and kept["lo"]))


def _p12(check, PK, M):
    print("== peak P12: the best within 6 h is never below the value at 6 h")
    T0 = 1_791_800_000_000
    end = T0 + 6 * HOUR
    pk = lambda c, px=1e-5, **k: PK.peak_of(c, T0, end, px, **k)
    pos = young_pos()
    at_min = lambda r: None if r.get("at") is None else (r["at"] - T0) // MIN
    rise = pk(series(T0, [1.0] * 359 + [1.06]))                       # TDF on results: 1.000 best, 1.062 at 6 h
    ramp = pk(series(T0, [1.0] * 300 + [1.0 + 0.01 * i for i in range(1, 60)]))
    spike = pk(series(T0, [1.0] * 359 + [50.0], vol=30), mc0=50_000)
    check(rise["x"] == rise["x6"] == 1.06 and at_min(rise) == 359 and ramp["x"] == ramp["x6"] == 1.59 and at_min(ramp) == 358
          and spike["x"] == 1.0 and spike["x6"] == 50.0 and any(c.startswith("unconfirmed") for c in spike["cut"]),
          "P12 a price that rises into the end: the best is the last close (%sx at minute %s; a ramp %sx at minute %s), a one-candle 50x print at the "
          "very end without support stays cut (best %sx)" % (rise["x"], at_min(rise), ramp["x"], at_min(ramp), spike["x"]))
    pe = dict(pos, px=1e-5, t=T0, entryAt=T0, _exits=[{"why": "time", "px": 1.26e-5, "at": end, "t": end + 5 * MIN}])
    est = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pe, None, [], 3)          # Harry on estimate-filled data: +26% at 6 h, best 1.0x before
    est_dead = PK.estimate({"v": PK.PEAK_V}, {"tips": {}}, pe, T0 + 30 * MIN, [], 3)
    check(est["x"] == est["x6"] == 1.26 and est["at"] == end and est["eur"] == round(M.pos_value(pe, 1.0, 1.26), 2) == est["eur6"] and est["eur"] > 0
          and est_dead["x"] == 1.0 and est_dead["x6"] == 0.0,
          "P12 an estimate from a time exit at 1.26x books a best of at least 1.26x (eur %s = eur6 %s); a rug before it keeps the best at the entry (%sx)" % (
              est["eur"], est["eur6"], est_dead["x"]))
    old = {"v": PK.PEAK_V - 1, "state": "ok", "src": "m1", "res": 1, "tries": 0, "pos": "w", "entryAt": T0, "end": end, "px": 1e-5, "cpx": 1e-5,
           "base": 1e-5, "x": 1.021, "at": T0 + 2 * HOUR, "rawX": 1.08, "x6": 1.071, "eur": 2.9, "eur6": 3.0, "dead": None, "cut": [], "n": 360}
    pw = dict(pos, px=1e-5, t=T0, entryAt=T0)
    new_est = {"v": PK.PEAK_V, "state": "est", "src": "est", "pos": "w", "upd": end + 99 * HOUR, "base": 1e-5, "x": 1.0, "lo": 0.9, "loAt": T0 + HOUR, "entryAt": T0, "end": end}
    kept = PK.keep_better(dict(new_est), old, pw, end + 99 * HOUR)
    kept_hi = PK.keep_better(dict(new_est), dict(old, x=1.5), pw, end + 99 * HOUR)
    check(kept["x"] == 1.071 and kept["at"] == end and kept["eur"] == round(M.pos_value(pw, 1.0, 1.071), 2) and kept["x6"] == 1.071
          and kept_hi["x"] == 1.5 and kept_hi["at"] == T0 + 2 * HOUR and kept_hi["eur"] == 2.9,
          "P12 an older version's doc whose best (1.021x, WOTF on results) is below its value at 6 h (1.071x) keeps at least that value (%sx), "
          "a best above it stays as it was" % kept["x"])
    fx = json.load(open(os.path.join(FIX, "named.json"), encoding="utf-8"))
    named = {c["name"]: PK.peak_of(expand(c), c["entryAt"], c["entryAt"] + 6 * HOUR, c["px"], c.get("rugOkAt"), [q[:3] for q in c["ds"]],
                                   liq0=c["liq0"], mc0=c["mc0"]) for c in fx["cases"]}
    cases = [pk(series(T0, m)) for m in ([1.0, 1.1, 1.2, 8.0, 1.1, 1.15, 1.2] + [1.1] * 300, [1.0] * 360 + [9.0] * 3, [1.0 - 0.0025 * i for i in range(361)],
                                         [1.0, 1.4, 1.5, 1.5, 0.01, 1.5, 1.6, 1.6, 1.6], [38 ** (i / 120) for i in range(121)] + [38 - i * 0.05 for i in range(200)])]
    bad = [(k, v["x"], v["x6"]) for k, v in list(named.items()) + [("case%d" % i, v) for i, v in enumerate(cases + [rise, ramp])]
           if v["state"] == "ok" and v["x6"] is not None and v["x"] < v["x6"] - 1e-12]
    check(not bad, "P12 x >= x6 in every live case and named fixture (%d checked; %s)" % (len(named) + len(cases) + 2, bad[:3] or "all fine"))


class _GT:
    """A stand-in GeckoTerminal for P10. mode: "ok" (flat minute candles at the pool's price), "503", "html" (a block page), "shape"
    (JSON without ohlcv_list), "429", "hang" (answers after 3 s), "trickle" (the answer a byte every 0.2 s, cut off after 8 s). Every request is noted
    with the number of memepeak docs on disk at that moment (watch: the run's db folder). "alt": 404 and 503 by turns. Candle rows it
    cannot read: "dicts" (rows as objects), "ms" (timestamps in ms), "iso" (timestamps as ISO text), "small" (candle numbers 0, 1, 2 for timestamps), "future" (seconds, but a day
    past the before_timestamp asked), "nullclose" (seconds, but every close null), "textclose" (seconds, but every value text
    such as "1e-05 USD"); "strnum": every value a numeric string (readable); "zero": readable rows whose
    closes are all 0. "odd1": the pool odd_pool answers without ohlcv_list, every other pool as "ok"; "okshape": the first request
    as "ok", every later one without ohlcv_list."""

    def __init__(self, px_of):
        self.mode, self.px_of, self.calls, self.watch, self.odd_pool = "ok", px_of, [], None, None
        gt = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                m = re.search(r"/pools/([^/]+)/ohlcv/minute\?(.*)$", self.path)
                docs = len(glob.glob(os.path.join(gt.watch, "db", "memepeak", "*.json"))) if gt.watch else 0
                gt.calls.append((m.group(1) if m else self.path, docs))
                mode = gt.mode
                if mode == "alt":                     # 503 and 404 by turns: a flaky host that still answers
                    mode = "503" if len(gt.calls) % 2 else "404"
                if mode == "odd1":                    # one pool answers oddly, the others normally
                    mode = "shape" if m and m.group(1) == gt.odd_pool else "ok"
                if mode == "okshape":                 # a readable first answer, then the shape changes
                    mode = "ok" if len(gt.calls) == 1 else "shape"
                try:
                    if mode == "404":
                        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
                        return
                    if mode == "503" or mode == "429":
                        self.send_response(int(mode)); self.send_header("Content-Length", "0"); self.end_headers()
                        return
                    if mode == "hang":
                        threading.Event().wait(3.0)       # not time.sleep: the main selftest turns that off in its process
                    if mode == "html":
                        self._send(b"<html><body>Just a moment...</body></html>", "text/html")
                        return
                    if mode == "shape":
                        self._send(json.dumps({"data": {"attributes": {"candles": []}}}).encode(), "application/json")
                        return
                    q = urllib.parse.parse_qs(m.group(2))
                    agg, lim, before = int(q["aggregate"][0]), int(q["limit"][0]), int(q["before_timestamp"][0])
                    px = gt.px_of.get(m.group(1), 1e-5)
                    top = before // (60 * agg) * (60 * agg)
                    lst = [[top - (i + 1) * 60 * agg, px, px, px, px, 1000.0] for i in range(lim)]
                    if mode == "dicts":
                        lst = [dict(zip(("t", "o", "h", "l", "c", "v"), r)) for r in lst]
                    elif mode == "ms":
                        lst = [[r[0] * 1000] + r[1:] for r in lst]
                    elif mode == "iso":
                        lst = [[time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r[0]))] + r[1:] for r in lst]
                    elif mode == "small":
                        lst = [[i] + r[1:] for i, r in enumerate(lst)]
                    elif mode == "future":
                        lst = [[r[0] + 86400] + r[1:] for r in lst]
                    elif mode == "nullclose":
                        lst = [r[:4] + [None] + r[5:] for r in lst]
                    elif mode == "textclose":
                        lst = [[r[0]] + ["%g USD" % v for v in r[1:]] for r in lst]
                    elif mode == "strnum":
                        lst = [[str(r[0])] + [repr(v) for v in r[1:]] for r in lst]
                    elif mode == "zero":
                        lst = [[r[0], 0, 0, 0, 0, 1000.0] for r in lst]
                    raw = json.dumps({"data": {"attributes": {"ohlcv_list": lst}}}).encode()
                    if mode == "trickle":
                        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        t_end = time.time() + 8.0          # then it hangs up: a client that waits for the whole answer fails late, never hangs
                        for b in raw:
                            if time.time() > t_end:
                                break
                            self.wfile.write(bytes([b])); self.wfile.flush()
                            threading.Event().wait(0.2)
                        return
                    self._send(raw, "application/json")
                except OSError:
                    pass

            def _send(self, raw, ctype):
                self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(raw)))
                self.end_headers(); self.wfile.write(raw)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _p10(check, PK, M, S, tmp):
    print("== peak P10: GeckoTerminal failing (5xx, timeouts, 429s, a block page, a changed shape, a slow answer)")
    rec = os.path.join(tmp, "rec")
    if not os.path.isdir(os.path.join(rec, "db", "memepos")):
        check(False, "P10 needs the recommend-mode db of P3")
        return
    pos = M.positions(rec)
    gt = _GT({p.get("pair"): M.num(p.get("px")) for p in pos.values()})
    ends = [PK.window(p)[1] for p in pos.values()]
    new, old = max(ends) + 3 * HOUR, max(ends) + 54 * HOUR     # every window under 48 h past its end, or every one over it
    saved = (PK.GT_429_LADDER_S, PK.SETTLE_EVERY, PK.F.TIMEOUT)
    runs = {}

    def go(name, mode, now, deadline=60.0, d=None):
        if d is None:
            d = os.path.join(tmp, "p10-" + name)
            shutil.copytree(rec, d)
        gt.mode, gt.calls, gt.watch = mode, [], d
        lines = []
        t = time.time()
        out = PK.run(d, now, deadline, mock=gt.url, log=lines.append)
        docs = M.load_docs(d, "memepeak")
        runs[name] = (out, list(gt.calls), docs, lines, time.time() - t, d)
        return runs[name]
    try:
        PK.GT_429_LADDER_S, PK.F.TIMEOUT = (0.05, 0.05, 0.05), 1.0
        go("503new", "503", new)
        go("503old", "503", old)
        go("alt", "alt", new)
        go("recover", "ok", old, d=runs["503old"][5])
        go("hang", "hang", old)
        go("429", "429", old)
        go("429new", "429", new)
        go("html", "html", old)
        go("shape", "shape", old)
        for name in ("dicts", "ms", "iso", "small", "future", "nullclose", "textclose"):
            go(name, name, old)
        go("zero", "zero", new)
        go("strnum", "strnum", old)
        its = PK.items(rec, old)
        n_of = {}
        for it in its:
            n_of[it["pool"]] = n_of.get(it["pool"], 0) + 1
        gt.odd_pool = [it["pool"] for it in its if n_of[it["pool"]] == 1 and it["pool"] != its[0]["pool"]][-1]
        go("odd1", "odd1", old)
        go("okshape", "okshape", old)
        go("trickle", "trickle", new, deadline=3.0)
        PK.SETTLE_EVERY = 2
        go("steps", "ok", new)
    finally:
        PK.GT_429_LADDER_S, PK.SETTLE_EVERY, PK.F.TIMEOUT = saved
        gt.close()
    n = len(PK.items(rec, old))
    st = lambda docs: sorted((x["state"], x["tries"], x["src"]) for x in docs.values())
    o, c, docs, lines, secs, _ = runs["503new"]
    check(o["why"] == PK.GT_GONE and len(c) == 3 and not docs and sum(1 for l in lines if "giving up on" in l) == 1,
          "P10 503 on every request, windows under 48 h: GeckoTerminal off after 3 requests, no doc written (%s, %d requests)" % (o["why"], len(c)))
    o, c, docs, lines, secs, _ = runs["alt"]
    check(o["why"] == "all asked" and len(c) >= 2 * n - 1 and not any("giving up on" in l for l in lines) and not docs,
          "P10 503 and 404 by turns: a 404 is an answer, so the 5xx never come three in a row and every window is asked (%s, %d requests)" % (o["why"], len(c)))
    o, c, docs, lines, secs, _ = runs["503old"]
    check(o["why"] == PK.GT_GONE and len(c) == 3 and st(docs) == [("waiting", 1, None)] * 3 and all(x["x"] is None for x in docs.values()),
          "P10 503 on windows over 48 h past their end: the 3 asked ones wait with tries 1, none is estimated, the rest is untouched (%s)" % st(docs))
    o, c, docs, lines, secs, _ = runs["recover"]
    check(o["why"] == "all asked" and len(docs) == n and all(x["state"] == "ok" and x["src"] == "m1" and x["x"] == 1.0 for x in docs.values()),
          "P10 the next healthy run prices every window from minute candles, the 3 that waited included (%s)" % st(docs))
    o, c, docs, lines, secs, _ = runs["hang"]
    check(o["why"] == PK.GT_GONE and len(c) == 3 and st(docs) == [("waiting", 1, None)] * 3 and secs < 10,
          "P10 timeouts: off after 3, the asked old windows wait with tries 1 (%.1f s)" % secs)
    o, c, docs, lines, secs, _ = runs["429"]
    o2, c2, docs2, _, _, _ = runs["429new"]
    check(o["why"] == "GeckoTerminal rate limit" and len(c) == 8 and len({x[0] for x in c[:4]}) == 1 and st(docs) == [("waiting", 1, None)]
          and sum(1 for l in lines if "waiting 0s" in l) == 6 and o2["why"] == "GeckoTerminal rate limit" and not docs2,
          "P10 429s: the same window asked 4 times (the 15, 30, 60 s ladder), then it waits for a later run (tries 1 when old, no doc when new); "
          "8 in the run and GeckoTerminal is given up (%d requests)" % len(c))
    for name, said in (("html", "not JSON"), ("shape", "ohlcv_list")):
        o, c, docs, lines, secs, _ = runs[name]
        check(o["why"] == PK.GT_SHAPE and len(c) == 1 and not docs and sum(1 for l in lines if said in l and "off for the rest of this run" in l) == 1,
              "P10 %s: one request, GeckoTerminal off for the run, logged once, no doc (not even for the old window asked) (%s)"
              % ("a block page (HTML)" if name == "html" else "an answer in another shape", o["why"]))
    for name, what in (("dicts", "rows as objects"), ("ms", "timestamps in ms"), ("iso", "timestamps as ISO text"), ("small", "candle numbers for timestamps"),
                       ("future", "a day newer than the before_timestamp asked"), ("nullclose", "closes null"),
                       ("textclose", "values as text such as 1e-05 USD")):
        o, c, docs, lines, secs, _ = runs[name]
        check(o["why"] == PK.GT_SHAPE and len(c) == 1 and not docs and sum(1 for l in lines if "off for the rest of this run" in l) == 1,
              "P10 candle rows it cannot read (%s): a changed shape, not an empty answer: one request, GeckoTerminal off, no doc, "
              "the old windows not estimated (%s, %d requests, %d docs)" % (what, o["why"], len(c), len(docs)))
    o, c, docs, lines, secs, _ = runs["zero"]
    asked = len({(it["pool"], it["key"]) for it in PK.items(rec, new)})
    check(o["why"] == "all asked" and len(c) == 2 * asked and not any("off for the rest" in l for l in lines)
          and st(docs) == [("waiting", 1, None)] * len(PK.items(rec, new)),
          "P10 readable rows whose closes are all 0: an empty answer, not a changed shape (a close of 0 is a number; its value never decides): every "
          "window asked as minute and 15-minute candles, waiting with tries 1 (%s, %d requests)" % (o["why"], len(c)))
    o, c, docs, lines, secs, _ = runs["strnum"]
    check(o["why"] == "all asked" and len(docs) == n and all(x["state"] == "ok" and x["src"] == "m1" and x["x"] == 1.0 for x in docs.values())
          and not any("GeckoTerminal answered" in l for l in lines),
          "P10 every value a numeric string (\"1e-05\"): readable rows, every window priced from minute candles (%s)" % st(docs))
    o, c, docs, lines, secs, _ = runs["odd1"]
    odd = [pid for pid, x in docs.items() if x["state"] == "waiting"]
    check(o["why"] == "all asked" and len(docs) == n and len(odd) == 1 and docs[odd[0]]["pair"] == gt.odd_pool and docs[odd[0]]["tries"] == 1
          and all(x["state"] == "ok" and x["src"] == "m1" for pid, x in docs.items() if pid not in odd)
          and sum(1 for l in lines if "answered one pool" in l) == 1 and not any("off for the rest" in l for l in lines),
          "P10 one pool answers in another shape after a readable first answer: only that window fails (old: waiting, tries 1), "
          "GeckoTerminal stays on and the windows behind it are priced (%s)" % st(docs))
    o, c, docs, lines, secs, _ = runs["okshape"]
    check(o["why"] == PK.GT_SHAPE and len(c) == 4 and sorted(x["state"] for x in docs.values()) == ["ok", "waiting", "waiting"]
          and sum(1 for l in lines if "off for the rest of this run" in l) == 1,
          "P10 the shape changes after a readable first answer: the third odd answer in a row switches GeckoTerminal off "
          "(%s, %d requests, %s)" % (o["why"], len(c), st(docs)))
    o, c, docs, lines, secs, _ = runs["trickle"]
    check(o["why"] == "deadline" and len(c) == 1 and not docs and secs <= 4.5,
          "P10 an answer sent a byte at a time is cut off at the deadline: --deadline-s 3 ended after %.1f s" % secs)
    o, c, docs, lines, secs, _ = runs["steps"]
    check(o["why"] == "all asked" and [x[1] for x in c] == [0, 0, 2, 2, 4, 4][:n] and len(docs) == n and o["ok"] == n,
          "P10 the docs are written as the run goes (every SETTLE_EVERY windows, here 2): docs on disk at each request %s" % [x[1] for x in c])


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
