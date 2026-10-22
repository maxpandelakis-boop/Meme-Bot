"""Winner/loser study, addendum 2 (fake money only): every coin every 15 minutes from 30 min to 18 h after the graduation, from
the one-minute bars: the universe filters, the chart numbers of features.py, the outcome of sell rule A from that minute
(not clipped) and the 6 h high. Then the wallet and market numbers for those rows.
usage: python3 research/winlose/grid.py <scratch>  -> <scratch>/grid.pkl"""
import glob, json, math, os, sys
import numpy as np, pandas as pd

S = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import features as FE          # loads d.pkl (used for the market regime numbers)
from load import eur
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import memebot as M

STEP, START, END, PATH = 15, 30, 18 * 60, 360
coins = pd.read_parquet(os.path.join(S, "h2", "coins.parquet")).drop_duplicates("pool").set_index("pool")
gap = set(np.load(os.path.join(S, "h2", "gap_minutes.npy")).tolist())
k = [json.loads(l) for l in open(os.path.join(S, "mk", "SOLUSDT.jsonl"))]
sol_t, sol_c = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])


def solusd(ms):
    i = np.searchsorted(sol_t, ms, side="right") - 1
    return sol_c[np.clip(i, 0, len(sol_c) - 1)]


def net(m):
    """What a 20 ticket became at multiple m, after fees, NOT clipped (memebot.tip_net)."""
    return M.tip_net(max(0.0, m))


rows = []
for f in sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet"))):
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(coins.index)]
    for pool, g in b.groupby("pool"):
        g = g.sort_values("mi")
        if g["mi"].max() < START:
            continue
        a = FE.dense(g)
        n = len(a["c"])
        c0 = coins.loc[pool]
        gm, kk = int(c0["grad_ms"]), float(c0["sol0"]) * float(c0["tok0"])
        vol = a["vb"] + a["vs"]
        cv = np.r_[0, np.cumsum(vol)]
        gmin = gm // 60000
        for E in range(START, min(END, n) + 1, STEP):
            p0 = a["c"][E - 1]
            if not (p0 > 0):
                continue
            ts = gm + E * 60000
            usd = float(solusd(ts))
            mc = p0 * 1e9 * usd
            liq = 2 * math.sqrt(kk * p0) * usd
            v24 = (cv[E] - cv[max(0, E - 1440)]) * usd
            ref = lambda m_: a["c"][max(0, E - 1 - m_)]
            c1, c6 = p0 / ref(60) - 1, p0 / ref(360) - 1
            if not (liq >= 15_000 and v24 >= 15_000 and 100_000 <= mc <= 5_000_000 and c1 > -0.10 and c6 > -0.50):
                continue
            if any((gmin + E - j) * 60000 in gap for j in range(1, 61)) or any((gmin + E + j) * 60000 in gap for j in range(PATH)):
                continue
            hi, lo = a["hi"][E:E + PATH] / p0, a["lo"][E:E + PATH] / p0
            if not len(hi):
                continue
            s = np.nonzero(lo <= 0.70)[0]; t = np.nonzero(hi >= 11.0)[0]
            if len(s) and (not len(t) or s[0] <= t[0]):
                mult = float(lo[s[0]])
            elif len(t):
                mult = 11.0
            else:
                mult = float(a["c"][min(E + PATH, n) - 1] / p0)
            fe = FE.chart_feats(a, E)
            fe.update(pool=pool, mint=c0["mint"], ts=ts, grad_ms=gm, E=E, mc=np.log10(mc), liqmc=liq / mc, volmc=v24 / mc,
                      eur=net(mult), mult=mult, hi6=float(np.nanmax(hi)), lo6=float(np.nanmin(lo)))
            rows.append(fe)
    print(os.path.basename(f), len(rows), flush=True)
G = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
G["win"] = G["eur"] > 0
G["rocket"] = G["hi6"] >= 10
G["hit3"] = G["hi6"] >= 3
G["gday"] = ((G["grad_ms"] - FE.d["grad_ms"].min()) // 86_400_000).astype(int)
G.to_pickle(os.path.join(S, "grid_chart.pkl"))
FE.rows = G
Mk = FE.market_all()
W = FE.wallet_chunked(G)
G = pd.concat([G, W, Mk], axis=1)
G.to_pickle(os.path.join(S, "grid.pkl"))
print(G.shape, "coins", G["mint"].nunique())
print(G[["eur", "win", "rocket", "hit3"]].mean())
