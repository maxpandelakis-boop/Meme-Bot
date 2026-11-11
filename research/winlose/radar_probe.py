"""Radar probe (fake money only; it books nothing, never touches the Radar account): what the live rocket hunter feeds its model.
The Radar account bought nothing in 150 rounds after the fix of 23 Oct (LIVE-CHECK-2026-10-23.md), where the test expected about 4 buys.
This saves, for the coins a round would score now, everything the round sees (DexScreener's pair, GeckoTerminal's minute candles and
last 300 trades, GeckoTerminal's pool info with its own trade counts and creation time, the launch radar's record) plus the numbers
rocket.features makes of it and the score, so the live inputs can be put next to the training grid's (early_grid.py LIVETR=300).
usage: python3 research/winlose/radar_probe.py <radar-data dir> <rocket-data dir> <out.json.gz> [max coins]"""
import gzip, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import rocket as R
import rocket_watch as W

GT_POOL = "https://api.geckoterminal.com/api/v2/networks/solana/pools/%s"


def main():
    radar, rk, out = sys.argv[1], sys.argv[2], sys.argv[3]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    now = time.time() * 1000
    http = W.Http()
    model = json.load(open(W.MODEL))
    memory = W.load_memory(rk)
    mkt, sol_usd = W.market(http)
    cand = W.candidates(radar, now)
    recs = {}
    import glob
    for fn in sorted(glob.glob(os.path.join(radar, "db", "memeradar", "*.json"))):
        try:
            for a, rec in (json.load(open(fn)).get("coins") or {}).items():
                recs[a] = rec
        except (OSError, ValueError):
            pass
    pairs = W.ds_pairs(http, sorted(cand))
    due = []
    for a, c in cand.items():
        p = W.pick_pair(pairs.get(a), c["pair"])
        if not p:
            continue
        mc = R.num(p.get("marketCap")) or R.num(p.get("fdv"))
        liq = R.num((p.get("liquidity") or {}).get("usd"))
        vol = R.num((p.get("volume") or {}).get("h24"))
        ch = p.get("priceChange") or {}
        age = (now - c["pool_ms"]) / 60_000
        if R.universe(age, mc, liq, vol, R.num(ch.get("h1")), R.num(ch.get("h6"))):
            due.append((age, a, c, p, mc, liq, vol))
    due.sort(key=lambda x: x[0])                 # the youngest first: the high scores come at 30-60 minutes
    rows = []
    for age, a, c, p, mc, liq, vol in due[:cap]:
        pool = p.get("pairAddress") or c["pair"]
        cs = W.gt_candles(http, pool, c["pool_ms"], now)
        tr = W.gt_trades(http, pool)
        info = http.get(GT_POOL % pool, "gtpool_" + pool, W.GT_GAP)
        at = (((info or {}).get("data") or {}).get("attributes") or {}) if isinstance(info, dict) else {}
        f = R.features(cs, tr, c["pool_ms"], now, sol_usd, mc, liq, vol, mkt, memory) if sol_usd else None
        sc = R.score(model, f)
        rec = recs.get(a) or {}
        rows.append({"t": now, "addr": a, "sym": c.get("sym"), "pool": pool, "pool_ms": c["pool_ms"], "age": age, "sol_usd": sol_usd,
                     "mc": mc, "liq": liq, "vol": vol, "score": sc,
                     "feat": {k: v for k, v in (f or {}).items() if isinstance(v, (int, float)) and v == v},
                     "radar": {k: rec.get(k) for k in ("mint", "pool", "first", "found", "dex", "lp", "seenAge")},
                     "instant": (rec.get("sig") or {}).get("instantPool"), "mintToPoolS": (rec.get("sig") or {}).get("mintToPoolS"),
                     "ds": {k: p.get(k) for k in ("dexId", "labels", "pairCreatedAt", "marketCap", "fdv", "liquidity", "volume", "priceChange", "txns")},
                     "gt": {k: at.get(k) for k in ("pool_created_at", "transactions", "volume_usd", "reserve_in_usd", "fdv_usd", "market_cap_usd")},
                     "candles": cs, "trades": tr})
        print("%s age %.0f score %s trades %d candles %d" % (c.get("sym"), age, sc and round(sc, 4), len(tr), len(cs)), flush=True)
    doc = {"t": now, "cut": model["cut"], "market": mkt, "candidates": len(cand), "universe": len(due), "calls": http.calls, "rows": rows}
    with gzip.open(out, "wt") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


if __name__ == "__main__":
    main()
