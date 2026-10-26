#!/usr/bin/env python3
"""seeker_watch.py: the Rocket seeker's minute (fake money only: it scores coins and books paper trades in its own account, it never
buys, signs or sends anything). seeker.yml runs `tick` once a minute in GitHub Actions; seeker.py holds the logic, seeker_model.json
the model (research/seeker/PREREG-SEEKER-2026-10-26.md). The Pick, the Sell bot, the Radar account and the Learning Pick never read
what it writes, and it reads nothing of theirs but the launch radar's records.

One tick:
  1. the coins: the launch radar's records (branch radar-data, db/memeradar/*.json, 48 hours) of PumpSwap graduations; their names
     give the theme heat, their launch readings the launch facts (seeker.facts)
  2. each graduation whose pool is 30 to 45 minutes old and not scored yet (MAX_SCORE a tick, the oldest first): DexScreener's pair
     (liquidity at least $10,000, a price), GeckoTerminal's one-minute candles since the pool opened (the side that prices the coin,
     memebot.unit_ok), seeker.features as of 30 minutes, seeker.score; at or over the model's cut it buys the coin once on paper (20
     at DexScreener's price). A coin it could not price yet is tried again the next minute until 43 minutes, then counted as missed
  3. every open position: the candles since its last look, Rocket hold on their closes (seeker.Book.update)
  4. <dir>/seeker.json (the account, the last scores, the counts) and <dir>/log/<UTC day>.jsonl (every score with its inputs, every
     sale) go to the branch seeker-data; the scan job copies seeker.json into the app's page. No push.
usage: python3 seeker_watch.py tick --dir sk --radar radar-data-dir [--now ms] [--mock DIR]
  --mock DIR reads every answer from DIR (selftest_seeker): ds.json, gt_<pool>_ohlcv.json
"""
import argparse, datetime as dt, glob, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import seeker as S
import memebot as M
import rocket_watch as RW       # read only: its HTTP client, DexScreener and GeckoTerminal readers

MODEL = os.path.join(HERE, "seeker_model.json")
MAX_SCORE = 10                  # coins scored a tick (one GeckoTerminal call each)
RECENT = 40                     # scores kept in seeker.json for the app
KEEP_MS = 3 * S.H               # how long a scored or missed coin is remembered (its window is 15 minutes)
MIN = S.MIN


def log(s):
    print(s, file=sys.stderr, flush=True)


def records(radar_dir):
    """The launch radar's records of PumpSwap graduations: {address: record} (the newest file's record of a coin wins)."""
    out = {}
    for fn in sorted(glob.glob(os.path.join(radar_dir, "db", "memeradar", "*.json"))):
        try:
            doc = json.load(open(fn))
        except (OSError, ValueError):
            continue
        for a, rec in (doc.get("coins") or {}).items():
            if isinstance(rec, dict) and rec.get("dex") == "pumpswap" and S.num(rec.get("pool")) and rec.get("pair"):
                out[a] = dict(rec, addr=a)
    return out


def candles(http, pool, since, now, px, side=None):
    """GeckoTerminal's one-minute candles of the side that prices the coin (base first, or the side used before), checked against
    DexScreener's price px (memebot.unit_ok); ([], None) when neither side does or none came. Without a price this minute the side
    used before is read unchecked (an open position's coin may be far from its buy price by now)."""
    if not px and side in M.GT_SIDES:
        cs = RW.gt_candles(http, pool, since, now, side)
        return (sorted(cs), side) if cs else ([], None)
    first = side if side in M.GT_SIDES else "base"
    for s in [first] + [x for x in M.GT_SIDES if x != first]:
        cs = RW.gt_candles(http, pool, since, now, s)
        if cs and M.unit_ok(cs, now, px):
            return sorted(cs), s
        if not cs:
            return [], None
    return [], None


def load(d):
    try:
        st = json.load(open(os.path.join(d, "seeker.json")))
    except (OSError, ValueError):
        st = {}
    return st if isinstance(st, dict) else {}


def tick(d, radar_dir, now, mock=None):
    http = RW.Http(mock)
    model = json.load(open(MODEL))
    cut = model["cut"]
    st = load(d)
    book = S.Book(st.get("book"))
    since = S.num(st.get("since")) or now
    scored = {a: t for a, t in (st.get("scored") or {}).items() if now - (S.num(t) or 0) < KEEP_MS}
    missed = {a: t for a, t in (st.get("missed") or {}).items() if now - (S.num(t) or 0) < KEEP_MS}
    cnt = {k: int(S.num((st.get("counts") or {}).get(k)) or 0) for k in ("scored", "bought", "missed", "noPair", "lowLiq", "noCandles")}
    recent = [r for r in st.get("recent") or [] if isinstance(r, dict)]
    recs = records(radar_dir)
    theme = S.Theme(recs.values())
    due = []
    for a, r in recs.items():
        pool = S.num(r["pool"])
        age = (now - pool) / MIN
        if a in scored or a in missed or book.bought(a):
            continue
        if S.E_MIN <= age <= S.LATE_MIN:
            due.append((pool, a, r))
        elif age > S.LATE_MIN and pool + S.E_MIN * MIN >= since and age <= S.LATE_MIN + 120:
            missed[a] = now                 # its window passed while the seeker ran and nobody scored it (a late radar record, a gap)
            cnt["missed"] += 1
    due.sort()
    pairs = RW.ds_pairs(http, sorted({a for _, a, _ in due[:MAX_SCORE]} | set(book.open))) if due or book.open else {}
    rows = []
    for pool_ms, a, r in due[:MAX_SCORE]:
        age = (now - pool_ms) / MIN
        last_try = age >= S.LATE_MIN - 2
        p = RW.pick_pair(pairs.get(a), r.get("pair"))
        row = {"t": int(now), "addr": a, "sym": r.get("sym"), "age": round(age, 1)}
        if not p:
            if last_try:
                scored[a] = now; cnt["noPair"] += 1
                rows.append(dict(row, why="no pair"))
            continue
        liq, px = S.num((p.get("liquidity") or {}).get("usd")), S.num(p.get("priceUsd"))
        if (liq or 0) < S.LIQ_MIN or not px:
            scored[a] = now; cnt["lowLiq"] += 1
            rows.append(dict(row, why="liquidity", liq=round(liq or 0)))
            continue
        pool = p.get("pairAddress") or r["pair"]
        cs, side = candles(http, pool, pool_ms, now, px)
        f = S.features(r, cs, theme) if cs else None
        if f is None:
            if last_try:
                scored[a] = now; cnt["noCandles"] += 1
                rows.append(dict(row, why="no candles"))
            continue
        sc = S.score(model, f)
        scored[a] = now
        cnt["scored"] += 1
        row.update(score=round(sc, 5), px=px, liq=round(liq), p0=f["_p0"], bars=f["_bars"], buy=False,
                   f={k: (round(f[k], 4) if S.fin(f.get(k)) else None) for k in model["features"]})
        pos = book.buy(a, r.get("sym"), pool, px, now, sc, cut) if sc >= cut else None
        if pos:
            pos["tok"] = side
            row["buy"] = True
            cnt["bought"] += 1
            log("  paper buy %s (%s) score %.4f >= %.4f at %s" % (r.get("sym"), a, sc, cut, px))
        rows.append(row)
    closed = []
    for a, pos in list(book.open.items()):
        p = RW.pick_pair(pairs.get(a), pos.get("pool"))
        px = S.num((p or {}).get("priceUsd"))
        last = S.num(pos.get("lastT")) or pos["t"]
        cs, side = candles(http, pos["pool"], last - MIN, now, px or (None if pos.get("tok") else pos["px"]), pos.get("tok"))
        if side:
            pos["tok"] = side
        # a minute is judged once it ended: the newest candle may still run
        done = [(int(c[0]), float(c[4])) for c in cs if c[0] + MIN <= now]
        pos["seen"] = int(now)
        out = book.update(a, now, done, px)
        if out:
            closed.append(out)
            log("  paper sell %s x%.2f (%s) %+.2f" % (out.get("sym"), out["mult"], out["why"], out["eur"]))
    recent = (rows + recent)[:RECENT]
    doc = {"v": 1, "t": int(now), "since": int(since), "cut": cut, "book": book.doc(), "scored": scored, "missed": missed, "counts": cnt,
           "recent": [{k: x.get(k) for k in ("t", "addr", "sym", "age", "score", "buy", "why") if k in x} for x in recent],
           "tick": {"due": len(due), "scored": sum(1 for x in rows if "score" in x), "bought": sum(1 for x in rows if x.get("buy")),
                    "closed": len(closed), "calls": http.calls, "records": len(recs)},
           "model": {k: model.get(k) for k in ("made", "rows", "src", "rule", "top")}}
    os.makedirs(os.path.join(d, "log"), exist_ok=True)
    with open(os.path.join(d, "seeker.json.tmp"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(os.path.join(d, "seeker.json.tmp"), os.path.join(d, "seeker.json"))
    if rows or closed:
        day = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        with open(os.path.join(d, "log", day + ".jsonl"), "a") as fh:
            for x in rows:
                fh.write(json.dumps(x, separators=(",", ":")) + "\n")
            for x in closed:
                fh.write(json.dumps(dict(x, closed=True), separators=(",", ":")) + "\n")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tick"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--radar", required=True)
    ap.add_argument("--now", type=float)
    ap.add_argument("--mock")
    a = ap.parse_args(argv)
    os.makedirs(a.dir, exist_ok=True)
    doc = tick(a.dir, a.radar, a.now or time.time() * 1000, a.mock)
    tk = doc["tick"]
    # "changed": a buy or a sale this minute (seeker.yml saves to seeker-data at once then, else every few minutes)
    print(json.dumps({"tick": tk, "summary": doc["book"]["summary"], "changed": bool(tk["bought"] or tk["closed"])}))


if __name__ == "__main__":
    main()
