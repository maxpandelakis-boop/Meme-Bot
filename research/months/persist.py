"""Added after the pre-registered run (information only, decides nothing): at step 5 (fit w1-w4, test w5), over every filter x
sell rule with >= 30 coins in each fit window and >= 20 on w5, how a rule's fit mean carries over to w5.
  python3 research/months/persist.py <out dir of check_months.py>  -> <out dir>/persist.json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import check_months as C
out = sys.argv[1]
res = {}
for fam in "PUR":
    d = C.load_rows(out, fam)
    sel = C.first_per_coin(np.ones(len(d["df"]), bool), d["codes"])
    base = {C.WN[i]: C.summ(d["O"][sel[d["wi"][sel] == i], C.K]) for i in range(5)}
    fit_ix, test_i = [0, 1, 2, 3], 4
    conds = C.conditions(d["df"], np.isin(d["wi"], fit_ix))
    filt, cnt, sums = C.scan_filters(d, fit_ix, conds)
    c = cnt[:, fit_ix]; ok = (c >= 30).all(1) & (cnt[:, test_i] >= 20)
    fit = sums[:, fit_ix].sum(1) / np.maximum(c.sum(1), 1)[:, None]
    te = sums[:, test_i] / np.maximum(cnt[:, test_i], 1)[:, None]
    f, t = fit[ok].ravel(), te[ok].ravel()
    top = f >= np.quantile(f, 0.99)
    r = {"baseK": base, "combos": int(len(f)), "fitPositive": round(100 * float((f > 0).mean()), 1),
         "testPositive": round(100 * float((t > 0).mean()), 1),
         "testPositiveIfFitPositive": round(100 * float((t[f > 0] > 0).mean()), 1) if (f > 0).any() else None,
         "testPositiveIfFitNegative": round(100 * float((t[f <= 0] > 0).mean()), 1),
         "testMeanTop1pctFit": round(float(t[top].mean()), 2), "testMeanAll": round(float(t.mean()), 2),
         "rankCorr": round(float(np.corrcoef(np.argsort(np.argsort(f)), np.argsort(np.argsort(t)))[0, 1]), 3)}
    res[fam] = r
    print(fam, json.dumps(r))
json.dump(res, open(out + "/persist.json", "w"), indent=1)
