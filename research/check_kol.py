"""The pre-registered KOL test of research/PREREG-KOL-2026-10-22.md (fake money only): copy the known traders kolscan.io lists
(research/kol/kol_wallets.csv) on the wallet pairs of branch "wallets", inside the radar's coins, and as a vote on Pick's gate
coins (branch history2). Written before any KOL copy's outcome was looked at.
usage: python3 research/check_kol.py <wallets dir> <history2 dir> [out.json]   (needs numpy, pandas and pyarrow)
"""
import glob, json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import memebot as M
import rocket as R
import filter_search as FS
from check_history2 import bot_gates

S0 = 1786320000000         # 2026-08-10 00:00 UTC
SPLIT = 1789430400000      # 2026-09-15 00:00 UTC (the history2 split)
MIN = 60_000
H = 3_600_000
WEEK = 7 * 86_400_000
D = 15                     # the copy buys 15 minutes after the KOL's buy (the radar checks every 15 minutes)
MIN_COINS = 100
BOOT_N, SEED, LOW_PCT = 2000, 7, 1.0
SIM_PASS = 95.0
COLS = ["t_q", "sol_q", "wid", "coin", "grad_ms", "g1", "g6"] + ["%s%d" % (k, d) for d in (1, 5, 15, 60) for k in "phabx"]


def tip(m):
    """Per 20 after memebot's fees, not clipped."""
    return np.array([M.tip_net(float(x)) if x == x else np.nan for x in np.asarray(m, dtype="float64")])


def eur2(m):
    """The WALLETS convention, for information: 2% round trip, clipped to -20..60."""
    return np.clip(20.0 * (np.asarray(m, dtype="float64") * 0.99 * 0.99 - 1.0), -20.0, 60.0)


def boot_low(v):
    rng = np.random.default_rng(SEED)
    n = len(v)
    m = np.array([v[rng.integers(0, n, n)].mean() for _ in range(BOOT_N)])
    return [round(float(np.percentile(m, q)), 3) for q in (LOW_PCT, 2.5, 97.5)]


def judge(t, mult, hi, hold, name, full=True):
    """t: buy times (ms), mult: rule-A multiples, hi: 6-hour high multiples, hold: multiple at the end (zero check); one per coin."""
    t, mult, hi, hold = (np.asarray(x, dtype="float64") for x in (t, mult, hi, hold))
    n = len(mult)
    if not n:
        return {"name": name, "coins": 0, "pass": False}
    v = tip(mult)
    out = {"name": name, "coins": n, "avg": round(float(v.mean()), 3), "win10": round(10.0 * float((v > 0).mean()), 1),
           "hit3": round(100.0 * float((hi >= 3.0).mean()), 1), "hit11": round(100.0 * float((mult >= 11.0).mean()), 1),
           "zero": round(100.0 * float((hold < 0.02).mean()), 1), "avg_2pct_clip": round(float(eur2(mult).mean()), 3)}
    if not full:
        return out
    out["ci_low1_low2.5_high97.5"] = boot_low(v)
    sim = FS.simulate({"scan": t, "mult": mult}, np.arange(n), n_sims=10_000)
    out["sims"] = {k: sim[k] for k in ("sims", "days", "pProfit", "avg")} if sim else None
    halves = {}
    for nm, part in (("before 15 Sep", t < SPLIT), ("from 15 Sep", t >= SPLIT)):
        halves[nm] = {"coins": int(part.sum()), "avg": round(float(v[part].mean()), 3) if part.any() else None}
    out["halves"] = halves
    wk = ((t - S0) // WEEK).astype(int)
    out["weeks"] = {int(w) + 1: {"coins": int((wk == w).sum()), "avg": round(float(v[wk == w].mean()), 2)} for w in np.unique(wk)}
    c = [n >= MIN_COINS, out["avg"] > 0 and out["ci_low1_low2.5_high97.5"][0] > 0,
         bool(sim) and sim["pProfit"] >= SIM_PASS, all(h["avg"] is not None and h["avg"] > 0 for h in halves.values())]
    out["conditions"] = {"coins": c[0], "avg_and_1pct_low_above_0": c[1], "sims_95": c[2], "both_halves": c[3]}
    out["pass"] = all(c)
    return out


def load_pairs(wdir):
    files = sorted(glob.glob(os.path.join(wdir, "pairs", "pairs_*.parquet")))
    p = pd.concat([pd.read_parquet(f, columns=COLS) for f in files], ignore_index=True)
    return p[p["grad_ms"] >= S0].sort_values(["coin", "t_q"], kind="stable").reset_index(drop=True)


def valid(p, d=D, ex="a"):
    ok = p["p%d" % d].notna() & (p["p%d" % d] > 0) & p["%s%d" % (ex, d)].notna()
    return ok & ~(p["g1"] if ex == "h" else p["g6"])


def first_valid(s, k=1, d=D, ex="a"):
    """The k-th distinct KOL into each coin (by buy time), if its copy can be judged."""
    s = s.assign(rank=s.groupby("coin").cumcount() + 1)
    s = s[s["rank"] == k]
    return s[valid(s, d, ex)]


def copy_judge(s, name, d=D, ex="a", full=True):
    return judge(s["t_q"] + d * MIN, s["%s%d" % (ex, d)], s["x%d" % d], s["h%d" % d], name, full)


def hourly(h2):
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(h2, "hourly", "hourly_*.parquet")))], ignore_index=True)
    return d[d["h"] <= 24].sort_values(["mint", "ts"]).reset_index(drop=True)


def rule_a(d):
    st, tp = d["stop30_min"].to_numpy(), d["tp11_min"].to_numpy()
    return np.where(~np.isnan(st) & (np.isnan(tp) | (st <= tp)), d["stop30_x"], np.where(~np.isnan(tp), 11.0, d["last6"]))


def main():
    wdir, h2 = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    kol = pd.read_csv(os.path.join(HERE, "kol", "kol_wallets.csv"))
    w = pd.read_parquet(os.path.join(wdir, "wallets.parquet"))
    kw = w[w["address"].isin(set(kol["address"]))]
    kids = set(kw["wid"].tolist())
    coins = pd.read_parquet(os.path.join(wdir, "coins.parquet"))[["coin", "mint"]]
    p = load_pairs(wdir)
    p["kol"] = p["wid"].isin(kids)
    res = {"kol_listed": len(kol), "kol_in_data": len(kids), "pairs": len(p), "coins": int(p["coin"].nunique()),
           "kol_pairs": int(p["kol"].sum()), "kol_coins": int(p.loc[p["kol"], "coin"].nunique())}
    print(json.dumps(res), flush=True)

    # candidate 1: the first KOL into each coin, copied 15 minutes later, rule A
    K = p[p["kol"]]
    c1 = first_valid(K)
    res["cand1_kol_copy"] = copy_judge(c1, "1 KOL copy")

    # candidate 2: candidate 1 inside the radar's coins (age 30 min-18 h, the latest hourly row at most 60 min old in rocket.universe)
    d = hourly(h2)
    c2 = c1.merge(coins, on="coin", how="left")
    c2["tc"] = c2["t_q"] + D * MIN
    c2 = c2.sort_values("tc")
    hr = d[["mint", "ts", "market_cap_usd", "liquidity_usd", "volume_24h", "price_change_1h", "price_change_6h"]].sort_values("ts")
    c2 = pd.merge_asof(c2, hr, left_on="tc", right_on="ts", by="mint", direction="backward", tolerance=H)
    age = (c2["tc"] - c2["grad_ms"]) / MIN
    c2["univ"] = [R.universe(a, mc, lq, v, c1_ if c1_ == c1_ else None, c6 if c6 == c6 else None)
                  for a, mc, lq, v, c1_, c6 in zip(age, c2["market_cap_usd"].fillna(0), c2["liquidity_usd"].fillna(0),
                                                    c2["volume_24h"].fillna(0), c2["price_change_1h"], c2["price_change_6h"])]
    c2u = c2[c2["univ"] & c2["ts"].notna()]
    res["cand2_kol_copy_radar_coins"] = copy_judge(c2u, "2 KOL copy inside the radar's coins")

    # candidate 3: Pick's first gate row per coin, the coins where a KOL bought before the row
    d = d[(d["grad_ms"] >= S0)].copy()
    d["A"] = rule_a(d)
    ok6 = ~d["gap_pre"] & ~d["gap_6"] & d["last6"].notna()
    g = d[bot_gates(d) & ok6].drop_duplicates("mint", keep="first")
    kb = K.merge(coins, on="coin").groupby("mint")["t_q"].min()
    g = g.assign(kol_t=g["mint"].map(kb))
    yes = g[g["kol_t"].notna() & (g["kol_t"] < g["ts"])]
    no = g[~(g["kol_t"].notna() & (g["kol_t"] < g["ts"]))]
    res["cand3_pick_kol_vote"] = judge(yes["ts"], yes["A"], yes["hi6"], yes["px1"] / yes["price_usd"],
                                       "3 Pick gate coins with a KOL buy before")

    # information only
    info = {}
    vp = p[valid(p)]
    base = vp.groupby("coin", sort=False).sample(n=1, random_state=SEED)
    info["base_random_pair_every_coin"] = copy_judge(base, "base: a random pair of every coin", full=False)
    nk = vp[~vp["kol"] & vp["coin"].isin(set(c1["coin"]))]
    info["same_coins_random_nonkol_pair"] = copy_judge(nk.groupby("coin", sort=False).sample(n=1, random_state=SEED),
                                                       "the KOL coins, a random non-KOL pair", full=False)
    for dd in (1, 5, 60):
        info["kol_copy_delay_%d" % dd] = copy_judge(first_valid(K, d=dd), "KOL copy, %d min late" % dd, d=dd, full=False)
    info["second_kol_into_coin"] = copy_judge(first_valid(K, k=2), "the second KOL into a coin", full=False)
    for ex, nm in (("b", "exit B (-20%, 3x, 6 h)"), ("h", "hold 1.7 h")):
        s = first_valid(K, ex=ex)
        info["kol_copy_exit_" + ex] = judge(s["t_q"] + D * MIN, s["%s%d" % (ex, D)], s["x%d" % D], s["h%d" % D], "KOL copy, " + nm, full=False)
    info["pick_gate_coins_without_kol"] = judge(no["ts"], no["A"], no["hi6"], no["px1"] / no["price_usd"],
                                                "Pick gate coins without a KOL buy before", full=False)
    per = c1.assign(v=tip(c1["a%d" % D])).merge(kw[["wid", "address"]], on="wid").merge(kol, on="address")
    info["per_kol_first_copies"] = (per.groupby("name")["v"].agg(["size", "mean"]).round(2).sort_values("size", ascending=False)
                                    .head(20).reset_index().values.tolist())
    res["information_only"] = info
    res["verdict"] = "PASS" if any(res[k]["pass"] for k in ("cand1_kol_copy", "cand2_kol_copy_radar_coins", "cand3_pick_kol_vote")) else "FAIL"

    txt = json.dumps(res, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(txt)
    if out_path:
        with open(out_path, "w") as f:
            f.write(txt + "\n")


if __name__ == "__main__":
    main()
