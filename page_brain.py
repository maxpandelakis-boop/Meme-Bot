"""page_brain.py: "Das Gehirn", the top of the Office tab (#pane-office). Fake money only: nothing here buys, signs or sends anything.

A dark panel that draws the bot as a brain: the core in the middle (the research lab that learns), the scan's agents on a ring around it
(each node lit by its state in the last run: done, failed, running), the coins the bot is thinking about on an inner ring (the pick and the
rocket hunter's best candidates, each node as bright as its score is close to the buy cut) and lines that carry signals into the core.
Under it the bot's "thoughts" in plain German sentences, built from the same numbers the other tabs show (the last scan, the pick and its
odds, the rocket round and its decision, the training, the two accounts).

Live: report.py's office script sends the event memebot-live with the live status row (app.status_doc: the agents with their status and
last line) while a scan runs; the script here lights the running agents, speeds the signal lines up and shows the running agent's last line
as the newest thought. Without the event (no live store, a scan not running) the panel shows the last run. A slow cycle picks one coin node
after the other and says what the bot knows about it (stopped with reduced motion: the first coin stays).

section(D, R) -> HTML; every chain string and every agent line is escaped (in the script through textContent).
"""
import html, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
W, H, CX, CY = 400, 340, 200, 168
RING_X, RING_Y = 124, 128          # the agents' ring (an ellipse: the panel is wider than tall)
INNER = 70                          # the coins' ring
COINS_MAX = 6
NAMES = {"dispatch": "Dirigent", "scouts": "Späher", "deep": "Tiefensuche", "spotter": "Launch-Späher", "candles": "Kerzen", "market": "Preise",
         "refresh": "Preis-Update", "analyst": "Filter", "safety": "Sicherheit", "trader": "Händler", "reporter": "Bericht", "radar": "Launch-Radar",
         "rocket": "Raketen-Jäger"}
ORDER = ("dispatch", "scouts", "deep", "market", "candles", "analyst", "safety", "refresh", "trader", "reporter", "radar", "rocket")
ST_WORD = {"done": "fertig", "failed": "Fehler", "fallback": "Ersatzweg", "running": "arbeitet", "skipped": "pausiert", "absent": "pausiert"}


def num(v):
    return M.num(v)


def de_int(v):
    return format(int(round(v)), ",").replace(",", ".")


def de_eur(v):
    s = format(abs(v), ",.2f").replace(",", "\x00").replace(".", ",").replace("\x00", ".")
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
        by["rocket"] = ("done", "%s Coins beobachtet, %d bewertet, %d gekauft" % (de_int(num(rd.get("candidates")) or 0), int(num(rd.get("scored")) or 0), int(num(rd.get("bought")) or 0)))
    by.setdefault("radar", ("done", "neue Pools unter 10 Minuten"))
    return [(i, NAMES[i]) + by[i] for i in ORDER if i in by]


def coins(D, doc):
    """[(symbol, kind, strength 0..1, what the bot knows)]: the pick first, then the rocket candidates by score."""
    out = []
    picks = [c for c in ((D.get("rec") or {}).get("picks") or []) if isinstance(c, dict)]
    if picks:
        p = picks[0]
        bits = ["mein Pick", "Score %d" % round(num(p.get("score")) or 0)]
        if num(p.get("upP")) is not None:
            bits.append("%d %% Chance auf Gewinn" % round(100 * num(p["upP"])))
        if num(p.get("zeroP")) is not None:
            bits.append("%d %% Risiko Totalverlust" % round(100 * num(p["zeroP"])))
        bits.append("Sicherheitscheck bestanden" if p.get("ok") else "Sicherheitscheck nicht sauber")
        out.append((str(p.get("sym") or "?")[:12], "pick", 1.0, ", ".join(bits)))
    if doc:
        cut = num(doc.get("cut")) or 0
        for r in [r for r in doc.get("top") or [] if isinstance(r, dict)][:COINS_MAX - len(out)]:
            sh = (num(r.get("score")) or 0) / cut if cut > 0 else 0
            mc = num(r.get("mc"))
            out.append((str(r.get("sym") or str(r.get("addr") or "?")[:6])[:12], "buy" if r.get("buy") else "cand", max(0.0, min(1.0, sh)),
                        "Raketen-Kandidat, %d %% der Kaufschwelle, %d min alt%s%s" % (round(100 * sh), int(num(r.get("age")) or 0),
                                                                                       (", Marktwert %s $" % de_int(mc)) if mc else "", ", gekauft" if r.get("buy") else "")))
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
            out.append((hm(t), "go", "Entscheidung Radar: gekauft %s, der Score hat die Schwelle erreicht. 20 € Spielgeld." % ", ".join(str(r.get("sym") or "?") for r in bought)))
        elif top:
            b = top[0]
            out.append((hm(t), "no", "Entscheidung Radar: nichts gekauft. Bester war %s mit %d %% der Kaufschwelle; ich kaufe erst bei 100 %%."
                        % (b.get("sym") or "?", round(100 * (num(b.get("score")) or 0) / cut) if cut else 0)))
        out.append((hm(t), "see", "Raketen-Radar: %s neue Coins beobachtet, %d im richtigen Alter bewertet." % (de_int(num(rd.get("candidates")) or 0), int(num(rd.get("scored")) or 0))))
    picks = [c for c in rc.get("picks") or [] if isinstance(c, dict)]
    t = num(rc.get("t"))
    if picks:
        p = picks[0]
        odds = ""
        if num(p.get("upP")) is not None and num(p.get("zeroP")) is not None:
            odds = " Chance auf Gewinn %d %%, Risiko Totalverlust %d %%." % (round(100 * num(p["upP"])), round(100 * num(p["zeroP"])))
        out.append((hm(t), "go", "Entscheidung Pick: %s für die nächsten 2 Stunden (Score %d).%s" % (p.get("sym") or "?", round(num(p.get("score")) or 0), odds)))
    elif rc:
        out.append((hm(t), "no", "Entscheidung Pick: kein Coin war sauber genug, also kein Pick."))
    if num(rc.get("scanned")):
        out.append((hm(t), "see", "Scan: %s Coins angeschaut, %d kamen durch alle Filter." % (de_int(rc["scanned"]), int(num(rc.get("passed")) or 0))))
    O = D.get("office") if isinstance(D.get("office"), dict) else {}
    tr = next((a for a in O.get("agents") or [] if isinstance(a, dict) and a.get("id") == "trainer"), None)
    if tr and tr.get("out"):
        out.append((hm(num(O.get("t"))), "learn", "Lernlabor: %s." % str(tr["out"])[:140]))
    return out


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
    parts = ['<svg class="bn-svg" viewBox="0 0 %d %d" role="img" aria-label="Das Gehirn des Bots: %d Helfer, %d Coins im Blick">' % (W, H, len(ags), len(cs)),
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
    for i, (sym, kind, k, _) in enumerate(cs):
        x, y = ring_xy(i, len(cs), INNER, INNER * 0.86, start=-60.0)
        r = 3.2 + 4.2 * k
        links.append('<line class="bn-cl %s" x1="%.1f" y1="%.1f" x2="%d" y2="%d" style="opacity:%.2f"/>' % (kind, x, y, CX, CY, 0.25 + 0.6 * k))
        nodes.append('<g class="bn-coin %s" data-coin="%d" style="--k:%.2f"><circle class="h" cx="%.1f" cy="%.1f" r="%.1f"/><circle class="c" cx="%.1f" cy="%.1f" r="%.1f"/>'
                     '<text x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>' % (kind, i, k, x, y, r * 2.4, x, y, r, x, y - r - 5, E(sym)))
    core = ('<g class="bn-core"><circle class="o3" cx="%d" cy="%d" r="44"/><circle class="o2" cx="%d" cy="%d" r="34"/><circle class="o1" cx="%d" cy="%d" r="27"/>'
            '<circle class="g" cx="%d" cy="%d" r="30" fill="url(#bn-core)"/>'
            '<text class="t1" x="%d" y="%d" text-anchor="middle">GEHIRN</text><text class="t2" x="%d" y="%d" text-anchor="middle" data-bn-word>%s</text></g>') % (
        CX, CY, CX, CY, CX, CY, CX, CY, CX, CY + 2, CX, CY + 14, E(live_word))
    parts += ['<g class="bn-links">%s</g>' % "".join(links), core, '<g filter="url(#bn-glow)">%s</g>' % "".join(nodes), '</svg>']
    return "".join(parts)


def section(D, R):
    doc = rocket_doc(D)
    ags, cs, th = agents(D), coins(D, doc), thoughts(D, R, doc)
    focus = "".join('<li data-f="%d"><b>%s</b> %s</li>' % (i, E(s), E(w)) for i, (s, _, _, w) in enumerate(cs))
    tl = "".join('<li class="%s" style="animation-delay:%.2fs"><time>%s</time><span>%s</span></li>' % (k, 0.15 + 0.12 * i, E(t), E(s)) for i, (t, k, s) in enumerate(th))
    legend = ('<div class="bn-leg"><span class="l-pick">Pick</span><span class="l-rk">Raketen-Kandidat</span><span class="l-ok">Helfer fertig</span>'
              '<span class="l-run">arbeitet gerade</span><span class="l-bad">Fehler</span></div>')
    return ('<style>%s</style><section class="bn" data-brain data-state="rest"><div class="bn-head"><div><div class="bn-ey">Office · live</div><h2 class="bn-h">Das Gehirn</h2></div>'
            '<span class="bn-live" data-bn-live>ruht · letzter Scan</span></div>'
            '<div class="bn-stage">%s</div><ul class="bn-focus" aria-live="polite">%s</ul>%s'
            '<div class="bn-th"><h3>Gedanken</h3><ol data-bn-thoughts>%s</ol></div></section><script>%s</script>') % (
        CSS, svg(ags, cs, "ruht"), focus, legend, tl or '<li class="see"><time>–</time><span>Noch keine Gedanken: der erste Scan kommt bald.</span></li>', JS)


JS = r"""
(function(){
var root=document.querySelector('[data-brain]');if(!root)return;
var word=root.querySelector('[data-bn-word]'),badge=root.querySelector('[data-bn-live]'),list=root.querySelector('[data-bn-thoughts]');
var fs=Array.prototype.slice.call(root.querySelectorAll('.bn-focus li')),cs=Array.prototype.slice.call(root.querySelectorAll('.bn-coin'));
var still=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches,i=0;
function focus(n){fs.forEach(function(f,k){f.classList.toggle('on',k===n);});cs.forEach(function(c,k){c.classList.toggle('on',k===n);});}
if(fs.length){focus(0);if(!still)setInterval(function(){if(document.hidden)return;i=(i+1)%fs.length;focus(i);},3200);}
cs.forEach(function(c,k){c.addEventListener('click',function(){i=k;focus(k);});});
var ST={done:1,failed:1,fallback:1,running:1,skipped:1};
// the live status row (report.py's office script): the running agents light up, the newest agent line becomes a thought
window.addEventListener('memebot-live',function(e){var d=e&&e.detail||{},st=d.status,live=d.state==='live';
  root.setAttribute('data-state',live?'live':'rest');if(word)word.textContent=live?'denkt nach':'ruht';
  if(badge)badge.textContent=live?'denkt gerade · Scan läuft':'ruht · letzter Scan';
  if(!st||!Array.isArray(st.agents))return;var run=null;
  st.agents.forEach(function(a){if(!a||!a.id)return;var s=ST[a.status]?a.status:(a.end?'done':'skipped');
    var g=root.querySelector('[data-ag="'+String(a.id).replace(/[^a-z0-9_-]/gi,'')+'"]'),l=root.querySelector('[data-ln="'+String(a.id).replace(/[^a-z0-9_-]/gi,'')+'"]');
    [g,l].forEach(function(x){if(x)x.setAttribute('class',x.getAttribute('class').replace(/\bst-\w+/,'st-'+s));});
    if(s==='running'&&a.lines&&a.lines.length)run={n:g?g.textContent:a.id,l:String(a.lines[a.lines.length-1]).slice(0,160)};});
  var old=list&&list.querySelector('li.now');if(old)old.parentNode.removeChild(old);
  if(live&&run&&list){var li=document.createElement('li');li.className='now';var t=document.createElement('time');t.textContent='jetzt';
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
