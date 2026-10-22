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
    (one round of the hourly radar: state done, the next round in 55 minutes, a call with miss60). Every kind has the momentum line and the
    patterns (record.mom / all / pat; empty: too few) and each coin's ws; the win order is learned only in round."""
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
    for c, ws in zip([good] + others, (2, 1, -1, 0)):       # the learned win order (hindsight): the ▲ shows only once it is learned (round)
        c["ws"] = ws
    # the momentum line and the patterns (launch_radar summary / pat_of): a long label to cut, two hints that could be chance, two rugged coins
    pat = {"at": t - H, "since": t - 72 * H, "hrs": 38, "w": 25, "l": 192, "need": 15,
           "rows": [["creator_sold", 41, 66, 2, 14, True, "warn", -1], ["x", 65, 127, 17, 23, False, "ok", 1], ["fund_cluster", 30, 120, 2, 20, False, "info", -1]],
           "why": [["SEALS", t - 130 * MIN, 3, [["creator_sold", 0, 3], ["rc_danger", 1, 3]]], ["RUGGY", t - 90 * MIN, 2, [["fund_cluster", 0, 2]]]]}
    recent = [{"addr": good["addr"], "sym": "PEPE2", "good": t - 4 * MIN, "later": {"5": None, "15": None, "30": None, "60": None}, "out": None},
              {"addr": b58(rng), "sym": "HIRE", "good": t - 95 * MIN, "later": {"5": 1.12, "15": 0.94, "30": 1.4, "60": 2.3}, "out": {"rug1h": False, "win1h": True, "x60": 2.3}},
              {"addr": b58(rng), "sym": "SEALS", "good": t - 130 * MIN, "later": {"5": 0.8, "15": 0.3, "30": 0.05, "60": 0.01}, "out": {"rug1h": True, "win1h": False, "x60": 0.01}},
              {"addr": b58(rng), "sym": "CALM", "good": t - 40 * MIN, "later": {"5": 1.05, "15": 1.1, "30": 0.97, "60": None}, "out": None},
              {"addr": b58(rng), "sym": "OLDONE", "good": t - 5 * H, "later": {"5": 1.0, "15": 1.0, "30": 1.0, "60": 1.0}, "out": {"rug1h": False, "win1h": False, "x60": 1.0}}]
    doc = {"v": 1, "kind": "radar", "t": t, "next": t + 150_000, "run": {"id": "1234", "start": t - 20 * MIN, "end": t + 35 * MIN, "cycle": 8, "source": "chain"},
           "state": "running", "why": "", "secs": 63.2, "model": {"from": "prior", "n": 212, "need": 300, "auc": None, "at": t - 2 * H,
                                                                    "win": {"from": "none", "n": 212, "auc": None, "why": "walk-forward needs 30 doubled coins in the last 2 days (have 4)"}},
           "counts": {"seen": 7 if kind == "empty" else 8, "good": 0 if kind == "empty" else 1, "pushed": 0 if kind == "empty" else 1, "seenAgeMed": 3.1},
           "wm": {"t": t - 50 * MIN, "nCoins": 4120}, "coins": [] if kind == "empty" else [good, dict(others[2], v="watch", d={})], "others": others,
           "lastGood": {"addr": recent[1]["addr"], "sym": "HIRE", "at": t - 34 * MIN} if kind == "empty" else {"addr": good["addr"], "sym": "PEPE2", "at": t},
           "recent": recent, "record": {"calls": 37, "rug": 0.03, "win": 0.14, "eur": -1.2, "n60": 33, "ci": {"rug": [0.0, 0.1], "win": [0.05, 0.27]}, "known": {"n": 33, "rug": 1, "win": 5},
                                        "mom": {"calls": 9, "n60": 9, "rug": 0.889, "win": 0.0} if kind == "empty" else {"calls": 47, "n60": 41, "rug": 0.91, "win": 0.04},
                                        "all": {"n60": 412, "rug": 0.72, "win": 0.03}, "pat": dict(pat, w=4, rows=[], why=[]) if kind == "empty" else pat},
           "hosts": {"dexscreener": "ok", "rugcheck": "ok", "pump.fun": "ok", "geckoterminal": "ok", "rpc": "ok"},
           "notes": ["RugCheck limited: 2 coins not fully checked"] if kind == "empty" else [], "lines": ["cycle 8: 8 seen, 1 without traps, 1 pushed (63 s)"]}
    if kind == "round":
        # one round of the hourly radar (launch_radar.py round): state done, the next round in 55 minutes, run.mode round, no run end; a call
        # whose 1 h price no round caught (miss60) and one still waiting for it
        doc.update(state="done", next=t + 55 * MIN, hourly=t, run={"id": "5678", "start": t - 2 * MIN, "end": None, "cycle": 1, "source": "hourly", "mode": "round"})
        doc["model"]["win"] = {"from": "learned", "n": 260, "auc": 0.61, "why": ""}
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
        pat["why"][0][0] = XSS_SYM
        doc["hosts"] = {"rugcheck": "<img src=h>", "dexscreener": "limited"}
        doc["why"] = XSS_NOTE
    elif kind == "hosts":
        doc["hosts"] = {"dexscreener": "ok", "rugcheck": "limited", "pump.fun": "ok", "geckoterminal": "unused", "rpc": "unused", "jupiter": "ok",
                        "launchlab": "off", "pump.fun trades": "down", "pumpportal": "limited"}
        doc["notes"] = ["RugCheck limited: 2 coins not fully checked"]
        doc["wm"] = {"t": t - 4 * H, "nCoins": 4120}
        doc["model"] = {"from": "learned", "n": 340, "need": 300, "auc": 0.712, "prior": 0.65, "at": t - H}
    return doc


def pat_doc(t):
    """A radar.json with every drop of the new whitelists (record.mom / all / pat, model.win, ws): a ws of 99, '2' or 1.5; a pat row with a bad
    name, a zero wn, more rugged with it than rugged, 7 fields (no direction), a 4th good row; a bad level (read as info), sure 'true' (read as
    not sure) and a direction '1' or true (read as 0); a why with 4 signals (cut to 3), one with bad triples (a name with a space, a count as
    text, no known count, more with it than known), one that is not a list, a 4th coin."""
    a = "1111111111111111111111111111111111111111pump"
    row = lambda n, **kw: [kw.get(str(i), v) for i, v in enumerate([n, 41, 66, 2, 14, True, "warn", -1])]
    return {"kind": "radar", "t": t, "coins": [{"addr": a, "ws": 99}, {"addr": a, "ws": 2}, {"addr": a, "ws": "2"}, {"addr": a, "ws": 1.5}], "others": [{"addr": a, "ws": -9}],
            "model": {"win": {"from": "x", "n": 5, "auc": "0.6", "why": "w" * 200}},
            "record": {"calls": 3, "mom": {"calls": 2, "n60": "9", "rug": 0.5, "win": None}, "all": [1, 2],
                       "pat": {"at": t, "since": -1, "hrs": 3, "w": "4", "l": 20, "need": 15,
                               "rows": [row("creator_sold"), row("a b"), row("x", **{"4": 0}), row("dev_dead")[:7], row("mc_500k", **{"6": "evil", "7": "1"}),
                                        row("liq_15pct", **{"5": "true", "7": True}), row("tweet"), row("x", **{"1": 70})],
                               "why": [["PEPE", t, 3, [["a", 1, 3], ["b", 2, 3], ["c", 3, 3], ["d", 4, 4]]], ["Q", t, 3, [["a b", 1, 3], ["e", "2", 3], ["f", 1], ["g", 3, 2], ["h", 0, 2]]],
                                       ["R", t, 3, "x"], ["S", t, 3, []], ["T", t, 3, []]]}}}


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
    # U5: the banner over the pick (page_radar.pick_banner stays; the pick no longer calls it: one heading by the tier says it, ui bug 19)
    ban, heads, inpage = {}, {}, []
    for tier in ("strong", "weak", "fallback", "risky", "watch"):
        D = {"rec": {"picks": [{"sym": "P", "addr": "A" * 44, "tier": tier, "relaxed": []}], "scanned": 10, "passed": 1}, "now": now, "open": [], "state": {}}
        h = R.rec_section(D, embed=False)
        m = re.search(r'<p class="nogood (\w+)" role="note">.*?<span>(.*?)</span></p>', P.pick_banner(D["rec"]["picks"]))
        ban[tier] = (m.group(1), m.group(2)) if m else None
        heads[tier] = (re.search(r"<h2>(.*?)</h2>", h) or re.match("", "")).group(1) if re.search(r"<h2>(.*?)</h2>", h) else None
        inpage.append("nogood" in h or P.BANNER in h)
    check(ban["strong"] is None and ban["weak"] is None and ban["fallback"] == ("warn", P.BANNER) and ban["risky"] == ("bad", P.BANNER) and ban["watch"] == ("bad", P.BANNER)
          and "weak · best available" in R.tier_chip({"tier": "weak"}) and not any(inpage)
          and heads == {"strong": "The pick for the next %s" % R.horizon_text(), "weak": "The pick for the next %s" % R.horizon_text(),
                        "fallback": "Risky pick for the next %s" % R.horizon_text(), "risky": "Risky pick for the next %s" % R.horizon_text(), "watch": "No pick this scan"},
          "U5 the pick banner '%s' (page_radar.pick_banner) is amber for fallback and red for risky and watch, none for strong or weak; the pick shows it "
          "no more: one heading by the tier instead %s %s" % (P.BANNER, ban, heads))
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
          and tabs == ["tab-home", "tab-pick", "tab-young", "tab-office", "tab-account"] and radios == tabs and not re.search(r"ghp_[A-Za-z0-9]{10}|github_pat_|x-access-token:|sb_secret_|Bearer [A-Za-z0-9]", page),
          "five tabs, Start, Pick, Radar, Gehirn, Archiv, one radio each (%s); the embedded radar.json is whitelisted, %d bytes (at most %d; a big doc is trimmed to %d others) and cannot close "
          "its script block; no token in the page" % (radios, len(m.group(1).encode()) if m else -1, P.DOC_MAX, len(cb["others"]) if cb else -1))
    ids = re.findall(r'\bid="([^"]+)"', re.sub(r"(?s)<script\b.*?</script>", "", page))
    yp = young_pane(page)
    lab = re.search(r'<label for="tab-young" role="tab">(.*?)</label>', page)
    check('id="tab-radar"' not in page and 'id="pane-radar"' not in page and len(ids) == len(set(ids)) and yp.find("data-radar") >= 0
          and yp.find("data-radar") < yp.find("under an hour old") and yp.count("data-radar ") + yp.count("data-radar>") == 1 and "Launch radar" in yp
          and lab and "data-r-tabcnt" in lab.group(1) and "data-y-tabcnt" not in page + P.JS and re.sub(r"<[^>]+>", "", lab.group(1)) == "Radar"
          and "#tab-radar:checked" not in page and "pane-radar" not in P.CSS + P.JS and "New launches (until " in yp,
          "the Radar tab (id tab-young) holds the radar: no tab-radar radio or pane, no id twice (%d ids), the radar's block on top of its pane, the full scan's "
          "new launches under it before the switch ('New launches (until ...)'); its label says Radar and carries one number, the radar's count (hidden at "
          "0), no full-scan count %r" % (len(ids), re.sub(r"<[^>]+>", "|", lab.group(1)) if lab else None))
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
    pc, gd = P.clean_doc(pat_doc(now)), P.clean_doc(radar_doc(now, "good"))
    check(pc and [c["ws"] for c in pc["coins"]] == [None, 2, None, None] and pc["others"][0]["ws"] == -9 and pc["model"]["win"] == {"from": "none", "n": 5, "auc": None, "why": "w" * 120}
          and pc["record"]["mom"] == {"calls": 2, "n60": None, "rug": 0.5, "win": None} and pc["record"]["all"] is None
          and pc["record"]["pat"] == {"at": now, "since": None, "hrs": 3, "w": None, "l": 20, "need": 15, "rows": [["creator_sold", 41, 66, 2, 14, True, "warn", -1],
                                      ["mc_500k", 41, 66, 2, 14, True, "info", 0], ["liq_15pct", 41, 66, 2, 14, False, "warn", 0]],
                                      "why": [["PEPE", now, 3, [["a", 1, 3], ["b", 2, 3], ["c", 3, 3]]], ["Q", now, 3, [["h", 0, 2]]], ["S", now, 3, []]]}
          and gd["record"]["pat"]["rows"] == radar_doc(now, "good")["record"]["pat"]["rows"] and gd["record"]["all"] == {"n60": 412, "rug": 0.72, "win": 0.03} and gd["coins"][0]["ws"] == 2
          and P.clean_doc(dict(radar_doc(now, "good"), record=None))["record"] is None and P.clean_doc({"kind": "radar", "t": now})["model"]["win"] is None
          and all(P.LABELS.get(n) for n in ("x", "creator_5pct", "mc_500k", "liq_15pct")),
          "the whitelist keeps record.mom / all / pat, model.win and ws (an integer -9 to 9) and drops the rest: a pat row with a bad name, a zero group, more "
          "with it than in the group or no direction, a 4th row; a bad level reads info, sure only a real true, a direction only -1, 0 or 1; a why's 4th "
          "signal, bad triples (more with it than known) and a 4th coin; the 4 new labels exist")
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
    check(not bad and "\u2014" not in P.JS + P.CSS + json.dumps(P.LABELS) + visible_text(page) and "when a bot makes a paper purchase" in A.PAGE_JS and "finds a coin with no trap," not in A.PAGE_JS,
          "U7 the radar's words carry no 'safe', 'guaranteed' or advice-style 'buy', and no em dash; the app's notification card says it notifies paper purchases only (Oct 22) (%d texts read)%s" % (
              len(words), (" " + str(bad[:3])) if bad else ""))
    check("around the clock" in P.INFO_TEXT and not re.search(r"7 to 24|07:00|24:00|first full scan after", P.INFO_TEXT),
          "U7 the Start/Stop info says the radar runs around the clock (no 7 to 24 h, no start with the first scan after its hours)")
    return d, page


NODE_SIM = r"""
var MB=window.MemebotLive,R=window.MemebotRadar,A=window.MemebotApp,o={};
var N=1e12,M=60000,doc=function(t,x){return Object.assign({kind:'radar',t:t,next:t+150000,state:'running',coins:[]},x||{});};
o.state=[R.radarState(doc(N-30000),N,0),R.radarState(doc(N-8*M),N,0),R.radarState(doc(N-40*M),N,0),R.radarState(doc(N,{state:'off'}),N,0),
  R.radarState(doc(N-M,{state:'hours',next:N+3*3600000}),N,0),R.radarState(null,N,0),R.radarState({kind:'live',t:N},N,0),
  R.radarState(doc(N-2*3600000,{state:'hours',next:N-5400000}),N,0),
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
// the radar's loop every 5 minutes (doc.next 5 minutes after doc.t): running within 2 of its cycles and a minute (11 min), late to 15, then
// stopped; the old 2.5-minute loop keeps its 6 minutes; a next far off counts as 10 minutes at most
o.loop5=[R.radarState(doc(N-8*M,{next:N-3*M}),N,0),R.radarState(doc(N-12*M,{next:N-7*M}),N,0),R.radarState(doc(N-16*M,{next:N-11*M}),N,0),
  R.radarState(doc(N-8*M),N,0),R.radarState(doc(N-8*M,{next:N+30*M}),N,0),R.cycle(doc(N,{next:N+5*M})),R.cycle(doc(N,{next:null}))];
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
// the next poll: the doc's next cycle + 15 s, at least 150 s after the last; 20 s / 60 s on the live store; the Office tab the same while a loop runs
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
// the desk on the Office tab with a loop every 2 minutes: round k's doc (t = its grid point, next 2 minutes later) lands 30 to 100 s after its time
// (the cycle's deadline); the page polls at radarNext's pace on that tab and takes each doc as took() does. Half an hour: the seconds it read
// anything but running, and its polls
function officeSim(via){var T=1e12,G=120000,docs=[],held=null,got=0,moved=false,nx=T,bad=0,polls=0,reset=(T+3600000)/1000;
  for(var k=0;k<20;k++)docs.push({at:T-G+k*G+30000+(k*37000)%70001,d:{kind:'radar',t:T-G+k*G,next:T+k*G,state:'running',run:{mode:'loop'},coins:[]}});
  for(var now=T;now<T+1800000;now+=1000){
    if(now>=nx){var d=null;docs.forEach(function(x){if(x.at<=now)d=x.d;});polls++;
      if(!(held&&held.t===d.t)){moved=!!(held&&got>0&&d.t>held.t);got=now;held=d;}
      nx=R.radarNext({doc:held,now:now,last:now,tab:'office',via:via,rem:via==='github'?60-polls:null,reset:reset,fails:0,got:got,moved:moved});}
    if(R.radarState(held,now,got,moved)!=='running')bad++;}
  return [bad,polls];}
o.officeSim=[officeSim('supabase'),officeSim('github')];
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
var rec=function(n,k){return {calls:37,rug:0.03,win:0.14,eur:-1.2,n60:n,ci:{rug:[0,0.1],win:[0.05,0.27]},known:k===undefined?{n:n,rug:1,win:5}:k};};
o.rec=[R.recShort(rec(19)),R.recShort(rec(20)),R.recLine(rec(19)),R.recLine(rec(20)),R.recLine(rec(30,{n:30,rug:1,win:31})),R.recLine(rec(30,null)),R.recShort(rec(30,{n:30.5,rug:1,win:2}))];
o.odds=[R.odds({upP:0.2,zeroP:0.3}),R.odds({odds:{up:0.22,zero:0.31,note:'x'}}),R.odds({odds:{up:'x'}}),R.odds(null)];
o.ago=[R.ago(30000),R.ago(34*60000),R.ago(3*3600000)];
o.groups=R.groups({line:[['bad','brand/celebrity name'],['warn','no socials'],['ok','RugCheck report']],hard:['brand_name','instant_pool'],soft:['no_socials'],unknown:['mint_time'],info:['dev_dead']});
// the momentum line, the patterns and the ▲ (hindsight, paper only): the words, the too-few forms; the fixtures through R.clean (Python's clean_doc must agree)
var mo=function(c,n){return {calls:c,n60:n,rug:0.91,win:0.04};},al={n60:412,rug:0.72,win:0.03};
o.mom=[R.momLine(mo(47,41),al),R.momLine(mo(9,9),al),R.momLine(mo(1,null),null),R.momLine(null,al),R.momLine(mo(47,41),null),R.momLine(mo(0,0),al)];
// the last row: hours that swing (selftest_learn's case): pooled 48% of rugged vs 29% of doubled, hour by hour more often in doubled coins
o.pat=[R.patHead({w:25,l:192,need:15}),R.patHead({w:4,l:120,need:15}),R.patHead(null),R.patRow(['creator_sold',41,66,2,14,true,'warn',-1]),R.patRow(['x',65,127,17,23,false,'ok',1]),
  R.patRow(['some_new',1,2,0,3,false,'info',0]),R.whyLine(['PEPE',N,3,[['creator_sold',0,3],['rc_danger',1,3]]],hm),R.whyLine(['PEPE',null,null,[['x',2,null]]],hm),R.whyLine(['PEPE',N,3,[]],hm),hm(N),
  R.patRow(['x',190,400,100,350,true,'ok',1])];
o.ws=[R.wsOn({ws:1},{win:{from:'learned'}}),R.wsOn({ws:0},{win:{from:'learned'}}),R.wsOn({ws:2},{win:{from:'none'}}),R.wsOn({ws:2},{win:null}),R.wsOn({ws:null},{win:{from:'learned'}}),R.wsOn({ws:3},null)];
o.parity=(global.FX||[]).map(function(d){return R.clean(d);});
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
    t_fx = int(time.time() * 1000)
    fx = [radar_doc(t_fx, k) for k in ("good", "round", "empty", "hosts")] + [pat_doc(t_fx)]
    with open(os.path.join(jd, "radar.js"), "w", encoding="utf-8") as f:
        f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;},getElementById:function(){return null;}};global.navigator={};\n"
                + "global.FX=%s;\n" % json.dumps(fx) + R.OFFICE_LIVE_JS + P.JS + A.PAGE_JS + NODE_SIM)
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
    check(nx[0] == 150000 and nx[1] == 150000 and nx[2] == 415000 and nx[3] == 20000 and nx[4] == 60000 and nx[5] == 20000 and nx[6] == 600000 and nx[7] == 900000,
          "U3 the radar poll: GitHub at the doc's next cycle + 15 s, at least 150 s apart (600 s while off), stretched by the budget (12 left: 900 s); "
          "the live store every 20 s fresh, 60 s stale; the Office tab (the desk) the same while a loop runs %s" % nx)
    osim = o.get("officeSim") or [[-1, 0], [-1, 0]]
    check(osim[0][0] == 0 and osim[1][0] == 0 and 80 <= osim[0][1] <= 95 and 10 <= osim[1][1] <= 13,
          "U3 the desk on the Office tab with a loop every 2 minutes (each doc landing 30 to 100 s after its time): running every second of a "
          "simulated half hour on the live store (%d polls) and on GitHub (%d polls, 24 an hour at most), never late between two polls %s" % (osim[0][1], osim[1][1], osim))
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
    check(o.get("loop5") == ["running", "late", "stopped", "late", "running", 300000, 150000],
          "U3 the radar's loop every 5 minutes is running for 2 of its own cycles and a minute (8 min old: running, 12: late, 16: stopped); the "
          "2.5-minute loop keeps its 6 minutes; its cycle is the doc's next minus its time, 2.5 to 10 minutes %s" % o.get("loop5"))
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
          and o["tabs"] == ["home", "pick", "young", "office", "account"] and o["tab"] == ["young", "young", "young", "young", "young", None, None]
          and o["radarLink"] == [True, True, False, False],
          "A3 MemebotApp: TABS %s (the website's order: Start, Pick, Radar, Gehirn, Archiv); #tab-radar, #radar, #tab-young and #new open Radar (a radar link at its top, no "
          "jump to the early list); the radar's count while its list is current (a round: the event's good), green before the early list's count on Radar's one badge %s %s" % (o["tabs"], o["badge"], o["newBadge"]))
    check(o["cleanRound"] == ["done", "round", 1e12 - 5, [True, False], ""],
          "U3 the script's whitelist keeps a round's state done, run.mode, hourly and miss60 (only a real true) %s" % o["cleanRound"])
    check(o["clean"] == [1, True, 1, "a,e", 0, "a b", "pump.fun trades,rugcheck", None, None] and o["verdict"] == ["✓ No trap found · 9 checks", "✕ 2 traps", "? not fully checked", "! 2 warnings"]
          and [g[0] for g in o["groups"]] == ["bad", "warn", "unk", "ok", "info"] and o["groups"][0][2] == ["brand/celebrity name", "pool opened with the mint"]
          and o["groups"][2][2] == ["mint time unknown"],
          "U3 the script's whitelist drops a bad address, a javascript: X link, unknown levels and keys (a host label with a space stays); the verdict chips and the Trap "
          "check groups (names past the line get their words) %s" % [o["clean"], o["groups"][:2]])
    rc = o["rec"]
    check(rc[0] == "37 coins · too few for a record yet" and rc[1] == "20 with a 1 h result · 5 doubled · 1 crashed"
          and rc[2] == "37 coins without traps · too few with a 1 h result for a record yet (19 of 20)"
          and rc[3] == "20 coins without traps with a 1 h result: 5 doubled, 1 crashed to near zero (95% range: 5% to 27% doubled, 0% to 10% crashed)"
          and rc[4] == rc[5] == "37 coins without traps · too few with a 1 h result for a record yet (0 of 20)" and rc[6] == "37 coins · too few for a record yet"
          and "paper, " not in "".join(rc) and "€" not in "".join(rc),
          "U3 the record line comes from one source, record.known (the counts the push and the Office chat say, ui bug 12): 'too few' under 20 coins with a 1 h "
          "result (or counts that do not fit: a count over n, not whole), from 20 on how many doubled and crashed to near zero with the 95%% ranges in the "
          "full line; the Radar record fold's title is the short form; no euros (they are on the Traders tab) %s" % rc)
    check(o["odds"] == [[0.2, 0.3], [0.22, 0.31], None, None] and o["ago"] == ["just now", "34 min ago", "3 h ago"],
          "U3 the trained odds are read from d.upP / d.zeroP and from d.odds {up, zero} (WP3's shapes); 'just now' under a minute %s" % [o["odds"], o["ago"]])
    mo, pt = o.get("mom") or [], o.get("pat") or [""] * 10
    check(mo == ["Rising fast, paper only: 47 coins · 91% crashed · 4% 2x at 1 h · all new coins: 72% crashed, 3% 2x", "Rising fast, paper only: 9 coins · too few yet (9 of 20 with a 1 h price)",
                 "Rising fast, paper only: 1 coin · too few yet (0 of 20 with a 1 h price)", "", "Rising fast, paper only: 47 coins · 91% crashed · 4% 2x at 1 h", ""],
          "the momentum line says 'paper only' and counts coins (never 'calls') with the labelled all-new-coins baseline (the same 1 h label), 'too few yet' "
          "under 20 with a 1 h price, nothing without a record or while no coin rose fast %s" % mo)
    check(pt[:3] == ["Same hours, signals at first sight: 192 crashed vs 25 doubled", "Patterns: too few doubled coins yet (4 of 15)", ""]
          and pt[3] == ["creator sold", "62%", "14%", True, "warn", "41 of 66 crashed, 2 of 14 doubled had it", "crashed"]
          and pt[4] == ["has an X link", "51%", "74%", False, "ok", "65 of 127 crashed, 17 of 23 doubled had it (could be chance)", "doubled"] and pt[5][0] == "some new" and pt[5][6] == ""
          and pt[6] == "PEPE, seen %s, crashed within 1 h · creator sold (0 of 3 doubled that hour had it), RugCheck danger (1 of 3)" % pt[9]
          and pt[7] == "PEPE, crashed within 1 h · has an X link (2 of ? doubled that hour had it)" and pt[8] == ""
          and pt[10] == ["has an X link", "less", "more", True, "ok", "190 of 400 crashed, 100 of 350 doubled had it; hour by hour it is more often in doubled coins", "doubled"],
          "the patterns: the head line or 'too few doubled coins yet (4 of 15)'; a row's label, the share of rugged and of doubled coins with it, or 'less' and "
          "'more' from the hour-by-hour direction when the pooled shares point the other way, the counts in its title ('could be chance' when not sure); a rugged "
          "coin, when it was seen and that it crashed within 1 h, with how many of its hour's doubled coins whose flag is known had them %s" % (pt[:9] + pt[10:]))
    check(o.get("ws") == [True, False, False, False, False, False],
          "the ▲ shows only for a ws of 1 or more once the win order is learned %s" % o.get("ws"))
    py = [P.clean_doc(x) for x in fx]
    check(o.get("parity") == py and len(py) == 5 and py[0]["record"]["pat"]["rows"] and py[1]["model"]["win"]["from"] == "learned" and py[4]["record"]["pat"]["rows"],
          "the page's two whitelists agree: Python's clean_doc and the script's R.clean give the same doc for the good, round, empty and hosts fixtures and the one "
          "with every drop of the new keys%s" % ("" if o.get("parity") == py else " (differ: %s)" % [k for k in py[0] if (o.get("parity") or [{}])[0].get(k) != py[0][k]]))
    words = mo + pt[:3] + [x for r in pt[3:6] + pt[10:] for x in (r[0], r[5], r[6])] + pt[6:9]
    check(not any(BANNED.search(w) or "\u2014" in w for w in words), "U7 the momentum and pattern words carry no 'safe', 'guaranteed' or advice-style 'buy', and no em dash")


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
    imgs: b.querySelectorAll('img, svg, iframe').length, hscroll: document.documentElement.scrollWidth - innerWidth, ev: window.__rev || null,
    recOpen: q('[data-r-rec]').open, recHidden: q('[data-r-rec]').hidden, recNotes: Array.from(b.querySelectorAll('[data-r-recent] > p.note')).map(p => p.textContent),
    recOrder: Array.from(q('[data-r-recent]').children).map(e => e.tagName.toLowerCase() + '.' + e.className),
    pat: Array.from(b.querySelectorAll('[data-r-recent] .rpat tbody tr')).map(tr => [tr.className, tr.title].concat(Array.from(tr.children).map(td => td.textContent))),
    patNote: (b.querySelector('[data-r-recent] .rpat + p.tnote') || {}).textContent || '',
    why: Array.from(b.querySelectorAll('[data-r-recent] .rpwhy li')).map(l => l.textContent), ws: Array.from(b.querySelectorAll('.rws')).map(s => [s.parentElement.className, s.title]) }; }"""
# the Track record fold open at a phone's width: the patterns table inside the fold, the long label cut, a hint muted, the numbers tabular
REC_JS = """() => { const f = document.querySelector('[data-r-rec]'), t = f.querySelector('.rpat'), rows = t ? Array.from(t.querySelectorAll('tbody tr')) : [], col = r => getComputedStyle(r.children[1]).color;
  return { hscroll: document.documentElement.scrollWidth - innerWidth, fits: !!t && t.getBoundingClientRect().right <= f.getBoundingClientRect().right + 0.5,
    cut: rows.filter(r => { const s = r.querySelector('.tc'); return s.scrollWidth > s.clientWidth + 1; }).map(r => r.querySelector('.tc').textContent),
    muted: rows.length > 1 && !rows[0].classList.contains('maybe') && rows.slice(1).every(r => r.classList.contains('maybe') && col(r) !== col(rows[0])),
    marks: rows.map(r => { const q = r.querySelector('.rq'), c = r.children[0].getBoundingClientRect(); if (!q || !q.getClientRects().length) return '';
      const b = q.getBoundingClientRect(); return b.width > 0 && b.left >= c.left && b.right <= c.right + 0.5 && getComputedStyle(q).visibility !== 'hidden' ? q.textContent : 'hidden'; }),
    note: (() => { const n = f.querySelector('.rpat + p.tnote'); return n && n.getClientRects().length ? n.textContent : ''; })(),
    nums: rows.length ? [getComputedStyle(rows[0].children[1]).textAlign, getComputedStyle(rows[0].children[2]).fontVariantNumeric] : [] }; }"""
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
                    pg.click("[data-r-rec] > summary")
                    pg.wait_for_timeout(150)
                    out["recfold"] = pg.evaluate(REC_JS)
                    shot(pg, "1d-radar-track-record-light-390x844.png", el="[data-r-rec]")
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
                        out.setdefault("banner", pg.evaluate("(() => { const b = document.querySelector('#pane-pick .nogood'), h = document.querySelector('#pane-pick h2'); return [b ? b.className : null, h ? h.textContent : null]; })()"))
                        shot(pg, "11-pick-banner-light-%dx%d.png" % (w, h))
                ctx.close()
            # 10. the installed app: five tabs, the radar on New from the live store (no GitHub poll), New's green badge, the deep links; the badge
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
          and g["ev"] == ["running", 1, "github"] and "8" in g["stats"] and g["rec"] == "33 with a 1 h result · 5 doubled · 1 crashed"
          and "33 coins without traps with a 1 h result: 5 doubled, 1 crashed to near zero (95% range: 5% to 27% doubled, 0% to 10% crashed)" in g["recIn"] and "€" not in g["recIn"]
          and "radar data 212 of 300 needed" in g["model"]
          and [a[:2] for a in g["act"]] == [["Start ↗", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"], ["Stop ↗", "https://github.com/some-owner/Meme-Bot/actions/workflows/radar.yml"]]
          and all(a[2] >= 44 for a in g["act"]),
          "U3 browser: #tab-radar opens Radar with the radar's Start and Stop links to radar.yml (44 px); the GitHub poll brings the doc; only the good coin gets a card (the doc's watch "
          "coin does not), with its chip and its line (3 chips and +3), the tab count 1, the fold count 7, the model status; the Radar record fold's title is short (%r), the "
          "counts and their ranges inside, no euros; the memebot-radar event says running, 1 good %s" % (g["rec"], {k: g[k] for k in ("pill", "chips", "ev")}))
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
    check(e_["cards"] == 0 and e_["listHidden"] and "No coin without traps right now" in e_["empty"] and "7 seen under 10 min · all with traps or not fully checked" in e_["empty"] and "2½" not in e_["empty"]
          and "last coin without traps: HIRE, 34 min ago" in e_["empty"] and e_["ocnt"] == "7" and e_["tabcnt"] == "" and all(x <= 0 for x in out["empty_h"])
          and orows.get("GROKAI") == ("rrow bad", "✕") and orows.get("NORC") == ("rrow warn", "?") and orows.get("TWOWARN") == ("rrow warn", "!") and orows.get("PUMPY") == ("rrow warn", "!")
          and e_["recent"] == ["PEPE2", "CALM", "HIRE", "SEALS"],
          "U3 browser: no good coin shows 'No coin without traps right now' (the empty card list hidden), the seen line, the last good coin (HIRE, 34 min ago) and 'Seen, with traps or not "
          "fully checked (7)': trap rows red with ✕, watch rows amber with ? (not checked) or ! (warnings); no tab count; the Radar record lists the calls of the last 3 h only %s %s" % (orows, e_["recent"]))
    check(g.get("ytab") is None and e_.get("ytab") is None and g.get("tabcnt") == "1" and e_.get("tabcnt") == "",
          "U3 browser: the website's Radar label carries one number, the radar's count of coins without traps (1, hidden at 0); no full-scan count any more "
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
    check(hn[:1] == ["RugCheck limited: 2 coins not fully checked"] and any(x.startswith("wallet check unavailable") for x in hn) and "pump.fun trades: down" in hn
          and "live feed: limited" in hn and len(hn) == 4 and not any("unused" in x or "off" in x.split(":")[-1] or "pumpportal" in x for x in hn),
          "S2 host notes: WP3's routine states (unused, off) make none; a down host gets a plain one, a limited one the radar already named gets none, the pump.fun "
          "feed is named 'live feed' as on the Office desk; an old wallet memory gets the page's note %s" % hn)
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
          and "Coins still on the bonding curve are not rated here: the curve watch calls them on paper only (About to graduate), with no push while its switch is off" in why
          and "radar data 212 of 300 needed" in why,
          "S1 the 'Why these checks?' fold shows each check with its study evidence in words, the weight-0 list by label, the model status and that coins "
          "still on their curve are only called on paper (%r)" % why[:120])
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
    check(bn == [None, "Risky pick for the next %s" % R.horizon_text()],
          "U5 browser: the fallback pick shows no banner any more, one heading by its tier instead (ui bug 19) %s" % bn)
    hs = out["h"]
    check(all(v <= 0 for v in hs.values()) and all(a["hscroll"] <= 0 for a in out["app"].values()) and len(hs) >= 16,
          "U8 no sideways scroll on Pick, New (with the radar) and Office at 390 x 844 and 1280 x 900, light and dark, and in the installed app on all five tabs (%d views%s)" % (
              len(hs) + len(out["app"]), "" if all(v <= 0 for v in hs.values()) else " " + str({k: v for k, v in hs.items() if v > 0})))
    ap = out["app"]["390x844 light"]
    check(ap["app"] and ap["tabs"] == ["home", "pick", "young", "office", "account"] and ap["names"] == ["Start", "Pick", "Radar", "Gehirn", "Archiv"] and ap["radar"]
          and ap["apptab"] == "young" and ap["badge_ok"] and ap["aria"] == "Radar, 1 coin without traps now" and ap["cards"] == 1 and out.get("deep") == ["young", True] and ap["y"] == 0
          and out["calls"]["gh"] == 0 and out["calls"]["sb"] >= 1 and all(a["over"] == 0 and a["btnW"] >= 60 for a in out["app"].values()) and not errs,
          "A3 installed app: five tabs (Start, Pick, Radar, Gehirn, Archiv), #tab-radar and the radar notification's message open Radar at its top, its badge says 1 in "
          "green (%s, read out in words), the live store's row radar feeds it and GitHub is not polled; no label cut at 320 px %s" % (
              ap.get("badgeBg"), {k: ap[k] for k in ("names", "aria")} if not errs else [errs[:2], ap, out.get("deep"), out["calls"]]))
    bg = out.get("badgeGone") or [False, "?"]
    check(bg[0] and bg[1] == "Radar",
          "S4 A3 the app's Radar badge follows the radar's news: the live store's row turns to no good coin and the badge goes (%s)" % bg)
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
    rcf, why_re = out.get("recfold") or {}, r"^%s, seen \d\d:\d\d, crashed within 1 h · %s$"
    check(g.get("recOpen") is False and not g.get("recHidden") and g.get("recOrder") == ["p.note rrline", "p.note rrmom", "p.note", "table.rpat", "p.tnote", "ul.rpwhy", "div.rrec-w"]
          and g.get("recNotes", [])[1:] == ["Rising fast, paper only: 47 coins · 91% crashed · 4% 2x at 1 h · all new coins: 72% crashed, 3% 2x", "Same hours, signals at first sight: 192 crashed vs 25 doubled"]
          and g.get("pat") == [["", "41 of 66 crashed, 2 of 14 doubled had it", "!creator sold", "62%", "14%"],
                               ["maybe", "65 of 127 crashed, 17 of 23 doubled had it (could be chance)", "✓has an X link?", "51%", "74%"],
                               ["maybe", "30 of 120 crashed, 2 of 20 doubled had it (could be chance)", "·top holders funded by one wallet?", "25%", "10%"]]
          and g.get("patNote") == "? could be chance"
          and len(g.get("why", [])) == 2 and re.match(why_re % ("SEALS", r"creator sold \(0 of 3 doubled that hour had it\), RugCheck danger \(1 of 3\)"), g["why"][0])
          and re.match(why_re % ("RUGGY", r"top holders funded by one wallet \(0 of 2 doubled that hour had it\)"), g["why"][1]),
          "the Track record fold (closed at first) holds, after the record line, the momentum line, the patterns' head, at most 3 signals (a hint that could be "
          "chance marked) and the rugged coins' flags, then the later prices; no new fold %s" % [g.get("recNotes", [])[1:], g.get("why")])
    check(rcf.get("hscroll", 1) <= 0 and rcf.get("fits") and rcf.get("cut") == ["·top holders funded by one wallet"] and rcf.get("muted") and rcf.get("nums") == ["right", "tabular-nums"]
          and rcf.get("marks") == ["", "?", "?"] and rcf.get("note") == "? could be chance",
          "the patterns at 390 px with the fold open: no sideways scroll, the table inside the fold, a long label cut with an ellipsis, a hint muted and "
          "marked with a visible '?' beside its label (a phone shows no title) and the note '? could be chance' under the table, the %% columns "
          "right-aligned and tabular %s" % rcf)
    check(e_.get("recNotes", [])[1:] == ["Rising fast, paper only: 9 coins · too few yet (9 of 20 with a 1 h price)", "Patterns: too few doubled coins yet (4 of 15)"]
          and e_.get("pat") == [] and e_.get("why") == [] and e_.get("recOrder") == ["p.note rrline", "p.note rrmom", "p.note", "div.rrec-w"],
          "too few: the momentum line and the patterns' head say so, no table and no coin lines %s" % e_.get("recNotes", [])[1:])
    wt = "orders like past doubled coins (hindsight)"
    check(rf.get("ws") == [["rtop", wt], ["rs", wt]] and g.get("ws") == [] and (out.get("hosts") or {}).get("ws") == []
          and rf.get("model", "").endswith(" · radar data 212 of 300 needed · win order learned on 260 coins") and "win order" not in g.get("model", ""),
          "the ▲ (%s) on the card and the fold's row with a ws of 1 or more only once the win order is learned (a round here), the model line then says "
          "'win order learned on 260 coins' %s" % (wt, [rf.get("ws"), rf.get("model")]))


def src_checks(check, tmp, skips):
    """radar.json's "src" (the round's discovery counts, the office desk's Sources) through both whitelists: names like gt:new, whole counts
    0..100000, the first 12 entries; Python and the script keep the same."""
    import page_radar as P
    t = 1_760_000_000_000
    bad = {"gt:new": 40, "pf:graduated": 180.0, "ll:llNew": 3, "Bad": 1, "x y": 2, "jup:recent": 2.5, "pf:new": True, "list:profiles": -1, "kw:x": 100001, "gm:x": "7", "<b>": 1}
    docs = [dict(kind="radar", t=t, src=bad), dict(kind="radar", t=t, src={"s:%d" % i: i for i in range(13)}), dict(kind="radar", t=t, src=[1, 2]), dict(kind="radar", t=t)]
    py = [P.clean_doc(d)["src"] for d in docs]
    check(py[0] == {"gt:new": 40, "pf:graduated": 180, "ll:llNew": 3} and list(py[1]) == ["s:%d" % i for i in range(12)] and py[2] == py[3] == {},
          "the whitelist keeps src only with names like gt:new and whole counts 0..100000, its first 12 entries (%s)" % py[0])
    node = shutil.which("node")
    if not node:
        skips.append("the src whitelist in node (no node)")
        return
    jd = os.path.join(tmp, "js-src")
    os.makedirs(jd, exist_ok=True)
    with open(os.path.join(jd, "src.js"), "w", encoding="utf-8") as f:
        f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;},getElementById:function(){return null;}};global.navigator={};\n"
                + P.JS + "\nconsole.log(JSON.stringify(%s.map(function(d){return window.MemebotRadar.clean(d).src;})));\n" % json.dumps(docs))
    r = subprocess.run([node, os.path.join(jd, "src.js")], capture_output=True, text=True)
    js = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    check(js == py, "the script's whitelist keeps the same src as Python's (%s)" % (js if js is not None else r.stderr[-300:]))


# ---------------------------------------------------------------------------------------------- the curve watch's section (About to graduate)
XSS_CURVE = "<img src=c onerror=a(8)>"      # 24 characters: kept whole by the whitelist, so it must arrive escaped
CURVE_BANNED = re.compile(r"\bsafe\b|\bguaranteed\b|\bbuy\b|\bbuying\b|\bclean\b|\bshould\b", re.I)


def curve_block(t, kind="calls"):
    """radar.json's curve block as launch_radar.curve_doc writes it (curve_watch.Book.doc's shape) at the doc's time t: kind calls (eight coins,
    ten calls: H2O called at 60, 75 and 90 % and graduated, one still on the curve, one that did not graduate, a dead one, a pushed one that
    doubled, a risky one, one without a 1 h value, a trap), empty (on, no call yet), off (rounds only, the same calls), on (the push switch on
    for 75m), list (on, the list only: the feed sends no trades, no coin followed on it), xss (a hostile symbol, chip, why and host), hostile
    (shapes the whitelists must drop)."""
    rng = random.Random(21)
    m = lambda: b58(rng)
    h2o = m()
    ok_chips = [["ok", "no rugger wallets"], ["ok", "RugCheck report"], ["info", "dev: 3 launches, 1 dead"]]
    call = lambda a, sym, thr, ago, prog, mcu, age, v="unknown", chips=(), out=None, push=None, mom=None, pts=None: {
        "mint": a, "sym": sym, "thr": thr, "t": t - ago, "prog": prog, "mcu": mcu, "mcs": round(mcu / 150.0, 2) if mcu else None, "age": age, "mom": mom, "pts": pts,
        "buys": 40, "sells": 12, "v": v, "chips": [list(c) for c in chips], "push": push, "out": out or {}}
    recent = [call(h2o, "H2O", 90, 4 * MIN, 90.3, 112_000, 69.8, "ok", ok_chips, {"grad": t - 2 * MIN, "gradMin": 2.0}, mom=True, pts=14.2),
              call(m(), "TRAPPY", 60, 5 * MIN, 60.4, 24_000, 6.1, "trap", [["bad", "3 holders from rugged coins"], ["warn", "no socials"]]),
              call(m(), "STILL", 60, 8 * MIN, 61.0, 31_000, 14.2, "unknown", [["unk", "RugCheck pending"]]),
              call(h2o, "H2O", 75, 12 * MIN, 76.2, 58_250, 61.5, "ok", ok_chips, {"grad": t - 2 * MIN, "gradMin": 10.0}, mom=True, pts=11.0),
              call(h2o, "H2O", 60, 20 * MIN, 60.8, 31_400, 53.0, "unknown", (), {"grad": t - 2 * MIN, "gradMin": 18.0}),
              call(m(), "RISKY", 75, 30 * MIN, 75.9, 61_000, 22.4, "risky", [["warn", "creator sold"], ["info", "61% sniped in 30 s (12 wallets)"]]),
              call(m(), "DEADC", 60, 65 * MIN, 60.2, 25_500, 0.4, "unknown", (), {"x60": 0.03, "at60": t - 5 * MIN, "how": "dead", "peak": 1.1, "rug": True, "x2": False, "eur": -2.91}),
              call(m(), "NOGRAD", 75, 70 * MIN, 75.5, 59_999, 140.0, "ok", ok_chips[:2], {"x60": 0.4231, "how": "curve", "peak": 1.3, "rug": False, "x2": False, "eur": -1.79}),
              call(m(), "MOONY", 90, 75 * MIN, 90.1, 1_254_000, 3000.0, "ok", ok_chips, {"grad": t - 73 * MIN, "gradMin": 2.0, "x60": 3.1, "how": "pool", "peak": 4.2, "rug": False,
                                                                                       "x2": True, "eur": 6.125}, push=t - 74 * MIN, mom=True, pts=21.0),
              call(m(), "MISSV", 60, 90 * MIN, 60.0, None, None, "unknown", (), {"miss": True, "why": "graduated after the hour, no curve price at it"})]
    stats = lambda n, ns, rug, x2, eur, **kw: dict({"n": n, "nS": ns, "rug": rug, "x2": x2, "eur": eur}, **kw)
    variants = [dict(stats(18, 12, 0.333, 0.083, -0.95, grad=0.25, gradMin=14.0, miss=1), id="60", thr=60, mom=False, by={"unknown": stats(10, 6, 0.5, 0.0, -1.2), "ok": stats(8, 6, 0.167, 0.167, -0.7)}),
                dict(stats(5, 3, 0.0, 0.333, 0.4, grad=0.4, gradMin=9.0, miss=0), id="60m", thr=60, mom=True, by={"ok": stats(5, 3, 0.0, 0.333, 0.4)}),
                dict(stats(31, 24, 0.25, 0.333, 0.42, grad=0.5, gradMin=6.0, miss=1), id="75", thr=75, mom=False,
                     by={"ok": stats(12, 9, 0.111, 0.444, 1.1), "risky": stats(8, 7, 0.571, 0.143, -1.6), "trap": stats(3, 2, 1.0, 0.0, -3.0), "unknown": stats(8, 6, 0.0, 0.5, 0.9)}),
                dict(stats(9, 6, 0.167, 0.5, 1.35, grad=0.667, gradMin=4.0, miss=0), id="75m", thr=75, mom=True, by={"ok": stats(9, 6, 0.167, 0.5, 1.35)}),
                dict(stats(4, 2, 0.0, 0.5, 0.125, grad=1.0, gradMin=2.0, miss=0), id="90", thr=90, mom=False, by={"ok": stats(4, 2, 0.0, 0.5, 0.125)}),
                dict(stats(0, 0, None, None, None, grad=None, gradMin=None, miss=0), id="90m", thr=90, mom=True, by={})]
    cv = {"v": 1, "t": t, "since": t - 9 * H, "hours": 9, "ticket": 3.0, "slip": 0.05, "thresholds": [60, 75, 90], "momPts": 10.0, "calls": 67, "late": 4,
          "recent": recent, "variants": variants, "greens": {"n": 26, "nS": 21, "rug": 0.19, "x2": 0.143, "eur": -0.31, "grad": None},
          "calib": {"n": 7, "mcSol": 405.2, "prog": 98.6, "scale": 1.0, "expect": 410.9}, "state": "on", "why": "", "follow": 14, "cand": 52, "trades": 18_400,
          "polls": 1060, "sol": 150.0, "hosts": {"pump.fun": "ok", "trades": "ok"}, "push": {"variant": None, "verdicts": ["ok"], "perH": 3, "sent1h": 0}}
    if kind == "empty":
        cv.update(calls=0, late=0, recent=[], variants=[dict(v, n=0, nS=0, by={}) for v in variants], greens={"n": 0, "nS": 0, "rug": None, "x2": None, "eur": None, "grad": None})
    elif kind == "off":
        cv.update(state="off", why="rounds only: the watch runs in a loop's spare time", hosts={"pump.fun": "ok", "trades": "off"})
    elif kind == "on":
        cv["push"] = {"variant": "75m", "verdicts": ["ok", "unknown"], "perH": 3, "sent1h": 1}
    elif kind == "list":
        cv.update(why="list only: PumpPortal sends coin trades only to paid clients", follow=0, trades=0, hosts={"pump.fun": "ok", "trades": "unavailable"},
                  recent=[dict(r, buys=None, sells=None) for r in recent])
    elif kind == "xss":
        cv["recent"] = [dict(r, sym=XSS_CURVE, chips=[["bad", XSS_CURVE]]) if i < 2 else r for i, r in enumerate(recent)]
        cv.update(state="limited", why=XSS_CURVE, hosts={"pump.fun": "<b>ok</b>", "trades": "silent"})
    elif kind == "hostile":
        cv["recent"] = [dict(recent[0], mint="0x<b>NOTBASE58"), dict(recent[1], thr=80), dict(recent[2], t="soon"), dict(recent[3], v="great", chips=[["evil", "x"], ["ok", 5], "z", ["warn", "\u200b"]]),
                        dict(recent[4], sym="A\u202eB\u0000C" + "\U0001F438" * 12, mom="yes", out={"grad": "x", "rug": "true", "how": "moon", "miss": 1}), [1], None] + recent[5:]
        cv["variants"] = [dict(variants[0], id="80x"), dict(variants[1], id="60m\n"), dict(variants[2], by={"ok": [1], "great": variants[2]["by"]["ok"], "risky": None})] + variants[3:]
        cv.update(state="weird", thresholds=[60, "75", True, 80, 90.0], hosts={"pump.fun": "OK", "trades": "limited", "x": "ok"}, push={"variant": "75x", "verdicts": ["trap", "ok", ["ok"]], "perH": "3"},
                  calib=[1], greens="x", why=["no"], since=-5)
    return cv


CURVE_JS = """() => { const b = document.querySelector('[data-r-curve]'), q = s => b.querySelector(s), vis = e => !!(e && e.getClientRects().length), r = e => e.getBoundingClientRect();
  const shown = e => { if (!vis(e) || getComputedStyle(e).visibility === 'hidden') return false;
    for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS' && !p.open && !(e.tagName === 'SUMMARY' && e.parentElement === p)) return false; return true; };
  const tab = q('.rc-tab'), wrap = tab && tab.parentElement;
  return { hidden: b.hidden, cls: b.className, html: b.innerHTML, text: b.innerText, hscroll: document.documentElement.scrollWidth - innerWidth,
    small: Array.from(b.querySelectorAll('a[href], summary')).filter(shown).filter(e => r(e).height < 43.5).map(e => e.textContent.slice(0, 30) + ' ' + Math.round(r(e).height)),
    inBox: !!wrap && r(wrap).right <= r(b).right + 0.5 && r(wrap).left >= r(b).left - 0.5, tabFits: !!tab && tab.scrollWidth <= wrap.clientWidth + 1,
    syms: Array.from(b.querySelectorAll('.rc-coin')).filter(shown).map(li => li.querySelector('.rc-sym').textContent),
    status: Array.from(b.querySelectorAll('.rc-coin')).map(li => li.querySelector('.rc-s').className + '|' + li.querySelector('.rc-s').textContent),
    imgs: b.querySelectorAll('img, svg, iframe, script').length, links: Array.from(b.querySelectorAll('a')).map(a => [a.getAttribute('href'), a.target, a.rel]),
    above: (() => { const o = document.querySelector('[data-r-others]'), k = document.querySelector('[data-r-rec]'), f = b.closest('details.rcurvef');
      return !!(o && k && f && (o.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) && (k.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)); })(),
    more: !!q('details.rc-more') && q('details.rc-more').open, pushCls: (q('.rc-push') || {}).className || '', ev: window.__rev || null,
    lowc: (() => { const lum = c => { let m = c.match(/[\\d.]+/g).map(Number); if (/^color\\(srgb/.test(c)) m = m.map((v, i) => i < 3 ? v * 255 : v);
        const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]); };
      const bgOf = e => { for (let p = e; p; p = p.parentElement) { const c = getComputedStyle(p).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; };
      return Array.from(b.querySelectorAll('[class^="rc-"], [class*=" rc-"]')).filter(shown).filter(e => Array.from(e.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()))
        .map(e => { const a = lum(getComputedStyle(e).color), c = lum(bgOf(e)); return [e.className, Math.round(100 * (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05)) / 100]; })
        .filter(x => x[1] < 4.5); })() }; }"""


def curve_checks(check, tmp, skips, shots=None):
    """The curve watch's section on the New tab ("About to graduate (paper test)"): both whitelists keep the block (and drop what they must), the
    build's and the script's views and elements are the same, the texts, escaping and wording, its place under the list, and the phone and
    desktop layouts in light and dark (screenshots into shots/curve when asked)."""
    import page_radar as P
    import curve_watch as CW
    print("== the curve watch's section on the New tab (About to graduate, paper test)")
    now = int(time.time() * 1000)
    t = now - 30_000
    blocks = {k: curve_block(t, k) for k in ("calls", "empty", "off", "on", "list", "xss", "hostile")}
    docs = {k: dict(radar_doc(now, "good"), curve=b) for k, b in blocks.items()}
    docs["none"] = radar_doc(now, "good")
    docs["bad block"] = dict(radar_doc(now, "good"), curve={"state": "on"})
    import launch_radar as LR                   # the night: the loop's last doc kept by finish_from, a call 2 minutes before the watch stopped
    blk = dict(blocks["calls"], recent=[dict(blocks["calls"]["recent"][2], t=t - 2 * MIN, out={})] + blocks["calls"]["recent"][3:])
    docs["hours"] = LR.finish_from(dict(radar_doc(now, "good"), curve=blk), "hours", now, "outside the radar's hours", "t", None, None, "manual", (7, 24))
    docs["lone half"] = dict(radar_doc(now, "good"), curve=dict(blocks["calls"], recent=[dict(blocks["calls"]["recent"][0], sym="A\udc00B\ud83d",
                                                                                              chips=[["ok", "x\udc00y"]])] + blocks["calls"]["recent"][1:]))
    cl = {k: P.clean_doc(d) for k, d in docs.items()}
    cv = cl["calls"]["curve"]
    # 1. the whitelist keeps the block whole (every key of curve_watch's shape) and drops what it must
    raw = blocks["calls"]
    ok9 = ("grad", "gradMin", "x60", "peak", "rug", "x2", "eur", "how", "miss")
    keep = all(set(r) <= set(c) and all(c[k] == r[k] for k in r if k != "out") and all(c["out"][k] == x for k, x in r["out"].items() if k in ok9)
               for r, c in zip(raw["recent"], cv["recent"]))
    check(cv and len(cv["recent"]) == 10 and keep and [v["id"] for v in cv["variants"]] == ["60", "60m", "75", "75m", "90", "90m"] and cv["variants"][2]["by"]["risky"]["eur"] == -1.6
          and cv["greens"]["n"] == 26 and cv["calib"]["prog"] == 98.6 and cv["hosts"] == {"pump.fun": "ok", "trades": "ok"} and cv["push"]["variant"] is None
          and cl["none"]["curve"] is None and cl["bad block"]["curve"] is None,
          "curve whitelist: clean_doc keeps radar.json's curve block with every call (10), its outcome fields, the six variants with their split by the quick check, "
          "the greens, the calibration, the hosts and the push switch; no block or one without a time is None")
    h = cl["hostile"]["curve"]
    hr = {r["sym"]: r for r in h["recent"]}
    check([r["sym"] for r in h["recent"]] == ["H2O", "A B C" + "\U0001F438" * 9, "RISKY", "DEADC", "NOGRAD", "MOONY", "MISSV"] and h["recent"][0]["v"] == "unknown"
          and h["recent"][0]["chips"] == [] and hr["H2O"]["thr"] == 75 and [v["id"] for v in h["variants"]] == ["75", "75m", "90", "90m"] and h["variants"][0]["by"] == {}
          and h["state"] == "off" and h["thresholds"] == [60, 90.0] and h["hosts"] == {"trades": "limited"} and h["push"] == {"variant": None, "verdicts": ["ok"], "perH": None, "sent1h": None}
          and h["calib"] is None and h["greens"] is None and h["why"] == "" and h["since"] is None and "NOTBASE58" not in json.dumps(h),
          "curve whitelist drops a mint that is not base58, a mark of 80, a call without a time, an unknown verdict (read as not fully checked) and bad chips, "
          "a variant id 80x or with a newline, a split row that is no row, an unknown state (off), thresholds not 60/75/90, a host state that is not lower-case "
          "letters, a push variant 75x and a trap verdict in the push list, a calib or greens that is no object (%s)" % [r["sym"] for r in h["recent"]])
    weird = P.clean_curve(dict(raw, recent=[dict(raw["recent"][0], sym="A\u202eB\u0000C" + "\U0001F438" * 12, mom="yes", out={"grad": "x", "rug": "true", "how": "moon", "miss": 1})]))
    w0 = weird["recent"][0]
    check(w0["sym"] == "A B C" + "\U0001F438" * 9 and w0["mom"] is None and w0["out"] == {"grad": None, "gradMin": None, "x60": None, "peak": None, "rug": None, "x2": None, "eur": None, "how": "",
                                                                                      "miss": False, "done": False},
          "curve whitelist: a symbol's direction marks and controls become spaces, the cut is in UTF-16 units without a half emoji (24: %r); a momentum, rug, "
          "graduation or 'how' of the wrong type is unknown, a miss only a real true" % w0["sym"])
    # the real book's block (curve_watch.Book.doc with the radar's state) keeps every key through the whitelist
    B = CW.Book()
    a1, a2 = b58(random.Random(31)), b58(random.Random(32))
    rowc = lambda a, p, at: {"mint": a, "symbol": "BOOK", "virtual_token_reserves": (CW.VT0 - CW.SELL * p / 100.0) * 1e6, "complete": False, "created_timestamp": t - 40 * MIN,
                             "last_trade_timestamp": at, "usd_market_cap": 1.0, "market_cap": 1.0 / 150}
    B.rows([rowc(a1, 58, t - 20 * MIN), rowc(a2, 72, t - 20 * MIN)], t - 20 * MIN)
    B.polled(t - 20 * MIN)
    B.rows([rowc(a1, 61, t - 19 * MIN), rowc(a2, 77, t - 19 * MIN)], t - 19 * MIN)
    B.migrate(a2, t - 10 * MIN, "feed")
    bd = B.doc(t, {"state": "on", "why": "", "follow": 2, "hosts": {"pump.fun": "ok", "trades": "waiting"}, "push": {"variant": None, "verdicts": ["ok"], "perH": 3, "sent1h": 0}},
               CW.greens_stats([], B.active_hours()))
    bc = P.clean_curve(json.loads(json.dumps(bd)))
    lost = [k for k in bd if k not in bc] + [k for r in bd["recent"] for k in r if k not in bc["recent"][0]] + [k for v in bd["variants"] for k in v if k not in bc["variants"][0]]
    check(bc and not lost and len(bc["recent"]) == len(bd["recent"]) == 2 and len(bc["variants"]) == 6 and bc["recent"][1]["out"]["grad"] == t - 10 * MIN,
          "curve whitelist on curve_watch.Book.doc's own block: no key lost (%s), its calls and the graduation kept" % (lost or "none"))
    hv = [P.curve_view(cl["hours"]["curve"], n) for n in (t, t + 61 * MIN, t + 7 * H)]
    lh = (cl["lone half"] or {}).get("curve") or {}
    check(cl["hours"]["curve"]["state"] == "off" and cl["hours"]["curve"]["t"] == t and hv[0]["head"] == "Curve watch off: the radar is hours"
          and [h_["coins"][0]["st"] for h_ in hv] == [["live", "still on the curve"], ["muted", "not watched to the end"], ["muted", "not watched to the end"]]
          and cl["lone half"] is not None and lh["recent"][0]["sym"] == "A B" and lh["recent"][0]["chips"][0] == ["ok", "x y"] and len(json.dumps(cl["lone half"])) > 0,
          "curve view at night (the loop's last doc kept by finish_from, the watch off, a call 2 minutes before it stopped): still on the curve at the "
          "block's time, then 'not watched to the end' an hour and 7 hours on, never 'did not graduate'; a symbol or chip with a lone surrogate half "
          "(a JSON escape cut in two) keeps the doc, the half a space")
    # 2. the view: head, sentences, coins (newest call per coin), statuses, results, tables, footnote
    v = P.curve_view(cv, t)
    co = v["coins"] + v["more"]
    check(v["head"] == "Curve watch on · 14 coins followed · 9 h watched" and [c["sym"] for c in co] == ["H2O", "TRAPPY", "STILL", "RISKY", "DEADC", "NOGRAD", "MOONY", "MISSV"]
          and len(v["coins"]) == P.CURVE_SHOWN and co[0]["prog"] == "90%" and co[0]["nums"] == "1 h 9 min after mint · market cap $112k · called at 60, 75 and 90%"
          and co[0]["line"][0] == ["ok", "no trap found yet"] and co[0]["line"][1:] == [["ok", "no rugger wallets"], ["ok", "RugCheck report"], ["info", "dev: 3 launches, 1 dead"]]
          and co[1]["line"][0] == ["bad", "trap"] and co[2]["line"][0] == ["unk", "not fully checked"] and co[3]["line"][0] == ["warn", "risky"]
          and [c["st"] for c in co] == [["grad", "graduated after 2 min"], ["live", "still on the curve"], ["live", "still on the curve"], ["live", "still on the curve"],
                                        ["bad", "dead"], ["muted", "did not graduate"], ["grad", "graduated after 2 min"], ["muted", "not watched to the end"]]
          and [c["res"] for c in co] == [None, None, None, None, ["bad", "rugged in 1 h"], ["", "1 h: 0.42x"], ["good", "doubled in 1 h"], ["muted", "no 1 h value"]]
          and co[4]["nums"] == "under 1 min after mint · market cap $26k · called at 60%" and co[5]["nums"].startswith("2 h 20 min after mint · market cap $60k")
          and co[6]["nums"] == "2 days after mint · market cap $1.3M · called at 90% · sent to the phone" and co[7]["nums"] == "mint time unknown · market cap unknown · called at 60%",
          "curve view: the head line, one row per coin by its newest call (H2O called at 60, 75 and 90%%, its newest numbers), its quick check first on its line, "
          "the status now (graduated after N min, still on the curve, dead, did not graduate when valued on its curve, not watched to the end without a "
          "value) and the hour's result (rugged, the multiple, doubled, no value) %s" % [c["st"][1] for c in co])
    vt = P.curve_view(cv, t + 61 * MIN)
    cv_later = dict(cv, t=t + 61 * MIN)
    vl = P.curve_view(cv_later, t + 61 * MIN)
    done_cv = dict(cv, recent=[dict(cv["recent"][2], out=dict(cv["recent"][2]["out"], done=True))])
    check([c["st"][1] for c in vt["coins"]][:3] == ["graduated after 2 min", "not watched to the end", "not watched to the end"]
          and [c["st"][1] for c in vl["coins"]][:3] == ["graduated after 2 min", "did not graduate", "did not graduate"]
          and P.curve_view(done_cv, t + 2 * H)["coins"][0]["st"] == ["grad", "graduated"],
          "curve view: an hour after a call by the viewer's clock, with the block's own time before it (the watch's last word), the coin was 'not watched "
          "to the end' (never 'did not graduate' for an hour nobody saw); a block whose own time is past the hour says did not graduate; a graduation "
          "found only later says graduated, without minutes")
    rows = {r["cells"][0]: r for r in v["rows"]}
    check(list(rows) == ["60%", "60% rising", "75%", "75% rising", "90%", "90% rising", "radar greens"]
          and rows["75%"]["cells"] == ["75%", "31", "50%", "25%", "33%", "+0.42"] and rows["75%"]["cls"] == "" and rows["60%"]["cls"] == "few"
          and rows["90%"]["cells"][-1] == "+0.13" and rows["60%"]["cells"][-1] == "−0.95" and rows["90% rising"]["cells"] == ["90% rising", "0", "–", "–", "–", "–"]
          and rows["radar greens"]["cells"] == ["radar greens", "26", "–", "19%", "14%", "−0.31"] and rows["radar greens"]["cls"] == "rc-g"
          and rows["75%"]["title"] == "31 calls, 24 with a 1 h value, graduated a median 6 min after the call, 1 without a 1 h value"
          and [r["cells"][:3] for r in v["by"]][:3] == [["60%", "no trap found yet", "8"], ["60%", "not fully checked", "10"], ["60% rising", "no trap found yet", "5"]]
          and len(v["by"]) == 9 and v["ticket"] == "3\u00a0€",
          "curve table: a row per variant (calls, graduated, rugged and doubled in 1 h, paper per 3 €, half up in whole cents: 0.125 is +0.13 € in both languages), grey under 20 "
          "valued calls, the radar's greens of the same hours last, and the split by the quick check (only verdicts with calls) %s" % rows["75%"]["cells"])
    check(v["note"] == ("Paper test: the radar calls pump.fun coins still on their bonding curve, before the pool opens, at 60, 75 and 90% of the curve sold, to find out "
                        "whether an earlier call helps. Each call is judged 1 h later with 3\u00a0€ on paper and 5% slippage, beside the radar's greens of the same hours.")
          and v["push"] == "No curve push goes out while the switch is off." and not v["pushOn"]
          and P.curve_view(cl["on"]["curve"], t)["push"] == "Curve pushes are on for the 75% rising calls (quick check: no trap found yet or not fully checked), at most 3 an hour."
          and "4 times a trading coin was first seen already past a mark, so no call was made." in v["foot"] and "at the last trade before 7 graduations the curve read 99% sold" in v["foot"]
          and "Rugged: gone, dead or worth 0.1x or less at 1 h; doubled: 2x to 30x within the hour and not gone or dead at 1 h; the greens by the same rules." in v["foot"]
          and "the first one within 90 s after it (then counted from that moment's price)" in v["foot"] and "of the calls an hour old whose hour was seen" in v["foot"]
          and P.curve_view(cl["off"]["curve"], t)["head"] == "Curve watch off: rounds only: the watch runs in a loop's spare time"
          and P.curve_view(cl["empty"]["curve"], t) == {"state": "on", "head": "Curve watch on · 14 coins followed · 9 h watched", "one": True} and P.curve_view(None, t) is None,
          "curve view: the paper test's sentence, 'No curve push goes out while the switch is off.' (switched on: which variant, which checks, how many an hour), "
          "the footnote (rising, the shares, the skipped calls, the progress check), a watch that is off says why, a block without a call is one line")
    vlist = P.curve_view(cl["list"]["curve"], t)
    rising = "Rising: 10 or more points of the curve in the 5 minutes before the call, and more purchases than sales. Without the coin's trades (pump.fun's list only) the points alone count."
    check(cl["list"]["curve"]["state"] == "on" and cl["list"]["curve"]["hosts"] == {"pump.fun": "ok", "trades": "unavailable"}
          and vlist["head"] == "Curve watch on · list only: PumpPortal sends coin trades only to paid clients · 9 h watched" and "0 coins" not in vlist["head"]
          and vlist["foot"].startswith(rising) and v["foot"].startswith(rising) and [c["sym"] for c in vlist["coins"] + vlist["more"]] == [c["sym"] for c in co]
          and P.curve_view(dict(cl["list"]["curve"], recent=[], calls=0), t)["head"] == vlist["head"],
          "curve view, the list only (the feed sends no coin trades without a paid key): the head says on and why, never '0 coins followed'; the "
          "variant legend says in one sentence that without trades the points alone count (%r)" % vlist["head"])
    # 3. the page: under the list (after Seen but not clean, before the Track record), escaped, hidden without a block, plain words
    pane = {k: P.curve_section(cl[k]) for k in ("calls", "empty", "off", "on", "xss", "none")}
    full = P.pane({"now": now, "dir": None})
    xs = pane["xss"]
    words = " ".join(visible_text(pane[k]) for k in pane) + " ".join(json.dumps(P.curve_view(cl[k]["curve"], t)) for k in ("calls", "on", "off", "xss"))
    js_words = " ".join(re.findall(r"'([^'\\]{6,})'", P.JS[P.JS.find("var CV="):P.JS.find("var R=window.MemebotRadar")] + P.JS[P.JS.find("  cleanCurve:"):P.JS.find("  clean:function")]))
    check(XSS_CURVE not in xs and "&lt;img src=c onerror=a(8)&gt;" in xs and "<b>ok</b>" not in json.dumps(cl["xss"]) and 'href="https://pump.fun/coin/' in pane["calls"]
          and pane["none"] == '<section class="rcurve" data-r-curve aria-label="About to graduate, paper test" hidden></section>'
          and pane["empty"].count("<p") == 1 and "About to graduate (paper test):</b> no call yet · Curve watch on" in pane["empty"] and 'class="rcurve one"' in pane["empty"]
          and full.find("data-r-others") < full.find("data-r-rec") < full.find("data-r-curve") and '<details class="rfold rcurvef"><summary><span class="t">Curve test (experiment)</span>' in full
          and full.find('<details class="rfold rcurvef">') < full.find("data-r-curve") and "No curve push goes out while the switch is off." in pane["calls"]
          and 'rel="noopener noreferrer"' in pane["calls"] and not CURVE_BANNED.search(words + " " + js_words) and "\u2014" not in words + P.JS + P.CSS,
          "curve section on the page: a hostile symbol, chip and why arrive escaped, a hostile host state is dropped; the coin links open pump.fun in a new tab "
          "without the referrer; no block: hidden; no call yet: one line; it sits in one closed fold 'Curve test (experiment)' at the end of the Radar tab "
          "(after Seen, with traps or not fully checked and the Radar record); its words "
          "and the script's never say buy, safe, clean or should, and no em dash")
    # 4. node: the script's whitelist and view say the same as Python's for every block above (raw and with a moving clock)
    node = shutil.which("node")
    if not node:
        skips.append("the curve section's node checks (no node)")
        print("  SKIP the curve section's node checks: node is not installed")
    else:
        cases = [[k, d] for k, d in docs.items()]
        nows = [t, t + 61 * MIN, t + 3 * H]
        jd = os.path.join(tmp, "js-curve")
        os.makedirs(jd, exist_ok=True)
        with open(os.path.join(jd, "c.js"), "w", encoding="utf-8") as f:
            f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;},getElementById:function(){return null;}};global.navigator={};\n"
                    + P.JS + "\nvar R=window.MemebotRadar,C=%s,N=%s;\nconsole.log(JSON.stringify(C.map(function(c){var d=R.clean(c[1]);return [c[0],d&&d.curve,N.map(function(n){return R.curveView(d&&d.curve,n);})];})));\n"
                    % (json.dumps(cases), json.dumps(nows)))
        r = subprocess.run([node, os.path.join(jd, "c.js")], capture_output=True, text=True)
        try:
            js = json.loads(r.stdout)
        except ValueError:
            js = None
        py = [[k, cl[k]["curve"] if cl[k] else None, [P.curve_view(cl[k]["curve"] if cl[k] else None, n) for n in nows]] for k, _ in cases]
        diff = [k for (k, a, b), (_, c, d) in zip(py, js or []) if a != c or b != d]
        check(js is not None and js == py and not diff,
              "node: MemebotRadar.cleanCurve and curveView give Python's clean_curve and curve_view for every block (calls, empty, off, on, list only, xss, hostile, none, "
              "one without a time, the night's kept block, lone surrogate halves) at the doc's time, an hour and three hours on (%s)" % (diff or ("same" if js else r.stderr[-300:])))
    # 5. the browser: the build's section and the script's are the same elements; 320, 390 and 1280 px, light and dark; the folds; a status moving on
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skips.append("the curve section's browser checks (no Playwright)")
        print("  SKIP the curve section's browser checks: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    d, _ = build_db(tmp, now, name="db-curve")
    lv = json.load(open(os.path.join(d, "radar_live.json")))
    lv["curve"] = curve_block(lv["t"], "calls")
    json.dump(lv, open(os.path.join(d, "radar_live.json"), "w"))
    page_html = page_of(d, now, repo=None)                  # no repository: no poll, the script draws the embedded doc only
    url = "https://some-owner.github.io/Meme-Bot/"
    out, errs = {}, []
    sd = shots                                              # the screenshots: curve-*.png beside the radar's own
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

        def open_(w, dark=False, js=True, clock=None):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme="dark" if dark else "light", java_script_enabled=js, service_workers="block")
            ctx.add_init_script("window.addEventListener('memebot-radar', e => { window.__rev = [e.detail.state, e.detail.good, e.detail.via]; });")
            ctx.route("**/*", lambda route: route.fulfill(status=200, body=page_html, headers={"Content-Type": "text/html; charset=utf-8"}) if route.request.url.split("#")[0] == url
                      else route.abort())
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            if clock:
                pg.clock.install(time=clock)
            pg.goto(url + "#tab-radar")
            if js:                                      # the section sits in the closed fold "Curve test (experiment)": opened as a reader would
                pg.evaluate("document.querySelectorAll('details.rcurvef').forEach(function(d){d.open=true;})")
            return ctx, pg
        ctx, pg = open_(390, js=False)
        out["nojs"] = pg.evaluate("document.querySelector('[data-r-curve]').innerHTML")
        ctx.close()
        for w, dark in ((320, False), (320, True), (390, False), (390, True), (1280, False), (1280, True)):
            ctx, pg = open_(w, dark)
            pg.wait_for_function("() => (window.__rev || [])[0] === 'running'", timeout=8000)
            pg.wait_for_timeout(300)
            info = pg.evaluate(CURVE_JS)
            out["%d %s" % (w, dark)] = info
            if sd:
                os.makedirs(sd, exist_ok=True)
                pg.locator("[data-r-curve]").screenshot(path=os.path.join(sd, "curve-%s-%d.png" % ("dark" if dark else "light", w)))
            if w == 390 and not dark:
                if sd:                                      # the section in its place on the New tab: under the radar's list, above the Track record
                    pg.locator("[data-radar]").screenshot(path=os.path.join(sd, "curve-in-radar-pane-light-390.png"))
                pg.click("details.rc-more > summary")
                pg.click("details.rc-by > summary")
                pg.wait_for_timeout(200)
                out["open"] = pg.evaluate(CURVE_JS)
                if sd:
                    pg.locator("[data-r-curve]").screenshot(path=os.path.join(sd, "curve-folds-open-light-390.png"))
            if w == 320 and not dark:
                pg.click("details.rc-more > summary")
                pg.click("details.rc-by > summary")
                pg.wait_for_timeout(200)
                out["open320"] = pg.evaluate(CURVE_JS)
            ctx.close()
        # the statuses move on with the doc's age (a fake clock an hour on): the section redraws, the open fold stays open
        ctx, pg = open_(390, clock=(lv["t"] + 20_000) / 1000.0)    # Playwright takes seconds
        pg.clock.run_for(3000)                    # the page's timers on the fake clock: its first draws
        pg.wait_for_timeout(300)
        pg.click("details.rc-more > summary")
        before = pg.evaluate(CURVE_JS)
        pg.clock.fast_forward(61 * 60_000)
        pg.clock.run_for(2000)
        pg.wait_for_timeout(300)
        after = pg.evaluate(CURVE_JS)
        ctx.close()
        # the other kinds through the script: off, switched on, a hostile symbol, an empty block, no block
        for kind in ("off", "on", "xss", "empty", "none"):
            lv2 = dict(lv)
            if kind == "none":
                lv2.pop("curve", None)
            else:
                lv2["curve"] = curve_block(lv["t"], kind)
            json.dump(lv2, open(os.path.join(d, "radar_live.json"), "w"))
            page_html = page_of(d, now, repo=None)
            ctx, pg = open_(390)
            pg.wait_for_function("() => (window.__rev || [])[0] === 'running'", timeout=8000)
            pg.wait_for_timeout(200)
            out[kind] = pg.evaluate(CURVE_JS)
            if sd and kind in ("off", "on", "empty") and not out[kind]["hidden"]:
                pg.locator("[data-r-curve]").screenshot(path=os.path.join(sd, "curve-%s-light-390.png" % kind))
            ctx.close()
        br.close()
    js390 = out["390 False"]
    wide = [out["%d %s" % (w, dk)] for w in (320, 390, 1280) for dk in (False, True)]
    check(js390["html"] == out["nojs"] and js390["cls"] == "rcurve" and not js390["hidden"] and js390["above"] and not errs,
          "browser: the script's section is the build's, element for element (the same innerHTML from the embedded doc), in the Curve test fold after the radar's other folds%s" % (
              "" if js390["html"] == out["nojs"] else " (differ at %d)" % next((i for i, (a, b) in enumerate(zip(js390["html"], out["nojs"])) if a != b), -1)))
    check(all(x["hscroll"] <= 0 and not x["small"] and x["inBox"] and x["tabFits"] for x in wide) and out["open320"]["hscroll"] <= 0 and out["open320"]["inBox"] and not out["open320"]["small"]
          and js390["syms"] == ["H2O", "TRAPPY", "STILL", "RISKY"] and out["open"]["more"] and len(out["open"]["syms"]) == 8 and all(x["imgs"] == 0 for x in wide)
          and all(a == [h, "_blank", "noopener noreferrer"] for a, h in zip(js390["links"], ["https://pump.fun/coin/" + c["mint"] for c in (P.curve_view(P.clean_curve(lv["curve"]), lv["t"])["coins"] + P.curve_view(P.clean_curve(lv["curve"]), lv["t"])["more"])])),
          "browser: at 320, 390 and 1280 px, light and dark, no sideways page scroll, the variant table fits its box (no scroll inside it either), every link "
          "and fold a 44 px tap target, four coins in view and four more in the fold, each coin a pump.fun link in a new tab; no image or script inside (%s)" % (
              [(x["small"], x["tabFits"]) for x in wide if x["small"] or not x["tabFits"]] or "ok"))
    check(all(not x["lowc"] for x in wide + [out["open"], out["open320"]]) and any("rc-s bad" in x["html"] for x in (out["open"],)),
          "browser: every text of the section's own (the status pills with 'dead' among them, the folds open) has a contrast of 4.5:1 or more, light and "
          "dark (%s)" % ([x["lowc"] for x in wide + [out["open"], out["open320"]] if x["lowc"]] or "all pass"))
    check(before["more"] and after["more"] and before["status"][2] == "rc-s live|still on the curve" and after["status"][2] == "rc-s muted|not watched to the end",
          "browser: an hour after a call the script redraws the section by the doc's age, and with no newer doc it says the watch did not see the hour end "
          "(still on the curve -> not watched to the end, never 'did not graduate'); an open fold stays open (%s -> %s)" % (before["status"][2], after["status"][2]))
    check(out["none"]["hidden"] and out["empty"]["cls"] == "rcurve one" and out["empty"]["text"].startswith("About to graduate (paper test): no call yet · Curve watch on")
          and "Curve watch off: rounds only" in out["off"]["text"] and out["on"]["pushCls"] == "rc-push on" and "Curve pushes are on for the 75% rising calls" in out["on"]["text"]
          and XSS_CURVE in out["xss"]["text"] and out["xss"]["imgs"] == 0 and "Curve watch limited: " + XSS_CURVE in out["xss"]["text"],
          "browser: no block hides the section, an empty one is one line, off says why, a switched-on push names its variant (amber), a hostile symbol and why "
          "show as text and add no element")


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
        src_checks(check, tmp, skips)
        curve_checks(check, tmp, skips, env.get("shots"))
        browser(check, tmp, d, skips, env.get("shots"))
    finally:
        if standin:
            sys.modules.pop("traps", None)
        shutil.rmtree(tmp, ignore_errors=True)
    return skips


def main():
    # alone as in selftest.main: the switch a month after the clock, so the new-launch checks see the page before it (the real switch,
    # 16 Oct 00:00 UTC, has passed; selftest.main sets the same)
    os.environ.setdefault("MEMEBOT_SWITCH_AT", str(int(time.time() * 1000) + 30 * 86_400_000))
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
