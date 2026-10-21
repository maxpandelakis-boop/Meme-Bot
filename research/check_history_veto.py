"""The pre-registered check of research/PREREG-HISTORY-2026-10-21.md (fake money only): the liquidity-share veto on the June/July
2026 rows of the branch "history" (research/history_build.py). Written before those rows were looked at.
usage: python3 research/check_history_veto.py <dir with postgard_hourly.parquet>     (needs pandas and pyarrow)
"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memebot as M

VETO = 0.20
MC_FLOOR = 200_000.0


def gate(r):
    mc, liq, vol = r["market_cap_usd"], r["liquidity_usd"], r["volume_24h"]
    c1, c6, c24 = r["price_change_1h"], r["price_change_6h"], r["price_change_24h"]
    num = lambda v: v is not None and v == v
    if not (6.0 <= r["age_h"] <= 24.0) or not (num(mc) and num(liq) and num(vol)):
        return False
    if not (100_000 <= mc <= 2_000_000) or liq < 15_000 or vol < 15_000:
        return False
    if (num(c1) and c1 <= -10) or (num(c6) and c6 <= -50) or (num(c24) and c24 <= -70):
        return False
    if (num(c1) and c1 >= 200) or (num(c6) and c6 >= 90):
        return False
    return not (0.9 <= liq / mc <= 1.1)


def outcome(r):
    """-> (eur per 20 after fees, clipped; went to zero) or None when nothing is known at the check."""
    if r["rug_by_1"]:
        return -20.0, True
    p0, p1 = r["price_usd"], r["px1"]
    if p1 is None or p1 != p1 or not p0:
        return None
    m = p1 / p0
    if m < 0.02:
        return -20.0, True
    return M.clamp(M.tip_net(m), M.EUR_CLIP[0], M.EUR_CLIP[1]), False


def per_coin(rows):
    by = {}
    for r in rows:
        by.setdefault(r["mint"], []).append(r["eur"])
    return {a: sum(v) / len(v) for a, v in by.items()}


def summary(rows):
    pc = per_coin(rows)
    n = len(rows)
    return {"rows": n, "coins": len(pc), "avg_row": round(sum(r["eur"] for r in rows) / n, 3) if n else None,
            "avg_coin": round(sum(pc.values()) / len(pc), 3) if pc else None,
            "zero_row_pct": round(100.0 * sum(r["zero"] for r in rows) / n, 2) if n else None}


def boot(a, b, n=2000, seed=7):
    """95% interval of mean(a) - mean(b), coins resampled within each side."""
    rng = random.Random(seed)
    a, b = list(a), list(b)
    d = []
    for _ in range(n):
        sa = [a[rng.randrange(len(a))] for _ in a]
        sb = [b[rng.randrange(len(b))] for _ in b]
        d.append(sum(sa) / len(sa) - sum(sb) / len(sb))
    d.sort()
    return round(d[int(0.025 * n)], 3), round(d[int(0.975 * n) - 1], 3)


def split(rows, name, test):
    a = [r for r in rows if test(r)]
    b = [r for r in rows if not test(r)]
    ca, cb = per_coin(a), per_coin(b)
    print("%-26s %s | rest %s" % (name, summary(a), summary(b)))
    return ca, cb


def main():
    import pandas as pd
    df = pd.read_parquet(os.path.join(sys.argv[1], "postgard_hourly.parquet"))
    rows = []
    for r in df.to_dict("records"):
        if not gate(r):
            continue
        o = outcome(r)
        if o is None:
            continue
        r["eur"], r["zero"] = o
        r["liqmc"] = r["liquidity_usd"] / r["market_cap_usd"]
        rows.append(r)
    if not rows:
        print("no rows in the population")
        return
    ts = sorted(r["ts"] for r in rows)
    mid = ts[len(ts) // 2]
    print("population: %d rows, %d coins, %s to %s UTC (median %s)" % (len(rows), len({r["mint"] for r in rows}),
          pd.to_datetime(ts[0], unit="ms"), pd.to_datetime(ts[-1], unit="ms"), pd.to_datetime(mid, unit="ms")))
    print("all (base rate)            %s" % summary(rows))
    cv, ck = split(rows, "vetoed (liq/mc >= 0.20)", lambda r: r["liqmc"] >= VETO)
    for name, part in (("first half", lambda r: r["ts"] < mid), ("second half", lambda r: r["ts"] >= mid)):
        sub = [r for r in rows if part(r)]
        split(sub, "  %s vetoed" % name, lambda r: r["liqmc"] >= VETO)
    week = lambda r: pd.to_datetime(r["ts"], unit="ms").strftime("%G-W%V")
    for w in sorted({week(r) for r in rows}):
        sub = [r for r in rows if week(r) == w]
        split(sub, "  week %s vetoed" % w, lambda r: r["liqmc"] >= VETO)
    split(rows, "mc under $200k (floor)", lambda r: r["market_cap_usd"] < MC_FLOOR)
    # the paper account's exits from the 6-hour path, baseline only: -30% stop, 11x, else the last price within 6 hours
    pe = []
    for r in rows:
        s, t = r.get("stop30_min"), r.get("tp11_min")
        if r.get("rug_ms") and r["rug_ms"] <= r["ts"] + 6 * 3_600_000 and not (t == t and t is not None):
            m = 0.0
        elif s is not None and s == s and (t is None or t != t or s <= t):
            m = min(r["stop30_x"], 0.70)
        elif t is not None and t == t:
            m = 11.0
        else:
            m = r["last6"] if r["last6"] == r["last6"] else None
        if m is not None:
            pe.append(M.tip_net(m))
    if pe:
        print("paper exits (stop -30%%, 11x, 6 h) on the same rows: %d rows, avg %.3f per 20" % (len(pe), sum(pe) / len(pe)))
    # H1, the deciding test
    if len(cv) < 20:
        print("H1: UNDECIDED, only %d vetoed coins (20 needed)" % len(cv))
        return
    a, b = sum(cv.values()) / len(cv), sum(ck.values()) / len(ck)
    lo, hi = boot(cv.values(), ck.values())
    holds = a < b and hi < 0
    print("H1: %s. Vetoed coins %.3f against kept %.3f per 20 (difference %.3f, 95%% coin-bootstrap interval %s to %s; %d against %d coins)"
          % ("HOLDS" if holds else "FAILS", a, b, a - b, lo, hi, len(cv), len(ck)))


if __name__ == "__main__":
    main()
