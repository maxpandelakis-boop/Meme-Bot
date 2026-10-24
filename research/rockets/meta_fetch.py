"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md): the launch facts of every graduated coin of the
five month windows, from pump.fun's public coin page data (name, ticker, creator wallet, creation time, the X / Telegram / website
links set at launch, the time it reached "king of the hill" on the bonding curve). Values that change after the launch (market
cap, replies, last trade) are not kept. Where pump.fun gives nothing, GeckoTerminal's token list gives at least name and ticker.

  plan  <monthsdata dir> <monthsh2 dir> <out dir>      the mints, start SOL side >= 10, in the five windows
  shard <plan.json> <i> <n> <out.json.gz>              mints i, i+n, ...; the file is rewritten every 200 mints
  final <dir with shard files> <out dir> [<old dir>]   one meta.parquet (an older one's rows kept for mints not fetched now)
Nothing is bought, no wallet, key or secret is used."""
import glob, gzip, json, os, sys, time, urllib.error, urllib.request

# Run 1 (24 Oct 08:20 UTC): /coins/<mint> on v3 answered 404 for every coin and the old host 530, so run 2 first tries these forms
# on a few coins and keeps the first one that answers with the coin.
PF = ("https://frontend-api-v3.pump.fun/coins/%s?sync=true", "https://frontend-api-v3.pump.fun/coins/%s",
      "https://frontend-api-v3.pump.fun/coins?searchTerm=%s&limit=5&offset=0&includeNsfw=true",
      "https://frontend-api-v3.pump.fun/coins/search?searchTerm=%s&limit=5&offset=0&includeNsfw=true",
      "https://frontend-api-v2.pump.fun/coins/%s", "https://advanced-api-v2.pump.fun/coins/%s")
GT = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/multi/%s"
KEEP = ("mint", "name", "symbol", "creator", "created_timestamp", "twitter", "telegram", "website", "king_of_the_hill_timestamp",
        "nsfw", "show_name", "image_uri", "video_uri", "is_banned", "hidden", "metadata_uri")
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))
UA = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (memebot-research)", "Origin": "https://pump.fun",
      "Referer": "https://pump.fun/"}
_last = {}


def log(*a):
    print(*a, flush=True)


def get(url, gap, tries=3):
    host = url.split("/")[2]
    w = _last.get(host, 0) + gap - time.time()
    if w > 0:
        time.sleep(w)
    code = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                _last[host] = time.time()
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            code = e.code
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524):
                time.sleep((2, 6, 15)[i])
                continue
            return e.code, None
        except Exception as e:
            code = type(e).__name__
            time.sleep(2 * (i + 1))
    return code, None


def cmd_plan(md, h2, out):
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    ms = lambda d: int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)
    inw = lambda t: any(ms(a) <= t < ms(b) for _, a, b in WINDOWS)
    rows = pd.read_parquet(os.path.join(h2, "meta_h2.parquet"))[["mint", "t", "sol0"]].to_dict("records")
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        rows += [{"mint": r["mint"], "t": r["t"], "sol0": r["sol0"]} for r in json.load(open(f))]
    mints = sorted({r["mint"] for r in rows if r["sol0"] >= 10 and inw(int(r["t"]))})
    json.dump({"mints": mints}, open(os.path.join(out, "plan.json"), "w"))
    log("mints", len(mints))


def save(out, res, k, n):
    tmp = out + ".tmp"
    with gzip.open(tmp, "wt") as fh:
        json.dump({"coins": res, "done": k, "planned": n}, fh)
    os.replace(tmp, out)


def coin_of(j, m):
    if isinstance(j, dict) and j.get("mint") == m:
        return j
    items = j if isinstance(j, list) else (j.get("coins") or j.get("data") or []) if isinstance(j, dict) else []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("mint") == m:
            return it
    return None


def cmd_shard(plan, i, n, out):
    mints = json.load(open(plan))["mints"][int(i)::int(n)]
    gap = float(os.environ.get("PF_GAP") or 0.8)
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 300))
    res, codes, fails = {}, {}, 0
    src = None
    for t, tpl in enumerate(PF):
        got = []
        for m in mints[:4]:
            code, j = get(tpl % m, gap)
            c = coin_of(j, m)
            got.append(code if c is None else "coin")
            if c is not None:
                log("probe", tpl, "->", sorted(c.keys())[:40])
        log("probe", tpl, got)
        if "coin" in got:
            src = t
            break
    if src is None:
        log("no pump.fun form answers with the coin from here; nothing fetched")
        save(out, res, 0, len(mints))
        return
    for k, m in enumerate(mints):
        if time.time() > stop:
            log("time budget used at", k, "of", len(mints))
            break
        code, j = get(PF[src] % m, gap)
        codes[str(code)] = codes.get(str(code), 0) + 1
        c = coin_of(j, m)
        if c is not None:
            res[m] = {key: c.get(key) for key in KEEP}
            fails = 0
        else:
            fails += 1
        if k < 3 or k % 200 == 199:
            log(k + 1, "of", len(mints), "got", len(res), codes)
            save(out, res, k + 1, len(mints))
        if fails >= 300 and len(res) < 0.05 * (k + 1):
            log("pump.fun answers nothing from here; stopping the pump.fun part at", k + 1)
            break
    # names for the rest from GeckoTerminal, 30 per call
    rest = [m for m in mints if m not in res] if not os.environ.get("SKIP_GT") else []
    gt = 0
    for a in range(0, len(rest), 30):
        if time.time() > stop + 1800:
            break
        code, j = get(GT % ",".join(rest[a:a + 30]), float(os.environ.get("GT_GAP") or 2.2))
        for d in ((j or {}).get("data") or []) if isinstance(j, dict) else []:
            at = d.get("attributes") or {}
            if at.get("address"):
                res[at["address"]] = {"mint": at["address"], "name": at.get("name"), "symbol": at.get("symbol"), "src": "gt"}
                gt += 1
    log("done: pump.fun", sum(1 for r in res.values() if r.get("src") != "gt"), "geckoterminal", gt, "of", len(mints), codes)
    save(out, res, len(mints), len(mints))


def cmd_final(src, out, old=None):
    """Joins the shards; rows of an older meta.parquet (old dir) are kept for mints this run did not get."""
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(src, "**", "*.json.gz"), recursive=True)):
        rows += list(json.load(gzip.open(f, "rt"))["coins"].values())
    d = pd.DataFrame(rows)
    if old and os.path.exists(os.path.join(old, "meta.parquet")):
        d = pd.concat([d, pd.read_parquet(os.path.join(old, "meta.parquet"))], ignore_index=True)
    d = d.drop_duplicates("mint", keep="first")
    for c in d.columns:
        if d[c].dtype == object and c not in ("mint",):
            d[c] = d[c].map(lambda x: None if x is None else (x if isinstance(x, str) else json.dumps(x)))
    d.to_parquet(os.path.join(out, "meta.parquet"), index=False)
    log("coins", len(d), "from pump.fun", int((d.get("src") != "gt").sum()) if "src" in d else len(d))


if __name__ == "__main__":
    {"plan": cmd_plan, "shard": cmd_shard, "final": cmd_final}[sys.argv[1]](*sys.argv[2:])
