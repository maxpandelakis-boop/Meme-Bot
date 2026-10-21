#!/usr/bin/env python3
"""selftest_filterteam.py: the filter team's report cards (filter_team.py) on made-up scored chunks (fake money only).

  python3 selftest_filterteam.py

Checks: one entry per coin (a coin in many scans counts once, at its mean), lone vetoes only (a coin thrown out by two bots is nobody's),
the lights (worse thrown-out coins: good; better: bad; mixed: warn; too few: idle), the Scorer's side flipped, chunks of another profile,
outside the window or scored before LEARN_FROM skipped, gates that are off in the profile leave the team, and the page section (empty state,
escaping, one card per bot plus the Scorer, no horizontal scroll classes needed).
"""
import random, sys
import memebot as M
M.apply_profile("2h")
import filter_team as FT
import report as R

FAILS = []


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


T0 = FT.LEARN_FROM + 86_400_000


def chunk(t0, coins, rule="m9-2h", scored=None):
    return {"t0": t0, "t": scored if scored is not None else t0 + 2 * 3_600_000, "rule": rule, "coins": coins}


def coin(a, eur, why=(), rank=None, gone=False, mult=1.0):
    c = {"a": a, "eur": eur, "why": list(why), "pass": not why, "gone": gone, "mult": mult}
    if rank:
        c["rank"] = rank
    return c


def main():
    rng = random.Random(3)
    t = FT.Team("m9-2h", since=T0 - 1)
    # 40 scans: 30 passers per scan (the same 60 coins over and over), 30 lone "liq" vetoes much worse, 30 lone "mc" vetoes a bit better,
    # 30 lone "crash" vetoes mixed, 10 coins thrown out by two bots, 5 lone "copy" vetoes (too few)
    for k in range(40):
        t0 = T0 + k * 3_600_000
        cs = [coin("P%d" % ((k + i) % 60), rng.uniform(-6, 2), rank=(i + 1)) for i in range(30)]
        cs += [coin("L%d" % ((k + i) % 60), rng.uniform(-20, -14), ("liq",), gone=i % 2 == 0, mult=0.01 if i % 2 == 0 else 0.2) for i in range(30)]
        cs += [coin("C%d" % ((k + i) % 60), rng.uniform(-1, 4), ("mc",)) for i in range(30)]
        cs += [coin("K%d" % ((k + i) % 60), rng.uniform(-9, 5), ("crash",)) for i in range(30)]
        cs += [coin("X%d" % i, -20.0, ("liq", "mc")) for i in range(10)]
        cs += [coin("Y%d" % i, -20.0, ("copy",)) for i in range(5)]
        t.feed(chunk(t0, cs))
    # skipped: another profile, before the window, scored before LEARN_FROM, junk
    t.feed(chunk(T0 + 1, [coin("Z1", -20.0, ("mc",))], rule="m8"))
    t.feed(chunk(T0 - 7_200_000, [coin("Z2", -20.0, ("mc",))]))
    t.feed(chunk(T0 + 2, [coin("Z3", -20.0, ("mc",))], scored=FT.LEARN_FROM - 1))
    t.feed("junk")
    t.feed(chunk(T0 + 3, ["junk", {"a": "Z4"}, coin("", -20.0, ("mc",))]))
    seen = {}
    for k in range(40):
        for i in range(30):
            seen["P%d" % ((k + i) % 60)] = seen.get("P%d" % ((k + i) % 60), 0) + 1
    check(len(t.passed) == 60 and all(t.passed[a][1] == n for a, n in seen.items()), "one entry per passer coin, its scans counted (%d coins)" % len(t.passed))
    check(len(t.alone["liq"]) == 60 and len(t.alone["size"]) == 60 and "X0" not in t.alone["liq"] and "X0" not in t.alone["size"],
          "lone vetoes per bot; a coin thrown out by two bots is nobody's")
    check(not any(z in acc for acc in [t.passed] + list(t.alone.values()) for z in ("Z1", "Z2", "Z3", "Z4")),
          "chunks of another profile, before the window, scored before LEARN_FROM, junk and coins without an address are skipped")
    check(len(t.t0s) == 41 and t.last["t0"] == T0 + 39 * 3_600_000 and t.last["alone"].get("liq") == 30, "scans counted; the newest scan's lone vetoes per bot")
    rep = FT.report(t, FT.active_tags())
    by = {c["id"]: c for c in rep["bots"]}
    check(by["liq"]["light"] == "good" and by["liq"]["hi"] < 0 and by["liq"]["zero"] == 1.0, "a bot whose thrown-out coins did worse earns its place; a coin that went to zero in any scan counts as zero (%s, zero %s)" % (by["liq"]["light"], by["liq"]["zero"]))
    check(by["size"]["light"] == "bad" and by["size"]["lo"] > 0, "a bot whose thrown-out coins did better is red (%s)" % by["size"]["light"])
    check(by["chart"]["light"] in ("warn", "bad") and by["chart"]["lo"] is not None, "a mixed bot has an interval (%s %.2f..%.2f)" % (by["chart"]["light"], by["chart"]["lo"], by["chart"]["hi"]))
    check(by["fake"]["light"] == "idle" and by["fake"]["diff"] is None and by["fake"]["n"] == 5, "fewer than %d coins: idle, no verdict" % FT.MIN_COINS)
    check("flow" not in by and "liqmc" not in [x["tag"] for x in by["liq"]["tags"]] if M.GATE_MAX_LIQMC is None else "flow" not in by,
          "gates that are off in the 2h profile leave the team (Buyer Counter)")
    sc = rep["scorer"]
    check(sc["n"] == 40 and sc["light"] in ("good", "bad", "warn"), "the Scorer compares its picks (rank 1) with the other passers (%d coins, %s)" % (sc["n"], sc["light"]))
    # the Scorer's side is flipped: picks that do better are good
    t2 = FT.Team("m9-2h")
    for k in range(30):
        t2.feed(chunk(T0 + k * 3_600_000, [coin("A%d" % k, 5.0 + k % 3, rank=1)] + [coin("B%d_%d" % (k, i), -5.0 - i % 3, rank=i + 2) for i in range(3)]))
    check(FT.report(t2)["scorer"]["light"] == "good", "the Scorer is green when its picks beat the other passers")
    lo, hi = FT.boot_diff([1.0] * 30, [1.0] * 30)
    check(lo == hi == 0.0, "the bootstrap of two equal sides is 0")
    # the page
    html = FT.section({"team": rep}, R)
    check(html.count('class="ftb ') == len(rep["bots"]) + 1 and "<h2>Filter team</h2>" in html and "earns its place" in html and "throws away better coins" in html,
          "the section: one card per bot plus the Scorer, the lights in words")
    check("June/July, market cap" in html and "June/July, crash" in html and "liquidity share" not in html,
          "the long-history check stands on the Size Gauge and the Chart Scanner; the switched-off liquidity share is gone")
    empty = FT.section({"team": None}, R)
    check("<h2>Filter team</h2>" in empty and "priced again 2 hours later" in empty, "before the first priced scan: one sentence")
    bad = dict(rep, bots=[dict(rep["bots"][0], name="<b>x</b>", job='"j"')])
    check("<b>x</b>" not in FT.section({"team": bad}, R) and "&lt;b&gt;x&lt;/b&gt;" in FT.section({"team": bad}, R), "names are escaped")
    print("\n%s" % ("ALL GREEN" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
