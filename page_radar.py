#!/usr/bin/env python3
"""page_radar.py: the launch radar on the Radar tab (its tab id stays tab-young), the trap-check line and the "no good coin" marks of the page. Fake
money only: nothing here buys, advises or links to a swap; green means "no trap found in N checks", never more.

report.py calls it in a few one-line hooks; everything the page shows of the launch radar lives here:

  block(D, mid)        the Radar tab's radar (until the switch the full scan's new launches follow it): its heading and pane(D, mid)
  pane(D, mid)         the radar: a shell the script RADAR_JS fills from the copy of radar.json embedded at build time
                       (mb/radar_live.json, whitelisted, at most 48 KB) and then from its polls (the live store's row "radar", else the
                       GitHub contents API on the branch radar-data inside the budget the office poll keeps, else raw.githubusercontent).
                       The script has no rule logic: every chip text comes from the doc (traps.chips, computed by the radar job).
  curve_section(doc)   in the Radar tab's last fold "Curve test (experiment)": "About to graduate (paper test)", the curve watch's block of radar.json (clean_curve): the newest
                       calls of coins still on pump.fun's curve (one row per coin: its curve %, minutes since the mint, market cap, quick check,
                       status now) and the variant table beside the radar's greens of the same hours; built here at the doc's time, redrawn by
                       the script (curveView) as the doc ages. A paper test: no push while radar_curve.json's switch is off, and it says so.
  young(D)             {address: rating} for the New launches rows: traps.rate(traps.signals_scan(row, mint, walletmem, now, pool)) at
                       page build, from recommend.json's young rows (now: the scan's time "t"), the mint and pool times in mb/pairs.json
                       (traps.pair_times: pf / ll createdAt, pairCreatedAt) and mb/walletmem.json.gz. Without pairs.json or the wallet
                       memory (or one older than 3 hours) the checks that need them are unknown, so no row can be green.
  row_chips, row_attr, young_head, card_trap, card_safety   the verdict chip, the one-row trap line, the red tint, the count heading,
                       the detail view, the card's old safety chip
  pick_banner(picks)   the banner over the pick when it is a fallback, risky or watch coin (weak keeps its own chip)
  CSS, JS              the styles (the tab, the line, the detail view) and RADAR_JS (window.MemebotRadar holds its decisions for the tests)

traps.py (the rule core) is imported only when it exists; a page built without it says "trap check unavailable" on every row.
"""
import gzip, html, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memebot as M

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)
try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Europe/Berlin")
    TZ_ID, TZ_NAME = "Europe/Berlin", "Berlin"
except Exception:          # no tz database: the page says UTC, as report.py does
    TZ_ID, TZ_NAME = "UTC", "UTC"

DOC_MAX = 48_000           # bytes: the embedded radar.json; over it "others" is trimmed first, then "recent", else nothing is embedded
WM_MAX_AGE = 3 * 3_600_000  # the wallet memory counts as checked for 3 hours after it was built (the radar job's rule, SPEC 3.2)
LINE_SHOWN = 4             # chips on the one-row trap line before "+N" (on a phone, up to 560 px: PHONE_SHOWN); a radar card shows CARD_SHOWN
PHONE_SHOWN = 2
CARD_SHOWN = 3
PHONE_LONG = 28            # a first chip longer than this (characters) is shown alone on a phone, so it stays whole
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
X_LINK = re.compile(r"^https://(www\.)?(x|twitter)\.com/[A-Za-z0-9_]{1,30}(/[A-Za-z0-9_/?=&%.-]{0,90})?$")
NAME = re.compile(r"^[A-Za-z0-9_.]{1,32}$")
HOST = re.compile(r"^[A-Za-z0-9.-][A-Za-z0-9. -]{0,23}$")     # the radar's host labels ("rugcheck", "pump.fun trades")
SRC = re.compile(r"^[a-z][A-Za-z0-9:_-]{0,23}$")               # a discovery list's name ("gt:new", "ll:llNew")
LEVELS = ("bad", "warn", "unk", "ok", "info")
ICON = {"bad": "✕", "warn": "!", "unk": "?", "ok": "✓", "info": "·"}
VERDICTS = ("good", "watch", "trap")
STATES = ("running", "degraded", "ending", "off", "hours", "done")     # done: a round is over (launch_radar.py round), its list stays until the next one
BANNER = "No good coin this scan: shown for the record, marked, not a recommendation"
LATER = ("5", "15", "30", "60")
PAT_ROWS = 3               # record.pat: at most 3 signals and 3 coins (launch_radar.pat_of keeps the same)
T3_MAX = 3                 # a coin's t3 (the learning trader's skip signs it has, launch_radar.t3_skips): at most this many words (SKIP_MAX is 2)

# words for a signal name (radar_weights.json, the rating's lists) when the doc's line does not carry its own text (the line has at most 8)
LABELS = {"instant_pool": "pool opened with the mint", "rugger_wallets": "holders from rugged coins", "brand_name": "brand/celebrity name",
          "bot_volume": "3,000+ buys already", "rc_danger": "RugCheck danger", "staircase10": "staircase chart", "no_socials": "no socials",
          "holder_cluster": "holder cluster", "creator_sold": "creator sold", "pumping_5m": "big rise in 5 min", "no_rc_report": "no RugCheck report",
          "young_5m": "pool under 5 min", "x_and_paid": "X link and DEX paid", "tweet": "launched off a tweet", "lists3": "on 3+ source lists",
          "dev_dead": "dev's earlier launches", "dev_young": "fresh dev wallet", "x_copied": "X account used by older coins",
          "tweet_shared": "coins off the same tweet", "sniped30": "sniped in the first 30 s", "bundle_slot": "wallets in the launch block",
          "fresh_holders": "fresh top holders", "fund_cluster": "top holders funded by one wallet", "staircase_early": "staircase so far",
          "chatty": "replies on pump.fun", "viral_tweet": "source tweet with 1,000+ likes",
          "rc_report": "RugCheck report", "mint_time": "mint time", "walletmem": "wallet memory",
          "x": "has an X link", "creator_5pct": "creator holds over 5%", "mc_500k": "market cap over $500k", "liq_15pct": "liquidity under 15% of market cap"}
UNKNOWN = {"rc_report": "RugCheck pending", "rcReport": "RugCheck pending", "no_rc_report": "RugCheck pending", "mint_time": "mint time unknown",
           "mintToPoolS": "mint time unknown", "instant_pool": "mint time unknown", "walletmem": "wallet memory unavailable",
           "wmChecked": "wallet memory unavailable", "rugger_wallets": "wallet memory unavailable", "brand_name": "name unknown", "bot_volume": "buys unknown"}
# the study's outcomes (radar_weights.json evidence rows) in words, for the why fold
OUTCOMES = {"rug1h": "rugged within 1 h", "rug2h": "rugged within 2 h", "rugAny": "rugged at any time", "win1h": "doubled within 1 h", "win2h": "doubled within 2 h"}
# the raw signal values (traps S keys) in words, for the Numbers tab
SKEYS = {"instantPool": "pool opened with the mint", "mintToPoolS": "mint to pool, seconds", "swAvg": "holders' past result per 20", "rugHolders": "holders from rugged coins",
         "wmChecked": "wallet memory checked", "brand": "brand or celebrity name", "buys": "buys so far", "rcReport": "RugCheck report", "rcDanger": "RugCheck danger",
         "rcWarn": "RugCheck warnings", "cluster": "holder cluster", "netSize": "insider network size", "creatorSold": "creator sold", "m5": "change in 5 min, %",
         "socN": "social links", "ageMin": "pool age, minutes", "x": "X link", "xKind": "X link kind", "paid": "DEX paid", "tweet": "X link is a tweet",
         "lists": "source lists", "stair": "staircase", "mc": "market cap", "liq": "liquidity", "creatorPct": "creator holds, %", "pumpswap": "PumpSwap pool",
         "devN": "dev's launches", "devDead": "dev's dead launches", "devGrad": "dev's graduated launches", "devAgeH": "dev wallet age, hours",
         "xUsed": "older coins with this X account", "tweetShared": "coins off the same tweet", "snip30": "supply sniped in 30 s, %", "snip30N": "sniper wallets",
         "slotN": "wallets in the launch block", "slotPct": "launch block share, %", "freshN": "fresh top holders", "fundN": "top holders with one funder",
         "replies": "replies on pump.fun", "tweetLikes": "likes of the source tweet"}
MEASURED_NOTE = "Measured, not weighted yet: it gets weight only when the radar's own records confirm it."
INFO_TEXT = ("The radar checks the newest pools every 2 minutes on its own during its hours (7 to 24 h Berlin unless changed), from the first full "
             "scan after they begin, and pump.fun graduations from a live feed when it is up: each run lasts about an hour and starts the next. Start "
             "and Stop open its page on GitHub. Start (only when it is stopped): tap \u201cRun workflow\u201d, the first list comes in about 4 minutes. Stop: "
             "the \u201c\u2026\u201d menu, then \u201cDisable workflow\u201d. Momentum and patterns: hindsight, paper only, never a push. Fake money: nothing is "
             "bought for real; the radar's coins without traps are bought on paper only.")


# ------------------------------------------------------------------------------------------------------------------ small helpers
def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _str(v, n):
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return ""
    return re.sub(r"[\x00-\x1f\x7f\u2028\u2029]", " ", str(v))[:n]


def _ms(v):
    v = _num(v)
    return v if v is not None and 0 <= v < 1e14 else None


def _names(v, n=20):
    return [x for x in v if isinstance(x, str) and NAME.match(x)][:n] if isinstance(v, list) else []


def _line(v):
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, (list, tuple)) and len(x) >= 2 and x[0] in LEVELS and isinstance(x[1], str) and x[1].strip():
            out.append([x[0], _str(x[1], 120)])
    return out[:12]


def _scalar(v):
    if v is None or isinstance(v, bool):
        return True, v
    if _num(v) is not None:
        return True, v
    if isinstance(v, str):
        return True, _str(v, 60)
    return False, None


def _dmap(v, depth=0):
    out = {}
    for k, x in (v.items() if isinstance(v, dict) else ()):
        if len(out) >= 60 or not isinstance(k, str) or not NAME.match(k):
            continue
        ok, s = _scalar(x)
        if ok:
            out[k] = s
        elif depth == 0 and isinstance(x, dict):
            sub = _dmap(x, 1)
            if sub:
                out[k] = sub
        elif depth == 0 and isinstance(x, list):
            vals = [y if _num(y) is not None else _str(y, 40) for y in x if _num(y) is not None or (isinstance(y, str) and y)][:16]
            if vals:
                out[k] = vals
    return out


def usd(v):
    v = _num(v)
    if v is None:
        return "?"
    a = abs(v)

    def f(x):
        t = "%.1f" % x
        return t[:-2] if t.endswith(".0") else t
    return "$" + (f(v / 1e9) + "B" if a >= 1e9 else f(v / 1e6) + "M" if a >= 1e6 else f(v / 1e3) + "k" if a >= 1e3 else "%.0f" % v)


def dur(mins):
    mins = _num(mins)
    if mins is None:
        return "?"
    mins = max(0.0, mins)
    return "%d min" % int(mins) if mins < 60 else "%d h" % int(mins / 60) if mins < 2880 else "%d days" % int(mins / 1440)


def pct(v):
    v = _num(v)
    return "?" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + "%d%%" % round(abs(v))


# ------------------------------------------------------------------------------------------------------------------ radar.json
def clean_coin(c, full=True):
    """One coin of radar.json through the whitelist (Appendix A): an address that is not base58 drops the coin, an X link that is not
    an x.com / twitter.com address is dropped, numbers must be finite, strings are cut."""
    if not isinstance(c, dict) or not isinstance(c.get("addr"), str) or not B58.match(c["addr"]):
        return None
    o = {"addr": c["addr"], "sym": _str(c.get("sym"), 24), "name": _str(c.get("name"), 48), "v": c.get("v") if c.get("v") in VERDICTS else "watch",
         "pts": _num(c.get("pts")), "age": _num(c.get("age")), "line": _line(c.get("line")), "liq": _num(c.get("liq")), "mc": _num(c.get("mc")),
         "n": _num(c.get("n")), "ws": int(c["ws"]) if _num(c.get("ws")) is not None and c["ws"] % 1 == 0 and -9 <= c["ws"] <= 9 else None}
    for k in ("hard", "soft", "unknown", "info", "plus"):
        o[k] = _names(c.get(k))
    if isinstance(c.get("pair"), str) and B58.match(c["pair"]):
        o["pair"] = c["pair"]
    if full:
        for k in ("pool", "mint", "first", "push"):
            o[k] = _ms(c.get(k))
        for k in ("px", "m5", "buys", "sells", "up"):
            o[k] = _num(c.get(k))
        o["dex"], o["lp"] = _str(c.get("dex"), 24), _str(c.get("lp"), 24)
        o["d"] = _dmap(c.get("d"))
        o["found"] = [_str(x, 24) for x in (c.get("found") or []) if isinstance(x, str)][:8] if isinstance(c.get("found"), list) else []
        pb = c.get("pb")             # bought on paper (radar_paper's rule 2): 1, else 0; only the whole numbers 0 and 1 pass
        o["pb"] = 1 if _num(pb) == 1 else 0
        o["t3"] = [_str(x, 60) for x in c.get("t3") if isinstance(x, str) and x.strip()][:T3_MAX] if isinstance(c.get("t3"), list) else []
    if isinstance(c.get("x"), str) and X_LINK.match(c["x"]):
        o["x"] = c["x"]
    return o


def _nums(v, keys):
    return {k: _num(v.get(k)) for k in keys} if isinstance(v, dict) else None


def _pat(p):
    """record.pat (winners vs losers of the same hours, launch_radar.pat_of) or None: rows [name, lk, ln, wk, wn, sure, lv, dir] with both
    groups known (ln, wn > 0), sure only a real true, an unknown level read as info, dir (matched by hour) -1, 0 or 1, else 0; coins [sym, t,
    hourW, [[name, k, known]]] with 0 <= k <= known; PAT_ROWS of each."""
    if not isinstance(p, dict):
        return None
    ok = lambda x: isinstance(x, list) and len(x) == 8 and isinstance(x[0], str) and NAME.match(x[0]) and all(_num(v) is not None for v in x[1:5]) and 0 <= x[1] <= x[2] and 0 <= x[3] <= x[4] and x[2] > 0 and x[4] > 0
    rows = [[x[0], x[1], x[2], x[3], x[4], x[5] is True, x[6] if x[6] in LEVELS else "info", int(x[7]) if _num(x[7]) in (-1, 0, 1) else 0]
            for x in (p.get("rows") if isinstance(p.get("rows"), list) else []) if ok(x)]
    kk = lambda s: isinstance(s, list) and len(s) == 3 and isinstance(s[0], str) and NAME.match(s[0]) and _num(s[1]) is not None and _num(s[2]) is not None and 0 <= s[1] <= s[2]
    why = [[_str(w[0], 24), _ms(w[1]), _num(w[2]), [[s[0], s[1], s[2]] for s in w[3] if kk(s)][:3]]
           for w in (p.get("why") if isinstance(p.get("why"), list) else []) if isinstance(w, list) and len(w) == 4 and isinstance(w[3], list)]
    return dict({"at": _ms(p.get("at")), "since": _ms(p.get("since")), "rows": rows[:PAT_ROWS], "why": why[:PAT_ROWS]}, **_nums(p, ("hrs", "w", "l", "need")))


def clean_doc(doc):
    """radar.json as the page may show it, or None: kind "radar" with a time, every key whitelisted (SPEC Appendix A), at most DOC_MAX
    bytes as JSON ("others" trimmed first, then "recent")."""
    if not isinstance(doc, dict) or doc.get("kind") != "radar" or _ms(doc.get("t")) is None:
        return None
    o = {"v": _num(doc.get("v")), "kind": "radar", "t": _ms(doc.get("t")), "next": _ms(doc.get("next")), "hourly": _ms(doc.get("hourly")),
         "state": doc.get("state") if doc.get("state") in STATES else "running", "why": _str(doc.get("why"), 200), "secs": _num(doc.get("secs"))}
    run = doc.get("run") if isinstance(doc.get("run"), dict) else {}
    o["run"] = {"id": _str(run.get("id"), 40), "start": _ms(run.get("start")), "end": _ms(run.get("end")), "cycle": _num(run.get("cycle")), "source": _str(run.get("source"), 12),
                "mode": run.get("mode") if run.get("mode") in ("round", "loop") else ""}
    md = doc.get("model") if isinstance(doc.get("model"), dict) else {}
    o["model"] = {"from": md.get("from") if md.get("from") in ("prior", "learned") else "prior", "n": _num(md.get("n")), "need": _num(md.get("need")),
                  "auc": _num(md.get("auc")), "prior": _num(md.get("prior")), "at": _ms(md.get("at")), "why": _str(md.get("why"), 200)}
    mw = md.get("win") if isinstance(md.get("win"), dict) else None      # the learned win order (hindsight; it only orders ties)
    o["model"]["win"] = {"from": "learned" if mw.get("from") == "learned" else "none", "n": _num(mw.get("n")), "auc": _num(mw.get("auc")), "why": _str(mw.get("why"), 120)} if mw else None
    cn = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    o["counts"] = {k: _num(cn.get(k)) for k in ("seen", "good", "pushed", "seenAgeMed")}
    wm = doc.get("wm") if isinstance(doc.get("wm"), dict) else {}
    o["wm"] = {"t": _ms(wm.get("t")), "nCoins": _num(wm.get("nCoins"))}
    o["coins"] = [x for x in (clean_coin(c) for c in (doc.get("coins") or [] if isinstance(doc.get("coins"), list) else [])) if x][:5]
    o["others"] = [x for x in (clean_coin(c, False) for c in (doc.get("others") or [] if isinstance(doc.get("others"), list) else [])) if x][:40]
    lg = doc.get("lastGood") if isinstance(doc.get("lastGood"), dict) else None
    o["lastGood"] = {"addr": lg["addr"], "sym": _str(lg.get("sym"), 24), "at": _ms(lg.get("at"))} if lg and isinstance(lg.get("addr"), str) and B58.match(lg["addr"]) else None
    rec = []
    for r in doc.get("recent") or [] if isinstance(doc.get("recent"), list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("addr"), str) or not B58.match(r["addr"]):
            continue
        lt = r.get("later") if isinstance(r.get("later"), dict) else {}
        out = r.get("out") if isinstance(r.get("out"), dict) else None
        pk = r.get("peak60") if isinstance(r.get("peak60"), dict) else None
        rec.append({"addr": r["addr"], "sym": _str(r.get("sym"), 24), "good": _ms(r.get("good")), "push": _ms(r.get("push")),
                    "later": {k: _num(lt.get(k)) for k in LATER}, "peak60": {"x": _num(pk.get("x")), "at": _ms(pk.get("at"))} if pk and _num(pk.get("x")) is not None else None,
                    "out": {"rug1h": out.get("rug1h") if isinstance(out.get("rug1h"), bool) else None, "win1h": out.get("win1h") if isinstance(out.get("win1h"), bool) else None,
                            "x60": _num(out.get("x60"))} if out else None, "miss60": r.get("miss60") is True})
    o["recent"] = rec[:40]
    rd = doc.get("record") if isinstance(doc.get("record"), dict) else None
    if rd:
        ci = rd.get("ci") if isinstance(rd.get("ci"), dict) else {}
        pair = lambda v: [_num(v[0]), _num(v[1])] if isinstance(v, list) and len(v) == 2 and _num(v[0]) is not None and _num(v[1]) is not None else None
        o["record"] = {"calls": _num(rd.get("calls")), "rug": _num(rd.get("rug")), "win": _num(rd.get("win")), "eur": _num(rd.get("eur")), "n60": _num(rd.get("n60")),
                       "ticket": _num(rd.get("ticket")), "ci": {"rug": pair(ci.get("rug")), "win": pair(ci.get("win"))}}
        o["record"].update(mom=_nums(rd.get("mom"), ("calls", "n60", "rug", "win")), all=_nums(rd.get("all"), ("n60", "rug", "win")), pat=_pat(rd.get("pat")),
                           known=_nums(rd.get("known"), ("n", "rug", "win")))     # the counts the push says (app.radar_record), the desk's chat too
    else:
        o["record"] = None
    hs = doc.get("hosts") if isinstance(doc.get("hosts"), dict) else {}
    o["hosts"] = {k: _str(v, 16) for k, v in list(hs.items())[:12] if isinstance(k, str) and HOST.match(k) and isinstance(v, str)}
    o["notes"] = [_str(x, 160) for x in (doc.get("notes") or []) if isinstance(x, str)][:8] if isinstance(doc.get("notes"), list) else []
    o["lines"] = [_str(x, 200) for x in (doc.get("lines") or []) if isinstance(x, str)][:12] if isinstance(doc.get("lines"), list) else []
    sr = doc.get("src") if isinstance(doc.get("src"), dict) else {}      # the round's discovery counts (the office desk's Sources)
    o["src"] = {k: int(v) for k, v in list(sr.items())[:12] if isinstance(k, str) and SRC.match(k) and _num(v) is not None and v == int(v) and 0 <= v <= 100_000}
    try:                                 # the curve watch's paper test (About to graduate); a block it cannot read is left out, never the doc
        o["curve"] = clean_curve(doc.get("curve"))
    except Exception:
        o["curve"] = None
    size = lambda: len(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    while size() > DOC_MAX and o["others"]:
        o["others"].pop()
    while size() > DOC_MAX and o["recent"]:
        o["recent"].pop()
    while size() > DOC_MAX and o["curve"] and o["curve"]["recent"]:
        o["curve"]["recent"].pop()
    return o if size() <= DOC_MAX else None


def embed_json(doc):
    """JSON for a <script type="application/json"> block: nothing in it can close the block or open a comment."""
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ------------------------------------------------------------------------------------------------------------------ the curve watch (paper test)
# radar.json's "curve" block (launch_radar.curve_doc, curve_watch.Book.doc): pump.fun coins called on paper while they are still on their bonding
# curve, before any pool, at 60, 75 and 90 % of it sold, each judged an hour later beside the radar's greens of the same hours. The Radar tab shows
# it under the radar's list as "About to graduate (paper test)": the newest calls by coin and the variant table. The two whitelists (clean_curve,
# MemebotRadar.cleanCurve) and the two views (curve_view, MemebotRadar.curveView) give the same: a string with CURVE_CTRL as spaces, cut in UTF-16
# units without a half emoji and CURVE_BLANK trimmed (the office chat's rule: page_office.CHAT_CTRL / CHAT_BLANK, here with the zero-width and
# word-joiner marks too), numbers printed with whole-number arithmetic only (no rounding mode of either language decides a digit). Hindsight on
# paper: the section never calls a coin a buy, it reports what each call did an hour later.
CURVE_THR = (60, 75, 90)    # the marks of the curve sold (curve_watch.THRESHOLDS)
CURVE_V = ("ok", "risky", "trap", "unknown")       # the quick check's verdicts before any pool (curve_watch.VERDICTS), in the table's order
CURVE_VW = {"ok": ("ok", "no trap found yet"), "risky": ("warn", "risky"), "trap": ("bad", "trap"), "unknown": ("unk", "not fully checked")}   # level, words
CURVE_HOW = ("pool", "curve", "gone", "dead")      # how a call's 1 h value was read (curve_watch.Book.set_value)
CURVE_STATES = ("on", "limited", "off")
CURVE_HOSTS = ("pump.fun", "trades")               # the block's hosts: pump.fun's curve list, the followed coins' trades on the live feed
CURVE_ID = re.compile(r"(60|75|90)m?")             # a variant id (curve_watch.variant_of): the mark, m for the momentum filter (fullmatch)
CURVE_HST = re.compile(r"[a-z]{1,12}")             # a host state: ok, limited, down, unused, off, waiting, silent, refused, unavailable (fullmatch)
CURVE_CTRL = r"\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff"
CURVE_BLANK = r"\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
CURVE_RECENT = 10           # calls in the block (curve_watch.RECENT_N)
CURVE_SHOWN = 4             # coins in view before the "N more coins" fold
CURVE_LINE = 4              # chips on a coin's one-row line (its verdict and up to 3 of its call's chips; a phone shows PHONE_SHOWN and "+N")
CURVE_FEW = 20              # calls with a 1 h value before a row's shares tell anything (the Track record's TOO_FEW): fewer are grey
CURVE_VALUE_MS = 3_600_000  # a call is judged at call + 60 min (curve_watch.VALUE_MS): a coin the watch saw on its curve that long "did not
                            # graduate"; one whose hour the watch did not see to the end (the block's own time is earlier) says so
CURVE_LATE_S = 90           # s a quick check may come after a call made without one and still count for it (curve_watch.LATE_MS)
CURVE_BIG = 1e9             # a number the section prints is under this, else it is unknown
_CC, _CB = re.compile("[%s]" % CURVE_CTRL), re.compile("^[{0}]+|[{0}]+\\Z".format(CURVE_BLANK))
_CS = re.compile("[\ud800-\udbff][\udc00-\udfff]|[\ud800-\udfff]")     # a surrogate pair (kept) or a lone half (a space: it has no character)


def _cstr(v, n):
    """A chain string of the curve block as both whitelists keep it: CURVE_CTRL and a lone surrogate half (a JSON escape a backend cut in
    two: it cannot be encoded, and would cost the whole doc) as spaces, cut to n UTF-16 units (the script's slice) without a half emoji at
    the end, CURVE_BLANK off both ends; '' for anything but a string."""
    if not isinstance(v, str):
        return ""
    u = _CS.sub(lambda m: m.group(0) if len(m.group(0)) == 2 else " ", _CC.sub(" ", v)).encode("utf-16-le", "surrogatepass")[:2 * n]
    return _CB.sub("", re.sub("[\ud800-\udbff]\\Z", "", u.decode("utf-16-le", "surrogatepass")))


def _cchips(v):
    """A call's chips ([[level, text]], traps.chips' words for the quick check) as the page keeps them: a known level, a text, at most 3."""
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, list) and len(x) >= 2 and x[0] in LEVELS and isinstance(x[1], str):
            s = _cstr(x[1], 60)
            if s:
                out.append([x[0], s])
    return out[:3]


def _crec(r):
    """One call of the block's recent list, or None without a base58 mint, a mark of 60, 75 or 90 and a time."""
    if not isinstance(r, dict) or not isinstance(r.get("mint"), str) or not B58.fullmatch(r["mint"]) or r.get("thr") not in CURVE_THR or _ms(r.get("t")) is None:
        return None
    o = r.get("out") if isinstance(r.get("out"), dict) else {}
    b = lambda d, k: d[k] if isinstance(d.get(k), bool) else None
    return dict({"mint": r["mint"], "sym": _cstr(r.get("sym"), 24), "thr": r["thr"], "t": _ms(r["t"])}, **{k: _num(r.get(k)) for k in ("prog", "mcu", "mcs", "age", "pts", "buys", "sells")},
                mom=b(r, "mom"), v=r["v"] if r.get("v") in CURVE_V else "unknown", chips=_cchips(r.get("chips")), push=_ms(r.get("push")),
                out={"grad": _ms(o.get("grad")), "gradMin": _num(o.get("gradMin")), "x60": _num(o.get("x60")), "peak": _num(o.get("peak")), "rug": b(o, "rug"),
                     "x2": b(o, "x2"), "eur": _num(o.get("eur")), "how": o["how"] if o.get("how") in CURVE_HOW else "", "miss": o.get("miss") is True,
                     "done": o.get("done") is True})


def _cvar(r):
    """One row of the variant table (its id decides the mark and the momentum filter), with its split by the quick check, or None."""
    if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not CURVE_ID.fullmatch(r["id"]):
        return None
    by = r.get("by") if isinstance(r.get("by"), dict) else {}
    return dict({"id": r["id"], "thr": int(r["id"][:2]), "mom": r["id"].endswith("m")}, **{k: _num(r.get(k)) for k in ("n", "nS", "rug", "x2", "eur", "grad", "gradMin", "miss", "unseen")},
                by={v: {k: _num(by[v].get(k)) for k in ("n", "nS", "rug", "x2", "eur")} for v in CURVE_V if isinstance(by.get(v), dict)})


def clean_curve(cv):
    """radar.json's "curve" block as the page may show it, or None without a time: the watch's state and why, its counts, its two hosts, the
    push switch (a variant id or None), the calibration, the greens of the same hours, the newest CURVE_RECENT calls and the six variants."""
    if not isinstance(cv, dict) or _ms(cv.get("t")) is None:
        return None
    nums = lambda d, ks: {k: _num(d.get(k)) for k in ks}
    hs = cv.get("hosts") if isinstance(cv.get("hosts"), dict) else {}
    ps = cv.get("push") if isinstance(cv.get("push"), dict) else {}
    lst = lambda k: cv[k] if isinstance(cv.get(k), list) else []
    o = dict({"v": _num(cv.get("v")), "t": _ms(cv["t"]), "state": cv["state"] if cv.get("state") in CURVE_STATES else "off", "why": _cstr(cv.get("why"), 160),
              "since": _ms(cv.get("since"))}, **nums(cv, ("hours", "ticket", "slip", "momPts", "calls", "late", "follow", "cand", "trades", "polls", "sol")))
    o["thresholds"] = [x for x in lst("thresholds") if x in CURVE_THR][:3]
    o["hosts"] = {k: hs[k] for k in CURVE_HOSTS if isinstance(hs.get(k), str) and CURVE_HST.fullmatch(hs[k])}
    o["push"] = {"variant": ps["variant"] if isinstance(ps.get("variant"), str) and CURVE_ID.fullmatch(ps["variant"]) else None,
                 "verdicts": [x for x in (ps["verdicts"] if isinstance(ps.get("verdicts"), list) else []) if x in ("ok", "risky", "unknown")][:3],
                 "perH": _num(ps.get("perH")), "sent1h": _num(ps.get("sent1h"))}
    o["calib"] = nums(cv["calib"], ("n", "mcSol", "prog", "scale", "expect")) if isinstance(cv.get("calib"), dict) else None
    o["greens"] = nums(cv["greens"], ("n", "nS", "rug", "x2", "eur", "grad")) if isinstance(cv.get("greens"), dict) else None
    o["recent"] = [x for x in (_crec(r) for r in lst("recent")) if x][:CURVE_RECENT]
    o["variants"] = [x for x in (_cvar(r) for r in lst("variants")) if x][:6]
    return o


def _cint(v):
    """A count the section prints (0 to CURVE_BIG, whole), else None."""
    v = _num(v)
    return int(math.floor(v)) if v is not None and 0 <= v < CURVE_BIG else None


def _cpct(v):
    """A share 0..1 as a whole percent, half up ('40%'), else '–'."""
    v = _num(v)
    return "%d%%" % math.floor(100 * v + 0.5) if v is not None and 0 <= v <= 1 else "–"


def _cmoney(v, sign=True, unit=True):
    """Euros in cents, half up: '+0.42 €', '−1.20 €' (a sign only when it is not 0.00), or without one '3 €' / '2.50 €'; without the unit
    (a table's cells, its head names it) '+0.42'; '–' unknown."""
    v = _num(v)
    if v is None or abs(v) >= CURVE_BIG:
        return "–"
    c = int(math.floor(abs(v) * 100 + 0.5))
    return (("−" if v < 0 else "+") if sign and c else "") + ("%d" % (c // 100) if not sign and c % 100 == 0 else "%d.%02d" % (c // 100, c % 100)) + ("\u00a0€" if unit else "")


def _cx(v):
    """A multiple of the call price: '0.42x', '2.30x', '14x'; '–' unknown."""
    v = _num(v)
    if v is None or not 0 <= v < CURVE_BIG:
        return "–"
    if v >= 10:
        return "%dx" % math.floor(v + 0.5)
    c = int(math.floor(v * 100 + 0.5))
    return "%d.%02dx" % (c // 100, c % 100)


def _cusd(v):
    """A market cap in dollars: $850, $58k, $1.2M (half up, in whole units); '' unknown."""
    v = _num(v)
    if v is None or not 0 <= v < 1e12:
        return ""
    d, k = math.floor(v + 0.5), math.floor(v / 1e3 + 0.5)
    if d < 1000:
        return "$%d" % d
    if k < 1000:
        return "$%dk" % k
    m = int(math.floor(v / 1e5 + 0.5))
    return "$%d.%dM" % (m // 10, m % 10) if m % 10 else "$%dM" % (m // 10)


def _cage(a):
    """Minutes from the mint to the call: '14 min after mint', '1 h 12 min after mint', 'under 1 min after mint', 'mint time unknown'."""
    a = _num(a)
    if a is None or not 0 <= a < CURVE_BIG:
        return "mint time unknown"
    m = int(math.floor(a))
    if m < 1:
        return "under 1 min after mint"
    if m < 60:
        return "%d min after mint" % m
    if m < 2880:
        return ("%d h %d min" % (m // 60, m % 60) if m % 60 else "%d h" % (m // 60)) + " after mint"
    return "%d days after mint" % (m // 1440)


def _cand(xs):
    """'60', '60 and 75', '60, 75 and 90'."""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _cvlabel(vid):
    """A variant's name: '75%', or '75% rising' with the momentum filter."""
    return vid[:2] + "%" + (" rising" if vid.endswith("m") else "")


def _cstatus(o, t, now, seen=None):
    """Where a called coin stands now, by what the watch saw (seen: the block's own time, its last word): graduated (after N min, or when is
    not known), dead (the curve sold back, or no coin and no pair), did not graduate (valued on its curve at the hour, or the watch saw the
    hour pass), not watched to the end (no value, or the hour ended after the block's time: the radar stopped, say at night) or still on
    the curve; [class, words]."""
    if o["grad"] is not None:
        gm = o["gradMin"]
        if gm is None or not 0 <= gm < CURVE_BIG:
            return ["grad", "graduated"]
        m = int(math.floor(gm + 0.5))
        return ["grad", "graduated within a minute" if m < 1 else "graduated after %d min" % m]
    if o.get("done"):
        return ["grad", "graduated"]
    if o["how"] in ("dead", "gone"):
        return ["bad", "dead"]
    if o["x60"] is not None:
        return ["muted", "did not graduate"]
    seen = now if seen is None else min(now, seen)
    if not o["miss"] and seen - t >= CURVE_VALUE_MS:
        return ["muted", "did not graduate"]
    if o["miss"] or now - t >= CURVE_VALUE_MS:
        return ["muted", "not watched to the end"]
    return ["live", "still on the curve"]


def _cresult(o):
    """The call's hour on paper, once known: rugged, doubled, the multiple at 1 h, or no value; None while it is pending."""
    if o["rug"] is True:
        return ["bad", "doubled, then rugged in 1 h" if o["x2"] is True else "rugged in 1 h"]
    if o["x2"] is True:
        return ["good", "doubled in 1 h"]
    if o["x60"] is not None:
        return ["", "1 h: " + _cx(o["x60"])]
    if o["miss"]:
        return ["muted", "no 1 h value"]
    return None


def _crow(label, s, extra, greens=False):
    """One row of a table: label, then the cells of extra (graduated, or the quick check), calls first in the main table; title in words."""
    n, ns = _cint(s.get("n")), _cint(s.get("nS"))
    few = ns is None or ns < CURVE_FEW
    bits = (["%d %s%s" % (n, "coin" if greens else "call", "" if n == 1 else "s")] if n is not None else []) + (["%d with a 1 h value" % ns] if ns is not None else [])
    gm, miss, uns = _num(s.get("gradMin")), _cint(s.get("miss")), _cint(s.get("unseen"))
    if gm is not None and 0 <= gm < CURVE_BIG:
        bits.append("graduated a median %d min after the call" % math.floor(gm + 0.5))
    if miss:
        bits.append("%d without a 1 h value" % miss)
    if uns:
        bits.append("%d whose hour nobody saw (not in graduated)" % uns)
    cells = [label] + extra(n) + [_cpct(s.get("rug")), _cpct(s.get("x2")), _cmoney(s.get("eur"), True, False)]
    return {"cls": " ".join(x for x in ("rc-g" if greens else "", "few" if few else "") if x), "cells": cells,
            "title": ("the radar's green coins first rated in the same hours, judged 1 h later by the same rules: " if greens else "") + ", ".join(bits)}


def curve_view(cv, now):
    """What the Radar tab shows of a curve block (clean_curve's) at the time now (ms; the script: the doc's time plus its age), the same as the
    script's MemebotRadar.curveView: None without a block; {state, head, one: True} for a block without a call (one line); else the head line,
    the paper test's sentence and the push switch's, the coins of the newest calls (one per coin: its newest call, the marks it was called at,
    its status now and its hour's result; CURVE_SHOWN in view, the rest in a fold), the variant table with the greens' row, its split by the
    quick check and the footnote. Every text is plain (the page escapes it, the script sets it as text)."""
    if not isinstance(cv, dict):
        return None
    st = cv.get("state") if cv.get("state") in CURVE_STATES else "off"
    fol, hrs, calls, late = (_cint(cv.get(k)) for k in ("follow", "hours", "calls", "late"))
    head = "Curve watch " + st
    if st == "on":                       # on with a why: the list only, its normal mode (no coin followed on the feed)
        head += "".join(" · " + b for b in (["%d coin%s followed" % (fol, "" if fol == 1 else "s")] if fol else []) + ([cv["why"]] if cv.get("why") else [])
                        + (["%d h watched" % hrs] if hrs else []))
    elif cv.get("why"):
        head += ": " + cv["why"]
    recent = cv.get("recent") if isinstance(cv.get("recent"), list) else []
    if not recent and not calls:
        return {"state": st, "head": head, "one": True}
    tk, sl, mp = _num(cv.get("ticket")), _num(cv.get("slip")), _num(cv.get("momPts"))
    tks = _cmoney(tk if tk is not None and 0 < tk < 1e6 else 3.0, False)
    sl = sl if sl is not None and 0 <= sl < 1 else 0.05
    mp = mp if mp is not None and 0 < mp <= 100 else 10.0
    thr = ["%d" % x for x in (cv.get("thresholds") or CURVE_THR)]
    note = ("Paper test: the radar calls pump.fun coins still on their bonding curve, before the pool opens, at %s%% of the curve sold, to find out "
            "whether an earlier call helps. Each call is judged 1 h later with %s on paper and %d%% slippage, beside the radar's greens of the same hours."
            % (_cand(thr), tks, math.floor(100 * sl + 0.5)))
    ps = cv.get("push") if isinstance(cv.get("push"), dict) else {}
    var = ps.get("variant") if isinstance(ps.get("variant"), str) and CURVE_ID.fullmatch(ps["variant"]) else None
    if var:
        vs, ph = [CURVE_VW[v][1] for v in ps.get("verdicts") or [] if v in CURVE_VW], _cint(ps.get("perH"))
        push = "Curve pushes are on for the %s calls%s%s." % (_cvlabel(var), " (quick check: %s)" % " or ".join(vs) if vs else "", ", at most %d an hour" % ph if ph is not None else "")
    else:
        push = "No curve push goes out while the switch is off."
    groups = []
    for r in recent:
        g = next((x for x in groups if x["r"]["mint"] == r["mint"]), None)
        if g is None:
            groups.append({"r": r, "thr": [r["thr"]]})
            continue
        if r["thr"] not in g["thr"]:
            g["thr"].append(r["thr"])
        if r["t"] > g["r"]["t"]:
            g["r"] = r
    groups.sort(key=lambda g: -g["r"]["t"])
    coins = []
    for g in groups:
        r, o = g["r"], g["r"]["out"]
        p, s = _num(r.get("prog")), _num(r.get("mcs"))
        mc = _cusd(r.get("mcu")) or ("%d SOL" % math.floor(s + 0.5) if s is not None and 0 <= s < CURVE_BIG else "unknown")
        vw = CURVE_VW.get(r["v"]) or CURVE_VW["unknown"]
        nums = [_cage(r.get("age")), "market cap " + mc, "called at %s%%" % _cand(["%d" % x for x in sorted(g["thr"])])] + (["sent to the phone"] if r.get("push") else [])
        coins.append({"mint": r["mint"], "sym": r.get("sym") or "?", "prog": "%d%%" % math.floor(p + 0.5) if p is not None and 0 <= p <= 100 else "?",
                      "nums": " · ".join(nums), "line": [[vw[0], vw[1]]] + [[x[0], x[1]] for x in r.get("chips") or []], "st": _cstatus(o, r["t"], now, _ms(cv.get("t"))),
                      "res": _cresult(o)})
    count = lambda n: ["%d" % n if n is not None else "–"]
    rows = [_crow(_cvlabel(v["id"]), v, lambda n, v=v: count(n) + [_cpct(v.get("grad"))]) for v in cv.get("variants") or []]
    if isinstance(cv.get("greens"), dict):
        rows.append(_crow("radar greens", cv["greens"], lambda n: count(n) + ["–"], True))
    by = [_crow(_cvlabel(v["id"]), b, lambda n, k=k: [CURVE_VW[k][1]] + count(n)) for v in cv.get("variants") or [] for k, b in ((k, v["by"].get(k)) for k in CURVE_V)
          if isinstance(b, dict) and _cint(b.get("n"))]
    foot = ["Rising: %d or more points of the curve in the 5 minutes before the call, and more purchases than sales." % math.floor(mp + 0.5),
            "Without the coin's trades (pump.fun's list only) the points alone count.",
            "Rugged, doubled and paper: of the calls with a 1 h value; graduated: of the calls an hour old whose hour was seen. Rugged: gone, dead or "
            "worth 0.1x or less at 1 h; doubled: 2x to 30x within the hour and not gone or dead at 1 h; the greens by the same rules. Quick check: as "
            "known at the call, or the first one within %d s after it (then counted from that moment's price). Grey: under %d calls with a 1 h value, "
            "too few to tell." % (CURVE_LATE_S, CURVE_FEW)]
    if late:
        foot.append("%d time%s a trading coin was first seen already past a mark, so no call was made." % (late, "" if late == 1 else "s"))
    cb = cv.get("calib") if isinstance(cv.get("calib"), dict) else {}
    cn, cp = _cint(cb.get("n")), _num(cb.get("prog"))
    if cn and cp is not None and 0 <= cp < 1000:
        foot.append("Progress check: at the last trade before %d graduation%s the curve read %d%% sold (about 100%% is right)." % (cn, "" if cn == 1 else "s", math.floor(cp + 0.5)))
    return {"state": st, "head": head, "one": False, "note": note, "push": push, "pushOn": bool(var), "coins": coins[:CURVE_SHOWN], "more": coins[CURVE_SHOWN:],
            "ticket": tks, "rows": rows, "by": by, "foot": " ".join(foot)}


def _ctable(head, rows):
    th = "".join("<th>%s</th>" % E(x) for x in head)
    trs = "".join('<tr%s title="%s">%s</tr>' % (' class="%s"' % r["cls"] if r["cls"] else "", E(r["title"]), "".join("<td>%s</td>" % E(x) for x in r["cells"])) for r in rows)
    return '<div class="rrec-w"><table class="rc-tab"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, trs)


def _ccoin(c):
    st, res = c["st"], c["res"]
    return ('<li class="rc-coin"><a class="rc-top" href="https://pump.fun/coin/%s" target="_blank" rel="noopener noreferrer"><span class="rc-sym">%s</span>'
            '<span class="rc-p">%s</span><span class="rc-s%s">%s</span></a><p class="rc-n">%s</p>%s%s</li>') % (
        E(c["mint"]), E(c["sym"]), E(c["prog"]), " " + st[0] if st[0] else "", E(st[1]), E(c["nums"]), line_html(c["line"], CURVE_LINE),
        '<p class="rc-r%s">%s</p>' % (" " + res[0] if res[0] else "", E(res[1])) if res else "")


def curve_inner(v):
    """The section's content for a view (curve_view's); the script builds the same elements (MemebotRadar's curve redraw)."""
    st = '<p class="rc-st" data-st="%s"><i class="rdot"></i><span>%s</span></p>' % (E(v["state"]), E(v["head"]))
    if v["one"]:
        return '<p class="rc-one"><b>About to graduate (paper test):</b> no call yet · %s</p>' % E(v["head"])
    h = '<div class="rc-h"><h3>About to graduate <small>(paper test)</small></h3>%s</div><p class="rc-note">%s</p><p class="rc-push%s">%s</p>' % (
        st, E(v["note"]), " on" if v["pushOn"] else "", E(v["push"]))
    if v["coins"]:
        h += '<ol class="rc-list">%s</ol>' % "".join(_ccoin(c) for c in v["coins"])
    if v["more"]:
        h += '<details class="rc-more" data-cf="more"><summary>%d more coin%s</summary><ol class="rc-list">%s</ol></details>' % (
            len(v["more"]), "" if len(v["more"]) == 1 else "s", "".join(_ccoin(c) for c in v["more"]))
    if v["rows"]:
        h += _ctable(["", "calls", "graduated", "rugged in 1 h", "doubled in 1 h", "paper per " + v["ticket"]], v["rows"])
    h += '<p class="tnote">%s</p>' % E(v["foot"])
    if v["by"]:
        h += '<details class="rc-by" data-cf="by"><summary>Split by the quick check</summary>%s</details>' % _ctable(
            ["", "quick check", "calls", "rugged in 1 h", "doubled in 1 h", "paper per " + v["ticket"]], v["by"])
    return h


def curve_section(doc):
    """The curve watch's section on the Radar tab under the radar's list (pane), from the doc's curve block at the doc's time; hidden without
    one. The script redraws it from every doc it takes (data-r-curve), its statuses moving on with the doc's age."""
    cv = doc.get("curve") if isinstance(doc, dict) else None
    v = curve_view(cv, _num(doc.get("t")) or 0) if isinstance(cv, dict) else None
    return '<section class="rcurve%s" data-r-curve aria-label="About to graduate, paper test"%s>%s</section>' % (
        " one" if v and v["one"] else "", "" if v else " hidden", curve_inner(v) if v else "")


# ------------------------------------------------------------------------------------------------------------------ data
def traps_mod():
    try:
        import traps as T
        return T
    except Exception:
        return None


def load_weights_file():
    try:
        with open(os.path.join(HERE, "radar_weights.json"), encoding="utf-8") as f:
            w = json.load(f)
        return w if isinstance(w, dict) else None
    except (OSError, ValueError):
        return None


def load_wm(d, ref):
    """mb/walletmem.json.gz (traps.feed, imported by the scan) or None: missing, unreadable, or built more than 3 hours before ref."""
    try:
        with gzip.open(os.path.join(d, "walletmem.json.gz"), "rt", encoding="utf-8") as f:
            wm = json.load(f)
    except Exception:
        return None
    if not isinstance(wm, dict):
        return None
    t = _ms(wm.get("t"))
    if ref and (t is None or ref - t > WM_MAX_AGE):
        return None
    return wm


def _pair_times(p):
    """(mint ms, pool ms) of one mb/pairs.json entry, as traps.pair_times reads it: the mint from pump.fun or LaunchLab createdAt, the
    pool from DexScreener's pairCreatedAt."""
    mint = M.parse_ms((p.get("pf") or {}).get("createdAt")) if isinstance(p.get("pf"), dict) else None
    if not mint and isinstance(p.get("ll"), dict):
        mint = M.parse_ms(p["ll"].get("createdAt"))
    pool = _num(p.get("pairCreatedAt"))
    return mint or None, (pool if pool and pool > 1e12 else None)


def load_times(d, addrs, T=None):
    """{address: (mint ms, pool ms)} from mb/pairs.json for the given addresses (traps.pair_times when the rule core has it). A coin
    that is in pairs.json gets an entry even when both times are unknown."""
    out, want = {}, set(addrs)
    try:
        with open(os.path.join(d, "pairs.json"), encoding="utf-8") as f:
            pairs = json.load(f)
    except (OSError, ValueError):
        return out
    pt = getattr(T, "pair_times", None) or _pair_times
    for p in pairs if isinstance(pairs, list) else []:
        a = p.get("address") if isinstance(p, dict) else None
        if a in want:
            try:
                mint, pool = pt(p)
            except Exception:
                mint, pool = None, None
            out[a] = (_num(mint) or None, _num(pool) or None)
    return out


def rating_of(T, W, y, times, wm, now):
    """One young row rated by the rule core; the page keeps the verdict, the lists, the chip line and the raw values. times: the row's
    (mint, pool) from mb/pairs.json, or None when pairs.json does not have the coin; now: the scan's time (recommend.json "t"). With
    no pool time the rule core counts the pool from now minus the row's age (f.ageH); but when pairs.json has the coin without a
    pool time, memebot measured that age from the mint (feats: pump.fun createdAt), so it is left out: the mint-to-pool gap stays
    unknown instead of reading as a pool opened with the mint."""
    mint, pool = times or (None, None)
    if times is not None and pool is None and isinstance(y.get("f"), dict) and "ageH" in y["f"]:
        y = dict(y, f={k: v for k, v in y["f"].items() if k != "ageH"})
    S = T.signals_scan(y, mint, wm, now=now, pool=pool)
    r = T.rate(S, W)
    line = _line(T.chips(r, S))
    keep = {k: v for k, v in (S or {}).items() if isinstance(k, str) and NAME.match(k)} if isinstance(S, dict) else {}
    for k, v in list(keep.items()):          # a link in the raw values is shown only when it is an x.com / twitter.com address
        if isinstance(v, str) and re.match(r"^\s*[A-Za-z][A-Za-z0-9+.-]*:", v) and not X_LINK.match(v):
            keep[k] = "not an x.com link"
    return {"v": r.get("verdict") if r.get("verdict") in VERDICTS else "watch", "n": _num(r.get("n")), "pts": _num(r.get("pts")),
            "hard": _names(r.get("hard")), "soft": _names(r.get("soft")), "unknown": _names(r.get("unknown")), "plus": _names(r.get("plus")),
            "info": _names(r.get("info")), "line": line, "S": _dmap(keep), "mint": mint, "pool": pool}


def data(D):
    """Everything the radar parts of the page need, read once per page and kept in D["_radar"]: the whitelisted radar doc, the
    young rows' ratings and the study weights for the why fold."""
    if isinstance(D.get("_radar"), dict):
        return D["_radar"]
    d, rec = D.get("dir"), D.get("rec") if isinstance(D.get("rec"), dict) else {}
    out = {"doc": None, "young": {}, "weights": load_weights_file(), "traps": False}
    if d:
        try:
            with open(os.path.join(d, "radar_live.json"), encoding="utf-8") as f:
                out["doc"] = clean_doc(json.load(f))
        except (OSError, ValueError):
            out["doc"] = None
    young = [c for c in (rec.get("young") or []) if isinstance(c, dict) and c.get("addr")]
    T = traps_mod()
    out["traps"] = T is not None
    if out["weights"] is None and T is not None:
        try:
            out["weights"] = T.load_weights()
        except Exception:
            out["weights"] = None
    if young:
        if T is None:
            out["young"] = {c["addr"]: None for c in young}
        else:
            ref = M.num(rec.get("t")) or M.num(D.get("now"))
            wm = load_wm(d, ref) if d else None
            times = load_times(d, [c["addr"] for c in young], T) if d else {}
            try:
                W = T.load_weights()
            except Exception:
                W = None
            for c in young:
                try:
                    out["young"][c["addr"]] = rating_of(T, W, c, times.get(c["addr"]), wm, ref) if W is not None else None
                except Exception:
                    out["young"][c["addr"]] = None        # a row the rule core could not rate says so; it is never green
    D["_radar"] = out
    return out


def young(D):
    return data(D)["young"]


# ------------------------------------------------------------------------------------------------------------------ the line and the chips
def verdict_text(rt):
    if not rt:
        return "", "? trap check unavailable"
    v = rt.get("v")
    if v == "good":
        n = _num(rt.get("n"))
        return "good", "✓ No trap found" + (" · %d checks" % n if n else "")
    if v == "trap":
        k = len(rt.get("hard") or [])
        return "bad", "✕ trap" if k <= 1 else "✕ %d traps" % k
    if rt.get("unknown"):
        return "warn", "? not fully checked"
    k = len(rt.get("soft") or [])
    return "warn", "! %d warnings" % k if k > 1 else "! not good yet"


def verdict_chip(rt):
    cls, text = verdict_text(rt)
    return '<span class="chip tv%s">%s</span>' % ((" " + cls) if cls else "", E(text))


def line_html(line, shown=LINE_SHOWN):
    """The trap-check line: one row, the first chips (red flags first, as traps.chips orders them), "+N" for the rest; every text in
    the title."""
    line = _line(line)
    if not line:
        return ""
    k = min(len(line), shown)
    ph = 1 if len(line[0][1]) > PHONE_LONG else PHONE_SHOWN
    chips = "".join('<span class="tc %s%s"><b aria-hidden="true">%s</b>%s</span>' % (lv, " x2" if i >= ph else "", ICON[lv], E(t)) for i, (lv, t) in enumerate(line[:k]))
    if len(line) > k:
        chips += '<span class="tc more m4">+%d</span>' % (len(line) - k)
    if len(line) > ph:
        chips += '<span class="tc more m2">+%d</span>' % (len(line) - ph)
    return '<div class="tline" title="%s">%s</div>' % (E(" · ".join(t for _, t in line)), chips)


def row_chips(rt):
    """The verdict chip and the trap line for one New launches row (they go first in the row's chips)."""
    if not rt:
        return verdict_chip(None)
    return verdict_chip(rt) + line_html(rt.get("line"))


def row_safety(rt, chip):
    """The row's old safety chip: a clean one goes when the trap line is there (its RugCheck check says it, and "clean" beside a trap
    reads wrong); a flagged one stays."""
    return "" if rt and 'class="chip"' in chip and "flagged" not in chip else chip


def card_safety(c, chip):
    """A New launches card's old safety chip beside its trap block: as on the row (row_safety); any other card keeps it."""
    return row_safety(c.get("_trap"), chip) if c.get("tier") == "young" and "_trap" in c else chip


def row_attr(rt):
    return ' class="trap"' if rt and rt.get("v") == "trap" else ""


def young_head(ratings, rows):
    """The count line over the New launches table: how many rows passed every check and how many did not (or could not be checked)."""
    rts = [ratings.get(c.get("addr")) for c in rows if isinstance(c, dict)]
    if not rts:
        return ""
    good = sum(1 for r in rts if r and r.get("v") == "good")
    return ('<p class="tsum"><span class="chip%s">%d without traps</span><span class="chip%s">%d with traps or unchecked</span>'
            '<small class="tbuy">paper buys follow the old rule: the trap check does not stop them (fake money)</small></p>' % (
        " good" if good else "", good, " bad" if len(rts) - good else "", len(rts) - good))


def label(name, level):
    if level == "unk":
        return UNKNOWN.get(name) or LABELS.get(name, name.replace("_", " ")) + " not checked"
    return LABELS.get(name, name.replace("_", " "))


GROUPS = (("bad", "Red flags", "hard"), ("warn", "Warnings", "soft"), ("unk", "Not checked", "unknown"), ("ok", "Passed", None), ("info", "Measured, not weighted yet", "info"))


def groups(rt):
    """The Trap check tab: the line's texts by level, and for the names the line had no room for, their words."""
    out = []
    line = _line(rt.get("line"))
    for lv, title, key in GROUPS:
        tx = [t for l_, t in line if l_ == lv]
        names = rt.get(key) or [] if key else []
        tx += [label(n, lv) for n in names[len(tx):]]
        if tx:
            out.append((lv, title, tx))
    return out


def fmt_val(v):
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return ("%d" % v) if float(v).is_integer() and abs(v) < 1e15 else ("%.3g" % v)
    if isinstance(v, list):
        return ", ".join(fmt_val(x) for x in v[:6]) + (" …" if len(v) > 6 else "")
    if isinstance(v, dict):
        return " · ".join("%s %s" % (k, fmt_val(x)) for k, x in list(v.items())[:5])
    return str(v)


def dtabs_html(uid, parts, default=1):
    """CSS-radio sub-tabs (no script needed): parts [(label, inner html)]; the tab `default` is open first."""
    radios = "".join('<input type="radio" name="%s" id="%s-%d"%s>' % (uid, uid, i, " checked" if i == default else "") for i in range(len(parts)))
    bar = "".join('<label for="%s-%d">%s</label>' % (uid, i, E(t)) for i, (t, _) in enumerate(parts))
    panes = "".join('<div class="dpane">%s</div>' % inner for _, inner in parts)
    return '<div class="dtabs">%s<div class="dtabbar" role="tablist">%s</div><div class="dpanes">%s</div></div>' % (radios, bar, panes)


def trap_pane(rt):
    gs = groups(rt)
    if not gs:
        return '<p class="note">No check result.</p>'
    out = []
    for lv, title, tx in gs:
        items = "".join('<li class="tc %s"><b aria-hidden="true">%s</b>%s</li>' % (lv, ICON[lv], E(t)) for t in tx)
        note = '<p class="tnote">%s</p>' % E(MEASURED_NOTE) if lv == "info" else ""
        out.append('<div class="tgrp %s"><h5>%s <span>%d</span></h5><ul>%s</ul>%s</div>' % (lv, E(title), len(tx), items, note))
    return "".join(out)


def kv_pane(rows):
    rows = [(k, v) for k, v in rows if v not in (None, "")]
    if not rows:
        return '<p class="note">No numbers.</p>'
    return '<div class="dkv">%s</div>' % "".join('<div><span class="k">%s</span><span class="v">%s</span></div>' % (E(k), E(v)) for k, v in rows)


def card_trap(c, now=None):
    """The trap block of a New launches card (rec_card, young tier): the verdict chip, the line, and on tap the detail view (Overview,
    Trap check, Numbers) with CSS-radio sub-tabs, so it works without a script."""
    if c.get("tier") != "young" or "_trap" not in c:
        return ""
    rt = c.get("_trap")
    head = '<div class="ttrap">%s%s</div>' % (verdict_chip(rt), line_html((rt or {}).get("line")))
    if not rt:
        return head
    f = c.get("f") if isinstance(c.get("f"), dict) else {}
    ref = M.num(now)
    mint = _num(rt.get("mint"))
    up, zp = M.num(c.get("upP")), M.num(c.get("zeroP"))
    ov = [("pool age", dur(M.num(c.get("ageMin")))), ("minted", (dur((ref - mint) / 60000) + " ago") if mint and ref else "mint time unknown"),
          ("liquidity", usd(c.get("liq"))), ("market cap", usd(c.get("mc"))), ("change in 5 min", pct(M.num(f.get("m5"))) if M.num(f.get("m5")) is not None else None),
          ("buys, last hour", ("%d" % M.num(f.get("buys1"))) if M.num(f.get("buys1")) is not None else None),
          ("trained odds (info only)", ("%s profit · %s zero" % (pct(100 * up).lstrip("+"), pct(100 * zp).lstrip("+") if zp is not None else "?")) if up is not None else None)]
    odds_note = '<p class="tnote">Trained odds are not used here: on coins under 1 h they did not separate winners.</p>' if up is not None else ""
    nums = [(SKEYS.get(k, k), fmt_val(v)) for k, v in sorted((rt.get("S") or {}).items())]
    uid = "ty-" + re.sub(r"[^A-Za-z0-9]", "", str(c.get("addr") or ""))[:16]
    det = dtabs_html(uid, [("Overview", kv_pane(ov) + odds_note), ("Trap check", trap_pane(rt)), ("Numbers", kv_pane(nums))])
    return head + '<details class="tdet"><summary>Trap check details</summary>%s</details>' % det


def pick_banner(picks):
    """The banner over the pick when no good coin made it: amber for a fallback, red for a risky or watch coin; weak and strong get none."""
    tiers = {c.get("tier") for c in picks or [] if isinstance(c, dict)}
    if not tiers & {"fallback", "risky", "watch"}:
        return ""
    cls = "bad" if tiers & {"risky", "watch"} else "warn"
    return '<p class="nogood %s" role="note"><b aria-hidden="true">%s</b><span>%s</span></p>' % (cls, ICON["bad"] if cls == "bad" else "!", E(BANNER))


# ------------------------------------------------------------------------------------------------------------------ the radar on the Radar tab
def _ev_row(e):
    """The headline row of one evidence entry of radar_weights.json ({label, rows: [{cohort, outcome, with, without, n, lift, lo, hi,
    verdict, ...}]}): the listed new launches (cohort L) and a rug outcome first, a row whose verdict holds first, then the biggest n.
    A flat entry with those keys counts as its own row. None when no row has both rates."""
    if not isinstance(e, dict):
        return None
    rows = e.get("rows") if isinstance(e.get("rows"), list) else [e]
    rows = [r for r in rows if isinstance(r, dict) and _num(r.get("with")) is not None and _num(r.get("without")) is not None]
    if not rows:
        return None
    return max(rows, key=lambda r: (r.get("cohort") == "L", str(r.get("outcome") or "").startswith("rug"),
                                    str(r.get("verdict") or "").lower().startswith("holds"), _num(r.get("n")) or 0))


def _ev_text(e):
    """One evidence entry in words: "rugged within 1 h: 60% with it, 13% without · 4.6x (95%: 3.5-6.4) · 397 coins"; "" without one."""
    r = _ev_row(e)
    if not r:
        return ""
    rate = lambda v: "%d%%" % round(100 * v if v <= 1 else v)
    oc = OUTCOMES.get(str(r.get("outcome") or "")) or re.sub(r"^rug\b", "rugged", re.sub(r"^win\b", "doubled", _str(r.get("outcome"), 30))) or "rugged"
    bits = ["%s: %s with it, %s without" % (oc, rate(r["with"]), rate(r["without"]))]
    lift, lo, hi = _num(r.get("lift")), _num(r.get("lo")), _num(r.get("hi"))
    if lift is not None:
        bits.append("%.2gx" % lift + (" (95%%: %.2g-%.2g)" % (lo, hi) if lo is not None and hi is not None else ""))
    if _num(r.get("n")) is not None:
        bits.append("%d coins" % r["n"])
    return " · ".join(bits)


def _zero_list(zero):
    """The weight-0 list of radar_weights.json ([{signal, label, reason, note, rows}], or {name: reason}) as [(reason, [labels])]."""
    items = []
    if isinstance(zero, dict):
        items = [(k, v) for k, v in zero.items()]
    elif isinstance(zero, list):
        for z in zero:
            if isinstance(z, dict):
                nm = z.get("label") or z.get("signal") or z.get("name")
                items.append((nm, z.get("reason") or z.get("why") or ""))
            elif isinstance(z, (list, tuple)) and z:
                items.append((z[0], z[1] if len(z) > 1 else ""))
            elif isinstance(z, str):
                items.append((z, ""))
    by = {}
    for nm, why in items:
        nm = _str(nm, 60).strip()
        if nm:
            by.setdefault(_str(why, 40).strip() or "no effect", []).append(LABELS.get(nm, nm.replace("_", " ")))
    return list(by.items())


def why_fold(W):
    """The "Why these checks?" fold: what decides (traps, warnings) with the study's evidence (radar_weights.json), what got weight 0 and
    why, what is only measured."""
    notes = ('<ul class="rwhy-notes"><li>Green means no trap found in the checks that ran. A check that could not run (RugCheck pending, mint time or wallet memory unknown) blocks the green.</li>'
             '<li>The dev history, snipers, bundles, fresh wallets, funding clusters, copied X links, pump.fun replies and the source tweet\'s likes are measured and shown grey. They get weight only when the radar\'s own records confirm them.</li>'
             '<li>Coins still on the bonding curve are not rated here: the curve watch calls them on paper only (About to graduate), with no push while its switch is off. Later prices and the 1-hour peak are measured on the pool the radar saw.</li>'
             '<li>Fake money: nothing is bought for real; the radar\'s coins without traps are bought on paper only.</li></ul>')
    body = ""
    if isinstance(W, dict):
        ev = W.get("evidence")
        evd = ev if isinstance(ev, dict) else {str(x.get("name") or x.get("sig") or x.get("signal") or i): x for i, x in enumerate(ev)} if isinstance(ev, list) and all(isinstance(x, dict) for x in ev) else {}
        pts = W.get("points") if isinstance(W.get("points"), dict) else {}
        for kind, cls, names, what in (("trap", "bad", W.get("hard"), "Traps: one is enough, the coin is never green"),
                                       ("warning", "warn", W.get("soft"), "Warnings: two or more block the green")):
            items = []
            for nme in _names(names, 30):
                p = _num(pts.get(nme))
                ev_t = _ev_text(evd.get(nme))
                items.append('<li><span class="rw-n">%s</span><span class="chip %s">%s</span>%s</li>' % (
                    E(LABELS.get(nme, nme.replace("_", " "))), cls, E(kind + (" · %g pt" % p if p is not None else "")), ('<small>%s</small>' % E(ev_t)) if ev_t else ""))
            if items:
                body += '<h5 class="rw-h">%s</h5><ul class="rwhy-list">%s</ul>' % (E(what), "".join(items))
        zl = _zero_list(W.get("zero"))
        if zl:
            body += '<p class="note"><strong>Weight 0</strong> (did not hold up in our data): %s.</p>' % E("; ".join(
                "%s: %s" % (why, ", ".join(nms)) for why, nms in zl))
        src = _str(W.get("src"), 40)
        if src:
            body += '<p class="note">Weights: %s. Each rate is the share of coins that rugged with and without the sign, in the study.</p>' % E(src)
    else:
        body = '<p class="note">The study weights are not in this build.</p>'
    return ('<details class="rfold rwhy"><summary><span class="t">Why these checks?</span></summary><div class="rfold-in">'
            '<p class="note rmodel" data-r-model></p>%s%s</div></details>') % (body, notes)


def pane(D, mid=""):
    """The radar on the Radar tab. RADAR_JS fills it from the embedded copy and the polls; without a script it says one line. mid (HTML: the radar's
    paper positions, page_traders.radar_positions) sits under the cards, above the folds: Seen, Radar record, Why these checks?, Curve test. The
    HTML is the same with and without GITHUB_REPOSITORY: the script finds the repository in the office's live view box (GitHub poll, raw copy,
    Start and Stop links)."""
    rd = data(D)
    doc = rd["doc"]
    tk = M.num(((D.get("traders") or {}).get("tickets") or {}).get("radar")) if isinstance(D.get("traders"), dict) else None
    attrs = ' data-tz="%s" data-tzn="%s" data-paper="%s"' % (TZ_ID, TZ_NAME, E("Bought on paper · " + M.eur_text(tk if tk else 10.0)))
    embed = '<script type="application/json" id="radar-doc">%s</script>' % embed_json(doc) if doc else ""
    if doc:
        good = sum(1 for c in doc["coins"] if c.get("v") == "good")
        ns = "The radar list needs JavaScript. Last check %s %s: %d coin%s without traps." % (_hhmm(doc["t"]), TZ_NAME, good, "" if good == 1 else "s")
    else:
        ns = "The radar list needs JavaScript. No radar check is in this build yet."
    actions = '<div class="ractions" data-r-actions hidden></div>'
    curve = ('<details class="rfold rcurvef"><summary><span class="t">Curve test (experiment)</span><span class="sum">coins called on paper while still on '
             'pump.fun\'s curve, before their pool opens</span></summary><div class="rfold-in">%s<p class="note rc-none">No curve call in this radar check.</p></div></details>') % curve_section(doc)
    return ('<section class="radar" data-radar%s>%s<noscript><p class="note">%s</p></noscript>'
            '<div class="rhead"><p class="rpill" data-r-pill><i class="rdot"></i><span data-r-pill-t>Launch radar</span></p>%s</div>'
            '<div class="rstats" data-r-stats hidden></div><ul class="rnotes" data-r-notes hidden></ul>'
            '<ol class="rcards" data-r-cards></ol>'
            '<div class="rempty" data-r-empty hidden><p class="rbig" data-r-empty-t></p><p class="rsub" data-r-empty-s></p><p class="rsub" data-r-lastgood hidden></p></div>%s'
            '<details class="rfold" data-r-others hidden><summary><span class="t">Seen, with traps or not fully checked</span> <span class="cnt" data-r-ocnt></span></summary><ol class="rrows" data-r-olist></ol></details>'
            '<details class="rfold" data-r-rec hidden><summary><span class="t">Radar record</span><span class="sum" data-r-recline></span></summary><div class="rfold-in" data-r-recent></div></details>'
            '%s%s</section>') % (attrs, embed, E(ns), actions, mid, why_fold(rd["weights"]), curve)


def _hhmm(ms):
    import datetime as dt
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    if TZ_ID != "UTC":
        from zoneinfo import ZoneInfo
        t = t.astimezone(ZoneInfo(TZ_ID))
    return t.strftime("%H:%M")


def tab_label():
    """The radar's count on the website's Radar tab label, its one number: the coins without traps while the radar's list is current (RADAR_JS
    sets it; hidden at 0)."""
    return '<span class="cnt" data-r-tabcnt title="Radar: coins without traps now" hidden></span>'


def block(D, mid=""):
    """The Radar tab's radar (until the switch the full scan's new launches follow it): a heading and the pane, mid (the paper positions) inside."""
    return ('<section class="rsec"><div class="sec-head"><h2>Launch radar <span class="h2s">pools under 10 min</span></h2></div>%s</section>' % pane(D, mid))


# ------------------------------------------------------------------------------------------------------------------ styles
CSS = r"""
/* the launch radar (page_radar.py) on top of the Radar tab; the trap-check line, the verdict chip and the detail view (also on the full
   scan's new launches and the pick); the "no good coin" banner. Page tokens only, so light and dark both work. */
.rsec .sec-head h2 .h2s { font-size:var(--fs-s); font-weight:400; color:var(--muted); margin-left:4px; white-space:nowrap }
.tabbar .cnt.good { background:color-mix(in srgb,var(--good-mark) 18%,var(--surface)); color:var(--good) }
.tsum .tbuy { flex:1 1 100%; color:var(--muted); font-size:var(--fs-s) }
.tline { display:flex; flex-wrap:nowrap; gap:4px; min-width:0; max-width:100%; overflow:hidden; flex:1 1 100%; contain:inline-size }   /* its chips never widen a table column */
.tc { display:inline-flex; align-items:center; gap:4px; flex:0 1 auto; min-width:2.6em; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;
  font-size:var(--fs-xs); line-height:1.4; padding:2px 8px 2px 6px; border-radius:999px; background:var(--chip); color:var(--fg2) }
.tc b { flex:none; font-weight:700; min-width:1em; text-align:center }
/* the one-row line: the first chip (the worst finding) stays whole and gives way only after the others have shrunk to a stub (their
   shrink factor is so much larger that the first one's share stays under a layout unit, so no stray ellipsis); "+N" never shrinks */
.tline .tc { display:block; flex:0 100000 auto; min-width:3.2em } .tline .tc:first-child { flex:0 1 auto; min-width:0; max-width:100% }
.tline .tc b { display:inline-block; margin-right:3px }
.tc.bad { background:color-mix(in srgb,var(--bad-mark) 15%,var(--surface)); color:var(--bad) }
.tc.warn { background:color-mix(in srgb,var(--warn-mark) 17%,var(--surface)); color:var(--warn) }
.tc.unk { background:var(--chip); color:var(--fg2); box-shadow:inset 0 0 0 1px var(--line) }
.tc.ok { background:color-mix(in srgb,var(--good-mark) 13%,var(--surface)); color:var(--good) }
.tc.info { background:none; color:var(--muted); box-shadow:inset 0 0 0 1px var(--line2) }
.tline .tc.more { flex:none; min-width:0; background:none; color:var(--muted); padding-inline:4px }
.tline .tc.m2 { display:none }
@media (max-width:560px) { .tline .tc.x2, .tline .tc.m4 { display:none } .tline .tc.m2 { display:inline-block } }
.radar [hidden], .tdet [hidden] { display:none !important }
.chip.tv { font-weight:600 }
.tsum { display:flex; flex-wrap:wrap; gap:6px; margin:0 }
.tbl tr.trap { background:color-mix(in srgb,var(--bad-mark) 7%,var(--surface)) } .tbl tr.trap > td:first-child { box-shadow:inset 3px 0 0 var(--bad-mark) }
@media (max-width:560px) { .stack tr.trap { box-shadow:inset 3px 0 0 var(--bad-mark) } .stack tr.trap > td:first-child { box-shadow:none } }
.ttrap { display:grid; gap:6px; min-width:0 } .ttrap .chip { justify-self:start }
details.tdet > summary { color:var(--accent); font-weight:500; min-height:44px; display:flex; align-items:center }
.dtabs { display:grid; gap:10px; margin-top:8px; min-width:0 } .dtabs > input { position:absolute; opacity:0; pointer-events:none }
.dtabbar { display:flex; gap:4px; flex-wrap:wrap; border-bottom:1px solid var(--line2); padding-bottom:6px }
.dtabbar label { cursor:pointer; padding:5px 10px; border-radius:999px; font-size:var(--fs-s); font-weight:500; color:var(--fg2); min-height:44px; display:inline-flex; align-items:center }
.dtabbar label:hover { color:var(--fg) }
.dpane { display:none; min-width:0 }
.dtabs > input:nth-of-type(1):checked ~ .dpanes > .dpane:nth-child(1), .dtabs > input:nth-of-type(2):checked ~ .dpanes > .dpane:nth-child(2),
.dtabs > input:nth-of-type(3):checked ~ .dpanes > .dpane:nth-child(3), .dtabs > input:nth-of-type(4):checked ~ .dpanes > .dpane:nth-child(4) { display:grid; gap:10px }
.dtabs > input:nth-of-type(1):checked ~ .dtabbar > label:nth-child(1), .dtabs > input:nth-of-type(2):checked ~ .dtabbar > label:nth-child(2),
.dtabs > input:nth-of-type(3):checked ~ .dtabbar > label:nth-child(3), .dtabs > input:nth-of-type(4):checked ~ .dtabbar > label:nth-child(4) { color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,var(--surface)) }
.dtabs > input:nth-of-type(1):focus-visible ~ .dtabbar > label:nth-child(1), .dtabs > input:nth-of-type(2):focus-visible ~ .dtabbar > label:nth-child(2),
.dtabs > input:nth-of-type(3):focus-visible ~ .dtabbar > label:nth-child(3), .dtabs > input:nth-of-type(4):focus-visible ~ .dtabbar > label:nth-child(4) { outline:2px solid var(--accent); outline-offset:2px }
.tgrp h5 { margin:0 0 4px; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:600 } .tgrp h5 span { font-weight:400 }
.tgrp.bad h5 { color:var(--bad) } .tgrp.warn h5 { color:var(--warn) }
.tgrp ul { list-style:none; margin:0; padding:0; display:flex; flex-wrap:wrap; gap:4px } .tgrp li.tc { white-space:normal; overflow-wrap:anywhere; min-width:0 }
.tnote { margin:4px 0 0; font-size:var(--fs-xs); color:var(--muted) }
.dkv { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:6px 12px } .dkv div { display:grid; min-width:0 }
.dkv .k { font-size:var(--fs-xs); color:var(--muted) } .dkv .v { font-weight:500; font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.nogood { margin:0; display:flex; gap:10px; align-items:flex-start; padding:10px 14px; border-radius:8px; font-weight:500; font-size:var(--fs-m) }
.nogood b { flex:none; width:22px; height:22px; border-radius:50%; display:inline-grid; place-items:center; font-size:12px; color:#fff }
.nogood.warn { background:color-mix(in srgb,var(--warn-mark) 15%,var(--surface)); color:var(--warn); border:1px solid color-mix(in srgb,var(--warn-mark) 45%,var(--line)) } .nogood.warn b { background:var(--warn-mark) }
.nogood.bad { background:color-mix(in srgb,var(--bad-mark) 12%,var(--surface)); color:var(--bad); border:1px solid color-mix(in srgb,var(--bad-mark) 45%,var(--line)) } .nogood.bad b { background:var(--bad-mark) }
/* the radar on the Radar tab */
.radar { display:grid; gap:14px; min-width:0 }
.rhead { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; justify-content:space-between; position:relative }
.rpill { margin:0; display:inline-flex; align-items:center; gap:8px; min-height:36px; padding:6px 14px; border-radius:999px; background:var(--surface); border:1px solid var(--line);
  font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums; min-width:0; max-width:100% }
.rpill span { min-width:0; overflow-wrap:anywhere }
.rdot { flex:none; width:9px; height:9px; border-radius:50%; background:var(--muted) }
.rpill[data-st="running"] .rdot { background:var(--good-mark); animation:rpulse 2s ease-in-out infinite } .rpill[data-st="late"] .rdot { background:var(--warn-mark) }
.rpill[data-st="stopped"] .rdot { background:var(--bad-mark) } .rpill[data-st="running"], .rpill[data-st="done"] { color:var(--fg) }
.rpill[data-st="done"] .rdot { background:var(--good-mark) } .rpill[data-st="done"][data-err] .rdot { background:var(--warn-mark) }
.rpill[data-wait] { color:var(--fg) } .rpill[data-wait] .rdot { background:var(--good-mark); animation:rpulse 2s ease-in-out infinite }
@keyframes rpulse { 50% { opacity:.35 } }
.ractions { display:flex; align-items:center; gap:8px }
.rbtn { display:inline-flex; align-items:center; min-height:44px; padding:0 16px; border-radius:999px; background:var(--accent); color:#fff; font-weight:500; font-size:var(--fs-s) }
.rbtn.quiet { background:var(--chip); color:var(--fg); border:1px solid var(--line) } .rbtn:hover, .rbtn:focus-visible { text-decoration:none; filter:brightness(1.08) }
details.rinfo > summary { list-style:none; width:44px; height:44px; display:grid; place-items:center; border-radius:50%; color:var(--muted); font-size:18px; cursor:pointer }
details.rinfo > summary::-webkit-details-marker { display:none }
details.rinfo[open] > p { position:absolute; right:0; top:calc(100% + 6px); z-index:5; width:min(320px,100%); box-sizing:border-box; margin:0; padding:10px 12px; border-radius:8px;
  background:var(--surface); border:1px solid var(--line); box-shadow:0 6px 24px rgba(0,0,0,.14); font-size:var(--fs-s); color:var(--fg2) }
.rstats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); background:var(--surface); border:1px solid var(--line); border-radius:8px }
.rstats > div { padding:10px 12px; display:grid; gap:2px; min-width:0 } .rstats > div + div { border-left:1px solid var(--line2) }
.rstats b { font-size:24px; font-weight:600; line-height:1.1; font-variant-numeric:tabular-nums } .rstats span { font-size:var(--fs-xs); color:var(--muted); line-height:1.3 }
.rstats .good b { color:var(--good) } .rstats.dim { border-style:dashed }   /* an old round's numbers: a dashed frame, never faded text */
.rnotes { list-style:none; margin:0; padding:0; display:flex; flex-wrap:wrap; gap:6px } .rnotes li { font-size:var(--fs-xs); padding:3px 10px; border-radius:999px;
  background:color-mix(in srgb,var(--warn-mark) 15%,var(--surface)); color:var(--warn); overflow-wrap:anywhere; max-width:100% }
.rcards { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:minmax(0,1fr); gap:10px }
@media (min-width:760px) { .rcards { grid-template-columns:repeat(2,minmax(0,1fr)) } }
.rcard { background:var(--surface); border:1px solid color-mix(in srgb,var(--good-mark) 40%,var(--line)); border-radius:10px; min-width:0; display:grid }
.rcard.dim { border-color:var(--line); border-style:dashed } .rcard.dim .chip.tv { background:var(--chip); color:var(--fg2) }
.rcard > details > summary { list-style:none; cursor:pointer; padding:12px 14px 10px; display:grid; gap:6px; min-width:0; color:var(--fg) }
.rcard > details > summary::-webkit-details-marker { display:none }
.rcard > details[open] > summary { border-bottom:1px solid var(--line2) } .rcard > details > .dtabs { padding:0 14px 12px }
.rtop { display:flex; align-items:baseline; gap:4px 8px; flex-wrap:wrap; min-width:0 }
.rsym { font-size:18px; font-weight:600; max-width:60%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.rname { color:var(--fg2); font-size:var(--fs-s); flex:1 1 60px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.rage { width:100%; font-size:var(--fs-s); color:var(--fg2); font-variant-numeric:tabular-nums }
.rnums { display:flex; flex-wrap:wrap; gap:2px 14px; font-size:var(--fs-s); font-variant-numeric:tabular-nums } .rnums span { white-space:nowrap } .rnums i { font-style:normal; color:var(--muted); margin-right:4px }
.rchips { display:flex; flex-wrap:wrap; gap:6px; align-items:center }
.rmore { font-size:var(--fs-xs); color:var(--accent) } .rcard > details[open] .rmore { display:none }
.rpaper { margin:0; font-size:var(--fs-s); font-weight:600; color:var(--fg) } .rchips .chip.t3 { white-space:normal }
/* the curve test inside its fold: the block without its own frame; the one line when the doc has no curve block */
.rcurvef .rcurve { border:0; padding:0; background:none } .rcurvef [data-r-curve]:not([hidden]) ~ .rc-none { display:none }
.rfoot { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:0 14px 12px }
.rfoot a { display:inline-flex; align-items:center; justify-content:center; min-height:44px; min-width:44px; padding:0 12px; border:1px solid var(--line); border-radius:999px;
  font-size:var(--fs-s); font-weight:500; color:var(--accent); background:var(--surface) } .rfoot a:hover, .rfoot a:focus-visible { text-decoration:none; border-color:var(--accent) }
.rfoot .rpush { font-size:var(--fs-xs); color:var(--muted); margin-left:auto }
.rempty { background:var(--surface); border:1px dashed var(--line); border-radius:10px; padding:18px 16px; display:grid; gap:6px; text-align:center }
.rempty .rbig { margin:0; font-size:22px; font-weight:600; color:var(--fg); text-wrap:balance } .rempty .rsub { margin:0; font-size:var(--fs-s); color:var(--fg2); text-wrap:pretty }
details.rfold { background:var(--surface); border:1px solid var(--line); border-radius:8px; min-width:0 }
details.rfold > summary { list-style:none; cursor:pointer; padding:12px 14px; display:flex; flex-wrap:wrap; gap:2px 10px; align-items:baseline; min-height:44px; color:var(--fg) }
details.rfold > summary::-webkit-details-marker { display:none }
details.rfold > summary::before { content:"\203a"; color:var(--muted); display:inline-block; transition:transform .15s; margin-right:2px } details.rfold[open] > summary::before { transform:rotate(90deg) }
details.rfold > summary .t { font-weight:600 } details.rfold > summary .sum { flex-basis:100%; font-size:var(--fs-s); color:var(--fg2); text-wrap:pretty }
details.rfold > summary .cnt { font-size:var(--fs-xs); background:var(--chip); color:var(--fg2); border-radius:999px; padding:1px 8px }
.rfold-in { padding:0 14px 14px; display:grid; gap:10px; min-width:0 }
.rrows { list-style:none; margin:0; padding:0 14px 12px; display:grid; gap:6px }
.rrow { display:grid; grid-template-columns:auto minmax(0,1fr); gap:2px 8px; align-items:center; padding:8px 10px; border-radius:8px; min-width:0 }
.rrow.bad { background:color-mix(in srgb,var(--bad-mark) 8%,var(--surface)); box-shadow:inset 3px 0 0 var(--bad-mark) }
.rrow.warn { background:color-mix(in srgb,var(--warn-mark) 9%,var(--surface)); box-shadow:inset 3px 0 0 var(--warn-mark) }
.rrow .rs { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .rrow .ra { font-size:var(--fs-xs); color:var(--fg2); justify-self:end; white-space:nowrap }
.rrow .tline { grid-column:1 / -1 }
.rrec-w { overflow-x:auto; min-width:0 } .rrec { width:100%; border-collapse:collapse; font-size:var(--fs-s); font-variant-numeric:tabular-nums } .rrec th, .rrec td { padding:6px 6px; border-top:1px solid var(--line2); text-align:right; white-space:nowrap }
.rrec th { border-top:0 } .rrec td:nth-child(2), .rrec th:nth-child(2), .rrec td:first-child, .rrec th:first-child { text-align:left } .rrec td:nth-child(2) { max-width:9ch; overflow:hidden; text-overflow:ellipsis; font-weight:600 } .rrec-w .tnote { margin-top:6px }
.mx.up { color:var(--good) } .mx.dn { color:var(--bad) } .mx.na { color:var(--muted) } .rrec .oc.bad { color:var(--bad) } .rrec .oc.good { color:var(--good) } .rrec .oc.muted, .rrec .oc.na { color:var(--muted) }
/* the Track record's momentum line and patterns (hindsight, paper only): the signal's chip takes what the two % columns leave, cut with an ellipsis */
.rpat { width:100%; border-collapse:collapse; font-size:var(--fs-s); font-variant-numeric:tabular-nums } .rpat th, .rpat td { padding:4px 6px; border-top:1px solid var(--line2); text-align:right; white-space:nowrap }
.rpat th { border-top:0; font-size:var(--fs-xs); font-weight:500; color:var(--muted) } .rpat td:first-child { text-align:left; max-width:0; width:100%; padding-left:0 } .rpat .tc { display:inline-block; max-width:100%; vertical-align:middle }
.rpat .tc b { display:inline-block; margin-right:3px } .rpat tr.maybe td { color:var(--muted) }
.rpat tr.maybe .tc { background:none; box-shadow:inset 0 0 0 1px var(--line); color:var(--fg2); max-width:calc(100% - 1.2em) }
.rpat .rq { margin-left:3px; font-weight:600; color:var(--fg2) } .rws { margin-left:4px; font-size:var(--fs-xs); color:var(--fg2); cursor:help }
.rpwhy { margin:0; padding-left:18px; font-size:var(--fs-xs); color:var(--fg2); display:grid; gap:4px; overflow-wrap:anywhere } .rrmom { overflow-wrap:anywhere }
.rwhy-notes { margin:0; padding-left:18px; font-size:var(--fs-s); color:var(--fg2); display:grid; gap:4px }
.rw-h { margin:4px 0 0; font-size:var(--fs-xs); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:600 }
.rwhy-list { list-style:none; margin:0; padding:0; display:grid; gap:8px } .rwhy-list li { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 8px; min-width:0 }
.rwhy-list .rw-n { font-weight:500 } .rwhy-list .chip { font-size:var(--fs-xs) } .rwhy-list small { flex-basis:100%; color:var(--fg2); font-size:var(--fs-xs); font-variant-numeric:tabular-nums }
.rmodel:empty { display:none }
/* the curve watch's paper test under the radar's list (About to graduate): one card, the coins as rows (the top line a 44 px link to the coin
   on pump.fun, its status on the right), the variant table scrolling inside its own box on the narrowest phones, never the page */
.rcurve { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 14px; display:grid; gap:8px; min-width:0 }
.rcurve h3 { margin:0; font-size:var(--fs-m); font-weight:600 } .rcurve h3 small { font-size:var(--fs-s); font-weight:400; color:var(--muted) }
.rc-h { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 12px; justify-content:space-between; min-width:0 }
.rc-st { margin:0; display:inline-flex; align-items:center; gap:6px; font-size:var(--fs-xs); color:var(--fg2); min-width:0 } .rc-st span { overflow-wrap:anywhere }
.rc-st .rdot { width:8px; height:8px } .rc-st[data-st="on"] .rdot { background:var(--good-mark) } .rc-st[data-st="limited"] .rdot { background:var(--warn-mark) }
.rc-note { margin:0; font-size:var(--fs-s); color:var(--fg2); text-wrap:pretty } .rc-push { margin:0; font-size:var(--fs-s); font-weight:500; color:var(--fg) }
.rc-push.on { color:var(--warn) }
.rc-list { list-style:none; margin:0; padding:0; display:grid; min-width:0 } .rc-coin { display:grid; gap:2px; padding:0 0 8px; min-width:0 }
.rc-coin + .rc-coin { border-top:1px solid var(--line2) }
.rc-top { display:flex; flex-wrap:wrap; align-items:center; gap:2px 8px; min-height:44px; color:var(--fg); min-width:0 } .rc-top:hover, .rc-top:focus-visible { text-decoration:none }
.rc-top:hover .rc-sym, .rc-top:focus-visible .rc-sym { color:var(--accent) }
.rc-sym { font-weight:600; flex:0 1 auto; min-width:0; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.rc-p { font-weight:600; color:var(--accent); font-variant-numeric:tabular-nums }
.rc-s { margin-left:auto; font-size:var(--fs-xs); white-space:nowrap; padding:2px 8px; border-radius:999px; background:var(--chip); color:var(--fg2) }
.rc-s.grad { color:var(--good); background:color-mix(in srgb,var(--good-mark) 13%,var(--surface)) } .rc-s.bad { color:var(--bad); background:color-mix(in srgb,var(--bad-mark) 9%,var(--surface)) }
.rc-s.live { color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,var(--surface)) } .rc-s.muted { color:var(--muted) }
.rc-n { margin:0; font-size:var(--fs-xs); color:var(--fg2); font-variant-numeric:tabular-nums; overflow-wrap:anywhere }
.rc-r { margin:0; font-size:var(--fs-xs); font-weight:500; color:var(--fg2) } .rc-r.bad { color:var(--bad) } .rc-r.good { color:var(--good) } .rc-r.muted { color:var(--muted); font-weight:400 }
details.rc-more > summary, details.rc-by > summary { cursor:pointer; min-height:44px; display:flex; align-items:center; color:var(--accent); font-size:var(--fs-s); font-weight:500 }
details.rc-more > .rc-list { border-top:1px solid var(--line2) }
.rc-tab { width:100%; border-collapse:collapse; font-size:var(--fs-s); font-variant-numeric:tabular-nums }
.rc-tab th, .rc-tab td { padding:5px 6px; border-top:1px solid var(--line2); text-align:right }
.rc-tab th { border-top:0; font-size:var(--fs-xs); font-weight:500; color:var(--muted); vertical-align:bottom; line-height:1.25; text-transform:none; letter-spacing:0; white-space:normal }
.rc-tab td { white-space:nowrap; vertical-align:baseline } .rc-tab th:first-child, .rc-tab td:first-child { text-align:left; white-space:normal; padding-left:0; font-weight:500 }
.rc-by .rc-tab th:nth-child(2), .rc-by .rc-tab td:nth-child(2) { text-align:left; white-space:normal } .rc-tab tr.few td { color:var(--muted) } .rc-tab tr.few td:first-child { font-weight:400 } .rc-tab tr.rc-g td { border-top:2px solid var(--line) }
@media (min-width:760px) { .rc-list { grid-template-columns:repeat(2,minmax(0,1fr)); column-gap:28px } .rc-coin + .rc-coin { border-top:0 }
  .rc-list > .rc-coin:nth-child(n+3) { border-top:1px solid var(--line2) } .rc-tab { max-width:720px } }
.rcurve.one { padding:10px 14px } .rc-one { margin:0; font-size:var(--fs-s); color:var(--fg2); overflow-wrap:anywhere } .rc-one b { color:var(--fg); font-weight:600 }
@media (max-width:420px) { .rcurve { padding:10px 12px } .rc-tab, .rc-tab th { font-size:11px } .rc-tab th, .rc-tab td { padding:4px 2px }
  .rc-tab th:first-child, .rc-tab td:first-child { padding-left:0 } }
@media (max-width:560px) { .rstats > div { padding:8px 8px } .rstats b { font-size:20px }
  .rhead { gap:8px } .rpill { width:100% } .rrec th, .rrec td { padding:6px 3px } .rrec .ow { display:none } .rrec td:nth-child(2) { max-width:7ch } .rpat th, .rpat td { padding:4px 3px } }
@media (prefers-reduced-motion: reduce) { .rpill[data-st="running"] .rdot, .rpill[data-wait] .rdot { animation:none } details.rfold > summary::before { transition:none } }
"""

# ------------------------------------------------------------------------------------------------------------------ the script
JS = r"""
(function(){
var LV=['bad','warn','unk','ok','info'],IC={bad:'✕',warn:'!',unk:'?',ok:'✓',info:'·'};
var B58=/^[1-9A-HJ-NP-Za-km-z]{32,48}$/,XL=/^https:\/\/(www\.)?(x|twitter)\.com\/[A-Za-z0-9_]{1,30}(\/[A-Za-z0-9_\/?=&%.-]{0,90})?$/,NM=/^[A-Za-z0-9_.]{1,32}$/,HN=/^[A-Za-z0-9.-][A-Za-z0-9. -]{0,23}$/;
var LABELS=__LABELS__,UNK=__UNKNOWN__,SK=__SKEYS__,MEASURED=__MEASURED__,INFO=__INFO__,T3=__T3__;
function isn(v){return typeof v==='number'&&isFinite(v);}
function num(v){return isn(v)?v:null;}
function ms(v){return isn(v)&&v>=0&&v<1e14?v:null;}
function str(v,n){return (typeof v==='string'||isn(v)?String(v):'').replace(/[\u0000-\u001f\u007f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]/g,' ').slice(0,n);}
function names(v){return Array.isArray(v)?v.filter(function(x){return typeof x==='string'&&NM.test(x);}).slice(0,20):[];}
function line(v){return (Array.isArray(v)?v:[]).filter(function(x){return Array.isArray(x)&&LV.indexOf(x[0])>=0&&typeof x[1]==='string'&&x[1].trim();}).slice(0,12).map(function(x){return [x[0],str(x[1],120)];});}
function scal(v){return v===null||typeof v==='boolean'||isn(v)?{ok:1,v:v}:typeof v==='string'?{ok:1,v:str(v,60)}:{ok:0};}
function dmap(v,deep){var o={},n=0;if(!v||typeof v!=='object'||Array.isArray(v))return o;
  Object.keys(v).forEach(function(k){if(n>=60||!NM.test(k))return;var s=scal(v[k]);
    if(s.ok){o[k]=s.v;n++;}else if(!deep&&v[k]&&typeof v[k]==='object'&&!Array.isArray(v[k])){var d=dmap(v[k],1);if(Object.keys(d).length){o[k]=d;n++;}}
    else if(!deep&&Array.isArray(v[k])){var a=v[k].filter(function(y){return isn(y)||typeof y==='string'&&y;}).slice(0,16).map(function(y){return isn(y)?y:str(y,40);});if(a.length){o[k]=a;n++;}}});return o;}
function coin(c,full){
  if(!c||typeof c!=='object'||typeof c.addr!=='string'||!B58.test(c.addr))return null;
  var o={addr:c.addr,sym:str(c.sym,24),name:str(c.name,48),v:['good','watch','trap'].indexOf(c.v)>=0?c.v:'watch',pts:num(c.pts),age:num(c.age),line:line(c.line),liq:num(c.liq),mc:num(c.mc),n:num(c.n),
    ws:Number.isInteger(c.ws)&&c.ws>=-9&&c.ws<=9?c.ws:null};
  ['hard','soft','unknown','info','plus'].forEach(function(k){o[k]=names(c[k]);});
  if(typeof c.pair==='string'&&B58.test(c.pair))o.pair=c.pair;
  if(full){['pool','mint','first','push'].forEach(function(k){o[k]=ms(c[k]);});['px','m5','buys','sells','up'].forEach(function(k){o[k]=num(c[k]);});
    o.dex=str(c.dex,24);o.lp=str(c.lp,24);o.d=dmap(c.d);o.found=Array.isArray(c.found)?c.found.filter(function(x){return typeof x==='string';}).slice(0,8).map(function(x){return str(x,24);}):[];
    o.pb=c.pb===1?1:0;o.t3=Array.isArray(c.t3)?c.t3.filter(function(x){return typeof x==='string'&&x.trim();}).slice(0,T3).map(function(x){return str(x,60);}):[];}
  if(typeof c.x==='string'&&XL.test(c.x))o.x=c.x;
  return o;}
function obj(v){return v&&typeof v==='object'&&!Array.isArray(v)?v:{};}
function nums(v,ks){if(!v||typeof v!=='object'||Array.isArray(v))return null;var o={};ks.forEach(function(k){o[k]=num(v[k]);});return o;}
function win(v){var o=nums(v,['n','auc']);if(o){o.from=v.from==='learned'?'learned':'none';o.why=str(v.why,120);}return o;}
// record.pat as clean_doc's _pat keeps it: rows [name, lk, ln, wk, wn, sure, lv, dir] with both groups known, sure only a real true, dir -1, 0 or 1
// (else 0); coins [sym, t, hourW, [[name, k, known]]] with 0 <= k <= known
function pat(p){if(!p||typeof p!=='object'||Array.isArray(p))return null;var o=nums(p,['hrs','w','l','need']),nm=function(x){return typeof x==='string'&&NM.test(x);};
  o.at=ms(p.at);o.since=ms(p.since);
  o.rows=(Array.isArray(p.rows)?p.rows:[]).filter(function(x){return Array.isArray(x)&&x.length===8&&nm(x[0])&&isn(x[1])&&isn(x[2])&&isn(x[3])&&isn(x[4])&&x[1]>=0&&x[1]<=x[2]&&x[3]>=0&&x[3]<=x[4]&&x[2]>0&&x[4]>0;})
    .slice(0,R.PAT_ROWS).map(function(x){return [x[0],x[1],x[2],x[3],x[4],x[5]===true,LV.indexOf(x[6])>=0?x[6]:'info',[-1,0,1].indexOf(x[7])>=0?x[7]:0];});
  o.why=(Array.isArray(p.why)?p.why:[]).filter(function(w){return Array.isArray(w)&&w.length===4&&Array.isArray(w[3]);}).slice(0,R.PAT_ROWS).map(function(w){
    return [str(w[0],24),ms(w[1]),num(w[2]),w[3].filter(function(s){return Array.isArray(s)&&s.length===3&&nm(s[0])&&isn(s[1])&&isn(s[2])&&s[1]>=0&&s[1]<=s[2];}).slice(0,3).map(function(s){return [s[0],s[1],s[2]];})];});
  return o;}
function dur(m){return !isn(m)?'?':m<60?Math.max(0,Math.floor(m))+' min':m<2880?Math.floor(m/60)+' h':Math.floor(m/1440)+' days';}
function p0(v){return isn(v)?Math.round(100*v)+'%':'?';}
function eur(v){return (v<0?'−':v>0?'+':'')+Math.abs(v).toFixed(2)+' €';}
// the curve watch's block (page_radar.clean_curve and curve_view, word for word): the strings' rule (CV.ctrl as spaces, a cut in UTF-16 units
// without a half emoji, CV.blank trimmed), the whitelist's parts, and the view's numbers in whole-number arithmetic (no toFixed rounding)
var CV=__CURVE__,CCC=new RegExp('['+CV.ctrl+']','g'),CTB=new RegExp('^['+CV.blank+']+|['+CV.blank+']+$','g'),CID=/^(60|75|90)m?$/;
function cstr(v,n){return typeof v!=='string'?'':v.replace(CCC,' ').replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]|[\uD800-\uDFFF]/g,function(m){return m.length===2?m:' ';})
  .slice(0,n).replace(/[\uD800-\uDBFF]$/,'').replace(CTB,'');}
function cnums(d,ks){var o={};ks.forEach(function(k){o[k]=num(d[k]);});return o;}
function isObj(v){return !!v&&typeof v==='object'&&!Array.isArray(v);}
function cbool(d,k){return typeof d[k]==='boolean'?d[k]:null;}
function cchips(v){var out=[];(Array.isArray(v)?v:[]).forEach(function(x){if(Array.isArray(x)&&x.length>=2&&LV.indexOf(x[0])>=0&&typeof x[1]==='string'){var s=cstr(x[1],60);if(s)out.push([x[0],s]);}});return out.slice(0,3);}
function crec(r){if(!isObj(r)||typeof r.mint!=='string'||!B58.test(r.mint)||CV.thr.indexOf(r.thr)<0||ms(r.t)==null)return null;
  var o=obj(r.out),x={mint:r.mint,sym:cstr(r.sym,24),thr:r.thr,t:ms(r.t)};['prog','mcu','mcs','age','pts','buys','sells'].forEach(function(k){x[k]=num(r[k]);});
  x.mom=cbool(r,'mom');x.v=CV.v.indexOf(r.v)>=0?r.v:'unknown';x.chips=cchips(r.chips);x.push=ms(r.push);
  x.out={grad:ms(o.grad),gradMin:num(o.gradMin),x60:num(o.x60),peak:num(o.peak),rug:cbool(o,'rug'),x2:cbool(o,'x2'),eur:num(o.eur),how:CV.how.indexOf(o.how)>=0?o.how:'',miss:o.miss===true,
    done:o.done===true};
  return x;}
function cvar(r){if(!isObj(r)||typeof r.id!=='string'||!CID.test(r.id))return null;
  var by=obj(r.by),x={id:r.id,thr:parseInt(r.id.slice(0,2),10),mom:/m$/.test(r.id)};['n','nS','rug','x2','eur','grad','gradMin','miss','unseen'].forEach(function(k){x[k]=num(r[k]);});
  x.by={};CV.v.forEach(function(v){if(isObj(by[v]))x.by[v]=cnums(by[v],['n','nS','rug','x2','eur']);});return x;}
function cint(v){return isn(v)&&v>=0&&v<CV.big?Math.floor(v):null;}
function cpct(v){return isn(v)&&v>=0&&v<=1?Math.floor(100*v+0.5)+'%':'–';}
function cmoney(v,sign,bare){if(!isn(v)||Math.abs(v)>=CV.big)return '–';var c=Math.floor(Math.abs(v)*100+0.5),w=Math.floor(c/100),f=c%100;
  return (sign&&c?(v<0?'−':'+'):'')+(!sign&&f===0?String(w):w+'.'+(f<10?'0':'')+f)+(bare?'':'\u00a0€');}
function cx(v){if(!isn(v)||!(v>=0&&v<CV.big))return '–';if(v>=10)return Math.floor(v+0.5)+'x';var c=Math.floor(v*100+0.5),f=c%100;return Math.floor(c/100)+'.'+(f<10?'0':'')+f+'x';}
function cusd(v){if(!isn(v)||!(v>=0&&v<1e12))return '';var d=Math.floor(v+0.5),k=Math.floor(v/1e3+0.5),m;if(d<1000)return '$'+d;if(k<1000)return '$'+k+'k';
  m=Math.floor(v/1e5+0.5);return '$'+Math.floor(m/10)+(m%10?'.'+(m%10):'')+'M';}
function cage(a){if(!isn(a)||!(a>=0&&a<CV.big))return 'mint time unknown';var m=Math.floor(a);if(m<1)return 'under 1 min after mint';if(m<60)return m+' min after mint';
  if(m<2880)return (m%60?Math.floor(m/60)+' h '+(m%60)+' min':Math.floor(m/60)+' h')+' after mint';return Math.floor(m/1440)+' days after mint';}
function cand(xs){return xs.length===1?xs[0]:xs.length?xs.slice(0,-1).join(', ')+' and '+xs[xs.length-1]:'';}
function cvlabel(id){return id.slice(0,2)+'%'+(/m$/.test(id)?' rising':'');}
function cstatus(o,t,now,seen){if(o.grad!=null){var gm=o.gradMin;if(gm==null||!(gm>=0&&gm<CV.big))return ['grad','graduated'];var m=Math.floor(gm+0.5);return ['grad',m<1?'graduated within a minute':'graduated after '+m+' min'];}
  if(o.done)return ['grad','graduated'];if(o.how==='dead'||o.how==='gone')return ['bad','dead'];if(o.x60!=null)return ['muted','did not graduate'];
  seen=seen==null?now:Math.min(now,seen);if(!o.miss&&seen-t>=CV.value)return ['muted','did not graduate'];
  if(o.miss||now-t>=CV.value)return ['muted','not watched to the end'];return ['live','still on the curve'];}
function cresult(o){if(o.rug===true)return ['bad',o.x2===true?'doubled, then rugged in 1 h':'rugged in 1 h'];if(o.x2===true)return ['good','doubled in 1 h'];
  if(o.x60!=null)return ['','1 h: '+cx(o.x60)];if(o.miss)return ['muted','no 1 h value'];return null;}
function crow(label,s,extra,greens){var n=cint(s.n),ns=cint(s.nS),few=ns==null||ns<CV.few,bits=[],gm=num(s.gradMin),miss=cint(s.miss),uns=cint(s.unseen);
  if(n!=null)bits.push(n+(greens?' coin':' call')+(n===1?'':'s'));if(ns!=null)bits.push(ns+' with a 1 h value');
  if(gm!=null&&gm>=0&&gm<CV.big)bits.push('graduated a median '+Math.floor(gm+0.5)+' min after the call');if(miss)bits.push(miss+' without a 1 h value');
  if(uns)bits.push(uns+' whose hour nobody saw (not in graduated)');
  return {cls:[greens?'rc-g':'',few?'few':''].filter(Boolean).join(' '),cells:[label].concat(extra(n),[cpct(s.rug),cpct(s.x2),cmoney(s.eur,true,true)]),
    title:(greens?"the radar's green coins first rated in the same hours, judged 1 h later by the same rules: ":'')+bits.join(', ')};}
var R=window.MemebotRadar={CYCLE:150000,CYCLE_MAX:600000,GRACE:60000,LATE:900000,HOUR:3600000,DONE_GRACE:1800000,FRESH:900000,ROUND:180000,SB_DONE:300000,SB_ROUND:60000,KICK:480000,LEAVE:30000,RESERVE:10,GH_MIN:150000,GH_OFFICE:300000,IDLE:600000,SB_FRESH:20000,SB_STALE:60000,SB_OTHER:300000,SB_APP:150000,
  TIMEOUT:20000,SB_TIMEOUT:8000,SB_RETRY:120000,LAG:120000,SHOWN:4,CARD:3,PHONE:2,LONG:28,RECENT:10800000,TOO_FEW:20,SCAN_LEN:2700000,PAT_ROWS:3,
  // radar.json's curve block as the page may show it, or null (page_radar.clean_curve: the same keys, the same cuts)
  cleanCurve:function(cv){if(!isObj(cv)||ms(cv.t)==null)return null;
    var hs=obj(cv.hosts),ps=obj(cv.push),lst=function(k){return Array.isArray(cv[k])?cv[k]:[];},o={v:num(cv.v),t:ms(cv.t),state:CV.states.indexOf(cv.state)>=0?cv.state:'off',why:cstr(cv.why,160),since:ms(cv.since)};
    ['hours','ticket','slip','momPts','calls','late','follow','cand','trades','polls','sol'].forEach(function(k){o[k]=num(cv[k]);});
    o.thresholds=lst('thresholds').filter(function(x){return CV.thr.indexOf(x)>=0;}).slice(0,3);
    o.hosts={};CV.hosts.forEach(function(k){if(typeof hs[k]==='string'&&/^[a-z]{1,12}$/.test(hs[k]))o.hosts[k]=hs[k];});
    o.push={variant:typeof ps.variant==='string'&&CID.test(ps.variant)?ps.variant:null,verdicts:(Array.isArray(ps.verdicts)?ps.verdicts:[]).filter(function(x){return ['ok','risky','unknown'].indexOf(x)>=0;}).slice(0,3),
      perH:num(ps.perH),sent1h:num(ps.sent1h)};
    o.calib=isObj(cv.calib)?cnums(cv.calib,['n','mcSol','prog','scale','expect']):null;o.greens=isObj(cv.greens)?cnums(cv.greens,['n','nS','rug','x2','eur','grad']):null;
    o.recent=lst('recent').map(function(r){return crec(r);}).filter(Boolean).slice(0,CV.recent);o.variants=lst('variants').map(function(r){return cvar(r);}).filter(Boolean).slice(0,6);
    return o;},
  // what the Radar tab shows of a whitelisted curve block at the time now (page_radar.curve_view says the same at build time): null without a block,
  // {state, head, one: true} without a call, else the head line, the two sentences, the coins (newest call per coin), the tables and the footnote
  curveView:function(cv,now){if(!isObj(cv))return null;
    var st=CV.states.indexOf(cv.state)>=0?cv.state:'off',fol=cint(cv.follow),hrs=cint(cv.hours),calls=cint(cv.calls),late=cint(cv.late),head='Curve watch '+st;
    if(st==='on')head+=(fol?[fol+' coin'+(fol===1?'':'s')+' followed']:[]).concat(cv.why?[cv.why]:[],hrs?[hrs+' h watched']:[]).map(function(b){return ' · '+b;}).join('');
    else if(cv.why)head+=': '+cv.why;
    var recent=Array.isArray(cv.recent)?cv.recent:[];
    if(!recent.length&&!calls)return {state:st,head:head,one:true};
    var tk=num(cv.ticket),sl=num(cv.slip),mp=num(cv.momPts),tks=cmoney(tk!=null&&tk>0&&tk<1e6?tk:3,false);
    sl=sl!=null&&sl>=0&&sl<1?sl:0.05;mp=mp!=null&&mp>0&&mp<=100?mp:10;
    var thr=(Array.isArray(cv.thresholds)&&cv.thresholds.length?cv.thresholds:CV.thr).map(function(x){return String(x);});
    var note='Paper test: the radar calls pump.fun coins still on their bonding curve, before the pool opens, at '+cand(thr)+'% of the curve sold, to find out '+
      'whether an earlier call helps. Each call is judged 1 h later with '+tks+' on paper and '+Math.floor(100*sl+0.5)+"% slippage, beside the radar's greens of the same hours.";
    var ps=obj(cv.push),vr=typeof ps.variant==='string'&&CID.test(ps.variant)?ps.variant:null,push;
    if(vr){var vs=(Array.isArray(ps.verdicts)?ps.verdicts:[]).filter(function(v){return CV.v.indexOf(v)>=0;}).map(function(v){return CV.vw[v][1];}),ph=cint(ps.perH);
      push='Curve pushes are on for the '+cvlabel(vr)+' calls'+(vs.length?' (quick check: '+vs.join(' or ')+')':'')+(ph!=null?', at most '+ph+' an hour':'')+'.';}
    else push='No curve push goes out while the switch is off.';
    var groups=[];
    recent.forEach(function(r){var g=null;for(var i=0;i<groups.length;i++)if(groups[i].r.mint===r.mint){g=groups[i];break;}
      if(!g){groups.push({r:r,thr:[r.thr]});return;}if(g.thr.indexOf(r.thr)<0)g.thr.push(r.thr);if(r.t>g.r.t)g.r=r;});
    groups.sort(function(a,b){return b.r.t-a.r.t;});
    var coins=groups.map(function(g){var r=g.r,o=r.out,p=num(r.prog),s=num(r.mcs),mc=cusd(r.mcu)||(s!=null&&s>=0&&s<CV.big?Math.floor(s+0.5)+' SOL':'unknown'),vw=CV.vw[r.v]||CV.vw.unknown;
      var nums=[cage(r.age),'market cap '+mc,'called at '+cand(g.thr.slice().sort(function(a,b){return a-b;}).map(function(x){return String(x);}))+'%'].concat(r.push?['sent to the phone']:[]);
      return {mint:r.mint,sym:r.sym||'?',prog:p!=null&&p>=0&&p<=100?Math.floor(p+0.5)+'%':'?',nums:nums.join(' · '),
        line:[[vw[0],vw[1]]].concat((r.chips||[]).map(function(x){return [x[0],x[1]];})),st:cstatus(o,r.t,now,ms(cv.t)),res:cresult(o)};});
    var count=function(n){return [n!=null?String(n):'–'];},vars=Array.isArray(cv.variants)?cv.variants:[],by=[];
    var rows=vars.map(function(v){return crow(cvlabel(v.id),v,function(n){return count(n).concat([cpct(v.grad)]);});});
    if(isObj(cv.greens))rows.push(crow('radar greens',cv.greens,function(n){return count(n).concat(['–']);},true));
    vars.forEach(function(v){CV.v.forEach(function(k){var b=isObj(v.by)?v.by[k]:null;if(isObj(b)&&cint(b.n))by.push(crow(cvlabel(v.id),b,function(n){return [CV.vw[k][1]].concat(count(n));}));});});
    var foot=['Rising: '+Math.floor(mp+0.5)+' or more points of the curve in the 5 minutes before the call, and more purchases than sales.',
      "Without the coin's trades (pump.fun's list only) the points alone count.",
      'Rugged, doubled and paper: of the calls with a 1 h value; graduated: of the calls an hour old whose hour was seen. Rugged: gone, dead or '+
      'worth 0.1x or less at 1 h; doubled: 2x to 30x within the hour and not gone or dead at 1 h; the greens by the same rules. Quick check: as '+
      'known at the call, or the first one within '+CV.late+' s after it (then counted from that moment\'s price). Grey: under '+CV.few+' calls with a 1 h value, '+
      'too few to tell.'];
    if(late)foot.push(late+' time'+(late===1?'':'s')+' a trading coin was first seen already past a mark, so no call was made.');
    var cb=obj(cv.calib),cn=cint(cb.n),cp=num(cb.prog);
    if(cn&&cp!=null&&cp>=0&&cp<1000)foot.push('Progress check: at the last trade before '+cn+' graduation'+(cn===1?'':'s')+' the curve read '+Math.floor(cp+0.5)+'% sold (about 100% is right).');
    return {state:st,head:head,one:false,note:note,push:push,pushOn:!!vr,coins:coins.slice(0,CV.shown),more:coins.slice(CV.shown),ticket:tks,rows:rows,by:by,foot:foot.join(' ')};},
  // radar.json as the page may show it, or null (SPEC Appendix A: every key whitelisted, numbers finite, strings cut, addresses base58)
  clean:function(d){
    if(!d||typeof d!=='object'||d.kind!=='radar'||ms(d.t)==null)return null;
    var run=obj(d.run),md=obj(d.model),cn=obj(d.counts),wm=obj(d.wm),lg=obj(d.lastGood),rd=d.record&&typeof d.record==='object'?d.record:null,hs=obj(d.hosts),o;
    o={v:num(d.v),kind:'radar',t:d.t,next:ms(d.next),hourly:ms(d.hourly),state:['running','degraded','ending','off','hours','done'].indexOf(d.state)>=0?d.state:'running',why:str(d.why,200),secs:num(d.secs),
      run:{id:str(run.id,40),start:ms(run.start),end:ms(run.end),cycle:num(run.cycle),source:str(run.source,12),mode:run.mode==='round'||run.mode==='loop'?run.mode:''},
      model:{from:md.from==='learned'?'learned':'prior',n:num(md.n),need:num(md.need),auc:num(md.auc),prior:num(md.prior),at:ms(md.at),why:str(md.why,200),win:win(md.win)},
      counts:{seen:num(cn.seen),good:num(cn.good),pushed:num(cn.pushed),seenAgeMed:num(cn.seenAgeMed)},wm:{t:ms(wm.t),nCoins:num(wm.nCoins)},
      coins:(Array.isArray(d.coins)?d.coins:[]).map(function(c){return coin(c,1);}).filter(Boolean).slice(0,5),
      others:(Array.isArray(d.others)?d.others:[]).map(function(c){return coin(c,0);}).filter(Boolean).slice(0,40),
      lastGood:typeof lg.addr==='string'&&B58.test(lg.addr)?{addr:lg.addr,sym:str(lg.sym,24),at:ms(lg.at)}:null,
      recent:(Array.isArray(d.recent)?d.recent:[]).filter(function(r){return r&&typeof r==='object'&&typeof r.addr==='string'&&B58.test(r.addr);}).slice(0,40).map(function(r){
        var lt=obj(r.later),out=r.out&&typeof r.out==='object'?r.out:null,l={};['5','15','30','60'].forEach(function(k){l[k]=num(lt[k]);});
        var pk=r.peak60&&typeof r.peak60==='object'&&isn(r.peak60.x)?{x:r.peak60.x,at:ms(r.peak60.at)}:null;
        return {addr:r.addr,sym:str(r.sym,24),good:ms(r.good),push:ms(r.push),later:l,peak60:pk,out:out?{rug1h:typeof out.rug1h==='boolean'?out.rug1h:null,win1h:typeof out.win1h==='boolean'?out.win1h:null,x60:num(out.x60)}:null,miss60:r.miss60===true};}),
      record:null,hosts:{},notes:(Array.isArray(d.notes)?d.notes:[]).filter(function(x){return typeof x==='string';}).slice(0,8).map(function(x){return str(x,160);}),
      lines:(Array.isArray(d.lines)?d.lines:[]).filter(function(x){return typeof x==='string';}).slice(0,12).map(function(x){return str(x,200);})};
    if(rd){var ci=obj(rd.ci),pr=function(v){return Array.isArray(v)&&v.length===2&&isn(v[0])&&isn(v[1])?[v[0],v[1]]:null;};
      o.record={calls:num(rd.calls),rug:num(rd.rug),win:num(rd.win),eur:num(rd.eur),n60:num(rd.n60),ticket:num(rd.ticket),ci:{rug:pr(ci.rug),win:pr(ci.win)}};}
    if(rd){o.record.mom=nums(rd.mom,['calls','n60','rug','win']);o.record.all=nums(rd.all,['n60','rug','win']);o.record.pat=pat(rd.pat);o.record.known=nums(rd.known,['n','rug','win']);}
    Object.keys(hs).slice(0,12).forEach(function(k){if(HN.test(k)&&typeof hs[k]==='string')o.hosts[k]=str(hs[k],16);});
    o.curve=R.cleanCurve(d.curve);     // the curve watch's paper test (About to graduate)
    var sr=obj(d.src);o.src={};Object.keys(sr).slice(0,12).forEach(function(k){var v=sr[k];if(/^[a-z][A-Za-z0-9:_-]{0,23}$/.test(k)&&isn(v)&&Math.floor(v)===v&&v>=0&&v<=100000)o.src[k]=v;});
    return o;},
  // how old the doc is (ms), from its own t: the local time since it was first seen (got), plus the delay it was seen with once a newer
  // doc replaced an older one here (moved, at most LAG); before that the phone's clock is the first guess (MemebotLive.age's pattern)
  age:function(doc,now,got,moved){var t=+(doc&&doc.t)||0,loc=got>0?Math.max(0,now-got):null;
    return loc==null?now-t:moved?loc+Math.min(R.LAG,Math.max(0,got-t)):Math.max(loc,now-t);},
  // a doc of one round (launch_radar.py round: state done, or degraded when its cycle failed): the radar runs one round after each full scan
  round:function(doc){return !!doc&&(doc.state==='done'||!!doc.run&&doc.run.mode==='round');},
  // when the next round is due (ms): the doc's next, else an hour after its round
  due:function(doc){return +doc.next>0?+doc.next:+doc.t+R.HOUR;},
  // the words for the next round after a round (the office says the same: page_office.next_words): "next about HH:MM" until doc.next, then
  // "next due since HH:MM"; without a next (a round by hand more than 3 h after the scan's last one) the next full scan starts one: "next
  // after the HH:MM scan" from the scan strip's estimate (scan, ms; an hour later each time that scan should be over by now), else "next
  // after the next full scan". now: the radar's clock (ms)
  nextWords:function(doc,now,scan,fmt){
    if(isn(doc.next)&&doc.next>0)return (now<doc.next?'next about ':'next due since ')+fmt(doc.next);
    if(isn(scan)&&scan>0){var s=scan,ref=Math.max(+doc.t||0,now);while(s+R.SCAN_LEN<ref)s+=R.HOUR;return 'next after the '+fmt(s)+' scan';}
    return 'next after the next full scan';},
  // a round: done (until its next round is due and DONE_GRACE more), late (one more hour), stopped (older). A loop: running (checked within
  // 2 of its cycles and a minute), late (15 minutes), stopped (older). off (switched off), hours (outside its hours: the doc names the next start;
  // a doc past that start by an hour is stopped: the first full scan inside the hours starts the radar), none (no doc)
  radarState:function(doc,now,got,moved){
    if(!doc||typeof doc!=='object'||doc.kind!=='radar'||!(+doc.t>0))return 'none';
    var a=R.age(doc,now,got,moved);
    if(doc.state==='off')return 'off';
    if(doc.state==='hours')return +doc.next>0&&+doc.t+a>+doc.next+R.HOUR?'stopped':'hours';     // the first full scan of the hours starts it: up to an hour
    if(R.round(doc)){var over=+doc.t+a-R.due(doc);return over<=R.DONE_GRACE?'done':over<=R.DONE_GRACE+R.HOUR?'late':'stopped';}
    return a<=2*R.cycle(doc)+R.GRACE?'running':a<=R.LATE?'late':'stopped';},
  // a loop's own cadence: the doc's next minus its time (the radar's 2 minutes count as 2.5, an older loop's 5), CYCLE to CYCLE_MAX; CYCLE without a next
  cycle:function(doc){var c=+doc.next-(+doc.t);return c>0?Math.min(R.CYCLE_MAX,Math.max(R.CYCLE,c)):R.CYCLE;},
  // the coins are current (a card in full colour, the tab's count): a running loop, or a round within FRESH of its check
  live:function(st,doc,now,got,moved){return st==='running'||st==='done'&&!!doc&&R.age(doc,now,got,moved)<=R.FRESH;},
  // supabase when the page carries the live store (and it did not just fail: back), else github while the shared budget keeps more
  // than RESERVE requests, else raw (raw.githubusercontent.com: not counted, can be minutes old), else none
  radarTransport:function(url,key,src,rem,reset,now,back){
    if(!(back>now)&&/^https:\/\/[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?\/?$/.test(String(url||''))&&/^sb_publishable_[A-Za-z0-9_-]+$/.test(String(key||'')))return 'supabase';
    if(!src)return 'none';
    return isn(rem)&&rem<=R.RESERVE&&+reset*1000>now?'raw':'github';},
  // the GitHub budget both polls share: the newest of the office poll's numbers (localStorage) and this poll's own
  budget:function(office,mine){var a=office&&isn(office.rem)&&+office.at>0?{rem:office.rem,reset:+office.reset||0,at:+office.at}:null,
    b=mine&&isn(mine.rem)&&+mine.remAt>0?{rem:mine.rem,reset:+mine.reset||0,at:+mine.remAt}:null,x=!a?b:!b?a:b.at>=a.at?b:a;
    return x?{rem:x.rem,reset:x.reset}:{rem:null,reset:0};},
  // when the next poll is due (ms). o: doc, now, last (the last poll), tab (radar | office | app), via, rem, reset, fails, got, moved, kick (a
  // tap on Start within KICK and no newer doc since: every SB_FRESH on the live store, every GH_MIN on GitHub, inside the budget). The Office
  // tab's desk follows a loop that runs (running or late) like the Radar tab: at 2-minute rounds its 300 s would read the radar as late between polls
  radarNext:function(o){
    var now=o.now,doc=o.doc,st=R.radarState(doc,now,o.got,o.moved),tab=o.tab||'radar',t,last=+o.last||0;
    if(tab==='office'&&(st==='running'||st==='late')&&!R.round(doc))tab='radar';
    var srv=doc&&+doc.t>0?+doc.t+R.age(doc,now,o.got,o.moved):now,loc=function(x){return now+(x-srv);};
    // a round: the next one is due at its next (it takes about ROUND); until then a poll every IDLE at most (a Start by hand), after it every IDLE;
    // the live store: every SB_ROUND on the Radar tab (a round by hand shows within a minute), SB_DONE elsewhere, sooner when the next round is due
    var due=doc&&R.round(doc)&&(st==='done'||st==='late')?loc(R.due(doc)+R.ROUND):null;
    if(o.via==='supabase')t=due!=null?now+Math.min(due>now?due-now:R.SB_DONE,tab==='radar'?R.SB_ROUND:R.SB_DONE):now+(tab==='radar'?(st==='running'?R.SB_FRESH:R.SB_STALE):tab==='app'?R.SB_APP:R.SB_OTHER);
    else{var gap=tab==='radar'?R.GH_MIN:R.GH_OFFICE;
      if(due!=null)t=Math.max(last+gap,due>now?Math.min(due,last+R.IDLE):last+R.IDLE);
      else if(st==='running'||st==='late')t=Math.max(last+gap,+doc.next>0?loc(+doc.next+15000):now);
      else if(st==='hours'&&+doc.next>0)t=Math.max(last+R.IDLE,loc(+doc.next+60000));
      else t=last+Math.max(gap,R.IDLE);
      if(o.kick)t=Math.min(t,Math.max(now,last+R.GH_MIN));
      if(o.via!=='raw'&&isn(o.rem)&&o.rem>R.RESERVE&&+o.reset>0){var left=Math.min(3600000,Math.max(0,o.reset*1000-now));t=Math.max(t,now+left/(o.rem-R.RESERVE));}}
    if(o.kick&&o.via==='supabase')t=Math.min(t,now+R.SB_FRESH);
    var f=Math.max(0,Math.min(10,+o.fails||0));if(f)t=Math.max(t,now+Math.min(1800000,75000*Math.pow(2,f)));
    return Math.max(t,now+1000);},
  good:function(doc){return doc&&Array.isArray(doc.coins)?doc.coins.filter(function(c){return c&&c.v==='good';}).length:0;},
  // the trained odds of a coin's numbers (info only): d.upP / d.zeroP, or d.odds {up, zero}; [up, zero] or null
  odds:function(d){d=obj(d);var o=obj(d.odds),up=isn(d.upP)?d.upP:isn(o.up)?o.up:null,z=isn(d.zeroP)?d.zeroP:isn(o.zero)?o.zero:null;return up==null?null:[up,z];},
  // "just now" under a minute, else "34 min ago"
  ago:function(msAgo){return !isn(msAgo)?'?':msAgo<60000?'just now':dur(msAgo/60000)+' ago';},
  // the record (SPEC 3.4) from one source, record.known (the counts the push and the Office chat say): in full inside the Radar record fold,
  // with the 95% ranges of the shares, and short on the fold's title; "too few" while fewer than TOO_FEW coins have a 1 h result. Its euros
  // are on the Traders tab
  known:function(r){var k=r&&r.known,ok=function(x){return isn(x)&&x>=0&&Math.floor(x)===x;};
    return k&&ok(k.n)&&ok(k.win)&&ok(k.rug)&&k.win<=k.n&&k.rug<=k.n?k:null;},
  recLine:function(r){if(!r||!isn(r.calls))return '';var k=R.known(r);
    if(!k||k.n<R.TOO_FEW)return r.calls+' coin'+(r.calls===1?'':'s')+' without traps · too few with a 1 h result for a record yet ('+(k?k.n:0)+' of '+R.TOO_FEW+')';
    var s=k.n+' coins without traps with a 1 h result: '+k.win+' doubled, '+k.rug+' crashed to near zero';
    var ci=r.ci||{};if(ci.rug&&ci.win)s+=' (95% range: '+p0(ci.win[0])+' to '+p0(ci.win[1])+' doubled, '+p0(ci.rug[0])+' to '+p0(ci.rug[1])+' crashed)';return s;},
  recShort:function(r){if(!r||!isn(r.calls))return '';var k=R.known(r);
    return k&&k.n>=R.TOO_FEW?k.n+' with a 1 h result · '+k.win+' doubled · '+k.rug+' crashed':r.calls+' coin'+(r.calls===1?'':'s')+' · too few for a record yet';},
  // the coins that rose fast (record.mom: 1.5x within 6 min or +50% in 5 min; counted, never bought or pushed) beside all new coins of the same
  // period (record.all), both with the same 1 h label; nothing while no coin rose fast
  momLine:function(m,a){if(!m||!isn(m.calls)||!(m.calls>0))return '';var s='Rising fast, paper only: '+m.calls+' coin'+(m.calls===1?'':'s');
    if(!(m.n60>=R.TOO_FEW))return s+' · too few yet ('+(isn(m.n60)?m.n60:0)+' of '+R.TOO_FEW+' with a 1 h price)';
    return s+' · '+p0(m.rug)+' crashed · '+p0(m.win)+' 2x at 1 h'+(a&&isn(a.rug)&&isn(a.win)?' · all new coins: '+p0(a.rug)+' crashed, '+p0(a.win)+' 2x':'');},
  // record.pat (rugged vs doubled coins of the same hours, their signals at first sight; the page says crashed, as the record's first line "crashed
  // to near zero"): the head line, one row [label, rugged %, 2x %, sure, level, title, where it is more often hour by hour (dir)], one rugged coin
  // with the flags its hour's doubled coins mostly lacked (fmt: the time as HH:MM).
  // The % are pooled over the hours: when they point the other way than the hours one by one, the row says 'more' and 'less' from dir instead
  patHead:function(p){if(!p||!isn(p.w)||!isn(p.l))return '';
    return isn(p.need)&&p.w<p.need?'Patterns: too few doubled coins yet ('+p.w+' of '+p.need+')':'Same hours, signals at first sight: '+p.l+' crashed vs '+p.w+' doubled';},
  patRow:function(x){var d=x[7],off=d&&(x[3]/x[4]-x[1]/x[2])*d<0,side=d>0?'doubled':d<0?'crashed':'';
    return [LABELS[x[0]]||x[0].replace(/_/g,' '),off?(d<0?'more':'less'):p0(x[1]/x[2]),off?(d>0?'more':'less'):p0(x[3]/x[4]),x[5],x[6],
      x[1]+' of '+x[2]+' crashed, '+x[3]+' of '+x[4]+' doubled had it'+(off?'; hour by hour it is more often in '+side+' coins':'')+(x[5]?'':' (could be chance)'),side];},
  whyLine:function(w,fmt){if(!w[3].length)return '';
    return (w[0]||'?')+(isn(w[1])?', seen '+fmt(w[1]):'')+', crashed within 1 h · '+w[3].map(function(s,i){return (LABELS[s[0]]||s[0].replace(/_/g,' '))+' ('+s[1]+' of '+(isn(s[2])?s[2]:'?')+(i?')':' doubled that hour had it)');}).join(', ');},
  // the ▲ beside a coin: it orders like past doubled coins (ws, hindsight) once a win order is learned; it changes no verdict
  wsOn:function(c,m){return !!(c&&isn(c.ws)&&c.ws>=1&&m&&m.win&&m.win.from==='learned');},
  verdict:function(c){if(!c)return ['','? trap check unavailable'];
    if(c.v==='good')return ['good','✓ No trap found'+(c.n?' · '+c.n+' checks':'')];
    if(c.v==='trap'){var k=(c.hard||[]).length;return ['bad',k>1?'✕ '+k+' traps':'✕ trap'];}
    if((c.unknown||[]).length)return ['warn','? not fully checked'];var s=(c.soft||[]).length;return ['warn',s>1?'! '+s+' warnings':'! not good yet'];},
  // the Trap check tab: the line's texts by level, and words for the names the line had no room for
  groups:function(c){return [['bad','Red flags','hard'],['warn','Warnings','soft'],['unk','Not checked','unknown'],['ok','Passed',null],['info','Measured, not weighted yet','info']].map(function(g){
    var tx=(c.line||[]).filter(function(x){return x[0]===g[0];}).map(function(x){return x[1];}),nm=g[2]?c[g[2]]||[]:[];
    for(var i=tx.length;i<nm.length;i++)tx.push(g[0]==='unk'?(UNK[nm[i]]||(LABELS[nm[i]]||nm[i].replace(/_/g,' '))+' not checked'):(LABELS[nm[i]]||nm[i].replace(/_/g,' ')));
    return [g[0],g[1],tx];}).filter(function(g){return g[2].length;});}};
function go(){
  var box=document.querySelector('[data-radar]');if(!box)return;
  var T=window.MEMEBOT_RADAR_T;if(T&&typeof T==='object')Object.keys(T).forEach(function(k){R[k]=T[k];});
  // the repository: from the office's live view box (report.py puts it there only on a page built on GitHub Actions), so the radar's HTML
  // is the same with and without GITHUB_REPOSITORY and the GitHub poll, the raw copy and the Start / Stop links exist only where it is known
  var lbox=document.querySelector('[data-live-src]'),rm=/^https:\/\/api\.github\.com\/repos\/([A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/contents\//.exec(lbox?lbox.getAttribute('data-live-src')||'':''),repo=rm?rm[1]:'';
  var src=window.MEMEBOT_RADAR_SRC||(repo?'https://api.github.com/repos/'+repo+'/contents/radar.json?ref=radar-data':''),raw=window.MEMEBOT_RADAR_RAW||(repo?'https://raw.githubusercontent.com/'+repo+'/radar-data/radar.json':'');
  var tz=box.getAttribute('data-tz')||'UTC',tzn=box.getAttribute('data-tzn')||'UTC',root=document.documentElement;
  var sbUrl=String(root.getAttribute('data-sb-url')||'').replace(/\/+$/,''),sbKey=root.getAttribute('data-sb-key')||'';
  var KEY='memebot-radar '+(src||sbUrl||'page'),$=function(s){return box.querySelector(s);};
  var tR=document.getElementById('tab-young'),tO=document.getElementById('tab-office');     // the radar sits on top of the Radar tab
  var S={doc:null,got:0,moved:false,next:0,fails:0,rem:null,reset:0,remAt:0,last:0,at:0,via:'',back:0,kick:0,kickT:0},busy=false,key=null,cards=[],startA=null,ghNow=false,ghFor=null;
  try{S.doc=R.clean(JSON.parse(document.getElementById('radar-doc').textContent));}catch(e){}
  function now(){return Date.now();}
  // a tap on Start (S.kick, this phone's clock) until the round's doc comes (a doc other than the one shown then, kickT) or KICK is over
  function kicking(){var k=+S.kick||0,a=now()-k;return k>0&&a>=0&&a<R.KICK&&(S.doc?+S.doc.t:0)===(+S.kickT||0);}
  function inApp(){return root.classList.contains('app');}
  function view(){return tR&&tR.checked?'radar':inApp()?'app':tO&&tO.checked?'office':null;}
  // the tabs of one browser share one poll and its answer; a stored doc older than this page's keeps this page's doc and its times
  function load(){try{var s=JSON.parse(localStorage.getItem(KEY));if(!s||typeof s!=='object'||!(+s.at>S.at)||typeof s.next!=='number')return false;
    var d=R.clean(s.doc);if(d&&(!S.doc||d.t>=S.doc.t))s.doc=d;else{s.doc=S.doc;s.got=S.got;s.moved=S.moved;}S=s;return true;}catch(e){}return false;}
  function save(){S.at=now();try{localStorage.setItem(KEY,JSON.stringify(S));}catch(e){}}
  // the office poll's state (report.py's live script keeps it under "memebot-live <its source>"): the newest one carries GitHub's numbers
  function office(){var best=null;try{for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k&&k.indexOf('memebot-live ')===0){var o=JSON.parse(localStorage.getItem(k));
    if(o&&typeof o==='object'&&(!best||+o.at>+best.at))best=o;}}}catch(e){}return best;}
  function hhmm(t){try{return new Date(t).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:tz});}catch(e){return new Date(t).toTimeString().slice(0,5);}}
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
  function usd(v){if(!isn(v))return '?';var a=Math.abs(v),f=function(x){return x.toFixed(1).replace(/\.0$/,'');};return '$'+(a>=1e9?f(v/1e9)+'B':a>=1e6?f(v/1e6)+'M':a>=1e3?f(v/1e3)+'k':v.toFixed(0));}
  function pc(v){return isn(v)?(v>0?'+':v<0?'−':'')+Math.round(Math.abs(v))+'%':'?';}
  function mult(v){return isn(v)?(v>=10?Math.round(v):v.toFixed(2))+'x':'–';}
  function chip(text,cls){return el('span','chip'+(cls?' '+cls:''),text);}
  function link(name,url){var a=el('a','',name);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
  function lineEl(ln,k){ln=ln||[];var d=el('div','tline'),n=Math.min(ln.length,k||R.SHOWN),p=ln.length&&ln[0][1].length>R.LONG?1:R.PHONE;d.title=ln.map(function(x){return x[1];}).join(' · ');
    for(var i=0;i<n;i++){var s=el('span','tc '+ln[i][0]+(i>=p?' x2':'')),b=el('b','',IC[ln[i][0]]);b.setAttribute('aria-hidden','true');s.appendChild(b);s.appendChild(document.createTextNode(ln[i][1]));d.appendChild(s);}
    if(ln.length>n)d.appendChild(el('span','tc more m4','+'+(ln.length-n)));if(ln.length>p)d.appendChild(el('span','tc more m2','+'+(ln.length-p)));return d;}
  function kv(rows){var w=el('div','dkv');rows.forEach(function(r){if(r[1]==null||r[1]==='')return;var d=el('div');d.appendChild(el('span','k',r[0]));d.appendChild(el('span','v',r[1]));w.appendChild(d);});
    if(!w.children.length)return el('p','note','No numbers.');return w;}
  function val(v){return v==null?'unknown':typeof v==='boolean'?(v?'yes':'no'):isn(v)?(Math.round(v)===v?String(v):String(+v.toPrecision(3))):Array.isArray(v)?v.slice(0,6).map(val).join(', '):
    typeof v==='object'?Object.keys(v).slice(0,5).map(function(k){return k+' '+val(v[k]);}).join(' · '):String(v);}
  function dtabs(uid,parts,def){var w=el('div','dtabs');
    parts.forEach(function(p,i){var r=el('input');r.type='radio';r.name=uid;r.id=uid+'-'+i;if(i===def)r.checked=true;w.appendChild(r);});
    var bar=el('div','dtabbar');bar.setAttribute('role','tablist');parts.forEach(function(p,i){var l=el('label','',p[0]);l.htmlFor=uid+'-'+i;bar.appendChild(l);});w.appendChild(bar);
    var ps=el('div','dpanes');parts.forEach(function(p){var d=el('div','dpane');p[1].forEach(function(n){d.appendChild(n);});ps.appendChild(d);});w.appendChild(ps);return w;}
  function trapPane(c){var gs=R.groups(c);if(!gs.length)return [el('p','note','No check result.')];
    return gs.map(function(g){var w=el('div','tgrp '+g[0]),h=el('h5','',g[1]+' ');h.appendChild(el('span','',String(g[2].length)));w.appendChild(h);
      var ul=el('ul');g[2].forEach(function(t){var li=el('li','tc '+g[0]),b=el('b','',IC[g[0]]);b.setAttribute('aria-hidden','true');li.appendChild(b);li.appendChild(document.createTextNode(t));ul.appendChild(li);});
      var m=S.doc&&S.doc.model;w.appendChild(ul);if(g[0]==='info')w.appendChild(el('p','tnote',MEASURED+(m&&m.from!=='learned'&&isn(m.need)?' Radar data so far: '+(isn(m.n)?m.n:0)+' of '+m.need+' calls with a 1 h result.':'')));return w;});}
  function srvNow(n){var d=S.doc;return d?+d.t+R.age(d,n,S.got,S.moved):n;}
  function fresh(st,n){return R.live(st,S.doc,n,S.got,S.moved);}
  function emit(st){var n=now(),det={doc:S.doc,state:st,via:S.via||'embedded',good:fresh(st,n)?R.good(S.doc):0,now:srvNow(n)};R.last=det;
    try{window.dispatchEvent(new CustomEvent('memebot-radar',{detail:det}));}catch(e){}}
  function setText(e,t){if(e&&e.textContent!==t)e.textContent=t;}
  function ageText(c,live,docAge){var a=isn(c.age)?c.age+(live?docAge/60000:0):null,m=isn(c.mint)&&S.doc?(+S.doc.t-c.mint)/60000+(live?docAge/60000:0):null;
    return 'pool '+(a==null?'age ?':dur(a))+' · '+(m==null?'mint time unknown':'minted '+dur(m)+' ago');}
  function card(c,i,live,docAge,rec){
    var li=el('li','rcard'+(live?'':' dim')),det=el('details'),sm=el('summary');
    var top=el('div','rtop');top.appendChild(el('span','rsym',c.sym||'?'));wsMark(top,c);if(c.name&&c.name!==c.sym)top.appendChild(el('span','rname',c.name));
    var ag=el('span','rage',ageText(c,live,docAge));top.appendChild(ag);li._age=ag;li._c=c;sm.appendChild(top);
    var nums=el('div','rnums');[['liq',usd(c.liq)],['mc',usd(c.mc)],['5 min',pc(c.m5)]].forEach(function(x){var s=el('span');s.appendChild(el('i','',x[0]));s.appendChild(document.createTextNode(x[1]));nums.appendChild(s);});
    sm.appendChild(nums);
    var ch=el('div','rchips'),vd=R.verdict(c);ch.appendChild(chip(vd[1],'tv'+(live?' '+vd[0]:'')));if(!live)ch.appendChild(chip('as of '+hhmm(+S.doc.t)));
    // the learning trader skips coins with these signs (no push for them; still rated, listed and bought on paper)
    if(c.t3&&c.t3.length){var t3=chip('Learning trader skips: '+c.t3.join(', '),'t3');t3.title='The learning trader skips coins with this sign, so no push went out for it';ch.appendChild(t3);}
    ch.appendChild(el('span','rmore','details ›'));sm.appendChild(ch);
    sm.appendChild(lineEl(c.line,R.CARD));if(c.pb===1)sm.appendChild(el('p','rpaper',box.getAttribute('data-paper')||'Bought on paper'));det.appendChild(sm);
    var d=c.d||{},ov=[['price',isn(c.px)?'$'+(+c.px.toPrecision(3)):null],['pool age',ageText(c,live,docAge)],['liquidity',usd(c.liq)],['market cap',usd(c.mc)],['change in 5 min',pc(c.m5)],
      ['buys / sells',isn(c.buys)?Math.round(c.buys)+' / '+(isn(c.sells)?Math.round(c.sells):'?'):null],['first seen',isn(c.first)?hhmm(c.first):null],['found by',(c.found||[]).join(', ')||null],
      ['DEX',c.dex||null],['launchpad',c.lp||null]];
    var parts=[['Overview',[kv(ov)]],['Trap check',trapPane(c)],['Numbers',[kv(Object.keys(d).sort().map(function(k){return [SK[k]||k,val(d[k])];}))]]];
    var od=R.odds(d);if(od)parts[0][1].push(el('p','tnote','Trained odds (info only): '+p0(od[0])+' profit'+(isn(od[1])?', '+p0(od[1])+' zero':'')+'. Not used: on coins under 1 h they did not separate winners.'));
    if(rec){var lp=[laterTable([rec])];if(rec.peak60)lp.push(el('p','tnote','Best close within 1 h (hindsight): '+mult(rec.peak60.x)+(isn(rec.peak60.at)?' at '+hhmm(rec.peak60.at):'')));
      parts.push(['Later',lp]);}
    det.appendChild(dtabs('rd'+i+'-'+(+S.doc.t%1e7),parts,1));li.appendChild(det);
    var ft=el('div','rfoot');
    ft.appendChild(link('DexScreener','https://dexscreener.com/solana/'+(c.pair||c.addr)));
    if(/pump$/.test(c.addr))ft.appendChild(link('pump.fun','https://pump.fun/coin/'+c.addr));
    if(c.x)ft.appendChild(link('X',c.x));
    if(isn(c.push))ft.appendChild(el('span','rpush','pushed '+hhmm(c.push)));
    li.appendChild(ft);return li;}
  function laterTable(rows){var w=el('div','rrec-w'),t=el('table','rrec'),hd=el('tr');w.appendChild(t);['time','coin','5 min','15 min','30 min','1 h',''].forEach(function(h){hd.appendChild(el('th','',h));});
    var th=el('thead');th.appendChild(hd);t.appendChild(th);var tb=el('tbody');
    rows.forEach(function(r){var tr=el('tr');tr.appendChild(el('td','',isn(r.good)?hhmm(r.good):'?'));tr.appendChild(el('td','',r.sym||'?'));
      ['5','15','30','60'].forEach(function(k){var v=r.later?r.later[k]:null;tr.appendChild(el('td','mx '+(!isn(v)?'na':v>=1?'up':'dn'),mult(v)));});
      // the 1 h outcome: ✓ only for a call alive at 1x or more; one alive below its call price is neutral (↓), never a check mark
      var o=r.out,x1=o&&isn(o.x60)?o.x60:r.later?r.later['60']:null,
        oc=o&&o.rug1h?['bad','✕','rugged']:o&&o.win1h?['good','⇈','2x']:(o||isn(x1))?(isn(x1)&&x1>=1?['','✓','alive, up']:isn(x1)?['muted','↓','alive, down']:['muted','·','alive']):r.miss60?['na','–','no 1 h price']:['muted','…','pending'];
      var td=el('td','oc '+oc[0],oc[1]);td.title=oc[2];td.appendChild(el('span','ow',' '+oc[2]));tr.appendChild(td);tb.appendChild(tr);});
    t.appendChild(tb);w.appendChild(el('p','tnote','✓ alive and up · ↓ alive but down · ✕ rugged · ⇈ 2x, 1 h after the call; multiples of the price at the call (hindsight, fake money); – no round caught that price'));return w;}
  // the patterns (record.pat, hindsight): the head line, the signals as a chip and the share of rugged and of doubled coins that had it (R.patRow; a
  // hint that could be chance muted, with a '?' and a note under the table: a phone shows no title), the rugged coins with the flags their hour's
  // doubled coins mostly lacked
  function patBox(p){var f=document.createDocumentFragment(),h=R.patHead(p),ws=p.why.map(function(x){return R.whyLine(x,hhmm);}).filter(Boolean),maybe=false;if(h)f.appendChild(el('p','note',h));
    if(p.rows.length){var t=el('table','rpat'),hd=el('tr'),th=el('thead'),tb=el('tbody');['','of crashed','of doubled'].forEach(function(x){hd.appendChild(el('th','',x));});th.appendChild(hd);t.appendChild(th);
      p.rows.forEach(function(x){var r=R.patRow(x),tr=el('tr',r[3]?'':'maybe'),td=el('td'),c=el('span','tc '+r[4]),b=el('b','',IC[r[4]]);tr.title=r[5];b.setAttribute('aria-hidden','true');
        c.appendChild(b);c.appendChild(document.createTextNode(r[0]));td.appendChild(c);if(!r[3]){td.appendChild(el('span','rq','?'));maybe=true;}
        tr.appendChild(td);tr.appendChild(el('td','',r[1]));tr.appendChild(el('td','',r[2]));tb.appendChild(tr);});
      t.appendChild(tb);f.appendChild(t);if(maybe)f.appendChild(el('p','tnote','? could be chance'));}
    if(ws.length){var ul=el('ul','rpwhy');ws.forEach(function(s){ul.appendChild(el('li','',s));});f.appendChild(ul);}
    return f;}
  function wsMark(box,c){if(R.wsOn(c,S.doc&&S.doc.model)){var s=el('span','rws','▲');s.title='orders like past doubled coins (hindsight)';s.setAttribute('aria-label',s.title);box.appendChild(s);}return box;}
  // the full scan's next start (ms): the scan strip's on Pick (page_office.scan_strip), 0 without it
  function scanNext(){var b=document.querySelector('[data-sstrip]');return b?+b.getAttribute('data-next')||0:0;}
  function nextW(st,n){return st==='done'&&S.doc?R.nextWords(S.doc,srvNow(n),scanNext(),hhmm):'';}
  function pill(st){var d=S.doc,t,w=R.round(d)?'last round ':'last check ';
    if(kicking())t='Waiting for the new round'+(d?' · last '+hhmm(+d.t):'');
    else if(st==='done')t='Last round '+hhmm(+d.t)+(d.state==='degraded'?' had errors':'')+' · '+nextW(st,now());
    else if(st==='running')t='Radar running · checked '+hhmm(+d.t)+(isn(d.next)?' · next '+hhmm(d.next):'')+(d.state==='degraded'?' · with errors':'');
    else if(st==='late')t='Radar late · '+w+hhmm(+d.t);
    else if(st==='stopped')t='Radar stopped · '+w+hhmm(+d.t);
    else if(st==='off')t='Radar off · switched off on GitHub';
    else if(st==='hours')t='Radar sleeping'+(isn(d.next)?' · next start '+hhmm(d.next):'');
    else t='Radar not started yet';
    if(S.via==='raw'&&d)t+=' · slower copy, as of '+hhmm(+d.t);return t;}
  // the curve watch's section under the list (page_radar.curve_inner builds the same elements): redrawn when its view changes (a new doc, or a
  // status moving on with the doc's age), its folds kept open across a redraw
  var cvKey=null;
  function ctable(head,rows){var w=el('div','rrec-w'),t=el('table','rc-tab'),th=el('thead'),hr=el('tr'),tb=el('tbody');
    head.forEach(function(h){hr.appendChild(el('th','',h));});th.appendChild(hr);t.appendChild(th);
    rows.forEach(function(r){var tr=el('tr',r.cls);tr.title=r.title;r.cells.forEach(function(c){tr.appendChild(el('td','',c));});tb.appendChild(tr);});t.appendChild(tb);w.appendChild(t);return w;}
  function ccoin(c){var li=el('li','rc-coin'),a=el('a','rc-top');a.href='https://pump.fun/coin/'+c.mint;a.target='_blank';a.rel='noopener noreferrer';
    a.appendChild(el('span','rc-sym',c.sym));a.appendChild(el('span','rc-p',c.prog));a.appendChild(el('span','rc-s'+(c.st[0]?' '+c.st[0]:''),c.st[1]));li.appendChild(a);
    li.appendChild(el('p','rc-n',c.nums));li.appendChild(lineEl(c.line,CV.line));if(c.res)li.appendChild(el('p','rc-r'+(c.res[0]?' '+c.res[0]:''),c.res[1]));return li;}
  function curveDraw(n){var box=$('[data-r-curve]');if(!box)return;
    var d=S.doc,v=d&&d.curve?R.curveView(d.curve,srvNow(n)):null,k=JSON.stringify(v);if(k===cvKey)return;cvKey=k;
    var open={};Array.prototype.forEach.call(box.querySelectorAll('details[data-cf]'),function(x){open[x.getAttribute('data-cf')]=x.open;});
    box.className='rcurve'+(v&&v.one?' one':'');box.hidden=!v;box.textContent='';if(!v)return;
    if(v.one){var p1=el('p','rc-one');p1.appendChild(el('b','','About to graduate (paper test):'));p1.appendChild(document.createTextNode(' no call yet · '+v.head));box.appendChild(p1);return;}
    var hd=el('div','rc-h'),h3=el('h3','','About to graduate '),st=el('p','rc-st');h3.appendChild(el('small','','(paper test)'));st.setAttribute('data-st',v.state);
    st.appendChild(el('i','rdot'));st.appendChild(el('span','',v.head));hd.appendChild(h3);hd.appendChild(st);box.appendChild(hd);
    box.appendChild(el('p','rc-note',v.note));box.appendChild(el('p','rc-push'+(v.pushOn?' on':''),v.push));
    if(v.coins.length){var ol=el('ol','rc-list');v.coins.forEach(function(c){ol.appendChild(ccoin(c));});box.appendChild(ol);}
    if(v.more.length){var dm=el('details','rc-more'),ol2=el('ol','rc-list');dm.setAttribute('data-cf','more');dm.appendChild(el('summary','',v.more.length+' more coin'+(v.more.length===1?'':'s')));
      v.more.forEach(function(c){ol2.appendChild(ccoin(c));});dm.appendChild(ol2);if(open.more)dm.open=true;box.appendChild(dm);}
    if(v.rows.length)box.appendChild(ctable(['','calls','graduated','rugged in 1 h','doubled in 1 h','paper per '+v.ticket],v.rows));
    box.appendChild(el('p','tnote',v.foot));
    if(v.by.length){var db=el('details','rc-by');db.setAttribute('data-cf','by');db.appendChild(el('summary','','Split by the quick check'));
      db.appendChild(ctable(['','quick check','calls','rugged in 1 h','doubled in 1 h','paper per '+v.ticket],v.by));if(open.by)db.open=true;box.appendChild(db);}}
  function draw(){
    var n=now(),st=R.radarState(S.doc,n,S.got,S.moved),d=S.doc,docAge=d?R.age(d,n,S.got,S.moved):0,live=fresh(st,n),kw=kicking(),k=[d?d.t:0,st,live,S.via,nextW(st,n),kw].join('|');   // the next words too: the office follows once its time has passed
    try{curveDraw(n);}catch(e){}     // the curve section on its own key: a status that moves on with the doc's age redraws it alone
    var p=$('[data-r-pill]');if(p){p.setAttribute('data-st',st);if(st==='done'&&d.state==='degraded')p.setAttribute('data-err','');else p.removeAttribute('data-err');
      if(kw)p.setAttribute('data-wait','');else p.removeAttribute('data-wait');setText($('[data-r-pill-t]'),pill(st));}
    if(startA)startA.className='rbtn'+(st==='running'?' quiet':'');    // a tap while a loop runs only queues a run; between rounds Start is one more round
    // the website's Radar label: the radar's count of coins without traps while its list is current (one number, as the app's badge)
    var tc=document.querySelector('[data-r-tabcnt]'),g=live?R.good(d):0;if(tc){tc.hidden=!g;setText(tc,String(g));tc.className='cnt'+(g?' good':'');}
    if(k===key){cards.forEach(function(li){setText(li._age,ageText(li._c,live,docAge));});return;}
    key=k;emit(st);
    var stats=$('[data-r-stats]'),notes=$('[data-r-notes]'),list=$('[data-r-cards]'),empty=$('[data-r-empty]'),of=$('[data-r-others]'),rf=$('[data-r-rec]');
    stats.textContent='';notes.textContent='';list.textContent='';cards=[];
    var has=!!d&&['running','done','late','stopped'].indexOf(st)>=0,cn=d?d.counts:{};
    stats.hidden=!has;stats.className='rstats'+(live||st==='done'?'':' dim');
    if(has)[[cn.seen,'seen',''],[cn.good,'no trap found',cn.good?'good':''],[cn.pushed,'pushed',''],[isn(cn.seenAgeMed)?Math.round(cn.seenAgeMed)+' min':null,'median age','']].forEach(function(x){
      var c=el('div',x[2]);c.appendChild(el('b','',x[0]!=null?String(x[0]):'?'));c.appendChild(el('span','',x[1]));stats.appendChild(c);});
    var nts=d&&has?d.notes.slice():[];
    if(has&&(!isn(d.wm.t)||+d.t-d.wm.t>3*3600000)&&!nts.some(function(x){return /wallet/i.test(x);}))nts.push('wallet check unavailable: no greens until the wallet memory is back');
    // a host the radar found limited or down, when its own notes do not name it ("unused" and "off" are routine: not shown)
    if(has)Object.keys(d.hosts).forEach(function(h){var v=d.hosts[h],w=h==='pumpportal'?'live feed':h;     // the pump.fun feed by what it is
      if((v==='limited'||v==='down')&&!nts.some(function(x){return x.toLowerCase().indexOf(w.toLowerCase())>=0;}))nts.push(w+': '+v);});
    nts.forEach(function(x){notes.appendChild(el('li','',x));});notes.hidden=!nts.length;
    var good=has?d.coins.filter(function(c){return c.v==='good';}):[],byAddr={};
    (d&&d.recent||[]).forEach(function(r){byAddr[r.addr]=r;});
    good.forEach(function(c,i){var li=card(c,i,live,docAge,byAddr[c.addr]);cards.push(li);list.appendChild(li);});
    list.hidden=!good.length;empty.hidden=!!good.length;
    if(!good.length){var big,sub='';
      if(st==='none'){big='Radar not started yet';sub='It starts with the next full scan, or tap Start.';}
      else if(st==='off'){big='Radar is switched off';sub='Start: enable the workflow on GitHub.';}
      else if(st==='hours'){big='Radar sleeping';sub=isn(d.next)?'The next round comes with the first scan after '+hhmm(d.next)+'.':'Outside its hours.';}
      else{big=live&&st==='running'?'No coin without traps right now':'No coin without traps at '+hhmm(+d.t);var s=isn(cn.seen)?cn.seen:d.others.length;
        sub=(s?s+' seen under 10 min · all with traps or not fully checked':'Nothing under 10 min old seen')+(R.round(d)?' · one round an hour':'');}
      setText($('[data-r-empty-t]'),big);setText($('[data-r-empty-s]'),sub);
      var lg=$('[data-r-lastgood]'),l=d&&d.lastGood;lg.hidden=!(l&&isn(l.at));if(!lg.hidden)setText(lg,'last coin without traps: '+(l.sym||'?')+', '+R.ago(srvNow(n)-l.at));}
    var oth=has?d.others:[],ol=$('[data-r-olist]');ol.textContent='';of.hidden=!oth.length;of.classList.toggle('dim',!live);setText($('[data-r-ocnt]'),String(oth.length));
    oth.forEach(function(c){var li=el('li','rrow '+(c.v==='trap'?'bad':'warn')),vd=R.verdict(c);li.title=vd[1];
      li.appendChild(wsMark(el('span','rs',vd[1].charAt(0)+' '+(c.sym||'?')),c));li.appendChild(el('span','ra',isn(c.age)?'pool '+dur(c.age+(live?docAge/60000:0)):''));li.appendChild(lineEl(c.line,3));ol.appendChild(li);});
    var rr=d?d.recent.filter(function(r){return isn(r.good)&&srvNow(n)-r.good<=R.RECENT;}).sort(function(a,b){return b.good-a.good;}):[],rl=R.recLine(d&&d.record);
    var rcd=d&&d.record,ml=R.momLine(rcd&&rcd.mom,rcd&&rcd.all),pt=rcd&&rcd.pat;     // the momentum line and the patterns: hindsight, never a push
    rf.hidden=!(rr.length||rl||ml||pt);setText($('[data-r-recline]'),R.recShort(d&&d.record)||rr.length+' call'+(rr.length===1?'':'s')+' in the last 3 h');
    var rc=$('[data-r-recent]');rc.textContent='';if(rl)rc.appendChild(el('p','note rrline',rl));
    if(ml)rc.appendChild(el('p','note rrmom',ml));if(pt)rc.appendChild(patBox(pt));
    if(rr.length)rc.appendChild(laterTable(rr));else rc.appendChild(el('p','note','No call without traps in the last 3 hours.'));
    var md=$('[data-r-model]'),m=d&&d.model;if(md)setText(md,!m?'':(m.from==='learned'?'Weights: learned on '+(m.n||'?')+' calls'+(isn(m.auc)?' · ranking quality '+m.auc.toFixed(2)+' ('+(isn(m.prior)?'study weights '+m.prior.toFixed(2)+', ':'')+'coin toss 0.50)':''):
      'Weights: study prior'+(isn(m.need)?' · radar data '+(isn(m.n)?m.n:0)+' of '+m.need+' needed':'')+(m.why?' · '+m.why:''))+(m.win&&m.win.from==='learned'?' · win order learned on '+(isn(m.win.n)?m.win.n:'?')+' coins':''));
  }
  function took(d,via){d=R.clean(d);if(!d)return false;var o=S.doc;
    if(o&&d.t<o.t)return true;                                  // an older copy (the CDN) never replaces a newer doc
    if(!(o&&o.t===d.t)||!S.got){S.moved=!!(o&&S.got>0&&d.t>o.t);S.got=now();}S.doc=d;return true;}
  function fetchT(url,opt,ms_){var ac=window.AbortController?new AbortController():null,tm;opt.signal=ac?ac.signal:undefined;
    var cut=new Promise(function(ok,no){tm=setTimeout(function(){if(ac)ac.abort();no(0);},ms_);});
    return Promise.race([fetch(url,opt),cut]).then(function(r){clearTimeout(tm);return r;},function(e){clearTimeout(tm);throw typeof e==='number'?e:0;});}
  function decode(b64){var s=atob(String(b64||'').replace(/\s+/g,'')),u=new Uint8Array(s.length);for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return JSON.parse(new TextDecoder('utf-8').decode(u));}
  // the live store: one GET of the row "radar" with the publishable key in the apikey header (sbGetRow: no agents check)
  function sbGetRow(id){return fetchT(sbUrl+'/rest/v1/live?id=eq.'+id+'&select=doc,updated',{headers:{apikey:sbKey,Accept:'application/json'},cache:'no-store'},R.SB_TIMEOUT)
    .then(function(r){if(!r.ok)throw r.status||0;return r.json();}).then(function(rows){return Array.isArray(rows)&&rows[0]?rows[0].doc:null;});}
  function ghGet(){return fetchT(src,{headers:{Accept:'application/vnd.github.raw+json'},cache:'no-cache'},R.TIMEOUT).then(function(r){
    var h=r.headers.get('X-RateLimit-Remaining');if(h!=null&&h!==''&&!isNaN(+h)){S.rem=+h;S.reset=+r.headers.get('X-RateLimit-Reset')||0;S.remAt=now();}
    if(r.status===404)return null;if(!r.ok)throw r.status||0;return r.text();}).then(function(t){if(t==null)return null;var j=JSON.parse(t);
    if(j&&typeof j.content==='string'&&j.encoding==='base64')j=decode(j.content);return j;});}
  function rawGet(){return fetchT(raw+(raw.indexOf('?')<0?'?':'&')+'m='+Math.floor(now()/60000),{cache:'no-cache'},R.TIMEOUT).then(function(r){if(r.status===404)return null;if(!r.ok)throw r.status||0;return r.json();});}
  // the page on its way out (a reload: the site's own after a long break, report.py's after a new scan; both set MEMEBOT_RELOADING to the time):
  // no poll, and one cut off by it is no failure (it would hold the next poll back on the reloaded page). Both marks end after LEAVE: a reload
  // that never happened (stopped, offline) must not stop the radar for good
  var leaving=0;function gone(){var r=+window.MEMEBOT_RELOADING||0,n=now();return leaving>0&&n-leaving<R.LEAVE||r>0&&n-r<R.LEAVE;}
  window.addEventListener('beforeunload',function(){leaving=now();});window.addEventListener('pagehide',function(){leaving=now();});
  function poll(){
    var v=view();if(busy||gone()||document.visibilityState!=='visible'||!v)return;
    if(load())draw();
    if(now()<S.next)return;
    var b=R.budget(office(),S),via=R.radarTransport(sbUrl,sbKey,src,b.rem,b.reset,now(),S.back);
    if(via==='raw'&&!raw)via='none';
    if(via==='none')return;
    busy=true;S.next=now()+R.TIMEOUT+5000;save();
    (via==='supabase'?sbGetRow('radar'):via==='raw'?rawGet():ghGet()).then(function(d){if(d!=null&&!took(d,via))throw 0;return d;}).then(function(d){S.fails=0;
      // the live store answered, but its row is missing or reads stopped (the radar's write to it failing): GitHub right away, once per
      // doc the page holds (a radar that is really stopped costs one call); with no doc at all the radar has not run: GitHub is not asked
      var st=R.radarState(S.doc,now(),S.got,S.moved);
      if(via==='supabase'&&src&&S.doc&&(d==null||st==='stopped')&&ghFor!==+S.doc.t){ghFor=+S.doc.t;S.back=now()+R.SB_RETRY;ghNow=true;}},function(code){if(gone())return;
      S.fails=(+S.fails||0)+1;if(via==='supabase'&&(code===540||S.fails>=2)){S.back=now()+R.SB_RETRY;S.fails=0;}})
    .then(function(){busy=false;if(gone())return;S.via=via;S.last=now();var b2=R.budget(office(),S);
      S.next=ghNow?now()+1000:R.radarNext({doc:S.doc,now:now(),last:S.last,tab:view()||'radar',via:via,rem:b2.rem,reset:b2.reset,fails:S.fails,got:S.got,moved:S.moved,kick:kicking()});ghNow=false;
      if(via!=='supabase'&&sbUrl&&sbKey&&+S.back>now())S.next=Math.min(S.next,Math.max(+S.back,now()+1000));   // GitHub only stood in: the live store's pace again once it may be asked
      save();try{draw();}catch(e){}});
  }
  // a tab change: the next poll comes at the new tab's pace (sooner on the Radar tab), never before the budget allows; New opened after a
  // break asks at once (wake)
  function retime(){if(!S.last||busy)return;var b=R.budget(office(),S);S.next=Math.min(S.next,R.radarNext({doc:S.doc,now:now(),last:S.last,tab:view()||'radar',via:S.via,rem:b.rem,reset:b.reset,fails:S.fails,got:S.got,moved:S.moved,kick:kicking()}));}
  Array.prototype.forEach.call(document.querySelectorAll('input[name="tab"]'),function(r){r.addEventListener('change',function(){retime();if(view()==='radar')wake();poll();});});
  window.addEventListener('storage',function(e){if(e.key===KEY&&load())try{draw();}catch(x){}});
  // back on the page (the app opened again, the tab shown, GitHub's page closed after a Start): on the live store a poll now when the last one
  // is SB_FRESH old; on GitHub at GH_MIN after the last one and never before the shared budget allows (radarNext); not while polls fail. A
  // round by hand shows at once
  function wake(){if(document.visibilityState!=='visible')return;leaving=0;      // shown again: not leaving (iOS can send pagehide for a mere app switch)
    if(busy||gone()||+S.fails>0)return;var b=R.budget(office(),S),via=R.radarTransport(sbUrl,sbKey,src,b.rem,b.reset,now(),S.back);
    if(via==='supabase'){if(now()-(+S.last||0)>=R.SB_FRESH)S.next=Math.min(S.next,now());}
    else if(S.last)S.next=Math.min(S.next,R.radarNext({doc:S.doc,now:now(),last:S.last,tab:view()||'radar',via:via,rem:b.rem,reset:b.reset,fails:S.fails,got:S.got,moved:S.moved,kick:true}));
    poll();}
  document.addEventListener('visibilitychange',wake);window.addEventListener('pageshow',wake);window.addEventListener('focus',wake);
  // #tab-radar, #radar, #tab-young or #new (the old Radar and New links) open the Radar tab once in a browser tab, #tab-pick, #tab-account and
  // #tab-office their own tab; the installed app reads the hash itself (app.py PAGE_JS)
  setTimeout(function(){var h=location.hash,m=/^#tab-(pick|account|office)$/.exec(h),tab=/^#(tab-radar|radar|tab-young|new)$/.test(h)?tR:m?document.getElementById('tab-'+m[1]):null;
    if(!inApp()&&tab){tab.checked=true;try{tab.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){}
    try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}if(document.activeElement===tab)tab.blur();}},0);   // the jump to the radio must not ring every tab
  var act=box.querySelector('[data-r-actions]');       // Start and Stop: plain links to the radar's page on GitHub (no token, nothing is started from here)
  if(act&&repo){var wf='https://github.com/'+repo+'/actions/workflows/radar.yml',inf=el('details','rinfo'),sm=el('summary','','\u24d8');
    startA=el('a','rbtn','Start \u2197');[startA,el('a','rbtn quiet','Stop \u2197')].forEach(function(a){a.href=wf;a.target='_blank';a.rel='noopener';act.appendChild(a);});
    // a tap on Start: the page waits for that round (the pill says so) and asks every SB_FRESH (GitHub: GH_MIN, the budget and a failure's back-off
    // still win: retime) until it comes, KICK at most; outside the radar's hours no round comes, the pill keeps "Radar sleeping"
    startA.addEventListener('click',function(){if(R.radarState(S.doc,now(),S.got,S.moved)==='hours')return;
      S.kick=now();S.kickT=S.doc?+S.doc.t:0;retime();save();key=null;try{draw();}catch(e){}});
    sm.setAttribute('aria-label','About start and stop');inf.appendChild(sm);inf.appendChild(el('p','',INFO));act.appendChild(inf);act.hidden=false;}
  load();try{draw();}catch(e){}
  setInterval(function(){poll();try{draw();}catch(e){}},1000);
  setTimeout(function(){emit(R.radarState(S.doc,now(),S.got,S.moved));poll();},0);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
})();
""".replace("__CURVE__", json.dumps({"thr": list(CURVE_THR), "v": list(CURVE_V), "vw": CURVE_VW, "how": list(CURVE_HOW), "states": list(CURVE_STATES), "hosts": list(CURVE_HOSTS),
                                    "ctrl": CURVE_CTRL, "blank": CURVE_BLANK, "recent": CURVE_RECENT, "shown": CURVE_SHOWN, "line": CURVE_LINE, "few": CURVE_FEW,
                                    "value": CURVE_VALUE_MS, "big": CURVE_BIG, "late": CURVE_LATE_S})).replace("__INFO__", json.dumps(INFO_TEXT)).replace("__LABELS__", json.dumps(LABELS)).replace("__UNKNOWN__", json.dumps(UNKNOWN)).replace("__SKEYS__", json.dumps(SKEYS)).replace("__MEASURED__", json.dumps(MEASURED_NOTE)).replace("__T3__", json.dumps(T3_MAX))
