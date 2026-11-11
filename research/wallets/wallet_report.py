"""The wallet study's verdict (research/wallets/PREREG-WALLETS-2026-11-11.md). Fake money only.

usage: python3 research/wallets/wallet_report.py <dir with ev_*.npz (any depth)> <out dir> <dev|holdout>
"dev" prints the dev days only; "holdout" prints both. Writes report.txt, result.json and trades.json (the rules' trades).
"""
import calendar, glob, json, os, sys, time
import numpy as np

TICKET = 20.0
WIN_DAYS, GAP, MIN_EV, TOP, TMIN = 21, 3, 10, 300, 2.0
SKIP = {"2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07"}
DEV = ("2026-09-02", "2026-09-19")
HOLD = ("2026-09-20", "2026-10-06")
BOOT, SEED = 4000, 11
HAIRCUT = 0.90


def dstr(s):
    return time.strftime("%Y-%m-%d", time.gmtime(s))


def dnum(d):
    return calendar.timegm(time.strptime(d, "%Y-%m-%d"))


def fee(x):
    return np.where(x < 5, 0.10, np.where(x < 47.5, 0.02 * x, np.where(x < 190, 0.95, 0.005 * x)))


def pnl(r, how, jup=False):
    """Per 20 $ after fees from the ratio exit/entry; a completed curve is sold 10% lower."""
    v = TICKET * r * np.where(how == 3, HAIRCUT, 1.0)
    if jup:
        return v - TICKET - 0.10
    return v - TICKET - fee(np.full_like(v, TICKET)) - fee(v)


def load(path):
    z = np.load(path)
    d = {k: z[k] for k in ("w", "m", "t", "buy_sol", "hold", "own_pnl", "r", "how", "rh", "hh", "desk", "r5", "how5", "mc", "age")}
    ok = ~np.isnan(d["r"])
    d = {k: v[ok] for k, v in d.items()}
    d["n_all"] = int(len(ok)); d["mints"] = z["mints"]
    d["p"] = pnl(d["r"].astype(np.float64), d["how"])
    return d


def aggregate(d):
    """Per wallet of one launch day: events, sum and sum of squares of the copier's result, own wins, own profit."""
    w, inv = np.unique(d["w"], return_inverse=True)
    n = np.bincount(inv).astype(np.float64)
    return dict(w=w, n=n, s=np.bincount(inv, weights=d["p"]), ss=np.bincount(inv, weights=d["p"] ** 2),
                ow=np.bincount(inv, weights=(d["own_pnl"] > 0).astype(np.float64)), op=np.bincount(inv, weights=d["own_pnl"].astype(np.float64)))


def lists(aggs):
    """W1 and W2 from the aggregates of the window's launch days. Returns (W1 hashes, W2 hashes, per-wallet table)."""
    w = np.concatenate([a["w"] for a in aggs])
    uw, inv = np.unique(w, return_inverse=True)
    col = lambda k: np.bincount(inv, weights=np.concatenate([a[k] for a in aggs]), minlength=len(uw))
    n, s, ss, ow, op = col("n"), col("s"), col("ss"), col("ow"), col("op")
    enough = n >= MIN_EV
    c1 = np.flatnonzero(enough & (ow / np.maximum(n, 1) >= 0.5))
    w1 = c1[np.argsort(-op[c1], kind="stable")[:TOP]]
    mean = s / np.maximum(n, 1)
    var = np.maximum(ss / np.maximum(n, 1) - mean ** 2, 0) * n / np.maximum(n - 1, 1)
    tval = np.where(var > 0, mean / np.sqrt(np.maximum(var, 1e-30) / np.maximum(n, 1)), 0.0)
    c2 = np.flatnonzero(enough & (mean > 0) & (tval >= TMIN))
    w2 = c2[np.argsort(-tval[c2], kind="stable")[:TOP]]
    info = dict(wallets=int(len(uw)), enough=int(enough.sum()), w1_pool=int(len(c1)), w2_pool=int(len(c2)),
                w1_mean_copy=float(mean[w1].mean()) if len(w1) else None, w2_mean_copy=float(mean[w2].mean()) if len(w2) else None,
                w1_events=float(n[w1].sum()), w2_events=float(n[w2].sum()))
    return uw[w1], uw[w2], info, dict(zip(uw[w2].tolist(), mean[w2].tolist())), dict(zip(uw[w1].tolist(), mean[w1].tolist()))


def pick(d, order, wl, second=False):
    """Indices of the rule's trades: per coin the first event of a listed wallet (second=True: of the second listed wallet)."""
    hit = order[np.isin(d["w"][order], wl)]
    if not second:
        _, first = np.unique(d["m"][hit], return_index=True)
        return hit[np.sort(first)]
    out, seen = [], {}
    for i in hit.tolist():
        m, w = int(d["m"][i]), int(d["w"][i])
        s = seen.setdefault(m, [w, False])
        if not s[1] and w != s[0]:
            s[1] = True; out.append(i)
    return np.array(out, np.int64)


def boot(vals, days, rng):
    ud = sorted(set(days))
    if len(ud) < 2 or not len(vals):
        return [None, None]
    days = np.array(days); vals = np.array(vals, np.float64)
    sums = np.array([vals[days == d].sum() for d in ud]); cnt = np.array([(days == d).sum() for d in ud], np.float64)
    k = rng.integers(0, len(ud), (BOOT, len(ud)))
    ms = sums[k].sum(1) / cnt[k].sum(1)
    return [round(float(np.percentile(ms, 2.5)), 3), round(float(np.percentile(ms, 97.5)), 3)]


def stats(rows, rng):
    if not rows:
        return dict(n=0)
    g = lambda k: np.array([r[k] for r in rows], np.float64)
    v, days = g("p"), [r["day"] for r in rows]
    ud = sorted(set(days))
    per_day = {d: [int(sum(x == d for x in days)), round(float(np.mean([a for a, x in zip(v, days) if x == d])), 2)] for d in ud}
    best = int(np.argmax(v))
    by_w = {}
    for r in rows:
        by_w.setdefault(r["w"], []).append(r["p"])
    top_w = max(by_w, key=lambda w: sum(by_w[w]))
    rest = [r["p"] for r in rows if r["w"] != top_w]
    active = sorted(by_w, key=lambda w: -len(by_w[w]))[:5]
    how = g("how")
    cut = lambda mask: [int(mask.sum()), round(float(v[mask].mean()), 2) if mask.any() else None]
    mc, age, hold = g("mc"), g("age"), g("hold")
    diff = v - g("base")
    return dict(
        n=len(v), avg=round(float(v.mean()), 3), ci=boot(v, days, rng), median=round(float(np.median(v)), 2),
        in_profit=round(float((v > 0).mean()) * 100, 1), days=len(ud), days_pos=int(sum(x[1] > 0 for x in per_day.values())),
        per_day=per_day, without_best=round(float(np.delete(v, best).mean()), 3) if len(v) > 1 else None, best=round(float(v[best]), 2),
        without_best_wallet=round(float(np.mean(rest)), 3) if rest else None, best_wallet=[top_w, len(by_w[top_w]), round(float(sum(by_w[top_w])), 2)],
        wallets=len(by_w), top5_active=[[w, len(by_w[w]), round(float(np.mean(by_w[w])), 2)] for w in active],
        base_avg=round(float(g("base").mean()), 3), minus_base=round(float(diff.mean()), 3), minus_base_ci=boot(diff, days, rng),
        same_coin_avg=round(float(g("coin").mean()), 3),
        how={k: round(float((how == c).mean()) * 100, 1) for k, c in (("wallet_sold", 0), ("time_or_end", 1), ("dead", 2), ("graduated", 3), ("ten_x", 4))},
        hold_median_s=round(float(np.median(hold[hold >= 0])), 0) if (hold >= 0).any() else None,
        sold_within_30s=round(float(((hold >= 0) & (hold < 30)).mean()) * 100, 1),
        mc_cut={"under_10k": cut(mc < 10e3), "10k_30k": cut((mc >= 10e3) & (mc < 30e3)), "over_30k": cut(mc >= 30e3)},
        age_cut={"under_2min": cut(age < 120), "2_15min": cut((age >= 120) & (age < 900)), "older": cut(age >= 900)},
        desk=round(float(g("desk").mean()), 3), hold24=round(float(g("ph").mean()), 3), delay5=round(float(np.nanmean(g("p5"))), 3),
        jupiter=round(float(g("pj").mean()), 3), jupiter_ci=boot(g("pj"), days, rng))


def verdict(s):
    if s.get("n", 0) < 30:
        return "FAIL (under 30 trades)"
    ok = (s["avg"] > 0 and s["ci"][0] is not None and s["ci"][0] > 0 and s["minus_base_ci"][0] is not None and s["minus_base_ci"][0] > 0
          and (s["without_best"] or -1) > 0 and (s["without_best_wallet"] or -1) > 0)
    if ok:
        return "PASS"
    if s["minus_base_ci"][0] is not None and s["minus_base_ci"][0] > 0 and s["avg"] <= 0:
        return "picks better, still loses"
    return "FAIL"


def main():
    src, out, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    assert mode in ("dev", "holdout")
    os.makedirs(out, exist_ok=True)
    paths = {os.path.basename(p)[3:13]: p for p in glob.glob(os.path.join(src, "**", "ev_*.npz"), recursive=True)}
    days = sorted(d for d in paths if d not in SKIP)
    last = DEV[1] if mode == "dev" else HOLD[1]
    lines = []

    def say(*a):
        s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)

    say("wallet study,", mode, "run; launch days with data:", len(paths), "used:", len(days), "missing or skipped:",
        sorted(set(dstr(s) for s in range(dnum("2026-08-10"), dnum("2026-10-07"), 86400)) - set(days)))
    aggs, cover = {}, {}
    tests = [d for d in days if DEV[0] <= d <= last]
    rows = {"W1": [], "W2": [], "W3": []}
    listinfo, w2_by_day, persist = {}, {}, {"W1": [], "W2": []}
    base_day = {}
    for d in days:
        if d > last:
            break
        ev = load(paths[d])
        cover[d] = [ev["n_all"], int(len(ev["p"]))]
        if d in tests:
            win = [x for x in days if dnum(d) - (WIN_DAYS + GAP - 1) * 86400 <= dnum(x) <= dnum(d) - GAP * 86400]
            w1, w2, info, w2mean, w1mean = lists([aggs[x] for x in win])
            info["window_days"] = len(win); listinfo[d] = info; w2_by_day[d] = set(w2.tolist())
            order = np.lexsort((np.arange(len(ev["t"])), ev["t"]))
            base = float(ev["p"].mean()); base_day[d] = [int(len(ev["p"])), round(base, 3), round(float((ev["p"] > 0).mean()) * 100, 1)]
            cm_n = np.bincount(ev["m"]).astype(np.float64); cm_s = np.bincount(ev["m"], weights=ev["p"])
            p5 = pnl(ev["r5"].astype(np.float64), ev["how5"]); ph = pnl(ev["rh"].astype(np.float64), ev["hh"]); pj = pnl(ev["r"].astype(np.float64), ev["how"], jup=True)
            for name, wl, second in (("W1", w1, False), ("W2", w2, False), ("W3", w2, True)):
                for i in pick(ev, order, wl, second).tolist():
                    m = int(ev["m"][i])
                    rows[name].append(dict(day=d, w=int(ev["w"][i]), mint=ev["mints"][m].decode(), t=int(ev["t"][i]), p=float(ev["p"][i]),
                                           how=int(ev["how"][i]), hold=int(ev["hold"][i]), mc=float(ev["mc"][i]), age=int(ev["age"][i]),
                                           desk=float(ev["desk"][i]), ph=float(ph[i]), p5=float(p5[i]), pj=float(pj[i]), base=base,
                                           coin=float(cm_s[m] / cm_n[m]), buy_sol=float(ev["buy_sol"][i])))
            # how much of the record lasts: the listed wallets' average in the window against all their events of the test day
            for name, wl, wm in (("W1", w1, w1mean), ("W2", w2, w2mean)):
                hit = np.isin(ev["w"], wl)
                if hit.any():
                    persist[name].append((d, float(np.mean(list(wm.values()))), float(ev["p"][hit].mean()), int(hit.sum())))
        aggs[d] = aggregate(ev)
        for old in [x for x in aggs if dnum(x) < dnum(d) - (WIN_DAYS + GAP) * 86400]:
            del aggs[old]
        del ev
        print("day", d, cover[d], "test" if d in tests else "", flush=True)

    rng = np.random.default_rng(SEED)
    res = dict(mode=mode, cover=cover, base_day=base_day, lists=listinfo, cells={})
    parts = [("dev", DEV)] + ([("holdout", HOLD)] if mode == "holdout" else [])
    for part, (lo, hi) in parts:
        say("\n==", part, lo, "to", hi, "==")
        bd = [base_day[d] for d in base_day if lo <= d <= hi]
        if bd:
            tot = sum(b[0] for b in bd)
            say("random wallet (every event): events", tot, "per 20 $", round(sum(b[0] * b[1] for b in bd) / tot, 3),
                "in profit %", round(sum(b[0] * b[2] for b in bd) / tot, 1))
        for name in ("W1", "W2", "W3"):
            s = stats([r for r in rows[name] if lo <= r["day"] <= hi], rng)
            s["verdict"] = verdict(s)
            res["cells"]["%s_%s" % (name, part)] = s
            if not s["n"]:
                say(name, "no trades"); continue
            say("\n%s: %s" % (name, s["verdict"]))
            say("  trades", s["n"], "| per 20 $", s["avg"], "95%", s["ci"], "| median", s["median"], "| in profit %", s["in_profit"],
                "| days in profit", "%d/%d" % (s["days_pos"], s["days"]))
            say("  random wallet same days", s["base_avg"], "| rule minus it", s["minus_base"], "95%", s["minus_base_ci"],
                "| other wallets in the same coins", s["same_coin_avg"])
            say("  without best trade", s["without_best"], "(best %s)" % s["best"], "| without best wallet", s["without_best_wallet"],
                "(%d trades, sum %s)" % (s["best_wallet"][1], s["best_wallet"][2]), "| wallets", s["wallets"])
            say("  exits %", s["how"], "| wallet's hold median s", s["hold_median_s"], "| sold within 30 s %", s["sold_within_30s"])
            say("  by market cap [n, avg]", s["mc_cut"], "| by coin age", s["age_cut"])
            say("  information: desk exits", s["desk"], "| held 24 h / graduation", s["hold24"], "| 5 s delay", s["delay5"],
                "| Jupiter-like fee", s["jupiter"], "95%", s["jupiter_ci"])
            say("  5 most active wallets [hash, trades, avg]", s["top5_active"])
            say("  per day [n, avg]", s["per_day"])
        for name in ("W1", "W2"):
            pp = [x for x in persist[name] if lo <= x[0] <= hi]
            if pp:
                say("%s record: copier average in the list window %.2f -> the same wallets on the test day %.2f (%d events)" % (
                    name, np.mean([x[1] for x in pp]), sum(x[2] * x[3] for x in pp) / sum(x[3] for x in pp), sum(x[3] for x in pp)))
        st = [len(w2_by_day[d] & w2_by_day[d2]) / max(len(w2_by_day[d]), 1) for d in w2_by_day for d2 in w2_by_day
              if lo <= d <= hi and dnum(d2) == dnum(d) + 7 * 86400]
        if st:
            say("W2 wallets still on the list 7 days later: %.0f%%" % (100 * float(np.mean(st))))
        li = [listinfo[d] for d in listinfo if lo <= d <= hi]
        if li:
            say("lists per day (average): wallets seen", int(np.mean([x["wallets"] for x in li])), "with 10+ events", int(np.mean([x["enough"] for x in li])),
                "W1 pool", int(np.mean([x["w1_pool"] for x in li])), "W2 pool", int(np.mean([x["w2_pool"] for x in li])))
    keep = [r for n in rows for r in rows[n]]
    json.dump(res, open(os.path.join(out, "result_%s.json" % mode), "w"), indent=1)
    json.dump({n: [dict(r, w=str(r["w"])) for r in rows[n]] for n in rows}, open(os.path.join(out, "trades_%s.json" % mode), "w"))
    open(os.path.join(out, "report_%s.txt" % mode), "w").write("\n".join(lines) + "\n")
    print("rows", len(keep))


if __name__ == "__main__":
    main()
