"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md): the launch facts of every graduated coin of the
five month windows straight from the Solana chain and the coin's own metadata file, as a second source next to pump.fun's API
(research/rockets/meta_fetch.py), which answers little from GitHub's runners.

  shard <plan.json> <i> <n> <out.json.gz>   mints i, i+n, ...; the file is rewritten every 200 mints
  replan <plan dir> <earlier chain.parquet>   for a later run: plan.json without the coins an earlier run read, but with those
                                            whose curve history failed (sig_error, asked again; nofile.json = their files
                                            already read), and refetch.json = the [mint, link] pairs of the other unread files
  files <refetch.json> <i> <n> <out.json.gz>   only the metadata files of [mint, link] pairs i, i+n, ... (links an earlier run
                                            could not read); no RPC
  final <dir with shard files> <out dir> [<earlier chain.parquet>]   one chain.parquet (an earlier run's rows kept, their file
                                            fields filled from the files output where it read one)
  wiki  <first day> <last day> <out.json>   the 1,000 most-read English Wikipedia articles of each day (a "news of the day" list)
  wikifill <wiki_top.json>                  the days that list could not get (rate limit) asked again, slowly

Per mint:
  - name, ticker and the link to the metadata file: from the mint account's own metadata (Token-2022 coins, pump.fun's newer
    launches) or the Metaplex metadata account (older SPL coins); probe of 24 Oct: no coin had a Metaplex account
  - pump.fun's bonding-curve account (address derived from the mint): the creator wallet stored in it
  - the oldest transaction of the bonding-curve account = the coin's creation (time) and how many curve transactions it had;
    only for coins without history2's creation time (env NEED = a JSON list of those mints), at most PAGES pages of 1,000
  - the metadata file (IPFS, set at launch, cannot change): the X, Telegram and website links the creator gave
RPC: Helius with the HELIUS_API_KEY secret when it answers, otherwise the public Solana RPC. The key is never printed or saved.
Nothing is bought, no wallet is used."""
import base64, concurrent.futures, glob, gzip, hashlib, json, os, re, sys, threading, time, urllib.error, urllib.request

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
META = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
GATEWAYS = tuple(os.environ["GATEWAYS"].split(",")) if os.environ.get("GATEWAYS") else (   # env: the probe's best (gateways.py)
    "https://ipfs.io/ipfs/%s", "https://gateway.pinata.cloud/ipfs/%s", "https://dweb.link/ipfs/%s", "https://w3s.link/ipfs/%s",
    "https://4everland.io/ipfs/%s", "https://nftstorage.link/ipfs/%s", "https://ipfs.filebase.io/ipfs/%s")
WIKI = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia.org/all-access/%s"
UA = {"User-Agent": "memebot-research (github.com/maxpandelakis-boop/Meme-Bot)", "Accept": "application/json",
      "Content-Type": "application/json"}


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------------------------------------ addresses (no library)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58d(s):
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return (b"\0" * (len(s) - len(s.lstrip("1"))) + b).rjust(32, b"\0")


def b58e(b):
    n, s = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def on_curve(b):
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u, v = (y * y - 1) % _P, (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return True
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    return (x * x - x2) % _P == 0


def pda(seeds, program):
    """Program-derived address (checked against history2's PumpSwap pool addresses, 8 of 8, on 24 Oct)."""
    pb = b58d(program)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + pb + b"ProgramDerivedAddress").digest()
        if not on_curve(h):
            return b58e(h)
    raise ValueError("no address")


def metadata_address(mint):
    return pda([b"metadata", b58d(META), b58d(mint)], META)


def curve_address(mint):
    return pda([b"bonding-curve", b58d(mint)], PUMP)


# ------------------------------------------------------------------------------------------------ http
_locks, _last = {}, {}
_glock = threading.Lock()


def http(url, body=None, gap=0.2, tries=3, timeout=30):
    host = url.split("/")[2]
    with _glock:
        lk = _locks.setdefault(host, threading.Lock())
    code = None
    for i in range(tries):
        with lk:
            w = _last.get(host, 0) + gap - time.time()
            if w > 0:
                time.sleep(w)
            _last[host] = time.time()
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(300_000)
                return 200, raw
        except urllib.error.HTTPError as e:
            code = e.code
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524):
                time.sleep((2, 6, 15)[i])
                continue
            return code, None
        except Exception as e:
            code = type(e).__name__
            time.sleep(2 * (i + 1))
    return code, None


DROP_AFTER = int(os.environ.get("DROP_AFTER") or 10)


class Rpc:
    def __init__(self):
        k = os.environ.get("HK") or ""
        self.urls = []
        if k:
            self.helius = "https://mainnet.helius-rpc.com/?api-key=" + k
            st, j = self.call_url(self.helius, "getSlot", [])
            log("helius rpc", "works" if j is not None else "does not answer (%s)" % st)
            if j is not None:
                self.urls.append((self.helius, 0.12))
        self.urls.append((PUBLIC_RPC, float(os.environ.get("PGAP") or 0.35)))
        self.codes = {}
        self.miss = 0           # Helius answers in a row that were rate limits (429): after DROP_AFTER of them it is left out


    def call_url(self, url, method, params, gap=0.2):
        st, raw = http(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, gap=gap)
        if raw is None:
            return st, None
        try:
            j = json.loads(raw)
        except Exception:
            return "badjson", None
        if "error" in j:
            return "rpc%s" % (j["error"] or {}).get("code"), None
        return st, j.get("result")

    def call(self, method, params):
        for url, gap in list(self.urls):
            st, res = self.call_url(url, method, params, gap)
            key = ("helius " if "helius" in url else "public ") + str(st)
            self.codes[key] = self.codes.get(key, 0) + 1
            if "helius" in url and len(self.urls) > 1:
                self.miss = getattr(self, "miss", 0) + 1 if st == 429 else 0
                if self.miss >= DROP_AFTER:          # the key's limit is used up: each call would wait 23 s for nothing
                    with _glock:
                        if len(self.urls) > 1 and "helius" in self.urls[0][0]:
                            self.urls = self.urls[1:]
                            log("helius rpc left out after %d rate-limit answers in a row; public RPC only" % DROP_AFTER)
            if res is not None:
                return res
        return None


def parse_metadata(b64):
    try:
        d = base64.b64decode(b64)
        o = 1 + 32 + 32
        out = []
        for _ in range(3):
            n = int.from_bytes(d[o:o + 4], "little")
            out.append(d[o + 4:o + 4 + n].decode("utf-8", "replace").rstrip("\x00").strip())
            o += 4 + n
        return {"name": out[0], "symbol": out[1], "uri": out[2]}
    except Exception:
        return None


def parse_curve(b64):
    try:
        d = base64.b64decode(b64)
        return {"curve_creator": b58e(d[49:81])} if len(d) >= 81 and any(d[49:81]) else {}
    except Exception:
        return {}


CID = re.compile(r"(?:/ipfs/|^ipfs://)([A-Za-z0-9]+)")      # also the bare ipfs:// links, which the run of 24 Oct skipped
_gw = [0]


def gateway_order(k):
    """The gateways for the k-th file. GW_ROTATE unset: start at gateway k and go round (the load spread over all of them);
    GW_ROTATE=0: always the order of GATEWAYS (the probe's best first); GW_ROTATE=r: start at one of the first r in turn,
    then the others in GATEWAYS order (two paced gateways share the files, each with its own limit)."""
    rot = os.environ.get("GW_ROTATE")
    if not rot:
        return [GATEWAYS[(k + j) % len(GATEWAYS)] for j in range(len(GATEWAYS))]
    first = GATEWAYS[k % int(rot)] if int(rot) > 0 else GATEWAYS[0]
    return [first] + [g for g in GATEWAYS if g != first]


def metadata_file(uri):
    """The metadata JSON: an IPFS file over FILE_TRIES gateways (default 2; see gateway_order), anything else from its own link
    (FILE_TRIES tries, a pause between them, none after an answer that will not change such as 404)."""
    if not uri:
        return None, "nouri"
    m = CID.search(uri)
    if m:
        urls = [g % m.group(1) for g in gateway_order(_gw[0])][:TRIES]
        _gw[0] += 1
    else:
        urls = [uri] * TRIES
    last, sts = None, []
    for t, u in enumerate(urls):
        if not u.startswith("http"):
            continue
        if t and not m:
            if str(last) in ("400", "401", "403", "404", "410", "badjson"):
                break
            time.sleep(3 * t)
        st, raw = http(u, gap=float(os.environ.get("GW_GAP") or 0.4), tries=1, timeout=12)
        last = st
        if raw:
            try:
                return json.loads(raw), "ok"
            except Exception:
                last = "badjson"
        sts.append(str(last))
    return None, ("|".join(sts) if m and sts else str(last))     # IPFS: every gateway's answer, e.g. "404|403|429"


GONE = {"400", "401", "403", "404", "410", "badjson", "nouri", "None"}


def file_gone(st):
    """True when a failed file will not come later: a gateway said 404 or 410 (not in the IPFS network), or every answer
    was one that does not change. False for rate limits, timeouts and server errors, which a later run asks again."""
    parts = str(st).split("|")
    return st == "ok" or "404" in parts or "410" in parts or all(p in GONE for p in parts)


TRIES = int(os.environ.get("FILE_TRIES") or 2)


def file_fields(j):
    return {"f_twitter": j.get("twitter"), "f_telegram": j.get("telegram"), "f_website": j.get("website"),
            "f_name": j.get("name"), "f_symbol": j.get("symbol"), "f_createdOn": j.get("createdOn"),
            "f_showName": j.get("showName"), "f_desc_len": len(str(j.get("description") or "")),
            "f_keys": ",".join(sorted(map(str, j.keys())))[:300],
            "f_image": str(j.get("image") or "")[:200],
            "f_video": str(j.get("video") or j.get("animation_url") or j.get("video_uri") or "")[:200]}


PAGES = int(os.environ.get("PAGES") or 8)


def one(rpc, mint, cv, need):
    rec = {"mint": mint}
    if not need:
        return rec
    before, n = None, 0
    for _ in range(PAGES):
        o = {"limit": 1000}
        if before:
            o["before"] = before
        sigs = rpc.call("getSignaturesForAddress", [cv, o])
        if not isinstance(sigs, list):
            rec["sig_error"] = True
            return rec
        n += len(sigs)
        if sigs:
            before = sigs[-1]["signature"]
            rec["created_s"] = sigs[-1].get("blockTime")
        if len(sigs) < 1000:
            rec["curve_sigs"] = n
            return rec
    rec["curve_sigs_capped"] = n          # more than PAGES x 1,000 curve transactions: created_s is not the creation
    return rec


def token2022_meta(v):
    try:
        for ext in v["data"]["parsed"]["info"].get("extensions") or []:
            if ext.get("extension") == "tokenMetadata":
                st = ext.get("state") or {}
                return {"name": st.get("name"), "symbol": st.get("symbol"), "uri": st.get("uri")}
    except Exception:
        pass
    return None


def cmd_shard(plan, i, n, out):
    mints = json.load(open(plan))["mints"][int(i)::int(n)]
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 200))
    rpc = Rpc()
    need = set(json.load(open(os.environ["NEED"]))) if os.environ.get("NEED") else set(mints)
    nofile = set(json.load(open(os.environ["NOFILE"]))) if os.environ.get("NOFILE") and os.path.exists(os.environ["NOFILE"]) else set()
    res, files = {}, {}
    pool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("WORKERS") or 6))
    for a in range(0, len(mints), 100):
        if time.time() > stop:
            log("time budget used at", a, "of", len(mints))
            break
        part = mints[a:a + 100]
        mds = [metadata_address(m) for m in part]
        cvs = [curve_address(m) for m in part]
        acc0 = rpc.call("getMultipleAccounts", [part, {"encoding": "jsonParsed"}]) or {}
        acc = rpc.call("getMultipleAccounts", [mds, {"encoding": "base64"}]) or {}
        acc2 = rpc.call("getMultipleAccounts", [cvs, {"encoding": "base64"}]) or {}
        meta = {}
        none = [None] * len(part)
        for m, v in zip(part, (acc0.get("value") or none) if isinstance(acc0, dict) else none):
            t = token2022_meta(v) if v else None
            if t:
                meta[m] = dict(t, meta_src="token2022")
        for m, v in zip(part, (acc.get("value") or none) if isinstance(acc, dict) else none):
            if v and v.get("data") and m not in meta:
                meta[m] = dict(parse_metadata(v["data"][0]) or {}, meta_src="metaplex")
        for m, v in zip(part, (acc2.get("value") or none) if isinstance(acc2, dict) else none):
            if v and v.get("data"):
                meta.setdefault(m, {}).update(parse_curve(v["data"][0]))
        jobs = {pool.submit(one, rpc, m, cv, m in need): m for m, cv in zip(part, cvs)}
        fj = {pool.submit(metadata_file, meta.get(m, {}).get("uri")): m for m in part if m not in nofile}
        for f in concurrent.futures.as_completed(jobs):
            m = jobs[f]
            r = f.result()
            r.update({k: v for k, v in meta.get(m, {}).items()})
            res[m] = r
        for f in concurrent.futures.as_completed(fj):
            m = fj[f]
            j, st = f.result()
            files[st] = files.get(st, 0) + 1
            if isinstance(j, dict):
                res[m].update(file_fields(j))
        if a % 200 == 0 or a + 100 >= len(mints):
            got = sum(1 for r in res.values() if r.get("created_s"))
            log(a + len(part), "of", len(mints), "created", got, "names", sum(1 for r in res.values() if r.get("symbol")),
                "creator", sum(1 for r in res.values() if r.get("curve_creator")), "files", files, "rpc", rpc.codes)
            tmp = out + ".tmp"
            with gzip.open(tmp, "wt") as fh:
                json.dump({"coins": res, "done": a + len(part), "planned": len(mints)}, fh)
            os.replace(tmp, out)
    pool.shutdown()


def _clean(d):
    import pandas as pd
    for c in d.columns:
        if not pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].where(~d[c].isin(["NaN", "None", "null"]), None)
    return d


def cmd_replan(plan_dir, prev):
    import pandas as pd
    d = _clean(pd.read_parquet(prev))
    p = json.load(open(os.path.join(plan_dir, "plan.json")))
    redo = set(d.loc[d["sig_error"].notna(), "mint"]) if "sig_error" in d else set()
    done = set(d["mint"]) - redo
    n0 = len(p["mints"])
    p["mints"] = [x for x in p["mints"] if x not in done]
    json.dump(p, open(os.path.join(plan_dir, "plan.json"), "w"))
    unread = d["f_keys"].isna() & d["uri"].fillna("").str.len().gt(0)
    json.dump(sorted(d.loc[d["mint"].isin(redo) & ~unread, "mint"]), open(os.path.join(plan_dir, "nofile.json"), "w"))
    r = d[unread & ~d["mint"].isin(redo)].sort_values("mint")
    json.dump([[m, u] for m, u in zip(r["mint"], r["uri"])], open(os.path.join(plan_dir, "refetch.json"), "w"))
    log("planned", n0, "already read", len(done), "asked again (curve history failed)", len(redo), "left", len(p["mints"]),
        "metadata files to ask for again", len(r), "+", int((d["mint"].isin(redo) & unread).sum()), "in the coins asked again")


def cmd_files(refetch, i, n, out):
    """Only the metadata files, for links an earlier run could not read (no RPC); written every 500 links."""
    pairs = json.load(open(refetch))[int(i)::int(n)]
    stop = time.time() + 60 * float(os.environ.get("FILE_MINUTES", 200))
    pool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("FILE_WORKERS") or 16))
    res, codes = {}, {}
    for a in range(0, len(pairs), 500):
        if time.time() > stop:
            log("files: time budget used at", a, "of", len(pairs))
            break
        fj = {pool.submit(metadata_file, u): m for m, u in pairs[a:a + 500]}
        for f in concurrent.futures.as_completed(fj):
            j, st = f.result()
            codes[st] = codes.get(st, 0) + 1
            if isinstance(j, dict):
                res[fj[f]] = file_fields(j)
        log("files", a + len(fj), "of", len(pairs), codes)
        tmp = out + ".tmp"
        with gzip.open(tmp, "wt") as fh:
            json.dump({"files": res, "done": a + len(fj), "planned": len(pairs), "codes": codes}, fh)
        os.replace(tmp, out)
    pool.shutdown()


def cmd_wiki(day0, day1, out):
    """The 1,000 most-read English Wikipedia articles of every day from day0 to day1 (Wikimedia's free pageview API)."""
    import datetime as dt
    d, end, res = dt.date.fromisoformat(day0), dt.date.fromisoformat(day1), {}
    while d <= end:
        st, raw = http(WIKI % d.strftime("%Y/%m/%d"), gap=0.3)
        try:
            arts = json.loads(raw)["items"][0]["articles"] if raw else []
        except Exception:
            arts = []
        res[d.isoformat()] = [[a.get("article"), a.get("views")] for a in arts]
        if d.day == 1:
            log(d, st, len(arts))
        d += dt.timedelta(days=1)
    json.dump(res, open(out, "w"))
    log("days", len(res), "with articles", sum(1 for v in res.values() if v))


def cmd_wikifill(path):
    """Ask again, slowly, for the days the wiki command got no list for (Wikimedia answered 429), and rewrite the file."""
    res = json.load(open(path))
    empty = sorted(d for d, v in res.items() if not v)
    for d in empty:
        arts = []
        for k in range(5):
            st, raw = http(WIKI % d.replace("-", "/"), gap=2.0)
            try:
                arts = json.loads(raw)["items"][0]["articles"] if raw else []
            except Exception:
                arts = []
            if arts:
                break
            time.sleep(20 * (k + 1))
        res[d] = [[a.get("article"), a.get("views")] for a in arts]
        log(d, st, len(arts))
    json.dump(res, open(path, "w"))
    log("days", len(res), "with articles", sum(1 for v in res.values() if v), "asked again", len(empty))


def cmd_final(src, out, prev=None):
    """One chain.parquet from the shard files, plus the rows of an earlier run (prev) for the coins this run left out."""
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    rows, files = [], {}
    for f in sorted(glob.glob(os.path.join(src, "**", "*.json.gz"), recursive=True)):
        j = json.load(gzip.open(f, "rt"))
        rows += list((j.get("coins") or {}).values())
        files.update(j.get("files") or {})
    d = pd.DataFrame(rows).drop_duplicates("mint")
    if prev and os.path.exists(prev):
        old = _clean(pd.read_parquet(prev))
        if len(d):                     # coins asked again: what this run could not read is kept from the earlier run
            o = old.drop_duplicates("mint").set_index("mint")
            again = d["mint"].isin(o.index)
            fcols = [c for c in o.columns if c.startswith("f_")]
            for c in set(fcols) | {"name", "symbol", "uri", "meta_src", "curve_creator"}:
                d[c] = d[c].astype(object) if c in d else None      # an all-empty column would be float and refuse text
            nof = again & d["f_keys"].isna()
            for c in fcols:
                d.loc[nof, c] = d.loc[nof, "mint"].map(o[c])
            for c in ("name", "symbol", "uri", "meta_src", "curve_creator"):
                miss = again & d[c].isna()
                d.loc[miss, c] = d.loc[miss, "mint"].map(o[c])
            log("coins asked again", int(again.sum()), "their files kept from the earlier run", int(nof.sum()))
        got = old["mint"].isin(set(files)) & old["f_keys"].isna()
        for c in next(iter(files.values()), {}):
            old[c] = old[c].astype(object) if c in old else None
            old.loc[got, c] = [files[m].get(c) for m in old.loc[got, "mint"]]
        log("earlier run", len(old), "this run", len(d), "earlier rows given a metadata file now", int(got.sum()))
        d = pd.concat([d, old[~old["mint"].isin(set(d["mint"]) if len(d) else set())]], ignore_index=True)
    for c in ("f_desc_len", "created_s", "curve_sigs", "curve_sigs_capped"):      # numbers stay numbers after the merges
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in d.columns:
        if (d[c].dtype == object or pd.api.types.is_string_dtype(d[c])) and c != "mint":
            d[c] = d[c].map(lambda x: None if x is None or (isinstance(x, float) and x != x) else
                            (x if isinstance(x, str) else json.dumps(x)))           # a missing value stays empty, not "NaN"
    d.to_parquet(os.path.join(out, "chain.parquet"), index=False)
    log("coins", len(d), {c: int(d[c].notna().sum()) for c in d.columns})


if __name__ == "__main__":
    {"shard": cmd_shard, "replan": cmd_replan, "files": cmd_files, "final": cmd_final, "wiki": cmd_wiki, "wikifill": cmd_wikifill}[sys.argv[1]](*sys.argv[2:])
