#!/usr/bin/env python3
"""selftest_fresh.py: the Pick account's fresh start of Oct 22 and where the app shows it. Fake money only: the fixtures are hand-made
docs, nothing is fetched.

  F1 memebot.FRESH_AT is the rocket hunter's first round (22 Oct 2026 10:08 UTC); a run from then on moves paperSince there once, keeps the
     rule (no "reset" sale), and keeps the rule's own start as paperRuleSince, which the exit replay reads (peak.context's ruleSince)
  F2 the account curve draws only points counted from the current start (a point from before the fresh start, counted from Oct 11, is
     left out)
  F3 the Pick tab's account block (page_home.pick_account): "Pick account" since the start, the open pick positions as the page's own
     cards, the last sells, how many trades lie before the start (Pick only) and the Radar for comparison; no open position
     says so; report.py puts it on the Pick tab
  F4 the Start tab's two cards say "Pick account" and "Radar account 🚀", each with its start

  python3 selftest_fresh.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  selftest.main: checks(check, SKIPS) after the brain's checks
"""
import datetime as dt, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MIN = 60_000
OLD = 1791655866812          # the v2 rule's start (11 Oct 2026), the account's start before the fresh one


def f1(check):
    import memebot as M, peak as P
    print("== fresh F1: the start moves once, the rule stays")
    at = dt.datetime.fromtimestamp(M.FRESH_AT / 1000, dt.timezone.utc)
    check(at == dt.datetime(2026, 10, 22, 10, 8, tzinfo=dt.timezone.utc), "F1 FRESH_AT is 22 Oct 2026 10:08 UTC (%s)" % at.isoformat())
    src = open(os.path.join(HERE, "memebot.py"), encoding="utf-8").read()
    check("if now >= FRESH_AT and paper_since < FRESH_AT:" in src and "rule_since = paper_since if restart else int(num(state.get(\"paperRuleSince\")) or paper_since)" in src
          and "\"paperSince\": paper_since, \"paperRuleSince\": rule_since, \"paperRule\": PAPER_RULE" in src
          and src.find("rule_since = ") < src.find("if now >= FRESH_AT") < src.find("for pid, p in sorted(pos.items()):\n        left = p[\"_left\"]"),
          "F1 the run moves paperSince to FRESH_AT once (the rule's start kept before it as paperRuleSince), before the exits; the rule is not touched")
    tmp = tempfile.mkdtemp(prefix="mb-fresh-")
    try:
        os.makedirs(os.path.join(tmp, "db", "memebot"))
        json.dump({"paperSince": M.FRESH_AT, "paperRuleSince": OLD}, open(os.path.join(tmp, "db", "memebot", "state.json"), "w"))
        ctx = P.context(tmp)
        json.dump({"paperSince": OLD}, open(os.path.join(tmp, "db", "memebot", "state.json"), "w"))
        ctx0 = P.context(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    xg = open(os.path.join(HERE, "exit_grid.py"), encoding="utf-8").read()
    check(ctx["since"] == M.FRESH_AT and ctx["ruleSince"] == OLD and ctx0["ruleSince"] == OLD == ctx0["since"]
          and 'M.in_account(p, ctx.get("ruleSince") or ctx["since"])' in xg,
          "F1 the exit replay keeps every trade of the rule (peak.context ruleSince = paperRuleSince, else paperSince)")


def f2(check):
    import report as R
    print("== fresh F2: the curve after the fresh start")
    import memebot as M
    t = M.FRESH_AT
    curve = [{"t": t - 60 * MIN, "paper": {"since": OLD, "pnl": -600.0}}, {"t": t + 50 * MIN, "paper": {"since": OLD, "pnl": -601.0}},
             {"t": t + 110 * MIN, "paper": {"since": t, "pnl": 2.0}}, {"t": t + 170 * MIN, "paper": {"since": t, "pnl": 7.1}}]
    html_ = R.paper_curve({"paper": {"since": t, "acct": {"pnl": 7.1}}, "curve": curve})
    rows = re.findall(r"<tr><td>[^<]*</td><td class=\"n\">([^<]*)</td>", html_)
    check(len(rows) == 2 and not any("600" in r or "601" in r for r in rows), "F2 only the points counted from the fresh start (%s)" % rows)
    import page_account as PA
    line = PA.balance_line({"curve": curve}, {"since": t})
    check("starts after two runs" not in line and line.count("<path") >= 1, "F2 the Archiv balance line draws the two new points")


def stub_r():
    import report as R

    class S:
        local = staticmethod(R.local)
        hold_card = staticmethod(lambda r, now: '<details class="card pos hold"><summary>%s</summary></details>' % r["p"]["sym"])
    return S


def f3(check):
    import memebot as M, page_home as PH
    print("== fresh F3: the Pick tab's account block")
    now, t = M.FRESH_AT + 600 * MIN, M.FRESH_AT
    tmp = tempfile.mkdtemp(prefix="mb-fresh-")
    try:
        os.makedirs(os.path.join(tmp, "db", "memebot"))
        json.dump({"v": 1, "t": now, "book": {"open": {}, "closed": [], "summary": {"trades": 0, "open": 0, "eur": 0, "openEur": 0}}, "top": [], "cut": 0.07},
                  open(os.path.join(tmp, "db", "memebot", "rocket.json"), "w"))
        rows = [{"p": {"sym": "OPEN1", "grp": "hold"}, "sym": "OPEN1", "grp": "hold", "open": True, "pnl": -0.99, "ticket": 50.0, "back": 0.0, "t": now - 60 * MIN, "status": []},
                {"p": {"sym": "WIN"}, "sym": "WIN", "grp": "hold", "open": False, "pnl": 13.36, "pct": 0.267, "ticket": 50.0, "back": 63.36, "t": t + 60 * MIN,
                 "exitT": now - 30 * MIN, "status": [{"why": "time"}]},
                {"p": {"sym": "LOSS"}, "sym": "LOSS", "grp": "hold", "open": False, "pnl": -16.43, "pct": -0.329, "ticket": 50.0, "back": 33.57, "t": t + 90 * MIN,
                 "exitT": now - 20 * MIN, "status": [{"why": "stop"}]},
                {"p": {"sym": "YNG"}, "sym": "YNG", "grp": "young", "open": False, "pnl": -3.0, "ticket": 3.0, "back": 0.0, "t": t + 5 * MIN, "exitT": now, "status": []}]
        D = {"now": now, "dir": tmp, "paper": {"since": t, "acct2": {"rows": rows}, "old": [{"p": {"grp": "hold"}}] * 3 + [{"p": {"grp": "young"}}] * 5},
             "open": [{"p": {"sym": "OPEN1", "grp": "hold", "t": now - 60 * MIN}}, {"p": {"sym": "OLDY", "grp": "young", "t": now}}]}
        S = stub_r()
        h = PH.pick_account(D, S).replace("\xa0", " ")
        D0 = dict(D, open=[], paper=dict(D["paper"], acct2={"rows": rows[1:]}))
        h0 = PH.pick_account(D0, S).replace("\xa0", " ")
        cards = (PH.acct_card("pick", "PICK", "Pick account", PH.pick_book(D), "x", since=PH.since_words(S, t))
                 + PH.acct_card("rad", "RADAR", "Radar account 🚀", PH.rocket_book(PH.rocket_doc(D)), "x", live=True, since=PH.since_words(S, M.FRESH_AT)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check("<h3>Pick account</h3>" in h and "since Oct 22, 12:08" in h and "50 € per buy" in h and "−4.06 €" in h,
          "F3 the head: Pick account since Oct 22, 12:08, the balance of the pick trades only (the new launch left out)")
    check("Open positions (1)" in h and h.count('<details class="card pos hold">') == 1 and "OPEN1" in h and "OLDY" not in h,
          "F3 the open pick positions as the page's cards (a new launch not among them)")
    sold = re.findall(r'<li class="(\w*)"><b>([^<]*)</b><span>([^<]*)</span><em>([^<]*)</em></li>', h)
    check([s[1] for s in sold] == ["LOSS", "WIN"] and "stop −30%" in sold[0][2] and "−33%" in sold[0][2] and sold[0][0] == "bad" and sold[1][3] == "+13.36 €"
          and "after 6 h" in sold[1][2], "F3 the last sells, newest first (%s)" % sold)
    check("The trades before the start (3)" in h and "For comparison, Radar 🚀: <b class=\"\">0.00 €</b>" in h, "F3 the trades before the start (Pick only) and the Radar")
    check("Open positions (0)" in h0 and "None right now" in h0, "F3 no open position says so")
    rp = open(os.path.join(HERE, "report.py"), encoding="utf-8").read()
    i = rp.find("pane_pick = (")
    check(i > 0 and rp.find("PH.pick_account(D, sys.modules[__name__])", i) - i < 200, "F3 report.py puts the block on the Pick tab, under the scan strip")
    check("Pick account" in cards and "Radar account 🚀" in cards and cards.count("since Oct 22, 12:08") == 2 and "der sichere" not in cards,
          "F4 the Start cards: Pick account and Radar account 🚀, both since Oct 22, 12:08")


def checks(check, skips=None):
    f1(check)
    f2(check)
    f3(check)


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
