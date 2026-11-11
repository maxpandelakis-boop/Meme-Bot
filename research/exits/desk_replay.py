"""Method check (fake money only): the real trades of the two 24/7 paper desks (desk-data/desk.json) replayed by a backtest
on GeckoTerminal one-minute candles of the same coins. Asks: does a candle backtest of the desk rule (stop -8% until 2x, sell
1/x at 2x, trail 10%) give the same sells and the same money as the live desk saw? Fetches public data only; buys nothing.

usage: python3 research/exits/desk_replay.py <desk.json> <out_dir>
"""
import json, os, sys, time, urllib.request

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
UA = {"User-Agent": "trencher-desk/1.0 (paper trading research)", "Accept": "application/json"}


def get(url):
    for i in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            code = getattr(e, "code", 0)
            if code == 404:
                return None
            time.sleep(10 + 10 * i)
    return None


def fee(x):
    return 0.0 if x <= 0 else 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x


def trades(acc):
    """activity (newest first) -> [{mint, symbol, t, usd, entry, sells: [{t, kind, multiple, frac, usd, pnl}]}]"""
    out, open_ = [], {}
    for a in reversed(acc.get("activity") or []):
        if a.get("kind") in ("buy", "copy"):
            open_[a["mint"]] = {"mint": a["mint"], "symbol": a.get("symbol"), "t": a["t"], "usd": a["usd"], "entry": a["price"], "mc": a.get("mc"), "sells": []}
            out.append(open_[a["mint"]])
        elif a.get("mint") in open_:
            open_[a["mint"]]["sells"].append({k: a.get(k) for k in ("t", "kind", "multiple", "frac", "usd", "pnl")})
    return out


def candles(pool, t_to):
    j = get(f"{GT}/pools/{pool}/ohlcv/minute?aggregate=1&limit=1000&currency=usd&before_timestamp={int(t_to)}")
    time.sleep(2.5)
    rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted([[int(r[0])] + [float(x) for x in r[1:6]] for r in rows])


def replay(cs, t_buy, usd, slip, stop=0.08, half_at=2.0, trail=0.10):
    """Backtest as research/check_desk.py does it: entry = close of the minute of the buy, then minute closes."""
    m0 = int(t_buy // 60) * 60
    first = [c for c in cs if c[0] >= m0]
    if not first:
        return None
    entry_mkt = first[0][4]
    entry = entry_mkt * (1 + slip)
    tokens = (usd - fee(usd)) / entry
    got, half, peak, sells = 0.0, False, entry_mkt, []
    for c in first[1:]:
        x = c[4] / entry
        if not half:
            if x >= half_at:
                f = min(1.0, 1 / x); g = tokens * f * c[4] * (1 - slip); got += g - fee(g); tokens *= 1 - f; half = True
                sells.append({"t": c[0], "kind": "half", "multiple": x})
            elif x <= 1 - stop:
                g = tokens * c[4] * (1 - slip); got += g - fee(g); tokens = 0
                sells.append({"t": c[0], "kind": "stop", "multiple": x}); break
        elif c[4] <= peak * (1 - trail):
            g = tokens * c[4] * (1 - slip); got += g - fee(g); tokens = 0
            sells.append({"t": c[0], "kind": "trail", "multiple": x}); break
        peak = max(peak, c[4])
    return {"entry_mkt": entry_mkt, "sells": sells, "pnl": got - usd if tokens == 0 else None, "open": tokens > 0,
            "last_multiple": first[-1][4] / entry}


def main(desk_fn, out_dir):
    d = json.load(open(desk_fn, encoding="utf-8"))
    os.makedirs(out_dir, exist_ok=True)
    now = time.time()
    report = {"at": now, "desks": {}}
    for name, acc, slip in (("big", d.get("acc") or {}, 0.005), ("fresh", (d.get("fresh") or {}).get("acc") or {}, 0.01)):
        rows = []
        for tr in trades(acc):
            j = get(f"{GT}/tokens/{tr['mint']}/pools?page=1")
            time.sleep(2.5)
            pools = [(float((p.get("attributes") or {}).get("reserve_in_usd") or 0), p["attributes"]["address"],
                      (p.get("relationships") or {}).get("dex", {}).get("data", {}).get("id")) for p in (j or {}).get("data") or []]
            row = dict(tr, pools=len(pools))
            if pools:
                liq, pool, dex = max(pools)
                t_end = min(now, (tr["sells"][-1]["t"] if tr["sells"] else tr["t"]) / 1000 + 6 * 3600)
                cs = candles(pool, t_end)
                row.update(pool=pool, dex=dex, liq_now=liq, n_candles=len(cs))
                row["candles"] = [c for c in cs if tr["t"] / 1000 - 600 <= c[0] <= t_end]
                row["bt"] = replay(cs, tr["t"] / 1000, tr["usd"], slip)
            rows.append(row)
            print(name, tr["symbol"], "live", [(s["kind"], round(s["multiple"], 3)) for s in tr["sells"]],
                  "backtest", row.get("bt") and [(s["kind"], round(s["multiple"], 3)) for s in row["bt"]["sells"]], flush=True)
        report["desks"][name] = rows
    json.dump(report, open(os.path.join(out_dir, "desk_replay.json"), "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
