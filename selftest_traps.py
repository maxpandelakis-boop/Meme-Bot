#!/usr/bin/env python3
"""selftest_traps.py: checks T1-T7 of SPEC 13.10 section 11 for traps.py and radar_weights.json (fake money only).

  python3 selftest_traps.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure

selftest.py calls checks(check, env) after spotter_checks. Needs no network, no mock server and no other package's files:
the radar's coin dicts below are built here the way launch_radar.py hands them to traps.signals_radar.
"""
import ast, copy, glob, gzip, json, math, os, random, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import traps as T          # noqa: E402

PY = sys.executable
H, MIN, DAY = 3_600_000, 60_000, 86_400_000
NOW = 1_792_000_000_000            # a fixed clock (2026-10-14 UTC); traps never reads the wall clock when given one
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ADVICE = re.compile(r"\b(safe|safety|buy|guaranteed|clean)\b", re.I)      # never in a text that can reach the page (I12)


def strings(o):
    """Every string inside a JSON value."""
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [x for k, v in o.items() for x in strings(k) + strings(v)]
    if isinstance(o, list):
        return [x for v in o for x in strings(v)]
    return []


def wallet(rng, suffix=""):
    return "".join(rng.choice(ALPH) for _ in range(44 - len(suffix))) + suffix


def base_S(**kw):
    """A coin that passes every check (rule D, strict): report, mint time, wallet memory, no soft warning, no good sign."""
    S = T.blank_signals()
    S.update(rcReport=True, rcDanger=[], rcWarn=[], cluster=False, netSize=None, mintToPoolS=240.0, instantPool=False, wmChecked=True,
             wmState="ok", rugHolders=0, swAvg=-1.0, brand=False, buys=400.0, socN=2.0, m5=6.0, creatorSold=False, ageMin=6.0, x="",
             xKind=None, paid=False, tweet=False, lists=1.0, mc=60_000.0, liq=22_000.0, creatorPct=1.0, pumpswap=True)
    S.update(kw)
    return S


def radar_coin(rng, wm, **kw):
    """The radar's merged coin dict for a CLEAN launch (Appendix B): pump.fun mint 4 min on the curve, pool 5 min old, $22k
    liquidity, a RugCheck report without danger, socials, top holders the wallet memory does not know."""
    holders = [wallet(rng) for _ in range(10)]
    c = {"now": NOW, "addr": wallet(rng, "pump"), "sym": "CLEAN", "name": "Clean Coin", "dex": "pumpswap", "pool": NOW - 5 * MIN, "mint": NOW - 9 * MIN,
         "first": NOW - 4 * MIN, "px": 0.00006, "liq": 22_000.0, "mc": 60_000.0, "m5": 7.0, "buys": 310.0, "socN": 2.0, "x": "https://x.com/cleancoin",
         "paid": False, "lists": 2, "devSold": False, "wm": wm,
         "rc": {"risks": [{"name": "Low amount of LP Providers", "level": "warn"}], "topHolders": [{"owner": h, "pct": 3.0} for h in holders],
                "token": {"supply": 1e9}, "creatorBalance": 1e7, "graphInsidersDetected": 0}}
    c.update(kw)
    return c


def checks(check, env=None):
    rng = random.Random(1310)
    W = T.load_weights()
    tmp = tempfile.mkdtemp(prefix="memebot-traps-")
    try:
        _weights(check, W)
        _t1(check, W, rng)
        _t2(check, W)
        _t3(check, W)
        _t4(check)
        _t5(check, W)
        _t6(check, W)
        _t7(check, W, tmp)
        _extras(check, W, rng, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- radar_weights.json
def _weights(check, W):
    print("== traps: radar_weights.json (the study prior)")
    keys = {"v", "src", "hard", "soft", "maxSoft", "needChecked", "points", "upside", "pushBlock", "thresholds", "brand", "evidence", "zero"}
    th = W["thresholds"]
    check(W["v"] == 1 and W["src"] == "study 2026-10-13" and keys <= set(W)
          and W["hard"] == ["instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "staircase10"]
          and W["soft"] == ["no_socials", "holder_cluster", "creator_sold", "pumping_5m"] and W["maxSoft"] == 1
          and W["needChecked"] == ["rc_report", "mint_time", "walletmem"] and W["pushBlock"] == ["holder_cluster"]
          and th["instantPoolS"] == 60 and th["swAvg"] == -7 and th["swMinRecords"] == 2 and th["rugHolders"] == 3 and th["buys"] == 3000
          and th["m5"] == 20 and th["youngMin"] == 5 and th["stair"] == {"n": 10, "rise": 0.2, "green": 0.7, "pull": 0.05} and th["curve2mS"] == 120
          and th["mintSkewS"] == 120 and th["wmMinCoins"] == 500 and th["wmMaxAgeH"] == 3.0,
          "radar_weights.json v1 'study 2026-10-13': hard, soft (maxSoft 1), needChecked, pushBlock and thresholds as the spec says "
          "(plus clock skew 120 s, wallet memory from 500 coins, 3 h old at most)")
    texts = [t for k, v in W.items() if k != "brand" for t in strings(v)]
    bad = [t for t in texts if ADVICE.search(t) or "\u2014" in t]
    check(not bad, "no text of radar_weights.json (note, labels, evidence, weight-0 reasons, caveats: %d strings) says safe, safety, buy, "
          "guaranteed or clean, or has an em dash%s" % (len(texts), "" if not bad else ": %s" % bad[:3]))
    ev_need = set(W["hard"]) | set(W["soft"]) | {"no_rc_report", "young_5m", "x_and_paid", "tweet", "lists3"}
    ev_ok = all(W["evidence"].get(k, {}).get("rows") for k in ev_need)
    ev_rows = [r for k in ev_need for r in W["evidence"][k]["rows"]]
    shape = all({"cohort", "outcome", "with", "without", "n", "lift", "lo", "hi"} <= set(r) for r in ev_rows)
    check(ev_ok and shape and all(W["evidence"][m]["rows"] == [] for m in W["measured"]),
          "evidence: every weighted signal has study rows (rug with / without, n, lift, 95%% interval, cohort; %d rows), measured signals none" % len(ev_rows))
    zero = {z["signal"]: z for z in W["zero"]}
    check(all(z.get("reason") for z in W["zero"]) and {"rc.top1>20", "rcn.creator_rugged", "jup.devMints>1", "rcn.copycat", "own.ticker_reused"} <= set(zero)
          and zero["rc.top1>20"]["reason"] == "reversed" and zero["rcn.copycat"]["reason"] == "too rare" and zero["rcn.creator_rugged"]["reason"] == "no effect",
          "the weight-0 list names its reason (reversed / too rare / no effect ...) for %d tested signals" % len(W["zero"]))


# ---------------------------------------------------------------- T1
def _t1(check, W, rng):
    print("== traps T1: every rule of rate()")
    r = T.rate(base_S(), W)
    check(r["verdict"] == "good" and r["push"] and r["pts"] == 0 and not r["hard"] and not r["soft"] and not r["unknown"] and r["n"] >= 9,
          "rule D, strict (report, mint time, wallet memory, 0 soft) -> good and pushable (%d checks)" % r["n"])
    hard_cases = {"instant_pool": dict(mintToPoolS=12.0, instantPool=None), "rugger_wallets": dict(rugHolders=3), "brand_name": dict(brand=True),
                  "bot_volume": dict(buys=3000.0), "rc_danger": dict(rcDanger=["Freeze Authority still enabled"]),
                  "staircase10": dict(stair={"n": 10, "rise": 0.3, "green": 0.8, "pull": 0.01, "stair": True})}
    res = {k: T.rate(base_S(**v), W) for k, v in hard_cases.items()}
    check(all(x["verdict"] == "trap" and x["hard"] == [k] and not x["push"] for k, x in res.items()),
          "each hard signal alone -> trap (%s)" % ", ".join("%s %d pts" % (k, x["pts"]) for k, x in res.items()))
    sw = T.rate(base_S(swAvg=-7.0, rugHolders=0), W)
    check(sw["verdict"] == "trap" and sw["hard"] == ["rugger_wallets"], "rugger wallets also by the holders' past average (sw.avg -7 or lower)")
    edge = {sec: T.rate(T.signals_radar(radar_coin(rng, None, mint=NOW - 5 * MIN - int(sec * 1000)), W), W)["hard"] for sec in (0, 59, 59.95, 60, 61)}
    check(edge == {0: ["instant_pool"], 59: ["instant_pool"], 59.95: ["instant_pool"], 60: [], 61: []} and T.instant(NOW, NOW - 59_000) is True
          and T.instant(NOW, NOW - 61_000) is False and T.instant(NOW, None) is None,
          "instant pool: 0, 59 and 59.95 s from mint to pool -> trap; 60 and 61 s -> not (the exact gap, as the study)")
    nm = T.rate(base_S(mintToPoolS=None, instantPool=None), W)
    check(nm["verdict"] == "watch" and nm["unknown"] == ["mint_time"] and not nm["push"], "unknown mint time -> watch, unknown = mint_time")
    nr = T.rate(base_S(rcReport=False, rcDanger=None, rcWarn=None, cluster=None), W)
    check(nr["verdict"] == "watch" and "rc_report" in nr["unknown"] and nr["pts"] == 2 and not nr["push"]
          and ["unk", "RugCheck pending"] in T.chips(nr, base_S(rcReport=False), W), "no RugCheck report -> watch, +2 points, 'RugCheck pending'")
    two = T.rate(base_S(socN=0.0, creatorSold=True), W)
    one = T.rate(base_S(socN=0.0), W)
    check(two["verdict"] == "watch" and two["soft"] == ["no_socials", "creator_sold"] and not two["unknown"] and one["verdict"] == "good" and one["push"],
          "2 soft warnings -> watch; 1 soft warning (rule D) -> good")
    cl = T.rate(base_S(cluster=True, netSize=232), W)
    check(cl["verdict"] == "good" and not cl["push"] and cl["soft"] == ["holder_cluster"] and ["warn", "holder cluster (insider network of 232)"] in T.chips(cl, base_S(cluster=True, netSize=232), W),
          "holder cluster -> good, push blocked")
    nw = T.rate(base_S(wmChecked=False, wmState="missing", rugHolders=None, swAvg=None), W)
    old = T.rate(T.signals_radar(radar_coin(rng, {"v": 1, "t": NOW - 4 * H, "common": [], "rug": [], "sw": {}}), W), W)
    empty = T.rate(T.signals_radar(radar_coin(rng, {"v": 1, "t": NOW - 10 * MIN, "nCoins": 0, "common": [], "rug": [], "sw": {}}), W), W)
    check(nw["verdict"] == "watch" and nw["unknown"] == ["walletmem"] and old["verdict"] == "watch" and "walletmem" in old["unknown"]
          and empty["verdict"] == "watch" and empty["unknown"] == ["walletmem"],
          "wallet memory missing, built from no coin, or older than 3 h -> watch (no greens)")
    m = base_S(devN=12.0, devDead=11.0, devAgeH=3.0, xUsed=2.0, xKind="account", snip30=0.61, snip30N=12.0, slotN=6.0, slotPct=0.44, freshN=6.0,
               freshOf=10.0, fundN=4.0, fundMin=3.0, tweetShared=2.0, stair={"n": 7, "rise": 0.3, "green": 0.85, "pull": 0.02, "stair": False})
    rm = T.rate(m, W)
    check(rm["verdict"] == "good" and rm["pts"] == 0 and rm["push"] and set(rm["info"]) == set(W["measured"]) | {"tweet_shared"},
          "measured signals (all %d set) never change verdict, points or push: they only show as info" % len(rm["info"]))
    # Appendix B through signals_radar (the radar's path)
    wm = {"v": 1, "t": NOW - 20 * MIN, "nCoins": 900, "common": [], "rug": [wallet(rng) for _ in range(30)], "sw": {}}
    clean = radar_coin(rng, wm)
    rug3 = radar_coin(rng, wm)
    rug3["rc"]["topHolders"][:3] = [{"owner": w, "pct": 4.0} for w in wm["rug"][:3]]
    xl = {}
    T.xlinks_add(xl, "https://twitter.com/CleanCoin/", wallet(rng, "pump"), NOW - 3 * H)
    fx = {"CLEAN": clean, "INSTA": dict(clean, mint=clean["pool"]), "BRAND": dict(clean, name="Grok Agent", sym="GROKA"), "NORC": dict(clean, rc=None),
          "NOMINT": dict(clean, mint=None, dex="meteora"), "CLUSTER": dict(clean, rc=dict(clean["rc"], graphInsidersDetected=232)), "RUGGERS": rug3,
          "XCOPY": dict(clean, xlinks=xl)}
    want = {"CLEAN": ("good", True), "INSTA": ("trap", False), "BRAND": ("trap", False), "NORC": ("watch", False), "NOMINT": ("watch", False),
            "CLUSTER": ("good", False), "RUGGERS": ("trap", False), "XCOPY": ("good", True)}
    got, lines = {}, {}
    for k, c in fx.items():
        S = T.signals_radar(c, W)
        rt = T.rate(S, W)
        got[k] = (rt["verdict"], rt["push"])
        lines[k] = T.chips(rt, S, W)
    check(got == want and ["bad", "pool opened with the mint"] in lines["INSTA"] and ["bad", "brand/celebrity name"] in lines["BRAND"]
          and ["unk", "RugCheck pending"] in lines["NORC"] and ["unk", "mint time unknown"] in lines["NOMINT"]
          and ["warn", "holder cluster (insider network of 232)"] in lines["CLUSTER"] and ["bad", "3 holders from rugged coins"] in lines["RUGGERS"]
          and ["info", "X account used by 1 older coin"] in lines["XCOPY"] and ["ok", "curve 4 min before pool"] in lines["CLEAN"],
          "Appendix B coins through signals_radar: %s" % ", ".join("%s %s%s" % (k, v[0], " push" if v[1] else "") for k, v in got.items()))
    _t1_unknown(check, W, rng, wm, clean)


def _t1_unknown(check, W, rng, wm, clean):
    """I5 'unknown is never clean': every check that could not run blocks green and the push (review fix1: B1, S3, SF2, N1, N2, nits)."""
    rr = lambda c: T.rate(T.signals_radar(c, W), W)
    # B1: a pool cannot open before its mint; a small negative gap is clock skew on a same-slot launch, a large one is unknown
    skew = {ms: rr(dict(clean, mint=clean["pool"] + ms)) for ms in (100, 1000, 5000, 119_000)}
    far = rr(dict(clean, mint=clean["pool"] + H))
    zero = rr(dict(clean, mint=0))
    secs = rr(dict(clean, mint=(clean["pool"] - 4 * MIN) / 1000.0))
    fb = {m: T.rate(base_S(mintToPoolS=m, instantPool=None), W) for m in (-3.0, -119.0, -121.0, -3600.0)}
    check(all(r["verdict"] == "trap" and r["hard"] == ["instant_pool"] for r in skew.values())
          and far["verdict"] == "watch" and far["unknown"] == ["mint_time"] and not far["push"] and zero["unknown"] == ["mint_time"] and not zero["push"]
          and secs["unknown"] == ["mint_time"] and T.instant(NOW, NOW + 100) is True and T.instant(NOW, NOW + H) is None and T.instant(NOW, 0) is None
          and fb[-3.0]["hard"] == ["instant_pool"] and fb[-119.0]["hard"] == ["instant_pool"] and fb[-121.0]["unknown"] == ["mint_time"]
          and fb[-3600.0]["unknown"] == ["mint_time"] and T.pair_times({"pf": {"createdAt": 0}, "pairCreatedAt": 5}) == (None, None),
          "a pool 0.1 s to 119 s 'before' its mint is the same launch (clock skew) -> instant pool trap; 1 h before, a mint time of 0 "
          "or in seconds -> mint time unknown, watch, no push")
    # the young tab without a pool time: recommend.json's age is rounded to 4 decimals (0.36 s), so a gap-0 pool can read as -0.1 s
    y = {"sym": "INST", "name": "Instant Coin", "dex": "pumpswap", "x": "https://x.com/inst", "mc": 70_000.0, "liq": 21_000.0,
         "f": {"ageH": 0.0833, "buys1": 300.0, "m5": 4.0, "socN": 2.0, "x": 1.0, "ds.paid": 0.0, "vt.tweet": 0.0, "srcN": 2.0},
         "risk": {"danger": [], "warn": [], "holders": [wallet(rng) for _ in range(8)], "creatorPct": 0.5}}
    young = T.rate(T.signals_scan(y, NOW - 0.0833 * H + 100, wm, now=NOW), W)
    check(young["verdict"] == "trap" and young["hard"] == ["instant_pool"] and not young["push"],
          "young tab: a pool opened with the mint whose rounded age puts it 0.1 s before the mint -> trap, never good + push")
    # SF2 / nit 1: brand and bot volume that could not be checked block green
    nb = T.rate(base_S(buys=None), W)
    nn = T.rate(base_S(brand=None), W)
    nn2 = T.rate(T.signals_radar(dict(clean, sym=None, name=None), W), W)
    check(nb["verdict"] == "watch" and nb["unknown"] == ["bot_volume"] and not nb["push"] and ["unk", "number of buys unknown"] in T.chips(nb, base_S(buys=None), W)
          and nn["verdict"] == "watch" and nn["unknown"] == ["brand_name"] and not nn["push"] and ["unk", "name unknown"] in T.chips(nn, base_S(brand=None), W)
          and nn2["unknown"] == ["brand_name"] and not nn2["push"],
          "no buy count -> watch, 'number of buys unknown'; no symbol and no name -> watch, 'name unknown'; neither is pushed")
    # nit 5 / N1: a report needs its danger list; an error answer or an empty shell is no report
    dl = T.rate(base_S(rcDanger=None), W)
    err = {k: rr(dict(clean, rc=v, holders=[wallet(rng) for _ in range(10)])) for k, v in
           (("error", {"error": "not found"}), ("429", {"error": "Too Many Requests"}), ("shell", {"risks": None, "topHolders": None}))}
    nodanger = T.signals_radar(dict(clean, rc={"topHolders": clean["rc"]["topHolders"]}), W)
    check(dl["verdict"] == "watch" and dl["unknown"] == ["rc_danger"] and not dl["push"] and ["unk", "RugCheck danger list missing"] in T.chips(dl, base_S(rcDanger=None), W)
          and ["ok", "RugCheck report"] not in T.chips(dl, base_S(rcDanger=None), W)
          and all(r["verdict"] == "watch" and "rc_report" in r["unknown"] and not r["push"] for r in err.values())
          and T.rc_summary({"error": "not found"}) is None and T.rc_summary({"risks": 5, "topHolders": True}) is None and T.rc_summary({}) is None
          and nodanger["rcReport"] is True and nodanger["rcDanger"] is None and T.rate(nodanger, W)["unknown"] == ["rc_danger"],
          "a RugCheck report without its danger list -> watch ('RugCheck danger list missing'); an error answer or an empty shell is no "
          "report ('RugCheck pending'), even with the top holders given separately")
    # S3: a memory refilling after a lost cache checks too little; its red flags still count
    mk = lambda n: {"v": 1, "t": NOW - 20 * MIN, "nCoins": n, "common": [], "rug": list(wm["rug"]), "sw": {}}
    sm = rr(dict(clean, wm=mk(499)))
    ok500 = rr(dict(clean, wm=mk(500)))
    rug3 = dict(clean, wm=mk(40))
    rug3["rc"] = dict(clean["rc"], topHolders=[{"owner": w, "pct": 4.0} for w in wm["rug"][:3]] + clean["rc"]["topHolders"][3:])
    small_trap = rr(rug3)
    S_sm = T.signals_radar(dict(clean, wm=mk(499)), W)
    check(sm["verdict"] == "watch" and sm["unknown"] == ["walletmem"] and not sm["push"] and S_sm["wmState"] == "small"
          and ["unk", "wallet memory too small"] in T.chips(sm, S_sm, W) and ok500["verdict"] == "good" and ok500["push"]
          and small_trap["verdict"] == "trap" and small_trap["hard"] == ["rugger_wallets"],
          "a wallet memory from 499 coins is too small (watch, 'wallet memory too small'), from 500 it counts; a small memory still "
          "raises its red flags (3 rugger holders -> trap)")
    # nit 7: the age limit is read from radar_weights.json; without a clock the caller has checked the age (it still needs 500 coins)
    hs = [h["owner"] for h in clean["rc"]["topHolders"]]
    W1 = copy.deepcopy(W)
    W1["thresholds"]["wmMaxAgeH"] = 0.25
    th_old = T.walletmem_lookup(hs, mk(900), NOW, W1)
    th_ok = T.walletmem_lookup(hs, mk(900), NOW, W)
    nc_ok, nc_small = T.walletmem_lookup(hs, mk(900)), T.walletmem_lookup(hs, mk(40))
    check(th_old["state"] == "old" and not th_old["checked"] and th_ok["state"] == "ok" and th_ok["checked"] and nc_ok["checked"] and nc_small["state"] == "small"
          and not nc_small["checked"], "the 3 h limit is thresholds.wmMaxAgeH (20 min old with a 15 min limit -> old); without a clock "
          "the caller has checked the age, the 500-coin floor still holds")
    # nit 6: n counts the checks that ran; a missing report is not one
    n_full = T.rate(base_S(), W)["n"]
    n_norc = T.rate(base_S(rcReport=False, rcDanger=None, rcWarn=None, cluster=None), W)["n"]
    check(n_full == 10 and n_norc == 7, "checks counted: %d with a report (staircase needs 10 candles), %d without one (report, danger "
          "list and cluster not run)" % (n_full, n_norc))


# ---------------------------------------------------------------- T2
def _study_brand():
    src = open(os.path.join(HERE, "research", "rugstudy", "scripts", "build.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BRAND" for t in node.targets):
            return ast.literal_eval(node.value.args[0])
    return None


def _t2(check, W):
    print("== traps T2: points")
    P = W["points"]
    want = {"instant_pool": 3, "rugger_wallets": 3, "rc_danger": 3, "staircase10": 3, "brand_name": 2, "bot_volume": 2, "no_rc_report": 2,
            "no_socials": 1, "holder_cluster": 1, "creator_sold": 1, "pumping_5m": 1, "young_5m": 1, "x_and_paid": -1, "tweet": -1, "lists3": -1}
    check(P == want, "points equal the spec: hard 3, brand 2, 3,000 buys 2, no report 2, each soft 1, young 1, good signs -1")
    good = dict(x="https://x.com/somecoin", paid=True, tweet=True, lists=4.0)
    br = T.rate(base_S(brand=True, **good), W)
    ins = T.rate(base_S(mintToPoolS=5.0, instantPool=None, **good), W)
    gd = T.rate(base_S(**good), W)
    so = T.rate(base_S(socN=0.0, tweet=True), W)
    yg = T.rate(base_S(ageMin=3.0, socN=0.0), W)
    check(br["pts"] == 2 and ins["pts"] == 3 and gd["pts"] == 0 and so["pts"] == 0 and yg["pts"] == 2 and br["plus"] == ["x_and_paid", "tweet", "lists3"],
          "pts = max(sum, hard points) as recommend.py: good signs never cancel a hard trap (brand + 3 good signs %d, instant pool + 3 good signs %d), "
          "they offset soft points (no socials + tweet %d) and never go below 0 (clean + 3 good signs %d)" % (br["pts"], ins["pts"], so["pts"], gd["pts"]))
    sb = _study_brand()
    rx = T.brand_re(W)
    words_hit = ["Grok Agent", "MrBeast coin", "mr beast", "TRUMP", "x ai", "Toy Story"]
    words_miss = ["Groku", "pepe", "metaverse", "elonmuskdog", "applepie"]
    check(sb is not None and W["brand"] == sb and all(rx.search(w) for w in words_hit) and not any(rx.search(w) for w in words_miss),
          "BRAND is the study regex verbatim (word boundaries: 'Grok Agent' yes, 'Groku' no)")
    up = T.rate(base_S(x="https://x.com/a/status/123456", tweet=True, cluster=True, creatorPct=8.0, mc=600_000.0, liq=50_000.0, pumpswap=False, brand=False), W)
    check(up["upside"] == 1 + 1 - 1 - 1 - 1 - 1 and T.rate(base_S(liq=5_000.0, mc=60_000.0, pumpswap=True), W)["upside"] == 0,
          "upside: +X link +tweet, -cluster -creator >5%% -mcap $500k -liq under 15%% (not PumpSwap) -brand (%d)" % up["upside"])


# ---------------------------------------------------------------- T3
def _t3(check, W):
    print("== traps T3: parity with the study's rules.py")
    fn = os.path.join(HERE, "tests", "fixtures", "traps", "study_rows.json.gz")
    with gzip.open(fn, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc["rows"]
    bad = []
    for r in rows:
        S = T.signals_scan(r["y"], r["mint"], r["wm"], pool=r["pool"], W=W)
        rt = T.rate(S, W)
        got = {"hard": sorted(h for h in rt["hard"] if h != "staircase10"), "soft": sorted(rt["soft"]), "checked": S["rcReport"] is True,
               "D": (not rt["hard"]) and S["rcReport"] is True and len(rt["soft"]) <= 1}
        if got != r["expect"]:
            bad.append("%s %s %s: got %s, study %s" % (r["c"], r["rid"], r["a"][:8], got, r["expect"]))
    share = 1 - len(bad) / max(1, len(rows))
    cov = {k: sum(1 for r in rows if k in r["expect"]["hard"] + r["expect"]["soft"]) for k in W["hard"][:5] + W["soft"]}
    for b in bad[:20]:
        print("    mismatch " + b)
    check(len(rows) == 300 and share >= 0.99 and sum(r["expect"]["D"] for r in rows) >= 10 and all(v >= 5 for v in cov.values()),
          "hard / soft / checked / rule D flags equal scripts/rules.py on %d study rows: %.1f%% (%d mismatches; flags seen: %s)"
          % (len(rows), 100 * share, len(bad), ", ".join("%s %d" % kv for kv in cov.items())))


# ---------------------------------------------------------------- T4
def _t4(check):
    print("== traps T4: outcome (the study's G1-G4)")
    base = {"addr": "So1aNaCoin111111111111111111111111111111pump", "dex": "pumpswap", "px": 1.0, "liq": 20_000.0, "mc": 80_000.0}

    def rec(p60, **kw):
        r = dict(base, later={"60": p60}, **kw)
        return T.outcome(r)
    real = rec({"px": 2.5, "liq": 32_000.0})
    dead = rec({"px": 3.0, "liq": 500.0}, peak60={"x": 2.5})
    fake = rec({"px": 3.0, "liq": 8_000.0})
    big = rec({"px": 40.0, "liq": 130_000.0})
    peak_big = rec({"px": 1.1, "liq": 21_000.0}, peak60={"x": 35.0})
    peak_ok = rec({"px": 1.1, "liq": 21_000.0}, peak60={"x": 2.4})
    selfp = T.outcome(dict(base, addr="So1aNaCoin1111111111111111111111111111111111", dex="meteora", mc=21_000.0, later={"60": {"px": 2.5, "liq": 32_000.0}}))
    grew = rec({"px": 2.0, "liq": 64_000.0})
    gone = rec({"gone": True})
    tenth = rec({"px": 0.1, "liq": 3_000.0})
    none = T.outcome(dict(base, later={"30": {"px": 1.0}}))
    check(real == {"rug1h": False, "win1h": True, "x60": 2.5} and peak_ok["win1h"] and not peak_ok["rug1h"], "a real 2.5x (liquidity grew like the price) and a confirmed peak60 of 2.4x are wins")
    check(dead["rug1h"] and not dead["win1h"], "G1: a dead pool (liquidity under $1,000) is a rug and never a win, even with a 2.5x peak before")
    check(not fake["win1h"] and not fake["rug1h"], "G2: 3x with liquidity that did not follow the price is no win")
    check(not big["win1h"] and not peak_big["win1h"], "G3: over 30x (price or peak) is no win")
    check(not selfp["win1h"] and not grew["win1h"], "G4: a self-priced pool (liquidity 95% of mcap, no pump mint, not PumpSwap; or liquidity that grew like the price) is no win")
    check(gone == {"rug1h": True, "win1h": False, "x60": 0.0} and tenth["rug1h"] and none == {"rug1h": None, "win1h": None, "x60": None},
          "gone -> rug (x60 0); 0.1x -> rug; no 60-minute price -> no outcome yet")


# ---------------------------------------------------------------- T5
def _records(rng, n_days, per_hour, sig_fn, start):
    out = []
    for h in range(n_days * 24):
        for i in range(per_hour):
            t = start + h * H + rng.randrange(H)
            S, rug = sig_fn(rng, t)
            out.append({"addr": "R%d-%05d%02dpump" % (start // H, h, i), "first": t, "sig": S, "out": {"rug1h": rug, "win1h": False, "x60": 0.0 if rug else 1.0}})
    return out


def _t5(check, W):
    print("== traps T5: fit (the radar model)")
    rng = random.Random(5)
    start = NOW - 6 * DAY

    def planted(rng, t):
        dd = rng.random() < 0.3
        soc0 = rng.random() < 0.2
        S = base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0, socN=0.0 if soc0 else 2.0)
        return S, rng.random() < (0.6 if dd else 0.12)
    recs = _records(rng, 6, 5, planted, start)
    few, rep_few = T.fit(recs[:299], W, NOW)
    check(few is None and rep_few["from"] == "prior" and rep_few["n"] == 299 and rep_few["why"] == "radar data 299 of 300 needed",
          "fewer than 300 records with an outcome -> the study prior ('%s')" % rep_few["why"])
    t0 = time.time()
    W2, rep = T.fit(recs, W, NOW)
    secs = time.time() - t0
    pts = (W2 or {}).get("points", {}).get("dev_dead")
    check(W2 is not None and rep["from"] == "learned" and "dev_dead" in W2["soft"] and pts is not None and 1 <= pts <= 2 and W2["hard"] == W["hard"]
          and rep["changes"]["soft"] == {"dev_dead": pts} and not rep["changes"]["zero"] and rep["auc"] >= rep["aucPrior"],
          "a measured signal true in both halves becomes soft with %s points (AUC %.2f vs %.2f, %.1f s); hard unchanged" % (pts, rep.get("auc") or 0, rep.get("aucPrior") or 0, secs))
    Wl = T.load_weights(model=rep)
    Wp = T.load_weights(model=dict(rep, prior="another prior"))
    Wx = T.load_weights(model=dict(rep, changes={"soft": {"instant_pool": 2, "fund_cluster": 9, "bundle_slot": 2}, "zero": ["rc_danger", "instant_pool"]}))
    check(Wl["soft"] == W["soft"] + ["dev_dead"] and Wp["soft"] == W["soft"] and Wx["hard"] == W["hard"] and Wx["soft"] == W["soft"] + ["bundle_slot"]
          and Wx["points"]["instant_pool"] == 3 and "fund_cluster" not in Wx["soft"],
          "model.json is applied only when learned on this prior; it can never add or remove a hard signal or give more than 2 points")

    def reversed_soc(rng, t):
        soc0 = rng.random() < 0.4
        return base_S(socN=0.0 if soc0 else 2.0), rng.random() < (0.05 if soc0 else 0.35)
    W3, rep3 = T.fit(_records(random.Random(6), 6, 5, reversed_soc, start), W, NOW)
    check(rep3["changes"]["zero"] == ["no_socials"] and (W3 is None or ("no_socials" not in W3["soft"] and W3["points"]["no_socials"] == 0)),
          "a V soft signal whose effect reverses in both halves goes to 0 (%s)" % rep3["why"])

    def extreme(rng, t):
        dd = rng.random() < 0.5
        return base_S(fundN=5.0 if dd else 0.0), (rng.random() < 0.97) if dd else (rng.random() < 0.02)
    W4, rep4 = T.fit(_records(random.Random(7), 6, 5, extreme, start), W, NOW)
    check(W4 is not None and W4["points"].get("fund_cluster") == 2 and "fund_cluster" in W4["soft"] and "fund_cluster" not in W4["hard"] and W4["hard"] == W["hard"],
          "an extreme measured signal is capped at soft with 2 points, never hard")

    def flips(rng, t):
        dd = rng.random() < 0.3
        S = base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0)
        if t >= NOW - 2 * DAY:
            return S, rng.random() < (0.02 if dd else 0.5)
        return S, rng.random() < (0.6 if dd else 0.12)
    W5, rep5 = T.fit(_records(random.Random(8), 6, 5, flips, start), W, NOW)
    check(W5 is None and rep5["from"] == "prior" and rep5["changes"]["soft"].get("dev_dead") and rep5["why"].startswith("study prior kept: walk-forward"),
          "the walk-forward guard refuses a signal that reverses in the last 2 days ('%s')" % rep5["why"])
    _t5_gates(check, W, start)


def _t5_gates(check, W, start):
    """Each gate of the fit on its own (review fix1, SF2): the decision table, Benjamini-Hochberg, null and one-half effects, the
    good-band guard, the train/test sizes, one coin counted once."""
    cfg = W["fit"]
    row = lambda kind, q, lo, hi, ratio, h1, h2: {"kind": kind, "q": q, "lo": lo, "hi": hi, "ratio": ratio, "halves": [h1, h2]}
    table = [(row("M", 0.01, 1.4, 4.0, 2.2, 2.0, 2.5), ("soft", 2)), (row("M", 0.01, 1.1, 2.0, 1.5, 1.4, 1.6), ("soft", 1)),
             (row("M", 0.05, 1.4, 4.0, 2.2, 2.0, 2.5), ("none", 0)), (row("M", 0.01, 1.0, 4.0, 2.2, 2.0, 2.5), ("none", 0)),
             (row("M", 0.01, 1.4, 4.0, 2.2, 2.0, 1.0), ("none", 0)), (row("M", 0.01, 1.4, 4.0, 2.2, 0.9, 2.5), ("none", 0)),
             (row("M", 0.01, 1.05, 1.5, 1.2, 1.1, 1.3), ("none", 0)), (row("M", 0.01, 1.4, 4.0, 20.0, 9.0, 30.0), ("soft", 2)),
             (row("M", 0.01, 0.2, 0.7, 0.4, 0.5, 0.3), ("none", 0)), (row("V", 0.01, 0.2, 0.7, 0.4, 0.5, 0.3), ("zero", 0)),
             (row("V", 0.06, 0.2, 0.7, 0.4, 0.5, 0.3), ("none", 0)), (row("V", 0.01, 0.2, 1.0, 0.4, 0.5, 0.3), ("none", 0)),
             (row("V", 0.01, 0.2, 0.7, 0.4, 1.0, 0.3), ("none", 0)), (row("V", 0.01, 0.2, 0.7, 0.4, 0.5, 1.2), ("none", 0)),
             (row("V", 0.01, 1.4, 4.0, 2.2, 2.0, 2.5), ("none", 0)), (row("M", None, 1.4, 4.0, 2.2, 2.0, 2.5), ("none", 0))]
    got = [T.decide(r, cfg) for r, _ in table]
    check(got == [w for _, w in table], "the fit's decision: a measured signal needs q < 0.05, interval low > 1, both halves above 1 and "
          "round(2 ln ratio) >= 1 (capped at 2); a V soft signal goes to 0 only with q < 0.05, interval high < 1 and both halves below 1 "
          "(%d cases%s)" % (len(table), "" if got == [w for _, w in table] else ": got %s" % got))
    q = [round(x, 4) for x in T._bh([0.01, 0.04, 0.03, 0.5])]
    check(q == [0.04, 0.0533, 0.0533, 0.5], "Benjamini-Hochberg: p 0.01 / 0.04 / 0.03 / 0.5 -> q %s" % q)

    def many(rng, t):                     # 10 signals tested: 9 without any effect, dev_dead weakly up (rug 30% vs 21%)
        dd = rng.random() < 0.4
        S = base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0, devAgeH=rng.choice([2.0, 100.0]), snip30=rng.choice([0.1, 0.5]),
                   slotN=rng.choice([1.0, 5.0]), freshN=rng.choice([0.0, 5.0]), fundN=rng.choice([0.0, 4.0]), xUsed=rng.choice([0.0, 2.0]),
                   xKind="account", socN=rng.choice([0.0, 2.0, 2.0]), creatorSold=rng.random() < 0.3, m5=rng.choice([5.0, 30.0, 5.0]))
        return S, rng.random() < (0.30 if dd else 0.21)
    Wm, repm = T.fit(_records(random.Random(116), 6, 5, many, start), W, NOW)
    dd = {r["signal"]: r for r in repm["signals"]}.get("dev_dead") or {}
    tested = [r for r in repm["signals"] if r["q"] is not None]
    check(Wm is None and repm["changes"] == {"soft": {}, "zero": []} and len(tested) == 10 and dd.get("p", 1) < 0.05 <= dd.get("q", 0)
          and dd.get("lo", 0) > 1 and all(h > 1 for h in dd.get("halves") or [0]),
          "null signals stay at weight 0 (%d tested); a weak one (p %.3f, interval low %.2f, both halves up) is kept at 0 by "
          "Benjamini-Hochberg (q %.2f)" % (len(tested), dd.get("p") or 0, dd.get("lo") or 0, dd.get("q") or 0))

    def one_half(rng, t):                 # dev_dead rugs 7x more in the first half of the training days only
        dd = rng.random() < 0.3
        S = base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0)
        if t < start + 2 * DAY:
            return S, rng.random() < (0.7 if dd else 0.1)
        return S, rng.random() < (0.18 if dd else 0.2)
    Wh, reph = T.fit(_records(random.Random(20), 6, 5, one_half, start), W, NOW)
    hh = {r["signal"]: r for r in reph["signals"]}.get("dev_dead") or {}
    check(Wh is None and reph["changes"]["soft"] == {} and (hh.get("q") or 1) < 0.05 and (hh.get("lo") or 0) > 1
          and (hh.get("halves") or [0, 9])[0] > 1 > (hh.get("halves") or [0, 9])[1],
          "an effect in one time half only (ratios %s) stays at weight 0 although q %.4f and interval low %.2f pass"
          % (hh.get("halves"), hh.get("q") or 0, hh.get("lo") or 0))

    def band(rng, t):                     # dev_dead holds up in training; in the last 2 days its coins without socials never rug
        dd = rng.random() < 0.4
        soc0 = rng.random() < 0.5
        S = base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0, socN=0.0 if soc0 else 2.0)
        if t < NOW - 2 * DAY:
            return S, rng.random() < (0.6 if dd else 0.12)
        return S, rng.random() < ((0.0 if soc0 else 0.95) if dd else 0.4)
    Wb, repb = T.fit(_records(random.Random(31), 6, 5, band, start), W, NOW)
    g = repb.get("good") or {}
    check(Wb is None and repb["changes"]["soft"].get("dev_dead") and repb["auc"] >= repb["aucPrior"] - cfg["aucSlack"]
          and repb["why"].startswith("study prior kept: the good band rugged more") and g["learned"]["rate"] > g["prior"]["hi"],
          "the walk-forward guard refuses a model whose good band rugs more (learned %.0f%% vs the prior's %.0f%%, interval to %.0f%%) "
          "although its AUC is fine (%.2f vs %.2f)" % (100 * g["learned"]["rate"], 100 * g["prior"]["rate"], 100 * g["prior"]["hi"],
                                                      repb["auc"], repb["aucPrior"]))

    def plain(rng, t):
        dd = rng.random() < 0.3
        return base_S(devN=10.0 if dd else 1.0, devDead=10.0 if dd else 0.0), rng.random() < (0.6 if dd else 0.12)
    recent = _records(random.Random(9), 2, 7, plain, NOW - 2 * DAY)
    old = _records(random.Random(10), 4, 5, plain, NOW - 6 * DAY)
    few_test = old[:288] + _records(random.Random(11), 1, 1, plain, NOW - DAY)              # 288 before, 24 in the last 2 days
    few_train = _records(random.Random(12), 1, 5, plain, NOW - 3 * DAY) + recent[:200]       # 120 before, 200 in them
    outs = [T.fit(x, W, NOW) for x in (recent, old, few_test, few_train)]
    sizes = [(r["nTrain"], r["nTest"]) for _, r in outs]
    check(all(w is None and r["why"].startswith("walk-forward needs") for w, r in outs) and sizes == [(0, 336), (480, 0), (288, 24), (120, 200)],
          "the walk-forward needs %d calls before the last 2 days and %d in them: recent-only, old-only, too few recent and too few old "
          "records keep the prior (%s)" % (cfg["minTrain"], cfg["minTest"], sizes))
    recs = _records(random.Random(5), 6, 5, plain, start)
    dup = [dict(r, first=r["first"] + 30 * MIN) for r in recs[::2]]
    _, rep1 = T.fit(recs, W, NOW)
    _, rep2 = T.fit(recs + dup, W, NOW)
    check(rep2["n"] == rep1["n"] == len(recs) and rep2["signals"] == rep1["signals"],
          "a coin recorded in two hour docs counts once (%d records + %d copies -> n %d, same test)" % (len(recs), len(dup), rep2["n"]))


# ---------------------------------------------------------------- T6
def _t6(check, W):
    print("== traps T6: X links")
    acc = {T.norm_x(u) for u in ("https://twitter.com/FooCoin/", "https://www.x.com/foocoin?lang=en", "http://mobile.twitter.com/FOOCOIN#top", "x.com/foocoin/")}
    tw = {T.norm_x(u) for u in ("https://x.com/Bar/status/18001234567?s=20", "https://twitter.com/someone/status/18001234567/photo/1", "https://x.com/i/web/status/18001234567")}
    cm = T.norm_x("https://x.com/i/communities/1789012345/")
    check(acc == {("account", "x.com/foocoin")} and tw == {("tweet", "x.com/i/status/18001234567")} and cm == ("community", "x.com/i/communities/1789012345"),
          "norm_x: x.com / twitter.com, www, mobile, query, fragment and trailing slash are one key; tweet vs account vs community")
    check(all(T.norm_x(u) is None for u in ("https://x.com/search?q=pepe", "https://x.com/home", "https://example.com/foocoin", "", None, "https://x.com/",
                                           "https://x.com/foo/status/abc", "javascript:alert(1)")),
          "norm_x: searches, home, other sites, empty and broken links -> None")
    links, a, b, c = {}, "A" * 40 + "pump", "B" * 40 + "pump", "C" * 40 + "pump"
    T.xlinks_add(links, "https://x.com/FooCoin", a, NOW - 30 * MIN)
    T.xlinks_add(links, "https://twitter.com/foocoin/", b, NOW - 5 * MIN)
    T.xlinks_add(links, "https://x.com/foocoin", c, NOW)
    T.xlinks_add(links, "https://x.com/foocoin", c, NOW + 5 * MIN)
    rc_ = T.x_reuse("https://x.com/foocoin", c, NOW, links)
    ra = T.x_reuse("https://x.com/foocoin", a, NOW - 30 * MIN, links)
    rb = T.x_reuse("https://x.com/foocoin", b, NOW - 5 * MIN, links)
    e = links["x.com/foocoin"]
    check(rc_["used"] == 1 and ra["used"] == 0 and rb["used"] == 1 and e[0] == a and e[2] == 3 and e[5][-1] == [c, NOW],
          "reuse excludes the coin itself and needs a 10-minute gap (C: %d older, A: %d, B: %d; 3 coins indexed once each)" % (rc_["used"], ra["used"], rb["used"]))
    T.xlinks_add(links, "https://x.com/someone/status/18001234567", a, NOW - H)
    T.xlinks_add(links, "https://x.com/other/status/18001234567", b, NOW - 2 * MIN)
    rt = T.x_reuse("https://twitter.com/x/status/18001234567", c, NOW, links)
    S = base_S(x="https://x.com/z/status/18001234567", xKind="tweet", tweet=True, xUsed=rt["used"], tweetShared=rt["shared"])
    rr = T.rate(S, W)
    check(rt["used"] == 0 and rt["shared"] == 2 and rr["info"] == ["tweet_shared"] and ["info", "3 coins off the same tweet"] in T.chips(rr, S, W)
          and rr["verdict"] == "good" and "x_copied" not in rr["info"],
          "a shared tweet is an info chip ('3 coins off the same tweet'), never 'X link copied'")
    many = {}
    coins12 = ["%s%02dpump" % ("D" * 38, i) for i in range(12)]
    ns = []
    for _ in range(3):                    # the feed adds every coin again each hour (pf rows and pairs.json, then the merge)
        for i, a in enumerate(coins12):
            T.xlinks_add(many, "https://x.com/serial", a, NOW - (60 - i) * MIN)
            T.xlinks_add(many, "https://twitter.com/Serial/", a, NOW - (60 - i) * MIN)
        ns.append(many["x.com/serial"][2])
    back = {}
    for _ in range(2):
        for i, a in reversed(list(enumerate(coins12))):
            T.xlinks_add(back, "https://x.com/serial", a, NOW - (60 - i) * MIN)
    rm = T.x_reuse("https://x.com/serial", "Z" * 40 + "pump", NOW, many)
    check(rm["used"] == T.XUSES_MAX and ns == [8, 8, 8] and len(many["x.com/serial"][5]) == T.XUSES_MAX and back["x.com/serial"][2] >= 8
          and back["x.com/serial"][5] == many["x.com/serial"][5] and "8+ older coins" in T._text("x_copied", base_S(xUsed=8.0, xKind="account"), W)
          and T._text("tweet_shared", base_S(tweetShared=8.0), W) == "8+ coins off the same tweet"
          and T._text("tweet_shared", base_S(tweetShared=6.0), W) == "7 coins off the same tweet",
          "a link used by 12 coins keeps the earliest %d; its coin count stays %s when the same coins come again every hour (it read 16, "
          "24, 32 before); '8+ older coins', '8+ coins off the same tweet'" % (T.XUSES_MAX, ns))
    # SF1: the coin's own creation time is the reference, not its first sighting
    orig, cp = "O" * 40 + "pump", "P" * 40 + "pump"
    lk = {}
    T.xlinks_add(lk, "https://x.com/origcoin", orig, NOW - 120 * MIN)
    T.xlinks_add(lk, "https://x.com/origcoin", cp, NOW - 60 * MIN)
    base = {"now": NOW, "x": "https://x.com/origcoin", "xlinks": lk, "pool": NOW - 5 * MIN, "first": NOW - 4 * MIN}
    So = T.signals_radar(dict(base, addr=orig, mint=NOW - 120 * MIN), W)
    So2 = T.signals_radar(dict(base, addr=orig, mint=None), W)             # mint unknown: its own entry in the index
    Sc = T.signals_radar(dict(base, addr=cp, mint=NOW - 60 * MIN), W)
    ro, rc2 = T.rate(base_S(xUsed=So["xUsed"], xKind=So["xKind"]), W), T.rate(base_S(xUsed=Sc["xUsed"], xKind=Sc["xKind"]), W)
    check(So["xUsed"] == 0 and So2["xUsed"] == 0 and Sc["xUsed"] == 1 and "x_copied" not in ro["info"] and "x_copied" in rc2["info"]
          and ["info", "X account used by 1 older coin"] in T.chips(rc2, base_S(xUsed=1.0, xKind="account"), W),
          "the original (minted 2 h ago, first seen now) is not 'copied' by a coin minted an hour after it; the copy is (%d / %d / %d)"
          % (So["xUsed"], So2["xUsed"], Sc["xUsed"]))
    own = {}
    T.xlinks_add(own, "https://x.com/curvecoin", c, NOW - 90 * MIN)           # the coin's own entry, long before its first sighting
    T.xlinks_add(own, "https://x.com/curvecoin", b, NOW - 30 * MIN)           # a younger coin with the same link
    r_own = T.x_reuse("https://x.com/curvecoin", c, NOW, own)
    r_b = T.x_reuse("https://x.com/curvecoin", b, NOW, own)
    check(r_own["used"] == 0 and r_b["used"] == 1, "a coin that spent 90 min on the curve: its own index entry is never an 'older coin', "
          "nor is a younger coin (%d); the younger one sees it (%d)" % (r_own["used"], r_b["used"]))
    bad = {"x.com/junk": "junk", "x.com/junk2": ["A", "x", "n", "account", 0, [[1, 2], "q", ["Q" * 44]]]}
    kj = T.xlinks_add(bad, "https://x.com/junk", a, NOW)
    kj2 = T.xlinks_add(bad, "https://x.com/junk2", a, NOW)
    check(kj == "x.com/junk" and bad[kj][5] == [[a, NOW]] and bad[kj2][5] == [[a, NOW]] and T.x_reuse("https://x.com/junk2", b, NOW + H, bad)["used"] == 1
          and T.xlinks_add(bad, None, a, NOW) is None and T.xlinks_add(bad, "https://x.com/junk", None, NOW) is None,
          "a malformed index entry is rebuilt, never a crash")


# ---------------------------------------------------------------- T7
def _snap_doc(t0, t1, coins):
    return {"t0": t0, "t": t1, "rule": "m9-2h", "coins": coins}


def _mk_mb(d, rng, now):
    """A small scan folder: scored snapshots (memesnapres), pump.fun rows, pairs.json and an older xlinks feed."""
    os.makedirs(os.path.join(d, "db", "memesnapres"))
    common = wallet(rng)
    early_rug = [wallet(rng) for _ in range(3)]
    late_rug = [wallet(rng) for _ in range(2)]
    ok_w = wallet(rng)
    filler = [wallet(rng) for _ in range(60)]
    docs = []
    # 30 ordinary coins with the common program account among their holders, half of them gone, results known
    for i in range(30):
        hs = [common] + rng.sample(filler, 3) + (late_rug if i == 0 else [])
        docs.append(("2026-10-12T%02d%02d-1" % (i % 24, i), _snap_doc(now - 30 * H + i * MIN, now - 27 * H + i * MIN,
                     [{"a": wallet(rng, "pump"), "s": "C%d" % i, "mult": 0.05 if i % 2 else 1.4, "gone": False, "eur": -18.0 if i % 2 else 6.0,
                       "rc": {"holders": hs}, "f": {"ageH": 0.5}}])))
    docs.append(("2026-10-13T0100-1", _snap_doc(now - 5 * H, now - 3 * H, [{"a": wallet(rng, "pump"), "s": "RUG1", "mult": 0.0, "gone": True, "eur": -20.0,
                                                                           "rc": {"holders": early_rug + [common]}, "f": {}}])))
    docs.append(("2026-10-13T0200-1", _snap_doc(now - 1 * H, now + 1 * H, [{"a": wallet(rng, "pump"), "s": "RUG2", "mult": 0.01, "gone": False, "eur": -20.0,
                                                                           "rc": {"holders": late_rug}, "f": {}}])))
    docs.append(("2026-10-13T0300-1", _snap_doc(now - 6 * H, now - 4 * H, [{"a": wallet(rng, "pump"), "s": "FINE", "mult": 1.8, "gone": False, "eur": 15.0,
                                                                           "rc": {"holders": [ok_w] + early_rug[:1] + late_rug}, "f": {}},
                                                                          {"a": wallet(rng, "pump"), "s": "ODD", "mult": 1.0, "eur": 0.0, "rc": {"holders": 7}},
                                                                          {"a": wallet(rng, "pump"), "s": "ODD2", "mult": 1.0, "eur": 0.0, "rc": "x"}])))
    # outside the 14-day window: a dated file that is not even opened, and an undated one whose t0 is too old
    old_rug = [wallet(rng) for _ in range(3)]
    docs.append(("2026-09-20T0100-1", _snap_doc(now - 24 * DAY, now - 24 * DAY + 2 * H, [{"a": wallet(rng, "pump"), "s": "OLD1", "mult": 0.0, "gone": True,
                                                                                         "eur": -20.0, "rc": {"holders": old_rug}}])))
    docs.append(("zz-undated", _snap_doc(now - 20 * DAY, now - 20 * DAY + 2 * H, [{"a": wallet(rng, "pump"), "s": "OLD2", "mult": 0.0, "gone": True,
                                                                                  "eur": -20.0, "rc": {"holders": old_rug}}])))
    for name, doc in docs:
        with open(os.path.join(d, "db", "memesnapres", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
    os.makedirs(os.path.join(d, "pf"))
    pf_a, pf_b = wallet(rng, "pump"), wallet(rng, "pump")
    with open(os.path.join(d, "pf", "new.txt"), "w", encoding="utf-8") as f:
        f.write("%s|AAA|Aaa|50000|50000|60000|3|false|false|%d|https://x.com/AaaCoin|https://aaa.example|null\n" % (pf_a, (now - 2 * H) // 1000))
        f.write("%s|BBB|Bbb|40000|40000|40000|0|false|false|%d|https://twitter.com/aaacoin/|null|null\n" % (pf_b, (now - 20 * MIN) // 1000))
    pairs = [{"address": pf_a, "symbol": "AAA", "marketCap": 50_000, "xUrl": "https://x.com/AaaCoin", "pairCreatedAt": now - 90 * MIN, "pf": {"createdAt": str((now - 2 * H) // 1000)}},
             {"address": wallet(rng, "pump"), "symbol": "aaa", "marketCap": 900_000, "pairCreatedAt": now - 30 * H},
             {"address": wallet(rng, "pump"), "symbol": "ZED", "marketCap": 12_000, "xUrl": "https://x.com/zed/status/18009999999", "pairCreatedAt": now - 10 * MIN},
             {"address": wallet(rng, "pump"), "symbol": "LLC", "marketCap": 30_000, "xUrl": "https://x.com/llcoin", "pairCreatedAt": now - 5 * MIN,
              "pf": [1, 2], "ll": {"createdAt": "2026-10-14T00:00:00"}}]
    with open(os.path.join(d, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump(pairs, f)
    old_links = {"x.com/oldcoin": ["O" * 40 + "pump", now - 40 * DAY, 1, "account", now - 35 * DAY, [["O" * 40 + "pump", now - 40 * DAY]]],
                 "x.com/keepcoin": ["K" * 40 + "pump", now - 20 * DAY, 1, "account", now - 20 * DAY, [["K" * 40 + "pump", now - 20 * DAY]]]}
    with open(os.path.join(d, "xlinks.json.gz"), "wb") as f:
        f.write(gzip.compress(json.dumps({"v": 1, "t": now - H, "links": old_links}).encode(), mtime=0))
    return {"common": common, "early": early_rug, "late": late_rug, "ok": ok_w, "pf_a": pf_a, "pf_b": pf_b, "old": old_rug}


def _t7_xlinks_rerun(check, tmp, rng):
    """S1/SF4: the scan runs the feed every hour on its own previous output; a link's coin count must not grow by itself."""
    mb = os.path.join(tmp, "mbx")
    os.makedirs(os.path.join(mb, "db", "memesnapres"))
    os.makedirs(os.path.join(mb, "pf"))
    coins = [wallet(rng, "pump") for _ in range(12)]
    with open(os.path.join(mb, "pf", "new.txt"), "w", encoding="utf-8") as f:
        for i, a in enumerate(coins):
            f.write("%s|SER|Serial %d|50000|50000|60000|3|false|false|%d|https://x.com/SerialCoin|null|null\n" % (a, i, (NOW - (90 - i) * MIN) // 1000))
    with open(os.path.join(mb, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump([{"address": a, "symbol": "SER", "marketCap": 50_000, "xUrl": "https://twitter.com/serialcoin", "pairCreatedAt": NOW - (80 - i) * MIN,
                    "pf": {"createdAt": (NOW - (90 - i) * MIN) // 1000}} for i, a in enumerate(coins)], f)
    ns, blobs = [], []
    for run in range(3):
        out = os.path.join(tmp, "fx%d" % run)
        T.feed(mb, out, NOW + run * H)
        shutil.copy(os.path.join(out, "xlinks.json.gz"), os.path.join(mb, "xlinks.json.gz"))
        e = json.load(gzip.open(os.path.join(out, "xlinks.json.gz"), "rt"))["links"]["x.com/serialcoin"]
        ns.append(e[2])
        blobs.append(json.dumps(e[5]))
    check(len(set(ns)) == 1 and 8 <= ns[0] <= 12 and len(set(blobs)) == 1, "three hourly feeds, each merging the last one's xlinks: a link "
          "of 12 coins keeps its count (%s: the coins that entered the earliest 8, at most the 12 there are) and the same earliest 8 (it "
          "grew 16, 24, 32 before)" % ns)


def _t7(check, W, tmp):
    print("== traps T7: feed (wallet memory, X links, copy table)")
    import memebot as M
    rng = random.Random(77)
    mb = os.path.join(tmp, "mb")
    k = _mk_mb(mb, rng, NOW)
    t0 = time.time()
    meta = T.feed(mb, os.path.join(tmp, "f1"), NOW)
    secs = time.time() - t0
    wm = json.load(gzip.open(os.path.join(tmp, "f1", "walletmem.json.gz"), "rt"))
    check(k["common"] in wm["common"] and k["common"] not in wm["rug"] and wm["nCoins"] == 33,
          "common accounts (top holder of more than max(20, 1%%) of %d coins) are listed and never counted as rugger wallets" % wm["nCoins"])
    check(set(k["early"]) <= set(wm["rug"]) and not set(k["late"]) & set(wm["rug"]) and k["ok"] not in wm["rug"],
          "no look-ahead: a rug whose result is known only after 'now' is not in the memory yet")
    late_avg = {w: wm["sw"].get(w) for w in k["late"]}
    meta_later = T.feed(mb, os.path.join(tmp, "f3"), NOW + 2 * H)
    wm3 = json.load(gzip.open(os.path.join(tmp, "f3", "walletmem.json.gz"), "rt"))
    late_avg3 = {w: wm3["sw"].get(w) for w in k["late"]}
    check(set(late_avg.values()) == {10.5} and set(late_avg3.values()) == {round((6.0 + 15.0 - 20.0) / 3, 2)},
          "no look-ahead in sw either: the late rug's holders also held 2 earlier coins; at 'now' their average is those two (+10.50), "
          "two hours later it includes the rug (%s)" % sorted(set(late_avg3.values())))
    look = T.walletmem_lookup([k["common"]] + k["early"], dict(wm, rug=wm["rug"] + [k["common"]]), NOW + 10 * MIN)
    look9 = T.walletmem_lookup([k["common"]] + k["early"], dict(wm, rug=wm["rug"] + [k["common"]], nCoins=900), NOW + 10 * MIN)
    check(set(k["late"]) <= set(wm3["rug"]) and look["rugHolders"] == 3 and look["state"] == "small" and look["checked"] is False
          and look9["state"] == "ok" and look9["checked"] is True and look9["rugHolders"] == 3,
          "two hours later the late rug is known; the lookup skips the common account even if it were listed (3 rugger holders); this "
          "memory of 33 coins is 'too small' (not checked) yet raises the flag")
    check(not set(k["old"]) & set(wm["rug"]) and meta["days"] == T.FEED_DAYS and meta["snapSkipped"] == 1 and meta["snapFiles"] == 34,
          "the feed reads the newest %d days: a file dated 24 days ago is not opened, an undated one with an old snapshot time is left "
          "out (%d files read, %d skipped)" % (meta["days"], meta["snapFiles"], meta["snapSkipped"]))
    wide = T.feed(mb, os.path.join(tmp, "f4"), NOW, days=30)
    wmw = json.load(gzip.open(os.path.join(tmp, "f4", "walletmem.json.gz"), "rt"))
    check(wmw["nCoins"] == 35 and set(k["old"]) <= set(wmw["rug"]) and wide["snapSkipped"] == 0,
          "with --days 30 the older snapshots count again (%d coins)" % wmw["nCoins"])
    done = {n: dict(dd, coins=[c for c in dd["coins"] if isinstance(c.get("rc"), dict) and isinstance(c["rc"].get("holders"), list)])
            for n, dd in M.load_docs(mb, "memesnapres").items() if dd["t"] <= NOW and dd["t0"] >= NOW - T.FEED_DAYS * DAY}   # memebot crashes on odd holders
    orig = M.load_docs
    M.load_docs = lambda d_, c_: done if c_ == "memesnapres" else orig(d_, c_)
    try:
        table = {w: v["avg"] for w, v in M.wallet_table(mb).items()}
    finally:
        M.load_docs = orig
    check(set(wm["sw"]) == set(table) and all(abs(wm["sw"][w] - table[w]) <= 0.0100001 for w in table) and len(table) > 0,
          "sw is memebot.wallet_table's average on the results known at 'now' (%d wallets; read in file-name order, so a sum may round 0.01 apart)" % len(table))
    xl = json.load(gzip.open(os.path.join(tmp, "f1", "xlinks.json.gz"), "rt"))["links"]
    sm = json.load(gzip.open(os.path.join(tmp, "f1", "symmc.json.gz"), "rt"))["sym"]
    check("x.com/aaacoin" in xl and xl["x.com/aaacoin"][0] == k["pf_a"] and xl["x.com/aaacoin"][2] == 2 and "x.com/keepcoin" in xl and "x.com/oldcoin" not in xl
          and "x.com/i/status/18009999999" in xl and sm == {"AAA": 900_000, "ZED": 12_000, "LLC": 30_000} and xl["x.com/llcoin"][1] == 1791936000000,
          "xlinks from pf/*.txt and pairs.json merged with the previous feed (30 days kept); symmc = the copy gate's max market cap per ticker; "
          "odd inputs (holders as a number, pf as a list) are skipped; a LaunchLab time without a zone is UTC")
    T.feed(mb, os.path.join(tmp, "f2"), NOW)
    same = all(open(os.path.join(tmp, "f1", n), "rb").read() == open(os.path.join(tmp, "f2", n), "rb").read()
               for n in ("walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz"))
    fb = meta["files"]
    check(same and all(fb[n]["bytes"] > 0 for n in fb) and set(fb) == {"walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz"} and meta["secs"] < 60,
          "deterministic: two runs give the same bytes; sizes reported (%s; %.2f s)" % (", ".join("%s %d B" % (n, fb[n]["bytes"]) for n in sorted(fb)), secs))
    _t7_xlinks_rerun(check, tmp, rng)
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        T.feed(mb, os.path.join(tmp, "f5"), NOW)
        tz_same = all(open(os.path.join(tmp, "f1", n), "rb").read() == open(os.path.join(tmp, "f5", n), "rb").read()
                      for n in ("walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz"))
        tz_parse = T.parse_ms("2026-10-14T00:00:00") == 1791936000000
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
    check(tz_same and tz_parse, "the feed's bytes do not depend on the machine's time zone (an ISO time without a zone is UTC)")
    out = os.path.join(tmp, "cli")
    t0 = time.time()
    p = subprocess.run([PY, os.path.join(HERE, "traps.py"), "feed", "--dir", mb, "--out", out, "--now", str(NOW)], capture_output=True, text=True, timeout=120)
    ok_json = False
    try:
        ok_json = json.loads(p.stdout.strip().splitlines()[-1])["files"]["walletmem.json.gz"]["nCoins"] == 33
    except (ValueError, KeyError, IndexError):
        pass
    files = sorted(os.listdir(out)) if os.path.isdir(out) else []
    check(p.returncode == 0 and ok_json and files == ["meta.json", "symmc.json.gz", "walletmem.json.gz", "xlinks.json.gz"] and time.time() - t0 < 60,
          "python3 traps.py feed --dir mb --out feed --now <ms> writes the four files and prints its meta line (%.1f s)" % (time.time() - t0))


# ---------------------------------------------------------------- more: staircase, RugCheck parity, chips, the young tab
def _extras(check, W, rng, tmp):
    print("== traps: staircase, RugCheck reading, the trap-check line")
    stair = [1.0 * 1.03 ** i for i in range(10)]
    organic = [1.0, 1.1, 1.25, 1.06, 1.15, 1.3, 1.12, 1.28, 1.4, 1.35]
    flat = [1.0, 1.01, 0.99, 1.0, 1.02, 1.0, 0.98, 1.01, 1.0, 1.0]
    nine = stair[:9]
    candles = [[i, 1.0 * 1.03 ** (i - 1) if i else 1.0, 0, 0, 1.0 * 1.03 ** i] for i in range(10)]
    s1, s2, s3, s4, s5 = (T.staircase(x) for x in (stair, organic, flat, nine, candles))
    check(s1["stair"] and not s2["stair"] and not s3["stair"] and not s4["stair"] and s4["n"] == 9 and s5["stair"] and s5["green"] == 0.9 and s2["pull"] > 0.1,
          "staircase: steady small green steps over 10 candles yes; organic pullbacks, flat, 9 candles no")
    e9 = T.rate(base_S(stair=s4), W)
    check(e9["verdict"] == "good" and e9["info"] == ["staircase_early"] and ["info", "staircase so far (9 min)"] in T.chips(e9, base_S(stair=s4), W),
          "6-9 candles: a grey 'staircase so far (9 min)', never the hard trap")
    import fetch as F
    import memebot as M
    rep = {"risks": [{"name": "Freeze Authority still enabled", "level": "danger"}, {"name": "Low Liquidity", "level": "warn"},
                     {"name": "High holder correlation", "level": "warn"}],
           "topHolders": [{"owner": wallet(rng), "address": wallet(rng), "pct": 5.0 - i * 0.2} for i in range(20)],
           "graphInsidersDetected": 232, "token": {"supply": 1e9}, "creatorBalance": 3e7, "totalHolders": 410}
    mint = wallet(rng, "pump")
    rd = os.path.join(tmp, "rc")
    os.makedirs(os.path.join(rd, "risk"))
    with open(os.path.join(rd, "risk", "reports_1.txt"), "w", encoding="utf-8") as f:
        f.write(F.rc_row(mint, rep) + "\n")
    rk = M.load_risk(rd)[mint]
    sm = T.rc_summary(rep)
    S = T.blank_signals()
    T._rc_into(S, sm)
    check(sm["danger"] == rk["danger"] and sm["warn"] == rk["warn"] and sm["holders"][:12] == rk["holdersTop"] and abs(sm["creatorPct"] - 3.0) < 1e-9
          and S["cluster"] and S["netSize"] == 232 and T.rc_summary(None) is None,
          "rc_summary reads a raw RugCheck report exactly as fetch.rc_row + memebot.load_risk do (danger, warnings, insider network, top holders)")
    full = base_S(mintToPoolS=10.0, instantPool=None, rugHolders=4, brand=True, buys=4000.0, rcDanger=["Freeze Authority still enabled"],
                  socN=0.0, cluster=True, netSize=232, creatorSold=True, m5=34.0, devN=12.0, devDead=11.0)
    fr = T.rate(full, W)
    line = T.chips(fr, full, W)
    levels = [lv for lv, _ in line]
    short = base_S(socN=0.0, m5=34.0, rcReport=False, rcDanger=None, cluster=None, wmChecked=False, wmState="noholders", rugHolders=None, devN=12.0, devDead=11.0)
    sline = T.chips(T.rate(short, W), short, W)
    check(len(line) == 8 and levels == sorted(levels, key=["bad", "warn", "unk", "ok", "info"].index) and line == [
        ["bad", "pool opened with the mint"], ["bad", "4 holders from rugged coins"], ["bad", "brand/celebrity name"], ["bad", "3,000+ buys already"],
        ["bad", "RugCheck danger: Freeze Authority still enabled"], ["warn", "no socials"], ["warn", "holder cluster (insider network of 232)"],
        ["warn", "creator sold"]] and sline == [["warn", "no socials"], ["warn", "+34% in 5 min"], ["unk", "RugCheck pending"], ["ok", "curve 4 min before pool"],
                                               ["info", "dev: 12 launches, 11 dead"]],
          "the trap-check line: hard first, then soft, not checked, passed, grey info, cut at 8; texts from the catalogue")
    m = base_S(devN=12.0, devDead=11.0, devAgeH=3.0, xUsed=2.0, xKind="account", snip30=0.61, snip30N=12.0, slotN=6.0, slotPct=0.44, freshN=6.0,
               freshOf=10.0, fundN=4.0, fundMin=3.0)
    texts = [t for lv, t in T.chips(T.rate(m, W), m, W) if lv == "info"]
    want = ["dev: 12 launches, 11 dead", "dev wallet 3 h old", "X account used by 2 older coins", "61% sniped in 30 s (12 wallets)",
            "6 wallets in launch block (~44%)"]
    allt = [T._text(n, m, W) for n in W["measured"] if n != "staircase_early"]
    check(texts == want and "6 of 10 top holders fresh" in allt and "4 top holders funded by one wallet in 3 min" in allt,
          "grey measured texts: %s" % "; ".join(allt))
    every = [t for S_ in (full, m, base_S(), base_S(rcReport=False), base_S(wmChecked=False, wmState="missing"), base_S(buys=None, brand=None, rcDanger=None),
                          base_S(wmChecked=False, wmState="small"), base_S(wmChecked=False, wmState="noholders"), base_S(tweetShared=9.0, x="https://x.com/a/status/123456"),
                          base_S(stair={"n": 7, "rise": 0.3, "green": 0.9, "pull": 0.0}, fundN=5.0, freshN=4.0, freshOf=10.0, devAgeH=None, devTxs=3.0))
             for _, t in T.chips(T.rate(S_, W), S_, W)] + list(T.UNKNOWN_TEXT.values()) + list(T.WM_TEXT.values())
    check(not any(ADVICE.search(t) for t in every) and not any("\u2014" in t for t in every),
          "no chip says safe, buy, guaranteed or clean, and none has an em dash (%d texts, every 'not checked' text included)" % len(every))
    # the young tab's path: without walletmem and pairs.json no row can be green
    y = {"sym": "NEWC", "name": "New Coin", "dex": "pumpswap", "x": "https://x.com/newc", "mc": 70_000.0, "liq": 21_000.0,
         "f": {"ageH": 0.2, "buys1": 300.0, "m5": 4.0, "socN": 2.0, "x": 1.0, "ds.paid": 0.0, "vt.tweet": 0.0, "srcN": 2.0},
         "risk": {"danger": [], "warn": [], "holders": [wallet(rng) for _ in range(8)], "creatorPct": 0.5}}
    wm = {"v": 1, "t": NOW - 30 * MIN, "nCoins": 500, "common": [], "rug": [], "sw": {}}
    a = T.rate(T.signals_scan(y, None, None, now=NOW), W)
    b = T.rate(T.signals_scan(y, NOW - 20 * MIN, None, now=NOW), W)
    c = T.rate(T.signals_scan(y, NOW - 20 * MIN, wm, now=NOW), W)
    d = T.rate(T.signals_scan(y, NOW - 20 * MIN, wm, now=NOW + 4 * H), W)
    check(a["verdict"] == "watch" and set(a["unknown"]) == {"mint_time", "walletmem"} and b["unknown"] == ["walletmem"] and c["verdict"] == "good"
          and d["verdict"] == "watch", "young tab: no mint time or no wallet memory -> '?' and never green; with both -> good; memory older than 3 h -> watch")
    pr = {"pairCreatedAt": NOW - 12 * MIN, "pf": {"createdAt": str((NOW - 16 * MIN) // 1000)}}
    mint, pool = T.pair_times(pr)
    e = T.rate(T.signals_scan(y, mint, wm, now=NOW, pool=pool), W)
    check((mint, pool) == (NOW - 16 * MIN, NOW - 12 * MIN) and T.pair_times({"ll": {"createdAt": "2026-10-14T00:00:00Z"}})[0] == 1791936000000
          and T.pair_times({}) == (None, None) and e["verdict"] == "good" and ["ok", "curve 4 min before pool"] in T.chips(e, T.signals_scan(y, mint, wm, now=NOW, pool=pool), W),
          "pair_times reads the mint (pump.fun or LaunchLab createdAt, seconds, ms or ISO) and the pool time of a pairs.json entry")
    # SF3: the page passes the coin's pairs.json entry and recommend.json's clock; the 3-argument call can never be green
    ins = {"pairCreatedAt": NOW - 12 * MIN, "pf": {"createdAt": NOW - 12 * MIN - 20_000}}
    S3 = T.signals_scan(y, ins, dict(wm, t=NOW - 5 * H), now=NOW)
    r3 = T.rate(S3, W)
    r3a = T.rate(T.signals_scan(y, ins["pf"]["createdAt"], dict(wm, t=NOW - 5 * H)), W)
    ok_e = T.rate(T.signals_scan(y, pr, wm, now=NOW), W)
    check(r3["hard"] == ["instant_pool"] and S3["mintToPoolS"] == 20.0 and "walletmem" in r3["unknown"] and S3["wmState"] == "old"
          and r3a["verdict"] == "watch" and r3a["unknown"] == ["mint_time"] and not r3a["push"] and ok_e["verdict"] == "good" and ok_e["push"],
          "signals_scan(row, pairs entry, walletmem, now=recommend t): a pool 20 s after the mint is the instant-pool trap and a 5-hour-old "
          "memory is not checked; the same row with only the mint time stays '? mint time unknown' (never green)")
    # boundaries (review nit 10)
    fl = lambda name, **kw: T.flag(name, base_S(**kw), W)
    st_ = lambda **kw: dict({"n": 10, "rise": 0.25, "green": 0.8, "pull": 0.01, "stair": True}, **kw)
    seven = [[i, 1.0 + 0.04 * i, 0, 0, (1.0 + 0.04 * i) * (1.03 if i % 10 < 7 else 0.999)] for i in range(10)]
    check(fl("pumping_5m", m5=20.0) is True and fl("pumping_5m", m5=19.9) is False and fl("lists3", lists=3.0) is True and fl("lists3", lists=2.0) is False
          and fl("instant_pool", mintToPoolS=60.0, instantPool=None) is False and fl("instant_pool", mintToPoolS=59.9, instantPool=None) is True
          and fl("staircase10", stair=st_(green=0.7)) is True and fl("staircase10", stair=st_(green=0.69)) is False
          and fl("staircase10", stair=st_(pull=0.049)) is True and fl("staircase10", stair=st_(pull=0.05)) is False
          and fl("staircase10", stair=st_(rise=0.2)) is True and fl("staircase10", stair=st_(rise=0.19)) is False
          and T.staircase(seven)["green"] == 0.7 and T.staircase(seven)["stair"] is True,
          "edges: +20%% in 5 min warns, 19.9 not; 3 lists is a good sign, 2 not; 60 s from mint to pool is not instant, 59.9 is; staircase at "
          "green 70%% and rise 20%% yes, pullback 5%% no (7 of 10 green candles: %s)" % T.staircase(seven)["green"])
    ds = T.signals_scan(dict(y, risk=dict(y["risk"], dev={"devSold": True})), mint, wm, now=NOW, pool=pool)
    tw = {k: T.signals_radar({"now": NOW, "x": v}, W)["tweet"] for k, v in (("tweet", "https://x.com/foo/status/1800123456789"), ("account", "https://x.com/foo"),
                                                                            ("none", None), ("empty", ""))}
    check(ds["creatorSold"] is True and "creator_sold" in T.rate(ds, W)["soft"] and tw == {"tweet": True, "account": False, "none": None, "empty": False},
          "the young tab takes 'creator sold' from RugCheck's dev facts when the factor is missing; the radar reads a tweet link as a tweet (%s)" % tw)
    _fuzz(check, W)


def _fuzz(check, W, n=400):
    """N3: type-confused inputs (numbers for lists, lists for strings, NaN, ...) never raise in the rule core."""
    rng = random.Random(1310)
    junk = [None, "", "abc", "1e400", 0, -1, 1.5, float("nan"), float("inf"), True, [], [1, "x"], {}, {"a": 1}, [[1, 2]], "https://x.com/a", 10 ** 30]

    def mut(o, p):
        if isinstance(o, dict):
            return {k: (rng.choice(junk) if rng.random() < p else mut(v, p)) for k, v in o.items()}
        if isinstance(o, list):
            return [rng.choice(junk) if rng.random() < p else mut(v, p) for v in o]
        return o
    wm = {"v": 1, "t": NOW - 20 * MIN, "nCoins": 900, "common": ["1" * 44], "rug": ["2" * 44], "sw": {"3" * 44: -9.0}}
    coin = radar_coin(random.Random(3), wm)
    coin.update(dev={"n": 3, "dead": 2, "grad": 0, "ageH": 1, "txs": 4}, closes=[1, 1.1, 1.2], snip30=0.3, slotN=2, freshN=1, fundN=1,
                xlinks={"x.com/cleancoin": ["A" * 44, NOW - H, 2, "account", NOW, [["A" * 44, NOW - H]]]})
    y = {"sym": "NEWC", "name": "New Coin", "dex": "pumpswap", "x": "https://x.com/newc", "mc": 7e4, "liq": 2.1e4,
         "f": {"ageH": 0.2, "buys1": 300.0, "m5": 4.0, "socN": 2.0, "x": 1.0, "ds.paid": 0.0, "vt.tweet": 0.0, "srcN": 2.0, "sw.avg": -1, "dev.sold": 0},
         "risk": {"danger": ["Freeze"], "warn": ["insider network of 99 wallets"], "holders": ["4" * 44], "creatorPct": 0.5, "dev": {"devSold": True}}}
    errs = []
    for i in range(n):
        p = rng.choice((0.05, 0.15, 0.3))
        c, yy, w2 = mut(copy.deepcopy(coin), p), mut(copy.deepcopy(y), p), mut(copy.deepcopy(wm), 0.2)
        links = mut(copy.deepcopy(coin["xlinks"]), 0.3)
        Sj = mut(base_S(devN=12.0, devDead=11.0, xUsed=2.0, xKind="account", stair={"n": 10, "rise": 0.3, "green": 0.8, "pull": 0.01}), 0.3)
        steps = (lambda: T.chips(T.rate(T.signals_radar(c, W), W), T.signals_radar(c, W), W),
                 lambda: T.chips(T.rate(T.signals_scan(yy, rng.choice([NOW - 9 * MIN, None, "x", 0, {"pf": [1]}]), w2, now=rng.choice([NOW, None]), W=W), W), {}, W),
                 lambda: T.chips(T.rate(Sj, W), Sj, W),
                 lambda: T.rc_summary(mut(copy.deepcopy(coin["rc"]), 0.3)),
                 lambda: T.walletmem_lookup(mut(["1" * 44, "2" * 44], 0.3), w2, NOW, W),
                 lambda: T.xlinks_add(links, rng.choice(["https://x.com/cleancoin", None, 5]), rng.choice(["Q" * 44, None, 5]), rng.choice([NOW, None, "x"])),
                 lambda: T.x_reuse("https://x.com/cleancoin", "Q" * 44, rng.choice([NOW, None, "x"]), links),
                 lambda: T.staircase(mut([[0, 1, 1, 1, 1], [1, 1, 1, 1, 1.1], 1.2, 1.3], 0.4)),
                 lambda: T.pair_times(mut({"pairCreatedAt": NOW, "pf": {"createdAt": NOW - 9 * MIN}, "ll": {"createdAt": "2026-10-14T00:00:00Z"}}, 0.4)))
        for k, fn in enumerate(steps):
            try:
                fn()
            except Exception as e:      # noqa: BLE001 - the point of the check
                errs.append("%d %s: %s" % (k, type(e).__name__, str(e)[:60]))
    check(not errs, "%d rounds of malformed inputs through signals, rate, chips, rc_summary, walletmem_lookup, xlinks_add, x_reuse, "
          "staircase and pair_times: no exception%s" % (n, "" if not errs else " (%d: %s)" % (len(errs), errs[:3])))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check, {})
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
