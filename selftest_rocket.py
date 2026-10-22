#!/usr/bin/env python3
"""selftest_rocket.py: the rocket hunter (rocket.py, rocket_watch.py, page_rocket.py, rocket.yml) on made-up data (fake money only).

  python3 selftest_rocket.py

Checks: R1 rocket.chart gives the research numbers (research/winlose/features.py chart_feats) on random charts; R2 the plain-JSON trees
give lightgbm's own probabilities (rocket_model.json's check rows); R3 the paper account: one buy per coin, rule A (stop on a low
first, 11x, 6 h), fees; R4 a round on mocked answers: universe, scoring, a buy at the cut, a sell, the state and the log, no network;
R5 the page block: no doc, a doc (escaped, no script), its place at the top of the Radar tab; R6 the workflow only writes rocket-data,
uses no secret but the run's token, and the scan job only reads rocket.json.
"""
import json, math, os, random, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rocket as R
import rocket_watch as RW
import page_rocket as PK

FAILS = []
H = 3_600_000


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def r1():
    try:
        sys.argv = sys.argv[:1]
        sys.path.insert(0, os.path.join(HERE, "research", "winlose"))
        import numpy as np
        import features as FE
    except Exception as e:
        check(True, "R1 skipped: the research module needs numpy and pandas (%s)" % type(e).__name__)
        return
    rng, bad, n = random.Random(3), [], 0
    for _ in range(30):
        E = rng.choice([30, 47, 75, 120, 230, 400, 900])
        c = [1e-6]
        for i in range(E - 1):
            c.append(c[-1] * math.exp(rng.gauss(0, 0.05)))
        a = dict(c=c, hi=[x * (1 + rng.random() * 0.05) for x in c], lo=[x * (1 - rng.random() * 0.05) for x in c],
                 vb=[rng.random() * 3 if rng.random() < 0.7 else 0.0 for _ in c], vs=[rng.random() * 3 if rng.random() < 0.7 else 0.0 for _ in c],
                 nb=[float(rng.randint(0, 5)) for _ in c], ns=[float(rng.randint(0, 5)) for _ in c], na=[0.0] * E)
        f1 = FE.chart_feats({k: np.array(v) for k, v in a.items()}, E)
        f2 = R.chart(dict(a, E=E))
        for k in set(f1) | set(f2):
            n += 1
            x, y = f1.get(k, float("nan")), f2.get(k, float("nan"))
            if not ((x != x and y != y) or abs(x - y) <= 1e-6 * max(1, abs(x))):
                bad.append(k)
    check(not bad and n > 1000, "R1 rocket.chart = the research numbers on 30 random charts (%d values, %d differ: %s)" % (n, len(bad), sorted(set(bad))[:5]))


def r2():
    m = json.load(open(RW.MODEL))
    ck = m.get("check") or {}
    got = [R.score(m, {k: (v if v is not None else float("nan")) for k, v in zip(m["features"], row)}) for row in ck.get("x") or []]
    diff = max((abs(a - b) for a, b in zip(got, ck.get("p") or [])), default=1)
    check(len(got) >= 10 and diff < 1e-6, "R2 the JSON trees give lightgbm's probabilities (%d rows, largest gap %.2g)" % (len(got), diff))
    check(0 < m["cut"] < 1 and m["cutTop"] == 0.005 and len(m["features"]) == len(set(m["features"])), "R2 the cut is the top 0.5%% of the training rows (%.4f)" % m["cut"])


def r3():
    b = R.Book()
    t = 1_800_000_000_000
    b.buy("A", "A", 1.0, t, 0.5, 0.1, "pA")
    check(b.buy("A", "A", 1.0, t + 1, 0.5, 0.1, "pA") is None, "R3 a coin is bought once")
    out = b.update("A", t + H, hi=12.0, lo=0.5, px=2.0)
    check(out and out["why"] == "stop" and abs(out["mult"] - 0.5) < 1e-9, "R3 a stop and a target in the same look count as the stop (the safe side)")
    b.buy("B", "B", 1.0, t, 0.5, 0.1, "pB")
    b.update("B", t + H, hi=5.0, lo=0.9, px=4.0)
    out = b.update("B", t + 2 * H, hi=11.5, lo=4.0, px=10.0)
    check(out and out["why"] == "11x" and out["mult"] == 11.0 and abs(out["eur"] - R.net(11.0)) < 1e-9, "R3 11x sells at 11x after fees")
    b.buy("C", "C", 1.0, t, 0.5, 0.1, "pC")
    check(b.update("C", t + 5 * H, hi=1.2, lo=0.8, px=1.1) is None, "R3 within 6 h and between the levels it stays open")
    out = b.update("C", t + 6 * H, hi=1.2, lo=0.8, px=1.1)
    check(out and out["why"] == "6h" and abs(out["mult"] - 1.1) < 1e-9, "R3 after 6 h it sells at the price then")
    s = b.summary()
    check(s["trades"] == 3 and s["x10"] == 1 and s["inProfitOf10"] is not None, "R3 the summary counts trades, 10x highs and the share in profit (%s)" % s)


def r4():
    tmp = tempfile.mkdtemp(prefix="memebot-rocket-")
    try:
        now = 1_800_000_000_000
        rd, rk, mock = (os.path.join(tmp, x) for x in ("rd", "rk", "mock"))
        os.makedirs(os.path.join(rd, "db", "memeradar")); os.makedirs(mock)
        pool_ms = now - 3 * H
        coins = {"MINT1": {"addr": "MINT1", "sym": "ONE", "pair": "POOL1", "pool": pool_ms},
                 "MINT2": {"addr": "MINT2", "sym": "TWO", "pair": "POOL2", "pool": pool_ms},
                 "MINT3": {"addr": "MINT3", "sym": "<b>x</b>", "pair": "POOL3", "pool": now - 5 * 60_000}}       # too young
        json.dump({"coins": coins}, open(os.path.join(rd, "db", "memeradar", "2026-01-01T00.json"), "w"))
        ds = [{"baseToken": {"address": "MINT1"}, "pairAddress": "POOL1", "priceUsd": "0.0004", "marketCap": 400000, "liquidity": {"usd": 60000},
               "volume": {"h24": 300000}, "priceChange": {"h1": 12, "h6": 40}},
              {"baseToken": {"address": "MINT2"}, "pairAddress": "POOL2", "priceUsd": "0.0001", "marketCap": 50000, "liquidity": {"usd": 9000},
               "volume": {"h24": 5000}, "priceChange": {"h1": 1, "h6": 2}},
              {"baseToken": {"address": "MINT3"}, "pairAddress": "POOL3", "priceUsd": "0.0004", "marketCap": 400000, "liquidity": {"usd": 60000},
               "volume": {"h24": 300000}, "priceChange": {"h1": 12, "h6": 40}}]
        json.dump(ds, open(os.path.join(mock, "ds.json"), "w"))
        rng = random.Random(5)
        px, rows = 0.0001, []
        for i in range(180):
            px *= math.exp(rng.gauss(0.008, 0.03))
            rows.append([(pool_ms + i * 60_000) // 1000, px, px * 1.02, px * 0.98, px, rng.random() * 2000])
        json.dump({"data": {"attributes": {"ohlcv_list": rows[::-1]}}}, open(os.path.join(mock, "gt_POOL1_ohlcv.json"), "w"))
        tr = [{"attributes": {"block_timestamp": "2027-01-15T07:%02d:00Z" % (m % 60), "kind": "buy" if m % 3 else "sell", "volume_in_usd": 50 + m,
                              "tx_from_address": "W%d" % (m % 17)}} for m in range(40)]
        json.dump({"data": tr}, open(os.path.join(mock, "gt_POOL1_trades.json"), "w"))
        kl = [[now - (26 - i) * H, "0", "0", "0", str(100 + i), "0"] for i in range(26)]
        json.dump(kl, open(os.path.join(mock, "binance_BTCUSDT.json"), "w")); json.dump(kl, open(os.path.join(mock, "binance_SOLUSDT.json"), "w"))
        m = json.load(open(RW.MODEL))
        m["cut"] = 0.0                       # every scored coin reaches the cut in this test
        mp = os.path.join(tmp, "model.json")
        json.dump(m, open(mp, "w"))
        old, RW.MODEL = RW.MODEL, mp
        try:
            doc = RW.round_(rk, rd, now, mock)
            doc2 = RW.round_(rk, rd, now + 5 * 60_000, mock)
        finally:
            RW.MODEL = old
        bk = doc["book"]
        check(doc["round"]["candidates"] == 2 and doc["round"]["scored"] == 1 and list(bk["open"]) == ["MINT1"],
              "R4 the round watches only coins 30 min old or more and scores only the one in the universe (big enough) and buys it at the cut (%s)" % doc["round"])
        check(doc2["round"]["scored"] == 0 and list(doc2["book"]["open"]) == ["MINT1"], "R4 a bought coin is neither scored nor bought again")
        logs = os.listdir(os.path.join(rk, "log"))
        check(os.path.exists(os.path.join(rk, "rocket.json")) and len(logs) == 1, "R4 the state and the day's log are written in the state folder only")
        check(set(doc["round"]["calls"]) <= {"ds", "gt", "binance"}, "R4 only DexScreener, GeckoTerminal and Binance are asked (%s)" % doc["round"]["calls"])
        # the page block
        os.makedirs(os.path.join(tmp, "page", "db", "memebot"))
        doc["top"][0]["sym"] = "<img src=x onerror=alert(1)>"
        json.dump(doc, open(os.path.join(tmp, "page", "db", "memebot", "rocket.json"), "w"))
        h = PK.section({"dir": os.path.join(tmp, "page")})
        check("Rocket hunter" in h and "Pick" in h and "<img" not in h and "&lt;img" in h and "<script" not in h, "R5 the block shows both accounts, escaped, no script")
        h0 = PK.section({"dir": os.path.join(tmp, "none")})
        check("has not run yet" in h0, "R5 without a doc: one sentence")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def r6():
    src = open(os.path.join(HERE, "report.py")).read()
    check('safe("rocket hunter", lambda: rocket_block(D)) + safe("launch radar"' in src, "R5 report.py puts the block at the top of the Radar tab")
    wf = open(os.path.join(HERE, ".github", "workflows", "rocket.yml")).read()
    secrets = set(x.split("}")[0].strip() for x in wf.split("secrets.")[1:])
    check(secrets == {"GITHUB_TOKEN"} and "HEAD:rocket-data" in wf and "--force" not in wf and "memebot-rocket" in wf,
          "R6 rocket.yml uses only the run's token, pushes only to rocket-data (no force) in its own concurrency group")
    sc = open(os.path.join(HERE, ".github", "workflows", "scan.yml")).read()
    check("git show FETCH_HEAD:rocket.json > mb/db/memebot/rocket.json" in sc, "R6 the scan job copies rocket.json into the page (read only)")


def main():
    r1(); r2(); r3(); r4(); r6()
    print("\n%d failed" % len(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
