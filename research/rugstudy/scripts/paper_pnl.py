#!/usr/bin/env python3
"""Paper new-launch positions since the restart by recommended trap band (closed positions; 3 fake EUR each).
Usage: venv/bin/python -I paper_pnl.py <out dir>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import pts
from rules import PY
out = []
closed = [r for r in PY if r["why"] != "open" and r.get("exitEur") is not None]
for nm, lo, hi in (("0 or less", -9, 0), ("1-2", 1, 2), ("3+", 3, 99), ("all", -9, 99)):
    a = [r for r in closed if lo <= pts(r) <= hi]
    if not a:
        continue
    res = sum(r["exitEur"] - (r["ticket"] or 3) for r in a)
    whys = {}
    for r in a:
        whys[r["why"]] = whys.get(r["why"], 0) + 1
    out.append("%-10s %3d closed positions, result %+7.2f fake EUR (%+.2f each = %+.0f%%), exits: %s" % (
        nm, len(a), res, res / len(a), 100 * res / len(a) / 3, ", ".join("%s %d" % kv for kv in sorted(whys.items()))))
print("\n".join(out))
open(os.path.join(sys.argv[1], "paper_pnl.txt"), "w").write("\n".join(out) + "\n")
