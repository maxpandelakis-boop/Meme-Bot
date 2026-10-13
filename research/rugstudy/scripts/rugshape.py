#!/usr/bin/env python3
"""How the rugs looked (early list, p60): LP pull (liquidity gone, price kept) vs sell-off (liquidity falls with the price, constant
product) and where the liquidity ended. Usage: python3 -I rugshape.py <results db dir> <out dir>"""
import glob, json, math, os, sys, statistics
DB, OUT = sys.argv[1:3]
rows = []
for fn in sorted(glob.glob(os.path.join(DB, "memeearly", "*.json"))):
    d = json.load(open(fn))
    for c in d["coins"]:
        p = c.get("p60")
        if not p or not c.get("px") or not c.get("liq"):
            continue
        inst = None if not c.get("minted") else (c["born"] - c["minted"] < 60000)
        if p.get("gone"):
            rows.append((inst, "gone", None, None, c["liq"]))
            continue
        r = (p.get("px") or 0) / c["px"]
        l1 = p.get("liq") or 0
        if l1 < 1000:
            rows.append((inst, "LP gone (liq < $1k)", r, l1, c["liq"]))
        elif r < 0.1:
            q = (l1 / c["liq"]) / math.sqrt(r)
            rows.append((inst, "sell-off (-90%%+, liq/sqrt(px) = %.1f)" % round(q, 1) if q < 3 else "odd", r, l1, c["liq"]))
out = []
for kind in ("instant", "curve", "unknown"):
    sel = [x for x in rows if (x[0] is True and kind == "instant") or (x[0] is False and kind == "curve") or (x[0] is None and kind == "unknown")]
    sell = [x for x in sel if x[1].startswith("sell-off")]
    lp = [x for x in sel if x[1].startswith("LP gone")]
    out.append("%-8s rugs at about 1 h: %d sell-offs, %d LP gone, %d gone from DexScreener" % (kind, len(sell), len(lp), sum(1 for x in sel if x[1] == "gone")))
    if sell:
        out.append("         sell-offs: liquidity at listing median $%s -> at 1 h median $%s; price multiple median %.4f" % (
            "{:,.0f}".format(statistics.median(x[4] for x in sell)), "{:,.0f}".format(statistics.median(x[3] for x in sell)), statistics.median(x[2] for x in sell)))
print("\n".join(out))
open(os.path.join(OUT, "rugshape.txt"), "w").write("\n".join(out) + "\n")
