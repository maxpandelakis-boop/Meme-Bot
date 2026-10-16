#!/usr/bin/env python3
"""The curve watch's paper test against the radar's greens (fake money only): per variant (60, 75, 90 % of the pump.fun curve sold, with
m for the momentum filter) and quick-check verdict, from the hour docs on radar-data (db/memecurve) and the radar's records
(db/memeradar), with curve_watch's own rules (Book.variants, stats, split_of, greens_stats). Adds what the page does not show: the two
time halves of each group against the greens of the same halves' hours, and how many minutes before the radar's first sight of its
pool a call came (the coins that graduated and that the radar saw).

    git fetch origin +radar-data:refs/remotes/origin/radar-data
    mkdir rd && git archive origin/radar-data | tar -x -C rd
    python3 research/check_curve.py rd            # one JSON object

The pre-registered rule for switching the push on (radar_curve.json curvePush): a variant needs at least 30 valued calls among its
ok-verdict calls, an average paper result above the greens' of the same hours, a rug share not above theirs, and the same sign of
the advantage in both time halves of its calls; of several, the best average. "rule" in the output applies it.
"""
import glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import curve_watch as CW
import radar_paper as RP

MIN_VALUED = 30


def load(d):
    b = CW.Book()
    for f in sorted(glob.glob(os.path.join(d, "db", "memecurve", "*.json"))):
        doc = json.load(open(f, encoding="utf-8"))
        b.load(os.path.basename(f)[:-5], doc)
    return b, RP.records(d)          # the radar's records as its own code reads them (hour docs' coins, keyed by token address)


def halves(cs):
    """The calls split at the median call time: (first, second)."""
    ts = sorted(c["t"] for c in cs)
    if len(ts) < 2:
        return cs, []
    mid = ts[len(ts) // 2]
    return [c for c in cs if c["t"] < mid], [c for c in cs if c["t"] >= mid]


def adv(cs, recs):
    """A group's average paper result minus the greens' of the same UTC hours (None when either has no valued trade)."""
    s = CW.stats(cs, short=True)
    g = CW.greens_stats(recs, {CW.utc_hour(c["t"]) for c in cs})
    return (round(s["eur"] - g["eur"], 2) if s["eur"] is not None and g["eur"] is not None else None), s, g


def earlier(cs, first):
    """Minutes from each call to the radar's first sight of its coin's pool (positive: the call came first), for the coins the radar saw."""
    out = [(first[a] - c["t"]) / 60_000 for a, c in cs if a in first]
    return {"n": len(out), "median": round(statistics.median(out), 1) if out else None,
            "earlier": sum(1 for x in out if x > 0)}


def main(d):
    b, recs = load(d)
    calls = b.calls()
    hours = b.active_hours()
    first = {}
    for r in recs:
        a, t = r.get("addr"), CW.num(r.get("first"))      # addr is the token's address (mint is its mint time)
        if a and t and (a not in first or t < first[a]):
            first[a] = t
    late = sum(int(CW.num(doc.get("late")) or 0) for doc in b.docs.values())
    out = {"hours": len(hours), "calls": len(calls), "late": late, "greens": CW.greens_stats(recs, hours), "variants": []}
    qualified = []
    for row in b.variants():
        thr, mom = row["thr"], row["mom"]
        mine = [(a, c) for a, c in calls if CW.in_variant(c, thr, mom)]
        sp = [(a, CW.split_of(c)) for a, c in mine]
        v = {"id": row["id"], "all": {k: row.get(k) for k in ("n", "nS", "grad", "gradMin", "rug", "x2", "eur", "miss", "unseen")},
             "by": row.get("by"), "earlier": earlier(mine, first)}
        for name, grp in (("all", [c for _, (_, c) in sp]), ("ok", [c for _, (vv, c) in sp if vv == "ok"])):
            a_all, s_all, g_all = adv(grp, recs)
            h1, h2 = halves(grp)
            v[name + "VsGreens"] = {"adv": a_all, "greens": g_all, "halves": [adv(h1, recs)[0], adv(h2, recs)[0]],
                                    "rug": s_all["rug"], "greensRug": g_all["rug"], "nS": s_all["nS"]}
        ok = v["okVsGreens"]
        hv = ok["halves"]
        passes = (ok["nS"] >= MIN_VALUED and ok["adv"] is not None and ok["adv"] > 0
                  and ok["rug"] is not None and ok["greensRug"] is not None and ok["rug"] <= ok["greensRug"]
                  and None not in hv and all(x > 0 for x in hv))
        v["passes"] = passes
        if passes:
            qualified.append((v["okVsGreens"]["greens"]["eur"] + ok["adv"], v["id"]))
        out["variants"].append(v)
    out["rule"] = {"minValuedOk": MIN_VALUED, "qualified": [i for _, i in sorted(qualified, reverse=True)],
                   "choice": max(qualified)[1] if qualified else None}
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else "rd"), indent=1, default=str))
