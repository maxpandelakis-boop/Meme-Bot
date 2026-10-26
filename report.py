#!/usr/bin/env python3
"""report.py: the analysis page. Renders everything in db/ as one self-contained HTML file (mb/report.html).

  python3 report.py [--dir mb] [--out mb/report.html] [--fragment]

bot.py writes it after every cycle, so the page is always the state after the last run. Open it in a browser (it is a plain
file, no server needed). --fragment leaves out the <html>/<head>/<body> wrapper for hosts that add their own.

In recommend mode the page has four tabs, the same on the website and in the app (app.py PAGE_JS draws them as its bottom bar):
Pick (the full scan's strip, the pick with one heading by its tier, the hour grid and one Details fold: the tip record, the training,
the coin test, all candidates, the weights, the run log), Radar (page_radar.py: the launch radar and its paper positions; until the
switch, memebot.switch_at(), the full scan's new launches under it), Traders (page_traders.py: the three paper traders on the same
finished trades, from traders.load) and Office (the radar's desk, the agent office). Nothing of the account sits outside the panes.
Pick mode keeps its sections in reading order: the big test (how the gated coins, the bot's top 10 and the rest did against the
"price unchanged" baseline), bankroll and equity (hero), equity curve per run, the bought coins (open positions with their last
price, sell levels and the bot's reasons), closed trades with their result, the top candidates of the last full scan and why they
were not bought, the factor weights in use (with a glossary) and the run log. Times are shown in Europe/Berlin, the bot's own trading day.
"""
import argparse, html, json, math, os, re, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
try:
    import page_radar as PR  # the launch radar on the Radar tab, the trap-check line and the "no good coin" marks (WP5b)
except ModuleNotFoundError as e:  # only a copy of the code without page_radar.py (the selftest's stand-in spotter): no radar parts; any other error is raised
    if e.name != "page_radar":
        raise
    PR = __import__("types").SimpleNamespace(pane=lambda D, mid="": "", block=lambda D, mid="": "", CSS="", JS="", tab_label=lambda: "", young=lambda D: {}, row_chips=lambda rt: "", row_attr=lambda rt: "", row_safety=lambda rt, chip: chip,
                                             card_safety=lambda c, chip: chip, young_head=lambda t, rows: "", card_trap=lambda c, now=None: "", pick_banner=lambda picks: "")

TITLE = "Meme-Bot Ledger"
E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
try:
    from zoneinfo import ZoneInfo
    TZ, TZ_NAME = ZoneInfo("Europe/Berlin"), "Berlin"
except Exception:   # no tz database: fall back to UTC
    TZ, TZ_NAME = dt.timezone.utc, "UTC"
WIDE, NARROW = 1052, 324          # chart widths in CSS px: the desktop column and the phone card's inner width at 390px (nothing scrolls)
TRACK_AT_MIN_PX = 76              # a paper row's price bar: the entry label starts at least this far in, clear of "stop −30%" at the left end,
TRACK_AT_MIN_W = 560              # and shows only on a bar at least this wide (on a narrower one the entry tick sits under the stop label)
MINUS = "\u2212"                  # a real minus sign for every negative number on the page
_flat = M.TICKET - M.fee(M.TICKET)
FLAT = round(max(0.0, _flat - M.fee(_flat)) - M.TICKET, 2)   # what 20 becomes when the price does not move: the two fees
WHY = {"target": "hit 2x, half sold", "stop": "−50% stop", "time": "3-day limit", "back to entry": "fell back to entry", "rug": "price gone", "manual": "sold by hand",
       "tp": "take-profit", "filters": "failed the filters", "reset": "closed at the restart"}
LEGACY_HOLD_H = 48         # the hold rule before the paper account v2 sold after 48 hours (its position docs do not say so)
GATE_SHORT = {"crash": "crashed", "spike": "spiked", "mc": "market cap out of range", "liq": "liquidity gone", "vol": "volume dried up", "wash": "wash trading",
              "old": "too old", "honeypot": "honeypot"}


def exit_label(e, p=None):
    """Why a sale happened, in words, by the rule the position was bought under: the paper account's reasons (take-profit +1000%,
    stop-loss -30%, 6-hour limit, rug, reset); the hold rule before it (its own take-profit level, the filters it failed, 48 hours);
    pick mode's own."""
    p = p if isinstance(p, dict) else {}
    w = str(e.get("why") or "?")
    if w == "filters" and e.get("gates"):
        return "failed the filters (%s)" % ", ".join(GATE_SHORT.get(g, g) for g in e["gates"])
    if p.get("grp") in M.PAPER_GROUPS and p.get("paper"):
        return re.sub(r" -(?=\d)", " " + MINUS, M.exit_word(w, p.get("grp"), M.is_chart(p)))
    if p.get("grp") == "hold" and w == "tp":
        return "take-profit +%d%%" % round(100 * (M.num(p.get("tp")) or 0.4))
    if p.get("grp") == "hold" and w == "time":
        return "%d-hour limit" % LEGACY_HOLD_H
    return WHY.get(w, w)


def fmt_eur(v):
    """A paper ticket as the user named it: 50 €, 3 €, with a no-break space so the € never wraps away from its number."""
    v = M.num(v)
    return "–" if v is None else M.eur_text(v)


def group_tag(p):
    """The paper position's group and ticket in one tag: top pick · 50 €, new launch · 3 €; a hold position of the rule before
    the restart is "old rule · 20 €"."""
    return "%s · %s" % ("old rule" if not p.get("paper") else ("new launch" if p.get("grp") == "young" else "top pick"), fmt_eur(p.get("ticket")))


def hold_rule_text(now=None):
    """How a paper position is sold, in full (the Open positions fold): memebot.PAPER_LABEL, the one wording of the rule on the page, and how
    it is carried out: the chart exit (memebot.chart_hit, since Oct 24) on the live chart, every minute; before memebot.LIVE_SELL_AT the
    fixed rule's minute closes."""
    live = (now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp() * 1000) >= M.live_sell_at()
    chart = ("on the live chart, looked at every minute: as soon as a minute's low reaches %d%% of the entry price or lower (the floor, booked at "
             "that low); once a minute's high has reached %g times the entry price, as soon as a minute's low falls %d%% under the highest price so "
             "far (the trailing stop, booked at that low; a minute that closes under that line right after a new high, at its close); as soon as a "
             "minute closes %d%% or more under its close %d minutes before (at that close); as soon as a minute's high reaches %g times the entry "
             "price (booked at exactly that level); %d hours after the purchase (at that minute's price); or when the price or the liquidity is gone "
             "(the pool is gone). Each sale is booked at the minute it happened, the next scan shows it. The rule since Oct 24 (the fixed rule "
             "before it, −%d%% / %gx / %d h, keeps running as a shadow rule on the same trades)." % (
                 round(100 * (1 - M.CHART_STOP)), M.CHART_ARM, round(100 * M.CHART_TRAIL), round(100 * M.CHART_DROP), M.CHART_DROP_MIN, 1 + M.HOLD_TP,
                 round(M.HOLD_MAX_H), round(100 * M.HOLD_STOP), 1 + M.HOLD_TP, round(M.HOLD_MAX_H)))
    how = chart if live else (
          "at the first minute candle that closes at %g times the entry price (booked at exactly that level), at the first one that closes at "
          "%d%% of it or lower (booked at that close: a crash through the level fills worse, never better), at the first scan after about %d hours (at "
          "that scan's price), or when the price or the liquidity is gone (the pool is gone). A scan without new candles checks both levels on its own "
          "price." % (1 + M.HOLD_TP, round(100 * (1 - M.HOLD_STOP)), round(M.HOLD_MAX_H)))
    return ("Fake money, no budget. Each scan's top pick is bought on paper for %s; the first %d new launches of each scan for %s each until %s, every coin "
            "the launch radar finds without traps for %s from then on. A coin that is held is not bought again. Each position %s, whichever comes first, "
            "all of it: %s Failing a filter sells nothing. Paper fees: %g%% per trade, at least %s; the tip record keeps %g%%, at least %s." % (
                fmt_eur(M.TOP_TICKET), M.YOUNG_BUY_N, fmt_eur(M.YOUNG_TICKET), local(M.switch_at()).strftime("%b %d, %H:%M"), fmt_eur(radar_ticket()),
                M.PAPER_LABEL, how, 100 * M.PAPER_FEE_PCT, _eur(M.PAPER_FEE_MIN), 100 * M.FEE_PCT, _eur(M.FEE_MIN)))


SRC = {"kw": "search “%s”", "gt": "GeckoTerminal %s", "pf": "pump.fun %s", "list": "DexScreener %s", "jup": "Jupiter %s", "gm": "GMGN %s"}
LIST_NAMES = {"reddit": "Reddit posts", "cgMeme": "CoinGecko meme list", "cmcGain": "CoinMarketCap gainers", "rayVol": "Raydium top pools", "llNew": "LaunchLab new", "llHot": "LaunchLab hot", "llMc": "LaunchLab biggest",
              "rcNew": "RugCheck new", "rcTrending": "RugCheck trending", "rcRecent": "RugCheck recent", "rcVerified": "RugCheck verified"}
FACTOR = {"lp.trusted": "launchpad pump.fun / Bonk / Bags", "lp.other": "launchpad elsewhere (bundle-prone)", "ds.paid": "DEX paid (DexScreener profile)", "ds.paidAgeH": "DEX paid: hours since payment", "ds.ads": "paid DexScreener ads", "ds.cto": "community takeover (DexScreener)",
          "vt.likes": "source tweet: likes (log)", "vt.replies": "source tweet: replies (log)", "vt.ageH": "source tweet: age in hours", "vt.fresh": "source tweet posted within 48h",
          "vt.followers": "source tweet: author's followers (log)", "vt.verified": "source tweet: verified author", "vt.media": "source tweet has a picture or video",
          "vt.tweet": "X link is a single tweet", "theme.animal": "animal story",
          "liqMc": "liquidity ÷ market cap", "volMc": "24h volume ÷ market cap", "logLiq": "liquidity (log)", "logMc": "market cap (log)",
          "buyShare": "share of buys, 24h", "buyRatio1h": "buys ÷ sells, 1h", "buyRatio6h": "buys ÷ sells, 6h", "buys1": "buys, last hour", "buys24": "buys, 24h",
          "c1": "price change 1h", "c6": "price change 6h", "c24": "price change 24h", "m5": "price change 5 min", "ageH": "age in hours",
          "vol1Share": "share of volume in last 1h", "vol6Share": "share of volume in last 6h", "fdvMc": "FDV ÷ market cap", "boosts": "DexScreener boosts",
          "nPairs": "number of pairs", "nDex": "number of DEXes", "x": "has an X account", "web": "websites", "socN": "social links",
          "srcN": "source lists naming it", "kwN": "keyword searches naming it", "src.pf": "on pump.fun",
          "rd.posts": "Reddit posts naming it, 48h", "rd.subs": "subreddits naming it", "rd.fresh": "hours since the newest Reddit post", "rd.byAddr": "Reddit post with its address",
          "cgm.listed": "on CoinGecko's Solana meme list", "cgm.rank": "CoinGecko market-cap rank", "cgm.chg1h": "CoinGecko 1h change", "cmc.search": "in CoinMarketCap's top searches",
          "cmc.searchRank": "CoinMarketCap search rank", "cmc.gain": "on CoinMarketCap's Solana gainers",
          "gp.risk": "GoPlus risk flags", "gp.trusted": "GoPlus trusted token", "gp.holders": "holders (GoPlus)", "gp.top10": "top 10 wallets % (GoPlus)", "gp.lpBurn": "LP burned % (GoPlus)", "gp.dexN": "DEX pools (GoPlus)",
          "gi.score": "GeckoTerminal score", "gi.holders": "holders (GeckoTerminal)", "gi.top10": "top 10 wallets % (GeckoTerminal)",
          "cm.rcUp": "RugCheck community up-votes", "cm.rcDown": "RugCheck community down-votes", "cm.rcNet": "RugCheck community vote balance", "cm.cgWatch": "CoinGecko watchlists",
          "cm.cgTwitter": "X followers (CoinGecko)", "cm.cgSentUp": "CoinGecko sentiment up %", "cm.stWatch": "StockTwits watchers", "cm.stMsgs": "StockTwits messages 24h",
          "cm.xFollowers": "X followers", "cm.xTweets": "tweets in 7 days", "cm.tgSubs": "Telegram members", "cm.tgMsgs": "Telegram messages 24h",
          "mkt.sol24": "SOL 24h change (market)", "mkt.btc24": "BTC 24h change (market)", "mkt.fng": "fear & greed index (market)",
          "hl.top1": "biggest wallet % (chain)", "hl.top10": "top 10 wallets % (chain)", "hl.top20": "top 20 wallets % (chain)",
          "bq.trades1h": "on-chain trades, last hour", "bq.buyers1h": "on-chain buyers, last hour", "bq.sellers1h": "on-chain sellers, last hour", "bq.netUsd1h": "on-chain net flow $, last hour",
          "bq.topBuyerShare": "biggest buyer's share of buying", "bq.traders": "on-chain traders, 6h", "bq.buyerRatio": "on-chain buyers ÷ sellers, 1h", "fl.rate1h": "swaps in the last hour (public RPC)", "fl.buyers": "buyers in the RPC sample", "fl.sellers": "sellers in the RPC sample",
          "fl.buyerRatio": "RPC sample buyers ÷ sellers", "fl.flip": "wallets that bought and sold (RPC sample)", "fl.topBuyer": "biggest buyer's share (RPC sample)",
          "fl.netUsd": "net buying in USD (RPC sample)", "fl.netShare": "net buying share (RPC sample)",
          "lct.interactions": "X/social interactions 24h (LunarCrush)", "lct.posts": "social posts 24h (LunarCrush)", "lct.contributors": "social contributors (LunarCrush)", "lct.sentiment": "social sentiment (LunarCrush)", "lct.trend": "social trend (LunarCrush)",
          "soc.match": "LunarCrush match", "soc.eng": "X engagements (LunarCrush)", "soc.ment": "mentions (LunarCrush)", "soc.cre": "creators (LunarCrush)",
          "soc.sent": "sentiment (LunarCrush)", "soc.galaxy": "galaxy score (LunarCrush)", "soc.alt": "alt rank (LunarCrush)",
          "rc.score": "RugCheck risk score", "rc.lp": "% of liquidity locked", "rc.top1": "top holder %", "rc.top10": "top 10 holders %", "rc.holders": "holders (RugCheck)",
          "rc.insiders": "insider wallets", "rc.creator": "creator holds %", "rc.danger": "RugCheck danger flags", "rc.warn": "RugCheck warnings", "rc.mutable": "metadata still mutable",
          "news.hits": "headlines naming it", "news.fresh": "freshness of the newest headline", "news.narr": "heat of its theme in the news",
          "gt.buyers24": "distinct buyers, 24h", "gt.sellers24": "distinct sellers, 24h", "gt.buyerRatio": "buyers ÷ sellers, 24h", "gt.buysPerBuyer": "trades per buyer",
          "gt.trend": "on a GeckoTerminal list", "gt.src": "GeckoTerminal lists naming it", "cg.trend": "CoinGecko trending", "cg.rank": "CoinGecko trending rank", "cg.chg24": "24h change (CoinGecko)",
          "gm.holders": "holders (GMGN)", "gm.top10": "top 10 holders % (GMGN)", "gm.smartDegen": "smart-money holders", "gm.renowned": "renowned holders", "gm.sniper": "sniper holders",
          "gm.bundler": "bundled buys share", "gm.rat": "rat-trader share", "gm.bluechip": "blue-chip owners share", "gm.rugRatio": "dev rug ratio", "gm.wash": "wash trading flagged",
          "gm.hot": "GMGN hot level", "gm.devHold": "dev team holds %", "gm.sniperHold": "snipers hold %", "gm.botDegen": "bot holders", "gm.honeypot": "honeypot flag",
          "gm.creatorHold": "creator still holds", "gm.twRename": "X account renames", "gm.smartShare": "smart-money share of holders", "gm.src": "GMGN lists naming it",
          "tb.n": "top buyers known", "tb.holdShare": "top buyers still holding", "tb.soldShare": "top buyers that sold", "tb.sniperShare": "snipers among top buyers",
          "tb.freshShare": "fresh wallets among top buyers", "tb.botShare": "bots among top buyers", "tb.smartN": "smart wallets among top buyers", "tb.smartHold": "smart wallets still holding",
          "sw.n": "holders with a track record", "sw.avg": "their past result per 20", "sw.wins": "their win share", "sw.lb": "top-profit wallets holding", "sw.lbWin": "their win rate",
          "jup.holders": "holders (Jupiter)", "jup.organic": "organic score (Jupiter)", "jup.top10Pct": "top 10 holders % (Jupiter)", "jup.devMints": "dev mints", "jup.verified": "verified (Jupiter)",
          "jup.traders24": "traders, 24h", "jup.netBuyers24": "net buyers, 24h", "jup.holderChg24": "holder change, 24h", "jup.netBuyers1": "net buyers, 1h",
          "jup.buyVolShare": "buy share of volume", "jup.mcPerHolder": "market cap per holder",
          "dev.pct": "creator holds % (Jupiter)", "dev.sold": "creator sold in the last 3h", "dev.txs3h": "creator transactions, 3h", "dev.authOff": "mint and freeze authority gone",
          "pf.replies": "pump.fun replies", "pf.live": "pump.fun live stream", "pf.athRatio": "all-time-high ÷ now", "pf.twitter": "has X (pump.fun)", "pf.website": "has website (pump.fun)", "pf.telegram": "has Telegram (pump.fun)"}


def factor_label(k):
    if k in FACTOR:
        return FACTOR[k]
    if k.startswith("src."):
        return "on list " + k[4:]
    return k


# ---------------------------------------------------------------- formatting
def sgn(s):
    """A leading ASCII hyphen becomes a real minus sign, so '−0.15' and '−50%' look alike everywhere."""
    return s.replace("-", MINUS, 1) if s[:1] == "-" else s


def fmt_money(v, dollars=True):
    """$9.5k, $103k, $1.5M, $2B: one decimal where it says something, none where it does not."""
    v = M.num(v)
    if v is None:
        return "–"
    s = (MINUS if v < 0 else "") + ("$" if dollars else "")
    v = abs(v)
    one = lambda x: ("%.1f" % x).rstrip("0").rstrip(".")
    if v >= 1e9:
        return "%s%sB" % (s, one(v / 1e9))
    if v >= 1e6:
        return "%s%sM" % (s, one(v / 1e6))
    if v >= 1e3:
        return "%s%sk" % (s, one(v / 1e3))
    return "%s%s" % (s, format(v, ",.0f"))


def fmt_px(p):
    p = M.num(p)
    if p is None or p <= 0:
        return "–"
    if p >= 1:
        return "$" + format(p, ",.2f")
    digits = -int(math.floor(math.log10(p))) + 3
    if digits > 12:
        return "$%.3g" % p
    return "$" + ("%." + str(digits) + "f") % p


def fmt_amt(v, signed=False):
    v = M.num(v)
    if v is None:
        return "–"
    return sgn(("%+.2f" if signed else "%.2f") % v)


def _eur(v, signed=False):
    """1,234.56 € with a real minus sign and a no-break space (page_account.eur's format, the one for euro results on the page)."""
    v = M.num(v)
    if v is None:
        return "n/a"
    t = format(abs(v), ",.2f")
    return (MINUS if v < 0 and t.strip("0.,") else ("+" if signed and v > 0 else "")) + t + "\u00a0€"


def fmt_mult(v):
    v = M.num(v)
    return "–" if v is None else ("%.2fx" % v if v >= 0.1 else "%.3fx" % v)


def fmt_int(v):
    """12,345: counts with a thousands separator."""
    v = M.num(v)
    return "–" if v is None else format(int(round(v)), ",")


def fmt_chg(m):
    """A price multiple as a signed change: 1.047 -> '+4.7%'."""
    m = M.num(m)
    return "–" if m is None else sgn("%+.1f%%" % (100 * (m - 1)))


def be_mult(ticket, fee=None):
    """The price multiple at which a position comes back at its ticket after both fees (buy and sell); fee: the position's fee model."""
    fee = fee or M.fee
    ticket = M.num(ticket) or M.TICKET
    net = ticket - fee(ticket)
    if net <= 0:
        return None
    gross = ticket
    for _ in range(30):                  # gross - fee(gross) = ticket, solved by fixed-point iteration (the fee is flat or a percentage)
        gross = ticket + fee(gross)
    return gross / net


def local(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone(TZ)


def fmt_dt(ms, short=False, day=False):
    ms = M.num(ms)
    if not ms:
        return "–"
    try:
        t = local(ms)
    except (OverflowError, OSError, ValueError):
        return "–"
    if day:
        return t.strftime("%b %d")
    return t.strftime("%b %d %H:%M") if short else t.strftime("%Y-%m-%d %H:%M") + " " + TZ_NAME


def fmt_age(ms, now):
    ms = M.num(ms)
    if not ms:
        return "–"
    h = max(0.0, (now - ms) / 3_600_000)
    if h < 1:
        return "%d min" % round(h * 60)
    if h < 48:
        return "%dh" % round(h)
    return "%.1fd" % (h / 24)


def pct(v):
    v = M.num(v)
    return "–" if v is None else "%d%%" % round(v)


def share(k, n):
    return ("%d (%s)" % (k, pct(100.0 * k / n))) if n else "–"


def clean_ticks(lo, hi, n=4):
    """Round tick values covering [lo, hi]: the first tick is at most one step below lo, the last at most one step above hi."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    ticks, v = [], math.floor(lo / step) * step
    while v <= hi + step * 0.01:
        ticks.append(round(v, 6))
        v += step
    return ticks, step


def domain(vals, pad=0.08):
    """(lo, hi, ticks): the plotted range, padded a little, with ticks that never run more than a fraction of a step past the data."""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    ticks, step = clean_ticks(lo, hi)
    span = hi - lo
    lo2, hi2 = lo - span * pad, hi + span * pad
    ticks = [t for t in ticks if lo2 - step * 0.6 <= t <= hi2 + step * 0.6]
    return min(lo2, ticks[0]) if ticks else lo2, max(hi2, ticks[-1]) if ticks else hi2, ticks


# ---------------------------------------------------------------- data
def iter_docs(d, coll):
    """(doc id, doc) of a collection, one file at a time in name order (memebot.load_docs holds them all: the big test's tens of
    thousands of snapshot files must never sit in memory together). A file that is no JSON object is skipped, as there."""
    folder = os.path.join(d, "db", coll)
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if fn.endswith(".json"):
            doc = M.load_json(os.path.join(folder, fn), None)
            if isinstance(doc, dict):
                yield fn[:-5], doc


class LazyDocs:
    """memebot.load_docs' answer for one collection, read lazily: values() and items() go through the files one at a time (iter_docs)."""

    def __init__(self, d, coll):
        self.d, self.coll = d, coll

    def items(self):
        return iter_docs(self.d, self.coll)

    def values(self):
        return (doc for _, doc in iter_docs(self.d, self.coll))


def blended_weights_lean(d, since=None):
    """memebot.blended_weights(d, since), the same numbers, with the big test's results read one file at a time: its result_rows keeps
    only the factors and results it learns from, not every snapshot whole (about 9 GB on 16 Oct; traps.feed swaps load_docs the same way).
    since: the TRAIN_DAYS window's start the run scored with (M.train_since of its clock)."""
    orig = M.load_docs
    M.load_docs = lambda dd, coll: LazyDocs(dd, coll) if coll == "memesnapres" else orig(dd, coll)
    try:
        return M.blended_weights(d, since)
    finally:
        M.load_docs = orig


def collect(d, now):
    pos = M.positions(d)
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    curve = sorted(M.load_docs(d, "memecurve").values(), key=lambda c: M.num(c.get("t")) or 0)
    runs = sorted(M.load_docs(d, "memeruns").values(), key=lambda r: -(M.num(r.get("t")) or 0))
    cash = M.bankroll(pos)
    px, liq_now, cpx = marks.get("px") or {}, marks.get("liq") or {}, marks.get("cpx") or {}
    since = M.num(state.get("paperSince"))

    rows = []
    for pid, p in pos.items():
        ticket, entry = M.num(p.get("ticket")) or M.TICKET, M.num(p.get("px"))
        exits = [e for e in p["_exits"] if isinstance(e, dict)]
        back = sum(M.num(e.get("eur")) or 0 for e in exits)
        last = M.num(px.get(pid))
        if last is None and p["_left"] <= 1e-9 and exits:
            last = M.num(exits[-1].get("px"))
        value = M.pos_value(p, p["_left"], last / entry) if p["_left"] > 1e-9 and last and entry else None
        closed = p["_left"] <= 1e-9
        pnl = back - ticket if closed else (back + (value or 0) - ticket if value is not None else None)
        whys = [str(e.get("why") or "?") for e in exits]
        half = any(w == "target" for w in whys)
        if closed:
            status, kind = ", ".join(exit_label(e, p) for e in exits), ("good" if pnl > 0 else "bad")
        elif half:
            status, kind = "half sold at 2x", "good"
        else:
            status, kind = "open", "neutral"
        sold_at = [(M.num(e.get("px")) / entry if M.num(e.get("px")) and entry else None, (M.num(e.get("frac")) or 1) < 0.999) for e in exits]
        cands = []
        if p.get("grp") in M.PAPER_GROUPS and not closed and p.get("pair"):     # the held coin's minute candles since the entry (the run that renders the page has them)
            t_in = M.num(p.get("entryAt")) or M.num(p.get("t")) or 0
            cands = [c for c in M.hold_candles(d, p) if c[0] >= t_in - 60_000 and c[4] > 0]     # none of the pool's other coin (UNIT_X)
        c_px = M.num(cpx.get(pid)) if not M.unit_off(cpx.get(pid), entry) else None
        rows.append({"id": pid, "p": p, "ticket": ticket, "entry": entry, "back": back, "last": last, "value": value, "closed": closed, "half": half,
                     "pnl": pnl, "status": status, "kind": kind, "mult": (last / entry) if last and entry else None, "sold_at": sold_at,
                     "liq_now": M.num(liq_now.get(pid)), "exit_t": M.num(exits[-1].get("t")) if closed and exits else None, "bot": p.get("grp") in M.BOT_GROUPS,
                     "candles": cands, "cpx": c_px or (cands[0][4] if cands else None)})
    rows.sort(key=lambda r: -(M.num(r["p"].get("t")) or 0))
    open_rows = [r for r in rows if not r["closed"]]
    closed_rows = [r for r in rows if r["closed"]]
    open_bot = [r for r in open_rows if r["bot"]]
    open_bank = [r for r in open_rows if r["p"].get("grp") in M.BANK_GROUPS]
    unpriced = [r for r in open_bank if r["value"] is None]
    equity = cash["free"] + sum(r["value"] or 0 for r in open_bank)      # pick mode's bankroll: the paper account has no budget
    bot_closed = [r for r in closed_rows if r["bot"]]
    wins = sum(1 for r in bot_closed if r["pnl"] > 0)
    paper = {"since": since, "acct": M.paper_account(pos, since, px),
             "noPx": sum(1 for r in open_rows if M.in_account(r["p"], since) and r["value"] is None),
             "closed": [r for r in closed_rows if since is not None and (M.num(r["p"].get("t")) or 0) >= since],
             "old": [r for r in closed_rows if since is None or (M.num(r["p"].get("t")) or 0) < since]}
    try:                             # the paper account's hindsight categories, activity feed and trade rows (page_account.py; reads only)
        import page_account as PA
        paper["acct2"] = PA.load(d, now, pos=pos, px=px, since=since)
    except Exception:                # a missing or broken page_account.py costs only the account block: render falls back to the plain strip
        paper["acct2"] = None
    try:                             # the three paper traders (traders.py; reads only, never raises): the Traders tab and the radar's paper positions
        import traders as TR
        traders = TR.load(d, now)
    except Exception as e:           # a missing or broken traders.py costs only those blocks: they say so, the rest of the page is unaffected
        traders = {"err": "%s: %s" % (type(e).__name__, str(e)[:120])}

    # big test: chunks of the same snapshot run -> one group. The result docs are read one at a time and dropped (iter_docs): all of
    # them at once took about 9 GB on 16 Oct and the scan's runner was shut down while the page was built
    groups, seen_coins = {}, set()
    team = FT.Team(M.RULE, M.train_since(now)) if FT else None     # the filter team's report cards (filter_team.py) from the same one pass
    for sid, r in iter_docs(d, "memesnapres"):
        if team is not None:
            team.feed(r)
        key = str(sid).rsplit("-", 1)[0]
        g = groups.setdefault(key, {"t0": M.num(r.get("t0")), "t": M.num(r.get("t")), "n": 0, "pass": [], "top": [], "fail": [], "up": 0, "gone": 0})
        for c in r.get("coins") or []:
            eur = M.num(c.get("eur")) if isinstance(c, dict) else None
            if eur is None:
                continue
            eur = M.clamp(eur, M.EUR_CLIP[0], M.EUR_CLIP[1])      # averages are shown clipped, like the learning sees them
            g["n"] += 1
            (g["pass"] if c.get("pass") else g["fail"]).append(eur)
            rank = M.num(c.get("rank"))
            if rank and rank <= 10:
                g["top"].append(eur)
            g["up"] += 1 if eur > 0 else 0
            g["gone"] += 1 if c.get("gone") else 0
        seen_coins.update(str(c.get("a")) for c in r.get("coins") or [] if isinstance(c, dict))
    avg = lambda xs: (sum(xs) / len(xs)) if xs else None
    big = []
    for key, g in sorted(groups.items(), key=lambda kv: kv[1]["t0"] or 0):
        big.append({"key": key, "t0": g["t0"], "t": g["t"], "n": g["n"], "passN": len(g["pass"]), "passAvg": avg(g["pass"]), "topN": len(g["top"]),
                    "topAvg": avg(g["top"]), "failN": len(g["fail"]), "failAvg": avg(g["fail"]), "up": g["up"], "gone": g["gone"]})

    # the last full scan: its top candidates and the run that made it (the raw snapshots one at a time, the newest scan's kept)
    last_t, cands, scan_n = 0, [], 0
    for _, s in iter_docs(d, "memesnap"):
        t = M.num(s.get("t")) or 0
        if t > last_t:
            last_t, cands, scan_n = t, [], 0
        if t and t == last_t:
            cands += [c for c in (s.get("coins") or []) if isinstance(c, dict) and M.num(c.get("rank"))]
            scan_n += M.num(s.get("n")) or 0
    cands.sort(key=lambda c: M.num(c["rank"]))
    scan_run = next((r for r in runs if isinstance(r, dict) and M.num(r.get("t")) == last_t), None) if last_t else None
    held_addrs = {r["p"].get("addr") for r in open_rows}
    ever_addrs = {r["p"].get("addr") for r in rows}
    w, winfo = blended_weights_lean(d, M.train_since(M.num(state.get("lastRun")) or now))     # the run's weights: its clock's window
    weights = sorted(w.items(), key=lambda kv: (-abs(kv[1]), kv[0]))[:16]
    rec = M.load_json(os.path.join(d, "db", "memebot", "recommend.json"), None)
    track = sorted([r for r in M.load_docs(d, "memerec").values() if isinstance(r, dict)], key=lambda r: -(M.num(r.get("t")) or 0))
    young_hist = sorted([r for r in M.load_docs(d, "memeyoung").values() if isinstance(r, dict)], key=lambda r: -(M.num(r.get("t")) or 0))[:48]
    train = M.load_json(os.path.join(d, "db", "memebot", "train.json"), None)
    office = M.load_json(os.path.join(d, "db", "memebot", "office.json"), None)
    try:
        team_rep = FT.report(team, FT.active_tags()) if team is not None else None
    except Exception:                # a broken report card costs only the filter team's section
        team_rep = None
    return {"team": team_rep, "dir": d, "now": now, "rec": rec if isinstance(rec, dict) else None, "office": office if isinstance(office, dict) else None,"track": track[:80], "track_all": track, "young_hist": young_hist, "train": train if isinstance(train, dict) else None, "pos": rows, "open": open_rows, "open_bot": open_bot, "unpriced": unpriced, "closed": closed_rows, "cash": cash, "equity": equity, "state": state, "paper": paper,
            "curve": curve, "runs": runs, "big": big, "seen_coins": len(seen_coins), "cands": cands[:15], "scan_t": last_t, "scan_run": scan_run,
            "scan_n": scan_n,
            "held": held_addrs, "ever": ever_addrs, "weights": weights, "winfo": winfo, "detail": winfo.get("detail") or {}, "wins": wins, "bot_closed": bot_closed,
            "traders": traders}




# ---------------------------------------------------------------- charts (inline SVG in CSS pixels; a wide and a narrow variant per chart)
def line_chart(series, budget, width, height=240, ref_label="start", aria_label="Equity per run", fmt_v=None, fmt_tick=None, fmt_t=None, fmt_tip=None):
    """series: [(name, css class, [(t, v)])], drawn in list order (the last on top). Hover: crosshair + tooltip via the page script (data-pts
    on the overlay). fmt_v formats the end labels, fmt_tip the tooltip's values (fmt_v without one), fmt_tick the y ticks, fmt_t the tooltip's
    time (each a function of one number giving a string; None keeps the plain 1234.56 and the ISO time). ref_label None leaves the reference line unlabelled. The right
    margin grows to the widest end label, so no label is cut at the chart's edge; end labels with the same text are drawn once."""
    pts_all = [(t, v) for _, _, pts in series for t, v in pts]
    if len(pts_all) < 2:
        return ""
    narrow = width < 400
    lab = fmt_v or fmt_amt
    ends_v = [pts[-1][1] for _, _, pts in series if len(pts) >= 2]
    ml, mr, mt, mb = (46, 52, 14, 28) if narrow else (44, 72, 14, 28)
    mr = max([mr] + [10 + int(7.4 * len(lab(v))) for v in ends_v])     # 7.4 px a character covers the widest webfont's digits at 12 px, plus the 8 px offset
    pw, ph = width - ml - mr, height - mt - mb
    t0, t1 = min(t for t, _ in pts_all), max(t for t, _ in pts_all)
    if t1 == t0:
        t1 = t0 + 1
    lo, hi, ticks = domain([v for _, v in pts_all] + [budget])
    step = (ticks[1] - ticks[0]) if len(ticks) > 1 else 1
    tick_fmt = fmt_tick or (fmt_amt if step < 1 else (lambda v: sgn("%g" % v)))
    X = lambda t: ml + (t - t0) / (t1 - t0) * pw
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, width, height, E(aria_label))]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml, y, ml + pw, y, ml - 6, y + 4, E(tick_fmt(tk))))
    yb = Y(budget)
    out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (ml, yb, ml + pw, yb))
    if ref_label is not None:
        out.append('<text class="tick over" x="%d" y="%.1f" text-anchor="start">%s %s</text>' % (ml + 4, yb - 5, E(ref_label), fmt_amt(budget)))   # left end, above the line: never meets the end labels
    n_lab = min(2 if narrow else 5, len({t for t, _ in pts_all}))
    for i in range(n_lab):
        t = t0 + (t1 - t0) * i / max(n_lab - 1, 1)
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="%s">%s</text>' % (X(t), height - 8, "start" if i == 0 else ("end" if i == n_lab - 1 else "middle"), fmt_dt(t, True)))
    ends = []
    for name, cls, pts in series:
        if len(pts) < 2:
            continue
        path = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", X(t), Y(v)) for i, (t, v) in enumerate(pts))
        if cls == "s1":
            out.append('<path class="area %s" d="%s L%.1f %.1f L%.1f %.1f Z"/>' % (cls, path, X(pts[-1][0]), mt + ph, X(pts[0][0]), mt + ph))
        out.append('<path class="line %s" d="%s"/>' % (cls, path))
        tl, vl = pts[-1]
        out.append('<circle class="dot %s" cx="%.1f" cy="%.1f" r="4"/>' % (cls, X(tl), Y(vl)))
        if not any(e[3] == lab(vl) and abs(e[0] - X(tl) - 8) < 1 for e in ends):     # two lines that end together: one label
            ends.append([X(tl) + 8, Y(vl) + 4, vl, lab(vl)])
    ends.sort(key=lambda e: e[1])
    for i in range(1, len(ends)):          # end labels that would collide are pushed apart (the legend names the series)
        if ends[i][1] - ends[i - 1][1] < 13:
            ends[i][1] = ends[i - 1][1] + 13
    for x, y, v, txt in ends:
        out.append('<text class="label" x="%.1f" y="%.1f">%s</text>' % (x, y, E(txt)))
    tip = fmt_tip or fmt_v
    tv = (lambda v: tip(v)) if tip else (lambda v: round(v, 2))     # the script prints a number with two decimals, a string as it is
    data = [{"x": round(X(t), 1), "t": fmt_t(t) if fmt_t else fmt_dt(t), "v": [(name, tv(v)) for name, _, pts in series for tt, v in pts if tt == t]} for t in sorted({t for t, _ in pts_all})]
    out.append('<line class="cross" x1="0" y1="%d" x2="0" y2="%d" style="opacity:0"/>' % (mt, mt + ph))
    out.append('<rect class="overlay" x="%d" y="%d" width="%d" height="%d" fill="transparent" data-pts="%s"/>' % (ml, mt, pw, ph, E(json.dumps(data, separators=(",", ":")))))
    out.append("</svg>")
    return "".join(out)


def bar_path(x, y0, y1, w, r=4):
    """A column from the baseline y0 to the data end y1, rounded only at the data end."""
    if abs(y1 - y0) < 0.5:
        return '<rect x="%.1f" y="%.1f" width="%.1f" height="1"/>' % (x, min(y0, y1) - 0.5, w)
    r = min(r, w / 2, abs(y1 - y0))
    if y1 < y0:   # grows up
        return '<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z"/>' % (x, y0, y1 + r, x, y1, x + r, y1, x + w - r, x + w, y1, x + w, y1 + r, y0)
    return '<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z"/>' % (x, y0, y1 - r, x, y1, x + r, y1, x + w - r, x + w, y1, x + w, y1 - r, y0)


def hbar_path(x0, x1, y, h, r=3):
    """A horizontal bar from the axis x0 to the data end x1, rounded only at the data end."""
    if abs(x1 - x0) < 0.5:
        return '<rect x="%.1f" y="%.1f" width="1" height="%.1f"/>' % (min(x0, x1) - 0.5, y, h)
    r = min(r, h / 2, abs(x1 - x0))
    if x1 > x0:
        return '<path d="M%.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Z"/>' % (x0, y, x1 - r, x1, y, x1, y + r, y + h - r, x1, y + h, x1 - r, y + h, x0)
    return '<path d="M%.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Z"/>' % (x0, y, x1 + r, x1, y, x1, y + r, y + h - r, x1, y + h, x1 + r, y + h, x0)


def grouped_bars(groups, series, width, baseline=None, height=220):
    """groups: [(label, short label, {series key: value|None})]; series: [(key, name, css class)]. Negative values hang below the zero line."""
    vals = [v for _, _, g in groups for v in g.values() if v is not None]
    if not vals:
        return ""
    ml, mr, mt, mb = 44, 12, 14, 28
    pw, ph = width - ml - mr, height - mt - mb
    lo, hi, ticks = domain(vals + [0.0] + ([baseline] if baseline is not None else []))
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Big test results per scan">' % (width, height, width, height)]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="%s" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>' % ("axis" if tk == 0 else "grid", ml, y, ml + pw, y, ml - 6, y + 4, sgn("%g" % tk)))
    if baseline is not None:
        yb = Y(baseline)
        out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (ml, yb, ml + pw, yb))
        if width > 400:    # the phone variant names the dashed line in the legend instead: there is no free spot between the bars
            out.append('<text class="tick over" x="%d" y="%.1f" text-anchor="end">price unchanged %s</text>' % (ml + pw - 4, yb - 4, fmt_amt(baseline, True)))
    band = pw / len(groups)
    bw = min(24, max(4, (band - 10) / len(series) - 2))
    every = max(1, int(math.ceil(72.0 / band)))     # label every k-th group so labels never collide
    for gi, (label, short, g) in enumerate(groups):
        gx = ml + band * gi + (band - (bw + 2) * len(series)) / 2
        if gi % every == 0 or gi == len(groups) - 1:
            out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (ml + band * gi + band / 2, height - 8, E(short if band < 90 else label)))
        for si, (key, name, cls) in enumerate(series):
            v = g.get(key)
            if v is None:
                continue
            x = gx + si * (bw + 2)
            out.append('<g class="bar %s" data-tip="%s · %s: %s">%s</g>' % (cls, E(label), E(name), fmt_amt(v, True), bar_path(x, Y(0), Y(v), bw)))
    out.append("</svg>")
    return "".join(out)


def weight_bars(weights, detail, width):
    """Factor weights as horizontal bars. Wide: diverging around 0 (positive to the right in blue, negative to the left in orange).
    Narrow (phone): one row per factor with the name above a single-sided bar, coloured by sign, so nothing is ever off-screen."""
    if not weights:
        return ""
    mx = max(abs(v) for _, v in weights) or 1
    tip = lambda k, v, lab: 'data-tip="%s (%s): %s%s"' % (E(lab), E(k), sgn("%+.2f" % v), (" · from %d coin results" % (detail.get(k) or {}).get("n")) if (detail.get(k) or {}).get("n") else " · prior")
    if width <= 400:
        rowh, ml, mr, top = 34, 8, 50, 6
        height = top + rowh * len(weights) + 4
        bw = width - ml - mr
        out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Factor weights in use">' % (width, height, width, height)]
        for i, (k, v) in enumerate(weights):
            y, lab = top + i * rowh, factor_label(k)
            x1 = ml + abs(v) / mx * bw
            out.append('<text class="label" x="%d" y="%.1f">%s</text>' % (ml, y + 11, E(lab)))
            out.append('<g class="bar %s" %s>%s</g>' % ("pos" if v >= 0 else "neg", tip(k, v, lab), hbar_path(ml, x1, y + 16, 10)))
            out.append('<text class="tick" x="%.1f" y="%.1f">%s</text>' % (x1 + 6, y + 25, sgn("%+.2f" % v)))
        out.append("</svg>")
        return "".join(out)
    rowh, ml, mr = 22, 230, 54
    height = rowh * len(weights) + 22
    pw = width - ml - mr
    cx = ml + pw / 2
    half = pw / 2 - 46                         # room for the value label on either side
    S = lambda v: v / mx * half
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Factor weights in use">' % (width, height, width, height)]
    ticks, step = clean_ticks(-mx, mx, 4)
    for tk in ticks:
        if abs(tk) > mx * 1.001 or tk == 0:
            continue
        x = cx + S(tk)
        out.append('<line class="grid" x1="%.1f" y1="4" x2="%.1f" y2="%d"/><text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x, x, height - 16, x, height - 4, sgn("%+.2f" % tk)))
    out.append('<line class="axis" x1="%.1f" y1="4" x2="%.1f" y2="%d"/>' % (cx, cx, height - 16))
    for i, (k, v) in enumerate(weights):
        y, lab = 6 + i * rowh, factor_label(k)
        out.append('<text class="label" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml - 8, y + 12, E(lab)))
        x1 = cx + S(v)
        out.append('<g class="bar %s" %s>%s</g>' % ("pos" if v >= 0 else "neg", tip(k, v, lab), hbar_path(cx, x1, y + 2, 12)))
        out.append('<text class="tick" x="%.1f" y="%.1f" text-anchor="%s">%s</text>' % ((x1 + 6) if v >= 0 else (x1 - 6), y + 12, "start" if v >= 0 else "end", sgn("%+.2f" % v)))
    out.append("</svg>")
    return "".join(out)


def chart_box(wide, narrow, legend=""):
    """One card holding the desktop and the phone variant of a chart (CSS shows one of them; both fit their card)."""
    return '<div class="chart"><div class="wide">%s</div><div class="narrow">%s</div>%s</div>' % (wide, narrow, legend)


# ---------------------------------------------------------------- the agent office: the worker steps of one hourly scan, drawn as a team
OFFICE_DEPTS = (   # key, name, colour (page tokens only, so dark and light both work; neighbours on both floor plans stay apart), agent ids; ring order, clockwise from the top left
    ("ops", "Operations", "color-mix(in oklch,var(--s1) 30%,var(--bad-mark))", ("dispatch",)),
    ("scouts", "Scouts", "color-mix(in oklch,var(--s1) 50%,var(--s3))", ("scouts", "deep", "spotter")),
    ("chart", "Chart desk", "var(--warn-mark)", ("candles",)),
    ("market", "Market data", "color-mix(in oklch,var(--s1) 65%,var(--bad-mark))", ("market", "refresh")),
    ("analysts", "Analysts", "var(--s3)", ("analyst",)),
    ("safety", "Safety desk", "var(--s2)", ("safety",)),
    ("trading", "Trading desk", "var(--s1)", ("trader",)),
    ("report", "Reporting", "color-mix(in oklch,var(--warn-mark) 50%,var(--s3))", ("reporter",)))
OFFICE_BRAIN = ("brain", "The Brain", "var(--accent)", ("trainer",))
OFFICE_AGENTS = {   # id: (name on the page, what it does, the outside services it calls); the trader's job is read from the hold rule in use
    "dispatch": ("Dispatcher", "decides what this run needs: the kind of scan, the open positions to watch, the checks that are due", ()),
    "trainer": ("Research lab", "fits the model again on the scored coins of its window (the last 14 days in the hourly profile): the walk-forward test, the zero model and the tuned limits", ()),
    "scouts": ("Source scouts", "collects coin addresses from DEX lists, launchpads, RugCheck lists, CoinGecko, CoinMarketCap, social posts and news",
               ("DexScreener", "GeckoTerminal", "Jupiter", "pump.fun", "Raydium", "Orca", "LaunchLab", "RugCheck", "CoinGecko", "CoinMarketCap", "Reddit", "Farcaster",
                "Mastodon", "4chan", "news feeds", "fear & greed index", "GMGN")),
    "candles": ("Candle keeper", "fetches minute candles for the held coins and the tips that are due for a check", ("GeckoTerminal",)),
    "market": ("Price desk", "prices every coin found: DexScreener pairs first, Jupiter prices for the rest", ("DexScreener", "Jupiter")),
    "analyst": ("Gatekeeper", "runs the gates, scores the coins and shortlists the best for the safety checks", ()),
    "deep": ("Deep searcher", "searches DexScreener with more keywords when only a few coins passed the gates", ("DexScreener",)),
    "spotter": ("Launch spotter", "lists the coins under an hour old about five minutes into the scan, for the New launches tab, before they are scored",
                ("DexScreener", "RugCheck")),
    "safety": ("Safety officers", "checks each shortlisted coin: RugCheck, GoPlus, the creator's wallet, on-chain trades, the community and the first buyers",
               ("RugCheck", "GoPlus", "GeckoTerminal", "Jupiter", "Solana RPC", "CoinGecko", "StockTwits", "X", "Telegram", "DexScreener", "GMGN")),
    "refresh": ("Price refresher", "fetches fresh prices for the candidates right before the pick", ("DexScreener",)),
    "trader": ("Paper trader", "", ()),
    "reporter": ("Reporter", "writes this page", ())}
OFFICE_AGENTS["radar"] = ("Launch radar", "rates every coin whose pool is under 10 minutes old in one quick round after each scan, in its own job; only coins without traps are shown and pushed",
                          ("DexScreener", "pump.fun", "GeckoTerminal", "Jupiter", "RugCheck", "Solana RPC", "LaunchLab"))
try:
    import forecast as FC     # the look-alike forecast for the pick (display only): Pick tab, Details
except ImportError:
    FC = None
try:
    import filter_team as FT  # the gates as a team of single bots with report cards: the Pick tab's Details, in place of the old coin test
except ImportError:           # a copy of the code without filter_team.py: the coin test as before it
    FT = None
try:
    import page_office as PO  # the agent cards, the Launch radar's desk (its own job: page_office.EXT_HOME), the daily overview, the scan strip (WP5c)
except ImportError:           # a copy of the code without page_office.py (the selftest's stand-in folder): the office and the Pick tab as before it
    class PO:
        EXT_HOME, CSS = {"radar": "analysts"}, ""
        scan_minute = staticmethod(lambda runs, default: int(default) % 60)
        ext_agents = staticmethod(lambda *a: [])
        cards = daily = scan_strip = balance = desk = staticmethod(lambda *a: "")
try:
    import page_home as PH    # the Start tab: both paper accounts side by side, the pick and the rocket candidates
except ImportError:
    PH = None
try:
    import page_brain as PB   # the brain at the top of the Brain tab (tab id office)
except ImportError:
    PB = None
OFFICE_HOSTS = (("launch-mint", "LaunchLab"), ("dexscreener", "DexScreener"), ("geckoterminal", "GeckoTerminal"), ("jup.ag", "Jupiter"), ("pump.fun", "pump.fun"),
                ("raydium", "Raydium"), ("orca.so", "Orca"), ("rugcheck", "RugCheck"), ("coingecko", "CoinGecko"), ("coinmarketcap", "CoinMarketCap"), ("reddit", "Reddit"),
                ("warpcast", "Farcaster"), ("mastodon", "Mastodon"), ("4cdn", "4chan"), ("gmgn", "GMGN"), ("gopluslabs", "GoPlus"), ("solana.com", "Solana RPC"),
                ("stocktwits", "StockTwits"), ("twitter", "X"), ("twimg", "X"), ("alternative.me", "fear & greed index"), ("t.me", "Telegram"), ("bitquery", "Bitquery"),
                ("lunarcrush", "LunarCrush"), ("news.google", "news feeds"), ("coindesk", "news feeds"), ("cointelegraph", "news feeds"), ("decrypt.co", "news feeds"),
                ("theblock", "news feeds"), ("cryptoslate", "news feeds"))
OFFICE_W = 660     # the floor plan's desktop width in CSS px: the map column beside the 360px panel
# the department picked on the floor plan: one radio per department, so it works without scripts (like the tabs)
OFFICE_CSS = "\n".join(
    '#od-{0}:checked ~ .ogrid .k-{0} .halo {{ opacity:1 }} #od-{0}:checked ~ .ogrid .k-{0} .top, #od-{0}:checked ~ .ogrid .k-{0} .core {{ stroke-width:3 }} '
    '#od-{0}:checked ~ .ogrid .wire.k-{0} {{ opacity:1; stroke-width:2.5 }} #od-{0}:checked ~ .ogrid .opanel.k-{0} {{ display:grid }} '
    '#od-{0}:checked ~ .ogrid label[for="od-{0}"] {{ background:color-mix(in srgb,var(--accent) 7%,transparent) }} '
    '#od-{0}:focus-visible ~ .ogrid label[for="od-{0}"] {{ outline:2px solid var(--accent); outline-offset:-2px }}'.format(k) for k, _, _, _ in OFFICE_DEPTS + (OFFICE_BRAIN,))


# ---------------------------------------------------------------- page
CSS = r"""
/* Layout: one 1100px column read top to bottom. Phone first: at 390px everything fits in a 16px gutter, charts are drawn at the
   card's inner width (no scrolling inside cards) and the reference sections fold behind a tap. Colours are tokens on :root. */
:root { --bg:#f5f6f8; --surface:#ffffff; --fg:#14171c; --fg2:#4b535e; --muted:#5b6470; --line:#e2e5ea; --line2:#eef0f3;
  --accent:#1f66c4; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#006300; --good-mark:#0ca30c; --bad:#c7342f; --bad-mark:#d03b3b; --warn:#8a5200; --warn-mark:#d98a1a;
  --chip:#eef2f7; --fs-xs:12px; --fs-s:13px; --fs-m:14px; --t1:var(--s1); --t2:var(--warn-mark); --t3:#7b5bd6;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#98a0ab; --line:#2a2f37; --line2:#262b33;
  --accent:#4d95ec; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --warn-mark:#e0a24a; --chip:#232830; --t3:#a08bf0; color-scheme:dark } }
:root[data-theme="dark"] { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#98a0ab; --line:#2a2f37; --line2:#262b33;
  --accent:#4d95ec; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --warn-mark:#e0a24a; --chip:#232830; --t3:#a08bf0; color-scheme:dark }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg); font:var(--fs-m)/1.5 var(--sans); -webkit-text-size-adjust:100% }
.wrap { max-width:1100px; margin:0 auto; padding-inline:16px; padding-block:20px 48px; display:grid; gap:24px }
.wrap > *, section > *, details > * { min-width:0 }
h1,h2,h3 { margin:0; text-wrap:balance; line-height:1.2 }
h1 { font-size:22px; font-weight:600 }
h2 { font-size:17px; font-weight:600 }
.eyebrow { font-size:var(--fs-xs); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500 }
header { order:-1; display:flex; flex-wrap:wrap; gap:6px 24px; align-items:baseline; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:12px }
header .meta { color:var(--muted); font-size:var(--fs-s) }
.live { display:flex; flex-wrap:wrap; align-items:center; gap:4px 12px; padding:8px 10px 8px 14px; border-radius:8px; font-size:var(--fs-s); color:var(--fg2);
  background:color-mix(in srgb,var(--accent) 8%,var(--surface)); border:1px solid color-mix(in srgb,var(--accent) 30%,var(--line)) }
.live .btn { margin-left:auto; display:inline-flex; align-items:center; min-height:44px; padding:0 16px; border-radius:999px; background:var(--accent); color:#fff; font-weight:500 }
.live .btn:hover, .live .btn:focus-visible { text-decoration:none; filter:brightness(1.1) }
.live small { flex-basis:100%; font-size:var(--fs-xs); color:var(--muted) }
section { display:grid; gap:12px }
.sec-head { display:flex; flex-wrap:wrap; gap:2px 16px; align-items:baseline; justify-content:space-between }
.sec-head p { margin:0; color:var(--fg2); font-size:var(--fs-s); text-wrap:pretty }
/* an ⓘ (info_i): a 44 px tap target that opens the explanation; beside a heading it sits at the heading's right end and keeps its place */
details.hi > summary { list-style:none; cursor:pointer; color:var(--muted); width:44px; height:44px; display:flex; align-items:center; justify-content:center; font-size:17px; line-height:1 }
details.hi > summary::-webkit-details-marker { display:none } details.hi > summary:hover, details.hi[open] > summary { color:var(--accent) }
.hi-b { display:grid; gap:6px; font-size:var(--fs-s); color:var(--fg2) } .hi-b p { margin:0 } .hi-b .note { max-width:none }
.sec-head.hasi { position:relative; padding-right:40px; row-gap:0 } .sec-head > details.hi { flex-basis:100% }
.sec-head > details.hi > summary { position:absolute; top:-11px; right:-10px } .sec-head > details.hi[open] { margin-right:-40px } .sec-head > details.hi[open] > .hi-b { margin-top:6px }
.paper details.hi, .ift details.hi { display:inline } .paper details.hi > summary, .ift details.hi > summary { display:inline-flex; vertical-align:middle; margin:-14px -6px -14px 0 }
.paper details.hi[open] > .hi-b, .ift details.hi[open] > .hi-b { margin-top:4px }

details.fold > summary { list-style:none; display:grid; grid-template-columns:1fr auto; column-gap:12px; align-items:center; padding:12px 14px; background:var(--surface); border:1px solid var(--line); border-radius:8px; cursor:pointer; color:var(--fg) }
details.fold > summary::-webkit-details-marker { display:none }
details.fold > summary .t { font-weight:600; font-size:17px; line-height:1.25 } details.fold > summary .sum { font-size:var(--fs-s); color:var(--fg2); grid-column:1 }
details.fold > summary::after { content:"›"; grid-column:2; grid-row:1 / span 2; color:var(--muted); font-size:24px; line-height:1; transform:rotate(90deg); transition:transform .15s }
details.fold[open] > summary { margin-bottom:12px } details.fold[open] > summary::after { transform:rotate(-90deg) }
details.fold > summary:hover { border-color:var(--accent) }
.rest { display:grid; gap:24px }
.hero { display:grid; grid-template-columns:minmax(280px,1.5fr) repeat(auto-fit,minmax(140px,1fr)); gap:12px }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px 14px; min-width:0; display:grid; gap:4px; align-content:start }
.tile .label { font-size:var(--fs-xs); color:var(--muted) }
.tile .value { font-size:20px; font-weight:600; letter-spacing:-.01em; font-variant-numeric:tabular-nums }
.tile.lead .value { font-size:40px; line-height:1.05 }
.tile .sub { font-size:var(--fs-s); color:var(--fg2) }
.delta { font-weight:500; font-size:15px; color:var(--fg2); font-variant-numeric:tabular-nums } .tile.lead .delta { font-size:16px; margin-left:8px; letter-spacing:0; white-space:nowrap }
.delta.good { color:var(--good) } .delta.bad { color:var(--bad) }
.verdict { font-size:17px; margin:0 0 12px } .verdict.good strong { color:var(--good) } .verdict.bad strong { color:var(--bad) }
.chart { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; display:grid; gap:8px }
.chart .narrow { display:none } .chart-svg { display:block; width:100%; max-width:100%; height:auto; font-family:var(--sans) }
.chart .narrow .chart-svg { max-width:480px; margin-inline:auto }
.chart-svg .grid { stroke:var(--line2); stroke-width:1 } .chart-svg .axis { stroke:var(--line); stroke-width:1 } .chart-svg .ref { stroke:var(--muted); stroke-width:1; stroke-dasharray:3 3 }
.chart-svg .tick { fill:var(--muted); font-size:var(--fs-xs); font-variant-numeric:tabular-nums } .chart-svg .label { fill:var(--fg2); font-size:var(--fs-xs) }
.chart-svg .over, .chart-svg .label { paint-order:stroke; stroke:var(--surface); stroke-width:3px; stroke-linejoin:round }
.chart-svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round } .chart-svg .line.s1 { stroke:var(--s1) } .chart-svg .line.s2 { stroke:var(--s2) }
.chart-svg .area.s1 { fill:var(--s1); opacity:.1 } .chart-svg .dot { stroke:var(--surface); stroke-width:2 } .chart-svg .dot.s1 { fill:var(--s1) } .chart-svg .dot.s2 { fill:var(--s2) }
.chart-svg .bar.s1 { fill:var(--s1) } .chart-svg .bar.s2 { fill:var(--s2) } .chart-svg .bar.s3 { fill:var(--s3) } .chart-svg .bar.pos { fill:var(--s1) } .chart-svg .bar.neg { fill:var(--s2) }
.chart-svg .bar:hover { opacity:.8 } .chart-svg .cross { stroke:var(--muted); stroke-width:1 }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; font-size:var(--fs-s); color:var(--fg2) }
.legend span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; background:var(--c) }
.legend .ref-leg::before { width:14px; height:0; border-top:2px dashed var(--muted); background:none; border-radius:0; vertical-align:3px }
.tip { position:fixed; pointer-events:none; background:var(--fg); color:var(--bg); font-size:var(--fs-xs); padding:6px 8px; border-radius:6px; max-width:280px; opacity:0; transition:opacity .08s; z-index:10; white-space:pre-line }
.tip.on { opacity:1 }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px }
.cards:has(.rec), .cards:has(.pos) { grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr)) }
.card.rec, .card.pos { container-type:inline-size }
.card { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; display:grid; gap:12px }
.card .top { display:flex; justify-content:space-between; gap:8px 12px; align-items:center; flex-wrap:wrap }
.card .sym { font-size:20px; font-weight:600 } .name { color:var(--fg2); font-size:var(--fs-s); margin-left:6px }
.tabs { display:grid; gap:20px } .tabs > input { position:absolute; opacity:0; pointer-events:none }
.tabbar { display:flex; gap:6px; border-bottom:1px solid var(--line); padding-bottom:0; min-width:0; overflow-x:auto; scrollbar-width:none }
@media (max-width:420px) { .tabbar .tl-long { display:none } .tabbar label { padding-inline:10px } }
.tabbar label { cursor:pointer; padding:10px 14px; border-radius:8px 8px 0 0; font-weight:500; color:var(--fg2); border:1px solid transparent; border-bottom:none; margin-bottom:-1px; display:inline-flex; gap:8px; align-items:center; min-height:44px }
.tabbar label:hover { color:var(--fg) } .tabbar .cnt { font-size:var(--fs-xs); background:var(--chip); color:var(--fg2); border-radius:999px; padding:1px 8px }
#tab-home:checked ~ .tabbar label[for="tab-home"], #tab-pick:checked ~ .tabbar label[for="tab-pick"], #tab-young:checked ~ .tabbar label[for="tab-young"], #tab-account:checked ~ .tabbar label[for="tab-account"],
#tab-office:checked ~ .tabbar label[for="tab-office"] { color:var(--accent); background:var(--surface); border-color:var(--line) }
.tabbar label:focus-visible, .tabs > input:focus-visible ~ .tabbar label[for] { outline:2px solid var(--accent); outline-offset:2px }
.pane { display:none; gap:24px } #tab-home:checked ~ #pane-home, #tab-pick:checked ~ #pane-pick, #tab-young:checked ~ #pane-young, #tab-account:checked ~ #pane-account, #tab-office:checked ~ #pane-office { display:grid }
.chips { display:flex; flex-wrap:wrap; gap:6px }
.chip { display:inline-block; font-size:var(--fs-xs); font-weight:500; padding:3px 9px; border-radius:999px; background:var(--chip); color:var(--fg2); white-space:nowrap; line-height:1.4 }
.chip.good { background:color-mix(in srgb,var(--good-mark) 16%,var(--surface)); color:var(--good) } .chip.bad { background:color-mix(in srgb,var(--bad-mark) 16%,var(--surface)); color:var(--bad) }
.chip.warn { background:color-mix(in srgb,var(--warn-mark) 18%,var(--surface)); color:var(--warn) }
.chip.neutral { background:color-mix(in srgb,var(--accent) 14%,var(--surface)); color:var(--accent) }
.odds { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px } .odds .tile { padding:10px 12px } .odds .tile .value { font-size:22px }
.kv { display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:8px 12px; font-size:var(--fs-m) }
.kv div { min-width:0 } .kv .k { color:var(--muted); font-size:var(--fs-xs) } .kv .v { font-variant-numeric:tabular-nums; white-space:nowrap; font-weight:500 }
.kv .v.multi { white-space:normal } .kv .span { grid-column:1 / -1 }
.row { display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:var(--fs-s) } .row .k { color:var(--muted); font-size:var(--fs-xs); margin-right:2px }
.safety { font-size:var(--fs-m); line-height:1.45; margin:0; padding:10px 12px; border-radius:6px; background:var(--chip); border-left:3px solid var(--accent) }
.safety::before { content:"Safety check · " attr(data-src); display:block; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); margin-bottom:2px }
.safety.flag { border-left-color:var(--warn-mark) }
.why { font-size:var(--fs-m); color:var(--fg2); margin:6px 0 0 } .why + .why { margin-top:4px }
details.more > summary { color:var(--accent); font-weight:500 } .tipf-b { display:grid; gap:12px } .tipf-b > .verdict { margin:0 } details.chartf[open] > .embed { margin-top:8px }
.embed { width:100%; height:360px; border:0; border-radius:6px; background:var(--chip) }
a { color:var(--accent); text-decoration:none } a:hover, a:focus-visible { text-decoration:underline }
.links { display:flex; flex-wrap:wrap; gap:8px }
.links a { display:inline-flex; align-items:center; min-height:44px; padding:0 14px; border:1px solid var(--line); border-radius:999px; background:var(--chip); color:var(--accent); font-size:var(--fs-s); font-weight:500 }
.links a:hover, .links a:focus-visible { text-decoration:none; border-color:var(--accent) } .links a:active { background:var(--line) }
.addr { font-family:var(--mono); font-size:var(--fs-xs); color:var(--muted); overflow-wrap:anywhere }
.tbl { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px } .tbl td .chip { white-space:normal }
.muted, td.muted { color:var(--muted) }
.sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap }
/* the paper account (recommend mode with paper positions): one strip, then one row per held coin that opens on tap */
.acct { display:grid; grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(0,1fr)); background:var(--surface); border:1px solid var(--line); border-radius:8px }
.acct > div { padding:12px 14px; display:grid; gap:2px; align-content:start; min-width:0 } .acct > div + div { border-left:1px solid var(--line2) }
.acct .k { font-size:var(--fs-xs); color:var(--muted) } .acct .v { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums }
.acct .lead .v { font-size:30px; line-height:1.1 } .acct .s, .acct .delta { font-size:var(--fs-s); color:var(--fg2) } .acct .delta.good { color:var(--good) } .acct .delta.bad { color:var(--bad) }
section h3 { font-size:15px; font-weight:600; margin:4px 0 0 }
.holds { display:grid; gap:8px }
details.hold { padding:0; gap:0; display:block } details.hold > summary { list-style:none; cursor:pointer; padding:12px 16px; display:grid; gap:4px 16px; align-items:center;
  grid-template-columns:minmax(120px,1fr) auto minmax(220px,2fr); grid-template-areas:"who plv track" "meta meta track" }
details.hold > summary::-webkit-details-marker { display:none } details.hold > summary .sym { color:var(--fg) }
details.hold > summary:hover { background:color-mix(in srgb,var(--accent) 5%,var(--surface)) } details.hold[open] > summary { border-bottom:1px solid var(--line2) }
details.hold .who { grid-area:who; min-width:0 } details.hold .plv { grid-area:plv; font-size:22px; font-weight:600; font-variant-numeric:tabular-nums; text-align:right }
details.hold .plv.good { color:var(--good) } details.hold .plv.bad { color:var(--bad) } details.hold .meta { grid-area:meta; font-size:var(--fs-s); color:var(--fg2) }
details.hold .track { grid-area:track } details.hold .meta::after { content:" · details ›"; color:var(--accent) } details.hold[open] .meta::after { content:" · close ‹" }
details.hold .body { padding:12px 16px 14px; display:grid; gap:12px } details.hold .worth { margin:0; font-size:var(--fs-s); color:var(--fg2) }
details.fold-lite > summary { color:var(--accent); font-weight:500; padding:4px 0; min-height:44px; box-sizing:border-box; display:flex; align-items:center }
/* 44 px tap targets: the card's folds (Safety check, Why, All numbers, Live chart) and the folds under a list; the negative margins keep the
   page's spacing (the target reaches into the gap around it) */
details.more > summary, details.safe > summary, details.tap > summary { min-height:44px; box-sizing:border-box; padding-block:11px; margin-block:-6px }
td.act a { display:inline-flex; align-items:center; justify-content:center; min-height:44px; min-width:44px; margin-block:-14px } details.fold-lite[open] > summary { margin-bottom:8px } details.fold-lite > .note { margin-bottom:8px }
.track { position:relative; height:56px; margin:0 4px; container-type:inline-size }
.track .rail, .track .fill { position:absolute; top:26px; height:6px; border-radius:999px } .track .rail { left:0; right:0; background:var(--line2) }
.track .fill.good, .track .dot.good { background:var(--good-mark) } .track .fill.warn, .track .dot.warn { background:var(--warn-mark) } .track .fill.bad, .track .dot.bad { background:var(--bad-mark) }
.track .tk { position:absolute; top:21px; height:16px; width:2px; margin-left:-1px; border-radius:1px; background:var(--fg2) }
.track .tk.be { width:0; margin-left:0; background:none; border-left:2px dotted var(--muted) } .track .tk.tp { width:3px; margin-left:-1.5px; background:var(--accent) }
.track .dot { position:absolute; top:22px; width:14px; height:14px; margin-left:-7px; border-radius:50%; border:3px solid var(--surface); box-shadow:0 0 0 1px var(--line) }
.track .now { position:absolute; top:0; transform:translateX(-50%); font-size:var(--fs-s); font-weight:600; white-space:nowrap; font-variant-numeric:tabular-nums }
.track .now.l { transform:translateX(-7px) } .track .now.r { transform:translateX(calc(-100% + 7px)) }
.track .now.good { color:var(--good) } .track .now.warn { color:var(--warn) } .track .now.bad { color:var(--bad) }
.track .tl { position:absolute; top:40px; transform:translateX(-50%); font-size:var(--fs-xs); color:var(--muted); white-space:nowrap } .track .tl.end { transform:translateX(calc(-100% + 2px)); color:var(--accent) }
.track .tl.start { transform:translateX(-1px); color:var(--bad) } .track .tl.at { transform:translateX(-1px) } .track .tk.st { width:3px; margin-left:-1.5px; background:var(--bad-mark) }
@supports not (container-type:inline-size) { .track .tl.at { display:none } }
.nw { white-space:nowrap }
.tleg { display:flex; flex-wrap:wrap; gap:2px 14px; font-size:var(--fs-xs); color:var(--fg2); font-variant-numeric:tabular-nums }
.clock { display:grid; gap:4px } .clock .bar { height:4px; border-radius:999px; background:var(--line2); overflow:hidden } .clock .bar span { display:block; height:100%; background:var(--muted) }
.clock .cap { display:flex; justify-content:space-between; flex-wrap:wrap; gap:2px 12px; font-size:var(--fs-xs); color:var(--fg2) }
.spark { margin:0; display:grid; gap:4px } .spark-box { position:relative; padding-right:52px } .spark-svg { display:block; width:100%; height:72px; overflow:visible }
.spark .sl { position:absolute; transform:translateY(-50%); font-size:11px; line-height:1; color:var(--muted); background:var(--surface); padding:1px 3px; border-radius:3px; left:2px }
.spark .sl.end { left:auto; right:0; color:var(--s1); font-weight:600; font-variant-numeric:tabular-nums } .spark .sl.tp { left:auto; right:56px; color:var(--accent) }
.spark-svg .line { fill:none; stroke:var(--s1); stroke-width:1.75; vector-effect:non-scaling-stroke; stroke-linejoin:round } .spark-svg .area { fill:var(--s1); opacity:.08 }
.spark-svg .ref { stroke:var(--muted); stroke-width:1; stroke-dasharray:4 3; vector-effect:non-scaling-stroke } .spark-svg .tpl { stroke:var(--accent); stroke-width:1.5; stroke-dasharray:1 3; vector-effect:non-scaling-stroke }
.spark figcaption { font-size:var(--fs-xs); color:var(--muted) }
/* a recommended coin: the market strip, the paper line, the safety checklist, the grouped numbers */
.stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px 12px; padding:10px 12px; background:var(--chip); border-radius:6px }
.stats div { display:grid; min-width:0 } .stats .k { font-size:var(--fs-xs); color:var(--muted) }
.stats .v { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.verdicts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px 12px; padding:10px 12px; border:1px solid var(--line); border-radius:6px }
.verdicts div { display:grid; min-width:0 } .verdicts .k { font-size:var(--fs-xs); color:var(--muted) } .verdicts .v { font-size:22px; font-weight:600; line-height:1.2; font-variant-numeric:tabular-nums }
.verdicts .s { font-size:var(--fs-xs); color:var(--fg2) } .verdicts .low .v { color:var(--warn) }
.odds-note { margin:8px 0 0; font-size:var(--fs-s); color:var(--fg2); text-wrap:pretty } .pick-note { margin:0; font-size:var(--fs-s); font-weight:500; color:var(--warn); text-wrap:pretty }
details.safe > summary { display:flex; gap:8px; align-items:center; color:var(--fg); font-weight:500 } details.safe > summary .ic { width:20px; height:20px; border-radius:50%; display:inline-grid; place-items:center; font-size:11px; font-weight:700; flex:none }
details.safe.ok > summary .ic { background:color-mix(in srgb,var(--good-mark) 18%,var(--surface)); color:var(--good) } details.safe.warn > summary .ic { background:color-mix(in srgb,var(--warn-mark) 24%,var(--surface)); color:var(--warn) }
details.safe.bad > summary .ic { background:color-mix(in srgb,var(--bad-mark) 18%,var(--surface)); color:var(--bad) }
details.safe > summary::after { content:"›"; color:var(--accent); margin-left:2px } details.safe[open] > summary::after { content:"‹" }
.paper { margin:0; padding:8px 12px; border-radius:6px; font-size:var(--fs-s); background:color-mix(in srgb,var(--accent) 9%,var(--surface)); border:1px solid color-mix(in srgb,var(--accent) 28%,var(--line)) }
.paper .k { font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--accent); font-weight:600; margin-right:4px }
.checks { border:1px solid var(--line); border-radius:6px; padding:10px 12px; display:grid; gap:8px }
details.more > .checks { margin-top:8px }
.checks-head { display:flex; flex-wrap:wrap; justify-content:space-between; gap:2px 12px; align-items:baseline }
.checks-head .t { font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:500 } .checks-head .sum { font-size:var(--fs-s); color:var(--fg2) }
.checks ul { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:1fr; gap:6px 18px }
.ck { display:grid; grid-template-columns:20px minmax(0,1fr) auto; gap:8px; align-items:start; font-size:var(--fs-s) }
.ck .ic { width:20px; height:20px; border-radius:50%; display:grid; place-items:center; font-size:11px; font-weight:700; line-height:1 }
.ck.ok .ic { background:color-mix(in srgb,var(--good-mark) 18%,var(--surface)); color:var(--good) } .ck.warn .ic { background:color-mix(in srgb,var(--warn-mark) 24%,var(--surface)); color:var(--warn) }
.ck.bad .ic { background:color-mix(in srgb,var(--bad-mark) 18%,var(--surface)); color:var(--bad) } .ck.note .ic { background:color-mix(in srgb,var(--accent) 14%,var(--surface)); color:var(--accent) }
.ck.unknown .ic { background:var(--chip); color:var(--muted) }
.ck .lb { min-width:0; line-height:1.3 } .ck .lb small { display:block; font-size:var(--fs-xs); color:var(--muted) }
.ck .vl { font-weight:500; text-align:right; line-height:1.3; font-variant-numeric:tabular-nums; max-width:15ch; overflow-wrap:anywhere } .ck.warn .vl { color:var(--warn) } .ck.bad .vl { color:var(--bad) }
.ck-leg { margin:0; font-size:var(--fs-xs); color:var(--muted) }
.groups { display:grid; gap:14px; margin-top:10px } .grp h4 { margin:0 0 6px; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:500 }
/* the history: two-line results and one square per tip */
td.res { white-space:normal; min-width:15ch } td.res .r1 { display:block; white-space:nowrap; font-weight:500 } td.res .r2 { display:block; font-size:var(--fs-xs); color:var(--muted); margin-top:2px }
td.res.good .r1 { color:var(--good) } td.res.bad .r1 { color:var(--bad) }
.stripbox { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px 14px; display:grid; gap:10px }
.strip-head { display:flex; flex-wrap:wrap; justify-content:space-between; gap:2px 12px; align-items:baseline } .strip-head .t { font-weight:600 } .strip-head .sum { font-size:var(--fs-s); color:var(--fg2) }
.strip { display:flex; flex-wrap:wrap; gap:4px }
.sq { display:inline-block; width:16px; height:16px; border-radius:3px; background:var(--chip) } .strip .sq:hover { outline:2px solid var(--accent); outline-offset:1px }
.sq.good { background:var(--good-mark) } .sq.bad { background:color-mix(in srgb,var(--bad-mark) 45%,var(--surface)) } .sq.zero { background:var(--bad-mark) }
.sq.pend { background:none; border:1.5px dashed var(--muted) }
.strip-leg { display:flex; flex-wrap:wrap; gap:4px 14px; font-size:var(--fs-xs); color:var(--fg2); align-items:center } .strip-leg i.sq { width:10px; height:10px; margin-right:6px; vertical-align:-1px }
table { border-collapse:collapse; width:100%; font-size:var(--fs-s) } th,td { text-align:left; padding:8px 12px; border-top:1px solid var(--line2); vertical-align:top }
th { color:var(--muted); font-weight:500; font-size:var(--fs-xs); letter-spacing:.04em; text-transform:uppercase; border-top:0; white-space:nowrap }
td.n,th.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap } td.w { white-space:nowrap } td .good { color:var(--good) } td .bad { color:var(--bad) }
td .row { margin-top:4px }
details { font-size:var(--fs-s) } summary { cursor:pointer; color:var(--fg2) } details .tbl { margin-top:8px }
.empty { background:var(--surface); border:1px dashed var(--line); border-radius:8px; padding:14px 16px; color:var(--fg2) } .empty code { font-family:var(--mono); font-size:var(--fs-xs); background:var(--chip); padding:1px 5px; border-radius:4px }
.note { font-size:var(--fs-s); color:var(--fg2); margin:0; max-width:72ch; text-wrap:pretty } .note strong { color:var(--fg); font-weight:600 }
.runs td.note-cell { min-width:36ch; max-width:60ch; white-space:normal; color:var(--fg2) } .runs .note-cell strong { color:var(--fg); font-weight:500 }
.runs .note-cell details { margin-top:4px } .runs .note-cell p { margin:4px 0 0 }
footer { color:var(--muted); font-size:var(--fs-s); border-top:1px solid var(--line); padding-top:14px; display:flex; flex-wrap:wrap; gap:4px 20px }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
/* the card's own width decides the strip and the checklist columns (after their base rules, so these win) */
@container (min-width:640px) { .stats { grid-template-columns:repeat(6,minmax(0,1fr)) } }
@container (min-width:430px) { .checks ul { grid-template-columns:1fr 1fr } }
@container (min-width:880px) { .checks ul { grid-template-columns:1fr 1fr 1fr } }
/* the agent office (third tab): the floor plan of the last run, one department open beside it (below it on phones), the team timeline */
.office { display:grid; gap:12px } .office > input { position:fixed; top:0; left:0; opacity:0; pointer-events:none }
.ostrip { display:flex; flex-wrap:wrap; gap:6px }
.ostrip span { display:inline-flex; gap:6px; align-items:baseline; padding:5px 12px; border-radius:999px; background:var(--surface); border:1px solid var(--line); font-size:var(--fs-s); color:var(--fg2) }
.ostrip b { color:var(--fg); font-weight:600; font-variant-numeric:tabular-nums } .ostrip .bad { border-color:color-mix(in srgb,var(--bad-mark) 50%,var(--line)) } .ostrip .bad b { color:var(--bad) }
.ogrid { display:grid; gap:12px; align-items:start; grid-template-columns:minmax(0,1fr) }
.omap { padding:12px } .ofloor { position:relative; margin-inline:auto } .chart .wide .ofloor { max-width:720px } .chart .narrow .ofloor { max-width:360px }
.chart .ofloor .chart-svg { max-width:none }
.ohit { position:absolute; display:block; cursor:pointer; border-radius:10px } .ohit:hover { background:color-mix(in srgb,var(--fg) 5%,transparent) }
.ofl .wire { fill:none; stroke:var(--dc); stroke-width:1.5; stroke-dasharray:5 5; opacity:.85; animation:owire 1.6s linear infinite }
@keyframes owire { to { stroke-dashoffset:-20 } }
.ofl .top { fill:color-mix(in srgb,var(--dc) 22%,var(--surface)); stroke:var(--dc); stroke-width:1.25 } .ofl .side { fill:color-mix(in srgb,var(--dc) 55%,var(--bg)) }
.ofl .halo { fill:none; stroke:var(--dc); stroke-width:2; opacity:0 }
.ofl .dk { fill:color-mix(in srgb,var(--fg) 30%,var(--surface)) } .ofl .dks { fill:color-mix(in srgb,var(--fg) 14%,var(--bg)) }
.ofl .mon { fill:var(--bg); stroke:color-mix(in srgb,var(--fg) 35%,var(--surface)); stroke-width:1 } .ofl .scr { fill:color-mix(in srgb,var(--dc) 75%,var(--surface)) }
.ofl .scr.failed { fill:var(--bad-mark) } .ofl .scr.fallback { fill:var(--warn-mark) } .ofl .desk.off .scr { fill:var(--line) } .ofl .desk.off { opacity:.5 }
.ofl .who { fill:var(--fg2) } .ofl .pill { fill:color-mix(in srgb,var(--s2) 20%,var(--surface)); stroke:var(--s2); stroke-width:1 }
.ofl .pill-t { fill:var(--fg); font-size:11px; font-weight:500 }
.ofl .oname { fill:var(--fg); font-size:13px; font-weight:600 } .ofl .osub { fill:var(--fg2); font-size:12px } .ofl .omut { fill:var(--muted); font-size:12px; font-variant-numeric:tabular-nums }
.ofl .lt { font-size:11px } .ofl .lt.done { fill:var(--good-mark) } .ofl .lt.failed { fill:var(--bad-mark) } .ofl .lt.fallback { fill:var(--warn-mark) } .ofl .lt.skipped { fill:var(--muted) } .ofl .lt.running { fill:var(--accent) }
.ofl .glow { fill:var(--accent) } .ofl .g1 { opacity:.2 } .ofl .g2 { opacity:.1 } .ofl .g3 { opacity:.05 }
.ofl .core { fill:color-mix(in srgb,var(--accent) 16%,var(--surface)); stroke:var(--accent); stroke-width:1.5 } .ofl .hub-t { fill:var(--fg); font-size:12px; font-weight:600; letter-spacing:.08em }
.ofl .hub-n { fill:var(--fg); font-size:14px; font-weight:600; font-variant-numeric:tabular-nums }
.olegend span::before { border-radius:50% } .olegend .ob::before { width:22px; height:12px; border-radius:6px; background:color-mix(in srgb,var(--s2) 20%,var(--surface)); border:1px solid var(--s2) }
.opanel { display:none; gap:12px; align-content:start }
.opanel .ohead { display:flex; justify-content:space-between; align-items:flex-start; gap:6px 12px; flex-wrap:wrap } .opanel h3 { font-size:17px; margin:2px 0 0 }
.oagent { display:grid; gap:10px; padding-top:12px; border-top:1px solid var(--line2) } .oagent > div, .oagent > p { min-width:0 }
.oagent .who { display:flex; flex-wrap:wrap; gap:6px 8px; align-items:center } .oagent .who strong { font-size:15px }
.oagent .job, .oagent .clk { margin:0; color:var(--fg2); font-size:var(--fs-s) } .oagent .clk { font-variant-numeric:tabular-nums }
.opanel .olab, .olive .olab { display:block; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:500; margin-bottom:4px }
.omsg { margin:0; padding:8px 10px; border-radius:6px; background:var(--chip); font-size:var(--fs-s); overflow-wrap:anywhere } .omsg.warn { border-left:3px solid var(--warn-mark) }
.oout { margin:0; font-weight:600; overflow-wrap:anywhere } .oout + .oout { font-weight:400; font-size:var(--fs-s); color:var(--fg2); margin-top:2px }
.oshare { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; font-size:var(--fs-xs); color:var(--fg2); font-variant-numeric:tabular-nums; margin-bottom:4px }
.obar { display:block; height:6px; border-radius:999px; background:var(--line2); overflow:hidden } .obar i { display:block; height:100%; border-radius:999px; background:var(--s1) } .obar.bg i { background:var(--s2) }
.olines { list-style:none; margin:0; padding:0; display:grid }
.oline { display:grid; grid-template-columns:12px minmax(0,1fr) auto; gap:8px; align-items:baseline; padding:4px 0; border-top:1px solid var(--line2); font:var(--fs-xs)/1.45 var(--mono) }
.oline .ic { color:var(--muted) } .oline .tx { overflow-wrap:anywhere; color:var(--fg) } .oline.warn .ic, .oline.warn .tx { color:var(--warn) }
.oline .m { display:inline-grid; grid-template-columns:44px auto; gap:6px; align-items:center; color:var(--muted); font-family:var(--sans); font-variant-numeric:tabular-nums }
.oline .m .obar { height:4px } .oline .m .obar i { background:var(--muted) }
.chart-svg .gbar.fg { fill:var(--s1) } .chart-svg .gbar.bg { fill:var(--s2) } .chart-svg .gbar.failed { fill:var(--bad-mark) } .chart-svg .gbar.fallback { stroke:var(--warn-mark); stroke-width:2 }
.chart-svg .gbar.open { fill-opacity:.45; stroke:var(--bad-mark); stroke-dasharray:3 2 } .chart-svg .lane { stroke:var(--line2); stroke-width:1 }
.chart-svg [data-tip]:hover .gbar { opacity:.8 }
/* the live view (a page built on GitHub Actions polls the branch "live" while a scan runs): without the script only the line with the website shows */
[data-lv][hidden] { display:none !important } .olink a { color:var(--accent); overflow-wrap:anywhere }
.olive { display:grid; gap:10px; padding:12px 14px; border:1px solid var(--line); border-radius:8px; background:var(--surface) } .olive p { margin:0 }
.olive .olv-head { display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center }
.obadge { display:inline-flex; align-items:center; gap:8px; padding:4px 12px; border-radius:999px; background:color-mix(in srgb,var(--bad-mark) 14%,var(--surface)); color:var(--bad);
  font-size:var(--fs-s); font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap }
.obadge i { width:8px; height:8px; border-radius:50%; background:var(--bad-mark); animation:opulse 1.6s ease-in-out infinite }
.onow { margin:0; padding:0; list-style:none; display:grid; gap:4px; font-size:var(--fs-s); color:var(--fg2) } .onow li { overflow-wrap:anywhere } .onow b { color:var(--fg); font-weight:600; margin-right:6px }
@keyframes opulse { 50% { opacity:.3 } } @keyframes ohalo { 0%, 100% { opacity:.15 } 50% { opacity:.85 } }
.office[data-live] .ofl .plat[data-live="wait"] { opacity:.45 } .office[data-live] .ofl .plat[data-live="work"] .halo { animation:ohalo 2s ease-in-out infinite }
.office[data-live] .ofl .hub[data-live="work"] .g1 { animation:opulse 2s ease-in-out infinite }
.office[data-live] .ofl .desk[data-live] { opacity:1 } .office[data-live] .ofl .plat:not([data-live="wait"]) .desk[data-live="wait"] { opacity:.5 }
.office[data-live] .ofl .desk[data-live="wait"] .scr { fill:var(--line) } .office[data-live] .ofl .desk[data-live="done"] .scr { fill:var(--good-mark) }
.office[data-live] .ofl .desk[data-live="fail"] .scr { fill:var(--bad-mark) } .office[data-live] .ofl .desk[data-live="work"] .scr { fill:var(--accent); animation:opulse 1.2s ease-in-out infinite }
.office[data-live] .ofl [data-live="work"] .lt { fill:var(--accent) } .office[data-live] .ofl [data-live="done"] .lt { fill:var(--good-mark) }
.office[data-live] .ofl [data-live="fail"] .lt { fill:var(--bad-mark) } .office[data-live] .ofl [data-live="wait"] .lt { fill:var(--muted) }
.office[data-live] .opanel [data-st]::before { content:"last run: " }
@media (min-width:1080px) { .ogrid { grid-template-columns:minmax(0,1fr) minmax(320px,360px) } .omap { position:sticky; top:12px } }
@media (prefers-reduced-motion: reduce) { .tip, details.fold > summary::after { transition:none } .ofl .wire { animation:none }
  .obadge i, .office[data-live] .ofl .plat[data-live] .halo, .office[data-live] .ofl .hub[data-live] .g1, .office[data-live] .ofl .desk[data-live] .scr { animation:none }
  .office[data-live] .ofl .plat[data-live="work"] .halo { opacity:.7 } }
@media (max-width:700px) { .chart .wide { display:none } .chart .narrow { display:block } }
@media (max-width:560px) {
  body { font-size:15px } h1 { font-size:21px } .wrap { gap:16px } .pane { gap:20px } footer { padding-top:10px }
  .tabbar { gap:0 } .tabbar label { padding:8px 9px; gap:5px; font-size:14px; white-space:nowrap } .tabbar .cnt { padding:1px 6px }
  .note, .why, .safety, .sec-head p, details, table, .legend, .tile .sub, header .meta, .live, .links a { font-size:14px } .chip { font-size:13px }
  .hero { grid-template-columns:1fr 1fr } .hero .tile.lead { grid-column:1 / -1 } .hero .tile:last-child:nth-child(even) { grid-column:1 / -1 } .tile.lead .value { font-size:32px }
  .ck .vl { max-width:13ch } .acct { grid-template-columns:1fr 1fr } .acct .lead { grid-column:1 / -1; border-bottom:1px solid var(--line2) } .acct > div + div { border-left:0 }
  .acct .cell:nth-child(3) { border-left:1px solid var(--line2) } .acct .cell:last-child { grid-column:1 / -1; border-top:1px solid var(--line2) }
  details.hold > summary { grid-template-columns:1fr auto; grid-template-areas:"who plv" "track track" "meta meta"; padding:12px 14px } details.hold .body { padding:12px 14px }
  .verdicts .v { font-size:20px } .spark-box { padding-right:46px }
  .card.rec .links { flex-wrap:wrap; overflow:visible }
  .kv { grid-template-columns:1fr 1fr } .embed { height:240px } .card { gap:12px } .odds { grid-template-columns:1fr 1fr } .odds .tile:last-child { grid-column:1 / -1 }
  .stack table, .stack tbody, .stack tr, .stack td { display:block } .stack thead { display:none } .stack tr { padding:10px 12px; border-top:1px solid var(--line2) } .stack tr:first-child { border-top:0 }
  .stack td { border-top:0; padding:2px 0; text-align:left; white-space:normal; min-width:0; max-width:none } .stack td.n, .stack td.w, .stack td.m, .stack td.act { display:inline-block; padding-right:12px }
  .stack td.d { display:inline-block; padding-right:12px } .stack td.res { display:block } .stack td.res .r1 { display:inline } .stack td.n::before, .stack td.d::before { content:attr(data-k) " "; color:var(--muted); font-size:12px } .stack td.act { padding-top:4px } }
@media (max-width:370px) { .tabbar label { padding:8px 6px; font-size:13px } }
""" + "@container (max-width:%dpx) { .track .tl.at { display:none } }\n" % (TRACK_AT_MIN_W - 1) + OFFICE_CSS + "\n"

# the early list on the New launches tab (only on a page built with GITHUB_REPOSITORY, so a page built elsewhere stays as it was): one column
# of cards on a phone, two from 760px; tap targets of at least 44px; the page's own colour tokens, so light and dark both work; nothing moves
THEME_CSS = r"""
/* The look since Oct 22 (the user: modern, easy on the eye): a deep night-blue theme by default (a page can still ask for the light one with
   data-theme="light"), soft glass cards, a pill tab bar, neon accents shared with the brain (--nn1 cyan, --nn2 violet). Only tokens and a
   few frames change here; every block keeps its own layout. */
:root:not([data-theme="light"]) { --bg:#070a14; --surface:#0f1424; --fg:#edf0fb; --fg2:#b8bfd6; --muted:#8890ad; --line:#1f2742; --line2:#192038;
  --accent:#6f8dff; --s1:#5b8cff; --s2:#ff8a4c; --s3:#2ad49a; --good:#3ddc84; --good-mark:#22c56e; --bad:#ff6b7a; --bad-mark:#ff5a6a; --warn:#ffc35c; --warn-mark:#f2a93b;
  --chip:#1a2138; --t3:#b18cff; color-scheme:dark }
:root { --nn1:#22d3ee; --nn2:#a855f7 }
:root:not([data-theme="light"]) { --nn1:#7cf7ff; --nn2:#b76bff }
:root:not([data-theme="light"]) body { background:radial-gradient(1200px 600px at 10% -10%, rgba(111,141,255,.16), transparent 60%),
  radial-gradient(900px 500px at 110% 10%, rgba(183,107,255,.12), transparent 60%), var(--bg); background-attachment:fixed }
.card, .tile, .chart, details.fold > summary, .sstrip { border-radius:14px }
:root:not([data-theme="light"]) .card, :root:not([data-theme="light"]) .tile, :root:not([data-theme="light"]) .chart,
:root:not([data-theme="light"]) details.fold > summary { background:color-mix(in srgb,var(--surface) 88%,transparent); box-shadow:0 1px 0 rgba(255,255,255,.03) inset }
h1 { background:linear-gradient(90deg,var(--fg) 30%,var(--nn1) 75%,var(--nn2)); -webkit-background-clip:text; background-clip:text; color:transparent }
.tabbar { gap:4px; padding:4px; border:1px solid var(--line); border-radius:999px; background:color-mix(in srgb,var(--surface) 80%,transparent);
  position:sticky; top:8px; z-index:5; backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px) }
.tabbar label { border:none; border-radius:999px; margin:0; min-height:40px; padding:8px 14px; justify-content:center; flex:1 1 auto; transition:background .2s, color .2s }
#tab-home:checked ~ .tabbar label[for="tab-home"], #tab-pick:checked ~ .tabbar label[for="tab-pick"], #tab-young:checked ~ .tabbar label[for="tab-young"],
#tab-account:checked ~ .tabbar label[for="tab-account"], #tab-office:checked ~ .tabbar label[for="tab-office"] {
  color:#fff; border:none; background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--nn2) 75%,var(--accent))); box-shadow:0 4px 14px -6px var(--accent) }
@media (max-width:560px) { .tabbar { gap:0; padding:3px } .tabbar label { padding:8px 6px; font-size:13.5px; min-height:38px } }
.arch-head { display:grid; gap:4px } .arch-head p { margin:0; color:var(--fg2); font-size:var(--fs-s); max-width:70ch }
"""

EARLY_CSS = r"""
.ehint { margin:0 }
details.early { background:var(--surface); border:1px solid var(--line); border-radius:8px; min-width:0 }
details.early > summary { list-style:none; display:flex; align-items:center; justify-content:space-between; gap:6px 12px; min-height:44px; padding:8px 14px; cursor:pointer; font-size:var(--fs-s); color:var(--fg) }
details.early > summary::-webkit-details-marker { display:none }
details.early > summary:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:8px }
.estatus { min-width:0; overflow-wrap:anywhere; text-wrap:pretty } .estatus::before { content:"›"; display:inline-block; margin-right:8px; color:var(--muted); transform:rotate(0deg) }
details.early[open] .estatus::before { transform:rotate(90deg) }
.obadge.eb { flex:none; padding:2px 10px; font-size:var(--fs-xs); letter-spacing:.06em; background:color-mix(in srgb,var(--accent) 12%,var(--surface)); color:var(--accent) }
.ebody { display:grid; gap:10px; padding:12px 14px 14px; min-width:0; border-top:1px solid var(--line2) }
.eorder { display:flex; flex-wrap:wrap; gap:8px }
.eorder label { position:relative; display:inline-flex; align-items:center; min-height:44px; padding:0 16px; border:1px solid var(--line); border-radius:999px; cursor:pointer; font-size:var(--fs-s); font-weight:500; color:var(--fg2); background:var(--surface) }
.eorder input { position:absolute; opacity:0; pointer-events:none }
.eorder label:has(input:checked) { color:var(--accent); border-color:var(--accent); background:color-mix(in srgb,var(--accent) 8%,var(--surface)) }
.eorder label:has(input:focus-visible) { outline:2px solid var(--accent); outline-offset:2px }
.ecards { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:minmax(0,1fr); gap:10px }
@media (min-width:760px) { .ecards { grid-template-columns:repeat(2,minmax(0,1fr)) } }
.ecard { border:1px solid var(--line); border-radius:8px; padding:10px 12px; display:grid; grid-template-columns:minmax(0,1fr); gap:6px; min-width:0; align-content:start }
details.early.dim .ecards, .ecard.old { opacity:.8 } details.early.dim .ecard.old { opacity:1 } .ecard.old { border-style:dashed }
details.early.nolist > summary { cursor:default } details.early.nolist .estatus::before { display:none }
.ehd { display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px; min-width:0 }
.ehd .ek { flex:none; min-width:18px; color:var(--muted); font:500 var(--fs-s) var(--mono) }
.ehd .es { flex:none; max-width:45%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; font-size:16px }
.ehd .enm { flex:1 1 72px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--fg2); font-size:var(--fs-s) }
.ehd .chip { flex:none }
.eline { margin:0; font:var(--fs-s)/1.45 var(--mono); color:var(--fg2); overflow-wrap:anywhere } .eline span { white-space:nowrap }
.eline span.ewrap { white-space:normal }   /* a launchpad or a DEX name comes from the sources (up to 24 characters): it may break, the page never widens */
.ecard .chips .chip { white-space:normal; overflow-wrap:anywhere }
.elinks { display:flex; flex-wrap:wrap; gap:8px }
.lchip { display:inline-flex; align-items:center; justify-content:center; min-height:44px; min-width:44px; box-sizing:border-box; padding:0 11px; border:1px solid var(--line); border-radius:999px; font-size:var(--fs-s); font-weight:500; color:var(--accent); background:var(--surface); text-decoration:none }
.lchip:hover { border-color:var(--accent); text-decoration:none } .lchip:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
@media (prefers-reduced-motion: reduce) { .estatus::before { transition:none } }
"""

JS = r"""
(function(){
  var tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
  function show(x,y,text){tip.textContent=text;tip.classList.add('on');var w=tip.offsetWidth,h=tip.offsetHeight;
    var left=Math.min(x+14,window.innerWidth-w-8),top=y-h-12;if(top<8)top=y+16;tip.style.left=left+'px';tip.style.top=top+'px';}
  function hide(){tip.classList.remove('on');}
  function overlay(e,o){var pts=o._pts||(o._pts=JSON.parse(o.getAttribute('data-pts')));var svg=o.ownerSVGElement;var r=svg.getBoundingClientRect();
    var vb=svg.viewBox.baseVal;var x=(e.clientX-r.left)/r.width*vb.width;var best=pts[0],bd=1e9;
    for(var i=0;i<pts.length;i++){var d=Math.abs(pts[i].x-x);if(d<bd){bd=d;best=pts[i];}}
    var c=svg.querySelector('.cross');if(c){c.setAttribute('x1',best.x);c.setAttribute('x2',best.x);c.style.opacity=1;}
    show(e.clientX,e.clientY,best.t+'\n'+best.v.map(function(v){return v[0]+': '+(typeof v[1]==='number'?v[1].toFixed(2):v[1]);}).join('\n'));}
  function handle(e){
    var m=e.target.closest&&e.target.closest('[data-tip]');
    if(m){show(e.clientX,e.clientY,m.getAttribute('data-tip'));return;}
    var o=e.target.closest&&e.target.closest('.overlay');
    if(o){overlay(e,o);return;}
    document.querySelectorAll('.cross').forEach(function(c){c.style.opacity=0;});hide();
  }
  document.addEventListener('mousemove',handle);
  document.addEventListener('click',handle);
  document.addEventListener('mouseleave',hide);
})();
"""


# the live view of the agent office: reads live.json on the branch "live" (bot.py pushes it while a scan runs: every 45 s when it changed,
# at least once a minute) through GitHub's contents API, only while the browser tab is visible and the office tab is open. The page
# sends no token, so every answer counts against the 60 requests an hour GitHub allows one address, a 304 too: it sends no ETag
# and asks for the raw file (Accept: application/vnd.github.raw+json, a header that needs no CORS preflight). It polls every 75 s while
# the newest snapshot is a live scan (at most 48 an hour); after the scan only on a grid around the hourly schedule: 2 minutes before
# the next scheduled start, 5 minutes after it (the scan starts a minute or two late and its first push is out by then), then every 10 minutes (6 an hour). GitHub's
# X-RateLimit-Remaining and -Reset stretch every gap so the address keeps 10 requests (other pages and devices behind it slow down
# instead of running out), a failed or 20 s slow fetch backs off, and the tabs of one browser share one poll and its answer through
# localStorage (a reload asks nothing new). It says "finished" only for a snapshot with "live": false; a live one that went 5 minutes
# without an update, or two failed polls in a row, read "paused". It only sets attributes and texts on the elements office_floor and
# office_panel mark with data-agent / data-agents, the SVG stays as drawn. The open tab and department survive the website's reloads
# (sessionStorage), and the website reloads once when a newer scan has finished and its page is out (4 minutes after its end).
# A 404 (no branch "live" yet) counts as no snapshot, not as a failure. window.MemebotLive holds the decisions (what to show, when
# to poll next, what the early list shows) for the tests; window.MEMEBOT_LIVE_SRC and window.MEMEBOT_LIVE_T (times in ms) point it elsewhere in tests.
# The New launches tab polls the same file (one poll for both tabs): live.json "young" is the early list of the scan running now, which
# bot.py pushes within seconds of its launch spotter writing it, about 5 minutes into the scan. In the scan window (2 minutes before a
# scheduled start to 35 after it, until that scan's last push) the page polls every 75 s, so a scan that starts late is caught too.
# Coin ages are counted from live.json's "updated" plus the local time since that "updated" was first seen here, never from the phone's
# clock; whether a snapshot is fresh is judged the same way once its "updated" has moved, the phone's clock is only the first guess.
# The cards are built with createElement and textContent only, once per new list, order or state (the ages change in place, so a
# selection or the focus survives); links come from fixed templates and an address that passes the base58 check, never a swap link.
# #new opens the tab once (the hash is dropped, so a reload keeps the tab the reader chose).
# The transport: a website built with the app's live store (bot.py site puts data-sb-url and a publishable data-sb-key on <html>) reads
# the Supabase row status instead while the page is visible (in a browser tab while the New launches or Agent office tab is open, one
# poll for all tabs of the browser through localStorage; in the installed app on any tab): every 4 s while a scan is live, every 30 s
# otherwise (a new scan shows within half a minute; an app left open and visible all day reads about 1.5 GB a month, inside the free
# plan's 5 GB), and the row current only when status names a new nver (its early list or pick changed: the page takes only those two
# from it). The snapshot the page draws is status with current's early list ("young")
# and pick when current is of the same scan (MB.merge), so it has the same shape as live.json on the GitHub poll: the office view and the
# early box draw it the same way, whichever transport brought it (one poller at a time, never both). An HTTP 540 (project paused) or two
# failures in a row (network, CORS, any other status) fall back to the GitHub poll above, quietly, and the live store is tried again 2
# minutes later. Every answer, and every change of what the early box shows, goes out as the window event "memebot-live" (detail: via,
# status: the snapshot, current: the whole record, state: the office's state, early: the early box's state, young: the early list) for
# the installed app's tab bar; MemebotLive.current() is the newest whole record.
OFFICE_LIVE_JS = r"""
(function(){
var MB=window.MemebotLive={LIVE:75000,IDLE:600000,STALE:300000,TIMEOUT:20000,RESERVE:10,GRID:[-2,5,15,25,35,45],WIN:[-2,35],EARLY_OLD:4500000,LAG:120000,RELOAD_AFTER:90000,RELOAD_GAP:120000,RELOADS:4,
  SB_EVERY:4000,SB_IDLE:30000,SB_TIMEOUT:8000,SB_RETRY:120000,SB_FAILS:2,
  // how old a snapshot is (ms). got: the local time its "updated" was first seen here; moved: it replaced an older "updated" of the same
  // scan, so the scan is pushing and the phone's clock is not needed: the local time since then, plus the delay it was seen with (at
  // most LAG). Before that, the phone's clock is the first guess (never less than the local time since). Without got: the phone's clock.
  age:function(doc,now,got,moved){var up=+(doc&&doc.updated)||0,loc=got>0?Math.max(0,now-got):null;
    return loc==null?now-up:moved?loc+Math.min(MB.LAG,Math.max(0,got-up)):Math.max(loc,now-up);},
  // which transport the page uses: supabase when it carries the live store's https address and a publishable key, else github when
  // it has the box for the branch "live", else none
  transport:function(url,key,src){
    if(/^https:\/\/[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?\/?$/.test(String(url||''))&&/^sb_publishable_[A-Za-z0-9_-]+$/.test(String(key||'')))return 'supabase';
    return src?'github':'none';
  },
  // after a poll of the live store (status: the HTTP status, 0 for no answer: network, CORS or timeout; fails: failures in a row, this
  // one included): stay with supabase, or fall back to github (540: the project is paused; SB_FAILS failures in a row)
  fallback:function(status,fails){return status>=200&&status<300?'supabase':status===540||fails>=MB.SB_FAILS?'github':'supabase';},
  // when the next poll of the live store is due (ms): SB_EVERY while the snapshot is a live scan updated within STALE (by age(), so a
  // phone clock that is off does not slow it down), else SB_IDLE; doubled per failure in a row, up to 30 s (live) or 2 minutes
  sbNext:function(now,fails,doc,got,moved){var live=!!(doc&&typeof doc==='object'&&doc.live===true&&MB.age(doc,now,got,moved)<MB.STALE),f=Math.max(0,Math.min(10,+fails||0));
    return now+Math.min(live?30000:120000,(live?MB.SB_EVERY:MB.SB_IDLE)*Math.pow(2,f));},
  // the snapshot from the live store: the row status (fresh every few seconds; of the early list and the pick it has only a brief) with
  // the early list and the pick of the row current when that is of the same scan, else no early list
  merge:function(st,cur){if(!st||typeof st!=='object')return st;var d={},k,same=!!(cur&&typeof cur==='object'&&cur.t===st.t);for(k in st)d[k]=st[k];
    d.young=same&&cur.young&&typeof cur.young==='object'?cur.young:null;if(same&&cur.pick&&typeof cur.pick==='object')d.pick=cur.pick;return d;},
  // what the box shows for the newest snapshot: hide (none, or older than this page's run), live, paused (a live one older than
  // STALE by its "updated", or two failed polls in a row: the scan may still run), done, stopped (no report came from it)
  state:function(doc,now,pageT,fails,got,moved){
    if(!doc||typeof doc!=='object'||!Array.isArray(doc.agents)||(+doc.t||0)<pageT)return 'hide';
    if(doc.live===true)return MB.age(doc,now,got,moved)<MB.STALE&&(+fails||0)<2?'live':'paused';
    if(doc.live!==false)return 'hide';
    var rep=null,bad=false;
    doc.agents.forEach(function(a){if(a&&a.id==='reporter')rep=a;if(a&&a.status==='failed'&&a.id!=='spotter')bad=true;});   // a failed early list is not a failed scan
    return rep&&rep.status==='done'&&!bad?'done':'stopped';
  },
  // RugCheck's words on a card: the coin's report, else "checking..." while the spotter still asks, else "did not finish" (the spotter was
  // stopped or failed before RugCheck answered for it)
  rcChip:function(rc,rcState){var lv=rc&&typeof rc==='object'?rc.level:null,t=lv?String(typeof rc.text==='string'?rc.text:'').slice(0,120):'';
    return lv==='clean'?'RugCheck: no danger flags':lv==='none'?(t||'no RugCheck report'):lv==='danger'||lv==='warn'?(t||'RugCheck'):
      rcState==='pending'?'RugCheck: checking…':'RugCheck did not finish';},
  // RugCheck in the status line: checking, did not answer, did not finish (the spotter was stopped: rcWhy, or coins without words), or how
  // many reports came
  rcSum:function(y,coins){if(!y)return '';if(y.rcState==='pending')return ' · RugCheck checking…';if(y.rcState==='down')return ' · RugCheck did not answer';
    var cs=(coins||[]).filter(function(c){return c&&typeof c==='object';}),got=cs.filter(function(c){return c.rc&&typeof c.rc==='object'&&c.rc.level&&c.rc.level!=='none';}).length;
    if(y.rcState==='partial'&&(y.rcWhy||cs.some(function(c){return !(c.rc&&typeof c.rc==='object');})))return ' · RugCheck did not finish'+(got?' (reports for '+got+' of '+cs.length+')':'');
    return ' · RugCheck reports for '+got+' of '+cs.length;},
  // the early list a snapshot carries: live.json "young" of the same scan, or null
  young:function(doc){var y=doc&&typeof doc==='object'?doc.young:null;return y&&typeof y==='object'&&Array.isArray(y.coins)&&+y.t>0&&+y.t===+doc.t?y:null;},
  // what the New launches tab's early box shows (section "states" of the build spec): doc is the newest snapshot, own the page's own early
  // list (its scan is pageT), got and moved as for age() (coin ages and the 75-minute limit never use the phone's clock)
  early:function(doc,now,pageT,fails,rem,reset,scan,own,got,moved){
    var M=60000,h=3600000,y=MB.young(doc),k,s,live=!!(doc&&typeof doc==='object'&&Array.isArray(doc.agents)&&(+doc.t||0)>pageT);
    if(live){
      var up=+doc.updated||0,srv=up+(got?Math.max(0,now-got):0),fresh=doc.live===true&&MB.age(doc,now,got,moved)<MB.STALE&&(+fails||0)<2;
      if(srv-(y?(+y.at||+y.t):+doc.t)>MB.EARLY_OLD)return 'hide';
      if(doc.live===true){
        if(rem===0&&!fresh)return 'limited';
        if(!fresh)return 'paused';
        if(!y)return 'wait';
        return y.state==='listed'?(y.partial===true?'partial':'listed'):y.state==='empty'?'empty':'none';
      }
      if(doc.live!==false||!y||y.state!=='listed')return 'hide';
      var rep=null;doc.agents.forEach(function(a){if(a&&a.id==='reporter')rep=a;});
      return rep&&rep.status==='done'?'done':'stopped';
    }
    var o=y&&+y.t===pageT?y:(own&&typeof own==='object'&&+own.t===pageT?own:null);
    if(o&&pageT>0&&o.state==='listed'&&Array.isArray(o.coins))return 'own';
    if(scan>0){k=Math.floor((now-scan)/h);s=scan+k*h;       // the last scheduled start: its scan should have reported by now
      if(now>=s+12*M&&now<=s+35*M&&Math.max(doc&&typeof doc==='object'?+doc.t||0:0,pageT)<s-5*M)return rem===0?'limited':'late';}
    return 'hide';
  },
  // when the next poll is due (ms): LIVE after a live snapshot; else the next grid point (minutes from a scheduled start, scan: the
  // next one when the page was made), IDLE without it; a failed poll waits longer; stretched to keep RESERVE requests until the reset
  next:function(doc,now,scan,rem,reset,fails,got,moved){
    var h=3600000,t=now+MB.IDLE,k,i,g,s,k0=Math.floor((now-scan)/h);
    if(doc&&typeof doc==='object'&&doc.live===true&&MB.age(doc,now,got,moved)<MB.STALE)t=now+MB.LIVE;
    else if(scan>0&&MB.GRID.length){t=Infinity;
      for(k=k0-1;k<=k0+1;k++){s=scan+k*h;
        for(i=0;i<MB.GRID.length;i++){g=s+MB.GRID[i]*60000;if(g>now+30000&&g<t)t=g;}
        // the scan window: every LIVE from 2 minutes before a scheduled start to 35 after it, until a last snapshot of that scan is in
        if(now>=s+MB.WIN[0]*60000&&now<=s+MB.WIN[1]*60000&&!(doc&&typeof doc==='object'&&doc.live===false&&(+doc.t||0)>=s-300000))t=Math.min(t,now+MB.LIVE);}}
    if(fails>0)t=Math.max(t,now+Math.min(1800000,MB.LIVE*Math.pow(2,fails)));
    if(rem!=null&&rem>=0&&reset>0){var left=Math.min(h,Math.max(0,reset*1000-now));t=Math.max(t,now+(rem>MB.RESERVE?left/(rem-MB.RESERVE):left+5000));}
    return t;
  }};
function go(){
  var box=document.querySelector('[data-live-src]');if(!box||!window.fetch||!window.Promise)return;
  var T=window.MEMEBOT_LIVE_T;if(T&&typeof T==='object')Object.keys(T).forEach(function(k){MB[k]=T[k];});
  var src=window.MEMEBOT_LIVE_SRC||box.getAttribute('data-live-src'),KEY='memebot-live '+src,names={};
  var pageT=+box.getAttribute('data-run-t')||0,scan=+box.getAttribute('data-next-scan')||0,home=box.getAttribute('data-pages')||'',tz=box.getAttribute('data-tz'),tzn=box.getAttribute('data-tzn');
  try{names=JSON.parse(box.getAttribute('data-names'))||{};}catch(e){}
  var all=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
  var office=document.querySelector('.office'),off=box.querySelector('[data-live-off]'),badge=box.querySelector('[data-live-badge]');
  var tabs=['tab-office','tab-young','tab-account'].map(function(i){return document.getElementById(i);}).filter(Boolean);   // the GitHub polls run while one of them is open (Brain, Radar, Archive: the old office)
  var root=document.documentElement,sbUrl=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),sbKey=root.getAttribute('data-sb-key')||'';
  var mode=MB.transport(sbUrl,sbKey,src),SB={next:0,fails:0,busy:false,nv:null,cur:null,st:null,back:0,at:0},SBKEY='memebot-sb '+sbUrl;
  var onSite=!!home&&location.href.indexOf(home)===0;if(onSite)all('[data-live-link]').forEach(function(e){e.hidden=true;});
  var inApp=function(){return root.classList.contains('app');};      // the installed app (app.py PAGE_JS): it polls on any of its tabs
  MB.via=function(){return mode;};MB.current=function(){return mode==='supabase'?SB.cur:S.doc;};
  // S: the newest snapshot, when the next poll is due, the failed polls in a row and GitHub's rate-limit numbers, shared by the tabs
  var S={doc:null,next:0,fails:0,rem:null,reset:0,at:0,got:0,moved:false},busy=false,shown=null,keep={};
  function load(){try{var s=JSON.parse(localStorage.getItem(KEY));if(s&&typeof s==='object'&&+s.at>S.at&&typeof s.next==='number'){S=s;return true;}}catch(e){}return false;}
  function save(){S.at=Date.now();try{localStorage.setItem(KEY,JSON.stringify(S));}catch(e){}}
  try{keep=JSON.parse(sessionStorage.getItem('memebot-keep'))||{};}catch(e){}
  if(keep.tab==='tab-radar')keep.tab='tab-young';      // the Radar tab is part of New now
  if(location.hash==='#new'&&document.getElementById('tab-young')){keep.tab='tab-young';try{sessionStorage.setItem('memebot-keep',JSON.stringify(keep));}catch(e){}
    try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}}     // once: a reload keeps the tab the reader chose
  all('input[name="tab"],input[name="odept"]').forEach(function(r){if(keep[r.name]===r.id)r.checked=true;
    r.addEventListener('change',function(){keep[r.name]=r.id;try{sessionStorage.setItem('memebot-keep',JSON.stringify(keep));}catch(e){}step();});});
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:tz})+' '+tzn;}catch(e){return new Date(ms).toTimeString().slice(0,5);}}
  function decode(b64){var s=atob(String(b64||'').replace(/\s+/g,'')),u=new Uint8Array(s.length);for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return JSON.parse(new TextDecoder('utf-8').decode(u));}
  function word(a){var s=a&&a.status;return !a?'wait':s==='running'?'work':s==='failed'?'fail':'done';}
  function mark(e,v){if(v)e.setAttribute('data-live',v);else e.removeAttribute('data-live');}
  function el(tag,text,kids){var e=document.createElement(tag);if(text)e.textContent=text;(kids||[]).forEach(function(k){e.appendChild(k);});return e;}
  function last(a){return a&&Array.isArray(a.lines)&&a.lines.length?String(a.lines[a.lines.length-1]):'';}
  function now(){return Date.now();}
  // the early list on the New launches tab: this page's own list and the scored list's verdict on each coin come with the page
  var ebox=document.querySelector('[data-early]'),eT=0,own=null,fin=null,eorder='new',eKey=null,eCards=null,eLabel=null,eSent=null;
  var B58=/^[1-9A-HJ-NP-Za-km-z]{32,48}$/,XL=/^https:\/\/(www\.)?(x|twitter)\.com\/[A-Za-z0-9_]{1,30}(\/status\/\d{1,25})?\/?$/;
  if(ebox){eT=+ebox.getAttribute('data-run-t')||0;
    try{own=JSON.parse(ebox.getAttribute('data-early-doc')||'null');}catch(e){}
    try{fin=JSON.parse(ebox.getAttribute('data-final')||'null');}catch(e){}
    try{var eo=localStorage.getItem('memebot-early-order');if(eo==='new'||eo==='score')eorder=eo;}catch(e){}
    all('input[name="eorder"]',ebox).forEach(function(r){r.checked=r.value===eorder;
      r.addEventListener('change',function(){if(!r.checked)return;eorder=r.value;try{localStorage.setItem('memebot-early-order',eorder);}catch(e){}eCards=null;try{drawEarly();}catch(x){}});});
    eLabel=ebox.querySelector('[data-early-label]');if(eLabel)eLabel._t=eLabel.textContent;
    var esum=ebox.querySelector('summary');if(esum)esum.addEventListener('click',function(e){if(ebox.classList.contains('nolist'))e.preventDefault();});}   // nothing to fold
  function isn(v){return typeof v==='number'&&isFinite(v);}
  function str(v,n){return (typeof v==='string'||isn(v)?String(v):'').slice(0,n);}
  function usd(v){if(!isn(v))return '?';var a=Math.abs(v),f=function(x){return x.toFixed(1).replace(/\.0$/,'');};
    return '$'+(a>=1e9?f(v/1e9)+'B':a>=1e6?f(v/1e6)+'M':a>=1e3?f(v/1e3)+'k':v.toFixed(0));}
  function pc(v){return isn(v)?(v>0?'+':v<0?'−':'')+Math.round(Math.abs(v))+'%':'?';}
  function dur(m){return m<60?Math.max(0,Math.floor(m))+' min':m<2880?Math.floor(m/60)+' h':Math.floor(m/1440)+' days';}
  function eur(b){return (b%1===0?String(b):b.toFixed(2))+' €';}
  function chip(text,cls){var c=el('span',text);c.className='chip'+(cls?' '+cls:'');return c;}
  function link(name,url){var a=el('a',name);a.className='lchip';a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
  // a card's age chip and token age at the server's time ref (null: at the time the list was made): set when the card is built and
  // again on every tick, only where the text changes, so a selection or the focus in the card survives
  function eages(li,c,y,ref){
    var born=isn(c.born)?c.born:null,age=born!=null&&ref!=null?(ref-born)/60000:(isn(c.ageMin)?c.ageMin:null),old=ref!=null&&age!=null&&age>=60;
    var t=age==null?'pair age unknown':old?'over 1 h now':'pair '+Math.max(0,Math.floor(age))+' min old'+(ref==null&&isn(+y.at)?' at '+hhmm(+y.at):'');
    var ce=li._age,cls='chip'+(age!=null&&!old&&age<=10?' neutral':'');
    if(ce.textContent!==t)ce.textContent=t;if(ce.className!==cls)ce.className=cls;
    if(li.classList.contains('old')!==old)li.classList.toggle('old',old);
    var tm=isn(c.minted)?((ref!=null?ref:+y.at)-c.minted)/60000:NaN;
    if(li._tok&&isFinite(tm)){t='token '+dur(tm)+' old';if(li._tok.textContent!==t)li._tok.textContent=t;}
  }
  function ecard(c,i,y,ref,fate){
    var li=el('li'),a=str(c.addr,48),born=isn(c.born)?c.born:null;
    li.className='ecard';li._age=chip('');
    var hd=el('div','',[el('span',String(i)),el('span',str(c.sym,24)||'?'),el('span',str(c.name,48)),li._age]);
    hd.className='ehd';hd.children[0].className='ek';hd.children[1].className='es';hd.children[2].className='enm';li.appendChild(hd);
    var l2=[],tok=isn(c.minted)&&(ref!=null||isn(+y.at)),lp=str(c.launchpad,24),dx=str(c.dex,24);
    if(tok)l2.push({tok:1,wrap:lp?'('+lp+')':''});                 // the token's age (filled by eages) and its launchpad
    if(dx)l2.push({wrap:dx});
    l2.push('liq '+usd(c.liq),'mc '+usd(c.mc));
    [l2,['1h vol '+usd(c.vol1),'5m '+pc(c.chgM5),'1h buys '+(isn(c.buysH1)?Math.round(c.buysH1):'?')+' / sells '+(isn(c.sellsH1)?Math.round(c.sellsH1):'?')]].forEach(function(l){
      var p=el('p');p.className='eline';l.forEach(function(x,j){if(j)p.appendChild(document.createTextNode(' · '));   // a line breaks between its facts
        if(typeof x==='string')return p.appendChild(el('span',x));
        if(x.tok){li._tok=el('span','');p.appendChild(li._tok);}
        if(x.wrap){var w=el('span',x.wrap);w.className='ewrap';if(x.tok)p.appendChild(document.createTextNode(' '));p.appendChild(w);}});   // a name from the sources
      li.appendChild(p);});                                                                                                            // may break: never wider than the card
    var ch=el('div'),rc=c.rc&&typeof c.rc==='object'?c.rc:null,lv=rc?rc.level:null;ch.className='chips';
    ch.appendChild(chip(MB.rcChip(rc,y.rcState),lv==='danger'?'bad':lv==='warn'?'warn':''));
    if(born!=null&&isn(c.minted)&&born-c.minted>=0&&born-c.minted<60000)ch.appendChild(chip('\u2715 pool opened with the mint','bad'));   // the one validated trap (rug study: instant pool)
    var fh=fate&&fate[a]&&typeof fate[a]==='object'&&fate[a].b==='held';      // the scored list's chip says it already
    if(c.held===true&&!fh)ch.appendChild(chip('paper: already held'));
    if(fate){var f=fate[a],on=f&&typeof f==='object'&&isn(f.k);
      var out=f&&typeof f==='object'?str(f.out,120):'',late=born!=null&&born>+y.t;
      if(late&&(!out||out==='born after the scan started'))out='born after the scan started (the scored list only takes coins older than the scan)';
      ch.appendChild(chip(on?'on the scored list #'+f.k+(isn(f.b)?' · bought '+eur(f.b):f.b==='held'?' · already held':''):
        /^not on the scored list/.test(out)?out:'not on the scored list'+(out?': '+out:''),on?'neutral':''));}
    li.appendChild(ch);
    if(B58.test(a)){var lk=el('div');lk.className='elinks';      // fixed templates around a checked address; no swap link
      lk.appendChild(link('DexScreener','https://dexscreener.com/solana/'+(typeof c.pair==='string'&&B58.test(c.pair)?c.pair:a)));
      lk.appendChild(link('RugCheck','https://rugcheck.xyz/tokens/'+a));lk.appendChild(link('Solscan','https://solscan.io/token/'+a));
      lk.appendChild(link('Birdeye','https://birdeye.so/token/'+a+'?chain=solana'));lk.appendChild(link('GMGN','https://gmgn.ai/sol/token/'+a));
      if(/pump$/.test(a))lk.appendChild(link('pump.fun','https://pump.fun/coin/'+a));
      if(typeof c.x==='string'&&XL.test(c.x))lk.appendChild(link('X',c.x));
      li.appendChild(lk);}
    li._c=c;eages(li,c,y,ref);
    return li;
  }
  function drawEarly(){
    if(!ebox)return;
    var n=now(),doc=S.doc,st=MB.early(doc,n,eT,S.fails,S.rem,S.reset,scan,own,S.got,S.moved),py=MB.young(doc);
    var es=st+'|'+(py?py.t+'|'+py.coins.length:'');if(es!==eSent){eSent=es;emit();}      // the installed app's tab badge follows what this box shows
    ebox.hidden=st==='hide';
    if(st==='hide')return;
    var y=st==='own'?(py&&+py.t===eT?py:own):py,coins=y&&Array.isArray(y.coins)?y.coins.filter(function(c){return c&&typeof c==='object';}).slice(0,20):[];
    var list=!!y&&y.state==='listed'&&['listed','partial','paused','limited','done','stopped','own'].indexOf(st)>=0,M_=60000;
    var key=(st==='own'?'own':'live')+':'+(y?y.t:doc&&doc.t);if(key!==eKey){eKey=key;ebox.open=st!=='own';}
    ebox.classList.toggle('dim',['paused','limited','stopped'].indexOf(st)>=0);
    var up=doc&&typeof doc==='object'?+(doc.updated||doc.end)||0:0,seen=y&&isn(y.at)?hhmm(y.at):'?',sc=y?+y.t:(doc?+doc.t||0:0);
    var rcw=MB.rcSum(y,coins),txt;
    if(st==='wait')txt='Scan running since '+hhmm(+doc.t)+'. The early list comes about 5 minutes after the start (about '+hhmm(+doc.t+5*M_)+').';
    else if(st==='late')txt="This hour's scan has not reported yet (it may have started late). If none started, the safety net starts one at about :40.";
    else if(st==='listed'||st==='partial'){var s=Math.max(0,Math.round(MB.age(doc,n,S.got,S.moved)/1000));
      txt='Found at '+seen+' by the scan running now, with the prices of that time · updated '+(s<120?s+' s':Math.round(s/60)+' min')+' ago'+rcw+
        (st==='partial'?' · '+(str(y.why,120).replace(/\.$/,'')||'DexScreener stopped early: some coins may be missing'):'');}
    else if(st==='paused')txt='Live view paused: no update since '+hhmm(up)+(list?'. The list is from '+seen+'; the scan may still be running.':'; the scan may still be running.');
    else if(st==='limited')txt="GitHub's hourly limit for this connection is used up; next try at "+hhmm(S.next)+'.';
    else if(st==='done')txt='The scan finished at '+hhmm(up)+'. Its scored list is being published'+(home&&location.href.indexOf(home)===0?'; the page reloads by itself and shows it below this list.':' and shows below this list on the website.');
    else if(st==='stopped'){var tr=doc.agents.filter(function(a){return a&&a.id==='trader';})[0];
      txt='The scan stopped at '+hhmm(up)+'. No scored list'+(tr&&tr.status==='done'?'':' and no paper buys')+' came from it; this is only what the launch spotter found at '+seen+'.';}
    else if(st==='own'){var nf=fin&&typeof fin==='object'&&+fin.t===+y.t&&fin.coins&&typeof fin.coins==='object'?coins.filter(function(c){var f=fin.coins[c.addr];return !(f&&isn(f.k));}).length:null;
      txt='Early list of this scan · seen '+seen+' · '+coins.length+' coin'+(coins.length===1?'':'s')+(nf!=null?' ('+nf+' not on the scored list)':'');}
    else if(st==='empty')txt='No coin under an hour old with at least '+usd(isn(y.minLiq)?y.minLiq:5000)+' of liquidity at '+seen+'. The scored list comes with the report, about '+hhmm(sc+28*M_)+'.';
    else txt='No early list this scan: '+(str(y&&y.why,120).replace(/\.$/,'')||'no reason given')+'. The scored list comes with the report, about '+hhmm(sc+28*M_)+'.';
    var stl=ebox.querySelector('[data-early-status]');if(stl.textContent!==txt)stl.textContent=txt;
    var body=ebox.querySelector('.ebody');if(body)body.style.display=list?'':'none';     // without a list the status line says it all, and nothing folds
    if(ebox.classList.contains('nolist')===list)ebox.classList.toggle('nolist',!list);
    if(eLabel){var lt=st==='own'?"Fake money · not advice. This was the list before scoring (RugCheck only; the creator's wallet was checked later). "+
      'The paper account bought from the scored list below, not from this list.':eLabel._t;if(eLabel.textContent!==lt)eLabel.textContent=lt;}
    var cl=ebox.querySelector('[data-early-list]'),ck=list?[y.t,y.at,y.rcAt,y.rcState,eorder,st,coins.length,fin?1:0].join('|'):'';
    // the server's clock now: the snapshot's time plus the local time since its "updated" was first seen (null: the page's own list)
    var ref=list&&py&&y===py&&S.got&&isn(+doc.updated)?+doc.updated+Math.max(0,n-S.got):null;
    if(ck===eCards){Array.prototype.forEach.call(cl.children,function(li){if(li._c)eages(li,li._c,y,ref);});return;}   // the ages move in place
    eCards=ck;cl.textContent='';
    if(!list)return;
    coins.sort(eorder==='score'?function(a,b){return (+a.k||99)-(+b.k||99);}:function(a,b){return (+b.born||0)-(+a.born||0)||(+a.k||99)-(+b.k||99);});
    var fate=st==='own'&&fin&&typeof fin==='object'&&+fin.t===+y.t&&fin.coins&&typeof fin.coins==='object'?fin.coins:null;
    coins.forEach(function(c,i){cl.appendChild(ecard(c,i+1,y,ref,fate));});
  }
  function draw(){
    var st=MB.state(S.doc,now(),pageT,S.fails,S.got,S.moved),on=st==='live',doc=S.doc,ags=on?doc.agents.filter(function(a){return a&&a.id;}):[],by={};
    ags.forEach(function(a){by[a.id]=a;});
    shown=st;box.hidden=st==='hide';
    all('[data-live-link]').forEach(function(e){e.hidden=on||onSite;});      // on the website itself its own address is not news
    all('[data-live-on]',box).forEach(function(e){e.hidden=!on;});off.hidden=on;
    all('[data-static-strip]').forEach(function(e){e.hidden=on;});
    if(office)mark(office,on?'on':'');
    all('[data-agent]:not([data-ext])').forEach(function(e){mark(e,on&&word(by[e.getAttribute('data-agent')]));});     // not an agent in its own job (the radar)
    all('[data-agents]').forEach(function(e){var w=e.getAttribute('data-agents').split(' ').map(function(i){return word(by[i]);});
      mark(e,on&&(['work','fail','done'].filter(function(k){return w.indexOf(k)>=0;})[0]||'wait'));});
    all('[data-word]').forEach(function(t){var v=t.closest('[data-agents]');v=v&&v.getAttribute('data-live');if(t._w==null)t._w=t.textContent;
      t.textContent=on&&v?t.getAttribute('data-word')+{work:'at work now',done:'done this run',fail:'failed this run',wait:'waiting'}[v]:t._w;});
    all('[data-live-chip]').forEach(function(c){var w=word(by[c.getAttribute('data-live-chip')]);c.hidden=!on;
      c.className='chip '+({work:'neutral',done:'good',fail:'bad'}[w]||'');c.textContent={work:'at work now',done:'done this run',fail:'failed this run',wait:'waiting'}[w];});
    all('[data-live-line]').forEach(function(p){var a=by[p.getAttribute('data-live-line')],l=last(a),t=l?'Now: '+l:'',mx=+p.getAttribute('data-live-max')||0;p.hidden=!(on&&word(a)==='work'&&l);
      p.textContent=mx&&t.length>mx?t.slice(0,mx-1).replace(/\s+$/,'')+'\u2026':t;});     // data-live-max: an agent card's one short line (page_office.py)
    if(on){
      var n=function(w){return ags.filter(function(a){return word(a)===w;}).length;},work=ags.filter(function(a){return word(a)==='work';});
      var strip=box.querySelector('[data-live-strip]'),list=box.querySelector('[data-live-now]');strip.textContent='';list.textContent='';
      [['All',ags.length],['At work',n('work')],['Done',n('done')],['Ran beside',ags.filter(function(a){return a.bg;}).length],['Failed',n('fail')],
       ['Waiting',Object.keys(names).filter(function(i){return !by[i];}).length]].forEach(function(c){
        var sp=el('span',c[0]+' ',[el('b',String(c[1]))]);if(c[0]==='Failed'&&c[1])sp.className='bad';strip.appendChild(sp);});
      (work.length?work:[null]).forEach(function(a){list.appendChild(a?el('li','',[el('b',names[a.id]||a.id),document.createTextNode(last(a)||'started')]):el('li','between two steps'));});
    }else if(st!=='hide'){
      var up=+(doc.updated||doc.end)||0,newer=(+doc.t||0)>pageT,site=!!home&&location.href.indexOf(home)===0;
      off.textContent=st==='paused'?'Live view paused: no update since '+hhmm(up)+', the scan may still be running.':
        st==='stopped'?'The last scan stopped at '+hhmm(up)+(newer?', so no new report came from it.':'.')+' The office goes live again during the next scan.':
        newer?'The last scan finished at '+hhmm(up)+(site?', the page refreshes when the new report is published.':', after this page was made: the website has its report.'):
        'The last scan finished at '+hhmm(up)+'; this page shows it. The office goes live again during the next scan.';
      var hold=false;try{hold=!!(window.MemebotApp&&typeof MemebotApp.hold==='function'&&MemebotApp.hold());}catch(e){}   // the app's Account tab or a tap at work: later
      // the new report is online about a minute after the scan's end: a reload RELOAD_AFTER after it, and again every RELOAD_GAP while this page
      // is still the old one (a slow deploy, an old copy on the way), RELOADS times at most per scan (sessionStorage "t|count|when")
      if(st==='done'&&newer&&site&&now()-up>MB.RELOAD_AFTER&&!hold){
        try{var rl=String(sessionStorage.getItem('memebot-reloaded')||'').split('|'),rn=rl[0]===String(doc.t)?Math.max(1,+rl[1]||1):0,ra=+rl[2]||0;
          if(rn<MB.RELOADS&&(!rn||now()-ra>MB.RELOAD_GAP)){sessionStorage.setItem('memebot-reloaded',doc.t+'|'+(rn+1)+'|'+now());
            window.MEMEBOT_RELOADING=Date.now();location.reload();}}catch(e){}   // the flag: the radar's poll stops (page_radar.py)
      }
    }
    tick();
  }
  function tick(){
    try{drawEarly();}catch(e){}
    var st=MB.state(S.doc,now(),pageT,S.fails,S.got,S.moved);if(st!==shown)return draw();
    if(st==='live'){var s=Math.max(0,Math.round(MB.age(S.doc,now(),S.got,S.moved)/1000));badge.textContent='LIVE · updated '+(s<120?s+' s':Math.round(s/60)+' min')+' ago';}
  }
  function poll(){
    if(busy||document.visibilityState!=='visible'||(tabs.length&&!tabs.some(function(t){return t.checked;})))return;
    if(load())draw();
    if(now()<S.next)return;
    busy=true;S.next=now()+MB.TIMEOUT+5000;save();          // claimed: the other tabs wait for this answer
    var ac=window.AbortController?new AbortController():null,tm,rem=null,reset=0;
    var cut=new Promise(function(ok,no){tm=setTimeout(function(){if(ac)ac.abort();no(0);},MB.TIMEOUT);});
    Promise.race([fetch(src,{headers:{Accept:'application/vnd.github.raw+json'},cache:'no-store',signal:ac?ac.signal:undefined}).then(function(r){
      var h=r.headers.get('X-RateLimit-Remaining');if(h!=null&&h!==''&&!isNaN(+h)){rem=+h;reset=+r.headers.get('X-RateLimit-Reset')||0;}
      if(r.status===404)return null;          // no live branch yet: no snapshot, not a failure (the polls stay on the schedule)
      if(!r.ok)throw 0;
      return r.text();
    }).then(function(t){if(t==null)return null;var j=JSON.parse(t);if(j&&typeof j.content==='string'&&j.encoding==='base64')j=decode(j.content);   // the JSON envelope, if the raw type is not honoured
      if(!j||typeof j!=='object'||!Array.isArray(j.agents))throw 0;return j;}),cut])
    .then(took,function(){S.fails=(+S.fails||0)+1;})
    .then(function(){clearTimeout(tm);if(rem!=null){S.rem=rem;S.reset=reset;}
      S.next=MB.next(S.doc,now(),scan,S.rem,S.reset,S.fails,S.got,S.moved);save();busy=false;try{draw();}catch(e){}});
  }
  // a snapshot came (either transport): got is when this "updated" was first seen here (the same snapshot again changes nothing)
  function took(d){var o=S.doc,same=!!(o&&d&&+o.t===+d.t);
    if(!(same&&+o.updated===+d.updated)||!S.got){S.moved=same&&S.got>0;S.got=now();}S.doc=d;S.fails=0;emit();}
  function emit(){try{var n=now();window.dispatchEvent(new CustomEvent('memebot-live',{detail:{via:mode,status:S.doc,current:mode==='supabase'?SB.cur:S.doc,
    state:MB.state(S.doc,n,pageT,S.fails,S.got,S.moved),early:ebox?MB.early(S.doc,n,eT,S.fails,S.rem,S.reset,scan,own,S.got,S.moved):'none',young:MB.young(S.doc)}}));}catch(e){}}
  // the live store: one GET of a row with the publishable key in the apikey header (never Authorization); rejects with the HTTP status (0: no answer)
  function sbGet(id){
    var ac=window.AbortController?new AbortController():null,tm;
    var cut=new Promise(function(ok,no){tm=setTimeout(function(){if(ac)ac.abort();no(0);},MB.SB_TIMEOUT);});
    return Promise.race([fetch(sbUrl+'/rest/v1/live?select=doc&id=eq.'+id,{headers:{apikey:sbKey,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status||0;return r.json();},function(){throw 0;}),cut]).then(function(rows){clearTimeout(tm);
      var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;return d&&typeof d==='object'&&Array.isArray(d.agents)?d:null;},function(e){clearTimeout(tm);throw typeof e==='number'?e:0;});
  }
  // the tabs of one browser share one poll of the live store and its answer through localStorage, as the GitHub poll does
  function sbLoad(){try{var s=JSON.parse(localStorage.getItem(SBKEY));if(!s||typeof s!=='object'||!(+s.at>SB.at)||typeof s.next!=='number'||Date.now()-s.at>2*MB.SB_IDLE)return false;
    SB.at=+s.at;SB.next=s.next;SB.fails=+s.fails||0;SB.nv=s.nv;SB.cur=s.cur&&typeof s.cur==='object'?s.cur:null;
    if(s.st&&typeof s.st==='object'&&s.st!==SB.st){SB.st=s.st;took(MB.merge(s.st,SB.cur));}if(SB.fails)S.fails=SB.fails;return true;}catch(e){}return false;}
  function sbSave(){SB.at=Date.now();try{localStorage.setItem(SBKEY,JSON.stringify({at:SB.at,next:SB.next,fails:SB.fails,nv:SB.nv,cur:SB.cur,st:SB.st}));}catch(e){}}
  // in a browser tab only while the New launches or Agent office tab is open (as the GitHub poll); in the installed app on any tab. The
  // row current is read only when status names a new nver (the version of current whose early list or pick changed; ver on an older
  // status): the page takes only those two from it
  function sbPoll(){
    if(SB.busy||document.visibilityState!=='visible'||(!inApp()&&tabs.length&&!tabs.some(function(t){return t.checked;})))return;
    if(sbLoad())try{draw();}catch(e){}
    if(now()<SB.next)return;
    SB.busy=true;SB.next=now()+2*MB.SB_TIMEOUT+2000;sbSave();          // claimed: the other tabs wait for this answer
    sbGet('status').then(function(st){
      var nv=st?(st.nver!=null?st.nver:st.ver):null;
      if(nv!=null&&nv!==SB.nv)return sbGet('current').then(function(c){SB.cur=c;SB.nv=nv;return st;});
      return st;
    }).then(function(st){SB.fails=0;SB.st=st;took(MB.merge(st,SB.cur));},function(code){
      SB.fails++;
      if(MB.fallback(typeof code==='number'?code:0,SB.fails)==='github'){mode='github';SB.back=now()+MB.SB_RETRY;S.fails=0;S.next=0;}   // quietly: the GitHub poll takes over
      else S.fails=SB.fails;
    }).then(function(){SB.busy=false;SB.next=MB.sbNext(now(),SB.fails,S.doc,S.got,S.moved);sbSave();try{draw();}catch(e){}});
  }
  function step(){
    if(mode==='github'&&SB.back&&now()>=SB.back&&MB.transport(sbUrl,sbKey,'')==='supabase'){mode='supabase';SB.back=0;SB.next=0;}   // the live store again
    if(mode==='supabase')sbPoll();else poll();
  }
  window.addEventListener('storage',function(e){if(mode==='github'&&e.key===KEY&&load()||mode==='supabase'&&e.key===SBKEY&&sbLoad())try{draw();}catch(x){}});
  setInterval(function(){step();try{tick();}catch(e){}},1000);
  document.addEventListener('visibilitychange',step);
  if(mode!=='supabase')load();
  draw();step();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
})();
"""


def tile(label, value, sub="", lead=False, delta=None):
    d = ""
    if delta is not None:
        d = '<span class="delta %s">%s%s</span>' % ("good" if delta > 0 else ("bad" if delta < 0 else ""), fmt_amt(delta, True), " since start" if lead else "")
    return '<div class="tile%s"><div class="label">%s</div><div class="value">%s%s</div>%s</div>' % (" lead" if lead else "", E(label), E(value), d, ('<div class="sub">%s</div>' % E(sub)) if sub else "")


def app_tab(html_, tab):
    """html_ (one section, fold or box) marked for the installed app's tab bar (app.py PAGE_JS): the app shows it on that tab only; a browser
    ignores the mark."""
    return re.sub(r"^<(section|details|div)\b", r'<\1 data-app="%s"' % tab, html_, count=1) if html_ else html_


def fold(title, summary, inner, open_=False):
    """A section that opens on tap: the summary row carries the heading and the one-line answer, the content sits below."""
    return '<details class="fold"%s><summary><span class="t">%s</span>%s</summary>%s</details>' % (
        " open" if open_ else "", E(title), ('<span class="sum">%s</span>' % E(summary)) if summary else "", inner)


def info_i(inner, label="More about this"):
    """An ⓘ that opens a short explanation: the page's sentences sit behind it, so a tab's first view is numbers, labels and colour.
    inner is HTML (escaped by the caller)."""
    return '<details class="hi"><summary aria-label="%s" title="%s">ⓘ</summary><div class="hi-b">%s</div></details>' % (E(label), E(label), inner)


def section(h2, sub, body, info=False, more=""):
    """A section with its heading. info: the sub line (and more, HTML) sit behind an ⓘ beside the heading instead of under it."""
    if info and (sub or more):
        return '<section><div class="sec-head hasi"><h2>%s</h2>%s</div>%s</section>' % (
            h2, info_i(('<p>%s</p>' % E(sub) if sub else "") + more, "About: " + re.sub(r"<[^>]*>", "", html.unescape(h2))), body)
    return '<section><div class="sec-head"><h2>%s</h2>%s</div>%s</section>' % (h2, ('<p>%s</p>' % E(sub)) if sub else "", body)


def coin_links(a, pair=None, x=None):
    """(label, url) for the chart, safety and trading sites that take a Solana mint address in the URL."""
    a = str(a or "")
    out = [("DexScreener", "https://dexscreener.com/solana/%s" % (pair or a)), ("RugCheck", "https://rugcheck.xyz/tokens/%s" % a),
           ("Jupiter", "https://jup.ag/swap/SOL-%s" % a), ("GMGN", "https://gmgn.ai/sol/token/%s" % a),
           ("Birdeye", "https://birdeye.so/token/%s?chain=solana" % a), ("Solscan", "https://solscan.io/token/%s" % a)]
    if a.endswith("pump"):
        out.append(("pump.fun", "https://pump.fun/coin/%s" % a))
    if str(x or "").startswith("https://"):
        out.append(("X / Twitter", str(x)))
    return out


def links(p):
    return '<div class="links">%s</div>' % "".join('<a href="%s" target="_blank" rel="noopener">%s</a>' % (E(u), E(n)) for n, u in coin_links(p.get("addr"), p.get("pair"), p.get("x")))


def safety_box(text, ok=None):
    """The RugCheck sentence as a labelled box; the source name moves into the label so the sentence starts with the facts."""
    s = str(text or "").strip()
    src = "RugCheck" if s.startswith("RugCheck") else ""
    for pre in ("RugCheck: ", "RugCheck "):
        s = s[len(pre):] if s.startswith(pre) else s
    return '<p class="safety%s" data-src="%s">%s</p>' % (" flag" if ok is False else "", src, E(s or "no safety report"))


def safety_chip(ok, text=""):
    """The one-word answer to 'is it safe?': words, not colour (green/red are kept for money won/lost)."""
    if ok is None:
        return '<span class="chip">no safety report</span>'
    if ok:
        return '<span class="chip">safety: clean</span>'
    return '<span class="chip warn">%s</span>' % E("flagged: " + str(text or "").replace("RugCheck", "").strip(": ") if text else "safety flags")


def sources_row(src):
    chips = "".join('<span class="chip">%s</span>' % E(LIST_NAMES[t.split(":", 1)[-1]] if t.startswith("list:") and t.split(":", 1)[-1] in LIST_NAMES else SRC.get(t.split(":", 1)[0], "%s") % t.split(":", 1)[-1]) for t in (src or [])[:4])
    return ('<div class="row"><span class="k">Seen on</span>%s</div>' % chips) if chips else ""


def name_html(sym, name):
    return ('<span class="name">%s</span>' % E(name)) if name and str(name) != str(sym) else ""


def position_card(r, now):
    p = r["p"]
    sc = M.num(p.get("score"))
    if r["half"]:
        sells = "the rest if it falls back to %s" % fmt_px(r["entry"])
    else:
        sells = "half at %s (2x) · all at %s (−50%%)" % (fmt_px(2 * r["entry"]) if r["entry"] else "–", fmt_px(0.5 * r["entry"]) if r["entry"] else "–")
    deadline = fmt_dt((M.num(p.get("t")) or 0) + (M.num(p.get("maxd")) or M.MAX_DAYS) * M.DAY, True)
    kv = [("bought", fmt_dt(p.get("t"), True)), ("entry", fmt_px(r["entry"])), ("last", fmt_px(r["last"])), ("multiple", fmt_mult(r["mult"])),
          ("sells", sells), ("time limit", deadline),
          ("paid", fmt_amt(r["ticket"])), ("worth now", fmt_amt(r["value"]) if r["value"] is not None else "no price yet"), ("still held", pct(100 * p["_left"])),
          ("sold so far", fmt_amt(r["back"])), ("score", ("%.0f" % sc if sc is not None else "–") + " · rank %s" % (p.get("rank") or "?")),
          ("cap at buy", fmt_money(p.get("mc"))), ("liquidity at buy", fmt_money(p.get("liq"))), ("liquidity now", fmt_money(r["liq_now"]) if r["liq_now"] is not None else "–"),
          ("held", fmt_age(p.get("t"), now))]
    pnl = r["pnl"]
    pnl_html = ('<span class="delta %s">%s</span>' % ("good" if pnl > 0 else ("bad" if pnl < 0 else ""), fmt_amt(pnl, True))) if pnl is not None else ""
    why = (p.get("why") or "").split("; RugCheck")[0]
    return ('<article class="card"><div class="top"><div><span class="sym">%s</span>%s</div><div class="chips">%s<span class="chip %s">%s</span></div></div>'
            '<div class="kv">%s</div>%s%s%s<div class="addr">%s</div></article>') % (
        E(p.get("sym")), name_html(p.get("sym"), p.get("name")), pnl_html, r["kind"], E(r["status"]),
        "".join('<div%s><div class="k">%s</div><div class="v%s">%s</div></div>' % (' class="span"' if k == "sells" else "", E(k), " multi" if k == "sells" else "", E(v)) for k, v in kv),
        safety_box(p.get("safety")), ('<details class="more"><summary>Why the bot bought it</summary><p class="why">%s</p></details>' % E(why)) if why else "",
        links(p), E(p.get("addr")))


# ---------------------------------------------------------------- the safety checklist and the held-coin card
CHECK_ICON = {"ok": "✓", "warn": "!", "bad": "✕", "note": "i", "unknown": "?"}
CHECK_WORD = {"ok": "passed", "warn": "passed only the relaxed floor", "bad": "failed", "note": "note", "unknown": "unknown"}


def pct1(v):
    """3.5% under 10, 24% above: small holder shares keep their decimal."""
    v = M.num(v)
    if v is None:
        return "–"
    return ("%.1f%%" % v) if 0 < v < 10 and abs(v - round(v)) >= 0.05 else "%d%%" % round(v)


def fmt_dur(h):
    """35 min, 5h 20m."""
    m = int(round(max(0.0, h) * 60))
    return ("%d min" % m) if m < 60 else "%dh %02dm" % divmod(m, 60)


def _judge(v, at_most=None, at_most_loose=None, at_least=None, at_least_loose=None):
    """ok within the profile's limit, warn within the relaxed floor's only, bad outside both, unknown without a value."""
    if v is None:
        return "unknown"
    if at_most is not None:
        return "ok" if v <= at_most else ("warn" if at_most_loose is not None and v <= at_most_loose else "bad")
    return "ok" if v >= at_least else ("warn" if at_least_loose is not None and v >= at_least_loose else "bad")


def safety_checks(rk):
    """A stored safety report (risk_doc) -> [(state, check, value, limit)]: every check the bot runs before it names a coin, judged
    against the active profile's limits (ok), the relaxed floor of the risky tier only (warn) or neither (bad). 'note' is worth
    knowing but blocks nothing. [] when there is no report."""
    rk = rk if isinstance(rk, dict) else {}
    if M.num(rk.get("lpLocked")) is None and "danger" not in rk:
        return []
    dv, gp, hl, L = rk.get("dev") or {}, rk.get("gp") or {}, rk.get("hl") or {}, M.LOOSE_FLOOR
    high = lambda *vs: max([M.num(v) for v in vs if M.num(v) is not None], default=None)
    out = []
    lp = M.num(rk.get("lpLocked"))
    out.append((_judge(lp, at_least=M.MIN_LP_LOCKED, at_least_loose=L["MIN_LP_LOCKED"]), "liquidity locked", pct(lp) if lp is not None else "unknown", "at least %s" % pct(M.MIN_LP_LOCKED)))
    top1 = high(rk.get("top1"), hl.get("top1Pct"))
    out.append((_judge(top1, at_most=M.MAX_TOP1, at_most_loose=L["MAX_TOP1"]), "biggest wallet", pct1(top1) if top1 is not None else "unknown", "at most %s" % pct(M.MAX_TOP1)))
    top10 = high(rk.get("top10"), hl.get("top10Pct"))
    out.append((_judge(top10, at_most=M.MAX_TOP10, at_most_loose=L["MAX_TOP10"]), "top 10 wallets", pct1(top10) if top10 is not None else "unknown", "at most %s" % pct(M.MAX_TOP10)))
    holders = M.num(rk.get("holdersN")) or M.num(dv.get("jupHolders"))
    out.append((_judge(holders, at_least=M.MIN_HOLDERS, at_least_loose=L["MIN_HOLDERS"]), "holders", fmt_int(holders) if holders else "unknown", "at least %s" % fmt_int(M.MIN_HOLDERS)))
    ins = M.num(rk.get("insiders"))
    out.append((_judge(ins, at_most=M.MAX_INSIDERS, at_most_loose=L["MAX_INSIDERS"]), "insider wallets", fmt_int(ins) if ins is not None else "unknown", "at most %d" % M.MAX_INSIDERS))
    creator = M.num(rk.get("creatorPct")) if M.num(rk.get("creatorPct")) is not None else M.num(dv.get("devPct"))
    lim_c = ("at most %s, no sale in 3h" % pct(M.MAX_CREATOR_PCT)) if M.MAX_CREATOR_PCT < 100 else "no sale in 3h"
    if M.truthy(dv.get("devSold")):
        age = M.num(dv.get("devSellAgeMin"))
        out.append(("bad", "creator holds", ("sold %d min ago" % age) if age is not None else "sold in the last 3h", lim_c))
    elif creator is None:
        out.append(("unknown", "creator holds", "unknown", lim_c))
    else:
        out.append(("ok" if creator <= M.MAX_CREATOR_PCT else "warn", "creator holds", pct1(creator), lim_c))
    auth = [n for k, n in (("mintable", "supply can be minted"), ("freezable", "accounts can be frozen"), ("closable", "accounts can be closed"),
                           ("balMutable", "balances can be rewritten"), ("nonTransferable", "cannot be transferred")) if M.truthy(gp.get(k))]
    if (M.num(gp.get("transferFee")) or 0) > 0:
        auth.append("transfer fee %s%%" % gp.get("transferFee"))
    if dv.get("mintAuthOff") is not None and not M.truthy(dv.get("mintAuthOff")):
        auth.insert(0, "mint authority active")
    freeze_on = dv.get("freezeAuthOff") is not None and not M.truthy(dv.get("freezeAuthOff")) and not M.truthy(gp.get("freezable"))
    if auth:
        out.append(("bad", "mint/freeze authority", ", ".join(auth[:2]), "both given up"))
    elif freeze_on:
        out.append(("warn", "mint/freeze authority", "freeze still active", "both given up"))
    elif dv.get("mintAuthOff") is None and not gp:
        out.append(("unknown", "mint/freeze authority", "unknown", "both given up"))
    else:
        out.append(("ok", "mint/freeze authority", "given up", "both given up"))
    danger = [x for x in M.names(rk, "danger") if not M.OWNERSHIP_FLAG.search(x)]
    out.append(("bad" if danger else "ok", "danger flags", ", ".join(danger[:3]) or "none", "RugCheck: none"))
    warn = M.names(rk, "warn")
    block = [x for x in warn if M.RISK_WARN_BLOCK.search(x)]
    rest = [x for x in warn if x not in block]
    out.append(("warn" if block else ("note" if rest else "ok"), "warnings", ", ".join((block + rest)[:3]) or "none",
                "RugCheck: no holder, creator or rug warning" if block or not rest else "RugCheck: these block nothing"))
    if rk.get("mutable") is not None:
        mut = M.truthy(rk.get("mutable"))
        out.append(("note" if mut else "ok", "metadata", "can still be changed" if mut else "locked", "not a gate"))
    return out


def checklist(rk, title="Safety check"):
    """The safety report as a checklist, one row per check with its value and its limit."""
    rows = safety_checks(rk)
    if not rows:
        return ""
    n = lambda s: sum(1 for r in rows if r[0] == s)
    bits = ["%d of %d passed" % (n("ok"), len(rows))] + [txt % n(s) for s, txt in (("warn", "%d only within the relaxed floor"), ("bad", "%d failed"), ("unknown", "%d unknown")) if n(s)]
    items = "".join('<li class="ck %s"><span class="ic" aria-hidden="true">%s</span><span class="sr">%s: </span><span class="lb">%s<small>%s</small></span><span class="vl">%s</span></li>' % (
        s, CHECK_ICON[s], CHECK_WORD[s], E(what), E(lim), E(val)) for s, what, val, lim in rows)
    return ('<div class="checks"><div class="checks-head"><span class="t">%s</span><span class="sum">%s</span></div><ul>%s</ul>'
            '<p class="ck-leg">✓ within the %s profile\'s limit · ! only within the relaxed floor · ✕ fails · i worth knowing · RugCheck, Jupiter and GoPlus at the scan</p></div>') % (
        E(title), E(" · ".join(bits)), items, E(M.HORIZON))


def checks_summary(rk):
    rows = safety_checks(rk)
    if not rows:
        return ""
    worst = next((r for s in ("bad", "warn") for r in rows if r[0] == s), None)
    return "%d of %d passed" % (sum(1 for r in rows if r[0] == "ok"), len(rows)) + ((" · %s: %s" % (worst[1], worst[2].split(", ")[0])) if worst else "")


def track_bar(mc, m, be, k=1.0, floor=None, trail=None):
    """Where the price stands on the paper rule's fixed log scale: from the stop (0.7 times the candle entry price, the left end) to
    the take-profit (11 times it, the right end), the levels a sale is decided on. mc: the price now ÷ the candle entry price (cpx; the
    entry price itself while the pool has no candles), the dot; m: the price now ÷ the entry price, its label; be: break-even after
    both fees ÷ the entry price; k: cpx ÷ the entry price, which places the entry and break-even ticks. The end labels always name
    the rule's levels; break-even keeps a few pixels from the entry tick so it stays visible; the entry label shows only on a bar
    wide enough to keep it clear of the stop label (CSS container query). floor: the stop's multiple of cpx (the chart exit's -50 %; the
    fixed rule's 0.7 without it); trail: the chart exit's armed trailing stop over cpx, a tick of its own."""
    floor = floor or 1.0 - M.HOLD_STOP
    lo, hi = math.log(floor), math.log(1.0 + M.HOLD_TP)
    P = lambda v: max(0.0, min(100.0, (math.log(max(v, 1e-9)) - lo) / (hi - lo) * 100))
    k = k or 1.0
    x_in, x_be = P(1.0 / k), P(be / k)
    cls = "good" if m is not None and m >= be else ("warn" if m is not None and m >= 1.0 else "bad")
    chg = lambda v: sgn("%+.1f%%" % (100 * (v - 1)))
    stop_t, tp_t = sgn("-%d%%" % round(100 * (1.0 - floor))), "+%d%%" % round(100 * M.HOLD_TP)
    out = ['<div class="rail"></div>']
    if trail and trail > floor:
        out.append('<span class="tk st" style="left:%.1f%%" title="trailing stop"></span>' % P(trail))
    if mc is not None:
        a, b = sorted((x_in, P(mc)))
        out.append('<div class="fill %s" style="left:%.1f%%;width:%.1f%%"></div>' % (cls, a, max(b - a, 0.8)))
    out.append('<span class="tk st" style="left:0%%"></span><span class="tk" style="left:%.1f%%"></span><span class="tk be" style="left:max(%.1f%%, calc(%.1f%% + 5px))"></span>'
               '<span class="tk tp" style="left:100%%"></span>' % (x_in, x_be, x_in))
    if mc is not None and m is not None:
        x = P(mc)
        out.append('<span class="dot %s" style="left:%.1f%%"></span><span class="now %s%s" style="left:%.1f%%">%s</span>' % (cls, x, cls, " l" if x < 10 else (" r" if x > 90 else ""), x, chg(m)))
    out.append('<span class="tl start" style="left:0%%">stop %s</span><span class="tl at" style="left:max(%.1f%%, %dpx)">entry · break-even %s</span><span class="tl end" style="left:100%%">sells %s</span>' % (
        stop_t, x_in, TRACK_AT_MIN_PX, chg(be), tp_t))
    aria = "price %s since the entry, on a scale from the stop at %s to the take-profit at %s; break-even after fees at %s" % (
        chg(m) if m is not None else "unknown", stop_t, tp_t, chg(be))
    return '<div class="track" role="img" aria-label="%s">%s</div>' % (E(aria), "".join(out))


def time_bar(t_start, now, end=None):
    """The 6-hour clock; end: the live limit (memebot.hold_end, from LIVE_SELL_AT on), when it sells at that minute."""
    held = max(0.0, (now - t_start) / 3_600_000)
    return ('<div class="clock"><div class="bar"><span style="width:%.1f%%"></span></div><div class="cap"><span>held %s of %dh</span><span>%s %s</span></div></div>' % (
        100 * min(1.0, held / M.HOLD_MAX_H), fmt_dur(held), round(M.HOLD_MAX_H), "sold at" if end else "sold at the first scan after about",
        fmt_dt(end or t_start + M.HOLD_MAX_H * 3_600_000, True)))


def spark(cands, ref, tp_px, w=320, h=64):
    """The price since the entry from the pool's minute candles (closes): entry dashed, the take-profit dotted when it is in view."""
    pts = [(c[0], c[4]) for c in cands if c[4] > 0]
    if len(pts) < 3 or not ref:
        return ""
    k = int(math.ceil(len(pts) / 160.0))
    pts = pts[::k] + ([pts[-1]] if (len(pts) - 1) % k else [])
    vals = [v for _, v in pts]
    lo, hi = min(vals + [ref]), max(vals + [ref])
    show_tp = bool(tp_px) and tp_px <= hi * 1.08
    if show_tp:
        hi = max(hi, tp_px)
    pad = (hi - lo) * 0.1 or ref * 0.02
    lo, hi = lo - pad, hi + pad
    t0, t1 = pts[0][0], max(pts[-1][0], pts[0][0] + 1)
    X = lambda t: (t - t0) / (t1 - t0) * w
    Y = lambda v: (hi - v) / (hi - lo) * h
    line = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", X(t), Y(v)) for i, (t, v) in enumerate(pts))
    svg = ['<svg class="spark-svg" viewBox="0 0 %d %d" preserveAspectRatio="none" aria-hidden="true">' % (w, h),
           '<path class="area" d="%s L%.1f %d L0 %d Z"/>' % (line, X(pts[-1][0]), h, h),
           '<line class="ref" x1="0" x2="%d" y1="%.1f" y2="%.1f"/>' % (w, Y(ref), Y(ref))]
    if show_tp:
        svg.append('<line class="tpl" x1="0" x2="%d" y1="%.1f" y2="%.1f"/>' % (w, Y(tp_px), Y(tp_px)))
    svg.append('<path class="line" d="%s"/></svg>' % line)
    top = max(pts, key=lambda p: p[1])
    last = pts[-1][1]
    pctY = lambda v: max(0.0, min(100.0, 100.0 * Y(v) / h))
    tags = '<span class="sl" style="top:%.1f%%">entry</span><span class="sl end" style="top:%.1f%%">%s</span>' % (pctY(ref), pctY(last), sgn("%+.1f%%" % (100 * (last / ref - 1))))
    if show_tp:
        tags += '<span class="sl tp" style="top:%.1f%%">sells</span>' % pctY(tp_px)
    cap = "price since the entry, one point per minute · highest %s at %s · %s to %s" % (
        sgn("%+.1f%%" % (100 * (top[1] / ref - 1))), fmt_dt(top[0], True)[-5:], fmt_dt(pts[0][0], True)[-5:], fmt_dt(pts[-1][0], True)[-5:])
    return '<figure class="spark"><div class="spark-box">%s%s</div><figcaption>%s</figcaption></figure>' % ("".join(svg), tags, E(cap))


# the reasons memebot stored with a position were written before the page's word rules: "66% of trades were buys", "biggest buyer 23% of the
# buying" read as purchases on the page (memebot's text itself stays as it is stored)
WHY_WORDS = ((re.compile(r"\btrades were buys\b"), "trades were purchases"), (re.compile(r"\bof the buying\b"), "of the purchases"),
             (re.compile(r"\bbuys\b"), "purchases"), (re.compile(r"\bbuying\b"), "purchasing"), (re.compile(r"\bbuy\b"), "purchase"))


def why_words(t):
    """A stored reason in the page's words (WHY_WORDS)."""
    for rx, w in WHY_WORDS:
        t = rx.sub(w, t)
    return t


def hold_card(r, now):
    """A paper position as one row that opens on tap. The row: the coin and its group (top pick · 50 €, new launch · 3 €), what it
    would bring if sold now against what it cost, the price on a log scale between the stop, the entry, break-even and the
    take-profit, and the clock. Opened: the price since the entry, the facts of the buy, the safety check it was bought on, why, the links."""
    p = r["p"]
    entry, ticket, mult, pnl = r["entry"], r["ticket"], r["mult"], r["pnl"]
    t0 = M.num(p.get("t")) or now                         # the time limit counts from the scan that bought it (memebot.py)
    t_buy = M.num(p.get("entryAt")) or t0
    ref = r.get("cpx") or entry                           # the take-profit and the stop are measured on the candles' own entry price
    chart = M.is_chart(p)                                 # the chart exit (since Oct 24): its floor, and its trail once armed
    floor = 1.0 - (M.CHART_STOP if chart else M.HOLD_STOP)
    hc = M.chart_hit(r.get("candles") or [], t_buy, None, ref) if chart and ref else {}
    trail = hc.get("lvl") if hc.get("hi") and hc["hi"] >= M.CHART_ARM else None
    tp_px = (1 + M.HOLD_TP) * ref if ref else None
    stop_px = floor * ref if ref else None
    k = ref / entry if ref and entry else 1.0
    be = be_mult(ticket, M.pos_fee(p)) or 1.0
    cls = "good" if (pnl or 0) > 0 else ("bad" if (pnl or 0) < 0 else "")
    held_h = max(0.0, (now - t0) / 3_600_000)
    meta = ("price %s since the entry" % fmt_chg(mult) if mult is not None else "no price yet") + " · held %s of %dh" % (fmt_dur(held_h), round(M.HOLD_MAX_H))
    live = now >= M.live_sell_at()           # memebot.LIVE_SELL_AT: the live chart decides, every minute
    leg = ('<div class="tleg"><span>entry %s</span><span>now %s</span><span title="the price change at which this ticket comes back whole after the buy and the sell fee">'
           'break-even %s</span><span>%s %s or lower</span>%s<span>%s %s, booked at %s</span></div>') % (
        fmt_px(entry), fmt_px(r["last"]) if r["last"] else "no price yet", sgn("%+.1f%%" % (100 * (be - 1))),
        "stop as soon as a minute's low touches" if live else "stop when a minute candle closes at", fmt_px(stop_px),
        ("<span>%s</span>" % E(("trailing stop at %s (%d%% under the high so far)" % (fmt_px(trail * ref), round(100 * M.CHART_TRAIL))) if trail else (
            "trailing stop from %s on (%d%% under the high), out on a fall of %d%% within %d min" % (
                fmt_px(M.CHART_ARM * ref), round(100 * M.CHART_TRAIL), round(100 * M.CHART_DROP), M.CHART_DROP_MIN)))) if chart and ref else "",
        "sells as soon as a minute's high touches" if live else "sells when a minute candle closes at", fmt_px(tp_px),
        fmt_px((1 + M.HOLD_TP) * entry) if entry else "–")
    worth = ("worth %s if sold now, paid %s, after both fees" % (fmt_amt(r["value"]), fmt_eur(ticket))) if r["value"] is not None else "no price since the buy · paid %s" % fmt_eur(ticket)
    kv = [("bought", fmt_dt(t_buy, True)), ("paid", fmt_eur(ticket)),
          ("score when bought", "%.0f · %s" % (M.num(p.get("score")) or 0, ("%d min old" % M.num(p["ageMin"])) if M.num(p.get("ageMin")) is not None else "rank #%s" % (p.get("rank") or "?"))),
          ("market cap when bought", fmt_money(p.get("mc"))), ("24h volume when bought", fmt_money(p.get("vol"))),
          ("liquidity", "%s → %s" % (fmt_money(p.get("liq")), fmt_money(r["liq_now"])) if r["liq_now"] is not None else fmt_money(p.get("liq")))]
    why = why_words((p.get("why") or "").split("; RugCheck")[0])
    rk = p.get("risk") if isinstance(p.get("risk"), dict) else None
    safety = ('<details class="more"><summary>Safety check when bought · %s</summary>%s</details>' % (E(checks_summary(rk)), checklist(rk, "Safety check when bought"))) if safety_checks(rk) else safety_box(p.get("safety"))
    return ('<details class="card pos hold"><summary><span class="who"><span class="sym">%s</span>%s <span class="chip">%s</span></span><span class="plv %s">%s</span>'
            '<span class="meta">%s</span>%s</summary><div class="body"><p class="worth">%s</p>%s%s%s<div class="kv">%s</div>%s%s%s<div class="addr">%s</div></div></details>') % (
        E(p.get("sym")), name_html(p.get("sym"), p.get("name")), E(group_tag(p)), cls, fmt_amt(pnl, True) if pnl is not None else "–", E(meta),
        track_bar(r["last"] / ref if r["last"] and ref else None, mult, be, k, floor, trail),
        E(worth), leg, time_bar(t0, now, M.hold_end(t_buy)), spark(r.get("candles") or [], ref, tp_px), kv_html(kv),
        safety, ('<details class="more"><summary>Why the bot bought it</summary><p class="why">%s</p></details>' % E(why)) if why else "",
        links(p), E(p.get("addr")))


def tier_chip(c):
    """strong / weak / fallback: how much the recommendation is worth, in one chip."""
    t = c.get("tier") or "strong"
    if t == "weak":
        return '<span class="chip warn" title="clean, but the score is under the bar: the best that was available">weak · best available</span>'
    if t == "fallback":
        relaxed = "; ".join(str(x) for x in (c.get("relaxed") or []))
        return '<span class="chip warn" title="%s">fallback · momentum rules relaxed</span>' % E(relaxed or "no clean coin passed every gate")
    if t == "risky":
        return '<span class="chip warn" title="no coin had a clean safety report this scan: this is the tradable coin with the best trained odds, shown with its flag and its odds">risky · nothing clean, best odds</span>'
    if t == "watch":
        return '<span class="chip bad" title="shown because the page always names the safest-looking coin: the zero model puts it over the limit, so it is not a pick">watch only · zero risk over the limit</span>'
    if t == "young":
        return '<span class="chip" title="under an hour old: shown on the new-launches tab, never picked (the profile wants coins at least %g hours old)">new launch · not a pick</span>' % M.GATE_MIN_AGE_H
    return '<span class="chip neutral">strong pick</span>'


def odds_warn(c):
    """The low-odds chip: the coin is named, the page says what the record gives it."""
    up = M.num(c.get("upP"))
    if c.get("lowOdds") and up is not None:
        return '<span class="chip warn" title="trained on the bot\'s own scored scans: fewer than %d%% of coins like this ended the window in profit after fees">low odds · %s profit chance</span>' % (round(100 * M.MIN_UP_P), pct(100 * up))
    return ""


def yes_no(v, yes="yes", no="no"):
    return "–" if v is None else (yes if v else no)


def same_odds(c, peers):
    """How many candidates of the scan share this coin's rounded odds, when all of them do (the model does not tell them apart), else 0."""
    key = lambda x: (round(100 * M.num(x.get("upP"))), round(100 * (M.num(x.get("zeroP")) or 0)))
    ps = [x for x in (peers or []) if isinstance(x, dict) and M.num(x.get("upP")) is not None]
    return len(ps) if M.num(c.get("upP")) is not None and len(ps) >= 3 and all(key(x) == key(c) for x in ps) else 0


# the "all numbers" groups of a card: the safety rows and the story rows by label, everything else is trading
SAFETY_KV = {"holders", "biggest wallet", "top 10 wallets", "insider wallets", "liquidity locked", "creator holds", "creator sold in 3h", "mint authority",
             "metadata changeable", "RugCheck score", "top 10 wallets (chain)", "GoPlus authorities", "GoPlus trusted", "LP burned (GoPlus)", "top 10 wallets (GoPlus)",
             "launchpad", "DEX paid"}
STORY_KV = {"source lists", "keyword hits", "community votes (RugCheck)", "CoinGecko watchlists", "X followers", "Telegram members", "StockTwits watchers",
            "X/social 24h (LunarCrush)", "the story: source tweet", "tweet text", "theme"}
STRIP_KV = {"age", "price", "market cap", "liquidity", "24h volume", "6h change"}       # on the card's stats strip already


def kv_html(kv):
    return "".join(('<div class="span"><div class="k">%s</div><div class="v multi">%s</div></div>' if len(str(v)) > 22 else '<div><div class="k">%s</div><div class="v">%s</div></div>') % (E(k), E(v)) for k, v in kv)


def paper_line(c, held=None):
    """The pick's paper position in one line: "Bought on paper: 50 € at 17:21 · now +4.2%" (this scan bought it; now from the position's
    profit or loss over its ticket, "no price yet" without one), "Already held since Oct 15, 16:21 · now −3.1%", "Not bought: <reason>";
    None when the scan says nothing. held: {address: paper row}, the open row of the coin, else its newest sold one."""
    b = c.get("bought")
    hr = (held or {}).get(c.get("addr"))
    t_in = (M.num(hr["p"].get("entryAt")) or M.num(hr["p"].get("t"))) if hr else None
    if hr and hr.get("pnl") is not None and hr.get("ticket"):
        now_ = ("sold, " if hr.get("closed") else "now ") + sgn("%+.1f%%" % (100.0 * hr["pnl"] / hr["ticket"]))
    else:
        now_ = "no price yet"
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        return "Bought on paper: %s%s · %s" % (fmt_eur(b), (" at " + local(t_in).strftime("%H:%M")) if t_in else "", now_)
    if b == "held":
        return ("Already held since %s · %s" % (local(t_in).strftime("%b %d, %H:%M"), now_)) if t_in else "Already held from an earlier scan"
    if b:
        return "Not bought: %s" % b
    return None


def rec_card(c, now, embed, peers=None, held=None):
    """A recommended coin, top to bottom: who it is and how much the pick is worth (the tier chip, safety, story), its market in one strip,
    for a risky or fallback pick one amber line, the paper position in one line, the safety check, then on tap: why the bot picked it, every
    number behind the pick (first the score and the trained odds, which are about the same for every coin right now), the live chart; the
    links (they wrap). held: {address: paper row} for the paper line."""
    f, rk = c.get("f") or {}, c.get("risk") or {}
    dv = rk.get("dev") or {}
    g = lambda k: M.num(f.get(k))
    hz = horizon_text()
    up, zp = M.num(c.get("upP")), M.num(c.get("zeroP"))
    paper = paper_line(c, held)
    verdicts = [("Score", "%.0f" % (M.num(c.get("score")) or 0), "of 100 · rank #%s" % (c.get("rank") or "?")),
                ("Chance of a profit", pct(100 * up) if up is not None else "–", ("within %s, after fees" % hz) if up is not None else "no trained model yet"),
                ("Chance of going to zero", pct(100 * zp) if zp is not None else "–", ("within %s" % hz) if zp is not None else "no trained model yet")]
    low = {"Chance of a profit"} if c.get("lowOdds") else set()
    verdict_html = '<div class="verdicts">%s</div>' % "".join('<div%s><span class="k">%s</span><span class="v">%s</span><span class="s">%s</span></div>' % (
        ' class="low" title="fewer than %d%% of coins like this ended the window in profit after fees"' % round(100 * M.MIN_UP_P) if k in low else "", E(k), E(v), E(sub)) for k, v, sub in verdicts)
    odds_note = '<p class="odds-note">The model gives almost every coin the same odds right now, so the score ranks them.</p>' if same_odds(c, peers) else ""
    age = fmt_age(now - (g("ageH") or 0) * 3_600_000, now) if g("ageH") is not None else "–"
    chg = lambda k: sgn("%+.0f%%" % g(k)) if g(k) is not None else "–"
    stats = [("price", fmt_px(c.get("px"))), ("market cap", fmt_money(c.get("mc"))), ("liquidity", fmt_money(c.get("liq"))), ("24h volume", fmt_money(c.get("vol"))),
             ("age", age), ("6h change", chg("c6"))]
    stats_html = '<div class="stats">%s</div>' % "".join('<div><span class="k">%s</span><span class="v">%s</span></div>' % (E(k), E(v)) for k, v in stats)
    holders = M.num(rk.get("holdersN")) or g("rc.holders") or M.num(dv.get("jupHolders"))
    creator = M.num(rk.get("creatorPct")) if M.num(rk.get("creatorPct")) is not None else M.num(dv.get("devPct"))
    sold = dv.get("devSold")
    kv = [("age", age), ("price", fmt_px(c.get("px"))), ("market cap", fmt_money(c.get("mc"))), ("liquidity", fmt_money(c.get("liq"))),
          ("liquidity ÷ cap", pct(100 * g("liqMc")) if g("liqMc") is not None else "–"), ("24h volume", fmt_money(c.get("vol"))),
          ("last hour's share of 24h volume", pct(100 * g("vol1Share")) if g("vol1Share") is not None else "–"),
          ("share of buys", pct(100 * g("buyShare")) if g("buyShare") is not None else "–"),
          ("buys ÷ sells, last hour", ("%.2fx" % g("buyRatio1h")) if g("buyRatio1h") is not None else "–"),
          ("1h change", chg("c1")), ("6h change", chg("c6")), ("24h change", chg("c24")),
          ("holders", fmt_int(holders) if holders else "–"), ("biggest wallet", pct1(rk.get("top1")) if M.num(rk.get("top1")) is not None else "–"),
          ("top 10 wallets", pct(rk.get("top10")) if M.num(rk.get("top10")) is not None else (pct(g("rc.top10")) if g("rc.top10") is not None else "–")),
          ("insider wallets", ("%d" % M.num(rk.get("insiders"))) if M.num(rk.get("insiders")) is not None else "–"),
          ("liquidity locked", pct(rk.get("lpLocked")) if M.num(rk.get("lpLocked")) is not None else "–"),
          ("creator holds", pct(creator) if creator is not None else "–"),
          ("creator sold in 3h", "–" if not dv else (("yes, %d min ago" % M.num(dv.get("devSellAgeMin"))) if sold and M.num(dv.get("devSellAgeMin")) is not None else yes_no(sold))),
          ("mint authority", "–" if dv.get("mintAuthOff") is None else ("given up" if dv.get("mintAuthOff") else "still active")),
          ("metadata changeable", yes_no(rk.get("mutable"))), ("RugCheck score", ("%d" % M.num(rk.get("score"))) if M.num(rk.get("score")) is not None else "–"),
          ("source lists", ("%d" % g("srcN")) if g("srcN") else "–"), ("keyword hits", ("%d" % g("kwN")) if g("kwN") else "0"),
          ("paid boosts", ("%d" % g("boosts")) if g("boosts") else "none"),
          ("buyers / sellers 24h", ("%d / %d" % (g("gt.buyers24"), g("gt.sellers24"))) if g("gt.buyers24") is not None and g("gt.sellers24") is not None else "–"),
          ("net new buyers, last hour", ("%+d" % g("jup.netBuyers1")) if g("jup.netBuyers1") is not None else "–"),
          ("holder change 24h", (sgn("%+.0f%%" % (100 * g("jup.holderChg24")))) if g("jup.holderChg24") is not None else "–")]
    if g("gm.smartDegen") is not None:
        kv.append(("smart-money wallets", "%d" % g("gm.smartDegen")))
    # an unknown value stays on the card only where the gap itself is a warning (the safety rows); elsewhere it is noise
    keep_unknown = {"holders", "biggest wallet", "top 10 wallets", "insider wallets", "liquidity locked", "creator holds", "creator sold in 3h", "mint authority"}
    kv = [(k, v) for k, v in kv if v != "–" or k in keep_unknown]
    gp, cm, hl = rk.get("gp") or {}, rk.get("cm") or {}, rk.get("hl") or {}
    if M.num(hl.get("top10Pct")) is not None:
        kv.append(("top 10 wallets (chain)", pct(hl.get("top10Pct")) + (" · biggest %s" % pct(hl.get("top1Pct")) if M.num(hl.get("top1Pct")) is not None else "")))
    if gp:
        flags = [n for k, n in (("mintable", "mintable"), ("freezable", "freezable"), ("closable", "closable"), ("balMutable", "balances mutable"), ("nonTransferable", "non-transferable")) if gp.get(k)]
        kv.append(("GoPlus authorities", ", ".join(flags) if flags else "none left (good)"))
        kv.append(("GoPlus trusted", yes_no(gp.get("trusted"))))
        if M.num(gp.get("lpBurnPct")) is not None:
            kv.append(("LP burned (GoPlus)", pct(gp.get("lpBurnPct"))))
        if M.num(gp.get("top10Pct")) is not None:
            kv.append(("top 10 wallets (GoPlus)", pct(gp.get("top10Pct"))))
    if cm:
        if M.num(cm.get("rcUp")) is not None or M.num(cm.get("rcDown")) is not None:
            kv.append(("community votes (RugCheck)", "%d up / %d down" % (M.num(cm.get("rcUp")) or 0, M.num(cm.get("rcDown")) or 0)))
        if M.num(cm.get("cgWatch")):
            kv.append(("CoinGecko watchlists", "%d" % M.num(cm.get("cgWatch"))))
        if M.num(cm.get("xFollowers")) is not None:
            kv.append(("X followers", "%d" % M.num(cm.get("xFollowers")) + ((" · %d tweets / 7d" % M.num(cm.get("xTweets7d"))) if M.num(cm.get("xTweets7d")) is not None else "")))
        if M.num(cm.get("tgSubs")) is not None:
            kv.append(("Telegram members", "%d" % M.num(cm.get("tgSubs")) + ((" · %d msgs / 24h" % M.num(cm.get("tgMsgs24"))) if M.num(cm.get("tgMsgs24")) is not None else "")))
        if M.num(cm.get("stWatch")) is not None:
            kv.append(("StockTwits watchers", "%d" % M.num(cm.get("stWatch"))))
    if g("bq.trades1h") is not None:
        kv.append(("on-chain, last hour", "%d trades · %d buyers / %d sellers · net %s" % (g("bq.trades1h"), g("bq.buyers1h") or 0, g("bq.sellers1h") or 0, fmt_amt(g("bq.netUsd1h") or 0, True))))
    if g("lct.interactions") is not None:
        kv.append(("X/social 24h (LunarCrush)", "%s interactions" % fmt_money(g("lct.interactions"), dollars=False) + ((" · %d posts" % g("lct.posts")) if g("lct.posts") is not None else "")))
    if c.get("launchpad"):
        kv.append(("launchpad", str(c["launchpad"]) + (" · not pump.fun, Bonk or Bags" if g("lp.other") else "")))
    dp = rk.get("dp") or {}
    if dp.get("paid") is not None:
        paid = M.truthy(dp.get("paid"))
        kv.append(("DEX paid", ("yes" + ((" · profile approved %.0f h before the scan" % M.num(dp["paidAgeH"])) if M.num(dp.get("paidAgeH")) is not None else "")
                                + ((" · %d paid ad%s" % (M.num(dp["ads"]), "" if M.num(dp["ads"]) == 1 else "s")) if M.num(dp.get("ads")) else "")) if paid else "no"))
    vt = rk.get("vt") or {}
    if M.num(vt.get("likes")) is not None:
        when = (" · posted %.0f h before the scan" % M.num(vt["tweetAgeH"])) if M.num(vt.get("tweetAgeH")) is not None else ""
        kv.append(("the story: source tweet", "@%s · %s likes · %s replies%s" % (vt.get("screenName") or "?", fmt_money(vt.get("likes"), dollars=False), fmt_money(vt.get("replies"), dollars=False), when)))
        if vt.get("text") and str(vt.get("text")) != "null":
            kv.append(("tweet text", "“%s”" % str(vt["text"])[:160]))
    elif g("vt.tweet"):
        kv.append(("the story: source tweet", "the X link is a single tweet, but it could not be read"))
    if g("theme.animal"):
        kv.append(("theme", "animal story"))
    if g("mkt.sol24") is not None:
        kv.append(("market: SOL 24h", sgn("%+.1f%%" % g("mkt.sol24")) + ((" · fear & greed %d" % g("mkt.fng")) if g("mkt.fng") is not None else "")))
    notes, amber = "", ""
    if c.get("standin"):
        notes += '<p class="note">DexScreener delivered no pair data this scan: the numbers here come from Jupiter or GeckoTerminal, which stood in. The chart opens by mint address.</p>'
    if c.get("tier") in ("risky", "fallback"):         # one amber line under the strip; a fallback keeps the list of what it failed
        amber = '<p class="pick-note">No coin passed every safety check this scan; this is the best of the rest.</p>'
        if c.get("relaxed"):
            notes += '<p class="note">It failed: %s.</p>' % E("; ".join(str(x) for x in c.get("relaxed") or []))
    elif c.get("tier") == "watch":
        notes += '<p class="note"><strong>Not a pick.</strong> Every coin that cleared the safety floor was over the zero limit this scan. This is the one with the fewest flags, shown with the odds that stopped it: %s%s.</p>' % (
            ("%s chance of a profit" % pct(100 * M.num(c["upP"]))) if M.num(c.get("upP")) is not None else "", (", %s chance of going to zero" % pct(100 * M.num(c["zeroP"]))) if M.num(c.get("zeroP")) is not None else "")
    chart = ('<details class="more chartf"><summary>Live chart</summary><iframe class="embed" src="https://dexscreener.com/solana/%s?embed=1&amp;theme=dark&amp;trades=0&amp;info=0" title="%s chart" loading="lazy"></iframe></details>' % (
        E(c.get("pair") or c.get("addr")), E(c.get("sym")))) if embed else ""     # behind a tap: a closed fold never loads the chart
    kv = [(k, v) for k, v in kv if k not in STRIP_KV]
    groups = [(name, [(k, v) for k, v in kv if test(k)]) for name, test in (("Trading", lambda k: k not in SAFETY_KV and k not in STORY_KV),
                                                                            ("Holders & safety", lambda k: k in SAFETY_KV), ("Story & attention", lambda k: k in STORY_KV))]
    numbers = '<details class="more nums"><summary>All numbers (%d)</summary><div class="groups"><div class="grp odds-grp"><h4>Score and odds</h4>%s%s</div>%s</div>%s</details>' % (
        len(kv) + len(verdicts), verdict_html, odds_note, "".join('<div class="grp"><h4>%s</h4><div class="kv">%s</div></div>' % (E(name), kv_html(items)) for name, items in groups if items),
        sources_row(c.get("src")))
    paper_html = ('<p class="paper">%s</p>' % E(paper)) if paper else ""
    rows = safety_checks(rk)
    if rows:
        worst = next((s_ for s_ in ("bad", "warn") if any(r_[0] == s_ for r_ in rows)), "ok")
        safety = '<details class="more safe %s"><summary><span class="ic" aria-hidden="true">%s</span>Safety check · %s</summary>%s</details>' % (
            worst, CHECK_ICON[worst], E(checks_summary(rk)), checklist(rk))
    else:
        safety = safety_box(c.get("safety"), c.get("ok"))
    why = '<details class="more"><summary>%s</summary><p class="why">%s</p></details>' % ("Why it ranks here" if c.get("tier") == "young" else "Why the bot picked it", E(c.get("why") or "")) if c.get("why") else ""
    return ('<article class="card rec"><div class="top"><div><span class="sym">%s</span>%s</div><div class="chips">%s%s</div></div>'
            '%s%s%s%s%s%s%s%s%s%s<div class="addr">%s</div></article>') % (
        E(c.get("sym")), name_html(c.get("sym"), c.get("name")), tier_chip(c), PR.card_safety(c, safety_chip(c.get("ok"))) + story_chip(c), PR.card_trap(c, now),
        stats_html, amber, paper_html, safety, why, notes, numbers, chart, links(c), E(c.get("addr")))


def coin_cell(rank, sym, name, chips):
    return '<td><strong>#%s %s</strong>%s%s</td>' % (E(rank), E(sym), name_html(sym, name), ('<div class="row">%s</div>' % chips) if chips else "")


def num_cells(score, mc, liq, vol):
    return ('<td class="n" data-k="score">%.0f</td><td class="n" data-k="market cap">%s</td><td class="n" data-k="liquidity">%s</td><td class="n" data-k="24h volume">%s</td>'
            % (score, fmt_money(mc), fmt_money(liq), fmt_money(vol)))


COIN_HEAD = '<thead><tr><th>coin</th><th class="n">score</th><th class="n">market cap</th><th class="n">liquidity</th><th class="n">24h volume</th><th></th></tr></thead>'
CHART_CELL = '<td class="act"><a href="https://dexscreener.com/solana/%s" target="_blank" rel="noopener">chart</a></td>'


def paper_rows(D):
    """{address: paper row} for the pick's paper line: the open row of each coin, else its newest sold one (D["pos"] is newest first)."""
    out = {}
    for r in D.get("pos") or []:
        a = r["p"].get("addr")
        if r["p"].get("grp") in M.PAPER_GROUPS and a and (a not in out or (out[a]["closed"] and not r["closed"])):
            out[a] = r
    return out


def pick_heading(picks):
    """One heading by the top pick's tier (the page never names, denies and buys a coin in one breath): strong and weak "The pick for
    the next 2 hours", risky and fallback "Risky pick for the next 2 hours", a watch coin or nothing "No pick this scan"."""
    tier = (picks[0].get("tier") or "strong") if picks else "none"
    if tier in ("watch", "none"):
        return "No pick this scan"
    return ("Risky pick for the next %s" if tier in ("risky", "fallback") else "The pick for the next %s") % horizon_text()


def search_block(D):
    """The nightly filter search (page_search.py, a report: frozen rules tested on coins they never saw) in the Pick tab's Details; its
    old place, the account block, is no longer on the page. Nothing without the module."""
    try:
        import page_search as PS
    except ImportError:
        return ""
    return '<section>%s</section>' % PS.section(D)


def shadow_block(D):
    """The Pick's shadow rules (page_shadow.py, fake money: four other sell rules on the same buys; the Pick's own rule is untouched) under
    the hour grid on the Pick tab. Nothing without the module."""
    try:
        import page_shadow as PSH
    except ImportError:
        return ""
    return '<section>%s</section>' % PSH.section(D, sys.modules[__name__])


def tests_block(inner):
    """The foot of the Pick tab: the shadow rules and the Learning Pick under one heading that says they are tests (Oct 26: the user wants
    the app "logisch und organisiert"; the Learning Pick's fold read like a part of the Pick account)."""
    if not inner:
        return ""
    return section("Tests on the side", "Other sell rules and the Learning Pick, each with fake money of its own. They never buy or sell for the Pick account.", inner)


def lernpick_block(D):
    """The Learning Pick (page_lernpick.py, fake money: a self-learning shadow bot with its own paper account; the Pick and the Radar are
    untouched) under the shadow rules on the Pick tab. Nothing without the module."""
    try:
        import page_lernpick as PL
    except ImportError:
        return ""
    return '<section>%s</section>' % PL.section(D, sys.modules[__name__])


def rocket_block(D):
    """The two paper accounts side by side and the rocket hunter's live test (page_rocket.py, fake money) at the top of the Radar
    tab. Nothing without the module."""
    try:
        import page_rocket as PK
    except ImportError:
        return ""
    return '<section>%s</section><script>%s</script>' % (PK.section(D), getattr(PK, "LIVE_JS", ""))


def winlose_block():
    """The winner/loser study (page_winlose.py, display only: which numbers come before big moves, and the few that tell the
    way) in the Pick tab's Details under the filter search. Nothing without the module."""
    try:
        import page_winlose as PW
    except ImportError:
        return ""
    return '<section>%s</section>' % PW.section()


def forecast_section(D):
    """What coins that looked like the pick did next (forecast.py, display only: it changes no pick and no sell rule), with how well
    these forecasts hit in their own backtest and on the bot's own picks."""
    rc = D.get("rec") or {}
    picks = [c for c in rc.get("picks") or [] if isinstance(c, dict)]
    if not picks:
        return ""
    p = picks[0]
    fc = FC.forecast(p.get("f"))
    head = "Look-alike forecast: %s" % E(str(p.get("sym") or "the pick"))
    sub = "what coins that looked like it at the scan did next, August to October 2026 · display only, it changes no pick"
    if not fc:
        return section(head, sub, '<div class="empty">No forecast: too few of the numbers it compares are known for this coin, or the reference file is missing.</div>')
    pc, b = FC.pct, fc["base"]
    lo, mid, hi = fc["m1"]
    rows = [("1.7 hours later (the 2h check)", "%.2fx to %.2fx, middle %.2fx" % (lo, hi, mid), "8 of 10 look-alikes ended in this range"),
            ("in profit after fees at 1.7 h", pc(fc["profit"]), "all coins of the data: %s" % pc(b["profit"])),
            ("to zero within 1.7 h", pc(fc["zero"]), "all coins of the data: %s" % pc(b["zero"])),
            ("2x at some point within 6 h", pc(fc["x2"]), "all coins of the data: %s" % pc(b["x2"])),
            ("3x at some point within 6 h", pc(fc["x3"]), "all coins of the data: %s" % pc(b["x3"]))]
    table = '<table class="fc"><tbody>%s</tbody></table>' % "".join(
        '<tr><td>%s</td><td class="num"><b>%s</b></td><td class="sub">%s</td></tr>' % (E(a), E(v), E(n)) for a, v, n in rows)
    ck = fc.get("check") or {}
    bt, bp = ck.get("backtest") or {}, ck.get("bot_picks") or {}
    honest = []
    cal = (bp.get("profit") or {}).get("cal") or []
    if bp.get("n") and len(cal) == 5:
        honest.append("Checked on the bot's own %d top picks since 7 October: the fifth with the best forecast said %s in profit and %s were, "
                      "the worst fifth said %s and %s were; the 8-of-10 range held %s of them." % (
                          bp["n"], pc(cal[4][0]), pc(cal[4][1]), pc(cal[0][0]), pc(cal[0][1]), pc(bp.get("range_hit") or 0)))
    zc = (bp.get("zero") or {}).get("cal") or []
    if zc:
        honest.append("Its chance of going to zero runs high: it said %s to %s, and %s to %s of those picks went to zero." % (
            pc(min(x[0] for x in zc)), pc(max(x[0] for x in zc)), pc(min(x[1] for x in zc)), pc(max(x[1] for x in zc))))
    if bt.get("n"):
        honest.append("The 2x and 3x chances were only checked on the data's own last three weeks (%d coins), where they were a little better "
                      "than the plain average." % bt["n"])
    note = '<p class="note">%s A forecast from look-alikes is a count of what happened to similar coins, never a promise; fake money only.</p>' % E(" ".join(honest))
    return section(head, sub + " · %d look-alikes" % fc["n"], table + note)


def rec_section(D, embed):
    rc = D.get("rec")
    if not rc:
        return ""
    picks = [c for c in rc.get("picks") or [] if isinstance(c, dict)]
    h2 = pick_heading(picks)
    head = "fake money · %s of %s coins passed the filters" % (fmt_int(rc.get("passed") or 0), fmt_int(rc.get("scanned")))
    if rc.get("pickBy") == "odds":
        head += " · ranked by trained odds"
    if M.num(rc.get("pricedAt")):
        head += " · prices refreshed %s, %d min into the scan" % (fmt_dt(rc["pricedAt"], True)[-5:], max(0, round((M.num(rc["pricedAt"]) - (M.num(rc.get("t")) or 0)) / 60000)))
    t_rec, t_run = M.num(rc.get("t")), M.num((D.get("state") or {}).get("lastRun"))
    if picks and t_rec and t_run and t_run - t_rec > 60_000:     # the newest run found no clean coin, so the older pick stays up: say so
        head = "from the run at %s · the latest run (%s) found no clean coin, so this older pick stays up · fake money" % (fmt_dt(t_rec, True), fmt_dt(t_run, True))
    peers = [c for c in picks + (rc.get("runnersUp") or []) if isinstance(c, dict)]
    held = paper_rows(D)
    if picks:
        body = '<div class="cards">%s</div>' % "".join(rec_card(c, D["now"], embed, peers, held) for c in picks)
    else:
        body = '<div class="empty">No recommendation this time: %s. The closest coins and what stopped them are listed below.</div>' % E(rc.get("reason") or ("no top coin had a clean safety report" if rc.get("passed") else "nothing passed the gates"))
    runners = [c for c in (rc.get("runnersUp") or []) if isinstance(c, dict)]
    if runners:
        tr = "".join('<tr>%s%s%s</tr>' % (coin_cell(c.get("rank") or "?", c.get("sym"), c.get("name"), safety_chip(c.get("ok"), c.get("safety"))),
                                          num_cells(M.num(c.get("score")) or 0, c.get("mc"), c.get("liq"), c.get("vol")), CHART_CELL % E(c.get("pair") or c.get("addr"))) for c in runners)
        body += '<details class="tap"><summary>Runners-up (%d)</summary><div class="tbl stack"><table>%s<tbody>%s</tbody></table></div></details>' % (len(runners), COIN_HEAD, tr)
    return section(E(h2), head, body, info=True)


def story_chip(c):
    """One chip when a coin is built on a story: a viral source tweet and/or an animal theme."""
    f, vt = c.get("f") or {}, (c.get("risk") or {}).get("vt") or {}
    bits = []
    if M.num(vt.get("likes")) is not None:
        bits.append("tweet with %s likes" % fmt_money(vt["likes"], dollars=False))
    if M.num(f.get("theme.animal")):
        bits.append("animal story")
    out = ('<span class="chip neutral">%s</span>' % E(" · ".join(bits))) if bits else ""
    if M.num(f.get("lp.other")):
        out += '<span class="chip warn" title="launched on %s: not pump.fun, Bonk or Bags, where bundled charts are common">%s launch</span>' % (E(c.get("launchpad") or "another launchpad"), E(c.get("launchpad") or "other launchpad"))
    return out


def odds_chip(c):
    up, zp = M.num(c.get("upP")), M.num(c.get("zeroP"))
    if up is None and zp is None:
        return '<span class="chip">no trained odds</span>'
    return '<span class="chip" title="trained odds within %s: chance of a profit · chance of going to zero">%s profit · %s zero</span>' % (
        E(horizon_text()), pct(100 * up) if up is not None else "–", pct(100 * zp) if zp is not None else "–")


def age_record(T):
    """The scored record by age at the scan (train.json 'ages'): the table that says whether the newest coins do better."""
    ages = [a for a in ((T or {}).get("ages") or []) if isinstance(a, dict) and a.get("n")]
    if not ages:
        return '<p class="note">No age record yet: the first scored scans decide whether coins under an hour old do better than the 3-to-12-hour coins the bot picks from.</p>'
    hz = horizon_text()
    tr = "".join('<tr><td>%s</td>%s%s</tr>' % (E(a.get("age")), stat_cells(a), stat_cells(a.get("passed")) if a.get("passed") else '<td class="n muted" colspan="4">–</td>') for a in ages)
    by = {a.get("lo"): a for a in ages}
    verdict = ""
    y, m = by.get(0), by.get(3)
    if y and m and y.get("avg") is not None and m.get("avg") is not None:
        better = y["avg"] > m["avg"]
        verdict = '<p class="note"><strong>What the record says:</strong> coins under an hour old averaged %s per 20 (%s went up, %s to zero) against %s (%s up, %s to zero) for the 3-to-12-hour coins the bot picks from, over %d and %d coin results. %s</p>' % (
            fmt_amt(y["avg"], True), pct(y.get("win")), pct(y.get("zero")), fmt_amt(m["avg"], True), pct(m.get("win")), pct(m.get("zero")), y["n"], m["n"],
            "So far the newest coins did better on average." if better else "So far the newest coins did not do better on average; the higher zero rate eats the winners.")
    return '%s<div class="tbl stack"><table><thead><tr><th>age at the scan</th><th colspan="4">all candidate-like coins</th><th colspan="4">coins that passed the gates</th></tr><tr><th></th>%s%s</tr></thead><tbody>%s</tbody></table></div><p class="note">a result is 20 in the coin at the scan, priced again %s later, after fees</p>' % (
        verdict, STAT_HEAD, STAT_HEAD, tr, E(hz))


def young_history(D):
    """Every new launch the tab listed in the last two days, and what 20 in it became 1 h and 24 h later: the thesis
    "the newest coins run" tested coin by coin, with the same fees as the tips."""
    docs = [d for d in (D.get("young_hist") or []) if isinstance(d, dict) and M.num(d.get("t"))]
    now = D["now"]
    rows, stats = [], {str(int(h)): [] for h in M.TIP_CHECKS}
    for doc in docs:
        t = M.num(doc["t"])
        outs = doc.get("outs") or {}
        for p in doc.get("picks") or []:
            if not isinstance(p, dict):
                continue
            cells = ""
            for h in M.TIP_CHECKS:
                key = str(int(h))
                cont = outs.get(key) or {}
                o = next((x for x in (cont.get("picks") or []) if isinstance(x, dict) and x.get("sym") == p.get("sym")), None)
                odd = odd_cell(cont, o, h)
                if odd:
                    cells += odd
                elif o:
                    stats[key].append(o)
                    cells += res_cell_html(o, h)
                else:
                    due = t + h * 3_600_000
                    cells += '<td class="n muted" data-k="%d h later">%s</td>' % (h, ("pending · %s" % fmt_dt(due, True)) if due > now else ("pending · next scan" if now - due < 3 * 3_600_000 else "no result"))
            chips = '<span class="chip">%d min old</span>%s' % (int(M.num(p.get("ageMin")) or 0), safety_chip(p.get("ok")))
            rows.append('<tr><td class="w">%s</td><td><strong>%s</strong><div class="row">%s</div></td><td class="n" data-k="score">%s</td><td class="n" data-k="market cap then">%s</td>%s%s</tr>' % (
                fmt_dt(t, True), E(p.get("sym")), chips, E("%.0f" % (M.num(p.get("score")) or 0)), fmt_money(p.get("mc")), cells, CHART_CELL % E(p.get("pair") or p.get("addr") or "")))
    if not rows:
        return ""
    bits = []
    for h in M.TIP_CHECKS:
        sc = stats[str(int(h))]
        if sc:
            up = sum(1 for o in sc if (M.num(o.get("eur")) or 0) > 0)
            bits.append("%d h later: %d priced, %d went up, %d to zero, average %s per 20" % (h, len(sc), up, sum(1 for o in sc if o.get("gone") or (M.num(o.get("mult")) or 0) < 0.02), fmt_amt(sum(M.num(o.get("eur")) or 0 for o in sc) / len(sc), True)) + ((" · " + tp_stats(sc)) if tp_stats(sc) else ""))
    head = '<thead><tr><th>scan at</th><th>coin</th><th class="n">score</th><th class="n">market cap then</th>%s<th></th></tr></thead>' % "".join('<th class="n">%d h later</th>' % h for h in M.TIP_CHECKS)
    note = ("the earlier new launches: " + "; ".join(bits)) if bits else "the earlier new launches: none priced again yet"
    return ('<details class="fold-lite"><summary>What the earlier new launches did</summary><p class="note">%s · 20 in each at the scan price, after fees · fake money</p>'
            '<details class="tap"><summary>%d new launches from the last scans</summary><div class="tbl stack hist"><table>%s<tbody>%s</tbody></table></div></details></details>') % (
        E(note), len(rows), head, "".join(rows))


def young_section(D, title=None):
    """The full scan's new launches (on the Radar tab until the switch, memebot.switch_at(), under title): every coin under an hour old with a
    tradable pair this scan, best score first, with the same odds and safety data as the pick, and the scored record by age. These coins are
    shown, never picked."""
    rc = D.get("rec") or {}
    young = [c for c in (rc.get("young") or []) if isinstance(c, dict)]
    n_all = int(M.num(rc.get("youngOf")) or len(young))
    head = ("from the hourly full scan: coins under an hour old with a DEX pair and at least %s of liquidity at the scan · never a pick (the %s profile picks from coins %g to %g hours old); "
            "the first %d are bought for %s each as paper positions · fake money") % (fmt_money(M.YOUNG_MIN_LIQ), M.HORIZON, M.GATE_MIN_AGE_H, M.GATE_MAX_AGE_H or 0, M.YOUNG_BUY_N, fmt_eur(M.YOUNG_TICKET))
    held = {r["p"].get("addr"): r for r in (D.get("open") or []) if r["p"].get("grp") in M.PAPER_GROUPS}
    # memebot marks only the first YOUNG_BUY_N; a coin further down the tab that the paper account holds is "already held" too
    young = [dict(c, bought="held") if c.get("bought") is None and c.get("addr") in held else c for c in young]
    if young:
        rows_html, traps = [], PR.young(D)          # each row's trap check (traps.rate at page build): verdict chip, one-row line, red tint
        for i, c in enumerate(young, 1):
            b = c.get("bought")
            buy = ('<span class="chip neutral">bought for %s</span>' % E(fmt_eur(b))) if isinstance(b, (int, float)) and not isinstance(b, bool) else (
                '<span class="chip neutral">already held</span>' if b == "held" else "")
            chips = '%s<span class="chip">%d min old</span>%s%s%s%s' % (PR.row_chips(traps.get(c.get("addr"))), int(M.num(c.get("ageMin")) or 0), buy,
                                                                       PR.row_safety(traps.get(c.get("addr")), safety_chip(c.get("ok"), c.get("safety"))), odds_chip(c), story_chip(c))
            rows_html.append('<tr%s>%s%s%s</tr>' % (PR.row_attr(traps.get(c.get("addr"))), coin_cell(i, c.get("sym"), c.get("name"), chips), num_cells(M.num(c.get("score")) or 0, c.get("mc"), c.get("liq"), c.get("vol")), CHART_CELL % E(c.get("pair") or c.get("addr"))))
        n_top = 1                              # in view: the best one (the radar sits above it on New); the others one tap below
        body = PR.young_head(traps, young) + '<div class="tbl stack"><table>%s<tbody>%s</tbody></table></div>' % (COIN_HEAD, "".join(rows_html[:n_top]))
        if rows_html[n_top:]:
            body += '<details class="fold-lite"><summary>%d more new launch%s</summary><div class="tbl stack"><table>%s<tbody>%s</tbody></table></div></details>' % (
                len(rows_html) - n_top, "" if len(rows_html) - n_top == 1 else "es", COIN_HEAD, "".join(rows_html[n_top:]))
        cards = "".join(rec_card(dict(c, tier="young", _trap=traps.get(c.get("addr"))), D["now"], embed=False, peers=young, held=held) for c in young)
        body += '<details class="tap"><summary>Every number behind each coin (%d cards)</summary><div class="cards">%s</div></details>' % (len(young), cards)
        gates = [(c.get("sym"), c.get("gates") or []) for c in young if c.get("gates")]
        if gates:
            body += '<details class="tap"><summary>Which other gates they would fail today</summary><ul class="note">%s</ul></details>' % "".join(
                "<li><strong>%s</strong>: %s</li>" % (E(sym), E("; ".join(str(x) for x in g))) for sym, g in gates)
    elif rc and "young" not in rc:
        body = '<div class="empty">This scan ran before the tab existed; the next scan fills it.</div>'
    elif rc:
        body = '<div class="empty">No coin under an hour old had a DEX pair with %s of liquidity in this scan (%d coins scanned).</div>' % (fmt_money(M.YOUNG_MIN_LIQ), int(M.num(rc.get("scanned")) or 0))
    else:
        body = '<div class="empty">No scan yet.</div>'
    body = '<h3>This scan</h3>%s<details class="fold-lite"><summary>The record by age</summary>%s</details>%s' % (body, age_record(D.get("train")), young_history(D))
    hint = ""
    if live_repo():
        hint, box = early_box(D, young, held)     # the hint behind the heading's ⓘ, the early box (hidden until a scan lists coins) on top
        body = box + body
    h2 = ("%d new launch%s under an hour old" % (n_all, "" if n_all == 1 else "es")) if rc else "New launches"
    if n_all > len(young) and young:
        h2 += " (the %d best shown)" % len(young)
    if title:                        # the legacy block on the Radar tab: its own heading, the count in the first line under it
        body = '<p class="note">%s</p>%s' % (E(h2), body)
        h2 = title
    return section(E(h2), head, body, info=True, more=hint)


EARLY_LABEL = ("Fake money · not advice. Not scored by the full scan yet and only partly safety-checked: RugCheck only, the creator's wallet is "
               "checked later. The paper account buys from the scored list at about minute 22, not from this list.")


def early_box(D, young, held):
    """The early list on the New launches tab (a page built on GitHub Actions only), as (hint, box): the hint (it sits behind the tab
    heading's ⓘ), and a box the live script fills while a
    scan runs with the coins its launch spotter found about five minutes in (live.json "young"), before they are scored. It carries this
    scan's own early list (data-early-doc, checked as bot.py checks what it pushes) and each coin's fate on the scored list (data-final),
    so after the scan the list stays folded above the scored one. Nothing here is a trade: no swap link, and the label says how it is bought."""
    now = D["now"]
    nxt = next_scan_ms(now, D.get("runs")) + 5 * 60_000
    hint = ('<p class="note ehint">During each scan, the coins it finds under an hour old appear here about 5 minutes after it starts, before they are '
            'scored (next: about %s %s). Keep this tab open.</p>') % (E(local(nxt).strftime("%H:%M")), TZ_NAME)
    doc = None
    path = os.path.join(D.get("dir") or "", "young_early.json")
    if D.get("dir") and os.path.exists(path):
        try:
            import bot as B
            doc = B.early_doc(path, now)
        except Exception:
            doc = None
    rc = D.get("rec") or {}
    final = {}
    if M.num(rc.get("t")):
        coins = {}
        for k, c in enumerate(young, 1):
            b = c.get("bought")
            coins[str(c.get("addr"))] = {"k": k, "b": b if (isinstance(b, (int, float)) and not isinstance(b, bool)) or b == "held" else ("held" if c.get("addr") in held else None)}
        rid = dt.datetime.fromtimestamp(M.num(rc["t"]) / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H%M")
        rec_e = M.load_json(os.path.join(D.get("dir") or "", "db", "memeearly", rid + ".json"), None) if D.get("dir") else None
        for c in (rec_e.get("coins") or []) if isinstance(rec_e, dict) and rec_e.get("t") == rc.get("t") else []:
            if isinstance(c, dict) and c.get("out") and str(c.get("addr")) not in coins:
                coins[str(c.get("addr"))] = {"out": str(c["out"])[:120]}
        final = {"t": rc.get("t"), "coins": coins}
    attrs = ' data-run-t="%d"' % int(M.num(now) or 0)
    if doc:
        attrs += ' data-early-doc="%s"' % E(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    if final:
        attrs += ' data-final="%s"' % E(json.dumps(final, separators=(",", ":"), ensure_ascii=False))
    box = ('<details class="early" data-early%s hidden><summary><span class="estatus" data-early-status></span><span class="obadge eb">EARLY</span></summary>'
           '<div class="ebody"><p class="note" data-early-label>%s</p>'
           '<div class="eorder" role="radiogroup" aria-label="Order of the early list">'
           '<label><input type="radio" name="eorder" value="new" checked>Newest first</label><label><input type="radio" name="eorder" value="score">Score order</label></div>'
           '<ol class="ecards" data-early-list></ol></div></details>') % (attrs, E(EARLY_LABEL))
    return hint, box


SCAN_MINUTE_UTC = 10      # the scheduled scan starts at this minute of every hour (.github/workflows/scan.yml); a run takes about 15 minutes
HISTORY_DAYS = 2          # the hour-by-hour list covers this many days
HISTORY_OPEN = 12         # rows shown before the rest folds (a phone screen's worth)


def next_scan_ms(now, runs=None):
    """When the next scan starts: at the median start minute of the last runs (db/memeruns; GitHub starts the hourly cron about half an
    hour late), else at the cron minute SCAN_MINUTE_UTC (page_office.scan_minute)."""
    t = dt.datetime.fromtimestamp((M.num(now) or 0) / 1000, dt.timezone.utc).replace(minute=PO.scan_minute(runs, SCAN_MINUTE_UTC), second=0, microsecond=0)
    if t.timestamp() * 1000 <= (M.num(now) or 0):
        t += dt.timedelta(hours=1)
    return int(t.timestamp() * 1000)


def no_coin_reason(note):
    """The 'why no coin' sentence of a run note, short."""
    s = str(note or "")
    m = re.search(r"No recommendation:?\s*([^.]*)", s)
    if m:
        return (m.group(1).strip(" .") or "no coin named")[:160]
    if "left as they were" in s or "rate limit or outage" in s:
        return "scan too small (rate limit or outage), the earlier pick was kept"
    return "no coin named"


def tp_val(o, level=None):
    """What 20 made in a result under the paper take-profit at `level` (default TP_RULE): sold the first minute a candle closed
    there after the entry price was taken, else held to the check. None when the result has no replay (no candles)."""
    tpx = o.get("tpx") if isinstance(o.get("tpx"), dict) else None
    return M.num(tpx.get(M.tp_key(M.TP_RULE if level is None else level))) if tpx else None


def tp_sold(o, level=None):
    """The minute after the tip the take-profit at `level` sold, or None (not reached, or no candles)."""
    tpm = o.get("tpMin") if isinstance(o.get("tpMin"), dict) else {}
    return M.num(tpm.get(M.tp_key(M.TP_RULE if level is None else level)))


def tp_pct():
    return round(100 * M.TP_RULE)


def peak_txt(o):
    """' · peak 5.9x · sold at +20% after 23 min: +2.22' when the candles of the window are known."""
    if M.num(o.get("hi")) is None:
        return ""
    s = " · peak %s" % fmt_mult(o.get("hi"))
    if tp_sold(o) is not None and tp_val(o) is not None:
        s += " · sold at +%d%% after %d min: %s" % (tp_pct(), tp_sold(o), fmt_amt(tp_val(o), True))
    return s


def candles_txt(o):
    return ' <span class="muted" title="priced from the minute candles of the window, because the run that should have priced it came too late">· from candles</span>' if o.get("fromCandles") else ""


def res_cell_html(o, hours):
    """A priced result in two lines: the multiple and what 20 made, then the peak and the take-profit replay in small print."""
    good = (M.num(o.get("eur")) or 0) > 0
    r2 = peak_txt(o)[3:] + candles_txt(o)
    return '<td class="n res %s" data-k="%d h later"><span class="r1">%s · %s</span>%s</td>' % (
        "good" if good else "bad", hours, fmt_mult(o.get("mult")), fmt_amt(o.get("eur"), True), ('<span class="r2">%s</span>' % r2) if r2 else "")


def tip_state(o):
    """good / bad / zero for a priced result."""
    if o.get("gone") or (M.num(o.get("mult")) or 0) < 0.02:
        return "zero"
    return "good" if (M.num(o.get("eur")) or 0) > 0 else "bad"


def tip_strip(items, title):
    """One square per tip, oldest left: its 1 h result as a colour (up, lost, to zero, not yet priced); hover or tap for the numbers."""
    if not items:
        return ""
    n = lambda s: sum(1 for x in items if x[1] == s)
    sq = "".join('<span class="sq %s" data-tip="%s"></span>' % (s, E(txt)) for _, s, txt in sorted(items, key=lambda x: x[0]))
    counts = " · ".join(txt % n(s) for s, txt in (("good", "%d went up"), ("bad", "%d lost"), ("zero", "%d to zero"), ("pend", "%d not priced yet")) if n(s))
    return ('<div class="stripbox"><div class="strip-head"><span class="t">%s</span><span class="sum">%d tips · %s</span></div><div class="strip" role="img" aria-label="%s">%s</div>'
            '<div class="strip-leg"><span><i class="sq good"></i>went up</span><span><i class="sq bad"></i>lost</span><span><i class="sq zero"></i>went to zero</span><span><i class="sq pend"></i>not priced yet</span>'
            '<span class="muted">20 each, after fees · oldest left</span></div></div>') % (E(title), len(items), E(counts), E("%d tips: %s" % (len(items), counts)), sq)


def odd_cell(cont, o, hours):
    """The cell of a check that is not a result: priced far too late (being priced again from the candles), still waiting for
    the pool's candles, or never priced because the pool has none."""
    if cont and M.stale_check(cont, hours):
        return '<td class="n muted" data-k="%d h later">priced %.1f h late · being priced again from the window\'s candles</td>' % (hours, M.num(cont.get("h")) or 0)
    if o and o.get("waiting"):
        return '<td class="n muted" data-k="%d h later">pending · the window\'s candles</td>' % hours
    if o and o.get("missed"):
        return '<td class="n muted" data-k="%d h later">not priced · %s</td>' % (hours, "the window\'s candles are unusable" if o.get("glitch") else "no candles for the window")
    return ""


def tp_stats(outs):
    """What 20 made when sold at +TP_RULE the first minute a candle closed there after the entry (else held to the end), over the
    results that have candles."""
    known = [o for o in outs if tp_val(o) is not None]
    if not known:
        return ""
    hit = sum(1 for o in known if tp_sold(o) is not None)
    return "selling at +%d%% when reached (%d of %d did): average %s per 20" % (tp_pct(), hit, len(known), fmt_amt(sum(tp_val(o) for o in known) / len(known), True))


def tp_levels_txt(pts, label):
    """Every take-profit level against holding, on the same results (the ones with candles): which level would have paid."""
    known = [o for _, o in pts if tp_val(o) is not None]
    if not known:
        return ""
    held = sum(M.num(o["eur"]) for o in known)
    bits = ["held to the end %s" % fmt_amt(held, True)]
    for lv in M.TP_LEVELS:
        tot = sum(tp_val(o, lv) for o in known)
        bits.append("sold at +%d%% %s (%d sold)" % (round(100 * lv), fmt_amt(tot, True), sum(1 for o in known if tp_sold(o, lv) is not None)))
    return ('<p class="note">Take-profit levels, %s, on the %d tip%s with minute candles (sold the first minute a candle closed at the level after the entry price, else held; fees included): %s.</p>'
            % (E(label), len(known), "" if len(known) == 1 else "s", " · ".join(bits)))


def compound_chain(recs, key="1"):
    """What 20 becomes when it rides every tip in turn: each tip's 1 h result (after fees) multiplies the stake. Tips of one
    scan share the stake equally. The honest 'how much would 20 be now' line."""
    equity, n = M.TICKET, 0
    for doc in sorted((d for d in recs if isinstance(d, dict) and str(d.get("rule") or M.RULE) == M.RULE), key=lambda d: M.num(d.get("t")) or 0):
        outs = [o for o in M.settled((doc.get("outs") or {}).get(key), float(key)) if M.num(o.get("eur")) is not None]
        if not outs:
            continue
        mult = sum((M.TICKET + M.num(o["eur"])) / M.TICKET for o in outs) / len(outs)
        equity *= max(0.0, mult)
        n += 1
    return {"equity": round(equity, 2), "n": n}



def profit_rows(D):
    """Every tip the bot named, priced again 1 h, horizon and 24 h later: [(key, hours, label, [(tip time, result)...])],
    oldest tip first, settled results only (fake money, 20 per tip, after fees)."""
    recs = sorted((d for d in (D.get("track_all") or D.get("track") or []) if isinstance(d, dict) and M.num(d.get("t")) and str(d.get("rule") or M.RULE) == M.RULE), key=lambda d: M.num(d["t"]))
    rows = []
    for key, hours, label in (("1", 1.0, "1 h later"), ("out", M.EVAL_H, "%s later (the horizon)" % horizon_text()), ("24", 24.0, "24 h later")):
        pts = []
        for d in recs:
            if key == "out":
                cont = d.get("out") if isinstance(d.get("out"), dict) else {}
                outs = [o for o in (cont.get("picks") or []) if isinstance(o, dict)]
            else:
                outs = M.settled((d.get("outs") or {}).get(key), hours)
            pts += [(M.num(d["t"]), o) for o in outs if M.num(o.get("eur")) is not None]
        rows.append((key, hours, label, pts))
    return rows


def profit_stats(pts):
    n = len(pts)
    tot = sum(M.num(o["eur"]) for _, o in pts)
    up = sum(1 for _, o in pts if M.num(o["eur"]) > 0)
    zero = sum(1 for _, o in pts if o.get("gone") or (M.num(o.get("mult")) or 0) < 0.02)
    tp = [tp_val(o) for _, o in pts if tp_val(o) is not None]
    tp_tot = sum((tp_val(o) if tp_val(o) is not None else M.num(o["eur"])) for _, o in pts)   # sold at +TP_RULE where the candles are known, else held to the end
    hit = sum(1 for _, o in pts if tp_sold(o) is not None)
    return {"n": n, "tot": tot, "up": up, "zero": zero, "tp": tp, "tpTot": tp_tot, "hit": hit}


def profit_section(D):
    """The tip record, the page's last word: every tip the bot named, priced again 1 h, horizon and 24 h later, summed up as
    fake money (20 per tip, after fees), with the running total drawn over time. A test of the tips; the paper account (the top pick
    for 50 and the first new launches for 3 each, every scan, sold by the paper rules) is the dashboard at the top."""
    rows = [r for r in profit_rows(D) if r[3]]
    if not rows:
        return ""
    key, hours, label, pts = rows[0]
    s = profit_stats(pts)
    staked = s["n"] * M.TICKET
    staked_t = format(staked, ",.0f") + "\u00a0€"
    yes = s["tot"] > 0
    verdict = ('<p class="verdict %s"><strong>%s.</strong> %d tip%s priced %s: %d went up, %d went to zero, together <strong>%s</strong> on %s staked (%s per 20 €).%s</p>' % (
        "good" if yes else "bad", "Up so far" if yes else "Down so far", s["n"], "s" if s["n"] != 1 else "", label, s["up"], s["zero"],
        _eur(s["tot"], True), staked_t, _eur(s["tot"] / s["n"], True), ""))
    tiles = [tile("All tips together, %s (%s per tip)" % (label, fmt_eur(M.TICKET)), _eur(s["tot"], True), "%d tips · %s staked · fake money, after fees" % (s["n"], staked_t), lead=True),
             tile("Tips that went up", "%d of %d" % (s["up"], s["n"])), tile("Tips that went to zero", "%d of %d" % (s["zero"], s["n"]))]
    words = '<p>Went up: a profit after fees, which needs about %s. Went to zero: under 2%% of the entry price.</p>' % E(sgn("%+.1f%%" % (100 * (be_mult(M.TICKET) - 1))))
    html_ = '<section class="hero">%s</section>' % "".join(tiles)          # in view: the three numbers (the paper account's total is on the Traders tab, once)
    trs = []
    for key_, hours_, label_, pts_ in rows:
        st_ = profit_stats(pts_)
        trs.append('<tr><td>%s</td><td class="n" data-k="tips priced">%d</td><td class="n" data-k="went up">%d</td><td class="n" data-k="to zero">%d</td><td class="n" data-k="together"><span class="%s">%s</span></td><td class="n" data-k="per 20">%s</td><td class="n" data-k="sold at +%d%% when reached">%s</td></tr>' % (
            E(label_), st_["n"], st_["up"], st_["zero"], "good" if st_["tot"] > 0 else "bad", _eur(st_["tot"], True), _eur(st_["tot"] / st_["n"], True), tp_pct(),
            (_eur(st_["tpTot"], True) + " (%d of %d with candles)" % (len(st_["tp"]), st_["n"])) if st_["tp"] else "–"))
    table = '<div class="tbl stack"><table><thead><tr><th>priced</th><th class="n">tips</th><th class="n">went up</th><th class="n">to zero</th><th class="n">together</th><th class="n">per 20\u00a0€</th><th class="n">sold at +%d%% when reached</th></tr></thead><tbody>%s</tbody></table></div>' % (tp_pct(), "".join(trs))
    replay = "".join(tp_levels_txt(pts_, label_) for _, _, label_, pts_ in rows)
    chart = ""
    by_t = {}
    for t, o in pts:                       # a scan that named two coins is one point: the running total after that scan
        by_t.setdefault(t, []).append(o)
    if len(by_t) >= 2:
        run, series = 0.0, []
        for t in sorted(by_t):
            run += sum(M.num(o["eur"]) for o in by_t[t])
            series.append((t, round(run, 2)))
        ser = [("all tips together, %s" % label, "s1", series)]
        legend = '<div class="legend"><span style="--c:var(--s1)">%s, 20\u00a0€ each, after fees</span><span class="ref-leg">break-even</span></div>' % E("all tips together, %s" % label)
        chart = chart_box(line_chart(ser, 0.0, WIDE, ref_label="break-even", aria_label="Running profit of the tips", fmt_v=lambda v: _eur(v, True), fmt_t=lambda t: fmt_dt(t, True)),
                          line_chart(ser, 0.0, NARROW, ref_label="break-even", aria_label="Running profit of the tips", fmt_v=lambda v: _eur(v, True), fmt_t=lambda t: fmt_dt(t, True)), legend)
    chain = compound_chain(D.get("track_all") or D.get("track") or [])
    note = '<p class="note">Running total of every tip in time order, 20\u00a0€ in each, sold %s. ' % label
    note += ('20\u00a0€ put into every tip one after the other, each time the whole stake, would be %s now after %d tips. ' % (_eur(chain["equity"]), chain["n"])) if chain["n"] else ""
    note += 'Fake money: every tip counts 20 € per window here, fees simulated at 0.5%, minimum 0.81 per trade. The paper account is separate: its positions are on the Traders tab, with paper fees of 1%, minimum 0.10.</p>'
    more = '<details class="fold-lite"><summary>With a take-profit, and how this is counted</summary>%s%s</details>' % (replay, note)
    rest_ = '<details class="fold-lite tipf"><summary>Running total and table</summary><div class="tipf-b">%s</div></details>' % (verdict + chart + table + more)
    return section("Tip record", "a test of the tips, not the paper account: every coin the bot named counted as its own 20 €, priced again after the window",
                   html_ + rest_, info=True, more=words)

def history_section(D):
    """Every scan of the last days, newest first: what the bot named at that hour (tier, score, the odds it gave), and
    what 20 in it became when the horizon had passed. Scans that named nothing say why. This is the page's memory."""
    runs = [r for r in (D.get("runs") or []) if isinstance(r, dict) and M.num(r.get("t"))]
    if not runs:
        return ""
    now = D["now"]
    hz = horizon_text()
    recent = [r for r in runs if M.num(r["t"]) >= now - HISTORY_DAYS * 86_400_000]
    runs = (recent or runs[:24])[:72]
    recs = [d for d in (D.get("track") or []) if isinstance(d, dict) and M.num(d.get("t"))]

    def rec_for(t):
        best = min(recs, key=lambda d: abs(M.num(d["t"]) - t), default=None)
        return best if best is not None and abs(M.num(best["t"]) - t) <= 180_000 else None
    rows, scored, n_named, strip = [], {str(int(h)): [] for h in M.TIP_CHECKS}, 0, []
    for r in runs:
        t = M.num(r["t"])
        rec = rec_for(t) or {}
        picks = [p for p in (r.get("picks") or []) if isinstance(p, dict) and p.get("grp") == "recommend"]
        recp = {p.get("sym"): p for p in (rec.get("picks") or []) if isinstance(p, dict)}
        rule = str(r.get("rule") or M.RULE)
        other = "" if rule == M.RULE else ('<span class="chip" title="a manual run of the other profile">%s profile</span>' % ("2h" if "2h" in rule else "24h"))
        when = '<td class="w">%s</td>' % fmt_dt(t, True)
        if not picks:
            rows.append('<tr>%s<td colspan="5"><span class="muted">no coin</span> · %s%s</td><td></td></tr>' % (when, E(no_coin_reason(r.get("note"))), (" " + other) if other else ""))
            continue

        def res_cell(sym, key, hours):
            cont = ((rec.get("outs") or {}).get(key) or {}) if rec else {}
            o = next((x for x in (cont.get("picks") or []) if isinstance(x, dict) and x.get("sym") == sym), None)
            odd = odd_cell(cont, o, hours)
            if odd:
                return odd
            if o:
                if rule == M.RULE:
                    scored[key].append(o)
                return res_cell_html(o, hours)
            if rule != M.RULE:
                return '<td class="n muted" data-k="%d h later">–</td>' % hours
            due = t + hours * 3_600_000
            if due > now:
                txt = "pending · %s" % fmt_dt(due, True)
            elif rec and now - due < 3 * 3_600_000:
                txt = "pending · next scan"
            else:
                txt = "no result"
            return '<td class="n muted" data-k="%d h later">%s</td>' % (hours, txt)
        n_named += 1
        for p in picks:
            rp = recp.get(p.get("sym")) or {}
            up, zp = M.num(rp.get("up")), M.num(rp.get("zp"))
            odds = ("%s / %s" % (pct(100 * up) if up is not None else "–", pct(100 * zp) if zp is not None else "–")) if (up is not None or zp is not None) else "–"
            tier = dict(p, tier=p.get("tier") or rp.get("tier") or "strong")
            res = "".join(res_cell(p.get("sym"), str(int(h)), h) for h in M.TIP_CHECKS)
            if rule == M.RULE:
                c1 = ((rec.get("outs") or {}).get("1") or {}) if rec else {}
                o1 = next((x for x in (c1.get("picks") or []) if isinstance(x, dict) and x.get("sym") == p.get("sym")), None)
                label = "%s · %s" % (fmt_dt(t, True), p.get("sym") or "?")
                if o1 and not odd_cell(c1, o1, 1.0) and M.num(o1.get("eur")) is not None:
                    strip.append((t, tip_state(o1), "%s\n1 h later: %s · %s" % (label, fmt_mult(o1.get("mult")), fmt_amt(o1.get("eur"), True))))
                else:
                    strip.append((t, "pend", "%s\n1 h result not priced yet" % label))
            chips = tier_chip(tier) + other
            rows.append('<tr>%s<td><strong>%s</strong>%s<div class="row">%s</div></td><td class="n" data-k="score">%s</td><td class="n" data-k="odds then" title="chance of a profit / chance of going to zero, as the bot saw it then">%s</td>%s%s</tr>' % (
                when, E(p.get("sym")), name_html(p.get("sym"), p.get("name")), chips, E("%.0f" % (M.num(p.get("score")) or 0)), E(odds), res,
                CHART_CELL % E(rp.get("pair") or p.get("addr") or rp.get("addr") or "")))
    sub = "%d scans in the last %d days, %d of them named a coin · fake money, 20 per tip, after fees" % (len(runs), HISTORY_DAYS, n_named)
    track = ""
    bits = []
    for h in M.TIP_CHECKS:
        sc = scored[str(int(h))]
        if sc:
            up_n = sum(1 for o in sc if (M.num(o.get("eur")) or 0) > 0)
            bits.append("%d h later: %d tips priced, %d went up, average %s per 20" % (h, len(sc), up_n, fmt_amt(sum(M.num(o.get("eur")) or 0 for o in sc) / len(sc), True)) + ((" · " + tp_stats(sc)) if tp_stats(sc) else ""))
    track = ("Track record: " + "; ".join(bits)) if bits else "No tip has been priced again yet"
    chain = compound_chain(recs)
    if chain["n"]:
        track += " · 20 put into every tip one after the other (sold after 1 h, after fees) would be %s now after %d tips" % (fmt_amt(chain["equity"]), chain["n"])
    head = '<thead><tr><th>scan at</th><th>named</th><th class="n">score</th><th class="n">odds then</th>%s<th></th></tr></thead>' % "".join('<th class="n">%d h later</th>' % h for h in M.TIP_CHECKS)
    body = tip_strip(strip, "Every tip of the last %d days, 1 h later" % HISTORY_DAYS)
    table = '<p class="note">%s.</p><div class="tbl stack hist"><table>%s<tbody>%s</tbody></table></div>' % (E(track), head, "".join(rows))
    body += '<details class="fold-lite"><summary>Every scan, hour by hour (%d)</summary>%s</details>' % (len(rows), table)
    return section("Recommendations, hour by hour", sub, body, info=True)


def stat_cells(st):
    st = st or {}
    if not st.get("n"):
        return '<td class="n muted" colspan="4">no tips</td>'
    avg = M.num(st.get("avg"))
    return '<td class="n">%d</td><td class="n">%s</td><td class="n">%s</td><td class="n %s">%s</td>' % (
        st["n"], pct(st.get("win")) if st.get("win") is not None else "–", pct(st.get("zero")) if st.get("zero") is not None else "–",
        "good" if (avg or 0) > 0 else "bad", fmt_amt(avg, True) if avg is not None else "–")


STAT_HEAD = '<th class="n">tips</th><th class="n">went up</th><th class="n">to zero</th><th class="n">per 20</th>'


def train_section(D):
    """The training programs' results: the walk-forward test (what the bot's rule would have picked in past scans, judged by
    models that had not seen those scans), the zero model and the tuned limits, the gate audit and the factor splits."""
    T = D.get("train")
    if not T:
        return ""
    hz = horizon_text()
    rows_n, scans_n = int(M.num(T.get("rows")) or 0), int(M.num(T.get("scans")) or 0)
    wf = T.get("walkForward") or {}
    body = ['<p class="note">%s</p>' % E(re.sub(r"(?<![\d.,])\d{4,}(?![\d.,])", lambda m: fmt_int(int(m.group())), str(T.get("note") or "")))]     # 247249 -> 247,249
    if wf:
        names = [("top1", "the bot's best coin per scan"), ("top2", "the bot's two best coins per scan"), ("top2zero", "the two best under the zero limit (the rule in use)"),
                 ("byOdds", "the best trained odds per scan (the risky tier's rule)"), ("allPass", "every coin that passed the gates"), ("bottom2", "the two worst-scored passing coins")]
        tr = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (E(label), stat_cells(wf.get(k)), pct((wf.get(k) or {}).get("coverage")) if (wf.get(k) or {}).get("coverage") is not None else "–")
                     for k, label in names if wf.get(k))
        body.append('<h3>Test on scans the model had not seen</h3><p class="note">%d scans judged by models fitted on the scans before them only · a tip is 20\u00a0€ in the coin, priced again %s later · coverage: scans in which the rule found a coin</p>'
                    '<div class="tbl stack"><table><thead><tr><th>rule</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table></div>' % (int(M.num(T.get("tested")) or 0), hz, STAT_HEAD, tr))
    tuned = T.get("tuned") or {}
    if T.get("zeroModel"):
        zm = T["zeroModel"]
        lim = M.num(tuned.get("MAX_ZERO_P"))
        why = "".join("<li>%s</li>" % E(w) for w in (T.get("tunedWhy") or []))
        zf = "".join('<tr><td>%s <code>%s</code></td><td class="n">%s</td><td>%s</td></tr>' % (E(factor_label(z.get("factor"))), E(z.get("factor")), E("%.2f" % (M.num(z.get("spread")) or 0)),
                     E(" → ".join(("%+.0f%%" % (100 * (math.exp(v) - 1))) for v in (z.get("lo") or [])))) for z in (T.get("zeroFactors") or [])[:10])
        body.append('<h3>Zero model</h3><p class="note">fitted on %s coin results (%s went to zero, %s base rate): each factor is cut into four value bins, low to high, and each bin shifts the odds of going to zero within %s. '
                    'A clean coin is skipped when its calibrated zero chance is above %s.</p>%s<div class="tbl stack"><table><thead><tr><th>factor</th><th class="n">spread</th><th>odds shift per bin, low → high</th></tr></thead><tbody>%s</tbody></table></div>' % (
                        fmt_int(M.num(zm.get("n")) or 0), fmt_int(M.num(zm.get("zeros")) or 0), pct(100 * (M.num(zm.get("base")) or 0)), hz, pct(100 * lim) if lim is not None else "–",
                        ("<ul class=\"note\">%s</ul>" % why) if why else "", zf))
    zg = [g for g in (T.get("zeroGrid") or []) if isinstance(g, dict)]
    sg = [g for g in (T.get("scoreGrid") or []) if isinstance(g, dict)]
    if zg or sg:
        tz = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (pct(100 * (M.num(g.get("limit")) or 0)), stat_cells(g), pct(g.get("coverage")) if g.get("coverage") is not None else "–") for g in zg)
        ts = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (E("%.0f" % (M.num(g.get("minScore")) or 0)), stat_cells(g), pct(g.get("coverage")) if g.get("coverage") is not None else "–") for g in sg)
        body.append('<details><summary>Limit grids (top-2 tips in the test on unseen scans)</summary><div class="tbl stack"><table><thead><tr><th>zero limit</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table>'
                    '<table><thead><tr><th>score at least</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tz, STAT_HEAD, ts))
    gates = [g for g in (T.get("gates") or []) if isinstance(g, dict)]
    if gates:
        tg = "".join('<tr><td>%s</td>%s</tr>' % (E(g.get("text") or g.get("gate")), stat_cells(g)) for g in gates[:14])
        body.append('<details><summary>Gate audit (coins that failed exactly one gate)</summary><p class="note">a gate whose lone failers did as well as the passers protects nothing; one whose failers went to zero earns its keep</p>'
                    '<div class="tbl stack"><table><thead><tr><th>gate</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tg))
    filters = [g for g in (T.get("filters") or []) if isinstance(g, dict)]
    if filters:
        tf = "".join('<tr><td>%s</td><td class="n">%s</td>%s</tr>' % (E(g.get("filter")), pct(g.get("share")) if g.get("share") is not None else "–", stat_cells(g)) for g in filters)
        body.append('<details><summary>Filter recipes from outside, tested on the bot\'s results</summary><p class="note">trading-terminal presets as they circulate on TikTok (market cap, volume, age, "DEX paid"), applied to every scored coin of this profile\'s training window, next to the bot\'s own gates · "DEX paid" is read from DexScreener\'s orders for new coins and from the presence of a DexScreener profile for older results</p>'
                    '<div class="tbl stack"><table><thead><tr><th>filter</th><th class="n">keeps</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tf))
    tips = T.get("tips") or {}
    summary = ("%s coin results from %s scans%s" % (fmt_int(rows_n), fmt_int(scans_n), (" of the last %d days" % T["days"]) if isinstance(T.get("days"), int) else "")) if rows_n else "waiting for the first scored snapshot"
    if wf.get("top2zero") or wf.get("top2"):
        st = wf.get("top2zero") or wf["top2"]
        summary += " · the top 2 on scans the model had not seen: %s up, %s to zero" % (pct(st.get("win")), pct(st.get("zero")))
    if tips.get("n"):
        summary += " · real tips: %d, %s up" % (tips["n"], pct(tips.get("win")))
    return fold("Training", summary, "<section>%s</section>" % "".join(body), open_=False)


CLOSED_SHOWN = 100       # the paper account's closed-trades folds list this many (the newest); the count per reason covers them all


def closed_fold(rows, note=""):
    """A paper account's closed trades: how many were sold for each reason, then the table of the newest CLOSED_SHOWN (newest bought
    first), so the page stays small when the account has sold thousands of positions."""
    if not rows:
        return ('<p class="note">%s</p>' % E(note) if note else "") + closed_table(rows)
    why = {}
    for r in rows:      # the reason without the filters' details, so the count stays short
        k = ", ".join(exit_label({"why": e.get("why")}, r["p"]) for e in r["p"].get("_exits") or [] if isinstance(e, dict)) or r["status"]
        why[k] = why.get(k, 0) + 1
    by = " · ".join("%s (%d)" % (k, n) for k, n in sorted(why.items(), key=lambda kv: (-kv[1], kv[0])))
    shown = ("; the newest %d are listed below" % CLOSED_SHOWN) if len(rows) > CLOSED_SHOWN else ""
    return '<p class="note">%s%d sold, by reason: %s%s</p>%s' % (E(note + ". ") if note else "", len(rows), E(by), E(shown), closed_table(rows[:CLOSED_SHOWN]))


def closed_table(rows):
    if not rows:
        return '<div class="empty">No closed trades yet.</div>'
    tr = []
    for r in rows:
        p = r["p"]
        days = ((r["exit_t"] or 0) - (M.num(p.get("t")) or 0)) / 86_400_000 if r["exit_t"] else None
        sold_at = ", ".join(("%.2fx" % m if m is not None else "–") + (" (half)" if half else "") for m, half in r["sold_at"]) or "–"
        tr.append('<tr><td><strong>%s</strong>%s</td><td class="d" data-k="group">%s</td><td class="d" data-k="bought">%s</td><td class="d" data-k="sold because"><span class="chip %s">%s</span></td><td class="n" data-k="sold at">%s</td><td class="n" data-k="paid">%s</td><td class="n" data-k="came back">%s</td><td class="n" data-k="result"><span class="%s">%s</span></td><td class="n" data-k="held">%s</td></tr>' % (
            E(p.get("sym")), name_html(p.get("sym"), p.get("name")), ('<span class="nw">%s</span>' % E(group_tag(p))) if p.get("grp") in M.PAPER_GROUPS else ("bot" if r["bot"] else "random"), fmt_dt(p.get("t"), True), r["kind"], E(r["status"]), E(sold_at), fmt_amt(r["ticket"]), fmt_amt(r["back"]),
            "good" if r["pnl"] > 0 else "bad", fmt_amt(r["pnl"], True), ("–" if days is None else ("%.0fh" % (24 * days)) if days < 2 else ("%.1fd" % days))))
    return '<div class="tbl stack"><table><thead><tr><th>coin</th><th>group</th><th>bought</th><th>sold because</th><th class="n">sold at</th><th class="n">paid</th><th class="n">came back</th><th class="n">result</th><th class="n">held</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def horizon_text():
    return M.eval_text()


def big_section(D):
    big, hz = D["big"], horizon_text()
    fee = "An unchanged price counts %s (the two fees)." % _eur(FLAT, True)
    if not big:
        if D["snap_t"]:
            return '<div class="empty">First results at about %s: the %s coins of the last scan get priced again %s later. %s</div>' % (
                fmt_dt(D["snap_t"] + M.EVAL_H * 3_600_000, True), fmt_int(D["snap_n"] or 0), hz, fee)
        return '<div class="empty">The coin test starts after the first full scan has been priced again %s later. Every full scan saves all its coins; %s later each one is checked: what would 20\u00a0€ in it have become? %s</div>' % (hz, hz, fee)
    last = big[-1]
    all_avg = ((last["passAvg"] or 0) * last["passN"] + (last["failAvg"] or 0) * last["failN"]) / last["n"] if last["n"] else None
    summary = '<p class="note"><strong>Last scan (%s):</strong> the bot’s top 10 averaged %s per 20 · everything scanned %s · unchanged price %s (the two fees)</p>' % (
        fmt_dt(last["t0"], True), fmt_amt(last["topAvg"], True) if last["topAvg"] is not None else "–", fmt_amt(all_avg, True) if all_avg is not None else "–", fmt_amt(FLAT, True))
    shown = big[-10:]
    groups = [(fmt_dt(g["t0"], True), fmt_dt(g["t0"], day=True), {"pass": g["passAvg"], "top": g["topAvg"], "fail": g["failAvg"]}) for g in shown]
    series = [("pass", "passed the gates", "s1"), ("top", "bot's top 10", "s2"), ("fail", "failed a gate", "s3")]
    legend = '<div class="legend">%s<span class="ref-leg">price unchanged %s</span></div>' % ("".join('<span style="--c:var(--%s)">%s</span>' % (cls, E(name)) for _, name, cls in series), fmt_amt(FLAT, True))
    chart = chart_box(grouped_bars(groups, series, WIDE, FLAT), grouped_bars(groups, series, NARROW, FLAT), legend)
    tr = "".join('<tr><td class="w">%s</td><td class="n">%d</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
        fmt_dt(g["t0"], True), g["n"], g["passN"], fmt_amt(g["passAvg"], True), g["topN"], fmt_amt(g["topAvg"], True), g["failN"], fmt_amt(g["failAvg"], True),
        share(g["up"], g["n"]), share(g["gone"], g["n"])) for g in reversed(big))
    table = ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>scan</th><th class="n">coins</th><th class="n">passed gates · avg</th><th class="n">top 10 · avg</th>'
             '<th class="n">failed a gate · avg</th><th class="n">up after %s</th><th class="n">price vanished</th></tr></thead><tbody>%s</tbody></table></div></details>') % (hz, tr)
    return summary + chart + table


def weights_section(D):
    if not D["weights"]:
        return ""
    lam, n, hz = D["winfo"]["lambda"], D["winfo"]["n"], horizon_text()
    note = ("Learned weights count for %d%% (%d coin results scored so far, one per coin and scan); the hand-made prior fills the rest. Each bar is a factor's weight in the score: positive means higher is better." % (round(100 * lam), n)
            if n else "Prior weights until ~600 coin results are scored; then each factor’s rank correlation with the %s result replaces them. Each bar is a factor's weight in the score: positive means higher is better." % hz)
    tr = "".join('<tr><td>%s<div class="addr">%s</div></td><td class="n">%s</td><td class="n">%s</td></tr>' % (
        E(factor_label(k)), E(k), sgn("%+.2f" % v), (D["detail"].get(k) or {}).get("n") or "prior") for k, v in D["weights"])
    table = ('<details><summary>Table view and glossary</summary><div class="tbl"><table><thead><tr><th>factor · key</th><th class="n">weight</th><th class="n">coin results</th></tr></thead><tbody>%s</tbody></table></div></details>') % tr
    legend = '<div class="legend"><span style="--c:var(--s1)">higher is better</span><span style="--c:var(--s2)">lower is better</span></div>'
    inner = '<section><p class="note">what the score rewards and punishes · %s</p>%s%s</section>' % (
        E(note), chart_box(weight_bars(D["weights"], D["detail"], WIDE), weight_bars(D["weights"], D["detail"], NARROW), legend), table)
    return fold("How the score is built", "%d factors in use · %s" % (len(D["weights"]), ("learned %d%%" % round(100 * lam)) if n else "hand-made weights until ~600 results"), inner)


def cands_table(D):
    c, held, ever = D["cands"], D["held"], D["ever"]
    if not D["scan_t"]:
        return '<div class="empty">No full scan saved yet.</div>'
    if not c:
        return '<div class="empty">No coin passed the gates in the last scan.</div>'
    tr = []
    for x in c:
        a = x.get("a")
        ok, txt = M.risk_view(x.get("rc"))
        if a in held:
            flag = '<span class="chip neutral">held</span>'
        elif a in ever:
            flag = '<span class="chip">bought before</span>'
        else:
            flag = safety_chip(ok, txt)
        src = "".join('<span class="chip">%s</span>' % E(SRC.get(t.split(":", 1)[0], "%s") % t.split(":", 1)[-1]) for t in (x.get("src") or [])[:4])
        tr.append('<tr>%s%s%s</tr>' % (coin_cell(int(M.num(x.get("rank"))), x.get("s"), None, flag + src), num_cells(M.num(x.get("sc")) or 0, x.get("mc"), x.get("liq"), x.get("vol")), CHART_CELL % E(a)))
    return '<div class="tbl stack"><table>%s<tbody>%s</tbody></table></div>' % (COIN_HEAD, "".join(tr))


def short_note(note):
    return ". ".join(s for s in str(note or "").split(". ") if not s.startswith(("Weights:", "Bankroll:", "Paper account since", "Saved all"))).strip()


def note_cell(note, rec_mode):
    """A run note split into what matters: the outcome sentence(s) in bold, the gate counts behind a tap, the scan sentence dropped
    (its numbers are the row's chips). Returns (html, sources)."""
    sents = [s.strip().rstrip(".") for s in str(note or "").split(". ") if s.strip()]
    src = next((m.group(1) for s in sents for m in [re.search(r"from (\d+) sources", s)] if m), None)
    main, gates = [], None
    for s in sents:
        if s.startswith(("Scanned", "Weights:", "Bankroll:", "Paper account since", "Saved all")):
            continue
        if s.startswith("Most common gate:"):
            gates = s
            continue
        s = s.replace("; nothing bought (recommend mode)", "") if rec_mode else s.replace(" (recommend mode)", "")
        main.append(s)
    html_ = ('<strong>%s.</strong>' % E(" · ".join(main))) if main else ""
    if gates:
        first = gates[len("Most common gate:"):].split(";")[0].strip()
        html_ += '<details><summary>gates · %s</summary><p>%s.</p></details>' % (E(first), E(gates))
    return html_ or E(short_note(note)), src


def n_buys(run):
    """The buys of a run: pick mode's positions and the paper account's (a recommendation or a new launch with a ticket)."""
    return sum(1 for p in (run.get("picks") or []) if isinstance(p, dict) and (p.get("grp") == "pick" or (isinstance(p.get("bought"), (int, float)) and not isinstance(p.get("bought"), bool))))


def runs_table(runs, rec_mode):
    if not runs:
        return ""
    tr = []
    for r in runs[:12]:
        if not isinstance(r, dict):
            continue
        cell, src = note_cell(r.get("note"), rec_mode)
        tr.append('<tr><td class="w">%s</td><td class="m"><span class="chip">%s</span></td><td class="n" data-k="scanned">%s</td><td class="n" data-k="passed">%s</td><td class="n" data-k="sources">%s</td><td class="n" data-k="buys">%d</td><td class="n" data-k="sells">%d</td><td class="note-cell">%s</td></tr>' % (
            fmt_dt(r.get("t"), True), E(r.get("mode")), E(r.get("scanned") or "–"), E(r.get("passed") or "–"), E(src or "–"),
            n_buys(r), len(r.get("exits") or []), cell))
    return '<div class="tbl runs stack"><table><thead><tr><th>when</th><th>mode</th><th class="n">scanned</th><th class="n">passed gates</th><th class="n">sources</th><th class="n">buys</th><th class="n">sells</th><th>what happened</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


TABS = ("home", "pick", "young", "office", "account")     # the tab ids in their order (app.py PAGE_JS's TABS): Start, Pick, Radar, Brain, Archive
ARCHIVE_HEAD = ('<div class="arch-head"><h2>Archive &amp; research</h2><p>Everything that is research or no longer runs: the studies and simulations, '
                'the three paper traders and the new launches (ended on Oct 16). Nothing is deleted; every number is still here and still updated.</p></div>')
TRADERS_ERR = [""]                                # why page_traders.py could not be imported (the Traders tab's fallback says it)


def traders_page():
    """page_traders.py (the Traders tab, the radar's paper positions), or None in a copy of the code without it (or with a broken one)."""
    try:
        import page_traders as PT
        return PT
    except Exception as e:
        TRADERS_ERR[0] = type(e).__name__
        return None


def radar_ticket():
    """The radar's paper ticket (radar_paper.RADAR_TICKET), 10 € in a copy of the code without radar_paper.py."""
    try:
        import radar_paper as RP
        return RP.RADAR_TICKET
    except Exception:
        return 10.0


def safe(name, fn):
    """A section that cannot be rendered (a malformed doc) shows a notice instead of taking the page down."""
    try:
        return fn()
    except Exception as e:
        return '<div class="empty">This section could not be rendered (%s: %s).</div>' % (E(name), E(str(e)[:120]))


def fmt_when(ms, now):
    """'19:05 Berlin' for a time today, else 'Oct 05 22:06 Berlin'."""
    ms = M.num(ms)
    if not ms:
        return "–"
    try:
        t, n = local(ms), local(now)
    except (OverflowError, OSError, ValueError):
        return "–"
    return (t.strftime("%H:%M") if t.date() == n.date() else t.strftime("%b %d %H:%M")) + " " + TZ_NAME


def dash_section(D):
    """Recommend mode: the paper account since the restart in one strip: the profit or loss, what went in, what came back (the
    trades won and lost) and what the open positions would bring if everything were sold now (by group). Fake money, no budget."""
    P = D["paper"]
    a = P["acct"]
    since = ("since the restart %s" % fmt_dt(P["since"], True)) if P["since"] else "since the restart"
    cells = [("invested", fmt_amt(a["invested"]), "%d position%s bought" % (a["n"], "" if a["n"] == 1 else "s")),
             ("returned", fmt_amt(a["back"]), ("%d closed · %d won · %d lost" % (a["nClosed"], a["won"], a["lost"])) if a["nClosed"] else "nothing sold yet"),
             ("open value", fmt_amt(a["open"]), ("%d open · %d top pick · %d new launch%s · if everything were sold now%s" % (a["nOpen"], a["nTop"], a["nYoung"], "" if a["nYoung"] == 1 else "es",
                                                                                                                     (" · %d with no price yet, counted at 0" % P["noPx"]) if P.get("noPx") else ""))
              if a["nOpen"] else "nothing held")]
    rate = ("%s on %s invested" % (sgn("%+.1f%%" % (100.0 * a["pnl"] / a["invested"])), fmt_amt(a["invested"]))) if a["invested"] else "nothing bought yet"
    return ('<div class="acct"><div class="lead"><span class="k">profit/loss %s</span><span class="v">%s</span>'
            '<span class="delta %s">%s</span><span class="s">fake money, after fees</span></div>%s</div>') % (
        E(since), fmt_amt(a["pnl"], True), "good" if a["pnl"] > 0 else ("bad" if a["pnl"] < 0 else ""), E(rate),
        "".join('<div class="cell"><span class="k">%s</span><span class="v">%s</span><span class="s">%s</span></div>' % (E(k), E(v), E(sub)) for k, v, sub in cells))


def paper_curve(D):
    """The paper account's profit or loss after every run since the restart (memecurve "paper"), break-even as the reference line."""
    since = D["paper"]["since"] or 0
    pts = [(M.num(c["t"]), M.num(c["paper"].get("pnl"))) for c in D["curve"] if isinstance(c, dict) and M.num(c.get("t")) and M.num(c.get("t")) >= since
           and isinstance(c.get("paper"), dict) and M.num(c["paper"].get("pnl")) is not None and (M.num(c["paper"].get("since")) or since) >= since]
    series = [("paper account", "s1", pts)]
    wide = line_chart(series, 0.0, WIDE, ref_label="break-even", aria_label="Paper account profit or loss since the restart")
    if not wide:
        body = '<div class="empty">The curve needs two runs since the restart. It shows what came back plus what the open positions would fetch, minus what went in.</div>'
    else:
        body = chart_box(wide, line_chart(series, 0.0, NARROW, ref_label="break-even", aria_label="Paper account profit or loss since the restart"), "")
        body += '<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>run</th><th class="n">profit/loss</th></tr></thead><tbody>%s</tbody></table></div></details>' % (
            "".join('<tr><td>%s</td><td class="n">%s</td></tr>' % (fmt_dt(t), fmt_amt(v, True)) for t, v in pts))
    sub = "profit or loss since the restart after every run: what came back plus what the open positions would fetch, minus what went in, after fees · now %s" % fmt_amt(D["paper"]["acct"]["pnl"], True)
    return '<details class="fold-lite"><summary>Profit/loss over time</summary><p class="note">%s</p>%s</details>' % (E(sub), body)


# ---------------------------------------------------------------- the agent office tab
OFFICE_ST = ("done", "failed", "fallback", "skipped", "running")
OFFICE_CHIP = {"done": "good", "failed": "bad", "fallback": "warn", "running": "neutral"}
OFFICE_MODE = {"full": "a full scan", "light": "a light scan", "none": "no scan, prices for the open positions only"}


def fmt_secs(s, short=False):
    """A duration in plain words: '45 s', '8 min 20 s', '29 min'; short (floor plan, timeline): '8.3 min'."""
    s = max(0, int(round(M.num(s) or 0)))
    if s < 60:
        return "%d s" % s
    if s >= 600:
        return "%d min" % round(s / 60.0)
    if short:
        return "%.1f min" % (s / 60.0)
    return ("%d min %d s" % (s // 60, s % 60)) if s % 60 else "%d min" % (s // 60)


def clock(ms):
    return local(ms).strftime("%H:%M:%S") if M.num(ms) else "–"


def host_tool(host):
    """The service a host belongs to ('www.reddit.com' -> 'Reddit'); an unknown host is shown as it is."""
    h = str(host).lower()
    return next((t for k, t in OFFICE_HOSTS if k in h), str(host))


def office_meta(aid, now=None):
    """(name, job, services) of an agent; the trader's job is the hold rule in use (what it takes on paper as of now, ms: the page's time,
    the clock without one), an unknown id keeps its id as its name."""
    if aid == "trader":         # the job as it is now: until the switch the first new launches too, from it the radar's coins without traps
        took = ("the first %d new launches for %s each" % (M.YOUNG_BUY_N, fmt_eur(M.YOUNG_TICKET)) if (now if M.num(now) is not None else dt.datetime.now().timestamp() * 1000) < M.switch_at()
                else "every coin the launch radar finds without traps for %s" % fmt_eur(radar_ticket()))
        return ("Paper trader", "names the pick and takes it on paper for %s, and %s; each paper position %s" % (fmt_eur(M.TOP_TICKET), took, M.PAPER_LABEL), ())
    return OFFICE_AGENTS.get(aid, (aid.replace("_", " ").capitalize(), "", ()))


def office_word(a):
    if a.get("ext"):            # an agent in its own job (the Launch radar): its state, not a step of this run
        return a.get("word") or "own job"
    if a["st"] == "running":
        return "writing this page" if a["id"] == "reporter" else "at work"
    return "did not run" if a["st"] == "absent" else ("never finished" if a.get("open") else a["st"])


def office_data(D):
    """office.json made ready to draw: the agents in run order with their seconds, each department with its agents and one rolled-up light,
    the run's span, how many agents worked at once and the department opened first (the slowest agent's). None without an agent."""
    O = D.get("office")
    if not isinstance(O, dict):
        return None
    ags = []
    for a in O.get("agents") or []:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        s, e, st = M.num(a.get("start")), M.num(a.get("end")), str(a.get("status") or "")
        waits = a.get("waits") if isinstance(a.get("waits"), dict) else {}
        lines = a.get("lines") if isinstance(a.get("lines"), list) else []
        blocked = a.get("blocked") if isinstance(a.get("blocked"), list) else []
        ags.append({"id": str(a["id"]), "s": s, "e": e, "st": st if st in OFFICE_ST else ("done" if s and e else "skipped"), "bg": bool(a.get("bg")),
                    "out": str(a.get("out") or ""), "lines": [str(x)[:200] for x in lines if x is not None][-60:],
                    "waits": {str(k): int(M.num(v)) for k, v in waits.items() if M.num(v)}, "blocked": [str(h) for h in blocked if h]})
    if not ags:
        return None
    marks = [x for a in ags for x in (a["s"], a["e"]) if x]
    t0 = M.num(O.get("t")) or (min(marks) if marks else 0)
    t1 = max([M.num(O.get("end")) or 0] + marks)
    t1 = t1 if t1 > t0 else t0 + 1000
    for a in ags:
        a["ran"] = bool(a["s"]) and a["st"] != "skipped"
        a["open"] = a["ran"] and not a["e"] and a["st"] != "running"     # started and never finished: failed, its bar runs to the end of the run
        a["st"] = "failed" if a["open"] else a["st"]
        a["secs"] = max(0.0, ((a["e"] or t1) - a["s"]) / 1000.0) if a["ran"] else 0.0
        a["name"], a["job"], a["tools"] = office_meta(a["id"], D.get("now"))
    by = {a["id"]: a for a in ags}
    ext = PO.ext_agents(D, office_meta, sys.modules[__name__])    # in their own job (the Launch radar, mb/radar_live.json): a desk, never a light, a bar or a count
    by.update({a["id"]: a for a in ext})
    depts = []
    for key, name, col, ids in OFFICE_DEPTS + (OFFICE_BRAIN,):
        ids = [i for i in ids if i != "spotter" or i in by] + [a["id"] for a in ext if a["dept"] == key]     # the launch spotter's desk only in a run it worked in
        mem = [by.get(i) or dict(zip(("name", "job", "tools"), office_meta(i, D.get("now"))), id=i, s=None, e=None, st="absent", bg=False, out="", lines=[], waits={}, blocked=[],
                                 ran=False, open=False, secs=0.0) for i in ids]
        sts = {m["st"] for m in mem if not m.get("ext")}
        light = "failed" if "failed" in sts else ("fallback" if "fallback" in sts else ("running" if "running" in sts else ("done" if any(m["ran"] for m in mem) else "skipped")))
        word = "at work" if light == "running" else (light if light != "skipped" or "skipped" in sts else "did not run")
        depts.append({"key": key, "name": name, "col": col, "agents": mem, "light": light, "word": word,
                      "secs": sum(m["secs"] for m in mem), "n": len(mem), "nbg": sum(1 for m in mem if m["bg"])})
    peak = cur = 0
    for _, k in sorted([(a["s"], 1) for a in ags if a["ran"]] + [(a["e"] or t1, -1) for a in ags if a["ran"]]):    # an end sorts before a start at the same ms
        cur += k
        peak = max(peak, cur)
    slow = max([a for a in ags if a["ran"]], key=lambda a: a["secs"], default=None)
    pick = next((d["key"] for d in depts if slow and any(m is slow for m in d["agents"])), None) or next((d["key"] for d in depts if d["light"] != "skipped"), "ops")
    return {"t0": t0, "t1": t1, "agents": ags, "depts": depts[:-1], "brain": depts[-1], "peak": peak, "pick": pick, "mode": str(O.get("mode") or ""), "ext": ext}


def office_pts(*p):
    return " ".join("%.1f,%.1f" % xy for xy in p)


def office_desk(x, y, a):
    """One desk: the desk top, a monitor (lit in the department colour while its agent ran, red if it failed, dark if it did not run),
    the agent in front of it, and a 'beside' tag over an agent that ran in its own process beside the others."""
    scr = a["st"] if a["st"] in ("failed", "fallback") else ""
    ext, here = a.get("ext"), a["ran"] or a.get("here")          # an agent in its own job: "own job", its person while its job runs (the radar script updates it)
    out = ['<g class="desk%s" data-agent="%s"%s>' % ("" if here else " off", E(a["id"]), (' data-ext="%s"' % E(a["id"])) if ext else ""),
           '<polygon class="dks" points="%s"/>' % office_pts((x - 15, y), (x, y + 7.5), (x + 15, y), (x + 15, y + 3), (x, y + 10.5), (x - 15, y + 3)),
           '<polygon class="dk" points="%s"/>' % office_pts((x - 15, y), (x, y - 7.5), (x + 15, y), (x, y + 7.5)),
           '<rect class="mon" x="%.1f" y="%.1f" width="18" height="13" rx="1.5"/><rect class="scr %s" x="%.1f" y="%.1f" width="15" height="10" rx="1"/>' % (x - 9, y - 15, scr, x - 7.5, y - 13.5)]
    if a["ran"] or ext:
        out.append('<circle class="who" cx="%.1f" cy="%.1f" r="3.2"/><ellipse class="who" cx="%.1f" cy="%.1f" rx="5.5" ry="3.2"/>' % (x, y + 11, x, y + 17))
    if ext:
        out.append('<rect class="pill own" x="%.1f" y="%.1f" width="52" height="15" rx="7.5"/><text class="pill-t" x="%.1f" y="%.1f" text-anchor="middle">own job</text>' % (x - 26, y - 33, x, y - 22))
    elif a["bg"]:
        out.append('<rect class="pill" x="%.1f" y="%.1f" width="46" height="15" rx="7.5"/><text class="pill-t" x="%.1f" y="%.1f" text-anchor="middle">beside</text>' % (x - 23, y - 33, x, y - 22))
    return "".join(out) + "</g>"


def office_floor(info, T, width):
    """The office floor as inline SVG in CSS pixels, with one tap area per department (an HTML label over the SVG, placed in percent).
    Wide: the Brain in the middle of a ring of eight platforms, each wired to the hub at the vertex that faces it, its words on the side
    away from the wire. Narrow (phone): the Brain on top, the platforms in two columns below it, wired along a spine between the columns.
    No wire crosses any words in either layout."""
    narrow = width < 400
    depts, b = info["depts"], info["brain"]
    places = []
    if narrow:
        hw, hh, ext, step = 64, 30, 6, 21
        hx, hy, rx, ry = width / 2.0, 64, 118, 50
        top0, rowh = 134, 152           # a row: its name, the platform, two badge lines; the gap to the next row is wider than the gaps inside it
        height = top0 + rowh * ((len(depts) + 1) // 2)
        for i, d in enumerate(depts):
            x0, y0 = (i % 2) * width / 2.0, top0 + (i // 2) * rowh
            cx, cy = x0 + width / 4.0, y0 + 70
            base = cy + hh + ext
            places.append((d, (x0, y0, width / 2.0, rowh), cx, cy, ((cx + hw, cy) if i % 2 == 0 else (cx - hw, cy)), [(y0 + 24, "name"), (base + 18, "count"), (base + 34, "time")]))
        hub_cell = (0, 0, width, top0 - 4)
    else:
        hw, hh, ext, step = 80, 37, 8, 26
        cw = width / 3.0
        rows = ((0, 168), (168, 176), (344, 168))      # the words of a platform sit closer to it than to the platform above
        height = 512
        hx, hy, rx, ry = width / 2.0, 256, 98, 56
        ring = ((0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2), (0, 1))
        for i, d in enumerate(depts[:8]):
            col, row = ring[i]
            x0, (y0, ch) = col * cw, rows[row]
            cx = x0 + cw / 2
            if row == 2:
                cy = y0 + 50
                base = cy + hh + ext
                texts = [(base + 22, "name"), (base + 39, "agents"), (base + 55, "time")]
            else:
                cy = y0 + (110 if row == 0 else 116)
                pad = 0 if row == 0 else 16
                texts = [(y0 + pad + 18, "name"), (y0 + pad + 35, "agents"), (y0 + pad + 51, "time")]
            anchor = (cx + hw, cy) if col == 0 else ((cx - hw, cy) if col == 2 else ((cx, cy + hh + ext) if row == 0 else (cx, cy - hh)))
            places.append((d, (x0, y0, cw, ch), cx, cy, anchor, texts))
        hub_cell = (cw, 168, cw, 176)
    out = ['<svg class="chart-svg ofl" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="The office floor: the Brain in the middle, one platform per department">' % (
        width, height, width, height)]
    if narrow:
        out.append('<path class="wire" style="--dc:var(--accent)" d="M%.1f %.1f V%.1f"/>' % (hx, hy + ry, places[-1][3]))
        out += ['<path class="wire k-%s" style="--dc:%s" d="M%.1f %.1f H%.1f"/>' % (d["key"], d["col"], hx, cy, ax) for d, _, _, cy, (ax, _), _ in places]
    else:
        out += ['<path class="wire k-%s" style="--dc:%s" d="M%.1f %.1f L%.1f %.1f"/>' % (d["key"], d["col"], hx, hy, ax, ay) for d, _, _, _, (ax, ay), _ in places]
    for d, _, cx, cy, _, texts in places:
        out.append('<g class="plat k-%s" style="--dc:%s" data-agents="%s">' % (d["key"], d["col"], E(" ".join(a["id"] for a in d["agents"] if not a.get("ext")))))   # the live view's agents
        out.append('<polygon class="halo" points="%s"/>' % office_pts((cx, cy - hh - 7), (cx + hw + 14, cy + ext / 2), (cx, cy + hh + ext + 7), (cx - hw - 14, cy + ext / 2)))
        out.append('<polygon class="side" points="%s"/>' % office_pts((cx - hw, cy), (cx, cy + hh), (cx + hw, cy), (cx + hw, cy + ext), (cx, cy + hh + ext), (cx - hw, cy + ext)))
        out.append('<polygon class="top" points="%s"/>' % office_pts((cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)))
        n = len(d["agents"])
        for j, a in enumerate(d["agents"]):
            out.append(office_desk(cx + (j - (n - 1) / 2.0) * 2 * step, cy - 4, a))
        nb = "%d agent%s" % (n, "" if n == 1 else "s") + ((" · %d beside" % d["nbg"]) if d["nbg"] and n > 1 else (" · beside" if d["nbg"] else ""))
        nb += (" · %d own job" % sum(1 for a in d["agents"] if a.get("ext"))) if any(a.get("ext") for a in d["agents"]) else ""      # the radar (page_office.py)
        words = {"name": '<tspan class="lt %s">●</tspan> %s' % (d["light"], E(d["name"])), "agents": E(" · ".join(a["name"] for a in d["agents"])), "count": E(nb),
                 "time": E(("%s · %s" % (fmt_secs(d["secs"], True), d["word"])) if d["secs"] else d["word"])}
        for y, k in texts:
            out.append('<text class="%s" x="%.1f" y="%.1f" text-anchor="middle"%s>%s</text>' % ("oname" if k == "name" else ("omut" if k == "time" else "osub"), cx, y,
                                                                                         ' data-word=""' if k == "time" else "", words[k]))
        out.append("</g>")
    tr = b["agents"][0]
    rows_n, scans_n = int(M.num((T or {}).get("rows")) or 0), int(M.num((T or {}).get("scans")) or 0)
    out.append('<g class="plat hub k-brain" data-agents="%s">%s<ellipse class="core" cx="%.1f" cy="%.1f" rx="%d" ry="%d"/>' % (
        E(" ".join(a["id"] for a in b["agents"])), "".join('<ellipse class="glow %s" cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f"/>' % (c, hx, hy, rx * k, ry * k) for c, k in (("g3", 1.24), ("g2", 1.13), ("g1", 1.05))), hx, hy, rx, ry))
    hub_lines = [(hy - 22, "hub-t", '<tspan class="lt %s">●</tspan> THE BRAIN' % b["light"]),
                 (hy - 3, "hub-n", ("%s coin results" % fmt_int(rows_n)) if rows_n else "no training yet"),
                 (hy + 14, "osub", ("from %d scans" % scans_n) if scans_n else "it learns from scored scans"),
                 (hy + 31, "omut", "%s · %s" % (E(tr["name"]), "beside" if tr["bg"] and tr["ran"] else E(office_word(tr))))]
    out += ['<text class="%s" x="%.1f" y="%.1f" text-anchor="middle"%s>%s</text>' % (c, hx, y, (' data-word="%s · "' % E(tr["name"])) if c == "omut" else "", t) for y, c, t in hub_lines]
    out.append("</g></svg>")
    hits = [(b, hub_cell)] + [(d, cell) for d, cell, _, _, _, _ in places]
    for d, (x, y, w, h) in hits:
        tip = "%s: %s" % (d["name"], "; ".join("%s %s%s" % (a["name"], office_word(a), (" in %s" % fmt_secs(a["secs"])) if a["ran"] else "") for a in d["agents"]))
        out.append('<label class="ohit" for="od-%s" title="%s" style="left:%.3f%%;top:%.3f%%;width:%.3f%%;height:%.3f%%"><span class="sr">%s</span></label>' % (
            d["key"], E(tip), 100.0 * x / width, 100.0 * y / height, 100.0 * w / width, 100.0 * h / height, E(d["name"])))
    return "".join(out)


def office_gantt(info, width):
    """The team timeline: one lane per agent across the run, a bar from its start to its end (agents that ran beside the others in the
    second colour, a failed one in red), the time it took after the bar, minutes since the start on the axis."""
    narrow = width < 400
    rows = info["agents"]
    ml, mr, lane, mt, mb = (102, 52, 24, 4, 26) if narrow else (132, 70, 26, 4, 28)
    pw, n = width - ml - mr, len(rows)
    height = mt + lane * n + mb
    t0, t1 = info["t0"], info["t1"]
    span = (t1 - t0) / 60000.0
    X = lambda ms: ml + max(0.0, min(1.0, (ms - t0) / float(t1 - t0))) * pw
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Team timeline: when each agent worked during the last run">' % (width, height, width, height)]
    ticks, _ = clean_ticks(0, span, 3 if narrow else 6)
    for tk in ticks:
        if tk > span * 1.0001:
            continue
        x = ml + tk / span * pw
        out.append('<line class="grid" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/><text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (
            x, mt, x, mt + lane * n, x, height - 8, "%g min" % tk))
    for i, a in enumerate(rows):
        y = mt + i * lane
        out.append('<text class="label" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml - 8, y + lane / 2.0 + 4, E(a["name"])))
        if not a["ran"]:
            out.append('<text class="tick" x="%d" y="%.1f">%s</text>' % (ml + 4, y + lane / 2.0 + 4, E(office_word(a))))
            continue
        x0 = X(a["s"])
        w = max(2.0, X(a["e"] or t1) - x0)
        cls = "gbar %s%s" % ("bg" if a["bg"] else "fg", " open" if a["open"] else (" " + a["st"] if a["st"] in ("failed", "fallback") else ""))
        tip = "%s · %s · %s · %s%s" % (a["name"], ("%s to %s" % (clock(a["s"]), clock(a["e"]))) if a["e"] else "started %s" % clock(a["s"]), fmt_secs(a["secs"]), office_word(a),
                                       " · beside the others" if a["bg"] else "")
        out.append('<g data-tip="%s"><rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="14" rx="3"/></g>' % (E(tip), cls, x0, y + (lane - 14) / 2.0, w))
        out.append('<text class="tick" x="%.1f" y="%.1f">%s</text>' % (x0 + w + 6, y + lane / 2.0 + 4, fmt_secs(a["secs"], True)))
    out.append("</svg>")
    return "".join(out)


def office_latest(lines):
    """The most telling of an agent's lines: its own summary if it wrote one, else the first host it gave up on, else what it named, else its
    last warning, else its last line that is not housekeeping."""
    for pat, k in ((r"\d+ requests,", -1), (r"giving up on", 0), (r"^(Recommended|No recommendation)", 0)):
        hit = [ln for ln in lines if re.search(pat, ln)]
        if hit:
            return hit[k]
    warn = [ln for ln in lines if ln.startswith("!")]
    real = [ln for ln in lines if not re.match(r"(saved \d+ docs|report: )", ln)]
    return (warn or real or lines or [""])[-1]


def office_line(ln):
    """A progress line as a row; a warning ('! ...') gets the warning mark, a line with 'k of n' a small meter."""
    warn = ln.startswith("!")
    tx = ln.lstrip("! ") if warn else ln
    m = re.search(r"(\d[\d,]*) of (\d[\d,]*)", tx)
    k, n = (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))) if m else (0, 0)
    meter = ('<span class="m"><span class="obar"><i style="width:%.0f%%"></i></span>%s</span>' % (100.0 * k / n, pct(100.0 * k / n))) if 0 < n and k <= n else "<span></span>"
    return '<li class="oline%s"><span class="ic">%s</span><span class="tx">%s</span>%s</li>' % (" warn" if warn else "", "!" if warn else "›", E(tx), meter)


TOOL_WORDS = {   # words in an agent's progress lines that show it called a service this run (a line need not name the host)
    "GeckoTerminal": ("geckoterminal", "candles "), "Jupiter": ("jupiter", "creator check"), "Solana RPC": ("public rpc", "solana.com", "on-chain"),
    "DexScreener": ("dexscreener", "dex paid"), "news feeds": ("news ", "headlines"), "fear & greed index": ("fear & greed",), "X": (" x ", "source tweets"),
    "Telegram": ("telegram",), "StockTwits": ("stocktwits",), "CoinGecko": ("coingecko",), "CoinMarketCap": ("coinmarketcap",), "RugCheck": ("rugcheck",),
    "GoPlus": ("goplus",), "GMGN": ("gmgn",), "Reddit": ("reddit",), "Farcaster": ("farcaster",), "Mastodon": ("mastodon",), "4chan": ("4chan",),
    "pump.fun": ("pump.fun",), "Raydium": ("raydium",), "Orca": ("orca",), "LaunchLab": ("launchlab",)}


def office_tools(a):
    """The services an agent called this run as chips with their state: blocked, rate-limit waits or ok (problems first). Only a service its
    lines show it called is marked ok; the others it is wired to are named once below, without a state."""
    names = list(a["tools"])
    waits, blocked = {}, set()
    for h, k in a["waits"].items():
        t = host_tool(h)
        waits[t] = waits.get(t, 0) + k
        names += [] if t in names else [t]
    for h in a["blocked"]:
        t = host_tool(h)
        blocked.add(t)
        names += [] if t in names else [t]
    if not names:
        return "<p class=\"note\">no outside calls: it works on the bot's own files</p>"
    text = " " + " ".join(a["lines"]).lower() + " "
    seen = lambda t: t in blocked or waits.get(t) or any(w in text for w in TOOL_WORDS.get(t, (t.lower(),)))
    used = [t for t in names if a["ran"] and seen(t)]
    rest = [t for t in names if t not in used]
    rank = lambda t: 0 if t in blocked else (1 if waits.get(t) else 2)
    chips = []
    for t in sorted(used, key=rank):
        if t in blocked:
            cls, state = "bad", "blocked"
        elif waits.get(t):
            cls, state = "warn", "%d rate-limit wait%s" % (waits[t], "" if waits[t] == 1 else "s")
        else:
            cls, state = "", "ok"
        chips.append('<span class="chip %s">%s · %s</span>' % (cls, E(t), state))
    idle = ('<p class="note">%s %s</p>' % ("Wired to" if not used else "Also wired to, no line about it this run:", E(", ".join(rest)))) if rest else ""
    return ('<div class="chips">%s</div>' % "".join(chips) if chips else "") + idle


def office_pick(D, t_run):
    """The trader's output line from recommend.json: the coin it named and what happened to the paper position (with the run's time when
    the pick on the page comes from another run than this log)."""
    rc = D.get("rec") or {}
    if not rc:
        return ""
    picks = [c for c in rc.get("picks") or [] if isinstance(c, dict)]
    t_rec = M.num(rc.get("t"))
    lead = ("The pick on this page (from the run at %s)" % fmt_when(t_rec, D["now"])) if t_rec and t_run and abs(t_rec - t_run) > 120_000 else "The pick"
    if not picks:
        return "%s: none, %s" % (lead, rc.get("reason") or "nothing passed the gates")
    c, b = picks[0], picks[0].get("bought")
    tail = ("bought for %s" % fmt_eur(b)) if isinstance(b, (int, float)) and not isinstance(b, bool) else ("already held" if b == "held" else (("not bought: %s" % b) if b else ""))
    yb = [y for y in rc.get("young") or [] if isinstance(y, dict) and isinstance(y.get("bought"), (int, float)) and not isinstance(y.get("bought"), bool)]
    more = ("; %d more recommendation%s, not bought" % (len(picks) - 1, "" if len(picks) == 2 else "s")) if len(picks) > 1 else ""
    more += ("; %d new launch%s bought for %s each" % (len(yb), "" if len(yb) == 1 else "es", fmt_eur(M.YOUNG_TICKET))) if yb else ""
    return "%s: %s (score %.0f)%s%s" % (lead, c.get("sym") or "?", M.num(c.get("score")) or 0, (", " + tail) if tail else "", more)


def office_panel(d, info, D):
    """The department opened on the floor plan: its agents, each with its job, its clock times, its output and latest message, the services
    it called and its progress lines (the skills), the bar of each agent's share of the run."""
    run_s = (info["t1"] - info["t0"]) / 1000.0
    n, nbg = d["n"], d["nbg"]
    sub = "%d agent%s" % (n, "" if n == 1 else "s") + ((" · %d ran beside the others" % nbg) if nbg and n > 1 else (" · ran beside the others" if nbg else ""))
    sub += (" · %s at work" % fmt_secs(d["secs"])) if d["secs"] else ""
    parts = ['<div class="ohead"><div><span class="olab">%s</span><h3>%s</h3></div><span class="chip %s" data-st>%s</span></div><p class="note">%s</p>' % (
        "the hub" if d["key"] == "brain" else "department", E(d["name"]), OFFICE_CHIP.get(d["light"], ""), E(d["word"]), E(sub))]
    if d["key"] == "brain":
        T = D.get("train") or {}
        rows_n = int(M.num(T.get("rows")) or 0)
        parts.append('<p class="note">%s</p>' % (E("The trained model and the scored history every pick is judged with: %s coin results from %d scans%s, %s of them went to zero within %s." % (
            fmt_int(rows_n), int(M.num(T.get("scans")) or 0), (" of the last %d days" % T["days"]) if isinstance(T.get("days"), int) else "", fmt_int(T.get("zeros") or 0), horizon_text())) if rows_n else "No training yet: the Brain fills once the first scans are scored."))
        parts.append(safe("daily overview", lambda: PO.daily(D, sys.modules[__name__])))    # today's launches in one sentence and the hour bar (page_office.py)
    for a in d["agents"]:
        if a.get("ext"):          # an agent in its own job (the Launch radar): its state and its last check, not a step of this run
            parts.append(PO.ext_panel(a, sys.modules[__name__]))
            continue
        who = '<div class="who"><strong>%s</strong><span class="chip %s" data-st>%s</span>%s<span class="chip" data-lv data-live-chip="%s" hidden></span></div>' % (
            E(a["name"]), OFFICE_CHIP.get(a["st"], ""), E(office_word(a)), '<span class="chip neutral">ran beside the others</span>' if a["bg"] else "", E(a["id"]))
        who += '<p class="omsg" data-lv data-live-line="%s" hidden></p>' % E(a["id"])
        job = ('<p class="job">%s</p>' % E(a["job"])) if a["job"] else ""
        if not a["ran"]:
            parts.append('<div class="oagent" data-agent="%s">%s%s<p class="clk">%s this run</p></div>' % (E(a["id"]), who, job, "skipped" if a["st"] == "skipped" else "not needed"))
            continue
        clk = ("%s to %s %s · %s" % (clock(a["s"]), clock(a["e"]), TZ_NAME, fmt_secs(a["secs"])) if a["e"] else
               "started %s %s, never finished · %s until the run ended" % (clock(a["s"]), TZ_NAME, fmt_secs(a["secs"])))
        pick = office_pick(D, info["t0"]) if a["id"] == "trader" else ""
        latest = office_latest(a["lines"])
        lines = [office_line(ln) for ln in a["lines"]]
        more = ('<details class="fold-lite"><summary>%d more step%s</summary><ul class="olines">%s</ul></details>' % (len(lines) - 6, "" if len(lines) == 7 else "s", "".join(lines[6:]))) if len(lines) > 6 else ""
        share = 100.0 * a["secs"] / run_s if run_s else 0
        parts.append(
            '<div class="oagent" data-agent="%s">%s%s<p class="clk">%s</p>'
            '<div><span class="olab">Output</span><p class="oout">%s</p>%s</div>%s'
            '<div><span class="olab">Connected tools</span>%s</div>'
            '<div><span class="olab">Skills · %d step%s</span><div class="oshare"><span class="obar%s"><i style="width:%.1f%%"></i></span><span>%s of the run</span></div><ul class="olines">%s</ul>%s</div></div>' % (
                E(a["id"]), who, job, E(clk), E(a["out"] or "–"), ('<p class="oout">%s</p>' % E(pick)) if pick else "",
                ('<div><span class="olab">Latest message</span><p class="omsg%s">%s</p></div>' % (" warn" if latest.startswith("!") else "", E(latest.lstrip("! ") if latest.startswith("!") else latest))) if latest else "",
                office_tools(a), len(lines), "" if len(lines) == 1 else "s", " bg" if a["bg"] else "", min(100.0, share), pct(share), "".join(lines[:6]), more))
    return '<div class="card opanel k-%s">%s</div>' % (d["key"], "".join(parts))


def live_repo():
    """owner/repo of the GitHub repository the page is built in (GITHUB_REPOSITORY, set on GitHub Actions), or None: the live view of the
    agent office reads the repository's branch "live", so a page built elsewhere goes without it."""
    r = os.environ.get("GITHUB_REPOSITORY", "").strip()
    return r if re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", r) else None


def pages_url(repo):
    """The repository's GitHub Pages address: https://<owner>.github.io/<repo>/ (the owner's own <owner>.github.io repository sits at the root)."""
    owner, name = repo.split("/")
    host = owner.lower() + ".github.io"
    return "https://%s/" % host if name.lower() == host else "https://%s/%s/" % (host, name)


def office_live(info, repo, now=None, runs=None):
    """The live view's parts: the line under the header that names the website, a hidden box the script fills (the LIVE badge, the status
    strip and who is at work right now while a scan runs; after it when the last scan finished or stopped, or that the live view is
    paused) and the script. data-next-scan (the next scheduled start) times its rare polls between the scans."""
    url = pages_url(repo)
    names = json.dumps({k: office_meta(k)[0] for k in OFFICE_AGENTS if k not in PO.EXT_HOME}, separators=(",", ":"))     # the scan's agents (not the radar: its own job)
    top = ('<p class="note olink" data-lv data-live-link>Live during a scan: <a href="%s">%s</a></p>'
           '<div class="olive" data-lv data-live-src="%s" data-pages="%s" data-tz="%s" data-tzn="%s" data-run-t="%d" data-next-scan="%d" data-names="%s" hidden>'
           '<p class="olv-head" data-lv data-live-on><span class="obadge"><i></i><span data-live-badge>LIVE</span></span>'
           '<span class="note">the cards show the scan at work now; Details shows the last finished run</span></p>'
           '<div class="ostrip" data-lv data-live-on data-live-strip></div>'
           '<div data-lv data-live-on><span class="olab">Right now</span><ul class="onow" data-live-now></ul></div>'
           '<p class="note" data-lv data-live-off hidden></p></div>') % (
        E(url), E(url), E("https://api.github.com/repos/%s/contents/live.json?ref=live" % repo), E(url), "Europe/Berlin" if TZ_NAME == "Berlin" else "UTC", TZ_NAME,
        int(M.num((info or {}).get("t0")) or 0), next_scan_ms(now, runs) if now else 0, E(names))
    return top, "<script>%s</script>" % OFFICE_LIVE_JS


def office_section(D):
    """The agent office tab: the worker steps of the last run as a team at work (db/memebot/office.json, written by bot.py each cycle).
    On top the agent cards and the paper account's line (page_office.py); everything else in one Details fold, closed until opened: a
    status strip, the floor plan with the Brain in the middle, one department opened beside it (CSS only: radio + label, so the fragment
    works without scripts; the slowest agent's department opens first, a tap on a card picks another) and the team timeline. A page built
    on GitHub Actions also names the website and carries the live view, which marks the cards and the floor plan while a scan runs."""
    info = office_data(D)
    repo = live_repo()
    live_top, live_js = office_live(info, repo, D.get("now"), D.get("runs")) if repo else ("", "")
    if not info:
        return section("Agent office", "each step of the hourly scan as an agent at work · fake money", live_top +
                       '<div class="empty">No agent log yet: the first run with the new code fills this tab with what each step of the scan did, how long it took and which services it called.</div>' + live_js)
    ags, T = info["agents"], D.get("train") or {}
    run_s = (info["t1"] - info["t0"]) / 1000.0
    head = "run of %s · %s · %d agent%s%s · fake money" % (
        fmt_when(info["t0"], D["now"]), fmt_secs(run_s), len(ags), "" if len(ags) == 1 else "s", (" · up to %d at work at once" % info["peak"]) if info["peak"] > 1 else "")
    count = lambda f: sum(1 for a in ags if f(a))
    cells = [("All", len(ags), ""), ("Done", count(lambda a: a["st"] == "done"), ""), ("Ran beside", count(lambda a: a["bg"]), ""),
             ("Failed", count(lambda a: a["st"] == "failed"), "bad"), ("Skipped", count(lambda a: a["st"] == "skipped"), "")]
    if count(lambda a: a["st"] == "running"):
        cells.insert(2, ("At work", count(lambda a: a["st"] == "running"), ""))
    nfb = count(lambda a: a["st"] == "fallback")
    if nfb:
        cells.insert(2, ("Fallback", nfb, ""))
    strip = '<div class="ostrip" data-lv data-static-strip>%s</div>' % "".join('<span class="%s">%s <b>%d</b></span>' % (c if k else "", E(lab), k) for lab, k, c in cells)
    note = "The run of %s%s, %s from its start to this page. Each department is one step of the scan, the Brain in the middle is the trained model and the scored history. Tap a department to see what its agents did." % (
        fmt_when(info["t0"], D["now"]), (", " + OFFICE_MODE[info["mode"]]) if info["mode"] in OFFICE_MODE else "", fmt_secs(run_s))
    every = info["depts"] + [info["brain"]]
    home = {m["id"]: d["name"] for d in every for m in d["agents"]}
    radios = "".join('<input type="radio" name="odept" id="od-%s"%s aria-label="%s">' % (d["key"], " checked" if d["key"] == info["pick"] else "", E(d["name"])) for d in every)
    legend = ('<div class="legend olegend"><span style="--c:var(--good-mark)">done</span><span style="--c:var(--accent)">at work</span><span style="--c:var(--warn-mark)">fallback</span><span style="--c:var(--bad-mark)">failed</span>'
              '<span style="--c:var(--muted)">skipped</span><span class="ob">beside: ran in its own process, at the same time as the others</span>%s</div>') % (
        '<span class="oj">own job: one quick round after each scan, not inside it</span>' if info.get("ext") else "")     # the Launch radar (page_office.py)
    floor = '<div class="chart omap"><div class="wide"><div class="ofloor">%s</div></div><div class="narrow"><div class="ofloor">%s</div></div>%s</div>' % (
        office_floor(info, T, OFFICE_W), office_floor(info, T, NARROW), legend)
    panels = '<div class="opanels">%s</div>' % "".join(office_panel(d, info, D) for d in every)
    nfail = count(lambda a: a["st"] == "failed")
    g_leg = '<div class="legend"><span style="--c:var(--s1)">in turn</span><span style="--c:var(--s2)">beside the others</span>%s</div>' % (
        '<span style="--c:var(--bad-mark)">failed</span>' if nfail else "")
    table = '<details><summary>Table view</summary><div class="tbl stack"><table><thead><tr><th>agent</th><th>department</th><th>start</th><th>end</th><th class="n">took</th><th>status</th><th>result</th></tr></thead><tbody>%s</tbody></table></div></details>' % "".join(
        '<tr><td><strong>%s</strong></td><td class="d" data-k="department">%s</td><td class="d" data-k="start">%s</td><td class="d" data-k="end">%s</td><td class="n" data-k="took">%s</td><td class="d" data-k="status">%s</td><td>%s</td></tr>' % (
            E(a["name"]), E(home.get(a["id"], "–")), clock(a["s"]), clock(a["e"]),
            fmt_secs(a["secs"]) if a["ran"] else "–", E(office_word(a) + (", beside the others" if a["bg"] else "")), E(a["out"] or "–")) for a in ags)
    timeline = '<h3>Team timeline</h3><p class="note">minutes since the run started at %s · one lane per agent, so you see who worked at the same time</p>%s%s' % (
        E(clock(info["t0"]) + " " + TZ_NAME), chart_box(office_gantt(info, WIDE), office_gantt(info, NARROW), g_leg), table)
    # on top (page_office.py): the agent cards and the paper account's line; the rest of the office in one fold, closed until opened (a tap
    # on a card opens it); without page_office.py there are no cards, so the fold stands open
    if (M.num(D.get("now")) or 0) >= M.switch_at():   # the new launches ended at the switch: no Launch spotter card any more
        info = dict(info, agents=[a for a in info["agents"] if a.get("id") != "spotter"])
    cards = safe("agent cards", lambda: PO.cards(info, sys.modules[__name__]))
    top = '<div class="otop">%s</div>' % cards if cards else ""      # the paper account's line is on the Traders tab, not here (a duplicate)
    inner = '<div class="ofold-in">%s<p class="note">%s</p><div class="office">%s<div class="ogrid">%s%s</div></div><div>%s</div></div>' % (strip, E(note), radios, floor, panels, timeline)
    details = '<details class="fold ofold" data-po-fold%s><summary><span class="t">Details</span><span class="sum">floor plan, timeline, daily overview</span></summary>%s</details>' % (
        "" if cards else " open", inner)
    body = '%s%s%s%s%s' % (("<style>%s</style>" % PO.CSS) if PO.CSS else "", live_top, top, details, live_js)
    return section("Agent office", head, body, info=True)      # the run's line behind the ⓘ: the cards say the rest


def render(data, fragment=False):
    D = data
    st, cash, now = D["state"], D["cash"], D["now"]
    equity = D["equity"]
    nb = len(D["bot_closed"])
    best = max(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    worst = min(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    scored = sum(g["n"] for g in D["big"])
    worth_now = sum(r["value"] or 0 for r in D["open_bot"])
    rec_mode = bool(D.get("rec")) and not D["pos"]        # recommend mode before its first paper position: the bankroll sections fold
    hz = horizon_text()
    D["snap_t"] = D["scan_t"] or M.num(st.get("bigSnapT")) or 0        # the last saved snapshot: the docs if synced, else the state's note of it
    D["snap_n"] = D["scan_n"] or M.num(st.get("bigSnapN")) or 0
    first_result = fmt_dt(D["snap_t"] + M.EVAL_H * 3_600_000, True) if D["snap_t"] else None
    eq_sub = "fake money · started with %s" % fmt_amt(cash["budget"])
    if D["unpriced"]:
        eq_sub += " · %d open position%s with no price yet, counted at 0" % (len(D["unpriced"]), "" if len(D["unpriced"]) == 1 else "s")

    def hero():
        tiles = [tile("Equity if everything were sold now", fmt_amt(equity), eq_sub, lead=True, delta=equity - cash["budget"]),
                 tile("Free in the bankroll", fmt_amt(cash["free"]), "%d free slot%s of %s each" % (cash["slots"], "" if cash["slots"] == 1 else "s", fmt_amt(cash["ticket"]))),
                 tile("Deployed (at cost)", fmt_amt(cash["deployed"]), "%d open position%s · worth %s now" % (cash["open"], "" if cash["open"] == 1 else "s", fmt_amt(worth_now)) if cash["open"] else "no open position")]
        if nb == 0:
            tiles.append(tile("Closed trades", "0", "none yet"))
        elif nb == 1:
            tiles += [tile("Closed trades", "1", "%d won · %d lost" % (D["wins"], nb - D["wins"])), tile("Only closed trade", fmt_amt(best["pnl"], True), best["p"].get("sym"))]
        else:
            tiles += [tile("Closed trades", str(nb), "%d won · %d lost" % (D["wins"], nb - D["wins"])),
                      tile("Best / worst trade", "%s / %s" % (fmt_amt(best["pnl"], True), fmt_amt(worst["pnl"], True)), "%s / %s" % (best["p"].get("sym"), worst["p"].get("sym")))]
        tiles.append(tile("Big test", ("%d scan%s" % (len(D["big"]), "" if len(D["big"]) == 1 else "s")) if scored else "–",
                          ("%d coin results after %s, %d different coins" % (scored, hz, D["seen_coins"])) if scored else ("first result ~%s" % first_result if first_result else "after the first scan")))
        html_ = '<section class="hero">%s</section>' % "".join(tiles)
        if rec_mode:
            return fold("Paper bankroll", "%s · untouched · nothing bought, nothing sold" % fmt_amt(equity), html_)
        return html_

    def curve():
        docs = [c for c in D["curve"] if isinstance(c, dict) and M.num(c.get("t"))]
        pts_bot = [(M.num(c["t"]), M.num(c.get("equity")) if M.num(c.get("equity")) is not None else cash["budget"] + (M.num(c.get("bot")) or 0)) for c in docs]
        series = [("bot", "s1", pts_bot)]
        if any((M.num(c.get("nRand")) or 0) > 0 for c in docs):
            series.append(("random control", "s2", [(M.num(c["t"]), cash["budget"] + (M.num(c.get("rand")) or 0)) for c in docs]))
        wide = line_chart(series, cash["budget"], WIDE)
        if not wide:
            body = '<div class="empty">The curve needs two runs. It shows the bankroll plus the value of the open positions after every run.</div>'
        else:
            legend = '<div class="legend"><span style="--c:var(--s1)">bot</span><span style="--c:var(--s2)">random control</span></div>' if len(series) > 1 else ""
            body = chart_box(wide, line_chart(series, cash["budget"], NARROW), legend)
            body += ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>run</th><th class="n">equity</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (
                '<th class="n">random control</th>' if len(series) > 1 else "",
                "".join('<tr><td>%s</td><td class="n">%s</td>%s</tr>' % (fmt_dt(t), fmt_amt(v), ('<td class="n">%s</td>' % fmt_amt(series[1][2][i][1])) if len(series) > 1 and i < len(series[1][2]) else "") for i, (t, v) in enumerate(pts_bot))))
        sub = "bankroll plus what the open positions would fetch, after fees · now %s" % fmt_amt(equity)
        if rec_mode:
            flat = pts_bot and all(abs(v - pts_bot[0][1]) < 0.005 for _, v in pts_bot)
            summary = ("flat at %s since %s" % (fmt_amt(equity), fmt_dt(pts_bot[0][0], True))) if flat else ("%s now · %s since start" % (fmt_amt(equity), fmt_amt(equity - cash["budget"], True)))
            return fold("Equity per run", summary, '<section><p class="note">%s</p>%s</section>' % (E(sub), body))
        return section("Equity per run", sub, body)

    def bought():
        n_bot, n_rand = len(D["open_bot"]), len(D["open"]) - len(D["open_bot"])
        head = "%d open%s · %s per coin" % (n_bot, (" plus %d random control" % n_rand) if n_rand else "", fmt_amt(cash["ticket"]))
        rule = '<details><summary>How a coin is sold</summary><p class="note">%s</p></details>' % (E(hold_rule_text(D.get("now"))) if D.get("rec") else
                "Half is sold at 2x (the rest if it falls back to the entry price); everything is sold at −50%, after 3 days, or when the price is gone.")
        if D["open"]:
            body = '<div class="cards">%s</div>' % "".join(hold_card(r, now) if r["p"].get("grp") in M.PAPER_GROUPS else position_card(r, now) for r in D["open"])
        elif rec_mode:
            body = '<div class="empty">No open positions: nothing has been bought yet; every scan buys its top pick and the first new launches.</div>'
        elif D.get("rec"):
            body = '<div class="empty">No open positions: the coins bought earlier are sold (see Closed trades); the next scan buys its top pick and new launches.</div>'
        else:
            body = '<div class="empty">No open positions. %s</div>' % ("The next pick run buys the two best coins when the bankroll has a free slot." if D["runs"] else "Run <code>python3 bot.py cycle</code> to start.")
        if rec_mode:
            return fold("Bought coins", "none yet", '<section><p class="note">%s</p>%s%s</section>' % (E(head), body, rule))
        if D.get("rec"):        # one line until tapped: the open positions can fill several phone screens (their count and value are in the header)
            return ('<details class="fold-lite pa-f opos" data-pa="open"><summary>Open positions (%d)</summary>' % len(D["open"])
                    + body.replace('<div class="cards">', '<div class="holds">', 1) + rule + '</details>')
        return section("Bought coins", head, body + rule)

    def closed(inline=False):
        if inline:        # the paper account: the trades since the restart, the ones before it behind their own fold
            new, old = D["paper"]["closed"], D["paper"]["old"]
            html_ = '<details class="fold-lite"><summary>Closed trades (%d) · what came back after fees</summary>%s</details>' % (len(new), safe("closed trades", lambda: closed_fold(new)))
            if old:
                note = ("bought before the paper account restarted on %s; not counted above" % fmt_dt(D["paper"]["since"], True)) if D["paper"]["since"] else \
                    "bought before the paper account restarted; not counted above"
                html_ += '<details class="fold-lite"><summary>Before the restart (%d trade%s)</summary>%s</details>' % (
                    len(old), "" if len(old) == 1 else "s", safe("closed trades", lambda: closed_fold(old, note)))
            return html_
        body = safe("closed trades", lambda: closed_table(D["closed"]))
        if rec_mode:
            return fold("Closed trades", "none yet", '<section><p class="note">what came back after fees, newest first</p>%s</section>' % body)
        return section("Closed trades", "what came back after fees, newest first", body)

    def candidates():
        if D["scan_t"]:
            head = "%s · %s coins scanned · ranked among those that passed the gates" % (fmt_dt(D["scan_t"]), fmt_int(D["scan_n"] or 0))
            run = D["scan_run"]
            if rec_mode:
                head += " · nothing bought: recommend mode, the best clean coin is shown at the top of the page"
            elif D.get("rec"):
                nb = [p for p in ((run or {}).get("picks") or []) if isinstance(p, dict) and p.get("grp") == "recommend" and isinstance(p.get("bought"), (int, float)) and not isinstance(p.get("bought"), bool)]
                head += (" · %d of the named coins bought as a paper position" % len(nb)) if nb else " · the named coin is shown at the top of the page, nothing new bought from this scan"
            elif run:
                n_b = len([p for p in (run.get("picks") or []) if isinstance(p, dict) and p.get("grp") == "pick"])
                head += (" · %d bought from it" % n_b) if n_b else (" · nothing bought: this was a check run (no free slot, or a pick less than 3 h earlier)" if run.get("mode") == "check" else " · nothing bought: no top coin had a clean safety report")
        else:
            head = "no full scan yet"
        inner = '<section><p class="note">%s</p>%s</section>' % (E(head), cands_table(D))
        return fold("All coins that passed the gates", ("%d of %s scanned" % (len(D["cands"]), fmt_int(D["scan_n"] or 0))) if D["scan_t"] else "no full scan yet", inner)

    def runlog():
        detail = ('<details><summary>Last run in detail</summary><p class="note">%s</p></details>' % E(st["note"])) if st.get("note") else ""
        inner = '<section>%s%s</section>' % (safe("run log", lambda: runs_table(D["runs"], rec_mode)), detail)
        n_runs = int(M.num(st.get("runs")) or len(D["runs"]))
        return fold("Run log", "last %d of %d run%s" % (min(12, len(D["runs"])), n_runs, "" if n_runs == 1 else "s"), inner)

    last_run = st.get("lastRun")
    # the full scan's strip on the Pick tab (page_office.py) is the one place for the next start and Scan now; the header says when the page
    # was updated, and the next start only on a page without the strip
    strip_html = safe("scan strip", lambda: PO.scan_strip(D, sys.modules[__name__])) if D.get("rec") else ""
    nxt = (" · next scan starts about %s" % fmt_when(next_scan_ms(now, D["runs"]), now)) if D.get("rec") and not strip_html else ""
    head = ('<header><div><div class="eyebrow">fake money only · no real trades</div><h1>%s</h1></div>'
            '<div class="meta">updated %s%s</div></header>') % (E(TITLE), E(fmt_when(last_run, now)), E(nxt))
    body = [head]
    if D.get("rec"):
        # four tabs, the same in the installed app (app.py PAGE_JS: its bottom bar) and on the website: Pick (the full scan's strip, the pick, the
        # hour grid and one Details fold: the tip record first, then the reference sections), Radar (the launch radar and its paper positions; until
        # the switch the full scan's new launches under it), Traders (the three paper traders, page_traders.py) and Office (the radar's desk, the agent
        # office). CSS-only, so the fragment works without scripts; nothing of the account sits outside the panes. The old links (#tab-radar,
        # #radar, #new) open Radar (page_radar.py's script; app.py PAGE_JS in the installed app)
        # five tabs (the user's direction of Oct 22: two parts, PICK and RADAR, and everything else in an archive): Start (page_home.py: both
        # paper accounts side by side, the pick and the rocket candidates), Pick (the full scan's strip, the pick, the hour grid), Radar (the
        # rocket hunter, then the launch radar and its paper positions), Brain (page_brain.py, then the radar's desk and the agent office) and
        # Archive (research and the three paper traders: nothing deleted, only out of the way). The tab ids stay (young is Radar, office is
        # Brain, account is Archive) so the old links and notifications still open the right place. All words in English since Oct 22.
        sw = M.switch_at()
        rest = [safe("forecast", lambda: forecast_section(D)) if FC else "", safe("profit", lambda: profit_section(D)), safe("training", lambda: train_section(D)),
                (safe("filter team", lambda: FT.section(D, sys.modules[__name__])) if FT else
                 section("Coin test: %s later" % hz, "what 20 € in each scanned coin was worth %s later, after fees" % hz, safe("big test", lambda: big_section(D)))),
                safe("filter search", lambda: search_block(D)), safe("winners vs losers", winlose_block),
                safe("candidates", candidates), safe("weights", lambda: weights_section(D))]
        if D["runs"]:
            rest.append(safe("run log", runlog))
        details = fold("Research", "forecast, tip record, training, filter team, filter search, winners vs losers, candidates, run log", '<div class="rest">%s</div>' % "\n".join(x for x in rest if x))
        pane_pick = (strip_html + (safe("pick account", lambda: PH.pick_account(D, sys.modules[__name__])) if PH else "")
                     + safe("recommendations", lambda: rec_section(D, embed=not fragment)) + safe("history", lambda: history_section(D))
                     + tests_block(safe("shadow rules", lambda: shadow_block(D)) + safe("learning pick", lambda: lernpick_block(D))))
        PT = traders_page()
        legacy = safe("new launches", lambda: young_section(D, "New launches (until %s)" % local(sw).strftime("%b %d"))) if now < sw else ""
        # the launch radar's old paper positions (10 € on every coin without traps) left the Radar tab on Oct 23: their account is off since Oct 22
        # (scan.yml MEMEBOT_TRADERS), so the list only grew rows stuck at "waiting for a price" and read as Radar buys next to the Radar account's 0;
        # every one of those trades is still in Archive > Three paper traders
        pane_young = safe("rocket hunter", lambda: rocket_block(D)) + safe("launch radar", lambda: PR.block(D)) + legacy
        if rec_mode:      # before the first paper position the traders hold one sentence
            traders_html = '<div class="empty">No paper trades yet: each scan\'s pick is bought on paper for %s and every radar coin found without traps for %s (fake money, nothing is bought for real).</div>' % (
                E(fmt_eur(M.TOP_TICKET)), E(fmt_eur(radar_ticket())))
        elif PT:
            traders_html = safe("traders", lambda: PT.section(D, bought))
        else:             # page_traders.py missing: the plain account strip as before, with a note; the rest of the page is unaffected
            traders_html = ('<p class="note">The three traders could not be loaded this time (%s). The paper account itself is unaffected.</p>' % E(TRADERS_ERR[0])
                            + safe("account", lambda: dash_section(D)) + safe("open positions", bought) + safe("closed trades", lambda: closed(True)) + safe("account curve", lambda: paper_curve(D)))
        # the old office (the radar's desk and its chat, the agent cards, the floor plan, the timeline, the daily overview): out of the Brain
        # tab since Oct 22 (the brain shows the helpers, their results and the decisions), kept whole in the archive; its live script still
        # feeds the brain (it polls while Brain, Radar or Archive is open)
        old_office = ('<details class="fold arch-office"><summary><span class="t">Old office (every detail)</span><span class="sum">launch radar desk, '
                      'helper cards, floor plan, timeline, daily overview</span></summary><div class="rest">%s%s</div></details>' % (
                          safe("radar desk", lambda: PO.desk(D, sys.modules[__name__])), safe("agent office", lambda: office_section(D))))
        pane_account = (ARCHIVE_HEAD + details + old_office
                        + '<details class="fold arch-tr"><summary><span class="t">Three paper traders (comparison)</span><span class="sum">stop-loss, best price in hindsight, learning · '
                          'with the new launches (ended %s)</span></summary>%s</details>' % (E(local(sw).strftime("%b %d")), traders_html))
        pane_office = (safe("brain", lambda: PB.section(D, sys.modules[__name__])) if PB else "")
        pane_home = safe("start", lambda: PH.section(D, sys.modules[__name__])) if PH else ""
        radios = "".join('<input type="radio" name="tab" id="tab-%s"%s>' % (k, " checked" if k == TABS[0] else "") for k in TABS)
        labels = ('<label for="tab-home" role="tab">Start</label><label for="tab-pick" role="tab">Pick</label><label for="tab-young" role="tab"><span>Radar</span>%s</label>'
                  '<label for="tab-office" role="tab">Brain</label><label for="tab-account" role="tab">Archive</label>') % PR.tab_label()
        body.append('<style>%s</style><div class="tabs">%s<div class="tabbar" role="tablist">%s</div><div class="pane" id="pane-home" data-app="home">%s</div><div class="pane" id="pane-pick">%s</div>'
                    '<div class="pane" id="pane-young">%s</div><div class="pane" id="pane-office">%s</div>'
                    '<div class="pane" id="pane-account" data-app="account" data-tk-pick="%s" data-tk-radar="%s">%s</div></div><script>%s</script>' % (
                        PR.CSS, radios, labels, pane_home, pane_pick, pane_young, pane_office, E(fmt_eur(M.TOP_TICKET)), E(fmt_eur(radar_ticket())), pane_account, PR.JS))
    else:
        rest = [section("Big test: %s later" % hz, "what 20 in each scanned coin was worth %s later, after fees" % hz, safe("big test", lambda: big_section(D))),
                safe("hero", hero), safe("equity curve", curve), safe("bought coins", bought), safe("closed trades", closed), safe("candidates", candidates)]
        w_html = safe("weights", lambda: weights_section(D))
        if w_html:
            rest.append(w_html)
        if D["runs"]:
            rest.append(safe("run log", runlog))
        body += [x for x in rest if x]
    body.append('<footer><span>generated %s</span><span class="ift">rule %s · %s profile %s</span></footer>' % (
        E(fmt_dt(now)), E(st.get("rule") or M.RULE), E(M.HORIZON), info_i('<p>fees simulated at 0.5%%, minimum 0.81 per trade (paper account: 1%%, minimum 0.10)</p>'
                                                                         '<p>prices from DexScreener at the time of each run</p><p>times in %s</p>' % TZ_NAME, "Fees, prices and times")))
    content = '<div class="wrap">%s</div>\n<script>%s</script>' % ("\n".join(body), JS)
    head_html = ('<title>%s</title>\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">\n'
                 '<style>%s</style>') % (E(TITLE), CSS + THEME_CSS + (EARLY_CSS if live_repo() and D.get("rec") and now < M.switch_at() else ""))
    if fragment:
        return head_html + "\n" + content
    return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n%s\n</head>\n<body>\n%s\n</body>\n</html>\n' % (head_html, content)


def build(d, out=None, now=None, fragment=False, horizon=None):
    st0 = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    M.apply_profile(horizon or st0.get("horizon") or "24h")       # the page reads the same rules the bot ran with
    now = int(now or dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    last = M.num((M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}).get("lastRun"))
    now = max(now, int(last)) if last else now      # a db written with a fake clock (tests) must not show negative ages
    page = render(collect(d, now), fragment)
    out = out or os.path.join(d, "report.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--out", default=None)
    ap.add_argument("--now", type=float, default=None)
    ap.add_argument("--fragment", action="store_true")
    ap.add_argument("--horizon", default=None)
    a = ap.parse_args()
    print(build(a.dir, a.out, a.now, a.fragment, a.horizon))


if __name__ == "__main__":
    main()
