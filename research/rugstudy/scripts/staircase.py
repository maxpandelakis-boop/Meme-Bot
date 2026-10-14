#!/usr/bin/env python3
"""Rug and winner study, step 4: the 'staircase chart' test (nexus_trades) on our stored minute-candle paths.
The first 15 minutes of each listed coin's 1 h path (memeyoung outs['1'].path, closes relative to the tip price) give the shape;
what happens in minutes 15-60 (relative to the minute-15 close) is the outcome. Only shapes with a rise can be staircases.
Usage: venv/bin/python -I staircase.py <results db dir> <out dir>"""
import glob, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import Boot, pct, fx

DB, OUT = sys.argv[1:3]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 15
rows = []
for fn in sorted(glob.glob(os.path.join(DB, "memeyoung", "*.json"))):
    rid = os.path.basename(fn)[:-5]
    d = json.load(open(fn))
    o = (d.get("outs") or {}).get("1") or {}
    for p in o.get("picks") or []:
        path = p.get("path")
        if not path:
            continue
        cs = [c for c in path if isinstance(c, list) and len(c) >= 5 and c[4] and c[4] > 0]
        early = [c for c in cs if c[0] <= W]
        late = [c for c in cs if W < c[0] <= 60]
        if len(early) < int(0.66 * W) or len(late) < 10 or early[0][0] > 2:
            continue
        closes = [c[4] for c in early]
        greens = sum(1 for c in early if c[4] > c[1]) / len(early)
        runmax, pull = closes[0], 0.0
        for x in closes:
            runmax = max(runmax, x)
            pull = max(pull, 1 - x / runmax)
        rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
        vol = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0
        ups = [r for r in rets if r > 0]
        # step regularity: coefficient of variation of the up-steps (small = machine-like equal steps)
        cv = (((sum((u - sum(ups) / len(ups)) ** 2 for u in ups) / len(ups)) ** 0.5) / (sum(ups) / len(ups))) if len(ups) >= 3 else None
        c15 = closes[-1]
        rise = c15 / closes[0] if closes[0] else None
        lmin = min(c[4] for c in late) / c15
        lmax = max(c[4] for c in late) / c15
        rows.append({"rid": rid, "sym": p.get("sym"), "rise": rise, "greens": greens, "pull": pull, "vol": vol, "cv": cv,
                     "rugAfter": lmin <= 0.1, "halfAfter": lmin <= 0.5, "winAfter": lmax >= 2.0, "upAfter": lmax >= 1.5})
bt = Boot([r["rid"] for r in rows])
REP = []
say = REP.append
say("# Staircase test on %d listed coins with a full minute path (first %d min = shape, minutes %d-60 = outcome vs the minute-%d close)" % (len(rows), W, W, W))
say("Note: staircase = rose >= 20% in the window, >= 70% green candles, deepest pullback under 5%.")
groups = [
    ("all", lambda r: True),
    ("rose >= 20% in the window", lambda r: r["rise"] >= 1.2),
    ("staircase (rise >= 20%, >= 70% green, pullback < 5%)", lambda r: r["rise"] >= 1.2 and r["greens"] >= 0.7 and r["pull"] < 0.05),
    ("rise >= 20% with a pullback >= 15% (organic-looking)", lambda r: r["rise"] >= 1.2 and r["pull"] >= 0.15),
    ("rise >= 20%, >= 60% green", lambda r: r["rise"] >= 1.2 and r["greens"] >= 0.6),
    ("rise >= 20%, pullback < 10%", lambda r: r["rise"] >= 1.2 and r["pull"] < 0.10),
    ("rise >= 20%, regular steps (cv < 0.8)", lambda r: r["rise"] >= 1.2 and r["cv"] is not None and r["cv"] < 0.8),
    ("flat (0.9-1.2)", lambda r: 0.9 <= r["rise"] < 1.2),
    ("falling (< 0.9)", lambda r: r["rise"] < 0.9),
]
say("%-55s %5s  %-26s %-26s %-26s" % ("shape in the first %d min" % W, "n", "-90%% after min %d" % W, "-50%% after min %d" % W, "2x after min %d" % W))
res = {}
for nm, fn in groups:
    line = "%-55s %5d  " % (nm, sum(1 for r in rows if fn(r)))
    res[nm] = {}
    for key in ("rugAfter", "halfAfter", "winAfter"):
        n, k = bt.per_run(rows, fn, lambda r: r[key])
        rt = bt.rate(n, k)
        res[nm][key] = rt
        line += "%-26s " % (("%s [%s-%s]" % (pct(rt["rate"], 0), pct(rt["lo"], 0), pct(rt["hi"], 0))) if rt else "-")
    say(line)
# staircase vs other risers
up = [r for r in rows if r["rise"] >= 1.2]
for key in ("rugAfter", "halfAfter", "winAfter"):
    n1, k1 = bt.per_run(up, lambda r: r["greens"] >= 0.7 and r["pull"] < 0.05, lambda r: r[key])
    n0, k0 = bt.per_run(up, lambda r: not (r["greens"] >= 0.7 and r["pull"] < 0.05), lambda r: r[key])
    c = bt.compare(n1, k1, n0, k0)
    if c:
        say("risers: staircase vs other risers, %s: %s of %d vs %s of %d, diff %+.0f pts [%+.0f..%+.0f], p=%.2f" % (
            key, pct(c["r1"], 0), c["n1"], pct(c["r0"], 0), c["n0"], 100 * c["diff"], 100 * c["dlo"], 100 * c["dhi"], c["p"]))
    res["staircase_vs_risers." + key] = c
json.dump(res, open(os.path.join(OUT, "staircase_w%d.json" % W), "w"), indent=1, default=str)
open(os.path.join(OUT, "staircase_w%d.txt" % W), "w").write("\n".join(REP) + "\n")
print("\n".join(REP))
