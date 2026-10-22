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
SHOWN = 5                 # candidates in view on the Radar tab; the rest of the round behind "N weitere"


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
    """The scan's paper account, its pick positions only (the new launches ended on Oct 16: Archiv tab), the same numbers as the Start tab."""
    try:
        import page_home as PH
        b = PH.pick_book(D)
    except Exception:
        return None
    return {"bal": b["bal"], "trades": b["closed"], "open": b["open"], "win": b["win"], "x3": b["x3"], "x10": b["x10"]} if b else None


def section(D):
    """The Radar tab's top block: the rocket hunter's own account, its open positions, every candidate of its last round with a bar to the
    buy cut, the rules in one line and the Pick account for comparison."""
    import page_home as PH
    doc = load((D or {}).get("dir"))
    head = ('<div class="rk-head"><div><h3>Raketen-Jäger</h3><small>Rocket hunter · eigenes Papierkonto</small></div>'
            '<span class="chip warn">Spielgeld</span></div>')
    wrap = lambda inner: '<div class="rk" data-pa="rocket">%s%s</div><style>%s</style>' % (head, inner, CSS)
    ps = pick_side(D)
    cmp_ = ('<p class="rk-cmp">Zum Vergleich Pick: <b class="%s">%s</b> · %s/10 im Plus · %d abgeschlossen</p>' % (
        PH.tone(ps["bal"]), E(PH.de_eur(ps["bal"], True)), E("–" if ps["win"] is None else PH.de_num(ps["win"], 1)), ps["trades"])) if ps else ""
    if doc is None:
        return wrap('<p class="rk-s">Der Raketen-Jäger ist noch nicht gelaufen: er prüft alle 15 Minuten die Coins des Radars und kauft auf '
                    'Papier nur, wenn der Raketen-Score eines Coins die Schwelle erreicht.</p>' + cmp_)
    b = PH.rocket_book(doc)
    win = "–" if b["win"] is None else PH.de_num(b["win"], 1)
    stats = [("im Plus", ("%s/10" % win) if b["win"] is not None else "–"), ("3x · 10x", "%d · %d" % (b["x3"], b["x10"])), ("offen", str(b["open"])), ("abgeschlossen", str(b["closed"]))]
    acct = ('<div class="rk-acct"><div class="rk-bal"><span class="k">Kontostand</span><b class="%s">%s</b>%s</div><div class="rk-sts">%s</div></div>') % (
        PH.tone(b["bal"]), E(PH.de_eur(b["bal"], True)), PH.spark(b["pts"], PH.tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), E(v)) for k, v in stats))
    op = []
    for a, p in sorted(((doc.get("book") or {}).get("open") or {}).items(), key=lambda kv: -(num(kv[1].get("t")) or 0)):
        if isinstance(p, dict):
            op.append('<li><b>%s</b><span>gekauft bei Score %s · jetzt x%s · Hoch x%s</span></li>' % (
                E(p.get("sym") or str(a)[:6]), E(PH.de_num(num(p.get("score")) or 0, 3)), E(PH.de_num(num(p.get("now")) or 1.0)), E(PH.de_num(num(p.get("hi")) or 1.0))))
    cut = num(doc.get("cut")) or 0
    rows = []
    for r in [r for r in doc.get("top") or [] if isinstance(r, dict)]:
        sh = (num(r.get("score")) or 0) / cut if cut > 0 else 0
        rows.append('<li class="%s"><b>%s</b><span class="rk-bar"><i style="width:%.1f%%"></i></span><em>%s</em><small>%d min alt%s</small></li>' % (
            "buy" if r.get("buy") else ("near" if sh >= 0.5 else ""), E(str(r.get("sym") or str(r.get("addr") or "?")[:6])[:14]), max(2.0, min(100.0, 100 * sh)),
            "gekauft" if r.get("buy") else "%d %%" % round(100 * sh), int(num(r.get("age")) or 0),
            (" · MC %s $" % PH.de_num(num(r["mc"]), 0)) if num(r.get("mc")) else ""))
    rd = doc.get("round") or {}
    when = ""
    if num(doc.get("t")):
        try:
            import page_account as PA
            when = "Letzte Runde %s %s · " % (PA.mday(doc["t"]), PA.hhmm(doc["t"]))
        except Exception:
            when = ""
    body = (acct
            + ('<div class="rk-st"><span class="k">Offene Positionen</span><ul class="rk-op">%s</ul></div>' % "".join(op) if op else "")
            + ('<div class="rk-st"><span class="k">Kandidaten der letzten Runde · Kauf ab 100 %% der Schwelle (%s)</span><ul class="rk-cands">%s</ul>%s</div>' % (
                E(PH.de_num(cut, 4)), "".join(rows[:SHOWN]), ('<details class="rk-more"><summary>%d weitere</summary><ul class="rk-cands">%s</ul></details>' % (
                    len(rows) - SHOWN, "".join(rows[SHOWN:]))) if len(rows) > SHOWN else "") if rows else '<p class="rk-s">In der letzten Runde lag kein Coin im passenden Alter.</p>')
            + '<p class="rk-s">%s%s Radar-Coins beobachtet, %d bewertet. 20 € pro Coin, Verkauf bei −30 %%, 11x oder nach 6 h. '
              'Live-Test: in der Historie wurde etwa 1 von 10 Käufen 10x, 2 von 10 endeten im Plus.</p>' % (E(when), E(PH.de_num(int(num(rd.get("candidates")) or 0), 0)), int(num(rd.get("scored")) or 0))
            + cmp_)
    return wrap(body)


CSS = r"""
/* the rocket hunter (page_rocket.py) at the top of the Radar tab */
.rk { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:14px 16px 10px; display:grid; gap:12px; min-width:0; margin-bottom:12px;
  background-image:radial-gradient(120% 80% at 100% 0%, color-mix(in srgb,var(--nn2) 14%,transparent), transparent 60%) }
.rk-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:4px 10px } .rk-head h3 { margin:0; font-size:19px }
.rk-head small { font-size:var(--fs-xs); color:var(--muted) }
.rk-acct { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:12px; align-items:center }
.rk-bal { display:grid; gap:2px; min-width:0 } .rk-bal b { font-size:28px; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; white-space:nowrap }
.rk-bal b.good { color:var(--good) } .rk-bal b.bad { color:var(--bad) }
.rk .k { font-size:var(--fs-xs); color:var(--muted) }
.rk-sts { display:grid; grid-template-columns:1fr 1fr; gap:6px }
.rk-sts span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
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
.rk-cmp { margin:0; font-size:var(--fs-s); color:var(--fg2); padding-top:8px; border-top:1px solid var(--line) }
.rk-cmp b.good { color:var(--good) } .rk-cmp b.bad { color:var(--bad) }
@media (max-width:560px) { .rk { padding:12px 12px 8px } .rk-acct { grid-template-columns:1fr } }
"""
