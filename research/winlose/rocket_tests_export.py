"""The three rocket hunter tests of 22 Oct (PREREG-EARLY-EXIT-2026-10-22.md) for the app (fake money only): rocket_tests.json next to
page_rocket.py, from the deciding runs (early_entry_live.json, rocket_exits_live.json, exit_model.json in the scratch folder).
usage: python3 research/winlose/rocket_tests_export.py <scratch>"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
S = sys.argv[1]
E = json.load(open(os.path.join(S, "early_entry_live.json")))
X = json.load(open(os.path.join(S, "rocket_exits_live.json")))
K = json.load(open(os.path.join(S, "exit_model.json")))


def seedmean(vn, cut):
    r = E["res"][vn]
    a = [r[s][cut]["all"] for s in r]
    return {"coins": round(float(np.mean([x["coins"] for x in a]))), "avg": round(float(np.mean([x["avg"] for x in a])), 2),
            "inProfitOf10": round(float(np.mean([x["inProfitOf10"] for x in a])), 1), "x10": round(float(np.mean([x["x10"] for x in a])), 1),
            "sim": round(float(np.mean([(r[s][cut]["sim"] or {}).get("pProfit") or 0 for s in r])), 1)}


out = {"v": 1, "made": "2026-10-22", "src": "research/winlose/PREREG-EARLY-EXIT-2026-10-22.md, EARLY-EXIT-2026-10-22.md",
       "history": {c: seedmean("V30", c) for c in ("0.005", "0.01", "0.02")},
       "early": {"choice": E["choice"], "variants": {vn: {k: row[k] for k in ("coins", "avg", "sim", "x10") if k in row} | {"holds": bool(row.get("holds"))}
                                                       for vn, row in E["table"].items()}},
       "exits": {"rules": len(X["rules"]), "choice": X["choice"], "beatEarlyAll3": X["beatEarlyAll3"],
                 "bestHindsight": X["infoBestPerFamily"]["F"]},
       "ki": {"holds": K["holds"], "ki": K["table"]["0.005"]["ki"]["all"], "ruleA": K["table"]["0.005"]["ra"]["all"],
              "kiSim": (K["table"]["0.005"]["ki"]["sim"] or {}).get("pProfit"), "ruleASim": (K["table"]["0.005"]["ra"]["sim"] or {}).get("pProfit"),
              "ki1": K["table"]["0.01"]["ki"]["all"], "ruleA1": K["table"]["0.01"]["ra"]["all"]}}
fn = os.path.join(HERE, "..", "..", "rocket_tests.json")
json.dump(out, open(fn, "w"), indent=1)
print(json.dumps(out, indent=1)[:1500])
