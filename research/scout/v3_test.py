"""Video 3 test (research/scout/PREREG-V3-2026-11-11.md). Fake money only.
usage: python3 research/scout/v3_test.py <history2 dir> <bars dir> <out dir>"""
import glob, json, os, sys
import numpy as np, pandas as pd

H, MIN = 3_600_000, 60_000
SPLIT = 1789430400000                      # 2026-09-15 00:00 UTC
END = 1791331200000                        # 2026-10-07 00:00 UTC
SLIP, HOLD_MS = 0.01, 12 * H
STOPS, ARMS, TRAILS = (0.06, 0.10, 0.20, 0.30), (0.15, 0.30, 1.00), (0.10, 0.20)
VAR = [(s, a, t) for s in STOPS for a in ARMS for t in TRAILS]
VS, VA, VT = (np.array([v[i] for v in VAR]) for i in range(3))
BASE = VAR.index((0.06, 0.15, 0.10))
FEE = {"fomo20": lambda g: 20 * g - 20 - 0.4 - 0.02 * 20 * g, "fomo200": lambda g: 20 * g - 20 - 0.1 - 0.005 * 20 * g,
       "jup": lambda g: 20 * g - 20 - 0.1}
BOOT = 3000


def sim(m, o, c, hi, lo, t0):
    """All 24 exits in one pass. Returns (gross multiples, hold multiple, exit minute of each) or None."""
    i0 = int(np.searchsorted(m, t0, side="left"))
    while i0 < len(m) and not (o[i0] == o[i0]):
        i0 += 1
    if i0 >= len(m) or m[i0] > t0 + 10 * MIN:
        return None
    entry = o[i0] * (1 + SLIP)
    n = len(VAR)
    out = np.full(n, np.nan); xt = np.zeros(n, dtype="int64"); high = np.zeros(n); live = np.ones(n, dtype=bool)
    last, tlast = c[i0], m[i0]
    for j in range(i0, len(m)):
        if m[j] > t0 + HOLD_MS:
            break
        if not (c[j] == c[j]):
            continue
        last, tlast = c[j], m[j]
        l, h_, cl = lo[j] / entry, hi[j] / entry, c[j] / entry
        if j == i0:
            l = min(o[j], c[j]) / entry          # our fill is this bar's open: only what follows counts roughly
        st = live & (high == 0) & (l <= 1 - VS)
        if st.any():
            out[st] = np.minimum(1 - VS[st], cl); xt[st] = m[j]; live &= ~st
        tr = live & (high > 0) & (l <= high * (1 - VT))
        if tr.any():
            out[tr] = np.minimum(high[tr] * (1 - VT[tr]), cl); xt[tr] = m[j]; live &= ~tr
        arm = live & (h_ >= 1 + VA)
        high[arm] = np.maximum(high[arm], h_)
        if not live.any():
            break
    out[live] = last / entry; xt[live] = tlast
    return out * (1 - SLIP), last / entry * (1 - SLIP), xt


def ci(vals, days, rng):
    ud = sorted(set(days))
    by = {d: np.array([v for v, x in zip(vals, days) if x == d]) for d in ud}
    ms = [np.concatenate([by[ud[i]] for i in rng.choice(len(ud), len(ud))]).mean() for _ in range(BOOT)]
    return [round(float(x), 3) for x in np.percentile(ms, [2.5, 97.5])]


def main():
    h2, bdir, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    cols = ["pool", "mint", "symbol", "ts", "age_h", "market_cap_usd", "volume_1h", "price_change_1h", "gap_pre"]
    d = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(os.path.join(h2, "hourly", "*.parquet")))], ignore_index=True)
    d = d[(d.age_h >= 4) & (d.age_h <= 40) & (d.market_cap_usd >= 150e3) & (d.market_cap_usd <= 2.4e6) & (d.volume_1h > 0) & ~d.gap_pre]
    d["b"] = d.ts // H * H + H                                   # entry time: the end of the row's clock hour
    d = d[d.b < END].sort_values(["b", "volume_1h"], ascending=[True, False])
    d["rank"] = d.groupby("b").cumcount() + 1
    d["prank"] = d.groupby("b")["price_change_1h"].rank(ascending=False, method="first")
    rng = np.random.default_rng(3)
    d["rnd"] = False
    for b, idx in d.groupby("b").indices.items():
        pick = rng.choice(idx, min(3, len(idx)), replace=False)
        d.iloc[pick, d.columns.get_loc("rnd")] = True
    print("band rows", len(d), "hours", d.b.nunique(), "median band coins per hour", d.groupby("b").size().median())
    cand = d[(d["rank"] <= 10) | (d.prank <= 3) | d.rnd].copy()
    pools = set(cand.pool)
    bars = {}
    for f in sorted(glob.glob(os.path.join(bdir, "**", "bars_*.parquet"), recursive=True)):
        b = pd.read_parquet(f, columns=["pool", "m", "p_open", "p_close", "p_hi", "p_lo"])
        b = b[b.pool.isin(pools)]
        for p, g in b.groupby("pool", sort=False):
            bars.setdefault(p, []).append(g)
    print("pools with bars", len(bars), "of", len(pools))
    for p in bars:
        g = pd.concat(bars[p]).sort_values("m")
        bars[p] = tuple(g[c].to_numpy(dtype="float64" if c != "m" else "int64") for c in ("m", "p_open", "p_close", "p_hi", "p_lo"))
    rows = []
    for r in cand.itertuples(index=False):
        if r.pool not in bars:
            continue
        s = sim(*bars[r.pool], int(r.b))
        if s is None:
            continue
        rows.append(dict(b=int(r.b), day=pd.Timestamp(r.b, unit="ms").strftime("%Y-%m-%d"), mint=r.mint, sym=r.symbol, rank=int(r.rank),
                         prank=int(r.prank), rnd=bool(r.rnd), up=bool(r.price_change_1h > 0), mc=round(float(r.market_cap_usd)),
                         age=float(r.age_h), g=[round(float(x), 4) for x in s[0]], hold=round(float(s[1]), 4), xt=int(s[2][BASE])))
    print("simulated", len(rows), "of", len(cand))
    T = pd.DataFrame(rows)
    G = np.array(T.g.tolist())
    T["hold_b"] = T.b >= SPLIT
    firstup = T[(T["rank"] <= 10) & T.up].sort_values(["b", "rank"]).groupby("b").head(1).index
    SEL = {"P": T.index.isin(firstup), "L": (T["rank"] <= 10).to_numpy(), "L_up": ((T["rank"] <= 10) & T.up).to_numpy(),
           "top3": (T["rank"] <= 3).to_numpy(), "mover3": (T.prank <= 3).to_numpy(), "C": T.rnd.to_numpy()}
    rng = np.random.default_rng(5)

    def stat(mask, vi, fee, full=False):
        g = G[mask, vi]; v = FEE[fee](g); days = T.day[mask].tolist()
        if len(v) == 0:
            return dict(n=0)
        s = dict(n=int(len(v)), avg=round(float(v.mean()), 3))
        if full:
            dm = pd.Series(v).groupby(days).mean()
            s.update(ci=ci(v, days, rng), days_pos="%d/%d" % ((dm > 0).sum(), len(dm)), in_profit=round(float((v > 0).mean()) * 100, 1),
                     without_top3=round(float(np.sort(v)[:-3].mean()), 3) if len(v) > 3 else None, median=round(float(np.median(v)), 2),
                     hold_avg=round(float(FEE[fee](T.hold[mask].to_numpy()).mean()), 3),
                     one_per_coin=round(float(pd.Series(v, index=T.mint[mask].to_numpy()).groupby(level=0).first().mean()), 3))
        return s

    dev, hol = ~T.hold_b.to_numpy(), T.hold_b.to_numpy()
    res = dict(variants=VAR, grid_dev={}, cells={})
    best = None
    for sn, sm in SEL.items():
        if sn == "C":
            continue
        for vi in range(len(VAR)):
            s = {f: stat(sm & dev, vi, f) for f in FEE}
            res["grid_dev"]["%s|%s" % (sn, VAR[vi])] = s
            if s["jup"]["n"] >= int(os.environ.get("V3_MIN_N", "200")) and (best is None or s["jup"]["avg"] > best[0]):
                best = (s["jup"]["avg"], sn, vi)
    res["best_dev"] = dict(sel=best[1], exit=VAR[best[2]], dev_jup_avg=best[0])
    lines = ["Video 3 test, fake money. Per 20 $ ticket. Exits (stop, trail armed at, trail).",
             "best dev variation (of 120, Jupiter fees): %s %s dev avg %+.3f" % (best[1], VAR[best[2]], best[0]), ""]

    def vs_control(mask, vi, fee):
        a = pd.Series(FEE[fee](G[mask & hol, vi])).groupby(T.day[mask & hol].tolist()).mean()
        c = pd.Series(FEE[fee](G[SEL["C"] & hol, vi])).groupby(T.day[SEL["C"] & hol].tolist()).mean()
        dd = (a - c).dropna().to_numpy()
        bs = [dd[rng.choice(len(dd), len(dd))].mean() for _ in range(BOOT)]
        return dict(avg=round(float(dd.mean()), 3), ci=[round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])])

    for name, sn, vi in (("P", "P", BASE), ("L", "L", BASE), ("C", "C", BASE), ("B", best[1], best[2]), ("C_for_B", "C", best[2])):
        cell = {}
        for part, pm in (("dev", dev), ("holdout", hol)):
            cell[part] = {f: stat(SEL[sn] & pm, vi, f, full=True) for f in FEE}
        if name in ("P", "L", "B"):
            cell["minus_control_holdout"] = {f: vs_control(SEL[sn], vi, f) for f in FEE}
        hh = cell["holdout"]["fomo20"]
        if name in ("P", "B"):
            ok = hh["n"] >= 100 and hh["avg"] > 0 and hh["ci"][0] > 0 and (hh["without_top3"] or 0) > 0 and cell["minus_control_holdout"]["fomo20"]["ci"][0] > 0
            cell["verdict"] = "PASS" if ok else "FAIL"
        stopped = float((G[SEL[sn] & hol, vi] <= (1 - VAR[vi][0]) * (1 - SLIP) + 1e-9).mean()) if (SEL[sn] & hol).any() else None
        cell["stopped_share_holdout"] = stopped
        res["cells"][name] = cell
        lines.append("%s = %s %s   %s" % (name, sn, VAR[vi], cell.get("verdict", "")))
        for part in ("dev", "holdout"):
            for f in FEE:
                s = cell[part][f]
                if s["n"]:
                    lines.append("  %-7s %-7s n %5d avg %+6.2f 95%% %s days+ %s profit %4.1f%% w/o top3 %+6.2f median %+5.2f hold %+6.2f 1/coin %+6.2f" % (
                        part, f, s["n"], s["avg"], s["ci"], s["days_pos"], s["in_profit"], s["without_top3"] or 0, s["median"], s["hold_avg"], s["one_per_coin"]))
        if "minus_control_holdout" in cell:
            lines.append("  minus control (holdout): %s" % cell["minus_control_holdout"])
        lines.append("  stopped share holdout: %s" % stopped); lines.append("")

    # the one-coin desk over the holdout: 20 $, 90% of the cash, next pick when flat; FOMO tiers by the real stake
    def ffee(x):
        return 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x
    for name, sn, vi in (("P", "P", BASE), ("B", best[1], best[2])):
        for feename in ("fomo", "jup"):
            cash, free_at, n = 20.0, 0, 0
            for i in T[SEL[sn] & hol].sort_values(["b", "rank"]).index:
                if T.b[i] < free_at or cash < 1:
                    continue
                stake = 0.9 * cash; back = stake * G[i, vi]
                cost = (ffee(stake) + ffee(back)) if feename == "fomo" else 0.10
                cash += back - stake - cost; n += 1
                xt = rows[i]["xt"] if vi == BASE else T.b[i] + HOLD_MS
                free_at = xt + MIN
            res["cells"][name]["desk_%s" % feename] = dict(trades=n, end_cash=round(cash, 2))
            lines.append("desk %s %s: 20 $ -> %.2f $ in %d trades (holdout, 22 days)%s" % (
                name, feename, cash, n, "" if vi == BASE else " (B: next buy only after the 12 h window, a lower bound on trades)"))
    lines += ["", "top dev grid rows (Jupiter fees):"]
    top = sorted(res["grid_dev"].items(), key=lambda kv: -(kv[1]["jup"].get("avg") or -99))[:8]
    for k, s in top:
        lines.append("  %-34s n %5d jup %+6.2f fomo200 %+6.2f fomo20 %+6.2f" % (k, s["jup"]["n"], s["jup"]["avg"], s["fomo200"]["avg"], s["fomo20"]["avg"]))
    worst = sorted(res["grid_dev"].items(), key=lambda kv: (kv[1]["jup"].get("avg") or 99))[:2]
    for k, s in worst:
        lines.append("  worst %-28s n %5d jup %+6.2f" % (k, s["jup"]["n"], s["jup"]["avg"]))
    pos = sum(1 for s in res["grid_dev"].values() if (s["jup"].get("avg") or -1) > 0)
    lines.append("dev grid rows above 0 with Jupiter fees: %d of %d; with FOMO 20 $: %d" % (
        pos, len(res["grid_dev"]), sum(1 for s in res["grid_dev"].values() if (s["fomo20"].get("avg") or -1) > 0)))
    json.dump(res, open(os.path.join(out, "v3_result.json"), "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    open(os.path.join(out, "v3_report.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
