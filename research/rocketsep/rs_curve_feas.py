"""Exploration (not a money test): could the Part 0a launch model's top picks be bought on the bonding curve before they graduate?

  python3 research/rocketsep/rs_curve_feas.py <data dir> <out dir>      -> <out dir>/curve_feas.json

Same launches, facts and model as rs_launch.py (fit on w3, scored on w4, seed 7). For the w4 launches it ranks highest, how many
graduated, and how long after the launch: a coin whose curve fills in the first minute is gone before an outsider can buy, one that
takes 5+ minutes leaves time to buy on the curve. We have no curve trades, so no buy price and no money here: that is the data a
paid source would add."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rs_launch as RL                                        # noqa: E402

FEATS = ["creator_launches30", "creator_grads30", "launches_1h", "cjk", "hour", "weekend", "name_len", "sym_len", "m_links",
         "m_xtype", "m_desc_len", "m_video", "i_group", "i_animated"]


def main(dd, od):
    import lightgbm as lgb
    T = RL.build(dd)
    gt = T["grad_t"].astype(float).to_numpy()
    gt = gt * (1000 if np.nanmedian(gt) < 1e11 else 1)
    cmin = (gt - T["t"].to_numpy(float)) / 60_000.0                 # minutes from the launch to the graduation
    Xf = T[FEATS].to_numpy(np.float32)
    y = T["full_rocket"].to_numpy()
    w3, w4 = (T["w"] == "w3").to_numpy(), (T["w"] == "w4").to_numpy()
    tt = T["t"].to_numpy()
    cut = np.quantile(tt[w3], 0.85)
    tr, va = w3 & (tt < cut), w3 & (tt >= cut)
    prm = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=500, feature_fraction=0.8, bagging_fraction=0.8,
               bagging_freq=1, lambda_l2=10.0, metric="auc", seed=7, num_threads=3, verbose=-1)
    bst = lgb.train(prm, lgb.Dataset(Xf[tr], y[tr].astype(float)), 1000, valid_sets=[lgb.Dataset(Xf[va], y[va].astype(float))],
                    callbacks=[lgb.early_stopping(100, verbose=False)])
    p = bst.predict(Xf[w4], num_iteration=bst.best_iteration)
    g4, y4, c4 = T["grad"].to_numpy()[w4], y[w4], cmin[w4]
    o = np.argsort(-p)
    res = {"w4_launches": int(w4.sum()), "trees": int(bst.best_iteration), "groups": {}}
    for nm, k in (("top0.1%", int(round(0.001 * len(p)))), ("top1%", int(round(0.01 * len(p)))), ("top5%", int(round(0.05 * len(p)))),
                  ("all", len(p))):
        s = o[:k]
        g, r, c = g4[s], y4[s], c4[s]
        cg = c[g & np.isfinite(c)]
        row = {"launches": int(k), "graduated": int(g.sum()), "gradPct": round(100 * g.mean(), 2), "fullRockets": int(r.sum())}
        if len(cg):
            row["curveMinQuantiles"] = {q: round(float(np.quantile(cg, q)), 2) for q in (0.25, 0.5, 0.75)}
            for lo, hi_, lab in ((-1e9, 1, "under1min"), (1, 5, "1to5min"), (5, 60, "5to60min"), (60, 1e12, "over60min")):
                m = g & np.isfinite(c) & (c >= lo) & (c < hi_)
                row[lab] = {"graduated": int(m.sum()), "fullRockets": int((m & r).sum()),
                            "perLaunch10k": round(1e4 * m.mean(), 1)}
        res["groups"][nm] = row
        print(nm, row, flush=True)
    json.dump(res, open(os.path.join(od, "curve_feas.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
