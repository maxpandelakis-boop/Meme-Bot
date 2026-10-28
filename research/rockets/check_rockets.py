"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md): which launch facts separate the coins that go
10x from the rest, and does any of them make money on months it never saw?

  python3 research/rockets/check_rockets.py <work dir> <history2 dir> <market.json> [<rocketsmeta dir>] [<rocketschain dir>]
          [<rocketsimages dir>] > out.json

[<rocketsimages dir>] is the branch rocketsimages (images.py: what each graduation's picture shows, F19-F22, amendment 5).
Amendment 7: a fact, a Part B candidate and a Part C cut only count when they also pass on w4 alone (a full unseen month), and a
money candidate's w5 mean after the allowance must not be below 0. w4 and w5 are reported on their own.

[<rocketschain dir>] is the branch rocketschain (meta_chain.py). <work dir> holds paths.npz, coins.parquet (build_paths.py) and entries.parquet (base.py). <rocketsmeta dir> is the branch
rocketsmeta (meta_fetch.py); without it only history2's launch facts (w3/w4) exist. Writes the result JSON to stdout and the rocket
lists to <work dir>/rockets_E5.csv, rockets_E30.csv. No network."""
import glob, json, math, os, re, sys
import numpy as np, pandas as pd

BAR, MIN, H, DAY = 300_000, 60_000, 3_600_000, 86_400_000
FIT_ALL, UNSEEN_ALL = ("w1", "w2", "w3"), ("w4", "w5")
ES = (5, 30)
ALLOW = 0.60
LIQ_MIN = 10_000
RULES = {"S1": (None, 10.0, 24), "S2": (0.50, 10.0, 24), "S3": (0.30, 11.0, 6)}
RULE_NAME = {"S1": "no stop / 10x / 24 h", "S2": "-50% / 10x / 24 h", "S3": "-30% / 11x / 6 h (rule K)"}
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ｦ-ﾟ]")


def sell_radar(v):
    return v - max(0.005 * v, 0.81) if v > 0 else 0.0


def money(mult):
    return sell_radar(19.19 * max(0.0, mult)) - 20.0


def rule_mult(P, stop, target, hours):
    n = hours * 12
    Q = P[:n]
    i_s = np.argmax(Q <= 1 - stop) if stop is not None and (Q <= 1 - stop).any() else None
    i_t = np.argmax(Q >= target) if (Q >= target).any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        return min(float(Q[i_s]), 1 - stop)
    if i_t is not None:
        return target
    return float(Q[-1])


# ------------------------------------------------------------------------------------------------ facts
def launch_facts(coins, hist, meta_dir, chain_dir=None, wiki=None):
    """Launch facts by source, first found wins: history2's create records (w3/w4), the chain and metadata files
    (meta_chain.py, branch rocketschain), pump.fun's API (meta_fetch.py, branch rocketsmeta), GeckoTerminal names (same branch)."""
    c = coins.copy()
    c["creator"] = c["creator"].where(c["creator"].notna(), None)
    c["src_creator"] = np.where(c["creator"].notna(), "history2", None)
    c["src_names"] = np.where(c["symbol"].notna(), "history2", None)
    c["src_created"] = np.where(c["created_ms"].notna(), "history2", None)
    c["tw"], c["tg"], c["ws"], c["src_links"] = None, None, None, None
    j = c["mint"].map

    def fill(col, val, src, srccol):
        new = c[col].isna() & val.notna()
        c.loc[new, col] = val[new]
        if srccol:
            c.loc[new, srccol] = src

    if chain_dir and os.path.exists(os.path.join(chain_dir, "chain.parquet")):
        ch = pd.read_parquet(os.path.join(chain_dir, "chain.parquet")).drop_duplicates("mint").set_index("mint")
        for col in ch.columns:          # meta_chain.py final of 24 Oct wrote missing values as the text "NaN"
            if not pd.api.types.is_numeric_dtype(ch[col]):
                ch[col] = ch[col].where(~ch[col].isin(["NaN", "None", "null"]), None)
        ch = ch.reindex(columns=sorted(set(ch.columns) | {"name", "symbol", "curve_creator", "created_s", "curve_sigs", "f_twitter",
                                                          "f_telegram", "f_website", "f_name", "uri", "f_createdOn", "f_image",
                                                          "f_video", "f_desc_len"}))
        fill("symbol", j(ch["symbol"].replace("", None)), "chain", "src_names")
        fill("token_name", j(ch["name"].replace("", None)), "chain", None)
        fill("creator", j(ch["curve_creator"]), "chain", "src_creator")
        cs = pd.to_numeric(j(ch["created_s"]), errors="coerce") * 1000
        cs[pd.to_numeric(j(ch["curve_sigs"]), errors="coerce").isna()] = np.nan      # capped: not the first transaction
        fill("created_ms", cs, "chain", "src_created")
        has = j(ch["f_name"]).notna() | j(ch["f_twitter"]).notna() | j(ch["f_website"]).notna()
        for col, src in (("tw", "f_twitter"), ("tg", "f_telegram"), ("ws", "f_website")):
            v = j(ch[src]).where(has, None)
            c[col] = v.where(has, None).fillna("").where(has, None)
        c.loc[has, "src_links"] = "metadata file"
        c["m_file"] = has
        c["m_uri"] = j(ch["uri"])
        c["m_createdOn"] = j(ch["f_createdOn"]).where(has, None)
        c["m_image"] = j(ch["f_image"]).where(has, None)
        c["m_video"] = j(ch["f_video"]).where(has, None)
        c["m_desc_len"] = pd.to_numeric(j(ch["f_desc_len"]), errors="coerce").where(has, np.nan)
    if meta_dir and os.path.exists(os.path.join(meta_dir, "meta.parquet")):
        pm = pd.read_parquet(os.path.join(meta_dir, "meta.parquet")).drop_duplicates("mint").set_index("mint")
        pm = pm.reindex(columns=sorted(set(pm.columns) | {"name", "symbol", "creator", "created_timestamp", "twitter", "telegram",
                                                          "website", "src"}))
        pf = pm[pm["src"].isna()]
        fill("symbol", j(pf["symbol"]), "pump.fun", "src_names")
        fill("token_name", j(pf["name"]), "pump.fun", None)
        fill("creator", j(pf["creator"]), "pump.fun", "src_creator")
        fill("created_ms", pd.to_numeric(j(pf["created_timestamp"]), errors="coerce"), "pump.fun", "src_created")
        has = c["mint"].isin(pf.index) & c["src_links"].isna()
        for col, src in (("tw", "twitter"), ("tg", "telegram"), ("ws", "website")):
            c.loc[has, col] = j(pf[src])[has].fillna("")
        c.loc[has, "src_links"] = "pump.fun"
        gt = pm[pm["src"] == "gt"]
        fill("symbol", j(gt["symbol"]), "geckoterminal", "src_names")
        fill("token_name", j(gt["name"]), "geckoterminal", None)
    hasl = c["src_links"].notna()
    tw = c["tw"].fillna("").astype(str).str.strip()
    tg = c["tg"].fillna("").astype(str).str.strip()
    ws = c["ws"].fillna("").astype(str).str.strip()
    nl = (tw != "").astype(int) + (tg != "").astype(int) + (ws != "").astype(int)
    c["nlinks"] = np.where(hasl, nl, np.nan)
    xs = np.where(tw.str.contains(r"/status/", regex=True), 1, np.where(tw != "", 2, 0))
    c["xtype"] = np.where(hasl, xs, np.nan)
    c = c.sort_values("t").reset_index(drop=True)
    t = c["t"].to_numpy(np.int64)
    # F1 creator's earlier graduations within 30 days
    prior = np.full(len(c), np.nan)
    for cr, g in c[c["creator"].notna()].groupby("creator"):
        tt = g["t"].to_numpy(np.int64)
        lo = np.searchsorted(tt, tt - 30 * DAY)
        prior[g.index.to_numpy()] = np.arange(len(tt)) - lo
    c["f_creator_prior"] = prior
    # F4 copycat ticker within 7 days
    sym = c["symbol"].fillna("").astype(str).str.upper().str.strip()
    dup = np.full(len(c), np.nan)
    for s, g in c[sym != ""].groupby(sym[sym != ""]):
        tt = g["t"].to_numpy(np.int64)
        lo = np.searchsorted(tt, tt - 7 * DAY)
        dup[g.index.to_numpy()] = np.arange(len(tt)) - lo
    c["f_dup7"] = dup
    # F3 curve minutes
    c["f_curve_min"] = (c["t"] - c["created_ms"]) / MIN
    c.loc[c["f_curve_min"] < -2, "f_curve_min"] = np.nan
    c["f_curve_min"] = c["f_curve_min"].clip(lower=0)
    # F5 script
    nm = c["symbol"].fillna("").astype(str) + " " + c["token_name"].fillna("").astype(str)
    c["f_cjk"] = np.where(nm.str.strip() != "", nm.map(lambda s: 1.0 if CJK.search(s) else 0.0), np.nan)
    # F6/F7 time
    dt = pd.to_datetime(c["t"], unit="ms", utc=True)
    c["f_hour"] = dt.dt.hour.astype(float)
    c["f_weekend"] = (dt.dt.dayofweek >= 5).astype(float)
    # F8 crowding
    c["f_grads24"] = (np.arange(len(c)) - np.searchsorted(t, t - DAY)).astype(float)
    c["f_nlinks"] = c["nlinks"]
    c["f_xtype"] = c["xtype"]
    media_facts(c, wiki)
    return c


STOP = set("""that this with from have were they what when your about list film series season which there their these would other
after first also into over more most some only then than them been will like just year years coin token official the and for
real world news new""".split())


def words(s):
    return {w for w in re.split(r"[^a-z0-9]+", str(s or "").lower()) if len(w) >= 4 and w not in STOP and not w.isdigit()}


TWEET = re.compile(r"/status(?:es)?/(\d{6,})")
CIDRE = re.compile(r"/ipfs/([A-Za-z0-9]{20,})")


def media_facts(c, wiki):
    """F12-F18 (amendment 4); c is sorted by graduation time."""
    t = c["t"].to_numpy(np.int64)
    w_of = [words(a) | words(b) for a, b in zip(c["symbol"], c["token_name"])]
    named = c["symbol"].notna() | c["token_name"].notna()
    # F12 news of the day: the day before's 1,000 most-read Wikipedia articles
    f12 = np.full(len(c), np.nan)
    if wiki:
        day_words = {}
        for d, arts in wiki.items():
            ws = set()
            for a, _ in arts:
                if a and ":" not in a and a != "Main_Page":
                    ws |= words(a.replace("_", " "))
            day_words[d] = ws
        days = pd.to_datetime(c["t"], unit="ms", utc=True).dt.normalize() - pd.Timedelta(days=1)
        for i, (d, ws) in enumerate(zip(days.dt.strftime("%Y-%m-%d"), w_of)):
            if named.iat[i] and day_words.get(d):
                f12[i] = 1.0 if ws & day_words[d] else 0.0
    c["f_news"] = f12
    # F13 theme heat: graduations of the 24 h before sharing a name word
    idx = {}
    for i, ws in enumerate(w_of):
        for w in ws:
            idx.setdefault(w, []).append(i)
    f13 = np.full(len(c), np.nan)
    for i, ws in enumerate(w_of):
        if not named.iat[i]:
            continue
        prev = set()
        for w in ws:
            lst = idx[w]
            k = np.searchsorted(lst, i)
            lo = np.searchsorted(t[lst[:k]], t[i] - DAY) if k else 0
            prev.update(lst[lo:k])
        f13[i] = len(prev)
    c["f_theme24"] = f13
    # F14 fresh post: the X post's own time (snowflake id) before the coin's creation
    hasl = c["src_links"].notna().to_numpy()
    tw = c["tw"].fillna("").astype(str)
    f14 = np.full(len(c), np.nan)
    for i, (x, cr) in enumerate(zip(tw, c["created_ms"])):
        if not hasl[i]:
            continue
        m = TWEET.search(x)
        if not m:
            f14[i] = 0.0
            continue
        if not np.isfinite(cr):
            continue
        age = cr - ((int(m.group(1)) >> 22) + 1288834974657)
        f14[i] = 1.0 if age <= H else (2.0 if age <= DAY else 3.0)
    c["f_post_age"] = f14
    if "m_file" not in c:
        for k in ("f_img_reused", "f_launch_other", "f_video", "f_desc_len"):
            c[k] = np.nan
        return
    mf = c["m_file"].fillna(False).to_numpy(bool)
    # F15 picture used by another graduation in the 7 days before
    cid = c["m_image"].fillna("").astype(str).map(lambda x: (CIDRE.search(x).group(1) if CIDRE.search(x) else x.strip()))
    f15 = np.full(len(c), np.nan)
    seen = {}
    for i, (x, ok) in enumerate(zip(cid, mf)):
        if not ok:
            continue
        lst = seen.setdefault(x, []) if x else None
        if lst is None:
            f15[i] = 0.0
            continue
        f15[i] = 1.0 if lst and t[i] - t[lst[-1]] <= 7 * DAY else 0.0
        lst.append(i)
    c["f_img_reused"] = f15
    # F16 launched on pump.fun's own page vs other tools
    uri = c["m_uri"].fillna("").astype(str)
    own = uri.str.contains("ipfs", case=False) & (c["m_createdOn"].fillna("").astype(str).str.strip().str.rstrip("/") == "https://pump.fun")
    c["f_launch_other"] = np.where(mf, (~own).astype(float), np.nan)
    # F17 video coin, F18 description length
    c["f_video"] = np.where(mf, (c["m_video"].fillna("").astype(str).str.strip() != "").astype(float), np.nan)
    c["f_desc_len"] = np.where(mf, c["m_desc_len"], np.nan)


def creator_rocket(c, e5):
    """F2: for each coin and entry E, did the creator have an earlier rocket (at E = 5) graduating at least 24 h 5 min before?"""
    r5 = e5.set_index("pool")["rocket"]
    c = c.copy()
    c["r5"] = c["pool"].map(r5).fillna(False).astype(bool)
    first_rocket = {}
    for cr, g in c[c["creator"].notna() & c["r5"]].groupby("creator"):
        first_rocket[cr] = int(g["t"].min())
    return first_rocket


BUCKETS = {
    "f_creator_prior": ([-0.5, 0.5, 2.5, 9.5, np.inf], ["0", "1-2", "3-9", "10+"]),
    "f_creator_rocket": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_curve_min": ([-np.inf, 1, 10, 60, 360, np.inf], ["<=1 min", "1-10 min", "10-60 min", "1-6 h", ">6 h"]),
    "f_dup7": ([-0.5, 0.5, 2.5, 9.5, np.inf], ["0", "1-2", "3-9", "10+"]),
    "f_cjk": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_hour": ([-0.5, 5.5, 11.5, 17.5, 23.5], ["0-6", "6-12", "12-18", "18-24"]),
    "f_weekend": ([-0.5, 0.5, 1.5], ["weekday", "weekend"]),
    "f_grads24": None, "f_sol24": None,
    "f_nlinks": ([-0.5, 0.5, 1.5, 2.5, 3.5], ["0", "1", "2", "3"]),
    "f_xtype": ([-0.5, 0.5, 1.5, 2.5], ["none", "post", "profile/community"]),
    "f_news": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_theme24": ([-0.5, 0.5, 4.5, 19.5, np.inf], ["0", "1-4", "5-19", "20+"]),
    "f_post_age": ([-0.5, 0.5, 1.5, 2.5, 3.5], ["no post", "up to 1 h", "1-24 h", "older"]),
    "f_img_reused": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_launch_other": ([-0.5, 0.5, 1.5], ["pump.fun", "other"]),
    "f_video": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_desc_len": ([-0.5, 0.5, 50.5, 200.5, np.inf], ["0", "1-50", "51-200", "over 200"]),
    "f_group": ([-0.5 + k for k in range(7)], ["animal_photo", "animal_drawn", "person_photo", "character_drawn", "text_logo",
                                               "object_scene"]),
    "f_animated": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_lookalike": ([-0.5, 0.5, 1.5], ["no", "yes"]),
    "f_name_fit": None,
}
GROUPS = tuple(BUCKETS["f_group"][1])
FACT_NO = {"f_creator_prior": "F1", "f_creator_rocket": "F2", "f_curve_min": "F3", "f_dup7": "F4", "f_cjk": "F5", "f_hour": "F6",
           "f_weekend": "F7", "f_grads24": "F8", "f_sol24": "F9", "f_nlinks": "F10", "f_xtype": "F11", "f_news": "F12",
           "f_theme24": "F13", "f_post_age": "F14", "f_img_reused": "F15", "f_launch_other": "F16", "f_video": "F17",
           "f_desc_len": "F18", "f_group": "F19", "f_animated": "F20", "f_lookalike": "F21", "f_name_fit": "F22"}


def picture_facts(c, images_dir):
    """F19-F22 (amendment 5) for the graduations whose picture images.py could read; look-alike = a picture of another
    graduation of the 7 days before at most 4 bits apart (64-bit average hash)."""
    for k in ("f_group", "f_animated", "f_lookalike", "f_name_fit"):
        c[k] = np.nan
    files = sorted(glob.glob(os.path.join(images_dir, "*.parquet"))) if images_dir else []
    if not files:
        return c
    im = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True).drop_duplicates("mint")
    im = im[im["img_ok"].fillna(False).astype(bool)].set_index("mint")
    j = c["mint"].map
    c["f_group"] = j(im["group"].map({g: k for k, g in enumerate(GROUPS)})).astype(float)
    c["f_animated"] = j(im["animated"].astype(float)).astype(float)
    c["f_name_fit"] = pd.to_numeric(j(im["name_fit"]), errors="coerce")
    h = j(im["ahash"])
    ok = h.notna().to_numpy() & c["t"].notna().to_numpy()
    t = c["t"].to_numpy(np.float64)
    order = np.argsort(t[ok])
    gi = np.nonzero(ok)[0][order]
    gt = t[gi]
    gh = np.array([int(x, 16) for x in h.to_numpy()[gi]], dtype=np.uint64)
    look = np.full(len(c), np.nan)
    for i in np.nonzero(ok)[0]:
        a, b = np.searchsorted(gt, t[i] - 7 * DAY), np.searchsorted(gt, t[i])
        idx = gi[a:b]
        x = np.bitwise_xor(gh[a:b], np.uint64(int(h.iat[i], 16)))[idx != i]
        look[i] = float((np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1).sum(1) <= 4).any()) if len(x) else 0.0
    c["f_lookalike"] = look
    return c


def holm(ps, alpha=0.05):
    order = np.argsort(ps)
    ok = np.zeros(len(ps), bool)
    for k, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - k):
            ok[i] = True
        else:
            break
    return ok


def ztest(x1, n1, x2, n2, direction):
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-18))
    z = (p1 - p2) / se * direction
    return 0.5 * math.erfc(z / math.sqrt(2))


def ratio_ci(fav, y, day, draws=4000, seed=7):
    rng = np.random.default_rng(seed)
    days = np.unique(day)
    di = {d: np.nonzero(day == d)[0] for d in days}
    out = []
    for _ in range(draws):
        idx = np.concatenate([di[d] for d in rng.choice(days, len(days))])
        a, b = y[idx][fav[idx]], y[idx][~fav[idx]]
        if len(a) and len(b) and b.mean() > 0:
            out.append(a.mean() / b.mean())
    return [round(float(np.quantile(out, 0.025)), 2), round(float(np.quantile(out, 0.975)), 2)] if out else None


def month_check(v, k):
    """Amendment 7: the Part B criteria on one window alone (v = money per trade after the allowance)."""
    v = np.asarray(v, float)
    lb = round(boot_lo(v, 0.01 / k), 2) if len(v) >= 2 else None
    wb = round(float((v.sum() - v.max()) / max(1, len(v) - 1)), 2) if len(v) > 1 else None
    return {"n": int(len(v)), "after_allowance": round(float(v.mean()), 2) if len(v) else None, "lower_bound": lb,
            "without_best": wb, "passes": bool(len(v) >= 40 and v.mean() > 0 and lb is not None and lb > 0 and wb > 0)}


def boot_lo(v, q, draws=20000, seed=7):
    v = np.asarray(v, float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for k in range(0, draws, 2000):
        means[k:k + 2000] = v[rng.integers(0, len(v), (2000, len(v)))].mean(1)
    return float(np.quantile(means, q))


def main(work, hist, market, meta_dir=None, chain_dir=None, images_dir=None):
    z = np.load(os.path.join(work, "paths.npz"))
    cl = z["cl"]
    coins = pd.read_parquet(os.path.join(work, "coins.parquet"))
    ent = pd.read_parquet(os.path.join(work, "entries.parquet"))
    wiki = None
    if chain_dir and os.path.exists(os.path.join(chain_dir, "wiki_top.json")):
        wiki = json.load(open(os.path.join(chain_dir, "wiki_top.json")))
    c = launch_facts(coins, hist, meta_dir, chain_dir, wiki)
    c = picture_facts(c, images_dir)
    sources = {k: {w: c[c["w"] == w][k].fillna("none").value_counts().to_dict() for w in sorted(c["w"].unique())}
                      for k in ("src_names", "src_creator", "src_created", "src_links")}
    row_of = {p: i for i, p in enumerate(coins["pool"])}
    # gaps (history2 recorder outages, w3/w4 only)
    g = np.sort(np.load(os.path.join(hist, "gap_minutes.npy")))
    br = np.nonzero(np.diff(g) > MIN)[0]
    st, en = np.r_[g[0], g[br + 1]], np.r_[g[br], g[-1]] + MIN
    big = (en - st) >= 10 * MIN
    GAPS = np.c_[st[big], en[big]]
    mk = json.load(open(market))
    sol = np.array(mk["SOLUSDT"], float)
    res = {"facts_available": {}, "partA": [], "partB": [], "partC": [], "base": {}, "describe": {}, "sources": sources}
    E5 = ent[(ent["E"] == 5) & ent["ok"]].merge(coins[["pool", "sol0", "tok0"]], on="pool", how="left")
    i5 = np.clip(np.searchsorted(sol[:, 0], E5["te"].to_numpy() - H, side="right") - 1, 0, None)
    E5 = E5[2 * np.sqrt(E5["sol0"] * E5["tok0"] * E5["p0"] * sol[i5, 1]) >= LIQ_MIN]
    fr = creator_rocket(c, E5)
    allrows = []
    for E in ES:
        e = ent[(ent["E"] == E) & ent["ok"]].copy()
        e = e.merge(c[["pool", "mint", "sol0", "tok0", "symbol", "token_name", "creator", "t"] + [k for k in c.columns if k.startswith("f_")]],
                    on="pool", how="left")
        # outage filter
        te = e["te"].to_numpy(np.int64)
        bad = np.zeros(len(e), bool)
        h2w = e["w"].isin(["w3", "w4"]).to_numpy()
        for a, b in GAPS:
            bad |= h2w & (a <= te + 6 * H) & (b >= te - H)
        # Amendment 1: pool liquidity at the entry of at least $10,000
        i = np.clip(np.searchsorted(sol[:, 0], te - H, side="right") - 1, 0, None)
        e["liq0"] = 2 * np.sqrt(e["sol0"] * e["tok0"] * e["p0"] * sol[i, 1])
        bad |= ~(e["liq0"] >= LIQ_MIN)
        e = e[~bad].copy()
        # F2 creator rocket known at the entry
        frm = e["creator"].map(fr)
        known = frm.notna() & (frm + 5 * MIN + DAY <= e["te"])
        e["f_creator_rocket"] = np.where(e["creator"].notna() & e["f_creator_prior"].notna(), known.astype(float), np.nan)
        # F9 SOL 24 h change before the entry
        i1 = np.searchsorted(sol[:, 0], e["te"].to_numpy() - H, side="right") - 1
        i0 = np.searchsorted(sol[:, 0], e["te"].to_numpy() - DAY - H, side="right") - 1
        e["f_sol24"] = sol[np.clip(i1, 0, None), 1] / sol[np.clip(i0, 0, None), 1] - 1
        # money per sell rule
        jl = ((e["te"].to_numpy(np.int64) - (e["t"].to_numpy(np.int64) // BAR * BAR)) // BAR - 1).astype(int)
        rows = e["pool"].map(row_of).to_numpy()
        for name, (s, x, hrs) in RULES.items():
            vals = np.empty(len(e))
            for k, (r, j, p0) in enumerate(zip(rows, jl, e["p0"].to_numpy())):
                P = cl[r, j + 1: j + 1 + 288] / p0
                vals[k] = money(rule_mult(P, s, x, hrs))
            e["m_" + name] = vals
        e["day"] = (e["te"] // DAY).astype(int)
        allrows.append(e)
        res["base"][str(E)] = {w: {"entries": int(len(g)), "rockets": int(g["rocket"].sum()), "rocketPct": round(100 * g["rocket"].mean(), 2),
                                   "zeroPct": round(100 * g["zero"].mean(), 1),
                                   **{nm: round(float(g["m_" + nm].mean()), 2) for nm in RULES}}
                               for w, g in e.groupby("w")}
    E_all = pd.concat(allrows, ignore_index=True)
    if os.environ.get("NULL"):
        # null check: the outcomes shuffled within each window and entry minute, so no fact can carry information
        rng = np.random.default_rng(int(os.environ["NULL"]))
        cols = ["rocket", "zero"] + ["m_" + nm for nm in RULES]
        for (w, E), g in E_all.groupby(["w", "E"]):
            perm = rng.permutation(g.index.to_numpy())
            E_all.loc[g.index, cols] = E_all.loc[perm, cols].to_numpy()
    E_all.to_parquet(os.path.join(work, "rows.parquet"), index=False)
    # availability
    facts = list(BUCKETS)
    for f in facts:
        av = {}
        for w, g in E_all[E_all["E"] == 5].groupby("w"):
            av[w] = round(float(g[f].notna().mean()), 3)
        res["facts_available"][f] = av
    # ------------------------------------------------------------------- Part A and B
    pa, pb = [], []
    for f in facts:
        av = res["facts_available"][f]
        if all(av.get(w, 0) >= 0.8 for w in FIT_ALL + UNSEEN_ALL):
            fit_w, uns_w = FIT_ALL, UNSEEN_ALL
        elif all(av.get(w, 0) >= 0.8 for w in ("w3", "w4")):
            fit_w, uns_w = ("w3",), tuple(w for w in ("w4", "w5") if av.get(w, 0) >= 0.8)
        else:
            continue
        for E in ES:
            e = E_all[(E_all["E"] == E) & E_all[f].notna()]
            fit, uns = e[e["w"].isin(fit_w)], e[e["w"].isin(uns_w)]
            if BUCKETS[f] is None:
                q = np.quantile(fit[f], [1 / 3, 2 / 3])
                edges, labels = [-np.inf, q[0], q[1], np.inf], ["low (<%.3g)" % q[0], "mid", "high (>%.3g)" % q[1]]
            else:
                edges, labels = BUCKETS[f]
            bf = pd.cut(fit[f], edges, labels=labels)
            bu = pd.cut(uns[f], edges, labels=labels)
            tab_fit = fit.groupby(bf, observed=False).agg(n=("rocket", "size"), rocket=("rocket", "mean"), zero=("zero", "mean"),
                                                          **{nm: ("m_" + nm, "mean") for nm in RULES})
            tab_uns = uns.groupby(bu, observed=False).agg(n=("rocket", "size"), rocket=("rocket", "mean"), zero=("zero", "mean"),
                                                          **{nm: ("m_" + nm, "mean") for nm in RULES})
            okb = tab_fit[tab_fit["n"] >= 200]
            if len(okb) < 2:
                continue
            fav_r = okb["rocket"].idxmax()
            fav_z = okb["zero"].idxmin()
            rec = {"fact": FACT_NO[f] + " " + f[2:], "E": E, "fit": list(fit_w), "unseen": list(uns_w),
                   "fit_table": {str(k): {"n": int(v["n"]), "rocketPct": round(100 * v["rocket"], 2) if v["n"] else None,
                                          "zeroPct": round(100 * v["zero"], 1) if v["n"] else None,
                                          **{nm: (round(v[nm], 2) if v["n"] else None) for nm in RULES}} for k, v in tab_fit.iterrows()},
                   "unseen_table": {str(k): {"n": int(v["n"]), "rocketPct": round(100 * v["rocket"], 2) if v["n"] else None,
                                             "zeroPct": round(100 * v["zero"], 1) if v["n"] else None,
                                             **{nm: (round(v[nm], 2) if v["n"] else None) for nm in RULES}} for k, v in tab_uns.iterrows()}}
            for kind, fav, col, dirn in (("rocket", fav_r, "rocket", 1), ("zero", fav_z, "zero", -1)):
                m = (bu == fav).to_numpy()
                y = uns[col].to_numpy().astype(float)
                x1, n1, x2, n2 = y[m].sum(), m.sum(), y[~m].sum(), (~m).sum()
                p = ztest(x1, n1, x2, n2, dirn) if n1 and n2 else 1.0
                mf = (bf == fav).to_numpy()
                yf = fit[col].to_numpy().astype(float)
                rec[kind] = {"favoured": str(fav), "fit_in": round(100 * yf[mf].mean(), 2), "fit_rest": round(100 * yf[~mf].mean(), 2),
                             "unseen_n": int(n1), "unseen_in": round(100 * x1 / n1, 2) if n1 else None,
                             "unseen_rest": round(100 * x2 / n2, 2) if n2 else None, "p": p,
                             "ratio_ci": ratio_ci(m, y, uns["day"].to_numpy()) if n1 and n2 else None}
                for wn in ("w4", "w5"):             # amendment 7: each unseen window on its own
                    sel = (uns["w"] == wn).to_numpy()
                    a1, b1 = y[m & sel].sum(), (m & sel).sum()
                    a2, b2 = y[~m & sel].sum(), (~m & sel).sum()
                    rec[kind][wn] = {"n_in": int(b1), "in": round(100 * a1 / b1, 2) if b1 else None,
                                     "rest": round(100 * a2 / b2, 2) if b2 else None,
                                     "p": ztest(a1, b1, a2, b2, dirn) if b1 and b2 else 1.0}
                pa.append((kind, rec))
            # Part B candidate
            best, bv = None, -np.inf
            for b in okb.index:
                for nm in RULES:
                    if okb.loc[b, nm] > bv:
                        best, bv = (b, nm), okb.loc[b, nm]
            b, nm = best
            m = (bu == b).to_numpy()
            v = uns["m_" + nm].to_numpy()[m] - ALLOW
            vw = {wn: uns["m_" + nm].to_numpy()[m & (uns["w"] == wn).to_numpy()] - ALLOW for wn in ("w4", "w5")}
            cand = {"fact": rec["fact"], "E": E, "bucket": str(b), "rule": RULE_NAME[nm], "fit_n": int(okb.loc[b, "n"]),
                    "fit_mean": round(float(bv), 2), "unseen_n": int(len(v)),
                    "unseen_mean": round(float(v.mean() + ALLOW), 2) if len(v) else None,
                    "after_allowance": round(float(v.mean()), 2) if len(v) else None,
                    "without_best": round(float((v.sum() - v.max()) / max(1, len(v) - 1)), 2) if len(v) > 1 else None,
                    "inProfit": round(100 * float((v + ALLOW > 0).mean()), 1) if len(v) else None,
                    "_v": v, "_vw": vw}
            pb.append(cand)
            res["partA"].append(rec)
    for kind in ("rocket", "zero"):
        items = [r for k, r in pa if k == kind]
        ok = holm(np.array([r[kind]["p"] for r in items])) if items else []
        ok4 = holm(np.array([r[kind]["w4"]["p"] for r in items])) if items else []
        for r, o, o4 in zip(items, ok, ok4):
            r[kind]["holm"] = bool(o)
            r[kind]["holm_w4"] = bool(o4)
            r[kind]["counts"] = bool(o and o4)      # amendment 7: also on the full unseen month alone
            r[kind]["p"] = float("%.3g" % r[kind]["p"])
            for wn in ("w4", "w5"):
                r[kind][wn]["p"] = float("%.3g" % r[kind][wn]["p"])
    k = max(1, len(pb))
    for cand in pb:
        v, vw = cand.pop("_v"), cand.pop("_vw")
        cand["lower_bound"] = round(boot_lo(v, 0.01 / k), 2) if len(v) >= 2 else None
        cand["holds_unseen"] = bool(len(v) >= 40 and v.mean() > 0 and cand["lower_bound"] is not None and cand["lower_bound"] > 0
                                    and cand["without_best"] > 0)
        cand["w4"], cand["w5"] = month_check(vw["w4"], k), month_check(vw["w5"], k)
        cand["holds"] = bool(cand["holds_unseen"] and cand["w4"]["passes"] and not (cand["w5"]["n"] and cand["w5"]["after_allowance"] < 0))
        res["partB"].append(cand)
    res["partB_candidates"] = k
    # ------------------------------------------------------------------- Part C
    res["partC"] = part_c(E_all, res["facts_available"])
    # ------------------------------------------------------------------- rocket lists and description
    for E in ES:
        e = E_all[E_all["E"] == E]
        r = e[e["rocket"]].sort_values("te")
        lst = pd.DataFrame({"window": r["w"], "graduated_utc": pd.to_datetime(r["t"], unit="ms").dt.strftime("%Y-%m-%d %H:%M"),
                            "ticker": r["symbol"], "name": r["token_name"], "mint": r["mint"],
                            "mcap_at_entry_usd": r["mc0"].round(0), "peak_x_24h": r["mx24"].round(1),
                            "minutes_to_10x": r["t10_min"], "lowest_before_10x": r["min_before10"].round(2),
                            "close_after_24h_x": r["last24"].round(2)})
        lst.to_csv(os.path.join(work, "rockets_E%d.csv" % E), index=False)
        d = {}
        for f in facts:
            if e[f].notna().mean() < 0.5:
                continue
            a, b = e[e["rocket"]][f].dropna(), e[~e["rocket"]][f].dropna()
            d[f] = {"rockets_median": round(float(a.median()), 3), "others_median": round(float(b.median()), 3),
                    "rockets_mean": round(float(a.mean()), 3), "others_mean": round(float(b.mean()), 3)}
        res["describe"][str(E)] = {"rockets": int(e["rocket"].sum()), "of": int(len(e)), "facts": d,
                                   "mcap_at_entry_median": {"rockets": round(float(e[e["rocket"]]["mc0"].median())),
                                                            "others": round(float(e[~e["rocket"]]["mc0"].median()))},
                                   "minutes_to_10x_median": float(e[e["rocket"]]["t10_min"].median()),
                                   "lowest_before_10x_median": round(float(e[e["rocket"]]["min_before10"].median()), 2),
                                   "rockets_that_fell_half_first_pct": round(100 * float((e[e["rocket"]]["min_before10"] <= 0.5).mean()), 1),
                                   "rockets_close_24h_below_entry_pct": round(100 * float((e[e["rocket"]]["last24"] < 1).mean()), 1)}
    return res


MODEL_FEATS = ["f_creator_prior", "f_creator_rocket", "f_curve_min", "f_dup7", "f_cjk", "f_hour", "f_weekend", "f_grads24",
               "f_sol24", "f_nlinks", "f_xtype", "f_news", "f_theme24", "f_post_age", "f_img_reused", "f_launch_other", "f_video",
               "f_desc_len", "f_group", "f_animated", "f_lookalike", "f_name_fit"]


def part_c(E_all, av):
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    everywhere = [f for f in MODEL_FEATS if all(av[f].get(w, 0) >= 0.8 for w in FIT_ALL + UNSEEN_ALL)]
    h2only = [f for f in MODEL_FEATS if f not in everywhere and all(av[f].get(w, 0) >= 0.8 for w in ("w3", "w4"))]
    if h2only:
        feats, fit_w, uns_w = everywhere + h2only, ("w3",), ("w4",)
    else:
        feats, fit_w, uns_w = everywhere, FIT_ALL, UNSEEN_ALL
    out = {"features": feats, "fit": list(fit_w), "unseen": list(uns_w), "models": []}
    cands = []
    for E in ES:
        e = E_all[E_all["E"] == E]
        fit, uns = e[e["w"].isin(fit_w)], e[e["w"].isin(uns_w)]
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=31, min_child_samples=50, random_state=7,
                                 verbose=-1)
        clf.fit(fit[feats].astype(float), fit["rocket"].astype(int))
        sf = clf.predict_proba(fit[feats].astype(float))[:, 1]
        su = clf.predict_proba(uns[feats].astype(float))[:, 1]
        auc = roc_auc_score(uns["rocket"].astype(int), su) if uns["rocket"].any() else None
        imp = dict(sorted(zip(feats, clf.booster_.feature_importance("gain").round(1).tolist()), key=lambda x: -x[1]))
        m = {"E": E, "unseen_auc": round(float(auc), 3) if auc else None, "gain": imp, "cuts": []}
        for wn in ("w4", "w5"):
            sel = (uns["w"] == wn).to_numpy()
            yy = uns["rocket"].astype(int).to_numpy()[sel]
            m["auc_" + wn] = round(float(roc_auc_score(yy, su[sel])), 3) if sel.any() and 0 < yy.sum() < len(yy) else None
        for top in (0.01, 0.02, 0.05):
            thr = np.quantile(sf, 1 - top)
            sel = su >= thr
            u = uns[sel]
            row = {"top": "%g%%" % (100 * top), "unseen_n": int(sel.sum()),
                   "rocketPct": round(100 * float(u["rocket"].mean()), 2) if len(u) else None,
                   "base_rocketPct": round(100 * float(uns["rocket"].mean()), 2)}
            for nm in RULES:
                v = u["m_" + nm].to_numpy() - ALLOW
                vw = {wn: u[u["w"] == wn]["m_" + nm].to_numpy() - ALLOW for wn in ("w4", "w5")}
                cands.append((row, nm, v, vw))
                row[nm] = {"mean": round(float(v.mean() + ALLOW), 2) if len(v) else None}
            m["cuts"].append(row)
        out["models"].append(m)
    k = len(cands)
    for row, nm, v, vw in cands:
        lb = round(boot_lo(v, 0.01 / k), 2) if len(v) >= 2 else None
        wb = round(float((v.sum() - v.max()) / max(1, len(v) - 1)), 2) if len(v) > 1 else None
        hu = bool(len(v) >= 40 and v.mean() > 0 and lb is not None and lb > 0 and wb > 0)
        m4, m5 = month_check(vw["w4"], k), month_check(vw["w5"], k)
        row[nm].update({"after_allowance": round(float(v.mean()), 2) if len(v) else None, "lower_bound": lb, "without_best": wb,
                        "holds_unseen": hu, "w4": m4, "w5": m5,
                        "holds": bool(hu and m4["passes"] and not (m5["n"] and m5["after_allowance"] < 0))})
    out["candidates"] = k
    return out


if __name__ == "__main__":
    r = main(*sys.argv[1:7])
    print(json.dumps(r, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
