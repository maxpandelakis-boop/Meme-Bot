"""Verdict of research/scout/PREREG-CONFIRM-2026-11-11.md. Fake money only.
usage: python3 research/scout/scout_confirm.py <dir with trades_*.json> <out dir>"""
import glob, json, os, sys
import numpy as np

CELL, BOOT = "V3+R", 4000


def ci(v, d, rng):
    ud = sorted(set(d)); by = {x: [a for a, b in zip(v, d) if b == x] for x in ud}
    ms = [np.mean(sum((by[ud[i]] for i in rng.choice(len(ud), len(ud))), [])) for _ in range(BOOT)]
    return [round(float(x), 3) for x in np.percentile(ms, [2.5, 97.5])]


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rows, days = [], []
    for f in sorted(glob.glob(os.path.join(src, "**", "trades_*.json"), recursive=True)):
        js = json.load(open(f)); rows += js["rows"]; days.append(js["day"])
    rng = np.random.default_rng(11)
    rr = sorted([r for r in rows if r["cell"] == CELL], key=lambda r: r["entry_t"])
    res = dict(days=days, n=len(rr))
    lines = ["Confirmation test %s, days %s..%s (%d days)" % (CELL, min(days), max(days), len(days))]
    for key in ("holdg2", "hold2", "holdg5", "pnl2", "scal2"):
        v = [r[key] for r in rr]; d = [r["day"] for r in rr]
        if not v:
            continue
        top3 = sorted(v)[-3:]
        wk = {}
        for x, dd in zip(v, d):
            w = (np.datetime64(dd) - np.datetime64("2026-08-11")).astype(int) // 7
            wk.setdefault(int(w), []).append(x)
        full = {w: x for w, x in wk.items() if w < 6}
        cv = [(r[key] - r["ctl"][key], r["day"]) for r in rr if r.get("ctl") and key in r["ctl"]]
        s = dict(n=len(v), avg=round(float(np.mean(v)), 3), ci=ci(v, d, rng),
                 without_top3=round(float((sum(v) - sum(top3)) / max(len(v) - 3, 1)), 3), median=round(float(np.median(v)), 2),
                 in_profit=round(float(np.mean(np.array(v) > 0)) * 100, 1),
                 weeks={w: [len(x), round(float(np.mean(x)), 2)] for w, x in sorted(wk.items())},
                 weeks_pos="%d/%d" % (sum(np.mean(x) > 0 for x in full.values()), len(full)),
                 grad_pct=round(float(np.mean([r.get("ghow") == "grad" for r in rr])) * 100, 1))
        if cv:
            s["control_avg"] = round(float(np.mean([r["ctl"][key] for r in rr if r.get("ctl") and key in r["ctl"]])), 3)
            s["minus_control"] = dict(avg=round(float(np.mean([x for x, _ in cv])), 3), ci=ci([x for x, _ in cv], [y for _, y in cv], rng))
        res[key] = s
        lines.append("%-7s n %d avg %+.2f 95%% %s w/o top3 %+.2f median %+.2f profit %.1f%% weeks+ %s control %s minus %s grad %.1f%%" % (
            key, s["n"], s["avg"], s["ci"], s["without_top3"], s["median"], s["in_profit"], s["weeks_pos"], s.get("control_avg"),
            s.get("minus_control"), s["grad_pct"]))
        lines.append("        weeks: %s" % s["weeks"])
    h = res.get("holdg2")
    ok = bool(h) and h["n"] >= 100 and h["avg"] > 0 and h["ci"][0] > 0 and h["without_top3"] > 0 and \
        int(h["weeks_pos"].split("/")[0]) >= 4 and h.get("minus_control", {}).get("ci", [-1])[0] > 0
    res["verdict"] = "PASS" if ok else "FAIL"
    lines.append("verdict: " + res["verdict"])
    json.dump(res, open(os.path.join(out, "confirm.json"), "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    open(os.path.join(out, "confirm.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
