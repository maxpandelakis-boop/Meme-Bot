#!/usr/bin/env python3
"""selftest_brain.py: the coin sheet of the brain (page_brain.py, the Gehirn tab): a tap on a coin opens its data. Fake money only: the
fixtures are hand-made docs, nothing is fetched.

  B1 one article per coin node, in the nodes' order, all in one dialog inside the brain and hidden until a tap; the tap hint
  B2 the pick's sheet: the bot's thoughts, its numbers in German notation, the eight filters with its own values, the safety checks,
     the links (pump.fun and DexScreener first, the pair in DexScreener's address), the DexScreener chart only as a fold (no iframe in
     the page), every string escaped
  B3 a bought rocket candidate: its paper position with the price line's points (page_rocket.chart_div); a candidate: the share of the
     buy cut; a sold one: the sell
  B4 no pick and no rocket round: no dialog, no hint; a broken record: the brain still renders and that coin's sheet says so
  B5 the pick's paper position from the account rows (page_account)
  W1-W6 in Chromium (390 and 1280 px): a tap beside a coin's dot opens its sheet as a modal dialog that fits the screen, the cycle stops
     while it is open, the position's line is drawn, the DexScreener iframe appears only when its fold opens, the sheet closes with
     its button, Escape and a tap beside it, the line under the brain opens the coin it names, "Radar-Tab" switches tabs; no script errors

  python3 selftest_brain.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  selftest.main: checks(check, SKIPS) after the traders' UI checks
"""
import json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import selftest_office as SO

NOW, MIN = SO.NOW, 60_000
XSS = SO.XSS
PICK = "EJAxERvKU4kEVXn3NarjvRtgaMaJyP9ZuMeKA7JJpump"
PAIR = "3unG5b7czBspnmjFRZzzNyQVpk8q3LERr6BAYnFohdfz"
RK = ["4krFcF31xNiRQseavbJ579r9fYfaqmbycXEZi49gpump", "Baw61KXAJk4MMnNJPBa87S8F77oNhMy7gQ63S8SLpump", "9RhEr8CvHZ92bKsnrwodi2qkcNxYyghjAzCSJgQPpump",
      "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"]
POOL = "DBFD4YE8Y6U6ipmaoH3s9jKQJwcK61Gsxgiss1bBuLUB"
CHART = [[0, 1.0], [5, 1.32], [12, 0.91], [20, 1.64]]


def pick_doc(t, **kw):
    f = {"ageH": 20.07, "buys1": 377.0, "buyShare": 0.6459, "c1": -3.55, "c6": 50.04, "c24": 1793.0, "liqMc": 0.0868, "srcN": 3.0}
    risk = {"score": 1.0, "lpLocked": 100.0, "danger": [], "warn": [], "holdersN": 2087.0, "top1": 4.42, "top10": 17.4, "insiders": 0.0, "creatorPct": 2.02,
            "mutable": False, "dev": {"devPct": 2.02, "devSold": 0.0, "mintAuthOff": 1.0, "freezeAuthOff": 1.0}, "gp": {"mintable": 0.0, "freezable": 0.0}}
    p = {"sym": "CHOO", "name": "Choo " + XSS, "addr": PICK, "pair": PAIR, "dex": "pumpswap", "px": 0.001059, "mc": 1048113.0, "liq": 90934.45, "vol": 1337973.94,
         "score": 47.3, "rank": 3, "why": "score 47/100 " + XSS, "safety": "RugCheck: no danger flags", "ok": True, "x": "https://x.com/ChooTheRescue", "f": f,
         "src": ["pf:top"], "risk": risk, "launchpad": "Pump.Fun", "standin": False, "lowOdds": True, "tier": "weak", "relaxed": [], "zeroP": 0.1015, "upP": 0.1896}
    p.update(kw)
    return {"t": t, "rule": "m9-2h", "scanned": 11897, "passed": 5, "picks": [p], "runnersUp": [], "reason": ""}


def rocket_json(t):
    top = [{"t": t, "addr": RK[0], "sym": "MI", "pool": POOL, "age": 33, "score": 0.0712, "mc": 197978, "px": 0.0001979, "buy": True},
           {"t": t, "addr": RK[1], "sym": XSS, "pool": None, "age": 269, "score": 0.0028, "mc": 1101766, "px": 0.001117, "buy": False},
           {"t": t, "addr": RK[2], "sym": "TRENCH", "pool": "x", "age": 153, "score": 0.0402, "mc": 101300, "px": 0.0001039, "buy": False},
           {"t": t, "addr": RK[3], "sym": "OLDIE", "pool": POOL, "age": 400, "score": 0.0101, "mc": 150000, "px": 0.0002, "buy": False}]
    op = {RK[0]: {"addr": RK[0], "sym": "MI", "pool": POOL, "t": t, "px": 0.0001979, "score": 0.0712, "cut": 0.0699, "hi": 1.64, "lo": 0.91, "now": 1.64, "chart": CHART}}
    cl = [{"addr": RK[3], "sym": "OLDIE", "pool": POOL, "t": t - 300 * MIN, "px": 0.0002, "score": 0.08, "cut": 0.0699, "hi": 1.2, "lo": 0.69, "out": t - 200 * MIN,
           "mult": 0.69, "eur": -6.3, "why": "stop", "chart": [[0, 1.0], [40, 1.2], [100, 0.69]]}]
    return {"v": 1, "t": t, "book": {"open": op, "closed": cl, "summary": {"trades": 1, "open": 1, "eur": -6.3, "openEur": 32.6}}, "checked": {},
            "round": {"candidates": 963, "scored": 8, "bought": 1}, "top": top, "cut": 0.0699, "model": {}}


def mk(d, pick=True, rocket=True, **kw):
    runs = SO.mk_db(d)
    SO.wj(os.path.join(d, "db", "memebot", "state.json"), {"lastRun": runs[0], "runs": 12, "horizon": "2h"})      # the live profile
    if pick:
        SO.wj(os.path.join(d, "db", "memebot", "recommend.json"), pick_doc(runs[0], **kw))
    if rocket:
        SO.wj(os.path.join(d, "db", "memebot", "rocket.json"), rocket_json(NOW - 10 * MIN))
    return SO.build(d)


def brain(page):
    return page[page.find('<div class="pane" id="pane-office">'):page.find('<div class="pane" id="pane-account"')]


def art(pane, i):
    m = re.search(r'<article class="bc" data-cd="%d" hidden>(.*?)</article>' % i, pane, re.S)
    return m.group(1).replace("\xa0", " ") if m else ""


def html_checks(check, tmp):
    page = mk(os.path.join(tmp, "full"))
    pane = brain(page)
    nodes = re.findall(r'<g class="bn-coin (\w+)" data-coin="(\d+)"[^>]*role="button" tabindex="0" aria-label="([^"]*)"><circle class="hit"', pane)
    arts = re.findall(r'<article class="bc" data-cd="(\d+)" hidden>', pane)
    check(len(nodes) == 5 and [n[1] for n in nodes] == arts == ["0", "1", "2", "3", "4"] and [n[0] for n in nodes] == ["pick", "buy", "cand", "cand", "cand"]
          and pane.count("<dialog") == 1 and pane.find("<dialog") > pane.find("data-bn-thoughts") and "Tippe auf einen Coin" in pane,
          "B1 one tap target and one hidden article per coin, in the nodes' order (%s / %s), one dialog in the brain, the tap hint" % ([n[:2] for n in nodes], arts))
    a0 = art(pane, 0)
    check("Mein Pick für die nächsten 2 Stunden" in a0 and "19 % Chance auf Gewinn und 10 % Risiko Totalverlust" in a0 and "mindestens 20 %" in a0
          and "1,05 Mio. $" in a0 and "90.934 $" in a0 and "0,00106 $" in a0 and "47 von 100 · Rang 3" in a0 and "+1.793 %" in a0,
          "B2 the pick's sheet: thoughts with the odds, the numbers in German notation")
    gates = re.findall(r'<li class="ok"><i aria-hidden="true">✓</i><span>([^<]*)</span><em>([^<]*)</em></li>', a0)
    check([g[0] for g in gates][:8] == ["Pool", "Kein Fake", "Alter", "Größe", "Liquidität", "Volumen", "Chart", "Käufer"] and ("Chart", "1 h −3,5 % · 6 h +50 %") in gates
          and ("Liquidität", "90.934 $ · 9 % des Marktwerts") in gates and ("Halter", "2.087") in gates and ("Größte Wallet", "4,4 %") in gates
          and ("Mint-/Freeze-Rechte", "abgegeben") in gates, "B2 the eight filters with the coin's own values, the safety checks in German (%s)" % gates[:3])
    lk = re.findall(r'<a href="([^"]*)" target="_blank" rel="noopener noreferrer">([^<]*)</a>', a0)
    check([n for _, n in lk][:2] == ["pump.fun", "DexScreener"] and lk[1][0] == "https://dexscreener.com/solana/" + PAIR and ("https://x.com/ChooTheRescue", "X / Twitter") in lk
          and "<iframe" not in pane and 'data-bc-live="https://dexscreener.com/solana/%s?embed=1&amp;theme=dark' % PAIR in a0 and "Alle Gründe des Bots" in a0,
          "B2 links (pump.fun, DexScreener with the pair first), the live chart only as a fold, no iframe in the page")
    check(XSS not in pane and "Choo &lt;img src=x onerror=alert(1)&gt;" in a0 and "score 47/100 &lt;img" in a0, "B2 the coin's strings are escaped")
    a1, a2, a3 = art(pane, 1), art(pane, 2), art(pane, 3)
    check("Raketen-Kauf" in a1 and "mein Modell gab ihm 7,1 % Chance auf 10x" in a1 and "Ich verkaufe bei −30 %" in a1 and "offen seit" in a1 and "jetzt x1,64" in a1
          and 'data-rk-ch="[[0,1.0],[5,1.32],[12,0.91],[20,1.64]]"' in a1.replace("&quot;", '"') and 'data-bc-tab="young"' in a1
          and "https://dexscreener.com/solana/" + POOL in a1, "B3 a bought candidate: its paper position, the price line's points, the way to the Radar tab, its pool's chart")
    check("Nicht gekauft" in a2 and "4 % der Kaufschwelle" in a2 and "&lt;img" in a2 and "Er ist nah dran" not in a2 and "https://pump.fun/coin/" + RK[1] in a2
          and "Nicht gekauft" in a3 and "58 % der Kaufschwelle" in a3 and "Er ist nah dran" in a3 and "https://dexscreener.com/solana/%s\"" % RK[2] in a3,
          "B3 candidates: the share of the cut, 'nah dran' from half of it; a pool that is not an address falls back to the mint")
    a4 = art(pane, 4)
    check("verkauft um" in a4 and "Stopp −30 %" in a4 and "Ergebnis −6,30 €" in a4 and "gab ihm 8,0 % Chance" in a4 and "data-rk-end=" in a4 and "Alle Verkäufe" in a4,
          "B3 a coin sold before: the numbers of its buy, the sell, its result and its line")
    empty = brain(mk(os.path.join(tmp, "empty"), pick=False, rocket=False))
    check("data-brain" in empty and "<dialog" not in empty and "Tippe auf einen Coin" not in empty, "B4 no pick and no round: no dialog and no hint")
    bad = brain(mk(os.path.join(tmp, "bad"), rocket=False, f="x", risk=[1], relaxed="ab", rank="?", tier="fallback"))
    a0b = art(bad, 0)
    check("data-brain" in bad and "<dialog" in bad and ("gelockert" in a0b or "ließen sich nicht lesen" in a0b), "B4 a broken pick record: the brain renders, the sheet still opens")
    import page_brain as PB, report as R
    t = NOW - 30 * MIN
    D = {"paper": {"acct2": {"rows": [{"p": {"addr": PICK}, "grp": "hold", "ticket": 50.0, "tBuy": t, "pnl": 3.2, "pct": 0.064, "open": True},
                                      {"p": {"addr": PICK}, "grp": "young", "ticket": 3.0, "tBuy": t + MIN, "pnl": -3.0, "pct": -1.0, "open": False}]}}}
    pp = PB.paper_pos(D, R, PICK).replace("\xa0", " ")
    check("50 € auf Papier gekauft um %s" % R.local(t).strftime("%H:%M") in pp and "jetzt +3,20 € (+6,4 %)" in pp and 'class="bc-p good"' in pp
          and PB.paper_pos(D, R, RK[0]) == "", "B5 the pick's paper position from the account (not the young group's), nothing for another coin (%s)" % re.sub(r"<[^>]+>", " ", pp))
    return page


def browser_checks(check, skips, page):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the brain's browser checks (no Playwright)")
        print("  SKIP the brain's browser checks: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    errs, frames = [], []
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

        def open_(w, h=844):
            ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark", has_touch=w < 700)

            def handler(route):
                u = route.request.url
                if u.startswith(SO.PAGES):
                    route.fulfill(status=200, body=page, headers={"Content-Type": "text/html; charset=utf-8"})
                else:
                    if "dexscreener.com" in u:
                        frames.append(u)
                    route.abort()
            ctx.route("**/*", handler)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("dialog", lambda d: (errs.append("dialog " + d.message), d.dismiss()))
            pg.goto(SO.PAGES)
            pg.evaluate("document.getElementById('tab-office').click()")
            pg.wait_for_timeout(300)
            return ctx, pg
        state = """(function(){var d=document.querySelector('[data-bn-dlg]'),a=[].filter.call(d.querySelectorAll('[data-cd]'),function(x){return !x.hidden;});
          var r=d.getBoundingClientRect();return {open:d.open,modal:d.matches(':modal'),shown:a.map(function(x){return x.getAttribute('data-cd');}),
          w:r.width,left:r.left,right:r.right,top:r.top,bottom:r.bottom,sw:d.scrollWidth,cw:d.clientWidth,vw:innerWidth,vh:innerHeight,
          on:[].map.call(document.querySelectorAll('.bn-coin'),function(c){return c.classList.contains('on');}).indexOf(true),
          svg:a.length?a[0].querySelectorAll('.rk-ch svg path.ln').length:0,ifr:d.querySelectorAll('iframe').length,
          young:document.getElementById('tab-young').checked,lock:document.documentElement.classList.contains('bn-lock')};})()"""
        ctx, pg = open_(390)
        dot = pg.locator('.bn-coin[data-coin="1"] circle.c').bounding_box()
        pg.mouse.click(dot["x"] + dot["width"] / 2 + 11, dot["y"] + dot["height"] / 2 + 6)      # beside the dot, inside its tap circle
        pg.wait_for_timeout(400)
        s1 = pg.evaluate(state)
        check(s1["open"] and s1["modal"] and s1["shown"] == ["1"] and s1["left"] >= 0 and s1["right"] <= s1["vw"] + 0.5 and s1["sw"] <= s1["cw"] + 1
              and s1["bottom"] <= s1["vh"] + 0.5 and s1["top"] > 0 and s1["lock"], "W1 390 px: a tap beside the bought coin's dot opens its sheet, modal, within the screen (%s)" % s1)
        check(s1["svg"] == 1 and s1["ifr"] == 0, "W2 the position's price line is drawn when the sheet opens; no chart iframe yet (%s, %s)" % (s1["svg"], s1["ifr"]))
        pg.wait_for_timeout(3600)
        check(pg.evaluate(state)["on"] == 1, "W2 the brain's cycle stops while the sheet is open")
        pg.evaluate("document.querySelector('[data-cd=\"1\"] .bc-live > summary').click()")
        pg.wait_for_timeout(300)
        s2 = pg.evaluate(state)
        src = pg.evaluate("(document.querySelector('[data-cd=\"1\"] .bc-fr iframe')||{}).src||''")
        check(s2["ifr"] == 1 and src.startswith("https://dexscreener.com/solana/" + POOL + "?embed=1"), "W3 the DexScreener iframe appears only when its fold opens (%s)" % src[:70])
        pg.locator('[data-cd="1"] [data-bc-x]').click()
        pg.wait_for_timeout(200)
        s3 = pg.evaluate(state)
        check(not s3["open"] and not s3["lock"], "W4 the close button closes the sheet and frees the page's scroll")
        pg.locator('.bn-coin[data-coin="0"]').tap()
        pg.wait_for_timeout(300)
        s4 = pg.evaluate(state)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        s5 = pg.evaluate(state)
        check(s4["open"] and s4["shown"] == ["0"] and not s5["open"], "W4 a tap on the pick opens its sheet, Escape closes it (%s, %s)" % (s4["shown"], s5["open"]))
        pg.evaluate("document.querySelector('.bn-focus li.on').click()")
        pg.wait_for_timeout(300)
        s6 = pg.evaluate(state)
        on = pg.evaluate("[].map.call(document.querySelectorAll('.bn-focus li'),function(l){return l.classList.contains('on');}).indexOf(true)")
        pg.mouse.click(195, 30)                  # beside the sheet: its backdrop
        pg.wait_for_timeout(300)
        s7 = pg.evaluate(state)
        check(s6["open"] and s6["shown"] == [str(on)] and not s7["open"], "W5 the line under the brain opens the coin it names (%s); a tap beside the sheet closes it" % s6["shown"])
        pg.locator('.bn-coin[data-coin="1"]').tap()
        pg.wait_for_timeout(300)
        pg.locator('[data-cd="1"] [data-bc-tab]').click()
        pg.wait_for_timeout(300)
        s8 = pg.evaluate(state)
        check(not s8["open"] and s8["young"], "W5 'Radar-Tab' closes the sheet and opens the Radar tab")
        ctx.close()
        ctx, pg = open_(1280, 900)
        pg.locator('.bn-coin[data-coin="2"]').click()
        pg.wait_for_timeout(400)
        s9 = pg.evaluate(state)
        check(s9["open"] and s9["shown"] == ["2"] and s9["w"] <= 562 and abs((s9["left"] + s9["right"]) / 2 - s9["vw"] / 2) < 2 and s9["top"] > 0 and s9["bottom"] < s9["vh"],
              "W6 1280 px: the sheet is a centred card (%s)" % {k: s9[k] for k in ("w", "left", "top", "bottom")})
        ctx.close()
        br.close()
    check(not errs, "W6 no script errors and no alert from the escaped strings (%s)" % errs[:3])


def checks(check, skips=None):
    skips = skips if skips is not None else []
    for k in ("GITHUB_REPOSITORY", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"):
        os.environ.pop(k, None)
    tmp = tempfile.mkdtemp(prefix="mb-brain-")
    try:
        page = html_checks(check, tmp)
        browser_checks(check, skips, page)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, skips)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d check group%s skipped: %s)" % (len(skips), "" if len(skips) == 1 else "s", "; ".join(skips)) if skips else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
