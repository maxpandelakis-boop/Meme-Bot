#!/usr/bin/env python3
"""selftest_radarui.py: the checks of the Radar tab, the trap-check line and the "no good coin" marks (WP5b; SPEC 11: U3, U4, U5, U8, U10, A3).

  python3 selftest_radarui.py                 -> PASS/FAIL per check, "ALL PASS" at the end (exit code 1 on any failure)
  python3 selftest_radarui.py --shots DIR     -> also writes the screenshots of SPEC 12 (1-5, 10, 11) into DIR

selftest.main calls checks(check, env) (env: {"skips": selftest.SKIPS}); the node and Playwright parts follow the same SKIPS rules as
selftest.py (a missing node or Playwright is named, not failed). Everything runs from fixtures: a recommend-mode db written here, radar.json
docs in every state, a stand-in for the GitHub API and the live store. Fake money only: nothing here buys anything.

traps.py (WP1) is used when it exists; until then a stand-in with the frozen API (load_weights, signals_scan, rate, chips) is put in
sys.modules for these checks only and taken out again (it is never written as a file).
"""
import gzip, json, os, random, re, shutil, subprocess, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MIN, H = 60_000, 3_600_000
XSS_NAME, XSS_SYM, XSS_X = "<img src=x onerror=alert(1)>", "<script>alert(2)</script>", "javascript:alert(4)"
BANNED = re.compile(r"\bsafe\b|\bguaranteed\b|\bbuy (it|now|this)\b|\bbuy\b(?! rule)", re.I)

# ---------------------------------------------------------------------------------------------- a stand-in for traps.py (WP1's frozen API)
TRAPS_STANDIN = r'''
import re
BRAND = re.compile(r"(?i)\b(grok|elon|trump|openai|tesla|spacex)\b")
W0 = {"v": 1, "src": "stand-in", "hard": ["instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "staircase10"],
      "soft": ["no_socials", "holder_cluster", "creator_sold", "pumping_5m"], "maxSoft": 1, "pushBlock": ["holder_cluster"],
      "points": {"instant_pool": 3, "rugger_wallets": 3, "brand_name": 2, "bot_volume": 2, "rc_danger": 3, "staircase10": 3, "no_socials": 1,
                 "holder_cluster": 1, "creator_sold": 1, "pumping_5m": 1},
      "evidence": {"instant_pool": {"rugWith": 0.6, "rugWithout": 0.2, "lift": 2.94, "ci": [2.54, 3.39], "n": 1646}},
      "zero": {"dev_rugged_before": "reversed in our data"}}
def load_weights(path=None):
    return dict(W0)
def signals_scan(y, pr_mint_ms, wm):
    f, rk = y.get("f") or {}, y.get("risk") if isinstance(y.get("risk"), dict) else None
    born = y.get("_born")
    m2p = (born - pr_mint_ms) / 1000.0 if born and pr_mint_ms else None
    rug = set((wm or {}).get("rug") or [])
    holders = [h for h in ((rk or {}).get("holders") or [])]
    return {"mintToPoolS": m2p, "instantPool": None if m2p is None else (0 <= m2p < 60), "wmChecked": wm is not None,
            "rugHolders": sum(1 for h in holders if h in rug) if wm is not None else None, "brand": bool(BRAND.search(str(y.get("name") or "") + " " + str(y.get("sym") or ""))),
            "buys": f.get("buys1"), "rcReport": rk is not None, "rcDanger": list((rk or {}).get("danger") or []), "socN": f.get("socN"), "m5": f.get("m5"),
            "creatorSold": ((rk or {}).get("dev") or {}).get("devSold"), "cluster": None, "ageMin": y.get("ageMin"), "x": y.get("x") or None}
def rate(S, W):
    hard = [n for n, v in (("instant_pool", S["instantPool"] is True), ("rugger_wallets", (S["rugHolders"] or 0) >= 3), ("brand_name", S["brand"]),
                           ("bot_volume", (S["buys"] or 0) >= 3000), ("rc_danger", bool(S["rcDanger"]))) if v]
    soft = [n for n, v in (("no_socials", S["socN"] == 0), ("creator_sold", S["creatorSold"] is True), ("pumping_5m", (S["m5"] or 0) >= 20)) if v]
    unknown = [n for n, v in (("rc_report", not S["rcReport"]), ("mint_time", S["mintToPoolS"] is None), ("walletmem", not S["wmChecked"])) if v]
    verdict = "trap" if hard else "good" if not unknown and len(soft) <= 1 else "watch"
    pts = max(sum(W["points"].get(n, 1) for n in hard + soft) + 2 * (not S["rcReport"]), sum(W["points"].get(n, 3) for n in hard))
    return {"verdict": verdict, "pts": pts, "upside": 0, "hard": hard, "soft": soft, "plus": [], "info": ["dev_dead"] if S.get("x") else [], "unknown": unknown,
            "push": verdict == "good" and not unknown, "n": 9 - len(unknown)}
TEXT = {"instant_pool": "pool opened with the mint", "brand_name": "brand/celebrity name", "bot_volume": "3,000+ buys already", "no_socials": "no socials",
        "creator_sold": "creator sold", "rc_report": "RugCheck pending", "mint_time": "mint time unknown", "walletmem": "wallet memory unavailable", "dev_dead": "dev: 12 launches, 11 dead"}
def chips(r, S):
    out = [["bad", "%d holders from rugged coins" % S["rugHolders"] if n == "rugger_wallets" else "RugCheck danger: %s" % S["rcDanger"][0] if n == "rc_danger" else TEXT[n]] for n in r["hard"]]
    out += [["warn", "+%d%% in 5 min" % round(S["m5"]) if n == "pumping_5m" else TEXT[n]] for n in r["soft"]]
    out += [["unk", TEXT[n]] for n in r["unknown"]]
    ok = []
    if S["mintToPoolS"] is not None and S["mintToPoolS"] >= 120:
        ok.append(["ok", "curve %d min before pool" % (S["mintToPoolS"] // 60)])
    if S["wmChecked"] and not (S["rugHolders"] or 0):
        ok.append(["ok", "no rugger wallets"])
    if S["rcReport"]:
        ok.append(["ok", "RugCheck report"])
    out += ok[:3] + [["info", TEXT[n]] for n in r["info"]]
    return out[:8]
'''


def traps_for_test():
    """(module, standin): the real traps.py when it has the frozen API, else the stand-in (put in sys.modules until restore())."""
    try:
        import traps as T
        if all(hasattr(T, n) for n in ("load_weights", "signals_scan", "rate", "chips")):
            return T, False
    except ImportError:
        pass
    mod = types.ModuleType("traps")
    exec(TRAPS_STANDIN, mod.__dict__)
    sys.modules["traps"] = mod
    return mod, True


def b58(rng, suffix="pump"):
    return "".join(rng.choice(ALPH) for _ in range(44 - len(suffix))) + suffix


# ---------------------------------------------------------------------------------------------- fixtures
def radar_doc(now, kind="good", rng=None):
    """A radar.json (Appendix A) as the radar job writes it: kind good (one coin without traps), empty (none, seven with traps or
    unchecked), late, stopped, off, hours, xss (a coin named like an HTML tag with a javascript: X link)."""
    rng = rng or random.Random(5)
    lag = {"late": 8 * MIN, "stopped": 40 * MIN}.get(kind, 30_000)
    t = now - lag
    good = {"addr": b58(rng), "sym": "PEPE2", "name": "Pepe Two", "pair": b58(rng, ""), "dex": "pumpswap", "lp": "pump.fun", "pool": t - 6 * MIN - 6000,
            "mint": t - 2 * H - 6 * MIN, "age": 6.1, "px": 0.0000123, "mc": 81200.0, "liq": 23400.0, "m5": 12.4, "buys": 412, "sells": 133,
            "x": "https://x.com/pepetwo", "v": "good", "pts": 1, "up": 2, "hard": [], "soft": ["no_socials"], "plus": ["tweet"], "info": ["dev_dead", "sniped30"],
            "unknown": [], "n": 9, "first": t - 4 * MIN, "push": t - 3 * MIN, "found": ["pf:graduated", "gt:new"],
            "line": [["warn", "no socials"], ["ok", "curve 4 min before pool"], ["ok", "no rugger wallets"], ["ok", "RugCheck report"],
                     ["info", "dev: 12 launches, 11 dead"], ["info", "61% sniped in 30 s (12 wallets)"]],
            "d": {"mintToPoolS": 240, "swAvg": 1.2, "rugHolders": 0, "buys": 412, "socN": 0, "m5": 12.4, "devN": 12, "devDead": 11, "snip30": 61, "snip30N": 12,
                  "rcDanger": [], "stair": {"n": 6, "rise": 0.08, "stair": False}, "upP": 0.22, "zeroP": 0.31}}
    others = [
        {"addr": b58(rng), "sym": "GROKAI", "age": 4.2, "v": "trap", "pts": 6, "hard": ["brand_name", "instant_pool"],
         "line": [["bad", "brand/celebrity name"], ["bad", "pool opened with the mint"], ["warn", "no socials"], ["info", "6 wallets in launch block (~44%)"]]},
        {"addr": b58(rng), "sym": "MOONER", "age": 8.7, "v": "trap", "pts": 3, "hard": ["bot_volume"], "line": [["bad", "3,000+ buys already"], ["ok", "RugCheck report"]]},
        {"addr": b58(rng), "sym": "NORC", "age": 2.1, "v": "watch", "pts": 2, "unknown": ["rc_report"], "line": [["unk", "RugCheck pending"], ["ok", "curve 3 min before pool"]]},
        {"addr": b58(rng), "sym": "METEO", "age": 5.5, "v": "watch", "pts": 0, "unknown": ["mint_time"], "line": [["unk", "mint time unknown"], ["ok", "RugCheck report"]]},
        {"addr": b58(rng), "sym": "TWOWARN", "age": 7.0, "v": "watch", "pts": 2, "soft": ["no_socials", "creator_sold"],
         "line": [["warn", "no socials"], ["warn", "creator sold"], ["ok", "RugCheck report"]]},
        {"addr": b58(rng), "sym": "RUGGY", "age": 3.3, "v": "trap", "pts": 3, "hard": ["rugger_wallets"], "line": [["bad", "3 holders from rugged coins"]]},
        {"addr": b58(rng), "sym": "PUMPY", "age": 9.1, "v": "watch", "pts": 3, "soft": ["pumping_5m", "no_socials"], "line": [["warn", "+34% in 5 min"], ["warn", "no socials"]]}]
    recent = [{"addr": good["addr"], "sym": "PEPE2", "good": t - 4 * MIN, "later": {"5": None, "15": None, "30": None, "60": None}, "out": None},
              {"addr": b58(rng), "sym": "HIRE", "good": t - 95 * MIN, "later": {"5": 1.12, "15": 0.94, "30": 1.4, "60": 2.3}, "out": {"rug1h": False, "win1h": True, "x60": 2.3}},
              {"addr": b58(rng), "sym": "SEALS", "good": t - 130 * MIN, "later": {"5": 0.8, "15": 0.3, "30": 0.05, "60": 0.01}, "out": {"rug1h": True, "win1h": False, "x60": 0.01}},
              {"addr": b58(rng), "sym": "CALM", "good": t - 40 * MIN, "later": {"5": 1.05, "15": 1.1, "30": 0.97, "60": None}, "out": None},
              {"addr": b58(rng), "sym": "OLDONE", "good": t - 5 * H, "later": {"5": 1.0, "15": 1.0, "30": 1.0, "60": 1.0}, "out": {"rug1h": False, "win1h": False, "x60": 1.0}}]
    doc = {"v": 1, "kind": "radar", "t": t, "next": t + 150_000, "run": {"id": "1234", "start": t - 20 * MIN, "end": t + 35 * MIN, "cycle": 8, "source": "chain"},
           "state": "running", "why": "", "secs": 63.2, "model": {"from": "prior", "n": 212, "need": 300, "auc": None, "at": t - 2 * H},
           "counts": {"seen": 7 if kind == "empty" else 8, "good": 0 if kind == "empty" else 1, "pushed": 0 if kind == "empty" else 1, "seenAgeMed": 3.1},
           "wm": {"t": t - 50 * MIN, "nCoins": 4120}, "coins": [] if kind == "empty" else [good], "others": others,
           "lastGood": {"addr": recent[1]["addr"], "sym": "HIRE", "at": t - 34 * MIN} if kind == "empty" else {"addr": good["addr"], "sym": "PEPE2", "at": t},
           "recent": recent, "record": {"calls": 37, "rug": 0.03, "win": 0.14, "eur": -1.2, "n60": 33, "ci": {"rug": [0.0, 0.1], "win": [0.05, 0.27]}},
           "hosts": {"dexscreener": "ok", "rugcheck": "ok", "pump.fun": "ok", "geckoterminal": "ok", "rpc": "ok"},
           "notes": ["RugCheck limited: 2 coins not fully checked"] if kind == "empty" else [], "lines": ["cycle 8: 8 seen, 1 without traps, 1 pushed (63 s)"]}
    if kind == "off":
        doc.update(state="off", coins=[], others=[], next=None)
    elif kind == "hours":
        doc.update(state="hours", coins=[], others=[], next=t + 6 * H)
    elif kind == "xss":
        doc["coins"] = [dict(good, sym=XSS_SYM, name=XSS_NAME, x=XSS_X, line=[["warn", XSS_NAME], ["ok", "RugCheck report"]],
                             d=dict(good["d"], **{"xKind": XSS_NAME}))]
        doc["others"] = [dict(others[0], sym=XSS_SYM, line=[["bad", XSS_NAME]])]
        doc["coins"].append({"addr": "0xNOT<b>SOLANA", "sym": "BADADDR", "v": "good"})       # dropped: not base58
    return doc


def young_rows(now, rng):
    """recommend.json young rows (the fields memebot writes) with the fixture's own pool time (_born) for the stand-in."""
    wallets = [b58(rng, "") for _ in range(6)]

    def row(sym, name, born_min, **kw):
        f = dict({"m5": 4.0, "buys1": 300, "socN": 2}, **kw.pop("f", {}))
        r = {"sym": sym, "name": name, "addr": b58(rng), "pair": b58(rng, ""), "dex": "pumpswap", "px": 0.00002, "mc": 60000.0, "liq": 18000.0, "vol": 90000.0,
             "score": 61.0, "rank": None, "why": "new launch", "safety": "RugCheck: no danger flags", "ok": True, "x": "https://x.com/" + re.sub(r"\W", "", sym.lower())[:12] or "x",
             "f": f, "src": ["pf:graduated"], "risk": {"danger": [], "warn": [], "holdersN": 210, "holders": wallets[:2]}, "launchpad": "pump.fun", "tier": None,
             "upP": 0.25, "zeroP": 0.3, "floor": "clears the relaxed floor", "ageMin": born_min, "gates": [], "_born": now - 10 * MIN - born_min * MIN}
        r.update(kw)
        return r
    rows = [row("CLEANY", "Clean Dog", 7), row("GROKY", "Grok Agent", 12), row("INSTA", "Insta Cat", 22), row("NORC", "No Report", 31, risk=None),
            row(XSS_SYM, XSS_NAME, 44, x=XSS_X), row("RUGGY", "Rug Holders", 50, risk={"danger": [], "warn": [], "holdersN": 90, "holders": wallets[2:5]}),
            row("SOCLESS", "No Socials Two", 55, f={"socN": 0, "m5": 35.0})]
    for i, r in enumerate(rows):
        r["bought"] = 3.0 if i < 5 else None
    mints = {rows[0]["addr"]: rows[0]["_born"] - 4 * MIN, rows[1]["addr"]: rows[1]["_born"] - 9 * MIN, rows[2]["addr"]: rows[2]["_born"] - 20_000,
             rows[5]["addr"]: rows[5]["_born"] - 5 * MIN, rows[6]["addr"]: rows[6]["_born"] - 6 * MIN, rows[4]["addr"]: rows[4]["_born"] - 3 * MIN}
    return rows, mints, wallets[2:5]


def build_db(tmp, now, side=True, radar="good", tier="fallback", name="db"):
    """A recommend-mode db: one pick of the given tier, seven new launches, mb/pairs.json and mb/walletmem.json.gz (side), mb/radar_live.json."""
    import memebot as M
    rng = random.Random(11)
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    rows, mints, ruggers = young_rows(now, rng)
    pick = {"sym": "BIGDOG", "name": "Big Dog", "addr": b58(rng), "pair": b58(rng, ""), "dex": "raydium", "px": 0.0012, "mc": 1.2e6, "liq": 180000.0, "vol": 900000.0,
            "score": 48.0, "rank": 1, "why": "momentum", "safety": "RugCheck: no danger flags", "ok": True, "x": "", "f": {"c6": 12.0}, "src": [], "risk": {"danger": []},
            "launchpad": "pump.fun", "tier": tier, "relaxed": ["6h change under the gate"] if tier in ("fallback", "risky") else [], "upP": 0.31, "zeroP": 0.12, "bought": "watch coin" if tier == "watch" else None}
    rec = {"t": now - 10 * MIN, "rule": M.RULE, "scanned": 1180, "passed": 37, "picks": [pick], "runnersUp": [], "young": rows, "youngOf": len(rows), "flagged": [], "reason": ""}
    json.dump(rec, open(os.path.join(d, "db", "memebot", "recommend.json"), "w"))
    json.dump({"lastRun": now - 9 * MIN, "runs": 12, "rule": M.RULE, "horizon": "24h"}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    if side:
        json.dump([{"address": a, "pf": {"createdAt": ms}} for a, ms in mints.items()], open(os.path.join(d, "pairs.json"), "w"))
        with gzip.open(os.path.join(d, "walletmem.json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "t": now - 50 * MIN, "nCoins": 4120, "common": [], "sw": {}, "rug": ruggers}, f)
    if radar:
        json.dump(radar_doc(now, radar), open(os.path.join(d, "radar_live.json"), "w"))
    return d, rows


def page_of(d, now, repo="some-owner/Meme-Bot"):
    """The page as report.py renders it (with GITHUB_REPOSITORY, as on GitHub Actions, when repo is given)."""
    import report as R
    old = os.environ.get("GITHUB_REPOSITORY")
    try:
        if repo:
            os.environ["GITHUB_REPOSITORY"] = repo
        else:
            os.environ.pop("GITHUB_REPOSITORY", None)
        return R.render(R.collect(d, now))
    finally:
        if old is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = old


def visible_text(page):
    """The page's own words (tags, scripts, styles and the embedded JSON taken out)."""
    s = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", page)
    return re.sub(r"<[^>]+>", " ", s)


# ---------------------------------------------------------------------------------------------- the checks
def py_checks(check, tmp, T, standin):
    import report as R
    import page_radar as P
    now = int(time.time() * 1000)
    d, rows = build_db(tmp, now)
    page = page_of(d, now)
    # U4: every row of the New launches tab has a verdict chip and the trap line; the texts are traps.chips' own
    pane = page.split('id="pane-young"', 1)[1].split('id="pane-office"', 1)[0] if 'id="pane-young"' in page else ""
    table = pane.split("<tbody>", 1)[1].split("</tbody>", 1)[0] if "<tbody>" in pane else ""
    trs = re.findall(r"<tr(?: class=\"trap\")?>.*?</tr>", table, re.S)
    W = T.load_weights()
    mints = {p["address"]: p["pf"]["createdAt"] for p in json.load(open(os.path.join(d, "pairs.json")))}
    with gzip.open(os.path.join(d, "walletmem.json.gz"), "rt") as f:
        wm = json.load(f)
    want = []
    for y in rows:
        S = T.signals_scan(y, mints.get(y["addr"]), wm)
        rt = T.rate(S, W)
        want.append((rt["verdict"], [list(x) for x in T.chips(rt, S)]))
    got_lines = [re.findall(r'<span class="tc (\w+)(?: x2)?"><b aria-hidden="true">.</b>(.*?)</span>', tr) for tr in trs]
    texts_ok = all([[lv, R.E(t)] for lv, t in w[1][:P.LINE_SHOWN]] == [list(x) for x in g] for w, g in zip(want, got_lines))
    tv = [re.search(r'<span class="chip tv(?: (\w+))?">(.*?)</span>', tr) for tr in trs]
    red = [bool(re.match(r'<tr class="trap">', tr)) for tr in trs]
    check(len(trs) == len(rows) == 7 and all(tv) and texts_ok and red == [w[0] == "trap" for w in want] and any(red) and (any(w[0] == "good" for w in want) or not standin)
          and "without traps</span>" in pane and "with traps or unchecked</span>" in pane,
          "U4 New launches: each of the %d rows carries its verdict chip and the one-row trap line with traps.chips' own texts (%s), trap rows red-tinted (%d), the heading counts "
          "both%s" % (len(trs), "stand-in rule core" if standin else "traps.py", sum(red), "" if texts_ok else " (texts differ: %s / %s)" % (want[:2], got_lines[:2])))
    good_rows = [w for w in want if w[0] == "good"]
    head = re.search(r'<p class="tsum"><span class="chip good">(\d+) without traps</span><span class="chip[^"]*">(\d+) with traps or unchecked</span>', pane)
    check(head and int(head.group(1)) == len(good_rows) and int(head.group(2)) == len(rows) - len(good_rows),
          "U4 the New launches heading: %s without traps · %s with traps or unchecked" % (head.group(1) if head else "?", head.group(2) if head else "?"))
    # without pairs.json and the wallet memory: every row shows "?", none is green
    d2, _ = build_db(tmp, now, side=False, name="db-noside")
    p2 = page_of(d2, now).split('id="pane-young"', 1)[1].split('id="pane-office"', 1)[0]
    tb2 = p2.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    trs2 = re.findall(r"<tr(?: class=\"trap\")?>.*?</tr>", tb2, re.S)
    check(len(trs2) == 7 and not re.search(r'chip tv good', tb2) and all('<span class="tc unk' in tr for tr in trs2)
          and all(re.search(r'<span class="chip tv (warn|bad)">(\?|✕)', tr) for tr in trs2) and "0 without traps" in p2,
          "U4 without mb/pairs.json and mb/walletmem.json.gz every row carries a ? check (mint time, wallet memory) and none is green")
    # an old wallet memory (built more than 3 hours before the scan) counts as missing
    d3, _ = build_db(tmp, now, name="db-oldwm")
    with gzip.open(os.path.join(d3, "walletmem.json.gz"), "wt", encoding="utf-8") as f:
        json.dump({"v": 1, "t": now - 4 * H, "nCoins": 10, "rug": []}, f)
    p3 = page_of(d3, now).split('id="pane-young"', 1)[1].split('id="pane-office"', 1)[0]
    check("chip tv good" not in p3.split("<tbody>", 1)[1].split("</tbody>", 1)[0], "U4 a wallet memory older than 3 hours gives no green row")
    # the card's detail view: CSS-radio sub-tabs, works without a script
    cards = pane.split("Every number behind each coin", 1)[1] if "Every number behind each coin" in pane else ""
    check(cards.count('<details class="tdet">') == 7 and cards.count('<div class="dtabs">') == 7 and "RED FLAGS".lower() in cards.lower() and 'type="radio" name="ty-' in cards
          and ">Overview</label>" in cards and ">Trap check</label>" in cards and ">Numbers</label>" in cards,
          "U4 every New launches card has the detail view (Overview, Trap check, Numbers) on CSS radios")
    # the early box's one validated chip, in the live script
    check("pool opened with the mint','bad')" in R.OFFICE_LIVE_JS and "born-c.minted<60000" in R.OFFICE_LIVE_JS,
          "the early box marks only the validated trap: a pool opened within 60 s of the mint (born and minted, no full verdict)")
    # U5: the banner over the pick
    ban = {}
    for tier in ("strong", "weak", "fallback", "risky", "watch"):
        D = {"rec": {"picks": [{"sym": "P", "addr": "A" * 44, "tier": tier, "relaxed": []}], "scanned": 10, "passed": 1}, "now": now, "open": [], "state": {}}
        h = R.rec_section(D, embed=False)
        m = re.search(r'<p class="nogood (\w+)" role="note">.*?<span>(.*?)</span></p>', h)
        ban[tier] = (m.group(1), m.group(2)) if m else None
    check(ban["strong"] is None and ban["weak"] is None and ban["fallback"] == ("warn", P.BANNER) and ban["risky"] == ("bad", P.BANNER) and ban["watch"] == ("bad", P.BANNER)
          and "weak · best available" in R.tier_chip({"tier": "weak"}),
          "U5 the pick banner '%s' shows amber for fallback and red for risky and watch, not for strong or weak (weak keeps its chip) %s" % (P.BANNER, ban))
    # the Radar tab: the embedded doc is whitelisted, at most 48 KB, and closes no script; the tab sits second; no token in the page
    m = re.search(r'<script type="application/json" id="radar-doc">(.*?)</script>', page, re.S)
    emb = json.loads(m.group(1)) if m else {}
    big = radar_doc(now, "good")
    big["others"] = [dict(big["others"][0], addr=b58(random.Random(i)), sym="X%d" % i, line=[["bad", "y" * 110]] * 12) for i in range(40)]
    big["recent"] = big["recent"] * 8
    cb = P.clean_doc(big)
    huge = dict(radar_doc(now, "good"), notes=["n" * 160] * 8, coins=[dict(radar_doc(now, "good")["coins"][0], d={"k%d" % i: "v" * 60 for i in range(60)})] * 5)
    tabs = re.findall(r'<label for="(tab-\w+)" role="tab">', page)
    check(m and emb.get("kind") == "radar" and len(m.group(1).encode()) <= P.DOC_MAX and "</" not in m.group(1) and cb and len(json.dumps(cb, separators=(",", ":")).encode()) <= P.DOC_MAX
          and len(cb["others"]) < 40 and P.clean_doc({"kind": "radar"}) is None and P.clean_doc({"kind": "live", "t": now}) is None
          and tabs == ["tab-pick", "tab-radar", "tab-young", "tab-office"] and not re.search(r"ghp_[A-Za-z0-9]{10}|github_pat_|x-access-token:|sb_secret_|Bearer [A-Za-z0-9]", page),
          "the Radar tab sits second (Pick, Radar, New, Office); the embedded radar.json is whitelisted, %d bytes (at most %d; a big doc is trimmed to %d others) and cannot close "
          "its script block; no token in the page" % (len(m.group(1).encode()) if m else -1, P.DOC_MAX, len(cb["others"]) if cb else -1))
    radar_of = lambda pg: pg.split('id="pane-radar">', 1)[1].split('<div class="pane" id="pane-young">', 1)[0]
    plain = page_of(d, now, repo=None)
    check(radar_of(plain) == radar_of(page) and "radar.yml" not in visible_text(page) and 'data-r-actions hidden' in radar_of(page),
          "the Radar tab's HTML is the same with and without GITHUB_REPOSITORY (its script finds the repository in the office's live box for the GitHub poll and the Start and Stop links)")
    hc = P.clean_doc(huge)
    check(hc is None or len(json.dumps(hc, separators=(",", ":"), ensure_ascii=False).encode()) <= P.DOC_MAX, "a doc too big even without its folds is left out whole, never cut mid-coin")
    # U10 (page side): a name like an HTML tag and a javascript: X link are inert on the New launches tab and in the embedded doc
    d4, _ = build_db(tmp, now, radar="xss", name="db-xss")
    p4 = page_of(d4, now)
    check(XSS_NAME not in p4 and XSS_SYM not in p4 and "javascript:" not in p4 and R.E(XSS_NAME) in p4 and "0xNOT" not in p4,
          "U10 page: a coin named %s and a javascript: X link are escaped on the New launches tab, its cards and the embedded radar doc (the bad address is dropped)" % XSS_NAME)
    # U7 for this package's words: no "safe", "guaranteed" or advice-style "buy" in the new UI text
    import app as A
    words = [P.BANNER, P.MEASURED_NOTE, visible_text(P.pane({"now": now, "dir": d})), P.INFO_TEXT, json.dumps(P.LABELS), json.dumps(P.UNKNOWN), json.dumps(P.SKEYS)]
    words += re.findall(r"'([^'\\]{12,})'", P.JS)
    words += re.findall(r"'([^'\\]*(?:radar|Radar|trap)[^'\\]*)'", A.PAGE_JS)
    bad = [w for w in words if BANNED.search(w)]
    check(not bad and "\u2014" not in P.JS + P.CSS + json.dumps(P.LABELS) + visible_text(page),
          "U7 the radar's words carry no 'safe', 'guaranteed' or advice-style 'buy', and no em dash (%d texts read)%s" % (len(words), (" " + str(bad[:3])) if bad else ""))
    return d, page


NODE_SIM = r"""
var MB=window.MemebotLive,R=window.MemebotRadar,A=window.MemebotApp,o={};
var N=1e12,M=60000,doc=function(t,x){return Object.assign({kind:'radar',t:t,next:t+150000,state:'running',coins:[]},x||{});};
o.state=[R.radarState(doc(N-30000),N,0),R.radarState(doc(N-8*M),N,0),R.radarState(doc(N-40*M),N,0),R.radarState(doc(N,{state:'off'}),N,0),
  R.radarState(doc(N-M,{state:'hours',next:N+3*3600000}),N,0),R.radarState(null,N,0),R.radarState({kind:'live',t:N},N,0),
  R.radarState(doc(N-2*3600000,{state:'hours',next:N-3600000}),N,0),
  // a phone clock 10 minutes fast: running once the doc was seen to move (got/moved), never from the phone's clock alone
  R.radarState(doc(N-30000),N+600000,N+600000-20000,true),R.radarState(doc(N-30000),N+600000,0)];   // ... before a doc moved, the phone's clock is the first guess
var U='https://abcref.supabase.co',K='sb_publishable_AbC_12-3',now=N;
o.transport=[R.radarTransport(U,K,'gh',60,N/1000+1800,now,0),R.radarTransport(U,K,'gh',60,N/1000+1800,now,now+60000),R.radarTransport('','','gh',null,0,now,0),
  R.radarTransport('','','gh',11,N/1000+1800,now,0),R.radarTransport('','','gh',10,N/1000+1800,now,0),R.radarTransport('','','gh',3,N/1000-10,now,0),
  R.radarTransport('','','',60,0,now,0),R.radarTransport(U,'sb_secret_x','gh',60,0,now,0),R.radarTransport(U,K+'"><x','',60,0,now,0)];
o.budget=[R.budget({rem:30,reset:9,at:5},{rem:20,reset:9,remAt:7}).rem,R.budget({rem:30,reset:9,at:8},{rem:20,reset:9,remAt:7}).rem,R.budget(null,{rem:20,reset:9,remAt:7}).rem,R.budget(null,null).rem];
// the next poll: the doc's next cycle + 15 s, at least 150 s after the last (300 s on the Office tab); 20 s / 60 s on the live store
var d1=doc(N-30000);
o.next=[R.radarNext({doc:d1,now:N,last:N,tab:'radar',via:'github',got:N})-N,R.radarNext({doc:d1,now:N,last:N,tab:'office',via:'github',got:N})-N,
  R.radarNext({doc:doc(N-1000,{next:N+400000}),now:N,last:N,tab:'radar',via:'github',got:N})-N,R.radarNext({doc:d1,now:N,last:N,tab:'radar',via:'supabase',got:N})-N,
  R.radarNext({doc:doc(N-20*M),now:N,last:N,tab:'radar',via:'supabase',got:N})-N,R.radarNext({doc:d1,now:N,last:N,tab:'office',via:'supabase',got:N})-N,
  R.radarNext({doc:doc(N,{state:'off'}),now:N,last:N,tab:'radar',via:'github',got:N})-N,R.radarNext({doc:d1,now:N,last:N,tab:'radar',via:'github',got:N,rem:12,reset:N/1000+1800})-N];
// one simulated hour of GitHub's 60 requests an hour for one address: the office poll during a live scan (every 75 s) and the radar poll
// on the Office tab (at most every 300 s), both stretched by the same budget numbers; then the radar alone on its tab
function sim(officeOn,tab,rem0){var Hh=3600000,T=1e12,rem=rem0,reset=(T+Hh)/1000,calls=0,raw=0,minRem=rem,oN=T,rN=T,oS=null,rS={rem:null,reset:0,remAt:0};
  var live={live:true,updated:T,t:T,agents:[]},rd=doc(T);
  for(var now=T;now<T+Hh;now+=1000){live.updated=now-5000;rd.t=now-30000;rd.next=now+120000;
    if(officeOn&&now>=oN){if(rem>0){rem--;calls++;}oS={rem:rem,reset:reset,at:now};oN=MB.next(live,now,0,rem,reset,0,now,false);}
    if(now>=rN){var b=R.budget(oS,rS),via=R.radarTransport('','','src',b.rem,b.reset,now,0);
      if(via==='github'){if(rem>0){rem--;calls++;}rS={rem:rem,reset:reset,remAt:now};}else raw++;
      var b2=R.budget(oS,rS);rN=R.radarNext({doc:rd,now:now,last:now,tab:tab,via:via,rem:b2.rem,reset:b2.reset,fails:0,got:now,moved:false});}
    minRem=Math.min(minRem,rem);}
  return [calls,minRem,raw];}
o.sim=[sim(true,'office',60),sim(false,'radar',60),sim(true,'office',25),sim(true,'radar',60)];
o.badge=[A.radarBadge({state:'running',doc:{coins:[{v:'good'},{v:'good'},{v:'watch'}]}}),A.radarBadge({state:'running',doc:{coins:[{v:'watch'}]}}),
  A.radarBadge({state:'late',doc:{coins:[{v:'good'}]}}),A.radarBadge({state:'stopped',doc:{coins:[{v:'good'}]}}),A.radarBadge(null),A.radarBadge({state:'running',doc:{coins:'x'}})];
o.tabs=A.TABS;o.tab=[A.tab('#tab-radar'),A.tab('tab-radar'),A.tab('#radar'),A.tab('#tab-young')];
var c=R.clean({kind:'radar',t:N,coins:[{addr:'1111111111111111111111111111111111111111pump',sym:'<b>x</b>',x:'javascript:alert(1)',v:'good',line:[['bad','a'],['evil','b'],['ok',5]],d:{a:1,'b c':2,e:{f:1}}},
  {addr:'0x<b>',v:'good'}],others:[{addr:'nope'}],notes:['a\u2028b'],hosts:{'x y':'ok',rugcheck:'limited'}});
o.clean=[c.coins.length,c.coins[0].x===undefined,c.coins[0].line.length,Object.keys(c.coins[0].d).join(','),c.others.length,c.notes[0],Object.keys(c.hosts).join(','),R.clean({kind:'radar'}),R.clean(null)];
o.verdict=[R.verdict({v:'good',n:9})[1],R.verdict({v:'trap',hard:['a','b']})[1],R.verdict({v:'watch',unknown:['rc_report']})[1],R.verdict({v:'watch',soft:['a','b']})[1]];
o.groups=R.groups({line:[['bad','brand/celebrity name'],['warn','no socials'],['ok','RugCheck report']],hard:['brand_name','instant_pool'],soft:['no_socials'],unknown:['mint_time'],info:['dev_dead']});
console.log(JSON.stringify(o));
"""


def node_checks(check, tmp, skips):
    import report as R
    import page_radar as P
    import app as A
    node = shutil.which("node")
    if not node:
        skips.append("the radar page's node checks (no node)")
        print("  SKIP the radar page's node checks: node is not installed")
        return
    jd = os.path.join(tmp, "js")
    os.makedirs(jd, exist_ok=True)
    with open(os.path.join(jd, "radar.js"), "w", encoding="utf-8") as f:
        f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;},getElementById:function(){return null;}};global.navigator={};\n"
                + R.OFFICE_LIVE_JS + P.JS + A.PAGE_JS + NODE_SIM)
    r = subprocess.run([node, os.path.join(jd, "radar.js")], capture_output=True, text=True)
    try:
        o = json.loads(r.stdout)
    except ValueError:
        check(False, "U3 the radar script runs in node: %s" % r.stderr[-400:])
        return
    check(o["state"] == ["running", "late", "stopped", "off", "hours", "none", "none", "stopped", "running", "late"],
          "U3 MemebotRadar.radarState: running, late, stopped, off, hours, none (a non-radar doc too), an hours doc past its start is stopped; a phone clock 10 min fast "
          "reads a moving doc as running (before it moved, the phone's clock is only the first guess: late) %s" % o["state"])
    check(o["transport"] == ["supabase", "github", "github", "github", "raw", "github", "none", "github", "none"] and o["budget"] == [20, 30, 20, None],
          "U3 MemebotRadar.radarTransport: the live store when the page carries it (github for 2 minutes after it failed), the GitHub API while the shared budget keeps more than "
          "RESERVE, raw.githubusercontent at RESERVE until the reset, none without a source; the budget takes the newest numbers of the office poll and its own %s %s" % (o["transport"], o["budget"]))
    nx = o["next"]
    check(nx[0] == 150000 and nx[1] == 300000 and nx[2] == 415000 and nx[3] == 20000 and nx[4] == 60000 and nx[5] == 300000 and nx[6] == 600000 and nx[7] == 900000,
          "U3 the radar poll: GitHub at the doc's next cycle + 15 s, at least 150 s apart (300 s on the Office tab, 600 s while off), stretched by the budget (12 left: 900 s); "
          "the live store every 20 s fresh, 60 s stale, 300 s on the Office tab %s" % nx)
    sim = o["sim"]
    check(sim[0][0] <= 50 and sim[0][1] >= 10 and sim[1][0] <= 25 and sim[2][0] <= 15 and sim[2][1] >= 10 and sim[3][0] <= 50 and sim[3][1] >= 10,
          "U3 the shared GitHub budget: a simulated hour with the office poll during a live scan and the radar poll on the Office tab makes %d counted calls (at most 50, %d left, "
          "%d raw reads); the radar alone %d; starting with 25 left, %d calls and %d kept" % (sim[0][0], sim[0][1], sim[0][2], sim[1][0], sim[2][0], sim[2][1]))
    check(o["badge"] == [2, None, None, None, None, None] and "radar" in o["tabs"] and o["tabs"].index("radar") == 1 and len(o["tabs"]) == 5 and o["tab"] == ["radar", "radar", None, "young"],
          "A3 MemebotApp: TABS %s, tab('#tab-radar') = radar, the badge counts coins with no trap found only while the radar runs and none at 0 %s" % (o["tabs"], o["badge"]))
    check(o["clean"] == [1, True, 1, "a,e", 0, "a b", "rugcheck", None, None] and o["verdict"] == ["✓ No trap found · 9 checks", "✕ 2 traps", "? not fully checked", "! 2 warnings"]
          and [g[0] for g in o["groups"]] == ["bad", "warn", "unk", "ok", "info"] and o["groups"][0][2] == ["brand/celebrity name", "pool opened with the mint"]
          and o["groups"][2][2] == ["mint time unknown"],
          "U3 the script's whitelist drops a bad address, a javascript: X link, unknown levels and keys; the verdict chips and the Trap check groups (names past the line get "
          "their words) %s" % [o["clean"], o["groups"][:2]])


def browser(check, tmp, d, skips, shots=None):
    """The Radar tab, the New launches tab and the installed app in Chromium. GitHub's API and the live store are stubbed with the
    fixture docs (fresh times), every other request is refused."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the radar page's browser checks (no Playwright)")
        print("  SKIP the radar page's browser checks: Playwright is not installed")
        return
    import report as R
    import bot as B
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    pages_url, sb_url = "https://some-owner.github.io/Meme-Bot/", "https://abcref.supabase.co"
    ms = lambda: int(time.time() * 1000)
    page_html = page_of(d, ms())
    # the installed app: bot.py site with the live store
    sd = os.path.join(tmp, "site")
    env_keep = {k: os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")}
    os.environ.update(SUPABASE_URL=sb_url, SUPABASE_PUBLISHABLE_KEY="sb_publishable_OKkey_1234567890")
    try:
        with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f:
            f.write(page_html)
        B.site(d, sd, "https://github.com/some-owner/Meme-Bot")
    finally:
        for k, v in env_keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    files = {n: open(os.path.join(sd, n), "rb").read() for n in os.listdir(sd) if os.path.isfile(os.path.join(sd, n))}
    state = {"doc": lambda: radar_doc(ms(), "good"), "gh": [], "sb": [], "other": []}
    dialogs, errs = [], []
    out = {}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def ctx_page(w=390, h=844, dark=False, hash_="#tab-radar", app=False, html_=None):
                ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark" if dark else "light", service_workers="block")
                ctx.add_init_script("window.addEventListener('memebot-radar', e => { window.__rev = [e.detail.state, e.detail.good, e.detail.via]; });")
                if app:
                    ctx.add_init_script("Object.defineProperty(Navigator.prototype,'standalone',{get:function(){return true;}});")
                cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "apikey, content-type, accept, prefer", "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}

                def handler(route):
                    u = route.request.url
                    if u.startswith(pages_url):
                        name = u[len(pages_url):].split("#")[0].split("?")[0] or "index.html"
                        if app and name in files:
                            ct = {"html": "text/html; charset=utf-8", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
                            route.fulfill(status=200, body=files[name], headers={"Content-Type": ct})
                        elif not app:
                            route.fulfill(status=200, body=html_ or page_html, headers={"Content-Type": "text/html; charset=utf-8"})
                        else:
                            route.fulfill(status=404, body="")
                    elif u.startswith("https://api.github.com/"):
                        state["gh"].append(u)
                        if "live.json" in u and state.get("live"):
                            route.fulfill(status=200, body=json.dumps(state["live"]()), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
                        elif "radar.json" in u and "ref=radar-data" in u:
                            route.fulfill(status=200, body=json.dumps(state["doc"]()), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*",
                                                                                                "X-RateLimit-Remaining": "51", "X-RateLimit-Reset": str(ms() // 1000 + 1800),
                                                                                                "Access-Control-Expose-Headers": "X-RateLimit-Remaining, X-RateLimit-Reset"})
                        else:
                            route.fulfill(status=404, body="{}", headers={"Access-Control-Allow-Origin": "*"})
                    elif u.startswith(sb_url + "/rest/v1/"):
                        if route.request.method == "OPTIONS":
                            route.fulfill(status=204, headers=cors)
                            return
                        state["sb"].append(u)
                        body = [{"doc": state["doc"](), "updated": "now"}] if "id=eq.radar" in u else []
                        route.fulfill(status=200, body=json.dumps(body), headers=dict(cors, **{"Content-Type": "application/json"}))
                    else:
                        state["other"].append(u[:60])
                        route.abort()
                ctx.route("**/*", handler)
                pg = ctx.new_page()
                pg.on("dialog", lambda dl: (dialogs.append(dl.message), dl.dismiss()))
                pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                pg.goto(pages_url + hash_)
                return ctx, pg

            def wait(pg, js, ms_=8000):
                try:
                    pg.wait_for_function(js, timeout=ms_)
                    return True
                except Exception:
                    return False

            def shot(pg, name, full=False, el=None):
                if shots:
                    os.makedirs(shots, exist_ok=True)
                    p = os.path.join(shots, name)
                    (pg.locator(el).first.screenshot(path=p) if el else pg.screenshot(path=p, full_page=full))
            radar_js = """() => { const b = document.querySelector('[data-radar]'), q = s => b.querySelector(s), vis = e => !!(e && e.getClientRects().length);
              return { tab: document.getElementById('tab-radar').checked, hash: location.hash, pill: q('[data-r-pill-t]').textContent, st: q('[data-r-pill]').getAttribute('data-st'),
                cards: b.querySelectorAll('[data-r-cards] > li').length, dim: b.querySelectorAll('[data-r-cards] > li.dim').length,
                lines: Array.from(b.querySelectorAll('[data-r-cards] .tline')).map(l => Array.from(l.children).map(c => [c.className, c.textContent])),
                chips: Array.from(b.querySelectorAll('[data-r-cards] .rchips .chip')).map(c => c.textContent), empty: vis(q('[data-r-empty]')) ? q('[data-r-empty]').innerText : '',
                ocnt: q('[data-r-ocnt]').textContent, others: vis(q('[data-r-others]')), tabcnt: (document.querySelector('[data-r-tabcnt]') || {}).hidden ? '' : (document.querySelector('[data-r-tabcnt]') || {}).textContent,
                stats: q('[data-r-stats]').innerText, rec: q('[data-r-recline]').textContent, model: q('[data-r-model]').textContent,
                links: Array.from(b.querySelectorAll('[data-r-cards] a')).map(a => [a.getAttribute('href'), a.rel, a.target]),
                act: Array.from(b.querySelectorAll('[data-r-actions] a')).map(a => [a.textContent, a.getAttribute('href'), vis(a) && a.getBoundingClientRect().height]),
                imgs: b.querySelectorAll('img').length, hscroll: document.documentElement.scrollWidth - innerWidth, ev: window.__rev || null }; }"""
            nodoc = re.sub(r'<script type="application/json" id="radar-doc">.*?</script>', "", page_html, flags=re.S)
            # 1. one good coin (light and dark, phone and desktop)
            for w, h, dark in ((390, 844, False), (390, 844, True), (1280, 900, False), (1280, 900, True)):
                ctx, pg = ctx_page(w, h, dark)
                wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running' && (window.__rev || [])[2] === 'github'")
                info = pg.evaluate(radar_js)
                out.setdefault("good", info)
                shot(pg, "1-radar-good-%s-%dx%d.png" % ("dark" if dark else "light", w, h))
                if w == 390 and not dark:
                    # 3. the detail view, Trap check tab
                    pg.click("[data-r-cards] > li summary")
                    pg.wait_for_timeout(200)
                    det = pg.evaluate("""() => { const li = document.querySelector('[data-r-cards] > li'), d = li.querySelector('details'), pane = Array.from(li.querySelectorAll('.dpane')).find(p => p.getClientRects().length);
                      return { open: d.open, groups: pane ? Array.from(pane.querySelectorAll('h5')).map(h => h.textContent) : [], tabs: Array.from(li.querySelectorAll('.dtabbar label')).map(l => l.textContent),
                        hscroll: document.documentElement.scrollWidth - innerWidth }; }""")
                    out["detail"] = det
                    shot(pg, "3-radar-detail-trapcheck-light-390x844.png", el="[data-r-cards] > li")
                    pg.click("[data-r-cards] > li .dtabbar label:nth-child(4)")
                    pg.wait_for_timeout(150)
                    out["later"] = pg.evaluate("Array.from(document.querySelectorAll('[data-r-cards] > li .dpane')).filter(p => p.getClientRects().length).map(p => p.innerText)[0] || ''")
                ctx.close()
            # the why fold (the study weights) on the Radar tab
            ctx, pg = ctx_page()
            wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running'")
            pg.evaluate("document.querySelector('.rwhy').open = true")
            pg.wait_for_timeout(150)
            out["why"] = pg.evaluate("document.querySelector('.rwhy').innerText")
            shot(pg, "1b-radar-why-fold-light-390x844.png", el=".rwhy")
            ctx.close()
            # the early box on the New launches tab: the one validated chip (a pool opened within 60 s of the mint), nothing else of the verdict
            t_e = ms()
            ra = random.Random(9)
            ecoins = [{"addr": b58(ra), "sym": "INSTANT", "born": t_e - 3 * MIN, "minted": t_e - 3 * MIN - 20_000, "ageMin": 3, "liq": 9000.0, "mc": 30000.0, "k": 1, "rc": {"level": "clean"}},
                      {"addr": b58(ra), "sym": "CURVED", "born": t_e - 5 * MIN, "minted": t_e - 9 * MIN, "ageMin": 5, "liq": 9000.0, "mc": 30000.0, "k": 2, "rc": {"level": "clean"}},
                      {"addr": b58(ra), "sym": "NOMINT", "born": t_e - 4 * MIN, "ageMin": 4, "liq": 9000.0, "mc": 30000.0, "k": 3, "rc": None}]
            state["live"] = lambda: {"v": 1, "t": t_e, "live": True, "updated": ms() - 5000, "agents": [{"id": "dispatch", "status": "done"}, {"id": "market", "status": "running"}],
                                     "young": {"v": 1, "t": t_e, "at": t_e + 1000, "state": "listed", "rcState": "done", "partial": False, "minLiq": 5000, "coins": ecoins}}
            ctx, pg = ctx_page(hash_="#new")
            wait(pg, "() => document.querySelectorAll('[data-early-list] > li').length === 3", 10000)
            out["early"] = pg.evaluate("Object.fromEntries(Array.from(document.querySelectorAll('[data-early-list] > li')).map(li => [li.querySelector('.es').textContent, Array.from(li.querySelectorAll('.chips .chip')).map(c => [c.className, c.textContent])]))")
            ctx.close()
            state["live"] = None
            # 2. none good: the empty state, the fold open (light and dark)
            state["doc"] = lambda: radar_doc(ms(), "empty")
            for w, h, dark in ((390, 844, False), (390, 844, True), (1280, 900, False)):
                ctx, pg = ctx_page(w, h, dark)
                wait(pg, "() => !document.querySelector('[data-r-empty]').hidden && document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running'")
                pg.evaluate("document.querySelector('[data-r-others]').open = true; document.querySelector('[data-r-rec]').open = true")
                pg.wait_for_timeout(150)
                info = pg.evaluate(radar_js)
                out.setdefault("empty", info)
                if w == 390:
                    out.setdefault("empty_h", [])
                    out["empty_h"].append(info["hscroll"])
                shot(pg, "2-radar-empty-fold-open-%s-%dx%d.png" % ("dark" if dark else "light", w, h), full=True)
                ctx.close()
            # 4. header states: late, off, hours (and stopped, none)
            out["states"] = {}
            for kind in ("late", "off", "hours", "stopped"):
                state["doc"] = (lambda k: lambda: radar_doc(ms(), k))(kind)
                ctx, pg = ctx_page(html_=nodoc)
                wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === '%s'" % kind)
                out["states"][kind] = pg.evaluate(radar_js)
                if kind in ("late", "off", "hours"):
                    shot(pg, "4-radar-header-%s-light-390x844.png" % kind, el="[data-radar]")
                ctx.close()
            state["doc"] = lambda: {"message": "Not Found"}
            ctx, pg = ctx_page(html_=nodoc)
            pg.wait_for_timeout(1200)
            out["states"]["none"] = pg.evaluate(radar_js)
            ctx.close()
            # U10 in the browser: the xss doc on the Radar tab and in the detail view
            state["doc"] = lambda: radar_doc(ms(), "xss")
            ctx, pg = ctx_page()
            wait(pg, "() => document.querySelectorAll('[data-r-cards] > li').length === 1 && document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running'")
            pg.click("[data-r-cards] > li summary")
            pg.click("[data-r-cards] > li .dtabbar label:nth-child(3)")
            pg.wait_for_timeout(200)
            out["xss"] = pg.evaluate(radar_js)
            out["xss_text"] = pg.evaluate("document.querySelector('[data-radar]').innerText")
            ctx.close()
            # 5. the New launches tab with trap lines and a red row; 11. the pick card with its banner; U8 every tab at both widths, light and dark
            state["doc"] = lambda: radar_doc(ms(), "good")
            out["h"] = {}
            for w, h, dark in ((390, 844, False), (390, 844, True), (1280, 900, False), (1280, 900, True)):
                ctx, pg = ctx_page(w, h, dark, hash_="")
                for tab in ("tab-pick", "tab-radar", "tab-young", "tab-office"):
                    pg.click('label[for="%s"]' % tab)
                    pg.wait_for_timeout(150)
                    if tab == "tab-young":
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = true)")
                        pg.wait_for_timeout(100)
                    out["h"]["%s %dx%d %s" % (tab, w, h, "dark" if dark else "light")] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                    if tab == "tab-young" and w == 390 and not dark:
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = false)")
                        out["young"] = pg.evaluate("""() => { const p = document.getElementById('pane-young'), rows = Array.from(p.querySelectorAll('tbody tr'));
                          return { rows: rows.length, red: rows.filter(r => r.classList.contains('trap')).length, tint: rows.filter(r => r.classList.contains('trap')).map(r => getComputedStyle(r.querySelector('td')).backgroundColor),
                            lines: rows.map(r => { const l = r.querySelector('.tline'); return l ? l.getBoundingClientRect().height : 0; }),
                            verdicts: rows.map(r => (r.querySelector('.chip.tv') || {}).textContent || ''), imgs: p.querySelectorAll('img').length }; }""")
                        el_ = pg.locator("#pane-young .tbl.stack").first
                        el_.scroll_into_view_if_needed()
                        shot(pg, "5-new-launches-trap-lines-light-390x844.png")
                        pg.evaluate("""() => { const f = Array.from(document.querySelectorAll('#pane-young details')).find(d => /Every number behind/.test(d.querySelector('summary').textContent));
                          f.open = true; const c = f.querySelectorAll('.card.rec')[1]; c.querySelector('details.tdet').open = true; c.id = 'shot-card'; }""")
                        pg.wait_for_timeout(150)
                        out["ycard"] = pg.evaluate("""() => { const c = document.getElementById('shot-card'), pane = Array.from(c.querySelectorAll('.dpane')).find(p => p.getClientRects().length);
                          return { groups: pane ? Array.from(pane.querySelectorAll('h5')).map(h => h.textContent) : [], verdict: (c.querySelector('.ttrap .chip') || {}).textContent || '',
                            hscroll: document.documentElement.scrollWidth - innerWidth }; }""")
                        shot(pg, "5b-new-launch-card-trapcheck-light-390x844.png", el="#shot-card")
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = false)")
                    if tab == "tab-young" and w == 1280 and not dark:
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = false)")
                        pg.locator("#pane-young .tsum").first.scroll_into_view_if_needed()
                        shot(pg, "5-new-launches-trap-lines-light-1280x900.png")
                    if tab == "tab-pick" and not dark:
                        out.setdefault("banner", pg.evaluate("(() => { const b = document.querySelector('#pane-pick .nogood'); return b ? [b.className, b.innerText, getComputedStyle(b).backgroundColor] : null; })()"))
                        shot(pg, "11-pick-banner-light-%dx%d.png" % (w, h))
                ctx.close()
            # 10. the installed app: five tabs, the Radar tab from the live store (no GitHub poll), its badge, the deep links
            state["doc"] = lambda: radar_doc(ms(), "good")
            state["gh"].clear()
            state["sb"].clear()
            out["app"] = {}
            for w, h, dark in ((390, 844, False), (390, 844, True), (320, 640, False)):
                ctx, pg = ctx_page(w, h, dark, hash_="#tab-radar", app=True)
                ok = wait(pg, "() => document.documentElement.classList.contains('app') && ((document.querySelector('.appbar [data-tab=\"radar\"] .ab-cnt') || {}).textContent || '') === '1'", 10000)
                a = pg.evaluate("""() => ({ app: document.documentElement.classList.contains('app'), tabs: Array.from(document.querySelectorAll('.appbar button')).map(b => b.getAttribute('data-tab')),
                  names: Array.from(document.querySelectorAll('.appbar button > span:not([class])')).map(s => s.textContent), apptab: document.documentElement.getAttribute('data-apptab'),
                  radar: document.getElementById('tab-radar').checked, aria: document.querySelector('.appbar [data-tab="radar"]').getAttribute('aria-label'),
                  hscroll: document.documentElement.scrollWidth - innerWidth, cards: document.querySelectorAll('[data-r-cards] > li').length,
                  btnW: Math.min(...Array.from(document.querySelectorAll('.appbar button')).map(b => b.getBoundingClientRect().width)),
                  over: Array.from(document.querySelectorAll('.appbar button > span:not([class])')).filter(s => s.scrollWidth > s.clientWidth + 1).length })""")
                a["badge_ok"] = ok
                out["app"]["%dx%d %s" % (w, h, "dark" if dark else "light")] = a
                if w == 390:
                    shot(pg, "10-app-shell-radar-%s-390x844.png" % ("dark" if dark else "light"))
                if w == 390 and not dark:
                    for t in ("young", "office", "account", "pick"):
                        pg.click('.appbar button[data-tab="%s"]' % t)
                        pg.wait_for_timeout(150)
                        out["h"]["app %s 390x844" % t] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                    # a tap on the radar notification while the app is open: the service worker tells it which tab to show
                    pg.evaluate("navigator.serviceWorker && navigator.serviceWorker.dispatchEvent(new MessageEvent('message', {data: {type: 'memebot-open', url: location.href.split('#')[0] + '#tab-radar'}}))")
                    pg.wait_for_timeout(200)
                    out["deep"] = pg.evaluate("[document.documentElement.getAttribute('data-apptab'), document.getElementById('tab-radar').checked]")
                ctx.close()
            out["calls"] = {"gh": len(state["gh"]), "sb": len([u for u in state["sb"] if "id=eq.radar" in u]), "other": state["other"][:3]}
            br.close()
    except Exception as e:
        check(False, "the radar page's browser checks could not run (Playwright is installed; Chromium needs a short TMPDIR path): %s" % str(e)[:300])
        return
    g, e_ = out["good"], out["empty"]
    check(g["tab"] and g["hash"] == "" and g["st"] == "running" and g["pill"].startswith("Radar running · checked ") and " · next " in g["pill"] and "this run until" in g["pill"]
          and g["cards"] == 1 and g["dim"] == 0 and g["chips"][:1] == ["✓ No trap found · 9 checks"] and g["tabcnt"] == "1" and g["ocnt"] == "7" and g["others"]
          and [c[1] for c in g["lines"][0]] == ["!no socials", "✓curve 4 min before pool", "✓no rugger wallets", "✓RugCheck report", "+2", "+4"]
          and g["ev"] == ["running", 1, "github"] and "8" in g["stats"] and "37 calls without traps" in g["rec"] and "radar data 212 of 300 needed" in g["model"]
          and [a[:2] for a in g["act"]] == [["Start \u2197", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"], ["Stop \u2197", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"]]
          and all(a[2] >= 44 for a in g["act"]),
          "U3 browser: #tab-radar opens the Radar tab with Start and Stop links to radar.yml (44 px); the GitHub poll brings the doc; a good coin's card shows its chip and its "
          "line (4 chips and +2), the tab count 1, the fold count 7, the record line and the model status; the memebot-radar event says running, 1 good %s" % ({k: g[k] for k in ("pill", "chips", "ev", "act")}))
    check(set(u for u, _, _ in g["links"]) >= {"https://x.com/pepetwo"} and all(u.startswith("https://") and rel == "noopener noreferrer" and tg == "_blank" for u, rel, tg in g["links"])
          and not any("jup.ag" in u or "swap" in u for u, _, _ in g["links"]),
          "U3 browser: the card's links are DexScreener, pump.fun and X only, in a new tab, no swap link %s" % [u[:40] for u, _, _ in g["links"]])
    check(e_["cards"] == 0 and "No clean coin right now" in e_["empty"] and "7 seen in the last 10 min · all with traps or not fully checked · checks every 2½ min" in e_["empty"]
          and "last coin without traps: HIRE, 34 min ago" in e_["empty"] and e_["ocnt"] == "7" and e_["tabcnt"] == "" and all(x <= 0 for x in out["empty_h"]),
          "U3 browser: no good coin shows 'No clean coin right now', the seen line, the last good coin (HIRE, 34 min ago) and 'Seen but not clean (7)'; no tab count %r" % e_["empty"][:160])
    st = out["states"]
    check(st["late"]["st"] == "late" and st["late"]["dim"] == 1 and any(c.startswith("as of ") for c in st["late"]["chips"]) and st["late"]["pill"].startswith("Radar late · last check")
          and st["late"]["tabcnt"] == "" and st["stopped"]["st"] == "stopped" and st["stopped"]["dim"] == 1 and st["off"]["st"] == "off" and st["off"]["pill"] == "Radar off · switched off on GitHub"
          and st["hours"]["st"] == "hours" and "next start" in st["hours"]["pill"] and st["none"]["st"] == "none" and st["none"]["pill"] == "Radar not started yet"
          and "Radar not started yet" in st["none"]["empty"],
          "U3 browser: a late or stopped doc greys its coins with 'as of HH:MM' and no count; the header says late, stopped, off, hours (with the next start) and not started yet %s" % (
              {k: v["pill"] for k, v in st.items()}))
    det = out.get("detail") or {}
    check(det.get("open") and det.get("tabs") == ["Overview", "Trap check", "Numbers", "Later"] and det.get("groups") == ["Warnings 1", "Passed 3", "Measured, not weighted yet 2"]
          and "Later" in det.get("tabs") and "…" in out.get("later", "") and det.get("hscroll", 1) <= 0,
          "browser: a tap opens the detail view on its Trap check tab (Overview, Trap check, Numbers, Later; warnings, passed, measured) %s" % det)
    why = out.get("why") or ""
    check("pool opened with the mint" in why and "Weight 0" in why and "Not in v1: coins still on the bonding curve" in why and "radar data 212 of 300 needed" in why,
          "the 'Why these checks?' fold shows each check with its study evidence, the weight-0 list, the model status and what v1 leaves out (%r)" % why[:120])
    ea = out.get("early") or {}
    inst = lambda k: [c for c in ea.get(k, []) if "pool opened with the mint" in c[1]]
    check(len(ea) == 3 and len(inst("INSTANT")) == 1 and "bad" in inst("INSTANT")[0][0] and not inst("CURVED") and not inst("NOMINT")
          and not any("No trap found" in c[1] for v in ea.values() for c in v),
          "the early box marks a pool opened within 60 s of the mint with the red chip, and nothing else of the verdict (no green, nothing for an unknown mint) %s" % {k: [c[1] for c in v][:3] for k, v in ea.items()})
    yc = out.get("ycard") or {}
    check(yc.get("verdict") == "\u2715 trap" and yc.get("groups", [""])[0].startswith("Red flags") and yc.get("hscroll", 1) <= 0,
          "U4 browser: a New launches card opens its detail view on the Trap check tab without a script's help (red flags first) %s" % yc)
    x = out["xss"]
    check(x["imgs"] == 0 and not dialogs and XSS_NAME in out["xss_text"] and not any("javascript" in u for u, _, _ in x["links"]) and x["cards"] == 1,
          "U10 browser: a coin named %s with a javascript: X link renders as text on the Radar tab and in its detail view, no link to it, the bad address dropped" % XSS_NAME)
    y = out.get("young") or {}
    check(y.get("rows") == 7 and y.get("red", 0) >= 1 and y.get("imgs") == 0 and all(0 < hh <= 30 for hh in y.get("lines", [])) and all(y.get("verdicts", [])),
          "U4 browser: the New launches rows each show the verdict chip and a one-row trap line (%s px tall), %d rows red-tinted (%s)" % (y.get("lines"), y.get("red", 0), (y.get("tint") or [""])[0]))
    bn = out.get("banner")
    check(bn and "nogood warn" in bn[0] and bn[1].endswith(P_BANNER()), "U5 browser: the fallback pick shows the amber banner %s" % (bn[:2] if bn else bn))
    hs = out["h"]
    check(all(v <= 0 for v in hs.values()) and all(a["hscroll"] <= 0 for a in out["app"].values()) and len(hs) >= 20,
          "U8 no sideways scroll on Pick, Radar, New and Office at 390 x 844 and 1280 x 900, light and dark, and in the installed app on all five tabs (%d views%s)" % (
              len(hs) + len(out["app"]), "" if all(v <= 0 for v in hs.values()) else " " + str({k: v for k, v in hs.items() if v > 0})))
    ap = out["app"]["390x844 light"]
    check(ap["app"] and ap["tabs"] == ["pick", "radar", "young", "office", "account"] and ap["names"] == ["Pick", "Radar", "New", "Office", "Account"] and ap["radar"]
          and ap["apptab"] == "radar" and ap["badge_ok"] and ap["aria"] == "Radar, 1 listed now" and ap["cards"] == 1 and out.get("deep") == ["radar", True]
          and out["calls"]["gh"] == 0 and out["calls"]["sb"] >= 1 and all(a["over"] == 0 and a["btnW"] >= 60 for a in out["app"].values()) and not errs,
          "A3 installed app: five tabs (Pick, Radar, New, Office, Account), #tab-radar and the notification's message open the Radar tab, its badge says 1 (read out in words), "
          "the live store's row radar feeds it and GitHub is not polled; no label cut at 320 px %s" % ({k: ap[k] for k in ("names", "aria")} if not errs else [errs[:2], ap, out.get("deep"), out["calls"]]))


def P_BANNER():
    import page_radar as P
    return P.BANNER


def checks(check, env=None):
    env = env or {}
    skips = env.get("skips") if isinstance(env.get("skips"), list) else []
    print("== the Radar tab, the trap-check line and the no-good-coin marks (WP5b)")
    T, standin = traps_for_test()
    tmp = tempfile.mkdtemp(prefix="mb-rui-")
    old_mod = {k: sys.modules.get(k) for k in ("page_radar",)}
    try:
        d, page = py_checks(check, tmp, T, standin)
        node_checks(check, tmp, skips)
        browser(check, tmp, d, skips, env.get("shots"))
    finally:
        if standin:
            sys.modules.pop("traps", None)
        shutil.rmtree(tmp, ignore_errors=True)
    return skips


def main():
    fails, skips = [], []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    shots = None
    if "--shots" in sys.argv:
        shots = sys.argv[sys.argv.index("--shots") + 1]
    checks(check, {"skips": skips, "shots": shots})
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d skipped: %s)" % (len(skips), "; ".join(skips)) if skips else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
