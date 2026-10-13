#!/usr/bin/env python3
"""Rug and winner study, step 5: simple additive trap points for the radar, fitted on the first half of the scans and checked on
the second half (L, S, E cohorts), the 'good coin' rule check, and the paper account's results by trap flag.
Usage: venv/bin/python -I points.py <out dir>  -> points.txt, points.json"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import Boot, pct, fx, auc

OUT = sys.argv[1]
REP = []
say = REP.append


def load(name):
    with open(os.path.join(OUT, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


L, S, P = load("listings"), load("snapyoung"), load("positions")
E = [r for r in L if r["inEarly"]]
PY = [r for r in P if r["grp"] == "young"]


def v(r, k):
    x = r["sig"].get(k)
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# the flags the radar can compute live (None = cannot tell for this coin)
FLAGS = {
    "instant_pool": ("pool opened < 60 s after the mint", lambda r: None if v(r, "instantPool") is None else v(r, "instantPool") == 1.0),
    "rugger_wallets": ("top holders' past coins average <= -7 per 20 (wallet memory) or 3+ holders in earlier rugs",
                       lambda r: None if (v(r, "sw.avg") is None and v(r, "own.holders_in_earlier_rug") is None) else
                       ((v(r, "sw.avg") is not None and v(r, "sw.avg") <= -7) or ((v(r, "own.holders_in_earlier_rug") or 0) >= 3))),
    "brand_name": ("named after a big brand / AI / celebrity", lambda r: v(r, "own.brand_name") == 1.0),
    "bot_volume": ("3000+ buys in its first hour", lambda r: None if v(r, "buys1") is None else v(r, "buys1") >= 3000),
    "pumping_5m": ("up 20%+ in the last 5 minutes", lambda r: None if v(r, "m5") is None else v(r, "m5") >= 20),
    "no_socials": ("no X, website or Telegram", lambda r: None if v(r, "socN") is None else v(r, "socN") <= 0),
    "holder_cluster": ("RugCheck: holder correlation or insider network", lambda r: None if not v(r, "rc.report") else v(r, "rcn.cluster_any") == 1.0),
    "creator_sold": ("creator already sold", lambda r: None if v(r, "dev.sold") is None else v(r, "dev.sold") > 0),
    "jup_organic_zero": ("Jupiter organic score 0", lambda r: None if v(r, "jup.organic") is None else v(r, "jup.organic") <= 0),
    "rc_danger": ("RugCheck danger flag", lambda r: None if not v(r, "rc.report") else v(r, "rcn.danger_any") == 1.0),
}
GOOD = {
    "x_and_paid": ("X link and a paid DexScreener profile", lambda r: v(r, "x") == 1.0 and v(r, "ds.paid") == 1.0),
    "tweet": ("launched off a tweet", lambda r: v(r, "vt.tweet") == 1.0),
    "lists3": ("on 3+ source lists", lambda r: (v(r, "srcN") or 0) >= 3),
}


def rr(rows, fn, y):
    a = [y(r) for r in rows if fn(r) is True and y(r) is not None]
    b = [y(r) for r in rows if fn(r) is False and y(r) is not None]
    if len(a) < 15 or len(b) < 15:
        return None, len(a)
    ra, rb = (sum(a) + 0.5) / (len(a) + 1), (sum(b) + 0.5) / (len(b) + 1)
    return ra / rb, len(a)


def fit_points(rows, y):
    pts = {}
    for k, (_, fn) in FLAGS.items():
        x, n = rr(rows, fn, y)
        pts[k] = 0 if x is None else max(0, min(4, round(2 * math.log(x))))      # 2 points per e-fold of the rug ratio, capped
    return pts


def score(r, pts):
    return sum(p for k, p in pts.items() if FLAGS[k][1](r) is True)


def evaluate(rows, pts, y, label):
    runs = sorted({r["rid"] for r in rows})
    bt = Boot([r["rid"] for r in rows])
    yy = [(score(r, pts), y(r)) for r in rows if y(r) is not None]
    a = auc([s for s, _ in yy], [t for _, t in yy])
    out = {"auc": a, "buckets": {}}
    say("  %s: AUC %s (n=%d)" % (label, fx(a, 3), len(yy)))
    for lo, hi, nm in ((0, 0, "0 points"), (1, 2, "1-2"), (3, 4, "3-4"), (5, 99, "5+")):
        n, k = bt.per_run(rows, lambda r, lo=lo, hi=hi: lo <= score(r, pts) <= hi, y)
        rt = bt.rate(n, k)
        out["buckets"][nm] = rt
        if rt:
            say("      %-9s %s of %d [%s-%s]" % (nm, pct(rt["rate"]), rt["n"], pct(rt["lo"]), pct(rt["hi"])))
    return out


RES = {"fits": {}, "eval": {}}
say("# Trap points: fitted on the first half of the scans (2 points per e-fold of the rug-rate ratio, 0-4), checked on the second half")
for c, rows, yk in (("L", L, "rug1h"), ("S", S, "rug2h"), ("E", E, "rug1h")):
    y = lambda r, yk=yk: r["out"].get(yk)
    runs = sorted({r["rid"] for r in rows})
    cut = runs[len(runs) // 2]
    A = [r for r in rows if r["rid"] < cut]
    Bv = [r for r in rows if r["rid"] >= cut]
    pts = fit_points(A, y)
    RES["fits"][c] = pts
    say("")
    say("## %s / %s: points from scans before %s: %s" % (c, yk, cut, ", ".join("%s %d" % (k, p) for k, p in pts.items())))
    RES["eval"][c + ".test." + yk] = evaluate(Bv, pts, y, "second half, %s" % yk)
    wk = "win1h" if c in ("L", "E") else "win2h"
    RES["eval"][c + ".test." + wk] = evaluate(Bv, pts, lambda r, wk=wk: r["out"].get(wk), "second half, %s" % wk)

# final points: from all data, the mean over the cohorts that could measure the flag (L for early-only flags)
final = {}
for k in FLAGS:
    vals = []
    for c, rows, yk in (("L", L, "rug1h"), ("S", S, "rug2h"), ("E", E, "rug1h")):
        x, n = rr(rows, FLAGS[k][1], lambda r, yk=yk: r["out"].get(yk))
        if x is not None:
            vals.append(2 * math.log(x))
    final[k] = max(0, min(4, round(sum(vals) / len(vals)))) if vals else 0
RES["final"] = final
say("")
say("## Final trap points (all scans, averaged over the cohorts that measure the flag): " + ", ".join("%s %d" % (k, p) for k, p in final.items()))
for c, rows, yk, wk in (("L", L, "rug1h", "win1h"), ("S", S, "rug2h", "win2h"), ("E", E, "rug1h", "win1h"), ("P", PY, "rug1h", "win1h")):
    say("")
    say("### %s with the final points (in-sample)" % c)
    RES["eval"][c + ".all." + yk] = evaluate(rows, final, lambda r, yk=yk: r["out"].get(yk), "all, %s" % yk)
    RES["eval"][c + ".all." + wk] = evaluate(rows, final, lambda r, wk=wk: r["out"].get(wk), "all, %s" % wk)

# 'good coin' check: zero trap points and at least one good sign
say("")
say("# 'Good coin' rule: 0 trap points and (X link + paid profile, or launched off a tweet, or on 3+ source lists)")
for c, rows, yk, wk in (("L", L, "rug1h", "win1h"), ("S", S, "rug2h", "win2h"), ("E", E, "rug1h", "win1h")):
    bt = Boot([r["rid"] for r in rows])
    runs = sorted({r["rid"] for r in rows})
    cut = runs[len(runs) // 2]
    say("## %s" % c)
    for nm, fn in (("0 trap points", lambda r: score(r, final) == 0),
                   ("0 trap points + a good sign", lambda r: score(r, final) == 0 and any(g(r) for _, g in GOOD.values())),
                   ("1-2 trap points", lambda r: 1 <= score(r, final) <= 2),
                   ("3+ trap points", lambda r: score(r, final) >= 3),
                   ("everything", lambda r: True)):
        line = "  %-30s" % nm
        for key in (yk, wk):
            for half, hf in (("1st", lambda r: r["rid"] < cut), ("2nd", lambda r: r["rid"] >= cut)):
                n, k = bt.per_run(rows, lambda r, fn=fn, hf=hf: fn(r) and hf(r), lambda r, key=key: r["out"].get(key))
                rt = bt.rate(n, k)
                line += " %s %s %s/%d" % (key, half, pct(rt["rate"], 0) if rt else "-", rt["n"] if rt else 0)
        say(line)

# the paper account (new launches since the restart): what each flag cost
say("")
say("# Paper new-launch positions since the 2026-10-10 18:11 UTC restart (3 fake EUR each; closed positions only)")
closed = [r for r in PY if r["why"] != "open" and r.get("exitEur") is not None]
tot = sum(r["exitEur"] - (r["ticket"] or 3) for r in closed)
say("closed %d, total result %+.2f EUR, %+.2f per position" % (len(closed), tot, tot / max(1, len(closed))))
pa = {"closed": len(closed), "total": tot, "flags": {}}
for k, (lab, fn) in FLAGS.items():
    a = [r for r in closed if fn(r) is True]
    b = [r for r in closed if fn(r) is False]
    if not a:
        continue
    ra = sum(r["exitEur"] - (r["ticket"] or 3) for r in a)
    rb = sum(r["exitEur"] - (r["ticket"] or 3) for r in b)
    pa["flags"][k] = {"n": len(a), "eur": ra, "per": ra / len(a), "nOther": len(b), "eurOther": rb, "perOther": rb / max(1, len(b))}
    say("  %-18s with: %3d positions %+7.2f EUR (%+.2f each) | without: %3d positions %+7.2f EUR (%+.2f each)" % (k, len(a), ra, ra / len(a), len(b), rb, rb / max(1, len(b))))
for nm, fn in (("0 trap points", lambda r: score(r, final) == 0), ("1-2 trap points", lambda r: 1 <= score(r, final) <= 2), ("3+ trap points", lambda r: score(r, final) >= 3)):
    a = [r for r in closed if fn(r)]
    if a:
        ra = sum(r["exitEur"] - (r["ticket"] or 3) for r in a)
        pa[nm] = {"n": len(a), "eur": ra}
        say("  %-18s %3d positions %+7.2f EUR (%+.2f each), sold by: %s" % (nm, len(a), ra, ra / len(a), ", ".join(
            "%s %d" % (w, sum(1 for r in a if r["why"] == w)) for w in sorted({r["why"] for r in a}))))
RES["paper"] = pa
json.dump(RES, open(os.path.join(OUT, "points.json"), "w"), indent=1, default=str)
open(os.path.join(OUT, "points.txt"), "w").write("\n".join(REP) + "\n")
print("\n".join(REP))
