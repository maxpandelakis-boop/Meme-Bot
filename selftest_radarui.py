#!/usr/bin/env python3
"""selftest_radarui.py: the checks of the launch radar on the New tab (the old Radar tab, merged into New), the trap-check line and the "no good coin" marks (WP5b; SPEC 11: U3, U4, U5, U8, U10, A3).

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
# hostile strings: tags that run when written through innerHTML (an <img onerror>, not a <script>, which innerHTML never runs)
# (symbols are cut to 24 characters by the whitelist: theirs fit whole)
XSS_NAME, XSS_SYM, XSS_X = "<img src=x onerror=alert(1)>", "<img src=y onerror=a(2)>", "javascript:alert(4)"
XSS_DANGER, XSS_NOTE, XSS_OTHER = "<img src=d onerror=a(5)>", "<img src=n onerror=alert(6)>", "<img src=o onerror=a(7)>"
XSS_ALL = (XSS_NAME, XSS_SYM, XSS_DANGER, XSS_NOTE, XSS_OTHER)
BANNED = re.compile(r"\bsafe\b|\bguaranteed\b|\bbuy (it|now|this)\b|\bbuy\b(?! rule)", re.I)

# ---------------------------------------------------------------------------------------------- a stand-in for traps.py (WP1's frozen API)
TRAPS_STANDIN = r'''
import re
BRAND = re.compile(r"(?i)\b(grok|elon|trump|openai|tesla|spacex)\b")
H = 3_600_000
# the shape of WP1's radar_weights.json (994c2c7): evidence {label, rows: [...]}, zero [{signal, label, reason, note, rows}]
W0 = {"v": 1, "src": "stand-in", "hard": ["instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "staircase10"],
      "soft": ["no_socials", "holder_cluster", "creator_sold", "pumping_5m"], "maxSoft": 1, "pushBlock": ["holder_cluster"],
      "points": {"instant_pool": 3, "rugger_wallets": 3, "brand_name": 2, "bot_volume": 2, "rc_danger": 3, "staircase10": 3, "no_socials": 1,
                 "holder_cluster": 1, "creator_sold": 1, "pumping_5m": 1},
      "evidence": {"instant_pool": {"label": "pool opened within 60 s of the mint", "rows": [
                       {"cohort": "L", "outcome": "rug1h", "with": 0.602, "without": 0.131, "n": 397, "n0": 306, "lift": 4.605, "lo": 3.466, "hi": 6.353, "verdict": "holds (one half weak)"},
                       {"cohort": "P", "outcome": "rugAny", "with": 0.624, "without": 0.16, "n": 117, "n0": 125, "lift": 3.9, "lo": 2.412, "hi": 6.927, "verdict": "HOLDS"},
                       {"cohort": "L", "outcome": "rug1h", "with": 0.6, "without": 0.2, "n": 397, "n0": 1249, "lift": 2.94, "lo": 2.54, "hi": 3.39}]},
                   "no_socials": {"label": "no socials", "rows": [{"cohort": "S", "outcome": "rug2h", "with": 0.7, "without": 0.4, "n": 300, "lift": 1.8, "lo": 1.5, "hi": 2.1, "verdict": "HOLDS"},
                                                                   {"cohort": "L", "outcome": "rug1h", "with": 0.55, "without": 0.2, "n": 410, "lift": 2.693, "lo": 2.2, "hi": 3.3, "verdict": "HOLDS"}]},
                   "dev_dead": {"label": "most of the dev's earlier launches are dead", "rows": []}},
      "zero": [{"signal": "rc.top1>20", "label": "biggest wallet over 20%", "reason": "reversed", "note": "coins with it rugged less, not more", "rows": []},
               {"signal": "rcn.creator_rugged", "label": "RugCheck: creator history of rugged tokens", "reason": "no effect", "note": "", "rows": []},
               {"signal": "rcn.copycat", "label": "RugCheck: copycat token", "reason": "too rare", "note": "", "rows": []},
               {"signal": "zp", "reason": "no effect for young coins", "rows": []}]}
def load_weights(path=None):
    return dict(W0)
def pair_times(pr):
    mint = (pr.get("pf") or {}).get("createdAt") or (pr.get("ll") or {}).get("createdAt")
    pool = pr.get("pairCreatedAt")
    return mint, (pool if pool and pool > 1e12 else None)
def signals_scan(y, pr_mint_ms, wm, now=None, pool=None, W=None):
    # as WP1's: the pool time is `pool` (pairs.json pairCreatedAt), else y["pool"], else now minus the row's age (f.ageH)
    f, rk = y.get("f") or {}, y.get("risk") if isinstance(y.get("risk"), dict) else None
    if pool is None:
        pool = y.get("pool")
    if pool is None and now is not None and f.get("ageH") is not None:
        pool = now - f["ageH"] * H
    m2p = (pool - pr_mint_ms) / 1000.0 if pool is not None and pr_mint_ms else None
    rug = set((wm or {}).get("rug") or [])
    holders = [h for h in ((rk or {}).get("holders") or [])]
    wm_ok = wm is not None and (now is None or now - (wm.get("t") or 0) <= 3 * H)
    return {"mintToPoolS": m2p, "instantPool": None if m2p is None else (0 <= m2p < 60), "wmChecked": wm_ok,
            "rugHolders": sum(1 for h in holders if h in rug) if wm_ok else None, "brand": bool(BRAND.search(str(y.get("name") or "") + " " + str(y.get("sym") or ""))),
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
    """A radar.json (Appendix A) as the radar job writes it: kind good (one coin without traps; a watch coin in "coins" that the page
    must not show as a card), empty (none, seven with traps or unchecked), late, stopped, off, hours, xss and xss-empty (tags for every
    name, note and host state, a javascript: X link), hosts (WP3's routine host states, one limited and one down, an old wallet memory), round
    (one round of the hourly radar: state done, the next round in 55 minutes, a call with miss60)."""
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
                  "rcDanger": [], "stair": {"n": 6, "rise": 0.08, "stair": False}, "odds": {"up": 0.22, "zero": 0.31, "note": "not used: on coins under 1 h they did not separate winners"}}}
    others = [
        {"addr": b58(rng), "sym": "GROKAI", "age": 4.2, "v": "trap", "pts": 6, "hard": ["brand_name", "instant_pool"],
         "line": [["bad", "brand/celebrity name"], ["bad", "pool opened with the mint"], ["warn", "no socials"], ["info", "6 wallets in launch block (~44%)"]]},
        {"addr": b58(rng), "sym": "MOONER", "age": 8.7, "v": "trap", "pts": 3, "hard": ["bot_volume"], "line": [["bad", "3,000+ buys already"], ["ok", "RugCheck report"]]},
        {"addr": b58(rng), "sym": "NORC", "age": 2.1, "v": "watch", "pts": 2, "unknown": ["rc_report"], "line": [["unk", "RugCheck pending"], ["ok", "curve 3 min before pool"]]},
        {"addr": b58(rng), "sym": "METEO", "age": 5.5, "v": "watch", "pts": 0, "unknown": ["mint_time"], "line": [["unk", "mint time unknown"], ["ok", "RugCheck report"]]},
        {"addr": b58(rng), "sym": "TWOWARN", "age": 7.0, "v": "watch", "pts": 2, "soft": ["holder_cluster", "creator_sold"],          # a long first chip: alone on a phone
         "line": [["warn", "holder cluster (insider network of 232)"], ["warn", "creator sold"], ["ok", "RugCheck report"]]},
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
           "wm": {"t": t - 50 * MIN, "nCoins": 4120}, "coins": [] if kind == "empty" else [good, dict(others[2], v="watch", d={})], "others": others,
           "lastGood": {"addr": recent[1]["addr"], "sym": "HIRE", "at": t - 34 * MIN} if kind == "empty" else {"addr": good["addr"], "sym": "PEPE2", "at": t},
           "recent": recent, "record": {"calls": 37, "rug": 0.03, "win": 0.14, "eur": -1.2, "n60": 33, "ci": {"rug": [0.0, 0.1], "win": [0.05, 0.27]}},
           "hosts": {"dexscreener": "ok", "rugcheck": "ok", "pump.fun": "ok", "geckoterminal": "ok", "rpc": "ok"},
           "notes": ["RugCheck limited: 2 coins not fully checked"] if kind == "empty" else [], "lines": ["cycle 8: 8 seen, 1 without traps, 1 pushed (63 s)"]}
    if kind == "round":
        # one round of the hourly radar (launch_radar.py round): state done, the next round in 55 minutes, run.mode round, no run end; a call
        # whose 1 h price no round caught (miss60) and one still waiting for it
        doc.update(state="done", next=t + 55 * MIN, hourly=t, run={"id": "5678", "start": t - 2 * MIN, "end": None, "cycle": 1, "source": "hourly", "mode": "round"})
        doc["recent"] = recent[:4] + [{"addr": b58(rng), "sym": "GONE", "good": t - 100 * MIN, "later": {"5": None, "15": 0.8, "30": None, "60": None}, "out": None, "miss60": True}]
    elif kind == "off":
        doc.update(state="off", coins=[], others=[], next=None)
    elif kind == "hours":
        doc.update(state="hours", coins=[], others=[], next=t + 6 * H)
    elif kind in ("xss", "xss-empty"):
        doc["coins"] = [] if kind == "xss-empty" else [dict(good, sym=XSS_SYM, name=XSS_NAME, x=XSS_X, line=[["warn", XSS_NAME], ["ok", "RugCheck report"]],
                                                           d=dict(good["d"], **{"xKind": XSS_NAME}), dex=XSS_NAME, lp=XSS_NAME, found=[XSS_NAME])]
        doc["others"] = [dict(others[0], sym=XSS_OTHER, line=[["bad", XSS_NAME]])]
        doc["coins"].append({"addr": "0xNOT<b>SOLANA", "sym": "BADADDR", "v": "good"})       # dropped: not base58
        doc["recent"] = [dict(r, sym=XSS_SYM) for r in recent]
        doc["lastGood"] = {"addr": good["addr"], "sym": XSS_SYM, "at": t - 5 * MIN}
        doc["notes"], doc["lines"] = [XSS_NOTE], [XSS_NOTE]
        doc["hosts"] = {"rugcheck": "<img src=h>", "dexscreener": "limited"}
        doc["why"] = XSS_NOTE
    elif kind == "hosts":
        doc["hosts"] = {"dexscreener": "ok", "rugcheck": "limited", "pump.fun": "ok", "geckoterminal": "unused", "rpc": "unused", "jupiter": "ok",
                        "launchlab": "off", "pump.fun trades": "down"}
        doc["notes"] = ["RugCheck limited: 2 coins not fully checked"]
        doc["wm"] = {"t": t - 4 * H, "nCoins": 4120}
        doc["model"] = {"from": "learned", "n": 340, "need": 300, "auc": 0.712, "prior": 0.65, "at": t - H}
    return doc


def young_rows(now, rng):
    """recommend.json young rows with the fields memebot writes (f.ageH is the pool's age at the scan, pos_factors rounding), the scan at
    rec_t = now - 10 min; and mb/pairs.json entries as memebot gather writes them (pairCreatedAt, pf.createdAt). Rows: CLEANY (curve 4 min
    before the pool), GROKY (brand), INSTA (pool 20 s after the mint), NORC (no RugCheck report, not in pairs.json), the hostile row (a
    tag for a name and a RugCheck danger name, a javascript: X link), RUGGY (3 holders from rugged coins, safety flagged), SOCLESS (a RugCheck
    danger: a first chip too long to share a phone's row, short enough to stand alone), and
    NOPOOL (in pairs.json without a pool time: memebot measured its age from the mint, which must not read as a pool opened with it)."""
    wallets = [b58(rng, "") for _ in range(6)]
    rec_t = now - 10 * MIN

    def row(sym, name, age_min, **kw):
        f = dict({"m5": 4.0, "buys1": 300, "socN": 2, "ageH": round(age_min * MIN / H, 4)}, **kw.pop("f", {}))
        r = {"sym": sym, "name": name, "addr": b58(rng), "pair": b58(rng, ""), "dex": "pumpswap", "px": 0.00002, "mc": 60000.0, "liq": 18000.0, "vol": 90000.0,
             "score": 61.0, "rank": None, "why": "new launch", "safety": "RugCheck: no danger flags", "ok": True, "x": "https://x.com/" + re.sub(r"\W", "", sym.lower())[:12] or "x",
             "f": f, "src": ["pf:graduated"], "risk": {"danger": [], "warn": [], "holdersN": 210, "holders": wallets[:2]}, "launchpad": "pump.fun", "tier": None,
             "upP": 0.25, "zeroP": 0.3, "floor": "clears the relaxed floor", "ageMin": int(age_min), "gates": []}
        r.update(kw)
        return r
    rows = [row("CLEANY", "Clean Dog", 7), row("GROKY", "Grok Agent", 12), row("INSTA", "Insta Cat", 22), row("NORC", "No Report", 31, risk=None),
            row(XSS_SYM, XSS_NAME, 44, x=XSS_X, risk={"danger": [XSS_DANGER], "warn": [], "holdersN": 99, "holders": wallets[:1]}),
            row("RUGGY", "Rug Holders", 50, risk={"danger": [], "warn": [], "holdersN": 90, "holders": wallets[2:5]}, ok=False, safety="RugCheck warning: Low amount of LP Providers"),
            row("SOCLESS", "No Socials Two", 55, f={"socN": 0, "m5": 35.0}, risk={"danger": ["Mint Authority enabled"], "warn": [], "holdersN": 120, "holders": wallets[:2]}),
            row("NOPOOL", "No Pool Time", 3)]
    for i, r in enumerate(rows):
        r["bought"] = 3.0 if i < 5 else None
    pool = {r["addr"]: rec_t - r["f"]["ageH"] * H for r in rows}
    gap = {"CLEANY": 4 * MIN, "GROKY": 9 * MIN, "INSTA": 20_000, XSS_SYM: 3 * MIN, "RUGGY": 5 * MIN, "SOCLESS": 6 * MIN}
    pairs = [{"address": r["addr"], "pairAddress": r["pair"], "pairCreatedAt": int(pool[r["addr"]]), "pf": {"createdAt": int(pool[r["addr"]] - gap[r["sym"]])}}
             for r in rows if r["sym"] in gap]
    nopool = rows[-1]
    pairs.append({"address": nopool["addr"], "pairAddress": nopool["pair"], "pairCreatedAt": None, "pf": {"createdAt": int(rec_t - nopool["f"]["ageH"] * H)}})
    return rows, pairs, wallets[2:5]


def build_db(tmp, now, side=True, radar="good", tier="fallback", name="db"):
    """A recommend-mode db: one pick of the given tier, eight new launches, mb/pairs.json and mb/walletmem.json.gz (side), mb/radar_live.json."""
    import memebot as M
    rng = random.Random(11)
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "db", "memebot"), exist_ok=True)
    rows, pairs, ruggers = young_rows(now, rng)
    pick = {"sym": "BIGDOG", "name": "Big Dog", "addr": b58(rng), "pair": b58(rng, ""), "dex": "raydium", "px": 0.0012, "mc": 1.2e6, "liq": 180000.0, "vol": 900000.0,
            "score": 48.0, "rank": 1, "why": "momentum", "safety": "RugCheck: no danger flags", "ok": True, "x": "", "f": {"c6": 12.0}, "src": [], "risk": {"danger": []},
            "launchpad": "pump.fun", "tier": tier, "relaxed": ["6h change under the gate"] if tier in ("fallback", "risky") else [], "upP": 0.31, "zeroP": 0.12, "bought": "watch coin" if tier == "watch" else None}
    rec = {"t": now - 10 * MIN, "rule": M.RULE, "scanned": 1180, "passed": 37, "picks": [pick], "runnersUp": [], "young": rows, "youngOf": len(rows), "flagged": [], "reason": ""}
    json.dump(rec, open(os.path.join(d, "db", "memebot", "recommend.json"), "w"))
    json.dump({"lastRun": now - 9 * MIN, "runs": 12, "rule": M.RULE, "horizon": "24h"}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))
    if side:
        json.dump(pairs, open(os.path.join(d, "pairs.json"), "w"))
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
def young_pane(page):
    return page.split('id="pane-young"', 1)[1].split('id="pane-office"', 1)[0] if 'id="pane-young"' in page else ""


def young_tbody(pane):
    """The scored list's rows: the first ones in view and the others in the "N more new launches" fold under them (report.young_section);
    the record tables come after the cards."""
    return "".join(re.findall(r"<tbody>(.*?)</tbody>", pane.split("Every number behind each coin", 1)[0], re.S))


def young_trs(pane):
    return re.findall(r"<tr(?: class=\"trap\")?>.*?</tr>", young_tbody(pane), re.S)


def weights_shape_checks(check, P, W, what):
    """The "Why these checks?" fold against a weights file in WP1's shape: every trap and warning named, each with the words of its
    evidence row (rates with and without, the factor, its interval, n); the weight-0 list by its labels and reasons, never "?"."""
    html_ = P.why_fold(W)
    txt = visible_text(html_)
    ev = W.get("evidence") or {}
    named = [n for n in list(W.get("hard") or []) + list(W.get("soft") or [])]
    with_ev = [n for n in named if P._ev_row(ev.get(n))]
    smalls = re.findall(r"<small>(.*?)</small>", html_)
    zl = P._zero_list(W.get("zero"))
    zn = sum(len(v) for _, v in zl)
    ok = (txt.count(" pt") == len(named) and len(smalls) == len(with_ev) and all(re.match(r"(rugged|doubled)[^:]*: \d+% with it, \d+% without · [\d.]+x \(95%: [\d.]+-[\d.]+\) · \d+ coins$", x) for x in smalls)
          and "?:" not in txt and "label " not in txt and "Weight 0" in txt and zn == len(W.get("zero") or []) and "–" not in txt)
    check(ok, "S1 the why fold reads %s: %d checks, %d with their evidence row in words (%s), %d weight-0 signs by label and reason (%s)" % (
        what, len(named), len(with_ev), (smalls or ["none"])[0], zn, "; ".join("%s: %d" % (k, len(v)) for k, v in zl)[:120]))
    return txt


def py_checks(check, tmp, T, standin):
    import report as R
    import page_radar as P
    now = int(time.time() * 1000)
    d, rows = build_db(tmp, now)
    rec_t = now - 10 * MIN
    page = page_of(d, now)
    pane = young_pane(page)
    trs = young_trs(pane)
    W = T.load_weights()
    pairs = json.load(open(os.path.join(d, "pairs.json")))
    times = P.load_times(d, [y["addr"] for y in rows], T)
    with gzip.open(os.path.join(d, "walletmem.json.gz"), "rt") as f:
        wm = json.load(f)
    rts = [P.rating_of(T, W, y, times.get(y["addr"]), wm, rec_t) for y in rows]
    want = [(rt["v"], rt["line"]) for rt in rts]
    by = {y["sym"]: rt for y, rt in zip(rows, rts)}
    N = len(rows)
    # B1: the rule core gets the pool time (pairs.json pairCreatedAt) and the scan's time, so a clean row can be green and the instant pool fires
    S_clean = T.signals_scan(rows[0], times[rows[0]["addr"]][0], wm, now=rec_t, pool=times[rows[0]["addr"]][1])
    S_age = T.signals_scan(rows[0], times[rows[0]["addr"]][0], wm, now=rec_t)          # no pool given: now minus f.ageH, as memebot writes it
    check(by["CLEANY"]["v"] == "good" and by["INSTA"]["v"] == "trap" and "instant_pool" in by["INSTA"]["hard"] and abs((S_clean.get("mintToPoolS") or 0) - 240) < 2
          and abs((S_age.get("mintToPoolS") or 0) - 240) < 3 and by["CLEANY"]["pool"] and by["NORC"]["v"] != "good"
          and set(times) == {p["address"] for p in pairs} and times[rows[0]["addr"]][1] == pairs[0]["pairCreatedAt"],
          "B1 New launches with the %s: the rule core gets the pool time from mb/pairs.json (pairCreatedAt) and the scan's time, so CLEANY (curve 4 min "
          "before the pool, mint to pool %s s; from f.ageH alone %s s) is green and INSTA (pool 20 s after the mint) is a trap: instant_pool %s" % (
              "stand-in rule core" if standin else "traps.py", S_clean.get("mintToPoolS"), S_age.get("mintToPoolS"), by["INSTA"]["hard"]))
    check(by["NOPOOL"]["v"] != "trap" and "instant_pool" not in by["NOPOOL"]["hard"] and by["NOPOOL"]["S"].get("mintToPoolS") is None
          and any(t == "mint time unknown" for _, t in by["NOPOOL"]["line"]),
          "B1 a row in pairs.json without a pool time (memebot measured its age from the mint) is not read as a pool opened with the mint: "
          "mint to pool unknown, %s" % [t for _, t in by["NOPOOL"]["line"]][:3])
    # U4: every row of the New launches tab has a verdict chip and the trap line; the texts are traps.chips' own
    got_lines = [re.findall(r'<span class="tc (\w+)(?: x2)?"><b aria-hidden="true">.</b>(.*?)</span>', tr) for tr in trs]
    texts_ok = all([[lv, R.E(t)] for lv, t in w[1][:P.LINE_SHOWN]] == [list(x) for x in g] for w, g in zip(want, got_lines))
    tv = [re.search(r'<span class="chip tv(?: (\w+))?">(.*?)</span>', tr) for tr in trs]
    red = [bool(re.match(r'<tr class="trap">', tr)) for tr in trs]
    check(len(trs) == N == 8 and all(tv) and texts_ok and red == [w[0] == "trap" for w in want] and any(red) and any(w[0] == "good" for w in want)
          and "without traps</span>" in pane and "with traps or unchecked</span>" in pane,
          "U4 New launches: each of the %d rows carries its verdict chip and the one-row trap line with traps.chips' own texts (%s), trap rows red-tinted (%d), "
          "at least one row green, the heading counts both%s" % (len(trs), "stand-in rule core" if standin else "traps.py", sum(red), "" if texts_ok else " (texts differ: %s / %s)" % (want[:2], got_lines[:2])))
    good_rows = [w for w in want if w[0] == "good"]
    head = re.search(r'<p class="tsum"><span class="chip good">(\d+) without traps</span><span class="chip[^"]*">(\d+) with traps or unchecked</span>', pane)
    check(head and int(head.group(1)) == len(good_rows) >= 1 and int(head.group(2)) == N - len(good_rows),
          "U4 the New launches heading: %s without traps · %s with traps or unchecked" % (head.group(1) if head else "?", head.group(2) if head else "?"))
    # the old safety chip: a clean one goes beside the trap line, a flagged one stays (RUGGY); on the cards too (UX S5)
    ruggy = [tr for tr, y in zip(trs, rows) if y["sym"] == "RUGGY"]
    cards = pane.split("Every number behind each coin", 1)[1] if "Every number behind each coin" in pane else ""
    card_tops = re.findall(r'<article class="card rec"><div class="top">(.*?)</div></div>', cards, re.S)
    check(ruggy and "flagged: " in ruggy[0] and not any("safety: clean" in tr for tr in trs) and len(card_tops) == N and not any("safety: clean" in t for t in card_tops)
          and any("flagged" in t or "safety flags" in t for t in card_tops) and P.row_safety({"v": "good"}, '<span class="chip warn">flagged: x</span>') == '<span class="chip warn">flagged: x</span>'
          and P.card_safety({"tier": None}, '<span class="chip">safety: clean</span>') == '<span class="chip">safety: clean</span>',
          "U4 a flagged safety chip stays on its row (RUGGY: flagged), a clean one goes beside the trap line, on the rows and on the New launches cards "
          "(no 'safety: clean' above a trap); other cards keep theirs")
    # without pairs.json and the wallet memory: every row shows "?", none is green
    d2, _ = build_db(tmp, now, side=False, name="db-noside")
    p2 = young_pane(page_of(d2, now))
    tb2 = young_tbody(p2)
    trs2 = young_trs(p2)
    check(len(trs2) == N and not re.search(r'chip tv good', tb2) and all('<span class="tc unk' in tr for tr in trs2)
          and all(re.search(r'<span class="chip tv (warn|bad)">(\?|✕)', tr) for tr in trs2) and '<span class="chip">0 without traps' in p2,
          "U4 without mb/pairs.json and mb/walletmem.json.gz every row carries a ? check (mint time, wallet memory) and none is green; the 0 is not green")
    # an old wallet memory (built more than 3 hours before the scan) counts as missing
    d3, _ = build_db(tmp, now, name="db-oldwm")
    with gzip.open(os.path.join(d3, "walletmem.json.gz"), "wt", encoding="utf-8") as f:
        json.dump({"v": 1, "t": now - 4 * H, "nCoins": 10, "rug": []}, f)
    p3 = young_pane(page_of(d3, now))
    check("chip tv good" not in young_tbody(p3) and len(young_trs(p3)) == N, "U4 a wallet memory older than 3 hours gives no green row")
    # the card's detail view: CSS-radio sub-tabs, works without a script
    check(cards.count('<details class="tdet">') == N and cards.count('<div class="dtabs">') == N and "RED FLAGS".lower() in cards.lower() and 'type="radio" name="ty-' in cards
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
    radios = re.findall(r'<input type="radio" name="tab" id="(tab-\w+)"', page)
    check(m and emb.get("kind") == "radar" and len(m.group(1).encode()) <= P.DOC_MAX and "</" not in m.group(1) and cb and len(json.dumps(cb, separators=(",", ":")).encode()) <= P.DOC_MAX
          and len(cb["others"]) < 40 and P.clean_doc({"kind": "radar"}) is None and P.clean_doc({"kind": "live", "t": now}) is None
          and tabs == ["tab-pick", "tab-young", "tab-office"] and radios == tabs and not re.search(r"ghp_[A-Za-z0-9]{10}|github_pat_|x-access-token:|sb_secret_|Bearer [A-Za-z0-9]", page),
          "three tabs, Pick, New, Office, one radio each (%s); the embedded radar.json is whitelisted, %d bytes (at most %d; a big doc is trimmed to %d others) and cannot close "
          "its script block; no token in the page" % (radios, len(m.group(1).encode()) if m else -1, P.DOC_MAX, len(cb["others"]) if cb else -1))
    ids = re.findall(r'\bid="([^"]+)"', re.sub(r"(?s)<script\b.*?</script>", "", page))
    yp = young_pane(page)
    lab = re.search(r'<label for="tab-young" role="tab">(.*?)</label>', page)
    check('id="tab-radar"' not in page and 'id="pane-radar"' not in page and len(ids) == len(set(ids)) and yp.find("data-radar") >= 0
          and yp.find("data-radar") < yp.find("under an hour old") and yp.count("data-radar ") + yp.count("data-radar>") == 1 and "Launch radar" in yp
          and lab and "data-r-tabcnt" in lab.group(1) and re.search(r'<span class="cnt" data-y-tabcnt title="[^"]*">8</span>', lab.group(1))
          and "#tab-radar:checked" not in page and "pane-radar" not in P.CSS + P.JS,
          "New holds the radar: no Radar tab or pane left, no id twice (%d ids), the radar's block on top of the New pane above the full scan's new launches, "
          "the New label carries the radar's count (hidden at 0) and the scan's 8 (hidden while the radar's shows) %r" % (len(ids), re.sub(r"<[^>]+>", "|", lab.group(1)) if lab else None))
    rd = P.clean_doc(radar_doc(now, "round"))
    check(rd and rd["state"] == "done" and rd["run"]["mode"] == "round" and rd["hourly"] == now - 30_000 and [r["miss60"] for r in rd["recent"]] == [False] * 4 + [True]
          and P.clean_doc(dict(radar_doc(now, "round"), run={"mode": "<x>"}))["run"]["mode"] == "" and "done" in P.STATES
          and P.clean_doc(dict(radar_doc(now, "round"), recent=[dict(radar_doc(now, "round")["recent"][4], miss60="yes")]))["recent"][0]["miss60"] is False,
          "the hourly radar's doc keeps its state done, run.mode round, hourly and each call's miss60 (only a real true) through the whitelist")
    radar_of = lambda pg: pg.split('<section class="radar"', 1)[1].split('</section>', 1)[0]
    plain = page_of(d, now, repo=None)
    check(radar_of(plain) == radar_of(page) and "radar.yml" not in visible_text(page) and 'data-r-actions hidden' in radar_of(page),
          "the radar's HTML is the same with and without GITHUB_REPOSITORY (its script finds the repository in the office's live box for the GitHub poll and the Start and Stop links)")
    ns = re.search(r'<noscript><p class="note">(.*?)</p></noscript>', radar_of(page))
    ns0 = re.search(r'<noscript><p class="note">(.*?)</p></noscript>', P.pane({"now": now, "dir": None, "_radar": {"doc": None, "young": {}, "weights": None, "traps": False}}))
    check(ns and "needs JavaScript" in ns.group(1) and "1 coin without traps" in ns.group(1) and ns0 and "No radar check is in this build yet" in ns0.group(1),
          "the radar without a script says one line: %r" % (ns.group(1) if ns else None))
    hc = P.clean_doc(huge)
    check(hc is None or len(json.dumps(hc, separators=(",", ":"), ensure_ascii=False).encode()) <= P.DOC_MAX, "a doc too big even without its folds is left out whole, never cut mid-coin")
    hd = P.clean_doc(dict(radar_doc(now, "hosts")))
    check(hd and hd["hosts"].get("pump.fun trades") == "down" and hd["hosts"].get("geckoterminal") == "unused",
          "the whitelist keeps WP3's host labels with a space ('pump.fun trades') %s" % (hd or {}).get("hosts"))
    # U10 (page side): names like HTML tags, a RugCheck danger name and a javascript: X link are inert on the New launches tab and in the embedded doc
    d4, _ = build_db(tmp, now, radar="xss", name="db-xss")
    p4 = page_of(d4, now)
    m4 = re.search(r'<script type="application/json" id="radar-doc">(.*?)</script>', p4, re.S)
    y4 = young_pane(p4)
    check(not any(x in p4 for x in XSS_ALL) and "javascript:" not in p4 and R.E(XSS_NAME) in p4 and R.E(XSS_DANGER) in y4 and "0xNOT" not in p4
          and m4 and not re.search(r"[<>&]", m4.group(1)) and XSS_NOTE in json.loads(m4.group(1)).get("notes", []),
          "U10 page: every hostile name (coin, symbol, RugCheck danger in the trap line and the Trap check tab, notes) is escaped on the New launches tab, its cards "
          "and the embedded radar doc (which holds no raw <, > or &); a javascript: X link and a bad address are dropped")
    # S1: the why fold in the shape of WP1's radar_weights.json (and the real file when it is next to this module)
    why_txt = weights_shape_checks(check, P, T.load_weights(), "the stand-in's copy of WP1's weights shape" if standin else "traps.load_weights()")
    check("rugged within 1 h: 60% with it, 13% without · 4.6x (95%: 3.5-6.4) · 397 coins" in why_txt and "reversed: biggest wallet over 20%" in why_txt,
          "S1 the why fold picks the headline row (listed new launches, rug within 1 h, a verdict that holds) and names weight-0 signs by label: %r" % why_txt[:160])
    wf = os.path.join(HERE, "radar_weights.json")
    if os.path.exists(wf):
        weights_shape_checks(check, P, json.load(open(wf, encoding="utf-8")), "radar_weights.json")
    # nit 5: report.py goes without the radar parts only when page_radar.py is missing; an import error inside it is raised, never hidden
    import subprocess as sp
    rd_ = []
    for broken in (False, True):
        cd = os.path.join(tmp, "code-%s" % broken)
        os.makedirs(cd, exist_ok=True)
        for n in ("report.py", "memebot.py"):
            shutil.copy(os.path.join(HERE, n), cd)
        if broken:
            open(os.path.join(cd, "page_radar.py"), "w").write("import no_such_module_wp5b\n")
        r_ = sp.run([sys.executable, "-c", "import report; print(repr(report.PR.pane({})))"], cwd=cd, capture_output=True, text=True)
        rd_.append((r_.returncode, r_.stdout.strip(), "no_such_module_wp5b" in r_.stderr))
    check(rd_[0] == (0, "''", False) and rd_[1][0] != 0 and rd_[1][2],
          "nit 5 report.py builds without the radar parts only when page_radar.py is missing (a copy of the trader's files); an import error inside page_radar.py is raised %s" % rd_)
    # U7 for this package's words: no "safe", "guaranteed" or advice-style "buy" in the new UI text
    import app as A
    words = [P.BANNER, P.MEASURED_NOTE, visible_text(P.pane({"now": now, "dir": d})), P.INFO_TEXT, json.dumps(P.LABELS), json.dumps(P.UNKNOWN), json.dumps(P.SKEYS), json.dumps(P.OUTCOMES)]
    words += re.findall(r"'([^'\\]{12,})'", P.JS)
    words += re.findall(r"'([^'\\]*(?:radar|Radar|trap)[^'\\]*)'", A.PAGE_JS)
    bad = [w for w in words if BANNED.search(w)]
    check(not bad and "\u2014" not in P.JS + P.CSS + json.dumps(P.LABELS) + visible_text(page) and "a coin with no trap found" in A.PAGE_JS and "finds a coin with no trap," not in A.PAGE_JS,
          "U7 the radar's words carry no 'safe', 'guaranteed' or advice-style 'buy', and no em dash; the app's notification card says 'a coin with no trap found' (%d texts read)%s" % (
              len(words), (" " + str(bad[:3])) if bad else ""))
    return d, page


NODE_SIM = r"""
var MB=window.MemebotLive,R=window.MemebotRadar,A=window.MemebotApp,o={};
var N=1e12,M=60000,doc=function(t,x){return Object.assign({kind:'radar',t:t,next:t+150000,state:'running',coins:[]},x||{});};
o.state=[R.radarState(doc(N-30000),N,0),R.radarState(doc(N-8*M),N,0),R.radarState(doc(N-40*M),N,0),R.radarState(doc(N,{state:'off'}),N,0),
  R.radarState(doc(N-M,{state:'hours',next:N+3*3600000}),N,0),R.radarState(null,N,0),R.radarState({kind:'live',t:N},N,0),
  R.radarState(doc(N-2*3600000,{state:'hours',next:N-3600000}),N,0),
  // a phone clock 10 minutes fast: running once the doc was seen to move (got/moved), never from the phone's clock alone
  R.radarState(doc(N-30000),N+600000,N+600000-20000,true),R.radarState(doc(N-30000),N+600000,0)];   // ... before a doc moved, the phone's clock is the first guess
// the hourly radar's rounds (state done, or degraded with run.mode round): done until doc.next + 30 min (next unknown: an hour after the
// round), then late for an hour, then stopped; a loop's 6-minute rule does not apply to them
var rd=function(t,x){return doc(t,Object.assign({state:'done',next:t+55*M,run:{mode:'round'}},x||{}));};
o.round=[R.radarState(rd(N-20*M),N,0),R.radarState(rd(N-80*M),N,0),R.radarState(rd(N-84*M),N,0),R.radarState(rd(N-86*M),N,0),R.radarState(rd(N-144*M),N,0),
  R.radarState(rd(N-146*M),N,0),R.radarState(rd(N-80*M,{next:null}),N,0),R.radarState(rd(N-100*M,{next:null}),N,0),
  R.radarState(rd(N-10*M,{state:'degraded'}),N,0),R.radarState(doc(N-10*M,{state:'done',next:N+50*M}),N,0),R.radarState(rd(N-10*M,{state:'off'}),N,0)];
// the next round's words after a round: before doc.next, past it, without a next (the strip's next scan; one that should be over moves on by
// an hour; none on the page)
var hm=function(t){return new Date(t).toISOString().slice(11,16);};
o.nextw=[R.nextWords(rd(N-20*M,{next:N+40*M}),N,0,hm),R.nextWords(rd(N-70*M,{next:N-10*M}),N,N+50*M,hm),R.nextWords(rd(N-20*M,{next:null}),N,N+50*M,hm),
  R.nextWords(rd(N-20*M,{next:null}),N,N-20*M,hm),R.nextWords(rd(N-20*M,{next:null}),N,N-60*M,hm),R.nextWords(rd(N-20*M,{next:null}),N,0,hm),
  hm(N+40*M),hm(N-10*M),hm(N+50*M),hm(N-20*M),hm(N)];
o.live=[R.live('done',rd(N-14*M),N,0),R.live('done',rd(N-16*M),N,0),R.live('running',doc(N-30000),N,0),R.live('late',rd(N-90*M),N,0),R.live('done',null,N,0)];
// the next poll of a round: near doc.next (+ ROUND, the round's own minutes), at most IDLE apart on GitHub (a Start by hand), SB_DONE on the live store
o.rnext=[R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'radar',via:'github',got:N})-N,R.radarNext({doc:rd(N-55*M,{next:N+5*M}),now:N,last:N,tab:'radar',via:'github',got:N})-N,
  R.radarNext({doc:rd(N-70*M,{next:N-10*M}),now:N,last:N,tab:'radar',via:'github',got:N})-N,R.radarNext({doc:rd(N-58*M,{next:N-1*M}),now:N,last:N,tab:'radar',via:'supabase',got:N})-N,
  R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'app',via:'supabase',got:N})-N,R.radarNext({doc:rd(N-100*M,{next:N-40*M}),now:N,last:N,tab:'office',via:'github',got:N})-N];
// a round on the New tab with the live store: every SB_ROUND (a round by hand shows within a minute); a tap on Start (kick): every SB_FRESH on
// the live store, GH_MIN after the last GitHub poll, the budget still wins (12 left: 900 s), a failure's back-off too
o.kick=[R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'radar',via:'supabase',got:N})-N,R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'radar',via:'supabase',got:N,kick:true})-N,
  R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N-60000,tab:'radar',via:'github',got:N,kick:true})-N,R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'radar',via:'github',got:N,kick:true,rem:12,reset:N/1000+1800})-N,
  R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'radar',via:'supabase',got:N,kick:true,fails:1})-N,R.radarNext({doc:rd(N-10*M,{next:N+50*M}),now:N,last:N,tab:'office',via:'supabase',got:N})-N];
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
// one hour on the New tab with the hourly radar: a round 5 minutes ago, the next in 55 minutes (it lands 3 minutes after that)
o.simRound=(function(){var T=1e12,calls=0,rN=T,d=rd(T-5*M,{next:T+55*M});for(var now=T;now<T+3600000;now+=1000){if(now>=T+58*M&&d.t<T)d=rd(now,{next:now+60*M});
  if(now>=rN){calls++;rN=R.radarNext({doc:d,now:now,last:now,tab:'radar',via:'github',got:now,moved:false});}}return calls;})();
o.badge=[A.radarBadge({state:'running',doc:{coins:[{v:'good'},{v:'good'},{v:'watch'}]}}),A.radarBadge({state:'running',doc:{coins:[{v:'watch'}]}}),
  A.radarBadge({state:'late',doc:{coins:[{v:'good'}]}}),A.radarBadge({state:'stopped',doc:{coins:[{v:'good'}]}}),A.radarBadge(null),A.radarBadge({state:'running',doc:{coins:'x'}}),
  A.radarBadge({state:'done',good:2,doc:{coins:[{v:'good'},{v:'good'}]}}),A.radarBadge({state:'done',good:0,doc:{coins:[{v:'good'}]}}),A.radarBadge({state:'done',doc:{coins:[{v:'good'}]}})];
o.newBadge=[A.newBadge(2,7),A.newBadge(null,7),A.newBadge(null,null),A.newBadge(0,0)];
o.tabs=A.TABS;o.tab=[A.tab('#tab-radar'),A.tab('tab-radar'),A.tab('#radar'),A.tab('#tab-young'),A.tab('#new'),A.tab('#tab-x'),A.tab('#newer')];
o.radarLink=[A.radarLink('#tab-radar'),A.radarLink('#radar'),A.radarLink('#tab-young'),A.radarLink('#new')];
var c=R.clean({kind:'radar',t:N,coins:[{addr:'1111111111111111111111111111111111111111pump',sym:'<b>x</b>',x:'javascript:alert(1)',v:'good',line:[['bad','a'],['evil','b'],['ok',5]],d:{a:1,'b c':2,e:{f:1}}},
  {addr:'0x<b>',v:'good'}],others:[{addr:'nope'}],notes:['a\u2028b'],hosts:{'x<y':'ok','pump.fun trades':'down',rugcheck:'limited'}});
o.clean=[c.coins.length,c.coins[0].x===undefined,c.coins[0].line.length,Object.keys(c.coins[0].d).join(','),c.others.length,c.notes[0],Object.keys(c.hosts).join(','),R.clean({kind:'radar'}),R.clean(null)];
var cr=R.clean({kind:'radar',t:N,state:'done',hourly:N-5,run:{mode:'round',end:null},recent:[{addr:'1111111111111111111111111111111111111111pump',miss60:true},{addr:'1111111111111111111111111111111111111112pump',miss60:'yes'}]});
o.cleanRound=[cr.state,cr.run.mode,cr.hourly,cr.recent.map(function(r){return r.miss60;}),R.clean({kind:'radar',t:N,run:{mode:'x'}}).run.mode];
o.verdict=[R.verdict({v:'good',n:9})[1],R.verdict({v:'trap',hard:['a','b']})[1],R.verdict({v:'watch',unknown:['rc_report']})[1],R.verdict({v:'watch',soft:['a','b']})[1]];
var rec=function(n){return {calls:37,rug:0.03,win:0.14,eur:-1.2,n60:n,ci:{rug:[0,0.1],win:[0.05,0.27]}};};
o.rec=[R.recShort(rec(19)),R.recShort(rec(20)),R.recLine(rec(19)),R.recLine(rec(20))];
o.odds=[R.odds({upP:0.2,zeroP:0.3}),R.odds({odds:{up:0.22,zero:0.31,note:'x'}}),R.odds({odds:{up:'x'}}),R.odds(null)];
o.ago=[R.ago(30000),R.ago(34*60000),R.ago(3*3600000)];
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
    check(o["round"] == ["done", "done", "done", "late", "late", "stopped", "done", "late", "done", "done", "off"],
          "U3 the hourly radar's rounds: done from doc.next until 30 min past it (an hour after the round when next is unknown), late for an hour after that, then "
          "stopped; a failed round (degraded, run.mode round) is done too, never 'running' from a loop's 6-minute rule %s" % o["round"])
    nw = o.get("nextw") or []
    check(len(nw) == 11 and nw[:6] == ["next about " + nw[6], "next due since " + nw[7], "next after the %s scan" % nw[8], "next after the %s scan" % nw[9],
                                       "next after the %s scan" % nw[10], "next after the next full scan"],
          "U3 the pill's next round after a round: 'next about HH:MM' before doc.next, 'next due since HH:MM' after it; a round with next null (a round by hand) "
          "names the full scan that starts the next one (the strip's estimate, the one running now, an hour on once that scan should be over), "
          "else 'next after the next full scan' %s" % nw[:6])
    check(o["live"] == [True, False, True, False, False],
          "U3 a round's coins are current (cards in colour, the count) for 15 minutes after it, a loop's while it runs, never when late %s" % o["live"])
    rn = o["rnext"]
    check(rn == [600000, 480000, 600000, 60000, 300000, 600000] and o["simRound"] <= 9,
          "U3 the poll of a round: near doc.next (8 min away: at its round's end, 480 s), else every 10 min (a Start by hand shows), the live store every minute on "
          "New, every 5 min elsewhere or at the next round; an hour on the New tab makes %d GitHub calls (was every 2.5 min) %s" % (o["simRound"], rn))
    check(o.get("kick") == [60000, 20000, 90000, 900000, 150000, 300000],
          "U3 a round by hand: the live store every minute on New (5 min on Office); after a tap on Start every 20 s, GitHub 150 s after its last poll, the "
          "budget (12 left: 900 s) and a failure's back-off still win %s" % o.get("kick"))
    check(o["badge"] == [2, None, None, None, None, None, 2, None, None] and o["newBadge"] == [{"n": 2, "good": True}, {"n": 7, "good": False}, None, None]
          and o["tabs"] == ["pick", "young", "office", "account"] and o["tab"] == ["young", "young", "young", "young", "young", None, None]
          and o["radarLink"] == [True, True, False, False],
          "A3 MemebotApp: TABS %s (one New tab); the old Radar links #tab-radar, #radar and #tab-young, #new open New (a radar link at its top, no jump to the early list); "
          "the radar's count while its list is current (a round: the event's good), green before the early list's count on New's one badge %s %s" % (o["tabs"], o["badge"], o["newBadge"]))
    check(o["cleanRound"] == ["done", "round", 1e12 - 5, [True, False], ""],
          "U3 the script's whitelist keeps a round's state done, run.mode, hourly and miss60 (only a real true) %s" % o["cleanRound"])
    check(o["clean"] == [1, True, 1, "a,e", 0, "a b", "pump.fun trades,rugcheck", None, None] and o["verdict"] == ["✓ No trap found · 9 checks", "✕ 2 traps", "? not fully checked", "! 2 warnings"]
          and [g[0] for g in o["groups"]] == ["bad", "warn", "unk", "ok", "info"] and o["groups"][0][2] == ["brand/celebrity name", "pool opened with the mint"]
          and o["groups"][2][2] == ["mint time unknown"],
          "U3 the script's whitelist drops a bad address, a javascript: X link, unknown levels and keys (a host label with a space stays); the verdict chips and the Trap "
          "check groups (names past the line get their words) %s" % [o["clean"], o["groups"][:2]])
    rc = o["rec"]
    check(rc[0] == "37 calls · too few for a record yet" and rc[1] == "37 calls · 3% rugged · 14% doubled" and "too few calls for a record yet (19 of 20 with a 1 h price)" in rc[2]
          and rc[3] == "37 calls without traps · 1 h later: 3% rugged, 14% doubled (95%: 0%-10% / 5%-27%) · paper, 3 € each: −1.20\u00a0€",
          "U3 the record line (SPEC 3.4) says 'too few calls' under 20 calls with a 1 h price and gives the rates from 20 on; the Track record fold's title is the "
          "short form, the intervals and the paper euros sit inside %s" % rc)
    check(o["odds"] == [[0.2, 0.3], [0.22, 0.31], None, None] and o["ago"] == ["just now", "34 min ago", "3 h ago"],
          "U3 the trained odds are read from d.upP / d.zeroP and from d.odds {up, zero} (WP3's shapes); 'just now' under a minute %s" % [o["odds"], o["ago"]])


RADAR_JS = """() => { const b = document.querySelector('[data-radar]'), q = s => b.querySelector(s), vis = e => !!(e && e.getClientRects().length);
  // a trap line's first chip cut (to the fraction of a pixel: an ellipsis shows) although it would fit beside the "+N"; a chip longer
  // than the whole row is cut, as it must be
  const cut = l => { const c = l.firstElementChild, more = Array.from(l.children).filter(x => x.classList.contains('more') && x.getClientRects().length);
    if (!c) return false; const r = document.createRange(); r.selectNodeContents(c); const cs = getComputedStyle(c), pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    const need = r.getBoundingClientRect().width, box = c.getBoundingClientRect().width - pad;
    return need > box + 0.01 && need + pad + more.reduce((a, x) => a + x.getBoundingClientRect().width + 4, 0) <= l.clientWidth; };
  return { tab: document.getElementById('tab-young').checked, hash: location.hash, pill: q('[data-r-pill-t]').textContent, st: q('[data-r-pill]').getAttribute('data-st'),
    cards: b.querySelectorAll('[data-r-cards] > li').length, dim: b.querySelectorAll('[data-r-cards] > li.dim').length, listHidden: q('[data-r-cards]').hidden,
    lines: Array.from(b.querySelectorAll('[data-r-cards] .tline')).map(l => Array.from(l.children).map(c => [c.className, c.textContent])),
    chips: Array.from(b.querySelectorAll('[data-r-cards] .rchips .chip')).map(c => c.textContent),
    chipCls: Array.from(b.querySelectorAll('[data-r-cards] .rchips .chip.tv')).map(c => c.className), empty: vis(q('[data-r-empty]')) ? q('[data-r-empty]').innerText : '',
    ocnt: q('[data-r-ocnt]').textContent, others: vis(q('[data-r-others]')), tabcnt: (document.querySelector('[data-r-tabcnt]') || {}).hidden ? '' : (document.querySelector('[data-r-tabcnt]') || {}).textContent,
    ytab: document.querySelector('[data-y-tabcnt]') ? document.querySelector('[data-y-tabcnt]').hidden : null,
    orows: Array.from(b.querySelectorAll('[data-r-olist] > li')).map(li => [li.className, li.querySelector('.rs').textContent]),
    notes: Array.from(b.querySelectorAll('[data-r-notes] li')).map(l => l.textContent), recent: Array.from(b.querySelectorAll('[data-r-recent] .rrec tbody tr td:nth-child(2)')).map(t => t.textContent),
    oc: Array.from(b.querySelectorAll('[data-r-recent] .rrec tbody tr')).map(tr => [tr.children[1].textContent, tr.lastElementChild.firstChild.textContent, tr.lastElementChild.title]),
    stats: q('[data-r-stats]').innerText, rec: q('[data-r-recline]').textContent, recIn: (q('[data-r-recent] .rrline') || {}).textContent || '', model: q('[data-r-model]').textContent,
    links: Array.from(b.querySelectorAll('[data-r-cards] a')).map(a => [a.getAttribute('href'), a.rel, a.target]),
    act: Array.from(b.querySelectorAll('[data-r-actions] a')).map(a => [a.textContent, a.getAttribute('href'), vis(a) && a.getBoundingClientRect().height, a.className]),
    firstCut: Array.from(b.querySelectorAll('.tline')).filter(vis).filter(cut).map(l => l.firstElementChild.textContent),
    imgs: b.querySelectorAll('img, svg, iframe').length, hscroll: document.documentElement.scrollWidth - innerWidth, ev: window.__rev || null }; }"""
# the tap targets under 44 px tall in a pane as the phone shows it (links, folds, buttons, labels), and the full scan's rows in view on New
TAP_JS = r"""(sel) => { const p = document.querySelector(sel), r = e => e.getBoundingClientRect();
  // shown: laid out and not inside a closed fold (Chromium lays out a closed fold's content when asked, so its rects alone do not tell)
  const shown = e => { if (!e.getClientRects().length || getComputedStyle(e).visibility === 'hidden') return false;
    for (let q = e.parentElement; q; q = q.parentElement) if (q.tagName === 'DETAILS' && !q.open && !(e.tagName === 'SUMMARY' && e.parentElement === q)) return false; return true; };
  return { small: Array.from(p.querySelectorAll('a[href], summary, button, label[for]')).filter(e => shown(e) && r(e).height < 43.5)
             .map(e => (e.innerText || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 30) + ' ' + Math.round(r(e).width) + 'x' + Math.round(r(e).height)),
           rows: Array.from(p.querySelectorAll('.tbl tbody tr')).filter(t => !t.closest('[data-radar]') && shown(t)).length }; }"""
FIRST_CUT_JS = """(sel) => Array.from(document.querySelectorAll(sel + ' .tline')).filter(l => l.getClientRects().length).filter(l => {
  const c = l.firstElementChild, more = Array.from(l.children).filter(x => x.classList.contains('more') && x.getClientRects().length);
  if (!c) return false; const r = document.createRange(); r.selectNodeContents(c); const cs = getComputedStyle(c), pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
  const need = r.getBoundingClientRect().width, box = c.getBoundingClientRect().width - pad;
  return need > box + 0.01 && need + pad + more.reduce((a, x) => a + x.getBoundingClientRect().width + 4, 0) <= l.clientWidth; }).map(l => l.firstElementChild.textContent)"""
# the gap between a chip's icon and its words (px), for every visible chip of every trap line under `sel`
ICON_GAP_JS = """(sel) => Array.from(document.querySelectorAll(sel + ' .tline .tc:not(.more)')).filter(c => c.getClientRects().length && c.querySelector('b')).slice(0, 12).map(c => {
  const b = c.querySelector('b'), r = document.createRange(); r.selectNodeContents(c.lastChild); return Math.round((r.getBoundingClientRect().left - b.getBoundingClientRect().right) * 10) / 10; })"""


def browser(check, tmp, d, skips, shots=None):
    """The New tab (the radar on top, the full scan's new launches below) and the installed app in Chromium. GitHub's API, raw.githubusercontent and the live store are
    stubbed with the fixture docs (fresh times), every other request is refused."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the radar page's browser checks (no Playwright)")
        print("  SKIP the radar page's browser checks: Playwright is not installed")
        return
    import report as R
    import bot as B
    import page_radar as P
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    pages_url, sb_url = "https://some-owner.github.io/Meme-Bot/", "https://abcref.supabase.co"
    ms = lambda: int(time.time() * 1000)
    page_html = page_of(d, ms())
    nodoc = re.sub(r'<script type="application/json" id="radar-doc">.*?</script>', "", page_html, flags=re.S)
    # the website with the live store (data-sb-url / data-sb-key on <html>, as bot.py site writes them) and an embedded doc 40 minutes old
    old_doc = radar_doc(ms() - 40 * MIN, "good")
    html_sb_old = re.sub(r'(<script type="application/json" id="radar-doc">).*?(</script>)', lambda m: m.group(1) + P.embed_json(P.clean_doc(old_doc)) + m.group(2),
                         page_html.replace("<html", '<html data-sb-url="%s" data-sb-key="sb_publishable_OKkey_1234567890"' % sb_url, 1), count=1, flags=re.S)
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
    state = {"doc": lambda: radar_doc(ms(), "good"), "gh": [], "sb": [], "raw": [], "other": [], "rawdoc": None, "sbrow": None}
    dialogs, errs = [], []
    out = {}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def ctx_page(w=390, h=844, dark=False, hash_="#tab-radar", app=False, html_=None, init=()):
                ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark" if dark else "light", service_workers="block")
                ctx.add_init_script("window.addEventListener('memebot-radar', e => { window.__rev = [e.detail.state, e.detail.good, e.detail.via]; });")
                if app:
                    ctx.add_init_script("Object.defineProperty(Navigator.prototype,'standalone',{get:function(){return true;}});")
                for js in init:
                    ctx.add_init_script(js)
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
                    elif u.startswith("https://raw.githubusercontent.com/some-owner/Meme-Bot/radar-data/radar.json"):
                        state["raw"].append(u)
                        route.fulfill(status=200, body=json.dumps((state["rawdoc"] or state["doc"])()), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
                    elif u.startswith(sb_url + "/rest/v1/"):
                        if route.request.method == "OPTIONS":
                            route.fulfill(status=204, headers=cors)
                            return
                        state["sb"].append(u)
                        if state.get("hold") is not None and "id=eq.radar" in u:
                            state["hold"].append(route)
                            return
                        body = (state["sbrow"]() if state["sbrow"] else [{"doc": state["doc"](), "updated": "now"}]) if "id=eq.radar" in u else []
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
                    p_ = os.path.join(shots, name)
                    (pg.locator(el).first.screenshot(path=p_) if el else pg.screenshot(path=p_, full_page=full))
            running = "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running' && (window.__rev || [])[2] === '%s'"
            # 1. one good coin (light and dark, phone and desktop)
            for w, h, dark in ((390, 844, False), (390, 844, True), (1280, 900, False), (1280, 900, True)):
                ctx, pg = ctx_page(w, h, dark)
                wait(pg, running % "github")
                info = pg.evaluate(RADAR_JS)
                out.setdefault("good", info)
                out.setdefault("goodW", {})["%d %s" % (w, dark)] = (info["firstCut"], pg.evaluate(ICON_GAP_JS, "[data-radar]"))
                shot(pg, "1-radar-good-%s-%dx%d.png" % ("dark" if dark else "light", w, h))
                if w == 390 and not dark:
                    # the info popover stays on the screen
                    pg.click("details.rinfo > summary")
                    pg.wait_for_timeout(150)
                    out["pop"] = pg.evaluate("(() => { const r = document.querySelector('details.rinfo[open] > p').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), innerWidth]; })()")
                    shot(pg, "1c-radar-info-popover-light-390x844.png")
                    pg.click("details.rinfo > summary")
                    # 3. the detail view, Trap check tab
                    pg.click("[data-r-cards] > li summary")
                    pg.wait_for_timeout(200)
                    det = pg.evaluate("""() => { const li = document.querySelector('[data-r-cards] > li'), d = li.querySelector('details'), pane = Array.from(li.querySelectorAll('.dpane')).find(p => p.getClientRects().length);
                      return { open: d.open, groups: pane ? Array.from(pane.querySelectorAll('h5')).map(h => h.textContent) : [], tabs: Array.from(li.querySelectorAll('.dtabbar label')).map(l => l.textContent),
                        tabH: Math.min(...Array.from(li.querySelectorAll('.dtabbar label')).map(l => l.getBoundingClientRect().height)), hscroll: document.documentElement.scrollWidth - innerWidth }; }""")
                    out["detail"] = det
                    shot(pg, "3-radar-detail-trapcheck-light-390x844.png", el="[data-r-cards] > li")
                    pg.click("[data-r-cards] > li .dtabbar label:nth-child(1)")
                    pg.wait_for_timeout(150)
                    out["overview"] = pg.evaluate("Array.from(document.querySelectorAll('[data-r-cards] > li .dpane')).filter(p => p.getClientRects().length).map(p => p.innerText)[0] || ''")
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
                info = pg.evaluate(RADAR_JS)
                out.setdefault("empty", info)
                if w == 390:
                    out.setdefault("empty_h", [])
                    out["empty_h"].append(info["hscroll"])
                    out.setdefault("emptyGap", pg.evaluate(ICON_GAP_JS, "[data-r-olist]"))
                shot(pg, "2-radar-empty-fold-open-%s-%dx%d.png" % ("dark" if dark else "light", w, h), full=True)
                ctx.close()
            # 4. header states: late, off, hours (and stopped, none)
            out["states"] = {}
            for kind in ("late", "off", "hours", "stopped"):
                state["doc"] = (lambda k: lambda: radar_doc(ms(), k))(kind)
                ctx, pg = ctx_page(html_=nodoc)
                wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === '%s'" % kind)
                out["states"][kind] = pg.evaluate(RADAR_JS)
                if kind in ("late", "off", "hours"):
                    shot(pg, "4-radar-header-%s-light-390x844.png" % kind, el="[data-radar]")
                ctx.close()
            state["doc"] = lambda: {"message": "Not Found"}
            ctx, pg = ctx_page(html_=nodoc)
            pg.wait_for_timeout(1200)
            out["states"]["none"] = pg.evaluate(RADAR_JS)
            ctx.close()
            # the hourly radar: a round 5 minutes old (its coin current), 25 minutes old (done, its coin greyed), late and stopped from doc.next
            out["rounds"] = {}
            for name, age in (("fresh", 5 * MIN), ("old", 25 * MIN), ("late", 100 * MIN), ("stopped", 3 * H), ("nonext", 20 * MIN)):
                # nonext: a round by hand long after the scan's last one names no next round (radar-data on 14.10, 13:16 UTC)
                state["doc"] = (lambda a, k: lambda: dict(radar_doc(ms() - a, "round"), **({"next": None, "hourly": None} if k == "nonext" else {})))(age, name)
                ctx, pg = ctx_page(html_=nodoc)
                wait(pg, "() => (window.__rev || [])[2] === 'github'")
                pg.evaluate("document.querySelector('[data-r-rec]').open = true")
                pg.wait_for_timeout(150)
                out["rounds"][name] = pg.evaluate(RADAR_JS)
                out["rounds"][name]["errAttr"] = pg.evaluate("document.querySelector('[data-r-pill]').hasAttribute('data-err')")
                out["rounds"][name]["strip"] = pg.evaluate("+(document.querySelector('[data-sstrip]') || {getAttribute: () => '0'}).getAttribute('data-next') || 0")
                if name in ("fresh", "old"):
                    shot(pg, "4b-radar-round-%s-light-390x844.png" % name, el="[data-radar]")
                ctx.close()
            # the old links of the Radar and New tabs open New in a browser (the hash is dropped)
            state["doc"] = lambda: radar_doc(ms(), "good")
            out["links"] = {}
            for h_ in ("#radar", "#tab-young", "#new"):
                ctx, pg = ctx_page(hash_=h_)
                pg.wait_for_timeout(600)
                out["links"][h_] = pg.evaluate("[document.getElementById('tab-young').checked, location.hash, document.querySelectorAll('input[name=\"tab\"]:checked').length]")
                ctx.close()
            # WP3's routine host states ("unused", "off") make no note; a limited or down host does, unless the radar's own notes name it;
            # an old wallet memory gets the page's own note
            state["doc"] = lambda: radar_doc(ms(), "hosts")
            ctx, pg = ctx_page(html_=nodoc)
            wait(pg, running % "github")
            out["hosts"] = pg.evaluate(RADAR_JS)
            ctx.close()
            # the raw copy (GitHub's budget at RESERVE, kept by the office poll): an older copy never replaces the newer embedded doc, and the
            # pill says "slower copy, as of HH:MM"
            state["doc"] = lambda: radar_doc(ms(), "good")
            state["rawdoc"] = lambda: radar_doc(ms() - 25 * MIN, "empty")
            gh0 = len([u for u in state["gh"] if "radar.json" in u])
            # (its time is ahead: on New the live script polls too, and its stubbed 404 for live.json carries no rate-limit numbers to share)
            ctx, pg = ctx_page(init=("try{localStorage.setItem('memebot-live https://api.github.com/x',JSON.stringify({rem:5,reset:Math.floor(Date.now()/1000)+1800,at:Date.now()+600000}));}catch(e){}",))
            wait(pg, "() => / · slower copy, as of /.test(document.querySelector('[data-r-pill-t]').textContent)", 6000)
            out["raw"] = pg.evaluate(RADAR_JS)
            out["raw"]["calls"] = [len(state["raw"]), len([u for u in state["gh"] if "radar.json" in u]) - gh0]
            ctx.close()
            state["rawdoc"] = None
            # the website with the live store: the radar's row is missing, GitHub holds a fresh doc: GitHub is asked once
            state["sbrow"] = lambda: []
            gh0, sb0 = len([u for u in state["gh"] if "radar.json" in u]), len(state["sb"])
            ctx, pg = ctx_page(html_=html_sb_old)
            wait(pg, running % "github", 8000)
            out["sbfall"] = pg.evaluate(RADAR_JS)
            out["sbfall"]["calls"] = [len(state["sb"]) - sb0, len([u for u in state["gh"] if "radar.json" in u]) - gh0]
            ctx.close()
            # ... with no radar doc at all (the radar has not run) GitHub is not asked; a radar that is really stopped (the live store's row and
            # GitHub hold the same old doc) costs one GitHub call, not one per live-store poll (the cadences cut to about a second here)
            sb_stopped = radar_doc(ms() - 40 * MIN, "good")
            state["sbrow"], gh0, sb0 = (lambda: []), len([u for u in state["gh"] if "radar.json" in u]), len(state["sb"])
            ctx, pg = ctx_page(html_=nodoc.replace("<html", '<html data-sb-url="%s" data-sb-key="sb_publishable_OKkey_1234567890"' % sb_url, 1),
                               init=("window.MEMEBOT_RADAR_T={SB_STALE:700,SB_RETRY:2500,GH_MIN:2500,IDLE:2500,RESERVE:-1e9};",))
            pg.wait_for_timeout(2500)
            once = [len(state["sb"]) - sb0, len([u for u in state["gh"] if "radar.json" in u]) - gh0]
            state["sbrow"], state["doc"] = (lambda: [{"doc": sb_stopped, "updated": "then"}]), (lambda: sb_stopped)
            sb0 = len(state["sb"])
            wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'stopped'", 4000)
            pg.wait_for_timeout(7000)                  # GitHub once, then the live store again: long enough for a second GitHub call to show
            out["sbonce"] = once + [len(state["sb"]) - sb0, len([u for u in state["gh"] if "radar.json" in u]) - gh0, pg.evaluate("document.querySelector('[data-r-pill]').getAttribute('data-st')")]
            ctx.close()
            state["sbrow"], state["doc"] = None, (lambda: radar_doc(ms(), "good"))
            # a round by hand (14.10: "it does not even update the time"): a tap on Start says "Waiting for the new round" and asks the live store every
            # SB_FRESH until the round's doc comes, then its time shows and the pace is back; back on the page it asks at once (one poll for two
            # events); the page on its way out asks nothing, and a poll cut off by the reload is no failure (the cadences cut to about a second)
            html_sb = nodoc.replace("<html", '<html data-sb-url="%s" data-sb-key="sb_publishable_OKkey_1234567890"' % sb_url, 1)   # no embedded doc: the row's round shows
            r_old, r_new = radar_doc(ms() - 20 * MIN, "round"), radar_doc(ms() - 5000, "round")
            state["sbrow"] = lambda: [{"doc": r_old, "updated": "then"}]
            ctx, pg = ctx_page(html_=html_sb, hash_="#tab-young", init=("window.MEMEBOT_RADAR_T={SB_ROUND:600000,SB_DONE:600000,SB_FRESH:700,KICK:20000};",))
            k = {"done": wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'done'", 6000)}
            pill = lambda: [pg.evaluate("document.querySelector('[data-r-pill-t]').textContent"), pg.evaluate("document.querySelector('[data-r-pill]').hasAttribute('data-wait')")]

            sbr = lambda: len([u for u in state["sb"] if "id=eq.radar" in u])     # the radar's row only (report.py reads its status row too)

            def reads(n, ms_):                         # the live-store reads since sb0, waiting up to ms_ for n of them (a slow runner gets its time)
                for _ in range(ms_ // 100):
                    if sbr() - sb0 >= n:
                        break
                    pg.wait_for_timeout(100)
                return sbr() - sb0
            pg.wait_for_timeout(1200)
            sb0 = sbr(); pg.wait_for_timeout(2000); k["idle"] = sbr() - sb0
            pg.evaluate("(function(){var a=document.querySelector('[data-r-actions] a');a.addEventListener('click',function(e){e.preventDefault();});a.click();})()")
            k["wait"] = pill()
            sb0 = sbr(); k["fast"] = reads(3, 9000)          # 3 reads: without the tap the next one is 10 minutes away
            state["sbrow"] = lambda: [{"doc": r_new, "updated": "now"}]
            k["got"] = wait(pg, "() => !document.querySelector('[data-r-pill]').hasAttribute('data-wait')", 4000)
            k["after"] = pill()
            sb0 = sbr(); pg.wait_for_timeout(2500); k["calm"] = sbr() - sb0
            pg.wait_for_timeout(500)
            sb0 = sbr(); pg.evaluate("document.dispatchEvent(new Event('visibilitychange'));document.dispatchEvent(new Event('visibilitychange'))")
            reads(1, 4000); pg.wait_for_timeout(300); k["woke"] = sbr() - sb0
            # a poll in flight when the page starts to leave: held, then cut off; S keeps no failure and no new last poll
            pg.wait_for_timeout(800); state["hold"] = []
            sb0 = sbr(); pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            reads(1, 4000); k["held"] = len(state["hold"])
            pg.evaluate("window.MEMEBOT_RELOADING=Date.now()")
            for r_ in state.pop("hold"):
                r_.abort()
            pg.wait_for_timeout(400)
            k["kept"] = pg.evaluate("(function(){for(var i=0;i<localStorage.length;i++){var x=localStorage.key(i);if(x.indexOf('memebot-radar')===0){var s=JSON.parse(localStorage.getItem(x));return [s.fails,Date.now()-s.last>1000];}}return null;})()")
            sb0 = sbr(); pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(1500); k["gone"] = sbr() - sb0
            k["new_t"] = pg.evaluate("new Date(%d).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:document.querySelector('[data-radar]').getAttribute('data-tz')||'UTC'})" % r_new["t"])
            ctx.close()
            r_hours = radar_doc(ms() - 2 * MIN, "hours")
            state["sbrow"] = lambda: [{"doc": r_hours, "updated": "then"}]
            ctx, pg = ctx_page(html_=html_sb, hash_="#tab-young", init=("window.MEMEBOT_RADAR_T={SB_ROUND:600000,SB_DONE:600000,SB_FRESH:700,KICK:20000};",))
            wait(pg, "() => document.querySelector('[data-r-pill]').getAttribute('data-st') === 'hours'", 6000)
            pg.evaluate("(function(){var a=document.querySelector('[data-r-actions] a');a.addEventListener('click',function(e){e.preventDefault();});a.click();})()")
            pg.wait_for_timeout(300)
            k["hours"] = pill()
            out["kick"] = k
            ctx.close()
            state["sbrow"] = None
            # U10 in the browser: the xss doc on the Radar tab and in the detail view, then the empty one (last good coin, notes, the fold)
            state["doc"] = lambda: radar_doc(ms(), "xss")
            ctx, pg = ctx_page()
            wait(pg, "() => document.querySelectorAll('[data-r-cards] > li').length === 1 && document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running'")
            pg.click("[data-r-cards] > li summary")
            pg.click("[data-r-cards] > li .dtabbar label:nth-child(3)")
            pg.evaluate("document.querySelectorAll('[data-radar] details').forEach(d => d.open = true)")
            pg.wait_for_timeout(200)
            out["xss"] = pg.evaluate(RADAR_JS)
            out["xss_text"] = pg.evaluate("document.querySelector('[data-radar]').innerText")
            ctx.close()
            state["doc"] = lambda: radar_doc(ms(), "xss-empty")
            ctx, pg = ctx_page(html_=nodoc)
            wait(pg, "() => !document.querySelector('[data-r-empty]').hidden && document.querySelector('[data-r-pill]').getAttribute('data-st') === 'running'")
            pg.evaluate("document.querySelectorAll('[data-radar] details').forEach(d => d.open = true)")
            pg.wait_for_timeout(150)
            out["xss2"] = pg.evaluate(RADAR_JS)
            out["xss2_text"] = pg.evaluate("document.querySelector('[data-radar]').innerText")
            ctx.close()
            # 5. the New launches tab with trap lines and a red row; 11. the pick card with its banner; U8 every tab at both widths, light and dark
            state["doc"] = lambda: radar_doc(ms(), "good")
            out["h"] = {}
            for w, h, dark in ((390, 844, False), (390, 844, True), (1280, 900, False), (1280, 900, True)):
                gh0 = len([u for u in state["gh"] if "radar.json" in u])
                ctx, pg = ctx_page(w, h, dark, hash_="")
                if w == 390 and not dark:
                    pg.wait_for_timeout(2500)              # the Pick tab: no radar poll (SPEC 6.1: only on the Radar or Office tab, or in the app)
                    out["pickPoll"] = len([u for u in state["gh"] if "radar.json" in u]) - gh0
                for tab in ("tab-pick", "tab-young", "tab-office"):
                    pg.click('label[for="%s"]' % tab)
                    pg.wait_for_timeout(150)
                    if tab == "tab-pick" and w == 390 and not dark:
                        out.setdefault("tap", {})[tab] = pg.evaluate(TAP_JS, "#pane-pick")
                    if tab == "tab-young":
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = true)")
                        pg.wait_for_timeout(100)
                    out["h"]["%s %dx%d %s" % (tab, w, h, "dark" if dark else "light")] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                    if tab == "tab-young" and not dark:
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = false)")
                        out.setdefault("youngW", {})[w] = pg.evaluate(FIRST_CUT_JS, "#pane-young tbody")
                        out.setdefault("tblScroll", {})[w] = pg.evaluate("(() => { const t = document.querySelector('#pane-young .tbl'); return t.scrollWidth - t.clientWidth; })()")
                        if w == 390:
                            out.setdefault("tap", {})[tab] = pg.evaluate(TAP_JS, "#pane-young")
                    if tab == "tab-young" and w == 390 and not dark:
                        out["young"] = pg.evaluate("""() => { const p = document.getElementById('pane-young'), rows = Array.from(p.querySelectorAll('tbody tr')).filter(r => !r.closest('[data-radar]'));
                          return { rows: rows.length, red: rows.filter(r => r.classList.contains('trap')).length, tint: rows.filter(r => r.classList.contains('trap')).map(r => getComputedStyle(r.querySelector('td')).backgroundColor),
                            lines: rows.map(r => { const l = r.querySelector('.tline'); return l ? l.getBoundingClientRect().height : 0; }),
                            verdicts: rows.map(r => (r.querySelector('.chip.tv') || {}).textContent || ''), imgs: p.querySelectorAll('img').length }; }""")
                        out["youngGap"] = pg.evaluate(ICON_GAP_JS, "#pane-young tbody")
                        el_ = pg.locator("#pane-young .tbl.stack").first
                        el_.scroll_into_view_if_needed()
                        shot(pg, "5-new-launches-trap-lines-light-390x844.png")
                        pg.evaluate("""() => { const f = Array.from(document.querySelectorAll('#pane-young details')).find(d => /Every number behind/.test(d.querySelector('summary').textContent));
                          f.open = true; const c = f.querySelectorAll('.card.rec')[1]; c.querySelector('details.tdet').open = true; c.id = 'shot-card'; }""")
                        pg.wait_for_timeout(150)
                        out["ycard"] = pg.evaluate("""() => { const c = document.getElementById('shot-card'), pane = Array.from(c.querySelectorAll('.dpane')).find(p => p.getClientRects().length);
                          return { groups: pane ? Array.from(pane.querySelectorAll('h5')).map(h => h.textContent) : [], verdict: (c.querySelector('.ttrap .chip') || {}).textContent || '',
                            top: c.querySelector('.top .chips').innerText, sumH: c.querySelector('details.tdet > summary').getBoundingClientRect().height,
                            tabH: Math.min(...Array.from(c.querySelectorAll('.dtabbar label')).map(l => l.getBoundingClientRect().height)), hscroll: document.documentElement.scrollWidth - innerWidth }; }""")
                        shot(pg, "5b-new-launch-card-trapcheck-light-390x844.png", el="#shot-card")
                        pg.evaluate("document.querySelectorAll('#pane-young details').forEach(d => d.open = false)")
                    if tab == "tab-young" and w == 1280 and not dark:
                        pg.locator("#pane-young .tsum").first.scroll_into_view_if_needed()
                        shot(pg, "5-new-launches-trap-lines-light-1280x900.png")
                    if tab == "tab-pick" and not dark:
                        out.setdefault("banner", pg.evaluate("(() => { const b = document.querySelector('#pane-pick .nogood'); return b ? [b.className, b.innerText, getComputedStyle(b).backgroundColor] : null; })()"))
                        shot(pg, "11-pick-banner-light-%dx%d.png" % (w, h))
                ctx.close()
            # 10. the installed app: four tabs, the radar on New from the live store (no GitHub poll), New's green badge, the deep links; the badge
            # follows the radar's news (the live store's row turns to no good coin: the badge goes)
            state["doc"] = lambda: radar_doc(ms(), "good")
            state["gh"].clear()
            state["sb"].clear()
            out["app"] = {}
            for w, h, dark in ((390, 844, False), (390, 844, True), (320, 640, False)):
                ctx, pg = ctx_page(w, h, dark, hash_="#tab-radar", app=True, init=("window.MEMEBOT_RADAR_T={SB_APP:1500};",))
                ok = wait(pg, "() => document.documentElement.classList.contains('app') && ((document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt.good') || {}).textContent || '') === '1'", 10000)
                a = pg.evaluate("""() => ({ app: document.documentElement.classList.contains('app'), tabs: Array.from(document.querySelectorAll('.appbar button')).map(b => b.getAttribute('data-tab')),
                  names: Array.from(document.querySelectorAll('.appbar button > span:not([class])')).map(s => s.textContent), apptab: document.documentElement.getAttribute('data-apptab'),
                  radar: document.getElementById('tab-young').checked, aria: document.querySelector('.appbar [data-tab="young"]').getAttribute('aria-label'), y: Math.round(scrollY),
                  badgeBg: (() => { const c = document.querySelector('.appbar [data-tab="young"] .ab-cnt'); return c ? getComputedStyle(c).backgroundColor : ''; })(),
                  hscroll: document.documentElement.scrollWidth - innerWidth, cards: document.querySelectorAll('[data-r-cards] > li').length,
                  btnW: Math.min(...Array.from(document.querySelectorAll('.appbar button')).map(b => b.getBoundingClientRect().width)),
                  over: Array.from(document.querySelectorAll('.appbar button > span:not([class])')).filter(s => s.scrollWidth > s.clientWidth + 1).length })""")
                a["badge_ok"] = ok
                out["app"]["%dx%d %s" % (w, h, "dark" if dark else "light")] = a
                if w == 390:
                    shot(pg, "10-app-shell-new-radar-%s-390x844.png" % ("dark" if dark else "light"))
                if w == 390 and not dark:
                    for t in ("young", "office", "account", "pick"):
                        pg.click('.appbar button[data-tab="%s"]' % t)
                        pg.wait_for_timeout(150)
                        out["h"]["app %s 390x844" % t] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                    # a tap on the radar notification while the app is open: the service worker tells it which tab to show
                    pg.evaluate("navigator.serviceWorker && navigator.serviceWorker.dispatchEvent(new MessageEvent('message', {data: {type: 'memebot-open', url: location.href.split('#')[0] + '#tab-radar'}}))")
                    pg.wait_for_timeout(200)
                    out["deep"] = pg.evaluate("[document.documentElement.getAttribute('data-apptab'), document.getElementById('tab-young').checked]")
                    state["doc"] = lambda: radar_doc(ms(), "empty")
                    gone = wait(pg, "() => !document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt') || getComputedStyle(document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt')).display === 'none' || !document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt').textContent", 8000)
                    out["badgeGone"] = [gone, pg.evaluate("document.querySelector('.appbar [data-tab=\"young\"]').getAttribute('aria-label')")]
                    state["doc"] = lambda: radar_doc(ms(), "good")
                ctx.close()
            out["calls"] = {"gh": len(state["gh"]), "sb": len([u for u in state["sb"] if "id=eq.radar" in u]), "other": state["other"][:3]}
            br.close()
    except Exception as e:
        check(False, "the radar page's browser checks could not run (Playwright is installed; Chromium needs a short TMPDIR path): %s" % str(e)[:300])
        return
    g, e_ = out["good"], out["empty"]
    check(g["tab"] and g["hash"] == "" and g["st"] == "running" and g["pill"].startswith("Radar running · checked ") and " · next " in g["pill"] and "this run until" not in g["pill"]
          and g["cards"] == 1 and g["dim"] == 0 and g["chips"][:1] == ["✓ No trap found · 9 checks"] and g["tabcnt"] == "1" and g["ocnt"] == "7" and g["others"]
          and [c[1] for c in g["lines"][0]] == ["!no socials", "✓curve 4 min before pool", "✓no rugger wallets", "+3", "+4"]
          and g["ev"] == ["running", 1, "github"] and "8" in g["stats"] and g["rec"] == "37 calls · 3% rugged · 14% doubled" and "(95%: 0%-10% / 5%-27%) · paper, 3 € each" in g["recIn"]
          and "radar data 212 of 300 needed" in g["model"]
          and [a[:2] for a in g["act"]] == [["Start ↗", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"], ["Stop ↗", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"]]
          and all(a[2] >= 44 for a in g["act"]),
          "U3 browser: #tab-radar (the old Radar tab's link) opens New with the radar's Start and Stop links to radar.yml (44 px); the GitHub poll brings the doc; only the good coin gets a card (the doc's watch "
          "coin does not), with its chip and its line (3 chips and +3), the tab count 1, the fold count 7, the model status; the Track record fold's title is short (%r), the "
          "intervals and the paper euros inside; the memebot-radar event says running, 1 good %s" % (g["rec"], {k: g[k] for k in ("pill", "chips", "ev")}))
    rs_ = out.get("rounds") or {}
    check([a[3] for a in g["act"]] == ["rbtn quiet", "rbtn quiet"] and [a[3] for a in out["states"]["off"]["act"]][:1] == ["rbtn"] and [a[3] for a in out["states"]["stopped"]["act"]][:1] == ["rbtn"]
          and [a[3] for a in out["states"]["late"]["act"]][:1] == ["rbtn"] and [a[3] for a in (rs_.get("old") or {}).get("act", [])][:2] == ["rbtn", "rbtn quiet"],
          "UX N3 Start is the main button unless a radar loop is running (a tap then only queues a run); between the hourly rounds it is one more round: running %s, off %s, "
          "done %s" % ([a[3] for a in g["act"]], [a[3] for a in out["states"]["off"]["act"]], [a[3] for a in (rs_.get("old") or {}).get("act", [])]))
    ts = out.get("tblScroll") or {}
    check(len(ts) == 2 and all(v <= 0 for v in ts.values()),
          "U8 the New launches table keeps every column in view at 390 and 1280 (a long trap line never widens the coin column: no sideways scroll inside the table) %s" % ts)
    pop = out.get("pop") or [-1, 9999, 0]
    check(pop[0] >= 0 and pop[1] <= pop[2], "UX S1 the ⓘ popover (Stop = Disable workflow) stays on a 390 px screen: left %d, right %d of %d" % tuple(pop))
    tp = out.get("tap") or {}
    check(set(tp) == {"tab-pick", "tab-young"} and not any(v["small"] for v in tp.values()) and tp["tab-young"]["rows"] == 1,
          "UX the Pick and New tabs at 390 px have no tap target under 44 px (the card's folds, the coin links, the chart links, the folds under the list) and New "
          "shows the full scan's best new launch in view, the others one tap below (%s)" % {k: v for k, v in tp.items()})
    gw = out.get("goodW", {})
    gaps = [x for v in gw.values() for x in v[1]] + out.get("emptyGap", []) + out.get("youngGap", [])
    yw = out.get("youngW", {})
    check(not any(v[0] for v in gw.values()) and not e_["firstCut"] and not any(yw.values()) and len(yw) == 2 and gaps and min(gaps) >= 2,
          "UX S3 the first chip of every trap line (the worst finding) is never cut when it fits beside the +N: radar cards at 390 and 1280, the fold rows, the New launches "
          "rows at 390 and 1280 (a chip longer than the row is shown alone on a phone) %s; "
          "UX N1 a gap between each chip's icon and its words (%s px at least)" % ({k: v[0] for k, v in gw.items()} if any(v[0] for v in gw.values()) else yw, min(gaps) if gaps else None))
    check(set(u for u, _, _ in g["links"]) >= {"https://x.com/pepetwo"} and all(u.startswith("https://") and rel == "noopener noreferrer" and tg == "_blank" for u, rel, tg in g["links"])
          and not any("jup.ag" in u or "swap" in u for u, _, _ in g["links"]),
          "U3 browser: the card's links are DexScreener, pump.fun and X only, in a new tab, no swap link %s" % [u[:40] for u, _, _ in g["links"]])
    orows = dict((sym.split(" ", 1)[1], (cls, sym[0])) for cls, sym in e_["orows"])
    check(e_["cards"] == 0 and e_["listHidden"] and "No clean coin right now" in e_["empty"] and "7 seen under 10 min · all with traps or not fully checked" in e_["empty"] and "2½" not in e_["empty"]
          and "last coin without traps: HIRE, 34 min ago" in e_["empty"] and e_["ocnt"] == "7" and e_["tabcnt"] == "" and all(x <= 0 for x in out["empty_h"])
          and orows.get("GROKAI") == ("rrow bad", "✕") and orows.get("NORC") == ("rrow warn", "?") and orows.get("TWOWARN") == ("rrow warn", "!") and orows.get("PUMPY") == ("rrow warn", "!")
          and e_["recent"] == ["PEPE2", "CALM", "HIRE", "SEALS"],
          "U3 browser: no good coin shows 'No clean coin right now' (the empty card list hidden), the seen line, the last good coin (HIRE, 34 min ago) and 'Seen but not clean (7)': "
          "trap rows red with ✕, watch rows amber with ? (not checked) or ! (warnings); no tab count; the Track record lists the calls of the last 3 h only %s %s" % (orows, e_["recent"]))
    check(g.get("ytab") is True and e_.get("ytab") is False,
          "U3 browser: the website's New label carries one number: the radar's green 1 hides the full scan's count, with no coin without traps the scan's count is back "
          "(%s / %s)" % (g.get("ytab"), e_.get("ytab")))
    st = out["states"]
    check(st["late"]["st"] == "late" and st["late"]["dim"] == 1 and any(c.startswith("as of ") for c in st["late"]["chips"]) and st["late"]["pill"].startswith("Radar late · last check")
          and st["late"]["chipCls"] == ["chip tv"] and st["late"]["tabcnt"] == "" and (st["late"]["ev"] or [0, 1])[:2] == ["late", 0]
          and st["stopped"]["st"] == "stopped" and st["stopped"]["dim"] == 1 and st["off"]["st"] == "off" and st["off"]["pill"] == "Radar off · switched off on GitHub"
          and st["hours"]["st"] == "hours" and "next start" in st["hours"]["pill"] and st["none"]["st"] == "none" and st["none"]["pill"] == "Radar not started yet"
          and "Radar not started yet" in st["none"]["empty"],
          "U3 browser: a late or stopped doc greys its coins (the 'No trap found' chip grey too, %s) with 'as of HH:MM', no count and 0 good in the event; the header says late, "
          "stopped, off, hours (with the next start) and not started yet %s" % (st["late"]["chipCls"], {k: v["pill"] for k, v in st.items()}))
    hn = out["hosts"]["notes"]
    check(hn[:1] == ["RugCheck limited: 2 coins not fully checked"] and any(x.startswith("wallet check unavailable") for x in hn) and "pump.fun trades: down" in hn and len(hn) == 3
          and not any("unused" in x or "off" in x.split(":")[-1] for x in hn),
          "S2 host notes: WP3's routine states (unused, off) make none; a down host gets a plain one, a limited one the radar already named gets none; an old wallet memory "
          "gets the page's note %s" % hn)
    check(out["hosts"].get("model") == "Weights: learned on 340 calls · ranking quality 0.71 (study weights 0.65, coin toss 0.50)",
          "UX N10 learned weights in plain words, no 'AUC': %r" % out["hosts"].get("model"))
    rw = out["raw"]
    check(rw["st"] == "running" and rw["cards"] == 1 and " · slower copy, as of " in rw["pill"] and rw["calls"][0] >= 1 and rw["calls"][1] == 0,
          "6.1 with GitHub's budget at RESERVE the radar reads raw.githubusercontent (%d calls, %d API calls), its pill says 'slower copy, as of HH:MM', and that copy, 25 min older, "
          "never replaces the newer embedded doc (still running, 1 card): %r" % (rw["calls"][0], rw["calls"][1], rw["pill"]))
    sf = out["sbfall"]
    check(sf["st"] == "running" and sf["cards"] == 1 and sf["calls"][0] >= 1 and 1 <= sf["calls"][1] <= 2 and sf["ev"] and sf["ev"][2] == "github",
          "nit 3 the website with the live store: the radar's row is missing and the page's copy is 40 min old, so GitHub is asked once and its fresh doc shows "
          "(live store %d, GitHub %d calls, %s)" % (sf["calls"][0], sf["calls"][1], sf["pill"]))
    so = out.get("sbonce") or [0, -1, 0, -1, ""]
    check(so[0] >= 2 and so[1] == 0 and so[2] >= 3 and so[3] == 1 and so[4] == "stopped",
          "nit 3 the live store answers without the radar's row and the page has no radar doc: GitHub is not asked (%d live-store reads, %d GitHub); a radar that "
          "is really stopped in both places costs one GitHub call (%d live-store reads, %d GitHub in all)" % tuple(so[:4]))
    kk = out.get("kick") or {}
    check(kk.get("done") and kk.get("idle") == 0 and (kk.get("wait") or [""])[0].startswith("Waiting for the new round · last ") and (kk.get("wait") or [0, 0])[1] is True
          and kk.get("fast", 0) >= 3 and kk.get("got") and (kk.get("after") or [""])[0].startswith("Last round %s · " % kk.get("new_t")) and (kk.get("after") or [0, 1])[1] is False
          and kk.get("calm") == 0,
          "14.10 a round by hand: a tap on Start says 'Waiting for the new round' (pulsing dot) and asks the live store every SB_FRESH (%s reads, %s while idle in 2 s), "
          "the round's time shows as soon as its doc comes, then the pace is back (%s reads in 2.5 s) %s" % (kk.get("fast"), kk.get("idle"), kk.get("calm"), [kk.get("wait"), kk.get("after")]))
    check((kk.get("hours") or [""])[0].startswith("Radar sleeping") and (kk.get("hours") or [0, 1])[1] is False,
          "14.10 a tap on Start while the radar sleeps outside its hours keeps 'Radar sleeping' (no round can come) %s" % kk.get("hours"))
    check(kk.get("woke") == 1 and kk.get("held") == 1 and kk.get("kept") == [0, True] and kk.get("gone") == 0,
          "14.10 back on the page the radar asks at once (%s read for two events); a poll cut off by the page's reload is no failure and no new last poll %s; "
          "a page on its way out asks nothing (%s reads)" % (kk.get("woke"), kk.get("kept"), kk.get("gone")))
    check(out.get("pickPoll") == 0, "6.1 the website polls the radar only on the Radar or Office tab (or in the app): %s GitHub calls in 2.5 s on the Pick tab" % out.get("pickPoll"))
    det = out.get("detail") or {}
    check(det.get("open") and det.get("tabs") == ["Overview", "Trap check", "Numbers", "Later"] and det.get("groups") == ["Warnings 1", "Passed 3", "Measured, not weighted yet 2"]
          and "…" in out.get("later", "") and det.get("hscroll", 1) <= 0 and det.get("tabH", 0) >= 44,
          "browser: a tap opens the detail view on its Trap check tab (Overview, Trap check, Numbers, Later; warnings, passed, measured), sub-tabs %s px tall %s" % (det.get("tabH"), det))
    check("Trained odds (info only): 22% profit, 31% zero. Not used" in out.get("overview", ""),
          "nit 2 the Overview shows the trained odds from d.odds (WP3's committed shape), as info only: %r" % out.get("overview", "")[-140:])
    why = out.get("why") or ""
    check("pool opened with the mint" in why and "rugged within 1 h: 60% with it, 13% without" in why and "Weight 0" in why and "biggest wallet over 20%" in why and "?:" not in why
          and "Not in v1: coins still on the bonding curve" in why and "radar data 212 of 300 needed" in why,
          "S1 the 'Why these checks?' fold shows each check with its study evidence in words, the weight-0 list by label, the model status and what v1 leaves out (%r)" % why[:120])
    ea = out.get("early") or {}
    inst = lambda k: [c for c in ea.get(k, []) if "pool opened with the mint" in c[1]]
    check(len(ea) == 3 and len(inst("INSTANT")) == 1 and "bad" in inst("INSTANT")[0][0] and not inst("CURVED") and not inst("NOMINT")
          and not any("No trap found" in c[1] for v in ea.values() for c in v),
          "the early box marks a pool opened within 60 s of the mint with the red chip, and nothing else of the verdict (no green, nothing for an unknown mint) %s" % {k: [c[1] for c in v][:3] for k, v in ea.items()})
    yc = out.get("ycard") or {}
    check(yc.get("verdict") == "✕ trap" and yc.get("groups", [""])[0].startswith("Red flags") and yc.get("hscroll", 1) <= 0 and "safety: clean" not in yc.get("top", "x")
          and yc.get("sumH", 0) >= 44 and yc.get("tabH", 0) >= 44,
          "U4 browser: a New launches card opens its detail view on the Trap check tab without a script's help (red flags first), no 'safety: clean' above its trap (UX S5), "
          "summary and sub-tabs at least 44 px (UX S4: %s / %s) %s" % (yc.get("sumH"), yc.get("tabH"), {k: yc.get(k) for k in ("verdict", "top")}))
    x, x2 = out["xss"], out["xss2"]
    check(x["imgs"] == 0 and x2["imgs"] == 0 and not dialogs and XSS_NAME in out["xss_text"] and XSS_SYM in out["xss_text"] and XSS_NOTE in out["xss_text"] and XSS_OTHER in out["xss_text"]
          and XSS_SYM in out["xss2_text"] and XSS_NOTE in out["xss2_text"] and not any("javascript" in u for u, _, _ in x["links"]) and x["cards"] == 1
          and x["recent"] and all(r == XSS_SYM for r in x["recent"]) and not errs,
          "U10 browser: tags for the coin's name and symbol, the fold's symbols, the recent calls, the last good coin, the notes and a host state render as text on the Radar tab "
          "and in its detail view (no img, svg or iframe, no dialog, no script error), no javascript: link, the bad address dropped")
    y = out.get("young") or {}
    check(y.get("rows") == 8 and y.get("red", 0) >= 1 and y.get("imgs") == 0 and all(0 < hh <= 30 for hh in y.get("lines", [])) and all(y.get("verdicts", [])),
          "U4 browser: the New launches rows each show the verdict chip and a one-row trap line (%s px tall), %d rows red-tinted (%s)" % (y.get("lines"), y.get("red", 0), (y.get("tint") or [""])[0]))
    bn = out.get("banner")
    check(bn and "nogood warn" in bn[0] and bn[1].endswith(P_BANNER()), "U5 browser: the fallback pick shows the amber banner %s" % (bn[:2] if bn else bn))
    hs = out["h"]
    check(all(v <= 0 for v in hs.values()) and all(a["hscroll"] <= 0 for a in out["app"].values()) and len(hs) >= 16,
          "U8 no sideways scroll on Pick, New (with the radar) and Office at 390 x 844 and 1280 x 900, light and dark, and in the installed app on all four tabs (%d views%s)" % (
              len(hs) + len(out["app"]), "" if all(v <= 0 for v in hs.values()) else " " + str({k: v for k, v in hs.items() if v > 0})))
    ap = out["app"]["390x844 light"]
    check(ap["app"] and ap["tabs"] == ["pick", "young", "office", "account"] and ap["names"] == ["Pick", "New", "Office", "Account"] and ap["radar"]
          and ap["apptab"] == "young" and ap["badge_ok"] and ap["aria"] == "New coins, 1 without traps now" and ap["cards"] == 1 and out.get("deep") == ["young", True] and ap["y"] == 0
          and out["calls"]["gh"] == 0 and out["calls"]["sb"] >= 1 and all(a["over"] == 0 and a["btnW"] >= 60 for a in out["app"].values()) and not errs,
          "A3 installed app: four tabs (Pick, New, Office, Account), #tab-radar and the radar notification's message open New at its top (the radar), New's badge says 1 in "
          "green (%s, read out in words), the live store's row radar feeds it and GitHub is not polled; no label cut at 320 px %s" % (
              ap.get("badgeBg"), {k: ap[k] for k in ("names", "aria")} if not errs else [errs[:2], ap, out.get("deep"), out["calls"]]))
    bg = out.get("badgeGone") or [False, "?"]
    check(bg[0] and bg[1] == "New coins",
          "S4 A3 the app's New badge follows the radar's news: the live store's row turns to no good coin and the badge goes (%s)" % bg)
    rf, ro, rl, rt, rn_ = (rs_.get(k) or {} for k in ("fresh", "old", "late", "stopped", "nonext"))
    hm = re.compile(r"^Last round \d\d:\d\d · next about \d\d:\d\d$")
    oc = dict((x[0], x[1:]) for x in rf.get("oc", []))
    check(rf.get("st") == "done" and hm.match(rf.get("pill", "")) and rf.get("cards") == 1 and rf.get("dim") == 0 and rf.get("tabcnt") == "1" and (rf.get("ev") or [0])[:2] == ["done", 1]
          and ro.get("st") == "done" and hm.match(ro.get("pill", "")) and ro.get("cards") == 1 and ro.get("dim") == 1 and ro.get("tabcnt") == "" and (ro.get("ev") or [0])[:2] == ["done", 0]
          and any(c.startswith("as of ") for c in ro.get("chips", [])) and not rf.get("errAttr")
          and rl.get("st") == "late" and rl.get("pill", "").startswith("Radar late · last round ") and rt.get("st") == "stopped" and rt.get("pill", "").startswith("Radar stopped · last round "),
          "U3 browser, the hourly radar: a round says %r; its coin is current (in colour, the count 1, the event done with 1 good) for 15 minutes, then greyed 'as of' with no "
          "count; 30 minutes past doc.next it is late, an hour later stopped (%r, %r)" % (rf.get("pill"), rl.get("pill"), rt.get("pill")))
    check(rn_.get("st") == "done" and re.match(r"^Last round \d\d:\d\d · next after the (\d\d:\d\d|next full) scan$", rn_.get("pill", "")) and rn_.get("strip") is not None
          and ((rn_["strip"] > 0) == (" next full " not in rn_.get("pill", ""))),
          "U3 browser: a round with next null still names when the next one comes: after the full scan the Pick strip expects (%r, strip %s)" % (rn_.get("pill"), rn_.get("strip")))
    check(oc.get("GONE") == ["–", "no 1 h price"] and oc.get("CALM") == ["…", "pending"] and oc.get("HIRE") == ["⇈", "2x"],
          "U3 browser: a call whose 1 h price no round caught (miss60) shows '–' (no 1 h price), not '… pending' forever; one still waiting shows '…' %s" % oc)
    lk = out.get("links") or {}
    check(all(v == [True, "", 1] for v in lk.values()) and len(lk) == 3,
          "the old links #radar, #tab-young and #new open New in a browser, once (the hash is dropped), one tab radio checked %s" % lk)


def P_BANNER():
    import page_radar as P
    return P.BANNER


def checks(check, env=None):
    env = env or {}
    skips = env.get("skips") if isinstance(env.get("skips"), list) else []
    print("== the launch radar on the New tab, the trap-check line and the no-good-coin marks (WP5b, WP10)")
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
