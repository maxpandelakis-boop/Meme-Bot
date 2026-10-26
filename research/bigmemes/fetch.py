"""Big meme coins on Binance spot (research only, fake money): the universe list and one-hour candles.

Runs in GitHub Actions (the Claude session cannot reach Binance or CoinGecko). Standard library only.
    python3 research/bigmemes/fetch.py out
writes out/universe_raw.json, out/manifest.json and out/klines/<SYMBOL>.csv.gz (t_ms,o,h,l,c,qv,n; one row per hour).
The universe rule is fixed in research/bigmemes/PREREG-BIGMEMES-2026-10-26.md; this file only collects what that rule needs.
"""
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "memebot-research/1.0", "Accept": "application/json"}
CG = "https://api.coingecko.com/api/v3"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DATA = "https://data.binance.vision"
HAND = ("DOGE SHIB PEPE FLOKI BONK WIF BOME MEME PEOPLE 1000SATS NEIRO TURBO PNUT ACT DOGS 1MBABYDOGE TRUMP PENGU MUBARAK "
        "BROCCOLI714 TST BANANAS31 1000CHEEMS 1000CAT PUMP").split()
EXTRA = ["BTC"]                 # for the BTC filter and benchmark only
LAST_DAY = 25                   # October 2026 daily files up to the 25th


def get(url, tries=6, wait=10.0, raw=False):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read()
                return b if raw else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(wait * (k + 1) * (6 if e.code == 429 else 1))
                continue
            print("http", e.code, url[:120], flush=True)
            return None
        except Exception as e:  # network blips
            print("err", type(e).__name__, url[:120], flush=True)
            time.sleep(wait * (k + 1))
    return None


def coingecko():
    memes, page = [], 1
    while page <= 30:
        rows = get(f"{CG}/coins/markets?vs_currency=usd&category=meme-token&order=market_cap_desc&per_page=250&page={page}")
        if not rows:
            break
        memes += [{"id": r["id"], "sym": (r.get("symbol") or "").upper(), "name": r.get("name"),
                   "mcap": r.get("market_cap"), "rank": r.get("market_cap_rank")} for r in rows]
        print("coingecko meme page", page, len(rows), flush=True)
        page += 1
        time.sleep(8)
    tick, page = [], 1
    while page <= 40:
        d = get(f"{CG}/exchanges/binance/tickers?page={page}")
        rows = (d or {}).get("tickers") or []
        if not rows:
            break
        tick += [{"base": t.get("base"), "target": t.get("target"), "coin_id": t.get("coin_id")} for t in rows]
        print("coingecko binance tickers page", page, len(rows), flush=True)
        page += 1
        time.sleep(8)
    return memes, tick


def s3_list(prefix, dirs=True):
    out, marker = [], ""
    while True:
        b = get(f"{S3}?delimiter=/&prefix={prefix}&marker={marker}", raw=True)
        if b is None:
            break
        x = b.decode()
        keys = re.findall(r"<Prefix>([^<]+)</Prefix>" if dirs else r"<Key>([^<]+)</Key>", x)
        keys = [k for k in keys if k != prefix]
        out += keys
        if "<IsTruncated>true</IsTruncated>" not in x or not keys:
            break
        marker = keys[-1]
    return out


def norm(base):
    for p in ("1000000", "1000", "1M"):
        if base.startswith(p) and len(base) > len(p) and not base[len(p)].isdigit():
            return base[len(p):]
    return base


def universe(out):
    memes, tick = coingecko()
    syms = sorted({p.rstrip("/").split("/")[-1] for p in s3_list("data/spot/monthly/klines/")})
    usdt = [s for s in syms if s.endswith("USDT") and not re.search(r"(UP|DOWN|BULL|BEAR)USDT$", s)]
    info = get("https://data-api.binance.vision/api/v3/exchangeInfo") or {}
    status = {s["symbol"]: s.get("status") for s in info.get("symbols", [])}
    meme_ids = {m["id"] for m in memes}
    meme_by_sym = {}
    for m in memes:
        meme_by_sym.setdefault(m["sym"], []).append(m)
    live_id = {}
    for t in tick:
        if (t.get("target") or "").upper() == "USDT" and t.get("base"):
            live_id[t["base"].upper()] = t.get("coin_id")
    picks = []
    for s in usdt:
        base = s[:-4]
        why = []
        if base in HAND:
            why.append("hand")
        if base in live_id:
            if live_id[base] in meme_ids:
                why.append("coingecko-id")
        elif norm(base) in meme_by_sym or base in meme_by_sym:
            why.append("coingecko-symbol")
        if why:
            ms = meme_by_sym.get(norm(base), []) + meme_by_sym.get(base, []) if base != norm(base) else meme_by_sym.get(base, [])
            picks.append({"symbol": s, "base": base, "why": why, "status": status.get(s, "not in exchangeInfo"),
                          "coingecko_id": live_id.get(base), "symbol_matches": ms[:5]})
    missing_hand = [h for h in HAND if h + "USDT" not in usdt]
    raw = {"meme_category": memes, "binance_tickers": tick, "binance_usdt_pairs": usdt, "picks": picks,
           "hand_missing_on_binance_usdt": missing_hand, "coingecko_ok": bool(memes) and bool(tick)}
    with open(os.path.join(out, "universe_raw.json"), "w") as f:
        json.dump(raw, f)
    print("meme category", len(memes), "binance tickers", len(tick), "usdt pairs", len(usdt), "picks", len(picks),
          "hand missing", missing_hand, flush=True)
    return [p["symbol"] for p in picks]


def parse(b):
    rows = []
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        for n in z.namelist():
            for r in csv.reader(io.TextIOWrapper(z.open(n), "utf-8")):
                if not r or not r[0].strip().isdigit():
                    continue
                t = int(r[0])
                if t > 10 ** 14:          # microseconds (files from 2025 on)
                    t //= 1000
                rows.append((t, r[1], r[2], r[3], r[4], r[7], r[8]))
    return rows


def klines(sym, out):
    files = [k for k in s3_list(f"data/spot/monthly/klines/{sym}/1h/", dirs=False) if k.endswith(".zip")]
    days = [k for k in s3_list(f"data/spot/daily/klines/{sym}/1h/", dirs=False)
            if k.endswith(".zip") and re.search(r"-2026-10-(\d\d)\.zip$", k) and int(k[-6:-4]) <= LAST_DAY]
    rows, bad = {}, []
    for k in files + days:
        b = get(f"{DATA}/{k}", raw=True)
        if b is None:
            bad.append(k)
            continue
        for r in parse(b):
            rows[r[0]] = r
    with gzip.open(os.path.join(out, "klines", sym + ".csv.gz"), "wt") as f:
        f.write("t_ms,o,h,l,c,qv,n\n")
        for t in sorted(rows):
            f.write(",".join(str(v) for v in rows[t]) + "\n")
    print(sym, "months", len(files), "days", len(days), "hours", len(rows), "failed", len(bad), flush=True)
    return {"symbol": sym, "months": len(files), "days": len(days), "hours": len(rows), "failed": bad}


def main():
    out = sys.argv[1]
    os.makedirs(os.path.join(out, "klines"), exist_ok=True)
    syms = universe(out) + [e + "USDT" for e in EXTRA]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda s: klines(s, out), syms))
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump({"fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "symbols": res}, f, indent=1)


if __name__ == "__main__":
    main()
