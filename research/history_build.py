"""Long-history data build, part 1 (fake money only): the graduated pump.fun coins of June and July 2026 from the MIT-licensed
Pumpfun Memecoin Corpus on Hugging Face (Slinky21/Pumpfun_Memecoin_Corpus), turned into rows like the big test's: a coin at a
given age after its graduation, with the market numbers a screener showed then (price, market cap, liquidity, volume, buys and
sells, price changes) and what the price did afterwards (1.7 hours later, as the 2h profile measures, and the path over 6 hours
for exit rules). It runs in GitHub Actions (history-build.yml, started by hand only) because the cloud session cannot reach
Hugging Face; the result goes to the branch "history". Nothing is bought, no credential is used.
usage: python3 research/history_build.py <out dir>
"""
import json, os, sys, time, urllib.request

SRC = "Slinky21/Pumpfun_Memecoin_Corpus"
FILES = ["README.md", "KNOWN_ISSUES.md", "postgard_outcomes.parquet", "migrations.parquet", "postgard_snapshots.parquet"]
AGES_H = range(1, 49)      # sample points: whole hours after the graduation
EVAL_H = 1.7               # the 2h profile's price check (memebot PROFILES["2h"]["EVAL_H"])
PATH_H = 6.0               # the paper account's time limit (memebot HOLD_MAX_H)
TOL_S = 600                # a snapshot within 10 minutes of a point stands for it


def fetch(path, out):
    url = "https://huggingface.co/datasets/%s/resolve/main/%s" % (SRC, path)
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "memebot-history-build"})
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                n = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    n += len(b)
            print("fetched %s: %.1f MB" % (path, n / 1e6))
            return
        except Exception as e:
            print("fetch %s failed (%s), retry %d" % (path, type(e).__name__, i + 1))
            time.sleep(10 * (i + 1))
    raise SystemExit("could not fetch " + path)


def ms(col):
    """A timestamp column as epoch milliseconds, NaN where it is empty (NaT must not become the smallest int64)."""
    import pandas as pd
    d = pd.to_datetime(col, utc=True)
    return (d.astype("int64") // 10 ** 6).where(d.notna())


def nearest(t, x):
    """Index of the value in the sorted array t nearest to x."""
    import numpy as np
    i = int(np.searchsorted(t, x))
    if i <= 0:
        return 0
    if i >= len(t):
        return len(t) - 1
    return i if t[i] - x < x - t[i - 1] else i - 1


def main():
    import numpy as np, pandas as pd, pyarrow.parquet as pq
    out = sys.argv[1]
    raw = os.path.join(out, "raw")
    os.makedirs(raw, exist_ok=True)
    for f in FILES:
        fetch(f, os.path.join(raw, f))
    for f in ("README.md", "KNOWN_ISSUES.md"):
        print("\n==== %s of %s" % (f, SRC))
        print(open(os.path.join(raw, f), encoding="utf-8", errors="replace").read()[:12000])

    print("\n==== schemas")
    for f in FILES:
        if f.endswith(".parquet"):
            pf = pq.ParquetFile(os.path.join(raw, f))
            print("%s: %d rows; %s" % (f, pf.metadata.num_rows, ", ".join("%s:%s" % (x.name, x.type) for x in pf.schema_arrow)))

    snap = pq.read_table(os.path.join(raw, "postgard_snapshots.parquet")).to_pandas()
    snap["ts"] = ms(snap["snapshot_time"])
    snap = snap[snap["ts"].notna()].astype({"ts": "int64"}).sort_values(["mint", "ts"]).reset_index(drop=True)
    num = [c for c in snap.columns if c not in ("ts",) and pd.api.types.is_numeric_dtype(snap[c]) and not pd.api.types.is_bool_dtype(snap[c])]
    flags = [c for c in snap.columns if pd.api.types.is_bool_dtype(snap[c])]
    print("\n==== snapshots: %d rows, %d mints, %s to %s UTC" % (len(snap), snap["mint"].nunique(),
          pd.to_datetime(snap["ts"].min(), unit="ms"), pd.to_datetime(snap["ts"].max(), unit="ms")))
    for c in ("phase", "dex_id", "incomplete_data"):
        if c in snap.columns:
            print("  %s: %s" % (c, snap[c].value_counts(dropna=False).head(12).to_dict()))
    gap = snap.groupby("mint")["ts"].diff() / 1000.0
    age = snap["seconds_since_graduation"] / 3600.0
    for lo, hi in ((0, 1), (1, 6), (6, 24), (24, 48), (48, 1e9)):
        m = (age >= lo) & (age < hi)
        print("  age %g-%g h: %d snapshots, median gap %.0f s, mints %d" % (lo, hi, int(m.sum()), float(gap[m].median()) if m.any() else -1, snap.loc[m, "mint"].nunique()))
    print("  numeric columns kept: %s" % ", ".join(num))

    outc = pq.read_table(os.path.join(raw, "postgard_outcomes.parquet")).to_pandas()
    for c in [c for c in outc.columns if "_at" in c and c != "computed_at"]:
        outc[c + "_ms"] = ms(outc[c])
    rug = dict(zip(outc["mint"], outc.get("rug_at_ms", pd.Series([None] * len(outc)))))
    mig = pq.read_table(os.path.join(raw, "migrations.parquet")).to_pandas()
    mig["mig_ms"] = ms(mig["migrated_at"])
    grad = dict(zip(mig["mint"], mig["mig_ms"]))

    rows, t0 = [], time.time()
    for mint, g in snap.groupby("mint", sort=False):
        t = g["ts"].to_numpy()
        px = g["price_usd"].to_numpy(dtype=float)
        liq = g["liquidity_usd"].to_numpy(dtype=float) if "liquidity_usd" in g else np.full(len(g), np.nan)
        sec = g["seconds_since_graduation"].to_numpy(dtype=float)
        g_ms = grad.get(mint)
        if g_ms is None or not np.isfinite(g_ms):
            ok = np.isfinite(sec)
            if not ok.any():
                continue
            g_ms = float(np.median(t[ok] - sec[ok] * 1000.0))
        r_ms = rug.get(mint)
        r_ms = float(r_ms) if r_ms is not None and np.isfinite(r_ms) else None
        cols = {c: g[c].to_numpy() for c in num + flags}
        for h in AGES_H:
            x = g_ms + h * 3_600_000
            i = nearest(t, x)
            if abs(t[i] - x) > TOL_S * 1000 or not (px[i] > 0):
                continue
            rec = {"mint": mint, "h": h, "ts": int(t[i]), "grad_ms": int(g_ms), "age_h": round((t[i] - g_ms) / 3.6e6, 3)}
            for c, v in cols.items():
                val = v[i]
                rec[c] = None if val is None or (isinstance(val, float) and not np.isfinite(val)) else (bool(val) if c in flags else float(val))
            x1 = t[i] + EVAL_H * 3_600_000
            j = nearest(t, x1)
            rugged1 = r_ms is not None and r_ms <= x1
            if abs(t[j] - x1) <= TOL_S * 1000 and px[j] > 0:
                rec.update(px1=float(px[j]), liq1=float(liq[j]) if np.isfinite(liq[j]) else None, dt1_s=round((t[j] - t[i]) / 1000.0))
            else:
                rec.update(px1=None, liq1=None, dt1_s=None)
            rec["rug_by_1"] = bool(rugged1)
            rec["rug_ms"] = int(r_ms) if r_ms is not None else None
            k = (t > t[i]) & (t <= t[i] + PATH_H * 3_600_000) & (px > 0)
            if k.any():
                pk, tk = px[k] / px[i], t[k]
                rec.update(hi6=float(pk.max()), lo6=float(pk.min()), n6=int(k.sum()), last6=float(pk[-1]), last6_dt_s=round((tk[-1] - t[i]) / 1000.0))
                s = np.nonzero(pk <= 0.70)[0]
                p = np.nonzero(pk >= 11.0)[0]
                rec["stop30_min"] = round((tk[s[0]] - t[i]) / 60000.0, 1) if len(s) else None
                rec["stop30_x"] = float(pk[s[0]]) if len(s) else None
                rec["tp11_min"] = round((tk[p[0]] - t[i]) / 60000.0, 1) if len(p) else None
            rows.append(rec)
    print("\n==== built %d rows from %d mints in %.0f s" % (len(rows), snap["mint"].nunique(), time.time() - t0))
    df = pd.DataFrame(rows)
    hist = os.path.join(out, "history")
    os.makedirs(hist, exist_ok=True)
    df.to_parquet(os.path.join(hist, "postgard_hourly.parquet"), compression="zstd", index=False)
    keep = [c for c in outc.columns if not c.endswith("_at") or c == "computed_at"]
    outc[[c for c in keep if c != "computed_at"]].to_parquet(os.path.join(hist, "postgard_outcomes.parquet"), compression="zstd", index=False)
    mig[["mint", "mig_ms", "seconds_to_graduation", "pool_address"]].to_parquet(os.path.join(hist, "migrations.parquet"), compression="zstd", index=False)
    summ = {"source": "https://huggingface.co/datasets/%s" % SRC, "licence": "MIT", "rows": len(df), "mints": int(df["mint"].nunique()) if len(df) else 0,
            "with_px1": int(df["px1"].notna().sum()) if len(df) else 0, "from": int(df["ts"].min()) if len(df) else None, "to": int(df["ts"].max()) if len(df) else None,
            "ages_h": [min(AGES_H), max(AGES_H)], "eval_h": EVAL_H, "path_h": PATH_H, "tol_s": TOL_S, "columns": list(df.columns)}
    json.dump(summ, open(os.path.join(hist, "summary.json"), "w"), indent=1)
    open(os.path.join(hist, "README.md"), "w").write(
        "# Long-history rows for the Meme-Bot (fake money only)\n\n"
        "Derived from the Pumpfun Memecoin Corpus by Slinky21 (https://huggingface.co/datasets/%s, MIT licence): the post-graduation "
        "snapshots of June and July 2026, sampled at whole hours after each coin's graduation (a snapshot within %d s), with the price "
        "%.1f hours later and the path over %.0f hours. Built by research/history_build.py.\n" % (SRC, TOL_S, EVAL_H, PATH_H))
    print(json.dumps({k: v for k, v in summ.items() if k != "columns"}))
    print("columns: %s" % ", ".join(df.columns))
    if len(df):
        print(df.describe(percentiles=[0.1, 0.5, 0.9]).T.to_string(max_rows=200, max_colwidth=40)[:20000])


if __name__ == "__main__":
    main()
