"""Discovery for the filter study: searches filters on the discovery days only and writes frozen.json. Fake money only.
usage: python3 research/filters/discover.py <rows dir> <out dir>"""
import json, os, sys
import numpy as np
from lib import *

rows = load(sys.argv[1], "discovery")
out = sys.argv[2]; os.makedirs(out, exist_ok=True)
L = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
days = np.array([r["day"] for r in rows]); ud = sorted(set(days.tolist()))
v = col(rows, JUDGED); v2 = col(rows, SECOND)
p("discovery days", len(ud), ud[0], "to", ud[-1], "base signals", len(rows), "per day", round(len(rows) / len(ud)))
p("base: desk per 20", round(v.mean(), 3), "hold", round(v2.mean(), 3), "quick", round(col(rows, "scal_fomo").mean(), 3),
  "desk jup", round(col(rows, "desk_jup").mean(), 3), "| in profit %", round((v > 0).mean() * 100, 1), "| completes %", round(np.mean([r["grad"] for r in rows]) * 100, 1))
p("exits", {h: int(sum(r["how"] == h for r in rows)) for h in sorted(set(r["how"] for r in rows))})
p("median age", np.median(col(rows, "age_min")), "median mc", np.median(col(rows, "mc")))

f5_median = float(np.median(col(rows, "sol_per_min")))
p("\n== fixed filters on discovery (information; judged on the holdout)")
for name, keep in fixed_filters(rows, f5_median).items():
    j = judge(rows, keep); j2 = judge(rows, keep, SECOND)
    p(name, "| kept", j["share"], "avg", j["avg"], "lift", j["lift"], j["lift_ci"], "days beat", j["days_beat"], "| hold lift", j2["lift"], j2["lift_ci"])

# ---- single features, walk-forward: the cut is fitted on earlier days, judged on the next block of 3 days
QS = [20, 30, 40, 50, 60, 70, 75]
def best_cut(x, y):
    """Among quantile cuts and both directions (kept share >= 25%), the one with the best average of the kept."""
    best = None
    for q in QS:
        c = float(np.percentile(x, q))
        for d in (1, -1):
            keep = x >= c if d == 1 else x <= c
            if keep.mean() < 0.25 or keep.mean() > 0.9 or keep.sum() < 30:
                continue
            m = y[keep].mean()
            if best is None or m > best[0]:
                best = (m, c, d)
    return best
START, BLOCK = 9, 3
res = []
for k in FEATS:
    x = col(rows, k)
    keep_oos = np.zeros(len(rows), bool); seen = np.zeros(len(rows), bool); dirs = []
    for b in range(START, len(ud), BLOCK):
        tr = np.isin(days, ud[:b]); te = np.isin(days, ud[b:b + BLOCK])
        bc = best_cut(x[tr], v[tr])
        if bc is None:
            continue
        _, c, d = bc
        keep_oos[te] = (x[te] >= c) if d == 1 else (x[te] <= c); seen[te] = True; dirs.append(d)
    if not seen.any() or keep_oos[seen].sum() < 30:
        continue
    sub = [r for r, s in zip(rows, seen) if s]
    j = judge(sub, keep_oos[seen]); j2 = judge(sub, keep_oos[seen], SECOND)
    res.append((j["lift"], k, j, j2, dirs))
res.sort(key=lambda t: -t[0])
p("\n== single features, walk-forward out of sample (days %s on)" % ud[START])
for lift, k, j, j2, dirs in res:
    p("%-18s lift %+.3f %s kept %.2f avg %+.3f days beat %s | hold lift %+.3f %s | dirs %s" % (k, lift, j["lift_ci"], j["share"], j["avg"], j["days_beat"], j2["lift"], j2["lift_ci"], "".join("+" if d > 0 else "-" for d in dirs)))

# D1..D3: the best three by walk-forward lift whose interval is above 0, whose direction never flipped, and whose second exit agrees
picks, pick_keeps = [], []
for lift, k, j, j2, dirs in res:
    if len(picks) == 3:
        break
    if j["lift_ci"][0] > 0 and len(set(dirs)) == 1 and j2["lift"] > 0:
        bc = best_cut(col(rows, k), v)
        if bc is None or bc[2] != dirs[0]:
            continue
        kp = col(rows, k) >= bc[1] if bc[2] == 1 else col(rows, k) <= bc[1]
        if any((kp & q).sum() / max((kp | q).sum(), 1) > 0.8 for q in pick_keeps):      # not the same coins as an earlier pick
            continue
        pick_keeps.append(kp)
        picks.append(dict(feat=k, cut=bc[1], dir=bc[2], wf_lift=lift, wf_ci=j["lift_ci"]))
p("\nD picks:", json.dumps(picks))

# ---- the score M, walk-forward then final
y = (v > 0).astype(float)
keep_oos = np.zeros(len(rows), bool); seen = np.zeros(len(rows), bool); sc_oos = np.zeros(len(rows))
for b in range(START, len(ud), BLOCK):
    tr = np.isin(days, ud[:b]); te = np.isin(days, ud[b:b + BLOCK])
    Ztr, st = shape([r for r, s in zip(rows, tr) if s]); w = fit_logit(Ztr, y[tr])
    Zte, _ = shape([r for r, s in zip(rows, te) if s], st)
    thr = float(np.percentile(Ztr @ w, 70))
    sc_oos[te] = Zte @ w; keep_oos[te] = (Zte @ w) >= thr; seen[te] = True
sub = [r for r, s in zip(rows, seen) if s]
jm = judge(sub, keep_oos[seen]); jm2 = judge(sub, keep_oos[seen], SECOND)
p("\n== score M walk-forward: kept", jm["share"], "avg", jm["avg"], "lift", jm["lift"], jm["lift_ci"], "days beat", jm["days_beat"], "| hold lift", jm2["lift"], jm2["lift_ci"])
for lo, hi in [(0, 50), (50, 70), (70, 90), (90, 100)]:
    s = sc_oos[seen]; a, b_ = np.percentile(s, lo), np.percentile(s, hi)
    mk = (s >= a) & (s <= b_)
    p("  score pct %d-%d: n %d desk %+.3f hold %+.3f in profit %.1f%%" % (lo, hi, mk.sum(), v[seen][mk].mean(), v2[seen][mk].mean(), (v[seen][mk] > 0).mean() * 100))
Z, st = shape(rows); w = fit_logit(Z, y)
thr = float(np.percentile(Z @ w, 70))
order = np.argsort(-np.abs(w[:-1]))
p("weights (largest):", ", ".join("%s %+.2f" % (FEATS[i], w[i]) for i in order[:14]))
json.dump(dict(f5_median=f5_median, picks=picks, model=dict(feats=FEATS, mean=st[0].tolist(), std=st[1].tolist(), w=w.tolist(), thr=thr),
               discovery_days=[ud[0], ud[-1]], base=dict(n=len(rows), desk=float(v.mean()), hold=float(v2.mean()))),
          open(os.path.join(out, "frozen.json"), "w"), indent=1)
open(os.path.join(out, "discovery.txt"), "w").write("\n".join(L) + "\n")
