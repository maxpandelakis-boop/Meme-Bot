"""Builds forecast_ref.json for forecast.py (fake money only, display only) from the August to October 2026 rows of the branch
"history2", and checks the forecast honestly before it is shown. Written before the check was run.

Reference rows: every row with liquidity and 24h volume at least $15k and a market cap of $30k to $5M, outside recorder outages,
with a 1.7-hour result and a 6-hour path; at most ROWS_PER_COIN rows per coin (its first hours of that kind), so one busy coin
cannot fill the look-alikes.

The check, in two parts:
1. backtest: the reference built only from coins that graduated before 15 September; forecasts for the first row through the
   bot's 2h gates of every coin that graduated from then on. Reported: Brier score of each chance (to zero within 1.7 h,
   profit after fees at 1.7 h, 2x and 3x within 6 h) against the plain average of the reference (the "skill": 1 - Brier /
   Brier of the average; above 0 means the look-alikes know more than the average), the five-bin calibration, and how often the
   10-90% range of the 1.7-hour multiple held the real one (80% would be right).
2. the bot's own coins: the full reference, forecasts for every coin through the 2h gates in the big test (memesnapres, from
   7 October on, so mostly after the data; once per coin) and for the top picks among them (rank 1 of each scan), against their
   real 1.7-hour result (zero, profit, range).
The numbers go into forecast_ref.json's "check" and are shown with every forecast.
usage: python3 research/forecast_build.py <history2 dir> <memesnapres dir> <out json>
"""
import glob, json, math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memebot as M
import forecast as FC
from check_history2 import bot_gates

SPLIT = 1789430400000      # 2026-09-15 00:00 UTC, by graduation
ROWS_PER_COIN = 3


def rows_of(d):
    """history2 rows -> (feature list, outcome list, grad_ms, mint) with the forecast's seven numbers and five outcomes."""
    import numpy as np
    f = {"ageH": d["age_h"], "logMc": np.log10(d["market_cap_usd"]), "c1": d["price_change_1h"], "c6": d["price_change_6h"],
         "m5": d["price_change_5m"], "volMc": d["volume_24h"] / d["market_cap_usd"], "vol1Share": d["volume_1h"] / d["volume_24h"]}
    m1 = (d["px1"] / d["price_usd"]).to_numpy()
    cols = {k: v.to_numpy() for k, v in f.items()}
    out = []
    for i in range(len(d)):
        x = FC.features({k: cols[k][i] for k in cols})
        m = float(m1[i])
        out.append((x, [m, float(m < 0.02), float(d["tp2_min"].iat[i] == d["tp2_min"].iat[i]), float(d["tp3_min"].iat[i] == d["tp3_min"].iat[i]),
                        float(M.tip_net(m) > 0)], int(d["grad_ms"].iat[i]), d["mint"].iat[i]))
    return out


def make_ref(rows):
    feats = [r[0] for r in rows]
    med, iqr = [], []
    for j in range(len(FC.FEATS)):
        v = sorted(x[j] for x in feats if x[j] is not None)
        q = lambda p: v[int(p * (len(v) - 1))]
        med.append(q(0.5))
        iqr.append((q(0.75) - q(0.25)) or 1.0)
    out = []
    for x, o, _, _ in rows:
        out.append([None if v is None else round((v - med[j]) / iqr[j], 4) for j, v in enumerate(x)] + [round(o[0], 4)] + [int(v) for v in o[1:]])
    n = len(rows)
    base = {k: sum(r[1][j] for r in rows) / n for j, k in ((1, "zero"), (2, "x2"), (3, "x3"), (4, "profit"))}
    return {"med": med, "iqr": iqr, "rows": out, "base": base, "n_rows": n, "n_coins": len({r[3] for r in rows})}


def score(preds, outs, base):
    """Brier of the forecast and of the base rate, the skill, and five-bin calibration (forecast -> real)."""
    n = len(preds)
    b = sum((p - y) ** 2 for p, y in zip(preds, outs)) / n
    b0 = sum((base - y) ** 2 for y in outs) / n
    pairs = sorted(zip(preds, outs))
    bins = [pairs[i * n // 5:(i + 1) * n // 5] for i in range(5)]
    cal = [[round(sum(p for p, _ in x) / len(x), 3), round(sum(y for _, y in x) / len(x), 3)] for x in bins if x]
    return {"n": n, "brier": round(b, 4), "brier_base": round(b0, 4), "skill": round(1 - b / b0, 3) if b0 else None, "cal": cal}


def judge(pairs, ref, name):
    """pairs: [(forecast, (m1, zero, x2 or None, x3 or None, profit))] -> the check's numbers."""
    res = {"n": len(pairs)}
    for j, k in ((1, "zero"), (4, "profit"), (2, "x2"), (3, "x3")):
        pp = [(fc[k], o[j]) for fc, o in pairs if o[j] is not None]
        if pp:
            res[k] = score([p for p, _ in pp], [y for _, y in pp], ref["base"][k])
    inside = [fc["m1"][0] <= o[0] <= fc["m1"][2] for fc, o in pairs]
    res["range_hit"] = round(sum(inside) / len(inside), 3) if inside else None
    print("%s: %s" % (name, json.dumps(res)))
    return res


def main():
    import pandas as pd
    h2, rec, out = sys.argv[1], sys.argv[2], sys.argv[3]
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(h2, "**", "hourly_*.parquet"), recursive=True))], ignore_index=True)
    d = d.sort_values(["mint", "ts"]).reset_index(drop=True)
    ok = (~d["gap_pre"] & ~d["gap_1"] & ~d["gap_6"] & d["px1"].notna() & d["last6"].notna() & (d["price_usd"] > 0))
    pool = d[ok & (d["liquidity_usd"] >= 15_000) & (d["volume_24h"] >= 15_000) & (d["market_cap_usd"] >= 30_000) & (d["market_cap_usd"] <= 5_000_000)]
    pool = pool.groupby("mint", sort=False).head(ROWS_PER_COIN)
    rows = rows_of(pool)
    print("reference: %d rows of %d coins" % (len(rows), pool["mint"].nunique()))

    # 1. backtest: reference before 15 September, forecasts for the gate passers after it
    fit = make_ref([r for r in rows if r[2] < SPLIT])
    test = d[ok & bot_gates(d) & (d["grad_ms"] >= SPLIT)].drop_duplicates("mint", keep="first")
    pairs = []
    for x, o, _, _ in rows_of(test):
        fc = forecast_x(x, fit)
        if fc:
            pairs.append((fc, o))
    back = judge(pairs, fit, "backtest (reference before 15 Sep, gate passers after)")

    # 2. the bot's own coins: every coin through the 2h gates in the big test (its factors at the scan, its result 1.7 h later),
    #    once per coin at its first scan, and the top picks (rank 1) among them; they are from 7 October on, after most of the data
    full = make_ref(rows)
    seen, pairs2, pairs3 = set(), [], []
    for fn in sorted(glob.glob(os.path.join(rec, "*.json"))):
        doc = json.load(open(fn, encoding="utf-8"))
        if str(doc.get("rule") or "") != "m9-2h" or (FC._num(doc.get("t")) or 0) < 1791380700000:
            continue
        for c in doc.get("coins") or []:
            m = FC._num(c.get("mult"))
            if c.get("why") or m is None or not isinstance(c.get("f"), dict):
                continue
            top = c.get("rank") == 1
            if c.get("a") in seen and not top:
                continue
            fc = FC.forecast(c["f"], full)
            if not fc:
                continue
            o = (m, float(bool(c.get("gone")) or m < 0.02), None, None, float(M.tip_net(m) > 0))
            if c.get("a") not in seen:
                seen.add(c.get("a"))
                pairs2.append((fc, o))
            if top:
                pairs3.append((fc, o))
    live = judge(pairs2, full, "the bot's own gate passers (big test, first scan per coin, 1.7 h)") if pairs2 else {"n": 0}
    tops = judge(pairs3, full, "the bot's top picks (rank 1 of each scan, 1.7 h)") if pairs3 else {"n": 0}

    full["check"] = {"backtest": back, "bot_passers": live, "bot_picks": tops, "built": "research/forecast_build.py",
                     "source": "history2 rows, 10 Aug to 8 Oct 2026; Data provided by [Slink21]. Pumpfun Solana Dataset (2026). CC BY 4.0"}
    json.dump(full, open(out, "w"), separators=(",", ":"))
    print("wrote %s: %.1f MB, base %s" % (out, os.path.getsize(out) / 1e6, json.dumps(full["base"])))


def forecast_x(x, ref):
    """forecast.forecast for an already made feature list."""
    keys = ("ageH", "logMc", "c1", "c6", "m5", "volMc", "vol1Share")
    f = {"ageH": 10 ** x[0] if x[0] is not None else None, "logMc": x[1], "c1": x[2], "c6": x[3], "m5": x[4],
         "volMc": (10 ** x[5] - 1) if x[5] is not None else None, "vol1Share": x[6]}
    assert set(f) == set(keys)
    return FC.forecast(f, ref)


if __name__ == "__main__":
    main()
