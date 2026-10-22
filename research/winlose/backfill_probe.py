"""Backfill probe for 8-22 Oct (fake money only): how many pump.fun graduations Helius can list, what a parsed migration looks
like (mint, pool), whether GeckoTerminal still gives the minute bars of an old pool, and whether Helius can read a pool's swaps of a
past hour. Prints counts, field names and public coin addresses only; the key (env HK) is never printed."""
import collections, datetime as dt, json, os, time, urllib.error, urllib.request

K = os.environ.get("HK") or ""
RPC = "https://mainnet.helius-rpc.com/?api-key=" + K
API = "https://api.helius.xyz/v0"
MIG = os.environ.get("MIG") or "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
WSOL = "So11111111111111111111111111111111111111112"
T0 = int(dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc).timestamp())
calls = collections.Counter()


def get(url, data=None, tries=3):
    for i in range(tries):
        req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "memebot-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 3 * i); continue
            return e.code, None
        except Exception as e:
            time.sleep(1); err = type(e).__name__
    return -1, None


def rpc(method, params):
    calls[method] += 1
    st, j = get(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return st, (j or {}).get("result") if isinstance(j, dict) else None, (j or {}).get("error") if isinstance(j, dict) else None


print("secret present:", bool(K))
sigs, before, pages = [], None, 0
while pages < 400:
    p = {"limit": 1000}
    if before:
        p["before"] = before
    st, res, err = rpc("getSignaturesForAddress", [MIG, p])
    pages += 1
    if not res:
        print("sigs stop", st, err); break
    sigs += [s for s in res if not s.get("err")]
    before = res[-1]["signature"]
    if (res[-1].get("blockTime") or 0) < T0:
        break
sigs = [s for s in sigs if (s.get("blockTime") or 0) >= T0]
day = collections.Counter(dt.datetime.utcfromtimestamp(s["blockTime"]).strftime("%m-%d") for s in sigs)
print("migration account sigs since 8 Oct:", len(sigs), "pages", pages)
print("per day", dict(sorted(day.items())))
# parse a sample from ~10 Oct
old = [s["signature"] for s in sigs if s["blockTime"] < T0 + 3 * 86400][:100]
calls["parse"] += 1
st, txs = get(API + "/transactions?api-key=" + K, {"transactions": old})
print("parse status", st, "n", len(txs) if isinstance(txs, list) else txs)
types = collections.Counter((t.get("type"), t.get("source")) for t in txs or [])
print("types", types.most_common(8))
pools = []
for t in txs or []:
    mints = {x.get("mint") for x in t.get("tokenTransfers") or []} - {WSOL, None}
    accs = [a.get("account") for a in t.get("accountData") or []]
    if len(mints) == 1 and t.get("source") in ("PUMP_AMM", "PUMP_FUN") or t.get("type") in ("CREATE_POOL", "MIGRATE"):
        pools.append((list(mints)[:1], t.get("type"), t.get("source"), t.get("timestamp")))
print("migrations parsed", len(pools), "sample", pools[:3])
if txs:
    t = txs[0]
    print("first tx type", t.get("type"), "source", t.get("source"), "desc", (t.get("description") or "")[:160])
    print("instr programs", [i.get("programId") for i in t.get("instructions") or []][:8])
# GeckoTerminal: the pool of a parsed mint, then old minute bars
mint = next((p[0][0] for p in pools if p[0]), None)
if mint:
    st, j = get("https://api.geckoterminal.com/api/v2/networks/solana/tokens/%s/pools?page=1" % mint)
    pl = [d["attributes"]["address"] for d in (j or {}).get("data") or []]
    print("gt token pools status", st, "n", len(pl))
    if pl:
        ts = (pools[0][3] or T0) + 25 * 3600
        st, j = get("https://api.geckoterminal.com/api/v2/networks/solana/pools/%s/ohlcv/minute?aggregate=1&limit=1000&before_timestamp=%d&currency=usd&token=base" % (pl[0], ts))
        ol = ((j or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
        print("gt old minute bars status", st, "n", len(ol), "first..last age min", ((ol[-1][0] - pools[0][3]) // 60, (ol[0][0] - pools[0][3]) // 60) if ol and pools[0][3] else None)
        # Helius: the pool's swaps of one past hour (signatures paged back, then parsed)
        target = (pools[0][3] or T0) + 3 * 3600
        before, n, pg, hour = None, 0, 0, []
        while pg < 60:
            p = {"limit": 1000}
            if before:
                p["before"] = before
            st, res, err = rpc("getSignaturesForAddress", [pl[0], p]); pg += 1
            if not res:
                break
            hour += [s["signature"] for s in res if target - 3600 <= (s.get("blockTime") or 0) < target and not s.get("err")]
            before = res[-1]["signature"]
            if (res[-1].get("blockTime") or 0) < target - 3600:
                break
        print("pool sig pages back to the hour", pg, "sigs in that hour", len(hour))
        if hour:
            calls["parse"] += 1
            st, tx2 = get(API + "/transactions?api-key=" + K, {"transactions": hour[:100]})
            sw = [t for t in tx2 or [] if t.get("type") == "SWAP" or t.get("source") == "PUMP_AMM"]
            print("parsed that hour", st, len(tx2 or []), "swaps", len(sw), "feePayer", bool(sw and sw[0].get("feePayer")))
st, res, err = rpc("getTransactionsForAddress", [MIG, {"limit": 1, "filters": {"blockTime": {"gte": T0}}}])
print("getTransactionsForAddress", st, "ok" if res else ("err %s" % (err or {}).get("code") if err else "none"))
print("calls", dict(calls))
