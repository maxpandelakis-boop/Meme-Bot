"""The rocket hunter on the page (fake money only, nothing is ever bought for real): report.py shows it at the top of the Radar tab.

section(D) -> HTML, a compact block "Rocket hunter (paper)":
  - the two paper accounts side by side: Pick (the scan's paper account, its sell rule unchanged) and Rocket hunter (its own
    account: rocket_watch.py buys a coin once when its score reaches the cut, rule A sells it), each with its balance, how many of
    10 closed trades ended in profit, and its 3x/10x hits
  - the rocket hunter's open positions and the best scores of its last round
  - one honest line: the model was positive on the earlier days only on few coins; this account is its live test
D: report.py's page data; reads D["dir"]/db/memebot/rocket.json (rocket_watch.py writes it on the branch rocket-data, the scan job
copies it) and, for the Pick side, page_account's numbers. Every value goes through a number check or html.escape. No script in
section(); LIVE_JS (report.py puts it after the block) reads the app's live row "rocket" (rocket_watch.py writes it every round) while
the Radar or Start tab is open, so the account, its open positions, its last sells and the candidates move between two scans; it
only fills the data-rk-* hooks of both tabs with textContent, and rocket.json stays what the page shows without the live store.
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
DOC = ("db", "memebot", "rocket.json")
SHOWN = 5                 # candidates in view on the Radar tab; the rest of the round behind "N weitere"
SOLD = 5                  # last sells on the Radar tab
WHY = {"stop": "Stopp −30 %", "11x": "11x erreicht", "6h": "nach 6 h", "gone": "Coin weg"}


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


def sym(p, a=None):
    return str(p.get("sym") or str(p.get("addr") or a or "?")[:6])[:14]


def open_li(PH, p, a=None):
    return '<li><b>%s</b><span>gekauft bei Score %s · jetzt x%s · Hoch x%s</span></li>' % (
        E(sym(p, a)), E(PH.de_num(num(p.get("score")) or 0, 3)), E(PH.de_num(num(p.get("now")) or 1.0)), E(PH.de_num(num(p.get("hi")) or 1.0)))


def sold_li(PH, p):
    """One sell: symbol, multiple, why and when, the result in euro (LIVE_JS builds the same row)."""
    try:
        import page_account as PA
        at = PA.hhmm(p["out"]) if num(p.get("out")) else ""
    except Exception:
        at = ""
    v = num(p.get("eur")) or 0.0
    bits = ["x" + PH.de_num(num(p.get("mult")) or 0.0), WHY.get(str(p.get("why") or ""), str(p.get("why") or "")), at]
    return '<li class="%s"><b>%s</b><span>%s</span><em>%s</em></li>' % (
        PH.tone(v), E(sym(p)), E(" · ".join(b for b in bits if b)), E(PH.de_eur(v, True)))


def section(D):
    """The Radar tab's top block: the rocket hunter's own account, its open positions, every candidate of its last round with a bar to the
    buy cut, the rules in one line and the Pick account for comparison."""
    import page_home as PH
    doc = load((D or {}).get("dir"))
    head = ('<div class="rk-head"><div><h3>Raketen-Jäger</h3><small>Rocket hunter · eigenes Papierkonto</small></div>'
            '<span class="chip warn">Spielgeld</span></div>')
    wrap = lambda inner: '<div class="rk" data-pa="rocket"%s>%s%s</div><style>%s</style>' % (
        (' data-rk-box data-rk-t="%d"' % int(num(doc.get("t")) or 0)) if doc else "", head, inner, CSS)
    ps = pick_side(D)
    cmp_ = ('<p class="rk-cmp">Zum Vergleich Pick: <b class="%s">%s</b> · %s/10 im Plus · %d abgeschlossen</p>' % (
        PH.tone(ps["bal"]), E(PH.de_eur(ps["bal"], True)), E("–" if ps["win"] is None else PH.de_num(ps["win"], 1)), ps["trades"])) if ps else ""
    if doc is None:
        return wrap('<p class="rk-s">Der Raketen-Jäger ist noch nicht gelaufen: er prüft alle 15 Minuten die Coins des Radars und kauft auf '
                    'Papier nur, wenn der Raketen-Score eines Coins die Schwelle erreicht.</p>' + cmp_)
    b = PH.rocket_book(doc)
    win = "–" if b["win"] is None else PH.de_num(b["win"], 1).rstrip("0").rstrip(",")
    stats = [("im Plus", '<span data-rk-st="win">%s</span>/10' % E(win), ""), ("3x · 10x", "%d · %d" % (b["x3"], b["x10"]), "hits"),
             ("offen", str(b["open"]), "open"), ("abgeschlossen", str(b["closed"]), "closed")]
    acct = ('<div class="rk-acct"><div class="rk-bal"><span class="k">Kontostand</span><b class="%s" data-rk-bal>%s</b>%s</div><div class="rk-sts">%s</div></div>') % (
        PH.tone(b["bal"]), E(PH.de_eur(b["bal"], True)), PH.spark(b["pts"], PH.tone(b["pts"][-1] if b["pts"] else 0)),
        "".join('<span><i>%s</i><b%s>%s</b></span>' % (E(k), (' data-rk-st="%s"' % c) if c else "", v if not c else E(v)) for k, v, c in stats))
    bk = doc.get("book") or {}
    op = [open_li(PH, p, a) for a, p in sorted((bk.get("open") or {}).items(), key=lambda kv: -(num(kv[1].get("t")) or 0)) if isinstance(p, dict)]
    sold = [sold_li(PH, p) for p in sorted((p for p in bk.get("closed") or [] if isinstance(p, dict)), key=lambda p: -(num(p.get("out")) or 0))[:SOLD]]
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
            + '<p class="rk-s rk-live" data-rk-live hidden></p>'
            + '<div class="rk-st" data-rk-opw%s><span class="k">Offene Positionen</span><ul class="rk-op" data-rk-op>%s</ul></div>' % ("" if op else " hidden", "".join(op))
            + '<div class="rk-st" data-rk-soldw%s><span class="k">Zuletzt verkauft</span><ul class="rk-sold" data-rk-sold>%s</ul></div>' % ("" if sold else " hidden", "".join(sold))
            + ('<div class="rk-st"><span class="k">Kandidaten der letzten Runde · Kauf ab 100 %% der Schwelle (%s)</span><ul class="rk-cands" data-rk-cands="rk">%s</ul>%s</div>' % (
                E(PH.de_num(cut, 4)), "".join(rows[:SHOWN]), ('<details class="rk-more" data-rk-more><summary>%d weitere</summary><ul class="rk-cands">%s</ul></details>' % (
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
.rk-sts > span { display:grid; padding:6px 8px; border-radius:10px; background:color-mix(in srgb,var(--fg) 4%,transparent) }
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
.rk-sold li { display:grid; grid-template-columns:minmax(0,1fr) auto; column-gap:10px; font-size:var(--fs-s); padding:4px 6px; border-radius:10px; margin:0 -6px }
.rk-sold li span { grid-column:1; color:var(--fg2); font-size:var(--fs-xs) } .rk-sold li em { grid-column:2; grid-row:1 / span 2; align-self:center; font-style:normal; font-variant-numeric:tabular-nums; font-weight:600 }
.rk-sold li.good em { color:var(--good) } .rk-sold li.bad em { color:var(--bad) }
.rk-sold li.new, .rk-op li.new { background:color-mix(in srgb,var(--nn1) 12%,transparent); animation:rkNew 2.4s ease-out 2 }
@keyframes rkNew { 0% { box-shadow:0 0 0 0 color-mix(in srgb,var(--nn1) 60%,transparent) } 100% { box-shadow:0 0 0 10px transparent } }
.rk-live { display:flex; align-items:center; gap:6px; color:var(--fg2) } .rk-live::before, .hm-live::before { content:""; width:7px; height:7px; border-radius:50%;
  background:var(--good); box-shadow:0 0 8px var(--good); flex:none }
@media (prefers-reduced-motion:reduce) { .rk-sold li.new, .rk-op li.new { animation:none } }
@media (max-width:560px) { .rk { padding:12px 12px 8px } .rk-acct { grid-template-columns:1fr } }
"""


# The live row "rocket" of the app's live store (rocket_watch.py writes it after every 15-minute round): one GET with the publishable key
# (data-sb-url/data-sb-key on <html>, set by bot.py site) every 45 s while the page is visible and the Radar or Start tab is open. It
# fills the data-rk-* hooks of every [data-rk-box] whose scan copy (data-rk-t) is not newer, only with textContent; without the store,
# or when a read fails, the page keeps what the scan wrote (rocket.json).
LIVE_JS = r"""
(function(){
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var boxes=[].slice.call(document.querySelectorAll('[data-rk-box]'));
  if(!/^https:\/\/[^\s\/]+$/.test(url)||!key||!boxes.length||!window.fetch)return;
  var EVERY=45000,SOLD=5,SHOWN=5,next=0,busy=false,seen=null,MINUS='−';
  var WHY={stop:'Stopp −30 %','11x':'11x erreicht','6h':'nach 6 h',gone:'Coin weg'};
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function de(v,d){var s=Math.abs(v).toLocaleString('de-DE',{minimumFractionDigits:d,maximumFractionDigits:d});return (v<0&&/[1-9]/.test(s)?MINUS:'')+s;}
  function eur(v){return (v>0.004?'+':'')+de(v,2)+' €';}
  function tone(v){return v>0.004?'good':(v<-0.004?'bad':'');}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function sym(p){return String(p.sym||String(p.addr||'?').slice(0,6)).slice(0,14);}
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
  function li(cls,b,span,em){var e=el('li',cls);e.appendChild(el('b',null,b));if(span!=null)e.appendChild(el('span',null,span));if(em!=null)e.appendChild(el('em',null,em));return e;}
  function fill(box,sel,items){var u=box.querySelector(sel);if(!u)return null;u.textContent='';items.forEach(function(x){u.appendChild(x);});return u;}
  function show(w,on){if(w){if(on)w.removeAttribute('hidden');else w.setAttribute('hidden','');}}
  function set(box,k,v){[].forEach.call(box.querySelectorAll('[data-rk-st="'+k+'"]'),function(e){e.textContent=v;});}
  function apply(d){
    var s=d.summary,t=n(d.t)||0,cut=n(d.cut)||0,bal=(n(s.eur)||0)+(n(s.openEur)||0),w=n(s.inProfitOf10);
    var now=(Array.isArray(d.soldNow)?d.soldNow:[]).map(String);
    var op=(Array.isArray(d.open)?d.open:[]).filter(function(p){return p&&typeof p==='object';}).sort(function(a,b){return (n(b.t)||0)-(n(a.t)||0);});
    var cl=(Array.isArray(d.closed)?d.closed:[]).filter(function(p){return p&&typeof p==='object';}).sort(function(a,b){return (n(b.out)||0)-(n(a.out)||0);}).slice(0,SOLD);
    var ids=cl.map(function(p){return String(p.addr)+'@'+(n(p.out)||0);}),fresh=function(p){var id=String(p.addr)+'@'+(n(p.out)||0);
      return now.indexOf(String(p.addr))>=0||(seen!==null&&seen.indexOf(id)<0);};
    boxes.forEach(function(box){
      if(t<(n(box.getAttribute('data-rk-t'))||0))return;
      [].forEach.call(box.querySelectorAll('[data-rk-bal]'),function(e){e.textContent=eur(bal);e.classList.remove('good','bad');if(tone(bal))e.classList.add(tone(bal));});
      set(box,'win',w===null?'–':de(w,1).replace(/,0$/,''));
      set(box,'hits',(n(s.x3)||0)+' · '+(n(s.x10)||0));
      set(box,'open',String(n(s.open)||0));set(box,'closed',String(n(s.trades)||0));
      var u=fill(box,'[data-rk-op]',op.map(function(p){return li('',sym(p),'gekauft bei Score '+de(n(p.score)||0,3)+' · jetzt x'+de(n(p.now)||1,2)+' · Hoch x'+de(n(p.hi)||1,2));}));
      if(u)show(u.closest('[data-rk-opw]'),op.length);
      u=fill(box,'[data-rk-sold]',cl.map(function(p){var v=n(p.eur)||0,o=n(p.out);
        return li((tone(v)+(fresh(p)?' new':'')).trim(),sym(p),['x'+de(n(p.mult)||0,2),WHY[p.why]||String(p.why||''),o?hhmm(o):''].filter(Boolean).join(' · '),eur(v));}));
      if(u)show(u.closest('[data-rk-soldw]'),cl.length);
      var cs=box.querySelector('[data-rk-cands]');
      if(cs&&Array.isArray(d.top)&&d.top.length){var pre=cs.getAttribute('data-rk-cands')==='hm'?'hm':'rk';
        fill(box,'[data-rk-cands]',d.top.slice(0,SHOWN).filter(function(r){return r&&typeof r==='object';}).map(function(r){
          var sh=cut>0?(n(r.score)||0)/cut:0,e=li(r.buy?'buy':(sh>=0.5?'near':''),sym(r),null,null),bar=el('span',pre+'-bar'),i=el('i');
          i.style.width=Math.max(2,Math.min(100,100*sh)).toFixed(1)+'%';bar.appendChild(i);e.appendChild(bar);
          e.appendChild(el('em',null,r.buy?'gekauft':Math.round(100*sh)+' %'));e.appendChild(el('small',null,Math.round(n(r.age)||0)+' min alt'));return e;}));
        [].forEach.call(box.querySelectorAll('[data-rk-more]'),function(m){m.setAttribute('hidden','');});}
      [].forEach.call(box.querySelectorAll('[data-rk-live]'),function(e){e.textContent='Live · Stand '+hhmm(t)+' · neue Käufe und Verkäufe erscheinen hier ohne Neuladen';e.removeAttribute('hidden');});
    });
    seen=ids;
  }
  function want(){if(document.visibilityState==='hidden')return false;var a=document.getElementById('tab-young'),b=document.getElementById('tab-home');
    return (!a&&!b)||!!(a&&a.checked)||!!(b&&b.checked);}
  function poll(){
    if(busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+EVERY;
    var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    fetch(url+'/rest/v1/live?select=doc&id=eq.rocket',{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){if(!r.ok)throw r.status;return r.json();})
      .then(function(rows){var d=Array.isArray(rows)&&rows[0]&&rows[0].doc;if(d&&typeof d==='object'&&d.summary&&typeof d.summary==='object')apply(d);})
      .catch(function(){next=Date.now()+2*EVERY;})
      .then(function(){clearTimeout(tm);busy=false;});
  }
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&/^tab-(young|home)$/.test(e.target.id||''))poll();});
  setInterval(poll,5000);poll();
})();
"""
