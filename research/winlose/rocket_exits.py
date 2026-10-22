"""Test 2 of PREREG-EARLY-EXIT-2026-10-22.md (fake money only): 134 exit rules for the rocket hunter's buys, from the one-minute bars
of the first 55 hours (branch chartbars55), against rule A (-30% stop, 11x target, 6 h). The choice is made on the early weeks
before the late weeks' numbers are printed.
usage: python3 research/winlose/rocket_exits.py <scratch> [variant]   (needs early_picks.pkl, cb55/; variant: test 1's choice, V30
default)  -> <scratch>/rocket_exits.json; FIX=1 reads early_picks_fix.pkl -> rocket_exits_fix.json;
GRID=live reads early_picks_live.pkl -> rocket_exits_live.json"""
import glob, importlib, itertools, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
S = sys.argv[1]
VAR = sys.argv[2] if len(sys.argv) > 2 else "V30"
sys.path.insert(0, os.path.join(HERE, "..", "..")); sys.path.insert(0, os.path.join(HERE, ".."))
import memebot as M
FS = importlib.import_module("filter_search")

LATE = 1790294400000
CUTS = (0.005, 0.01, 0.02)


def rules():
    out = []
    for st, tp, h in itertools.product((None, 0.70, 0.50, 0.30), (3.0, 5.0, 11.0, 20.0, None), (2, 6, 12, 24)):
        out.append({"fam": "F", "stop": st, "target": tp, "hold_h": h})
    for w, fr, h in itertools.product((0.30, 0.40, 0.50, 0.60), (1.0, 2.0, 3.0), (6, 24)):
        out.append({"fam": "T", "stop": 0.70, "trail": w, "trail_from": fr, "hold_h": h})
    for frac, at in itertools.product((0.5, 1 / 3), (2.0, 3.0, 5.0)):
        out.append({"fam": "P", "stop": 0.70, "part": [frac, at], "rest": "A", "target": 11.0, "hold_h": 6})
        for w, h in itertools.product((0.40, 0.50), (6, 24)):
            out.append({"fam": "P", "stop": 0.70, "part": [frac, at], "rest": "trail", "trail": w, "trail_from": 0.0, "hold_h": h})
    return out


def name(r):
    pc = lambda x: "-%d%%" % round(100 * (1 - x))
    if r["fam"] == "F":
        return "stop %s, target %s, %d h" % (pc(r["stop"]) if r["stop"] else "none", "%gx" % r["target"] if r["target"] else "none", r["hold_h"])
    if r["fam"] == "T":
        return "trail %d%% %s, %d h" % (round(100 * r["trail"]), "at once" if r["trail_from"] <= 1 else "from %gx" % r["trail_from"], r["hold_h"])
    f, at = r["part"]
    rest = "rest rule A" if r["rest"] == "A" else "rest trail %d%%, %d h" % (round(100 * r["trail"]), r["hold_h"])
    return "sell %s at %gx, %s" % ("1/2" if f == 0.5 else "1/3", at, rest)


def walk(r, hi, lo, c):
    """One position under rule r. hi/lo/c: the minutes from the buy on, as multiples of the buy price (index 0 = the first minute
    after the buy). -> [(fraction, multiple, why), ...]. A stop sells at the minute's low, a target at its level, a stop before a
    target in the same minute; a trail follows the highest high up to the minute before; at the time limit the last close."""
    L = int(r["hold_h"] * 60)
    rem, peak, sold, part_done = 1.0, 1.0, [], False
    n = min(L, len(c))
    for i in range(n):
        h, l = hi[i], lo[i]
        # the stop level for this minute
        if r["fam"] == "T":
            level = peak * (1 - r["trail"]) if peak >= r["trail_from"] else r["stop"]
        elif r["fam"] == "P" and part_done and r["rest"] == "trail":
            level = peak * (1 - r["trail"])
        else:
            level = r.get("stop")
        if level is not None and l <= level:
            sold.append((rem, l, "stop")); rem = 0.0
            break
        if r["fam"] == "P" and not part_done and h >= r["part"][1]:
            sold.append((r["part"][0], r["part"][1], "part")); rem -= r["part"][0]; part_done = True
        tgt = r.get("target") if (r["fam"] == "F" or (r["fam"] == "P" and r["rest"] == "A")) else None
        if tgt and h >= tgt:
            sold.append((rem, tgt, "target")); rem = 0.0
            break
        peak = max(peak, h)
    if rem > 1e-9:
        sold.append((rem, c[n - 1] if n else 1.0, "time"))
    return sold


def eur_of(sold):
    inv = M.TICKET - M.fee(M.TICKET)
    return round(sum(inv * f * m - M.fee(inv * f * m) for f, m, _ in sold) - M.TICKET, 2)


def bars(pools):
    out = {}
    for f in sorted(glob.glob(os.path.join(S, "cb55", "bars_*.parquet"))):
        b = pd.read_parquet(f, columns=["pool", "mi", "p_close", "p_hi", "p_lo"])
        b = b[b["pool"].isin(pools)]
        for pool, g in b.groupby("pool"):
            n = int(g["mi"].max()) + 1
            mi = g["mi"].to_numpy()
            c = np.full(n, np.nan); c[mi] = g["p_close"].to_numpy(); c = pd.Series(c).ffill().to_numpy()
            hi = np.full(n, np.nan); hi[mi] = g["p_hi"].to_numpy(); hi = np.where(np.isnan(hi), c, hi)
            lo = np.full(n, np.nan); lo[mi] = g["p_lo"].to_numpy(); lo = np.where(np.isnan(lo), c, lo)
            out[pool] = (c, hi, lo)
    return out


if __name__ == "__main__":
    FIX = "_fix" if os.environ.get("FIX") else ("_live" if os.environ.get("GRID") == "live" else "")
    PK = pd.read_pickle(os.path.join(S, "early_picks%s.pkl" % FIX))
    PK = PK[(PK["variant"] == VAR) & (PK["seed"] == 7)].copy()
    RU = rules()
    A = next(j for j, r in enumerate(RU) if r["fam"] == "F" and r["stop"] == 0.70 and r["target"] == 11.0 and r["hold_h"] == 6)
    B = bars(set(PK["pool"]))
    key = PK[["pool", "E"]].drop_duplicates()
    res, bad = {}, 0
    for pool, E in key.itertuples(index=False):
        c, hi, lo = B[pool]
        p0 = c[E - 1]
        hh, ll, cc = (hi[E:E + 24 * 60] / p0).tolist(), (lo[E:E + 24 * 60] / p0).tolist(), (c[E:E + 24 * 60] / p0).tolist()
        res[(pool, E)] = [walk(r, hh, ll, cc) for r in RU]
    PK["sold"] = [res[(p, e)] for p, e in zip(PK["pool"], PK["E"])]
    # check: rule A here gives the grid's rule A multiple (same bars, same conventions)
    gm = np.array([sum(f * m for f, m, _ in s[A]) for s in PK["sold"]])
    bad = int((np.abs(gm - PK["mult"].to_numpy()) > 1e-4 * np.maximum(1, PK["mult"].to_numpy())).sum())
    print("picks %d (%s, seed 7), rule A replay differs from the grid on %d" % (len(PK), VAR, bad), flush=True)
    EUR = np.array([[eur_of(s) for s in ss] for ss in PK["sold"]])
    MUL = np.array([[sum(f * m for f, m, _ in s) for s in ss] for ss in PK["sold"]])
    X10 = np.array([[any(f > 0 and m >= 10 for f, m, _ in s) for s in ss] for ss in PK["sold"]])
    late = (PK["week"] >= LATE).to_numpy()
    cut = PK["cut"].to_numpy()

    def st(ix, j):
        v = EUR[ix, j]
        if not len(v):
            return {"coins": 0}
        rng = np.random.default_rng(7)
        bs = np.sort(v[rng.integers(0, len(v), (2000, len(v)))].mean(1))
        return {"coins": int(len(v)), "avg": round(float(v.mean()), 2), "lo95": round(float(bs[50]), 2), "hi95": round(float(bs[1949]), 2),
                "inProfitOf10": round(10 * float((v > 0).mean()), 1), "x10booked": round(100 * float(X10[ix, j].mean()), 1),
                "total": round(float(v.sum()), 1)}

    def sim(ix, j):
        cap = FS.MULT_CAP
        FS.MULT_CAP = 1e9                 # the rule's own multiple, not the 11x cap of rule A
        try:
            s = FS.simulate({"scan": PK["ts"].to_numpy(np.float64)[ix], "mult": MUL[ix, j]}, np.arange(len(ix)))
        finally:
            FS.MULT_CAP = cap
        if s:
            s.pop("curve", None)
        return s

    I = {c: np.flatnonzero(cut == c) for c in CUTS}
    Ie = {c: np.flatnonzero((cut == c) & ~late) for c in CUTS}
    Il = {c: np.flatnonzero((cut == c) & late) for c in CUTS}
    dev = {c: EUR[Ie[c]].mean(0) for c in CUTS}
    ok = [j for j in range(len(RU)) if all(dev[c][j] > dev[c][A] for c in CUTS)]
    print("rule A, early weeks: %s" % {"%g" % c: st(Ie[c], A) for c in CUTS})
    print("%d of %d rules beat rule A in the early weeks at all three tiers" % (len(ok), len(RU)))
    top = sorted(range(len(RU)), key=lambda j: -dev[0.02][j])[:12]
    print("the 12 best at the top 2%, early weeks:")
    for j in top:
        print("  %-40s 2%%: %+6.2f  1%%: %+6.2f  0.5%%: %+6.2f %s" % (name(RU[j]), dev[0.02][j], dev[0.01][j], dev[0.005][j], "*" if j in ok else ""))
    choice = max(ok, key=lambda j: dev[0.02][j]) if ok else None
    print("\nTHE CHOICE (early weeks):", name(RU[choice]) if choice is not None else "none (rule A stays)", flush=True)
    out = {"variant": VAR, "picks": int(len(PK)), "replayDiff": bad, "rules": [name(r) for r in RU], "ruleA": name(RU[A]),
           "choice": name(RU[choice]) if choice is not None else None, "beatEarlyAll3": len(ok),
           "early": {name(RU[j]): {"%g" % c: round(float(dev[c][j]), 2) for c in CUTS} for j in range(len(RU))}}
    if choice is not None:
        print("\nLATE WEEKS, once:")
        tab = {}
        for lab, j in (("choice", choice), ("ruleA", A)):
            tab[lab] = {"%g" % c: {"all": st(I[c], j), "early": st(Ie[c], j), "late": st(Il[c], j), "sim": sim(I[c], j)} for c in CUTS}
            for c in CUTS:
                t = tab[lab]["%g" % c]
                print("  %-7s top %-5s all %s | late %s | sims in profit %s" % (lab, "%g%%" % (100 * c), t["all"], t["late"], (t["sim"] or {}).get("pProfit")))
        d = EUR[Il[0.02], choice] - EUR[Il[0.02], A]
        rng = np.random.default_rng(7)
        bs = np.sort(d[rng.integers(0, len(d), (2000, len(d)))].mean(1)) if len(d) else np.array([np.nan])
        chk = {"a_late_beats_A_0.5": bool(EUR[Il[0.005], choice].mean() > EUR[Il[0.005], A].mean()),
               "a_late_beats_A_2": bool(EUR[Il[0.02], choice].mean() > EUR[Il[0.02], A].mean()),
               "b_late_paired_lo95_above_0": bool(len(d) and bs[50] > 0),
               "c_sims_not_below": bool((tab["choice"]["0.005"]["sim"] or {}).get("pProfit", -1) >= (tab["ruleA"]["0.005"]["sim"] or {}).get("pProfit", 101))}
        out.update(table=tab, pairedLate2={"coins": int(len(d)), "avg": round(float(d.mean()), 2), "lo95": round(float(bs[50]), 2),
                                            "hi95": round(float(bs[1949]), 2)}, checks=chk, holds=all(chk.values()), rule=RU[choice])
        print("  paired late top 2%% (choice - rule A): %s" % out["pairedLate2"])
        print("  checks:", chk, "-> HOLDS" if out["holds"] else "-> does not hold (rule A stays)")
    # for information: every family's best on all weeks at the top 0.5% (not a choice)
    info = {}
    for fam in "FTP":
        js = [j for j, r in enumerate(RU) if r["fam"] == fam]
        j = max(js, key=lambda j: EUR[I[0.005], j].mean())
        info[fam] = {"rule": name(RU[j]), "all0.5": st(I[0.005], j)}
    out["infoBestPerFamily"] = info
    out["ruleA_all"] = {"%g" % c: dict(st(I[c], A), sim=sim(I[c], A)) for c in CUTS}
    print("info, best per family on all weeks at 0.5%% (hindsight, not a choice): %s" % info)
    json.dump(out, open(os.path.join(S, "rocket_exits%s.json" % FIX), "w"), default=float)
