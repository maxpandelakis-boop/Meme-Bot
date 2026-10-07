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
  * python3 memebot.py train   -> the training programs: walk-forward test of the ranking, the zero model (which factor values go
    with a coin going to zero within the horizon), limit grids, gate audit; writes db/memebot/train.json for the runs

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

RULE = "m9"
BUDGET = 40.0            # the whole fake bankroll; bot positions are paid out of it and sales flow back into it
TICKET = 20.0            # fake units per position -> BUDGET / TICKET = 2 coins held at once
MIN_TICKET = 15.0        # below 40 free, the bot still buys two coins of free/2 each as long as each is at least this
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
GATE_CRASH = {"chgH1": -40.0, "chgH6": -50.0, "chgH24": -70.0}   # a coin that fell this much is a dump, not a dip
GATE_SPIKE = {"chgH1": 150.0, "chgH6": 400.0}                     # and one that rose this much is the top
GATE_MAX_VOLMC = 8.0     # 24h volume more than 8x the market cap is wash trading, not interest
PAID_LISTS = ("boostTop", "boostLatest", "ads")                   # DexScreener lists that cost money; a coin seen only there is not "found"
MIN_LP_LOCKED = 50.0
MAX_CREATOR_PCT = 100.0  # the creator's share of the supply; the 2h profile caps it (a dev who still holds a lot can dump it)
MAX_TOP1 = 20.0          # holder checks (RugCheck): the biggest wallet, the top 10 together, insider wallets, holder count
MAX_TOP10 = 50.0
MIN_REC_SCORE = 45.0
SOFT_GATES = ("nobuyers", "novol1h")   # recommend mode: when no clean coin passes every gate, the best clean coin failing only these is named, labelled
FALLBACK_MAX_AGE_X = 2.0                # ... and only if it is at most this many times the profile's maximum age and not falling over 6 hours
DEEP_SCAN_BELOW = 10 ** 9   # fewer gated coins than this after a full scan -> the deep search runs too; set this high, it always runs     # recommend mode: a clean coin below this score is not worth naming ("no coin good enough" instead)
MAX_INSIDERS = 15
MIN_HOLDERS = 300
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
PRIOR = {"liqMc": 0.35, "volMc": 0.1, "buyShare": 0.1, "buyRatio1h": 0.15, "c6": -0.2, "c1": -0.15, "c24": -0.1, "srcN": 0.25, "kwN": 0.1,
         "boosts": -0.15, "nDex": 0.1, "soc.eng": 0.1, "x": 0.1, "web": 0.05,
         # holders: many holders, spread out, growing; few insiders and whales
         "rc.lp": 0.1, "rc.top10": -0.15, "rc.top1": -0.15, "rc.insiders": -0.15, "rc.holders": 0.15, "jup.holders": 0.1, "jup.holderChg24": 0.1,
         "dev.sold": -0.25, "dev.pct": -0.1, "dev.authOff": 0.05,
         "jup.top10Pct": -0.1, "jup.organic": 0.1, "jup.netBuyers24": 0.1,
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
MIN_SCAN_FOR_REC = 300   # recommend mode: a scan smaller than this is a broken fetch, not a universe
HORIZON = "24h"          # which profile is active: "24h" (survive a day) or "2h" (pump in the next two hours)
GATE_MAX_AGE_H = None    # 2h profile: coins older than this are not "early" anymore
GATE_MIN_BUYRATIO1H = None   # 2h profile: buys must outweigh sells in the last hour by this factor
GATE_MIN_VOL1SHARE = None    # 2h profile: the last hour's share of the day's volume must be at least this (1/24 = even pace)
PROFILES = {
    "24h": {},   # the defaults above
    "2h": {      # early, small, accelerating; measured two hours later; scored by momentum, not stability
        "RULE": "m9-2h", "GATE_MC": (50_000, 2_000_000), "GATE_MIN_LIQ": 15_000, "GATE_MIN_VOL24": 15_000, "GATE_MIN_AGE_H": 3.0, "GATE_MAX_AGE_H": 12.0,
        "GATE_MIN_BUYRATIO1H": 1.05, "GATE_MIN_VOL1SHARE": 1.0 / 36, "GATE_CRASH": {"chgH1": -10.0, "chgH6": -50.0, "chgH24": -70.0},
        "MAX_TOP10": 35.0, "MIN_REC_SCORE": 50.0, "MIN_LP_LOCKED": 90.0, "MAX_CREATOR_PCT": 5.0,
        "GATE_SPIKE": {"chgH1": 200.0, "chgH6": 600.0}, "SNAP_GAP_H": 0.4, "EVAL_H": 1.7, "MIN_HOLDERS": 800, "MAX_TOP1": 20.0, "MAX_INSIDERS": 10,
        "SHORTLIST": 16, "RC_BIG": 60, "LEARN_FULL_N": 25000,     # ~3 full 2h snapshots before the learned weights take over
        "PRIOR": {"buyRatio1h": 0.3, "vol1Share": 0.25, "jup.netBuyers1": 0.2, "gt.buyerRatio": 0.15, "jup.holderChg24": 0.15, "buyShare": 0.1, "srcN": 0.2, "kwN": 0.05,
                  "c1": 0.1, "liqMc": 0.15, "logLiq": 0.1, "ageH": -0.1, "boosts": -0.15, "rc.top1": -0.15, "rc.insiders": -0.15, "rc.holders": 0.1, "rc.top10": -0.1,
                  "x": 0.05, "news.hits": 0.05, "gm.smartDegen": 0.15, "gm.bundler": -0.1, "gm.sniperHold": -0.1, "gm.wash": -0.15, "tb.smartHold": 0.15, "sw.lb": 0.2,
                  "dev.sold": -0.3, "dev.pct": -0.15, "dev.authOff": 0.05}}}


def apply_profile(name):
    """Switch the module's rules to a profile. Called once at startup from --horizon; every command of a run must use the same one."""
    global HORIZON
    prof = PROFILES.get(name)
    if prof is None:
        raise SystemExit("unknown horizon %r (choose from %s)" % (name, ", ".join(PROFILES)))
    HORIZON = name
    for k, v in prof.items():
        globals()[k] = v
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
        with open(path, encoding="utf-8") as f:
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


def tickets_for(free):
    """How the free bankroll is split into buys: two of TICKET when 40 is free; below that still two of free/2 as long as each
    is at least MIN_TICKET; otherwise one of what is left (if at least MIN_TICKET); otherwise nothing."""
    free = math.floor(free * 100) / 100.0
    if free >= 2 * TICKET:
        return [TICKET, TICKET]
    if free >= 2 * MIN_TICKET:
        half = math.floor(free / 2 * 100) / 100.0
        return [half, half]
    if free >= MIN_TICKET:
        return [free]
    return []


def bankroll(pos):
    """The fake bankroll: BUDGET minus every bot ticket ever paid, plus every bot sale that came back.
    Open positions are counted at their ticket (what was paid), not at their current value."""
    spent = sum(num(p.get("ticket")) or TICKET for p in pos.values() if p.get("grp") in BOT_GROUPS)
    back = sum(num(e.get("eur")) or 0 for p in pos.values() if p.get("grp") in BOT_GROUPS for e in p["_exits"])
    n_open = sum(1 for p in pos.values() if p.get("grp") in BOT_GROUPS and p["_left"] > 1e-9)
    deployed = sum((num(p.get("ticket")) or TICKET) * p["_left"] for p in pos.values() if p.get("grp") in BOT_GROUPS if p["_left"] > 1e-9)
    free = BUDGET - spent + back
    tickets = tickets_for(free + 1e-9)
    return {"budget": BUDGET, "ticket": TICKET, "spent": round(spent, 2), "back": round(back, 2), "free": round(free, 2),
            "open": n_open, "deployed": round(deployed, 2), "slots": len(tickets), "tickets": tickets}


def due_snaps(d, now):
    snaps, done = load_docs(d, "memesnap"), load_docs(d, "memesnapres")
    return {sid: sn for sid, sn in sorted(snaps.items()) if sid not in done and isinstance(sn.get("coins"), list)
            and str(sn.get("rule") or RULE) == RULE and now - (num(sn.get("t")) or now) >= EVAL_H * 3_600_000}


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
    tk = bankroll(pos)["tickets"]
    return room, "%d picks today, %d free slot%s of %s" % (done, slots, "" if slots == 1 else "s", "/".join("%.2f" % t for t in tk))


def snap_due(d, now):
    last = max([num(sn.get("t")) or 0 for sn in load_docs(d, "memesnap").values()] or [0])
    return now - last >= SNAP_GAP_H * 3_600_000


def cmd_mode(d, now, force=False, snapshot=False, recommend=False):
    pos = positions(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    room, why = (PICKS_PER_RUN, "recommend mode: no buys, the two best coins are written to the page") if recommend else pick_room(state, pos, now, force)
    sd = snap_due(d, now) or snapshot
    due = due_snaps(d, now)
    # recommend mode always scans everything: a button press minutes after the last scan still deserves the whole universe
    print(json.dumps({"pick": room > 0, "room": room, "why": why, "scan": "full" if (sd or recommend) else ("light" if room > 0 else "none"), "bigTestSaveDue": sd,
                      "bigTestDue": len(due), "bigTestDueCoins": sum(len(sn["coins"]) for sn in due.values()),
                      "open": sum(1 for p in pos.values() if p["_left"] > 1e-9), "cash": bankroll(pos)}))


def eval_text():
    """'2 hours' / '24 hours': how long after a snapshot its coins are priced again. EVAL_H carries some slack below the
    nominal horizon (1.7 for the 2h profile, 23.5 for 24h) so a run that starts a little early still scores it."""
    return "%d hours" % round(EVAL_H)


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
DEV_COLS = ("address", "devWallet", "devPct", "mintAuthOff", "freezeAuthOff", "jupHolders", "organic", "txs3h", "devSold", "devSellAgeMin", "topHoldersPct")
LL_COLS = ("address", "symbol", "name", "creator", "marketCap", "volume24h", "createdAt", "poolId", "finished")
TB_COLS = ("address", "status", "tags", "makerTags")                       # tb/<coin>.txt: address here is the WALLET
TEXT_COLS = {"address", "symbol", "name", "dexId", "pairAddress", "poolAddress", "xUrl", "twitter", "website", "telegram", "createdAt", "launchpad", "devWallet", "creator", "poolId",
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
        with open(fn, encoding="utf-8", errors="replace") as f:
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
    dev, _ = load_side(d, "dev", DEV_COLS)
    ll, ltags = load_side(d, "ll", LL_COLS)
    for src in (jtags, ptags, gtags, mtags, ltags):
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
        if a in dev:
            p["dev"] = dict(dev[a])
        if a in ll:
            p["ll"] = {k: ll[a].get(k) for k in ("creator", "marketCap", "createdAt", "finished")}
        if a in gm:
            p["gm"] = {k: gm[a].get(k) for k in ("holders", "top10", "smartDegen", "renowned", "sniper", "bundler", "rat", "bluechip", "rugRatio", "wash",
                                                 "hot", "devHold", "sniperHold", "botDegen", "honeypot", "creatorStatus", "twRename", "launchpad")}
    with open(os.path.join(d, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump(list(best.values()), f, separators=(",", ":"))
    with open(os.path.join(d, "universe.json"), "w", encoding="utf-8") as f:
        json.dump(universe, f, separators=(",", ":"))
    held = [p["addr"] for p in pos.values() if p["_left"] > 1e-9 and B58.match(str(p.get("addr", "")))]
    for doc in load_docs(d, "memerec").values():        # recommendations not yet priced again travel like open positions
        if isinstance(doc, dict) and not doc.get("out") and now - (num(doc.get("t")) or now) < 48 * 3_600_000:
            held += [str(p.get("addr")) for p in (doc.get("picks") or []) if isinstance(p, dict) and B58.match(str(p.get("addr", "")))]
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
    dv = pr.get("dev") or {}
    if dv:
        f["dev.pct"], f["dev.txs3h"] = num(dv.get("devPct")), num(dv.get("txs3h"))
        f["dev.sold"] = 1.0 if dv.get("devSold") else 0.0
        f["dev.authOff"] = 1.0 if (dv.get("mintAuthOff") and dv.get("freezeAuthOff")) else 0.0
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


def gates(pr, basic, sym_mc, f=None):
    price, mc, liq, vol24, age_h = basic["price"], basic["mc"], basic["liq"], basic["vol24"], basic["age_h"]
    f = f or {}
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
    chg = {k: num(pr.get(k)) for k in ("chgH1", "chgH6", "chgH24")}
    if any(chg[k] is not None and chg[k] <= v for k, v in GATE_CRASH.items()): fails.append("crash")
    if any(chg[k] is not None and chg[k] >= v for k, v in GATE_SPIKE.items()): fails.append("spike")
    if vol24 and mc and vol24 / mc > GATE_MAX_VOLMC: fails.append("wash")
    tags = pr.get("tags") or []
    if tags and all(t.startswith("list:") and t[5:] in PAID_LISTS for t in tags): fails.append("paid")
    if GATE_MAX_AGE_H is not None and age_h is not None and age_h > GATE_MAX_AGE_H: fails.append("old")
    if GATE_MIN_BUYRATIO1H is not None and (f.get("buyRatio1h") is None or f["buyRatio1h"] < GATE_MIN_BUYRATIO1H): fails.append("nobuyers")
    if GATE_MIN_VOL1SHARE is not None and (f.get("vol1Share") is None or f["vol1Share"] < GATE_MIN_VOL1SHARE): fails.append("novol1h")
    return fails


FAIL_TEXT = {"price": "no price", "curve": "still on its launch curve", "nodex": "no DEX pair data (Jupiter, GeckoTerminal or GMGN list only)", "honeypot": "flagged as a honeypot (GMGN)", "notmeme": "not a meme coin (stock, wrapped or staked asset, stablecoin)",
             "copy": "copycat of a bigger coin with the same name", "paid": "seen only on paid DexScreener lists (boosts, ads)",
             "nobuyers": "buys do not outweigh sells in the last hour", "novol1h": "volume not accelerating in the last hour"}


def fail_text(k):
    """The wording of a gate, built from the active profile's numbers."""
    if k == "liq":
        return "liquidity under %s" % money(GATE_MIN_LIQ)
    if k == "mc":
        return "market cap outside %s-%s" % (money(GATE_MC[0]), money(GATE_MC[1]))
    if k == "vol":
        return "under %s traded in 24h" % money(GATE_MIN_VOL24)
    if k == "young":
        return "under %s old" % ("an hour" if GATE_MIN_AGE_H == 1 else "%g hours" % GATE_MIN_AGE_H)
    if k == "old":
        return "older than %g hours (%s profile wants early coins)" % (GATE_MAX_AGE_H, HORIZON)
    if k == "crash":
        return "crashed (down %.0f%%+ in 1h, %.0f%%+ in 6h or %.0f%%+ in 24h)" % tuple(-GATE_CRASH[x] for x in ("chgH1", "chgH6", "chgH24"))
    if k == "spike":
        return "spiked (up %.0f%%+ in 1h or %.0f%%+ in 6h)" % (GATE_SPIKE["chgH1"], GATE_SPIKE["chgH6"])
    if k == "wash":
        return "24h volume over %gx the market cap (wash trading)" % GATE_MAX_VOLMC
    return FAIL_TEXT.get(k, k)


def money(v):
    v = float(v)
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if v >= div:
            return "$%g%s" % (round(v / div, 1), unit)
    return "$%g" % v


# ---------------------------------------------------------------- learning the weights
def learnable(c):
    """Only coins that could have been candidates teach the weights: with the dust (no liquidity, tiny market cap) in the
    sample, the weights learn 'established coins survive', not 'which candidate rises'."""
    liq, mc = num(c.get("liq")), num(c.get("mc"))
    return liq is not None and mc is not None and liq >= GATE_MIN_LIQ and GATE_MC[0] <= mc <= GATE_MC[1]


def usable_result(doc):
    """A scored snapshot chunk teaches only when its pricing worked: when more than half of its candidate-like coins (minimum
    liquidity and market cap at the time) count as gone, the price fetch failed for the chunk and 'gone' means 'unpriced'."""
    if not isinstance(doc, dict) or str(doc.get("rule") or RULE) != RULE:
        return False
    cand = [c for c in (doc.get("coins") or []) if isinstance(c, dict) and learnable(c)]
    return len(cand) < 20 or sum(1 for c in cand if c.get("gone")) <= 0.5 * len(cand)


def result_rows(d):
    rows = []
    for doc in load_docs(d, "memesnapres").values():
        if not usable_result(doc):
            continue                      # each profile learns from its own horizon only, and only from chunks whose pricing worked
        for c in doc.get("coins") or []:
            if isinstance(c, dict) and isinstance(c.get("f"), dict) and num(c.get("eur")) is not None and learnable(c):
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


# ---------------------------------------------------------------- training: out-of-sample tests, the zero model, tuned limits
TRAIN_MIN_ROWS = 400       # scored candidate coins before a fitted model counts (walk-forward checkpoints with less history are skipped)
TRAIN_BINS = 4             # equal-count value bins per factor in the zero model
TRAIN_CHECKPOINTS = 8      # walk-forward: the models are refitted this many times along the history, each tested on the scans after it only
TRAIN_MIN_TIPS = 30        # a limit is tuned only from at least this many out-of-sample tips
MAX_ZERO_P = 0.35          # a clean coin whose trained chance of going to zero is above this is skipped; the training may tighten it ...
ZERO_P_FLOOR = 0.05        # ... but never below this, nor below 1.5x the base zero rate: a tighter limit would leave the picks to chance
ZERO_GRID = (0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5)
SCORE_GRID = tuple(range(35, 85, 5))


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def bin_of(x, edges):
    b = 0
    while b < len(edges) and x > edges[b]:
        b += 1
    return b


def train_groups(d):
    """The scored snapshots as (run, t0, [coin...]) in time order. One coin row: factors, clipped result, gone flag, gate pass,
    the gates it failed, the score it had. Only candidate-like coins (learnable) are kept, as for the weights."""
    by_run = {}
    for sid, doc in load_docs(d, "memesnapres").items():
        if not usable_result(doc):
            continue
        run = str(sid).rsplit("-", 1)[0]
        t0 = num(doc.get("t0")) or num(doc.get("t")) or 0
        g = by_run.setdefault(run, {"t": t0, "rows": []})
        g["t"] = min(g["t"], t0)
        for c in doc.get("coins") or []:
            if isinstance(c, dict) and isinstance(c.get("f"), dict) and num(c.get("eur")) is not None and learnable(c) and c.get("a"):
                mult = num(c.get("mult")) or 0.0
                g["rows"].append({"a": str(c["a"]), "s": c.get("s"), "f": c["f"], "eur": clamp(num(c["eur"]), EUR_CLIP[0], EUR_CLIP[1]), "mult": mult,
                                  "gone": bool(c.get("gone")) or mult <= 0.0, "pass": bool(c.get("pass")), "why": [str(x) for x in (c.get("why") or []) if x],
                                  "sc": num(c.get("sc"))})
    return sorted(((run, g["t"], g["rows"]) for run, g in by_run.items() if g["rows"]), key=lambda x: (x[1], x[0]))


def bin_model(rows, target):
    """Which factor values go with an outcome (target(row) -> bool) within the horizon. Each factor is cut into equal-count bins
    and each bin gets the (smoothed) log-odds of the outcome against the base rate. A coin's raw score is the sum over its
    factors. The raw score is then calibrated on the same rows (bucket -> observed rate, made monotone), so what comes out is a
    probability that means what it says. None when there is too little history or too few cases on either side."""
    n = len(rows)
    ys = [bool(target(r)) for r in rows]
    gone_n = sum(1 for y in ys if y)
    if n < TRAIN_MIN_ROWS or gone_n < 10 or gone_n > n - 10:
        return None
    base = gone_n / float(n)
    factors = {}
    keys = sorted({k for r in rows for k in r["f"] if num(r["f"].get(k)) is not None})
    for k in keys:
        pts = [(num(r["f"][k]), y) for r, y in zip(rows, ys) if num(r["f"].get(k)) is not None]
        if len(pts) < 2 * LEARN_MIN_N:
            continue
        xs = sorted(p[0] for p in pts)
        if xs[0] == xs[-1]:
            continue
        edges = sorted({xs[int(len(xs) * i / TRAIN_BINS) - 1] for i in range(1, TRAIN_BINS)})   # upper edge of each bin, ties merged
        cnt = [[0, 0] for _ in range(len(edges) + 1)]
        for x, g in pts:
            b = bin_of(x, edges)
            cnt[b][0] += 1
            cnt[b][1] += 1 if g else 0
        lo = [round(logit((c[1] + 4.0 * base) / (c[0] + 4.0)) - logit(base), 3) for c in cnt]   # 4 pseudo-coins at the base rate
        if max(abs(v) for v in lo) < 0.15:
            continue                                  # a factor that tells nothing about zeros stays out
        factors[k] = {"edges": [round(e, 6) for e in edges], "lo": lo, "n": len(pts)}
    if not factors:
        return None
    model = {"base": round(base, 5), "n": n, "zeros": gone_n, "factors": factors, "cal": []}
    raw = sorted((raw_zero(model, r["f"]), y) for r, y in zip(rows, ys))
    target = max(50, len(raw) // 10)
    blocks, cur, i = [], None, 0
    while i < len(raw):                               # buckets of ~target coins; coins with the same raw score stay in one bucket
        j = i
        while j + 1 < len(raw) and raw[j + 1][0] == raw[i][0]:
            j += 1
        if cur is None:
            cur = [raw[j][0], 0.0, 0.0]
        cur[0] = raw[j][0]
        cur[1] += sum(1 for _, g in raw[i:j + 1] if g)
        cur[2] += j + 1 - i
        if cur[2] >= target:
            blocks.append(cur)
            cur = None
        i = j + 1
    if cur is not None:
        if blocks and cur[2] < target / 2.0:
            blocks[-1] = [cur[0], blocks[-1][1] + cur[1], blocks[-1][2] + cur[2]]
        else:
            blocks.append(cur)
    i = 0
    while i < len(blocks) - 1:                        # pool adjacent buckets until the zero rate never falls as the raw score rises
        if blocks[i + 1][1] / blocks[i + 1][2] < blocks[i][1] / blocks[i][2]:
            blocks[i] = [blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1], blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    model["cal"] = [{"hi": round(b[0], 4), "p": round(b[1] / b[2], 4), "n": int(b[2])} for b in blocks]
    return model


def zero_model(rows):
    """The chance of going to zero (no price, or liquidity gone) within the horizon."""
    return bin_model(rows, lambda r: r["gone"])


def up_model(rows):
    """The chance of a profit after fees within the horizon."""
    return bin_model(rows, lambda r: r["eur"] > 0)


def chances(zmodel, umodel, f):
    """(chance of zero, chance of profit) for a coin's factors; None where there is no model."""
    return zero_p(zmodel, f) if zmodel else None, zero_p(umodel, f) if umodel else None


def raw_zero(model, f):
    s = 0.0
    for k, m in model["factors"].items():
        v = num(f.get(k))
        if v is not None:
            s += m["lo"][bin_of(v, m["edges"])]
    return s


def zero_p(model, f):
    """The trained chance (0..1) that a coin with these factors goes to zero within the horizon; None without a model."""
    if not isinstance(model, dict) or not model.get("factors") or not model.get("cal"):
        return None
    raw = raw_zero(model, f)
    for b in model["cal"]:
        if raw <= b["hi"]:
            return b["p"]
    return model["cal"][-1]["p"]


def tip_stats(tips):
    n = len(tips)
    if not n:
        return {"n": 0, "avg": None, "win": None, "zero": None, "median": None}
    mults = sorted(num(t.get("mult")) or 0.0 for t in tips)
    return {"n": n, "avg": round(sum(num(t.get("eur")) or 0.0 for t in tips) / n, 2), "win": round(100.0 * sum(1 for t in tips if (num(t.get("eur")) or 0.0) > 0) / n, 1),
            "zero": round(100.0 * sum(1 for t in tips if t.get("gone")) / n, 1), "median": round(mults[n // 2], 3)}


def fit_weights(rows):
    learned, nl, _ = learn([(r["f"], r["eur"]) for r in rows]) if rows else ({}, 0, {})
    lam = clamp(nl / float(LEARN_FULL_N))
    w = {}
    for k in set(PRIOR) | set(learned):
        v = (1 - lam) * PRIOR.get(k, 0.0) + lam * learned.get(k, 0.0)
        if abs(v) >= 0.01:
            w[k] = round(v, 4)
    return w


def walk_forward(groups):
    """Refit the weights and the zero model at TRAIN_CHECKPOINTS points along the history, each time on the scans before the
    point only, and let that model rank the gate-passing coins of the scans up to the next point. What those coins did is the
    honest, out-of-sample record of the ranking. Returns [(run, t0, candidates best first, history size)]."""
    n = len(groups)
    tested = []
    if n < 4:
        return tested
    cps = sorted({int(round(n * i / float(TRAIN_CHECKPOINTS + 1))) for i in range(1, TRAIN_CHECKPOINTS + 1)} - {0, n})
    for a, b in zip(cps, cps[1:] + [n]):
        hist = [r for _, _, rows in groups[:a] for r in rows]
        if len(hist) < TRAIN_MIN_ROWS:
            continue
        w, model, umodel = fit_weights(hist), zero_model(hist), up_model(hist)
        for run, t0, rows in groups[a:b]:
            sc = score_all([(r["a"], r["f"]) for r in rows], w)
            cands = [dict(r, sc=sc.get(r["a"], 50.0), zp=zero_p(model, r["f"]) if model else None, up=zero_p(umodel, r["f"]) if umodel else None) for r in rows if r["pass"]]
            cands.sort(key=lambda r: -r["sc"])
            tested.append((run, t0, cands, len(hist)))
    return tested


def strategy(tested, top=2, zmax=None, min_sc=None, by_odds=False):
    """The tips a rule would have given in the tested scans: the best `top` candidates (above min_sc, under the zero limit);
    by_odds ranks them by trained profit chance minus zero chance instead of the score (the risky tier's rule)."""
    tips, covered = [], 0
    for _, _, cands, _ in tested:
        pool = sorted(cands, key=lambda c: -((c.get("up") or 0.0) - (c.get("zp") or 0.0))) if by_odds else cands
        got = [c for c in pool if (zmax is None or c["zp"] is None or c["zp"] <= zmax) and (min_sc is None or c["sc"] >= min_sc)][:top]
        tips += got
        covered += 1 if got else 0
    st = tip_stats(tips)
    st["coverage"] = round(100.0 * covered / len(tested), 1) if tested else None
    return st


def gate_audit(groups):
    """Coins that failed exactly one gate, by gate, next to the coins that passed all: a gate whose lone failers did as well
    as the passers is not protecting anything; one whose failers went to zero is earning its keep."""
    by = {}
    for _, _, rows in groups:
        for r in rows:
            if r["pass"]:
                by.setdefault("pass", []).append(r)
            elif len(r["why"]) == 1:
                by.setdefault(r["why"][0], []).append(r)
    out = [dict(gate=k, text="passed every gate" if k == "pass" else fail_text(k), **tip_stats(v)) for k, v in by.items() if len(v) >= 20]
    return sorted(out, key=lambda x: (x["gate"] != "pass", -x["n"]))


def tip_record(d):
    """Every real tip the bot gave (memerec) that has been priced again, as one stats row."""
    tips = []
    for doc in load_docs(d, "memerec").values():
        if isinstance(doc, dict) and isinstance(doc.get("out"), dict) and str(doc.get("rule") or RULE) == RULE:
            tips += [o for o in (doc["out"].get("picks") or []) if isinstance(o, dict)]
    return tip_stats(tips)


def tune(tested, base, base_rate):
    """Pick the zero limit and the strong-pick score bar from the out-of-sample record. The zero limit is the tightest one that
    keeps at least 85% of the scans covered and cuts the zero rate; the score bar is the one with the best win rate. Both are
    bounded, and neither moves without TRAIN_MIN_TIPS tips behind it. base_rate: the share of all candidates that went to zero;
    the limit never goes under 1.5x of it (the grid gets multiples of it, so a low base rate still gets a limit that bites)."""
    tuned, why = {"MAX_ZERO_P": MAX_ZERO_P, "MIN_REC_SCORE": MIN_REC_SCORE}, []
    floor = max(ZERO_P_FLOOR, 1.5 * (base_rate or 0.0))
    grid = sorted(set(ZERO_GRID) | {round(k * base_rate, 3) for k in (2, 3, 4, 6) if base_rate and 0.03 <= k * base_rate <= 0.6})
    zero_grid = [dict(limit=z, **strategy(tested, 2, zmax=z)) for z in grid]
    score_grid = [dict(minScore=s, **strategy(tested, 2, min_sc=s)) for s in SCORE_GRID]
    if base.get("n", 0) >= TRAIN_MIN_TIPS and base.get("coverage"):
        ok = [g for g in zero_grid if g["n"] >= TRAIN_MIN_TIPS and g["coverage"] >= 0.85 * base["coverage"] and g["limit"] >= floor
              and g["zero"] is not None and base["zero"] is not None and g["zero"] <= base["zero"]]
        if ok:
            best = min(ok, key=lambda g: (g["zero"], -(g["avg"] or 0), -g["limit"]))   # the loosest limit that does the job
            tuned["MAX_ZERO_P"] = best["limit"]
            why.append("zero limit %d%%: %d%% of the top-2 tips went to zero against %d%% without it, %d%% of the scans still get a tip" % (
                round(100 * best["limit"]), round(best["zero"]), round(base["zero"]), round(best["coverage"])))
        ok = [g for g in score_grid if g["n"] >= TRAIN_MIN_TIPS and g["win"] is not None]
        if ok:
            best = max(ok, key=lambda g: (g["win"], g["avg"] or 0, -g["minScore"]))
            tuned["MIN_REC_SCORE"] = float(min(max(best["minScore"], MIN_REC_SCORE - 10), MIN_REC_SCORE + 20))
            why.append("strong picks from score %d: %d%% of such tips went up (%d tips)" % (tuned["MIN_REC_SCORE"], round(best["win"]), best["n"]))
    return tuned, zero_grid, score_grid, why


def cmd_train(d, now):
    """The training programs, all on the scored snapshots of this profile: the walk-forward test of the ranking, the zero
    model, the limit grids, the gate audit, the factor splits and the real tip record. Writes db/memebot/train.json, which
    the next runs read (zero model and tuned limits), and prints the summary."""
    groups = train_groups(d)
    rows = [r for _, _, g in groups for r in g]
    doc = {"t": now, "rule": RULE, "rows": len(rows), "scans": len(groups), "zeros": sum(1 for r in rows if r["gone"]),
           "tested": 0, "walkForward": {}, "zeroGrid": [], "scoreGrid": [], "gates": [], "factors": [], "tips": tip_record(d),
           "tuned": {"MAX_ZERO_P": MAX_ZERO_P, "MIN_REC_SCORE": MIN_REC_SCORE}, "tunedWhy": [], "zeroModel": None, "upModel": None, "zeroFactors": [], "note": ""}
    if rows:
        tested = walk_forward(groups)
        doc["tested"] = len(tested)
        if tested:
            wf = {"top1": strategy(tested, 1), "top2": strategy(tested, 2), "allPass": strategy(tested, 10 ** 6)}
            bottom = []
            for _, _, cands, _ in tested:
                bottom += cands[-2:] if len(cands) > 2 else []
            wf["bottom2"] = tip_stats(bottom)
            wf["bottom2"]["coverage"] = None
            tuned, zero_grid, score_grid, why = tune(tested, wf["top2"], sum(1 for r in rows if r["gone"]) / float(len(rows)))
            wf["top2zero"] = strategy(tested, 2, zmax=tuned["MAX_ZERO_P"])
            wf["byOdds"] = strategy(tested, 1, by_odds=True)
            doc.update({"walkForward": wf, "zeroGrid": zero_grid, "scoreGrid": score_grid, "tuned": tuned, "tunedWhy": why})
        doc["gates"] = gate_audit(groups)
        model = zero_model(rows)
        doc["upModel"] = up_model(rows)
        if model:
            doc["zeroModel"] = model
            doc["zeroFactors"] = [{"factor": k, "spread": round(max(m["lo"]) - min(m["lo"]), 3), "lo": m["lo"], "edges": m["edges"]}
                                  for k, m in sorted(model["factors"].items(), key=lambda kv: -(max(kv[1]["lo"]) - min(kv[1]["lo"])))[:12]]
        splits = []
        for k in sorted({k for r in rows for k in r["f"]}):
            vals = sorted(num(r["f"][k]) for r in rows if num(r["f"].get(k)) is not None)
            if len(vals) < 2 * LEARN_MIN_N or vals[0] == vals[-1]:
                continue
            med = vals[len(vals) // 2]
            hi = [r for r in rows if num(r["f"].get(k)) is not None and num(r["f"][k]) >= med]
            lo = [r for r in rows if num(r["f"].get(k)) is not None and num(r["f"][k]) < med]
            if len(hi) < LEARN_MIN_N or len(lo) < LEARN_MIN_N:
                continue
            h, l = tip_stats(hi), tip_stats(lo)
            splits.append({"factor": k, "split": round(med, 4), "high": h, "low": l, "gap": round(h["avg"] - l["avg"], 2), "zeroGap": round(h["zero"] - l["zero"], 1)})
        doc["factors"] = sorted(splits, key=lambda s: -abs(s["gap"]))[:16]
    wf = doc["walkForward"]
    if not rows:
        doc["note"] = "No scored snapshots yet: the training starts once the first big-test results are in."
    elif not wf:
        doc["note"] = "%d scored coins from %d scans: too little history for the walk-forward test (it needs 4 scans and %d coins before the first checkpoint)." % (len(rows), len(groups), TRAIN_MIN_ROWS)
    else:
        t2, t2z, ap = wf["top2"], wf.get("top2zero") or wf["top2"], wf["allPass"]
        doc["note"] = ("Walk-forward on %d scans (%d coin results): the bot's top-2 picks averaged %+.2f per 20 (%d%% up, %d%% to zero); all gate-passing coins %+.2f (%d%% up, %d%% to zero)." % (
            len(tested), len(rows), t2["avg"], round(t2["win"]), round(t2["zero"]), ap["avg"], round(ap["win"]), round(ap["zero"])))
        if doc["zeroModel"]:
            doc["note"] += " With the zero model (limit %d%%): %+.2f per 20, %d%% to zero, %d%% of the scans covered." % (round(100 * doc["tuned"]["MAX_ZERO_P"]), t2z["avg"], round(t2z["zero"]), round(t2z["coverage"]))
        else:
            doc["note"] += " No zero model yet (it needs %d coins and at least 10 zeros)." % TRAIN_MIN_ROWS
        bo = wf.get("byOdds") or {}
        if doc["upModel"] and bo.get("n"):
            doc["note"] += " Ranked by trained odds alone (profit chance minus zero chance), the best coin per scan averaged %+.2f per 20 (%d%% up, %d%% to zero)." % (bo["avg"], round(bo["win"]), round(bo["zero"]))
    path = os.path.join(d, "db", "memebot")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "train.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    short = {k: doc[k] for k in ("rows", "scans", "zeros", "tested", "walkForward", "tuned", "tunedWhy", "note", "tips")}
    short["zeroModel"], short["upModel"] = bool(doc["zeroModel"]), bool(doc["upModel"])
    print(json.dumps(short, indent=1))
    return doc


def load_train(d):
    """What the last training left for the runs: (zero model, profit model, zero limit, strong-pick score bar, rows trained on)."""
    doc = load_json(os.path.join(d, "db", "memebot", "train.json"), {}) or {}
    if not isinstance(doc, dict) or str(doc.get("rule") or RULE) != RULE:
        return None, None, MAX_ZERO_P, MIN_REC_SCORE, 0
    tuned = doc.get("tuned") or {}
    model = doc.get("zeroModel") if isinstance(doc.get("zeroModel"), dict) else None
    umodel = doc.get("upModel") if isinstance(doc.get("upModel"), dict) else None
    zmax = num(tuned.get("MAX_ZERO_P"))
    zmax = min(max(zmax, ZERO_P_FLOOR), 0.9) if zmax is not None else MAX_ZERO_P
    bar = num(tuned.get("MIN_REC_SCORE"))
    bar = min(max(bar, MIN_REC_SCORE - 10), MIN_REC_SCORE + 20) if bar is not None else MIN_REC_SCORE
    return model, umodel, zmax, bar, int(num(doc.get("rows")) or 0)


def odds_text(r):
    up, zp = r.get("up"), r.get("zp")
    bits = (["%d%% chance of a profit" % round(100 * up)] if up is not None else []) + (["%d%% chance of going to zero" % round(100 * zp)] if zp is not None else [])
    return ("trained odds: " + ", ".join(bits) + " within " + eval_text()) if bits else ""


def zero_view(model, umodel, zmax, r, rtxt):
    """The zero model's verdict on a clean coin: (ok, safety text). Without a model the RugCheck verdict stands as it is."""
    r["zp"], r["up"] = chances(model, umodel, r["f"])
    if r["zp"] is None:
        return True, rtxt
    if r["zp"] > zmax:
        return False, "training model: %d%% chance of going to zero within %s (limit %d%%)" % (round(100 * r["zp"]), eval_text(), round(100 * zmax))
    return True, "%s; %s" % (rtxt, odds_text(r))


HARD_BLOCK = ("price", "curve", "nodex", "honeypot", "notmeme", "copy")   # gates no tier relaxes: without a tradable pair or as a scam there is nothing to name


def risky_rows(rows, held, recent, zmodel, umodel):
    """The last resort of recommend mode: every coin with a tradable pair, the profile's minimum liquidity and market cap and no
    crash, whatever else it failed, ranked by trained odds (profit chance minus zero chance), then score."""
    out = []
    for r in rows:
        if r["a"] in held or r["a"] in recent or any(k in HARD_BLOCK or k == "crash" for k in r["fails"]):
            continue
        liq, mc = r["basic"].get("liq"), r["basic"].get("mc")
        if not r["basic"].get("price") or liq is None or liq < GATE_MIN_LIQ or mc is None or mc < GATE_MC[0]:
            continue
        r["zp"], r["up"] = chances(zmodel, umodel, r["f"])
        out.append(r)
    out.sort(key=lambda r: (-((r["up"] or 0.0) - (r["zp"] or 0.0)), -r["sc"]))
    return out


# ---------------------------------------------------------------- the scan
def scan(d, pos, pairs, now, w):
    """Factors, gates and scores for every coin with pair data. Returns rows (best first) and helpers."""
    soc, risk = load_social(d), load_risk(d)
    for a, pr in pairs.items():                       # the creator check (Jupiter + RPC) rides on the RugCheck entry
        if pr.get("dev") and a in risk and isinstance(risk[a], dict):
            risk[a] = dict(risk[a], dev=pr["dev"])
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
        fails = gates(pr, basic, sym_mc, f)
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


OWNERSHIP_FLAG = re.compile(r"high ownership|single holder ownership", re.I)


def risk_view(r):
    """A RugCheck summary -> (True/False/None, text). None means there is no report, so the coin is not bought."""
    if not isinstance(r, dict):
        return None, "no RugCheck report"
    danger = [x for x in names(r, "danger") if not OWNERSHIP_FLAG.search(x)]   # ownership is judged by the numbers below
    if danger:
        return False, "RugCheck danger: " + ", ".join(danger[:3])
    warn = names(r, "warn")
    bad = [x for x in warn if RISK_WARN_BLOCK.search(x)]
    if bad:
        return False, "RugCheck warning: " + ", ".join(bad[:2])
    lp = num(r.get("lpLocked"))
    if lp is None or lp < MIN_LP_LOCKED:
        return False, "RugCheck: only %s%% of liquidity locked" % ("?" if lp is None else round(lp))
    top1, top10, ins, hold = num(r.get("top1Pct")), num(r.get("top10Pct")), num(r.get("insiders")), num(r.get("holders"))
    if top1 is not None and top1 > MAX_TOP1:
        return False, "RugCheck: one wallet holds %d%%" % round(top1)
    if top10 is not None and top10 > MAX_TOP10:
        return False, "RugCheck: top 10 wallets hold %d%%" % round(top10)
    if ins is not None and ins > MAX_INSIDERS:
        return False, "RugCheck: %d insider wallets" % ins
    creator = num(r.get("creatorPct"))
    if creator is not None and creator > MAX_CREATOR_PCT:
        return False, "RugCheck: the creator still holds %d%%" % round(creator)
    dv = r.get("dev") or {}
    dev_pct = num(dv.get("devPct"))
    if dev_pct is not None and dev_pct > MAX_CREATOR_PCT:
        return False, "the creator still holds %d%% (Jupiter)" % round(dev_pct)
    if dv.get("devSold"):
        age = num(dv.get("devSellAgeMin"))
        return False, "the creator sold %s" % (("%d minutes ago" % age) if age is not None else "within the last hours")
    if dv and dv.get("mintAuthOff") is False:
        return False, "mint authority still active (Jupiter)"
    dev_note = ""
    if dv:
        dev_note = ", creator holds %s%%" % (round(dev_pct) if dev_pct is not None else "?") + (", no creator sale in 3h" if dv.get("txs3h") is not None else "")
    if hold is not None and hold < MIN_HOLDERS:
        return False, "RugCheck: only %d holders" % hold
    return True, "RugCheck: no danger flags, %d%% of liquidity locked" % round(lp) + (", top 10 wallets hold %d%%" % round(top10) if top10 is not None else "") + \
        (", %d holders" % hold if hold is not None else "") + (", %d insiders" % ins if ins else "") + dev_note + (" (warnings: " + ", ".join(warn[:2]) + ")" if warn else "")


def risk_doc(r):
    if not isinstance(r, dict):
        return None
    doc = {"score": num(r.get("score")), "lpLocked": num(r.get("lpLocked")), "danger": names(r, "danger")[:6], "warn": names(r, "warn")[:6],
           "holdersN": num(r.get("holders")), "top1": num(r.get("top1Pct")), "top10": num(r.get("top10Pct")), "insiders": num(r.get("insiders")),
           "creatorPct": num(r.get("creatorPct")), "mutable": r.get("mutable"), "launchpad": r.get("launchpad")}
    dv = r.get("dev")
    if isinstance(dv, dict):
        doc["dev"] = {k: dv.get(k) for k in ("devPct", "devSold", "devSellAgeMin", "mintAuthOff", "freezeAuthOff", "txs3h", "jupHolders", "organic") if dv.get(k) is not None}
    if r.get("holdersTop"):
        doc["holders"] = list(r["holdersTop"])[:40]      # kept in snapshots so scored coins can credit their wallets
    return doc


def soft_rows(rows, held, recent):
    """Coins that failed only the soft (momentum/age) gates, best score first: the fallback pool of recommend mode."""
    max_age = (GATE_MAX_AGE_H or 1e9) * FALLBACK_MAX_AGE_X
    out = [r for r in rows if not r["ok"] and r["fails"] and set(r["fails"]) <= set(SOFT_GATES) and r["a"] not in held and r["a"] not in recent
           and (r["basic"].get("age_h") is None or r["basic"]["age_h"] <= max_age) and (r["f"].get("c6") is None or r["f"]["c6"] >= 0)]
    out.sort(key=lambda r: -r["sc"])
    return out


def cmd_shortlist(d, now, force=False, snapshot=False, recommend=False):
    pos, pairs = positions(d), load_pairs(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    room = PICKS_PER_RUN if recommend else pick_room(state, pos, now, force)[0]
    w, _ = blended_weights(d)
    rows, _, held, recent, risk = scan(d, pos, pairs, now, w)
    cands = [r for r in rows if r["ok"] and r["a"] not in held and r["a"] not in recent and r["a"] not in risk]
    short = cands[:SHORTLIST] if room > 0 else []
    if recommend and room > 0 and len(short) < SHORTLIST:      # the fallback pool needs RugCheck reports too
        short += [r for r in soft_rows(rows, held, recent) if r["a"] not in risk][:SHORTLIST - len(short)]
    more = cands[len(short):len(short) + RC_BIG] if (snap_due(d, now) or snapshot) else []
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
def cmd_run(d, mode, now, force=False, snapshot=False, recommend=False):
    out_dir = os.path.join(d, "out")
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.json")):
        os.remove(old)
    pos, pairs = positions(d), load_pairs(d)
    state = load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    marks = load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    miss = dict(marks.get("miss") or {})
    asked = mode
    if recommend:                       # recommend mode: scan and rank as for a pick, but write recommendations instead of positions
        mode, room = "pick", PICKS_PER_RUN
    else:
        room = pick_room(state, pos, now, force)[0] if mode == "pick" else 0   # --force: a manual pick run (the bankroll still caps it)
    if mode == "pick" and room <= 0:
        mode = "check"
    n_open = sum(1 for p in pos.values() if p["_left"] > 1e-9)
    writes, exits_done, picks_done, emitted = [], [], [], {}
    run_id = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")

    def emit(coll, doc_id, data):
        fn = os.path.join(out_dir, "%s__%s.json" % (coll, doc_id))
        with open(fn, "w", encoding="utf-8") as f:
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
    zmodel, umodel, zmax, rec_bar, trained_n = load_train(d)     # the zero and profit models and the limits the last training left
    rows, fail_count, held, recent, risk = scan(d, pos, pairs, now, w)
    gated = [r for r in rows if r["ok"]]
    flagged, unchecked, chosen, zero_flagged = [], 0, [], 0

    def clean(r):
        """RugCheck's verdict, then the zero model's: (ok, text); None when no report came back."""
        ok_r, rtxt = risk_view(risk.get(r["a"]))
        if ok_r:
            ok_r, rtxt = zero_view(zmodel, umodel, zmax, r, rtxt)
        return ok_r, rtxt
    day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    tickets = bankroll(pos)["tickets"]
    if mode == "pick":
        for r in gated:
            if r["a"] in held or r["a"] in recent:
                continue
            ok_r, rtxt = clean(r)
            if ok_r is None:
                unchecked += 1
                if unchecked > SHORTLIST:
                    break
            elif not ok_r:
                flagged.append({"sym": r["pr"].get("symbol"), "risk": rtxt})
                zero_flagged += 1 if rtxt.startswith("training model") else 0
            else:
                chosen.append((r, rtxt))
                if len(chosen) >= room:
                    break
        if recommend and len(rows) < MIN_SCAN_FOR_REC:
            # a broken fetch (rate limit, outage) must not replace yesterday's recommendations with scraps
            parts_extra = "Only %d coins came back from the sources (rate limit or outage), so the recommendations were left as they were." % len(rows)
            picks_done.append({"grp": "skipped", "sym": "-", "score": 0, "why": parts_extra})
            chosen = []
        tiers = {}
        if recommend and len(rows) >= MIN_SCAN_FOR_REC:
            # no positions: the best clean coins and the runners-up go to memebot/recommend for the page. There is always a
            # pick: "strong" from MIN_REC_SCORE, "weak" below it, "fallback" when no clean coin passed every gate (the best
            # clean coin that failed only the soft momentum/age gates, labelled with them), and "risky" when nothing is clean
            # at all: the coin with the best trained odds among the tradable ones, shown with its flag and its odds.
            for r, _ in chosen:
                tiers[r["a"]] = "strong" if r["sc"] >= rec_bar else "weak"
            if not chosen:
                for r in soft_rows(rows, held, recent):
                    ok_r, rtxt = clean(r)
                    if ok_r is False and rtxt.startswith("training model"):
                        flagged.append({"sym": r["pr"].get("symbol"), "risk": rtxt}); zero_flagged += 1
                    if ok_r:
                        chosen.append((r, rtxt)); tiers[r["a"]] = "fallback"
                        break
            if not chosen:
                for r in risky_rows(rows, held, recent, zmodel, umodel):
                    ok_r, rtxt = risk_view(risk.get(r["a"]))
                    if ok_r is None:
                        rtxt = "no safety report came back for it"
                    chosen.append((r, "%s; %s" % (rtxt, odds_text(r)) if odds_text(r) else rtxt)); tiers[r["a"]] = "risky"
                    break

            def rec(r, rtxt, ok):
                pr = r["pr"]
                if "zp" not in r:
                    r["zp"], r["up"] = chances(zmodel, umodel, r["f"])
                return {"sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48], "addr": r["a"], "pair": pr.get("pairAddress"), "dex": pr.get("dexId"),
                        "px": r["basic"]["price"], "mc": r["basic"]["mc"], "liq": r["basic"]["liq"], "vol": r["basic"]["vol24"], "score": r["sc"], "rank": r.get("rank"),
                        "why": why_text(r), "safety": rtxt, "ok": ok, "x": x_link(pr), "f": pos_factors(r["f"]), "src": (pr.get("tags") or [])[:12], "risk": risk_doc(risk.get(r["a"])),
                        "tier": tiers.get(r["a"]), "relaxed": [fail_text(k) for k in r["fails"]] if tiers.get(r["a"]) in ("fallback", "risky") else [], "zeroP": r.get("zp"), "upP": r.get("up")}
            runners = []
            for r in gated[:12]:
                if r["a"] in {c[0]["a"] for c in chosen}:
                    continue
                ok_r, rtxt = clean(r)
                runners.append(rec(r, rtxt, ok_r))
            reason = "" if chosen else "no coin in the scan had a tradable pair with the minimum liquidity and market cap"
            emit("memebot", "recommend", {"t": now, "rule": RULE, "scanned": len(rows), "passed": len(gated), "picks": [rec(r, rtxt, True) for r, rtxt in chosen],
                                          "runnersUp": runners[:8], "flagged": flagged[:8], "reason": reason, "zeroLimit": zmax if zmodel else None, "trained": trained_n, "scoreBar": rec_bar})
            if chosen:   # the track record: every recommendation is priced again EVAL_H later (see rec_outcomes)
                emit("memerec", run_id, {"t": now, "rule": RULE, "picks": [{"sym": str(r["pr"].get("symbol") or "?")[:24], "addr": r["a"], "pair": r["pr"].get("pairAddress"),
                                                                            "px": r["basic"]["price"], "mc": r["basic"]["mc"], "score": r["sc"], "zp": r.get("zp"), "up": r.get("up"), "tier": tiers.get(r["a"])} for r, _ in chosen]})
            picks_done += [{"grp": "recommend", "sym": r["pr"].get("symbol"), "name": r["pr"].get("name"), "addr": r["a"], "score": r["sc"], "tier": tiers.get(r["a"]),
                            "why": ("%s pick; " % tiers.get(r["a"]) if tiers.get(r["a"]) != "strong" else "") + why_text(r) + "; " + rtxt} for r, rtxt in chosen]
            chosen = []
        elif recommend:
            chosen = []
        for i, (r, rtxt) in enumerate(chosen):
            pr, a = r["pr"], r["a"]
            ticket_i = tickets[i] if i < len(tickets) else TICKET
            pid = "%s-p-%s-%s" % (day, slug(pr.get("symbol")), a[:6])
            emit("memepos", pid, {"grp": "pick", "addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48],
                                  "pair": pr.get("pairAddress"), "dex": pr.get("dexId"), "t": now, "px": r["basic"]["price"], "mc": r["basic"]["mc"],
                                  "liq": r["basic"]["liq"], "vol": r["basic"]["vol24"], "score": r["sc"], "rank": r.get("rank"),
                                  "why": why_text(r) + "; " + rtxt, "safety": rtxt, "x": x_link(pr), "xKnown": True, "f": pos_factors(r["f"]),
                                  "src": (pr.get("tags") or [])[:12], "risk": risk_doc(risk.get(a)), "ticket": ticket_i, "rule": RULE,
                                  "weights": {k: v for k, v in sorted(w.items(), key=lambda kv: -abs(kv[1]))[:12]}})
            picks_done.append({"grp": "pick", "sym": pr.get("symbol"), "name": pr.get("name"), "addr": a, "why": why_text(r) + "; " + rtxt, "score": r["sc"], "ticket": ticket_i})
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
    if rows and (snap_due(d, now) or snapshot):
        coins = [snap_coin(r, risk.get(r["a"])) for r in rows if r["basic"]["price"]]
        for k in range(0, len(coins), SNAP_CHUNK):
            part = coins[k:k + SNAP_CHUNK]
            emit("memesnap", "%s-%d" % (run_id, k // SNAP_CHUNK + 1), {"t": now, "rule": RULE, "n": len(part), "part": k // SNAP_CHUNK + 1,
                                                                        "total": len(coins), "coins": part})
        snap_n = len(coins)
    deferred, dropped = 0, 0
    for sid, sn in due_snaps(d, now).items():
        coins = [c for c in sn["coins"] if isinstance(c, dict)]
        priced = sum(1 for c in coins if pairs.get(c.get("a")) and num(pairs[c.get("a")].get("priceUsd")))
        late = bool(coins) and priced < 0.7 * len(coins)
        if late and now - (num(sn.get("t")) or now) < (EVAL_H + 1.0) * 3_600_000:
            deferred += 1               # the price fetch failed for most of them (outage, rate limit): score this snapshot next run;
            continue                    # an hour past the horizon it is scored anyway, but then only the coins that did get a price count
        res = [snap_result(c, pairs) for c in coins if not late or (pairs.get(c.get("a")) and num(pairs[c.get("a")].get("priceUsd")))]
        unpriced = len(coins) - len(res)
        dropped += unpriced
        if not res:
            continue
        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
        cl = lambda r: clamp(r["eur"], EUR_CLIP[0], EUR_CLIP[1])      # one 1000x dust coin must not set the group average
        p_ok, p_no = [cl(r) for r in res if r["pass"]], [cl(r) for r in res if not r["pass"]]
        top = [cl(r) for r in res if r.get("rank") and r["rank"] <= 10]
        emit("memesnapres", sid, {"t": now, "t0": num(sn.get("t")), "rule": sn.get("rule"), "n": len(res), "passN": len(p_ok), "passAvg": avg(p_ok),
                                  "failN": len(p_no), "failAvg": avg(p_no), "top10N": len(top), "top10Avg": avg(top), "unpriced": unpriced, "coins": res})
        big.append((len(res), avg(p_ok), len(p_ok), avg(p_no), len(top), avg(top), len(p_no)))
        scored_n += len(res)
    if scored_n:
        # new results -> re-learn and save the weights the next runs will use
        all_res = dict(load_docs(d, "memesnapres")); all_res.update(emitted.get("memesnapres", {}))
        rows_l = [(c["f"], clamp(num(c["eur"]), EUR_CLIP[0], EUR_CLIP[1])) for doc in all_res.values() if usable_result(doc) for c in (doc.get("coins") or [])
                  if isinstance(c, dict) and isinstance(c.get("f"), dict) and num(c.get("eur")) is not None and learnable(c)]
        learned, n_l, detail = learn(rows_l)
        emit("memeweights", run_id, {"t": now, "rule": RULE, "n": n_l, "lambda": round(clamp(n_l / float(LEARN_FULL_N)), 3), "learned": learned,
                                     "prior": PRIOR, "detail": {k: v for k, v in sorted(detail.items(), key=lambda kv: -abs(kv[1]["rho"]))[:40]}})

    # ---------- the recommendation track record: price each past tip again once its horizon has passed ----------
    rec_scored = []
    for rid, doc in load_docs(d, "memerec").items():
        t0 = num(doc.get("t"))
        if not isinstance(doc, dict) or doc.get("out") or not t0 or now - t0 < EVAL_H * 3_600_000 or str(doc.get("rule") or RULE) != RULE:
            continue
        outs = []
        for p in doc.get("picks") or []:
            pr = pairs.get(p.get("a") or p.get("addr"))
            px0, px1 = num(p.get("px")), num(pr.get("priceUsd")) if pr else None
            if not px0:
                continue
            if px1 is None and now - t0 < (EVAL_H + 1.0) * 3_600_000:
                outs = None; break                   # no price yet (fetch outage): try again next run, up to an hour late
            mult = (px1 / px0) if px1 else 0.0
            invested = TICKET - fee(TICKET); gross = invested * mult
            outs.append({"sym": p.get("sym"), "mult": round(mult, 4), "eur": round((max(0.0, gross - fee(gross)) if gross > 0 else 0.0) - TICKET, 2), "gone": not px1})
        if outs:
            doc = dict(doc, out={"t": now, "h": round((now - t0) / 3_600_000, 2), "picks": outs})
            emit("memerec", rid, doc)
            rec_scored += outs

    # ---------- note, state, marks, run log ----------
    parts = []
    top_fail = sorted(fail_count.items(), key=lambda x: -x[1])[:3]
    if mode == "pick":
        parts.append("Scanned %d coins from %d sources; %d passed the gates." % (len(rows), len(load_lists(d)) + sum(1 for t in {t for r in rows for t in (r["pr"].get("tags") or [])} if t.startswith("kw:")), len(gated)))
        if top_fail:
            parts.append("Most common gate: " + "; ".join("%s (%d)" % (fail_text(k2), v) for k2, v in top_fail) + ".")
        if flagged:
            parts.append("%s flagged %s, so %s skipped." % ("Safety checks" if zero_flagged else "RugCheck",", ".join("%s (%s)" % (x["sym"], re.sub(r"^RugCheck( danger| warning)?: ", "", x["risk"])) for x in flagged[:3]),
                                                                  "it was" if len(flagged) == 1 else "they were"))
        rs = [x for x in picks_done if x["grp"] == "recommend"]
        ps = [x for x in picks_done if x["grp"] == "pick"]
        sk = [x for x in picks_done if x["grp"] == "skipped"]
        if sk:
            parts.append(sk[0]["why"])
        elif rs:
            parts.append("Recommended " + ", ".join("%s (score %.0f)" % (x["sym"], x["score"]) for x in rs) + " for the next %s; nothing bought (recommend mode)." % HORIZON)
        elif recommend:
            parts.append("No recommendation: no top coin had a clean safety report." if gated else "No recommendation: nothing passed the gates.")
        elif ps:
            parts.append("Picked " + ", ".join("%s (score %.0f, %.2f)" % (x["sym"], x["score"], x.get("ticket", TICKET)) for x in ps) +
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
        if zmodel:
            parts.append("Zero model: trained on %d coin results, a clean coin is skipped above a %d%% zero chance; when nothing is clean the best odds are named as a risky pick." % (trained_n, round(100 * zmax)))
    else:
        parts.append(("Checked %d open fake position%s." % (n_open, "" if n_open == 1 else "s")) if n_open else "No open fake positions to check.")
        if n_open and not exits_done:
            parts.append("Nothing hit a sell rule.")
    if exits_done:
        parts.append("Sold: " + "; ".join("%s (%s, %s, %.2f back)" % (x["sym"], "bot" if x["grp"] in ("pick", "early") else "random", x["why"], x["eur"]) for x in exits_done) + ".")
    if rec_scored:
        parts.append("Track record: %d earlier tip%s priced again after %s: %s." % (len(rec_scored), "s" if len(rec_scored) > 1 else "", eval_text(),
                     ", ".join("%s %.2fx (%+.2f per 20)" % (o["sym"], o["mult"], o["eur"]) for o in rec_scored)))
    if deferred:
        parts.append("Big test postponed for %d snapshot%s: most of its coins came back without a price this run." % (deferred, "s" if deferred > 1 else ""))
    if dropped:
        parts.append("%d coins of a late-scored snapshot had no price and were left out rather than counted as zero." % dropped)
    if snap_n:
        parts.append("Saved all %d scanned coins for the big test; they get priced again in %s." % (snap_n, eval_text()))
    if big:   # one line for all chunks of the scored snapshot
        wavg = lambda i_n, i_a: (sum(b[i_a] * b[i_n] for b in big if b[i_a] is not None) / max(sum(b[i_n] for b in big if b[i_a] is not None), 1)) if any(b[i_a] is not None for b in big) else None
        n_all, n_ok, n_no, n_top = (sum(b[i] for b in big) for i in (0, 2, 0, 4))
        n_no = n_all - n_ok
        a_ok, a_no, a_top = wavg(2, 1), wavg(6, 3), wavg(4, 5)   # each average weighted by its own group's count per chunk
        parts.append("Big test: %d coins from the earlier scan, %s later: %s." % (n_all, eval_text(), "; ".join(x for x in [
            "the %d that passed the gates averaged %+.2f per 20" % (n_ok, a_ok) if n_ok and a_ok is not None else "",
            "the bot's top 10 averaged %+.2f" % a_top if a_top is not None else "",
            "the other %d averaged %+.2f" % (n_no, a_no) if a_no is not None else ""] if x)))
    all_pos = dict(load_docs(d, "memepos")); all_pos.update(emitted.get("memepos", {}))
    all_ex = dict(load_docs(d, "memeexit")); all_ex.update(emitted.get("memeexit", {}))
    cash_after = bankroll(positions_from(all_pos, all_ex))
    parts.append("Bankroll: %.2f free of %.0f, %d open." % (cash_after["free"], BUDGET, cash_after["open"]))
    note = " ".join(parts)
    runs = int(state.get("runs") or 0) + 1
    emit("memebot", "state", {"rule": RULE, "horizon": HORIZON, "evalH": EVAL_H, "ticket": TICKET, "budget": BUDGET, "started": state.get("started") or now, "lastRun": now, "runs": runs,
                              "lastMode": mode, "lastPick": now if mode == "pick" else state.get("lastPick"), "note": note, "cash": cash_after,
                              "scanned": len(rows) if mode == "pick" or snap_n else state.get("scanned"),
                              "passed": len(gated) if mode == "pick" or snap_n else state.get("passed"),
                              "bigSnapT": now if snap_n else state.get("bigSnapT"), "bigSnapN": snap_n or state.get("bigSnapN"),
                              "weightsN": winfo["n"], "lastEarly": state.get("lastEarly")})
    emit("memebot", "marks", new_marks)
    emit("memecurve", run_id, curve_point(all_pos, all_ex, new_marks["px"], now))
    emit("memeruns", run_id, {"t": now, "mode": mode, "rule": RULE, "scanned": len(rows), "passed": len(gated),
                              "flagged": flagged, "picks": picks_done, "exits": exits_done, "note": note})
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
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
    ap.add_argument("cmd", choices=["mode", "gather", "shortlist", "run", "train", "learn", "analyze", "wallets", "cash"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--mode", choices=["pick", "check"], default="check")
    ap.add_argument("--now", type=float, default=None)
    ap.add_argument("--force", action="store_true", help="manual run: pick even inside the 3-hour gap or the daily cap (the bankroll still caps it)")
    ap.add_argument("--snapshot", action="store_true", help="manual rescan: save a big-test snapshot of this scan even if the last one is recent")
    ap.add_argument("--recommend", action="store_true", help="no buys: write the two best clean coins to memebot/recommend instead of opening positions")
    ap.add_argument("--horizon", default=os.environ.get("MEMEBOT_HORIZON", "24h"), choices=sorted(PROFILES), help="rule profile: 24h (survive a day) or 2h (pump in the next two hours)")
    a = ap.parse_args()
    apply_profile(a.horizon)
    now = int(a.now if a.now else time.time() * 1000)
    if a.cmd == "mode":
        cmd_mode(a.dir, now, a.force, a.snapshot, a.recommend)
    elif a.cmd == "gather":
        cmd_gather(a.dir, now)
    elif a.cmd == "shortlist":
        cmd_shortlist(a.dir, now, a.force, a.snapshot, a.recommend)
    elif a.cmd == "train":
        cmd_train(a.dir, now)
    elif a.cmd == "learn":
        cmd_learn(a.dir)
    elif a.cmd == "analyze":
        cmd_analyze(a.dir)
    elif a.cmd == "wallets":
        cmd_wallets(a.dir)
    elif a.cmd == "cash":
        cmd_cash(a.dir)
    else:
        cmd_run(a.dir, a.mode, now, a.force, a.snapshot, a.recommend)


if __name__ == "__main__":
    main()
