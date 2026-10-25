"""Ten bots with 100 EUR each (fake money only): research/tournament/PREREG-TOURNAMENT-2026-10-25.md.

  rows <monthsdata dir> <monthsh2 dir> <history2 gap_minutes.npy> <out dir>   every bot's buys and sales per coin -> rows.pkl
  run <out dir>                                                                the 100 EUR accounts, the ranking, the test -> result.json

The coins, the windows, the features and the Pick-type entry are research/check_months.py's (PR #42) and
research/chartexit/check_chartexit.py's (PR #46): five-minute USD candles of the first 48 hours after graduation, the entry at the
close of the last finished candle, the path from the first candle wholly after it. Nothing is bought; no network. Needs pandas,
pyarrow."""
import glob, heapq, json, math, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chartexit"))
import check_chartexit as CX          # replay_np (the chart exit, the live pick) and its window table

BAR, MIN, H = 300_000, 60_000, 3_600_000
WN = CX.WN
window = CX.window
WICK_X = 5.0
NB = 300                       # five-minute candles kept after the entry (24 h = 288)
HOURS = (1, 2, 3, 6, 12, 24)
CHART = (0.50, 0.15, 1.5, 0.0, 0, 0.0, 1, 6)        # stop, trail, arm, lock, stale_h, stale_g, fade (1 = drop), T: the live pick
_live = json.load(open(os.path.join(HERE, "..", "chartexit", "result.json")))["low"]["live"]["v"]
assert CHART == (_live["stop"], _live["trail"], _live["arm"], _live["lock"], _live["stale_h"], _live["stale_g"],
                 CX.FADES.index(_live["fade"]), _live["T"])

STAKE, FEE, MIN_BUY, START = 0.10, 0.01, 1.0, 100.0
ALLOWANCE = 1.5                # % of the stake per round trip: research/PREREG-REVIEW-2026-11-04.md's real-cost allowance

# id, German name for the table, family, rule
BOTS = [
    ("sellbot", "Sell bot (Pick heute)", "P", "chart"),
    ("K", "Alte Pick-Regel (K)", "P", ("fix", 0.30, 11.0, 6)),
    ("A", "Schatten A", "P", ("fix", 0.20, 3.0, 6)),
    ("B", "Schatten B", "P", ("fix", None, 2.0, 12)),
    ("C", "Schatten C", "P", ("half", 0.30, 11.0, 6)),
    ("D", "Schatten D", "P", ("trail", 0.30, None, 6)),
    ("LP", "Lern-Pick-Regel", "LP", ("fix", 0.20, 2.0, 2)),
    ("hold", "Diamantenhand", "P", ("fix", None, None, 24)),
    ("rocket", "Raketenjäger", "R", ("fix", 0.30, 11.0, 6)),
    ("flip", "Schnell-Verkäufer", "P", "flip"),
]
TEXT = {
    "sellbot": "Pick-Filter; verkauft nach dem Chart (−50 %, 11x, 15 % unter dem Hoch ab 1,5x, −15 % in 30 Min, 6 h)",
    "K": "Pick-Filter; Stopp −30 %, Ziel 11x, 6 h",
    "A": "Pick-Filter; Stopp −20 %, Ziel 3x, 6 h",
    "B": "Pick-Filter; kein Stopp, Ziel 2x, 12 h",
    "C": "Pick-Filter; die Hälfte bei 2x, Rest −30 % / 11x / 6 h",
    "D": "Pick-Filter; Stopp 30 % unter dem besten Kurs, 6 h",
    "LP": "Lern-Pick-Auswahl (ohne Gehirn); Stopp −20 %, Ziel 2x, 2 h",
    "hold": "Pick-Filter; kein Stopp, kein Ziel, verkauft nach 24 h",
    "rocket": "junge Coins (30 Min–18 h), +50 % in 1 h mit viel Volumen; −30 % / 11x / 6 h",
    "flip": "Pick-Filter; verkauft nach 5–10 Minuten",
}
K_RULE = ("fix", 0.30, 11.0, 6)


# --------------------------------------------------------------------------------------------------------- the sell rules
def sell_fixed(C, Hh, L, nb, rule):
    """One fixed rule on one path -> [(bar, share, multiple), ...]. Per candle: the low at the stop level (booked at the low, never
    above the level), the high at the target, the half sale at its level on the high, then the trailing stop's best close."""
    kind, stop, target, T = rule
    n = nb[T]
    half = 2.0 if kind == "half" else None
    trail = stop if kind == "trail" else None
    left, best, out = 1.0, 1.0, []
    for k in range(n):
        lvl = best * (1.0 - trail) if trail else ((1.0 - stop) if stop is not None else None)
        if lvl is not None and L[k] <= lvl:
            out.append((k, left, min(L[k], lvl)))
            return out
        if target is not None and Hh[k] >= target:
            out.append((k, left, target))
            return out
        if half and left > 0.5 and Hh[k] >= half:
            out.append((k, 0.5, half))
            left = 0.5
        if trail:
            best = max(best, C[k])
    out.append((n - 1, left, C[n - 1]))
    return out


def sell_chart(C, Hh, L, O, nb):
    """The chart exit (CX.replay_np's order and fills, the "low" fill) with its sale's candle."""
    stop, trail, arm, lock, stale_h, stale_g, fade, T = CHART
    nT = nb[T]
    hi, armed_t = 1.0, False
    for k in range(nT):
        c, h, l = C[k], Hh[k], L[k]
        lvl = 1.0 - stop
        if armed_t:
            lvl = max(lvl, (1.0 - trail) * hi)
        if l <= lvl:
            return [(k, 1.0, min(l, lvl))]
        if h >= 11.0:
            return [(k, 1.0, 11.0)]
        hi = max(hi, h)
        if not armed_t and hi >= arm:
            armed_t = True
        lvl2 = 1.0 - stop
        if armed_t:
            lvl2 = max(lvl2, (1.0 - trail) * hi)
        if c <= lvl2:
            return [(k, 1.0, c)]
        ref = C[k - 6] if k >= 6 else 1.0
        if c <= 0.85 * ref:
            return [(k, 1.0, c)]
    return [(nT - 1, 1.0, C[nT - 1])]


def sell(rule, A, nb):
    if rule == "chart":
        return sell_chart(A["C"], A["H"], A["L"], A["O"], nb)
    if rule == "flip":
        return [(0, 1.0, A["C"][0])]
    return sell_fixed(A["C"], A["H"], A["L"], nb, rule)


# --------------------------------------------------------------------------------------------------------- rows
SOL = GAPS = META = None


def solusd(t):
    i = np.searchsorted(SOL[0], t, side="right") - 1
    return SOL[1][np.clip(i, 0, len(SOL[1]) - 1)]


def coin(c, b):
    """One coin -> {family: entry dict with every bot's sales} for P, LP, R (the first entry through each), the U rows (the monkey's
    choices, the old Pick rule) and the hours with a Pick-gate coin."""
    t0 = int(c["t"]) // BAR * BAR
    j = ((b["t"].to_numpy() - t0) // BAR).astype(int)
    keep = (j >= 0) & (j < 600)
    j = j[keep]
    if not len(j):
        return None
    n = 600
    cl = np.full(n, np.nan); hi = np.full(n, np.nan); lo = np.full(n, np.nan); op = np.full(n, np.nan); v = np.zeros(n)
    has = np.zeros(n, bool)
    cl[j] = b["c"].to_numpy()[keep]; hi[j] = b["h"].to_numpy()[keep]; lo[j] = b["l"].to_numpy()[keep]; op[j] = b["o"].to_numpy()[keep]
    v[j] = b["v"].to_numpy()[keep]
    has[j] = True
    has &= np.isfinite(cl) & (cl > 0)
    cl[~has] = np.nan
    cf = pd.Series(cl).ffill().to_numpy()
    i0 = int(np.argmax(has))
    p_first = op[i0] if np.isfinite(op[i0]) and op[i0] > 0 else cl[i0]
    cv = np.r_[0, np.cumsum(v)]
    kk = float(c["sol0"]) * float(c["tok0"])
    gm = int(c["t"])
    out = {"pool": c["pool"], "w": c["w"], "U": [], "Phours": set()}
    p_dead = False           # check_chartexit: a coin whose first Pick-gate hour lacks 24 h of candles has no Pick-type entry
    Es = sorted(set(range(30, 1081, 15)) | set(range(60, 1441, 60)))
    for E in Es:
        te = gm + E * MIN
        jl = (te - t0) // BAR - 1
        if jl < 0 or jl + 1 + 12 >= n or not np.isfinite(cf[jl]) or not has[:jl + 1].any():
            continue
        p0 = cf[jl]
        usd = float(solusd(te))
        mc = p0 * 1e9
        liq = 2 * math.sqrt(kk * p0 / usd) * usd
        v24 = cv[jl + 1] - cv[max(0, jl + 1 - 288)]
        v1 = cv[jl + 1] - cv[max(0, jl + 1 - 12)]

        def px(back):
            k = jl - back
            return cf[k] if k >= 0 and np.isfinite(cf[k]) else p_first

        r1h, r6h, r24h = p0 / px(12) - 1, p0 / px(72) - 1, p0 / px(288) - 1
        hourly = E % 60 == 0
        fam = []
        if hourly and 360 <= E <= 1440 and 100_000 <= mc <= 2_000_000 and liq >= 15_000 and v24 >= 15_000 \
                and not (r1h <= -0.10 or r6h <= -0.50 or r24h <= -0.70) and not (r1h >= 2.0 or r6h >= 0.90) and v24 / mc <= 8:
            fam.append("P")
        if hourly and 60 <= E <= 1440 and v24 >= 0.1 * mc and liq >= 15_000 and 50_000 <= mc <= 2_000_000:
            fam.append("LP")
        if 30 <= E <= 1080 and E % 15 == 0 and liq >= 15_000 and v24 >= 15_000 and 100_000 <= mc <= 5_000_000 \
                and not (r1h <= -0.10) and not (r6h <= -0.50) and r1h >= 0.50 and v24 > 0 and v1 >= 0.25 * v24:
            fam.append("R")
        if hourly and 60 <= E <= 1440 and liq >= 15_000 and v24 >= 15_000 and mc >= 50_000:
            fam.append("U")
        if not fam:
            continue
        if GAPS is not None and c["w"] in ("w3", "w4"):
            a, z = te - H, te + 6 * H
            if ((GAPS[:, 1] >= a) & (GAPS[:, 0] <= z)).any():
                continue
        jt = {t: int((te + t * H - t0) // BAR - 1 - (jl + 1)) for t in HOURS}
        if len(cf[jl + 2: jl + 2 + jt[24]]) < jt[24]:
            if "P" in fam and "P" not in out and not p_dead:
                p_dead = True
            continue
        if "P" in fam:
            out["Phours"].add(te // H)
        need = [f for f in fam if f == "U" or (f not in out and not (f == "P" and p_dead))]
        if not need:
            continue
        s = slice(jl + 2, jl + 2 + NB)
        Cc = cf[s] / p0
        hs = has[s]
        Hh = np.where(hs, np.fmax(hi[s], cl[s]), cf[s]) / p0
        Ll = np.where(hs, np.fmin(lo[s], cl[s]), cf[s]) / p0
        Oo = np.where(hs & np.isfinite(op[s]) & (op[s] > 0), op[s], np.r_[cf[jl + 1], cf[jl + 2: jl + 1 + NB]][:len(Cc)]) / p0
        Hh = np.where(Hh <= WICK_X * Cc, Hh, Cc)
        Ll = np.where(Ll >= Cc / WICK_X, Ll, Cc)
        Oo = np.clip(Oo, Ll, Hh)
        A = {"C": Cc, "H": Hh, "L": Ll, "O": Oo}
        nb = {t: max(1, min(len(Cc), jt[t])) for t in HOURS}
        base = t0 + (jl + 3) * BAR                # the close time of the path's first candle
        for f in need:
            if f == "U":
                out["U"].append((te, [(base + k * BAR, s_, m) for k, s_, m in sell(K_RULE, A, nb)]))
                continue
            sales = {}
            for bid, _, fb, rule in BOTS:
                if fb == f:
                    sales[bid] = [(base + k * BAR, s_, m) for k, s_, m in sell(rule, A, nb)]
            e = {"te": te, "E": E, "sales": sales}
            if f == "P":                             # the check against research/chartexit (K and the chart exit, 50 EUR, low fill)
                e["cx"] = CX.replay_np(Cc[:CX.NB], Hh[:CX.NB], Ll[:CX.NB], Oo[:CX.NB], np.zeros(CX.NB),
                                       [min(CX.NB, jt[t]) for t in CX.HOURS], 0.0, np.array(CHART, float))[0]
            out[f] = e
    return out


def _work(args):
    path, k, n = args
    b = pd.read_parquet(path)
    if n > 1:
        pools = np.sort(b["pool"].unique())[k::n]
        b = b[b["pool"].isin(pools)]
    res = []
    for pool, g in b.groupby("pool", sort=False):
        c = META.get(pool)
        if c is None:
            continue
        r = coin(c, g.sort_values("t"))
        if r is not None and (r["U"] or any(f in r for f in ("P", "LP", "R"))):
            res.append(r)
    return res


def cmd_rows(md, h2, gapf, out):
    global SOL, GAPS, META
    import multiprocessing as mp
    os.makedirs(out, exist_ok=True)
    s = np.array(json.load(open(os.path.join(md, "market.json")))["SOLUSDT"], dtype=float)
    SOL = (s[:, 0], s[:, 1])
    g = np.sort(np.load(gapf))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    GAPS = np.c_[st[big], en[big]]
    meta = {}
    for r in pd.read_parquet(os.path.join(h2, "meta_h2.parquet")).to_dict("records"):
        r["w"] = window(int(r["t"]))
        if r["w"]:
            meta[r["pool"]] = r
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        for r in json.load(open(f)):
            r["w"] = window(int(r["t"]))
            if r["w"]:
                meta[r["pool"]] = r
    META = meta
    jobs = [(f, 0, 1) for f in sorted(glob.glob(os.path.join(h2, "bars_*.parquet")))]
    jobs += [(f, k, 6) for f in sorted(glob.glob(os.path.join(md, "bars_w*.parquet"))) for k in range(6)]
    rows = []
    with mp.get_context("fork").Pool(3) as pool:
        for part in pool.imap_unordered(_work, jobs, chunksize=1):
            rows += part
    # a pool in two sources (the window edges) counts once: keep the copy whose first entry is earliest (check_chartexit's order)
    rows.sort(key=lambda r: (min([r[f]["te"] for f in ("P", "LP", "R") if f in r] + [t for t, _ in r["U"]] + [2 ** 62]), r["pool"]))
    seen, uniq = set(), []
    for r in rows:
        if r["pool"] not in seen:
            seen.add(r["pool"]); uniq.append(r)
    pd.to_pickle(uniq, os.path.join(out, "rows.pkl"))
    cnt = {f: pd.Series([r["w"] for r in uniq if f in r]).value_counts().sort_index().to_dict() for f in ("P", "LP", "R")}
    cnt["U rows"] = pd.Series([r["w"] for r in uniq for _ in r["U"]]).value_counts().sort_index().to_dict()
    print("coins", len(uniq), json.dumps(cnt), flush=True)


# --------------------------------------------------------------------------------------------------------- the accounts
def account(buys, stake=STAKE):
    """buys: [(te, pool, sales)] in time order, sales [(ms, share, multiple)]. 100 EUR, each buy stake x the money at cost (at most
    the free cash, none under MIN_BUY), one buy per clock hour, paper fees FEE a side. -> end cash and the trades."""
    cash, open_cost, last_hour, broke = START, 0.0, None, None
    q, trades = [], []

    def settle(until):
        nonlocal cash, open_cost
        while q and q[0][0] <= until:
            _, _, back, cost = heapq.heappop(q)
            cash += back
            open_cost -= cost

    seq = 0
    for te, pool, sales in buys:
        settle(te)
        hour = te // H
        if hour == last_hour:
            continue
        amt = min(stake * (cash + open_cost), cash)
        if amt < MIN_BUY:
            if broke is None and cash + open_cost < MIN_BUY / stake:
                broke = te                   # the money at cost is under 10 EUR: from here no buy reaches 1 EUR (added after the run)
            continue
        cash -= amt
        open_cost += amt
        last_hour = hour
        back_all = 0.0
        for ms, sh, m in sales:
            back = amt * (1 - FEE) * sh * max(0.0, m) * (1 - FEE)
            back_all += back
            seq += 1
            heapq.heappush(q, (max(ms, te), seq, back, amt * sh))
        trades.append((te, pool, amt, back_all))
    settle(2 ** 62)
    return cash, trades, broke


def boot_lo(v, q, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    m = np.empty(draws)
    for k in range(0, draws, 2000):
        m[k:k + 2000] = v[rng.integers(0, len(v), (2000, len(v)))].mean(1)
    return float(np.quantile(m, q))


def stats(cash, trades, broke=None, w=None):
    r = np.array([100 * (b / a - 1) for _, _, a, b in trades]) if trades else np.zeros(0)
    d = {"end": round(cash, 2), "trades": len(trades)}
    if broke is not None and w is not None:
        d["brokeAfterDays"] = round((broke - dict((x, a) for x, a, _ in CX.W_MS)[w]) / (24 * H), 1)
    if len(r):
        d.update(inProfit=round(100 * float((r > 0).mean()), 1), meanPct=round(float(r.mean()), 2), bestPct=round(float(r.max()), 1),
                 worstPct=round(float(r.min()), 1), medianPct=round(float(np.median(r)), 2))
    return d


def bar(trades):
    """research/PREREG-REVIEW-2026-11-04.md's bar on one bot's trades (results in % of the stake, after the cost allowance)."""
    r = np.array([100 * (b / a - 1) for _, _, a, b in trades]) - ALLOWANCE if trades else np.zeros(0)
    if not len(r):
        return {"n": 0, "holds": False}
    lo = boot_lo(r, 0.01)
    best = int(np.argmax(r))
    d = {"n": int(len(r)), "meanAfterCosts": round(float(r.mean()), 2), "lower1pct": round(lo, 2),
         "sumWithoutBest": round(float(r.sum() - r[best]), 1)}
    d["holds"] = bool(d["n"] >= 40 and d["meanAfterCosts"] > 0 and lo > 0 and d["sumWithoutBest"] > 0)
    return d


def spearman(a, b):
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def cmd_run(out, n_monkeys=200):
    rows = pd.read_pickle(os.path.join(out, "rows.pkl"))
    res = {"coins": {f: {w: sum(1 for r in rows if f in r and r["w"] == w) for w in WN} for f in ("P", "LP", "R")}}
    # the check: K and the chart exit on the Pick-type coins against research/chartexit/result.json (50 EUR, the old fee floor)
    cxr = json.load(open(os.path.join(HERE, "..", "chartexit", "result.json")))
    chk = {}
    for w in WN:
        ps = [r["P"] for r in rows if "P" in r and r["w"] == w]
        k = [CX.money(sum(s_ * m for _, s_, m in p["sales"]["K"])) for p in ps]
        x = [CX.money(p["cx"]) for p in ps]
        x2 = [CX.money(sum(s_ * m for _, s_, m in p["sales"]["sellbot"])) for p in ps]
        chk[w] = {"n": len(ps), "nCX": cxr["coins"][w], "K": round(float(np.mean(k)), 2), "K_CX": cxr["low"]["K"][w],
                  "chart": round(float(np.mean(x)), 2), "chart_here": round(float(np.mean(x2)), 2),
                  "chart_CX": cxr["low"]["live"]["byWindow"][w]["mean"]}
    res["checkAgainstChartexit"] = chk
    print(json.dumps(chk), flush=True)

    buys = {}
    for bid, _, fam, _ in BOTS:
        for w in WN:
            b = sorted(((r[fam]["te"], r["pool"], r[fam]["sales"][bid]) for r in rows if fam in r and r["w"] == w), key=lambda x: (x[0], x[1]))
            buys[(bid, w)] = b
    table = {}
    for bid, nm, fam, _ in BOTS:
        t = {"name": nm, "text": TEXT[bid], "family": fam}
        for w in WN:
            cash, tr, broke = account(buys[(bid, w)])
            t[w] = stats(cash, tr, broke, w)
            t[w]["stake5"] = round(account(buys[(bid, w)], 0.05)[0], 2)
            t[w]["stake20"] = round(account(buys[(bid, w)], 0.20)[0], 2)
            t[w]["bar"] = bar(tr)
        t["train"] = round(float(np.mean([t[w]["end"] for w in WN[:3]])), 2)
        t["trainMeanPct"] = round(float(np.mean([t[w].get("meanPct", 0.0) for w in WN[:3]])), 2)
        table[bid] = t
        print(bid, t["train"], {w: (t[w]["end"], t[w]["trades"], t[w].get("meanPct")) for w in WN}, flush=True)

    # the monkey: in every hour with a Pick-gate coin, a random coin of that hour from U, the old Pick rule
    monkey = {}
    for w in WN:
        hours = sorted(set().union(*[r["Phours"] for r in rows if r["w"] == w]))
        byh = {}
        for r in rows:
            if r["w"] != w:
                continue
            for te, sales in r["U"]:
                byh.setdefault(te // H, []).append((te, r["pool"], sales))
        ends, means = [], []
        for seed in range(n_monkeys):
            rng = np.random.default_rng(1000 + seed)
            got, b = set(), []
            for h in hours:
                opts = [o for o in byh.get(h, []) if o[1] not in got]
                if not opts:
                    continue
                o = opts[int(rng.integers(len(opts)))]
                got.add(o[1])
                b.append(o)
            cash, tr, _ = account(b)
            ends.append(cash)
            means.append(stats(cash, tr).get("meanPct", 0.0))
        monkey[w] = {"median": round(float(np.median(ends)), 2), "p10": round(float(np.quantile(ends, 0.10)), 2),
                     "p90": round(float(np.quantile(ends, 0.90)), 2), "meanPct": round(float(np.median(means)), 2),
                     "plannedBuys": len(b), "hours": len(hours)}
    monkey["train"] = round(float(np.mean([monkey[w]["median"] for w in WN[:3]])), 2)
    res["monkey"] = monkey
    print("monkey", json.dumps(monkey), flush=True)

    ids = [b[0] for b in BOTS]
    order = sorted(ids, key=lambda i: (-table[i]["train"], -table[i]["trainMeanPct"]))
    for k, i in enumerate(order):
        table[i]["rankTrain"] = k + 1
    for w in ("w4", "w5"):
        o = sorted(ids, key=lambda i: (-table[i][w]["end"], -table[i][w].get("meanPct", -1e9)))
        for k, i in enumerate(o):
            table[i]["rank_" + w] = k + 1
    win = order[0]
    t4 = table[win]["w4"]
    test = {"winner": win, "w4end": t4["end"], "aboveStart": bool(t4["end"] > START), "beatsMonkey": bool(t4["end"] > monkey["w4"]["median"]),
            "bar": t4["bar"], "top3": {i: {"train": table[i]["rankTrain"], "w4": table[i]["rank_w4"], "w5": table[i]["rank_w5"]} for i in order[:3]},
            "spearman_w4": round(spearman([table[i]["train"] for i in ids], [table[i]["w4"]["end"] for i in ids]), 2),
            "spearman_w5": round(spearman([table[i]["train"] for i in ids], [table[i]["w5"]["end"] for i in ids]), 2),
            "bestOnW4": max(ids, key=lambda i: table[i]["w4"]["end"])}
    test["holds"] = bool(test["aboveStart"] and test["beatsMonkey"] and t4["bar"]["holds"])
    # added after the run (most bots ran down to the 10 EUR floor, where the end balance says little): the same ranks by mean per trade
    test["spearman_meanPct_w4"] = round(spearman([table[i]["trainMeanPct"] for i in ids], [table[i]["w4"].get("meanPct", -100) for i in ids]), 2)
    test["spearman_meanPct_w5"] = round(spearman([table[i]["trainMeanPct"] for i in ids], [table[i]["w5"].get("meanPct", -100) for i in ids]), 2)
    res["test"] = test
    res["bots"] = {i: table[i] for i in order}
    res["anyAboveStart"] = {w: [i for i in ids if table[i][w]["end"] > START] for w in WN}
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else float(o))
    print(json.dumps(test, indent=1, default=lambda o: o.item() if hasattr(o, "item") else float(o)), flush=True)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"rows": cmd_rows, "run": cmd_run}[cmd](*args)
