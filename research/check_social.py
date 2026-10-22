#!/usr/bin/env python3
"""The social-signal check of research/PREREG-SOCIAL-2026-10-21.md (fake money only).

usage: python3 -I research/check_social.py <memesnapres dir> [--speed]   (--speed: part 2, the pump.fun comment speed)
"""
import os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

CUT = 1792022400000   # 2026-10-14 00:00 UTC: fit half before, check half from
REPLIES_MIN = 422.0   # top 30% of pf.replies on the fit half
TRENDS = ("jup:trending1h", "jup:trending", "gt:trending1h", "gt:trending")
BOOSTS = ("list:boostTop", "list:boostLatest")


def net(mult, fee=0.01):
    return H.clamp(20.0 * (1 - fee) * (1 - fee) * mult - 20.0, *H.EUR_CLIP)


def on(f, k):
    return (f.get(k) or 0) > 0


SIGNALS = {   # id -> (row -> True/False/None); None: not known for this row, left out of the test
    "x": lambda r: on(r["f"], "x"),
    "web": lambda r: on(r["f"], "web"),
    "tweet": lambda r: on(r["f"], "vt.tweet"),
    "tg": lambda r: None if r["f"].get("pf.telegram") is None else on(r["f"], "pf.telegram"),
    "replies": lambda r: None if r["f"].get("pf.replies") is None else r["f"]["pf.replies"] >= REPLIES_MIN,
    "boost": lambda r: on(r["f"], "boosts") or any(s in BOOSTS for s in r["src"]),
    "paid": lambda r: None if r["f"].get("ds.paid") is None else on(r["f"], "ds.paid"),
    "news": lambda r: on(r["f"], "news.hits"),
    "reddit": lambda r: on(r["f"], "rd.posts"),
    "kw": lambda r: on(r["f"], "kwN"),
    "trend": lambda r: any(s in TRENDS for s in r["src"]),
}


def count(r):
    return sum(1 for g in SIGNALS.values() if g(r))


def first_per_coin(rows):
    out = {}
    for r in sorted(rows, key=lambda r: r["scan"]):
        out.setdefault(r["a"], r)
    return list(out.values())


def stats(rs, fee=0.01):
    n = len(rs)
    if not n:
        return {"n": 0}
    v = [net(r["mult"], fee) for r in rs]
    return {"n": n, "avg": sum(v) / n, "zero": sum(r["gone"] for r in rs) / n, "x3": sum(r["mult"] >= 3 for r in rs) / n}


def diff_ci(a, b, seed=7, draws=1000):
    if len(a) < 5 or len(b) < 5:
        return None
    va, vb = [net(r["mult"]) for r in a], [net(r["mult"]) for r in b]
    rnd, d = random.Random(seed), []
    for _ in range(draws):
        sa = [va[rnd.randrange(len(va))] for _ in va]
        sb = [vb[rnd.randrange(len(vb))] for _ in vb]
        d.append(sum(sa) / len(sa) - sum(sb) / len(sb))
    d.sort()
    return d[int(0.025 * draws)], d[int(0.975 * draws)]


def split(rs, g):
    yes, no = [], []
    for r in rs:
        s = g(r)
        if s is None:
            continue
        (yes if s else no).append(r)
    return yes, no


def fmt(s):
    if not s.get("n"):
        return "n 0"
    return "n %5d  avg %+6.2f  zero %5.1f%%  3x %4.1f%%" % (s["n"], s["avg"], 100 * s["zero"], 100 * s["x3"])


def pct(vals, q):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))]


def speed_signals(rows):
    """Part 2: the cut between the halves and the signals, fixed on the fit half (research/PREREG-SOCIAL-2026-10-21.md)."""
    rows = [r for r in rows if r["f"].get("pc.n1h") is not None]
    if not rows:
        print("no row carries pc.n1h: the comment-speed logger read nothing (pump.fun blocked?)")
        sys.exit(0)
    cut = sorted(r["scan"] for r in rows)[len(rows) // 2]
    fit = [r for r in rows if r["scan"] < cut]
    n1 = pct([r["f"]["pc.n1h"] for r in fit], 0.7) if fit else 0
    u1 = pct([r["f"].get("pc.users1h") or 0 for r in fit], 0.7) if fit else 0
    print("part 2: cut %d, speed >= %s replies/h, people >= %s commenters/h" % (cut, n1, u1))
    return rows, cut, {"speed": lambda r: r["f"]["pc.n1h"] >= n1, "people": lambda r: (r["f"].get("pc.users1h") or 0) >= u1,
                       "fresh": lambda r: None if r["f"].get("pc.newestMin") is None else r["f"]["pc.newestMin"] <= 10}


def main(d, speed=False):
    rows, _ = H.load(d, rule="m9-2h")
    cut, signals = CUT, SIGNALS
    if speed:
        rows, cut, signals = speed_signals(rows)
    halves = {"fit": [r for r in rows if r["scan"] < cut], "check": [r for r in rows if r["scan"] >= cut]}
    if speed and min(len(first_per_coin(rs)) for rs in halves.values()) < 300:
        print("not enough data yet: %s coins per half (300 needed)" % [len(first_per_coin(rs)) for rs in halves.values()])
        return
    groups = {h: {"all": first_per_coin(rs), "pass": first_per_coin([r for r in rs if r["pass"]])} for h, rs in halves.items()}
    # K for the count signal: best average on the fit half, all coins
    best = 0 if speed else max(range(1, 7), key=lambda k: (stats(split(groups["fit"]["all"], lambda r: count(r) >= k)[0]).get("avg", -99)
                                           if len(split(groups["fit"]["all"], lambda r: count(r) >= k)[0]) >= 100 else -99))
    sig = signals if speed else dict(SIGNALS, count=lambda r: count(r) >= best)
    if not speed:
        print("count signal: K =", best, "(chosen on the fit half)")
    res = {}
    for h in ("fit", "check"):
        print("\n=== %s half ===" % h)
        for grp in ("all", "pass"):
            base = groups[h][grp]
            print("-- %s: base %s | fee 1%%/side %+.2f, 0.5%%/side %+.2f, 1.5%%/side %+.2f" % (
                grp, fmt(stats(base)), stats(base)["avg"], stats(base, 0.005)["avg"], stats(base, 0.015)["avg"]))
            for name, g in sig.items():
                yes, no = split(base, g)
                ci = diff_ci(yes, no)
                res[(h, grp, name)] = (stats(yes), stats(no), ci)
                print("  %-8s ON  %s | OFF %s | diff ci %s" % (name, fmt(stats(yes)), fmt(stats(no)),
                                                               "-" if ci is None else "%+.2f..%+.2f" % ci))
    print("\n=== verdict (pre-registered) ===")
    for name in sig:
        fy, fn, fci = res[("fit", "all", name)]
        cy, cn, cci = res[("check", "all", name)]
        py, pn, _ = res[("check", "pass", name)]
        buy = (cci and cci[0] > 0 and fy.get("avg", 0) > fn.get("avg", 0) and py.get("n") and py["avg"] > 0
               and cy.get("x3", 0) >= cn.get("x3", 0))
        veto_on = fci and cci and fci[1] < 0 and cci[1] < 0     # "on" is worse on both halves
        veto_off = fci and cci and fci[0] > 0 and cci[0] > 0    # "off" is worse on both halves
        verdict = "BUY SIGNAL" if buy else "VETO when on" if veto_on else "VETO when off" if veto_off else "nothing"
        if veto_on or veto_off:   # keeping the better side must not lower the 3x share of the passers
            keep = pn if veto_on else py
            allp = stats(groups["check"]["pass"])
            if keep.get("n", 0) and keep["x3"] < allp["x3"]:
                verdict += " (fails: fewer 3x among passers kept, %.1f%% vs %.1f%%)" % (100 * keep["x3"], 100 * allp["x3"])
        print("  %-8s %s" % (name, verdict))


if __name__ == "__main__":
    main(sys.argv[1], speed="--speed" in sys.argv[2:])
