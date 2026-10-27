"""seeker.py: the Rocket seeker's pure logic (fake money only: it scores coins and books paper trades in its own account, it never buys,
signs or sends anything and holds no key). seeker_watch.py feeds it every minute; research/seeker/ trained and pre-registered it
(PREREG-SEEKER-2026-10-26.md, seeker_train.py). The Pick, the Sell bot, the Radar account and the Learning Pick never read it.

What it does with one pump.fun graduation (a PumpSwap pool the launch radar recorded, branch radar-data), once, 30 to 45 minutes after
the pool opened:
  facts(rec, theme)   the launch facts the radar read at the launch (research/rockets/check_rockets.py's names): bonding-curve minutes
      (pool time - mint time), the creator's earlier graduations (sig devGrad), the X link (none / a post / a profile or community),
      the X post's age at the mint (from the post's id), how many graduations of the 24 hours before share a name word (theme heat),
      a CJK name
  bars(candles, pool_ms) + chart(...)   the first 30 minutes of the chart: GeckoTerminal's one-minute candles summed to five-minute
      clock bars (bar 0 holds the graduation), up to the last bar that closed before graduation + 30 minutes, as the training's
      five-minute candles (seeker_train.chart_feats; selftest_seeker checks both give the same numbers)
  score(model, f)     P(a close at 10x within 24 hours) from seeker_model.json (LightGBM trees as plain JSON, its missing-value rules)
  Book                the paper account: a score at or over the model's cut buys the coin once for TICKET at DexScreener's price of that
      minute; "Rocket hold" sells it on one-minute closes: at or below 0.5x the buy, or (once a close reached 2x) at or below 0.6x the
      best close, or after 24 hours at the last close; a close more than GLITCH_X off the one before it that neither DexScreener's
      price of the moment nor the next two closes confirm is a glitch, not judged; a coin whose pools hold under RUG_LIQ of liquidity is
      a rug, sold at 0 (the Pick account's and the Learning Pick's line). memebot's paper fees (tip_net). Nothing here is advice.
"""
import math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

TICKET = 20.0
E_MIN = 30                  # the score is taken as of 30 minutes after the graduation (the training's entry)
LATE_MIN = 45               # ... and only until 45 minutes (a coin first seen later is missed, never scored with older numbers)
LIQ_MIN = 10_000            # pool liquidity at the score, $ (the training's entry filter)
FLOOR, ARM, KEEP = 0.5, 2.0, 0.6
HOLD_MS = 24 * 3_600_000
BAR, MIN, H, DAY = 300_000, 60_000, 3_600_000, 86_400_000
GLITCH_X = M.UNIT_X         # a one-minute close more than this many times off the close before it is a GeckoTerminal glitch unless
                            # DexScreener's price of the moment or the two closes after it say the same: NEX Ai (27 Oct) had a close at
                            # 4,615,119x its buy and then one at 7,231x while DexScreener had it at 1.2x, and was booked +138,058
RUG_LIQ = 1_000             # $ of liquidity left in the coin's pools (DexScreener) under which it is a rug, sold at 0, as on the Pick
                            # account (memebot) and the Learning Pick: SOLY and NEX Ai (27 Oct) had their liquidity pulled, so their price
                            # froze at 1.52x and 0.65x with no trade after it, and the 24-hour sale would have booked a price nobody could sell at
NEAR_MS = 5 * MIN           # DexScreener's price now vouches for the closes of the last five minutes, and for the newest close of any age
                            # (no trade after it: the price now is its price; .AiTown's rug to 0.0001x, judged again hours later)
nan = float("nan")

# check_rockets.py (PR #55) word rules for the theme heat, its tweet id and CJK patterns, line by line
STOP = set("""that this with from have were they what when your about list film series season which there their these would other
after first also into over more most some only then than them been will like just year years coin token official the and for
real world news new""".split())
TWEET = re.compile(r"/status(?:es)?/(\d{6,})")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ｦ-ﾟ]")


def num(v):
    return M.num(v)


def fin(x):
    return x is not None and x == x and abs(x) != float("inf")


def words(s):
    return {w for w in re.split(r"[^a-z0-9]+", str(s or "").lower()) if len(w) >= 4 and w not in STOP and not w.isdigit()}


# ------------------------------------------------------------------------------------------------------------- launch facts
def sig(rec, k):
    """A launch reading of the radar record: its first (sig0), else its latest (sig)."""
    for part in ("sig0", "sig"):
        v = ((rec or {}).get(part) or {}).get(k)
        if v is not None:
            return v
    return None


class Theme:
    """The graduations of the radar's records by name word: theme(pool_ms, sym, name) -> how many graduations of the 24 hours before
    share a name word (check_rockets.media_facts F13), None for a coin without a name."""

    def __init__(self, recs):
        self.idx = {}
        for r in recs:
            t = num(r.get("pool"))
            if t:
                for w in words(r.get("sym")) | words(r.get("name")):
                    self.idx.setdefault(w, []).append((t, r.get("addr")))

    def __call__(self, t, sym, name, addr=None):
        ws = words(sym) | words(name)
        if not str(sym or "").strip() and not str(name or "").strip():
            return None
        prev = set()
        for w in ws:
            for tt, a in self.idx.get(w, ()):
                if t - DAY <= tt < t and a != addr:
                    prev.add(a)
        return float(len(prev))


def facts(rec, theme):
    """The launch facts of one radar record (a PumpSwap graduation): the six inputs of LAUNCH_F."""
    pool, mint = num(rec.get("pool")), num(rec.get("mint"))
    f = {}
    cm = (pool - mint) / MIN if pool and mint else None
    f["f_curve_min"] = max(0.0, cm) if cm is not None and cm >= -2 else nan
    dg = num(sig(rec, "devGrad"))
    f["f_creator_prior"] = float(dg) if dg is not None else nan
    x = str(sig(rec, "x") or "").strip()
    f["f_xtype"] = 1.0 if "/status/" in x else (2.0 if x else 0.0)
    # the post's age needs the mint time; without it both are missing (the training blanked them together, PREREG)
    if not mint:
        f["f_post_age"] = nan
    else:
        m = TWEET.search(x)
        if not m:
            f["f_post_age"] = 0.0
        else:
            age = mint - ((int(m.group(1)) >> 22) + 1288834974657)
            f["f_post_age"] = 1.0 if age <= H else (2.0 if age <= DAY else 3.0)
    sym, name = rec.get("sym"), rec.get("name")
    th = theme(pool, sym, name, rec.get("addr")) if theme and pool else None
    f["f_theme24"] = th if th is not None else nan
    nm = "%s %s" % (sym or "", name or "")
    f["f_cjk"] = (1.0 if CJK.search(nm) else 0.0) if nm.strip() else nan
    return f


# ------------------------------------------------------------------------------------------------------------- the chart
def bars(candles, pool_ms, at_ms):
    """One-minute candles [[ms, o, h, l, c, v_usd], ...] -> five-minute clock bars from the graduation's bar (its five-minute clock
    bar) to the last one that closed at or before at_ms: closes (forward-filled, NaN before the first trade), highs (max of the
    minutes' highs and closes, NaN without a trade), USD volume, a trade in the bar (1/0)."""
    t0 = (int(pool_ms) // BAR) * BAR
    n = (int(at_ms) - t0) // BAR
    if n <= 0:
        return None
    cl, hi, v, has, lt = [nan] * n, [nan] * n, [0.0] * n, [0] * n, [None] * n
    for row in candles or []:
        try:
            t, _o, h, _l, c, vol = (float(x) for x in row[:6])
        except (TypeError, ValueError):
            continue
        j = int((t - t0) // BAR)
        if not (0 <= j < n) or not (c > 0):
            continue
        if lt[j] is None or t >= lt[j]:
            cl[j], lt[j] = c, t
        hv = max(h, c) if h == h else c
        hi[j] = hv if hi[j] != hi[j] else max(hi[j], hv)
        v[j] += vol if vol == vol else 0.0
        has[j] = 1
    last = nan
    for j in range(n):
        if cl[j] == cl[j]:
            last = cl[j]
        else:
            cl[j] = last
    return {"cl": cl, "hi": hi, "v": v, "has": has}


def chart(b):
    """seeker_train.chart_feats in plain Python: the chart at the entry (the last bar)."""
    out = {k: nan for k in ("c_ret", "c_peak", "c_vol", "c_act", "c_r5", "c_r15", "c_mc")}
    if not b or not b["cl"]:
        return out
    cl, hi, v, has = b["cl"], b["hi"], b["v"], b["has"]
    n, p0 = len(cl), cl[-1]
    if not fin(p0) or p0 <= 0:
        return out
    tr = [j for j in range(n) if has[j] > 0]
    first = cl[tr[0]] if tr else nan
    out["c_ret"] = math.log(p0 / first) if fin(first) and first > 0 else nan
    hh = [x for x in hi if fin(x)]
    out["c_peak"] = max(hh) / p0 if hh else nan
    out["c_vol"] = math.log10(1.0 + sum(x for x in v if fin(x)))
    out["c_act"] = sum(1 for x in has if x > 0) / n
    for k, back in (("c_r5", 1), ("c_r15", 3)):
        q = cl[n - 1 - back] if n - 1 - back >= 0 else nan
        out[k] = math.log(p0 / q) if fin(q) and q > 0 else nan
    out["c_mc"] = math.log10(p0 * 1e9)
    return out


def features(rec, candles, theme):
    """All 13 inputs as of graduation + E_MIN minutes, plus the entry close (_p0) and the bars used (_bars). None without a bar."""
    pool = num(rec.get("pool"))
    if not pool:
        return None
    b = bars(candles, pool, pool + E_MIN * MIN)
    if not b or not any(b["has"]):
        return None
    f = facts(rec, theme)
    f.update(chart(b))
    f["_p0"], f["_bars"] = b["cl"][-1], len(b["cl"])
    return f


# ------------------------------------------------------------------------------------------------------------- the model
def _left(node, v):
    """LightGBM's numerical split: a missing value goes the learned way for missing_type NaN, counts as 0 otherwise (Zero: 0 and
    missing go the learned way)."""
    mt = node.get("missing_type") or "None"
    if v is None or v != v:
        if mt == "NaN":
            return node["default_left"]
        v = 0.0
    if mt == "Zero" and abs(v) <= 1e-35:
        return node["default_left"]
    return v <= node["threshold"]


def _tree(node, x):
    while "leaf_value" not in node:
        node = node["left_child"] if _left(node, x[node["split_feature"]]) else node["right_child"]
    return node["leaf_value"]


def score(model, f):
    if not model or not f:
        return None
    x = [num(f.get(k)) if num(f.get(k)) is not None else nan for k in model["features"]]
    s = sum(_tree(t, x) for t in model["trees"])
    return 1.0 / (1.0 + math.exp(-s))


# ------------------------------------------------------------------------------------------------------------- the paper account
def net(mult):
    return M.tip_net(max(0.0, mult))


def near(a, b):
    """Whether two prices (or multiples) are at most GLITCH_X times apart; False when either is missing or not above zero."""
    a, b = num(a), num(b)
    return bool(a and b and a > 0 and b > 0 and 1.0 / GLITCH_X <= a / b <= GLITCH_X)


def believed(last, x, after, now_x=None):
    """Whether a close x (a multiple of the buy price) is the coin's price and not a glitch: near the close before it (last), or near
    DexScreener's price now (now_x, for a close of the last minutes or the newest close), or near both of the two closes after it (a level
    the chart stays at)."""
    return near(x, last) or near(x, now_x) or (len(after) == 2 and all(near(x, y) for y in after))


def rule(p, t, x):
    """Rocket hold on one close x (a multiple of the buy price) at minute t: the reason to sell, or None. Updates p's best and last."""
    p["last"], p["lastT"] = round(x, 6), int(t)
    if x <= FLOOR:
        return "floor"
    p["best"] = round(max(num(p.get("best")) or 1.0, x), 6)
    if p["best"] >= ARM and x <= KEEP * p["best"]:
        return "trail"
    if t + MIN - p["t"] >= HOLD_MS:
        return "24h"
    return None


class Book:
    """The Rocket seeker's paper account: doc = {"open": {addr: pos}, "closed": [pos, ...]}."""

    def __init__(self, doc=None):
        doc = doc if isinstance(doc, dict) else {}
        self.open = doc.get("open") if isinstance(doc.get("open"), dict) else {}
        self.closed = doc.get("closed") if isinstance(doc.get("closed"), list) else []

    def bought(self, a):
        return a in self.open or any(p.get("addr") == a for p in self.closed)

    def buy(self, a, sym, pool, px, now, sc, cut):
        if self.bought(a) or not px or px <= 0:
            return None
        p = {"addr": a, "sym": sym, "pool": pool, "t": int(now), "px": px, "score": round(sc, 4), "cut": round(cut, 4), "best": 1.0, "last": 1.0}
        self.open[a] = p
        return p

    def update(self, a, now, closes, px=None, liq=None):
        """closes: [(minute ms, close)] of the minutes since the last look; a minute counts once it started after the buy, and only a
        believed close (no glitch) is judged. px: the price now (DexScreener); liq: the liquidity now ($, the coin's pools on
        DexScreener; under RUG_LIQ a rug, sold at 0). Returns the closed position or None."""
        p = self.open.get(a)
        if not p:
            return None
        xs = sorted((t, c / p["px"]) for t, c in (closes or []) if c and c > 0)
        now_x = px / p["px"] if px and px > 0 else None
        for i, (t, x) in enumerate(xs):
            if t < p["t"] or t <= (num(p.get("lastT")) or 0):
                continue
            if not believed(num(p.get("last")) or 1.0, x, [y for _, y in xs[i + 1:i + 3]], now_x if now - t <= NEAR_MS or i == len(xs) - 1 else None):
                continue
            why = rule(p, t, x)
            if why:
                return self._close(a, t + MIN, p["last"], why)
        if px and px > 0:
            p["now"] = round(px / p["px"], 6)
        if liq is not None and liq < RUG_LIQ:
            return self._close(a, now, 0.0, "rug")
        if now - p["t"] >= HOLD_MS:
            return self._close(a, now, num(p.get("last")) or num(p.get("now")) or 0.0, "24h")
        return None

    def _close(self, a, at, mult, why):
        p = self.open.pop(a)
        p.update(out=int(at), mult=round(mult, 4), eur=net(mult), why=why, g=1)      # g: sold with the glitch guard (GLITCH_X)
        self.closed.append(p)
        return p

    def reopen_glitches(self):
        """Sales booked before the glitch guard (no "g") at a multiple more than GLITCH_X off DexScreener's price at the look before
        ("now"): sold on a glitch (NEX Ai and .AiTown, 27 Oct). Each is open again as bought, its old booking kept under "was", so the
        next look judges it again on its candles since the buy. -> their addresses"""
        back = []
        for p in list(self.closed):
            if p.get("g") or not num(p.get("now")) or near(p.get("mult"), p.get("now")) or p.get("addr") in self.open:
                continue
            self.closed.remove(p)
            p["was"] = {k: p.pop(k) for k in ("out", "mult", "eur", "why", "best", "last", "lastT") if k in p}
            p.update(best=1.0, last=1.0)
            self.open[p["addr"]] = p
            back.append(p["addr"])
        return back

    def summary(self):
        eur = [p["eur"] for p in self.closed]
        open_val = sum(net(num(p.get("now")) or num(p.get("last")) or 1.0) for p in self.open.values())
        allp = list(self.closed) + list(self.open.values())
        return {"trades": len(self.closed), "open": len(self.open), "eur": round(sum(eur), 2), "openEur": round(open_val, 2),
                "inProfitOf10": round(10 * sum(1 for e in eur if e > 0) / len(eur), 1) if eur else None,
                "x10": sum(1 for p in allp if (num(p.get("best")) or 0) >= 10), "x3": sum(1 for p in allp if (num(p.get("best")) or 0) >= 3),
                "x2": sum(1 for p in allp if (num(p.get("best")) or 0) >= 2), "avg": round(sum(eur) / len(eur), 3) if eur else None}

    def doc(self):
        return {"open": self.open, "closed": self.closed, "summary": self.summary()}
