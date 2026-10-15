"""The exit what-if test on the page (hindsight, fake money only, nothing is ever bought for real): page_account.section shows it
under the radar account, before the activity feed.

section(D) -> HTML, a compact block "What if the exits were different (hindsight)":
  - one sentence first: the paper trader keeps its rule (-30% stop, 11x, 6 h); this is hindsight on its past trades
  - per group (new launches, top picks, and the radar account once it has priced trades): the current rule replayed, per trade and
    per half (the figure every rule below is measured against: the same prices and the same method on both sides), with what the
    paper account really made with the same trades in its small line; up to three rules that did better per trade in both halves of
    the trades and overall (with the halves, the difference to the current rule and its 95% range, and the difference with the stop
    first wherever the stored prices cannot tell the order), or "No rule beat the current one in both halves." / "Too few trades
    yet"; the no-stop row under its own heading (for comparison, not one of the rules that did better; when it is one of them it is
    listed there only); and the sample sizes
  - an ⓘ fold with the method, the sources and their counts, the calibration gap and the fill model
D: report.py's page data; only D["dir"] is read (db/memebot/exitgrid.json, written by exit_grid.py in the peaks job after each scan;
this module writes nothing). Every value from the doc goes through a number check or html.escape; no coin name is shown. Static HTML
and CSS, no script. On a phone (560 px or less) the groups stack.
Wording: hindsight only, nothing here names a coin or says what to do; the paper trader's rule is not changed by this block.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import exit_grid as EG    # read only: the grid of rules it replays (STOPS x TARGETS), for the count the page names
import memebot as M
import page_account as PA

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = PA.MINUS
DOC = ("db", "memebot", "exitgrid.json")
GROUPS = (("young", "New launches"), ("hold", "Top picks"), ("radar", "Radar account"))
SHOW_N = 3
WHY_WORDS = {"stop": "stop sales", "tp": "take-profit sales", "time": "6-hour sales", "rug": "dead pools"}
OUT_WORDS = {"peak doc est": "estimated", "peak doc unit": "price unit mismatch", "peak doc waiting": "not priced yet",
             "no usable peak doc": "no 6-hour price record", "path ends before 6 h": "candles end early", "no entry price": "no entry price",
             "not priced": "not priced", "unreadable": "unreadable", "estimated": "estimated"}


def num(v):
    return M.num(v)


def pct_word(stop):
    """-0.30 -> "−30%"."""
    return "%s%d%%" % (MINUS, round(100 * stop))


def rule_name(stop, target):
    """The rule in a few words: "−20% stop, 2x target", "no stop, 11x target", "−50% stop, no target"."""
    s, t = num(stop), num(target)
    return "%s, %s" % ("no stop" if s is None else pct_word(s) + " stop", "no target" if t is None else ("%gx target" % t))


def cur_name():
    """The rule that really runs, as the task names it: "−30% stop, 11x, 6 h"."""
    return "%s stop, %gx, %g\u00a0h" % (pct_word(M.HOLD_STOP), 1.0 + M.HOLD_TP, M.HOLD_MAX_H)


def per(v):
    """Euros per trade with a sign: −0.71 €, +0.35 €."""
    return PA.eur(v, True)


def load(d):
    """The doc, or None when there is none yet; {"err": ...} when it cannot be read."""
    fn = os.path.join(d or "", *DOC)
    if not os.path.exists(fn):
        return None
    doc = M.load_json(fn, "bad")
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), dict):
        return {"err": "not a readable doc"}
    return doc


def _row(r, cls):
    """One rule: its name, its result per trade, and one small line (the halves, the difference and its 95% range, and the difference
    with the stop first where the order is unclear when that order changed any trade of the rule)."""
    pt, old, new = num(r.get("pt")), num(r.get("old")), num(r.get("new"))
    bits = []
    if old is not None and new is not None:
        bits.append("older half %s, newer half %s" % (per(old), per(new)))
    diff = num(r.get("diff"))
    if diff is not None:
        ci = r.get("ci") if isinstance(r.get("ci"), list) and len(r["ci"]) == 2 else None
        rng = (" (95%% range %s to %s)" % (per(num(ci[0])), per(num(ci[1])))) if ci and num(ci[0]) is not None and num(ci[1]) is not None else ""
        bits.append("%s against the current rule replayed%s" % (per(diff), rng))
    sf = num(r.get("sfDiff"))
    if sf is not None and (num(r.get("ord")) or 0) > 0:
        bits.append("%s with the stop first where the order is unclear" % per(sf))
    return ('<li class="xg-r %s"><span class="n">%s</span><b class="%s">%s</b><small>%s</small></li>') % (
        cls, E(rule_name(r.get("stop"), r.get("target"))), PA.tone(pt), E(per(pt) + " per trade"), E(" · ".join(bits)))


def group(key, title, blk, min_half):
    """One group's card, or "" for the radar account before it has priced trades."""
    n = int(num(blk.get("n")) or 0)
    n_all = int(num(blk.get("all")) or 0)
    if key == "radar" and n == 0:
        return ""
    n_old, n_new = int(num(blk.get("nOld")) or 0), int(num(blk.get("nNew")) or 0)
    size = "%d of %d trades replayed" % (n, n_all) if n_all > n else "%d trades replayed" % n
    if n:
        size += " · %d older, %d newer" % (n_old, n_new)
    head = '<div class="xg-t"><b>%s</b><span>%s</span></div>' % (E(title), E(size))
    if not n:
        return '<section class="xg-g" data-xg="%s">%s<p class="xg-none">No closed trade with stored prices yet.</p></section>' % (E(key), head)
    cur = blk.get("cur") if isinstance(blk.get("cur"), dict) else {}
    act = blk.get("actual") if isinstance(blk.get("actual"), dict) else {}
    a_pt, r_pt = num(act.get("pt")), num(cur.get("pt"))
    # the headline is the replay: the rules below are measured against it (same prices, same method); what the paper account really
    # made is the small line, so the two kinds of number never stand side by side as if they compared
    halves = ("older half %s, newer half %s · " % (per(num(cur.get("old"))), per(num(cur.get("new"))))
              if num(cur.get("old")) is not None and num(cur.get("new")) is not None else "")
    cur_html = ('<div class="xg-cur"><span class="k">Current rule (%s), replayed</span><b class="%s">%s</b><small>%s</small></div>') % (
        E(cur_name()), PA.tone(r_pt), E(per(r_pt) + " per trade"),
        E("%swhat the paper account really made with these trades: %s per trade" % (halves, per(a_pt))))
    verdict = blk.get("verdict")
    best = [r for r in (blk.get("best") or []) if isinstance(r, dict)][:SHOW_N]
    if verdict == "beat" and best:
        mid = ('<p class="xg-sub">Did better per trade in both halves and overall:</p><ol class="xg-best">%s</ol>'
               % "".join(_row(r, "b") for r in best))
    elif verdict == "few":
        mid = '<p class="xg-none">Too few trades yet: %d replayed, %d in each half needed before a rule can count as better.</p>' % (n, int(num(min_half) or 0))
    else:
        mid = '<p class="xg-none">No rule beat the current one in both halves.</p>'
    ns = blk.get("noStop") if isinstance(blk.get("noStop"), dict) else None
    # the no-stop row has its own heading: right under "Did better ..." it would read as one more rule that did better; when it is one
    # of them it is listed there, once
    if ns and verdict == "beat" and any(num(r.get("stop")) is None and num(r.get("target")) == num(ns.get("target")) for r in best):
        ns = None
    tail = ('<p class="xg-sub">For comparison, without a stop (the same %s target and %g\u00a0h):</p><ol class="xg-best xg-ns">%s</ol>'
            % (E("%gx" % (num(ns.get("target")) or 1.0 + M.HOLD_TP)), M.HOLD_MAX_H, _row(ns, "ns"))) if ns else ""
    return '<section class="xg-g" data-xg="%s">%s%s%s%s</section>' % (E(key), head, cur_html, mid, tail)


def _sources(doc):
    """How many trades each kind of stored price covers, and why the others stayed out, in words (the radar account's trades, replayed
    on their own exit, and its left-out ones named as such)."""
    m1 = m15 = peak_only = radar = n = 0
    out = {}
    for key, _ in GROUPS:
        blk = doc["groups"].get(key) if isinstance(doc["groups"].get(key), dict) else {}
        for k, v in (blk.get("src") or {}).items() if isinstance(blk.get("src"), dict) else ():
            v = int(num(v) or 0)
            parts = str(k).split("+")
            n += v
            m1 += v if "m1" in parts else 0
            m15 += v if "m15" in parts else 0
            peak_only += v if parts == ["peak"] else 0
            radar += v if parts == ["radar"] else 0
        for k, v in (blk.get("out") or {}).items() if isinstance(blk.get("out"), dict) else ():
            w = (key == "radar", OUT_WORDS.get(str(k), str(k)[:40]))
            out[w] = out.get(w, 0) + int(num(v) or 0)
    word = lambda k, v: ("%d radar account trade%s %s" % (v, "" if v == 1 else "s", k[1])) if k[0] else "%d %s" % (v, k[1])
    left = ", ".join(word(k, v) for k, v in sorted(out.items(), key=lambda kv: (-kv[1], kv[0])) if v)
    return ("%d trades replayed: %d with 1-minute candles of the same coin for the first hour or two, %d with 15-minute candles, %d on the "
            "6-hour price record alone%s%s.") % (n, m1, m15, peak_only, (", %d radar account trades on their own exit" % radar) if radar else "",
                                                ("; left out: " + left) if left else "")


def how(doc):
    """The ⓘ text: what was replayed, how, how well the replay matches what really happened, and the honesty rules."""
    fill = doc.get("fill") if isinstance(doc.get("fill"), dict) else {}
    young = doc["groups"].get("young") if isinstance(doc["groups"].get("young"), dict) else {}
    cal = young.get("calib") if isinstance(young.get("calib"), dict) else {}
    calib = ""
    if num(cal.get("replay")) is not None and num(cal.get("actual")) is not None:
        by = cal.get("byWhy") if isinstance(cal.get("byWhy"), dict) else {}
        diffs = [(abs((num(b.get("replay")) or 0.0) - (num(b.get("actual")) or 0.0)), k) for k, b in by.items() if isinstance(b, dict) and k in WHY_WORDS]
        top = max(diffs) if diffs else None
        most = ("; most of it in the %s" % WHY_WORDS[top[1]]) if top and top[0] >= 0.01 else ""
        calib = (" Check: the current rule replayed on the new launches gives %s per trade against %s it really made (a gap of %s%s)."
                 % (per(num(cal.get("replay"))), per(num(cal.get("actual"))), per(num(cal.get("gap"))), most))
    f = lambda k: ("%.0f%%" % (100 * num(fill.get(k)))) if num(fill.get(k)) is not None else "?"
    return ("Hindsight on the paper trades since the restart, replayed rule by rule on stored prices: the 6-hour price record of each "
            "trade (its best, lowest and last close) and, where they were kept, the 1-minute and 15-minute candles of the same coin. A rule "
            "sells at the first close at or below its stop (at the stop, or lower when the price fell through it), at the first close at or "
            "above its target (at the target), else at 6 hours; closes only, never wicks; a pool that died is a total loss; paper fees on both "
            "sides. Where the stored prices show a fall only roughly, the sale price is estimated from the paper trader's own stop sales (%s, "
            "%s and %s of the way from the lowest price to the stop, for a pool that lived, one that died and inside a 15-minute candle). "
            "Where the stored prices cannot tell whether the stop or the target came first, the replay takes the target. "
            "A rule counts as better only when it did better per trade in the older half and in the newer half of the trades and overall, "
            "also with every such sale at the stop and at the lowest price, also with the stop first wherever the order is unclear, and "
            "with at least %d trades in each half. The 95%% range comes from resampling the trades. %s%s Nobody knows the top or the "
            "bottom in advance. Fake money, nothing is bought for real.") % (
        f("alive"), f("dead"), f("candle"), int(num(doc.get("minHalf")) or 0), _sources(doc), calib)


def section(D):
    """The whole block (see the module doc). Never raises on a bad doc: a notice instead."""
    doc = load((D or {}).get("dir") or "")
    keep = ("The paper trader keeps its rule (%s). This is hindsight on its past trades: other stops and targets replayed on the "
            "same trades. %d rules are tried, and among that many one can do better by luck, so a rule here is a lead to watch, "
            "not proof." % (cur_name(), len(EG.STOPS) * len(EG.TARGETS)))
    when = ""
    if isinstance(doc, dict) and num(doc.get("t")):
        when = "replayed %s %s" % (PA.mday(doc["t"]), PA.hhmm(doc["t"]))
    head = ('<div class="xg-head"><h3>What if the exits were different</h3><span class="chip warn">hindsight</span><span class="xg-cnt">%s</span></div>'
            '<p class="xg-keep">%s</p>') % (E(when), E(keep))
    wrap = lambda inner: '<div class="xg" data-pa="exitgrid">%s%s</div><style>%s</style>' % (head, inner, CSS)
    if doc is None:
        return wrap('<p class="xg-none">No replay yet: it runs in the job after each scan.</p>')
    if doc.get("err"):
        return wrap('<p class="xg-none">The replay could not be read this time (%s).</p>' % E(doc["err"]))
    cards = "".join(group(k, t, doc["groups"][k], doc.get("minHalf")) for k, t in GROUPS if isinstance(doc["groups"].get(k), dict))
    if not cards:
        return wrap('<p class="xg-none">No closed trade with stored prices yet.</p>')
    info = '<details class="pa-i"><summary>ⓘ how</summary><p>%s</p></details>' % E(how(doc))
    return wrap('<div class="xg-gs">%s</div>%s' % (cards, info))


CSS = r"""
/* the exit what-if test (page_exits.py): one card per group, the current rule, the rules that did better in both halves, no stop */
.xg { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 4px; display:grid; gap:10px; min-width:0 }
.xg-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .xg-head h3 { margin:0 }
.xg-cnt { margin-left:auto; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.xg-keep { margin:0; font-size:var(--fs-s); color:var(--fg2); max-width:70ch; text-wrap:pretty }
.xg-gs { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px }
.xg-g { border:1px solid var(--line); border-left:4px solid var(--warn-mark); border-radius:10px; padding:10px 14px 12px; display:grid; gap:8px; min-width:0; align-content:start }
.xg-t { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:2px 10px } .xg-t b { font-weight:600; font-size:15px }
.xg-t span { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.xg-cur { display:grid; gap:1px } .xg-cur .k { font-size:var(--fs-xs); color:var(--muted) }
.xg-cur b { font-size:22px; line-height:1.15; font-weight:600; font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.xg-cur small, .xg-r small { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.xg .good { color:var(--good) } .xg .bad { color:var(--bad) }
.xg-sub { margin:0; font-size:var(--fs-xs); color:var(--fg2) }
.xg-best { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.xg-r { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:0 10px; padding-top:6px; border-top:1px solid var(--line2); min-width:0 }
.xg-r .n { font-size:var(--fs-s); font-weight:500; min-width:0; overflow-wrap:anywhere } .xg-r b { font-variant-numeric:tabular-nums; white-space:nowrap; font-size:var(--fs-s) }
.xg-r small { grid-column:1 / -1 } .xg-ns .xg-r .n { color:var(--fg2) }
.xg-none { margin:0; font-size:var(--fs-s); color:var(--muted) }
@media (max-width:560px) {
  .xg { padding:12px 12px 2px } .xg-gs { grid-template-columns:minmax(0,1fr); gap:10px } .xg-g { padding:10px 12px 12px } .xg-cur b { font-size:20px }
  .xg-r { grid-template-columns:minmax(0,1fr) } .xg-r b { white-space:normal }
}
"""
