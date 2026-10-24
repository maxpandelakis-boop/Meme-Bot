"""The five-minute replay of check_chartexit.py against one-minute bars (fake money only): the w3/w4 Pick-type coins whose 6 hours
after the entry lie inside history2's first 25 hours (branch chartbars), K and the chosen exit on both, the minute version run as
the live Pick watch would (each minute's low and high, the close 30 minutes before, the last 60 minutes' volume).
usage: calib_minute.py <out dir with paths.pkl and result.json> <chartbars dir>"""
import glob, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_chartexit as X

out, cbd = sys.argv[1], sys.argv[2]
rows = [r for r in pd.read_pickle(os.path.join(out, "paths.pkl")) if r["w"] in ("w3", "w4") and r["E"] + 6 * 60 <= 25 * 60 - 2]
res = json.load(open(os.path.join(out, "result.json")))
J = res["low"]["live"]["j"]
want = {r["pool"]: r for r in rows}
bars = {}
for f in sorted(glob.glob(os.path.join(cbd, "bars_*.parquet"))):
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(want)]
    for pool, g in b.groupby("pool"):
        bars[pool] = g.sort_values("mi")


def minute_path(r, g):
    E = r["E"]
    n = E + 6 * 60 + 2
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n)
    g = g[(g["mi"] >= 0) & (g["mi"] < n)]
    i = g["mi"].to_numpy().astype(int)
    cl[i] = g["p_close"].to_numpy(); hi[i] = g["p_hi"].to_numpy(); lo[i] = g["p_lo"].to_numpy(); op[i] = g["p_open"].to_numpy()
    v[i] = (g["sol_buy"] + g["sol_sell"]).to_numpy()
    has = np.isfinite(cl) & (cl > 0)
    cf = pd.Series(np.where(has, cl, np.nan)).ffill().to_numpy()
    if not np.isfinite(cf[E - 1]):
        return None
    p0 = cf[E - 1]
    s = slice(E, E + 6 * 60)
    C = cf[s] / p0
    if not np.isfinite(C).all():
        return None
    hs = has[s]
    Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
    Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
    Hh = np.where(Hh <= X.WICK_X * C, Hh, C)
    Ll = np.where(Ll >= C / X.WICK_X, Ll, C)
    O = np.clip(np.where(hs & np.isfinite(op[s]), op[s] / p0, np.r_[1.0, C[:-1]]), Ll, Hh)
    v1 = v[max(0, E - 60):E].sum()
    return C, Hh, Ll, O, v[s] * hs, v1


def replay_min(C, Hh, L, O, V, v1, P):
    """check_chartexit.replay_np with minutes for bars: 30 bars = 30 minutes, 60 bars = the hour, the 6 h limit = 360 bars."""
    stop, trail, arm, lock, stale_h, stale_g, fade, T = P
    nT, nS = int(T * 60), int(stale_h * 60) if stale_h else -1
    hi, armed_t, armed_l = 1.0, trail > 0 and arm <= 1.0, False
    for k in range(min(nT, len(C))):
        c, h, l, o = C[k], Hh[k], L[k], O[k]
        lvl = 1.0 - stop
        if armed_l:
            lvl = max(lvl, 1.03)
        if armed_t:
            lvl = max(lvl, (1.0 - trail) * hi)
        if l <= lvl:
            return min(l, lvl), min(o, lvl), "stop" if lvl <= 1.0 - stop + 1e-12 else "trail"
        if h >= 11.0:
            return 11.0, 11.0, "tp"
        hi = max(hi, h)
        armed_t = armed_t or (trail > 0 and hi >= arm)
        armed_l = armed_l or (lock > 0 and hi >= lock)
        lvl2 = 1.0 - stop
        if armed_l:
            lvl2 = max(lvl2, 1.03)
        if armed_t:
            lvl2 = max(lvl2, (1.0 - trail) * hi)
        if c <= lvl2:
            return c, lvl2, "trail"
        if k == nS - 1 and hi < stale_g:
            return c, c, "stale"
        if fade == 1 and c <= 0.85 * (C[k - 30] if k >= 30 else 1.0):
            return c, c, "drop"
        if fade == 2 and k >= 59 and v1 > 0 and V[k - 59:k + 1].sum() < 0.25 * v1:
            return c, c, "vol"
    k = min(nT, len(C)) - 1
    return C[k], C[k], "time"


g5 = np.load(os.path.join(out, "grid.npz"))
allrows = pd.read_pickle(os.path.join(out, "paths.pkl"))
ix = {r["pool"]: i for i, r in enumerate(allrows)}
P = X.var_array()
recs = []
for r in rows:
    g = bars.get(r["pool"])
    if g is None:
        continue
    mp = minute_path(r, g)
    if mp is None:
        continue
    C, Hh, L, O, V, v1 = mp
    rec = {"w": r["w"]}
    for lab, j in (("K", X.K), ("X", J)):
        a, b, why = replay_min(C, Hh, L, O, V, v1, P[j])
        rec[lab + "1"], rec[lab + "1lvl"], rec[lab + "why"] = X.money(a), X.money(b), why
        rec[lab + "5"], rec[lab + "5lvl"] = X.money(g5["M"][ix[r["pool"]], j, 0]), X.money(g5["M"][ix[r["pool"]], j, 1])
    recs.append(rec)
df = pd.DataFrame(recs)
summary = {"coins": len(df), "byWindow": {}}
for w, d in list(df.groupby("w")) + [("all", df)]:
    s = {k: round(float(d[k].mean()), 2) for k in ("K5", "X5", "K1", "X1", "K5lvl", "X5lvl", "K1lvl", "X1lvl")}
    s["n"] = len(d)
    s["diff5"], s["diff1"] = round(s["X5"] - s["K5"], 2), round(s["X1"] - s["K1"], 2)
    lo5, lo, hi = X.boot((d["X1"] - d["K1"]).to_numpy())
    s["diff1_ci95"] = [round(lo, 2), round(hi, 2)]
    s["whyX1"] = d["Xwhy"].value_counts().to_dict()
    s["whyK1"] = d["Kwhy"].value_counts().to_dict()
    summary["byWindow"][w] = s
json.dump(summary, open(os.path.join(out, "calib_minute.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
