"""The pre-registered check of research/PREREG-HISTORY2-2026-10-21.md (fake money only): the bot's gates and a filter search on
the August to October 2026 rows of the branch "history2" (research/history_build2.py). Written before those rows were looked at.
usage: python3 research/check_history2.py <history2 dir, hourly_*.parquet in it or below>     (needs numpy, pandas and pyarrow)
"""
import glob, itertools, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memebot as M

SPLIT = 1789430400000      # 2026-09-15 00:00 UTC, by graduation
FIT_MIN, CHECK_MIN = 300, 150
EXITS = ("hold", "A", "B")


def eur(m):
    return M.clamp(M.tip_net(max(0.0, m)), M.EUR_CLIP[0], M.EUR_CLIP[1])


def exit_mult(r, stop, tp):
    s, t = r[stop + "_min"], r[tp + "_min"]
    s = None if s != s else s
    t = None if t != t else t
    if s is not None and (t is None or s <= t):
        return r[stop + "_x"]
    if t is not None:
        return {"tp3": 3.0, "tp11": 11.0}[tp]
    return r["last6"]


def outcomes(d):
    """Adds eur_hold, eur_A, eur_B (NaN where unknown), zero and hit3 to the rows."""
    import numpy as np
    hold = d["px1"] / d["price_usd"]
    ok1 = hold.notna() & ~d["gap_pre"] & ~d["gap_1"]
    d["eur_hold"] = np.where(ok1, [eur(m) if m == m else np.nan for m in hold], np.nan)
    ok6 = ~d["gap_pre"] & ~d["gap_6"] & d["last6"].notna()
    rs = d.to_dict("records")
    d["eur_A"] = np.where(ok6, [eur(exit_mult(r, "stop30", "tp11")) for r in rs], np.nan)
    d["eur_B"] = np.where(ok6, [eur(exit_mult(r, "stop20", "tp3")) for r in rs], np.nan)
    d["zero"] = hold < 0.02
    d["hit3"] = d["tp3_min"].notna()
    return d


def features(d):
    tx = d["buys_1h"] + d["sells_1h"]
    return {"age_h": d["age_h"], "mc": d["market_cap_usd"], "liqmc": d["liquidity_usd"] / d["market_cap_usd"],
            "volmc": d["volume_24h"] / d["market_cap_usd"], "vol1share": d["volume_1h"] / d["volume_24h"],
            "c5m": d["price_change_5m"], "c1": d["price_change_1h"], "c6": d["price_change_6h"], "c24": d["price_change_24h"],
            "buyshare": d["buys_1h"] / tx, "buyers": d["buyers_1h"], "topbuyer": d["top_buyer_share_1h"],
            "atomic": d["atomic_1h"] / tx, "idle": d["last_trade_s"]}


def first_per_coin(d, mask, col):
    s = d[mask & d[col].notna()]
    return s.drop_duplicates("mint", keep="first")      # rows are in time order within a coin


def stats(s, col):
    n = len(s)
    if not n:
        return {"coins": 0}
    return {"coins": n, "avg": round(float(s[col].mean()), 3), "zero": round(100.0 * float(s["zero"].mean()), 1),
            "hit3": round(100.0 * float(s["hit3"].mean()), 1), "win": round(100.0 * float((s[col] > 0).mean()), 1)}


def boot(v, n=2000, seed=7):
    rng = random.Random(seed)
    v = list(v)
    m = sorted(sum(v[rng.randrange(len(v))] for _ in v) / len(v) for _ in range(n))
    return round(m[int(0.025 * n)], 3), round(m[int(0.975 * n) - 1], 3)


def bot_gates(d):
    mc, liq, vol = d["market_cap_usd"], d["liquidity_usd"], d["volume_24h"]
    c1, c6, c24 = d["price_change_1h"], d["price_change_6h"], d["price_change_24h"]
    r = liq / mc
    return ((d["age_h"] >= 6) & (d["age_h"] <= 24) & (mc >= 100_000) & (mc <= 2_000_000) & (liq >= 15_000) & (vol >= 15_000)
            & ~(c1 <= -10) & ~(c6 <= -50) & ~(c24 <= -70) & ~(c1 >= 200) & ~(c6 >= 90) & ~(vol / mc > M.GATE_MAX_VOLMC)
            & ~((r >= 0.9) & (r <= 1.1)))


def main():
    import numpy as np, pandas as pd
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(sys.argv[1], "**", "hourly_*.parquet"), recursive=True))], ignore_index=True)
    d = d.sort_values(["mint", "ts"]).reset_index(drop=True)
    d = outcomes(d)
    print("rows %d, coins %d; with a hold result %d, with a 6 h result %d" % (len(d), d["mint"].nunique(), d["eur_hold"].notna().sum(), d["eur_A"].notna().sum()))

    print("\n== part 1: the bot's gates (information only)")
    g = bot_gates(d)
    for col in ("eur_hold", "eur_A", "eur_B"):
        s = first_per_coin(d, g, col)
        print("  %-8s %s" % (col[4:], stats(s, col)))
        for name, part in (("before 15 Sep", s["grad_ms"] < SPLIT), ("from 15 Sep", s["grad_ms"] >= SPLIT)):
            print("    %-14s %s" % (name, stats(s[part], col)))

    print("\n== part 2: the filter search")
    base = (d["liquidity_usd"] >= 15_000) & (d["volume_24h"] >= 15_000)
    fit, chk = base & (d["grad_ms"] < SPLIT), base & (d["grad_ms"] >= SPLIT)
    F = features(d)
    conds = []
    for k, v in F.items():
        lo, hi = v[fit].quantile(0.33), v[fit].quantile(0.67)
        conds.append(("%s<=%.4g" % (k, lo), k, v <= lo))
        conds.append(("%s>=%.4g" % (k, hi), k, v >= hi))
    rules = [(c[0], c[2]) for c in conds]
    rules += [(a[0] + " & " + b[0], a[2] & b[2]) for a, b in itertools.combinations(conds, 2) if a[1] != b[1]]
    print("  %d rules x %d outcomes" % (len(rules), len(EXITS)))
    res = []
    for name, m in rules:
        for ex in EXITS:
            col = "eur_" + ex
            s = first_per_coin(d, fit & m, col)
            if len(s) >= FIT_MIN:
                res.append((float(s[col].mean()), name, ex, m))
    res.sort(key=lambda x: -x[0])
    for ex in EXITS:
        col = "eur_" + ex
        print("  base, %-4s fit %s | check %s" % (ex, stats(first_per_coin(d, fit, col), col), stats(first_per_coin(d, chk, col), col)))
    if not res:
        print("no rule lets through %d fit coins" % FIT_MIN)
        return
    print("  the ten best on the fit part, and how they did on the check part (information only):")
    for avg, name, ex, m in res[:10]:
        col = "eur_" + ex
        print("    %-60s %-4s fit %s | check %s" % (name, ex, stats(first_per_coin(d, fit & m, col), col), stats(first_per_coin(d, chk & m, col), col)))
    avg, name, ex, m = res[0]
    col = "eur_" + ex
    s = first_per_coin(d, chk & m, col)
    b3 = float(first_per_coin(d, chk, col)["hit3"].mean())
    lo, hi = boot(s[col]) if len(s) else (None, None)
    ok = len(s) >= CHECK_MIN and s[col].mean() > 0 and lo is not None and lo > 0 and s["hit3"].mean() >= b3
    print("\nchosen on the fit part: %s with %s (fit %.3f per 20)" % (name, ex, avg))
    print("check part: %s, 95%% interval %s to %s; base 3x share %.1f%%" % (stats(s, col), lo, hi, 100 * b3))
    print("DECISION: %s" % ("PASSES, a candidate for the forward check" if ok else "FAILS"))


if __name__ == "__main__":
    main()
