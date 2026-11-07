"""Buy only rocket-like coins and hold them through the dip (fake money only): research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md.

  python3 research/rocketsep/check_rs.py ceiling <out dir>        Part 1: what a perfect separator / filter would be worth -> ceiling.json
  python3 research/rocketsep/check_rs.py similar <out dir>        Part 0b: rocket-after-sale vs zero-after-sale, fact by fact -> similar.json
  python3 research/rocketsep/check_rs.py buy <out dir>            Part 2: the buy side, choose + test, both families -> buy.json
  python3 research/rocketsep/check_rs.py hold <out dir>           Part 3a: the separator at the live sales -> hold.json
  python3 research/rocketsep/check_rs.py council <out dir> A|B    Part 3b: the 100 / 130 checkers -> council_<fam>.json
  python3 research/rocketsep/check_rs.py best <out dir>           Part 5: the best rule in hindsight with its coins -> best.json

<out dir> is research/rocketsep/rs_build.py's, with rs_facts.py's facts.npz. Nothing is bought; no network."""
import glob, json, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "council"))
import check_council as CC                                    # noqa: E402  PR #53: buys, frames, plans, council
import rs_facts as RF                                         # noqa: E402

DC, M, X = CC.DC, CC.M, CC.X
SEED = 7
COST = 0.75                                  # research/PREREG-REVIEW-2026-11-04.md: 1.5 points per 50-EUR round trip
FE_F = list(M.COIN_F + M.POS_F + M.LAUNCH_F)
FA = FE_F + RF.G_F
FB = FA + RF.L_F + RF.H_F + RF.W_F
BPLANS = ["V3", "K", "LP", "R6", "R24", "TR", "TR2", "HN"]
QB = (0.01, 0.02, 0.05, 0.10, 0.20)
QH = (0.01, 0.02, 0.05, 0.10)
B_SPLIT = int(pd.Timestamp("2026-08-30", tz="UTC").timestamp() * 1000)
T0 = time.time()


def log(*a, **kw):
    print("[%5.0fs]" % (time.time() - T0), *a, flush=True)


# --------------------------------------------------------------------------------------------------------- load
def load(out):
    Mt, P, D, F = CC.load(out)
    shards = sorted(glob.glob(os.path.join(out, "shards", "*.npz")))
    z = [np.load(f)["FE"] for f in shards]
    FE = np.stack([z[s][r] for s, r in zip(Mt["shard"], Mt["row"])]).astype(np.float32)
    fz = np.load(os.path.join(out, "facts.npz"))
    ix = pd.Series(np.arange(len(fz["eid"])), index=fz["eid"])
    j = ix.reindex(Mt["eid"].to_numpy()).to_numpy()
    assert not np.isnan(j).any()
    j = j.astype(int)
    Fx = {k: fz[k][j] for k in ("G", "L", "HE", "WE", "HA", "WA", "HB", "WB")}
    return Mt, P, D, F, FE, Fx


def last_candle(Mt):
    nEnd, cut = Mt["nEnd"].to_numpy(), Mt["cut"].to_numpy()
    return np.where(cut >= 0, np.minimum(nEnd - 1, cut - 1), nEnd - 1).astype(np.int64)


def _trail_kernel():
    import numba

    @numba.njit(parallel=True, cache=False)
    def run(C, Hh, L, O, last, floor, arm, tr, level_fill, out):
        """From the buy: out at max(floor, (1 - tr) x the highest high once that high reached arm), else the last close."""
        for i in numba.prange(C.shape[0]):
            hi = 1.0
            armed = arm <= 1.0
            res = C[i, last[i]]
            for k in range(last[i] + 1):
                lv = floor
                if armed and tr > 0:
                    lv = max(lv, (1.0 - tr) * hi)
                if lv > 0 and L[i, k] <= lv:
                    res = min(O[i, k], lv) if level_fill else L[i, k]
                    break
                if Hh[i, k] > hi:
                    hi = Hh[i, k]
                if not armed and hi >= arm:
                    armed = True
            out[i] = res
    return run


def buy_plans(Mt, P):
    """-> (n, 8) multiples of the buy price per buy plan, main (candle low) and level fill"""
    n = len(Mt)
    rows = np.arange(n)
    nb = np.stack(Mt["nb"].to_numpy())
    nT6 = nb[:, X.HOURS.index(6)].astype(np.int64)
    last = last_candle(Mt)
    nT24 = np.minimum(288, last + 1)
    z = np.zeros(n, np.int64)
    kern = _trail_kernel()
    res = []
    for fill in (False, True):
        out = np.zeros((n, len(BPLANS)))
        out[:, 0] = Mt["A_lv" if fill else "A_m"].to_numpy()
        out[:, 2] = Mt["B_lv" if fill else "B_m"].to_numpy()
        out[:, 1] = DC.run_rule(P, rows, z, nT6, 0.70, 11.0, fill)
        out[:, 3] = DC.run_rule(P, rows, z, nT6, 0.50, 11.0, fill)
        out[:, 4] = DC.run_rule(P, rows, z, nT24, 0.50, 10.0, fill)
        for j, (fl, arm, tr) in ((5, (0.0, 1.0, 0.30)), (6, (0.50, 2.0, 0.40)), (7, (0.0, 1e9, 0.0))):
            o = np.zeros(n)
            kern(P["C"], P["H"], P["L"], P["O"], last, fl, arm, tr, fill, o)
            out[:, j] = o
        res.append(out)
    return res


def buy_labels(Mt, P):
    cut = Mt["cut"].to_numpy()
    ok = ~((cut >= 0) & (cut < 288))
    mx = P["H"][:, :288].max(1)
    mn = P["L"][:, :288].min(1)
    return ok, mx >= 10.0, (mn <= 0.1) & (mx < 2.0), mx


def sale_labels(Mt, P, k):
    last = last_candle(Mt)
    idx = k[:, None] + 1 + np.arange(288)[None, :]
    valid = idx <= last[:, None]
    idx = np.clip(idx, 0, P["H"].shape[1] - 1)
    hh = np.where(valid, np.take_along_axis(P["H"], idx, 1), -np.inf)
    ll = np.where(valid, np.take_along_axis(P["L"], idx, 1), np.inf)
    mx, mn = hh.max(1), ll.min(1)
    mx = np.where(np.isfinite(mx), mx, 0.0)
    cut = Mt["cut"].to_numpy()
    ok = ~((cut >= 0) & (cut <= k + 288)) & valid.any(1)
    return ok, mx >= 10.0, (mn <= 0.1) & (mx < 1.0), mx


def roles_of(Mt, role):
    return Mt["roles"].str.contains(role).to_numpy()


def win_rows(Mt, fam, part):
    """fam A: fit/choose/test windows; fam B: the w3 split. -> (fit, judge list of (name, mask))"""
    w = Mt["w"].to_numpy()
    gm = Mt["gm"].to_numpy()
    if fam == "A":
        if part == "choose":
            return np.isin(w, ["w1", "w2"]), [("w3", w == "w3")]
        return np.isin(w, ["w1", "w2", "w3"]), [("w4", w == "w4"), ("w5", w == "w5")]
    if part == "choose":
        return (w == "w3") & (gm < B_SPLIT), [("w3late", (w == "w3") & (gm >= B_SPLIT))]
    return w == "w3", [("w4", w == "w4")]


# --------------------------------------------------------------------------------------------------------- models
LGBC = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=100, feature_fraction=0.7, bagging_fraction=0.8,
            bagging_freq=1, lambda_l2=10.0, metric="auc", seed=SEED, num_threads=3, verbose=-1)


def fit_clf(Xtr, y, gt):
    import lightgbm as lgb
    cut = np.quantile(gt, 0.85)
    va = gt >= cut
    if y[va].sum() == 0 or y[~va].sum() == 0 or (~y[va]).sum() == 0:
        b = lgb.train(LGBC, lgb.Dataset(Xtr, y.astype(float)), num_boost_round=200)
        return b, 200
    dtr = lgb.Dataset(Xtr[~va], y[~va].astype(float))
    dva = lgb.Dataset(Xtr[va], y[va].astype(float), reference=dtr)
    b = lgb.train(LGBC, dtr, num_boost_round=1000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    return b, max(1, int(b.best_iteration))


def oof_full(Xf, lab, fit, gm, apply_rows):
    """lab: (use, y) over all rows; fit rows; 3 blocked folds by graduation time -> (oof scores on fit rows, full-model scores on
    apply_rows, trees)"""
    use, y = lab
    idx = np.nonzero(fit)[0]
    order = idx[np.argsort(gm[idx], kind="stable")]
    oof = np.full(len(gm), np.nan)
    for part in np.array_split(order, 3):
        fo = np.zeros(len(gm), bool)
        fo[part] = True
        tr = fit & ~fo & use
        b, it = fit_clf(Xf[tr], y[tr], gm[tr])
        oof[fo] = b.predict(Xf[fo], num_iteration=it)
    tr = fit & use
    b, it = fit_clf(Xf[tr], y[tr], gm[tr])
    sc = np.full(len(gm), np.nan)
    sc[apply_rows] = b.predict(Xf[apply_rows], num_iteration=it)
    imp = dict(zip(range(Xf.shape[1]), b.feature_importance("gain")))
    return oof, sc, it, imp


def auc(y, s):
    from sklearn.metrics import roc_auc_score
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    if y.sum() == 0 or (~y).sum() == 0:
        return None
    return round(float(roc_auc_score(y, s)), 3)


# --------------------------------------------------------------------------------------------------------- the bar
def boot_lo1(m, draws=10000):
    m = np.asarray(m, float)
    if len(m) < 2:
        return None
    rng = np.random.default_rng(SEED)
    bs = np.empty(draws)
    for s in range(0, draws, 1000):
        bs[s:s + 1000] = m[rng.integers(0, len(m), (1000, len(m)))].mean(1)
    return float(np.quantile(bs, 0.01)), float((bs <= 0).mean())


def profit(mC, cost=COST):
    """PR #39's four points on trades (money per 50-EUR trade)"""
    m = np.asarray(mC, float) - cost
    if len(m) == 0:
        return {"n": 0, "holds": False}
    lo = boot_lo1(m)
    wob = float(m.sum() - m.max()) if len(m) > 1 else float("nan")
    ok = len(m) >= 40 and m.mean() > 0 and lo is not None and lo[0] > 0 and wob > 0
    return {"n": int(len(m)), "meanAfterCost": round(float(m.mean()), 2), "total": round(float(m.sum()), 2),
            "lo1": None if lo is None else round(lo[0], 2), "p": None if lo is None else round(lo[1], 5),
            "totalWithoutBest": round(wob, 2), "holds": bool(ok)}


def paired(d, n_hold):
    d = np.asarray(d, float)
    lo = boot_lo1(d)
    wob = float(d.sum() - d.max()) if len(d) > 1 else float("nan")
    ok = len(d) >= 40 and n_hold >= 10 and d.mean() > 0 and lo is not None and lo[0] > 0 and wob > 0
    return {"n": int(len(d)), "holds_n": int(n_hold), "diff": round(float(d.mean()), 3), "total": round(float(d.sum()), 2),
            "lo1": None if lo is None else round(lo[0], 3), "p": None if lo is None else round(lo[1], 5),
            "totalWithoutBest": round(wob, 2), "passes": bool(ok)}


def money(m):
    return DC.money(np.asarray(m, float))


# --------------------------------------------------------------------------------------------------------- Part 1
def cmd_ceiling(out):
    Mt, P, D, F, FE, Fx = load(out)
    BM, BMl = buy_plans(Mt, P)
    np.save(os.path.join(out, "buyplans.npy"), BM)
    np.save(os.path.join(out, "buyplans_lv.npy"), BMl)
    W = Mt["w"].to_numpy()
    res = {"buys": int(len(Mt)), "perWindow": {w: int((W == w).sum()) for w in X.WN}, "sale": {}, "buy": {}}
    okb, Rb, Zb, mxb = buy_labels(Mt, P)
    for fr, role, rule in (("A", "P", "Sell bot (v3)"), ("B", "L", "Learning Pick -20%/2x/2h")):
        Fm = CC.Frame(Mt, P, D, F, fr)
        ok, Rs, Zs, mxs = sale_labels(Mt, P, Fm.k)
        mS = money(Fm.sale)
        mP = money(Fm.plan)
        # hindsight exit: the highest high within 24 h after the sale (minus nothing more than the fees)
        mMax = money(np.maximum(mxs, Fm.sale))
        out_fr = {"rule": rule, "role": role}
        for wn in X.WN + ["w1-w3", "w4-w5", "all"]:
            ws = {"w1-w3": ["w1", "w2", "w3"], "w4-w5": ["w4", "w5"], "all": X.WN}.get(wn, [wn])
            r = roles_of(Mt, role) & np.isin(W, ws)
            n = int(r.sum())
            if not n:
                continue
            rr = r & Rs
            row = {"buys": n, "ruleMean": round(float(mS[r].mean()), 2), "rocketsAfterSale": int(rr.sum()),
                   "rocketsPer1000": round(1000 * rr.sum() / n, 2), "zerosAfterSale": int((r & Zs).sum()),
                   "perfect": {}}
            for j, pn in enumerate(CC.PN):
                g = (mP[:, j] - mS)
                row["perfect"][pn] = {"eurPer1000": round(float(g[rr].sum() * 1000 / n), 1),
                                      "newMean": round(float((mS[r] + np.where(rr[r], g[r], 0)).mean()), 2),
                                      "oracleAnyHoldNewMean": round(float((mS[r] + np.maximum(g[r], 0)).mean()), 2)}
            g = mMax - mS
            row["perfect"]["MAX24"] = {"eurPer1000": round(float(g[rr].sum() * 1000 / n), 1),
                                       "newMean": round(float((mS[r] + np.where(rr[r], g[r], 0)).mean()), 2)}
            out_fr[wn] = row
        res["sale"][fr] = out_fr
        log("ceiling", fr, {k: (v["buys"], v["rocketsPer1000"], v["ruleMean"], v["perfect"]["TR"]["newMean"], v["perfect"]["MAX24"]["newMean"])
                            for k, v in out_fr.items() if isinstance(v, dict) and "buys" in v})
    mB = money(BM)
    for role in ("P", "L", "A"):
        res["buy"][role] = {}
        for wn, ws in (("w1-w3", ["w1", "w2", "w3"]), ("w4", ["w4"]), ("w5", ["w5"]), ("all", X.WN)):
            r = roles_of(Mt, role) & np.isin(W, ws) & okb
            n = int(r.sum())
            rr, nr = r & Rb, r & ~Rb
            row = {"buys": n, "rockets": int(rr.sum()), "rocketPct": round(100 * rr.sum() / max(n, 1), 2), "plans": {}}
            for j, pn in enumerate(BPLANS):
                mR = float(mB[rr, j].mean()) if rr.any() else float("nan")
                mN = float(mB[nr, j].mean())
                s = -(mN - COST) / ((mR - COST) - (mN - COST)) if rr.any() and mR > mN else None
                row["plans"][pn] = {"mean": round(float(mB[r, j].mean()), 2), "rocketMean": round(mR, 2), "nonRocketMean": round(mN, 2),
                                    "breakEvenRocketPct": None if s is None else round(100 * s, 2),
                                    "onlyRocketsMean": round(mR, 2)}
            res["buy"][role][wn] = row
        log("buy ceiling", role, {k: (v["buys"], v["rocketPct"], {p: v["plans"][p]["breakEvenRocketPct"] for p in ("V3", "TR", "HN")})
                                  for k, v in res["buy"][role].items()})
    json.dump(res, open(os.path.join(out, "ceiling.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- features
def buy_X(FE, Fx, fam):
    Xa = np.c_[FE, Fx["G"]]
    if fam == "A":
        return Xa.astype(np.float32), FA
    return np.c_[Xa, Fx["L"], Fx["HE"], Fx["WE"]].astype(np.float32), FB


def sale_X(Fm, Fx, fr, fam):
    Xa = np.c_[Fm.F, Fx["G"]]
    names = list(CC.FEATS) + RF.G_F
    if fam == "A":
        return Xa.astype(np.float32), names
    return np.c_[Xa, Fx["L"], Fx["H" + fr], Fx["W" + fr]].astype(np.float32), names + RF.L_F + RF.H_F + RF.W_F


def top_imp(imp, names, k=12):
    s = sorted(imp.items(), key=lambda x: -x[1])[:k]
    return [[names[i], round(float(v), 1)] for i, v in s if v > 0]


# --------------------------------------------------------------------------------------------------------- Part 2
def cmd_buy(out):
    Mt, P, D, F, FE, Fx = load(out)
    BM, BMl = np.load(os.path.join(out, "buyplans.npy")), np.load(os.path.join(out, "buyplans_lv.npy"))
    mB, mBl = money(BM), money(BMl)
    okb, Rb, Zb, mxb = buy_labels(Mt, P)
    gm = Mt["gm"].to_numpy().astype(np.float64)
    res = {}
    for fam in ("A", "B"):
        Xf, names = buy_X(FE, Fx, fam)
        res[fam] = {"features": len(names)}
        chosen = {}
        for part in ("choose", "test"):
            fit, judges = win_rows(Mt, fam, part)
            apply_rows = np.zeros(len(Mt), bool)
            for _, jm in judges:
                apply_rows |= jm
            scores, info = {}, {}
            for mname, use, y in (("bR", okb, Rb), ("bRZ", okb & (Rb | Zb), Rb)):
                oof, sc, it, imp = oof_full(Xf, (use, y), fit, gm, apply_rows)
                scores[mname] = (oof, sc)
                info[mname] = {"trees": it, "top": top_imp(imp, names),
                               "auc": {jn: auc(Rb[jm & okb], sc[jm & okb]) for jn, jm in judges},
                               "aucOOF": auc(Rb[fit & okb], oof[fit & okb])}
                log(fam, part, mname, info[mname]["auc"], "oof", info[mname]["aucOOF"], "trees", it)
            pres = {"models": info, "frames": {}}
            for role in ("P", "L", "A"):
                rmask = roles_of(Mt, role)
                fr_res = {"cands": []}
                for mname in ("bR", "bRZ"):
                    oof, sc = scores[mname]
                    for q in QB:
                        cutv = float(np.nanquantile(oof[fit & rmask], 1 - q))
                        for jn, jm in judges:
                            J = jm & rmask
                            buy = J & (sc >= cutv)
                            nb = int(buy.sum())
                            for j, pn in enumerate(BPLANS):
                                m = mB[buy, j]
                                fr_res["cands"].append({"model": mname, "q": q, "plan": pn, "win": jn, "n": nb,
                                                        "mean": round(float(m.mean()), 3) if nb else None,
                                                        "rockets": int((buy & Rb).sum()), "base_n": int(J.sum()),
                                                        "base_rocketPct": round(100 * (J & Rb & okb).sum() / max((J & okb).sum(), 1), 2)})
                if part == "choose":
                    el = [c for c in fr_res["cands"] if c["n"] >= 20]
                    order = {(m_, q_, p_): i for i, (m_, q_, p_) in enumerate((m_, q_, p_) for m_ in ("bR", "bRZ") for q_ in QB for p_ in BPLANS)}
                    el.sort(key=lambda c: (-c["mean"], c["n"], order[(c["model"], c["q"], c["plan"])]))
                    fr_res["chosen"] = el[0] if el else None
                    chosen[role] = el[0] if el else None
                    log(fam, "chosen", role, fr_res["chosen"])
                else:
                    ch = chosen.get(role)
                    if ch is None:
                        fr_res["verdict"] = "no candidate had 20 trades on the choose window"
                    else:
                        oof, sc = scores[ch["model"]]
                        cutv = float(np.nanquantile(oof[fit & rmask], 1 - ch["q"]))
                        j = BPLANS.index(ch["plan"])
                        fr_res["chosen"] = ch
                        fr_res["test"] = {}
                        for jn, jm in judges:
                            buy = jm & rmask & (sc >= cutv)
                            pc = profit(mB[buy, j])
                            pc["levelFillMeanAfterCost"] = round(float(mBl[buy, j].mean() - COST), 2) if buy.any() else None
                            pc["rockets"] = int((buy & Rb).sum())
                            pc["rocketPct"] = round(100 * (buy & Rb & okb).sum() / max((buy & okb).sum(), 1), 2)
                            pc["basePlanMean"] = round(float(mB[jm & rmask, j].mean()), 2)
                            pc["liveRuleMean"] = round(float(mB[jm & rmask, BPLANS.index("V3" if role != "L" else "LP")].mean()), 2)
                            fr_res["test"][jn] = pc
                            if jn == judges[0][0]:
                                fr_res["buys_" + jn] = coin_list(Mt, buy, BM[:, j], mxb)
                        t4 = fr_res["test"].get("w4", {})
                        t5 = fr_res["test"].get("w5")
                        w5ok = True if fam == "B" else (t5 is not None and t5["n"] >= 10 and t5["meanAfterCost"] >= 0)
                        fr_res["holds"] = bool(t4.get("holds") and w5ok)
                        log(fam, "TEST", role, ch["model"], ch["q"], ch["plan"], {k: (v["n"], v.get("meanAfterCost"), v.get("lo1"), v["holds"])
                                                                               for k, v in fr_res["test"].items()}, "HOLDS" if fr_res["holds"] else "fails")
                    # every candidate on the test windows (reported, not the bar)
                pres["frames"][role] = fr_res
            res[fam][part] = pres
        json.dump(res, open(os.path.join(out, "buy.json"), "w"), indent=1)


def coin_list(Mt, sel, mult, mx):
    idx = np.nonzero(sel)[0]
    rows = []
    for i in idx:
        r = Mt.iloc[i]
        rows.append({"mint": r["mint"], "buy": pd.Timestamp(int(r["te"]), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M"),
                     "hoursAfterGrad": int(r["E"]) // 60, "mcap": int(r["mc"]), "mult": round(float(mult[i]), 3),
                     "eur": round(float(money(mult[i])), 2), "high24": round(float(mx[i]), 2)})
    return rows


# --------------------------------------------------------------------------------------------------------- Part 3a
def cmd_hold(out):
    Mt, P, D, F, FE, Fx = load(out)
    gm = Mt["gm"].to_numpy().astype(np.float64)
    res = {}
    for fr, role in (("A", "P"), ("B", "L")):
        Fm = CC.Frame(Mt, P, D, F, fr)
        ok, Rs, Zs, mxs = sale_labels(Mt, P, Fm.k)
        gain = Fm.gain
        gain_lv = money(Fm.plan_lv) - money(Fm.sale_lv)[:, None]
        rmask = roles_of(Mt, role)
        res[fr] = {}
        for fam in ("A", "B"):
            Xf, names = sale_X(Fm, Fx, fr, fam)
            chosen = None
            fres = {}
            for part in ("choose", "test"):
                fit, judges = win_rows(Mt, fam, part)
                apply_rows = np.zeros(len(Mt), bool)
                for _, jm in judges:
                    apply_rows |= jm
                scores, info = {}, {}
                for mname, use, y in (("sR", ok, Rs), ("sRZ", ok & (Rs | Zs), Rs)):
                    oof, sc, it, imp = oof_full(Xf, (use, y), fit, gm, apply_rows)
                    scores[mname] = (oof, sc)
                    info[mname] = {"trees": it, "top": top_imp(imp, names), "aucOOF": auc(Rs[fit & ok], oof[fit & ok]),
                                   "auc": {jn: auc(Rs[jm & ok], sc[jm & ok]) for jn, jm in judges},
                                   "aucOnRole": {jn: auc(Rs[jm & ok & rmask], sc[jm & ok & rmask]) for jn, jm in judges}}
                    log(fr, fam, part, mname, info[mname]["auc"], info[mname]["aucOnRole"], "trees", it)
                cands = []
                for mname in ("sR", "sRZ"):
                    oof, sc = scores[mname]
                    for q in QH:
                        cutv = float(np.nanquantile(oof[fit & rmask], 1 - q))
                        for jn, jm in judges:
                            J = jm & rmask
                            h = J & (sc >= cutv)
                            for j, pn in enumerate(CC.PN):
                                d = np.where(h, gain[:, j], 0.0)[J]
                                cands.append({"model": mname, "q": q, "plan": pn, "win": jn, "buys": int(J.sum()), "holds": int(h.sum()),
                                              "diff": round(float(d.mean()), 3), "rocketsHeld": int((h & Rs).sum()),
                                              "rocketsAll": int((J & Rs).sum())})
                part_res = {"models": info}
                if part == "choose":
                    el = [c for c in cands if c["holds"] >= 5]
                    el.sort(key=lambda c: (-c["diff"], c["holds"]))
                    chosen = el[0] if el else None
                    part_res["chosen"] = chosen
                    part_res["top10"] = el[:10]
                    log(fr, fam, "chosen", chosen)
                else:
                    part_res["all"] = cands
                    if chosen is None:
                        part_res["verdict"] = "no candidate held 5 on the choose window"
                    else:
                        oof, sc = scores[chosen["model"]]
                        cutv = float(np.nanquantile(oof[fit & rmask], 1 - chosen["q"]))
                        j = CC.PN.index(chosen["plan"])
                        part_res["test"] = {}
                        for jn, jm in judges:
                            J = jm & rmask
                            h = J & (sc >= cutv)
                            d = np.where(h, gain[:, j], 0.0)[J]
                            dl = np.where(h, gain_lv[:, j], 0.0)[J]
                            pr = paired(d, int(h.sum()))
                            pr["levelFillDiff"] = round(float(dl.mean()), 3)
                            mC = money(np.where(h, Fm.plan[:, j], Fm.sale))[J]
                            pr["ruleMean"] = round(float(money(Fm.sale[J]).mean()), 2)
                            pr["newMean"] = round(float(mC.mean()), 2)
                            pr["profit"] = profit(mC)
                            pr["rocketsHeld"] = int((h & Rs).sum())
                            pr["rocketsAll"] = int((J & Rs).sum())
                            pr["heldWon"] = int((h & (gain[:, j] > 0)).sum())
                            part_res["test"][jn] = pr
                            part_res["held_" + jn] = coin_list(Mt, h, np.where(h, Fm.plan[:, j], Fm.sale), mxs)
                        t4 = part_res["test"].get("w4", {})
                        t5 = part_res["test"].get("w5")
                        w5ok = True if fam == "B" else (t5 is not None and t5["diff"] >= 0)
                        part_res["holds"] = bool(t4.get("passes") and t4.get("levelFillDiff", -1) >= 0 and w5ok)
                        log(fr, fam, "TEST", chosen["model"], chosen["q"], chosen["plan"],
                            {k: (v["holds_n"], v["diff"], v["lo1"], v["passes"]) for k, v in part_res["test"].items()},
                            "HOLDS" if part_res["holds"] else "fails")
                fres[part] = part_res
            res[fr][fam] = fres
            json.dump(res, open(os.path.join(out, "hold.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- Part 0b
def cmd_similar(out):
    Mt, P, D, F, FE, Fx = load(out)
    W = Mt["w"].to_numpy()
    res = {}
    for fr in ("A", "B"):
        Fm = CC.Frame(Mt, P, D, F, fr)
        ok, Rs, Zs, _ = sale_labels(Mt, P, Fm.k)
        Xf, names = sale_X(Fm, Fx, fr, "B")
        rows = []
        for c, nm in enumerate(names):
            if nm in ("why",):
                continue
            x = Xf[:, c].astype(np.float64)
            row = {"fact": nm}
            for wn, ws in (("w1-w3", ["w1", "w2", "w3"]), ("w4", ["w4"]), ("w3", ["w3"])):
                s = ok & np.isin(W, ws) & (Rs | Zs) & np.isfinite(x)
                if s.sum() < 50 or Rs[s].sum() < 10:
                    continue
                row[wn] = {"auc": auc(Rs[s], x[s]), "medRocket": round(float(np.median(x[s & Rs])), 4),
                           "medZero": round(float(np.median(x[s & Zs])), 4), "nRocket": int((s & Rs).sum()), "nZero": int((s & Zs).sum())}
            if "w4" in row and (("w1-w3" in row) or ("w3" in row)):
                rows.append(row)
        ref = lambda r: r.get("w1-w3", r.get("w3"))["auc"] or 0.5
        rows.sort(key=lambda r: -abs(ref(r) - 0.5))
        res[fr] = rows
        log("similar", fr, [(r["fact"], ref(r), r["w4"]["auc"]) for r in rows[:12]])
    json.dump(res, open(os.path.join(out, "similar.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- Part 5
CHART_Q = ["lr60", "lr360", "vol60", "v60_ratio", "turnover", "lmc", "lliq", "liqmc", "ath", "atl", "age"]


def plan_exit(Mt, P, i, plan):
    """One buy, one buy plan -> (multiple, path candle of the sale, reason) for the coin lists."""
    C, Hh, L, O = P["C"][i], P["H"][i], P["L"][i], P["O"][i]
    nb = Mt["nb"].iat[i]
    nT6, nT2 = int(nb[X.HOURS.index(6)]), int(nb[X.HOURS.index(2)])
    last = int(last_candle(Mt.iloc[[i]])[0])
    if plan == "V3":
        m, k, why = CC.v3_sale(C, Hh, L, O, nT6)
        return m, k, CC.WHY_A[why]
    if plan == "LP":
        m, k, why = CC.lp_sale(C, Hh, L, O, nT2)
        return m, k, CC.WHY_B[why]
    if plan in ("K", "R6", "R24"):
        lvl, tp, nT = {"K": (0.70, 11.0, nT6), "R6": (0.50, 11.0, nT6), "R24": (0.50, 10.0, min(288, last + 1))}[plan]
        for k in range(nT):
            if L[k] <= lvl:
                return L[k], k, "stop"
            if Hh[k] >= tp:
                return tp, k, "target"
        return C[nT - 1], nT - 1, "time"
    fl, arm, tr = {"TR": (0.0, 1.0, 0.30), "TR2": (0.50, 2.0, 0.40), "HN": (0.0, 1e9, 0.0)}[plan]
    hi, armed = 1.0, arm <= 1.0
    for k in range(last + 1):
        lv = fl
        if armed and tr > 0:
            lv = max(lv, (1.0 - tr) * hi)
        if lv > 0 and L[k] <= lv:
            return L[k], k, ("trail" if armed and tr > 0 and lv > fl else "floor")
        hi = max(hi, Hh[k])
        if not armed and hi >= arm:
            armed = True
    return C[last], last, "end of data"


def coins_of(Mt, P, sel, plan, names, mx):
    rows = []
    for i in np.nonzero(sel)[0]:
        m, k, why = plan_exit(Mt, P, i, plan)
        r = Mt.iloc[i]
        t_sale = int(r["t0"]) + (int(r["jl"]) + 2 + int(k) + 1) * X.BAR
        nm = names.get(r["pool"], ("", ""))
        rows.append({"coin": nm[0] or "?", "name": nm[1] or "", "mint": r["mint"],
                     "buy": pd.Timestamp(int(r["te"]), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M"),
                     "hAfterGrad": int(r["E"]) // 60, "mcapAtBuy": int(r["mc"]),
                     "sale": pd.Timestamp(t_sale, unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M"), "why": why,
                     "mult": round(float(m), 3), "eur": round(float(money(m)), 2), "high24": round(float(mx[i]), 2)})
    return rows


def cond_matrix(Xf, names, fit_rows, use_h=False):
    sys.path.insert(0, os.path.join(HERE, "..", "rockets"))
    import check_rockets as RK
    cols, labs = [], []
    for f in RF.G_F:
        c = names.index(f)
        x = Xf[:, c]
        bk = RK.BUCKETS.get(f)
        if bk is None:
            qs = np.nanquantile(x[fit_rows], [0.2, 0.4, 0.6, 0.8])
            b = np.digitize(x, qs)
            for k in range(5):
                cols.append(np.isfinite(x) & (b == k)); labs.append("%s quintile %d" % (f, k + 1))
        else:
            cuts, bl = bk
            b = np.digitize(x, cuts) - 1
            for k, lab in enumerate(bl):
                cols.append(np.isfinite(x) & (b == k)); labs.append("%s = %s" % (f, lab))
    extra = CHART_Q + ((RF.L_F + RF.H_F[:10] + RF.W_F) if use_h else [])
    for f in extra:
        c = names.index(f)
        x = Xf[:, c]
        qs = np.nanquantile(x[fit_rows & np.isfinite(x)], [0.2, 0.4, 0.6, 0.8])
        b = np.digitize(x, qs)
        for k in range(5):
            cols.append(np.isfinite(x) & (b == k)); labs.append("%s quintile %d" % (f, k + 1))
    return np.stack(cols, 1), labs


def cmd_best(out):
    Mt, P, D, F, FE, Fx = load(out)
    BM = np.load(os.path.join(out, "buyplans.npy"))
    mB = money(BM)
    okb, Rb, Zb, mxb = buy_labels(Mt, P)
    W = Mt["w"].to_numpy()
    gf = pd.read_parquet(os.path.join(out, "gfacts.parquet"))
    names = {p: (str(s) if isinstance(s, str) else "", str(n) if isinstance(n, str) else "") for p, s, n in
             zip(gf.index, gf["symbol"], gf["token_name"])}
    res = {}
    for fam, ins, checks in (("A", ["w1", "w2", "w3"], ["w4", "w5"]), ("B", ["w3"], ["w4"])):
        Xf, fnames = buy_X(FE, Fx, fam)
        fit_rows = np.isin(W, ins)
        Cm, labs = cond_matrix(Xf, fnames, fit_rows, fam == "B")
        K = Cm.shape[1]
        res[fam] = {"conditions": K, "frames": {}}
        for role in ("P", "L", "A"):
            rm = roles_of(Mt, role)
            sets = {w: rm & np.isin(W, [w] if w != "ins" else ins) for w in ["ins"] + checks}
            stats = {}
            for wn, s in sets.items():
                Cs = Cm[s].astype(np.float64)
                Ms = mB[s]
                cnt = np.zeros((K, K))
                sm = np.zeros((K, K, len(BPLANS)))
                for i in range(K):
                    mi = Cs * Cs[:, i:i + 1]
                    cnt[i] = mi.sum(0)
                    sm[i] = mi.T @ Ms
                stats[wn] = (cnt, sm)
            cnt, sm = stats["ins"]
            mean = np.where(cnt[:, :, None] >= 40, sm / np.maximum(cnt[:, :, None], 1), -np.inf)
            iu = np.triu_indices(K)
            flat = mean[iu[0], iu[1], :]
            order = np.argsort(-flat, axis=None)[:200]
            top = []
            seen = set()
            for o in order:
                a, p = np.unravel_index(o, flat.shape)
                i, j = int(iu[0][a]), int(iu[1][a])
                key = (min(i, j), max(i, j), p)
                if key in seen or not np.isfinite(flat[a, p]):
                    continue
                seen.add(key)
                row = {"rule": labs[i] + ("" if i == j else " AND " + labs[j]), "plan": BPLANS[p],
                       "ins": {"n": int(cnt[i, j]), "mean": round(float(mean[i, j, p]), 2)}}
                for wn in checks:
                    c2, s2 = stats[wn]
                    row[wn] = {"n": int(c2[i, j]), "mean": round(float(s2[i, j, p] / c2[i, j]), 2) if c2[i, j] else None}
                row["_ij"] = (i, j, int(p))
                top.append(row)
                if len(top) >= 25:
                    break
            best = top[0]
            i, j, p = best.pop("_ij")
            for r in top[1:]:
                r.pop("_ij", None)
            sel = Cm[:, i] & Cm[:, j] & rm
            best["coins_ins"] = coins_of(Mt, P, sel & np.isin(W, ins), BPLANS[p], names, mxb)
            for wn in checks:
                best["coins_" + wn] = coins_of(Mt, P, sel & (W == wn), BPLANS[p], names, mxb)
                pc = profit(mB[sel & (W == wn), p])
                best[wn]["profit"] = pc
            best["ins"]["profit"] = profit(mB[sel & np.isin(W, ins), p])
            # the luck size: the best rule on the first check window in hindsight, and its in-sample result
            c2, s2 = stats[checks[0]]
            m2 = np.where(c2[:, :, None] >= 40, s2 / np.maximum(c2[:, :, None], 1), -np.inf)
            f2 = m2[iu[0], iu[1], :]
            a, p2 = np.unravel_index(np.argmax(f2), f2.shape)
            i2, j2 = int(iu[0][a]), int(iu[1][a])
            hind = {"rule": labs[i2] + ("" if i2 == j2 else " AND " + labs[j2]), "plan": BPLANS[p2],
                    checks[0]: {"n": int(c2[i2, j2]), "mean": round(float(m2[i2, j2, p2]), 2)},
                    "ins": {"n": int(cnt[i2, j2]), "mean": round(float(sm[i2, j2, p2] / cnt[i2, j2]), 2) if cnt[i2, j2] else None}}
            nrules = int(np.isfinite(flat).sum())
            pos_ins = int((flat > COST).sum())
            res[fam]["frames"][role] = {"rulesWith40": nrules, "positiveInSampleAfterCost": pos_ins, "best": best, "top25": top,
                                        "bestOn_" + checks[0] + "_inHindsight": hind}
            log(fam, role, "rules", nrules, "positive in-sample", pos_ins, "BEST", best["rule"], best["plan"], best["ins"],
                {wn: (best[wn]["n"], best[wn]["mean"]) for wn in checks}, "| hindsight", hind)
        json.dump(res, open(os.path.join(out, "best.json"), "w"), indent=1)


# --------------------------------------------------------------------------------------------------------- Part 4: the jury
JURY_ROLES = CC.ROLES


def fnum(x, nd=2):
    if x is None or not np.isfinite(x):
        return "unknown"
    return ("%." + str(nd) + "f") % x


def cmd_cards(out, jd):
    """The jury's cards: w4 frame-A buys the chosen family-B rule takes (sample 60) + 60 random ones it does not take."""
    Mt, P, D, F, FE, Fx = load(out)
    BM = np.load(os.path.join(out, "buyplans.npy"))
    mB = money(BM)
    okb, Rb, Zb, mxb = buy_labels(Mt, P)
    bj = json.load(open(os.path.join(out, "buy.json")))
    ch = bj["B"]["test"]["frames"]["A"]["chosen"]
    Xf, names = buy_X(FE, Fx, "B")
    gm = Mt["gm"].to_numpy().astype(np.float64)
    fit, judges = win_rows(Mt, "B", "test")
    W = Mt["w"].to_numpy()
    rm = roles_of(Mt, "A")
    use, y = (okb, Rb) if ch["model"] == "bR" else (okb & (Rb | Zb), Rb)
    oof, sc, _, _ = oof_full(Xf, (use, y), fit, gm, W == "w4")
    cutv = float(np.nanquantile(oof[fit & rm], 1 - ch["q"]))
    J = rm & (W == "w4")
    take = J & (sc >= cutv)
    log("rule takes", int(take.sum()), "of", int(J.sum()), "w4 frame-A buys; buy.json said", bj["B"]["test"]["frames"]["A"]["test"]["w4"]["n"])
    if take.sum() < 10:
        json.dump({"skipped": "the rule takes fewer than 10 w4 buys"}, open(os.path.join(jd, "skipped.json"), "w"))
        return
    rng = np.random.default_rng(SEED)
    a = np.nonzero(take)[0]
    b = np.nonzero(J & ~take)[0]
    a = np.sort(rng.choice(a, size=min(60, len(a)), replace=False))
    b = np.sort(rng.choice(b, size=60, replace=False))
    cases = np.r_[a, b]
    rng.shuffle(cases)
    j = BPLANS.index(ch["plan"])
    w3 = rm & (W == "w3")
    base = {"buys": int(w3.sum()), "mean": round(float(mB[w3, j].mean()), 2), "pos": round(100 * float((mB[w3, j] > 0).mean()), 1),
            "rocket": round(100 * float((Rb & okb & w3).sum() / max((okb & w3).sum(), 1)), 2),
            "zero": round(100 * float((Zb & okb & w3).sum() / max((okb & w3).sum(), 1)), 1)}
    ix = {n: i for i, n in enumerate(names)}
    v = lambda i, f: float(Xf[i, ix[f]])
    lines = []
    key = []
    for cid, i in enumerate(cases, 1):
        r = Mt.iloc[i]
        pre = P["preC"][i][:-1]             # amendment 1: the stored 36th close (the candle the buy falls in) ends after the buy
        prv = P["preV"][i][:-1]
        txt = ["=== CASE %d ===" % cid,
               "At the buy: %d h after the graduation; market cap %s USD; liquidity %s USD; 24 h volume %s USD; price change 1 h %s %%, 6 h %s %%, "
               "24 h %s %%." % (int(r["E"]) // 60, fnum(r["mc"], 0), fnum(r["liq"], 0), fnum(r["v24"], 0), fnum(100 * r["r1h"], 0),
                                fnum(100 * r["r6h"], 0), fnum(100 * r["r24h"], 0)),
               "The 35 five-minute closes before the buy as a multiple of the buy price (oldest first; the last one is the buy price): " + " ".join(fnum(x, 2) for x in pre),
               "Their volumes (USD): " + " ".join(fnum(x, 0) for x in prv),
               "Market: SOL 1 h %s %%, 6 h %s %%, 24 h %s %%; BTC 24 h %s %%." % tuple(fnum(100 * v(i, f), 1) for f in ("sol1h", "sol6h", "sol24h", "btc24h")),
               "Launch: bonding curve %s minutes; creator's graduations in the 30 days before %s; creator's launches in the 30 days before %s; "
               "graduations in the 24 h before %s; graduations sharing a name word in the 24 h before %s; copycat tickers in 7 days %s; CJK name %s; "
               "links %s; X link type %s (0 none, 1 a post, 2 a profile/community); description length %s; picture group %s (0 animal photo, "
               "1 animal drawn, 2 person photo, 3 drawn character, 4 text/logo, 5 object/scene); picture used by a graduation of the week before %s; "
               "look-alike picture %s." % (fnum(v(i, "f_curve_min"), 1), fnum(v(i, "f_creator_prior"), 0), fnum(v(i, "l_creator_launches30"), 0),
                                         fnum(v(i, "f_grads24"), 0), fnum(v(i, "f_theme24"), 0), fnum(v(i, "f_dup7"), 0), fnum(v(i, "f_cjk"), 0),
                                         fnum(v(i, "f_nlinks"), 0), fnum(v(i, "f_xtype"), 0), fnum(v(i, "f_desc_len"), 0), fnum(v(i, "f_group"), 0),
                                         fnum(v(i, "f_img_reused"), 0), fnum(v(i, "f_lookalike"), 0)),
               "Holders and flow in the hour before: buyers %s, sellers %s, buys %s, sells %s, the top buyer's share of buying %s; in 24 h buys %s, sells %s."
               % tuple(fnum(v(i, "h_" + f), 0 if "share" not in f else 3) for f in ("buyers_1h", "sellers_1h", "buys_1h", "sells_1h",
                                                                                   "top_buyer_share_1h", "buys_24h", "sells_24h")),
               "Wallets (first buys of 0.1 SOL or more since the graduation): %s so far, %s in the last 15 min, %s in the last 60 min with %s SOL; "
               "share with 5+ earlier finished coins %s, share with an earlier 3x coin %s; the largest first buy's share of all first-buy SOL %s."
               % (fnum(v(i, "w_n"), 0), fnum(v(i, "w_new15"), 0), fnum(v(i, "w_new60"), 0), fnum(v(i, "w_sol60"), 1),
                  fnum(v(i, "w_exp_share"), 2), fnum(v(i, "w_win_share"), 2), fnum(v(i, "w_top_share"), 3))]
        lines.append("\n".join(txt) + "\n")
        key.append({"case": cid, "row": int(i), "eid": r["eid"], "taken": bool(take[i]), "mult": float(BM[i, j]), "eur": float(mB[i, j]),
                    "rocket": bool(Rb[i]), "high24": float(mxb[i])})
    os.makedirs(jd, exist_ok=True)
    head = ("You are one reviewer of a jury of ten. Fake money only (a paper-trading research test, nothing is bought). Each case is a "
            "Solana meme coin some hours after it graduated from pump.fun, at the moment a bot could buy it for 50 EUR. If bought, it is "
            "sold by the 'Sell bot' rule: floor at half the buy price, a trailing stop 15 %% under the highest price once it reached 1.5x, "
            "a sell when the price drops 15 %% within 30 minutes, take profit at 11x, otherwise sold 6 h after the buy. Paper fees 1 %% "
            "each side; a real-cost allowance of 0.75 EUR per trade. Decide for each case: BUY (you expect the trade to end with more than "
            "the 50 EUR plus costs) or SKIP. Base rates from the month before (w3, %d buys of this kind): mean result %s EUR per buy, "
            "%s %% ended in profit, %s %% reached 10x within 24 h, %s %% fell to a tenth without ever reaching 2x.\n\n" % (base["buys"], base["mean"], base["pos"],
                                                                                                            base["rocket"], base["zero"]))
    open(os.path.join(jd, "cards.txt"), "w").write(head + "\n".join(lines))
    json.dump({"chosen": ch, "base_w3": base, "cases": key}, open(os.path.join(out, "jury_key.json"), "w"), indent=1)
    log("cards", len(cases), "taken", int(take[cases].sum()))


def read_votes(jd, rnd):
    votes = {}
    for k in range(1, 11):
        f = os.path.join(jd, "r%d_%d.json" % (rnd, k))
        if os.path.exists(f):
            votes[k] = {int(x["case"]): x for x in json.load(open(f))}
    return votes


def cmd_debate(out, jd):
    v = read_votes(jd, 1)
    assert len(v) == 10, len(v)
    cases = sorted(v[1])
    txt = []
    for c in cases:
        parts = ["CASE %d round-1 votes:" % c]
        for k in range(1, 11):
            x = v[k].get(c, {})
            parts.append("  reviewer %d (%s): %s, p %s, %s" % (k, JURY_ROLES[k - 1], x.get("vote"), x.get("p"), x.get("reason", "")))
        txt.append("\n".join(parts))
    open(os.path.join(jd, "debate.txt"), "w").write("\n\n".join(txt) + "\n")


def cmd_jury(out, jd):
    key = json.load(open(os.path.join(out, "jury_key.json")))
    K = {c["case"]: c for c in key["cases"]}
    res = {"chosen": key["chosen"], "rounds": {}}
    for rnd in (1, 2):
        v = read_votes(jd, rnd)
        nb = {c: sum(1 for k in v if v[k].get(c, {}).get("vote") == "BUY") for c in K}
        pm = {c: np.mean([float(v[k][c].get("p", 0.5)) for k in v if c in v[k]]) for c in K}
        buy = [c for c in K if nb[c] >= 6]
        eur = np.array([K[c]["eur"] for c in buy])
        allr = np.array([K[c]["rocket"] for c in K])
        allp = np.array([pm[c] for c in K])
        from sklearn.metrics import roc_auc_score
        pos = np.array([K[c]["eur"] > COST for c in K])
        res["rounds"][rnd] = {"buys": len(buy), "buysTakenByRule": int(sum(K[c]["taken"] for c in buy)),
                              "meanEurAfterCost": round(float(eur.mean() - COST), 2) if len(buy) else None,
                              "rocketsBought": int(sum(K[c]["rocket"] for c in buy)), "rocketsAll": int(allr.sum()),
                              "aucProfit": round(float(roc_auc_score(pos, allp)), 3) if pos.any() and (~pos).any() else None,
                              "aucRocket": round(float(roc_auc_score(allr, allp)), 3) if allr.any() else None,
                              "votesPerReviewer": {k: sum(1 for c in v[k] if v[k][c].get("vote") == "BUY") for k in v},
                              "profit": profit(np.array([K[c]["eur"] for c in buy]))}
    tk = [c for c in K if K[c]["taken"]]
    res["ruleOnCards"] = {"buys": len(tk), "meanEurAfterCost": round(float(np.mean([K[c]["eur"] for c in tk]) - COST), 2)}
    res["randomOnCards"] = {"buys": len(K) - len(tk), "meanEurAfterCost": round(float(np.mean([K[c]["eur"] for c in K if not K[c]["taken"]]) - COST), 2)}
    json.dump(res, open(os.path.join(out, "jury.json"), "w"), indent=1)
    log(json.dumps(res))


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"ceiling": cmd_ceiling, "buy": cmd_buy, "hold": cmd_hold, "similar": cmd_similar, "best": cmd_best,
     "cards": cmd_cards, "debate": cmd_debate, "jury": cmd_jury}[cmd](*sys.argv[2:])
