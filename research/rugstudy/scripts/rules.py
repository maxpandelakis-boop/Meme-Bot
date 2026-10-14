#!/usr/bin/env python3
"""Rug and winner study, step 6: the radar's hard traps / soft warnings as rules, checked per half (L, E, S, P), with the 1 h
hold multiple (memeyoung 1 h mark; dead pools count 0) as the money view.
Usage: venv/bin/python -I rules.py <out dir> -> rules.txt, rules.json"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import Boot, pct, fx

OUT = sys.argv[1]
REP = []
say = REP.append


def load(name):
    with open(os.path.join(OUT, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


L, S, P = load("listings"), load("snapyoung"), load("positions")
E = [r for r in L if r["inEarly"]]
PY = [r for r in P if r["grp"] == "young"]


def v(r, k):
    x = r["sig"].get(k)
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


HARD = {
    "instant pool (< 60 s after mint)": lambda r: v(r, "instantPool") == 1.0,
    "rugger wallets (sw.avg <= -7 or 3+ holders in earlier rugs)": lambda r: (v(r, "sw.avg") is not None and v(r, "sw.avg") <= -7) or (v(r, "own.holders_in_earlier_rug") or 0) >= 3,
    "brand / AI / celebrity name": lambda r: v(r, "own.brand_name") == 1.0,
    "3000+ buys in the first hour": lambda r: (v(r, "buys1") or 0) >= 3000,
    "RugCheck danger flag": lambda r: v(r, "rcn.danger_any") == 1.0,
}
SOFT = {
    "no socials": lambda r: v(r, "socN") is not None and v(r, "socN") <= 0,
    "RugCheck holder cluster": lambda r: v(r, "rcn.cluster_any") == 1.0,
    "creator sold": lambda r: (v(r, "dev.sold") or 0) > 0,
    "up 20%+ in 5 min": lambda r: (v(r, "m5") or 0) >= 20,
}
GOOD = lambda r: (v(r, "x") == 1.0 and v(r, "ds.paid") == 1.0) or v(r, "vt.tweet") == 1.0 or (v(r, "srcN") or 0) >= 3
hard = lambda r: sum(1 for f in HARD.values() if f(r))
soft = lambda r: sum(1 for f in SOFT.values() if f(r))
checked = lambda r: bool(v(r, "rc.report"))

RULES = [
    ("A. any hard trap", lambda r: hard(r) >= 1),
    ("B. no hard trap, not RugCheck-checked", lambda r: hard(r) == 0 and not checked(r)),
    ("C. no hard trap, checked, 2+ soft warnings", lambda r: hard(r) == 0 and checked(r) and soft(r) >= 2),
    ("D. no hard trap, checked, 0-1 soft warning", lambda r: hard(r) == 0 and checked(r) and soft(r) <= 1),
    ("E. = D + a good sign (X+paid, tweet, 3+ lists)", lambda r: hard(r) == 0 and checked(r) and soft(r) <= 1 and GOOD(r)),
    ("all", lambda r: True),
]


def mult1h(r):
    o = r["out"]
    if o.get("e_p60_state") in ("dead", "gone"):
        return 0.0
    m = o.get("y_1h")
    if m is None:
        m = o.get("e_p60")
    if m is None:
        return None
    return min(m, 30.0)


def main():
    RES = {}
    for c, rows, yk, wk in (("L", L, "rug1h", "win1h"), ("E", E, "rug1h", "win1h"), ("S", S, "rug2h", "win2h"), ("P", PY, "rug1h", "win1h")):
        bt = Boot([r["rid"] for r in rows])
        runs = sorted({r["rid"] for r in rows})
        cut = runs[len(runs) // 2]
        say("")
        say("## %s (%d coins, halves split at %s)" % (c, len(rows), cut))
        say("%-50s %6s  %-30s %-30s %-24s %s" % ("rule", "n", yk + " 1st | 2nd half", wk + " 1st | 2nd half", "all: rug / win [95% CI]", "1h hold multiple mean / median"))
        RES[c] = {}
        for nm, fn in RULES:
            sel = [r for r in rows if fn(r)]
            cells = []
            for key in (yk, wk):
                parts = []
                for hf in (lambda r: r["rid"] < cut, lambda r: r["rid"] >= cut):
                    ys = [r["out"].get(key) for r in sel if hf(r) and r["out"].get(key) is not None]
                    parts.append("%s/%d" % (pct(sum(ys) / len(ys), 0), len(ys)) if ys else "-")
                cells.append(" | ".join(parts))
            n1, k1 = bt.per_run(rows, fn, lambda r: r["out"].get(yk))
            n2, k2 = bt.per_run(rows, fn, lambda r: r["out"].get(wk))
            a, b = bt.rate(n1, k1), bt.rate(n2, k2)
            ms = sorted(m for m in (mult1h(r) for r in sel) if m is not None) if c != "S" else sorted(min(r["out"]["mult"], 30) for r in sel if r["out"].get("mult") is not None)
            mm = ("%.2f / %.2f (n=%d)" % (sum(ms) / len(ms), ms[len(ms) // 2], len(ms))) if ms else "-"
            RES[c][nm] = {"n": len(sel), "rug": a, "win": b, "multMean": (sum(ms) / len(ms)) if ms else None, "multMedian": ms[len(ms) // 2] if ms else None}
            say("%-50s %6d  %-30s %-30s %-24s %s" % (nm, len(sel), cells[0], cells[1],
                                                    ("%s [%s-%s] / %s" % (pct(a["rate"], 0), pct(a["lo"], 0), pct(a["hi"], 0), pct(b["rate"], 0))) if a and b else "-", mm))
        say("hard traps, one by one (%s):" % yk)
        for nm, fn in HARD.items():
            n1, k1 = bt.per_run(rows, fn, lambda r: r["out"].get(yk))
            n0, k0 = bt.per_run(rows, lambda r, fn=fn: not fn(r), lambda r: r["out"].get(yk))
            cmp_ = bt.compare(n1, k1, n0, k0)
            if cmp_ and cmp_["n1"]:
                say("   %-58s %s of %d vs %s of %d, lift %s [%s-%s]" % (nm, pct(cmp_["r1"], 0), cmp_["n1"], pct(cmp_["r0"], 0), cmp_["n0"], fx(cmp_["lift"]), fx(cmp_["llo"]), fx(cmp_["lhi"])))
    json.dump(RES, open(os.path.join(OUT, "rules.json"), "w"), indent=1, default=str)
    open(os.path.join(OUT, "rules.txt"), "w").write("\n".join(REP) + "\n")
    print("\n".join(REP))


if __name__ == "__main__":
    main()
