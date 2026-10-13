#!/usr/bin/env python3
"""Overlap of the instant-pool trap with the other hard traps (early-list coins). Usage: venv/bin/python -I overlap.py <out dir>"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import E, v, HARD
out = []
ins = HARD["instant pool (< 60 s after mint)"]; br = HARD["brand / AI / celebrity name"]; bv = HARD["3000+ buys in the first hour"]
rw = HARD["rugger wallets (sw.avg <= -7 or 3+ holders in earlier rugs)"]
for nm, f2 in (("brand", br), ("botvol", bv), ("rugger", rw)):
    t = collections.defaultdict(lambda: [0, 0])
    for r in E:
        y = r["out"].get("rug1h")
        if y is None or v(r, "instantPool") is None:
            continue
        k = (bool(ins(r)), bool(f2(r)))
        t[k][0] += 1
        t[k][1] += y
    out.append(nm + ": " + "  ".join("%s/%s %d%% of %d" % ("instant" if a else "curve", nm if b else "no-" + nm, 100 * x[1] / x[0], x[0]) for (a, b), x in sorted(t.items())))
for lab, inst in (("curve (>= 60 s) & no other hard trap", 0.0), ("instant & no other hard trap", 1.0)):
    t = [r for r in E if v(r, "instantPool") == inst and not br(r) and not bv(r) and not rw(r) and r["out"].get("rug1h") is not None]
    out.append("%s: rug1h %d of %d, win1h %d" % (lab, sum(r["out"]["rug1h"] for r in t), len(t), sum(bool(r["out"].get("win1h")) for r in t)))
print("\n".join(out))
open(os.path.join(sys.argv[1], "overlap.txt"), "w").write("\n".join(out) + "\n")
