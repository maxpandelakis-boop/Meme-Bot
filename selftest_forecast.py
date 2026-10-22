"""Self test of the look-alike forecast (forecast.py; fake money only, display only): the numbers it compares, the forecast from a
small made-up reference, the push line, the Pick tab's section and the pick notification's text (no store, nothing is sent).
usage: python3 selftest_forecast.py
"""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import forecast as FC

FAILS = []


def check(ok, what):
    print("  %s %s" % ("PASS" if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def ref_of(rows):
    """A reference with med 0 and iqr 1, so the stored numbers are the features themselves."""
    n = len(rows)
    base = {k: sum(r[7 + j] for r in rows) / n for j, k in ((1, "zero"), (2, "x2"), (3, "x3"), (4, "profit"))}
    return {"med": [0.0] * 7, "iqr": [1.0] * 7, "rows": rows, "base": base, "check": {"bot_picks": {"n": 5}}}


def main():
    f = {"ageH": 10.0, "logMc": 5.5, "c1": 500.0, "c6": -20.0, "m5": None, "volMc": 9.0, "vol1Share": 0.1}
    x = FC.features(f)
    check(x[0] == 1.0 and x[1] == 5.5 and x[2] == 300.0 and x[3] == -20.0 and x[4] is None and x[5] == 1.0 and x[6] == 0.1,
          "features: log age, log mc, changes clipped to 300%%, unknown stays unknown, log(1+vol/mc), the hour's share (%s)" % x)
    check(FC.forecast({"ageH": 3, "c1": 2}, ref_of([[0] * 7 + [1.0, 0, 0, 0, 1]])) is None, "too few known numbers: no forecast")
    near = [[1.0, 5.5, 0, 0, None, 1.0, 0.1, 3.0, 0, 1, 1, 1] for _ in range(30)]
    far = [[3.0, 9.0, 200, 200, None, 3.0, 0.9, 0.0, 1, 0, 0, 0] for _ in range(300)]
    ref = ref_of(near + far)
    old_k = FC.K
    FC.K = 30
    try:
        fc = FC.forecast({"ageH": 10.0, "logMc": 5.5, "c1": 0, "c6": 0, "volMc": 9.0, "vol1Share": 0.1}, ref)
    finally:
        FC.K = old_k
    check(fc is not None and fc["n"] == 30 and fc["m1"] == [3.0, 3.0, 3.0],
          "the 30 nearest are the look-alikes, their 1.7 h multiples make the range (%s)" % (fc and fc["m1"]))
    exp3 = (30 + FC.SHRINK * ref["base"]["x3"]) / (30 + FC.SHRINK)
    check(fc is not None and abs(fc["x3"] - exp3) < 1e-9 and fc["x3"] < 1.0, "chances are shrunk toward the average of all rows (%.3f)" % (fc or {}).get("x3", -1))
    check(FC.push_line(fc).startswith("Look-alikes: 3x in 6 h ") and FC.push_line(None) == "", "the push line, and none without a forecast")
    check(FC.pct(0.001) == "under 1%" and FC.pct(0.123) == "12%", "chances as people read them")
    check(not any(w in FC.push_line(fc).lower() for w in ("buy", "safe", "clean", "guaranteed")), "the push line holds no word a notification never says")

    real = FC.load()
    check(isinstance(real, dict) and len(real["rows"]) > 1000 and set(real["base"]) == {"zero", "x2", "x3", "profit"} and real.get("check"),
          "forecast_ref.json loads: %d rows, base and check" % (len(real["rows"]) if real else 0))

    import report, app
    D = {"rec": {"picks": [{"sym": "MOON", "f": {"ageH": 10, "logMc": 5.6, "c1": 5, "c6": 10, "m5": 1, "volMc": 2, "vol1Share": 0.06}}]}}
    html = report.forecast_section(D)
    check("Look-alike forecast: MOON" in html and "display only" in html and "never a promise" in html and "8 of 10" in html,
          "the Pick tab's section: heading, display only, the range and the honest note")
    D2 = {"rec": {"picks": [{"sym": "<b>X</b>", "f": {}}]}}
    h2 = report.forecast_section(D2)
    check("No forecast" in h2 and "<b>X</b>" not in h2, "without the numbers: one line, and a hostile symbol stays text")
    check(report.forecast_section({"rec": {"picks": []}}) == "", "no pick: no section")

    sent = []
    app.notify = lambda kind, title, body, url=None: sent.append((kind, title, body)) or {"sent": 0}
    app.notify_pick({"t": 1, "picks": [dict(D["rec"]["picks"][0], tier="strong", score=50)]})
    app.notify_pick({"t": 1, "picks": [dict(D["rec"]["picks"][0], tier="watch")]})
    app.notify_pick({"t": 1, "picks": [{"sym": "P1"}]})
    check(len(sent) == 3 and "Look-alikes: 3x in 6 h" in sent[0][2] and sent[0][2].endswith("Paper trading only, nothing is bought for real."),
          "the pick notification carries the look-alike line (%r)" % (sent[0][2] if sent else None))
    check("Look-alikes" not in sent[1][2] and "Look-alikes" not in sent[2][2], "a watch-only coin and a pick without numbers get no line")
    print("\n%s" % ("FORECAST ALL PASS" if not FAILS else "FORECAST %d FAILED" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
