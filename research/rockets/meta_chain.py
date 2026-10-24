"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md): the launch facts of every graduated coin of the
five month windows straight from the Solana chain and the coin's own metadata file, as a second source next to pump.fun's API
(research/rockets/meta_fetch.py), which answers little from GitHub's runners.

  shard <plan.json> <i> <n> <out.json.gz>   mints i, i+n, ...; the file is rewritten every 200 mints
  final <dir with shard files> <out dir>    one chain.parquet

Per mint:
  - the Metaplex metadata account (address derived from the mint): name, ticker, link to the metadata file
  - pump.fun's bonding-curve account (address derived from the mint): the creator wallet stored in it
  - the oldest transaction that touched the metadata account = the coin's creation (time; the account is written once)
  - the metadata file (IPFS, set at launch, cannot change): the X, Telegram and website links the creator gave
RPC: Helius with the HELIUS_API_KEY secret when it answers, otherwise the public Solana RPC. The key is never printed or saved.
Nothing is bought, no wallet is used."""
import base64, concurrent.futures, glob, gzip, hashlib, json, os, re, sys, threading, time, urllib.error, urllib.request

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
META = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
GATEWAYS = ("https://ipfs.io/ipfs/%s", "https://gateway.pinata.cloud/ipfs/%s", "https://dweb.link/ipfs/%s", "https://w3s.link/ipfs/%s",
            "https://4everland.io/ipfs/%s")
UA = {"User-Agent": "memebot-research", "Accept": "application/json", "Content-Type": "application/json"}


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
        self.urls.append((PUBLIC_RPC, 0.35))
        self.codes = {}

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
        for url, gap in self.urls:
            st, res = self.call_url(url, method, params, gap)
            key = ("helius " if "helius" in url else "public ") + str(st)
            self.codes[key] = self.codes.get(key, 0) + 1
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


CID = re.compile(r"/ipfs/([A-Za-z0-9]+)")
_gw = [0]


def metadata_file(uri):
    """The metadata JSON: the original link first, then the same file over other IPFS gateways."""
    if not uri:
        return None, "nouri"
    urls = [uri]
    m = CID.search(uri)
    if m:
        k = _gw[0]
        _gw[0] += 1
        urls += [GATEWAYS[(k + j) % len(GATEWAYS)] % m.group(1) for j in range(2)]
    last = None
    for u in urls:
        if not u.startswith("http"):
            continue
        st, raw = http(u, gap=0.25, tries=2, timeout=20)
        last = st
        if raw:
            try:
                return json.loads(raw), "ok"
            except Exception:
                last = "badjson"
    return None, str(last)


def one(rpc, mint, md):
    rec = {"mint": mint}
    sigs = rpc.call("getSignaturesForAddress", [md, {"limit": 1000}])
    if isinstance(sigs, list) and sigs:
        old = sigs[-1]
        rec["created_s"] = old.get("blockTime")
        rec["meta_sigs"] = len(sigs)
    return rec


def cmd_shard(plan, i, n, out):
    mints = json.load(open(plan))["mints"][int(i)::int(n)]
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 200))
    rpc = Rpc()
    res, files = {}, {}
    pool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("WORKERS") or 6))
    for a in range(0, len(mints), 100):
        if time.time() > stop:
            log("time budget used at", a, "of", len(mints))
            break
        part = mints[a:a + 100]
        mds = [metadata_address(m) for m in part]
        cvs = [curve_address(m) for m in part]
        acc = rpc.call("getMultipleAccounts", [mds, {"encoding": "base64"}]) or {}
        acc2 = rpc.call("getMultipleAccounts", [cvs, {"encoding": "base64"}]) or {}
        meta = {}
        for m, v in zip(part, (acc.get("value") or [None] * len(part)) if isinstance(acc, dict) else [None] * len(part)):
            if v and v.get("data"):
                meta[m] = parse_metadata(v["data"][0]) or {}
        for m, v in zip(part, (acc2.get("value") or [None] * len(part)) if isinstance(acc2, dict) else [None] * len(part)):
            if v and v.get("data"):
                meta.setdefault(m, {}).update(parse_curve(v["data"][0]))
        jobs = {pool.submit(one, rpc, m, md): m for m, md in zip(part, mds)}
        fj = {pool.submit(metadata_file, meta.get(m, {}).get("uri")): m for m in part}
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
                res[m].update({"f_twitter": j.get("twitter"), "f_telegram": j.get("telegram"), "f_website": j.get("website"),
                               "f_name": j.get("name"), "f_symbol": j.get("symbol"), "f_createdOn": j.get("createdOn"),
                               "f_showName": j.get("showName"), "f_desc_len": len(str(j.get("description") or ""))})
        if a % 200 == 0 or a + 100 >= len(mints):
            got = sum(1 for r in res.values() if r.get("created_s"))
            log(a + len(part), "of", len(mints), "created", got, "names", sum(1 for r in res.values() if r.get("symbol")),
                "creator", sum(1 for r in res.values() if r.get("curve_creator")), "files", files, "rpc", rpc.codes)
            tmp = out + ".tmp"
            with gzip.open(tmp, "wt") as fh:
                json.dump({"coins": res, "done": a + len(part), "planned": len(mints)}, fh)
            os.replace(tmp, out)
    pool.shutdown()


def cmd_final(src, out):
    import pandas as pd
    os.makedirs(out, exist_ok=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(src, "**", "*.json.gz"), recursive=True)):
        rows += list(json.load(gzip.open(f, "rt"))["coins"].values())
    d = pd.DataFrame(rows).drop_duplicates("mint")
    for c in d.columns:
        if d[c].dtype == object and c != "mint":
            d[c] = d[c].map(lambda x: None if x is None else (x if isinstance(x, str) else json.dumps(x)))
    d.to_parquet(os.path.join(out, "chain.parquet"), index=False)
    log("coins", len(d), {c: int(d[c].notna().sum()) for c in d.columns})


if __name__ == "__main__":
    {"shard": cmd_shard, "final": cmd_final}[sys.argv[1]](*sys.argv[2:])
