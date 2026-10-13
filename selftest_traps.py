#!/usr/bin/env python3
"""selftest_traps.py: checks T1-T7 of SPEC 13.10 section 11 for traps.py and radar_weights.json (fake money only).

  python3 selftest_traps.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure

selftest.py calls checks(check, env) after spotter_checks. Needs no network, no mock server and no other package's files:
the radar's coin dicts below are built here the way launch_radar.py hands them to traps.signals_radar.
"""
import ast, glob, gzip, json, math, os, random, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import traps as T          # noqa: E402

PY = sys.executable
H, MIN, DAY = 3_600_000, 60_000, 86_400_000
NOW = 1_792_000_000_000            # a fixed clock (2026-10-14 UTC); traps never reads the wall clock when given one
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


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
          and th["m5"] == 20 and th["youngMin"] == 5 and th["stair"] == {"n": 10, "rise": 0.2, "green": 0.7, "pull": 0.05} and th["curve2mS"] == 120,
          "radar_weights.json v1 'study 2026-10-13': hard, soft (maxSoft 1), needChecked, pushBlock and thresholds as the spec says")
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
        for _ in range(per_hour):
            t = start + h * H + rng.randrange(H)
            S, rug = sig_fn(rng, t)
            out.append({"first": t, "sig": S, "out": {"rug1h": rug, "win1h": False, "x60": 0.0 if rug else 1.0}})
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
    for i in range(12):
        T.xlinks_add(many, "https://x.com/serial", "%s%02dpump" % ("D" * 38, i), NOW - (60 - i) * MIN)
    rm = T.x_reuse("https://x.com/serial", "Z" * 40 + "pump", NOW, many)
    check(rm["used"] == T.XUSES_MAX and many["x.com/serial"][2] == 12 and len(many["x.com/serial"][5]) == T.XUSES_MAX
          and "8+ older coins" in T._text("x_copied", base_S(xUsed=8.0, xKind="account"), W),
          "a link used by many coins keeps the earliest %d and prints '8+ older coins'" % T.XUSES_MAX)


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
        hs = [common] + rng.sample(filler, 3)
        docs.append(("2026-10-12T%02d%02d-1" % (i % 24, i), _snap_doc(now - 30 * H + i * MIN, now - 27 * H + i * MIN,
                     [{"a": wallet(rng, "pump"), "s": "C%d" % i, "mult": 0.05 if i % 2 else 1.4, "gone": False, "eur": -18.0 if i % 2 else 6.0,
                       "rc": {"holders": hs}, "f": {"ageH": 0.5}}])))
    docs.append(("2026-10-13T0100-1", _snap_doc(now - 5 * H, now - 3 * H, [{"a": wallet(rng, "pump"), "s": "RUG1", "mult": 0.0, "gone": True, "eur": -20.0,
                                                                           "rc": {"holders": early_rug + [common]}, "f": {}}])))
    docs.append(("2026-10-13T0200-1", _snap_doc(now - 1 * H, now + 1 * H, [{"a": wallet(rng, "pump"), "s": "RUG2", "mult": 0.01, "gone": False, "eur": -20.0,
                                                                           "rc": {"holders": late_rug}, "f": {}}])))
    docs.append(("2026-10-13T0300-1", _snap_doc(now - 6 * H, now - 4 * H, [{"a": wallet(rng, "pump"), "s": "FINE", "mult": 1.8, "gone": False, "eur": 15.0,
                                                                           "rc": {"holders": [ok_w] + early_rug[:1]}, "f": {}}])))
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
             {"address": wallet(rng, "pump"), "symbol": "ZED", "marketCap": 12_000, "xUrl": "https://x.com/zed/status/18009999999", "pairCreatedAt": now - 10 * MIN}]
    with open(os.path.join(d, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump(pairs, f)
    old_links = {"x.com/oldcoin": ["O" * 40 + "pump", now - 40 * DAY, 1, "account", now - 35 * DAY, [["O" * 40 + "pump", now - 40 * DAY]]],
                 "x.com/keepcoin": ["K" * 40 + "pump", now - 20 * DAY, 1, "account", now - 20 * DAY, [["K" * 40 + "pump", now - 20 * DAY]]]}
    with open(os.path.join(d, "xlinks.json.gz"), "wb") as f:
        f.write(gzip.compress(json.dumps({"v": 1, "t": now - H, "links": old_links}).encode(), mtime=0))
    return {"common": common, "early": early_rug, "late": late_rug, "ok": ok_w, "pf_a": pf_a, "pf_b": pf_b}


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
    meta_later = T.feed(mb, os.path.join(tmp, "f3"), NOW + 2 * H)
    wm3 = json.load(gzip.open(os.path.join(tmp, "f3", "walletmem.json.gz"), "rt"))
    look = T.walletmem_lookup([k["common"]] + k["early"], dict(wm, rug=wm["rug"] + [k["common"]]), NOW + 10 * MIN)
    check(set(k["late"]) <= set(wm3["rug"]) and look == {"swAvg": look["swAvg"], "rugHolders": 3, "checked": True, "state": "ok"},
          "two hours later the late rug is known; the lookup skips the common account even if it were listed (3 rugger holders)")
    done = {n: dd for n, dd in M.load_docs(mb, "memesnapres").items() if dd["t"] <= NOW}
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
          and "x.com/i/status/18009999999" in xl and sm == {"AAA": 900_000, "ZED": 12_000},
          "xlinks from pf/*.txt and pairs.json merged with the previous feed (30 days kept); symmc = the copy gate's max market cap per ticker")
    T.feed(mb, os.path.join(tmp, "f2"), NOW)
    same = all(open(os.path.join(tmp, "f1", n), "rb").read() == open(os.path.join(tmp, "f2", n), "rb").read()
               for n in ("walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz"))
    fb = meta["files"]
    check(same and all(fb[n]["bytes"] > 0 for n in fb) and set(fb) == {"walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz"} and meta["secs"] < 60,
          "deterministic: two runs give the same bytes; sizes reported (%s; %.2f s)" % (", ".join("%s %d B" % (n, fb[n]["bytes"]) for n in sorted(fb)), secs))
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
    every = [t for S_ in (full, m, base_S(), base_S(rcReport=False), base_S(wmChecked=False, wmState="missing")) for _, t in T.chips(T.rate(S_, W), S_, W)]
    check(not any(re.search(r"\b(safe|buy|guaranteed|clean)\b", t, re.I) for t in every) and not any("\u2014" in t for t in every),
          "no chip says safe, buy, guaranteed or clean, and none has an em dash (%d texts)" % len(every))
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
