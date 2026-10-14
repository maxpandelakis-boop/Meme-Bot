"""The radar account on the page (fake money only, nothing is ever bought for real): page_account.section shows it right under the
block "Without the stop-loss".

section(D) -> HTML, a compact block "Radar account (bought within minutes)":
  - two tiles, "All 5" and "Green only": the big P/L of the sold ones, invested and back, the win rate, how many sold and how many
    are still inside their 6 hours, and in one small line the same coins in hindsight (sold at the best close within 6 h, and at the
    raw top close, with how many of those could not have been sold there)
  - the best and the worst trade
  - a folded list of the last 30 coins bought: coin (green or not), bought at, sold because, result %, euros
  - honest states: no radar round yet, rounds without a listed coin, everything still inside its 6 hours, windows being priced
D: report.py's page data; only D["dir"] and D["now"] are read (radar_paper.account reads db/memeradar, db/memeradarpaper and
radar_live.json, and writes nothing). Everything is static HTML and CSS; no script. The fake-money note is in the block once.
"""
import html, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import page_account as PA
import radar_paper as RP

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
LIST_N = 30
WHY = {"stop": "stop %s%d%%" % (PA.MINUS, round(100 * M.HOLD_STOP)), "tp": "take-profit +%s%%" % format(round(100 * M.HOLD_TP), ","),
       "time": "%d h limit" % round(M.HOLD_MAX_H), "rug": "pool died"}
VOID = {"unit": "not priced: price unit", "nodata": "not priced: no candles"}


def _when(ms):
    """Oct 14 13:16 (the page's local time)."""
    return "%s %s" % (PA.mday(ms), PA.hhmm(ms)) if RP.num(ms) else "–"


def _pct(r):
    return PA.pct_f(r["eur"] / r["ticket"] - 1.0) if r.get("eur") is not None and r["ticket"] else "–"


def tile(key, title, st, rows_all):
    """One account: its P/L big, then invested, back, the win rate, the counts and the hindsight line."""
    cnt = "%d sold" % st["n"]
    if st["open"]:
        cnt += " · %d open" % st["open"]
    if st["pricing"]:
        cnt += " · %d pricing" % st["pricing"]
    head = '<div class="rp-t"><span>%s</span><b>%s</b></div>' % (E(title), E(cnt))
    if not st["all"]:
        none = "no coin yet" if key == "all" else ("no green coin yet" if rows_all else "no coin yet")
        return '<div class="rp-tile %s" data-rp="%s">%s<p class="rp-none">%s</p></div>' % (key, key, head, E(none))
    if not st["n"]:
        nxt = min((r["end"] for r in rows_all if r["state"] == "open" and (key == "all" or r["green"])), default=None)
        say = ("first result after %s (6 h after its round)" % _when(nxt)) if nxt and not st["pricing"] else (
            "6 h over: priced after the next scan" if st["pricing"] else "not priced: no candles")
        return '<div class="rp-tile %s" data-rp="%s">%s<div class="rp-v" data-rp-v="pnl">–</div><p class="rp-none">%s</p></div>' % (key, key, head, E(say))
    rate = "%.0f%%" % (100 * st["winRate"]) if st["winRate"] is not None else "–"
    hind = ""
    if st["hind"] is not None:                 # the raw top only where it differs from the filtered best
        raw = (' · raw top <b class="%s">%s</b>%s' % (PA.tone(st["raw"]), E(PA.eur(st["raw"], True)), E(" (%d not sellable)" % st["rawCut"]))) if st["rawCut"] else ""
        hind = '<p class="rp-h">hindsight: best in 6 h <b class="%s">%s</b>%s</p>' % (PA.tone(st["hind"]), E(PA.eur(st["hind"], True)), raw)
    return ('<div class="rp-tile %s" data-rp="%s">%s<div class="rp-v %s" data-rp-v="pnl">%s</div>'
            '<div class="rp-f"><span>invested <b>%s</b></span><span>back <b>%s</b></span><span>win rate <b>%s</b> <small>%d of %d</small></span></div>%s</div>') % (
        key, key, head, PA.tone(st["pnl"]), E(PA.eur(st["pnl"], True)), E(PA.eur(st["invested"])), E(PA.eur(st["back"])), E(rate), st["won"], st["n"], hind)


def _because(r):
    if r["state"] == "closed":
        return WHY.get(r["why"], r["why"] or "sold")
    if r["state"] == "void":
        return VOID.get(r["why"], "not priced")
    if r["state"] == "pricing":
        return "6 h over · priced after the next scan"
    return "open until %s" % PA.hhmm(r["end"])


def row(r):
    g = '<span class="chip good">green</span>' if r["green"] else '<span class="rp-vd">%s</span>' % E(r.get("verdict") or "not green")
    res = '<span class="%s">%s</span>' % (PA.tone(r["pnl"]), E(PA.eur(r["pnl"], True))) if r.get("pnl") is not None else '<span class="muted">–</span>'
    return ('<tr><td class="c"><strong>%s</strong> %s</td><td class="w">%s<small>%s</small></td><td class="p %s">%s</td><td class="e">%s</td></tr>') % (
        E(r["sym"]), g, E(_because(r)), E("bought " + _when(r["entryAt"])), PA.tone(r["pnl"]) if r.get("pnl") is not None else "", E(_pct(r)), res)


def section(D):
    A = RP.account((D or {}).get("dir") or "", (D or {}).get("now") or 0)
    rows = A["rows"]
    al, gr = A["all"], A["green"]
    sub = []
    if rows:
        sub.append("%d bought" % len(rows))
    if A["rounds"]:
        sub.append("%d round%s" % (A["rounds"], "" if A["rounds"] == 1 else "s"))
    if A["lastRound"]:
        sub.append("last %s" % _when(A["lastRound"]))
    head = ('<div class="rp-head"><h3>Radar account</h3><span class="rp-sub">bought within minutes</span><span class="chip neutral">fake money</span>'
            '<span class="rp-cnt">%s</span></div>') % E(" · ".join(sub))
    how = ("The best 5 coins (pools under 10 minutes old) of the radar's first round each hour go in here for %s each, at the price the radar "
           "saw, at the round's time, and every coin the radar listed as good in any of its 2-minute rounds; a coin only once. Green: the radar rated it "
           "good in that round. Sold by the paper account's rules on the pool's minute candles: "
           "the first close at %s%% or lower is a stop, the first level of +%s%% or more that the next close confirms is a take-profit (at that "
           "level), else the close at %d hours; a pool that died is a total loss; paper fees on both sides. Hindsight: the same coins sold at their best "
           "close within 6 hours (filtered like the account's best within 6 h), and at the raw top close, unfiltered, which one candle, dust volume, a "
           "dead pool or a level over the cap can make unsellable. Priced by the job after each scan, so a result shows about an hour after its 6 "
           "hours.") % (PA.eur(RP.TICKET), PA.MINUS + str(round(100 * M.HOLD_STOP)), format(round(100 * M.HOLD_TP), ","), round(M.HOLD_MAX_H))
    info = '<details class="pa-i"><summary>ⓘ how</summary><p>%s</p></details>' % E(how)
    wrap = lambda inner: '<div class="rp" data-pa="radarpaper">%s%s</div><style>%s</style>' % (head, inner, CSS)
    if A.get("err"):
        return wrap('<p class="rp-none">The radar account could not be read this time (%s).</p>' % E(A["err"]))
    if not rows:
        say = ("No radar round yet: the best 5 of the first round each hour and every good coin will be counted here." if not A["rounds"] else
               "The radar ran %d round%s but listed no coin yet." % (A["rounds"], "" if A["rounds"] == 1 else "s"))
        return wrap('<p class="rp-none">%s</p>%s' % (E(say), info))
    tiles = tile("all", "All 5", al, rows) + tile("green", "Green only", gr, rows)
    bw = ""
    if al["best"] is not None:
        b, w = al["best"], al["worst"]
        bw = ('<p class="rp-bw"><span>best <b>%s</b> <b class="%s">%s</b> <small>%s</small></span>%s</p>') % (
            E(b["sym"]), PA.tone(b["pnl"]), E(PA.eur(b["pnl"], True)), E(_pct(b)),
            ('<span>worst <b>%s</b> <b class="%s">%s</b> <small>%s</small></span>' % (E(w["sym"]), PA.tone(w["pnl"]), E(PA.eur(w["pnl"], True)), E(_pct(w))))
            if w is not None and w["id"] != b["id"] else "")
    last = rows[:LIST_N]
    lst = ('<details class="fold-lite pa-f rp-list"><summary>Last %d bought%s</summary><div class="tbl rp-tbl"><table><thead><tr><th>coin</th>'
           '<th>sold because</th><th class="n">result</th><th class="n">euros</th></tr></thead><tbody>%s</tbody></table></div></details>') % (
        len(last), (" of %d" % len(rows)) if len(rows) > len(last) else "", "".join(row(r) for r in last))
    return wrap('<div class="rp-tiles">%s</div>%s%s%s' % (tiles, bw, lst, info))


CSS = r"""
/* the radar account (page_radarpaper.py): two tiles, all 5 and green only, the best and worst trade, the folded list */
.rp { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 4px; display:grid; gap:10px; min-width:0 }
.rp-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .rp-head h3 { margin:0 } .rp-sub { font-size:var(--fs-s); color:var(--fg2) }
.rp-cnt { margin-left:auto; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.rp-tiles { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px }
.rp-tile { --tc:var(--accent); border:1px solid var(--line); border-left:4px solid var(--tc); border-radius:10px; padding:10px 14px 12px; display:grid; gap:6px; min-width:0; align-content:start }
.rp-tile.green { --tc:var(--good-mark) }
.rp-t { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:2px 10px } .rp-t span { font-weight:600; font-size:15px }
.rp-t b { font-weight:500; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.rp-v { font-size:30px; line-height:1.1; font-weight:600; letter-spacing:-.01em; font-variant-numeric:tabular-nums; white-space:nowrap }
.rp .good { color:var(--good) } .rp .bad { color:var(--bad) }
.rp-f { display:flex; flex-wrap:wrap; gap:2px 14px; font-size:var(--fs-s); color:var(--fg2) } .rp-f b { color:var(--fg); font-variant-numeric:tabular-nums; white-space:nowrap }
.rp-f small { font-size:var(--fs-xs); color:var(--muted) }
.rp-h { margin:0; padding-top:6px; border-top:1px solid var(--line2); font-size:var(--fs-xs); color:var(--muted) } .rp-h b { font-variant-numeric:tabular-nums; white-space:nowrap }
.rp-none { margin:0; font-size:var(--fs-s); color:var(--muted) }
.rp-bw { margin:0; display:flex; flex-wrap:wrap; gap:2px 18px; font-size:var(--fs-s); color:var(--fg2) } .rp-bw span { overflow-wrap:anywhere }
.rp-bw b { color:var(--fg) } .rp-bw b.good { color:var(--good) } .rp-bw b.bad { color:var(--bad) } .rp-bw small { color:var(--muted) }
.rp-tbl td small { display:block; font-size:var(--fs-xs); color:var(--muted); margin-top:1px; font-variant-numeric:tabular-nums }
.rp-tbl td.c { overflow-wrap:anywhere } .rp-tbl td.c strong { font-weight:600 } .rp-tbl td.c .chip { margin-left:4px; vertical-align:1px }
.rp-tbl .rp-vd { font-size:var(--fs-xs); color:var(--muted) }
.rp-tbl th.n, .rp-tbl td.p, .rp-tbl td.e { text-align:right } .rp-tbl td.p, .rp-tbl td.e { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap }
@media (max-width:560px) {
  .rp { padding:12px 12px 2px } .rp-tiles { grid-template-columns:1fr; gap:10px } .rp-tile { padding:10px 12px 12px } .rp-v { font-size:26px }
  .rp-tbl table, .rp-tbl tbody, .rp-tbl tr, .rp-tbl td { display:block } .rp-tbl thead { display:none }
  .rp-tbl tr { display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"c p" "w e"; gap:2px 12px; padding:8px 4px; border-top:1px solid var(--line2) }
  .rp-tbl tr:first-child { border-top:0 } .rp-tbl td { border-top:0; padding:0; min-width:0 }
  .rp-tbl td.c { grid-area:c } .rp-tbl td.p { grid-area:p } .rp-tbl td.w { grid-area:w; font-size:var(--fs-s); color:var(--fg2) } .rp-tbl td.e { grid-area:e; align-self:end }
}
"""
