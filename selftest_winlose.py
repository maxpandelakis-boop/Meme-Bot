#!/usr/bin/env python3
"""selftest_winlose.py: the winner/loser study's page block (page_winlose.py) and its place in the page (fake money only).

  python3 selftest_winlose.py

Checks: W1 no file and a broken file give a short note, no error; W2 the real winlose.json renders the verdict (nothing switched on),
both lists and the method, with no script; W3 made-up text is escaped; W4 report.py puts the block in the Pick tab's Details."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import page_winlose as PW

FAILS = []


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def main():
    tmp = tempfile.mkdtemp(prefix="memebot-winlose-")
    bad = os.path.join(tmp, "bad.json")
    open(bad, "w").write("{not json")
    a, b = PW.section(os.path.join(tmp, "none.json")), PW.section(bad)
    check("No study file" in a and "No study file" in b, "W1 no file / a broken file: a short note")
    h = PW.section()
    check("nothing switched on" in h and "Big move, either way" in h and "Which way" in h and "ⓘ how" in h and "<script" not in h
          and "rocket hunter" in h and "few losers" in h and "together" in h,
          "W2 the real file: verdict, both lists, all signals together, the variants, method, no script")
    doc = json.load(open(PW.PATH))
    check(doc["score"]["verdict"] == "fails", "W2 the file records the failed pre-registered test")
    doc["move"][0]["label"] = "<img src=x onerror=alert(1)>"
    doc["period"] = "<b>x</b>"
    p = os.path.join(tmp, "x.json")
    json.dump(doc, open(p, "w"))
    h = PW.section(p)
    check("<img" not in h and "&lt;img" in h and "<b>x</b>" not in h, "W3 made-up text is escaped")
    import report as R
    blk = R.winlose_block()
    src = open(os.path.join(HERE, "report.py")).read()
    check("Winners vs losers" in blk and 'safe("winners vs losers", winlose_block)' in src, "W4 report.py shows the block in Details")
    print("\n%d failed" % len(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
