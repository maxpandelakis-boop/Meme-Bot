"""The paper account on the page (fake money only, nothing is ever bought for real).

report.py calls two hooks:
  collect():  paper["acct2"] = load(d, now, pos=pos, px=px, since=since)
  render():   the account block is section(D, bought)

load(d, now, pos=None, px=None, since=None) -> dict
    Reads only: db/memebot/state.json and marks.json (when pos/px are not given), the paper positions with their exits, and
    db/memepeak/<pid>.json (written by peak.py, one doc per position whose 6 h window has closed). It writes nothing.
    Returns the three categories of the paper account since the restart, the activity feed and one row per position:
      "stop"   the stop-loss account, exactly M.paper_account (the rule that really runs)
      "best"   best minute-candle close within 6 h of the entry (hindsight): the booked memepeak docs (state ok or est)
      "six"    held 6 h, then sold (hindsight): the booked docs whose x6 is known
      "counts" priced N of M, waiting, estimated, 15-min, not booked (unit), windows still open
      "feed"   paper buys (at entryAt) and sales (exit "at", else "t") since the restart, newest first (at most FEED_MAX)
      "rows"   one row per position since the restart, newest first, with its result and its peak doc
      "noloss" without the stop-loss (hindsight): the trades sold at the stop and at the take-profit, and all trades, each with
               the sum and the extreme of their best (max profit) and lowest (max loss) close within 6 h, what the rule really made
               with the same trades, and how many went back above the entry after the stop (rose further after the take-profit);
               beside the best, the raw top close (peak.py's rawX, unfiltered) where it differs, with its euros and why it was not
               sellable ("one candle", "pool died", "over the cap": raw_reason)

section(D, bought=None) -> HTML
    The survival header (big P/L since the restart, its rate, the balance line, four tiles), the three category strips, the block
    "Without the stop-loss" (two tiles, the all-trades line, the folded per-trade list of max profit and max loss), the activity feed, the top trades in four orders (newest, top %, worst %, best in 6 h) with the two hindsight columns, the open
    positions (report.py's own `bought`), the trades before the restart and the curve fold with the dashed "best within 6 h" line.
    Everything is static HTML and CSS; the only script shows the trader's latest line while a scan runs, and only when the page
    already holds the live doc (report.py's live poll fires the "memebot-live" event; this module starts no poll of its own).
    Right under the block "Without the stop-loss" comes the radar account (page_radarpaper.section: 3 EUR on each launch-radar
    round's best 5, sold by the same rules; radar_paper.py), when page_radarpaper.py is there, and after it the exit what-if block
    (page_exits.section: other stops and targets replayed on the same trades, hindsight; exit_grid.py), when page_exits.py is there.
    On a phone (820 px or less) the category strips keep only the big P/L, its rate and the "same trades" line in view (the
    figures sit in their ⓘ fold) and the feed shows the newest 6 rows (the rest open the fold); CSS only, both are in the page.

Every hindsight number carries the word "hindsight". No text here gives advice.
"""
import html, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS, NB = "−", " "
WINDOW_MS = 6 * 3_600_000           # the hindsight window after the entry (peak.py: end = entryAt + 6 h)
SETTLE_MS = 2 * 60_000              # a window counts once now >= end + 2 min
FEED_PHONE, FEED_SHOWN, FEED_MAX = 6, 20, 300     # the activity feed: rows in view on a phone, on a wide screen, rows in all (the rest in the fold)
TOP_NEW, TOP_N = 100, 50            # the trades: newest 100; top %, worst % and best in 6 h 50 each
BOOKED = ("ok", "est")              # memepeak states that are booked in the "best within 6 h" category
PEAK_STATES = ("ok", "est", "unit", "waiting")
CAP_WORDS = "not confirmed (over 30x or $100M cap)"
CUT_HEAD = {"pool dead": "pool dead", "collapse": "pool dead", "dust": "too little volume", "unconfirmed": "not confirmed by the next close",
            "jump": "not confirmed", "cap": CAP_WORDS, "unit": "price unit mismatch"}       # peak.py's cut texts start "<rule>: ..."
CUT_WORDS = (("rug", "pool dead"), ("dead", "pool dead"), ("liq", "pool dead"), ("collapse", "pool dead"), ("dust", "too little volume"),
             ("volume", "too little volume"), ("unconfirmed", "not confirmed by the next close"), ("confirm", "not confirmed by the next close"),
             ("cap", CAP_WORDS), ("jump", "not confirmed"), ("unit", "price unit mismatch"))
FEED_WHY = {"tp": "take-profit", "stop": "stop", "time": "6 h limit", "rug": "rug", "reset": "restart", "manual": "by hand", "filters": "filters",
            "target": "half at 2x"}
SORTS = (("new", "Newest"), ("top", "Top %"), ("worst", "Worst %"), ("best", "Best in 6 h"))
NL_SHOWN, NL_MAX = 50, 300          # the per-trade list without the stop-loss: rows in its first fold, rows in all (the rest in a fold inside)
RAW_WHY = {"unconfirmed": "one candle", "dust": "dust volume", "cap": "over the cap", "jump": "jump not held", "pool dead": "pool died",
           "collapse": "pool died", "rug": "pool died", "unit": "price unit"}   # why the raw top close was not booked (peak.py's cut rules)


def num(v):
    return M.num(v)


def _report():
    """report.py's module (its formatters, folds and closed-trades table): the one already loaded, also when it runs as a script."""
    r = sys.modules.get("report")
    if r is None:
        main = sys.modules.get("__main__")
        if main is not None and os.path.basename(getattr(main, "__file__", "") or "") == "report.py":
            return main
        import report as r
    return r


# ---------------------------------------------------------------- formatting
def eur(v, signed=False):
    """1,234.56 € with a real minus sign and a no-break space before the euro sign; signed: +12.36 €."""
    v = num(v)
    if v is None:
        return "–"
    s = format(abs(v), ",.2f")
    if v < 0 and s.strip("0.,"):
        return MINUS + s + NB + "€"
    return ("+" if signed and v > 0 else "") + s + NB + "€"


def pct1(v):
    """A share as +23.3% / −23.3% (v is a fraction)."""
    v = num(v)
    if v is None:
        return "–"
    s = "%+.1f%%" % (100 * v)
    return (MINUS + s[1:]) if s[0] == "-" else s


def pct_move(v):
    """A trade's move as +412% / −32% / +4.5% (v is a fraction)."""
    v = num(v)
    if v is None:
        return "–"
    p = 100 * v
    s = ("%+.0f%%" % p) if abs(p) >= 9.95 else ("%+.1f%%" % p)
    return (MINUS + s[1:]) if s[0] == "-" else s


def mult(x):
    x = num(x)
    if x is None:
        return "–"
    if x >= 1000:
        return format(x, ",.0f") + "x"
    return ("%.2fx" % x) if x >= 0.1 else ("%.3fx" % x)


def tone(v):
    v = num(v)
    return "good" if v is not None and v > 0.004 else ("bad" if v is not None and v < -0.004 else "")


def mins_txt(ms):
    ms = num(ms)
    if ms is None or ms < 0:
        return ""
    m = ms / 60_000
    if m < 90:
        return "%d min" % round(m)
    return "%.1f h" % (m / 60)


def held_txt(ms):
    ms = num(ms)
    if ms is None or ms < 0:
        return "–"
    h = ms / 3_600_000
    return ("%d min" % round(h * 60)) if h < 1 else (("%dh" % round(h)) if h < 48 else ("%.1fd" % (h / 24)))


def _local(ms):
    return _report().local(ms)


def hhmm(ms):
    try:
        return _local(num(ms)).strftime("%H:%M")
    except (TypeError, OverflowError, OSError, ValueError):
        return "–"


def mday(ms):
    """A day as the rest of the page writes it: Oct 10."""
    try:
        return _local(num(ms)).strftime("%b %d")
    except (TypeError, OverflowError, OSError, ValueError):
        return "–"


def day_label(ms):
    """The feed's day header, always a date (Sat Oct 10): the page is built once per scan and may be read after midnight, so a
    "Today" fixed at the build would be a day off."""
    try:
        return _local(num(ms)).strftime("%a %b %d")
    except (TypeError, OverflowError, OSError, ValueError):
        return ""


# ---------------------------------------------------------------- data
def cut_reason(cut):
    """The first filter that fired, in a few plain words. peak.py's cut texts start with the rule ("pool dead: rug exit, ...",
    "dust: 59,257x on $3 volume", "cap: 1 level over 30x or a $100M market cap without support"); other texts by their words."""
    for c in cut or []:
        s = str(c).lower()
        head = s.split(":", 1)[0].strip()
        if head in CUT_HEAD:
            return CUT_HEAD[head]
        for key, words in CUT_WORDS:
            if key in s:
                return words
        return str(c)[:60]
    return ""


def peak_mult(v):
    """A multiple as peak.py writes it in its cut texts ("59,257x", "35.2x", "4.00x"), to find the raw top's own rule."""
    return "{:,.0f}x".format(v) if v >= 100 else ("%.1fx" % v if v >= 10 else "%.2fx" % v)


def raw_reason(pk):
    """Why the raw top close (rawX: the highest close inside the window, unfiltered) was not booked, in two words, when it is more
    than 5% over the booked best; "" when they agree. A dust or unconfirmed cut that names the raw multiple wins; else a cap or jump
    cut, then a dead pool, when the raw top is over 1.5x the best (closes that far up are listed by peak.py unless one of those
    rules dropped them); else the next close was lower: one candle."""
    raw, x = num((pk or {}).get("rawX")), num((pk or {}).get("x"))
    if raw is None or x is None or raw <= 1.05 * x:
        return ""
    cut = [str(c) for c in (pk.get("cut") or [])]
    rule = lambda c: next((k for k in RAW_WHY if c.strip().lower().startswith(k)), None)     # "dust: 59,257x on $3 volume" -> dust
    rules = [rule(c) for c in cut]
    name = peak_mult(raw)
    for c, k in zip(cut, rules):
        if k in ("dust", "unconfirmed") and name in c:
            return RAW_WHY[k]
    if raw > 1.5 * x:
        for k in ("cap", "jump", "pool dead", "rug", "collapse", "unit"):
            if k in rules:
                return RAW_WHY[k]
    return RAW_WHY["unconfirmed"]


def peak_doc(doc):
    """A memepeak doc reduced to checked fields, or None when it is not a doc at all. A booked state without a finite multiple is
    treated as still waiting: an unreadable number is never booked."""
    if not isinstance(doc, dict) or doc.get("state") not in PEAK_STATES:
        return None
    g = {k: num(doc.get(k)) for k in ("x", "x6", "eur", "eur6", "at", "entryAt", "end", "rawX", "ticket", "tries", "res", "lo", "loAt", "eurLo")}
    st = doc["state"]
    if st in BOOKED and (g["x"] is None or g["x"] < 0):
        st = "waiting"
    cut = [str(c)[:120] for c in doc.get("cut") or [] if isinstance(c, (str, int, float))][:8] if isinstance(doc.get("cut"), list) else []
    src = doc.get("src") if doc.get("src") in ("m1", "m15", "est") else None
    x6 = g["x6"] if g["x6"] is not None and g["x6"] >= 0 else None
    lo = g["lo"] if st in BOOKED and g["lo"] is not None and g["lo"] >= 0 else None      # the low within 6 h (peak.py PEAK_V 2)
    return {"state": st, "src": src, "x": g["x"] if st in BOOKED else None, "x6": x6 if st in BOOKED else None, "eur": g["eur"], "eur6": g["eur6"],
            "at": g["at"], "entryAt": g["entryAt"], "end": g["end"], "rawX": g["rawX"], "tries": g["tries"], "cut": cut,
            "dead": isinstance(doc.get("dead"), dict), "lo": lo, "loAt": g["loAt"] if lo is not None else None,
            "eurLo": g["eurLo"] if lo is not None and g["eurLo"] is not None and g["eurLo"] >= 0 else None}


def _stats(items):
    """[(ticket, back)] -> invested, back, P/L, won, lost, n."""
    inv = round(sum(t for t, _ in items), 2)
    back = round(sum(b for _, b in items), 2)
    won = sum(1 for t, b in items if b > t)
    return {"n": len(items), "invested": inv, "back": back, "pnl": round(back - inv, 2), "won": won, "lost": len(items) - won,
            "winRate": (won / len(items)) if items else None}


def load(d, now, pos=None, px=None, since=None):
    """The paper account's three categories, its activity feed and one row per position (see the module doc). Never raises: a
    failure returns empty categories with "err" set, so the page still renders."""
    try:
        return _load(d, now, pos, px, since)
    except Exception as e:      # the page must never fail on this block
        empty = _stats([])
        return {"since": since, "err": "%s: %s" % (type(e).__name__, str(e)[:160]), "stop": dict(M.paper_account({}, since), winRate=None),
                "best": empty, "six": empty, "counts": {"M": 0, "priced": 0, "est": 0, "m15": 0, "unit": 0, "waiting": 0, "open": 0},
                "feed": [], "feedN": 0, "rows": [], "bestTrade": None, "peakPts": [], "sameBest": None, "sameSix": None, "noPx": 0,
                "noloss": noloss_data([])}


def _load(d, now, pos, px, since):
    if pos is None or since is None or px is None:
        state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
        marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
        pos = M.positions(d) if pos is None else pos
        since = num(state.get("paperSince")) if since is None else since
        px = (marks.get("px") or {}) if px is None else px
    px = px if isinstance(px, dict) else {}
    stop = M.paper_account(pos, since, px)
    stop["winRate"] = (stop["won"] / stop["nClosed"]) if stop["nClosed"] else None
    docs = {}
    for key, doc in M.load_docs(d, "memepeak").items():
        pd = peak_doc(doc)
        if pd is None:
            continue
        pid = key if key in pos else (doc.get("pos") if isinstance(doc.get("pos"), str) else key)
        docs[pid] = pd
    rows, feed = [], []
    for pid, p in pos.items():
        if not M.in_account(p, since):
            continue
        ticket, entry = num(p.get("ticket")) or 0.0, num(p.get("px"))
        exits = [e for e in p.get("_exits") or [] if isinstance(e, dict)]
        back = sum(num(e.get("eur")) or 0 for e in exits)
        left = num(p.get("_left"))
        left = 1.0 if left is None else left
        closed = left <= 1e-9
        last = num(px.get(pid))
        value = M.pos_value(p, left, last / entry) if not closed and last and entry else None
        pnl = back - ticket if closed else back + (value or 0) - ticket
        got = back if closed else (back + value if value is not None else None)
        pct = (got / ticket - 1) if got is not None and ticket > 0 else None
        t_buy = num(p.get("entryAt")) or num(p.get("t")) or 0
        end = t_buy + WINDOW_MS
        pk = docs.get(pid)
        rows.append({"id": pid, "p": p, "sym": str(p.get("sym") or "?"), "name": p.get("name"), "grp": p.get("grp"), "ticket": ticket, "entry": entry,
                     "t": num(p.get("t")) or 0, "tBuy": t_buy, "end": end, "open": not closed, "back": round(back, 2), "value": value,
                     "pnl": round(pnl, 2), "pct": pct, "exitT": num(exits[-1].get("t")) if closed and exits else None,
                     "status": [e for e in exits], "pk": pk, "windowOpen": now < end + SETTLE_MS})
        feed.append({"t": t_buy, "k": "buy", "id": pid, "sym": str(p.get("sym") or "?"), "grp": p.get("grp"), "ticket": ticket})
        for e in exits:
            ep = num(e.get("px"))
            frac = num(e.get("frac"))
            frac = 1.0 if frac is None else frac
            feed.append({"t": num(e.get("at")) or num(e.get("t")) or 0, "k": "sell", "id": pid, "sym": str(p.get("sym") or "?"), "grp": p.get("grp"),
                         "why": str(e.get("why") or "?"), "move": (ep / entry - 1) if ep is not None and entry else None,
                         "eur": round((num(e.get("eur")) or 0) - ticket * frac, 2), "half": frac < 0.999})
    rows.sort(key=lambda r: (-r["t"], r["id"]))
    feed.sort(key=lambda f: (-(f["t"] or 0), 0 if f["k"] == "sell" else 1, f["id"]))
    booked = [r for r in rows if r["pk"] and r["pk"]["state"] in BOOKED]
    for r in booked:                                      # the doc's euros, else the paper fees on its multiple (peak.py writes both)
        pk = r["pk"]
        if pk["eur"] is None:
            pk["eur"] = round(M.pos_value(r["p"], 1.0, pk["x"]), 2)
        if pk["x6"] is not None and pk["eur6"] is None:
            pk["eur6"] = round(M.pos_value(r["p"], 1.0, pk["x6"]), 2)
        if pk["lo"] is not None and pk["eurLo"] is None:
            pk["eurLo"] = round(M.pos_value(r["p"], 1.0, pk["lo"]), 2)
        pk["rawWhy"] = raw_reason(pk)                      # the raw top close, unfiltered, and what selling there would have given
        pk["eurRaw"] = round(M.pos_value(r["p"], 1.0, pk["rawX"]), 2) if pk["rawWhy"] else pk["eur"]
    six = [r for r in booked if r["pk"]["x6"] is not None]
    best = _stats([(r["ticket"], r["pk"]["eur"]) for r in booked])
    six_st = _stats([(r["ticket"], r["pk"]["eur6"]) for r in six])
    unit = sum(1 for r in rows if r["pk"] and r["pk"]["state"] == "unit")
    counts = {"M": len(rows), "priced": len(booked), "est": sum(1 for r in booked if r["pk"]["state"] == "est"),
              "m15": sum(1 for r in booked if r["pk"]["state"] == "ok" and r["pk"]["src"] == "m15"), "unit": unit,
              "waiting": len(rows) - len(booked) - unit, "open": sum(1 for r in rows if r["windowOpen"] and not (r["pk"] and r["pk"]["state"] in BOOKED))}
    closed_rows = [r for r in rows if not r["open"]]
    top = max(closed_rows, key=lambda r: (r["pnl"], r["t"]), default=None)
    pts, run = [], 0.0
    for r in sorted(booked, key=lambda r: (r["pk"]["end"] or r["end"], r["id"])):     # the dashed line: cumulative by window end
        run += r["pk"]["eur"] - r["ticket"]
        pts.append((r["pk"]["end"] or r["end"], round(run, 2)))
    same = lambda rs: round(sum(r["pnl"] for r in rs), 2) if rs else None
    old_n, old_bk = 0, []                                 # the trades before the restart: their best within 6 h, shown apart (old_trades)
    for pid, p in pos.items():
        if M.in_account(p, since) or p.get("grp") not in M.PAPER_GROUPS:
            continue
        old_n += 1
        pk = docs.get(pid)
        if not pk or pk["state"] not in BOOKED:
            continue
        ticket = num(p.get("ticket")) or 0.0
        eur = pk["eur"] if pk["eur"] is not None else round(M.pos_value(p, 1.0, pk["x"]), 2)
        back = sum(num(e.get("eur")) or 0 for e in p.get("_exits") or [] if isinstance(e, dict))
        old_bk.append((ticket, eur, round(back - ticket, 2)))
    old = {"n": old_n, "priced": len(old_bk), "best": _stats([(t, e) for t, e, _ in old_bk]),
           "same": round(sum(x for _, _, x in old_bk), 2) if old_bk else None}
    return {"since": since, "err": None, "old": old, "stop": stop, "best": best, "six": six_st, "counts": counts, "feed": feed[:FEED_MAX], "feedN": len(feed),
            "rows": rows, "bestTrade": {"pnl": top["pnl"], "sym": top["sym"]} if top else None, "peakPts": pts,
            "sameBest": same(booked), "sameSix": same(six), "noPx": sum(1 for r in rows if r["open"] and r["value"] is None),
            "noloss": noloss_data(rows)}


def nl_priced(r):
    """Whether a trade row has both ends of its 6 hours: a booked best (eur) and a booked low (eurLo, peak.py PEAK_V 2)."""
    pk = r.get("pk")
    return bool(pk) and pk["state"] in BOOKED and pk["x"] is not None and pk["eur"] is not None and pk["lo"] is not None and pk["eurLo"] is not None


def nl_pct(r, hi):
    """A priced trade sold at its best (hi) or its lowest close within 6 h: what came back over the ticket, minus 1 (after the paper
    fees, as the real result's %)."""
    v = r["pk"]["eur"] if hi else r["pk"]["eurLo"]
    return v / r["ticket"] - 1.0 if r["ticket"] > 0 else 0.0


def _exit_t(r, why):
    """The time of a row's first sale for this reason (the candle that sold it, else the run's), or None."""
    ts = [num(e.get("at")) or num(e.get("t")) for e in r["status"] if e.get("why") == why]
    ts = [t for t in ts if t]
    return min(ts) if ts else None


def nl_stats(rs, why=None, over=1.0):
    """Without the stop-loss, for a set of trade rows: "of" trades, "n" priced (both ends booked), and over the priced ones "best" (the
    P/L had each been sold at its best close within 6 h), "worst" (at its lowest), "real" (what the rule made with them), "raw" (at the
    raw top close, unfiltered, where it differs; "rawN" of them could not have been sold there: one candle, a dead pool, a level over
    the cap), "bestP" and
    "loP" (the best trade at its best and the worst at its lowest, as a share of its ticket after the paper fees, like the real
    result's %) and, with why, "back": how many had their best above over times the entry after that sale (the stop: back above the
    entry; the take-profit: higher than where it sold)."""
    pr = [r for r in rs if nl_priced(r)]
    out = {"of": len(rs), "n": len(pr), "best": None, "worst": None, "real": None, "bestP": None, "loP": None, "back": None, "raw": None, "rawN": 0}
    if not pr:
        return out
    eraw = lambda r: r["pk"]["eurRaw"] if r["pk"].get("eurRaw") is not None else r["pk"]["eur"]
    out.update(raw=round(sum(eraw(r) - r["ticket"] for r in pr), 2), rawN=sum(1 for r in pr if r["pk"].get("rawWhy")))
    out.update(best=round(sum(r["pk"]["eur"] - r["ticket"] for r in pr), 2), worst=round(sum(r["pk"]["eurLo"] - r["ticket"] for r in pr), 2),
               real=round(sum(r["pnl"] for r in pr), 2), bestP=max(nl_pct(r, True) for r in pr), loP=min(nl_pct(r, False) for r in pr))
    if why:
        sold = [(r, _exit_t(r, why)) for r in pr]
        out["back"] = sum(1 for r, t in sold if t and r["pk"]["x"] > over and r["pk"]["at"] is not None and r["pk"]["at"] > t)
    return out


def noloss_data(rows):
    """The block "Without the stop-loss" from the trade rows: "stop" (sold at the stop), "tp" (sold at the take-profit), "all" (every
    trade since the restart) and "list" (the rows whose 6-hour window has closed, newest first, at most NL_MAX) with "listN" (all of
    them); "open": the trades still inside their first 6 hours (counted nowhere yet). All three count only trades whose 6 hours are
    over ("of"), and sum only the priced ones ("n")."""
    done = [r for r in rows if not r["windowOpen"] or nl_priced(r)]     # the trades whose 6 hours are over
    stop = [r for r in done if any(e.get("why") == "stop" for e in r["status"])]
    tp = [r for r in done if any(e.get("why") == "tp" for e in r["status"])]
    return {"stop": nl_stats(stop, "stop", 1.0), "tp": nl_stats(tp, "tp", 1.0 + M.HOLD_TP), "all": nl_stats(done),
            "list": done[:NL_MAX], "listN": len(done), "open": len(rows) - len(done)}


# ---------------------------------------------------------------- the parts of the page
def _acct(D):
    P = D.get("paper") or {}
    A = P.get("acct2")
    if not isinstance(A, dict):
        A = load(D.get("dir") or "", D.get("now") or 0, since=P.get("since"))
        P["acct2"] = A
    return A


def balance_line(D, A):
    """The paper account's P/L after every run since the restart (memecurve "paper"), 120 px high, break-even dashed. The page's own
    numbers only; drawn with a stretched viewBox and strokes that do not scale, so it fills any width without scrolling."""
    since = A.get("since") or 0
    pts = [(num(c.get("t")), num(c["paper"].get("pnl"))) for c in D.get("curve") or [] if isinstance(c, dict) and num(c.get("t")) and num(c.get("t")) >= since
           and isinstance(c.get("paper"), dict) and num(c["paper"].get("pnl")) is not None]
    pts.sort()
    if len(pts) < 2:
        return '<div class="pa-line pa-line-empty"><span>the balance line starts after two runs</span></div>'
    W, H, pad = 600.0, 102.0, 6.0
    t0, t1 = pts[0][0], pts[-1][0]
    vs = [v for _, v in pts] + [0.0]
    lo, hi = min(vs), max(vs)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    X = lambda t: (t - t0) / ((t1 - t0) or 1) * W
    Y = lambda v: pad + (hi - v) / (hi - lo) * (H - 2 * pad)
    xy = [(X(t), Y(v)) for t, v in pts]
    path = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", x, y) for i, (x, y) in enumerate(xy))
    cls = tone(pts[-1][1]) or "flat"
    y0 = Y(0.0)
    zl = zero_label(xy, y0, W, H)
    lab = ('<span class="zl" style="%s:0;top:%.0fpx">break-even</span>' % (zl[0], zl[1])) if zl else ""
    return ('<div class="pa-line %s" role="img" aria-label="Paper account profit or loss after every run since the restart, now %s">'
            '<svg viewBox="0 0 %d %d" preserveAspectRatio="none"><line class="z" x1="0" y1="%.1f" x2="%d" y2="%.1f"/>'
            '<path class="a" d="%s L%.1f %.1f L0 %.1f Z"/><path class="l" d="%s"/></svg>'
            '%s<span class="st">%s</span><span class="en">now %s</span></div>') % (
        cls, E(eur(pts[-1][1], True)), W, H, y0, W, y0, path, W, y0, y0, path, lab, E(mday(t0)), E(hhmm(pts[-1][0])))


def _crosses(xy, xa, xb, ya, yb):
    """Whether the polyline xy (sorted by x) passes through the box [xa, xb] x [ya, yb]."""
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        if x2 < xa or x1 > xb:
            continue
        at = lambda x: y1 if x2 == x1 else y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        ys = (at(max(x1, xa)), at(min(x2, xb)))
        if min(ys) <= yb and max(ys) >= ya:
            return True
    return False


def zero_label(xy, y0, W, H):
    """Where the balance line's "break-even" label goes: (side, top px). The right end first, then the left end, each above and
    then below the zero line, wherever the line does not pass (the label is about 62 px wide, up to a quarter of a phone's line).
    None when the line passes every place: the dashed zero line then stands alone."""
    for side, xa, xb in (("right", 0.74 * W, W), ("left", 0.0, 0.26 * W)):
        for top in ((y0 - 15) if y0 >= 15 else None, min(H - 13, y0 + 3)):
            if top is not None and not _crosses(xy, xa, xb, top - 1, top + 14):
                return side, round(top)
    return None


def header(D, A):
    """The survival header: the stop-loss account's P/L since the restart in big type, its rate on what went in, the balance line
    and four tiles. The numbers are M.paper_account's, nothing else."""
    R = _report()
    a = A["stop"]
    since = A.get("since")
    rate = (a["pnl"] / a["invested"]) if a["invested"] else None
    wr = a.get("winRate")
    bt = A.get("bestTrade")
    no_px = int(A.get("noPx") or 0)
    tiles = [("Win rate", ("%.1f%%" % (100 * wr)) if wr is not None else "–", ("%d won · %d lost" % (a["won"], a["lost"])) if a["nClosed"] else "nothing sold yet", ""),
             ("Trades", "%d|closed" % a["nClosed"], ("%d open · %d top pick%s · %d new launch%s" % (
                 a["nOpen"], a["nTop"], "" if a["nTop"] == 1 else "s", a["nYoung"], "" if a["nYoung"] == 1 else "es")) if a["nOpen"] else "0 open · nothing held", ""),
             ("Best trade", eur(bt["pnl"], True) if bt else "–", bt["sym"] if bt else "nothing sold yet", tone(bt["pnl"]) if bt else ""),
             ("Open value", eur(a["open"]), ("if all sold now" + ((" · %d with no price yet, counted at 0" % no_px) if no_px else "")) if a["nOpen"] else "nothing held", "")]
    when = mday(since) if since else ""
    info = ("profit/loss since the restart%s: what came back plus what the open positions would fetch now, minus what went in, after the "
            "paper fees (1%%, at least 0.10 per trade). The rule that runs: the top pick for %s, the first %d new launches for %s each, sold at "
            "+%d%%, at %s%% or after %d hours. Fake money, nothing is bought for real.") % (
        (" on %s" % R.fmt_dt(since)) if since else "", R.fmt_eur(M.TOP_TICKET), M.YOUNG_BUY_N, R.fmt_eur(M.YOUNG_TICKET), round(100 * M.HOLD_TP),
        MINUS + str(round(100 * M.HOLD_STOP)), round(M.HOLD_MAX_H))
    return ('<div class="pa-hero" data-pa="header"><div class="pl"><div class="pa-eyebrow"><span>Stop-loss account</span><span class="chip neutral">the rule</span>'
            '<span>fake money</span></div><div class="pa-k">P/L since %s</div><div class="pa-big %s" data-pa-v="pnl">%s</div>'
            '<div class="pa-rate %s" data-pa-v="rate">%s</div>'
            '<details class="pa-i"><summary aria-label="How this is counted"><span class="dt-only">ⓘ how this is counted</span><span class="ph-only">ⓘ</span></summary><p>%s</p></details></div>%s'
            '<div class="pa-tiles">%s</div></div>') % (
        E(when or "the restart"), tone(a["pnl"]), E(eur(a["pnl"], True)), tone(rate),
        ('%s<span> on %s invested</span>' % (E(pct1(rate)), E(eur(a["invested"])))) if rate is not None else "<span>nothing bought yet</span>", E(info),
        balance_line(D, A),
        "".join('<div class="pa-tile" data-pa-tile="%s"><span class="k">%s</span><span class="v %s">%s</span><span class="s">%s</span></div>' % (
            E(k.lower().replace(" ", "-")), E(k), c, _tile_v(v), E(s)) for k, v, s, c in tiles))


def _tile_v(v):
    """A tile's value; "403|closed" puts the word in small type beside the count."""
    if "|" not in v:
        return E(v)
    a, b = v.split("|", 1)
    return '%s<small> %s</small>' % (E(a), E(b))


def _wl_bar(won, lost):
    n = won + lost
    if not n:
        return ""
    return '<div class="pa-wl" role="img" aria-label="%d won, %d lost"><i style="width:%.1f%%"></i></div>' % (won, lost, 100.0 * won / n)


def _cat(cls, key, title, chip, pnl, rate_txt, figs, same, how):
    """One category card. A wide screen shows the big P/L, its rate, the figures (invested, back, ...), the won/lost bar and the
    counts. A phone (820 px or less) keeps the big P/L, its rate and the "same trades" line in view; the figures move into the ⓘ
    fold (a second copy that only a phone shows), so the three cards stay short. pnl None: the category is still empty."""
    vr = ('<div class="vr"><div class="v %s">%s</div><div class="r">%s</div></div>' % (tone(pnl), E(eur(pnl, True)), E(rate_txt)) if pnl is not None
          else '<div class="vr"><div class="v muted">–</div><div class="r">%s</div></div>' % E(rate_txt))
    summ = '<span class="dt-only">ⓘ how</span><span class="ph-only">ⓘ figures and how</span>' if figs else "ⓘ how"
    return ('<div class="pa-cat %s" data-pa="%s"><div class="head"><span class="t">%s</span>%s</div>%s%s%s'
            '<details class="pa-i"><summary>%s</summary>%s<p>%s</p></details></div>') % (
        cls, key, E(title), chip, vr, ('<div class="det">%s</div>' % figs) if figs else "", same, summ, ('<div class="ph">%s</div>' % figs) if figs else "", E(how))


def _figs(kv, won, lost, foot):
    """A category's figures: the key numbers, the won/lost bar and the counts line."""
    return '<dl>%s</dl>%s<div class="foot">%s</div>' % ("".join('<div><dt>%s</dt><dd>%s</dd></div>' % (E(k), E(v)) for k, v in kv), _wl_bar(won, lost), E(foot))


def strips(D, A):
    """The three categories side by side (stacked on a phone): the stop-loss account (the rule), best within 6 h and held 6 h then
    sold (both hindsight, with the stop-loss result of the same positions beside them so the three compare like for like)."""
    a, b, s, c = A["stop"], A["best"], A["six"], A["counts"]
    rate = (a["pnl"] / a["invested"]) if a["invested"] else None
    k1 = [("invested", eur(a["invested"])), ("back", eur(a["back"])), ("open", eur(a["open"]))]
    wl1 = ("%d won · %d lost" % (a["won"], a["lost"])) if a["nClosed"] else "nothing sold yet"
    how1 = ("The rule that really runs: each paper position is sold at +%d%%, at %s%% or after %d hours, whichever comes first. Open positions count "
            "at the last price, after fees; one with no price yet counts 0.") % (round(100 * M.HOLD_TP), MINUS + str(round(100 * M.HOLD_STOP)), round(M.HOLD_MAX_H))
    cat1 = _cat("rule", "stop", "Stop-loss account", '<span class="chip neutral">the rule</span>', a["pnl"],
                ("%s on %s invested" % (pct1(rate), eur(a["invested"]))) if rate is not None else "nothing bought yet",
                _figs(k1, a["won"], a["lost"], wl1), "", how1)
    chip = '<span class="chip warn">hindsight, not a trading rule</span>'

    def hind(key, title, st, same, howto, foot):
        if not st["n"]:
            return _cat(key, key, title, chip, None, foot, "", "", howto)
        r = st["pnl"] / st["invested"] if st["invested"] else None
        kv = [("invested", eur(st["invested"])), ("back", eur(st["back"])), ("trades", str(st["n"]))]
        line = ('<div class="same">same %d trades under the stop-loss rule: <b class="%s">%s</b></div>' % (st["n"], tone(same), E(eur(same, True)))
                if same is not None else "")
        return _cat(key, key, title, chip, st["pnl"], ("%s on %s invested" % (pct1(r), eur(st["invested"]))) if r is not None else "",
                    _figs(kv, st["won"], st["lost"], "%d won · %d lost · %s" % (st["won"], st["lost"], foot)), line, howto)
    priced = "priced %d of %d · %d waiting · %d estimated · %d on 15-min candles" % (c["priced"], c["M"], c["waiting"], c["est"], c["m15"]) + (
        (" · %d not booked (price unit)" % c["unit"]) if c["unit"] else "")
    how2 = ("Hindsight: every paper position since the restart, open or sold, booked at its highest minute-candle close within 6 hours after the "
            "entry, measured on the pool it was bought on. Wicks never count; dust candles, a dead pool, a collapse and spikes the next close did "
            "not hold are filtered out. Estimates and 15-minute candles are lower bounds. No rule can know the top in advance.%s") % (
        (" %d windows are still open." % c["open"]) if c["open"] else "")
    how3 = ("Hindsight: the same positions sold at the last minute-candle close 6 hours after the entry, and at 0 when the pool died inside "
            "the window. Only positions whose 6-hour price is known count here.")
    cat2 = hind("peak", "Best within 6 h", b, A.get("sameBest"), how2, priced)
    cat3 = hind("six", "Held 6 h, then sold", s, A.get("sameSix"), how3, "%d of %d trades" % (s["n"], c["M"]) if s["n"] else "no 6-hour price known yet")
    return '<div class="pa-cats">%s%s%s</div>' % (cat1, cat2, cat3)


def pct_f(v):
    """A share as a move with thousands separators: 8.4 -> +840%, -0.32 -> −32%, -1 -> −100%, 839 -> +83,900%."""
    v = num(v)
    if v is None:
        return "–"
    p = 100 * v
    if abs(p) < 0.05:
        return "0%"
    s = "{:+,.0f}%".format(p) if abs(p) >= 9.95 else "%+.1f%%" % p
    return (MINUS + s[1:]) if s[0] == "-" else s


def _rng(worst, best, real, who):
    """The range bar of a tile: from the sum at the lowest closes (red, left of break-even) to the sum at the best closes (green,
    right of it) on one scale, with a dot where the rule really ended."""
    m = max(abs(worst), abs(best), abs(real), 0.01)
    pos = lambda v: 50.0 + 50.0 * v / m
    seg = lambda a, b, c: ('<i class="%s" style="left:%.1f%%;width:%.1f%%"></i>' % (c, pos(a), pos(b) - pos(a))) if b > a else ""
    return ('<div class="nl-rng" role="img" aria-label="%s">%s%s<i class="z"></i><b style="left:%.1f%%"></b></div>') % (
        E("at the lowest closes %s, at the best %s, %s %s" % (eur(worst, True), eur(best, True), who, eur(real, True))),
        seg(worst, min(best, 0.0), "dn"), seg(max(worst, 0.0), best, "up"), pos(real))


def _nl_tile(key, title, st, who, back_txt, none_txt):
    """One tile of the block: max loss (left) and max profit (right) as sums with the worst and the best move, the range bar with
    the rule's dot, and one count line."""
    cnt = ("%d trade%s" % (st["n"], "" if st["n"] == 1 else "s")) if st["n"] == st["of"] else "priced %d of %d" % (st["n"], st["of"])
    if not st["of"]:
        return ('<div class="nl-tile %s" data-nl="%s"><div class="nl-t"><span>%s</span></div><p class="nl-none">%s</p></div>') % (key, key, E(title), E(none_txt))
    if not st["n"]:
        return ('<div class="nl-tile %s" data-nl="%s"><div class="nl-t"><span>%s</span><b>%s</b></div><p class="nl-none">priced after the next scans</p></div>') % (
            key, key, E(title), E(cnt))
    back = ('<span>%s</span>' % E(back_txt % (st["back"], st["n"]))) if st["back"] is not None else ""
    return ('<div class="nl-tile %s" data-nl="%s"><div class="nl-t"><span>%s</span><b>%s</b></div>'
            '<div class="nl-lh"><div class="lo"><span class="k">max loss</span><span class="v %s" data-nl-v="worst">%s</span><span class="p">worst trade %s</span></div>'
            '<div class="hi"><span class="k">max profit</span><span class="v %s" data-nl-v="best">%s</span><span class="p">best trade %s</span></div></div>'
            '%s<div class="nl-f"><span class="nl-dot"><i></i>%s <b class="%s" data-nl-v="real">%s</b></span>%s</div></div>') % (
        key, key, E(title), E(cnt), tone(st["worst"]), E(eur(st["worst"], True)), E(pct_f(st["loP"])), tone(st["best"]), E(eur(st["best"], True)),
        E(pct_f(st["bestP"])), _rng(st["worst"], st["best"], st["real"], who), E(who), tone(st["real"]), E(eur(st["real"], True)), back)


def _nl_cell(r, hi):
    """A per-trade cell: the max profit (hi) or the max loss as % of the ticket after the fees (as the result), and when it came
    after the entry."""
    pk = r["pk"]
    if not nl_priced(r):
        word = "not booked" if pk and pk["state"] == "unit" else "waiting"
        return '<td class="%s"><span class="muted">%s</span></td>' % ("hi" if hi else "lo", word)
    v, t = nl_pct(r, hi), (pk["at"] if hi else pk["loAt"])
    when = mins_txt((t - (pk["entryAt"] or r["tBuy"])) if t is not None else None)
    c = tone(v)
    raw = ""
    if hi and pk.get("rawWhy"):                           # the raw top beside the filtered best, and why it was not sellable
        raw = '<small class="nl-raw" data-nl-raw>raw top %s %s · %s</small>' % (E(mult(pk["rawX"])), E(eur(pk["eurRaw"] - r["ticket"], True)), E(pk["rawWhy"]))
    return '<td class="%s"><span%s>%s</span><small>%s</small>%s</td>' % ("hi" if hi else "lo", (' class="%s"' % c) if c else "", E(pct_f(v)),
                                                                         E(("at " + when) if when else ""), raw)


def _nl_rows(rows, R):
    out = []
    for r in rows:
        why = ", ".join(R.exit_label(e, r["p"]) for e in r["status"]) or ("open" if r["open"] else "sold")
        pk = r["pk"] if nl_priced(r) else None
        lab = ("estimate" if pk["state"] == "est" else ("15-min candles" if pk["src"] == "m15" else "")) if pk else ""
        out.append('<tr><td class="c"><strong>%s</strong><small>%s</small></td><td class="r"><span class="%s">%s</span><small>%s</small></td>%s%s</tr>' % (
            E(r["sym"]), E(" · ".join(x for x in (why, R.fmt_dt(r["tBuy"], True), lab) if x)), tone(r["pnl"]), E(eur(r["pnl"], True)),
            E(pct_move(r["pct"])) if r["pct"] is not None else "no price", _nl_cell(r, True), _nl_cell(r, False)))
    return "".join(out)


def _nl_table(rows, R):
    return ('<div class="tbl nl-tbl"><table><thead><tr><th>coin</th><th class="n">result</th><th class="n">max profit</th><th class="n">max loss</th></tr></thead>'
            '<tbody>%s</tbody></table></div>') % _nl_rows(rows, R)


def noloss(D, A):
    """Without the stop-loss (hindsight): two tiles (the trades sold at the stop, the trades sold at the take-profit: max loss and max
    profit within 6 h as sums with the worst and best trade, the range bar with what the rule made, one count), one line for all
    trades, and the per-trade list (newest first, NL_SHOWN rows, the rest up to NL_MAX in a fold inside it). Almost no text: the how
    sits behind the ⓘ."""
    R = _report()
    N = A.get("noloss") or noloss_data([])
    st, tp, al = N["stop"], N["tp"], N["all"]
    stop_pct, tp_pct = MINUS + str(round(100 * M.HOLD_STOP)), "+" + format(round(100 * M.HOLD_TP), ",")
    if not al["of"]:
        cnt = "no 6 hours over yet"
    elif al["n"] < al["of"]:
        cnt = "priced %d of %d" % (al["n"], al["of"])
    else:
        cnt = "%d trades" % al["n"]
    if N.get("open"):
        cnt += " · %d inside their 6 h" % N["open"]
    tiles = (_nl_tile("stop", "Sold at %s%% (stop)" % stop_pct, st, "the stop made", "%d of %d back above the entry", "no trade sold at the stop yet")
             + _nl_tile("tp", "Sold at %s%% (take-profit)" % tp_pct, tp, "the take-profit made", "%d of %d rose further", "no trade sold at the take-profit yet"))
    if al["n"]:
        raw = ('<span class="raw">at the raw top <b class="%s" data-nl-v="raw">%s</b><small>%s</small></span>' % (
            tone(al["raw"]), E(eur(al["raw"], True)), E("%d not sellable there" % al["rawN"]))) if al.get("rawN") else ""
        line = ('<div class="nl-all" data-nl="all"><span class="k">%s</span><span>at the best <b class="%s" data-nl-v="best">%s</b></span>%s'
                '<span>at the lowest <b class="%s" data-nl-v="worst">%s</b></span><span>the rule made <b class="%s" data-nl-v="real">%s</b></span></div>') % (
            E("All %d trades, sold each" % al["n"] if al["n"] == al["of"] else "All %d priced trades, sold each" % al["n"]), tone(al["best"]), E(eur(al["best"], True)),
            raw, tone(al["worst"]), E(eur(al["worst"], True)), tone(al["real"]), E(eur(al["real"], True)))
    else:
        line = ""
    lst = N.get("list") or []
    if lst:
        more = lst[NL_SHOWN:]
        rest = N.get("listN", len(lst)) - len(lst)
        inner = ('<details class="fold-lite pa-f"><summary>Older trades (%d)</summary>%s%s</details>' % (
            len(more) + rest, _nl_table(more, R), ('<p class="note">The newest %d are here; %d older ones are not shown.</p>' % (NL_MAX, rest)) if rest else "")) if more else ""
        fold = '<details class="fold-lite pa-f nl-list"><summary>Per trade (%d)</summary>%s%s</details>' % (N.get("listN", len(lst)), _nl_table(lst[:NL_SHOWN], R), inner)
    else:
        fold = ""
    how = ("Hindsight, not a rule that ran: each paper trade since the restart, sold at its highest (max profit) or its lowest (max loss) minute-candle "
           "close within 6 hours after the entry, on the pool it was bought on, after the paper fees. Wicks, dust candles and one-candle glitches do not "
           "count; a pool that died counts as a total loss. The dot is what the rule (stop at %s%%, take-profit at %s%%, 6 hours) really made with "
           "the same trades; 'back above the entry' and 'rose further' count the trades whose best came after that sale. The raw top is the highest "
           "close of all, unfiltered, shown where it differs: one candle, dust volume, a dead pool or a level over the cap could not be sold "
           "there. Estimates and 15-minute "
           "candles are bounds. Nobody knows the top or the bottom in advance. Fake money, nothing is bought "
           "for real.") % (stop_pct, tp_pct)
    return ('<div class="pa-nl" data-pa="noloss"><div class="nl-head"><h3>Without the stop-loss</h3><span class="chip warn">hindsight</span>'
            '<span class="nl-cnt">%s</span></div><div class="nl-tiles">%s</div>%s%s<details class="pa-i"><summary>ⓘ how</summary><p>%s</p></details></div>') % (
        E(cnt), tiles, line, fold, E(how))


def feed_row(f, R, cls=""):
    grp = "new launch" if f.get("grp") == "young" else "top pick"
    c = (" " + cls) if cls else ""
    if f["k"] == "buy":
        return '<li class="pa-ev b%s"><span class="tm">%s</span><i></i><span class="tx"><b class="act">BOUGHT</b> <b>%s</b> · %s</span><span class="am">%s</span></li>' % (
            c, E(hhmm(f["t"])), E(f["sym"]), E(grp), E(R.fmt_eur(f["ticket"])))
    why = FEED_WHY.get(f["why"], f["why"])
    move = (" " + pct_move(f["move"])) if f.get("move") is not None else ""
    return '<li class="pa-ev s %s%s"><span class="tm">%s</span><i></i><span class="tx"><b class="act">SOLD</b> <b>%s</b> · %s%s%s</span><span class="am">%s</span></li>' % (
        tone(f["eur"]) or "flat", c, E(hhmm(f["t"])), E(f["sym"]), E(why), E(move), " · half" if f.get("half") else "", E(eur(f["eur"], True)))


def _feed_list(items, R, day0=None, cls=""):
    """Feed rows with a date header wherever the day changes (day0: the day of the row before them); cls marks rows that only a
    wide screen ("ex") or only a phone ("ph") shows."""
    out, day = [], day0
    for f in items:
        dl = day_label(f["t"])
        if dl != day:
            out.append('<li class="pa-day%s">%s</li>' % ((" " + cls) if cls else "", E(dl)))
            day = dl
        out.append(feed_row(f, R, cls))
    return "".join(out), day


def feed(D, A):
    """Every paper buy and sale since the restart, newest first: 20 rows on a wide screen and 6 on a phone, the rest (up to
    FEED_MAX) behind a fold. Rows 7-20 are in the page twice: in the list (wide screens only) and at the top of the fold (phones
    only). Static per build (it changes only at the trader step); the live line below the head shows the trader's latest line
    while a scan runs."""
    R = _report()
    items = A.get("feed") or []
    newest = items[0]["t"] if items else None
    head = ('<div class="head"><h3>Activity</h3><span class="upd">updated each scan%s</span></div>'
            '<p class="pa-livel" data-acct-live hidden><i aria-hidden="true"></i><span></span></p>') % E((" · newest " + hhmm(newest)) if newest else "")
    if not items:
        return '<div class="pa-feed" data-pa="feed">%s<p class="note">No paper trade since the restart yet.</p></div>' % head
    first, day = _feed_list(items[:FEED_PHONE], R)
    mid_items = items[FEED_PHONE:FEED_SHOWN]
    mid, day_mid = _feed_list(mid_items, R, day, "ex")
    rest = items[FEED_SHOWN:]
    more = ""
    if mid_items or rest:
        ph, _ = _feed_list(mid_items, R, day, "ph")
        tail, _ = _feed_list(rest, R, day_mid)
        n_all = A.get("feedN") or len(items)
        more = '<details class="fold-lite pa-more pa-f%s"><summary>All since %s (%d%s)</summary><ol class="pa-evs">%s%s</ol></details>' % (
            "" if rest else " ph-only", E(mday(A.get("since"))), n_all, (", newest %d here" % FEED_MAX) if n_all > FEED_MAX else "", ph, tail)
    return '<div class="pa-feed" data-pa="feed">%s<ol class="pa-evs two">%s%s</ol>%s</div>' % (head, first, mid, more)


def _peak_cells(r):
    """The two hindsight cells of a trade: best in 6 h (multiple, minutes after the entry, P/L) and at 6 h (multiple, P/L), plus
    the filtered chip with the first cut reason."""
    pk = r["pk"]
    if not pk or pk["state"] == "waiting":
        word = "window open" if r["windowOpen"] else "waiting"
        return '<span class="muted">%s</span>' % word, '<span class="muted">%s</span>' % word, ""
    if pk["state"] == "unit":
        return '<span class="muted">not booked</span>', '<span class="muted">–</span>', '<span class="chip warn">price unit mismatch</span>'
    lab = " · estimate" if pk["state"] == "est" else (" · 15-min candles" if pk["src"] == "m15" else "")
    at = mins_txt((pk["at"] - (pk["entryAt"] or r["tBuy"])) if pk["at"] is not None else None)
    at = ("at " + at) if at else ""
    p_best = pk["eur"] - r["ticket"]
    best = '<span class="x %s">%s</span><small>%s</small>' % (tone(p_best), E(mult(pk["x"])), E(" · ".join(x for x in (at, eur(p_best, True)) if x) + lab))
    if pk["x6"] is not None and pk["eur6"] is not None:
        p6 = pk["eur6"] - r["ticket"]
        six = '<span class="x %s">%s</span><small>%s</small>' % (tone(p6), E(mult(pk["x6"])), E(eur(p6, True)))
    else:
        six = '<span class="muted">unknown</span>'
    chip = ""
    if pk["cut"]:
        why = cut_reason(pk["cut"])
        raw = pk["rawX"]
        chip = '<span class="chip warn" data-pa="filtered">%s</span>' % E(("%s ignored: %s" % (mult(raw), why)) if raw is not None and pk["x"] is not None and raw > 1.05 * pk["x"]
                                                                        else "filtered: %s" % why)
    return best, six, chip


def trade_row(r, R):
    p = r["p"]
    if r["open"]:
        st = '<span class="chip neutral">open</span>'
        held = ""
    else:
        st = '<span class="chip %s">%s</span>' % ("good" if r["pnl"] > 0 else "bad", E(", ".join(R.exit_label(e, p) for e in r["status"]) or "sold"))
        held = held_txt((r["exitT"] or 0) - r["t"]) if r["exitT"] else ""
    best, six, chip = _peak_cells(r)
    res = '<span class="%s">%s</span>' % (tone(r["pnl"]), E(eur(r["pnl"], True))) if r["pnl"] is not None else "–"
    got = (r["back"] + (r["value"] or 0)) if r["open"] else r["back"]
    return ('<tr><td class="c"><strong>%s</strong>%s<small>%s · %s</small></td><td class="p %s">%s</td><td class="m">%s<small>%s → %s</small></td>'
            '<td class="w">%s<small>%s</small></td><td class="h h1">%s%s</td><td class="h h2">%s</td></tr>') % (
        E(r["sym"]), R.name_html(r["sym"], r["name"]), E(R.group_tag(p)), E(R.fmt_dt(r["tBuy"], True)), tone(r["pct"]), E(pct_move(r["pct"])) if r["pct"] is not None else "no price",
        res, E(format(r["ticket"], ",.2f")), E(format(got, ",.2f")) if (got is not None and not (r["open"] and r["value"] is None)) else "–",
        st, E(("held " + held) if held else ("open since " + R.fmt_dt(r["tBuy"], True) if r["open"] else "")), best, chip, six)


def _table(rows, R):
    if not rows:
        return '<div class="empty">Nothing here yet.</div>'
    return ('<div class="tbl pa-tbl"><table><thead><tr><th>coin</th><th class="n">%%</th><th class="n">result</th><th>sold because</th>'
            '<th>best in 6 h (hindsight)</th><th>at 6 h (hindsight)</th></tr></thead><tbody>%s</tbody></table></div>') % "".join(trade_row(r, R) for r in rows)


def trades(D, A):
    """The trades since the restart in four pre-rendered orders (CSS radios, no script): newest (100), top % (50), worst % (50),
    best in 6 h (50). % = what came back over the ticket, minus 1; open positions at the marked price. Closed rows carry the two
    hindsight columns and the filtered chip."""
    R = _report()
    rows = A.get("rows") or []
    closed = [r for r in rows if not r["open"]]
    n_open = len(rows) - len(closed)
    priced = [r for r in rows if r["pct"] is not None]
    peaked = [r for r in rows if r["pk"] and r["pk"]["state"] in BOOKED]
    lists = {"new": rows[:TOP_NEW],
             "top": sorted(priced, key=lambda r: (-r["pct"], -r["t"], r["id"]))[:TOP_N],
             "worst": sorted(priced, key=lambda r: (r["pct"], -r["t"], r["id"]))[:TOP_N],
             "best": sorted(peaked, key=lambda r: (-r["pk"]["x"], -r["t"], r["id"]))[:TOP_N]}
    why = {}
    for r in closed:
        k = ", ".join(R.exit_label({"why": e.get("why")}, r["p"]) for e in r["status"]) or "sold"
        why[k] = why.get(k, 0) + 1
    by = " · ".join("%s (%d)" % (k, n) for k, n in sorted(why.items(), key=lambda kv: (-kv[1], kv[0])))
    note = ('<p class="note">%d sold%s.</p><details class="pa-i"><summary>ⓘ the two hindsight columns</summary><p>Best in 6 h: the highest minute-candle '
            'close within 6 hours after the entry, when it came and what it would have given after fees; at 6 h: the close 6 hours after the entry. Both are '
            'hindsight (filtered for dead pools, dust and spikes the next close did not hold), not a rule that ran. %% = what came back over what was paid; '
            'open positions at the last price.</p></details>') % (len(closed), E((": " + by) if by else ""))
    radios = "".join('<input type="radio" name="pa-sort" id="pa-s-%s"%s>' % (k, " checked" if k == "new" else "") for k, _ in SORTS)
    bar = "".join('<label for="pa-s-%s">%s <span class="cnt">%d</span></label>' % (k, E(t), len(lists[k])) for k, t in SORTS)
    panes = "".join('<div class="pane %s" data-pa-sort="%s">%s</div>' % (k, k, _table(lists[k], R)) for k, _ in SORTS)
    return ('<details class="fold-lite pa-trades pa-f" data-pa="trades"><summary>Top trades · %d closed · %d open</summary>'
            '%s<div class="pa-tt">%s<div class="bar" role="radiogroup" aria-label="Order">%s</div>%s</div></details>') % (
        len(closed), n_open, note, radios, bar, panes)


def old_trades(D):
    """The trades bought before the restart, behind their own fold (as report.py showed them)."""
    R = _report()
    old = (D.get("paper") or {}).get("old") or []
    if not old:
        return ""
    since = (D.get("paper") or {}).get("since")
    note = ("bought before the paper account restarted on %s; not counted above" % R.fmt_dt(since, True)) if since else "bought before the paper account restarted; not counted above"
    o = ((D.get("paper") or {}).get("acct2") or {}).get("old") or {}
    if o.get("priced"):
        b = o["best"]
        hint = ('<p class="note">Best within 6 h (hindsight, not a rule): <b class="%s">%s</b> on %d of %d trades; the same trades as they were sold: '
                '<b class="%s">%s</b></p>') % (tone(b["pnl"]), E(eur(b["pnl"], True)), o["priced"], o["n"], tone(o["same"]), E(eur(o["same"], True)))
    elif o.get("n"):
        hint = '<p class="note">Best within 6 h (hindsight): priced after the next scans.</p>'
    else:
        hint = ""
    return '<details class="fold-lite pa-f"><summary>Before the restart (%d trade%s)</summary>%s%s</details>' % (
        len(old), "" if len(old) == 1 else "s", hint, R.safe("closed trades", lambda: R.closed_fold(old, note)))


def _no_ref(svg):
    """A chart without report.py's "break-even 0.00" text at the left end: the dashed hindsight line starts at 0 there and would
    run through it. The dashed zero line and its 0 tick stay; the legend names it."""
    return re.sub(r'<text class="tick over"[^>]*>[^<]*</text>', "", svg, count=1)


def curve(D, A):
    """report.py's paper curve fold, plus the dashed hindsight line: best within 6 h, cumulative P/L by window end."""
    R = _report()
    since = A.get("since") or 0
    pts = [(num(c["t"]), num(c["paper"].get("pnl"))) for c in D.get("curve") or [] if isinstance(c, dict) and num(c.get("t")) and num(c.get("t")) >= since
           and isinstance(c.get("paper"), dict) and num(c["paper"].get("pnl")) is not None]
    pk = [(t, v) for t, v in A.get("peakPts") or [] if t and t >= since]
    series = [("stop-loss account", "s1", pts)]
    two = len(pk) >= 2
    if two:
        series.append(("best within 6 h (hindsight)", "s2 dash", pk))
    chart = lambda w: (_no_ref if two else (lambda s: s))(R.line_chart(series, 0.0, w, ref_label="break-even", aria_label="Paper account profit or loss since the restart"))
    wide = chart(R.WIDE)
    if not wide:
        body = '<div class="empty">The curve needs two runs since the restart. It shows what came back plus what the open positions would fetch, minus what went in.</div>'
    else:
        legend = ('<div class="legend"><span style="--c:var(--s1)">stop-loss account</span><span class="pa-dleg">best within 6 h (hindsight), by window end</span>'
                  '<span class="pa-zleg">break-even (0)</span></div>' if two else "")
        body = R.chart_box(wide, chart(R.NARROW), legend)
        tbl = lambda head, rows: '<div class="tbl"><table><thead><tr><th>%s</th><th class="n">%s</th></tr></thead><tbody>%s</tbody></table></div>' % (
            head[0], head[1], "".join('<tr><td>%s</td><td class="n">%s</td></tr>' % (R.fmt_dt(t), R.fmt_amt(v, True)) for t, v in rows))
        body += '<details class="pa-f pa-tv"><summary>Table view</summary>%s%s</details>' % (
            tbl(("run", "stop-loss account" if two else "profit/loss"), pts), tbl(("window end", "best within 6 h (hindsight)"), pk) if two else "")
    sub = "profit or loss since the restart after every run: what came back plus what the open positions would fetch, minus what went in, after fees · now %s" % R.fmt_amt(A["stop"]["pnl"], True)
    if two:
        sub += " · dashed: best within 6 h (hindsight), %d windows" % len(pk)
    return '<details class="fold-lite pa-f"><summary>Profit/loss over time</summary><p class="note">%s</p>%s</details>' % (E(sub), body)


def radar_account(D):
    """The radar account's block (page_radarpaper.py), or nothing when that module is not there."""
    try:
        import page_radarpaper as RPP
    except ImportError:
        return ""
    return RPP.section(D)


def exit_grid(D):
    """The exit what-if block (page_exits.py: other stops and targets replayed on the same trades, hindsight), or nothing when that
    module is not there."""
    try:
        import page_exits as PX
    except ImportError:
        return ""
    return PX.section(D)


def section(D, bought=None):
    """The whole account block (see the module doc); every part renders on its own, a broken part shows a notice. The top trades
    (one line while folded) come before the open positions, which can fill several phone screens."""
    R = _report()
    A = _acct(D)
    parts = ["<style>%s</style>" % CSS, R.safe("account", lambda: header(D, A)), R.safe("categories", lambda: strips(D, A)),
             R.safe("without the stop-loss", lambda: noloss(D, A)), R.safe("radar account", lambda: radar_account(D)),
             R.safe("exit what-if", lambda: exit_grid(D)), R.safe("activity", lambda: feed(D, A)), R.safe("trades", lambda: trades(D, A))]
    if bought:
        parts.append(R.safe("open positions", bought))
    parts += [R.safe("closed trades", lambda: old_trades(D)), R.safe("account curve", lambda: curve(D, A))]
    if A.get("err"):
        parts.insert(1, '<p class="note">The hindsight categories could not be read this time (%s); the stop-loss account above is complete.</p>' % E(A["err"]))
    return "".join(parts) + "<script>%s</script>" % JS


# the trader's latest line while a scan runs: only from the live doc the page already holds (report.py's live poll fires
# "memebot-live" while the Office or New launches tab, or the app, is open); no poll of its own, text only (no HTML from the doc)
JS = r"""
(function(){var box=document.querySelector('[data-acct-live]');if(!box||!window.addEventListener)return;var sp=box.querySelector('span');
  window.addEventListener('memebot-live',function(e){var d=(e&&e.detail)||{},doc=d.status&&Array.isArray(d.status.agents)?d.status:d.current,a=null,l='';
    if(d.state==='live'&&doc&&Array.isArray(doc.agents))a=doc.agents.filter(function(x){return x&&x.id==='trader';})[0]||null;
    if(a)l=Array.isArray(a.lines)&&a.lines.length?String(a.lines[a.lines.length-1]):(typeof a.out==='string'?a.out:'');
    l=l.replace(/\s+/g,' ').trim().slice(0,160);box.hidden=!l;
    if(sp)sp.textContent=l?(a.status==='running'?'Trader now: ':'Trader this scan: ')+l:'';});})();
"""

CSS = r"""
/* the paper account (page_account.py): the survival header, three category strips, the activity feed, the trades in four orders */
.pa-hero { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px 18px; display:grid; gap:14px 24px;
  grid-template-columns:minmax(0,1fr) minmax(0,1.25fr); grid-template-areas:"pl line" "tiles tiles"; align-items:start }
.pa-hero .pl { grid-area:pl; display:grid; gap:2px; min-width:0 }
.pa-eyebrow { display:flex; flex-wrap:wrap; gap:4px 8px; align-items:center; font-size:var(--fs-xs); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500 }
.pa-eyebrow .chip { text-transform:none; letter-spacing:0 }
.pa-k { font-size:var(--fs-s); color:var(--fg2); margin-top:6px }
.pa-big { font-size:46px; line-height:1.04; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--fg) }
.pa-big.good, .pa-cat .v.good, .pa-tile .v.good, .pa-rate.good { color:var(--good) } .pa-big.bad, .pa-cat .v.bad, .pa-tile .v.bad, .pa-rate.bad { color:var(--bad) }
.pa-rate { font-size:18px; font-weight:600; font-variant-numeric:tabular-nums; color:var(--fg2) } .pa-rate span { font-size:var(--fs-s); font-weight:400; color:var(--fg2) }
details.pa-i { font-size:var(--fs-s); color:var(--fg2) }
details.pa-i > summary { list-style:none; color:var(--accent); font-size:var(--fs-xs); min-height:44px; padding:0 12px 0 0; display:flex; align-items:center; width:max-content; max-width:100%; cursor:pointer }
details.pa-f > summary { min-height:44px; padding:12px 0; box-sizing:border-box; cursor:pointer } details.pa-f[open] > summary { margin-bottom:0 }
.pa-i .ph-only, .pa-cat .ph, .pa-more.ph-only, .pa-ev.ph, .pa-day.ph { display:none }
details.pa-i > summary::-webkit-details-marker { display:none } details.pa-i p { margin:6px 0 0; max-width:60ch; text-wrap:pretty }
.pa-line { grid-area:line; position:relative; height:120px; min-width:0 }
.pa-line svg { position:absolute; left:0; right:0; top:0; width:100%; height:102px; overflow:visible }
.pa-line .l { fill:none; stroke:var(--muted); stroke-width:2; vector-effect:non-scaling-stroke; stroke-linejoin:round } .pa-line .a { fill:var(--muted); opacity:.10 }
.pa-line.good .l { stroke:var(--good-mark) } .pa-line.good .a { fill:var(--good-mark) } .pa-line.bad .l { stroke:var(--bad-mark) } .pa-line.bad .a { fill:var(--bad-mark) }
.pa-line .z { stroke:var(--muted); stroke-width:1; stroke-dasharray:4 3; vector-effect:non-scaling-stroke }
.pa-line span { position:absolute; font-size:11px; line-height:1; color:var(--muted); background:var(--surface); padding:1px 3px; border-radius:3px }
.pa-line .st { left:0; bottom:0 } .pa-line .en { right:0; bottom:0 }
.pa-line-empty { display:grid; place-items:center } .pa-line-empty span { position:static }
.pa-tiles { grid-area:tiles; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; border-top:1px solid var(--line2); padding-top:12px }
.pa-tile { display:grid; gap:1px; min-width:0; align-content:start } .pa-tile .k { font-size:var(--fs-xs); color:var(--muted) }
.pa-tile .v { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; line-height:1.2; overflow-wrap:anywhere } .pa-tile .v small { font-size:var(--fs-s); font-weight:500; color:var(--fg2) } .pa-tile .s { font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere }
.pa-cats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px }
.pa-cat { --cc:var(--muted); background:var(--surface); border:1px solid var(--line); border-top:4px solid var(--cc); border-radius:12px; padding:12px 16px 14px; display:grid; gap:6px; align-content:start; min-width:0 }
.pa-cat.rule { --cc:var(--accent) } .pa-cat.peak { --cc:var(--warn-mark) } .pa-cat.six { --cc:color-mix(in srgb,var(--warn-mark) 45%,var(--muted)) }
.pa-cat .head { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:4px 8px } .pa-cat .t { font-weight:600; font-size:15px }
.pa-cat .chip { white-space:normal }
.pa-cat .vr { display:grid; gap:6px } .pa-cat .det { display:grid; gap:6px }
.pa-cat .v { font-size:32px; line-height:1.1; font-weight:600; letter-spacing:-.01em; font-variant-numeric:tabular-nums; white-space:nowrap }
.pa-cat .r { font-size:var(--fs-s); color:var(--fg2) }
.pa-cat dl { margin:4px 0 0; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:4px 10px } .pa-cat dl div { min-width:0 }
.pa-cat dt { font-size:var(--fs-xs); color:var(--muted) } .pa-cat dd { margin:0; font-weight:500; font-variant-numeric:tabular-nums; font-size:var(--fs-s); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.pa-wl { height:6px; border-radius:999px; background:color-mix(in srgb,var(--bad-mark) 55%,var(--surface)); overflow:hidden; margin-top:4px } .pa-wl i { display:block; height:100%; background:var(--good-mark) }
.pa-cat .foot { font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.pa-cat .same { font-size:var(--fs-xs); color:var(--fg2); border-top:1px solid var(--line2); padding-top:6px } .pa-cat .same b { font-variant-numeric:tabular-nums }
.pa-cat .same b.good { color:var(--good) } .pa-cat .same b.bad { color:var(--bad) }
.pa-feed { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px; display:grid; gap:4px; min-width:0 }
.pa-feed .head { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:2px 12px } .pa-feed h3 { margin:0 }
.pa-feed .upd { font-size:var(--fs-xs); color:var(--muted) }
.pa-livel { margin:0; display:flex; gap:8px; align-items:baseline; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere }
.pa-livel[hidden] { display:none } .pa-livel i { flex:none; width:8px; height:8px; border-radius:50%; background:var(--bad-mark); animation:opulse 1.6s ease-in-out infinite }
.pa-evs { list-style:none; margin:0; padding:0 }
.pa-ev { display:grid; grid-template-columns:44px 20px minmax(0,1fr) auto; gap:8px; align-items:baseline; padding:7px 0; border-top:1px solid var(--line2); font-size:var(--fs-m) }
.pa-ev .tm { color:var(--muted); font-size:var(--fs-s); font-variant-numeric:tabular-nums }
.pa-ev i { width:20px; height:20px; border-radius:50%; display:inline-grid; place-items:center; font-size:10px; font-style:normal; line-height:1; align-self:start; margin-top:1px;
  background:color-mix(in srgb,var(--accent) 14%,var(--surface)); color:var(--accent) } .pa-ev.b i::before { content:"▲" } .pa-ev.s i::before { content:"▼" }
.pa-ev.s i { background:var(--chip); color:var(--muted) } .pa-ev.good i { background:color-mix(in srgb,var(--good-mark) 18%,var(--surface)); color:var(--good) }
.pa-ev.bad i { background:color-mix(in srgb,var(--bad-mark) 16%,var(--surface)); color:var(--bad) }
.pa-ev .tx { min-width:0; overflow-wrap:anywhere; color:var(--fg2) } .pa-ev .tx b { color:var(--fg); font-weight:600 } .pa-ev .tx b.act { font-size:var(--fs-xs); letter-spacing:.06em; color:var(--muted) }
.pa-ev .am { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--fg2) } .pa-ev.good .am { color:var(--good) } .pa-ev.bad .am { color:var(--bad) }
.pa-day { font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:500; padding:10px 0 2px }
.pa-day:first-child { padding-top:4px } .pa-evs > li { break-inside:avoid } .pa-day { break-after:avoid }
@media (min-width:900px) { .pa-evs.two { columns:2; column-gap:40px } }
.pa-tt { display:grid; gap:10px } .pa-tt > input { position:absolute; opacity:0; pointer-events:none }
.pa-tt .bar { display:flex; flex-wrap:wrap; gap:6px }
.pa-tt .bar label { cursor:pointer; display:inline-flex; align-items:center; gap:6px; min-height:44px; padding:0 14px; border-radius:999px; border:1px solid var(--line);
  background:var(--surface); color:var(--fg2); font-weight:500; font-size:var(--fs-s) } .pa-tt .bar .cnt { font-size:var(--fs-xs); color:var(--muted) }
#pa-s-new:checked ~ .bar label[for="pa-s-new"], #pa-s-top:checked ~ .bar label[for="pa-s-top"], #pa-s-worst:checked ~ .bar label[for="pa-s-worst"],
#pa-s-best:checked ~ .bar label[for="pa-s-best"] { background:color-mix(in srgb,var(--accent) 12%,var(--surface)); border-color:var(--accent); color:var(--accent) }
#pa-s-new:checked ~ .bar label[for="pa-s-new"] .cnt, #pa-s-top:checked ~ .bar label[for="pa-s-top"] .cnt, #pa-s-worst:checked ~ .bar label[for="pa-s-worst"] .cnt,
#pa-s-best:checked ~ .bar label[for="pa-s-best"] .cnt { color:var(--accent) }
.pa-tt > input:focus-visible ~ .bar label { outline:none } #pa-s-new:focus-visible ~ .bar label[for="pa-s-new"], #pa-s-top:focus-visible ~ .bar label[for="pa-s-top"],
#pa-s-worst:focus-visible ~ .bar label[for="pa-s-worst"], #pa-s-best:focus-visible ~ .bar label[for="pa-s-best"] { outline:2px solid var(--accent); outline-offset:2px }
.pa-tt .pane { display:none } #pa-s-new:checked ~ .pane.new, #pa-s-top:checked ~ .pane.top, #pa-s-worst:checked ~ .pane.worst, #pa-s-best:checked ~ .pane.best { display:block }
.pa-tbl td small { display:block; font-size:var(--fs-xs); color:var(--muted); margin-top:1px; font-variant-numeric:tabular-nums }
.pa-tbl td.c { overflow-wrap:anywhere } .pa-tbl td.c strong { font-weight:600 } .pa-tbl td.p { text-align:right; font-weight:600; font-size:15px; font-variant-numeric:tabular-nums; white-space:nowrap }
.pa-tbl td.p.good { color:var(--good) } .pa-tbl td.p.bad { color:var(--bad) } .pa-tbl td.m { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; font-weight:500 }
.pa-tbl td.w .chip { white-space:normal } .pa-tbl td.h .x { font-weight:600; font-variant-numeric:tabular-nums } .pa-tbl td.h .chip { margin-top:4px; white-space:normal }
.pa-tbl th { white-space:normal } .pa-dleg::before { width:16px !important; height:0 !important; border-top:2px dashed var(--s2); background:none !important; border-radius:0 !important; vertical-align:3px !important }
.pa-zleg::before { width:16px !important; height:0 !important; border-top:1px dashed var(--muted); background:none !important; border-radius:0 !important; vertical-align:3px !important }
.chart-svg .line.dash { stroke-dasharray:7 5 }
section[data-app="account"] details.hold .who { overflow-wrap:anywhere }
/* without the stop-loss (hindsight): two tiles, max loss left and max profit right over a range bar with the rule's dot */
.pa-nl { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px 4px; display:grid; gap:10px; min-width:0 }
.nl-head { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px } .nl-head h3 { margin:0 } .nl-cnt { margin-left:auto; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.nl-tiles { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px }
.nl-tile { --tc:var(--muted); border:1px solid var(--line); border-left:4px solid var(--tc); border-radius:10px; padding:10px 14px 12px; display:grid; gap:8px; min-width:0; align-content:start }
.nl-tile.stop { --tc:var(--bad-mark) } .nl-tile.tp { --tc:var(--good-mark) }
.nl-t { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:2px 10px } .nl-t span { font-weight:600; font-size:15px }
.nl-t b { font-weight:500; font-size:var(--fs-xs); color:var(--muted); font-variant-numeric:tabular-nums }
.nl-lh { display:grid; grid-template-columns:1fr 1fr; gap:10px } .nl-lh > div { display:grid; gap:0; min-width:0 } .nl-lh .hi { text-align:right }
.nl-lh .k { font-size:var(--fs-xs); color:var(--muted) } .nl-lh .v { font-size:24px; line-height:1.15; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; letter-spacing:-.01em }
.nl-lh .p { font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums; white-space:nowrap }
.pa-nl .good { color:var(--good) } .pa-nl .bad { color:var(--bad) }
.nl-rng { position:relative; height:10px; border-radius:999px; background:var(--line2); margin:2px 0 }
.nl-rng i { position:absolute; top:0; bottom:0 } .nl-rng i.dn { background:var(--bad-mark); border-radius:999px 0 0 999px } .nl-rng i.up { background:var(--good-mark); border-radius:0 999px 999px 0 }
.nl-rng i.z { left:50%; width:2px; margin-left:-1px; top:-3px; bottom:-3px; background:var(--fg2) }
.nl-rng b { position:absolute; top:50%; width:14px; height:14px; margin:-7px 0 0 -7px; border-radius:50%; background:var(--fg); border:2px solid var(--surface) }
.nl-f { display:flex; flex-wrap:wrap; justify-content:space-between; gap:2px 12px; font-size:var(--fs-s); color:var(--fg2) } .nl-f b { font-variant-numeric:tabular-nums }
.nl-dot { display:inline-flex; align-items:baseline; gap:6px } .nl-dot i { width:9px; height:9px; border-radius:50%; background:var(--fg); align-self:center }
.nl-none { margin:0; font-size:var(--fs-s); color:var(--muted) }
.nl-all { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 18px; padding:8px 0 0; border-top:1px solid var(--line2); font-size:var(--fs-s); color:var(--fg2) }
.nl-all .k { font-weight:600; color:var(--fg) } .nl-all b { font-size:15px; font-variant-numeric:tabular-nums; white-space:nowrap }
.nl-all .raw small { margin-left:6px; font-size:var(--fs-xs); color:var(--muted) }
.nl-tbl td small.nl-raw { color:var(--fg2) }
.nl-tbl td small { display:block; font-size:var(--fs-xs); color:var(--muted); margin-top:1px; font-variant-numeric:tabular-nums }
.nl-tbl td.c { overflow-wrap:anywhere } .nl-tbl td.c strong { font-weight:600 } .nl-tbl th.n, .nl-tbl td.r, .nl-tbl td.hi, .nl-tbl td.lo { text-align:right }
.nl-tbl td.r span, .nl-tbl td.hi span, .nl-tbl td.lo span { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap }
@media (max-width:820px) {
  .pa-cats { grid-template-columns:1fr; gap:10px } .pa-hero { grid-template-columns:1fr; grid-template-areas:"pl" "line" "tiles" }
  .pa-cat { padding:10px 14px 0; gap:4px } .pa-cat .vr { display:flex; flex-wrap:wrap; align-items:baseline; gap:0 10px }
  .pa-cat .det, .pa-i .dt-only, .pa-ev.ex, .pa-day.ex { display:none }
  .pa-cat details.pa-i[open] { padding-bottom:12px } .pa-i .ph-only { display:inline } .pa-cat .ph { display:grid; gap:6px; margin:2px 0 8px } .pa-more.ph-only { display:block } .pa-ev.ph { display:grid } .pa-day.ph { display:block }
}
@media (max-width:560px) {
  .pa-tt .bar label { padding:0 12px } .pa-tt .bar .cnt { display:none }
  .pa-hero { padding:14px } .pa-big { font-size:40px } .pa-tiles { grid-template-columns:1fr 1fr } .pa-tile .v { font-size:18px } .pa-tile .v small { font-size:12px } .pa-cat .v { font-size:28px }
  .pa-ev { grid-template-columns:40px 20px minmax(0,1fr) auto; gap:6px; font-size:14px }
  .pa-tbl table, .pa-tbl tbody, .pa-tbl tr, .pa-tbl td { display:block } .pa-tbl thead { display:none }
  .pa-tbl tr { display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"c p" "w m" "h1 h1" "h2 h2"; gap:2px 12px; padding:10px 12px; border-top:1px solid var(--line2) }
  .pa-tbl tr:first-child { border-top:0 } .pa-tbl td { border-top:0; padding:0; min-width:0 }
  .pa-nl { padding:12px 12px 2px } .nl-tiles { grid-template-columns:1fr; gap:10px } .nl-tile { padding:10px 12px 12px } .nl-lh .v { font-size:22px }
  .nl-all { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:2px 10px } .nl-all .k { grid-column:1 / -1 } .nl-all span:not(.k) { display:grid; font-size:var(--fs-xs); color:var(--muted) }
  .nl-all span.raw { grid-column:1 / -1; display:flex; flex-wrap:wrap; align-items:baseline; gap:0 6px; order:9 } .nl-all .raw small { margin:0 }
  .nl-tbl table, .nl-tbl tbody, .nl-tbl tr, .nl-tbl td { display:block } .nl-tbl thead { display:none }
  .nl-tbl tr { display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"c r" "hi lo"; gap:2px 12px; padding:8px 4px; border-top:1px solid var(--line2) }
  .nl-tbl tr:first-child { border-top:0 } .nl-tbl td { border-top:0; padding:0; min-width:0 } .nl-tbl td.c { grid-area:c } .nl-tbl td.r { grid-area:r }
  .nl-tbl td.hi { grid-area:hi; text-align:left } .nl-tbl td.lo { grid-area:lo }
  .nl-tbl td.hi::before { content:"max profit"; display:block; color:var(--muted); font-size:var(--fs-xs) } .nl-tbl td.lo::before { content:"max loss"; display:block; color:var(--muted); font-size:var(--fs-xs) }
  .nl-tbl td.hi small, .nl-tbl td.lo small { display:inline; margin:0 0 0 6px; white-space:nowrap }
  .nl-tbl td.hi small.nl-raw { display:block; margin:1px 0 0; white-space:normal }
  .pa-tbl td.c { grid-area:c } .pa-tbl td.p { grid-area:p } .pa-tbl td.m { grid-area:m } .pa-tbl td.w { grid-area:w }
  .pa-tbl td.h { grid-area:h1; display:flex; flex-wrap:wrap; gap:2px 8px; align-items:baseline; font-size:var(--fs-s) } .pa-tbl td.h + td.h { grid-area:h2 }
  .pa-tbl td.h1::before { content:"best in 6 h (hindsight)"; color:var(--muted); font-size:var(--fs-xs) } .pa-tbl td.h2::before { content:"at 6 h (hindsight)"; color:var(--muted); font-size:var(--fs-xs) } .pa-tbl td.h small { display:inline; margin:0 } .pa-tbl td.h .chip { margin:0 } }
/* a phone: each category in short rows: its name and chip beside the P/L, its rate beside the ⓘ, then the same trades; an open ⓘ takes the full width */
@media (max-width:820px) {
  .pa-cat { grid-template-columns:minmax(0,1fr) auto; column-gap:10px; row-gap:0 }
  .pa-cat .head { grid-column:1; grid-row:1; flex-direction:column; align-items:flex-start; justify-content:center; align-self:center; gap:4px }
  .pa-cat .vr { display:contents } .pa-cat .v { grid-column:2; grid-row:1; justify-self:end; align-self:center }
  .pa-cat .r { grid-column:1; grid-row:2; align-self:center } .pa-cat details.pa-i { grid-column:2; grid-row:2; justify-self:end }
  .pa-cat details.pa-i > summary { padding:0 }
  .pa-cat details.pa-i[open] { grid-column:1 / -1; grid-row:auto; justify-self:stretch } .pa-cat .same { grid-column:1 / -1; grid-row:3 }
  .pa-cat .chip { font-size:12px; padding:2px 8px; white-space:nowrap } .pa-cat .same { padding-bottom:8px }
  /* the header's ⓘ sits at the end of the rate's line (an open one takes the full width below it) */
  .pa-hero .pl { grid-template-columns:minmax(0,1fr) auto } .pa-hero .pl > * { grid-column:1 / -1 } .pa-hero .pl > .pa-rate { grid-column:1; align-self:center }
  .pa-hero .pl > details.pa-i:not([open]) { grid-column:2; grid-row:4 } .pa-hero .pl > details.pa-i > summary { min-width:44px; padding:0; justify-content:center; font-size:15px }
}
@media (max-width:560px) { .pa-cat .v { font-size:24px } .pa-cat .r { font-size:var(--fs-xs) } }
@media (prefers-reduced-motion: reduce) { .pa-livel i { animation:none } }
"""
