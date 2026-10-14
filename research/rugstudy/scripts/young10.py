#!/usr/bin/env python3
"""Rule D (no hard trap, RugCheck-checked, 0-1 soft warning) inside the radar's own population: coins under 10 minutes old.
Usage: venv/bin/python -I young10.py <out dir>"""
import json, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import HARD, SOFT, GOOD, hard, soft, checked, v, mult1h, L, S, E, PY
from stats import Boot, pct
out = []
for c, rows, yk, wk, agek in (("L", L, "rug1h", "win1h", "listAgeMin"), ("E", E, "rug1h", "win1h", "listAgeMin"), ("S", S, "rug2h", "win2h", "ageMin")):
    y10 = [r for r in rows if v(r, agek) is not None and v(r, agek) < 10]
    runs = sorted({r["rid"] for r in rows})
    bt = Boot([r["rid"] for r in y10])
    out.append("## %s: %d coins under 10 min at listing, from %d scans (of %d)" % (c, len(y10), len({r['rid'] for r in y10}), len(runs)))
    for nm, fn in (("any hard trap", lambda r: hard(r) >= 1), ("instant pool", HARD["instant pool (< 60 s after mint)"]),
                   ("no hard trap, not checked", lambda r: hard(r) == 0 and not checked(r)),
                   ("rule D: no hard trap, checked, 0-1 soft", lambda r: hard(r) == 0 and checked(r) and soft(r) <= 1),
                   ("all under 10 min", lambda r: True)):
        sel = [r for r in y10 if fn(r)]
        n1, k1 = bt.per_run(y10, fn, lambda r: r["out"].get(yk))
        n2, k2 = bt.per_run(y10, fn, lambda r: r["out"].get(wk))
        a, b = bt.rate(n1, k1), bt.rate(n2, k2)
        per = collections.Counter(r["rid"] for r in sel)
        scans_with = len(per)
        out.append("  %-42s n=%4d  %s %s [%s-%s]  %s %s [%s-%s]  scans with one: %d of %d" % (
            nm, len(sel), yk, pct(a["rate"], 0) if a else "-", pct(a["lo"], 0) if a else "-", pct(a["hi"], 0) if a else "-",
            wk, pct(b["rate"], 0) if b else "-", pct(b["lo"], 0) if b else "-", pct(b["hi"], 0) if b else "-", scans_with, len(runs)))
print("\n".join(out))
open(os.path.join(sys.argv[1], "young10.txt"), "w").write("\n".join(out) + "\n")
