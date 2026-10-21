"""Probe for the long-history study (fake money only): which free data sets exist on Hugging Face, how big they are, what
their columns hold, and whether GeckoTerminal still serves minute candles for their old pools. It runs in GitHub Actions
(history-probe.yml, started by hand only) because the cloud session cannot reach these hosts. The log holds status codes,
file lists with sizes, column names, licence lines, row counts and a few cell values cut to 120 characters, with every
Solana address masked; no credential is used and nothing is written anywhere.
usage: python3 research/history_probe.py
"""
import json, re, sys, time, urllib.parse, urllib.request

HF = "https://huggingface.co"
DS = "https://datasets-server.huggingface.co"
GT = "https://api.geckoterminal.com/api/v2"
KNOWN = ["jocry/Pumpfun_Memecoin_Corpus", "Slinky21/Pumpfun_Memecoin_Corpus", "loopholetape/pumpfun-launches", "pumpdatafun/pump-fun-trades-sample"]
SEARCH = ["pumpfun", "pump.fun", "pump-fun", "pumpswap", "memecoin", "solana meme", "solana token", "rug pull"]
ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")


def get(url, raw=False, tries=2):
    """-> (status, body or None). JSON unless raw."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "memebot-history-probe", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read(8_000_000).decode("utf-8", "replace")
                return r.status, (body if raw else json.loads(body))
        except urllib.error.HTTPError as e:
            if e.code == 429 and i + 1 < tries:
                time.sleep(15)
                continue
            return e.code, None
        except Exception as e:      # timeouts, DNS, bad JSON: the probe reports and goes on
            return "err %s" % type(e).__name__, None
    return "gave up", None


def cut(v, n=120):
    s = ADDR.sub(lambda m: m.group(0)[:4] + "…", str(v))
    return s if len(s) <= n else s[:n] + "…"


def size(n):
    n = float(n or 0)
    for u in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024
    return "%.1f PB" % n


def search():
    print("== Hugging Face search")
    seen = {}
    for q in SEARCH:
        st, js = get("%s/api/datasets?search=%s&limit=40&full=false" % (HF, urllib.parse.quote(q)))
        print("search %-14s -> %s, %d hits" % (q, st, len(js or [])))
        for d in js or []:
            seen[d.get("id")] = d
    rows = sorted(seen.values(), key=lambda d: -(d.get("downloads") or 0))
    for d in rows[:60]:
        print("  %-60s downloads %6s likes %4s modified %s" % (cut(d.get("id"), 60), d.get("downloads"), d.get("likes"), str(d.get("lastModified"))[:10]))
    return [d.get("id") for d in rows]


def card(ds):
    st, txt = get("%s/datasets/%s/raw/main/README.md" % (HF, ds), raw=True)
    print("  card: %s" % st)
    if not txt:
        return
    keep = [ln for ln in txt.splitlines() if ln.strip()][:70]
    for ln in keep:
        print("   | " + cut(ln, 160))


def files(ds):
    st, js = get("%s/api/datasets/%s?blobs=true" % (HF, ds))
    print("  meta: %s" % st)
    if not js:
        return
    cd = js.get("cardData") or {}
    print("  licence %s, gated %s, private %s, modified %s, downloads %s" % (cd.get("license"), js.get("gated"), js.get("private"), str(js.get("lastModified"))[:10], js.get("downloads")))
    sib = js.get("siblings") or []
    total = sum(s.get("size") or 0 for s in sib)
    print("  %d files, %s in all" % (len(sib), size(total)))
    for s in sorted(sib, key=lambda s: -(s.get("size") or 0))[:25]:
        print("   %10s  %s" % (size(s.get("size")), cut(s.get("rfilename"), 100)))


def server(ds):
    st, info = get("%s/info?dataset=%s" % (DS, urllib.parse.quote(ds)))
    print("  datasets-server info: %s" % st)
    found = []
    for cfg, di in ((info or {}).get("dataset_info") or {}).items():
        splits = di.get("splits") or {}
        print("  config %s: %s rows in %s, size %s" % (cfg, {k: v.get("num_examples") for k, v in splits.items()}, list(splits), size(di.get("dataset_size"))))
        feats = di.get("features") or {}
        print("   columns: %s" % cut(", ".join("%s:%s" % (k, (v or {}).get("dtype") or (v or {}).get("_type")) for k, v in feats.items()), 1500))
        for sp in list(splits)[:2]:
            st2, fr = get("%s/first-rows?dataset=%s&config=%s&split=%s" % (DS, urllib.parse.quote(ds), urllib.parse.quote(cfg), urllib.parse.quote(sp)))
            rows = (fr or {}).get("rows") or []
            print("   first rows %s/%s: %s, %d rows" % (cfg, sp, st2, len(rows)))
            for r in rows[:2]:
                print("    " + cut(json.dumps(r.get("row"), default=str), 600))
            if rows:
                found.append(rows[0].get("row") or {})
    return found


def gecko(rows):
    """Does GeckoTerminal still serve minute candles near a data set row's time? One token per data set, three calls."""
    for row in rows[:1]:
        mint = next((v for k, v in row.items() if isinstance(v, str) and ADDR.fullmatch(v) and ("mint" in k.lower() or "token" in k.lower() or "address" in k.lower())), None)
        ts = next((v for k, v in row.items() if any(w in k.lower() for w in ("time", "created", "date", "slot"))), None)
        print("  gecko: mint column %s, time value %s" % ("found" if mint else "none", cut(ts, 40)))
        if not mint:
            return
        st, js = get("%s/networks/solana/tokens/%s/pools?page=1" % (GT, mint))
        pools = [p.get("attributes", {}) for p in (js or {}).get("data") or []]
        print("  gecko token pools: %s, %d pools %s" % (st, len(pools), [cut(p.get("name"), 30) for p in pools[:3]]))
        time.sleep(3)
        pid = ((js or {}).get("data") or [{}])[0].get("attributes", {}).get("address") if pools else None
        if pid:
            st, oh = get("%s/networks/solana/pools/%s/ohlcv/minute?aggregate=1&limit=1000" % (GT, pid))
            lst = (((oh or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            span = (time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[-1][0])), time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[0][0]))) if lst else None
            print("  gecko minute candles (latest page): %s, %d candles, from-to %s" % (st, len(lst), span))
            time.sleep(3)


def main():
    t0 = time.time()
    ids = search()
    extra = [d for d in ids if d not in KNOWN and re.search(r"pump|meme|solana", d or "", re.I)][:8]
    for ds in KNOWN + extra:
        print("\n== %s" % ds)
        files(ds)
        card(ds)
        rows = server(ds)
        if ds in KNOWN:
            gecko(rows or [])
        if time.time() - t0 > 11 * 60:
            print("time is up after %d data sets" % (KNOWN + extra).index(ds))
            break
    print("\nprobe done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    sys.exit(main())
