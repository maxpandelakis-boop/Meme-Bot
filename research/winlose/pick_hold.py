"""Addendum 4 of research/winlose/PREREG-WINLOSE-2026-10-22.md (fake money only): the bot's gate passers held longer, 64 exit rules
from the one-minute bars of the first 55 hours. usage: python3 research/winlose/pick_hold.py <scratch>   (dev and holdout in one run:
the choice is made on dev before the holdout numbers are printed)"""
import glob, itertools, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..")); sys.path.insert(0, os.path.join(HERE, ".."))
import memebot as M

S = sys.argv[1]
HOLD = 1790294400000
HOLDS, STOPS, TPS = (1.7, 6, 12, 24), (None, 0.80, 0.70, 0.50), (None, 2.0, 3.0, 11.0)
RULES = list(itertools.product(HOLDS, STOPS, TPS))
d = pd.read_pickle(os.path.join(S, "d.pkl"))
gp = d[d["gates"] & ~d["gap_pre"]].drop_duplicates("mint")[["mint", "pool", "grad_ms", "ts", "h", "price_usd"]]
gap = np.load(os.path.join(S, "h2", "gap_minutes.npy")) // 60000
want = set(gp["pool"])
E_of = dict(zip(gp["pool"], ((gp["ts"] - gp["grad_ms"]) // 60000).astype(int)))
res = {}
for f in sorted(glob.glob(os.path.join(S, "cb55", "bars_*.parquet"))):
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(want)]
    for pool, g in b.groupby("pool"):
        n = int(g["mi"].max()) + 1
        mi = g["mi"].to_numpy()
        c = np.full(n, np.nan); c[mi] = g["p_close"].to_numpy(); c = pd.Series(c).ffill().to_numpy()
        hi = np.full(n, np.nan); hi[mi] = g["p_hi"].to_numpy(); hi = np.where(np.isnan(hi), c, hi)
        lo = np.full(n, np.nan); lo[mi] = g["p_lo"].to_numpy(); lo = np.where(np.isnan(lo), c, lo)
        E = E_of[pool]
        if E > n or not (c[E - 1] > 0):
            continue
        p0 = c[E - 1]
        out = []
        for H, st, tp in RULES:
            L = int(H * 60)
            seg_h, seg_l = hi[E:E + L] / p0, lo[E:E + L] / p0
            if len(seg_h) < L and E + L <= 55 * 60:
                # the pool has no more bars: its last price stands (no trade = nothing to sell into above it)
                pass
            s_ = np.nonzero(seg_l <= st)[0] if st else np.array([], int)
            t_ = np.nonzero(seg_h >= tp)[0] if tp else np.array([], int)
            if len(s_) and (not len(t_) or s_[0] <= t_[0]):
                m = float(seg_l[s_[0]])
            elif len(t_):
                m = tp
            else:
                m = float(c[min(E + L, n) - 1] / p0)
            out.append(m)
        res[pool] = out
R = gp[gp["pool"].isin(res)].copy()
mult = np.array([res[p] for p in R["pool"]])
eur = np.vectorize(lambda m: M.tip_net(max(0.0, m)))(mult)
dev = (R["grad_ms"] < HOLD).to_numpy()
# gap check: leave out coins whose 24 h after entry touch a recorder outage
gm = (R["ts"] // 60000).to_numpy()
ok = np.array([not np.isin(np.arange(t, t + 24 * 60), gap).any() for t in gm])
if "--with-outages" in sys.argv:
    ok[:] = True          # an outage only hides trades: the stop may fire late, the price at the end is still known
print("gate coins: dev %d, holdout %d (outage-free %d)" % (dev.sum(), (~dev).sum(), ok.sum()))


def st(ix, j):
    v = eur[ix, j]
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": int(len(v)), "avg": round(float(v.mean()), 3), "lo95": round(float(bs[50]), 3), "hi95": round(float(bs[1949]), 3),
            "in_profit_of10": round(10 * float((v > 0).mean()), 1), "zero": round(100 * float((mult[ix, j] < 0.02).mean()), 1),
            "x3": round(100 * float((mult[ix, j] >= 3).mean()), 1)}


name = lambda r: "hold %gh, stop %s, target %s" % (r[0], "-%d%%" % round(100 * (1 - r[1])) if r[1] else "none", "%gx" % r[2] if r[2] else "none")
A = RULES.index((6, 0.70, 11.0))
D, Hh = np.flatnonzero(dev & ok), np.flatnonzero(~dev & ok)
ref = st(D, A)
print("rule A on dev:", ref)
table = []
for j, r in enumerate(RULES):
    table.append((st(D, j), j))
table.sort(key=lambda x: -x[0]["avg"])
print("\nthe 12 best on dev:")
for s, j in table[:12]:
    print("  %-40s %s" % (name(RULES[j]), s))
best_safe = max(table, key=lambda x: (x[0]["in_profit_of10"], x[0]["avg"]))
print("most in profit on dev:", name(RULES[best_safe[1]]), best_safe[0])
cand = [x for x in table if x[0]["in_profit_of10"] >= ref["in_profit_of10"]]
choice = cand[0][1]
print("\nTHE CHOICE (dev):", name(RULES[choice]), cand[0][0])
print("\nHOLDOUT, once:")
for lab, j in (("choice", choice), ("rule A", A), ("most in profit (info)", best_safe[1])):
    print("  %-22s %-40s %s" % (lab, name(RULES[j]), st(Hh, j)))
sys.path.insert(0, os.path.join(S, "fs9"))
import importlib
FS = importlib.import_module("filter_search")
sims = {}
for lab, j in (("choice", choice), ("ruleA", A), ("safest", best_safe[1])):
    Rr = {"scan": R["ts"].to_numpy(np.float64)[Hh], "mult": mult[Hh, j]}
    s = FS.simulate(Rr, np.arange(len(Hh)))
    s and s.pop("curve")
    sims[lab] = s
    print("  sim", lab, s)
json.dump({"rules": [name(r) for r in RULES], "choice": name(RULES[choice]), "safest": name(RULES[best_safe[1]]),
           "dev": {name(RULES[j]): s for s, j in table}, "hold": {lab: st(Hh, j) for lab, j in (("choice", choice), ("ruleA", A), ("safest", best_safe[1]))},
           "sims": sims}, open(os.path.join(S, "pick_hold.json"), "w"))
