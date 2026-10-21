"""The pre-registered check of research/PREREG-GATES-2026-10-21.md (fake money only): each 2h gate's lone vetoes against the gate's
passers on the June/July 2026 rows of the branch "history" (research/history_build.py). Written before those rows were split.
usage: python3 research/check_history_gates.py <dir with postgard_hourly.parquet>     (needs pandas and pyarrow)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memebot as M
from check_history_veto import outcome, boot

MARGIN = -1.00       # REMOVE needs the interval's low end above this (per 20)
ZERO_PTS = 5.0       # and the vetoed coins' zero share at most this many points over the kept coins'
MIN_COINS = 20


def ok(v):
    return v is not None and v == v


def fails(r):
    """The gates of the list a row fails, None when the row is outside the tested population (no data, FluxBeam-like, or a
    liq/young fail, which are not tested). Ages 24 to 48 h fail only "old"."""
    mc, liq, vol = r["market_cap_usd"], r["liquidity_usd"], r["volume_24h"]
    if not (ok(mc) and ok(liq) and ok(vol)) or mc <= 0 or not ok(r["age_h"]):
        return None
    if 0.9 <= liq / mc <= 1.1 or liq < 15_000 or r["age_h"] < 6.0 or r["age_h"] > 48.0:
        return None
    c1, c6, c24 = r["price_change_1h"], r["price_change_6h"], r["price_change_24h"]
    out = set()
    if r["age_h"] > 24.0:
        out.add("old")
    if not (100_000 <= mc <= 2_000_000):
        out.add("mc")
    if vol < 15_000:
        out.add("vol")
    if (ok(c1) and c1 <= -10) or (ok(c6) and c6 <= -50) or (ok(c24) and c24 <= -70):
        out.add("crash")
    if (ok(c1) and c1 >= 200) or (ok(c6) and c6 >= 90):
        out.add("spike")
    if vol / mc > M.GATE_MAX_VOLMC:
        out.add("wash")
    return out


def coins(rows):
    by = {}
    for r in rows:
        by.setdefault(r["mint"], []).append(r)
    return {a: (sum(x["eur"] for x in v) / len(v), any(x["zero"] for x in v)) for a, v in by.items()}


def line(name, rows):
    c = coins(rows)
    n = len(c)
    return "%-28s rows %5d coins %4d per coin %s per row %s zero (coins) %s" % (
        name, len(rows), n, ("%.3f" % (sum(v[0] for v in c.values()) / n)) if n else "-",
        ("%.3f" % (sum(r["eur"] for r in rows) / len(rows))) if rows else "-", ("%.1f%%" % (100.0 * sum(v[1] for v in c.values()) / n)) if n else "-")


def main():
    import pandas as pd
    df = pd.read_parquet(os.path.join(sys.argv[1], "postgard_hourly.parquet"))
    rows = []
    for r in df.to_dict("records"):
        g = fails(r)
        if g is None:
            continue
        o = outcome(r)
        if o is None:
            continue
        r["eur"], r["zero"], r["g"] = o[0], o[1], g
        rows.append(r)
    kept = [r for r in rows if not r["g"]]
    ts = sorted(r["ts"] for r in rows)
    mid = ts[len(ts) // 2]
    print("population: %d rows (%d kept), %s to %s UTC" % (len(rows), len(kept), pd.to_datetime(ts[0], unit="ms"), pd.to_datetime(ts[-1], unit="ms")))
    print(line("kept (base rate)", kept))
    ck = coins(kept)
    for gate in ("crash", "spike", "wash", "mc", "vol", "old"):
        vet = [r for r in rows if r["g"] == {gate}]
        print(line("%s vetoed alone" % gate, vet))
        for name, part in (("first half", lambda r: r["ts"] < mid), ("second half", lambda r: r["ts"] >= mid)):
            print("  " + line("%s %s" % (gate, name), [r for r in vet if part(r)]) + " | kept: " + line("", [r for r in kept if part(r)]).strip())
        cv = coins(vet)
        if len(cv) < MIN_COINS:
            print("  %s: UNDECIDED, KEEP (only %d vetoed coins)" % (gate, len(cv)))
            continue
        a = sum(v[0] for v in cv.values()) / len(cv)
        b = sum(v[0] for v in ck.values()) / len(ck)
        lo, hi = boot([v[0] for v in cv.values()], [v[0] for v in ck.values()])
        za = 100.0 * sum(v[1] for v in cv.values()) / len(cv)
        zb = 100.0 * sum(v[1] for v in ck.values()) / len(ck)
        remove = lo > MARGIN and za <= zb + ZERO_PTS
        print("  %s: %s. vetoed %.3f against kept %.3f per coin (difference %.3f, 95%% interval %s to %s; %d against %d coins; zero %.1f%% against %.1f%%)"
              % (gate, "REMOVE" if remove else "KEEP", a, b, a - b, lo, hi, len(cv), len(ck), za, zb))


if __name__ == "__main__":
    main()
