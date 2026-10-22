"""Before building a live rocket score into the radar (fake money only): does the rocket hunter (addendum 2, B) keep its edge with
only the numbers the radar could get live from GeckoTerminal minute candles (open, high, low, close, volume in USD; no buy/sell
split, no trade counts, no wallet histories) plus DexScreener's market cap and liquidity and BTC/SOL? Information only: the
holdout was already looked at for B, so only the forward test of the live score can prove anything.
usage: python3 research/winlose/rocket_live_check.py <scratch>"""
import os, sys
import numpy as np, pandas as pd
sys.argv = sys.argv[:2]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import partC as C

LIVE = ["ret_5", "ret_15", "ret_30", "ret_60", "ret_120", "ret_240", "ret_grad", "dd_ath", "min_since_ath", "from_low", "rsi_1m", "rsi_5m",
        "rsi_15m", "vol_spike_5", "vol_spike_15", "vol_trend_60", "active_min_60", "vola_60", "max_drop_1m_60", "max_jump_1m_60", "bb_pos",
        "trend_slope", "trend_r2", "body_5", "upwick_5", "lowick_5", "body_15", "upwick_15", "lowick_15", "engulf_bull", "engulf_bear",
        "support_touches", "dist_support", "resist_touches", "dist_resist", "first_hour_ret", "first_hour_sol", "first_hour_maxdd",
        "mc", "liqmc", "volmc", "btc_1h", "btc_24h", "sol_1h", "sol_24h"]
if "--plus" in os.environ.get("LIVE_SET", ""):
    LIVE += ["trades_60", "avg_trade_sol_60", "grads_24h", "regime_eur", "regime_hit3"]     # DexScreener txns, pump.fun list, own records
if "--gt" in os.environ.get("LIVE_SET", ""):
    # GeckoTerminal's trades endpoint (last 300 trades: buyer address, buy/sell, USD size) + the radar's own memory: no wallet history
    LIVE += ["buy_imb_5", "buy_imb_15", "buy_imb_60", "buys_trend_30", "trades_60", "avg_trade_sol_60", "w_buyers", "w_sol", "w_top_share",
             "w_recent_share", "grads_24h", "regime_eur", "regime_hit3"]
if os.path.exists(os.path.join(sys.argv[1], "grid_live.pkl")):
    C.G = pd.read_pickle(os.path.join(sys.argv[1], "grid_live.pkl")).sort_values("ts").reset_index(drop=True)
    C.dev = C.G[C.G["grad_ms"] < C.HOLD]
RECENT = ["r_buyers", "r_sol", "r_top_share", "r_avg_buy", "r_known_share", "r_smart_n", "r_smart_share", "r_smartbig_n", "r_avg_lroi"]
ALLW = ["w_buyers", "w_sol", "w_top_share", "w_fresh_share", "w_exp_share", "w_smart_n", "w_smart_share", "w_smartbig_n", "w_avg_lroi",
        "w_recent_share", "w_recent_smart", "atomic_60"]
if "--free" in os.environ.get("LIVE_SET", ""):
    LIVE = [k for k in LIVE if not k.startswith("w_")] + RECENT          # last 300 trades + a seeded wallet memory
if "--helius" in os.environ.get("LIVE_SET", ""):
    LIVE = [k for k in LIVE if not k.startswith("w_")] + RECENT + ALLW   # every buyer since the graduation + their history
C.NUM[:] = [k for k in LIVE if k in C.G.columns]
print(len(C.NUM), "live numbers")
dev, hold = C.dev, C.G[C.G["grad_ms"] >= C.HOLD]
acc = {c: [] for c in C.CUTS}
for st in np.arange(C.G["grad_ms"].min() + 14 * C.DAY, C.HOLD, 7 * C.DAY):
    tr = dev[dev["grad_ms"] < st - 2 * C.DAY]
    te = dev[(dev["grad_ms"] >= st) & (dev["grad_ms"] < min(st + 7 * C.DAY, C.HOLD))]
    s_tr, s_te = C.scores(tr, te)
    for c in C.CUTS:
        acc[c].append(C.picks(te, s_te["B"], np.quantile(s_tr["B"], 1 - c)))
for c in C.CUTS:
    print("dev B", c, C.summary(pd.concat(acc[c])))
s_tr, s_te = C.scores(dev, hold)
for c in C.CUTS:
    print("hold B", c, C.summary(C.picks(hold, s_te["B"], np.quantile(s_tr["B"], 1 - c))))
