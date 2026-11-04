#!/usr/bin/env python3
"""check_quickflip.py: the quick-flip test of 4 Nov 2026 (research only, fake money). Pre-registration:
research/quickflip/PREREG-QUICKFLIP-2026-11-04.md. Buy, then sell after H = 1-10 minutes if the trade is in profit after all costs
(else a stop, the first later profit or a time cap), on the history2 one-minute bars and on the Pick account's live minute paths.

  python3 check_quickflip.py build  --bars <chartbars dir> --h2 <history2 dir> --out <work dir>
  python3 check_quickflip.py fit    --out <work dir>              -> FIT table + research/quickflip/FROZEN-2026-11-04.json
  python3 check_quickflip.py check  --out <work dir>              -> CHECK judgement of the frozen rules + every rule on CHECK
  python3 check_quickflip.py live   --out <work dir> --res <results checkout>   -> the Pick account's / Learning Pick's buys
"""
import argparse, glob, json, math, os, pickle, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT = 1788998400000            # 10 Sep 2026 00:00 UTC: FIT before, CHECK from then
LIVE_FROM = 1792684800000        # 22 Oct 2026 16:00 UTC: shadow.SINCE, the first Pick buys with a 12-hour minute path
MIN = 60_000
K = 62                           # path minutes 0..61 (61 = the copier's late sale after a 60-minute cap)
HS = (1, 2, 3, 5, 10)
STOPS = (0.10, 0.20, 0.30)
CAPS = (15, 60)
BOOT, Q = 10_000, 0.01
FROZEN = os.path.join(HERE, "FROZEN-2026-11-04.json")


# ---- money -------------------------------------------------------------------------------------------------------------------

def pick_money(m):
    """50 EUR, 1 % per side (at least 0.10), allowance 0.75 -> EUR result after the allowance (vectorised)."""
    v = 49.5 * np.asarray(m, dtype=float)
    fee = np.maximum(0.01 * v, 0.10)
    back = np.where(v > fee, v - fee, 0.0)
    return back - 50.0 - 0.75


def radar_money(m):
    """20 EUR, max(0.5 %, 0.81) per side (memebot.tip_net), allowance 0.60 -> EUR result after the allowance (vectorised)."""
    v = 19.19 * np.asarray(m, dtype=float)
    fee = np.maximum(0.005 * v, 0.81)
    back = np.where(v > fee, v - fee, 0.0)
    return back - 20.0 - 0.60


MONEY = {"pick": (pick_money, 50.0), "radar": (radar_money, 20.0)}


def breakeven(fn):
    lo, hi = 1.0, 2.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if fn(mid) > 0:
            hi = mid
        else:
            lo = mid
    return hi


BE = {k: breakeven(v[0]) for k, v in MONEY.items()}


# ---- rules -------------------------------------------------------------------------------------------------------------------

def rules():
    out = [("T_%d" % h, {"kind": "T", "H": h}) for h in HS]
    for h in HS:
        for s in STOPS:
            for cap in CAPS:
                out.append(("W_%d_%d_%d" % (h, int(s * 100), cap), {"kind": "W", "H": h, "stop": s, "cap": cap}))
    return out


RULES = rules()


def run_rule(C, HI, LO, r, be):
    """C/HI/LO: [n, K] prices (column 0 = entry). -> (multiple, minute sold, True if sold at the stop)."""
    n = C.shape[0]
    e = C[:, 0]
    if r["kind"] == "T":
        k = np.full(n, r["H"])
        return C[:, r["H"]] / e, k, np.zeros(n, bool)
    s, H, cap = r["stop"], r["H"], r["cap"]
    mult = np.full(n, np.nan)
    when = np.full(n, -1)
    stopped = np.zeros(n, bool)
    open_ = np.ones(n, bool)
    for k in range(1, cap + 1):
        lo = LO[:, k] / e
        cl = C[:, k] / e
        hit = open_ & (lo <= 1.0 - s)
        mult[hit], when[hit], stopped[hit] = lo[hit], k, True
        open_ &= ~hit
        if k >= H:
            ok = open_ & (cl >= be)
            mult[ok], when[ok] = cl[ok], k
            open_ &= ~ok
        if k == cap:
            mult[open_], when[open_] = cl[open_], k
            open_[:] = False
    return mult, when, stopped


def copier(C, when):
    """The person copying by hand: buys at the close of the minute after the bot's entry, sells at the close of the minute after
    the bot's sale."""
    idx = np.arange(C.shape[0])
    return C[idx, np.minimum(when + 1, K - 1)] / C[:, 1]


# ---- statistics ---------------------------------------------------------------------------------------------------------------

def bar39(v, rng=None):
    """PR #39 bar on results after the allowance (EUR per trade)."""
    v = np.asarray(v, dtype=float)
    n = len(v)
    if n == 0:
        return {"n": 0, "holds": False}
    rng = rng or np.random.default_rng(20261104)
    means = np.empty(BOOT)
    for i in range(0, BOOT, 1000):
        idx = rng.integers(0, n, size=(1000, n))
        means[i:i + 1000] = v[idx].mean(axis=1)
    lo = float(np.quantile(means, Q))
    wob = float(v.sum() - v.max())
    r = {"n": n, "mean": round(float(v.mean()), 3), "total": round(float(v.sum()), 2), "lo1": round(lo, 3),
         "totalWithoutBest": round(wob, 2), "pBootPos": round(float((means > 0).mean()), 4)}
    r["holds"] = bool(n >= 40 and r["mean"] > 0 and lo > 0 and wob > 0)
    return r


def describe(mult, when, stopped, money):
    fn, ticket = MONEY[money]
    v = fn(mult)
    return {"n": int(len(v)), "mean": round(float(v.mean()), 3) if len(v) else None,
            "pctOfTicket": round(100 * float(v.mean()) / ticket, 2) if len(v) else None,
            "total": round(float(v.sum()), 2), "inProfit": round(float((v > 0).mean()), 3) if len(v) else None,
            "grossMean": round(float(np.nanmean(mult)), 4) if len(v) else None,
            "grossMedian": round(float(np.nanmedian(mult)), 4) if len(v) else None,
            "stopShare": round(float(stopped.mean()), 3) if len(v) else None,
            "meanMinutes": round(float(when.mean()), 1) if len(v) else None,
            "worst": round(float(v.min()), 2) if len(v) else None, "best": round(float(v.max()), 2) if len(v) else None}


# ---- build --------------------------------------------------------------------------------------------------------------------

def build(a):
    import pandas as pd
    coins = pd.read_parquet(os.path.join(a.h2, "coins.parquet"))
    coins = coins[coins["sol0"] >= 10].drop_duplicates("pool")
    gaps = np.sort(np.load(os.path.join(a.h2, "gap_minutes.npy")).astype("int64"))
    cols = ["pool", "mi", "p_close", "p_hi", "p_lo"]
    bars = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(os.path.join(a.bars, "bars_*.parquet")))],
                     ignore_index=True)
    bars = bars[bars["pool"].isin(set(coins["pool"])) & np.isfinite(bars["p_close"]) & (bars["p_close"] > 0)]
    bars = bars.sort_values(["pool", "mi"]).reset_index(drop=True)
    pools = bars["pool"].to_numpy()
    starts = np.flatnonzero(np.r_[True, pools[1:] != pools[:-1]])
    ends = np.r_[starts[1:], len(pools)]
    where = dict(zip(pools[starts], zip(starts, ends)))
    MI = bars["mi"].to_numpy().astype(np.int32)
    CL = bars["p_close"].to_numpy().astype(np.float64)
    HI = bars["p_hi"].to_numpy().astype(np.float64)
    LO = bars["p_lo"].to_numpy().astype(np.float64)
    HI = np.where(np.isfinite(HI), np.maximum(HI, CL), CL)
    LO = np.where(np.isfinite(LO), np.minimum(LO, CL), CL)
    print("bars", len(bars), "pools", len(where), flush=True)

    hourly = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(a.h2, "hourly", "*.parquet")))],
                       ignore_index=True)
    hourly = hourly[hourly["pool"].isin(set(coins["pool"]))]
    solusd = hourly.groupby(hourly["ts"] // 3_600_000)["sol_usd"].median()
    print("hourly rows", len(hourly), flush=True)

    def path(pool, e):
        if pool not in where:
            return None
        i, j = where[pool]
        mi = MI[i:j]
        a0, a1 = np.searchsorted(mi, e - 5), np.searchsorted(mi, e + K)
        if a0 >= a1 or mi[a0] > e:
            return None                                  # no bar in the 5 minutes up to the entry
        m, cl, hi, lo = mi[a0:a1], CL[i + a0:i + a1], HI[i + a0:i + a1], LO[i + a0:i + a1]
        C = np.empty(K); Hh = np.empty(K); Ll = np.empty(K)
        last = cl[m <= e][-1]
        pos = {int(x): t for t, x in enumerate(m)}
        for k in range(K):
            t = pos.get(e + k) if k > 0 else None
            if t is None:
                C[k] = Hh[k] = Ll[k] = last
            else:
                C[k], Hh[k], Ll[k] = cl[t], hi[t], lo[t]
                last = cl[t]
        return C, Hh, Ll

    def gap_near(t_ms):
        lo_i = np.searchsorted(gaps, t_ms - 5 * MIN)
        return lo_i < len(gaps) and gaps[lo_i] <= t_ms + 75 * MIN

    sets = {}
    g = coins.set_index("pool")

    def add(key, pool, e, grad_ms, extra=None):
        t_ms = int(grad_ms) + (e + 1) * MIN
        if gap_near(t_ms):
            return "gap"
        p = path(pool, e)
        if p is None:
            return "nobar"
        sets.setdefault(key, []).append((pool, int(grad_ms), e, t_ms, p, extra))
        return "ok"

    from collections import Counter
    cnt = {k: Counter() for k in ("G0", "G30", "P", "R")}
    for pool, row in g.iterrows():
        cnt["G0"][add("G0", pool, 0, row["grad_ms"])] += 1
        # G30: liquidity >= $10k at minute 29 (2 x the SOL side of the constant product, in USD)
        if pool in where:
            i, j = where[pool]
            mi = MI[i:j]
            b = np.searchsorted(mi, 29, side="right") - 1
            if b >= 0 and mi[b] >= 24:
                price = CL[i + b]
                usd = solusd.get((int(row["grad_ms"]) + 30 * MIN) // 3_600_000, solusd.median())
                liq = 2.0 * math.sqrt(max(row["sol0"] * row["tok0"] * price, 0.0)) * usd
                if liq >= 10_000:
                    cnt["G30"][add("G30", pool, 29, row["grad_ms"], {"liq": liq})] += 1
                else:
                    cnt["G30"]["lowliq"] += 1
            else:
                cnt["G30"]["nobar"] += 1
        else:
            cnt["G30"]["nobar"] += 1

    hourly = hourly.sort_values(["pool", "h"])
    pc = lambda s: s.fillna(0.0)
    pickok = ((hourly["h"] >= 1) & (hourly["h"] <= 23) & (hourly["liquidity_usd"] >= 20_000)
              & (hourly["market_cap_usd"] >= 100_000) & (hourly["market_cap_usd"] <= 50_000_000)
              & (hourly["volume_24h"] >= 20_000) & (pc(hourly["price_change_1h"]) > -40) & (pc(hourly["price_change_6h"]) > -50)
              & (pc(hourly["price_change_24h"]) > -70) & (pc(hourly["price_change_1h"]) < 150) & (pc(hourly["price_change_6h"]) < 400)
              & (hourly["volume_24h"] <= 8 * hourly["market_cap_usd"]))
    radarok = ((hourly["h"] >= 1) & (hourly["h"] <= 12) & (hourly["liquidity_usd"] >= 15_000) & (hourly["volume_24h"] >= 15_000)
               & (hourly["market_cap_usd"] >= 100_000) & (hourly["market_cap_usd"] <= 5_000_000)
               & (pc(hourly["price_change_1h"]) > -10) & (pc(hourly["price_change_6h"]) > -50))
    for key, ok in (("P", pickok), ("R", radarok)):
        first = hourly[ok].drop_duplicates("pool")
        for _, row in first.iterrows():
            cnt[key][add(key, row["pool"], 60 * int(row["h"]) - 1, row["grad_ms"], {"h": int(row["h"])})] += 1

    out = {}
    for key, lst in sets.items():
        P = np.stack([x[4][0] for x in lst]); Hh = np.stack([x[4][1] for x in lst]); Ll = np.stack([x[4][2] for x in lst])
        out[key] = {"pool": [x[0] for x in lst], "grad": np.array([x[1] for x in lst]), "t": np.array([x[3] for x in lst]),
                    "C": P, "HI": Hh, "LO": Ll}
        print(key, len(lst), dict(cnt[key]), flush=True)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "paths.pkl"), "wb") as f:
        pickle.dump({"sets": out, "counts": {k: dict(v) for k, v in cnt.items()}}, f)


def load(a):
    with open(os.path.join(a.out, "paths.pkl"), "rb") as f:
        return pickle.load(f)


def part(s, which):
    m = s["grad"] < SPLIT if which == "fit" else s["grad"] >= SPLIT
    return s["C"][m], s["HI"][m], s["LO"][m]


def score_all(C, HI, LO, money):
    res = {}
    for name, r in RULES:
        mult, when, stopped = run_rule(C, HI, LO, r, BE[money])
        res[name] = (mult, when, stopped)
    return res


def fit(a):
    d = load(a)
    frozen, table = {"made": "fit on graduations before 10 Sep 2026 (w3)", "be": BE, "cells": {}}, {}
    for key in ("G0", "G30", "P", "R"):
        C, HI, LO = part(d["sets"][key], "fit")
        for money in ("pick", "radar"):
            res = score_all(C, HI, LO, money)
            rows = {name: describe(*res[name], money) for name, _ in RULES}
            table["%s/%s" % (key, money)] = rows
            ok = [(rows[n]["mean"], n) for n, _ in RULES if rows[n]["n"] >= 100]
            best = max(ok)[1] if ok else None
            frozen["cells"]["%s/%s" % (key, money)] = {"rule": best, "fit": rows[best] if best else None}
            print("%-4s %-5s n=%d best %s %s" % (key, money, len(C), best, rows[best]["mean"] if best else None), flush=True)
    with open(FROZEN, "w") as f:
        json.dump(frozen, f, indent=1)
    with open(os.path.join(HERE, "FIT-TABLE-2026-11-04.json"), "w") as f:
        json.dump(table, f, indent=1)


def check(a):
    d = load(a)
    frozen = json.load(open(FROZEN))
    rdict = dict(RULES)
    out = {"judge": {}, "all": {}, "luck": {}, "copier": {}}
    for key in ("G0", "G30", "P", "R"):
        C, HI, LO = part(d["sets"][key], "check")
        for money in ("pick", "radar"):
            cell = "%s/%s" % (key, money)
            fn = MONEY[money][0]
            res = score_all(C, HI, LO, money)
            rows = {name: describe(*res[name], money) for name, _ in RULES}
            out["all"][cell] = rows
            name = frozen["cells"][cell]["rule"]
            mult, when, stopped = res[name]
            j = bar39(fn(mult))
            j.update({"rule": name, "desc": rows[name]})
            out["judge"][cell] = j
            out["luck"][cell] = {"rulesAboveZero": sum(1 for r in rows.values() if r["mean"] > 0), "rules": len(rows),
                                 "bestCheck": max((r["mean"], n) for n, r in rows.items())}
            cm = copier(C, when)
            cp = {"frozen": describe(cm, when + 1, stopped, money)}
            for h in HS:
                m2, w2, s2 = res["T_%d" % h]
                cp["T_%d" % h] = describe(copier(C, w2), w2 + 1, s2, money)
            out["copier"][cell] = cp
            print("%-10s n=%d %s mean %.2f lo1 %.2f holds %s | rules>0 %d/35 | copier %.2f" % (
                cell, j["n"], name, j["mean"], j["lo1"], j["holds"], out["luck"][cell]["rulesAboveZero"],
                cp["frozen"]["mean"]), flush=True)
    with open(os.path.join(HERE, "CHECK-2026-11-04.json"), "w") as f:
        json.dump(out, f, indent=1)


# ---- live ---------------------------------------------------------------------------------------------------------------------

def grid(c, w=None):
    """A live path (rows [seconds from the entry, close multiple, ...], optional w rows [seconds, high, low]) -> C, HI, LO [K]
    with column 0 = the entry candle (close 1.0 by construction), minute k = the k-th candle after it."""
    rows = sorted((float(r[0]), float(r[1])) for r in c if r and r[1] is not None)
    s0 = [s for s, _ in rows if s <= 0]
    if not s0:
        return None
    s0 = s0[-1]
    byk = {}
    for s, v in rows:
        k = int(round((s - s0) / 60.0))
        if 0 <= k < K:
            byk[k] = v
    wk = {}
    for r in w or []:
        k = int(round((float(r[0]) - s0) / 60.0))
        if 0 <= k < K and r[1] is not None and r[2] is not None:
            wk[k] = (float(r[1]), float(r[2]))
    C = np.empty(K); Hh = np.empty(K); Ll = np.empty(K)
    last = byk.get(0, 1.0)
    for k in range(K):
        if k in byk:
            last = byk[k]
            hi, lo = wk.get(k, (last, last))
            C[k], Hh[k], Ll[k] = last, max(hi, last), min(lo, last)
        else:
            C[k] = Hh[k] = Ll[k] = last
    return C, Hh, Ll


def live(a):
    sys.path.insert(0, os.path.join(HERE, "..", "livesearch"))
    sys.path.insert(0, os.path.join(HERE, "..", ".."))
    sys.path.insert(0, os.path.join(HERE, ".."))
    import ls_build
    frozen = json.load(open(FROZEN))
    rdict = dict(RULES)
    picks = [r for r in ls_build.build_pick(a.res) if r["shadow"] and r["real"] is not None
             and (ls_build.num(r["p"].get("entryAt")) or 0) >= LIVE_FROM]
    G = [grid(r["shadow"]["c"], r["shadow"].get("w")) for r in picks]
    keep = [i for i, x in enumerate(G) if x is not None]
    picks = [picks[i] for i in keep]
    C = np.stack([G[i][0] for i in keep]); HI = np.stack([G[i][1] for i in keep]); LO = np.stack([G[i][2] for i in keep])
    real = np.array([r["real"] for r in picks]) - 0.75          # the real booked result (Sell bot), after the same allowance
    out = {"pick": {"n": len(picks), "real": bar39(real), "rules": {}, "frozen": {}, "copier": {}},
           "from": LIVE_FROM, "to": max(int(ls_build.num(r["p"].get("entryAt"))) for r in picks)}
    res = score_all(C, HI, LO, "pick")
    for name, _ in RULES:
        mult, when, stopped = res[name]
        v = pick_money(mult)
        dsc = describe(mult, when, stopped, "pick")
        dsc["vsReal"] = round(float((v - real).mean()), 3)
        out["pick"]["rules"][name] = dsc
    for money in ("pick", "radar"):
        name = frozen["cells"]["P/%s" % money]["rule"]
        mult, when, stopped = run_rule(C, HI, LO, rdict[name], BE[money])
        v = MONEY[money][0](mult)
        j = bar39(v)
        j.update({"rule": name, "desc": describe(mult, when, stopped, money)})
        if money == "pick":
            diff = v - real
            j["pairedVsReal"] = bar39(diff)
        out["pick"]["frozen"][money] = j
        out["pick"]["copier"][money] = describe(copier(C, when), when + 1, stopped, money)
    for h in HS:
        m2, w2, s2 = res["T_%d" % h]
        out["pick"]["copier"]["T_%d" % h] = describe(copier(C, w2), w2 + 1, s2, "pick")
    # first minutes of the real buys: how far does the price go at all?
    out["pick"]["firstMinutes"] = {str(k): {"median": round(float(np.median(C[:, k])), 4), "p10": round(float(np.quantile(C[:, k], .1)), 4),
                                            "p90": round(float(np.quantile(C[:, k], .9)), 4),
                                            "aboveBE": round(float((C[:, k] >= BE["pick"]).mean()), 3)} for k in (1, 2, 3, 5, 10)}

    # Learning Pick (closes only) cross-check
    lern = ls_build.build_lern(a.res)
    LG = [grid(d.get("c") or []) for d in lern if isinstance(d.get("c"), list) and d.get("c")]
    LG = [x for x in LG if x is not None]
    if LG:
        LC = np.stack([x[0] for x in LG]); LH = np.stack([x[1] for x in LG]); LL = np.stack([x[2] for x in LG])
        lres = score_all(LC, LH, LL, "pick")
        out["lern"] = {"n": len(LG), "rules": {n: describe(*lres[n], "pick") for n, _ in RULES}}
        name = frozen["cells"]["P/pick"]["rule"]
        out["lern"]["frozen"] = dict(bar39(pick_money(lres[name][0])), rule=name)
    with open(os.path.join(HERE, "LIVE-2026-11-04.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"n": out["pick"]["n"], "real": out["pick"]["real"], "frozen": out["pick"]["frozen"],
                      "copier": out["pick"]["copier"]["pick"], "first": out["pick"]["firstMinutes"],
                      "lern": out.get("lern", {}).get("frozen")}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "fit", "check", "live"])
    ap.add_argument("--bars"); ap.add_argument("--h2"); ap.add_argument("--out"); ap.add_argument("--res")
    a = ap.parse_args()
    {"build": build, "fit": fit, "check": check, "live": live}[a.step](a)


if __name__ == "__main__":
    main()
