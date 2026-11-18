"""Turn the fetch's universe_raw.json into the frozen list (UNIVERSE.json + UNIVERSE.md). Names only, no prices.

    python3 research/bigmemes/universe.py <data dir> [--drop SYMBOL=reason ...]

Every pair the pre-registered rule picks goes in. The only manual change the pre-registration allows: a pair matched by
symbol only (no longer listed) is dropped with --drop when its Binance coin is clearly a different, non-meme project.
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--drop", nargs="*", default=[])
    ap.add_argument("--md", default="research/bigmemes/UNIVERSE.md")
    ap.add_argument("--json", default="research/bigmemes/UNIVERSE.json")
    a = ap.parse_args()
    raw = json.load(open(os.path.join(a.data, "universe_raw.json")))
    drop = dict(x.split("=", 1) for x in a.drop)
    keep, gone = [], []
    for p in raw["picks"]:
        if p["symbol"] in drop:
            if p["why"] != ["coingecko-symbol"]:
                raise SystemExit(f"{p['symbol']} is not a symbol-only match; the pre-registration does not allow dropping it")
            gone.append((p, drop[p["symbol"]]))
        else:
            keep.append(p)
    with open(a.json, "w") as f:
        json.dump({"symbols": [p["symbol"] for p in keep]}, f, indent=1)
    lines = ["# The frozen universe: meme coins on Binance spot (USDT pairs)", "",
             f"Built by research/bigmemes/universe.py from the fetch's universe_raw.json (CoinGecko meme category: "
             f"{len(raw['meme_category'])} coins; CoinGecko's Binance ticker list: {len(raw['binance_tickers'])} tickers; "
             f"Binance USDT pairs with monthly files: {len(raw['binance_usdt_pairs'])}). Written from names only, before any "
             f"price was read.", "",
             f"Hand-list coins without a Binance USDT pair: {', '.join(raw['hand_missing_on_binance_usdt']) or 'none'}.", "",
             f"## In ({len(keep)})", "", "| pair | why | Binance status | CoinGecko id / symbol matches |", "|---|---|---|---|"]
    for p in keep:
        ms = "; ".join(f"{m['name']} ({m['id']})" for m in p["symbol_matches"][:3])
        lines.append(f"| {p['symbol']} | {', '.join(p['why'])} | {p['status']} | {p['coingecko_id'] or ''} {ms} |")
    lines += ["", f"## Dropped as a different, non-meme project with the same ticker ({len(gone)})", ""]
    lines += [f"- {p['symbol']}: {why}" for p, why in gone] or ["- none"]
    with open(a.md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(len(keep), "in,", len(gone), "dropped")


if __name__ == "__main__":
    main()
