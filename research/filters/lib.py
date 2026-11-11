"""Shared by discover.py and judge.py (research/filters/PREREG-FILTERS-2026-11-11.md). Fake money only."""
import glob, json, os
import numpy as np

DISCOVERY_END = "2026-09-12"           # launch days up to here may be searched; later days are the holdout
FEATS = ["age_min", "mc", "rs_sol", "sol_per_min", "first60_share", "chg5", "dd_high", "buys5", "sells5", "buyers5", "sellers5",
         "buys_per_buyer5", "real5", "vol5_sol", "netflow5_sol", "med_buy5", "top3_share5", "n_trades", "buyers_all", "sellers_all",
         "flip_share", "top1_pct", "top10_pct", "dev_pct", "dev_buy_sol", "dev_bought", "dev_sold_frac", "dev_sold_any",
         "early10_buyers", "slot0_buys", "slot0_pct", "snipe4_buys", "snipe4_pct", "max_slot_wallets", "cr_24h", "cr_7d", "cr_grad",
         "sym_copies", "wexp_med", "wexp_new_share", "wexp_5plus_share", "hour"]
JUDGED, SECOND = "desk_fomo", "hold_fomo"
BOOT, SEED = 4000, 7


def load(rows_dir, which):
    """which: 'discovery' or 'holdout'. The discovery call never opens a holdout file."""
    rows = []
    for f in sorted(glob.glob(os.path.join(rows_dir, "rows_*.json"))):
        day = os.path.basename(f)[5:15]
        if (day <= DISCOVERY_END) != (which == "discovery"):
            continue
        rows += json.load(open(f))["rows"]
    return rows


def col(rows, k):
    return np.array([float(r[k]) for r in rows])


def boot_diff(kept_by_day, all_by_day, q=(2.5, 97.5), seed=SEED):
    """Interval by day of mean(kept) - mean(all) and of mean(kept); days resampled."""
    days = sorted(all_by_day)
    rng = np.random.default_rng(seed)
    d, m = [], []
    for _ in range(BOOT):
        pick = rng.choice(len(days), len(days))
        k = np.concatenate([kept_by_day[days[i]] for i in pick]); a = np.concatenate([all_by_day[days[i]] for i in pick])
        if len(k) == 0:
            continue
        d.append(k.mean() - a.mean()); m.append(k.mean())
    return [round(float(x), 3) for x in np.percentile(d, q)], [round(float(x), 3) for x in np.percentile(m, q)]


def judge(rows, keep, key=JUDGED):
    """Kept coins vs all base signals of the same days."""
    v = col(rows, key); days = np.array([r["day"] for r in rows]); keep = np.asarray(keep, bool)
    ud = sorted(set(days.tolist()))
    kb = {d: v[(days == d) & keep] for d in ud}; ab = {d: v[days == d] for d in ud}
    n = int(keep.sum())
    if n == 0:
        return dict(n=0)
    kv = v[keep]
    ci_d, ci_m = boot_diff(kb, ab)
    ci_d99, _ = boot_diff(kb, ab, q=(0.3, 99.7))
    beat = [float(kb[d].mean() - ab[d].mean()) for d in ud if len(kb[d])]
    big = max(ud, key=lambda d: abs(kb[d].sum()))
    rest = np.concatenate([kb[d] for d in ud if d != big])
    return dict(n=n, share=round(n / len(v), 3), per_day=round(n / len(ud), 1), avg=round(float(kv.mean()), 3), ci=ci_m,
                base=round(float(v.mean()), 3), lift=round(float(kv.mean() - v.mean()), 3), lift_ci=ci_d, lift_ci99=ci_d99,
                days_beat=[int(sum(x > 0 for x in beat)), len(beat)], days_pos=int(sum(kb[d].mean() > 0 for d in ud if len(kb[d]))),
                without_best=round(float(np.delete(kv, int(np.argmax(kv))).mean()), 3) if n > 1 else None,
                without_biggest_day=[big, round(float(rest.mean()), 3) if len(rest) else None],
                in_profit=round(float((kv > 0).mean()) * 100, 1), median=round(float(np.median(kv)), 3))


def fixed_filters(rows, f5_median):
    f1 = col(rows, "cr_24h") >= 3
    f2 = col(rows, "early10_buyers") == 0
    f3 = (col(rows, "dev_bought") > 0) & (col(rows, "dev_sold_frac") >= 0.9)
    return {"F1 no launch factory (creator <3 coins in 24 h)": ~f1, "F2 early demand (a non-creator buyer in 10 s)": ~f2,
            "F3 dev did not dump (sold <90%)": ~f3, "F4 none of F1-F3": ~(f1 | f2 | f3),
            "F5 slow curve (SOL/min below discovery median)": col(rows, "sol_per_min") < f5_median}


# ---- the score M: logistic regression on rank-like features (clipped z-scores of log1p-shaped values), numpy only
def shape(rows, stats=None):
    X = np.stack([col(rows, k) for k in FEATS], axis=1)
    X = np.sign(X) * np.log1p(np.abs(X))
    if stats is None:
        stats = (X.mean(0), X.std(0) + 1e-9)
    Z = np.clip((X - stats[0]) / stats[1], -4, 4)
    return np.concatenate([Z, np.ones((len(Z), 1))], axis=1), stats


def fit_logit(Z, y, l2=10.0, iters=60):
    w = np.zeros(Z.shape[1])
    R = np.eye(Z.shape[1]) * l2; R[-1, -1] = 0
    for _ in range(iters):
        pr = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (pr - y) + R @ w
        Hs = (Z * (pr * (1 - pr))[:, None]).T @ Z + R
        step = np.linalg.solve(Hs, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w
