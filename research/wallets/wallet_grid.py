"""Copy trading round 2: the grid and the finalists (research/wallets/PREREG-COPY2-2026-11-13.md). Fake money only.

usage: python3 research/wallets/wallet_grid.py <dir with e2_*.npz (any depth)> <out dir> dev
       python3 research/wallets/wallet_grid.py <dir> <out dir> final <finalists.json>
"dev" runs all 7,680 cells on the dev days and names the finalists. "final" runs only the finalists on the hidden days.
"""
import calendar, glob, json, os, sys, time
import numpy as np

DELAYS = (1, 2, 5, 30)
LISTS = ("S1", "S2", "S3", "S4", "S5")
WINS = (21, 7)
EXITS = ("mirror", "tp50sl20", "tp100sl30", "hold")
FILTERS = ("all", "age<2m", "age2-15m", "age>15m", "mc<10k", "mc10-30k", "mc>30k", "two")
FEES = (("fomo", 20), ("fomo", 50), ("fomo", 100), ("fomo", 200), ("jup", 20), ("jup", 100))
GAP = 3
SKIP = {"2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07"}
DEV = ("2026-09-02", "2026-09-19")
HOLD = ("2026-09-20", "2026-10-06")
BOOT, SEED, SLIP, HAIRCUT = 2000, 13, 0.01, 0.90


def dnum(d):
    return calendar.timegm(time.strptime(d, "%Y-%m-%d"))


def fee(x):
    return np.where(x < 5, 0.10, np.where(x < 47.5, 0.02 * x, np.where(x < 190, 0.95, 0.005 * x)))


def pnl(r, how, vs, usd, kind, T):
    """$ result of a T $ ticket: ratio r (1% a side inside), minus the own price impact on the curve at the buy and at the sell,
    minus the fee. A completed curve is sold 10% lower."""
    r = r.astype(np.float64); vs = vs.astype(np.float64); usd = usd.astype(np.float64)
    ts = T / usd
    v = ts * r * np.where(how == 3, HAIRCUT, 1.0) / (1 + ts / vs)
    vsx = vs * np.sqrt(np.maximum(r * (1 + SLIP) / (1 - SLIP), 1e-12))        # on the curve the price goes with the pool squared
    out = v / (1 + v / vsx) * usd
    if kind == "jup":
        return out - T - 0.10
    return out - T - fee(np.full_like(out, float(T))) - fee(out)


def load(path):
    z = np.load(path)
    return {k: z[k] for k in z.files}


def aggregate(d):
    w, inv = np.unique(d["w"], return_inverse=True)
    bc = lambda x: np.bincount(inv, weights=x.astype(np.float64), minlength=len(w))
    a = dict(w=w, n=bc(np.ones(len(inv))), own_win=bc(d["own_pnl"] > 0), own=bc(d["own_pnl"]), sold=bc(d["hold"] >= 0),
             slow=bc(d["hold"] >= 60), buy=bc(d["buy_sol"]))
    for dl in DELAYS:
        x = d["r%d" % dl][:, 0].astype(np.float64) - 1
        ok = ~np.isnan(x); x = np.where(ok, x, 0.0)
        a["n%d" % dl] = bc(ok); a["s%d" % dl] = bc(x); a["ss%d" % dl] = bc(x * x)
    return a


def lists(aggs):
    """{(list, delay): wallet hashes} from the window's per-day aggregates."""
    uw, inv = np.unique(np.concatenate([a["w"] for a in aggs]), return_inverse=True)
    col = lambda k: np.bincount(inv, weights=np.concatenate([a[k] for a in aggs]), minlength=len(uw))
    n_all, own_win, own, sold, slow, buy = (col(k) for k in ("n", "own_win", "own", "sold", "slow", "buy"))
    slow_ok = (sold > 0) & (slow / np.maximum(sold, 1) >= 0.5)
    out = {}
    c5 = np.flatnonzero((n_all >= 10) & (own_win / np.maximum(n_all, 1) >= 0.5) & slow_ok)
    s5 = uw[c5[np.argsort(-own[c5], kind="stable")[:300]]]
    for dl in DELAYS:
        n, s, ss = col("n%d" % dl), col("s%d" % dl), col("ss%d" % dl)
        mean = s / np.maximum(n, 1)
        var = np.maximum(ss / np.maximum(n, 1) - mean ** 2, 0) * n / np.maximum(n - 1, 1)
        tv = np.where(var > 0, mean / np.sqrt(np.maximum(var, 1e-30) / np.maximum(n, 1)), 0.0)
        top = lambda mask, score, k: uw[np.flatnonzero(mask)[np.argsort(-score[mask], kind="stable")[:k]]]
        out["S1", dl] = top((n >= 10) & (mean > 0) & (tv >= 2), tv, 300)
        out["S2", dl] = top((n >= 20) & (mean > 0) & (tv >= 3), tv, 100)
        out["S3", dl] = top((n >= 10) & (mean > 0) & slow_ok, mean, 100)
        out["S4", dl] = top((n >= 10) & (mean > 0) & (buy / np.maximum(n_all, 1) >= 1.0), mean, 100)
        out["S5", dl] = s5
    return out


def first_per_coin(m, idx):
    _, f = np.unique(m[idx], return_index=True)
    return idx[np.sort(f)]


def picks(d, dl, wl, order):
    """{filter: event indices} for one list at one delay."""
    hit = order[np.isin(d["w"][order], wl)]
    age, mc, m = d["age%d" % dl], d["mc%d" % dl], d["m"]
    out = {"all": first_per_coin(m, hit)}
    for name, mask in (("age<2m", age < 120), ("age2-15m", (age >= 120) & (age < 900)), ("age>15m", age >= 900),
                       ("mc<10k", mc < 10e3), ("mc10-30k", (mc >= 10e3) & (mc < 30e3)), ("mc>30k", mc >= 30e3)):
        out[name] = first_per_coin(m, hit[mask[hit]])
    two, seen = [], {}
    for i in hit.tolist():
        s = seen.setdefault(int(m[i]), [int(d["w"][i]), False])
        if not s[1] and int(d["w"][i]) != s[0]:
            s[1] = True; two.append(i)
    out["two"] = np.array(two, np.int64)
    return out


def ci(sums, cnts, rng, lo=2.5, hi=97.5):
    """Bootstrap by day for many cells at once: sums, cnts are (cells, days)."""
    nd = sums.shape[1]
    los, his = [], []
    k = rng.integers(0, nd, (BOOT, nd))
    L = np.empty((BOOT, sums.shape[0]))
    for b in range(BOOT):
        c = cnts[:, k[b]].sum(1)
        L[b] = np.where(c > 0, sums[:, k[b]].sum(1) / np.maximum(c, 1), np.nan)
    return np.nanpercentile(L, lo, axis=0), np.nanpercentile(L, hi, axis=0)


def key(c):
    return "%ds|%s|w%d|%s|%s|%s%d" % (c[0], c[1], c[2], c[3], c[4], c[5][0], c[5][1])


def main():
    src, out, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    paths = {os.path.basename(p)[3:13]: p for p in glob.glob(os.path.join(src, "**", "e2_*.npz"), recursive=True)}
    days = sorted(d for d in paths if d not in SKIP)
    lo, hi = DEV if mode == "dev" else HOLD
    tests = [d for d in days if lo <= d <= hi]
    fin = None
    if mode == "final":
        fin = json.load(open(sys.argv[4]))
        want = {tuple(c["cell"][:5]) + (tuple(c["cell"][5]),) for c in fin}
    lines = []

    def say(*a):
        s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)

    say("copy round 2,", mode, "| launch days", len(days), "| test days", len(tests))
    cells = [(dl, l, w, f, e, fe) for dl in DELAYS for l in LISTS for w in WINS for f in FILTERS for e in EXITS for fe in FEES]
    if fin is not None:
        cells = [c for c in cells if c in want]
    ix = {c: k for k, c in enumerate(cells)}
    S = np.zeros((len(cells), len(tests))); C = np.zeros((len(cells), len(tests))); W = np.zeros((len(cells), len(tests)))
    detail = {c: [] for c in cells} if fin is not None else None
    base = {}
    aggs = {}
    for d in days:
        if d > hi:
            break
        ev = load(paths[d])
        if d in tests:
            ti = tests.index(d)
            L = {}
            for w in WINS:
                win = [x for x in aggs if dnum(d) - (w + GAP - 1) * 86400 <= dnum(x) <= dnum(d) - GAP * 86400]
                L[w] = lists([aggs[x] for x in win])
            for dl in DELAYS:
                r, how, vs, usd = ev["r%d" % dl], ev["how%d" % dl], ev["vs%d" % dl], ev["usd"]
                valid = np.flatnonzero(~np.isnan(r[:, 0]))
                order = valid[np.lexsort((valid, ev["t"][valid]))]
                if fin is not None:                      # the random wallet under the same delay, exit and fee
                    for c in cells:
                        if c[0] == dl:
                            ei = EXITS.index(c[4])
                            p = pnl(r[valid, ei], how[valid, ei], vs[valid], usd[valid], c[5][0], c[5][1])
                            base.setdefault(c, []).append((len(p), float(p.sum())))
                for l in LISTS:
                    for w in WINS:
                        if fin is not None and not any(c[0] == dl and c[1] == l and c[2] == w for c in cells):
                            continue
                        pk = picks(ev, dl, L[w][l, dl], order)
                        for f in FILTERS:
                            idx = pk[f]
                            if not len(idx):
                                continue
                            for ei, e in enumerate(EXITS):
                                for fe in FEES:
                                    c = (dl, l, w, f, e, fe)
                                    if c not in ix:
                                        continue
                                    p = pnl(r[idx, ei], how[idx, ei], vs[idx], usd[idx], fe[0], fe[1])
                                    k = ix[c]
                                    S[k, ti] = p.sum(); C[k, ti] = len(p); W[k, ti] = (p > 0).sum()
                                    if detail is not None:
                                        detail[c] += [(d, int(ev["w"][i]), float(x), int(ev["t"][i]), int(ev["hold"][i]), int(how[i, ei]))
                                                      for i, x in zip(idx.tolist(), p.tolist())]
        aggs[d] = aggregate(ev)
        for old in [x for x in aggs if dnum(x) < dnum(d) - (max(WINS) + GAP) * 86400]:
            del aggs[old]
        print("day", d, len(ev["w"]), "test" if d in tests else "", flush=True)

    rng = np.random.default_rng(SEED)
    n = C.sum(1); T = np.array([c[5][1] for c in cells], np.float64)
    avg = np.where(n > 0, S.sum(1) / np.maximum(n, 1), np.nan)
    with np.errstate(invalid="ignore"):
        dpos = ((S > 0) & (C > 0)).sum(1); dall = (C > 0).sum(1)
    if mode == "dev":
        lo_, hi_ = ci(S, C, rng)
        pct, lop = 100 * avg / T, 100 * lo_ / T
        res = [dict(cell=[c[0], c[1], c[2], c[3], c[4], list(c[5])], key=key(c), n=int(n[k]), avg=round(float(avg[k]), 3) if n[k] else None,
                    pct=round(float(pct[k]), 2) if n[k] else None, lo=round(float(lo_[k]), 3) if n[k] else None,
                    hi=round(float(hi_[k]), 3) if n[k] else None, win=round(float(W[k].sum() / max(n[k], 1) * 100), 1),
                    days_pos="%d/%d" % (dpos[k], dall[k])) for k, c in enumerate(cells)]
        json.dump(res, open(os.path.join(out, "grid_dev.json"), "w"))
        big = n >= 150
        say("cells", len(cells), "| with 150+ trades", int(big.sum()), "| average above 0:", int((big & (avg > 0)).sum()),
            "| interval above 0:", int((big & (lo_ > 0)).sum()))
        row = lambda k: "  %-46s n %6d | per trade %8.2f $ = %6.2f%% | 95%% %7.2f..%7.2f | in profit %4.1f%% | days %s" % (
            res[k]["key"], n[k], avg[k], pct[k], lo_[k], hi_[k], res[k]["win"], res[k]["days_pos"])
        for dl in DELAYS:
            for kind in ("fomo", "jup"):
                m = np.array([c[0] == dl and c[5][0] == kind for c in cells]) & big
                say("\ndelay %d s, %s fee: cells %d, average above 0: %d, interval above 0: %d; best five by interval low (%% of ticket):" % (
                    dl, kind, m.sum(), (m & (avg > 0)).sum(), (m & (lo_ > 0)).sum()))
                for k in sorted(np.flatnonzero(m), key=lambda k: -lop[k])[:5]:
                    say(row(k))
        say("\nby lever: average of the cells' averages in % of the ticket (150+ trades)")
        for name, pos, vals in (("delay", 0, DELAYS), ("list", 1, LISTS), ("window", 2, WINS), ("filter", 3, FILTERS), ("exit", 4, EXITS), ("fee", 5, FEES)):
            say("  " + name + ": " + " | ".join("%s %.2f%%" % (v if pos != 5 else "%s%d" % v, np.mean(pct[big & np.array([c[pos] == v for c in cells])]))
                                              for v in vals if (big & np.array([c[pos] == v for c in cells])).any()))
        # the finalists
        elig = big & np.array([c[0] >= 2 for c in cells])
        qual = [k for k in sorted(np.flatnonzero(elig & (lo_ > 0)), key=lambda k: -lop[k])]
        chosen = []

        def differs(k):
            return all((cells[k][1], cells[k][4]) != (cells[j][1], cells[j][4]) for j in chosen)
        for kind in ("fomo", "jup"):
            for k in qual:
                if cells[k][5][0] == kind and k not in chosen:
                    chosen.append(k); break
        for k in qual:
            if len(chosen) >= 5:
                break
            if k not in chosen and differs(k):
                chosen.append(k)
        nq = len(chosen)
        for k in sorted(np.flatnonzero(elig), key=lambda k: -pct[k]):
            if len(chosen) >= 5:
                break
            if k not in chosen and differs(k):
                chosen.append(k)
        info = [k for k in sorted(np.flatnonzero(big & np.array([c[0] == 1 for c in cells])), key=lambda k: -lop[k])[:2]]
        say("\nfinalists (the first %d qualified; the rest only fill the list):" % nq)
        fl = []
        for j, k in enumerate(chosen + info):
            say(row(k) + ("" if j < nq else "   [did not qualify]" if j < len(chosen) else "   [1 s, information]"))
            fl.append(dict(res[k], qualified=j < nq, info_1s=j >= len(chosen)))
        json.dump(fl, open(os.path.join(out, "finalists.json"), "w"), indent=1)
    else:
        say("hidden days", lo, "to", hi)
        outj = []
        for c0 in fin:
            c = tuple(c0["cell"][:5]) + (tuple(c0["cell"][5]),)
            k = ix[c]; rows = detail[c]; Tk = c[5][1]
            if not rows:
                say("\n" + c0["key"], "no trades"); continue
            v = np.array([x[2] for x in rows]); dd = np.array([tests.index(x[0]) for x in rows])
            lo99, hi99 = ci(S[k:k + 1], C[k:k + 1], rng, 0.5, 99.5)
            lo95, hi95 = ci(S[k:k + 1], C[k:k + 1], rng)
            byw = {}
            for x in rows:
                byw[x[1]] = byw.get(x[1], 0.0) + x[2]
            bw = max(byw, key=byw.get)
            rest = np.array([x[2] for x in rows if x[1] != bw])
            bn = sum(x[0] for x in base[c]); bavg = sum(x[1] for x in base[c]) / bn
            hold = np.array([x[4] for x in rows])
            ok = (len(v) >= 100 and v.mean() > 0 and lo99[0] > 0 and np.delete(v, v.argmax()).mean() > 0 and len(rest) and rest.mean() > 0 and v.mean() > bavg)
            tag = "1 s, information" if c0.get("info_1s") else ("finalist" if c0.get("qualified") else "finalist that did not qualify on dev")
            say("\n%s  [%s]  ->  %s" % (c0["key"], tag, "PASS" if ok else "FAIL"))
            say("  dev: n %d, per trade %.2f $ (%.2f%%), 95%% %s..%s" % (c0["n"], c0["avg"], c0["pct"], c0["lo"], c0["hi"]))
            say("  hidden: n %d, per trade %.2f $ (%.2f%% of %d $), 95%% %.2f..%.2f, 99%% %.2f..%.2f, in profit %.1f%%, days in profit %d/%d" % (
                len(v), v.mean(), 100 * v.mean() / Tk, Tk, lo95[0], hi95[0], lo99[0], hi99[0], 100 * (v > 0).mean(), dpos[k], dall[k]))
            say("  without best trade %.2f (best %.2f) | without best wallet %.2f (its sum %.2f) | wallets %d | random wallet %.2f | median hold of the wallet %s s" % (
                np.delete(v, v.argmax()).mean() if len(v) > 1 else float("nan"), v.max(), rest.mean() if len(rest) else float("nan"), byw[bw], len(byw), bavg,
                int(np.median(hold[hold >= 0])) if (hold >= 0).any() else None))
            say("  per day [n, avg]: " + ", ".join("%s [%d, %.2f]" % (tests[t][5:], C[k, t], S[k, t] / C[k, t]) for t in range(len(tests)) if C[k, t]))
            outj.append(dict(key=c0["key"], tag=tag, verdict="PASS" if ok else "FAIL", n=len(v), avg=float(v.mean()), pct=float(100 * v.mean() / Tk),
                             ci95=[float(lo95[0]), float(hi95[0])], ci99=[float(lo99[0]), float(hi99[0])], base=float(bavg),
                             trades=[[x[0], str(x[1]), round(x[2], 3), x[3], x[4], x[5]] for x in rows]))
        json.dump(outj, open(os.path.join(out, "final.json"), "w"))
    open(os.path.join(out, "report_%s.txt" % ("grid_dev" if mode == "dev" else "final")), "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
