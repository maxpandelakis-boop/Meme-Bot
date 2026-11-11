"""Rocket study, step 1 (fake money only, no network): every pump.fun graduation of the five month windows as one dense row of
five-minute USD closes over its first 50 hours, plus its graduation facts.

  python3 research/rockets/build_paths.py <monthsdata dir> <monthsh2 dir> <history2 dir> <out dir>

Writes <out>/paths.npz (cl: closes ffilled, NaN before the first trade; hi: highs, NaN without a trade; v: USD volume; has: a
trade in the bar) and <out>/coins.parquet (one row per coin: window, pool, mint, t = graduation ms, sol0, and for history2's
windows symbol, token_name, creator, created_ms). Candles as in research/check_months.py: bar 0 starts at the graduation's
five-minute clock bar."""
import glob, json, os, sys
import numpy as np, pandas as pd

BAR = 300_000
NB = 600
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))
W_MS = [(w, int(pd.Timestamp(a, tz="UTC").timestamp() * 1000), int(pd.Timestamp(b, tz="UTC").timestamp() * 1000)) for w, a, b in WINDOWS]


def window(t):
    for w, a, b in W_MS:
        if a <= t < b:
            return w
    return None


def main(md, h2, hist, out):
    os.makedirs(out, exist_ok=True)
    meta = []
    for r in pd.read_parquet(os.path.join(h2, "meta_h2.parquet")).to_dict("records"):
        meta.append(dict(r, src="h2"))
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        for r in json.load(open(f)):
            meta.append(dict(r, src="gt"))
    m = pd.DataFrame(meta)
    m["w"] = [window(int(t)) for t in m["t"]]
    m = m[m["w"].notna() & (m["sol0"] >= 10)].drop_duplicates("pool").reset_index(drop=True)
    names = pd.read_parquet(os.path.join(hist, "coins.parquet"), columns=["pool", "symbol", "token_name", "creator", "created_ms"])
    m = m.merge(names.drop_duplicates("pool"), on="pool", how="left")
    ix = {p: i for i, p in enumerate(m["pool"])}
    t0 = (m["t"].to_numpy(np.int64) // BAR) * BAR
    n = len(m)
    cl = np.full((n, NB), np.nan, np.float32)
    hi = np.full((n, NB), np.nan, np.float32)
    v = np.zeros((n, NB), np.float32)
    files = sorted(glob.glob(os.path.join(h2, "bars_*.parquet"))) + sorted(glob.glob(os.path.join(md, "bars_w*.parquet")))
    for f in files:
        b = pd.read_parquet(f)
        r = b["pool"].map(ix)
        ok = r.notna().to_numpy()
        r = r.to_numpy()[ok].astype(np.int64)
        j = ((b["t"].to_numpy()[ok] - t0[r]) // BAR).astype(np.int64)
        k = (j >= 0) & (j < NB)
        r, j = r[k], j[k]
        c = b["c"].to_numpy()[ok][k]
        good = np.isfinite(c) & (c > 0)
        r, j = r[good], j[good]
        cl[r, j] = c[good]
        hi[r, j] = np.fmax(b["h"].to_numpy()[ok][k][good], c[good])
        v[r, j] = b["v"].to_numpy()[ok][k][good]
        print(f, len(b), flush=True)
    has = np.isfinite(cl)
    clf = pd.DataFrame(cl.T).ffill().to_numpy(np.float32).T
    m["nbars"] = has.sum(1)
    np.savez(os.path.join(out, "paths.npz"), cl=clf, hi=hi, v=v, has=has)
    m.to_parquet(os.path.join(out, "coins.parquet"), index=False)
    print(m.groupby("w").agg(coins=("pool", "size"), with_bars=("nbars", lambda x: int((x > 0).sum())),
                             named=("symbol", lambda x: int(x.notna().sum()))))


if __name__ == "__main__":
    main(*sys.argv[1:5])
