#!/usr/bin/env python3
"""curve_watch.py: the launch radar's curve watch, the pure logic. Fake money only: it calls pump.fun coins on paper while they are still
on their bonding curve (no pool yet), it never buys, signs or sends anything, holds no key, and no call is advice; a call is a paper test
of whether the radar can name a coin 5-10 minutes earlier than today.

Why (the radar records of 14-15 Oct): the radar's first sight of a pump.fun coin comes a median 1.06 min after its pool opens (the live
feed's lag a median 29 s), but the run-up happens before that, on the curve: over the 71 graduated pump.fun coins with curve candles,
the last ~15 curve minutes before the pool rose a median +144% (the greens +99%). Example H2O (15 Oct): 72 minutes on the curve, the
pool at 10:53:32, the radar's push at 10:54:32 at 4.131e-05, 5.583e-05 a minute later.

What launch_radar.py feeds it (no request, no thread, no clock of its own; every time is the caller's ms):
  Book.rows(rows, now, src, info)    pump.fun list rows (the curve list sorted by market cap, the radar's newest-coins list): candidates,
                                     their progress, facts (mint time, creator, X link, socials) and graduations (complete); info(mint):
                                     the feed's create (its time, creator and curve state: a new coin's first progress reading)
  Book.trade(ev)                     one trade of a followed coin from the live feed (radar_feed's trade events, replayed in order). The
                                     list alone is the normal mode: PumpPortal sends coin trades only to paid API-key clients (none came
                                     in the first live run, 15 Oct), so the book is fed by the lists and the trade path stays for a feed
                                     that does send them
  Book.migrate(mint, t, via)         a graduation (the feed's migrate event, the list's complete flag, a coin fetch)
  Book.follow(now) / set_follow()    the coins to follow live (subscribeTokenTrade, at most FOLLOW_MAX), and which ones are followed
  Book.check_order(now)              the coins whose quick checks are due (the caller runs them and sets the verdict: set_check)
  Book.value_due(now) / set_value()  the calls whose 60-minute value is due, and the value the caller found (pool or curve price)
  Book.variants(), Book.doc()        the paper test's table and radar.json's "curve" block
Progress (pump.fun's curve, constant product): 1,073,000,000 virtual tokens at the start, 793,100,000 real tokens to sell; progress =
sold / 793.1M from the virtual token reserves when a reading has them, else from the market cap in SOL (the same curve: k = 30 SOL x
1.073e9 tokens), sanity-checked to 0-100 % (an implausible reading is unknown, never 0). Self-calibration: the market cap and the raw
progress (before clamp, so a constant that reads too high shows as over 100 %) at the last trade before each graduation are kept; their
median shows a wrong constant in the doc, and from CAL_MIN graduations on a median progress more than CAL_TOL off 100 % scales every
reading, either way (bounded to 0.67-1.5).
Calls: a followed coin whose progress crosses 60, 75 or 90 % (a reading under the threshold at most CROSS_WIN_MS before the one over it;
a coin first seen above a threshold is not called for it, only counted as "late" when it could have been called) gets one record per
threshold (the first crossing): time, progress, market cap (SOL, USD when the SOL price is known), price (SOL per token), minutes since
the mint, the momentum numbers (progress points gained and buys/sells in the last MOM_WIN_MS) and the quick-check verdict at that moment
(a verdict that comes within LATE_MS of a call made without one is kept beside it, with the price of that moment). Variants on paper,
side by side: each threshold with and without the momentum filter (at the crossing: MOM_PTS points or more in 5 minutes, and more buys
than sells when the coin's trades are known; from the list's readings alone, without trades, the points alone; the call keeps which in
momBy, "trades" or "list"), each split by the verdict ok / risky / trap / unknown (a late verdict's call entered at its own price).
Outcomes (judged 60 minutes after the call): graduated or not and how many minutes later (only when someone saw it: an hour nobody
watched is unseen, never "did not graduate"), the price at the graduation, the value at call + 60 min (the pool's DexScreener price,
converted at the call's SOL price, or the curve price: from the trades, the list's first reading after the hour or a coin fetch), the
peak within the hour (the list's readings and the trades on the curve, the radar's prices of the pool), rugged and doubled by
traps.outcome's rules as the greens are (judged: gone, dead or 0.1x or less at 60 minutes; 2x to 30x within the hour and not gone or
dead at 60), and a paper result: TICKET EUR in at the call price plus SLIP (stated slippage) with the paper fees, valued at 60 minutes
(gone or a dead pool 0, a dead curve at its curve price: it buys back). A value nobody could read is missing, never 0.
Hindsight only: nothing here changes the radar's verdicts, its points, its list or its pushes. Standard library and memebot (read only).
"""
import collections, datetime as dt, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

# ---------------------------------------------------------------- pump.fun's curve
VT0 = 1_073_000_000.0       # virtual token reserves at the start of a pump.fun curve
SELL = 793_100_000.0        # real tokens the curve sells before it completes (the other 206.9M go to the pool)
VS0 = 30.0                  # virtual SOL at the start
SUPPLY = 1e9                # tokens
K = VS0 * VT0               # the curve's constant product
MC_END = K * SUPPLY / (VT0 - SELL) ** 2      # market cap in SOL when the curve completes (about 410.9 SOL)
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
LONE = re.compile("[\ud800-\udfff]")      # in a str from JSON a surrogate is always a lone half (a pair is one character)
MIN, H = 60_000, 3_600_000

# ---------------------------------------------------------------- calls and their variants
THRESHOLDS = (60, 75, 90)   # % of the curve sold: a 60 % call has up to 4.6x of curve left (price ~ 1/vTokens^2), 75 % 2.9x, 90 % 1.65x; the
                            # records' median run-up (+144% in the last ~15 curve minutes) starts around 72 %, so 75 % sits about 10-15 minutes
                            # before a typical pool, 90 % a few minutes before it, 60 % earlier and with more coins that never finish
MOM_WIN_MS = 5 * MIN        # the momentum window
MOM_PTS = 10.0              # progress points gained in it (a pace that finishes 75 -> 100 % within about 12 minutes, the records' median
                            # graduating coin's pace) ...
                            # ... and more buys than sells in it when the coin's trades are followed live (momBy "trades"); without them
                            # (pump.fun's list only, the normal mode) the points alone (momBy "list"); no reading: unknown, never yes
MOM_COVER_MS = 2 * MIN      # the least of the window the readings must cover (a coin followed for a minute has no momentum reading)
MOM_STALE_MS = 2 * MIN      # the reading the gain counts from is at most this long before the window's start (a round's gap in the list
                            # polls fits; a coin back on the list after a long while, or a create an hour old, gives no gain spread
                            # over a longer time than the window)
MOM_BY = ("list", "trades") # which momentum a call had: the points alone (no trades known) or the points and more buys than sells
CROSS_WIN_MS = 10 * MIN     # a reading under the threshold this recent makes the next one over it a crossing
VERDICTS = ("ok", "risky", "trap", "unknown")
VARIANT_RE = re.compile(r"^(60|75|90)(m?)$")

# ---------------------------------------------------------------- following
FOLLOW_MAX = 40             # coins followed live at once (subscribeTokenTrade keys on the one socket)
FOLLOW_MIN = 30.0           # % a coin needs to be followed (under it the 60 % call is far off)
FOLLOW_KEEP = 5.0           # points of head start a followed coin keeps over a new one (no churn of subscriptions)
STALE_MS = 15 * MIN         # a coin with no trade (list or feed) this long is not a candidate (pump.fun's market-cap order holds old coins)
CHECK_AT = 45.0             # % from which a coin's quick checks start (done before its 60 % call)
TRADE_FRESH_MS = 60_000     # a coin with a feed trade this recent takes no list reading (the trades are newer)
PTS_KEEP = 240              # progress readings kept per coin
BOOK_MAX = 3000             # coins in the book (the least recently seen without a call go first)

# ---------------------------------------------------------------- calibration
CAL_MIN = 5                 # graduations with a last trade before the calibration is applied
CAL_TOL = 0.05              # ... when the median progress at the last trade is more than this off 100 %
CAL_WIN_MS = 2 * MIN        # the last trade must be this close to the graduation
CAL_KEEP = 200
RAW_LO, RAW_HI = -50.0, 200.0   # a raw reading kept for the calibration (unclamped: a constant that reads too high shows as over 100 %)

# ---------------------------------------------------------------- outcomes and the paper result
VALUE_MS = 60 * MIN         # a call is judged at call + 60 min
SETTLE_LATE_MS = 20 * MIN   # a value not read within this after its time stays missing (never 0)
POOL_SLACK_MS = 5 * MIN     # a radar later price this close to call + 60 min serves as the value when DexScreener was not read
GRAD_KNOWN_MS = 3 * MIN     # a list's complete flag this soon after the coin's last reading on the curve dates its graduation; later, its
                            # time is unknown (graduated: never a made-up time or minutes)
TICKET = 3.0                # EUR on paper per call (the new-launch ticket)
SLIP = 0.05                 # stated slippage: the paper entry is the call price + 5 % (a hot curve moves a few % in the seconds between a
                            # call and a fill; the 3 EUR itself moves a curve of 30-115 SOL by far less than 0.1 %)
RUG_X, WIN_X, DEAD_LIQ, PEAK_MAX = 0.10, 2.0, 1_000.0, 30.0   # traps.outcome's rules, the greens' row is judged by the same (judged):
                            # gone, dead or 0.1x or less at 60 minutes is a rug; 2x to 30x within the hour a double, never on a coin gone
                            # or dead at 60 minutes (a higher peak is a bad reading)
DEAD_PROG = 5.0             # a curve sold back under 5 % is dead: a rug by those rules (its price is still the value: the curve buys back,
                            # so 0.1x itself never happens on a curve: a 60 % call sold back to nothing is still worth about 0.3x)
LATE_MS = 90_000            # a verdict this soon after a call made without one (unknown) counts for it, at the price of that moment (the
                            # curve push's wait, launch_radar.CURVE_PUSH_WAIT_MS: the split and the push judge the same calls)

# ---------------------------------------------------------------- storage
KEEP_MS = 48 * H            # hour docs on radar-data (db/memecurve/<UTC hour>.json), like the radar's records
RECENT_N = 10               # calls in radar.json's curve block
DOC_MAX = 9_000             # bytes of the curve block (radar.json stays under launch_radar.DOC_MAX)


def num(v):
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fin(v, nd=None):
    x = num(v)
    return None if x is None else (round(x, nd) if nd is not None else x)


def sig(v, n=4):
    """A price to n significant digits (curve prices are 1e-8 to 1e-6 SOL)."""
    x = num(v)
    return None if x is None or x <= 0 else float("%.*g" % (n, x))


def utc_hour(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H")


def hour_ms(hour):
    return int(dt.datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def text(v, n):
    """A chain string for the docs: one line without control, bidi or zero-width marks and without a lone surrogate half (a JSON escape a
    backend cut in two: no character, and the page could not encode it), at most n characters (the page escapes it)."""
    return LONE.sub("", CTRL.sub("", str(v or "")))[:n]


def ms_of(v):
    """A time from pump.fun (ms, s or an ISO date) in ms, else None."""
    x = M.parse_ms(v)
    return int(x) if x else None


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


# ---------------------------------------------------------------- progress
def clamp(p):
    """A progress reading in % -> 0..100, or None when it is implausible (more than 2 points outside: a unit or a constant is wrong)."""
    if p is None or not -2.0 <= p <= 102.0:
        return None
    return max(0.0, min(100.0, p))


def raw_ok(p):
    """A raw progress reading (before clamp and the calibration's scale) kept for the calibration: -50 to 200 %, else None (a reading that
    far off is a wrong unit, not a constant a few % off)."""
    return p if p is not None and RAW_LO <= p <= RAW_HI else None


def tokens(v):
    """Token reserves in tokens: pump.fun's lists send raw units (6 decimals), PumpPortal tokens."""
    x = num(v)
    if x is None or x <= 0:
        return None
    return x / 1e6 if x > VT0 * 1000 else x


def raw_vt(vt):
    """% of the curve sold from the virtual token reserves, before clamp (raw_ok's range)."""
    x = tokens(vt)
    return raw_ok((VT0 - x) / SELL * 100.0) if x else None


def raw_rt(rt):
    """% of the curve sold from the real token reserves still to sell (0 at the end; raw units when over twice what a curve sells), before
    clamp."""
    x = num(rt)
    if x is None or x < 0:
        return None
    x = x / 1e6 if x > SELL * 2 else x
    return raw_ok((1.0 - x / SELL) * 100.0)


def raw_mc(mcs):
    """% of the curve sold from the market cap in SOL (the same constant product: vTokens = sqrt(k x supply / mc)), before clamp."""
    x = num(mcs)
    if x is None or x <= 0:
        return None
    return raw_vt(math.sqrt(K * SUPPLY / x))


def prog_vt(vt):
    """% of the curve sold from the virtual token reserves (clamp: 0-100, an implausible reading None)."""
    return clamp(raw_vt(vt))


def prog_rt(rt):
    return clamp(raw_rt(rt))


def prog_mc(mcs):
    return clamp(raw_mc(mcs))


def mc_of_prog(p):
    """The curve's market cap in SOL at p % sold."""
    vt = VT0 - SELL * p / 100.0
    return K * SUPPLY / (vt * vt) if vt > 0 else None


def curve_left(p):
    """Tokens the curve account still holds at p % sold (the rest to sell plus the pool's 206.9M): pump.fun's top-holders list counts that
    account as a holder entered at the mint; it is the curve, not a sniper."""
    return SELL * (1.0 - p / 100.0) + (SUPPLY - SELL)


def row_facts(c, sol=None):
    """A pump.fun coin row (the curve list, coins-v3, or the radar's newest-coins row in the same keys) -> the facts the book keeps, or None
    without a base58 mint: mint, sym, name, creator, tm (mint ms), x (X link), soc (links count), done (complete), ltt (last trade ms),
    prog (%), praw (the same before clamp: the calibration scales it), mcs (SOL), sol (the row's own USD per SOL), curve (the bonding-curve
    accounts, holders that are not buyers)."""
    if not isinstance(c, dict):
        return None
    a = c.get("mint")
    if not (isinstance(a, str) and B58.fullmatch(a)):
        return None
    mcs, usd = num(c.get("market_cap")), num(c.get("usd_market_cap"))
    own = usd / mcs if usd and mcs and usd > 0 and mcs > 0 else None
    raw = raw_vt(c.get("virtual_token_reserves"))
    if raw is None:
        raw = raw_rt(c.get("real_token_reserves"))
    if raw is None and mcs:
        raw = raw_mc(mcs)
    if raw is None and usd and (own or sol):
        raw = raw_mc(usd / (own or sol))
    p = clamp(raw)
    if mcs is None and p is not None:
        mcs = mc_of_prog(p)
    links = [c.get(k) for k in ("twitter", "telegram", "website")]
    x = c.get("twitter") if isinstance(c.get("twitter"), str) and re.match(r"^https://(www\.)?(x|twitter)\.com/", c["twitter"]) else ""
    curve = [v for v in (c.get("bonding_curve"), c.get("associated_bonding_curve")) if isinstance(v, str) and B58.fullmatch(v)]
    return {"mint": a, "sym": text(c.get("symbol"), 24), "name": text(c.get("name"), 48), "creator": c.get("creator") if isinstance(c.get("creator"), str) and B58.fullmatch(c["creator"]) else None,
            "tm": ms_of(c.get("created_timestamp")), "x": x[:200], "soc": sum(1 for v in links if isinstance(v, str) and v.strip()), "done": c.get("complete") is True,
            "ltt": ms_of(c.get("last_trade_timestamp")), "prog": p, "praw": raw, "mcs": mcs, "sol": own, "curve": curve}


def paper(x, slip=SLIP):
    """The paper result of TICKET EUR in at the call price plus slip, with the paper account's fees, valued at x times the call price (None:
    not valued; 0: a rug or a dead coin)."""
    if x is None:
        return None
    return round(M.pos_value({"ticket": TICKET, "grp": "young", "paper": M.PAPER_RULE}, 1.0, max(0.0, x) / (1.0 + slip)) - TICKET, 2)


def variant_of(s):
    """A variant id ("60", "75m", ...: the threshold, m for the momentum filter) -> (threshold, momentum) or None."""
    m = VARIANT_RE.match(str(s or "").strip())
    return (int(m.group(1)), bool(m.group(2))) if m else None


def variant_id(thr, mom):
    return "%d%s" % (thr, "m" if mom else "")


def in_variant(call, thr, mom):
    """Whether a call counts for the variant: its threshold, and with the filter only a call whose momentum held at the crossing."""
    return call.get("thr") == thr and (not mom or call.get("mom") is True)


# ---------------------------------------------------------------- the quick checks' verdict
CURVE_HARD = ("rugger_wallets", "brand_name", "rc_danger")        # the radar's hard traps that can apply before a pool exists
CURVE_SOFT = ("no_socials", "holder_cluster", "creator_sold")     # its soft warnings that can
CURVE_RED = ("dev_dead", "x_copied", "tweet_shared", "sniped30", "bundle_slot")   # measured red flags (weight 0 in the radar): risky here,
                                                                  # so the test shows whether they matter on the curve
CURVE_INFO = ("dev_young", "fresh_holders", "fund_cluster")       # shown grey only (a fresh dev wallet is the rule on pump.fun)
RC_POOL_RISK = re.compile(r"liquidity|\blp\b|lp provider|market", re.I)   # RugCheck risks about a pool: none exists yet, not counted


def verdict(T, S, W):
    """The curve verdict of a coin's signals S (traps' keys) with the radar's weights W, through traps.flag and traps.chips: trap (a hard
    trap that applies on the curve), risky (a soft warning or a measured red flag), unknown (nothing found, but the RugCheck report, the
    wallet memory or the dev history is missing), ok (all three done, nothing found). -> (verdict, chips [[level, text]] at most 6)."""
    hard = [f for f in CURVE_HARD if f in W.get("hard", ()) and T.flag(f, S, W)]
    soft = [f for f in CURVE_SOFT if f in W.get("soft", ()) and T.flag(f, S, W)]
    red = [f for f in CURVE_RED if T.flag(f, S, W)]
    grey = [f for f in CURVE_INFO if T.flag(f, S, W)]
    unknown = []
    if S.get("rcReport") is not True:
        unknown.append("rc_report")
    elif S.get("wmChecked") is not True:
        unknown.append("walletmem")
    if S.get("devN") is None:
        unknown.append("dev_history")
    v = "trap" if hard else "risky" if soft or red else "unknown" if unknown else "ok"
    try:
        chips = T.chips({"hard": hard, "soft": soft, "unknown": unknown, "info": red + grey, "plus": []}, S, W)
    except Exception:
        chips = []
    return v, [[str(c[0])[:8], text(c[1], 60)] for c in chips if isinstance(c, (list, tuple)) and len(c) >= 2][:6]


# ---------------------------------------------------------------- the book
class Book:
    """The curve watch's state: coins (in memory only), calls (hour docs, kept KEEP_MS), the calibration and the SOL price."""

    def __init__(self):
        self.coins, self.docs, self.call_hour, self.fol, self.vtrack = {}, {}, {}, {}, {}
        self.gaps = collections.deque(maxlen=200)       # when the feed reconnected (trades in between may be missing): feed_gap
        self.cal, self.sols = collections.deque(maxlen=CAL_KEEP), collections.deque(maxlen=50)
        self.scale = 1.0
        self.n = dict.fromkeys(("rows", "trades", "calls", "late", "grads", "polls"), 0)

    # ---- hour docs
    def hour_doc(self, t):
        h = utc_hour(t)
        return self.docs.setdefault(h, {"v": 1, "hour": h, "t": hour_ms(h), "upd": t, "polls": 0, "coins": {}})

    def entry(self, mint):
        """The coin's doc entry (its calls), or None."""
        h = self.call_hour.get(mint)
        return ((self.docs.get(h) or {}).get("coins") or {}).get(mint) if h else None

    def calls(self):
        """Every call of the kept hours: [(mint, call)]."""
        return [(a, c) for d in self.docs.values() for a, e in (d.get("coins") or {}).items() for c in (e.get("calls") or {}).values() if isinstance(c, dict)]

    def call(self, mint, thr):
        return ((self.entry(mint) or {}).get("calls") or {}).get(str(thr))

    def load(self, hour, doc):
        """An hour doc from radar-data (or a local copy) merged in: per call the copy that knows more; a call in another shape is repaired
        or left out (call_ok: doc_calls counts the same, the never-shrink guard compares like with like)."""
        if not isinstance(doc, dict) or not isinstance(doc.get("coins"), dict):
            return
        fresh = hour not in self.docs
        mine = self.docs.setdefault(hour, {"v": 1, "hour": hour, "t": hour_ms(hour), "upd": doc.get("upd"), "polls": 0, "coins": {}})
        mine["polls"] = max(int(num(mine.get("polls")) or 0), int(num(doc.get("polls")) or 0))
        mine["late"] = max(int(num(mine.get("late")) or 0), int(num(doc.get("late")) or 0))
        for a, e in doc["coins"].items():
            if not isinstance(e, dict) or not isinstance(e.get("calls"), dict):
                continue
            m = mine["coins"].setdefault(a, dict({k: e.get(k) for k in ("mint", "sym", "tm", "creator")}, calls={}))
            for k, c in e["calls"].items():
                c = call_ok(k, c)
                if c is not None and (k not in m["calls"] or weight(c) > weight(m["calls"][k])):
                    m["calls"][k] = c
            if m["calls"]:
                self.call_hour[a] = hour
            else:
                mine["coins"].pop(a, None)
        if fresh and not mine["coins"] and not mine["polls"]:
            self.docs.pop(hour, None)            # nothing usable in it

    def prune(self, now):
        for h in [h for h in self.docs if hour_ms(h) < now - KEEP_MS]:
            for a in self.docs[h].get("coins") or {}:
                if self.call_hour.get(a) == h:
                    self.call_hour.pop(a, None)
            self.docs.pop(h)
        for k in [k for k in self.vtrack if self.call(*k) is None]:
            self.vtrack.pop(k, None)
        if len(self.coins) > BOOK_MAX:
            keep = sorted(self.coins.values(), key=lambda c: (c["mint"] in self.call_hour or c["mint"] in self.fol, c.get("seen") or 0), reverse=True)[:BOOK_MAX]
            self.coins = {c["mint"]: c for c in keep}

    def counts(self, since=0):
        """{hour: calls} of the hour docs from since (the never-shrink guard's count)."""
        return {h: sum(len(e.get("calls") or {}) for e in (d.get("coins") or {}).values()) for h, d in self.docs.items() if hour_ms(h) >= since}

    def polled(self, now):
        """A list poll answered: the hour counts as watched (the greens of the same hours are the comparison)."""
        d = self.hour_doc(now)
        d["polls"] = int(num(d.get("polls")) or 0) + 1
        d["upd"] = now
        self.n["polls"] += 1

    # ---- coins
    def coin(self, mint, now=None):
        c = self.coins.get(mint)
        if c is None:
            c = self.coins[mint] = {"mint": mint, "sym": "", "name": "", "creator": None, "tm": None, "x": "", "soc": None, "curve": [], "seen": now,
                                    "pts": collections.deque(maxlen=PTS_KEEP), "tr": collections.deque(), "p": None, "pt": None, "praw": None,
                                    "px": None, "mcs": None, "ltr": None, "t0tr": None, "above": {}, "grad": None, "csold": None, "chk": None, "src": None,
                                    "lpt": None}
        return c

    def sol(self):
        """USD per SOL: the median of the last list rows' own ratio (usd_market_cap / market_cap), None without one."""
        return median(list(self.sols))

    def rows(self, rows, now, src="list", info=None):
        """pump.fun rows: candidates with their facts and a progress reading at now (a curve's price holds between trades, so the state
        at its last trade is its state now; it moves the open calls' peak and value track as a trade does); a complete row graduates a
        coin the book knows. info(mint): the feed's create facts {t, creator} for a missing mint time or creator. Returns the rows read."""
        got = 0
        for r in rows or []:
            f = row_facts(r, self.sol())
            if f is None:
                continue
            got += 1
            if f["sol"]:
                self.sols.append(f["sol"])
            a = f["mint"]
            if f["done"]:
                c0 = self.coins.get(a)
                if c0 is not None and c0.get("grad") is None:
                    if now - (c0.get("pt") or 0) <= GRAD_KNOWN_MS:
                        self.migrate(a, now, "list")
                    else:
                        self.graduated(a, now)
                continue
            c = self.coin(a, now)
            c["seen"], c["src"] = now, c.get("src") or src
            for k in ("sym", "name", "creator", "tm", "x", "soc"):
                if f.get(k) not in (None, ""):
                    c[k] = f[k]
            c["curve"] = list(dict.fromkeys(c["curve"] + f["curve"]))[:4]
            if info and (not c["tm"] or not c["creator"] or (c["pt"] is None and not c["pts"])):
                fi = info(a) or {}
                c["tm"] = c["tm"] or ms_of(fi.get("t"))
                c["creator"] = c["creator"] or (fi.get("creator") if isinstance(fi.get("creator"), str) and B58.fullmatch(fi["creator"]) else None)
                if c["pt"] is None and not c["pts"]:
                    self.first_reading(c, fi, now)
            if f["ltt"]:
                c["ltt"] = max(c.get("ltt") or 0, f["ltt"])
            if f["praw"] is None or c.get("grad") is not None:
                continue
            if c["ltr"] and now - c["ltr"][0] < TRADE_FRESH_MS:
                continue                 # trades of this coin came in the last minute: they are newer than any list
            self.point(c, now, clamp(f["praw"] * self.scale), (f["mcs"] or 0) / SUPPLY or None, f["mcs"], "list")
        self.n["rows"] += got
        return got

    def first_reading(self, c, fi, now):
        """A new coin's create on the feed (fi: {t, vtok, mcs}) as its first progress reading, before any list reading: for momentum only
        (kept in its readings, never the reading under a mark that makes the next one a crossing: a coin first listed past a mark was not
        seen crossing it)."""
        t = ms_of(fi.get("t"))
        raw = raw_vt(fi.get("vtok"))
        if raw is None:
            raw = raw_mc(fi.get("mcs"))
        p = clamp(raw * self.scale) if raw is not None else None
        if t and p is not None and t < now:
            c["pts"].append((t, p))

    def trade(self, ev):
        """One trade of a followed coin (radar_feed's event {mint, t, side, sol, tok, vsol, vtok, mcs, who, pool}): a curve trade (pool pump or
        none) is a progress and price reading; the creator selling is noted (creator_sold); the open calls' peak and value tracks move."""
        a = ev.get("mint") if isinstance(ev, dict) else None
        if a not in self.coins or not isinstance(ev.get("t"), int):
            return []
        c, t = self.coins[a], ev["t"]
        self.n["trades"] += 1
        pool = str(ev.get("pool") or "pump").lower()
        if pool not in ("pump", "pump.fun", "pumpfun", "bonding_curve"):
            return []                    # a trade on the pool: the graduation comes as its own event
        side = 1 if ev.get("side") == "buy" else -1 if ev.get("side") == "sell" else 0
        if side:
            c["tr"].append((t, side))
            c["t0tr"] = c["t0tr"] or t
        while c["tr"] and c["tr"][0][0] < t - MOM_WIN_MS - MIN:
            c["tr"].popleft()
        if side < 0 and ev.get("who") and ev.get("who") == c.get("creator"):
            c["csold"] = True
        vt, vs, mcs = tokens(ev.get("vtok")), num(ev.get("vsol")), num(ev.get("mcs"))
        if vs and vs > 1e6:
            vs /= 1e9                    # lamports
        if not (mcs and mcs > 0) and vt and vs and vs > 0:
            mcs = vs / vt * SUPPLY
        praw = raw_vt(vt) if vt else None      # before clamp: the calibration keeps it, a constant that reads too high shows over 100 %
        if praw is None and mcs:
            praw = raw_mc(mcs)
        px = mcs / SUPPLY if mcs and mcs > 0 else None
        c["ltr"] = (t, px, mcs, praw)
        if px:
            self.track(a, t, px, "trade")
        if praw is None:
            return []
        return self.point(c, t, clamp(praw * self.scale), px, mcs, "trade")

    def track(self, a, t, px, via):
        """A price reading of a coin (a curve trade, or a list reading: the list alone is the normal mode) moves its open calls: within the
        hour their peak (the call's and a late verdict's since its time) and the value track's last price; after it, a trade's first price
        with whether every trade since the last one was seen (after), or the list's first reading at or after the hour (list: the value as a
        coin fetch then would read it)."""
        for thr in THRESHOLDS:
            cl = self.call(a, thr)
            if cl is None or cl.get("out", {}).get("x60") is not None or not num(cl.get("px")):
                continue
            v = self.vtrack.setdefault((a, thr), {})
            T = cl["t"] + VALUE_MS
            if t <= T:
                v["last"] = (t, px)
                cl["hi"] = round(max(num(cl.get("hi")) or 1.0, px / cl["px"]), 4)
                lt = cl.get("late")
                if isinstance(lt, dict) and num(lt.get("px")) and t >= lt["t"]:
                    lt["hi"] = round(max(num(lt.get("hi")) or 1.0, px / lt["px"]), 4)
            if via == "list" and t >= T and "list" not in v:
                v["list"] = (int(t), px)
            elif via == "trade" and t > T and "after" not in v:
                v["after"] = (t, px, "last" in v and self.unbroken(a, v["last"][0], t))

    def point(self, c, t, p, px, mcs, via):
        """A progress reading: kept for momentum, and a crossing of a threshold (a reading under it at most CROSS_WIN_MS before) makes a call.
        A coin first seen above a threshold is "late" for it (no call); it is counted as a missed call (the hour doc's late) only when it
        could have been one: a trade within STALE_MS, and seen before or after the run's first poll (a book starts empty each run: its
        first poll's coins above a mark were past it long ago, stalled ones too). Returns the new calls."""
        if p is None or (c["pt"] is not None and t < c["pt"]):
            return []
        if via == "list":
            c["lpt"] = t
            if px:
                self.track(c["mint"], t, px, "list")     # the open calls' peak and value track (a trade's own reading moved them already)
        prev, prev_t = c["p"], c["pt"]
        c["pts"].append((t, p))
        c["p"], c["pt"], c["seen"] = p, t, max(c.get("seen") or 0, t)
        if px:
            c["px"], c["mcs"] = px, mcs
        new = []
        for thr in THRESHOLDS:
            if p < thr or self.call(c["mint"], thr) is not None or thr in c["above"]:
                continue
            if prev is not None and prev < thr and t - prev_t <= CROSS_WIN_MS:
                new.append(self.make_call(c, thr, t, p, px, mcs, via))
            else:
                c["above"][thr] = t
                if (prev is not None or self.n["polls"] >= 2) and t - self.last_trade(c) <= STALE_MS:
                    self.n["late"] += 1          # a coin that could have been called (trading, seen after the run's first poll), seen past
                    d = self.hour_doc(t)         # the mark: kept per hour like the calls (48 h), never the stalled coins of a first poll
                    d["late"] = int(num(d.get("late")) or 0) + 1
        return new

    def momentum(self, c, t):
        """{pts: progress gained in the last MOM_WIN_MS (from the last reading at or before its start when that one is at most MOM_STALE_MS
        older, else the first reading inside the window when it covers MOM_COVER_MS; the readings are the list's polls, the create's and the
        trades'), buys, sells (trades in the window, when the trades followed cover MOM_COVER_MS)}; None = not known."""
        pts = list(c["pts"])
        base = None
        for tp, pp in pts:
            if tp <= t - MOM_WIN_MS:
                base = (tp, pp)
            else:
                break
        if base is not None and base[0] < t - MOM_WIN_MS - MOM_STALE_MS:
            base = None                          # too old: the gain since it says nothing about the last 5 minutes
        if base is None:
            inside = [x for x in pts if t - MOM_WIN_MS < x[0] <= t]
            if inside and t - inside[0][0] >= MOM_COVER_MS:
                base = inside[0]
        gain = round(c["p"] - base[1], 2) if base and c["p"] is not None else None
        buys = sells = None
        if c["t0tr"] is not None and t - c["t0tr"] >= MOM_COVER_MS:
            w = [s for tt, s in c["tr"] if t - MOM_WIN_MS <= tt <= t]
            buys, sells = sum(1 for s in w if s > 0), sum(1 for s in w if s < 0)
        return {"pts": gain, "buys": buys, "sells": sells}

    def make_call(self, c, thr, t, p, px, mcs, via):
        m5 = self.momentum(c, t)
        by = None if m5["pts"] is None else "list" if m5["buys"] is None else "trades"
        mom = None if by is None else bool(m5["pts"] >= MOM_PTS and (by == "list" or m5["buys"] > m5["sells"]))
        sol = self.sol()
        chk = c.get("chk") or {}
        call = {"t": int(t), "thr": thr, "via": via, "prog": round(p, 2), "px": sig(px), "mcs": fin(mcs, 2), "sol": fin(sol, 2),
                "mcu": round(mcs * sol) if mcs and sol else None, "age": round((t - c["tm"]) / MIN, 1) if c.get("tm") and t >= c["tm"] else None,
                "m5": m5, "mom": mom, "momBy": by, "v": chk.get("v") or "unknown", "chips": list(chk.get("chips") or [])[:6], "hi": 1.0, "out": {},
                "push": None}
        d = self.hour_doc(t)
        a = c["mint"]
        h = self.call_hour.get(a)
        e = self.entry(a) if h else None
        if e is None:
            e = d["coins"][a] = {"mint": a, "sym": c.get("sym") or "?", "tm": c.get("tm"), "creator": c.get("creator"), "calls": {}}
            self.call_hour[a] = d["hour"]
        e["calls"][str(thr)] = call
        if call["px"]:
            self.vtrack[(a, thr)] = {"last": (int(t), call["px"])}     # a coin with no trade after its call keeps this price on the curve
        self.docs[self.call_hour[a]]["upd"] = t
        self.n["calls"] += 1
        return a, call

    def migrate(self, mint, t, via="feed"):
        """A graduation: the coin leaves the watch; the calibration takes its last trade (feed graduations only); its calls get the time and the
        price at the graduation (the last curve trade, when it came within CAL_WIN_MS)."""
        c = self.coins.get(mint)
        if c is not None and c.get("grad") is None:
            c["grad"] = t
            self.n["grads"] += 1
            ltr = c.get("ltr")
            if via == "feed" and ltr and 0 <= t - ltr[0] <= CAL_WIN_MS and ltr[3] is not None:
                self.cal.append((t, ltr[2], ltr[3]))
                self.recalibrate()
        ltr = (c or {}).get("ltr")
        e = self.entry(mint)
        for cl in ((e or {}).get("calls") or {}).values():
            o = cl.setdefault("out", {})
            if o.get("grad") is None and t >= cl["t"] - CAL_WIN_MS:
                o["grad"], o["gradVia"] = int(t), via
                o["gradMin"] = round(max(0.0, t - cl["t"]) / MIN, 1)
                if ltr and 0 <= t - ltr[0] <= CAL_WIN_MS and ltr[1] and num(cl.get("px")):
                    o["gx"] = round(ltr[1] / cl["px"], 4)

    def graduated(self, mint, now):
        """A graduation seen only after the fact (a list's complete flag long after the coin's last reading, pump.fun's coin fetch, no
        pool time known): the coin leaves the watch; its calls get no graduation time and no minutes (none is known), only that it
        graduated (done) and, when the coin was still read on the curve after a call's hour, that it graduated after it (gradAfter)."""
        c = self.coins.get(mint)
        if c is not None and c.get("grad") is None:
            c["grad"] = now
            self.n["grads"] += 1
        pt = (c or {}).get("pt") or 0
        for cl in ((self.entry(mint) or {}).get("calls") or {}).values():
            o = cl.setdefault("out", {})
            if o.get("grad") is None:
                o["done"] = True
                if pt > cl["t"] + VALUE_MS:
                    o["gradAfter"] = True

    def recalibrate(self):
        n = len(self.cal)
        pm = median([x[2] for x in self.cal])
        if n >= CAL_MIN and pm and abs(pm / 100.0 - 1.0) > CAL_TOL:
            self.scale = max(0.67, min(1.5, 100.0 / pm))
        else:
            self.scale = 1.0

    def calib(self):
        return {"n": len(self.cal), "mcSol": fin(median([x[1] for x in self.cal]), 1), "prog": fin(median([x[2] for x in self.cal]), 2),
                "scale": round(self.scale, 3), "expect": round(MC_END, 1)}

    # ---- following and checks
    def follow(self, now):
        """The coins to follow live, best first, at most FOLLOW_MAX: on the curve, FOLLOW_MIN % or more, a trade within STALE_MS; a coin
        with an open call and a coin already followed keep a head start."""
        out = []
        for a, c in self.coins.items():
            if c.get("grad") is not None or c["p"] is None or c["p"] < FOLLOW_MIN:
                continue
            if now - self.last_trade(c) > STALE_MS:
                continue
            bonus = (FOLLOW_KEEP if a in self.fol else 0.0) + (20.0 if self.open_call(a, now) else 0.0)
            out.append((c["p"] + bonus, a))
        return [a for _, a in sorted(out, reverse=True)[:FOLLOW_MAX]]

    @staticmethod
    def last_trade(c):
        """The coin's last trade (ms): pump.fun's last_trade_timestamp or a trade the feed brought; the last reading only when neither is
        known (a list without the field)."""
        last = max(c.get("ltt") or 0, (c["ltr"] or (0,))[0])
        return last or c.get("pt") or 0

    def set_follow(self, mints, now):
        """The coins followed now (the feed got them): since when, for the value of a call from its trades."""
        keep = {a: self.fol.get(a, now) for a in mints}
        self.fol = keep

    def open_call(self, a, now):
        e = self.entry(a)
        return any(now <= c["t"] + VALUE_MS for c in ((e or {}).get("calls") or {}).values())

    def check_order(self, now):
        """Coins whose quick checks may run, best first: called coins, then CHECK_AT % and more; on the curve, a trade within STALE_MS."""
        out = []
        for a, c in self.coins.items():
            if c.get("grad") is not None or c["p"] is None:
                continue
            called = a in self.call_hour
            if c["p"] < CHECK_AT and not called:
                continue
            if now - self.last_trade(c) > STALE_MS and not called:
                continue
            out.append((1 if called else 0, c["p"], a))
        return [a for _, _, a in sorted(out, reverse=True)]

    def set_check(self, mint, v, chips, now):
        """The coin's verdict now (the caller's quick checks): the next call takes it. A call made under LATE_MS ago without one (unknown)
        keeps "unknown" as its verdict at the call; the first verdict that comes late is noted beside it with its time and the curve's
        price then (late), and the split by verdict counts the call under it with the entry at that price: what a push at that moment
        would have had, never a verdict that rests on what happened after the entry (a creator selling after the call)."""
        c = self.coins.get(mint)
        if c is None:
            return
        v = v if v in VERDICTS else "unknown"
        c["chk"] = {"v": v, "chips": list(chips or [])[:6], "at": now}
        px = sig(c.get("px"))                    # the curve's price now (it holds between trades)
        if v == "unknown" or not px or c.get("grad") is not None:
            return
        for cl in ((self.entry(mint) or {}).get("calls") or {}).values():
            if cl.get("v") == "unknown" and not cl.get("late") and 0 <= now - cl["t"] <= LATE_MS:
                cl["late"] = {"v": v, "t": int(now), "px": px, "hi": 1.0, "chips": list(chips or [])[:6]}

    # ---- outcomes
    def value_due(self, now):
        """Calls whose value at call + VALUE_MS is due and not read yet: [(mint, threshold, kind)], kind "pool" (graduated by then: the
        pool's price) or "curve"; past SETTLE_LATE_MS a call is marked missing (never 0)."""
        out = []
        for a, cl in self.calls():
            o = cl.setdefault("out", {})
            T = cl["t"] + VALUE_MS
            if o.get("x60") is not None or o.get("miss") or now < T:
                continue
            if now > T + SETTLE_LATE_MS:
                o["miss"] = True
                continue
            out.append((a, cl["thr"], "pool" if o.get("grad") is not None and o["grad"] <= T else "curve"))
        return out

    def feed_gap(self, t):
        """The live feed reconnected at t (its trades between the old socket and the new one may be missing)."""
        self.gaps.append(int(t))

    def unbroken(self, mint, t0, t1):
        """Whether every trade of the coin from t0 to t1 was seen: followed without a break since t0 at the latest (set_follow keeps the
        time a coin has been followed since; one that dropped out and came back starts again) and no feed reconnect in between."""
        return mint in self.fol and self.fol[mint] <= t0 and not any(t0 < g <= t1 for g in self.gaps)

    def curve_value(self, mint, thr, now, followed):
        """The curve price at call + VALUE_MS from the trades followed: the price after the last trade at or before it (a curve's price
        holds between trades), when every trade from that one to the hour was seen (unbroken): a trade after the hour came while the coin
        was followed without a break, or it is still followed so (followed: the feed is up). Else the list's first reading at or after the
        hour (as a coin fetch then would read it). Else None (a coin fetch reads it) -> (t, px)."""
        cl = self.call(mint, thr)
        v = self.vtrack.get((mint, thr)) or {}
        if cl is None:
            return None
        T = cl["t"] + VALUE_MS
        if "last" in v and ((v.get("after") or (0, 0, False))[2] or (followed and self.unbroken(mint, v["last"][0], T))):
            return (T, v["last"][1])
        return v.get("list")

    def set_value(self, mint, thr, how, t, px=None, liq=None, sol=None, pool_pts=()):
        """A call's value at call + VALUE_MS: how "curve" (px in SOL per token), "pool" (px in USD, liq in USD, converted at the call's SOL
        price, else sol), "gone" (no pair, no coin: 0). pool_pts: the radar's pool prices [(t, USD)] up to the value time, for the peak.
        Settles x60, peak, rug and x2 (judged: traps.outcome's rules, as the greens' row), the paper result, and the same from a late
        verdict's price (out.late). Returns the call, or None when it cannot be settled (no SOL price for a pool)."""
        cl = self.call(mint, thr)
        if cl is None or not num(cl.get("px")):
            return None
        o = cl.setdefault("out", {})
        hi = num(cl.get("hi")) or 1.0
        lt = cl.get("late") if isinstance(cl.get("late"), dict) and num((cl.get("late") or {}).get("px")) else None
        lhi = (num(lt.get("hi")) or 1.0) if lt else None
        if how == "gone":
            x, how2 = 0.0, "gone"
        elif how == "pool":
            s = num(cl.get("sol")) or num(sol)
            if not s or not num(px):
                return None
            base = cl["px"] * s
            x = px / base
            how2 = "pool"
            if liq is not None and num(liq) is not None and liq < DEAD_LIQ:
                x, how2 = 0.0, "dead"
            for t_p, p in pool_pts or ():
                if num(p) and num(t_p) is not None and t_p <= cl["t"] + VALUE_MS:
                    hi = max(hi, p / base)
                    if lt and t_p >= lt["t"]:
                        lhi = max(lhi, p / (lt["px"] * s))
            hi = max(hi, x)
        else:
            if not num(px):
                return None
            x, how2 = px / cl["px"], "curve"
            p = prog_mc(px * SUPPLY)
            if p is not None and p < DEAD_PROG:
                how2 = "dead"
            hi = max(hi, x)
        rug, x2 = judged(x, hi, how2)
        o.update({"x60": round(x, 4), "at60": int(t), "how": how2, "peak": round(hi, 4), "rug": rug, "x2": x2, "eur": paper(x)})
        if lt:                                   # the entry at the late verdict's price (its own peak since then)
            lx = x * cl["px"] / lt["px"]
            lhi = max(lhi, lx)
            lrug, lx2 = judged(lx, lhi, how2)
            o["late"] = {"x60": round(lx, 4), "peak": round(lhi, 4), "rug": lrug, "x2": lx2, "eur": paper(lx)}
        return cl

    def set_miss(self, mint, thr, why):
        """A call whose value cannot be read (it stays missing, never 0): why in a few words."""
        cl = self.call(mint, thr)
        if cl is not None:
            cl.setdefault("out", {}).update(miss=True, why=str(why)[:60])

    def link_pool(self, mint, rec):
        """The radar's own record of the coin's pool (same mint): its first sight, the later prices as x of its first price and its 1 h labels."""
        if not isinstance(rec, dict):
            return
        px0 = num(rec.get("px"))
        lt = rec.get("later") if isinstance(rec.get("later"), dict) else {}
        out = rec.get("out") if isinstance(rec.get("out"), dict) else {}
        link = {"first": rec.get("first"), "x": {m: (0.0 if o.get("gone") else round(num(o.get("px")) / px0, 3) if num(o.get("px")) and px0 else None)
                                                 for m, o in lt.items() if isinstance(o, dict)},
                "rug1h": out.get("rug1h"), "win1h": out.get("win1h"), "good": rec.get("good"), "push": rec.get("push")}
        for cl in ((self.entry(mint) or {}).get("calls") or {}).values():
            cl.setdefault("out", {})["pool"] = link

    # ---- the paper test
    def variants(self, calls=None):
        """The variant table: per threshold, without and with the momentum filter: n calls, settled, graduated within the hour (share of
        the calls whose hour was seen: grad_seen), its median minutes, the calls whose hour nobody saw (unseen), rugged and doubled within
        the hour (judged), the average paper result, missing values; and the same split by the verdict at the call (split_of: a call made
        without one counts under the first verdict within LATE_MS, entered at that moment's price)."""
        calls = [c for _, c in (calls if calls is not None else self.calls())]
        rows = []
        for thr in THRESHOLDS:
            for mom in (False, True):
                cs = [c for c in calls if in_variant(c, thr, mom)]
                row = {"id": variant_id(thr, mom), "thr": thr, "mom": mom}
                row.update(stats(cs))
                sp = [split_of(c) for c in cs]
                by = {v: [c for v2, c in sp if v2 == v] for v in VERDICTS}
                row["by"] = {v: stats(g, short=True) for v, g in by.items() if g}
                rows.append(row)
        return rows

    def push_cands(self, now, var, verdicts, pushed, wait_ms):
        """The calls of the push variant that may get a notification now: made within wait_ms, the coin still on the curve, its verdict
        now one of verdicts and never trap, the coin never pushed. Newest first: [(mint, call, verdict)]."""
        if var is None:
            return []
        thr, mom = var
        out = []
        for a, cl in self.calls():
            c = self.coins.get(a) or {}
            v = (c.get("chk") or {}).get("v") or cl.get("v") or "unknown"
            if in_variant(cl, thr, mom) and 0 <= now - cl["t"] <= wait_ms and c.get("grad") is None and (cl.get("out") or {}).get("grad") is None \
                    and v != "trap" and v in verdicts and a not in pushed and not cl.get("push"):
                out.append((a, cl, v))
        return sorted(out, key=lambda x: -x[1]["t"])

    def doc(self, now, state, greens=None, extra=None):
        """radar.json's "curve" block: the watch's state, the newest RECENT_N calls, the variant table with the radar's greens of the same
        hours, the calibration; at most DOC_MAX bytes (recent calls cut first, then the verdict split)."""
        calls = self.calls()
        recent = []
        for a, cl in sorted(calls, key=lambda x: -x[1]["t"])[:RECENT_N]:
            e = self.entry(a) or {}
            o = cl.get("out") or {}
            recent.append({"mint": a, "sym": text(e.get("sym"), 24) or "?", "thr": cl["thr"], "t": cl["t"], "prog": cl.get("prog"), "mcu": cl.get("mcu"),
                           "mcs": cl.get("mcs"), "age": cl.get("age"), "mom": cl.get("mom"), "pts": (cl.get("m5") or {}).get("pts"),
                           "buys": (cl.get("m5") or {}).get("buys"), "sells": (cl.get("m5") or {}).get("sells"), "v": split_of(cl)[0],
                           "chips": list(((cl.get("late") or {}) if split_of(cl)[0] != cl.get("v") else cl).get("chips") or [])[:3], "push": cl.get("push"),
                           "out": {k: o.get(k) for k in ("grad", "gradMin", "x60", "peak", "rug", "x2", "eur", "how", "miss", "done") if o.get(k) is not None}})
        hours = sorted(h for h, d in self.docs.items() if num(d.get("polls")))
        d = {"v": 1, "t": now, "since": hour_ms(hours[0]) if hours else None, "hours": len(hours), "ticket": TICKET, "slip": SLIP,
             "thresholds": list(THRESHOLDS), "momPts": MOM_PTS, "calls": len(calls), "late": sum(int(num(d.get("late")) or 0) for d in self.docs.values()), "recent": recent,
             "variants": self.variants(calls), "greens": greens, "calib": self.calib()}
        d.update(state or {})
        d.update(extra or {})
        size = lambda x: len(json.dumps(x, separators=(",", ":")))
        while size(d) > DOC_MAX and d["recent"]:
            d["recent"] = d["recent"][:-1]
        if size(d) > DOC_MAX:
            for r in d["variants"]:
                r["by"] = {}
        return d

    def active_hours(self):
        return {h for h, d in self.docs.items() if num(d.get("polls"))}


def judged(x, peak, how):
    """traps.outcome's rules on a call's hour (the greens' row is judged by them): rugged = gone or dead at 60 minutes (no pair or coin, a
    pool under $1,000 of liquidity, a curve sold back under DEAD_PROG) or RUG_X or less; doubled = WIN_X to PEAK_MAX at the peak within the
    hour or at 60 minutes, never on a coin gone or dead at 60 minutes. -> (rug, x2)"""
    dead = how in ("gone", "dead")
    return bool(dead or x <= RUG_X), bool(not dead and (WIN_X <= peak <= PEAK_MAX or WIN_X <= x <= PEAK_MAX))


def split_of(c):
    """The verdict a call counts under in the split, and the call as counted: its verdict at the call, or for a call made without one
    (unknown) the first verdict that came within LATE_MS, with the entry at that moment's price (out.late; not valued yet when that
    is missing)."""
    v = c.get("v") if c.get("v") in VERDICTS else "unknown"
    lt = c.get("late")
    if v != "unknown" or not isinstance(lt, dict) or lt.get("v") not in VERDICTS or lt.get("v") == "unknown":
        return v, c
    o = c.get("out") if isinstance(c.get("out"), dict) else {}
    lo = o.get("late")
    out = dict(o, **lo) if isinstance(lo, dict) else {k: x for k, x in o.items() if k not in ("x60", "peak", "rug", "x2", "eur")}
    return lt["v"], dict(c, out=out)


def grad_seen(c):
    """Whether a call's coin graduated within its hour, as far as anyone saw: True / False, None when nobody saw (no graduation time
    and no value at the hour: the radar was not running, or the graduation came to light only later without its time)."""
    o = c.get("out") if isinstance(c.get("out"), dict) else {}
    if num(o.get("grad")) is not None:
        return o["grad"] <= c["t"] + VALUE_MS
    if o.get("gradAfter"):
        return False
    if o.get("done"):
        return None
    return False if o.get("x60") is not None else None     # valued at the hour on its curve (or gone): not graduated by then


def stats(cs, short=False):
    """The paper test's numbers of a group of calls (see Book.variants). The graduated share counts only the calls an hour old whose hour
    was seen (grad_seen); the others are unseen, never "did not graduate"."""
    settled = [c for c in cs if (c.get("out") or {}).get("x60") is not None]
    aged = [c for c in cs if (c.get("out") or {}).get("x60") is not None or (c.get("out") or {}).get("miss")]
    share = lambda xs, f: round(sum(1 for x in xs if f(x)) / len(xs), 3) if xs else None
    eurs = [c["out"]["eur"] for c in settled if num(c["out"].get("eur")) is not None]
    out = {"n": len(cs), "nS": len(settled), "rug": share(settled, lambda c: c["out"].get("rug")), "x2": share(settled, lambda c: c["out"].get("x2")),
           "eur": round(sum(eurs) / len(eurs), 2) if eurs else None}
    if not short:
        seen = [c for c in aged if grad_seen(c) is not None]
        g = [c for c in seen if grad_seen(c)]
        out.update(grad=round(len(g) / len(seen), 3) if seen else None, gradMin=fin(median([num(c["out"].get("gradMin")) for c in g]), 1),
                   miss=sum(1 for c in cs if (c.get("out") or {}).get("miss")), unseen=len(aged) - len(seen))
    return out


OUT_NUMS = ("grad", "gradMin", "gx", "x60", "at60", "peak", "eur")     # a stored outcome's numbers
CALL_NUMS = ("prog", "px", "mcs", "sol", "mcu", "age", "hi", "push")


def call_ok(k, c):
    """A stored call (key k in its coin's calls) as the book takes it, else None: a dict with an int time and a threshold of THRESHOLDS
    under its own key. The rest is repaired, never read as 0: a number in another form becomes one or none (an outcome's is dropped),
    an outcome that is not a dict is none yet, m5 a dict, chips a list, a verdict that is none of VERDICTS unknown, a late verdict whole
    or none, a momentum that is no bool none, its form (momBy) one of MOM_BY or left out (a call stored before it was kept: its
    momentum, if any, was the trades'). A copy: the stored doc is not changed."""
    if not isinstance(c, dict) or isinstance(c.get("t"), bool) or not isinstance(c.get("t"), int) or c.get("thr") not in THRESHOLDS or str(c.get("thr")) != str(k):
        return None
    c = dict(c)
    for f in CALL_NUMS:
        if f in c and c[f] is not None and (isinstance(c[f], bool) or not isinstance(c[f], (int, float)) or not math.isfinite(c[f])):
            c[f] = num(c[f])
    o = c.get("out") if isinstance(c.get("out"), dict) else {}
    c["out"] = {f: (v if f not in OUT_NUMS or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)) else num(v))
                for f, v in o.items() if f not in OUT_NUMS or num(v) is not None}
    if not isinstance(c["out"].get("late"), dict):
        c["out"].pop("late", None)
    lt = c.pop("late", None)                  # a late verdict: whole (its verdict, an int time, a price) or none
    if isinstance(lt, dict) and lt.get("v") in VERDICTS and isinstance(lt.get("t"), int) and not isinstance(lt.get("t"), bool) and num(lt.get("px")):
        c["late"] = dict(lt, px=num(lt["px"]), hi=num(lt.get("hi")))
    c["m5"] = c.get("m5") if isinstance(c.get("m5"), dict) else {}
    if not isinstance(c.get("mom"), bool):
        c["mom"] = None
    if c.get("momBy") not in MOM_BY:
        c.pop("momBy", None)
    c["chips"] = [x for x in c.get("chips") if isinstance(x, (list, tuple)) and len(x) >= 2][:6] if isinstance(c.get("chips"), list) else []
    if c.get("v") not in VERDICTS:
        c["v"] = "unknown"
    return c


def doc_calls(doc):
    """The calls Book.load takes from a stored hour doc (the never-shrink guard's count of a tree, by load's own rules)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("coins"), dict):
        return 0
    return sum(1 for e in doc["coins"].values() if isinstance(e, dict) and isinstance(e.get("calls"), dict) for k, c in e["calls"].items()
               if call_ok(k, c) is not None)


def weight(c):
    """Which of two copies of a call knows more (a restore merges the local and the branch copies)."""
    o = c.get("out") if isinstance(c.get("out"), dict) else {}
    return (1 if o.get("x60") is not None else 0, 1 if o.get("pool") else 0, 1 if o.get("grad") is not None else 0, 1 if c.get("push") else 0, len(o))


def greens_stats(recs, hours):
    """The radar's green coins of the same hours as the comparison: first good in a watched UTC hour; their 1 h value (the 60-minute price
    over the price when rated good; gone or under $1,000 of liquidity 0), the radar's own rug and win labels, the paper result with the
    same slippage. recs: the radar's records."""
    gs = [r for r in recs if isinstance(r, dict) and num(r.get("good")) and utc_hour(r["good"]) in hours]
    settled, eurs = [], []
    for r in gs:
        l60 = (r.get("later") or {}).get("60") if isinstance(r.get("later"), dict) else None
        gp = num(r.get("goodPx"))
        if not isinstance(l60, dict) or not gp:
            continue
        if l60.get("gone") or (num(l60.get("liq")) is not None and l60["liq"] < DEAD_LIQ):
            x = 0.0
        elif num(l60.get("px")):
            x = l60["px"] / gp
        else:
            continue
        settled.append(r)
        eurs.append(paper(x))
    out_k = lambda r, k: (r.get("out") or {}).get(k) if isinstance(r.get("out"), dict) else None
    known = lambda k: [r for r in settled if isinstance(out_k(r, k), bool)]
    share = lambda xs, k: round(sum(1 for r in xs if out_k(r, k)) / len(xs), 3) if xs else None
    return {"n": len(gs), "nS": len(settled), "rug": share(known("rug1h"), "rug1h"), "x2": share(known("win1h"), "win1h"),
            "eur": round(sum(eurs) / len(eurs), 2) if eurs else None, "grad": None}
