#!/usr/bin/env python3
"""selftest_rocket.py: the rocket hunter (rocket.py, rocket_watch.py, page_rocket.py, rocket.yml) on made-up data (fake money only).

  python3 selftest_rocket.py

Checks: R1 rocket.chart gives the research numbers (research/winlose/features.py chart_feats) on random charts; R1b the same with
minutes without a trade (high = low = the last close, features.dense fill_hl=False); R1c the grid's last 300 trades
(features.live_view) reach as far back as the live trades and keep the same split; R2 the plain-JSON trees
give lightgbm's own probabilities (rocket_model.json's check rows); R3 the paper account: one buy per coin, rule A (stop on a low
first, 11x, 6 h), fees; R4 a round on mocked answers: universe, scoring, a buy at the cut, a sell, the state and the log, no network;
R5 the page block: no doc, a doc (escaped, no script), its place at the top of the Radar tab; R6 the workflow only writes rocket-data,
uses the run's token and the push secrets only, and the scan job only reads rocket.json; R7 the "Radar 🚀" push of a round's paper buys;
R8 the minute watch between rounds; R9 rocket.yml's round step as written, on a fake clock: four rounds 15 minutes apart in one run,
each followed by a save, the watch until the next round and a save, the radar's records fetched again before each later round,
rocket_watch.py always without the token, a failed round neither stops the others nor ends the run green.
"""
import json, math, os, random, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rocket as R
import rocket_watch as RW
import page_rocket as PK
import page_home as PH

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


def r1c():
    """The model is trained on what the live account sees (LIVE-CHECK-2026-10-23.md): features.live_view cut to the last 300 trades
    reaches as far back as rocket.dense with GeckoTerminal's last 300 trades (trades after the check included), keeps the buy/sell
    split and counts of the minutes after the oldest trade's minute and has none before it."""
    try:
        sys.path.insert(0, os.path.join(HERE, "research", "winlose"))
        import numpy as np, pandas as pd
        import features as FE
    except Exception as e:
        check(True, "R1c skipped: the research module needs numpy and pandas (%s)" % type(e).__name__)
        return
    rng, bad, reaches = random.Random(11), [], []
    for _ in range(20):
        E = rng.choice([40, 90, 250])
        pool_ms, sol, busy = 1_800_000_000_000, 150.0, rng.choice([0.5, 3, 20, 120])
        px, rows, trades, bars = 1e-6, [], [], []
        for i in range(E + 1):
            k = int(rng.expovariate(1 / busy)) if rng.random() < 0.7 else 0
            if not k and i < E:
                continue
            px *= math.exp(rng.gauss(0, 0.05))
            tr = [{"t": pool_ms + i * 60_000 + (j + 1) * 59_000 / (k + 1), "buy": rng.random() < 0.55, "usd": rng.random() * 300, "who": "w%d" % rng.randrange(500)}
                  for j in range(k)]
            trades += tr
            if i < E:
                usd = sum(x["usd"] for x in tr)
                rows.append([pool_ms + i * 60_000, px, px * 1.02, px * 0.98, px, usd])
                bars.append({"mi": i, "p_close": px, "p_hi": px * 1.02, "p_lo": px * 0.98, "n_atomic": 0,
                             "sol_buy": sum(x["usd"] for x in tr if x["buy"]) / sol, "sol_sell": sum(x["usd"] for x in tr if not x["buy"]) / sol,
                             "n_buy": sum(1 for x in tr if x["buy"]), "n_sell": sum(1 for x in tr if not x["buy"])})
            else:
                bars.append({"mi": i, "p_close": px, "p_hi": px, "p_lo": px, "n_atomic": 0, "sol_buy": 0.0, "sol_sell": 0.0,
                             "n_buy": sum(1 for x in tr if x["buy"]), "n_sell": sum(1 for x in tr if not x["buy"])})
        last = sorted(trades, key=lambda x: x["t"])[-300:]
        b = R.dense(rows, last, pool_ms, pool_ms + E * 60_000, sol)
        a, reach = FE.live_view(FE.dense(pd.DataFrame(bars), fill_hl=False), E, 300)
        reaches.append(reach)
        if reach != b["reach"]:
            bad.append("reach %d vs %d" % (reach, b["reach"]))
            continue
        for i in range(E):
            if i == E - reach:                    # the oldest trade's minute: live has only its last trades
                continue
            for k in ("nb", "ns", "vb", "vs"):
                if abs(a[k][i] - b[k][i]) > 1e-9 * max(1.0, abs(b[k][i])):
                    bad.append(k)
    check(not bad and len(set(reaches)) > 3, "R1c the grid's last 300 trades = the live trades: same reach (%s), same split and counts (%s)" % (
        sorted(set(reaches))[:8], sorted(set(bad))[:5]))


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
        check("rocket hunter" in h and "Pick account" not in h and "Radar account 🚀" in h and "<img" not in h and "&lt;img" in h and "<script" not in h,
              "R5 the block shows the Radar account only (the Pick account 'for comparison' left it on Oct 26: each account once), escaped, no script")
        check(re.search(r"<span data-rk-round>Last round [^<]* radar coins watched, \d+ scored\. </span>", h) and "data-rk-round" in PK.LIVE_JS
              and "'Last round '+hhmm(t)" in PK.LIVE_JS, "R5 the round's line: the page's round, its time replaced live by a newer round's")
        js = PK.LIVE_JS
        check(all(k in h for k in ("data-rk-box", "data-rk-bal", 'data-rk-st="open"', "data-rk-op", "data-rk-sold", 'data-rk-cands="rk"', "data-rk-live"))
              and "id=eq.rocket" in js and "apikey:key" in js and "innerHTML" not in js and "Authorization" not in js and "tab-young" in js,
              "R5 the live row 'rocket' fills the block's data-rk hooks (publishable key, textContent only, while the Radar or Start tab is open)")
        lj = RW.live_doc(R.Book(doc["book"]), now, 0.5, [], [])
        check(PK.sold_li(PH, {"sym": "A<b>", "mult": 0.68, "eur": -6.6, "why": "stop", "out": now}).count("stop −30%") == 1 and "&lt;b&gt;" in PK.sold_li(PH, {"sym": "A<b>"})
              and isinstance(lj.get("summary"), dict) and isinstance(lj.get("open"), list), "R5 a sell row in the page's words (escaped); the live row has the shape LIVE_JS reads")
        check("Tested on Oct 22" in h and "does not hold" in h and "134" in h, "R5 the fold with the tests of 22 Oct is in the block")
        rp = PK.tests({"history": {"0.005": {"coins": 3}}, "replay": {"0.005": {"coins": 137, "avg": -7.84, "inProfitOf10": 0.5, "x10": 0, "sim": 0.0}}})
        check("Retest Oct 9–21" in rp and "137 buys" in rp and "no 10x" in rp, "R5 the fold shows the replay on the unseen days")
        tt = PK.tests({"history": {"0.005": {"coins": 3, "avg": "<script>", "x10": 1}}, "exits": {"rules": 2, "choice": "<b>x</b>"}})
        check("<script" not in tt and "<b>x" not in tt and "&lt;b&gt;x" in tt, "R5 the tests fold escapes what it shows")
        cd = PK.chart_div({"chart": [[0, 1], [5, "<b>"], [9, 2.5]], "t": now, "out": now + 9 * 60_000, "mult": 2.5}, True)
        check('data-rk-ch="[[0,1.0],[9,2.5]]"' in cd.replace("&quot;", '"') and 'data-rk-end="9,2.5"' in cd and "<b>" not in cd and "drawAll" in PK.LIVE_JS,
              "R5 a position's price line goes to the page as numbers only, LIVE_JS draws it with or without the live store")
        h0 = PK.section({"dir": os.path.join(tmp, "none")})
        check("has not run yet" in h0, "R5 without a doc: one sentence")
        # the trades in view (user, Oct 25: "where can I see what it buys and sells"): an empty account says so; a sale shows buy → sell price
        os.makedirs(os.path.join(tmp, "page0", "db", "memebot"))
        json.dump(dict(doc, book={"open": {}, "closed": []}), open(os.path.join(tmp, "page0", "db", "memebot", "rocket.json"), "w"))
        he = PK.section({"dir": os.path.join(tmp, "page0")})
        check("None open right now." in he and "No trade yet" in he and "data-rk-opnone>" in he and "data-rk-soldnone>" in he
              and "data-rk-opw hidden" not in he and "data-rk-soldw hidden" not in he and "All trades of the Radar account" not in he
              and "data-rk-opnone" in js and "data-rk-soldnone" in js,
              "R5 no trade yet: the open positions and the last sells stay in view with one line each (LIVE_JS hides the line once there is one)")
        sold = {"addr": "S1", "sym": "S<i>1", "t": now - 3 * 3_600_000, "px": 0.0002, "out": now - 3_600_000, "mult": 0.7, "eur": -6.1, "why": "stop"}
        opn = {"addr": "O1", "sym": "O1", "t": now - 600_000, "px": 0.00125, "now": 1.2, "hi": 1.3}
        json.dump(dict(doc, book={"open": {"O1": opn}, "closed": [sold]}), open(os.path.join(tmp, "page0", "db", "memebot", "rocket.json"), "w"))
        hs = PK.section({"dir": os.path.join(tmp, "page0")})
        sl = PK.sold_li(PH, sold)
        check("$0.0002000 → $0.0001400" in sl and sl.count("stop −30%") == 1 and "S&lt;i&gt;1" in sl and "at $0.001250" in hs
              and "All trades of the Radar account (1 sold" in hs and "data-rk-opnone hidden" in hs and "data-rk-soldnone hidden" in hs
              and "<i>1" not in hs and "px(bp)+' → '+px(bp*m)" in js,
              "R5 a sale shows buy price → sell price, the multiple, why and when; an open one when and at what price it was bought; a fold lists every sale")
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
    rnd = wf[wf.index("- name: Four rounds"):]
    calls = [l.strip() for l in rnd.splitlines() if "rocket_watch.py" in l and not l.strip().startswith("#")]
    check(len(calls) == 2 and all(c.startswith("env -u REPO_URL ") for c in calls) and rnd.count("secrets.GITHUB_TOKEN") == 1
          and "REPO_URL: https://x-access-token:${{ secrets.GITHUB_TOKEN }}" in rnd,
          "R6 the round itself never sees the GitHub token: rocket_watch.py runs with REPO_URL (the token's only carrier) removed (%s)" % calls)
    sc = open(os.path.join(HERE, ".github", "workflows", "scan.yml")).read()
    check("git show FETCH_HEAD:rocket.json > mb/db/memebot/rocket.json" in sc, "R6 the scan job copies rocket.json into the page (read only)")


def r7():
    import app as A
    w = A.rocket_words([{"sym": "ONE<b>", "score": 0.1234, "cut": 0.0839}, {"sym": "TWO", "score": 0.09}], {"trades": 3, "eur": -12.5})
    check(w and w[0].startswith("Radar 🚀") and "ONE" in w[0] and "+1" in w[0] and "0.123" in w[1] and "0.084" in w[1] and "Paper money only" in w[1]
          and "-12.50" in w[1], "R7 the push says Radar 🚀, the coin, its score and the cut, the record and that it is paper money (%s)" % (w,))
    w2 = A.rocket_words([], {"trades": 4, "eur": 170.0}, [{"sym": "TWO", "mult": 11.0, "eur": 190.03, "why": "11x"}, {"sym": "SIX", "mult": 0.5, "eur": -10.1, "why": "stop"}])
    check(w2 and w2[0] == "Radar 🚀 sold: TWO x11.00 (+190.03 €, target 11x)" and "SIX x0.50 (-10.10 €, stop -30%)" in w2[1] and "Paper money only" in w2[1],
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


def r8():
    """The minute watch between two rounds: rule A on the open positions only, a sell booked and logged at once, the round's scores
    kept; nothing open or the time up: it returns without a request."""
    tmp = tempfile.mkdtemp()
    try:
        t0 = 1_800_000_000_000
        b = R.Book()
        b.buy("AAA", "AAA", 1.0, t0, 0.5, 0.1, "pA")
        b.buy("BBB", "BBB", 1.0, t0, 0.5, 0.1, "pB")
        rk, mock = os.path.join(tmp, "rk"), os.path.join(tmp, "mock")
        os.makedirs(rk); os.makedirs(mock)
        json.dump({"v": 1, "t": t0, "book": b.doc(), "top": [{"addr": "X", "sym": "X", "score": 0.2, "age": 40, "buy": False}], "cut": 0.1, "checked": {"X": t0}},
                  open(os.path.join(rk, "rocket.json"), "w"))
        now = [t0 + 10 * 60_000]
        json.dump([{"baseToken": {"address": "AAA"}, "pairAddress": "pA", "priceUsd": "8"}, {"baseToken": {"address": "BBB"}, "pairAddress": "pB", "priceUsd": "1.1"}],
                  open(os.path.join(mock, "ds.json"), "w"))
        s_ = (now[0] - 30_000) // 1000
        json.dump({"data": {"attributes": {"ohlcv_list": [[s_, 5, 11.5, 5, 8, 100]]}}}, open(os.path.join(mock, "gt_pA_ohlcv.json"), "w"))
        json.dump({"data": {"attributes": {"ohlcv_list": [[s_, 1, 1.2, 0.9, 1.1, 100]]}}}, open(os.path.join(mock, "gt_pB_ohlcv.json"), "w"))
        slept = []
        def sleep(x):
            slept.append(x)
            now[0] += x * 1000
        out = RW.watch(rk, t0 + 13 * 60_000, mock, clock=lambda: now[0], sleep=sleep)
        st = json.load(open(os.path.join(rk, "rocket.json")))
        logs = open(os.path.join(rk, "log", os.listdir(os.path.join(rk, "log"))[0])).read()
        check(out["sold"] == 1 and list(st["book"]["open"]) == ["BBB"] and st["book"]["closed"][0]["why"] == "11x" and '"closed":true' in logs
              and st["top"][0]["sym"] == "X" and st["checked"] == {"X": t0} and st["t"] == t0,
              "R8 the watch sells AAA at 11x within the minute, logs it, keeps BBB open and the round's scores (%s)" % out)
        bb = st["book"]["open"]["BBB"].get("chart") or []
        aa = st["book"]["closed"][0].get("chart") or []
        check(bb[0] == [0, 1.0] and bb[-1][1] == 1.1 and len(bb) >= 2 and aa and aa[-1][1] == 8.0 and all(m >= 0 for m, _ in bb),
              "R8 every look adds the minute closes to the position's price line (the buy is [0, 1]); a sell keeps its line (%s, %s)" % (bb[-3:], aa[-2:]))
        big = {"t": t0, "px": 1.0, "chart": [[i, 1.0] for i in range(400)]}
        RW.chart_add(big, [], 1.0, t0 + 401 * 60_000)
        check(len(big["chart"]) <= RW.CHART_N and big["chart"][0] == [0, 1.0] and big["chart"][-1][0] == 401, "R8 a long line is thinned to CHART_N points, the buy and the newest kept")
        check(out["why"] == "time" and out["looks"] == 3 and slept[:2] == [60, 60], "R8 one look a minute until the next round (%s, %s)" % (out, slept))
        st["book"]["open"] = {}
        json.dump(st, open(os.path.join(rk, "rocket.json"), "w"))
        out2 = RW.watch(rk, t0 + 99 * 60_000, os.path.join(tmp, "none"), clock=lambda: now[0], sleep=sleep)
        check(out2 == {"looks": 0, "sold": 0, "why": "nothing open"}, "R8 nothing open: the watch ends at once (%s)" % out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


STUB_RW = r"""import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
now = int(open(os.path.join(d, "clock")).read())
cmd = sys.argv[1]
rec = {"cmd": cmd, "at": now, "argv": sys.argv[2:], "token": "REPO_URL" in os.environ, "supabase": "SUPABASE_URL" in os.environ}
open(os.path.join(d, "calls.jsonl"), "a").write(json.dumps(rec) + "\n")
plan = json.load(open(os.path.join(d, "plan.json")))
n = sum(1 for l in open(os.path.join(d, "calls.jsonl")) if json.loads(l)["cmd"] == cmd) - 1
if cmd == "round":
    open(os.path.join(d, "clock"), "w").write(str(now + 170))         # a round takes about 3 minutes
    sys.exit(1 if n in plan.get("fail", []) else 0)
until = int(sys.argv[sys.argv.index("--until") + 1])
if n in plan.get("open", []):                                        # something open: it looks every minute until the next round
    open(os.path.join(d, "clock"), "w").write(str(max(now, until)))
"""


def _shim(bindir, name, body):
    fn = os.path.join(bindir, name)
    open(fn, "w").write("#!/bin/bash\n" + body + "\n")
    os.chmod(fn, 0o755)


def r9():
    """rocket.yml's round step run as written (bash -e, as GitHub runs it) with stand-ins for rocket_watch.py, git, date and sleep on a
    fake clock."""
    import subprocess
    try:
        import yaml
    except ImportError:
        print("skip  R9 (PyYAML is not installed)")
        return
    wf = yaml.safe_load(open(os.path.join(HERE, ".github", "workflows", "rocket.yml"), encoding="utf-8"))
    job = wf["jobs"]["round"]
    st = next(x for x in job["steps"] if str(x.get("name", "")).startswith("Four rounds"))
    on = wf.get("on") or wf.get(True) or {}
    check(on.get("schedule") == [{"cron": "7,22,37,52 * * * *"}] and wf["concurrency"] == {"group": "memebot-rocket", "cancel-in-progress": False}
          and job["timeout-minutes"] == 75 and job["steps"][-1] is st and "STARTED" in job["steps"][0]["run"],
          "R9 rocket.yml: the cron still fires every 15 minutes, one run at a time (the newest waiting run takes over), 75 minutes for a run of four rounds")
    started = 1_800_000_000

    def run(plan):
        tmp = tempfile.mkdtemp()
        try:
            ws, bindir = os.path.join(tmp, "ws"), os.path.join(tmp, "bin")
            for x in (ws, bindir, os.path.join(ws, "rk"), os.path.join(ws, "rd")):
                os.makedirs(x)
            open(os.path.join(ws, "rocket_watch.py"), "w").write(STUB_RW)
            open(os.path.join(ws, "plan.json"), "w").write(json.dumps(plan))
            open(os.path.join(ws, "clock"), "w").write(str(started + 25))      # the clones and the push sender took 25 s
            open(os.path.join(ws, "calls.jsonl"), "w").close()
            clock = os.path.join(ws, "clock")
            _shim(bindir, "date", 'if [ "$1" = "+%%s" ]; then cat "%s"; else /bin/date "$@"; fi' % clock)
            _shim(bindir, "sleep", 'echo $(( $(cat "%s") + $1 )) > "%s"' % (clock, clock))
            _shim(bindir, "git", 'printf "%%s|%%s|%%s\\n" "$(cat "%s")" "${REPO_URL:+token}" "$*" >> "%s"; exit 0'
                  % (clock, os.path.join(ws, "git.log")))
            env = {"PATH": bindir + os.pathsep + os.environ.get("PATH", ""), "STARTED": str(started), "HOME": tmp,
                   "REPO_URL": "https://x-access-token:SECRET@github.com/o/r.git", "SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "k"}
            p = subprocess.run(["bash", "-e", "-c", st["run"]], cwd=ws, env=env, capture_output=True, text=True, timeout=60)
            calls = [json.loads(l) for l in open(os.path.join(ws, "calls.jsonl"))]
            gl = [l.split("|", 2) for l in open(os.path.join(ws, "git.log")).read().splitlines()] if os.path.exists(os.path.join(ws, "git.log")) else []
            return p, calls, gl, int(open(clock).read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    p, calls, gl, end = run({"open": [1, 2]})
    rounds = [c for c in calls if c["cmd"] == "round"]
    watches = [c for c in calls if c["cmd"] == "watch"]
    ats = [started + i * 900 for i in range(4)]
    order = [c["cmd"] for c in calls]
    pushes = [g for g in gl if g[2].startswith("push")]
    fetches = [g for g in gl if "fetch" in g[2] and "radar-data" in g[2]]
    check(p.returncode == 0 and len(rounds) == 4 and [r["at"] for r in rounds] == [started + 25] + ats[1:]
          and [int(w["argv"][w["argv"].index("--until") + 1]) for w in watches] == [a + 840 for a in ats] and order == ["round", "watch"] * 4,
          "R9 one run: four rounds 15 minutes apart (the first at once), each followed by the watch until 14 minutes after its start (%s)"
          % [(r["at"] - started) for r in rounds])
    check(not any(c["token"] for c in calls) and all(c["supabase"] for c in calls) and len(pushes) == 8
          and all(g[1] == "token" and "HEAD:rocket-data" in g[2] for g in pushes) and "SECRET" not in p.stdout + p.stderr,
          "R9 rocket_watch.py never has the token (the push secrets it has); the state is pushed to rocket-data after every round and every "
          "watch (%d pushes)" % len(pushes))
    t_push = [int(g[0]) for g in pushes]
    check(all(t_push[2 * i] < (int(watches[i]["argv"][watches[i]["argv"].index("--until") + 1]) if i in (1, 2) else 10 ** 12) for i in range(4))
          and t_push[2] == rounds[1]["at"] + 170 and len(fetches) == 3 and int(fetches[0][0]) == ats[1]
          and end - started == 3600 - 60 and "4 rounds, 0 failed" in p.stdout,
          "R9 a round's buys are saved before its watch begins; the radar's records are fetched again before each later round; the run "
          "ends a minute before the next round is due (%d min after its start, inside its 75), so the waiting run's first round comes 15 "
          "minutes after the last one" % ((end - started) // 60))
    p2, calls2, _, _ = run({"fail": [1]})
    check(p2.returncode != 0 and sum(1 for c in calls2 if c["cmd"] == "round") == 4 and "round 1 failed" in p2.stdout and "4 rounds, 1 failed" in p2.stdout,
          "R9 a failed round neither stops the others nor lets the run end green (%s)" % p2.returncode)


def main():
    r1(); r1b(); r1c(); r2(); r3(); r4(); r6(); r7(); r8(); r9()
    print("\n%d failed" % len(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
