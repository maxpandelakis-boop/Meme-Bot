"""The pre-registered smart-wallet test of research/PREREG-WALLETS-2026-10-21.md (fake money only), on the pairs of the branch
"wallets" (research/wallet_build.py). Written before those pairs were looked at.
usage: python3 research/check_wallets.py <wallets dir> [<history2 dir> for the information on the bot's gates] [out.json]
(needs numpy, pandas and pyarrow)
"""
import glob, itertools, json, os, sys
import numpy as np, pandas as pd

S0 = 1786320000000         # 2026-08-10 00:00 UTC
C0 = 1788220800000         # 2026-09-01 00:00 UTC
T0 = 1789430400000         # 2026-09-15 00:00 UTC (the history2 split)
SETTLE = 55 * 3600_000     # a scored pair's coin graduated at least this long before the period it is used on
FEE_RT = 0.02              # round trip, the judged fee
CLIP = (-20.0, 60.0)
D_SEARCH = 5
EXITS = {"hold": "h", "A": "a", "B": "b"}
NS = (5, 10, 20)
SCORES = [("copy", t) for t in (0.0, 2.0, 5.0)] + [("hits", h) for h in (0.10, 0.20)] + [("own", r) for r in (1.2, 1.5)]
KS = (1, 2)
C_MIN, T_MIN = 100, 100
BOT_SHARE = 0.20
BOOT_N, SEED = 2000, 7


def eur(m, fee_rt=FEE_RT, clip=True):
    f = fee_rt / 2.0
    v = 20.0 * (np.asarray(m, dtype="float64") * (1 - f) * (1 - f) - 1.0)
    return np.clip(v, *CLIP) if clip else v


def load(wdir):
    files = sorted(glob.glob(os.path.join(wdir, "**", "pairs_*.parquet"), recursive=True))
    p = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return p.sort_values(["coin", "t_q"], kind="stable").reset_index(drop=True)


def valid(p, ex, d):
    """Copies that can be judged under exit ex at delay d: a price, no outage in the window."""
    ok = p["p%d" % d].notna() & (p["p%d" % d] > 0)
    return ok & ~(p["g1"] if ex == "hold" else p["g6"])


def smart(p, upto, n_min, score, ex, d=D_SEARCH):
    """The smart wallets scored on the pairs of coins graduated at least SETTLE before upto."""
    s = p[(p["grad_ms"] + SETTLE <= upto)]
    kind, thr = score
    if kind == "copy":
        s = s[valid(s, ex, d)]
        v = pd.Series(eur(s[EXITS[ex] + str(d)]), index=s.index)
    elif kind == "hits":
        s = s[valid(s, "A", d)]
        v = (s["x%d" % d] >= 3.0).astype(float)
    else:
        s = s[s["roi"].notna() & (s["sol_in"] > 0)]
        v = s["roi"].astype(float)
    coins = s["coin"].nunique()
    g = v.groupby(s["wid"]).agg(["size", "mean"])
    g = g[(g["size"] >= n_min) & (g["size"] <= BOT_SHARE * max(coins, 1)) & (g["mean"] >= thr)]
    return set(g.index.tolist())


def signals(p, lo, hi, wallets, k, ex, d=D_SEARCH):
    """One copy per coin of the period: the k-th smart wallet's buy, copied d minutes later."""
    s = p[(p["grad_ms"] >= lo) & (p["grad_ms"] < hi) & p["wid"].isin(wallets)]
    s = s.assign(rank=s.groupby("coin").cumcount() + 1)
    s = s[s["rank"] == k]
    return s[valid(s, ex, d)]


def stats(s, ex, d=D_SEARCH, fee_rt=FEE_RT, clip=True, boot=False):
    n = len(s)
    if not n:
        return {"coins": 0}
    v = eur(s[EXITS[ex] + str(d)], fee_rt, clip)
    out = {"coins": n, "avg": round(float(v.mean()), 3), "win": round(100.0 * float((v > 0).mean()), 1),
           "hit3": round(100.0 * float(((s["x%d" % d] >= 3.0) & ~s["g6"]).mean()), 1),
           "zero": round(100.0 * float((s["h%d" % d] < 0.02).mean()), 1)}
    if boot:
        rng = np.random.default_rng(SEED)
        m = np.sort(np.array([v[rng.integers(0, n, n)].mean() for _ in range(BOOT_N)]))
        out["ci"] = [round(float(m[int(0.025 * BOOT_N)]), 3), round(float(m[int(0.975 * BOOT_N) - 1]), 3)]
    return out


def base(p, lo, hi, ex, d=D_SEARCH):
    """Every coin of the period copied at one of its pairs, picked at random (seed 7): a copy of any wallet."""
    s = p[(p["grad_ms"] >= lo) & (p["grad_ms"] < hi)]
    s = s[valid(s, ex, d)]
    rng = np.random.default_rng(SEED)
    s = s.assign(r=rng.random(len(s))).sort_values(["coin", "r"]).drop_duplicates("coin")
    return s


def gate_rows(h2dir, s, d):
    """Information: of the copies s, those whose coin passed the bot's gates in the history2 row of the hour before the copy."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import check_history2 as CH
    files = sorted(glob.glob(os.path.join(h2dir, "**", "hourly_*.parquet"), recursive=True))
    cols = ["mint", "ts", "age_h", "market_cap_usd", "liquidity_usd", "volume_24h", "price_change_1h", "price_change_6h", "price_change_24h"]
    rows = pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)
    rows = rows[CH.bot_gates(rows)]
    x = s["t_q"] + d * 60_000
    m = s.assign(x=x).merge(rows[["mint", "ts"]], on="mint", how="inner")
    m = m[(m["ts"] <= m["x"]) & (m["ts"] > m["x"] - 3600_000)]
    return s[s["coin"].isin(set(m["coin"]))]


def main():
    wdir = sys.argv[1]
    h2dir = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    out_json = sys.argv[3] if len(sys.argv) > 3 else None
    p = load(wdir)
    coins = pd.read_parquet(glob.glob(os.path.join(wdir, "**", "coins.parquet"), recursive=True)[0])
    p["mint"] = coins.set_index("coin")["mint"].reindex(p["coin"]).to_numpy()
    print("pairs %d, wallets %d, coins %d; S %d, C %d, T %d coins" % (
        len(p), p["wid"].nunique(), p["coin"].nunique(), p.loc[p["grad_ms"] < C0, "coin"].nunique(),
        p.loc[(p["grad_ms"] >= C0) & (p["grad_ms"] < T0), "coin"].nunique(), p.loc[p["grad_ms"] >= T0, "coin"].nunique()))
    res = {"search": [], "base": {}}

    # the search: wallets scored on S, signals on C
    cache = {}
    for n_min, score, k, ex in itertools.product(NS, SCORES, KS, EXITS):
        key = (n_min, score, ex if score[0] == "copy" else None)
        if key not in cache:
            cache[key] = smart(p, C0, n_min, score, ex)
        w = cache[key]
        st = stats(signals(p, C0, T0, w, k, ex), ex)
        res["search"].append({"N": n_min, "score": "%s>=%g" % score, "K": k, "exit": ex, "wallets": len(w), **st})
    srch = pd.DataFrame(res["search"])
    elig = srch[srch["coins"] >= C_MIN].sort_values("avg", ascending=False)
    print("\nsearch on C (wallets from S), %d rules, %d eligible (>= %d coins); the best 15:" % (len(srch), len(elig), C_MIN))
    print(elig.head(15).to_string(index=False))
    for ex in EXITS:
        b = base(p, C0, T0, ex)
        res["base"]["C_" + ex] = stats(b, ex)
    print("base on C:", json.dumps({k: v for k, v in res["base"].items()}))
    if not len(elig):
        print("no eligible rule: FAILS")
        res["verdict"] = "FAIL (no eligible rule)"
    else:
        best = elig.iloc[0]
        sc = next(s for s in SCORES if "%s>=%g" % s == best["score"])
        rule = (int(best["N"]), sc, int(best["K"]), best["exit"])
        print("\nchosen: N %d, %s, K %d, exit %s" % (rule[0], best["score"], rule[2], rule[3]))
        w = smart(p, T0, rule[0], sc, rule[3])
        sig = signals(p, T0, 1 << 62, w, rule[2], rule[3])
        st = stats(sig, rule[3], boot=True)
        b = base(p, T0, 1 << 62, rule[3])
        bst = stats(b, rule[3])
        c1 = st["coins"] >= T_MIN
        c2 = st.get("avg", -1) > 0 and st.get("ci", [-1])[0] > 0
        c3 = st.get("hit3", -1) >= bst.get("hit3", 101)
        verdict = "PASS" if c1 and c2 and c3 else "FAIL"
        print("T: %d smart wallets; %s" % (len(w), json.dumps(st)))
        print("base on T: %s" % json.dumps(bst))
        print("conditions: coins %s, average and interval above 0 %s, 3x share at least the base's %s -> %s" % (c1, c2, c3, verdict))
        res.update(chosen={"N": rule[0], "score": best["score"], "K": rule[2], "exit": rule[3]}, wallets_T=len(w),
                   T=st, base_T=bst, conditions=[bool(c1), bool(c2), bool(c3)], verdict=verdict)
        # information only
        info = {}
        for fee in (0.01, 0.03):
            info["fee_%g" % fee] = stats(sig, rule[3], fee_rt=fee)
        info["unclipped"] = stats(sig, rule[3], clip=False)
        for d in (1, 15, 60):
            info["delay_%d" % d] = stats(signals(p, T0, 1 << 62, w, rule[2], rule[3], d), rule[3], d)
        active = p[(p["grad_ms"] >= T0) & p["wid"].isin(w)]["wid"].nunique()
        info["wallets_trading_on_T"] = int(active)
        if h2dir:
            info["with_bot_gates"] = stats(gate_rows(h2dir, sig, D_SEARCH), rule[3])
            info["base_with_bot_gates"] = stats(gate_rows(h2dir, b, D_SEARCH), rule[3])
        top = []
        for r in elig.head(10).itertuples(index=False):
            s_ = next(s for s in SCORES if "%s>=%g" % s == r.score)
            w_ = smart(p, T0, int(r.N), s_, r.exit)
            top.append({"N": int(r.N), "score": r.score, "K": int(r.K), "exit": r.exit, "C_avg": r.avg,
                        **stats(signals(p, T0, 1 << 62, w_, int(r.K), r.exit), r.exit, boot=True)})
        info["top10_on_T"] = top
        res["info"] = info
        print("\ninformation only:")
        for k_, v in info.items():
            if k_ != "top10_on_T":
                print("  %s: %s" % (k_, json.dumps(v)))
        print("  the ten best C rules on T:")
        print(pd.DataFrame(top).to_string(index=False))
        # the chosen wallets, for a later live watch (addresses only when the test passes)
        if verdict == "PASS":
            wl = pd.read_parquet(glob.glob(os.path.join(wdir, "**", "wallets.parquet"), recursive=True)[0])
            res["wallet_list"] = wl[wl["wid"].isin(w)]["address"].tolist()
    if out_json:
        json.dump(res, open(out_json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
