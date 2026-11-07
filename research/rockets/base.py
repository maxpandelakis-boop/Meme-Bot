"""Rocket study, step 2: entries at fixed minutes after the graduation and what the price did in the next 24 hours.

  python3 research/rockets/base.py <work dir>      (needs paths.npz + coins.parquet from build_paths.py)

Entry at E minutes after the graduation at the close of the last five-minute candle that closed before then (as
research/check_months.py); the path starts with the candle that holds the entry moment. rocket = a five-minute close at
10x the entry or more within 24 h; zero = the close 24 h after the entry at 0.1x or less. Writes <work>/entries.parquet."""
import os, sys
import numpy as np, pandas as pd

BAR, MIN = 300_000, 60_000
ES = (5, 15, 30, 60)
N24 = 288


def entries(work):
    z = np.load(os.path.join(work, "paths.npz"))
    cl, has, hi, v = z["cl"], z["has"], z["hi"], z["v"]
    m = pd.read_parquet(os.path.join(work, "coins.parquet"))
    gm = m["t"].to_numpy(np.int64)
    t0 = gm // BAR * BAR
    out = []
    ar = np.arange(len(m))
    cv = np.cumsum(v, 1)
    anyhas = np.cumsum(has, 1) > 0
    for E in ES:
        te = gm + E * MIN
        jl = ((te - t0) // BAR - 1).astype(np.int64)
        ok = (jl >= 0) & (jl + N24 + 1 < cl.shape[1])
        jl = np.clip(jl, 0, cl.shape[1] - N24 - 2)
        p0 = cl[ar, jl]
        ok &= anyhas[ar, jl] & np.isfinite(p0) & (p0 > 0)
        idx = jl[:, None] + 1 + np.arange(N24)[None, :]
        P = cl[ar[:, None], idx] / p0[:, None]
        Hh = np.where(has[ar[:, None], idx], hi[ar[:, None], idx], np.nan) / p0[:, None]
        mx = np.nanmax(np.where(np.isfinite(P), P, -1), 1)
        hit = P >= 10
        t10 = np.where(hit.any(1), hit.argmax(1) + 1, -1)
        pre = np.where(np.arange(N24)[None, :] < np.where(t10 > 0, t10 - 1, N24)[:, None], P, np.inf)
        mn_before = np.nanmin(pre, 1)
        hit3 = P >= 3
        d = pd.DataFrame({"pool": m["pool"], "w": m["w"], "E": E, "te": te, "ok": ok, "p0": p0, "mc0": p0 * 1e9,
                          "vol0": cv[ar, jl], "mx24": mx, "hx24": np.nanmax(np.where(np.isfinite(Hh), Hh, -1), 1),
                          "last24": P[:, -1], "t10_min": np.where(t10 > 0, t10 * 5, np.nan),
                          "x3": hit3.any(1), "min_before10": mn_before,
                          "gain_pre": p0 / np.where(np.isfinite(cl[ar, np.argmax(has, 1)]), cl[ar, np.argmax(has, 1)], np.nan)})
        d["rocket"] = d["mx24"] >= 10
        d["zero"] = d["last24"] <= 0.1
        out.append(d)
    e = pd.concat(out, ignore_index=True)
    e.to_parquet(os.path.join(work, "entries.parquet"), index=False)
    return e


if __name__ == "__main__":
    e = entries(sys.argv[1])
    e = e[e["ok"]]
    t = e.groupby(["E", "w"]).agg(coins=("pool", "size"), rockets=("rocket", "sum"), rocket_pct=("rocket", "mean"),
                                  x3_pct=("x3", "mean"), zero_pct=("zero", "mean"), med_mc0=("mc0", "median"))
    t["rocket_pct"] *= 100; t["x3_pct"] *= 100; t["zero_pct"] *= 100
    print(t.round(2).to_string())
