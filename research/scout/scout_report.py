"""The scout study's verdict (research/scout/PREREG-SCOUT-2026-11-11.md). Fake money only.
usage: python3 research/scout/scout_report.py <dir with trades_*.json> <out dir>"""
import glob, json, os, sys
import numpy as np

DEV = ["2026-09-%02d" % d for d in range(24, 31)]
HOLD = ["2026-10-%02d" % d for d in range(1, 8)]
PRIMARY = ["V1", "V2+R", "V3+R"]
BOOT, SEED = 4000, 7
TICKET = 20.0


def boot_by_day(vals, days, rng):
    """95% interval of the mean per trade, resampling days."""
    ud = sorted(set(days))
    if len(ud) < 2:
        return (float("nan"), float("nan"))
    by = {d: np.array([v for v, dd in zip(vals, days) if dd == d]) for d in ud}
    ms = []
    for _ in range(BOOT):
        pick = rng.choice(len(ud), len(ud))
        a = np.concatenate([by[ud[i]] for i in pick])
        ms.append(a.mean())
    return (float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5)))


def stats(rows, key, rng):
    if not rows:
        return dict(n=0)
    v = np.array([r[key] for r in rows]); d = [r["day"] for r in rows]
    by_day = {}
    for x, dd in zip(v, d):
        by_day.setdefault(dd, []).append(x)
    best = int(np.argmax(v))
    paired = [(r[key] - r["ctl"][key], r["day"]) for r in rows if r.get("ctl")]
    out = dict(n=len(v), avg=round(float(v.mean()), 3), ci=[round(x, 3) for x in boot_by_day(list(v), d, rng)],
               in_profit=round(float((v > 0).mean()) * 100, 1), days=len(by_day), days_pos=sum(np.mean(x) > 0 for x in by_day.values()),
               without_best=round(float(np.delete(v, best).mean()), 3) if len(v) > 1 else None,
               best=dict(sym=rows[best]["sym"], mint=rows[best]["mint"], pnl=round(float(v[best]), 2)),
               zero_pct=round(float(np.mean([r["zero"] for r in rows])) * 100, 1),
               how={h: sum(r["how"] == h for r in rows) for h in sorted(set(r["how"] for r in rows))},
               grad_pct=round(float(np.mean([r["grad"] for r in rows])) * 100, 1),
               hold_avg=round(float(np.mean([r[key.replace("pnl", "hold")] for r in rows])), 3),
               per_day={dd: [len(x), round(float(np.mean(x)), 2)] for dd, x in sorted(by_day.items())})
    if by_day:
        worst_day = max(by_day, key=lambda dd: abs(sum(by_day[dd])))
        rest = [x for x, dd in zip(v, d) if dd != worst_day]
        out["without_biggest_day"] = [worst_day, round(float(np.mean(rest)), 3) if rest else None]
    if paired:
        pv = [x for x, _ in paired]; pd_ = [dd for _, dd in paired]
        cv = np.array([r["ctl"][key] for r in rows if r.get("ctl")])
        out["control"] = dict(n=len(cv), avg=round(float(cv.mean()), 3), zero_pct=round(float(np.mean([r["ctl"]["zero"] for r in rows if r.get("ctl")])) * 100, 1))
        out["minus_control"] = dict(avg=round(float(np.mean(pv)), 3), ci=[round(x, 3) for x in boot_by_day(pv, pd_, rng)])
    return out


def verdict(h):
    if h.get("n", 0) < 30:
        return "FAIL (fewer than 30 trades)"
    mc = h.get("minus_control", {}).get("ci", [float("nan")])[0]
    better = mc == mc and mc > 0
    if h["avg"] > 0 and better and (h["without_best"] or 0) > 0:
        return "PASS"
    if better:
        return "PICKS BETTER, STILL LOSES"
    return "FAIL"


def portfolio(rows, fmin=0.50):
    """For information: the video's desk (20 $, 40% of free cash a buy, max 2 open) over the trades in time order,
    using each trade's result per 20 as a multiple of the stake (fees scaled to the stake, minimum fmin per trade)."""
    rows = sorted(rows, key=lambda r: r["entry_t"])
    cash, open_, n = 20.0, [], 0
    for r in rows:
        done = [o for o in open_ if o[0] <= r["entry_t"]]
        for o in done:
            cash += o[1]; open_.remove(o)
        if len(open_) >= 2 or cash < 1.0:
            continue
        stake = 0.4 * cash
        nfee = 3 if r["how"] in ("trail", "2x+end") else 2
        gross = (r["pnl50"] + nfee * 0.50) / TICKET     # the 20 $ trade's result before its fees (each at the 0.50 minimum)
        back = stake * (1 + gross) - nfee * max(0.005 * stake, fmin)
        cash -= stake; open_.append((r["exit"], max(back, 0.0))); n += 1
    cash += sum(o[1] for o in open_)
    return dict(trades=n, end_cash=round(cash, 2))


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rows, meta = [], []
    for f in sorted(glob.glob(os.path.join(src, "**", "trades_*.json"), recursive=True)):
        js = json.load(open(f)); rows += js["rows"]; meta.append(dict(day=js["day"], launches=js["launches"], coins=js["coins"]))
    rng = np.random.default_rng(SEED)
    res = dict(days=meta, cells={})
    lines = ["Scout study, fake money only. Ticket 20 $, FOMO fee 0.5% (min 0.50; pnl81 = min 0.81), 1% slippage a side.", ""]
    for cell in sorted(set(r["cell"] for r in rows)):
        res["cells"][cell] = {}
        for part, days in (("dev", DEV), ("holdout", HOLD)):
            rr = [r for r in rows if r["cell"] == cell and r["day"] in days]
            res["cells"][cell][part] = {k: stats(rr, k, rng) for k in ("pnl50", "pnl81")}
        h = res["cells"][cell]["holdout"]["pnl50"]; dv = res["cells"][cell]["dev"]["pnl50"]
        v = verdict(h) if cell in PRIMARY else "(secondary)"
        res["cells"][cell]["verdict"] = v
        if cell in PRIMARY or cell == "V1+R":
            res["cells"][cell]["portfolio_holdout"] = portfolio([r for r in rows if r["cell"] == cell and r["day"] in HOLD])
        for part, s in (("dev", dv), ("holdout", h)):
            if s.get("n"):
                lines.append("%-8s %-7s n %5d  avg %+6.2f  95%% %+6.2f..%+6.2f  profit %4.1f%%  days+ %d/%d  zero %4.1f%%  w/o best %+6.2f  "
                             "control %+6.2f  minus %+6.2f (%+6.2f..%+6.2f)  hold %+6.2f  %s" % (
                                 cell, part, s["n"], s["avg"], s["ci"][0], s["ci"][1], s["in_profit"], s["days_pos"], s["days"], s["zero_pct"],
                                 s["without_best"] or 0, s.get("control", {}).get("avg", float("nan")),
                                 s.get("minus_control", {}).get("avg", float("nan")), *(s.get("minus_control", {}).get("ci", [float("nan")] * 2)),
                                 s["hold_avg"], s["how"]))
        lines.append("%-8s verdict: %s   pnl81 holdout avg %s" % (cell, v, res["cells"][cell]["holdout"]["pnl81"].get("avg")))
        lines.append("")
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1)
    open(os.path.join(out, "report.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
