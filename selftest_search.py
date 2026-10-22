#!/usr/bin/env python3
"""selftest_search.py: the nightly filter search (filter_search.py) and its page block (page_search.py) on made-up scored chunks
(fake money only).

  python3 selftest_search.py

Checks: S1 the run writes the doc and the state and nothing else, and freezes one rule; S2 a second run on the same rows freezes
nothing new; S3 a frozen rule is measured only on scans after its frozenAt (rows before it can be changed at will without moving
its forward numbers); S4 a rule that wins on the unseen rows is "better" only once it has MIN_FWD coins over MIN_DAYS days, and a
losing one is "worse"; S5 the mistakes line counts the top picks of the last days; S6 the page block: no doc, a broken doc, a doc
(escaped text, the verdict, no script).
"""
import json, os, random, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_search as FS
import page_search as PS

FAILS = []
DAY, HOUR = 86_400_000, 3_600_000
T0 = FS.H.LEARN_FROM + DAY


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def coin(i, rng, good):
    """One coin row: 'good' coins have a high buy share and double; the rest lose a little or go to zero."""
    bs = rng.uniform(0.7, 0.9) if good else rng.uniform(0.3, 0.6)
    mult = rng.uniform(1.5, 2.5) if good else (0.0 if rng.random() < 0.1 else rng.uniform(0.7, 1.0))
    f = {k: rng.uniform(0, 10) for k in FS.FEATURES}
    f.update(ageH=rng.uniform(7, 20), buyShare=bs)
    return {"a": "C%05d" % i, "s": "C%d" % i, "f": f, "pass": rng.random() < 0.3, "rank": None, "eur": 0.0, "mult": mult,
            "gone": mult < 0.02, "liq": 30_000, "mc": 300_000, "why": []}


def write_chunks(d, days, start=T0, seed=1, n=120):
    rng = random.Random(seed)
    i = 0
    for k in range(days * 4):
        t0 = start + k * 6 * HOUR
        coins = []
        for _ in range(n):
            coins.append(coin(i, rng, rng.random() < 0.3))
            i += 1
        passers = [c for c in coins if c["pass"]]
        if passers:
            passers[0]["rank"] = 1
        json.dump({"t0": t0, "t": t0 + 2 * HOUR, "rule": "m9-2h", "coins": coins}, open(os.path.join(d, "%d.json" % t0), "w"))
    return start + days * DAY


def main():
    tmp = tempfile.mkdtemp(prefix="memebot-search-")
    try:
        snaps, out = os.path.join(tmp, "snaps"), os.path.join(tmp, "fs")
        os.makedirs(snaps)
        end = write_chunks(snaps, 6)
        FS.MIN_HALF = 30           # the made-up days are small
        state = {}
        doc, state = FS.build(snaps, state, end + DAY)
        FS.write(out, FS.DOC, FS.clean(doc))
        FS.write(out, FS.STATE, FS.clean(state))
        ch = state["challengers"]
        check(sorted(os.listdir(out)) == sorted([FS.DOC, FS.STATE]) and len(ch) == 1 and doc["tried"] > 1000,
              "S1 the run writes the doc and the state only and freezes one rule (%s; %d rules tried)" % (ch[0]["text"] if ch else "-", doc["tried"]))
        check(any(c[0] == "buyShare" and c[1] == ">=" for c in ch[0]["rule"]["c"]), "S1 the frozen rule found the made-up edge (buy share high): %s" % ch[0]["text"])
        doc2, state2 = FS.build(snaps, state, end + DAY)
        check(len(state2["challengers"]) == 1, "S2 a second run on the same rows freezes nothing new")
        check(doc2["challengers"][0]["fwd"].get("n", 0) == 0 and doc2["challengers"][0]["verdict"] == "watch",
              "S3 no row after frozenAt: the frozen rule has no forward coins and is only watched")
        # change every row before frozenAt: the forward numbers must not move; then add unseen days where the edge holds
        end2 = write_chunks(snaps, 5, start=end, seed=2)
        doc3, _ = FS.build(snaps, state, end2 + DAY)
        for fn in os.listdir(snaps):
            p = os.path.join(snaps, fn)
            dd = json.load(open(p))
            if dd["t0"] <= ch[0]["frozenAt"]:
                for c in dd["coins"]:
                    c["mult"] = 0.0
                json.dump(dd, open(p, "w"))
        doc4, _ = FS.build(snaps, state, end2 + DAY)
        f3, f4 = doc3["challengers"][0]["fwd"], doc4["challengers"][0]["fwd"]
        check(f3 == f4 and f3["n"] > 0, "S3 rows up to frozenAt never touch the forward test (%d unseen coins, %s per 20 both times)" % (f3["n"], f3.get("avg")))
        v = doc3["challengers"][0]
        want = "better" if f3["n"] >= FS.MIN_FWD and f3["days"] >= FS.MIN_DAYS else "watch"
        check(v["verdict"] == want and (want != "better" or doc3["leader"]), "S4 the edge holds on unseen days: verdict %s (n %d, %d days)" % (v["verdict"], f3["n"], f3["days"]))
        bad = dict(state["challengers"][0], rule={"w": "any", "c": [["buyShare", "<=", 0.6]]})
        doc5, _ = FS.build(snaps, {"challengers": [bad]}, end2 + DAY)
        check(any(c["verdict"] == "worse" for c in doc5["challengers"]), "S4 a losing rule on unseen days is 'worse'")
        m = doc3["mistakes"]
        check(m["picks"]["n"] > 0 and m.get("lost") is not None and m["lostKept"] + m["lostBlocked"] == m["lost"],
              "S5 the mistakes line: %d top picks, %s lost (%s kept, %s blocked)" % (m["picks"]["n"], m.get("lost"), m.get("lostKept"), m.get("lostBlocked")))
        # S6 the page block
        d = os.path.join(tmp, "mb")
        os.makedirs(os.path.join(d, "db", "memebot"))
        h0 = PS.section({"dir": d})
        check('data-pa="filtersearch"' in h0 and "No search yet" in h0, "S6 no doc: the block says so")
        open(os.path.join(d, *PS.DOC), "w").write("{bad")
        h1 = PS.section({"dir": d})
        check("could not be read" in h1, "S6 a broken doc: a notice, no error")
        doc3["challengers"][0]["text"] = "<script>x</script>"
        if doc3.get("leader"):
            doc3["leader"]["text"] = "<script>x</script>"
        json.dump(FS.clean(doc3), open(os.path.join(d, *PS.DOC), "w"))
        h2 = PS.section({"dir": d})
        check("<script>" not in h2 and "&lt;script&gt;" in h2 and ("beat the gates" in h2 or "No rule beats" in h2) and "ⓘ how" in h2,
              "S6 a doc: the verdict, escaped text, the method fold, no script")
        import report as R
        h3 = R.search_block({"dir": d})
        check('data-pa="filtersearch"' in h3 and h3.startswith("<section>") and "Filter search" in R.search_block.__doc__ + h3,
              "S7 the page shows the block: the Pick tab's Details holds it (report.search_block)")
        # S8 the user's goal: about 6 of 10 in profit, and only with a profit per pick
        lead = doc3["challengers"][0]
        check(doc3["winGoal"] == FS.WIN_GOAL and lead["fwd"]["win"] >= FS.WIN_GOAL and lead["goal"] is (lead["verdict"] != "watch"),
              "S8 the made-up edge wins %.0f%% of its unseen coins: goal %s (verdict %s)" % (lead["fwd"]["win"], lead["goal"], lead["verdict"]))
        check("Goal: 6 of 10 in profit" in h2 and ("Reached." in h2) == bool(doc3.get("leader") and lead["goal"]) and "of 10 in profit ·" in h2,
              "S8 the page names the goal, where the rule stands, and the share in profit next to the profit per 20")
        many_small = {"n": 200, "days": 5, "avg": -0.5, "win": 70.0, "hit3": 0.0, "zero": 5.0}
        g = PS.goal_line({"winGoal": 60.0}, many_small, {})
        check("Not yet." in g and "7.0 of 10" in g, "S8 7 of 10 in profit but a loss per pick is no goal: %s" % g[g.find("This rule"):])
        old = doc5["challengers"][0]
        check(not old["goal"], "S8 a losing rule never reaches the goal")
        # S9 the simulations: thousands of runs per rule, the verdict needs most of them in profit
        s_good, s_bad = lead["fwd"].get("sim") or {}, old["fwd"].get("sim") or {}
        check(s_good.get("sims") == FS.SIMS and s_good["pProfit"] >= FS.SIM_HOLD and s_bad.get("pProfit", 100) < 50
              and s_good["avg"][0] <= s_good["avg"][1] <= s_good["avg"][2] and len(s_good["curve"]["bad"]) == s_good["days"]
              and s_good["curve"]["bad"][-1] <= s_good["curve"]["typical"][-1],
              "S9 %d runs each: the edge in profit in %.0f%% of them, the losing rule in %.0f%%; the bad curve ends below the typical one" % (
                  s_good.get("sims", 0), s_good.get("pProfit", 0), s_bad.get("pProfit", 0)))
        import numpy as np
        flat = {"scan": np.repeat(np.arange(8) * DAY, 20).astype(float), "mult": np.full(160, 1.01)}
        sf = FS.simulate(flat, np.arange(160))
        check(sf["pProfit"] < 5, "S9 a rule that only breaks even before costs loses in the runs (random fees and slippage): %.1f%% in profit" % sf["pProfit"])
        check(FS.simulate(flat, np.arange(FS.SIM_MIN - 1)) is None, "S9 too few coins: no simulation")
        orig = FS.SIM_HOLD
        FS.SIM_HOLD = 101.0
        doc6, _ = FS.build(snaps, state, end2 + DAY)
        FS.SIM_HOLD = orig
        check(doc6["challengers"][0]["verdict"] != "better" and not doc6.get("leader"), "S9 a rule that does not hold in enough runs is never 'better'")
        check("simulations of this rule" in h2 and 'class="fs-sp"' in h2 and "<polyline" in h2, "S9 the page shows the runs' chance of profit and the two curves")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks failed" % len(FAILS) if FAILS else "\nALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
