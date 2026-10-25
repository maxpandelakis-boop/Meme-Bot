"""The rocket hunter for live use (fake money only): the model on exactly the numbers rocket.py computes live (one-minute candles,
the latest trades, a seeded wallet memory, DexScreener's market cap/liquidity/volume, BTC/SOL), its stress test, and the export.
usage: python3 research/winlose/rocket_model.py <scratch> [--export]
<scratch>/grid_live.pkl: since 22 Oct the rows of 30 minutes and later of early_grid.py with LIVEHL=1 (a minute without a trade has
high = low = the last close, as rocket.dense; grid.py's forward-filled wicks had booked fake 10x on dead pools, wick_check.py); since
23 Oct with LIVEHL=1 LIVETR=300 (grid_early_live_tr300.pkl): the trade and wallet numbers from the last 300 trades only, as the live
account gets them (the model of 22 Oct had learned them from every trade of the hour and bought 60% fewer coins live,
LIVE-CHECK-2026-10-23.md).
Stress test (information: the holdout was seen for variant B before): walk-forward over every week from 24 Aug to 8 Oct (each
week trained only on coins that graduated two days or more before it), cuts at the top 0.25-5%, fees 0.5-2% per side, the buy
15 or 30 minutes late (the coin's next check), and filter_search.simulate's 10,000 runs."""
import importlib, json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__))
S = sys.argv[1]
sys.path.insert(0, os.path.join(HERE, "..", "..")); sys.path.insert(0, os.path.join(HERE, ".."))
import memebot as M
import rocket as R

G = pd.read_pickle(os.path.join(S, "grid_live.pkl")).sort_values("ts").reset_index(drop=True)
CHART = ["ret_5", "ret_15", "ret_30", "ret_60", "ret_120", "ret_240", "ret_grad", "dd_ath", "min_since_ath", "from_low", "rsi_1m", "rsi_5m",
         "rsi_15m", "vol_spike_5", "vol_spike_15", "vol_trend_60", "buy_imb_5", "buy_imb_15", "buy_imb_60", "buys_trend_30", "trades_60",
         "avg_trade_sol_60", "active_min_60", "vola_60", "max_drop_1m_60", "max_jump_1m_60", "bb_pos", "trend_slope", "trend_r2", "body_5",
         "upwick_5", "lowick_5", "body_15", "upwick_15", "lowick_15", "engulf_bull", "engulf_bear", "support_touches", "dist_support",
         "resist_touches", "dist_resist", "first_hour_ret", "first_hour_sol", "first_hour_maxdd"]
WAL = ["r_buyers", "r_sol", "r_top_share", "r_avg_buy", "r_known_share", "r_smart_n", "r_smart_share", "r_smartbig_n", "r_avg_lroi"]
MKT = ["mc", "liqmc", "volmc", "btc_1h", "btc_24h", "sol_1h", "sol_24h"]
NUM = CHART + WAL + MKT
# EXTRA=hour,atomic_60,... adds columns for a variant test (hour/dow from the time of the check); never with --export
G["hour"] = pd.to_datetime(G["ts"], unit="ms").dt.hour
G["dow"] = pd.to_datetime(G["ts"], unit="ms").dt.dayofweek
EXTRA = [c for c in (os.environ.get("EXTRA") or "").split(",") if c]
assert not (EXTRA and "--export" in sys.argv)
NUM = NUM + EXTRA
# DROP=btc_1h,... leaves columns out for a variant test (research/radarmkt/PREREG-RADARMKT-2026-10-25.md); never with --export
DROP = [c for c in (os.environ.get("DROP") or "").split(",") if c]
assert not (DROP and "--export" in sys.argv)
NUM = [c for c in NUM if c not in DROP]
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=int(os.environ.get("SEED") or 7))
DAY = 86_400_000
CUTS = (0.0025, 0.005, 0.01, 0.02, 0.05)


def fee_net(m, fee):
    t = R.TICKET
    return t * (1 - fee) ** 2 * max(0.0, m) - t


def summ(p, col="eur"):
    if not len(p):
        return {"coins": 0}
    v = p[col].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": int(len(p)), "avg": round(float(v.mean()), 2), "lo95": round(float(bs[50]), 2), "hi95": round(float(bs[1949]), 2),
            "inProfitOf10": round(10 * float((v > 0).mean()), 1), "x10": round(100 * float(p["rocket"].mean()), 1),
            "x3": round(100 * float(p["hit3"].mean()), 1), "zero": round(100 * float((p["mult"] < 0.02).mean()), 1), "total": round(float(v.sum()), 1)}


if "--export" not in sys.argv:
    # the next check of the same coin (15 and 30 minutes later): a late buy
    for k in (1, 2):
        nx = G.groupby("mint")["mult"].shift(-k)
        G["mult_late%d" % k] = nx
        G["eur_late%d" % k] = [M.tip_net(max(0.0, m)) if m == m else np.nan for m in nx]
    out = {c: [] for c in CUTS}
    weeks = np.arange(G["grad_ms"].min() + 14 * DAY, G["grad_ms"].max() + 1, 7 * DAY)
    for st in weeks:
        tr = G[G["grad_ms"] < st - 2 * DAY]
        te = G[(G["grad_ms"] >= st) & (G["grad_ms"] < st + 7 * DAY)]
        if not len(te):
            continue
        m = lgb.LGBMClassifier(**P).fit(tr[NUM], tr["rocket"])
        s_tr, s_te = m.predict_proba(tr[NUM])[:, 1], m.predict_proba(te[NUM])[:, 1]
        for c in CUTS:
            pk = te[s_te >= np.quantile(s_tr, 1 - c)].drop_duplicates("mint").copy()
            pk["week"] = pd.to_datetime(st, unit="ms").strftime("%m-%d")
            out[c].append(pk)
        print("week", pd.to_datetime(st, unit="ms").date(), "train", tr["mint"].nunique(), "test", te["mint"].nunique(), flush=True)
    res = {}
    FS = importlib.import_module("filter_search")
    for c in CUTS:
        p = pd.concat(out[c])
        r = {"all": summ(p), "weeks": {w: summ(g) for w, g in p.groupby("week")}}
        for fee in (0.005, 0.01, 0.02):
            p["e%g" % fee] = [fee_net(m, fee) for m in p["mult"]]
            r["fee%g" % fee] = summ(p, "e%g" % fee)
        for k in (1, 2):
            q = p[p["eur_late%d" % k].notna()]
            r["late%d" % (15 * k)] = summ(q.assign(eur=q["eur_late%d" % k], mult=q["mult_late%d" % k]))
        sim = FS.simulate({"scan": p["ts"].to_numpy(np.float64), "mult": p["mult"].to_numpy(np.float64)}, np.arange(len(p))) if hasattr(FS, "simulate") else None
        if sim:
            sim.pop("curve", None)
        r["sim"] = sim
        res["%g" % c] = r
        print("\ncut top %g%%: %s" % (100 * c, r["all"]))
        print("  weeks:", {w: (s["coins"], s["avg"]) for w, s in r["weeks"].items()})
        print("  fees 0.5/1/2%%: %s %s %s" % (r["fee0.005"].get("avg"), r["fee0.01"].get("avg"), r["fee0.02"].get("avg")), " late 15/30 min:", r["late15"].get("avg"), r["late30"].get("avg"))
        print("  sim:", sim)
    json.dump(res, open(os.path.join(S, "rocket_stress%s%s_s%s.json" % ("_" + "+".join(EXTRA) if EXTRA else "", "_no_" + "+".join(DROP) if DROP else "", os.environ.get("SEED") or 7)), "w"), default=float)
else:
    m = lgb.LGBMClassifier(**P).fit(G[NUM], G["rocket"])
    s = m.predict_proba(G[NUM])[:, 1]
    dump = m.booster_.dump_model()
    feats = dump["feature_names"]
    assert feats == [k.replace(" ", "_") for k in NUM], feats
    trees = [t["tree_structure"] for t in dump["tree_info"]]
    cut = float(np.quantile(s, 1 - 0.005))
    ex = G[NUM].head(20)
    model = {"v": 1, "made": "2026-10-23", "features": NUM, "trees": trees, "cut": cut, "cutTop": 0.005,
             "rows": int(len(G)), "coins": int(G["mint"].nunique()),
             "src": "history2 10 Aug-8 Oct 2026; research/winlose/rocket_model.py (grid without forward-filled wicks, 22 Oct; trades and wallets from the last 300 trades as live, 23 Oct)",
             "check": {"x": [[None if v != v else float(v) for v in r] for r in ex.values.tolist()], "p": [float(x) for x in m.predict_proba(ex)[:, 1]]}}
    json.dump(model, open(os.path.join(HERE, "..", "..", "rocket_model.json"), "w"), separators=(",", ":"))
    print("exported", len(trees), "trees, cut", cut, os.path.getsize(os.path.join(HERE, "..", "..", "rocket_model.json")) / 1e6, "MB")
