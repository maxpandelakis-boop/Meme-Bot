"""page_lernpick.py: the fold "Learning Pick" on the Pick tab (lernpick.py's paper account and brain). Fake money only: nothing here buys,
signs or sends anything, and nothing here is advice. English words (the user's wish of 22 Oct 2026: the app in English).

section(D, R) -> HTML: a fold under the shadow rules. Its summary line says what the Learning Pick made so far and whether its brain
learned last night; inside:
  - one sentence on what it is: its own paper account, retrained every night, a new brain takes over only when it beats the current one
    on days neither has seen; it never changes the Pick or the Radar and sends no push
  - three tiles since its first buy: the Learning Pick, the Pick and the Radar (sold trades: result, per trade, how many in profit)
  - the brain: when it was trained, which brain buys and which rule sells (and since when), last night's exams in one line each, what the
    buy brain looks for now (its strongest inputs in words), the brains waiting for their exam
  - the trades (open ones with the last scan's price, sold ones with their result), newest first, at most TRADES_SHOWN
  - every exam so far in a fold (replayed ones marked), and what it learns from
D: report.py's page data (D["dir"], D["now"]); R: report itself (local times, factor names). Reads lernpick.summary only; every chain
string is escaped. Static HTML and CSS, no script.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = "−"
TRADES_SHOWN = 30
EXAMS_SHOWN = 40
WHY = {"tp": "target", "half": "half at target", "stop": "stop", "trail": "trailing stop", "time": "time limit", "rug": "pool dead",
       "dead": "pool dead", "noprice": "no price (counted as lost)"}


def num(v):
    return M.num(v)


def eur(v, signed=True):
    """+1.23 € / −4.50 € (a real minus, a no-break space before the €)."""
    v = num(v)
    if v is None:
        return "–"
    s = "%s%.2f €" % (MINUS if v < -0.004 else ("+" if signed and v > 0.004 else ""), abs(v))
    return s


def tone(v):
    v = num(v)
    return "good" if v is not None and v > 0.004 else ("bad" if v is not None and v < -0.004 else "")


def when(R, ms, fmt="%b %d, %H:%M"):
    try:
        return R.local(ms).strftime(fmt)
    except Exception:
        return "–"


def bday(i):
    """A brain's id (the date of its newest data, 2026-10-17) as "Oct 17"."""
    import datetime as dt
    try:
        return dt.datetime.strptime(str(i), "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
    except ValueError:
        return str(i or "–")


def label(R, k):
    if k == "fs.lead":
        return "passes the filter search's leading rule"
    try:
        return R.factor_label(k)
    except Exception:
        return k


def likes(lab, up):
    """'prefers a higher pump.fun replies', but 'avoids coins that have Telegram (pump.fun)' and 'avoids coins on pump.fun' for yes/no inputs."""
    w = "prefers" if up else "avoids"
    head, _, rest = lab.partition(" ")
    if head in ("has", "passes") and rest:
        return "%s coins that %s %s" % (w, {"has": "have", "passes": "pass"}[head], rest)
    if head in ("on", "in") and rest:
        return "%s coins %s" % (w, lab)
    return "%s a %s %s" % (w, "higher" if up else "high", lab)


def rule_text(r):
    import lernpick as L
    return L.rule_text(r)


def head_line(S, R):
    me, B = S["me"], S.get("brain") or {}
    bits = []
    if me["n"]:
        bits.append("%s on %d sold trade%s" % (eur(me["closedPnl"]), me["sold"], "" if me["sold"] == 1 else "s") if me["sold"] else "%d trade%s open" % (me["open"], "" if me["open"] == 1 else "s"))
    elif B.get("buy"):
        bits.append("buys from the next scan")
    else:
        bits.append("waiting for its first nightly training")
    live = [e for e in B.get("exams") or [] if not e.get("replay") and e.get("n")]
    if B.get("t"):
        last = [e for e in live if num(e.get("t")) == num(B.get("t"))]
        if any(e.get("won") for e in last):
            bits.append("learned last night")
        elif last:
            bits.append("kept its brain last night")
    return " · ".join(bits)


def tile(name, sub, a, ticket, cls=""):
    if a.get("sold"):
        big = '<b class="%s">%s</b>' % (tone(a["closedPnl"]), E(eur(a["closedPnl"])))
        line = "%s per trade · %d of %d won" % (eur(a["per"]), a["won"], a["sold"])
    else:
        big = "<b>–</b>"
        line = "nothing sold yet"
    opn = (a.get("n") or 0) - (a.get("sold") or 0)
    if opn > 0:
        line += " · %d open" % opn
    return ('<div class="lp-tile %s"><span class="lp-tn">%s</span><small>%s</small>%s<small>%s</small></div>') % (
        cls, E(name), E("%s a trade" % M.eur_text(ticket) if ticket else sub), big, E(line))


def exam_line(e, R):
    part = "Buying" if e.get("part") == "buy" else "Selling"
    if not e.get("n"):
        return "%s: the brain of %s dropped (%s)." % (part, bday(e.get("id")), e.get("why") or "no exam")
    unit = "scan" if e.get("unit") == "scan" else "trade"
    if e.get("same"):
        verdict = "the same choice as now, nothing to change"
    elif e.get("won"):
        verdict = "learned: the new one takes over"
    else:
        verdict = "kept the current one (the new one was not clearly better)"
    extra = ""
    if e.get("part") == "sell" and e.get("rule"):
        import lernpick as L
        g = {r["id"]: r for r in L.SELL_GRID}
        extra = " (new rule: %s)" % rule_text(g.get(e["rule"])) if e.get("rule") != e.get("was") else ""
    pk = (" · the Pick: %s" % eur(e["pick"])) if e.get("pick") is not None else ""
    return "%s: the brain of %s vs. the current one on %d unseen %ss: %s vs. %s per %s%s, better in %d%% of %d re-draws. %s%s." % (
        part, bday(e.get("id")), e["n"], unit, eur(e.get("new")), eur(e.get("old")), unit, pk, round(100 * (num(e.get("p")) or 0)), 2000, verdict[0].upper() + verdict[1:], extra)


def brain_box(S, R):
    B = S.get("brain")
    if not B or not B.get("buy"):
        return ('<div class="lp-brain"><p class="lp-m">No brain yet: the first nightly training (after the filter search, about 08:50 Berlin '
                'time) builds one from every scan so far, and the next scan buys.</p></div>')
    buy, sell = B["buy"], B.get("sell") or {}
    rows = ['<p><b>Trained</b> %s · on %s coin rows from %s hourly scans</p>' % (
        E(when(R, B.get("t"))), E("{:,}".format(int((B.get("data") or {}).get("rows") or 0))), E("{:,}".format(int((B.get("data") or {}).get("scans") or 0))))]
    how = "its first brain" if buy.get("start") else "passed its exam"
    rows.append('<p><b>Buys with</b> the brain of %s (%s, trading since %s)</p>' % (E(bday(buy.get("id"))), E(how), E(when(R, buy.get("since")))))
    srule = "the Pick's own rule" if sell.get("cid") == "start" else "learned rule, trading since %s" % when(R, sell.get("since"))
    rows.append('<p><b>Sells with</b> %s (%s)</p>' % (E(rule_text(sell)), E(srule)))
    last = [e for e in B.get("exams") or [] if num(e.get("t")) == num(B.get("t"))]
    if last:
        rows.append('<ul class="lp-ex">%s</ul>' % "".join("<li class=\"%s\">%s</li>" % ("won" if e.get("won") else "", E(exam_line(e, R))) for e in last))
    else:
        rows.append('<p class="lp-m">Last night no brain was due for its exam (a new brain waits until about 2 days of unseen data are in).</p>')
    top = buy.get("top") or []
    if top:
        li = []
        for k, v in top:
            li.append('<li><span>%s</span><small class="%s">%s</small></li>' % (E(likes(label(R, k), v > 0)), tone(v), E(eur(v))))
        rows.append('<p class="lp-sub">What it looks for now</p><ul class="lp-top">%s</ul><small class="lp-m">€ per 50 € that the input moves a '
                    'coin from the bottom to the top of its scan, after 2 hours (what the brain learned, not a promise)</small>' % "".join(li))
    pend = [p for p in B.get("pending") or [] if p.get("buy") or p.get("sell")]
    if pend:
        rows.append('<p class="lp-m">Waiting for their exam: the brains of %s.</p>' % E(", ".join(bday(p["id"]) for p in pend)))
    live = [e for e in B.get("exams") or [] if not e.get("replay") and e.get("n")]
    rep = [e for e in B.get("exams") or [] if e.get("replay") and e.get("n")]
    rows.append('<p class="lp-m">Exams passed: %d of %d since it went live%s.</p>' % (
        sum(1 for e in live if e.get("won")), len(live), ("; %d of %d in the replay of the nights before" % (sum(1 for e in rep if e.get("won")), len(rep))) if rep else ""))
    return '<div class="lp-brain">%s</div>' % "".join(rows)


def trades_table(S, R):
    rows = S["trades"][:TRADES_SHOWN]
    if not rows:
        return ""
    body = []
    for p in rows:
        coin = '<td><b>%s</b><small>%s%s</small></td>' % (E(p.get("sym")), E(when(R, p.get("t"), "%b %d %H:%M")), E(" · same coin as the Pick" if p.get("samePick") else ""))
        rule = '<td><small>%s</small></td>' % E(rule_text(p.get("rule")))
        if p.get("state") == "sold":
            res = '<td class="n %s">%s<small>%s</small></td>' % (tone(p.get("eur")), E(eur(p.get("eur"))), E(WHY.get(p.get("why"), p.get("why") or "")))
        else:
            now = p.get("_now")
            res = '<td class="n">open<small>%s</small></td>' % E(("now %.2fx" % now) if now else "no price this scan")
        body.append("<tr>%s%s%s</tr>" % (coin, rule, res))
    more = (" (the last %d of %d)" % (TRADES_SHOWN, len(S["trades"]))) if len(S["trades"]) > TRADES_SHOWN else ""
    return ('<details class="lp-tr" open><summary>Its trades%s</summary><div class="lp-scroll"><table class="lp-t"><thead><tr><th>Coin</th><th>Sell rule</th>'
            '<th>Result</th></tr></thead><tbody>%s</tbody></table></div><small class="lp-m">Sold in hindsight from minute candles once 6 hours have passed '
            '(its rule replayed on them), so a result shows about 6 to 7 hours after the buy. After paper fees.</small></details>') % (E(more), "".join(body))


def exams_table(S, R):
    B = S.get("brain") or {}
    ex = [e for e in B.get("exams") or [] if e.get("n")][:EXAMS_SHOWN]
    if not ex:
        return ""
    body = []
    for e in ex:
        verdict = "same" if e.get("same") else ("learned" if e.get("won") else "kept")
        body.append('<tr class="%s"><td><b>%s</b><small>%s · brain of %s%s</small></td><td class="n">%d</td><td class="n %s">%s</td>'
                    '<td class="n %s">%s</td><td class="n">%d%%</td><td class="n"><b>%s</b></td></tr>' % (
                        "won" if e.get("won") else "", E(when(R, e.get("t"), "%b %d")), E("buying" if e.get("part") == "buy" else "selling"),
                        E(bday(e.get("id"))), E(" · replay" if e.get("replay") else ""), e["n"], tone(e.get("new")), E(eur(e.get("new"))),
                        tone(e.get("old")), E(eur(e.get("old"))), round(100 * (num(e.get("p")) or 0)), E(verdict)))
    return ('<details class="lp-tr"><summary>Every exam</summary><div class="lp-scroll"><table class="lp-t lp-t2"><thead><tr><th>Night</th>'
            '<th>unseen</th><th>new</th><th>current</th><th>agree</th><th></th></tr></thead><tbody>%s</tbody></table></div>'
            '<small class="lp-m">Per scan (buying: what each brain\'s top coin made in 2 hours) or per trade (selling: each rule on the same minute '
            'candles). A new brain takes over only when it made more and at least 80%% of 2,000 re-draws of the same data agree. '
            'Replay: the nights before it went live, worked out with the same rules.</small></details>') % "".join(body)


def learns_from(S):
    B = S.get("brain") or {}
    dt = B.get("data") or {}
    pa, tr = dt.get("paths") or {}, dt.get("trades") or {}
    if not dt:
        return ""
    n_paths = sum(int(v or 0) for v in pa.values())
    return ('<p class="lp-m">It learns from: every coin of every hourly scan in its range (%s rows: what the Pick saw and what happened 2 hours '
            'later, the Pick\'s %d buys among them) for buying; the minute candles of %d paper trades (%d Pick buys, %d old new launches, %d old '
            'launch radar, %d of its own) for selling. The Radar\'s trades end at its own sale, so they cannot replay other sell rules: they are '
            'compared below, not trained on. Its range: coins 1 hour to 3 days old with real trading (24 h volume at least 10%% of the market cap).</p>') % (
        E("{:,}".format(int(dt.get("rows") or 0))), int(tr.get("pick") or 0), n_paths, int(pa.get("hold") or 0), int(pa.get("young") or 0),
        int(pa.get("radar") or 0), int(pa.get("lern") or 0))


def section(D, R):
    import lernpick as L
    S = L.summary((D or {}).get("dir") or "", (D or {}).get("now"))
    since = S.get("since")
    tiles = ""
    if since:
        tiles = '<div class="lp-tiles">%s%s%s</div><small class="lp-m">Since its first buy, %s. Sold trades only; the Radar buys other coins (minutes-old launches).</small>' % (
            tile("Learning Pick", "learns every night", S["me"], S["ticket"], "me"), tile("Pick", "the real one", S["pick"], M.TOP_TICKET),
            tile("Radar", "rocket hunter", S["radar"], S["radar"].get("ticket")), E(when(R, since)))
    inner = ('<div class="lp"><p class="lp-lead">A second Pick with its own paper account (fake money). Every night it retrains on everything '
             'seen so far, and a new brain takes over only when it beats the current one on days neither of them has seen. It never changes '
             'the Pick or the Radar and sends no push. It would only replace the real Pick if it holds up for weeks and you say yes.</p>'
             '%s%s%s%s%s</div>') % (tiles, brain_box(S, R), trades_table(S, R), exams_table(S, R), learns_from(S))
    return ('<details class="fold lp-fold" id="learning-pick"><summary><span class="t">Learning Pick</span><span class="sum">%s</span></summary>%s</details>'
            '<style>%s</style>') % (E(head_line(S, R)), inner, CSS)


CSS = r"""
/* the Pick tab's Learning Pick (page_lernpick.py) */
.lp { display:grid; grid-template-columns:minmax(0,1fr); gap:12px; min-width:0 } .lp > * { min-width:0 }
.lp-lead { margin:0; color:var(--fg2); font-size:var(--fs-s); max-width:70ch }
.lp-tiles { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px }
.lp-tile { display:grid; gap:2px; padding:10px; border:1px solid var(--line); border-radius:12px; min-width:0 }
.lp-tile.me { border-color:color-mix(in srgb,var(--accent) 55%,var(--line)); background:color-mix(in srgb,var(--accent) 7%,transparent) }
.lp-tile .lp-tn { font-weight:600; font-size:var(--fs-s) } .lp-tile small { font-size:11px; color:var(--muted); overflow-wrap:anywhere }
.lp-tile b { font-size:18px; font-weight:650; overflow-wrap:anywhere; font-variant-numeric:tabular-nums } .lp-tile b.good { color:var(--good) } .lp-tile b.bad { color:var(--bad) }
.lp-brain { display:grid; gap:6px; padding:12px; border:1px solid var(--line); border-radius:12px; font-size:var(--fs-s) }
.lp-brain p { margin:0 } .lp-brain b { font-weight:600 }
.lp-sub { font-weight:600; margin-top:4px !important }
.lp-ex, .lp-top { margin:0; padding:0; list-style:none; display:grid; gap:4px }
.lp-ex li { padding:6px 8px; border-radius:8px; background:color-mix(in srgb,var(--fg) 4%,transparent); font-size:12px }
.lp-ex li.won { background:color-mix(in srgb,var(--good) 12%,transparent) }
.lp-top li { display:flex; justify-content:space-between; gap:10px; font-size:12px; border-bottom:1px solid var(--line2); padding:3px 0 }
.lp-top li small { font-variant-numeric:tabular-nums; white-space:nowrap } .lp-top .good { color:var(--good) } .lp-top .bad { color:var(--bad) }
.lp-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100% }
.lp-t { width:100%; border-collapse:collapse; font-size:12px }
.lp-t th { text-align:left; font-weight:500; color:var(--muted); font-size:11px; padding:4px 6px; border-bottom:1px solid var(--line) }
.lp-t td { padding:6px; border-bottom:1px solid var(--line2); vertical-align:top } .lp-t td b { font-weight:600 }
.lp-t td small { display:block; font-size:11px; color:var(--muted) }
.lp-t td.n, .lp-t th:last-child { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
.lp-t2 th:not(:first-child) { text-align:right } .lp-t2 td { padding:6px 4px } .lp-t2 { font-size:11.5px }
.lp-t .good { color:var(--good) } .lp-t .bad { color:var(--bad) } .lp-t tr.won td { background:color-mix(in srgb,var(--good) 8%,transparent) }
.lp-m { margin:0; font-size:11px; color:var(--muted) }
details.lp-tr > summary { color:var(--accent); font-weight:500; cursor:pointer; min-height:44px; display:flex; align-items:center }
.lp-tile b { font-size:16px } @media (max-width:340px) { .lp-tiles { grid-template-columns:1fr } }
"""
