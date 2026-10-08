"""Exit rules replayed on the stored candle paths of every tip (memerec) and every listed new launch (memeyoung).

Each 1 h / 24 h result priced from candles carries "path": [[minutes after the tip, high, low, close], ...] relative to the
entry price (from 2026-10-08 on). A rule sells at its take-profit or stop level the first time a candle reaches it; when one
candle reaches both, the stop is assumed first (conservative); a trailing stop follows the highest high of the earlier
candles. Without an exit the coin is sold at the window's end price. Fake money: 20 per pick, fees 0.5% with a 0.81 minimum.

usage: git archive origin/results db/memerec db/memeyoung | tar -x -C /tmp/res && python3 -I research/check_exits.py /tmp/res
"""
import glob, json, os, sys

TICKET = 20.0


def fee(x):
    return max(0.81, 0.005 * x)


def net(m):
    inv = TICKET - fee(TICKET)
    g = inv * m
    return (max(0.0, g - fee(g)) if g > 0 else 0.0) - TICKET


def replay(path, end_mult, tp=None, sl=None, trail=None):
    """-> the multiple the rule sold at."""
    peak = 1.0
    for _, hi, lo, close in path:
        stop = None
        if sl is not None:
            stop = 1.0 - sl
        if trail is not None:
            t = peak * (1.0 - trail)
            stop = t if stop is None else max(stop, t)
        if stop is not None and lo <= stop:
            return stop
        if tp is not None and hi >= 1.0 + tp:
            return 1.0 + tp
        peak = max(peak, hi)
    return end_mult


RULES = [("hold to the end", {}), ("+20% / -20%", {"tp": 0.2, "sl": 0.2}), ("+30% / -15%", {"tp": 0.3, "sl": 0.15}),
         ("+50%, no stop", {"tp": 0.5}), ("+50% / -30%", {"tp": 0.5, "sl": 0.3}), ("+100% / -50%", {"tp": 1.0, "sl": 0.5}),
         ("+20%, no stop", {"tp": 0.2}), ("trailing stop 20%", {"trail": 0.2}), ("trailing stop 30%", {"trail": 0.3}),
         ("+50% or trailing 25%", {"tp": 0.5, "trail": 0.25})]


def results(root):
    out = []
    for coll in ("memerec", "memeyoung"):
        for fn in glob.glob(os.path.join(root, "db", coll, "*.json")):
            try:
                doc = json.load(open(fn, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for key, res in ((doc.get("outs") or {}).items() if isinstance(doc.get("outs"), dict) else []):
                for o in (res or {}).get("picks") or []:
                    if isinstance(o, dict) and isinstance(o.get("path"), list) and o["path"] and isinstance(o.get("mult"), (int, float)):
                        out.append((coll, key, o))
    return out


def main(root):
    rs = results(root)
    print("results with a stored candle path: %d" % len(rs))
    for coll in ("memerec", "memeyoung"):
        for key in ("1", "24"):
            sel = [o for c, k, o in rs if c == coll and k == key]
            if not sel:
                continue
            print("\n== %s, %s h window: %d results (%s)" % (coll, key, len(sel), "the bot's tips" if coll == "memerec" else "new launches under an hour old"))
            for name, kw in RULES:
                e = [net(replay(o["path"], o["mult"], **kw)) for o in sel]
                print("  %-24s avg %+6.2f per 20   win %5.1f%%   total %+8.2f" % (name, sum(e) / len(e), 100.0 * sum(1 for x in e if x > 0) / len(e), sum(e)))


if __name__ == "__main__":
    main(sys.argv[1])
