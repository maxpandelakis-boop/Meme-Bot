"""rocket.py: the rocket hunter's pure logic (fake money only: it scores coins and books paper trades, it never buys, signs or sends
anything and holds no key). rocket_watch.py feeds it; research/winlose/ trained and tested it (WINLOSE-2026-10-22.md, addendum 2 B).

What it does with the numbers of one coin at one check (every 15 minutes from 30 minutes to 18 hours after its pool opened):
  features(candles, trades, pool_ms, now_ms, sol_usd, mc, liq, vol24, market, memory) -> the model's numbers, the same as
      research/winlose/features.py chart_feats + wallet_recent computes them from the history2 bars (selftest_rocket R1 checks it);
      the model is trained on features.live_view's last 300 trades, the trades GeckoTerminal gives here ("reach")
  score(model, f) -> P(the price reaches 10x within 6 hours), from radar_rocket model trees (rocket_model.json, plain JSON)
  universe(...) -> whether the coin is one the model was trained on (liquidity and 24 h volume $15k, market cap $100k-5M, not
      down 10% in an hour or 50% in 6 hours, 30 min to 18 h old)
  Book: the paper account. A coin whose score reaches the model's cut is bought once for TICKET at the check's price; rule A sells
      it (-30% stop on a low, 11x target on a high, 6 hours), after memebot's fees (tip_net); a coin whose pools hold under RUG_LIQ of
      liquidity is a rug, sold at 0 (the Pick account's, the Learning Pick's and the Rocket seeker's line). Nothing here is advice.
  sane(pos, candles, px, now) -> the high and low rule A judges, of the candles that are the coin's price: a close more than GLITCH_X
      off the one before it that neither DexScreener's price now nor the next two closes confirm is a GeckoTerminal glitch, not
      judged (the Rocket seeker's guard); a wick more than memebot.CANDLE_WICK_X beyond its close is one too (the Pick's guard)
Inputs:
  candles  [[ms, open, high, low, close, volume_usd], ...] one-minute (GeckoTerminal ohlcv, any order)
  trades   [{"t": ms, "buy": bool, "usd": float, "who": address}, ...] the pool's latest trades (GeckoTerminal: the last 300)
  memory   {address: [n, wins, bigs, log_roi_sum]} experienced wallets' earlier coins (seeded from the Aug-Oct 2026 history)
"""
import math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

TICKET = 20.0
START_MIN, END_MIN, STEP_MIN = 30, 18 * 60, 15
STOP, TARGET, HOLD_MS = 0.70, 11.0, 6 * 3_600_000      # sell rule A, the rule the model was trained with
SMART_MIN = 5
H = 3_600_000
GLITCH_X = M.UNIT_X         # a one-minute close more than this many times off the close before it is a GeckoTerminal glitch unless
                            # DexScreener's price of the moment or the two closes after it say the same (seeker.GLITCH_X: NEX Ai, 27 Oct,
                            # had a close at 4,615,119x its buy while DexScreener had it at 1.2x); here such a high booked 11x, such a low a stop
RUG_LIQ = 1_000             # $ of liquidity left in the coin's pools (DexScreener) under which it is a rug, sold at 0 (seeker.RUG_LIQ, the
                            # Pick account's and the Learning Pick's line): a pulled pool freezes the price nobody can sell at
NEAR_MS = 5 * 60_000        # DexScreener's price now vouches for the closes of the last five minutes and for the newest close of any age
nan = float("nan")


def num(v):
    return M.num(v)


def finite(x):
    return x is not None and x == x and abs(x) != float("inf")


# --------------------------------------------------------------------------------------------------- the minute arrays
def dense(candles, trades, pool_ms, now_ms, sol_usd):
    """Per-minute arrays from the pool's first minute to the minute before now: close/high/low (forward-filled), SOL volume split
    into buys and sells (from the trades where they reach, else half and half), buy and sell counts (from the trades; minutes
    before the trades reach are counted from the candles' share), and how far back the trades reach (minutes)."""
    E = int((now_ms - pool_ms) // 60_000)
    if E <= 0 or not sol_usd:
        return None
    c, hi, lo = [nan] * E, [nan] * E, [nan] * E
    v = [0.0] * E
    for row in candles or []:
        try:
            t, o, h, l, cl, vol = (float(x) for x in row[:6])
        except (TypeError, ValueError):
            continue
        i = int((t - pool_ms) // 60_000)
        if 0 <= i < E:
            c[i], hi[i], lo[i], v[i] = cl, h, l, vol / sol_usd
    last = nan
    for i in range(E):
        if c[i] == c[i]:
            last = c[i]
        else:
            c[i] = last
            hi[i] = last if hi[i] != hi[i] else hi[i]
            lo[i] = last if lo[i] != lo[i] else lo[i]
    vb, vs = [x / 2 for x in v], [x / 2 for x in v]
    nb, ns = [0.0] * E, [0.0] * E
    ts = [t for t in (num((x or {}).get("t")) for x in trades or []) if t]
    reach = E
    if ts:
        oldest = int((min(ts) - pool_ms) // 60_000)
        reach = max(0, E - max(0, oldest))
        tb, tsl = [0.0] * E, [0.0] * E
        for x in trades:
            t = num(x.get("t"))
            if not t:
                continue
            i = int((t - pool_ms) // 60_000)
            if 0 <= i < E:
                if x.get("buy"):
                    nb[i] += 1; tb[i] += (num(x.get("usd")) or 0.0) / sol_usd
                else:
                    ns[i] += 1; tsl[i] += (num(x.get("usd")) or 0.0) / sol_usd
        for i in range(max(0, oldest), E):
            if tb[i] + tsl[i] > 0:
                vb[i], vs[i] = tb[i], tsl[i]
    return {"c": c, "hi": hi, "lo": lo, "vb": vb, "vs": vs, "nb": nb, "ns": ns, "na": [0.0] * E, "reach": reach, "E": E}


# ------------------------------------------------------------------------------------------------- the chart numbers
def _rsi(close, n=14):
    close = [x for x in close if x == x]
    if len(close) < n + 1:
        return nan
    d = [close[i + 1] - close[i] for i in range(len(close) - n - 1, len(close) - 1)]
    up, dn = sum(x for x in d if x > 0), -sum(x for x in d if x < 0)
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


def _std(a):
    if len(a) < 2:
        return 0.0
    m = sum(a) / len(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / len(a))


def _polyfit1(y):
    n = len(y)
    x = list(range(n))
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx if sxx else 0.0
    return b, my - b * mx


def _nanmax(a):
    a = [x for x in a if x == x]
    return max(a) if a else nan


def _nanmin(a):
    a = [x for x in a if x == x]
    return min(a) if a else nan


def chart(b):
    """research/winlose/features.py chart_feats, line by line in plain Python (no numpy at run time)."""
    E = b["E"]
    c, hi, lo, vb, vs, nb, ns, na = (b[k] for k in ("c", "hi", "lo", "vb", "vs", "nb", "ns", "na"))
    if E < 30 or not finite(c[-1]) or c[-1] <= 0:
        return {}
    lc = [math.log(x) if x == x and x > 0 else nan for x in c]
    f = {}
    first_ok = next((i for i, x in enumerate(lc) if x == x), 0)
    for k in (5, 15, 30, 60, 120, 240):
        f["ret_%d" % k] = lc[-1] - lc[max(0, E - 1 - k)]
    f["ret_grad"] = lc[-1] - lc[first_ok]
    ath = _nanmax(hi)
    f["dd_ath"] = c[-1] / ath
    athi = max((i for i in range(E) if hi[i] == hi[i]), key=lambda i: (hi[i], -i))
    f["min_since_ath"] = E - 1 - athi
    f["from_low"] = c[-1] / _nanmin(lo[max(0, E - 240):])
    f["rsi_1m"] = _rsi(c[-15:])
    f["rsi_5m"] = _rsi(c[E - 1::-5][::-1][-15:]) if E >= 75 else nan
    f["rsi_15m"] = _rsi(c[E - 1::-15][::-1][-15:]) if E >= 225 else nan
    v = [a + b_ for a, b_ in zip(vb, vs)]
    v60 = sum(v[-60:]) / 12
    f["vol_spike_5"] = sum(v[-5:]) / v60 if v60 > 0 else nan
    s120 = sum(v[-120:])
    f["vol_spike_15"] = sum(v[-15:]) / (s120 / 8) if s120 > 0 else nan
    prev60 = sum(v[-120:-60])
    f["vol_trend_60"] = sum(v[-60:]) / prev60 if prev60 > 0 else nan
    for k in (5, 15, 60):
        t = sum(vb[-k:]) + sum(vs[-k:])
        f["buy_imb_%d" % k] = (sum(vb[-k:]) - sum(vs[-k:])) / t if t > 0 else 0.0
    f["buys_trend_30"] = (sum(nb[-30:]) + 1) / (sum(nb[-60:-30]) + 1)
    tr60 = sum(nb[-60:]) + sum(ns[-60:])
    f["trades_60"] = tr60
    f["avg_trade_sol_60"] = sum(v[-60:]) / tr60 if tr60 else nan
    f["active_min_60"] = sum(1 for a, b_ in zip(nb[-60:], ns[-60:]) if a + b_ > 0)
    f["atomic_60"] = sum(na[-60:]) / tr60 if tr60 else nan
    w = lc[-61:]
    r1 = [w[i + 1] - w[i] for i in range(len(w) - 1)]
    r1 = [x for x in r1 if finite(x)]
    f["vola_60"] = _std(r1) if len(r1) > 5 else nan
    f["max_drop_1m_60"] = min(r1) if r1 else nan
    f["max_jump_1m_60"] = max(r1) if r1 else nan
    c5 = lc[E - 1::-5][::-1][-24:]
    if len(c5) >= 12:
        t20 = c5[-20:]
        m, s = sum(t20) / len(t20), _std(t20)
        f["bb_pos"] = (c5[-1] - m) / s if s > 0 else 0.0
        b1, a1 = _polyfit1(c5)
        res = [y - (a1 + b1 * i) for i, y in enumerate(c5)]
        vr = _std(c5) ** 2
        f["trend_slope"] = b1
        f["trend_r2"] = 1 - (_std(res) ** 2) / vr if vr > 0 else 0.0
    for k in (5, 15):
        o, cl, h, l = c[-k - 1], c[-1], _nanmax(hi[-k:]), _nanmin(lo[-k:])
        rng = h - l
        if rng > 0:
            f["body_%d" % k] = (cl - o) / rng
            f["upwick_%d" % k] = (h - max(o, cl)) / rng
            f["lowick_%d" % k] = (min(o, cl) - l) / rng
    if E >= 11:
        o1, c1, o2, c2 = c[-11], c[-6], c[-6], c[-1]
        f["engulf_bull"] = float(c1 < o1 and c2 > o2 and c2 - o2 > o1 - c1)
        f["engulf_bear"] = float(c1 > o1 and c2 < o2 and o2 - c2 > c1 - o1)
    nn = min(24, E // 5)
    l5 = [_nanmin(lo[max(0, E - 5 * (i + 1)):E - 5 * i]) for i in range(nn)][::-1]
    if len(l5) >= 6 and all(finite(x) for x in l5):
        sup = min(l5)
        f["support_touches"] = sum(1 for x in l5 if x <= sup * 1.05)
        f["dist_support"] = c[-1] / sup
        r5 = [_nanmax(hi[max(0, E - 5 * (i + 1)):E - 5 * i]) for i in range(nn)]
        f["resist_touches"] = sum(1 for x in r5 if x >= max(r5) * 0.95)
        f["dist_resist"] = c[-1] / max(r5)
    f["first_hour_ret"] = lc[min(59, E - 1)] - lc[first_ok]
    f["first_hour_sol"] = sum(v[:60])
    f["first_hour_maxdd"] = _nanmin(lo[:60]) / _nanmax(hi[:60])
    return f


def wallets(trades, now_ms, sol_usd, memory):
    """features.py wallet_recent from the latest trades: the wallets whose first buy (0.1 SOL or more) in the trades was in the last
    hour, and what the seeded memory knows of them."""
    first = {}
    for x in sorted(trades or [], key=lambda x: num(x.get("t")) or 0):
        t, who = num(x.get("t")), x.get("who")
        if not x.get("buy") or not t or not who or t >= now_ms:
            continue
        sol = (num(x.get("usd")) or 0.0) / sol_usd if sol_usd else 0.0
        if sol >= 0.1 and who not in first:
            first[who] = (t, sol)
    rec = [(w, s) for w, (t, s) in first.items() if t >= now_ms - H]
    if not rec:
        return {}
    sols = [s for _, s in rec]
    known = smart = big = 0
    lro = []
    for w, _ in rec:
        m = (memory or {}).get(w)
        if m and m[0] >= SMART_MIN:
            known += 1
            smart += 1 if m[1] / m[0] >= 0.5 else 0
            big += 1 if m[2] >= 2 else 0
            lro.append(m[3] / m[0])
    n = len(rec)
    return {"r_buyers": n, "r_sol": sum(sols), "r_top_share": max(sols) / sum(sols), "r_avg_buy": sum(sols) / n,
            "r_known_share": known / n, "r_smart_n": smart, "r_smart_share": smart / n, "r_smartbig_n": big,
            "r_avg_lroi": sum(lro) / len(lro) if lro else nan}


def features(candles, trades, pool_ms, now_ms, sol_usd, mc, liq, vol24, market=None, memory=None):
    b = dense(candles, trades, pool_ms, now_ms, sol_usd)
    if b is None:
        return None
    f = chart(b)
    if not f:
        return None
    f.update(wallets(trades, now_ms, sol_usd, memory))
    f.update({"mc": math.log10(mc) if mc and mc > 0 else nan, "liqmc": liq / mc if mc else nan, "volmc": vol24 / mc if mc else nan})
    f.update(market or {})
    f["_reach"] = b["reach"]
    return f


def universe(age_min, mc, liq, vol24, c1, c6):
    return (START_MIN <= age_min <= END_MIN and (liq or 0) >= 15_000 and (vol24 or 0) >= 15_000 and 100_000 <= (mc or 0) <= 5_000_000
            and not (c1 is not None and c1 <= -10) and not (c6 is not None and c6 <= -50))


# ------------------------------------------------------------------------------------------------- the model
def _tree(node, x):
    while "leaf_value" not in node:
        v = x[node["split_feature"]]
        if v is None or v != v:
            go_left = node.get("default_left", True)
        else:
            go_left = v <= node["threshold"]
        node = node["left_child"] if go_left else node["right_child"]
    return node["leaf_value"]


def score(model, f):
    """P(10x within 6 h) from the dumped LightGBM trees (binary: the sigmoid of the summed leaves)."""
    if not model or not f:
        return None
    x = [num(f.get(k)) if num(f.get(k)) is not None else nan for k in model["features"]]
    s = sum(_tree(t, x) for t in model["trees"])
    return 1.0 / (1.0 + math.exp(-s))


# ------------------------------------------------------------------------------------------------- the paper account
def net(mult):
    return M.tip_net(max(0.0, mult))


def near(a, b):
    """Whether two prices (or multiples) are at most GLITCH_X times apart; False when either is missing or not above zero (seeker.near)."""
    a, b = num(a), num(b)
    return bool(a and b and a > 0 and b > 0 and 1.0 / GLITCH_X <= a / b <= GLITCH_X)


def believed(last, x, after, now_x=None):
    """Whether a close x (a multiple of the buy price) is the coin's price and not a glitch: near the believed close before it (last), or
    near DexScreener's price now (now_x, for a close of the last minutes or the newest close), or near both of the two closes after it
    (a level the chart stays at). seeker.believed."""
    return near(x, last) or near(x, now_x) or (len(after) == 2 and all(near(x, y) for y in after))


def sane(p, candles, px, now):
    """The candles of one look [[ms, open, high, low, close, ...], ...] (any order; from the position's last counted minute on) that
    rule A judges, sorted: a close more than GLITCH_X off the counted close before it (p["last"], a multiple of the buy price; the buy's
    1.0 at first) counts only when DexScreener's price now (px: for the closes of the last NEAR_MS and the newest one) or both of the
    next two closes say the same, else its candle is left out; a counted candle's wick more than memebot.CANDLE_WICK_X beyond its close
    is a glitch too, the close stands in (memebot.hold_wicks, the Pick's guard). p["last"] and p["lastT"]: the newest counted close and
    its minute."""
    bp = num(p.get("px"))
    if not bp or bp <= 0:
        return []
    rows = []
    for r in candles or []:
        try:
            row = [float(v) for v in r[:5]]
        except (TypeError, ValueError):
            continue
        if len(row) == 5 and row[4] > 0:
            rows.append(row)
    rows.sort()
    now_x = px / bp if px and px > 0 else None
    out = []
    for i, r in enumerate(rows):
        x = r[4] / bp
        if not believed(num(p.get("last")) or 1.0, x, [y[4] / bp for y in rows[i + 1:i + 3]], now_x if now - r[0] <= NEAR_MS or i == len(rows) - 1 else None):
            continue
        h, l = M.hold_wicks(r)
        out.append([r[0], r[1], h, l, r[4]])
        p["last"], p["lastT"] = round(x, 6), int(r[0])
    return out


class Book:
    """The rocket hunter's paper account: doc = {"open": {addr: pos}, "closed": [pos, ...], "seen": {addr: last check ms}}."""

    def __init__(self, doc=None):
        doc = doc if isinstance(doc, dict) else {}
        self.open = doc.get("open") if isinstance(doc.get("open"), dict) else {}
        self.closed = doc.get("closed") if isinstance(doc.get("closed"), list) else []

    def bought(self, a):
        return a in self.open or any(p.get("addr") == a for p in self.closed)

    def buy(self, a, sym, px, now, sc, cut, pool):
        if self.bought(a) or not px or px <= 0:
            return None
        p = {"addr": a, "sym": sym, "pool": pool, "t": now, "px": px, "score": round(sc, 4), "cut": round(cut, 4), "hi": 1.0, "lo": 1.0}
        self.open[a] = p
        return p

    def update(self, a, now, hi=None, lo=None, px=None, gone=False, liq=None):
        """New high/low (prices, of the candles since the last look that sane counted) and the price now; rule A decides. A stop and a
        target in the same minute count as the stop (the safe side). liq: the liquidity now ($, the coin's pools on DexScreener); under
        RUG_LIQ it is a rug, sold at 0. Returns the closed position or None."""
        p = self.open.get(a)
        if not p:
            return None
        if gone:
            return self._close(a, now, 0.0, "gone")
        if lo is not None and lo / p["px"] <= STOP:
            return self._close(a, now, lo / p["px"], "stop")
        if hi is not None:
            p["hi"] = max(p["hi"], hi / p["px"])
            if p["hi"] >= TARGET:
                return self._close(a, now, TARGET, "11x")
        if lo is not None:
            p["lo"] = min(p["lo"], lo / p["px"])
        if px:
            p["now"] = px / p["px"]
        if liq is not None and liq < RUG_LIQ:
            return self._close(a, now, 0.0, "rug")
        if now - p["t"] >= HOLD_MS and px:
            return self._close(a, now, px / p["px"], "6h")
        return None

    def _close(self, a, now, mult, why):
        p = self.open.pop(a)
        p.update(out=now, mult=round(mult, 4), eur=net(mult), why=why)
        self.closed.append(p)
        return p

    def summary(self):
        eur = [p["eur"] for p in self.closed]
        open_val = sum(net(p.get("now") or 1.0) for p in self.open.values())
        return {"trades": len(self.closed), "open": len(self.open), "eur": round(sum(eur), 2), "openEur": round(open_val, 2),
                "inProfitOf10": round(10 * sum(1 for e in eur if e > 0) / len(eur), 1) if eur else None,
                "x10": sum(1 for p in self.closed if (p.get("hi") or 0) >= TARGET or p.get("why") == "11x"),
                "x3": sum(1 for p in self.closed if (p.get("hi") or 0) >= 3), "avg": round(sum(eur) / len(eur), 3) if eur else None}

    def doc(self):
        return {"open": self.open, "closed": self.closed[-500:], "summary": self.summary()}
