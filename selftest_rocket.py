#!/usr/bin/env python3
"""selftest_rocket.py: the rocket hunter (rocket.py, rocket_watch.py, page_rocket.py, rocket.yml) on made-up data (fake money only).

  python3 selftest_rocket.py

Checks: R1 rocket.chart gives the research numbers (research/winlose/features.py chart_feats) on random charts; R1b the same with
minutes without a trade (high = low = the last close, features.dense fill_hl=False); R2 the plain-JSON trees
give lightgbm's own probabilities (rocket_model.json's check rows); R3 the paper account: one buy per coin, rule A (stop on a low
first, 11x, 6 h), fees; R4 a round on mocked answers: universe, scoring, a buy at the cut, a sell, the state and the log, no network;
R5 the page block: no doc, a doc (escaped, no script), its place at the top of the Radar tab; R6 the workflow only writes rocket-data,
uses the run's token and the push secrets only, and the scan job only reads rocket.json; R7 the "Radar 🚀" push of a round's paper buys.
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


def r1b():
    """Minutes without a trade: rocket.dense (live) and the research grid (features.dense, fill_hl=False) give the same high, low and
    close (the last close), and so the same chart numbers; the old forward fill of the high and low (fill_hl=True) does not."""
    try:
        sys.path.insert(0, os.path.join(HERE, "research", "winlose"))
        import numpy as np, pandas as pd
        import features as FE
    except Exception as e:
        check(True, "R1b skipped: the research module needs numpy and pandas (%s)" % type(e).__name__)
        return
    rng, bad, n, old_differs = random.Random(9), [], 0, 0
    for _ in range(20):
        E = rng.choice([40, 90, 250, 600])
        pool_ms, sol = 1_800_000_000_000, 150.0
        mins = sorted(set([E - 1] + [i for i in range(E - 1) if rng.random() < 0.4]))
        px, rows = 1e-6, []
        for i in mins:
            px *= math.exp(rng.gauss(0, 0.08))
            hi = px * (1 + rng.random() * (30 if rng.random() < 0.05 else 0.05))         # now and then a wild wick
            rows.append([pool_ms + i * 60_000, px, hi, px * (1 - rng.random() * 0.05), px, rng.random() * 3000])
        b = R.dense(rows, [], pool_ms, pool_ms + E * 60_000, sol)
        g = pd.DataFrame({"mi": [int((r[0] - pool_ms) // 60_000) for r in rows], "p_close": [r[4] for r in rows], "p_hi": [r[2] for r in rows],
                          "p_lo": [r[3] for r in rows], "sol_buy": [r[5] / sol / 2 for r in rows], "sol_sell": [r[5] / sol / 2 for r in rows],
                          "n_buy": 0, "n_sell": 0, "n_atomic": 0})
        a, a_old = FE.dense(g, fill_hl=False), FE.dense(g)
        for k in ("c", "hi", "lo"):
            n += E
            if any(abs(x - y) > 1e-12 * max(1e-12, abs(y)) for x, y in zip(b[k], a[k])):
                bad.append(k)
        old_differs += any(abs(x - y) > 1e-12 for x, y in zip(b["hi"], a_old["hi"]))
        f1, f2 = FE.chart_feats(a, E), R.chart(b)
        for k in set(f1) | set(f2):
            x, y = f1.get(k, float("nan")), f2.get(k, float("nan"))
            if not ((x != x and y != y) or abs(x - y) <= 1e-6 * max(1, abs(x))):
                bad.append(k)
    check(not bad and n > 1000, "R1b minutes without a trade: live and research arrays and chart numbers agree (%d values, differ: %s)" % (n, sorted(set(bad))[:5]))
    check(old_differs > 0, "R1b the old forward fill of highs would differ on such charts (%d of 20)" % old_differs)


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
        check("Rocket hunter" in h and "Pick" in h and "Raketen-Jäger" in h and "<img" not in h and "&lt;img" in h and "<script" not in h, "R5 the block shows both accounts, escaped, no script")
        check("Geprüft am 22. Okt" in h and "hält nicht" in h and "134" in h, "R5 the fold with the tests of 22 Oct is in the block")
        tt = PK.tests({"history": {"0.005": {"coins": 3, "avg": "<script>", "x10": 1}}, "exits": {"rules": 2, "choice": "<b>x</b>"}})
        check("<script" not in tt and "<b>x" not in tt and "&lt;b&gt;x" in tt, "R5 the tests fold escapes what it shows")
        h0 = PK.section({"dir": os.path.join(tmp, "none")})
        check("noch nicht gelaufen" in h0, "R5 without a doc: one sentence")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def r6():
    src = open(os.path.join(HERE, "report.py")).read()
    check('safe("rocket hunter", lambda: rocket_block(D)) + safe("launch radar"' in src, "R5 report.py puts the block at the top of the Radar tab")
    wf = open(os.path.join(HERE, ".github", "workflows", "rocket.yml")).read()
    secrets = set(x.split("}")[0].split()[0].strip() for x in wf.split("secrets.")[1:])
    check(secrets == {"GITHUB_TOKEN", "SUPABASE_URL", "SUPABASE_SECRET_KEY"} and "HEAD:rocket-data" in wf and "--force" not in wf
          and "memebot-rocket" in wf and "--require-hashes" in wf,
          "R6 rocket.yml uses the run's token and the push secrets only (%s), pushes only to rocket-data (no force) in its own concurrency group, the push sender pinned" % sorted(secrets))
    rnd = wf[wf.index("- name: One round"):wf.index("- name: Save the state")]
    check("GITHUB_TOKEN" not in rnd, "R6 the round itself never sees the GitHub token")
    sc = open(os.path.join(HERE, ".github", "workflows", "scan.yml")).read()
    check("git show FETCH_HEAD:rocket.json > mb/db/memebot/rocket.json" in sc, "R6 the scan job copies rocket.json into the page (read only)")


def r7():
    import app as A
    w = A.rocket_words([{"sym": "ONE<b>", "score": 0.1234, "cut": 0.0839}, {"sym": "TWO", "score": 0.09}], {"trades": 3, "eur": -12.5})
    check(w and w[0].startswith("Radar 🚀") and "ONE" in w[0] and "+1" in w[0] and "0.123" in w[1] and "0.084" in w[1] and "Papiergeld" in w[1]
          and "-12.50" in w[1], "R7 the push says Radar 🚀, the coin, its score and the cut, the record and that it is paper money (%s)" % (w,))
    w2 = A.rocket_words([], {"trades": 4, "eur": 170.0}, [{"sym": "TWO", "mult": 11.0, "eur": 190.03, "why": "11x"}, {"sym": "SIX", "mult": 0.5, "eur": -10.1, "why": "stop"}])
    check(w2 and w2[0] == "Radar 🚀 verkauft: TWO x11.00 (+190.03 €, Ziel 11x)" and "SIX x0.50 (-10.10 €, Stop -30 %)" in w2[1] and "Papiergeld" in w2[1],
          "R7 a round with sells only: the push names each sale, its multiple, euros and why (%s)" % (w2,))
    w3 = A.rocket_words([{"sym": "NEW", "score": 0.1, "cut": 0.08}], None, [{"sym": "OLD", "mult": 1.2, "eur": 3.6, "why": "6h"}])
    check(w3 and "NEW" in w3[0] and "OLD x1.20" in w3[1], "R7 buys and sells of one round: one push (the rate guard would drop a second)")
    check(A.rocket_words([]) is None and A.notify_rocket([]) == {"skipped": "no buys"}, "R7 no buys: no push")
    check(A.KINDS.get("rocket") and len(A.TOPIC["rocket"]) in (4, 8) and A.PREF_OF.get("rocket") == "young",
          "R7 kind rocket: its own rate guard, an 8-letter topic, the New coins setting")
    old = os.environ.pop("SUPABASE_URL", None)
    try:
        check(A.notify_rocket([{"sym": "X", "score": 0.2, "cut": 0.08}]).get("skipped") == "no live store", "R7 without the store nothing is sent")
    finally:
        if old is not None:
            os.environ["SUPABASE_URL"] = old
    src = open(os.path.join(HERE, "rocket_watch.py")).read()
    check("app.notify_rocket(buys, book.summary(), closed)" in src and "if not mock:" in src and 'app.put_row("rocket"' in src,
          "R7 rocket_watch pushes a round's buys and sells once and writes the live row, never in a mocked round")
    b = R.Book(); b.buy("A", "A", 1.0, 1, 0.2, 0.1, "p"); b.buy("B", "B", 1.0, 1, 0.2, 0.1, "p"); out = b.update("B", 2, hi=12.0, lo=0.9, px=11.0)
    ld = RW.live_doc(b, 3, 0.08, [{"addr": "A", "sym": "A", "score": 0.2, "age": 40, "buy": True, "pool": "x"}], [out])
    check(ld["summary"]["trades"] == 1 and len(ld["open"]) == 1 and ld["soldNow"] == ["B"] and "pool" not in ld["top"][0] and len(json.dumps(ld)) < 4000,
          "R7 the live row: summary, open positions, the last sells, the round's top scores, small (%d bytes)" % len(json.dumps(ld)))


def main():
    r1(); r1b(); r2(); r3(); r4(); r6(); r7()
    print("\n%d failed" % len(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
