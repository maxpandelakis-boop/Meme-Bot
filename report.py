#!/usr/bin/env python3
"""report.py: the analysis page. Renders everything in db/ as one self-contained HTML file (mb/report.html).

  python3 report.py [--dir mb] [--out mb/report.html] [--fragment]

bot.py writes it after every cycle, so the page is always the state after the last run. Open it in a browser (it is a plain
file, no server needed). --fragment leaves out the <html>/<head>/<body> wrapper for hosts that add their own.

Sections: bankroll and equity (hero), equity curve per run, the bought coins (open positions with their last price and the
bot's reasons), closed trades with their result, the 24-hour big test (how the gated coins, the bot's top 10 and the rest did),
the factor weights in use, the top candidates of the last full scan, and the run log.
"""
import argparse, html, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M

TITLE = "Meme-Bot Ledger"
E = lambda s: html.escape(str(s if s is not None else ""), quote=True)


# ---------------------------------------------------------------- formatting
def fmt_money(v, dollars=True):
    v = M.num(v)
    if v is None:
        return "–"
    s = "$" if dollars else ""
    if abs(v) >= 1e9:
        return "%s%.2fB" % (s, v / 1e9)
    if abs(v) >= 1e6:
        return "%s%.1fM" % (s, v / 1e6)
    if abs(v) >= 1e4:
        return "%s%.0fk" % (s, v / 1e3)
    return "%s%s" % (s, format(v, ",.0f"))


def fmt_px(p):
    p = M.num(p)
    if p is None or p <= 0:
        return "–"
    if p >= 1:
        return "$" + format(p, ",.4g") if p < 1e4 else "$" + format(p, ",.0f")
    digits = min(12, max(3, -int(math.floor(math.log10(p))) + 3))
    return "$" + ("%." + str(digits) + "f") % p


def fmt_amt(v, signed=False):
    v = M.num(v)
    if v is None:
        return "–"
    return ("%+.2f" if signed else "%.2f") % v


def fmt_mult(v):
    v = M.num(v)
    return "–" if v is None else ("%.2fx" % v if v >= 0.1 else "%.3fx" % v)


def fmt_dt(ms, short=False):
    ms = M.num(ms)
    if not ms:
        return "–"
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return t.strftime("%b %d %H:%M") if short else t.strftime("%Y-%m-%d %H:%M UTC")


def fmt_age(ms, now):
    ms = M.num(ms)
    if not ms:
        return "–"
    h = (now - ms) / 3_600_000
    if h < 1:
        return "%d min" % round(h * 60)
    if h < 48:
        return "%.0f h" % h
    return "%.1f d" % (h / 24)


def pct(v):
    v = M.num(v)
    return "–" if v is None else "%d%%" % round(v)


def clean_ticks(lo, hi, n=4):
    """n-ish round tick values spanning [lo, hi] (always includes 0 when the range crosses it)."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        ticks.append(round(v, 6))
        v += step
    return ticks


# ---------------------------------------------------------------- data
def collect(d, now):
    pos = M.positions(d)
    exits = M.load_docs(d, "memeexit")
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    curve = sorted(M.load_docs(d, "memecurve").values(), key=lambda c: M.num(c.get("t")) or 0)
    runs = sorted(M.load_docs(d, "memeruns").values(), key=lambda r: -(M.num(r.get("t")) or 0))
    snaps = M.load_docs(d, "memesnap")
    res = M.load_docs(d, "memesnapres")
    cash = M.bankroll(pos)
    px = marks.get("px") or {}

    rows = []
    for pid, p in pos.items():
        ticket, entry = M.num(p.get("ticket")) or M.TICKET, M.num(p.get("px"))
        back = sum(M.num(e.get("eur")) or 0 for e in p["_exits"])
        last = M.num(px.get(pid))
        if last is None and p["_left"] <= 1e-9 and p["_exits"]:
            last = M.num(p["_exits"][-1].get("px"))
        value = None
        if p["_left"] > 1e-9 and last and entry:
            gross = (ticket - M.fee(ticket)) * p["_left"] * last / entry
            value = max(0.0, gross - M.fee(gross))
        closed = p["_left"] <= 1e-9
        pnl = back - ticket if closed else (back + (value or 0) - ticket if value is not None else None)
        whys = [e.get("why", "?") for e in p["_exits"]]
        if closed:
            status, kind = ", ".join(whys), ("good" if pnl > 0 else "bad")
        elif p["_exits"]:
            status, kind = "half sold at 2x", "good"
        else:
            status, kind = "open", "neutral"
        rows.append({"id": pid, "p": p, "ticket": ticket, "entry": entry, "back": back, "last": last, "value": value, "closed": closed,
                     "pnl": pnl, "status": status, "kind": kind, "mult": (last / entry) if last and entry else None,
                     "exit_t": M.num(p["_exits"][-1].get("t")) if closed and p["_exits"] else None, "bot": p.get("grp") in M.BOT_GROUPS})
    rows.sort(key=lambda r: -(M.num(r["p"].get("t")) or 0))
    open_rows = [r for r in rows if not r["closed"]]
    closed_rows = [r for r in rows if r["closed"]]
    equity = cash["free"] + sum(r["value"] or 0 for r in open_rows if r["bot"])
    bot_closed = [r for r in closed_rows if r["bot"]]
    wins = sum(1 for r in bot_closed if r["pnl"] > 0)

    # big test: chunks of the same snapshot run -> one group
    groups = {}
    for sid, r in res.items():
        key = str(sid).rsplit("-", 1)[0]
        g = groups.setdefault(key, {"t0": M.num(r.get("t0")), "t": M.num(r.get("t")), "n": 0, "pass": [], "top": [], "fail": [], "up": 0, "gone": 0, "coins": 0})
        for c in r.get("coins") or []:
            eur = M.num(c.get("eur"))
            if eur is None:
                continue
            g["n"] += 1
            (g["pass"] if c.get("pass") else g["fail"]).append(eur)
            if c.get("rank") and c["rank"] <= 10:
                g["top"].append(eur)
            g["up"] += 1 if eur > 0 else 0
            g["gone"] += 1 if c.get("gone") else 0
    avg = lambda xs: (sum(xs) / len(xs)) if xs else None
    big = []
    for key, g in sorted(groups.items(), key=lambda kv: kv[1]["t0"] or 0):
        big.append({"key": key, "t0": g["t0"], "t": g["t"], "n": g["n"], "passN": len(g["pass"]), "passAvg": avg(g["pass"]), "topN": len(g["top"]),
                    "topAvg": avg(g["top"]), "failN": len(g["fail"]), "failAvg": avg(g["fail"]), "up": g["up"], "gone": g["gone"]})

    # the last full scan: its top candidates
    last_t = max([M.num(s.get("t")) or 0 for s in snaps.values()] or [0])
    cands = []
    if last_t:
        for s in snaps.values():
            if (M.num(s.get("t")) or 0) == last_t:
                cands += [c for c in (s.get("coins") or []) if isinstance(c, dict) and c.get("rank")]
        cands.sort(key=lambda c: c["rank"])
    held_addrs = {r["p"].get("addr") for r in open_rows}
    ever_addrs = {r["p"].get("addr") for r in rows}
    w, winfo = M.blended_weights(d)
    weights = sorted(w.items(), key=lambda kv: -abs(kv[1]))[:16]
    detail = (winfo.get("detail") or {})
    return {"now": now, "pos": rows, "open": open_rows, "closed": closed_rows, "cash": cash, "equity": equity, "state": state, "curve": curve,
            "runs": runs, "big": big, "cands": cands[:15], "scan_t": last_t, "scan_n": sum(M.num(s.get("n")) or 0 for s in snaps.values() if (M.num(s.get("t")) or 0) == last_t),
            "held": held_addrs, "ever": ever_addrs, "weights": weights, "winfo": winfo, "detail": detail, "wins": wins, "bot_closed": bot_closed}


# ---------------------------------------------------------------- charts (inline SVG, drawn to one scale)
def line_chart(series, budget, width=720, height=240):
    """series: [(name, css class, [(t, v)])]. Hover: crosshair + tooltip via the page script (data-pts on the overlay)."""
    pts_all = [(t, v) for _, _, pts in series for t, v in pts]
    if len(pts_all) < 2:
        return ""
    ml, mr, mt, mb = 44, 60, 14, 28
    pw, ph = width - ml - mr, height - mt - mb
    t0, t1 = min(t for t, _ in pts_all), max(t for t, _ in pts_all)
    if t1 == t0:
        t1 = t0 + 1
    vals = [v for _, v in pts_all] + [budget]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = lo - pad, hi + pad
    ticks = clean_ticks(lo, hi, 4)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    X = lambda t: ml + (t - t0) / (t1 - t0) * pw
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" viewBox="0 0 %d %d" role="img" aria-label="Equity per run">' % (width, height)]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%g</text>' % (ml, y, ml + pw, y, ml - 6, y + 4, tk))
    yb = Y(budget)
    out.append('<line class="ref" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f">start %g</text>' % (ml, yb, ml + pw, yb, ml + pw + 4, yb + 4, budget))
    # x labels: first, last and up to 3 between
    n_lab = min(5, len({t for t, _ in pts_all}))
    for i in range(n_lab):
        t = t0 + (t1 - t0) * i / max(n_lab - 1, 1)
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="%s">%s</text>' % (X(t), height - 8, "start" if i == 0 else ("end" if i == n_lab - 1 else "middle"), fmt_dt(t, True)))
    for name, cls, pts in series:
        if len(pts) < 2:
            continue
        path = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", X(t), Y(v)) for i, (t, v) in enumerate(pts))
        if cls == "s1":
            out.append('<path class="area %s" d="%s L%.1f %.1f L%.1f %.1f Z"/>' % (cls, path, X(pts[-1][0]), mt + ph, X(pts[0][0]), mt + ph))
        out.append('<path class="line %s" d="%s"/>' % (cls, path))
        tl, vl = pts[-1]
        out.append('<circle class="dot %s" cx="%.1f" cy="%.1f" r="4"/><text class="label" x="%.1f" y="%.1f">%s %.2f</text>' % (cls, X(tl), Y(vl), X(tl) + 8, Y(vl) + 4, "" if len(series) == 1 else name, vl))
    data = [{"x": round(X(t), 1), "t": fmt_dt(t), "v": [(name, round(v, 2)) for name, _, pts in series for tt, v in pts if tt == t]} for t in sorted({t for t, _ in pts_all})]
    out.append('<line class="cross" x1="0" y1="%d" x2="0" y2="%d" style="opacity:0"/>' % (mt, mt + ph))
    out.append('<rect class="overlay" x="%d" y="%d" width="%d" height="%d" fill="transparent" data-pts=\'%s\'/>' % (ml, mt, pw, ph, E(json.dumps(data, separators=(",", ":")))))
    out.append("</svg>")
    return "".join(out)


def bar_path(x, y0, y1, w, r=4):
    """A column from the baseline y0 to the data end y1, rounded only at the data end."""
    if abs(y1 - y0) < 0.5:
        return '<rect x="%.1f" y="%.1f" width="%.1f" height="1"/>' % (x, min(y0, y1) - 0.5, w)
    r = min(r, w / 2, abs(y1 - y0))
    if y1 < y0:   # grows up
        return '<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z"/>' % (x, y0, y1 + r, x, y1, x + r, y1, x + w - r, x + w, y1, x + w, y1 + r, y0)
    return '<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z"/>' % (x, y0, y1 - r, x, y1, x + r, y1, x + w - r, x + w, y1, x + w, y1 - r, y0)


def grouped_bars(groups, series, width=720, height=220):
    """groups: [(label, {series key: value|None, ...})]; series: [(key, name, css class)]. Negative values hang below the baseline."""
    vals = [v for _, g in groups for v in g.values() if v is not None]
    if not vals:
        return ""
    ml, mr, mt, mb = 44, 12, 14, 28
    pw, ph = width - ml - mr, height - mt - mb
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - (pad if lo < 0 else 0), hi + pad
    ticks = clean_ticks(lo, hi, 4)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    Y = lambda v: mt + (hi - v) / (hi - lo) * ph
    out = ['<svg class="chart-svg" viewBox="0 0 %d %d" role="img" aria-label="Big test results per scan">' % (width, height)]
    for tk in ticks:
        y = Y(tk)
        out.append('<line class="%s" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%g</text>' % ("axis" if tk == 0 else "grid", ml, y, ml + pw, y, ml - 6, y + 4, tk))
    band = pw / len(groups)
    bw = min(24, (band - 10) / len(series) - 2)
    for gi, (label, g) in enumerate(groups):
        gx = ml + band * gi + (band - (bw + 2) * len(series)) / 2
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (ml + band * gi + band / 2, height - 8, E(label)))
        for si, (key, name, cls) in enumerate(series):
            v = g.get(key)
            if v is None:
                continue
            x = gx + si * (bw + 2)
            out.append('<g class="bar %s" data-tip="%s · %s: %+.2f">%s</g>' % (cls, E(label), E(name), v, bar_path(x, Y(0), Y(v), bw)))
    out.append("</svg>")
    return "".join(out)


def weight_bars(weights, detail, width=720):
    """Horizontal diverging bars around 0: positive weights to the right (blue), negative to the left (red)."""
    if not weights:
        return ""
    rowh, ml, mr = 22, 150, 60
    height = rowh * len(weights) + 10
    pw = width - ml - mr
    mx = max(abs(v) for _, v in weights) or 1
    cx = ml + pw / 2
    S = lambda v: v / mx * (pw / 2 - 4)
    out = ['<svg class="chart-svg" viewBox="0 0 %d %d" role="img" aria-label="Factor weights in use">' % (width, height)]
    out.append('<line class="axis" x1="%.1f" y1="4" x2="%.1f" y2="%d"/>' % (cx, cx, height - 4))
    for i, (k, v) in enumerate(weights):
        y = 6 + i * rowh
        n = (detail.get(k) or {}).get("n")
        out.append('<text class="label" x="%d" y="%.1f" text-anchor="end">%s</text>' % (ml - 8, y + 12, E(k)))
        x0, x1 = (cx, cx + S(v)) if v >= 0 else (cx + S(v), cx)
        out.append('<g class="bar %s" data-tip="%s: %+.3f%s"><rect x="%.1f" y="%.1f" width="%.1f" height="12" rx="3"/></g>' % ("pos" if v >= 0 else "neg", E(k), v, (" (from %d coins)" % n) if n else " (prior)", x0, y + 2, max(1, x1 - x0), ))
        out.append('<text class="tick" x="%.1f" y="%.1f" text-anchor="%s">%+.2f</text>' % ((x1 + 6) if v >= 0 else (x0 - 6), y + 12, "start" if v >= 0 else "end", v))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- page
CSS = r"""
/* Layout: one 1100px column; a hero row of figures, then sections scanned top to bottom. */
:root { --bg:#f5f6f8; --surface:#ffffff; --fg:#14171c; --fg2:#4b535e; --muted:#7a838f; --line:#e2e5ea; --line2:#eef0f3;
  --accent:#2a78d6; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#006300; --good-mark:#0ca30c; --bad:#c7342f; --bad-mark:#d03b3b; --warn:#9a5b00;
  --chip:#eef2f7; --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#848c97; --line:#2a2f37; --line2:#22262d;
  --accent:#3987e5; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --chip:#232830; color-scheme:dark } }
:root[data-theme="dark"] { --bg:#101215; --surface:#181b20; --fg:#eef0f3; --fg2:#b6bcc5; --muted:#848c97; --line:#2a2f37; --line2:#22262d;
  --accent:#3987e5; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#2bbf3a; --good-mark:#0ca30c; --bad:#ef7070; --bad-mark:#e66767; --warn:#e0a24a; --chip:#232830; color-scheme:dark }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 var(--sans); }
.wrap { max-width:1100px; margin:0 auto; padding-inline:16px; padding-block:24px 48px; display:grid; gap:28px }
h1,h2,h3 { margin:0; text-wrap:balance; line-height:1.2 }
h1 { font-size:22px; font-weight:600 }
h2 { font-size:16px; font-weight:600 }
.eyebrow { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500 }
header { display:flex; flex-wrap:wrap; gap:8px 24px; align-items:baseline; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:14px }
header .meta { color:var(--fg2); font-size:13px; display:flex; flex-wrap:wrap; gap:4px 16px }
section { display:grid; gap:12px }
.sec-head { display:flex; flex-wrap:wrap; gap:4px 16px; align-items:baseline; justify-content:space-between }
.sec-head p { margin:0; color:var(--fg2); font-size:13px }
.hero { display:grid; grid-template-columns:minmax(220px,1.4fr) repeat(auto-fit,minmax(140px,1fr)); gap:12px }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; display:grid; gap:2px; align-content:start }
.tile .label { font-size:12px; color:var(--muted) }
.tile .value { font-size:22px; font-weight:600; letter-spacing:-.01em }
.tile.lead .value { font-size:44px; line-height:1.05 }
.tile .sub { font-size:12px; color:var(--fg2) }
.delta { font-weight:500; font-size:16px } .tile.lead .delta { font-size:20px; margin-left:6px } .delta.good { color:var(--good) } .delta.bad { color:var(--bad) }
.chart { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px 8px 4px }
.chart-svg { width:100%; min-width:560px; display:block; font-family:var(--sans) }
.chart-svg .grid { stroke:var(--line2); stroke-width:1 } .chart-svg .axis { stroke:var(--line); stroke-width:1 } .chart-svg .ref { stroke:var(--muted); stroke-width:1 }
.chart-svg .tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums } .chart-svg .label { fill:var(--fg2); font-size:11px }
.chart-svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round } .chart-svg .line.s1 { stroke:var(--s1) } .chart-svg .line.s2 { stroke:var(--s2) }
.chart-svg .area.s1 { fill:var(--s1); opacity:.1 } .chart-svg .dot { stroke:var(--surface); stroke-width:2 } .chart-svg .dot.s1 { fill:var(--s1) } .chart-svg .dot.s2 { fill:var(--s2) }
.chart-svg .bar.s1 { fill:var(--s1) } .chart-svg .bar.s2 { fill:var(--s2) } .chart-svg .bar.s3 { fill:var(--s3) } .chart-svg .bar.pos { fill:var(--s1) } .chart-svg .bar.neg { fill:var(--bad-mark) }
.chart-svg .bar:hover { opacity:.8 } .chart-svg .cross { stroke:var(--muted); stroke-width:1 }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; font-size:12px; color:var(--fg2); padding:0 8px }
.legend span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; background:var(--c) }
.tip { position:fixed; pointer-events:none; background:var(--fg); color:var(--bg); font-size:12px; padding:6px 8px; border-radius:6px; max-width:280px; opacity:0; transition:opacity .08s; z-index:10; white-space:pre-line }
.tip.on { opacity:1 }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px }
.card { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; display:grid; gap:8px }
.card .top { display:flex; justify-content:space-between; gap:12px; align-items:baseline }
.card .sym { font-size:18px; font-weight:600 } .name { color:var(--fg2); font-size:12px; margin-left:6px }
.chip { display:inline-block; font-size:11px; font-weight:500; padding:2px 8px; border-radius:999px; background:var(--chip); color:var(--fg2); white-space:nowrap }
.chip.good { background:color-mix(in srgb,var(--good-mark) 16%,var(--surface)); color:var(--good) } .chip.bad { background:color-mix(in srgb,var(--bad-mark) 16%,var(--surface)); color:var(--bad) }
.chip.neutral { background:color-mix(in srgb,var(--accent) 14%,var(--surface)); color:var(--accent) }
.kv { display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:6px 12px; font-size:13px }
.kv div { min-width:0 } .kv .k { color:var(--muted); font-size:11px } .kv .v { font-variant-numeric:tabular-nums; white-space:nowrap }
.why { font-size:13px; color:var(--fg2); margin:0 } .safety { font-size:13px; margin:0 }
.links { display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12px } a { color:var(--accent); text-decoration:none } a:hover,a:focus-visible { text-decoration:underline }
.addr { font-family:var(--mono); font-size:11px; color:var(--muted); overflow-wrap:anywhere }
.tbl { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px }
table { border-collapse:collapse; width:100%; font-size:13px } th,td { text-align:left; padding:8px 12px; border-top:1px solid var(--line2); vertical-align:top }
th { color:var(--muted); font-weight:500; font-size:11px; letter-spacing:.04em; text-transform:uppercase; border-top:0; white-space:nowrap }
td.n,th.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap } td .good { color:var(--good) } td .bad { color:var(--bad) }
details { font-size:13px } summary { cursor:pointer; color:var(--fg2) } details .tbl { margin-top:8px }
.empty { background:var(--surface); border:1px dashed var(--line); border-radius:8px; padding:20px; color:var(--fg2) } .empty code { font-family:var(--mono); font-size:12px; background:var(--chip); padding:1px 5px; border-radius:4px }
.note { font-size:13px; color:var(--fg2); margin:0; max-width:72ch }
.runs td.note-cell { max-width:520px; white-space:normal; color:var(--fg2) }
footer { color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:14px; display:flex; flex-wrap:wrap; gap:4px 20px }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
@media (prefers-reduced-motion: reduce) { .tip { transition:none } }
@media (max-width:560px) { .tile.lead .value { font-size:36px } .hero { grid-template-columns:1fr 1fr } .hero .tile.lead { grid-column:1 / -1 } }
"""

JS = r"""
(function(){
  var tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
  function show(x,y,text){tip.textContent=text;tip.classList.add('on');var w=tip.offsetWidth,h=tip.offsetHeight;
    var left=Math.min(x+14,window.innerWidth-w-8),top=y-h-12;if(top<8)top=y+16;tip.style.left=left+'px';tip.style.top=top+'px';}
  function hide(){tip.classList.remove('on');}
  document.addEventListener('mousemove',function(e){
    var m=e.target.closest&&e.target.closest('[data-tip]');
    if(m){show(e.clientX,e.clientY,m.getAttribute('data-tip'));return;}
    var o=e.target.closest&&e.target.closest('.overlay');
    if(o){var pts=o._pts||(o._pts=JSON.parse(o.getAttribute('data-pts')));var svg=o.ownerSVGElement;var r=svg.getBoundingClientRect();
      var vb=svg.viewBox.baseVal;var x=(e.clientX-r.left)/r.width*vb.width;var best=pts[0],bd=1e9;
      for(var i=0;i<pts.length;i++){var d=Math.abs(pts[i].x-x);if(d<bd){bd=d;best=pts[i];}}
      var c=svg.querySelector('.cross');if(c){c.setAttribute('x1',best.x);c.setAttribute('x2',best.x);c.style.opacity=1;}
      show(e.clientX,e.clientY,best.t+'\n'+best.v.map(function(v){return v[0]+': '+v[1].toFixed(2);}).join('\n'));return;}
    document.querySelectorAll('.cross').forEach(function(c){c.style.opacity=0;});hide();
  });
  document.addEventListener('mouseleave',hide);
})();
"""


def tile(label, value, sub="", lead=False, delta=None):
    d = ""
    if delta is not None:
        d = ' <span class="delta %s">%s</span>' % ("good" if delta > 0 else ("bad" if delta < 0 else ""), fmt_amt(delta, True))
    return '<div class="tile%s"><div class="label">%s</div><div class="value">%s%s</div>%s</div>' % (" lead" if lead else "", E(label), E(value), d, ('<div class="sub">%s</div>' % E(sub)) if sub else "")


def links(p):
    a, pair = p.get("addr"), p.get("pair")
    out = ['<a href="https://dexscreener.com/solana/%s" target="_blank" rel="noopener">DexScreener</a>' % E(pair or a),
           '<a href="https://rugcheck.xyz/tokens/%s" target="_blank" rel="noopener">RugCheck</a>' % E(a)]
    if p.get("x"):
        out.append('<a href="%s" target="_blank" rel="noopener">X</a>' % E(p["x"]))
    return '<div class="links">%s</div>' % "".join(out)


def position_card(r, now):
    p = r["p"]
    kv = [("bought", fmt_dt(p.get("t"), True)), ("entry", fmt_px(r["entry"])), ("last", fmt_px(r["last"])), ("multiple", fmt_mult(r["mult"])),
          ("paid", fmt_amt(r["ticket"])), ("worth now", fmt_amt(r["value"]) if r["value"] is not None else "no price yet"), ("left", pct(100 * p["_left"])),
          ("came back", fmt_amt(r["back"])), ("score", "%s (rank %s)" % (M.num(p.get("score")) and "%.0f" % M.num(p.get("score")), p.get("rank") or "?")),
          ("cap at buy", fmt_money(p.get("mc"))), ("liquidity", fmt_money(p.get("liq"))), ("held", fmt_age(p.get("t"), now))]
    pnl = r["pnl"]
    pnl_html = ('<span class="delta %s">%s</span>' % ("good" if pnl > 0 else ("bad" if pnl < 0 else ""), fmt_amt(pnl, True))) if pnl is not None else ""
    return ('<article class="card"><div class="top"><div><span class="sym">%s</span><span class="name">%s</span></div><div>%s <span class="chip %s">%s</span></div></div>'
            '<div class="kv">%s</div><p class="safety">%s</p><p class="why">%s</p>%s<div class="addr">%s</div></article>') % (
        E(p.get("sym")), E(p.get("name")), pnl_html, r["kind"], E(r["status"]), "".join('<div><div class="k">%s</div><div class="v">%s</div></div>' % (E(k), E(v)) for k, v in kv),
        E(p.get("safety") or ""), E((p.get("why") or "").split("; RugCheck")[0]), links(p), E(p.get("addr")))


def closed_table(rows):
    if not rows:
        return '<div class="empty">No closed trades yet.</div>'
    tr = []
    for r in rows:
        p = r["p"]
        days = ((r["exit_t"] or 0) - (M.num(p.get("t")) or 0)) / 86_400_000 if r["exit_t"] else None
        tr.append('<tr><td><strong>%s</strong><span class="name">%s</span></td><td>%s</td><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n"><span class="%s">%s</span></td><td class="n">%s</td><td class="n">%s</td></tr>' % (
            E(p.get("sym")), E(p.get("name")), "bot" if r["bot"] else "random", fmt_dt(p.get("t"), True), E(r["status"]), fmt_amt(r["ticket"]), fmt_amt(r["back"]),
            "good" if r["pnl"] > 0 else "bad", fmt_amt(r["pnl"], True), fmt_mult(r["back"] / r["ticket"] if r["ticket"] else None), ("%.1f d" % days) if days is not None else "–"))
    return '<div class="tbl"><table><thead><tr><th>coin</th><th>group</th><th>bought</th><th>sold because</th><th class="n">paid</th><th class="n">came back</th><th class="n">result</th><th class="n">payout ratio</th><th class="n">held</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def big_section(big):
    if not big:
        return '<div class="empty">The big test starts after the first full scan has been priced again 24 hours later. Every full scan saves all its coins; the next day each one is checked: what would 20 in it have become?</div>'
    groups = [(fmt_dt(g["t0"], True), {"pass": g["passAvg"], "top": g["topAvg"], "fail": g["failAvg"]}) for g in big[-10:]]
    series = [("pass", "passed the gates", "s1"), ("top", "bot's top 10", "s2"), ("fail", "failed a gate", "s3")]
    chart = grouped_bars(groups, series)
    legend = '<div class="legend">%s</div>' % "".join('<span style="--c:var(--%s)">%s</span>' % (cls, E(name)) for _, name, cls in series)
    tr = "".join('<tr><td>%s</td><td class="n">%d</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%d · %s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
        fmt_dt(g["t0"], True), g["n"], g["passN"], fmt_amt(g["passAvg"], True), g["topN"], fmt_amt(g["topAvg"], True), g["failN"], fmt_amt(g["failAvg"], True),
        pct(100 * g["up"] / g["n"]) if g["n"] else "–", pct(100 * g["gone"] / g["n"]) if g["n"] else "–") for g in reversed(big))
    table = ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>scan</th><th class="n">coins</th><th class="n">passed gates · avg</th><th class="n">top 10 · avg</th>'
             '<th class="n">failed a gate · avg</th><th class="n">up after 24h</th><th class="n">gone</th></tr></thead><tbody>%s</tbody></table></div></details>') % tr
    return '<div class="chart">%s</div>%s%s' % (chart, legend, table) if chart else table


def cands_table(c, held, ever):
    if not c:
        return '<div class="empty">No full scan saved yet.</div>'
    tr = []
    for x in c:
        a = x.get("a")
        flag = "held" if a in held else ("bought before" if a in ever else ("safety report" if x.get("rc") else "no safety report"))
        src = ", ".join(str(s) for s in (x.get("src") or [])[:4])
        tr.append('<tr><td class="n">%s</td><td><strong>%s</strong></td><td class="n">%.0f</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td><td><span class="chip">%s</span></td><td><a href="https://dexscreener.com/solana/%s" target="_blank" rel="noopener">chart</a></td></tr>' % (
            x.get("rank"), E(x.get("s")), M.num(x.get("sc")) or 0, fmt_money(x.get("mc")), fmt_money(x.get("liq")), fmt_money(x.get("vol")), E(src), E(flag), E(a)))
    return '<div class="tbl"><table><thead><tr><th class="n">rank</th><th>coin</th><th class="n">score</th><th class="n">market cap</th><th class="n">liquidity</th><th class="n">24h volume</th><th>seen on</th><th>status</th><th></th></tr></thead><tbody>%s</tbody></table></div>' % "".join(tr)


def runs_table(runs):
    if not runs:
        return ""
    tr = "".join('<tr><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%d</td><td class="n">%d</td><td class="note-cell">%s</td></tr>' % (
        fmt_dt(r.get("t"), True), E(r.get("mode")), r.get("scanned") or "–", r.get("passed") or "–", len([p for p in (r.get("picks") or []) if p.get("grp") == "pick"]), len(r.get("exits") or []), E(r.get("note") or "")) for r in runs[:12])
    return '<div class="tbl runs"><table><thead><tr><th>when</th><th>mode</th><th class="n">scanned</th><th class="n">passed gates</th><th class="n">buys</th><th class="n">sells</th><th>what happened</th></tr></thead><tbody>%s</tbody></table></div>' % tr


def render(data, fragment=False):
    D = data
    st, cash, now = D["state"], D["cash"], D["now"]
    equity = D["equity"]
    nb = len(D["bot_closed"])
    best = max(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    worst = min(D["bot_closed"], key=lambda r: r["pnl"], default=None)
    scored = sum(g["n"] for g in D["big"])
    hero = [tile("Equity if everything were sold now", fmt_amt(equity), "started with %g · fake money" % cash["budget"], lead=True, delta=equity - cash["budget"]),
            tile("Free in the bankroll", fmt_amt(cash["free"]), "%d of %d slots open" % (cash["slots"], int(cash["budget"] // cash["ticket"]))),
            tile("Deployed", fmt_amt(cash["deployed"]), "%d open position%s" % (cash["open"], "" if cash["open"] == 1 else "s")),
            tile("Closed trades", str(nb), ("%d won · %d lost" % (D["wins"], nb - D["wins"])) if nb else "none yet"),
            tile("Best / worst trade", ("%s / %s" % (fmt_amt(best["pnl"], True), fmt_amt(worst["pnl"], True))) if best else "–", ("%s / %s" % (best["p"].get("sym"), worst["p"].get("sym"))) if best else ""),
            tile("Big test", "%d coins" % scored if scored else "–", ("%d scans priced again after 24h" % len(D["big"])) if scored else "after the first scan")]
    # equity curve
    pts_bot = [(M.num(c["t"]), M.num(c.get("equity")) if c.get("equity") is not None else cash["budget"] + (M.num(c.get("bot")) or 0)) for c in D["curve"] if M.num(c.get("t"))]
    series = [("bot", "s1", pts_bot)]
    if any((c.get("nRand") or 0) > 0 for c in D["curve"]):
        series.append(("random control", "s2", [(M.num(c["t"]), cash["budget"] + (M.num(c.get("rand")) or 0)) for c in D["curve"] if M.num(c.get("t"))]))
    curve_svg = line_chart(series, cash["budget"])
    if curve_svg:
        curve_html = '<div class="chart">%s</div>' % curve_svg
        if len(series) > 1:
            curve_html += '<div class="legend"><span style="--c:var(--s1)">bot</span><span style="--c:var(--s2)">random control</span></div>'
        curve_html += ('<details><summary>Table view</summary><div class="tbl"><table><thead><tr><th>run</th><th class="n">equity</th>%s</tr></thead><tbody>%s</tbody></table></div></details>' % (
            '<th class="n">random control</th>' if len(series) > 1 else "",
            "".join('<tr><td>%s</td><td class="n">%s</td>%s</tr>' % (fmt_dt(t), fmt_amt(v), ('<td class="n">%s</td>' % fmt_amt(series[1][2][i][1])) if len(series) > 1 else "") for i, (t, v) in enumerate(pts_bot))))
    else:
        curve_html = '<div class="empty">The curve needs two runs. It shows the bankroll plus the value of the open positions after every run.</div>'
    open_html = ('<div class="cards">%s</div>' % "".join(position_card(r, now) for r in D["open"])) if D["open"] else \
        ('<div class="empty">No open positions. %s</div>' % ("The next pick run buys the two best coins when the bankroll has a free slot." if D["runs"] else "Run <code>python3 bot.py cycle</code> to start."))
    w_html = ""
    if D["weights"]:
        lam = D["winfo"]["lambda"]
        w_html = '<div class="chart">%s</div><p class="note">%s</p>' % (weight_bars(D["weights"], D["detail"]),
            E("Learned weights count for %d%% (%d coins scored so far); the hand-made prior fills the rest. Each bar is a factor's weight in the score: positive means higher is better." % (round(100 * lam), D["winfo"]["n"]))
            if D["winfo"]["n"] else E("Nothing learned yet: these are the hand-made prior weights. After ~600 scored big-test coins they are fully replaced by each factor's rank correlation with the 24h result."))
    last_run = st.get("lastRun")
    head = ('<header><div><div class="eyebrow">paper trading · nothing is bought for real</div><h1>%s</h1></div>'
            '<div class="meta"><span>last run %s</span><span>%s run%s</span><span>last scan %s coins, %s passed the gates</span><span>rule %s</span></div></header>') % (
        E(TITLE), E(fmt_dt(last_run)), st.get("runs") or 0, "" if st.get("runs") == 1 else "s", st.get("scanned") or "–", st.get("passed") or "–", E(st.get("rule") or M.RULE))
    body = [head, '<section class="hero">%s</section>' % "".join(hero)]
    if st.get("note"):
        body.append('<section><div class="eyebrow">Last run</div><p class="note">%s</p></section>' % E(st["note"]))
    body.append('<section><div class="sec-head"><h2>Equity per run</h2><p>bankroll plus what the open positions would fetch, after fees</p></div>%s</section>' % curve_html)
    body.append('<section><div class="sec-head"><h2>Bought coins</h2><p>%d open · each bought for %g · sold half at 2x, all at −50%%, after 3 days, or when the price is gone</p></div>%s</section>' % (len(D["open"]), cash["ticket"], open_html))
    body.append('<section><div class="sec-head"><h2>Closed trades</h2><p>what came back after fees, newest first</p></div>%s</section>' % closed_table(D["closed"]))
    body.append('<section><div class="sec-head"><h2>Big test: 24 hours later</h2><p>average result of 20 in every scanned coin, by group</p></div>%s</section>' % big_section(D["big"]))
    if w_html:
        body.append('<section><div class="sec-head"><h2>Factor weights in use</h2><p>what the score rewards and punishes</p></div>%s</section>' % w_html)
    body.append('<section><div class="sec-head"><h2>Top candidates of the last full scan</h2><p>%s · %s coins scanned · ranked among those that passed the gates</p></div>%s</section>' % (
        E(fmt_dt(D["scan_t"])) if D["scan_t"] else "no scan yet", int(D["scan_n"]) if D["scan_n"] else "–", cands_table(D["cands"], D["held"], D["ever"])))
    if D["runs"]:
        body.append('<section><div class="sec-head"><h2>Run log</h2><p>last %d runs</p></div>%s</section>' % (min(12, len(D["runs"])), runs_table(D["runs"])))
    body.append('<footer><span>generated %s</span><span>fees simulated at 0.5%%, minimum 0.81 per trade</span><span>prices from DexScreener at the time of each run</span></footer>' % E(fmt_dt(now)))
    inner = ('<title>%s</title>\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">\n'
             '<style>%s</style>\n<div class="wrap">%s</div>\n<script>%s</script>') % (E(TITLE), CSS, "\n".join(body), JS)
    if fragment:
        return inner
    return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n%s\n</head>\n<body>\n%s\n</body>\n</html>\n' % (
        inner.split("\n<div class=\"wrap\">", 1)[0], "<div class=\"wrap\">" + inner.split("\n<div class=\"wrap\">", 1)[1])


def build(d, out=None, now=None, fragment=False):
    now = int(now or dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    last = M.num((M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}).get("lastRun"))
    now = max(now, int(last)) if last else now      # a db written with a fake clock (tests) must not show negative ages
    page = render(collect(d, now), fragment)
    out = out or os.path.join(d, "report.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(page)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--out", default=None)
    ap.add_argument("--now", type=float, default=None)
    ap.add_argument("--fragment", action="store_true")
    a = ap.parse_args()
    print(build(a.dir, a.out, a.now, a.fragment))


if __name__ == "__main__":
    main()
