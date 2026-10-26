"""Exploratory check (not pre-registered as a test, reported as exploration): do rules that were positive in-sample stay positive
on the unseen windows more often than all rules do? Same rule grid as check_rs.py best (single conditions and pairs, >=40 in-sample and >=20 w4 trades).

  python3 research/rocketsep/rs_persist.py <out dir>     -> <out dir>/persist.json
"""
import sys, os, json, numpy as np
sys.path.insert(0, "research/rocketsep")
import check_rs as RS
out = sys.argv[1]
Mt, P, D, F, FE, Fx = RS.load(out)
BM = np.load(os.path.join(out, "buyplans.npy")); mB = RS.money(BM)
W = Mt["w"].to_numpy()
res = {}
for fam, ins, chk in (("A", ["w1", "w2", "w3"], ["w4", "w5"]), ("B", ["w3"], ["w4"])):
    Xf, names = RS.buy_X(FE, Fx, fam)
    Cm, labs = RS.cond_matrix(Xf, names, np.isin(W, ins), fam == "B")
    K = Cm.shape[1]
    for role in ("P", "L", "A"):
        rm = RS.roles_of(Mt, role)
        st = {}
        for wn, s in [("ins", rm & np.isin(W, ins))] + [(w, rm & (W == w)) for w in chk]:
            Cs = Cm[s].astype(float); Ms = mB[s]
            cnt = np.zeros((K, K)); sm = np.zeros((K, K, 8))
            for i in range(K):
                mi = Cs * Cs[:, i:i + 1]; cnt[i] = mi.sum(0); sm[i] = mi.T @ Ms
            st[wn] = (cnt, sm)
        iu = np.triu_indices(K)
        ci, si = st["ins"][0][iu], st["ins"][1][iu]
        c4, s4 = st["w4"][0][iu], st["w4"][1][iu]
        mi = si / np.maximum(ci[:, None], 1) - RS.COST; m4 = s4 / np.maximum(c4[:, None], 1) - RS.COST
        ok = (ci[:, None] >= 40) & (c4[:, None] >= 20)
        posI = ok & (mi > 0)
        okP = np.broadcast_to(ok, mi.shape)                                  # rule x plan pairs (all counts below are pairs)
        r = {"rules": int(ok.sum()), "rulePlanPairs": int(okP.sum()), "posInSample": int(posI.sum()),
             "posW4_given_posIns": int((posI & (m4 > 0)).sum()), "posW4_all": int((okP & (m4 > 0)).sum())}
        r["shareW4pos_given_posIns"] = round(r["posW4_given_posIns"] / max(r["posInSample"], 1), 4)
        r["shareW4pos_all"] = round(r["posW4_all"] / max(r["rulePlanPairs"], 1), 4)
        if "w5" in st:                                                       # the same shares on w5 (pairs with 5+ w5 trades)
            c5a, s5a = st["w5"][0][iu], st["w5"][1][iu]
            m5 = s5a / np.maximum(c5a[:, None], 1) - RS.COST
            ok5 = okP & (c5a[:, None] >= 5)
            for nm, base in (("all", ok5), ("given_posIns", posI & ok5), ("given_posIns_posW4", posI & (m4 > 0) & ok5)):
                r["w5pos_" + nm] = [int((base & (m5 > 0)).sum()), int(base.sum())]
        both = np.argwhere(posI & (m4 > 0))
        lst = []
        for a, p in both:
            i, j = int(iu[0][a]), int(iu[1][a])
            row = {"rule": labs[i] + ("" if i == j else " AND " + labs[j]), "plan": RS.BPLANS[p], "ins": [int(ci[a]), round(float(mi[a, p]), 2)],
                   "w4": [int(c4[a]), round(float(m4[a, p]), 2)]}
            if "w5" in st:
                c5, s5 = st["w5"][0][i, j], st["w5"][1][i, j, p]
                row["w5"] = [int(c5), round(float(s5 / c5 - RS.COST), 2) if c5 else None]
            lst.append(row)
        lst.sort(key=lambda x: -min(x["ins"][1], x["w4"][1]))
        r["bothPositive_top"] = lst[:15]
        if "w5" in st:
            r["bothPos_w5"] = {"n": len(lst), "w5pos": sum(1 for x in lst if x["w5"][1] is not None and x["w5"][1] > 0 and x["w5"][0] >= 5),
                               "w5known": sum(1 for x in lst if x["w5"][0] >= 5)}
        res[fam + role] = r
        print(fam, role, {k: v for k, v in r.items() if k != "bothPositive_top"}, flush=True)
        for x in lst[:5]:
            print("    ", x)
json.dump(res, open(os.path.join(out, "persist.json"), "w"), indent=1)
