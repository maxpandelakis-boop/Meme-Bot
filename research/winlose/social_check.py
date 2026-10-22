"""Winner/loser study, social probe result (fake money only): from the socialprobe branch's social.jsonl, how much talk came
BEFORE each coin's entry hour, winners against losers against the rest.  usage: python3 research/winlose/social_check.py social.jsonl [out.json]"""
import json, sys
import numpy as np, pandas as pd

rows = []
for l in open(sys.argv[1]):
    r = json.loads(l)
    t = r["ts"] / 1000.0
    g = r["grad_ms"] / 1000.0
    pf = [x for x in r.get("pf") or []]
    pre = [x for x in pf if x[0] < t]
    rows.append({"label": r["label"], "pf_ok": r.get("pf_status") == 200, "rd_ok": r.get("rd_mint_status") == 200,
                 "pf_all": len(pf), "pf_pre": len(pre), "pf_users_pre": len({x[1] for x in pre}),
                 "pf_last1h": sum(1 for x in pre if x[0] >= t - 3600), "pf_pre_grad": sum(1 for x in pre if x[0] < g),
                 "rd_mint_pre": sum(1 for x in r.get("rd_mint") or [] if x < t),
                 "rd_sym_pre": sum(1 for x in r.get("rd_sym") or [] if x < t)})
d = pd.DataFrame(rows)
print("read: pump.fun %d of %d, reddit %d of %d" % (d.pf_ok.sum(), len(d), d.rd_ok.sum(), len(d)))
cols = ["pf_pre", "pf_users_pre", "pf_last1h", "pf_pre_grad", "rd_mint_pre", "rd_sym_pre"]
t = d.groupby("label")[cols].agg(["mean", "median"]).round(2)
any_ = d.assign(**{c + "_any": d[c] > 0 for c in ("rd_mint_pre", "rd_sym_pre", "pf_last1h")}).groupby("label")[["rd_mint_pre_any", "rd_sym_pre_any", "pf_last1h_any"]].mean().round(3)
print(t.to_string()); print(any_.to_string())
from scipy.stats import mannwhitneyu
res = {}
for c in cols:
    a, b = d.loc[d.label == "win", c], d.loc[d.label == "lose", c]
    if len(a) > 5 and len(b) > 5:
        u = mannwhitneyu(a, b)
        res[c] = {"auc": round(u.statistic / (len(a) * len(b)), 3), "p": float(u.pvalue)}
print(res)
if len(sys.argv) > 2:
    json.dump({"table": t.reset_index().to_dict(), "auc": res, "read_pf": int(d.pf_ok.sum()), "read_rd": int(d.rd_ok.sum()), "n": len(d)},
              open(sys.argv[2], "w"), default=str)
