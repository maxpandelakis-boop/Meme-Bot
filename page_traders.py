"""page_traders.py: the Traders tab (three paper traders on one buy stream) and the radar's paper positions on the Radar tab. Fake money
only: nothing here buys, signs or sends anything, and nothing here is advice.

report.py calls it in two places:
  section(D, bought=None)  the Traders tab (#pane-account): the head with its ⓘ, the compare card (one chart with three lines and a three-row
                          table, all on the same finished trades), the three trader cards (stop-loss, best price looking back, learning), the
                          activity and four folds (open positions, finished trades, how the learning trader decides, the trades before the
                          restart). With D["traders"]["err"] only a note, the activity (the paper account's own) and the open positions.
  radar_positions(D)      the Radar tab's "Radar paper positions": the newest RADAR_SHOWN rule-2 buys (10 € each) with their state or result,
                          the rest in a fold, the radar's old 3 € test in one sentence.

Every number comes from D["traders"] = traders.load(d, now) (the logic's contract); nothing here computes a result, it only formats.
Every chain string (a symbol, an address) is escaped. The best-price trader is looking back and says so wherever its numbers stand; the
learning trader's live part is kept apart from the part worked out afterwards. Trader colours (--t1, --t2, --t3) mark lines, dots and the
card's top bar only; green and red mean profit and loss.
"""
import calendar, html, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M
import page_account as PA     # the page's formats (eur, pct1, hhmm, mday, tone), the activity rows (_feed_list) and their styles

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = "−"
RADAR_SHOWN = 10             # the radar's paper positions in view; the rest in the fold under them
FEED_SHOWN = 10              # activity rows in view; the rest in the fold "All activity"
FINISHED_SHOWN = 100         # the finished trades' table: the newest this many
GROUPS = ("pick", "radar", "young")
WORD = {"pick": "Picks", "radar": "Radar", "young": "New launches"}
TAG = {"pick": "pick", "radar": "radar", "young": "new launch"}
TRADERS = (("t1", "Stop-loss"), ("t2", "Best-price"), ("t3", "Learning"))       # the compare table's names; " trader" only where there is room


def _report():
    return PA._report()


def num(v):
    return M.num(v)


def T_of(D):
    """D["traders"] as a dict ({"err": ...} when it is missing or not one)."""
    T = D.get("traders")
    return T if isinstance(T, dict) else {"err": "no traders data"}


def ticket(v):
    """A ticket as the user named it: 50 €, 10 €, 3 €."""
    return _report().fmt_eur(v)


def money(v, signed=True):
    """A result in euros, green or red: <b class="good">+12.36 €</b>; n/a when unknown."""
    v = num(v)
    if v is None:
        return '<span class="muted">n/a</span>'
    return '<b class="m %s">%s</b>' % (PA.tone(v), E(PA.eur(v, signed)))


def share(v, of):
    """A result over what went in, one decimal: −20.0%; n/a without an amount invested."""
    v, of = num(v), num(of)
    return PA.pct1(v / of) if v is not None and of else "n/a"


def when(ms, now):
    """17:21 on the day of the page, Oct 14, 17:21 before it (never an ISO date)."""
    try:
        return PA.hhmm(ms) if PA.mday(ms) == PA.mday(now) else "%s, %s" % (PA.mday(ms), PA.hhmm(ms))
    except Exception:
        return ""


def when2(ms, now):
    """when() for a narrow time column: 17:21, or 17:21 with its day under it (<small>Oct 14</small>) before the page's day; HTML."""
    try:
        return E(PA.hhmm(ms)) + ("" if PA.mday(ms) == PA.mday(now) else "<small>%s</small>" % E(PA.mday(ms)))
    except Exception:
        return ""


def day_ms(day):
    """A decision's day "2026-10-14" as ms (00:00 UTC), or None."""
    try:
        return calendar.timegm(time.strptime(str(day), "%Y-%m-%d")) * 1000
    except (TypeError, ValueError, OverflowError):
        return None


def group_word(g, sw, now):
    """A group's name on the cards; the new launches say when they ended (or end), the radar when it starts."""
    if g == "young":
        return "New launches (%s %s)" % ("ended" if now >= sw else "until", PA.mday(sw))
    if g == "radar" and now < sw:
        return "Radar (from %s)" % PA.mday(sw)
    return WORD[g]


def t2_notes(x):
    """How a best-price sum was counted, as short phrases ("" for a count of 0): estimated lows, spikes capped at memebot.CANDLE_MAX_X,
    spikes left out. x: T2's stats or the radar's old test (radarV1), both with est, capped and leftOut."""
    n = lambda k: int(num(x.get(k)) or 0)
    return ["%d estimated (the real best is at least this)" % n("est") if n("est") else "",
            ("%d price spike%s counted at %gx at most" % (n("capped"), "" if n("capped") == 1 else "s", M.CANDLE_MAX_X)) if n("capped") else "",
            ("%d spike%s left out (no volume or pool already dead)" % (n("leftOut"), "" if n("leftOut") == 1 else "s")) if n("leftOut") else ""]


# ---------------------------------------------------------------- the Radar tab: the radar's paper positions
def radar_positions(D):
    """The radar's rule-2 buys (10 € on every coin found without traps, from the switch), newest first: time, coin (with the first four
    address characters where two rows share a symbol), and its state (running until, waiting for a price, no price data) or its result
    and exit word; RADAR_SHOWN in view, the rest in a fold; one sentence on the radar's old 3 € test, which is not part of the traders."""
    T = T_of(D)
    now = num(D.get("now")) or num(T.get("now")) or 0
    sw = num(T.get("switchAt")) or M.switch_at()
    tk = num((T.get("tickets") or {}).get("radar")) or 10.0
    rows = [t for t in T.get("trades") or [] if isinstance(t, dict) and t.get("group") == "radar"]
    syms = {}
    for t in rows:
        syms[str(t.get("sym"))] = syms.get(str(t.get("sym")), 0) + 1

    def row(t):
        sym = str(t.get("sym") or "?")
        tail = (' <small class="ad">%s</small>' % E(str(t.get("addr") or "")[:4])) if syms.get(sym, 0) > 1 else ""
        if num(t.get("t1")) is not None:          # the move is the trade row's own (the feed keeps only the newest sales)
            st = '%s <span class="ew">%s</span>' % (money(t["t1"]), E(PA.exit_word(t.get("t1why"), t.get("move"))))
        elif t.get("state") == "running":
            st = '<span class="ew">running until %s</span>' % E(when(t.get("end"), now))
        elif t.get("state") == "noprice":
            st = '<span class="ew">no price data</span>'
        else:
            st = '<span class="ew">waiting for a price</span>'
        return '<li class="trp"><span class="tm">%s</span><span class="cn"><b>%s</b>%s</span><span class="st">%s</span></li>' % (when2(t.get("entryAt"), now), E(sym), tail, st)
    if T.get("err"):
        body = '<p class="note trerr">The radar\'s paper positions could not be computed this time (%s). The paper account itself is unaffected.</p>' % E(str(T["err"]).split(":")[0])
    elif rows:
        body = '<ol class="trps">%s</ol>' % "".join(row(t) for t in rows[:RADAR_SHOWN])
        if rows[RADAR_SHOWN:]:
            body += _report().fold("All radar positions (%d)" % len(rows), "newest first", '<ol class="trps">%s</ol>' % "".join(row(t) for t in rows[RADAR_SHOWN:]))
    elif now < sw:
        body = '<p class="note">From %s, %s, every coin the radar finds without traps is bought on paper for %s.</p>' % (E(PA.mday(sw)), E(PA.hhmm(sw)), E(ticket(tk)))
    else:
        body = '<p class="note">No radar paper position yet. The radar runs 07:00 to 24:00.</p>'
    v1 = T.get("radarV1") or {}
    foot = ""
    if num(v1.get("n")):
        foot = ('<p class="note trp-foot">Before %s the radar tested %s on the best 5 coins of each hour (%d coins, %s on %d priced); that test is not part of '
                'the three traders.</p>') % (E(PA.mday(sw)), E(ticket(M.YOUNG_TICKET)), int(num(v1["n"])), E(PA.eur(v1.get("pnl"), True)), int(num(v1.get("priced")) or 0))
        if num(v1.get("t2")) is not None and num(v1.get("priced")):      # the same coins sold the Best-price trader's way (its card's notes)
            foot += ('<p class="note trp-foot">Sold at the best price within 6 h instead, looking back (not possible in reality): %s on the same %d%s.</p>'
                     % (E(PA.eur(v1["t2"], True)), int(num(v1["priced"])), E("".join(" · " + p for p in t2_notes(v1) if p))))
    return ('<section class="trpos" data-tr="radar"><div class="sec-head"><h3>Radar paper positions</h3><p>every coin found without traps is bought on paper for %s</p></div>'
            '%s%s</section>') % (E(ticket(tk)), body, foot)


# ---------------------------------------------------------------- the Traders tab
def head(T, now):
    sw = num(T.get("switchAt")) or M.switch_at()
    tk = T.get("tickets") or {}
    info = ('<p>Fake money: nothing is bought for real. All three get the same coins: each scan\'s pick for %s and, from %s, every radar coin found '
            'without traps for %s. Until %s the bot also bought the %d newest launches of each scan for %s each; those trades stay in all three. The '
            'traders differ only in when they sell, and the learning trader may skip coins.</p>') % (
        E(ticket(tk.get("pick") or M.TOP_TICKET)), E(PA.mday(sw)), E(ticket(tk.get("radar") or 10.0)), E(PA.mday(sw)), M.YOUNG_BUY_N, E(ticket(tk.get("young") or M.YOUNG_TICKET)))
    return ('<div class="sec-head hasi"><h2>Three paper traders</h2>%s</div>' % _report().info_i(info, "About the three paper traders"))


def compare(T):
    """The compare card: the three lines of the finished trades over time, a three-row table and the footnote."""
    R = _report()
    S = T.get("same") or {}
    ser = T.get("series") or {}
    names = {"t1": "Stop-loss", "t2": "Best price, looking back", "t3": "Learning"}
    # drawn learning, best price, stop-loss: the real paper account on top; the learning line is wider under it, so where the two are the
    # same (no change in force yet) it shows as a band around the stop-loss line
    series = [(names[k], k, [(num(p[0]), num(p[1])) for p in ser.get(k) or [] if isinstance(p, (list, tuple)) and len(p) == 2 and num(p[0]) and num(p[1]) is not None])
              for k in ("t3", "t2", "t1")]
    lab = lambda v: PA.eur(round(v), True).replace(".00", "")      # +1,753 €: whole euros, so the end labels fit a phone's chart
    chart = lambda w, h: R.line_chart(series, 0.0, w, h, ref_label=None, aria_label="Result of finished trades over time, three traders", fmt_v=lab,
                                      fmt_tick=lambda v: PA.eur(v, True).replace(".00", "").replace("\u00a0€", ""),
                                      fmt_t=lambda t: "%s, %s" % (PA.mday(t), PA.hhmm(t)), fmt_tip=lambda v: PA.eur(v, True))
    wide = chart(R.WIDE, 240)
    if wide:
        legend = ('<div class="legend"><span style="--c:var(--t1)">Stop-loss</span><span class="trdash" style="--c:var(--t2)">Best price, looking back</span>'
                  '<span style="--c:var(--t3)">Learning</span></div>')
        plot = '<div class="chart trchart"><div class="wide">%s</div><div class="narrow">%s</div>%s</div>' % (wide, chart(R.NARROW, 120), legend)
    else:
        plot = '<p class="note">The chart starts with the second finished trade.</p>'
    lv, vs = (T.get("t3") or {}).get("live") or {}, (T.get("t3") or {}).get("vsT1") or {}
    # the learning trader's lead is marked as a replay until it is all live (no mark while it equals the stop-loss trader: nothing was replayed)
    sub = {"t2": "looking back", "t3": "worked out afterwards" if num(vs.get("diff")) and (num(lv.get("n")) or 0) < (num(vs.get("n")) or 0) else ""}
    rows = "".join('<tr><td><i class="trdot %s" aria-hidden="true"></i>%s<span class="trw"> trader</span>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
        k, E(name), ('<small>%s</small>' % E(sub[k])) if sub.get(k) else "", money(S.get(k)), E(share(S.get(k), S.get("invested"))), E(R.fmt_int(S.get("n") or 0)))
        for k, name in TRADERS)
    table = ('<table class="trtbl"><thead><tr><th>Trader</th><th class="n">Result</th><th class="n">of invested</th><th class="n">Trades</th></tr></thead>'
             '<tbody>%s</tbody></table>') % rows
    c = T.get("counts") or {}
    # what is not compared yet, by what it waits for: the 6 hours (sold or not: the open ones are in "Open positions"), the sale, a price
    foot = "Same %s finished trade%s for all three (6 h over and priced)" % (R.fmt_int(S.get("n") or 0), "" if (S.get("n") or 0) == 1 else "s")
    for k, words in (("waiting", "waiting for a price"), ("running", "still inside their 6 hours"), ("selling", "held past the 6 hours"), ("noprice", "without price data")):
        if num(c.get(k)):
            foot += " · %d %s" % (int(num(c[k])), words)
    return '<div class="trcard trcmp" data-tr="compare"><p class="trk">Finished trades</p>%s%s<p class="trfoot">%s.</p></div>' % (plot, table, E(foot))


def split(T, key, sw, now):
    """The per-group line of a trader card: Picks −307.00 € · Radar 0.00 € (none yet) · New launches (ended Oct 16) −520.61 €. A group
    with no finished trade is left out, except the radar after the switch."""
    G = (T.get("same") or {}).get("groups") or {}
    bits = []
    for g in GROUPS:
        x = G.get(g) or {}
        if num(x.get("n")):
            bits.append('%s %s' % (E(group_word(g, sw, now)), money(x.get(key))))
        elif g == "radar" and now >= sw:
            bits.append('Radar %s <span class="muted">(none yet)</span>' % money(0.0, False))
    return '<p class="trl trsplit">%s</p>' % " · ".join(bits) if bits else ""


def card(k, title, chip, chip_cls, pre, T, lines, sw, now, info=""):
    """One trader's card: the 4 px bar in its colour, the title and its chip, the lines before the big number (pre: the rule, or the
    learning trader's rules per group), the big number (its result on the same finished trades) and its sub line, the detail lines, the
    split by group."""
    S = T.get("same") or {}
    v = num(S.get(k))
    big = '<p class="trbig %s">%s</p>' % (PA.tone(v), E(PA.eur(v, True)) if v is not None else "n/a")
    sub = '<p class="trsub">on %s finished trade%s · %s of %s</p>' % (_report().fmt_int(S.get("n") or 0), "" if (S.get("n") or 0) == 1 else "s",
                                                                      E(share(S.get(k), S.get("invested"))), E(PA.eur(S.get("invested"))))
    # six rows in every card (head, the lines before the number, the number, its sub line, the details, the split): at 900 px and wider the three
    # cards share them (subgrid), so the big numbers and the splits line up
    return ('<article class="trcard trader %s" data-tr="%s"><div class="trh%s"><h3>%s</h3><span class="chip%s">%s</span>%s</div><div class="trpre">%s</div>%s%s'
            '<div class="trls">%s</div>%s</article>') % (
        k, k, " hasi" if info else "", E(title), (" " + chip_cls) if chip_cls else "", E(chip), _report().info_i(info, "About the " + title.lower()) if info else "",
        "".join(pre), big, sub, "".join(lines), split(T, k, sw, now) or "<div></div>")


def cards(T, now):
    sw = num(T.get("switchAt")) or M.switch_at()
    t1, t2, t3 = T.get("t1") or {}, T.get("t2") or {}, T.get("t3") or {}
    since = num(T.get("since"))
    rule = '<p class="trrule">%s</p>' % E((str(T.get("ruleText") or M.PAPER_LABEL)[:1].upper() + str(T.get("ruleText") or M.PAPER_LABEL)[1:]) + (" · since %s" % PA.mday(since) if since else ""))
    op = t1.get("open") or {}
    n_op, n_rd = int(num(op.get("n")) or 0), len(radar_open(T))        # the open positions as the fold "Open positions" counts them
    held = "%d position%s worth %s" % (n_op, "" if n_op == 1 else "s", E(PA.eur(op.get("value"))))
    if n_rd:
        held = "%d position%s: %d paper worth %s, %d radar" % (n_op + n_rd, "" if n_op + n_rd == 1 else "s", n_op, E(PA.eur(op.get("value"))), n_rd)
    l1 = ['<p class="trl">Won %d · lost %d · open now: %s · account total %s</p>' % (int(num(t1.get("won")) or 0), int(num(t1.get("lost")) or 0), held, money(t1.get("account")))]
    rd = t1.get("radar") or {}
    if num(rd.get("noprice")):
        l1.append('<p class="trl">%d radar position%s without price data, not counted (if all were total losses: %s)</p>' % (
            int(num(rd["noprice"])), "" if num(rd["noprice"]) == 1 else "s", E(PA.eur(rd.get("worst"), True))))
    parts = t2_notes(t2)
    l2 =['<p class="trl">Without its single best trade: %s · typical trade %s</p>' % (money(t2.get("noBest")), money(t2.get("median")))]
    # behind its ⓘ: how the best price is counted, and why on a few coins it is below what the stop-loss trader really got
    fin = [t for t in T.get("trades") or [] if isinstance(t, dict) and t.get("state") == "finished" and num(t.get("t1")) is not None and num(t.get("t2")) is not None]
    below = sum(1 for t in fin if t["t2"] < t["t1"])
    info2 = ('<p>Looking back, it sells each coin at the highest minute close inside its 6 hours. %s</p>' % E(" · ".join(p for p in parts if p) + "." if any(parts) else "")
             + ('<p>On %s of %s trades the stop-loss trader got more: its %g h sale comes at the first scan after the window, at that scan\'s price, and '
                'its target is booked at exactly %gx.</p>' % (_report().fmt_int(below), _report().fmt_int(len(fin)), M.HOLD_MAX_H, 1 + M.HOLD_TP) if below else ""))
    G = t3.get("groups") or {}
    pre3, l3 = [], []
    for g in GROUPS:
        x = G.get(g) or {}
        lr = x.get("learning") or {}
        n, need, ch = int(num(lr.get("n")) or 0), int(num(lr.get("need")) or 80), int(num(x.get("changes")) or 0)
        st = ("learning (%d of %d)" % (n, need) if n < need else "no change so far") if not ch else (
            ("changed %s" % PA.mday(x.get("lastChange"))) if ch == 1 else "changed %d times, last %s" % (ch, PA.mday(x.get("lastChange"))))
        word = ("New launches (%s)" % ("ended" if now >= sw else "until %s" % PA.mday(sw))) if g == "young" else group_word(g, sw, now)
        pre3.append('<p class="trl">%s: %s · %s</p>' % (E(word), E(x.get("ruleText") or "stop %s30%% · 11x · 6 h" % MINUS), E(st)))
    skips = ["%s (%s)" % (s.get("text"), WORD[g].lower()) for g in GROUPS for s in (G.get(g) or {}).get("skip") or [] if isinstance(s, dict) and s.get("text")]
    pre3.append('<p class="trl">%s</p>' % E(("Skips coins with: " + "; ".join(skips)) if skips else "Skips: none yet"))
    vs, live, sk = t3.get("vsT1") or {}, t3.get("live") or {}, t3.get("skipped") or {}
    ci = vs.get("ci") if isinstance(vs.get("ci"), list) and len(vs["ci"]) == 2 else [0.0, 0.0]
    if not num(vs.get("diff")) and not num(ci[0]) and not num(ci[1]):
        l3.append('<p class="trl">Compared with the stop-loss trader on the same trades: the same so far (no change in force yet)</p>')
    else:
        chance = " · could be chance" if (num(ci[0]) or 0) <= 0 <= (num(ci[1]) or 0) else ""
        n_vs, n_live = int(num(vs.get("n")) or 0), int(num(live.get("n")) or 0)      # until live trades exist the whole lead is a replay: it says so here
        after = (" · worked out afterwards" if not n_live else " · %s of these %s trades worked out afterwards" % (_report().fmt_int(n_vs - n_live), _report().fmt_int(n_vs))) if n_live < n_vs else ""
        l3.append('<p class="trl">Compared with the stop-loss trader on the same trades: %s (likely %s to %s)%s</p>' % (
            money(vs.get("diff")), E(PA.eur(ci[0], True)), E(PA.eur(ci[1], True)), E(chance + after)))
    if num(sk.get("n")):
        l3.append('<p class="trl">Skipped %d coin%s: the stop-loss trader made %s on them</p>' % (int(num(sk["n"])), "" if num(sk["n"]) == 1 else "s", money(sk.get("t1"))))
    if now >= sw:
        l3.append('<p class="trl">Live since %s: %s.</p>' % (
            E(PA.mday(sw)), ("%s on %d trade%s" % (money(live.get("diff")), int(num(live.get("n"))), "" if num(live.get("n")) == 1 else "s")) if num(live.get("n")) else "no finished trade yet"))
    else:
        l3.append('<p class="trl">Live from %s, %s; until then every step is worked out afterwards.</p>' % (E(PA.mday(sw)), E(PA.hhmm(sw))))
    return '<div class="trcards">%s%s%s</div>' % (
        card("t1", "Stop-loss trader", "the real paper account", "", [rule], T, l1, sw, now),
        card("t2", "Best-price trader", "looking back · not possible in reality", "warn", ['<p class="trrule">Sells each coin at its highest minute close within 6 h</p>'], T, l2, sw, now, info2),
        card("t3", "Learning trader", "learns only from finished trades", "", pre3, T, l3, sw, now))


def feed_items(D, T):
    """The stream's buys and sales, newest first; without the traders (err) the paper account's own feed."""
    if T.get("err"):
        return [f for f in ((D.get("paper") or {}).get("acct2") or {}).get("feed") or [] if isinstance(f, dict)]
    return [f for f in T.get("feed") or [] if isinstance(f, dict)]


def activity(D, T):
    """The newest FEED_SHOWN buys and sales of the stream (page_account's rows: a Bought or Sold badge, the coin in bold, its group, the
    amount); the rest are in the fold "All activity" (all_activity) under it, the first of the tab's folds."""
    R = _report()
    items = feed_items(D, T)
    newest = items[0]["t"] if items else None
    # the newest row's day is in the head (newest Thu Oct 15, 17:21); a day header follows only where the day changes
    hd = '<div class="head"><h3>Activity</h3><span class="upd">%s</span></div>' % E(("newest %s, %s" % (PA.day_label(newest), PA.hhmm(newest))) if newest else "updated each scan")
    if not items:
        return '<div class="pa-feed trfeed" data-tr="feed">%s<p class="note">No paper trade yet.</p></div>' % hd
    first, _ = PA._feed_list(items[:FEED_SHOWN], R, PA.day_label(newest))
    return '<div class="pa-feed trfeed" data-tr="feed">%s<ol class="pa-evs">%s</ol></div>' % (hd, first)


def all_activity(D, T):
    """The fold with the rest of the activity (after the newest FEED_SHOWN), with its own day headers. traders.load keeps the newest 400
    (feedN says how many there are): the title then says "Latest activity (400 of 1,285)", never a cap as a count."""
    R = _report()
    items = feed_items(D, T)
    if not items[FEED_SHOWN:]:
        return ""
    _, day = PA._feed_list(items[:FEED_SHOWN], R)
    rest, _ = PA._feed_list(items[FEED_SHOWN:], R, day)
    total = int(num(T.get("feedN")) or 0) if not T.get("err") else 0
    if total > len(items):
        title, summ = "Latest activity (%s of %s)" % (R.fmt_int(len(items)), R.fmt_int(total)), "the newest %s bought and sold, newest first" % R.fmt_int(len(items))
    else:
        title, summ = "All activity (%s)" % R.fmt_int(len(items)), "everything bought and sold, newest first"
    return R.fold(title, summ, '<ol class="pa-evs trall">%s</ol>' % rest)


def radar_open(T):
    """The radar buys the stop-loss trader still holds: in their 6 hours, no result yet."""
    return [t for t in T.get("trades") or [] if isinstance(t, dict) and t.get("group") == "radar" and t.get("state") == "running" and num(t.get("t1")) is None]


def open_fold(D, T):
    """The open paper positions (report.py's hold cards: the price bar, the clock, the facts of the buy) and the radar buys still running."""
    R = _report()
    now = num(D.get("now")) or 0
    rows = [r for r in D.get("open") or [] if r["p"].get("grp") in M.PAPER_GROUPS]
    radar = radar_open(T)
    body = ('<div class="holds">%s</div>' % "".join(R.hold_card(r, now) for r in rows)) if rows else ""
    if radar:
        body += '<ol class="trps">%s</ol>' % "".join('<li class="trp"><span class="tm">%s</span><span class="cn"><b>%s</b> <small>radar · %s</small></span><span class="st"><span class="ew">running until %s</span></span></li>' % (
            when2(t.get("entryAt"), now), E(t.get("sym") or "?"), E(ticket(t.get("ticket"))), E(when(t.get("end"), now))) for t in radar)
    if not body:
        body = '<p class="note">No open position right now.</p>'
    body += '<details class="trhow"><summary>How a coin is sold</summary><p class="note">%s</p></details>' % E(R.hold_rule_text())
    op = (T.get("t1") or {}).get("open") or {}
    summ = "%d paper position%s worth %s" % (len(rows), "" if len(rows) == 1 else "s", PA.eur(op.get("value"))) if rows else "no paper position open"
    if radar:
        summ += " · %d radar position%s running" % (len(radar), "" if len(radar) == 1 else "s")
    return R.fold("Open positions (%d)" % (len(rows) + len(radar)), summ, body)


def finished_fold(T):
    """The finished trades, newest FINISHED_SHOWN: the coin (bold, its group and time under it) and one result per trader; the learning trader's
    cell says "skipped" where it skipped the coin. Stacks on a phone (no cut columns)."""
    R = _report()
    now = num(T.get("now")) or 0
    fin = [t for t in T.get("trades") or [] if isinstance(t, dict) and t.get("state") == "finished"]
    if not fin:
        return R.fold("Finished trades (0)", "none yet", '<p class="note">A trade counts once its 6 hours are over, it is sold and its best price is known.</p>')
    cell = lambda k, lab, t: '<td class="n" data-k="%s">%s</td>' % (lab, '<span class="muted">skipped</span>' if k == "t3" and t.get("skipped") else money(t.get(k)))
    rows = "".join('<tr><td class="c"><strong>%s</strong><small>%s · %s</small></td>%s%s%s</tr>' % (
        E(t.get("sym") or "?"), E(TAG.get(t.get("group"), "")), E(when(t.get("entryAt"), now)),
        cell("t1", "Stop-loss", t), cell("t2", "Best price, looking back", t), cell("t3", "Learning", t)) for t in fin[:FINISHED_SHOWN])
    table = ('<div class="tbl stack trfin"><table><thead><tr><th>Coin</th><th class="n">Stop-loss</th><th class="n">Best price (looking back)</th><th class="n">Learning</th></tr></thead>'
             '<tbody>%s</tbody></table></div>') % rows
    return R.fold("Finished trades (%d)" % len(fin), "newest %d of %d · one result per trader" % (min(len(fin), FINISHED_SHOWN), len(fin)),
                  '<p class="note">Newest %d of %d.</p>%s' % (min(len(fin), FINISHED_SHOWN), len(fin), table))


def change_text(x):
    """What a decision changed, in words: "target 11x → 3x", "skips coins with: no socials", "stops skipping: no socials", or "kept"."""
    ch = x.get("changed")
    if ch == "rule":
        a, b = x.get("prev") or {}, x.get("rule") or {}
        bits = []
        if a.get("stop") != b.get("stop"):
            bits.append("stop %s%d%% → %s%d%%" % (MINUS, round(100 * (num(a.get("stop")) or 0)), MINUS, round(100 * (num(b.get("stop")) or 0))))
        if a.get("target") != b.get("target"):
            bits.append("target %gx → %gx" % (num(a.get("target")) or 0, num(b.get("target")) or 0))
        if a.get("hours") != b.get("hours"):
            bits.append("time limit %g h → %g h" % (num(a.get("hours")) or 0, num(b.get("hours")) or 0))
        return ", ".join(bits) or "rule"
    if ch == "skip-add":
        return "skips a sign"
    if ch == "skip-drop":
        return "stops skipping a sign"
    return "kept"


def log_rows(decs):
    """The decision log, newest first, one row per change and one per run of kept days of one group (and mode): (first day ms, last day ms,
    group, mode, change, why, changed?)."""
    by = {}
    for x in sorted((x for x in decs if isinstance(x, dict) and day_ms(x.get("day")) is not None), key=lambda x: (x.get("group"), x.get("day"))):
        runs = by.setdefault(x.get("group"), [])
        d, ch = day_ms(x["day"]), bool(x.get("changed"))
        if runs and not ch and not runs[-1][6] and runs[-1][3] == x.get("mode") and runs[-1][1] == d - 86_400_000:
            runs[-1] = (runs[-1][0], d, runs[-1][2], runs[-1][3], "kept", str(x.get("why") or ""), False)
        else:
            runs.append((d, d, x.get("group"), x.get("mode"), change_text(x), str(x.get("why") or ""), ch))
    out = [r for g in by.values() for r in g]
    out.sort(key=lambda r: (-r[1], GROUPS.index(r[2]) if r[2] in GROUPS else 9))
    return out


def decide_fold(T):
    """How the learning trader decides: four paragraphs (the steps, the bars, the skip signs, worked out afterwards before the switch and
    live from it) and the decision log."""
    R = _report()
    sw = num(T.get("switchAt")) or M.switch_at()
    at = PA.hhmm((sw // 86_400_000) * 86_400_000)
    paras = ("It starts with the stop-loss trader's rule and changes one step at a time: the stop (%s20, %s30 or %s40%%), the target (2x, 3x or 11x) or the time limit "
             "(6 h or 2 h). Once a day at %s Berlin it looks only at trades that finished before then." % (MINUS, MINUS, MINUS, at),
             "A change needs at least 80 finished trades of that kind, 40 older and 40 newer; it must be better in both halves and with every way of reading "
             "coarse prices, likely better than zero, and still better without its single best trade. At most one change a day.",
             "It may also skip coins with a sign that lost money: at least 30 coins with and 30 without the sign, worse in both halves, at most 2 signs and at most "
             "40% of coins skipped.",
             "Before %s these steps were worked out afterwards on the trades so far; from %s they are made live, before the trades happen. Only the live part "
             "shows whether learning helps." % (PA.mday(sw), PA.mday(sw)))
    rows = log_rows(T.get("decisions") or [])
    if rows:
        tr = "".join('<tr%s><td class="d" data-k="date">%s<small>%s</small></td><td class="d" data-k="coins">%s</td><td class="d" data-k="change">%s</td><td>%s</td></tr>' % (
            ' class="ch"' if r[6] else "", E(PA.mday(r[0]) if r[0] == r[1] else "%s to %s" % (PA.mday(r[0]), PA.mday(r[1]))),
            E("live" if r[3] == "live" else "worked out afterwards"), E(WORD.get(r[2], r[2])), E(r[4]), E(r[5])) for r in rows)
        log = ('<div class="tbl stack trlog"><table><thead><tr><th>Date</th><th>Coins</th><th>Change</th><th>Why</th></tr></thead><tbody>%s</tbody></table></div>' % tr)
    else:
        log = '<p class="note">No decision yet: the first comes at the first daily step.</p>'
    n_ch = sum(1 for r in rows if r[6])
    return R.fold("How the learning trader decides", "%d change%s so far · learns only from finished trades" % (n_ch, "" if n_ch == 1 else "s"),
                  "".join('<p class="note">%s</p>' % E(p) for p in paras) + log)


def old_fold(D):
    """The trades bought before the paper account restarted (report.py's closed-trades table), as today."""
    R = _report()
    old = (D.get("paper") or {}).get("old") or []
    if not old:
        return ""
    since = (D.get("paper") or {}).get("since")
    note = ("bought before the paper account restarted on %s; not counted above" % R.fmt_dt(since, True)) if since else "bought before the paper account restarted; not counted above"
    return R.fold("Before the restart (%d trade%s)" % (len(old), "" if len(old) == 1 else "s"), "not part of the three traders",
                  R.safe("closed trades", lambda: R.closed_fold(old, note)))


def section(D, bought=None):
    """The Traders tab (see the module doc); every part renders on its own, a broken part shows a notice."""
    R = _report()
    T = T_of(D)
    now = num(D.get("now")) or num(T.get("now")) or 0
    parts = ["<style>%s%s</style>" % (PA.CSS, CSS), head(T, now)]
    if T.get("err"):
        parts.append('<p class="note trerr">The traders could not be computed this time (%s). The paper account itself is unaffected.</p>' % E(str(T["err"]).split(":")[0]))
        parts += [R.safe("activity", lambda: activity(D, T)),
                  '<div class="trfolds">%s%s</div>' % (R.safe("all activity", lambda: all_activity(D, T)), R.safe("open positions", lambda: open_fold(D, T)))]
    else:
        parts += [R.safe("compare", lambda: compare(T)), R.safe("trader cards", lambda: cards(T, now)), R.safe("activity", lambda: activity(D, T)),
                  '<div class="trfolds">%s</div>' % "".join((R.safe("all activity", lambda: all_activity(D, T)), R.safe("open positions", lambda: open_fold(D, T)),
                                                              R.safe("finished trades", lambda: finished_fold(T)), R.safe("decisions", lambda: decide_fold(T)),
                                                              R.safe("before the restart", lambda: old_fold(D))))]
    return "".join(p for p in parts if p)


CSS = r"""
/* the Traders tab (page_traders.py) and the radar's paper positions: one card style (radius 12, padding 16, 12 px gaps, no shadow), type steps
   12/13/15/17/22/34, tabular numbers; the trader colours only on lines, dots and the 4 px top bar; green and red only for profit and loss */
.trcard { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; display:grid; gap:12px; min-width:0 }
.trcard p { margin:0 } .trk { font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:600 }
.trcmp { gap:8px } .trcmp .chart { border:0; padding:0; background:none; gap:6px } .trcmp .legend { font-size:var(--fs-xs) } .trfoot { font-size:var(--fs-xs); color:var(--fg2) }
.chart-svg .line.t1 { stroke:var(--t1) } .chart-svg .line.t2 { stroke:var(--t2); stroke-dasharray:5 4 } .chart-svg .line.t3 { stroke:var(--t3); stroke-width:5 }
.chart-svg .dot.t1 { fill:var(--t1) } .chart-svg .dot.t2 { fill:var(--t2) } .chart-svg .dot.t3 { fill:var(--t3) }
.legend .trdash::before { height:0; width:14px; border-top:2px dashed var(--c); background:none; border-radius:0; vertical-align:3px }
table.trtbl { width:100%; border-collapse:collapse; font-size:var(--fs-s); font-variant-numeric:tabular-nums }
.trtbl th, .trtbl td { padding:3px 4px; border-top:1px solid var(--line2); vertical-align:baseline } .trtbl th { border-top:0; white-space:nowrap; text-transform:none; letter-spacing:0; font-size:var(--fs-xs) }
.trtbl td:first-child { padding-left:0 } .trtbl td.n { white-space:nowrap } .trtbl td:last-child, .trtbl th:last-child { padding-right:0 }
.trtbl td small { display:block; padding-left:15px; color:var(--muted); font-size:var(--fs-xs) }
.trdot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; vertical-align:0 } .trdot.t1 { background:var(--t1) } .trdot.t2 { background:var(--t2) } .trdot.t3 { background:var(--t3) }
b.m { font-weight:600; white-space:nowrap } b.m.good, .trbig.good { color:var(--good) } b.m.bad, .trbig.bad { color:var(--bad) }
.trcards { display:grid; grid-template-columns:minmax(0,1fr); gap:8px }
@media (min-width:900px) { .trcards { grid-template-columns:repeat(3,minmax(0,1fr)) } }
.trcard.trader { border-top:4px solid var(--tc); gap:3px; align-content:start; padding:12px 16px } .trader.t1 { --tc:var(--t1) } .trader.t2 { --tc:var(--t2) } .trader.t3 { --tc:var(--t3) }
.trh { display:grid; justify-items:start; gap:4px } .trh h3 { margin:0; font-size:17px; font-weight:600 }
.trh.hasi { position:relative; padding-right:36px } .trh > details.hi > summary { position:absolute; top:-12px; right:-12px } .trh > details.hi[open] > .hi-b { margin-top:2px }
.trh .chip { white-space:normal } .trpre, .trls { display:grid; gap:3px; align-content:start }
/* wide: the three cards share their six rows, so the big numbers and the split lines sit at one height */
@supports (grid-template-rows:subgrid) { @media (min-width:900px) { .trcard.trader { grid-row:span 6; grid-template-rows:subgrid; row-gap:3px } } }
.trrule { font-size:var(--fs-s); color:var(--fg2) } .trbig { font-size:34px; font-weight:600; line-height:1.1; letter-spacing:-.01em; font-variant-numeric:tabular-nums; margin-top:2px !important }
.trsub { font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums } .trl { font-size:var(--fs-s); line-height:1.4; color:var(--fg); font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.trsplit { border-top:1px solid var(--line2); padding-top:4px; margin-top:2px !important }
.trfeed { padding:10px 16px 6px } .trfeed .pa-ev { font-size:var(--fs-s); line-height:1.35; padding:2px 0 } .trfeed .head h3 { font-size:17px; font-weight:600 }
.trall { list-style:none; margin:0; padding:0 }
/* the tab's folds as one list: a row each, one frame around them all */
.trfolds { display:grid; gap:0; min-width:0 }
.trfolds > details.fold > summary { border-radius:0; border-top-width:0; padding:10px 14px } .trfolds > details.fold > summary .t { font-size:15px }
.trfolds > details.fold:first-child > summary { border-top-width:1px; border-radius:12px 12px 0 0 } .trfolds > details.fold:last-child:not([open]) > summary { border-radius:0 0 12px 12px }
.trfolds > details.fold[open] { padding-bottom:16px } .trfolds > details.fold:only-child > summary { border-radius:12px }
.trfolds > details.fold > summary::after { font-size:20px }
details.trhow > summary { color:var(--accent); font-weight:500; min-height:44px; display:flex; align-items:center } details.trhow p { margin-top:4px }
.trps { list-style:none; margin:0; padding:0; display:grid }
/* a radar position: the time (its day under it before today) in a fixed column, the coin whole, the result and its exit word on the right; when
   they do not fit beside the coin they move to a line of their own, right-aligned (a symbol never breaks into letters) */
.trp { display:flex; flex-wrap:wrap; gap:2px 10px; align-items:baseline; padding:8px 0; border-top:1px solid var(--line2); font-size:var(--fs-s); font-variant-numeric:tabular-nums }
.trp:first-child { border-top:0 } .trp .tm { flex:0 0 3.4em; color:var(--muted) } .trp .tm small { display:block; font-size:var(--fs-xs) }
.trp .cn { flex:1 1 7em; min-width:0; overflow-wrap:anywhere } .trp .cn small { color:var(--muted); font-size:var(--fs-xs) }
.trp .st { margin-left:auto; text-align:right } .trp .ew { color:var(--fg2) } .trp .st b.m + .ew { margin-left:6px }
.trpos { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; display:grid; gap:8px; min-width:0 }
.trpos h3 { margin:0; font-size:15px } .trpos > .sec-head p { flex-basis:100% } .trpos details.fold > summary { padding:10px 0; border:0; border-top:1px solid var(--line2); border-radius:0 }
.trp-foot { color:var(--fg2) }
.trfin td.c strong { font-weight:600 } .trfin td.c small { display:block; color:var(--muted); font-size:var(--fs-xs) } .trfin th.n, .trfin td.n { text-align:right }
.trfolds .note + .note { margin-top:8px } .trlog tr.ch td { font-weight:600 } .trlog td small { display:block; font-weight:400; color:var(--muted); font-size:var(--fs-xs) } .trlog td:last-child { min-width:24ch }
@media (max-width:560px) {
  .trcard { padding:14px } .trcard.trader { padding:8px 14px 10px } table.trtbl { font-size:var(--fs-s) } .trcmp .legend { font-size:var(--fs-xs) }
  .trfeed { padding:8px 14px 4px } .trfeed .pa-ev { font-size:var(--fs-s) } .trfolds details.fold > summary .sum { display:none }
  #pane-account { gap:12px } .trtbl .trw { display:none }
  .trtbl th:nth-child(4), .trtbl td:nth-child(4) { display:none }     /* the same count in every row: the footnote says it */
  .trlog td:last-child { min-width:0 } }
"""
