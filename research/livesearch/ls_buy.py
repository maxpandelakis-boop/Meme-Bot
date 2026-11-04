#!/usr/bin/env python3
"""ls_buy.py: family F3 of the live-data rule search (PREREG-LIVESEARCH-2026-11-04.md): buy filters on the big test (every coin of
every hourly scan, 22 Oct 10:08 UTC on, price about 2 h later). A window (filter_search.WINDOWS, plus the Learning Pick's universe)
and one or two of filter_search.FEATURES at or under / at or over a FIT quartile of the window; one entry per coin and UTC day (the
first scan it passes); result per 50 EUR = 50 x 0.99^2 x min(mult, 11) - 50 (a coin without a price 2 h later counts as 0).
F3r: per scan the gate passer ranked first by one big-test factor (up or down), one entry per coin and day.

  python3 ls_buy.py --data <ls_build out> --out <dir>
"""
import argparse, itertools, os, pickle, sys
from multiprocessing import Pool
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import filter_search as FS

SPLIT = 1793404800000
TICKET, FEE, CAP = 50.0, 0.01, 11.0
QS = (0.25, 0.50, 0.75)
MIN_FIT = 60
DAY = 86_400_000
G = {}


def build(bt):
    feats = list(FS.FEATURES)
    allf = sorted({k for r in bt for k in r["f"]})
    R = {"scan": np.array([r["scan"] for r in bt], dtype=float), "pass": np.array([r["pass"] for r in bt]),
         "mult": np.array([r["mult"] for r in bt], dtype=float), "gone": np.array([r["gone"] for r in bt]),
         "liq": np.array([r["liq"] for r in bt], dtype=float), "mc": np.array([r["mc"] for r in bt], dtype=float),
         "sc": np.array([r["sc"] if r["sc"] is not None else np.nan for r in bt], dtype=float)}
    for k in allf:
        R[k] = np.array([r["f"].get(k, np.nan) for r in bt], dtype=float)
    _, coin = np.unique(np.array([r["a"] for r in bt], dtype=object), return_inverse=True)
    R["key"] = coin.astype(np.int64) * 1000 + (R["scan"] // DAY).astype(np.int64)
    m = np.where(R["gone"], 0.0, np.minimum(R["mult"], CAP))
    R["r"] = TICKET * (1 - FEE) ** 2 * m - TICKET
    return R, feats, allf


def windows(R):
    age = R["ageH"]
    w = {"new": (age >= 0) & (age < 1), "1-6h": (age >= 1) & (age < 6), "6-24h": (age >= 6) & (age <= 24), "24h+": age > 24,
         "any": np.ones(len(age), bool), "gates": R["pass"]}
    w["lern"] = ((age >= 1) & (age <= 72) & (R["volMc"] >= 0.1) & (R["liq"] >= 15_000) & (R["mc"] >= 50_000) & (R["mc"] <= 2_000_000))
    return w


def first_entries(mask):
    """Indices of the first row per coin and day among the masked rows (rows are in scan order)."""
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return idx
    _, first = np.unique(G["R"]["key"][idx], return_index=True)
    return idx[np.sort(first)]


def score(mask):
    idx = first_entries(mask)
    fit = G["R"]["scan"][idx] < SPLIT
    r = G["R"]["r"][idx]
    nf, nc = int(fit.sum()), int((~fit).sum())
    if nf < MIN_FIT:
        return None
    rc = r[~fit]
    return (nf, float(r[fit].mean()), nc, float(rc.mean()) if nc else np.nan,
            float((rc.sum() - rc.max()) / (nc - 1)) if nc > 1 else np.nan)


def job(spec):
    wname, conds = spec
    m = G["W"][wname].copy()
    for k, op, thr in conds:
        v = G["R"][k]
        m &= (v <= thr) if op == "<=" else (v >= thr)
    return spec, score(m)


def init(R, W):
    G["R"], G["W"] = R, W


def rank_rules(R):
    """F3r: per scan the gate passer ranked first by one factor, up or down."""
    out = []
    passers = np.nonzero(R["pass"])[0]
    scans = R["scan"][passers]
    for k in [k for k in R if k not in ("scan", "pass", "mult", "gone", "key", "r")]:
        v = R[k][passers]
        if np.isnan(v).mean() > 0.5:
            continue
        for sign in (1, -1):
            best = {}
            for i, s, x in zip(passers, scans, v):
                if np.isnan(x):
                    continue
                if s not in best or sign * x > sign * R[k][best[s]]:
                    best[s] = i
            m = np.zeros(len(R["r"]), bool)
            m[list(best.values())] = True
            out.append(((k, "top" if sign > 0 else "bottom"), score(m)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    bt = pickle.load(open(os.path.join(a.data, "bt.pkl"), "rb"))
    R, feats, allf = build(bt)
    del bt
    W = windows(R)
    G["R"], G["W"] = R, W
    feats = [k for k in feats if k in R]
    specs = []
    fitmask = R["scan"] < SPLIT
    for wname, wm in W.items():
        singles = []
        for k in feats:
            v = R[k][wm & fitmask]
            v = v[~np.isnan(v)]
            if len(v) < 200 or len(np.unique(v)) < 4:
                continue
            for q in QS:
                thr = float(np.quantile(v, q))
                for op in ("<=", ">="):
                    singles.append((k, op, round(thr, 6)))
        specs.append((wname, ()))
        specs += [(wname, (c,)) for c in singles]
        specs += [(wname, (c1, c2)) for c1, c2 in itertools.combinations(singles, 2) if c1[0] != c2[0]]
    print("rules", len(specs), flush=True)
    with Pool(4, initializer=init, initargs=(R, W)) as pool:
        res = [x for x in pool.imap_unordered(job, specs, chunksize=64) if x[1] is not None]
    rr = [x for x in rank_rules(R) if x[1] is not None]
    pickle.dump({"res": res, "rank": rr}, open(os.path.join(a.out, "f3.pkl"), "wb"))
    print("scored", len(res), "rank rules", len(rr), flush=True)


if __name__ == "__main__":
    main()
