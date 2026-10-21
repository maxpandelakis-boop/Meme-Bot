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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks failed" % len(FAILS) if FAILS else "\nALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
