#!/usr/bin/env python3
"""selftest_newrules.py: the New rules test (newrules.py, page_newrules.py, the filter search's B pass) and the Nov 4 clean-up (the
Learning Pick and the Rocket seeker stop buying, shadow rule D retired, the nightly training gone) on made-up data. Fake money only.

  python3 selftest_newrules.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                import selftest_newrules; selftest_newrules.checks(check)

NR1 the rules are the frozen candidates (research/livesearch/CANDIDATES-2026-11-04.json) word for word; FROM/UNTIL as pre-registered
NR2 a chart-exit variant replays with its own numbers and puts memebot's CHART_* back (also after an error); without "cp" as before
NR3 the Pick part: only buys from FROM, every rule on the same buys, P rules keep the buys whose factors pass (an unknown factor never
    passes), the real account beside them; the PR #39 bar (>= 40 trades, mean and 1 % point after the allowance, without the best)
NR4 the B part: the first scan per coin and UTC day, windows, the 2-hour result with fees and the cap, a coin without a price = 0,
    scans before FROM ignored; filter_search.load feeds the sink without changing its rows; the doc lands in filtersearch.json
NR5 the clean-up: the Learning Pick and the seeker buy nothing from STOPPED_AT on (before it as before), shadow D off the accounts but
    kept, filtersearch.yml without the Learning Pick's steps, the Start box and the fold
"""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MIN, HOUR = 60_000, 3_600_000


def checks(check):
    tmp = tempfile.mkdtemp(prefix="memebot-newrules-")
    try:
        _nr1(check)
        _nr2(check)
        _nr3(check, tmp)
        _nr4(check, tmp)
        _nr5(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _nr1(check):
    import newrules as NR
    print("== new rules NR1: the frozen candidates")
    C = json.load(open(os.path.join(HERE, "research", "livesearch", "CANDIDATES-2026-11-04.json"), encoding="utf-8"))
    fam = {f["family"][:2]: f["candidates"] for f in C["families"]}
    sell_ok = [r["cp"] == {k: v for k, v in c["rule"]["cp"].items()} and r["hours"] == c["rule"]["hours"] and r["stop"] == c["rule"]["stop"]
               and r["target"] == c["rule"]["target"] and r["chart"] for r, c in zip(NR.SELL, fam["F1"])]
    skip_ok = [s["c"] == c["conds"] for s, c in zip(NR.SKIP, fam["F2"])]
    buy_ok = [b["c"] == c["conds"] and b["w"] == c["window"] for b, c in zip(NR.BUY, fam["F3"])]
    check(len(NR.SELL) == len(fam["F1"]) == 3 and all(sell_ok) and len(NR.SKIP) == len(fam["F2"]) == 3 and all(skip_ok)
          and len(NR.BUY) == len(fam["F3"]) == 3 and all(buy_ok) and [r["id"] for r in NR.SELL + NR.SKIP + NR.BUY] == [c["id"] for f in ("F1", "F2", "F3") for c in fam[f]],
          "NR1 N1-N3, P1-P3 and B1-B3 are the frozen candidates of CANDIDATES-2026-11-04.json, word for word")
    check(NR.FROM == C["forwardFrom"] == 1793836800000 and NR.UNTIL == C["forwardBuysUntil"] == 1795262400000,
          "NR1 buys count from 5 Nov 2026 00:00 UTC; the judgement takes them up to 21 Nov 12:00 UTC")


def _path(entry, rows):
    return {"v": 1, "state": "ok", "entryAt": entry, "cpx": 1.0, "dead": None, "c": [[int(m * 60 - 19), x, v] for m, x, v in rows],
            "w": [[int(m * 60 - 19), x * 1.001, x * 0.999] for m, x, v in rows]}


def _nr2(check):
    import newrules as NR, shadow as SH, memebot as M
    print("== new rules NR2: a chart-exit variant")
    base = {k: getattr(M, k) for k in SH.CHART_KEYS}
    T = M.live_sell_at() + HOUR
    # up to 1.8x (arms X at 1.5x, not N1 at 2x), then a fall to 1.45x: X sells on its trail, N1 holds and sells at the time limit
    rows = [(m, 1.0 + 0.8 * m / 60, 500) for m in range(61)] + [(61 + m, 1.45, 500) for m in range(300)] + [(361 + m, 1.6, 500) for m in range(400)]
    doc = _path(T, rows)
    x = next(r for r in SH.RULES if r["id"] == "X")
    rx, rn = SH.replay(doc, x), SH.replay(doc, NR.SELL[0])
    after = {k: getattr(M, k) for k in SH.CHART_KEYS}
    check(rx["why"] == "trail" and rx["sales"][0][2] < 1.6 and rn["why"] == "time" and abs(rn["sales"][0][2] - 1.6) < 1e-6
          and rn["sales"][0][0] == T + 12 * HOUR and after == base,
          "NR2 the Sell bot replayed sells on its trail; N1 (arms at 2x, a 30 % fall, 12 h) holds to its 12-hour limit; CHART_* put back")
    bad = dict(NR.SELL[0], hours=None)
    try:
        SH.replay(doc, bad)
    except Exception:
        pass
    check({k: getattr(M, k) for k in SH.CHART_KEYS} == base, "NR2 CHART_* are put back after a replay that fails too")


def _pos(d, pid, t, f, real, sym="AAA"):
    import memebot as M
    os.makedirs(os.path.join(d, "db", "memepos"), exist_ok=True)
    os.makedirs(os.path.join(d, "db", "memeexit"), exist_ok=True)
    json.dump({"grp": "hold", "ticket": 50.0, "t": t, "entryAt": t, "px": 1e-5, "pair": "POOL" + pid, "addr": "ADDR" + pid, "sym": sym,
               "paper": M.PAPER_RULE, "f": f}, open(os.path.join(d, "db", "memepos", pid + ".json"), "w"))
    if real is not None:
        json.dump({"pos": pid, "t": t + 2 * HOUR, "px": 1e-5, "frac": 1.0, "why": "time", "eur": 50.0 + real, "grp": "hold"},
                  open(os.path.join(d, "db", "memeexit", pid + "-1.json"), "w"))


def _nr3(check, tmp):
    import newrules as NR, shadow as SH, memebot as M
    print("== new rules NR3: the Pick part")
    d = os.path.join(tmp, "pick")
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    json.dump({"paperSince": NR.FROM - 30 * 86_400_000, "paperRule": M.PAPER_RULE}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    good = {"buyRatio1h": 1.5, "buys1": 100, "rc.top10": 20.0, "logLiq": 4.5}
    some = {"buyRatio1h": 1.5, "buys1": 900}
    rows = [(m, 1.0 + 0.004 * m, 500) for m in range(720)]           # a slow rise to 3.9x over 12 h
    cases = [("2026-11-04T2300-h-OLD-a", NR.FROM - HOUR, good, 1.0), ("2026-11-05T0100-h-A-a", NR.FROM + HOUR, good, 5.0),
             ("2026-11-05T0300-h-B-b", NR.FROM + 3 * HOUR, some, -2.0), ("2026-11-05T0500-h-C-c", NR.FROM + 5 * HOUR, {}, 0.5),
             ("2026-11-05T0700-h-D-d", NR.FROM + 7 * HOUR, good, None)]
    for pid, t, f, real in cases:
        _pos(d, pid, t, f, real)
        doc = _path(t, rows)
        doc["pid"] = pid
        SH.write_doc(d, pid, doc)
    S = NR.pick_test(d, NR.FROM + 30 * HOUR)
    ids = [a["id"] for a in S["accts"]]
    sk = {a["id"]: a for a in S["skips"]}
    n1 = next(a for a in S["accts"] if a["id"] == "N1")
    check(S["n"] == 3 and S["open"] == 1 and ids == ["K", "X", "N1", "N2", "N3"] and S["real"]["eur"] == 3.5 and all(a["n"] == 3 for a in S["accts"])
          and n1["vsReal"] == round(n1["eur"] - 3.5, 2) and not any(r["pid"].endswith("OLD-a") for r in S["trades"]),
          "NR3 only the buys from FROM count (an older one does not), an unsold one is open, every sell rule on the same 3 buys, the real account beside them")
    check(sk["P1"]["n"] == 1 and sk["P1"]["real"] == 5.0 and sk["P2"]["n"] == 1 and sk["P3"]["n"] == 1 and all(a["of"] == 3 for a in sk.values()),
          "NR3 P1-P3 keep only the buys whose factors pass both conditions (too many buys, a missing factor: left out)")
    b1 = NR.bar([10.0] * 50, 1.5)
    b2 = NR.bar([10.0] * 39, 1.5)
    b3 = NR.bar([-50.0] * 49 + [500.0], 1.5)
    b4 = NR.bar([1.0] * 60, 1.5)
    check(b1["holds"] and not b2["holds"] and b2["why"] == "fewer than 40 trades" and not b3["holds"] and b3["wob"] < 0 and not b4["holds"] and b4["mean"] < 0,
          "NR3 the PR #39 bar: 40 trades at least, the mean and its 1 % point after the allowance above zero, also without the best trade")


def _nr4(check, tmp):
    import newrules as NR, filter_search as FS
    print("== new rules NR4: the B part on the big test")
    sink = NR.BigSink()
    f = {"ageH": 10.0, "volMc": 0.5, "vol1Share": 0.01, "jup.holderChg24": 6000, "jup.organic": 70.0, "buyRatio1h": 2.0}
    c = {"a": "COIN1", "s": "ONE", "f": f, "liq": 30_000.0, "mc": 300_000.0, "mult": 2.0}
    sink(NR.FROM + HOUR, c)
    sink(NR.FROM + 2 * HOUR, dict(c, mult=0.5))                       # the same coin later that day: not again
    sink(NR.FROM + 25 * HOUR, dict(c, mult=20.0))                     # the next day: again, capped at 11x
    sink(NR.FROM + 26 * HOUR, dict(c, a="COIN2", mult=0.01))          # no price: 0
    sink(NR.FROM - HOUR, dict(c, a="COIN3"))                          # before FROM: ignored
    sink(NR.FROM + 3 * HOUR, dict(c, a="COIN4", mc=3_000_000.0))      # outside the Learning Pick's universe
    doc = sink.doc(NR.FROM + 30 * HOUR)
    a = {x["id"]: x for x in doc["accts"]}
    want = [round(50 * 0.99 ** 2 * 2.0 - 50, 2), round(50 * 0.99 ** 2 * 11.0 - 50, 2), -50.0]
    got = [x[2] for x in a["B1"]["last"]]
    check(a["B1"]["n"] == 3 and len(got) == 3 and all(abs(g - w) < 0.011 for g, w in zip(got, want)) and a["B3"]["n"] == 3 and a["B2"]["n"] == 0
          and a["B1"]["days"] == 2 and abs(a["B1"]["eurWob"] - (sum(want) - max(want))) < 0.02 and doc["judge"]["B1"]["why"] == "fewer than 40 trades",
          "NR4 the first scan per coin and UTC day, 1 % a side, capped at 11x, no price = 0, nothing before FROM, the windows, without the best coin")
    snaps = os.path.join(tmp, "snaps")
    os.makedirs(snaps, exist_ok=True)
    coins = [dict(c, a="C%d" % i, sc=40.0, why=[], gone=False, eur=1.0) for i in range(3)]
    json.dump({"t0": NR.FROM + HOUR, "t": NR.FROM + 3 * HOUR, "rule": "m9-2h", "coins": coins}, open(os.path.join(snaps, "2026-11-05T0100-1.json"), "w"))
    s2 = NR.BigSink()
    R1 = FS.load(snaps)
    R2 = FS.load(snaps, sink=s2)
    same = all((R1[k] == R2[k]).all() if hasattr(R1[k], "all") else R1[k] == R2[k] for k in R1 if k not in FS.FEATURES) and len(R1["scan"]) == 3
    check(same and s2.doc(0)["accts"][0]["n"] == 3, "NR4 filter_search.load feeds the sink every kept coin and gives the same rows with it")
    src = open(os.path.join(HERE, "filter_search.py"), encoding="utf-8").read()
    check("doc[\"newrules\"] = sink.doc(now)" in src and "sink = NR.BigSink()" in src and src.count("except Exception as e:") >= 2,
          "NR4 the nightly filter search writes the doc \"newrules\" into filtersearch.json; a failure there never stops the search")


def _nr5(check, tmp):
    import lernpick as L, seeker as SK, shadow as SH, newrules as NR
    import yaml
    print("== new rules NR5: the clean-up")
    out = L.buy(tmp, L.STOPPED_AT)
    check(out.get("bought") is None and out.get("why") == L.STOPPED_WHY and L.STOPPED_AT == 1793815200000,
          "NR5 the Learning Pick buys nothing from 4 Nov 2026 18:00 UTC on (its open trades are still sold by run)")
    bk = SK.Book({})
    p1 = bk.buy("A1", "ONE", "POOL", 1e-5, SK.STOPPED_AT - MIN, 0.1, 0.05)
    p2 = bk.buy("A2", "TWO", "POOL", 1e-5, SK.STOPPED_AT, 0.1, 0.05)
    check(p1 is not None and p2 is None and SK.STOPPED_AT == 1793815200000, "NR5 the Rocket seeker buys before STOPPED_AT as before and nothing from it on")
    check([r["id"] for r in SH.RULES] == ["K", "A", "B", "C", "X"] and [r["id"] for r in SH.RETIRED] == ["D"] and SH.RETIRED[0]["trail"] == 0.30,
          "NR5 shadow rule D is off the accounts and kept in RETIRED")
    fs = yaml.safe_load(open(os.path.join(HERE, ".github", "workflows", "filtersearch.yml"), encoding="utf-8"))
    raw = open(os.path.join(HERE, ".github", "workflows", "filtersearch.yml"), encoding="utf-8").read()
    st = fs["jobs"]["search"]["steps"]
    check("lernpick.py" not in raw.replace("lernpick.py train ran", "") and not any(s.get("id") in ("lpget", "lptrain") for s in st)
          and [l.strip() for l in raw.splitlines() if "git push" in l] == ['git push -q "$REPO_URL" HEAD:filtersearch'],
          "NR5 filtersearch.yml: the Learning Pick's training steps are gone, the filter search pushes only to its own branch")
    gone = ["winlose-backfill-run", "winlose-backfill", "winlose-bars", "winlose-bars55", "winlose-helius", "winlose-hfprobe", "winlose-market",
            "winlose-social", "probe-keys", "history-probe"]
    check(not any(os.path.exists(os.path.join(HERE, ".github", "workflows", w + ".yml")) for w in gone),
          "NR5 the dead research workflows (triggers on an old branch, probes) are deleted")
    import page_newrules as PNR, page_live as LV
    import report as R
    d = os.path.join(tmp, "page")
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    json.dump({"newrules": {"accts": [{"id": "B1", "name": "<b>x</b>", "text": "t", "n": 2, "eur": 4.0, "per": 2.0, "won": 1, "eurWob": -1.0}]}},
              open(os.path.join(d, "db", "memebot", "filtersearch.json"), "w"))
    D = {"dir": d, "now": NR.FROM + HOUR}
    h = PNR.section(D, R)
    bal, line, role, go = PNR.box(D, R)
    pre = PNR.box({"dir": d, "now": NR.FROM - HOUR}, R)
    check('id="new-rules"' in h and "&lt;b&gt;x&lt;/b&gt;" in h and "<b>x</b>" not in h and "1 of 9 in profit" in h and "Nov 22" in h
          and bal == '<b class="lv-ab">1 of 9</b>' and 'data-open="new-rules"' in go and pre[0] == '<b class="lv-ab">–</b>' and "start" in pre[1],
          "NR5 the fold (escaped, how many of the 9 are in profit, the judgement day) and the Start box with its tap to the fold, before and after FROM")
    src = open(os.path.join(HERE, "page_live.py"), encoding="utf-8").read()
    check("lp_stopped = now >= L.STOPPED_AT" in src and "PNR.box(D, R)" in src and "not rs_stopped" in src,
          "NR5 Start: the New rules test takes the stopped Learning Pick's box; the stopped Rocket seeker leaves Start (its fold stays)")


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
