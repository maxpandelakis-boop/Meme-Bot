"""Probe 2 for the filter study (read-only, no key): the exact fields of RugCheck's full report that the Scout's new checks need
(creatorTokens, topHolders, knownAccounts), for pump.fun coins a few minutes old. usage: python3 research/filters/probe2.py"""
import json, time, urllib.request
UA = {"User-Agent": "memebot-research", "Accept": "application/json"}
def get(url):
    try:
        t0 = time.time()
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            j = json.loads(r.read().decode())
        print("  ok %.2f s %s" % (time.time() - t0, url[:90]), flush=True)
        return j
    except Exception as e:
        print("  get failed", url[:110], type(e).__name__, str(e)[:120], flush=True)
        return None
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
c = []
for page in (1, 2):
    for d in (get(GT + "/new_pools?page=%d" % page) or {}).get("data") or []:
        a = d.get("attributes") or {}
        if ((d.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id") != "pump-fun":
            continue
        mint = str(d["relationships"]["base_token"]["data"]["id"]).replace("solana_", "")
        c.append((((a.get("transactions") or {}).get("m5") or {}).get("buyers") or 0, mint, a.get("pool_created_at"), a.get("name")))
    time.sleep(2)
c.sort(reverse=True)
for buyers, mint, created, name in c[:5]:
    print("\n---- coin", name, mint, "created", created, "buyers5", buyers, "now", time.strftime("%H:%M:%SZ", time.gmtime()), flush=True)
    j = get("https://api.rugcheck.xyz/v1/tokens/%s/report" % mint) or {}
    print("creator", j.get("creator"), "creatorBalance", j.get("creatorBalance"), "supply", (j.get("token") or {}).get("supply"), "totalHolders", j.get("totalHolders"), "detectedAt", j.get("detectedAt"))
    ct = j.get("creatorTokens") or []
    print("creatorTokens", len(ct), json.dumps(ct[:4]))
    print("  createdAt range", min((x.get("createdAt") or "" for x in ct), default=None), max((x.get("createdAt") or "" for x in ct), default=None))
    print("topHolders", json.dumps((j.get("topHolders") or [])[:4]))
    print("knownAccounts", json.dumps(j.get("knownAccounts")))
    print("risks", json.dumps(j.get("risks")))
    print("markets[0] keys", list(((j.get("markets") or [{}])[0]).keys()))
    i = (get(GT + "/tokens/%s/info" % mint) or {}).get("data", {}).get("attributes", {})
    print("GT developer", i.get("developer_address"), i.get("developer_holding_percentage"), "launchpad", json.dumps(i.get("launchpad_details")))
    time.sleep(3)
