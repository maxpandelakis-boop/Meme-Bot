#!/usr/bin/env python3
"""Rug and winner study, step 2: signal tables, lifts with run-level bootstrap CIs, combos, hours, age, joint model.
Usage: venv/bin/python -I analyze.py <out dir>   (reads listings.jsonl, snapyoung.jsonl, positions.jsonl; writes results.json + report.txt)"""
import collections, json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import Boot, bh, pct, fx, auc, ridge_logit

OUT = sys.argv[1]
REP = []


def say(s=""):
    REP.append(s)


def load(name):
    with open(os.path.join(OUT, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


L, S, P = load("listings"), load("snapyoung"), load("positions")
PY = [r for r in P if r["grp"] == "young"]


def g(r, k):
    v = r["sig"].get(k)
    return v


def thr(k, op, x):
    def f(r):
        v = g(r, k)
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return {"<": v < x, "<=": v <= x, ">": v > x, ">=": v >= x, "==": v == x}[op]
    return f


def eq(k, val):
    def f(r):
        v = g(r, k)
        return None if v is None else (v == val)
    return f


def rc_only(fn):
    """A RugCheck-derived signal is unknown for a coin without a report (never 'absent')."""
    def f(r):
        if not g(r, "rc.report"):
            return None
        return fn(r)
    return f


# name, label, trap mapping (the user's list), predicate
SIGNALS = [
    # ---- the user's trap list, as far as we stored anything for it
    ("rcn.creator_rugged", "RugCheck: creator history of rugged tokens", "dev history with dead coins", rc_only(thr("rcn.creator_rugged", ">", 0))),
    ("jup.devMints>1", "Jupiter: dev minted more than 1 token", "dev history (count only)", thr("jup.devMints", ">", 1)),
    ("jup.devMints>=10", "Jupiter: dev minted 10+ tokens", "dev history (count only)", thr("jup.devMints", ">=", 10)),
    ("rcn.copycat", "RugCheck: copycat token", "copied X link / clone", rc_only(thr("rcn.copycat", ">", 0))),
    ("own.ticker_reused", "ticker already used by another coin we saw >= 1 h earlier", "clone (our data)", thr("own.ticker_reused", ">", 0)),
    ("gate.copy", "scan gate 'copy' (copycat of a bigger coin's ticker)", "clone (bot gate)", thr("gate.copy", ">", 0)),
    ("rcn.holder_correlation", "RugCheck: high holder correlation", "bubble map / same-source funding", rc_only(thr("rcn.holder_correlation", ">", 0))),
    ("rcn.insider_net", "RugCheck: insider network (any size)", "insider network", rc_only(thr("rcn.insider_net", ">", 0))),
    ("rcn.insider_net>=500", "RugCheck: insider network of 500+ wallets", "insider network", rc_only(thr("rcn.insider_net_size", ">=", 500))),
    ("rcn.cluster_any", "RugCheck: holder correlation or insider network", "bubble map / insider network", rc_only(thr("rcn.cluster_any", ">", 0))),
    ("own.holders_in_earlier_rug>=1", "a top holder was a top holder of an earlier coin that went to zero", "connected wallets (our data)", rc_only(thr("own.holders_in_earlier_rug", ">=", 1))),
    ("own.holders_in_earlier_rug>=3", "3+ top holders were in earlier coins that went to zero", "connected wallets (our data)", rc_only(thr("own.holders_in_earlier_rug", ">=", 3))),
    ("own.holders_seen_before>=3", "3+ top holders seen in earlier coins", "connected wallets (our data)", rc_only(thr("own.holders_seen_before", ">=", 3))),
    ("sw.avg<0", "top wallets with a track record lost on past coins", "wallet history", thr("sw.avg", "<", 0)),
    ("sw.n>0", "top wallets with a track record present", "wallet history", rc_only(thr("sw.n", ">", 0))),
    # ---- RugCheck / holders (stored)
    ("rc.report", "RugCheck report exists", "", thr("rc.report", ">", 0)),
    ("rcn.danger_any", "RugCheck: any danger flag", "", rc_only(thr("rcn.danger_any", ">", 0))),
    ("early.rc=danger", "early list: RugCheck danger", "", eq("early.rc", "danger")),
    ("early.rc=clean", "early list: RugCheck clean", "", eq("early.rc", "clean")),
    ("early.rc=none", "early list: no RugCheck report", "", eq("early.rc", "none")),
    ("young.ok=False", "new-launch row: safety check failed", "", lambda r: None if g(r, "young.ok") is None and not r.get("inYoung") else (g(r, "young.ok") is False)),
    ("rcn.single_holder", "RugCheck: single holder ownership", "", rc_only(thr("rcn.single_holder", ">", 0))),
    ("rcn.top10_high", "RugCheck: top 10 high ownership / concentration", "", rc_only(thr("rcn.top10_high", ">", 0))),
    ("rcn.lp_unlocked", "RugCheck: large amount of LP unlocked", "", rc_only(thr("rcn.lp_unlocked", ">", 0))),
    ("rcn.low_liquidity", "RugCheck: low liquidity", "", rc_only(thr("rcn.low_liquidity", ">", 0))),
    ("rcn.few_lp_providers", "RugCheck: low amount of LP providers", "", rc_only(thr("rcn.few_lp_providers", ">", 0))),
    ("rcn.mc_per_holder", "RugCheck: high market cap per holder", "", rc_only(thr("rcn.mc_per_holder", ">", 0))),
    ("rcn.mutable", "RugCheck: mutable metadata", "", rc_only(thr("rcn.mutable", ">", 0))),
    ("rcn.authority", "RugCheck: mint/freeze authority on", "", rc_only(thr("rcn.authority", ">", 0))),
    ("rc.top1>20", "biggest wallet > 20%", "single holder", rc_only(thr("rc.top1", ">", 20))),
    ("rc.top10>35", "top 10 wallets > 35%", "", rc_only(thr("rc.top10", ">", 35))),
    ("rc.top10>50", "top 10 wallets > 50%", "", rc_only(thr("rc.top10", ">", 50))),
    ("rc.holders<300", "under 300 holders", "", rc_only(thr("rc.holders", "<", 300))),
    ("rc.holders>=1000", "1000+ holders", "", rc_only(thr("rc.holders", ">=", 1000))),
    ("rc.creator>5", "creator still holds > 5%", "dev bought / holds", rc_only(thr("rc.creator", ">", 5))),
    ("rc.creator>0", "creator still holds some", "dev holds", rc_only(thr("rc.creator", ">", 0))),
    ("dev.sold>0", "creator sold", "dev dump", thr("dev.sold", ">", 0)),
    ("rc.lp<90", "under 90% of LP locked/burnt", "", rc_only(thr("rc.lp", "<", 90))),
    ("jup.organic=0", "Jupiter organic score 0", "fake activity", thr("jup.organic", "<=", 0)),
    ("jup.top10Pct>35", "Jupiter: top 10 > 35%", "", thr("jup.top10Pct", ">", 35)),
    # ---- market and flow
    ("liq<10k", "liquidity under $10k", "", thr("liq", "<", 10_000)),
    ("liq>=50k", "liquidity $50k+", "", thr("liq", ">=", 50_000)),
    ("mc<30k", "market cap under $30k", "", thr("mc", "<", 30_000)),
    ("mc>=500k", "market cap $500k+", "", thr("mc", ">=", 500_000)),
    ("liqMc>=0.5", "liquidity >= half the market cap", "", thr("liqMc", ">=", 0.5)),
    ("liqMc<0.15", "liquidity < 15% of market cap", "", thr("liqMc", "<", 0.15)),
    ("volMc>=5", "24h volume >= 5x market cap", "fake volume", thr("volMc", ">=", 5)),
    ("gate.wash", "scan gate 'wash' (volume > 8x mc)", "fake volume", thr("gate.wash", ">", 0)),
    ("buyShare<0.5", "fewer buys than sells (24h count)", "", thr("buyShare", "<", 0.5)),
    ("buyRatio1h<1", "1h buys < sells", "", thr("buyRatio1h", "<", 1)),
    ("buyRatio1h>=1.5", "1h buys >= 1.5x sells", "", thr("buyRatio1h", ">=", 1.5)),
    ("buys1<100", "under 100 buys in the last hour", "", thr("buys1", "<", 100)),
    ("m5>=20", "up 20%+ in the last 5 minutes", "already going up", thr("m5", ">=", 20)),
    ("m5<=-20", "down 20%+ in the last 5 minutes", "", thr("m5", "<=", -20)),
    ("c1>=100", "up 100%+ in the last hour", "already going up", thr("c1", ">=", 100)),
    ("c1<=-50", "down 50%+ in the last hour", "", thr("c1", "<=", -50)),
    ("gate.spike", "scan gate 'spike' (rose too fast)", "already going up", thr("gate.spike", ">", 0)),
    ("gate.crash", "scan gate 'crash' (fell too fast)", "", thr("gate.crash", ">", 0)),
    ("fl.topBuyer>=0.3", "on-chain sample: one buyer >= 30% of buy volume", "bundle / one actor", thr("fl.topBuyer", ">=", 0.3)),
    ("fl.flip>0", "on-chain sample: flippers present", "", thr("fl.flip", ">", 0)),
    ("fl.buyerRatio<1", "on-chain sample: fewer buyers than sellers", "", thr("fl.buyerRatio", "<", 1)),
    ("ds.paid", "DexScreener profile paid", "hype", thr("ds.paid", ">", 0)),
    ("boosts>0", "DexScreener boosts bought", "hype", thr("boosts", ">", 0)),
    ("x", "has an X link", "", thr("x", ">", 0)),
    ("web", "has a website", "", thr("web", ">", 0)),
    ("socN=0", "no socials at all", "", thr("socN", "<=", 0)),
    ("pf.telegram", "pump.fun: telegram link", "", thr("pf.telegram", ">", 0)),
    ("vt.tweet", "launched off a tweet", "", thr("vt.tweet", ">", 0)),
    ("kwN>0", "found by a keyword search", "", thr("kwN", ">", 0)),
    ("srcN>=3", "on 3+ source lists", "", thr("srcN", ">=", 3)),
    ("news.hits>0", "named in news/posts", "", thr("news.hits", ">", 0)),
    ("own.brand_name", "named after a big brand / AI / celebrity (exploratory)", "", thr("own.brand_name", ">", 0)),
    ("theme.animal", "animal theme", "", thr("theme.animal", ">", 0)),
    ("score>=50", "bot score >= 50", "", thr("score", ">=", 50)),
    ("zp>=0.5", "trained zero odds >= 50% (in-sample)", "", thr("zp", ">=", 0.5)),
    ("zp>=0.7", "trained zero odds >= 70% (in-sample)", "", thr("zp", ">=", 0.7)),
    ("instantPool", "pool opened within 60 s of the mint (curve bought out at once)", "bundle / sniped launch", thr("instantPool", ">", 0)),
    ("graduated", "token sat on its curve 2+ min before the pool", "organic launch", thr("graduated", ">", 0)),
    ("dex=pumpswap", "pool on PumpSwap", "", lambda r: None if not g(r, "dex") else g(r, "dex") == "pumpswap"),
    ("launchpad=pump.fun", "launchpad pump.fun", "", lambda r: None if not (g(r, "launchpad") or g(r, "rc.launchpad")) else
        str(g(r, "launchpad") or g(r, "rc.launchpad")).lower().replace(" ", "") in ("pump.fun", "pumpfun")),
    ("ageMin<10", "younger than 10 minutes", "radar age limit", thr("ageMin", "<", 10)),
    ("ageMin<5", "younger than 5 minutes", "", thr("ageMin", "<", 5)),
]
SIGDEF = {s[0]: s for s in SIGNALS}

NUMERIC = ["mintToPoolMin", "liq", "mc", "liqMc", "volMc", "buyShare", "buyRatio1h", "buys1", "m5", "c1", "score", "zp", "ageMin", "srcN",
           "rc.top1", "rc.top10", "rc.holders", "rc.score", "rc.creator", "jup.devMints", "sw.avg", "own.holders_seen_before",
           "own.holders_in_earlier_rug", "rcn.insider_net_size", "fl.topBuyer", "fl.rate1h", "pf.athRatio", "mkt.sol24", "mkt.fng"]

# outcomes per cohort
OUTS = {
    "L": [("rug1h", lambda r: r["out"].get("rug1h")), ("win1h", lambda r: r["out"].get("win1h")), ("win1hEnd", lambda r: r["out"].get("win1hEnd")),
          ("rug2h", lambda r: r["out"].get("rug2h")), ("rug24h", lambda r: r["out"].get("rug24h"))],
    "S": [("rug2h", lambda r: r["out"].get("rug2h")), ("win2h", lambda r: r["out"].get("win2h"))],
    "P": [("rugAny", lambda r: (r["out"].get("rug24h") is True) or ("rug" in (r.get("why") or "")) or ((r.get("exitX") is not None) and r["exitX"] <= 0.1) if r["why"] != "open" or r["out"].get("rug24h") is not None else None),
          ("stopOrRug", lambda r: None if r["why"] == "open" else (("stop" in r["why"]) or ("rug" in r["why"]))),
          ("win1h", lambda r: r["out"].get("win1h"))],
}
COHORTS = {"L": L, "S": S, "P": PY}
COHORT_NAME = {"L": "listed new launches (memeyoung U early list, first listing per coin)", "S": "every snapshot coin < 1 h old, >= $5k liquidity (first sighting)",
               "P": "paper new-launch positions since the restart"}

boots = {c: Boot([r["rid"] for r in rows]) for c, rows in COHORTS.items()}
# time halves by run
halves = {}
for c, rows in COHORTS.items():
    runs = sorted({r["rid"] for r in rows})
    cut = runs[len(runs) // 2]
    halves[c] = cut

RES = {"base": {}, "signals": {}, "numeric": {}, "hours": {}, "age": {}, "combos": {}, "model": {}, "paper": {}, "notes": []}

# ------------------------------------------------------------------ base rates
say("# Rug and winner study on the bot's own data (fake money only)")
say()
say("## Cohorts and base rates (95%% CI: run-level bootstrap, %d resamples)" % 4000)
for c, rows in COHORTS.items():
    bt = boots[c]
    say("- %s: %s, %d coins from %d scans (%s .. %s)" % (c, COHORT_NAME[c], len(rows), len(bt.runs), bt.runs[0], bt.runs[-1]))
    for oname, of in OUTS[c]:
        n, k = bt.per_run(rows, lambda r: True, of)
        rt = bt.rate(n, k)
        RES["base"]["%s.%s" % (c, oname)] = rt
        if rt:
            say("    %-10s %4d of %4d = %s (CI %s .. %s)" % (oname, rt["k"], rt["n"], pct(rt["rate"]), pct(rt["lo"]), pct(rt["hi"])))

# ------------------------------------------------------------------ signal tables
say()
say("## Signals: rate with vs without (lift = rate with / rate without; CI = run bootstrap; q = BH within the cohort-outcome)")
FAMILIES = [("L", "rug1h"), ("L", "win1h"), ("S", "rug2h"), ("S", "win2h"), ("L", "rug24h"), ("P", "rugAny"), ("P", "stopOrRug")]
for c, oname in FAMILIES:
    rows = COHORTS[c]
    bt = boots[c]
    of = dict(OUTS[c])[oname]
    res = []
    for name, label, trap, pred in SIGNALS:
        n1, k1 = bt.per_run(rows, lambda r: pred(r) is True, of)
        n0, k0 = bt.per_run(rows, lambda r: pred(r) is False, of)
        cmp_ = bt.compare(n1, k1, n0, k0)
        if not cmp_:
            continue
        # halves
        hv = []
        for side in (0, 1):
            m = (lambda r: r["rid"] < halves[c]) if side == 0 else (lambda r: r["rid"] >= halves[c])
            a1 = [of(r) for r in rows if m(r) and pred(r) is True and of(r) is not None]
            a0 = [of(r) for r in rows if m(r) and pred(r) is False and of(r) is not None]
            hv.append((len(a1), (sum(a1) / len(a1)) if a1 else None, len(a0), (sum(a0) / len(a0)) if a0 else None))
        cmp_.update(name=name, label=label, trap=trap, halves=hv)
        res.append(cmp_)
    qs = bh([x["p"] for x in res])
    for x, q in zip(res, qs):
        x["q"] = q
        same = all(h[1] is not None and h[3] is not None and ((h[1] - h[3]) * x["diff"] > 0) for h in x["halves"])
        x["sameSign"] = same
        if x["n1"] < 20 or x["n0"] < 20:
            v = "too rare"
        elif x["dlo"] > 0 or x["dhi"] < 0:
            v = "HOLDS" if (same and x["q"] < 0.10) else ("holds (one half weak)" if x["q"] < 0.10 else "weak (multiple testing)")
        elif x["p"] < 0.10:
            v = "hint"
        else:
            v = "no effect"
        x["verdict"] = v
    res.sort(key=lambda x: (x["verdict"] not in ("HOLDS", "holds (one half weak)"), -abs(math.log(max(x["lift"], 1e-6)) if math.isfinite(x["lift"]) else 9)))
    RES["signals"]["%s.%s" % (c, oname)] = res
    say()
    say("### %s / %s  (base %s)" % (c, oname, pct((RES["base"]["%s.%s" % (c, oname)] or {}).get("rate"))))
    say("%-34s %6s %6s %7s %6s %7s %6s %-15s %6s %-12s %-18s %s" % ("signal", "n_with", "rate", "n_w/o", "rate", "lift", "", "lift 95% CI", "q", "halves", "verdict", "trap"))
    for x in res:
        hv = " ".join(pct(h[1], 0) + "/" + pct(h[3], 0) for h in x["halves"])
        say("%-34s %6d %6s %7d %6s %7s %6s %-15s %6s %-12s %-18s %s" % (x["name"][:34], x["n1"], pct(x["r1"]), x["n0"], pct(x["r0"]), fx(x["lift"]), "",
                                                                      "%s..%s" % (fx(x["llo"]), fx(x["lhi"])), fx(x["q"], 3), hv, x["verdict"], x["trap"]))

# ------------------------------------------------------------------ numeric quartiles
say()
say("## Numeric signals by quartile (rate per quartile, n per quartile)")
for c, oname in (("L", "rug1h"), ("L", "win1h"), ("S", "rug2h"), ("S", "win2h")):
    rows = COHORTS[c]
    bt = boots[c]
    of = dict(OUTS[c])[oname]
    say()
    say("### %s / %s" % (c, oname))
    out = {}
    for k in NUMERIC:
        vals = sorted(float(g(r, k)) for r in rows if g(r, k) is not None and of(r) is not None and isinstance(g(r, k), (int, float)))
        if len(vals) < 80:
            continue
        qs = [vals[int(len(vals) * q)] for q in (0.25, 0.5, 0.75)]
        if len(set(qs)) < 2:
            # mostly one value: split at zero / the mode
            edges = sorted(set(qs))
        else:
            edges = qs
        bins = []
        lo_e = [-float("inf")] + edges
        hi_e = edges + [float("inf")]
        for a, b in zip(lo_e, hi_e):
            n, kk = bt.per_run(rows, lambda r, a=a, b=b: isinstance(g(r, k), (int, float)) and a < float(g(r, k)) <= b if a != -float("inf") else
                                isinstance(g(r, k), (int, float)) and float(g(r, k)) <= b, of)
            rt = bt.rate(n, kk)
            if rt and rt["n"] > 0:
                bins.append(dict(rt, a=a, b=b))
        out[k] = bins
        e = lambda v: ("min" if v == -float("inf") else "max") if not math.isfinite(v) else fx(v, 3 if abs(v) < 10 else 0)
        say("%-28s " % k + " | ".join("%s..%s: %s n=%d [%s-%s]" % (e(b["a"]), e(b["b"]), pct(b["rate"], 0), b["n"], pct(b["lo"], 0), pct(b["hi"], 0)) for b in bins))
    RES["numeric"]["%s.%s" % (c, oname)] = out

# ------------------------------------------------------------------ hours (Berlin)
say()
say("## Hour of day (Berlin time, CEST = UTC+2 in this period)")
for c, onames in (("L", ("rug1h", "win1h")), ("S", ("rug2h", "win2h"))):
    rows = COHORTS[c]
    bt = boots[c]
    say()
    say("### %s" % c)
    say("hour   n   " + "   ".join("%-24s" % o for o in onames) + "  scans")
    hrs = {}
    for h in range(24):
        line = "%02d  %4d   " % (h, sum(1 for r in rows if g(r, "hourBerlin") == h))
        hrs[h] = {}
        for o in onames:
            of = dict(OUTS[c])[o]
            n, k = bt.per_run(rows, lambda r, h=h: g(r, "hourBerlin") == h, of)
            rt = bt.rate(n, k)
            hrs[h][o] = rt
            line += "%-24s   " % (("%s [%s-%s]" % (pct(rt["rate"], 0), pct(rt["lo"], 0), pct(rt["hi"], 0))) if rt else "-")
        line += "%d" % len({r["rid"] for r in rows if g(r, "hourBerlin") == h})
        say(line)
    blocks = {}
    say("4-hour blocks:")
    for b0 in range(0, 24, 4):
        line = "%02d-%02d " % (b0, b0 + 4)
        blocks[b0] = {}
        for o in onames:
            of = dict(OUTS[c])[o]
            n, k = bt.per_run(rows, lambda r, b0=b0: g(r, "hourBerlin") is not None and b0 <= g(r, "hourBerlin") < b0 + 4, of)
            rt = bt.rate(n, k)
            blocks[b0][o] = rt
            line += " %s %s n=%d [%s-%s]  " % (o, pct(rt["rate"]), rt["n"], pct(rt["lo"]), pct(rt["hi"])) if rt else ""
        say(line)
    RES["hours"][c] = {"hours": hrs, "blocks": blocks}

# ------------------------------------------------------------------ age at listing
say()
say("## Age at listing")
AGEB = [(0, 5), (5, 10), (10, 20), (20, 40), (40, 61)]
for c, onames, key in (("L", ("rug1h", "win1h", "win1hEnd", "rug24h"), "listAgeMin"), ("S", ("rug2h", "win2h"), "ageMin")):
    rows = COHORTS[c]
    bt = boots[c]
    say()
    say("### %s (age = %s)" % (c, key))
    RES["age"][c] = {}
    for a, b in AGEB + [(0, 10), (10, 61)]:  # ages under 0 (pool opened during the scan) count as 0
        line = "%2d-%2d min " % (a, b - 1 if b == 61 else b)
        RES["age"][c]["%d-%d" % (a, b)] = {}
        for o in onames:
            of = dict(OUTS[c])[o]
            n, k = bt.per_run(rows, lambda r, a=a, b=b: g(r, key) is not None and a <= max(0.0, float(g(r, key))) < b, of)
            rt = bt.rate(n, k)
            RES["age"][c]["%d-%d" % (a, b)][o] = rt
            line += " %s %s of %d [%s-%s] " % (o, pct(rt["rate"]), rt["n"], pct(rt["lo"]), pct(rt["hi"])) if rt else ""
        say(line)
    for o in onames:
        of = dict(OUTS[c])[o]
        n1, k1 = bt.per_run(rows, lambda r: g(r, key) is not None and float(g(r, key)) < 10, of)
        n0, k0 = bt.per_run(rows, lambda r: g(r, key) is not None and float(g(r, key)) >= 10, of)
        cm = bt.compare(n1, k1, n0, k0)
        RES["age"][c]["under10_vs_older." + o] = cm
        if cm:
            say("  under 10 min vs older, %s: %s vs %s, diff %+.1f pts [%+.1f..%+.1f], p=%.3f" % (o, pct(cm["r1"]), pct(cm["r0"]), 100 * cm["diff"], 100 * cm["dlo"], 100 * cm["dhi"], cm["p"]))

# ------------------------------------------------------------------ combos: discovery on the first half, validation on the second
say()
say("## Two-signal AND rules (found on the first half of the scans, checked on the second half)")


def combo_search(c, oname, want_high=True, min_n=25, top=12, pool=None):
    rows = COHORTS[c]
    of = dict(OUTS[c])[oname]
    cut = halves[c]
    A = [r for r in rows if r["rid"] < cut and of(r) is not None]
    Bv = [r for r in rows if r["rid"] >= cut and of(r) is not None]
    base_a = sum(of(r) for r in A) / len(A)
    base_b = sum(of(r) for r in Bv) / len(Bv)
    names = pool or [s[0] for s in SIGNALS]
    pv = {nm: [SIGDEF[nm][3](r) for r in A] for nm in names}
    pvb = {nm: [SIGDEF[nm][3](r) for r in Bv] for nm in names}
    ya = [1 if of(r) else 0 for r in A]
    yb = [1 if of(r) else 0 for r in Bv]
    cands = []
    for i, n1 in enumerate(names):
        for n2 in names[i:]:
            sel = [k for k in range(len(A)) if pv[n1][k] is True and pv[n2][k] is True]
            if len(sel) < min_n:
                continue
            rate = sum(ya[k] for k in sel) / len(sel)
            # Wilson lower/upper bound to rank (penalises small n)
            z = 1.96
            nn = len(sel)
            ctr = (rate + z * z / (2 * nn)) / (1 + z * z / nn)
            half = z * math.sqrt(rate * (1 - rate) / nn + z * z / (4 * nn * nn)) / (1 + z * z / nn)
            bound = ctr - half if want_high else -(ctr + half)
            cands.append((bound, n1, n2, nn, rate))
    cands.sort(reverse=True)
    out = []
    for bound, n1, n2, nn, rate in cands[:top]:
        selb = [k for k in range(len(Bv)) if pvb[n1][k] is True and pvb[n2][k] is True]
        rb = (sum(yb[k] for k in selb) / len(selb)) if selb else None
        out.append({"rule": n1 if n1 == n2 else "%s & %s" % (n1, n2), "nA": nn, "rateA": rate, "baseA": base_a, "nB": len(selb), "rateB": rb, "baseB": base_b})
    return out


for c, oname, hi_ in (("L", "rug1h", True), ("S", "rug2h", True), ("L", "win1h", True), ("S", "win2h", True), ("L", "rug1h", False), ("S", "rug2h", False)):
    rs = combo_search(c, oname, hi_, min_n=25 if c == "L" else 40)
    RES["combos"]["%s.%s.%s" % (c, oname, "high" if hi_ else "low")] = rs
    say()
    say("### %s / %s, rules with the %s rate" % (c, oname, "highest" if hi_ else "lowest"))
    for x in rs:
        say("  %-58s first half %s of %d (base %s)  ->  second half %s of %d (base %s)" % (x["rule"][:58], pct(x["rateA"]), x["nA"], pct(x["baseA"]),
                                                                                         pct(x["rateB"]), x["nB"], pct(x["baseB"])))

json.dump(RES, open(os.path.join(OUT, "results.json"), "w"), default=lambda o: None if isinstance(o, float) and not math.isfinite(o) else str(o), indent=1)
open(os.path.join(OUT, "report.txt"), "w").write("\n".join(REP) + "\n")
print("\n".join(REP))
