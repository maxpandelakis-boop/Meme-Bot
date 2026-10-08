"""Offline research harness for the Meme-Bot big-test rows (db/memesnapres/*.json).

One row = one coin in one scan with the factors the bot saw then and what 20 (after fees) became at the horizon.
Everything here is fake money: eur is the profit of a 20 ticket, clipped to EUR_CLIP like the bot's own training.

Usage (from any directory, the harness takes the data dir as an argument):
    python3 -I harness.py /path/to/memesnapres            # prints the baselines
    import harness as H; rows, scans = H.load("/path/to/memesnapres"); H.evaluate(rows, scans, rule, k=1)

A rule is a function rule(rows_of_one_scan, history_rows) -> list of chosen rows (at most k), where history_rows are
the rows of EARLIER scans only (walk-forward: a rule may fit on them, never on the scan it picks from).
"""
import glob, json, math, os, random, statistics, sys

EUR_CLIP = (-20.0, 60.0)
LEARN_FROM = 1791380700000   # 2026-10-07 13:45 UTC: results scored before this counted every unpriced coin as gone (no Jupiter fallback yet)
TICKET = 20.0
GATE_MC = (50_000.0, 2_000_000.0)
GATE_MIN_LIQ = 15_000.0


def num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def learnable(c):
    liq, mc = num(c.get("liq")), num(c.get("mc"))
    return liq is not None and mc is not None and liq >= GATE_MIN_LIQ and GATE_MC[0] <= mc <= GATE_MC[1]


def priceless_at_snapshot(c):
    why = c.get("why") or []
    return any(str(w) in ("nodex", "curve") for w in why) or any("no DEX pair" in str(w) or "launch curve" in str(w) for w in why)


def usable_result(doc):
    """A scored snapshot whose price fetch did not fail wholesale (over half of the candidate-like coins 'gone')."""
    cand = [c for c in (doc.get("coins") or []) if isinstance(c, dict) and learnable(c) and not (c.get("gone") and priceless_at_snapshot(c))]
    return len(cand) < 20 or sum(1 for c in cand if c.get("gone")) <= 0.5 * len(cand)


def load(d, rule=None, only_learnable=True):
    """-> (rows, scans). rows: dicts with scan (t0), t (scored), a, s, f, pass, sc, rank, why, mc, liq, mult, eur (clipped), gone, late.
    scans: sorted list of t0. Chunks of one snapshot (same t0) are merged into one scan."""
    rows, by_scan = [], {}
    for fn in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            doc = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not num(doc.get("t0")):
            continue
        if rule and str(doc.get("rule") or "") != rule:
            continue
        if not usable_result(doc) or (num(doc.get("t")) or 0) < LEARN_FROM:
            continue
        t0, t1 = num(doc["t0"]), num(doc.get("t"))
        for c in doc.get("coins") or []:
            if not isinstance(c, dict) or not isinstance(c.get("f"), dict) or num(c.get("eur")) is None:
                continue
            if c.get("gone") and priceless_at_snapshot(c):
                continue
            if only_learnable and not learnable(c):
                continue
            mult = num(c.get("mult")) or 0.0
            rows.append({"scan": t0, "t": t1, "h": (t1 - t0) / 3_600_000 if t1 else None, "a": c.get("a"), "s": c.get("s"), "f": c["f"], "pass": bool(c.get("pass")),
                         "sc": num(c.get("sc")), "rank": num(c.get("rank")), "why": c.get("why") or [], "mc": num(c.get("mc")), "liq": num(c.get("liq")),
                         "mult": mult, "eur": clamp(num(c["eur"]), *EUR_CLIP), "eurRaw": num(c["eur"]), "gone": bool(c.get("gone")) or mult < 0.02,
                         "rc": c.get("rc") if isinstance(c.get("rc"), dict) else None, "src": c.get("src") or []})
            by_scan.setdefault(t0, 0)
            by_scan[t0] += 1
    scans = sorted(by_scan)
    return rows, scans


def by_scan(rows):
    out = {}
    for r in rows:
        out.setdefault(r["scan"], []).append(r)
    return out


def stats(chosen):
    """chosen: list of rows (over all scans). -> dict n, avg (per 20), win %, zero %, median mult, total."""
    n = len(chosen)
    if not n:
        return {"n": 0, "avg": None, "win": None, "zero": None, "median": None, "total": 0.0}
    eur = [r["eur"] for r in chosen]
    return {"n": n, "avg": round(sum(eur) / n, 2), "win": round(100.0 * sum(1 for e in eur if e > 0) / n, 1),
            "zero": round(100.0 * sum(1 for r in chosen if r["gone"]) / n, 1), "median": round(statistics.median(r["mult"] for r in chosen), 3), "total": round(sum(eur), 2)}


def evaluate(rows, scans, rule, k=1, min_history=0, seed=None):
    """Walk-forward: for each scan (in time order) the rule sees that scan's rows and the rows of earlier scans only.
    -> (stats over all chosen rows, per-scan list [(scan, [chosen rows])], coverage = scans where it chose something)."""
    groups = by_scan(rows)
    chosen_all, per_scan = [], []
    for i, t0 in enumerate(scans):
        g = groups.get(t0) or []
        # history = rows whose outcome was already KNOWN at this scan's time (scored at or before t0), not merely earlier scans:
        # a snapshot taken 1 h ago is scored 2 h after it, so its labels did not exist yet (the skeptic found this look-ahead)
        hist = [r for r in rows if r["scan"] < t0 and (r["t"] or 1e18) <= t0]
        picks = []
        if i >= min_history:
            picks = list(rule(g, hist) or [])[:k]
        chosen_all += picks
        per_scan.append((t0, picks))
    st = stats(chosen_all)
    st["scans"] = len(scans)
    st["covered"] = sum(1 for _, p in per_scan if p)
    return st, per_scan


def bootstrap_ci(per_scan, n_boot=2000, seed=1):
    """95% interval of the average eur per pick, resampling SCANS (a scan's picks are one block)."""
    blocks = [[r["eur"] for r in p] for _, p in per_scan if p]
    if len(blocks) < 3:
        return None
    rng = random.Random(seed)
    avgs = []
    for _ in range(n_boot):
        sample = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        flat = [e for b in sample for e in b]
        avgs.append(sum(flat) / len(flat))
    avgs.sort()
    return round(avgs[int(0.025 * n_boot)], 2), round(avgs[int(0.975 * n_boot)], 2)


def scan_consistency(per_scan):
    """How many scans the rule's average was positive in, of those it picked in."""
    picked = [(t, p) for t, p in per_scan if p]
    pos = sum(1 for _, p in picked if sum(r["eur"] for r in p) / len(p) > 0)
    return pos, len(picked)


# ---------------------------------------------------------------- baselines
def rule_gate_pass(g, hist):
    return [r for r in g if r["pass"]]


def rule_bot_top(g, hist):
    """The bot's own ranking at the time: gate passers by rank (the shortlist's order), then score."""
    ps = [r for r in g if r["pass"]]
    return sorted(ps, key=lambda r: (r["rank"] if r["rank"] else 1e9, -(r["sc"] or 0)))


def rule_all(g, hist):
    return list(g)


def rule_random(seed):
    rng = random.Random(seed)
    def f(g, hist):
        g2 = list(g)
        rng.shuffle(g2)
        return g2
    return f


def report(rows, scans, k=1, extra=None):
    print("rows %d, scans %d (%s to %s)" % (len(rows), len(scans), ts(scans[0]) if scans else "-", ts(scans[-1]) if scans else "-"))
    hs = [r["h"] for r in rows if r["h"]]
    if hs:
        print("horizon hours: median %.2f, min %.2f, max %.2f" % (statistics.median(hs), min(hs), max(hs)))
    rules = [("all learnable coins", rule_all, None), ("gate passers (all)", rule_gate_pass, None), ("bot top-%d" % k, rule_bot_top, k), ("random (k=%d)" % k, rule_random(1), k)]
    for name, fn, kk in rules + (extra or []):
        st, ps = evaluate(rows, scans, fn, k=kk or 10 ** 9)
        ci = bootstrap_ci(ps)
        pos, n = scan_consistency(ps)
        print("%-36s n %5d  avg %7s  win %5s%%  zero %5s%%  median %6s  ci95 %s  positive scans %d/%d" % (name, st["n"], st["avg"], st["win"], st["zero"], st["median"], ci, pos, n))


def ts(ms):
    import datetime
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


if __name__ == "__main__":
    d = sys.argv[1]
    rule = sys.argv[2] if len(sys.argv) > 2 else None
    rows, scans = load(d, rule=rule)
    report(rows, scans)
