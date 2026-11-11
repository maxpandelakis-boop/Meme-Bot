"""Probe for the scout study (fake money only): the schema of the Pumpfun_v2 trade/create files and a DexScreener lookup of
the coins shown in the Trading Desk video. usage: python3 research/scout/probe.py <out dir>"""
import json, os, sys, time, urllib.request, urllib.parse
SRC = "Slinky21/Pumpfun_v2_dataset"
UA = {"User-Agent": "memebot-research"}
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
log = open(os.path.join(out, "probe.txt"), "w")
def p(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
def get(url, tries=4, raw=False):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                b = r.read(); return b if raw else json.loads(b.decode())
        except Exception as e:
            p("get failed", url[:100], type(e).__name__, str(e)[:100]); time.sleep(5 * (i + 1))
    return None
js = get("https://huggingface.co/api/datasets/%s?blobs=true" % SRC)
files = [(s["rfilename"], s.get("size") or 0) for s in js["siblings"] if s["rfilename"].endswith(".parquet")]
by = {}
for f, n in files:
    by.setdefault(f.split("/")[-2], []).append((f, n))
for k, v in sorted(by.items()):
    v.sort(); p("table", k, len(v), "files", round(sum(n for _, n in v) / 1e9, 1), "GB", "first", v[0][0], "last", v[-1][0])
json.dump(files, open(os.path.join(out, "files.json"), "w"))
import pyarrow.parquet as pq
for tab in ("trade", "create", "complete", "graduate"):
    if tab not in by: continue
    f, n = min(by[tab], key=lambda x: x[1])
    url = "https://huggingface.co/datasets/%s/resolve/main/%s" % (SRC, urllib.parse.quote(f))
    tmp = os.path.join(out, "tmp.parquet")
    urllib.request.urlretrieve(url, tmp) if False else open(tmp, "wb").write(get(url, raw=True))
    pf = pq.ParquetFile(tmp)
    p("\n==", tab, f, n, "rows", pf.metadata.num_rows); p(pf.schema_arrow)
    t = pf.read_row_group(0).slice(0, 8).to_pandas()
    import pandas as pd; pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
    p(t.T.to_string())
    os.remove(tmp)
# the video's coins (Trading Desk video, lock screen "Sunday, November 8"): pump.fun pairs created 6 to 9 Nov 2026
lo, hi = 1794096000000 - 2 * 86400000, 1794096000000 + 2 * 86400000   # 2026-11-08 00:00 UTC +- 2 days
for sym in ["HUSK", "LARK", "PINE", "MOSS", "DUSK", "CORAL", "FLINT", "GULP", "WILLOW"]:
    d = get("https://api.dexscreener.com/latest/dex/search?q=%s" % sym) or {}
    hits = []
    for pr in d.get("pairs") or []:
        b = pr.get("baseToken") or {}
        if pr.get("chainId") != "solana" or (b.get("symbol") or "").upper() != sym: continue
        hits.append((pr.get("pairCreatedAt"), pr.get("dexId"), b.get("address"), pr.get("fdv"), (pr.get("volume") or {}).get("h24")))
    near = [h for h in hits if h[0] and lo <= h[0] <= hi]
    p("\nvideo coin", sym, "solana pairs", len(hits), "created 6-10 Nov", len(near))
    for h in sorted(hits, key=lambda h: h[0] or 0)[-6:]:
        p("   ", time.strftime("%Y-%m-%d %H:%M", time.gmtime((h[0] or 0) / 1000)), h[1:])
    time.sleep(1)
