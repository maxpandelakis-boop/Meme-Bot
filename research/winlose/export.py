"""Winner/loser study (fake money only): the app's display file winlose.json from partA.json, choice.json and holdout.json.
usage: python3 research/winlose/export.py <scratch> [social summary json]  -> ./winlose.json"""
import json, os, sys
import pandas as pd

S = sys.argv[1]
LABEL = {
    "trades_60": "trades in the last hour", "avg_trade_sol_60": "average trade size, last hour", "trend_r2": "how straight the 2 h trend is",
    "buyers_1h": "buyers in the last hour", "sellers_1h": "sellers in the last hour", "ret_5": "price change, 5 min", "ret_15": "price change, 15 min",
    "ret_30": "price change, 30 min", "ret_60": "price change, 1 h (chart)", "ret_120": "price change, 2 h", "ret_240": "price change, 4 h",
    "topbuyer": "biggest buyer's share", "rsi_1m": "RSI (1 min)", "body_5": "last 5-min candle body", "body_15": "last 15-min candle body",
    "trend_slope": "2 h trend slope", "buy_imb_5": "buy pressure, 5 min", "buy_imb_15": "buy pressure, 15 min", "bb_pos": "Bollinger position",
    "min_since_ath": "minutes since the high", "resist_touches": "touches of the resistance", "vol_spike_5": "volume spike, 5 min",
    "vol_spike_15": "volume spike, 15 min", "c5m": "screener change, 5 min", "first_hour_sol": "SOL traded in the first hour",
    "w_buyers": "wallets that bought before", "buyer_seller_ratio": "buyers per seller, last hour", "max_jump_1m_60": "biggest 1-min jump",
    "dist_support": "distance above support", "from_low": "distance above the 4 h low", "first_hour_maxdd": "first hour's deepest fall",
    "w_sol": "SOL the wallets put in", "w_avg_lroi": "earlier results of those wallets", "buys_trend_30": "buys, last 30 min vs before",
    "upwick_15": "upper wick, 15-min candle", "lowick_15": "lower wick, 15-min candle", "mc_chg": "market cap vs an hour ago", "nn_win": "look-alike charts: winner share", "nn_lose": "look-alike charts: loser share",
    "nn_eur": "look-alike charts: average result", "w_smart_share": "share of smart wallets", "w_fresh_share": "share of fresh wallets",
    "w_top_share": "biggest wallet's share", "max_drop_1m_60": "biggest 1-min drop", "vola_60": "volatility, last hour", "regime_hit3": "3x share of coins 2-3 days ago", "regime_eur": "result of coins 2-3 days ago", "ret_grad": "change since graduation",
}
R = pd.read_json(os.path.join(S, "partA.json"))
ch, ho = json.load(open(os.path.join(S, "choice.json"))), json.load(open(os.path.join(S, "holdout.json")))


def rows(comp, n):
    g = R[R["comp"] == comp].dropna(subset=["early", "late", "hold"]).copy()
    g["strength"] = (g["hold"] - .5).abs()
    g = g.sort_values(["holds", "strength"], ascending=False).head(n)
    return [{"num": r["num"], "label": LABEL.get(r["num"], r["num"]), "dev": round((r["early"] + r["late"]) / 2, 3), "hold": round(r["hold"], 3),
             "holds": bool(r["holds"]), "up": bool(r["hold"] > .5)} for _, r in g.iterrows()]


key = "%s_%g" % tuple(ch["choice"])
doc = {"v": 1, "made": "2026-10-22", "coins": 4738, "rows": 24710, "numbers": 87,
       "period": "10 Aug to 8 Oct 2026 (unseen: from 25 Sep)",
       "holds": {c: int(R[(R["comp"] == c) & R["holds"]].shape[0]) for c in ("move_vs_calm", "win_vs_lose", "win_vs_rest")},
       "move": rows("move_vs_calm", 8), "direction": rows("win_vs_lose", 5),
       "score": {"dev": ch["dev"], "dev_gates": ch["dev_gates"], "hold": ho[key], "hold_gates": ho["gates"], "verdict": "fails"}}
cb = os.path.join(S, "combined_bt.json")
if os.path.exists(cb):
    doc["combined"] = json.load(open(cb))
hc, cc = os.path.join(S, "holdoutC.json"), os.path.join(S, "choiceC.json")
if os.path.exists(hc):
    H, C = json.load(open(hc)), json.load(open(cc))
    sim = json.load(open(os.path.join(S, "simC.json"))) if os.path.exists(os.path.join(S, "simC.json")) else {}
    keep = lambda o: {k: o.get(k) for k in ("coins", "avg", "lo95", "hi95", "in_profit_of10", "hit3", "rocket10x", "zero")}
    doc["variants"] = {
        "base": keep(H["holdout"]["base"]),
        "A": {"name": "few losers", "cut": 0.05, "dev": keep(C["dev"]["A_0.05"]), "hold": keep(H["holdout"]["A_0.05"]), "sim": sim.get("A_0.05"),
              "verdict": "fails: never 100 picks on the earlier days; on unseen days 5.9 of 10 in profit but -3.08 per 20 (the losers go to zero)"},
        "B": {"name": "rocket hunter", "cut": 0.005, "dev": keep(C["dev"]["B_0.005"]), "hold": keep(H["holdout"]["B_0.005"]), "sim": sim.get("B_0.005"),
              "chosen": keep(H["holdout"]["B_0.02"]),
              "verdict": "fails as pre-registered (top 2%: -2.78 per 20); the strictest cut (top 0.5%) was positive on both parts but on 28 and 34 coins only"},
        "C": {"name": "expected profit", "cut": 0.02, "dev": keep(C["dev"]["C_0.02"]), "hold": keep(H["holdout"]["C_0.02"]), "sim": sim.get("C_0.02"),
              "verdict": "fails: +0.46 per 20 on unseen days, range -5.06 to +7.05"}}
if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
    doc["social"] = json.load(open(sys.argv[2]))
json.dump(doc, open("winlose.json", "w"), indent=1, default=float)
print(json.dumps(doc, default=float)[:1500])
