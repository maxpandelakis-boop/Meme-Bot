"""Test 3 of PREREG-EARLY-EXIT-2026-10-22.md (fake money only): the exit model ("stay in or get out") against rule A on the rocket
hunter's picks, walk-forward by week; with --export, the model on all states as exit_model.json (plain-JSON trees, read by rocket.py).
Policy (KI exit): the -30% stop on the minute lows stays; every 15 minutes after the buy the model gives P(2x before 0.5x); below
1/3 it sells at that check's close; 24 h at most. Each week's model learns only from coins that graduated 3 days or more before it
(the label looks 24 h ahead from states up to 42 h old: the pre-registered "two days or more" is kept with a margin).
usage: python3 research/winlose/exit_model.py <scratch> [variant] [--export]   (needs exit_states.pkl, early_picks_live.pkl, cb55/)"""
import importlib, json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__))
S = sys.argv[1]
VAR = next((a for a in sys.argv[2:] if a.startswith("V")), "V30")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "..")); sys.path.insert(0, os.path.join(HERE, ".."))
import memebot as M
import rocket_exits as RX
FS = importlib.import_module("filter_search")

NUM = json.load(open(os.path.join(HERE, "..", "..", "rocket_model.json")))["features"] + ["age_min"]     # the live model's 60 + age
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)
DAY, LATE, CUTS = 86_400_000, 1790294400000, (0.005, 0.01, 0.02)
HOLD_P, STOP, MAXH, STEP = 1 / 3, 0.70, 24 * 60, 15
X = pd.read_pickle(os.path.join(S, "exit_states.pkl"))

if "--export" in sys.argv:
    m = lgb.LGBMClassifier(**P).fit(X[NUM], X["y"])
    dump = m.booster_.dump_model()
    assert dump["feature_names"] == [k.replace(" ", "_") for k in NUM]
    ex = X[NUM].sample(20, random_state=7)
    model = {"v": 1, "made": "2026-10-22", "features": NUM, "trees": [t["tree_structure"] for t in dump["tree_info"]], "hold": HOLD_P,
             "label": "2x before 0.5x within 24 h", "rows": int(len(X)), "coins": int(X["mint"].nunique()),
             "base": float(X["y"].mean()), "src": "history2 10 Aug-8 Oct 2026; research/winlose/exit_model.py",
             "check": {"x": [[None if v != v else float(v) for v in r] for r in ex.values.tolist()], "p": [float(x) for x in m.predict_proba(ex)[:, 1]]}}
    fn = os.path.join(HERE, "..", "..", "exit_model.json")
    json.dump(model, open(fn, "w"), separators=(",", ":"))
    print("exported", len(model["trees"]), "trees", round(os.path.getsize(fn) / 1e6, 2), "MB; label share", round(model["base"], 3))
    sys.exit()

PK = pd.read_pickle(os.path.join(S, "early_picks_live.pkl"))
PK = PK[(PK["variant"] == VAR) & (PK["seed"] == 7)].copy()
weeks = sorted(PK["week"].unique())
B = RX.bars(set(PK["pool"]))
A = RX.rules()
RA = next(r for r in A if r["fam"] == "F" and r["stop"] == 0.70 and r["target"] == 11.0 and r["hold_h"] == 6)
X["key"] = list(zip(X["pool"], X["E"]))
prob = {}
for st in weeks:
    tr = X[X["grad_ms"] < st - 3 * DAY]
    te_pools = set(PK.loc[PK["week"] == st, "pool"])
    te = X[X["pool"].isin(te_pools)]
    m = lgb.LGBMClassifier(**P).fit(tr[NUM], tr["y"])
    if len(te):
        prob.update(zip(te["key"], m.predict_proba(te[NUM])[:, 1]))
    print("week", pd.to_datetime(st, unit="ms").date(), "train states", len(tr), "coins", tr["mint"].nunique(), "test pools", len(te_pools), flush=True)


def ki(pool, E):
    """The KI exit from minute E: -> ([(fraction, multiple, why)], decisions [(minute after the buy, P)])."""
    c, hi, lo = B[pool]
    p0 = c[E - 1]
    dec = []
    for i in range(min(MAXH, len(c) - E)):
        if lo[E + i] / p0 <= STOP:
            return [(1.0, lo[E + i] / p0, "stop")], dec
        t = E + i + 1
        if (i + 1) % STEP == 0 and (pool, t) in prob:
            p = prob[(pool, t)]
            dec.append((i + 1, round(float(p), 3)))
            if p < HOLD_P:
                return [(1.0, c[t - 1] / p0, "ki")], dec
    n = min(MAXH, len(c) - E)
    return [(1.0, c[E + n - 1] / p0, "time")], dec


KI, DEC, RAs = [], [], []
for pool, E in zip(PK["pool"], PK["E"].astype(int)):
    sold, dec = ki(pool, E)
    c, hi, lo = B[pool]
    p0 = c[E - 1]
    KI.append(sold); DEC.append(dec)
    RAs.append(RX.walk(RA, (hi[E:E + MAXH] / p0).tolist(), (lo[E:E + MAXH] / p0).tolist(), (c[E:E + MAXH] / p0).tolist()))
PK["ki"], PK["dec"], PK["ra"] = KI, DEC, RAs
for k in ("ki", "ra"):
    PK["eur_" + k] = [RX.eur_of(s) for s in PK[k]]
    PK["mul_" + k] = [sum(f * m for f, m, _ in s) for s in PK[k]]
    PK["x10_" + k] = [any(m >= 10 for f, m, _ in s) for s in PK[k]]
PK["late"] = PK["week"] >= LATE
print("rule A replay = the grid's rule A on %d of %d picks" % (int((np.abs(PK["mul_ra"] - PK["mult"]) < 1e-4 * np.maximum(1, PK["mult"])).sum()), len(PK)))


def st(p, k):
    if not len(p):
        return {"coins": 0}
    v = p["eur_" + k].to_numpy()
    rng = np.random.default_rng(7)
    bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
    return {"coins": int(len(v)), "avg": round(float(v.mean()), 2), "lo95": round(float(bs[50]), 2), "hi95": round(float(bs[1949]), 2),
            "inProfitOf10": round(10 * float((v > 0).mean()), 1), "x10booked": round(100 * float(p["x10_" + k].mean()), 1),
            "total": round(float(v.sum()), 1)}


def sim(p, k):
    cap = FS.MULT_CAP
    FS.MULT_CAP = 1e9
    try:
        s = FS.simulate({"scan": p["ts"].to_numpy(np.float64), "mult": p["mul_" + k].to_numpy(np.float64)}, np.arange(len(p)))
    finally:
        FS.MULT_CAP = cap
    if s:
        s.pop("curve", None)
    return s


tab = {}
for c in CUTS:
    p = PK[PK["cut"] == c]
    tab["%g" % c] = {k: {"all": st(p, k), "early": st(p[~p["late"]], k), "late": st(p[p["late"]], k), "sim": sim(p, k)} for k in ("ki", "ra")}
    for k, lab in (("ki", "KI exit"), ("ra", "rule A")):
        t = tab["%g" % c][k]
        print("top %-5s %-8s all %s\n                early %s | late %s | sims in profit %s" % ("%g%%" % (100 * c), lab, t["all"], t["early"], t["late"], (t["sim"] or {}).get("pProfit")))
p2 = PK[(PK["cut"] == 0.02) & PK["late"]]
d = (p2["eur_ki"] - p2["eur_ra"]).to_numpy()
rng = np.random.default_rng(7)
bs = np.sort(d[rng.integers(0, len(d), (2000, len(d)))].mean(1))
p05l = PK[(PK["cut"] == 0.005) & PK["late"]]
chk = {"a_late_beats_A_0.5": bool(p05l["eur_ki"].mean() > p05l["eur_ra"].mean()), "a_late_beats_A_2": bool(d.mean() > 0),
       "b_late_paired_lo95_above_0": bool(bs[50] > 0),
       "c_sims_not_below": bool((tab["0.005"]["ki"]["sim"] or {}).get("pProfit", -1) >= (tab["0.005"]["ra"]["sim"] or {}).get("pProfit", 101))}
holds = all(chk.values())
print("paired late top 2%% (KI - rule A): coins %d avg %+.2f (%+.2f to %+.2f)" % (len(d), d.mean(), bs[50], bs[1949]))
print("checks:", chk, "-> HOLDS" if holds else "-> does not hold")
why = PK[PK["cut"] == 0.005].apply(lambda r: r["ki"][0][2], axis=1).value_counts().to_dict()
print("KI exits at the top 0.5%:", why)
big = PK[(PK["cut"] == 0.005) & (PK["hi6"] >= 10)][["mint", "E", "hi6", "mul_ra", "mul_ki"]]
print("the 10x coins at the top 0.5%% (rule A vs KI multiple):\n%s" % big.round(2).to_string())
json.dump({"variant": VAR, "table": tab, "pairedLate2": {"coins": int(len(d)), "avg": round(float(d.mean()), 2), "lo95": round(float(bs[50]), 2),
           "hi95": round(float(bs[1949]), 2)}, "checks": chk, "holds": holds, "kiWhy": why},
          open(os.path.join(S, "exit_model.json"), "w"), default=float)
PK.drop(columns=["dec"]).to_pickle(os.path.join(S, "exit_picks.pkl"))
