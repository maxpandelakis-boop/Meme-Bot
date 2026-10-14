#!/usr/bin/env python3
"""Freeze the rug study's outputs into radar_weights.json, the launch radar's prior (fake-money paper bot; nothing is bought).

Usage: python3 -I make_weights.py <study out dir> <dest json>

Reads only the study's own outputs (results.json, rules.json, rules.txt, staircase_w10.json, recommend.json, young10.txt,
winpoints.txt, paper_pnl.txt, build_log.txt). The rule sets, points and thresholds below are the study's recommendation
(scripts/recommend.py, scripts/rules.py, scripts/winpoints.py); the brand regex is read verbatim from scripts/build.py.
Every number in "evidence" and "zero" comes from the outputs, nothing is fitted here. Deterministic: the same outputs give
the same file, byte for byte.
"""
import ast, json, math, os, re, sys

OUT, DEST = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))


def lj(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return json.load(f)


def txt(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return f.read()


def r3(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return round(x, 3)


def brand_regex():
    """The BRAND pattern of scripts/build.py, verbatim (the adjacent string literals joined, as Python joins them)."""
    src = open(os.path.join(HERE, "scripts", "build.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BRAND" for t in node.targets):
            call = node.value
            return ast.literal_eval(call.args[0])
    raise SystemExit("BRAND not found in build.py")


RESULTS = lj("results.json")
SIG = {key: {s["name"]: s for s in rows} for key, rows in RESULTS["signals"].items()}
COHORTS = {
    "L": "listed new launches (new-launches tab and early list), first listing per coin, rug or 2x within 1 h",
    "S": "every scanned coin under 1 h old with $5k+ liquidity, first sighting, rug or 2x within 2 h",
    "P": "paper new-launch positions since the 2026-10-10 restart (3 fake euros each), rug at any time",
    "E": "the early list only (coins the launch spotter saw minutes old), rug within 1 h",
}


def row(key, name, flip=False):
    """One results.json signal entry -> evidence row. flip: the study measured the opposite flag (e.g. 'report exists')."""
    s = SIG.get(key, {}).get(name)
    if not s:
        return None
    c, o = key.split(".")
    n1, r1, n0, r0 = s["n1"], s["r1"], s["n0"], s["r0"]
    lift, lo, hi = s.get("lift"), s.get("llo"), s.get("lhi")
    halves = [[h[0], r3(h[1]), h[2], r3(h[3])] for h in (s.get("halves") or []) if isinstance(h, list) and len(h) == 4]
    if flip:
        n1, r1, n0, r0 = n0, r0, n1, r1
        lift = (1.0 / lift) if lift else None
        lo, hi = ((1.0 / hi) if hi else None), ((1.0 / lo) if lo else None)
        halves = [[h[2], h[3], h[0], h[1]] for h in halves]
    return {"cohort": c, "outcome": o, "with": r3(r1), "without": r3(r0), "n": n1, "n0": n0, "lift": r3(lift), "lo": r3(lo), "hi": r3(hi),
            "q": r3(s.get("q")), "halves": halves, "verdict": s.get("verdict"), "src": "results.json " + name + (" (flipped)" if flip else "")}


def rows(names, keys=("L.rug1h", "S.rug2h", "P.rugAny"), flip=False):
    out = []
    for name in names:
        for key in keys:
            r = row(key, name, flip)
            if r:
                out.append(r)
    return out


# ------------------------------------------------------------------ rules.txt: the hard traps one by one (combined flags)
HARD_TXT = {}
cur = None
for line in txt("rules.txt").splitlines():
    m = re.match(r"^## (\w) \(", line)
    if m:
        cur = m.group(1)
        continue
    m = re.match(r"^\s+(.+?)\s+(\d+)% of (\d+) vs (\d+)% of (\d+), lift ([\d.]+) \[([\d.]+)-([\d.]+)\]", line)
    if m and cur:
        HARD_TXT.setdefault(m.group(1).strip(), {})[cur] = {"cohort": cur, "outcome": "rug2h" if cur == "S" else "rug1h", "with": int(m.group(2)) / 100.0,
                                                           "without": int(m.group(4)) / 100.0, "n": int(m.group(3)), "n0": int(m.group(5)),
                                                           "lift": float(m.group(6)), "lo": float(m.group(7)), "hi": float(m.group(8)),
                                                           "src": "rules.txt hard traps one by one"}


def hard_txt(label):
    return [HARD_TXT[label][c] for c in ("L", "E", "S", "P") if c in HARD_TXT.get(label, {})]


# ------------------------------------------------------------------ rule D and the radar's own population (coins under 10 min)
RULES = lj("rules.json")
rule_d = {}
for c in ("L", "E", "S", "P"):
    res = RULES.get(c) or {}
    d_, a_, all_ = res.get("D. no hard trap, checked, 0-1 soft warning"), res.get("A. any hard trap"), res.get("all")
    if d_ and a_ and all_:
        rule_d[c] = {"n": d_["n"], "rug": r3(d_["rug"]["rate"]), "rugLo": r3(d_["rug"]["lo"]), "rugHi": r3(d_["rug"]["hi"]), "win": r3(d_["win"]["rate"]),
                     "trapRug": r3(a_["rug"]["rate"]), "allRug": r3(all_["rug"]["rate"]), "allN": all_["n"]}
young10 = {}
cur = None
for line in txt("young10.txt").splitlines():
    m = re.match(r"^## (\w): (\d+) coins under 10 min", line)
    if m:
        cur = m.group(1)
        continue
    m = re.match(r"^\s+(rule D: no hard trap, checked, 0-1 soft|all under 10 min|any hard trap|no hard trap, not checked)\s+n=\s*(\d+)\s+(rug\dh) (\d+)% \[(\d+)%-(\d+)%\]", line)
    if m and cur:
        key = {"rule D: no hard trap, checked, 0-1 soft": "ruleD", "all under 10 min": "all", "any hard trap": "trap", "no hard trap, not checked": "unchecked"}[m.group(1)]
        young10.setdefault(cur, {})[key] = {"n": int(m.group(2)), "outcome": m.group(3), "rug": int(m.group(4)) / 100.0, "lo": int(m.group(5)) / 100.0, "hi": int(m.group(6)) / 100.0}

STAIR = lj("staircase_w10.json")
st, sv = STAIR["staircase (rise >= 20%, >= 70% green, pullback < 5%)"]["rugAfter"], STAIR["staircase_vs_risers.rugAfter"]
stair_rows = [{"cohort": "L", "outcome": "rug after minute 10", "with": r3(sv["r1"]), "without": r3(sv["r0"]), "n": sv["n1"], "n0": sv["n0"], "lift": r3(sv["lift"]),
               "lo": r3(sv["llo"]), "hi": r3(sv["lhi"]), "q": None, "halves": [], "verdict": "holds",
               "src": "staircase_w10.json: staircase vs other coins that rose 20%+ in their first 10 minutes"}]

REC = lj("recommend.json")
points_check = {c: {"aucRug": r3(v.get("auc.%s.all" % ("rug2h" if c == "S" else "rug1h"))),
                    "aucRugHalves": [r3(v.get("auc.%s.1st half" % ("rug2h" if c == "S" else "rug1h"))), r3(v.get("auc.%s.2nd half" % ("rug2h" if c == "S" else "rug1h")))],
                    "bands": {b: r3((v.get("%s.%s" % (nm, "rug2h" if c == "S" else "rug1h")) or {}).get("rate"))
                              for b, nm in (("0 or less", "0 or less (eligible as good)"), ("1-2", "1-2 (yellow)"), ("3+", "3+ (red / hidden)"))}}
                for c, v in sorted(REC["res"].items())}

# ------------------------------------------------------------------ the weights (the study's recommendation, see recommend.py)
LABELS = {
    "instant_pool": "pool opened within 60 s of the mint",
    "rugger_wallets": "top holders come from rugged coins (wallet memory)",
    "brand_name": "named after a brand, AI or celebrity",
    "bot_volume": "3,000+ buys in the first hour",
    "rc_danger": "RugCheck danger flag",
    "staircase10": "staircase chart over the first 10 minutes",
    "no_socials": "no socials",
    "holder_cluster": "RugCheck holder cluster (insider network or holder correlation)",
    "creator_sold": "creator already sold",
    "pumping_5m": "up 20% or more in 5 minutes",
    "no_rc_report": "no RugCheck report yet",
    "young_5m": "pool under 5 minutes old",
    "x_and_paid": "X link and a paid DexScreener profile",
    "tweet": "launched off a tweet",
    "lists3": "on 3 or more source lists",
    "x": "has an X link",
    "creator_5pct": "creator still holds over 5%",
    "mc_500k": "market cap $500k or more",
    "liq_15pct": "liquidity under 15% of the market cap (not PumpSwap)",
    "dev_dead": "most of the dev's earlier launches are dead",
    "dev_young": "dev wallet under 1 day old",
    "x_copied": "X account or community already used by an older coin",
    "tweet_shared": "other coins launched off the same tweet",
    "sniped30": "supply sniped in the first 30 seconds",
    "bundle_slot": "several wallets bought in the launch block",
    "fresh_holders": "top holders in brand-new wallets",
    "fund_cluster": "top holders funded by one wallet within 15 minutes",
    "staircase_early": "staircase so far (6 to 9 minutes)",
}
EVIDENCE = {
    "instant_pool": rows(["instantPool"]) + hard_txt("instant pool (< 60 s after mint)"),
    "rugger_wallets": hard_txt("rugger wallets (sw.avg <= -7 or 3+ holders in earlier rugs)") + rows(["own.holders_in_earlier_rug>=3", "sw.avg<0"]),
    "brand_name": rows(["own.brand_name"]),
    "bot_volume": hard_txt("3000+ buys in the first hour"),
    "rc_danger": rows(["rcn.danger_any"]) + hard_txt("RugCheck danger flag"),
    "staircase10": stair_rows,
    "no_socials": rows(["socN=0"]),
    "holder_cluster": rows(["rcn.cluster_any"]),
    "creator_sold": rows(["dev.sold>0"]),
    "pumping_5m": rows(["m5>=20"]),
    "no_rc_report": rows(["rc.report"], flip=True),
    "young_5m": rows(["ageMin<5"]),
    "x_and_paid": rows(["x", "ds.paid"]),
    "tweet": rows(["vt.tweet"]),
    "lists3": rows(["srcN>=3"]),
    "x": rows(["x"], keys=("L.win1h", "S.win2h")),
    "creator_5pct": rows(["rc.creator>5"], keys=("L.win1h", "S.win2h")),
    "mc_500k": rows(["mc>=500k"], keys=("L.win1h", "S.win2h")),
    "liq_15pct": rows(["liqMc<0.15"], keys=("L.win1h", "S.win2h")),
}
for k in list(EVIDENCE):
    EVIDENCE[k] = {"label": LABELS[k], "rows": EVIDENCE[k]}
EVIDENCE["tweet"]["win"] = rows(["vt.tweet"], keys=("L.win1h", "S.win2h"))
EVIDENCE["holder_cluster"]["win"] = rows(["rcn.cluster_any"], keys=("L.win1h", "S.win2h"))
EVIDENCE["brand_name"]["win"] = rows(["own.brand_name"], keys=("L.win1h", "S.win2h"))
for k in ("dev_dead", "dev_young", "x_copied", "tweet_shared", "sniped30", "bundle_slot", "fresh_holders", "fund_cluster", "staircase_early"):
    EVIDENCE[k] = {"label": LABELS[k], "rows": [], "note": "never stored before 2026-10-13: measured by the radar from now on, weight 0 until its own records confirm it"}
EVIDENCE["dev_dead"]["related"] = rows(["rcn.creator_rugged", "jup.devMints>1"], keys=("L.rug1h", "S.rug2h"))
EVIDENCE["x_copied"]["related"] = rows(["own.ticker_reused"], keys=("L.rug1h", "S.rug2h"))

# weight 0: tested here and not used (reason from the L / rug1h row unless a note says otherwise)
ZERO = [
    ("rc.top1>20", "biggest wallet over 20%", None),
    ("rc.top10>35", "top 10 wallets over 35%", None),
    ("rc.top10>50", "top 10 wallets over 50%", None),
    ("rcn.single_holder", "RugCheck: single holder ownership", None),
    ("rc.holders<300", "under 300 holders", None),
    ("rcn.creator_rugged", "RugCheck: creator history of rugged tokens", None),
    ("jup.devMints>1", "Jupiter: dev minted more than 1 token", None),
    ("jup.devMints>=10", "Jupiter: dev minted 10+ tokens", None),
    ("rcn.copycat", "RugCheck: copycat token", None),
    ("own.ticker_reused", "ticker already used by an older coin", ("covered", "a copy of a bigger coin's ticker is already blocked by the bot's copy gate; in the snapshot cohort the effect was small (lift 1.11) and weak in one half")),
    ("rcn.lp_unlocked", "RugCheck: LP unlocked", None),
    ("rcn.few_lp_providers", "RugCheck: few LP providers", None),
    ("rcn.mutable", "RugCheck: mutable metadata", None),
    ("rcn.mc_per_holder", "RugCheck: high market cap per holder", None),
    ("rcn.low_liquidity", "RugCheck: low liquidity warning", ("reversed", "weak in one half of the listed coins and reversed in the snapshot cohort (lift 0.10) and the paper positions (0.18)")),
    ("volMc>=5", "24 h volume over 5x the market cap", None),
    ("boosts>0", "DexScreener boosts bought", None),
    ("jup.organic=0", "Jupiter organic score 0", ("unreliable", "known for only a third of new coins (Jupiter has no score for most fresh pools), and the paper positions with it lost less than those without")),
    ("score>=50", "bot score 50 or more", ("no effect for young coins", "the bot's score did not separate young winners (out-of-time AUC 0.42-0.45, model.txt); trained odds are shown as information only")),
]


def zero_reason(name, override):
    if override:
        return override
    s = SIG["L.rug1h"].get(name)
    if not s:
        return ("not measured", "")
    if str(s.get("verdict")).startswith("too rare"):
        return ("too rare", "")
    lo, hi = s.get("llo"), s.get("lhi")
    if hi is not None and hi < 1.0:
        return ("reversed", "coins with it rugged less, not more")
    if lo is not None and hi is not None and lo <= 1.0 <= hi:
        return ("no effect", "")
    return ("no effect", "")


zero = []
for name, label, override in ZERO:
    reason, note = zero_reason(name, override)
    ev = rows([name], keys=("L.rug1h", "S.rug2h", "P.rugAny"))
    zero.append({"signal": name, "label": label, "reason": reason, "note": note, "rows": ev})
zero.append({"signal": "hourBerlin", "label": "hour of the day", "reason": "no effect", "note": "no 4-hour block differed from the day's rate (report.txt, hour of day)", "rows": []})
zero.append({"signal": "zp", "label": "trained chance of going to zero", "reason": "no effect for young coins",
             "note": "out-of-time AUC for rugs 0.45-0.51 on coins under 1 h (model.txt); shown as information only", "rows": []})

W = {
    "v": 1,
    "src": "study 2026-10-13",
    "note": "Fake money only. The study's rule D made strict: a check that could not run never counts as passed. Weights move only through traps.fit (radar data, walk-forward guarded).",
    "hard": ["instant_pool", "rugger_wallets", "brand_name", "bot_volume", "rc_danger", "staircase10"],
    "soft": ["no_socials", "holder_cluster", "creator_sold", "pumping_5m"],
    "maxSoft": 1,
    "needChecked": ["rc_report", "mint_time", "walletmem"],
    "points": {"instant_pool": 3, "rugger_wallets": 3, "rc_danger": 3, "staircase10": 3, "brand_name": 2, "bot_volume": 2, "no_rc_report": 2,
               "no_socials": 1, "holder_cluster": 1, "creator_sold": 1, "pumping_5m": 1, "young_5m": 1, "x_and_paid": -1, "tweet": -1, "lists3": -1},
    "upside": {"x": 1, "tweet": 1, "holder_cluster": -1, "creator_5pct": -1, "mc_500k": -1, "liq_15pct": -1, "brand_name": -1},
    "pushBlock": ["holder_cluster"],
    "measured": ["dev_dead", "dev_young", "x_copied", "sniped30", "bundle_slot", "fresh_holders", "fund_cluster", "staircase_early"],
    "infoOnly": ["tweet_shared"],
    "thresholds": {
        "instantPoolS": 60, "mintSkewS": 120, "curve2mS": 120,
        "swAvg": -7.0, "swMinRecords": 2, "rugHolders": 3,
        "buys": 3000, "m5": 20.0, "youngMin": 5.0,
        "stair": {"n": 10, "rise": 0.2, "green": 0.7, "pull": 0.05}, "stairEarlyN": 6,
        "creatorPct": 5.0, "mc": 500000.0, "liqMc": 0.15, "lists": 3,
        "wmMaxAgeH": 3.0, "wmMinCoins": 500,
        "devDead": {"n": 3, "share": 0.8}, "devYoungH": 24.0, "devYoungTxs": 10,
        "xGapS": 600, "sniped30": 0.3, "bundleSlot": 3, "freshHolders": 3, "fundCluster": 3, "fundMinutes": 15, "fundExchange": 25,
    },
    "brand": brand_regex(),
    "fit": {"minRecords": 300, "boot": 2000, "seed": 20261013, "q": 0.05, "maxPoints": 2, "testDays": 2, "minTrain": 150, "minTest": 30,
            "minSide": 15, "aucSlack": 0.01},
    "labels": LABELS,
    "cohorts": {c: dict(desc=COHORTS[c], **({"n": RESULTS["base"][k]["n"], "base": r3(RESULTS["base"][k]["rate"])} if k in RESULTS["base"] else
                                             {"n": rule_d.get(c, {}).get("allN"), "base": rule_d.get(c, {}).get("allRug")}))
                for c, k in (("L", "L.rug1h"), ("S", "S.rug2h"), ("P", "P.rugAny"), ("E", "E.rug1h"))},
    "ruleD": {"all": rule_d, "under10min": young10},
    "pointsCheck": points_check,
    "evidence": EVIDENCE,
    "zero": zero,
    "caveats": ["8 days of data, one market regime", "points were set after seeing the data: the halves show stability, not an independent test",
                "survivorship: coins that rugged before minute 5 or never left the curve are not in the data",
                "a RugCheck report without warnings on a coin minutes old proves little", "the radar's own records are the first forward test"],
}
with open(DEST, "w", encoding="utf-8") as f:
    json.dump(W, f, indent=1, sort_keys=False, ensure_ascii=False)
    f.write("\n")
print("wrote %s: %d evidence entries, %d weight-0 entries, %d bytes" % (DEST, len(EVIDENCE), len(zero), os.path.getsize(DEST)))
