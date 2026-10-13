#!/usr/bin/env python3
"""The recommended radar trap points (hand-set from steps 2-6), scored on every cohort: AUC and rug / 2x rates per band, both halves.
Usage: venv/bin/python -I recommend.py <out dir> -> recommend.txt, recommend.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import L, S, E, PY, v
from stats import Boot, pct, fx, auc

POINTS = [  # (key, points, test)
    ("instant_pool", 3, lambda r: v(r, "instantPool") == 1.0),
    ("rugger_wallets", 3, lambda r: (v(r, "sw.avg") is not None and v(r, "sw.avg") <= -7) or (v(r, "own.holders_in_earlier_rug") or 0) >= 3),
    ("rugcheck_danger", 3, lambda r: v(r, "rcn.danger_any") == 1.0),
    ("bot_volume_3000_buys_1h", 2, lambda r: (v(r, "buys1") or 0) >= 3000),
    ("brand_name", 2, lambda r: v(r, "own.brand_name") == 1.0),
    ("no_rugcheck_report", 2, lambda r: not v(r, "rc.report")),
    ("no_socials", 1, lambda r: v(r, "socN") is not None and v(r, "socN") <= 0),
    ("pumping_20pct_5m", 1, lambda r: (v(r, "m5") or 0) >= 20),
    ("age_under_5min", 1, lambda r: v(r, "ageMin") is not None and v(r, "ageMin") < 5),
    ("holder_cluster", 1, lambda r: v(r, "rcn.cluster_any") == 1.0),
    ("creator_sold", 1, lambda r: (v(r, "dev.sold") or 0) > 0),
    ("good_x_and_paid", -1, lambda r: v(r, "x") == 1.0 and v(r, "ds.paid") == 1.0),
    ("good_tweet", -1, lambda r: v(r, "vt.tweet") == 1.0),
    ("good_3_lists", -1, lambda r: (v(r, "srcN") or 0) >= 3),
]


def pts(r):
    hard = sum(p for k, p, f in POINTS if p >= 3 and f(r))
    s = sum(p for k, p, f in POINTS if f(r))
    return max(s, hard)          # good signs never cancel a hard trap


def main():
    REP = []
    say = REP.append
    RES = {}
    for c, rows, yk, wk in (("L", L, "rug1h", "win1h"), ("E", E, "rug1h", "win1h"), ("S", S, "rug2h", "win2h"), ("P", PY, "rug1h", "win1h")):
        runs = sorted({r["rid"] for r in rows})
        cut = runs[len(runs) // 2]
        bt = Boot([r["rid"] for r in rows])
        say("## %s" % c)
        RES[c] = {}
        for key in (yk, wk):
            for half, hf in (("1st half", lambda r: r["rid"] < cut), ("2nd half", lambda r: r["rid"] >= cut), ("all", lambda r: True)):
                yy = [(pts(r), r["out"].get(key)) for r in rows if hf(r) and r["out"].get(key) is not None]
                a = auc([s if "rug" in key else -s for s, _ in yy], [t for _, t in yy])
                RES[c]["auc.%s.%s" % (key, half)] = a
                say("  AUC %-6s %-8s %s (n=%d)" % (key, half, fx(a, 3), len(yy)))
        for nm, lo, hi in (("0 or less (eligible as good)", -9, 0), ("1-2 (yellow)", 1, 2), ("3+ (red / hidden)", 3, 99)):
            line = "  %-30s" % nm
            for key in (yk, wk):
                n, k = bt.per_run(rows, lambda r, lo=lo, hi=hi: lo <= pts(r) <= hi, lambda r, key=key: r["out"].get(key))
                rt = bt.rate(n, k)
                RES[c]["%s.%s" % (nm, key)] = rt
                line += "  %s %s of %d [%s-%s]" % (key, pct(rt["rate"]), rt["n"], pct(rt["lo"]), pct(rt["hi"])) if rt else ""
            say(line)
    json.dump({"points": [(k, p) for k, p, _ in POINTS], "res": RES}, open(os.path.join(sys.argv[1], "recommend.json"), "w"), indent=1, default=str)
    open(os.path.join(sys.argv[1], "recommend.txt"), "w").write("\n".join(REP) + "\n")
    print("\n".join(REP))


if __name__ == "__main__":
    main()
