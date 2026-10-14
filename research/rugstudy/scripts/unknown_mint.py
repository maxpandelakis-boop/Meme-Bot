#!/usr/bin/env python3
"""Coins whose mint time is unknown (mostly not pump.fun): dex, address suffix and the LP-related RugCheck flags vs rug1h.
Usage: venv/bin/python -I unknown_mint.py <out dir>"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import E, v
out = []
U = [r for r in E if v(r, "instantPool") is None and r["out"].get("rug1h") is not None]
t = collections.defaultdict(lambda: [0, 0])
for r in U:
    k = (str(r["sig"].get("dex")), "pump-suffix" if r["a"].endswith("pump") else "other-suffix")
    t[k][0] += 1
    t[k][1] += r["out"]["rug1h"]
out.append("mint time unknown, by dex / address: " + "; ".join("%s %s: %d of %d rug" % (k[0], k[1], x[1], x[0]) for k, x in sorted(t.items(), key=lambda kv: -kv[1][0])))
for nm, f in (("RugCheck LP unlocked", lambda r: v(r, "rcn.lp_unlocked") == 1.0), ("RugCheck LP locked < 90%", lambda r: v(r, "rc.lp") is not None and v(r, "rc.lp") < 90),
              ("RugCheck few LP providers", lambda r: v(r, "rcn.few_lp_providers") == 1.0), ("RugCheck danger", lambda r: v(r, "rcn.danger_any") == 1.0),
              ("no RugCheck report", lambda r: not v(r, "rc.report"))):
    a = [r["out"]["rug1h"] for r in U if f(r)]
    b = [r["out"]["rug1h"] for r in U if not f(r)]
    out.append("  %-28s with: %d of %d rug | without: %d of %d" % (nm, sum(a), len(a), sum(b), len(b)))
print("\n".join(out))
open(os.path.join(sys.argv[1], "unknown_mint.txt"), "w").write("\n".join(out) + "\n")
