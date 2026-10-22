"""The pre-registered big filter search on history2 (research/PREREG-SEARCH-2026-10-21.md; fake money only).
usage: python3 research/filtersearch_h2.py <history2 dir, hourly/*.parquet in it>      (needs numpy, pandas, pyarrow; ~2 min, 4 GB)

123,120 combinations (6,840 rules x 6 age windows x 3 exits), chosen on train (graduated before 1 Sep) and check (1 to 20 Sep),
the one choice tested once on the holdout (from 21 Sep), next to the bot's gates and the new launches (1 h after graduation).
"""
import glob, itertools, math, os, sys
import numpy as np, pandas as pd

FEE = 0.01                    # per buy and per sell
SPL1, SPL2 = 1788220800000, 1789948800000     # 2026-09-01, 2026-09-21 00:00 UTC (by graduation)
AGES = {"new(1h)": (1, 1), "2-3h": (2, 3), "4-6h": (4, 6), "6-24h(bot)": (6, 24), "24-48h": (24, 48), "any": (1, 48)}
EXITS = ("hold", "A", "B")


def load(src):
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(src, "hourly", "*.parquet")))], ignore_index=True)
    d = d[~d.gap_pre & ~d.gap_1 & ~d.gap_6 & d.last6.notna() & d.px1.notna() & (d.liquidity_usd >= 5000)]
    d = d.sort_values(["mint", "ts"]).reset_index(drop=True)
    net = lambda m: 20 * (1 - FEE) ** 2 * np.asarray(m) - 20

    def ex(stop, tp, tpx):
        s, t = d[stop + "_min"].to_numpy(), d[tp + "_min"].to_numpy()
        return np.where(~np.isnan(s) & (np.isnan(t) | (s <= t)), d[stop + "_x"].to_numpy(), np.where(~np.isnan(t), tpx, d.last6.to_numpy()))
    d["r_hold"] = net(np.minimum(d.px1 / d.price_usd, 11.0))
    d["r_A"], d["r_B"] = net(ex("stop30", "tp11", 11.0)), net(ex("stop20", "tp3", 3.0))
    d["zero"], d["hit3"] = (d.px1 / d.price_usd) < 0.02, d.tp3_min.notna()
    d["per"] = np.where(d.grad_ms < SPL1, 0, np.where(d.grad_ms < SPL2, 1, 2))
    return d


def features(d):
    tx = (d.buys_1h + d.sells_1h).replace(0, np.nan)
    return {"mc": d.market_cap_usd, "liqmc": d.liquidity_usd / d.market_cap_usd, "volmc": d.volume_24h / d.market_cap_usd,
            "vol1share": d.volume_1h / d.volume_24h.replace(0, np.nan), "c5m": d.price_change_5m, "c1": d.price_change_1h, "c6": d.price_change_6h,
            "c24": d.price_change_24h, "buyshare": d.buys_1h / tx, "buyers": d.buyers_1h, "topbuyer": d.top_buyer_share_1h, "atomic": d.atomic_1h / tx,
            "idle": d.last_trade_s, "liq": d.liquidity_usd, "vol1": d.volume_1h}


def main():
    d = load(sys.argv[1])
    F = features(d)
    coin, per, age = pd.factorize(d.mint)[0], d.per.to_numpy(), d.age_h.to_numpy()
    R = {e: d["r_" + e].to_numpy() for e in EXITS}
    Z, H3 = d.zero.to_numpy(), d.hit3.to_numpy()

    def first(mask):
        idx = np.flatnonzero(mask)
        _, f = np.unique(coin[idx], return_index=True)
        return idx[f]

    def st(ix, e):
        if not len(ix):
            return {"n": 0}
        r = R[e][ix]
        return {"n": len(ix), "avg": float(r.mean()), "se": float(r.std(ddof=1) / math.sqrt(len(ix))) if len(ix) > 1 else 9.0,
                "zero": float(Z[ix].mean()), "hit3": float(H3[ix].mean())}

    conds = []
    for k, v in F.items():
        v = v.to_numpy(dtype="float64")
        for q in np.nanquantile(v[per == 0], [0.2, 0.4, 0.6, 0.8]):
            conds += [("%s<=%.4g" % (k, q), k, v <= q), ("%s>=%.4g" % (k, q), k, v >= q)]
    rules = [("(no filter)", np.ones(len(d), bool))] + [(c[0], c[2]) for c in conds] + [
        (a[0] + " & " + b[0], a[2] & b[2]) for a, b in itertools.combinations(conds, 2) if a[1] != b[1]]
    print("%d rules x %d ages x %d exits = %d combinations" % (len(rules) - 1, len(AGES), len(EXITS), (len(rules) - 1) * len(AGES) * len(EXITS)))
    cand = []
    for an, (lo, hi) in AGES.items():
        am = (age >= lo) & (age <= hi)
        for name, m in rules:
            ix = [first(m & am & (per == p)) for p in (0, 1)]
            for e in EXITS:
                a, b = st(ix[0], e), st(ix[1], e)
                if a["n"] >= 200 and b["n"] >= 100:
                    cand.append((min(a["avg"], b["avg"]), name, an, e, a, b))
    ps = sorted(0.5 * (1 - math.erf((c[5]["avg"] / c[5]["se"]) / math.sqrt(2))) for c in cand)
    holm = next((i for i, p in enumerate(ps) if p > 0.05 / (len(ps) - i)), len(ps))
    cand.sort(key=lambda c: -c[0])
    print("candidates %d; positive on train and check %d; Holm survivors at 5%%: %d" % (len(cand), sum(1 for c in cand if c[4]["avg"] > 0 and c[5]["avg"] > 0), holm))
    for c in cand[:10]:
        print("  %-45s %-10s %-4s train %+.2f (n %d, 3x %.1f%%) check %+.2f (n %d, 3x %.1f%%)" % (c[1], c[2], c[3], c[4]["avg"], c[4]["n"], 100 * c[4]["hit3"], c[5]["avg"], c[5]["n"], 100 * c[5]["hit3"]))
    best = cand[0]
    mc, liq, vol = d.market_cap_usd, d.liquidity_usd, d.volume_24h
    gates = ((d.age_h >= 6) & (d.age_h <= 24) & (mc >= 100_000) & (mc <= 2_000_000) & (liq >= 15_000) & (vol >= 15_000) & ~(d.price_change_1h <= -40)
             & ~(d.price_change_6h <= -50) & ~(d.price_change_24h <= -70) & ~(d.price_change_1h >= 150) & ~(d.price_change_6h >= 400)).to_numpy()
    lo, hi = AGES[best[2]]
    choice = dict(rules)[best[1]] & (age >= lo) & (age <= hi)
    rng = np.random.default_rng(7)
    print("\nTHE CHOICE: %s, %s, exit %s; the holdout once:" % best[1:4])
    for name, m in (("choice", choice), ("bot gates", gates), ("new launches (1 h)", age == 1)):
        for p in (0, 1, 2):
            ix = first(m & (per == p))
            v = R[best[3]][ix]
            b = np.sort(v[rng.integers(0, len(v), size=(4000, len(v)))].mean(axis=1)) if len(v) > 2 else [np.nan] * 4000
            print("  %-20s %s n %5d  %+.2f per 20 (95%% %+.2f to %+.2f)  to zero %.1f%%  3x %.1f%%" % (
                name, ("train", "check", "HOLDOUT")[p], len(ix), v.mean(), b[100], b[3899], 100 * Z[ix].mean(), 100 * H3[ix].mean()))


if __name__ == "__main__":
    main()
