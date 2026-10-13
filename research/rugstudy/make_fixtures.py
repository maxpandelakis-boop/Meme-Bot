#!/usr/bin/env python3
"""Study-parity fixtures for selftest_traps.py (check T3): 300 rows sampled from the study's listings.jsonl and snapyoung.jsonl,
each with the RAW inputs the radar's rule core reads (a recommend.json-like young row: symbol, name, the scan's factors, the
RugCheck summary with its top holders; the mint and pool times; the slice of the wallet memory those holders touch, as known
at the row's time) and the flags scripts/rules.py gives the same row (hard traps, soft warnings, RugCheck-checked, rule D).

Usage (needs numpy for scripts/rules.py, so the study's venv):
  PY -I make_fixtures.py <study out dir> <results db dir> <memesnapres dir> <dest .json or .json.gz>
Reads data only. Deterministic (seeded sample, sorted output)."""
import collections, glob, gzip, json, os, random, sys

OUT, DB, SNAP, DEST = sys.argv[1:5]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))
sys.argv = [sys.argv[0], OUT]
import rules as R          # noqa: E402  (loads the study rows; its HARD / SOFT / checked are the reference)

H = 3_600_000
RUG_X = 0.10
F_KEYS = ("sw.avg", "socN", "buys1", "m5", "x", "ds.paid", "vt.tweet", "srcN", "dev.sold", "rc.creator", "ageH", "liqMc")
HARD_NAMES = {"instant pool (< 60 s after mint)": "instant_pool", "rugger wallets (sw.avg <= -7 or 3+ holders in earlier rugs)": "rugger_wallets",
              "brand / AI / celebrity name": "brand_name", "3000+ buys in the first hour": "bot_volume", "RugCheck danger flag": "rc_danger"}
SOFT_NAMES = {"no socials": "no_socials", "RugCheck holder cluster": "holder_cluster", "creator sold": "creator_sold", "up 20%+ in 5 min": "pumping_5m"}


def num(x):
    try:
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def lj(fn):
    with open(fn, encoding="utf-8") as f:
        return json.load(f)


# the sample first, so the snapshot pass only keeps what it needs
rng = random.Random(1013)
L = sorted(R.L, key=lambda r: (r["rid"], r["a"]))
S = sorted(R.S, key=lambda r: (r["rid"], r["a"]))
pick = [("L", r) for r in rng.sample(L, 150)] + [("S", r) for r in rng.sample(S, 150)]
need = {(r["rid"], r["a"]) for _, r in pick}

# one pass over the snapshots: holder history (build.py HOLDER_EVENTS, every wallet) and the sampled rows' snapshot coins
SEEN = collections.Counter()
HIST = collections.defaultdict(list)          # wallet -> [(t_known, addr, gone)]
SNAPROW = {}
nhold = 0
for fn in sorted(glob.glob(os.path.join(SNAP, "*.json"))):
    d = lj(fn)
    rid = os.path.basename(fn).rsplit("-", 1)[0]
    t0, t1 = num(d.get("t0")), num(d.get("t"))
    if not t0:
        continue
    for c in d.get("coins") or []:
        a = c.get("a")
        rc = c.get("rc")
        if isinstance(rc, dict) and rc.get("holders"):
            hs = set(rc["holders"][:40])
            SEEN.update(hs)
            nhold += 1
            gone = bool(c.get("gone")) or (num(c.get("mult")) is not None and num(c["mult"]) < RUG_X)
            for w in hs:
                HIST[w].append((t1 or t0 + 2 * H, a, gone))
        age = num((c.get("f") or {}).get("ageH"))
        if (rid, a) in need and age is not None and age < 3:
            SNAPROW[(rid, a)] = c
COMMON = {w for w, k in SEEN.items() if k > max(20, 0.01 * nhold)}

POS, BYRUN = {}, {}
for fn in glob.glob(os.path.join(DB, "memepos", "*.json")):
    p = lj(fn)
    POS[os.path.basename(fn)[:-5]] = p
    BYRUN[(p.get("rec"), p.get("addr"))] = p
EARLY = {}
for fn in sorted(glob.glob(os.path.join(DB, "memeearly", "*.json"))):
    d = lj(fn)
    rid = d.get("id") or os.path.basename(fn)[:-5]
    for c in d.get("coins") or []:
        EARLY[(rid, c["addr"])] = c


def risk_of(rc, keep):
    if not isinstance(rc, dict):
        return None
    hs = [h for h in (rc.get("holders") or [])[:40] if isinstance(h, str)]
    trimmed = [h for h in hs if h in keep][:40]
    trimmed += [h for h in hs if h not in keep][:max(0, 2 - len(trimmed))]
    out = {"danger": list(rc.get("danger") or []), "warn": list(rc.get("warn") or []), "holders": trimmed, "creatorPct": num(rc.get("creatorPct"))}
    if isinstance(rc.get("dev"), dict) and rc["dev"].get("devSold") is not None:
        out["dev"] = {"devSold": rc["dev"]["devSold"]}
    return out


rows, miss = [], 0
for cohort, r in pick:
    k = (r["rid"], r["a"])
    sn = SNAPROW.get(k)
    pos = BYRUN.get(k) if cohort == "L" else None
    if cohort == "L":
        f = (sn or {}).get("f") or (pos or {}).get("f") or {}
        rc = sn.get("rc") if sn and sn.get("rc") else (pos or {}).get("risk")
        name = (pos or {}).get("name")
        e = EARLY.get(k)
        mint, pool = (num(e.get("minted")), num(e.get("born"))) if e else (None, None)
    else:
        f, rc, name, mint, pool = (sn or {}).get("f") or {}, (sn or {}).get("rc"), None, None, None
    if cohort == "S" and not sn:
        miss += 1
    hs = set((rc or {}).get("holders", [])[:40]) if isinstance(rc, dict) else set()
    rugged = sorted(w for w in hs if any(tk <= r["t"] and a != r["a"] and g for tk, a, g in HIST.get(w, ())))
    common = sorted(hs & COMMON)
    y = {"sym": r.get("sym"), "name": name, "dex": r["sig"].get("dex"), "mc": num(r["sig"].get("mc")), "liq": num(r["sig"].get("liq")),
         "f": {kk: num(f.get(kk)) for kk in F_KEYS if num(f.get(kk)) is not None}, "risk": risk_of(rc, set(rugged) | set(common))}
    hard = sorted(HARD_NAMES[n] for n, fn in R.HARD.items() if fn(r))
    soft = sorted(SOFT_NAMES[n] for n, fn in R.SOFT.items() if fn(r))
    chk = bool(R.checked(r))
    rows.append({"c": cohort, "rid": r["rid"], "a": r["a"], "t": r["t"], "y": y, "mint": mint, "pool": pool,
                 "wm": {"v": 1, "t": r["t"], "nCoins": nhold, "common": common, "rug": rugged, "sw": {}},
                 "expect": {"hard": hard, "soft": soft, "checked": chk, "D": (not hard) and chk and len(soft) <= 1},
                 "study": {k2: r["sig"].get(k2) for k2 in ("sw.avg", "own.holders_in_earlier_rug", "own.brand_name", "instantPool", "rcn.cluster_any", "dev.sold")}})
rows.sort(key=lambda x: (x["c"], x["rid"], x["a"]))
doc = {"v": 1, "src": "study 2026-10-13: scripts/rules.py flags on listings.jsonl (L) and snapyoung.jsonl (S)", "n": len(rows), "rows": rows}
raw = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
with open(DEST, "wb") as fo:
    fo.write(gzip.compress(raw, 9, mtime=0) if DEST.endswith(".gz") else raw)
cov = collections.Counter()
for x in rows:
    for h in x["expect"]["hard"]:
        cov["hard:" + h] += 1
    for s_ in x["expect"]["soft"]:
        cov["soft:" + s_] += 1
    cov["D"] += x["expect"]["D"]
    cov["checked"] += x["expect"]["checked"]
print(json.dumps({"rows": len(rows), "snapshotMissing": miss, "bytes": os.path.getsize(DEST), "coverage": dict(sorted(cov.items()))}))
