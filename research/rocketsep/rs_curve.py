"""Buying the launch model's top picks on the pump.fun bonding curve (fake money only; research/rocketsep/PREREG-CURVE-2026-10-26.md).

  python3 research/rocketsep/rs_curve.py targets <data dir>                       -> curve_targets.csv, curve_probe.csv (no network)
  python3 research/rocketsep/rs_curve.py probe <probe csv> <out json>             -> GeckoTerminal coverage on coins outside the lists
  python3 research/rocketsep/rs_curve.py fetch <targets csv> <i> <n> <out json.gz> -> one shard of curve minute candles
  python3 research/rocketsep/rs_curve.py judge <targets csv> <candle dir> <out dir> -> <out dir>/curve.json (no network)

targets: the Part 0a launch model of rs_curve_feas.py (14 launch facts, fit on w3, seed 7, unchanged) ranks every w4 launch; the top
0.1 % (primary) and the top 1 % (secondary) are written with their launch and graduation times. probe: 30 w4 launches outside the top
5 % (15 graduated after 5+ minutes, 15 never graduated) for what GeckoTerminal returns for curve pools; it logs counts and times
only, no prices. fetch: GeckoTerminal's public one-minute candles of each coin's curve pool from the launch to its graduation or 24 h
and 5 minutes after it, one coin after another with 2.2 s between calls (no key). judge: the pre-registered plan and bar."""
import bisect, csv, gzip, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

GT = "https://api.geckoterminal.com/api/v2/networks/solana/"
GAP = float(os.environ.get("GT_GAP") or 2.2)
BUDGET_S = float(os.environ.get("BUDGET_S") or 19_000)          # stop a shard in time to upload what it has
MIN, H = 60_000, 3_600_000
STAKE, FEE, ALLOW = 50.0, 0.0125, 0.75                          # pump.fun curve fee each side; the 0.75 EUR allowance of PR #39
STOP, HOLD, LEVEL = 0.5, 24 * H, 0.9
P0 = 30 / 1.073e9                                              # the curve's start price in SOL (30 SOL and 1,073 M tokens virtual)
G0 = 30 * 1.073e9 / 279.9e6 / 279.9e6                           # its price when 793.1 M tokens are sold and it completes (14.7 x P0)
TARGETS = os.path.join(HERE, "curve_targets.csv")
PROBE = os.path.join(HERE, "curve_probe.csv")
COLS = ["mint", "curve", "t_ms", "grad_t_ms", "graduated", "score", "rank", "set"]


# ------------------------------------------------------------------------------------------------------------------ targets
def cmd_targets(dd):
    import numpy as np
    import rs_curve_feas as CF
    T, gt, cmin, w4, p, bst = CF.scores(dd)
    W = T[w4].reset_index(drop=True)
    g4 = gt[w4]
    o = np.argsort(-p, kind="stable")
    n1, n10 = int(round(0.001 * len(p))), int(round(0.01 * len(p)))
    rows = []
    for r, i in enumerate(o[:n10]):
        rows.append([W.at[i, "mint"], W.at[i, "curve"], int(W.at[i, "t"]), "" if not np.isfinite(g4[i]) else int(g4[i]),
                     int(bool(W.at[i, "grad"])), "%.6g" % p[i], r + 1, "top0.1" if r < n1 else "top1"])
    with open(TARGETS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    rest = o[int(round(0.05 * len(p))):]
    rng = np.random.default_rng(26)
    gr = W["grad"].to_numpy()
    late = gr & np.isfinite(cmin[w4]) & (cmin[w4] >= 5)
    pick = list(rng.choice(rest[late[rest]], 15, replace=False)) + list(rng.choice(rest[~gr[rest]], 15, replace=False))
    with open(PROBE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for i in pick:
            w.writerow([W.at[i, "mint"], W.at[i, "curve"], int(W.at[i, "t"]), "" if not np.isfinite(g4[i]) else int(g4[i]),
                        int(bool(W.at[i, "grad"])), "%.6g" % p[i], "", "probe"])
    print("w4 launches", len(p), "trees", bst.best_iteration, "top0.1", n1, "top1", n10, "graduated in top0.1",
          int(sum(r[4] for r in rows[:n1])), flush=True)


def read_targets(path):
    out = []
    for r in csv.DictReader(open(path)):
        r["t_ms"] = int(r["t_ms"])
        r["grad_t_ms"] = int(r["grad_t_ms"]) if r["grad_t_ms"] else None
        r["graduated"] = r["graduated"] == "1"
        out.append(r)
    return out


# ------------------------------------------------------------------------------------------------------------------ network
_last = [0.0]
calls = {"n": 0}


def get(path):
    """(HTTP status, JSON or None), GAP seconds between calls, retries on 429 and server errors"""
    for i in range(5):
        w = _last[0] + GAP - time.time()
        if w > 0:
            time.sleep(w)
        calls["n"] += 1
        req = urllib.request.Request(GT + path, headers={"Accept": "application/json", "User-Agent": "memebot-research"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                _last[0] = time.time()
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(6 * (i + 1))
                continue
            return e.code, None
        except Exception:
            _last[0] = time.time()
            time.sleep(3 * (i + 1))
    return -1, None


def ohlcv(pool, mint, before_s):
    st, j = get("pools/%s/ohlcv/minute?aggregate=1&limit=1000&currency=token&token=%s&before_timestamp=%d" % (pool, mint, before_s))
    rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(j, dict) else None
    if rows is None:
        return st, None
    return st, sorted([int(r[0]) * 1000] + [float(x) for x in r[1:6]] for r in rows if isinstance(r, list) and len(r) >= 6)


def curve_pool(mint):
    """the coin's pump.fun curve pool in GeckoTerminal's token listing, if the curve address itself is not a pool there"""
    st, j = get("tokens/%s/pools?page=1" % mint)
    for d in ((j or {}).get("data") or []) if isinstance(j, dict) else []:
        dex = (((d.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id") or ""
        if dex == "pump-fun":
            return st, (d.get("attributes") or {}).get("address")
    return st, None


def end_ms(r):
    e = r["t_ms"] + HOLD + 5 * MIN
    if r["grad_t_ms"] is not None:
        e = min(e, r["grad_t_ms"] + 2 * MIN)
    return e


def one(r):
    """all curve minute candles of a coin from its launch to end_ms"""
    pool, how = r["curve"], "curve"
    st, c = ohlcv(pool, r["mint"], end_ms(r) // 1000)
    if c is None:
        st2, pool = curve_pool(r["mint"])
        if pool:
            how = "token listing"
            st, c = ohlcv(pool, r["mint"], end_ms(r) // 1000)
        else:
            return {"status": st, "lookup": st2, "pool": None, "candles": None}
    cand = list(c or [])
    while c and len(c) >= 1000 and cand[0][0] > r["t_ms"] + MIN:      # page back to the launch minute
        st, c = ohlcv(pool, r["mint"], cand[0][0] // 1000)
        old = [x for x in (c or []) if x[0] < cand[0][0]]
        if not old:
            break
        cand = old + cand
    return {"status": st, "pool": pool, "how": how, "candles": [[x[0]] + [float("%.6g" % v) for v in x[1:]] for x in cand]}


def cmd_probe(path, out):
    res = []
    for r in read_targets(path):
        d = one(r)
        c = d.get("candles") or []
        row = {"graduated": r["graduated"], "status": d["status"], "how": d.get("how"), "lookup": d.get("lookup"), "candles": len(c)}
        if c:
            row["firstMinAfterLaunch"] = round((c[0][0] - r["t_ms"]) / MIN, 1)
            row["lastMinAfterLaunch"] = round((c[-1][0] - r["t_ms"]) / MIN, 1)
            row["firstOpenOverP0"] = round(c[0][1] / P0, 3)
            if r["grad_t_ms"]:
                row["lastMinBeforeGrad"] = round((r["grad_t_ms"] - c[-1][0]) / MIN, 1)
                row["lastHighOverG0"] = round(c[-1][2] / G0, 3)
        res.append(row)
        print(json.dumps(row), flush=True)
    ok = [x for x in res if x["candles"] > 0]
    summ = {"coins": len(res), "withCandles": len(ok), "graduatedWith": sum(x["graduated"] for x in ok),
            "notGraduatedWith": sum(not x["graduated"] for x in ok), "calls": calls["n"], "rows": res}
    json.dump(summ, open(out, "w"), indent=1)
    print("probe", {k: v for k, v in summ.items() if k != "rows"}, flush=True)
    if len(ok) < 10:
        sys.exit("GeckoTerminal returned curve candles for fewer than 10 of %d probe coins: the fetch does not start" % len(res))


def cmd_fetch(path, i, n, out):
    T = read_targets(path)
    T = [r for k, r in enumerate(sorted(T, key=lambda r: int(r["rank"]))) if k % n == i]     # the primary set comes first
    t0, res = time.time(), {}
    for k, r in enumerate(T):
        if time.time() - t0 > BUDGET_S:
            print("budget reached after", k, "coins", flush=True)
            break
        res[r["mint"]] = one(r)
        if k % 50 == 0:
            print(k, len(T), r["set"], "calls", calls["n"], "%.0f s" % (time.time() - t0), flush=True)
            json.dump(res, gzip.open(out, "wt"))
    json.dump(res, gzip.open(out, "wt"))
    print("done", len(res), "of", len(T), "calls", calls["n"], flush=True)


# ------------------------------------------------------------------------------------------------------------------ judge
def trade(r, c, G, stop=STOP, tp=None, entry="oc", grad_exit="level"):
    """one buy by the pre-registered plan: (status, exit/entry ratio, graduated while held, minutes held). Prices in SOL; G is the
    price at which the curve completes. grad_exit "level": sold on the curve once it reaches LEVEL x G (about 93 % of the curve
    sold); "before": the close of the minute before the one that completes it; "final": the close of the minute that completes it."""
    if not c:
        return "no candles", None, None, None
    E = (r["t_ms"] + MIN + MIN - 1) // MIN * MIN                      # the first minute that starts 60 s or more after the launch
    g = r["grad_t_ms"]
    if g is not None and g < E + MIN:
        return "graduated before the entry", None, None, None
    ts = [x[0] for x in c]
    k = bisect.bisect_left(ts, E)
    if k < len(c) and ts[k] == E:
        o, h, l, cl = c[k][1:5]
        P, last = (max(o, cl) if entry == "oc" else h), cl
        after = k + 1
    elif k > 0:
        P = last = c[k - 1][4]                                           # no trade in that minute: the curve's standing price
        after = k
    else:
        return "no price at the entry", None, None, None
    if not P > 0:
        return "no price at the entry", None, None, None
    if P >= LEVEL * G:
        return "curve nearly full at the entry", None, None, None
    grad_in = g is not None and g < E + HOLD
    if grad_in:
        limit = g // MIN * MIN - 1 if grad_exit == "before" else g
    else:
        limit = E + HOLD - 1
    X, held = None, None
    for x in c[after:]:
        if x[0] > limit:
            break
        o, h, l, cl = x[1:5]
        lo = l if l >= 0.5 * min(o, cl) else min(o, cl)                  # a one-trade spike below half the candle counts as its body
        hi = h if h <= 2 * max(o, cl) else max(o, cl)
        if stop is not None and lo <= stop * P:
            X, held = min(o, stop * P), x[0]
            break
        if grad_exit == "level" and hi >= LEVEL * G:
            X, held = max(o, LEVEL * G), x[0]
            break
        if tp is not None and hi >= tp * P:
            X, held = max(o, tp * P), x[0]
            break
        last, held = cl, x[0]
    grad_held = grad_in and (X is None or (grad_exit == "level" and X >= LEVEL * G))
    if X is None:
        X = last
    return "trade", X / P, bool(grad_held), None if held is None else round((held - E) / MIN, 1)


def eur(ratio):
    return STAKE * (1 - FEE) * ratio * (1 - FEE) - STAKE


def cmd_judge(path, cdir, od):
    import numpy as np
    import check_rs as RS
    T = read_targets(path)
    C = {}
    for f in sorted(os.listdir(cdir)):
        if f.endswith(".json.gz"):
            C.update(json.load(gzip.open(os.path.join(cdir, f), "rt")))
    pr = json.load(open(os.path.join(cdir, "probe.json")))
    gq = [x["lastHighOverG0"] for x in pr["rows"] if x.get("lastHighOverG0") and x.get("lastMinBeforeGrad", 99) <= 2]
    gm = float(np.median(gq)) if gq else float("nan")
    G = G0 if 0.75 <= gm <= 1.25 else G0 * gm                          # the probe coins' last curve high, if not near the theory
    plans = {"primary": dict(), "sold the minute before completion": dict(grad_exit="before"),
             "sold at the final curve price": dict(grad_exit="final"), "no stop": dict(stop=None), "stop 0.7": dict(stop=0.7),
             "stop 0.5 + take 2x": dict(tp=2.0), "entry at the candle high": dict(entry="h")}
    res = {"G": G, "G0": G0, "probeLastHighOverG0": {"n": len(gq), "median": round(gm, 3)}, "coverage": {}, "sets": {}}
    for st in ("top0.1", "top1"):
        rows = [r for r in T if r["set"] == "top0.1" or st == "top1"]
        fetched = [r for r in rows if r["mint"] in C]
        have = [r for r in fetched if C[r["mint"]].get("candles")]
        cov = {}
        for gname, gsel in (("graduated", True), ("never graduated", False)):
            f = [r for r in fetched if r["graduated"] == gsel]
            h = [r for r in f if C[r["mint"]].get("candles")]
            cov[gname] = {"fetched": len(f), "withCandles": len(h), "share": round(len(h) / max(len(f), 1), 3)}
        ratio = cov["never graduated"]["share"] / max(cov["graduated"]["share"], 1e-9)
        res["coverage"][st] = {"targets": len(rows), "fetched": len(fetched), "withCandles": len(have), **cov,
                               "coverageRatio": round(ratio, 3), "answerable": bool(ratio >= 0.9)}
        out = {}
        for pn, kw in plans.items():
            stat, m, gh, coins = {}, [], [], []
            for r in fetched:
                s, X, grad_held, held = trade(r, C[r["mint"]].get("candles"), G, **kw)
                stat[s] = stat.get(s, 0) + 1
                if s == "trade":
                    m.append(eur(X))
                    gh.append(grad_held)
                    coins.append({"mint": r["mint"], "rank": int(r["rank"]), "ratio": round(X, 4), "eur": round(eur(X) - ALLOW, 2),
                                  "graduatedWhileHeld": grad_held, "minHeld": held})
            m, gh = np.array(m), np.array(gh, bool)
            row = {"status": stat, **RS.profit(m, ALLOW), "graduatedWhileHeld": int(gh.sum())}
            if len(m):
                row["eurGraduatedWhileHeld"] = round(float((m[gh] - ALLOW).sum()), 2)
                row["eurOthers"] = round(float((m[~gh] - ALLOW).sum()), 2)
                row["ratioQuantiles"] = {q: round(float(np.quantile([c["ratio"] for c in coins], q)), 3) for q in (0.1, 0.5, 0.9, 0.99)}
            if pn == "primary":
                row["best10"] = sorted(coins, key=lambda c: -c["eur"])[:10]
                row["coins"] = coins
            out[pn] = row
            print(st, pn, {k: v for k, v in row.items() if k not in ("coins", "best10")}, flush=True)
        res["sets"][st] = out
    p = res["sets"]["top0.1"]["primary"]
    res["verdict"] = {"holds": bool(p.get("holds")) and res["coverage"]["top0.1"]["answerable"],
                      "answerable": res["coverage"]["top0.1"]["answerable"]}
    json.dump(res, open(os.path.join(od, "curve.json"), "w"), indent=1)
    print("verdict", res["verdict"], flush=True)


if __name__ == "__main__":
    a = sys.argv
    {"targets": lambda: cmd_targets(a[2]), "probe": lambda: cmd_probe(a[2], a[3]),
     "fetch": lambda: cmd_fetch(a[2], int(a[3]), int(a[4]), a[5]), "judge": lambda: cmd_judge(a[2], a[3], a[4])}[a[1]]()
