#!/usr/bin/env python3
"""ls_skip.py: family F2 of the live-data rule search (PREREG-LIVESEARCH-2026-11-04.md): which Pick buys to leave out. One or two
buy-time factors (the position's "f") at or under / at or over the FIT buys' 33 %, 50 % or 67 % point, keeping >= 40 % of the FIT
buys; result per buy = the Sell bot (rule X) replayed on its path (ls_sell.py's f1.pkl).

  python3 ls_skip.py --data <dir with pick.pkl and f1.pkl> --out <dir>
"""
import argparse, json, math, os, pickle, sys
import numpy as np

SPLIT = 1793404800000
QS = (0.33, 0.50, 0.67)
MIN_KEEP = 0.40


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pick = [r for r in pickle.load(open(os.path.join(a.data, "pick.pkl"), "rb")) if r["shadow"]]
    f1 = pickle.load(open(os.path.join(a.data, "f1.pkl"), "rb"))
    y = np.array(f1["pick"]["X"], dtype=float)
    t = np.array(f1["t_pick"])
    fit, chk = t < SPLIT, t >= SPLIT
    feats = sorted({k for r in pick for k in (r["p"].get("f") or {})})
    Xf = np.array([[float(r["p"]["f"].get(k)) if isinstance(r["p"]["f"].get(k), (int, float)) else np.nan for k in feats] for r in pick])
    conds, masks = [], []
    for j, k in enumerate(feats):
        col = Xf[:, j]
        v = col[fit & ~np.isnan(col)]
        if len(v) < 0.8 * fit.sum() or len(np.unique(v)) < 3:
            continue
        for q in QS:
            thr = float(np.quantile(v, q))
            for op in ("<=", ">="):
                m = (col <= thr) if op == "<=" else (col >= thr)
                m = m & ~np.isnan(col)
                if m[fit].mean() >= MIN_KEEP and m[fit].mean() < 0.999:
                    conds.append((k, op, round(thr, 6)))
                    masks.append(m)
    M_ = np.array(masks)
    print("factors", len(feats), "single conditions", len(conds), flush=True)
    out = []
    nf = fit.sum()
    for i in range(len(conds)):
        m = M_[i]
        out.append(((i,), m))
    for i in range(len(conds)):
        both = M_[i] & M_[i + 1:]
        keep = both[:, fit].sum(1) >= MIN_KEEP * nf
        for jj in np.nonzero(keep)[0]:
            j = i + 1 + jj
            if conds[i][0] == conds[j][0]:
                continue
            out.append(((i, j), both[jj]))
    print("rules", len(out), flush=True)
    rows = []
    for key, m in out:
        f_, c_ = m & fit, m & chk
        if c_.sum() < 5:
            continue
        rows.append({"c": [conds[i] for i in key], "nFit": int(f_.sum()), "fit": float(y[f_].mean()), "nChk": int(c_.sum()),
                     "chk": float(y[c_].mean()), "chkWob": float((y[c_].sum() - y[c_].max()) / max(1, c_.sum() - 1))})
    base = {"fit": float(y[fit].mean()), "chk": float(y[chk].mean()), "nFit": int(fit.sum()), "nChk": int(chk.sum())}
    pickle.dump({"rows": rows, "base": base, "feats": feats}, open(os.path.join(a.out, "f2.pkl"), "wb"))


if __name__ == "__main__":
    main()
