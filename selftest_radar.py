#!/usr/bin/env python3
"""selftest_radar.py: the launch radar's checks R1-R10 (SPEC 11), R11 (the WP0 probe's findings applied: adapter defaults, routes,
rate rules), R12 (one round per start: no successor, the later prices hourly rounds can catch), R13 (2-minute rounds, momentum on
paper) and R14 (the push's why and record; pump.fun replies and the source tweet's likes measured at first sight, at most 2 lookups a
cycle), against a local mock of every host it asks, a fake clock (cadence 1 s, 150 s of clock time a cycle; 120 s in R13), a local
bare git remote and a local stand-in for the app's live store; R15 (the fast lane after a graduation on the live feed: the coin rated
within seconds, its lag in the record, one push, only the requests it needs), R16 (radar.json's curve block) and R17 (the fast lane's
push against app's rate guard and the next round). Fake money only.

  python3 selftest_radar.py        runs the checks on their own (PASS/FAIL per check, "RADAR ALL PASS" at the end)
  checks(check, env=None)          the same from selftest.py's main (check(ok, what) as there)
  mock_routes(method, path, query, body)
                                   the radar's own routes for selftest.py's Mock (GitHub's workflow API and the fixture coins of the
                                   last mock made here); None for every other request, so hooking it in changes no existing answer

traps.py (WP1) and peak.py (WP2) are other work packages. When they are not importable here, a minimal stand-in that follows the
spec's rules (SPEC 5 WP1 rate, 7.3 chips, 4.8 fit) is used for these checks only; it is never written into the repository. The
notification itself is app.notify_radar (WP4): without it, a recording stand-in takes the notifications and the PushSink leg is
skipped (named at the end).
"""
import base64, contextlib, glob, gzip, io, json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, types, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PY = sys.executable
BASE = "80e7fe0"
T0 = 1791892800000                # 2026-10-13 12:00 UTC (14:00 Berlin): the fake clock's start
MIN = 60_000
H = 3_600_000
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
GH_TOKEN = "ghs_TESTradarTOKEN_0123456789abcdef"          # never in any output, file or branch
REPO = "tester/meme-bot"
SKIPPED = []
MOCK = None                       # the last RadarMock made: mock_routes answers from it
MOCKS = []                        # every RadarMock made: run_radar points their clocks at the radar's fake clock


def addr(seed, suffix="pump"):
    rng = random.Random(seed)
    return "".join(rng.choice(ALPH) for _ in range(44 - len(suffix))) + suffix


# ---------------------------------------------------------------- stand-ins for traps.py and peak.py (used only when they are missing)
TRAPS_STANDIN = r'''
"""A minimal stand-in for traps.py (WP1) for selftest_radar.py only: the spec's rules, nothing more."""
import math, re
BRAND = r"\b(google|apple|nvidia|openai|chatgpt|gpt|gemini|grok|deepseek|tesla|elon|musk|trump|mrbeast|nike|amazon|microsoft|meta|spacex|xai|binance|pokemon)\b"
M_SIG = {"dev_dead": lambda S: (S.get("devN") or 0) >= 3 and (S.get("devDead") or 0) >= 0.8 * (S.get("devN") or 1),
         "dev_young": lambda S: S.get("devAgeH") is not None and S["devAgeH"] < 24,
         "x_copied": lambda S: (S.get("xUsed") or 0) >= 1, "tweet_shared": lambda S: (S.get("tweetShared") or 0) >= 1,
         "sniped30": lambda S: (S.get("snip30") or 0) >= 0.3, "bundle_slot": lambda S: (S.get("slotN") or 0) >= 4,
         "fresh_holders": lambda S: (S.get("freshN") or 0) >= 5, "fund_cluster": lambda S: (S.get("fundN") or 0) >= 3,
         "staircase_early": lambda S: isinstance(S.get("stair"), dict) and 6 <= (S["stair"].get("n") or 0) < 10 and bool(S["stair"].get("stair"))}


def load_weights(path=None):
    return {"v": 1, "src": "stand-in", "hard": ["instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "staircase10"],
            "soft": ["no_socials", "holder_cluster", "creator_sold", "pumping_5m"], "maxSoft": 1, "pushBlock": ["holder_cluster"],
            "points": {"hard": 3, "brand_name": 2, "bot_volume": 2, "no_rc_report": 2, "soft": 1, "young_5m": 1, "good": -1}, "brand": BRAND}


def norm_x(url):
    u = str(url or "").strip()
    m = re.match(r"^https?://(?:www\.)?(?:x|twitter)\.com/(.+?)/?(?:\?.*)?$", u, re.I)
    if not m:
        return None
    p = m.group(1).lower().rstrip("/")
    if re.match(r"^i/communities/\d+", p):
        return "community", "x.com/" + p
    if re.match(r"^[a-z0-9_]{1,30}/status/\d+", p):
        return "tweet", "x.com/" + "/".join(p.split("/")[:3])
    if re.match(r"^[a-z0-9_]{1,30}$", p):
        return "account", "x.com/" + p
    return None


def _uses(e):
    if not isinstance(e, list) or len(e) < 6 or not isinstance(e[5], list):
        return []
    return e[5] if e[5] else ([[e[0], e[1]]] if e[0] else [])


def x_reuse(url, addr, first_ms, links, gap_s=600):
    nk = norm_x(url)
    out = {"kind": nk[0] if nk else None, "key": nk[1] if nk else None, "used": None, "shared": None}
    if not nk:
        return out
    uses = _uses((links or {}).get(nk[1]))
    if nk[0] == "tweet":
        out["used"], out["shared"] = 0, sum(1 for u in uses if u[0] != addr)
        return out
    out["used"] = sum(1 for u in uses if u[0] != addr and u[1] <= first_ms - gap_s * 1000)
    out["shared"] = 0
    return out


def staircase(closes, n_min=10):
    cs = [c for c in closes or [] if c]
    if len(cs) < 2:
        return {"n": len(cs), "rise": None, "green": None, "pull": None, "stair": False}
    rise = cs[-1] / cs[0] - 1
    green = sum(1 for a, b in zip(cs, cs[1:]) if b > a) / (len(cs) - 1)
    peak, pull = cs[0], 0.0
    for c in cs:
        peak = max(peak, c)
        pull = max(pull, 1 - c / peak)
    return {"n": len(cs), "rise": rise, "green": green, "pull": pull, "stair": len(cs) >= 6 and rise >= 0.2 and green >= 0.7 and pull < 0.05}


def walletmem_lookup(holders, wm, now=None):
    if not wm or not holders:
        return {"swAvg": None, "rugHolders": None, "checked": False}
    common, rug, sw = set(wm.get("common") or []), set(wm.get("rug") or []), wm.get("sw") or {}
    hs = [h for h in holders if h not in common]
    avg = [sw[h] for h in hs if h in sw]
    return {"swAvg": sum(avg) / len(avg) if avg else None, "rugHolders": sum(1 for h in hs if h in rug), "checked": True}


def signals_scan(y, pr_mint_ms, wm):
    raise NotImplementedError("stand-in")


def signals_radar(c):
    return {k: c.get(k) for k in c if not isinstance(c.get(k), dict) or k == "stair"}


def _flags(S, W):
    hard = []
    if S.get("instantPool"):
        hard.append("instant_pool")
    if (S.get("swAvg") is not None and S["swAvg"] <= -7) or (S.get("rugHolders") or 0) >= 3:
        hard.append("rugger_wallets")
    if S.get("brand"):
        hard.append("brand_name")
    if (S.get("buys") or 0) >= 3000:
        hard.append("bot_volume")
    if S.get("rcDanger"):
        hard.append("rc_danger")
    st = S.get("stair")
    if isinstance(st, dict) and st.get("stair") and (st.get("n") or 0) >= 10:
        hard.append("staircase10")
    soft = []
    if S.get("socN") is not None and S["socN"] <= 0:
        soft.append("no_socials")
    if S.get("cluster"):
        soft.append("holder_cluster")
    if S.get("creatorSold"):
        soft.append("creator_sold")
    if (S.get("m5") or 0) >= 20:
        soft.append("pumping_5m")
    info = [k for k, f in M_SIG.items() if f(S)]
    for k in info:
        if k in (W.get("soft") or []):
            soft.append(k)
    return hard, soft, info


def rate(S, W):
    hard, soft, info = _flags(S, W)
    P = W.get("points") or {}
    unknown = []
    if S.get("rcReport") is not True:
        unknown.append("rc_report")
    if S.get("mintToPoolS") is None:
        unknown.append("mint_time")
    if S.get("wmChecked") is not True:
        unknown.append("walletmem")
    for k in ("brand", "buys"):
        if S.get(k) is None:
            unknown.append(k)
    if S.get("rcReport") is True and S.get("rcDanger") is None:
        unknown.append("rc_danger")
    plus = []
    if S.get("x") and S.get("paid"):
        plus.append("x_and_paid")
    if S.get("tweet"):
        plus.append("tweet")
    if (S.get("lists") or 0) >= 3:
        plus.append("lists3")
    hp = sum(P.get(h, P.get("hard", 3)) for h in hard)
    pts = hp + len(soft) * P.get("soft", 1) + (P.get("no_rc_report", 2) if S.get("rcReport") is not True else 0) + \
        (P.get("young_5m", 1) if S.get("ageMin") is not None and S["ageMin"] < 5 else 0) + P.get("good", -1) * len(plus)
    pts = max(pts, hp)
    verdict = "trap" if hard else ("good" if not unknown and len(soft) <= W.get("maxSoft", 1) else "watch")
    up = (1 if S.get("x") else 0) + (1 if S.get("tweet") else 0) - (1 if S.get("cluster") else 0) - (1 if (S.get("creatorPct") or 0) > 5 else 0) \
        - (1 if (S.get("mc") or 0) >= 500_000 else 0) - (1 if S.get("liq") and S.get("mc") and S["liq"] < 0.15 * S["mc"] and not S.get("pumpswap") else 0) - (1 if S.get("brand") else 0)
    push = verdict == "good" and not any(b in soft for b in W.get("pushBlock") or []) and not unknown
    n = sum(1 for k in ("instantPool", "swAvg", "brand", "buys", "rcReport", "rcDanger", "cluster", "creatorSold", "m5", "socN") if S.get(k) is not None)
    return {"verdict": verdict, "pts": pts, "upside": up, "hard": hard, "soft": soft, "plus": plus, "info": [i for i in info if i not in soft],
            "unknown": unknown, "push": push, "n": n}


def chips(rating, S):
    out = []
    T = {"instant_pool": "pool opened with the mint", "brand_name": "brand/celebrity name", "bot_volume": "3,000+ buys already", "staircase10": "staircase chart",
         "rugger_wallets": "%s holders from rugged coins" % (S.get("rugHolders") or "some"),
         "rc_danger": "RugCheck danger: %s" % ((S.get("rcDanger") or ["?"])[0]),
         "no_socials": "no socials", "holder_cluster": "holder cluster (insider network of %s)" % int(S.get("netSize") or 0),
         "creator_sold": "creator sold", "pumping_5m": "+%d%% in 5 min" % round(S.get("m5") or 0),
         "rc_report": "RugCheck pending", "mint_time": "mint time unknown", "walletmem": "wallet memory unavailable"}
    out += [["bad", T[h]] for h in rating["hard"] if h in T]
    out += [["warn", T.get(s, s)] for s in rating["soft"]]
    out += [["unk", T[u]] for u in rating["unknown"] if u in T]
    ok = []
    if S.get("mintToPoolS") is not None and S["mintToPoolS"] >= 60:
        ok.append("curve %d min before pool" % round(S["mintToPoolS"] / 60))
    if S.get("wmChecked") and "rugger_wallets" not in rating["hard"]:
        ok.append("no rugger wallets")
    if S.get("rcReport") is True and not S.get("rcDanger"):
        ok.append("RugCheck report")
    out += [["ok", t] for t in ok[:3]]
    for i in rating["info"]:
        if i == "x_copied":
            out.append(["info", "X account used by %d older coin%s" % (S["xUsed"], "" if S["xUsed"] == 1 else "s")])
        elif i == "dev_dead":
            out.append(["info", "dev: %d launches, %d dead" % (S["devN"], S["devDead"])])
        elif i == "staircase_early":
            out.append(["info", "staircase so far (%d min)" % S["stair"]["n"]])
    return out[:8]


def outcome(rec):
    l60 = (rec.get("later") or {}).get("60") or {}
    px0 = rec.get("px")
    if l60.get("gone"):
        return {"rug1h": True, "win1h": False, "x60": 0.0}
    x60 = (l60.get("px") / px0) if l60.get("px") and px0 else None
    rug = bool((l60.get("liq") is not None and l60["liq"] < 1000) or (x60 is not None and x60 <= 0.1))
    pk = (rec.get("peak60") or {}).get("x")
    win = (not rug) and bool((pk and pk >= 2) or (x60 and x60 >= 2 and (l60.get("liq") or 0) >= 5000)) and not (x60 and x60 > 30)
    return {"rug1h": rug, "win1h": win, "x60": x60}


def _auc(scores, ys):
    pos = [s for s, y in zip(scores, ys) if y]
    neg = [s for s, y in zip(scores, ys) if not y]
    if not pos or not neg:
        return 0.5
    return sum((1.0 if p > q else 0.5 if p == q else 0.0) for p in pos for q in neg) / (len(pos) * len(neg))


def fit(records, W, now):
    rows = [r for r in records if isinstance((r.get("out") or {}).get("rug1h"), bool)]
    if len(rows) < 300:
        return None, {"why": "%d of 300 records with a 1 h outcome" % len(rows), "n": len(rows)}
    rows.sort(key=lambda r: r.get("first") or 0)
    cut = now - 2 * 86_400_000
    train, test = [r for r in rows if (r.get("first") or 0) < cut], [r for r in rows if (r.get("first") or 0) >= cut]
    half = train[len(train) // 2:], train[:len(train) // 2]
    W2 = dict(W, soft=list(W.get("soft") or []), points=dict(W.get("points") or {}))
    promoted = []
    for k, f in M_SIG.items():
        ok = True
        for part in half:
            w = [r for r in part if f(r.get("sig") or {})]
            wo = [r for r in part if not f(r.get("sig") or {})]
            if len(w) < 10 or len(wo) < 10:
                ok = False
                break
            ratio = (sum(r["out"]["rug1h"] for r in w) / len(w) + 0.01) / (sum(r["out"]["rug1h"] for r in wo) / len(wo) + 0.01)
            ok = ok and ratio >= 1.5
        if ok:
            W2["soft"].append(k)
            W2["points"][k] = 2
            promoted.append(k)
    if not promoted:
        return None, {"why": "no measured signal held up", "n": len(rows)}
    pts = lambda Wx: [rate(r.get("sig") or {}, Wx)["pts"] for r in test]
    ys = [r["out"]["rug1h"] for r in test]
    a1, a2 = _auc(pts(W), ys), _auc(pts(W2), ys)
    if a2 < a1 - 0.01:
        return None, {"why": "walk-forward: AUC %.2f under the prior's %.2f" % (a2, a1), "auc": a2, "aucPrior": a1, "n": len(rows)}
    return W2, {"why": "", "auc": a2, "aucPrior": a1, "n": len(rows), "promoted": promoted}


def feed(d, out, now):
    raise NotImplementedError("stand-in")
'''

PEAK_STANDIN = r'''
"""A minimal stand-in for peak.py (WP2) for selftest_radar.py only: the dead-pool cut of the glitch filter (a DexScreener point
under $1,000 of liquidity, or gone, ends the window), nothing more."""
def peak_of(cands, entry_at, end, px, rug_ok_at=None, ds_points=(), liq0=None, mc0=None, res=1):
    cs = sorted([c for c in cands if c and c[4] and entry_at - 60_000 <= c[0] and c[0] + 60_000 <= end], key=lambda c: c[0])
    if not cs:
        return {"state": "waiting", "x": None, "at": None, "cut": []}
    dead = next((t for t, p, liq in sorted(ds_points or ()) if entry_at <= t <= end and liq is not None and liq < 1000), None)
    cut = ["pool dead: liquidity under $1,000 at minute %d" % ((dead - entry_at) // 60_000)] if dead else []
    live = [c for c in cs if dead is None or c[0] < dead] or cs[:1]
    base = cs[0][4]
    best = max(live, key=lambda c: c[4])
    return {"state": "ok", "x": round(best[4] / base, 4), "at": best[0], "cut": cut, "res": 1}
'''


def standin(name, src):
    m = types.ModuleType(name)
    m.__file__ = "<stand-in %s>" % name
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


def modules():
    """(traps, peak, which are stand-ins)."""
    out, stand = [], []
    for name, src in (("traps", TRAPS_STANDIN), ("peak", PEAK_STANDIN)):
        try:
            mod = __import__(name)
        except ImportError:
            mod = standin(name, src)
            stand.append(name)
        out.append(mod)
    return out[0], out[1], stand


# ---------------------------------------------------------------- the mock
def fixture(name, seed, **kw):
    """A coin of the mock. pf: in pump.fun's lists; v3: pump.fun's coins-v3 knows it (default: pf); jup: in Jupiter's recent list (its
    createdAt is the mint); trades: "few" (one page from the mint: the launch is reached) or "many" (every page has more); fresh: its
    holders' wallets are 2 hours old and one wallet funded them a minute apart; bund: pump.fun flags its first holder a bundler."""
    c = {"name": name, "a": addr(seed, kw.pop("suffix", "pump")), "sym": name, "title": name.title() + " Coin", "dex": "pumpswap", "pool": T0, "mint": T0 - 4 * MIN,
         "pf": True, "gt": False, "jup": False, "liq": 22_000.0, "mc": 60_000.0, "px": 0.00006, "m5": 5.0, "buys": 200, "sells": 120, "x": "https://x.com/%s_sol" % name.lower(),
         "tg": True, "rc": "ok", "danger": [], "warn": [], "net": 0, "nets": None, "holders": [addr(seed * 100 + i, "") for i in range(5)], "creator": addr(seed * 7 + 3, ""),
         "paid": True, "sold": False, "trades": "few", "fresh": False, "bund": False, "devN": 3}
    c.update(kw)
    c.setdefault("v3", c["pf"])
    return c


FIX = {
    "CLEAN": fixture("CLEAN", 1),
    "INSTA": fixture("INSTA", 2, mint=T0 - 2 * MIN, pool=T0 - 2 * MIN + 20_000),
    "BRAND": fixture("BRAND", 3, title="Grok Agent", sym="GROKAI"),
    "NORC": fixture("NORC", 4, rc="404", paid=False),
    "NOMINT": fixture("NOMINT", 5, suffix="", dex="meteora", pf=False, gt=True, mint=None),
    "CLUSTER": fixture("CLUSTER", 6, net=232, nets=[{"id": "n1", "size": 71, "type": "transfer"}, {"id": "n2", "size": 5, "type": "transfer"}], devN=60, fresh=True),
    "RUGGERS": fixture("RUGGERS", 7),
    "OLD": fixture("OLD", 8, pool=T0 - 12 * MIN, mint=T0 - 20 * MIN),
    "XCOPY": fixture("XCOPY", 9, x="https://x.com/OriginalDog", m5=30.0, net=120, trades="many", bund=True),
    "COPY": fixture("COPY", 10, sym="COPYCAT", mc=100_000.0),
    "JUPMINT": fixture("JUPMINT", 13, suffix="", dex="meteora", pf=False, jup=True, mint=T0 - 20_000),
    "V3ONLY": fixture("V3ONLY", 14, pf=False, v3=True, gt=True, x=None, tg=False, m5=30.0),
    "LOWLIQ": fixture("LOWLIQ", 15, liq=2_000.0),                 # under memebot's YOUNG_MIN_LIQ: never on the radar
    "CURVE": fixture("CURVE", 16, dex="pumpfun"),                 # its DexScreener pair is still the launch curve: never on the radar
}
RUG_WALLETS = FIX["RUGGERS"]["holders"][:3]
OLDER = addr(99)
YOUNGER = addr(98)


class RadarMock:
    """Every host the radar asks, from the fixture coins. hang: path parts whose request waits 20 s; rc429: addresses whose RugCheck
    report is a 429; jup_bad: Jupiter's recent list in another shape; gone: addresses DexScreener has no pair for; gt429 / rpc429: the
    next so many GeckoTerminal / RPC requests answer 429; gt_page2_old: GeckoTerminal's new pools are an hour old; th429: addresses
    whose top holders frontend-api-v3 answers with a 429; dev_ignore: pump.fun's creator filter ignored; gh403 / runs500: the next so
    many reads of the radar workflow's state answer 403 (GitHub's secondary rate limit) / of its run list answer 500. heads: every
    request (method, path, query, Origin header, the RPC method and first parameter, time)."""

    def __init__(self, coins):
        self.coins = {c["a"]: c for c in coins}
        self.workflow, self.runs, self.dispatches, self.log, self.hang, self.rc429, self.gone = "active", [], [], [], set(), set(), set()
        self.jup_bad, self.auth_bad, self.lock = False, 0, threading.Lock()
        self.clock = lambda: T0 + 10 * MIN          # the radar's clock (run_radar sets it): candles end there
        self.gt429, self.rpc429, self.gt_page2_old, self.th429, self.dev_ignore, self.heads = 0, 0, False, set(), False, []
        self.gh403 = self.runs500 = 0
        self.tweet_likes = {}                       # tweet id -> likes, "tomb" (a deleted tweet), "unavail" (a protected one), "empty" ({}),
                                                    # "nofav" (a tweet without favorite_count) or 429; any other id: no route (404)
        MOCKS.append(self)

    def pair(self, c):
        socials = ([{"type": "twitter", "url": c["x"]}] if c.get("x") else []) + ([{"type": "telegram", "url": "https://t.me/x"}] if c.get("tg") else [])
        return {"chainId": "solana", "dexId": c["dex"], "pairAddress": c["a"][:20] + "pool", "baseToken": {"address": c["a"], "symbol": c["sym"], "name": c["title"]},
                "priceUsd": "%.10f" % c["px"], "marketCap": c["mc"], "fdv": c["mc"], "liquidity": {"usd": c["liq"]},
                "volume": {"h24": 50_000, "h6": 50_000, "h1": 50_000}, "priceChange": {"m5": c["m5"], "h1": c["m5"], "h6": c["m5"], "h24": c["m5"]},
                "txns": {"h24": {"buys": c["buys"], "sells": c["sells"]}, "h6": {"buys": c["buys"], "sells": c["sells"]}, "h1": {"buys": c["buys"], "sells": c["sells"]}},
                "pairCreatedAt": c["pool"], "info": {"websites": [], "socials": socials}}

    def route(self, method, path, query, body):
        """(status, JSON body) or None (not a radar route)."""
        q = urllib.parse.parse_qs(query)
        by_pool = {c["a"][:20] + "pool": c for c in self.coins.values()}
        if path.startswith("/api.github.com/repos/%s/actions/workflows/radar.yml" % REPO):
            return ("gh", path, method, body)
        if path.startswith("/frontend-api-v3.pump.fun/coins/user-created-coins/") or re.match(r"^/frontend-api-v3\.pump\.fun/coins/[1-9A-HJ-NP-Za-km-z]{32,48}$", path):
            return 404, {"message": "Cannot GET %s" % path.split(".fun", 1)[1][:20]}       # routes pump.fun took away (the probe's run 1)
        dev = (q.get("creator") or [""])[0]
        if path == "/frontend-api-v3.pump.fun/coins" and dev and self.dev_ignore:
            return 200, [self.pf(c) for c in self.coins.values() if c["pf"] and c["creator"] != dev]
        if path == "/frontend-api-v3.pump.fun/coins" and dev:
            n = next((c["devN"] for c in self.coins.values() if c["creator"] == dev), 3)
            return 200, [{"mint": addr(hash((dev, i)) % 10**6 + 500), "creator": dev, "complete": i == 0, "usd_market_cap": 4_000 if i else 90_000,
                          "created_timestamp": T0 - (i + 2) * H} for i in range(min(50, n))]
        m = re.match(r"^/frontend-api-v3\.pump\.fun/coins-v2/user-created-coins/([^/]+)$", path)
        if m:
            n = next((c["devN"] for c in self.coins.values() if c["creator"] == m.group(1)), 3)
            return 200, {"coins": [], "count": n, "limit": 50, "offset": 0}
        m = re.match(r"^/frontend-api-v3\.pump\.fun/coins-v3/([1-9A-HJ-NP-Za-km-z]{32,48})$", path)
        if m:
            c = self.coins.get(m.group(1))
            return (200, self.pf(c)) if c and c["v3"] else (404, {"error": "not found"})
        m = re.match(r"^/(frontend-api-v3|advanced-api-v2)\.pump\.fun/coins/top-holders/([^/]+)$", path)
        if m and m.group(2) not in self.coins:
            return 404, {"message": "coin not found"}
        if m:
            if m.group(1) == "frontend-api-v3" and m.group(2) in self.th429:
                return 429, {"error": "slow down"}
            return 200, self.top_holders(self.coins[m.group(2)])
        m = re.match(r"^/swap-api\.pump\.fun/v2/coins/([^/]+)/trades$", path)
        if m and m.group(1) in self.coins:
            return 200, self.trades(self.coins[m.group(1)], (q.get("cursor") or [""])[0])
        m = re.match(r"^/swap-api\.pump\.fun/v1/coins/([^/]+)/candles$", path)
        if m and m.group(1) in self.coins:
            c = self.coins[m.group(1)]
            now = self.clock()
            rows = []
            for k in range(100):
                t = (c["mint"] // MIN) * MIN + k * MIN
                if t > now:
                    break
                close = c["px"] * (1 + 0.04 * min(k, 30))
                rows.append({"timestamp": t, "open": close * 0.99, "high": close * 1.01, "low": close * 0.98, "close": close, "volume": 900.0})
            return 200, rows
        m = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/report$", path)
        if m and m.group(1) in self.coins:
            c = self.coins[m.group(1)]
            if m.group(1) in self.rc429 or c["rc"] == "429":
                return 429, {"error": "slow down"}
            if c["rc"] == "404":
                return 404, {"error": "not found"}
            risks = [{"name": n, "level": "danger"} for n in c["danger"]] + [{"name": n, "level": "warn"} for n in c["warn"]]
            return 200, {"mint": c["a"], "score": 100, "score_normalised": 3, "risks": risks, "totalHolders": 400, "graphInsidersDetected": c["net"], "insiderNetworks": c["nets"],
                         "creatorTokens": None,
                         "topHolders": [{"owner": h, "pct": 4.0 - i * 0.5, "insider": False} for i, h in enumerate(c["holders"])], "token": {"supply": 1e15},
                         "creatorBalance": 1e12, "creator": c["creator"], "markets": [{"lp": {"lpLockedPct": 100}}], "launchpad": {"name": "pump.fun"}}
        if path.startswith("/api.dexscreener.com/tokens/v1/solana/"):
            want = path.rsplit("/", 1)[1].split(",")
            if not any(a in self.coins for a in want):
                return None
            return 200, [self.pair(self.coins[a]) for a in want if a in self.coins and a not in self.gone]
        m = re.match(r"^/api\.dexscreener\.com/orders/v1/solana/([^/]+)$", path)
        if m and m.group(1) in self.coins:
            return 200, ([{"type": "tokenProfile", "status": "approved", "paymentTimestamp": T0 - H}] if self.coins[m.group(1)]["paid"] else [])
        if path.startswith("/lite-api.jup.ag/tokens/v2/search") and (q.get("query") or [""])[0] in self.coins:
            c = self.coins[q["query"][0]]
            return 200, [{"id": c["a"], "symbol": c["sym"], "name": c["title"], "dev": c["creator"], "holderCount": 400, "organicScore": 50,
                          "audit": {"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devBalancePercentage": 1.0, "topHoldersPercentage": 20.0}}]
        if path == "/cdn.syndication.twimg.com/tweet-result":
            import fetch as F
            tid = (q.get("id") or [""])[0]
            v = self.tweet_likes.get(tid) if (q.get("token") or [""])[0] == F.tweet_token(tid or "0") else None
            if v == 429:
                return 429, {"errors": [{"message": "Rate limit exceeded"}]}
            if v == "tomb":
                return 200, {"__typename": "TweetTombstone", "tombstone": {"text": {"text": "This Post was deleted"}}}
            if v in ("unavail", "empty", "nofav"):
                return 200, {"unavail": {"__typename": "TweetUnavailable", "reason": "Protected"}, "empty": {},
                             "nofav": {"__typename": "Tweet", "id_str": tid, "text": "a story"}}[v]
            if v is None:
                return None                         # not one of this mock's tweets: lists() answers 404 (mock_routes keeps None)
            return 200, {"__typename": "Tweet", "id_str": tid, "favorite_count": v, "conversation_count": 7, "created_at": "2026-10-13T09:00:00.000Z",
                         "user": {"screen_name": "someone", "followers_count": 900}, "text": "a <b>story</b> about a dog"}
        if "/ohlcv/minute" in path:
            pool = path.split("/pools/")[1].split("/")[0]
            c = by_pool.get(pool)
            if not c:
                return None
            before = int((q.get("before_timestamp") or ["0"])[0]) * 1000
            lim = int((q.get("limit") or ["10"])[0])
            rows = []
            for i in range(lim):
                t = before - (i + 1) * MIN
                if t < c["pool"]:
                    break
                k = (t - c["pool"]) // MIN
                close = c["px"] * (1 + 0.04 * min(k, 30)) * (2.5 if k == 40 else 1.0)       # one print at minute 40, no DexScreener point there
                rows.append([t // 1000, close, close * 1.01, close * 0.99, close, 5000.0])
            return 200, {"data": {"attributes": {"ohlcv_list": rows}}}
        return None

    def top_holders(self, c):
        """pump.fun's top holders: the pool, then the fixture's holders; the first two entered 10 s after the mint. isSniper and isDev
        are set on every holder (the radar must not read them), fundingSource is null as the probe found."""
        hs = [{"address": c["a"][:20] + "pool", "amount": 600_000_000.0, "enteredAt": c["pool"], "isSniper": True, "isDev": False, "isBundler": False, "fundingSource": None}]
        for i, w in enumerate(c["holders"]):
            hs.append({"address": w, "amount": 30_000_000.0 - i * 1_000_000, "enteredAt": c["mint"] + (10_000 if i < 2 else 5 * MIN), "isSniper": True,
                       "isDev": True, "isBundler": bool(c["bund"] and i == 0), "fundingSource": None})
        return {"topHolders": hs, "totalHolders": 300}

    def trades(self, c, cursor):
        """swap-api trades, newest first, 100 a page: "few" = one page down to the mint (3 buyers in the first 30 s, two in the mint's slot),
        "many" = every page has more."""
        slot0 = 300_000_000
        if c["trades"] == "many":
            page = int(cursor or 0)
            rows = [{"timestamp": c["pool"] + 9 * MIN - (page * 100 + i) * 600, "type": "buy" if i % 2 else "sell", "userAddress": addr(i + 7000, ""),
                     "baseAmount": 1_000_000.0, "slotIndexId": "%012d%010d" % (slot0 + 5000 - page * 100 - i, i), "program": "pump_amm"} for i in range(100)]
            return {"trades": rows, "pagination": {"hasMore": True, "limit": 100, "nextCursor": str(page + 1)}}
        b = [(c["mint"], 0, c["creator"], 20_000_000.0), (c["mint"] + 400, 0, c["holders"][0], 15_000_000.0), (c["mint"] + 12_000, 30, c["holders"][1], 10_000_000.0),
             (c["mint"] + 90_000, 225, c["holders"][2], 5_000_000.0)]
        rows = [{"timestamp": t, "type": "buy", "userAddress": w, "baseAmount": amt, "slotIndexId": "%012d%010d" % (slot0 + s, 7), "program": "pump"} for t, s, w, amt in b]
        rows.append({"timestamp": c["pool"] + MIN, "type": "sell", "userAddress": c["holders"][3], "baseAmount": 1_000_000.0,
                     "slotIndexId": "%012d%010d" % (slot0 + 900, 1), "program": "pump_amm"})
        return {"trades": sorted(rows, key=lambda r: -r["timestamp"]), "pagination": {"hasMore": False, "limit": 100, "nextCursor": None}}

    def pf(self, c):
        return {"mint": c["a"], "symbol": c["sym"], "name": c["title"], "usd_market_cap": c["mc"], "market_cap": 300, "ath_market_cap": c["mc"], "reply_count": 4,
                "is_currently_live": False, "complete": True, "created_timestamp": c["mint"], "twitter": c["x"], "website": None, "telegram": "https://t.me/x" if c["tg"] else None,
                "creator": c["creator"], "pump_swap_pool": c["a"][:20] + "pool"}

    def lists(self, path, q):
        """The discovery lists (only in this module's server)."""
        if path.startswith("/frontend-api-v3.pump.fun/coins"):
            if (q.get("offset") or ["0"])[0] != "0" or "created_timestamp" in (q.get("sort") or [""])[0]:
                return 200, []
            return 200, [self.pf(c) for c in self.coins.values() if c["pf"]]
        if path.startswith("/api.geckoterminal.com/api/v2/networks/solana/new_pools"):
            if (q.get("page") or ["1"])[0] != "1":
                return 200, {"data": [], "included": []}
            gt = [c for c in self.coins.values() if c["gt"]]
            return 200, {"data": [{"id": "solana_" + c["a"][:20] + "pool", "type": "pool", "attributes": {"name": c["sym"] + " / SOL", "address": c["a"][:20] + "pool",
                                   "base_token_price_usd": str(c["px"]), "fdv_usd": str(c["mc"]), "reserve_in_usd": str(c["liq"]), "volume_usd": {"h24": "1000"},
                                   "price_change_percentage": {"h1": "1", "h6": "1", "h24": "1"}, "transactions": {"h24": {"buys": 10, "sells": 5, "buyers": 5, "sellers": 3}},
                                   "pool_created_at": "2026-10-13T%s:00Z" % ("11:00" if self.gt_page2_old else "11:59")},
                                   "relationships": {"base_token": {"data": {"id": "solana_" + c["a"]}}, "dex": {"data": {"id": c["dex"]}}}} for c in gt],
                         "included": [{"id": "solana_" + c["a"], "type": "token", "attributes": {"symbol": c["sym"], "name": c["title"]}} for c in gt]}
        if path.startswith("/lite-api.jup.ag/tokens/v2/recent"):
            jup = [{"id": c["a"], "symbol": c["sym"], "name": c["title"], "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["mint"] / 1000)),
                    "dev": c["creator"], "usdPrice": c["px"], "mcap": c["mc"], "liquidity": c["liq"], "firstPool": {"createdAt": c["pool"]}}
                   for c in self.coins.values() if c["jup"]]
            return 200, ({"oops": "another shape"} if self.jup_bad else jup)
        if path.startswith("/api.dexscreener.com/token-profiles/latest/v1"):
            return 200, []
        if path.startswith("/launch-mint-v1.raydium.io/get/list"):
            return 200, {"success": True, "data": {"rows": []}}
        return 404, {"error": "no route " + path}

    def rpc(self, body):
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            return 400, {"error": "bad json"}
        method, params = req.get("method"), req.get("params") or []
        p0 = str(params[0]) if params else ""
        nomint = next((c["a"] for c in self.coins.values() if c["name"] == "NOMINT"), None)
        fresh = {w: (c, i) for c in self.coins.values() if c["fresh"] for i, w in enumerate(c["holders"])}
        if method == "getSignaturesForAddress":
            if p0 in fresh:
                return 200, {"jsonrpc": "2.0", "id": 1, "result": [{"signature": "f_%s_%d" % (p0, i), "blockTime": int(T0 / 1000) - 7200 - i * 30} for i in range(2)]}
            if p0 == nomint:
                return 200, {"jsonrpc": "2.0", "id": 1, "result": [{"signature": "m%d" % i, "blockTime": int(T0 / 1000) - i} for i in range(1000)]}
            if any(c["creator"] == p0 for c in self.coins.values()):
                return 200, {"jsonrpc": "2.0", "id": 1, "result": [{"signature": "d_%s_%d" % (p0[:8], i), "blockTime": int(T0 / 1000) - 40 * 86400 - i * 3600} for i in range(30)]}
            return 200, {"jsonrpc": "2.0", "id": 1, "result": [{"signature": "w_%s_%d" % (p0, i), "blockTime": int(T0 / 1000) - 30 * 86400 - i * 3600} for i in range(40)]}
        if method == "getTransaction":
            sig = p0
            if sig.startswith("f_"):
                w = sig.split("_")[1]
                c, i = fresh[w]
                fu = addr(4242, "")
                return 200, {"jsonrpc": "2.0", "id": 1, "result": {"blockTime": int(T0 / 1000) - 7300 + i * 60, "meta": {},
                             "transaction": {"message": {"accountKeys": [{"pubkey": fu}], "instructions": [{"parsed": {"type": "transfer", "info": {"source": fu, "destination": w, "lamports": 10}}}]}}}}
            if sig.startswith("w_"):
                w = sig.split("_")[1]
                return 200, {"jsonrpc": "2.0", "id": 1, "result": {"blockTime": int(T0 / 1000) - 30 * 86400 - 39 * 3600, "meta": {},
                             "transaction": {"message": {"accountKeys": [{"pubkey": "F" + w[1:]}], "instructions": [{"parsed": {"type": "transfer", "info": {"source": "F" + w[1:], "destination": w, "lamports": 10}}}]}}}}
            return 200, {"jsonrpc": "2.0", "id": 1, "result": {"blockTime": int(T0 / 1000) - 100, "meta": {"preTokenBalances": [], "postTokenBalances": []}}}
        return 200, {"jsonrpc": "2.0", "id": 1, "result": None}


def mock_routes(method, path, query, body):
    """The radar's routes for selftest.py's Mock: (status, body) or None. GitHub's workflow API answers "active" with no other run."""
    m = MOCK
    if m is None:
        return None
    got = m.route(method, path, query, body)
    if isinstance(got, tuple) and got and got[0] == "gh":
        return gh_answer(m, method, path, body)
    return got


def gh_answer(m, method, path, body):
    if path.endswith("/dispatches") and method == "POST":
        with m.lock:
            m.dispatches.append(json.loads(body or b"{}"))
        return 204, None
    if path.endswith("/runs"):
        return 200, {"total_count": len(m.runs), "workflow_runs": m.runs}
    return 200, {"id": 1, "name": "Meme-Bot launch radar", "path": ".github/workflows/radar.yml", "state": m.workflow}


def serve(mock):
    class Hd(BaseHTTPRequestHandler):
        def go(self, method):
            u = urllib.parse.urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
            rpc_m = rpc_p0 = None
            if u.path.startswith("/api.mainnet-beta.solana.com"):
                try:
                    req = json.loads(body or b"{}")
                    rpc_m, rpc_p0 = req.get("method"), str((req.get("params") or [""])[0])
                except ValueError:
                    pass
            with mock.lock:
                mock.log.append((method, u.path, time.time()))
                mock.heads.append({"m": method, "path": u.path, "q": u.query, "origin": self.headers.get("Origin"), "rpc": rpc_m, "p0": rpc_p0, "t": time.time()})
                limited = (u.path.startswith("/api.geckoterminal.com/") and mock.gt429 > 0) or (rpc_m and mock.rpc429 > 0)
                if limited and rpc_m:
                    mock.rpc429 -= 1
                elif limited:
                    mock.gt429 -= 1
            if any(h in u.path for h in mock.hang):
                threading.Event().wait(20)
            if limited:
                code, out = 429, {"error": "rate limited"}
            elif u.path.startswith("/api.github.com/"):
                if self.headers.get("Authorization") != "Bearer " + GH_TOKEN:
                    mock.auth_bad += 1
                    code, out = 401, {"message": "Bad credentials"}
                elif mock.gh403 > 0 and method == "GET" and u.path.endswith("/workflows/radar.yml"):
                    mock.gh403 -= 1
                    code, out = 403, {"message": "You have exceeded a secondary rate limit"}
                elif mock.runs500 > 0 and u.path.endswith("/runs"):
                    mock.runs500 -= 1
                    code, out = 500, {"message": "Server Error"}
                else:
                    code, out = gh_answer(mock, method, u.path, body)
            elif u.path.startswith("/api.mainnet-beta.solana.com"):
                code, out = mock.rpc(body)
            else:
                got = mock.route(method, u.path, u.query, body)
                code, out = got if got is not None else mock.lists(u.path, urllib.parse.parse_qs(u.query))
            raw = json.dumps(out).encode() if out is not None else b""
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except OSError:
                pass

        def do_GET(self):
            self.go("GET")

        def do_POST(self):
            self.go("POST")

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- the git remote (results, radar-feed)
def git(*a, cwd=None):
    p = subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (a[0], p.stderr[-300:]))
    return p.stdout.strip()


def put_branch(remote, branch, files, tmp):
    """files {path: bytes or JSON-able} as the one commit of branch on the bare remote."""
    w = tempfile.mkdtemp(dir=tmp)
    for p, v in files.items():
        fp = os.path.join(w, *p.split("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "wb") as f:
            f.write(v if isinstance(v, bytes) else json.dumps(v).encode())
    git("init", "-q", "-b", branch, cwd=w)
    git("add", "-A", cwd=w)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", branch, cwd=w)
    git("push", "-q", "--force", remote, "%s:refs/heads/%s" % (branch, branch), cwd=w)
    shutil.rmtree(w, ignore_errors=True)


def refs(remote):
    out = {}
    for line in git("--git-dir", remote, "for-each-ref", "--format=%(objectname) %(refname)").splitlines():
        sha, ref = line.split(" ", 1)
        out[ref] = sha
    return out


def branch_files(remote, branch):
    try:
        names = git("--git-dir", remote, "ls-tree", "-r", "--name-only", branch).splitlines()
    except RuntimeError:
        return {}
    return {n: subprocess.run(["git", "--git-dir", remote, "show", "%s:%s" % (branch, n)], capture_output=True).stdout for n in names}


def gz(doc):
    return gzip.compress(json.dumps(doc).encode())


def feed_files(T, now, wm_age=30 * MIN):
    """radar-feed as traps.feed writes it. XCOPY's account link (traps' xlinks format [first addr, first ms, coins, kind, last ms, uses]) is
    used by an older coin 3 hours before, by XCOPY itself and by a younger coin: one older coin, not three."""
    x_key = T.norm_x(FIX["XCOPY"]["x"])
    xc = FIX["XCOPY"]
    uses = sorted([[OLDER, now - 3 * H], [xc["a"], xc["mint"]], [YOUNGER, xc["mint"] + 3 * MIN]], key=lambda u: u[1])
    return {"walletmem.json.gz": gz({"v": 1, "t": now - wm_age, "nCoins": 500, "common": [], "sw": {}, "rug": RUG_WALLETS}),
            "xlinks.json.gz": gz({"v": 1, "t": now, "links": {x_key[1]: [uses[0][0], uses[0][1], 3, x_key[0], uses[-1][1], uses]} if x_key else {}}),
            "symmc.json.gz": gz({"v": 1, "t": now, "sym": {"COPYCAT": 5_000_000.0}}), "meta.json": {"t": now, "nCoins": 500}}


# ---------------------------------------------------------------- running the radar in this process
@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def memebot_rules():
    """memebot's profile globals as they were (the radar sets the 2h profile in this process)."""
    import memebot as M
    keys = set(M.PROFILES["2h"]) | {"HORIZON"}
    saved = {k: getattr(M, k) for k in keys if hasattr(M, k)}
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(M, k, v)


class Sink:
    """The notifications the radar sends (a stand-in for app.notify_radar): their coins and words."""

    def __init__(self):
        self.got = []

    def __call__(self, coins, record=None):
        import launch_radar as LR
        title, body = LR.push_text(coins, record)
        self.got.append({"coins": [c.get("sym") for c in coins], "title": title, "body": body,
                         "known": (record or {}).get("known") if isinstance(record, dict) else None})
        return {"kind": "radar", "sent": 1}


def run_radar(T, P, url, remote, rd, now, minutes=10, notifier=None, hours="0-24", extra=None, deadline=8.0, patch=None, envs=None, cmd="loop", source="manual",
              clock=None):
    """One radar run in this process: (exit code, the Radar, its log lines, seconds). cmd loop (radar.yml's way: --minutes long) or round
    (one cycle). clock: a fake clock of its own (LR.FakeClock(now, step=120_000) for 2-minute cycles; default 150 s)."""
    import launch_radar as LR
    lines = []
    argv = [cmd, "--dir", rd] + (["--minutes", str(minutes)] if cmd == "loop" else []) + ["--cadence", "1", "--clock", "fake", "--now", str(int(now)),
            "--deadline", str(deadline), "--cache", rd + "-cache", "--source", source] + (["--mock", url] if url else []) + (["--remote", remote] if remote else []) + (extra or [])
    e = dict(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9001", GITHUB_REF_NAME="main", MEMEBOT_RADAR_HOURS=hours, RADAR_URL=None,
             SUPABASE_URL=None, SUPABASE_SECRET_KEY=None, MEMEBOT_RADAR_ADAPTERS=None)
    e.update(envs or {})
    t = time.time()
    with env(**e), memebot_rules():
        R = LR.Radar(LR.args_of(argv), log=lines.append, notifier=notifier, traps=T, peak=P, clock=clock)
        for m in MOCKS:
            m.clock = R.clock.now
        if patch:
            patch(R)
        code = R.round() if cmd == "round" else R.loop()
    return code, R, lines, time.time() - t


def unit_radar(T, P, tmp, name, now=T0, extra=None, log=None, clock=None):
    """A Radar without a run (no GitHub, fake clock) for checks on one method."""
    import launch_radar as LR
    return LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, name), "--clock", "fake", "--now", str(int(now)), "--cache", os.path.join(tmp, name + "-c"),
                                "--no-github"] + (extra or [])), log=log or (lambda s_: None), traps=T, peak=P, clock=clock)


def fresh_remote(T, tmp, name, now, t3=None, **kw):
    """A bare remote with only radar-feed (feed_files(T, now, **kw); t3: its t3skip.json too, a dict or raw bytes)."""
    rem = os.path.join(tmp, name + ".git")
    git("init", "-q", "--bare", rem)
    put_branch(rem, "radar-feed", dict(feed_files(T, now, **kw), **({"t3skip.json": t3} if t3 is not None else {})), tmp)
    return rem


def radar_json(remote):
    raw = branch_files(remote, "radar-data").get("radar.json")
    return json.loads(raw) if raw else {}


def hour_recs(remote):
    out = {}
    for p, raw in branch_files(remote, "radar-data").items():
        if p.startswith("db/memeradar/"):
            for a, rec in (json.loads(raw).get("coins") or {}).items():
                out[a] = rec
    return out


# ---------------------------------------------------------------- the checks
def checks(check, env_=None):
    global MOCK
    import launch_radar as LR
    import memebot as M
    T, P, stand = modules()
    if stand:
        print("  (traps.py / peak.py not here yet: the checks use the spec's stand-in for %s)" % " and ".join(stand))
    tmp = tempfile.mkdtemp(prefix="memebot-radar-")
    mock = RadarMock(FIX.values())
    MOCK = mock
    srv = serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    remote = os.path.join(tmp, "remote.git")
    git("init", "-q", "--bare", remote)
    odds = lambda p: {"factors": {"zzz": {"edges": [1.0], "lo": [0.0, 0.0]}}, "cal": [{"hi": 1e9, "p": p}]}     # trained odds for the detail view (info only)
    put_branch(remote, "results", {"db/memebot/state.json": {"v": 1}, "db/memeradar/2026-10-10T08.json": {"v": 1, "hour": "2026-10-10T08", "t": 0, "coins": {}},
                                   "db/memebot/train.json": {"zeroModel": odds(0.12), "upModel": odds(0.31)}}, tmp)
    put_branch(remote, "radar-feed", feed_files(T, T0), tmp)
    before = refs(remote)
    by = {c["name"]: c["a"] for c in FIX.values()}
    rules = memebot_rules()
    rules.__enter__()
    try:
        # ---- R1, R2, R4 (first part), R7 (refs), R5 (no successor): a loop run of 4 cycles at T0
        print("== launch radar R1: 4 cycles on the fixtures -> radar.json and a record for every eligible coin")
        sink = Sink()
        code, R, lines, secs = run_radar(T, P, url, remote, os.path.join(tmp, "rdA"), T0, minutes=10, notifier=sink, envs={"MEMEBOT_SWITCH_AT": str(T0 - H)})
        heads_a = list(mock.heads)
        doc, recs = radar_json(remote), hour_recs(remote)
        raw = json.dumps(doc, separators=(",", ":"))
        coins = doc.get("coins") or []
        eligible = {by[n] for n in ("CLEAN", "INSTA", "BRAND", "NORC", "NOMINT", "CLUSTER", "RUGGERS", "XCOPY", "JUPMINT", "V3ONLY")}
        cyc = [l for l in lines if re.match(r"^cycle \d+:", l)]
        print("  %s" % "\n  ".join(cyc[-4:]))
        check(code == 0 and len(cyc) == 4 and doc.get("v") == 1 and doc.get("kind") == "radar" and len(raw) <= LR.DOC_MAX and doc.get("state") == "ending",
              "4 cycles, radar.json valid (%d bytes, state %s, %.1f s)" % (len(raw), doc.get("state"), secs))
        order = [c["sym"] for c in coins]
        check(coins and all(c["v"] == "good" for c in coins) and len(coins) <= 5 and all(c["age"] < 10 for c in coins + (doc.get("others") or [])) and order == ["CLEAN", "CLUSTER"],
              "coins: only good ones, at most 5, every pool under 10 min, ordered by upside (%s); %d in the fold" % (order, len(doc.get("others") or [])))
        pbs = {c["sym"]: c.get("pb") for c in coins}
        cl_ = recs.get(by["CLEAN"]) or {}
        push1 = next((e[0] for e in cl_.get("rt") or [] if e[1] == "good" and e[3] == 1), None)
        check(pbs == {"CLEAN": 1, "CLUSTER": 0} and all(isinstance(c.get("pb"), int) for c in coins) and isinstance(cl_.get("sigG"), dict)
              and push1 is not None and cl_.get("sigGt") == push1 and "sigG" not in (recs.get(by["CLUSTER"]) or {}) and "sigGt" not in (recs.get(by["CLUSTER"]) or {}),
              "TR16 every radar.json coin has pb (bought on paper by radar_paper's rule 2, 0 or 1), the switch an hour before the run: CLEAN 1, "
              "CLUSTER (good, a holder cluster) 0 %s; the record keeps the signals of its first push-worthy green rating (sigG) and that rating's "
              "time (sigGt) only where there is one" % pbs)
        check(set(recs) == eligible and all(len(r["rt"]) == 4 for a, r in recs.items() if a != by["INSTA"]) and len(recs[by["INSTA"]]["rt"]) >= 3
              and all(r.get("found") and r.get("seenAge") is not None for r in recs.values()) and not {by[n] for n in ("OLD", "COPY", "LOWLIQ", "CURVE")} & set(recs),
              "a record for each of the %d eligible coins (none for OLD, the copy of a bigger ticker, LOWLIQ under $5k or CURVE still on its launch "
              "curve), every rating kept (%s), found and seenAge set" % (len(recs), sorted({len(r["rt"]) for r in recs.values()})))
        mk = lambda n, v, up, pts, liq: {"addr": n, "sym": n, "v": v, "up": up, "pts": pts, "liq": liq}
        pool_r = [mk("g1", "good", 1, 0, 9e3), mk("g2", "good", 2, 1, 5e3), mk("g3", "good", 2, 0, 4e3), mk("g4", "good", 2, 0, 8e3), mk("g5", "good", 0, -1, 1e4),
                  mk("g6", "good", -1, 0, 9e4), mk("g7", "good", 1, 0, 2e4), mk("w1", "watch", 0, 3, 1e4), mk("w2", "watch", 0, 2, 5e3), mk("w3", "watch", 0, 2, 7e3),
                  mk("t1", "trap", 3, 6, 1e5), mk("t2", "trap", 3, 4, 1e3)]
        random.Random(5).shuffle(pool_r)
        top_r, coins_r, oth_r = LR.rank(pool_r)
        top_s, coins_s, _ = LR.rank([x for x in pool_r if x["addr"] in ("g1", "w1", "w2", "w3", "t1", "t2")])
        ids = lambda xs: [x["addr"] for x in xs]
        check(ids(coins_r) == ["g4", "g3", "g2", "g7", "g1"] and ids(top_r) == ids(coins_r) and ids(oth_r) == ["w3", "w2", "w1", "t2", "t1"]
              and ids(top_s) == ["g1", "w3", "w2", "w1", "t2"] and ids(coins_s) == ["g1"],
              "the best 5 of 7 good, 3 watch and 2 trap coins: good by upside, then fewer points, then more liquidity (%s), the fold watch then "
              "trap (%s); with one good coin the best 5 fill up with watch, then trap coins, and only the good one is listed" % (ids(coins_r), ids(oth_r)))
        dc = next((c.get("d") or {} for c in coins if c["addr"] == by["CLEAN"]), {})
        check(dc.get("upP") == 0.31 and dc.get("zeroP") == 0.12 and "odds" not in dc and sum(1 for l in lines if re.match(r"^cycle \d+: .*, 1 pushed ", l)) == 1
              and R.publishes == 5,
              "radar.json: the trained odds (info only) as d.upP / d.zeroP (%s / %s), the field names the page reads; the cycle line says 1 pushed once, "
              "and radar-data is pushed again right after the notification (%d pushes in 4 cycles)" % (dc.get("upP"), dc.get("zeroP"), R.publishes))
        sink_b = Sink()
        code_b, Rb, linesb, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdB"), T0 + 8.5 * MIN, minutes=2.5, notifier=sink_b)
        rb = hour_recs(remote).get(by["CLEAN"]) or {}
        cl = recs.get(by["CLEAN"]) or {}
        check(cl.get("good") and cl.get("goodPx") and cl["sig"].get("mintToPoolS") == 240 and cl["chk"]["rc"] == "ok" and cl["chk"]["wm"] == "ok"
              and isinstance(cl["sig"].get("holders"), list) and cl.get("push") and "5" in cl.get("later", {}) and not cl["later"]["5"].get("late"),
              "CLEAN's record: good at %s, curve 4 min before the pool, checks %s, price 5 min later %s" % (cl.get("good"), cl.get("chk"), cl.get("later", {}).get("5")))

        print("== launch radar R2: the fixtures' verdicts")
        rated = {a: r["rt"][-1][1] for a, r in recs.items()}
        doc_by = {c["addr"]: c for c in coins}
        oth = {c["addr"]: c for c in doc.get("others") or []}
        txt = lambda a: " | ".join(t for _, t in ((doc_by.get(a) or oth.get(a) or {}).get("line") or []))
        sig = lambda n: recs[by[n]]["sig"]
        exp = {"CLEAN": "good", "INSTA": "trap", "BRAND": "trap", "NORC": "watch", "NOMINT": "watch", "CLUSTER": "good", "RUGGERS": "trap", "XCOPY": "watch",
               "JUPMINT": "trap", "V3ONLY": "watch"}
        got = {n: rated.get(by[n]) for n in exp}
        check(got == exp, "verdicts %s" % got)
        check("pool opened with the mint" in txt(by["INSTA"]) and "brand/celebrity name" in txt(by["BRAND"]) and "holders from rugged coins" in txt(by["RUGGERS"])
              and "RugCheck pending" in txt(by["NORC"]) and (oth.get(by["NORC"]) or {}).get("pts", 0) >= 2 and "mint time unknown" in txt(by["NOMINT"])
              and "holder cluster (insider network of 232)" in txt(by["CLUSTER"]) and "X account used by 1 older coin" in txt(by["XCOPY"])
              and "pool opened with the mint" in txt(by["JUPMINT"]),
              "trap lines: INSTA, BRAND, RUGGERS, JUPMINT red; NORC '? RugCheck pending' (+%s); NOMINT 'mint time unknown'; CLUSTER's cluster; XCOPY's grey X line"
              % (oth.get(by["NORC"]) or {}).get("pts"))
        sx = dict(sig("XCOPY"), xUsed=0)
        check(sig("XCOPY").get("xUsed") == 1 and T.rate(sx, R.W_prior)["verdict"] == "watch" and not doc_by.get(by["CLUSTER"], {}).get("push"),
              "XCOPY: X account used by an older coin (measured, grey), the same verdict without it; CLUSTER good but never pushed")
        cc = R.last_c.get(by["CLEAN"]) or {}
        S2 = T.signals_radar(dict(cc)) or {}

        def same(x, y):
            if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                return x == y
            return abs(x - y) <= 0.01 + 1e-3 * abs(y)          # traps may round (ageMin to 2 places)
        diff = sorted(k for k in LR.S_KEYS if S2.get(k) is not None and cc.get(k) is not None and not isinstance(S2[k], (dict, list)) and not same(S2[k], cc[k]))
        check(cc and not diff, "traps.signals_radar reads the radar's coin dict (CLEAN's, last cycle) as the radar does (%s)" % ("same values" if not diff else "differs: %s" % diff))
        Ru = unit_radar(T, P, tmp, "rdU")
        Ru.symmc = {"BIG": 5_000_000.0}

        def row(n, age=5.0, price=1e-5, liq=20_000.0, mc=50_000.0, fails=(), sym=None, pool=True):
            return {"a": addr(500 + n), "pr": {"pairCreatedAt": (T0 - int(age * MIN)) if pool else None, "symbol": sym or "E%d" % n}, "basic": {"price": price, "liq": liq, "mc": mc},
                    "fails": list(fails)}
        rows = {"ok": row(1), "soft fail": row(2, fails=["lowscore"]), "price 0": row(3, price=0.0), "no price": row(4, price=None), "under YOUNG_MIN_LIQ": row(5, liq=M.YOUNG_MIN_LIQ - 1),
                "at YOUNG_MIN_LIQ": row(6, liq=float(M.YOUNG_MIN_LIQ)), "gate price": row(7, fails=["price"]), "gate curve": row(8, fails=["curve"]), "gate nodex": row(9, fails=["nodex"]),
                "gate honeypot": row(10, fails=["honeypot"]), "gate copy": row(11, fails=["copy"]), "ticker of a bigger coin": row(12, sym="BIG", mc=1_000_000.0),
                "ticker, mc over a third": row(13, sym="big", mc=2_000_000.0), "no pool time": row(14, pool=False), "10.5 min, check pending": row(15, age=10.5),
                "10.5 min, nothing pending": row(16, age=10.5), "12.6 min, check pending": row(17, age=12.6), "10.5 min, no record": row(18, age=10.5)}
        Ru.docs = {"u": {"coins": {rows[n]["a"]: {"addr": rows[n]["a"]} for n in ("10.5 min, check pending", "10.5 min, nothing pending", "12.6 min, check pending")}}}
        Ru.rec_hour = {a: "u" for a in Ru.docs["u"]["coins"]}
        Ru.work = {rows["10.5 min, check pending"]["a"]: {"rc": "pending"}, rows["12.6 min, check pending"]["a"]: {"dev": "pending"},
                   rows["10.5 min, no record"]["a"]: {"rc": "pending"}}
        live_u, fin_u = Ru.eligible(list(rows.values()), T0)
        name_of = {r["a"]: n for n, r in rows.items()}
        got_live, got_fin = sorted(name_of[r["a"]] for r in live_u), sorted(name_of[r["a"]] for r in fin_u)
        check(got_live == sorted(["ok", "soft fail", "at YOUNG_MIN_LIQ", "ticker, mc over a third"]) and got_fin == ["10.5 min, check pending"],
              "eligible: pool under 10 min, a price over 0, liquidity at least YOUNG_MIN_LIQ, none of the gates price/curve/nodex/honeypot/copy, no "
              "ticker of a coin 3x bigger (%s); a recorded coin past 10 min with a check pending is finished for the record until 12.5 min (%s)" % (got_live, got_fin))
        neg, rn = {}, None
        for skew in (1, 30, 119, 300):
            an = addr(710 + skew)
            Ru.cache["pf"][an] = {"t": T0 + skew * 1000}            # the mint `skew` s after the pool: two sources' clocks on one launch
            rn_ = {"a": an, "pr": {"pairCreatedAt": T0, "symbol": "NEG", "name": "Negative Gap", "dexId": "pumpswap", "pairAddress": "NegPool"},
                   "basic": {"price": 1e-5, "liq": 20_000.0, "mc": 50_000.0}, "f": {}, "age": 5.0}
            rn = rn if rn else rn_
            Sn, cn = Ru.signals(rn_, T0 + 5 * MIN)
            rtn = T.rate(Sn, Ru.W_prior)
            S2n = T.signals_radar(dict(cn)) or {}
            neg[skew] = (cn["mint"] == T0 + skew * 1000, Sn.get("instantPool"), cn.get("instantPool"), S2n.get("instantPool"), rtn["verdict"],
                         "instant_pool" in (rtn.get("hard") or []), "mint_time" in (rtn.get("unknown") or []), Ru.chk(an, Sn, T0 + 5 * MIN, False)["mint"])
        hard_ = (True, True, True, True, "trap", True, False, "ok")
        check(neg == {1: hard_, 30: hard_, 119: hard_, 300: (True, None, None, None, neg[300][4], False, True, "unknown")} and neg[300][4] != "good",
              "a pool up to 120 s before its mint (thresholds.mintSkewS: two clocks on one launch) is the instant-pool trap in the radar's own "
              "reading as in traps' (the raw mint goes to traps); 300 s before is unknown, never 'not instant' (%s)" % neg)
        th_ = Ru.thresholds()
        Ru.W = dict(Ru.W_prior, thresholds=dict(th_, mintSkewS=10, instantPoolS=30))
        g10 = (Ru.gap(T0, T0 + 30_000), Ru.gap(T0 + 29_000, T0), Ru.gap(T0 + 31_000, T0), Ru.gap(T0, 1_700_000))
        Ru.W = Ru.W_prior
        check(g10 == ((None, None), (29.0, True), (31.0, False), (None, None)) and Ru.gap(T0, T0 + 30_000) == (-30.0, True) and Ru.gap(T0 + 61_000, T0) == (61.0, False),
              "the radar's own gap reads radar_weights.json's thresholds (I7): mintSkewS 10 makes a pool 30 s before its mint unknown, "
              "instantPoolS 30 moves the line; a time that is no launch time (1970) is unknown (%s)" % (g10,))
        Ru.W = dict(Ru.W_prior, brand=None)
        cb = Ru.coin(dict(rn, pr=dict(rn["pr"], name="Grok Agent")), T0 + 5 * MIN)
        Ru.W = dict(Ru.W_prior, brand="(")
        cb2 = Ru.coin(rn, T0 + 5 * MIN)
        Ru.W = Ru.W_prior
        check(cb["brand"] is None and cb2["brand"] is None and Ru.coin(dict(rn, pr=dict(rn["pr"], name="Grok Agent")), T0 + 5 * MIN)["brand"] is True,
              "the brand check reads only radar_weights.json's list (I7): without a list, or with one that does not compile, it is unknown, never passed")

        wm0 = {"v": 1, "t": T0 - MIN, "nCoins": 500, "common": [], "sw": {}, "rug": []}
        aw, an_ = addr(730), addr(733)
        Ru.cache["rc"][aw] = {"st": "ok", "t": T0, "rep": {"topHolders": [{"owner": addr(731, ""), "pct": 4.0, "address": addr(732, "")}], "risks": [],
                                                         "token": {"supply": 1e9}, "creatorBalance": 0}}
        got_w = {}
        for label, wm_ in (("ok", wm0), ("small", dict(wm0, nCoins=100)), ("empty", dict(wm0, nCoins=0)), ("old", dict(wm0, t=T0 - 4 * H)), ("missing", None)):
            Ru.wm = wm_
            Sw_, _ = Ru.signals(dict(rn, a=aw), T0 + 5 * MIN)
            Sx_, _ = Ru.signals(dict(rn, a=an_), T0 + 5 * MIN)
            nts_ = Ru.build_doc("running", [], [], [], T0 + 5 * MIN, T0 + 5 * MIN + 150_000, 0.0, 0)["notes"]
            got_w[label] = (Ru.wm_state(T0 + 5 * MIN), Ru.chk(aw, Sw_, T0 + 5 * MIN, False)["wm"], Ru.chk(an_, Sx_, T0 + 5 * MIN, False)["wm"], Sw_.get("wmChecked") is True,
                            next((n_ for n_ in nts_ if "wallet" in n_), ""))
        Ru.wm = None
        wn_ = lambda w_: "wallet check unavailable (%s): no coin can be without traps" % w_
        check(got_w == {"ok": ("ok", "ok", "ok", True, ""), "small": ("small", "small", "small", False, wn_("wallet memory too small: 100 of 500 coins")),
                        "empty": ("empty", "empty", "empty", False, wn_("wallet memory empty")), "old": ("old", "old", "old", False, wn_("wallet memory older than 3 h")),
                        "missing": ("missing", "missing", "missing", False, wn_("no wallet memory yet"))},
              "the wallet memory's state as traps judges it (thresholds wmMinCoins 500, wmMaxAgeH 3): a memory of 100 coins is too small, one of 0 "
              "empty; neither checks anything, the record's chk says so (traps' reading; the memory's own state for a coin without holders yet) and "
              "the header gives the reason (%s)" % got_w)
        ax, bx1, bx2, xurl = addr(740), addr(741), addr(742), "https://x.com/somedog"
        nkx = T.norm_x(xurl)
        Ru.docs["x"] = {"coins": {ax: {"addr": ax, "first": T0 - 8 * MIN}}}
        Ru.rec_hour[ax] = "x"
        Ru.cache["pf"][ax] = {"x": xurl}                         # a pump.fun row without the mint time: the reference is the first sighting
        Ru.cache["xidx"][nkx[1]] = {bx1: T0 - 13 * MIN, bx2: T0 - 19 * MIN}       # 5 and 11 minutes before the coin was first seen
        rx_ = {"a": ax, "pr": {"pairCreatedAt": T0 - 9 * MIN, "symbol": "XREF", "name": "X Ref"}, "basic": {"price": 1e-5, "liq": 20_000.0, "mc": 50_000.0}, "f": {}, "age": 9.0}
        xl0, Ru.xlinks = Ru.xlinks, {}
        x_local = Ru.coin(rx_, T0)["xUsed"]
        Ru.cache["xidx"].pop(nkx[1])
        Ru.xlinks = {nkx[1]: [bx1, T0 - 15 * MIN, 1, nkx[0], T0 - 15 * MIN, [[bx1, T0 - 15 * MIN]]]}
        x_feed = Ru.coin(rx_, T0)["xUsed"]
        Ru.xlinks = xl0
        check(x_local == 1 and x_feed == 0,
              "x_copied for a coin without a mint time is counted from its first sighting (traps.x_reuse's reference), not from now: in the "
              "radar's own index only the coin 11 minutes older counts, not the one 5 minutes older (%s); in the scan's index a coin 7 "
              "minutes older than the first sighting is not counted (%s)" % (x_local, x_feed))
        a_pb, tp_ = addr(750), T0 - 30 * MIN       # good and push-worthy at tp_ (pool 2 minutes old), then good but not push-worthy
        Ru.docs["pb"] = {"coins": {a_pb: {"addr": a_pb, "sym": "PBC", "pool": tp_ - 2 * MIN, "first": tp_,
                                          "rt": [[tp_, "good", 0.0, 1, 1e-5, 2], [tp_ + 2 * MIN, "good", 1.0, 0, 1.1e-5, 1]]}}}
        Ru.rec_hour[a_pb] = "pb"
        x_no, x_ok = {"addr": a_pb, "push_ok": False}, {"addr": a_pb, "push_ok": True}
        import radar_paper as RP_pb
        pb_ = {}
        for k_, sw_ in (("after", tp_ - H), ("between", tp_ + MIN), ("before", T0 + H)):
            with env(MEMEBOT_SWITCH_AT=str(sw_)):
                pb_[k_] = (Ru.paper_bought(x_no, T0), Ru.paper_bought(x_ok, T0))
        b2_, RP_pb.buys_v2 = RP_pb.buys_v2, lambda *a_, **k_: 1 / 0
        try:
            for k_, sw_ in (("err after", T0 - H), ("err before", T0 + H)):
                with env(MEMEBOT_SWITCH_AT=str(sw_)):
                    pb_[k_] = (Ru.paper_bought(x_no, T0), Ru.paper_bought(x_ok, T0))
        finally:
            RP_pb.buys_v2 = b2_
            Ru.docs.pop("pb", None)
            Ru.rec_hour.pop(a_pb, None)
        check(pb_ == {"after": (1, 1), "between": (0, 0), "before": (0, 0), "err after": (0, 1), "err before": (0, 0)},
              "TR16 pb is radar_paper's rule 2, not the current rating: a coin bought at its push-worthy rating after the switch stays 1 when "
              "its later rating is not push-worthy; 0 when its only push-worthy rating was before the switch and before the switch at all, "
              "although push_ok is true; when the rule cannot be read, push_ok from the switch on %s" % pb_)
        wo_ = [LR.went_out(o_) for o_ in ({"kind": "radar", "sent": 0, "gone": 0, "bad": 0, "failed": 0, "skipped": None}, {"sent": 1, "skipped": None},
                                          {"sent": 2, "skipped": "rate guard"}, {"skipped": "no push sender"}, None, "sent")]
        gh_ = LR.urllib_host(LR.RS.GH_API)
        Ru.http.dead.add(gh_)
        Ru.http.fails[gh_] = 3
        Ru.http.mute.add(gh_)
        Ru.http.hit429.add(gh_)
        Ru.http.cool[gh_] = time.time() + 600
        Ru.gh_fresh()
        gh_ok = gh_ not in Ru.http.dead and gh_ not in Ru.http.fails and gh_ not in Ru.http.mute and gh_ not in Ru.http.hit429 and gh_ not in Ru.http.cool
        Ru.lines_log = []
        for i_ in range(LR.LOG_KEEP + 7):
            Ru.say("line %d" % i_)
        lp_ = LR.later_points({"later": {"5": {"t": T0 + 5 * MIN, "px": 2e-5, "liq": 9_000.0}, "30": {"t": T0 + 30 * MIN, "gone": True}, "15": {"px": 1.0}}})
        check(wo_ == [False, True, False, False, False, False] and gh_ok and len(Ru.lines_log) <= LR.LOG_KEEP and Ru.lines_log[-1] == "line %d" % (LR.LOG_KEEP + 6)
              and lp_ == [(T0 + 5 * MIN, 2e-5, 9_000.0), (T0 + 30 * MIN, None, 0.0)],
              "small parts: a notification counts as sent only with sent >= 1 and nothing skipped (%s); the kill switch's host is cleared of every "
              "breaker mark before each read; the log in memory stays under LOG_KEEP lines; a later price found gone is liquidity 0 for the "
              "peak's glitch filter (a dead pool), one without a time is left out" % wo_)
        mw_ = json.loads(json.dumps(Ru.W_prior))
        mw_["marker"] = "learned"
        Ru.model, Ru.W = {"v": 1, "from": "prior", "at": T0}, Ru.W_prior
        Ru.load_tree({"model.json": json.dumps({"v": 1, "from": "learned", "at": T0 + MIN, "n": 420, "src": Ru.W_prior.get("src"), "w": mw_}).encode()})
        took = Ru.W.get("marker") == "learned" and Ru.model.get("from") == "learned"
        Ru.model, Ru.W = {"v": 1, "from": "prior", "at": T0 + 2 * MIN}, Ru.W_prior
        Ru.load_tree({"model.json": json.dumps({"v": 1, "from": "learned", "at": T0 + MIN, "n": 420, "src": Ru.W_prior.get("src"), "w": mw_}).encode()})
        kept = Ru.W is Ru.W_prior and Ru.model.get("from") == "prior"
        Ru.model, Ru.W = {}, Ru.W_prior
        check(took and kept, "a restored model.json is put in use at once (its weights with it), unless the run already fitted a newer one")

        print("== launch radar R2b: an old wallet memory, a notification that did not go out")
        rem_w = fresh_remote(T, tmp, "remote-wm", T0 + 2 * MIN, wm_age=4 * H)
        sink_w = Sink()
        code_w, Rw, linesw, _ = run_radar(T, P, url, rem_w, os.path.join(tmp, "rdW"), T0 + 2 * MIN, minutes=2.5, notifier=sink_w)
        dw, rw = radar_json(rem_w), hour_recs(rem_w)
        cw = rw.get(by["CLEAN"]) or {}
        check(code_w == 0 and not dw.get("coins") and any("wallet memory older than 3 h" in n for n in dw.get("notes") or []) and cw.get("chk", {}).get("wm") == "old"
              and cw["rt"][-1][1] != "good" and not cw.get("good") and not sink_w.got,
              "wallet memory 4 hours old: no coin without traps (CLEAN %s), the header says why (%s), nothing sent" % (cw.get("rt", [[0, "?"]])[-1][1], (dw.get("notes") or ["?"])[0]))
        rows_s = []

        def keep_rows(R_):
            orig = R_.store_row
            R_.store_row = lambda doc: (rows_s.append(json.loads(json.dumps(doc))), orig(doc))[1]
        rem_s = fresh_remote(T, tmp, "remote-skip", T0 + MIN)
        code_s, Rsk, liness, _ = run_radar(T, P, url, rem_s, os.path.join(tmp, "rdSk"), T0 + MIN, minutes=2.5, patch=keep_rows,
                                           notifier=lambda coins, record=None: {"kind": "radar", "sent": 0, "gone": 0, "bad": 0, "failed": 0, "skipped": None})
        ds, rsk = radar_json(rem_s), hour_recs(rem_s)
        pj_s = json.loads(branch_files(rem_s, "radar-data").get("pushed.json") or b"{}")
        said = [d_ for d_ in rows_s + [ds] if (d_.get("counts") or {}).get("pushed") or any(c.get("push") for c in d_.get("coins") or [])]
        check(code_s == 0 and rows_s and not said and not (rsk.get(by["CLEAN"]) or {}).get("push") and by["CLEAN"] in pj_s
              and any(n.get("sym") == "CLEAN" for d_ in rows_s for n in d_.get("coins") or [])
              and all(", 0 pushed " in l for l in liness if re.match(r"^cycle \d+:", l)),
              "a notification that reached no phone (app.notify's answer when none is subscribed: sent 0, nothing skipped): neither radar.json nor the app's row nor the record says pushed, the cycle "
              "line says 0 pushed; the coin stays in pushed.json, so it is never sent later")

        print("== launch radar A1: the push follows the learning trader's radar skip signs (radar-feed t3skip.json)")
        import radar_paper as RP_
        b_cl = next(iter(RP_.buys_v2([recs[by["CLEAN"]]], (), 0).values()), None)
        sg_cl = RP_.signs(b_cl["feat"], b_cl["pts"], b_cl["late"]) if b_cl else {}
        on = next((f for f, v in sorted(sg_cl.items()) if v is True), None)
        off = next((f for f, v in sorted(sg_cl.items()) if v is False), None)
        t3doc = lambda f: {"v": 1, "t3v": 1, "day": "2026-10-16", "asOf": T0 - H, "skip": [f], "texts": ["words of " + f]}
        runs_t3 = {}
        for name, t3 in (("on", t3doc(on)), ("off", t3doc(off)), ("bad", b"{not json"), ("none", None)):
            rem_t = fresh_remote(T, tmp, "remote-t3" + name, T0 + MIN, t3=t3)
            sink_t = Sink()
            code_t, R_t, _, _ = run_radar(T, P, url, rem_t, os.path.join(tmp, "rdT3" + name), T0 + MIN, minutes=2.5, notifier=sink_t,
                                          envs={"MEMEBOT_SWITCH_AT": str(T0 - H)})
            d_t = radar_json(rem_t)
            r_t = hour_recs(rem_t).get(by["CLEAN"]) or {}
            runs_t3[name] = (code_t, any("CLEAN" in g["coins"] for g in sink_t.got), next((c for c in d_t.get("coins") or [] if c["sym"] == "CLEAN"), {}), r_t, R_t.t3skip)
        on_, off_, bad_, none_ = (runs_t3[k] for k in ("on", "off", "bad", "none"))
        check(on and off and all(r[0] == 0 for r in runs_t3.values()) and not on_[1] and on_[2].get("t3") == ["words of " + on] and on_[2].get("pb") == 1
              and any(e[1] == "good" and e[3] == 1 for e in on_[3].get("rt") or []) and on_[4] == {on: "words of " + on}
              and off_[1] and "t3" not in off_[2] and bad_[1] and bad_[4] == {} and none_[1] and none_[4] == {},
              "A1 a green coin with a sign the learning trader skips (%s) is not pushed but still rated good, listed with its words (t3) and bought on "
              "paper (pb 1, push-worthy rating); with a sign it lacks (%s) it is pushed; an unreadable or missing t3skip.json changes nothing" % (on, off))

        print("== launch radar R3: later prices, late, gone, outcome")
        check(all("5" in r["later"] for a, r in recs.items() if r["first"] <= T0 + MIN), "the price 5 minutes after first sight is in every record of the first cycle")
        code, R2, lines2, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdC"), T0 + 20 * MIN, minutes=2.5, notifier=sink)
        recs2 = hour_recs(remote)
        l15 = [r["later"].get("15") for r in recs2.values() if r["first"] <= T0 + MIN]
        check(code == 0 and l15 and all(isinstance(x, dict) and x.get("late") is True and x.get("px") for x in l15) and all("30" not in r["later"] for r in recs2.values()),
              "a run 20 minutes later takes the 15-minute prices late and marks them (%d records)" % len(l15))
        mock.gone.add(by["NORC"])
        code, R3, lines3, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdD"), T0 + 61 * MIN, minutes=5, notifier=sink)
        mock.gone.discard(by["NORC"])
        recs3 = hour_recs(remote)
        l60 = {a: r["later"].get("60") for a, r in recs3.items()}
        out = {a: r.get("out") for a, r in recs3.items()}
        cl3 = recs3[by["CLEAN"]]
        check(all(isinstance(v, dict) for v in l60.values()) and l60[by["NORC"]].get("gone") is True and all(not v.get("gone") for a, v in l60.items() if a != by["NORC"])
              and all(isinstance(o, dict) and isinstance(o.get("rug1h"), bool) for o in out.values()) and out[by["NORC"]]["rug1h"] is True
              and isinstance(cl3.get("peak60"), dict) and cl3["peak60"].get("x"),
              "60-minute prices (NORC gone: DexScreener answered without its pair), outcomes for all, CLEAN's peak within the hour %s" % cl3.get("peak60"))
        Rg = LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, "rdG"), "--clock", "fake", "--now", str(T0), "--cache", os.path.join(tmp, "rdG-c"), "--no-github"]),
                      log=lambda s: None, traps=T, peak=P)
        fake = {"addr": "G" * 44, "first": T0 - 5 * MIN, "later": {}, "px": 1.0}
        Rg.docs = {"x": {"coins": {fake["addr"]: fake}}}
        Rg.rec_hour = {fake["addr"]: "x"}
        Rg.later_prices({}, set(), T0)
        unknown_ok = "5" not in fake["later"]
        Rg.later_prices({}, {fake["addr"]}, T0)
        check(unknown_ok and fake["later"].get("5", {}).get("gone") is True, "gone only when DexScreener answered for the coin (no answer: no price, not gone)")
        dcl = next((r for r in radar_json(remote).get("recent") or [] if r.get("addr") == by["CLEAN"]), {})
        check(dcl.get("push") and isinstance(dcl.get("peak60"), dict) and dcl["peak60"].get("x") and dcl["peak60"].get("at"),
              "radar.json's recent calls carry push and peak60 (CLEAN: pushed %s, best close within 1 h %s), the fields the page's Later pane reads"
              % (dcl.get("push"), dcl.get("peak60")))
        win = {"10 s before due": T0 - 5 * MIN + 10_000, "1 s before due (clock jitter)": T0 - 5 * MIN + 1_000, "2 min late": T0 - 7 * MIN, "3 min late": T0 - 8 * MIN}
        wa = {n: addr(600 + i) for i, n in enumerate(win)}
        Rg.docs = {"w": {"coins": {wa[n]: {"addr": wa[n], "first": f, "later": {}, "px": 1.0} for n, f in win.items()}}}
        Rg.rec_hour = {a: "w" for a in wa.values()}
        Rg.later_prices({a: {"priceUsd": "1.5", "liquidityUsd": 9000.0} for a in wa.values()}, set(wa.values()), T0)
        p5 = {n: Rg.docs["w"]["coins"][wa[n]]["later"].get("5") for n in win}
        check(p5["10 s before due"] is None and p5["1 s before due (clock jitter)"] and not p5["1 s before due (clock jitter)"].get("late")
              and p5["2 min late"] and not p5["2 min late"].get("late") and p5["3 min late"] is None and LR.LATE_X == 0.5,
              "the 5-minute price: never taken before it is due (only the clock's 2 s jitter), taken up to half its offset late (2 of 2.5 min, inside "
              "a cycle and half a minute, so not marked late), missing after that (%s)" % {n: (None if v is None else ("late" if v.get("late") else "on time")) for n, v in p5.items()})
        w60 = {"44 min": T0 - 44 * MIN, "46 min": T0 - 46 * MIN, "61 min": T0 - 61 * MIN, "89 min": T0 - 89 * MIN, "91 min": T0 - 91 * MIN, "33 min": T0 - 33 * MIN}
        got60 = {}
        for mode in ("round", "loop"):
            wb = {n: addr(650 + i) for i, n in enumerate(w60)}
            Rg.docs = {"w": {"coins": {wb[n]: {"addr": wb[n], "first": f, "later": {}, "px": 1.0} for n, f in w60.items()}}}
            Rg.rec_hour, Rg.one_round = {a: "w" for a in wb.values()}, mode == "round"
            Rg.later_prices({a: {"priceUsd": "1.5", "liquidityUsd": 9000.0} for a in wb.values()}, set(wb.values()), T0)
            lab = lambda v: None if v is None else "late" if v.get("late") else "early" if v.get("early") else "on time"
            got60[mode] = {n: (lab(Rg.docs["w"]["coins"][wb[n]]["later"].get("60")), sorted(Rg.docs["w"]["coins"][wb[n]]["later"])) for n in w60}
        Rg.one_round = False
        check(got60["round"] == {"44 min": (None, ["30"]), "46 min": ("early", ["60"]), "61 min": ("on time", ["60"]), "89 min": ("late", ["60"]), "91 min": (None, []),
                                 "33 min": (None, ["30"])}
              and got60["loop"] == {"44 min": (None, ["30"]), "46 min": (None, []), "61 min": ("on time", ["60"]), "89 min": ("late", ["60"]), "91 min": (None, []),
                                    "33 min": (None, ["30"])},
              "the 1 h price in a round (the next one comes about an hour later): taken 45 to 90 minutes after first sight (46 min: marked early, "
              "89: late), missing outside that; a loop never takes it early; a round 33 minutes in takes only the 30-minute price, and the prices "
              "no round caught stay missing (no key, never 0): %s" % got60["round"])
        ap = addr(700)
        first = T0 - 63 * MIN
        rec_p = {"addr": ap, "sym": "DEADPK", "pair": "DeadPool", "first": first, "px": 1.0, "liq": 20_000.0, "mc": 50_000.0, "good": first, "peak60": None,
                 "later": {"5": {"t": first + 5 * MIN, "px": 1.0, "liq": 20_000.0}, "15": {"t": first + 15 * MIN, "px": 1.0, "liq": 18_000.0},
                           "30": {"t": first + 30 * MIN, "px": 1.0, "liq": 200.0}, "60": {"t": first + 60 * MIN, "px": 1.0, "liq": 250.0}}}
        cands_p = [[first + i * MIN, 1.0, 1.0, 1.0, 4.0 if 40 <= i <= 42 else 1.0, 900.0] for i in range(60)]
        Rg.docs, Rg.rec_hour, Rg.cache["peak"] = {"p": {"coins": {ap: rec_p}}}, {ap: "p"}, {}
        calls_p = []
        Rg.P = types.SimpleNamespace(peak_of=lambda *a_, **k_: (calls_p.append(k_), P.peak_of(*a_, **k_))[1])
        Rg.src.candles = lambda pool, t0, t1: [[first + 5 * H, 1.0, 1.0, 1.0, 1.0, 900.0]]       # no candle inside the hour yet
        Rg.gt_slot([("peak", ap)], T0)
        waited = rec_p["peak60"] is None and Rg.cache["peak"].get(ap) == 1 and ("peak", ap) in Rg.gt_jobs([], T0)
        Rg.src.candles = lambda pool, t0, t1: cands_p
        Rg.gt_slot([("peak", ap)], T0)
        pk = rec_p["peak60"] or {}
        kw = calls_p[-1] if calls_p else {}
        raw_x = P.peak_of(cands_p, first, first + H, 1.0).get("x")
        check(waited and pk.get("x") is not None and pk["x"] <= 1.05 and raw_x >= 3.9 and any("dead" in c for c in pk.get("cut") or []) and kw.get("liq0") == 20_000.0
              and kw.get("mc0") == 50_000.0 and (first + 30 * MIN, 1.0, 200.0) in (kw.get("ds_points") or []),
              "peak60 with the glitch filter's data (DexScreener's later prices and liquidity, liq0, mc0): a pool dead at minute 30 ($200) keeps "
              "its 4x print out (%s, %s; %sx without them); no candle inside the hour yet: not stored, tried again" % (pk.get("x"), (pk.get("cut") or ["?"])[0], raw_x))
        Rg.P = P
        ag, at_, an_ = addr(720), addr(721), addr(722)
        Rg.docs = {"g": {"coins": {ag: {"addr": ag, "first": T0 - 63 * MIN, "pair": "P1", "good": T0 - 63 * MIN, "peak60": None},
                                   at_: {"addr": at_, "first": T0 - 66 * MIN, "pair": "P2", "good": None, "top": 1, "peak60": None},
                                   an_: {"addr": an_, "first": T0 - 65 * MIN, "pair": "P3", "good": None, "peak60": None}}}}
        Rg.cache["peak"] = {}
        check(Rg.gt_jobs([], T0) == [("peak", ag), ("peak", at_)], "peak60 only for records that were ever good (first) or in the best 5, never for the rest")

        print("== launch radar R4: push notifications")
        pushes = [g for g in sink.got]
        body_ok = all("fake money" in g["body"] and not re.search(r"\b(buy|safe|clean|guaranteed)\b", g["title"].split(":", 1)[-1] + " " + g["body"], re.I) for g in pushes)
        check(len(pushes) == 1 and pushes[0]["coins"] == ["CLEAN"] and pushes[0]["title"].startswith("CLEAN: no trap found (pool ") and body_ok,
              "exactly one notification, for CLEAN, none for INSTA/BRAND/NORC/NOMINT/CLUSTER/RUGGERS/XCOPY/JUPMINT/V3ONLY: %r / %r" % ((pushes or [{}])[0].get("title"), (pushes or [{}])[0].get("body")))
        pj = json.loads(branch_files(remote, "radar-data").get("pushed.json") or b"{}")
        check(set(pj) == {by["CLEAN"]}, "pushed.json on radar-data holds CLEAN")
        check(code_b == 0 and not sink_b.got and rb.get("rt") and len(rb["rt"]) >= 5 and rb["rt"][-1][1] == "good",
              "a restart while CLEAN is still under 10 minutes rates it again (good) and sends nothing (pushed.json restored)")
        x = lambda a, age=5.0, ok=True: {"addr": a, "sym": a[:4], "push_ok": ok, "age": age, "doc": {"sym": a[:4], "age": age, "n": 9, "liq": 23000}}
        Rg.restore_state = "ok"
        nochan = Rg.to_push([x("AAAA")], T0)
        Rg.notifier = Sink()
        Rg.restore_state, Rg.pushed = "ok", {"p%d" % i: T0 - i * 10 * MIN for i in range(4)}
        full = Rg.to_push([x("AAAA")], T0)
        Rg.pushed = {"p%d" % i: T0 - (i + 3) * 20 * MIN for i in range(4)}
        room = Rg.to_push([x("AAAA"), x("BBBB"), x("CCCC", ok=False)], T0)
        Rg.restore_state = "failed"
        norest = Rg.to_push([x("AAAA")], T0)
        t2, b2 = LR.push_text([x("AAAA")["doc"], x("BBBB")["doc"]])
        check(nochan == [] and full == [] and [c["addr"] for c in room] == ["AAAA", "BBBB"] and norest == [] and t2 == "AAAA: no trap found (pool 5 min) +1 more"
              and b2 == "9 checks passed · liquidity $23k · fake money, nothing is bought.",
              "at most 4 notifications an hour; two coins in one cycle make one notification (%r); none when pushed.json was not restored, none without a channel" % t2)
        Ru.cache["paid"], Ru.paid_at = {"A1": False, "A2": True, "A3": False}, {"A1": T0 - 4 * MIN, "A3": T0 - MIN}
        check(Ru.paid_due("A1", T0) and not Ru.paid_due("A2", T0) and not Ru.paid_due("A3", T0) and Ru.paid_due("A4", T0),
              "DexScreener's paid profile: asked again 3 minutes after an unpaid answer (a profile paid while the coin is on the radar is seen), "
              "never again once paid")

        print("== launch radar R5: kill switch, active hours, no successor")
        src_lr = open(LR.__file__, encoding="utf-8").read()
        check(not mock.dispatches and mock.auth_bad == 0 and not any("successor" in l for l in lines + linesb + lines2 + lines3)
              and not hasattr(LR.Radar, "chain") and not hasattr(LR, "CHAIN_BEFORE") and "/dispatches" not in src_lr,
              "no radar run starts another: the 10-minute loop, the restart and the later runs dispatched nothing (the scan's last step starts each round)")
        span = {}
        for m_, ex_ in ((100, []), (0, []), (0, ["--no-github"])):
            lines_m = []
            with env(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9001", GITHUB_REF_NAME="main", MEMEBOT_RADAR_HOURS="0-24"), memebot_rules():
                Rm_ = LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, "rdMin"), "--minutes", str(m_), "--clock", "fake", "--now", str(T0), "--cache",
                                           os.path.join(tmp, "rdMin-c")] + ex_), log=lines_m.append, traps=T, peak=P)
                Rm_.cycle = lambda k_, t_, last_: "off"            # the loop's own length only: no cycle runs
                Rm_.loop()
            span[(m_, bool(ex_))] = ((Rm_.run_end - Rm_.run_start) / MIN if Rm_.run_end else None, any("100 minutes asked" in l for l in lines_m))
        check([LR.run_minutes(m, f) for m, f in ((120, False), (330, False), (70, False), (10, False), (0, False), (0, True), (None, False))] == [70, 70, 70, 10, 55, 0, 55]
              and span == {(100, False): (70.0, True), (0, False): (55.0, False), (0, True): (None, False)},
              "a loop run (a VM's way) lasts at most 70 minutes; 0 = until stopped only without GitHub (a VM), else 55; the loop itself runs that "
              "long (%s)" % span)
        rem_k = fresh_remote(T, tmp, "remote-kill", T0 + 3 * H)
        mock.gh403, mock.workflow = 3, "disabled_manually"
        code_k, Rk, linesk, _ = run_radar(T, P, url, rem_k, os.path.join(tmp, "rdK"), T0 + 3 * H, minutes=10, notifier=Sink())
        mock.gh403, mock.workflow = 0, "active"
        dk = radar_json(rem_k)
        check(code_k == 0 and dk.get("state") == "off" and len([l for l in linesk if re.match(r"^cycle \d+:", l)]) == 3,
              "three 403s from GitHub (its secondary rate limit) never turn the kill switch off: the workflow, disabled meanwhile, is read at the "
              "next cycle and the run ends (state %s after %d cycles)" % (dk.get("state"), len([l for l in linesk if re.match(r"^cycle \d+:", l)])))
        mock.workflow = "disabled_manually"
        code, Ro, lineso, so = run_radar(T, P, url, remote, os.path.join(tmp, "rdO"), T0 + 3 * H, minutes=55, notifier=Sink())
        mock.workflow = "active"
        do = radar_json(remote)
        check(code == 0 and do.get("state") == "off" and not [l for l in lineso if re.match(r"^cycle \d+:", l)] and so < 30 and do.get("lastGood") and do.get("record"),
              "workflow disabled: the run ends within one cycle, radar.json state off (the last good coin and the record line kept)")
        code, Rh, linesh, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdH"), T0 + 3 * H, minutes=55, hours="1-2", notifier=Sink())
        dh = radar_json(remote)
        check(code == 0 and dh.get("state") == "hours" and dh.get("next") and LR.berlin(dh["next"]).hour == 1 and not [l for l in linesh if re.match(r"^cycle \d+:", l)],
              "outside the active hours the loop ends at once with state hours and the next start (%s Berlin)" % (LR.berlin(dh["next"]).strftime("%H:%M") if dh.get("next") else "?"))
        sha0 = refs(remote).get("refs/heads/radar-data")
        hout = []
        with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=remote, GITHUB_TOKEN=None):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_h = LR.main(["hours", "--dir", os.path.join(tmp, "hours"), "--now", str(T0 + 3 * H)], log=hout.append)
        check(rc_h == 0 and buf.getvalue().strip() == "inside=false" and refs(remote).get("refs/heads/radar-data") == sha0 and any("already says so" in l for l in hout),
              "the hours gate step: inside=false, nothing pushed again while radar.json already says hours")
        with env(MEMEBOT_RADAR_HOURS="0-24", RADAR_URL=remote, GITHUB_TOKEN=None):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                LR.main(["hours", "--dir", os.path.join(tmp, "hours2"), "--now", str(T0)], log=hout.append)
        ok_in = buf.getvalue().strip() == "inside=true"
        files_before = branch_files(remote, "radar-data")
        put_branch(remote, "radar-data", dict(files_before, **{"radar.json": json.loads(files_before["radar.json"]) | {"state": "running"}}), tmp)
        with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=remote, GITHUB_TOKEN=None):
            with contextlib.redirect_stdout(io.StringIO()):
                LR.main(["hours", "--dir", os.path.join(tmp, "hours3"), "--now", str(T0 + 3 * H)], log=hout.append)
        after = branch_files(remote, "radar-data")
        check(ok_in and json.loads(after["radar.json"]).get("state") == "hours" and {k for k in after if k != "radar.json"} == {k for k in files_before if k != "radar.json"}
              and all(after[k] == files_before[k] for k in after if k != "radar.json"),
              "the hours gate: inside=true inside the window; outside it writes state hours once and keeps every record file as it was")
        put_branch(remote, "radar-data", dict(after, **{"radar.json": json.loads(after["radar.json"]) | {"state": "running"}}), tmp)
        sha_h, files_h, hout2 = refs(remote).get("refs/heads/radar-data"), branch_files(remote, "radar-data"), []
        fa = types.ModuleType("app")                              # the app's live store, recorded (app.call / put_row / enabled as app.py has them)
        fa.rows, fa.puts, fa.fail = {"radar": json.loads(files_h["radar.json"])}, [], False

        def fa_call(method, path, body=None, **kw):
            if fa.fail:
                raise RuntimeError("HTTP 503")
            return [{"doc": fa.rows["radar"]}] if method == "GET" and "id=eq.radar" in path and "radar" in fa.rows else []
        fa.call, fa.enabled = fa_call, lambda: True
        fa.put_row = lambda rid, doc, track=None: (fa.puts.append((rid, json.loads(json.dumps(doc)))), fa.rows.__setitem__(rid, doc))
        real_exists, real_app = LR.Git.exists, sys.modules.get("app")
        LR.Git.exists = lambda self_, branch, timeout=30: None          # git ls-remote got no answer
        sys.modules["app"] = fa
        app_puts = []
        try:
            with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=remote, GITHUB_TOKEN=None, SUPABASE_URL="http://127.0.0.1:9", SUPABASE_SECRET_KEY="sb_secret_TESTonlyNOTaKEY"):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc_n = LR.main(["hours", "--dir", os.path.join(tmp, "hours4"), "--now", str(T0 + 3 * H)], log=hout2.append)
                    app_puts.append(len(fa.puts))
                    LR.main(["hours", "--dir", os.path.join(tmp, "hours4b"), "--now", str(T0 + 3 * H + MIN)], log=hout2.append)
                    app_puts.append(len(fa.puts))
                    fa.rows["radar"], fa.fail = dict(fa.rows["radar"], state="running"), True
                    LR.main(["hours", "--dir", os.path.join(tmp, "hours4c"), "--now", str(T0 + 3 * H + 2 * MIN)], log=hout2.append)
                    app_puts.append(len(fa.puts))
        finally:
            LR.Git.exists = real_exists
            if real_app is None:
                sys.modules.pop("app", None)
            else:
                sys.modules["app"] = real_app
        prev_h = json.loads(files_h["radar.json"])
        put_h = fa.puts[0][1] if fa.puts else {}
        check(app_puts == [1, 1, 1] and fa.puts[0][0] == "radar" and put_h.get("state") == "hours" and put_h.get("next") and put_h.get("record") == prev_h.get("record")
              and put_h.get("lastGood") == prev_h.get("lastGood") and any("already says so" in l for l in hout2) and any("not read either: nothing written" in l for l in hout2)
              and not any("sb_secret_TEST" in l for l in hout2),
              "the hours gate when GitHub does not answer about radar-data: the app's row still says hours (the page shows the night, not a "
              "stopped radar) and keeps the record line and the last good coin from the row's own last doc; not twice; when the app's store "
              "does not answer either nothing is written")
        rem_n = os.path.join(tmp, "remote-nobranch.git")
        git("init", "-q", "--bare", rem_n)
        with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=rem_n, GITHUB_TOKEN=None):
            with contextlib.redirect_stdout(io.StringIO()):
                rc_m = LR.main(["hours", "--dir", os.path.join(tmp, "hours5"), "--now", str(T0 + 3 * H)], log=hout2.append)
        check(rc_n == 0 and refs(remote).get("refs/heads/radar-data") == sha_h and branch_files(remote, "radar-data") == files_h and any("did not answer" in l for l in hout2)
              and rc_m == 0 and "refs/heads/radar-data" not in refs(rem_n) and any("does not exist yet: not made here" in l for l in hout2),
              "the hours gate when GitHub does not answer about radar-data: radar-data is not written (no tree of radar.json alone over the records); without "
              "the branch it is not made there (the first run makes it from the results copy)")
        vm_t = []

        def vm(R_):
            real = R_.cycle

            def cyc(k, t, last):
                vm_t.append(R_.clock.now())
                return "off" if len(vm_t) >= 3 else real(k, t, last)
            R_.cycle = cyc
        code_v, Rv, linesv, _ = run_radar(T, P, url, None, os.path.join(tmp, "rdV"), T0 - 150_000, minutes=0, hours="13-14", extra=["--no-github"], patch=vm)
        check(code_v == 0 and len(vm_t) == 3 and vm_t[2] >= T0 + 23 * H and any("sleeping until" in l for l in linesv) and Rv.run_end is None,
              "a VM (--no-github, --minutes 0) sleeps through the hours outside the active ones and goes on at the next start (%s Berlin)"
              % (LR.berlin(vm_t[2]).strftime("%H:%M") if len(vm_t) > 2 else "?"))
        long_ = []
        code_l, Rl, linesl, _ = run_radar(T, P, url, None, os.path.join(tmp, "rdL"), T0, minutes=120, extra=["--no-github"],
                                          patch=lambda R_: setattr(R_, "cycle", lambda k, t, last: (long_.append(k), "off")[1]))
        check(code_l == 0 and Rl.run_end - Rl.run_start == 70 * MIN and any("a run is at most 70 minutes" in l for l in linesl),
              "minutes 120 asked: the run lasts 70 (said in the log)")
        states_d = []

        def failing(n_bad):
            def patch_(R_):
                real, store = R_.cycle, R_.store_row
                seen = []

                def cyc(k, t, last):
                    seen.append(k)
                    if len(seen) <= n_bad:
                        raise RuntimeError("cycle broken (test)")
                    return real(k, t, last)
                R_.cycle = cyc
                R_.store_row = lambda doc: (states_d.append((doc.get("state"), doc.get("why"))), store(doc))[1]
            return patch_
        rem_d = fresh_remote(T, tmp, "remote-degraded", T0 + 4 * H)
        code_d, Rdg, linesd, _ = run_radar(T, P, url, rem_d, os.path.join(tmp, "rdDg"), T0 + 4 * H, minutes=10, notifier=Sink(), patch=failing(3))
        first_d = list(states_d)
        del states_d[:]
        rem_e = fresh_remote(T, tmp, "remote-exit", T0 + 4 * H)
        code_e, Re_, linese, _ = run_radar(T, P, url, rem_e, os.path.join(tmp, "rdEx"), T0 + 4 * H, minutes=30, notifier=Sink(), patch=failing(99))
        de = radar_json(rem_e)
        check(code_d == 0 and first_d == [("degraded", "3 cycles in a row failed"), ("ending", "")] and radar_json(rem_d).get("state") == "ending"
              and code_e == 1 and de.get("state") == "degraded" and de.get("why") == "10 cycles in a row failed" and not de.get("coins")
              and (de.get("wm") or {}).get("t") and any("in a row failed" in n for n in de.get("notes") or []),
              "cycles that fail: from the 3rd in a row radar.json says degraded with the reason (%s), the next good cycle says running again; after "
              "10 the run ends (exit 1) and radar.json still says degraded" % first_d)

        # radar.yml's loop (a round every 2 minutes for 55 minutes, each run starting the next): when its next round would fall outside the
        # hours, its last radar.json says hours (no run follows to say it); a failed push of its last round is tried once more (no cycle follows)
        import launch_radar as LR_l
        rem_le = fresh_remote(T, tmp, "remote-loop-end", T0)
        c_le, R_le, l_le, _ = run_radar(T, P, url, rem_le, os.path.join(tmp, "rdLe"), T0 + 50 * MIN, minutes=10, hours="0-15")
        d_le = radar_json(rem_le)
        lastfail = []

        def flaky_last(R_):
            real = R_.git.push_tree

            def pt(files, *a, **k):
                try:
                    st_ = json.load(open(files["radar.json"], encoding="utf-8")).get("state")
                except Exception:
                    st_ = None
                if st_ == "ending" and not lastfail:
                    lastfail.append(1)
                    raise RuntimeError("push refused (test)")
                return real(files, *a, **k)
            R_.git.push_tree = pt
        rem_lp = fresh_remote(T, tmp, "remote-loop-push", T0)
        c_lp, R_lp, l_lp, _ = run_radar(T, P, url, rem_lp, os.path.join(tmp, "rdLp"), T0, minutes=10, patch=flaky_last)
        d_lp = radar_json(rem_lp)
        check(c_le == 0 and d_le.get("state") == "hours" and d_le.get("next") and LR_l.berlin(d_le["next"]).hour == 0
              and c_lp == 0 and lastfail == [1] and any("once more" in l for l in l_lp) and d_lp.get("state") == "ending",
              "the loop: its next round outside the hours (a run ending at 15:00 with hours 0-15) leaves radar.json in state hours with the next "
              "start (%s); the last round's push that failed is tried once more and lands (%s)" % (d_le.get("state"), d_lp.get("state"))
              + ("" if c_le == 0 and c_lp == 0 and lastfail == [1] else " %s" % [c_le, c_lp, lastfail]))

        wf = open(os.path.join(HERE, ".github", "workflows", "radar.yml"), encoding="utf-8").read()
        sc = open(os.path.join(HERE, ".github", "workflows", "scan.yml"), encoding="utf-8").read().splitlines()
        body = lambda lines: lines[lines.index(next(l for l in lines if "Install the push sender" in l)) + 2:][:30]
        job_env = wf.split("    steps:")[0]
        wf_code = "\n".join(l for l in wf.splitlines() if not l.strip().startswith("#"))
        inputs = wf_code.split("permissions:")[0]
        check(re.search(r"^on:\n  workflow_dispatch:", wf, re.M) and "schedule" not in wf and "group: memebot-radar" in wf and "cancel-in-progress: false" in wf
              and re.search(r"^    timeout-minutes: 70\b", wf, re.M) and "if: (vars.MEMEBOT_RADAR || '1') != '0'" in wf and body(wf.splitlines()) == body(sc)
              and "RADAR_URL" not in job_env and "SUPABASE_SECRET_KEY: ${{" not in job_env and not re.search(r"git push|refs/heads/(results|live|radar-feed)", wf)
              and "run: python3 launch_radar.py loop --dir rd --cadence 120 --deadline 100 --minutes 55\n" in wf_code and "launch_radar.py round" not in wf_code
              and not re.search(r"^      minutes:", inputs, re.M) and "options: ['manual', 'hourly', 'auto']" in inputs
              and wf_code.count("/dispatches") == 1 and "if: steps.loop.outcome == 'success'" in wf_code and '"inputs": {"source": "auto"}' in wf_code
              and "actions/cache/save@v4" in wf and "if: always() && steps.hours.outputs.inside == 'true'" in wf
              and "MEMEBOT_RADAR_ADAPTERS: ${{ vars.MEMEBOT_RADAR_ADAPTERS || '' }}" in job_env
              and 'out=$(timeout 150 python3 launch_radar.py hours --dir rd) || out="inside=true"' in wf
              and sorted(int(x) for x in re.findall(r"^        timeout-minutes: (\d+)\b", wf, re.M)) == [1, 2, 3, 4, 62]
              and all("--max-time" in l or re.search(r"\btimeout \d+ curl\b", l) for l in wf.splitlines() if re.search(r"\bcurl\b", l) and not l.strip().startswith("#"))
              and len(re.findall(r"\bcurl -sS --max-time \d+", wf)) == 2,
              "radar.yml: dispatch only (source manual, hourly or auto, no minutes), group memebot-radar, a round every 2 minutes for 55 minutes "
              "(launch_radar.py loop, step 62, job 70 min), one next-run step only after a loop that ended well, MEMEBOT_RADAR gate, the adapter switches from a repository variable, the push sender's install "
              "step as in scan.yml, the token only in the steps that use it, the hours and tidy steps bounded in time (they hold the radar's group)")

        print("== launch radar R6: limits")
        lim = fixture("LIMIT", 11, pool=T0 + 4 * H - MIN, mint=T0 + 4 * H - 5 * MIN)
        hang = fixture("HANG", 12, pool=T0 + 4 * H - MIN, mint=T0 + 4 * H - 5 * MIN)
        mock2 = RadarMock([lim, hang])
        mock2.rc429.add(lim["a"])
        mock2.hang.add("/orders/v1/solana/" + hang["a"])
        mock2.jup_bad = True
        srv2 = serve(mock2)
        url2 = "http://127.0.0.1:%d" % srv2.server_address[1]
        rem2 = os.path.join(tmp, "remote2.git")
        git("init", "-q", "--bare", rem2)
        put_branch(rem2, "radar-feed", feed_files(T, T0 + 4 * H), tmp)
        code, R6, lines6, secs6 = run_radar(T, P, url2, rem2, os.path.join(tmp, "rd6"), T0 + 4 * H, minutes=2.5, notifier=Sink(), deadline=4.0)
        d6, r6 = radar_json(rem2), hour_recs(rem2)
        lr = r6.get(lim["a"]) or {}
        check(code == 0 and lr.get("chk", {}).get("rc") == "429" and lr["rt"][-1][1] != "good" and any("429 rate limited by api.rugcheck.xyz" in l for l in lines6)
              and d6.get("hosts", {}).get("rugcheck") == "limited" and any(n.startswith("RugCheck limited") for n in d6.get("notes") or []),
              "RugCheck 429: the coin stays unknown (%s), never good, the host is skipped and noted (%s)" % (lr.get("rt", [[0, "?"]])[-1][1], d6.get("notes")))
        check(secs6 <= 4.0 + 5 and (d6.get("secs") or 99) <= 4.0 + 5, "a host that hangs 20 s never holds the cycle past its deadline + 5 s (%.1f s, deadline 4 s)" % (d6.get("secs") or -1))
        check(R6.src.on.get("jup_recent") is False and d6.get("hosts", {}).get("jupiter") != "down" and any("jup recent not checked (source down)" in n for n in d6.get("notes") or [])
              and any("jup_recent: the answer has no" in l for l in lines6), "an answer in another shape turns its adapter off for the run, said once")
        srv2.shutdown()
        srv2.server_close()

        print("== launch radar R7: the radar-data branch")
        now_refs = refs(remote)
        check(set(now_refs) - set(before) == {"refs/heads/radar-data"} and all(now_refs[r] == before[r] for r in before),
              "the radar wrote branch radar-data only (refs %s), results and radar-feed untouched" % sorted(r.split("/")[-1] for r in now_refs))
        sha = now_refs["refs/heads/radar-data"]
        Rs = LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, "rdS"), "--clock", "fake", "--now", str(T0 + 70 * MIN), "--cache", os.path.join(tmp, "rdS-c"),
                                  "--remote", remote, "--no-github"]), log=lambda s: None, traps=T, peak=P)
        with memebot_rules():
            Rs.restore()
        hr = sorted(Rs.docs)[0]
        drop = next(iter(Rs.docs[hr]["coins"]))
        del Rs.docs[hr]["coins"][drop]
        landed = Rs.publish(LR.finish_from({}, "running", T0 + 70 * MIN, "", "t", None, None, "manual", (0, 24)))
        check(Rs.restore_state == "ok" and landed is False and refs(remote)["refs/heads/radar-data"] == sha and any("never-shrink guard" in n for n in Rs.notes_run),
              "the never-shrink guard refuses a tree with fewer records than the last one in the same hours")
        Rs2 = unit_radar(T, P, tmp, "rdS2", now=T0 + 70 * MIN, extra=["--remote", remote])
        with memebot_rules():
            Rs2.restore()
        gone_h = max(Rs2.docs, key=lambda h: len(Rs2.docs[h]["coins"]))
        del Rs2.docs[gone_h]
        landed2 = Rs2.publish(LR.finish_from({}, "running", T0 + 70 * MIN, "", "t", None, None, "manual", (0, 24)))
        hr0 = LR.utc_hour(T0)
        hr_old = LR.utc_hour(T0 - 3 * H)
        check(landed2 is False and refs(remote)["refs/heads/radar-data"] == sha and not LR.guard_ok({}, {hr0: 4}, T0)[0] and LR.guard_ok({hr0: 4}, {hr0: 4, hr_old: 9}, T0)[0]
              and not LR.guard_ok({hr0: 3}, {hr0: 4}, T0)[0],
              "never-shrink: an hour doc that vanished counts with 0 (a whole hour of records missing is refused); an hour older than 47 h rolls off")
        answers, asked = [None, True], []
        Rt = unit_radar(T, P, tmp, "rdT", now=T0 + 70 * MIN, extra=["--remote", remote], log=lambda s_: None)
        Rt.git.exists = lambda b, timeout=30: (asked.append(b), answers.pop(0))[1]
        with memebot_rules():
            Rt.restore()
        answers2, asked2, said_t = [None, False], [], []
        Rt2 = unit_radar(T, P, tmp, "rdT2", now=T0 + 70 * MIN, extra=["--remote", remote], log=said_t.append)
        Rt2.git.exists = lambda b, timeout=30: (asked2.append(b), answers2.pop(0))[1]
        with memebot_rules():
            Rt2.restore()
        check(Rt.restore_state == "ok" and len(asked) == 2 and Rt.docs and Rt2.restore_state == "ok" and len(asked2) == 2 and any("does not exist yet" in l for l in said_t),
              "a restore whose git ls-remote got no answer asks again on the next try (then restores, or starts fresh when the branch is gone)")
        sink_f = Sink()

        def broken(R_):
            def bad(*a, **k):
                raise RuntimeError("fetch failed (test)")
            R_.git.fetch_ok = R_.git.fetch
            R_.git.fetch = lambda branch, ref, timeout=60: bad() if branch == "radar-data" else R_.git.fetch_ok(branch, ref, timeout)
        mock.coins[by["CLEAN"]]["pool"] = T0 + 2 * H
        code, Rf, linesf, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdF"), T0 + 2 * H + MIN, minutes=2.5, notifier=sink_f, patch=broken)
        mock.coins[by["CLEAN"]]["pool"] = T0
        check(code == 0 and Rf.restore_state == "failed" and refs(remote)["refs/heads/radar-data"] == sha and Rf.publishes == 0 and not sink_f.got
              and any("not restored" in n for n in Rf.notes_run),
              "radar-data that cannot be read: no record push, no notification (a pushable coin was on the list), retried every cycle")

        print("== launch radar R8: memebot's rules under their own names, three files unchanged, standard library only")
        src = open(os.path.join(HERE, "launch_radar.py"), encoding="utf-8").read() + open(os.path.join(HERE, "radar_src.py"), encoding="utf-8").read()
        import fetch as F
        import radar as RD
        used_m = set(re.findall(r"\bM\.([A-Za-z_][A-Za-z0-9_]*)", src))
        used_f = set(re.findall(r"\bF\.([A-Za-z_][A-Za-z0-9_]*)", src))
        used_r = set(re.findall(r"\bRD\.([A-Za-z_][A-Za-z0-9_]*)", src))
        pinned = ("scan", "load_pairs", "load_side", "load_lists", "positions", "apply_profile", "YOUNG_MIN_LIQ", "B58", "PF_COLS", "GT_COLS", "JUP_COLS", "DEV_COLS",
                  "DP_COLS", "x_link", "launchpad_of", "parse_ms", "chances", "load_train", "pos_value", "CURVE_DEX", "PAPER_RULE")
        check(all(n in used_m and hasattr(M, n) for n in pinned) and all(hasattr(M, n) for n in used_m) and all(hasattr(F, n) for n in used_f) and all(hasattr(RD, n) for n in used_r)
              and {"gather", "weights", "ds_chunk"} <= used_r and "blended_weights" not in used_m and not re.search(r"^\s*def (scan|young_rows|cmd_gather|risk_view)\b", src, re.M),
              "launch_radar.py and radar_src.py call %d memebot, %d fetch and %d radar names, all exist, none copied, never blended_weights" % (len(used_m), len(used_f), len(used_r)))
        same = []
        for f in ("memebot.py", "fetch.py", "radar.py"):
            p = subprocess.run(["git", "-C", HERE, "show", "%s:%s" % (BASE, f)], capture_output=True)
            now_b = open(os.path.join(HERE, f), "rb").read()
            if f == "memebot.py" and p.returncode == 0 and p.stdout != now_b:
                # the three changes since: the switch (memebot.switch_at, the new launches end; PAPER_RULE as it was), the big test read
                # lazily (DocDir, 16 Oct, the user's go: only how memesnap and memesnapres are loaded) and the training window
                # (TRAIN_DAYS, 21 Oct, the user's go). Every changed stretch of memebot.py names one of them, and nothing else in it moved
                import difflib, hashlib
                hunks, cur = [], []
                for ln in difflib.unified_diff(p.stdout.decode("utf-8").splitlines(), now_b.decode("utf-8").splitlines(), lineterm="", n=0):
                    if ln.startswith("@@"):
                        cur = []
                        hunks.append(cur)
                    elif ln[:1] in "+-" and not ln.startswith(("+++", "---")):
                        cur.append(ln)
                old_k = ("switch_at", "SWITCH_AT", "young_on", "PAPER_LABEL", "DocDir", "LAZY_COLLS", "memesnapres", "collections.abc")
                win_k = ("TRAIN_DAYS", "train_since", "in_window")
                txt = lambda h: "\n".join(h)
                # the stretches that name only the window are pinned whole (the fingerprint of their removed and added lines, 21 Oct): any
                # other edit inside them, or a new one, fails until it is authorized and the fingerprint renewed
                win = [h for h in hunks if any(k in txt(h) for k in win_k) and not any(k in txt(h) for k in old_k)]
                win_ok = hashlib.sha256("\n".join(sorted(ln for h in win for ln in h)).encode("utf-8")).hexdigest() == \
                    "d8bd4356505a87338c8cc34b3029245fe681d5538ad8e2cadec3b592f3a5c70a"
                same.append(bool(hunks) and all(any(k in txt(h) for k in old_k + win_k) for h in hunks) and win_ok
                            and not any(ln.startswith("-PAPER_RULE") for h in hunks for ln in h))
                continue
            same.append(p.returncode == 0 and p.stdout == now_b)
        import ast
        mods = set()
        for f in ("launch_radar.py", "radar_src.py"):
            for node in ast.walk(ast.parse(open(os.path.join(HERE, f), encoding="utf-8").read())):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
        own = {"memebot", "fetch", "radar", "radar_src", "app", "traps", "peak", "radar_paper"}
        std = set(getattr(sys, "stdlib_module_names", ())) or {"argparse", "datetime", "glob", "gzip", "importlib", "io", "json", "math", "os", "re", "shutil", "subprocess",
                                                              "sys", "tarfile", "time", "urllib", "zoneinfo"}
        check(all(same) and mods - own <= std, "fetch.py and radar.py are byte for byte as at %s, memebot.py too but for the switch, the lazy big test and the training window (%s); imports: %s" % (BASE, same, sorted(mods - own)))

        print("== launch radar R9: no secret in any file, branch, row or log line")
        from selftest import Rest, serve_app, PushSink, APP_SECRET
        rest, psink = Rest(), PushSink()
        asrv = serve_app(rest, psink)
        sb_url = "http://127.0.0.1:%d" % asrv.server_address[1]
        code, R9, lines9, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rd9"), T0 + 5 * H, minutes=2.5, notifier=Sink(),
                                        envs={"SUPABASE_URL": sb_url, "SUPABASE_SECRET_KEY": APP_SECRET})
        bad_remote = "https://x-access-token:%s@127.0.0.1:9/nothing.git" % GH_TOKEN
        code_b, Rx, linesx, _ = run_radar(T, P, url, bad_remote, os.path.join(tmp, "rdX"), T0 + 5 * H, minutes=2.5, notifier=Sink(),
                                          envs={"SUPABASE_URL": sb_url, "SUPABASE_SECRET_KEY": APP_SECRET})
        row = (rest.live.get("radar") or {}).get("doc") or {}
        blobs = []
        for f in glob.glob(os.path.join(tmp, "**", "*"), recursive=True):
            if os.path.isfile(f) and "/git/" not in f and ".git" + os.sep not in f:
                try:
                    blobs.append(open(f, "rb").read())
                except OSError:
                    pass
        for b in ("radar-data", "results", "radar-feed"):
            blobs += list(branch_files(remote, b).values())
        allt = b"\n".join(blobs) + "\n".join(lines + lines2 + lines3 + lines6 + lines9 + linesx + linesf + linesb + linesk + lineso + linesh + hout).encode() + json.dumps(row).encode()
        secrets = [GH_TOKEN.encode(), APP_SECRET.encode()]
        said_r = []
        with env(GITHUB_TOKEN=GH_TOKEN, SUPABASE_SECRET_KEY=APP_SECRET):
            Rr = unit_radar(T, P, tmp, "rdR", log=said_r.append)
            Rr.say("push to %s failed, token %s, key %s, sb_secret_abcdefgh123" % (bad_remote, GH_TOKEN, APP_SECRET))
        check(said_r and not any(s_.decode() in said_r[-1] for s_ in secrets) and "sb_secret_abc" not in said_r[-1] and "https://127.0.0.1:9/nothing.git" in said_r[-1],
              "the radar's own log redacts a credentialed URL, the token's and the secret key's values and any sb_secret_ key: %r" % (said_r[-1][:120] if said_r else ""))
        check(row.get("kind") == "radar" and not any(s in allt for s in secrets) and any("radar-data restore failed" in l for l in linesx) and code_b == 0,
              "the app's row radar written (%s); neither the GitHub token nor the store's secret key in %d files, 3 branches, the row or %d log lines (a credentialed remote that fails is redacted)"
              % (row.get("state"), len(blobs), len(lines + lines9 + linesx)))
        asrv.shutdown()
        asrv.server_close()

        print("== launch radar R10: the radar model")
        planted = lambda n, ok: plant(T, n, ok)
        rem_of = {}
        for name, n, ok, want in (("few", 250, True, "prior"), ("good", 420, True, "learned"), ("reversed", 420, False, "prior")):
            rem_m = rem_of[name] = os.path.join(tmp, "remote-%s.git" % name)
            git("init", "-q", "--bare", rem_m)
            put_branch(rem_m, "results", planted(n, ok), tmp)
            put_branch(rem_m, "radar-feed", feed_files(T, T0 + 6 * H), tmp)
            code, Rm, linesm, _ = run_radar(T, P, url, rem_m, os.path.join(tmp, "rdM-" + name), T0 + 6 * H, minutes=5, notifier=Sink())
            dm = radar_json(rem_m)
            mj = json.loads(branch_files(rem_m, "radar-data").get("model.json") or b"{}")
            md_ = dm.get("model") or {}
            why_ok = (md_.get("why") == "") if n < 300 else (bool(md_.get("why")) if want == "prior" else True)    # "study prior kept: ..." from 300 on
            prior_ok = isinstance(md_.get("prior"), (int, float)) if name == "good" else True
            check(code == 0 and mj.get("from") == want and md_.get("from") == want and md_.get("need") == 300 and mj.get("src") == Rm.W_prior.get("src")
                  and (md_["n"] == n) and ((want == "learned") == (Rm.W is not Rm.W_prior)) and why_ok and prior_ok,
                  "%d planted records (%s): model %s, radar.json says %s of %s needed%s" % (n, name, mj.get("from"), dm.get("model", {}).get("n"), dm.get("model", {}).get("need"),
                                                                                         ("; " + mj.get("why")) if mj.get("why") else ""))
        rem_g = rem_of["good"]
        fg = branch_files(rem_g, "radar-data")
        mg = json.loads(fg["model.json"])
        mg["w"]["marker"] = "from radar-data"
        put_branch(rem_g, "radar-data", dict(fg, **{"model.json": mg}), tmp)
        seen_m = {}

        def model_seen(fail_n, fit=True):
            def patch(R_):
                ob, of = R_.build_doc, R_.git.fetch
                left = [fail_n]

                def bd(*a_, **k_):
                    d_ = ob(*a_, **k_)
                    seen_m.setdefault(fail_n, []).append((d_["model"]["from"], (R_.W or {}).get("marker")))
                    return d_

                def fetch(*a_, **k_):
                    if a_ and a_[0] == "radar-data" and left[0] > 0:
                        left[0] -= 1
                        raise RuntimeError("planted: radar-data not readable")
                    return of(*a_, **k_)
                R_.build_doc, R_.git.fetch = bd, fetch
                if not fit:
                    R_.maybe_fit = lambda now_: None             # the run fits nothing itself: only the restored model can be in use
            return patch
        run_radar(T, P, url, rem_g, os.path.join(tmp, "rdM-start"), T0 + 6 * H + 10 * MIN, minutes=2.5, notifier=Sink(), patch=model_seen(0))
        run_radar(T, P, url, rem_g, os.path.join(tmp, "rdM-retry"), T0 + 6 * H + 20 * MIN, minutes=4, notifier=Sink(), patch=model_seen(4, fit=False))
        check(seen_m.get(0, [None])[0] == ("learned", "from radar-data") and [x for x in seen_m.get(4, [])][:1] == [("prior", None)]
              and seen_m.get(4, [None])[-1] == ("learned", "from radar-data"),
              "a learned model.json on radar-data is in use from the run's first cycle (%s); when radar-data is read only at a later cycle, its "
              "model and weights are put in use together then, never 'learned' over the prior's weights (%s)" % (seen_m.get(0, [])[:1], seen_m.get(4)))
        Ru.model = {"from": "learned", "w": {"v": 1, "points": {}}, "src": "another study"}
        stale = Ru.apply_model()
        stale_ok = stale is False and Ru.W is Ru.W_prior and Ru.model == {}
        Ru.model = {"from": "learned", "w": json.loads(json.dumps(Ru.W_prior)), "src": Ru.W_prior.get("src")}
        check(stale_ok and Ru.apply_model() and Ru.W is Ru.model["w"],
              "model.json's learned weights are used only when fitted on this study prior (src); another prior's are dropped and fitted again")
        Ru.W = Ru.W_prior
        size = lambda d_: len(json.dumps(d_, separators=(",", ":")))
        big = {"coins": [], "others": [{"addr": "A" * 44, "sym": "S", "age": 1.0, "v": "watch", "pts": 2, "line": [["warn", "x" * 150]]} for _ in range(400)],
               "recent": [{"addr": "B" * 44, "sym": "R", "good": T0, "later": {}, "out": None} for _ in range(20)]}
        f1 = LR.fit_size(json.loads(json.dumps(big)))
        f2 = LR.fit_size(dict(json.loads(json.dumps(big)), others=big["others"][:5], recent=[{"addr": "B" * 44, "sym": "R", "good": T0, "later": {"x": "y" * 2000}} for _ in range(40)]))
        check(size(f1) <= LR.DOC_MAX and len(f1["recent"]) == 20 and 0 < len(f1["others"]) < 400 and size(f2) <= LR.DOC_MAX and f2["others"] == [] and 0 < len(f2["recent"]) < 40,
              "radar.json over 48 KB: the fold (others) is cut first (%d of 400 left, recent kept), then recent (%d of 40 left)" % (len(f1["others"]), len(f2["recent"])))
        round_checks(check, LR, T, P, tmp)
        fast_checks(check, LR, T, P, tmp)
        probe_checks(check, LR, T, P, url, mock, heads_a, recs, by, tmp)
        talk_checks(check, LR, T, P, tmp, pushes, recs[by["CLEAN"]])
        fastlane_checks(check, LR, T, P, tmp)
        fastpush_checks(check, LR, T, P, tmp)
        curve_doc_checks(check, LR, T, P, url, mock, tmp)
        if not real_push(check, T, P, url, remote, tmp):
            SKIPPED.append("R4's PushSink leg (app.notify_radar comes with WP4)")
    finally:
        rules.__exit__(None, None, None)
        MOCK = None
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


def round_checks(check, LR, T, P, tmp):
    """R12: one round per start (radar.yml's way, the scan starting one after each full scan): one cycle and the run ends, never a
    successor; radar.json state done with about when the next round comes; the later prices a later round can still catch (the 1 h
    price 45 to 90 minutes after first sight gives the outcome; the 5/15/30-minute ones stay missing, never 0, and nothing waits for
    them); a round that fails, a push to radar-data that fails, a model fitted in a round, the kill switch."""
    print("== launch radar R12: one round per start (no successor), the later prices hourly rounds can catch")
    TR = T0 + 7 * H                          # 19:00 UTC, 21:00 Berlin
    ca = fixture("RNDA", 31, pool=TR - 2 * MIN, mint=TR - 6 * MIN)
    cb = fixture("RNDB", 32, pool=TR - 3 * MIN, mint=TR - 7 * MIN)
    cc = fixture("RNDC", 33, pool=TR + 18 * MIN, mint=TR + 14 * MIN)     # launched between the hourly rounds: the manual round finds it
    m3 = RadarMock([ca, cb])
    srv3 = serve(m3)
    url3 = "http://127.0.0.1:%d" % srv3.server_address[1]
    rem = fresh_remote(T, tmp, "remote-round", TR)
    ncyc = lambda L: len([l for l in L if re.match(r"^cycle \d+:", l)])
    go = lambda name, at, src, remote=rem, **kw: run_radar(T, P, url3, remote, os.path.join(tmp, name), at, cmd="round", source=src, notifier=kw.pop("notifier", Sink()), **kw)
    try:
        c1, R1, l1, s1 = go("rdR1", TR, "hourly")
        d1, r1 = radar_json(rem), hour_recs(rem)
        run1 = d1.get("run") or {}
        model1 = json.loads(branch_files(rem, "radar-data").get("model.json") or b"{}")
        check(c1 == 0 and ncyc(l1) == 1 and any("one round" in l for l in l1) and d1.get("state") == "done" and run1.get("mode") == "round"
              and run1.get("source") == "hourly" and run1.get("end") is None and d1.get("hourly") == R1.run_start and d1.get("next") == R1.run_start + H
              and {ca["a"], cb["a"]} <= set(r1) and all(r1[x]["later"] == {} for x in (ca["a"], cb["a"])) and not m3.dispatches
              and not any("successor" in l for l in l1) and s1 < 60,
              "a round (radar.yml's way, started by the scan): exactly one cycle and the run ends (%.1f s here); radar.json state done, mode round, "
              "the next round about an hour after this one (%s), both new coins recorded; nothing dispatched"
              % (s1, LR.berlin(d1["next"]).strftime("%H:%M Berlin") if d1.get("next") else "?"))
        check(model1.get("at") and model1.get("from") in ("prior", "learned"),
              "a round that fits the radar model pushes model.json again right after (no later cycle would): radar-data's model.json dated %s" % model1.get("at"))
        m3.coins[cc["a"]] = cc
        c2, R2, l2, _ = go("rdR2", TR + 20 * MIN, "manual")
        d2, r2 = radar_json(rem), hour_recs(rem)
        la2 = r2[ca["a"]]["later"]
        check(c2 == 0 and ncyc(l2) == 1 and d2.get("state") == "done" and (d2.get("run") or {}).get("source") == "manual" and d2.get("hourly") == R1.run_start
              and d2.get("next") == R1.run_start + H and sorted(la2) == ["15"] and la2["15"].get("late") is True and cc["a"] in r2
              and not any(l.startswith("radar model:") for l in l2),
              "a round by hand 20 minutes later: the next hourly round stays an hour after the scan's last one; it takes the 15-minute price "
              "(%s, late) and the 5-minute one stays missing; the model fitted in the first round is kept, not fitted again" % sorted(la2))
        m3.gone.add(cb["a"])
        c3, R3, l3, _ = go("rdR3", TR + 52 * MIN, "hourly")
        m3.gone.discard(cb["a"])
        d3, r3 = radar_json(rem), hour_recs(rem)
        la, lb, lc = (r3[x["a"]]["later"] for x in (ca, cb, cc))
        oa, ob = r3[ca["a"]].get("out") or {}, r3[cb["a"]].get("out") or {}
        ra = next((x for x in d3.get("recent") or [] if x.get("addr") == ca["a"]), {})
        check(c3 == 0 and ncyc(l3) == 1 and sorted(la) == ["15", "60"] and la["60"].get("early") is True and la["60"].get("px") and lb["60"].get("gone") is True
              and oa.get("rug1h") is False and ob.get("rug1h") is True and sorted(lc) == ["30"] and d3.get("hourly") == R3.run_start and d3.get("next") == R3.run_start + H
              and (ra.get("later") or {}).get("5") is None and (ra.get("later") or {}).get("30") is None and isinstance((ra.get("later") or {}).get("60"), float)
              and ra.get("miss60") is False and ((d3.get("record") or {}).get("n60") or 0) >= 1,
              "the next hourly round, 52 minutes in: the first round's coins get their 1 h price (8 minutes early, marked early; RNDB's pool gone) "
              "and so a 1 h outcome for the record line and the model (RNDA alive, RNDB rugged); the coin the manual round found gets its "
              "30-minute price; radar.json's later for RNDA: %s (null = not caught, shown as a dash; never 0)" % (ra.get("later"),))
        c4, R4, l4, _ = go("rdR4", TR + 112 * MIN, "hourly")
        d4, r4 = radar_json(rem), hour_recs(rem)
        rc4 = r4[cc["a"]]
        rcd = next((x for x in d4.get("recent") or [] if x.get("addr") == cc["a"]), {})
        rad = next((x for x in d4.get("recent") or [] if x.get("addr") == ca["a"]), {})
        check(c4 == 0 and ncyc(l4) == 1 and "60" not in rc4["later"] and rc4.get("out") is None and sorted(rc4["later"]) == ["30"]
              and rcd.get("miss60") is True and (rcd.get("later") or {}).get("60") is None and rad.get("miss60") is False and (rad.get("out") or {}).get("rug1h") is False
              and not m3.dispatches and not any("successor" in l for l in l1 + l2 + l3 + l4),
              "a coin whose 1 h price no round caught (the next round came 92 minutes after first sight): the price stays missing, no outcome, "
              "nothing waits or fails (radar.json marks it miss60 for the page); four rounds, one cycle each, nothing ever dispatched")
        Rn = unit_radar(T, P, tmp, "rdN", now=TR)
        late_eve = TR + 150 * MIN                                       # 23:30 Berlin
        Rn.hours, Rn.source, Rn.run_start = (7, 24), "hourly", late_eve
        nx_night = Rn.next_round(late_eve + 2 * MIN)
        Rn.source, Rn.last_doc = "manual", {"hourly": TR - 130 * MIN}
        Rn.hours = (0, 24)
        nx_man = Rn.next_round(TR)
        Rn.last_doc = {"hourly": TR - 4 * H}
        nx_old = Rn.next_round(TR)
        Rn.last_doc = {}
        nx_none = Rn.next_round(TR)
        check(nx_night == late_eve + 8 * H and LR.berlin(nx_night).strftime("%H:%M") == "07:30" and nx_man == TR + 50 * MIN and nx_old is None and nx_none is None,
              "the next round's time: an hour after the scan's last round, inside the active hours (a round at 23:30 Berlin -> 07:30); for a "
              "round by hand from the last hourly one (2 h 10 min ago -> in 50 min); unknown when none is known from the last 3 hours")

        def boom(R_):
            def bad(k, t, last):
                raise RuntimeError("cycle broken (test)")
            R_.cycle = bad
        rem_x = fresh_remote(T, tmp, "remote-round-x", TR)
        cx, Rx, lx, _ = go("rdRx", TR, "hourly", remote=rem_x, patch=boom)
        dx = radar_json(rem_x)
        check(cx == 1 and dx.get("state") == "degraded" and str(dx.get("why")).startswith("the round failed: ") and (dx.get("run") or {}).get("mode") == "round"
              and dx.get("next") == Rx.run_start + H and not dx.get("coins"),
              "a round whose cycle fails: exit 1 (the run shows red), radar.json says degraded with the reason (%s) and the next round's time" % dx.get("why"))
        fails = []

        def flaky(R_):
            real = R_.git.push_tree

            def pt(*a, **k):
                if len(fails) < 2:
                    fails.append(1)
                    raise RuntimeError("push refused (test)")
                return real(*a, **k)
            R_.git.push_tree = pt
        rem_p = fresh_remote(T, tmp, "remote-round-p", TR)
        cp, Rp, lp, _ = go("rdRp", TR, "hourly", remote=rem_p, patch=flaky)
        rp = hour_recs(rem_p)
        check(cp == 0 and len(fails) == 2 and any("once more" in l for l in lp) and {ca["a"], cb["a"]} <= set(rp) and radar_json(rem_p).get("state") == "done",
              "a round whose pushes to radar-data fail (the list's and the model's) tries once more at its end, since no cycle comes after it: "
              "its records land (%d)" % len(rp))
        m3.workflow = "disabled_manually"
        co, Ro, lo, so = go("rdRo", TR + 113 * MIN, "manual")
        m3.workflow = "active"
        do = radar_json(rem)
        ch, Rh, lh, _ = go("rdRh", TR + 114 * MIN, "hourly", hours="1-2")
        dh = radar_json(rem)
        check(co == 0 and do.get("state") == "off" and ncyc(lo) == 0 and do.get("record") and ch == 0 and dh.get("state") == "hours" and ncyc(lh) == 0
              and dh.get("next") and LR.berlin(dh["next"]).hour == 1 and not m3.dispatches,
              "kill switches unchanged: a round that starts while the workflow is disabled (one queued before the switch) ends at once with "
              "state off; one outside the active hours ends with state hours and the next start")
    finally:
        srv3.shutdown()
        srv3.server_close()


def fast_checks(check, LR, T, P, tmp):
    """R13: 2-minute rounds (radar.yml: --cadence 120 --deadline 100) on a fake clock of 120 s a cycle: the deadline and step ends, a
    coin without a pair asked again at the next cycle, the later prices at 6, 16, 30 and 60 minutes (none late), rt of RT_MAX ratings
    with 6 fields (radar_paper buys the same as from 4); momentum on paper set once by its rule and nothing else changed by it; the
    record line's mom and all (the 60-minute price alone)."""
    import radar_paper as RP
    print("== launch radar R13: 2-minute rounds, momentum on paper")
    wf = open(os.path.join(HERE, ".github", "workflows", "radar.yml"), encoding="utf-8").read()
    cd = re.search(r"launch_radar\.py loop --dir rd --cadence (\d+) --deadline (\d+) ", wf)
    R2 = unit_radar(T, P, tmp, "rdF", extra=["--cadence", "120"], clock=LR.FakeClock(T0, step=120_000))
    ends = [round(R2.deadline * s_ / LR.DEADLINE_S, 3) for s_ in LR.STEP_END.values()]
    check(cd and (int(cd.group(1)), int(cd.group(2))) == (120, R2.deadline) and R2.deadline == 100 and R2.step == 120_000 and ends == [20, 28, 48, 76, 84, 96]
          and LR.FakeClock(T0).step == LR.CYCLE_S * 1000 == 150_000,
          "radar.yml's --cadence 120 --deadline 100: 125 s scaled to 120 is %g s, the step ends %s s; the fake clock's default stays 150 s"
          % (R2.deadline, "/".join("%g" % e for e in ends)))

    sb = os.path.join(tmp, "rdF-sb")
    os.makedirs(sb, exist_ok=True)
    a_np, a_60, a_cv, a_new = (addr(1300 + i) for i in range(4))
    with open(os.path.join(sb, "lists.json"), "w") as f:
        json.dump({"profiles": [a_np, a_60, a_cv, a_new]}, f)
    R2.pool_cache({}, {a_np}, T0 + 1_000)               # DexScreener had no pair at the last cycle, which started 1 s after its grid point
    R2.cache["pool"].update({a_60: [None, False, T0 + 60_000], a_cv: [None, True, T0 + 1_000]})
    R2.clock.wait(T0 + 120_000)
    asks = set(R2.ds_asks(sb, R2.clock.now()))
    keep, LR.NOPAIR_RECHECK_MS = LR.NOPAIR_RECHECK_MS, 120_000
    try:
        old = set(R2.ds_asks(sb, R2.clock.now()))
    finally:
        LR.NOPAIR_RECHECK_MS = keep
    check(asks == {a_np, a_cv, a_new} and old == {a_new},
          "a coin DexScreener answered without a pair (or on its launch curve) is asked again at the next cycle, 119 s later (the old "
          "2-minute rule skipped it); one answered 60 s ago is not")
    a_l = addr(1310)
    R2.clock.wait(T0 + 2 * 120_000)
    first = R2.clock.now()
    R2.docs, R2.rec_hour = {"l": {"coins": {a_l: {"addr": a_l, "first": first, "later": {}, "px": 1.0}}}}, {a_l: "l"}
    for k in range(1, 32):
        R2.clock.wait(T0 + (2 + k) * 120_000)
        R2.later_prices({a_l: {"priceUsd": "1.5", "liquidityUsd": 9000.0}}, {a_l}, R2.clock.now())
    lt = R2.docs["l"]["coins"][a_l]["later"]
    at = {m: round((o["t"] - first) / MIN, 1) for m, o in lt.items()}
    check(at == {"5": 6.0, "15": 16.0, "30": 30.0, "60": 60.0} and not any(o.get("late") or o.get("early") for o in lt.values()),
          "the later prices at 2-minute cycles: 5 and 15 at the first cycle after them, 30 and 60 on time, none marked late (%s)" % at)

    a_r = addr(1320)
    row = {"a": a_r, "pr": {"pairCreatedAt": T0, "symbol": "RT", "name": "Rt", "dexId": "pumpswap", "pairAddress": "RtPool", "chgM5": 5.0},
           "basic": {"price": 2e-5, "liq": 20_000.0, "mc": 50_000.0}, "f": {}, "age": 1.0}
    for k in range(LR.RT_MAX + 2):
        R2.rate(row, T0 + k * 120_000)
    rt = R2.rec(a_r)["rt"]
    check(len(rt) == LR.RT_MAX == 12 and all(len(e) == 6 and e[4] == 2e-5 and isinstance(e[5], int) for e in rt),
          "rt keeps %d ratings, each [t, verdict, points, push, price, upside] (%s)" % (len(rt), rt[-1]))

    mrec = lambda: {"addr": "M", "sym": "M", "first": T0, "px": 1.0, "liq": 20_000.0}
    mrow = lambda px=1.6, liq=21_000.0, m5=5.0, age=3.0: {"basic": {"price": px, "liq": liq, "mc": 80_000.0}, "pr": {"chgM5": m5}, "age": age}

    def mom(now, r, record_only=False, rec=None):
        rec = rec or mrec()
        R2.momentum(rec, r, now, "watch", record_only)
        return rec.get("mom")
    once = mrec()
    m0 = mom(T0, mrow(px=1.0, liq=20_000.0, m5=60.0), rec=once)
    m1 = mom(T0 + 2 * MIN, mrow(px=2.0), rec=once)
    got = {"1.6x": mom(T0 + 2 * MIN, mrow()), "1.4x": mom(T0 + 2 * MIN, mrow(px=1.4)), "7 min": mom(T0 + 7 * MIN, mrow()),
           "less liquidity": mom(T0 + 2 * MIN, mrow(liq=19_000.0)), "record only": mom(T0 + 2 * MIN, mrow(), True), "pool 10 min": mom(T0 + 2 * MIN, mrow(age=10.0)),
           "under YOUNG_MIN_LIQ": mom(T0 + 2 * MIN, mrow(liq=4_000.0), rec=dict(mrec(), liq=3_000.0)), "m5 49": mom(T0, mrow(px=1.0, liq=20_000.0, m5=49.0))}
    check((got["1.6x"] or {}).get("by") == "x" and got["1.6x"]["x"] == 1.6 and got["1.6x"]["t"] == T0 + 2 * MIN and not any(v for k, v in got.items() if k != "1.6x")
          and (m0 or {}).get("by") == "m5" and m1 is m0 and once["mom"]["t"] == T0,
          "momentum on paper: 1.6x within 6 minutes with liquidity not lower (by x); +60%% in 5 minutes at first sight (by m5, once); none at "
          "1.4x, after 6 minutes, with less liquidity, on a record-only rating, at 10 minutes or under YOUNG_MIN_LIQ (%s)" % sorted(k for k, v in got.items() if v))

    # two loop runs of 5 cycles on the same coins, momentum patched out in the second: the lists, verdicts and pushes stay the same
    TF = T0 + 10 * H
    coins = [fixture(n, 1330 + i, pool=TF - MIN, mint=TF - 5 * MIN, **kw)
             for i, (n, kw) in enumerate((("RISER", {"rc": "404", "paid": False}), ("PUMPER", {"m5": 60.0}), ("DRAIN", {}), ("LATE", {}), ("STEADY", {})))]
    moves = {"RISER": (1, 1.6, 1.3), "DRAIN": (1, 1.6, 0.7), "LATE": (4, 1.6, 1.3)}     # from that cycle on: price and liquidity times
    by = {c["name"]: c["a"] for c in coins}
    mf = RadarMock(coins)
    srvf = serve(mf)
    seen = {False: [], True: []}

    def drive(off):
        def patch_(R_):
            real, ob = R_.cycle, R_.build_doc
            if off:
                R_.momentum = lambda *a_: None

            def cyc(k, t, last):
                for c in coins:
                    k0, fx, lx = moves.get(c["name"], (99, 1.0, 1.0))
                    c["px"], c["liq"] = (6e-5 * fx, 22_000.0 * lx) if k >= k0 else (6e-5, 22_000.0)
                return real(k, t, last)

            def bd(*a_, **k_):
                d_ = ob(*a_, **k_)
                seen[off].append([[(x["addr"], x["v"], x["pts"]) for x in d_[part]] for part in ("coins", "others")])
                return d_
            R_.cycle, R_.build_doc = cyc, bd
        return patch_
    try:
        runs = {}
        for off in (False, True):
            rem_ = fresh_remote(T, tmp, "remote-mom-%d" % off, TF)
            sink_ = Sink()
            c_, _, _, _ = run_radar(T, P, "http://127.0.0.1:%d" % srvf.server_address[1], rem_, os.path.join(tmp, "rdMom%d" % off), TF, minutes=10,
                                    notifier=sink_, clock=LR.FakeClock(TF, step=120_000), patch=drive(off))
            runs[off] = (c_, hour_recs(rem_), radar_json(rem_), json.loads(branch_files(rem_, "radar-data").get("pushed.json") or b"{}"), sink_.got)
    finally:
        srvf.shutdown()
        srvf.server_close()
    (c_on, rec_on, doc_on, pj_on, got_on), (c_off, rec_off, doc_off, pj_off, got_off) = runs[False], runs[True]
    mo = {n: (rec_on.get(a) or {}).get("mom") for n, a in by.items()}
    ri, pu = rec_on.get(by["RISER"]) or {}, rec_on.get(by["PUMPER"]) or {}
    check(c_on == 0 and len(ri.get("rt") or []) == 5 and (mo["RISER"] or {}).get("by") == "x" and mo["RISER"]["t"] == ri["rt"][1][0] and mo["RISER"]["v"] == "watch"
          and not ri.get("good")
          and (mo["PUMPER"] or {}).get("by") == "m5" and mo["PUMPER"]["t"] == pu.get("first") and not (mo["DRAIN"] or mo["LATE"] or mo["STEADY"])
          and abs(ri["rt"][1][4] / ri["rt"][0][4] - 1.6) < 1e-6 and (doc_on.get("record") or {}).get("mom") == {"calls": 2, "n60": 0, "rug": None, "win": None},
          "a loop at 2 minutes: RISER (watch: no RugCheck report) at 1.6x at its 2nd rating with more liquidity has momentum by x and stays "
          "watch, PUMPER +60%% at first sight by m5 "
          "(once), none for DRAIN (liquidity down), LATE (up 8 minutes after first sight) or STEADY; radar.json's record.mom %s"
          % (doc_on.get("record") or {}).get("mom"))
    l5 = {n: (rec_on.get(a) or {}).get("later", {}).get("5") or {} for n, a in by.items()}
    check(all(round((o.get("t", 0) - (rec_on.get(by[n]) or {}).get("first", 0)) / MIN, 1) == 6.0 and not o.get("late") for n, o in l5.items()),
          "the loop takes every coin's 5-minute price at its 3rd cycle (6 minutes), not marked late")
    vs = lambda recs: {a: ([e[1:] for e in r["rt"]], bool(r.get("good")), bool(r.get("push")), r.get("top")) for a, r in recs.items()}
    check(c_off == 0 and seen[False] and seen[False] == seen[True] and vs(rec_on) == vs(rec_off) and set(pj_on) == set(pj_off)
          and [g["coins"] for g in got_on] == [g["coins"] for g in got_off] and not any(r.get("mom") for r in rec_off.values()),
          "with momentum patched out every cycle's list and fold, every rating, good and pushed mark, pushed.json and the notifications are the same (%d lists, "
          "%d pushed): momentum changes nothing but the record" % (len(seen[False]), len(pj_on)))
    strip = lambda b: {a: {k: v for k, v in x.items() if k != "_rec"} for a, x in b.items()}
    b6 = strip(RP.buys_of(list(rec_on.values())))
    b4 = strip(RP.buys_of([dict(r, rt=[e[:4] for e in r["rt"]]) for r in rec_on.values()]))
    check(b6 and b6 == b4, "radar_paper buys the same %d coins from 6-field ratings as from their first 4 fields" % len(b6))

    def rec_(n, mom_=None, l60=None, **kw):
        r = {"addr": addr(1340 + n), "sym": "S%d" % n, "dex": "pumpswap", "first": T0 - 2 * H, "px": 1.0, "liq": 20_000.0, "mc": 50_000.0,
             "rt": [[T0 - 2 * H, "watch", 2.0, 0, 1.0, 0]], "later": {}}
        if mom_:
            r["mom"] = dict({"t": T0 - 2 * H + 2 * MIN, "liq": 20_000.0, "mc": 50_000.0, "by": "x"}, **mom_)
        if l60:
            r["later"]["60"] = dict({"t": T0 - H}, **l60)
        return dict(r, **kw)
    planted = [rec_(1, {"px": 2.0}, {"px": 0.15, "liq": 3_000.0}),            # 0.075x of the momentum price: rugged; 0.15x of the first: neither
               rec_(2, {"px": 1.0}, {"px": 2.0, "liq": 30_000.0}),            # 2x with liquidity grown like a pool's: doubled
               rec_(3, {"px": 1.5}),                                          # no 1 h price yet: a call, not in n60
               rec_(4, None, {"gone": True}),
               rec_(5, None, {"px": 1.0, "liq": 20_000.0}, peak60={"x": 3.0}, out={"rug1h": False, "win1h": True}),  # peak60 left out: neither
               rec_(6, None, {"gone": True}, first=T0 - 20 * 24 * H, rt=[[T0 - 20 * 24 * H, "watch", 2.0, 0]])]      # 4-field ratings (before the 2-minute radar): not in all
    R2.docs, R2.rec_hour, R2.res_summary = {"p": {"coins": {r["addr"]: r for r in planted}}}, {r["addr"]: "p" for r in planted}, []
    line, _, _ = R2.summary(T0)
    R2.docs, R2.res_summary = {}, [LR.summ(r, T) for r in planted]
    line2, _, _ = R2.summary(T0)
    off_ = LR.finish_from({"record": line}, "off", T0, "switched off", "t", None, None, "manual", (0, 24))
    check(line["mom"] == {"calls": 3, "n60": 2, "rug": 0.5, "win": 0.5} and line["all"] == {"n60": 4, "rug": 0.25, "win": 0.25} and line2 == line
          and {k for k in line if k not in ("mom", "all")} == {"calls", "n60", "rug", "win", "eur", "ci", "known"} and line["calls"] == 0 and line["win"] is None
          and line["known"] == {"n": 0, "rug": 0, "win": 0}
          and LR.summ(planted[0])["mom"] is None and LR.summ(planted[0])["all"] is None and off_["record"]["mom"] == line["mom"] and off_["record"]["all"] == line["all"]
          and LR.summ(planted[5], T)["all"] is None and LR.summ(planted[3], T)["all"] == {"rug": True, "win": False},
          "the record line's mom %s and all %s: the 60-minute price alone (from the momentum price for mom; peak60 left out of both), a "
          "momentum call without a 1 h price counted in calls only, the same from results' records; kept in an off or hours doc; a rugged "
          "record of 20 days ago with 4-field ratings (before momentum was measured) is left out of all" % (line["mom"], line["all"]))


# the WP0 probe's hand-off (research/probe-radar.md, ADAPTERS block and its two constants), as the probe wrote it
PROBE_ADAPTERS = {
    "pf_graduated": True, "pf_new": True, "gt_new_pools": True, "jup_recent": True, "ds_profiles": True,
    "ll_new": False, "rc_new_tokens": False,
    "rc_report": True, "rc_insider_networks": True, "rc_creator_tokens": False, "pf_coin_v3": True, "ds_orders": True,
    "pf_dev_history": True, "pf_top_holders": True, "pf_holder_flags": False, "pf_wallet_overview": False, "pf_advanced_coin": False,
    "swap_trades": True, "swap_candles": True,
    "rpc_dev_age": True, "rpc_holder_age": True, "rpc_funding": True, "rpc_mint_time": True,
    "gt_m1_backfill": True, "gh_contents_poll": True, "raw_fallback": True, "supabase": True,
}
PROBE_RPC_GAP_S = 1.1
PROBE_GT_429_LADDER_S = (15, 30, 60)


def probe_checks(check, LR, T, P, url, mock, heads, recs, by, tmp):
    """R11: what the WP0 probe found on GitHub's runners, applied: the adapter defaults, the routes pump.fun took away, the mint time
    from Jupiter and coins-v3, the dev history from coins?creator=, the launch trades and top holders, swap-api's candles, the RPC's
    1.1 s per method and its 429, GeckoTerminal's 429 ladder and new-pools page 2. heads: run A's requests; recs: its records."""
    import radar_src as RS
    print("== launch radar R11: the WP0 probe's findings")
    radar_only = {"ds_tokens", "dev_check", "gt_candles", "x_tweet", "pf_curve"}        # pf_curve: the curve watch's list (selftest_curve)
    differ = sorted(k for k, v in PROBE_ADAPTERS.items() if not ((k in RS.ADAPTERS and RS.ADAPTERS[k] is v) or (k in RS.NOT_HERE and k not in RS.ADAPTERS)))
    extra = sorted(set(RS.ADAPTERS) - set(PROBE_ADAPTERS) - radar_only)
    check(not differ and not extra and RS.RPC_GAP_S == PROBE_RPC_GAP_S and tuple(RS.GT_429_LADDER_S) == PROBE_GT_429_LADDER_S
          and RS.PAGES == {"pf_graduated": 4, "pf_new": 2, "gt_new_pools": 2} and LR.RPC_CAP == 15 and LR.FUND_CAP == 5
          and LR.DS_FIRST_REQ == 20 and LR.DS_MAX_REQ == 12 and all(isinstance(RS.NOT_HERE[k], str) and RS.NOT_HERE[k] for k in RS.NOT_HERE),
          "the adapter defaults are the probe's (%d switches, %d of its entries not this package's: %s); RPC 1.1 s per method, GeckoTerminal 429 "
          "ladder 15/30/60 s, pages 4/2/2, RPC 15 and funding 5 a cycle, DexScreener 20 requests in the first cycle, 12 later%s"
          % (len(RS.ADAPTERS), len(RS.NOT_HERE), ", ".join(sorted(RS.NOT_HERE)), ("; differ %s, extra %s" % (differ, extra)) if differ or extra else ""))

    gone = [h for h in heads if re.match(r"^/frontend-api-v3\.pump\.fun/coins/(user-created-coins/|[1-9A-HJ-NP-Za-km-z]{32,48}$)", h["path"])]
    v3 = [h for h in heads if h["path"].startswith("/frontend-api-v3.pump.fun/coins-v3/")]
    rpc_mint = lambda a: [h for h in heads if h["rpc"] == "getSignaturesForAddress" and h["p0"] == a]
    rj, rv = recs[by["JUPMINT"]], recs[by["V3ONLY"]]
    check(not gone and [h["path"].rsplit("/", 1)[1] for h in v3] == [by["V3ONLY"]] and rv["sig"].get("mintToPoolS") == 240 and rv["chk"]["mint"] == "ok"
          and rj["sig"].get("mintToPoolS") == 20 and rj["sig"].get("instantPool") is True and "jup:recent" in (rj.get("found") or []) and not rpc_mint(by["JUPMINT"])
          and len(rpc_mint(by["NOMINT"])) == 3 and recs[by["NOMINT"]]["chk"]["mint"] == "unknown",
          "mint time: pump.fun's list row, then Jupiter's createdAt (JUPMINT: pool %s s after the mint, an instant pool, no RPC call), then coins-v3 "
          "(asked once, only for V3ONLY, which no list carried); the gone routes coins/{mint} and coins/user-created-coins never asked; the RPC "
          "as the last fallback, 3 pages at most (NOMINT: %d pages, still unknown)" % (rj["sig"].get("mintToPoolS"), len(rpc_mint(by["NOMINT"]))))

    sc, sk = recs[by["CLEAN"]]["sig"], recs[by["CLUSTER"]]["sig"]
    creator = lambda n: FIX[n]["creator"]
    count_calls = lambda n: [h for h in heads if h["path"] == "/frontend-api-v3.pump.fun/coins-v2/user-created-coins/" + creator(n)]
    by_creator = lambda n: [h for h in heads if h["path"] == "/frontend-api-v3.pump.fun/coins" and ("creator=" + creator(n)) in h["q"]]
    check((sc.get("devN"), sc.get("devDead"), sc.get("devGrad")) == (3, 2, 1) and (sk.get("devN"), sk.get("devDead"), sk.get("devGrad")) == (59, 49, 1)
          and len(by_creator("CLEAN")) == 1 and not count_calls("CLEAN") and len(by_creator("CLUSTER")) == 1 and len(count_calls("CLUSTER")) == 1,
          "dev history from coins?creator= (one call a dev, cached): CLEAN's dev 3 launches (2 dead, 1 graduated); CLUSTER's dev 50 rows, so "
          "coins-v2 gave the total: %s earlier launches, %s dead" % (sk.get("devN"), sk.get("devDead")))
    rx = recs[by["XCOPY"]]
    trades = lambda n: [h for h in heads if h["path"] == "/swap-api.pump.fun/v2/coins/%s/trades" % by[n]]
    holders = [h for h in heads if "/coins/top-holders/" in h["path"]]
    web = [h for h in heads if h["path"].startswith("/swap-api.pump.fun/") or "/coins/top-holders/" in h["path"] or "/coins-v2/" in h["path"]]
    check((sc.get("snip30"), sc.get("snip30N"), sc.get("slotN"), sc.get("slotPct")) == (0.045, 3, 2, 0.035) and len(trades("CLEAN")) == 1
          and (rx["sig"].get("snip30"), rx["sig"].get("snip30N"), rx["sig"].get("slotN")) == (0.059, 2, 1) and len(trades("XCOPY")) == 3
          and rx["chk"]["trades"] == "ok" and holders and all(h["path"].startswith("/frontend-api-v3.") for h in holders)
          and web and all(h["origin"] == "https://pump.fun" for h in web),
          "launch trades (swap-api, 100 a page): CLEAN's launch on page 1, 4.5% bought in 30 s by 3 wallets, 2 in the mint's slot; XCOPY's 3 "
          "pages never reach the launch, so the top holders' entry times give it (5.9% by 2 wallets; isSniper / isDev set on every holder "
          "and never read; 1 bundler flagged); pump.fun's web origin sent")
    ohlcv = [h for h in heads if "/ohlcv/minute" in h["path"]]
    swapc = lambda n: [h for h in heads if h["path"] == "/swap-api.pump.fun/v1/coins/%s/candles" % by[n]]
    st = sc.get("stairCurve") or {}
    check(sc.get("closes") and len(sc["closes"]) <= 15 and st.get("n") == 4 and swapc("CLEAN") and len(swapc("CLEAN")) <= 3
          and not any(by["CLEAN"][:20] in h["path"] for h in ohlcv) and any(by["NOMINT"][:20] in h["path"] for h in ohlcv),
          "staircase so far of a pump.fun coin from swap-api's candles (CLEAN: %d closes from the pool's minute, the curve's 4 minutes before "
          "it measured apart, %d calls, none to GeckoTerminal); a pool off pump.fun (NOMINT) from GeckoTerminal" % (len(sc.get("closes") or []), len(swapc("CLEAN"))))
    fund_tx = [h for h in heads if h["rpc"] == "getTransaction" and (h["p0"] or "").startswith(("f_", "w_"))]
    check(sk.get("freshN") == 5 and sk.get("freshOf") == 5 and sk.get("fundN") == 5 and sk.get("fundMin") == 4.0 and fund_tx
          and all(h["p0"].startswith("f_") for h in fund_tx) and len(fund_tx) == 5,
          "fresh holders (one RPC call each): CLUSTER's top 5 are 2 hours old, all funded by one wallet within %s min; getTransaction only for "
          "fresh holders (%d calls, none for the old wallets)" % (sk.get("fundMin"), len(fund_tx)))

    # the request rules, against the mock directly (real time)
    h = RS.RadarHttp(url, 0.0, log=lambda s_: None)
    h.pace_mock = True
    h.new_cycle(time.time() + 8.0, 15)
    mark = len(mock.heads)
    sig = lambda w: {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [w, {"limit": 1000}]}
    for i in range(3):
        h.post(F_RPC(), sig(addr(900 + i, "")))
        if i == 0:
            h.post(F_RPC(), {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": ["w_x_1", {}]})
    got = [x for x in mock.heads[mark:] if x["rpc"]]
    ts = [x["t"] for x in got if x["rpc"] == "getSignaturesForAddress"]
    tx = [x["t"] for x in got if x["rpc"] == "getTransaction"]
    h.new_cycle(time.time() + 1.5, 15)
    mark2 = len(mock.heads)
    h.post(F_RPC(), sig(addr(910, "")))
    skipped = h.code == "skip" and len(mock.heads) == mark2
    gaps = [b_ - a_ for a_, b_ in zip(ts, ts[1:])]
    check(len(ts) == 3 and min(gaps) >= RS.RPC_GAP_S - 0.02 and tx and tx[0] - ts[0] < 1.0 and skipped,
          "RPC: %s s between two calls of one method (10 per method per 10 s), another method not held up (%.2f s), no call that would wait past "
          "the step's end" % ("/".join("%.2f" % g for g in gaps), (tx[0] - ts[0]) if tx else -1))
    h = RS.RadarHttp(url, 0.0, log=lambda s_: None)
    h.new_cycle(time.time() + 30.0, 15)
    mock.rpc429 = 1
    r1 = h.post(F_RPC(), sig(addr(920, "")))
    rpc = RS.RPC_HOST
    cool_rpc = h.cool.get(rpc, 0) - time.time()
    mark3 = len(mock.heads)
    h.cool[rpc] = 0.0
    r2 = h.post(F_RPC(), sig(addr(921, "")))
    skip_rest = r2 is None and h.code == "skip" and len(mock.heads) == mark3
    h.new_cycle(time.time() + 30.0, 15)
    r3 = h.post(F_RPC(), sig(addr(922, "")))
    check(r1 is None and 9.0 <= cool_rpc <= 10.5 and skip_rest and isinstance(r3, dict) and h.level.get(rpc) == 0,
          "RPC 429: skipped for the rest of the cycle (retry-after %.0f s), asked again the next cycle" % cool_rpc)
    gt = RS.GT_HOST
    gt_url = "https://api.geckoterminal.com/api/v2/networks/solana/pools/%spool/ohlcv/minute?aggregate=1&limit=5&before_timestamp=%d" % (by["NOMINT"][:20], T0 // 1000)
    h = RS.RadarHttp(url, 0.0, log=lambda s_: None)
    h.new_cycle(time.time() + 30.0, 15)
    mock.gt429 = 4
    cools, cut = [], None
    for i in range(4):
        h.cool[gt] = 0.0
        h.get(gt_url)
        cools.append(round(h.cool.get(gt, 0) - time.time()))
        if i == 0:
            first = (h.blocked(gt), gt in h.hit429, h.state(gt))
        cut = gt in h.hit429
    mock.gt429 = 0
    h.new_cycle(time.time() + 30.0, 15)
    h.cool[gt] = 0.0
    ok = h.get(gt_url)
    check(cools == [15, 30, 60, 60] and first == (True, False, "limited") and cut and isinstance(ok, dict) and h.level.get(gt) == 0,
          "GeckoTerminal 429: cools %s s, asked again later in the same cycle (blocked, not skipped for the cycle) until the ladder ends; a good "
          "answer resets it" % "/".join(str(c) for c in cools))
    sb = os.path.join(tmp, "probe-sb")
    for old, want in ((False, True), (True, False)):
        mock.gt_page2_old = old
        mark = len(mock.heads)
        src = RS.Sources(RS.RadarHttp(url, 0.0, log=lambda s_: None), lambda s_: None, dict(RS.ADAPTERS))
        src.http.new_cycle(time.time() + 30.0, 15)
        src.gt_new(sb, T0)
        pages = [x["q"] for x in mock.heads[mark:] if "/new_pools" in x["path"]]
        if old:
            p_old = pages
        else:
            p_new = pages
    mock.gt_page2_old = False
    check(len(p_new) == 2 and "page=2" in p_new[1] and len(p_old) == 1,
          "GeckoTerminal new pools: page 2 only while page 1's oldest pool is under 10 minutes old (%d pages, then %d)" % (len(p_new), len(p_old)))
    src = RS.Sources(RS.RadarHttp(url, 0.0, log=lambda s_: None), lambda s_: None, dict(RS.ADAPTERS))
    src.http.new_cycle(time.time() + 30.0, 15)
    xc = FIX["XCOPY"]
    mock.th429.add(xc["a"])
    mark = len(mock.heads)
    ho = src.pf_holders(xc["a"], xc["mint"], skip={xc["a"][:20] + "pool"})
    hosts = [x["path"].split(".pump.fun")[0].lstrip("/") for x in mock.heads[mark:]]
    mock.th429.discard(xc["a"])
    src = RS.Sources(RS.RadarHttp(url, 0.0, log=lambda s_: None), lambda s_: None, dict(RS.ADAPTERS))
    src.http.new_cycle(time.time() + 30.0, 15)
    mark = len(mock.heads)
    none = src.pf_holders(addr(930), T0, skip=set())
    hosts404 = [x["path"].split(".pump.fun")[0].lstrip("/") for x in mock.heads[mark:]]
    mock.dev_ignore = True
    dv = src.pf_dev(xc["creator"], T0)
    mock.dev_ignore = False
    check(isinstance(ho, dict) and ho.get("snip30N") == 2 and ho.get("n") == 5 and hosts == ["frontend-api-v3", "advanced-api-v2"] and none is None
          and hosts404 == ["frontend-api-v3"] and dv is None and src.on.get("pf_dev_history") is False,
          "top holders: a 429 on frontend-api-v3 asks advanced-api-v2 (the pool not counted as a holder), a coin pump.fun does not know is not "
          "asked again there; an ignored creator filter turns the dev history off for the run, never read as no launches")


def talk_checks(check, LR, T, P, tmp, pushes, clean):
    """R14: the notification says why and the record (app.radar_words: the first passed checks by name, the record of earlier green coins
    once 20 have a 1 h outcome, the fake-money words at the end, inside the push's limits; the radar hands its cycle's record over); the
    replies on pump.fun and the likes of a coin's source tweet are measured at first sight with weight 0: at most TWEET_CAP lookups a
    cycle, coins at first sight first, none when the step is short of time, a failed one unknown, an id X cannot be asked about or an
    answer that is not a tweet settled unknown without taking a slot or switching the adapter off; sig0 keeps the first sight's reading
    and is never filled in later. pushes: run A's notifications; clean: CLEAN's record from run A."""
    import app as A
    import radar_src as RS
    print("== launch radar R14: the push says why and the record; pump.fun replies and the source tweet's likes measured at first sight")
    no_words = re.compile(r"\b(buy|buys|buying|safe|safety|clean|guaranteed)\b", re.I)
    line = [["warn", "no socials"], ["ok", "curve 4 min before pool"], ["ok", "no rugger wallets"], ["ok", "RugCheck report"], ["info", "4 replies on pump.fun"]]
    c = {"addr": "W" * 44, "sym": "WHY", "age": 6.4, "liq": 23_400, "n": 9, "line": line}
    rec_ok = {"calls": 31, "n60": 26, "rug": 0.231, "win": 0.115, "known": {"n": 26, "rug": 6, "win": 3}}
    t1, b1 = LR.push_text([c], rec_ok)
    t0, b0 = LR.push_text([c], dict(rec_ok, known={"n": 19, "rug": 6, "win": 3}))
    odd = [{"known": {"n": "26", "rug": 6, "win": 3}}, {"known": {"n": 26, "rug": -1, "win": 3}}, {"known": {"n": 26, "rug": 6, "win": 30}},
           {"known": {"n": 26.5, "rug": 6, "win": 3}}, {"known": {"n": float("inf"), "rug": 6, "win": 3}}, {"known": {"n": True, "rug": 6, "win": 3}},
           {"known": {"n": 26, "rug": None, "win": 3}}, {"known": [26, 6, 3]}, {"calls": 40, "n60": 40, "rug": 0.2, "win": 0.1}, {}, None, "26"]
    want = ("9 checks passed (curve 4 min before pool, no rugger wallets) · liquidity $23k · greens so far: 3 of 26 doubled in 1 h, 6 rugged · "
            "fake money, nothing is bought.")
    check(t1 == "WHY: no trap found (pool 6 min)" and b1 == want and b0 == want.replace("greens so far: 3 of 26 doubled in 1 h, 6 rugged · ", "")
          and all(LR.push_text([c], r)[1] == b0 for r in odd) and (t1, b1) == A.radar_words([c], rec_ok) and A.radar_words([], rec_ok) is None,
          "the push says why (the first 2 passed checks of its line) and the record: %r; under 20 green calls with a 1 h outcome, or counts "
          "that are not whole numbers that fit (%d odd records), no record line: never a guess" % (b1, len(odd)))
    longs = [["ok", "curve " + "9" * 80 + " min before pool"], ["ok", "x\u202e\x07\n" + "y" * 70], ["ok", "looks safe to buy"], ["ok", "RugCheck report"]]
    cl = dict(c, sym="S\u202eY<b>M\x07" * 10, line=longs, liq=float("inf"), n=None, age=float("nan"))
    t2, b2 = LR.push_text([cl, c, c], {"known": {"n": 10.0 ** 290, "rug": 6, "win": 3}})
    t3, b3 = LR.push_text([cl], {"known": {"n": 10 ** 12, "rug": 10 ** 12, "win": 10 ** 12}})
    t4, b4 = LR.push_text([dict(c, line=[["ok", "looks safe"], ["ok", 7], ["bad", "pool opened with the mint"], "ok", ["ok"]])], rec_ok)
    pay = json.loads(A.message(t3, b3, "#tab-radar", tag="radar"))["notification"]
    words = [t1, b1, t2, b2, t3, b3, t4, b4]
    check(all(len(t) <= A.TITLE_MAX for t in words[::2]) and all(len(b) <= A.BODY_MAX and b.endswith("fake money, nothing is bought.") for b in words[1::2])
          and "greens so far" not in b2 and "greens so far: 1000000000000 of 1000000000000" in b3 and pay["body"] == b3 and pay["title"] == t3
          and not any(no_words.search(w) or re.search(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069\u2014]", w) for w in words)
          and t2 == ("SY<b>M" * 3)[:16] + ": no trap found +2 more" and b4 == "9 checks passed · liquidity $23k · " + want.split(" · ", 2)[2]
          and "All checks passed (curve %s, x %s) · liquidity unknown · " % ("9" * 34, "y" * 38) in b2,
          "inside the push's limits (title %d, body %d characters): a record line too long is left out, each named check cut at 40 "
          "characters, control and bidi characters dropped, a check whose words say safe or buy never named; message() keeps the body "
          "whole (%d bytes); every body ends 'fake money, nothing is bought.'" % (A.TITLE_MAX, A.BODY_MAX, len(A.message(t3, b3, "#tab-radar", tag="radar"))))
    # characters a phone could read as text direction or hide inside a word: the Arabic letter mark (a strong right-to-left character),
    # C1 controls, the BOM, zero-width and soft hyphens, which would also split 'buy' or 'safe' past the advice-word filter; and a
    # liquidity or a check count of absurd length is cut before the fake-money words, never them
    t5, b5 = A.radar_words([dict(c, sym="\u061cABC\ufeff\u200bD\x9b", line=[["ok", "b\u200buy now"], ["ok", "s\xadafe"], ["ok", "x\x80\x9b\x9fy\u2060"]])], None)
    huge = [A.radar_words([dict(c, line=[], **kw)], rec_ok)[1] for kw in ({"liq": 1e300}, {"n": 1e300}, {"liq": 1e300, "n": 1e300})]
    pay5 = [json.loads(A.message("t", b_, "#tab-radar", tag="radar"))["notification"]["body"] for b_ in huge]
    check(t5 == "ABCD: no trap found (pool 6 min)" and b5 == "9 checks passed (xy) · liquidity $23k · fake money, nothing is bought."
          and A._sym("\u200b \u00ad") == "?" and all(len(b_) <= A.BODY_MAX and b_.endswith(" · fake money, nothing is bought.") for b_ in huge + pay5),
          "push words: U+061C, C1 controls, the BOM and zero-width characters are dropped from the symbol and the named checks, a check "
          "that says buy or safe behind a zero-width space or a soft hyphen is never named (%r); a liquidity or a check count of 1e300 "
          "is cut before 'fake money, nothing is bought.', which message() keeps (%d, %d, %d characters)" % (((t5, b5),) + tuple(len(b_) for b_ in pay5)))
    p0 = (pushes or [{}])[0]
    check(p0.get("known") == {"n": 0, "rug": 0, "win": 0} and "(curve 4 min before pool, no rugger wallets)" in str(p0.get("body"))
          and "greens so far" not in str(p0.get("body")),
          "run A: the radar hands its cycle's record to the notification (known %s: no green call with a 1 h outcome yet, so no record "
          "line) and CLEAN's push names its first passed checks: %r" % (p0.get("known"), p0.get("body")))
    s0 = clean.get("sig0") or {}
    check(s0.get("replies") == 4.0 and s0.get("tweetLikes") is None and (clean.get("sig") or {}).get("replies") == 4.0,
          "run A: CLEAN's first-sight signals carry pump.fun's reply count (4, the list's reply_count) and no tweet likes (its X link is an account)")

    # ---- the tweet lookups on one Radar: the cap, first sight first, a shared tweet, the step's time, failures
    m = RadarMock([])
    srv = serve(m)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        Ru = unit_radar(T, P, tmp, "rdTw", extra=["--mock", url])
        ids = ["18000000000000%05d" % i for i in range(8)]
        m.tweet_likes.update({ids[0]: 12_000, ids[1]: 50, ids[2]: 3_000, ids[3]: "tomb", ids[5]: 429, ids[6]: 70})
        link = lambda i, h="someone": "https://x.com/%s/status/%s" % (h, ids[i])
        link_to = lambda t: "https://x.com/someone/status/" + t
        row = lambda seed, u, age: {"a": addr(seed), "pr": {"xUrl": u}, "age": age}
        tw_heads = lambda: [h for h in m.heads if h["path"] == "/cdn.syndication.twimg.com/tweet-result"]
        a1, a2, a3, a4, a5, a6 = (row(1500 + i, u, age) for i, (u, age) in enumerate(((link(0), 3.0), (link(1), 4.0), (link(2), 5.0), (link(0, "other"), 6.0),
                                                                                         (link(2), 1.0), ("https://x.com/someone", 0.5))))
        Ru.docs["2026-10-13T11"] = {"coins": {a5["a"]: {"addr": a5["a"]}}}
        Ru.rec_hour[a5["a"]] = "2026-10-13T11"          # a5 was seen before: the coins at first sight are asked first
        live = [a5, a6, a3, a1, a4, a2]
        likes = lambda rs: [(Ru.work.get(r["a"]) or {}).get("likes") for r in rs]
        Ru.http.new_cycle(time.time() + 30)
        n1 = Ru.tweet_likes(live, T0)
        got1, h1 = likes([a1, a2, a3, a4, a5, a6]), len(tw_heads())
        Ru.http.new_cycle(time.time() + 30)
        n2 = Ru.tweet_likes(live, T0 + 2 * MIN)
        got2, h2 = likes([a1, a2, a3, a4, a5, a6]), len(tw_heads())
        tok = all(dict(urllib.parse.parse_qsl(h["q"])).get("token") == __import__("fetch").tweet_token(dict(urllib.parse.parse_qsl(h["q"])).get("id")) for h in tw_heads())
        check(n1 == 2 and h1 == 2 and got1 == [12_000, 50, None, 12_000, None, None] and n2 == 1 and h2 == 3 and got2 == [12_000, 50, 3_000, 12_000, 3_000, None]
              and tok and Ru.tweets["x.com/i/status/" + ids[0]][0] == 12_000,
              "at most %d tweet lookups a cycle (fetch.viral's endpoint and token), coins at first sight first: two coins read, one coin off the "
              "same tweet takes that reading, the third tweet and the coin seen before wait for the next cycle, which reads it once for both; "
              "an account link is never looked up (%s, then %s)" % (LR.TWEET_CAP, got1, got2))
        b = [row(1600 + i, link(i + 3), 2.0 + i) for i in range(4)]      # a deleted tweet, a 404, a 429, then one that would answer
        Ru.http.new_cycle(time.time() + LR.TWEET_LEFT_S - 1.0)
        n_short, h_short = Ru.tweet_likes(b, T0 + 4 * MIN), len(tw_heads())
        Ru.http.new_cycle(time.time() + 30)
        n_fail, h_fail = Ru.tweet_likes(b[:2], T0 + 4 * MIN), len(tw_heads())
        n_again = Ru.tweet_likes(b[:2], T0 + 6 * MIN)
        Ru.http.new_cycle(time.time() + 30)
        n_429 = Ru.tweet_likes(b[2:], T0 + 4 * MIN)
        h_429 = len(tw_heads())
        Ru.src.on["x_tweet"] = False
        Ru.http.new_cycle(time.time() + 30)
        n_off = Ru.tweet_likes([row(1700, link(7), 2.0)], T0 + 4 * MIN)
        check(n_short == 0 and h_short == h2 and n_fail == 2 and h_fail == h2 + 2 and likes(b[:2]) == [None, None] and n_again == 0
              and all("likes" in Ru.work[r["a"]] for r in b[:2]) and n_429 == 1 and h_429 == h_fail + 1 and likes(b[2:]) == [None, None]
              and not any("likes" in (Ru.work.get(r["a"]) or {}) for r in b[2:]) and Ru.http.blocked(RS.XTW_HOST) and n_off == 0 and len(tw_heads()) == h_429
              and RS.GAPS.get(RS.XTW_HOST) == 1.5 and RS.HOST_LABEL.get(RS.XTW_HOST) == "x tweets" and RS.ADAPTER_HOST["x_tweet"] == (RS.XTW_HOST,),
              "a step with under %g s left asks X nothing (the cycle is never held up); a deleted tweet or a 404 leaves the likes unknown for "
              "good (not asked again); a 429 stops the lookups for the cycle (both coins wait, unknown, asked again later); switched off "
              "(MEMEBOT_RADAR_ADAPTERS x_tweet=0) nothing is asked; "
              "the host keeps fetch's 1.5 s gap and is named 'x tweets'" % LR.TWEET_LEFT_S)

        # odd links and odd answers on a new run (x_tweet's first answer of the run decides its shape): an id X cannot be asked about
        # (a leading zero, over 25 digits, another script's digits, which urllib cannot put in a URL) is settled unknown with no request
        # and no slot; a 200 that is not a tweet (protected, {}) is that tweet's answer: unknown for good, the adapter stays on
        Ro = unit_radar(T, P, tmp, "rdTwOdd", extra=["--mock", url])
        oid = ["18000000000002%05d" % i for i in range(4)]
        m.tweet_likes.update({"20": 4_321, oid[0]: "unavail", oid[1]: "empty", oid[2]: 5_000})
        odd = [row(1800 + i, "https://x.com/someone/status/" + t, 0.5 + 0.1 * i) for i, t in enumerate(("0123", "9" * 30, "\u0661" * 19))]
        c_un, c_jack = row(1810, link_to(oid[0]), 1.0), row(1811, "https://x.com/jack/status/20", 2.0)
        c_empty, c_ok = row(1812, link_to(oid[1]), 0.3), row(1813, link_to(oid[2]), 3.0)
        h0 = len(tw_heads())
        Ro.http.new_cycle(time.time() + 30)
        n_a = Ro.tweet_likes(odd + [c_un, c_jack], T0)
        asked_a = [dict(urllib.parse.parse_qsl(h["q"])).get("id") for h in tw_heads()[h0:]]
        Ro.http.new_cycle(time.time() + 30)
        n_b = Ro.tweet_likes(odd + [c_un, c_jack, c_empty, c_ok], T0 + 2 * MIN)
        asked_b = [dict(urllib.parse.parse_qsl(h["q"])).get("id") for h in tw_heads()[h0 + len(asked_a):]]
        lk = [(Ro.work.get(r["a"]) or {}).get("likes") for r in odd + [c_un, c_jack, c_empty, c_ok]]
        check(n_a == 2 and asked_a == [oid[0], "20"] and n_b == 2 and asked_b == [oid[1], oid[2]] and lk == [None, None, None, None, 4_321, None, 5_000]
              and all("likes" in Ro.work[r["a"]] for r in odd + [c_un, c_empty]) and Ro.src.use("x_tweet") and not Ro.src.off_why
              and not Ro.http.blocked(RS.XTW_HOST) and RS.tweet_id("20") == "20" and RS.tweet_id("\u0661" * 19) is None,
              "3 coins whose tweet ids X cannot be asked about (0123, 30 digits, Arabic-Indic digits) are settled unknown with no request and "
              "no slot, so the cycle still reads 2 tweets, the first tweet's id 20 among them; a protected tweet's answer and an empty {} "
              "leave that coin unknown for good and the adapter on (asked %s, then %s; likes %s)" % (asked_a, asked_b, lk))
        Rf = unit_radar(T, P, tmp, "rdTwOff", extra=["--mock", url])
        m.tweet_likes[oid[3]] = "nofav"
        c_nofav, c_after = row(1820, link_to(oid[3]), 0.5), row(1821, link_to(oid[2]), 1.0)
        h1 = len(tw_heads())
        Rf.http.new_cycle(time.time() + 30)
        n_off1 = Rf.tweet_likes([c_nofav, c_after], T0)
        check(n_off1 == 1 and len(tw_heads()) == h1 + 1 and not Rf.src.use("x_tweet") and Rf.src.off_why.get("x_tweet") == "favorite_count"
              and not any("likes" in (Rf.work.get(r["a"]) or {}) for r in (c_nofav, c_after)),
              "a run's first answer that is a tweet without favorite_count (the endpoint changed) switches x_tweet off, and the cycle "
              "asks nothing more: the next coin stays unknown (%d lookup)" % n_off1)
    finally:
        srv.shutdown()
        srv.server_close()

    # ---- a host that sends its answer a byte at a time is cut off at the lookup's end (the socket timeout bounds each wait only), as
    # no answer: the host rests for the cycle; a big answer in many chunks is read whole
    tweet_body = b'{"__typename":"Tweet","id_str":"20","favorite_count":5,"conversation_count":1}'

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            body = tweet_body + (b" " * 300_000 if "fast" in self.server.mode else b"")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if "fast" in self.server.mode:
                    self.wfile.write(body)
                for i in range(len(body) if self.server.mode == "trickle" else 0):
                    self.wfile.write(body[i:i + 1])
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    slow = {}
    for mode in ("trickle", "fast"):
        sv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        sv.mode = mode
        threading.Thread(target=sv.serve_forever, daemon=True).start()
        said = []
        try:
            hs = RS.RadarHttp(mock="http://127.0.0.1:%d" % sv.server_address[1], log=said.append)
            hs.new_cycle(time.time() + 60)
            t_s = time.time()
            got_s = RS.Sources(hs, said.append, on={"x_tweet": True}).tweet("20", until=time.time() + 1.5)
            slow[mode] = (got_s, round(time.time() - t_s, 1), hs.code, hs.blocked(RS.XTW_HOST), said)
        finally:
            sv.shutdown()
            sv.server_close()
    check(slow["trickle"][0] is None and slow["trickle"][1] < 2.5 and slow["trickle"][2] is None and slow["trickle"][3]
          and any("no answer" in l and "step's end" in l for l in slow["trickle"][4])
          and slow["fast"][0] == {"likes": 5, "replies": 1} and slow["fast"][1] < 1.5 and not slow["fast"][3],
          "a tweet lookup whose answer comes a byte every 0.1 s (8 s in all) ends at its 1.5 s budget (%.1f s): no answer, the host rests "
          "for the cycle; an answer of 300 kB comes in whole (%s)" % (slow["trickle"][1], slow["fast"][0]))

    # ---- a radar run: first sight's reading in sig0, never filled in later; weight 0 in the rating
    TW = T0 + 9 * H
    tid = ["18000000000001%05d" % i for i in range(3)]
    fx = [fixture("TWA", 41, x="https://x.com/someone/status/" + tid[0], pool=TW - MIN, mint=TW - 5 * MIN),
          fixture("TWB", 42, x="https://x.com/someone/status/" + tid[1], pool=TW - 2 * MIN, mint=TW - 6 * MIN),
          fixture("TWC", 43, x="https://x.com/someone/status/" + tid[2], pool=TW - 3 * MIN, mint=TW - 7 * MIN),
          fixture("TWD", 44, x="https://x.com/other/status/" + tid[0], pool=TW - 4 * MIN, mint=TW - 8 * MIN)]
    m2 = RadarMock(fx)
    m2.tweet_likes.update({tid[0]: 12_000, tid[1]: 50, tid[2]: 3_000})
    srv2 = serve(m2)
    url2 = "http://127.0.0.1:%d" % srv2.server_address[1]
    rem = fresh_remote(T, tmp, "remote-talk", TW)
    try:
        code, Rw, lw, _ = run_radar(T, P, url2, rem, os.path.join(tmp, "rdTalk"), TW, minutes=5, notifier=Sink(), deadline=20.0)
    finally:
        srv2.shutdown()
        srv2.server_close()
    rr, doc = hour_recs(rem), radar_json(rem)
    r_ = {c_["name"]: rr.get(c_["a"]) or {} for c_ in fx}
    s0 = {k: (v.get("sig0") or {}) for k, v in r_.items()}
    s1 = {k: (v.get("sig") or {}) for k, v in r_.items()}
    heads = [h for h in m2.heads if h["path"] == "/cdn.syndication.twimg.com/tweet-result"]
    cyc = len([l for l in lw if re.match(r"^cycle \d+:", l)])
    docs = {c_["sym"]: c_ for c_ in (doc.get("coins") or []) + (doc.get("others") or [])}
    rt = {k: [x[1:3] for x in v.get("rt") or []] for k, v in r_.items()}
    check(code == 0 and cyc == 2 and len(heads) == 3 and [s0[k].get("tweetLikes") for k in ("TWA", "TWB", "TWC", "TWD")] == [12_000, 50, None, 12_000]
          and s1["TWC"].get("tweetLikes") == 3_000 and all(s0[k].get("replies") == 4.0 for k in s0)
          and rt["TWA"] == rt["TWB"] and rt["TWA"] and (doc.get("hosts") or {}).get("x tweets") == "ok"
          and {"viral_tweet", "chatty"} <= set((docs.get("TWA") or {}).get("info") or []) and "viral_tweet" not in ((docs.get("TWB") or {}).get("info") or [])
          and ["info", "source tweet with 12,000 likes"] in ((docs.get("TWA") or {}).get("line") or []),
          "a radar run of 2 cycles: the first-sight signals (sig0) carry the replies (4) and the likes read at first sight (TWA 12,000, TWB 50, "
          "TWD off TWA's tweet 12,000); TWC, past the cap at first sight, is read in the next cycle: its later signals have 3,000, its sig0 "
          "stays unknown, never filled in; TWA's and TWB's verdicts and points are the same (%s): only the grey info differs; %d lookups, "
          "radar.json names the host 'x tweets'" % (rt["TWA"], len(heads)))


class FeedOne:
    """The live feed's interface for R15: one graduation (handed over once), the creates' facts of the coins it names, state ok."""

    def __init__(self, evs, info):
        self.evs, self.inf = list(evs), dict(info)

    def take(self):
        out, self.evs = self.evs, []
        return out

    def take_trades(self):
        return []

    def info(self, m):
        return self.inf.get(m)

    def lines(self):
        return []

    def state(self):
        return "ok"

    def stats(self):
        return {}

    def follow(self, mints):
        return []

    def trade_state(self):
        return {"shape": None, "want": 0, "subbed": 0, "since": None, "last": None, "n": 0}

    def stop(self, timeout=3.0):
        return True


def fastlane_checks(check, LR, T, P, tmp):
    """R15: the fast lane. A graduation on the live feed gets its coin rated within seconds by a mini-round (DexScreener for that mint,
    RugCheck, the rating, radar-data, the push) between two cycles instead of at the next early cycle: its tries while the pool is not
    listed, the record's feed lag and via, one push and never a second, only the requests that coin needs, the last cycle's hosts kept."""
    print("== launch radar R15: the fast lane after a graduation on the live feed")
    now0 = T0 + 30 * H
    g = now0 + 40_000
    fast = fixture("FASTGR", 41, pf=False, v3=False, gt=False, jup=False, pool=g, mint=g - 25 * MIN)
    mock = RadarMock(list(FIX.values()) + [fast])
    srv = serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    rem = fresh_remote(T, tmp, "fl", now0)
    rd = os.path.join(tmp, "rdFL")
    sink, lines = Sink(), []
    argv = ["loop", "--dir", rd, "--minutes", "10", "--cadence", "1", "--clock", "fake", "--now", str(now0), "--deadline", "8", "--cache", rd + "-cache",
            "--source", "manual", "--mock", url, "--remote", rem]
    e = dict(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9015", GITHUB_REF_NAME="main", MEMEBOT_RADAR_HOURS="0-24", RADAR_URL=None,
             SUPABASE_URL=None, SUPABASE_SECRET_KEY=None, MEMEBOT_RADAR_ADAPTERS=None, MEMEBOT_RADAR_FAST=None, MEMEBOT_RADAR_CURVE=None)
    try:
        with env(**e), memebot_rules():
            R = LR.Radar(LR.args_of(argv), log=lines.append, notifier=sink, traps=T, peak=P)
            mock.clock = R.clock.now
            R.start()
            R.live = FeedOne([{"kind": "migrate", "mint": fast["a"], "t": g}], {fast["a"]: {"t": fast["mint"], "creator": fast["creator"]}})
            R.cycle(0, R.clock.now(), False)
            hosts0 = dict((R.last_doc or {}).get("hosts") or {})
            mock.gone.add(fast["a"])
            R.clock.wait(g)
            R.live_take(R.clock.now())
            queued = {a_: dict(q_) for a_, q_ in R.fastq.items()}
            early0 = R.early_due(R.clock.now() + LR.LIVE_DEBOUNCE_MS, R.clock.now() + 100_000)
            R.clock.wait(g + 5_000)
            not_yet = R.fast_due(R.clock.now(), R.clock.now() + 100_000)
            R.clock.wait(g + LR.FAST_TRIES_MS[0])
            n0 = len(mock.heads)
            R.fast(R.clock.now(), R.clock.now() + 100_000)
            try1 = (dict(R.fastq.get(fast["a"]) or {}), R.rec(fast["a"]), sum(1 for h in mock.heads[n0:] if "/tokens/v1/" in h["path"]))
            mock.gone.discard(fast["a"])
            R.clock.wait(g + LR.FAST_TRIES_MS[1])
            t2 = R.clock.now()
            due2 = R.fast_due(t2, t2 + 100_000)
            n1 = len(mock.heads)
            w0 = time.time()
            R.fast(t2, t2 + 100_000)
            took = time.time() - w0
            heads2 = mock.heads[n1:]
            rec = json.loads(json.dumps(R.rec(fast["a"]) or {}))
            doc = radar_json(rem)
            pj = json.loads(branch_files(rem, "radar-data").get("pushed.json") or b"{}")
            early1 = R.early_due(R.clock.now() + LR.LIVE_DEBOUNCE_MS, R.clock.now() + 100_000)
            R.clock.wait(now0 + 120_000)
            R.cycle(1, R.clock.now(), False)
            rec2 = R.rec(fast["a"]) or {}
    finally:
        srv.shutdown()
        srv.server_close()
    fd = rec.get("feed") or {}
    coin = next((c for c in doc.get("coins") or [] if c.get("addr") == fast["a"]), {})
    check(queued == {fast["a"]: {"t": g, "n": 0}} and not early0 and not not_yet and try1[0] == {"t": g, "n": 1} and try1[1] is None and try1[2] == 1 and due2
          and any("fast lane: 1 graduation asked, no pool listed yet" in l for l in lines),
          "a graduation on the feed goes into the fast lane's queue (no early cycle meanwhile); 6 s after it DexScreener is asked once, the pool "
          "is not listed yet: the coin stays queued for its next try at 14 s")
    check(rec.get("first") == t2 and fd.get("mig") == g and fd.get("via") == "fast" and 13.5 <= (fd.get("lag") or 0) <= 16.0 and (rec.get("rt") or [[0, ""]])[0][1] == "good"
          and coin.get("v") == "good" and coin.get("push") == t2 and [x["coins"] for x in sink.got] == [["FASTGR"]] and pj.get(fast["a"]) == t2
          and any(l.startswith("fast lane: FASTGR") for l in doc.get("lines") or []) and took < LR.FAST_DEADLINE_S,
          "at the second try the coin is rated %.1f s after its graduation (feed.lag, via fast; the early round took up to 60 s): good, on radar.json's "
          "list and pushed once (pushed.json), its line on the desk; the mini-round took %.1f s" % (fd.get("lag") or -1, took))
    ds = [h for h in heads2 if "/tokens/v1/" in h["path"]]
    other = sorted({h["path"].split("/")[1] for h in heads2})
    check(len(ds) == 1 and fast["a"] in ds[0]["path"] and not any("geckoterminal" in h["path"] or "/recent" in h["path"] for h in heads2)
          and not any(h["path"] == "/frontend-api-v3.pump.fun/coins" and "creator=" not in h["q"] for h in heads2)
          and sum(1 for h in heads2 if h["path"].startswith("/api.rugcheck.xyz/")) == 1
          and all(doc["hosts"].get(k) == v for k, v in hosts0.items() if v != "unused" and k in ("geckoterminal", "jupiter")),
          "only the steps that coin needs: one DexScreener request for its mint, one RugCheck report, its own tier-2 checks, no discovery list "
          "and no GeckoTerminal (%s); the hosts it did not ask keep the last cycle's state" % ", ".join(other))
    check(not early1 and len(rec2.get("rt") or []) == 2 and [x["coins"] for x in sink.got] == [["FASTGR"]] and rec2.get("push") == t2,
          "no early cycle for a graduation the fast lane rated; the next round rates the coin again and never pushes it a second time")


def fastpush_checks(check, LR, T, P, tmp):
    """R17: the fast lane's push against app's rate guard and the round. Two greens rated by two fast lanes 8 s apart go through the real
    app.notify_radar (only its transport stubbed: one phone, every send ok): the second one meets app's 60 s gap, is unmarked and pushed
    by a later cycle (never lost); a lane that starts FAST_LEAD_MS before the round leaves its green's push to the round, so it ends before
    it whatever the notification would take."""
    import app as A
    print("== launch radar R17: the fast lane's push against app's rate guard and the next round")
    now0 = T0 + 32 * H
    g1, g2 = now0 + 40_000, now0 + 48_000
    f1 = fixture("FASTA", 44, pf=False, v3=False, gt=False, jup=False, pool=g1, mint=g1 - 25 * MIN)
    f2 = fixture("FASTB", 45, pf=False, v3=False, gt=False, jup=False, pool=g2, mint=g2 - 25 * MIN)
    f3 = fixture("FASTC", 46, pf=False, v3=False, gt=False, jup=False, pool=g2, mint=g2 - 25 * MIN)
    mock = RadarMock(list(FIX.values()) + [f1, f2, f3])
    srv = serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    sent, outs, lines = [], [], []
    stubs = {"enabled": lambda: True, "_webpush": lambda: object(), "vapid": lambda: ("k", "k"), "_sub_ok": lambda s_: True, "keys_ok": lambda s_: True,
             "call": lambda *a_, **k_: [{"endpoint": "https://push.example/1", "sub": {"endpoint": "https://push.example/1", "keys": {}}, "prefs": {}, "fails": 0}],
             "_send": lambda wp, sub, data, ttl, urg, topic, until=None: (sent.append(data), ("ok", 201, ""))[1], "_settle": lambda *a_, **k_: None}
    orig = {k: getattr(A, k) for k in stubs}

    def notifier(coins, record=None):
        out = A.notify_radar(coins, record)
        outs.append(([c.get("sym") for c in coins], out))
        return out

    def radar(name, rid):
        rem = fresh_remote(T, tmp, name, now0)
        rd = os.path.join(tmp, "rd" + name)
        argv = ["loop", "--dir", rd, "--minutes", "10", "--cadence", "1", "--clock", "fake", "--now", str(now0), "--deadline", "8", "--cache", rd + "-cache",
                "--source", "manual", "--mock", url, "--remote", rem]
        R = LR.Radar(LR.args_of(argv), log=lines.append, notifier=notifier, traps=T, peak=P)
        mock.clock = R.clock.now
        R.start()
        return R
    e = dict(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9017", GITHUB_REF_NAME="main", MEMEBOT_RADAR_HOURS="0-24", RADAR_URL=None,
             SUPABASE_URL=None, SUPABASE_SECRET_KEY=None, MEMEBOT_RADAR_ADAPTERS=None, MEMEBOT_RADAR_FAST=None, MEMEBOT_RADAR_CURVE=None)
    try:
        for k, v in stubs.items():
            setattr(A, k, v)
        A._last_push.pop("radar", None)
        with env(**e), memebot_rules():
            R = radar("fpRG", "9017")
            R.live = FeedOne([{"kind": "migrate", "mint": f1["a"], "t": g1}, {"kind": "migrate", "mint": f2["a"], "t": g2}],
                             {f1["a"]: {"t": f1["mint"], "creator": f1["creator"]}, f2["a"]: {"t": f2["mint"], "creator": f2["creator"]}})
            R.cycle(0, R.clock.now(), False)
            del outs[:]
            R.clock.wait(g2)
            R.live_take(R.clock.now())
            R.clock.wait(g1 + LR.FAST_TRIES_MS[0])
            mock.gone.add(f2["a"])                          # FASTB's pool is not listed yet at the first lane
            R.fast(R.clock.now(), R.clock.now() + 100_000)
            mock.gone.discard(f2["a"])
            R.clock.wait(R.clock.now() + LR.FAST_GAP_MS)
            R.fast(R.clock.now(), R.clock.now() + 100_000)
            lanes = [(s_, (o_ or {}).get("sent"), (o_ or {}).get("skipped")) for s_, o_ in outs]
            marked = (f1["a"] in R.pushed, f2["a"] in R.pushed, R.push_hold > time.time())
            del outs[:]
            R.clock.wait(R.clock.now() + 2 * MIN)
            R.cycle(1, R.clock.now(), False)                  # still inside app's gap: no notification is tried, nothing is marked
            held = (list(outs), f2["a"] in R.pushed)
            A._last_push["radar"] = time.time() - 61.0        # app's 60 s are over (no wall-clock wait in the test)
            R.push_hold = 0.0
            R.clock.wait(R.clock.now() + 2 * MIN)
            R.cycle(2, R.clock.now(), False)
            later = [(s_, (o_ or {}).get("sent")) for s_, o_ in outs]
            pushB = (R.rec(f2["a"]) or {}).get("push")
        check(lanes == [(["FASTA"], 1, None), (["FASTB"], 0, "rate guard")] and marked == (True, False, True) and held == ([], False)
              and later == [(["FASTB"], 1)] and pushB and f2["a"] in R.pushed,
              "a second green 8 s after the first one's push meets app's 60 s rate guard: it is unmarked (not lost as pushed), no notification is "
              "tried while the gap lasts, and the first cycle after it pushes the coin (%s, then %s)" % (lanes, later))
        A._last_push.pop("radar", None)
        del outs[:], lines[:]
        with env(**e), memebot_rules():
            Rc = radar("fpLead", "9018")
            Rc.live = FeedOne([{"kind": "migrate", "mint": f3["a"], "t": g2}], {f3["a"]: {"t": f3["mint"], "creator": f3["creator"]}})
            Rc.cycle(0, Rc.clock.now(), False)
            del outs[:]
            Rc.clock.wait(g2)
            Rc.live_take(Rc.clock.now())
            Rc.clock.wait(g2 + LR.FAST_TRIES_MS[0])
            t_k = Rc.clock.now() + LR.FAST_LEAD_MS
            due = Rc.fast_due(Rc.clock.now(), t_k)
            w0 = time.time()
            Rc.fast(Rc.clock.now(), t_k)
            took = time.time() - w0
            lead = (list(outs), f3["a"] in Rc.pushed, ((Rc.rec(f3["a"]) or {}).get("rt") or [[0, ""]])[0][1])
            Rc.clock.wait(t_k)
            t_rnd = Rc.clock.now()
            Rc.cycle(1, t_rnd, False)
            rnd = [(s_, (o_ or {}).get("sent")) for s_, o_ in outs]
        call_s, send_s = LR.app_budget()
        check(due and lead == ([], False, "good") and took < LR.FAST_LEAD_MS / 1000.0 - LR.PUSH_MARGIN_S and any("left to the round" in l for l in lines)
              and rnd == [(["FASTC"], 1)] and (Rc.rec(f3["a"]) or {}).get("push") == t_rnd,
              "a fast lane %d s before the round rates its green coin but leaves the push to the round (a notification may take %.0f s): it ends "
              "after %.1f s, before the round, and the round pushes the coin" % (LR.FAST_LEAD_MS // 1000, call_s + send_s, took))
    finally:
        for k, v in orig.items():
            setattr(A, k, v)
        A._last_push.pop("radar", None)
        srv.shutdown()
        srv.server_close()


def curve_doc_checks(check, LR, T, P, url, mock, tmp):
    """R16: radar.json's curve block (curve_watch.Book.doc) in a loop run: there in every cycle, within the doc's size, push off, no
    curve request with the fake clock (the watch runs in a loop's spare time only); MEMEBOT_RADAR_CURVE=off says off; a feed that sends no
    trades (silent) makes it on, list only; calls stored before the momentum's form was kept come back from radar-data and count."""
    print("== launch radar R16: radar.json's curve block")
    out = {}
    for name, val in (("on", None), ("off", "off")):
        rem = fresh_remote(T, tmp, "cd" + name, T0 + 40 * H)
        n0 = len(mock.heads)
        code, R, _, _ = run_radar(T, P, url, rem, os.path.join(tmp, "rdCD" + name), T0 + 40 * H, minutes=2.5, notifier=Sink(),
                                  envs={"MEMEBOT_RADAR_CURVE": val, "MEMEBOT_RADAR_FEED": None})
        d = radar_json(rem)
        out[name] = (code, d.get("curve") or {}, len(json.dumps(d, separators=(",", ":"))), [h for h in mock.heads[n0:] if "complete=false" in h["q"]],
                     sorted(p for p in branch_files(rem, "radar-data") if "curve" in p))
    con, cof = out["on"][1], out["off"][1]
    check(out["on"][0] == 0 and con.get("state") == "limited" and "feed is off" in con.get("why", "") and [r["id"] for r in con.get("variants") or []] == ["60", "60m", "75", "75m", "90", "90m"]
          and (con.get("push") or {}).get("variant") is None and con.get("hosts", {}).get("trades") == "off" and out["on"][2] <= LR.DOC_MAX and out["on"][3] == []
          and con.get("calib", {}).get("expect") == 410.9 and (con.get("greens") or {}).get("n") == 0 and out["on"][4] == ["curvepushed.json"],
          "every cycle's radar.json has the curve block: state limited without the live feed (%r), the six variants, push off, the "
          "calibration's expected 410.9 SOL, the greens; no curve request on the fake clock (the watch uses a loop's spare time); %d bytes"
          % (con.get("why"), out["on"][2]))
    check(out["off"][0] == 0 and cof.get("state") == "off" and "MEMEBOT_RADAR_CURVE=off" in cof.get("why", "") and out["off"][3] == [],
          "MEMEBOT_RADAR_CURVE=off: the block says off and why, nothing asked")
    import curve_watch as CW
    import radar_feed as RF
    t0 = T0 + 41 * H
    hour = CW.utc_hour(t0 - 30 * MIN)
    a1, a2 = addr(9301), addr(9302)
    oc = lambda thr, t, **kw: dict({"t": t, "thr": thr, "via": "trade", "prog": thr + 1.0, "px": 1e-7, "mcs": 100.0, "sol": 150.0, "mcu": 15000, "age": 20.0,
                                    "m5": {"pts": 14.0, "buys": 30, "sells": 9}, "mom": True, "v": "ok", "chips": [], "hi": 1.0, "out": {}, "push": None}, **kw)
    cdoc = {"v": 1, "hour": hour, "t": CW.hour_ms(hour), "upd": t0 - 20 * MIN, "polls": 40,
            "coins": {a1: {"mint": a1, "sym": "OLDA", "calls": {"75": oc(75, t0 - 30 * MIN)}},
                      a2: {"mint": a2, "sym": "OLDB", "calls": {"60": oc(60, t0 - 25 * MIN, m5={"pts": None, "buys": None, "sells": None}, mom=None, via="list")}}}}
    rem = fresh_remote(T, tmp, "cdold", t0)
    put_branch(rem, "radar-data", {"db/memecurve/%s.json" % hour: cdoc, "radar.json": {"v": 1, "kind": "radar", "t": t0 - MIN}}, tmp)
    R = unit_radar(T, P, tmp, "rdCDold", t0, extra=["--remote", rem])
    R.restore()
    fs = RF.LiveFeed(None, lambda: t0)                  # the live feed after its silence rule (no trade TRADE_SILENT_S after the first subscription)
    fs.tfirst, fs.n["subs"] = time.time() - RF.TRADE_SILENT_S - 1, 3
    fs.silence(time.time())
    R.live = fs
    R.curve_follow(R.clock.now())
    doc = R.build_doc("running", [], [], [], R.clock.now(), R.clock.now() + 120_000, 1.0, 0)
    landed = R.publish(doc)
    back = json.loads(branch_files(rem, "radar-data").get("db/memecurve/%s.json" % hour) or b"{}")
    cv = doc.get("curve") or {}
    var = {r["id"]: r["n"] for r in cv.get("variants") or []}
    b75 = ((back.get("coins") or {}).get(a1) or {}).get("calls", {}).get("75") or {}
    check(R.restore_state == "ok" and landed and not R.ckept and cv.get("calls") == 2 and var.get("75m") == 1 and var.get("60") == 1 and var.get("60m") == 0
          and sorted(back.get("coins") or {}) == sorted([a1, a2]) and b75.get("mom") is True and "momBy" not in b75
          and cv.get("state") == "on" and cv.get("why") == "list only: PumpPortal sends coin trades only to paid clients" and cv.get("hosts", {}).get("trades") == "unavailable"
          and cv.get("follow") == 0 and "every %d s" % (LR.CURVE_LIST_MS // 1000) in con.get("why", ""),
          "calls stored before the momentum's form was kept come back from radar-data, count in the variants as before (75%% rising %s) and go back "
          "whole; with the live feed silent (no trade for a client without a paid key) the block is on, %r, trades unavailable, and without "
          "the feed it says the list every %d s" % (var.get("75m"), cv.get("why"), LR.CURVE_LIST_MS // 1000))


def F_RPC():
    import fetch as F
    return F.RPC


def plant(T, n, ok):
    """results' db/memeradar with n records spread over 6 days: coins whose dev launched 12 coins, 11 of them dead, rug far more often
    (in the last 2 days the other way round when ok is False)."""
    rng = random.Random(n)
    docs = {}
    for i in range(n):
        first = T0 + 6 * H - 6 * 86_400_000 + int(i * (6 * 86_400_000 - 3 * H) / n)
        dead = i % 2 == 0
        late = first >= T0 + 6 * H - 2 * 86_400_000
        p = 0.7 if dead else 0.1
        if late and not ok:
            p = 0.1 if dead else 0.7
        rug = rng.random() < p
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(first / 1000))
        a = addr(10_000 + i)
        sig = {"instantPool": False, "mintToPoolS": 300, "swAvg": None, "rugHolders": 0, "wmChecked": True, "brand": False, "buys": 100, "rcReport": True, "rcDanger": [],
               "cluster": False, "creatorSold": False, "m5": 3.0, "socN": 2, "ageMin": 6.0, "x": "https://x.com/a", "paid": False, "tweet": False, "lists": 1,
               "mc": 50_000, "liq": 20_000, "devN": 12 if dead else 0, "devDead": 11 if dead else 0}
        docs.setdefault(hour, {"v": 1, "hour": hour, "t": first - first % H, "upd": first, "coins": {}})["coins"][a] = {
            "addr": a, "sym": "P%d" % i, "first": first, "pool": first - 6 * MIN, "px": 1.0, "rt": [[first, "watch", 2, 0]], "sig": sig,
            "later": {"60": {"t": first + H, "px": 0.05 if rug else 1.2, "liq": 500 if rug else 20_000}}, "out": {"rug1h": rug, "win1h": False, "x60": 0.05 if rug else 1.2}}
    return {"db/memeradar/%s.json" % h: d for h, d in docs.items()}


def real_push(check, T, P, url, remote, tmp):
    """With app.notify_radar (WP4): one notification through app.py to a local push service; its body says fake money."""
    import importlib.util
    try:
        import app as A
    except Exception:
        return False
    if not (hasattr(A, "notify_radar") and "radar" in getattr(A, "KINDS", {})) or importlib.util.find_spec("cryptography") is None:
        return False
    from selftest import Rest, serve_app, PushSink, APP_SECRET, FAKE_PYWEBPUSH
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    rest, psink = Rest(), PushSink()
    asrv = serve_app(rest, psink)
    sb_url = "http://127.0.0.1:%d" % asrv.server_address[1]
    fake = os.path.join(tmp, "fakepush")
    os.makedirs(fake, exist_ok=True)
    with open(os.path.join(fake, "pywebpush.py"), "w") as f:
        f.write(FAKE_PYWEBPUSH)
    k = ec.generate_private_key(ec.SECP256R1())
    p256 = base64.urlsafe_b64encode(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
    auth = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    ep = sb_url + "/push/radarphone"
    rest.subs[ep] = {"endpoint": ep, "sub": {"endpoint": ep, "keys": {"p256dh": p256, "auth": auth}}, "prefs": {"young": True}, "fails": 0, "delivered": None}
    rem = os.path.join(tmp, "remote-push.git")
    git("init", "-q", "--bare", rem)
    put_branch(rem, "radar-feed", feed_files(T, T0 + 8 * H), tmp)
    mock = MOCK
    a = next(c["a"] for c in mock.coins.values() if c["name"] == "CLEAN")
    mock.coins[a]["pool"] = T0 + 8 * H - MIN
    sys.path.insert(0, fake)
    try:
        code, R, lines, _ = run_radar(T, P, url, rem, os.path.join(tmp, "rdPush"), T0 + 8 * H, minutes=2.5, notifier=None,
                                      envs={"SUPABASE_URL": sb_url, "SUPABASE_SECRET_KEY": APP_SECRET})
    finally:
        sys.path.remove(fake)
        mock.coins[a]["pool"] = T0
        asrv.shutdown()
        asrv.server_close()
    got = [json.loads(g["data"]) for g in psink.got if g["data"].startswith("{")]
    body = " ".join(str((g.get("notification") or {}).get("body")) for g in got)
    check(code == 0 and got and "fake money" in body.lower() and not re.search(r"\bbuy\b", body, re.I) and "checks passed (curve " in body
          and all(len(str((g.get("notification") or {}).get("body"))) <= 300 for g in got),
          "through app.notify_radar to a local push service, naming the checks it passed: %r" % body[:160])
    return True


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d radar checks failed" % len(fails) if fails else "\nRADAR ALL PASS" + (" (skipped: %s)" % "; ".join(SKIPPED) if SKIPPED else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
