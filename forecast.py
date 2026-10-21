"""The look-alike forecast for a pick (fake money only, display only): what coins that looked like it at the scan did next, from
the August to October 2026 rows (branch "history2", research/history_build2.py; "Data provided by [Slink21]. Pumpfun Solana
Dataset (2026)." CC BY 4.0). It never changes which coin is picked, how it is scored or when the paper account sells: report.py
shows it under Pick > Details and app.py adds one short line to the pick notification.

forecast_ref.json (built by research/forecast_build.py) holds a sample of those rows: seven numbers a screener shows (age, market
cap, 1 h and 6 h and 5 min price change, 24 h volume to market cap, the last hour's share of the day's volume) and what followed
(the multiple 1.7 hours later, whether it went to zero, whether it reached 2x or 3x within 6 hours), plus how well these
forecasts did in its own backtest ("check"). forecast(f) takes a pick's factors (memebot's "f") and returns the K nearest coins'
outcomes, shrunk toward the average of all rows, or None when too few of the seven numbers are known.
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
REF_PATH = os.path.join(HERE, "forecast_ref.json")
K = 100                  # look-alike coins per forecast (one row per coin)
SHRINK = 20.0            # pseudo-coins at the average of all rows: few look-alikes cannot make an extreme chance
MIN_KNOWN = 4            # of the seven numbers, at least this many must be known
FEATS = ("age", "lmc", "c1", "c6", "m5", "lvolmc", "vol1")
_REF = None


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def features(f):
    """A pick's factors (memebot f: ageH, logMc, c1, c6, m5, volMc, vol1Share) as the seven numbers, None where unknown."""
    f = f if isinstance(f, dict) else {}
    cl = lambda v, a, b: None if v is None else max(a, min(b, v))
    vm = _num(f.get("volMc"))
    age = _num(f.get("ageH"))
    return [math.log10(age) if age and age > 0 else None, _num(f.get("logMc")), cl(_num(f.get("c1")), -100.0, 300.0),
            cl(_num(f.get("c6")), -100.0, 300.0), cl(_num(f.get("m5")), -100.0, 300.0),
            math.log10(1.0 + vm) if vm is not None and vm >= 0 else None, cl(_num(f.get("vol1Share")), 0.0, 1.0)]


def load(path=REF_PATH):
    global _REF
    if _REF is None or path != REF_PATH:
        try:
            with open(path, encoding="utf-8") as fh:
                ref = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(ref, dict) or not isinstance(ref.get("rows"), list) or not ref["rows"]:
            return None
        if path != REF_PATH:
            return ref
        _REF = ref
    return _REF


def _quant(v, q):
    v = sorted(v)
    if not v:
        return None
    i = q * (len(v) - 1)
    lo = int(math.floor(i))
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (i - lo)


def forecast(f, ref=None):
    """-> {"n", "m1": [p10, p50, p90] (the multiple 1.7 hours later), "zero", "x2", "x3", "profit" (chances, 0..1), "base": the
    same chances over all rows, "check": the backtest summary} or None."""
    ref = ref if ref is not None else load()
    if not ref:
        return None
    x = features(f)
    if sum(v is not None for v in x) < MIN_KNOWN:
        return None
    med, iqr = ref["med"], ref["iqr"]
    s = [None if v is None else (v - med[i]) / iqr[i] for i, v in enumerate(x)]
    scored = []
    for r in ref["rows"]:
        d, n = 0.0, 0
        for i, v in enumerate(s):
            w = r[i]
            if v is None or w is None:
                continue
            d += (v - w) ** 2
            n += 1
        if n:
            scored.append((d / n, r))
    scored.sort(key=lambda t: t[0])
    near = [r for _, r in scored[:K]]
    if not near:
        return None
    o = len(FEATS)       # outcomes after the features: m1, zero, x2, x3, profit
    base = ref["base"]
    chance = lambda j, key: (sum(r[o + j] for r in near) + SHRINK * base[key]) / (len(near) + SHRINK)
    return {"n": len(near), "m1": [round(_quant([r[o] for r in near], q), 3) for q in (0.1, 0.5, 0.9)],
            "zero": chance(1, "zero"), "x2": chance(2, "x2"), "x3": chance(3, "x3"), "profit": chance(4, "profit"),
            "base": base, "check": ref.get("check") or {}}


def pct(p):
    """A chance as people read it: "under 1%", "4%", "38%"."""
    return "under 1%" if p < 0.005 else "%.0f%%" % (100 * p)


def push_line(fc):
    """One short line for the pick notification, "" without a forecast."""
    if not fc:
        return ""
    return "Look-alikes: 3x in 6 h %s, to zero %s" % (pct(fc["x3"]), pct(fc["zero"]))
