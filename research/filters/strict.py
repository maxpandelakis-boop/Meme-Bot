"""Amendment 2 of the filter study: the desk's strict picker (watch 10 to 40 minutes) against buying at first sight. Fake money only.
usage: python3 research/filters/strict.py <rows dir> <out dir>"""
import json, os, sys
import numpy as np
from lib import *

out = sys.argv[2]; os.makedirs(out, exist_ok=True)
L = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
def boot(by, f, q=(2.5, 97.5)):
    days = sorted(by); rng = np.random.default_rng(SEED); r = []
    for _ in range(BOOT):
        pick = rng.choice(len(days), len(days))
        try: r.append(f([by[days[i]] for i in pick]))
        except ValueError: pass
    return [round(float(x), 3) for x in np.percentile(r, q)]
res = {}
for which in ("discovery", "holdout"):
    rows = load(sys.argv[1], which)
    ud = sorted(set(r["day"] for r in rows))
    base = col(rows, JUDGED)
    p("\n==== %s: %d days, first-sight signals %d (%.0f a day), per 20: desk %+.3f, without FOMO fee %+.3f" % (which, len(ud), len(rows), len(rows) / len(ud), base.mean(), col(rows, "desk_jup").mean()))
    veto0 = (col(rows, "cr_24h") == 0) & (col(rows, "top1_pct") < 20)
    p("first sight with the veto: kept %.0f%% desk %+.3f" % (veto0.mean() * 100, base[veto0].mean()))
    S = [r for r in rows if r.get("strict")]
    sets = {"S1 strict (watch 10-40 min)": S, "S2 strict + veto": [r for r in S if r["cr_24h"] == 0 and r["strict"]["top1_pct"] < 20]}
    res[which] = {}
    for name, sel in sets.items():
        if len(sel) < 2:
            p(name, "| buys", len(sel)); continue
        v = np.array([r["strict"]["desk_fomo"] for r in sel]); h = np.array([r["strict"]["hold_fomo"] for r in sel]); jv = np.array([r["strict"]["desk_jup"] for r in sel])
        by = {d: (np.array([r["strict"]["desk_fomo"] for r in sel if r["day"] == d]), np.array([r[JUDGED] for r in rows if r["day"] == d])) for d in ud}
        byj = {d: (np.array([r["strict"]["desk_jup"] for r in sel if r["day"] == d]),) for d in ud}
        ci = boot(by, lambda xs: np.concatenate([x[0] for x in xs]).mean())
        cid = boot(by, lambda xs: np.concatenate([x[0] for x in xs]).mean() - np.concatenate([x[1] for x in xs]).mean())
        cij = boot(byj, lambda xs: np.concatenate([x[0] for x in xs]).mean())
        dpos = sum(1 for d in ud if len(by[d][0]) and by[d][0].mean() > 0); dbeat = sum(1 for d in ud if len(by[d][0]) and by[d][0].mean() > by[d][1].mean())
        hows = {k: round(float(np.mean([r["strict"]["how"] == k for r in sel])) * 100, 1) for k in ("stop", "trail", "end", "2x+end")}
        own = np.array([r[JUDGED] for r in sel])
        res[which][name] = dict(n=len(sel), per_day=len(sel) / len(ud), avg=float(v.mean()), ci=ci, lift=float(v.mean() - base.mean()), lift_ci=cid, jup=float(jv.mean()), jup_ci=cij,
                                without_best=float(np.delete(v, int(np.argmax(v))).mean()), days_pos=dpos, days_beat=dbeat, days=len(ud))
        p("%s\n    buys %d (%.0f a day, %.1f%% of first-sight signals) | desk %+.3f %s | vs first sight %+.3f %s | days in profit %d/%d, better than first sight %d/%d | without best %+.3f | in profit %.1f%% | exits %s\n    hold %+.3f | without FOMO fee %+.3f %s | median wait %d min, median price vs first sight %.2fx, median MC %.0f | the same coins bought at first sight: %+.3f" % (
            name, len(sel), len(sel) / len(ud), len(sel) / len(rows) * 100, v.mean(), ci, v.mean() - base.mean(), cid, dpos, len(ud), dbeat, len(ud), np.delete(v, int(np.argmax(v))).mean(),
            (v > 0).mean() * 100, hows, h.mean(), jv.mean(), cij, np.median([r["strict"]["wait_min"] for r in sel]), np.median([r["strict"]["up"] for r in sel]), np.median([r["strict"]["mc"] for r in sel]), own.mean()))
json.dump(res, open(os.path.join(out, "strict.json"), "w"), indent=1)
open(os.path.join(out, "strict.txt"), "w").write("\n".join(L) + "\n")
