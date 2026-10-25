#!/usr/bin/env python3
"""check_pickfilters.py: the verdict of PREREG-PICKFILTERS-2026-10-25.md (two Pick buy filters on the real Pick trades).

usage: python3 research/pickfilters/check_pickfilters.py <results dir> [--since ISO] [--until ISO] [--closed-by ISO] [--all-rules]
  <results dir> holds db/memepos and db/memeexit (git archive origin/results | tar -x -C <dir>)
  the defaults are the pre-registered window; other dates (and --all-rules for the v2 trades too) are a dry run only
"""
import argparse, datetime as dt, glob, json, os, random

TICKET, COST, COOL_H, B, SEED = 50.0, 0.75, 6.0, 10_000, 7
V3 = "v3: top 50 / chart exit: -50% floor, trail 15% from 1.5x, -15% in 30 min, 11x, 6h"
DROP_TIERS = ("risky", "fallback")


def ms(iso):
    return int(dt.datetime.fromisoformat(iso).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def trades(d, since, until, closed_by, all_rules=False):
    pos = {}
    for f in glob.glob(os.path.join(d, "db", "memepos", "*.json")):
        p = json.load(open(f))
        if p.get("grp") == "hold":
            pos[os.path.basename(f)[:-5]] = p
    sales = {}
    for f in glob.glob(os.path.join(d, "db", "memeexit", "*.json")):
        e = json.load(open(f))
        sales.setdefault(e.get("pos"), []).append(e)
    out = []
    for pid, p in pos.items():
        ex = sales.get(pid, [])
        if not ex or sum(float(e.get("frac") or 1.0) for e in ex) < 0.99:
            continue
        end = max(int(e.get("at") or e["t"]) for e in ex)
        out.append({"pid": pid, "addr": p.get("addr"), "t": int(p["t"]), "end": end, "tier": p.get("tier"), "paper": p.get("paper"),
                    "pnl": sum(float(e.get("eur") or 0.0) for e in ex) - float(p.get("ticket") or TICKET)})
    allt = sorted(out, key=lambda r: r["t"])
    for r in allt:   # F1 looks at every earlier Pick sale of the coin, also one before the window
        r["rebuy"] = any(o["addr"] == r["addr"] and o["t"] < r["t"] and r["t"] - COOL_H * 3_600_000 <= o["end"] <= r["t"] for o in allt)
    return [r for r in allt if since <= r["t"] < until and r["end"] <= closed_by and (all_rules or r["paper"] == V3)]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def diff_p(kept, dropped, rng):
    """one-sided bootstrap: the share of re-draws where mean(kept) - mean(dropped) <= 0, and the 5 % lower bound"""
    ds = sorted(mean([rng.choice(kept) for _ in kept]) - mean([rng.choice(dropped) for _ in dropped]) for _ in range(B))
    return sum(1 for x in ds if x <= 0) / B, ds[int(0.05 * B)]


def bar(xs, rng):
    """the PR #39 bar on the kept trades"""
    if len(xs) < 40:
        return False, "only %d trades (40 needed)" % len(xs)
    m = mean(xs) - COST
    lo = sorted(mean([rng.choice(xs) for _ in xs]) for _ in range(B))[int(0.01 * B)] - COST
    nob = (sum(xs) - max(xs)) / (len(xs) - 1) - COST
    ok = m > 0 and lo > 0 and nob > 0
    return ok, "mean after costs %+.2f, 1%% bound %+.2f, without the best trade %+.2f" % (m, lo, nob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--since", default="2026-10-26T00:00:00")
    ap.add_argument("--until", default="2026-11-22T00:00:00")
    ap.add_argument("--closed-by", default="2026-11-22T12:00:00")
    ap.add_argument("--all-rules", action="store_true")
    a = ap.parse_args()
    rows = trades(a.dir, ms(a.since), ms(a.until), ms(a.closed_by), a.all_rules)
    print("%d closed Pick trades, %+.2f per trade" % (len(rows), mean([r["pnl"] for r in rows])))
    res = []
    for name, drop in (("F1 no quick re-buy", lambda r: r["rebuy"]), ("F2 gates only", lambda r: r["tier"] in DROP_TIERS)):
        rng = random.Random(SEED)
        kept = [r["pnl"] for r in rows if not drop(r)]
        dropped = [r["pnl"] for r in rows if drop(r)]
        if len(kept) < 40 or len(dropped) < 20:
            res.append((name, None, None, kept, dropped))
            continue
        p, lo = diff_p(kept, dropped, rng)
        res.append((name, p, lo, kept, dropped))
    ps = sorted(r[1] for r in res if r[1] is not None)
    for name, p, lo, kept, dropped in res:
        head = "%s: kept %d (%+.2f), dropped %d (%+.2f)" % (name, len(kept), mean(kept), len(dropped), mean(dropped))
        if p is None:
            print(head + " -> too few trades, no verdict")
            continue
        alpha = 0.025 if p == ps[0] and len(ps) == 2 else 0.05
        better = p < alpha and (len(ps) < 2 or p == ps[0] or ps[0] < 0.025)
        ok, txt = bar(kept, random.Random(SEED))
        verdict = "worth switching on" if better and ok else ("better than the Pick, but fails the bar" if better else "not proven")
        print(head + " -> p %.4f, 5%% bound of the difference %+.2f; %s; %s" % (p, lo, txt, verdict))


if __name__ == "__main__":
    main()
