"""Probe for the live paper run of the round 3 lead (fake money only, read-only): can the PumpSwap buys be recorded for free?
1. Is the Pumpfun_v2 data set still growing (newest files, last change)?
2. PublicNode websocket, logsSubscribe on the PumpSwap program: how many notifications a second, do the logs carry the event
   data ("Program data:"), and which fields are in it (one transaction fetched over HTTP to match wallet and pool).
usage: python3 research/wallets/live/probe_live.py <out dir>"""
import asyncio, base64, hashlib, json, os, sys, time, urllib.request

AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSS = ["wss://solana-rpc.publicnode.com", "wss://api.mainnet-beta.solana.com"]
HTTP = "https://solana-rpc.publicnode.com"
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
lines = []


def p(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)


def get(url, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                         headers={"User-Agent": "memebot-research", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            p("get failed", url[:80], type(e).__name__, str(e)[:120]); time.sleep(3 * (i + 1))
    return None


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(b):
    n = int.from_bytes(b, "big"); s = ""
    while n:
        n, r = divmod(n, 58); s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


js = get("https://huggingface.co/api/datasets/Slinky21/Pumpfun_v2_dataset?blobs=true")
if js:
    fs = sorted(s["rfilename"] for s in js["siblings"] if s["rfilename"].endswith(".parquet") and "/swap/" in s["rfilename"])
    p("data set lastModified", js.get("lastModified"), "| swap files", len(fs), "| newest", fs[-1] if fs else None)
    p("folders", sorted(set(s["rfilename"].split("/")[0] for s in js["siblings"])))

DISC = {hashlib.sha256(("event:" + n).encode()).digest()[:8]: n for n in ("BuyEvent", "SellEvent", "CreatePoolEvent", "DepositEvent", "WithdrawEvent")}


async def listen(url, secs):
    import websockets
    n = data = 0; kinds = {}; samples = {}; sizes = 0; t0 = time.time(); errs = 0
    async with websockets.connect(url, max_size=None, ping_interval=20) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                  "params": [{"mentions": [AMM]}, {"commitment": "confirmed"}]}))
        while time.time() - t0 < secs:
            try:
                raw = await asyncio.wait_for(ws.recv(), 20)
            except asyncio.TimeoutError:
                p("  silent for 20 s"); continue
            sizes += len(raw)
            m = json.loads(raw)
            v = (m.get("params") or {}).get("result", {}).get("value")
            if not v:
                p("  first message", str(m)[:200]); continue
            n += 1
            if v.get("err"):
                errs += 1; continue
            for ln in v["logs"]:
                if ln.startswith("Program data: "):
                    try:
                        b = base64.b64decode(ln[14:])
                    except Exception:
                        continue
                    k = DISC.get(b[:8], "other:" + b[:8].hex())
                    kinds[k] = kinds.get(k, 0) + 1; data += 1
                    if len(samples.setdefault(k, [])) < 3:
                        samples[k].append((v["signature"], b))
    dt = time.time() - t0
    p("  %s: %d notifications in %.0f s = %.1f/s, failed tx %d, %.0f KB/s, Program data lines %d" % (url, n, dt, n / dt, errs, sizes / dt / 1e3, data))
    p("  kinds", kinds)
    return samples


samples = {}
for url in WSS:
    try:
        p("websocket", url)
        samples = asyncio.run(listen(url, 60))
        if samples:
            break
    except Exception as e:
        p("  failed", type(e).__name__, str(e)[:200])

for k, ss in samples.items():
    for sig, b in ss[:2]:
        p("\n", k, "bytes", len(b), "sig", sig)
        body = b[8:]
        tx = get(HTTP, {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                        "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}]})
        keys = []
        try:
            r = tx["result"]; keys = r["transaction"]["message"]["accountKeys"] + r["meta"].get("loadedAddresses", {}).get("writable", []) + r["meta"].get("loadedAddresses", {}).get("readonly", [])
            p("  blockTime", r.get("blockTime"), "fee payer", keys[0], "accounts", len(keys))
        except Exception as e:
            p("  no transaction", type(e).__name__, str(tx)[:150])
        # walk the body: 8-byte numbers until a 32-byte chunk matches an account of the transaction
        off = 0; row = []
        while off + 8 <= len(body):
            if off + 32 <= len(body) and b58(body[off:off + 32]) in keys:
                a = b58(body[off:off + 32]); row.append("@%d key[%d] %s" % (off, keys.index(a), a)); off += 32
            else:
                row.append("@%d u64 %d" % (off, int.from_bytes(body[off:off + 8], "little"))); off += 8
        p("  " + "\n  ".join(row)); p("  rest bytes", len(body) - off, "| base64", base64.b64encode(b).decode()[:700])
open(os.path.join(out, "probe_live.txt"), "w").write("\n".join(lines) + "\n")
