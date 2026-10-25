"""Rocket study, universe L (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md, amendments 6 and 7): which facts,
known at the launch, separate the pump.fun launches that take off from the rest, on months the choice never saw?

  python3 research/rockets/check_launches.py <universe dir> <market.json> [<lmeta dir>] [<images dir>] [<rocketschain dir>]
          [<rocketsimages dir>] > out.json

<universe dir> = branch rocketslaunches (launches.py build). <lmeta dir> = branch rocketslmeta (metadata files of the random
600,000). <images dir> = the pictures of the random 150,000 of those (images.py). <rocketschain dir> = branch rocketschain
(wiki_top.json, the graduations' picture links), <rocketsimages dir> = branch rocketsimages (the graduations' picture hashes).
Outcomes: L1 graduated; L2 graduated at least 10 minutes after the launch (launches graduating sooner left out of L2).
Fit w3, unseen w4 + w5, and w4 alone (amendments 7 and 8: a full month). NULL=<seed> shuffles both outcomes within each window
(a code check: nothing may pass then). No network, nothing is bought."""
import glob, json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_rockets import BUCKETS as G_BUCKETS, CIDRE, CJK, TWEET, holm, words, ztest  # noqa: E402

DAY, H = 86_400, 3_600
FIT, UNSEEN, MONTH = ("w3",), ("w4", "w5"), ("w4",)                  # amendment 8: w2 left out
OUTCOMES = ("L1", "L2")
GROUPS = ("animal_photo", "animal_drawn", "person_photo", "character_drawn", "text_logo", "object_scene")
BUCKETS = {
    "f_creator_launches30": ([-0.5, 0.5, 2.5, 20.5, np.inf], ["0", "1-2", "3-20", "over 20"]),
    "f_creator_grads30": ([-0.5, 0.5, 2.5, np.inf], ["0", "1-2", "3+"]),
    "f_dup7_grad": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_cjk": G_BUCKETS["f_cjk"], "f_hour": G_BUCKETS["f_hour"], "f_weekend": G_BUCKETS["f_weekend"],
    "f_launches1h": None, "f_sol24": None,
    "f_theme24": G_BUCKETS["f_theme24"],
    "f_nlinks": G_BUCKETS["f_nlinks"], "f_xtype": G_BUCKETS["f_xtype"], "f_news": G_BUCKETS["f_news"],
    "f_post_age": G_BUCKETS["f_post_age"], "f_img_reused": G_BUCKETS["f_img_reused"],
    "f_launch_other": G_BUCKETS["f_launch_other"], "f_video": G_BUCKETS["f_video"], "f_desc_len": G_BUCKETS["f_desc_len"],
    "f_group": ([-0.5 + k for k in range(len(GROUPS) + 1)], list(GROUPS)),
    "f_animated": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_lookalike": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_name_fit": None,
}
FACT_NO = {"f_creator_launches30": "L-F1", "f_creator_grads30": "L-F1b", "f_dup7_grad": "L-F4", "f_cjk": "L-F5",
           "f_hour": "L-F6", "f_weekend": "L-F7", "f_launches1h": "L-F8", "f_sol24": "L-F9", "f_nlinks": "L-F10",
           "f_xtype": "L-F11", "f_news": "L-F12", "f_theme24": "L-F13", "f_post_age": "L-F14", "f_img_reused": "L-F15",
           "f_launch_other": "L-F16", "f_video": "L-F17", "f_desc_len": "L-F18", "f_group": "L-F19", "f_animated": "L-F20",
           "f_lookalike": "L-F21", "f_name_fit": "L-F22"}
SAMPLE_FACTS = ("f_nlinks", "f_xtype", "f_news", "f_post_age", "f_img_reused", "f_launch_other", "f_video", "f_desc_len")
PICTURE_FACTS = ("f_group", "f_animated", "f_lookalike", "f_name_fit")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def count_before(key, t, ev_key, ev_t, span):
    """For each (key, t): how many events of the same key happened in [t - span, t). Keys are integer codes."""
    big = np.int64(10 ** 10)
    ev = np.sort(ev_key.astype(np.int64) * big + ev_t.astype(np.int64))
    q = key.astype(np.int64) * big + t.astype(np.int64)
    return (np.searchsorted(ev, q, side="left") - np.searchsorted(ev, q - span, side="left")).astype(float)


def universe(udir):
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(udir, "L_*.parquet")))], ignore_index=True)
    d = d.drop_duplicates("mint").sort_values("t").reset_index(drop=True)
    d["t"] = d["t"].astype(np.int64)
    d["L1"] = pd.to_numeric(d["graduated"], errors="coerce").astype(float)        # empty = unresolved, left out
    dt = d["grad_t"] - d["t"]
    d["L2"] = np.where(d["L1"] == 1, np.where(dt >= 600, 1.0, np.nan), d["L1"])
    d["day"] = (d["t"] // DAY).astype(int)
    return d


def launch_facts(d, sol):
    t = d["t"].to_numpy(np.int64)
    cr = d["creator"].fillna("").astype(str)
    cc = pd.factorize(cr)[0]
    has_cr = (cr != "").to_numpy()
    d["f_creator_launches30"] = np.where(has_cr, count_before(cc, t, cc[has_cr], t[has_cr], 30 * DAY), np.nan)
    gi = (d["L1"] == 1).to_numpy() & has_cr & d["grad_t"].notna().to_numpy()
    d["f_creator_grads30"] = np.where(has_cr, count_before(cc, t, cc[gi], d["grad_t"].to_numpy()[gi], 30 * DAY), np.nan)
    sym = d["symbol"].fillna("").astype(str).str.upper().str.strip()
    sc = pd.factorize(sym)[0]
    has_s = (sym != "").to_numpy()
    gs = (d["L1"] == 1).to_numpy() & has_s & d["grad_t"].notna().to_numpy()
    n7 = count_before(sc, t, sc[gs], d["grad_t"].to_numpy()[gs], 7 * DAY)
    d["f_dup7_grad"] = np.where(has_s, (n7 > 0).astype(float), np.nan)
    nm = d["symbol"].fillna("").astype(str) + " " + d["name"].fillna("").astype(str)
    d["f_cjk"] = np.where(nm.str.strip() != "", nm.map(lambda s: 1.0 if CJK.search(s) else 0.0), np.nan)
    dt = pd.to_datetime(d["t"], unit="s", utc=True)
    d["f_hour"] = dt.dt.hour.astype(float)
    d["f_weekend"] = (dt.dt.dayofweek >= 5).astype(float)
    d["f_launches1h"] = (np.arange(len(d)) - np.searchsorted(t, t - H, side="left")).astype(float)
    i1 = np.clip(np.searchsorted(sol[:, 0], t * 1000 - 3_600_000, side="right") - 1, 0, None)
    i0 = np.clip(np.searchsorted(sol[:, 0], t * 1000 - 86_400_000 - 3_600_000, side="right") - 1, 0, None)
    d["f_sol24"] = sol[i1, 1] / sol[i0, 1] - 1
    # L-F13 theme heat: graduations of the 24 h before whose name shares a word with this launch's name
    w_of = [words(a) | words(b) for a, b in zip(d["symbol"], d["name"])]
    gidx = np.nonzero((d["L1"] == 1).to_numpy() & d["grad_t"].notna().to_numpy())[0]
    gt = d["grad_t"].to_numpy()
    by_word = {}
    for i in gidx[np.argsort(gt[gidx])]:
        for w in w_of[i]:
            by_word.setdefault(w, []).append(i)
    by_word = {w: (np.array(v), gt[np.array(v)]) for w, v in by_word.items()}
    f13 = np.full(len(d), np.nan)
    named = (d["symbol"].notna() | d["name"].notna()).to_numpy()
    for i, ws in enumerate(w_of):
        if not named[i]:
            continue
        seen = set()
        for w in ws:
            if w in by_word:
                idx, tt = by_word[w]
                a, b = np.searchsorted(tt, t[i] - DAY), np.searchsorted(tt, t[i])
                seen.update(idx[a:b].tolist())
        f13[i] = len(seen)
    d["f_theme24"] = f13
    d["_words"] = w_of
    return d


def sample_facts(d, lmeta_dir, chain_dir):
    """L-F10-F18 for the launches of the metadata sample whose file was read (amendment 6)."""
    lm = pd.read_parquet(os.path.join(lmeta_dir, "lmeta.parquet")).drop_duplicates("mint").set_index("mint")
    j = d["mint"].map
    d["in_sample"] = d["mint"].isin(lm.index)
    ok = j(lm["file_status"]).eq("ok") if "file_status" in lm else pd.Series(False, index=d.index)
    d["m_file"] = ok.fillna(False).to_numpy(bool)
    d["chain_complete"] = j(lm["complete"]) if "complete" in lm else np.nan
    f = d["m_file"].to_numpy(bool)
    get = lambda c: (j(lm[c]) if c in lm else pd.Series(None, index=d.index)).fillna("").astype(str).str.strip()
    tw, tg, ws = get("f_twitter"), get("f_telegram"), get("f_website")
    tw, tg, ws = [x.where(~x.isin(["None", "null", "nan"]), "") for x in (tw, tg, ws)]
    nl = (tw != "").astype(int) + (tg != "").astype(int) + (ws != "").astype(int)
    d["f_nlinks"] = np.where(f, nl, np.nan)
    d["f_xtype"] = np.where(f, np.where(tw.str.contains(r"/status/", regex=True), 1, np.where(tw != "", 2, 0)), np.nan)
    wiki = None
    if chain_dir and os.path.exists(os.path.join(chain_dir, "wiki_top.json")):
        wiki = json.load(open(os.path.join(chain_dir, "wiki_top.json")))
    f12 = np.full(len(d), np.nan)
    if wiki:
        day_words = {}
        for k, arts in wiki.items():
            s = set()
            for a, _ in arts:
                if a and ":" not in a and a != "Main_Page":
                    s |= words(a.replace("_", " "))
            day_words[k] = s
        days = (pd.to_datetime(d["t"], unit="s", utc=True).dt.normalize() - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
        for i in np.nonzero(f)[0]:
            dw = day_words.get(days.iat[i])
            if dw:
                f12[i] = 1.0 if d["_words"].iat[i] & dw else 0.0
    d["f_news"] = f12
    f14 = np.full(len(d), np.nan)
    tms = d["t"].to_numpy(np.int64) * 1000
    for i in np.nonzero(f)[0]:
        m = TWEET.search(tw.iat[i])
        if not m:
            f14[i] = 0.0
            continue
        age = float(tms[i]) - ((int(m.group(1)) >> 22) + 1288834974657)     # float as check_rockets.py (malformed ids)
        f14[i] = 1.0 if age <= 3_600_000 else (2.0 if age <= 86_400_000 else 3.0)
    d["f_post_age"] = f14
    img = get("f_image")
    cid = img.map(lambda x: CIDRE.search(x).group(1) if CIDRE.search(x) else x)
    # L-F15: the same picture file as a graduation of the 7 days before (graduations' pictures: this sample + rocketschain)
    gpic = {}
    gt = d.set_index("mint")["grad_t"]
    for m, c in zip(d["mint"][f & (d["L1"] == 1).to_numpy()], cid[f & (d["L1"] == 1).to_numpy()]):
        if c:
            gpic.setdefault(c, []).append(gt.get(m))
    if chain_dir and os.path.exists(os.path.join(chain_dir, "chain.parquet")):
        ch = pd.read_parquet(os.path.join(chain_dir, "chain.parquet"), columns=["mint", "f_image"])
        for m, x in zip(ch["mint"], ch["f_image"].fillna("").astype(str)):
            if x in ("NaN", "None", "null"):            # meta_chain.py final of 24 Oct wrote missing values as text
                continue
            c = CIDRE.search(x).group(1) if CIDRE.search(x) else x.strip()
            if c and m in gt.index and pd.notna(gt.get(m)):
                gpic.setdefault(c, []).append(gt.get(m))
    t = d["t"].to_numpy(np.int64)
    f15 = np.full(len(d), np.nan)
    for i in np.nonzero(f)[0]:
        c = cid.iat[i]
        if not c:
            f15[i] = 0.0
            continue
        ts = gpic.get(c, [])
        f15[i] = 1.0 if any(x is not None and pd.notna(x) and t[i] - 7 * DAY <= x < t[i] for x in ts) else 0.0
    d["f_img_reused"] = f15
    uri = d["uri"].fillna("").astype(str)
    own = uri.str.contains("ipfs", case=False) & (get("f_createdOn").str.rstrip("/") == "https://pump.fun")
    d["f_launch_other"] = np.where(f, (~own).astype(float), np.nan)
    d["f_video"] = np.where(f, (get("f_video") != "").astype(float), np.nan)
    dl = pd.to_numeric(j(lm["f_desc_len"]) if "f_desc_len" in lm else np.nan, errors="coerce")
    d["f_desc_len"] = np.where(f, dl, np.nan)
    return d


def picture_facts(d, images_dir, gimages_dir):
    """L-F19-F22 for the picture sub-sample (images.py output); look-alikes against the graduations' pictures."""
    im = pd.read_parquet(glob.glob(os.path.join(images_dir, "*.parquet"))[0]).drop_duplicates("mint").set_index("mint")
    im = im[im["img_ok"].fillna(False).astype(bool)]
    j = d["mint"].map
    has = d["mint"].isin(im.index).to_numpy()
    gcode = {g: k for k, g in enumerate(GROUPS)}
    d["f_group"] = j(im["group"].map(gcode)).astype(float) if "group" in im else np.nan
    d["f_animated"] = j(im["animated"].astype(float)) if "animated" in im else np.nan
    d["f_name_fit"] = pd.to_numeric(j(im["name_fit"]), errors="coerce") if "name_fit" in im else np.nan
    gh = []
    gt = d.set_index("mint")["grad_t"]
    for src in [images_dir] + ([gimages_dir] if gimages_dir else []):
        for f in glob.glob(os.path.join(src, "*.parquet")):
            x = pd.read_parquet(f, columns=["mint", "ahash", "img_ok"])
            x = x[x["img_ok"].fillna(False).astype(bool) & x["ahash"].notna()]
            for m, h in zip(x["mint"], x["ahash"]):
                g = gt.get(m)
                if g is not None and pd.notna(g):
                    gh.append((float(g), int(h, 16), m))
    gh.sort()
    gts = np.array([x[0] for x in gh])
    ghs = np.array([x[1] for x in gh], dtype=np.uint64)
    gms = np.array([x[2] for x in gh], dtype=object)
    t = d["t"].to_numpy(np.int64)
    look = np.full(len(d), np.nan)
    hashes = j(im["ahash"]) if "ahash" in im else pd.Series(None, index=d.index)
    for i in np.nonzero(has)[0]:
        h = hashes.iat[i]
        if not isinstance(h, str):
            continue
        a, b = np.searchsorted(gts, t[i] - 7 * DAY), np.searchsorted(gts, t[i])
        if b <= a:
            look[i] = 0.0
            continue
        x = np.bitwise_xor(ghs[a:b], np.uint64(int(h, 16)))
        bits = np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1).sum(1)
        same = (bits <= 4) & (gms[a:b] != d["mint"].iat[i])
        look[i] = 1.0 if same.any() else 0.0
    d["f_lookalike"] = look
    return d


def day_ratio_ci(fav, y, day, draws=2000, seed=7):
    """95 % interval of rate(favoured) / rate(rest), bootstrap over days (days drawn with replacement, as ratio_ci)."""
    days, inv = np.unique(day, return_inverse=True)
    k = len(days)
    a_n = np.bincount(inv, weights=fav, minlength=k)
    a_x = np.bincount(inv, weights=fav * y, minlength=k)
    b_n = np.bincount(inv, weights=~fav, minlength=k)
    b_x = np.bincount(inv, weights=(~fav) * y, minlength=k)
    rng = np.random.default_rng(seed)
    W = rng.multinomial(k, np.full(k, 1 / k), size=draws).astype(float)
    ra = (W @ a_x) / np.maximum(W @ a_n, 1e-9)
    rb = (W @ b_x) / np.maximum(W @ b_n, 1e-9)
    ok = rb > 0
    r = ra[ok] / rb[ok]
    return [round(float(np.quantile(r, 0.025)), 3), round(float(np.quantile(r, 0.975)), 3)] if len(r) else None


def part_a(d, facts, avail):
    recs, pv, pm = [], [], []
    for f in facts:
        for oc in OUTCOMES:
            e = d[d[f].notna() & d[oc].notna()]
            fit, uns = e[e["w"].isin(FIT)], e[e["w"].isin(UNSEEN)]
            mon, w5 = e[e["w"].isin(MONTH)], e[e["w"] == "w5"]
            if not len(fit) or not len(uns):
                continue
            if BUCKETS[f] is None:
                q = np.quantile(fit[f], [1 / 3, 2 / 3])
                edges, labels = [-np.inf, q[0], q[1], np.inf], ["low (<%.3g)" % q[0], "mid", "high (>%.3g)" % q[1]]
            else:
                edges, labels = BUCKETS[f]
            cut = lambda x: pd.cut(x[f], edges, labels=labels)
            tf = fit.groupby(cut(fit), observed=False)[oc].agg(["size", "mean"])
            okb = tf[tf["size"] >= 200]
            if len(okb) < 2:
                continue
            fav = okb["mean"].idxmax()
            rec = {"fact": FACT_NO[f] + " " + f[2:], "outcome": oc, "favoured": str(fav),
                   "fit_table": {str(k): {"n": int(v["size"]), "pct": round(100 * v["mean"], 3) if v["size"] else None}
                                 for k, v in tf.iterrows()}, "available": avail.get(f)}
            for label, part in (("unseen", uns), ("w4", mon), ("w5", w5)):
                if not len(part):
                    continue
                m = (cut(part) == fav).to_numpy()
                y = part[oc].to_numpy(float)
                x1, n1, x2, n2 = y[m].sum(), m.sum(), y[~m].sum(), (~m).sum()
                p = ztest(x1, n1, x2, n2, 1) if n1 and n2 else 1.0
                rec[label] = {"n_in": int(n1), "pct_in": round(100 * x1 / n1, 3) if n1 else None,
                              "pct_rest": round(100 * x2 / n2, 3) if n2 else None, "p": p,
                              "ratio_ci": day_ratio_ci(m, y, part["day"].to_numpy()) if n1 and n2 else None}
            fm = (cut(fit) == fav).to_numpy()
            yf = fit[oc].to_numpy(float)
            rec["fit"] = {"pct_in": round(100 * yf[fm].mean(), 3), "pct_rest": round(100 * yf[~fm].mean(), 3)}
            recs.append(rec)
            pv.append(rec["unseen"]["p"])
            pm.append(rec.get("w4", {}).get("p", 1.0))
    hu, hm = holm(np.array(pv)), holm(np.array(pm))
    for r, a, b in zip(recs, hu, hm):
        r["holm_unseen"], r["holm_w4"] = bool(a), bool(b)
        ci = r["unseen"].get("ratio_ci")
        r["matters"] = bool(a and b and ci and ci[0] >= 1.25)
        for k in ("unseen", "w4", "w5"):
            if k in r:
                r[k]["p"] = float("%.3g" % r[k]["p"])
    return recs


def auc_ci(y, s, day, draws=200, seed=7):
    from sklearn.metrics import roc_auc_score
    days = np.unique(day)
    di = {x: np.nonzero(day == x)[0] for x in days}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        idx = np.concatenate([di[x] for x in rng.choice(days, len(days))])
        if y[idx].min() != y[idx].max():
            out.append(roc_auc_score(y[idx], s[idx]))
    return [round(float(np.quantile(out, 0.025)), 3), round(float(np.quantile(out, 0.975)), 3)] if out else None


def part_c(d, feats):
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    res = {"features": feats, "models": []}
    for oc in OUTCOMES:
        e = d[d[oc].notna()]
        fit, uns = e[e["w"].isin(FIT)], e[e["w"].isin(UNSEEN)]
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=31, min_child_samples=50, random_state=7,
                                 verbose=-1)
        clf.fit(fit[feats].astype(float), fit[oc].astype(int))
        sf = clf.predict_proba(fit[feats].astype(float))[:, 1]
        m = {"outcome": oc, "fit_n": int(len(fit)), "gain": dict(sorted(zip(feats, clf.booster_.feature_importance("gain").round(1).tolist()),
                                                                       key=lambda x: -x[1]))}
        for label, part in (("unseen", uns), ("w4", e[e["w"].isin(MONTH)]), ("w5", e[e["w"] == "w5"])):
            if not len(part) or part[oc].nunique() < 2:
                continue
            s = clf.predict_proba(part[feats].astype(float))[:, 1]
            y = part[oc].to_numpy(int)
            cuts = []
            for top in (0.01, 0.02, 0.05):
                sel = s >= np.quantile(sf, 1 - top)
                cuts.append({"top": "%g%%" % (100 * top), "n": int(sel.sum()),
                             "pct": round(100 * float(y[sel].mean()), 3) if sel.any() else None,
                             "base_pct": round(100 * float(y.mean()), 3)})
            m[label] = {"n": int(len(part)), "auc": round(float(roc_auc_score(y, s)), 3),
                        "auc_ci": auc_ci(y, s, part["day"].to_numpy()), "cuts": cuts}
        res["models"].append(m)
    return res


def main(udir, market, lmeta_dir=None, images_dir=None, chain_dir=None, gimages_dir=None):
    sol = np.array(json.load(open(market))["SOLUSDT"], float)
    d = universe(udir)
    log("launches", len(d))
    d = launch_facts(d, sol)
    log("launch facts done")
    facts = ["f_creator_launches30", "f_creator_grads30", "f_dup7_grad", "f_cjk", "f_hour", "f_weekend", "f_launches1h",
             "f_sol24", "f_theme24"]
    if lmeta_dir and os.path.exists(os.path.join(lmeta_dir, "lmeta.parquet")):
        d = sample_facts(d, lmeta_dir, chain_dir)
        facts += list(SAMPLE_FACTS)
        log("sample facts done")
    if images_dir and glob.glob(os.path.join(images_dir, "*.parquet")):
        d = picture_facts(d, images_dir, gimages_dir)
        facts += list(PICTURE_FACTS)
        log("picture facts done")
    if os.environ.get("NULL"):
        rng = np.random.default_rng(int(os.environ["NULL"]))
        for w, g in d[d["w"] != ""].groupby("w"):
            perm = rng.permutation(g.index.to_numpy())
            d.loc[g.index, ["L1", "L2"]] = d.loc[perm, ["L1", "L2"]].to_numpy()
    res = {"launches": {}, "available": {}, "sample": {}}
    for w, g in d.groupby("w"):
        res["launches"][w or "history (counts only)"] = {"n": int(len(g)), "graduated": int(g["L1"].sum()), "L2_n": int(g["L2"].notna().sum()),
                              "L2_pos": int(g["L2"].sum()), "days": int(g["day"].nunique()),
                              "src": g["src"].value_counts().to_dict()}
    base = {"all": d}
    if "in_sample" in d:
        s = d[d["in_sample"]]
        base["sample"] = s
        for w, g in s.groupby("w"):
            gr, ng = g[g["L1"] == 1], g[g["L1"] == 0]
            res["sample"][w] = {"n": int(len(g)), "file_read_pct": round(100 * float(g["m_file"].mean()), 1),
                                "file_read_pct_graduated": round(100 * float(gr["m_file"].mean()), 1) if len(gr) else None,
                                "file_read_pct_not": round(100 * float(ng["m_file"].mean()), 1) if len(ng) else None,
                                "chain_complete_vs_L1": {"both": int(((g["chain_complete"] == True) & (g["L1"] == 1)).sum()),  # noqa: E712
                                                         "chain_only": int(((g["chain_complete"] == True) & (g["L1"] == 0)).sum()),  # noqa: E712
                                                         "L1_only": int(((g["chain_complete"] == False) & (g["L1"] == 1)).sum())}}  # noqa: E712
    for f in facts:
        src = base["all"] if f not in SAMPLE_FACTS + PICTURE_FACTS else base["sample"]
        res["available"][f] = {w: round(float(g[f].notna().mean()), 3) for w, g in src[src["w"] != ""].groupby("w")}
    res["partA"] = part_a(d, facts, res["available"])
    if "sample" in base:
        res["partC"] = part_c(base["sample"], facts)
    return res


if __name__ == "__main__":
    r = main(*sys.argv[1:7])
    print(json.dumps(r, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
