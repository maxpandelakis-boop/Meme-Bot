"""The nightly filter search on the page (fake money only, nothing is ever bought for real): page_account.section shows it under the
exit what-if block.

section(D) -> HTML, a compact block "Filter search (nightly)":
  - one sentence first: the bot keeps its gates; a rule here is a candidate, switched on only by the user
  - the verdict: the frozen rule that beat the gates on coins it never saw (filter_search.py's "better"), or "No rule beats the gates
    on unseen coins yet" with the best one under test and how far it is from a verdict
  - tonight's rule: the one the search froze last night, with its two training halves
  - the mistakes: the top picks of the last days that lost, and how many of them the leading rule would have let through or blocked
  - the big one-off study (research/SEARCH-2026-10-21.md) in one line per data set, when the doc carries it
  - an ⓘ fold with the method
D: report.py's page data; only D["dir"] is read (db/memebot/filtersearch.json, written by filter_search.py on the branch
"filtersearch" and copied into db/memebot by the scan job; this module writes nothing). Every value goes through a number check or
html.escape. Static HTML and CSS, no script.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import page_account as PA

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
DOC = ("db", "memebot", "filtersearch.json")


def num(v):
    return M.num(v)


def per(v):
    return PA.eur(v, True)


def load(d):
    fn = os.path.join(d or "", *DOC)
    if not os.path.exists(fn):
        return None
    doc = M.load_json(fn, "bad")
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
        return {"err": "not a readable doc"}
    return doc


def st_line(s, what="coins"):
    """'312 coins over 5 days · −1.20 € per 20 · 3x 1.3% · to zero 4.0% · 95% range −2.10 € to −0.30 €'."""
    if not isinstance(s, dict) or not num(s.get("n")):
        return "no coins yet"
    bits = ["%d %s over %d day%s" % (int(s["n"]), what, int(num(s.get("days")) or 0), "" if int(num(s.get("days")) or 0) == 1 else "s"),
            "%s per 20" % per(num(s.get("avg"))), "3x %.1f%%" % (num(s.get("hit3")) or 0.0), "to zero %.1f%%" % (num(s.get("zero")) or 0.0)]
    if num(s.get("lo")) is not None and num(s.get("hi")) is not None:
        bits.append("range %s to %s" % (per(num(s["lo"])), per(num(s["hi"]))))
    return " · ".join(bits)


def verdict(doc):
    rules = doc.get("rules") if isinstance(doc.get("rules"), dict) else {}
    need = int(num(rules.get("minFwd")) or 100)
    lead = doc.get("leader") if isinstance(doc.get("leader"), dict) else None
    if lead:
        fwd, g = lead.get("fwd") or {}, lead.get("gates") or {}
        return ('<div class="fs-v good"><span class="k">A rule beat the gates on coins it never saw (not switched on: your decision)</span>'
                '<b>%s</b><small>this rule: %s</small><small>the gates on the same days: %s</small></div>') % (
            E(lead.get("text")), E(st_line(fwd)), E(st_line(g)))
    chs = [c for c in (doc.get("challengers") or []) if isinstance(c, dict)]
    best = chs[0] if chs else None
    if not best:
        return '<div class="fs-v"><b>No rule under test yet.</b><small>The first search freezes one tonight.</small></div>'
    fwd, g = best.get("fwd") or {}, best.get("gates") or {}
    state = ("still collecting: %d of %d unseen coins" % (int(num(fwd.get("n")) or 0), need)) if best.get("verdict") == "watch" else "tested: not better"
    return ('<div class="fs-v"><span class="k">No rule beats the gates on unseen coins yet</span><b>Best so far: %s</b>'
            '<small>%s · %s</small><small>the gates on the same days: %s</small></div>') % (
        E(best.get("text")), E(state), E(st_line(fwd)), E(st_line(g)))


def tonight(doc):
    t = doc.get("tonight") if isinstance(doc.get("tonight"), dict) else None
    if not t:
        return ""
    tr = t.get("train") or {}
    h = tr.get("halves") if isinstance(tr.get("halves"), list) and len(tr["halves"]) == 2 else None
    halves = (" · older half %s, newer half %s" % (per(num(h[0])), per(num(h[1])))) if h else ""
    return ('<p class="fs-s"><span class="k">Learned last night (frozen, tested from now on only on new coins):</span> %s<br><small>on the '
            'scans so far: %s%s</small></p>') % (E(t.get("text")), E(st_line(tr)), E(halves))


def mistakes(doc):
    m = doc.get("mistakes") if isinstance(doc.get("mistakes"), dict) else None
    if not m or not isinstance(m.get("picks"), dict) or not num(m["picks"].get("n")):
        return ""
    p = m["picks"]
    s = "Top picks of the last %d days: %s." % (int(num(m.get("days")) or 7), st_line(p, "picks"))
    if num(m.get("lost")) is not None:
        s += (" Of the %d that lost, the leading rule would have let %d through and blocked %d; of the %d that won it would have "
              "blocked %d.") % (int(m["lost"]), int(num(m.get("lostKept")) or 0), int(num(m.get("lostBlocked")) or 0), int(num(m.get("won")) or 0),
                                int(num(m.get("wonBlocked")) or 0))
    return '<p class="fs-s"><span class="k">Mistakes:</span> %s</p>' % E(s)


def study(doc):
    s = doc.get("study") if isinstance(doc.get("study"), dict) else None
    if not s or not isinstance(s.get("lines"), list):
        return ""
    items = "".join("<li>%s</li>" % E(x) for x in s["lines"][:6] if isinstance(x, str))
    return '<details class="fold-lite fs-st"><summary>%s</summary><ul>%s</ul></details>' % (E(s.get("title") or "The big search"), items)


def how(doc):
    d = doc["data"]
    return ("Every night the search reads every coin of every scan so far (%s rows, %s coins, %s scans) with what 20 became about "
            "2 hours later, after %g%% fees per buy and per sell, the price multiple capped at %gx. It tries %s rules (one or two numbers above "
            "or below a quartile, in %d age windows, the old new launches among them) and keeps the one that did best in both halves of the "
            "scans and lost no 3x coins against the gates. That rule is frozen with its numbers; from then on it is measured only on coins "
            "that came later, next to the gates on the same coins. It counts as better only with %d coins or more over %d days or more, "
            "above zero and above the gates per 20, a 3x share not below the gates', and the low end of its range above zero, the range "
            "widened for the number of rules under test at once (%s now). The leading rule's mistakes line uses the bot's top picks. Fake money; nothing "
            "here changes what the bot buys.") % (
        "{:,}".format(int(num(d.get("rows")) or 0)), "{:,}".format(int(num(d.get("coins")) or 0)), "{:,}".format(int(num(d.get("scans")) or 0)),
        100 * (num(doc.get("fee")) or 0.01), num(doc.get("cap")) or 11, "{:,}".format(int(num(doc.get("tried")) or 0)), int(num(doc.get("windows")) or 6),
        int(num((doc.get("rules") or {}).get("minFwd")) or 100), int(num((doc.get("rules") or {}).get("minDays")) or 3), int(num(doc.get("nLive")) or 0))


def section(D):
    doc = load((D or {}).get("dir") or "")
    when = ("searched %s %s" % (PA.mday(doc["t"]), PA.hhmm(doc["t"]))) if isinstance(doc, dict) and num(doc.get("t")) else ""
    head = ('<div class="fs-head"><h3>Filter search (nightly)</h3><span class="chip warn">fake money</span><span class="fs-cnt">%s</span></div>'
            '<p class="fs-keep">The bot keeps its gates and its sell rule. Each night a search learns from all scans so far, the day\'s '
            'picks included, freezes its best rule and tests every frozen rule only on coins it never saw. A rule here is a candidate; '
            'only you can switch one on.</p>') % E(when)
    wrap = lambda inner: '<div class="fs" data-pa="filtersearch">%s%s</div><style>%s</style>' % (head, inner, CSS)
    if doc is None:
        return wrap('<p class="fs-s">No search yet: it runs once a night.</p>')
    if doc.get("err"):
        return wrap('<p class="fs-s">The search result could not be read this time (%s).</p>' % E(doc["err"]))
    info = '<details class="pa-i"><summary>ⓘ how</summary><p>%s</p></details>' % E(how(doc))
    return wrap(verdict(doc) + tonight(doc) + mistakes(doc) + study(doc) + info)


CSS = r"""
/* the nightly filter search (page_search.py) */
.fs { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 4px; display:grid; gap:10px; min-width:0 }
.fs-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .fs-head h3 { margin:0 }
.fs-cnt { margin-left:auto; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.fs-keep { margin:0; font-size:var(--fs-s); color:var(--fg2); max-width:70ch; text-wrap:pretty }
.fs-v { border:1px solid var(--line); border-left:4px solid var(--warn-mark); border-radius:10px; padding:10px 14px 12px; display:grid; gap:3px; min-width:0 }
.fs-v.good { border-left-color:var(--good) } .fs-v .k, .fs-s .k { font-size:var(--fs-xs); color:var(--muted) }
.fs-v b { font-size:16px; font-weight:600; overflow-wrap:anywhere }
.fs-v small, .fs-s small { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.fs-s { margin:0; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere }
.fs-st ul { margin:6px 0 0; padding-left:18px; font-size:var(--fs-s); color:var(--fg2) }
@media (max-width:560px) { .fs { padding:12px 12px 2px } .fs-v { padding:10px 12px 12px } }
"""
