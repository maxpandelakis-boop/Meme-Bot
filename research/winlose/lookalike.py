"""Winner/loser study (fake money only): the chart look-alikes. For every row, the 50 most similar charts (last 2 hours:
5-minute closes relative to now, 10-minute volume shares, the path since the graduation in 4 points) among rows of coins that
graduated 2 days or more earlier (their 6 h results were known by then): winner share, loser share, average result.
usage: python3 research/winlose/lookalike.py <scratch>   (needs feat.pkl and cb/)  -> adds nn_* columns to feat.pkl"""
import glob, os, sys
import numpy as np, pandas as pd
from sklearn.neighbors import NearestNeighbors
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
S = sys.argv[1]
sys.argv = sys.argv[:1] + [S]
from features import dense

F = pd.read_pickle(os.path.join(S, "feat.pkl"))
F["E"] = ((F["ts"] - F["grad_ms"]) // 60_000).astype(int)
vec = {}
by_pool = F.groupby("pool")
pools = set(F["pool"])
for f in sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet"))):
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(pools)]
    for pool, g in b.groupby("pool"):
        a = dense(g.sort_values("mi"))
        n = len(a["c"])
        for idx, E in by_pool.get_group(pool)["E"].items():
            E = min(E, n)
            if E < 120:
                continue
            lc = np.log(np.clip(a["c"][:E], 1e-30, None))
            p = lc[E - 1::-5][:25][::-1]
            if len(p) < 25 or not np.isfinite(p).all():
                continue
            v = (a["vb"] + a["vs"])[E - 120:E].reshape(12, 10).sum(1)
            v = v / v.sum() if v.sum() > 0 else v
            since = lc[np.linspace(0, E - 1, 5).astype(int)] - lc[E - 1]
            vec[idx] = np.nan_to_num(np.r_[(p - p[-1]) * 3, v, np.clip(since, -5, 5)])
X = pd.DataFrame.from_dict(vec, orient="index").sort_index()
print("vectors", X.shape)
G = F.loc[X.index]
out = pd.DataFrame(index=X.index, columns=["nn_win", "nn_lose", "nn_eur"], dtype=float)
for day in sorted(G["gday"].unique()):
    q = G.index[G["gday"] == day]
    ref = G.index[G["gday"] <= day - 2]
    if len(ref) < 500:
        continue
    nn = NearestNeighbors(n_neighbors=50).fit(X.loc[ref].to_numpy())
    _, ix = nn.kneighbors(X.loc[q].to_numpy())
    r = G.loc[ref]
    out.loc[q, "nn_win"] = r["hit3"].to_numpy()[ix].mean(1)
    out.loc[q, "nn_lose"] = r["lose80"].to_numpy()[ix].mean(1)
    out.loc[q, "nn_eur"] = r["eur_A"].to_numpy()[ix].mean(1)
F = F.drop(columns=[c for c in F.columns if c.startswith("nn_")] + ["E"])
F = F.join(out)
F.to_pickle(os.path.join(S, "feat.pkl"))
print(F[["nn_win", "nn_lose", "nn_eur"]].describe())
