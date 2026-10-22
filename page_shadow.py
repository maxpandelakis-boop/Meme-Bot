"""page_shadow.py: the fold "Schatten-Regeln" on the Pick tab (shadow.py's accounts). Fake money only: nothing here buys, signs or sends
anything, and nothing here is advice. German words, like the user writes.

section(D, R) -> HTML: a fold under the hour grid. Its summary line says how many buys were compared and which shadow rule is ahead of
the real rule replayed (K); inside:
  - one sentence on what this is: every real Pick buy runs again under four other sell rules (same coin, minute, 50 €, fees); the real
    Pick rule stays as it is
  - the accounts on the same buys: the real Pick account, K (the real rule replayed: the yardstick, same prices and method as the
    shadows), and A to D, each with its result, per buy, how many ended in profit, and how far it is from K
  - when the results come (about 12 hours after each buy), how many buys are still open or left out, since when
  - the buys one by one (newest first, at most TRADES_SHOWN) in a small table that scrolls sideways on a phone
D: report.py's page data (D["dir"], D["now"]); R: report itself (local times). Reads shadow.summary only; every chain string is
escaped. Static HTML and CSS, no script.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import page_home as PH       # pure helpers: German numbers (de_eur, de_num), tone

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
TRADES_SHOWN = 30
WHY = {"tp": "Ziel", "half": "Hälfte", "stop": "Stop", "trail": "Stop", "time": "Zeit", "rug": "Pool tot", "dead": "Pool tot"}


def num(v):
    return M.num(v)


def short(v):
    """−16,9 / +4,2 / 0,0: one decimal, a real minus, for the narrow cells."""
    v = num(v)
    if v is None:
        return "–"
    s = PH.de_num(v, 1)
    return ("+" + s) if v > 0.04 else s


def when(R, ms):
    try:
        return R.local(ms).strftime("%d.%m. %H:%M")
    except Exception:
        return "–"


def head_line(S, R):
    """The fold's summary line."""
    if not S["n"]:
        if S["open"]:
            return "%d Kauf%s läuft mit · erste Ergebnisse ca. 12 h nach dem Kauf" % (S["open"], "" if S["open"] == 1 else "e")
        return "läuft seit %s · startet mit dem nächsten Pick-Kauf" % when(R, S["since"])
    lead = next((a for a in S["accts"] if a["id"] == S["leader"]), None)
    k = next(a for a in S["accts"] if a["id"] == "K")
    bit = ""
    if lead and S["ahead"]:
        bit = " · vorn: %s %s (%s € gegen die echte Regel)" % (lead["id"], lead["name"], short(lead["eur"] - k["eur"]))
    elif lead:
        bit = " · keine besser als die echte Regel"
    return "%d Käufe verglichen%s" % (S["n"], bit)


def acct_row(a, cls, S):
    vs = ""
    if a.get("vsK") is not None:
        vs = '<small class="%s">%s € gegen K</small>' % (PH.tone(a["vsK"]), E(short(a["vsK"])))
    chip = '<i class="sh-chip">vorn</i>' if cls == "lead" else ""
    label = "%s · %s" % (a["id"], a["name"]) if a["id"] != "real" else a["name"]
    won = "%d/%d" % (a["won"], a["n"]) if a["n"] else "–"
    return ('<tr class="%s"><td><b>%s</b>%s<small>%s</small></td><td class="n %s"><b>%s</b>%s</td><td class="n">%s</td><td class="n">%s</td></tr>') % (
        cls, E(label), chip, E(a["text"]), PH.tone(a["eur"]) if a["n"] else "", E(PH.de_eur(a["eur"], True)) if a["n"] else "–", vs,
        E(PH.de_eur(a["per"], True)) if a["per"] is not None else "–", E(won))


def trades_table(S, R):
    rows = S["trades"][:TRADES_SHOWN]
    if not rows:
        return ""
    ids = [a["id"] for a in S["accts"]]
    head = "<tr><th>Coin</th><th>echt</th>%s</tr>" % "".join("<th>%s</th>" % E(i) for i in ids)
    body = []
    for r in rows:
        coin = '<td><b>%s</b><small>%s</small></td>' % (E(r["sym"]), E(when(R, r["t"])))
        if r["state"] == "ok":
            cells = ['<td class="n %s">%s</td>' % (PH.tone(r["real"]), E(short(r["real"])))]
            for i in ids:
                x = r["res"][i]
                cells.append('<td class="n %s" title="%s">%s</td>' % (PH.tone(x["eur"]), E(WHY.get(x["why"], x["why"])), E(short(x["eur"]))))
            body.append("<tr>%s%s</tr>" % (coin, "".join(cells)))
        else:
            what = "läuft (Ergebnis ca. 12 h nach dem Kauf)" if r["state"] == "open" else "ohne Minutenkerzen, nicht gezählt"
            real = '<td class="n %s">%s</td>' % (PH.tone(r["real"]), E(short(r["real"]))) if r["real"] is not None else '<td class="n">–</td>'
            body.append('<tr class="wait">%s%s<td colspan="%d" class="m">%s</td></tr>' % (coin, real, len(ids), E(what)))
    more = (' (die letzten %d von %d)' % (TRADES_SHOWN, len(S["trades"]))) if len(S["trades"]) > TRADES_SHOWN else ""
    return ('<details class="sh-tr"><summary>Die Käufe einzeln%s</summary><div class="sh-scroll"><table class="sh-t2"><thead>%s</thead><tbody>%s</tbody>'
            '</table></div><small class="sh-m">€ nach Gebühren je Kauf · echt = was das Pick-Konto wirklich bekam · K bis D nachgerechnet</small></details>') % (
        E(more), head, "".join(body))


def section(D, R):
    import shadow as SH
    S = SH.summary((D or {}).get("dir") or "", (D or {}).get("now"))
    lead = S["leader"] if S["n"] and S["ahead"] else None
    real = S["real"]
    rows = [acct_row(real, "real", S)]
    for a in S["accts"]:
        rows.append(acct_row(a, "ctl" if a["id"] == "K" else ("lead" if a["id"] == lead else ""), S))
    note = ["Verglichen: %d Käufe, deren 12 Stunden vorbei sind" % S["n"]]
    if S["open"]:
        note.append("%d noch offen" % S["open"])
    if S["out"]:
        note.append("%d ohne Minutenkerzen (bei allen Regeln weggelassen)" % S["out"])
    note.append("seit %s" % when(R, S["since"]))
    few = ' Nach wenigen Käufen sagt ein Vorsprung noch nichts; nach etwa zwei Wochen wird verglichen.' if S["n"] < 60 else ""
    inner = ('<div class="sh"><p class="sh-lead">Jeder echte Pick-Kauf läuft hier zusätzlich unter vier anderen Verkaufs-Regeln: gleicher Coin, '
             'gleiche Minute, gleiche %s, gleiche Gebühren. Die echte Pick-Regel bleibt, wie sie ist. Nur Papiergeld.</p>'
             '<div class="sh-scroll"><table class="sh-t"><thead><tr><th>Regel</th><th>Ergebnis</th><th>pro Kauf</th><th>im Plus</th></tr></thead>'
             '<tbody>%s</tbody></table></div>'
             '<p class="sh-m">K ist die echte Regel, mit denselben Minutenkerzen nachgerechnet: daran werden A bis D gemessen. Die Ergebnisse kommen '
             'etwa 12 Stunden nach jedem Kauf (dann liegen die Minutenkerzen vor).%s</p><p class="sh-m">%s</p>%s</div>') % (
        E(("%g €" % S["ticket"]) if S["ticket"] == int(S["ticket"]) else PH.de_eur(S["ticket"])), "".join(rows), E(few), E(" · ".join(note)), trades_table(S, R))
    return ('<details class="fold sh-fold" id="schatten"><summary><span class="t">Schatten-Regeln</span><span class="sum">%s</span></summary>%s</details>'
            '<style>%s</style>') % (E(head_line(S, R)), inner, CSS)


CSS = r"""
/* the Pick tab's shadow rules (page_shadow.py) */
.sh { display:grid; gap:10px; min-width:0 }
.sh-lead { margin:0; color:var(--fg2); font-size:var(--fs-s); max-width:70ch }
.sh-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100% }
.sh-t, .sh-t2 { width:100%; border-collapse:collapse; font-size:var(--fs-s) }
.sh-t th, .sh-t2 th { text-align:left; font-weight:500; color:var(--muted); font-size:11px; padding:4px 6px; border-bottom:1px solid var(--line) }
.sh-t td, .sh-t2 td { padding:7px 6px; border-bottom:1px solid var(--line2); vertical-align:top }
.sh-t td b, .sh-t2 td b { font-weight:600 } .sh-t td small, .sh-t2 td small { display:block; font-size:11px; color:var(--muted) }
.sh-t td.n, .sh-t2 td.n, .sh-t th:not(:first-child), .sh-t2 th:not(:first-child) { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
.sh-t .good, .sh-t2 .good { color:var(--good) } .sh-t .bad, .sh-t2 .bad { color:var(--bad) }
.sh-t td.n small.good { color:var(--good) } .sh-t td.n small.bad { color:var(--bad) }
.sh-t tr.real td { background:color-mix(in srgb,var(--fg) 4%,transparent) }
.sh-t tr.ctl td:first-child b { color:var(--fg2) }
.sh-t tr.lead td { background:color-mix(in srgb,var(--accent) 10%,transparent) }
.sh-chip { font-style:normal; font-size:10px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; margin-left:6px; padding:1px 6px;
  border-radius:999px; color:var(--accent); background:color-mix(in srgb,var(--accent) 18%,transparent) }
.sh-t2 { font-size:12px } .sh-t2 td { padding:6px 5px } .sh-t2 tr.wait td.m { color:var(--muted); font-size:11px; text-align:left }
.sh-m { margin:0; font-size:11px; color:var(--muted) }
details.sh-tr > summary { color:var(--accent); font-weight:500; cursor:pointer; min-height:44px; display:flex; align-items:center }
"""
