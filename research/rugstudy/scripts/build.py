#!/usr/bin/env python3
"""Rug and winner study, step 1: build the study tables from the bot's own recorded data (fake-money paper bot, read only).

Usage: python3 -I build.py <results db dir> <memesnapres dir> <repo dir (read only, for the zero model)> <out dir>

Writes <out>/listings.jsonl (one row per listed young coin: memeyoung U memeearly, first listing per coin),
       <out>/snapyoung.jsonl (every snapshot coin under 1 h old with >= $5k liquidity, first appearance per coin),
       <out>/positions.jsonl (paper positions since the v2 restart, with exits),
       <out>/glitches.json (every observation the glitch rules caught), <out>/build_log.txt
"""
import collections, glob, json, math, os, re, sys, datetime as dt
from zoneinfo import ZoneInfo

DB, SNAP, REPO, OUT = sys.argv[1:5]
sys.path.insert(0, REPO)
import memebot as M   # read only: zero_p / the stored zero model

BERLIN = ZoneInfo("Europe/Berlin")
H = 3_600_000
RESTART = int(dt.datetime(2026, 10, 10, 18, 11, tzinfo=dt.timezone.utc).timestamp() * 1000)
DEAD_LIQ = 1_000.0       # G1: a pool under $1k liquidity is dead -> rug, whatever the price says
REAL_LIQ = 5_000.0       # a rise counts only with at least this much liquidity at that time
AMM_MAX = 1.5            # G4: liq ratio above 1.5 * sqrt(price ratio) = a self-priced pool (fluxbeam token-factory pairs move liq 1:1 with price)
AMM_MIN = 0.5            # G2: liq ratio must be >= 0.5 * sqrt(price ratio) (constant-product pool); real moves sit at 0.95-1.25
PEAK_MAX = 30.0          # G3: a peak above 30x the entry is not believed (memebot CANDLE_MAX_X)
RUG_X = 0.10             # price down 90% or more
WIN_X = 2.0
LOG = []


def log(s):
    LOG.append(s)
    print(s, file=sys.stderr)


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def lj(fn):
    with open(fn, encoding="utf-8") as f:
        return json.load(f)


def rid_of(t):
    return dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")


def berlin_hour(t):
    return dt.datetime.fromtimestamp(t / 1000, BERLIN).hour


# ------------------------------------------------------------------ the zero model of the last training (in-sample caveat)
TRAIN = lj(os.path.join(DB, "memebot", "train.json"))
ZMODEL = TRAIN.get("zeroModel")


def zp_of(f):
    try:
        return M.zero_p(ZMODEL, f) if f else None
    except Exception:
        return None


# ------------------------------------------------------------------ snapshot results (2 h outcome + all factors)
log("reading memesnapres ...")
SNAPYOUNG = []                              # young (< 1 h) with >= $5k liquidity
SNAPIDX = {}                                # (run id, addr) -> snapshot coin, for coins under 3 h (joins)
SYM_FIRST = {}                              # upper symbol -> list of (t, addr) first sightings per addr (ticker reuse)
HOLDER_SEEN = collections.Counter()         # wallet -> number of coins (with rc docs) it is a top holder of (program accounts)
HOLDER_EVENTS = []                          # (t_known, wallet set, rugged?) for the wallet-reuse signal
nfiles = 0
for fn in sorted(glob.glob(os.path.join(SNAP, "*.json"))):
    d = lj(fn)
    nfiles += 1
    rid = os.path.basename(fn).rsplit("-", 1)[0]
    t0, t1 = num(d.get("t0")), num(d.get("t"))
    if not t0:
        continue
    for c in d.get("coins") or []:
        a = c.get("a")
        f = c.get("f") or {}
        s = str(c.get("s") or "").strip().upper()
        if s:
            lst = SYM_FIRST.setdefault(s, {})
            if a not in lst or t0 < lst[a]:
                lst[a] = t0
        rc = c.get("rc")
        if isinstance(rc, dict) and rc.get("holders"):
            hs = set(rc["holders"][:40])
            HOLDER_SEEN.update(hs)
            gone = bool(c.get("gone")) or (num(c.get("mult")) is not None and num(c["mult"]) < RUG_X)
            HOLDER_EVENTS.append((t1 or t0 + 2 * H, t0, a, hs, gone))
        age = num(f.get("ageH"))
        if age is None or age >= 3:
            continue
        row = {"rid": rid, "t": t0, "tEval": t1, "a": a, "s": c.get("s"), "f": f, "rc": rc, "why": c.get("why") or [], "sc": num(c.get("sc")),
               "pass": c.get("pass"), "mc": num(c.get("mc")), "liq": num(c.get("liq")), "mult": num(c.get("mult")), "gone": bool(c.get("gone")),
               "src": c.get("src") or [], "x": c.get("x")}
        SNAPIDX[(rid, a)] = row
        if age < 1 and (row["liq"] or 0) >= REAL_LIQ:
            SNAPYOUNG.append(row)
log("snapshot files %d, young rows (liq>=5k) %d, join index %d, holder docs %d" % (nfiles, len(SNAPYOUNG), len(SNAPIDX), len(HOLDER_EVENTS)))

# program / pool accounts: wallets that are top holders of more than 1% of all coins with holder lists are not people
NHOLD = len(HOLDER_EVENTS)
COMMON = {w for w, k in HOLDER_SEEN.items() if k > max(20, 0.01 * NHOLD)}
log("common holder accounts excluded (top holder of >1%% of coins): %d" % len(COMMON))
# wallet -> sorted list of (t_known, t0, addr, gone)
WALLET_HIST = collections.defaultdict(list)
for t_known, t0, a, hs, gone in HOLDER_EVENTS:
    for w in hs - COMMON:
        WALLET_HIST[w].append((t_known, t0, a, gone))
for w in WALLET_HIST:
    WALLET_HIST[w].sort()


def wallet_reuse(rc, t, a):
    """How many of this coin's top holders were top holders of an EARLIER coin whose 2 h result was already known at t, and how many of
    those earlier coins went to zero (gone or -90%). Only results known before t count (no look-ahead)."""
    if not isinstance(rc, dict) or not rc.get("holders"):
        return None, None, None
    hs = set(rc["holders"][:40]) - COMMON
    seen_w, rug_w, rug_coins = 0, 0, set()
    for w in hs:
        prev = [e for e in WALLET_HIST.get(w, ()) if e[0] <= t and e[2] != a]
        if prev:
            seen_w += 1
            r = [e for e in prev if e[3]]
            if r:
                rug_w += 1
                rug_coins.update(e[2] for e in r)
    return seen_w, rug_w, len(rug_coins)


def ticker_reused(sym, a, t):
    """The same ticker (case-insensitive) on another coin first seen at least 1 h before t (our own sightings since 2026-10-05)."""
    s = str(sym or "").strip().upper()
    if not s:
        return None
    return any(b != a and t0 <= t - H for b, t0 in SYM_FIRST.get(s, {}).items())


BRAND = re.compile(r"\b(google|apple|nvidia|openai|chatgpt|gpt|gemini|claude|grok|deepseek|tesla|elon|musk|trump|mrbeast|mr ?beast|nike|amazon|microsoft|meta|"
                   r"rockstar|gta|minecraft|disney|pixar|spacex|x ai|xai|binance|bnb|coinbase|robinhood|blackrock|starbucks|mcdonald|coca|pepsi|"
                   r"netflix|youtube|tiktok|samsung|amd|intel|hermes|hermès|rolex|ferrari|lamborghini|bmw|porsche|toy story|spongebob|simpsons|batman|pokemon)\b", re.I)


# ------------------------------------------------------------------ signals from factors + RugCheck doc
INSIDER_NET = re.compile(r"insider network of (\d+) wallets", re.I)


def signals(f, rc, why, extra):
    """Flat dict of every signal we stored; None = not known for this coin."""
    f = f or {}
    s = {}
    g = lambda k: num(f.get(k))
    s["ageMin"] = 60 * g("ageH") if g("ageH") is not None else extra.get("ageMin")
    s["liq"] = extra.get("liq") if extra.get("liq") is not None else (10 ** g("logLiq") if g("logLiq") is not None else None)
    s["mc"] = extra.get("mc") if extra.get("mc") is not None else (10 ** g("logMc") if g("logMc") is not None else None)
    for k in ("liqMc", "volMc", "buyShare", "buyRatio1h", "buys1", "buys24", "vol1Share", "c1", "m5", "srcN", "kwN", "boosts", "nPairs", "socN", "web",
              "x", "pf.replies", "pf.twitter", "pf.website", "pf.telegram", "pf.live", "pf.athRatio", "vt.tweet", "vt.likes", "theme.animal",
              "jup.devMints", "jup.organic", "jup.holders", "jup.verified", "jup.top10Pct", "jup.netBuyers1", "jup.mcPerHolder", "jup.holderChg24",
              "rc.score", "rc.lp", "rc.top1", "rc.top10", "rc.holders", "rc.insiders", "rc.creator", "rc.danger", "rc.warn", "rc.mutable",
              "dev.pct", "dev.sold", "dev.txs3h", "dev.authOff", "ds.paid", "ds.paidAgeH", "ds.ads", "ds.cto", "cm.rcNet", "cm.rcDown",
              "sw.n", "sw.avg", "sw.wins", "fl.rate1h", "fl.buyers", "fl.sellers", "fl.flip", "fl.buyerRatio", "fl.netShare", "fl.topBuyer",
              "gt.buyerRatio", "gt.buyers24", "lp.trusted", "lp.other", "src.pf", "mkt.sol24", "mkt.fng", "news.hits", "gm.src"):
        s[k] = g(k)
    s["score"] = extra.get("score")
    s["zp"] = zp_of(f) if f else None
    # RugCheck names
    if isinstance(rc, dict):
        dn = [str(x) for x in (rc.get("danger") or [])]
        wn = [str(x) for x in (rc.get("warn") or [])]
        alln = dn + wn
        low = [x.lower() for x in alln]
        has = lambda *keys: any(any(k in x for k in keys) for x in low)
        s["rc.report"] = 1.0
        s["rcn.danger_any"] = 1.0 if dn else 0.0
        s["rcn.creator_rugged"] = 1.0 if has("creator history of rugged") else 0.0
        s["rcn.lp_unlocked"] = 1.0 if has("lp unlocked") else 0.0
        s["rcn.low_liquidity"] = 1.0 if has("low liquidity") else 0.0
        s["rcn.single_holder"] = 1.0 if has("single holder") else 0.0
        s["rcn.top10_high"] = 1.0 if has("top 10 holders high", "high holder concentration") else 0.0
        s["rcn.holder_correlation"] = 1.0 if has("holder correlation") else 0.0
        m = [int(INSIDER_NET.search(x).group(1)) for x in alln if INSIDER_NET.search(x)]
        s["rcn.insider_net"] = 1.0 if m else 0.0
        s["rcn.insider_net_size"] = float(max(m)) if m else 0.0
        s["rcn.cluster_any"] = 1.0 if (m or has("holder correlation")) else 0.0
        s["rcn.copycat"] = 1.0 if has("copycat") else 0.0
        s["rcn.mutable"] = 1.0 if (has("mutable metadata") or rc.get("mutable") is True) else 0.0
        s["rcn.authority"] = 1.0 if has("mint authority", "freeze authority", "permanent control") else 0.0
        s["rcn.few_lp_providers"] = 1.0 if has("lp providers") else 0.0
        s["rcn.mc_per_holder"] = 1.0 if has("market cap per holder") else 0.0
        s["rc.top1"] = num(rc.get("top1")) if s.get("rc.top1") is None else s["rc.top1"]
        s["rc.top10"] = num(rc.get("top10")) if s.get("rc.top10") is None else s["rc.top10"]
        s["rc.holders"] = num(rc.get("holdersN")) if s.get("rc.holders") is None else s["rc.holders"]
        s["rc.insiders"] = num(rc.get("insiders")) if s.get("rc.insiders") is None else s["rc.insiders"]
        s["rc.creator"] = num(rc.get("creatorPct")) if s.get("rc.creator") is None else s["rc.creator"]
        s["rc.lp"] = num(rc.get("lpLocked")) if s.get("rc.lp") is None else s["rc.lp"]
        s["rc.launchpad"] = str(rc.get("launchpad") or "") or None
        dv = rc.get("dev") or {}
        if s.get("dev.sold") is None and num(dv.get("devSold")) is not None:
            s["dev.sold"] = num(dv.get("devSold"))
        sw, rw, rcn = wallet_reuse(rc, extra["t"], extra["a"])
        s["own.holders_seen_before"] = sw
        s["own.holders_in_earlier_rug"] = rw
        s["own.earlier_rug_coins"] = rcn
    else:
        s["rc.report"] = 0.0
    # gate words the scan put on the coin
    why = set(why or [])
    for k in ("copy", "crash", "spike", "wash", "nobuyers", "novol1h", "risk", "liq", "mc", "vol", "young", "paid"):
        s["gate." + k] = 1.0 if k in why else 0.0
    s["dex"] = extra.get("dex")
    s["launchpad"] = extra.get("launchpad")
    s["hourBerlin"] = berlin_hour(extra["t"])
    s["own.ticker_reused"] = None if extra.get("sym") is None else (1.0 if ticker_reused(extra.get("sym"), extra["a"], extra["t"]) else 0.0)
    s["own.brand_name"] = None if extra.get("sym") is None and extra.get("name") is None else (
        1.0 if BRAND.search("%s %s" % (extra.get("sym") or "", extra.get("name") or "")) else 0.0)
    return s


def self_priced_coin(sg, a, dex, oc):
    """G4 at coin level: liquidity >= 90% of the market cap on a token that is not a pump.fun mint and not on PumpSwap (fluxbeam-style
    token-factory pairs: liquidity valued with the token's own price, so it moves 1:1 with the price and is not real USD depth), or a
    later observation that showed liquidity growing like the price. Its rises are not counted as winners (win -> None)."""
    lm = sg.get("liqMc")
    if lm is None and sg.get("liq") and sg.get("mc"):
        lm = sg["liq"] / sg["mc"]
    flag = bool(oc.get("selfPriced")) or (lm is not None and lm >= 0.9 and not str(a).endswith("pump") and str(dex or "").lower() != "pumpswap")
    sg["selfPriced"] = 1.0 if flag else 0.0
    if flag:
        for k in ("win1h", "win1hEnd", "win2h"):
            if oc.get(k):
                GLITCH.append({"rule": "G4 self-priced pool (winner dropped)", "addr": a, "obs": k, "liqMc": lm, "dex": dex})
                oc[k] = None


def add_mint(sg, born, minted):
    """Pool opening vs token mint (early list only: DexScreener pairCreatedAt vs pump.fun / LaunchLab createdAt).
    instantPool: the pool opened within 60 s of the mint (no bonding-curve phase: the curve was bought out at once, a bundled launch).
    curve2m: the token sat on its curve 2+ minutes before the pool (organic graduation). Unknown mint time -> None."""
    if not born or not minted:
        sg["mintToPoolMin"] = sg["instantPool"] = sg["graduated"] = None
        return
    m = (born - minted) / 60000.0
    sg["mintToPoolMin"] = m
    sg["instantPool"] = 1.0 if 0 <= m < 1.0 else 0.0
    sg["graduated"] = 1.0 if m >= 2.0 else 0.0


# ------------------------------------------------------------------ memeyoung (listed new launches, 1 h path, 24 h)
log("reading memeyoung / memeearly / memepos ...")
YOUNG = {}
for fn in sorted(glob.glob(os.path.join(DB, "memeyoung", "*.json"))):
    rid = os.path.basename(fn)[:-5]
    d = lj(fn)
    t = num(d.get("t"))
    picks = [p for p in d.get("picks") or [] if num(p.get("px"))]
    outs = d.get("outs") or {}
    by = {}
    for key in ("1", "24"):
        o = (outs.get(key) or {}).get("picks") or []
        # outs are written in pick order, skipping picks without px: match by order, check the symbol
        if not o:
            by[key] = None
        elif len(o) == len(picks) and all(str(x.get("sym")) == str(p.get("sym")) for x, p in zip(o, picks)):
            by[key] = o
        else:
            symq = collections.defaultdict(list)
            for x in o:
                symq[str(x.get("sym"))].append(x)
            by[key] = [symq[str(p.get("sym"))].pop(0) if symq[str(p.get("sym"))] else None for p in picks]
            log("memeyoung %s outs[%s]: order mismatch, matched by symbol" % (rid, key))
    for i, p in enumerate(picks):
        YOUNG[(rid, p["addr"])] = {"rid": rid, "t": t, "pricedAt": num(d.get("pricedAt")), "p": p, "k": i + 1,
                                   "o1": by.get("1", [None] * len(picks))[i] if by.get("1") else None,
                                   "o24": by.get("24", [None] * len(picks))[i] if by.get("24") else None,
                                   "o1h": num((outs.get("1") or {}).get("h")), "o24h": num((outs.get("24") or {}).get("h"))}

EARLY = {}
for fn in sorted(glob.glob(os.path.join(DB, "memeearly", "*.json"))):
    d = lj(fn)
    rid = d.get("id") or os.path.basename(fn)[:-5]
    for c in d.get("coins") or []:
        EARLY[(rid, c["addr"])] = {"rid": rid, "t": num(d.get("t")), "at": num(d.get("at")), "c": c}

POS = {}
for fn in glob.glob(os.path.join(DB, "memepos", "*.json")):
    POS[os.path.basename(fn)[:-5]] = lj(fn)
EXITS = collections.defaultdict(list)
for fn in glob.glob(os.path.join(DB, "memeexit", "*.json")):
    e = lj(fn)
    EXITS[e.get("pos")].append(e)
POS_BY_RUN = {}
for pid, p in POS.items():
    POS_BY_RUN[(p.get("rec"), p.get("addr"))] = pid
log("memeyoung listings %d, memeearly listings %d, positions %d" % (len(YOUNG), len(EARLY), len(POS)))

GLITCH = []


def obs(px0, liq0, px1, liq1, gone):
    """One later observation against an entry -> (ratio or None, state): state 'gone', 'dead' (liq < $1k: G1), 'rug' (-90%),
    'up_real', 'up_fake' (G2 failed), 'flat'."""
    if gone:
        return 0.0, "gone"
    if not px0 or px1 is None:
        return None, None
    r = px1 / px0
    if liq1 is not None and liq1 < DEAD_LIQ:
        return r, "dead"
    if r < RUG_X:
        return r, "rug"
    if r >= WIN_X:
        if liq1 is None:
            return r, "up_noliq"
        lr = liq1 / liq0 if liq0 else None
        if liq1 >= REAL_LIQ and lr is not None and lr > AMM_MAX * math.sqrt(r):
            return r, "up_selfpriced"     # G4: liquidity grew like the price itself: the pool's sides are valued with the token's own price
        if liq1 >= REAL_LIQ and lr is not None and lr >= AMM_MIN * math.sqrt(r) and r <= PEAK_MAX:
            return r, "up_real"
        return r, "up_fake"
    return r, "flat"


def path_stats(path, upto=60):
    """Candle path [[min, o, h, l, c], ...] relative to the entry: (peak close, low close, last close, n candles, first minute) for min <= upto."""
    cs = [c for c in (path or []) if isinstance(c, list) and len(c) >= 5 and c[0] <= upto and num(c[4])]
    if not cs:
        return None
    closes = [c[4] for c in cs]
    return {"peak": max(closes), "low": min(closes), "last": closes[-1], "n": len(cs), "first": cs[0][0], "lastMin": cs[-1][0]}


def outcome(e, y, sn, pid):
    """Combine every later observation of one listing into rug / winner flags. e: memeearly coin, y: memeyoung listing, sn: snapshot row
    of the same run, pid: paper position id."""
    o = {"rug1h": None, "win1h": None, "win1hEnd": None, "rug2h": None, "win2h": None, "rug24h": None, "fakePeak": False, "srcs": []}
    rugs1, wins1, wend1, known1 = [], [], [], []
    notes = []
    if e:
        c = e["c"]
        px0, liq0 = num(c.get("px")), num(c.get("liq"))
        for k in ("p2", "p60"):
            p = c.get(k)
            if not isinstance(p, dict):
                continue
            r, st = obs(px0, liq0, num(p.get("px")), num(p.get("liq")), p.get("gone"))
            if st is None:
                continue
            known1.append(k)
            o["e_" + k] = r
            o["e_" + k + "_state"] = st
            if st in ("gone", "dead", "rug"):
                rugs1.append("early." + k + "." + st)
                if st == "dead" and r is not None and r >= WIN_X:
                    o["fakePeak"] = True
                    GLITCH.append({"rule": "G1 dead pool", "sym": c.get("sym"), "addr": c.get("addr"), "rid": e["rid"], "obs": k, "x": round(r, 2), "liq": p.get("liq")})
            if st == "up_real":
                wins1.append("early." + k)
                wend1.append("early." + k)
            if st == "up_selfpriced":
                GLITCH.append({"rule": "G4 self-priced pool", "sym": c.get("sym"), "addr": c.get("addr"), "rid": e["rid"], "obs": k, "x": round(r, 2), "liq": p.get("liq"), "liq0": liq0})
                o["selfPriced"] = True
            if st in ("up_fake", "up_noliq"):
                GLITCH.append({"rule": "G2 amm" if st == "up_fake" else "G2 no liq", "sym": c.get("sym"), "addr": c.get("addr"), "rid": e["rid"], "obs": k,
                               "x": round(r, 2), "liq": p.get("liq"), "liq0": liq0})
                o["fakePeak"] = True
        o["srcs"].append("early")
    if y:
        o1 = y.get("o1")
        if isinstance(o1, dict) and not o1.get("missed") and not o1.get("waiting") and num(o1.get("mult")) is not None:
            m = num(o1["mult"])
            known1.append("young1h")
            o["y_1h"] = m
            if o1.get("gone") or m < RUG_X:
                rugs1.append("young.1h")
            ps = path_stats(o1.get("path"))
            if ps:
                o["y_peak"], o["y_low"], o["y_pathN"], o["y_pathFirst"] = ps["peak"], ps["low"], ps["n"], ps["first"]
                if ps["low"] <= RUG_X:
                    rugs1.append("young.path")
                if WIN_X <= ps["peak"] <= PEAK_MAX:
                    wins1.append("young.path")
            if m >= WIN_X:
                notes.append("young1h_up_unconfirmed")   # the 1 h mark has no liquidity check in memeyoung: confirmed below
        elif isinstance(o1, dict) and o1.get("glitch"):
            GLITCH.append({"rule": "G3 candle span", "sym": y["p"].get("sym"), "addr": y["p"].get("addr"), "rid": y["rid"], "obs": "young1h"})
        o24 = y.get("o24")
        if isinstance(o24, dict) and not o24.get("missed") and not o24.get("waiting") and num(o24.get("mult")) is not None:
            o["y_24h"] = num(o24["mult"])
        o["srcs"].append("young")
    if sn:
        o["s_2h"] = sn.get("mult")
        o["s_gone"] = sn.get("gone")
        o["srcs"].append("snap")
    # rug within 1 h
    if rugs1:
        o["rug1h"] = True
    elif known1:
        o["rug1h"] = False
    o["rugWhy"] = rugs1
    # a peak is believed only if the pool was not dead at the 1 h checks (a rise right before an LP pull is how Doggo / Husky looked)
    if rugs1 and any(".dead" in x or ".gone" in x for x in rugs1):
        wins1 = [w for w in wins1 if w.startswith("early.p2")]      # only a real rise seen before the death, with liquidity, stays
    # the memeyoung 1 h mark alone (no liquidity) confirms only when another source says the pool was alive with liquidity
    if "young1h_up_unconfirmed" in notes and not rugs1:
        alive = (o.get("e_p60_state") in ("up_real", "flat")) or (sn and not sn.get("gone") and (num(sn.get("mult")) or 0) >= 1.0)
        if alive:
            wend1.append("young.1h")
            wins1.append("young.1h")
    if known1 or wins1:
        o["win1h"] = bool(wins1)
        o["win1hEnd"] = bool(wend1)
    o["winWhy"] = wins1
    # 2 h (snapshot endpoint)
    r2 = None
    if sn and sn.get("mult") is not None:
        g2 = bool(sn.get("gone"))
        m2 = num(sn.get("mult")) or 0.0
        r2 = g2 or m2 < RUG_X
        o["win2h"] = (not g2) and WIN_X <= m2 <= PEAK_MAX
        if m2 > PEAK_MAX:
            GLITCH.append({"rule": "G3 snapshot >30x", "sym": sn.get("s"), "addr": sn.get("a"), "rid": sn.get("rid"), "obs": "snap2h", "x": m2})
            o["win2h"] = None
    o["rug2h"] = True if (o["rug1h"] or r2) else (False if (o["rug1h"] is False or r2 is False) else None)
    # 24 h: memeyoung 24 h mark (no liquidity there: undercounts rugs whose dead pool still shows a price)
    r24 = None
    if o.get("y_24h") is not None:
        r24 = o["y_24h"] < RUG_X
    o["rug24h"] = True if (o["rug2h"] or r24) else (False if r24 is False else None)
    # paper position (6 h rule)
    if pid:
        ex = EXITS.get(pid) or []
        p = POS[pid]
        o["pos"] = pid
        o["posWhy"] = ",".join(sorted({str(x.get("why")) for x in ex})) or "open"
        px0 = num(p.get("px"))
        o["posX"] = (num(ex[-1].get("px")) / px0) if ex and px0 and num(ex[-1].get("px")) is not None else None
    return o


# ------------------------------------------------------------------ listings: memeyoung U memeearly, first listing per coin
keys = sorted(set(YOUNG) | set(EARLY), key=lambda k: k[0])
first = {}
for k in keys:
    rid, a = k
    if a not in first:
        first[a] = k
listings = []
for a, k in first.items():
    rid = k[0]
    y, e = YOUNG.get(k), EARLY.get(k)
    sn = SNAPIDX.get(k)
    pid = POS_BY_RUN.get(k)
    p = (y or {}).get("p") or {}
    c = (e or {}).get("c") or {}
    t = (y or e)["t"]
    sym = p.get("sym") or c.get("sym")
    pos = POS.get(pid) if pid else None
    f = (sn or {}).get("f") or (pos or {}).get("f") or {}
    rc = (sn or {}).get("rc") if sn and sn.get("rc") else ((pos or {}).get("risk"))
    extra = {"t": t, "a": a, "sym": sym, "name": (pos or {}).get("name"), "dex": c.get("dex") or (pos or {}).get("dex"),
             "launchpad": p.get("launchpad") or (rc or {}).get("launchpad") if isinstance(rc, dict) else p.get("launchpad"),
             "ageMin": p.get("ageMin") if p.get("ageMin") is not None else c.get("ageMin"), "liq": c.get("liq") if c.get("liq") is not None else (sn or {}).get("liq"),
             "mc": p.get("mc") if p.get("mc") is not None else c.get("mc"), "score": p.get("score") if p.get("score") is not None else c.get("score")}
    sg = signals(f, rc, (sn or {}).get("why"), extra)
    born, minted = num(c.get("born")), num(c.get("minted"))
    add_mint(sg, born, minted)
    sg["early.rc"] = c.get("rc") if e else None
    sg["young.ok"] = p.get("ok") if y else None
    sg["listAgeMin"] = c.get("ageMin") if e else p.get("ageMin")
    sg["early.k"] = c.get("k") if e else None
    sg["young.k"] = (y or {}).get("k")
    sg["bought"] = 1.0 if pid else 0.0
    oc = outcome(e, y, sn, pid)
    self_priced_coin(sg, a, extra.get("dex"), oc)
    listings.append({"rid": rid, "t": t, "a": a, "sym": sym, "inEarly": bool(e), "inYoung": bool(y), "hasSnap": bool(sn), "hasF": bool(f), "hasRc": isinstance(rc, dict),
                     "sig": sg, "out": oc})
log("listings (first per coin) %d: early %d, young %d, with snapshot factors %d, with RugCheck doc %d" % (
    len(listings), sum(r["inEarly"] for r in listings), sum(r["inYoung"] for r in listings), sum(r["hasSnap"] for r in listings), sum(r["hasRc"] for r in listings)))

# ------------------------------------------------------------------ snapshot young cohort, first appearance per coin
SNAPYOUNG.sort(key=lambda r: r["t"])
seen = set()
snaprows = []
for r in SNAPYOUNG:
    if r["a"] in seen:
        continue
    seen.add(r["a"])
    rc = r["rc"]
    extra = {"t": r["t"], "a": r["a"], "sym": r["s"], "name": None, "dex": None, "launchpad": (rc or {}).get("launchpad") if isinstance(rc, dict) else None,
             "ageMin": None, "liq": r["liq"], "mc": r["mc"], "score": r["sc"]}
    sg = signals(r["f"], rc, r["why"], extra)
    m, g = r["mult"], r["gone"]
    win = (not g) and m is not None and WIN_X <= m <= PEAK_MAX
    if m is not None and m > PEAK_MAX and not g:
        GLITCH.append({"rule": "G3 snapshot >30x", "sym": r["s"], "addr": r["a"], "rid": r["rid"], "obs": "snap2h", "x": m})
        win = None
    oc = {"rug2h": bool(g or (m is not None and m < RUG_X)), "win2h": win, "mult": m, "gone": g, "evalH": (r["tEval"] - r["t"]) / H if r["tEval"] else None}
    self_priced_coin(sg, r["a"], None, oc)
    snaprows.append({"rid": r["rid"], "t": r["t"], "a": r["a"], "sym": r["s"], "hasRc": isinstance(rc, dict), "sig": sg, "out": oc})
log("snapshot young cohort (first per coin) %d, with RugCheck %d" % (len(snaprows), sum(r["hasRc"] for r in snaprows)))

# ------------------------------------------------------------------ paper positions since the restart
posrows = []
for pid, p in sorted(POS.items()):
    t = num(p.get("t"))
    if not t or t < RESTART:
        continue
    ex = EXITS.get(pid) or []
    px0 = num(p.get("px"))
    rid = p.get("rec")
    y = YOUNG.get((rid, p.get("addr")))
    e = EARLY.get((rid, p.get("addr")))
    sn = SNAPIDX.get((rid, p.get("addr")))
    oc = outcome(e, y, sn, pid)
    extra = {"t": t, "a": p.get("addr"), "sym": p.get("sym"), "name": p.get("name"), "dex": p.get("dex"), "launchpad": (p.get("risk") or {}).get("launchpad"),
             "ageMin": p.get("ageMin"), "liq": num(p.get("liq")), "mc": num(p.get("mc")), "score": num(p.get("score"))}
    sg = signals(p.get("f"), p.get("risk"), (sn or {}).get("why"), extra)
    sg["safety"] = p.get("safety")
    self_priced_coin(sg, p.get("addr"), p.get("dex"), oc)
    ec = (e or {}).get("c") or {}
    add_mint(sg, num(ec.get("born")), num(ec.get("minted")))
    posrows.append({"pid": pid, "grp": p.get("grp"), "t": t, "rid": rid, "a": p.get("addr"), "sym": p.get("sym"), "ticket": num(p.get("ticket")),
                    "why": ",".join(sorted({str(x.get("why")) for x in ex})) or "open", "exitX": (num(ex[-1].get("px")) / px0) if ex and px0 and num(ex[-1].get("px")) is not None else None,
                    "exitEur": sum(num(x.get("eur")) or 0 for x in ex) if ex else None, "exitAt": num(ex[-1].get("at")) if ex else None,
                    "sig": sg, "out": oc})
log("paper positions since restart %d" % len(posrows))

os.makedirs(OUT, exist_ok=True)
for name, rows in (("listings", listings), ("snapyoung", snaprows), ("positions", posrows)):
    with open(os.path.join(OUT, name + ".jsonl"), "w", encoding="utf-8") as fo:
        for r in rows:
            fo.write(json.dumps(r, default=str) + "\n")
with open(os.path.join(OUT, "glitches.json"), "w", encoding="utf-8") as fo:
    json.dump(GLITCH, fo, indent=1, default=str)
with open(os.path.join(OUT, "build_log.txt"), "w", encoding="utf-8") as fo:
    fo.write("\n".join(LOG) + "\n")
print(json.dumps({"listings": len(listings), "snapyoung": len(snaprows), "positions": len(posrows), "glitches": len(GLITCH)}))
