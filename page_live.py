"""page_live.py: the Start tab's live panel (#live), the user's wish of Oct 25 ("alles clean machen und cool zum live zugucken wie alles
live agiert"). Fake money only: nothing here buys, sells, signs or sends anything, and nothing here changes a rule, a pick or an account.

Two parts, in the words of the Start cards (the user mixes up the accounts, so every line names its bot and its account):
  lanes  one row per bot: PICK BOT (buys one coin a scan for the Pick account), SELL BOT 🤖 (sells the Pick account's coins on the live
         chart, a look every minute), RADAR 🚀 (the Radar account's rocket hunter, a round every 15 minutes) and LEARNING PICK (the shadow
         account, a buy with each scan, trains every night). Each says what its bot did last, counts down to its next move with a bar that
         fills up, and shows its open coins with their change since the buy as chips. A move overdue by far turns the lane amber ("late").
  feed   the last day's events of all four, newest first: buys, sells, Radar rounds and scans, each with its time, its bot, the coin and
         the result in €; the first FEED_SHOWN in view, the rest behind "Show all".
section(D, R) -> HTML with the panel's CSS and LV_JS. Without scripts it shows the page's state (the numbers of the last scan). With the
app's live store LV_JS reads two live rows, only while the Start tab is in front: their versions every POLL_S seconds (a few bytes), a
row itself only when its version moved: pickwatch (memebot.LIVE_WATCH_ROW: the sell bot's look every minute, its sales, the Pick positions
of a scan newer than the page) and rocket (rocket_watch.live_doc: the Radar account's positions and sells, the round's best scores). It
also listens to the scan's live status (report.py's event memebot-live): a running scan shows in the PICK BOT lane. A new event slides into
the feed. Text only: no HTML from a row, every chain string escaped here and set with textContent there.
"""
import datetime as dt, html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import page_home as PH

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
num = M.num
H = 3_600_000
FEED_H = 24               # hours of events in the feed
FEED_MAX = 40             # events at most
FEED_SHOWN = 8            # in view before "Show all"
CHIPS = 4                 # open coins as chips in a lane, the rest as "+n"
POLL_S = 10               # s between two looks at the live rows' versions (a row itself only when its version moved)
LOOK_MS = 60_000          # the sell bot looks every minute (rocket_watch.WATCH_S)
ROUND_MS = 15 * 60_000    # the Radar round every 15 minutes (rocket.yml)
LATE = {"scan": 45 * 60_000, "look": 15 * 60_000, "round": 35 * 60_000}  # overdue by this much: the lane turns amber (the sell bot pauses
PAUSE_MS = 150_000        # during a Radar round and between two runs of rocket.yml, a few minutes: "pause", not "late")
WHO = {"pick": "PICK BOT", "sell": "SELL BOT 🤖", "acct": "PICK ACCOUNT", "radar": "RADAR 🚀", "lp": "LEARNING PICK", "scan": "SCAN"}
RK_WHY = {"stop": "stop −30%", "11x": "hit 11x", "6h": "after 6 h", "gone": "coin gone"}      # page_rocket.WHY
try:
    from page_brain import NAMES as AGENTS          # the scan's helpers by name (Scouts, Deep search, Prices ...) for the running scan's line
except Exception:
    AGENTS = {}
LP_WHY = {"tp": "target", "half": "half at target", "stop": "stop", "trail": "trailing stop", "time": "time limit", "rug": "pool dead"}


def pct(m):
    """A multiple of the buy price as a change: 1.234 -> +23%, 0.8 -> −20%, 1.0 -> 0%."""
    return PH.sb_pct(m) if num(m) else "–"


def hm(R, ms):
    return PH.hhmm(R, ms)


def sym(v):
    return str(v or "?")[:14]


def rk_sig(top):
    """The signature of a round's best scores (LV_JS computes the same): a new one in the live row is a new round."""
    return "|".join("%s:%d" % (str(r.get("addr") or "")[:6], round(1e5 * (num(r.get("score")) or 0))) for r in (top or [])[:5] if isinstance(r, dict))


def next_night(now):
    """The Learning Pick's next training: the next 06:50 UTC (lernpick.NIGHT_MS, filtersearch.yml's start; it buys with each scan)."""
    try:
        import lernpick as L
        night = L.NIGHT_MS
    except Exception:
        night = 6 * H + 50 * 60_000
    day = (int(now) // (24 * H)) * 24 * H
    t = day + night
    return t if t > now else t + 24 * H


def lp_summary(D):
    try:
        import lernpick as L
        return L.summary(D.get("dir") or "", D.get("now"))
    except Exception:
        return None


def scan_words(r, rows):
    """What a scan did for the Pick account, as escaped HTML: bought its pick, picked a coin the account already held (no second buy),
    picked one without buying it, or found no coin clean enough. rows: the Pick account's positions (page_home.pick_book)."""
    picks = [c for c in r.get("picks") or [] if isinstance(c, dict)]
    got = next((c for c in picks if num(c.get("bought"))), None)
    if got:
        return "bought <b>%s</b> for the Pick account" % E(sym(got.get("sym")))
    if not picks:
        return "no coin was clean enough, nothing bought"
    p, t = picks[0], num(r.get("t")) or 0
    held = any((x.get("p") or {}).get("addr") == p.get("addr") and (num(x.get("tBuy")) or num(x.get("t")) or 0) < t
               and (x.get("open") or (num(x.get("exitT")) or 0) > t) for x in rows or [] if isinstance(x, dict))
    return ("picked <b>%s</b> again, already held" if held else "picked <b>%s</b>, not bought") % E(sym(p.get("sym")))


def ev(k, t, who, html_text, eur=None, dim=False):
    return {"k": k, "t": int(t), "who": who, "h": html_text, "eur": eur, "dim": dim}


def events(D, R, doc=None, S=None):
    """The feed: [{k (a key LV_JS knows it by), t, who, h (escaped HTML), eur, dim}], newest first, FEED_H hours, FEED_MAX at most.
    doc: rocket.json, S: the Learning Pick's summary (read here when not given)."""
    now = D["now"]
    doc = doc if doc is not None else PH.rocket_doc(D)
    since = now - FEED_H * H
    out = []
    b = PH.pick_book(D) or {}
    tk = PH.de_eur(b.get("ticket") or 50.0).replace(".00", "")
    for r in b.get("rows") or []:
        p = r.get("p") or {}
        t_buy = num(r.get("tBuy")) or num(r.get("t"))
        if t_buy and t_buy >= since:
            tier = {"strong": "strong pick", "fair": "fair pick", "weak": "weak pick", "risky": "risky pick", "fallback": "relaxed pick"}.get(str(p.get("tier") or ""), "")
            out.append(ev("buy:%s" % r.get("id"), t_buy, "pick", "bought <b>%s</b> for the Pick account%s" % (E(sym(r.get("sym"))), (" · " + E(tier)) if tier else ""),
                          "%s" % tk))
        x = num(r.get("exitT"))
        if not r.get("open") and x and x >= since:
            ex = [e for e in r.get("status") or [] if isinstance(e, dict)]
            why = str(ex[-1].get("why") or "") if ex else ""
            chart = M.is_chart(p)
            words = PH.SB_WHY.get(why, why) if chart else PH.PICK_WHY.get(why, why)
            out.append(ev("sell:%s" % r.get("id"), x, "sell" if chart else "acct",
                          "sold <b>%s</b> · Pick account · %s%s" % (E(sym(r.get("sym"))), E(words),
                                                                   (" · " + E(pct(1 + num(r["pct"])))) if num(r.get("pct")) is not None else ""),
                          num(r.get("pnl"))))
    if doc:
        bk = doc.get("book") or {}
        for p in list((bk.get("open") or {}).values()) + list(bk.get("closed") or []):
            if not isinstance(p, dict):
                continue
            if (num(p.get("t")) or 0) >= since:
                out.append(ev("rbuy:%s" % p.get("addr"), num(p["t"]), "radar", "bought <b>%s</b> for the Radar account 🚀 · score at the buy line" % E(sym(p.get("sym"))),
                              PH.de_eur(M.TICKET).replace(".00", "")))
            if num(p.get("out")) and num(p["out"]) >= since:
                out.append(ev("rsell:%s" % p.get("addr"), num(p["out"]), "radar", "sold <b>%s</b> from the Radar account 🚀 · %s · %s" % (
                    E(sym(p.get("sym"))), E(RK_WHY.get(str(p.get("why") or ""), str(p.get("why") or ""))), E(pct(p.get("mult")))), num(p.get("eur"))))
        t = num(doc.get("t"))
        if t and t >= since:
            rd, cut = doc.get("round") or {}, num(doc.get("cut")) or 0
            top = [r for r in doc.get("top") or [] if isinstance(r, dict)]
            bought = [r for r in top if r.get("buy")]
            best = ("best <b>%s</b> at %d%% of the buy line · %s" % (E(sym(top[0].get("sym"))), round(100 * (num(top[0].get("score")) or 0) / cut) if cut else 0,
                                                                    "bought" if bought else "no buy")) if top else "no coin of the right age"
            out.append(ev("rround:%s" % rk_sig(top), t, "radar", "round · %s coins watched · %s" % (PH.de_num(int(num(rd.get("candidates")) or 0), 0), best),
                          dim=not bought))
    S = S if S is not None else lp_summary(D)
    if S:
        for p in S.get("trades") or []:
            if not isinstance(p, dict):
                continue
            if (num(p.get("t")) or 0) >= since:
                out.append(ev("lbuy:%s" % p.get("pid"), num(p["t"]), "lp", "bought <b>%s</b> for its shadow account" % E(sym(p.get("sym"))),
                              PH.de_eur(S.get("ticket") or 50).replace(".00", "")))
            if p.get("state") == "sold" and num(p.get("out")) and num(p["out"]) >= since:
                why = p.get("why") if isinstance(p.get("why"), str) else ""
                m = 1 + (num(p.get("eur")) or 0) / (num(S.get("ticket")) or 50)
                out.append(ev("lsell:%s" % p.get("pid"), num(p["out"]), "lp", "sold <b>%s</b> · %s · %s" % (E(sym(p.get("sym"))), E(LP_WHY.get(why, why)), E(pct(m))),
                              num(p.get("eur"))))
    for r in D.get("runs") or []:
        t = num((r or {}).get("t")) if isinstance(r, dict) else None
        if not t or t < since:
            continue
        out.append(ev("scan:%d" % t, t, "scan", "%s coins looked at · %d passed every filter · %s" % (
            PH.de_num(int(num(r.get("scanned")) or 0), 0), int(num(r.get("passed")) or 0), scan_words(r, b.get("rows"))), dim=True))
    out.sort(key=lambda e: -e["t"])
    seen, keep = set(), []
    for e in out:
        if e["k"] not in seen:
            seen.add(e["k"])
            keep.append(e)
    return keep[:FEED_MAX]


def ev_li(R, e, now):
    eur = e.get("eur")
    if isinstance(eur, str):
        amt = '<em class="lv-amt">%s</em>' % E(eur)
    elif eur is not None:
        amt = '<em class="lv-amt %s">%s</em>' % (PH.tone(eur), E(PH.de_eur(eur, True)))
    else:
        amt = ""
    return ('<li class="lv-ev lv-w-%s%s" data-k="%s" data-t="%d"><time>%s<small data-lv-ago>%s</small></time><p><span class="lv-who">%s</span> %s</p>%s</li>') % (
        e["who"], " lv-dim" if e.get("dim") else "", E(e["k"]), e["t"], E(hm(R, e["t"])), E(ago(now - e["t"])), E(WHO.get(e["who"], e["who"].upper())), e["h"], amt)


def ago(ms):
    """'now', '4m ago', '2h ago' (LV_JS keeps it current)."""
    m = max(0, int(ms // 60_000))
    return "now" if m < 1 else ("%dm ago" % m if m < 60 else "%dh ago" % (m // 60))


def chip(label, m, key, note=""):
    """An open coin as a chip: its symbol and the change since the buy (m: a multiple of the buy price), coloured by sign."""
    t = PH.tone((m - 1) if num(m) else None)
    return '<span class="lv-chip %s" data-lv-chip="%s"%s><b>%s</b><i>%s</i></span>' % (t, E(key), (' title="%s"' % E(note)) if note else "", E(sym(label)), E(pct(m) if num(m) else "…"))


def chips(items):
    """items: [(label, multiple or None, key, note)]; the first CHIPS, then '+n'."""
    if not items:
        return ""
    h = "".join(chip(*x) for x in items[:CHIPS])
    if len(items) > CHIPS:
        h += '<span class="lv-chip lv-more">+%d</span>' % (len(items) - CHIPS)
    return h


# a tap on a lane opens where its bot lives (the four tiles that repeated the tab bar did that before Oct 25): page_home.JS switches the
# tab (in the installed app through its own bar) and, with data-open, scrolls to that card or opens that fold
GO = {"pick": ("pick", ""), "sell": ("pick", "sell-bot"), "radar": ("young", ""), "lp": ("pick", "learning-pick")}


def lane(key, ico, name, sub, cdk, cd, bar, say, chips_html="", late=False):
    tab, card = GO.get(key, ("home", ""))
    return ('<label class="lv-lane lv-%s%s" data-lv-lane="%s" for="tab-%s" data-go="%s"%s><span class="lv-top"><span class="lv-ico" aria-hidden="true">%s</span>'
            '<span class="lv-nm"><b>%s <span class="lv-gt" aria-hidden="true">›</span></b><small>%s</small></span><span class="lv-cd"><small data-lv-cdk>%s</small>'
            '<b data-lv-cd>%s</b></span></span><span class="lv-bar"><i data-lv-bar style="width:%.1f%%"></i></span><span class="lv-say" data-lv-say>%s</span>'
            '<span class="lv-chips" data-lv-chips>%s</span></label>') % (
        key, " lv-late" if late else "", key, tab, tab, (' data-open="%s"' % card) if card else "", ico, E(name), E(sub), E(cdk), E(cd),
        max(0.0, min(100.0, bar)), say, chips_html)


def left(ms):
    """A countdown in words: 'in 7:05' under an hour, 'in 3 h 05 min' above, 'now' when due."""
    if ms <= 0:
        return "now"
    s = int(ms // 1000)
    return "in %d:%02d" % (s // 60, s % 60) if s < 3600 else "in %d h %02d min" % (s // 3600, (s % 3600) // 60)


def share(now, t0, t1):
    return 100.0 * (now - t0) / (t1 - t0) if t1 > t0 else 0.0


def section(D, R):
    """The live panel (id live) for the Start tab: the four lanes and the feed, with LV_CSS and LV_JS. '' when nothing can be read."""
    now = D["now"]
    doc = PH.rocket_doc(D)
    S = lp_summary(D)
    runs = [r for r in D.get("runs") or [] if isinstance(r, dict) and num(r.get("t"))]
    scan_t = num(runs[0]["t"]) if runs else 0
    nxt = R.next_scan_ms(now, runs)
    # PICK BOT: the last scan and the next
    if runs:
        r0 = runs[0]
        say = "Last scan %s: looked at %s coins, %s." % (E(hm(R, scan_t)), E(PH.de_num(int(num(r0.get("scanned")) or 0), 0)), scan_words(r0, (PH.pick_book(D) or {}).get("rows")))
    else:
        say = "No scan yet."
    lanes = [lane("pick", "🔎", "PICK BOT", "buys for the Pick account, hourly", "next scan", left(nxt - now) if nxt > now else "any moment",
                  share(now, scan_t or nxt - H, nxt), say)]
    # SELL BOT: the open chart-exit positions of the Pick account, at the scan's price (LV_JS: the watch's minute)
    pick = {}
    items = []
    for r in D.get("open") or []:
        p = (r or {}).get("p") or {}
        if not isinstance(r, dict) or p.get("grp") != "hold":
            continue
        pid = str(p.get("_id") or r.get("id") or "")
        entry, last = num(r.get("entry")), num(r.get("last"))
        pick[pid] = {"sym": sym(p.get("sym")), "px": entry, "cpx": num(r.get("cpx")), "t": num(p.get("entryAt")) or num(p.get("t"))}
        items.append((p.get("sym"), (last / entry) if last and entry else None, "p:" + pid, "change since the buy, at the scan's price"))
    w = PH.sb_watch(D)
    look = num(w.get("t")) or 0
    live_at = M.live_sell_at()
    if now < live_at:
        sb_say, sb_cd = "Starts with the live chart.", "–"
    elif items:
        sb_say = "Watching %d coin%s of the Pick account on the live chart%s." % (len(items), "" if len(items) == 1 else "s", (", last look %s" % E(hm(R, look))) if look else "")
        sb_cd = (left(look + LOOK_MS - now) if now - look < LOOK_MS else ("looking…" if now - look < PAUSE_MS else "pause")) if look and now - look < LATE["look"] else "every minute"
    else:
        sb_say, sb_cd = "Nothing to sell right now. It takes over the next coin the Pick bot buys.", "idle"
    lanes.append(lane("sell", "🤖", "SELL BOT 🤖", "sells the Pick account's coins live", "next look", sb_cd,
                      share(now, look, look + LOOK_MS) if look and items and now - look < LATE["look"] else 0, sb_say, chips(items)))
    # RADAR: the last round, the next, its open coins
    radar, rk_t, cut, rk_items = {}, 0, 0, []
    if doc:
        rk_t, cut = num(doc.get("t")) or 0, num(doc.get("cut")) or 0
        top = [r for r in doc.get("top") or [] if isinstance(r, dict)]
        rd = doc.get("round") or {}
        best = ("best <b>%s</b> at %d%% of the buy line (it buys at 100%%)" % (E(sym(top[0].get("sym"))), round(100 * (num(top[0].get("score")) or 0) / cut) if cut else 0)) if top else "no coin of the right age"
        rk_say = "Last round %s: %s coins watched, %s." % (E(hm(R, rk_t)), E(PH.de_num(int(num(rd.get("candidates")) or 0), 0)), best)
        for a, p in ((doc.get("book") or {}).get("open") or {}).items():
            if isinstance(p, dict):
                radar[str(a)] = {"sym": sym(p.get("sym")), "t": num(p.get("t"))}
                rk_items.append((p.get("sym"), num(p.get("now")), "r:" + str(a), "change since the buy"))
        rk_due = rk_t + ROUND_MS
        lanes.append(lane("radar", "🚀", "RADAR 🚀", "hunts rockets for the Radar account", "next round",
                          left(rk_due - now) if now < rk_due else "every 15 min", share(now, rk_t, rk_due), rk_say, chips(rk_items)))
    # LEARNING PICK: its open coins at the last scan, the next training
    lp_items = []
    if S:
        me = S.get("me") or {}
        for p in S.get("trades") or []:
            if isinstance(p, dict) and p.get("state") == "open":
                lp_items.append((p.get("sym"), num(p.get("_now")), "l:" + str(p.get("pid")), "change since the buy, at the last scan's price"))
        nn = next_night(now)
        lp_say = "Buys 1 coin with each scan by its own model. %d open, %d sold so far (%s)." % (
            int(me.get("open") or 0), int(me.get("sold") or 0), E(PH.de_eur(me.get("closedPnl"), True)))
        lanes.append(lane("lp", "🧠", "LEARNING PICK", "shadow account, learns nightly", "next training",
                          left(nn - now), share(now, nn - 24 * H, nn), lp_say, chips(lp_items)))
    feed = events(D, R, doc, S)
    known = [e["k"] for e in feed]
    data = {"now": now, "scanT": scan_t, "nextScan": nxt, "look": look, "liveAt": live_at, "rkT": rk_t, "cut": cut, "rkSig": rk_sig((doc or {}).get("top")),
            "lpNext": next_night(now), "pick": pick, "radar": radar, "keys": known, "late": LATE, "pause": PAUSE_MS, "lookMs": LOOK_MS, "roundMs": ROUND_MS, "ux": M.UNIT_X, "every": POLL_S * 1000,
            "row": M.LIVE_WATCH_ROW, "tk": PH.de_eur(M.TOP_TICKET).replace(".00", ""), "rtk": PH.de_eur(M.TICKET).replace(".00", "")}
    lis = "".join(ev_li(R, e, now) for e in feed)
    more = len(feed) - FEED_SHOWN
    feed_html = ('<div class="lv-feed"><div class="lv-fh"><b>Live feed</b><small>buys, sells, rounds and scans of the last %d h · newest first</small></div>'
                 '<input type="checkbox" id="lv-all" class="lv-all" hidden><ol class="lv-list" data-lv-list>%s</ol>%s</div>') % (
        FEED_H, lis or '<li class="lv-none">Nothing happened in the last %d hours.</li>' % FEED_H,
        '<label for="lv-all" class="lv-showall" data-lv-more%s>Show all (%d)</label>' % ("" if more > 0 else " hidden", len(feed)))
    return ('<section class="lv" id="live" data-lv="%s"><div class="lv-head"><span class="lv-badge" data-lv-badge><i></i>LIVE</span>'
            '<time class="lv-clock" data-lv-clock>%s</time><div class="lv-ht"><h3>What the bots are doing</h3><small data-lv-src>as of the last scan %s · fake money</small></div>'
            '</div><div class="lv-lanes">%s</div>%s</section><style>%s</style><script>%s</script>') % (
        E(json.dumps(data, separators=(",", ":"))), E(hm(R, now)), E(hm(R, scan_t) if scan_t else "–"), "".join(lanes), feed_html, LV_CSS, LV_JS)


LV_JS = r"""
(function(){
  var box=document.querySelector('[data-lv]');if(!box)return;
  var D;try{D=JSON.parse(box.getAttribute('data-lv')||'{}');}catch(e){return;}
  var root=document.documentElement,url=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),key=root.getAttribute('data-sb-key')||'';
  var store=/^https:\/\/[^\s\/]+$/.test(url)&&!!key&&!!window.fetch,MINUS='−',SHOWN=""" + str(FEED_SHOWN) + r""",MAX=""" + str(FEED_MAX) + r""";
  var WHO=""" + json.dumps(WHO, ensure_ascii=False) + r""",SBW=""" + json.dumps(PH.SB_WHY, ensure_ascii=False) + r""",RKW=""" + json.dumps(RK_WHY, ensure_ascii=False) + r""";
  var AG=""" + json.dumps(AGENTS, ensure_ascii=False) + r""";
  var known={};(D.keys||[]).forEach(function(k){known[k]=1;});
  var vers={},busy=false,next=0,okAt=0,scanLive=null;
  var L={};['pick','sell','radar','lp'].forEach(function(k){var e=box.querySelector('[data-lv-lane="'+k+'"]');if(e)L[k]={el:e,cd:e.querySelector('[data-lv-cd]'),cdk:e.querySelector('[data-lv-cdk]'),
    bar:e.querySelector('[data-lv-bar]'),say:e.querySelector('[data-lv-say]'),chips:e.querySelector('[data-lv-chips]')};});
  var st={look:+D.look||0,rkT:+D.rkT||0,rkSig:D.rkSig||'',lookN:null};
  function n(v){v=typeof v==='number'?v:parseFloat(v);return isFinite(v)?v:null;}
  function now(){return Date.now();}
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
  function pct(m){var v=Math.round(100*(m-1));return (v>0?'+':(v<0?MINUS:''))+Math.abs(v)+'%';}
  function eur(v){var s=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});return (v>0.004?'+':(v<-0.004?MINUS:''))+s+'\u00a0€';}
  function tone(v){return v>0.004?'good':(v<-0.004?'bad':'');}
  function hhmm(ms){try{return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function left(ms){if(ms<=0)return 'now';var s=Math.floor(ms/1000);if(s<3600)return 'in '+Math.floor(s/60)+':'+('0'+s%60).slice(-2);
    return 'in '+Math.floor(s/3600)+' h '+('0'+Math.floor(s%3600/60)).slice(-2)+' min';}
  function ago(ms){var m=Math.max(0,Math.floor(ms/60000));return m<1?'now':(m<60?m+'m ago':Math.floor(m/60)+'h ago');}
  function set(e,t){if(e&&e.textContent!==t)e.textContent=t;}
  function bar(l,p){if(l&&l.bar)l.bar.style.width=Math.max(0,Math.min(100,p)).toFixed(1)+'%';}
  function late(l,on){if(l)l.el.classList.toggle('lv-late',!!on);}
  function sym(s){return String(s||'?').slice(0,14);}
  // a lane's chips: [{k,label,m}] (m: a multiple of the buy price); a changed value flashes up or down
  function chips(l,items){if(!l||!l.chips)return;var old={};[].forEach.call(l.chips.querySelectorAll('[data-lv-chip]'),function(c){old[c.getAttribute('data-lv-chip')]=c;});
    l.chips.textContent='';items.slice(0,4).forEach(function(x){var c=el('span','lv-chip '+(x.m?tone(x.m-1):''));c.setAttribute('data-lv-chip',x.k);
      c.appendChild(el('b',null,sym(x.label)));var i=el('i',null,x.m?pct(x.m):'…');c.appendChild(i);
      var o=old[x.k],ot=o&&o.querySelector('i')?o.querySelector('i').textContent:null;
      if(ot&&ot!==i.textContent){var up=parseFloat(ot.replace(MINUS,'-'))<(x.m?Math.round(100*(x.m-1)):0);c.classList.add(up?'lv-up':'lv-dn');}
      l.chips.appendChild(c);});
    if(items.length>4)l.chips.appendChild(el('span','lv-chip lv-more','+'+(items.length-4)));}
  // a new event at the top of the feed (text only); known keys never come twice
  function add(k,t,who,parts,amt,amtCls,dim){if(known[k])return;known[k]=1;var list=box.querySelector('[data-lv-list]');if(!list)return;
    var none=list.querySelector('.lv-none');if(none)none.parentNode.removeChild(none);
    var li=el('li','lv-ev lv-w-'+who+(dim?' lv-dim':'')+' lv-new');li.setAttribute('data-k',k);li.setAttribute('data-t',String(Math.round(t)));
    var tm=el('time',null,hhmm(t));tm.appendChild(el('small',null,ago(now()-t)));tm.lastChild.setAttribute('data-lv-ago','');li.appendChild(tm);
    var p=el('p');p.appendChild(el('span','lv-who',WHO[who]||who));p.appendChild(document.createTextNode(' '));
    parts.forEach(function(x){if(x&&typeof x==='object'){p.appendChild(el('b',null,x.b));}else p.appendChild(document.createTextNode(String(x)));});li.appendChild(p);
    if(amt)li.appendChild(el('em','lv-amt'+(amtCls?' '+amtCls:''),amt));
    var items=list.querySelectorAll('li.lv-ev'),at=null;for(var i=0;i<items.length;i++){if((+items[i].getAttribute('data-t')||0)<t){at=items[i];break;}}
    list.insertBefore(li,at);while(list.querySelectorAll('li.lv-ev').length>MAX)list.removeChild(list.lastElementChild);
    var m=box.querySelector('[data-lv-more]'),c=list.querySelectorAll('li.lv-ev').length;if(m){set(m,'Show all ('+c+')');if(c>SHOWN)m.removeAttribute('hidden');}
    setTimeout(function(){li.classList.remove('lv-new');},6000);}
  // the sell bot's row: its look every minute, the coins it watches (also the Pick positions of a newer scan), its sales
  function pickwatch(d){var pos=d.pos&&typeof d.pos==='object'?d.pos:{},sold=d.sold&&typeof d.sold==='object'?d.sold:{},t=n(d.t),items=[];
    if(t)st.look=t;
    Object.keys(pos).forEach(function(id){var w=pos[id];if(!w||typeof w!=='object'||sold[id])return;var P=(D.pick||{})[id]||{},cpx=n(w.cpx)||n(P.cpx),m=n(w.now),entry=n(P.px);
      var off=cpx&&entry&&(cpx/entry>D.ux||cpx/entry<1/D.ux);     // the pool's other coin (memebot.UNIT_X): no chart of its own yet, '…'
      var x=off?null:(m&&cpx&&entry?m*cpx/entry:(m||null));items.push({k:'p:'+id,label:w.sym||P.sym,m:x});
      var tb=n(w.entryAt)||n(w.t);if(!(D.pick||{})[id]&&tb)add('buy:'+id,tb,'pick',['bought ',{b:sym(w.sym)},' for the Pick account'],D.tk,'',false);});
    Object.keys(sold).forEach(function(id){var x=sold[id];if(!x||typeof x!=='object'||!n(x.at))return;var v=n(x.pnl)||0;
      add('sell:'+id,n(x.at),'sell',['sold ',{b:sym(x.sym||((D.pick||{})[id]||{}).sym)},' · '+(SBW[x.why]||String(x.why||''))+(n(x.mult)?' · '+pct(n(x.mult)):'')],eur(v),tone(v),false);});
    st.lookN=items.length;chips(L.sell,items);
    if(L.sell){set(L.sell.say,items.length?'Watching '+items.length+' coin'+(items.length===1?'':'s')+' of the Pick account on the live chart, last look '+hhmm(st.look)+'.':
      'Nothing to sell right now. It takes over the next coin the Pick bot buys.');}}
  // the Radar account's row: a new round (new best scores), its buys and sells, its open coins
  function rocket(d){var top=Array.isArray(d.top)?d.top.filter(function(r){return r&&typeof r==='object';}):[],cut=n(d.cut)||n(D.cut)||0,t=n(d.t);st.rkLive=true;
    var sig=top.slice(0,5).map(function(r){return String(r.addr||'').slice(0,6)+':'+Math.round(1e5*(n(r.score)||0));}).join('|');
    if(sig&&sig!==st.rkSig&&t){st.rkSig=sig;st.rkT=t;var b=top[0],bought=top.filter(function(r){return r.buy;});
      add('rround:'+sig,t,'radar',['round · best ',{b:sym(b.sym)},' at '+(cut?Math.round(100*(n(b.score)||0)/cut):0)+'% of the buy line · '+(bought.length?'bought':'no buy')],'','',!bought.length);
      if(L.radar)set(L.radar.say,'Last round '+hhmm(t)+': best '+sym(b.sym)+' at '+(cut?Math.round(100*(n(b.score)||0)/cut):0)+'% of the buy line (it buys at 100%).');}
    var items=[];(Array.isArray(d.open)?d.open:[]).forEach(function(p){if(!p||typeof p!=='object'||!p.addr)return;items.push({k:'r:'+p.addr,label:p.sym,m:n(p.now)});
      if(n(p.t))add('rbuy:'+p.addr,n(p.t),'radar',['bought ',{b:sym(p.sym)},' for the Radar account 🚀 · score at the buy line'],D.rtk,'',false);});
    (Array.isArray(d.closed)?d.closed:[]).forEach(function(p){if(!p||typeof p!=='object'||!p.addr||!n(p.out))return;var v=n(p.eur)||0;
      add('rsell:'+p.addr,n(p.out),'radar',['sold ',{b:sym(p.sym)},' from the Radar account 🚀 · '+(RKW[p.why]||String(p.why||''))+(n(p.mult)?' · '+pct(n(p.mult)):'')],eur(v),tone(v),false);});
    if(L.radar)chips(L.radar,items);}
  // the scan's live status (report.py): a running scan in the PICK BOT lane, with the helper at work
  window.addEventListener('memebot-live',function(e){var d=e&&e.detail||{},s=d.status;
    if(d.state!=='live'||!s||!Array.isArray(s.agents)){if(scanLive){scanLive=null;tick();}return;}
    var run=null;s.agents.forEach(function(a){if(a&&a.status==='running')run=a;});
    // the scan's pick shows here as soon as the status row has it (the Pick account's row, pickopen, follows when the scan ends)
    scanLive={t:n(s.t)||now(),who:run?(AG[run.id]||String(run.id||'')):'',line:run&&run.lines&&run.lines.length?String(run.lines[run.lines.length-1]).slice(0,120):'',
      pick:s.pick&&s.pick.sym?sym(s.pick.sym):''};tick();});
  function tick(){var t=now();
    set(box.querySelector('[data-lv-clock]'),new Date(t).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}));
    var P=L.pick;if(P){P.el.classList.toggle('lv-run',!!scanLive);
      if(scanLive){set(P.cdk,'scan running');set(P.cd,Math.max(0,Math.floor((t-scanLive.t)/60000))+' min');bar(P,100);
        set(P.say,'Scanning now'+(scanLive.who?' · '+scanLive.who+(scanLive.line?': '+scanLive.line:''):'')+'.'+(scanLive.pick?" This scan's pick: "+scanLive.pick+'.':'')+' The page updates when it is done.');late(P,false);}
      else{var due=+D.nextScan||0,lt=!!okAt&&t-due>=D.late.scan;set(P.cdk,'next scan');set(P.cd,t<due?left(due-t):(lt?'late':'any moment'));late(P,lt);
        bar(P,due>(+D.scanT||0)?100*(t-(+D.scanT||due-36e5))/(due-(+D.scanT||due-36e5)):0);}}
    var S=L.sell;if(S&&t>=(+D.liveAt||0)){var open=st.lookN==null?Object.keys(D.pick||{}).length:st.lookN,lk=st.look;
      if(!open){set(S.cd,'idle');bar(S,0);late(S,false);}
      else if(lk&&t-lk<D.late.look){set(S.cd,t-lk<D.lookMs?left(lk+D.lookMs-t):(t-lk<D.pause?'looking…':'pause'));bar(S,100*(t-lk)/D.lookMs);late(S,false);}
      else if(lk&&okAt){set(S.cd,'late');bar(S,100);late(S,true);}
      else{set(S.cd,'every minute');bar(S,0);}}
    var R=L.radar;if(R&&st.rkT){var due2=st.rkT+D.roundMs,lt2=st.rkLive&&t-due2>=D.late.round;
      set(R.cd,t<due2?left(due2-t):(lt2?'late':(st.rkLive?'any moment':'every 15 min')));bar(R,100*(t-st.rkT)/D.roundMs);late(R,lt2);}
    var G=L.lp;if(G&&D.lpNext){set(G.cd,left(D.lpNext-t));bar(G,100*(1-(D.lpNext-t)/864e5));}
    var b=box.querySelector('[data-lv-badge]');if(b){var on=okAt&&Date.now()-okAt<3*60000;b.classList.toggle('on',!!on);}
  }
  function agoAll(){var t=now();[].forEach.call(box.querySelectorAll('li.lv-ev'),function(li){var e=li.querySelector('[data-lv-ago]');if(e)set(e,ago(t-(+li.getAttribute('data-t')||t)));});}
  function want(){if(document.visibilityState==='hidden')return false;var h=document.getElementById('tab-home');return !h||!!h.checked;}
  function get(q){var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();},10000);
    return fetch(url+'/rest/v1/live?'+q,{headers:{apikey:key,Accept:'application/json'},cache:'no-store',signal:ac?ac.signal:undefined})
      .then(function(r){clearTimeout(tm);if(!r.ok)throw r.status;return r.json();},function(e){clearTimeout(tm);throw e;});}
  // the versions of both rows (a few bytes) every few seconds; a row itself only when its version moved
  function poll(){if(!store||busy||!want()||Date.now()<next)return;busy=true;next=Date.now()+D.every;
    get('select=id,ver&id=in.('+D.row+',rocket)').then(function(rows){var due=[];(Array.isArray(rows)?rows:[]).forEach(function(r){if(r&&r.id&&r.ver!==vers[r.id])due.push(r.id);});
      okAt=Date.now();if(!due.length)return;
      return get('select=id,ver,doc&id=in.('+due.join(',')+')').then(function(rows){(Array.isArray(rows)?rows:[]).forEach(function(r){if(!r||!r.doc||typeof r.doc!=='object')return;vers[r.id]=r.ver;
        try{if(r.id===D.row)pickwatch(r.doc);else if(r.id==='rocket')rocket(r.doc);}catch(e){}});
        var src=box.querySelector('[data-lv-src]');set(src,'live · updates every few seconds · fake money');});})
    .catch(function(){next=Date.now()+3*D.every;}).then(function(){busy=false;tick();});}
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){next=0;poll();}});
  document.addEventListener('change',function(e){if(e.target&&e.target.id==='tab-home'){next=0;poll();}});
  tick();agoAll();setInterval(tick,1000);setInterval(agoAll,20000);setInterval(poll,Math.min(2000,D.every));poll();
})();
"""


LV_CSS = r"""
/* the live panel (page_live.py) on the Start tab: four bot lanes with a clock each, then the feed; a dark stage like the brain's */
.lv { --lv-pick:var(--accent); --lv-sell:var(--good); --lv-radar:var(--nn2); --lv-lp:var(--nn1); --lv-scan:var(--muted);
  position:relative; display:grid; gap:12px; padding:14px; border-radius:18px; overflow:hidden; border:1px solid var(--line); scroll-margin-top:70px;
  background:radial-gradient(110% 70% at 100% 0%, color-mix(in srgb,var(--nn2) 14%,transparent), transparent 60%),
             radial-gradient(90% 60% at 0% 100%, color-mix(in srgb,var(--nn1) 9%,transparent), transparent 60%), var(--surface) }
.lv [hidden] { display:none !important }
.lv-head { display:grid; grid-template-columns:auto auto; justify-content:space-between; align-items:center; gap:8px 10px } .lv-ht { grid-column:1 / -1 }
.lv-badge { justify-self:start; display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:700; letter-spacing:.12em; padding:4px 9px; border-radius:999px;
  color:var(--muted); border:1px solid var(--line); background:color-mix(in srgb,var(--bg) 60%,transparent) }
.lv-badge i { width:8px; height:8px; border-radius:50%; background:var(--muted) }
.lv-badge.on { color:#ff6b7a; border-color:color-mix(in srgb,#ff4d5e 50%,transparent) }
.lv-badge.on i { background:#ff4d5e; box-shadow:0 0 0 0 rgba(255,77,94,.6); animation:lv-ping 1.6s ease-out infinite }
.lv-ht h3 { margin:0; font-size:17px; letter-spacing:-.01em } .lv-ht small { display:block; font-size:var(--fs-xs); color:var(--muted) }
.lv-clock { justify-self:end; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:13px; color:var(--fg2); font-variant-numeric:tabular-nums }
.lv-lanes { display:grid; gap:8px }
.lv-lane { --c:var(--accent); display:grid; gap:6px; padding:10px 12px; border-radius:14px; min-width:0; cursor:pointer; color:inherit; -webkit-tap-highlight-color:transparent;
  background:color-mix(in srgb,var(--bg) 55%,transparent); border:1px solid color-mix(in srgb,var(--c) 26%,var(--line)); transition:border-color .2s, background .2s }
.lv-lane:hover, .lv-lane:active { border-color:color-mix(in srgb,var(--c) 60%,var(--line)); background:color-mix(in srgb,var(--c) 7%,color-mix(in srgb,var(--bg) 55%,transparent)) }
.lv-gt { color:var(--muted); font-weight:400 }
.lv-pick { --c:var(--lv-pick) } .lv-sell { --c:var(--lv-sell) } .lv-radar { --c:var(--lv-radar) } .lv-lp { --c:var(--lv-lp) }
.lv-top { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:10px }
.lv-ico { width:34px; height:34px; border-radius:11px; display:grid; place-items:center; font-size:18px; background:color-mix(in srgb,var(--c) 16%,transparent) }
.lv-nm { display:grid; min-width:0 } .lv-nm b { font-size:13px; letter-spacing:.06em; color:var(--c) }
.lv-nm small { font-size:11px; color:var(--muted); line-height:1.3 }
.lv-cd { display:grid; justify-items:end; text-align:right } .lv-cd small { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em }
.lv-cd b { font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:15px; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap }
.lv-bar { display:block; height:4px; border-radius:4px; background:color-mix(in srgb,var(--fg) 8%,transparent); overflow:hidden }
.lv-bar i { display:block; height:100%; width:0; border-radius:4px; background:linear-gradient(90deg,color-mix(in srgb,var(--c) 55%,transparent),var(--c));
  box-shadow:0 0 8px color-mix(in srgb,var(--c) 70%,transparent); transition:width 1s linear }
.lv-say { display:block; margin:0; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere } .lv-say b { color:var(--fg) }
.lv-chips { display:flex; flex-wrap:wrap; gap:6px } .lv-chips:empty { display:none }
.lv-chip { display:inline-flex; align-items:baseline; gap:6px; padding:3px 9px; border-radius:999px; font-size:12px; background:var(--chip); border:1px solid transparent }
.lv-chip b { font-weight:600; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .lv-chip i { font-style:normal; font-variant-numeric:tabular-nums; font-weight:600 }
.lv-chip.good i { color:var(--good) } .lv-chip.bad i { color:var(--bad) } .lv-chip.lv-more { color:var(--muted) }
.lv-chip.lv-up { animation:lv-up 1.4s ease-out } .lv-chip.lv-dn { animation:lv-dn 1.4s ease-out }
.lv-late { border-color:color-mix(in srgb,var(--warn) 60%,var(--line)) } .lv-late .lv-cd b { color:var(--warn) }
.lv-run .lv-bar i { width:100% !important; background:repeating-linear-gradient(-45deg,var(--c) 0 8px,color-mix(in srgb,var(--c) 45%,transparent) 8px 16px);
  background-size:200% 100%; animation:lv-stripe 1.2s linear infinite } .lv-run .lv-cd b { color:var(--c) }
.lv-feed { display:grid; gap:8px; padding-top:4px } .lv-fh { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 10px }
.lv-fh b { font-size:15px } .lv-fh small { font-size:11px; color:var(--muted) }
.lv-list { list-style:none; margin:0; padding:0; display:grid; gap:2px; position:relative }
.lv-list::before { content:""; position:absolute; left:47px; top:6px; bottom:6px; width:1px; background:var(--line) }
.lv-ev { position:relative; display:grid; grid-template-columns:44px minmax(0,1fr) auto; align-items:center; gap:10px; padding:7px 4px 7px 0; border-radius:10px }
.lv-ev::before { content:""; position:absolute; left:44px; top:50%; width:7px; height:7px; margin-top:-3.5px; border-radius:50%; background:var(--w,var(--muted));
  box-shadow:0 0 0 3px var(--surface), 0 0 8px var(--w,transparent) }
.lv-ev > p { margin:0 0 0 12px; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere; line-height:1.35 } .lv-ev > p b { color:var(--fg) }
.lv-ev time { display:grid; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12px; color:var(--fg); font-variant-numeric:tabular-nums; line-height:1.25 }
.lv-ev time small { font-family:var(--sans,inherit); font-size:10px; color:var(--muted) }
.lv-who { font-size:10px; font-weight:700; letter-spacing:.08em; color:var(--w,var(--muted)); margin-right:2px }
.lv-amt { font-style:normal; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--fg2) }
.lv-amt.good { color:var(--good) } .lv-amt.bad { color:var(--bad) }
.lv-w-pick, .lv-w-acct { --w:var(--lv-pick) } .lv-w-sell { --w:var(--lv-sell) } .lv-w-radar { --w:var(--lv-radar) } .lv-w-lp { --w:var(--lv-lp) } .lv-w-scan { --w:var(--lv-scan) }
.lv-dim > p { color:var(--muted) } .lv-dim > p b { color:var(--fg2) }
.lv-new { animation:lv-in .7s cubic-bezier(.2,.8,.2,1), lv-glow 6s ease-out }
.lv-none { font-size:var(--fs-s); color:var(--muted); padding:6px 0 }
.lv-list > li.lv-ev:nth-child(n+""" + str(FEED_SHOWN + 1) + r""") { display:none } .lv-all:checked ~ .lv-list > li.lv-ev { display:grid }
.lv-showall { justify-self:start; color:var(--accent); font-size:var(--fs-s); font-weight:500; cursor:pointer; padding:6px 0; min-height:32px }
.lv-all:checked ~ .lv-showall { display:none }
@keyframes lv-ping { 0% { box-shadow:0 0 0 0 rgba(255,77,94,.6) } 80%,100% { box-shadow:0 0 0 8px rgba(255,77,94,0) } }
@keyframes lv-stripe { to { background-position:-32px 0 } }
@keyframes lv-in { from { opacity:0; transform:translateY(-8px) } to { opacity:1; transform:none } }
@keyframes lv-glow { 0%,40% { background:color-mix(in srgb,var(--w,var(--accent)) 16%,transparent) } 100% { background:transparent } }
@keyframes lv-up { 0%,30% { border-color:var(--good); background:color-mix(in srgb,var(--good) 22%,var(--chip)) } 100% { } }
@keyframes lv-dn { 0%,30% { border-color:var(--bad); background:color-mix(in srgb,var(--bad) 22%,var(--chip)) } 100% { } }
@media (prefers-reduced-motion: reduce) { .lv-badge.on i, .lv-new, .lv-chip.lv-up, .lv-chip.lv-dn, .lv-run .lv-bar i { animation:none } .lv-bar i { transition:none } }
"""
