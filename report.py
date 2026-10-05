#!/usr/bin/env python3
"""report.py: the analysis page. Renders everything in db/ as one self-contained HTML file (mb/report.html).

  python3 report.py [--dir mb] [--out mb/report.html] [--fragment]

bot.py writes it after every cycle, so the page is always the state after the last run. Open it in a browser (it is a plain
file, no server needed). --fragment leaves out the <html>/<head>/<body> wrapper for hosts that add their own.

Sections: bankroll and equity (hero), equity curve per run, the bought coins (open positions with their last price, sell levels
and the bot's reasons), closed trades with their result, the 24-hour big test (how the gated coins, the bot's top 10 and the
rest did against the "price unchanged" baseline), the factor weights in use (with a glossary), the top candidates of the last
full scan and why they were not bought, and the run log. Times are shown in Europe/Berlin, the bot's own trading day.
"""
import argparse, html, json, math, os, sys, datetime as dt

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
WIDE, NARROW = 1052, 560          # chart widths in CSS px: the desktop column and the phone variant (scrolls inside its card)
_flat = M.TICKET - M.fee(M.TICKET)
FLAT = round(max(0.0, _flat - M.fee(_flat)) - M.TICKET, 2)   # what 20 becomes when the price does not move: the two fees
WHY = {"target": "hit 2x, half sold", "stop": "−50% stop", "time": "3-day limit", "back to entry": "fell back to entry", "rug": "price gone"}
SRC = {"kw": "search “%s”", "gt": "GeckoTerminal %s", "pf": "pump.fun %s", "list": "DexScreener %s", "jup": "Jupiter %s", "gm": "GMGN %s"}
FACTOR = {"liqMc": "liquidity ÷ market cap", "volMc": "24h volume ÷ market cap", "logLiq": "liquidity (log)", "logMc": "market cap (log)",
          "buyShare": "share of buys, 24h", "buyRatio1h": "buys ÷ sells, 1h", "buyRatio6h": "buys ÷ sells, 6h", "buys1": "buys, last hour", "buys24": "buys, 24h",
          "c1": "price change 1h", "c6": "price change 6h", "c24": "price change 24h", "m5": "price change 5 min", "ageH": "age in hours",
          "vol1Share": "share of volume in last 1h", "vol6Share": "share of volume in last 6h", "fdvMc": "FDV ÷ market cap", "boosts": "DexScreener boosts",
          "nPairs": "number of pairs", "nDex": "number of DEXes", "x": "has an X account", "web": "websites", "socN": "social links",
          "srcN": "source lists naming it", "kwN": "keyword searches naming it", "src.pf": "on pump.fun",
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
          "pf.replies": "pump.fun replies", "pf.live": "pump.fun live stream", "pf.athRatio": "all-time-high ÷ now", "pf.twitter": "has X (pump.fun)", "pf.website": "has website (pump.fun)", "pf.telegram": "has Telegram (pump.fun)"}


def factor_label(k):
    if k in FACTOR:
        return FACTOR[k]
    if k.startswith("src."):
        return "on list " + k[4:]
    return k


# ---------------------------------------------------------------- formatting
def fmt_money(v, dollars=True):
    v = M.num(v)
    if v is None:
        return "–"
    s = ("-" if v < 0 else "") + ("$" if dollars else "")
    v = abs(v)
    if v >= 1e9:
        return "%s%.2fB" % (s, v / 1e9)
    if v >= 1e6:
        return "%s%.1fM" % (s, v / 1e6)
    if v >= 1e4:
        return "%s%.0fk" % (s, v / 1e3)
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
    return ("%+.2f" if signed else "%.2f") % v


def fmt_mult(v):
    v = M.num(v)
    return "–" if v is None else ("%.2fx" % v if v >= 0.1 else "%.3fx" % v)


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
        return "%.0f h" % h
    return "%.1f d" % (h / 24)


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
    px, liq_now = marks.get("px") or {}, marks.get("liq") or {}

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
            status, kind = ", ".join(WHY.get(w, w) for w in whys), ("good" if pnl > 0 else "bad")
        elif half:
            status, kind = "half sold at 2x", "good"
        else:
            status, kind = "open", "neutral"
        sold_at = [(M.num(e.get("px")) / entry if M.num(e.get("px")) and entry else None, (M.num(e.get("frac")) or 1) < 0.999) for e in exits]
        rows.append({"id": pid, "p": p, "ticket": ticket, "entry": entry, "back": back, "last": last, "value": value, "closed": closed, "half": half,
                     "pnl": pnl, "status": status, "kind": kind, "mult": (last / entry) if last and entry else None, "sold_at": sold_at,
                     "liq_now": M.num(liq_now.get(pid)), "exit_t": M.num(exits[-1].get("t")) if closed and exits else None, "bot": p.get("grp") in M.BOT_GROUPS})
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
    return {"now": now, "pos": rows, "open": open_rows, "open_bot": open_bot, "unpriced": unpriced, "closed": closed_rows, "cash": cash, "equity": equity, "state": state,
            "curve": curve, "runs": runs, "big": big, "seen_coins": len(seen_coins), "cands": cands[:15], "scan_t": last_t, "scan_run": scan_run,
            "scan_n": sum(M.num(s.get("n")) or 0 for s in snaps.values() if isinstance(s, dict) and (M.num(s.get("t")) or 0) == last_t),
            "held": held_addrs, "ever": ever_addrs, "weights": weights, "winfo": winfo, "detail": winfo.get("detail") or {}, "wins": wins, "bot_closed": bot_closed}


# ---------------------------------------------------------------- charts (inline SVG in CSS pixels; a wide and a narrow variant per chart)
def line_chart(series, budget, width, height=240):
    """series: [(name, css class, [(t, v)])]. Hover: crosshair + tooltip via the page script (data-pts on the overlay)."""
    pts_all = [(t, v) for _, _, pts in series for t, v in pts]
    if len(pts_all) < 2:
        return ""
    ml, mr, mt, mb = 44, 72, 14, 28
    pw, ph = width - ml - mr, height - mt - mb
    t0, t1 = min(t for t, _ in pts_all), max(t for t, _ in pts_all)
    if t1 == t0:
        t1 = t0 + 1
    lo, hi, ticks = domain([v for _, v in pts_all] + [budget])
    X = lambda t: ml + (t - t0) / (t1 - t0) * pw
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Equity per run">' % (width, height, width, height)]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%g</text>' % (ml, y, ml + pw, y, ml - 6, y + 4, tk))
    yb = Y(budget)
    out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f">start %g</text>' % (ml, yb, ml + pw, yb, ml + pw + 4, yb + 4, budget))
    n_lab = min(5 if width > 700 else 3, len({t for t, _ in pts_all}))
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
        out.append('<text class="label" x="%.1f" y="%.1f">%.2f</text>' % (x, y, v))
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
        out.append('<line class="%s" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%g</text>' % ("axis" if tk == 0 else "grid", ml, y, ml + pw, y, ml - 6, y + 4, tk))
    if baseline is not None:
        yb = Y(baseline)
        out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">price unchanged %+.2f</text>' % (ml, yb, ml + pw, yb, ml + pw - 4, yb - 4, baseline))
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
            out.append('<g class="bar %s" data-tip="%s · %s: %+.2f">%s</g>' % (cls, E(label), E(name), v, bar_path(x, Y(0), Y(v), bw)))
    out.append("</svg>")
    return "".join(out)


def weight_bars(weights, detail, width):
    """Horizontal diverging bars around 0: positive weights to the right (blue), negative to the left (orange)."""
    if not weights:
        return ""
    rowh, ml, mr = 22, 230 if width > 700 else 190, 54
    height = rowh * len(weights) + 22
    pw = width - ml - mr
    mx = max(abs(v) for _, v in weights) or 1
    cx = ml + pw / 2
    half = pw / 2 - 46                         # room for the value label on either side
    S = lambda v: v / mx * half
    out = ['<svg class="chart-svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Factor weights in use">' % (width, height, width, height)]
    ticks, step = clean_ticks(-mx, mx, 4)
    for tk in ticks:
        if abs(tk) > mx * 1.001 or tk == 0:
            continue
        x = cx + S(tk)
        out.append('<line class="grid" x1="%.1f" y1="4" x2="%.1f" y2="%d"/><text class="tick" x="%.1f" y="%d" text-anchor="middle">%+g</text>' % (x, x, height - 16, x, height - 4, tk))
    out.append('<line class="axis" x1="%.1f" y1="4" x2="%.1f" y2="%d"/>' % (cx, cx, height - 16))
    for i, (k, v) in enumerate(weights):
        y = 6 + i * rowh
        n = (detail.get(k) or {}).get("n")
        lab = factor_label(k)
        out.append('<text class="label" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml - 8, y + 12, E(lab if width > 700 or len(lab) <= 26 else lab[:25] + "…")))
        x1 = cx + S(v)
        out.append('<g class="bar %s" data-tip="%s (%s): %+.3f%s">%s</g>' % ("pos" if v >= 0 else "neg", E(lab), E(k), v, (" · from %d coin results" % n) if n else " · prior", hbar_path(cx, x1, y + 2, 12)))
        out.append('<text class="tick" x="%.1f" y="%.1f" text-anchor="%s">%+.2f</text>' % ((x1 + 6) if v >= 0 else (x1 - 6), y + 12, "start" if v >= 0 else "end", v))
    out.append("</svg>")
    return "".join(out)


def chart_box(wide, narrow, legend="", scroll_end=False):
    """One card holding the desktop and the phone variant of a chart (CSS shows one of them)."""
    return '<div class="chart%s"><div class="wide">%s</div><div class="narrow">%s</div>%s</div>' % (" scroll-end" if scroll_end else "", wide, narrow, legend)


# ---------------------------------------------------------------- page
CSS = r"""
/* Layout: one 1100px column; a hero row of figures, then sections scanned top to bottom. Charts are drawn in CSS px: a desktop
   variant at the column width and a phone variant that scrolls inside its card. */
:root { --bg:#f5f6f8; --surface:#ffffff; --fg:#14171c; --fg2:#4b535e; --muted:#667080; --line:#e2e5ea; --line2:#eef0f3;
  --accent:#2a78d6; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#006300; --good-mark:#0ca30c; --bad:#c7342f; --bad-mark:#d03b3b; --warn:#9a5b00;
  --chip:#eef2f7; --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#8a929d; --line:#2a2f37; --line2:#22262d;
  --accent:#3987e5; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --chip:#232830; color-scheme:dark } }
:root[data-theme="dark"] { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#8a929d; --line:#2a2f37; --line2:#22262d;
  --accent:#3987e5; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --chip:#232830; color-scheme:dark }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 var(--sans); }
.wrap { max-width:1100px; margin:0 auto; padding-inline:16px; padding-block:24px 48px; display:grid; gap:28px }
.wrap > *, section > *, details { min-width:0 }
h1,h2,h3 { margin:0; text-wrap:balance; line-height:1.2 }
h1 { font-size:22px; font-weight:600 }
h2 { font-size:16px; font-weight:600 }
.eyebrow { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500 }
header { display:flex; flex-wrap:wrap; gap:8px 24px; align-items:baseline; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:14px }
header .meta { color:var(--fg2); font-size:13px; display:flex; flex-wrap:wrap; gap:4px 16px }
section { display:grid; gap:12px }
.sec-head { display:flex; flex-wrap:wrap; gap:4px 16px; align-items:baseline; justify-content:space-between }
.sec-head p { margin:0; color:var(--fg2); font-size:13px }
.hero { display:grid; grid-template-columns:minmax(240px,1.5fr) repeat(auto-fit,minmax(140px,1fr)); gap:12px }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; display:grid; gap:2px; align-content:start }
.tile .label { font-size:12px; color:var(--muted) }
.tile .value { font-size:20px; font-weight:600; letter-spacing:-.01em }
.tile.lead .value { font-size:44px; line-height:1.05 }
.tile .sub { font-size:12px; color:var(--fg2) }
.delta { font-weight:500; font-size:15px } .tile.lead .delta { display:block; font-size:20px; margin-top:2px } .delta.good { color:var(--good) } .delta.bad { color:var(--bad) }
.chart { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; display:grid; gap:8px }
.chart .narrow { display:none } .chart-svg { display:block; max-width:100%; height:auto; font-family:var(--sans) }
.chart .narrow .chart-svg { max-width:none }
.chart-svg .grid { stroke:var(--line2); stroke-width:1 } .chart-svg .axis { stroke:var(--line); stroke-width:1 } .chart-svg .ref { stroke:var(--muted); stroke-width:1 }
.chart-svg .tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums } .chart-svg .label { fill:var(--fg2); font-size:11px }
.chart-svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round } .chart-svg .line.s1 { stroke:var(--s1) } .chart-svg .line.s2 { stroke:var(--s2) }
.chart-svg .area.s1 { fill:var(--s1); opacity:.1 } .chart-svg .dot { stroke:var(--surface); stroke-width:2 } .chart-svg .dot.s1 { fill:var(--s1) } .chart-svg .dot.s2 { fill:var(--s2) }
.chart-svg .bar.s1 { fill:var(--s1) } .chart-svg .bar.s2 { fill:var(--s2) } .chart-svg .bar.s3 { fill:var(--s3) } .chart-svg .bar.pos { fill:var(--s1) } .chart-svg .bar.neg { fill:var(--s2) }
.chart-svg .bar:hover { opacity:.8 } .chart-svg .cross { stroke:var(--muted); stroke-width:1 }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; font-size:12px; color:var(--fg2) }
.legend span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; background:var(--c) }
.tip { position:fixed; pointer-events:none; background:var(--fg); color:var(--bg); font-size:12px; padding:6px 8px; border-radius:6px; max-width:280px; opacity:0; transition:opacity .08s; z-index:10; white-space:pre-line }
.tip.on { opacity:1 }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px }
.card { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; display:grid; gap:8px }
.card .top { display:flex; justify-content:space-between; gap:12px; align-items:baseline; flex-wrap:wrap }
.card .sym { font-size:18px; font-weight:600 } .name { color:var(--fg2); font-size:12px; margin-left:6px }
.chip { display:inline-block; font-size:11px; font-weight:500; padding:2px 8px; border-radius:999px; background:var(--chip); color:var(--fg2); white-space:nowrap }
.chip.good { background:color-mix(in srgb,var(--good-mark) 16%,var(--surface)); color:var(--good) } .chip.bad { background:color-mix(in srgb,var(--bad-mark) 16%,var(--surface)); color:var(--bad) }
.chip.neutral { background:color-mix(in srgb,var(--accent) 14%,var(--surface)); color:var(--accent) }
.kv { display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:6px 12px; font-size:13px }
.kv div { min-width:0 } .kv .k { color:var(--muted); font-size:11px } .kv .v { font-variant-numeric:tabular-nums; white-space:nowrap }
.kv .v.wrap { white-space:normal }
.why { font-size:13px; color:var(--fg2); margin:0 } .safety { font-size:13px; margin:0 }
.links { display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12px } a { color:var(--accent); text-decoration:none } a:hover,a:focus-visible { text-decoration:underline }
.addr { font-family:var(--mono); font-size:11px; color:var(--muted); overflow-wrap:anywhere }
.tbl { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px }
table { border-collapse:collapse; width:100%; font-size:13px } th,td { text-align:left; padding:8px 12px; border-top:1px solid var(--line2); vertical-align:top }
th { color:var(--muted); font-weight:500; font-size:11px; letter-spacing:.04em; text-transform:uppercase; border-top:0; white-space:nowrap }
td.n,th.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap } td .good { color:var(--good) } td .bad { color:var(--bad) }
details { font-size:13px } summary { cursor:pointer; color:var(--fg2) } details .tbl { margin-top:8px }
.empty { background:var(--surface); border:1px dashed var(--line); border-radius:8px; padding:14px 16px; color:var(--fg2) } .empty code { font-family:var(--mono); font-size:12px; background:var(--chip); padding:1px 5px; border-radius:4px }
.note { font-size:13px; color:var(--fg2); margin:0; max-width:72ch }
.runs td.note-cell { min-width:36ch; max-width:60ch; white-space:normal; color:var(--fg2) }
footer { color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:14px; display:flex; flex-wrap:wrap; gap:4px 20px }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
@media (prefers-reduced-motion: reduce) { .tip { transition:none } }
@media (max-width:700px) { .chart .wide { display:none } .chart .narrow { display:block } }
@media (max-width:560px) { .tile.lead .value { font-size:36px } .hero { grid-template-columns:1fr 1fr } .hero .tile.lead { grid-column:1 / -1 }
  .runs table,.runs tbody,.runs tr,.runs td { display:block } .runs thead { display:none } .runs tr { padding:8px 0; border-top:1px solid var(--line2) }
  .runs td { border-top:0; padding:2px 12px; text-align:left; white-space:normal } .runs td.n { display:inline-block; padding-right:8px } .runs td.note-cell { min-width:0; max-width:none }
  .runs td.n::before { content:attr(data-k) " "; color:var(--muted); font-size:11px } }
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
  document.querySelectorAll('.chart.scroll-end').forEach(function(c){c.scrollLeft=c.scrollWidth;});
})();
"""


def tile(label, value, sub="", lead=False, delta=None):
    d = ""
    if delta is not None:
        d = '<span class="delta %s">%s</span>' % ("good" if delta > 0 else ("bad" if delta < 0 else ""), fmt_amt(delta, True))
    return '<div class="tile%s"><div class="label">%s</div><div class="value">%s%s</div>%s</div>' % (" lead" if lead else "", E(label), E(value), d, ('<div class="sub">%s</div>' % E(sub)) if sub else "")


def coin_links(a, pair=None, x=None):
    """(label, url) for the chart, safety and trading sites that take a Solana mint address in the URL."""
    a = str(a or "")
    out = [("DexScreener", "https://dexscreener.com/solana/%s" % (pair or a)), ("RugCheck", "https://rugcheck.xyz/tokens/%s" % a),
           ("Jupiter", "https://jup.ag/swap/SOL-%s" % a), ("GMGN", "https://gmgn.ai/sol/token/%s" % a),
           ("Birdeye", "https://birdeye.so/token/%s?chain=solana" % a), ("Solscan", "https://solscan.io/token/%s" % a)]
    if a.endswith("pump"):
        out.append(("pump.fun", "https://pump.fun/coin/%s" % a))
    if str(x or "").startswith("https://"):
        out.append(("X", str(x)))
    return out


def links(p):
    return '<div class="links">%s</div>' % "".join('<a href="%s" target="_blank" rel="noopener">%s</a>' % (E(u), E(n)) for n, u in coin_links(p.get("addr"), p.get("pair"), p.get("x")))


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
          ("sold so far", fmt_amt(r["back"])), ("score", ("%.0f" % sc if sc is not None else "–") + " (rank %s)" % (p.get("rank") or "?")),
          ("cap at buy", fmt_money(p.get("mc"))), ("liquidity at buy", fmt_money(p.get("liq"))), ("liquidity now", fmt_money(r["liq_now"]) if r["liq_now"] is not None else "–"),
          ("held", fmt_age(p.get("t"), now))]
    pnl = r["pnl"]
    pnl_html = ('<span class="delta %s">%s</span>' % ("good" if pnl > 0 else ("bad" if pnl < 0 else ""), fmt_amt(pnl, True))) if pnl is not None else ""
    return ('<article class="card"><div class="top"><div><span class="sym">%s</span><span class="name">%s</span></div><div>%s <span class="chip %s">%s</span></div></div>'
            '<div class="kv">%s</div><p class="safety">%s</p><p class="why">%s</p>%s<div class="addr">%s</div></article>') % (
        E(p.get("sym")), E(p.get("name")), pnl_html, r["kind"], E(r["status"]),
        "".join('<div><div class="k">%s</div><div class="v%s">%s</div></div>' % (E(k), " wrap" if k == "sells" else "", E(v)) for k, v in kv),
        E(p.get("safety") or ""), E((p.get("why") or "").split("; RugCheck")[0]), links(p), E(p.get("addr")))


def closed_table(rows):
    if not rows:
        return '<div class="empty">No closed trades yet.</div>'
    tr = []
    for r in rows:
        p = r["p"]
        days = ((r["exit_t"] or 0) - (M.num(p.get("t")) or 0)) / 86_400_000 if r["exit_t"] else None
        sold_at = ", ".join(("%.2fx" % m if m is not None else "–") + (" (half)" if half else "") for m, half in r["sold_at"]) or "–"
        tr.append('<tr><td><strong>%s</strong><span class="name">%s</span></td><td>%s</td><td>%s</td><td><span class="chip %s">%s</span></td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n"><span class="%s">%s</span></td><td class="n">%s</td></tr>' % (
            E(p.get("sym")), E(p.get("name")), "bot" if r["bot"] else "random", fmt_dt(p.get("t"), True), r["kind"], E(r["status"]), E(sold_at), fmt_amt(r["ticket"]), fmt_amt(r["back"]),
            "good" if r["pnl"] > 0 else "bad", fmt_amt(r["pnl"], True), ("%.1f d" % days) if days is not None else "–"))
    return '<div class="tbl"><table><thead><tr><th>coin</th><th>group</th><th>bought</th><th>sold because</th><th class="n">sold at</th><th class="n">paid</th><th class="n">came back</th><th class="n">result</th><th class="n">held</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def big_section(big):
    if not big:
        return '<div class="empty">The big test starts after the first full scan has been priced again 24 hours later. Every full scan saves all its coins; the next day each one is checked: what would 20 in it have become?</div>'
    shown = big[-10:]
    groups = [(fmt_dt(g["t0"], True), fmt_dt(g["t0"], day=True), {"pass": g["passAvg"], "top": g["topAvg"], "fail": g["failAvg"]}) for g in shown]
    series = [("pass", "passed the gates", "s1"), ("top", "bot's top 10", "s2"), ("fail", "failed a gate", "s3")]
    legend = '<div class="legend">%s</div>' % "".join('<span style="--c:var(--%s)">%s</span>' % (cls, E(name)) for _, name, cls in series)
    chart = chart_box(grouped_bars(groups, series, WIDE, FLAT), grouped_bars(groups, series, NARROW, FLAT), legend, scroll_end=True)
    tr = "".join('<tr><td>%s</td><td class="n">%d</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
        fmt_dt(g["t0"], True), g["n"], g["passN"], fmt_amt(g["passAvg"], True), g["topN"], fmt_amt(g["topAvg"], True), g["failN"], fmt_amt(g["failAvg"], True),
        share(g["up"], g["n"]), share(g["gone"], g["n"])) for g in reversed(big))
    table = ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>scan</th><th class="n">coins</th><th class="n">passed gates · avg</th><th class="n">top 10 · avg</th>'
             '<th class="n">failed a gate · avg</th><th class="n">up after 24h</th><th class="n">price vanished</th></tr></thead><tbody>%s</tbody></table></div></details>') % tr
    return chart + table


def weights_section(D):
    if not D["weights"]:
        return ""
    lam, n = D["winfo"]["lambda"], D["winfo"]["n"]
    note = ("Learned weights count for %d%% (%d coin results scored so far, one per coin and scan); the hand-made prior fills the rest. Each bar is a factor's weight in the score: positive means higher is better." % (round(100 * lam), n)
            if n else "Nothing learned yet: these are the hand-made prior weights. After ~600 scored big-test coin results they are fully replaced by each factor's rank correlation with the 24h result.")
    tr = "".join('<tr><td>%s</td><td class="addr">%s</td><td class="n"><span class="%s">%+.3f</span></td><td class="n">%s</td></tr>' % (
        E(factor_label(k)), E(k), "good" if v >= 0 else "bad", v, (D["detail"].get(k) or {}).get("n") or "prior") for k, v in D["weights"])
    table = ('<details><summary>Table view and glossary</summary><div class="tbl"><table><thead><tr><th>factor</th><th>key</th><th class="n">weight</th><th class="n">coin results</th></tr></thead><tbody>%s</tbody></table></div></details>') % tr
    legend = '<div class="legend"><span style="--c:var(--s1)">higher is better</span><span style="--c:var(--s2)">lower is better</span></div>'
    return chart_box(weight_bars(D["weights"], D["detail"], WIDE), weight_bars(D["weights"], D["detail"], NARROW), legend) + '<p class="note">%s</p>%s' % (E(note), table)


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
            flag, cls = "held", "neutral"
        elif a in ever:
            flag, cls = "bought before", ""
        elif ok is None:
            flag, cls = "no safety report", ""
        elif ok:
            flag, cls = "clean", "good"
        else:
            flag, cls = "flagged: " + txt.replace("RugCheck", "").strip(": "), "bad"
        src = ", ".join(SRC.get(t.split(":", 1)[0], "%s") % t.split(":", 1)[-1] for t in (x.get("src") or [])[:4])
        tr.append('<tr><td class="n">%s</td><td><strong>%s</strong></td><td class="n">%.0f</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td><td><span class="chip %s">%s</span></td><td><a href="https://dexscreener.com/solana/%s" target="_blank" rel="noopener">chart</a></td></tr>' % (
            E(int(M.num(x.get("rank")))), E(x.get("s")), M.num(x.get("sc")) or 0, fmt_money(x.get("mc")), fmt_money(x.get("liq")), fmt_money(x.get("vol")), E(src), cls, E(flag), E(a)))
    return '<div class="tbl"><table><thead><tr><th class="n">rank</th><th>coin</th><th class="n">score</th><th class="n">market cap</th><th class="n">liquidity</th><th class="n">24h volume</th><th>seen on</th><th>safety · why not bought</th><th></th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def short_note(note):
    return ". ".join(s for s in str(note or "").split(". ") if not s.startswith(("Weights:", "Bankroll:", "Saved all"))).strip()


def runs_table(runs):
    if not runs:
        return ""
    tr = "".join('<tr><td>%s</td><td>%s</td><td class="n" data-k="scanned">%s</td><td class="n" data-k="passed">%s</td><td class="n" data-k="buys">%d</td><td class="n" data-k="sells">%d</td><td class="note-cell">%s</td></tr>' % (
        fmt_dt(r.get("t"), True), E(r.get("mode")), E(r.get("scanned") or "–"), E(r.get("passed") or "–"), len([p for p in (r.get("picks") or []) if isinstance(p, dict) and p.get("grp") == "pick"]),
        len(r.get("exits") or []), E(short_note(r.get("note")))) for r in runs[:12] if isinstance(r, dict))
    return '<div class="tbl runs"><table><thead><tr><th>when</th><th>mode</th><th class="n">scanned</th><th class="n">passed gates</th><th class="n">buys</th><th class="n">sells</th><th>what happened</th></tr></thead><tbody>%s</tbody></table></div>' % tr


def safe(name, fn):
    """A section that cannot be rendered (a malformed doc) shows a notice instead of taking the page down."""
    try:
        return fn()
    except Exception as e:
        return '<div class="empty">This section could not be rendered (%s: %s).</div>' % (E(name), E(str(e)[:120]))


def render(data, fragment=False):
    D = data
    st, cash, now = D["state"], D["cash"], D["now"]
    equity = D["equity"]
    nb = len(D["bot_closed"])
    best = max(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    worst = min(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    scored = sum(g["n"] for g in D["big"])
    worth_now = sum(r["value"] or 0 for r in D["open_bot"])
    eq_sub = "started with %g · fake money" % cash["budget"]
    if D["unpriced"]:
        eq_sub += " · %d open position%s with no price yet, counted at 0" % (len(D["unpriced"]), "" if len(D["unpriced"]) == 1 else "s")

    def hero():
        tiles = [tile("Equity if everything were sold now", fmt_amt(equity), eq_sub, lead=True, delta=equity - cash["budget"]),
                 tile("Free in the bankroll", fmt_amt(cash["free"]), "%d free slot%s of %g each" % (cash["slots"], "" if cash["slots"] == 1 else "s", cash["ticket"])),
                 tile("Deployed (at cost)", fmt_amt(cash["deployed"]), "%d open position%s · worth %s now" % (cash["open"], "" if cash["open"] == 1 else "s", fmt_amt(worth_now)) if cash["open"] else "no open position"),
                 tile("Closed trades", str(nb), ("%d won · %d lost" % (D["wins"], nb - D["wins"])) if nb else "none yet")]
        if nb == 1:
            tiles.append(tile("Only closed trade", fmt_amt(best["pnl"], True), best["p"].get("sym")))
        else:
            tiles.append(tile("Best / worst trade", ("%s / %s" % (fmt_amt(best["pnl"], True), fmt_amt(worst["pnl"], True))) if best else "–", ("%s / %s" % (best["p"].get("sym"), worst["p"].get("sym"))) if best else ""))
        tiles.append(tile("Big test", ("%d scan%s" % (len(D["big"]), "" if len(D["big"]) == 1 else "s")) if scored else "–",
                          ("%d coin results after 24h, %d different coins" % (scored, D["seen_coins"])) if scored else "after the first scan"))
        return '<section class="hero">%s</section>' % "".join(tiles)

    def curve():
        pts_bot = [(M.num(c["t"]), M.num(c.get("equity")) if M.num(c.get("equity")) is not None else cash["budget"] + (M.num(c.get("bot")) or 0)) for c in D["curve"] if isinstance(c, dict) and M.num(c.get("t"))]
        series = [("bot", "s1", pts_bot)]
        if any((M.num(c.get("nRand")) or 0) > 0 for c in D["curve"] if isinstance(c, dict)):
            series.append(("random control", "s2", [(M.num(c["t"]), cash["budget"] + (M.num(c.get("rand")) or 0)) for c in D["curve"] if isinstance(c, dict) and M.num(c.get("t"))]))
        wide = line_chart(series, cash["budget"], WIDE)
        if not wide:
            body = '<div class="empty">The curve needs two runs. It shows the bankroll plus the value of the open positions after every run.</div>'
        else:
            legend = '<div class="legend"><span style="--c:var(--s1)">bot</span><span style="--c:var(--s2)">random control</span></div>' if len(series) > 1 else ""
            body = chart_box(wide, line_chart(series, cash["budget"], NARROW), legend, scroll_end=True)
            body += ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>run</th><th class="n">equity</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (
                '<th class="n">random control</th>' if len(series) > 1 else "",
                "".join('<tr><td>%s</td><td class="n">%s</td>%s</tr>' % (fmt_dt(t), fmt_amt(v), ('<td class="n">%s</td>' % fmt_amt(series[1][2][i][1])) if len(series) > 1 and i < len(series[1][2]) else "") for i, (t, v) in enumerate(pts_bot))))
        return '<section><div class="sec-head"><h2>Equity per run</h2><p>bankroll plus what the open positions would fetch, after fees · now %s</p></div>%s</section>' % (fmt_amt(equity), body)

    def bought():
        n_bot, n_rand = len(D["open_bot"]), len(D["open"]) - len(D["open_bot"])
        head = "%d open%s · each bought for %g · sold half at 2x (the rest if it falls back to entry), all at −50%%, after 3 days, or when the price is gone" % (
            n_bot, (" plus %d random control" % n_rand) if n_rand else "", cash["ticket"])
        body = ('<div class="cards">%s</div>' % "".join(position_card(r, now) for r in D["open"])) if D["open"] else \
            ('<div class="empty">No open positions. %s</div>' % ("The next pick run buys the two best coins when the bankroll has a free slot." if D["runs"] else "Run <code>python3 bot.py cycle</code> to start."))
        return '<section><div class="sec-head"><h2>Bought coins</h2><p>%s</p></div>%s</section>' % (E(head), body)

    def candidates():
        if D["scan_t"]:
            head = "%s · %d coins scanned · ranked among those that passed the gates" % (fmt_dt(D["scan_t"]), int(D["scan_n"] or 0))
            run = D["scan_run"]
            if run:
                n_b = len([p for p in (run.get("picks") or []) if isinstance(p, dict) and p.get("grp") == "pick"])
                head += (" · %d bought from it" % n_b) if n_b else (" · nothing bought: this was a check run (no free slot, or a pick less than 3 h earlier)" if run.get("mode") == "check" else " · nothing bought: no top coin had a clean safety report")
        else:
            head = "no full scan yet"
        return '<section><div class="sec-head"><h2>Top candidates of the last full scan</h2><p>%s</p></div>%s</section>' % (E(head), cands_table(D))

    last_run = st.get("lastRun")
    scan_txt = ("last scan %s coins, %s passed the gates" % (E(st.get("scanned")), E(st.get("passed") or 0))) if st.get("scanned") else "no scan yet"
    head = ('<header><div><div class="eyebrow">paper trading · nothing is bought for real</div><h1>%s</h1></div>'
            '<div class="meta"><span>last run %s</span><span>%s run%s</span><span>%s</span><span>rule %s</span></div></header>') % (
        E(TITLE), E(fmt_dt(last_run)), E(st.get("runs") or 0), "" if st.get("runs") == 1 else "s", scan_txt, E(st.get("rule") or M.RULE))
    body = [head, safe("hero", hero)]
    if st.get("note"):
        body.append('<section><div class="eyebrow">Last run</div><p class="note">%s</p></section>' % E(st["note"]))
    body.append(safe("equity curve", curve))
    body.append(safe("bought coins", bought))
    body.append('<section><div class="sec-head"><h2>Closed trades</h2><p>what came back after fees, newest first</p></div>%s</section>' % safe("closed trades", lambda: closed_table(D["closed"])))
    body.append('<section><div class="sec-head"><h2>Big test: 24 hours later</h2><p>what 20 in each scanned coin was worth a day later, after fees · an unchanged price counts %+.2f (the two fees)</p></div>%s</section>' % (FLAT, safe("big test", lambda: big_section(D["big"]))))
    w_html = safe("weights", lambda: weights_section(D))
    if w_html:
        body.append('<section><div class="sec-head"><h2>Factor weights in use</h2><p>what the score rewards and punishes</p></div>%s</section>' % w_html)
    body.append(safe("candidates", candidates))
    if D["runs"]:
        body.append('<section><div class="sec-head"><h2>Run log</h2><p>last %d runs</p></div>%s</section>' % (min(12, len(D["runs"])), safe("run log", lambda: runs_table(D["runs"]))))
    body.append('<footer><span>generated %s</span><span>fees simulated at 0.5%%, minimum 0.81 per trade</span><span>prices from DexScreener at the time of each run</span><span>times in %s</span></footer>' % (E(fmt_dt(now)), TZ_NAME))
    content = '<div class="wrap">%s</div>\n<script>%s</script>' % ("\n".join(body), JS)
    head_html = ('<title>%s</title>\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">\n'
                 '<style>%s</style>') % (E(TITLE), CSS)
    if fragment:
        return head_html + "\n" + content
    return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n%s\n</head>\n<body>\n%s\n</body>\n</html>\n' % (head_html, content)


def build(d, out=None, now=None, fragment=False):
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
    a = ap.parse_args()
    print(build(a.dir, a.out, a.now, a.fragment))


if __name__ == "__main__":
    main()
