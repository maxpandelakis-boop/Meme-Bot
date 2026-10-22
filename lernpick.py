#!/usr/bin/env python3
"""lernpick.py: the Learning Pick, a self-learning shadow bot. Fake money only: nothing here signs or sends a transaction, nothing the
scan, the Pick, the rocket hunter, the training or the big test reads comes from here, and nothing here is advice. It never changes the
real Pick or the Radar; it keeps its own paper account (db/memelern) and sends no push.

The question (the user, 22 Oct 2026: "so dass sie super schlau und erfahren werden"): can a bot that retrains itself every night on
everything seen so far beat the Pick? The old learning trader rewrote itself without a guard and lost (-21 %), so this one has one: a new
brain only takes over when it beats the current brain on days that neither of them has seen.

The brain has two parts:
  buy   which coin of the hourly scan to buy. A ridge regression on the scan's own factors (each turned into its rank within the scan,
        0 = lowest, 1 = highest, plus a "missing" flag), trained on the big test: every coin of every hourly scan with what 50 EUR in it
        was worth about 2 hours later after the paper fees (the multiple capped at MULT_CAP). Only coins of its universe count (UNIVERSE:
        1 hour to 3 days old, 24 h volume at least 10 % of the market cap, liquidity and market cap like the 2h profile's learnable coins,
        no hard block): without that the regression learns "buy coins that never move" (they lose only the fees). The ridge strength is
        chosen on the training rows' last 3 days. When the nightly filter search has a rule that beat the gates on unseen coins, "passes
        that rule" is one more input (fs.lead).
  sell  when to sell: one rule of the pre-registered grid SELL_GRID (stop, target, hold time, trailing stop), the one that made the most
        on the minute paths of every paper trade so far (the Pick's buys, the old new launches and launch radar, the shadow rules' paths,
        its own trades). It starts with the Pick's rule (-30 %, 11x, 6 h).

Every night (filtersearch.yml, after the filter search; train()):
  1. a candidate brain is trained on everything known by then and frozen (frozenAt = the newest scored scan).
  2. the oldest candidate whose part has enough unseen data is examined against the current brain (champion) on what came after the
     candidate's frozenAt only (neither brain has seen it): buy on at least EXAM_SCANS scans (what each brain's top coin made per scan,
     paired by scan), sell on at least EXAM_PATHS Pick-like trades (the Pick's, the shadow rules' and its own minute paths, paired by
     trade). The candidate's part takes over only when it made more and at least EXAM_CONF of BOOT bootstrap draws agree; otherwise the
     champion stays and the doc says so. Each candidate is examined once per part; one that waited EXAM_MAX_DAYS is dropped.
  The first night with no state replays every night since the data began (MIN_TRAIN_DAYS of training first), so the brain that trades
  tonight came out of the same procedure; those exams are marked replay.

Every hourly scan (bot.py cycle, after memebot run; buy()): the champion scores this scan's coins (the big-test snapshot the scan just
wrote, db/memesnap) and buys its best coin in the universe for TICKET, at the snapshot's price (the price the Pick pays), unless it
already holds it (then the next one). It also notes the scan's price of its open positions (marks).

Every peaks job (run()): a position whose PATH_H hours have passed gets its minute path from GeckoTerminal (one request, shadow.py's
method and peak.py's glitch filter) and is sold by its own rule replayed on it (shadow.replay: closes only, the target first, a stop at
the lower of the close and the level). A pool without minute candles is sold at its marks: the first scan price after the hold time,
0 when the liquidity went under 1,000 $ or no price came for GIVE_UP_H hours.

Files: lernpick.json (DOC: the brain, the candidates, the exams; the branch "lernpick", copied into db/memebot by the scan for the page
and the buy) and db/memelern/<pid>.json (the positions, results branch).

  python3 lernpick.py train --snaps <memesnapres> --res <results dir> --out <dir> [--fs <dir>] [--now ms]   (nightly)
  python3 lernpick.py buy --dir mb [--now ms]                                                               (scan)
  python3 lernpick.py run --dir mb [--now ms] [--deadline-s 60] [--mock URL]                               (peaks job)
  python3 lernpick.py summary --dir mb [--now ms]
"""
import argparse, glob, hashlib, json, math, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: num, load_json, load_docs, load_pairs, positions, pos_value, the paper rule, PAPER_RULE

V = 1
DOC = "lernpick.json"
COLL = ("db", "memelern")
H, MIN, DAY = 3_600_000, 60_000, 86_400_000
TICKET = 50.0                       # like the Pick's top pick (memebot.TOP_TICKET)
FEE_POS = {"grp": "hold", "paper": M.PAPER_RULE}     # the Pick's paper fees (1 %, at least 0.10 per trade) through memebot.pos_value
MULT_CAP = 11.0                     # the Pick's take-profit: one freak coin cannot carry a brain
CLIP = (-50.0, 150.0)               # the training label in EUR per 50 (up to 4x counts in full)
UNIVERSE = {"minAgeH": 1.0, "maxAgeH": 72.0, "minVolMc": 0.1, "minLiq": 15_000.0, "mc": (50_000.0, 2_000_000.0)}
HARD_BLOCK = ("price", "curve", "nodex", "honeypot", "notmeme", "copy")     # memebot.HARD_BLOCK
LEARN_FROM = 1791380700000          # memebot.LEARN_FROM: results scored before this taught nonsense
FEAT_MIN_SHARE = 0.05               # a factor needs a value in this share of the universe rows to be an input
LAMBDAS = (1e-3, 1e-2, 1e-1)
VAL_DAYS = 3                        # the ridge strength is chosen on the training rows' last days
MIN_TRAIN_DAYS = 5
MIN_TRAIN_ROWS = 2000
EXAM_SCANS, EXAM_PATHS = 30, 20
EXAM_CONF, BOOT = 0.80, 2000
EXAM_MAX_DAYS = 6
NIGHT_MS = 6 * H + 50 * MIN         # filtersearch.yml's start (06:50 UTC): the replay's nights
PATH_H = 6.0                        # hours of minute path per position (the longest hold in SELL_GRID)
SETTLE_MS = 2 * MIN
MAX_TRIES, GIVE_UP_H = 3, 48.0
MAX_ITEMS = 12                      # paths one peaks run asks for
SNAP_FRESH_MS = 45 * MIN            # the scan's snapshot must be this fresh for a buy
MARKS_KEEP = 12
EXAMS_KEEP = 60
DEAD_FILL = 0.5

STOPS, TARGETS, HOLDS = (None, 0.2, 0.3, 0.4), (1.5, 2.0, 3.0, 11.0), (2.0, 4.0, 6.0)


def _rule(stop, target, hours, trail=None):
    rid = ("TR%d" % round(100 * trail) if trail else ("S%d" % round(100 * stop) if stop else "S0")) + ("-T%g" % target if target else "-T0") + "-H%g" % hours
    return {"id": rid, "stop": stop, "target": target, "hours": hours, "trail": trail}


SELL_GRID = tuple([_rule(s, t, h) for s in STOPS for t in TARGETS for h in HOLDS]
                  + [_rule(0.3, t, h, trail=0.3) for t in (None, 11.0) for h in (4.0, 6.0)])
START_SELL = _rule(M.HOLD_STOP, 1.0 + M.HOLD_TP, M.HOLD_MAX_H)          # the Pick's own rule
assert START_SELL["id"] in {r["id"] for r in SELL_GRID} and max(r["hours"] for r in SELL_GRID) <= PATH_H


def num(v):
    return M.num(v)


def log(s):
    print(s, file=sys.stderr, flush=True)


def seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ms) // 1000))


def rule_text(r):
    """"stop −30 % · 11x · 6 h", "trailing 30 % · 6 h", "no stop · 2x · 4 h"."""
    if not r:
        return "–"
    bits = ["trailing stop %d %%" % round(100 * r["trail"])] if r.get("trail") else (["stop −%d %%" % round(100 * r["stop"])] if r.get("stop") else ["no stop"])
    bits.append(("target %gx" % r["target"]) if r.get("target") else "no target")
    bits.append("%g h" % r["hours"])
    return " · ".join(bits)


def money(frac_mult, ticket=TICKET):
    """What came back after the paper fees for sales [(frac, mult), ...], minus the ticket."""
    p = dict(FEE_POS, ticket=ticket)
    return round(sum(M.pos_value(p, f, m) for f, m in frac_mult) - ticket, 2)


def r_of(mult):
    """The big test's label: EUR per 50 after the paper fees when sold at mult (capped)."""
    return money([(1.0, min(max(mult, 0.0), MULT_CAP))])


# ---------------------------------------------------------------- the universe and the inputs
def in_universe(c):
    """Whether a snapshot coin (memesnap / memesnapres) is one the Learning Pick may buy."""
    if not isinstance(c, dict) or not isinstance(c.get("f"), dict):
        return False
    if any(str(w) in HARD_BLOCK for w in c.get("why") or []):
        return False
    liq, mc, f = num(c.get("liq")), num(c.get("mc")), c["f"]
    age, vm = num(f.get("ageH")), num(f.get("volMc"))
    U = UNIVERSE
    return (liq is not None and mc is not None and age is not None and vm is not None and liq >= U["minLiq"] and U["mc"][0] <= mc <= U["mc"][1]
            and U["minAgeH"] <= age <= U["maxAgeH"] and vm >= U["minVolMc"])


def fs_pass(rule, f):
    """1.0 when a coin's factors pass a filter-search rule (filter_search.rule_mask's meaning: its age window, every condition), else 0.0."""
    if not isinstance(rule, dict) or not isinstance(f, dict):
        return 0.0
    age = num(f.get("ageH"))
    w = rule.get("w")
    if w != "any":
        if age is None:
            return 0.0
        ok = {"new": 0 <= age < 1, "1-6h": 1 <= age < 6, "6-24h": 6 <= age <= 24, "24h+": age > 24}.get(w)
        if not ok:
            return 0.0        # "gates" (the bot's gates) is not known here: never passes
    for c in rule.get("c") or []:
        v = num(f.get(c[0]))
        if v is None or not (v <= c[2] if c[1] == "<=" else v >= c[2]):
            return 0.0
    return 1.0


def values(c, feats, fsrule=None):
    """A coin's raw inputs in the order of feats (nan when missing)."""
    f = c.get("f") or {}
    out = []
    for k in feats:
        if k == "fs.lead":
            out.append(fs_pass(fsrule, f))
        else:
            v = num(f.get(k))
            out.append(float("nan") if v is None else v)
    return out


def pct_block(V):
    """Each column's rank within the block (one scan's universe), ties averaged, scaled to 0..1 (the mid-rank over the count); a
    missing value sits at 0.5 (its flag says it is missing). numpy arrays in, out."""
    import numpy as np
    P = np.full(V.shape, 0.5)
    for j in range(V.shape[1]):
        v = V[:, j]
        ok = ~np.isnan(v)
        m = int(ok.sum())
        if m < 2:
            continue
        _, inv, cnt = np.unique(v[ok], return_inverse=True, return_counts=True)
        mid = (np.cumsum(cnt) - cnt) + cnt / 2.0
        P[ok, j] = mid[inv] / m
    return P


def design(V, groups):
    """[ranks within each group | missing flags | 1] for the rows V (raw inputs) grouped by scan (groups: list of row-index arrays)."""
    import numpy as np
    P = np.full(V.shape, 0.5)
    for ix in groups:
        P[ix] = pct_block(V[ix])
    return np.hstack([P, np.isnan(V).astype(float), np.ones((len(V), 1))])


def score(model, A):
    import numpy as np
    w = np.array(model["w"] + model["wn"] + [model["b"]], dtype=float)
    return A @ w


# ---------------------------------------------------------------- the big test rows
class Rows(object):
    """The universe rows of the big test, in scan order: scan (t0), t (scored), r (EUR per 50), mult (numpy columns), F (each row's factor
    dict); pick: {scan: EUR per 50 of the Pick's choice (rank 1 among the gate passers)}; bounds: each scan's row range. A(feats, fsrule):
    the design matrix for one input list, built once per list."""

    def __init__(self, rows, pick):
        import numpy as np
        rows = sorted(rows, key=lambda x: (x[0], x[1]))
        self.scan = np.array([x[0] for x in rows], dtype=float)
        self.t = np.array([x[1] for x in rows], dtype=float)
        self.mult = np.array([x[2] for x in rows], dtype=float)
        self.r = np.array([r_of(m) for m in self.mult.tolist()], dtype=float)
        self.F = [x[3] for x in rows]
        self.pick = pick
        self.scans, start = np.unique(self.scan, return_index=True)
        self.bounds = list(zip(start.tolist(), start[1:].tolist() + [len(rows)]))
        self._A = {}

    def A(self, feats, fsrule=None):
        import numpy as np
        key = (tuple(feats), json.dumps(fsrule, sort_keys=True) if "fs.lead" in feats else "")
        if key not in self._A:
            V_ = np.array([values({"f": f}, feats, fsrule) for f in self.F], dtype=float).reshape(len(self.F), len(feats))
            self._A[key] = design(V_, [np.arange(a, b) for a, b in self.bounds])
        return self._A[key]

    def scan_slices(self, mask=None):
        """[(scan, row slice)] of the scans whose rows are all inside mask (a boolean per row; a scan is cut whole: its scored time is one)."""
        out = []
        for (a, b), s in zip(self.bounds, self.scans.tolist()):
            if mask is None or bool(mask[a:b].all()):
                out.append((s, slice(a, b)))
        return out

    def feats(self, upto, fsrule=None):
        """The inputs of a brain trained by upto: every factor with a value in FEAT_MIN_SHARE of the rows scored by then (the market
        factors are the same for every coin of a scan, so they are left out), plus fs.lead with a filter-search rule."""
        n, seen = 0, {}
        for f, t in zip(self.F, self.t.tolist()):
            if t > upto:
                continue
            n += 1
            for k, v in f.items():
                if num(v) is not None:
                    seen[k] = seen.get(k, 0) + 1
        out = sorted(k for k, c in seen.items() if c >= FEAT_MIN_SHARE * max(1, n) and not k.startswith("mkt."))
        return out + (["fs.lead"] if fsrule else [])


def load_rows(snaps):
    """The big test (memesnapres chunks, streamed) -> Rows of the universe coins with a usable result."""
    sys.path.insert(0, os.path.join(HERE, "research"))
    import harness as HX        # the big test's loader rules (usable_result, priceless_at_snapshot)
    rows, pick = [], {}
    for fn in sorted(glob.glob(os.path.join(snaps, "*.json"))):
        doc = M.load_json(fn, None)
        if not isinstance(doc, dict) or not num(doc.get("t0")) or (num(doc.get("t")) or 0) < LEARN_FROM or not HX.usable_result(doc):
            continue
        t0, t1 = num(doc["t0"]), num(doc.get("t")) or num(doc["t0"])
        for c in doc.get("coins") or []:
            if not isinstance(c, dict) or num(c.get("mult")) is None or (c.get("gone") and HX.priceless_at_snapshot(c)):
                continue
            if c.get("pass") and num(c.get("rank")) == 1:
                pick[t0] = r_of(num(c["mult"]))
            if in_universe(c):
                rows.append((t0, t1, num(c["mult"]), {k: v for k, v in c["f"].items() if num(v) is not None}))
    return Rows(rows, pick)


# ---------------------------------------------------------------- training the buy part
def fit(A, y, lam):
    """Ridge (the intercept unpenalised) -> (w over ranks, w over missing flags, intercept)."""
    import numpy as np
    k = A.shape[1]
    pen = np.eye(k) * lam * len(y)
    pen[-1, -1] = 0.0
    w = np.linalg.solve(A.T @ A + pen, A.T @ np.clip(y, CLIP[0], CLIP[1]))
    n = (k - 1) // 2
    return [round(float(x), 5) for x in w[:n]], [round(float(x), 5) for x in w[n:2 * n]], round(float(w[-1]), 5)


def top1(model, R, slices):
    """{scan: EUR per 50 of the model's best coin in that scan} over the scans in slices."""
    import numpy as np
    s = score(model, R.A(model["feats"], model.get("fsRule")))
    out = {}
    for sc, sl in slices:
        i = int(np.argmax(s[sl]))
        out[sc] = float(R.r[sl][i])
    return out


def train_buy(R, upto, fsrule=None):
    """The buy part trained on the rows scored by upto -> model dict or None (too little data)."""
    import numpy as np
    known = R.t <= upto
    if int(known.sum()) < MIN_TRAIN_ROWS or not known.any() or R.scan[known].max() - R.scan[known].min() < MIN_TRAIN_DAYS * DAY:
        return None
    feats = R.feats(upto, fsrule)
    A = R.A(feats, fsrule)
    vstart = R.scan[known].max() - VAL_DAYS * DAY
    fit_m, val_sl = known & (R.t <= vstart), R.scan_slices(known & (R.scan > vstart))
    best = None
    if int(fit_m.sum()) >= MIN_TRAIN_ROWS // 2 and val_sl:
        for lam in LAMBDAS:
            w, wn, b = fit(A[fit_m], R.r[fit_m], lam)
            v = float(np.mean(list(top1({"feats": feats, "fsRule": fsrule, "w": w, "wn": wn, "b": b}, R, val_sl).values())))
            if best is None or v > best[0]:
                best = (v, lam)
    lam = best[1] if best else LAMBDAS[1]
    w, wn, b = fit(A[known], R.r[known], lam)
    return {"feats": feats, "w": w, "wn": wn, "b": b, "lam": lam, "val": round(best[0], 3) if best else None, "n": int(known.sum()),
            "scans": int(len(np.unique(R.scan[known]))), "fsRule": fsrule or None}


def effects(model, n=None):
    """The inputs by how much the model moves a coin from the bottom to the top of its scan on them, biggest first:
    [(factor, EUR per 50)] (positive: it prefers a higher value)."""
    out = sorted(((k, round(w, 3)) for k, w in zip(model["feats"], model["w"])), key=lambda kv: -abs(kv[1]))
    return out[:n] if n else out


def changes(new, old, n=3):
    """The inputs whose effect changed most from old to new: [(factor, old EUR, new EUR)]."""
    if not old or "feats" not in old:
        return [(k, None, v) for k, v in effects(new, n)]
    o = dict(zip(old["feats"], old["w"]))
    d = sorted(((k, o.get(k), v) for k, v in zip(new["feats"], new["w"])), key=lambda x: -abs(x[2] - (x[1] or 0.0)))
    return [(k, None if a is None else round(a, 3), round(b, 3)) for k, a, b in d[:n]]


# ---------------------------------------------------------------- the minute paths and the sell part
def replay(doc, rule):
    import shadow as SH       # the shadow rules' replay: closes only, target first, a stop at min(close, level), dead pools
    return SH.replay(doc, rule)


def path_money(doc, rule):
    """EUR per 50 of one minute path under one rule, or None (not replayable)."""
    res = replay(doc, rule)
    if res is None:
        return None
    return money([(s[1], s[2]) for s in res["sales"]])


def load_paths(res_dir):
    """Every usable minute path of a paper trade: db/memepath (the Pick's buys "hold", the old new launches "young" and launch radar
    "radar"), db/memeshadow (the Pick's buys again, 12 h: used when memepath lacks the buy), db/memelern (its own) -> [{"id", "grp",
    "entryAt", "end", "pick": True for the Pick-like ones (the hourly market), "doc"}] with at least PATH_H hours of path."""
    out, seen = [], set()
    for fn in sorted(glob.glob(os.path.join(res_dir, "db", "memelern", "*.json"))):
        d = M.load_json(fn, None)
        if isinstance(d, dict) and isinstance(d.get("c"), list) and num(d.get("cpx")) and num(d.get("entryAt")):
            out.append({"id": "lern:" + str(d.get("pid")), "grp": "lern", "entryAt": int(d["entryAt"]), "end": int(d["entryAt"] + PATH_H * H), "pick": True, "doc": d})
    for fn in sorted(glob.glob(os.path.join(res_dir, "db", "memepath", "*.json"))):
        d = M.load_json(fn, None)
        if not isinstance(d, dict) or not isinstance(d.get("c"), list) or not num(d.get("cpx")) or not num(d.get("entryAt")):
            continue
        if (num(d.get("end")) or 0) - d["entryAt"] < PATH_H * H - MIN:
            continue
        g = str(d.get("grp") or "")
        out.append({"id": "path:" + str(d.get("id")), "grp": g, "entryAt": int(d["entryAt"]), "end": int(d["end"]), "pick": g == "hold", "doc": d})
        seen.add(str(d.get("id")))
    for fn in sorted(glob.glob(os.path.join(res_dir, "db", "memeshadow", "*.json"))):
        d = M.load_json(fn, None)
        if isinstance(d, dict) and d.get("state") == "ok" and isinstance(d.get("c"), list) and str(d.get("pid")) not in seen:
            out.append({"id": "shadow:" + str(d.get("pid")), "grp": "hold", "entryAt": int(d["entryAt"]), "end": int(d.get("end") or d["entryAt"] + 12 * H), "pick": True, "doc": d})
    return sorted(out, key=lambda p: (p["entryAt"], p["id"]))


def train_sell(paths, upto):
    """The sell part: the grid rule that made the most per trade on every path complete by upto (each trade once) -> (rule, its EUR
    per trade, n) or (None, None, n) with fewer than EXAM_PATHS trades. A path any rule cannot replay is left out of all."""
    done = [p for p in paths if p["end"] + SETTLE_MS <= upto]
    table = []
    for p in done:
        row = [path_money(p["doc"], r) for r in SELL_GRID]
        if all(v is not None for v in row):
            table.append(row)
    if len(table) < EXAM_PATHS:
        return None, None, len(table)
    avg = [sum(col) / len(table) for col in zip(*table)]
    i = max(range(len(SELL_GRID)), key=lambda j: (round(avg[j], 6), SELL_GRID[j]["id"] == START_SELL["id"]))
    return dict(SELL_GRID[i]), round(avg[i], 3), len(table)


# ---------------------------------------------------------------- the exam
def paired(a, b, sid):
    """Paired differences a - b -> {"n", "new", "old", "diff", "p": share of BOOT bootstrap draws with a positive mean difference}."""
    import numpy as np
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    d = a - b
    rng = np.random.default_rng(seed("exam", sid))
    p = float((d[rng.integers(0, len(d), size=(BOOT, len(d)))].mean(axis=1) > 0).mean()) if len(d) else 0.0
    return {"n": int(len(d)), "new": round(float(a.mean()), 3) if len(d) else None, "old": round(float(b.mean()), 3) if len(d) else None,
            "diff": round(float(d.mean()), 3) if len(d) else None, "p": round(p, 3)}


def won(x):
    return x["n"] > 0 and x["diff"] > 0 and x["p"] >= EXAM_CONF


def exam_buy(R, cand, champ, upto):
    """The candidate's and the champion's buy parts on the scans after the candidate's frozenAt, scored by upto -> exam dict or None
    (fewer than EXAM_SCANS scans yet)."""
    sl = R.scan_slices((R.scan > cand["frozenAt"]) & (R.t <= upto))
    if len(sl) < EXAM_SCANS:
        return None
    a, b = top1(cand["buy"], R, sl), top1(champ, R, sl)
    keys = sorted(a)
    x = paired([a[k] for k in keys], [b[k] for k in keys], "buy|" + cand["id"])
    pk = [R.pick[k] for k in keys if R.pick.get(k) is not None]
    x["pick"] = round(sum(pk) / len(pk), 3) if pk else None
    x["unit"] = "scan"
    return x


def exam_sell(paths, cand, champ_rule, upto):
    """The candidate's and the champion's sell rules on the Pick-like trades bought after the candidate's frozenAt whose paths are
    complete by upto -> exam dict or None (fewer than EXAM_PATHS such trades yet)."""
    a, b = [], []
    for p in paths:
        if not p["pick"] or p["entryAt"] <= cand["frozenAt"] or p["end"] + SETTLE_MS > upto:
            continue
        x, y = path_money(p["doc"], cand["sell"]), path_money(p["doc"], champ_rule)
        if x is not None and y is not None:
            a.append(x)
            b.append(y)
    if len(a) < EXAM_PATHS:
        return None
    out = paired(a, b, "sell|" + cand["id"])
    out["unit"] = "trade"
    return out


def night(state, R, paths, upto, now, replayed=False, fsrule=None):
    """One night: examine the due candidates, then freeze tonight's. Changes state in place; returns the night's exams."""
    exams = []
    for cand in list(state["pending"]):
        for part in ("buy", "sell"):
            if cand.get(part + "Done"):
                continue
            if part == "buy":
                x = exam_buy(R, cand, state["buy"], upto) if cand.get("buy") else None
            else:
                x = exam_sell(paths, cand, state["sell"], upto) if cand.get("sell") else None
            if x is None and not cand.get(part):
                cand[part + "Done"] = True                    # nothing to examine (the part was not trained)
                continue
            if x is None:
                if now - cand["frozenAt"] > EXAM_MAX_DAYS * DAY:
                    cand[part + "Done"] = True
                    exams.append({"t": now, "id": cand["id"], "part": part, "won": False, "replay": replayed, "why": "too little unseen data in %d days" % EXAM_MAX_DAYS})
                continue
            cand[part + "Done"] = True
            ok = won(x)
            e = dict(x, t=now, id=cand["id"], part=part, won=ok, replay=replayed, same=bool(x["diff"] == 0 and (part == "buy" or cand["sell"]["id"] == state["sell"]["id"])))
            if part == "buy":
                e["changed"] = changes(cand["buy"], state["buy"]) if ok else []
                if ok:
                    state["buy"] = dict(cand["buy"], id=cand["id"], frozenAt=cand["frozenAt"], since=now)
            else:
                e["rule"], e["was"] = cand["sell"]["id"], state["sell"]["id"]
                if ok:
                    state["sell"] = dict(cand["sell"], since=now, frozenAt=cand["frozenAt"], cid=cand["id"])
            exams.append(e)
        if cand.get("buyDone") and cand.get("sellDone"):
            state["pending"].remove(cand)
    cid = day(upto)
    if not any(c["id"] == cid for c in state["pending"]) and upto > (state.get("lastFrozen") or 0):
        buy = train_buy(R, upto, fsrule)
        sell, sell_avg, n_paths = train_sell(paths, upto)
        if buy or sell:
            cand = {"id": cid, "frozenAt": upto, "buy": buy, "sell": sell, "sellAvg": sell_avg, "sellN": n_paths, "night": now}
            if state.get("buy") is None and buy:              # the very first brain: nothing to beat yet, it starts trading
                state["buy"] = dict(buy, id=cid, frozenAt=upto, since=now, start=True)
                cand["buy"], cand["buyDone"] = None, True
            if state.get("sell") is None:
                state["sell"] = dict(START_SELL, since=now, frozenAt=None, cid="start")
            state["pending"].append(cand)
            state["lastFrozen"] = upto
    state["exams"] = (state.get("exams") or []) + exams
    state["exams"] = state["exams"][-EXAMS_KEEP:]
    state["nights"] = int(state.get("nights") or 0) + 1
    return exams


def fs_leader(fs_dir):
    """The nightly filter search's leading rule, only when it beat the gates on unseen coins (verdict "better"), with its id -> rule dict
    {"w", "c", "id", "text"} or None."""
    if not fs_dir:
        return None
    doc = M.load_json(os.path.join(fs_dir, "filtersearch.json"), None)
    st = M.load_json(os.path.join(fs_dir, "filtersearch-state.json"), None)
    lead = (doc or {}).get("leader") if isinstance(doc, dict) else None
    if not isinstance(lead, dict) or not isinstance(st, dict):
        return None
    for c in st.get("challengers") or []:
        if isinstance(c, dict) and c.get("id") == lead.get("id") and isinstance(c.get("rule"), dict):
            return dict(c["rule"], id=c["id"], text=c.get("text"))
    return None


def trades_count(res_dir):
    """How many paper trades each source has (for the page's "learns from" line)."""
    out = {}
    for name, coll in (("pick", "memepos"), ("lern", "memelern"), ("radarOld", "memeradarpaper"), ("traders", "memetrader")):
        out[name] = len(glob.glob(os.path.join(res_dir, "db", coll, "*.json")))
    pos = M.load_docs(res_dir, "memepos")
    out["pick"] = sum(1 for p in pos.values() if p.get("grp") == "hold")
    out["young"] = sum(1 for p in pos.values() if p.get("grp") == "young")
    rk = M.load_json(os.path.join(res_dir, "db", "memebot", "rocket.json"), {}) or {}
    book = rk.get("book") if isinstance(rk, dict) else None
    out["rocket"] = len((book or {}).get("closed") or []) + len((book or {}).get("open") or {}) if isinstance(book, dict) else 0
    return out


def train(snaps, res_dir, out_dir, now, fs_dir=None):
    """The nightly step (see the module doc) -> the doc written to out_dir/DOC."""
    t0 = time.time()
    old = M.load_json(os.path.join(out_dir, DOC), None)
    state = old if isinstance(old, dict) and old.get("v") == V and isinstance(old.get("pending"), list) else None
    fsrule = fs_leader(fs_dir)
    R = load_rows(snaps)
    paths = load_paths(res_dir)
    if not len(R.t):
        raise SystemExit("no big-test rows in the universe")
    upto_now = float(R.t[R.t <= now].max())
    if state is None:
        state = {"v": V, "pending": [], "exams": [], "buy": None, "sell": None, "nights": 0, "started": now}
        first = R.scan.min() // DAY * DAY + (MIN_TRAIN_DAYS + 1) * DAY + NIGHT_MS
        N = first
        while N < now - 12 * H:                               # the replay: every past night at 06:50 UTC
            sel = R.t <= N
            if sel.any():
                night(state, R, paths, float(R.t[sel].max()), N, replayed=True, fsrule=fsrule)
            N += DAY
    tonight = night(state, R, paths, upto_now, now, fsrule=fsrule)
    state.update(t=now, secs=round(time.time() - t0, 1), upto=upto_now, fs=({"id": fsrule.get("id"), "text": fsrule.get("text")} if fsrule else None),
                 data={"rows": int(len(R.t)), "scans": int(len(R.scans)), "from": float(R.scan.min()), "to": upto_now, "feats": len((state.get("buy") or {}).get("feats") or []),
                       "paths": {g: sum(1 for p in paths if p["grp"] == g) for g in sorted({p["grp"] for p in paths})},
                       "trades": trades_count(res_dir)},
                 tonight=[{k: e.get(k) for k in ("id", "part", "won", "n", "new", "old", "diff", "p", "why")} for e in tonight],
                 universe=UNIVERSE, grid=len(SELL_GRID))
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "." + DOC + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean(state), f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, os.path.join(out_dir, DOC))
    return state


def clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


# ---------------------------------------------------------------- the positions
def coll_dir(d):
    return os.path.join(d, *COLL)


def safe_id(pid):
    pid = str(pid)
    return pid if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$", pid) and ".." not in pid else None


def positions(d):
    """{pid: position} of db/memelern."""
    out = {}
    for fn in sorted(glob.glob(os.path.join(coll_dir(d), "*.json"))):
        doc = M.load_json(fn, None)
        if isinstance(doc, dict) and doc.get("v") == V and doc.get("pid"):
            out[str(doc["pid"])] = doc
    return out


def write_pos(d, doc):
    """db/memelern/<pid>.json whole or not at all (a temp file outside the synced folder, then a rename)."""
    tmp_dir = os.path.join(d, ".lerntmp")
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(coll_dir(d), exist_ok=True)
    tmp = os.path.join(tmp_dir, doc["pid"] + ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean(doc), f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, os.path.join(coll_dir(d), doc["pid"] + ".json"))


def brain_doc(d):
    doc = M.load_json(os.path.join(d, "db", "memebot", DOC), None)
    return doc if isinstance(doc, dict) and doc.get("v") == V else None


def this_scan(d, now):
    """The coins of this scan's big-test snapshot (db/memesnap chunks with the newest time, at most SNAP_FRESH_MS before now) -> (t, coins)."""
    best, coins = None, []
    for fn in glob.glob(os.path.join(d, "db", "memesnap", "*.json")):
        doc = M.load_json(fn, None)
        t = num((doc or {}).get("t")) if isinstance(doc, dict) else None
        if t is None or t > now + MIN or now - t > SNAP_FRESH_MS:
            continue
        if best is None or t > best:
            best, coins = t, []
        if t == best:
            coins += [c for c in doc.get("coins") or [] if isinstance(c, dict)]
    return best, coins


def buy(d, now):
    """This scan's buy (see the module doc) -> the summary line (dict). Never raises."""
    out = {"ok": True, "bought": None}
    if os.environ.get("MEMEBOT_LERNPICK", "1").strip() == "0":
        out["why"] = "switched off (repository variable MEMEBOT_LERNPICK=0)"
        return out
    try:
        B = brain_doc(d)
        model = (B or {}).get("buy")
        sell = (B or {}).get("sell") or START_SELL
        pos = positions(d)
        t, coins = this_scan(d, now)
        pairs = M.load_pairs(d) if os.path.exists(os.path.join(d, "pairs.json")) else {}
        for pid, p in pos.items():                            # the scan's price of every open position (the fallback for a sale)
            if p.get("state") != "open":
                continue
            pr = pairs.get(p.get("addr")) or {}
            px, liq = num(pr.get("priceUsd")), num((pr.get("liquidity") or {}).get("usd") if isinstance(pr.get("liquidity"), dict) else pr.get("liquidityUsd"))
            if px or liq is not None:
                p["marks"] = ((p.get("marks") or []) + [[int(now), px, liq]])[-MARKS_KEEP:]
                write_pos(d, p)
        if not model or not model.get("feats"):
            out["why"] = "no brain yet (the first nightly training makes one)"
            return out
        if t is None:
            out["why"] = "no fresh snapshot of this scan"
            return out
        uni = [c for c in coins if in_universe(c) and num(c.get("px"))]
        if not uni:
            out["why"] = "no coin of this scan in the universe"
            return out
        import numpy as np
        V_ = np.array([values(c, model["feats"], model.get("fsRule")) for c in uni], dtype=float)
        s = score(model, design(V_, [np.arange(len(uni))]))
        if any(int(num(p.get("t")) or 0) == int(t) for p in pos.values()):
            out["why"] = "already bought this scan"
            return out
        held = {p.get("addr") for p in pos.values() if p.get("state") == "open"}
        order = sorted(range(len(uni)), key=lambda i: (-float(s[i]), str(uni[i].get("a"))))
        pick = None
        for i in order:
            c = uni[i]
            pr = pairs.get(c.get("a")) or {}
            if c.get("a") in held or not pr.get("pairAddress"):
                continue
            pick = (i, c, pr)
            break
        if pick is None:
            out["why"] = "every scored coin is held or has no pool address"
            return out
        i, c, pr = pick
        P = design(V_, [np.arange(len(uni))])[i]
        top = sorted(((k, float(model["w"][j]) * (float(P[j]) - 0.5)) for j, k in enumerate(model["feats"])), key=lambda kv: -kv[1])[:4]
        pid = "%s-l-%s-%s" % (time.strftime("%Y-%m-%dT%H%M", time.gmtime(t / 1000)), M.slug(c.get("s")), str(c.get("a"))[:6])
        same = [q for q in M.load_docs(d, "memepos").values() if q.get("grp") == "hold" and num(q.get("t")) == t]
        doc = {"v": V, "pid": pid, "sym": str(c.get("s") or "?")[:24], "addr": c.get("a"), "pair": pr.get("pairAddress"), "dex": pr.get("dexId"),
               "t": int(t), "entryAt": int(t), "px": num(c["px"]), "mc": num(c.get("mc")), "liq": num(c.get("liq")), "ageH": num(c["f"].get("ageH")),
               "ticket": TICKET, "brain": model.get("id"), "rule": {k: sell.get(k) for k in ("id", "stop", "target", "hours", "trail")},
               "score": round(float(s[i]), 3), "of": len(uni), "why": [[k, round(v, 3)] for k, v in top if v > 0],
               "pick": same[0].get("sym") if same else None, "samePick": bool(same and same[0].get("addr") == c.get("a")),
               "state": "open", "tries": 0, "marks": [[int(now), num(c["px"]), num(c.get("liq"))]]}
        if not safe_id(pid) or os.path.exists(os.path.join(coll_dir(d), pid + ".json")):
            out["why"] = "already bought this scan"
            return out
        write_pos(d, doc)
        out.update(bought=doc["sym"], pid=pid, score=doc["score"], of=len(uni), samePick=doc["samePick"])
    except Exception as e:      # a shadow bot: the scan must go on
        out.update(ok=False, err="%s: %s" % (type(e).__name__, str(e)[:200]))
        log("lernpick buy: %s" % out["err"])
    return out


# ---------------------------------------------------------------- the sales
def sell_from_marks(p, now):
    """A position without minute candles, sold at its marks: the first scan price at or after its hold time ("time"), 0 when the
    liquidity fell under 1,000 $ ("rug"), 0 after GIVE_UP_H hours without any price ("no price") -> (sales, why) or None (wait)."""
    px0 = num(p.get("px"))
    end = p["entryAt"] + int(p["rule"]["hours"] * H)
    marks = [m for m in p.get("marks") or [] if isinstance(m, list) and len(m) >= 3 and num(m[0])]
    for m in marks:
        if num(m[0]) > p["entryAt"] and num(m[2]) is not None and num(m[2]) < 1000:
            return [[int(m[0]), 1.0, 0.0, "rug"]], "rug"
    for m in marks:
        if num(m[0]) >= end and num(m[1]) and px0:
            return [[int(m[0]), 1.0, min(num(m[1]) / px0, MULT_CAP), "time"]], "time"
    if now >= end + GIVE_UP_H * H:
        return [[int(now), 1.0, 0.0, "noprice"]], "noprice"
    return None


def book_sale(p, sales, src, now):
    p.update(state="sold", sales=sales, why=sales[-1][3], out=int(max(s[0] for s in sales)), src=src, upd=int(now),
             eur=money([(s[1], s[2]) for s in sales], num(p.get("ticket")) or TICKET), top=max(s[2] for s in sales))
    return p


def run(d, now, deadline_s=60.0, mock=None):
    """The due positions' minute paths and sales -> the summary line (dict). Never raises."""
    t0 = time.time()
    out = {"ok": True, "due": 0, "sold": 0, "marks": 0, "waiting": 0, "why": "nothing due"}
    try:
        import fetch as F
        import peak as P
        import shadow as SH
        due = [p for p in positions(d).values() if p.get("state") == "open" and now >= p["entryAt"] + int(PATH_H * H) + SETTLE_MS]
        due.sort(key=lambda p: (p["entryAt"], p["pid"]))
        out["due"] = len(due)
        if not due:
            return out
        http = F.Http(mock, pause=0, log=log)
        until, why = t0 + float(deadline_s), "all asked"
        for p in due[:MAX_ITEMS]:
            if P.GT_HOST in http.dead:
                why = P.GT_GONE
                break
            end = p["entryAt"] + int(PATH_H * H)
            st, j = P.gt_get(http, SH.gt_url(p["pair"], end), until)
            if st in ("deadline", "limited", "dead", "share"):
                why = {"deadline": "deadline", "limited": "GeckoTerminal rate limit", "dead": P.GT_GONE, "share": P.GT_SHARE}[st]
                break
            rows = P.ohlcv_rows(j, P.gt_before(end), 1) if st == "ok" else []
            got = None
            if st == "ok" and rows and P.covers(rows, p["entryAt"], 1):
                r = P.peak_of(rows, p["entryAt"], end, num(p.get("px")), None, (), liq0=num(p.get("liq")), mc0=num(p.get("mc")), res=1)
                if r.get("state") == "ok":
                    path = P.path_of(rows, p["entryAt"], end, r, "lern", "lern", p["pid"])
                    if path and path.get("c"):
                        got = path
            if got:
                p.update(cpx=got["cpx"], dead=got["dead"], c=got["c"])
                res = SH.replay(p, p["rule"])
                if res is not None:
                    write_pos(d, book_sale(p, res["sales"], "candles", now))
                    out["sold"] += 1
                    continue
            if st in ("ok", "empty"):
                p["tries"] = int(p.get("tries") or 0) + 1
            if p["tries"] >= MAX_TRIES or now >= end + GIVE_UP_H * H:
                m = sell_from_marks(p, now)
                if m:
                    write_pos(d, book_sale(p, m[0], "marks", now))
                    out["marks"] += 1
                    continue
            p["upd"] = int(now)
            write_pos(d, p)
            out["waiting"] += 1
        out["why"] = why
    except Exception as e:
        out.update(ok=False, err="%s: %s" % (type(e).__name__, str(e)[:200]))
        log("lernpick run: %s (the positions written so far stay)" % out["err"])
    out["secs"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------- the summary (the page)
def last_mark(p):
    for m in reversed(p.get("marks") or []):
        if isinstance(m, list) and len(m) >= 2 and num(m[1]):
            return int(m[0]), num(m[1])
    return None, None


def summary(d, now=None):
    """The Learning Pick's account, the comparison with the Pick and the Radar since its first buy, and the brain. Reads only."""
    now = int(now or time.time() * 1000)
    pos = sorted(positions(d).values(), key=lambda p: (-p["t"], p["pid"]))
    sold = [p for p in pos if p.get("state") == "sold"]
    opn = [p for p in pos if p.get("state") == "open"]
    val = 0.0
    for p in opn:
        _, px = last_mark(p)
        mult = (px / num(p["px"])) if px and num(p.get("px")) else 0.0
        p["_now"] = round(mult, 4) if px else None
        val += M.pos_value(dict(FEE_POS, ticket=num(p.get("ticket")) or TICKET), 1.0, min(mult, MULT_CAP)) if px else 0.0
    inv = sum(num(p.get("ticket")) or TICKET for p in pos)
    back = sum((num(p.get("eur")) or 0.0) + (num(p.get("ticket")) or TICKET) for p in sold)
    since = min((p["t"] for p in pos), default=None)
    me = {"n": len(pos), "open": len(opn), "sold": len(sold), "won": sum(1 for p in sold if (num(p.get("eur")) or 0) > 0.004),
          "invested": round(inv, 2), "back": round(back, 2), "openValue": round(val, 2), "pnl": round(back + val - inv, 2),
          "closedPnl": round(sum(num(p.get("eur")) or 0.0 for p in sold), 2),
          "per": round(sum(num(p.get("eur")) or 0.0 for p in sold) / len(sold), 2) if sold else None,
          "x2": sum(1 for p in sold if (num(p.get("top")) or 0) >= 2.0), "samePick": sum(1 for p in pos if p.get("samePick"))}
    # the Pick since the same start: its paper buys (grp hold) from the first Learning Pick buy on, the closed ones by their exits
    pick = {"n": 0, "sold": 0, "closedPnl": 0.0, "won": 0}
    if since is not None:
        for p in M.positions(d).values():
            if p.get("grp") != "hold" or (num(p.get("t")) or 0) < since:
                continue
            pick["n"] += 1
            if p["_left"] <= 1e-9:
                r = sum(num(e.get("eur")) or 0.0 for e in p["_exits"]) - (num(p.get("ticket")) or 0.0)
                pick["sold"] += 1
                pick["closedPnl"] += r
                pick["won"] += 1 if r > 0.004 else 0
    pick["closedPnl"] = round(pick["closedPnl"], 2)
    pick["per"] = round(pick["closedPnl"] / pick["sold"], 2) if pick["sold"] else None
    radar = {"n": 0, "sold": 0, "closedPnl": 0.0, "won": 0, "ticket": None}
    rk = M.load_json(os.path.join(d, "db", "memebot", "rocket.json"), {}) or {}
    book = rk.get("book") if isinstance(rk, dict) and isinstance(rk.get("book"), dict) else {}
    if since is not None:
        for p in (book.get("closed") or []):
            if isinstance(p, dict) and (num(p.get("t")) or 0) >= since:
                radar["n"] += 1
                radar["sold"] += 1
                radar["closedPnl"] += num(p.get("eur")) or 0.0
                radar["won"] += 1 if (num(p.get("eur")) or 0) > 0.004 else 0
        radar["n"] += sum(1 for p in (book.get("open") or {}).values() if isinstance(p, dict) and (num(p.get("t")) or 0) >= since)
    radar["closedPnl"] = round(radar["closedPnl"], 2)
    radar["per"] = round(radar["closedPnl"] / radar["sold"], 2) if radar["sold"] else None
    try:
        import rocket as RK
        radar["ticket"] = RK.TICKET
    except Exception:
        radar["ticket"] = 20.0
    return {"v": V, "t": now, "since": since, "ticket": TICKET, "me": me, "pick": pick, "radar": radar, "brain": brain_brief(brain_doc(d)),
            "trades": [{k: p.get(k) for k in ("pid", "sym", "addr", "pair", "t", "px", "state", "eur", "why", "top", "rule", "brain", "samePick", "pick", "_now", "of", "score", "src")}
                       for p in pos]}


def brain_brief(B):
    """What the page shows of the brain doc: the two champions (the buy part without its weights, its strongest inputs instead), the
    exams newest first, the candidates waiting, the data counts."""
    if not isinstance(B, dict):
        return None
    buy = B.get("buy") if isinstance(B.get("buy"), dict) else None
    out = {k: B.get(k) for k in ("t", "secs", "upto", "fs", "data", "nights", "started", "universe", "grid")}
    out["buy"] = {k: buy.get(k) for k in ("id", "frozenAt", "since", "start", "lam", "n", "scans", "val")} if buy else None
    if buy and buy.get("feats") and buy.get("w"):
        out["buy"]["top"] = effects(buy, 6)
    out["sell"] = B.get("sell")
    out["exams"] = sorted([e for e in B.get("exams") or [] if isinstance(e, dict)], key=lambda e: (-(num(e.get("t")) or 0), str(e.get("part"))))
    out["pending"] = [{"id": c.get("id"), "frozenAt": c.get("frozenAt"), "buy": bool(c.get("buy")) and not c.get("buyDone"),
                       "sell": (c.get("sell") or {}).get("id") if not c.get("sellDone") else None} for c in B.get("pending") or [] if isinstance(c, dict)]
    out["tonight"] = B.get("tonight")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="the Learning Pick: a self-learning shadow bot (fake money, its own paper account)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="the nightly step: examine, freeze, write the doc")
    t.add_argument("--snaps", required=True)
    t.add_argument("--res", required=True, help="the results branch's folder (minute paths, positions)")
    t.add_argument("--out", required=True)
    t.add_argument("--fs", default=None, help="the filtersearch branch's folder (its leading rule feeds the brain)")
    t.add_argument("--now", type=int, default=None)
    for name in ("buy", "run", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--dir", default="mb")
        s.add_argument("--now", type=int, default=None)
        if name == "run":
            s.add_argument("--deadline-s", type=float, default=60.0)
            s.add_argument("--mock", default=None)
    a = ap.parse_args(argv)
    now = a.now if a.now is not None else int(time.time() * 1000)
    if a.cmd == "train":
        st = train(a.snaps, a.res, a.out, now, a.fs)
        print(json.dumps({"ok": True, "secs": st["secs"], "rows": st["data"]["rows"], "buy": (st.get("buy") or {}).get("id"),
                          "sell": (st.get("sell") or {}).get("id"), "pending": [c["id"] for c in st["pending"]], "tonight": st["tonight"]}))
    elif a.cmd == "buy":
        print(json.dumps(buy(a.dir, now)), flush=True)
    elif a.cmd == "run":
        print(json.dumps(run(a.dir, now, a.deadline_s, a.mock)), flush=True)
    else:
        print(json.dumps(summary(a.dir, now), default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
