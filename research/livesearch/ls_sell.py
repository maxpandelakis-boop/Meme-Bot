#!/usr/bin/env python3
"""ls_sell.py: family F1 of the live-data rule search (PREREG-LIVESEARCH-2026-11-04.md): sell rules on the Pick account's buys,
replayed by shadow.replay on the 12-hour minute paths the shadow job keeps, the Pick's paper fees (shadow.money), 50 EUR a buy.
Cross-check (report only): the same rules with hours <= 6 on the Learning Pick's 6-hour paths.

  python3 ls_sell.py --data <ls_build out> --out <dir>
"""
import argparse, itertools, json, os, pickle, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import memebot as M
import shadow as SH

SPLIT = 1793404800000          # 31 Oct 2026 00:00 UTC: FIT before, CHECK from it on
CHART_KEYS = ("CHART_STOP", "CHART_TRAIL", "CHART_ARM", "CHART_DROP", "CHART_DROP_MIN", "HOLD_MAX_H")
BASE = {k: getattr(M, k) for k in CHART_KEYS}


def grid():
    rules = []
    stops = [("stop", None), ("stop", .10), ("stop", .15), ("stop", .20), ("stop", .25), ("stop", .30), ("stop", .40), ("stop", .50),
             ("trail", .10), ("trail", .15), ("trail", .20), ("trail", .30)]
    for (kind, v), tg, h, half in itertools.product(stops, (1.3, 1.5, 2.0, 2.5, 3.0, 5.0, 11.0, None), (1, 2, 3, 4, 6, 8, 12), (None, 1.5, 2.0)):
        if half and tg is not None and tg <= half:
            continue
        r = {"stop": v if kind == "stop" else None, "target": tg, "hours": float(h)}
        if kind == "trail":
            r["stop"], r["trail"] = v, v
        if half:
            r["half"] = half
        r["id"] = "S%s%s-T%s-H%g%s" % ("t" if kind == "trail" else "", "-" if v is None else int(round(100 * v)), "-" if tg is None else "%g" % tg, h,
                                       "-h%g" % half if half else "")
        rules.append(r)
    for arm, tr, dr, dm, fl, h in itertools.product((1.2, 1.3, 1.5, 2.0), (.10, .15, .20, .25), (None, .10, .15, .20, .30), (15, 30, 60), (.30, .50), (3, 6, 12)):
        if dr is None and dm != 30:
            continue
        rules.append({"id": "X-a%g-t%d-d%s-m%d-f%d-H%d" % (arm, round(100 * tr), "-" if dr is None else round(100 * dr), dm, round(100 * fl), h),
                      "chart": True, "stop": fl, "target": 1.0 + M.HOLD_TP, "hours": float(h),
                      "cp": {"CHART_STOP": fl, "CHART_TRAIL": tr, "CHART_ARM": arm, "CHART_DROP": dr if dr is not None else 0.999,
                             "CHART_DROP_MIN": dm, "HOLD_MAX_H": float(h)}})
    rules.append({"id": "K", "stop": 0.30, "target": 11.0, "hours": 6.0})
    rules.append({"id": "X", "chart": True, "stop": M.CHART_STOP, "target": 1.0 + M.HOLD_TP, "hours": M.HOLD_MAX_H, "cp": dict(BASE)})
    return rules


def run_rule(args):
    rule, items = args
    cp = rule.get("cp")
    if cp:
        for k, v in cp.items():
            setattr(M, k, v)
    out = []
    try:
        for p, doc in items:
            r = SH.replay(doc, rule)
            out.append(None if r is None else SH.money(p, r["sales"]))
    finally:
        for k, v in BASE.items():
            setattr(M, k, v)
    return rule["id"], out


def lern_pos(d):
    """A Learning Pick doc as a paper position for shadow.money (the Pick's fees)."""
    return {"grp": "hold", "paper": M.PAPER_RULE, "ticket": 50.0, "px": d.get("px"), "entryAt": d.get("entryAt")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pick = pickle.load(open(os.path.join(a.data, "pick.pkl"), "rb"))
    lern = pickle.load(open(os.path.join(a.data, "lern.pkl"), "rb"))
    items = [(r["p"], r["shadow"]) for r in pick if r["shadow"]]
    t_pick = [int(SH.entry_of(r["p"])) for r in pick if r["shadow"]]
    litems = [(lern_pos(d), d) for d in lern if isinstance(d.get("c"), list) and d.get("cpx")]
    t_lern = [int(d["entryAt"]) for d in lern if isinstance(d.get("c"), list) and d.get("cpx")]
    rules = grid()
    print("rules", len(rules), "pick paths", len(items), "lern paths", len(litems), flush=True)
    with Pool(4) as pool:
        res = dict(pool.map(run_rule, [(r, items) for r in rules], chunksize=8))
        short = [r for r in rules if r["hours"] <= 6]
        lres = dict(pool.map(run_rule, [(r, litems) for r in short], chunksize=8))
    os.makedirs(a.out, exist_ok=True)
    pickle.dump({"rules": rules, "pick": res, "t_pick": t_pick, "lern": lres, "t_lern": t_lern,
                 "sym": [r["p"].get("sym") for r in pick if r["shadow"]]}, open(os.path.join(a.out, "f1.pkl"), "wb"))


if __name__ == "__main__":
    main()
