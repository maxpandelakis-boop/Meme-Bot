"""page_shadow.py: the fold "Shadow rules" on the Pick tab (shadow.py's accounts). Fake money only: nothing here buys, signs or sends
anything, and nothing here is advice. English words (the user's wish of Oct 22: the whole app in English).

section(D, R) -> HTML: a fold under the hour grid. Its summary line says how many buys were compared and which shadow rule is ahead of
the old fixed rule replayed (K; the Pick's rule until the chart exit of Oct 24, X); inside:
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
import page_home as PH       # pure helpers: numbers (de_eur, de_num), tone

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
TRADES_SHOWN = 30
WHY = {"tp": "target", "half": "half", "stop": "stop", "trail": "trailing stop", "drop": "fast fall", "time": "time", "rug": "pool dead", "dead": "pool dead"}


def num(v):
    return M.num(v)


def short(v):
    """−16.9 / +4.2 / 0.0: one decimal, a real minus, for the narrow cells."""
    v = num(v)
    if v is None:
        return "–"
    s = PH.de_num(v, 1)
    return ("+" + s) if v > 0.04 else s


def when(R, ms):
    try:
        return R.local(ms).strftime("%b %d %H:%M")
    except Exception:
        return "–"


def head_line(S, R):
    """The fold's summary line."""
    if not S["n"]:
        if S["open"]:
            return "%d buy%s running along · first results about 12 h after the buy" % (S["open"], "" if S["open"] == 1 else "s")
        return "running since %s · starts with the next Pick buy" % when(R, S["since"])
    lead = next((a for a in S["accts"] if a["id"] == S["leader"]), None)
    k = next(a for a in S["accts"] if a["id"] == "K")
    bit = ""
    if lead and S["ahead"]:
        bit = " · ahead: %s %s (%s € against K, the old fixed rule)" % (lead["id"], lead["name"], short(lead["eur"] - k["eur"]))
    elif lead:
        bit = " · none better than K, the old fixed rule"
    return "%d buys compared%s" % (S["n"], bit)


def acct_row(a, cls, S):
    vs = ""
    if a.get("vsK") is not None:
        vs = '<small class="%s">%s € against K</small>' % (PH.tone(a["vsK"]), E(short(a["vsK"])))
    chip = '<i class="sh-chip">ahead</i>' if cls == "lead" else ""
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
    head = "<tr><th>Coin</th><th>real</th>%s</tr>" % "".join("<th>%s</th>" % E(i) for i in ids)
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
            what = "running (result about 12 h after the buy)" if r["state"] == "open" else "no minute candles, not counted"
            real = '<td class="n %s">%s</td>' % (PH.tone(r["real"]), E(short(r["real"]))) if r["real"] is not None else '<td class="n">–</td>'
            body.append('<tr class="wait">%s%s<td colspan="%d" class="m">%s</td></tr>' % (coin, real, len(ids), E(what)))
    more = (' (the last %d of %d)' % (TRADES_SHOWN, len(S["trades"]))) if len(S["trades"]) > TRADES_SHOWN else ""
    return ('<details class="sh-tr"><summary>Every buy%s</summary><div class="sh-scroll"><table class="sh-t2"><thead>%s</thead><tbody>%s</tbody>'
            '</table></div><small class="sh-m">€ after fees per buy · real = what the Pick account really got · K to X replayed</small></details>') % (
        E(more), head, "".join(body))


def section(D, R):
    import shadow as SH
    S = SH.summary((D or {}).get("dir") or "", (D or {}).get("now"))
    lead = S["leader"] if S["n"] and S["ahead"] else None
    real = S["real"]
    rows = [acct_row(real, "real", S)]
    for a in S["accts"]:
        rows.append(acct_row(a, "ctl" if a["id"] == "K" else ("lead" if a["id"] == lead else ""), S))
    note = ["Compared: %d buys whose 12 hours are over" % S["n"]]
    if S["open"]:
        note.append("%d still open" % S["open"])
    if S["out"]:
        note.append("%d without minute candles (left out for every rule)" % S["out"])
    note.append("since %s" % when(R, S["since"]))
    few = ' After a few buys a lead means nothing yet; the comparison comes after about two weeks.' if S["n"] < 60 else ""
    inner = ('<div class="sh"><p class="sh-lead">Every real Pick buy also runs here under other sell rules: same coin, '
             'same minute, same %s, same fees. The Pick itself sells by the chart exit since Oct 24 (X); K is the fixed rule it used before. '
             'Paper money only.</p>'
             '<div class="sh-scroll"><table class="sh-t"><thead><tr><th>Rule</th><th>Result</th><th>per buy</th><th>in profit</th></tr></thead>'
             '<tbody>%s</tbody></table></div>'
             '<p class="sh-m">K is the old fixed rule, replayed on the same minute candles: X (the chart exit, replayed the same way) and A to D '
             'are measured against it. The results come '
             'about 12 hours after each buy (when the minute candles are in).%s</p><p class="sh-m">%s</p>%s</div>') % (
        E(("%g €" % S["ticket"]) if S["ticket"] == int(S["ticket"]) else PH.de_eur(S["ticket"])), "".join(rows), E(few), E(" · ".join(note)), trades_table(S, R))
    return ('<details class="fold sh-fold" id="schatten"><summary><span class="t">Shadow rules</span><span class="sum">%s</span></summary>%s</details>'
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
