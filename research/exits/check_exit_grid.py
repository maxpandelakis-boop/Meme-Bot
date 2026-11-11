"""The pre-registered exit grid of research/exits/PREREG-EXITS-2026-11-11.md (fake money only): 480 sell rules replayed on the
stored candle paths of the bot's tips (memerec) and new launches (memeyoung) at FOMO's fees; two picks chosen on the older two
thirds of the days, judged once on the newest third.

usage: git archive origin/results db/memerec db/memeyoung | tar -x -C /tmp/res && python3 -I research/exits/check_exit_grid.py /tmp/res
"""
import glob, itertools, json, os, random, sys
from collections import defaultdict

STOPS = [0.08, 0.15, 0.25, 0.40, None]
TPS = [None, ("back", 2.0), ("half", 1.5), ("half", 2.0), ("all", 1.2), ("all", 1.5), ("all", 2.0), ("all", 3.0)]
TRAILS = [None, 0.10, 0.20, 0.30]
HOURS = [1, 4, 24]
VARIANTS = list(itertools.product(STOPS, TPS, TRAILS, HOURS))
D = (0.08, ("back", 2.0), 0.10, 24)
HOLD = (None, None, None, 24)
SLIP = {"memerec": 0.005, "memeyoung": 0.01}


def fomo_fee(x):
    return 0.0 if x <= 0 else 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x


def name(v):
    s, tp, tr, h = v
    return "stop %s, %s, trail %s, %dh" % ("-%d%%" % round(100 * s) if s else "none",
                                             "no TP" if not tp else "%s at %.1fx" % (tp[0], tp[1]),
                                             "%d%%" % round(100 * tr) if tr else "none", h)


def parts(v):
    return sum(1 for x in v[:3] if x)


def replay(path, v, pess=False):
    """path: [[minute after entry, open, high, low, close, step]] from the entry on -> ([(share, multiple)], how it ended)."""
    stop, tp, trail, hours = v
    left, peak, sales, done_tp = 1.0, 1.0, [], False
    armed = trail is not None and not (tp and tp[0] in ("back", "half"))
    last = 1.0
    for minute, op, hi, lo, close, step in path:
        if minute > hours * 60:
            break
        last = close
        lvl = (1.0 - stop) if stop else None
        if armed:
            t = peak * (1.0 - trail)
            lvl = t if lvl is None else max(lvl, t)
        probe = lo if (pess and step > 1) else close
        if lvl is not None and probe <= lvl:
            why = "trail" if (armed and (not stop or lvl > 1.0 - stop + 1e-12)) else "stop"
            return sales + [(left, probe)], why
        if tp and not done_tp and close >= tp[1]:
            if tp[0] == "all":
                return sales + [(left, tp[1])], "take-profit"
            share = 0.5
            sales.append((share, tp[1])); left -= share; done_tp = True
            if trail is not None:
                armed = True
        peak = max(peak, close)
    return sales + [(left, last)], ("part + time" if done_tp else "time")


def net(sales, ticket, slip, fees=True):
    inv = ticket - (fomo_fee(ticket) if fees else 0.0)
    got = 0.0
    for share, m in sales:
        g = inv * share * m * (1 - slip) / (1 + slip)
        got += g - (min(fomo_fee(g), g) if fees else 0.0)
    return got - ticket


def load(root, coll):
    out = []
    for fn in sorted(glob.glob(os.path.join(root, "db", coll, "*.json"))):
        try:
            doc = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = int(doc.get("t") or 0)
        picks = doc.get("picks") or []
        outs = doc.get("outs") if isinstance(doc.get("outs"), dict) else {}
        r24 = ((outs.get("24") or {}).get("picks")) or []
        r1 = ((outs.get("1") or {}).get("picks")) or []
        for i, o in enumerate(r24):
            ok = lambda q: isinstance(q, dict) and isinstance(q.get("path"), list) and q["path"] and (q.get("cv") or 0) >= 2 \
                and isinstance(q.get("tpFrom"), (int, float)) and all(isinstance(c, list) and len(c) == 5 for c in q["path"])
            if not ok(o) or not isinstance(o.get("mult"), (int, float)):
                continue
            start = o["tpFrom"]
            path = []
            o1 = r1[i] if i < len(r1) else None
            if ok(o1) and o1.get("sym") == o.get("sym"):
                path = [[c[0] - start] + c[1:] + [1] for c in o1["path"] if c[0] >= start]
            cut = path[-1][0] + start if path else start - 1e-9
            path += [[c[0] - start] + c[1:] + [15] for c in o["path"] if c[0] > cut and c[0] >= start]
            if not path:
                continue
            addr = picks[i].get("addr") if i < len(picks) and isinstance(picks[i], dict) else o.get("sym")
            out.append({"day": t // 86400000, "t": t, "addr": addr, "sym": o.get("sym"), "path": path, "fine": sum(1 for c in path if c[5] == 1)})
    return out


def boot(by_day, n=2000, seed=11):
    days = sorted(by_day)
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        s, k = 0.0, 0
        for _ in days:
            v = by_day[rng.choice(days)]
            s += sum(v); k += len(v)
        means.append(s / k if k else 0.0)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summ(rows, vals):
    by = defaultdict(list)
    for r, x in zip(rows, vals):
        by[r["day"]].append(x)
    lo, hi = boot(by)
    return "n %4d  avg %+6.2f  95%% %+6.2f..%+6.2f  in profit %4.1f%%  days %d/%d positive" % (
        len(vals), sum(vals) / len(vals), lo, hi, 100 * sum(1 for x in vals if x > 0) / len(vals),
        sum(1 for v in by.values() if sum(v) > 0), len(by))


def main(root):
    for coll in ("memerec", "memeyoung"):
        rows = load(root, coll)
        slip = SLIP[coll]
        days = sorted({r["day"] for r in rows})
        k = max(1, len(days) // 3)
        cut = days[len(days) - k]
        dev = [r for r in rows if r["day"] < cut]
        hold = [r for r in rows if r["day"] >= cut]
        ddays = sorted({r["day"] for r in dev})
        b = [ddays[0], ddays[len(ddays) // 3], ddays[2 * len(ddays) // 3]]
        block = lambda r: 0 if r["day"] < b[1] else 1 if r["day"] < b[2] else 2
        print("\n==== %s: %d tips, %d coins, %d days; older days %d tips, holdout %d tips (%d days); one-minute candles per tip: median %d"
              % (coll, len(rows), len({r["addr"] for r in rows}), len(days), len(dev), len(hold), k,
                 sorted(r["fine"] for r in rows)[len(rows) // 2]))
        f = lambda r, v, ticket=8.0, fees=True, pess=False: net(replay(r["path"], v, pess)[0], ticket, slip if fees else 0.0, fees)
        table = []
        for v in VARIANTS:
            vals = [f(r, v) for r in dev]
            bl = [[], [], []]
            for r, x in zip(dev, vals):
                bl[block(r)].append(x)
            table.append((sum(vals) / len(vals), min(sum(x) / len(x) for x in bl if x), v))
        best_mean = max(table, key=lambda t: (round(t[0], 6), -parts(t[2])))[2]
        best_rob = max(table, key=lambda t: (round(t[1], 6), -parts(t[2])))[2]
        print("  older days, ticket 8 $: the 8 best by average of %d variants (%d with an average above 0)" % (len(table), sum(1 for t in table if t[0] > 0)))
        for m, w, v in sorted(table, key=lambda t: -t[0])[:8]:
            print("    %+6.2f  worst block %+6.2f  %s" % (m, w, name(v)))
        print("  older days: the 3 worst")
        for m, w, v in sorted(table, key=lambda t: t[0])[:3]:
            print("    %+6.2f  worst block %+6.2f  %s" % (m, w, name(v)))
        picks = [("MEAN pick", best_mean), ("ROBUST pick", best_rob), ("video rule D", D), ("hold 24 h", HOLD)]
        for lab, part in (("OLDER DAYS", dev), ("HOLDOUT", hold)):
            print("  -- %s, ticket 8 $ (per trade in $)" % lab)
            for pl, v in picks:
                print("    %-12s %-46s %s" % (pl, name(v), summ(part, [f(r, v) for r in part])))
        print("  -- HOLDOUT checks")
        dvals = [f(r, D) for r in hold]
        first = {}
        for r in sorted(hold, key=lambda r: r["t"]):
            first.setdefault(r["addr"], r)
        for pl, v in picks[:2]:
            vals = [f(r, v) for r in hold]
            print("    %s: %s" % (pl, name(v)))
            print("      minus video rule D            %s" % summ(hold, [a - c for a, c in zip(vals, dvals)]))
            i = max(range(len(vals)), key=lambda j: vals[j])
            rest = [x for j, x in enumerate(vals) if j != i]
            print("      without the best trade (%s %+.2f): avg %+6.2f" % (hold[i]["sym"], vals[i], sum(rest) / len(rest)))
            one = list(first.values())
            print("      one tip per coin              %s" % summ(one, [f(r, v) for r in one]))
            print("      ticket 20 $                   %s" % summ(hold, [f(r, v, 20.0) for r in hold]))
            print("      no fee, no slippage (8 $)     %s" % summ(hold, [f(r, v, 8.0, False) for r in hold]))
            print("      pessimistic fill              %s" % summ(hold, [f(r, v, 8.0, True, True) for r in hold]))
            ends = defaultdict(int)
            for r in hold:
                ends[replay(r["path"], v)[1]] += 1
            print("      how the trades ended: %s" % dict(ends))
            top = sorted(zip(vals, hold), key=lambda z: -z[0])[:10]
            print("      ten best: " + ", ".join("%s %+.2f" % (r["sym"], x) for x, r in top))
        hv = [f(r, HOLD, 8.0, False) for r in hold]
        print("    hold 24 h with no fee, no slippage: %s" % summ(hold, hv))
        print("    variants with a holdout average above 0 (information, not a pick): %d of %d" % (
            sum(1 for v in VARIANTS if sum(f(r, v) for r in hold) > 0), len(VARIANTS)))


if __name__ == "__main__":
    main(sys.argv[1])
