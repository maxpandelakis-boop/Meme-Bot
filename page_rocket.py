"""The rocket hunter on the page (fake money only, nothing is ever bought for real): report.py shows it at the top of the Radar tab.

section(D) -> HTML, a compact block "Rocket hunter (paper)":
  - the two paper accounts side by side: Pick (the scan's paper account, its sell rule unchanged) and Rocket hunter (its own
    account: rocket_watch.py buys a coin once when its score reaches the cut, rule A sells it), each with its balance, how many of
    10 closed trades ended in profit, and its 3x/10x hits
  - the rocket hunter's open positions and the best scores of its last round
  - one honest line: the model was positive on the earlier days only on few coins; this account is its live test
D: report.py's page data; reads D["dir"]/db/memebot/rocket.json (rocket_watch.py writes it on the branch rocket-data, the scan job
copies it) and, for the Pick side, page_account's numbers. Every value goes through a number check or html.escape. No script.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
DOC = ("db", "memebot", "rocket.json")


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


def pick_side(D):
    """The scan's paper account: its balance (the last point of the balance line) and its closed trades."""
    try:
        import page_account as PA
        A = PA._acct(D)
    except Exception:
        return None
    rows = [r for r in (A or {}).get("rows") or [] if isinstance(r, dict)]
    closed = [r for r in rows if not r.get("open") and num(r.get("pnl")) is not None]
    pts = [c["paper"].get("pnl") for c in (D or {}).get("curve") or [] if isinstance(c, dict) and isinstance(c.get("paper"), dict)]
    bal = num(pts[-1]) if pts else (sum(num(r["pnl"]) for r in closed) if closed else None)
    win = round(10 * sum(1 for r in closed if num(r["pnl"]) > 0) / len(closed), 1) if closed else None
    return {"bal": bal, "trades": len(closed), "open": sum(1 for r in rows if r.get("open")), "win": win}


def card(title, sub, bal, trades, open_, win, hits):
    w = "–" if win is None else "%.1f of 10" % win
    return ('<div class="rk-c"><span class="k">%s</span><b class="%s">%s</b><small>%s</small>'
            '<small>%d closed · %d open · in profit %s%s</small></div>') % (
        E(title), "up" if (num(bal) or 0) > 0 else "dn" if (num(bal) or 0) < 0 else "", E(eur(bal)), E(sub), trades, open_, E(w), E(hits))


def section(D):
    doc = load((D or {}).get("dir"))
    head = '<div class="rk-head"><h3>Pick and rocket hunter (paper)</h3><span class="chip warn">fake money</span></div>'
    wrap = lambda inner: '<div class="rk" data-pa="rocket">%s%s</div><style>%s</style>' % (head, inner, CSS)
    ps = pick_side(D)
    pick = card("Pick: the safer one", "the scan's paper account, sell rule unchanged", ps["bal"], ps["trades"], ps["open"], ps["win"], "") if ps else ""
    if doc is None:
        return wrap('<div class="rk-cards">%s</div><p class="rk-s">The rocket hunter has not run yet: it checks the radar\'s coins every '
                    '15 minutes and buys on paper only when a coin\'s rocket score reaches its cut.</p>' % pick)
    sm = (doc.get("book") or {}).get("summary") or {}
    hits = " · 3x %d · 10x %d" % (int(num(sm.get("x3")) or 0), int(num(sm.get("x10")) or 0))
    bal = (num(sm.get("eur")) or 0.0) + (num(sm.get("openEur")) or 0.0)
    rocket = card("Rocket hunter: the big ones", "own account, 20 a coin, -30% / 11x / 6 h", bal, int(num(sm.get("trades")) or 0),
                  int(num(sm.get("open")) or 0), num(sm.get("inProfitOf10")), hits)
    op = []
    for a, p in sorted(((doc.get("book") or {}).get("open") or {}).items(), key=lambda kv: -(num(kv[1].get("t")) or 0)):
        if isinstance(p, dict):
            op.append("<li><b>%s</b> bought at score %.3f · now x%.2f · high x%.2f</li>" % (
                E(p.get("sym") or str(a)[:6]), num(p.get("score")) or 0, num(p.get("now")) or 1.0, num(p.get("hi")) or 1.0))
    top = []
    for r in (doc.get("top") or [])[:5]:
        if isinstance(r, dict):
            top.append("<li>%s · score %.4f%s · %d min old</li>" % (E(r.get("sym") or str(r.get("addr"))[:6]), num(r.get("score")) or 0,
                                                                   " · bought" if r.get("buy") else "", int(num(r.get("age")) or 0)))
    rd = doc.get("round") or {}
    when = ""
    if num(doc.get("t")):
        try:
            import page_account as PA
            when = "last round %s %s · " % (PA.mday(doc["t"]), PA.hhmm(doc["t"]))
        except Exception:
            when = ""
    body = ('<div class="rk-cards">%s%s</div>' % (pick, rocket)
            + ('<div class="rk-st"><span class="k">Open rocket positions</span><ul>%s</ul></div>' % "".join(op) if op else "")
            + ('<div class="rk-st"><span class="k">Best scores of the last round (cut %.4f)</span><ul>%s</ul></div>' % (num(doc.get("cut")) or 0, "".join(top)) if top else "")
            + '<p class="rk-s">%s%d radar coins watched, %d scored. A live test: on the history the strictest cut made money only on few coins '
              '(about 1 in 10 bought became 10x, 2 of 10 ended in profit); this account shows whether it holds.</p>' % (
                  E(when), int(num(rd.get("candidates")) or 0), int(num(rd.get("scored")) or 0)))
    return wrap(body)


CSS = r"""
/* the rocket hunter (page_rocket.py) */
.rk { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 8px; display:grid; gap:10px; min-width:0; margin-bottom:12px }
.rk-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .rk-head h3 { margin:0 }
.rk-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:8px }
.rk-c { border:1px solid var(--line); border-radius:10px; padding:10px 12px; display:grid; gap:2px; min-width:0 }
.rk-c .k, .rk-st .k { font-size:var(--fs-xs); color:var(--muted) } .rk-c b { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums }
.rk-c b.up { color:var(--good) } .rk-c b.dn { color:var(--bad) }
.rk-c small { font-size:var(--fs-xs); color:var(--fg2); overflow-wrap:anywhere }
.rk-st ul { margin:4px 0 0; padding-left:18px; font-size:var(--fs-s); color:var(--fg2) }
.rk-s { margin:0; font-size:var(--fs-xs); color:var(--muted); max-width:70ch; overflow-wrap:anywhere }
@media (max-width:560px) { .rk { padding:12px 12px 6px } }
"""
