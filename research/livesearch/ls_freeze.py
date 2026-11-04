#!/usr/bin/env python3
"""ls_freeze.py: the selection of PREREG-LIVESEARCH-2026-11-04.md on the outputs of ls_sell.py (f1.pkl), ls_skip.py (f2.pkl) and
ls_buy.py (f3.pkl): per family the 50 best rules on FIT, the luck test (how they did on CHECK against all rules), and the candidates
(at most 3: among the 50 best on FIT, CHECK mean > 0 and > the family's yardstick on CHECK, best FIT first) -> CANDIDATES json.

  python3 ls_freeze.py --data <dir> --out research/livesearch/CANDIDATES-2026-11-04.json
"""
import argparse, json, os, pickle
import numpy as np

SPLIT = 1793404800000
TOP = 50


def rk(a):
    return np.argsort(np.argsort(a))


def luck(F, C, W, top):
    return {"rules": int(len(F)), "rankCorr": round(float(np.corrcoef(rk(F), rk(C))[0, 1]), 3),
            "top50ChkPos": round(float((C[top] > 0).mean()), 3), "allChkPos": round(float((C > 0).mean()), 3),
            "top50ChkMean": round(float(C[top].mean()), 3), "allChkMean": round(float(C.mean()), 3),
            "top50ChkPosWithoutBest": round(float((W[top] > 0).mean()), 3), "allChkPosWithoutBest": round(float((W > 0).mean()), 3)}


def f1(data):
    d = pickle.load(open(os.path.join(data, "f1.pkl"), "rb"))
    t = np.array(d["t_pick"])
    fit, chk = t < SPLIT, t >= SPLIT
    rules = [r for r in d["rules"] if all(v is not None for v in d["pick"][r["id"]])]
    V = np.array([d["pick"][r["id"]] for r in rules], dtype=float)
    F, C = V[:, fit].mean(1), V[:, chk].mean(1)
    W = np.array([(v[chk].sum() - v[chk].max()) / (chk.sum() - 1) for v in V])
    ids = [r["id"] for r in rules]
    iK, iX = ids.index("K"), ids.index("X")
    o = np.argsort(-F, kind="stable")
    top = o[:TOP]
    cands = [i for i in top if C[i] > 0 and C[i] > C[iX] and C[i] > C[iK]][:3]
    out = []
    for n, i in enumerate(cands, 1):
        r = {k: v for k, v in rules[i].items()}
        out.append({"id": "N%d" % n, "rule": r, "fitRank": int(np.nonzero(o == i)[0][0]) + 1, "nFit": int(fit.sum()), "fit": round(float(F[i]), 2),
                    "nChk": int(chk.sum()), "chk": round(float(C[i]), 2), "chkWithoutBest": round(float(W[i]), 2)})
    yard = {"K": {"fit": round(float(F[iK]), 2), "chk": round(float(C[iK]), 2)}, "X": {"fit": round(float(F[iX]), 2), "chk": round(float(C[iX]), 2)}}
    lern = {}
    for c in out:
        v = d["lern"].get(c["rule"]["id"])
        lern[c["id"]] = round(float(np.mean(v)), 2) if v and all(x is not None for x in v) else None
    return {"family": "F1 sell rules on the Pick's buys", "luck": luck(F, C, W, top), "yardstick": yard, "candidates": out,
            "lernCrossCheck": lern, "lernK": round(float(np.mean(d["lern"]["K"])), 2), "lernX": round(float(np.mean(d["lern"]["X"])), 2)}


def f2(data):
    d = pickle.load(open(os.path.join(data, "f2.pkl"), "rb"))
    rows = sorted(d["rows"], key=lambda r: -r["fit"])
    F = np.array([r["fit"] for r in rows]); C = np.array([r["chk"] for r in rows]); W = np.array([r["chkWob"] for r in rows])
    top = np.arange(min(TOP, len(rows)))
    b = d["base"]
    seen, cands = set(), []
    for i in top:
        r = rows[i]
        key = tuple(map(tuple, r["c"]))
        if key in seen:
            continue
        seen.add(key)
        if r["chk"] > 0 and r["chk"] > b["chk"]:
            cands.append((i, r))
    out = [{"id": "P%d" % n, "conds": [list(c) for c in r["c"]], "fitRank": int(i) + 1, "nFit": r["nFit"], "fit": round(r["fit"], 2), "nChk": r["nChk"],
            "chk": round(r["chk"], 2), "chkWithoutBest": round(r["chkWob"], 2)} for n, (i, r) in enumerate(cands[:3], 1)]
    return {"family": "F2 Pick buys to leave out (sold by the Sell bot, rule X)", "luck": luck(F, C, W, top), "yardstick": {"allBuys": b}, "candidates": out}


def f3(data):
    d = pickle.load(open(os.path.join(data, "f3.pkl"), "rb"))
    rows = [(("rule",) + s, v) for s, v in d["res"]] + [(("rank",) + s, v) for s, v in d["rank"]]
    rows = [(s, v) for s, v in rows if v[2] >= 1]
    rows.sort(key=lambda x: (-x[1][1], repr(x[0])))
    F = np.array([v[1] for _, v in rows]); C = np.array([v[3] for _, v in rows]); W = np.array([v[4] if v[2] > 1 else -1e9 for _, v in rows])
    gates = next(v for s, v in rows if s == ("rule", "gates", ()))
    top = np.arange(TOP)
    cands = [(i, rows[i]) for i in top if C[i] > 0 and C[i] > gates[3]][:3]
    out = []
    for n, (i, (s, v)) in enumerate(cands, 1):
        c = {"id": "B%d" % n, "fitRank": int(i) + 1, "nFit": v[0], "fit": round(v[1], 2), "nChk": v[2], "chk": round(v[3], 2), "chkWithoutBest": round(v[4], 2)}
        if s[0] == "rule":
            c.update(window=s[1], conds=[list(x) for x in s[2]])
        else:
            c.update(rank=list(s[1:]))
        out.append(c)
    return {"family": "F3 buy filters on the big test (2-hour price)", "luck": luck(F, C, W, top),
            "yardstick": {"gates": {"nFit": gates[0], "fit": round(gates[1], 2), "nChk": gates[2], "chk": round(gates[3], 2)}}, "candidates": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    doc = {"v": 1, "prereg": "research/livesearch/PREREG-LIVESEARCH-2026-11-04.md", "split": SPLIT, "forwardFrom": 1793836800000,
           "forwardBuysUntil": 1795262400000, "judge": "22 Nov 2026, PR #39 bar", "families": [f1(a.data), f2(a.data), f3(a.data)]}
    json.dump(doc, open(a.out, "w"), indent=1)
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
