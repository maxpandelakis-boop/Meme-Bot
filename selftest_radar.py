#!/usr/bin/env python3
"""selftest_radar.py: the launch radar's checks R1-R10 (SPEC 11) and R11 (the WP0 probe's findings applied: adapter defaults, routes,
rate rules), against a local mock of every host it asks, a fake clock (cadence 1 s, 150 s of clock time a cycle), a local bare git
remote and a local stand-in for the app's live store. Fake money only.

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

    def __call__(self, coins):
        import launch_radar as LR
        title, body = LR.push_text(coins)
        self.got.append({"coins": [c.get("sym") for c in coins], "title": title, "body": body})
        return {"kind": "radar", "sent": 1}


def run_radar(T, P, url, remote, rd, now, minutes=10, notifier=None, hours="0-24", extra=None, deadline=8.0, patch=None, envs=None):
    """One radar run in this process: (exit code, the Radar, its log lines, seconds)."""
    import launch_radar as LR
    lines = []
    argv = ["loop", "--dir", rd, "--minutes", str(minutes), "--cadence", "1", "--clock", "fake", "--now", str(int(now)), "--deadline", str(deadline),
            "--cache", rd + "-cache", "--source", "manual"] + (["--mock", url] if url else []) + (["--remote", remote] if remote else []) + (extra or [])
    e = dict(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9001", GITHUB_REF_NAME="main", MEMEBOT_RADAR_HOURS=hours, RADAR_URL=None,
             SUPABASE_URL=None, SUPABASE_SECRET_KEY=None, MEMEBOT_RADAR_ADAPTERS=None)
    e.update(envs or {})
    t = time.time()
    with env(**e), memebot_rules():
        R = LR.Radar(LR.args_of(argv), log=lines.append, notifier=notifier, traps=T, peak=P)
        for m in MOCKS:
            m.clock = R.clock.now
        if patch:
            patch(R)
        code = R.loop()
    return code, R, lines, time.time() - t


def unit_radar(T, P, tmp, name, now=T0, extra=None, log=None):
    """A Radar without a run (no GitHub, fake clock) for checks on one method."""
    import launch_radar as LR
    return LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, name), "--clock", "fake", "--now", str(int(now)), "--cache", os.path.join(tmp, name + "-c"),
                                "--no-github"] + (extra or [])), log=log or (lambda s_: None), traps=T, peak=P)


def fresh_remote(T, tmp, name, now, **kw):
    """A bare remote with only radar-feed (feed_files(T, now, **kw))."""
    rem = os.path.join(tmp, name + ".git")
    git("init", "-q", "--bare", rem)
    put_branch(rem, "radar-feed", feed_files(T, now, **kw), tmp)
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
        # ---- R1, R2, R4 (first part), R7 (refs), R5 (chain): a run of 4 cycles at T0
        print("== launch radar R1: 4 cycles on the fixtures -> radar.json and a record for every eligible coin")
        sink = Sink()
        code, R, lines, secs = run_radar(T, P, url, remote, os.path.join(tmp, "rdA"), T0, minutes=10, notifier=sink)
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
        an = addr(710)
        Ru.cache["pf"][an] = {"t": T0 + 30_000}                     # the mint 30 s after the pool: two sources' clocks disagree
        rn = {"a": an, "pr": {"pairCreatedAt": T0, "symbol": "NEG", "name": "Negative Gap", "dexId": "pumpswap", "pairAddress": "NegPool"},
              "basic": {"price": 1e-5, "liq": 20_000.0, "mc": 50_000.0}, "f": {}, "age": 5.0}
        Sn, cn = Ru.signals(rn, T0 + 5 * MIN)
        rtn = T.rate(Sn, Ru.W_prior)
        check(cn["mint"] is None and cn["mintToPoolS"] is None and Sn.get("instantPool") is None and Sn.get("mintToPoolS") is None and rtn["verdict"] != "good"
              and "mint_time" in (rtn.get("unknown") or []),
              "a pool that opened before its mint (the clocks disagree): the gap is unknown, never 'not instant' (verdict %s, unknown %s)" % (rtn["verdict"], rtn.get("unknown")))
        Ru.W = dict(Ru.W_prior, brand=None)
        cb = Ru.coin(dict(rn, pr=dict(rn["pr"], name="Grok Agent")), T0 + 5 * MIN)
        Ru.W = dict(Ru.W_prior, brand="(")
        cb2 = Ru.coin(rn, T0 + 5 * MIN)
        Ru.W = Ru.W_prior
        check(cb["brand"] is None and cb2["brand"] is None and Ru.coin(dict(rn, pr=dict(rn["pr"], name="Grok Agent")), T0 + 5 * MIN)["brand"] is True,
              "the brand check reads only radar_weights.json's list (I7): without a list, or with one that does not compile, it is unknown, never passed")

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
                                           notifier=lambda coins: {"kind": "radar", "sent": 0, "skipped": "no push sender"})
        ds, rsk = radar_json(rem_s), hour_recs(rem_s)
        pj_s = json.loads(branch_files(rem_s, "radar-data").get("pushed.json") or b"{}")
        said = [d_ for d_ in rows_s + [ds] if (d_.get("counts") or {}).get("pushed") or any(c.get("push") for c in d_.get("coins") or [])]
        check(code_s == 0 and rows_s and not said and not (rsk.get(by["CLEAN"]) or {}).get("push") and by["CLEAN"] in pj_s
              and any(n.get("sym") == "CLEAN" for d_ in rows_s for n in d_.get("coins") or [])
              and all(", 0 pushed " in l for l in liness if re.match(r"^cycle \d+:", l)),
              "a notification that did not go out (no push sender): neither radar.json nor the app's row nor the record says pushed, the cycle "
              "line says 0 pushed; the coin stays in pushed.json, so it is never sent later")

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
        win = {"10 s before due": T0 - 5 * MIN + 10_000, "1 s before due (clock jitter)": T0 - 5 * MIN + 1_000, "7 min late": T0 - 12 * MIN, "8 min late": T0 - 13 * MIN}
        wa = {n: addr(600 + i) for i, n in enumerate(win)}
        Rg.docs = {"w": {"coins": {wa[n]: {"addr": wa[n], "first": f, "later": {}, "px": 1.0} for n, f in win.items()}}}
        Rg.rec_hour = {a: "w" for a in wa.values()}
        Rg.later_prices({a: {"priceUsd": "1.5", "liquidityUsd": 9000.0} for a in wa.values()}, set(wa.values()), T0)
        p5 = {n: Rg.docs["w"]["coins"][wa[n]]["later"].get("5") for n in win}
        check(p5["10 s before due"] is None and p5["1 s before due (clock jitter)"] and not p5["1 s before due (clock jitter)"].get("late")
              and (p5["7 min late"] or {}).get("late") is True and p5["8 min late"] is None,
              "the 5-minute price: never taken before it is due (only the clock's 2 s jitter), taken up to 1.5x its offset late (7 of 7.5 min) and "
              "marked late, missing after that (%s)" % {n: (None if v is None else ("late" if v.get("late") else "on time")) for n, v in p5.items()})
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
        check(code_b == 0 and not sink_b.got and rb.get("rt") and len(rb["rt"]) == 5 and rb["rt"][-1][1] == "good",
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

        print("== launch radar R5: kill switch, active hours, the successor")
        n_disp = len(mock.dispatches)
        check(n_disp >= 1 and mock.dispatches[0] == {"ref": "main", "inputs": {"minutes": "55", "source": "chain"}} and sum(1 for l in lines if l.startswith("successor: dispatched")) == 1
              and mock.auth_bad == 0 and any("a run of 2.5 min starts none" in l for l in linesb) and not any(l.startswith("successor: dispatched") for l in linesb + lines2),
              "run A (10 minutes) dispatched its successor once at its end minus 2 minutes, a 55-minute one (%s); a 2.5-minute run starts none" % mock.dispatches[:1])
        mock.runs = [{"id": 1234, "status": "pending"}]
        d0 = len(mock.dispatches)
        code, Rp, linesp, _ = run_radar(T, P, url, remote, os.path.join(tmp, "rdP"), T0 + 2 * H, minutes=5, notifier=Sink())
        mock.runs = []
        check(len(mock.dispatches) == d0 and any("another radar run is waiting" in l for l in linesp), "no successor while another radar run is pending (C4)")
        mock.runs500 = 1
        d0 = len(mock.dispatches)
        code, Rq, linesq, _ = run_radar(T, P, url, fresh_remote(T, tmp, "remote-chain", T0 + 2 * H), os.path.join(tmp, "rdQ"), T0 + 2 * H, minutes=5, notifier=Sink())
        hic = [l for l in linesq if l.startswith("successor:")]
        check(mock.runs500 == 0 and len(mock.dispatches) == d0 + 1 and len(hic) == 2 and "GitHub did not list the runs" in hic[0] and hic[0].endswith("tried once more") and hic[1].startswith("successor: dispatched"),
              "a GitHub hiccup at the chain point (the run list answered 500) is tried once more half a minute later: %s" % hic)
        with env(GITHUB_REPOSITORY=REPO, GITHUB_TOKEN=GH_TOKEN, GITHUB_RUN_ID="9001", GITHUB_REF_NAME="main"), memebot_rules():
            outs = []
            for label, end_at in (("ends 5 min before 14:00", T0 - 5 * MIN), ("ends 30 s after 14:00", T0 + 30_000), ("ends 15 min before 14:00", T0 - 15 * MIN)):
                Rc = LR.Radar(LR.args_of(["loop", "--dir", os.path.join(tmp, "rdCh"), "--clock", "fake", "--now", str(T0), "--cache", os.path.join(tmp, "rdCh-c"), "--mock", url]),
                              log=lambda s_: None, traps=T, peak=P)
                Rc.hours, Rc.run_start, Rc.run_end, Rc.run_minutes = (13, 14), end_at - 30 * MIN, end_at, 30.0
                n0 = len(mock.dispatches)
                outs.append((label, Rc.chain(), len(mock.dispatches) - n0, Rc.chained))
        check([o[1:] for o in outs] == [(False, 0, True), (False, 0, True), (True, 1, True)] and mock.dispatches[-1]["inputs"]["minutes"] == "55",
              "active hours 13-14 Berlin: no successor when the hours end within 10 minutes of the run's end or before it; one (55 minutes) with "
              "15 minutes left (%s)" % outs)
        check([LR.run_minutes(m, f) for m, f in ((120, False), (330, False), (70, False), (10, False), (0, False), (0, True), (None, False))] == [70, 70, 70, 10, 55, 0, 55],
              "a run lasts at most 70 minutes (the job stops at 75: a longer run would be cut before it starts its successor); 0 = until stopped only "
              "without GitHub (a VM), else 55")
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
        real_exists = LR.Git.exists
        LR.Git.exists = lambda self_, branch, timeout=30: None          # git ls-remote got no answer
        try:
            with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=remote, GITHUB_TOKEN=None):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc_n = LR.main(["hours", "--dir", os.path.join(tmp, "hours4"), "--now", str(T0 + 3 * H)], log=hout2.append)
        finally:
            LR.Git.exists = real_exists
        rem_n = os.path.join(tmp, "remote-nobranch.git")
        git("init", "-q", "--bare", rem_n)
        with env(MEMEBOT_RADAR_HOURS="1-2", RADAR_URL=rem_n, GITHUB_TOKEN=None):
            with contextlib.redirect_stdout(io.StringIO()):
                rc_m = LR.main(["hours", "--dir", os.path.join(tmp, "hours5"), "--now", str(T0 + 3 * H)], log=hout2.append)
        check(rc_n == 0 and refs(remote).get("refs/heads/radar-data") == sha_h and branch_files(remote, "radar-data") == files_h and any("did not answer" in l for l in hout2)
              and rc_m == 0 and "refs/heads/radar-data" not in refs(rem_n) and any("does not exist yet: not made here" in l for l in hout2),
              "the hours gate when GitHub does not answer about radar-data: nothing written (no tree of radar.json alone over the records); without "
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

        wf = open(os.path.join(HERE, ".github", "workflows", "radar.yml"), encoding="utf-8").read()
        sc = open(os.path.join(HERE, ".github", "workflows", "scan.yml"), encoding="utf-8").read().splitlines()
        body = lambda lines: lines[lines.index(next(l for l in lines if "Install the push sender" in l)) + 2:][:30]
        job_env = wf.split("    steps:")[0]
        check(re.search(r"^on:\n  workflow_dispatch:", wf, re.M) and "schedule" not in wf and "group: memebot-radar" in wf and "cancel-in-progress: false" in wf
              and re.search(r"^    timeout-minutes: 75\b", wf, re.M) and "if: vars.MEMEBOT_RADAR != '0'" in wf and body(wf.splitlines()) == body(sc)
              and "RADAR_URL" not in job_env and "SUPABASE_SECRET_KEY: ${{" not in job_env and not re.search(r"git push|refs/heads/(results|live|radar-feed)", wf)
              and "launch_radar.py loop --dir rd --minutes \"$MIN\" --cadence 150" in wf and "actions/cache/save@v4" in wf and "if: always() && steps.hours.outputs.inside == 'true'" in wf
              and "MEMEBOT_RADAR_ADAPTERS: ${{ vars.MEMEBOT_RADAR_ADAPTERS || '' }}" in job_env
              and "(at most %d: the job stops at 75)" % LR.MAX_MINUTES in wf and LR.MAX_MINUTES + 5 <= 75 and "330" not in wf
              and 'out=$(timeout 150 python3 launch_radar.py hours --dir rd) || out="inside=true"' in wf and len(re.findall(r"^        timeout-minutes: [234]\b", wf, re.M)) == 3
              and all("--max-time" in l for l in wf.splitlines() if re.search(r"\bcurl -sS\b", l) and "api" in l),
              "radar.yml: dispatch only, group memebot-radar, 75 min, minutes at most 70, MEMEBOT_RADAR gate, the adapter switches from a repository "
              "variable, the push sender's install step as in scan.yml, the token only in the steps that use it, the hours and tidy steps bounded "
              "in time (they hold the radar's group)")

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
            same.append(p.returncode == 0 and p.stdout == open(os.path.join(HERE, f), "rb").read())
        import ast
        mods = set()
        for f in ("launch_radar.py", "radar_src.py"):
            for node in ast.walk(ast.parse(open(os.path.join(HERE, f), encoding="utf-8").read())):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
        own = {"memebot", "fetch", "radar", "radar_src", "app", "traps", "peak"}
        std = set(getattr(sys, "stdlib_module_names", ())) or {"argparse", "datetime", "glob", "gzip", "importlib", "io", "json", "math", "os", "re", "shutil", "subprocess",
                                                              "sys", "tarfile", "time", "urllib", "zoneinfo"}
        check(all(same) and mods - own <= std, "memebot.py, fetch.py and radar.py are byte for byte as at %s (%s); imports: %s" % (BASE, same, sorted(mods - own)))

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
        allt = b"\n".join(blobs) + "\n".join(lines + lines2 + lines3 + lines6 + lines9 + linesx + linesf + linesb + linesp + lineso + linesh + hout).encode() + json.dumps(row).encode()
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
        for name, n, ok, want in (("few", 250, True, "prior"), ("good", 420, True, "learned"), ("reversed", 420, False, "prior")):
            rem_m = os.path.join(tmp, "remote-%s.git" % name)
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
        probe_checks(check, LR, T, P, url, mock, heads_a, recs, by, tmp)
        if not real_push(check, T, P, url, remote, tmp):
            SKIPPED.append("R4's PushSink leg (app.notify_radar comes with WP4)")
    finally:
        rules.__exit__(None, None, None)
        MOCK = None
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


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
    radar_only = {"ds_tokens", "dev_check", "gt_candles"}
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
    check(code == 0 and got and "fake money" in body.lower() and not re.search(r"\bbuy\b", body, re.I), "through app.notify_radar to a local push service: %r" % body[:120])
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
