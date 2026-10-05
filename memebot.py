#!/usr/bin/env python3
"""Meme bot v5: fake money only, nothing is ever bought for real.

v5 (rule m8): a bankroll instead of an open-ended ticket count
  * BUDGET = 40 fake units in total. Every bot position costs TICKET = 20, so at most two coins are held at once; money comes
    back into the bankroll when a position is sold, and only then can the bot buy again
  * a pick run buys the TWO best-scored coins that pass the gates and have a clean RugCheck report (PICKS_PER_RUN = 2)
  * the random control group is off by default (CONTROL_PICKS = 0); it would spend fake money outside the 40 budget
  * python3 memebot.py cash -> the bankroll: what is deployed, what came back, what is free
  * fetching is done by fetch.py and the whole cycle by bot.py; this file only reads the fetched files and decides

What changed from v1 (rule m6 -> m7):
  * the coin list comes from many public sources at once (DexScreener boost/profile/ad/takeover lists, RugCheck's new-token
    list and ~50 DexScreener keyword searches), so a scan covers ~1000 coins instead of ~140
  * every number from every source is kept per coin (DexScreener, RugCheck, LunarCrush social buzz, which lists it was on)
  * the hand-made checks became *factors*; only a few hard gates remain (price, liquidity, market cap, launch curve, age, copycat)
  * the score is learned: every big-test coin is priced again 24h later, and each factor's rank correlation with the result
    becomes its weight (blended with a prior until ~600 coins are scored). The weights are saved as memeweights/<run>.
  * big-test snapshots are saved in chunks of 200 coins (memesnap/<run>-<k>), results likewise (memesnapres/<run>-<k>)
  * exits are unchanged: half at 2x, all out at -50%, back-to-entry after the half, 3-day limit, rug when the price is gone

What changed in v3 (still rule m7, more knowledge per coin):
  * news.json: headlines and social posts. Factors news.hits (headlines naming the coin), news.fresh (how recent the newest
    one is), news.narr (how hot the coin's theme words are across today's headlines)
  * gt/*.txt: GeckoTerminal pools (trending, new, top) -> address source plus distinct buyers/sellers (gt.* factors)
  * cg.json: CoinGecko trending coins matched by ticker (cg.* factors)
  * smart wallets: a RugCheck row may carry a 13th field with the top holder addresses. Scored big-test coins credit
    every wallet that held them; a new coin's sw.* factors say whether wallets with a winning record hold it
  * python3 memebot.py wallets -> prints the wallet table learned so far

What changed in v4 (still rule m7): traders as a source, from GMGN's public quotation API
  * gm/*.txt: coins ranked by smart-money activity, with per-coin trader quality (smart-degen and renowned holders, snipers,
    bundlers, rat traders, bluechip owners, rug ratio, wash-trading and honeypot flags, dev-team holdings) -> gm.* factors,
    a honeypot gate, and one more address source
  * tb/<address>.txt: the coin's 70 top buyers with status (hold / bought_more / sold / sold_part) and tags -> tb.* factors
    (share still holding, smart wallets holding, sniper and fresh-wallet shares) and more wallets for the wallet memory
  * wallets.json: GMGN's most profitable wallets (7d/30d) -> sw.lb* factors: how many of them hold the coin right now

Usage (all paths inside --dir, default ./mb):
  python3 memebot.py mode       -> {"pick", "scan", "bigTestSaveDue", "cash", ...}: what this run needs to fetch
  python3 memebot.py gather     -> merges lists.json + pairs/*.txt (+ social.json) into pairs.json/universe.json and prints
                                   "chunks": addresses that still need DexScreener data (open positions first), and coverage
  python3 memebot.py shortlist  -> addresses that need a RugCheck report: the best candidates first, then more for the big test
  python3 memebot.py run --mode pick|check -> writes out/*.json + out/manifest.json, prints a summary ("picks", "exits")
                                   (--force lets a manual pick run ignore the 3-hour gap and the daily cap, never the budget)
  python3 memebot.py cash       -> the bankroll
  python3 memebot.py learn      -> prints the learned factor weights from every scored big-test coin
  python3 memebot.py analyze    -> median split of every factor: which side did better 24h later

Inputs in --dir (every fetched file is plain text, one coin per line, fields separated by | ; a line with the wrong number of
fields is skipped, "null" means unknown):
  db/<collection>/<doc>.json  saved docs: memepos, memeexit, memesnap, memesnapres, memeweights, memebot/state, memebot/marks
  lists.json     {"boostTop": [addr..], "boostLatest": [..], "profiles": [..], "ads": [..], "cto": [..], "rcNew": [..]} (any names)
  pairs/*.txt    DexScreener rows, 27 fields: address|symbol|name|dexId|pairAddress|priceUsd|marketCap|fdv|liquidityUsd|volH24|volH6|volH1|
                 chgM5|chgH1|chgH6|chgH24|buysH24|sellsH24|buysH6|sellsH6|buysH1|sellsH1|pairCreatedAt|boosts|xUrl|websites|socials
                 or 3 fields for cheap re-pricing: address|priceUsd|liquidityUsd. search_<name>.txt files tag their coins kw:<name>.
                 (a JSON array of pair objects with the same keys also works)
  jup/*.txt      Jupiter token rows, 26 fields: address|symbol|name|usdPrice|mcap|fdv|liquidity|holderCount|organicScore|top10Pct|devMints|
                 isVerified|firstPool.createdAt|chg1h|chg6h|chg24h|buyVol24|sellVol24|buys24|sells24|traders24|netBuyers24|holderChg24|
                 buys1h|sells1h|netBuyers1h. Used as the coin's pair data when DexScreener has none, and as jup.* factors.
  pf/*.txt       pump.fun rows, 13 fields: mint|symbol|name|usd_market_cap|market_cap|ath_market_cap|reply_count|is_currently_live|
                 complete|created_timestamp|twitter|website|telegram. Only an address source plus pf.* factors (its caps are not trusted).
  social.json    LunarCrush rows: [symbol, name, engagements, mentions, creators, sentiment, galaxy, altRank] (or dicts with those keys)
  risk/*.txt     RugCheck rows, 12 fields: mint|score|lpLockedPct|holders|top1Pct|top10Pct|insiders|creatorPct|mutable|launchpad|
                 danger names ; separated|warn names ; separated      (risk.json {addr: {...}} also works)
                 or 13 fields: the same plus |top holder addresses ; separated  (feeds the smart-wallet memory)
  gt/*.txt       GeckoTerminal pool rows, 17 fields: baseTokenAddress|symbol|name|poolAddress|dex|priceUsd|fdv|reserveUsd|volH24|chgH1|chgH6|
                 chgH24|buysH24|sellsH24|buyers24|sellers24|poolCreatedAt. Address source (tag gt:<file>) plus gt.* factors.
  cg.json        CoinGecko trending: rows [symbol, name, rank] or [symbol, name, rank, chg24, marketCapRank] (or dicts). cg.* factors by ticker.
  news.json      headlines / posts: rows [text, source, time] (time = ms, s or ISO; may be null) or dicts {t|title|text, src, at|t}.
                 news.* factors: direct mentions of the coin, freshness, and the heat of the coin's theme words.
  gm/*.txt       GMGN token rows, 26 fields: address|symbol|name|price|market_cap|liquidity|volume|holder_count|top_10_holder_rate|
                 smart_degen_count|renowned_count|sniper_count|bundler_rate|rat_trader_amount_rate|bluechip_owner_percentage|rug_ratio|
                 is_wash_trading|hot_level|dev_team_hold_rate|top70_sniper_hold_rate|bot_degen_count|is_honeypot|creator_token_status|
                 twitter_rename_count|open_timestamp|launchpad. Address source (tag gm:<file>) plus gm.* factors and the honeypot gate.
  tb/<addr>.txt  GMGN top buyers of one coin (file named by the coin address), 4 fields: wallet|status|tags ; separated|maker tags.
  wallets.json   GMGN wallet leaderboard: rows [wallet, pnl, winrate, tags ; separated] or dicts {wallet_address, pnl_7d|pnl_30d, winrate_*, tags}.
"""
import argparse, glob, json, math, os, random, re, sys, time, datetime as dt

RULE = "m8"
BUDGET = 40.0            # the whole fake bankroll; bot positions are paid out of it and sales flow back into it
TICKET = 20.0            # fake units per position -> BUDGET / TICKET = 2 coins held at once
FEE_PCT, FEE_MIN = 0.005, 0.81
PICKS_PER_RUN = 2        # the two best coins per pick run (as far as the bankroll allows)
CONTROL_PICKS = 0        # random control coins per pick run (0 = off; they would spend fake money outside the budget)
DAILY_MAX = 4            # bot picks per Berlin day
PICK_GAP_H = 2.9
REPICK_DAYS = 7
TP_MULT, STOP_MULT, MAX_DAYS = 2.0, 0.5, 3
# hard gates (everything else is a factor the big test measures)
GATE_MIN_LIQ = 20_000
GATE_MC = (100_000, 50_000_000)
GATE_MIN_VOL24 = 20_000
GATE_MIN_AGE_H = 1.0
MIN_LP_LOCKED = 50.0
RISK_WARN_BLOCK = re.compile(r"holder|ownership|unlocked|creator|copycat|rug", re.I)
SHORTLIST = 12           # best candidates that get a RugCheck report in a pick run
RC_BIG = 120             # more coins (by score) that get a RugCheck report when a snapshot is due
RAND_MIN_LIQ = 20_000
SNAP_GAP_H = 11.5
EVAL_H = 23.5
SNAP_CHUNK = 200
LEARN_MIN_N = 80         # coins a factor needs on both sides before its correlation counts
LEARN_FULL_N = 600       # scored coins at which the learned weights fully replace the prior
EUR_CLIP = (-20.0, 60.0) # a 24h result is clipped to this range before learning, so one 50x coin does not set the weights
DAY = 86_400_000
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
# prior weights (sign = direction). Used fully until coins are scored, then blended out.
PRIOR = {"liqMc": 0.35, "volMc": 0.25, "buyShare": 0.2, "buyRatio1h": 0.2, "c6": -0.1, "c1": -0.1, "srcN": 0.15,
         "soc.eng": 0.1, "x": 0.1, "rc.lp": 0.1, "rc.top10": -0.1,
         # v3 knowledge: news, narrative heat, distinct buyers (GeckoTerminal), CoinGecko trending, smart wallets
         "news.hits": 0.1, "news.narr": 0.1, "news.fresh": 0.05, "gt.buyerRatio": 0.1, "cg.trend": 0.05, "sw.avg": 0.15, "sw.n": 0.05,
         # v4 traders: GMGN smart money, top buyers, leaderboard wallets
         "gm.smartDegen": 0.15, "gm.renowned": 0.1, "gm.bluechip": 0.1, "gm.hot": 0.05, "gm.bundler": -0.1, "gm.rat": -0.1, "gm.sniperHold": -0.1,
         "gm.wash": -0.15, "gm.rugRatio": -0.1, "gm.devHold": -0.05, "tb.holdShare": 0.1, "tb.smartHold": 0.15, "tb.sniperShare": -0.05,
         "tb.freshShare": -0.05, "sw.lb": 0.2, "sw.lbWin": 0.05}
SMART_TAGS = re.compile(r"smart_degen|renowned|app_smart_money|launchpad_smart|smart_money|\bkol\b", re.I)
BOT_TAGS = re.compile(r"sandwich_bot|bot_degen|\bbot\b|arbitrager", re.I)
TB_MAX_FILES = 400       # top-buyer files kept per scan (one per coin)
NEWS_MAX_AGE_H = 48.0    # headlines older than this are ignored
NEWS_STOP = set("""the a an and or of to in on for with from by at is are was be this that it its as new coin coins token tokens meme memecoin
memecoins crypto cryptocurrency solana sol pump fun pumpfun dex trading trade price market cap mcap launch launches launched inu dog cat ai
official community cto up down today news live here now just one all you your our we they what why how when who will can get got""".split())
SW_MIN_COINS = 2         # a wallet needs this many scored coins before its record counts
BOT_GROUPS = ("pick", "early")   # position groups paid out of the bankroll


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def fee(amount):
    return max(FEE_PCT * amount, FEE_MIN) if amount > 0 else 0.0


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_docs(d, coll):
    out = {}
    for p in glob.glob(os.path.join(d, "db", coll, "*.json")):
        doc = load_json(p, None)
        if isinstance(doc, dict):
            out[os.path.splitext(os.path.basename(p))[0]] = doc
    return out


def slug(s, n=12):
    s = re.sub(r"[^A-Za-z0-9]", "", str(s or ""))[:n]
    return s or "X"


def money(v):
    return ("$%.1fM" % (v / 1e6)) if v >= 1e6 else ("$%.0fk" % (v / 1e3))


def x_link(pr):
    u = str(pr.get("xUrl") or "").strip()
    return u[:120] if re.match(r"^https://(www\.)?(x|twitter)\.com/[A-Za-z0-9_]{1,30}(/.*)?$", u) else ""


# ---------------------------------------------------------------- saved state
def positions(d):
    pos, exits = load_docs(d, "memepos"), load_docs(d, "memeexit")
    for pid, p in pos.items():
        p["_id"] = pid
        p["_exits"] = sorted([e for e in exits.values() if e.get("pos") == pid], key=lambda e: e.get("t", 0))
        p["_left"] = max(0.0, 1.0 - sum(num(e.get("frac")) or 0 for e in p["_exits"]))
    return pos


def bankroll(pos):
    """The fake bankroll: BUDGET minus every bot ticket ever paid, plus every bot sale that came back.
    Open positions are counted at their ticket (what was paid), not at their current value."""
    spent = sum(num(p.get("ticket")) or TICKET for p in pos.values() if p.get("grp") in BOT_GROUPS)
    back = sum(num(e.get("eur")) or 0 for p in pos.values() if p.get("grp") in BOT_GROUPS for e in p["_exits"])
    n_open = sum(1 for p in pos.values() if p.get("grp") in BOT_GROUPS and p["_left"] > 1e-9)
    deployed = sum((num(p.get("ticket")) or TICKET) * p["_left"] for p in pos.values() if p.get("grp") in BOT_GROUPS if p["_left"] > 1e-9)
    free = BUDGET - spent + back
    return {"budget": BUDGET, "ticket": TICKET, "spent": round(spent, 2), "back": round(back, 2), "free": round(free, 2),
            "open": n_open, "deployed": round(deployed, 2), "slots": max(0, int((free + 1e-9) // TICKET))}


def due_snaps(d, now):
    snaps, done = load_docs(d, "memesnap"), load_docs(d, "memesnapres")
    return {sid: sn for sid, sn in sorted(snaps.items()) if sid not in done and isinstance(sn.get("coins"), list)
            and now - (num(sn.get("t")) or now) >= EVAL_H * 3_600_000}


def berlin_day(ms):
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        t = t.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        t = t + dt.timedelta(hours=2)
    return t.strftime("%Y-%m-%d")


def pick_room(state, pos, now, force=False):
    """How many bot positions this run may open: the bankroll always caps it, the 3-hour gap and the daily cap only without --force."""
    slots = bankroll(pos)["slots"]
    if slots <= 0:
        return 0, "the whole %.0f budget is deployed, this run only checks prices and exits" % BUDGET
    if not force and (num(state.get("lastPick")) or 0) > now - PICK_GAP_H * 3_600_000:
        return 0, "scanned less than 3 hours ago, this run only checks prices and exits"
    today = berlin_day(now)
    done = sum(1 for p in pos.values() if p.get("grp") == "pick" and berlin_day(num(p.get("t")) or 0) == today)
    if not force and done >= DAILY_MAX:
        return 0, "already %d picks today, this run only checks exits" % done
    room = min(PICKS_PER_RUN, slots) if force else min(PICKS_PER_RUN, DAILY_MAX - done, slots)
    return room, "%d picks today, %d free slot%s of %.0f" % (done, slots, "" if slots == 1 else "s", TICKET)


def snap_due(d, now):
    last = max([num(sn.get("t")) or 0 for sn in load_docs(d, "memesnap").values()] or [0])
    return now - last >= SNAP_GAP_H * 3_600_000


def cmd_mode(d, now, force=False):
    pos = positions(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    room, why = pick_room(state, pos, now, force)
    sd = snap_due(d, now)
    due = due_snaps(d, now)
    print(json.dumps({"pick": room > 0, "room": room, "why": why, "scan": "full" if sd else ("light" if room > 0 else "none"), "bigTestSaveDue": sd,
                      "bigTestDue": len(due), "bigTestDueCoins": sum(len(sn["coins"]) for sn in due.values()),
                      "open": sum(1 for p in pos.values() if p["_left"] > 1e-9), "cash": bankroll(pos)}))


def cmd_cash(d):
    print(json.dumps(bankroll(positions(d)), indent=1))


# ---------------------------------------------------------------- gathering pair data from many files
def load_lists(d):
    raw = load_json(os.path.join(d, "lists.json"), {})
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, list):
                out[re.sub(r"[^A-Za-z0-9]", "", str(k))[:16]] = [a.strip() for a in v if isinstance(a, str) and B58.match(a.strip())]
    return out


PIPE_COLS = ("address", "symbol", "name", "dexId", "pairAddress", "priceUsd", "marketCap", "fdv", "liquidityUsd", "volH24", "volH6", "volH1",
             "chgM5", "chgH1", "chgH6", "chgH24", "buysH24", "sellsH24", "buysH6", "sellsH6", "buysH1", "sellsH1", "pairCreatedAt", "boosts",
             "xUrl", "websites", "socials")
PX_COLS = ("address", "priceUsd", "liquidityUsd")          # cheap re-pricing rows: 3 fields
JUP_COLS = ("address", "symbol", "name", "priceUsd", "marketCap", "fdv", "liquidityUsd", "holders", "organic", "top10Pct", "devMints", "verified",
            "createdAt", "chgH1", "chgH6", "chgH24", "buyVol24", "sellVol24", "buysH24", "sellsH24", "traders24", "netBuyers24", "holderChg24",
            "buysH1", "sellsH1", "netBuyers1")
RC_COLS = ("address", "score", "lpLocked", "holders", "top1Pct", "top10Pct", "insiders", "creatorPct", "mutable", "launchpad", "danger", "warn")
RC_COLS13 = RC_COLS + ("topAddrs",)                     # v3: optional 13th field, top holder addresses ; separated
PF_COLS = ("address", "symbol", "name", "usdMc", "mc", "athMc", "replies", "live", "complete", "createdAt", "twitter", "website", "telegram")
GT_COLS = ("address", "symbol", "name", "poolAddress", "dexId", "priceUsd", "fdv", "liquidityUsd", "volH24", "chgH1", "chgH6", "chgH24",
           "buysH24", "sellsH24", "buyers24", "sellers24", "createdAt")
GM_COLS = ("address", "symbol", "name", "priceUsd", "marketCap", "liquidityUsd", "volH24", "holders", "top10", "smartDegen", "renowned", "sniper",
           "bundler", "rat", "bluechip", "rugRatio", "wash", "hot", "devHold", "sniperHold", "botDegen", "honeypot", "creatorStatus", "twRename",
           "openTs", "launchpad")
TB_COLS = ("address", "status", "tags", "makerTags")                       # tb/<coin>.txt: address here is the WALLET
TEXT_COLS = {"address", "symbol", "name", "dexId", "pairAddress", "poolAddress", "xUrl", "twitter", "website", "telegram", "createdAt", "launchpad",
             "danger", "warn", "topAddrs", "creatorStatus", "status", "tags", "makerTags"}
CURVE_DEX = re.compile(r"pumpfun|dbc|launchlab|boop|moonit|curve", re.I)
NOT_MEME = re.compile(r"xstock|securities|tokenized|wrapped|wormhole|staked|\bst[A-Z]|liquid stak|tether|usd[ct]?\b|\bpyusd|stablecoin|xaut|cbbtc|wbtc|weth", re.I)


def to_num(v):
    v = v.replace("−", "-").replace(",", "").replace("$", "").rstrip("%").strip()
    if v.lower() in ("true", "yes"):
        return 1.0
    if v.lower() in ("false", "no"):
        return 0.0
    return num(v)


def parse_ms(v):
    """Milliseconds from a number (ms or s) or an ISO date string; None otherwise."""
    if v is None:
        return None
    x = num(v)
    if x is not None:
        return x * 1000 if x < 1e11 else x
    try:
        s = str(v).strip().replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s).timestamp() * 1000
    except (ValueError, TypeError):
        return None


def pipe_rows(fn, cols):
    """Plain text file: one row per line, len(cols) fields separated by |. Rows with the wrong field count are skipped."""
    out = []
    try:
        with open(fn) as f:
            for line in f:
                parts = [p.strip() for p in line.strip().strip("`").split("|")]
                if len(parts) != len(cols) or not B58.match(parts[0]):
                    continue
                row = {}
                for k, v in zip(cols, parts):
                    if v.lower() in ("", "null", "none", "n/a", "-", "undefined"):
                        row[k] = None
                    elif k in TEXT_COLS:
                        row[k] = v
                    else:
                        row[k] = to_num(v)
                out.append(row)
    except OSError:
        pass
    return out


def load_pair_file(fn):
    """A pairs file is a JSON array of pair objects, or text rows with 27 fields (full pair) or 3 fields (address|price|liquidity)."""
    arr = load_json(fn, None)
    if isinstance(arr, dict):
        arr = arr.get("pairs") or []
    if isinstance(arr, list):
        return arr
    rows = pipe_rows(fn, PIPE_COLS)
    if not rows:
        rows = [dict(r, px_only=True) for r in pipe_rows(fn, PX_COLS)]
    return rows


def jup_pair(j):
    """A Jupiter token row as a pair object (used only when DexScreener has no pair for the coin)."""
    vol = (j.get("buyVol24") or 0) + (j.get("sellVol24") or 0)
    return {"address": j["address"], "symbol": j.get("symbol"), "name": j.get("name"), "dexId": "jupiter", "pairAddress": None,
            "priceUsd": j.get("priceUsd"), "marketCap": j.get("marketCap"), "fdv": j.get("fdv"), "liquidityUsd": j.get("liquidityUsd"),
            "volH24": vol or None, "chgH1": j.get("chgH1"), "chgH6": j.get("chgH6"), "chgH24": j.get("chgH24"),
            "buysH24": j.get("buysH24"), "sellsH24": j.get("sellsH24"), "buysH1": j.get("buysH1"), "sellsH1": j.get("sellsH1"),
            "pairCreatedAt": parse_ms(j.get("createdAt")), "xUrl": None}


def merge_pairs(d):
    """Every pairs/* file -> best DexScreener pair per token (price-only rows fill in when nothing better exists), plus how many
    pairs/DEXes were seen and which search files listed it."""
    best, npairs, dexes, tags = {}, {}, {}, {}
    files = sorted(glob.glob(os.path.join(d, "pairs", "*.json")) + glob.glob(os.path.join(d, "pairs", "*.txt")))
    for fn in files:
        arr = load_pair_file(fn)
        base = os.path.splitext(os.path.basename(fn))[0]
        tag = ("kw:" + base[7:].lower()[:14]) if base.startswith("search_") else None
        for p in arr if isinstance(arr, list) else []:
            if not isinstance(p, dict):
                continue
            a = str(p.get("address") or "").strip()
            if not B58.match(a) or str(p.get("chainId") or "solana").lower() != "solana":
                continue
            prev = best.get(a)
            if p.get("px_only"):
                if prev is None:
                    best[a] = dict(p)
                elif prev.get("px_only") and (num(p.get("liquidityUsd")) or 0) > (num(prev.get("liquidityUsd")) or 0):
                    best[a] = dict(p)
                continue
            npairs[a] = npairs.get(a, 0) + 1
            dexes.setdefault(a, set()).add(str(p.get("dexId") or "?").lower())
            if tag:
                tags.setdefault(a, set()).add(tag)
            if prev is None or prev.get("px_only") or (num(p.get("liquidityUsd")) or 0) > (num(prev.get("liquidityUsd")) or 0):
                best[a] = dict(p)
    for a, p in best.items():
        p["address"] = a
        if a in npairs:
            p["nPairs"] = npairs[a]
            p["nDex"] = len(dexes[a])
    return best, tags, len(files)


def load_side(d, sub, cols):
    """jup/*.txt or pf/*.txt rows -> {address: row}, keeping the row with the most filled fields; tags per file name."""
    rows, tags = {}, {}
    for fn in sorted(glob.glob(os.path.join(d, sub, "*.txt"))):
        base = os.path.splitext(os.path.basename(fn))[0]
        for r in pipe_rows(fn, cols):
            a = r["address"]
            tags.setdefault(a, set()).add("%s:%s" % (sub, base[:16]))
            prev = rows.get(a)
            if prev is None or sum(v is not None for v in r.values()) > sum(v is not None for v in prev.values()):
                rows[a] = r
    return rows, tags


def gt_pair(g):
    """A GeckoTerminal pool row as a pair object (used only when DexScreener has no pair for the coin)."""
    return {"address": g["address"], "symbol": g.get("symbol"), "name": g.get("name"), "dexId": str(g.get("dexId") or "geckoterminal"),
            "pairAddress": g.get("poolAddress"), "priceUsd": g.get("priceUsd"), "marketCap": g.get("fdv"), "fdv": g.get("fdv"),
            "liquidityUsd": g.get("liquidityUsd"), "volH24": g.get("volH24"), "chgH1": g.get("chgH1"), "chgH6": g.get("chgH6"), "chgH24": g.get("chgH24"),
            "buysH24": g.get("buysH24"), "sellsH24": g.get("sellsH24"), "pairCreatedAt": parse_ms(g.get("createdAt")), "xUrl": None, "gt_only": True}


def gm_pair(g):
    """A GMGN token row as a pair object (used only when no DEX source has the coin)."""
    return {"address": g["address"], "symbol": g.get("symbol"), "name": g.get("name"), "dexId": "gmgn", "pairAddress": None,
            "priceUsd": g.get("priceUsd"), "marketCap": g.get("marketCap"), "fdv": g.get("marketCap"), "liquidityUsd": g.get("liquidityUsd"),
            "volH24": g.get("volH24"), "pairCreatedAt": parse_ms(g.get("openTs")), "xUrl": None, "gm_only": True}


def cmd_gather(d, now):
    pos = positions(d)
    lists = load_lists(d)
    best, tags, nfiles = merge_pairs(d)
    jup, jtags = load_side(d, "jup", JUP_COLS)
    pf, ptags = load_side(d, "pf", PF_COLS)
    gt, gtags = load_side(d, "gt", GT_COLS)
    gm, mtags = load_side(d, "gm", GM_COLS)
    for src in (jtags, ptags, gtags, mtags):
        for a, t in src.items():
            tags.setdefault(a, set()).update(t)
    for name, addrs in lists.items():
        for a in addrs:
            tags.setdefault(a, set()).add("list:" + name)
    # Jupiter data stands in for a missing DexScreener pair; pump.fun rows only add facts (their market caps are not trusted)
    for a, j in jup.items():
        if a not in best or best[a].get("px_only"):
            best[a] = jup_pair(j)
    for a, g in gt.items():                   # GeckoTerminal pool data stands in when neither DexScreener nor Jupiter has the coin
        if a not in best or best[a].get("px_only"):
            best[a] = gt_pair(g)
    for a, g in gm.items():                   # GMGN likewise, last resort
        if a not in best or best[a].get("px_only"):
            best[a] = gm_pair(g)
    universe = {a: sorted(t) for a, t in tags.items()}
    for a in best:
        universe.setdefault(a, [])
    for a, p in best.items():
        p["tags"] = universe.get(a, [])
        if a in jup:
            p["jup"] = {k: jup[a].get(k) for k in ("holders", "organic", "top10Pct", "devMints", "verified", "traders24", "netBuyers24", "holderChg24", "netBuyers1", "buyVol24", "sellVol24")}
        if a in pf:
            p["pf"] = {k: pf[a].get(k) for k in ("mc", "athMc", "replies", "live", "complete", "createdAt", "twitter", "website", "telegram")}
        if a in gt:
            p["gt"] = {k: gt[a].get(k) for k in ("buyers24", "sellers24", "buysH24", "sellsH24", "volH24", "liquidityUsd", "chgH24")}
        if a in gm:
            p["gm"] = {k: gm[a].get(k) for k in ("holders", "top10", "smartDegen", "renowned", "sniper", "bundler", "rat", "bluechip", "rugRatio", "wash",
                                                 "hot", "devHold", "sniperHold", "botDegen", "honeypot", "creatorStatus", "twRename", "launchpad")}
    with open(os.path.join(d, "pairs.json"), "w") as f:
        json.dump(list(best.values()), f, separators=(",", ":"))
    with open(os.path.join(d, "universe.json"), "w") as f:
        json.dump(universe, f, separators=(",", ":"))
    held = [p["addr"] for p in pos.values() if p["_left"] > 1e-9 and B58.match(str(p.get("addr", "")))]
    due = []
    for sn in due_snaps(d, now).values():
        due += [str(c.get("a")) for c in sn["coins"] if isinstance(c, dict) and B58.match(str(c.get("a", "")))]
    listed = [a for addrs in lists.values() for a in addrs] + sorted(pf) + sorted(jup) + sorted(gt) + sorted(gm)
    full = {a for a, p in best.items() if not p.get("px_only") and p.get("dexId") != "jupiter" and not p.get("gt_only") and not p.get("gm_only")}
    need, seen = [], set()
    for a in held + due + listed:
        if a in seen:
            continue
        seen.add(a)
        if (a in held or a in due) and a not in best:
            need.append(a)                    # open trades and due big-test coins only need a price
        elif a not in held and a not in due and a not in full:
            need.append(a)                    # everything else wants full DexScreener data
    # coverage = how much of what the run asked for came back; pump.fun-only coins often have no DEX pair at all,
    # so they do not count against it
    wanted = set(held) | set(due) | {a for addrs in lists.values() for a in addrs} | set(jup) | set(gt) | set(gm)
    covered = sum(1 for a in wanted if a in best)
    chunks = [",".join(need[i:i + 4]) for i in range(0, len(need), 4)]
    news = load_news(d, now)
    print(json.dumps({"files": nfiles, "coins": len(best), "fullData": len(full), "jupiter": len(jup), "pumpfun": len(pf), "geckoterminal": len(gt),
                      "gmgn": len(gm), "topBuyerFiles": len(load_top_buyers(d)), "leaderboardWallets": len(load_leaderboard(d)),
                      "coingecko": len(load_cg(d)), "news": len(news["items"]), "newsTopWords": news["top"][:12], "smartWallets": len(wallet_table(d)),
                      "lists": {k: len(v) for k, v in lists.items()},
                      "heldMissing": [a for a in held if a not in best], "dueMissing": sum(1 for a in set(due) if a not in best),
                      "wanted": len(wanted), "covered": covered, "coverage": round(covered / len(wanted), 3) if wanted else 1.0,
                      "missing": len(need), "chunks": chunks}, indent=1))


# ---------------------------------------------------------------- factors
def load_pairs(d):
    out = {}
    for p in load_json(os.path.join(d, "pairs.json"), []):
        if isinstance(p, dict) and B58.match(str(p.get("address") or "")):
            out[p["address"]] = p
    return out


def load_social(d):
    raw = load_json(os.path.join(d, "social.json"), [])
    if isinstance(raw, dict):
        raw = [dict(v, symbol=k) if isinstance(v, dict) else {} for k, v in raw.items()]
    by_sym = {}
    cols = ("symbol", "name", "engagements", "mentions", "creators", "sentiment", "galaxy", "altRank")
    for s in raw if isinstance(raw, list) else []:
        if isinstance(s, list) and len(s) >= 3:          # compact row: [symbol, name, engagements, mentions, creators, sentiment, galaxy, altRank]
            s = dict(zip(cols, s))
        if not isinstance(s, dict):
            continue
        sym = re.sub(r"[^a-z0-9]", "", str(s.get("symbol") or "").lower())
        if sym:
            prev = by_sym.get(sym)
            if prev is None or (num(s.get("engagements")) or 0) > (num(prev.get("engagements")) or 0):
                by_sym[sym] = s
    return by_sym


def load_risk(d):
    """RugCheck facts: risk.json ({address: {...}} or a list) plus risk/*.txt rows of 12 fields
    (mint|score|lpLockedPct|holders|top1Pct|top10Pct|insiders|creatorPct|mutable|launchpad|danger names ; separated|warn names)
    or 13 fields (the same plus the top holder addresses ; separated)."""
    raw = load_json(os.path.join(d, "risk.json"), {})
    if isinstance(raw, list):
        raw = {str(o.get("address") or "").strip(): o for o in raw if isinstance(o, dict)}
    out = {str(k).strip(): v for k, v in (raw or {}).items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
    split = lambda v: [x.strip()[:60] for x in str(v or "").split(";") if x.strip() and x.strip().lower() not in ("none", "null")]
    for fn in sorted(glob.glob(os.path.join(d, "risk", "*.txt"))):
        for r in pipe_rows(fn, RC_COLS) + pipe_rows(fn, RC_COLS13):
            r["danger"], r["warn"] = split(r.get("danger")), split(r.get("warn"))
            r["mutable"] = bool(r.get("mutable"))
            r["holdersTop"] = [a for a in split(r.get("topAddrs")) if B58.match(a)][:12]
            out[r["address"]] = r
    return out


# ---------------------------------------------------------------- v3 knowledge: news, CoinGecko, smart wallets
def words(s):
    """Lower-case theme words of a coin name or headline: letters/digits, 3+ chars, no stop words."""
    return [w for w in re.findall(r"[a-z0-9]{3,}", str(s or "").lower()) if w not in NEWS_STOP]


def load_news(d, now):
    """news.json -> {"items": [(text_lower, age_h)], "top": [...], "heat": {word: share of headlines}}. Rows [text, source, time] or dicts."""
    raw = load_json(os.path.join(d, "news.json"), [])
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("news") or []
    items = []
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, list) and r:
            text, at = r[0], r[2] if len(r) > 2 else None
        elif isinstance(r, dict):
            text, at = r.get("t") or r.get("title") or r.get("text"), r.get("at") or r.get("time") or r.get("ts")
        else:
            continue
        text = str(text or "").strip().lower()
        if not text:
            continue
        ms = parse_ms(at)
        age = (now - ms) / 3_600_000 if ms and ms > 1e12 else None
        if age is not None and (age > NEWS_MAX_AGE_H or age < -2):
            continue
        items.append((text[:400], age))
    heat = {}
    for text, _ in items:
        for w in set(words(text)):
            heat[w] = heat.get(w, 0) + 1
    n = max(len(items), 1)
    heat = {w: c / n for w, c in heat.items()}
    top = [w for w, _ in sorted(heat.items(), key=lambda kv: -kv[1])]
    return {"items": items, "heat": heat, "top": top}


def news_for(pr, news):
    """news.hits = headlines naming the coin ($SYM, the symbol as a word, or the full name); news.fresh = 1/(1+hours since the newest hit);
    news.narr = average heat of the coin's own theme words across all headlines (0 when the words appear nowhere)."""
    items = news["items"]
    if not items:
        return {}
    sym = re.sub(r"[^a-z0-9]", "", str(pr.get("symbol") or "").lower())
    name = re.sub(r"\s+", " ", str(pr.get("name") or "").strip().lower())
    pats = []
    if sym:
        pats.append(re.compile(r"\$" + re.escape(sym) + r"\b"))
        if len(sym) >= 4 and sym not in NEWS_STOP:
            pats.append(re.compile(r"\b" + re.escape(sym) + r"\b"))
    if len(name) >= 5 and name != sym and not all(w in NEWS_STOP for w in name.split()):
        pats.append(re.compile(r"\b" + re.escape(name) + r"\b"))
    hits, newest = 0, None
    if pats:
        for text, age in items:
            if any(p.search(text) for p in pats):
                hits += 1
                if age is not None and (newest is None or age < newest):
                    newest = age
    f = {"news.hits": float(hits)}
    if hits:
        f["news.fresh"] = 1.0 / (1.0 + max(newest, 0.0)) if newest is not None else 0.5
    ws = set(words(name)) | ({sym} if sym and len(sym) >= 4 and sym not in NEWS_STOP else set())
    if ws:
        f["news.narr"] = sum(news["heat"].get(w, 0.0) for w in ws) / len(ws)
    return f


def load_cg(d):
    """cg.json -> {ticker: {"rank", "chg24", "mcRank"}}: CoinGecko trending rows [symbol, name, rank(, chg24, marketCapRank)] or dicts."""
    raw = load_json(os.path.join(d, "cg.json"), [])
    if isinstance(raw, dict):
        raw = raw.get("coins") or raw.get("items") or []
    out = {}
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(r, list) and len(r) >= 2:
            r = dict(zip(("symbol", "name", "rank", "chg24", "mcRank"), r))
        if not isinstance(r, dict):
            continue
        sym = re.sub(r"[^a-z0-9]", "", str(r.get("symbol") or "").lower())
        if sym and sym not in out:
            out[sym] = {"name": r.get("name"), "rank": num(r.get("rank")) or float(i + 1), "chg24": num(r.get("chg24")), "mcRank": num(r.get("mcRank"))}
    return out


def wallet_table(d):
    """Smart-wallet memory: every scored big-test coin whose RugCheck report listed its top holders credits those wallets with the
    coin's clipped 24h result. Returns {wallet: {"n": coins, "avg": mean eur, "wins": share > 0}} for wallets with >= SW_MIN_COINS coins."""
    acc = {}
    for doc in load_docs(d, "memesnapres").values():
        for c in doc.get("coins") or []:
            if not isinstance(c, dict) or num(c.get("eur")) is None:
                continue
            holders = (c.get("rc") or {}).get("holders") if isinstance(c.get("rc"), dict) else None
            eur = clamp(num(c["eur"]), EUR_CLIP[0], EUR_CLIP[1])
            for wlt in holders or []:
                if isinstance(wlt, str) and B58.match(wlt):
                    a = acc.setdefault(wlt, [0, 0.0, 0])
                    a[0] += 1; a[1] += eur; a[2] += 1 if eur > 0 else 0
    return {w: {"n": n, "avg": round(s / n, 2), "wins": round(k / n, 3)} for w, (n, s, k) in acc.items() if n >= SW_MIN_COINS}


def wallets_for(holders, table):
    """sw.n = how many of the coin's known holders have a record; sw.avg = their mean past result per 20 euros; sw.wins = their win share."""
    if not holders or not table:
        return {}
    known = [table[w] for w in holders if w in table]
    f = {"sw.n": float(len(known))}
    if known:
        f["sw.avg"] = sum(k["avg"] for k in known) / len(known)
        f["sw.wins"] = sum(k["wins"] for k in known) / len(known)
    return f


# ---------------------------------------------------------------- v4 traders: GMGN top buyers and the wallet leaderboard
def split_tags(v):
    return [x.strip().lower() for x in str(v or "").split(";") if x.strip() and x.strip().lower() not in ("none", "null")]


def load_top_buyers(d):
    """tb/<coin address>.txt -> {coin: [{"wallet", "status", "tags"}]}; the file name is the coin, each row a wallet."""
    out = {}
    for fn in sorted(glob.glob(os.path.join(d, "tb", "*.txt")))[:TB_MAX_FILES]:
        coin = os.path.splitext(os.path.basename(fn))[0]
        if not B58.match(coin):
            continue
        rows = [{"wallet": r["address"], "status": str(r.get("status") or "").lower(), "tags": split_tags(r.get("tags")) + split_tags(r.get("makerTags"))}
                for r in pipe_rows(fn, TB_COLS)]
        if rows:
            out[coin] = rows[:100]
    return out


def load_leaderboard(d):
    """wallets.json -> {wallet: {"pnl", "win", "tags"}}: GMGN's most profitable wallets (rows [wallet, pnl, winrate, tags] or dicts)."""
    raw = load_json(os.path.join(d, "wallets.json"), [])
    if isinstance(raw, dict):
        raw = raw.get("rank") or raw.get("wallets") or raw.get("data") or []
    out = {}
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, list) and r:
            r = dict(zip(("wallet_address", "pnl", "winrate", "tags"), r))
        if not isinstance(r, dict):
            continue
        w = str(r.get("wallet_address") or r.get("wallet") or r.get("address") or "").strip()
        if not B58.match(w):
            continue
        pnl = num(r.get("pnl")) if r.get("pnl") is not None else num(r.get("pnl_7d") if r.get("pnl_7d") is not None else r.get("pnl_30d"))
        win = num(r.get("winrate")) if r.get("winrate") is not None else num(r.get("winrate_7d") if r.get("winrate_7d") is not None else r.get("winrate_30d"))
        tags = r.get("tags")
        tags = split_tags(";".join(tags)) if isinstance(tags, list) else split_tags(tags)
        prev = out.get(w)
        if prev is None or (pnl or 0) > (prev["pnl"] or 0):
            out[w] = {"pnl": pnl, "win": win, "tags": tags}
    return out


def holding(r):
    return r["status"] in ("hold", "bought_more", "holding")


def top_buyer_feats(rows, board):
    """tb.* factors from a coin's top buyers, plus sw.lb* from the leaderboard wallets among those still holding."""
    if not rows:
        return {}, []
    n = float(len(rows))
    hold = [r for r in rows if holding(r)]
    smart = [r for r in rows if any(SMART_TAGS.search(t) for t in r["tags"])]
    f = {"tb.n": n, "tb.holdShare": len(hold) / n, "tb.soldShare": sum(1 for r in rows if r["status"].startswith("sold")) / n,
         "tb.sniperShare": sum(1 for r in rows if "sniper" in r["tags"]) / n, "tb.freshShare": sum(1 for r in rows if "fresh_wallet" in r["tags"]) / n,
         "tb.botShare": sum(1 for r in rows if any(BOT_TAGS.search(t) for t in r["tags"])) / n,
         "tb.smartN": float(len(smart)), "tb.smartHold": float(sum(1 for r in smart if holding(r)))}
    if board:
        lb = [board[r["wallet"]] for r in hold if r["wallet"] in board]
        f["sw.lb"] = float(len(lb))
        if lb:
            wins = [x["win"] for x in lb if x["win"] is not None]
            if wins:
                f["sw.lbWin"] = sum(wins) / len(wins)
    return f, [r["wallet"] for r in hold]


def names(r, k):
    return [str(x.get("name") if isinstance(x, dict) else x)[:60] for x in (r.get(k) or []) if x][:8]


def social_for(pr, soc):
    """LunarCrush buzz matched by ticker: match 2 = symbol and name agree, 1 = symbol only, 0 = none."""
    sym = re.sub(r"[^a-z0-9]", "", str(pr.get("symbol") or "").lower())
    s = soc.get(sym) if sym else None
    if not s:
        return None, 0
    n1, n2 = re.sub(r"[^a-z0-9]", "", str(pr.get("name") or "").lower()), re.sub(r"[^a-z0-9]", "", str(s.get("name") or "").lower())
    return s, 2 if (n1 and n2 and (n1 == n2 or n1 in n2 or n2 in n1)) else 1


def feats(pr, now, soc=None, rc=None, news=None, cg=None, wallets=None, tb=None, board=None):
    """Every number the bot knows about a coin right now, as named factors (None = unknown)."""
    g = lambda k: num(pr.get(k))
    price, mc, liq = g("priceUsd"), g("marketCap") or g("fdv"), g("liquidityUsd")
    vol24, vol6, vol1 = g("volH24"), g("volH6"), g("volH1")
    b24, s24, b6, s6, b1, s1 = (g(k) or 0 for k in ("buysH24", "sellsH24", "buysH6", "sellsH6", "buysH1", "sellsH1"))
    born = g("pairCreatedAt")
    age_h = (now - born) / 3_600_000 if born and born > 1e12 else None
    f = {"c1": g("chgH1"), "c6": g("chgH6"), "c24": g("chgH24"), "m5": g("chgM5"), "ageH": age_h,
         "buyShare": b24 / (b24 + s24) if b24 + s24 > 0 else None, "buyRatio1h": b1 / max(s1, 1.0) if b1 + s1 > 0 else None,
         "buyRatio6h": b6 / max(s6, 1.0) if b6 + s6 > 0 else None, "buys1": b1 if b1 + s1 > 0 else None, "buys24": b24 if b24 + s24 > 0 else None,
         "liqMc": liq / mc if liq and mc else None, "volMc": vol24 / mc if vol24 and mc else None,
         "vol1Share": vol1 / vol24 if vol1 is not None and vol24 else None, "vol6Share": vol6 / vol24 if vol6 is not None and vol24 else None,
         "logMc": math.log10(mc) if mc and mc > 0 else None, "logLiq": math.log10(liq) if liq and liq > 0 else None,
         "fdvMc": g("fdv") / mc if g("fdv") and mc else None, "boosts": g("boosts") or 0.0, "nPairs": g("nPairs"), "nDex": g("nDex"),
         "x": 1.0 if x_link(pr) else 0.0, "web": g("websites"), "socN": g("socials")}
    tags = pr.get("tags") or []
    f["srcN"] = float(len(tags))
    f["kwN"] = float(sum(1 for t in tags if t.startswith("kw:")))
    for t in tags:
        if t.startswith("list:") or t.startswith("jup:"):
            f["src." + t.replace("list:", "")] = 1.0
    f["src.pf"] = 1.0 if any(t.startswith("pf:") for t in tags) else 0.0
    j = pr.get("jup") or {}
    if j:
        for k in ("holders", "organic", "top10Pct", "devMints", "verified", "traders24", "netBuyers24", "holderChg24", "netBuyers1"):
            f["jup." + k] = num(j.get(k))
        bv, sv = num(j.get("buyVol24")), num(j.get("sellVol24"))
        f["jup.buyVolShare"] = bv / (bv + sv) if bv is not None and sv is not None and bv + sv > 0 else None
        if f.get("jup.holders") and mc:
            f["jup.mcPerHolder"] = mc / f["jup.holders"]
    p = pr.get("pf") or {}
    if p:
        f["pf.replies"] = num(p.get("replies"))
        f["pf.live"] = num(p.get("live"))
        if num(p.get("athMc")) and num(p.get("mc")) and num(p.get("mc")) > 0:
            f["pf.athRatio"] = num(p.get("athMc")) / num(p.get("mc"))
        f["pf.twitter"] = 1.0 if p.get("twitter") else 0.0
        f["pf.website"] = 1.0 if p.get("website") else 0.0
        f["pf.telegram"] = 1.0 if p.get("telegram") else 0.0
        born_pf = parse_ms(p.get("createdAt"))
        if born_pf and age_h is None:
            f["ageH"] = (now - born_pf) / 3_600_000
    if soc is not None:
        s, match = social_for(pr, soc)
        f["soc.match"] = float(match)
        if s and match:
            for k, src in (("eng", "engagements"), ("ment", "mentions"), ("cre", "creators"), ("sent", "sentiment"), ("galaxy", "galaxy"), ("alt", "altRank")):
                f["soc." + k] = num(s.get(src))
    if isinstance(rc, dict):
        for k, src in (("score", "score"), ("lp", "lpLocked"), ("top1", "top1Pct"), ("top10", "top10Pct"), ("holders", "holders"),
                       ("insiders", "insiders"), ("creator", "creatorPct")):
            f["rc." + k] = num(rc.get(src))
        f["rc.danger"], f["rc.warn"] = float(len(names(rc, "danger"))), float(len(names(rc, "warn")))
        f["rc.mutable"] = 1.0 if rc.get("mutable") else 0.0
    # ---- v3 knowledge ----
    gt = pr.get("gt") or {}
    if gt:
        by, sl = num(gt.get("buyers24")), num(gt.get("sellers24"))
        f["gt.buyers24"], f["gt.sellers24"] = by, sl
        f["gt.buyerRatio"] = by / max(sl, 1.0) if by is not None and sl is not None and by + sl > 0 else None
        gb, gs = num(gt.get("buysH24")), num(gt.get("sellsH24"))
        if by and gb:
            f["gt.buysPerBuyer"] = gb / by           # many trades from few wallets = bots / wash trading
        f["gt.trend"] = 1.0
    f["gt.src"] = float(sum(1 for t in tags if t.startswith("gt:")))
    if news is not None:
        f.update(news_for(pr, news))
    if cg is not None:
        sym = re.sub(r"[^a-z0-9]", "", str(pr.get("symbol") or "").lower())
        c = cg.get(sym) if sym else None
        f["cg.trend"] = 1.0 if c else 0.0
        if c:
            f["cg.rank"] = c.get("rank")
            f["cg.chg24"] = c.get("chg24")
    # ---- v4 traders ----
    gm = pr.get("gm") or {}
    if gm:
        for k in ("holders", "top10", "smartDegen", "renowned", "sniper", "bundler", "rat", "bluechip", "rugRatio", "hot", "devHold", "sniperHold", "botDegen", "twRename"):
            f["gm." + k] = num(gm.get(k))
        f["gm.wash"] = 1.0 if num(gm.get("wash")) else 0.0
        f["gm.honeypot"] = 1.0 if num(gm.get("honeypot")) else 0.0
        f["gm.creatorHold"] = 1.0 if "hold" in str(gm.get("creatorStatus") or "").lower() else 0.0
        if f.get("gm.holders") and f.get("gm.smartDegen") is not None:
            f["gm.smartShare"] = f["gm.smartDegen"] / f["gm.holders"]
    f["gm.src"] = float(sum(1 for t in tags if t.startswith("gm:")))
    holders = list((rc or {}).get("holdersTop") or []) if isinstance(rc, dict) else []
    if tb:
        tf, tb_hold = top_buyer_feats(tb, board)
        f.update(tf)
        holders += [w for w in tb_hold if w not in holders]
    if wallets is not None and holders:
        f.update(wallets_for(holders, wallets))
    return {k: v for k, v in f.items() if v is not None}, {"price": price, "mc": mc, "liq": liq, "vol24": vol24, "age_h": age_h, "holders": holders[:40]}


def gates(pr, basic, sym_mc):
    price, mc, liq, vol24, age_h = basic["price"], basic["mc"], basic["liq"], basic["vol24"], basic["age_h"]
    fails = []
    if not price or price <= 0: fails.append("price")
    if CURVE_DEX.search(str(pr.get("dexId", ""))): fails.append("curve")
    if str(pr.get("dexId", "")).lower() == "jupiter" or pr.get("gt_only") or pr.get("gm_only"): fails.append("nodex")      # known only from a list: no DexScreener pair data to trade on
    if num((pr.get("gm") or {}).get("honeypot")): fails.append("honeypot")                              # GMGN says it cannot be sold
    if NOT_MEME.search(str(pr.get("name", "")) + " " + str(pr.get("symbol", ""))): fails.append("notmeme")   # tokenized stocks, wrapped and staked assets, stablecoins
    if age_h is None or age_h < GATE_MIN_AGE_H: fails.append("young")
    if not liq or liq < GATE_MIN_LIQ: fails.append("liq")
    if not mc or not (GATE_MC[0] <= mc <= GATE_MC[1]): fails.append("mc")
    if not vol24 or vol24 < GATE_MIN_VOL24: fails.append("vol")
    s = str(pr.get("symbol") or "").upper()
    if mc and mc * 3 <= sym_mc.get(s, 0): fails.append("copy")
    return fails


FAIL_TEXT = {"price": "no price", "curve": "still on its launch curve", "nodex": "no DEX pair data (Jupiter, GeckoTerminal or GMGN list only)", "honeypot": "flagged as a honeypot (GMGN)", "notmeme": "not a meme coin (stock, wrapped or staked asset, stablecoin)", "young": "under an hour old", "liq": "liquidity under $20k",
             "mc": "market cap outside $100k-$50M", "vol": "under $20k traded in 24h", "copy": "copycat of a bigger coin with the same name"}


# ---------------------------------------------------------------- learning the weights
def result_rows(d):
    rows = []
    for doc in load_docs(d, "memesnapres").values():
        for c in doc.get("coins") or []:
            if isinstance(c, dict) and isinstance(c.get("f"), dict) and num(c.get("eur")) is not None:
                rows.append((c["f"], clamp(num(c["eur"]), EUR_CLIP[0], EUR_CLIP[1])))
    return rows


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r, i = [0.0] * len(vals), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def learn(rows):
    """Rank correlation of every factor with the clipped 24h result. Returns (weights, n_rows, detail)."""
    keys = sorted({k for f, _ in rows for k in f if num(f.get(k)) is not None})
    w, detail = {}, {}
    for k in keys:
        pts = [(num(f[k]), e) for f, e in rows if num(f.get(k)) is not None]
        if len(pts) < LEARN_MIN_N:
            continue
        xs = [p[0] for p in pts]
        if min(xs) == max(xs):
            continue
        rho = spearman(xs, [p[1] for p in pts])
        detail[k] = {"n": len(pts), "rho": round(rho, 4)}
        if abs(rho) >= 0.03:
            w[k] = round(rho, 4)
    return w, len(rows), detail


def blended_weights(d):
    """Prior weights, replaced by the learned ones as scored coins pile up. Also returns where they came from."""
    rows = result_rows(d)
    learned, n, detail = learn(rows) if rows else ({}, 0, {})
    lam = clamp(n / float(LEARN_FULL_N))
    w = {}
    for k in set(PRIOR) | set(learned):
        v = (1 - lam) * PRIOR.get(k, 0.0) + lam * learned.get(k, 0.0)
        if abs(v) >= 0.01:
            w[k] = round(v, 4)
    return w, {"n": n, "lambda": round(lam, 3), "learned": learned, "detail": detail}


def score_all(items, w):
    """items: list of (addr, feats). Percentile rank per factor across the scan, weighted sum -> 0..100."""
    if not items:
        return {}
    tot = sum(abs(v) for v in w.values()) or 1.0
    pct = {}
    for k in w:
        have = [(a, num(f.get(k))) for a, f in items if num(f.get(k)) is not None]
        if len(have) < 2:
            continue
        r = ranks([v for _, v in have])
        pct[k] = {a: r[i] / (len(have) - 1) for i, (a, _) in enumerate(have)}
    out = {}
    for a, f in items:
        s = 0.0
        for k, wk in w.items():
            p = pct.get(k, {}).get(a, 0.5)
            s += wk * (2 * p - 1)
        out[a] = round(50 + 50 * s / tot, 1)
    return out


# ---------------------------------------------------------------- the scan
def scan(d, pos, pairs, now, w):
    """Factors, gates and scores for every coin with pair data. Returns rows (best first) and helpers."""
    soc, risk = load_social(d), load_risk(d)
    news, cg, wallets = load_news(d, now), load_cg(d), wallet_table(d)
    tbs, board = load_top_buyers(d), load_leaderboard(d)
    held = {p.get("addr") for p in pos.values() if p["_left"] > 1e-9}
    recent = {p.get("addr") for p in pos.values() if now - (num(p.get("t")) or 0) < REPICK_DAYS * DAY}
    sym_mc = {}
    for a, pr in pairs.items():
        s = str(pr.get("symbol") or "").upper()
        sym_mc[s] = max(sym_mc.get(s, 0), num(pr.get("marketCap")) or 0)
    rows, fail_count = [], {}
    for a, pr in pairs.items():
        if pr.get("px_only"):
            continue                      # price-only rows serve exits and the big test's re-pricing, they are not scanned coins
        f, basic = feats(pr, now, soc, risk.get(a), news, cg, wallets, tbs.get(a), board)
        if isinstance(risk.get(a), dict) and basic.get("holders"):
            risk[a]["holdersTop"] = basic["holders"]        # RugCheck owners + top buyers still holding -> what the wallet memory learns from
        if basic["age_h"] is None and f.get("ageH") is not None:
            basic["age_h"] = f["ageH"]
        fails = gates(pr, basic, sym_mc)
        for x in fails:
            fail_count[x] = fail_count.get(x, 0) + 1
        rows.append({"a": a, "pr": pr, "f": f, "basic": basic, "fails": fails, "ok": not fails})
    sc = score_all([(r["a"], r["f"]) for r in rows], w)
    for r in rows:
        r["sc"] = sc.get(r["a"], 50.0)
    rows.sort(key=lambda r: -r["sc"])
    rank = 0
    for r in rows:
        if r["ok"]:
            rank += 1
            r["rank"] = rank
    return rows, fail_count, held, recent, risk


def risk_view(r):
    """A RugCheck summary -> (True/False/None, text). None means there is no report, so the coin is not bought."""
    if not isinstance(r, dict):
        return None, "no RugCheck report"
    danger = names(r, "danger")
    if danger:
        return False, "RugCheck danger: " + ", ".join(danger[:3])
    warn = names(r, "warn")
    bad = [x for x in warn if RISK_WARN_BLOCK.search(x)]
    if bad:
        return False, "RugCheck warning: " + ", ".join(bad[:2])
    lp = num(r.get("lpLocked"))
    if lp is None or lp < MIN_LP_LOCKED:
        return False, "RugCheck: only %s%% of liquidity locked" % ("?" if lp is None else round(lp))
    top10 = num(r.get("top10Pct"))
    return True, "RugCheck: no danger flags, %d%% of liquidity locked" % round(lp) + (", top 10 wallets hold %d%%" % round(top10) if top10 is not None else "") + \
        (" (warnings: " + ", ".join(warn[:2]) + ")" if warn else "")


def risk_doc(r):
    if not isinstance(r, dict):
        return None
    doc = {"score": num(r.get("score")), "lpLocked": num(r.get("lpLocked")), "danger": names(r, "danger")[:6], "warn": names(r, "warn")[:6]}
    if r.get("holdersTop"):
        doc["holders"] = list(r["holdersTop"])[:40]      # kept in snapshots so scored coins can credit their wallets
    return doc


def cmd_shortlist(d, now, force=False):
    pos, pairs = positions(d), load_pairs(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    room = pick_room(state, pos, now, force)[0]
    w, _ = blended_weights(d)
    rows, _, held, recent, risk = scan(d, pos, pairs, now, w)
    cands = [r for r in rows if r["ok"] and r["a"] not in held and r["a"] not in recent and r["a"] not in risk]
    short = cands[:SHORTLIST] if room > 0 else []
    more = cands[len(short):len(short) + RC_BIG] if snap_due(d, now) else []
    print(json.dumps({"shortlist": [r["a"] for r in short + more], "pick": [r["pr"].get("symbol") for r in short],
                      "n": len(short) + len(more), "gated": sum(1 for r in rows if r["ok"]), "scanned": len(rows)}, indent=1))


def why_text(r):
    f, b = r["f"], r["basic"]
    bits = ["score %.0f/100 (rank %s of the coins that passed the gates)" % (r["sc"], r.get("rank", "?"))]
    if b["liq"] and b["mc"]:
        bits.append("liquidity %d%% of a %s market cap" % (round(100 * b["liq"] / b["mc"]), money(b["mc"])))
    if b["vol24"]:
        bits.append("%s traded in 24h" % money(b["vol24"]))
    if f.get("buyShare") is not None:
        bits.append("%d%% of trades were buys" % round(100 * f["buyShare"]))
    if f.get("c6") is not None:
        bits.append("%+.0f%% in 6h" % f["c6"])
    if b["age_h"] is not None:
        bits.append(("%.0f days old" % (b["age_h"] / 24)) if b["age_h"] >= 48 else ("%.0f hours old" % b["age_h"]))
    if f.get("srcN"):
        bits.append("seen on %d source lists" % f["srcN"])
    if f.get("soc.match") and f.get("soc.eng") is not None:
        bits.append("%s X engagements (LunarCrush)" % (("%.1fM" % (f["soc.eng"] / 1e6)) if f["soc.eng"] >= 1e6 else ("%.0fk" % (f["soc.eng"] / 1e3))))
    if f.get("news.hits"):
        bits.append("named in %d headline%s" % (f["news.hits"], "" if f["news.hits"] == 1 else "s"))
    if f.get("news.narr"):
        bits.append("its theme is in %d%% of today's headlines" % round(100 * f["news.narr"]))
    if f.get("gt.buyers24") is not None and f.get("gt.sellers24") is not None:
        bits.append("%d distinct buyers vs %d sellers in 24h (GeckoTerminal)" % (f["gt.buyers24"], f["gt.sellers24"]))
    if f.get("cg.trend"):
        bits.append("on CoinGecko's trending list")
    if f.get("sw.n"):
        bits.append("%d top wallet%s with a track record (avg %+.1f euros per 20 on past coins)" % (f["sw.n"], "" if f["sw.n"] == 1 else "s", f.get("sw.avg", 0)))
    if f.get("gm.smartDegen") is not None:
        bits.append("%d smart-money and %d renowned wallets hold it (GMGN)" % (f["gm.smartDegen"], f.get("gm.renowned") or 0))
    if f.get("tb.n"):
        bits.append("%d%% of the top %d buyers still hold" % (round(100 * f["tb.holdShare"]), f["tb.n"]) +
                    (", %d of them smart money" % f["tb.smartHold"] if f.get("tb.smartHold") else "") +
                    (", %d from GMGN's top-profit list" % f["sw.lb"] if f.get("sw.lb") else ""))
    for k, txt in (("gm.wash", "wash trading flagged"), ("gm.bundler", "bundled buys %d%%"), ("gm.rat", "rat traders %d%%"), ("gm.sniperHold", "snipers hold %d%%")):
        v = f.get(k)
        if v and (k == "gm.wash" or v >= 0.05):
            bits.append(txt % round(100 * v) if "%d" in txt else txt)
    return ", ".join(bits)


def pos_factors(f):
    """What the page reads from a position's factors, plus everything else (rounded)."""
    out = {}
    for k, v in f.items():
        v = num(v)
        if v is not None:
            out[k] = round(v, 4 if abs(v) < 10 else 2)
    return out


def snap_coin(r, rc):
    f = pos_factors(r["f"])
    c = {"a": r["a"], "s": str(r["pr"].get("symbol") or "?")[:16], "px": r["basic"]["price"], "mc": r["basic"]["mc"], "liq": r["basic"]["liq"],
         "vol": r["basic"]["vol24"], "pass": bool(r["ok"]), "sc": r["sc"], "why": r["fails"][:6], "x": bool(f.get("x")), "f": f,
         "src": (r["pr"].get("tags") or [])[:12]}
    if r.get("rank"):
        c["rank"] = r["rank"]
    if rc:
        c["rc"] = risk_doc(rc)
    return c


def snap_result(c, pairs):
    """What €20 in a coin from the snapshot would be worth 24 hours later, after Fomo-like fees."""
    pr, px0 = pairs.get(c.get("a")), num(c.get("px"))
    price, liq = (num(pr.get("priceUsd")), num(pr.get("liquidityUsd"))) if pr else (None, None)
    gone = not price or (liq is not None and liq < 1000)
    mult = 0.0 if gone or not px0 else price / px0
    invested = TICKET - fee(TICKET)
    gross = invested * mult
    eur = (max(0.0, gross - fee(gross)) if gross > 0 else 0.0) - TICKET
    out = {k: c.get(k) for k in ("a", "s", "pass", "sc", "rank", "why", "x", "f", "rc", "src", "mc", "liq") if c.get(k) is not None}
    out.update({"mult": round(mult, 4), "eur": round(eur, 2), "gone": bool(gone)})
    return out


def curve_point(pos_docs, exit_docs, px, t):
    g = {k: {"net": 0.0, "n": 0} for k in ("pick", "rand", "early", "erand")}
    for pid, p in pos_docs.items():
        grp = p.get("grp")
        if grp not in g or (num(p.get("t")) or 0) > t:
            continue
        ticket, entry = num(p.get("ticket")) or TICKET, num(p.get("px"))
        ex = [e for e in exit_docs.values() if e.get("pos") == pid and (num(e.get("t")) or 0) <= t]
        left = max(0.0, 1.0 - sum(num(e.get("frac")) or 0 for e in ex))
        cash, last, open_val = sum(num(e.get("eur")) or 0 for e in ex), num((px or {}).get(pid)), 0.0
        if left > 1e-6 and last and entry:
            gross = (ticket - fee(ticket)) * left * last / entry
            open_val = max(0.0, gross - fee(gross))
        g[grp]["net"] += cash + open_val - ticket
        g[grp]["n"] += 1
    for v in g.values():
        v["net"] = round(v["net"], 2)
    return {"t": t, "bot": round(g["pick"]["net"] + g["early"]["net"], 2), "rand": round(g["rand"]["net"] + g["erand"]["net"], 2),
            "nBot": g["pick"]["n"] + g["early"]["n"], "nRand": g["rand"]["n"] + g["erand"]["n"], "g": g, "rule": RULE,
            "budget": BUDGET, "equity": round(BUDGET + g["pick"]["net"] + g["early"]["net"], 2)}


# ---------------------------------------------------------------- the run
def cmd_run(d, mode, now, force=False):
    out_dir = os.path.join(d, "out")
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.json")):
        os.remove(old)
    pos, pairs = positions(d), load_pairs(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    marks = load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    miss = dict(marks.get("miss") or {})
    asked = mode
    room = pick_room(state, pos, now, force)[0] if mode == "pick" else 0   # --force: a manual pick run (the bankroll still caps it)
    if mode == "pick" and room <= 0:
        mode = "check"
    n_open = sum(1 for p in pos.values() if p["_left"] > 1e-9)
    writes, exits_done, picks_done, emitted = [], [], [], {}
    run_id = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")

    def emit(coll, doc_id, data):
        fn = os.path.join(out_dir, "%s__%s.json" % (coll, doc_id))
        with open(fn, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        writes.append({"collection": coll, "doc_id": doc_id, "file": fn})
        emitted.setdefault(coll, {})[doc_id] = data

    # ---------- exits ----------
    new_marks = {"t": now, "px": {}, "liq": {}, "miss": {}}
    for pid, p in sorted(pos.items()):
        left = p["_left"]
        if left <= 1e-9:
            continue
        ticket = num(p.get("ticket")) or TICKET
        entry, invested = num(p.get("px")), ticket - fee(ticket)
        pr = pairs.get(p.get("addr"))
        price, liq = (num(pr.get("priceUsd")), num(pr.get("liquidityUsd"))) if pr else (None, None)
        k = len(p["_exits"]) + 1

        def sell(frac, px, why):
            gross = invested * frac * (px / entry) if entry and px else 0.0
            cash = max(0.0, gross - fee(gross)) if gross > 0 else 0.0
            emit("memeexit", "%s-%d" % (pid, k), {"pos": pid, "t": now, "px": px or 0, "frac": round(frac, 6), "why": why,
                                                  "eur": round(cash, 2), "grp": p.get("grp"), "rule": RULE})
            exits_done.append({"id": pid, "sym": p.get("sym"), "grp": p.get("grp"), "why": why, "frac": frac,
                               "eur": round(cash, 2), "mult": (px / entry) if entry and px else 0, "ticket": ticket})

        if not price or not entry:
            miss[pid] = int(miss.get(pid, 0)) + 1
            if miss[pid] >= 2 or (pr and liq is not None and liq < 1000):
                sell(left, 0.0, "rug")
            else:
                new_marks["miss"][pid] = miss[pid]
                new_marks["px"][pid] = (marks.get("px") or {}).get(pid)
            continue
        if liq is not None and liq < 1000:
            sell(left, 0.0, "rug"); continue
        mult, age_d = price / entry, (now - num(p.get("t"))) / DAY
        half_done = any(e.get("why") == "target" for e in p["_exits"])
        if mult <= STOP_MULT:
            sell(left, price, "stop")
        elif not half_done and mult >= TP_MULT:
            sell(0.5, price, "target"); left -= 0.5
            new_marks["px"][pid] = price; new_marks["liq"][pid] = liq
        elif half_done and mult <= 1.0:
            sell(left, price, "back to entry")
        elif age_d >= (num(p.get("maxd")) or MAX_DAYS):
            sell(left, price, "time")
        else:
            new_marks["px"][pid] = price; new_marks["liq"][pid] = liq

    # ---------- scan + picks ----------
    w, winfo = blended_weights(d)
    rows, fail_count, held, recent, risk = scan(d, pos, pairs, now, w)
    gated = [r for r in rows if r["ok"]]
    flagged, unchecked, chosen = [], 0, []
    day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    if mode == "pick":
        for r in gated:
            if r["a"] in held or r["a"] in recent:
                continue
            ok_r, rtxt = risk_view(risk.get(r["a"]))
            if ok_r is None:
                unchecked += 1
                if unchecked > SHORTLIST:
                    break
            elif not ok_r:
                flagged.append({"sym": r["pr"].get("symbol"), "risk": rtxt})
            else:
                chosen.append((r, rtxt))
                if len(chosen) >= room:
                    break
        for r, rtxt in chosen:
            pr, a = r["pr"], r["a"]
            pid = "%s-p-%s-%s" % (day, slug(pr.get("symbol")), a[:6])
            emit("memepos", pid, {"grp": "pick", "addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48],
                                  "pair": pr.get("pairAddress"), "dex": pr.get("dexId"), "t": now, "px": r["basic"]["price"], "mc": r["basic"]["mc"],
                                  "liq": r["basic"]["liq"], "vol": r["basic"]["vol24"], "score": r["sc"], "rank": r.get("rank"),
                                  "why": why_text(r) + "; " + rtxt, "safety": rtxt, "x": x_link(pr), "xKnown": True, "f": pos_factors(r["f"]),
                                  "src": (pr.get("tags") or [])[:12], "risk": risk_doc(risk.get(a)), "ticket": TICKET, "rule": RULE,
                                  "weights": {k: v for k, v in sorted(w.items(), key=lambda kv: -abs(kv[1]))[:12]}})
            picks_done.append({"grp": "pick", "sym": pr.get("symbol"), "name": pr.get("name"), "addr": a, "why": why_text(r) + "; " + rtxt, "score": r["sc"]})
            new_marks["px"][pid] = r["basic"]["price"]; new_marks["liq"][pid] = r["basic"]["liq"]
        # control group (off by default): random coins from the same gated pool, outside the bankroll
        rng = random.Random("%s-%s" % (RULE, run_id))
        taken = {r["a"] for r, _ in chosen}
        pool = sorted(r["a"] for r in gated if r["a"] not in held and r["a"] not in recent and r["a"] not in taken
                      and (r["basic"]["liq"] or 0) >= RAND_MIN_LIQ)
        rng.shuffle(pool)
        by_a = {r["a"]: r for r in rows}
        for a in pool[:min(len(chosen), CONTROL_PICKS)]:
            r, pr = by_a[a], by_a[a]["pr"]
            pid = "%s-r-%s-%s" % (day, slug(pr.get("symbol")), a[:6])
            emit("memepos", pid, {"grp": "rand", "addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48],
                                  "pair": pr.get("pairAddress"), "dex": pr.get("dexId"), "t": now, "px": r["basic"]["price"], "mc": r["basic"]["mc"],
                                  "liq": r["basic"]["liq"], "vol": r["basic"]["vol24"], "score": r["sc"], "rank": r.get("rank"),
                                  "why": "random pick from the same list (control group)", "x": x_link(pr), "xKnown": True, "f": pos_factors(r["f"]),
                                  "src": (pr.get("tags") or [])[:12], "risk": risk_doc(risk.get(a)), "ticket": TICKET, "rule": RULE})
            picks_done.append({"grp": "rand", "sym": pr.get("symbol"), "name": pr.get("name"), "addr": a, "score": r["sc"]})
            new_marks["px"][pid] = r["basic"]["price"]; new_marks["liq"][pid] = r["basic"]["liq"]

    # ---------- big test: snapshot every scanned coin (in chunks), price older snapshots again after 24 hours ----------
    snap_n, big, scored_n = 0, [], 0
    if rows and snap_due(d, now):
        coins = [snap_coin(r, risk.get(r["a"])) for r in rows if r["basic"]["price"]]
        for k in range(0, len(coins), SNAP_CHUNK):
            part = coins[k:k + SNAP_CHUNK]
            emit("memesnap", "%s-%d" % (run_id, k // SNAP_CHUNK + 1), {"t": now, "rule": RULE, "n": len(part), "part": k // SNAP_CHUNK + 1,
                                                                        "total": len(coins), "coins": part})
        snap_n = len(coins)
    for sid, sn in due_snaps(d, now).items():
        res = [snap_result(c, pairs) for c in sn["coins"] if isinstance(c, dict)]
        if not res:
            continue
        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
        p_ok, p_no = [r["eur"] for r in res if r["pass"]], [r["eur"] for r in res if not r["pass"]]
        top = [r["eur"] for r in res if r.get("rank") and r["rank"] <= 10]
        emit("memesnapres", sid, {"t": now, "t0": num(sn.get("t")), "rule": sn.get("rule"), "n": len(res), "passN": len(p_ok), "passAvg": avg(p_ok),
                                  "failN": len(p_no), "failAvg": avg(p_no), "top10N": len(top), "top10Avg": avg(top), "coins": res})
        big.append((len(res), avg(p_ok), len(p_ok), avg(p_no), len(top), avg(top)))
        scored_n += len(res)
    if scored_n:
        # new results -> re-learn and save the weights the next runs will use
        all_res = dict(load_docs(d, "memesnapres")); all_res.update(emitted.get("memesnapres", {}))
        rows_l = [(c["f"], clamp(num(c["eur"]), EUR_CLIP[0], EUR_CLIP[1])) for doc in all_res.values() for c in (doc.get("coins") or [])
                  if isinstance(c, dict) and isinstance(c.get("f"), dict) and num(c.get("eur")) is not None]
        learned, n_l, detail = learn(rows_l)
        emit("memeweights", run_id, {"t": now, "rule": RULE, "n": n_l, "lambda": round(clamp(n_l / float(LEARN_FULL_N)), 3), "learned": learned,
                                     "prior": PRIOR, "detail": {k: v for k, v in sorted(detail.items(), key=lambda kv: -abs(kv[1]["rho"]))[:40]}})

    # ---------- note, state, marks, run log ----------
    parts = []
    top_fail = sorted(fail_count.items(), key=lambda x: -x[1])[:3]
    if mode == "pick":
        parts.append("Scanned %d coins from %d sources; %d passed the gates." % (len(rows), len(load_lists(d)) + sum(1 for t in {t for r in rows for t in (r["pr"].get("tags") or [])} if t.startswith("kw:")), len(gated)))
        if top_fail:
            parts.append("Most common gate: " + "; ".join("%s (%d)" % (FAIL_TEXT.get(k2, k2), v) for k2, v in top_fail) + ".")
        if flagged:
            parts.append("RugCheck flagged %s, so %s skipped." % (", ".join("%s (%s)" % (x["sym"], re.sub(r"^RugCheck( danger| warning)?: ", "", x["risk"])) for x in flagged[:3]),
                                                                  "it was" if len(flagged) == 1 else "they were"))
        ps = [x for x in picks_done if x["grp"] == "pick"]
        if ps:
            parts.append("Picked " + ", ".join("%s (score %.0f)" % (x["sym"], x["score"]) for x in ps) + " at %.0f each" % TICKET +
                         (", plus %d random coin%s from the same pool to compare." % (CONTROL_PICKS, "" if CONTROL_PICKS == 1 else "s") if any(x["grp"] == "rand" for x in picks_done) else "."))
        elif unchecked and not risk:
            parts.append("No RugCheck reports came back, so no fake buys this time.")
        elif gated and not flagged:
            parts.append("The best coins are already held or were picked in the last 7 days, so no new fake buys this time.")
        elif gated:
            parts.append("No top coin had a clean safety report, so no new fake buys this time.")
        else:
            parts.append("Nothing passed the gates, so no new fake buys this time. Staying out is a result too.")
        parts.append("Weights: %s (%d scored coins so far)." % (", ".join("%s %+.2f" % kv for kv in sorted(w.items(), key=lambda kv: -abs(kv[1]))[:5]), winfo["n"]))
    else:
        parts.append(("Checked %d open fake position%s." % (n_open, "" if n_open == 1 else "s")) if n_open else "No open fake positions to check.")
        if n_open and not exits_done:
            parts.append("Nothing hit a sell rule.")
    if exits_done:
        parts.append("Sold: " + "; ".join("%s (%s, %s, %.2f back)" % (x["sym"], "bot" if x["grp"] in ("pick", "early") else "random", x["why"], x["eur"]) for x in exits_done) + ".")
    if snap_n:
        parts.append("Saved all %d scanned coins for the big test; they get priced again in 24 hours." % snap_n)
    if big:   # one line for all chunks of the scored snapshot
        wavg = lambda i_n, i_a: (sum(b[i_a] * b[i_n] for b in big if b[i_a] is not None) / max(sum(b[i_n] for b in big if b[i_a] is not None), 1)) if any(b[i_a] is not None for b in big) else None
        n_all, n_ok, n_no, n_top = (sum(b[i] for b in big) for i in (0, 2, 0, 4))
        n_no = n_all - n_ok
        a_ok, a_no, a_top = wavg(2, 1), wavg(0, 3), wavg(4, 5)
        parts.append("Big test: %d coins from yesterday's scan, 24 hours later: %s." % (n_all, "; ".join(x for x in [
            "the %d that passed the gates averaged %+.2f per 20" % (n_ok, a_ok) if n_ok and a_ok is not None else "",
            "the bot's top 10 averaged %+.2f" % a_top if a_top is not None else "",
            "the other %d averaged %+.2f" % (n_no, a_no) if a_no is not None else ""] if x)))
    all_pos = dict(load_docs(d, "memepos")); all_pos.update(emitted.get("memepos", {}))
    all_ex = dict(load_docs(d, "memeexit")); all_ex.update(emitted.get("memeexit", {}))
    cash_after = bankroll(positions_from(all_pos, all_ex))
    parts.append("Bankroll: %.2f free of %.0f, %d open." % (cash_after["free"], BUDGET, cash_after["open"]))
    note = " ".join(parts)
    runs = int(state.get("runs") or 0) + 1
    emit("memebot", "state", {"rule": RULE, "ticket": TICKET, "budget": BUDGET, "started": state.get("started") or now, "lastRun": now, "runs": runs,
                              "lastMode": mode, "lastPick": now if mode == "pick" else state.get("lastPick"), "note": note, "cash": cash_after,
                              "scanned": len(rows) if mode == "pick" or snap_n else state.get("scanned"),
                              "passed": len(gated) if mode == "pick" or snap_n else state.get("passed"),
                              "bigSnapT": now if snap_n else state.get("bigSnapT"), "bigSnapN": snap_n or state.get("bigSnapN"),
                              "weightsN": winfo["n"], "lastEarly": state.get("lastEarly")})
    emit("memebot", "marks", new_marks)
    emit("memecurve", run_id, curve_point(all_pos, all_ex, new_marks["px"], now))
    emit("memeruns", run_id, {"t": now, "mode": mode, "rule": RULE, "scanned": len(rows), "passed": len(gated),
                              "flagged": flagged, "picks": picks_done, "exits": exits_done, "note": note})
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(writes, f, indent=1)
    top5 = [{"sym": r["pr"].get("symbol"), "score": r["sc"], "addr": r["a"]} for r in gated[:5]]
    print(json.dumps({"mode": mode, "asked": asked, "scanned": len(rows), "gated": len(gated), "top5": top5, "flagged": flagged, "picks": picks_done,
                      "exits": exits_done, "bigTestSaved": snap_n, "bigTestScored": scored_n, "weights": w, "weightsFrom": winfo["n"],
                      "cash": cash_after, "writes": len(writes), "note": note}, indent=1))


def positions_from(pos_docs, exit_docs):
    """positions() over in-memory docs (saved docs plus the ones this run just emitted)."""
    pos = {pid: dict(p) for pid, p in pos_docs.items()}
    for pid, p in pos.items():
        p["_id"] = pid
        p["_exits"] = sorted([e for e in exit_docs.values() if e.get("pos") == pid], key=lambda e: e.get("t", 0))
        p["_left"] = max(0.0, 1.0 - sum(num(e.get("frac")) or 0 for e in p["_exits"]))
    return pos


def cmd_learn(d):
    rows = result_rows(d)
    learned, n, detail = learn(rows) if rows else ({}, 0, {})
    w, info = blended_weights(d)
    print(json.dumps({"scored": n, "lambda": info["lambda"], "learned": learned, "used": w,
                      "detail": dict(sorted(detail.items(), key=lambda kv: -abs(kv[1]["rho"])))}, indent=1))


def cmd_wallets(d):
    table = wallet_table(d)
    rows = sorted(table.items(), key=lambda kv: (-kv[1]["avg"], -kv[1]["n"]))
    print(json.dumps({"wallets": len(table), "best": [dict(w=w, **v) for w, v in rows[:25]], "worst": [dict(w=w, **v) for w, v in rows[-10:]]}, indent=1))


def cmd_analyze(d):
    rows = [(f, e) for f, e in result_rows(d)]
    keys = sorted({k for f, _ in rows for k in f})
    out = []
    for k in keys:
        vals = sorted(num(f[k]) for f, _ in rows if num(f.get(k)) is not None)
        if len(vals) < 20 or vals[0] == vals[-1]:
            continue
        med = vals[len(vals) // 2]
        hi = [e for f, e in rows if num(f.get(k)) is not None and num(f[k]) >= med]
        lo = [e for f, e in rows if num(f.get(k)) is not None and num(f[k]) < med]
        if len(hi) < 8 or len(lo) < 8:
            continue
        avg = lambda a: sum(a) / len(a)
        up = lambda a: round(100 * sum(1 for e in a if e > 0) / len(a))
        out.append({"factor": k, "split": round(med, 4), "high": {"n": len(hi), "avg": round(avg(hi), 2), "up": up(hi)},
                    "low": {"n": len(lo), "avg": round(avg(lo), 2), "up": up(lo)}, "gap": round(avg(hi) - avg(lo), 2)})
    out.sort(key=lambda r: -abs(r["gap"]))
    print(json.dumps({"coins": len(rows), "factors": out}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["mode", "gather", "shortlist", "run", "learn", "analyze", "wallets", "cash"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--mode", choices=["pick", "check"], default="check")
    ap.add_argument("--now", type=float, default=None)
    ap.add_argument("--force", action="store_true", help="manual run: pick even inside the 3-hour gap or the daily cap (the bankroll still caps it)")
    a = ap.parse_args()
    now = int(a.now if a.now else time.time() * 1000)
    if a.cmd == "mode":
        cmd_mode(a.dir, now, a.force)
    elif a.cmd == "gather":
        cmd_gather(a.dir, now)
    elif a.cmd == "shortlist":
        cmd_shortlist(a.dir, now, a.force)
    elif a.cmd == "learn":
        cmd_learn(a.dir)
    elif a.cmd == "analyze":
        cmd_analyze(a.dir)
    elif a.cmd == "wallets":
        cmd_wallets(a.dir)
    elif a.cmd == "cash":
        cmd_cash(a.dir)
    else:
        cmd_run(a.dir, a.mode, now, a.force)


if __name__ == "__main__":
    main()
