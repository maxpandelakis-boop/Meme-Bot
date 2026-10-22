"""The rocket hunter's wallet memory (fake money only): from the wallets branch (every wallet's first buy of each graduated coin of
10 Aug-8 Oct 2026 and what it made), the wallets with 5 coins or more -> {address: [coins, wins (made 1.5x or more), big wins (3x or
more), sum of log results]} as rocket_memory.json.gz. usage: python3 research/winlose/rocket_memory.py <wallets dir> <out file>"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd

src, out = sys.argv[1:3]
p = pd.concat([pd.read_parquet(f, columns=["wid", "roi"]) for f in sorted(glob.glob(os.path.join(src, "pairs", "*.parquet")))], ignore_index=True)
p["n"] = 1
p["win"] = (p["roi"] > 1.5).astype("int32")
p["big"] = (p["roi"] > 3).astype("int32")
p["l"] = np.log(p["roi"].clip(1e-3, 1e3))
g = p.groupby("wid")[["n", "win", "big", "l"]].sum()
g = g[g["n"] >= 5].join(pd.read_parquet(os.path.join(src, "wallets.parquet")).set_index("wid")["address"], how="inner")
mem = {a: [int(n), int(w), int(b), round(float(l), 3)] for a, n, w, b, l in zip(g["address"], g["n"], g["win"], g["big"], g["l"])}
with gzip.open(out, "wt") as f:
    json.dump(mem, f, separators=(",", ":"))
print("wallet memory: %d wallets, %.1f MB" % (len(mem), os.path.getsize(out) / 1e6))
