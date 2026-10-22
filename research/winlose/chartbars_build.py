"""Compact copy of the history2 one-minute bars for the winner/loser study (fake money only).
usage: python3 research/winlose/chartbars_build.py <bars dir from the history-build artifact> <coins.parquet> <out dir>
Keeps each pool's bars of its first 25 hours (entries are at most 24 h old; the outcomes are already in the hourly rows),
as minute index since the graduation and float32 numbers, in files under 90 MB, so the cloud session can read them from a branch."""
import glob, os, sys
import numpy as np, pandas as pd

src, coins, out = sys.argv[1:4]
KEEP_H = int(os.environ.get("KEEP_H") or 25)
os.makedirs(out, exist_ok=True)
g = pd.read_parquet(coins, columns=["pool", "grad_ms"]).drop_duplicates("pool").set_index("pool")["grad_ms"]
files = sorted(glob.glob(os.path.join(src, "**", "bars_*.parquet"), recursive=True))
print(len(files), "bar files")
n = 0
for f in files:
    b = pd.read_parquet(f)
    b["mi"] = ((b["m"] - b["pool"].map(g)) // 60_000)
    b = b[(b["mi"] >= 0) & (b["mi"] < KEEP_H * 60)].copy()
    b["mi"] = b["mi"].astype("int16")
    keep = ["pool", "mi", "p_open", "p_close", "p_hi", "p_lo", "sol_buy", "sol_sell", "n_buy", "n_sell", "n_atomic"]
    b = b[keep]
    for c in ("p_open", "p_close", "p_hi", "p_lo", "sol_buy", "sol_sell"):
        b[c] = b[c].astype("float32")
    for c in ("n_buy", "n_sell", "n_atomic"):
        b[c] = b[c].astype("int32")
    p = os.path.join(out, os.path.basename(f))
    b.to_parquet(p, index=False, compression="zstd")
    n += len(b)
    print(os.path.basename(f), len(b), "%.1f MB" % (os.path.getsize(p) / 1e6))
print("rows", n)
