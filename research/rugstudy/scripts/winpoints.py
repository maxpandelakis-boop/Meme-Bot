#!/usr/bin/env python3
"""Equal-weight upside points (sign only, nothing fitted) for the 2x question, scored per half. Usage: venv/bin/python -I winpoints.py <out dir>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import L, S, E, PY, v
from recommend import pts
from stats import auc, pct
UP = [("+ X link", 1, lambda r: v(r, "x") == 1.0), ("+ launched off a tweet", 1, lambda r: v(r, "vt.tweet") == 1.0),
      ("+ on 3+ source lists", 1, lambda r: (v(r, "srcN") or 0) >= 3),
      ("- RugCheck holder correlation / insider network", -1, lambda r: v(r, "rcn.cluster_any") == 1.0),
      ("- creator still holds > 5%", -1, lambda r: (v(r, "rc.creator") or 0) > 5),
      ("- market cap >= $500k at < 1 h", -1, lambda r: (v(r, "mc") or 0) >= 500000),
      ("- liquidity < 15% of market cap", -1, lambda r: v(r, "liqMc") is not None and v(r, "liqMc") < 0.15),
      ("- brand / AI / celebrity name", -1, lambda r: v(r, "own.brand_name") == 1.0)]
up = lambda r: sum(p for _, p, f in UP if f(r))
out = ["upside points: " + "; ".join(n for n, _, _ in UP)]
for c, rows, wk, rk in (("L", L, "win1h", "rug1h"), ("E", E, "win1h", "rug1h"), ("S", S, "win2h", "rug2h"), ("P", PY, "win1h", "rug1h")):
    runs = sorted({r["rid"] for r in rows}); cut = runs[len(runs) // 2]
    line = "%s:" % c
    for half, hf in (("1st", lambda r: r["rid"] < cut), ("2nd", lambda r: r["rid"] >= cut)):
        yy = [(up(r), r["out"].get(wk)) for r in rows if hf(r) and r["out"].get(wk) is not None]
        line += "  %s half AUC %.3f (n=%d, %d winners)" % (half, auc([s for s, _ in yy], [t for _, t in yy]), len(yy), sum(t for _, t in yy))
    out.append(line)
    for nm, f in (("upside >= 2", lambda r: up(r) >= 2), ("upside >= 2 and trap points <= 0", lambda r: up(r) >= 2 and pts(r) <= 0),
                  ("upside <= 0", lambda r: up(r) <= 0), ("all", lambda r: True)):
        a = [r for r in rows if f(r) and r["out"].get(wk) is not None]
        b = [r for r in rows if f(r) and r["out"].get(rk) is not None]
        out.append("     %-36s n=%4d  %s %s   %s %s" % (nm, len(a), wk, pct(sum(r["out"][wk] for r in a) / len(a)) if a else "-", rk, pct(sum(r["out"][rk] for r in b) / len(b)) if b else "-"))
print("\n".join(out))
open(os.path.join(sys.argv[1], "winpoints.txt"), "w").write("\n".join(out) + "\n")
