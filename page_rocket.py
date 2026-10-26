"""The rocket hunter on the page (fake money only, nothing is ever bought for real): report.py shows it at the top of the Radar tab.

section(D) -> HTML, a compact block "Rocket hunter (paper)":
  - the two paper accounts side by side: Pick (the scan's paper account, its sell rule unchanged) and Rocket hunter (its own
    account: rocket_watch.py buys a coin once when its score reaches the cut, rule A sells it), each with its balance, how many of
    10 closed trades ended in profit, and its 3x/10x hits
  - the rocket hunter's open positions (bought when, at what price, now, high) and its last sells (buy price → sell price, why, when),
    each with a line when there is none ("No trade yet" before its first buy), and a fold with all its sold trades
  - the best scores of its last round
  - one honest line: on the corrected history (22 Oct) the model was in the red; this account is its live test
  - a fold with the tests of 22 Oct (rocket_tests.json next to this module, research/winlose/rocket_tests_export.py): the corrected
    history, the replay on the unseen days 9-21 Oct (research/winlose/backfill.py), an earlier first check, 134 other exit rules, a
    model deciding "stay in or get out" (none held)
D: report.py's page data; reads D["dir"]/db/memebot/rocket.json (rocket_watch.py writes it on the branch rocket-data, the scan job
copies it) and, for the Pick side, page_account's numbers. Every value goes through a number check or html.escape. No script in
section(); LIVE_JS (report.py puts it after the block) reads the app's live row "rocket" (rocket_watch.py writes it every round) while
the Radar or Start tab is open, so the account, its open positions, its last sells and the candidates move between two scans; it
only fills the data-rk-* hooks of both tabs with textContent, and rocket.json stays what the page shows without the live store.
"""
import html, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
DOC = ("db", "memebot", "rocket.json")
TESTS = os.path.join(HERE, "rocket_tests.json")
SHOWN = 5                 # candidates in view on the Radar tab; the rest of the round behind "N more"
SOLD = 5                  # last sells on the Radar tab
WHY = {"stop": "stop −30%", "11x": "hit 11x", "6h": "after 6 h", "gone": "coin gone"}
NO_TRADE = ("No trade yet: the Radar account has bought nothing since it started (%s). It buys only when a coin reaches 100%% of the "
            "line in the candidates below, so days without a buy are normal.")


def since_day():
    """The day the Radar account started (memebot.FRESH_AT, the accounts' fresh start of Oct 22), e.g. "Oct 22"."""
    try:
        import page_account as PA
        return PA.mday(num(getattr(M, "FRESH_AT", None)))
    except Exception:
        return "Oct 22"


def num(v):
    return M.num(v)


def eur(v):
    v = num(v)
    return "–" if v is None else ("%+.2f €" % (0.0 if abs(v) < 0.005 else v)).replace("-", "−")


def load(d):
    try:
        doc = json.load(open(os.path.join(d or "", *DOC)))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("book"), dict) else None


def load_tests(path=None):
    try:
        t = json.load(open(path or TESTS))
    except (OSError, ValueError):
        return None
    return t if isinstance(t, dict) and isinstance(t.get("history"), dict) else None


def tests(t=None):
    """The fold "Tested on Oct 22": the corrected history of the live rule and the three tests, each with its coins and result."""
    import page_home as PH
    t = t if t is not None else load_tests()
    if not t:
        return ""
    pc = lambda v: "–" if num(v) is None else PH.de_num(num(v), 1) + "%"
    h = (t.get("history") or {}).get("0.005") or {}
    li = []
    if num(h.get("coins")):
        li.append("<li><b>Look back Aug 10 – Oct 8, only the trades live sees</b><span>%d buys: %s per 20 € · %s of 10 in profit · 10x in %s · %s of 10,000 "
                  "simulations in profit</span></li>" % (int(num(h["coins"])), E(PH.de_eur(h.get("avg"), True)), E(PH.de_num(num(h.get("inProfitOf10")) or 0, 1)),
                                                       E(pc(h.get("x10"))), E(pc(h.get("sim")))))
    rp = (t.get("replay") or {}).get("0.005") or {}
    if num(rp.get("coins")):
        x10 = int(num(rp.get("x10")) or 0)
        li.append("<li><b>Retest Oct 9–21, unseen days as if live</b><span>%d buys: %s per 20 € · %s of 10 in profit · %s · %s of 10,000 "
                  "simulations in profit</span></li>" % (int(num(rp["coins"])), E(PH.de_eur(rp.get("avg"), True)), E(PH.de_num(num(rp.get("inProfitOf10")) or 0, 1)),
                                                       "no 10x" if not x10 else "%d× 10x" % x10, E(pc(rp.get("sim")))))
    ea = t.get("early") or {}
    vs = {k: v for k, v in (ea.get("variants") or {}).items() if isinstance(v, dict) and k != "V30"}
    if vs:
        best = max(vs.items(), key=lambda kv: num(kv[1].get("avg")) or -99)
        held = [k for k, v in vs.items() if v.get("holds")]
        li.append("<li><b>Enter earlier (5, 10, 15 or 20 instead of 30 minutes)</b><span>%s · best %s minutes: %s per 20 €</span></li>" % (
            "holds" if held else "does not hold", E(best[0][1:]), E(PH.de_eur(best[1].get("avg"), True))))
    ex = t.get("exits") or {}
    if num(ex.get("rules")):
        li.append("<li><b>Other sell rules (%d: partial sells, trailing stop, time limit)</b><span>%s</span></li>" % (
            int(num(ex["rules"])), "none beats −30%, 11x, 6 h" if not ex.get("choice") else "new: " + E(ex["choice"])))
    ki = t.get("ki") or {}
    if isinstance(ki.get("ki"), dict) and isinstance(ki.get("ruleA"), dict):
        li.append("<li><b>AI decides every 15 minutes: stay in or get out</b><span>%s · %s per 20 € against %s with the fixed rule "
                  "(%d buys); on the only real 10x coin it would have stayed in until it crashed</span></li>" % (
                      "holds" if ki.get("holds") else "does not hold", E(PH.de_eur(ki["ki"].get("avg"), True)), E(PH.de_eur(ki["ruleA"].get("avg"), True)),
                      int(num(ki["ki"].get("coins")) or 0)))
    if not li:
        return ""
    return ('<details class="rk-more rk-tests"><summary>Tested on Oct 22 (look back, fake money)</summary><ul class="rk-tl">%s</ul>'
            '<p class="rk-s">Every test was fixed in advance and ran week by week on earlier data only. The live buys of this account '
            'are the real test.</p></details>') % "".join(li)


def sym(p, a=None):
    return str(p.get("sym") or str(p.get("addr") or a or "?")[:6])[:14]


def chart_div(p, closed=False):
    """The position's price line for LIVE_JS's chart (it draws every [data-rk-ch], with or without the live store): the points
    [minutes since the buy, multiple], and for a sell its minute and multiple. Numbers only."""
    pts = [[int(m), round(float(v), 4)] for m, v in (p.get("chart") or []) if num(m) is not None and num(v) is not None][-400:]
    if len(pts) < 2 and not closed:
        return '<div class="rk-ch" data-rk-ch="[]"></div>'
    end = ""
    if closed and num(p.get("out")) and num(p.get("t")):
        end = ' data-rk-end="%d,%s"' % (int((num(p["out"]) - num(p["t"])) // 60_000), round(num(p.get("mult")) or 0.0, 4))
    return '<div class="rk-ch" data-rk-ch="%s"%s></div>' % (E(json.dumps(pts, separators=(",", ":"))), end)


def px_text(v):
    """A coin's price in US dollars as the rest of the page writes it (report.fmt_px; LIVE_JS's px() the same): $0.0002288, $1.25."""
    v = num(v)
    if v is None or v <= 0:
        return "–"
    if v >= 1:
        return "$" + format(v, ",.2f")
    d = -int(math.floor(math.log10(v))) + 3
    return ("$%.3g" % v) if d > 12 else "$" + ("%." + str(d) + "f") % v


def at_text(ms, day=True):
    """Oct 25, 14:02 (or 14:02) in the page's time zone."""
    try:
        import page_account as PA
        return ("%s, %s" % (PA.mday(ms), PA.hhmm(ms))) if day else PA.hhmm(ms)
    except Exception:
        return ""


def open_li(PH, p, a=None):
    """One open position: bought when and at what price, the price now and its high as multiples (LIVE_JS builds the same row)."""
    return '<li><b>%s</b><span>bought %s at %s · now x%s · high x%s</span>%s</li>' % (
        E(sym(p, a)), E(at_text(p.get("t")) if num(p.get("t")) else "–"), E(px_text(p.get("px"))), E(PH.de_num(num(p.get("now")) or 1.0)),
        E(PH.de_num(num(p.get("hi")) or 1.0)), chart_div(p))


def sold_li(PH, p):
    """One sell: symbol, buy price → sell price, multiple, why and when, the result in euro (LIVE_JS builds the same row)."""
    at = at_text(p["out"]) if num(p.get("out")) else ""
    v, m, bp = num(p.get("eur")) or 0.0, num(p.get("mult")) or 0.0, num(p.get("px"))
    bits = [("%s → %s" % (px_text(bp), px_text(bp * m))) if bp else "", "x" + PH.de_num(m), WHY.get(str(p.get("why") or ""), str(p.get("why") or "")), at]
    return '<li class="%s"><b>%s</b><span>%s</span><em>%s</em>%s</li>' % (
        PH.tone(v), E(sym(p)), E(" · ".join(b for b in bits if b)), E(PH.de_eur(v, True)), chart_div(p, True) if p.get("chart") else "")


def all_trades(PH, bk):
    """The fold "All trades of the Radar account": every sold position of the scan's copy (rocket.json keeps the last 500), newest first:
    the coin and its buy time, buy price → sell price with the multiple, when and why it sold, the result in euro. '' before the first sale."""
    cl = sorted((p for p in bk.get("closed") or [] if isinstance(p, dict)), key=lambda p: -(num(p.get("out")) or 0))
    if not cl:
        return ""
    rows = []
    for p in cl:
        v, m, bp = num(p.get("eur")) or 0.0, num(p.get("mult")) or 0.0, num(p.get("px"))
        rows.append('<tr><td><b>%s</b><small>bought %s</small></td><td>%s → %s<small>x%s · sold %s · %s</small></td><td class="n %s">%s</td></tr>' % (
            E(sym(p)), E(at_text(p.get("t")) if num(p.get("t")) else "–"), E(px_text(bp)), E(px_text(bp * m) if bp else "–"), E(PH.de_num(m)),
            E(at_text(p.get("out")) if num(p.get("out")) else "–"), E(WHY.get(str(p.get("why") or ""), str(p.get("why") or ""))), PH.tone(v), E(PH.de_eur(v, True))))
    tot = sum(num(p.get("eur")) or 0.0 for p in cl)
    return ('<details class="rk-more rk-all"><summary>All trades of the Radar account (%d sold, %s)</summary><div class="rk-scroll"><table class="rk-t">'
            '<thead><tr><th>Coin</th><th>Buy → sell price</th><th>Result</th></tr></thead><tbody>%s</tbody></table></div>'
            '<small class="rk-s">Prices in US dollars per coin, results in euro after the paper fees. This list is the last scan\'s copy; the last '
            'sells above move live.</small></details>') % (len(cl), E(PH.de_eur(tot, True)), "".join(rows))


def section(D):
    """The Radar tab's top block: the rocket hunter's own account, its open positions, every candidate of its last round with a bar to the
    buy cut and the rules in one line."""
    import page_home as PH
    doc = load((D or {}).get("dir"))
    since = ""
    try:
        import page_account as PA
        fresh = num(getattr(M, "FRESH_AT", None))
        since = ("since %s, %s" % (PA.mday(fresh), PA.hhmm(fresh))) if fresh else ""
    except Exception:
        since = ""
    head = ('<div class="rk-head"><div><h3>Radar account 🚀</h3><small>%s</small></div><span class="chip warn">fake money</span></div>' % E(
        " · ".join(x for x in ("rocket hunter, every 15 minutes", since, "%s per buy" % PH.de_eur(float(M.TICKET)).replace(".00", "")) if x)))
    wrap = lambda inner: '<div class="rk" data-pa="rocket"%s>%s%s</div><style>%s</style>' % (
        (' data-rk-box data-rk-t="%d"' % int(num(doc.get("t")) or 0)) if doc else "", head, inner, CSS)
    # Oct 26 clean-up: the Pick account "for comparison" left this block (each account once, both on the Start tab)
    if doc is None:
        return wrap('<p class="rk-s">The rocket hunter has not run yet: every 15 minutes it checks the radar\'s coins and buys on '
                    'paper only when a coin\'s rocket score reaches the buy line.</p>')
    b = PH.rocket_book(doc)
    win = "–" if b["win"] is None else PH.de_num(b["win"], 1).rstrip("0").rstrip(".")
    stats = [("in profit", '<span data-rk-st="win">%s</span>/10' % E(win), ""), ("3x · 10x", "%d · %d" % (b["x3"], b["x10"]), "hits"),
             ("open", str(b["open"]), "open"), ("closed", str(b["closed"]), "closed")]
    acct = ('<div class="rk-acct"><div class="rk-bal"><span class="k">Balance</span><b class="%s" data-rk-bal>%s</b>%s</div><div class="rk-sts">%s</div></div>') % (
        PH.tone(b["bal"]), E(PH.de_eur(b["bal"], True)), PH.spark(b["pts"], PH.tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b%s>%s</b></span>' % (E(k), (' data-rk-st="%s"' % c) if c else "", v if not c else E(v)) for k, v, c in stats))
    bk = doc.get("book") or {}
    op = [open_li(PH, p, a) for a, p in sorted((bk.get("open") or {}).items(), key=lambda kv: -(num(kv[1].get("t")) or 0)) if isinstance(p, dict)]
    sold = [sold_li(PH, p) for p in sorted((p for p in bk.get("closed") or [] if isinstance(p, dict)), key=lambda p: -(num(p.get("out")) or 0))[:SOLD]]
    cut = num(doc.get("cut")) or 0
    rows = []
    for r in [r for r in doc.get("top") or [] if isinstance(r, dict)]:
        sh = (num(r.get("score")) or 0) / cut if cut > 0 else 0
        rows.append('<li class="%s"><b>%s</b><span class="rk-bar"><i style="width:%.1f%%"></i></span><em>%s</em><small>%d min old%s</small></li>' % (
            "buy" if r.get("buy") else ("near" if sh >= 0.5 else ""), E(str(r.get("sym") or str(r.get("addr") or "?")[:6])[:14]), max(2.0, min(100.0, 100 * sh)),
            "bought" if r.get("buy") else "%d%%" % round(100 * sh), int(num(r.get("age")) or 0),
            (" · MC $%s" % PH.de_num(num(r["mc"]), 0)) if num(r.get("mc")) else ""))
    rd = doc.get("round") or {}
    when = ""
    if num(doc.get("t")):
        try:
            import page_account as PA
            when = "Last round %s %s · " % (PA.mday(doc["t"]), PA.hhmm(doc["t"]))
        except Exception:
            when = ""
    body = (acct
            + '<p class="rk-s rk-live" data-rk-live hidden></p>'
            + '<div class="rk-st" data-rk-opw><span class="k">Open positions</span><ul class="rk-op" data-rk-op>%s</ul><p class="rk-s" data-rk-opnone%s>None open right now.</p></div>' % (
                "".join(op), " hidden" if op else "")
            + '<div class="rk-st" data-rk-soldw><span class="k">Last sells</span><ul class="rk-sold" data-rk-sold>%s</ul><p class="rk-s" data-rk-soldnone%s>%s</p></div>' % (
                "".join(sold), " hidden" if sold else "", E(NO_TRADE % since_day()))
            + all_trades(PH, bk)
            + ('<div class="rk-st"><span class="k">Candidates of the last round · buys at 100%% of the line (%s)</span><ul class="rk-cands" data-rk-cands="rk">%s</ul>%s</div>' % (
                E(PH.de_num(cut, 4)), "".join(rows[:SHOWN]), ('<details class="rk-more" data-rk-more><summary>%d more</summary><ul class="rk-cands">%s</ul></details>' % (
                    len(rows) - SHOWN, "".join(rows[SHOWN:]))) if len(rows) > SHOWN else "") if rows else '<p class="rk-s">No coin of the right age in the last round.</p>')
            + '<p class="rk-s"><span data-rk-round>%s%s radar coins watched, %d scored. </span>20 € per coin, sold at −30%%, 11x or after 6 h. '
              'Live test: in the corrected look back this strategy lost money (about 1 in 10 buys in profit, 1 in 45 went 10x).</p>' % (
                  E(when), E(PH.de_num(int(num(rd.get("candidates")) or 0), 0)), int(num(rd.get("scored")) or 0))
            + tests())
    return wrap(body)


CSS = r"""
/* the rocket hunter (page_rocket.py) at the top of the Radar tab */
.rk [hidden] { display:none !important }      /* an empty list (open positions, last sells) and the live line stay out of view until they have something */
.rk { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:14px 16px 10px; display:grid; gap:12px; min-width:0; margin-bottom:12px;
  background-image:radial-gradient(120% 80% at 100% 0%, color-mix(in srgb,var(--nn2) 14%,transparent), transparent 60%) }
.rk-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:4px 10px } .rk-head h3 { margin:0; font-size:19px }
.rk-head small { font-size:var(--fs-xs); color:var(--muted) }
.rk-acct { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:12px; align-items:center }
.rk-bal { display:grid; gap:2px; min-width:0 } .rk-bal b { font-size:28px; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; white-space:nowrap }
.rk-bal b.good { color:var(--good) } .rk-bal b.bad { color:var(--bad) }
.rk .k { font-size:var(--fs-xs); color:var(--muted) }
.rk-sts { display:grid; grid-template-columns:1fr 1fr; gap:6px }
.rk-sts > span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
.rk-sts i { font-style:normal; font-size:11px; color:var(--muted) } .rk-sts b { font-size:15px; font-variant-numeric:tabular-nums }
.rk-st { display:grid; gap:6px } .rk-st ul { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.rk-op li { display:grid; font-size:var(--fs-s) } .rk-op li span { color:var(--fg2); font-size:var(--fs-xs) }
.rk-cands li { display:grid; grid-template-columns:minmax(64px,auto) 1fr auto; column-gap:10px; align-items:center; font-size:var(--fs-s) }
.rk-cands li b { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:120px }
.rk-cands li em { font-style:normal; font-variant-numeric:tabular-nums; color:var(--fg2); min-width:44px; text-align:right }
.rk-cands li small { grid-column:1 / -1; font-size:11px; color:var(--muted); margin-top:-2px }
.rk-bar { height:6px; border-radius:6px; background:color-mix(in srgb,var(--fg) 8%,transparent); overflow:hidden }
.rk-bar i { display:block; height:100%; border-radius:6px; background:linear-gradient(90deg,var(--accent),var(--nn2)) }
.rk-cands li.near em { color:var(--warn) } .rk-cands li.buy em { color:var(--good); font-weight:600 } .rk-cands li.buy .rk-bar i { background:var(--good-mark) }
.rk-more > summary { cursor:pointer; color:var(--accent); font-size:var(--fs-s); padding:6px 0 } .rk-more[open] > summary { margin-bottom:6px }
.rk-s { margin:0; font-size:var(--fs-xs); color:var(--muted); max-width:70ch; overflow-wrap:anywhere }
.rk-sold li { display:grid; grid-template-columns:minmax(0,1fr) auto; column-gap:10px; font-size:var(--fs-s); padding:4px 6px; border-radius:10px; margin:0 -6px }
.rk-sold li span { grid-column:1; color:var(--fg2); font-size:var(--fs-xs) } .rk-sold li em { grid-column:2; grid-row:1 / span 2; align-self:center; font-style:normal; font-variant-numeric:tabular-nums; font-weight:600 }
.rk-sold li.good em { color:var(--good) } .rk-sold li.bad em { color:var(--bad) }
.rk-sold li.new, .rk-op li.new { background:color-mix(in srgb,var(--nn1) 12%,transparent); animation:rkNew 2.4s ease-out 2 }
@keyframes rkNew { 0% { box-shadow:0 0 0 0 color-mix(in srgb,var(--nn1) 60%,transparent) } 100% { box-shadow:0 0 0 10px transparent } }
.rk-live { display:flex; align-items:center; gap:6px; color:var(--fg2) } .rk-live::before, .hm-live::before { content:""; width:7px; height:7px; border-radius:50%;
  background:var(--good); box-shadow:0 0 8px var(--good); flex:none }
.rk-op li { gap:4px } .rk-ch { grid-column:1 / -1; min-width:0; margin-top:4px } .rk-ch svg { display:block; width:100%; height:auto; overflow:visible }
.rk-ch-wait { font-size:11px; color:var(--muted) }
.rk-svg .ln { fill:none; stroke-width:1.8; stroke-linejoin:round; stroke-linecap:round } .rk-svg.up .ln { stroke:var(--good) } .rk-svg.dn .ln { stroke:var(--bad) }
.rk-svg .g0 { stop-opacity:.28 } .rk-svg.up .g0, .rk-svg.up .g1 { stop-color:var(--good) } .rk-svg.dn .g0, .rk-svg.dn .g1 { stop-color:var(--bad) } .rk-svg .g1 { stop-opacity:0 }
.rk-svg .lv { stroke-width:1; stroke-dasharray:3 3; stroke:var(--muted) } .rk-svg .lv.stop { stroke:var(--bad) } .rk-svg .lv.goal { stroke:var(--good) }
.rk-svg text { font:10px/1 system-ui, sans-serif; fill:var(--muted) } .rk-svg .lt.stop { fill:var(--bad) } .rk-svg .lt.goal { fill:var(--good) }
.rk-svg .lx { fill:var(--fg); font-weight:600 } .rk-svg .pb { fill:var(--accent) } .rk-svg .pn { fill:var(--fg) } .rk-svg.up .ps { fill:var(--good) } .rk-svg.dn .ps { fill:var(--bad) }
.rk-svg .pulse { fill:var(--nn1); opacity:.35; transform-box:fill-box; transform-origin:center; animation:rkPulse 1.6s ease-out infinite }
@keyframes rkPulse { 0% { transform:scale(.5); opacity:.6 } 100% { transform:scale(1.8); opacity:0 } }
.rk-sold li .rk-ch { grid-column:1 / -1; grid-row:3 }
@media (prefers-reduced-motion:reduce) { .rk-sold li.new, .rk-op li.new, .rk-svg .pulse { animation:none } }
.rk-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100% }
.rk-t { width:100%; border-collapse:collapse; font-size:12px }
.rk-t th { text-align:left; font-weight:500; color:var(--muted); font-size:11px; padding:4px 6px; border-bottom:1px solid var(--line) }
.rk-t td { padding:6px; border-bottom:1px solid var(--line2); vertical-align:top; font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.rk-t td small { display:block; font-size:11px; color:var(--muted) } .rk-t td.n, .rk-t th:last-child { text-align:right; white-space:nowrap }
.rk-t .good { color:var(--good) } .rk-t .bad { color:var(--bad) }
.rk-tl { list-style:none; margin:0 0 6px; padding:0; display:grid; gap:8px } .rk-tl li { display:grid; gap:1px; font-size:var(--fs-s) }
.rk-tl li span { color:var(--fg2); font-size:var(--fs-xs); overflow-wrap:anywhere }
@media (max-width:560px) { .rk { padding:12px 12px 8px } .rk-acct { grid-template-columns:1fr } }
"""


# The live row "rocket" of the app's live store (rocket_watch.py writes it after every 15-minute round): one GET with the publishable key
# (data-sb-url/data-sb-key on <html>, set by bot.py site) every 45 s while the page is visible and the Radar or Start tab is open. It
# fills the data-rk-* hooks of every [data-rk-box] whose scan copy (data-rk-t) is not newer, only with textContent; without the store,
# or when a read fails, the page keeps what the scan wrote (rocket.json).
LIVE_JS = r"""
(function(){
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var boxes=[].slice.call(document.querySelectorAll('[data-rk-box]'));
  var NS='http://www.w3.org/2000/svg',W=300,HT=96,PL=4,PR=58,PT=8,PB=16;
  function sv(tag,at,txt){var e=document.createElementNS(NS,tag);for(var k in at)e.setAttribute(k,at[k]);if(txt!=null)e.textContent=txt;return e;}
  function dex(v,d){return (Math.round(v*Math.pow(10,d))/Math.pow(10,d)).toFixed(d);}
  // one position's price line: log scale, the buy (1x) and the stop (0.7x) as dashed lines, 11x when the line comes near it, the buy
  // as a dot at minute 0, the sell (data-rk-end) as a dot at its minute, an open position's last point pulsing
  function draw(div){
    var pts;try{pts=JSON.parse(div.getAttribute('data-rk-ch')||'[]');}catch(e){pts=[];}
    pts=(Array.isArray(pts)?pts:[]).filter(function(q){return Array.isArray(q)&&isFinite(q[0])&&isFinite(q[1])&&q[1]>0;});
    var end=String(div.getAttribute('data-rk-end')||'').split(','),em=parseFloat(end[0]),ev=parseFloat(end[1]),sold=isFinite(em);
    if(sold&&isFinite(ev)&&ev>0)pts.push([em,ev]);
    div.textContent='';
    if(pts.length<2){div.appendChild(el('small','rk-ch-wait','The price line appears after the first minute check'));return;}
    var xs=pts.map(function(q){return q[0];}),vs=pts.map(function(q){return q[1];});
    var x1=Math.max(30,Math.max.apply(null,xs)),lo=Math.min(0.62,Math.min.apply(null,vs)*0.95),hi=Math.max(1.3,Math.max.apply(null,vs)*1.12);
    if(hi>7)hi=Math.max(hi,12);
    var L=Math.log,X=function(m){return PL+(W-PL-PR)*m/x1;},Y=function(v){return PT+(HT-PT-PB)*(L(hi)-L(Math.max(v,1e-6)))/(L(hi)-L(lo));};
    var last=pts[pts.length-1],up=last[1]>=1,svg=sv('svg',{viewBox:'0 0 '+W+' '+HT,'class':'rk-svg '+(up?'up':'dn'),role:'img','aria-label':'Price since the buy'});
    var gid='rkg'+Math.random().toString(36).slice(2,8),g=sv('linearGradient',{id:gid,x1:0,y1:0,x2:0,y2:1});
    g.appendChild(sv('stop',{offset:'0','class':'g0'}));g.appendChild(sv('stop',{offset:'1','class':'g1'}));var df=sv('defs',{});df.appendChild(g);svg.appendChild(df);
    function lvl(v,cls,txt){if(v<lo||v>hi)return;var y=Y(v).toFixed(1);svg.appendChild(sv('line',{x1:PL,x2:W-PR,y1:y,y2:y,'class':'lv '+cls}));
      svg.appendChild(sv('text',{x:W-PR+4,y:(+y+3).toFixed(1),'class':'lt '+cls},txt));}
    lvl(1,'buy','buy 1x');lvl(0.7,'stop','stop');if(hi>=11)lvl(11,'goal','target 11x');
    var d=pts.map(function(q,i){return (i?'L':'M')+X(q[0]).toFixed(1)+' '+Y(q[1]).toFixed(1);}).join(' ');
    svg.appendChild(sv('path',{d:d+' L'+X(last[0]).toFixed(1)+' '+(HT-PB)+' L'+X(pts[0][0]).toFixed(1)+' '+(HT-PB)+' Z',fill:'url(#'+gid+')','class':'ar'}));
    svg.appendChild(sv('path',{d:d,'class':'ln'}));
    svg.appendChild(sv('circle',{cx:X(pts[0][0]).toFixed(1),cy:Y(pts[0][1]).toFixed(1),r:3.5,'class':'pb'}));
    var lx=X(last[0]),ly=Y(last[1]);
    if(!sold)svg.appendChild(sv('circle',{cx:lx.toFixed(1),cy:ly.toFixed(1),r:7,'class':'pulse'}));
    svg.appendChild(sv('circle',{cx:lx.toFixed(1),cy:ly.toFixed(1),r:3.5,'class':sold?'ps':'pn'}));
    var ty=ly-9<PT+6?ly+16:ly-9;
    svg.appendChild(sv('text',{x:(lx-6).toFixed(1),y:ty.toFixed(1),'class':'lx','text-anchor':'end'},(sold?'sold x':'now x')+dex(last[1],2)));
    svg.appendChild(sv('text',{x:PL,y:HT-3,'class':'ax'},'buy'));
    svg.appendChild(sv('text',{x:W-PR,y:HT-3,'class':'ax','text-anchor':'end'},x1>=120?dex(x1/60,1)+' h':Math.round(x1)+' min'));
    div.appendChild(svg);
  }
  function drawAll(root){[].forEach.call((root||document).querySelectorAll('[data-rk-ch]'),draw);}
  window.memebotRkChart=draw;      // the brain's coin sheet (page_brain.py) draws a bought candidate's line with it when the sheet opens
  function chartDiv(p,sold){var e=el('div','rk-ch');e.setAttribute('data-rk-ch',JSON.stringify(Array.isArray(p.chart)?p.chart:[]));
    if(sold&&isFinite(+p.out)&&isFinite(+p.t))e.setAttribute('data-rk-end',Math.floor((+p.out-+p.t)/60000)+','+(+p.mult||0));return e;}
  drawAll();
  if(!/^https:\/\/[^\s\/]+$/.test(url)||!key||!boxes.length||!window.fetch)return;
  var EVERY=45000,SOLD=5,SHOWN=5,next=0,busy=false,seen=null,MINUS='−';
  var WHY={stop:'stop −30%','11x':'hit 11x','6h':'after 6 h',gone:'coin gone'};
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function de(v,d){var s=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});return (v<0&&/[1-9]/.test(s)?MINUS:'')+s;}
  function eur(v){return (v>0.004?'+':'')+de(v,2)+' €';}
  function tone(v){return v>0.004?'good':(v<-0.004?'bad':'');}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function at(ms){try{return new Date(ms).toLocaleDateString('en-US',{month:'short',day:'2-digit'})+', '+hhmm(ms);}catch(e){return '';}}
  function px(p){if(!(p>0))return '–';if(p>=1)return '$'+p.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    var d=-Math.floor(Math.log10(p))+3;return d>12?'$'+p.toPrecision(3):'$'+p.toFixed(d);}
  function sym(p){return String(p.sym||String(p.addr||'?').slice(0,6)).slice(0,14);}
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
  function li(cls,b,span,em){var e=el('li',cls);e.appendChild(el('b',null,b));if(span!=null)e.appendChild(el('span',null,span));if(em!=null)e.appendChild(el('em',null,em));return e;}
  function fill(box,sel,items){var u=box.querySelector(sel);if(!u)return null;u.textContent='';items.forEach(function(x){u.appendChild(x);});return u;}
  function show(w,on){if(w){if(on)w.removeAttribute('hidden');else w.setAttribute('hidden','');}}
  function set(box,k,v){[].forEach.call(box.querySelectorAll('[data-rk-st="'+k+'"]'),function(e){e.textContent=v;});}
  function apply(d){
    var s=d.summary,t=n(d.t)||0,cut=n(d.cut)||0,bal=(n(s.eur)||0)+(n(s.openEur)||0),w=n(s.inProfitOf10);
    var now=(Array.isArray(d.soldNow)?d.soldNow:[]).map(String);
    var op=(Array.isArray(d.open)?d.open:[]).filter(function(p){return p&&typeof p==='object';}).sort(function(a,b){return (n(b.t)||0)-(n(a.t)||0);});
    var cl=(Array.isArray(d.closed)?d.closed:[]).filter(function(p){return p&&typeof p==='object';}).sort(function(a,b){return (n(b.out)||0)-(n(a.out)||0);}).slice(0,SOLD);
    var ids=cl.map(function(p){return String(p.addr)+'@'+(n(p.out)||0);}),fresh=function(p){var id=String(p.addr)+'@'+(n(p.out)||0);
      return now.indexOf(String(p.addr))>=0||(seen!==null&&seen.indexOf(id)<0);};
    boxes.forEach(function(box){
      if(t<(n(box.getAttribute('data-rk-t'))||0))return;
      [].forEach.call(box.querySelectorAll('[data-rk-bal]'),function(e){e.textContent=eur(bal);e.classList.remove('good','bad');if(tone(bal))e.classList.add(tone(bal));});
      set(box,'win',w===null?'–':de(w,1).replace(/\.0$/,''));
      set(box,'hits',(n(s.x3)||0)+' · '+(n(s.x10)||0));
      set(box,'open',String(n(s.open)||0));set(box,'closed',String(n(s.trades)||0));
      var u=fill(box,'[data-rk-op]',op.map(function(p){var e=li('',sym(p),'bought '+(n(p.t)?at(n(p.t)):'–')+' at '+px(n(p.px))+' · now x'+de(n(p.now)||1,2)+' · high x'+de(n(p.hi)||1,2));
        e.appendChild(chartDiv(p,false));return e;}));
      if(u)[].forEach.call(box.querySelectorAll('[data-rk-opnone]'),function(e){show(e,!op.length);});
      u=fill(box,'[data-rk-sold]',cl.map(function(p){var v=n(p.eur)||0,o=n(p.out),bp=n(p.px),m=n(p.mult)||0;
        var e=li((tone(v)+(fresh(p)?' new':'')).trim(),sym(p),[bp?px(bp)+' → '+px(bp*m):'','x'+de(m,2),WHY[p.why]||String(p.why||''),o?at(o):''].filter(Boolean).join(' · '),eur(v));
        if(Array.isArray(p.chart)&&p.chart.length)e.appendChild(chartDiv(p,true));return e;}));
      if(u)[].forEach.call(box.querySelectorAll('[data-rk-soldnone]'),function(e){show(e,!cl.length);});
      var cs=box.querySelector('[data-rk-cands]');
      if(cs&&Array.isArray(d.top)&&d.top.length){var pre=cs.getAttribute('data-rk-cands')==='hm'?'hm':'rk';
        fill(box,'[data-rk-cands]',d.top.slice(0,SHOWN).filter(function(r){return r&&typeof r==='object';}).map(function(r){
          var sh=cut>0?(n(r.score)||0)/cut:0,e=li(r.buy?'buy':(sh>=0.5?'near':''),sym(r),null,null),bar=el('span',pre+'-bar'),i=el('i');
          i.style.width=Math.max(2,Math.min(100,100*sh)).toFixed(1)+'%';bar.appendChild(i);e.appendChild(bar);
          e.appendChild(el('em',null,r.buy?'bought':Math.round(100*sh)+'%'));e.appendChild(el('small',null,Math.round(n(r.age)||0)+' min old'));return e;}));
        [].forEach.call(box.querySelectorAll('[data-rk-more]'),function(m){m.setAttribute('hidden','');});}
      drawAll(box);
      [].forEach.call(box.querySelectorAll('[data-rk-live]'),function(e){e.textContent='Live · as of '+hhmm(t)+' · new buys and sells show up here without a reload';e.removeAttribute('hidden');});
      // a round newer than the page: its time (the page's counts belong to the older round, the live row has none)
      if(t>(n(box.getAttribute('data-rk-t'))||0))[].forEach.call(box.querySelectorAll('[data-rk-round]'),function(e){e.textContent='Last round '+hhmm(t)+'. ';});
    });
    seen=ids;
  }
  function want(){if(document.visibilityState==='hidden')return false;var a=document.getElementById('tab-young'),b=document.getElementById('tab-home');
    return (!a&&!b)||!!(a&&a.checked)||!!(b&&b.checked);}
  function poll(){
    if(busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+EVERY;
    var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    fetch(url+'/rest/v1/live?select=doc&id=eq.rocket',{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status;return r.json();})
      .then(function(rows){var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;if(d&&typeof d==='object'&&d.summary&&typeof d.summary==='object')apply(d);})
      .catch(function(){next=Date.now()+2*EVERY;})
      .then(function(){clearTimeout(tm);busy=false;});
  }
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&/^tab-(young|home)$/.test(e.target.id||''))poll();});
  setInterval(poll,5000);poll();
})();
"""
