"""Probe for the filter study (fake money only, read-only calls, no key): (1) the schema of the dataset's swap table, (2) what the
free live sources return for a coin that is a few minutes old, so that a filter found on past data can also be computed live.
usage: python3 research/filters/probe.py <files.json> <out dir>"""
import json, os, sys, time, urllib.parse, urllib.request
UA = {"User-Agent": "memebot-research", "Accept": "application/json"}
out = sys.argv[2]; os.makedirs(out, exist_ok=True)
log = open(os.path.join(out, "probe.txt"), "w")
def p(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            p("  get failed", url[:120], type(e).__name__, str(e)[:120]); time.sleep(4 * (i + 1))
    return None
def shape(x, depth=0, maxd=3):
    """Keys and types, values cut short."""
    if isinstance(x, dict):
        if depth >= maxd: return "{%d keys}" % len(x)
        return {k: shape(v, depth + 1, maxd) for k, v in list(x.items())[:60]}
    if isinstance(x, list):
        return ["len %d" % len(x)] + ([shape(x[0], depth + 1, maxd)] if x else [])
    s = str(x)
    return s if len(s) <= 60 else s[:57] + "..."

# ---- 1. the swap table
try:
    import fsspec, pyarrow.parquet as pq
    files = [tuple(x) for x in json.load(open(sys.argv[1]))]
    for tab in ("swap", "graduate"):
        f = sorted(x for x, _ in files if "/%s/" % tab in x)[-3]
        url = "https://huggingface.co/datasets/Slinky21/Pumpfun_v2_dataset/resolve/main/" + urllib.parse.quote(f)
        with fsspec.open(url, "rb").open() as fh:
            pf = pq.ParquetFile(fh)
            p("==", tab, f, "rows", pf.metadata.num_rows, "row groups", pf.metadata.num_row_groups)
            p(pf.schema_arrow)
            import pandas as pd
            pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)
            p(pf.read_row_group(0).slice(0, 4).to_pandas().T.to_string())
except Exception as e:
    p("swap probe failed", type(e).__name__, str(e)[:300])

# ---- 2. live sources for fresh coins
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
np_ = get(GT + "/new_pools?page=1") or {}
cands = []
for d in np_.get("data") or []:
    a = d.get("attributes") or {}
    mint = str(((d.get("relationships") or {}).get("base_token") or {}).get("data", {}).get("id", "")).replace("solana_", "")
    dex = ((d.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id", "")
    buyers = ((a.get("transactions") or {}).get("m5") or {}).get("buyers") or 0
    cands.append((buyers, mint, a.get("address"), dex, a.get("pool_created_at"), a.get("name")))
cands.sort(reverse=True)
p("\n== new pools", len(cands), "dex mix", {x: sum(1 for c in cands if c[3] == x) for x in set(c[3] for c in cands)})
for buyers, mint, pool, dex, created, name in cands[:3]:
    p("\n---- coin", name, mint, "pool", pool, dex, "created", created, "buyers5", buyers)
    j = get(GT + "/pools/%s/trades" % pool)
    tr = (j or {}).get("data") or []
    p("GT trades:", len(tr), json.dumps(shape(tr[0]) if tr else None))
    if tr:
        ts = sorted(x["attributes"].get("block_timestamp") for x in tr)
        p("  span", ts[0], "to", ts[-1], "wallets", len(set(x["attributes"].get("tx_from_address") for x in tr)))
    time.sleep(2)
    p("GT token info:", json.dumps(shape((get(GT + "/tokens/%s/info" % mint) or {}).get("data"))))
    time.sleep(2)
    j = get("https://api.rugcheck.xyz/v1/tokens/%s/report" % mint)
    p("RugCheck report:", json.dumps(shape(j, maxd=2))[:6000])
    j = get("https://api.rugcheck.xyz/v1/tokens/%s/report/summary" % mint)
    p("RugCheck summary:", json.dumps(j)[:1500])
    j = get("https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=%s" % mint)
    p("GoPlus:", json.dumps(shape(j, maxd=4))[:5000])
    for name_, url in [("pump coin", "https://frontend-api-v3.pump.fun/coins/%s" % mint),
                       ("pump trades", "https://frontend-api-v3.pump.fun/trades/all/%s?limit=50&offset=0&minimumSize=0" % mint),
                       ("pump swap-api trades", "https://swap-api.pump.fun/v2/coins/%s/trades?limit=50" % mint),
                       ("DexScreener", "https://api.dexscreener.com/latest/dex/tokens/%s" % mint)]:
        j = get(url, tries=1)
        p(name_ + ":", json.dumps(shape(j, maxd=3))[:3000])
        if name_ == "pump coin" and isinstance(j, dict) and j.get("creator"):
            cr = j["creator"]
            jj = get("https://frontend-api-v3.pump.fun/coins/user-created-coins/%s?offset=0&limit=50&includeNsfw=true" % cr, tries=1)
            p("pump creator coins:", json.dumps(shape(jj, maxd=2))[:1500])
    # the public RPC: signatures of the mint (how many, how fast)
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [mint, {"limit": 1000}]}).encode()
        t0 = time.time()
        with urllib.request.urlopen(urllib.request.Request("https://solana-rpc.publicnode.com", data=body, headers={**UA, "Content-Type": "application/json"}), timeout=60) as r:
            res = json.loads(r.read().decode()).get("result") or []
        p("RPC signatures of the mint:", len(res), "in", round(time.time() - t0, 2), "s")
    except Exception as e:
        p("RPC failed", type(e).__name__, str(e)[:200])
    time.sleep(2)
