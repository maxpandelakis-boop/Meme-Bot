"""page_seeker.py: the fold "Rocket seeker 🔭" under "Tests on the side" on the Pick tab, and its numbers for the Start tab's box
(page_live.py). Fake money only: nothing here buys, signs or sends anything, and nothing here is advice. English words.

The Rocket seeker (seeker.py, seeker_watch.py, seeker.yml) is a test bot with money of its own: once a minute it scores each new
pump.fun graduation 30 minutes after its launch and buys the ones at its model's cut on paper. The user mixes up the accounts, so every
line says which bot this is and that it never trades for the Pick account or the Radar account 🚀.

doc(D) -> seeker.json as the scan copied it (D["dir"]/db/memebot/seeker.json), None without it
numbers(doc) -> {bal, closed, open, win, x2, x10, pts, since, t, checked} for the Start box, None without the doc
section(D, R) -> HTML: the fold: what it is, four tiles, how it buys and sells, its trades (open first), the last coins it checked, and
  the test it has to pass (pre-registered: research/seeker/PREREG-SEEKER-2026-10-26.md). Static HTML and CSS, no script; every chain
  string is escaped.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = "−"
NAME = "Rocket seeker 🔭"
TRADES_SHOWN = 120
CHECKS_SHOWN = 12
JUDGED = "Nov 27"            # PREREG: the buys of its first 30 days, judged once
BACKTEST = "−7.80 €"         # research/seeker/results/backtest.json, w4 top 2 % after the allowance, per 20 € trade
WHY = {"floor": "fell to half", "trail": "40% under its best", "24h": "after 24 h", "rug": "liquidity pulled (rug)"}


def num(v):
    return M.num(v)


def doc(D):
    try:
        d = json.load(open(os.path.join((D or {}).get("dir") or "", "db", "memebot", "seeker.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("book"), dict) else None


def numbers(d):
    if not d:
        return None
    bk = d.get("book") or {}
    sm = bk.get("summary") or {}
    closed = sorted((p for p in bk.get("closed") or [] if isinstance(p, dict) and num(p.get("eur")) is not None), key=lambda p: num(p.get("out")) or 0)
    pts, run = [], 0.0
    for p in closed:
        run += num(p["eur"])
        pts.append(run)
    cnt = d.get("counts") or {}
    return {"bal": (num(sm.get("eur")) or 0.0) + (num(sm.get("openEur")) or 0.0), "closed": int(num(sm.get("trades")) or 0),
            "open": int(num(sm.get("open")) or 0), "win": num(sm.get("inProfitOf10")), "x2": int(num(sm.get("x2")) or 0),
            "x10": int(num(sm.get("x10")) or 0), "pts": pts, "since": num(d.get("since")), "t": num(d.get("t")) or 0,
            "checked": int(num(cnt.get("scored")) or 0), "bought": int(num(cnt.get("bought")) or 0)}


def eur(v, signed=True):
    v = num(v)
    if v is None:
        return "–"
    return "%s%.2f €" % (MINUS if v < -0.004 else ("+" if signed and v > 0.004 else ""), abs(v))


def tone(v):
    v = num(v)
    return "good" if v is not None and v > 0.004 else ("bad" if v is not None and v < -0.004 else "")


def when(R, ms, fmt="%b %d, %H:%M"):
    try:
        return R.local(ms).strftime(fmt)
    except Exception:
        return "–"


def px_text(R, v):
    try:
        return R.fmt_px(v)
    except Exception:
        return "–" if not num(v) else "$%.3g" % num(v)


def tile(name, sub, big, cls=""):
    return '<div class="rs-tile"><span class="rs-tn">%s</span><b class="%s">%s</b><small>%s</small></div>' % (E(name), cls, E(big), E(sub))


def trade_row(p, R, now):
    px0 = num(p.get("px"))
    coin = '<td><b>%s</b><small>bought %s · score %s</small></td>' % (E(p.get("sym") or "?"), E(when(R, p.get("t"))), E("%.3f" % (num(p.get("score")) or 0)))
    best = num(p.get("best")) or 1.0
    if num(p.get("out")):
        m = num(p.get("mult")) or 0.0
        how = "%.2fx · best %.1fx · sold %s · %s" % (m, best, when(R, p.get("out")), WHY.get(p.get("why"), p.get("why") or ""))
        mid = '<td><span class="rs-px">%s → %s</span><small>%s</small></td>' % (E(px_text(R, px0)), E(px_text(R, px0 * m) if px0 else "–"), E(how))
        return '<tr>%s%s<td class="n %s">%s</td></tr>' % (coin, mid, tone(p.get("eur")), E(eur(p.get("eur"))))
    m = num(p.get("now")) or num(p.get("last"))
    end = (num(p.get("t")) or 0) + 24 * 3_600_000
    mid = '<td><span class="rs-px">%s → now %s</span><small>%s · best %.1fx · its 24 h end %s</small></td>' % (
        E(px_text(R, px0)), E(px_text(R, px0 * m) if px0 and m else "–"), E("%.2fx" % m if m else "no price yet"), best, E(when(R, end)))
    return '<tr class="rs-open">%s%s<td class="n">open</td></tr>' % (coin, mid)


def section(D, R):
    d = doc(D)
    now = (D or {}).get("now") or 0
    lead = ('<p class="rs-lead">A test bot with fake money of its own (20 € a coin). Once a minute it looks at every new pump.fun coin 30 minutes '
            'after its launch and buys the ones its model rates as rocket-like. It never buys or sells for the Pick account or the Radar account 🚀 '
            'and sends no push.</p>')
    rows_n = int(num(((d or {}).get("model") or {}).get("rows")) or 28279)
    how = ('<div class="rs-how"><p><b>How it picks</b> A model trained on 5 months of launches (%s coins) reads what the launch radar '
           'found at the launch (how long the coin took to launch, the creator\'s earlier hits, its X link, whether other coins with the same '
           'words launched that day) and the first 30 minutes of its chart. It buys the top 2 %% (about 3 to 5 coins a day).</p>'
           '<p><b>How it sells</b> Rocket hold, on minute closes: at half the buy price; once it doubled, 40 %% under its best; else after 24 hours.</p>'
           '<p><b>Its test</b> It counts only if its first 30 days pass the review bar (at least 40 trades, in profit after costs, also without its '
           'best trade), judged on %s. On the months it learned from, the same rule lost %s per 20 € trade: it found 3 times more rockets than '
           'chance, but not enough to pay for the rest.</p></div>') % ("{:,}".format(rows_n), E(JUDGED), E(BACKTEST))
    if not d:
        inner = lead + '<p class="rs-m">It starts with its first look; no coin checked yet.</p>' + how
        head = "starts soon · test bot"
    else:
        n = numbers(d)
        bk = d.get("book") or {}
        rows = sorted((p for p in bk.get("open", {}).values() if isinstance(p, dict)), key=lambda p: -(num(p.get("t")) or 0))
        rows += sorted((p for p in bk.get("closed") or [] if isinstance(p, dict)), key=lambda p: -(num(p.get("out")) or 0))
        win = "–" if n["win"] is None else ("%.1f" % n["win"]).rstrip("0").rstrip(".")
        tiles = '<div class="rs-tiles">%s%s%s%s</div>' % (
            tile("Balance", "sold + open, after fees", eur(n["bal"]), tone(n["bal"])), tile("Trades", "%d open · %s of 10 sold in profit" % (n["open"], win), "%d sold" % n["closed"]),
            tile("Rockets", "coins that reached 10x after its buy", "%d" % n["x10"]), tile("Checked", "coins scored · %d bought" % n["bought"], "{:,}".format(n["checked"])))
        since = '<small class="rs-m">Since %s · last look %s.</small>' % (E(when(R, n["since"])), E(when(R, n["t"], "%H:%M")))
        if rows:
            body = "".join(trade_row(p, R, now) for p in rows[:TRADES_SHOWN])
            tr = ('<details class="rs-tr" id="rocket-seeker-trades" open><summary>Its trades: %d open, %d sold</summary><div class="rs-scroll"><table class="rs-t">'
                  '<thead><tr><th>Coin</th><th>Buy → sell price</th><th>Result</th></tr></thead><tbody>%s</tbody></table></div>'
                  '<small class="rs-m">Prices in US dollars per coin, results in euro after the paper fees. Open coins at the price of its last look '
                  'before this page was made.</small></details>') % (n["open"], n["closed"], body)
        else:
            tr = '<p class="rs-m">No trade yet: no coin has reached its buy line so far.</p>'
        cut = num(d.get("cut")) or 0
        ck = [r for r in d.get("recent") or [] if isinstance(r, dict)][:CHECKS_SHOWN]
        li = []
        for r in ck:
            if num(r.get("score")) is not None and cut:
                say = "%d%% of the buy line%s" % (round(100 * num(r["score"]) / cut), " · bought" if r.get("buy") else "")
            else:
                say = {"liquidity": "too little liquidity", "no pair": "no price found", "no candles": "no chart found"}.get(r.get("why"), r.get("why") or "")
            li.append('<li class="%s"><span><b>%s</b> %s</span><small>%s</small></li>' % ("rs-buy" if r.get("buy") else "", E(r.get("sym") or "?"), E(when(R, r.get("t"), "%H:%M")), E(say)))
        checks = ('<details class="rs-tr"><summary>The last coins it checked</summary><ul class="rs-ck">%s</ul><small class="rs-m">It buys at 100%% of '
                  'its buy line. %s coins checked so far, %s missed (seen too late or without a price).</small></details>') % (
            "".join(li), "{:,}".format(n["checked"]), "{:,}".format(int(num((d.get("counts") or {}).get("missed")) or 0))) if li else ""
        inner = lead + tiles + since + tr + how + checks
        head = "%s · %d sold · %d open · test bot" % (eur(n["bal"]), n["closed"], n["open"])
    return ('<details class="fold rs-fold" id="rocket-seeker"><summary><span class="t">%s</span><span class="sum">%s</span></summary><div class="rs">%s</div></details>'
            '<style>%s</style>') % (E(NAME), E(head), inner, CSS)


CSS = r"""
/* the Rocket seeker's fold under Tests on the side (page_seeker.py) */
.rs { display:grid; grid-template-columns:minmax(0,1fr); gap:12px; min-width:0 } .rs > * { min-width:0 }
.rs-lead { margin:0; color:var(--fg2); font-size:var(--fs-s); max-width:70ch }
.rs-tiles { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px }
.rs-tile { display:grid; gap:2px; padding:10px; border:1px solid var(--line); border-radius:12px; min-width:0 }
.rs-tile .rs-tn { font-weight:600; font-size:var(--fs-s) } .rs-tile small { font-size:11px; color:var(--muted); overflow-wrap:anywhere }
.rs-tile b { font-size:16px; font-weight:650; overflow-wrap:anywhere; font-variant-numeric:tabular-nums } .rs-tile b.good { color:var(--good) } .rs-tile b.bad { color:var(--bad) }
.rs-how { display:grid; gap:6px; padding:12px; border:1px solid var(--line); border-radius:12px; font-size:var(--fs-s) } .rs-how p { margin:0 } .rs-how b { font-weight:600 }
.rs-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100% }
.rs-t { width:100%; border-collapse:collapse; font-size:12px }
.rs-t th { text-align:left; font-weight:500; color:var(--muted); font-size:11px; padding:4px 6px; border-bottom:1px solid var(--line) }
.rs-t td { padding:6px; border-bottom:1px solid var(--line2); vertical-align:top } .rs-t td b { font-weight:600 }
.rs-t td small { display:block; font-size:11px; color:var(--muted) }
.rs-t td.n, .rs-t th:last-child { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
.rs-t .rs-px { font-variant-numeric:tabular-nums; overflow-wrap:anywhere } .rs-t tr.rs-open td { background:color-mix(in srgb,var(--warn) 7%,transparent) }
.rs-t .good { color:var(--good) } .rs-t .bad { color:var(--bad) }
.rs-ck { margin:0; padding:0; list-style:none; display:grid; gap:2px }
.rs-ck li { display:flex; justify-content:space-between; gap:10px; font-size:12px; border-bottom:1px solid var(--line2); padding:4px 0 }
.rs-ck li small { color:var(--muted); white-space:nowrap } .rs-ck li.rs-buy small { color:var(--warn); font-weight:600 }
.rs-m { margin:0; font-size:11px; color:var(--muted) }
details.rs-tr > summary { color:var(--accent); font-weight:500; cursor:pointer; min-height:44px; display:flex; align-items:center }
"""
