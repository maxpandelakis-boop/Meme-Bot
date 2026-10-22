"""page_brain.py: "The brain", the top of the Brain tab (#pane-office). Fake money only: nothing here buys, signs or sends anything.

A dark panel that draws the bot as a brain: the core in the middle (the research lab that learns), the scan's agents on a ring around it
(each node lit by its state in the last run: done, failed, running), the coins the bot is thinking about on an inner ring (the pick and the
rocket hunter's best candidates, each node as bright as its score is close to the buy cut) and lines that carry signals into the core.
Under it the bot's "thoughts" in plain English sentences, built from the same numbers the other tabs show (the last scan, the pick and its
odds, the rocket round and its decision, the training, the two accounts).

Live: report.py's office script sends the event memebot-live with the live status row (app.status_doc: the agents with their status and
last line) while a scan runs; the script here lights the running agents, speeds the signal lines up and shows the running agent's last line
as the newest thought. Without the event (no live store, a scan not running) the panel shows the last run. A slow cycle picks one coin node
after the other and says what the bot knows about it (stopped with reduced motion: the first coin stays).

A tap on a coin node (or on the line under the brain) opens its data in a sheet (a modal <dialog>, over the app's tab bar): what the bot
thinks about it, its numbers, the filters it passed with its own values, the safety checks (the pick) or the buy cut and the paper position
with its price line (a rocket candidate; page_rocket.LIVE_JS draws it), a DexScreener live chart that loads only on a tap, and the links.
All of it comes from the scan's files (recommend.json, rocket.json, the paper account) and is rendered here, escaped; the sheet says when
its numbers are from.

section(D, R) -> HTML; every chain string and every agent line is escaped (in the script through textContent).
"""
import html, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
W, H, CX, CY = 400, 340, 200, 168
RING_X, RING_Y = 124, 128          # the agents' ring (an ellipse: the panel is wider than tall)
INNER = 70                          # the coins' ring
COINS_MAX = 6
HIT = 20                            # a coin's tap circle (viewBox units: about 34 px across on a phone; neighbours sit 60+ apart)
NAMES = {"dispatch": "Dispatcher", "scouts": "Scouts", "deep": "Deep search", "spotter": "Launch scout", "candles": "Candles", "market": "Prices",
         "refresh": "Price refresh", "analyst": "Filter", "safety": "Safety", "trader": "Trader", "reporter": "Reporter", "radar": "Launch radar",
         "rocket": "Rocket hunter"}
ORDER = ("dispatch", "scouts", "deep", "market", "candles", "analyst", "safety", "refresh", "trader", "reporter", "radar", "rocket")
ST_WORD = {"done": "done", "failed": "failed", "fallback": "fallback", "running": "working", "skipped": "paused", "absent": "paused"}


def num(v):
    return M.num(v)


def de_int(v):
    """1234 -> 1,234 (English grouping since Oct 22; the name stays)."""
    return format(int(round(v)), ",")


def de_eur(v):
    s = format(abs(v), ",.2f")
    return ("−" if v < -0.004 else "+" if v > 0.004 else "") + s + " €"


def rocket_doc(D):
    try:
        doc = json.load(open(os.path.join((D or {}).get("dir") or "", "db", "memebot", "rocket.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def agents(D):
    """[(id, name, state, short result)] in ring order: the scan's agents from office.json, the launch radar and the rocket hunter."""
    O = D.get("office") if isinstance(D.get("office"), dict) else {}
    by = {}
    for a in O.get("agents") or []:
        if isinstance(a, dict) and a.get("id") in NAMES:
            st = str(a.get("status") or "")
            by[a["id"]] = (st if st in ST_WORD else "done" if a.get("end") else "skipped", str(a.get("out") or "")[:120])
    doc = rocket_doc(D)
    if doc:
        rd = doc.get("round") or {}
        by["rocket"] = ("done", "%s coins watched, %d scored, %d bought" % (de_int(num(rd.get("candidates")) or 0), int(num(rd.get("scored")) or 0), int(num(rd.get("bought")) or 0)))
    by.setdefault("radar", ("done", "new pools under 10 minutes"))
    return [(i, NAMES[i]) + by[i] for i in ORDER if i in by]


TEAM = ("dispatch", "scouts", "deep", "market", "candles", "analyst", "safety", "refresh", "trader", "reporter", "trainer")
JOBS = {"dispatch": "plans the run", "scouts": "collects coins from every source", "deep": "searches with more keywords", "market": "fetches the prices",
        "candles": "fetches minute candles", "analyst": "filters and scores", "safety": "checks the best ones for traps", "refresh": "fresh prices before the pick",
        "trader": "buys the pick on paper", "reporter": "builds this page", "trainer": "learns from every result"}


def dur(sec):
    return "%d s" % round(sec) if sec < 90 else ("%.1f min" % (sec / 60)).replace(".0 min", " min")


def team(D, R):
    """The scan's helpers in run order, each with its state, how long it took and its result of the last run (the old office cards, in
    one compact list), and the run's head line: when it started, what kind of scan, how long. ("", []) without office.json."""
    O = D.get("office") if isinstance(D.get("office"), dict) else {}
    by = {a["id"]: a for a in O.get("agents") or [] if isinstance(a, dict) and a.get("id")}
    rows = []
    for i in TEAM:
        a = by.get(i)
        if not a:
            continue
        s, e = num(a.get("start")), num(a.get("end"))
        st = str(a.get("status") or "")
        st = st if st in ST_WORD else ("done" if s and e else "skipped")
        rows.append((i, "Learning lab" if i == "trainer" else NAMES.get(i, i), JOBS.get(i, ""), st, dur((e - s) / 1000.0) if s and e and e >= s else "–", str(a.get("out") or "")[:140]))
    t0, t1 = num(O.get("t")), num(O.get("end"))
    head = ""
    if t0:
        mode = {"full": "full scan", "light": "short scan", "none": "prices only"}.get(str(O.get("mode") or ""), "scan")
        head = "Last run %s · %s%s · %d helpers" % (R.local(t0).strftime("%H:%M"), mode, (" · %s" % dur((t1 - t0) / 1000.0)) if t1 and t1 > t0 else "", len(rows))
    return head, rows


def coins(D, doc):
    """[(symbol, kind, strength 0..1, what the bot knows, its record)]: the pick first, then the rocket candidates by score."""
    out = []
    picks = [c for c in ((D.get("rec") or {}).get("picks") or []) if isinstance(c, dict)]
    if picks:
        p = picks[0]
        bits = ["my pick", "score %d" % round(num(p.get("score")) or 0)]
        if num(p.get("upP")) is not None:
            bits.append("%d%% chance of a profit" % round(100 * num(p["upP"])))
        if num(p.get("zeroP")) is not None:
            bits.append("%d%% risk of going to zero" % round(100 * num(p["zeroP"])))
        bits.append("safety check passed" if p.get("ok") else "safety check not clean")
        out.append((str(p.get("sym") or "?")[:12], "pick", 1.0, ", ".join(bits), p))
    if doc:
        cut = num(doc.get("cut")) or 0
        for r in [r for r in doc.get("top") or [] if isinstance(r, dict)][:COINS_MAX - len(out)]:
            sh = (num(r.get("score")) or 0) / cut if cut > 0 else 0
            mc = num(r.get("mc"))
            out.append((str(r.get("sym") or str(r.get("addr") or "?")[:6])[:12], "buy" if r.get("buy") else "cand", max(0.0, min(1.0, sh)),
                        "rocket candidate, %d%% of the buy line, %d min old%s%s" % (round(100 * sh), int(num(r.get("age")) or 0),
                                                                                     (", market cap $%s" % de_int(mc)) if mc else "", ", bought" if r.get("buy") else ""), r))
    return out


def thoughts(D, R, doc):
    """[(time text, kind, sentence)], newest first: what the bot did and decided, in plain words."""
    now, out = D["now"], []
    hm = lambda ms: R.local(ms).strftime("%H:%M") if ms else "–"
    rc = D.get("rec") or {}
    if doc:
        rd, cut = doc.get("round") or {}, num(doc.get("cut")) or 0
        top = [r for r in doc.get("top") or [] if isinstance(r, dict)]
        bought = [r for r in top if r.get("buy")]
        t = num(doc.get("t"))
        if bought:
            out.append((hm(t), "go", "Radar decision: bought %s, the score reached the buy line. 20 € fake money." % ", ".join(str(r.get("sym") or "?") for r in bought)))
        elif top:
            b = top[0]
            out.append((hm(t), "no", "Radar decision: nothing bought. Best was %s at %d%% of the buy line; I only buy at 100%%."
                        % (b.get("sym") or "?", round(100 * (num(b.get("score")) or 0) / cut) if cut else 0)))
        out.append((hm(t), "see", "Rocket radar: %s new coins watched, %d of the right age scored." % (de_int(num(rd.get("candidates")) or 0), int(num(rd.get("scored")) or 0))))
    picks = [c for c in rc.get("picks") or [] if isinstance(c, dict)]
    t = num(rc.get("t"))
    if picks:
        p = picks[0]
        odds = ""
        if num(p.get("upP")) is not None and num(p.get("zeroP")) is not None:
            odds = " Chance of a profit %d%%, risk of going to zero %d%%." % (round(100 * num(p["upP"])), round(100 * num(p["zeroP"])))
        out.append((hm(t), "go", "Pick decision: %s for the next 2 hours (score %d).%s" % (p.get("sym") or "?", round(num(p.get("score")) or 0), odds)))
    elif rc:
        out.append((hm(t), "no", "Pick decision: no coin was clean enough, so no pick."))
    if num(rc.get("scanned")):
        out.append((hm(t), "see", "Scan: looked at %s coins, %d passed every filter." % (de_int(rc["scanned"]), int(num(rc.get("passed")) or 0))))
    O = D.get("office") if isinstance(D.get("office"), dict) else {}
    tr = next((a for a in O.get("agents") or [] if isinstance(a, dict) and a.get("id") == "trainer"), None)
    if tr and tr.get("out"):
        out.append((hm(num(O.get("t"))), "learn", "Learning lab: %s." % str(tr["out"])[:140]))
    return out


# ---------------------------------------------------------------- the coin sheet: a tap on a coin opens its data
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ICON = {"ok": "✓", "warn": "!", "bad": "✕", "note": "i", "unknown": "?"}
TIER_THINK = {"": "My pick for the next %s: the best clean coin of this scan.",
              "weak": "My pick for the next %s, but only the best there was: clean, yet its score is below my mark.",
              "fallback": "No coin passed every filter this time. This is the best one with relaxed rules, so be careful.",
              "risky": "No coin had a clean safety report. This is the tradable one with the best odds, so be careful.",
              "watch": "Not a pick, only to watch: my model puts its risk of going to zero too high."}
WHY_EN = {"stop": "stop −30%", "11x": "hit 11x", "6h": "after 6 h", "gone": "coin gone"}


def val_en(v):
    """A safety value as the sheet shows it: numbers as they come (2,087 · 4.4%), words as they are."""
    return str(v)


def de(v, d=0):
    """1234.5 -> 1,234.5 with a real minus (English notation since Oct 22; the short name stays)."""
    s = format(abs(v), ",.%df" % d)
    return ("−" if v < 0 and s.strip("0,.") else "") + s


def usd(v):
    """1048113 -> '$1.05M', 90934 -> '$90,934', a coin price keeps three significant digits."""
    v = num(v)
    if v is None or v < 0:
        return "–"
    if v >= 1e6:
        return "$" + de(v / 1e6, 2) + "M"
    if v >= 1000:
        return "$" + de(v)
    if v == 0:
        return "$0"
    d = min(12, max(2, 2 - int(math.floor(math.log10(v)))))
    return "$" + de(v, d).rstrip("0").rstrip(".")


def share(v, d=0):
    v = num(v)
    return "–" if v is None else de(100 * v, d) + "%"


def chg(v):
    """A change already in percent: +50%, −3.6% (one decimal under 10)."""
    v = num(v)
    return "–" if v is None else ("+" if v > 0.05 else "") + de(v, 1 if abs(v) < 10 else 0) + "%"


def mult(v):
    v = num(v)
    return "–" if v is None else "x" + de(v, 2)


def hours():
    h = str(getattr(M, "HORIZON", "") or "")[:-1]
    n = int(h) if h.isdigit() else 2
    return "1 hour" if n == 1 else "%d hours" % n


def hm(R, ms):
    try:
        return R.local(ms).strftime("%H:%M")
    except Exception:
        return "–"


def kv(items):
    return '<dl class="bc-kv">%s</dl>' % "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (E(k), E(v)) for k, v in items if v not in (None, "", "–"))


def checks(title, rows, after=""):
    """rows: (state, label, value) -> one list with an icon per row (✓ passed, ! only the relaxed floor, ✕ failed, i a note, ? unknown)."""
    if not rows:
        return ""
    return '<div class="bc-sec"><h4>%s</h4><ul class="bc-ck">%s</ul>%s</div>' % (E(title), "".join(
        '<li class="%s"><i aria-hidden="true">%s</i><span>%s</span><em>%s</em></li>' % (s if s in ICON else "note", ICON.get(s, "i"), E(l), E(v)) for s, l, v in rows), after)


def links(R, a, pair, x=None):
    """pump.fun and DexScreener first, then the safety and trading sites (report.coin_links); nothing without a real mint address."""
    if not B58.match(str(a or "")):
        return ""
    pair = pair if B58.match(str(pair or "")) else None
    first = {"pump.fun": 0, "DexScreener": 1}
    ls = sorted(R.coin_links(a, pair, x), key=lambda nu: first.get(nu[0], 2))
    return '<div class="bc-lk">%s</div>' % "".join('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (E(u), E(n)) for n, u in ls)


def live_chart(a, pair):
    """DexScreener's chart behind a tap: the iframe is only made when the fold opens (the page's script), so a closed sheet loads nothing."""
    p = pair if B58.match(str(pair or "")) else a
    if not B58.match(str(p or "")):
        return ""
    return ('<details class="bc-live" data-bc-live="https://dexscreener.com/solana/%s?embed=1&amp;theme=dark&amp;trades=0&amp;info=0"><summary>Live chart (DexScreener)</summary>'
            '<div class="bc-fr"></div></details>') % E(p)


def head(sym, name, kind, chip):
    nm = str(name or "").strip()
    return ('<div class="bc-hd"><div class="bc-id"><b>%s</b>%s</div><span class="bc-chip %s">%s</span>'
            '<button type="button" class="bc-x" data-bc-x aria-label="Close">×</button></div>') % (
        E(sym), ('<small>%s</small>' % E(nm[:48])) if nm and nm.lower() != str(sym).lower() else "", kind, E(chip))


def paper_pos(D, R, a):
    """The pick's paper position (the scan's account, page_account): bought when, for how much, where it stood at the scan."""
    try:
        import page_account as PA
        rows = [r for r in (PA._acct(D) or {}).get("rows") or [] if isinstance(r, dict) and (r.get("p") or {}).get("addr") == a and r.get("grp") != "young"]
    except Exception:
        return ""
    if not rows:
        return ""
    r = max(rows, key=lambda r: num(r.get("tBuy")) or 0)
    t, pnl, pc = num(r.get("tBuy")), num(r.get("pnl")), num(r.get("pct"))
    bits = ["%s € bought on paper at %s" % (de(num(r.get("ticket")) or 0), hm(R, t))]
    if pnl is not None:
        bits.append(("%s %s%s" % ("now" if r.get("open") else "sold:", de_eur(pnl), (" (%s)" % chg(100 * pc)) if pc is not None else "")))
    return '<div class="bc-sec"><h4>Paper position (Pick account)</h4><p class="bc-p %s">%s</p></div>' % ("good" if (pnl or 0) > 0.004 else "bad" if (pnl or 0) < -0.004 else "", E(" · ".join(bits)))


def pick_card(D, R, p):
    hz, f = hours(), p.get("f") if isinstance(p.get("f"), dict) else {}
    up, zp, sc = num(p.get("upP")), num(p.get("zeroP")), num(p.get("score"))
    tier = str(p.get("tier") or "")
    tier = tier if tier in TIER_THINK else ""
    think = [TIER_THINK[tier] % hz if "%s" in TIER_THINK[tier] else TIER_THINK[tier]]
    if up is not None and zp is not None:
        think.append("I put its chance of a profit at %s and its risk of going to zero at %s in %s." % (share(up), share(zp), hz))
    if p.get("lowOdds") and up is not None:
        think.append("That is low: I would like at least %s." % share(M.MIN_UP_P))
    think.append("Safety check passed." if p.get("ok") else "Safety check not clean.")
    rk = (D.get("rec") or {})
    stats = [("Score", ("%s of 100" % de(sc or 0)) + ((" · rank %d" % int(num(p["rank"]))) if num(p.get("rank")) else "")),
             ("Chance of a profit", share(up)), ("Risk of going to zero", share(zp)), ("Price at the scan", usd(p.get("px"))),
             ("Market cap", usd(p.get("mc"))), ("Liquidity", usd(p.get("liq"))), ("Volume 24 h", usd(p.get("vol"))),
             ("Age", (de(num(f["ageH"]), 1) + " h") if num(f.get("ageH")) is not None else "–"), ("Share of buys", share(f.get("buyShare"))),
             ("24 h", chg(f.get("c24")))]
    lq = num(f.get("liqMc"))
    gates = [("Pool", "real pool%s" % ((" on %s" % p["dex"]) if p.get("dex") else "")),
             ("No fake", "no copycat" + ((" · on %d source lists" % int(num(f["srcN"]))) if num(f.get("srcN")) else "")),
             ("Age", (de(num(f["ageH"]), 1) + " h") if num(f.get("ageH")) is not None else "–"), ("Size", "market cap " + usd(p.get("mc"))),
             ("Liquidity", usd(p.get("liq")) + ((" · %s of the market cap" % share(lq)) if lq is not None else "")), ("Volume", usd(p.get("vol")) + " in 24 h"),
             ("Chart", "1 h %s · 6 h %s" % (chg(f.get("c1")), chg(f.get("c6")))),
             ("Buyers", ("%s buys in 1 h" % de(num(f["buys1"]))) if num(f.get("buys1")) is not None else "–")]
    relaxed = [str(x) for x in p.get("relaxed") or []] if isinstance(p.get("relaxed"), list) else []
    gate_st = "note" if tier == "fallback" else "ok"
    gate_html = checks("Filters: %s" % ("relaxed" if tier == "fallback" else "all passed"), [(gate_st, k, v) for k, v in gates],
                       ('<p class="bc-s">Not passed: %s</p>' % E("; ".join(relaxed))) if relaxed else "")
    try:
        srows = R.safety_checks(p.get("risk"))
    except Exception:
        srows = []
    safe = checks("Safety check", [(s, w, val_en(v)) for s, w, v, _ in srows]) if srows else (
        '<div class="bc-sec"><h4>Safety check</h4><p class="bc-s">%s</p></div>' % E(p.get("safety") or "no report"))
    why = ('<details class="bc-why"><summary>Every reason the bot gave</summary><p>%s</p></details>' % E(p["why"])) if p.get("why") else ""
    t = num(rk.get("t"))
    return (head(p.get("sym") or "?", p.get("name"), "pick", "My pick" if tier != "watch" else "Watch only")
            + '<div class="bc-think"><i>Thoughts</i><p>%s</p></div>' % E(" ".join(think))
            + kv(stats) + gate_html + safe + paper_pos(D, R, p.get("addr")) + why + live_chart(p.get("addr"), p.get("pair"))
            + links(R, p.get("addr"), p.get("pair"), p.get("x"))
            + '<p class="bc-t">As of the scan at %s · new numbers with the next scan%s</p>' % (E(hm(R, t)), ("<br><code>%s</code>" % E(p["addr"])) if p.get("addr") else ""))


def rocket_card(D, R, doc, r):
    cut, sc = num(doc.get("cut")) or 0, num(r.get("score")) or 0
    sh = sc / cut if cut > 0 else 0
    a = str(r.get("addr") or "")
    bk = doc.get("book") if isinstance(doc.get("book"), dict) else {}
    op = (bk.get("open") or {}).get(a) if isinstance(bk.get("open"), dict) else None
    cl = [p for p in bk.get("closed") or [] if isinstance(p, dict) and p.get("addr") == a]
    pos = op if isinstance(op, dict) else (cl[-1] if cl else None)
    bought = bool(r.get("buy") or pos)
    if bought:      # the numbers of the buy (a bought coin is not scored again)
        bs, bc = (num((pos or {}).get("score")) or sc), (num((pos or {}).get("cut")) or cut)
        think = "Bought%s: my model put its chance of 10x in 6 hours at %s, the buy line was %s. 20 € fake money. " % (
            (" at %s" % hm(R, num(pos["t"]))) if pos and num(pos.get("t")) else "", share(bs, 1), share(bc, 1))
        if pos and pos is not op:
            think += "Sold at %s (%s), result %s." % (hm(R, num(pos.get("out"))), WHY_EN.get(str(pos.get("why") or ""), str(pos.get("why") or "")),
                                                     de_eur(num(pos.get("eur")) or 0))
        else:
            think += "I sell at −30%, at 11x or after 6 hours."
    else:
        think = ("Not bought: my model puts its chance of 10x in 6 hours at %s, that is %d%% of the buy line (%s). I only buy at 100%%. "
                 "%sI look at it again in the next rounds while it is younger than 18 hours." % (
                     share(sc, 1), round(100 * sh), share(cut, 1), "It is close. " if sh >= 0.5 else ""))
    stats = [("Chance of 10x (6 h)", share(sc, 1)), ("Buy line", share(cut, 1)), ("Reached", "%d%% of the line" % round(100 * sh)),
             ("Age at the check", "%d min" % int(num(r.get("age")) or 0)), ("Market cap", usd(r.get("mc"))), ("Price at the check", usd(r.get("px")))]
    bar = '<div class="bc-bar" role="img" aria-label="%d%% of the buy line"><i class="%s" style="width:%.1f%%"></i></div>' % (
        round(100 * sh), "buy" if bought else "near" if sh >= 0.5 else "", max(2.0, min(100.0, 100 * sh)))
    try:
        import rocket as RK
        lim = (RK.START_MIN, RK.END_MIN // 60)
    except Exception:
        lim = (30, 18)
    gates = [("ok", "Age", "%d min to %d h" % lim), ("ok", "Market cap", "$100,000 to $5M"), ("ok", "Liquidity", "at least $15,000"),
             ("ok", "Volume 24 h", "at least $15,000"), ("ok", "No crash", "1 h above −10%, 6 h above −50%")]
    pos_html = ""
    if pos:
        try:
            import page_rocket as PK
            ch = PK.chart_div(pos, closed=pos is not op)
        except Exception:
            ch = ""
        if pos is op:
            line = "open since %s · now %s · high %s" % (hm(R, num(pos.get("t"))), mult(pos.get("now") or 1.0), mult(pos.get("hi") or 1.0))
        else:
            line = "sold at %s · %s · %s · %s" % (hm(R, num(pos.get("out"))), mult(pos.get("mult")), WHY_EN.get(str(pos.get("why") or ""), str(pos.get("why") or "")),
                                                 de_eur(num(pos.get("eur")) or 0))
        pos_html = ('<div class="bc-sec"><h4>Paper position (Radar account 🚀)</h4><p class="bc-p">%s</p>%s<p class="bc-s">%s on the '
                    '<button type="button" class="bc-go" data-bc-tab="young">Radar tab</button></p></div>') % (
            E(line), ch, "Live, updated every minute," if pos is op else "All sells")
    t = num(doc.get("t")) or num(r.get("t"))
    return (head(r.get("sym") or a[:6] or "?", "", "buy" if bought else "cand", "Rocket buy" if bought else "Rocket candidate")
            + '<div class="bc-think"><i>Thoughts</i><p>%s</p></div>' % E(think) + bar + kv(stats)
            + checks("Radar filters: all passed", gates) + pos_html + live_chart(a, r.get("pool")) + links(R, a, r.get("pool"))
            + '<p class="bc-t">As of the rocket round at %s · new every 15 minutes%s</p>' % (E(hm(R, t)), ("<br><code>%s</code>" % E(a)) if a else ""))


def sheet(D, R, doc, cs):
    """One article per coin node, all in one dialog; the script shows the tapped one."""
    arts = []
    for i, (_, kind, _, _, rec) in enumerate(cs):
        try:
            body = pick_card(D, R, rec) if kind == "pick" else rocket_card(D, R, doc or {}, rec)
        except Exception as e:            # one coin's bad record never takes the brain down: its sheet says so
            body = head(rec.get("sym") or "?", "", kind, "Data") + '<p class="bc-s">The data of this coin could not be read (%s).</p>' % E(type(e).__name__)
        arts.append('<article class="bc" data-cd="%d" hidden>%s</article>' % (i, body))
    if not arts:
        return ""
    return '<dialog class="bn-dlg" data-bn-dlg aria-label="Coin data"><div class="bc-in">%s</div></dialog>' % "".join(arts)


def ring_xy(i, n, rx, ry, start=-90.0):
    a = math.radians(start + 360.0 * i / max(1, n))
    return CX + rx * math.cos(a), CY + ry * math.sin(a)


def stars():
    """A fixed field of faint neurons behind the brain (the same on every page, no randomness at render time)."""
    pts, s = [], 7
    for _ in range(46):
        s = (s * 1103515245 + 12345) % 2147483648
        x = 8 + (s % 384)
        s = (s * 1103515245 + 12345) % 2147483648
        y = 8 + (s % 324)
        pts.append((x, y))
    lines = []
    for i, (x, y) in enumerate(pts):
        near = sorted(((x - a) ** 2 + (y - b) ** 2, j) for j, (a, b) in enumerate(pts) if j != i)[:2]
        lines += ['<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x, y, pts[j][0], pts[j][1]) for _, j in near if j > i]
    dots = "".join('<circle cx="%d" cy="%d" r="%.1f" style="animation-delay:-%.1fs"/>' % (x, y, 0.8 + (i % 3) * 0.4, (i * 0.37) % 4) for i, (x, y) in enumerate(pts))
    return '<g class="bn-bg"><g class="bn-bgl">%s</g><g class="bn-bgd">%s</g></g>' % ("".join(lines), dots)


def svg(ags, cs, live_word):
    parts = ['<svg class="bn-svg" viewBox="0 0 %d %d" role="img" aria-label="The bot’s brain: %d helpers, %d coins in view">' % (W, H, len(ags), len(cs)),
             '<defs><radialGradient id="bn-core" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#fff" stop-opacity=".95"/>'
             '<stop offset=".25" stop-color="var(--nn1)"/><stop offset=".7" stop-color="var(--nn2)" stop-opacity=".55"/><stop offset="1" stop-color="var(--nn2)" stop-opacity="0"/></radialGradient>'
             '<filter id="bn-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
             stars()]
    links, nodes = [], []
    for i, (aid, name, st, out_) in enumerate(ags):
        x, y = ring_xy(i, len(ags), RING_X, RING_Y)
        mx, my = (x + CX) / 2 + (CY - y) * 0.12, (y + CY) / 2 + (x - CX) * 0.12
        links.append('<path class="bn-ln st-%s" data-ln="%s" d="M%.1f %.1f Q%.1f %.1f %d %d" style="animation-delay:-%.2fs"/>' % (st, E(aid), x, y, mx, my, CX, CY, i * 0.41))
        ly = y + (15 if y >= CY - 4 else -10)
        anchor = "middle" if abs(x - CX) < 40 else ("start" if x > CX else "end")
        lx = x + (0 if anchor == "middle" else (9 if anchor == "start" else -9))
        ly = y + 4 if anchor != "middle" else ly
        nodes.append('<g class="bn-ag st-%s" data-ag="%s"><title>%s: %s</title><circle class="h" cx="%.1f" cy="%.1f" r="9"/><circle class="c" cx="%.1f" cy="%.1f" r="4.6"/>'
                     '<text x="%.1f" y="%.1f" text-anchor="%s">%s</text></g>' % (st, E(aid), E(name), E(out_ or ST_WORD.get(st, st)), x, y, x, y, lx, ly, anchor, E(name)))
    for i, (sym, kind, k, _, _) in enumerate(cs):
        x, y = ring_xy(i, len(cs), INNER, INNER * 0.86, start=-60.0)
        r = 3.2 + 4.2 * k
        links.append('<line class="bn-cl %s" x1="%.1f" y1="%.1f" x2="%d" y2="%d" style="opacity:%.2f"/>' % (kind, x, y, CX, CY, 0.25 + 0.6 * k))
        # a wide invisible circle under each coin: a thumb-sized tap target for its data (the dots alone are a few pixels on a phone)
        nodes.append('<g class="bn-coin %s" data-coin="%d" style="--k:%.2f" role="button" tabindex="0" aria-label="%s: open its data"><circle class="hit" cx="%.1f" cy="%.1f" r="%d"/>'
                     '<circle class="h" cx="%.1f" cy="%.1f" r="%.1f"/><circle class="c" cx="%.1f" cy="%.1f" r="%.1f"/>'
                     '<text x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>' % (kind, i, k, E(sym), x, y, HIT, x, y, r * 2.4, x, y, r, x, y - r - 5, E(sym)))
    core = ('<g class="bn-core"><circle class="o3" cx="%d" cy="%d" r="44"/><circle class="o2" cx="%d" cy="%d" r="34"/><circle class="o1" cx="%d" cy="%d" r="27"/>'
            '<circle class="g" cx="%d" cy="%d" r="30" fill="url(#bn-core)"/>'
            '<text class="t1" x="%d" y="%d" text-anchor="middle">BRAIN</text><text class="t2" x="%d" y="%d" text-anchor="middle" data-bn-word>%s</text></g>') % (
        CX, CY, CX, CY, CX, CY, CX, CY, CX, CY + 2, CX, CY + 14, E(live_word))
    parts += ['<g class="bn-links">%s</g>' % "".join(links), core, '<g filter="url(#bn-glow)">%s</g>' % "".join(nodes), '</svg>']
    return "".join(parts)


def section(D, R):
    doc = rocket_doc(D)
    ags, cs, th = agents(D), coins(D, doc), thoughts(D, R, doc)
    focus = "".join('<li data-f="%d"><b>%s</b> %s<span class="bn-more" aria-hidden="true">Data ›</span></li>' % (i, E(s), E(w)) for i, (s, _, _, w, _) in enumerate(cs))
    tl = "".join('<li class="%s" style="animation-delay:%.2fs"><time>%s</time><span>%s</span></li>' % (k, 0.15 + 0.12 * i, E(t), E(s)) for i, (t, k, s) in enumerate(th))
    head, rows = team(D, R)
    team_html = ('<div class="bn-tm"><h3>Helpers</h3>%s<ul>%s</ul><p class="bn-tmn">Every detail of the old office (floor plan, timeline, daily overview) is in the Archive.</p></div>' % (
        ('<p class="bn-tmh">%s</p>' % E(head)) if head else "",
        "".join('<li class="st-%s" data-tm="%s" title="%s"><i></i><div><b>%s</b><span data-tm-out>%s</span></div><em data-tm-st>%s</em></li>' % (
            st, E(i), E(j), E(n), E(o or ST_WORD.get(st, st)), E(d if st != "running" else ST_WORD["running"])) for i, n, j, st, d, o in rows))) if rows else ""
    legend = ('<div class="bn-leg"><span class="l-pick">Pick</span><span class="l-rk">Rocket candidate</span><span class="l-ok">Helper done</span>'
              '<span class="l-run">working now</span><span class="l-bad">Failed</span>%s</div>') % ('<em class="bn-tap">Tap a coin for its data</em>' if cs else "")
    return ('<style>%s</style><section class="bn" data-brain data-state="rest"><div class="bn-head"><div><div class="bn-ey">Live</div><h2 class="bn-h">The brain</h2></div>'
            '<span class="bn-live" data-bn-live>resting · last scan</span></div>'
            '<div class="bn-stage">%s</div><ul class="bn-focus" aria-live="polite">%s</ul>%s'
            '<div class="bn-th"><h3>Thoughts</h3><ol data-bn-thoughts>%s</ol></div>%s%s</section><script>%s</script>') % (
        CSS, svg(ags, cs, "resting"), focus, legend, tl or '<li class="see"><time>–</time><span>No thoughts yet: the first scan comes soon.</span></li>', team_html,
        sheet(D, R, doc, cs), JS)


JS = r"""
(function(){
var root=document.querySelector('[data-brain]');if(!root)return;
var word=root.querySelector('[data-bn-word]'),badge=root.querySelector('[data-bn-live]'),list=root.querySelector('[data-bn-thoughts]');
var fs=Array.prototype.slice.call(root.querySelectorAll('.bn-focus li')),cs=Array.prototype.slice.call(root.querySelectorAll('.bn-coin'));
var still=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches,i=0;
function focus(n){fs.forEach(function(f,k){f.classList.toggle('on',k===n);});cs.forEach(function(c,k){c.classList.toggle('on',k===n);});}
var dlg=root.querySelector('[data-bn-dlg]'),cards=Array.prototype.slice.call(root.querySelectorAll('[data-cd]')),from=null;
if(fs.length){focus(0);if(!still)setInterval(function(){if(document.hidden||(dlg&&dlg.hasAttribute('open')))return;i=(i+1)%fs.length;focus(i);},3200);}
// a tap on a coin (its node, or the line under the brain) opens its data: one dialog, the tapped coin's article shown; showModal puts it
// in the top layer, over the app's tab bar; the rocket position's price line is drawn by page_rocket's chart script when it opens
function show(n){if(!dlg||!cards[n])return;i=n;focus(n);from=document.activeElement;
  cards.forEach(function(c,k){if(k===n)c.removeAttribute('hidden');else c.setAttribute('hidden','');});
  if(typeof window.memebotRkChart==='function')[].forEach.call(cards[n].querySelectorAll('[data-rk-ch]'),function(d){try{window.memebotRkChart(d);}catch(e){}});
  if(typeof dlg.showModal==='function'){if(!dlg.open)dlg.showModal();}else{dlg.setAttribute('open','');dlg.classList.add('fb');}
  document.documentElement.classList.add('bn-lock');dlg.scrollTop=0;}
function done(){document.documentElement.classList.remove('bn-lock');if(from&&from.focus)try{from.focus({preventScroll:true});}catch(e){}from=null;}
function hide(){if(!dlg)return;if(typeof dlg.close==='function'&&dlg.open)dlg.close();else{dlg.removeAttribute('open');dlg.classList.remove('fb');done();}}
cs.forEach(function(c,k){c.addEventListener('click',function(){show(k);});
  c.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();show(k);}});});
fs.forEach(function(f,k){f.addEventListener('click',function(){show(k);});});
if(dlg){dlg.addEventListener('close',done);
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&dlg.classList.contains('fb')&&dlg.hasAttribute('open'))hide();});   // no showModal: Escape by hand
  dlg.addEventListener('click',function(e){var t=e.target;if(t===dlg){hide();return;}      // a tap beside the sheet (its backdrop)
    if(t.closest&&t.closest('[data-bc-x]')){hide();return;}
    var go=t.closest&&t.closest('[data-bc-tab]');if(!go)return;hide();
    var A=window.MemebotApp,k=go.getAttribute('data-bc-tab');if(A&&typeof A.select==='function'){A.select(k,'top');return;}
    var r=document.getElementById('tab-'+k);if(r){r.click();window.scrollTo(0,0);}});
  // DexScreener's chart: the iframe is made only when its fold opens, so a sheet costs nothing until then
  dlg.addEventListener('toggle',function(e){var d=e.target;if(!d||!d.open||!d.getAttribute||!d.hasAttribute('data-bc-live'))return;
    var box=d.querySelector('.bc-fr'),u=d.getAttribute('data-bc-live')||'';
    if(!box||box.firstChild||!/^https:\/\/dexscreener\.com\/solana\/[1-9A-HJ-NP-Za-km-z]{32,44}\?/.test(u))return;
    var f=document.createElement('iframe');f.src=u;f.title='Live chart';f.setAttribute('loading','lazy');box.appendChild(f);},true);}
var ST={done:1,failed:1,fallback:1,running:1,skipped:1};
// the live status row (report.py's office script): the running agents light up, the newest agent line becomes a thought
window.addEventListener('memebot-live',function(e){var d=e&&e.detail||{},st=d.status,live=d.state==='live';
  root.setAttribute('data-state',live?'live':'rest');if(word)word.textContent=live?'thinking':'resting';
  if(badge)badge.textContent=live?'thinking · scan running':'resting · last scan';
  if(!st||!Array.isArray(st.agents))return;var run=null;
  st.agents.forEach(function(a){if(!a||!a.id)return;var s=ST[a.status]?a.status:(a.end?'done':'skipped');
    var g=root.querySelector('[data-ag="'+String(a.id).replace(/[^a-z0-9_-]/gi,'')+'"]'),l=root.querySelector('[data-ln="'+String(a.id).replace(/[^a-z0-9_-]/gi,'')+'"]');
    [g,l].forEach(function(x){if(x)x.setAttribute('class',x.getAttribute('class').replace(/\bst-\w+/,'st-'+s));});
    var row=root.querySelector('[data-tm="'+String(a.id).replace(/[^a-z0-9_-]/gi,'')+'"]');
    if(row&&live){row.className='st-'+s;var so=row.querySelector('[data-tm-st]');if(so&&s==='running')so.textContent='working';
      var lo=row.querySelector('[data-tm-out]');if(lo&&a.lines&&a.lines.length&&s==='running')lo.textContent=String(a.lines[a.lines.length-1]).slice(0,160);}
    if(s==='running'&&a.lines&&a.lines.length)run={n:g?g.textContent:a.id,l:String(a.lines[a.lines.length-1]).slice(0,160)};});
  var old=list&&list.querySelector('li.now');if(old)old.parentNode.removeChild(old);
  if(live&&run&&list){var li=document.createElement('li');li.className='now';var t=document.createElement('time');t.textContent='now';
    var s=document.createElement('span');s.textContent=run.n+': '+run.l;li.appendChild(t);li.appendChild(s);list.insertBefore(li,list.firstChild);}
});
})();
"""

CSS = r"""
/* the brain (page_brain.py): always a dark stage with neon nodes, whatever the page's theme */
.bn { --nn1:#7cf7ff; --nn2:#b76bff; --nn3:#ff5fa2; --nok:#5cf2a6; --nbad:#ff6b6b; --nbg:#05070f; --nfg:#e8ecff; --nmut:#8b93b8;
  position:relative; display:grid; gap:12px; padding:14px; border-radius:20px; overflow:hidden; color:var(--nfg);
  background:radial-gradient(90% 70% at 50% 42%, #1a1440 0%, #0b0d22 45%, var(--nbg) 100%); border:1px solid #232a52;
  box-shadow:0 0 0 1px rgba(124,247,255,.05) inset, 0 18px 50px -20px rgba(120,80,255,.45) }
.bn-head { display:flex; justify-content:space-between; align-items:flex-end; gap:8px; flex-wrap:wrap }
.bn-ey { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--nmut) }
.bn h2 { font-size:22px; font-weight:600; letter-spacing:-.01em; background:linear-gradient(90deg,var(--nn1),var(--nn2) 60%,var(--nn3)); -webkit-background-clip:text; background-clip:text; color:transparent }
.bn-live { font-size:12px; padding:4px 10px; border-radius:999px; border:1px solid #2c3463; color:var(--nmut); display:inline-flex; align-items:center; gap:6px }
.bn-live::before { content:""; width:7px; height:7px; border-radius:50%; background:var(--nmut) }
.bn[data-state="live"] .bn-live { color:var(--nn1); border-color:color-mix(in srgb,var(--nn1) 45%,transparent) }
.bn[data-state="live"] .bn-live::before { background:var(--nn1); box-shadow:0 0 8px var(--nn1); animation:bn-blink 1s ease-in-out infinite }
.bn-stage { margin:0 -6px } .bn-svg { display:block; width:100%; height:auto; font-family:var(--sans) }
.bn-bgl line { stroke:#5d6bd6; stroke-width:.5; opacity:.16 } .bn-bgd circle { fill:#9fb0ff; opacity:.35; animation:bn-tw 4s ease-in-out infinite }
.bn-ln { fill:none; stroke:var(--nn2); stroke-width:1.1; opacity:.5; stroke-dasharray:3 7; animation:bn-flow 2.6s linear infinite }
.bn-ln.st-done { stroke:var(--nn1); opacity:.42 } .bn-ln.st-failed { stroke:var(--nbad); opacity:.6 } .bn-ln.st-skipped, .bn-ln.st-absent { opacity:.12; animation:none }
.bn-ln.st-running { stroke:var(--nn1); opacity:1; stroke-width:1.8; animation-duration:.8s }
.bn[data-state="live"] .bn-ln { animation-duration:1.1s }
.bn-cl { stroke:var(--nn3); stroke-width:1; stroke-dasharray:2 5; animation:bn-flow 1.8s linear infinite } .bn-cl.pick { stroke:var(--nok) }
.bn-ag .h { fill:var(--nn1); opacity:.12 } .bn-ag .c { fill:var(--nn1) } .bn-ag text { fill:var(--nfg); font-size:10px; opacity:.85 }
.bn-ag.st-failed .c, .bn-ag.st-failed .h { fill:var(--nbad) } .bn-ag.st-fallback .c { fill:#ffc35c }
.bn-ag.st-skipped .c, .bn-ag.st-absent .c { fill:var(--nmut) } .bn-ag.st-skipped .h, .bn-ag.st-absent .h { opacity:0 } .bn-ag.st-skipped text, .bn-ag.st-absent text { opacity:.45 }
.bn-ag.st-running .h { opacity:.45; animation:bn-pulse 1s ease-in-out infinite; transform-box:fill-box; transform-origin:center }
.bn-coin { cursor:pointer } .bn-coin .c { fill:var(--nn3) } .bn-coin .h { fill:var(--nn3); opacity:calc(.08 + .25 * var(--k)) }
.bn-coin.pick .c, .bn-coin.pick .h { fill:var(--nok) } .bn-coin.buy .c, .bn-coin.buy .h { fill:#ffd35c }
.bn-coin text { fill:var(--nfg); font-size:10px; font-weight:600; opacity:.8 }
.bn-coin.on .h { opacity:.55; animation:bn-pulse 1.6s ease-in-out infinite; transform-box:fill-box; transform-origin:center } .bn-coin.on text { opacity:1 }
.bn-core .o3 { fill:none; stroke:var(--nn2); stroke-width:.8; stroke-dasharray:1 5; opacity:.6; animation:bn-spin 30s linear infinite; transform-box:fill-box; transform-origin:center }
.bn-core .o2 { fill:none; stroke:var(--nn1); stroke-width:1; stroke-dasharray:14 6 2 6; opacity:.5; animation:bn-spin 18s linear infinite reverse; transform-box:fill-box; transform-origin:center }
.bn-core .o1 { fill:#0b0d22; stroke:var(--nn1); stroke-width:.6; opacity:.9 }
.bn-core .g { animation:bn-breathe 4s ease-in-out infinite; transform-box:fill-box; transform-origin:center }
.bn[data-state="live"] .bn-core .g { animation-duration:1.2s }
.bn-core .t1 { fill:#0b0d22; font-size:8.5px; font-weight:700; letter-spacing:.16em } .bn-core .t2 { fill:#0b0d22; font-size:7.5px; font-weight:600 }
.bn-focus { list-style:none; margin:0; padding:0; min-height:40px; display:grid }
.bn-focus li { grid-area:1 / 1; font-size:13px; line-height:1.4; color:#cfd6ff; padding:8px 12px; border-radius:12px; background:rgba(124,247,255,.06);
  border:1px solid rgba(124,247,255,.18); opacity:0; transform:translateY(4px); transition:opacity .4s, transform .4s; pointer-events:none }
.bn-focus li.on { opacity:1; transform:none } .bn-focus li b { color:var(--nn1) }
.bn-leg { display:flex; flex-wrap:wrap; gap:4px 14px; font-size:11px; color:var(--nmut) }
.bn-leg span::before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; vertical-align:0 }
.bn-leg .l-pick::before { background:var(--nok) } .bn-leg .l-rk::before { background:var(--nn3) } .bn-leg .l-ok::before { background:var(--nn1) }
.bn-leg .l-run::before { background:var(--nn1); box-shadow:0 0 6px var(--nn1) } .bn-leg .l-bad::before { background:var(--nbad) }
.bn-th h3 { font-size:13px; letter-spacing:.12em; text-transform:uppercase; color:var(--nmut); font-weight:500; margin:4px 0 8px }
.bn-th ol { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.bn-th li { display:grid; grid-template-columns:42px 1fr; gap:8px; font-size:13px; line-height:1.45; padding:8px 10px; border-radius:12px;
  background:rgba(255,255,255,.035); border-left:2px solid var(--nn2); animation:bn-in .6s ease-out both }
.bn-th li.go { border-left-color:var(--nok) } .bn-th li.no { border-left-color:#ffc35c } .bn-th li.see { border-left-color:var(--nn1) } .bn-th li.learn { border-left-color:var(--nn2) }
.bn-th li.now { border-left-color:var(--nn1); background:rgba(124,247,255,.08) }
.bn-th time { font-size:11px; color:var(--nmut); font-variant-numeric:tabular-nums; padding-top:2px } .bn-th span { color:#dfe4ff; overflow-wrap:anywhere }
.bn-tm h3 { font-size:13px; letter-spacing:.12em; text-transform:uppercase; color:var(--nmut); font-weight:500; margin:4px 0 4px }
.bn-tmh { margin:0 0 8px; font-size:12px; color:var(--nmut) } .bn-tmn { margin:8px 0 0; font-size:11px; color:var(--nmut) }
.bn-tm ul { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr)); gap:6px }
.bn-tm li { display:grid; grid-template-columns:10px 1fr auto; gap:8px; align-items:start; padding:8px 10px; border-radius:12px; background:rgba(255,255,255,.035); border:1px solid rgba(124,247,255,.08) }
.bn-tm li > i { width:8px; height:8px; border-radius:50%; margin-top:5px; background:var(--nn1); box-shadow:0 0 6px var(--nn1) }
.bn-tm li.st-failed > i { background:var(--nbad); box-shadow:0 0 6px var(--nbad) } .bn-tm li.st-fallback > i { background:#ffc35c; box-shadow:none }
.bn-tm li.st-skipped > i, .bn-tm li.st-absent > i { background:var(--nmut); box-shadow:none }
.bn-tm li.st-running { border-color:rgba(124,247,255,.4) } .bn-tm li.st-running > i { animation:bn-blink 1s ease-in-out infinite }
.bn-tm li div { display:grid; min-width:0 } .bn-tm b { font-size:13px; color:#e8ecff } .bn-tm small { font-size:11px; color:var(--nmut) }
.bn-tm span { font-size:12px; color:#c3cbef; overflow-wrap:anywhere; margin-top:2px } .bn-tm em { font-style:normal; font-size:12px; color:var(--nmut); font-variant-numeric:tabular-nums; white-space:nowrap }
.bn-coin .hit { fill:transparent } .bn-coin:focus { outline:none } .bn-coin:focus-visible .h { opacity:.8; stroke:#fff; stroke-width:1.2 }
.bn-focus li.on { pointer-events:auto; cursor:pointer } .bn-focus li:hover { border-color:rgba(124,247,255,.4) }
.bn-more { float:right; margin-left:10px; font-size:12px; font-weight:600; color:var(--nn1); white-space:nowrap }
.bn-leg .bn-tap { font-style:normal; color:var(--nn1); flex-basis:100% }
/* the coin sheet: a bottom sheet on a phone, a centred card on a wide screen; always dark like the brain */
html.bn-lock, html.bn-lock body { overflow:hidden }
.bn-dlg { position:fixed; inset:0; margin:auto auto 0; width:100%; max-width:560px; max-height:88vh; max-height:min(88dvh, 900px); padding:0; overflow:auto;
  overscroll-behavior:contain; color:var(--nfg); font-family:var(--sans); border:1px solid #2c3463; border-bottom:0; border-radius:20px 20px 0 0;
  background:radial-gradient(120% 50% at 50% 0%, #1a1440 0%, #0b0d22 60%, var(--nbg) 100%); box-shadow:0 -18px 50px -20px rgba(120,80,255,.55) }
.bn-dlg[open] { animation:bn-up .28s ease-out } .bn-dlg::backdrop { background:rgba(3,4,14,.66) }
.bn-dlg.fb { z-index:60 }
.bc-in { padding:0 16px calc(18px + env(safe-area-inset-bottom)) } .bc { display:grid; gap:12px; min-width:0 } .bc[hidden] { display:none }
.bc-hd { position:sticky; top:0; z-index:2; display:grid; grid-template-columns:minmax(0,1fr) auto auto; align-items:center; gap:10px; margin:0 -16px;
  padding:18px 12px 10px 16px; background:#0e0d28; border-bottom:1px solid rgba(124,247,255,.1) }
.bc-hd::before { content:""; position:absolute; top:7px; left:50%; width:38px; height:4px; margin-left:-19px; border-radius:4px; background:#3a4270 }
.bc-id { min-width:0 } .bc-id b { display:block; font-size:22px; font-weight:700; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.bc-id small { display:block; font-size:12px; color:var(--nmut); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.bc-chip { font-size:11px; font-weight:600; padding:4px 10px; border-radius:999px; border:1px solid currentColor; white-space:nowrap; color:var(--nn3) }
.bc-chip.pick { color:var(--nok) } .bc-chip.buy { color:#ffd35c }
.bc-x { appearance:none; -webkit-appearance:none; border:0; margin:0; width:40px; height:40px; border-radius:50%; background:rgba(255,255,255,.08); color:var(--nfg);
  font:400 24px/1 var(--sans); cursor:pointer; -webkit-tap-highlight-color:transparent } .bc-x:focus-visible { outline:2px solid var(--nn1); outline-offset:2px }
.bc-think { padding:10px 12px; border-radius:14px; background:rgba(183,107,255,.10); border:1px solid rgba(183,107,255,.28) }
.bc-think i { display:block; font-style:normal; font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--nn2); margin-bottom:4px }
.bc-think p { margin:0; font-size:14px; line-height:1.45; color:#e6e9ff }
.bc-kv { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; margin:0 }
.bc-kv div { padding:7px 10px; border-radius:10px; background:rgba(255,255,255,.04); min-width:0 } .bc-kv dt { font-size:11px; color:var(--nmut) }
.bc-kv dd { margin:1px 0 0; font-size:14px; font-weight:600; font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.bc-sec h4 { margin:0 0 6px; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--nmut); font-weight:500 }
.bc-ck { list-style:none; margin:0; padding:0; display:grid; gap:4px }
.bc-ck li { display:grid; grid-template-columns:16px auto minmax(0,1fr); gap:8px; align-items:baseline; font-size:13px; padding:6px 8px; border-radius:8px; background:rgba(255,255,255,.03) }
.bc-ck i { font-style:normal; font-weight:700; text-align:center; color:var(--nmut) } .bc-ck .ok i { color:var(--nok) } .bc-ck .warn i { color:#ffc35c } .bc-ck .bad i { color:var(--nbad) }
.bc-ck span { color:#cfd6ff } .bc-ck em { font-style:normal; text-align:right; color:#e8ecff; font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.bc-bar { height:8px; border-radius:8px; background:rgba(255,255,255,.08); overflow:hidden }
.bc-bar i { display:block; height:100%; border-radius:8px; background:linear-gradient(90deg,var(--nn1),var(--nn2)) } .bc-bar i.near { background:linear-gradient(90deg,var(--nn2),#ffc35c) }
.bc-bar i.buy { background:var(--nok) }
.bc-p { margin:0 0 4px; font-size:14px; overflow-wrap:anywhere } .bc-p.good { color:var(--nok) } .bc-p.bad { color:var(--nbad) }
.bc-s { margin:6px 0 0; font-size:12px; color:var(--nmut); overflow-wrap:anywhere }
.bc-go { appearance:none; -webkit-appearance:none; border:0; margin:0; padding:0; background:none; font:inherit; color:var(--nn1); text-decoration:underline; cursor:pointer }
.bc-why > summary, .bc-live > summary { cursor:pointer; font-size:13px; color:var(--nn1); padding:6px 0 }
.bc-why p { margin:4px 0 0; font-size:12px; line-height:1.5; color:#c3cbef; overflow-wrap:anywhere }
.bc-fr iframe { display:block; width:100%; height:380px; border:0; border-radius:12px; background:var(--nbg) }
.bc-lk { display:flex; flex-wrap:wrap; gap:6px } .bc-lk a { font-size:13px; padding:8px 12px; border-radius:999px; border:1px solid rgba(124,247,255,.3); color:var(--nn1);
  text-decoration:none; background:rgba(124,247,255,.06) }
.bc-t { margin:0; font-size:11px; line-height:1.5; color:var(--nmut) } .bc-t code { font-family:var(--mono); font-size:11px; word-break:break-all; color:#aab3dd }
@keyframes bn-up { from { transform:translateY(28px); opacity:0 } to { transform:none; opacity:1 } }
@media (min-width:700px) { .bn-dlg { margin:auto; border-bottom:1px solid #2c3463; border-radius:20px } .bc-hd::before { display:none } .bc-hd { padding-top:14px } }
@keyframes bn-flow { to { stroke-dashoffset:-20 } }
@keyframes bn-tw { 0%,100% { opacity:.15 } 50% { opacity:.6 } }
@keyframes bn-pulse { 0%,100% { transform:scale(1) } 50% { transform:scale(1.5) } }
@keyframes bn-breathe { 0%,100% { transform:scale(.94); opacity:.9 } 50% { transform:scale(1.06); opacity:1 } }
@keyframes bn-spin { to { transform:rotate(360deg) } }
@keyframes bn-blink { 50% { opacity:.3 } }
@keyframes bn-in { from { opacity:0; transform:translateY(6px) } to { opacity:1; transform:none } }
@media (min-width:700px) { .bn { padding:20px 24px } .bn-stage { max-width:640px; margin:0 auto; width:100% } }
@media (prefers-reduced-motion: reduce) { .bn *, .bn *::before { animation:none !important; transition:none !important } }
"""
