"""The pre-registered check of research/PREREG-DESK-2026-11-11.md (fake money only): the Trencher Trading Desk's sell rules
(hard stop -8% until 2x, half at 2x, the rest trailing 10% off the high) replayed on the stored candle paths of the bot's tips
(memerec) and new launches (memeyoung), against hold-to-end, the live paper rule (-30% / +1000%) and a 20% trailing stop.
Triggers and fills as research/check_exits.py: minute closes from tpFrom on, a stop fills at min(level, close).

usage: git archive origin/results db/memerec db/memeyoung | tar -x -C /tmp/res && python3 -I research/check_desk.py /tmp/res
"""
import glob, json, os, random, sys
from collections import defaultdict


def fee(x, fmin, pct=0.005):
    return max(fmin, pct * x)


def sales_net(sales, ticket, fmin):
    """sales: [(share of the position, multiple)] -> net result of a ticket after the buy fee and each sale's fee."""
    inv = ticket - fee(ticket, fmin)
    got = 0.0
    for share, m in sales:
        g = inv * share * m
        got += max(0.0, g - fee(g, fmin)) if g > 0 else 0.0
    return got - ticket


def desk(path, end, start, stop=0.08, half_at=2.0, trail=0.10):
    """-> [(share, multiple)] the desk rule sold at."""
    half, peak, left, sales = False, 1.0, 1.0, []
    for minute, op, hi, lo, close in path:
        if minute < start:
            continue
        if not half:
            if close <= 1.0 - stop:
                return sales + [(left, min(1.0 - stop, close))]
            if close >= half_at:
                share = 1.0 / half_at
                sales.append((share, half_at)); left -= share; half = True
                peak = max(peak, close)
                continue
        else:
            lvl = peak * (1.0 - trail)
            if close <= lvl:
                return sales + [(left, min(lvl, close))]
        peak = max(peak, close)
    return sales + [(left, end)]


def simple(path, end, start, tp=None, sl=None, trail=None):
    peak = 1.0
    for minute, op, hi, lo, close in path:
        if minute < start:
            continue
        lvl = None
        if sl is not None:
            lvl = 1.0 - sl
        if trail is not None:
            t = peak * (1.0 - trail)
            lvl = t if lvl is None else max(lvl, t)
        if lvl is not None and close <= lvl:
            return [(1.0, min(lvl, close))]
        if tp is not None and close >= 1.0 + tp:
            return [(1.0, 1.0 + tp)]
        peak = max(peak, close)
    return [(1.0, end)]


RULES = [("DESK (-8% until 2x, half at 2x, trail 10%)", lambda o: desk(o["path"], o["mult"], o["tpFrom"])),
         ("hold to the end", lambda o: simple(o["path"], o["mult"], o["tpFrom"])),
         ("live rule -30% / +1000%", lambda o: simple(o["path"], o["mult"], o["tpFrom"], tp=10.0, sl=0.3)),
         ("trailing stop 20%", lambda o: simple(o["path"], o["mult"], o["tpFrom"], trail=0.2))]


def rows(root, coll):
    out = []
    for fn in sorted(glob.glob(os.path.join(root, "db", coll, "*.json"))):
        try:
            doc = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = int(doc.get("t") or 0)
        picks = doc.get("picks") or []
        outs = doc.get("outs") if isinstance(doc.get("outs"), dict) else {}
        for key, res in outs.items():
            for i, o in enumerate((res or {}).get("picks") or []):
                if isinstance(o, dict) and isinstance(o.get("path"), list) and o["path"] and isinstance(o.get("mult"), (int, float)) \
                        and (o.get("cv") or 0) >= 2 and isinstance(o.get("tpFrom"), (int, float)) \
                        and all(isinstance(c, list) and len(c) == 5 for c in o["path"]):
                    addr = picks[i].get("addr") if i < len(picks) and isinstance(picks[i], dict) else o.get("sym")
                    out.append({"key": key, "t": t, "day": t // 86400000, "addr": addr, "sym": o.get("sym"), "o": o})
    return out


def boot_by_day(vals_by_day, n=2000, seed=11):
    days = sorted(vals_by_day)
    if not days:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        s, k = 0.0, 0
        for _ in days:
            v = vals_by_day[rng.choice(days)]
            s += sum(v); k += len(v)
        means.append(s / k if k else 0.0)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summary(sel, f, ticket, fmin):
    by_day = defaultdict(list)
    for r in sel:
        by_day[r["day"]].append(f(r))
    allv = [x for v in by_day.values() for x in v]
    if not allv:
        return None
    lo, hi = boot_by_day(by_day)
    pos_days = sum(1 for v in by_day.values() if sum(v) > 0)
    return {"n": len(allv), "avg": sum(allv) / len(allv), "ci": (lo, hi), "win": sum(1 for x in allv if x > 0) / len(allv),
            "days": len(by_day), "pos_days": pos_days}


def fmt(s):
    return "n %4d  avg %+6.2f  95%% %+6.2f..%+6.2f  in profit %4.1f%%  days %d (%d positive)" % (
        s["n"], s["avg"], s["ci"][0], s["ci"][1], 100 * s["win"], s["days"], s["pos_days"])


def main(root):
    for coll in ("memerec", "memeyoung"):
        allrows = rows(root, coll)
        for key in ("24", "1"):
            sel = [r for r in allrows if r["key"] == key]
            if not sel:
                continue
            days = sorted({r["day"] for r in sel})
            cut = days[len(days) - max(1, len(days) // 3)]
            print("\n== %s, %s h window: %d results, %d coins, days %d (holdout from day index %d)" % (
                coll, key, len(sel), len({r["addr"] for r in sel}), len(days), len(days) - max(1, len(days) // 3)))
            for ticket, fmin in ((20.0, 0.81), (8.0, 0.50)):
                print("  ticket %.0f, min fee %.2f" % (ticket, fmin))
                nets = {name: (lambda rr, rule=rule: sales_net(rule(rr["o"]), ticket, fmin)) for name, rule in RULES}
                for name, f in nets.items():
                    print("    %-44s %s" % (name, fmt(summary(sel, f, ticket, fmin))))
                d = nets[RULES[0][0]]
                for name, f in list(nets.items())[1:]:
                    s = summary(sel, lambda r, f=f: d(r) - f(r), ticket, fmin)
                    print("    DESK minus %-33s avg %+6.2f  95%% %+6.2f..%+6.2f" % (name, s["avg"], s["ci"][0], s["ci"][1]))
                if ticket == 20.0:
                    old = [r for r in sel if r["day"] < cut]
                    new = [r for r in sel if r["day"] >= cut]
                    for lab, part in (("older two thirds", old), ("HOLDOUT newest third", new)):
                        s = summary(part, d, ticket, fmin)
                        if s:
                            print("    DESK %-39s %s" % (lab, fmt(s)))
                    vals = sorted(((d(r), r) for r in sel), key=lambda x: -x[0])
                    rest = [r for _, r in vals[1:]]
                    print("    DESK without the best tip (%s %+.2f)          %s" % (vals[0][1]["sym"], vals[0][0], fmt(summary(rest, d, ticket, fmin))))
                    first, seen = [], set()
                    for r in sorted(sel, key=lambda r: r["t"]):
                        if r["addr"] not in seen:
                            seen.add(r["addr"]); first.append(r)
                    print("    DESK one tip per coin (the first)          %s" % fmt(summary(first, d, ticket, fmin)))
                    exits = defaultdict(int)
                    for r in sel:
                        s = desk(r["o"]["path"], r["o"]["mult"], r["o"]["tpFrom"])
                        exits["half at 2x" if len(s) > 1 else "stop -8%" if s[0][1] <= 0.92 and s[0][1] != r["o"]["mult"] else "window end"] += 1
                    print("    how DESK ended: %s" % dict(exits))


if __name__ == "__main__":
    main(sys.argv[1])
