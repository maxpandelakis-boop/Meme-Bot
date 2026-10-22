"""Shared loading for the winner/loser study (fake money only): history2 hourly rows with outcomes, the universe and the splits."""
import glob, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memebot as M
from check_history2 import exit_mult, bot_gates

DAY = 86_400_000
T0 = 1786320000000            # 2026-08-10 00:00 UTC
HOLDOUT = 1790294400000       # 2026-09-25 00:00 UTC: graduations from here are the final holdout, looked at once


def eur(m):
    return M.clamp(M.tip_net(max(0.0, m)), M.EUR_CLIP[0], M.EUR_CLIP[1])


def load(h2):
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(h2, "hourly", "hourly_*.parquet")))], ignore_index=True)
    d = d[d["h"] <= 24].sort_values(["mint", "ts"]).reset_index(drop=True)
    hold = d["px1"] / d["price_usd"]
    ok1 = hold.notna() & ~d["gap_pre"] & ~d["gap_1"]
    ok6 = ~d["gap_pre"] & ~d["gap_6"] & d["last6"].notna()
    eh = np.array([eur(m) if m == m else np.nan for m in hold])
    d["eur_hold"] = np.where(ok1, eh, np.nan)
    st, tp = d["stop30_min"].to_numpy(), d["tp11_min"].to_numpy()
    A = np.where(~np.isnan(st) & (np.isnan(tp) | (st <= tp)), d["stop30_x"], np.where(~np.isnan(tp), 11.0, d["last6"]))
    d["eur_A"] = np.where(ok6, [eur(m) for m in A], np.nan)
    d["hold_x"] = hold
    d["zero"] = hold < 0.02
    d["hit3"] = d["tp3_min"].notna()
    d["lose80"] = (d["lo6"] <= 0.2) & ~d["hit3"]
    d["day"] = ((d["ts"] - T0) // DAY).astype(int)
    d["gday"] = ((d["grad_ms"] - T0) // DAY).astype(int)
    d["gates"] = bot_gates(d)
    # the study universe: what a bot with the kept gates (liquidity/volume, $100k floor, crash gate) sees from 1 h to 24 h old
    mc, c1, c6, c24 = d["market_cap_usd"], d["price_change_1h"], d["price_change_6h"], d["price_change_24h"]
    d["univ"] = ((d["liquidity_usd"] >= 15_000) & (d["volume_24h"] >= 15_000) & (mc >= 100_000) & (mc <= 5_000_000)
                 & ~(c1 <= -10) & ~(c6 <= -50) & ~(c24 <= -70) & ~d["gap_pre"])
    return d
