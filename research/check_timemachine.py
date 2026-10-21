"""The pre-registered check of research/PREREG-TIMEMACHINE-2026-10-21.md (fake money only): the Time Machine's look-alike forecasts
against the trained odds (up, zp) of the 2h tips. Written before any forecast was computed.
usage: python3 research/check_timemachine.py <memesnapres dir> <memerec dir>      (needs numpy)
"""
import glob, json, math, os, sys
import numpy as np

LEARN_FROM = 1791380700000
K, SHRINK = 100, 10.0
FEATS = ("lage", "lmc", "liqMc", "lvol", "c1", "c6", "buyShare")


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def feats(c):
    f = c.get("f") or {}
    age, mc, vm = num(f.get("ageH")), num(c.get("mc")), num(f.get("volMc"))
    cl = lambda v: None if v is None else max(-100.0, min(300.0, v))
    return [math.log10(age) if age and age > 0 else None, math.log10(mc) if mc and mc > 0 else None, num(f.get("liqMc")),
            math.log10(1 + vm) if vm is not None and vm >= 0 else None, cl(num(f.get("c1"))), cl(num(f.get("c6"))), num(f.get("buyShare"))]


def load_pool(d):
    rows = []      # (t_scored, t0, addr, profit, zero, feats)
    for fn in sorted(glob.glob(os.path.join(d, "*.json"))):
        doc = json.load(open(fn, encoding="utf-8"))
        if str(doc.get("rule") or "") != "m9-2h":
            continue
        t0, t1 = num(doc.get("t0")), num(doc.get("t"))
        if not t0 or not t1 or t1 < LEARN_FROM:
            continue
        for c in doc.get("coins") or []:
            eur, mc, liq = num(c.get("eur")), num(c.get("mc")), num(c.get("liq"))
            if eur is None or mc is None or liq is None or liq < 10_000 or not (30_000 <= mc <= 5_000_000):
                continue
            zero = bool(c.get("gone")) or (num(c.get("mult")) or 0.0) < 0.02
            rows.append((t1, t0, c.get("a"), eur > 0, zero, feats(c)))
    return rows


def load_tips(d):
    tips = []
    for fn in sorted(glob.glob(os.path.join(d, "*.json"))):
        doc = json.load(open(fn, encoding="utf-8"))
        if str(doc.get("rule") or "") != "m9-2h":
            continue
        out = doc.get("out") or {}          # the horizon's result sits at the top level (outs holds the 1 h and 24 h checks)
        res = {p.get("sym"): p for p in out.get("picks") or [] if isinstance(p, dict)}
        for p in doc.get("picks") or []:
            r = res.get(p.get("sym"))
            if num(p.get("up")) is None or num(p.get("zp")) is None or not r or num(r.get("eur")) is None:
                continue
            zero = bool(r.get("gone")) or (num(r.get("mult")) is not None and num(r.get("mult")) < 0.02)
            tips.append({"t": num(doc.get("t")), "a": p.get("addr"), "sym": p.get("sym"), "up": num(p["up"]), "zp": num(p["zp"]), "profit": num(r["eur"]) > 0, "zero": zero})
    return tips


def main():
    pool = load_pool(sys.argv[1])
    tips = load_tips(sys.argv[2])
    T1 = np.array([r[0] for r in pool])
    T0 = np.array([r[1] for r in pool])
    A = np.array([str(r[2]) for r in pool])
    P = np.array([r[3] for r in pool], dtype=float)
    Z = np.array([r[4] for r in pool], dtype=float)
    X = np.array([[np.nan if v is None else v for v in r[5]] for r in pool], dtype=float)
    print("pool %d rows, %d tips with odds and a result" % (len(pool), len(tips)))
    out = []
    for tp in tips:
        own = np.where((A == str(tp["a"])) & (np.abs(T0 - tp["t"]) <= 30 * 60_000))[0]
        if not len(own):
            continue
        x = X[own[0]]
        m = T1 < tp["t"]
        if m.sum() < 1000:
            continue
        Xp, Pp, Zp, Ap = X[m], P[m], Z[m], A[m]
        med = np.nanmedian(Xp, axis=0)
        iqr = np.nanpercentile(Xp, 75, axis=0) - np.nanpercentile(Xp, 25, axis=0)
        iqr[~(iqr > 0)] = 1.0
        S = (Xp - med) / iqr
        s = (x - med) / iqr
        D2 = (S - s) ** 2
        avg = np.nanmean(D2, axis=0)
        D2 = np.where(np.isnan(D2), avg, D2)
        dist = D2.sum(axis=1)
        order = np.argsort(dist, kind="stable")
        seen, idx = set(), []
        for i in order:
            if Ap[i] in seen:
                continue
            seen.add(Ap[i])
            idx.append(i)
            if len(idx) == K:
                break
        bp, bz = Pp.mean(), Zp.mean()
        fp = (Pp[idx].sum() + SHRINK * bp) / (len(idx) + SHRINK)
        fz = (Zp[idx].sum() + SHRINK * bz) / (len(idx) + SHRINK)
        out.append(dict(tp, tmP=fp, tmZ=fz, baseP=bp, baseZ=bz))
    if not out:
        print("no tips matched")
        return
    out.sort(key=lambda r: r["t"])
    if os.environ.get("TM_DUMP"):          # the forecasts per tip, for later studies (added after the decision; does not change it)
        json.dump(out, open(os.environ["TM_DUMP"], "w"), default=lambda v: v.item() if hasattr(v, "item") else str(v))
    brier = lambda rs, k, y: sum((r[k] - (1.0 if r[y] else 0.0)) ** 2 for r in rs) / len(rs)
    mid = len(out) // 2
    print("tips with a forecast: %d; profit %.1f%%, zero %.1f%%" % (len(out), 100 * sum(r["profit"] for r in out) / len(out), 100 * sum(r["zero"] for r in out) / len(out)))
    for name, rs in (("all", out), ("first half", out[:mid]), ("second half", out[mid:])):
        print("%-12s profit Brier: TM %.4f trained %.4f base %.4f | zero Brier: TM %.4f trained %.4f base %.4f (%d tips)" % (
            name, brier(rs, "tmP", "profit"), brier(rs, "up", "profit"), brier(rs, "baseP", "profit"),
            brier(rs, "tmZ", "zero"), brier(rs, "zp", "zero"), brier(rs, "baseZ", "zero"), len(rs)))
    for k, y in (("tmP", "profit"), ("up", "profit"), ("tmZ", "zero"), ("zp", "zero")):
        rs = sorted(out, key=lambda r: r[k])
        bins = [rs[i * len(rs) // 5:(i + 1) * len(rs) // 5] for i in range(5)]
        print("calibration %-4s: %s" % (k, "  ".join("%.2f->%.2f" % (sum(r[k] for r in b) / len(b), sum(r[y] for r in b) / len(b)) for b in bins if b)))
    rep = lambda h: brier(h, "tmP", "profit") < brier(h, "up", "profit")
    ok = rep(out) and brier(out, "tmZ", "zero") < brier(out, "zp", "zero") and rep(out[:mid]) and rep(out[mid:])
    print("DECISION: %s" % ("REPLACE the trained odds" if ok else "KEEP the trained odds"))


if __name__ == "__main__":
    main()
