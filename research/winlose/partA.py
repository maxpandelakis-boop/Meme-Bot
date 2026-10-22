"""Part A of research/winlose/PREREG-WINLOSE-2026-10-22.md: where winners and losers differ, like with like (fake money only).
usage: python3 research/winlose/partA.py <scratch>  -> prints a table, writes <scratch>/partA.json"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.stats import norm, rankdata

S = sys.argv[1]
F = pd.read_pickle(os.path.join(S, "feat.pkl"))
EARLY, HOLD = 1788566400000, 1790294400000          # 5 Sep, 25 Sep
META = {"mint", "pool", "ts", "grad_ms", "h", "gday", "day", "eur_A", "eur_hold", "hit3", "lose80", "zero", "gates", "lo6", "hi6"}
NUM = [c for c in F.columns if c not in META]
hb = pd.cut(F["h"], [0, 1, 2, 5, 11, 24], labels=False)
dev = F["grad_ms"] < HOLD
mcq = pd.qcut(F.loc[dev, "mc"], 5, retbins=True)[1]
F["stratum"] = hb * 10 + np.clip(np.searchsorted(mcq[1:-1], F["mc"]), 0, 4)
F["part"] = np.where(F["grad_ms"] < EARLY, "early", np.where(F["grad_ms"] < HOLD, "late", "hold"))


def strat_auc(x, pos, neg, strat):
    """Stratified Mann-Whitney: within each stratum AUC of pos over neg, weighted by n_pos*n_neg; z from the summed U."""
    U = E = V = W = 0.0
    for s in np.unique(strat):
        m = strat == s
        a, b = x[m & pos], x[m & neg]
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        n1, n2 = len(a), len(b)
        if n1 < 3 or n2 < 3:
            continue
        r = rankdata(np.r_[a, b])
        u = r[:n1].sum() - n1 * (n1 + 1) / 2
        U += u; E += n1 * n2 / 2; V += n1 * n2 * (n1 + n2 + 1) / 12; W += n1 * n2
    if W == 0:
        return np.nan, np.nan
    z = (U - E) / np.sqrt(V)
    return U / W, z


# one row per coin for the comparison (its first universe hour), so a coin with 20 hours does not count 20 times
C = F.drop_duplicates("mint")
res = []
for comp, pos_f, neg_f in (("win_vs_lose", lambda c: c["hit3"], lambda c: c["lose80"]),
                           ("win_vs_rest", lambda c: c["hit3"], lambda c: ~c["hit3"]),
                           ("move_vs_calm", lambda c: c["hit3"] | c["lose80"], lambda c: ~(c["hit3"] | c["lose80"]))):
    for k in NUM:
        row = {"comp": comp, "num": k}
        for part in ("early", "late", "hold"):
            c = C[C["part"] == part]
            auc, z = strat_auc(c[k].to_numpy(float), pos_f(c).to_numpy(), neg_f(c).to_numpy(), c["stratum"].to_numpy())
            row[part] = auc
            row["z_" + part] = z
        res.append(row)
R = pd.DataFrame(res)
R["p_hold"] = 2 * norm.sf(R["z_hold"].abs())
out = []
for comp, g in R.groupby("comp"):
    g = g.copy()
    # Holm over the numbers of this comparison
    order = np.argsort(g["p_hold"].fillna(1).to_numpy())
    m = len(g); holm = np.ones(m); prev = 0
    for i, j in enumerate(order):
        prev = max(prev, min(1, (m - i) * g["p_hold"].fillna(1).iloc[j])); holm[j] = prev
    g["p_holm"] = holm
    same = (np.sign(g["early"] - .5) == np.sign(g["late"] - .5)) & (np.sign(g["late"] - .5) == np.sign(g["hold"] - .5))
    g["holds"] = same & (g["p_holm"] < 0.05)
    g["dev_strength"] = ((g["early"] + g["late"]) / 2 - .5).abs()
    out.append(g)
R = pd.concat(out)
pd.set_option("display.width", 200)
print("coins: early %d, late %d, hold %d; winners %d, losers %d" % ((C.part == "early").sum(), (C.part == "late").sum(), (C.part == "hold").sum(), C.hit3.sum(), C.lose80.sum()))
for comp, g in R.groupby("comp"):
    g = g.sort_values("dev_strength", ascending=False)
    print("\n==", comp, "| holds:", int(g["holds"].sum()), "of", len(g))
    print(g.head(25)[["num", "early", "late", "hold", "p_holm", "holds"]].round(3).to_string(index=False))
R.to_json(os.path.join(S, "partA.json"), orient="records")
