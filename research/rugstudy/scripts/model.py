#!/usr/bin/env python3
"""Rug and winner study, step 3: joint (ridge logistic) models with an out-of-time check, stratified signal tables
(organic launches only), and simple additive trap points for the radar.
Usage: venv/bin/python -I model.py <out dir>  -> model.txt, model.json"""
import json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import Boot, bh, pct, fx, auc, ridge_logit

OUT = sys.argv[1]
REP = []
say = REP.append


def load(name):
    with open(os.path.join(OUT, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


L, S = load("listings"), load("snapyoung")


def v(r, k):
    x = r["sig"].get(k)
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def flag(r, k, op=">", t=0.0, need_rc=False):
    if need_rc and not v(r, "rc.report"):
        return 0.0
    x = v(r, k)
    if x is None:
        return 0.0
    return 1.0 if {">": x > t, ">=": x >= t, "<": x < t, "<=": x <= t}[op] else 0.0


def clip(x, a, b):
    return max(a, min(b, x))


# feature name -> function(row) -> float (missing handled inside: 0 + an indicator feature where it matters)
FEATS = {
    "brand_name": lambda r: flag(r, "own.brand_name"),
    "no_socials": lambda r: 1.0 if (v(r, "socN") is not None and v(r, "socN") <= 0) else 0.0,
    "x_link": lambda r: flag(r, "x"),
    "launched_off_tweet": lambda r: flag(r, "vt.tweet"),
    "dex_paid": lambda r: flag(r, "ds.paid"),
    "log_liq": lambda r: math.log10(max(v(r, "liq") or 5000, 1000)),
    "log_mc": lambda r: math.log10(max(v(r, "mc") or 5000, 1000)),
    "liq_mc": lambda r: clip(v(r, "liqMc") or 0.3, 0, 2),
    "age_min": lambda r: clip(v(r, "ageMin") if v(r, "ageMin") is not None else 30, 0, 60),
    "chg_1h": lambda r: math.copysign(math.log1p(abs(clip(v(r, "c1") or 0, -100, 5000)) / 100), v(r, "c1") or 0),
    "chg_5m": lambda r: clip(v(r, "m5") or 0, -60, 100) / 20,
    "log_buys_1h": lambda r: math.log10(1 + (v(r, "buys1") or 0)),
    "buy_ratio_1h": lambda r: clip(v(r, "buyRatio1h") if v(r, "buyRatio1h") is not None else 1.2, 0, 5),
    "source_lists": lambda r: clip(v(r, "srcN") or 0, 0, 10),
    "keyword_hit": lambda r: flag(r, "kwN"),
    "ticker_reused": lambda r: flag(r, "own.ticker_reused"),
    "bot_score": lambda r: v(r, "score") or 47,
    "gate_crash": lambda r: flag(r, "gate.crash"),
    "gate_spike": lambda r: flag(r, "gate.spike"),
    "gate_copy": lambda r: flag(r, "gate.copy"),
    "rc_report": lambda r: flag(r, "rc.report"),
    "rc_top1_gt20": lambda r: flag(r, "rc.top1", ">", 20, True),
    "rc_top10_gt35": lambda r: flag(r, "rc.top10", ">", 35, True),
    "rc_log_holders": lambda r: math.log10(1 + (v(r, "rc.holders") or 0)) if v(r, "rc.report") else 0.0,
    "rc_holder_correlation": lambda r: flag(r, "rcn.holder_correlation", ">", 0, True),
    "rc_insider_network": lambda r: flag(r, "rcn.insider_net", ">", 0, True),
    "rc_low_liquidity": lambda r: flag(r, "rcn.low_liquidity", ">", 0, True),
    "rc_mc_per_holder": lambda r: flag(r, "rcn.mc_per_holder", ">", 0, True),
    "rc_creator_rugged": lambda r: flag(r, "rcn.creator_rugged", ">", 0, True),
    "rc_lp_unlocked": lambda r: flag(r, "rcn.lp_unlocked", ">", 0, True),
    "rc_danger_any": lambda r: flag(r, "rcn.danger_any", ">", 0, True),
    "creator_sold": lambda r: flag(r, "dev.sold"),
    "jup_organic_known": lambda r: 1.0 if v(r, "jup.organic") is not None else 0.0,
    "jup_organic_zero": lambda r: flag(r, "jup.organic", "<=", 0) if v(r, "jup.organic") is not None else 0.0,
    "wallets_known": lambda r: flag(r, "sw.n"),
    "wallets_past_avg": lambda r: clip(v(r, "sw.avg"), -20, 20) / 10 if v(r, "sw.avg") is not None else 0.0,
    "holders_in_earlier_rugs": lambda r: math.log1p(v(r, "own.holders_in_earlier_rug") or 0),
}
L_ONLY = {
    "instant_pool": lambda r: flag(r, "instantPool"),
    "mint_time_known": lambda r: 1.0 if v(r, "instantPool") is not None else 0.0,
}


def matrix(rows, names, fns):
    X = np.array([[fns[n](r) for n in names] for r in rows], dtype=float)
    return X


def standardize(Xtr, X):
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (X - mu) / sd, mu, sd


def fit_eval(rows, ykey, names, fns, label):
    rows = [r for r in rows if r["out"].get(ykey) is not None]
    runs = sorted({r["rid"] for r in rows})
    cut = runs[len(runs) // 2]
    tr = [r for r in rows if r["rid"] < cut]
    te = [r for r in rows if r["rid"] >= cut]
    ytr = np.array([1.0 if r["out"][ykey] else 0.0 for r in tr])
    yte = np.array([1.0 if r["out"][ykey] else 0.0 for r in te])
    Xtr_raw, Xte_raw = matrix(tr, names, fns), matrix(te, names, fns)
    Xtr, mu, sd = standardize(Xtr_raw, Xtr_raw)
    Xte = (Xte_raw - mu) / sd
    best = None
    for lam in (1, 3, 10, 30, 100, 300):
        w = ridge_logit(Xtr, ytr, lam)
        s = np.hstack([np.ones((len(te), 1)), Xte]) @ w
        a = auc(list(s), list(yte))
        if a is not None and (best is None or a > best[0]):
            best = (a, lam, w)
    a_te, lam, w_half = best
    # baselines on the same second half
    base = {}
    for nm, fn in (("bot score (higher = better)", lambda r: -(v(r, "score") or 47) if "rug" in ykey else (v(r, "score") or 47)),
                   ("trained zero odds", lambda r: (v(r, "zp") or 0) if "rug" in ykey else -(v(r, "zp") or 0)),
                   ("brand name only", lambda r: flag(r, "own.brand_name") * (1 if "rug" in ykey else -1)),
                   ("wallet past avg (sw.avg)", lambda r: (-(v(r, "sw.avg")) if v(r, "sw.avg") is not None else 0.0) * (1 if "rug" in ykey else -1)),
                   ("age (younger = riskier)", lambda r: -(v(r, "ageMin") or 30) * (1 if "rug" in ykey else -1))):
        base[nm] = auc([fn(r) for r in te], list(yte))
    if "instant_pool" in names:
        base["instant pool only"] = auc([flag(r, "instantPool") * (1 if "rug" in ykey else -1) for r in te], list(yte))
    # final fit on all rows with the chosen lambda
    yall = np.array([1.0 if r["out"][ykey] else 0.0 for r in rows])
    Xall_raw = matrix(rows, names, fns)
    Xall, mu2, sd2 = standardize(Xall_raw, Xall_raw)
    w = ridge_logit(Xall, yall, lam)
    # run-bootstrap of the coefficients (fewer resamples: Newton fits)
    bt_runs = sorted({r["rid"] for r in rows})
    byrun = {}
    for i, r in enumerate(rows):
        byrun.setdefault(r["rid"], []).append(i)
    rng = np.random.default_rng(7)
    coefs = []
    for _ in range(200):
        pick = rng.integers(0, len(bt_runs), len(bt_runs))
        idx = [i for p in pick for i in byrun[bt_runs[p]]]
        Xb, yb = Xall[idx], yall[idx]
        if yb.sum() < 5:
            continue
        coefs.append(ridge_logit(Xb, yb, lam, iters=30))
    C = np.array(coefs)
    lo, hi = np.percentile(C, 2.5, axis=0), np.percentile(C, 97.5, axis=0)
    out = {"label": label, "y": ykey, "n": len(rows), "events": int(yall.sum()), "nTrain": len(tr), "nTest": len(te), "cut": cut, "lambda": lam,
           "aucTest": a_te, "baselines": base, "coef": []}
    for j, nm in enumerate(names):
        out["coef"].append({"f": nm, "b": float(w[j + 1]), "lo": float(lo[j + 1]), "hi": float(hi[j + 1]), "sd": float(sd2[j]), "mean": float(mu2[j]),
                            "perUnit": float(w[j + 1] / sd2[j])})
    out["coef"].sort(key=lambda c: -abs(c["b"]))
    return out


def show(m):
    say("")
    say("### %s: %s (n=%d, events=%d; trained on scans before %s, tested on %d later coins; ridge lambda %g)" % (
        m["label"], m["y"], m["n"], m["events"], m["cut"], m["nTest"], m["lambda"]))
    say("out-of-time AUC: joint model %.3f | " % m["aucTest"] + " | ".join("%s %s" % (k, fx(a, 3)) for k, a in m["baselines"].items()))
    say("%-26s %8s %18s %10s  %s" % ("feature (standardized)", "coef", "95% CI (runs)", "odds x/SD", "reading"))
    for c in m["coef"]:
        sig = "clear" if (c["lo"] > 0 or c["hi"] < 0) else "unclear"
        say("%-26s %+8.3f %8s..%-8s %10.2f  %s %s" % (c["f"], c["b"], fx(c["lo"], 2), fx(c["hi"], 2), math.exp(c["b"]),
                                                      ("raises" if c["b"] > 0 else "lowers") + (" the rug odds" if "rug" in m["y"] else " the winner odds"), sig))


RES = {}
say("# Joint models (ridge logistic regression, features standardized; coefficients are log-odds per 1 SD)")
names_c = list(FEATS)
fns_l = dict(FEATS, **L_ONLY)
names_l = names_c + list(L_ONLY)
for rows, ykey, names, fns, label in ((L, "rug1h", names_l, fns_l, "L listed launches"), (S, "rug2h", names_c, FEATS, "S snapshot young coins"),
                                       (L, "win1h", names_l, fns_l, "L listed launches"), (S, "win2h", names_c, FEATS, "S snapshot young coins")):
    m = fit_eval(rows, ykey, names, fns, label)
    RES["%s.%s" % (label[0], ykey)] = m
    show(m)

# the early-list subset only (mint time known for most), with the instant-pool feature
E = [r for r in L if r["inEarly"]]
m = fit_eval(E, "rug1h", names_l, fns_l, "E early-list coins")
RES["E.rug1h"] = m
show(m)
m = fit_eval(E, "win1h", names_l, fns_l, "E early-list coins")
RES["E.win1h"] = m
show(m)

# ------------------------------------------------------------------ stratified: organic launches only (mint known, curve >= 2 min) vs instant pools
say("")
say("# Signals inside each launch type (early list, mint time known): does a signal still matter once the launch type is known?")
SIGS = [("brand name", lambda r: flag(r, "own.brand_name")), ("no socials", lambda r: 1.0 if (v(r, "socN") is not None and v(r, "socN") <= 0) else (0.0 if v(r, "socN") is not None else None)),
        ("x link", lambda r: flag(r, "x") if v(r, "x") is not None else None), ("dex paid", lambda r: flag(r, "ds.paid") if v(r, "ds.paid") is not None else None),
        ("liq >= 50k", lambda r: flag(r, "liq", ">=", 50000)), ("mc >= 500k", lambda r: flag(r, "mc", ">=", 500000)),
        ("age < 10 min", lambda r: flag(r, "ageMin", "<", 10)), ("up 100%+ in 1h", lambda r: flag(r, "c1", ">=", 100) if v(r, "c1") is not None else None),
        ("up 20%+ in 5m", lambda r: flag(r, "m5", ">=", 20) if v(r, "m5") is not None else None),
        ("score >= 50", lambda r: flag(r, "score", ">=", 50)),
        ("RC holder correlation", lambda r: flag(r, "rcn.holder_correlation") if v(r, "rc.report") else None),
        ("RC insider network", lambda r: flag(r, "rcn.insider_net") if v(r, "rc.report") else None),
        ("RC top1 > 20%", lambda r: flag(r, "rc.top1", ">", 20) if v(r, "rc.report") else None),
        ("RC top10 > 35%", lambda r: flag(r, "rc.top10", ">", 35) if v(r, "rc.report") else None),
        ("RC holders >= 1000", lambda r: flag(r, "rc.holders", ">=", 1000) if v(r, "rc.report") else None),
        ("RC creator rugged before", lambda r: flag(r, "rcn.creator_rugged") if v(r, "rc.report") else None),
        ("RC any danger", lambda r: flag(r, "rcn.danger_any") if v(r, "rc.report") else None),
        ("creator sold", lambda r: flag(r, "dev.sold") if v(r, "dev.sold") is not None else None),
        ("wallets lost on past coins (sw.avg < -7)", lambda r: flag(r, "sw.avg", "<", -7) if v(r, "sw.avg") is not None else None),
        ("3+ holders in earlier rugs", lambda r: flag(r, "own.holders_in_earlier_rug", ">=", 3) if v(r, "rc.report") else None),
        ("ticker reused", lambda r: flag(r, "own.ticker_reused")),
        ("Jupiter organic 0", lambda r: flag(r, "jup.organic", "<=", 0) if v(r, "jup.organic") is not None else None)]
strata = {"organic (curve >= 2 min)": [r for r in E if v(r, "graduated") == 1.0], "instant pool (< 60 s)": [r for r in E if v(r, "instantPool") == 1.0],
          "mint time unknown": [r for r in E if v(r, "instantPool") is None]}
RES["strata"] = {}
for ykey in ("rug1h", "win1h"):
    say("")
    say("## %s" % ykey)
    say("%-42s " % "signal" + " ".join("%-36s" % k for k in strata))
    for nm, fn in SIGS:
        line = "%-42s " % nm
        RES["strata"].setdefault(ykey, {})[nm] = {}
        for k, rows in strata.items():
            bt = Boot([r["rid"] for r in rows])
            n1, k1 = bt.per_run(rows, lambda r: fn(r) == 1.0, lambda r: r["out"].get(ykey))
            n0, k0 = bt.per_run(rows, lambda r: fn(r) == 0.0, lambda r: r["out"].get(ykey))
            c = bt.compare(n1, k1, n0, k0)
            RES["strata"][ykey][nm][k] = c
            if c and c["n1"] >= 10 and c["n0"] >= 10:
                mark = "*" if (c["dlo"] > 0 or c["dhi"] < 0) else " "
                line += "%-36s " % ("%s n=%d vs %s n=%d %s" % (pct(c["r1"], 0), c["n1"], pct(c["r0"], 0), c["n0"], mark))
            else:
                line += "%-36s " % ("(n=%d with)" % (c["n1"] if c else 0))
        say(line)
    for k, rows in strata.items():
        yy = [r["out"].get(ykey) for r in rows if r["out"].get(ykey) is not None]
        say("  base %s: %s of %d" % (k, pct(sum(yy) / len(yy)) if yy else "-", len(yy)))
say("(* = 95% run-bootstrap CI of the difference excludes 0)")

json.dump(RES, open(os.path.join(OUT, "model.json"), "w"), indent=1, default=str)
open(os.path.join(OUT, "model.txt"), "w").write("\n".join(REP) + "\n")
print("\n".join(REP))
