#!/usr/bin/env python3
"""selftest_seeker.py: the Rocket seeker (seeker.py, seeker_watch.py, page_seeker.py, seeker.yml) on made-up data (fake money only).

  python3 selftest_seeker.py

Checks: S1 the plain-JSON trees give LightGBM's own probabilities (research/seeker/results/parity.json, made by seeker_train.py from
seeker_model.json; some rows with inputs missing); S2 seeker.chart gives seeker_train.chart_feats's numbers on real five-minute bars;
S3 one-minute candles sum to the training's five-minute clock bars, only bars closed by graduation + 30 minutes; S4 the launch facts
from a radar record (curve minutes, creator, X link and post age, theme heat over 24 hours, CJK; no mint time: both missing); S5 the
paper account: one buy per coin, Rocket hold on closes (half, 40 % under the best after 2x, 24 h), fees; S6 a tick on mocked answers:
only PumpSwap graduations 30-45 minutes old, the liquidity line, a retry without a price, a buy at the cut, a sale later, the missed
count, the state and the log, no numpy, no network; S7 the page: the fold under Tests on the side (escaped, no script) and the Start
box with its lane and feed; S8 the workflow writes only its own branch, runs the bot without the token, in its own group, and the
scan job only reads seeker.json; S9 the glitch guard: NEX Ai's two GeckoTerminal glitch closes (27 Oct) sell nothing, a real crash
(confirmed by the next closes or by DexScreener) and a real rocket still sell, the sales booked before the guard on a glitch are open
again and a tick judges them on their candles since the buy.
"""
import json, math, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import seeker as S
import seeker_watch as SW

FAILS = []
MIN, H = 60_000, 3_600_000
nan = float("nan")
T0 = 1_793_000_000_000 // 300_000 * 300_000 + 200_000          # a graduation at 3:20 into a five-minute bar


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def same(a, b, tol=1e-9):
    if a is None or b is None or a != a or b != b:
        return (a is None or a != a) and (b is None or b != b)
    return abs(a - b) <= tol * max(1.0, abs(b))


def s1(check):
    m = json.load(open(SW.MODEL))
    p = json.load(open(os.path.join(HERE, "research", "seeker", "results", "parity.json")))
    diff = max(abs(S.score(m, {k: (nan if v is None else v) for k, v in zip(p["features"], r)}) - s) for r, s in zip(p["rows"], p["scores"]))
    nmiss = sum(1 for r in p["rows"] if any(v is None for v in r))
    check(diff < 1e-9 and nmiss >= 20 and p["features"] == m["features"], "S1 trees = LightGBM on %d rows (%d with missing inputs), max diff %.1e" % (len(p["rows"]), nmiss, diff))
    check(0 < m["cut"] < 1 and len(m["trees"]) == 400 and m.get("top") == 0.02, "S1 the model: 400 trees, cut %.4f at the top 2 %%" % m["cut"])


def s2(check):
    p = json.load(open(os.path.join(HERE, "research", "seeker", "results", "parity.json")))
    bad = []
    for b in p["bars"]:
        f = S.chart({k: [nan if x is None else x for x in v] for k, v in b["bars"].items()})
        bad += [k for k, v in b["chart"].items() if not same(f[k], v, 1e-6)]
    check(not bad and len(p["bars"]) == 20, "S2 seeker.chart = seeker_train.chart_feats on 20 real bar rows%s" % (": " + ",".join(bad) if bad else ""))


def s3(check):
    t0 = T0 // 300_000 * 300_000
    cs = [[T0 - 5 * MIN, 1, 1, 1, 1, 5],                         # before the graduation's five-minute bar: left out
          [t0 + 4 * MIN, 1.0, 1.2, 0.9, 1.1, 10], [t0 + 3 * MIN + 0, 1.0, 1.0, 1.0, 1.0, 5],  # bar 0: two minutes, the later close wins
          [t0 + 11 * MIN, 1.1, 1.5, 1.0, 1.4, 7],                # bar 2 (bar 1 without a trade: forward-filled)
          [t0 + 29 * MIN, 2.0, 2.2, 1.9, 2.1, 3],                # bar 5: the last closed by T0 + 30 min (t0 + 33:20)
          [t0 + 31 * MIN, 9.0, 9.0, 9.0, 9.0, 99]]               # bar 6 closes after the entry: left out
    b = S.bars(cs, T0, T0 + 30 * MIN)
    ok = (len(b["cl"]) == 6 and b["cl"][0] == 1.1 and b["hi"][0] == 1.2 and b["v"][0] == 15 and b["cl"][1] == 1.1 and b["has"][1] == 0
          and b["hi"][1] != b["hi"][1] and b["cl"][2] == 1.4 and b["cl"][5] == 2.1 and b["has"] == [1, 0, 1, 0, 0, 1] and 99 not in b["v"])
    check(ok, "S3 minutes -> five-minute clock bars up to graduation + 30 min: %s" % b["cl"])
    f = S.chart(b)
    check(same(f["c_ret"], math.log(2.1 / 1.1)) and same(f["c_peak"], 2.2 / 2.1) and same(f["c_r15"], math.log(2.1 / 1.4)) and same(f["c_act"], 0.5)
          and same(f["c_mc"], math.log10(2.1e9)) and same(f["c_vol"], math.log10(1 + 15 + 7 + 3)), "S3 the chart numbers of those bars")


def snow(ms):
    return str((int(ms) - 1288834974657) << 22)


def rec(a, sym, name, pool, mint=None, grad=0, x="", dex="pumpswap"):
    return {"addr": a, "sym": sym, "name": name, "pool": pool, "mint": mint, "pair": "P" + a, "dex": dex,
            "sig0": {"devGrad": grad, "x": x}, "sig": {"devGrad": None if grad is None else grad + 1, "x": x}}


def s4(check):
    recs = [rec("A", "PEPE", "Pepe Rocket", T0, T0 - 5 * MIN, 2, "https://x.com/someone/status/" + snow(T0 - 30 * MIN)),
            rec("B", "ROCKETDOG", "rocket dog", T0 - 3 * H), rec("C", "MOON", "rocket moon", T0 - 23 * H), rec("D", "ROCKET", "x", T0 - 25 * H),
            rec("E", "PEPE", "frog", T0 + 2 * MIN), rec("F", "the", "coin token", T0 - H)]
    th = S.Theme(recs)
    f = S.facts(recs[0], th)
    # "rocket": B (3 h), C (23 h) share it, D is older than 24 h, E later; "pepe": none before; the stop words and short words never count
    check(f["f_curve_min"] == 5.0 and f["f_creator_prior"] == 2.0 and f["f_xtype"] == 1.0 and f["f_post_age"] == 1.0 and f["f_theme24"] == 2.0
          and f["f_cjk"] == 0.0, "S4 the launch facts of a record: %s" % f)
    g = S.facts(rec("G", "猫", "", T0, None, None, "https://x.com/someacct"), th)
    check(g["f_curve_min"] != g["f_curve_min"] and g["f_post_age"] != g["f_post_age"] and g["f_creator_prior"] != g["f_creator_prior"]
          and g["f_xtype"] == 2.0 and g["f_cjk"] == 1.0 and g["f_theme24"] == 0.0, "S4 without a mint time: curve and post age missing; a profile link, a CJK name")
    h = S.facts(rec("H", "OLD", "old post", T0, T0 - 1 * MIN, 0, "https://twitter.com/a/status/" + snow(T0 - 3 * 86_400_000)), th)
    check(h["f_post_age"] == 3.0 and h["f_xtype"] == 1.0 and S.words("The Rocket-dog 2026 coin") == {"rocket"}, "S4 an old post, the word rules")


def s5(check):
    b = S.Book()
    p = b.buy("A", "A", "PA", 1.0, T0, 0.2, 0.1)
    check(p is not None and b.buy("A", "A", "PA", 1.0, T0 + MIN, 0.2, 0.1) is None, "S5 one buy per coin")
    out = b.update("A", T0 + 10 * MIN, [(T0 - MIN, 0.1), (T0 + MIN, 1.5), (T0 + 2 * MIN, 0.6), (T0 + 3 * MIN, 0.5), (T0 + 4 * MIN, 3.0)])
    check(out and out["why"] == "floor" and out["mult"] == 0.5 and out["out"] == T0 + 4 * MIN and out["eur"] == S.M.tip_net(0.5),
          "S5 a close at half sells at that close (the minute before the buy does not count): %s" % (out and out["why"]))
    b.buy("B", "B", "PB", 2.0, T0, 0.2, 0.1)
    o1 = b.update("B", T0 + 5 * MIN, [(T0 + MIN, 3.0), (T0 + 2 * MIN, 5.0), (T0 + 3 * MIN, 3.1)])
    o2 = b.update("B", T0 + 6 * MIN, [(T0 + 3 * MIN, 0.1), (T0 + 4 * MIN, 2.9)])        # minute 3 already judged: not again
    check(o1 is None and o2 and o2["why"] == "trail" and same(o2["mult"], 1.45) and b.open == {}, "S5 after 2x: 40 % under the best close (2.9 <= 0.6 x 5.0)")
    b.buy("C", "C", "PC", 1.0, T0, 0.2, 0.1)
    o3 = b.update("C", T0 + 5 * MIN, [(T0 + MIN, 1.8)], px=1.7)
    o4 = b.update("C", T0 + 24 * H + 5 * MIN, [], px=1.6)
    check(o3 is None and b.closed[-1:] and o4 and o4["why"] == "24h" and same(o4["mult"], 1.8), "S5 24 hours: sold at the last close")
    b.buy("D", "D", "PD", 1.0, T0, 0.2, 0.1)
    o5 = b.update("D", T0 + 24 * H + 2 * MIN, [(T0 + 24 * H - MIN, 1.3), (T0 + 24 * H, 9.0)])
    sm = b.summary()
    check(o5 and o5["why"] == "24h" and o5["mult"] == 1.3 and sm["trades"] == 4 and sm["open"] == 0 and sm["x2"] == 1 and sm["x3"] == 0 and sm["x10"] == 0,
          "S5 the minute that ends the 24 hours sells; summary %s" % sm)


def gt(rows):
    return {"data": {"attributes": {"ohlcv_list": [[int(t // 1000), o, h, l, c, v] for t, o, h, l, c, v in rows]}}}


def s6(check, tmp):
    rd, sk, mk = (os.path.join(tmp, x) for x in ("rd", "sk", "mk"))
    for x in (os.path.join(rd, "db", "memeradar"), sk, mk):
        os.makedirs(x, exist_ok=True)
    now = T0 + 33 * MIN
    coins = {"AAA": rec("AAA", "ROCKY", "Rocky", T0, T0 - 4 * MIN, 1, "https://x.com/a/status/" + snow(T0 - 10 * MIN)),
             "BBB": rec("BBB", "YOUNG", "too young", now - 10 * MIN),
             "CCC": rec("CCC", "MET", "meteora pool", T0, dex="meteora"),
             "DDD": rec("DDD", "THIN", "thin pool", T0 + MIN),
             "EEE": rec("EEE", "NOPX", "no price yet", T0 - 2 * MIN),
             "FFF": rec("FFF", "LATE", "seen late", now - 50 * MIN)}
    json.dump({"coins": coins}, open(os.path.join(rd, "db", "memeradar", "2026-10-26T10.json"), "w"))
    t0 = T0 // 300_000 * 300_000
    rows = [(t0 + k * MIN, 1e-4, 1.1e-4, 0.9e-4, 1e-4 * (1 + 0.02 * k), 500.0) for k in range(3, 33)]
    json.dump(gt(rows), open(os.path.join(mk, "gt_PAAA_ohlcv.json"), "w"))
    json.dump(gt(rows), open(os.path.join(mk, "gt_PDDD_ohlcv.json"), "w"))
    ds = [{"baseToken": {"address": "AAA"}, "pairAddress": "PAAA", "priceUsd": "0.000166", "liquidity": {"usd": 25000}},
          {"baseToken": {"address": "DDD"}, "pairAddress": "PDDD", "priceUsd": "0.000166", "liquidity": {"usd": 4000}}]
    json.dump(ds, open(os.path.join(mk, "ds.json"), "w"))
    model = json.load(open(SW.MODEL))
    cheap = os.path.join(tmp, "m_buy.json")
    json.dump(dict(model, cut=1e-9), open(cheap, "w"))
    old = SW.MODEL
    try:
        SW.MODEL = cheap
        st = json.load(open(os.path.join(sk, "seeker.json"))) if os.path.exists(os.path.join(sk, "seeker.json")) else {}
        json.dump({"since": now - 2 * H}, open(os.path.join(sk, "seeker.json"), "w"))       # it ran when FFF's window passed
        d1 = SW.tick(sk, rd, now, mk)
    finally:
        SW.MODEL = old
    bk = d1["book"]
    c = d1["counts"]
    check(list(bk["open"]) == ["AAA"] and c["scored"] == 1 and c["bought"] == 1 and c["lowLiq"] == 1 and c["missed"] == 1
          and "EEE" not in d1["scored"] and "BBB" not in d1["scored"] and "CCC" not in d1["scored"] and c["noPair"] == 0,
          "S6 a tick: scores the 33-min PumpSwap coin and buys it at the cut, a thin pool left out, no price retried, too young and other DEX not "
          "looked at, a coin whose window passed counted missed: %s" % c)
    lg = [json.loads(x) for x in open(os.path.join(sk, "log", os.listdir(os.path.join(sk, "log"))[0]))]
    got = next((x for x in lg if x.get("addr") == "AAA"), {})
    check(got.get("buy") and got.get("bars") == 6 and set(got.get("f") or {}) == set(model["features"]) and got["f"]["f_curve_min"] == 4.0
          and got["f"]["f_post_age"] == 1.0, "S6 the log row: its inputs, 6 bars, the buy")
    # later: EEE has no price at its last try (43 min) -> no pair; AAA's price fell under half -> sold
    later = T0 + 43 * MIN
    rows2 = rows + [(t0 + 40 * MIN, 1e-4, 1e-4, 0.5e-4, 0.6e-4, 500.0), (t0 + 41 * MIN, 1e-4, 1e-4, 0.5e-4, 0.7e-4, 500.0)]
    json.dump(gt(rows2), open(os.path.join(mk, "gt_PAAA_ohlcv.json"), "w"))
    ds[0]["priceUsd"] = "0.00007"
    json.dump(ds, open(os.path.join(mk, "ds.json"), "w"))
    d2 = SW.tick(sk, rd, later, mk)
    sold = d2["book"]["closed"]
    check(sold and sold[0]["why"] == "floor" and sold[0]["mult"] < 0.5 and d2["counts"]["noPair"] == 1 and d2["book"]["open"] == {}
          and d2["counts"]["bought"] == 1 and d2["counts"]["missed"] == 1, "S6 a later tick: the coin without a price given up at 43 minutes, the bought one sold at half: %s %s"
          % ([(p["sym"], p["why"], p["mult"]) for p in sold], d2["counts"]))
    # the real cut (no buy on such a coin), plain Python only (no numpy on the runner)
    code = ("import sys; sys.modules['numpy'] = None; sys.modules['pandas'] = None; sys.path.insert(0, %r); import seeker_watch as SW, json; "
            "d = SW.tick(%r, %r, %d, %r); print(json.dumps(d['counts']))") % (HERE, os.path.join(tmp, "sk2"), rd, now, mk)
    os.makedirs(os.path.join(tmp, "sk2"), exist_ok=True)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    cc = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else {}
    check(p.returncode == 0 and cc.get("scored") == 1 and cc.get("bought") == 0, "S6 the real model, numpy blocked: scored, not at its cut %s %s" % (cc, p.stderr[-300:]))
    src = open(os.path.join(HERE, "seeker.py")).read() + open(os.path.join(HERE, "seeker_watch.py")).read()
    check(not re.search(r"^\s*(import|from)\s+(numpy|pandas|lightgbm)", src, re.M) and "app." not in src, "S6 no numpy/pandas/lightgbm, no push, no live row")
    return sk


class _R:
    import report as _rep
    local = staticmethod(_rep.local)
    fmt_px = staticmethod(_rep.fmt_px)


def s7(check, tmp, sk):
    import page_seeker as PSK, page_live as PL, report as REP
    D0 = {"dir": os.path.join(tmp, "nodir"), "now": T0}
    h0 = PSK.section(D0, REP)
    check('id="rocket-seeker"' in h0 and "starts soon" in h0 and "<script" not in h0, "S7 the fold without a doc")
    mb = os.path.join(tmp, "mb", "db", "memebot")
    os.makedirs(mb, exist_ok=True)
    doc = json.load(open(os.path.join(sk, "seeker.json")))
    doc["book"]["closed"][0]["sym"] = "<img src=x onerror=alert(1)>"
    doc["recent"][0]["sym"] = "<b>x</b>"
    json.dump(doc, open(os.path.join(mb, "seeker.json"), "w"))
    D = {"dir": os.path.join(tmp, "mb"), "now": T0 + 50 * MIN, "runs": [], "open": []}
    h = PSK.section(D, REP)
    check("Rocket seeker 🔭" in h and "<img src=x" not in h and "&lt;img" in h and "<script" not in h and "1 sold" in h and "fell to half" in h
          and "Nov 27" in h, "S7 the fold with a doc: its trade escaped, the sale's reason, the judgement day")
    tb = REP.tests_block(REP.seeker_block(D))
    check("Tests on the side" in tb and 'id="rocket-seeker"' in tb and "Rocket seeker" in tb, "S7 under Tests on the side")
    src = open(os.path.join(HERE, "report.py")).read()
    check('safe("rocket seeker", lambda: seeker_block(D))' in src, "S7 the Pick tab's tests include it")
    live = PL.section(D, REP)
    check('lv-a-rs' in live and "ROCKET SEEKER 🔭" in live and "sold <b>&lt;img" in live and "<img src=x" not in live and 'data-open="rocket-seeker"' in live,
          "S7 the Start tab: its own box and lane, its sale in the feed (escaped)")


def s8(check):
    y = open(os.path.join(HERE, ".github", "workflows", "seeker.yml")).read()
    pushes = re.findall(r"git push[^\n]*", y)
    check(pushes and all('"HEAD:$DATA_BRANCH"' in x for x in pushes) and "'seeker-smoke' || 'seeker-data'" in y, "S8 the workflow pushes only to its data branch")
    check("env -u REPO_URL timeout 55 python3 seeker_watch.py tick" in y and "group: memebot-seeker" in y and "secrets.SUPABASE" not in y,
          "S8 the bot runs without the token, in its own group, without the push secrets")
    s = open(os.path.join(HERE, ".github", "workflows", "scan.yml")).read()
    lines = [x for x in s.splitlines() if "seeker" in x]
    check("git show FETCH_HEAD:seeker.json > mb/db/memebot/seeker.json" in s and len(lines) == 4 and not any("push" in x for x in lines),
          "S8 the scan only copies seeker.json")


def s9(check, tmp):
    px = 5.488e-05                                               # NEX Ai's buy (27 Oct 2026, 23:54 UTC), its closes as GeckoTerminal gave them
    b = S.Book()
    b.buy("N", "NEX Ai", "PN", px, T0, 0.0618, 0.057)
    real = [(T0 + k * MIN, px * (1.0 + 0.02 * k)) for k in range(1, 9)]
    o1 = b.update("N", T0 + 9 * MIN, real, px=1.17 * px)
    o2 = b.update("N", T0 + 13 * MIN, [(T0 + 9 * MIN, 4_615_119.1 * px), (T0 + 10 * MIN, 7_231.48 * px), (T0 + 11 * MIN, 1.2 * px),
                                        (T0 + 12 * MIN, 1.21 * px)], px=1.2035 * px)
    n = b.open.get("N") or {}
    check(o1 is None and o2 is None and same(n.get("best"), 1.21) and n.get("lastT") == T0 + 12 * MIN,
          "S9 NEX Ai's glitch closes (4,615,119x, then 7,231x, DexScreener 1.2x) sell nothing and are no best: best %s" % n.get("best"))
    b.buy("R", "RUG", "PR", 1.0, T0, 0.1, 0.05)
    b.update("R", T0 + 3 * MIN, [(T0 + MIN, 1.2), (T0 + 2 * MIN, 1.28)])
    o3 = b.update("R", T0 + 6 * MIN, [(T0 + 3 * MIN, 0.18), (T0 + 4 * MIN, 0.17), (T0 + 5 * MIN, 0.15)])
    check(o3 and o3["why"] == "floor" and same(o3["mult"], 0.18) and o3.get("g") == 1,
          "S9 a real crash (1.28x to 0.18x, the next closes stay there) sells at 0.18x without DexScreener's price")
    b.buy("Q", "QUICK", "PQ", 1.0, T0, 0.1, 0.05)
    o4 = b.update("Q", T0 + 3 * MIN, [(T0 + MIN, 1.0), (T0 + 2 * MIN, 0.1)], px=0.1)
    check(o4 and o4["why"] == "floor" and same(o4["mult"], 0.1), "S9 a crash in the newest minute sells when DexScreener has the same price")
    b.buy("W", "WAIT", "PW", 1.0, T0, 0.1, 0.05)
    o5 = b.update("W", T0 + 3 * MIN, [(T0 + MIN, 1.0), (T0 + 2 * MIN, 0.0001)], px=1.0)
    o6 = b.update("W", T0 + 5 * MIN, [(T0 + 2 * MIN, 0.0001), (T0 + 3 * MIN, 1.02), (T0 + 4 * MIN, 1.01)], px=1.01)
    check(o5 is None and o6 is None and b.open["W"]["lastT"] == T0 + 4 * MIN and same(b.open["W"]["last"], 1.01),
          "S9 a glitch in the newest minute waits, and the next look leaves it out")
    b.buy("D", "DEAD", "PD", 1.0, T0, 0.1, 0.05)                 # .AiTown (27 Oct): a rug to 0.0001x, no trade after it, judged hours later
    o8 = b.update("D", T0 + 6 * H, [(T0 + MIN, 1.27), (T0 + 8 * MIN, 0.000064)], px=0.000064)
    b.buy("E", "STALE", "PE", 1.0, T0, 0.1, 0.05)
    o9 = b.update("E", T0 + 6 * H, [(T0 + MIN, 1.27), (T0 + 8 * MIN, 0.000064), (T0 + 9 * MIN, 1.25)], px=1.25)
    check(o8 and o8["why"] == "floor" and o8["mult"] == 0.0001 and o9 is None and same(b.open["E"]["last"], 1.25),
          "S9 a rug with no trade after it counts when DexScreener's price now is the same, hours later; an old glitch with trades after it does not")
    b.buy("K", "ROCKET", "PK", 1.0, T0, 0.1, 0.05)
    o7 = b.update("K", T0 + 7 * MIN, [(T0 + k * MIN, x) for k, x in enumerate((1.5, 3.0, 7.0, 16.0, 30.0, 17.0), 1)])
    check(o7 and o7["why"] == "trail" and same(o7["mult"], 17.0), "S9 a real rocket (1.5x to 30x within minutes) still counts: sold at 17x")
    # the sales booked before the guard, as seeker.json holds them (no "g")
    nex = {"addr": "N2", "sym": "NEX Ai", "pool": "PN2", "t": T0, "px": px, "score": 0.0618, "cut": 0.057, "best": 4615119.128804,
           "last": 7231.476908, "tok": "base", "seen": T0 + 11 * MIN, "now": 1.203535, "lastT": T0 + 10 * MIN, "out": T0 + 11 * MIN,
           "mult": 7231.4769, "eur": 138058.18, "why": "trail"}
    ait = dict(nex, addr="A2", sym=".AiTown", pool="PA2", px=3.114e-05, best=1.298045, last=6.4e-05, now=0.182177, mult=0.0001, eur=-20.0, why="floor")
    fine = dict(nex, addr="F2", sym="FINE", pool="PF2", best=1.1, last=0.45, now=0.6, mult=0.45, eur=S.net(0.45), why="floor")
    late = dict(fine, addr="G2", sym="GUARDED", mult=30.0, now=1.0, eur=S.net(30.0), why="trail", g=1)
    b2 = S.Book({"open": {}, "closed": [dict(nex), ait, fine, late]})
    back = b2.reopen_glitches()
    nx = b2.open.get("N2") or {}
    check(back == ["N2", "A2"] and [p["addr"] for p in b2.closed] == ["F2", "G2"] and nx.get("best") == 1.0 and "lastT" not in nx
          and (nx.get("was") or {}).get("eur") == 138058.18 and b2.reopen_glitches() == [] and b2.summary()["eur"] == round(S.net(0.45) + S.net(30.0), 2),
          "S9 the pre-guard sales on a glitch are open again (their old booking kept), a believable one and a guarded one stay: %s" % back)
    # a tick: NEX Ai open again, judged on its candles since the buy (the glitch closes still in them)
    rd, sk, mk = (os.path.join(tmp, "s9", x) for x in ("rd", "sk", "mk"))
    for x in (os.path.join(rd, "db", "memeradar"), sk, mk):
        os.makedirs(x, exist_ok=True)
    json.dump({"coins": {}}, open(os.path.join(rd, "db", "memeradar", "2026-10-27T00.json"), "w"))
    nex3 = dict(nex, addr="NNN", pool="PNNN")
    json.dump({"since": T0 - H, "book": {"open": {}, "closed": [nex3]}}, open(os.path.join(sk, "seeker.json"), "w"))
    rows = ([(T0 + k * MIN, px, px, px, px * (1.0 + 0.02 * k), 50.0) for k in range(0, 9)]
            + [(T0 + 9 * MIN, px, 4_615_119.1 * px, px, 4_615_119.1 * px, 50.0), (T0 + 10 * MIN, px, 7_231.48 * px, px, 7_231.48 * px, 50.0)]
            + [(T0 + k * MIN, px, px, px, px * x, 50.0) for k, x in ((11, 1.2), (12, 0.9), (13, 0.45), (14, 0.44))])
    json.dump(gt(rows), open(os.path.join(mk, "gt_PNNN_ohlcv.json"), "w"))
    json.dump([{"baseToken": {"address": "NNN"}, "pairAddress": "PNNN", "priceUsd": str(0.44 * px), "liquidity": {"usd": 20000}}],
              open(os.path.join(mk, "ds.json"), "w"))
    d = SW.tick(sk, rd, T0 + 15 * MIN + 5_000, mk)
    sold = d["book"]["closed"]
    check(len(sold) == 1 and sold[0]["why"] == "floor" and same(sold[0]["mult"], 0.45) and sold[0].get("g") == 1 and sold[0]["was"]["mult"] == 7231.4769
          and d["book"]["summary"]["eur"] == S.net(0.45) and d["book"]["summary"]["x10"] == 0,
          "S9 a tick judges NEX Ai again from its buy: the glitch closes skipped, sold at the real half (%s)" % [(p["why"], p["mult"], p["eur"]) for p in sold])


def checks(check):
    tmp = tempfile.mkdtemp(prefix="memebot-seeker-")
    try:
        s1(check)
        s2(check)
        s3(check)
        s4(check)
        s5(check)
        sk = s6(check, tmp)
        s7(check, tmp, sk)
        s8(check)
        s9(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    checks(check)
    print("\n%d checks failed" % len(FAILS) if FAILS else "\nALL PASS")
    sys.exit(1 if FAILS else 0)
