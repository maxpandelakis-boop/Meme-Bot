"""Early entry test of the rocket hunter (fake money only; PREREG-EARLY-EXIT-2026-10-22.md, test 1): the grid of grid.py with the
early checks 5, 10, 15, 20 and 25 minutes after the graduation added to the 15-minute checks from 30 minutes to 18 hours. Same
universe filters, same outcome (sell rule A from that minute, not clipped, the 6 h high), the live model's numbers (chart_feats
with min_e=5, wallet_recent, market). The rows of 30 minutes and later are grid_live.pkl's rows again (the check prints the count).
usage: python3 research/winlose/early_grid.py <scratch>  -> <scratch>/grid_early.pkl"""
import glob, json, math, multiprocessing as mp, os, sys
import numpy as np, pandas as pd

S = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import features as FE          # loads d.pkl (market regime numbers) and pairs.pkl later (wallet_recent)
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import memebot as M

EARLY = (5, 10, 15, 20, 25)
ES = EARLY + tuple(range(30, 18 * 60 + 1, 15))
PATH = 360
coins = pd.read_parquet(os.path.join(S, "h2", "coins.parquet")).drop_duplicates("pool").set_index("pool")
gap = set(np.load(os.path.join(S, "h2", "gap_minutes.npy")).tolist())
k = [json.loads(l) for l in open(os.path.join(S, "mk", "SOLUSDT.jsonl"))]
sol_t, sol_c = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])


def solusd(ms):
    i = np.searchsorted(sol_t, ms, side="right") - 1
    return sol_c[np.clip(i, 0, len(sol_c) - 1)]


def one_file(f):
    rows = []
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(coins.index)]
    for pool, g in b.groupby("pool"):
        g = g.sort_values("mi")
        if g["mi"].max() < EARLY[0]:
            continue
        a = FE.dense(g)
        n = len(a["c"])
        c0 = coins.loc[pool]
        gm, kk = int(c0["grad_ms"]), float(c0["sol0"]) * float(c0["tok0"])
        vol = a["vb"] + a["vs"]
        cv = np.r_[0, np.cumsum(vol)]
        gmin = gm // 60000
        for E in ES:
            if E > n:
                break
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
            fe = FE.chart_feats(a, E, min_e=EARLY[0])
            fe.update(pool=pool, mint=c0["mint"], ts=ts, grad_ms=gm, E=E, mc=np.log10(mc), liqmc=liq / mc, volmc=v24 / mc,
                      eur=M.tip_net(max(0.0, mult)), mult=mult, hi6=float(np.nanmax(hi)), lo6=float(np.nanmin(lo)))
            rows.append(fe)
    print(os.path.basename(f), len(rows), flush=True)
    return rows


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet")))
    with mp.get_context("fork").Pool(4) as pool:
        parts = pool.map(one_file, files, chunksize=1)
    G = pd.DataFrame([r for p in parts for r in p]).sort_values("ts").reset_index(drop=True)
    G["win"] = G["eur"] > 0
    G["rocket"] = G["hi6"] >= 10
    G["hit3"] = G["hi6"] >= 3
    FE.rows = G
    G = pd.concat([G, FE.market_all(), FE.wallet_recent(G)], axis=1)
    G.to_pickle(os.path.join(S, "grid_early.pkl"))
    print(G.shape, "coins", G["mint"].nunique(), "rows from 30 min:", int((G["E"] >= 30).sum()), "(grid_live.pkl: 69,647)")
    print(G.groupby("E").size().head(8).to_string())
    print(G.groupby(G["E"] < 30)[["eur", "rocket", "hit3"]].mean())
