"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md): which IPFS gateways answer for the coins'
metadata files from GitHub's machines. The chain fetch of 24 Oct read only 38.5 % of the files (ipfs.io links 34.7 %): two
gateways, one try each, 48 workers on three machines. This probe takes 300 links that failed and 100 that worked (seed 7) and
asks every gateway below for each, one request at a time per gateway (GAP seconds apart), and the link's own host for the
links that are not IPFS. No outcome is used; nothing is bought; no key is used.

  probe <chain.parquet> <out.json>"""
import concurrent.futures, json, os, re, sys, time, urllib.error, urllib.request

CID = re.compile(r"(?:/ipfs/|^ipfs://)([A-Za-z0-9]{20,})")      # also the bare ipfs:// links (meta_chain.py skipped them)
GATEWAYS = {
    "ipfs.io": "https://ipfs.io/ipfs/%s", "dweb.link": "https://dweb.link/ipfs/%s", "w3s.link": "https://w3s.link/ipfs/%s",
    "gateway.pinata.cloud": "https://gateway.pinata.cloud/ipfs/%s", "pump.mypinata.cloud": "https://pump.mypinata.cloud/ipfs/%s",
    "cf-ipfs.com": "https://cf-ipfs.com/ipfs/%s", "4everland.io": "https://4everland.io/ipfs/%s",
    "nftstorage.link": "https://nftstorage.link/ipfs/%s", "ipfs.filebase.io": "https://ipfs.filebase.io/ipfs/%s",
    "trustless-gateway.link": "https://trustless-gateway.link/ipfs/%s", "flk-ipfs.xyz": "https://flk-ipfs.xyz/ipfs/%s",
    "ipfs.cyou": "https://ipfs.cyou/ipfs/%s", "dget.top": "https://dget.top/ipfs/%s", "storry.tv": "https://storry.tv/ipfs/%s",
    "subdomain dweb.link": "https://%s.ipfs.dweb.link/", "subdomain w3s.link": "https://%s.ipfs.w3s.link/",
}
UA = {"User-Agent": "memebot-research (github.com/maxpandelakis-boop/Meme-Bot)"}


def get(url, timeout):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            raw = r.read(300_000)
        try:
            json.loads(raw)
            return "ok", time.time() - t
        except Exception:
            return "notjson", time.time() - t
    except urllib.error.HTTPError as e:
        return str(e.code), time.time() - t
    except Exception as e:
        return type(e).__name__, time.time() - t


def run_gateway(name, pattern, cids, gap, timeout):
    res, fails = {}, 0
    for k, (mint, cid) in enumerate(cids):
        if fails >= 25 and not any(v == "ok" for v in res.values()):
            res[mint] = "skipped (25 failures first)"
            continue
        st, dt = get(pattern % cid, timeout)
        res[mint] = st
        fails = fails + 1 if st != "ok" else 0
        time.sleep(max(0.0, gap - dt))
    return name, res


def cmd_probe(chain_path, out):
    import numpy as np, pandas as pd
    d = pd.read_parquet(chain_path)
    for c in d.columns:
        if not pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].where(~d[c].isin(["NaN", "None", "null"]), None)
    d = d[d["uri"].notna()].sort_values("mint").reset_index(drop=True)
    read = d["f_keys"].notna()
    rng = np.random.default_rng(7)
    bad = d[~read].iloc[rng.choice(int((~read).sum()), 300, replace=False)]
    good = d[read].iloc[rng.choice(int(read.sum()), 100, replace=False)]
    gap, timeout = float(os.environ.get("GAP") or 0.5), float(os.environ.get("TIMEOUT") or 12)
    out_d = {"gap_s": gap, "timeout_s": timeout}
    for label, part in (("failed_before", bad), ("worked_before", good)):
        cids = [(m, CID.search(u).group(1)) for m, u in zip(part["mint"], part["uri"]) if CID.search(u)]
        other = [(m, u) for m, u in zip(part["mint"], part["uri"]) if not CID.search(u)]
        o = out_d.setdefault(label, {"links": len(part), "ipfs_links": len(cids), "other_links": len(other)})
        pool = concurrent.futures.ThreadPoolExecutor(len(GATEWAYS) + 1)
        futs = [pool.submit(run_gateway, n, p, cids, gap, timeout) for n, p in GATEWAYS.items()]
        futs.append(pool.submit(run_gateway, "own host (not IPFS)", "%s", other, gap, timeout))
        per = dict(f.result() for f in futs)
        pool.shutdown()
        o["by_gateway"] = {n: {"ok": sum(v == "ok" for v in r.values()), "of": len(r),
                               "codes": dict(sorted({c: sum(v == c for v in r.values()) for c in set(r.values())}.items()))}
                           for n, r in per.items()}
        ipfs_names = [n for n in GATEWAYS]
        o["ipfs_any_gateway_ok"] = sum(any(per[n].get(m) == "ok" for n in ipfs_names) for m, _ in cids)
        hosts = part["uri"].str.extract(r"https?://([^/]+)/")[0].fillna("?")
        o["other_hosts"] = hosts[[not CID.search(u) for u in part["uri"]]].value_counts().head(10).to_dict()
        print(label, json.dumps(o)[:3000], flush=True)
    json.dump(out_d, open(out, "w"), indent=1)


if __name__ == "__main__":
    {"probe": cmd_probe}[sys.argv[1]](*sys.argv[2:])
