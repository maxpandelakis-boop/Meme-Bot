"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md, amendment 6): every pump.fun launch of the five
month windows from the Solana chain, not only the ~72,000 that graduated, for the user's ask to compare as many coins as possible.

  probe <out.json>                     what the free sources give (public Solana RPC, Helius when HK is set, HuggingFace, pump.fun)
  probe2 <out.json>                    the HuggingFace pump.fun datasets in detail (files, sizes, columns, first rows) and the
                                       launch transactions the first probe could not read (error -32015, a newer version)
  probe3 <work dir> <grad mints.json>  the three free launch datasets up close: their documents, file coverage by day, one file
                                       of each read, 100 random rows of each checked against the chain, overlap with our graduations
  verify <work dir> <monthsdata dir> <monthsh2 dir>   the test of amendment 6 for the two datasets used (Slinky21's corpus for
                                       w2, Slinky21's Pumpfun_v2 for w3-w5): completeness against the chain's own launch list in
                                       random hours, 300 random rows against the chain, and how many of our graduations they hold
  verify2 <work dir> <monthsdata dir> <monthsh2 dir>   amendment 8: Pumpfun_v2 again (half-hours of 10 Aug - 6 Oct with the
                                       launch transactions read, rows against their own launch transaction, our graduations of
                                       the days it covers) and loopholetape's launches for 9-17 Oct, and the two on the days both hold
  build <work> <monthsdata> <monthsh2> <out dir>   universe L of amendment 6 from the two checked datasets: one row per launch
                                       (L_<w>[_<part>].parquet: mint, curve, creator, name, ticker, metadata link, launch time,
                                       graduated and when)
  mshard <universe dir> <i> <n> <out.json.gz>   launches i, i+n, ... of the metadata sample (MSAMPLE, default 600,000, seed 7):
                                       the metadata file (links, picture, video, description, createdOn) and the curve's
                                       complete flag on the chain
  mfinal <dir with shard files> <out dir> [<earlier lmeta.parquet>]   one lmeta.parquet
  sigs <out dir>                       every launch signature of the five windows (sigs_<w>.parquet: signature, slot, time, failed)
  shard <sig dir> <i> <n> <out.json.gz> launches i, i+n, ... of the random sample (SAMPLE launches, seed 7): the launch
                                       transaction, the curve account (graduated or not, read now) and the metadata file
  final <dir with shard files> <out dir> [<earlier launches.parquet>]   one launches.parquet

Each launch is a transaction that touches pump.fun's mint authority (one fixed address that only signs new coins). Its CreateEvent
log holds the name, ticker, metadata link, mint, creator and time; the TradeEvent logs of the same transaction hold the creator's
own first buy. Nothing is bought. HK (the Helius key) is only passed to the script, never printed or saved."""
import base64, concurrent.futures, glob, gzip, hashlib, itertools, json, os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta_chain import PUMP, PUBLIC_RPC, Rpc, b58e, curve_address, http, log, metadata_file, pda  # noqa: E402

MINT_AUTHORITY = pda([b"mint-authority"], PUMP)
EV_CREATE = hashlib.sha256(b"event:CreateEvent").digest()[:8]
EV_TRADE = hashlib.sha256(b"event:TradeEvent").digest()[:8]


def _str(d, o):
    n = int.from_bytes(d[o:o + 4], "little")
    return d[o + 4:o + 4 + n].decode("utf-8", "replace"), o + 4 + n


def parse_launch(tx):
    """CreateEvent (+ the creator's buys in the same transaction) of one launch transaction, or None."""
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return None
    rec, buys = None, 0
    for line in (tx.get("meta") or {}).get("logMessages") or []:
        if not line.startswith("Program data: "):
            continue
        try:
            d = base64.b64decode(line[14:])
        except Exception:
            continue
        if d[:8] == EV_CREATE and rec is None:
            try:
                o = 8
                name, o = _str(d, o)
                symbol, o = _str(d, o)
                uri, o = _str(d, o)
                keys = []
                for _ in range(4):
                    if len(d) >= o + 32:
                        keys.append(b58e(d[o:o + 32]))
                        o += 32
                rec = {"name": name, "symbol": symbol, "uri": uri, "mint": keys[0], "curve": keys[1], "user": keys[2],
                       "creator": keys[3] if len(keys) > 3 else None, "ev_len": len(d)}
                if len(d) >= o + 8:
                    rec["ev_ts"] = int.from_bytes(d[o:o + 8], "little", signed=True)
            except Exception:
                return None
        elif d[:8] == EV_TRADE and len(d) >= 8 + 32 + 17:
            if d[8 + 32 + 16]:
                buys += int.from_bytes(d[40:48], "little")
    if rec:
        rec["dev_buy_sol"] = buys / 1e9
        rec["slot"] = tx.get("slot")
        rec["block_time"] = tx.get("blockTime")
    return rec


def rpc_only(url, gap):
    r = Rpc.__new__(Rpc)
    r.urls, r.codes = [(url, gap)], {}
    return r


def timed(f, *a):
    t = time.time()
    v = f(*a)
    return v, round(time.time() - t, 2)


def slot_at(rpc, ts, hi):
    """Binary search for the first slot whose block time is at or after ts (skipped slots step forward)."""
    lo = hi - int((time.time() - ts) / 0.4 * 1.3)
    for _ in range(40):
        if hi - lo < 50:
            break
        mid = (lo + hi) // 2
        bt = None
        for k in range(20):
            bt = rpc.call("getBlockTime", [mid + k])
            if bt is not None:
                break
        if bt is None:
            return None
        if bt < ts:
            lo = mid
        else:
            hi = mid
    return hi


def sig_near(rpc, ts, top):
    s = slot_at(rpc, ts, top)
    if s is None:
        return None, None
    for k in range(30):
        b = rpc.call("getBlock", [s + k, {"transactionDetails": "signatures", "maxSupportedTransactionVersion": 1, "rewards": False}])
        if b and b.get("signatures"):
            return b["signatures"][0], s + k
    return None, s


def probe_rpc(name, rpc, out):
    o = out.setdefault(name, {})
    top = rpc.call("getSlot", [])
    o["slot"] = top
    sigs, sec = timed(rpc.call, "getSignaturesForAddress", [MINT_AUTHORITY, {"limit": 1000}])
    if not isinstance(sigs, list):
        o["signatures"] = "no answer %s" % rpc.codes
        return
    bt = [s.get("blockTime") for s in sigs if s.get("blockTime")]
    o["signatures"] = {"n": len(sigs), "seconds": sec, "failed": sum(s.get("err") is not None for s in sigs),
                       "span_minutes": round((max(bt) - min(bt)) / 60, 1) if bt else None}
    if bt and max(bt) > min(bt):
        o["launches_per_day_now"] = round(len(sigs) / ((max(bt) - min(bt)) / 86400))
    ok = [s["signature"] for s in sigs if s.get("err") is None]
    got, sec = timed(lambda: [rpc.call("getTransaction", [x, {"encoding": "json", "maxSupportedTransactionVersion": 0}]) for x in ok[:6]])
    parsed = [parse_launch(t) for t in got]
    o["tx_now"] = {"seconds_for_6": sec, "parsed": sum(p is not None for p in parsed),
                   "examples": [{k: p.get(k) for k in ("name", "symbol", "mint", "creator", "user", "dev_buy_sol", "ev_len", "block_time")}
                                for p in parsed if p][:3]}
    if parsed and parsed[0]:
        o["curve_pda_matches_event"] = sum(p is not None and curve_address(p["mint"]) == p["curve"] for p in parsed)
    # speed: 120 transactions with 8 threads
    pool = concurrent.futures.ThreadPoolExecutor(8)
    t = time.time()
    res = list(pool.map(lambda x: rpc.call("getTransaction", [x, {"encoding": "json", "maxSupportedTransactionVersion": 0}]), ok[:120]))
    o["speed"] = {"tx": len(res), "ok": sum(r is not None for r in res), "per_second": round(len(res) / (time.time() - t), 1),
                  "codes": dict(rpc.codes)}
    # archive: a launch from the first window (25 Apr 2026)
    for label, ts in (("apr25", 1777075200), ("aug10", 1786320000)):
        s, slot = sig_near(rpc, ts, top)
        if not s:
            o[label] = "no block found %s" % rpc.codes
            continue
        old = rpc.call("getSignaturesForAddress", [MINT_AUTHORITY, {"limit": 1000, "before": s}])
        if not isinstance(old, list) or not old:
            o[label] = {"slot": slot, "signatures": "none %s" % rpc.codes}
            continue
        bt = [x.get("blockTime") for x in old if x.get("blockTime")]
        tx = rpc.call("getTransaction", [old[0]["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}])
        p = parse_launch(tx)
        o[label] = {"slot": slot, "n": len(old), "first_time": max(bt) if bt else None, "last_time": min(bt) if bt else None,
                    "launches_per_day": round(len(old) / ((max(bt) - min(bt)) / 86400)) if bt and max(bt) > min(bt) else None,
                    "tx_parsed": {k: p.get(k) for k in ("name", "symbol", "mint", "creator", "dev_buy_sol")} if p else None}
    pool.shutdown()


def probe_web(out):
    w = out.setdefault("web", {})
    for q in ("pump", "pumpfun", "pump.fun", "memecoin", "solana token", "solana meme"):
        st, raw = http("https://huggingface.co/api/datasets?search=%s&limit=100&full=false" % q.replace(" ", "%20"), gap=0.5, tries=2)
        try:
            w["hf:" + q] = [(d["id"], d.get("downloads"), (d.get("lastModified") or "")[:10]) for d in json.loads(raw)]
        except Exception:
            w["hf:" + q] = "status %s" % st
    for u in ("https://frontend-api-v3.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true",
              "https://frontend-api-v3.pump.fun/coins/latest",
              "https://frontend-api-v3.pump.fun/coins/for-you?offset=0&limit=50&includeNsfw=true",
              "https://advanced-api-v2.pump.fun/coins/list?sortBy=creationTime&limit=50"):
        st, raw = http(u, gap=0.5, tries=1)
        w[u] = {"status": st, "head": (raw or b"")[:300].decode("utf-8", "replace")}


def cmd_probe(out_path):
    out = {"mint_authority": MINT_AUTHORITY}
    log("mint authority", MINT_AUTHORITY)
    k = os.environ.get("HK") or ""
    if k:
        try:
            probe_rpc("helius", rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12), out)
        except Exception as e:
            out["helius"] = "error %s" % type(e).__name__
        log(json.dumps(out.get("helius"))[:3000])
    try:
        probe_rpc("public", rpc_only(PUBLIC_RPC, 0.3), out)
    except Exception as e:
        out["public"] = "error %s" % type(e).__name__
    log(json.dumps(out.get("public"))[:3000])
    probe_web(out)
    log(json.dumps(out["web"])[:6000])
    json.dump(out, open(out_path, "w"), indent=1)


HF_SETS = ("loopholetape/pumpfun-launches", "Slinky21/Pumpfun_v2_dataset", "Slinky21/Pumpfun_Memecoin_Corpus",
           "jocry/Pumpfun_Memecoin_Corpus", "Tr4m0ryp/trenches-pumpfun-forward-2026-08", "akilx/pump-fun-point-in-time-forensics",
           "akilx/pump-fun-30days-forensic-trades", "pumpdatafun/pump-fun-trades-sample", "blackhawkdragon/pumpfun-real-data",
           "evnisv/pump-fun", "Pumpdotstudio/pump-fun-sentiment-100k", "Rain729/pumpire-6k", "biznus1/pumpswap-historical-trades",
           "DataStore/pumpswap-amm-historical-data-sample", "muhammetakkurt/pump-fun-meme-token-dataset", "rincel/pumpfun")


def cmd_probe2(out_path):
    out = {"hf": {}, "tx_versions": {}}
    for ds in HF_SETS:
        o = out["hf"].setdefault(ds, {})
        st, raw = http("https://huggingface.co/api/datasets/%s?blobs=true" % ds, gap=0.4, tries=2)
        try:
            j = json.loads(raw)
            o["files"] = [(x.get("rfilename"), x.get("size")) for x in j.get("siblings") or []][:60]
            o["n_files"] = len(j.get("siblings") or [])
            o["bytes"] = sum((x.get("size") or 0) for x in j.get("siblings") or [])
            o["card"] = {k: j.get("cardData", {}).get(k) for k in ("license", "size_categories", "pretty_name")} if j.get("cardData") else None
            o["modified"] = j.get("lastModified")
        except Exception:
            o["api"] = "status %s" % st
        st, raw = http("https://huggingface.co/datasets/%s/resolve/main/README.md" % ds, gap=0.4, tries=1)
        o["readme"] = (raw or b"")[:2500].decode("utf-8", "replace") if raw else "status %s" % st
        st, raw = http("https://datasets-server.huggingface.co/size?dataset=%s" % ds, gap=0.4, tries=1)
        try:
            o["rows"] = [(c.get("config"), c.get("split"), c.get("num_rows")) for c in json.loads(raw)["size"].get("splits", [])]
        except Exception:
            o["rows"] = "status %s" % st
        st, raw = http("https://datasets-server.huggingface.co/first-rows?dataset=%s&config=default&split=train" % ds, gap=0.4, tries=1)
        try:
            fr = json.loads(raw)
            o["columns"] = [(f.get("name"), (f.get("type") or {}).get("dtype")) for f in fr.get("features", [])]
            o["first_rows"] = [{k: str(v)[:80] for k, v in r["row"].items()} for r in fr.get("rows", [])[:3]]
        except Exception:
            o["first_rows"] = "status %s" % st
        log(ds, json.dumps({k: v for k, v in o.items() if k != "readme"})[:1500])
        log("README", ds, (o.get("readme") or "")[:1200].replace("\n", " | "))
    k = os.environ.get("HK") or ""
    if k:
        rpc = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12)
        for label, before in (("now", None), ("apr25", None)):
            o = {"limit": 200}
            if label == "apr25":
                s, _ = sig_near(rpc, 1777075200 + 6 * 3600, rpc.call("getSlot", []))
                o["before"] = s
            sigs = [x["signature"] for x in (rpc.call("getSignaturesForAddress", [MINT_AUTHORITY, o]) or []) if x.get("err") is None][:60]
            res = {}
            for v in (0, 1, 2):
                rr = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12)
                got = [rr.call("getTransaction", [x, {"encoding": "json", "maxSupportedTransactionVersion": v}]) for x in sigs]
                res["max_version_%d" % v] = {"ok": sum(g is not None for g in got), "parsed": sum(parse_launch(g) is not None for g in got if g),
                                             "versions": sorted({str(g.get("version")) for g in got if g}), "codes": dict(rr.codes)}
            rr = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12)
            raw_err = rr.call_url(rr.urls[0][0], "getTransaction", [sigs[0], {"encoding": "json"}]) if sigs else None
            res["no_version_answer"] = str(raw_err)[:300]
            out["tx_versions"][label] = res
            log("tx versions", label, json.dumps(res)[:1500])
    json.dump(out, open(out_path, "w"), indent=1)


HF = "https://huggingface.co/datasets/%s/resolve/main/%s"
DATASETS = {"corpus": "Slinky21/Pumpfun_Memecoin_Corpus", "v2": "Slinky21/Pumpfun_v2_dataset",
            "loophole": "loopholetape/pumpfun-launches"}


def hf_files(ds):
    st, raw = http("https://huggingface.co/api/datasets/%s?blobs=true" % ds, gap=0.4, tries=3, timeout=60)
    j = json.loads(raw)
    return [(x.get("rfilename"), x.get("size") or 0) for x in j.get("siblings") or []]


def hf_get(ds, path, dest):
    """One file of a dataset to dest (streamed; urllib follows HuggingFace's redirect to its file store)."""
    import shutil, urllib.request
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    req = urllib.request.Request(HF % (ds, path), headers={"User-Agent": "memebot-research"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh, 1 << 20)
    return dest


def chain_check(rpc, rows):
    """For dataset rows (mint, name, symbol, uri, creator where present): the mint's own Token-2022 metadata and the curve
    account's creator, compared field by field."""
    from meta_chain import token2022_meta, parse_curve
    out = {"checked": 0, "mint_found": 0}
    for a in range(0, len(rows), 100):
        part = rows[a:a + 100]
        mints = [r["mint"] for r in part]
        acc = rpc.call("getMultipleAccounts", [mints, {"encoding": "jsonParsed"}]) or {}
        acc2 = rpc.call("getMultipleAccounts", [[curve_address(m) for m in mints], {"encoding": "base64"}]) or {}
        for r, v, c in zip(part, acc.get("value") or [None] * len(part), acc2.get("value") or [None] * len(part)):
            out["checked"] += 1
            t = token2022_meta(v) if v else None
            if v:
                out["mint_found"] += 1
            cr = parse_curve(c["data"][0]).get("curve_creator") if c and c.get("data") else None
            for k, chain_v in (("name", (t or {}).get("name")), ("symbol", (t or {}).get("symbol")), ("uri", (t or {}).get("uri")),
                               ("creator", cr)):
                if r.get(k) is None or chain_v is None:
                    continue
                key = k + "_same"
                out.setdefault(key, [0, 0])
                out[key][1] += 1
                out[key][0] += int(str(r[k]).strip() == str(chain_v).strip())
    return out


def pick(cols, *names):
    for n in names:
        for c in cols:
            if c.lower() == n:
                return c
    return None


def summarize(df, label, grads, rpc, out):
    import numpy as np, pandas as pd
    cols = list(df.columns)
    o = out.setdefault(label, {})
    o["rows"], o["columns"] = len(df), [(c, str(t)) for c, t in df.dtypes.items()]
    o["first_rows"] = [{k: str(v)[:70] for k, v in r.items()} for r in df.head(3).to_dict("records")]
    mc = pick(cols, "mint", "token_mint", "mint_address", "token")
    tc = pick(cols, "created_at", "created_timestamp", "block_time", "timestamp", "created", "launch_time", "ts", "time", "slot_time")
    if tc:
        t = df[tc]
        num = pd.api.types.is_numeric_dtype(t) and not pd.api.types.is_bool_dtype(t)
        tt = pd.to_datetime(t, unit="ms" if t.max() > 1e11 else "s", utc=True, errors="coerce") if num else \
            pd.to_datetime(t, utc=True, errors="coerce")
        o["time_col"], o["from"], o["to"] = tc, str(tt.min()), str(tt.max())
        days = max((tt.max() - tt.min()).total_seconds() / 86400, 1e-9)
        o["rows_per_day"] = round(len(df) / days)
    if mc:
        m = set(df[mc].astype(str))
        o["mint_col"], o["distinct_mints"] = mc, len(m)
        o["our_graduations_in_it"] = len(m & grads)
        nc, sc, uc = pick(cols, "name", "token_name"), pick(cols, "symbol", "token_symbol", "ticker"), pick(cols, "uri", "metadata_uri")
        cc = pick(cols, "creator", "dev_wallet", "creator_wallet", "user", "dev")
        rng = np.random.default_rng(7)
        sub = df.iloc[rng.choice(len(df), size=min(100, len(df)), replace=False)]
        rows = [{"mint": str(r[mc]), "name": r.get(nc) if nc else None, "symbol": r.get(sc) if sc else None,
                 "uri": r.get(uc) if uc else None, "creator": r.get(cc) if cc else None} for _, r in sub.iterrows()]
        o["chain_check"] = chain_check(rpc, rows)
    log(label, json.dumps(o)[:4000])


def cmd_probe3(work, grads_path):
    import pandas as pd
    os.makedirs(work, exist_ok=True)
    grads = set(json.load(open(grads_path))["mints"])
    k = os.environ.get("HK") or ""
    rpc = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12) if k else rpc_only(PUBLIC_RPC, 0.3)
    out = {}
    for key, ds in DATASETS.items():
        o = out.setdefault(key, {"dataset": ds})
        try:
            files = hf_files(ds)
        except Exception as e:
            o["files"] = "error %s" % type(e).__name__
            continue
        by = {}
        for f, sz in files:
            top = "/".join(f.split("/")[:-1]) or "."
            b = by.setdefault(top, [0, 0, f, f])
            b[0] += 1
            b[1] += sz
            b[2], b[3] = min(b[2], f), max(b[3], f)
        o["folders"] = {k2: {"files": v[0], "MB": round(v[1] / 1e6), "first": v[2], "last": v[3]} for k2, v in sorted(by.items())}
        log(key, "folders", json.dumps(o["folders"])[:3000])
        for doc in ("README.md", "KNOWN_ISSUES.md", "DATASHEET.md"):
            if any(f == doc for f, _ in files):
                st, raw = http(HF % (ds, doc), gap=0.3, tries=2, timeout=60)
                txt = (raw or b"").decode("utf-8", "replace")
                o[doc] = txt[:20000]
                log("=====", key, doc, len(txt), "chars =====")
                log(txt[:9000])
        want = []
        if key == "corpus":
            want = ["tokens.parquet", "migrations.parquet"]
        elif key == "v2":
            cr = sorted([(sz, f) for f, sz in files if "/create/" in f and f.endswith(".parquet")])
            gr = sorted([(sz, f) for f, sz in files if "/graduate/" in f and f.endswith(".parquet")])
            want = [cr[len(cr) // 2][1]] if cr else []
            want += [gr[len(gr) // 2][1]] if gr else []
        else:
            la = sorted(f for f, _ in files if f.startswith("data/launches/") and f.endswith(".parquet"))
            lg = sorted(f for f, _ in files if f.startswith("data/launches_legacy/") and f.endswith(".parquet"))
            want = ([la[len(la) // 2]] if la else []) + ([lg[len(lg) // 2]] if lg else []) + \
                   [f for f, _ in files if f.startswith("data/graduation_pools/") and f.endswith(".parquet")]
        for f in want:
            try:
                dest = hf_get(ds, f, os.path.join(work, key, f))
                df = pd.read_parquet(dest)
                summarize(df, "%s:%s" % (key, f), grads, rpc, o)
            except Exception as e:
                o[f] = "error %s %s" % (type(e).__name__, str(e)[:200])
                log(key, f, o[f])
    json.dump(out, open(os.path.join(work, "probe3.json"), "w"), indent=1, default=str)


def our_grads(md, h2):
    """Our graduations (start SOL side >= 10, inside the windows): mint -> graduation time (ms), as meta_fetch.py's plan."""
    import pandas as pd
    lo_hi = [(_ts(a) * 1000, _ts(b) * 1000) for _, a, b in WINDOWS]
    rows = pd.read_parquet(os.path.join(h2, "meta_h2.parquet"))[["mint", "t", "sol0"]].to_dict("records")
    for f in sorted(glob.glob(os.path.join(md, "meta_w*.json"))):
        rows += [{"mint": r["mint"], "t": r["t"], "sol0": r["sol0"]} for r in json.load(open(f))]
    return {r["mint"]: int(r["t"]) for r in rows if r["sol0"] >= 10 and any(a <= int(r["t"]) < b for a, b in lo_hi)}


def chain_launches(rpc, t0, t1, top, read_tx=False):
    """The chain's own list of pump.fun launches between t0 and t1 (unix s): successful signatures, and with read_tx the mints."""
    before, _ = sig_near(rpc, t1, top)
    sigs = []
    while before:
        page = rpc.call("getSignaturesForAddress", [MINT_AUTHORITY, {"limit": 1000, "before": before}])
        if not page:
            break
        sigs += [(x["signature"], x.get("blockTime")) for x in page if x.get("err") is None and x.get("blockTime")]
        before = page[-1]["signature"]
        if (page[-1].get("blockTime") or t1) < t0:
            break
    sigs = [s for s, bt in sigs if t0 <= bt < t1]
    mints = None
    if read_tx:
        pool = concurrent.futures.ThreadPoolExecutor(8)
        txs = list(pool.map(lambda x: rpc.call("getTransaction", [x, {"encoding": "json", "maxSupportedTransactionVersion": 1}]), sigs))
        pool.shutdown()
        mints = [p["mint"] for p in (parse_launch(t) for t in txs) if p]
    return sigs, mints


def cmd_verify(work, md, h2):
    import numpy as np, pandas as pd
    os.makedirs(work, exist_ok=True)
    k = os.environ.get("HK") or ""
    rpc = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12) if k else rpc_only(PUBLIC_RPC, 0.3)
    top = rpc.call("getSlot", [])
    grads = our_grads(md, h2)
    rng = np.random.default_rng(7)
    out = {"our_graduations": len(grads)}
    # ---- Slinky21's Pumpfun_v2: create events, 10 Aug onwards
    ds = DATASETS["v2"]
    files = hf_files(ds)
    cr = sorted(f for f, _ in files if "/create/" in f and f.endswith(".parquet"))
    def stamp(f):                      # create_20260928T152442.parquet -> that day
        d = f.rsplit("_", 1)[1][:8]
        return _ts("%s-%s-%s" % (d[:4], d[4:6], d[6:8]))

    lo, hi = _ts("2026-08-10"), _ts("2026-10-22")
    keep = [f for f in cr if lo - 86400 <= stamp(f) <= hi + 86400]
    o = out.setdefault("v2", {"create_files": len(cr), "files_used": len(keep), "first": keep[0] if keep else None,
                              "last": keep[-1] if keep else None})
    parts = []
    for f in keep:
        try:
            d = pd.read_parquet(hf_get(ds, f, os.path.join(work, "v2", os.path.basename(f))),
                                columns=["block_time", "signature", "mint", "creator", "tx_signer", "token_name", "symbol", "uri"])
            parts.append(d)
            os.remove(os.path.join(work, "v2", os.path.basename(f)))
        except Exception as e:
            o.setdefault("errors", []).append("%s %s" % (f, type(e).__name__))
    v2 = pd.concat(parts, ignore_index=True).drop_duplicates("signature")
    v2["bt"] = v2["block_time"].astype("int64") // 10**6
    v2 = v2[(v2["bt"] >= lo) & (v2["bt"] < hi)]
    days = pd.to_datetime(v2["bt"], unit="s", utc=True).dt.strftime("%Y-%m-%d").value_counts().sort_index()
    o["rows"], o["per_day"] = len(v2), days.to_dict()
    o["days_under_20000"] = [d for d, n in days.items() if n < 20000]
    v2.to_parquet(os.path.join(work, "v2_creates.parquet"), index=False)
    hours = sorted(rng.choice(np.arange(lo, hi - 2 * 86400, 3600), 3, replace=False).tolist())
    o["hours"] = []
    sset = set(v2["signature"])
    for h in hours:
        sigs, _ = chain_launches(rpc, h, h + 3600, top)
        ds_h = set(v2[(v2["bt"] >= h) & (v2["bt"] < h + 3600)]["signature"])
        o["hours"].append({"hour": time.strftime("%Y-%m-%d %H:00", time.gmtime(h)), "chain": len(sigs),
                           "chain_in_dataset": sum(x in sset for x in sigs), "dataset": len(ds_h),
                           "dataset_in_chain": len(ds_h & set(sigs))})
        log("v2 hour", o["hours"][-1])
    sub = v2.iloc[rng.choice(len(v2), 300, replace=False)]
    o["chain_check"] = chain_check(rpc, [{"mint": r["mint"], "name": r["token_name"], "symbol": r["symbol"], "uri": r["uri"],
                                          "creator": r["creator"]} for _, r in sub.iterrows()])
    m = set(v2["mint"])
    g = {x: t for x, t in grads.items() if lo * 1000 + 86400000 <= t < (hi - 86400) * 1000}
    o["our_graduations_in_days"], o["of_them_in_dataset"] = len(g), sum(x in m for x in g)
    log("v2", json.dumps({k2: v for k2, v in o.items() if k2 != "per_day"}))
    # ---- Slinky21's corpus: tokens of 5 Jun - 14 Jul
    ds = DATASETS["corpus"]
    t = pd.read_parquet(hf_get(ds, "tokens.parquet", os.path.join(work, "corpus", "tokens.parquet")),
                        columns=["mint", "detected_at", "name", "symbol", "uri", "creator", "graduated_at", "seconds_to_graduation",
                                 "initial_buy_sol", "is_mayhem_mode"])
    t["bt"] = t["detected_at"].astype("int64") // 10**6
    o = out.setdefault("corpus", {"rows": len(t), "from": str(t["detected_at"].min()), "to": str(t["detected_at"].max())})
    days = pd.to_datetime(t["bt"], unit="s", utc=True).dt.strftime("%Y-%m-%d").value_counts().sort_index()
    o["per_day"] = days.to_dict()
    t.to_parquet(os.path.join(work, "corpus_tokens.parquet"), index=False)
    a, b = _ts("2026-06-26"), _ts("2026-07-13")
    cand = [x for x in np.arange(a, b, 1800) if not (_ts("2026-07-03") - 3600 <= x < _ts("2026-07-04") + 3600)]
    o["halfhours"] = []
    mset = set(t["mint"])
    for h in sorted(rng.choice(cand, 2, replace=False).tolist()):
        sigs, mints = chain_launches(rpc, h, h + 1800, top, read_tx=True)
        o["halfhours"].append({"from": time.strftime("%Y-%m-%d %H:%M", time.gmtime(h)), "chain": len(sigs),
                               "chain_read": len(mints or []), "chain_in_dataset": sum(x in mset for x in (mints or []))})
        log("corpus half hour", o["halfhours"][-1])
    sub = t.iloc[rng.choice(len(t), 300, replace=False)]
    o["chain_check"] = chain_check(rpc, [{"mint": r["mint"], "name": r["name"], "symbol": r["symbol"], "uri": r["uri"],
                                          "creator": r["creator"]} for _, r in sub.iterrows()])
    lo2, hi2 = _ts("2026-06-25"), _ts("2026-07-14")
    g = {x: tt for x, tt in grads.items() if lo2 * 1000 + 86400000 <= tt < hi2 * 1000 and not
         (_ts("2026-07-03") * 1000 <= tt < _ts("2026-07-05") * 1000)}
    o["our_graduations_in_days"], o["of_them_in_dataset"] = len(g), sum(x in mset for x in g)
    gr = t[t["graduated_at"].notna()]
    o["dataset_graduated"], o["dataset_graduated_in_our_list"] = len(gr), int(gr["mint"].isin(set(grads)).sum())
    log("corpus", json.dumps({k2: v for k2, v in o.items() if k2 != "per_day"}))
    json.dump(out, open(os.path.join(work, "verify.json"), "w"), indent=1, default=str)


# ------------------------------------------------------------------------------------------------ verify2 (amendment 8)
LOOP_FILES = "data/launches/%s.parquet"
LOOP_COLS = ["mint", "creator", "t0", "name", "symbol", "uri", "mayhem", "quote_asset", "graduated", "migrate_dt_s",
             "curve_complete"]


def _days(a, b):
    return [time.strftime("%Y-%m-%d", time.gmtime(t)) for t in range(_ts(a), _ts(b) + 1, 86400)]


def read_loophole(work, days):
    import pandas as pd
    ds, have = DATASETS["loophole"], {f for f, _ in hf_files(DATASETS["loophole"])}
    parts, missing = [], []
    for day in days:
        f = LOOP_FILES % day
        if f not in have:
            missing.append(day)
            continue
        dest = hf_get(ds, f, os.path.join(work, "loop", day + ".parquet"))
        x = pd.read_parquet(dest)
        parts.append(x[[c for c in LOOP_COLS if c in x.columns]])
        os.remove(dest)
    d = pd.concat(parts, ignore_index=True).drop_duplicates("mint") if parts else pd.DataFrame(columns=LOOP_COLS)
    d["bt"] = pd.to_numeric(d["t0"], errors="coerce")
    return d, missing


def read_v2(work, lo, hi, cols):
    import pandas as pd
    ds = DATASETS["v2"]

    def stamp(f):
        x = f.rsplit("_", 1)[1][:8]
        return _ts("%s-%s-%s" % (x[:4], x[4:6], x[6:8]))
    parts = []
    for f, _ in hf_files(ds):
        if "/create/" in f and f.endswith(".parquet") and lo - 86400 <= stamp(f) <= hi + 86400:
            dest = hf_get(ds, f, os.path.join(work, "v2", os.path.basename(f)))
            parts.append(pd.read_parquet(dest, columns=cols))
            os.remove(dest)
    d = pd.concat(parts, ignore_index=True).drop_duplicates("signature")
    d["bt"] = _secs(d["block_time"])
    return d[(d["bt"] >= lo) & (d["bt"] < hi)]


def launch_tx_of(rpc, mint):
    """The launch transaction of a mint: the oldest signature of the mint account, when it has under 1,000 in all."""
    page = rpc.call("getSignaturesForAddress", [mint, {"limit": 1000}])
    if not page or len(page) >= 1000:
        return None
    return page[-1]["signature"]


def launch_check(rpc, rows):
    """Dataset rows (mint, name, symbol, uri, creator, and sig where the dataset has it) against their own launch transaction's
    CreateEvent, and the curve account's current creator next to it."""
    from meta_chain import parse_curve
    out = {"rows": len(rows), "tx_found": 0}
    for a in range(0, len(rows), 100):
        part = rows[a:a + 100]
        def cv(m):
            try:
                return curve_address(m)
            except Exception:
                return "11111111111111111111111111111111"
        acc = rpc.call("getMultipleAccounts", [[cv(r["mint"]) for r in part], {"encoding": "base64"}]) or {}
        curves = acc.get("value") or [None] * len(part)
        for r, c in zip(part, curves):
            sig = r.get("sig") or launch_tx_of(rpc, r["mint"])
            tx = rpc.call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1}]) if sig else None
            p = parse_launch(tx)
            if not p or p.get("mint") != r["mint"]:
                continue
            out["tx_found"] += 1
            cc = parse_curve(c["data"][0]).get("curve_creator") if c and c.get("data") else None
            for k, chain_v in (("name", p.get("name")), ("symbol", p.get("symbol")), ("uri", p.get("uri")),
                               ("creator", p.get("creator"))):
                if r.get(k) is None or chain_v is None:
                    continue
                o = out.setdefault(k + "_same", [0, 0])
                o[1] += 1
                o[0] += int(str(r[k]).strip() == str(chain_v).strip())
            if cc and p.get("creator"):
                o = out.setdefault("curve_creator_is_launch_creator", [0, 0])
                o[1] += 1
                o[0] += int(cc == p["creator"])
                if r.get("creator") and cc != p["creator"]:
                    o = out.setdefault("where_curve_differs_dataset_is_launch_creator", [0, 0])
                    o[1] += 1
                    o[0] += int(str(r["creator"]) == p["creator"])
    return out


def chain_back(rpc, spans):
    """The mint authority's successful signatures inside the given [a, b) spans, paged back from the newest one (no start point
    search: verify and verify2 found none in Sep and Oct). Returns {span start: [signatures]}."""
    out = {a: [] for a, _ in spans}
    lo = min(a for a, _ in spans)
    before, pages, t_last = None, 0, None
    while True:
        opt = {"limit": 1000}
        if before:
            opt["before"] = before
        page = rpc.call("getSignaturesForAddress", [MINT_AUTHORITY, opt])
        if not page:
            log("chain_back: empty page after", pages, "pages, last time", t_last)
            break
        pages += 1
        for x in page:
            bt = x.get("blockTime")
            if x.get("err") is None and bt:
                for a, b in spans:
                    if a <= bt < b:
                        out[a].append(x["signature"])
        before, t_last = page[-1]["signature"], page[-1].get("blockTime")
        if pages % 200 == 0:
            log("chain_back", pages, "pages, at", time.strftime("%Y-%m-%d %H:%M", time.gmtime(t_last or 0)))
        if t_last and t_last < lo:
            break
    return out


def chain_halfhour(rpc, h, top, ds_sig=None, ds_mint=None, ds_rows=None, sigs=None):
    """One half-hour of the chain's launches (successful transactions touching the mint authority, read and parsed) against a
    dataset: chain launches found in it, and its rows of [h+60, h+1740) found on the chain."""
    if sigs is None:
        sigs, _ = chain_launches(rpc, h, h + 1800, top)
    o = {"from": time.strftime("%Y-%m-%d %H:%M", time.gmtime(h)), "chain_sigs": len(sigs)}
    known = [x for x in sigs if ds_sig is not None and x in ds_sig]
    rest = [x for x in sigs if not (ds_sig is not None and x in ds_sig)]
    pool = concurrent.futures.ThreadPoolExecutor(8)
    txs = list(pool.map(lambda x: rpc.call("getTransaction", [x, {"encoding": "json", "maxSupportedTransactionVersion": 1}]), rest))
    pool.shutdown()
    parsed = [(x, parse_launch(t)) for x, t in zip(rest, txs)]
    o["read_failed"] = sum(1 for t in txs if t is None)
    o["not_a_launch"] = sum(1 for (x, p), t in zip(parsed, txs) if t is not None and not p)
    launches = [p["mint"] for x, p in parsed if p]
    if ds_sig is not None:
        o["chain_launches"] = len(known) + len(launches)
        o["chain_in_dataset"] = len(known) + sum(m in ds_mint for m in launches)
        inner = ds_rows[(ds_rows["bt"] >= h + 60) & (ds_rows["bt"] < h + 1740)]
        sset = set(sigs)
        o["dataset_rows"], o["dataset_rows_on_chain"] = len(inner), int(inner["signature"].isin(sset).sum())
    else:
        o["chain_launches"] = len(launches)
        o["chain_in_dataset"] = sum(m in ds_mint for m in launches)
        inner = ds_rows[(ds_rows["bt"] >= h + 60) & (ds_rows["bt"] < h + 1740)]
        o["dataset_rows"], o["dataset_rows_on_chain"] = len(inner), int(inner["mint"].isin(set(launches)).sum())
    log("half hour", o)
    return o


def _share(hs, a, b):
    x, n = sum(h[a] for h in hs), sum(h[b] for h in hs)
    return round(x / n, 4) if n else None


def cmd_verify2(work, md, h2):
    """Amendment 8: the checks of amendment 6 where verify could not make them (Pumpfun_v2's hours, the creator at launch, our
    graduations of the days it covers), and the same checks for loopholetape's launches (9-17 Oct)."""
    import numpy as np
    os.makedirs(work, exist_ok=True)
    k = os.environ.get("HK") or ""
    rpc = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12) if k else rpc_only(PUBLIC_RPC, 0.3)
    top = rpc.call("getSlot", [])
    grads = our_grads(md, h2)
    out = {"our_graduations": len(grads)}
    # ---- Pumpfun_v2: its own span is 10 Aug - 8 Oct 03:30 UTC (verify); launch days used 10 Aug - 6 Oct
    lo, hi = _ts("2026-08-10"), _ts("2026-10-07")
    v2 = read_v2(work, lo, hi, ["block_time", "signature", "mint", "creator", "token_name", "symbol", "uri", "is_mayhem_mode"])
    o = out.setdefault("v2", {"rows": len(v2), "mayhem_rows": int(v2["is_mayhem_mode"].fillna(False).astype(bool).sum())})
    rng = np.random.default_rng(7)
    hh = sorted(rng.choice(np.arange(lo, hi, 1800), 6, replace=False).tolist())
    sset, mset = set(v2["signature"]), set(v2["mint"])
    o["halfhours"] = [chain_halfhour(rpc, h, top, sset, mset, v2) for h in hh]
    o["chain_in_dataset_share"] = _share(o["halfhours"], "chain_in_dataset", "chain_launches")
    o["dataset_on_chain_share"] = _share(o["halfhours"], "dataset_rows_on_chain", "dataset_rows")
    sub = v2.iloc[rng.choice(len(v2), 300, replace=False)]
    o["row_check"] = launch_check(rpc, [{"mint": r["mint"], "sig": r["signature"], "name": r["token_name"], "symbol": r["symbol"],
                                         "uri": r["uri"], "creator": r["creator"]} for _, r in sub.iterrows()])
    g = {x for x, t in grads.items() if _ts("2026-08-11") * 1000 <= t < _ts("2026-10-07") * 1000}
    o["our_graduations_11aug_6oct"], o["of_them_in_dataset"] = len(g), len(g & mset)
    log("v2", json.dumps(o)[:3000])
    # ---- loopholetape's launches: 27 Sep - 17 Oct (its "launches" subset, after its decoder fix)
    lp, missing = read_loophole(work, _days("2026-09-27", "2026-10-17"))
    o = out.setdefault("loophole", {"rows": len(lp), "days_missing": missing,
                                    "mayhem_rows": int(pd_num(lp["mayhem"]).fillna(0).astype(bool).sum()),
                                    "quote": lp["quote_asset"].fillna("?").value_counts().head(6).to_dict()})
    a, b = _ts("2026-10-09"), _ts("2026-10-18")
    hh = sorted(rng.choice(np.arange(a, b, 1800), 4, replace=False).tolist())
    lset = set(lp["mint"])
    o["halfhours"] = [chain_halfhour(rpc, h, top, None, lset, lp) for h in hh]
    o["chain_in_dataset_share"] = _share(o["halfhours"], "chain_in_dataset", "chain_launches")
    o["dataset_on_chain_share"] = _share(o["halfhours"], "dataset_rows_on_chain", "dataset_rows")
    w5 = lp[(lp["bt"] >= a) & (lp["bt"] < b)]
    sub = w5.iloc[rng.choice(len(w5), 300, replace=False)]
    o["row_check"] = launch_check(rpc, [{"mint": r["mint"], "name": r["name"], "symbol": r["symbol"], "uri": r["uri"],
                                         "creator": r["creator"]} for _, r in sub.iterrows()])
    g = {x for x, t in grads.items() if _ts("2026-09-29") * 1000 <= t < _ts("2026-10-18") * 1000}
    o["our_graduations_29sep_17oct"], o["of_them_in_dataset"] = len(g), len(g & lset)
    # ---- the two recorders on the days both cover (27 Sep - 6 Oct): same launches, same fields
    a2, b2 = _ts("2026-09-27"), _ts("2026-10-07")
    va, la = v2[(v2["bt"] >= a2 + 3600) & (v2["bt"] < b2 - 3600)], lp[(lp["bt"] >= a2 + 3600) & (lp["bt"] < b2 - 3600)]
    j = va.merge(lp, on="mint", suffixes=("_v2", "_lp"))
    o["overlap"] = {"v2_rows": len(va), "v2_in_loophole": int(va["mint"].isin(lset).sum()), "loophole_rows": len(la),
                    "loophole_in_v2": int(la["mint"].isin(mset).sum()), "joined": len(j),
                    "creator_same": int((j["creator_v2"].astype(str) == j["creator_lp"].astype(str)).sum()),
                    "symbol_same": int((j["symbol_v2"].astype(str) == j["symbol_lp"].astype(str)).sum()),
                    "time_diff_s_p50_p99": [round(float(x), 2) for x in np.nanquantile((j["bt_lp"] - j["bt_v2"]).abs(), [0.5, 0.99])]
                    if len(j) else None}
    pv, pl = [(d["bt"] // 86400).astype(int).value_counts() for d in (v2, lp)]
    o["per_day_v2_vs_loophole"] = {time.strftime("%Y-%m-%d", time.gmtime(int(dd) * 86400)): [int(pv.get(dd, 0)), int(pl[dd])]
                                   for dd in sorted(pl.index)}
    log("loophole", json.dumps(o)[:3000])
    json.dump(out, open(os.path.join(work, "verify2.json"), "w"), indent=1, default=str)


def cmd_verify3(work, md, h2):
    """Amendment 9: rule 1 of amendment 6 for Pumpfun_v2, in the same 6 half-hours as verify2 (seed 7), with the chain's list
    read back from its newest signature."""
    import numpy as np
    os.makedirs(work, exist_ok=True)
    k = os.environ.get("HK") or ""
    rpc = rpc_only("https://mainnet.helius-rpc.com/?api-key=" + k, 0.12) if k else rpc_only(PUBLIC_RPC, 0.3)
    lo, hi = _ts("2026-08-10"), _ts("2026-10-07")
    rng = np.random.default_rng(7)
    hh = sorted(rng.choice(np.arange(lo, hi, 1800), 6, replace=False).tolist())
    log("half-hours", [time.strftime("%Y-%m-%d %H:%M", time.gmtime(h)) for h in hh])
    v2 = read_v2(work, min(hh) - 86400, max(hh) + 86400, ["block_time", "signature", "mint"])
    sigs = chain_back(rpc, [(h, h + 1800) for h in hh])
    sset, mset = set(v2["signature"]), set(v2["mint"])
    o = {"halfhours": [chain_halfhour(rpc, h, None, sset, mset, v2, sigs=sigs[h]) for h in hh]}
    o["chain_in_dataset_share"] = _share(o["halfhours"], "chain_in_dataset", "chain_launches")
    o["dataset_on_chain_share"] = _share(o["halfhours"], "dataset_rows_on_chain", "dataset_rows")
    log("v2", json.dumps(o)[:3000])
    json.dump({"v2": o}, open(os.path.join(work, "verify3.json"), "w"), indent=1, default=str)


def pd_num(x):
    import pandas as pd
    return pd.to_numeric(x, errors="coerce")


# ------------------------------------------------------------------------------------------------ universe L (amendment 6)
def _secs(x):
    """A timestamp column (datetime of any unit, or numbers in s / ms / us) -> unix seconds as float, NaN where missing."""
    import pandas as pd
    if pd.api.types.is_datetime64_any_dtype(x):
        return ((pd.to_datetime(x, utc=True) - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() // 1).astype(float)
    v = pd.to_numeric(x, errors="coerce").astype(float)
    m = v.max()
    return v / (1e6 if m > 1e14 else 1e3 if m > 1e11 else 1)


L_DAYS = {"w3": ("2026-08-10", "2026-09-07"), "w4": ("2026-09-10", "2026-10-06"), "w5": ("2026-10-09", "2026-10-17")}
# first and last launch day, both included (amendment 8: w2 left out, the corpus failed its check; w5 ends on loophole's last day)


def cmd_build(work, md, h2, out):
    """Universe L (amendments 6 and 8): every launch of the datasets that passed (SOURCES, default "v2,loophole"), one row per
    mint. Rows in a window's launch days that are not mayhem mode get w = w3..w5; all other rows get w = "" and only serve as
    history for the counting facts (creator, ticker, theme, crowding)."""
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    srcs = (os.environ.get("SOURCES") or "v2,loophole").split(",")
    grads = our_grads(md, h2)
    gser = pd.Series({m: t // 1000 for m, t in grads.items()}, dtype="int64")
    parts, gtimes = [], []
    if "v2" in srcs:
        ds = DATASETS["v2"]

        def day_of(f):
            d = f.rsplit("_", 1)[1][:8]
            return _ts("%s-%s-%s" % (d[:4], d[4:6], d[6:8]))
        cre, gra = [], []
        for f, _ in hf_files(ds):
            if not f.endswith(".parquet") or day_of(f) < _ts("2026-08-09"):
                continue
            if "/create/" in f:
                cols = ["block_time", "mint", "bonding_curve", "creator", "token_name", "symbol", "uri", "is_mayhem_mode"]
                cre.append(pd.read_parquet(hf_get(ds, f, os.path.join(work, "tmp.parquet")), columns=cols))
            elif "/graduate/" in f:
                gra.append(pd.read_parquet(hf_get(ds, f, os.path.join(work, "tmp.parquet")), columns=["block_time", "mint"]))
        c = pd.concat(cre, ignore_index=True).drop_duplicates("mint")
        g = pd.concat(gra, ignore_index=True)
        gtimes.append(pd.DataFrame({"mint": g["mint"], "gt": _secs(g["block_time"])}))
        parts.append(pd.DataFrame({"mint": c["mint"], "curve": c["bonding_curve"], "creator": c["creator"], "name": c["token_name"],
                                   "symbol": c["symbol"], "uri": c["uri"], "mayhem": c["is_mayhem_mode"].astype(float),
                                   "t": _secs(c["block_time"]), "src": "v2", "unresolved": False}))
        log("v2 creates", len(c), "graduate events", len(g), "files", len(cre), len(gra))
    if "loophole" in srcs:
        lp, missing = read_loophole(work, _days("2026-09-27", "2026-10-17"))
        gr = pd_num(lp["graduated"])
        cc = pd_num(lp["curve_complete"])
        nonsol = lp["quote_asset"].fillna("").astype(str).str.lower().ne("sol") & lp["quote_asset"].notna()
        done = (gr == 1) | (nonsol & (cc == 1))
        unres = gr.isna() & cc.isna()
        gtimes.append(pd.DataFrame({"mint": lp["mint"][done], "gt": (lp["bt"] + pd_num(lp["migrate_dt_s"]))[done]}))
        gtimes.append(pd.DataFrame({"mint": lp["mint"][done], "gt": float("inf")}))       # graduated, time maybe unknown
        parts.append(pd.DataFrame({"mint": lp["mint"], "curve": None, "creator": lp["creator"], "name": lp["name"],
                                   "symbol": lp["symbol"], "uri": lp["uri"], "mayhem": pd_num(lp["mayhem"]).astype(float),
                                   "t": lp["bt"], "src": "loophole", "unresolved": unres.to_numpy()}))
        log("loophole launches", len(lp), "graduated", int(done.sum()), "unresolved", int(unres.sum()), "days missing", missing)
    allx = pd.concat(parts, ignore_index=True)
    allx = allx[allx["t"].notna() & allx["mint"].notna()]
    unres = set(allx.loc[allx["unresolved"], "mint"]) - set(allx.loc[~allx["unresolved"], "mint"])
    allx = allx.drop_duplicates("mint").drop(columns=["unresolved"])        # v2's row first where both have the mint
    allx["t"] = allx["t"].astype("int64")
    gt = pd.concat(gtimes, ignore_index=True) if gtimes else pd.DataFrame(columns=["mint", "gt"])
    known = gt[gt["gt"] < float("inf")].groupby("mint")["gt"].min()
    anyg = set(gt["mint"])
    allx["grad_t_ds"] = allx["mint"].map(known)
    allx["grad_t_ours"] = allx["mint"].map(gser).astype(float)
    allx["grad_t"] = allx[["grad_t_ds", "grad_t_ours"]].min(axis=1)
    g_any = allx["mint"].isin(anyg) | allx["grad_t_ours"].notna()
    allx["graduated"] = g_any.astype(float).where(g_any | ~allx["mint"].isin(unres))
    allx["w"] = ""
    summary = {"sources": srcs, "rows_all": len(allx), "mayhem_all": int((allx["mayhem"] == 1).sum())}
    for w, (a, b) in L_DAYS.items():
        t0, t1 = _ts(a), _ts(b) + 86400
        inday = (allx["t"] >= t0) & (allx["t"] < t1)
        m = inday & (allx["mayhem"] != 1)
        allx.loc[m, "w"] = w
        d = allx[m]
        gm = {x for x, t in grads.items() if t0 * 1000 + 86400000 <= t < t1 * 1000}
        summary[w] = {"launches_in_days": int(inday.sum()), "mayhem_left_out": int((inday & (allx["mayhem"] == 1)).sum()),
                      "test_rows": int(m.sum()), "by_source": d["src"].value_counts().to_dict(),
                      "graduated": int((d["graduated"] == 1).sum()), "unresolved": int(d["graduated"].isna().sum()),
                      "graduated_10min_plus": int(((d["grad_t"] - d["t"]) >= 600).sum()),
                      "graduated_time_unknown": int(((d["graduated"] == 1) & d["grad_t"].isna()).sum()),
                      "graduated_in_dataset": int(d["grad_t_ds"].notna().sum()),
                      "graduated_in_our_list": int(d["grad_t_ours"].notna().sum()),
                      "our_graduations_of_these_days": len(gm), "of_them_in_L": len(gm & set(allx.loc[inday, "mint"]))}
        log(w, summary[w])
    summary["history_rows"] = int((allx["w"] == "").sum())
    allx = allx.sort_values("t").reset_index(drop=True)
    k = max(1, -(-len(allx) // 400_000))
    for j in range(k):
        allx.iloc[j * len(allx) // k:(j + 1) * len(allx) // k].to_parquet(os.path.join(out, "L_%02d.parquet" % j), index=False,
                                                                          compression="zstd")
    summary["files"] = k
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)


def load_universe(udir):
    import pandas as pd
    return pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(udir, "L_*.parquet")))], ignore_index=True)


def meta_sample(udir):
    """The random 600,000 (seed 7) of universe L's window rows, drawn from the list sorted by mint."""
    import numpy as np
    d = load_universe(udir)
    d = d[d["w"] != ""].sort_values("mint").reset_index(drop=True)
    n = int(os.environ.get("MSAMPLE") or 600_000)
    take = np.sort(np.random.default_rng(7).permutation(len(d))[:min(n, len(d))])
    return d.iloc[take].reset_index(drop=True)


def cmd_mshard(udir, i, n, out):
    d = meta_sample(udir)
    skip = set(json.load(open(os.environ["DONE"]))) if os.environ.get("DONE") and os.path.exists(os.environ["DONE"]) else set()
    part = d.iloc[int(i)::int(n)]
    part = part[~part["mint"].isin(skip)].reset_index(drop=True)
    log("universe sample", len(d), "this shard", len(part), "already done", len(skip))
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 300))
    rpc = Spread()
    fpool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("FILE_WORKERS") or 16))
    res, files = {}, {}
    for a in range(0, len(part), 100):
        if time.time() > stop:
            log("time budget used at", a, "of", len(part))
            break
        chunk = part.iloc[a:a + 100]
        curves = [c if isinstance(c, str) and c else curve_address(m) for m, c in zip(chunk["mint"], chunk["curve"])]
        acc = rpc.call("getMultipleAccounts", [curves, {"encoding": "base64"}])
        vals = (acc or {}).get("value") if isinstance(acc, dict) else None
        got = list(fpool.map(metadata_file, chunk["uri"].fillna("").astype(str)))
        for k, (m, (j, st)) in enumerate(zip(chunk["mint"], got)):
            r = {"mint": m, "file_status": st}
            v = vals[k] if vals else None
            if v and v.get("data"):
                try:
                    b = base64.b64decode(v["data"][0])
                    r["complete"] = bool(b[48]) if len(b) > 48 else None
                except Exception:
                    pass
            elif vals is not None:
                r["curve_gone"] = True
            files[st] = files.get(st, 0) + 1
            if isinstance(j, dict):
                r.update({"f_twitter": j.get("twitter"), "f_telegram": j.get("telegram"), "f_website": j.get("website"),
                          "f_name": j.get("name"), "f_symbol": j.get("symbol"), "f_createdOn": j.get("createdOn"),
                          "f_desc_len": len(str(j.get("description") or "")),
                          "f_image": str(j.get("image") or "")[:200],
                          "f_video": str(j.get("video") or j.get("animation_url") or j.get("video_uri") or "")[:200]})
            res[m] = r
        if a % 2000 == 0 or a + 100 >= len(part):
            log(a + len(chunk), "of", len(part), "files", files, "complete", sum(1 for r in res.values() if r.get("complete")),
                "rpc", rpc.codes)
            tmp = out + ".tmp"
            with gzip.open(tmp, "wt") as fh:
                json.dump({"rows": res, "done": a + len(chunk), "planned": len(part)}, fh)
            os.replace(tmp, out)
    fpool.shutdown()
    with gzip.open(out, "wt") as fh:
        json.dump({"rows": res, "planned": len(part)}, fh)


def cmd_mfinal(src, out, prev=None):
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(src, "**", "lmeta_*.json.gz"), recursive=True)):
        rows += list(json.load(gzip.open(f, "rt"))["rows"].values())
    d = pd.DataFrame(rows).drop_duplicates("mint")
    if prev and os.path.exists(prev):
        old = pd.read_parquet(prev)
        d = pd.concat([d, old[~old["mint"].isin(set(d["mint"]))]], ignore_index=True)
    for c in d.columns:
        if d[c].dtype != object or c == "mint":
            continue
        v = d[c].dropna()
        if len(v) and v.map(lambda x: isinstance(x, bool)).all():
            d[c] = d[c].astype("boolean")
        else:
            d[c] = d[c].map(lambda x: None if x is None or (isinstance(x, float) and x != x) else (x if isinstance(x, str) else json.dumps(x)))
    d.to_parquet(os.path.join(out, "lmeta.parquet"), index=False, compression="zstd")
    log("rows", len(d), "files", d["file_status"].value_counts().to_dict(), "complete", int(d.get("complete", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()))


# ------------------------------------------------------------------------------------------------ the fetch
WINDOWS = (("w1", "2026-04-25", "2026-05-25"), ("w2", "2026-06-25", "2026-07-25"), ("w3", "2026-08-10", "2026-09-10"),
           ("w4", "2026-09-10", "2026-10-09"), ("w5", "2026-10-09", "2026-10-22"))      # as research/rockets/build_paths.py
TAIL_DAYS = 2              # launches of a window's last 2 days are left out: a coin needs time to graduate


def _ts(day):
    import datetime as dt
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


class Spread:
    """Helius (when the key answers) and the public RPC taken in turn, so both carry the load; a failed call tries the other."""

    def __init__(self):
        k = os.environ.get("HK") or ""
        self.urls = []
        if k:
            u = "https://mainnet.helius-rpc.com/?api-key=" + k
            if rpc_only(u, 0.1).call("getSlot", []) is not None:
                self.urls.append((u, float(os.environ.get("HGAP") or 0.1)))
        self.urls.append((PUBLIC_RPC, float(os.environ.get("PGAP") or 0.26)))
        self.rpcs = [rpc_only(u, g) for u, g in self.urls]
        self._k = itertools.count()
        log("rpc", ["helius" if "helius" in u else "public" for u, _ in self.urls])

    def call(self, method, params):
        k = next(self._k)
        for j in range(len(self.rpcs)):
            r = self.rpcs[(k + j) % len(self.rpcs)]
            v = r.call(method, params)
            if v is not None:
                return v
        return None

    @property
    def codes(self):
        out = {}
        for (u, _), r in zip(self.urls, self.rpcs):
            for c, n in r.codes.items():
                out[c] = out.get(c, 0) + n
        return out


def cmd_sigs(out_dir):
    """All signatures of the mint authority for each window, newest first, from the window's end back to its start."""
    import pandas as pd
    os.makedirs(out_dir, exist_ok=True)
    rpc = Spread()
    top = rpc.call("getSlot", [])

    def one_window(w, a, b):
        t0, t1 = _ts(a), _ts(b)
        before, _ = sig_near(rpc, t1, top)
        rows, pages, miss = [], 0, 0
        while before:
            page = rpc.call("getSignaturesForAddress", [MINT_AUTHORITY, {"limit": 1000, "before": before}])
            if page is None:
                miss += 1
                if miss > 8:
                    log(w, "gave up after", pages, "pages")
                    break
                time.sleep(5 * miss)
                continue
            miss = 0
            if not page:
                break
            pages += 1
            rows += [(x["signature"], x.get("slot"), x.get("blockTime"), x.get("err") is not None) for x in page]
            before = page[-1]["signature"]
            last = page[-1].get("blockTime") or t1
            if pages % 200 == 0:
                log(w, pages, "pages", len(rows), "signatures, back to", time.strftime("%Y-%m-%d %H:%M", time.gmtime(last)))
            if last < t0:
                break
        d = pd.DataFrame(rows, columns=["sig", "slot", "bt", "failed"]).drop_duplicates("sig")
        d = d[(d["bt"] >= t0) & (d["bt"] < t1)]
        d.to_parquet(os.path.join(out_dir, "sigs_%s.parquet" % w), index=False)
        log(w, "signatures", len(d), "failed", int(d["failed"].sum()), "per day", round(len(d) / ((t1 - t0) / 86400)))
        return w, len(d)

    with concurrent.futures.ThreadPoolExecutor(len(WINDOWS)) as ex:
        log("done", list(ex.map(lambda x: one_window(*x), WINDOWS)), rpc.codes)


def sample_sigs(sig_dir):
    """The random sample: SAMPLE launches (default all) drawn with seed 7 from the windows' successful launch transactions."""
    import numpy as np, pandas as pd
    parts = []
    for w, a, b in WINDOWS:
        f = os.path.join(sig_dir, "sigs_%s.parquet" % w)
        if os.path.exists(f):
            d = pd.read_parquet(f)
            d = d[~d["failed"] & (d["bt"] < _ts(b) - TAIL_DAYS * 86400)]
            parts.append(d.assign(w=w))
    d = pd.concat(parts, ignore_index=True).sort_values("sig").reset_index(drop=True)
    n = int(os.environ.get("SAMPLE") or len(d))
    rng = np.random.default_rng(7)
    take = rng.permutation(len(d))[:min(n, len(d))]
    return d.iloc[np.sort(take)].reset_index(drop=True), len(d)


def cmd_shard(sig_dir, i, n, out):
    d, total = sample_sigs(sig_dir)
    skip = set(json.load(open(os.environ["DONE"]))) if os.environ.get("DONE") and os.path.exists(os.environ["DONE"]) else set()
    part = d.iloc[int(i)::int(n)]
    part = part[~part["sig"].isin(skip)].reset_index(drop=True)
    log("launches in the windows", total, "sample", len(d), "this shard", len(part), "already done", len(skip))
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 300))
    rpc = Spread()
    pool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("WORKERS") or 12))
    fpool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("FILE_WORKERS") or 16))
    res, files, bad = {}, {}, 0
    opts = {"encoding": "json", "maxSupportedTransactionVersion": 1}      # since autumn 2026 many launches are version-1 transactions
    for a in range(0, len(part), 100):
        if time.time() > stop:
            log("time budget used at", a, "of", len(part))
            break
        chunk = part.iloc[a:a + 100]
        txs = list(pool.map(lambda s: rpc.call("getTransaction", [s, opts]), chunk["sig"]))
        recs = []
        for (_, r), tx in zip(chunk.iterrows(), txs):
            p = parse_launch(tx) if tx else None
            if p is None:
                bad += 1
                res[r["sig"]] = {"sig": r["sig"], "w": r["w"], "bt": int(r["bt"]), "ok": False, "got_tx": tx is not None}
                continue
            p.update({"sig": r["sig"], "w": r["w"], "bt": int(r["bt"]), "ok": True})
            recs.append(p)
        curves = [p["curve"] for p in recs]
        acc = rpc.call("getMultipleAccounts", [curves, {"encoding": "base64"}]) if curves else None
        vals = (acc or {}).get("value") if isinstance(acc, dict) else None
        for p, v in zip(recs, vals or [None] * len(recs)):
            if v and v.get("data"):
                try:
                    b = base64.b64decode(v["data"][0])
                    p["complete"] = bool(b[48]) if len(b) > 48 else None
                    p["real_sol"] = int.from_bytes(b[32:40], "little") / 1e9 if len(b) >= 40 else None
                except Exception:
                    pass
            elif vals is not None:
                p["curve_gone"] = True
        got = list(fpool.map(lambda p: metadata_file(p.get("uri")), recs))
        for p, (j, st) in zip(recs, got):
            files[st] = files.get(st, 0) + 1
            if isinstance(j, dict):
                p.update({"f_twitter": j.get("twitter"), "f_telegram": j.get("telegram"), "f_website": j.get("website"),
                          "f_name": j.get("name"), "f_symbol": j.get("symbol"), "f_createdOn": j.get("createdOn"),
                          "f_desc_len": len(str(j.get("description") or "")),
                          "f_image": str(j.get("image") or "")[:200],
                          "f_video": str(j.get("video") or j.get("animation_url") or j.get("video_uri") or "")[:200]})
            p["file_status"] = st
            res[p["sig"]] = p
        if a % 1000 == 0 or a + 100 >= len(part):
            log(a + len(chunk), "of", len(part), "launches", sum(1 for r in res.values() if r.get("ok")), "no launch", bad,
                "graduated", sum(1 for r in res.values() if r.get("complete")), "files", files, "rpc", rpc.codes)
            tmp = out + ".tmp"
            with gzip.open(tmp, "wt") as fh:
                json.dump({"launches": res, "done": a + len(chunk), "planned": len(part), "total": total}, fh)
            os.replace(tmp, out)
    pool.shutdown()
    fpool.shutdown()
    with gzip.open(out, "wt") as fh:
        json.dump({"launches": res, "planned": len(part), "total": total}, fh)


def cmd_final(src, out, prev=None):
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    rows, totals = [], set()
    for f in sorted(glob.glob(os.path.join(src, "**", "launch_*.json.gz"), recursive=True)):
        j = json.load(gzip.open(f, "rt"))
        rows += list(j["launches"].values())
        totals.add(j.get("total"))
    d = pd.DataFrame(rows).drop_duplicates("sig")
    if prev and os.path.exists(prev):
        old = pd.read_parquet(prev)
        d = pd.concat([d, old[~old["sig"].isin(set(d["sig"]))]], ignore_index=True)
    for c in d.columns:
        if d[c].dtype != object or c in ("sig", "w"):
            continue
        v = d[c].dropna()
        if len(v) and v.map(lambda x: isinstance(x, bool)).all():
            d[c] = d[c].astype("boolean")
        elif len(v) and v.map(lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)).all():
            d[c] = pd.to_numeric(d[c], errors="coerce")
        else:
            d[c] = d[c].map(lambda x: None if x is None or (isinstance(x, float) and x != x) else (x if isinstance(x, str) else json.dumps(x)))
    d.to_parquet(os.path.join(out, "launches.parquet"), index=False)
    log("rows", len(d), "launches", int(d["ok"].fillna(False).astype(bool).sum()), "graduated", int(d.get("complete", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "launches in the windows", sorted(x for x in totals if x))


if __name__ == "__main__":
    {"probe": cmd_probe, "probe2": cmd_probe2, "probe3": cmd_probe3, "verify": cmd_verify, "verify2": cmd_verify2, "verify3": cmd_verify3,
     "build": cmd_build,
     "mshard": cmd_mshard, "mfinal": cmd_mfinal, "sigs": cmd_sigs, "shard": cmd_shard, "final": cmd_final}[sys.argv[1]](*sys.argv[2:])
