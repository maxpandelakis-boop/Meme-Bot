"""Check of the grid outcomes (fake money only). features.dense forward-fills each minute's HIGH and LOW into the following minutes
without a trade, so a dead pool's last wick counts again in every quiet minute after it: a coin whose last trade minute had a high of
238x its close "reaches 10x" after the entry although nobody traded again. The live code (rocket.py dense, Book.update) never did
this: a minute without a trade has high = low = the last close. This recomputes the outcome of every grid row with that rule (rule
A from the minute, the 6 h high and low) and keeps the old numbers next to it.
usage: python3 research/winlose/wick_check.py <scratch> [grid file, default grid_early.pkl]  -> <scratch>/<grid>_fix.pkl"""
import glob, multiprocessing as mp, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import memebot as M

S = sys.argv[1]
GF = sys.argv[2] if len(sys.argv) > 2 else "grid_early.pkl"
PATH = 360
G = pd.read_pickle(os.path.join(S, GF))
WANT = G.groupby("pool")["E"].apply(list).to_dict()


def arrays(g):
    """close forward-filled; high and low only where the minute traded, else the close (as rocket.dense)."""
    n = int(g["mi"].max()) + 1
    mi = g["mi"].to_numpy()
    c = np.full(n, np.nan); c[mi] = g["p_close"].to_numpy(); c = pd.Series(c).ffill().to_numpy()
    hi = np.full(n, np.nan); hi[mi] = g["p_hi"].to_numpy(); hi = np.where(np.isnan(hi), c, hi)
    lo = np.full(n, np.nan); lo[mi] = g["p_lo"].to_numpy(); lo = np.where(np.isnan(lo), c, lo)
    return c, hi, lo


def one(f):
    out = []
    b = pd.read_parquet(f, columns=["pool", "mi", "p_close", "p_hi", "p_lo"])
    b = b[b["pool"].isin(WANT)]
    for pool, g in b.groupby("pool"):
        c, hi, lo = arrays(g.sort_values("mi"))
        n = len(c)
        for E in WANT[pool]:
            p0 = c[E - 1]
            h, l = hi[E:E + PATH] / p0, lo[E:E + PATH] / p0
            s = np.nonzero(l <= 0.70)[0]; t = np.nonzero(h >= 11.0)[0]
            if len(s) and (not len(t) or s[0] <= t[0]):
                m = float(l[s[0]])
            elif len(t):
                m = 11.0
            else:
                m = float(c[min(E + PATH, n) - 1] / p0)
            out.append((pool, E, m, float(np.nanmax(h)), float(np.nanmin(l))))
    return out


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet")))
    with mp.get_context("fork").Pool(4) as p:
        parts = p.map(one, files, chunksize=1)
    F = pd.DataFrame([r for x in parts for r in x], columns=["pool", "E", "mult_fix", "hi6_fix", "lo6_fix"])
    G = G.merge(F, on=["pool", "E"], how="left")
    G["eur_fix"] = [M.tip_net(max(0.0, m)) for m in G["mult_fix"]]
    G["rocket_fix"] = G["hi6_fix"] >= 10
    G["hit3_fix"] = G["hi6_fix"] >= 3
    G.to_pickle(os.path.join(S, GF.replace(".pkl", "_fix.pkl")))
    ch = G["rocket"] != G["rocket_fix"]
    print("rows", len(G), "missing", int(G["mult_fix"].isna().sum()))
    print("10x label: old %d rows (%d coins), fixed %d rows (%d coins); changed %d rows of %d coins" % (
        G["rocket"].sum(), G.loc[G["rocket"], "mint"].nunique(), G["rocket_fix"].sum(), G.loc[G["rocket_fix"], "mint"].nunique(),
        ch.sum(), G.loc[ch, "mint"].nunique()))
    print("rule A result changed on %d rows; mean per 20 old %.3f fixed %.3f" % (
        int((np.abs(G["mult"] - G["mult_fix"]) > 1e-6).sum()), G["eur"].mean(), G["eur_fix"].mean()))
