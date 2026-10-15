#!/usr/bin/env python3
"""traps.py: the launch radar's rule core (FAKE MONEY ONLY: nothing is ever bought, nothing here is advice).

Pure functions except feed(). Every weighted number comes from radar_weights.json (the rug study of 2026-10-13, frozen) or
from a radar-model refit that passed its walk-forward guard (fit). The video signals the bot never stored before ("M"
signals: dev history, copied X link, snipers, launch-block bundles, fresh or same-funded holders, early staircase, pump.fun
replies, a source tweet with many likes) are measured and shown grey with weight 0 until fit() promotes one on the radar's
own records. Unknown is never clean.

API (frozen, SPEC 13.10 section 5 WP1):
  load_weights(path=None, model=None) -> W        radar_weights.json; then the learned changes of model.json if they passed
  norm_x(url) -> (kind, key) | None               kind "tweet" | "account" | "community"
  staircase(closes, n_min=10) -> {"n","rise","green","pull","stair"}
  walletmem_lookup(holders, wm, now=None, W=None) -> {"swAvg","rugHolders","checked","state"}
  signals_scan(y, pr_mint_ms, wm, now=None, pool=None) -> S     one recommend.json young row; pr_mint_ms may be the coin's
                                                   mb/pairs.json entry (then the mint and the pool time both come from it)
  signals_radar(c) -> S                            the radar's merged coin dict (keys in its docstring)
  rate(S, W=None) -> {"verdict","pts","upside","hard","soft","plus","info","unknown","push","n"}
  chips(rating, S, W=None) -> [[level, text]]     level: bad | warn | unk | ok | info; at most 8
  outcome(rec) -> {"rug1h","win1h","x60"}
  fit(records, W, now) -> (W2 | None, report)     report is what the radar writes as model.json
  win_label(rec) -> 1 | 0 | None                  doubled with real liquidity (no rug) | rugged | neither, or a self-priced pool
  compare(records, W, now) -> report               winners vs losers at first sight, matched by UTC hour (model.json "cmp")
  win_fit(records, W, now) -> (wmodel | None, report)   the learned win order, walk-forward guarded (model.json "win")
  win_score(S, wmodel, W) -> int | None            the win order's score of one coin
  feed(d, out, now) -> meta                        python3 traps.py feed --dir mb --out feed --now <ms>
Helpers: rc_summary(report), xlinks_add(links, url, addr, ms), x_reuse(url, addr, ref_ms, links), instant(pool_ms, mint_ms),
pair_times(pairs_json_entry) -> (mint ms, pool ms), flag(name, S, W), apply_changes(W, changes), blank_signals().
Stdlib only. memebot is imported read-only, and only by feed().

Winner patterns (compare, win_fit, win_score) are hindsight and follow these rules:
  1. Labels never feed the green rule, a verdict, the points or a push; the win score only orders coins of equal points.
  2. Winners and losers are matched by the UTC hour of first sight; only hours with both count.
  3. Only first-sight signals (sig0) are used, so a coin that lived longer is not seen with more checks done. Unknown is not counted;
     older records without sig0 are not used.
  4. A signal is tested with 15+ winners and 15+ losers known and 5+ expected winners with and without it; else "too few".
  5. A pattern needs Benjamini-Hochberg q < 0.05 and the same direction in both halves of the hours; everything else could be chance.
  6. The per-coin why only describes, with counts, in hours with 2+ winners whose flag is known.
  7. The win order is learned only when it holds on the last 2 days (walk-forward).
"""
import copy, glob, gzip, json, math, os, random, re, sys, time
from operator import mul

HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_FILE = os.path.join(HERE, "radar_weights.json")
MIN = 60_000
H = 3_600_000
DAY = 86_400_000
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
INSIDER_NET = re.compile(r"insider network of (\d+) wallets", re.I)               # the study's bubble-map reading (build.py)
TWEET_LINK = re.compile(r"^https://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,30}/status/\d{5,25}")   # memebot.TWEET_LINK
# outcome constants of the study (build.py G1-G4)
DEAD_LIQ, REAL_LIQ, RUG_X, WIN_X, AMM_MIN, AMM_MAX, PEAK_MAX = 1_000.0, 5_000.0, 0.10, 2.0, 0.5, 1.5, 30.0
XUSES_MAX = 8               # earliest coins kept per X link in xlinks.json.gz
XLINK_KEEP_MS = 30 * DAY
WALLET_MAX_AGE_H = 3.0      # older wallet memory: the check counts as not done (no greens); radar_weights.json thresholds.wmMaxAgeH wins
WALLET_MIN_COINS = 500      # a memory built from fewer scored coins is "too small" (thresholds.wmMinCoins wins)
MINT_SKEW_S = 120           # a pool up to this long "before" its mint is clock skew on a same-slot launch (thresholds.mintSkewS wins)
TIME_MIN_MS = 1e12          # a time at or below this (2001) is a zero or a seconds value, never a real launch time
FEED_DAYS = 14              # feed reads the scored snapshots of the newest 14 days (the study had 8): a flat run time as the cache grows
CHATTY_REPLIES = 1          # pump.fun replies that make a coin "chatty" (measured only; thresholds.chattyReplies wins). Any reply at all:
                            # in the scan's snapshots of 6-15 Oct, 12 of 17,347 coins under 1 h old had one (1 to 34), so a higher bar
                            # would leave the radar's own records too few coins with it to ever test
VIRAL_LIKES = 1000          # likes of the tweet a coin launched off that make it "viral_tweet" (measured only; thresholds.viralLikes wins):
                            # the 306 source tweets the scan read for coins under 1 h old had 22 likes at the median, 944 at the 90th
                            # percentile; 31 had 1,000 or more (the 'viral real story' launch, still enough coins to be tested)

S_KEYS = ("instantPool", "mintToPoolS", "swAvg", "rugHolders", "wmChecked", "wmState",
          "brand", "buys", "rcReport", "rcDanger", "rcWarn", "cluster", "netSize",
          "creatorSold", "m5", "socN", "ageMin", "x", "xKind", "paid", "tweet", "lists",
          "stair", "mc", "liq", "creatorPct", "pumpswap",
          "devN", "devDead", "devGrad", "devAgeH", "devTxs", "xUsed", "tweetShared", "snip30", "snip30N", "slotN", "slotPct",
          "freshN", "freshOf", "fundN", "fundMin", "replies", "tweetLikes")
GOOD_SIGNS = ("x_and_paid", "tweet", "lists3")
CHECKS = ("rc_report", "instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "no_socials", "holder_cluster",
          "creator_sold", "pumping_5m", "staircase10")


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def blank_signals():
    return {k: None for k in S_KEYS}


def _count(v):
    """A count (replies, likes) as a number, or None: a negative, non-finite or yes/no value is no reading, never 0."""
    x = num(v) if not isinstance(v, bool) else None
    return x if x is not None and x >= 0 else None


# ---------------------------------------------------------------- weights
_W_CACHE = {}
_RE_CACHE = {}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def apply_changes(W, changes):
    """The prior W plus a fit's allowed changes: a measured signal becomes soft (1..maxPoints points, counts in maxSoft); a V soft
    signal goes to 0. Hard signals are never added or removed here; anything else in `changes` is ignored."""
    W2 = copy.deepcopy(W)
    mx = int((W.get("fit") or {}).get("maxPoints", 2))
    changes = changes if isinstance(changes, dict) else {}
    soft_add = changes.get("soft") if isinstance(changes.get("soft"), dict) else {}
    for name in sorted(soft_add):
        p = num(soft_add[name])
        if name in W.get("measured", ()) and name not in W2["soft"] and name not in W2["hard"] and p is not None and 1 <= p <= mx:
            W2["soft"].append(name)
            W2["points"][name] = int(p)
    for name in changes.get("zero") or []:
        if name in W.get("soft", ()) and name not in W.get("measured", ()) and name not in W["hard"]:
            W2["soft"] = [s for s in W2["soft"] if s != name]
            W2["points"][name] = 0
    return W2


def load_weights(path=None, model=None):
    """radar_weights.json (the study prior), then the changes of a learned model.json (a path or the dict) when its "from" is
    "learned" and it was fitted on this same prior. The default prior is cached: treat the returned dict as read-only."""
    path = path or WEIGHTS_FILE
    try:
        key = (os.path.abspath(path), os.path.getmtime(path))
    except OSError:
        key = None
    W = _W_CACHE.get(key) if key else None
    if W is None:
        W = _read_json(path)
        if not isinstance(W, dict) or W.get("v") != 1 or not isinstance(W.get("points"), dict):
            raise ValueError("radar_weights.json: not a v1 weights file")
        W["model"] = {"from": "prior"}
        if key:
            _W_CACHE.clear()
            _W_CACHE[key] = W
    if model is None:
        return W
    m = model
    if isinstance(m, str):
        try:
            m = _read_json(m)
        except (OSError, ValueError):
            m = None
    if not isinstance(m, dict) or m.get("from") != "learned" or m.get("prior") != W.get("src") or not isinstance(m.get("changes"), dict):
        return W
    W2 = apply_changes(W, m["changes"])
    W2["model"] = {"from": "learned", "n": m.get("n"), "auc": m.get("auc"), "aucPrior": m.get("aucPrior"), "at": m.get("at")}
    return W2


def brand_re(W=None):
    pat = (W or load_weights())["brand"]
    r = _RE_CACHE.get(pat)
    if r is None:
        r = _RE_CACHE[pat] = re.compile(pat, re.I)
    return r


# ---------------------------------------------------------------- X links
_X_HOST = re.compile(r"^(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com(/[^?#]*)?(?:[?#].*)?$", re.I)
_X_RESERVED = {"home", "search", "explore", "hashtag", "intent", "share", "messages", "notifications", "settings", "login", "signup",
               "tos", "privacy", "compose", "i"}


def norm_x(url):
    """An X (Twitter) link -> (kind, key): a tweet (any handle, /status/<id>) -> ("tweet", "x.com/i/status/<id>"); a community ->
    ("community", "x.com/i/communities/<id>"); an account -> ("account", "x.com/<handle>"). x.com and twitter.com, www and mobile,
    query, fragment and trailing slashes are ignored; the key is lower case. Anything else (searches, other sites) -> None."""
    u = str(url or "").strip()
    m = _X_HOST.match(u)
    if not m:
        return None
    parts = [p for p in (m.group(1) or "").split("/") if p]
    if not parts:
        return None
    low = [p.lower() for p in parts]
    if low[0] == "i":
        if len(low) >= 3 and low[1] == "communities" and low[2].isdigit():
            return ("community", "x.com/i/communities/" + low[2])
        if len(low) >= 3 and low[1] == "status" and low[2].isdigit():
            return ("tweet", "x.com/i/status/" + low[2])
        if len(low) >= 4 and low[1] == "web" and low[2] == "status" and low[3].isdigit():
            return ("tweet", "x.com/i/status/" + low[3])
        return None
    if low[0] in _X_RESERVED or not re.match(r"^[a-z0-9_]{1,30}$", low[0]):
        return None
    if len(low) >= 3 and low[1] == "status" and low[2].isdigit():
        return ("tweet", "x.com/i/status/" + low[2])
    if len(low) >= 2 and low[1] == "status":
        return None
    return ("account", "x.com/" + low[0])


def _uses(e):
    """The [[addr, ms], ...] of an xlinks entry, as a new list of well-formed pairs sorted by time (anything malformed is dropped).
    A single-coin entry is stored without its list: [addr, ms, 1, kind, last, []] reads as [[addr, ms]]."""
    if not isinstance(e, list) or len(e) < 6 or not isinstance(e[5], list):
        return []
    src = e[5] if e[5] else [[e[0], e[1]]]
    out = []
    for u in src:
        if isinstance(u, (list, tuple)) and len(u) == 2 and isinstance(u[0], str) and u[0] and num(u[1]) is not None:
            out.append([u[0], int(num(u[1]))])
    out.sort(key=lambda u: (u[1], u[0]))
    return out


def xlinks_add(links, url, addr, ms):
    """Index one coin's X link: links[key] = [first addr, first ms, n, kind, last ms, [[addr, ms], ...earliest XUSES_MAX]] (the file
    stores a one-coin entry with an empty list). A coin already indexed keeps its earliest time. n counts the coins that ever entered
    the kept list, so it is at least the list's length and stays put when the same coins are added again every hour; XUSES_MAX or more
    reads as "8+". A malformed entry is rebuilt. Returns the key, or None for a link that is not an X link."""
    nk = norm_x(url)
    ms = num(ms)
    if not nk or not isinstance(addr, str) or not addr or ms is None or not isinstance(links, dict):
        return None
    kind, key = nk
    ms = int(ms)
    e = links.get(key)
    uses = _uses(e)
    n = int(num(e[2]) or 0) if uses and isinstance(e, list) and len(e) >= 3 else 0
    last = int(num(e[4]) or ms) if uses and len(e) >= 5 else ms
    for u in uses:
        if u[0] == addr:
            u[1] = min(u[1], ms)
            break
    else:
        if len(uses) < XUSES_MAX or ms < uses[-1][1]:
            uses.append([addr, ms])
            n += 1
    uses.sort(key=lambda u: (u[1], u[0]))
    del uses[XUSES_MAX:]
    links[key] = [uses[0][0], uses[0][1], max(n, len(uses)), kind, max(last, ms), uses]
    return key


def x_reuse(url, addr, ref_ms, links, gap_s=600):
    """How the coin's X link was used before: {"kind","key","used","shared"}. used = older coins (created at least gap_s before
    this coin, never the coin itself) with the same account or community link; a tweet link counts in shared instead (other coins
    off the same tweet: in our data that is a good sign, not a clone). The index stores each coin's creation time (its mint, else
    its pool), so the coin's own time is the earlier of ref_ms (its mint when known, else its first sighting) and its own entry in
    the index. At most XUSES_MAX coins are kept per link."""
    nk = norm_x(url)
    out = {"kind": nk[0] if nk else None, "key": nk[1] if nk else None, "used": None, "shared": None}
    if not nk:
        return out
    uses = _uses((links or {}).get(nk[1]) if isinstance(links, dict) else None)
    if nk[0] == "tweet":
        out["used"], out["shared"] = 0, sum(1 for u in uses if u[0] != addr)
        return out
    refs = [u[1] for u in uses if u[0] == addr]
    if num(ref_ms) is not None:
        refs.append(num(ref_ms))
    if not refs:
        return out
    ref = min(refs)
    out["used"] = sum(1 for u in uses if u[0] != addr and u[1] <= ref - gap_s * 1000)
    out["shared"] = 0
    return out


# ---------------------------------------------------------------- chart shape
def staircase(closes, n_min=10, th=None):
    """The 'staircase chart' (nexus_trades; study staircase.py) on the minute candles from pool open: rise = last close / first
    close - 1, green = share of candles closing above their open (or above the previous close when only closes are given),
    pull = deepest fall from a running high. stair = at least n_min candles, rise >= 20%, green >= 70%, pull < 5%.
    closes: numbers, or candles [t, o, h, l, c, ...]."""
    th = th or {"rise": 0.2, "green": 0.7, "pull": 0.05}
    vals = []
    for x in closes if isinstance(closes, (list, tuple)) else []:
        if isinstance(x, (list, tuple)) and len(x) >= 5:
            o, c = num(x[1]), num(x[4])
        else:
            o, c = None, num(x)
        if c is not None and c > 0:
            vals.append((o if o and o > 0 else None, c))
    n = len(vals)
    if n < 2:
        return {"n": n, "rise": None, "green": None, "pull": None, "stair": False}
    cl = [c for _, c in vals]
    g = d = 0
    for i, (o, c) in enumerate(vals):
        ref = o if o is not None else (cl[i - 1] if i else None)
        if ref is None:
            continue
        d += 1
        g += 1 if c > ref else 0
    runmax, pull = cl[0], 0.0
    for x in cl:
        runmax = max(runmax, x)
        pull = max(pull, 1 - x / runmax)
    rise = cl[-1] / cl[0] - 1
    green = g / d if d else 0.0
    stair = n >= n_min and rise >= th["rise"] and green >= th["green"] and pull < th["pull"]
    return {"n": n, "rise": round(rise, 4), "green": round(green, 4), "pull": round(pull, 4), "stair": bool(stair)}


def _stair_shape(st, th):
    s = th["stair"]
    return (isinstance(st, dict) and num(st.get("rise")) is not None and num(st.get("green")) is not None and num(st.get("pull")) is not None
            and st["rise"] >= s["rise"] and st["green"] >= s["green"] and st["pull"] < s["pull"])


# ---------------------------------------------------------------- wallet memory
_WM_SETS = {"id": None, "sig": None, "sets": None}


def _wm_sets(wm):
    common, rug = wm.get("common"), wm.get("rug")
    sig = (len(common) if isinstance(common, list) else -1, len(rug) if isinstance(rug, list) else -1, str(wm.get("t")))
    if _WM_SETS["id"] != id(wm) or _WM_SETS["sig"] != sig:
        as_set = lambda xs: {w for w in xs if isinstance(w, str)} if isinstance(xs, list) else set()
        _WM_SETS.update(id=id(wm), sig=sig, sets=(as_set(common), as_set(rug)))
    return _WM_SETS["sets"]


def walletmem_lookup(holders, wm, now=None, W=None):
    """The wallet memory (walletmem.json.gz, from the scan's scored snapshots) against a coin's top holders.
    swAvg: the mean past result per 20 of the holders that have a record (memebot's sw.avg, all holders, wallets with 2+ coins).
    rugHolders: holders, minus the common program accounts, that were top holders of a coin that went to zero (the study's
    'holders in earlier rugs'). checked: the memory is there, built from at least thresholds.wmMinCoins scored coins, not older
    than thresholds.wmMaxAgeH at `now`, and the coin has top holders. Without `now` the memory's age cannot be told, so it is not
    checked (state old): unknown is never clean. The radar's signals_radar passes the cycle's clock, the page's signals_scan
    recommend.json's "t". A memory that is not checked still raises its red flags (fewer red flags, never a false green).
    state: ok | old | small | empty | missing | noholders."""
    out = {"swAvg": None, "rugHolders": None, "checked": False, "state": "missing"}
    if not isinstance(wm, dict) or wm.get("v") != 1 or not isinstance(wm.get("rug"), list):
        return out
    hs, seen = [], set()
    for h in holders if isinstance(holders, (list, tuple)) else []:
        if isinstance(h, str) and h and h not in seen:
            seen.add(h)
            hs.append(h)
    if not hs:
        out["state"] = "noholders"
        return out
    th = (W or load_weights())["thresholds"]
    common, rug = _wm_sets(wm)
    sw = wm.get("sw") if isinstance(wm.get("sw"), dict) else {}
    known = [num(sw[w]) for w in hs if w in sw and num(sw[w]) is not None]
    out["swAvg"] = round(sum(known) / len(known), 3) if known else None
    out["rugHolders"] = sum(1 for w in hs if w in rug and w not in common)
    t, now, n = num(wm.get("t")), num(now), num(wm.get("nCoins"))
    max_age = (num(th.get("wmMaxAgeH")) or WALLET_MAX_AGE_H) * H
    min_coins = num(th.get("wmMinCoins")) or WALLET_MIN_COINS
    if now is None or t is None or now - t > max_age:
        out["state"] = "old"                         # too old, or its age cannot be told (no clock, no time in the file)
    elif not n:
        out["state"] = "empty"                       # built from no coin at all: it checks nothing
    elif n < min_coins:
        out["state"] = "small"                       # refilling after a lost cache: most rugger wallets are not in it yet
    else:
        out["state"], out["checked"] = "ok", True
    return out


# ---------------------------------------------------------------- RugCheck
def rc_summary(rep):
    """A RugCheck report (raw /report JSON, as fetch.rc_row reads it) or a stored summary (memebot.risk_doc) -> {"danger","warn",
    "holders","creatorPct","net"}; None when there is no report. A raw report needs its "risks" or "topHolders" list, a summary its
    "danger" or "warn" list: an error answer ({"error": ...}) or an empty shell is no report. A report without its danger list gives
    danger None (the danger check is then not done, never passed). Names are cut to 60 characters like memebot.names; a raw
    report's insider graph over 50 wallets adds the warning "insider network of N wallets" exactly as fetch.rc_row does. holders:
    the top holders' owners, up to 40 (a raw report lists about 20; the study's lists were RugCheck's top 12 plus GMGN's top buyers,
    up to 40; the first 12 are exactly fetch.rc_row's)."""
    if not isinstance(rep, dict):
        return None
    lst = lambda k: rep.get(k) if isinstance(rep.get(k), list) else None
    clean = lambda v: re.sub(r"[|\r\n;]", " ", str(v or "")).strip()[:60]
    if lst("risks") is not None or lst("topHolders") is not None:
        risks = [r for r in (lst("risks") or []) if isinstance(r, dict)]
        lvl = lambda r: str(r.get("level") or "").lower()
        danger = [clean(r.get("name")) for r in risks if lvl(r) == "danger" and clean(r.get("name"))] if lst("risks") is not None else None
        warn = [clean(r.get("name")) for r in risks if lvl(r) == "warn" and clean(r.get("name"))]
        net = num(rep.get("graphInsidersDetected"))
        if net and net > 50:
            warn.append("insider network of %d wallets" % int(net))
        holders = []
        for h in lst("topHolders") or []:
            if isinstance(h, dict):
                a = str(h.get("owner") or h.get("address") or "").strip()
                if B58.match(a) and a not in holders:
                    holders.append(a)
        supply = num(rep["token"].get("supply")) if isinstance(rep.get("token"), dict) else None
        cb = num(rep.get("creatorBalance"))
        cpct = (cb / supply * 100) if supply and cb is not None else None
        sizes = [num(n.get("size")) for n in (lst("insiderNetworks") or []) if isinstance(n, dict) and num(n.get("size")) is not None]
        return {"danger": danger, "warn": warn, "holders": holders[:40], "creatorPct": cpct, "net": max(sizes) if sizes else None}
    if lst("danger") is None and lst("warn") is None:
        return None
    names = lambda k: [str(x.get("name") if isinstance(x, dict) else x)[:60] for x in lst(k) or [] if x]
    hs = [h for h in (lst("holders") or []) if isinstance(h, str) and h]
    return {"danger": names("danger") if lst("danger") is not None else None, "warn": names("warn"), "holders": hs[:40],
            "creatorPct": num(rep.get("creatorPct")), "net": None}


def _rc_into(S, s):
    if s is None:
        S["rcReport"], S["rcDanger"], S["rcWarn"], S["cluster"], S["netSize"] = False, None, None, None, None
        return
    S["rcReport"] = True
    S["rcDanger"] = list(s["danger"]) if isinstance(s.get("danger"), list) else None
    S["rcWarn"] = list(s["warn"]) if isinstance(s.get("warn"), list) else []
    low = [x.lower() for x in (S["rcDanger"] or []) + S["rcWarn"]]
    sizes = [int(m.group(1)) for x in low for m in [INSIDER_NET.search(x)] if m]
    S["cluster"] = bool(sizes) or any("holder correlation" in x for x in low)      # the study's flag: what RugCheck warned about
    if s.get("net"):
        sizes.append(int(s["net"]))                                                  # a raw report's network size, for the text only
    S["netSize"] = max(sizes) if sizes else None


def parse_ms(v):
    """Milliseconds from a number (ms or s) or an ISO date (memebot.parse_ms, copied so the page and the radar need no memebot). An
    ISO date without a zone is read as UTC (the runners' zone), so the result never depends on the machine's time zone."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    x = num(v)
    if x is not None:
        return x * 1000 if x < 1e11 else x
    try:
        import datetime as _dt
        d = _dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp() * 1000
    except (ValueError, TypeError, OverflowError):
        return None


def _real_ms(v):
    x = num(v)
    return x if x is not None and x > TIME_MIN_MS else None


def pair_times(pr):
    """(mint ms, pool ms) of one mb/pairs.json entry: the mint from pump.fun (pf.createdAt) or LaunchLab (ll.createdAt), the pool
    from DexScreener (pairCreatedAt). Either is None when unknown (a zero or a time before 2001 is unknown)."""
    pr = pr if isinstance(pr, dict) else {}
    mint = _real_ms(parse_ms(pr["pf"].get("createdAt"))) if isinstance(pr.get("pf"), dict) else None
    if mint is None and isinstance(pr.get("ll"), dict):
        mint = _real_ms(parse_ms(pr["ll"].get("createdAt")))
    return mint, _real_ms(pr.get("pairCreatedAt"))


def _gap(pool_ms, mint_ms, W):
    """(seconds from mint to pool, instant) or (None, None) when it cannot be told. A pool cannot open before its mint: a gap a little
    under 0 (up to thresholds.mintSkewS) is two clocks on a launch in the same slot, so it is instant (the study: 351 of 397 instant
    pools have a gap of exactly 0 s). A pool further "before" its mint, or a time that is no real launch time, is unknown, never
    "not instant"."""
    p, m = _real_ms(pool_ms), _real_ms(mint_ms)
    if p is None or m is None:
        return None, None
    th = W["thresholds"]
    s = (p - m) / 1000.0
    if s < -(num(th.get("mintSkewS")) or MINT_SKEW_S):
        return None, None
    return s, s < th["instantPoolS"]


def instant(pool_ms, mint_ms, W=None):
    """Pool opened within 60 s of the mint -> True; later -> False; unknown -> None (the study's instantPool: gap < 60 s; a small
    negative gap is clock skew and counts as instant, a large one is unknown)."""
    return _gap(pool_ms, mint_ms, W or load_weights())[1]


# ---------------------------------------------------------------- signals
def _brand(sym, name, W):
    if not sym and not name:
        return None
    return bool(brand_re(W).search("%s %s" % (sym or "", name or "")))


def _mint_pool(S, pool, mint, W):
    gap, inst = _gap(pool, mint, W)
    if gap is not None:
        S["mintToPoolS"] = round(gap, 1)
        S["instantPool"] = bool(inst)                     # on the exact gap, as the study (not the rounded one)


def _wm_into(S, holders, wm, now, W):
    lk = walletmem_lookup(holders, wm, now, W)
    S["rugHolders"], S["wmChecked"], S["wmState"] = lk["rugHolders"], lk["checked"], lk["state"]
    if S.get("swAvg") is None:
        S["swAvg"] = lk["swAvg"]


def signals_scan(y, pr_mint_ms, wm, now=None, pool=None, W=None):
    """S for one recommend.json young row (memebot rec() + ageMin): y["f"] carries the scan's factors (sw.avg, socN, buys1, m5,
    x, ds.paid, vt.tweet, srcN, dev.sold, ageH), y["risk"] the RugCheck summary with its top holders. pr_mint_ms: the mint time
    from mb/pairs.json (pf.createdAt or ll.createdAt) or None, or the coin's whole mb/pairs.json entry (then its pairCreatedAt is
    the pool time too). The pool's open time is `pool`, else the pairs.json entry's, else y["pool"], else now (recommend.json "t")
    minus the row's age. now (recommend.json "t") also dates the wallet memory (without it the memory counts as not checked).
    Without a mint time and a pool time (or `now` to place the pool) the row cannot be green. The page's call:
    signals_scan(row, pairs_by_addr.get(row["addr"]), walletmem, now=recommend["t"])."""
    W = W or load_weights()
    y = y if isinstance(y, dict) else {}
    if isinstance(pr_mint_ms, dict):
        pr_mint_ms, pr_pool = pair_times(pr_mint_ms)
        pool = pool if pool is not None else pr_pool
    f = y.get("f") if isinstance(y.get("f"), dict) else {}
    risk = y.get("risk") if isinstance(y.get("risk"), dict) else None
    S = blank_signals()
    g = lambda k: num(f.get(k))
    age_h = g("ageH")
    S["ageMin"] = round(60 * age_h, 2) if age_h is not None else num(y.get("ageMin"))
    pool = num(pool) if pool is not None else num(y.get("pool"))
    if pool is None and now is not None and age_h is not None:
        pool = num(now) - age_h * H
    _mint_pool(S, pool, pr_mint_ms, W)
    s = rc_summary(risk)
    _rc_into(S, s)
    S["swAvg"] = g("sw.avg")
    _wm_into(S, (s or {}).get("holders") or [], wm, num(now) if now is not None else None, W)
    S["brand"] = _brand(y.get("sym"), y.get("name"), W)
    S["buys"], S["m5"], S["socN"], S["lists"] = g("buys1"), g("m5"), g("socN"), g("srcN")
    sold = g("dev.sold")
    if sold is None and risk and isinstance(risk.get("dev"), dict) and risk["dev"].get("devSold") is not None:
        sold = 1.0 if risk["dev"].get("devSold") else 0.0
    S["creatorSold"] = None if sold is None else sold > 0
    x = y.get("x")
    S["x"] = (str(x) if x else "") if "x" in y else ("" if g("x") == 0 else (True if g("x") else None))
    S["xKind"] = (norm_x(S["x"]) or (None,))[0] if isinstance(S["x"], str) and S["x"] else None
    S["paid"] = None if g("ds.paid") is None else g("ds.paid") >= 1
    S["tweet"] = None if g("vt.tweet") is None else g("vt.tweet") >= 1
    S["replies"] = _count(g("pf.replies"))
    lk = _count(g("vt.likes"))                           # the scan stores log10(1 + likes)
    S["tweetLikes"] = float(round(10 ** min(lk, 12.0) - 1)) if lk is not None else None
    S["mc"], S["liq"] = num(y.get("mc")), num(y.get("liq"))
    S["creatorPct"] = (s or {}).get("creatorPct") if (s or {}).get("creatorPct") is not None else g("rc.creator")
    S["pumpswap"] = str(y.get("dex") or "").lower() == "pumpswap"
    return S


def signals_radar(c, W=None):
    """S for the radar's merged coin dict. Keys (all optional except now/addr; None = not known):
      now (the cycle's clock, ms), addr, sym, name, dex, pool (pairCreatedAt ms), mint (ms), first (first sight ms),
      px, liq, mc, m5 (DexScreener priceChange.m5), buys (txns.h1.buys so far), socN (DexScreener info socials), x (X url or ""),
      paid (DexScreener orders: paid profile), lists (how many sources found it),
      rc (raw RugCheck report, or a summary with danger/warn/holders, or None when there is none yet), holders (top holder
      owners, else taken from rc), wm (walletmem dict), devSold, creatorPct,
      dev {"n","dead","grad","ageH","txs"}, xUsed / tweetShared (else from xlinks: an xlinks.json.gz "links" dict; the coin's
      own time for "older coins" is its mint, else its own index entry or first sight),
      snip30, snip30N, slotN, slotPct, freshN, freshOf, fundN, fundMin, closes (minute closes or candles from pool open),
      replies (pump.fun's reply_count from a recent list reading), tweetLikes (the likes of the tweet the X link points at; only for a
      tweet link, None when it was not read). Both are measured only (chatty, viral_tweet): a failed reading is None, never 0."""
    W = W or load_weights()
    c = c if isinstance(c, dict) else {}
    S = blank_signals()
    now = num(c.get("now"))
    pool, mint = num(c.get("pool")), num(c.get("mint"))
    _mint_pool(S, pool, mint, W)
    S["ageMin"] = round((now - pool) / MIN, 2) if now is not None and pool is not None else None
    s = rc_summary(c.get("rc"))
    _rc_into(S, s)
    holders = c.get("holders") if isinstance(c.get("holders"), list) else (s or {}).get("holders") or []
    _wm_into(S, holders, c.get("wm"), now, W)
    S["brand"] = _brand(c.get("sym"), c.get("name"), W)
    for k in ("buys", "m5", "socN", "lists", "mc", "liq"):
        S[k] = num(c.get(k))
    S["creatorSold"] = None if c.get("devSold") is None else bool(c.get("devSold"))
    x = c.get("x")
    S["x"] = None if x is None else str(x or "")
    S["xKind"] = (norm_x(S["x"]) or (None,))[0] if S["x"] else None
    S["paid"] = None if c.get("paid") is None else bool(c.get("paid"))
    S["tweet"] = None if S["x"] is None else bool(TWEET_LINK.match(S["x"]))
    S["creatorPct"] = num(c.get("creatorPct")) if num(c.get("creatorPct")) is not None else (s or {}).get("creatorPct")
    S["pumpswap"] = str(c.get("dex") or "").lower() == "pumpswap"
    dev = c.get("dev") if isinstance(c.get("dev"), dict) else {}
    S["devN"], S["devDead"], S["devGrad"], S["devAgeH"], S["devTxs"] = (num(dev.get(k)) for k in ("n", "dead", "grad", "ageH", "txs"))
    if c.get("xUsed") is not None or c.get("tweetShared") is not None:
        S["xUsed"], S["tweetShared"] = num(c.get("xUsed")), num(c.get("tweetShared"))
    elif isinstance(c.get("xlinks"), dict) and S["x"]:
        ref = mint if _real_ms(mint) is not None else (num(c.get("first")) if num(c.get("first")) is not None else now)
        r = x_reuse(S["x"], c.get("addr"), ref, c["xlinks"], W["thresholds"].get("xGapS", 600))
        S["xUsed"], S["tweetShared"] = r["used"], r["shared"]
    for k in ("snip30", "snip30N", "slotN", "slotPct", "freshN", "freshOf", "fundN", "fundMin"):
        S[k] = num(c.get(k))
    S["replies"], S["tweetLikes"] = _count(c.get("replies")), _count(c.get("tweetLikes"))
    if c.get("closes"):
        st = staircase(c["closes"], n_min=W["thresholds"]["stair"]["n"], th=W["thresholds"]["stair"])
        S["stair"] = st if st["n"] >= 2 else None
    return S


# ---------------------------------------------------------------- rating
def _has_x(S):
    x = S.get("x")
    return bool(x) if x is not None else False


def flag(name, S, W=None):
    """One named signal on S -> True / False / None (cannot tell). Thresholds from W."""
    W = W or load_weights()
    th = W["thresholds"]
    g = lambda k: S.get(k)
    n = lambda k: num(S.get(k))
    if name == "instant_pool":
        if g("instantPool") is not None:
            return bool(g("instantPool"))
        m = n("mintToPoolS")
        if m is None or m < -(num(th.get("mintSkewS")) or MINT_SKEW_S):
            return None
        return m < th["instantPoolS"]
    if name == "rugger_wallets":
        sw, rh = n("swAvg"), n("rugHolders")
        if (sw is not None and sw <= th["swAvg"]) or (rh is not None and rh >= th["rugHolders"]):
            return True
        return False if g("wmChecked") is True else None
    if name == "brand_name":
        return None if g("brand") is None else bool(g("brand"))
    if name == "bot_volume":
        return None if n("buys") is None else n("buys") >= th["buys"]
    if name == "rc_danger":
        return bool(g("rcDanger")) if g("rcReport") is True and isinstance(g("rcDanger"), list) else None
    if name in ("staircase10", "staircase_early"):
        st = g("stair")
        k = num(st.get("n")) if isinstance(st, dict) else None
        if k is None:
            return None
        lo, hi = (th["stair"]["n"], 10 ** 9) if name == "staircase10" else (th.get("stairEarlyN", 6), th["stair"]["n"])
        if k < lo:
            return None
        return _stair_shape(st, th) if k < hi else None
    if name == "no_socials":
        return None if n("socN") is None else n("socN") <= 0
    if name == "holder_cluster":
        return bool(g("cluster")) if g("rcReport") is True and g("cluster") is not None else None
    if name == "creator_sold":
        return None if g("creatorSold") is None else bool(g("creatorSold"))
    if name == "pumping_5m":
        return None if n("m5") is None else n("m5") >= th["m5"]
    if name == "no_rc_report":
        return g("rcReport") is not True
    if name == "young_5m":
        return None if n("ageMin") is None else n("ageMin") < th["youngMin"]
    if name == "x_and_paid":
        return _has_x(S) and g("paid") is True
    if name == "tweet":
        return g("tweet") is True
    if name == "lists3":
        return (n("lists") or 0) >= th["lists"]
    if name == "x":
        return _has_x(S)
    if name == "creator_5pct":
        return None if n("creatorPct") is None else n("creatorPct") > th["creatorPct"]
    if name == "mc_500k":
        return None if n("mc") is None else n("mc") >= th["mc"]
    if name == "liq_15pct":
        if n("liq") is None or not n("mc"):
            return None
        return n("liq") / n("mc") < th["liqMc"] and not g("pumpswap")
    if name == "dev_dead":
        dn, dd = n("devN"), n("devDead")
        if dn is None or dd is None:
            return None
        return dn >= th["devDead"]["n"] and dd >= th["devDead"]["share"] * dn
    if name == "dev_young":
        a, t = n("devAgeH"), n("devTxs")
        if a is None and t is None:
            return None
        return (a is not None and a < th["devYoungH"]) or (t is not None and t < th["devYoungTxs"])
    if name == "x_copied":
        return None if n("xUsed") is None else n("xUsed") >= 1 and g("xKind") in ("account", "community")
    if name == "tweet_shared":
        return None if n("tweetShared") is None else n("tweetShared") >= 1
    if name == "sniped30":
        return None if n("snip30") is None else n("snip30") >= th["sniped30"]
    if name == "bundle_slot":
        return None if n("slotN") is None else n("slotN") >= th["bundleSlot"]
    if name == "fresh_holders":
        return None if n("freshN") is None else n("freshN") >= th["freshHolders"]
    if name == "fund_cluster":
        return None if n("fundN") is None else n("fundN") >= th["fundCluster"]
    if name == "chatty":
        return None if n("replies") is None else n("replies") >= (num(th.get("chattyReplies")) or CHATTY_REPLIES)
    if name == "viral_tweet":         # no tweet link at all is a plain no; a tweet whose likes were not read is unknown
        if n("tweetLikes") is not None:
            return n("tweetLikes") >= (num(th.get("viralLikes")) or VIRAL_LIKES)
        return False if g("tweet") is False else None
    raise KeyError("unknown signal " + name)


def rate(S, W=None):
    """The verdict. trap: any hard signal. good: no hard signal, a RugCheck report with its danger list, the mint time known, the
    wallet memory checked, every hard check that can apply decided (brand needs a name, bot volume the buy count), and at most
    maxSoft soft warnings. watch: everything else; `unknown` lists what blocked good (rc_report, mint_time, walletmem,
    brand_name, bot_volume, rc_danger). push = good, no pushBlock signal and nothing unknown. pts = max(sum of all points, sum
    of the hard points): good signs never cancel a hard trap. Measured (M) signals only show in `info` unless W promoted them to
    soft. n = the checks that ran (a missing RugCheck report is not counted)."""
    W = W or load_weights()
    S = S if isinstance(S, dict) else {}
    P = W["points"]
    hard = [h for h in W["hard"] if flag(h, S, W)]
    soft = [s for s in W["soft"] if flag(s, S, W)]
    unknown = []
    if S.get("rcReport") is not True:
        unknown.append("rc_report")
    if flag("instant_pool", S, W) is None:
        unknown.append("mint_time")
    if S.get("wmChecked") is not True and S.get("rcReport") is True:
        unknown.append("walletmem")
    for k in ("brand_name", "bot_volume", "rc_danger"):
        if flag(k, S, W) is None and (k != "rc_danger" or S.get("rcReport") is True):
            unknown.append(k)
    plus = [g for g in GOOD_SIGNS if flag(g, S, W)]
    info = [m for m in list(W.get("measured", ())) + list(W.get("infoOnly", ())) if m not in W["soft"] and flag(m, S, W)]
    hard_pts = sum(P.get(h, 0) for h in hard)
    total = hard_pts + sum(P.get(s, 0) for s in soft) + sum(P.get(g, 0) for g in plus)
    if flag("no_rc_report", S, W):
        total += P.get("no_rc_report", 0)
    if flag("young_5m", S, W):
        total += P.get("young_5m", 0)
    pts = max(total, hard_pts)
    upside = sum(v for k, v in W["upside"].items() if flag(k, S, W))
    verdict = "trap" if hard else ("good" if not unknown and len(soft) <= W["maxSoft"] else "watch")
    push = verdict == "good" and not unknown and not any(flag(b, S, W) for b in W.get("pushBlock", ()))
    done = sum(1 for k in CHECKS if (flag(k, S, W) is not None if k != "rc_report" else S.get("rcReport") is True))
    return {"verdict": verdict, "pts": int(pts), "upside": int(upside), "hard": hard, "soft": soft, "plus": plus, "info": info,
            "unknown": unknown, "push": bool(push), "n": done}


# ---------------------------------------------------------------- the trap-check line
def _ago(sec):
    if sec < 120:
        return "1 min"
    m = sec / 60.0
    if m < 120:
        return "%d min" % round(m)
    h = m / 60.0
    if h < 48:
        return "%d h" % round(h)
    return "%d days" % round(h / 24)


def _n(v):
    return int(round(num(v) or 0))


def _s(k, one, many):
    return one if k == 1 else many


def _text(name, S, W):
    th = W["thresholds"]
    n = lambda k: num(S.get(k))
    if name == "instant_pool":
        return "pool opened with the mint"
    if name == "rugger_wallets":
        rh = n("rugHolders")
        if rh is not None and rh >= th["rugHolders"]:
            return "%d holders from rugged coins" % _n(rh)
        return "top holders lost on past coins"
    if name == "brand_name":
        return "brand/celebrity name"
    if name == "bot_volume":
        return "3,000+ buys already"
    if name == "rc_danger":
        d = S.get("rcDanger") if isinstance(S.get("rcDanger"), list) else []
        return "RugCheck danger: %s" % (str(d[0])[:40] if d else "flag")
    if name == "staircase10":
        return "staircase chart"
    if name == "no_socials":
        return "no socials"
    if name == "holder_cluster":
        return "holder cluster (insider network of %d)" % _n(S["netSize"]) if n("netSize") else "holder cluster"
    if name == "creator_sold":
        return "creator sold"
    if name == "pumping_5m":
        return "+%d%% in 5 min" % _n(S.get("m5"))
    if name == "dev_dead":
        k = _n(S.get("devN"))
        return "dev: %d %s, %d dead" % (k, _s(k, "launch", "launches"), _n(S.get("devDead")))
    if name == "dev_young":
        a = n("devAgeH")
        if a is not None:
            return "dev wallet %s old" % _ago(a * 3600)
        k = _n(S.get("devTxs"))
        return "dev wallet: %d %s" % (k, _s(k, "transaction", "transactions"))
    if name == "x_copied":
        k = _n(S.get("xUsed"))
        return "X %s used by %d%s older %s" % ("community" if S.get("xKind") == "community" else "account", k, "+" if k >= XUSES_MAX else "",
                                               _s(k, "coin", "coins"))
    if name == "tweet_shared":
        k = _n(S.get("tweetShared")) + 1
        return "%s coins off the same tweet" % ("%d+" % XUSES_MAX if k >= XUSES_MAX else "%d" % k)
    if name == "sniped30":
        k = _n(S.get("snip30N"))
        return "%d%% sniped in 30 s" % round(100 * (n("snip30") or 0)) + (" (%d %s)" % (k, _s(k, "wallet", "wallets")) if n("snip30N") is not None else "")
    if name == "bundle_slot":
        k = _n(S.get("slotN"))
        return "%d %s in launch block" % (k, _s(k, "wallet", "wallets")) + (" (~%d%%)" % round(100 * n("slotPct")) if n("slotPct") is not None else "")
    if name == "fresh_holders":
        return "%d of %d top holders fresh" % (_n(S.get("freshN")), _n(S.get("freshOf")) or 10)
    if name == "fund_cluster":
        k = _n(S.get("fundN"))
        return "%d top holders funded by one wallet" % k + (" in %d min" % max(1, _n(S.get("fundMin"))) if n("fundMin") is not None else "")
    if name == "staircase_early":
        st = S.get("stair") if isinstance(S.get("stair"), dict) else {}
        return "staircase so far (%d min)" % _n(st.get("n"))
    if name == "chatty":
        k = _n(S.get("replies"))
        return "%d %s on pump.fun" % (k, _s(k, "reply", "replies"))
    if name == "viral_tweet":
        return "source tweet with {:,} likes".format(_n(S.get("tweetLikes")))
    return name.replace("_", " ")


UNKNOWN_TEXT = {"rc_report": "RugCheck pending", "mint_time": "mint time unknown", "brand_name": "name unknown", "bot_volume": "number of buys unknown",
                "rc_danger": "RugCheck danger list missing"}
WM_TEXT = {"noholders": "top holders unknown", "small": "wallet memory too small", "empty": "wallet memory too small"}


def chips(rating, S, W=None):
    """The trap-check line: [[level, text], ...], at most 8, in this order: bad (hard traps), warn (soft warnings), unk (not
    checked), ok (up to 3 passed key checks), info (grey measured signals, weight 0). Plain words, never advice."""
    W = W or load_weights()
    S = S if isinstance(S, dict) else {}
    rating = rating if isinstance(rating, dict) else rate(S, W)
    out = [["bad", _text(h, S, W)] for h in rating.get("hard") or []]
    out += [["warn", _text(s, S, W)] for s in rating.get("soft") or []]
    for u in rating.get("unknown") or []:
        if u == "walletmem":
            st = S.get("wmState")
            out.append(["unk", WM_TEXT.get(st, "wallet memory unavailable") if isinstance(st, str) else "wallet memory unavailable"])
        else:
            out.append(["unk", UNKNOWN_TEXT.get(u, u.replace("_", " ") + " unknown")])
    ok = []
    if flag("instant_pool", S, W) is False and num(S.get("mintToPoolS")) is not None and S["mintToPoolS"] >= 0:
        ok.append(["ok", "curve %s before pool" % _ago(S["mintToPoolS"])])
    if flag("rugger_wallets", S, W) is False:
        ok.append(["ok", "no rugger wallets"])
    if S.get("rcReport") is True and isinstance(S.get("rcDanger"), list) and not S["rcDanger"]:
        ok.append(["ok", "RugCheck report"])
    out += ok[:3]
    out += [["info", _text(m, S, W)] for m in rating.get("info") or []]
    return out[:8]


# ---------------------------------------------------------------- outcome (the study's G1-G4)
def _obs(px0, liq0, px1, liq1, gone):
    if gone:
        return 0.0, "gone"
    if not px0 or px1 is None:
        return None, None
    r = px1 / px0
    if liq1 is not None and liq1 < DEAD_LIQ:
        return r, "dead"                                     # G1: a dead pool is a rug, whatever the price says
    if r <= RUG_X:
        return r, "rug"
    if r >= WIN_X:
        if liq1 is None:
            return r, "up_noliq"
        lr = liq1 / liq0 if liq0 else None
        if liq1 >= REAL_LIQ and lr is not None and lr > AMM_MAX * math.sqrt(r):
            return r, "up_selfpriced"                        # G4: liquidity grew like the price itself
        if liq1 >= REAL_LIQ and lr is not None and lr >= AMM_MIN * math.sqrt(r) and r <= PEAK_MAX:
            return r, "up_real"                              # G2 consistent liquidity, G3 at most 30x
        return r, "up_fake"
    return r, "flat"


def outcome(rec):
    """A radar record's 1 h outcome from its later prices: rug1h = at the 60-minute price the pool was gone, under $1,000 of
    liquidity (G1) or at 0.1x or less; win1h = a confirmed peak60 of 2x-30x (not on a pool that was dead or gone at 60 min), or
    a 60-minute price of 2x-30x with $5k+ liquidity grown like a constant-product pool (G2, G3); never on a self-priced pool
    (G4: liquidity 90%+ of the market cap on a token that is neither a pump.fun mint nor on PumpSwap, or liquidity that grew
    like the price). x60 = the 60-minute price / the first price (0 when gone). Hindsight: feeds nothing but the record line."""
    none = {"rug1h": None, "win1h": None, "x60": None}
    if not isinstance(rec, dict):
        return none
    lat = (rec.get("later") or {}).get("60") if isinstance(rec.get("later"), dict) else None
    if not isinstance(lat, dict):
        return none
    px0, liq0, mc0 = num(rec.get("px")), num(rec.get("liq")), num(rec.get("mc"))
    r, st = _obs(px0, liq0, num(lat.get("px")), num(lat.get("liq")), bool(lat.get("gone")))
    if st is None:
        return none
    lm = (liq0 / mc0) if liq0 and mc0 else num((rec.get("sig") or {}).get("liqMc")) if isinstance(rec.get("sig"), dict) else None
    self_priced = st == "up_selfpriced" or (lm is not None and lm >= 0.9 and not str(rec.get("addr") or "").endswith("pump")
                                            and str(rec.get("dex") or "").lower() != "pumpswap")
    rug = st in ("gone", "dead", "rug")
    win = False
    if not self_priced:
        if st == "up_real":
            win = True
        pk = rec.get("peak60")
        x = num(pk.get("x")) if isinstance(pk, dict) else None
        if x is not None and WIN_X <= x <= PEAK_MAX and st not in ("gone", "dead"):
            win = True
    return {"rug1h": bool(rug), "win1h": bool(win), "x60": round(r, 4) if r is not None else None}


# ---------------------------------------------------------------- the radar model (fit)
def auc(scores, ys):
    """Mann-Whitney AUC, ties count half (the study's stats.auc)."""
    pairs = sorted(zip(scores, ys))
    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        rank_sum += (i + 1 + j) / 2.0 * sum(1 for t in range(i, j) if pairs[t][1])
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def _bh(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    q, prev = [0.0] * m, 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return q


def _pctl(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _weights_draws(nh, b, seed):
    rng = random.Random(seed)
    out = []
    for _ in range(b):
        m = [0] * nh
        for _ in range(nh):
            m[rng.randrange(nh)] += 1
        out.append(m)
    return out


def _lr(k1, n1, k0, n0):
    return math.log((k1 + 0.5) / (n1 + 1.0)) - math.log((k0 + 0.5) / (n0 + 1.0))


def _band_rate(rows, draws, hidx, pick):
    """Rug rate of the rows where pick(S) holds, with a 95% interval from the hour bootstrap."""
    nh = len(hidx)
    n, k = [0] * nh, [0] * nh
    for t, S, y in rows:
        if pick(S):
            h = hidx[t // H]
            n[h] += 1
            k[h] += 1 if y else 0
    N, K = sum(n), sum(k)
    if not N:
        return {"n": 0, "k": 0, "rate": None, "lo": None, "hi": None}
    rs = []
    for m in draws:
        bn = sum(map(mul, m, n))
        if bn:
            rs.append(sum(map(mul, m, k)) / bn)
    return {"n": N, "k": K, "rate": round(K / N, 4), "lo": round(_pctl(rs, 2.5), 4), "hi": round(_pctl(rs, 97.5), 4)}


def decide(row, cfg):
    """One tested signal's change (the study's rule): ("soft", points) for a measured signal whose rug-rate ratio is above 1 with
    95% confidence (interval low > 1), significant after Benjamini-Hochberg (q < cfg q) and above 1 in both time halves, points =
    clamp(round(2 ln ratio), 0, maxPoints), at least 1; ("zero", 0) for a V soft signal whose ratio is below 1 the same way
    (interval high < 1, q, both halves below 1); else ("none", 0)."""
    q, lo, hi, ratio, halves = num(row.get("q")), num(row.get("lo")), num(row.get("hi")), num(row.get("ratio")), row.get("halves") or []
    if q is None or q >= cfg["q"] or lo is None or hi is None or not ratio or len(halves) != 2:
        return "none", 0
    hv = [num(h) for h in halves]
    if row.get("kind") == "M" and lo > 1 and all(h is not None and h > 1 for h in hv):
        pts = max(0, min(int(cfg["maxPoints"]), int(round(2 * math.log(ratio)))))
        return ("soft", pts) if pts >= 1 else ("none", 0)
    if row.get("kind") == "V" and hi < 1 and all(h is not None and h < 1 for h in hv):
        return "zero", 0
    return "none", 0


def fit(records, W=None, now=None):
    """The radar model ("it trains itself"): on radar records with a known 1 h outcome, every measured signal and every V soft
    signal is tested the study's way (rug rate with vs without, 95% interval from a bootstrap that resamples whole hours,
    Benjamini-Hochberg, the same direction in both time halves). A measured signal that passes becomes soft (points =
    clamp(round(2 ln ratio), 0, 2)); a V soft signal that reverses significantly goes to 0; hard signals never change.
    The changes are decided on the records before the last 2 days and kept only if, on the last 2 days, the rug AUC is at least
    the prior's minus 0.01 and the good band's rug rate is not above the prior's interval. W must be the prior.
    A coin recorded twice (in two hour docs) counts once: its earliest record with an outcome.
    Returns (W2, report) or (None, report); the report is the radar's model.json."""
    W = W or load_weights()
    cfg = W["fit"]
    now = int(now if now is not None else time.time() * 1000)
    rows, by_addr = [], {}
    for r in records or []:
        if not isinstance(r, dict):
            continue
        o = r.get("out") if isinstance(r.get("out"), dict) else {}
        t = num(r.get("first")) if num(r.get("first")) is not None else num(r.get("t"))
        if o.get("rug1h") is None or t is None or not isinstance(r.get("sig"), dict):
            continue
        row = (int(t), r["sig"], bool(o["rug1h"]))
        a = r.get("addr")
        if isinstance(a, str) and a:
            if a not in by_addr or row[0] < by_addr[a][0]:
                by_addr[a] = row
        else:
            rows.append(row)
    rows += list(by_addr.values())
    rows.sort(key=lambda x: (x[0], bool(x[2])))
    rep = {"v": 1, "from": "prior", "n": len(rows), "need": cfg["minRecords"], "at": now, "prior": W.get("src"), "auc": None, "aucPrior": None,
           "nTrain": 0, "nTest": 0, "changes": {"soft": {}, "zero": []}, "signals": [], "why": ""}
    if len(rows) < cfg["minRecords"]:
        rep["why"] = "radar data %d of %d needed" % (len(rows), cfg["minRecords"])
        return None, rep
    cut = now - cfg["testDays"] * DAY
    train, test = [x for x in rows if x[0] < cut], [x for x in rows if x[0] >= cut]
    rep["nTrain"], rep["nTest"] = len(train), len(test)
    if len(train) < cfg["minTrain"] or len(test) < cfg["minTest"]:
        rep["why"] = "walk-forward needs %d calls before the last %d days and %d in them (have %d and %d)" % (
            cfg["minTrain"], cfg["testDays"], cfg["minTest"], len(train), len(test))
        return None, rep
    hours = sorted({t // H for t, _, _ in train})
    hidx = {h: i for i, h in enumerate(hours)}
    nh = len(hours)
    draws = _weights_draws(nh, cfg["boot"], cfg["seed"])
    mid = train[len(train) // 2][0]
    cands = [m for m in W.get("measured", ())] + [s for s in W["soft"] if s not in W.get("measured", ())]
    tested = []
    for name in cands:
        n1, k1, n0, k0 = [0] * nh, [0] * nh, [0] * nh, [0] * nh
        halves = [[0, 0, 0, 0], [0, 0, 0, 0]]
        for t, S, y in train:
            f = flag(name, S, W)
            if f is None:
                continue
            h = hidx[t // H]
            hv = halves[0 if t < mid else 1]
            if f:
                n1[h] += 1; k1[h] += 1 if y else 0; hv[0] += 1; hv[1] += 1 if y else 0
            else:
                n0[h] += 1; k0[h] += 1 if y else 0; hv[2] += 1; hv[3] += 1 if y else 0
        N1, K1, N0, K0 = sum(n1), sum(k1), sum(n0), sum(k0)
        row = {"signal": name, "kind": "M" if name in W.get("measured", ()) else "V", "n1": N1, "r1": round(K1 / N1, 4) if N1 else None,
               "n0": N0, "r0": round(K0 / N0, 4) if N0 else None, "ratio": None, "lo": None, "hi": None, "p": None, "q": None,
               "halves": [None, None], "pts": 0, "action": "none"}
        rep["signals"].append(row)
        if N1 < cfg["minSide"] or N0 < cfg["minSide"]:
            row["action"] = "too rare"
            continue
        row["ratio"] = round(math.exp(_lr(K1, N1, K0, N0)), 4)
        row["halves"] = [round(math.exp(_lr(hv[1], hv[0], hv[3], hv[2])), 4) if hv[0] and hv[2] else None for hv in halves]
        lrs, ds = [], []
        for m in draws:
            bn1, bk1, bn0, bk0 = sum(map(mul, m, n1)), sum(map(mul, m, k1)), sum(map(mul, m, n0)), sum(map(mul, m, k0))
            if bn1 and bn0:
                lrs.append(_lr(bk1, bn1, bk0, bn0))
                ds.append(bk1 / bn1 - bk0 / bn0)
        if not ds:
            row["action"] = "too rare"
            continue
        row["lo"], row["hi"] = round(math.exp(_pctl(lrs, 2.5)), 4), round(math.exp(_pctl(lrs, 97.5)), 4)
        p = 2 * min(sum(1 for d in ds if d <= 0), sum(1 for d in ds if d >= 0)) / len(ds)
        row["p"] = max(min(1.0, p), 1.0 / len(ds))
        tested.append(row)
    for row, q in zip(tested, _bh([r["p"] for r in tested])):
        row["q"] = round(q, 4)
        act, pts = decide(row, cfg)
        if act == "soft":
            row["pts"], row["action"] = pts, "soft"
            rep["changes"]["soft"][row["signal"]] = pts
        elif act == "zero":
            row["action"] = "zero"
            rep["changes"]["zero"].append(row["signal"])
    W2 = apply_changes(W, rep["changes"])
    ys = [y for _, _, y in test]
    a_p = auc([rate(S, W)["pts"] for _, S, _ in test], ys)
    rep["aucPrior"] = round(a_p, 4) if a_p is not None else None
    if not rep["changes"]["soft"] and not rep["changes"]["zero"]:
        rep["auc"] = rep["aucPrior"]
        rep["why"] = "study prior kept: no signal passed the test on %d calls" % len(train)
        return None, rep
    a_n = auc([rate(S, W2)["pts"] for _, S, _ in test], ys)
    rep["auc"] = round(a_n, 4) if a_n is not None else None
    thours = sorted({t // H for t, _, _ in test})
    tidx = {h: i for i, h in enumerate(thours)}
    tdraws = _weights_draws(len(thours), cfg["boot"], cfg["seed"] + 1)
    g_p = _band_rate(test, tdraws, tidx, lambda S: rate(S, W)["verdict"] == "good")
    g_n = _band_rate(test, tdraws, tidx, lambda S: rate(S, W2)["verdict"] == "good")
    rep["good"] = {"prior": g_p, "learned": g_n}
    if a_p is None or a_n is None:
        rep["why"] = "study prior kept: the last %d days hold no rug or only rugs" % cfg["testDays"]
        return None, rep
    if a_n < a_p - cfg["aucSlack"]:
        rep["why"] = "study prior kept: walk-forward AUC %.2f vs %.2f" % (a_n, a_p)
        return None, rep
    if g_n["n"] and (not g_p["n"] or g_n["rate"] > g_p["hi"]):
        rep["why"] = "study prior kept: the good band rugged more (%s)" % (
            "%.0f%% vs %.0f%%" % (100 * g_n["rate"], 100 * g_p["rate"]) if g_p["n"] else "no prior good call to compare")
        return None, rep
    rep["from"] = "learned"
    rep["why"] = "learned on %d calls: AUC %.2f vs %.2f" % (len(train), a_n, a_p)
    W2["model"] = {"from": "learned", "n": len(rows), "auc": rep["auc"], "aucPrior": rep["aucPrior"], "at": now}
    return W2, rep


# ---------------------------------------------------------------- winners vs losers at first sight (hindsight only)
STUDY_DAYS = 14             # compare reads the labelled records of the newest 14 days
STUDY_MIN_WIN = 15          # a signal is tested with at least 15 winners and 15 losers whose flag is known ...
STUDY_MIN_LOSE = 15
STUDY_MIN_EXP = 5           # ... and at least 5 expected winners with the flag and 5 without
STUDY_Q = 0.05              # Benjamini-Hochberg q under which a signal (same direction in both halves) is a pattern
WHY_HOURS = 6               # the per-coin why: rugged top or green coins of the last 6 hours ...
WHY_MIN_WIN = 2             # ... in an hour with at least 2 winners, a flag counted with at least 2 of them known
WIN_TEST_DAYS = 2           # the win order is chosen before the last 2 days and tested on them
WIN_MIN_TRAIN = 150
WIN_MIN_TEST = 30           # winners and losers each in the test days
WIN_AUC_MIN = 0.55
WIN_MAX_SIGNALS = 5


def _self_priced(rec):
    """outcome()'s pool test on the first sight: liquidity 90%+ of the market cap on a token that is neither a pump.fun mint nor on
    PumpSwap (mostly Meteora: its price moves with its own liquidity)."""
    liq0, mc0 = num(rec.get("liq")), num(rec.get("mc"))
    return bool(liq0 and mc0 and liq0 / mc0 >= 0.9 and not str(rec.get("addr") or "").endswith("pump")
                and str(rec.get("dex") or "").lower() != "pumpswap")


def win_label(rec):
    """A record's class for the winner study: 0 = rugged within the hour (out.rug1h); 1 = no rug and a 15, 30 or 60-minute price of
    2x-30x with liquidity of $5k+ grown like a constant-product pool (_obs "up_real"); None = no outcome yet, neither, or a
    self-priced pool (left out of both classes). The same rule for every record: peak60, which only top or green records get, is
    not read."""
    o = rec.get("out") if isinstance(rec, dict) and isinstance(rec.get("out"), dict) else {}
    if not isinstance(o.get("rug1h"), bool) or _self_priced(rec):
        return None
    if o["rug1h"]:
        return 0
    later = rec.get("later") if isinstance(rec.get("later"), dict) else {}
    px0, liq0 = num(rec.get("px")), num(rec.get("liq"))
    for m in ("15", "30", "60"):
        lat = later.get(m)
        if isinstance(lat, dict) and not lat.get("gone") and _obs(px0, liq0, num(lat.get("px")), num(lat.get("liq")), False)[1] == "up_real":
            return 1
    return None


def _study_cands(W):
    out = []
    for k in list(W["hard"]) + list(W["soft"]) + list(W.get("measured", ())) + list(W.get("infoOnly", ())) + list(GOOD_SIGNS) \
            + list(W.get("upside") or {}) + ["young_5m", "no_rc_report"]:
        if k not in out:
            out.append(k)
    return out


def _study_rows(records, W, cands, now):
    """(rows, noSig0): per coin its earliest labelled record of the last STUDY_DAYS with first-sight signals (sig0), as
    (first ms, UTC hour, label, {signal: flag}, record); noSig0 = labelled coins without sig0 (older records: not used)."""
    by, nosig = {}, set()
    for r in records or []:
        if not isinstance(r, dict) or not isinstance(r.get("addr"), str):
            continue
        t, y = num(r.get("first")), win_label(r)
        if t is None or y is None or t < now - STUDY_DAYS * DAY:
            continue
        if not isinstance(r.get("sig0"), dict):
            nosig.add(r["addr"])
        elif r["addr"] not in by or t < by[r["addr"]][0]:
            by[r["addr"]] = (int(t), y, r)
    rows = [(t, t // H, y, {k: flag(k, r["sig0"], W) for k in cands}, r) for t, y, r in by.values()]
    rows.sort(key=lambda x: (x[0], x[4]["addr"]))
    return rows, len(nosig - set(by))


def _cmh(tabs):
    """Cochran-Mantel-Haenszel over hour tables [a, b, c, d] (winners with / without the flag, losers with / without); an hour
    counts only with a winner and a loser. -> [A, E, V, MH numerator, MH denominator, wk, wn, lk, ln]."""
    s = [0.0] * 5 + [0] * 4
    for a, b, c, d in tabs:
        n = a + b + c + d
        if not a + b or not c + d:
            continue
        s[0] += a
        s[1] += (a + b) * (a + c) / n
        s[2] += (a + b) * (c + d) * (a + c) * (b + d) / (n * n * (n - 1.0))
        s[3] += a * d / n
        s[4] += b * c / n
        s[5] += a
        s[6] += a + b
        s[7] += c
        s[8] += c + d
    return s


def _odds(nu, de):
    return float("%.3g" % (nu / de)) if nu and de else None


def _study(rows, cands, W):
    """The per-signal rows of compare on these rows (see compare) and the informative hours."""
    hw = {}
    for _, h, y, _, _ in rows:
        hw.setdefault(h, [0, 0])[y] += 1
    inf = sorted(h for h, (l, w) in hw.items() if l and w)
    mid = inf[len(inf) // 2] if inf else 0
    kinds = (("hard", W["hard"]), ("soft", W["soft"]), ("measured", W.get("measured", ())), ("info", W.get("infoOnly", ())),
             ("good", GOOD_SIGNS), ("upside", W.get("upside") or {}))
    out, sides = [], []
    side = lambda s: (s[3] > s[4]) - (s[3] < s[4])
    for name in cands:
        tab = {}
        for _, h, y, F, _ in rows:
            if F[name] is not None:
                tab.setdefault(h, [0, 0, 0, 0])[(0 if y else 2) + (0 if F[name] else 1)] += 1
        s = _cmh(tab.values())
        halves = [_cmh(t for h, t in tab.items() if (h < mid) == first) for first in (True, False)]
        A, E, V = s[0], s[1], s[2]
        ok = s[6] >= STUDY_MIN_WIN and s[8] >= STUDY_MIN_LOSE and E >= STUDY_MIN_EXP and s[6] - E >= STUDY_MIN_EXP and V > 0
        p = math.erfc(math.sqrt(max(0.0, abs(A - E) - 0.5) ** 2 / V / 2)) if ok else None
        out.append({"signal": name, "kind": next((k for k, xs in kinds if name in xs), "points"), "wk": s[5], "wn": s[6], "lk": s[7], "ln": s[8],
                    "or": _odds(s[3], s[4]), "dir": side(s), "p": p, "q": None, "halves": [_odds(x[3], x[4]) for x in halves], "verdict": "too few"})
        sides.append([side(x) for x in halves])
    tested = [(r, hs) for r, hs in zip(out, sides) if r["p"] is not None]
    for (r, hs), q in zip(tested, _bh([r["p"] for r, _ in tested])):
        r["q"] = q
        agree = r["dir"] != 0 and hs == [r["dir"], r["dir"]]
        r["verdict"] = "pattern" if q < STUDY_Q and agree else "hint" if r["p"] < 0.05 else "none"
    rank = {"pattern": 0, "hint": 1, "none": 2, "too few": 3}
    out.sort(key=lambda r: (rank[r["verdict"]], r["q"] if r["q"] is not None else 2.0, r["p"] if r["p"] is not None else 2.0, cands.index(r["signal"])))
    for r in out:
        r["p"], r["q"] = (float("%.3g" % r[k]) if r[k] is not None else None for k in ("p", "q"))
    return out, inf


def compare(records, W=None, now=None):
    """Winners vs losers at first sight (the radar's winner patterns; hindsight, never a verdict, points or a push). Rows: per coin
    its earliest record of the last STUDY_DAYS with sig0 and a win_label. Every signal of W (hard, soft, measured, info only, good
    signs, upside) plus young_5m and no_rc_report is compared within the UTC hour of first sight, over the hours with a winner and
    a loser whose flag is known (Cochran-Mantel-Haenszel chi-square with continuity correction, Mantel-Haenszel odds ratio). Tested
    only with STUDY_MIN_WIN winners and losers known and STUDY_MIN_EXP expected winners with and without the flag; then
    Benjamini-Hochberg over the tested ones. verdict: pattern (q < STUDY_Q, the same direction in both halves of the hours), hint
    (p < 0.05, could be chance), none, too few. Report: {at, since, n, w, l, hrs, noSig0, need, rows: [{signal, kind, wk, wn, lk,
    ln, or, dir, p, q, halves, verdict}], coins: the per-coin why [sym, first, winners that hour, [[signal, winners with it, winners
    known]]]: the rugged top or green coins of the last WHY_HOURS in hours with WHY_MIN_WIN+ winners, and their flags that at most a
    third of that hour's winners whose flag is known had (WHY_MIN_WIN+ known; by p, at most 3), newest first, at most 20}."""
    W = W or load_weights()
    now = int(now if now is not None else time.time() * 1000)
    cands = _study_cands(W)
    rows, nosig = _study_rows(records, W, cands, now)
    out, inf = _study(rows, cands, W)
    keep = set(inf)
    pkey = {r["signal"]: (r["p"] if r["p"] is not None else 2.0, cands.index(r["signal"])) for r in out}
    wins = {}
    for _, h, y, F, _ in rows:
        if y:
            wins.setdefault(h, []).append(F)
    coins = []
    for t, h, y, F, rec in rows:
        ws = wins.get(h) or []
        if y or t < now - WHY_HOURS * H or not (rec.get("top") or rec.get("good")) or len(ws) < WHY_MIN_WIN:
            continue
        kn = {k: [G[k] for G in ws if G[k] is not None] for k in cands if F[k]}      # only the winners whose flag is known count
        rare = sorted((pkey[k], k, sum(v), len(v)) for k, v in kn.items() if len(v) >= WHY_MIN_WIN)
        rare = [[k, n, m] for _, k, n, m in rare if 3 * n <= m][:3]
        if rare:
            coins.append([str(rec.get("sym") or "?")[:24], t, len(ws), rare])
    coins.sort(key=lambda c: -c[1])
    return {"at": now, "since": rows[0][0] if rows else None, "n": len(rows), "w": sum(1 for x in rows if x[2] and x[1] in keep),
            "l": sum(1 for x in rows if not x[2] and x[1] in keep), "hrs": len(inf), "noSig0": nosig, "need": STUDY_MIN_WIN, "rows": out, "coins": coins[:20]}


def _hm_se(a, n1, n0):
    """Hanley-McNeil standard error of an AUC with n1 positives and n0 negatives."""
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    return math.sqrt(max(0.0, a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0))


def win_fit(records, W=None, now=None):
    """The learned win order, walk-forward: compare on the rows before the last WIN_TEST_DAYS; each pattern signal gets +1 (winners
    had it more) or -1, at most WIN_MAX_SIGNALS by q; the order is kept only if on the last WIN_TEST_DAYS (at least WIN_MIN_TEST
    winners and losers) the AUC of win_score is at least WIN_AUC_MIN and its Hanley-McNeil 95% low end is above 0.5. Needs
    WIN_MIN_TRAIN rows before. -> (wmodel {w, src, auc, at} | None, report {from: learned | none, at, src, w, n, auc, aucLo,
    nTrain, nTest, wTest, lTest, why})."""
    W = W or load_weights()
    now = int(now if now is not None else time.time() * 1000)
    cands = _study_cands(W)
    rows, _ = _study_rows(records, W, cands, now)
    cut = now - WIN_TEST_DAYS * DAY
    train, test = [x for x in rows if x[0] < cut], [x for x in rows if x[0] >= cut]
    wt = sum(1 for x in test if x[2])
    rep = {"from": "none", "at": now, "src": W.get("src"), "w": {}, "n": len(rows), "auc": None, "aucLo": None, "nTrain": len(train),
           "nTest": len(test), "wTest": wt, "lTest": len(test) - wt, "why": ""}
    if len(train) < WIN_MIN_TRAIN:
        rep["why"] = "walk-forward needs %d coins before the last %d days (have %d)" % (WIN_MIN_TRAIN, WIN_TEST_DAYS, len(train))
        return None, rep
    for k, n in (("doubled", wt), ("rugged", len(test) - wt)):
        if n < WIN_MIN_TEST:
            rep["why"] = "walk-forward needs %d %s coins in the last %d days (have %d)" % (WIN_MIN_TEST, k, WIN_TEST_DAYS, n)
            return None, rep
    pats = [r for r in _study(train, cands, W)[0] if r["verdict"] == "pattern"][:WIN_MAX_SIGNALS]
    rep["w"] = w = {r["signal"]: 1 if r["dir"] > 0 else -1 for r in pats}
    if not w:
        rep["why"] = "no pattern in %d coins before the last %d days" % (len(train), WIN_TEST_DAYS)
        return None, rep
    a = auc([sum(v for k, v in w.items() if F[k]) for _, _, _, F, _ in test], [y for _, _, y, _, _ in test])
    lo = a - 1.96 * _hm_se(a, wt, len(test) - wt)
    rep["auc"], rep["aucLo"] = round(a, 4), round(lo, 4)
    if a < WIN_AUC_MIN or lo <= 0.5:
        rep["why"] = "walk-forward AUC %.2f (low %.2f) on %d coins: not learned" % (a, lo, len(test))
        return None, rep
    rep["from"] = "learned"
    rep["why"] = "learned on %d coins: AUC %.2f (low %.2f) on %d later coins" % (len(train), a, lo, len(test))
    return {"w": dict(w), "src": W.get("src"), "auc": rep["auc"], "at": now}, rep


def win_score(S, wmodel, W=None):
    """The learned win order's score of one coin's signals: the sum of the weights (+1 / -1) of the signals that are true, -5..5; None
    without a learned order (wmodel is win_fit's model or its "w"). W is only read for the thresholds: its points, lists and
    thresholds are never changed, so a verdict, the points and a push are the same with or without a win order."""
    w = wmodel.get("w") if isinstance(wmodel, dict) and isinstance(wmodel.get("w"), dict) else wmodel
    if not isinstance(w, dict) or not w:
        return None
    W = W or load_weights()
    S = S if isinstance(S, dict) else {}
    s = 0
    for k, v in w.items():
        try:
            s += int(num(v)) if num(v) in (1.0, -1.0) and flag(k, S, W) else 0
        except KeyError:
            continue                                         # a signal this traps.py no longer knows
    return max(-WIN_MAX_SIGNALS, min(WIN_MAX_SIGNALS, s))


# ---------------------------------------------------------------- feed (runs in the scan job after sync; reads only <d>)
def _gz_write(path, obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    data = gzip.compress(raw, compresslevel=6, mtime=0)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def _gz_read(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return None


_NAME_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T")


def _name_ms(fn):
    """The day a scored-snapshot file was taken, from its name (<run id YYYY-MM-DDTHHMM>-<k>.json, UTC), or None."""
    m = _NAME_DAY.match(os.path.basename(fn))
    if not m:
        return None
    import datetime as _dt
    try:
        return _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_dt.timezone.utc).timestamp() * 1000
    except ValueError:
        return None


def _snap_holders(c):
    rc = c.get("rc")
    hs = rc.get("holders") if isinstance(rc, dict) else None
    return [h for h in hs if isinstance(h, str)] if isinstance(hs, list) else []


def feed(d, out, now, days=FEED_DAYS):
    """The radar's feed from the scan's own data (mb/), written to <out>:
      walletmem.json.gz {"v":1,"t","nCoins","common":[...],"sw":{wallet: avg},"rug":[wallets]}: the study's wallet memory (build.py)
        from the db/memesnapres snapshots taken in the last `days` days (by their t0; a file whose name says it is older is not
        even opened): common = top holder of more than max(20, 1% of the coins with holder lists); rug = top holders (minus
        common) of a coin that went to zero (gone or under 0.1x) with the result known at `now`; sw = memebot.wallet_table avg on
        the results known at `now`. The window keeps the run time flat while the snapshot cache grows (about 2 s a day of
        snapshots) and keeps the memory close to the 8 days the study calibrated on.
      xlinks.json.gz {"v":1,"t","links":{key: [addr, firstMs, n, kind, lastMs, [[addr, ms], ...]]}}: X links from pf/*.txt and
        pairs.json, merged with the previous <d>/xlinks.json.gz, links last used over 30 days ago dropped.
      symmc.json.gz {"v":1,"t","sym":{SYM: max market cap}}: the copy gate's table (memebot.scan).
      meta.json: counts, sizes, the days and files read, and seconds. Deterministic: the same inputs give the same bytes."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)     # also under python3 -I, which leaves the script's folder off the path
    import memebot as M              # read only
    t_start = time.time()
    now = int(now)
    days = max(1, int(num(days) or FEED_DAYS))
    since = now - days * DAY
    os.makedirs(out, exist_ok=True)
    # one streaming pass over the scored snapshots of the window (about 2 s a day): only holder lists, outcomes and euros are kept
    events, seen, slim = [], {}, {}
    n_read = n_skip = 0
    for fn in sorted(glob.glob(os.path.join(d, "db", "memesnapres", "*.json"))):
        day = _name_ms(fn)
        if day is not None and day + DAY <= since:
            n_skip += 1                                   # taken on a day that ended before the window: not opened
            continue
        doc = M.load_json(fn, None)
        n_read += 1
        if not isinstance(doc, dict):
            continue
        t0, t1 = num(doc.get("t0")), num(doc.get("t"))
        if t0 is not None and t0 < since:
            continue
        coins = [c for c in (doc.get("coins") or []) if isinstance(c, dict)]
        known = t1 if t1 else ((t0 or 0) + 2 * H)
        if known <= now:      # memebot.wallet_table reads exactly these two fields of a coin: eur and rc.holders
            slim[os.path.basename(fn)[:-5]] = {"coins": [{"eur": c.get("eur"), "rc": {"holders": _snap_holders(c)}} for c in coins
                                                         if num(c.get("eur")) is not None and isinstance(c.get("rc"), dict)]}
        if not t0:
            continue
        for c in coins:
            hl = _snap_holders(c)
            if not hl:
                continue
            hs = {h for h in hl[:40] if B58.match(h)}
            for h in hs:
                seen[h] = seen.get(h, 0) + 1
            mult = num(c.get("mult"))
            events.append((known, hs, bool(c.get("gone")) or (mult is not None and mult < RUG_X)))
        del doc, coins
    n_coins = len(events)
    common = {w for w, k in seen.items() if k > max(20, 0.01 * n_coins)}
    rug = set()
    for known, hs, gone in events:
        if gone and known <= now:
            rug |= hs - common
    orig = M.load_docs
    M.load_docs = lambda dd, coll: slim if coll == "memesnapres" else orig(dd, coll)    # memebot's own wallet_table, on the slim copy
    try:
        table = M.wallet_table(d)
    finally:
        M.load_docs = orig
    sw = {w: v["avg"] for w, v in table.items()}
    wm = {"v": 1, "t": now, "nCoins": n_coins, "common": sorted(common), "sw": sw, "rug": sorted(rug)}
    meta = {"v": 1, "t": now, "days": days, "snapFiles": n_read, "snapSkipped": n_skip, "files": {}}
    meta["files"]["walletmem.json.gz"] = {"nCoins": n_coins, "common": len(common), "sw": len(sw), "rug": len(rug),
                                          "bytes": _gz_write(os.path.join(out, "walletmem.json.gz"), wm)}
    del slim, events
    prev = _gz_read(os.path.join(d, "xlinks.json.gz"))
    links = {}
    if isinstance(prev, dict) and prev.get("v") == 1 and isinstance(prev.get("links"), dict):
        for k, e in prev["links"].items():
            if isinstance(e, list) and len(e) >= 6 and isinstance(e[5], list) and norm_x("https://" + k):
                links[k] = [e[0], int(num(e[1]) or 0), int(num(e[2]) or 0), e[3], int(num(e[4]) or 0),
                            [[u[0], int(num(u[1]) or 0)] for u in _uses(e) if isinstance(u, list) and len(u) == 2 and num(u[1]) is not None]]
    n_prev = len(links)
    pf, _ = M.load_side(d, "pf", M.PF_COLS)
    for a in sorted(pf):
        r = pf[a] if isinstance(pf[a], dict) else {}
        ms = _real_ms(parse_ms(r.get("createdAt"))) or now
        xlinks_add(links, r.get("twitter"), a, min(ms, now))
    pairs = M.load_pairs(d)
    pairs = pairs if isinstance(pairs, dict) else {}
    for a in sorted(pairs):
        pr = pairs[a] if isinstance(pairs[a], dict) else {}
        mint, pool = pair_times(pr)
        ms = mint or pool or now
        xlinks_add(links, pr.get("xUrl"), a, min(ms, now))
    links = {k: (e[:5] + [[]] if len(e[5]) == 1 else e) for k, e in links.items() if e[4] >= now - XLINK_KEEP_MS}   # one coin: no list
    meta["files"]["xlinks.json.gz"] = {"links": len(links), "before": n_prev,
                                       "bytes": _gz_write(os.path.join(out, "xlinks.json.gz"), {"v": 1, "t": now, "links": links})}
    sym = {}
    for a, pr in pairs.items():
        if not isinstance(pr, dict):
            continue
        s = str(pr.get("symbol") or "").upper()
        mc = num(pr.get("marketCap")) or 0
        if s and mc >= sym.get(s, 0):
            sym[s] = mc
    meta["files"]["symmc.json.gz"] = {"syms": len(sym), "bytes": _gz_write(os.path.join(out, "symmc.json.gz"), {"v": 1, "t": now, "sym": sym})}
    meta["secs"] = round(time.time() - t_start, 2)
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, sort_keys=True, indent=1)
    return meta


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="traps.py: the launch radar's rule core (fake money only)")
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("feed", help="build walletmem / xlinks / symmc for the radar from the scan's data")
    f.add_argument("--dir", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--now", type=int, default=None)
    f.add_argument("--days", type=int, default=FEED_DAYS, help="days of scored snapshots to read (default %d)" % FEED_DAYS)
    a = ap.parse_args(argv)
    if a.cmd != "feed":
        ap.print_help()
        return 2
    meta = feed(a.dir, a.out, a.now if a.now is not None else int(time.time() * 1000), a.days)
    print(json.dumps(meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
