"""Test 3 of PREREG-EARLY-EXIT-2026-10-22.md (fake money only): the states an open rocket position can be in, for the exit model.
Every coin of the live grid (grid_early_live.pkl) every 15 minutes from its first grid row to 24 h after its last one (at most
42 h after the graduation), from the one-minute bars of the first 55 hours (branch chartbars55; a minute without a trade has
high = low = the last close, as rocket.dense). Kept: price known, market cap $50k or more (a position bought at $100k or more is
stopped out at -30% before that), no recorder outage in the hour before or the 6 h after.
Numbers: the live model's 60 (chart, recent wallets, market cap/liquidity/volume, BTC/SOL) and the age in minutes.
Label: from the state's close, 2x before 0.5x (minute highs/lows; both in one minute = the fall); neither within 24 h: the last
close above the state's close.
usage: python3 research/winlose/exit_states.py <scratch>  -> <scratch>/exit_states.pkl"""
import glob, json, math, multiprocessing as mp, os, sys
import numpy as np, pandas as pd

S = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import features as FE
STEP, LAST, HZ, UP, DN = 15, 42 * 60, 24 * 60, 2.0, 0.5
coins = pd.read_parquet(os.path.join(S, "h2", "coins.parquet")).drop_duplicates("pool").set_index("pool")
gap = set((np.load(os.path.join(S, "h2", "gap_minutes.npy")) // 60000).tolist())
k = [json.loads(l) for l in open(os.path.join(S, "mk", "SOLUSDT.jsonl"))]
sol_t, sol_c = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])
G = pd.read_pickle(os.path.join(S, "grid_early_live.pkl"))
SPAN = G.groupby("pool")["E"].agg(["min", "max"]).to_dict("index")


def solusd(ms):
    i = np.searchsorted(sol_t, ms, side="right") - 1
    return sol_c[np.clip(i, 0, len(sol_c) - 1)]


def label(hi, lo, c, t, p0):
    h, l = hi[t:t + HZ] / p0, lo[t:t + HZ] / p0
    u, d = np.nonzero(h >= UP)[0], np.nonzero(l <= DN)[0]
    if len(d) and (not len(u) or d[0] <= u[0]):
        return 0
    if len(u):
        return 1
    return int(c[min(t + HZ, len(c)) - 1] > p0)


def one(f):
    rows = []
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(SPAN)]
    for pool, g in b.groupby("pool"):
        a = FE.dense(g.sort_values("mi"), fill_hl=False)
        n = len(a["c"])
        c0 = coins.loc[pool]
        gm, kk = int(c0["grad_ms"]), float(c0["sol0"]) * float(c0["tok0"])
        cv = np.r_[0, np.cumsum(a["vb"] + a["vs"])]
        gmin = gm // 60000
        sp = SPAN[pool]
        for t in range(int(sp["min"]) + STEP, min(int(sp["max"]) + HZ, LAST, n) + 1, STEP):
            p0 = a["c"][t - 1]
            if not (p0 > 0):
                continue
            ts = gm + t * 60000
            usd = float(solusd(ts))
            mc = p0 * 1e9 * usd
            if mc < 50_000:
                continue
            if any(gmin + t - j in gap for j in range(1, 61)) or any(gmin + t + j in gap for j in range(360)):
                continue
            fe = FE.chart_feats(a, t, min_e=5)
            if not fe:
                continue
            liq = 2 * math.sqrt(kk * p0) * usd
            v24 = (cv[t] - cv[max(0, t - 1440)]) * usd
            fe.update(pool=pool, mint=c0["mint"], ts=ts, grad_ms=gm, E=t, age_min=t, mc=np.log10(mc), liqmc=liq / mc, volmc=v24 / mc,
                      y=label(a["hi"], a["lo"], a["c"], t, p0))
            rows.append(fe)
    print(os.path.basename(f), len(rows), flush=True)
    return rows


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(S, "cb55", "bars_*.parquet")))
    with mp.get_context("fork").Pool(4) as p:
        parts = p.map(one, files, chunksize=1)
    X = pd.DataFrame([r for x in parts for r in x]).sort_values("ts").reset_index(drop=True)
    FE.rows = X
    X = pd.concat([X, FE.market_all(), FE.wallet_recent(X, chunk=60)], axis=1)
    X.to_pickle(os.path.join(S, "exit_states.pkl"))
    print(X.shape, "coins", X["mint"].nunique(), "label mean %.3f" % X["y"].mean())
