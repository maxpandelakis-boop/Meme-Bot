#!/usr/bin/env python3
"""report.py: the analysis page. Renders everything in db/ as one self-contained HTML file (mb/report.html).

  python3 report.py [--dir mb] [--out mb/report.html] [--fragment]

bot.py writes it after every cycle, so the page is always the state after the last run. Open it in a browser (it is a plain
file, no server needed). --fragment leaves out the <html>/<head>/<body> wrapper for hosts that add their own.

Sections, in reading order: the recommendation (recommend mode), the big test (how the gated coins, the bot's top 10 and the rest
did against the "price unchanged" baseline), bankroll and equity (hero), equity curve per run, the bought coins (open positions with
their last price, sell levels and the bot's reasons), closed trades with their result, the top candidates of the last full scan and
why they were not bought, the factor weights in use (with a glossary) and the run log. In recommend mode the bankroll sections and
the reference sections fold behind a tap. Times are shown in Europe/Berlin, the bot's own trading day.
"""
import argparse, html, json, math, os, re, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M

TITLE = "Meme-Bot Ledger"
E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
try:
    from zoneinfo import ZoneInfo
    TZ, TZ_NAME = ZoneInfo("Europe/Berlin"), "Berlin"
except Exception:   # no tz database: fall back to UTC
    TZ, TZ_NAME = dt.timezone.utc, "UTC"
WIDE, NARROW = 1052, 324          # chart widths in CSS px: the desktop column and the phone card's inner width at 390px (nothing scrolls)
MINUS = "\u2212"                  # a real minus sign for every negative number on the page
_flat = M.TICKET - M.fee(M.TICKET)
FLAT = round(max(0.0, _flat - M.fee(_flat)) - M.TICKET, 2)   # what 20 becomes when the price does not move: the two fees
WHY = {"target": "hit 2x, half sold", "stop": "−50% stop", "time": "3-day limit", "back to entry": "fell back to entry", "rug": "price gone", "manual": "sold by hand",
       "tp": "take-profit +%d%%" % round(100 * M.HOLD_TP), "filters": "failed the filters"}
GATE_SHORT = {"crash": "crashed", "spike": "spiked", "mc": "market cap out of range", "liq": "liquidity gone", "vol": "volume dried up", "wash": "wash trading",
              "old": "too old", "honeypot": "honeypot"}


def exit_label(e, grp=None):
    """Why a sale happened, in words: the filters a held coin failed are named; a held coin's time limit is HOLD_MAX_H, not 3 days."""
    w = str(e.get("why") or "?")
    if w == "filters" and e.get("gates"):
        return "failed the filters (%s)" % ", ".join(GATE_SHORT.get(g, g) for g in e["gates"])
    if w == "time" and grp == "hold":
        return "%d-hour limit" % round(M.HOLD_MAX_H)
    return WHY.get(w, w)


def hold_rule_text():
    return ("One paper position per named coin, paid from the bankroll while a slot is free (at most %d at once); a coin named again while it is held buys nothing. "
            "All of it is sold the first minute a candle closes %d%% above the entry, the first scan the coin fails a filter (%s), or after %d hours. "
            "A coin sold is not bought again for %d hours." % (int(M.BUDGET // M.TICKET), round(100 * M.HOLD_TP), ", ".join(GATE_SHORT.get(g, g) for g in M.HOLD_EXIT_GATES),
                                                                round(M.HOLD_MAX_H), round(M.HOLD_COOL_H)))
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


def be_mult(ticket):
    """The price multiple at which a paper position comes back at its ticket after both fees (buy and sell)."""
    ticket = M.num(ticket) or M.TICKET
    net = ticket - M.fee(ticket)
    if net <= 0:
        return None
    gross = ticket
    for _ in range(30):                  # gross - fee(gross) = ticket, solved by fixed-point iteration (the fee is flat or 0.5%)
        gross = ticket + M.fee(gross)
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
def collect(d, now):
    pos = M.positions(d)
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    curve = sorted(M.load_docs(d, "memecurve").values(), key=lambda c: M.num(c.get("t")) or 0)
    runs = sorted(M.load_docs(d, "memeruns").values(), key=lambda r: -(M.num(r.get("t")) or 0))
    snaps = M.load_docs(d, "memesnap")
    res = M.load_docs(d, "memesnapres")
    cash = M.bankroll(pos)
    px, liq_now, cpx = marks.get("px") or {}, marks.get("liq") or {}, marks.get("cpx") or {}

    rows = []
    for pid, p in pos.items():
        ticket, entry = M.num(p.get("ticket")) or M.TICKET, M.num(p.get("px"))
        exits = [e for e in p["_exits"] if isinstance(e, dict)]
        back = sum(M.num(e.get("eur")) or 0 for e in exits)
        last = M.num(px.get(pid))
        if last is None and p["_left"] <= 1e-9 and exits:
            last = M.num(exits[-1].get("px"))
        value = None
        if p["_left"] > 1e-9 and last and entry:
            gross = (ticket - M.fee(ticket)) * p["_left"] * last / entry
            value = max(0.0, gross - M.fee(gross))
        closed = p["_left"] <= 1e-9
        pnl = back - ticket if closed else (back + (value or 0) - ticket if value is not None else None)
        whys = [str(e.get("why") or "?") for e in exits]
        half = any(w == "target" for w in whys)
        if closed:
            status, kind = ", ".join(exit_label(e, p.get("grp")) for e in exits), ("good" if pnl > 0 else "bad")
        elif half:
            status, kind = "half sold at 2x", "good"
        else:
            status, kind = "open", "neutral"
        sold_at = [(M.num(e.get("px")) / entry if M.num(e.get("px")) and entry else None, (M.num(e.get("frac")) or 1) < 0.999) for e in exits]
        cands = []
        if p.get("grp") == "hold" and not closed and p.get("pair"):     # the held coin's minute candles since the entry (the run that renders the page has them)
            t_in = M.num(p.get("entryAt")) or M.num(p.get("t")) or 0
            cands = [c for c in M.load_candles(d, str(p["pair"]), "hold") if c[0] >= t_in - 60_000 and c[4] > 0]
        rows.append({"id": pid, "p": p, "ticket": ticket, "entry": entry, "back": back, "last": last, "value": value, "closed": closed, "half": half,
                     "pnl": pnl, "status": status, "kind": kind, "mult": (last / entry) if last and entry else None, "sold_at": sold_at,
                     "liq_now": M.num(liq_now.get(pid)), "exit_t": M.num(exits[-1].get("t")) if closed and exits else None, "bot": p.get("grp") in M.BOT_GROUPS,
                     "candles": cands, "cpx": M.num(cpx.get(pid)) or (cands[0][4] if cands else None)})
    rows.sort(key=lambda r: -(M.num(r["p"].get("t")) or 0))
    open_rows = [r for r in rows if not r["closed"]]
    closed_rows = [r for r in rows if r["closed"]]
    open_bot = [r for r in open_rows if r["bot"]]
    unpriced = [r for r in open_bot if r["value"] is None]
    equity = cash["free"] + sum(r["value"] or 0 for r in open_bot)
    bot_closed = [r for r in closed_rows if r["bot"]]
    wins = sum(1 for r in bot_closed if r["pnl"] > 0)

    # big test: chunks of the same snapshot run -> one group
    groups = {}
    for sid, r in res.items():
        if not isinstance(r, dict):
            continue
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
    avg = lambda xs: (sum(xs) / len(xs)) if xs else None
    big = []
    for key, g in sorted(groups.items(), key=lambda kv: kv[1]["t0"] or 0):
        big.append({"key": key, "t0": g["t0"], "t": g["t"], "n": g["n"], "passN": len(g["pass"]), "passAvg": avg(g["pass"]), "topN": len(g["top"]),
                    "topAvg": avg(g["top"]), "failN": len(g["fail"]), "failAvg": avg(g["fail"]), "up": g["up"], "gone": g["gone"]})
    seen_coins = {str(c.get("a")) for r in res.values() if isinstance(r, dict) for c in (r.get("coins") or []) if isinstance(c, dict)}

    # the last full scan: its top candidates and the run that made it
    last_t = max([M.num(s.get("t")) or 0 for s in snaps.values() if isinstance(s, dict)] or [0])
    cands = []
    if last_t:
        for s in snaps.values():
            if isinstance(s, dict) and (M.num(s.get("t")) or 0) == last_t:
                cands += [c for c in (s.get("coins") or []) if isinstance(c, dict) and M.num(c.get("rank"))]
        cands.sort(key=lambda c: M.num(c["rank"]))
    scan_run = next((r for r in runs if isinstance(r, dict) and M.num(r.get("t")) == last_t), None) if last_t else None
    held_addrs = {r["p"].get("addr") for r in open_rows}
    ever_addrs = {r["p"].get("addr") for r in rows}
    w, winfo = M.blended_weights(d)
    weights = sorted(w.items(), key=lambda kv: (-abs(kv[1]), kv[0]))[:16]
    rec = M.load_json(os.path.join(d, "db", "memebot", "recommend.json"), None)
    track = sorted([r for r in M.load_docs(d, "memerec").values() if isinstance(r, dict)], key=lambda r: -(M.num(r.get("t")) or 0))
    young_hist = sorted([r for r in M.load_docs(d, "memeyoung").values() if isinstance(r, dict)], key=lambda r: -(M.num(r.get("t")) or 0))[:48]
    train = M.load_json(os.path.join(d, "db", "memebot", "train.json"), None)
    return {"now": now, "rec": rec if isinstance(rec, dict) else None, "track": track[:80], "track_all": track, "young_hist": young_hist, "train": train if isinstance(train, dict) else None, "pos": rows, "open": open_rows, "open_bot": open_bot, "unpriced": unpriced, "closed": closed_rows, "cash": cash, "equity": equity, "state": state,
            "curve": curve, "runs": runs, "big": big, "seen_coins": len(seen_coins), "cands": cands[:15], "scan_t": last_t, "scan_run": scan_run,
            "scan_n": sum(M.num(s.get("n")) or 0 for s in snaps.values() if isinstance(s, dict) and (M.num(s.get("t")) or 0) == last_t),
            "held": held_addrs, "ever": ever_addrs, "weights": weights, "winfo": winfo, "detail": winfo.get("detail") or {}, "wins": wins, "bot_closed": bot_closed}




# ---------------------------------------------------------------- charts (inline SVG in CSS pixels; a wide and a narrow variant per chart)
def line_chart(series, budget, width, height=240, ref_label="start", aria_label="Equity per run"):
    """series: [(name, css class, [(t, v)])]. Hover: crosshair + tooltip via the page script (data-pts on the overlay)."""
    pts_all = [(t, v) for _, _, pts in series for t, v in pts]
    if len(pts_all) < 2:
        return ""
    narrow = width < 400
    ml, mr, mt, mb = (46, 52, 14, 28) if narrow else (44, 72, 14, 28)
    pw, ph = width - ml - mr, height - mt - mb
    t0, t1 = min(t for t, _ in pts_all), max(t for t, _ in pts_all)
    if t1 == t0:
        t1 = t0 + 1
    lo, hi, ticks = domain([v for _, v in pts_all] + [budget])
    step = (ticks[1] - ticks[0]) if len(ticks) > 1 else 1
    tick_fmt = fmt_amt if step < 1 else (lambda v: sgn("%g" % v))
    X = lambda t: ml + (t - t0) / (t1 - t0) * pw
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, width, height, E(aria_label))]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml, y, ml + pw, y, ml - 6, y + 4, tick_fmt(tk)))
    yb = Y(budget)
    out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (ml, yb, ml + pw, yb))
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
        ends.append([X(tl) + 8, Y(vl) + 4, vl])
    ends.sort(key=lambda e: e[1])
    for i in range(1, len(ends)):          # end labels that would collide are pushed apart (the legend names the series)
        if ends[i][1] - ends[i - 1][1] < 13:
            ends[i][1] = ends[i - 1][1] + 13
    for x, y, v in ends:
        out.append('<text class="label" x="%.1f" y="%.1f">%s</text>' % (x, y, fmt_amt(v)))
    data = [{"x": round(X(t), 1), "t": fmt_dt(t), "v": [(name, round(v, 2)) for name, _, pts in series for tt, v in pts if tt == t]} for t in sorted({t for t, _ in pts_all})]
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


# ---------------------------------------------------------------- page
CSS = r"""
/* Layout: one 1100px column read top to bottom. Phone first: at 390px everything fits in a 16px gutter, charts are drawn at the
   card's inner width (no scrolling inside cards) and the reference sections fold behind a tap. Colours are tokens on :root. */
:root { --bg:#f5f6f8; --surface:#ffffff; --fg:#14171c; --fg2:#4b535e; --muted:#5b6470; --line:#e2e5ea; --line2:#eef0f3;
  --accent:#1f66c4; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#006300; --good-mark:#0ca30c; --bad:#c7342f; --bad-mark:#d03b3b; --warn:#8a5200; --warn-mark:#d98a1a;
  --chip:#eef2f7; --fs-xs:12px; --fs-s:13px; --fs-m:14px;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#98a0ab; --line:#2a2f37; --line2:#262b33;
  --accent:#4d95ec; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --warn-mark:#e0a24a; --chip:#232830; color-scheme:dark } }
:root[data-theme="dark"] { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#98a0ab; --line:#2a2f37; --line2:#262b33;
  --accent:#4d95ec; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --warn-mark:#e0a24a; --chip:#232830; color-scheme:dark }
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
.live .btn { margin-left:auto; display:inline-flex; align-items:center; min-height:36px; padding:0 16px; border-radius:999px; background:var(--accent); color:#fff; font-weight:500 }
.live .btn:hover, .live .btn:focus-visible { text-decoration:none; filter:brightness(1.1) }
.live small { flex-basis:100%; font-size:var(--fs-xs); color:var(--muted) }
section { display:grid; gap:12px }
.sec-head { display:flex; flex-wrap:wrap; gap:2px 16px; align-items:baseline; justify-content:space-between }
.sec-head p { margin:0; color:var(--fg2); font-size:var(--fs-s); text-wrap:pretty }
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
.tabbar { display:flex; gap:6px; border-bottom:1px solid var(--line); padding-bottom:0 }
.tabbar label { cursor:pointer; padding:10px 14px; border-radius:8px 8px 0 0; font-weight:500; color:var(--fg2); border:1px solid transparent; border-bottom:none; margin-bottom:-1px; display:inline-flex; gap:8px; align-items:center; min-height:44px }
.tabbar label:hover { color:var(--fg) } .tabbar .cnt { font-size:var(--fs-xs); background:var(--chip); color:var(--fg2); border-radius:999px; padding:1px 8px }
#tab-pick:checked ~ .tabbar label[for="tab-pick"], #tab-young:checked ~ .tabbar label[for="tab-young"] { color:var(--accent); background:var(--surface); border-color:var(--line) }
.tabbar label:focus-visible, .tabs > input:focus-visible ~ .tabbar label[for] { outline:2px solid var(--accent); outline-offset:2px }
.pane { display:grid; gap:24px } #tab-young:checked ~ #pane-pick, #tab-pick:checked ~ #pane-young { display:none }
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
details.more > summary { color:var(--accent); font-weight:500 }
.embed { width:100%; height:360px; border:0; border-radius:6px; background:var(--chip) }
a { color:var(--accent); text-decoration:none } a:hover, a:focus-visible { text-decoration:underline }
.links { display:flex; flex-wrap:wrap; gap:8px }
.links a { display:inline-flex; align-items:center; min-height:40px; padding:0 14px; border:1px solid var(--line); border-radius:999px; background:var(--chip); color:var(--accent); font-size:var(--fs-s); font-weight:500 }
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
details.fold-lite > summary { color:var(--accent); font-weight:500; padding:4px 0 } details.fold-lite[open] > summary { margin-bottom:8px } details.fold-lite > .note { margin-bottom:8px }
.track { position:relative; height:56px; margin:0 4px }
.track .rail, .track .fill { position:absolute; top:26px; height:6px; border-radius:999px } .track .rail { left:0; right:0; background:var(--line2) }
.track .fill.good, .track .dot.good { background:var(--good-mark) } .track .fill.warn, .track .dot.warn { background:var(--warn-mark) } .track .fill.bad, .track .dot.bad { background:var(--bad-mark) }
.track .tk { position:absolute; top:21px; height:16px; width:2px; margin-left:-1px; border-radius:1px; background:var(--fg2) }
.track .tk.be { width:0; margin-left:0; background:none; border-left:2px dotted var(--muted) } .track .tk.tp { width:3px; margin-left:-1.5px; background:var(--accent) }
.track .dot { position:absolute; top:22px; width:14px; height:14px; margin-left:-7px; border-radius:50%; border:3px solid var(--surface); box-shadow:0 0 0 1px var(--line) }
.track .now { position:absolute; top:0; transform:translateX(-50%); font-size:var(--fs-s); font-weight:600; white-space:nowrap; font-variant-numeric:tabular-nums }
.track .now.l { transform:translateX(-7px) } .track .now.r { transform:translateX(calc(-100% + 7px)) }
.track .now.good { color:var(--good) } .track .now.warn { color:var(--warn) } .track .now.bad { color:var(--bad) }
.track .tl { position:absolute; top:40px; transform:translateX(-50%); font-size:var(--fs-xs); color:var(--muted); white-space:nowrap } .track .tl.end { transform:translateX(calc(-100% + 2px)); color:var(--accent) }
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
.odds-note { margin:-6px 0 0; font-size:var(--fs-s); color:var(--warn); text-wrap:pretty }
details.safe > summary { display:flex; gap:8px; align-items:center; color:var(--fg); font-weight:500 } details.safe > summary .ic { width:20px; height:20px; border-radius:50%; display:inline-grid; place-items:center; font-size:11px; font-weight:700; flex:none }
details.safe.ok > summary .ic { background:color-mix(in srgb,var(--good-mark) 18%,var(--surface)); color:var(--good) } details.safe.warn > summary .ic { background:color-mix(in srgb,var(--warn-mark) 24%,var(--surface)); color:var(--warn) }
details.safe.bad > summary .ic { background:color-mix(in srgb,var(--bad-mark) 18%,var(--surface)); color:var(--bad) }
details.safe > summary::after { content:"›"; color:var(--accent); margin-left:2px } details.safe[open] > summary::after { content:"‹" }
.paper { margin:0; padding:8px 12px; border-radius:6px; font-size:var(--fs-s); background:color-mix(in srgb,var(--accent) 9%,var(--surface)); border:1px solid color-mix(in srgb,var(--accent) 28%,var(--line)) }
.paper .k { display:block; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--accent); font-weight:600 }
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
@media (prefers-reduced-motion: reduce) { .tip, details.fold > summary::after { transition:none } }
@media (max-width:700px) { .chart .wide { display:none } .chart .narrow { display:block } }
@media (max-width:560px) {
  body { font-size:15px } h1 { font-size:21px } .wrap { gap:20px }
  .note, .why, .safety, .sec-head p, details, table, .legend, .tile .sub, header .meta, .live, .links a { font-size:14px } .chip { font-size:13px }
  .hero { grid-template-columns:1fr 1fr } .hero .tile.lead { grid-column:1 / -1 } .hero .tile:last-child:nth-child(even) { grid-column:1 / -1 } .tile.lead .value { font-size:32px }
  .ck .vl { max-width:13ch } .acct { grid-template-columns:1fr 1fr } .acct .lead { grid-column:1 / -1; border-bottom:1px solid var(--line2) } .acct > div + div { border-left:0 }
  .acct .cell:nth-child(3) { border-left:1px solid var(--line2) } .acct .cell:last-child { grid-column:1 / -1; border-top:1px solid var(--line2) }
  details.hold > summary { grid-template-columns:1fr auto; grid-template-areas:"who plv" "track track" "meta meta"; padding:12px 14px } details.hold .body { padding:12px 14px }
  .verdicts .v { font-size:20px } .spark-box { padding-right:46px }
  .kv { grid-template-columns:1fr 1fr } .embed { height:240px } .card { gap:12px } .odds { grid-template-columns:1fr 1fr } .odds .tile:last-child { grid-column:1 / -1 }
  .stack table, .stack tbody, .stack tr, .stack td { display:block } .stack thead { display:none } .stack tr { padding:10px 12px; border-top:1px solid var(--line2) } .stack tr:first-child { border-top:0 }
  .stack td { border-top:0; padding:2px 0; text-align:left; white-space:normal; min-width:0; max-width:none } .stack td.n, .stack td.w, .stack td.m, .stack td.act { display:inline-block; padding-right:12px }
  .stack td.d { display:inline-block; padding-right:12px } .stack td.res { display:block } .stack td.res .r1 { display:inline } .stack td.n::before, .stack td.d::before { content:attr(data-k) " "; color:var(--muted); font-size:12px } .stack td.act { padding-top:4px } }
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
    show(e.clientX,e.clientY,best.t+'\n'+best.v.map(function(v){return v[0]+': '+v[1].toFixed(2);}).join('\n'));}
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


def tile(label, value, sub="", lead=False, delta=None):
    d = ""
    if delta is not None:
        d = '<span class="delta %s">%s%s</span>' % ("good" if delta > 0 else ("bad" if delta < 0 else ""), fmt_amt(delta, True), " since start" if lead else "")
    return '<div class="tile%s"><div class="label">%s</div><div class="value">%s%s</div>%s</div>' % (" lead" if lead else "", E(label), E(value), d, ('<div class="sub">%s</div>' % E(sub)) if sub else "")


def fold(title, summary, inner, open_=False):
    """A section that opens on tap: the summary row carries the heading and the one-line answer, the content sits below."""
    return '<details class="fold"%s><summary><span class="t">%s</span>%s</summary>%s</details>' % (
        " open" if open_ else "", E(title), ('<span class="sum">%s</span>' % E(summary)) if summary else "", inner)


def section(h2, sub, body):
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
    if p.get("grp") == "hold":
        sells = "all at %s (+%d%%) · or the first scan it fails a filter" % (fmt_px((1 + M.HOLD_TP) * r["entry"]) if r["entry"] else "–", round(100 * M.HOLD_TP))
        deadline = fmt_dt((M.num(p.get("t")) or 0) + M.HOLD_MAX_H * 3_600_000, True)
    elif r["half"]:
        sells = "the rest if it falls back to %s" % fmt_px(r["entry"])
    else:
        sells = "half at %s (2x) · all at %s (−50%%)" % (fmt_px(2 * r["entry"]) if r["entry"] else "–", fmt_px(0.5 * r["entry"]) if r["entry"] else "–")
    if p.get("grp") != "hold":
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
    bits = ["%d of %d clean" % (n("ok"), len(rows))] + [txt % n(s) for s, txt in (("warn", "%d only within the relaxed floor"), ("bad", "%d failed"), ("unknown", "%d unknown")) if n(s)]
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
    return "%d of %d clean" % (sum(1 for r in rows if r[0] == "ok"), len(rows)) + ((" · %s: %s" % (worst[1], worst[2].split(", ")[0])) if worst else "")


def track_bar(cur, be, tp):
    """Where the price stands, in % since the entry, between the entry (0), break-even after both fees (be) and the take-profit (tp)."""
    c0 = cur if cur is not None else 0.0
    lo, hi = min(-20.0, c0 - 5), max(tp + 5, c0 + 5)
    P = lambda v: max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    cls = "good" if c0 >= be else ("warn" if c0 >= 0 else "bad")
    out = ['<div class="rail"></div>']
    if cur is not None:
        a, b = sorted((P(0), P(cur)))
        out.append('<div class="fill %s" style="left:%.1f%%;width:%.1f%%"></div>' % (cls, a, max(b - a, 0.8)))
    out.append('<span class="tk" style="left:%.1f%%"></span><span class="tk be" style="left:%.1f%%"></span><span class="tk tp" style="left:%.1f%%"></span>' % (P(0), P(be), P(tp)))
    if cur is not None:
        x = P(cur)
        out.append('<span class="dot %s" style="left:%.1f%%"></span><span class="now %s%s" style="left:%.1f%%">%s</span>' % (cls, x, cls, " l" if x < 10 else (" r" if x > 90 else ""), x, sgn("%+.1f%%" % cur)))
    out.append('<span class="tl" style="left:%.1f%%">entry</span><span class="tl end" style="left:%.1f%%">sells %s</span>' % (P(0), P(tp), sgn("%+.0f%%" % tp)))
    aria = "price %s since the entry; break-even after fees at %s; sold at %s" % (sgn("%+.1f%%" % cur) if cur is not None else "unknown", sgn("%+.1f%%" % be), sgn("%+.0f%%" % tp))
    return '<div class="track" role="img" aria-label="%s">%s</div>' % (E(aria), "".join(out))


def time_bar(t_start, now):
    held = max(0.0, (now - t_start) / 3_600_000)
    return ('<div class="clock"><div class="bar"><span style="width:%.1f%%"></span></div><div class="cap"><span>held %s of %dh</span><span>sold %s at the latest</span></div></div>' % (
        100 * min(1.0, held / M.HOLD_MAX_H), fmt_dur(held), round(M.HOLD_MAX_H), fmt_dt(t_start + M.HOLD_MAX_H * 3_600_000, True)))


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


def hold_card(r, now):
    """A held paper position as one row that opens on tap. The row: the coin, what it would bring if sold now against what it
    cost, the price between the entry, break-even and the take-profit, and the clock. Opened: the price since the entry, the
    facts of the buy, the safety check it was bought on, why, the links."""
    p = r["p"]
    entry, ticket, mult, pnl = r["entry"], r["ticket"], r["mult"], r["pnl"]
    t0 = M.num(p.get("t")) or now                         # the hold limit counts from the scan that named it (memebot.py)
    t_buy = M.num(p.get("entryAt")) or t0
    ref = r.get("cpx") or entry                           # the take-profit is measured on the candles' own entry price
    tp_px = (1 + M.HOLD_TP) * ref if ref else None
    tp = 100 * (tp_px / entry - 1) if tp_px and entry else 100 * M.HOLD_TP
    be = be_mult(ticket)
    be_pct = 100 * (be - 1) if be else 0.0
    cur = 100 * (mult - 1) if mult is not None else None
    cls = "good" if (pnl or 0) > 0 else ("bad" if (pnl or 0) < 0 else "")
    held_h = max(0.0, (now - t0) / 3_600_000)
    meta = "price %s since the entry · held %s of %dh" % (fmt_chg(mult), fmt_dur(held_h), round(M.HOLD_MAX_H))
    leg = '<div class="tleg"><span>entry %s</span><span>now %s</span><span title="the price change at which this ticket comes back whole after the buy and the sell fee">break-even %s</span><span>sells at %s</span></div>' % (
        fmt_px(entry), fmt_px(r["last"]), sgn("%+.1f%%" % be_pct), fmt_px(tp_px))
    worth = ("worth %s if sold now, paid %s, after both fees" % (fmt_amt(r["value"]), fmt_amt(ticket))) if r["value"] is not None else "no price since the buy · paid %s" % fmt_amt(ticket)
    kv = [("bought", fmt_dt(t_buy, True)), ("paid", fmt_amt(ticket)), ("score at buy", "%.0f · rank #%s" % (M.num(p.get("score")) or 0, p.get("rank") or "?")),
          ("market cap at buy", fmt_money(p.get("mc"))), ("24h volume at buy", fmt_money(p.get("vol"))),
          ("liquidity", "%s → %s" % (fmt_money(p.get("liq")), fmt_money(r["liq_now"])) if r["liq_now"] is not None else fmt_money(p.get("liq")))]
    why = (p.get("why") or "").split("; RugCheck")[0]
    rk = p.get("risk") if isinstance(p.get("risk"), dict) else None
    safety = ('<details class="more"><summary>Safety check at the buy · %s</summary>%s</details>' % (E(checks_summary(rk)), checklist(rk, "Safety check at the buy"))) if safety_checks(rk) else safety_box(p.get("safety"))
    return ('<details class="card pos hold"><summary><span class="who"><span class="sym">%s</span>%s</span><span class="plv %s">%s</span>'
            '<span class="meta">%s</span>%s</summary><div class="body"><p class="worth">%s</p>%s%s%s<div class="kv">%s</div>%s%s%s<div class="addr">%s</div></div></details>') % (
        E(p.get("sym")), name_html(p.get("sym"), p.get("name")), cls, fmt_amt(pnl, True) if pnl is not None else "–", E(meta), track_bar(cur, be_pct, tp),
        E(worth), leg, time_bar(t0, now), spark(r.get("candles") or [], ref, tp_px), kv_html(kv),
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


def rec_card(c, now, embed, peers=None, held=None):
    """A recommended coin, top to bottom: who it is and how much the pick is worth (tier, safety), its market in one strip, the
    score and the trained odds in one strip, the paper position, then on tap: the safety checklist, why the bot picked it and
    every number behind the pick; the live chart, the links. held: {address: open hold row} for the paper-position line."""
    f, rk = c.get("f") or {}, c.get("risk") or {}
    dv = rk.get("dev") or {}
    g = lambda k: M.num(f.get(k))
    hz = horizon_text()
    up, zp = M.num(c.get("upP")), M.num(c.get("zeroP"))
    b = c.get("bought")
    paper = None
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        paper = "bought for %s · sold at +%d%% or the first scan it fails a filter" % (fmt_amt(b), round(100 * M.HOLD_TP))
    elif b == "held":
        hr = (held or {}).get(c.get("addr"))
        paper = "already held from an earlier tip · not bought again"
        if hr:
            paper = "already held since %s (bought for %s) · %s if sold now, after fees · not bought again" % (
                fmt_dt(M.num(hr["p"].get("entryAt")) or M.num(hr["p"].get("t")), True), fmt_amt(hr["ticket"]), fmt_amt(hr["pnl"], True) if hr["pnl"] is not None else "no price yet")
    elif b:
        paper = "not bought: %s" % b
    verdicts = [("Score", "%.0f" % (M.num(c.get("score")) or 0), "of 100 · rank #%s" % (c.get("rank") or "?")),
                ("Chance of a profit", pct(100 * up) if up is not None else "–", ("within %s, after fees" % hz) if up is not None else "no trained model yet"),
                ("Chance of going to zero", pct(100 * zp) if zp is not None else "–", ("within %s" % hz) if zp is not None else "no trained model yet")]
    low = {"Chance of a profit"} if c.get("lowOdds") else set()
    verdict_html = '<div class="verdicts">%s</div>' % "".join('<div%s><span class="k">%s</span><span class="v">%s</span><span class="s">%s</span></div>' % (
        ' class="low" title="fewer than %d%% of coins like this ended the window in profit after fees"' % round(100 * M.MIN_UP_P) if k in low else "", E(k), E(v), E(sub)) for k, v, sub in verdicts)
    n_same = same_odds(c, peers)
    odds_note = ('<p class="odds-note">Same odds for all %d candidates of this scan: the model, trained on the bot\'s own scored scans, cannot tell them apart here, so the score ranks them.</p>' % n_same) if n_same else ""
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
    notes = ""
    if c.get("standin"):
        notes += '<p class="note">DexScreener delivered no pair data this scan: the numbers here come from Jupiter or GeckoTerminal, which stood in. The chart opens by mint address.</p>'
    if c.get("tier") == "fallback":
        notes = '<p class="note">Named only because nothing cleaner passed every gate. It failed: %s.</p>' % E("; ".join(str(x) for x in c.get("relaxed") or []))
    elif c.get("tier") == "watch":
        notes += '<p class="note"><strong>Not a pick.</strong> Every coin that cleared the safety floor was over the zero limit this scan. This is the safest-looking one, shown with the odds that stopped it: %s%s.</p>' % (
            ("%s chance of a profit" % pct(100 * M.num(c["upP"]))) if M.num(c.get("upP")) is not None else "", (", %s chance of going to zero" % pct(100 * M.num(c["zeroP"]))) if M.num(c.get("zeroP")) is not None else "")
    elif c.get("tier") == "risky":
        notes = '<p class="note">No coin had a clean safety report this scan. This is the tradable coin with the best trained odds (chance of profit minus chance of zero), not a clean pick.%s</p>' % (
            (" It also failed: %s." % E("; ".join(str(x) for x in c.get("relaxed") or []))) if c.get("relaxed") else "")
    chart = ('<iframe class="embed" src="https://dexscreener.com/solana/%s?embed=1&amp;theme=dark&amp;trades=0&amp;info=0" title="%s chart" loading="lazy"></iframe>' % (E(c.get("pair") or c.get("addr")), E(c.get("sym")))) if embed else ""
    kv = [(k, v) for k, v in kv if k not in STRIP_KV]
    groups = [(name, [(k, v) for k, v in kv if test(k)]) for name, test in (("Trading", lambda k: k not in SAFETY_KV and k not in STORY_KV),
                                                                            ("Holders & safety", lambda k: k in SAFETY_KV), ("Story & attention", lambda k: k in STORY_KV))]
    numbers = '<details class="more nums"><summary>All numbers (%d)</summary><div class="groups">%s</div>%s</details>' % (
        len(kv), "".join('<div class="grp"><h4>%s</h4><div class="kv">%s</div></div>' % (E(name), kv_html(items)) for name, items in groups if items), sources_row(c.get("src")))
    paper_html = ('<p class="paper"><span class="k">paper position</span>%s</p>' % E(paper)) if paper else ""
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
        E(c.get("sym")), name_html(c.get("sym"), c.get("name")), tier_chip(c), safety_chip(c.get("ok")) + story_chip(c),
        stats_html, verdict_html, odds_note, paper_html, safety, why, notes, numbers, chart, links(c), E(c.get("addr")))


def coin_cell(rank, sym, name, chips):
    return '<td><strong>#%s %s</strong>%s%s</td>' % (E(rank), E(sym), name_html(sym, name), ('<div class="row">%s</div>' % chips) if chips else "")


def num_cells(score, mc, liq, vol):
    return ('<td class="n" data-k="score">%.0f</td><td class="n" data-k="market cap">%s</td><td class="n" data-k="liquidity">%s</td><td class="n" data-k="24h volume">%s</td>'
            % (score, fmt_money(mc), fmt_money(liq), fmt_money(vol)))


COIN_HEAD = '<thead><tr><th>coin</th><th class="n">score</th><th class="n">market cap</th><th class="n">liquidity</th><th class="n">24h volume</th><th></th></tr></thead>'
CHART_CELL = '<td class="act"><a href="https://dexscreener.com/solana/%s" target="_blank" rel="noopener">chart</a></td>'


def rec_section(D, embed):
    rc = D.get("rec")
    if not rc:
        return ""
    picks = rc.get("picks") or []
    n = len(picks)
    hz = " for the next 2 hours" if M.HORIZON == "2h" else ""
    h2 = {0: "No recommendation", 1: "One recommendation", 2: "Two recommendations"}.get(n, "%d recommendations" % n) + hz
    if picks and all(c.get("tier") == "watch" for c in picks):
        h2 = "No pick, one coin to watch" + hz
    head = "fake money · %s of %s coins passed the gates" % (fmt_int(rc.get("passed") or 0), fmt_int(rc.get("scanned")))
    if rc.get("pickBy") == "odds":
        head += " · ranked by trained odds"
    if M.num(rc.get("pricedAt")):
        head += " · prices refreshed %s, %d min into the scan" % (fmt_dt(rc["pricedAt"], True)[-5:], max(0, round((M.num(rc["pricedAt"]) - (M.num(rc.get("t")) or 0)) / 60000)))
    t_rec, t_run = M.num(rc.get("t")), M.num((D.get("state") or {}).get("lastRun"))
    if picks and t_rec and t_run and t_run - t_rec > 60_000:     # the newest run found no clean coin, so the older pick stays up: say so
        head = "from the run at %s · the latest run (%s) found no clean coin, so this older pick stays up · fake money" % (fmt_dt(t_rec, True), fmt_dt(t_run, True))
    peers = [c for c in picks + (rc.get("runnersUp") or []) if isinstance(c, dict)]
    held = {r["p"].get("addr"): r for r in (D.get("open") or []) if r["p"].get("grp") == "hold"}
    if picks:
        body = '<div class="cards">%s</div>' % "".join(rec_card(c, D["now"], embed, peers, held) for c in picks)
    else:
        body = '<div class="empty">No recommendation this time: %s. The closest coins and what stopped them are listed below.</div>' % E(rc.get("reason") or ("no top coin had a clean safety report" if rc.get("passed") else "nothing passed the gates"))
    runners = [c for c in (rc.get("runnersUp") or []) if isinstance(c, dict)]
    if runners:
        tr = "".join('<tr>%s%s%s</tr>' % (coin_cell(c.get("rank") or "?", c.get("sym"), c.get("name"), safety_chip(c.get("ok"), c.get("safety"))),
                                          num_cells(M.num(c.get("score")) or 0, c.get("mc"), c.get("liq"), c.get("vol")), CHART_CELL % E(c.get("pair") or c.get("addr"))) for c in runners)
        body += '<details><summary>Runners-up (%d)</summary><div class="tbl stack"><table>%s<tbody>%s</tbody></table></div></details>' % (len(runners), COIN_HEAD, tr)
    return section(E(h2), head, body)


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
    return '<h3>What the earlier new launches did</h3><p class="note">%s · 20 in each at the scan price, after fees · fake money</p><details><summary>%d new launches from the last scans</summary><div class="tbl stack hist"><table>%s<tbody>%s</tbody></table></div></details>' % (
        E(note), len(rows), head, "".join(rows))


def young_section(D):
    """The new-launches tab: every coin under an hour old with a tradable pair this scan, best score first, with the same odds
    and safety data as the pick, and the scored record by age. These coins are shown, never picked."""
    rc = D.get("rec") or {}
    young = [c for c in (rc.get("young") or []) if isinstance(c, dict)]
    n_all = int(M.num(rc.get("youngOf")) or len(young))
    head = "coins under an hour old with a DEX pair and at least %s of liquidity at the scan · shown, never picked: the %s profile picks from coins %g to %g hours old · fake money" % (
        fmt_money(M.YOUNG_MIN_LIQ), M.HORIZON, M.GATE_MIN_AGE_H, M.GATE_MAX_AGE_H or 0)
    if young:
        rows_html = []
        for i, c in enumerate(young, 1):
            chips = '<span class="chip">%d min old</span>%s%s%s' % (int(M.num(c.get("ageMin")) or 0), safety_chip(c.get("ok"), c.get("safety")), odds_chip(c), story_chip(c))
            rows_html.append('<tr>%s%s%s</tr>' % (coin_cell(i, c.get("sym"), c.get("name"), chips), num_cells(M.num(c.get("score")) or 0, c.get("mc"), c.get("liq"), c.get("vol")), CHART_CELL % E(c.get("pair") or c.get("addr"))))
        body = '<div class="tbl stack"><table>%s<tbody>%s</tbody></table></div>' % (COIN_HEAD, "".join(rows_html))
        cards = "".join(rec_card(dict(c, tier="young"), D["now"], embed=False, peers=young) for c in young)
        body += '<details><summary>Every number behind each coin (%d cards)</summary><div class="cards">%s</div></details>' % (len(young), cards)
        gates = [(c.get("sym"), c.get("gates") or []) for c in young if c.get("gates")]
        if gates:
            body += '<details><summary>Which other gates they would fail today</summary><ul class="note">%s</ul></details>' % "".join(
                "<li><strong>%s</strong>: %s</li>" % (E(sym), E("; ".join(str(x) for x in g))) for sym, g in gates)
    elif rc and "young" not in rc:
        body = '<div class="empty">This scan ran before the tab existed; the next scan fills it.</div>'
    elif rc:
        body = '<div class="empty">No coin under an hour old had a DEX pair with %s of liquidity in this scan (%d coins scanned).</div>' % (fmt_money(M.YOUNG_MIN_LIQ), int(M.num(rc.get("scanned")) or 0))
    else:
        body = '<div class="empty">No scan yet.</div>'
    body = '<h3>The record by age</h3>%s<h3>This scan</h3>%s%s' % (age_record(D.get("train")), body, young_history(D))
    h2 = ("%d new launch%s under an hour old" % (n_all, "" if n_all == 1 else "es")) if rc else "New launches"
    if n_all > len(young) and young:
        h2 += " (the %d best shown)" % len(young)
    return section(E(h2), head, body)


SCAN_MINUTE_UTC = 10      # the scheduled scan starts at this minute of every hour (.github/workflows/scan.yml); a run takes about 15 minutes
HISTORY_DAYS = 2          # the hour-by-hour list covers this many days
HISTORY_OPEN = 12         # rows shown before the rest folds (a phone screen's worth)


def next_scan_ms(now):
    """When the next scheduled scan starts, from the hourly cron in scan.yml."""
    t = dt.datetime.fromtimestamp((M.num(now) or 0) / 1000, dt.timezone.utc).replace(minute=SCAN_MINUTE_UTC, second=0, microsecond=0)
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
    fake money (20 per tip, after fees), with the running total drawn over time. A test of the tips; the paper account (one
    position per coin, sold by the hold rule) is the dashboard at the top."""
    rows = [r for r in profit_rows(D) if r[3]]
    if not rows:
        return ""
    key, hours, label, pts = rows[0]
    s = profit_stats(pts)
    staked = s["n"] * M.TICKET
    yes = s["tot"] > 0
    verdict = ('<p class="verdict %s"><strong>%s.</strong> %d tip%s priced %s: %d went up, %d went to zero, together <strong>%s</strong> on %s staked (%s per 20).%s</p>' % (
        "good" if yes else "bad", "Up so far" if yes else "Down so far", s["n"], "s" if s["n"] != 1 else "", label, s["up"], s["zero"],
        fmt_amt(s["tot"], True), fmt_amt(staked), fmt_amt(s["tot"] / s["n"], True), ""))
    tiles = [tile("All tips together, %s" % label, fmt_amt(s["tot"], True), "%d tips · %s staked · fake money, after fees" % (s["n"], fmt_amt(staked)), lead=True),
             tile("Tips that went up", "%d of %d" % (s["up"], s["n"]), "a profit after fees needs about %s" % sgn("%+.1f%%" % (100 * (be_mult(M.TICKET) - 1)))),
             tile("Tips that went to zero", "%d of %d" % (s["zero"], s["n"]), "under 2% of the entry price")]
    held = [r for r in (D.get("pos") or []) if r["p"].get("grp") == "hold"]
    if held:      # the same tips as paper positions: one per coin, sold by the hold rule, not one 20 per tip and window
        n_c, n_o = sum(1 for r in held if r["closed"]), sum(1 for r in held if not r["closed"])
        tot_h = sum(r["pnl"] for r in held if r["pnl"] is not None)
        tiles.append(tile("Held as paper positions", fmt_amt(tot_h, True), "%d sold · %d open · one position per coin, sold at +%d%% or when it fails a filter" % (n_c, n_o, round(100 * M.HOLD_TP))))
    html_ = '<section class="hero">%s</section>' % "".join(tiles)
    trs = []
    for key_, hours_, label_, pts_ in rows:
        st_ = profit_stats(pts_)
        trs.append('<tr><td>%s</td><td class="n" data-k="tips priced">%d</td><td class="n" data-k="went up">%d</td><td class="n" data-k="to zero">%d</td><td class="n" data-k="together"><span class="%s">%s</span></td><td class="n" data-k="per 20">%s</td><td class="n" data-k="sold at +%d%% when reached">%s</td></tr>' % (
            E(label_), st_["n"], st_["up"], st_["zero"], "good" if st_["tot"] > 0 else "bad", fmt_amt(st_["tot"], True), fmt_amt(st_["tot"] / st_["n"], True), tp_pct(),
            (fmt_amt(st_["tpTot"], True) + " (%d of %d with candles)" % (len(st_["tp"]), st_["n"])) if st_["tp"] else "–"))
    table = '<div class="tbl"><table><thead><tr><th>priced</th><th class="n">tips</th><th class="n">went up</th><th class="n">to zero</th><th class="n">together</th><th class="n">per 20</th><th class="n">sold at +%d%% when reached</th></tr></thead><tbody>%s</tbody></table></div>' % (tp_pct(), "".join(trs))
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
        legend = '<div class="legend"><span style="--c:var(--s1)">%s, 20 each, after fees</span><span class="ref-leg">break-even</span></div>' % E("all tips together, %s" % label)
        chart = chart_box(line_chart(ser, 0.0, WIDE, ref_label="break-even", aria_label="Running profit of the tips"), line_chart(ser, 0.0, NARROW, ref_label="break-even", aria_label="Running profit of the tips"), legend)
    chain = compound_chain(D.get("track_all") or D.get("track") or [])
    note = '<p class="note">Running total of every tip in time order, 20 in each, sold %s. ' % label
    note += ('20 put into every tip one after the other, each time the whole stake, would be %s now after %d tips. ' % (fmt_amt(chain["equity"]), chain["n"])) if chain["n"] else ""
    note += 'Fake money: every tip counts 20 per window here; the held paper positions (one per coin) are in "Open positions" and "Closed trades" and make the paper account at the top. Fees simulated at 0.5%, minimum 0.81 per trade.</p>'
    more = '<details class="fold-lite"><summary>With a take-profit, and how this is counted</summary>%s%s</details>' % (replay, note)
    return section("Tip record", "a test of the tips, not the paper account: every coin the bot named counted as its own 20, priced again after the window", verdict + html_ + chart + table + more)

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
    return section("Recommendations, hour by hour", sub, body)


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
    body = ['<p class="note">%s</p>' % E(T.get("note") or "")]
    if wf:
        names = [("top1", "the bot's best coin per scan"), ("top2", "the bot's two best coins per scan"), ("top2zero", "the two best under the zero limit (the rule in use)"),
                 ("byOdds", "the best trained odds per scan (the risky tier's rule)"), ("allPass", "every coin that passed the gates"), ("bottom2", "the two worst-scored passing coins")]
        tr = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (E(label), stat_cells(wf.get(k)), pct((wf.get(k) or {}).get("coverage")) if (wf.get(k) or {}).get("coverage") is not None else "–")
                     for k, label in names if wf.get(k))
        body.append('<h3>Walk-forward test</h3><p class="note">%d scans judged by models fitted on the scans before them only · a tip is 20 in the coin, priced again %s later · coverage: scans in which the rule found a coin</p>'
                    '<div class="tbl stack"><table><thead><tr><th>rule</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table></div>' % (int(M.num(T.get("tested")) or 0), hz, STAT_HEAD, tr))
    tuned = T.get("tuned") or {}
    if T.get("zeroModel"):
        zm = T["zeroModel"]
        lim = M.num(tuned.get("MAX_ZERO_P"))
        why = "".join("<li>%s</li>" % E(w) for w in (T.get("tunedWhy") or []))
        zf = "".join('<tr><td>%s <code>%s</code></td><td class="n">%s</td><td>%s</td></tr>' % (E(factor_label(z.get("factor"))), E(z.get("factor")), E("%.2f" % (M.num(z.get("spread")) or 0)),
                     E(" → ".join(("%+.0f%%" % (100 * (math.exp(v) - 1))) for v in (z.get("lo") or [])))) for z in (T.get("zeroFactors") or [])[:10])
        body.append('<h3>Zero model</h3><p class="note">fitted on %d coin results (%d went to zero, %s base rate): each factor is cut into four value bins, low to high, and each bin shifts the odds of going to zero within %s. '
                    'A clean coin is skipped when its calibrated zero chance is above %s.</p>%s<div class="tbl stack"><table><thead><tr><th>factor</th><th class="n">spread</th><th>odds shift per bin, low → high</th></tr></thead><tbody>%s</tbody></table></div>' % (
                        int(M.num(zm.get("n")) or 0), int(M.num(zm.get("zeros")) or 0), pct(100 * (M.num(zm.get("base")) or 0)), hz, pct(100 * lim) if lim is not None else "–",
                        ("<ul class=\"note\">%s</ul>" % why) if why else "", zf))
    zg = [g for g in (T.get("zeroGrid") or []) if isinstance(g, dict)]
    sg = [g for g in (T.get("scoreGrid") or []) if isinstance(g, dict)]
    if zg or sg:
        tz = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (pct(100 * (M.num(g.get("limit")) or 0)), stat_cells(g), pct(g.get("coverage")) if g.get("coverage") is not None else "–") for g in zg)
        ts = "".join('<tr><td>%s</td>%s<td class="n">%s</td></tr>' % (E("%.0f" % (M.num(g.get("minScore")) or 0)), stat_cells(g), pct(g.get("coverage")) if g.get("coverage") is not None else "–") for g in sg)
        body.append('<details><summary>Limit grids (top-2 tips in the walk-forward test)</summary><div class="tbl stack"><table><thead><tr><th>zero limit</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table>'
                    '<table><thead><tr><th>score at least</th>%s<th class="n">coverage</th></tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tz, STAT_HEAD, ts))
    gates = [g for g in (T.get("gates") or []) if isinstance(g, dict)]
    if gates:
        tg = "".join('<tr><td>%s</td>%s</tr>' % (E(g.get("text") or g.get("gate")), stat_cells(g)) for g in gates[:14])
        body.append('<details><summary>Gate audit (coins that failed exactly one gate)</summary><p class="note">a gate whose lone failers did as well as the passers protects nothing; one whose failers went to zero earns its keep</p>'
                    '<div class="tbl stack"><table><thead><tr><th>gate</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tg))
    filters = [g for g in (T.get("filters") or []) if isinstance(g, dict)]
    if filters:
        tf = "".join('<tr><td>%s</td><td class="n">%s</td>%s</tr>' % (E(g.get("filter")), pct(g.get("share")) if g.get("share") is not None else "–", stat_cells(g)) for g in filters)
        body.append('<details><summary>Filter recipes from outside, tested on the bot\'s results</summary><p class="note">trading-terminal presets as they circulate on TikTok (market cap, volume, age, "DEX paid"), applied to every scored coin of this profile, next to the bot\'s own gates · "DEX paid" is read from DexScreener\'s orders for new coins and from the presence of a DexScreener profile for older results</p>'
                    '<div class="tbl stack"><table><thead><tr><th>filter</th><th class="n">keeps</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (STAT_HEAD, tf))
    tips = T.get("tips") or {}
    summary = ("%d coin results from %d scans" % (rows_n, scans_n)) if rows_n else "waiting for the first scored snapshot"
    if wf.get("top2zero") or wf.get("top2"):
        st = wf.get("top2zero") or wf["top2"]
        summary += " · walk-forward top-2: %s up, %s to zero" % (pct(st.get("win")), pct(st.get("zero")))
    if tips.get("n"):
        summary += " · real tips: %d, %s up" % (tips["n"], pct(tips.get("win")))
    return fold("Training", summary, "<section>%s</section>" % "".join(body), open_=False)


def closed_table(rows):
    if not rows:
        return '<div class="empty">No closed trades yet.</div>'
    tr = []
    for r in rows:
        p = r["p"]
        days = ((r["exit_t"] or 0) - (M.num(p.get("t")) or 0)) / 86_400_000 if r["exit_t"] else None
        sold_at = ", ".join(("%.2fx" % m if m is not None else "–") + (" (half)" if half else "") for m, half in r["sold_at"]) or "–"
        tr.append('<tr><td><strong>%s</strong>%s</td><td class="d" data-k="group">%s</td><td class="d" data-k="bought">%s</td><td class="d" data-k="sold because"><span class="chip %s">%s</span></td><td class="n" data-k="sold at">%s</td><td class="n" data-k="paid">%s</td><td class="n" data-k="came back">%s</td><td class="n" data-k="result"><span class="%s">%s</span></td><td class="n" data-k="held">%s</td></tr>' % (
            E(p.get("sym")), name_html(p.get("sym"), p.get("name")), "bot" if r["bot"] else "random", fmt_dt(p.get("t"), True), r["kind"], E(r["status"]), E(sold_at), fmt_amt(r["ticket"]), fmt_amt(r["back"]),
            "good" if r["pnl"] > 0 else "bad", fmt_amt(r["pnl"], True), ("–" if days is None else ("%.0fh" % (24 * days)) if days < 2 else ("%.1fd" % days))))
    return '<div class="tbl stack"><table><thead><tr><th>coin</th><th>group</th><th>bought</th><th>sold because</th><th class="n">sold at</th><th class="n">paid</th><th class="n">came back</th><th class="n">result</th><th class="n">held</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def horizon_text():
    return M.eval_text()


def big_section(D):
    big, hz = D["big"], horizon_text()
    fee = "An unchanged price counts %s (the two fees)." % fmt_amt(FLAT, True)
    if not big:
        if D["snap_t"]:
            return '<div class="empty">First results at about %s: the %d coins of the last scan get priced again %s later. %s</div>' % (
                fmt_dt(D["snap_t"] + M.EVAL_H * 3_600_000, True), int(D["snap_n"] or 0), hz, fee)
        return '<div class="empty">The big test starts after the first full scan has been priced again %s later. Every full scan saves all its coins; %s later each one is checked: what would 20 in it have become? %s</div>' % (hz, hz, fee)
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
    return ". ".join(s for s in str(note or "").split(". ") if not s.startswith(("Weights:", "Bankroll:", "Saved all"))).strip()


def note_cell(note, rec_mode):
    """A run note split into what matters: the outcome sentence(s) in bold, the gate counts behind a tap, the scan sentence dropped
    (its numbers are the row's chips). Returns (html, sources)."""
    sents = [s.strip().rstrip(".") for s in str(note or "").split(". ") if s.strip()]
    src = next((m.group(1) for s in sents for m in [re.search(r"from (\d+) sources", s)] if m), None)
    main, gates = [], None
    for s in sents:
        if s.startswith(("Scanned", "Weights:", "Bankroll:", "Saved all")):
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
            len([p for p in (r.get("picks") or []) if isinstance(p, dict) and p.get("grp") == "pick"]), len(r.get("exits") or []), cell))
    return '<div class="tbl runs stack"><table><thead><tr><th>when</th><th>mode</th><th class="n">scanned</th><th class="n">passed gates</th><th class="n">sources</th><th class="n">buys</th><th class="n">sells</th><th>what happened</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


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
    """Recommend mode with paper positions: the paper account in one strip: what everything would fetch now against the 40 it
    started with, the open positions, the free cash and the next buy, the closed trades."""
    cash, equity = D["cash"], D["equity"]
    budget = cash["budget"]
    open_bot = D["open_bot"]
    worth = sum(r["value"] or 0 for r in open_bot)
    paid = sum(r["ticket"] * r["p"]["_left"] for r in open_bot)
    realized = sum(r["pnl"] for r in D["bot_closed"])
    nb, wins = len(D["bot_closed"]), D["wins"]
    delta = equity - budget
    tk = cash.get("tickets") or []
    nxt = ("next buy %s" % (("2 × %s" % fmt_amt(tk[0])) if len(tk) == 2 else fmt_amt(tk[0]))) if tk else "no new buy until a sale"
    cells = [("open positions", str(len(open_bot)), ("paid %s · worth %s" % (fmt_amt(paid), fmt_amt(worth))) if open_bot else "nothing held"),
             ("free cash", fmt_amt(cash["free"]), nxt),
             ("closed trades", str(nb), ("%d won · %d lost · %s" % (wins, nb - wins, fmt_amt(realized, True))) if nb else "none yet")]
    return ('<div class="acct"><div class="lead"><span class="k">value if everything were sold now</span><span class="v">%s</span>'
            '<span class="delta %s">%s since the start (%s)</span></div>%s</div>') % (
        fmt_amt(equity), "good" if delta > 0 else ("bad" if delta < 0 else ""), fmt_amt(delta, True), fmt_amt(budget),
        "".join('<div class="cell"><span class="k">%s</span><span class="v">%s</span><span class="s">%s</span></div>' % (E(k), E(v), E(sub)) for k, v, sub in cells))


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

    def curve(since=None):
        docs = [c for c in D["curve"] if isinstance(c, dict) and M.num(c.get("t"))]
        if since and sum(1 for c in docs if M.num(c["t"]) >= since) >= 2:
            docs = [c for c in docs if M.num(c["t"]) >= since]
        else:
            since = None
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
        sub = ("since the first held position (%s) · " % fmt_dt(since + 2 * 3_600_000, True) if since else "") + "bankroll plus what the open positions would fetch, after fees · now %s" % fmt_amt(equity)
        if since:
            return '<details class="fold-lite"><summary>Account value over time</summary><p class="note">%s</p>%s</details>' % (E(sub), body)
        if rec_mode:
            flat = pts_bot and all(abs(v - pts_bot[0][1]) < 0.005 for _, v in pts_bot)
            summary = ("flat at %s since %s" % (fmt_amt(equity), fmt_dt(pts_bot[0][0], True))) if flat else ("%s now · %s since start" % (fmt_amt(equity), fmt_amt(equity - cash["budget"], True)))
            return fold("Equity per run", summary, '<section><p class="note">%s</p>%s</section>' % (E(sub), body))
        return section("Equity per run", sub, body)

    def bought():
        n_bot, n_rand = len(D["open_bot"]), len(D["open"]) - len(D["open_bot"])
        head = "%d open%s · %s per coin" % (n_bot, (" plus %d random control" % n_rand) if n_rand else "", fmt_amt(cash["ticket"]))
        rule = '<details><summary>How a coin is sold</summary><p class="note">%s</p></details>' % (E(hold_rule_text()) if D.get("rec") else
                "Half is sold at 2x (the rest if it falls back to the entry price); everything is sold at −50%, after 3 days, or when the price is gone.")
        if D.get("rec") and not rec_mode:
            head = "%d held · one paper position per named coin, paid from the free bankroll · fake money" % n_bot
        if D["open"]:
            body = '<div class="cards">%s</div>' % "".join(hold_card(r, now) if r["p"].get("grp") == "hold" else position_card(r, now) for r in D["open"])
        elif rec_mode:
            body = '<div class="empty">No open positions: the bot holds a coin it names while a paper slot is free; nothing has been bought yet.</div>'
        elif D.get("rec"):
            body = '<div class="empty">No open positions: the coins bought earlier are sold (see Closed trades); the next named coin is bought while a slot is free.</div>'
        else:
            body = '<div class="empty">No open positions. %s</div>' % ("The next pick run buys the two best coins when the bankroll has a free slot." if D["runs"] else "Run <code>python3 bot.py cycle</code> to start.")
        if rec_mode:
            return fold("Bought coins", "none yet", '<section><p class="note">%s</p>%s%s</section>' % (E(head), body, rule))
        if D.get("rec"):
            return '<h3>Open positions</h3>' + body.replace('<div class="cards">', '<div class="holds">', 1) + rule
        return section("Bought coins", head, body + rule)

    def closed(inline=False):
        body = safe("closed trades", lambda: closed_table(D["closed"]))
        if inline:
            return '<details class="fold-lite"><summary>Closed trades (%d) · what came back after fees</summary>%s</details>' % (len(D["closed"]), body)
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
        return fold("Run log", "last %d runs" % min(12, len(D["runs"])), inner)

    last_run = st.get("lastRun")
    nxt = (" · next scan starts about %s" % fmt_when(next_scan_ms(now), now)) if D.get("rec") else ""
    head = ('<header><div><div class="eyebrow">paper trading · nothing is bought for real · scans every hour</div><h1>%s</h1></div>'
            '<div class="meta">updated %s%s · %s run%s</div></header>') % (E(TITLE), E(fmt_when(last_run, now)), E(nxt), E(st.get("runs") or 0), "" if st.get("runs") == 1 else "s")
    body = [head]
    tabs = ""
    if D.get("rec"):
        # two tabs: the pick (and its track record) and the new launches under an hour old; CSS-only, so the fragment works without scripts
        n_young = int(M.num((D["rec"] or {}).get("youngOf")) or len((D["rec"] or {}).get("young") or []))
        pane_pick = safe("recommendations", lambda: rec_section(D, embed=not fragment)) + safe("history", lambda: history_section(D))
        pane_young = safe("new launches", lambda: young_section(D))
        tabs = ('<div class="tabs"><input type="radio" name="tab" id="tab-pick" checked><input type="radio" name="tab" id="tab-young">'
                '<div class="tabbar" role="tablist"><label for="tab-pick" role="tab">The pick</label><label for="tab-young" role="tab">New launches &lt;1h <span class="cnt">%d</span></label></div>'
                '<div class="pane" id="pane-pick">%s</div><div class="pane" id="pane-young">%s</div></div>' % (n_young, pane_pick, pane_young))
    rest = [safe("training", lambda: train_section(D))] if D.get("rec") else []
    rest.append(section("Big test: %s later" % hz, "what 20 in each scanned coin was worth %s later, after fees" % hz, safe("big test", lambda: big_section(D))))
    shown = []
    if D.get("rec") and D["pos"]:
        # recommend mode holds the coins it names: the paper account and the held coins come first, then the pick and its record,
        # the closed trades and the curve of the account since the first held coin
        held_t = [M.num(r["p"].get("t")) for r in D["pos"] if r["p"].get("grp") == "hold" and M.num(r["p"].get("t"))]
        since = (min(held_t) - 2 * 3_600_000) if held_t else None
        account = section("Paper account", "fake money · the bot holds the coins it names: one paper position per coin, paid from the 40 it started with",
                          safe("account", lambda: dash_section(D)) + safe("open positions", bought) + safe("closed trades", lambda: closed(True)) + safe("equity curve", lambda: curve(since)))
        shown = [tabs, account, safe("profit", lambda: profit_section(D))]
        rest.append(safe("candidates", candidates))
    elif tabs:
        body.append(tabs)
    else:
        rest += [safe("hero", hero), safe("equity curve", curve), safe("bought coins", bought), safe("closed trades", closed), safe("candidates", candidates)]
    w_html = safe("weights", lambda: weights_section(D))
    if w_html:
        rest.append(w_html)
    if D["runs"]:
        rest.append(safe("run log", runlog))
    if D.get("rec"):
        # the page answers one question: which coin, why, and the numbers behind it; everything else sits behind one tap
        body += [x for x in shown if x]
        n_scan = D["scan_n"] or M.num((D.get("rec") or {}).get("scanned")) or 0
        body.append(fold("Details: training, big test, all candidates, weights, run log", "%s coins in the last scan" % fmt_int(n_scan) + (" · %s coin results scored" % fmt_int(scored) if scored else ""),
                         '<div class="rest">%s</div>' % "\n".join(x for x in rest if x)))
        if not (D.get("rec") and D["pos"]):
            body.append(safe("profit", lambda: profit_section(D)))  # the tip record, every tip priced again (with positions it sits above the details)
    else:
        body += [x for x in rest if x]
    body.append('<footer><span>generated %s</span><span>rule %s · %s profile</span><span>fees simulated at 0.5%%, minimum 0.81 per trade</span><span>prices from DexScreener at the time of each run</span><span>times in %s</span></footer>' % (
        E(fmt_dt(now)), E(st.get("rule") or M.RULE), E(M.HORIZON), TZ_NAME))
    content = '<div class="wrap">%s</div>\n<script>%s</script>' % ("\n".join(body), JS)
    head_html = ('<title>%s</title>\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">\n'
                 '<style>%s</style>') % (E(TITLE), CSS)
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
