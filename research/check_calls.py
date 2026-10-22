"""The call channel of the third video (fake money only; research/PREREG-CALLS-2026-10-22.md): every pump.fun graduation called
2, 5 or 10 minutes after it ($20k-$90k market cap), bought at the call or on a 5% dip, sold by the channel's quick-trade plan
(1/2 at +30%, the rest at 1.6x / 1.4x, or all at +30%; -30% stop; 6 h), from the one-minute bars of branch chartbars.
usage: python3 research/check_calls.py <scratch with h2/ (history2), cb/ (chartbars), mk/ (marketctx)>
       -> <scratch>/calls_rows.pkl and research/calls/calls-check-2026-10-22.json"""
import datetime as dt, glob, json, multiprocessing as mp, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "winlose"))
import memebot as M
import filter_search as FS
from features import dense

S = sys.argv[1]
utc = lambda *a: int(dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp() * 1000)
T0, T_END, LATE = utc(2026, 8, 10), utc(2026, 10, 7, 20), utc(2026, 9, 25)
DAY, WEEK, MIN = 86_400_000, 7 * 86_400_000, 60_000
CALLS = (2, 5, 10)
MC_LO, MC_HI = 20_000, 90_000
DIP, DIP_WAIT = 0.95, 30
PATH, STOP, INFO = 360, 0.70, 1440
EXITS = {"X1": ((0.5, 1.30), (0.5, 1.60)), "X2": ((0.5, 1.30), (0.5, 1.40)), "X3": ((1.0, 1.30),), "A": ((1.0, 11.0),)}
FILLS = {"std": (False, False), "stopLevel": (True, False), "targetFirst": (False, True)}
WIN = max(CALLS) + DIP_WAIT + PATH + 1          # minutes after the graduation that must be free of recorder outages


def fee_std(a):
    return M.fee(a)


FEES = {"std": fee_std, "pct1": lambda a: 0.01 * a if a > 0 else 0.0, "gross": lambda a: 0.0}


def eur_of(sold, fee):
    """sold: [(fraction, multiple)] -> what a 20 ticket became, each sale paying its own fee (as rocket_exits.eur_of)."""
    inv = M.TICKET - fee(M.TICKET)
    return sum(max(0.0, inv * f * m - fee(inv * f * m)) for f, m in sold) - M.TICKET


def walk(parts, hi, lo, c, stop_level=False, target_first=False):
    """Each part is its own limit sell; the stop sells whatever is still held at the low of the minute that crosses it (or at its
    level); a stop and a target in the same minute count as the stop (or the target first); at the end the last close."""
    s = np.flatnonzero(lo <= STOP)
    s = int(s[0]) if len(s) else None
    sold, rem = [], 1.0
    for f, lv in parts:
        t = np.flatnonzero(hi >= lv)
        if len(t) and (s is None or t[0] < s or (target_first and t[0] == s)):
            sold.append((f, lv)); rem -= f
    if rem > 1e-9:
        sold.append((rem, (STOP if stop_level else float(lo[s])) if s is not None else float(c[-1])))
    return sold


def first(mask):
    i = np.flatnonzero(mask)
    return int(i[0]) if len(i) else 10 ** 9


def path(a, start, p0, n_min):
    """Minutes start .. start+n_min-1 as multiples of p0; a pool without more bars keeps its last close."""
    out = []
    for k in ("hi", "lo", "c"):
        x = a[k][start:start + n_min]
        if len(x) < n_min:
            x = np.r_[x, np.full(n_min - len(x), a["c"][-1])]
        out.append(x / p0)
    return out


def one_file(f):
    coins = pd.read_parquet(os.path.join(S, "h2", "coins.parquet")).drop_duplicates("pool").set_index("pool")
    coins = coins[(coins["sol0"] >= 80) & (coins["sol0"] <= 90) & (coins["grad_ms"] >= T0) & (coins["grad_ms"] < T_END)]
    gap = np.load(os.path.join(S, "h2", "gap_minutes.npy")) // MIN
    k = [json.loads(l) for l in open(os.path.join(S, "mk", "SOLUSDT.jsonl"))]
    sol_t, sol_c = np.array([r[0] for r in k]), np.array([float(r[4]) for r in k])
    rows, info, skipped = [], [], {"gap": 0, "mc": 0, "nofill": 0}
    b = pd.read_parquet(f)
    b = b[b["pool"].isin(coins.index)]
    for pool, g in b.groupby("pool"):
        a = dense(g.sort_values("mi"), fill_hl=False)
        gm = int(coins.at[pool, "grad_ms"])
        gmin = gm // MIN
        if ((gap >= gmin) & (gap <= gmin + WIN)).any():
            skipped["gap"] += 1
            continue
        gap24 = bool(((gap >= gmin) & (gap <= gmin + max(CALLS) + INFO)).any())
        for C in CALLS:
            p0 = float(a["c"][min(C, len(a["c"])) - 1])
            ts = gm + C * MIN
            usd = float(sol_c[np.clip(np.searchsorted(sol_t, ts, side="right") - 1, 0, len(sol_c) - 1)])
            mc = p0 * 1e9 * usd
            if not (p0 > 0 and MC_LO <= mc <= MC_HI):
                skipped["mc"] += 1
                continue
            if not gap24:
                hi, lo, c = path(a, C, p0, INFO)
                info.append({"pool": pool, "C": C, "peak24": float(hi.max()), "low24": float(lo.min()), "c24": float(c[-1]),
                             "stopFirst": first(lo <= STOP) < first(hi >= 1.30)})
            for entry in ("call", "dip"):
                if entry == "call":
                    buy, start, tbuy = p0, C, ts
                else:
                    lo30 = path(a, C, p0, DIP_WAIT)[1]
                    j = np.flatnonzero(lo30 <= DIP)
                    if not len(j):
                        skipped["nofill"] += 1
                        continue
                    buy, start, tbuy = DIP * p0, C + int(j[0]) + 1, ts + int(j[0]) * MIN
                hi, lo, c = path(a, start, buy, PATH)
                r = {"pool": pool, "grad_ms": gm, "ts": tbuy, "C": C, "entry": entry, "mc": mc,
                     "hi6": float(hi.max()), "lo6": float(lo.min())}
                for x, parts in EXITS.items():
                    for fl, (sl, tf) in FILLS.items():
                        sold = walk(parts, hi, lo, c, sl, tf)
                        r["m_%s_%s" % (x, fl)] = sum(fr * m for fr, m in sold)
                        for fe, fn in FEES.items():
                            if fl == "std" or fe == "std":
                                r["e_%s_%s_%s" % (x, fl, fe)] = eur_of(sold, fn)
                        if fl == "std":
                            r["half30_%s" % x] = any(abs(m - 1.30) < 1e-9 for _, m in sold)
                rows.append(r)
    print(os.path.basename(f), len(rows), flush=True)
    return rows, info, skipped


def boot_days(e, day, n=2000, seed=7):
    days, inv = np.unique(day, return_inverse=True)
    s, k = np.bincount(inv, weights=e), np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(days), size=(n, len(days)))
    m = s[pick].sum(1) / k[pick].sum(1)
    return [round(float(np.percentile(m, 2.5)), 2), round(float(np.percentile(m, 97.5)), 2)]


def stats(d, col, mcol):
    e = d[col].to_numpy()
    if not len(e):
        return {"coins": 0}
    early, late = d["grad_ms"] < LATE, d["grad_ms"] >= LATE
    sim = FS.simulate({"scan": d["ts"].to_numpy(), "mult": d[mcol].to_numpy()}, np.arange(len(d)))
    wk = ((d["grad_ms"] - T0) // WEEK).astype(int)
    return {"coins": int(len(e)), "per20": round(float(e.mean()), 2), "range95": boot_days(e, (d["grad_ms"] // DAY).to_numpy()),
            "early": round(float(e[early.to_numpy()].mean()), 2), "late": round(float(e[late.to_numpy()].mean()), 2),
            "inProfitOf10": round(10 * float((e > 0).mean()), 1), "sim": sim["pProfit"] if sim else None,
            "weeks": {int(w): round(float(e[(wk == w).to_numpy()].mean()), 2) for w in sorted(wk.unique())}}


def main():
    files = sorted(glob.glob(os.path.join(S, "cb", "bars_*.parquet")))
    with mp.Pool(max(1, os.cpu_count() - 1)) as p:
        res = p.map(one_file, files)
    d = pd.DataFrame([r for x in res for r in x[0]])
    inf = pd.DataFrame([r for x in res for r in x[1]])
    skipped = {k: sum(x[2][k] for x in res) for k in res[0][2]}
    d.to_pickle(os.path.join(S, "calls_rows.pkl"))
    out = {"made": "2026-10-22", "prereg": "research/PREREG-CALLS-2026-10-22.md", "coins": int(d["pool"].nunique()),
           "skipped": skipped, "variants": {}, "reference": {}, "info": {}}
    for C in CALLS:
        for entry in ("call", "dip"):
            q = d[(d["C"] == C) & (d["entry"] == entry)]
            for x in EXITS:
                st = stats(q, "e_%s_std_std" % x, "m_%s_std" % x)
                st["holds"] = bool(st["coins"] and st["early"] > 0 and st["late"] > 0 and st["range95"][0] > 0
                                   and (st["sim"] or 0) >= FS.SIM_HOLD)
                st["half30"] = round(100 * float(q["half30_%s" % x].mean()), 1) if x != "A" else None
                st["kinder"] = {fl: round(float(q["e_%s_%s_std" % (x, fl)].mean()), 2) for fl in ("stopLevel", "targetFirst")}
                st["fees"] = {fe: round(float(q["e_%s_std_%s" % (x, fe)].mean()), 2) for fe in ("pct1", "gross")}
                (out["reference"] if x == "A" else out["variants"])["C%d_%s_%s" % (C, entry, x)] = st
    held = {k: v for k, v in out["variants"].items() if v["holds"]}
    out["choice"] = max(held, key=lambda k: held[k]["early"]) if held else None
    for C in CALLS:
        q = inf[inf["C"] == C]
        n = len(q)
        win = {}
        for lv in (1.30, 1.72, 2.0, 3.0):
            up = q["peak24"] >= lv
            win["%g" % lv] = {"share": round(100 * float(up.mean()), 1),
                              "alsoStop": round(100 * float((up & (q["low24"] <= STOP)).sum() / max(1, up.sum())), 1),
                              "below24h": round(100 * float((up & (q["c24"] < 1)).sum() / max(1, up.sum())), 1)}
        out["info"]["C%d" % C] = {"coins": n, "peak": win, "stopBefore30": round(100 * float(q["stopFirst"].mean()), 1),
                                  "below24h": round(100 * float((q["c24"] < 1).mean()), 1),
                                  "medianPeak": round(float(q["peak24"].median()), 2)}
    os.makedirs(os.path.join(HERE, "calls"), exist_ok=True)
    with open(os.path.join(HERE, "calls", "calls-check-2026-10-22.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("coins", out["coins"], "skipped", skipped)
    print("%-16s %6s %7s %15s %7s %7s %5s %6s %6s %7s %7s" % ("variant", "coins", "per20", "95%", "early", "late", "of10",
                                                            "sim%", "half30", "pct1", "gross"))
    for name, st in list(out["variants"].items()) + list(out["reference"].items()):
        print("%-16s %6d %7.2f %15s %7.2f %7.2f %5.1f %6s %6s %7.2f %7.2f%s" % (
            name, st["coins"], st["per20"], st["range95"], st["early"], st["late"], st["inProfitOf10"], st["sim"],
            st["half30"], st["fees"]["pct1"], st["fees"]["gross"], "  HOLDS" if st.get("holds") else ""))
    print("choice", out["choice"])
    print(json.dumps(out["info"], indent=1))


if __name__ == "__main__":
    main()
