"""The pre-registered check of research/PREREG-REPLAYS-2026-10-22.md (fake money only): the video's 10,000 replays of a coin's own
past hourly moves as a forecast and as a picker, on the history2 rows and on the bot's own scans. Written before any replay was run.
usage: python3 research/check_replays.py <history2 dir> <memesnapres dir>      (needs numpy, pandas and pyarrow)
"""
import glob, json, math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import memebot as M
import forecast as FC
from check_history2 import bot_gates, eur, boot
from forecast_build import rows_of, make_ref, forecast_x, score, ROWS_PER_COIN

SPLIT = 1789430400000      # 2026-09-15 00:00 UTC, by graduation
LEARN_FROM = 1791380700000
N, MIN_MOVES, MAX_MOVES = 10_000, 5, 24
TS = [round(0.20 + 0.05 * i, 2) for i in range(13)]
_RNG = np.random.default_rng(7)
_IA, _IB = None, None
# break-even multiple of tip_net (profit means tip_net > 0)
_lo, _hi = 1.0, 2.0
for _ in range(60):
    _mid = (_lo + _hi) / 2
    _lo, _hi = (_mid, _hi) if M.tip_net(_mid) <= 0 else (_lo, _mid)
BREAK_EVEN = _hi


def replay(moves):
    """moves: the coin's own past hourly log moves -> (profit chance, zero chance) from 10,000 replays, or None."""
    moves = [x for x in moves if x == x and math.isfinite(x)][-MAX_MOVES:]
    if len(moves) < MIN_MOVES:
        return None
    r = np.asarray(moves)
    a = r[_RNG.integers(0, len(r), N)]
    b = r[_RNG.integers(0, len(r), N)]
    m = np.exp(a + 0.7 * b)
    return float((m >= BREAK_EVEN).mean()), float((m < 0.02).mean())


def h2_moves(d):
    """For every history2 row, the list of the coin's own hourly log moves up to it (consecutive hours only)."""
    out = [None] * len(d)
    mint, h, p, c1 = d["mint"].to_numpy(), d["h"].to_numpy(), d["price_usd"].to_numpy(), d["price_change_1h"].to_numpy()
    prev_m, moves = None, []
    for i in range(len(d)):
        if mint[i] != prev_m:
            prev_m, moves = mint[i], []
            if h[i] == 1 and c1[i] == c1[i] and c1[i] > -100:
                moves.append(math.log(1 + c1[i] / 100.0))
        elif h[i] == h[i - 1] + 1 and p[i] > 0 and p[i - 1] > 0:
            moves.append(math.log(p[i] / p[i - 1]))
        out[i] = list(moves)
    return out


def pick_stats(chances, profits, eurs, hit3s):
    n = len(eurs)
    if not n:
        return {"coins": 0}
    lo, hi = boot(eurs)
    return {"coins": n, "win": round(100.0 * sum(profits) / n, 1), "avg": round(sum(eurs) / n, 3), "ci": [lo, hi],
            "hit3": None if hit3s is None else round(100.0 * sum(hit3s) / n, 1)}


def main():
    import pandas as pd
    h2, rec = sys.argv[1], sys.argv[2]
    print("break-even multiple %.4f" % BREAK_EVEN)
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(h2, "**", "hourly_*.parquet"), recursive=True))], ignore_index=True)
    d = d.sort_values(["mint", "ts"]).reset_index(drop=True)
    d["moves"] = h2_moves(d)
    ok = (~d["gap_pre"] & ~d["gap_1"] & ~d["gap_6"] & d["px1"].notna() & d["last6"].notna() & (d["price_usd"] > 0))

    # test 1, history2: the forecast_build backtest rows
    pool = d[ok & (d["liquidity_usd"] >= 15_000) & (d["volume_24h"] >= 15_000) & (d["market_cap_usd"] >= 30_000) & (d["market_cap_usd"] <= 5_000_000)]
    pool = pool.groupby("mint", sort=False).head(ROWS_PER_COIN)
    rows = rows_of(pool)
    fit = make_ref([r for r in rows if r[2] < SPLIT])
    test = d[ok & bot_gates(d) & (d["grad_ms"] >= SPLIT)].drop_duplicates("mint", keep="first")
    la, rp, ys, young = [], [], [], 0
    for (x, o, _, _), mv in zip(rows_of(test), test["moves"]):
        fc = forecast_x(x, fit)
        r = replay(mv)
        if not fc:
            continue
        if r is None:
            young += 1
            continue
        la.append(fc["profit"]); rp.append(r[0]); ys.append(o[4])
    print("\n== test 1, history2 (gate passers from 15 Sep): %d with both forecasts, %d too young" % (len(ys), young))
    print("  replays:    %s" % json.dumps(score(rp, ys, fit["base"]["profit"])))
    print("  look-alike: %s" % json.dumps(score(la, ys, fit["base"]["profit"])))

    # test 2, history2 picker
    g = d[ok & bot_gates(d)].copy()
    g["chance"] = [(replay(mv) or (None,))[0] for mv in g["moves"]]
    g = g[g["chance"].notna()]
    g["eur"] = [eur(m) for m in (g["px1"] / g["price_usd"])]
    g["profit"] = (g["px1"] / g["price_usd"]) >= BREAK_EVEN
    g["hit3"] = g["tp3_min"].notna()
    f_, c_ = g[g["grad_ms"] < SPLIT], g[g["grad_ms"] >= SPLIT]

    def sel(part, t):
        return part[part["chance"] >= t].drop_duplicates("mint", keep="first")

    print("\n== test 2, history2 picker (first gate row per coin with chance >= T, held 1.7 h)")
    print("  all gate passers, fit:   %s" % pick_stats(None, list(f_.drop_duplicates("mint")["profit"]), list(f_.drop_duplicates("mint")["eur"]), list(f_.drop_duplicates("mint")["hit3"])))
    print("  all gate passers, check: %s" % pick_stats(None, list(c_.drop_duplicates("mint")["profit"]), list(c_.drop_duplicates("mint")["eur"]), list(c_.drop_duplicates("mint")["hit3"])))
    best = None
    for t in TS:
        s = sel(f_, t)
        avg = float(s["eur"].mean()) if len(s) else float("nan")
        print("  T=%.2f fit: coins %d, win %.1f%%, avg %.3f" % (t, len(s), 100 * s["profit"].mean() if len(s) else 0, avg))
        if len(s) >= 100 and (best is None or avg > best[1]):
            best = (t, avg)
    if best is None:
        print("no T lets 100 fit coins through")
        return
    T = best[0]
    s = sel(c_, T)
    t2 = pick_stats(None, list(s["profit"]), list(s["eur"]), list(s["hit3"]))
    print("  chosen T=%.2f (fit avg %.3f); CHECK: %s" % (T, best[1], t2))

    # tests 1 and 3 on the bot's own scans
    full = make_ref(rows)
    del d, g, pool, test
    hist = {}          # address -> [(t0, mc)] in scan order (file names start with the scan time)
    seen, la2, rp2, ys2, picks, young2 = set(), [], [], [], [], 0
    allp = []
    for fn in sorted(glob.glob(os.path.join(rec, "*.json"))):
        doc = json.load(open(fn, encoding="utf-8"))
        if str(doc.get("rule") or "") != "m9-2h":
            continue
        t0, t1 = FC._num(doc.get("t0")), FC._num(doc.get("t")) or 0
        for c in doc.get("coins") or []:
            a, mc = c.get("a"), FC._num(c.get("mc"))
            if not a or not t0:
                continue
            hv = hist.setdefault(a, [])
            if mc and mc > 0 and (not hv or t0 - hv[-1][0] > 60_000):
                hv.append((t0, mc))
            m = FC._num(c.get("mult"))
            if t1 < LEARN_FROM or c.get("why") or m is None or not isinstance(c.get("f"), dict) or a in seen:
                continue
            seen.add(a)
            mv = [math.log(q / p) for (s0, p), (s1, q) in zip(hv, hv[1:]) if 30 <= (s1 - s0) / 60_000 <= 120]
            r = replay(mv)
            prof = float(M.tip_net(m) > 0)
            e = eur(m)
            allp.append((prof, e))
            if r is None:
                young2 += 1
                continue
            fc = FC.forecast(c["f"], full)
            if fc:
                la2.append(fc["profit"]); rp2.append(r[0]); ys2.append(prof)
            if r[0] >= T:
                picks.append((prof, e))
    print("\n== test 1, the bot's gate passers (first scan per coin): %d with both forecasts, %d too young" % (len(ys2), young2))
    if ys2:
        print("  replays:    %s" % json.dumps(score(rp2, ys2, full["base"]["profit"])))
        print("  look-alike: %s" % json.dumps(score(la2, ys2, full["base"]["profit"])))
    print("\n== test 3, the bot's gate passers with chance >= %.2f" % T)
    print("  all passers: %s" % pick_stats(None, [p for p, _ in allp], [e for _, e in allp], None))
    t3 = pick_stats(None, [p for p, _ in picks], [e for _, e in picks], None)
    print("  picked:      %s" % t3)

    build = all(t.get("coins", 0) >= 30 and t["win"] >= 60 and t["avg"] > 0 for t in (t2, t3)) and t2["ci"][0] > 0
    print("\nDECISION: %s" % ("BUILD IN as a radar filter" if build else "not a filter; see test 1 for SHOW ONLY"))


if __name__ == "__main__":
    main()
