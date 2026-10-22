"""The winner/loser study on the page (fake money only, display only: it changes no pick, no gate and no sell rule).
report.py shows it in the Pick tab's Details under the filter search.

section(path=None) -> HTML, a compact block "Winners vs losers (study)":
  - the verdict first: the score learned from all the numbers beat the gates on unseen days but still lost, so nothing changed
  - "big move either way": the numbers that tell a coin will move a lot (up OR down), the reason danger signals look like 3x signals
  - "which way": the few numbers that separate winners from losers among similar coins, and how weak they are
  - all signals of the bot's own scans together, and the three variants side by side (A few losers, B rockets, C expected profit)
  - the social probe (pump.fun replies, Reddit before the entry), when the file carries it
  - an ⓘ fold with the method
The file is winlose.json next to this module (written once by research/winlose/export.py); every value goes through a number check
or html.escape. Static HTML and CSS, no script.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
PATH = os.path.join(HERE, "winlose.json")


def num(v):
    return M.num(v)


def per(v):
    v = num(v)
    return "–" if v is None else ("%+.2f €" % (0.0 if abs(v) < 0.005 else v)).replace("-", "−")


def load(path=None):
    try:
        doc = json.load(open(path or PATH))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("score"), dict) else None


def st(s):
    if not isinstance(s, dict) or not num(s.get("coins")):
        return "no coins"
    tail = ("10x %.1f%% · to zero %.1f%%" % (num(s.get("rocket10x")) or 0, num(s.get("zero")) or 0)) if "rocket10x" in s else (
        "fell 80%% %.1f%%" % (num(s.get("lose80")) or 0))
    return "%d coins · %s per 20 · %.1f of 10 in profit · 3x %.1f%% · %s" % (
        int(num(s["coins"])), per(s.get("avg")), num(s.get("in_profit_of10")) or 0, num(s.get("hit3")) or 0, tail)


def strength(auc):
    a = num(auc)
    if a is None:
        return ""
    d = abs(a - 0.5)
    return "strong" if d >= 0.15 else "clear" if d >= 0.08 else "weak"


def items(rows, up_txt, down_txt):
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        tag = "holds on unseen days" if r.get("holds") else "did not hold on unseen days"
        out.append("<li><b>%s</b>: %s · %s (%s, AUC %.2f)</li>" % (
            E(r.get("label")), E(up_txt if r.get("up") else down_txt), E(tag), E(strength(r.get("hold"))), num(r.get("hold")) or 0.5))
    return "<ul>%s</ul>" % "".join(out) if out else ""


def section(path=None):
    doc = load(path)
    head = ('<div class="wl-head"><h3>Winners vs losers (study)</h3><span class="chip warn">fake money</span>'
            '<span class="wl-cnt">%s</span></div>') % E(("made %s" % doc.get("made")) if doc else "")
    wrap = lambda inner: '<div class="wl" data-pa="winlose">%s%s</div><style>%s</style>' % (head, inner, CSS)
    if doc is None:
        return wrap('<p class="wl-s">No study file.</p>')
    sc = doc["score"]
    h = doc.get("holds") if isinstance(doc.get("holds"), dict) else {}
    verdict = ('<div class="wl-v"><span class="k">Verdict: nothing switched on</span><b>A score from all %d numbers beats the gates on '
               'unseen days, but still loses money.</b><small>unseen days: score %s</small><small>unseen days: gates %s</small>'
               '<small>earlier days (walk-forward): score %s · gates %s</small></div>') % (
        int(num(doc.get("numbers")) or 0), E(st(sc.get("hold"))), E(st(sc.get("hold_gates"))), E(per((sc.get("dev") or {}).get("avg"))),
        E(per((sc.get("dev_gates") or {}).get("avg"))))
    move = ('<div class="wl-st"><p class="wl-s"><span class="k">Big move, either way (%d of %d numbers hold)</span> These tell that a '
            'coin will move a lot, not which way. That is why danger signals keep looking like 3x signals.</p>%s</div>') % (
        int(num(h.get("move_vs_calm")) or 0), int(num(doc.get("numbers")) or 0), items(doc.get("move"), "higher before big moves", "lower before big moves"))
    way = ('<div class="wl-st"><p class="wl-s"><span class="k">Which way: winners against losers of the same age and size (%d of %d hold)</span> '
           'Only these separate the 3x coins from the ones that fell 80%%, and only a little.</p>%s</div>') % (
        int(num(h.get("win_vs_lose")) or 0), int(num(doc.get("numbers")) or 0), items(doc.get("direction"), "higher in winners", "lower in winners"))
    comb = ""
    cb = doc.get("combined")
    if isinstance(cb, dict) and isinstance(cb.get("hold"), dict):
        hd, hg = cb["hold"], cb.get("hold_gates") or {}
        comb = ('<p class="wl-s"><span class="k">All %d numbers of the bot\'s own scans together (dev/holder, RugCheck, social, smart wallets)</span> '
                'unseen days: %s per 20 on %d coins, %.0f%% in profit, 3x %.2f%% · gates %s. Fails: it picks quiet coins that lose only the fees.</p>') % (
            int(num(cb.get("numbers")) or 0), E(per(hd.get("avg"))), int(num(hd.get("n")) or 0), num(hd.get("win")) or 0, num(hd.get("hit3")) or 0,
            E(per(hg.get("avg"))))
    var = ""
    vs = doc.get("variants")
    if isinstance(vs, dict):
        cards = []
        for key in ("A", "B", "C"):
            v = vs.get(key)
            if not isinstance(v, dict):
                continue
            sim = v.get("sim") if isinstance(v.get("sim"), dict) else None
            simtxt = (" · %s%% of 10,000 simulated runs in profit" % E(num(sim.get("pProfit")))) if sim else ""
            cards.append('<div class="wl-c"><span class="k">%s · %s (top %s%%)</span><small>earlier days: %s</small><small>unseen days: %s%s</small>'
                         '<small>%s</small></div>' % (E(key), E(v.get("name")), E("%g" % (100 * (num(v.get("cut")) or 0))), E(st(v.get("dev"))),
                                                       E(st(v.get("hold"))), E(simtxt), E(v.get("verdict"))))
        var = ('<div class="wl-st"><p class="wl-s"><span class="k">Few losers or rockets? (every coin every 15 minutes, sell rule A, not clipped)</span> '
               'Neither reaches both goals: the more picks end in profit, the less the bot makes, because the safe-looking coins '
               'that still fail go to zero and there are no rockets among them. Only the rocket hunter made money, on very few coins.</p>'
               '<div class="wl-cards">%s</div></div>') % "".join(cards)
    soc = ""
    s = doc.get("social")
    if isinstance(s, dict) and s.get("text"):
        soc = '<p class="wl-s"><span class="k">Social (pump.fun comments, Reddit)</span> %s</p>' % E(s["text"])
    how = ("%s coins, %s hourly rows, %s. Winner: reached 3x within 6 h; loser: fell to 20%% or less without 3x. Numbers from "
           "one-minute charts (returns, RSI, volume spikes, buy pressure, candles, support/resistance, trend), the screener, the "
           "wallets that bought before (with their earlier results), BTC/SOL and the meme market, and the 50 most similar earlier charts. "
           "Compared like with like (age x market cap), Holm-corrected; the score is gradient boosting trained walk-forward and "
           "checked once on unseen days. Sell rule A (-30%%/11x/6 h), fees as the paper account. research/winlose/.") % (
        "{:,}".format(int(num(doc.get("coins")) or 0)), "{:,}".format(int(num(doc.get("rows")) or 0)), E(doc.get("period")))
    info = '<details class="pa-i"><summary>ⓘ how</summary><p>%s</p></details>' % E(how)
    return wrap(verdict + move + way + comb + var + soc + info)


CSS = r"""
/* the winner/loser study (page_winlose.py) */
.wl { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 4px; display:grid; gap:10px; min-width:0 }
.wl-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .wl-head h3 { margin:0 }
.wl-cnt { margin-left:auto; font-size:var(--fs-xs); color:var(--muted) }
.wl-v { border:1px solid var(--line); border-left:4px solid var(--warn-mark); border-radius:10px; padding:10px 14px 12px; display:grid; gap:3px; min-width:0 }
.wl-v .k, .wl-s .k { font-size:var(--fs-xs); color:var(--muted); display:block }
.wl-v b { font-size:16px; font-weight:600; overflow-wrap:anywhere }
.wl-v small { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.wl-s { margin:0; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere; max-width:70ch }
.wl-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:8px; margin-top:6px }
.wl-c { border:1px solid var(--line); border-radius:10px; padding:8px 12px; display:grid; gap:2px; min-width:0 }
.wl-c .k { font-size:var(--fs-xs); color:var(--muted) } .wl-c small { font-size:var(--fs-xs); color:var(--fg2); overflow-wrap:anywhere }
.wl-st ul { margin:6px 0 0; padding-left:18px; font-size:var(--fs-s); color:var(--fg2) }
@media (max-width:560px) { .wl { padding:12px 12px 2px } .wl-v { padding:10px 12px 12px } }
"""
