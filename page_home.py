"""page_home.py: the Start tab (#pane-home), the first thing the app shows. Fake money only: nothing here buys, signs or sends anything,
and nothing here is advice. English words (the user's wish of Oct 22: the whole app in English).

The product has two parts, and this tab shows both at a glance:
  PICK   the full scan's paper account (50 € a pick, its sell rule unchanged)
  RADAR  the rocket hunter's own paper account (rocket_watch.py, 20 € a coin when its rocket score reaches the cut)
and under them the Learning Pick (lernpick.py, a self-learning shadow with its own paper account) as a slim row whose tap opens its fold.
pick_account(D, R) -> HTML: the Pick tab's account block (balance since the start, the open pick positions as cards, the last sells, the
Radar for comparison), because the open Pick positions were only in the Archive. From memebot.LIVE_SELL_AT on (the Pick sells on the live
chart) it carries one more line that PK_LIVE_JS fills from the app's live row memebot.LIVE_WATCH_ROW: what the minute watch sold of the
positions this page still shows open, before the next scan books it.
section(D, R) -> HTML:
  - the two accounts side by side: balance, a small line of the balance over time, x of 10 closed trades in profit, the big hits
    (3x and 10x) and the open positions
  - "Right now": the current pick with its look-alike forecast (forecast.py) and the rocket hunter's best candidates of its last
    round, each with how close its score is to the buy cut
  - when the next scan and the last radar round ran, and a short map of the other tabs
Every number comes from the page data (D) and rocket.json; nothing here changes a pick, a sell rule or an account. The Pick side counts the
paper account's pick positions only (the new launches ended on Oct 16 and live in the Archive tab). Every chain string is escaped.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
MINUS = "−"
CANDS_SHOWN = 5           # rocket candidates on the Start tab (the Radar tab lists all of the last round)


def num(v):
    return M.num(v)


def de_num(v, d=2):
    """1234.5 -> 1,234.50 with a real minus sign (English notation since Oct 22; the name stays, other pages call it)."""
    s = format(abs(v), ",.%df" % d)
    return (MINUS if v < 0 and s.strip("0,.") else "") + s


def de_eur(v, signed=False):
    v = num(v)
    if v is None:
        return "–"
    s = de_num(v) + " €"
    return ("+" + s) if signed and v > 0.004 else s


def tone(v):
    v = num(v)
    return "good" if v is not None and v > 0.004 else ("bad" if v is not None and v < -0.004 else "")


def hhmm(R, ms):
    try:
        return R.local(ms).strftime("%H:%M")
    except Exception:
        return "–"


def when(R, ms, now):
    """'12:08' today, else 'Oct 21 12:08'."""
    try:
        t, n = R.local(ms), R.local(now)
    except Exception:
        return "–"
    return t.strftime("%H:%M") if t.date() == n.date() else t.strftime("%b %d %H:%M")


def rocket_doc(D):
    try:
        doc = json.load(open(os.path.join((D or {}).get("dir") or "", "db", "memebot", "rocket.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("book"), dict) else None


def pick_book(D):
    """The paper account's pick positions since the restart: balance (closed results plus the open ones at their last price), closed and
    open counts, x of 10 closed in profit, 3x and 10x hits, and the balance after every closed trade. None without the account."""
    try:
        import page_account as PA
        A = PA._acct(D)
    except Exception:
        return None
    rows = [r for r in (A or {}).get("rows") or [] if isinstance(r, dict) and r.get("grp") != "young" and num(r.get("pnl")) is not None]
    if not isinstance(A, dict):
        return None
    closed = sorted((r for r in rows if not r.get("open")), key=lambda r: num(r.get("exitT")) or num(r.get("t")) or 0)
    opn = [r for r in rows if r.get("open")]
    mult = lambda r: (num(r.get("back")) or 0) / (num(r.get("ticket")) or 1)
    pts, run = [], 0.0
    for r in closed:
        run += num(r["pnl"])
        pts.append(run)
    return {"bal": sum(num(r["pnl"]) for r in rows), "closed": len(closed), "open": len(opn),
            "win": round(10 * sum(1 for r in closed if num(r["pnl"]) > 0) / len(closed), 1) if closed else None,
            "x3": sum(1 for r in closed if mult(r) >= 3), "x10": sum(1 for r in closed if mult(r) >= 10), "pts": pts, "rows": rows,
            "ticket": num(getattr(M, "TOP_TICKET", None)) or 50.0}


def rocket_book(doc):
    """The rocket hunter's account from rocket.json: the same numbers as pick_book."""
    if not doc:
        return None
    bk = doc.get("book") or {}
    sm = bk.get("summary") or {}
    closed = sorted((p for p in bk.get("closed") or [] if isinstance(p, dict) and num(p.get("eur")) is not None), key=lambda p: num(p.get("out")) or num(p.get("t")) or 0)
    pts, run = [], 0.0
    for p in closed:
        run += num(p["eur"])
        pts.append(run)
    return {"bal": (num(sm.get("eur")) or 0.0) + (num(sm.get("openEur")) or 0.0), "closed": int(num(sm.get("trades")) or 0), "open": int(num(sm.get("open")) or 0),
            "win": num(sm.get("inProfitOf10")), "x3": int(num(sm.get("x3")) or 0), "x10": int(num(sm.get("x10")) or 0), "pts": pts, "ticket": float(M.TICKET), "t": num(doc.get("t")) or 0}


def spark(pts, cls):
    """The balance after every closed trade as a small line (break-even dashed); a flat placeholder before two trades."""
    if len(pts) < 2:
        return '<svg class="hm-sp" viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true"><line class="z" x1="0" y1="15" x2="120" y2="15"/></svg>'
    vs = [0.0] + list(pts)
    lo, hi = min(vs), max(vs)
    hi = hi if hi - lo > 1e-9 else lo + 1
    xy = [(120.0 * i / (len(vs) - 1), 2 + 26 * (hi - v) / (hi - lo)) for i, v in enumerate(vs)]
    d = " ".join("%s%.1f %.1f" % ("M" if i == 0 else "L", x, y) for i, (x, y) in enumerate(xy))
    z = 2 + 26 * hi / (hi - lo)
    return ('<svg class="hm-sp %s" viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true"><line class="z" x1="0" y1="%.1f" x2="120" y2="%.1f"/>'
            '<path class="a" d="%s L120 30 L0 30 Z"/><path class="l" d="%s"/></svg>') % (cls, z, z, d, d)


def since_words(R, ms):
    """'since Oct 22, 12:08' (Berlin; the page's own way to write a day), '' without a start."""
    try:
        return "since %s" % R.local(ms).strftime("%b %d, %H:%M") if num(ms) else ""
    except Exception:
        return ""


def acct_card(key, title, sub, b, empty, live=False, since=""):
    """One account card; live=True (the rocket hunter) adds the data-rk-* hooks page_rocket.LIVE_JS fills from the app's live row. since:
    the account's start in words (both accounts count from the same moment since the Pick's fresh start, memebot.FRESH_AT)."""
    head = '<div class="hm-k"><span class="hm-dot"></span>%s<small>%s</small></div>%s' % (
        E(title), E(sub), ('<small class="hm-since">%s</small>' % E(since)) if since else "")
    if not b:
        return ('<div class="hm-acc hm-%s">%s<p class="hm-empty">%s</p></div>') % (key, head, E(empty))
    h = (lambda k: ' data-rk-st="%s"' % k) if live else (lambda k: "")
    win = "–" if b["win"] is None else de_num(b["win"], 1).rstrip("0").rstrip(".")
    stats = [("in profit", ("<span%s>%s</span><small>/10</small>" % (h("win"), E(win))) if (b["win"] is not None or live) else "–"),
             ("3x · 10x", "<span%s>%d · %d</span>" % (h("hits"), b["x3"], b["x10"])),
             ("open", "<span%s>%d</span>" % (h("open"), b["open"]))]
    return ('<div class="hm-acc hm-%s"%s>%s'
            '<b class="hm-bal %s"%s>%s</b>%s<div class="hm-st">%s</div><small class="hm-n"><span%s>%d</span> closed · %s per buy · fake money</small></div>') % (
        key, (' data-rk-box data-rk-t="%d"' % int(b.get("t") or 0)) if live else "", head, tone(b["bal"]), " data-rk-bal" if live else "",
        E(de_eur(b["bal"], True)), spark(b["pts"], tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), v) for k, v in stats), h("closed"), b["closed"], E(de_eur(b["ticket"]).replace(".00", "")))


def lern_row(D, R):
    """The Learning Pick (lernpick.py, a self-learning shadow with its own paper account) as a slim row under the two accounts: its balance
    the way the Pick card counts it (sold trades plus the open ones at the last scan price), the sold trades' result as the fold's summary
    line says it, how many open, since its first buy. A tap opens the Pick tab with its fold open (the user could not find it at the foot
    of the Pick tab, Oct 23). '' without the module or when it cannot be read."""
    try:
        import lernpick as L
        S = L.summary((D or {}).get("dir") or "", (D or {}).get("now"))
        me = S["me"]
    except Exception:
        return ""
    if me["n"]:
        big = '<b class="hm-bal %s">%s</b>' % (tone(me["pnl"]), E(de_eur(me["pnl"], True)))
        line = "%s%d open · %s per buy · fake money" % (("%d sold %s · " % (me["sold"], de_eur(me["closedPnl"], True))) if me["sold"] else "",
                                                       me["open"], de_eur(S.get("ticket") or 50).replace(".00", ""))
    else:
        big = '<b class="hm-bal">–</b>'
        line = "buys from the next scan · fake money" if (S.get("brain") or {}).get("buy") else "waiting for its first training · fake money"
    since = since_words(R, S.get("since"))
    return ('<label class="hm-acc hm-lp" for="tab-pick" data-go="pick" data-open="learning-pick">'
            '<span class="hm-k"><span class="hm-dot"></span>LEARNING PICK<small>shadow · learns every day · no push</small></span>'
            '%s%s<span class="hm-lpf"><small class="hm-n">%s</small><span class="hm-go">Open ›</span></span></label>') % (
        ('<small class="hm-since">%s</small>' % E(since)) if since else "", big, E(line))


PICK_WHY = {"tp": "11x reached", "stop": "stop −30%", "time": "after 6 h", "rug": "coin gone", "reset": "restart", "manual": "by hand"}
PICK_SOLD = 5             # last sells in the Pick tab's account block


def pick_account(D, R):
    """The Pick tab's account block (the user could not find the open Pick positions on Oct 22; they sat in Archive > Three paper traders):
    the Pick account since its start (balance, the same stats as the Start card), every open pick position as the page's own position card
    (R.hold_card, tap opens: price since the buy, stop and target, the clock, the links), the last sells, and the Radar account for
    comparison. Display only; the account, its rule and the trades before the start stay where they were (Archive)."""
    now = D["now"]
    b = pick_book(D)
    since = since_words(R, ((D.get("paper") or {}).get("since")))
    ticket = de_eur(num(getattr(M, "TOP_TICKET", None)) or 50.0).replace(".00", "")
    head = ('<div class="pk-head"><div><h3>Pick account</h3><small>hourly pick · %s</small></div><span class="chip warn">fake money</span></div>' % E(
        " · ".join(x for x in (since, "%s per buy" % ticket) if x)))
    if not b:
        return '<div class="pk" data-pa="pick">%s<p class="pk-s">No pick bought since the start yet.</p></div><style>%s</style>' % (head, PK_CSS)
    win = "–" if b["win"] is None else de_num(b["win"], 1).rstrip("0").rstrip(".")
    stats = [("in profit", "%s/10" % win), ("3x · 10x", "%d · %d" % (b["x3"], b["x10"])), ("open", str(b["open"])), ("closed", str(b["closed"]))]
    acct = ('<div class="pk-acct"><div class="pk-bal"><span class="k">Balance</span><b class="%s">%s</b>%s</div><div class="pk-sts">%s</div></div>') % (
        tone(b["bal"]), E(de_eur(b["bal"], True)), spark(b["pts"], tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), E(v)) for k, v in stats))
    opn = [r for r in D.get("open") or [] if isinstance(r, dict) and (r.get("p") or {}).get("grp") == "hold"]
    cards = []
    for r in opn:
        try:
            cards.append(R.hold_card(r, now))
        except Exception:
            cards.append('<div class="pk-s">%s</div>' % E((r.get("p") or {}).get("sym") or "?"))
    t0 = num((D.get("paper") or {}).get("since")) or 0
    before = sum(1 for r in opn if (num((r.get("p") or {}).get("t")) or 0) < t0)
    op_html = ('<div class="pk-st"><span class="k">Open positions (%d)%s</span><div class="holds">%s</div></div>' % (
        len(opn), (" · %d bought before the start, not counted" % before) if before else "", "".join(cards)) if opn else
        '<div class="pk-st"><span class="k">Open positions (0)</span><p class="pk-s">None right now. Every scan buys its pick on paper for %s.</p></div>' % E(ticket))
    op_html += pick_live(opn, now)
    closed = sorted((r for r in b["rows"] if not r.get("open")), key=lambda r: -(num(r.get("exitT")) or num(r.get("t")) or 0))[:PICK_SOLD]
    sold = []
    for r in closed:
        ex = [e for e in r.get("status") or [] if isinstance(e, dict)]
        why = str(ex[-1].get("why") or "") if ex else ""
        pct = num(r.get("pct"))
        bits = [("%s%s%%" % ("+" if pct > 0 else "", de_num(100 * pct, 0))) if pct is not None else "", PICK_WHY.get(why, why),
                when(R, num(r.get("exitT")), now) if num(r.get("exitT")) else ""]
        sold.append('<li class="%s"><b>%s</b><span>%s</span><em>%s</em></li>' % (
            tone(r.get("pnl")), E(str(r.get("sym") or "?")[:14]), E(" · ".join(x for x in bits if x)), E(de_eur(r.get("pnl"), True))))
    sold_html = ('<div class="pk-st"><span class="k">Recently sold</span><ul class="pk-sold">%s</ul></div>' % "".join(sold)) if sold else ""
    rk = rocket_book(rocket_doc(D))
    cmp_ = ('<p class="pk-cmp">For comparison, Radar 🚀: <b class="%s">%s</b> · %d closed · %d open</p>' % (
        tone(rk["bal"]), E(de_eur(rk["bal"], True)), rk["closed"], rk["open"])) if rk else ""
    live_at = M.live_sell_at()
    foot = ('<p class="pk-s">Sells at −30%%, at 11x or after 6 h (the rule is unchanged). %s The trades before the start (%d) are in the archive under '
            '“Three paper traders”.</p>' % (E("%s %s it sells on the live chart: every minute, a dip to −30%% (the minute's low) or a jump to 11x (its high) sells "
                                               "at that minute, the 6 h limit 6 h after the purchase." % ("Since" if now >= live_at else "From", R.local(live_at).strftime("%b %d, %H:%M"))
                                             if hasattr(R, "local") else ""),
                                           sum(1 for r in (D.get("paper") or {}).get("old") or [] if isinstance(r, dict) and (r.get("p") or {}).get("grp") == "hold")))
    js = ("<script>%s</script>" % PK_LIVE_JS) if "data-pk-box" in op_html else ""
    return '<div class="pk" data-pa="pick">%s%s%s%s%s%s</div><style>%s</style>%s' % (head, acct, op_html, sold_html, foot, cmp_, PK_CSS, js)


def pick_live(opn, now):
    """The minute watch's line under the open pick positions (memebot.LIVE_SELL_AT on): empty and hidden on the page; PK_LIVE_JS shows the
    sales the watch saw of the positions listed here (data-pk-open: their ids), each at its minute, and when it looked last. '' before."""
    if now < M.live_sell_at():
        return ""
    ids = [str((r.get("p") or {}).get("_id") or "") for r in opn if (r.get("p") or {}).get("_id")]
    return ('<div class="pk-st pk-lv" data-pk-box data-pk-open="%s" hidden><span class="k" data-pk-head hidden>Sold on the live chart since this page '
            'was built (booked at that minute, the next scan adds it to the balance)</span><ul class="pk-sold" data-pk-sold></ul>'
            '<small class="pk-s" data-pk-line></small></div>') % E(json.dumps(ids, separators=(",", ":")))


# the Pick account's minute watch (memebot.LIVE_SELL_AT): the app's live row memebot.LIVE_WATCH_ROW, read while the Pick tab is open, every
# 45 s, the same way page_rocket.LIVE_JS reads the Radar's; text only (no HTML from the row)
PK_LIVE_JS = r"""
(function(){
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var box=document.querySelector('[data-pk-box]');
  if(!box||!/^https:\/\/[^\s\/]+$/.test(url)||!key||!window.fetch)return;
  var ids;try{ids=JSON.parse(box.getAttribute('data-pk-open')||'[]');}catch(e){ids=[];}
  var EVERY=45000,next=0,busy=false,MINUS='−',WHY={stop:'stop −30%',tp:'11x reached',time:'after 6 h'};
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function de(v,d){var s=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});return (v<0&&/[1-9]/.test(s)?MINUS:'')+s;}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
  function apply(d){
    var sold=d.sold&&typeof d.sold==='object'?d.sold:{},pos=d.pos&&typeof d.pos==='object'?d.pos:{},u=box.querySelector('[data-pk-sold]'),rows=[];
    ids.forEach(function(id){var x=sold[id];if(x&&typeof x==='object'&&n(x.at))rows.push(x);});
    rows.sort(function(a,b){return n(b.at)-n(a.at);});
    if(u){u.textContent='';rows.forEach(function(x){var v=n(x.pnl)||0,li=el('li',v>0.004?'good':(v<-0.004?'bad':''));
      li.appendChild(el('b',null,String(x.sym||'?').slice(0,14)));
      li.appendChild(el('span',null,['x'+de(n(x.mult)||0,2),WHY[x.why]||String(x.why||''),hhmm(n(x.at))].filter(Boolean).join(' · ')));
      li.appendChild(el('em',null,(v>0.004?'+':'')+de(v,2)+' €'));u.appendChild(li);});}
    var w=ids.filter(function(id){return pos[id]&&!sold[id];}).length,line=box.querySelector('[data-pk-line]');
    if(line)line.textContent='Live chart · last look '+(n(d.t)?hhmm(n(d.t)):'–')+' · '+w+' of '+ids.length+' open position'+(ids.length===1?'':'s')+' watched every minute';
    var hd=box.querySelector('[data-pk-head]');if(hd){if(rows.length)hd.removeAttribute('hidden');else hd.setAttribute('hidden','');}
    if(rows.length||ids.length)box.removeAttribute('hidden');
  }
  function want(){if(document.visibilityState==='hidden')return false;var a=document.getElementById('tab-pick');return !a||!!a.checked;}
  function poll(){
    if(busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+EVERY;
    var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    fetch(url+'/rest/v1/live?select=doc&id=eq.""" + M.LIVE_WATCH_ROW + r"""',{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status;return r.json();})
      .then(function(rows){var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;if(d&&typeof d==='object')apply(d);})
      .catch(function(){next=Date.now()+2*EVERY;})
      .then(function(){clearTimeout(tm);busy=false;});
  }
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&e.target.id==='tab-pick')poll();});
  setInterval(poll,5000);poll();
})();
"""


PK_CSS = r"""
/* the Pick tab's account block (page_home.pick_account), the same look as the rocket hunter's block on the Radar tab */
.pk { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:14px 16px 10px; display:grid; gap:12px; min-width:0; margin:0 0 12px;
  background-image:radial-gradient(120% 80% at 100% 0%, color-mix(in srgb,var(--accent) 14%,transparent), transparent 60%) }
.pk-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:4px 10px } .pk-head h3 { margin:0; font-size:19px }
.pk-head small { font-size:var(--fs-xs); color:var(--muted) }
.pk-acct { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:12px; align-items:center }
.pk-bal { display:grid; gap:2px; min-width:0 } .pk-bal b { font-size:28px; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; white-space:nowrap }
.pk-bal b.good { color:var(--good) } .pk-bal b.bad { color:var(--bad) }
.pk .k { font-size:var(--fs-xs); color:var(--muted) }
.pk-sts { display:grid; grid-template-columns:1fr 1fr; gap:6px }
.pk-sts > span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
.pk-sts i { font-style:normal; font-size:11px; color:var(--muted) } .pk-sts b { font-size:15px; font-variant-numeric:tabular-nums }
.pk-st { display:grid; gap:6px; min-width:0 } .pk-st .holds { display:grid; gap:8px; min-width:0 }
.pk-sold { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.pk-sold li { display:grid; grid-template-columns:minmax(0,1fr) auto; column-gap:10px; font-size:var(--fs-s) }
.pk-sold li span { grid-column:1; color:var(--fg2); font-size:var(--fs-xs) }
.pk-sold li em { grid-column:2; grid-row:1 / span 2; align-self:center; font-style:normal; font-variant-numeric:tabular-nums; font-weight:600 }
.pk-sold li.good em { color:var(--good) } .pk-sold li.bad em { color:var(--bad) }
.pk-s { margin:0; font-size:var(--fs-xs); color:var(--muted); max-width:70ch; overflow-wrap:anywhere }
.pk-cmp { margin:0; font-size:var(--fs-s); color:var(--fg2); padding-top:8px; border-top:1px solid var(--line) }
.pk-cmp b.good { color:var(--good) } .pk-cmp b.bad { color:var(--bad) }
@media (max-width:420px) { .pk-acct { grid-template-columns:1fr } }
"""


def pick_now(D, R):
    """The current pick: symbol, tier, safety, the trained odds and the look-alike forecast (forecast.py), and a way to its full card."""
    picks = [c for c in ((D.get("rec") or {}).get("picks") or []) if isinstance(c, dict)]
    if not picks:
        return ('<div class="hm-now hm-pick"><div class="hm-nh"><span class="hm-tag">Pick</span></div>'
                '<p class="hm-empty">No pick right now: no coin passed every filter and the safety check.</p></div>')
    p = picks[0]
    fc = None
    try:
        import forecast as FC
        fc = FC.forecast(p.get("f"))
    except Exception:
        fc = None
    rows = []
    po, pz = num(p.get("upP")), num(p.get("zeroP"))
    if po is not None:
        rows.append(("Chance of a profit (2 h)", "%d%%" % round(100 * po)))
    if pz is not None:
        rows.append(("Chance of going to zero", "%d%%" % round(100 * pz)))
    if fc:
        rows += [("Similar coins: 2x in 6 h", "%d%%" % round(100 * fc["x2"])), ("Similar coins: 3x in 6 h", "%d%%" % round(100 * fc["x3"]))]
    tier = {"strong": "strong pick", "fair": "fair pick", "weak": "weak pick"}.get(str(p.get("tier") or ""), "")
    held = ""
    hr = next((r for r in (pick_book(D) or {}).get("rows") or [] if r.get("open") and (r.get("p") or {}).get("addr") == p.get("addr")), None)
    if hr and num(hr.get("pct")) is not None:
        held = '<span class="hm-chip %s">bought · %s%%</span>' % (tone(hr["pct"]), E(("+" if hr["pct"] > 0 else "") + de_num(100 * hr["pct"], 1)))
    meta = []
    if num(p.get("mc")):
        meta.append("MC %s" % R.fmt_money(p.get("mc")))
    if num((p.get("f") or {}).get("ageH")) is not None:
        meta.append("%s h old" % de_num(num(p["f"]["ageH"]), 0))
    if num(p.get("score")) is not None:
        meta.append("Score %d" % round(num(p["score"])))
    return ('<div class="hm-now hm-pick"><div class="hm-nh"><span class="hm-tag">Pick</span><small>for the next 2 hours</small></div>'
            '<div class="hm-coin"><b>%s</b><span>%s</span>%s%s%s</div><small class="hm-meta">%s</small>%s'
            '<label class="hm-go" for="tab-pick" data-go="pick">All about the pick ›</label></div>') % (
        E(p.get("sym") or "?"), E(str(p.get("name") or "")[:28]), ('<span class="hm-chip">%s</span>' % E(tier)) if tier else "",
        '<span class="hm-chip good">safety: clean</span>' if p.get("ok") else "", held, E(" · ".join(meta)),
        ('<div class="hm-odds">%s</div>' % "".join('<span><i>%s</i><b>%s</b></span>' % (E(k), E(v)) for k, v in rows)) if rows else "")


def rocket_now(D, R, doc):
    """The rocket hunter's best candidates of its last round, each with a bar: its score as a share of the buy cut (100 % buys)."""
    head = '<div class="hm-nh"><span class="hm-tag rad">Radar 🚀</span><small>Rocket candidates · buys at 100%</small></div>'
    if not doc:
        return '<div class="hm-now hm-rd">%s<p class="hm-empty">The rocket hunter has not run yet: it checks the new coins every 15 minutes.</p></div>' % head
    cut = num(doc.get("cut")) or 0
    rows = []
    for r in [r for r in doc.get("top") or [] if isinstance(r, dict)][:CANDS_SHOWN]:
        sc = num(r.get("score")) or 0
        share = sc / cut if cut > 0 else 0
        w = max(2.0, min(100.0, 100 * share))
        rows.append('<li class="%s"><b>%s</b><span class="hm-bar"><i style="width:%.1f%%"></i></span><em>%s</em><small>%s</small></li>' % (
            "buy" if r.get("buy") else ("near" if share >= 0.5 else ""), E(str(r.get("sym") or str(r.get("addr") or "?")[:6])[:14]), w,
            "bought" if r.get("buy") else "%d%%" % round(100 * share), E("%d min old" % int(num(r.get("age")) or 0))))
    rd = doc.get("round") or {}
    t = num(doc.get("t"))
    foot = "Last round %s · %s coins watched · %d scored · %d bought" % (
        when(R, t, D["now"]) if t else "–", de_num(int(num(rd.get("candidates")) or 0), 0), int(num(rd.get("scored")) or 0), int(num(rd.get("bought")) or 0))
    body = ('<ul class="hm-cands" data-rk-cands="hm">%s</ul>' % "".join(rows)) if rows else '<p class="hm-empty">No coin of the right age in the last round.</p>'
    return ('<div class="hm-now hm-rd" data-rk-box data-rk-t="%d">%s%s<small class="hm-meta">%s</small><label class="hm-go" for="tab-young" data-go="young">Go to Radar ›</label></div>') % (
        int(t or 0), head, body, E(foot))


def section(D, R):
    now = D["now"]
    doc = rocket_doc(D)
    pk, rk = pick_book(D), rocket_book(doc)
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and num(r.get("t"))]
    nxt = R.next_scan_ms(now, runs)
    status = ['<span><i class="hm-pulse"></i>Pick scan last %s · next ≈ %s</span>' % (E(hhmm(R, num(runs[0]["t"]))) if runs else "–", E(hhmm(R, nxt)))]
    if doc and num(doc.get("t")):
        status.append('<span><i class="hm-pulse rad"></i>Rocket radar last %s · every 15 min</span>' % E(hhmm(R, num(doc["t"]))))
    # both accounts count from the same moment since the Pick's fresh start (memebot.FRESH_AT, the rocket hunter's first round)
    cards = (acct_card("pick", "PICK", "Pick account", pk, "No pick bought since the start yet.", since=since_words(R, (D.get("paper") or {}).get("since")))
             + acct_card("rad", "RADAR", "Radar account 🚀", rk, "Starts with the first radar round.", live=True, since=since_words(R, getattr(M, "FRESH_AT", None))))
    lp = lern_row(D, R)
    nav = [("pick", "Pick", "The pick, its safety check, hour by hour"), ("young", "Radar", "Rocket hunter and launch radar"),
           ("office", "Brain", "What the bot is thinking"), ("account", "Archive", "Research, old traders, all the data")]
    return ('<style>%s</style><section class="hm" data-home>'
            '<div class="hm-hero"><div class="hm-ey">%s accounts · fake money · no real trades</div><div class="hm-accs">%s%s</div></div>'
            '<div class="hm-status">%s</div>'
            '<h2 class="hm-h">Right now</h2><div class="hm-nows">%s%s</div>'
            '<nav class="hm-nav">%s</nav></section><script>%s</script>') % (
        CSS, "Three" if lp else "Two", cards, lp, "".join(status), pick_now(D, R), rocket_now(D, R, doc),
        "".join('<label for="tab-%s" data-go="%s"><b>%s</b><small>%s</small></label>' % (k, k, E(n), E(s)) for k, n, s in nav), JS)


JS = r"""
(function(){
// a link on the Start tab opens its tab; in the installed app through its own tab switch (so the bottom bar follows), at the top, or
// with data-open at that fold, opened (the Learning Pick row)
document.addEventListener('click',function(e){var l=e.target&&e.target.closest?e.target.closest('[data-home] [data-go]'):null;if(!l)return;
  var f=document.getElementById(l.getAttribute('data-open')||'');
  function show(){try{if(!f){window.scrollTo(0,0);return;}f.open=true;      // below the website's sticky tab bar (none in the app)
    var b=document.querySelector('.tabbar'),c=b?getComputedStyle(b):null,off=c&&c.position==='sticky'&&b.offsetHeight?(parseFloat(c.top)||0)+b.offsetHeight+10:12;
    window.scrollTo(0,Math.max(0,f.getBoundingClientRect().top+(window.scrollY||0)-off));}catch(x){}}
  var A=window.MemebotApp;if(A&&typeof A.select==='function'){e.preventDefault();A.select(l.getAttribute('data-go'),'top');if(f)setTimeout(show,0);return;}
  setTimeout(show,0);});
})();
"""

CSS = r"""
/* the Start tab (page_home.py): two account cards side by side, then the pick and the rocket candidates, then a map of the other tabs */
.hm { display:grid; gap:14px } .hm [hidden] { display:none !important }
.hm-hero { position:relative; border-radius:18px; padding:14px; overflow:hidden; border:1px solid var(--line);
  background:radial-gradient(120% 90% at 0% 0%, color-mix(in srgb,var(--accent) 22%,transparent), transparent 60%),
             radial-gradient(120% 90% at 100% 100%, color-mix(in srgb,var(--nn2) 20%,transparent), transparent 60%), var(--surface) }
.hm-ey { font-size:var(--fs-xs); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0 2px 10px }
.hm-accs { display:grid; grid-template-columns:1fr 1fr; gap:10px }
.hm-acc { min-width:0; display:grid; gap:6px; align-content:start; padding:12px; border-radius:14px; background:color-mix(in srgb,var(--bg) 55%,transparent);
  border:1px solid color-mix(in srgb,var(--fg) 8%,transparent); backdrop-filter:blur(6px) }
.hm-k { display:flex; flex-wrap:wrap; align-items:center; gap:2px 6px; font-weight:600; letter-spacing:.06em; font-size:var(--fs-s) }
.hm-k small { font-weight:400; letter-spacing:0; color:var(--muted); font-size:var(--fs-xs) } .hm-since { font-size:11px; color:var(--fg2); margin-top:-4px }
.hm-dot { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent) }
.hm-rad .hm-dot { background:var(--nn2); box-shadow:0 0 10px var(--nn2) }
.hm-bal { font-size:clamp(19px,5.6vw,30px); font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; line-height:1.1; white-space:nowrap }
.hm-bal.good { color:var(--good) } .hm-bal.bad { color:var(--bad) }
.hm-sp { width:100%; height:30px; display:block } .hm-sp .z { stroke:var(--muted); stroke-dasharray:2 3; stroke-width:1; vector-effect:non-scaling-stroke; opacity:.6 }
.hm-sp .l { fill:none; stroke:var(--accent); stroke-width:1.6; vector-effect:non-scaling-stroke } .hm-sp .a { fill:var(--accent); opacity:.12 }
.hm-sp.good .l { stroke:var(--good) } .hm-sp.good .a { fill:var(--good) } .hm-sp.bad .l { stroke:var(--bad) } .hm-sp.bad .a { fill:var(--bad) }
.hm-st { display:grid; grid-template-columns:repeat(3,auto); justify-content:space-between; gap:4px }
.hm-st > span { display:grid; min-width:0 } .hm-st i { font-style:normal; font-size:11px; color:var(--muted) }
.hm-st b { font-size:15px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap } .hm-st small { font-size:11px; font-weight:400; color:var(--muted); margin:0 3px 0 1px }
.hm-n { font-size:11px; color:var(--muted) } .hm-empty { margin:0; font-size:var(--fs-s); color:var(--fg2) }
.hm-status { display:flex; flex-wrap:wrap; gap:6px 16px; font-size:var(--fs-xs); color:var(--fg2); padding:0 4px }
.hm-status span { display:inline-flex; align-items:center; gap:6px }
.hm-pulse { width:7px; height:7px; border-radius:50%; background:var(--good-mark); animation:hm-p 2.4s ease-in-out infinite } .hm-pulse.rad { background:var(--nn2) }
@keyframes hm-p { 0%,100% { box-shadow:0 0 0 0 color-mix(in srgb,currentColor 0%,transparent); opacity:1 } 50% { opacity:.45 } }
.hm-h { margin:6px 2px 0; font-size:17px }
.hm-nows { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr)); gap:10px }
.hm-now { min-width:0; display:grid; gap:8px; align-content:start; padding:12px 14px; border-radius:14px; background:var(--surface); border:1px solid var(--line) }
.hm-nh { display:flex; align-items:center; gap:8px } .hm-nh small { color:var(--muted); font-size:var(--fs-xs) }
.hm-tag { font-size:11px; font-weight:600; letter-spacing:.08em; text-transform:uppercase; padding:2px 8px; border-radius:999px;
  color:var(--accent); background:color-mix(in srgb,var(--accent) 16%,transparent) }
.hm-tag.rad { color:var(--nn2); background:color-mix(in srgb,var(--nn2) 16%,transparent) }
.hm-coin { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 8px } .hm-coin > b { font-size:22px; font-weight:600 } .hm-coin > span { color:var(--fg2); font-size:var(--fs-s) }
.hm-chip { font-size:11px; padding:1px 8px; border-radius:999px; background:var(--chip); color:var(--fg2); align-self:center }
.hm-chip.good { color:var(--good); background:color-mix(in srgb,var(--good) 14%,transparent) } .hm-chip.bad { color:var(--bad); background:color-mix(in srgb,var(--bad) 14%,transparent) }
.hm-meta { font-size:var(--fs-xs); color:var(--muted) }
.hm-odds { display:grid; grid-template-columns:1fr 1fr; gap:6px }
.hm-odds span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
.hm-odds i { font-style:normal; font-size:11px; color:var(--muted) } .hm-odds b { font-size:16px; font-variant-numeric:tabular-nums }
.hm-go { justify-self:start; color:var(--accent); font-size:var(--fs-s); font-weight:500; cursor:pointer; padding:6px 0; min-height:32px }
.hm-cands { list-style:none; margin:0; padding:0; display:grid; gap:6px }
.hm-cands li { display:grid; grid-template-columns:minmax(64px,auto) 1fr auto; grid-template-rows:auto auto; column-gap:10px; align-items:center; font-size:var(--fs-s) }
.hm-cands li b { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:110px }
.hm-cands li em { font-style:normal; font-variant-numeric:tabular-nums; color:var(--fg2); text-align:right; min-width:40px }
.hm-cands li small { grid-column:1 / -1; font-size:11px; color:var(--muted); margin-top:-2px }
.hm-bar { height:6px; border-radius:6px; background:color-mix(in srgb,var(--fg) 8%,transparent); overflow:hidden }
.hm-bar i { display:block; height:100%; border-radius:6px; background:linear-gradient(90deg,var(--accent),var(--nn2)) }
.hm-cands li.near em { color:var(--warn) } .hm-cands li.buy em { color:var(--good); font-weight:600 } .hm-cands li.buy .hm-bar i { background:var(--good-mark) }
.hm-nav { display:grid; grid-template-columns:1fr 1fr; gap:8px }
.hm-nav label { display:grid; gap:2px; padding:10px 12px; border-radius:12px; border:1px solid var(--line); background:var(--surface); cursor:pointer; min-height:44px }
.hm-nav label:hover { border-color:var(--accent) } .hm-nav b { font-size:var(--fs-m) } .hm-nav small { font-size:11px; color:var(--muted) }
.hm-lp { grid-column:1 / -1; grid-template-columns:minmax(0,1fr) auto; column-gap:12px; cursor:pointer; text-decoration:none; color:inherit }
.hm-lp > .hm-k, .hm-lp > .hm-since { grid-column:1 } .hm-lp > .hm-bal { grid-column:2; grid-row:1 / span 2; align-self:center }
.hm-lp .hm-dot { background:var(--good); box-shadow:0 0 10px var(--good) } .hm-lp:hover { border-color:var(--accent) }
.hm-lpf { grid-column:1 / -1; display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:4px 10px } .hm-lpf .hm-go { padding:0; min-height:0 }
@media (min-width:700px) { .hm-nav { grid-template-columns:repeat(4,1fr) } .hm-hero { padding:18px } .hm-acc { padding:16px } }
@media (max-width:360px) { .hm-accs { grid-template-columns:1fr } }
@media (prefers-reduced-motion: reduce) { .hm-pulse { animation:none } }
"""
