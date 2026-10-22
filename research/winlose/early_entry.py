"""Test 1 of PREREG-EARLY-EXIT-2026-10-22.md (fake money only): the rocket hunter with its first check at 5, 10, 15 or 20 minutes
after the graduation against today's 30 minutes. Walk-forward over every week (as rocket_model.py), five seeds, the top 0.5% (and
1%, 2% for information), filter_search.simulate's 10,000 runs; then the pre-registered decision.
usage: python3 research/winlose/early_entry.py <scratch>   (needs grid_early.pkl)  -> <scratch>/early_entry.json, early_picks.pkl
FIX=1: the outcomes and the 10x label without the forward-filled wicks (wick_check.py, grid_early_fix.pkl) -> *_fix.json/.pkl"""
import importlib, json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__))
S = sys.argv[1]
sys.path.insert(0, os.path.join(HERE, "..", "..")); sys.path.insert(0, os.path.join(HERE, ".."))
import memebot as M
FS = importlib.import_module("filter_search")

CHART = ["ret_5", "ret_15", "ret_30", "ret_60", "ret_120", "ret_240", "ret_grad", "dd_ath", "min_since_ath", "from_low", "rsi_1m", "rsi_5m",
         "rsi_15m", "vol_spike_5", "vol_spike_15", "vol_trend_60", "buy_imb_5", "buy_imb_15", "buy_imb_60", "buys_trend_30", "trades_60",
         "avg_trade_sol_60", "active_min_60", "vola_60", "max_drop_1m_60", "max_jump_1m_60", "bb_pos", "trend_slope", "trend_r2", "body_5",
         "upwick_5", "lowick_5", "body_15", "upwick_15", "lowick_15", "engulf_bull", "engulf_bear", "support_touches", "dist_support",
         "resist_touches", "dist_resist", "first_hour_ret", "first_hour_sol", "first_hour_maxdd"]
WAL = ["r_buyers", "r_sol", "r_top_share", "r_avg_buy", "r_known_share", "r_smart_n", "r_smart_share", "r_smartbig_n", "r_avg_lroi"]
MKT = ["mc", "liqmc", "volmc", "btc_1h", "btc_24h", "sol_1h", "sol_24h"]
NUM = CHART + WAL + MKT
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
DAY = 86_400_000
LATE = 1790294400000            # 25 Sep 2026 00:00 UTC: weeks starting from here are the late weeks
SEEDS = (7, 11, 23, 42, 99)
CUTS = (0.005, 0.01, 0.02)
REG = list(range(30, 18 * 60 + 1, 15))
VARIANTS = {"V30": REG, "V20": [20] + REG, "V15": [15] + REG, "V10": [10, 25] + REG, "V5": [5, 20] + REG}


def summ(p):
    if not len(p):
        return {"coins": 0}
    v = p["eur"].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": int(len(p)), "avg": round(float(v.mean()), 2), "lo95": round(float(bs[50]), 2), "hi95": round(float(bs[1949]), 2),
            "inProfitOf10": round(10 * float((v > 0).mean()), 1), "x10": round(100 * float(p["rocket"].mean()), 1),
            "x3": round(100 * float(p["hit3"].mean()), 1), "zero": round(100 * float((p["mult"] < 0.02).mean()), 1),
            "total": round(float(v.sum()), 1), "ageMin": int(p["E"].median())}


def sim(p):
    s = FS.simulate({"scan": p["ts"].to_numpy(np.float64), "mult": p["mult"].to_numpy(np.float64)}, np.arange(len(p)))
    if s:
        s.pop("curve", None)
    return s


FIX = "_fix" if os.environ.get("FIX") else ""
G0 = pd.read_pickle(os.path.join(S, "grid_early%s.pkl" % FIX)).sort_values("ts").reset_index(drop=True)
if FIX:
    for k in ("mult", "eur", "rocket", "hit3", "hi6", "lo6"):
        G0[k] = G0[k + "_fix"]
base = G0[G0["E"].isin(REG)]
weeks = np.arange(base["grad_ms"].min() + 14 * DAY, base["grad_ms"].max() + 1, 7 * DAY)
print("rows", len(G0), "coins", G0["mint"].nunique(), "weeks", [pd.to_datetime(w, unit="ms").strftime("%m-%d") for w in weeks], flush=True)
res, picks = {}, []
for vn, Es in VARIANTS.items():
    G = G0[G0["E"].isin(Es)].reset_index(drop=True)
    res[vn] = {}
    for seed in SEEDS:
        out = {c: [] for c in CUTS}
        for st in weeks:
            tr = G[G["grad_ms"] < st - 2 * DAY]
            te = G[(G["grad_ms"] >= st) & (G["grad_ms"] < st + 7 * DAY)]
            if not len(te):
                continue
            m = lgb.LGBMClassifier(random_state=seed, **P).fit(tr[NUM], tr["rocket"])
            s_tr, s_te = m.predict_proba(tr[NUM])[:, 1], m.predict_proba(te[NUM])[:, 1]
            for c in CUTS:
                pk = te[s_te >= np.quantile(s_tr, 1 - c)].drop_duplicates("mint").copy()
                pk["week"] = int(st)
                out[c].append(pk)
        r = {}
        for c in CUTS:
            p = pd.concat(out[c])
            late = p["week"] >= LATE
            r["%g" % c] = {"all": summ(p), "early": summ(p[~late]), "late": summ(p[late]), "sim": sim(p),
                           "weeks": {pd.to_datetime(w, unit="ms").strftime("%m-%d"): [len(g), round(float(g["eur"].mean()), 2)] for w, g in p.groupby("week")}}
            picks.append(p.assign(variant=vn, seed=seed, cut=c)[["variant", "seed", "cut", "week", "mint", "pool", "ts", "grad_ms", "E", "eur", "mult", "hi6", "rocket", "hit3"]])
        res[vn][seed] = r
        a = r["0.005"]
        print("%s seed %3d  top0.5%%: %s | early %s/%s late %s/%s | sim %s" % (vn, seed, a["all"], a["early"].get("coins"), a["early"].get("avg"),
              a["late"].get("coins"), a["late"].get("avg"), (a["sim"] or {}).get("pProfit")), flush=True)

# the pre-registered decision (top 0.5%)
def mean_of(vn, key):
    xs = []
    for seed in SEEDS:
        a = res[vn][seed]["0.005"]
        v = (a["sim"] or {}).get("pProfit") if key == "sim" else a[key].get("avg")
        xs.append(np.nan if v is None else v)
    return np.array(xs, dtype=float)


table, holds = {}, []
ref = {k: mean_of("V30", k) for k in ("all", "early", "late", "sim")}
for vn in VARIANTS:
    x = {k: mean_of(vn, k) for k in ("all", "early", "late", "sim")}
    row = {"avg": round(float(np.nanmean(x["all"])), 2), "seeds": x["all"].tolist(), "early": round(float(np.nanmean(x["early"])), 2),
           "late": round(float(np.nanmean(x["late"])), 2), "sim": round(float(np.nanmean(x["sim"])), 1),
           "coins": round(float(np.mean([res[vn][s]["0.005"]["all"]["coins"] for s in SEEDS])), 1),
           "x10": round(float(np.mean([res[vn][s]["0.005"]["all"]["x10"] for s in SEEDS])), 1),
           "inProfitOf10": round(float(np.mean([res[vn][s]["0.005"]["all"]["inProfitOf10"] for s in SEEDS])), 1)}
    if vn != "V30":
        row["checks"] = {"a_mean_above_V30": bool(np.nanmean(x["all"]) > np.nanmean(ref["all"])),
                         "b_4of5_seeds": int((x["all"] > ref["all"]).sum()) >= 4,
                         "c_both_halves": bool(np.nanmean(x["early"]) > np.nanmean(ref["early"]) and np.nanmean(x["late"]) > np.nanmean(ref["late"])),
                         "d_sim_not_below": bool(np.nanmean(x["sim"]) >= np.nanmean(ref["sim"])),
                         "e_above_0": bool(np.nanmean(x["all"]) > 0)}
        row["seedsBetter"] = int((x["all"] > ref["all"]).sum())
        row["holds"] = all(row["checks"].values())
        if row["holds"]:
            holds.append((row["avg"], vn))
    table[vn] = row
choice = max(holds)[1] if holds else "V30"
print("\nDECISION (top 0.5%, seed means):")
for vn, row in table.items():
    print("  %-4s coins %5.1f  per20 %+6.2f  early %+6.2f  late %+6.2f  sims in profit %5.1f%%  10x %4.1f%%  %s" % (
        vn, row["coins"], row["avg"], row["early"], row["late"], row["sim"], row["x10"], row.get("checks", "")))
print("THE CHOICE:", choice)
json.dump({"res": {vn: {str(s): r for s, r in v.items()} for vn, v in res.items()}, "table": table, "choice": choice,
           "weeks": [int(w) for w in weeks]}, open(os.path.join(S, "early_entry%s.json" % FIX), "w"), default=float)
pd.concat(picks).to_pickle(os.path.join(S, "early_picks%s.pkl" % FIX))
