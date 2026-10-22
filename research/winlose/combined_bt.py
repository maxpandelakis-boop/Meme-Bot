"""Winner/loser study, all signals together on the bot's own scans (addendum of PREREG-WINLOSE-2026-10-22.md; fake money only).
usage: python3 research/winlose/combined_bt.py <memesnapres dir> [--holdout]"""
import os, sys
import numpy as np
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", ".."))
import filter_search as FS
from filtersearch_bt import ALL

HOLD, DAY = 1792281600000, 86_400_000          # 18 Oct
CUTS = (0.02, 0.05, 0.10, 0.20)
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)
R = FS.load(sys.argv[1], features=ALL)
X = np.column_stack([R[k] for k in ALL])
move = (R["mult"] >= 2) | (R["mult"] <= 0.2)
up = R["mult"] >= 2
day = (R["scan"] // DAY).astype(int)
print("rows %d coins %d days %d..%d" % (len(day), R["coin"].max() + 1, day.min(), day.max()))


def scores(tr, te):
    reg = lgb.LGBMRegressor(**P).fit(X[tr], np.clip(R["r"][tr], -20, 60))
    cm = lgb.LGBMClassifier(**P).fit(X[tr], move[tr])
    tm = tr[move[tr]]
    cu = lgb.LGBMClassifier(**P).fit(X[tm], up[tm])
    f = lambda ix: {"reg": reg.predict(X[ix]), "two": cm.predict_proba(X[ix])[:, 1] * cu.predict_proba(X[ix])[:, 1]}
    return f(tr), f(te), reg


def pick(te, s, cut):
    m = np.zeros(len(day), bool); m[te[s >= cut]] = True
    return FS.entries(R, m)


def gates(te):
    m = np.zeros(len(day), bool); m[te] = True
    return FS.entries(R, m & R["pass"])


if "--holdout" not in sys.argv:
    acc = {(s, c): [] for s in ("reg", "two") for c in CUTS}
    g = []
    for d0 in range(int((1791676800000) // DAY) + 4, int(HOLD // DAY)):          # from 11 Oct
        tr, te = np.flatnonzero(day < d0), np.flatnonzero(day == d0)
        if not len(te):
            continue
        s_tr, s_te, reg = scores(tr, te)
        for s in ("reg", "two"):
            for c in CUTS:
                acc[(s, c)].append(pick(te, s_te[s], np.quantile(s_tr[s], 1 - c)))
        g.append(gates(te))
        print("day", d0, "train", len(tr), "test", len(te), flush=True)
    print("gates", FS.stats(R, np.concatenate(g)))
    best = None
    for k, v in acc.items():
        st = FS.stats(R, np.concatenate(v))
        print(k, st)
        if st["n"] >= 100 and (best is None or st["avg"] > best[1]["avg"]):
            best = (k, st)
    print("THE CHOICE", best)
    open(os.path.join(HERE, "..", "..", ".combined_choice"), "w").write("%s %g" % best[0])
    imp = sorted(zip(reg.feature_importances_, ALL), reverse=True)[:20]
    print("importance (last fold):", imp)
else:
    s, c = open(os.path.join(HERE, "..", "..", ".combined_choice")).read().split()
    tr, te = np.flatnonzero(day < HOLD // DAY), np.flatnonzero(day >= HOLD // DAY)
    s_tr, s_te, _ = scores(tr, te)
    print("gates HOLDOUT", FS.stats(R, gates(te)))
    for k in ("reg", "two"):
        for cc in CUTS:
            st = FS.stats(R, pick(te, s_te[k], np.quantile(s_tr[k], 1 - cc)))
            print(("CHOICE " if (k == s and abs(cc - float(c)) < 1e-9) else "       ") + "%s %g" % (k, cc), st)
