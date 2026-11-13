"""Copy trading round 3 (research/wallets/PREREG-COPY2-2026-11-13.md, "Round 3"): after the graduation, on the stored wallet
pairs (branch "wallets"). Fake money only. usage: python3 -I research/wallets/copy3_check.py <dir with pairs_*.parquet> <out.txt>"""
import calendar, glob, os, sys, time
import numpy as np
import pyarrow.parquet as pq

DAY = 86400_000
DEV = ("2026-09-02", "2026-09-19"); HOLD = ("2026-09-20", "2026-10-06")
SLIP, T, BOOT, SEED = 0.01, 20.0, 4000, 17


def dnum(d):
    return calendar.timegm(time.strptime(d, "%Y-%m-%d")) * 1000


def fee(x):
    return np.where(x < 5, 0.10, np.where(x < 47.5, 0.02 * x, np.where(x < 190, 0.95, 0.005 * x)))


def pnl(mult, kind):
    v = T * mult * (1 - SLIP) / (1 + SLIP)
    return v - T - (0.10 if kind == "jup" else fee(np.full_like(v, T)) + fee(v))


def boot(v, d, rng, lo=2.5, hi=97.5):
    ud = np.unique(d)
    s = np.array([v[d == x].sum() for x in ud]); c = np.array([(d == x).sum() for x in ud], float)
    k = rng.integers(0, len(ud), (BOOT, len(ud)))
    m = s[k].sum(1) / c[k].sum(1)
    return float(np.percentile(m, lo)), float(np.percentile(m, hi))


def main():
    src, out = sys.argv[1], sys.argv[2]
    cols = ["t_q", "wid", "coin", "h1", "a1", "b1", "h5", "a5", "b5"]
    parts = [pq.read_table(f, columns=cols) for f in sorted(glob.glob(os.path.join(src, "pairs_*.parquet")))]
    d = {c: np.concatenate([p.column(c).to_numpy(zero_copy_only=False) for p in parts]) for c in cols}
    del parts
    ok = ~np.isnan(d["t_q"].astype(float)) if d["t_q"].dtype.kind == "f" else np.ones(len(d["t_q"]), bool)
    d = {c: v[ok] for c, v in d.items()}
    t = d["t_q"].astype(np.int64); order = np.argsort(t, kind="stable")
    d = {c: v[order] for c, v in d.items()}; t = t[order]
    day = t // DAY
    lines = []

    def say(*a):
        s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)
    say("pairs with a qualifying buy:", len(t), "wallets", len(np.unique(d["wid"])), "coins", len(np.unique(d["coin"])))
    rng = np.random.default_rng(SEED)
    nw = int(d["wid"].max()) + 1
    cells = {}
    days = [x for x in range(dnum(DEV[0]) // DAY, dnum(HOLD[1]) // DAY + 1)]
    for dl in (1, 5):
        for ex in ("h", "a", "b"):
            mult = d["%s%d" % (ex, dl)].astype(np.float64)
            x = mult * (1 - SLIP) / (1 + SLIP) - 1
            has = ~np.isnan(x)
            for dd in days:
                lo = np.searchsorted(t, (dd - 22) * DAY); hi = np.searchsorted(t, (dd - 1) * DAY)     # 21 days, one day lag
                a, b = np.searchsorted(t, dd * DAY), np.searchsorted(t, (dd + 1) * DAY)
                w = d["wid"][lo:hi][has[lo:hi]]; xv = x[lo:hi][has[lo:hi]]
                n = np.bincount(w, minlength=nw).astype(float); s = np.bincount(w, weights=xv, minlength=nw); ss = np.bincount(w, weights=xv * xv, minlength=nw)
                mean = s / np.maximum(n, 1); var = np.maximum(ss / np.maximum(n, 1) - mean ** 2, 0) * n / np.maximum(n - 1, 1)
                tv = np.where(var > 0, mean / np.sqrt(np.maximum(var, 1e-30) / np.maximum(n, 1)), 0)
                top = lambda m, k: np.flatnonzero(m)[np.argsort(-tv[m], kind="stable")[:k]]
                L = {"S1": top((n >= 10) & (mean > 0) & (tv >= 2), 300), "S2": top((n >= 20) & (mean > 0) & (tv >= 3), 100)}
                idx = np.arange(a, b)[has[a:b]]
                for kind in ("fomo", "jup"):
                    p_all = pnl(mult[idx], kind)
                    cells.setdefault(("base", dl, ex, "all", kind), []).append((dd, p_all, d["wid"][idx]))
                    for ln, wl in L.items():
                        hit = idx[np.isin(d["wid"][idx], wl)]
                        _, f = np.unique(d["coin"][hit], return_index=True)
                        one = hit[np.sort(f)]
                        two, seen = [], {}
                        for i in hit.tolist():
                            s2 = seen.setdefault(int(d["coin"][i]), [int(d["wid"][i]), False])
                            if not s2[1] and int(d["wid"][i]) != s2[0]:
                                s2[1] = True; two.append(i)
                        for fn, sel in (("all", one), ("two", np.array(two, np.int64))):
                            cells.setdefault((ln, dl, ex, fn, kind), []).append((dd, pnl(mult[sel], kind), d["wid"][sel]))
    d0, d1, h0, h1 = (dnum(x) // DAY for x in DEV + HOLD)

    def part(c, lo, hi):
        rows = [r for r in cells[c] if lo <= r[0] <= hi and len(r[1])]
        if not rows:
            return None
        v = np.concatenate([r[1] for r in rows]); dd = np.concatenate([np.full(len(r[1]), r[0]) for r in rows]); w = np.concatenate([r[2] for r in rows])
        return v, dd, w
    say("\n== dev days (per 20 $ ticket) ==")
    dev = []
    for c in sorted(cells):
        r = part(c, d0, d1)
        if r is None:
            continue
        v, dd, w = r
        lo, hi = boot(v, dd, rng) if c[0] != "base" else (float("nan"), float("nan"))
        say("  %-4s %d min exit %s %-3s %-4s n %7d avg %6.2f 95%% %6.2f..%6.2f in profit %4.1f%%" % (c + (len(v), v.mean(), lo, hi, 100 * (v > 0).mean())))
        if c[0] != "base" and len(v) >= 100:
            dev.append((lo, c))
    fin = [c for _, c in sorted(dev, reverse=True)[:3]]
    say("\n== hidden days: the three dev-best cells ==")
    for c in fin:
        v, dd, w = part(c, h0, h1)
        l95 = boot(v, dd, rng); l99 = boot(v, dd, rng, 0.5, 99.5)
        bw = {}
        for x, y in zip(w.tolist(), v.tolist()):
            bw[x] = bw.get(x, 0) + y
        top = max(bw, key=bw.get)
        base = part(("base", c[1], c[2], "all", c[4]), h0, h1)[0].mean()
        ok = len(v) >= 100 and v.mean() > 0 and l99[0] > 0 and np.delete(v, v.argmax()).mean() > 0 and v[w != top].mean() > 0 and v.mean() > base
        dvv = part(c, d0, d1)[0]
        say("  %-4s %d min exit %s %-3s %-4s -> %s | dev n %d avg %.2f | hidden n %d avg %.2f 95%% %.2f..%.2f 99%% %.2f..%.2f in profit %.1f%% | "
            "without best trade %.2f, without best wallet %.2f | random wallet %.2f | days in profit %d/%d" % (
                c + ("PASS" if ok else "FAIL", len(dvv), dvv.mean(), len(v), v.mean(), l95[0], l95[1], l99[0], l99[1], 100 * (v > 0).mean(),
                     np.delete(v, v.argmax()).mean(), v[w != top].mean(), base,
                     sum(v[dd == x].mean() > 0 for x in np.unique(dd)), len(np.unique(dd)))))
    open(out, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
