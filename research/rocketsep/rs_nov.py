"""The Pick-group rules that were positive in all three periods, frozen now and judged later on a month no one has seen
(fake money only; research/rocketsep/PREREG-NOV-2026-10-26.md).

  python3 research/rocketsep/rs_nov.py freeze <out dir>               -> research/rocketsep/NOV-RULES-2026-10-26.json
  python3 research/rocketsep/rs_nov.py judge <out dir> <window>       -> <out dir>/nov_judge.json

freeze: family-A rule-plan pairs of check_rs.py best / rs_persist.py, role P, with 40+ trades and a mean above the 0.75 EUR allowance
in w1-w3, 20+ trades and a positive mean after it on w4, 5+ trades and a positive mean after it on w5. Each condition is written
out with its fixed cut values (the quintile edges come from w1-w3, as in cond_matrix), so the rule can be applied to new data
without refitting anything.
judge: the same rules on the buys of <window> (a later build with rs_build.py + rs_facts.py; buyplans.npy from check_rs.py
ceiling), role P, each rule alone and all of them together (a buy taken when any rule takes it, sold by the plan of the first
rule in the file that takes it)."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_rs as RS                                         # noqa: E402
import rs_facts as RF                                         # noqa: E402

RULES = os.path.join(HERE, "NOV-RULES-2026-10-26.json")
INS, W4, W5 = ["w1", "w2", "w3"], "w4", "w5"


def cond_defs(Xf, names, fit_rows):
    """cond_matrix's columns as fixed definitions: (label, feature, edges, k, kind)"""
    sys.path.insert(0, os.path.join(HERE, "..", "rockets"))
    import check_rockets as RK
    defs = []
    for f in RF.G_F:
        x = Xf[:, names.index(f)]
        bk = RK.BUCKETS.get(f)
        if bk is None:
            qs = np.nanquantile(x[fit_rows], [0.2, 0.4, 0.6, 0.8])
            defs += [("%s quintile %d" % (f, k + 1), f, [float(q) for q in qs], k, "quintile") for k in range(5)]
        else:
            cuts, bl = bk
            defs += [("%s = %s" % (f, lab), f, [float(c) for c in cuts], k, "bucket") for k, lab in enumerate(bl)]
    for f in RS.CHART_Q:
        x = Xf[:, names.index(f)]
        qs = np.nanquantile(x[fit_rows & np.isfinite(x)], [0.2, 0.4, 0.6, 0.8])
        defs += [("%s quintile %d" % (f, k + 1), f, [float(q) for q in qs], k, "quintile") for k in range(5)]
    return defs


def apply_def(Xf, names, d):
    _, f, edges, k, kind = d
    x = Xf[:, names.index(f)]
    b = np.digitize(x, edges) - (1 if kind == "bucket" else 0)
    return np.isfinite(x) & (b == k)


def stats(m):
    return [int(len(m)), round(float(m.mean() - RS.COST), 2) if len(m) else None]


def cmd_freeze(out):
    Mt, P, D, F, FE, Fx = RS.load(out)
    mB = RS.money(np.load(os.path.join(out, "buyplans.npy")))
    W = Mt["w"].to_numpy()
    Xf, names = RS.buy_X(FE, Fx, "A")
    fit = np.isin(W, INS)
    Cm, labs = RS.cond_matrix(Xf, names, fit)
    defs = cond_defs(Xf, names, fit)
    assert [d[0] for d in defs] == labs
    assert all((apply_def(Xf, names, d) == Cm[:, i]).all() for i, d in enumerate(defs))
    rm = RS.roles_of(Mt, "P")
    K = Cm.shape[1]
    rules = []
    for i in range(K):
        for j in range(i, K):
            sel = Cm[:, i] & Cm[:, j] & rm
            s_ins, s4, s5 = sel & fit, sel & (W == W4), sel & (W == W5)
            if s_ins.sum() < 40 or s4.sum() < 20 or s5.sum() < 5:
                continue
            for p, plan in enumerate(RS.BPLANS):
                a, b, c = stats(mB[s_ins, p]), stats(mB[s4, p]), stats(mB[s5, p])
                if a[1] > 0 and b[1] > 0 and c[1] > 0:
                    rules.append({"rule": labs[i] + ("" if i == j else " AND " + labs[j]), "plan": plan,
                                  "conditions": [dict(zip(("label", "feature", "edges", "k", "kind"), defs[x])) for x in sorted({i, j})],
                                  "w1-w3": a, "w4": b, "w5": c})
    rules.sort(key=lambda r: -min(r["w1-w3"][1], r["w4"][1], r["w5"][1]))
    res = {"frozen": "2026-10-26", "role": "P", "allowanceEUR": RS.COST, "cost": "per 50-EUR buy, after paper fees and the allowance",
           "searched": "all single conditions and pairs of check_rs.py best (family A), 8 plans", "rules": rules}
    json.dump(res, open(RULES, "w"), indent=1, ensure_ascii=False)
    for r in rules:
        print(r["rule"], r["plan"], r["w1-w3"], r["w4"], r["w5"], flush=True)
    print(len(rules), "rule-plan pairs frozen", flush=True)


def cmd_judge(out, win):
    R = json.load(open(RULES))
    Mt, P, D, F, FE, Fx = RS.load(out)
    mB = RS.money(np.load(os.path.join(out, "buyplans.npy")))
    W = Mt["w"].to_numpy()
    Xf, names = RS.buy_X(FE, Fx, "A")
    base = RS.roles_of(Mt, "P") & (W == win)
    res = {"window": win, "buys": int(base.sum()), "rules": [], "together": None}
    taken = np.full(len(W), -1)
    for r in R["rules"]:
        sel = base.copy()
        for c in r["conditions"]:
            sel &= apply_def(Xf, names, (c["label"], c["feature"], c["edges"], c["k"], c["kind"]))
        p = RS.BPLANS.index(r["plan"])
        res["rules"].append({"rule": r["rule"], "plan": r["plan"], "trades": int(sel.sum()), "profit": RS.profit(mB[sel, p])})
        taken[sel & (taken < 0)] = p
    t = taken >= 0
    res["together"] = {"trades": int(t.sum()), "profit": RS.profit(mB[np.nonzero(t)[0], taken[t]])}
    json.dump(res, open(os.path.join(out, "nov_judge.json"), "w"), indent=1)
    print(json.dumps(res["together"]), flush=True)


if __name__ == "__main__":
    {"freeze": lambda: cmd_freeze(sys.argv[2]), "judge": lambda: cmd_judge(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
