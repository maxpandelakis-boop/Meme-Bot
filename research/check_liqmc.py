"""Forward check of the 2h profile's liquidity-share veto (GATE_MAX_LIQMC, research/STUDY-2026-10-21.md), written before its data.
usage: python3 -I research/check_liqmc.py <data dir with memesnapres/> [from UTC ms] [to UTC ms]

Population: the coins the gate without the veto passes (the pass flag, or "liqmc" as the only why tag once the veto is on),
FluxBeam-like pools (liquidity 0.9 to 1.1 times the market cap) left out, scans from FROM (default 2026-10-20 04:00 UTC, right
after the study's hidden days) to TO. Vetoed: liquidity at 20% of the market cap or more. Counted per coin, because the bot
buys a coin once while the big test lists it in every scan. The veto stays only if both hold, with at least 20 vetoed coins:
  (a) the vetoed coins average worse per 20 than the kept ones (each coin's mean over its scans);
  (b) the bot's top pick by score averages at least as well with the veto as without it.
Printed beside it, not part of the verdict: the rows, both halves and the share that went to zero (98% down or more). That
share is no test of this veto: per coin it was lower for the vetoed coins on the study's discovery days.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

FROM = 1792468800000   # 2026-10-20 04:00 UTC
VETO = 0.20


def liqmc(r):
    return r["liq"] / r["mc"] if r["liq"] and r["mc"] else None


def in_pop(r):
    lm = liqmc(r)
    return (r["pass"] or r["why"] == ["liqmc"]) and not (lm is not None and 0.9 <= lm <= 1.1)


def vetoed(r):
    lm = liqmc(r)
    return lm is not None and lm >= VETO


def per_coin(rows):
    by = {}
    for r in rows:
        by.setdefault(r["a"], []).append(r)
    means = [sum(x["eur"] for x in v) / len(v) for v in by.values()]
    zero = sum(1 for v in by.values() if any(x["gone"] for x in v))
    return {"coins": len(by), "avg": round(sum(means) / len(means), 2) if means else None, "zero": round(100.0 * zero / len(by), 1) if by else None}


def main():
    a = sys.argv[1:]
    lo = int(a[1]) if len(a) > 1 else FROM
    hi = int(a[2]) if len(a) > 2 else 10 ** 15
    rows, scans = H.load(os.path.join(a[0], "memesnapres"), rule="m9-2h")
    rows = [r for r in rows if lo <= r["scan"] < hi and in_pop(r)]
    scans = sorted({r["scan"] for r in rows})
    if not scans:
        print("no scans in the window")
        return
    print("scans %d, %s to %s UTC" % (len(scans), H.ts(scans[0]), H.ts(scans[-1])))
    v, k = [r for r in rows if vetoed(r)], [r for r in rows if not vetoed(r)]
    cv, ck = per_coin(v), per_coin(k)
    print("per coin  vetoed %s | kept %s" % (cv, ck))
    print("per row   vetoed %s | kept %s" % (H.stats(v), H.stats(k)))
    mid = scans[len(scans) // 2]
    for name, part in (("first half", lambda r: r["scan"] < mid), ("second half", lambda r: r["scan"] >= mid)):
        print("%-11s vetoed %s | kept %s" % (name, per_coin([r for r in v if part(r)]), per_coin([r for r in k if part(r)])))
    groups = H.by_scan(rows)
    top = lambda g: max(g, key=lambda r: r["sc"] or 0)
    t_all = [top(g) for g in groups.values()]
    t_kept = [top([r for r in g if not vetoed(r)]) for g in groups.values() if any(not vetoed(r) for r in g)]
    s_all, s_kept = H.stats(t_all), H.stats(t_kept)
    print("top pick  without the veto %s | with it %s (changed in %d of %d scans)" % (s_all, s_kept, sum(1 for x in t_all if vetoed(x)), len(t_all)))
    why = "vetoed coins average %s against %s per coin; top pick %s with the veto against %s without" % (cv["avg"], ck["avg"], s_kept["avg"], s_all["avg"])
    if cv["coins"] < 20:
        print("VERDICT: too few vetoed coins (%d of 20); run again a week later" % cv["coins"])
    elif cv["avg"] < ck["avg"] and s_kept["avg"] >= s_all["avg"]:
        print("VERDICT: the veto stays (%s)" % why)
    else:
        print("VERDICT: the veto comes out (%s)" % why)


if __name__ == "__main__":
    main()
