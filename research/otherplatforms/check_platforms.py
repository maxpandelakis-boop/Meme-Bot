"""Four meme-coin methods from text sources on other platforms (fake money only): research/otherplatforms/PREREG-PLATFORMS-2026-11-04.md.

  python3 research/otherplatforms/check_platforms.py <monthsdata dir> <monthsh2 dir> <history2 coins.parquet> <out.json>

<monthsdata dir>: bars_w1/w2/w5.parquet, meta_w1/w2/w5.json, market.json (branch monthsdata). <monthsh2 dir>: bars_<day>.parquet
(branch monthsh2). coins.parquet: branch history2 (pool, grad_ms, sol0, tok0). Nothing is bought; no network. Needs pyarrow."""
import glob, json, math, os, sys
import numpy as np, pandas as pd

BAR, MIN, H = 300_000, 60_000, 3_600_000
N = 600                       # five-minute slots kept per coin (48 h = 576)
E_MAX, HOLD = 288, 288        # entries until bar 288 (24 h), holds up to 288 bars (24 h)
LIQ_MIN, ALLOW, BUY, FEE = 10_000, 0.60, 20.0, 0.81
H2_WINDOWS = {"w3": ("2026-08-10", "2026-09-10"), "w4": ("2026-09-10", "2026-10-09")}
LADDER_J = [(2.0, 0.50), (3.0, 0.25), (4.0, 0.25)]           # Jekyll: 50 % at 2x, more at 3x, the rest at 4x
LADDER_G = [(2.0, 0.50), (5.0, 0.25), (10.0, 0.25)]          # trojan / dextools: 50 % at 2x, 25 % at 5x, 25 % at 10x
LADDER_A = [(2.0, 0.25), (5.0, 0.25), (10.0, 0.25)]          # Archer blueprint: 25 % each, last 25 % rides
METHODS = ["M1", "M2", "M3", "M4"]
NAMES = {"M1": "Breakout, pullback, reclaim, buy the retest",
         "M2": "GMGN Migrated (mc >= $30k in the first hour) + Jekyll exits",
         "M3": "Axiom Trending (mc >= $70k and >= $30k 5-min volume) + Jekyll exits",
         "M4": "DexScreener new pairs (liq > $20k, FDV > $85k) + shared ladder",
         "B0": "information, not pre-registered: every graduation at bar 1 + Jekyll exits"}


def sale(v):
    """A sale worth v EUR after its fee (a sale worth less than its fee is not made)."""
    return max(0.0, v - max(0.005 * v, FEE)) if v > 0 else 0.0


def ladder_exit(cl, hi, has, k, p0, ladder, stop_fn):
    """Sell parts at targets (candle high), the rest at the stop (close) or at the time limit. -> (EUR, gross multiple)."""
    left, eur, gross, ti = 1.0, 0.0, 0.0, 0
    tok = BUY - FEE
    last = p0
    for j in range(k + 1, min(k + 1 + HOLD, N)):
        if not has[j]:
            continue
        last = cl[j]
        if stop_fn(cl[j], p0):                                 # worst case: the stop counts before a target in the same candle
            m = cl[j] / p0
            eur += sale(tok * left * m); gross += left * m; left = 0.0
            break
        while ti < len(ladder) and hi[j] >= ladder[ti][0] * p0:
            m, f = ladder[ti]
            eur += sale(tok * f * m); gross += f * m; left -= f; ti += 1
        if left <= 1e-9:
            break
    if left > 1e-9:
        m = last / p0
        eur += sale(tok * left * m); gross += left * m
    return eur - BUY, gross


def coin(c, b, sol):
    g = int(c["t"])
    t0 = g // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < N)
    j = j[keep]
    if not len(j):
        return {}
    cl = np.full(N, np.nan); hi = np.full(N, np.nan); lo = np.full(N, np.nan); vo = np.zeros(N); has = np.zeros(N, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]
    vo[j] = b["v"].to_numpy()[keep]; has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    hi = np.where(np.isfinite(hi), np.fmax(hi, cl), cl); lo = np.where(np.isfinite(lo), np.fmin(lo, cl), cl)
    kk = float(c["sol0"]) * float(c["tok0"])

    def liq(k):
        te = t0 + (k + 1) * BAR
        i = int(np.clip(np.searchsorted(sol[0], te, side="right") - 1, 0, len(sol[1]) - 1))
        usd = float(sol[1][i])
        return 2 * math.sqrt(kk * cl[k] / usd) * usd

    out = {}
    pct = lambda s: (lambda x, p0: x <= s * p0)
    ks = [k for k in range(1, E_MAX + 1) if has[k]]
    # M2: first close from bar 1 on with mc >= 30k, within 60 min (bars 1..11)
    for k in ks:
        if k > 11:
            break
        if cl[k] * 1e9 >= 30_000 and liq(k) >= LIQ_MIN:
            out["M2"] = ladder_exit(cl, hi, has, k, cl[k], LADDER_J, pct(0.65)); break
    # M3: mc >= 70k and >= 30k volume in that candle, within 24 h
    for k in ks:
        if cl[k] * 1e9 >= 70_000 and vo[k] >= 30_000 and liq(k) >= LIQ_MIN:
            out["M3"] = ladder_exit(cl, hi, has, k, cl[k], LADDER_J, pct(0.65)); break
    # M4: liquidity > 20k and FDV > 85k, within 24 h
    for k in ks:
        if cl[k] * 1e9 > 85_000 and liq(k) > 20_000:
            out["M4"] = ladder_exit(cl, hi, has, k, cl[k], LADDER_G, pct(0.65)); break
    # B0 (information): bar 1 (first candle with data from bar 1 on, within the first hour) + Jekyll exits
    for k in ks:
        if k > 11:
            break
        if liq(k) >= LIQ_MIN:
            out["B0"] = ladder_exit(cl, hi, has, k, cl[k], LADDER_J, pct(0.65)); break
    # M1: level = highest close of the candles closed by 60 min; breakout, retest (low <= L), entry close >= L
    jN = (g + 60 * MIN - t0) // BAR - 1
    rng = has[:jN + 1]
    if jN >= 1 and rng.sum() >= 2:
        L = float(np.nanmax(cl[:jN + 1][rng]))
        kb = next((k for k in range(jN + 1, E_MAX + 1) if has[k] and cl[k] > L), None)
        if kb is not None:
            k2 = next((k for k in range(kb + 1, E_MAX + 1) if has[k] and lo[k] <= L), None)
            if k2 is not None:
                ke = None
                for k in range(k2, E_MAX + 1):
                    if not has[k]:
                        continue
                    if cl[k] < 0.85 * L:
                        break                                 # structure broken before an entry
                    if cl[k] >= L:
                        ke = k; break
                if ke is not None and liq(ke) >= LIQ_MIN:
                    out["M1"] = ladder_exit(cl, hi, has, ke, cl[ke], LADDER_A, lambda x, p0, L=L: x < 0.90 * L)
    return out


def load_sol(md):
    mk = json.load(open(os.path.join(md, "market.json")))
    s = np.array(mk["SOLUSDT"], dtype=float)
    return s[:, 0], s[:, 1]


def windows(md, h2, coins_pq):
    for w in ("w1", "w2", "w5"):
        meta = {r["pool"]: r for r in json.load(open(os.path.join(md, "meta_%s.json" % w))) if float(r.get("sol0") or 0) >= 10}
        yield w, meta, pd.read_parquet(os.path.join(md, "bars_%s.parquet" % w))
    cs = pd.read_parquet(coins_pq, columns=["pool", "grad_ms", "sol0", "tok0"])
    cs = cs[cs.sol0 >= 10]
    files = sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))
    bars = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    for w, (a, z) in H2_WINDOWS.items():
        ta, tz = pd.Timestamp(a, tz="UTC").value // 10**6, pd.Timestamp(z, tz="UTC").value // 10**6
        sub = cs[(cs.grad_ms >= ta) & (cs.grad_ms < tz)]
        meta = {r.pool: {"t": int(r.grad_ms), "sol0": float(r.sol0), "tok0": float(r.tok0)} for r in sub.itertuples()}
        yield w, meta, bars[bars.pool.isin(meta)]


def boot_lo(v, q, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for k in range(0, draws, 1000):
        means[k:k + 1000] = v[rng.integers(0, len(v), (1000, len(v)))].mean(1)
    return float(np.quantile(means, q)), float((means <= 0).mean())


def judge(v, q=0.0025):
    v = np.asarray(v, float)
    if not len(v):
        return {"n": 0, "holds": False}
    va = v - ALLOW
    lo, p = boot_lo(va, q)
    best = int(np.argmax(v))
    r = {"n": int(len(v)), "meanAfterAllowance": round(float(va.mean()), 2), "lowerBound": round(lo, 2), "pBoot": round(p, 4),
         "total": round(float(va.sum()), 1), "totalWithoutBest": round(float(va.sum() - va[best]), 1),
         "inProfit": round(100 * float((v > 0).mean()), 1), "bestTrade": round(float(v[best]), 2)}
    r["holds"] = bool(r["n"] >= 40 and r["meanAfterAllowance"] > 0 and lo > 0 and r["totalWithoutBest"] > 0)
    return r


def main(md, h2, coins_pq, out):
    sol = load_sol(md)
    T = {m: {"w": [], "eur": [], "gross": []} for m in METHODS + ["B0"]}
    ncoins = {}
    for w, meta, bars in windows(md, h2, coins_pq):
        n = 0
        for pool, b in bars.groupby("pool", sort=False):
            c = meta.get(pool)
            if c is None:
                continue
            n += 1
            for m, (eur, gross) in coin(c, b.sort_values("t"), sol).items():
                T[m]["w"].append(w); T[m]["eur"].append(eur); T[m]["gross"].append(gross)
        ncoins[w] = n
        print(w, "coins with candles", n, flush=True)
    res = {"prereg": "research/otherplatforms/PREREG-PLATFORMS-2026-11-04.md", "coins": ncoins, "methods": {}}
    for m, t in T.items():
        wv, ev, gv = np.array(t["w"]), np.array(t["eur"]), np.array(t["gross"])
        r = {"name": NAMES[m], "all": judge(ev) if m != "B0" else judge(ev, 0.01), "byWindow": {}}
        r["all"]["grossMultipleMean"] = round(float(gv.mean()), 3) if len(gv) else None
        r["all"]["grossMultipleMedian"] = round(float(np.median(gv)), 3) if len(gv) else None
        for w in ("w1", "w2", "w3", "w4", "w5"):
            s = ev[wv == w]
            r["byWindow"][w] = {"n": int(len(s)), "meanAfterAllowance": round(float((s - ALLOW).mean()), 2) if len(s) else None,
                                "inProfit": round(100 * float((s > 0).mean()), 1) if len(s) else None,
                                "grossMean": round(float(gv[wv == w].mean()), 3) if len(s) else None}
        r["windowsPositive"] = sum(1 for x in r["byWindow"].values() if x["meanAfterAllowance"] is not None and x["meanAfterAllowance"] > 0)
        res["methods"][m] = r
        print(m, json.dumps(r["all"]), "positive windows", r["windowsPositive"], flush=True)
    json.dump(res, open(out, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:5])
