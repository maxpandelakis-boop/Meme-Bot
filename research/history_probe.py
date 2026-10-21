"""Probe for the long-history study (fake money only): which free data sets exist on Hugging Face, how big they are, what their
tables and columns hold, and whether GeckoTerminal still serves minute candles for old pools. It runs in GitHub Actions
(history-probe.yml, started by hand only) because the cloud session cannot reach these hosts. The log holds status codes, file
lists with sizes, column names and types, licence lines, row counts and a few cell values cut short, with every Solana address
masked; no credential is used and nothing is written anywhere.
usage: python3 research/history_probe.py [--search] [data set id ...]
Parquet schemas are read from each file's footer with HTTP range requests (pyarrow, when installed), never the whole file.
"""
import json, re, sys, time, urllib.parse, urllib.request

HF = "https://huggingface.co"
DS = "https://datasets-server.huggingface.co"
GT = "https://api.geckoterminal.com/api/v2"
SEARCH = ["pumpfun", "pump.fun", "pump-fun", "pumpswap", "memecoin", "solana meme", "rug pull"]
ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
UA = {"User-Agent": "memebot-history-probe"}


def get(url, raw=False, tries=2):
    """-> (status, body or None). JSON unless raw."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict(UA, Accept="application/json"))
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read(8_000_000).decode("utf-8", "replace")
                return r.status, (body if raw else json.loads(body))
        except urllib.error.HTTPError as e:
            if e.code == 429 and i + 1 < tries:
                time.sleep(20)
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


class RangeFile:
    """A read-only file over HTTP range requests, enough for pyarrow to read a parquet footer."""
    def __init__(self, url, length):
        self.url, self.length, self.pos, self.fetched = url, length, 0, 0
        self.closed = False

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.length + off)
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.length - self.pos
        n = min(n, self.length - self.pos)
        if n <= 0:
            return b""
        req = urllib.request.Request(self.url, headers=dict(UA, Range="bytes=%d-%d" % (self.pos, self.pos + n - 1)))
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
        self.pos += len(b)
        self.fetched += len(b)
        return b

    def close(self):
        self.closed = True


def schema(ds, path, length):
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("    (pyarrow not installed: no schema)")
        return
    try:
        f = RangeFile("%s/datasets/%s/resolve/main/%s" % (HF, ds, urllib.parse.quote(path)), length)
        pf = pq.ParquetFile(f)
        md = pf.metadata
        print("    schema of %s: %d rows, %d row groups, footer read with %s" % (cut(path, 90), md.num_rows, md.num_row_groups, size(f.fetched)))
        print("     " + cut(", ".join("%s:%s" % (fl.name, fl.type) for fl in pf.schema_arrow), 2500))
        st = md.row_group(0).column(0).statistics if md.num_row_groups else None
        if st is not None and st.has_min_max:
            print("     first column %s min %s max %s (row group 0)" % (pf.schema_arrow[0].name, cut(st.min, 40), cut(st.max, 40)))
    except Exception as e:
        print("    schema of %s failed: %s %s" % (cut(path, 90), type(e).__name__, cut(e, 200)))


def search():
    print("== Hugging Face search")
    seen = {}
    for q in SEARCH:
        st, js = get("%s/api/datasets?search=%s&limit=40&full=false" % (HF, urllib.parse.quote(q)))
        for d in js or []:
            seen[d.get("id")] = d
    for d in sorted(seen.values(), key=lambda d: -(d.get("downloads") or 0))[:60]:
        print("  %-60s downloads %6s modified %s" % (cut(d.get("id"), 60), d.get("downloads"), str(d.get("lastModified"))[:10]))


def card(ds, n=120):
    st, txt = get("%s/datasets/%s/raw/main/README.md" % (HF, ds), raw=True)
    print("  card: %s" % st)
    for ln in [ln for ln in (txt or "").splitlines() if ln.strip()][:n]:
        print("   | " + cut(ln, 200))


def files(ds):
    st, js = get("%s/api/datasets/%s?blobs=true" % (HF, ds))
    print("  meta: %s" % st)
    if not js:
        return []
    cd = js.get("cardData") or {}
    print("  licence %s, gated %s, modified %s, downloads %s" % (cd.get("license"), js.get("gated"), str(js.get("lastModified"))[:10], js.get("downloads")))
    sib = [s for s in js.get("siblings") or [] if s.get("rfilename")]
    print("  %d files, %s in all" % (len(sib), size(sum(s.get("size") or 0 for s in sib))))
    groups = {}
    for s in sib:
        name = s["rfilename"]
        parts = name.split("/")
        # the table is the last folder; a top-level file is its own group
        key = parts[-2] if len(parts) > 1 else name
        groups.setdefault(key, []).append(s)
    for key, fs in sorted(groups.items(), key=lambda kv: -sum(s.get("size") or 0 for s in kv[1])):
        names = sorted(s["rfilename"] for s in fs)
        dates = sorted(set(re.findall(r"20\d\d-?\d\d-?\d\d", " ".join(names))))
        print("   %-34s %4d files %10s  dates %s .. %s  e.g. %s" % (cut(key, 34), len(fs), size(sum(s.get("size") or 0 for s in fs)), dates[0] if dates else "-", dates[-1] if dates else "-", cut(names[0], 90)))
    return groups


def server(ds):
    st, info = get("%s/info?dataset=%s" % (DS, urllib.parse.quote(ds)))
    print("  datasets-server info: %s" % st)
    for cfg, di in ((info or {}).get("dataset_info") or {}).items():
        splits = di.get("splits") or {}
        print("  config %s: %s rows" % (cfg, {k: v.get("num_examples") for k, v in splits.items()}))
        for sp in list(splits)[:1]:
            st2, fr = get("%s/first-rows?dataset=%s&config=%s&split=%s" % (DS, urllib.parse.quote(ds), urllib.parse.quote(cfg), urllib.parse.quote(sp)))
            for r in ((fr or {}).get("rows") or [])[:1]:
                print("    first row: " + cut(json.dumps(r.get("row"), default=str), 900))


def gecko_depth():
    """How far back GeckoTerminal serves minute candles: one old graduated pool, paged back with before_timestamp."""
    print("\n== GeckoTerminal depth")
    st, js = get("%s/networks/solana/dexes/pumpswap/pools?page=10&sort=h24_volume_usd_desc" % GT)
    pools = [p.get("attributes", {}) for p in (js or {}).get("data") or []]
    print("  pumpswap pools page 10: %s, %d pools" % (st, len(pools)))
    for back_days in (30, 60, 90, 150):
        time.sleep(7)
        old = [p for p in pools if p.get("pool_created_at")]
        if not old:
            return
        p = old[0]
        before = int(time.time()) - back_days * 86400
        st, oh = get("%s/networks/solana/pools/%s/ohlcv/hour?aggregate=1&limit=24&before_timestamp=%d" % (GT, p.get("address"), before))
        lst = (((oh or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        print("  pool created %s, hour candles before %d days ago: %s, %d candles" % (str(p.get("pool_created_at"))[:10], back_days, st, len(lst)))


def main():
    a = sys.argv[1:]
    t0 = time.time()
    if "--search" in a:
        search()
    for ds in [x for x in a if not x.startswith("--")]:
        print("\n== %s" % ds)
        groups = files(ds)
        card(ds)
        server(ds)
        for key, fs in list(groups.items())[:40]:
            pq_files = sorted((s for s in fs if s["rfilename"].endswith(".parquet")), key=lambda s: s["rfilename"])
            if pq_files:
                schema(ds, pq_files[0]["rfilename"], pq_files[0].get("size") or 0)
        if time.time() - t0 > 20 * 60:
            print("time is up")
            break
    if "--gecko" in a:
        gecko_depth()
    print("\nprobe done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    sys.exit(main())
