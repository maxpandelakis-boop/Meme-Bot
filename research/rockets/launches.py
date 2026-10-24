"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md, amendment 6): every pump.fun launch of the five
month windows from the Solana chain, not only the ~72,000 that graduated, for the user's ask to compare as many coins as possible.

  probe <out.json>        what the free sources give (public Solana RPC, Helius when HK is set, HuggingFace, pump.fun's lists)

Each launch is a transaction that touches pump.fun's mint authority (one fixed address that only signs new coins). Its CreateEvent
log holds the name, ticker, metadata link, mint, creator and time; the TradeEvent logs of the same transaction hold the creator's
own first buy. Nothing is bought. HK (the Helius key) is only passed to the script, never printed or saved."""
import base64, concurrent.futures, hashlib, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta_chain import PUMP, PUBLIC_RPC, Rpc, b58e, curve_address, http, log, pda  # noqa: E402

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
        b = rpc.call("getBlock", [s + k, {"transactionDetails": "signatures", "maxSupportedTransactionVersion": 0, "rewards": False}])
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


if __name__ == "__main__":
    {"probe": cmd_probe}[sys.argv[1]](*sys.argv[2:])
