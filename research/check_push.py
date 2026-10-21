"""The pre-registered check of research/PREREG-PUSH-2026-10-21.md (fake money only): which picks deserve a push.
usage: python3 research/check_push.py <memerec dir> <tm.json from check_timemachine.py with TM_DUMP>
"""
import glob, json, os, sys

SPLIT = 1792108800000      # 2026-10-16 00:00 UTC


def tips(d, tm):
    f = {(round(r["t"]), r["sym"]): r["tmP"] for r in tm}
    out = []
    for fn in sorted(glob.glob(os.path.join(d, "*.json"))):
        doc = json.load(open(fn, encoding="utf-8"))
        if doc.get("rule") != "m9-2h" or not doc.get("picks"):
            continue
        p = doc["picks"][0]
        res = {r.get("sym"): r for r in (doc.get("out") or {}).get("picks") or [] if isinstance(r, dict)}
        r = res.get(p.get("sym"))
        if not r or r.get("eur") is None:
            continue
        out.append({"t": doc["t"], "sym": p.get("sym"), "tier": p.get("tier"), "score": p.get("score") or 0, "up": p.get("up"),
                    "eur": max(-20.0, min(60.0, r["eur"])), "zero": bool(r.get("gone")) or (r.get("mult") or 1) < 0.02,
                    "tmP": f.get((round(doc["t"]), p.get("sym")))})
    return out


def stat(rs):
    n = len(rs)
    return (n, sum(r["eur"] for r in rs) / n if n else None, sum(r["zero"] for r in rs) / n if n else None)


def pct(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def main():
    rs = tips(sys.argv[1], json.load(open(sys.argv[2])))
    fit = [r for r in rs if r["t"] < SPLIT]
    chk = [r for r in rs if r["t"] >= SPLIT]
    print("tips: fit %d, check %d; all fit %s, all check %s" % (len(fit), len(chk), stat(fit), stat(chk)))
    cands = [("tier strong", lambda r: r["tier"] == "strong")]
    cands += [("score >= %d" % s, (lambda s: lambda r: r["score"] >= s)(s)) for s in (48, 50, 52)]
    upm = pct([r["up"] for r in fit if r["up"] is not None], 0.5)
    cands.append(("up >= fit median %.4f" % upm, lambda r: r["up"] is not None and r["up"] >= upm))
    tmf = [r["tmP"] for r in fit if r["tmP"] is not None]
    for q in (0.4, 0.5, 0.6):
        thr = pct(tmf, q)
        cands.append(("TM profit >= fit p%d %.3f" % (q * 100, thr), (lambda thr: lambda r: r["tmP"] is not None and r["tmP"] >= thr)(thr)))
    best = None
    for name, rule in cands:
        s = stat([r for r in fit if rule(r)])
        ok = s[0] >= 0.25 * len(fit)
        print("fit   %-30s %s%s" % (name, s, "" if ok else "  (lets through under 25%)"))
        if ok and (best is None or s[1] > best[2][1]):
            best = (name, rule, s)
    if not best:
        print("no candidate lets through 25% of the fit tips")
        return
    name, rule, _ = best
    a, b = stat(chk), stat([r for r in chk if rule(r)])
    for n2, r2 in cands:
        print("check %-30s %s" % (n2, stat([r for r in chk if r2(r)])))
    ok = b[0] >= 0.15 * len(chk) and b[1] is not None and b[1] > a[1] and b[2] <= a[2]
    print("chosen on fit: %s. check: pushed %s against all %s -> %s" % (name, b, a, "GOES LIVE" if ok else "FAILS, pushes stay as they are"))


if __name__ == "__main__":
    main()
