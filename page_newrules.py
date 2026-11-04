"""page_newrules.py: the fold "New rules test 🧪" on the Pick tab (newrules.py's accounts) and its box on the Start tab. Fake money only:
nothing here buys, signs or sends anything, and nothing here is advice. English words (the whole app in English since Oct 22).

section(D, R) -> HTML: a fold at the top of "Tests on the side". Its summary line says how many of the 9 frozen rules are in profit on
the new days; inside, one sentence on what this is and why most such rules turn out to be luck, then three small tables:
  - N1-N3 (other sell rules on the Pick account's buys) next to the real Pick account, X (the Sell bot replayed) and K
  - P1-P3 (Pick buys to leave out): the kept buys sold by the Sell bot replayed, and the real account on the same buys
  - B1-B3 (buy rules on every scanned coin, sold after about 2 h): from the nightly filter search's doc (db/memebot/filtersearch.json
    "newrules"), so a day behind
box(D, R) -> the Start tab's box (page_live.accounts) in place of the Learning Pick's, which stopped on Nov 4.
D: report.py's page data (D["dir"], D["now"]); R: report itself (local times). Every chain string is escaped. Static HTML and CSS.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import page_home as PH       # pure helpers: numbers (de_eur, de_num), tone

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
NAME = "New rules test 🧪"
WORDS = {"X": "Sell bot, replayed", "K": "Old fixed rule"}


def num(v):
    return M.num(v)


def when(R, ms, fmt="%b %d %H:%M"):
    try:
        return R.local(ms).strftime(fmt)
    except Exception:
        return "–"


def big_doc(D):
    doc = M.load_json(os.path.join((D or {}).get("dir") or "", "db", "memebot", "filtersearch.json"), {}) or {}
    nr = doc.get("newrules") if isinstance(doc, dict) else None
    return nr if isinstance(nr, dict) and isinstance(nr.get("accts"), list) else None


def data(D):
    import newrules as NR
    S = NR.pick_test((D or {}).get("dir") or "", (D or {}).get("now"))
    B = big_doc(D)
    rules = [a for a in S["accts"] if a["id"] not in ("K", "X")] + S["skips"] + ((B or {}).get("accts") or [])
    started = [a for a in rules if a.get("n")]
    return S, B, rules, sum(1 for a in started if (num(a.get("eur")) or 0) > 0.004), len(NR.SELL) + len(NR.SKIP) + len(NR.BUY)


def head_line(D, R):
    import newrules as NR
    S, B, rules, up, total = data(D)
    if (D or {}).get("now", 0) < NR.FROM:
        return "starts %s · %d rules frozen on Nov 4" % (when(R, NR.FROM), total)
    if not S["n"] and not any(a.get("n") for a in rules):
        return "running since %s · first results about 12 h after the next Pick buy" % when(R, NR.FROM)
    return "%d of %d in profit · %d Pick buys compared · judged %s" % (up, total, S["n"], NR.JUDGE_AT)


def eur_cell(v, n=1):
    if not n or num(v) is None:
        return '<td class="n">–</td>'
    return '<td class="n %s">%s</td>' % (PH.tone(v), E(PH.de_eur(v, True)))


def row(label, text, a, extra="", cls=""):
    won = "%d/%d" % (a["won"], a["n"]) if a.get("n") else "–"
    return '<tr class="%s"><td><b>%s</b><small>%s</small></td>%s%s<td class="n">%s</td>%s</tr>' % (
        cls, E(label), E(text), eur_cell(a.get("eur"), a.get("n")), eur_cell(a.get("per"), a.get("n")), E(won), extra)


def section(D, R):
    import newrules as NR
    S, B, rules, up, total = data(D)
    real = S["real"]
    head = '<thead><tr><th>Rule</th><th>Result</th><th>per buy</th><th>in profit</th><th>vs real</th></tr></thead>'
    t1 = [row(real["name"], real["text"], real, '<td class="n">–</td>', "real")]
    for a in S["accts"]:
        label = "%s · %s" % (a["id"], WORDS.get(a["id"], a["name"]))
        t1.append(row(label, a["text"], a, eur_cell(a.get("vsReal"), a.get("n")), "ctl" if a["id"] in ("K", "X") else ""))
    t2 = []
    for a in S["skips"]:
        kept = "%d of %d buys" % (a["n"], a["of"]) if a.get("of") else "no buy yet"
        t2.append(row("%s · %s" % (a["id"], a["name"]), "%s · %s" % (a["text"], kept), a, eur_cell(a.get("real"), a.get("n"))))
    t3 = []
    for a in (B or {}).get("accts") or []:
        t3.append(row("%s · %s" % (a["id"], a["name"]), a["text"], a, eur_cell(a.get("eurWob"), a.get("n"))))
    if not t3:
        t3.append('<tr><td colspan="5" class="m">%s</td></tr>' % E("Measured each morning after 07:50 (the nightly filter search); the first numbers come on the morning after the first day."))
    note = ["Compared: %d Pick buys whose 12 hours are over" % S["n"]]
    if S["open"]:
        note.append("%d still open" % S["open"])
    if S["out"]:
        note.append("%d without minute candles" % S["out"])
    note.append("since %s · judged once on %s" % (when(R, NR.FROM), NR.JUDGE_AT))
    lead = ('<p class="nr-lead">On Nov 4 the bots\' own data of Oct 22 to Nov 4 was searched: about 48,000 rules. The 9 best were frozen '
            'and run here with fake money on new days, from %s on. On the days they were found on they all made money, and that alone '
            'means little: almost every rule found that way turns out to be luck. Only what still earns here counts. The Pick account, '
            'the Sell bot and the Radar account 🚀 are not changed by this.</p>') % E(when(R, NR.FROM))
    inner = ('<div class="nr">%s'
             '<p class="nr-h">Other sell rules on the Pick account\'s buys</p><div class="nr-scroll"><table class="nr-t">%s<tbody>%s</tbody></table></div>'
             '<p class="nr-h">Pick buys to leave out (the rest sold by the Sell bot, replayed)</p><div class="nr-scroll"><table class="nr-t">'
             '<thead><tr><th>Rule</th><th>Result</th><th>per buy</th><th>in profit</th><th>real</th></tr></thead><tbody>%s</tbody></table></div>'
             '<p class="nr-h">Buy rules on every scanned coin (sold after about 2 h)</p><div class="nr-scroll"><table class="nr-t">'
             '<thead><tr><th>Rule</th><th>Result</th><th>per buy</th><th>in profit</th><th>w/o best</th></tr></thead><tbody>%s</tbody></table></div>'
             '<p class="nr-m">€ after fees, 50 € a buy. "vs real" is the difference to the real Pick account on the same buys; "real" is what the '
             'Pick account really got on the kept buys; "w/o best" is the result without the rule\'s best coin (one lucky coin must not carry a rule). '
             'A rule passes on %s only with at least 40 trades, a profit after costs that is clearly above zero (also without its best trade), '
             'and for the Pick rules more than the real account on the same buys.</p><p class="nr-m">%s</p></div>') % (
        lead, head, "".join(t1), "".join(t2), "".join(t3), E(NR.JUDGE_AT), E(" · ".join(note)))
    return ('<details class="fold nr-fold" id="new-rules"><summary><span class="t">%s</span><span class="sum">%s</span></summary>%s</details>'
            '<style>%s</style>') % (E(NAME), E(head_line(D, R)), inner, CSS)


def box(D, R):
    """The Start tab's box: how many of the 9 are in profit, since when, the judgement day, and a tap that opens the fold."""
    import newrules as NR
    S, B, rules, up, total = data(D)
    now = (D or {}).get("now") or 0
    if now < NR.FROM:
        bal, line = '<b class="lv-ab">–</b>', "%d rules frozen on Nov 4 · start %s · judged %s" % (total, E(when(R, NR.FROM)), E(NR.JUDGE_AT))
    elif not any(a.get("n") for a in rules):
        bal, line = '<b class="lv-ab">–</b>', "running since %s · first results about 12 h after the next Pick buy · judged %s" % (
            E(when(R, NR.FROM, "%b %d %H:%M")), E(NR.JUDGE_AT))
    else:
        bal = '<b class="lv-ab">%d of %d</b>' % (up, total)
        line = "rules in profit · %d Pick buys compared · since %s · judged %s" % (S["n"], E(when(R, NR.FROM, "%b %d")), E(NR.JUDGE_AT))
    go = '<label class="lv-nrgo" for="tab-pick" data-go="pick" data-open="new-rules">See the %d rules ›</label>' % total
    role = "Nine rules found on the bots' own data, tested with fake money on new days. Most such rules turn out to be luck."
    return bal, line, role, go


CSS = r"""
/* the New rules test (page_newrules.py) */
.nr { display:grid; gap:10px; min-width:0 }
.nr-lead { margin:0; color:var(--fg2); font-size:var(--fs-s); max-width:70ch }
.nr-h { margin:6px 0 0; font-weight:600; font-size:var(--fs-s) }
.nr-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100% }
.nr-t { width:100%; border-collapse:collapse; font-size:var(--fs-s) }
.nr-t th { text-align:left; font-weight:500; color:var(--muted); font-size:11px; padding:4px 6px; border-bottom:1px solid var(--line) }
.nr-t td { padding:7px 6px; border-bottom:1px solid var(--line2); vertical-align:top }
.nr-t td b { font-weight:600 } .nr-t td small { display:block; font-size:11px; color:var(--muted) }
.nr-t td.n, .nr-t th:not(:first-child) { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
.nr-t td.m { color:var(--muted); font-size:11px }
.nr-t .good { color:var(--good) } .nr-t .bad { color:var(--bad) }
.nr-t tr.real td { background:color-mix(in srgb,var(--fg) 4%,transparent) }
.nr-t tr.ctl td:first-child b { color:var(--fg2) }
.nr-m { margin:0; font-size:11px; color:var(--muted) }
.lv-nrgo { display:inline-flex; align-items:center; min-height:44px; color:var(--accent); font-weight:500; cursor:pointer; font-size:var(--fs-s) }
"""
