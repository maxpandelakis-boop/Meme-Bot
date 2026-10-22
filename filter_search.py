#!/usr/bin/env python3
"""filter_search.py: the nightly filter search (fake money only). A report and nothing else: nothing here buys, signs or sends
anything, and nothing the scan, the trader or the training reads comes from here. The bot keeps its gates and its sell rule; a rule
found here is only ever shown on the page as a candidate, and only the user can switch one on (in code, by hand).

The question: is there a filter that does better than the bot's own gates on coins it has never seen? Every night:
  1. learn: the big test (every coin of every hourly scan with the factors the bot saw and what 20 became about 2 hours later) has
     grown by a day, the day's picks and their real results included. A search over SEARCH_RULES conditions on those rows (one or
     two numbers above or below a quartile of the training rows, in one of the age windows WINDOWS) picks the rule that did best
     in BOTH halves of the training rows (the lower of the two averages counts), with at least MIN_HALF coins in each half and a
     3x share not below the gates'. That rule is FROZEN with its thresholds and the time of the last row it saw (frozenAt).
  2. test: every frozen rule of the last MAX_CHALLENGERS nights is measured on the rows that came AFTER its frozenAt only (it
     never saw them), next to the gates on the same rows. A rule is "better" only when, on at least MIN_FWD coins over at least
     MIN_DAYS days, its average per 20 is above zero, above the gates' average, its 3x share is not below the gates', and the lower
     end of its bootstrap interval is above zero at the 95% level corrected for the number of rules under test (Bonferroni).
  3. mistakes: the bot's top picks (rank 1 among the gate passers) of the last LOOKBACK_DAYS days that lost money, and how many of
     them the leading rule would have let through, against how many winning picks it would have blocked.
Profit per 20 after FEE_SIDE per buy and per sell, the price multiple capped at MULT_CAP (one freak coin cannot carry a rule); one
entry per coin and test window (the first scan the rule lets it through).

Files: the doc (DOC, for the page: page_search.py shows it under the paper account) and the state (STATE: the frozen rules) live
on the branch "filtersearch" (.github/workflows/filtersearch.yml); the scan job copies the doc into db/memebot before the page.

  python3 filter_search.py run --snaps <memesnapres dir> --out <dir> [--now ms] [--study research/SEARCH-STUDY.json]
"""
import argparse, glob, json, math, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "research"))
import harness as H      # the big test's loader rules: usable_result, LEARN_FROM, priceless_at_snapshot

DOC = "filtersearch.json"
STATE = "filtersearch-state.json"
FEE_SIDE = 0.01          # 1% per buy and per sell: about what a swap on PumpSwap/Raydium costs with slippage on a small ticket
MULT_CAP = 11.0          # the paper account's take-profit
TICKET = 20.0
MIN_LIQ, MIN_MC = 5_000.0, 10_000.0
HARD_BLOCK = ("price", "curve", "nodex", "honeypot", "notmeme", "copy")   # memebot.HARD_BLOCK: no tradable pair or a scam, never a buy
FEATURES = ("ageH", "logMc", "liqMc", "volMc", "vol1Share", "c1", "c6", "c24", "m5", "buyShare", "buyRatio1h", "buys1", "srcN",
            "jup.holders", "jup.holderChg24", "jup.netBuyers24", "jup.top10Pct", "jup.organic", "pf.replies", "pf.athRatio")
QUANTS = (0.25, 0.5, 0.75)
WINDOWS = {"new": "coins under 1 h old (the old new launches)", "1-6h": "1 to 6 hours old", "6-24h": "6 to 24 hours old",
           "24h+": "older than a day", "any": "any age", "gates": "coins that passed the bot's gates"}
MIN_HALF = 60            # coins in each training half
MIN_FWD, MIN_DAYS = 100, 3
MAX_CHALLENGERS = 30
LOOKBACK_DAYS = 7
DAY = 86_400_000
BOOT = 2000


def num(v):
    return H.num(v)


# ---------------------------------------------------------------------------------------------------------------- the rows
def load(snaps, features=FEATURES):
    """The big test's rows (liquidity at least MIN_LIQ, market cap at least MIN_MC), streamed file by file -> dict of numpy
    columns: scan, t (scored), coin (int id), pass, rank, r (profit per 20), zero, hit3, and one column per features."""
    import numpy as np
    cols = {k: [] for k in ("scan", "t", "a", "pass", "rank", "mult", "gone") + tuple(features)}
    for fn in sorted(glob.glob(os.path.join(snaps, "*.json"))):
        try:
            doc = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not num(doc.get("t0")) or not H.usable_result(doc) or (num(doc.get("t")) or 0) < H.LEARN_FROM:
            continue
        t0, t1 = num(doc["t0"]), num(doc.get("t")) or num(doc["t0"])
        for c in doc.get("coins") or []:
            if not isinstance(c, dict) or not isinstance(c.get("f"), dict) or num(c.get("eur")) is None:
                continue
            if c.get("gone") and H.priceless_at_snapshot(c):
                continue
            liq, mc = num(c.get("liq")), num(c.get("mc"))
            if not liq or liq < MIN_LIQ or not mc or mc < MIN_MC or any(str(w) in HARD_BLOCK for w in c.get("why") or []):
                continue
            f, m = c["f"], num(c.get("mult")) or 0.0
            cols["scan"].append(t0); cols["t"].append(t1); cols["a"].append(str(c.get("a")))
            cols["pass"].append(bool(c.get("pass"))); cols["rank"].append(num(c.get("rank")) or 0.0)
            cols["mult"].append(m); cols["gone"].append(bool(c.get("gone")) or m < 0.02)
            for k in features:
                v = num(f.get(k))
                cols[k].append(float("nan") if v is None else v)
    R = {k: np.array(v, dtype="float64") for k, v in cols.items() if k in features or k in ("scan", "t", "rank", "mult")}
    R["pass"], R["zero"] = np.array(cols["pass"], dtype=bool), np.array(cols["gone"], dtype=bool)
    order = np.lexsort((R["scan"],))
    _, R["coin"] = np.unique(np.array(cols["a"], dtype=object), return_inverse=True)
    for k in list(R):
        R[k] = R[k][order]
    R["r"] = TICKET * (1 - FEE_SIDE) ** 2 * np.minimum(R["mult"], MULT_CAP) - TICKET
    R["hit3"] = R["mult"] >= 3.0
    return R


def window_mask(R, w):
    import numpy as np
    age = R["ageH"]
    return {"new": (age >= 0) & (age < 1), "1-6h": (age >= 1) & (age < 6), "6-24h": (age >= 6) & (age <= 24), "24h+": age > 24,
            "any": np.ones(len(age), bool), "gates": R["pass"]}[w]


def cond_mask(R, c):
    """c = [feature, "<=" or ">=", threshold]; an unknown number never passes."""
    v = R[c[0]]
    return v <= c[2] if c[1] == "<=" else v >= c[2]


def rule_mask(R, rule):
    m = window_mask(R, rule["w"])
    for c in rule["c"]:
        m = m & cond_mask(R, c)
    return m


def rule_text(rule):
    words = {"ageH": "age (h)", "logMc": "market cap", "liqMc": "liquidity/market cap", "volMc": "24h volume/market cap",
             "vol1Share": "last hour's share of the day's volume", "c1": "change 1h %", "c6": "change 6h %", "c24": "change 24h %",
             "m5": "change 5 min %", "buyShare": "buy share", "buyRatio1h": "buys/sells 1h", "buys1": "buys 1h", "srcN": "source lists",
             "jup.holders": "holders", "jup.holderChg24": "holder change 24h %", "jup.netBuyers24": "net buyers 24h",
             "jup.top10Pct": "top-10 wallets %", "jup.organic": "organic score", "pf.replies": "pump.fun replies", "pf.athRatio": "price/all-time high"}
    def val(k, v):
        if k == "logMc":                        # stored as log10 of the dollars: shown as dollars
            v = 10 ** v
            return "$%.0fk" % (v / 1e3) if v < 1e6 else "$%.2fM" % (v / 1e6)
        return "%.3g" % v
    parts = ["%s %s %s" % (words.get(c[0], c[0]), "≤" if c[1] == "<=" else "≥", val(c[0], c[2])) for c in rule["c"]]
    return "%s%s" % (WINDOWS[rule["w"]], (": " + " and ".join(parts)) if parts else "")


def entries(R, mask):
    """Index of the first row of each coin inside mask (rows are in scan order), in coin order. Without a sort: written backwards,
    the earliest row of a coin is the last write to its slot."""
    import numpy as np
    idx = np.flatnonzero(mask)
    if not len(idx):
        return idx
    n = R.get("ncoin")
    if n is None:
        n = R["ncoin"] = int(R["coin"].max()) + 1
    first = np.full(n, -1, dtype=np.int64)
    rev = idx[::-1]
    first[R["coin"][rev]] = rev
    return first[first >= 0]


def stats(R, ix, k_tests=1, seed=7):
    """n, days, avg per 20, win %, zero %, 3x %, total, and the bootstrap interval (two-sided 95%, Bonferroni over k_tests)."""
    import numpy as np
    n = int(len(ix))
    if not n:
        return {"n": 0}
    r = R["r"][ix]
    out = {"n": n, "days": int(len(set((R["scan"][ix] // DAY).tolist()))), "avg": round(float(r.mean()), 3), "win": round(100 * float((r > 0).mean()), 1),
           "zero": round(100 * float(R["zero"][ix].mean()), 1), "hit3": round(100 * float(R["hit3"][ix].mean()), 2), "total": round(float(r.sum()), 2)}
    if n >= 10:
        rng = np.random.default_rng(seed)
        means = np.sort(r[rng.integers(0, n, size=(BOOT, n))].mean(axis=1))
        a = 0.05 / max(1, k_tests)
        out["lo"] = round(float(means[int(a / 2 * BOOT)]), 3)
        out["hi"] = round(float(means[min(BOOT - 1, int((1 - a / 2) * BOOT))]), 3)
    return out


# ---------------------------------------------------------------------------------------------------------------- learn
def search(R, upto):
    """The best rule on the rows scored by upto (both halves count) -> (rule or None, its stats, how many rules were tried)."""
    import numpy as np, itertools
    known = R["t"] <= upto
    if known.sum() < 1000:
        return None, None, 0
    scans = np.unique(R["scan"][known])
    mid = scans[len(scans) // 2]
    halves = (known & (R["scan"] < mid), known & (R["scan"] >= mid))
    g = [entries(R, h & R["pass"]) for h in halves]
    gate3 = min(float(R["hit3"][ix].mean()) if len(ix) else 0.0 for ix in g)
    conds = []
    for k in FEATURES:
        v = R[k][known]
        v = v[~np.isnan(v)]
        if len(v) < 500:
            continue
        for q in sorted(set(np.quantile(v, QUANTS).tolist())):
            conds += [[k, "<=", round(q, 6)], [k, ">=", round(q, 6)]]
    cm = [cond_mask(R, c) for c in conds]
    combos = [()] + [(i,) for i in range(len(conds))] + [(i, j) for i, j in itertools.combinations(range(len(conds)), 2) if conds[i][0] != conds[j][0]]
    best, tried = None, 0
    for w in WINDOWS:
        sub = np.flatnonzero(window_mask(R, w) & known)      # the window's training rows only: every mask below is this short
        S = {k: R[k][sub] for k in ("coin", "r", "hit3")}
        hw = [h[sub] for h in halves]
        cms = [c[sub] for c in cm]
        for combo in combos:
            tried += 1
            m = None
            for i in combo:
                m = cms[i] if m is None else m & cms[i]
            sc, ok = [], True
            for h in hw:
                ix = entries(S, h if m is None else h & m)
                if len(ix) < MIN_HALF or float(S["hit3"][ix].mean()) < gate3:
                    ok = False
                    break
                sc.append(float(S["r"][ix].mean()))
            if ok and (best is None or min(sc) > best[0]):
                best = (min(sc), {"w": w, "c": [conds[i] for i in combo]}, sc)
    if best is None:
        return None, None, tried
    rule = best[1]
    st = stats(R, entries(R, known & rule_mask(R, rule)))
    st["halves"] = [round(x, 3) for x in best[2]]
    return rule, st, tried


# ---------------------------------------------------------------------------------------------------------------- test
def forward(R, ch, n_live):
    """A frozen rule on the rows after its frozenAt, next to the gates on the same rows -> the challenger dict with fwd, gates, verdict."""
    new = R["scan"] > ch["frozenAt"]
    fwd = stats(R, entries(R, new & rule_mask(R, ch["rule"])), k_tests=n_live)
    gates = stats(R, entries(R, new & R["pass"]))
    if fwd.get("n", 0) < MIN_FWD or fwd.get("days", 0) < MIN_DAYS:
        verdict = "watch"
    elif (fwd["avg"] > 0 and fwd["avg"] > (gates.get("avg") if gates.get("n") else -1e9) and fwd.get("lo", -1) > 0
          and fwd["hit3"] >= (gates.get("hit3") or 0.0)):
        verdict = "better"
    else:
        verdict = "worse"
    return dict(ch, fwd=fwd, gates=gates, verdict=verdict)


def mistakes(R, rule, now):
    """The top picks of the last LOOKBACK_DAYS days: their result, the losers and winners the rule would have kept or blocked."""
    import numpy as np
    pick = (R["rank"] == 1) & R["pass"] & (R["scan"] >= now - LOOKBACK_DAYS * DAY) & (R["t"] <= now)
    ix = np.flatnonzero(pick)
    out = {"days": LOOKBACK_DAYS, "picks": stats(R, ix)}
    if rule is not None and len(ix):
        keep = rule_mask(R, rule)[ix]
        lost, won = R["r"][ix] < 0, R["r"][ix] > 0
        out.update(lost=int(lost.sum()), won=int(won.sum()), lostKept=int((lost & keep).sum()), lostBlocked=int((lost & ~keep).sum()),
                   wonKept=int((won & keep).sum()), wonBlocked=int((won & ~keep).sum()), kept=stats(R, ix[keep]), blocked=stats(R, ix[~keep]))
    return out


# ---------------------------------------------------------------------------------------------------------------- run
def build(snaps, state, now, study=None):
    t0 = time.time()
    R = load(snaps)
    upto = float(R["t"][R["t"] <= now].max()) if len(R["t"]) else 0.0
    rule, st, tried = search(R, upto)
    chs = [c for c in (state.get("challengers") or []) if isinstance(c, dict) and isinstance(c.get("rule"), dict)]
    if rule is not None and not any(c["frozenAt"] >= upto for c in chs):
        chs.append({"id": time.strftime("%Y-%m-%d", time.gmtime(upto / 1000)), "rule": rule, "text": rule_text(rule), "frozenAt": upto, "train": st, "tried": tried})
    chs = chs[-MAX_CHALLENGERS:]
    tested = [forward(R, c, len(chs)) for c in chs]
    # the tested ones first, best per 20 first; then the ones still collecting, the most unseen coins first
    ranked = sorted(tested, key=lambda c: (0, -c["fwd"]["avg"]) if c["verdict"] != "watch" else (1, -c["fwd"].get("n", 0)))
    leader = next((c for c in ranked if c["verdict"] == "better"), None)
    tonight = tested[-1] if tested and rule is not None and tested[-1]["frozenAt"] == upto else None
    lead_rule = (leader or tonight or {}).get("rule")
    scans = R["scan"]
    doc = {"v": 1, "t": now, "secs": None, "fee": FEE_SIDE, "cap": MULT_CAP, "tried": tried, "windows": len(WINDOWS),
           "data": {"rows": int(len(scans)), "coins": int(R["coin"].max() + 1) if len(scans) else 0, "scans": int(len(set(scans.tolist()))),
                    "from": float(scans.min()) if len(scans) else None, "to": upto},
           "gatesAll": stats(R, entries(R, (R["t"] <= upto) & R["pass"])),
           "tonight": {k: tonight[k] for k in ("id", "text", "train", "frozenAt")} if tonight else None,
           "leader": {k: leader[k] for k in ("id", "text", "fwd", "gates", "train")} if leader else None,
           "challengers": [{k: c[k] for k in ("id", "text", "frozenAt", "fwd", "gates", "verdict")} for c in ranked[:10]],
           "nLive": len(chs), "mistakes": mistakes(R, lead_rule, now), "rules": {"minFwd": MIN_FWD, "minDays": MIN_DAYS, "minHalf": MIN_HALF}}
    if study:
        doc["study"] = study
    doc["secs"] = round(time.time() - t0, 1)
    return doc, {"v": 1, "challengers": [{k: c[k] for k in ("id", "rule", "text", "frozenAt", "train", "tried")} for c in chs]}


def write(out, name, obj):
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "." + name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, os.path.join(out, name))


def clean(o):
    """NaN and infinities to None (the doc is strict JSON)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description="the nightly filter search (fake money only; a report, the bot keeps its gates)")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--snaps", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--now", type=int, default=None)
    ap.add_argument("--study", default=None)
    a = ap.parse_args(argv)
    now = a.now or int(time.time() * 1000)
    try:
        state = json.load(open(os.path.join(a.out, STATE), encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    study = None
    if a.study:
        try:
            study = json.load(open(a.study, encoding="utf-8"))
        except (OSError, ValueError):
            study = None
    doc, state = build(a.snaps, state if isinstance(state, dict) else {}, now, study)
    write(a.out, DOC, clean(doc))
    write(a.out, STATE, clean(state))
    print(json.dumps({"ok": True, "rows": doc["data"]["rows"], "tried": doc["tried"], "tonight": (doc["tonight"] or {}).get("text"),
                      "leader": (doc["leader"] or {}).get("text"), "live": doc["nLive"], "secs": doc["secs"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
