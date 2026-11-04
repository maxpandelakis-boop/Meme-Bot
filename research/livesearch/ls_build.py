#!/usr/bin/env python3
"""ls_build.py: the live-data rule search of 4 Nov 2026 (research only, fake money). Builds the three data sets from the bots' own
live records of 22 Oct 10:08 UTC (memebot.FRESH_AT) to 4 Nov 2026:

  bt    the big test: every coin of every hourly scan snapshot (db/memesnapres on branch bigtest) with liquidity >= $5k and market cap
        >= $10k, no hard block, with the factors the scan saw and its price about 2 h later (filter_search.py's loader rules)
  pick  the Pick account's buys (grp "hold" in db/memepos on branch results) with their buy-time factors, the real booked result and
        the 12-hour minute path the shadow job keeps (db/memeshadow)
  lern  the Learning Pick's buys (db/memelern) with its 6-hour path (closes)

  python3 ls_build.py --bt <memesnapres dir> --res <results checkout> --out <dir>
"""
import argparse, glob, json, math, os, pickle, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import harness as H

FROM = 1792663680000            # memebot.FRESH_AT: 22 Oct 2026 10:08 UTC, the Pick account's fresh start
MIN_LIQ, MIN_MC = 5_000.0, 10_000.0
HARD_BLOCK = ("price", "curve", "nodex", "honeypot", "notmeme", "copy")


def num(v):
    return H.num(v)


def one(fn):
    try:
        doc = json.load(open(fn, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or not num(doc.get("t0")) or (num(doc["t0"]) or 0) < FROM or not H.usable_result(doc):
        return []
    t0, t1 = num(doc["t0"]), num(doc.get("t")) or num(doc["t0"])
    out = []
    for c in doc.get("coins") or []:
        if not isinstance(c, dict) or not isinstance(c.get("f"), dict) or num(c.get("eur")) is None:
            continue
        if c.get("gone") and H.priceless_at_snapshot(c):
            continue
        liq, mc = num(c.get("liq")), num(c.get("mc"))
        why = [str(w) for w in c.get("why") or []]
        if not liq or liq < MIN_LIQ or not mc or mc < MIN_MC or any(w in HARD_BLOCK for w in why):
            continue
        m = num(c.get("mult")) or 0.0
        f = {k: v for k, v in c["f"].items() if num(v) is not None}
        out.append({"scan": t0, "t": t1, "a": str(c.get("a")), "s": str(c.get("s") or "")[:24], "pass": bool(c.get("pass")),
                    "sc": num(c.get("sc")), "rank": num(c.get("rank")), "why": why, "mc": mc, "liq": liq, "mult": m,
                    "gone": bool(c.get("gone")) or m < 0.02, "f": f})
    return out


def build_bt(d):
    fns = sorted(fn for fn in glob.glob(os.path.join(d, "*.json")) if os.path.basename(fn) >= "2026-10-22T09")
    rows = []
    with Pool(4) as pool:
        for part in pool.imap_unordered(one, fns, chunksize=50):
            rows.extend(part)
    rows.sort(key=lambda r: (r["scan"], r["a"]))
    return rows


def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_pick(res):
    pos, ex = {}, {}
    for fn in glob.glob(os.path.join(res, "db", "memepos", "*.json")):
        d = load(fn)
        if isinstance(d, dict) and d.get("grp") == "hold" and (num(d.get("t")) or 0) >= FROM:
            pos[os.path.basename(fn)[:-5]] = d
    for fn in glob.glob(os.path.join(res, "db", "memeexit", "*.json")):
        d = load(fn)
        if isinstance(d, dict) and d.get("pos") in pos:
            ex.setdefault(d["pos"], []).append(d)
    out = []
    for pid, p in pos.items():
        sh = load(os.path.join(res, "db", "memeshadow", pid + ".json"))
        exits = sorted(ex.get(pid, []), key=lambda e: num(e.get("t")) or 0)
        left = 1.0 - sum(num(e.get("frac")) or 0 for e in exits)
        back = sum(num(e.get("eur")) or 0 for e in exits)
        out.append({"pid": pid, "p": p, "exits": exits, "real": round(back - (num(p.get("ticket")) or 50.0), 2) if left < 1e-6 else None,
                    "shadow": sh if isinstance(sh, dict) and sh.get("state") == "ok" else None})
    return sorted(out, key=lambda r: num(r["p"].get("entryAt")) or num(r["p"].get("t")))


def build_lern(res):
    out = []
    for fn in sorted(glob.glob(os.path.join(res, "db", "memelern", "*.json"))):
        d = load(fn)
        if isinstance(d, dict):
            out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt", required=True)
    ap.add_argument("--res", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pick, lern = build_pick(a.res), build_lern(a.res)
    print("pick buys", len(pick), "lern buys", len(lern), flush=True)
    bt = build_bt(a.bt)
    print("bt rows", len(bt), "scans", len({r["scan"] for r in bt}), flush=True)
    for name, obj in (("bt", bt), ("pick", pick), ("lern", lern)):
        with open(os.path.join(a.out, name + ".pkl"), "wb") as f:
            pickle.dump(obj, f, protocol=4)


if __name__ == "__main__":
    main()
