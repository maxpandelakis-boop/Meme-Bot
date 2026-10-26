"""page_home.py: the Start tab (#pane-home), the first thing the app shows. Fake money only: nothing here buys, signs or sends anything,
and nothing here is advice. English words (the user's wish of Oct 22: the whole app in English).

The product has two accounts and a test, and this tab shows them at a glance:
  PICK   the full scan's paper account (50 € a pick, its sell rule unchanged)
  RADAR  the rocket hunter's own paper account (rocket_watch.py, 20 € a coin when its rocket score reaches the cut)
  LEARNING PICK  a self-learning shadow with its own paper account (lernpick.py)
pick_account(D, R) -> HTML: the Pick tab's account block (balance since the start, the open pick positions as cards, the last sells),
because the open Pick positions were only in the Archive. From memebot.LIVE_SELL_AT on (the Pick sells on the live chart) PK_LIVE_JS
reads the app's live row memebot.LIVE_WATCH_ROW and marks a card sold when the minute watch sold that position after the page was built,
until the next scan books it. sell_bot(D, R, opn) -> HTML: the same chart exit as a bot of its own
on top of that block (the user could not find it on Oct 24): each open position's price now and its next move, filled live by SB_JS.
section(D, R) -> HTML: the live panel (page_live.py). Since Oct 26 (the user: "mach es logisch und organisiert") it is the whole tab: one
box per account (Pick account with the Pick bot and the Sell bot, Radar account 🚀 with the Radar bot, the Learning Pick with its own bot),
each with its money and its bots' last move, clock and open coins, then the feed of the last day's buys, sells, rounds and scans. The
account cards on top and "Right now" (the pick and the rocket candidates, both on their own tabs) are gone: each bot shows once. Without
the live panel the account cards come back (acct_card, sell_bot_row, lern_row).
Every number comes from the page data (D) and rocket.json; nothing here changes a pick, a sell rule or an account. The Pick side counts the
paper account's pick positions only (the new launches ended on Oct 16 and live in the Archive tab). Every chain string is escaped.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = "−"


def num(v):
    return M.num(v)


def de_num(v, d=2):
    """1234.5 -> 1,234.50 with a real minus sign (English notation since Oct 22; the name stays, other pages call it)."""
    s = format(abs(v), ",.%df" % d)
    return (MINUS if v < 0 and s.strip("0,.") else "") + s


def de_eur(v, signed=False):
    v = num(v)
    if v is None:
        return "–"
    s = de_num(v) + " €"
    return ("+" + s) if signed and v > 0.004 else s


def tone(v):
    v = num(v)
    return "good" if v is not None and v > 0.004 else ("bad" if v is not None and v < -0.004 else "")


def hhmm(R, ms):
    try:
        return R.local(ms).strftime("%H:%M")
    except Exception:
        return "–"


def when(R, ms, now):
    """'12:08' today, else 'Oct 21 12:08'."""
    try:
        t, n = R.local(ms), R.local(now)
    except Exception:
        return "–"
    return t.strftime("%H:%M") if t.date() == n.date() else t.strftime("%b %d %H:%M")


def rocket_doc(D):
    try:
        doc = json.load(open(os.path.join((D or {}).get("dir") or "", "db", "memebot", "rocket.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("book"), dict) else None


def pick_book(D):
    """The paper account's pick positions since the restart: balance (closed results plus the open ones at their last price), closed and
    open counts, x of 10 closed in profit, 3x and 10x hits, and the balance after every closed trade. None without the account."""
    try:
        import page_account as PA
        A = PA._acct(D)
    except Exception:
        return None
    rows = [r for r in (A or {}).get("rows") or [] if isinstance(r, dict) and r.get("grp") != "young" and num(r.get("pnl")) is not None]
    if not isinstance(A, dict):
        return None
    closed = sorted((r for r in rows if not r.get("open")), key=lambda r: num(r.get("exitT")) or num(r.get("t")) or 0)
    opn = [r for r in rows if r.get("open")]
    mult = lambda r: (num(r.get("back")) or 0) / (num(r.get("ticket")) or 1)
    pts, run = [], 0.0
    for r in closed:
        run += num(r["pnl"])
        pts.append(run)
    return {"bal": sum(num(r["pnl"]) for r in rows), "closed": len(closed), "open": len(opn),
            "win": round(10 * sum(1 for r in closed if num(r["pnl"]) > 0) / len(closed), 1) if closed else None,
            "x3": sum(1 for r in closed if mult(r) >= 3), "x10": sum(1 for r in closed if mult(r) >= 10), "pts": pts, "rows": rows,
            "ticket": num(getattr(M, "TOP_TICKET", None)) or 50.0}


def rocket_book(doc):
    """The rocket hunter's account from rocket.json: the same numbers as pick_book."""
    if not doc:
        return None
    bk = doc.get("book") or {}
    sm = bk.get("summary") or {}
    closed = sorted((p for p in bk.get("closed") or [] if isinstance(p, dict) and num(p.get("eur")) is not None), key=lambda p: num(p.get("out")) or num(p.get("t")) or 0)
    pts, run = [], 0.0
    for p in closed:
        run += num(p["eur"])
        pts.append(run)
    return {"bal": (num(sm.get("eur")) or 0.0) + (num(sm.get("openEur")) or 0.0), "closed": int(num(sm.get("trades")) or 0), "open": int(num(sm.get("open")) or 0),
            "win": num(sm.get("inProfitOf10")), "x3": int(num(sm.get("x3")) or 0), "x10": int(num(sm.get("x10")) or 0), "pts": pts, "ticket": float(M.TICKET), "t": num(doc.get("t")) or 0}


def spark(pts, cls):
    """The balance after every closed trade as a small line (break-even dashed); a flat placeholder before two trades."""
    if len(pts) < 2:
        return '<svg class="hm-sp" viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true"><line class="z" x1="0" y1="15" x2="120" y2="15"/></svg>'
    vs = [0.0] + list(pts)
    lo, hi = min(vs), max(vs)
    hi = hi if hi - lo > 1e-9 else lo + 1
    xy = [(120.0 * i / (len(vs) - 1), 2 + 26 * (hi - v) / (hi - lo)) for i, v in enumerate(vs)]
    d = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", x, y) for i, (x, y) in enumerate(xy))
    z = 2 + 26 * hi / (hi - lo)
    return ('<svg class="hm-sp %s" viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true"><line class="z" x1="0" y1="%.1f" x2="120" y2="%.1f"/>'
            '<path class="a" d="%s L120 30 L0 30 Z"/><path class="l" d="%s"/></svg>') % (cls, z, z, d, d)


def since_words(R, ms):
    """'since Oct 22, 12:08' (Berlin; the page's own way to write a day), '' without a start."""
    try:
        return "since %s" % R.local(ms).strftime("%b %d, %H:%M") if num(ms) else ""
    except Exception:
        return ""


def acct_card(key, title, sub, b, empty, live=False, since=""):
    """One account card; live=True (the rocket hunter) adds the data-rk-* hooks page_rocket.LIVE_JS fills from the app's live row. since:
    the account's start in words (both accounts count from the same moment since the Pick's fresh start, memebot.FRESH_AT)."""
    head = '<div class="hm-k"><span class="hm-dot"></span>%s<small>%s</small></div>%s' % (
        E(title), E(sub), ('<small class="hm-since">%s</small>' % E(since)) if since else "")
    if not b:
        return ('<div class="hm-acc hm-%s">%s<p class="hm-empty">%s</p></div>') % (key, head, E(empty))
    h = (lambda k: ' data-rk-st="%s"' % k) if live else (lambda k: "")
    win = "–" if b["win"] is None else de_num(b["win"], 1).rstrip("0").rstrip(".")
    stats = [("in profit", ("<span%s>%s</span><small>/10</small>" % (h("win"), E(win))) if (b["win"] is not None or live) else "–"),
             ("3x · 10x", "<span%s>%d · %d</span>" % (h("hits"), b["x3"], b["x10"])),
             ("open", "<span%s>%d</span>" % (h("open"), b["open"]))]
    return ('<div class="hm-acc hm-%s"%s>%s'
            '<b class="hm-bal %s"%s>%s</b>%s<div class="hm-st">%s</div><small class="hm-n"><span%s>%d</span> closed · %s per buy · fake money</small></div>') % (
        key, (' data-rk-box data-rk-t="%d"' % int(b.get("t") or 0)) if live else "", head, tone(b["bal"]), " data-rk-bal" if live else "",
        E(de_eur(b["bal"], True)), spark(b["pts"], tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), v) for k, v in stats), h("closed"), b["closed"], E(de_eur(b["ticket"]).replace(".00", "")))


def lern_row(D, R):
    """The Learning Pick (lernpick.py, a self-learning shadow with its own paper account) as a slim row under the two accounts: its balance
    the way the Pick card counts it (sold trades plus the open ones at the last scan price, or at the sale their rule already made on the
    scan prices: lernpick.rule_on_marks; until Oct 25 a coin stopped out in its first hour counted at 14x here), the sold trades' result as the fold's summary
    line says it, how many open, since its first buy. A tap opens the Pick tab with its fold open (the user could not find it at the foot
    of the Pick tab, Oct 23). '' without the module or when it cannot be read."""
    try:
        import lernpick as L
        S = L.summary((D or {}).get("dir") or "", (D or {}).get("now"))
        me = S["me"]
    except Exception:
        return ""
    if me["n"]:
        big = '<b class="hm-bal %s">%s</b>' % (tone(me["pnl"]), E(de_eur(me["pnl"], True)))
        line = "%s%d open · %s per buy · fake money" % (("%d sold %s · " % (me["sold"], de_eur(me["closedPnl"], True))) if me["sold"] else "",
                                                       me["open"], de_eur(S.get("ticket") or 50).replace(".00", ""))
    else:
        big = '<b class="hm-bal">–</b>'
        line = "buys from the next scan · fake money" if (S.get("brain") or {}).get("buy") else "waiting for its first training · fake money"
    since = since_words(R, S.get("since"))
    return ('<label class="hm-acc hm-lp" for="tab-pick" data-go="pick" data-open="learning-pick">'
            '<span class="hm-k"><span class="hm-dot"></span>LEARNING PICK<small>shadow · learns every day · no push</small></span>'
            '%s%s<span class="hm-lpf"><small class="hm-n">%s</small><span class="hm-go">Open ›</span></span></label>') % (
        ('<small class="hm-since">%s</small>' % E(since)) if since else "", big, E(line))


PICK_WHY = {"tp": "11x reached", "stop": "stop −30%", "trail": "trailing stop", "drop": "fell %d%% in %d min" % (round(100 * M.CHART_DROP), M.CHART_DROP_MIN),
            "time": "after 6 h", "rug": "coin gone", "reset": "restart", "manual": "by hand"}    # trail and drop: the chart exit's own reasons
PICK_STOP_CHART = "stop −%d%%" % round(100 * M.CHART_STOP)     # the chart exit's stop (its floor)
PICK_SOLD = 5             # last sells in the Pick tab's account block


def pick_account(D, R):
    """The Pick tab's account block (the user could not find the open Pick positions on Oct 22; they sat in Archive > Three paper traders):
    the Pick account since its start (balance, the same stats as the Start card), every open pick position as the page's own position card
    (R.hold_card, tap opens: price since the buy, stop and target, the clock, the links), and the last sells.
    Display only; the account, its rule and the trades before the start stay where they were (Archive)."""
    now = D["now"]
    b = pick_book(D)
    since = since_words(R, ((D.get("paper") or {}).get("since")))
    ticket = de_eur(num(getattr(M, "TOP_TICKET", None)) or 50.0).replace(".00", "")
    head = ('<div class="pk-head"><div><h3>Pick account</h3><small>hourly pick · %s</small></div><span class="chip warn">fake money</span></div>' % E(
        " · ".join(x for x in (since, "%s per buy" % ticket) if x)))
    if not b:
        return '<div class="pk" data-pa="pick">%s<p class="pk-s">No pick bought since the start yet.</p></div><style>%s</style>' % (head, PK_CSS)
    win = "–" if b["win"] is None else de_num(b["win"], 1).rstrip("0").rstrip(".")
    stats = [("in profit", "%s/10" % win), ("3x · 10x", "%d · %d" % (b["x3"], b["x10"])), ("open", str(b["open"])), ("closed", str(b["closed"]))]
    acct = ('<div class="pk-acct"><div class="pk-bal"><span class="k">Balance</span><b class="%s">%s</b>%s</div><div class="pk-sts">%s</div></div>') % (
        tone(b["bal"]), E(de_eur(b["bal"], True)), spark(b["pts"], tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), E(v)) for k, v in stats))
    opn = [r for r in D.get("open") or [] if isinstance(r, dict) and (r.get("p") or {}).get("grp") == "hold"]
    cards = []
    for r in opn:
        try:
            c = R.hold_card(r, now)
        except Exception:
            c = '<div class="pk-s">%s</div>' % E((r.get("p") or {}).get("sym") or "?")
        cards.append('<div class="pk-card" data-pk-card="%s">%s</div>' % (E((r.get("p") or {}).get("_id") or ""), c))     # PK_LIVE_JS marks it sold
    t0 = num((D.get("paper") or {}).get("since")) or 0
    before = sum(1 for r in opn if (num((r.get("p") or {}).get("t")) or 0) < t0)
    op_html = ('<div class="pk-st"><span class="k">Open positions (<span data-pk-n>%d</span>)%s</span><div class="holds">%s</div></div>' % (
        len(opn), (" · %d bought before the start, not counted" % before) if before else "", "".join(cards)) if opn else
        '<div class="pk-st"><span class="k">Open positions (0)</span><p class="pk-s">None right now. Every scan buys its pick on paper for %s.</p></div>' % E(ticket))
    op_html += pick_live(opn, now)
    closed = sorted((r for r in b["rows"] if not r.get("open")), key=lambda r: -(num(r.get("exitT")) or num(r.get("t")) or 0))[:PICK_SOLD]
    sold = []
    for r in closed:
        ex = [e for e in r.get("status") or [] if isinstance(e, dict)]
        why = str(ex[-1].get("why") or "") if ex else ""
        pct = num(r.get("pct"))
        bits = [("%s%s%%" % ("+" if pct > 0 else "", de_num(100 * pct, 0))) if pct is not None else "",
                PICK_STOP_CHART if why == "stop" and M.is_chart(r.get("p")) else PICK_WHY.get(why, why),
                when(R, num(r.get("exitT")), now) if num(r.get("exitT")) else ""]
        sold.append('<li class="%s"><b>%s</b><span>%s</span><em>%s</em></li>' % (
            tone(r.get("pnl")), E(str(r.get("sym") or "?")[:14]), E(" · ".join(x for x in bits if x)), E(de_eur(r.get("pnl"), True))))
    sold_html = ('<div class="pk-st"><span class="k">Recently sold</span><ul class="pk-sold">%s</ul></div>' % "".join(sold)) if sold else ""
    # Oct 26 clean-up: the Radar account "for comparison" left this block (each account once, both on the Start tab)
    live_at = M.live_sell_at()
    # Oct 25 clean-up: the rule in full behind a tap (the sell bot card above says what it does now)
    foot = ('<details class="pk-how"><summary>How it sells</summary><p class="pk-s">%s The trades before the start (%d) are in the archive under “Three paper traders”.</p></details>' % (
        E(("Sells on the live chart, every minute (the chart exit, since Oct 24): %d%% under its highest price once it has reached %gx, on a fall of %d%% "
           "within %d minutes, at −%d%%, at 11x or after 6 h, each at that minute. The fixed rule before it (−%d%%, 11x, 6 h) runs on as shadow rule K "
           "on the same trades.") % (round(100 * M.CHART_TRAIL), M.CHART_ARM, round(100 * M.CHART_DROP), M.CHART_DROP_MIN, round(100 * M.CHART_STOP),
                                    round(100 * M.HOLD_STOP)) if now >= live_at else "Sells at −30%, at 11x or after 6 h."),
        sum(1 for r in (D.get("paper") or {}).get("old") or [] if isinstance(r, dict) and (r.get("p") or {}).get("grp") == "hold")))
    js = ("<script>%s</script>" % PK_LIVE_JS) if "data-pk-box" in op_html else ""
    sb = sell_bot(D, R, opn)
    if sb:
        js += "<style>%s</style><script>%s</script>" % (SB_CSS, SB_JS)
    return '<div class="pk" data-pa="pick">%s%s%s%s%s%s</div><style>%s</style>%s' % (head, acct, sb, op_html, sold_html, foot, PK_CSS, js)


def pick_live(opn, now):
    """The ids of the open pick positions for PK_LIVE_JS (memebot.LIVE_SELL_AT on; '' before): a position the minute watch has sold since
    the page was built keeps its card, marked sold with its minute, why and its result until the next scan books it (Oct 26: it used to
    show its old price under "Open positions" and its sale a second time in a list of its own under it)."""
    if now < M.live_sell_at():
        return ""
    ids = [str((r.get("p") or {}).get("_id") or "") for r in opn if (r.get("p") or {}).get("_id")]
    return '<div class="pk-st pk-lv" data-pk-box data-pk-open="%s" hidden></div>' % E(json.dumps(ids, separators=(",", ":")))


# The sell bot: the Pick account's chart exit (memebot.chart_hit, run every minute by rocket_watch.py) shown as a bot of its own. The user
# could not find it on Oct 24 ("einen Bot, der die Coins rauspickt und dann noch einen Bot, der automatisch guckt ... und verkauft"): the
# position card showed only its floor and 11x, the rest sat in the grey line under it. Display only: the rule, the watch and the account
# stay as they are. SB_JS writes the same words from the live row memebot.LIVE_WATCH_ROW (its "pos": now / hi / lvl over cpx).
SB_WHY = {"trail": "profit lock", "drop": "fast fall", "stop": "emergency stop −%d%%" % round(100 * M.CHART_STOP), "tp": "11x reached",
          "time": "after 6 h"}


def sb_pct(x):
    """A multiple of the entry price as a change: 1.41 -> +41%, 0.5 -> −50%."""
    v = round(100 * (x - 1.0))
    return ("+" if v > 0 else (MINUS if v < 0 else "")) + "%d%%" % abs(v)


def sb_plan(R, entry, cpx, hi, lvl):
    """The sell bot's next move for one position in words (SB_JS's plan() writes the same): before the trail is armed, where it arms;
    after, the price it sells at. Prices over cpx (the rule's own basis), changes over the entry price (as the position card)."""
    if not entry or not cpx or M.unit_off(cpx, entry):
        return "Waiting for this coin's first minute candles."
    k = cpx / entry
    if hi and hi >= M.CHART_ARM and lvl:
        return "Profit lock ON: sells if the price falls to %s (%s), %d%% under its best price %s (%s)." % (
            R.fmt_px(lvl * cpx), sb_pct(lvl * k), round(100 * M.CHART_TRAIL), R.fmt_px(hi * cpx), sb_pct(hi * k))
    return "Profit lock switches on at %s (%s), then it sells as soon as the price falls %d%% under its best price.%s" % (
        R.fmt_px(M.CHART_ARM * cpx), sb_pct(M.CHART_ARM * k), round(100 * M.CHART_TRAIL), (" Best so far %s." % sb_pct(hi * k)) if hi else "")


def sb_watch(D):
    """The minute watch's row as the scan read it right before its run (pickwatch.json, bot.live_watch_in), {} without it."""
    try:
        doc = M.load_json(os.path.join(D.get("dir") or "", M.LIVE_WATCH_ROW + ".json"), None)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def sell_bot(D, R, opn):
    """The Pick tab's sell bot card (id sell-bot, the Start row opens it): what it does in one line, each open chart-exit position with
    its price now and its next move (sb_plan), the other ways out with the minute of the 6-hour limit, its last look. '' before the chart
    exit (memebot.LIVE_SELL_AT)."""
    now = D["now"]
    if now < M.live_sell_at():
        return ""
    w = sb_watch(D)
    rows = []
    for r in opn:
        p = r.get("p") or {}
        if not M.is_chart(p):
            continue
        entry, ref = num(r.get("entry")), num(r.get("cpx")) or num(r.get("entry"))
        t_buy = num(p.get("entryAt")) or num(p.get("t")) or now
        hc = M.chart_hit(r.get("candles") or [], t_buy, None, ref) if ref else {}
        last = num(r.get("last"))
        end = M.hold_end(t_buy)
        rows.append(('<div class="sb-pos" data-sb-pos="%s" data-sb-px="%s" data-sb-cpx="%s"><div class="sb-row"><b>%s</b><span class="sb-now %s" data-sb-now>%s</span></div>'
                     '<p class="sb-plan" data-sb-plan>%s</p><small class="sb-also">Also sells on a fall of %d%% within %d minutes, at −%d%% (emergency stop), '
                     'at 11x, and at the latest at %s (after 6 h).</small></div>') % (
            E(p.get("_id") or r.get("id") or ""), E(repr(entry) if entry else ""), E(repr(ref) if ref else ""), E(str(p.get("sym") or "?")[:14]),
            tone((last / entry - 1) if last and entry else None), E(("now %s" % sb_pct(last / entry)) if last and entry else "no price yet"),
            E(sb_plan(R, entry, ref, hc.get("hi"), hc.get("lvl"))), round(100 * M.CHART_DROP), M.CHART_DROP_MIN, round(100 * M.CHART_STOP),
            E(hhmm(R, end) if end else "–")))
    t = num(w.get("t"))
    body = "".join(rows) or ('<p class="sb-empty">Nothing to sell right now. It takes over every coin the Pick buys and watches it every minute.</p>')
    return ('<div class="sb" id="sell-bot" data-sb><div class="sb-head"><span class="sb-ico" aria-hidden="true">🤖</span><div><h4>Sell bot</h4>'
            '<small>sells the Pick account\'s coins on the live chart · looks every minute</small></div>'
            '<span class="sb-look" data-sb-look>%s</span></div>%s</div>') % (E(("last look %s" % hhmm(R, t)) if t else "live"), body)


def sell_bot_row(D, R):
    """The sell bot on the Start tab: a slim row under the accounts (it has no account of its own: its sales are the Pick account's),
    what it watches, its last look; a tap opens the Pick tab at its card. SB_JS (on the page with the Pick tab's card) keeps it live.
    '' before the chart exit."""
    if D["now"] < M.live_sell_at():
        return ""
    syms = [str((r.get("p") or {}).get("sym") or "?")[:14] for r in D.get("open") or []
            if isinstance(r, dict) and (r.get("p") or {}).get("grp") == "hold" and M.is_chart(r.get("p"))]
    t = num(sb_watch(D).get("t"))
    line = ("watching %s every minute" % ", ".join(syms)) if syms else "nothing to sell right now · takes over the next pick"
    return ('<label class="hm-acc hm-lp hm-sb" for="tab-pick" data-go="pick" data-open="sell-bot">'
            '<span class="hm-k"><span class="hm-dot"></span>SELL BOT 🤖<small>for the Pick account · sells on the live chart</small></span>'
            '<span class="hm-lpf"><small class="hm-n" data-sb-sum>%s</small><span class="hm-go">Open ›</span></span></label>') % (
        E(line + ((" · last look %s" % hhmm(R, t)) if t else "")))


SB_JS = r"""
(function(){
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var card=document.querySelector('[data-sb]');
  if(!card||!/^https:\/\/[^\s\/]+$/.test(url)||!key||!window.fetch)return;
  var EVERY=45000,next=0,busy=false,MINUS='−',ARM=""" + repr(M.CHART_ARM) + r""",TRAIL=""" + repr(M.CHART_TRAIL) + r""",UX=""" + repr(M.UNIT_X) + r""";
  var WHY=""" + json.dumps(SB_WHY, ensure_ascii=False) + r""";
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function pct(x){var v=Math.round(100*(x-1));return (v>0?'+':(v<0?MINUS:''))+Math.abs(v)+'%';}
  function px(p){if(!(p>0))return '–';if(p>=1)return '$'+p.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    var d=-Math.floor(Math.log10(p))+3;return d>12?'$'+p.toPrecision(3):'$'+p.toFixed(d);}
  function eur(v){var s=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});return (v>0.004?'+':(v<-0.004?MINUS:''))+s+' €';}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function plan(entry,cpx,hi,lvl){if(!entry||!cpx)return "Waiting for this coin's first minute candles.";var k=cpx/entry;
    if(hi&&hi>=ARM&&lvl)return 'Profit lock ON: sells if the price falls to '+px(lvl*cpx)+' ('+pct(lvl*k)+'), '+Math.round(100*TRAIL)+'% under its best price '+px(hi*cpx)+' ('+pct(hi*k)+').';
    return 'Profit lock switches on at '+px(ARM*cpx)+' ('+pct(ARM*k)+'), then it sells as soon as the price falls '+Math.round(100*TRAIL)+'% under its best price.'+(hi?' Best so far '+pct(hi*k)+'.':'');}
  function apply(d){
    var pos=d.pos&&typeof d.pos==='object'?d.pos:{},sold=d.sold&&typeof d.sold==='object'?d.sold:{},t=n(d.t),watched=[],gone=[];
    [].forEach.call(card.querySelectorAll('[data-sb-pos]'),function(b){
      var id=b.getAttribute('data-sb-pos'),w=pos[id],x=sold[id],entry=n(b.getAttribute('data-sb-px')),now=b.querySelector('[data-sb-now]'),pl=b.querySelector('[data-sb-plan]');
      var sym=(b.querySelector('b')||{}).textContent||'?';
      if(x&&typeof x==='object'&&n(x.at)){var v=n(x.pnl)||0;
        if(now){now.textContent='sold '+(n(x.mult)?pct(n(x.mult)):'');now.className='sb-now '+(v>0.004?'good':(v<-0.004?'bad':''));}
        if(pl)pl.textContent='Sold at '+hhmm(n(x.at))+' by the '+(WHY[x.why]||String(x.why||''))+': '+eur(v)+'. The next scan books it.';
        var al=b.querySelector('.sb-also');if(al)al.setAttribute('hidden','');
        gone.push(sym+' '+eur(v));return;}
      if(!w||typeof w!=='object')return;
      var cpx=n(w.cpx)||n(b.getAttribute('data-sb-cpx')),m=n(w.now);watched.push(sym);
      if(cpx&&entry&&(cpx/entry>UX||cpx/entry<1/UX))cpx=null;     // the pool's other coin (memebot.UNIT_X): no chart of its own yet
      if(now&&m&&cpx&&entry){var c=m*cpx/entry;now.textContent='now '+pct(c);now.className='sb-now '+(c>1.004?'good':(c<0.996?'bad':''));}
      if(pl)pl.textContent=plan(entry,cpx,n(w.hi),n(w.lvl));
    });
    var lk=card.querySelector('[data-sb-look]');if(lk&&t)lk.textContent='last look '+hhmm(t);
    [].forEach.call(document.querySelectorAll('[data-sb-sum]'),function(e){
      var s=watched.length?'watching '+watched.join(', ')+' every minute':(gone.length?'sold '+gone.join(', '):'nothing to sell right now · takes over the next pick');
      e.textContent=s+(t?' · last look '+hhmm(t):'');});
  }
  function want(){if(document.visibilityState==='hidden')return false;var a=document.getElementById('tab-pick'),b=document.getElementById('tab-home');
    return (!a&&!b)||(a&&a.checked)||(b&&b.checked);}
  function poll(){
    if(busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+EVERY;
    var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    fetch(url+'/rest/v1/live?select=doc&id=eq.""" + M.LIVE_WATCH_ROW + r"""',{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status;return r.json();})
      .then(function(rows){var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;if(d&&typeof d==='object')apply(d);})
      .catch(function(){next=Date.now()+2*EVERY;})
      .then(function(){clearTimeout(tm);busy=false;});
  }
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&(e.target.id==='tab-pick'||e.target.id==='tab-home'))poll();});
  setInterval(poll,5000);poll();
})();
"""


SB_CSS = r"""
/* the sell bot (page_home.sell_bot): its own card in the Pick account block, a row on the Start tab */
.sb { display:grid; gap:10px; padding:12px 14px; border-radius:14px; border:1px solid color-mix(in srgb,var(--good) 45%,var(--line));
  background:linear-gradient(135deg, color-mix(in srgb,var(--good) 12%,transparent), transparent 70%), var(--surface); scroll-margin-top:70px }
.sb-head { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:4px 10px }
.sb-ico { font-size:24px; line-height:1 } .sb-head h4 { margin:0; font-size:17px } .sb-head small { font-size:var(--fs-xs); color:var(--fg2) }
.sb-look { grid-column:2; justify-self:start; font-size:11px; padding:2px 8px; border-radius:999px; white-space:nowrap; color:var(--good);
  background:color-mix(in srgb,var(--good) 14%,transparent) }
.sb-pos { display:grid; gap:4px; padding:10px 12px; border-radius:12px; background:color-mix(in srgb,var(--bg) 55%,transparent); border:1px solid var(--line) }
.sb-row { display:flex; justify-content:space-between; align-items:baseline; gap:10px } .sb-row b { font-size:16px }
.sb-now { font-weight:600; font-variant-numeric:tabular-nums } .sb-now.good { color:var(--good) } .sb-now.bad { color:var(--bad) }
.sb-plan { margin:0; font-size:var(--fs-s); color:var(--fg); overflow-wrap:anywhere } .sb-also { font-size:var(--fs-xs); color:var(--muted) }
.sb-empty { margin:0; font-size:var(--fs-s); color:var(--fg2) } .sb [hidden] { display:none !important }
.hm-sb .hm-dot { background:var(--good); box-shadow:0 0 10px var(--good) }
"""


# the Pick account's minute watch (memebot.LIVE_SELL_AT): the app's live row memebot.LIVE_WATCH_ROW, read while the Pick tab is open, every
# 45 s, the same way page_rocket.LIVE_JS reads the Radar's; text only (no HTML from the row)
PK_LIVE_JS = r"""
(function(){
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var box=document.querySelector('[data-pk-box]');
  if(!box||!/^https:\/\/[^\s\/]+$/.test(url)||!key||!window.fetch)return;
  var ids;try{ids=JSON.parse(box.getAttribute('data-pk-open')||'[]');}catch(e){ids=[];}
  var EVERY=45000,next=0,busy=false,MINUS='−',WHY=""" + json.dumps(SB_WHY, ensure_ascii=False) + r""";
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function de(v,d){var s=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});return (v<0&&/[1-9]/.test(s)?MINUS:'')+s;}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function pct(m){var v=Math.round(100*(m-1));return (v>0?'+':(v<0?MINUS:''))+Math.abs(v)+'%';}
  function apply(d){
    var sold=d.sold&&typeof d.sold==='object'?d.sold:{},gone=0;
    ids.forEach(function(id){var x=sold[id],c=document.querySelector('[data-pk-card="'+(window.CSS&&CSS.escape?CSS.escape(id):id)+'"]');
      if(!x||typeof x!=='object'||!n(x.at)||!c)return;gone++;
      var v=n(x.pnl)||0,note=c.querySelector('.pk-gone-note');
      if(!note){note=document.createElement('p');note.className='pk-gone-note';c.insertBefore(note,c.firstChild);}
      note.className='pk-gone-note '+(v>0.004?'good':(v<-0.004?'bad':''));
      note.textContent='Sold at '+hhmm(n(x.at))+' by the Sell bot · '+[WHY[x.why]||String(x.why||''),n(x.mult)?pct(n(x.mult)):'',(v>0.004?'+':'')+de(v,2)+' €'].filter(Boolean).join(' · ')+' · the next scan books it';
      c.classList.add('pk-gone');});
    var k=document.querySelector('[data-pk-n]');if(k)k.textContent=String(Math.max(0,ids.length-gone));
  }
  function want(){if(document.visibilityState==='hidden')return false;var a=document.getElementById('tab-pick');return !a||!!a.checked;}
  function poll(){
    if(busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+EVERY;
    var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    fetch(url+'/rest/v1/live?select=doc&id=eq.""" + M.LIVE_WATCH_ROW + r"""',{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status;return r.json();})
      .then(function(rows){var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;if(d&&typeof d==='object')apply(d);})
      .catch(function(){next=Date.now()+2*EVERY;})
      .then(function(){clearTimeout(tm);busy=false;});
  }
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&e.target.id==='tab-pick')poll();});
  setInterval(poll,5000);poll();
})();
"""


PK_CSS = r"""
/* the Pick tab's account block (page_home.pick_account), the same look as the rocket hunter's block on the Radar tab */
.pk-card { display:grid; gap:6px } .pk-gone > :not(.pk-gone-note) { opacity:.45 }
.pk-gone-note { margin:0; padding:6px 10px; border-radius:10px; font-size:var(--fs-s); font-weight:500; background:var(--chip); color:var(--fg2) }
.pk-gone-note.good { color:var(--good); background:color-mix(in srgb,var(--good) 12%,transparent) } .pk-gone-note.bad { color:var(--bad); background:color-mix(in srgb,var(--bad) 12%,transparent) }
.pk { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:14px 16px 10px; display:grid; gap:12px; min-width:0; margin:0 0 12px;
  background-image:radial-gradient(120% 80% at 100% 0%, color-mix(in srgb,var(--accent) 14%,transparent), transparent 60%) }
.pk-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:4px 10px } .pk-head h3 { margin:0; font-size:19px }
.pk-head small { font-size:var(--fs-xs); color:var(--muted) }
.pk-acct { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:12px; align-items:center }
.pk-bal { display:grid; gap:2px; min-width:0 } .pk-bal b { font-size:28px; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; white-space:nowrap }
.pk-bal b.good { color:var(--good) } .pk-bal b.bad { color:var(--bad) }
.pk .k { font-size:var(--fs-xs); color:var(--muted) }
.pk-sts { display:grid; grid-template-columns:1fr 1fr; gap:6px }
.pk-sts > span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
.pk-sts i { font-style:normal; font-size:11px; color:var(--muted) } .pk-sts b { font-size:15px; font-variant-numeric:tabular-nums }
.pk-st { display:grid; gap:6px; min-width:0 } .pk-st .holds { display:grid; gap:8px; min-width:0 }
.pk-sold { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.pk-sold li { display:grid; grid-template-columns:minmax(0,1fr) auto; column-gap:10px; font-size:var(--fs-s) }
.pk-sold li span { grid-column:1; color:var(--fg2); font-size:var(--fs-xs) }
.pk-sold li em { grid-column:2; grid-row:1 / span 2; align-self:center; font-style:normal; font-variant-numeric:tabular-nums; font-weight:600 }
.pk-sold li.good em { color:var(--good) } .pk-sold li.bad em { color:var(--bad) }
.pk-s { margin:0; font-size:var(--fs-xs); color:var(--muted); max-width:70ch; overflow-wrap:anywhere }
.pk-how > summary { cursor:pointer; color:var(--accent); font-size:var(--fs-s); font-weight:500; min-height:44px; display:flex; align-items:center } .pk-how > p { margin-top:4px }
@media (max-width:420px) { .pk-acct { grid-template-columns:1fr } }
"""


def live_panel(D, R):
    """The live panel (page_live.py: the three accounts with their bots, each bot's clock, and the feed of buys and sells), '' without
    the module or when it fails (section then shows the account cards of before Oct 26 and says so)."""
    try:
        import page_live as PL
        return PL.section(D, R)
    except Exception as e:
        LIVE_ERR[0] = type(e).__name__
        return ""


LIVE_ERR = [""]


def section(D, R):
    lv = live_panel(D, R)
    if lv:
        body = lv
    else:
        # without the live panel: the two account cards, the sell bot's row and the Learning Pick's row (the Start tab before Oct 26)
        doc = rocket_doc(D)
        pk, rk = pick_book(D), rocket_book(doc)
        cards = (acct_card("pick", "PICK", "Pick account", pk, "No pick bought since the start yet.", since=since_words(R, (D.get("paper") or {}).get("since")))
                 + acct_card("rad", "RADAR", "Radar account 🚀", rk, "Starts with the first radar round.", live=True, since=since_words(R, getattr(M, "FRESH_AT", None))))
        lp = lern_row(D, R)
        sb = sell_bot_row(D, R)
        body = ('<div class="hm-hero"><div class="hm-ey">%s accounts · fake money · no real trades</div><div class="hm-accs">%s%s</div></div>'
                '<p class="hm-empty">The live view could not be built this time%s.</p>') % (
            "Three" if lp else "Two", cards, sb + lp, (" (%s)" % E(LIVE_ERR[0])) if LIVE_ERR[0] else "")
    return '<style>%s</style><section class="hm" data-home>%s</section><script>%s</script>' % (CSS, body, JS)


JS = r"""
(function(){
// a link on the Start tab opens its tab; in the installed app through its own tab switch (so the bottom bar follows), at the top, or
// with data-open at that fold, opened (the Learning Pick row)
document.addEventListener('click',function(e){var l=e.target&&e.target.closest?e.target.closest('[data-home] [data-go]'):null;if(!l)return;
  var f=document.getElementById(l.getAttribute('data-open')||'');
  function show(){try{if(!f){window.scrollTo(0,0);return;}f.open=true;      // below the website's sticky tab bar (none in the app)
    var b=document.querySelector('.tabbar'),c=b?getComputedStyle(b):null,off=c&&c.position==='sticky'&&b.offsetHeight?(parseFloat(c.top)||0)+b.offsetHeight+10:12;
    window.scrollTo(0,Math.max(0,f.getBoundingClientRect().top+(window.scrollY||0)-off));}catch(x){}}
  var A=window.MemebotApp;if(A&&typeof A.select==='function'){e.preventDefault();A.select(l.getAttribute('data-go'),'top');if(f)setTimeout(show,0);return;}
  setTimeout(show,0);});
})();
"""

CSS = r"""
/* the Start tab (page_home.py): the live panel (page_live.py); without it the account cards of before Oct 26 */
.hm { display:grid; gap:14px } .hm [hidden] { display:none !important }
.hm-hero { position:relative; border-radius:18px; padding:14px; overflow:hidden; border:1px solid var(--line);
  background:radial-gradient(120% 90% at 0% 0%, color-mix(in srgb,var(--accent) 22%,transparent), transparent 60%),
             radial-gradient(120% 90% at 100% 100%, color-mix(in srgb,var(--nn2) 20%,transparent), transparent 60%), var(--surface) }
.hm-ey { font-size:var(--fs-xs); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0 2px 10px }
.hm-accs { display:grid; grid-template-columns:1fr 1fr; gap:10px }
.hm-acc { min-width:0; display:grid; gap:6px; align-content:start; padding:12px; border-radius:14px; background:color-mix(in srgb,var(--bg) 55%,transparent);
  border:1px solid color-mix(in srgb,var(--fg) 8%,transparent); backdrop-filter:blur(6px) }
.hm-k { display:flex; flex-wrap:wrap; align-items:center; gap:2px 6px; font-weight:600; letter-spacing:.06em; font-size:var(--fs-s) }
.hm-k small { font-weight:400; letter-spacing:0; color:var(--muted); font-size:var(--fs-xs) } .hm-since { font-size:11px; color:var(--fg2); margin-top:-4px }
.hm-dot { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent) }
.hm-rad .hm-dot { background:var(--nn2); box-shadow:0 0 10px var(--nn2) }
.hm-bal { font-size:clamp(19px,5.6vw,30px); font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; line-height:1.1; white-space:nowrap }
.hm-bal.good { color:var(--good) } .hm-bal.bad { color:var(--bad) }
.hm-sp { width:100%; height:30px; display:block } .hm-sp .z { stroke:var(--muted); stroke-dasharray:2 3; stroke-width:1; vector-effect:non-scaling-stroke; opacity:.6 }
.hm-sp .l { fill:none; stroke:var(--accent); stroke-width:1.6; vector-effect:non-scaling-stroke } .hm-sp .a { fill:var(--accent); opacity:.12 }
.hm-sp.good .l { stroke:var(--good) } .hm-sp.good .a { fill:var(--good) } .hm-sp.bad .l { stroke:var(--bad) } .hm-sp.bad .a { fill:var(--bad) }
.hm-st { display:grid; grid-template-columns:repeat(3,auto); justify-content:space-between; gap:4px }
.hm-st > span { display:grid; min-width:0 } .hm-st i { font-style:normal; font-size:11px; color:var(--muted) }
.hm-st b { font-size:15px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap } .hm-st small { font-size:11px; font-weight:400; color:var(--muted); margin:0 3px 0 1px }
.hm-n { font-size:11px; color:var(--muted) } .hm-empty { margin:0; font-size:var(--fs-s); color:var(--fg2) }
.hm-go { justify-self:start; color:var(--accent); font-size:var(--fs-s); font-weight:500; cursor:pointer; padding:6px 0; min-height:32px }
.hm-lp { grid-column:1 / -1; grid-template-columns:minmax(0,1fr) auto; column-gap:12px; cursor:pointer; text-decoration:none; color:inherit }
.hm-lp > .hm-k, .hm-lp > .hm-since { grid-column:1 } .hm-lp > .hm-bal { grid-column:2; grid-row:1 / span 2; align-self:center }
.hm-lp .hm-dot { background:var(--good); box-shadow:0 0 10px var(--good) } .hm-lp:hover { border-color:var(--accent) }
.hm-lpf { grid-column:1 / -1; display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:4px 10px } .hm-lpf .hm-go { padding:0; min-height:0 }
@media (min-width:700px) { .hm-hero { padding:18px } .hm-acc { padding:16px } }
@media (max-width:360px) { .hm-accs { grid-template-columns:1fr } }
"""
