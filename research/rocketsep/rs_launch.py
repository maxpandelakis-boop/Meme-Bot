"""Part 0a: what the full rockets among every launch of w3/w4 have in common (fake money only, description only;
research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md).

  python3 research/rocketsep/rs_launch.py <data dir> <out dir>

Every pump.fun launch of 10 Aug-6 Oct (branch rocketslaunches, Slinky21/Pumpfun_v2_dataset, CC-BY-4.0, "Data provided by [Slink21]";
mayhem mode left out as in PR #55). Full rocket = the coin graduated and, from its close 30 minutes after the graduation, its high in
the next 24 h reaches 10x that price (history2 five-minute candles, branch monthsh2; wicks beyond 5x the close count as the close).
Writes <out dir>/launch.json. No network."""
import glob, json, os, re, sys
import numpy as np, pandas as pd

MIN, H, DAY, BAR = 60_000, 3_600_000, 86_400_000, 300_000
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ｦ-ﾟ]")
TWEET = re.compile(r"/status(?:es)?/\d{6,}")


def count_before(key, t, ev_key, ev_t, span):
    big = np.int64(10 ** 13)
    ev = np.sort(ev_key.astype(np.int64) * big + ev_t.astype(np.int64))
    q = key.astype(np.int64) * big + t.astype(np.int64)
    return (np.searchsorted(ev, q, side="left") - np.searchsorted(ev, q - span, side="left")).astype(float)


def rockets_after_grad(dd):
    meta = pd.read_parquet(os.path.join(dd, "monthsh2", "meta_h2.parquet"))
    gm = dict(zip(meta["pool"], meta["t"].astype(np.int64)))
    mint = dict(zip(meta["pool"], meta["mint"]))
    out = {}
    for f in sorted(glob.glob(os.path.join(dd, "monthsh2", "bars_*.parquet"))):
        b = pd.read_parquet(f, columns=["pool", "t", "h", "c"])
        for pool, g in b.groupby("pool", sort=False):
            if pool not in gm:
                continue
            t = g["t"].to_numpy(np.int64)
            o = np.argsort(t)
            t, h, c = t[o], g["h"].to_numpy(float)[o], g["c"].to_numpy(float)[o]
            ok = np.isfinite(c) & (c > 0)
            t, h, c = t[ok], h[ok], c[ok]
            h = np.where(np.isfinite(h) & (h <= 5 * c), np.fmax(h, c), c)
            t30 = gm[pool] + 30 * MIN
            k = np.searchsorted(t + BAR, t30, "right") - 1          # the last candle that ended by +30 min
            if k < 0:
                continue
            p30 = c[k]
            s = (t >= t30 - BAR) & (t < t30 + 24 * H) & (np.arange(len(t)) > k)
            if not s.any():
                continue
            hi = h[s].max()
            cend = c[s][-1]
            out[mint[pool]] = (hi / p30, cend / p30)
    return out


def main(dd, od):
    L = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(dd, "rocketslaunches", "L_*.parquet")))], ignore_index=True)
    L = L.drop_duplicates("mint").reset_index(drop=True)
    L["t"] = L["t"].astype(np.int64) * 1000
    cr = L["creator"].fillna("").astype(str)
    has_cr = (cr != "").to_numpy()
    code = pd.factorize(cr)[0].astype(np.int64)
    gt = pd.to_numeric(L["grad_t"], errors="coerce").to_numpy()
    gscale = 1000 if np.nanmedian(gt) < 1e11 else 1
    gi = np.isfinite(gt)
    t = L["t"].to_numpy(np.int64)
    L["creator_launches30"] = np.where(has_cr, count_before(code, t, code[has_cr], t[has_cr], 30 * DAY), np.nan)
    L["creator_grads30"] = np.where(has_cr, count_before(code, t, code[gi & has_cr], (gt[gi & has_cr] * gscale).astype(np.int64), 30 * DAY), np.nan)
    allt = np.sort(t)
    L["launches_1h"] = (np.searchsorted(allt, t, "left") - np.searchsorted(allt, t - H, "left")).astype(float)
    nm = L["name"].fillna("").astype(str) + " " + L["symbol"].fillna("").astype(str)
    L["cjk"] = nm.map(lambda s: 1.0 if CJK.search(s) else 0.0)
    dt = pd.to_datetime(L["t"], unit="ms", utc=True)
    L["hour"] = dt.dt.hour.astype(float)
    L["weekend"] = (dt.dt.dayofweek >= 5).astype(float)
    L["name_len"] = L["name"].fillna("").astype(str).str.len().astype(float)
    L["sym_len"] = L["symbol"].fillna("").astype(str).str.len().astype(float)
    T = L[L["w"].isin(["w3", "w4"])].copy()
    lm = pd.read_parquet(os.path.join(dd, "rocketslmeta", "lmeta.parquet")).drop_duplicates("mint").set_index("mint")
    okf = lm["f_name"].notna() | lm["f_twitter"].notna() | lm["f_website"].notna() | lm["f_desc_len"].notna()
    lm = lm[okf]
    j = T["mint"].map
    tw = j(lm["f_twitter"]).fillna("").astype(str).str.strip()
    tg = j(lm["f_telegram"]).fillna("").astype(str).str.strip()
    ws = j(lm["f_website"]).fillna("").astype(str).str.strip()
    read = T["mint"].isin(lm.index).to_numpy()
    T["m_links"] = np.where(read, (tw != "").astype(int) + (tg != "").astype(int) + (ws != "").astype(int), np.nan)
    T["m_xtype"] = np.where(read, np.where(tw.str.contains(TWEET), 1, np.where(tw != "", 2, 0)), np.nan)
    T["m_desc_len"] = np.where(read, pd.to_numeric(j(lm["f_desc_len"]), errors="coerce"), np.nan)
    T["m_video"] = np.where(read, (j(lm["f_video"]).fillna("").astype(str).str.strip() != "").astype(float), np.nan)
    im = pd.read_parquet(os.path.join(dd, "rocketslimages", "images.parquet")).drop_duplicates("mint")
    im = im[im["img_ok"].fillna(False).astype(bool)].set_index("mint")
    groups = ["animal_photo", "animal_drawn", "person_photo", "character_drawn", "text_logo", "object_scene"]
    T["i_group"] = T["mint"].map(im["group"].map({g: k for k, g in enumerate(groups)})).astype(float)
    T["i_animated"] = T["mint"].map(im["animated"].map(lambda x: float(bool(x)) if x is not None else np.nan)).astype(float)
    rk = rockets_after_grad(dd)
    gr = T["graduated"].fillna(0).to_numpy() > 0
    hi = T["mint"].map({m: v[0] for m, v in rk.items()}).to_numpy(float)
    T["has_path"] = np.isfinite(hi)
    T["full_rocket"] = gr & (hi >= 10)
    T["grad"] = gr
    res = {"launches": {w: int((T["w"] == w).sum()) for w in ("w3", "w4")},
           "graduated": {w: int((gr & (T["w"] == w).to_numpy()).sum()) for w in ("w3", "w4")},
           "graduated_with_path": {w: int((gr & T["has_path"].to_numpy() & (T["w"] == w).to_numpy()).sum()) for w in ("w3", "w4")},
           "full_rockets": {w: int((T["full_rocket"] & (T["w"] == w)).sum()) for w in ("w3", "w4")},
           "metadata_read": {w: int((read & (T["w"] == w).to_numpy()).sum()) for w in ("w3", "w4")},
           "pictures_read": {w: int((T["i_group"].notna() & (T["w"] == w)).sum()) for w in ("w3", "w4")}, "facts": {}}
    print(res, flush=True)
    B = {"creator_launches30": ([-0.5, 0.5, 2.5, 20.5, np.inf], ["0 (first launch)", "1-2", "3-20", "over 20"]),
         "creator_grads30": ([-0.5, 0.5, 2.5, np.inf], ["0", "1-2", "3+"]),
         "launches_1h": ([-1, 400, 700, 1000, np.inf], ["<=400", "401-700", "701-1000", ">1000"]),
         "cjk": ([-0.5, 0.5, 1.5], ["no", "yes"]),
         "hour": ([-0.5, 5.5, 11.5, 17.5, 23.5], ["0-6", "6-12", "12-18", "18-24"]),
         "weekend": ([-0.5, 0.5, 1.5], ["weekday", "weekend"]),
         "name_len": ([-0.5, 4.5, 10.5, 20.5, np.inf], ["<=4", "5-10", "11-20", ">20"]),
         "sym_len": ([-0.5, 3.5, 5.5, 8.5, np.inf], ["<=3", "4-5", "6-8", ">8"]),
         "m_links": ([-0.5, 0.5, 1.5, 2.5, 3.5], ["0", "1", "2", "3"]),
         "m_xtype": ([-0.5, 0.5, 1.5, 2.5], ["none", "post", "profile/community"]),
         "m_desc_len": ([-0.5, 0.5, 50.5, 200.5, np.inf], ["0", "1-50", "51-200", "over 200"]),
         "m_video": ([-0.5, 0.5, 1.5], ["no", "yes"]),
         "i_group": ([-0.5 + k for k in range(7)], groups),
         "i_animated": ([-0.5, 0.5, 1.5], ["no", "yes"])}
    for f, (cuts, labs) in B.items():
        x = T[f].to_numpy(float)
        bk = np.digitize(x, cuts) - 1
        rows = {}
        for w in ("w3", "w4"):
            sw = (T["w"] == w).to_numpy() & np.isfinite(x)
            fr = T["full_rocket"].to_numpy()
            for i, lab in enumerate(labs):
                s = sw & (bk == i)
                rest = sw & (bk != i)
                if s.sum() == 0:
                    continue
                r_in = fr[s].mean()
                r_out = fr[rest].mean() if rest.any() else np.nan
                rows.setdefault(lab, {})[w] = {"n": int(s.sum()), "gradPct": round(100 * gr[s].mean(), 3),
                                               "fullRocketsPer10k": round(1e4 * r_in, 2), "nRockets": int(fr[s].sum()),
                                               "ratioVsRest": round(float(r_in / r_out), 2) if r_out and r_out > 0 else None}
        res["facts"][f] = rows
    # all cheap facts together: LightGBM fit on w3, judged on w4
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    feats = list(B)
    Xf = T[feats].to_numpy(np.float32)
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
    y4 = y[w4]
    o = np.argsort(-p)
    top = {}
    for q in (0.001, 0.01, 0.05):
        k = max(1, int(round(q * len(p))))
        top["top%.1f%%" % (100 * q)] = {"launches": k, "fullRockets": int(y4[o[:k]].sum()), "per10k": round(1e4 * y4[o[:k]].mean(), 1),
                                        "graduatedPct": round(100 * T["grad"].to_numpy()[w4][o[:k]].mean(), 2)}
    res["model"] = {"auc_w4": round(float(roc_auc_score(y4, p)), 3), "trees": int(bst.best_iteration),
                    "base_per10k_w4": round(1e4 * y4.mean(), 2), "top": top,
                    "gain": {f: round(float(g), 1) for f, g in sorted(zip(feats, bst.feature_importance("gain")), key=lambda x: -x[1])}}
    # among the graduations only: P(full rocket | graduated) by the same facts
    print(json.dumps(res["model"], indent=0), flush=True)
    json.dump(res, open(os.path.join(od, "launch.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
