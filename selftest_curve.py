#!/usr/bin/env python3
"""selftest_curve.py: the curve watch (curve_watch.py; its wiring in launch_radar.py and radar_src.py; its push switch in radar_curve.json
and app.py). Fake money only; nothing here reaches out: pump.fun, RugCheck, swap-api and the RPC answer from selftest_radar's local mock,
extended with coins still on their curve, and git pushes go to a local bare remote.

  python3 selftest_curve.py        runs the checks on their own (PASS/FAIL per check, "CURVE ALL PASS" at the end)
  checks(check)                    the same from selftest.py's main

C1 progress (the curve's constants, units, sanity), C2 pump.fun rows, C3 calls (crossings, late coins, one per threshold), C4 momentum,
C5 trades (the feed's events: units, pool trades, the creator selling, the hour's peak), C6 calibration, C7 outcomes and the paper
result, C8 the variant table, the greens and radar.json's block, C9 the verdict (traps.py's flags and chips), C10 storage (merge, prune,
JSON), C11 the push switch (off by default, on for one variant, never a trap, once per coin, the hourly cap), C12 the wiring against the
mock (the list, the quick checks and their budgets, the values, radar-data and its guard), C13 fail-open, C14 the push's words (app.curve_words)
and the switch end to end (nothing reaches app.notify while it is off), C15 the watch's own client (nothing it hears blocks a host for the
rounds), C16 stored curve docs in another shape (repaired or left out, counted alike by the guard; the radar's own pushes never stop),
C17 judging the calls (late verdicts at their own price, the greens' rules, unseen hours, the calibration both ways, unbroken trades).
"""
import json, math, os, re, shutil, sys, tempfile, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import curve_watch as CW          # noqa: E402

MIN, H = 60_000, 3_600_000
T00 = 1791892800000               # selftest_radar.T0: 2026-10-13 12:00 UTC
SOL = 150.0
ADVICE = re.compile(r"\b(buy|buys|buying|safe|safety|clean|guaranteed)\b", re.I)


def sr():
    import selftest_radar as SR
    return SR


def mint(i, suffix="pump"):
    return sr().addr(9000 + i, suffix)


def vt_of(p):
    return CW.VT0 - CW.SELL * p / 100.0


def row(a, p, t0, raw=True, **kw):
    """A pump.fun curve-list row at p % sold as of t0 (virtual token reserves in raw units, as the list sends them), minted 30 minutes
    before selftest_radar's T0."""
    vt = vt_of(p)
    mc = CW.K * CW.SUPPLY / (vt * vt)
    r = {"mint": a, "symbol": "C%d" % (int(p) % 97), "name": "Curve Coin", "virtual_token_reserves": vt * (1e6 if raw else 1.0), "market_cap": mc,
         "usd_market_cap": mc * SOL, "complete": False, "created_timestamp": T00 - 30 * MIN, "creator": mint(500, ""), "twitter": "https://x.com/curvecoin",
         "telegram": "https://t.me/curve", "website": None, "last_trade_timestamp": t0, "bonding_curve": mint(600, ""), "associated_bonding_curve": mint(601, "")}
    r.update(kw)
    return r


def trade(a, t, p, side="buy", who=None, pool="pump", mcs=True, units="tokens"):
    """A trade event as radar_feed hands it over, at p % sold after the trade."""
    vt = vt_of(p)
    vs = CW.K / vt
    ev = {"mint": a, "t": int(t), "side": side, "sol": 0.5, "tok": 1e6, "vsol": vs, "vtok": vt, "mcs": vs / vt * CW.SUPPLY if mcs else None, "who": who, "pool": pool}
    if units == "raw":
        ev["vsol"], ev["vtok"] = vs * 1e9, vt * 1e6
    return ev


def checks(check):
    import selftest_radar as SR
    T, P, _ = SR.modules()
    T0 = SR.T0
    tmp = tempfile.mkdtemp(prefix="memebot-curve-")
    try:
        c1_progress(check)
        c2_rows(check, T0)
        c3_calls(check, T0)
        c4_momentum(check, T0)
        c5_trades(check, T0)
        c6_calib(check, T0)
        c7_outcomes(check, T0)
        c8_table(check, T0)
        c9_verdict(check, T)
        c10_storage(check, T0)
        c11_push(check, T, P, T0, tmp)
        c12_wiring(check, T, P, T0, tmp)
        c13_failopen(check, T, P, T0, tmp)
        c14_words(check, T, P, T0, tmp)
        c15_hosts(check, T, P, T0, tmp)
        c16_stored(check, T, P, T0, tmp)
        c17_judging(check, T, T0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c1_progress(check):
    print("== curve C1: progress on pump.fun's curve")
    end = CW.mc_of_prog(100)
    check(abs(CW.MC_END - 410.88) < 0.05 and abs(end - CW.MC_END) < 1e-6 and abs(CW.mc_of_prog(0) - 27.96) < 0.01 and abs(CW.mc_of_prog(75) - 140.78) < 0.01,
          "the constants: 1,073,000,000 virtual tokens, 793,100,000 to sell, 30 virtual SOL: market cap %.2f SOL at the start, %.2f at 75 %%, %.1f at "
          "the end (the curve's 85 SOL of real money)" % (CW.mc_of_prog(0), CW.mc_of_prog(75), CW.MC_END))
    got = {p: (round(CW.prog_vt(vt_of(p)), 6), round(CW.prog_vt(vt_of(p) * 1e6), 6), round(CW.prog_rt(CW.SELL * (1 - p / 100.0) * 1e6), 6), round(CW.prog_mc(CW.mc_of_prog(p)), 6))
           for p in (0, 30, 60, 75, 90, 100)}
    check(all(all(abs(x - p) < 1e-6 for x in v) for p, v in got.items()),
          "progress from the virtual token reserves (tokens or raw units), the real reserves left and the market cap in SOL agree at 0-100 %")
    bad = [CW.prog_vt(1.0), CW.prog_vt(0), CW.prog_vt(-5), CW.prog_vt("x"), CW.prog_mc(1e9), CW.prog_mc(0), CW.prog_vt(True), CW.prog_vt(float("nan")), CW.prog_vt(2e9)]
    check(bad == [None] * len(bad) and CW.prog_vt(vt_of(101.5)) == 100.0 and CW.prog_vt(vt_of(-1.5)) == 0.0,
          "an implausible reading (a wrong unit or constant: more than 2 points outside 0-100 %, zero, negative, text, NaN) is unknown, never 0; "
          "up to 2 points outside is clamped")
    left = CW.curve_left(75)
    check(abs(left - (0.25 * CW.SELL + 206_900_000)) < 1 and abs(CW.curve_left(100) - 206_900_000) < 1,
          "the curve's own holding at 75 %%: %.0fM tokens (the rest to sell plus the pool's 206.9M), the account pump.fun lists as a holder" % (left / 1e6))


def c2_rows(check, T0):
    print("== curve C2: pump.fun rows")
    a = mint(1)
    f = CW.row_facts(row(a, 62.5, T0))
    f2 = CW.row_facts(dict(row(a, 62.5, T0), virtual_token_reserves=None))
    f3 = CW.row_facts(dict(row(a, 62.5, T0), virtual_token_reserves=None, real_token_reserves=CW.SELL * 0.375 * 1e6, market_cap=None))
    f4 = CW.row_facts(dict(row(a, 62.5, T0), virtual_token_reserves=None, market_cap=None), sol=SOL)
    check(abs(f["prog"] - 62.5) < 1e-6 and abs(f2["prog"] - 62.5) < 1e-6 and abs(f3["prog"] - 62.5) < 1e-6 and abs(f4["prog"] - 62.5) < 1e-4
          and abs(f["sol"] - SOL) < 1e-9 and f["tm"] == T0 - 30 * MIN and f["soc"] == 2 and f["x"] == "https://x.com/curvecoin" and f["curve"] == [mint(600, ""), mint(601, "")],
          "a list row: progress from the virtual reserves, else the real reserves, the market cap in SOL, or the USD market cap at the SOL price; "
          "the row's own USD per SOL, the mint time, 2 links, the X link and the curve's accounts")
    bad = [CW.row_facts(x) for x in (None, [], {"mint": "0OIl" * 11}, {"mint": a + "\n"}, {"symbol": "X"})]
    odd = CW.row_facts(dict(row(a, 50, T0), twitter="https://evil.example/x", symbol="AB‮CD​" + "Z" * 40, creator="nope"))
    check(bad == [None] * 5 and odd["x"] == "" and odd["sym"] == "ABCD" + "Z" * 20 and odd["creator"] is None,
          "a row without a base58 mint is skipped; a link that is not X is no X link; a symbol loses its bidi and zero-width marks (24 characters); "
          "a creator that is no address is none")


def book_with(a, t0, p0, **kw):
    B = CW.Book()
    B.rows([row(a, p0, t0, **kw)], t0)
    return B


def c3_calls(check, T0):
    print("== curve C3: calls at 60, 75 and 90 % (the first crossing, one per threshold)")
    a, b, c, d = mint(10), mint(11), mint(12), mint(13)
    B = CW.Book()
    B.rows([row(a, 55, T0), row(b, 80, T0), row(c, 59, T0), row(d, 40, T0)], T0)
    new1 = B.rows([row(a, 61, T0 + 30_000), row(b, 81, T0 + 30_000), row(c, 92, T0 + 30_000), row(d, 40, T0 + 30_000)], T0 + 30_000)
    calls1 = [(m, thr) for m in (a, b, c, d) for thr in CW.THRESHOLDS if B.call(m, thr)]
    ca = B.call(a, 60)
    check(new1 == 4 and B.call(a, 60) and not B.call(a, 75) and not B.call(b, 60) and not B.call(b, 75) and B.coins[b]["above"] == {60: T0, 75: T0}
          and all(B.call(c, thr) for thr in CW.THRESHOLDS) and not any(B.call(d, thr) for thr in CW.THRESHOLDS) and B.n["late"] == 0,
          "a reading under 60 %% then one over it is a 60 %% call; a coin first seen at 80 %% is past 60 and 75 (no call; in the book's first rows "
          "not counted as a missed call: it may have passed them long ago); a jump from 59 to 92 %% crosses all three at once (%d calls)" % len(calls1))
    check(ca["t"] == T0 + 30_000 and ca["prog"] == 61.0 and ca["via"] == "list" and ca["px"] == CW.sig(CW.mc_of_prog(61) / CW.SUPPLY) and abs(ca["mcs"] - CW.mc_of_prog(61)) < 0.01
          and ca["mcu"] == round(ca["mcs"] * SOL) and ca["sol"] == SOL and ca["age"] == 30.5 and ca["v"] == "unknown" and ca["mom"] is None and ca["out"] == {},
          "a call holds its time, progress, price (SOL per token), market cap in SOL and USD, minutes since the mint, its verdict (none yet: unknown) "
          "and momentum (unknown from two list readings)")
    B.rows([row(a, 58, T0 + 60_000)], T0 + 60_000)
    B.rows([row(a, 63, T0 + 90_000)], T0 + 90_000)
    check(B.call(a, 60) is ca and B.call(a, 60)["t"] == T0 + 30_000 and B.n["calls"] == 4,
          "back under 60 % and over it again: still the first crossing's record (one record per coin per threshold)")
    e = mint(14)
    B.rows([row(e, 50, T0)], T0)
    B.rows([row(e, 70, T0 + 11 * MIN)], T0 + 11 * MIN)
    f = mint(15)
    B.rows([row(f, 50, T0)], T0)
    B.rows([row(f, 50, T0 + 2 * MIN, complete=True)], T0 + 2 * MIN)
    B.rows([row(f, 70, T0 + 3 * MIN)], T0 + 3 * MIN)
    check(not B.call(e, 60) and B.coins[e]["above"].get(60) == T0 + 11 * MIN and B.coins[f]["grad"] == T0 + 2 * MIN and not B.call(f, 60)
          and B.n["late"] == 1,
          "a reading under the threshold more than 10 minutes before the one over it is no crossing (a missed call); a coin the list calls complete "
          "has graduated and is not called after")
    B.polled(T0 + 4 * MIN)
    B.polled(T0 + 4 * MIN)
    g, h_ = mint(16), mint(17)
    B.rows([row(g, 77, T0 + 4 * MIN), row(h_, 92, T0 + 4 * MIN, last_trade_timestamp=T0 - 2 * H)], T0 + 4 * MIN)
    d_ = B.doc(T0 + 5 * MIN, {})
    hour = CW.utc_hour(T0)
    B2 = CW.Book()
    B2.load(hour, json.loads(json.dumps(B.docs[hour])))
    check(B.n["late"] == 3 and d_["late"] == 3 and B.docs[hour]["late"] == 3 and B2.doc(T0 + 5 * MIN, {})["late"] == 3 and B.coins[h_]["above"] == {60: T0 + 4 * MIN, 75: T0 + 4 * MIN, 90: T0 + 4 * MIN},
          "missed calls counted only for coins that could have been called: a trading coin first seen at 77 %% after the run's first polls (60 and "
          "75), the one seen again after a gap (60); a coin with no trade for 2 hours never; kept in the hour doc (48 h, like the calls): %d" % d_["late"])


def c4_momentum(check, T0):
    print("== curve C4: momentum (progress points and buys over sells in the last 5 minutes)")
    a = mint(20)

    def run(steps, gap=10_000, start=40.0, sides=None, follow_at=0):
        B = book_with(a, T0, start)
        out = []
        for i in range(1, steps + 1):
            t = T0 + follow_at + i * gap
            side = (sides(i) if sides else "buy")
            out += B.trade(trade(a, t, start + (75.5 - start) * i / steps, side))
        return B, dict(out)
    B1, c1 = run(36)                                    # 40 -> 75.5 % in 6 minutes, buys only: 75 % crossed at minute ~5.9
    m1 = B1.call(a, 75)
    B2, _ = run(36, sides=lambda i: "buy" if i % 3 == 0 else "sell")
    m2 = B2.call(a, 75)
    B3, _ = run(36, start=70.0)                          # 70 -> 75.5 in 6 minutes: 5.5 points
    m3 = B3.call(a, 75)
    B4 = book_with(a, T0, 74.0)
    B4.trade(trade(a, T0 + 30_000, 74.5))
    B4.trade(trade(a, T0 + 60_000, 75.2))
    m4 = B4.call(a, 75)
    check(m1 and m1["mom"] is True and m1["m5"]["pts"] >= 10 and m1["m5"]["buys"] > 0 and m1["m5"]["sells"] == 0 and m1["via"] == "trade",
          "35 points in 6 minutes, buys only: momentum at the 75 %% crossing (%s)" % m1["m5"])
    check(m2 and m2["mom"] is False and m2["m5"]["buys"] < m2["m5"]["sells"] and m2["m5"]["pts"] >= CW.MOM_PTS and m3 and m3["mom"] is False
          and m3["m5"]["pts"] < CW.MOM_PTS and m4 and m4["mom"] is None and m4["m5"] == {"pts": None, "buys": None, "sells": None},
          "rising fast on more sells than buys: no momentum (%s); 5.5 points in 6 minutes: no momentum (%s); a coin followed for one minute: "
          "momentum unknown, never yes (%s)" % (m2["m5"], m3["m5"]["pts"], m4["m5"]))
    B5 = book_with(a, T0, 50.0)
    for i in range(1, 50):
        B5.trade(trade(a, T0 + i * 10_000, 50.0 + i * 0.3, "buy"))
    m5 = B5.momentum(B5.coins[a], T0 + 49 * 10_000)
    check(abs(m5["pts"] - (64.7 - 55.7)) < 0.01 and m5["buys"] == 31,
          "the window is the last 5 minutes: the gain from the last reading at or before its start (%s points), the buys inside it (%s)" % (m5["pts"], m5["buys"]))


def c5_trades(check, T0):
    print("== curve C5: the feed's trades (units, pool trades, the creator selling, the hour's peak)")
    a = mint(30)
    cr = mint(500, "")
    B = book_with(a, T0, 59.0)
    B.trade(trade(a, T0 + 10_000, 59.5, units="raw", mcs=False))
    p_raw = B.coins[a]["p"]
    B.trade(trade(a, T0 + 20_000, 59.6, mcs=False))
    px = B.coins[a]["px"]
    B.trade(trade(a, T0 + 25_000, 99.0, pool="pump-amm"))
    B.trade(trade(mint(31), T0 + 25_000, 99.0))
    check(abs(p_raw - 59.5) < 1e-6 and abs(px - CW.mc_of_prog(59.6) / CW.SUPPLY) < 1e-15 and abs(B.coins[a]["p"] - 59.6) < 1e-6 and mint(31) not in B.coins
          and B.n["trades"] == 3,
          "a trade's progress from its virtual reserves (tokens, or raw units and lamports), its market cap from them when marketCapSol is missing; "
          "a trade on the pool (pump-amm) is no curve reading; a coin the book does not hold is ignored")
    B.trade(trade(a, T0 + 30_000, 60.5, side="sell", who=mint(77, "")))
    s0 = B.coins[a]["csold"]
    B.trade(trade(a, T0 + 40_000, 61.0, side="buy", who=cr))
    s1 = B.coins[a]["csold"]
    B.trade(trade(a, T0 + 50_000, 60.8, side="sell", who=cr))
    cl = B.call(a, 60)
    check(s0 is None and s1 is None and B.coins[a]["csold"] is True and cl and cl["via"] == "trade" and cl["t"] == T0 + 30_000,
          "the creator selling on the curve is noted (creator_sold); another wallet's sale or the creator's buy is not; the 60 % call comes at the "
          "crossing trade's receipt time")
    for i, p in enumerate((70.0, 80.0, 65.0)):
        B.trade(trade(a, T0 + (2 + i) * MIN, p))
    B.trade(trade(a, cl["t"] + CW.VALUE_MS + MIN, 99.0))
    hi = cl["hi"]
    check(abs(hi - CW.mc_of_prog(80) / CW.mc_of_prog(60.5)) < 1e-3 and B.vtrack[(a, 60)]["after"][0] == cl["t"] + CW.VALUE_MS + MIN
          and abs(B.vtrack[(a, 60)]["last"][1] - CW.mc_of_prog(65) / CW.SUPPLY) < 1e-15,
          "an open call's peak within its hour follows the trades (%.3fx at 80 %%, not the 99 %% trade after the hour); the last price before its "
          "hour and the first after are kept for its value" % hi)


def c6_calib(check, T0):
    print("== curve C6: calibration (the last trade before each graduation)")
    B = CW.Book()
    for i in range(6):
        a = mint(40 + i)
        B.rows([row(a, 50, T0)], T0)
        B.trade(trade(a, T0 + MIN, 100.0 if i % 2 else 99.0))
        B.migrate(a, T0 + MIN + 20_000, "feed")
    cal_ok, sc_ok = B.calib(), B.scale
    B2, scales = CW.Book(), []
    for i in range(6):
        a = mint(50 + i)
        B2.rows([row(a, 50, T0)], T0)
        B2.trade(trade(a, T0 + MIN, 80.0))
        if i == 5:
            B2.migrate(a, T0 + 5 * MIN, "feed")            # the last trade 4 minutes before: no sample
        else:
            B2.migrate(a, T0 + MIN + 5_000, "feed")
        scales.append(B2.scale)
    a6 = mint(56)
    B2.rows([row(a6, 50, T0)], T0)
    B2.trade(trade(a6, T0 + MIN, 80.0))
    B2.migrate(a6, T0 + MIN + 5_000, "feed")
    a7 = mint(57)
    B2.rows([row(a7, 50, T0)], T0)
    B2.trade(trade(a7, T0 + 2 * MIN, 60.0))
    a8 = mint(58)
    B2.rows([row(a8, 40, T0)], T0)
    B2.rows([row(a8, 50, T0 + MIN, complete=True)], T0 + MIN)
    check(cal_ok["n"] == 6 and cal_ok["prog"] == 99.5 and sc_ok == 1.0 and abs(cal_ok["mcSol"] - CW.mc_of_prog(99.5)) < 0.5 and cal_ok["expect"] == 410.9,
          "6 graduations whose last trade read 99-100 %%: the median %s %%, market cap %s SOL (expected %s), no correction" % (cal_ok["prog"], cal_ok["mcSol"], cal_ok["expect"]))
    check(scales[:4] == [1.0] * 4 and scales[4:] == [1.25, 1.25] and B2.calib()["n"] == 6 and abs(B2.scale - 1.25) < 1e-9 and abs(B2.coins[a7]["p"] - 75.0) < 1e-6
          and B2.coins[a8]["grad"] == T0 + MIN,
          "constants off (the last trades read 80 %%): 4 samples change nothing, the 5th applies x%.2f (a graduation 4 minutes after its last trade "
          "and a list graduation give no sample); a later 60 %% reading counts as 75 %%" % B2.scale)
    B3 = CW.Book()
    for i in range(6):
        a = mint(60 + i)
        B3.rows([row(a, 50, T0)], T0)
        B3.trade(trade(a, T0 + MIN, 30.0))
        B3.migrate(a, T0 + MIN + 1000, "feed")
    check(B3.scale == 1.5, "a wildly wrong reading is corrected by 1.5x at most (the median 30 %% would ask for %.2fx): the doc shows it" % (100 / 30.0))


def c7_outcomes(check, T0):
    print("== curve C7: outcomes and the paper result")
    p1 = CW.paper(1.0)
    exp1 = round(((CW.TICKET - 0.10) * (1 / 1.05) - 0.10) - CW.TICKET, 2)
    check(p1 == exp1 == -0.34 and CW.paper(0.0) == -3.0 and CW.paper(None) is None and CW.paper(2.0) == round(((CW.TICKET - 0.10) * (2 / 1.05) - 0.10) - CW.TICKET, 2)
          and CW.paper(-1) == -3.0,
          "the paper result: %g EUR in at the call price plus %d %% slippage, the paper fees (1 %%, at least 0.10 a trade): %+.2f at 1x, %+.2f at 2x, -3.00 "
          "for a rug, none without a value" % (CW.TICKET, CW.SLIP * 100, p1, CW.paper(2.0)))
    a, b, c, d, e = (mint(70 + i) for i in range(5))
    B = CW.Book()
    for m in (a, b, c, d, e):
        B.rows([row(m, 58, T0)], T0)
        B.rows([row(m, 61, T0 + MIN)], T0 + MIN)
    B.set_follow([a, b, c, d, e], T0)
    B.trade(trade(a, T0 + 8 * MIN, 70.0))
    B.migrate(a, T0 + 9 * MIN, "feed")
    ca = B.call(a, 60)
    check(ca["out"]["grad"] == T0 + 9 * MIN and ca["out"]["gradMin"] == 8.0 and ca["out"]["gradVia"] == "feed"
          and abs(ca["out"]["gx"] - CW.mc_of_prog(70) / CW.mc_of_prog(61)) < 1e-3,
          "a graduation 8 minutes after the call: its time, minutes and the price at it (the last curve trade: %.2fx the call price)" % ca["out"]["gx"])
    T_ = T0 + MIN + CW.VALUE_MS
    due0 = B.value_due(T_ - 1)
    due = dict(((m, thr), k) for m, thr, k in B.value_due(T_))
    check(due0 == [] and due == {(a, 60): "pool", (b, 60): "curve", (c, 60): "curve", (d, 60): "curve", (e, 60): "curve"},
          "the value is due 60 minutes after the call: the pool's price for a coin that graduated by then, the curve's for the rest")
    px0 = ca["px"]
    B.set_value(a, 60, "pool", T_, px=px0 * SOL * 1.6, liq=40_000.0, pool_pts=[(T0 + 20 * MIN, px0 * SOL * 2.4), (T_ + MIN, px0 * SOL * 9)])
    o = ca["out"]
    check(o["x60"] == 1.6 and o["how"] == "pool" and o["peak"] == 2.4 and o["x2"] is True and o["rug"] is False and o["eur"] == CW.paper(1.6),
          "a pool at 1.6x the call price (USD at the call's SOL price): peak 2.4x from the radar's pool prices inside the hour (not the 9x after it), "
          "doubled, paper %+.2f" % o["eur"])
    B.set_value(b, 60, "pool", T_, px=B.call(b, 60)["px"] * SOL * 3, liq=600.0)
    B.set_value(c, 60, "gone", T_)
    v = B.curve_value(d, 60, T_, True)
    B.set_value(d, 60, "curve", v[0], px=v[1])
    v_e = B.curve_value(e, 60, T_, False)
    B.set_value(e, 60, "curve", T_, px=CW.mc_of_prog(3.0) / CW.SUPPLY)
    ob, oc, od, oe = (B.call(m, 60)["out"] for m in (b, c, d, e))
    check(ob["x60"] == 0.0 and ob["how"] == "dead" and ob["rug"] is True and ob["eur"] == -3.0 and oc["x60"] == 0.0 and oc["how"] == "gone" and oc["rug"]
          and od["x60"] == 1.0 and od["how"] == "curve" and od["rug"] is False and v_e is None and oe["how"] == "dead" and oe["rug"] is True
          and oe["x2"] is False and abs(oe["x60"] - CW.mc_of_prog(3) / CW.mc_of_prog(61)) < 1e-3 and oe["eur"] == CW.paper(oe["x60"]),
          "a pool under $1,000 of liquidity is dead (0, a rug), no pair and no coin is gone (0, a rug); a coin still followed and quiet keeps the call "
          "price on its curve (1x); one not followed needs a coin fetch; a curve sold back under 5 %% is dead, a rug by the greens' rules, its "
          "paper result at its curve price (%.2fx: the curve buys back, so 0.1x itself never happens on a curve)" % oe["x60"])
    f = mint(80)
    B.rows([row(f, 58, T0)], T0)
    B.rows([row(f, 61, T0 + MIN)], T0 + MIN)
    B.call(f, 60)["sol"] = None
    B.sols.clear()
    none_sol = B.set_value(f, 60, "pool", T_, px=1e-5, liq=9_000.0)
    B.value_due(T_ + CW.SETTLE_LATE_MS + 1)
    of = B.call(f, 60)["out"]
    check(none_sol is None and of.get("miss") is True and of.get("x60") is None and B.value_due(T_ + 2 * H) == [],
          "no SOL price to convert a pool's USD price: not settled; 20 minutes past its time without a value it is missing (never 0) and asked no more")


def c8_table(check, T0):
    print("== curve C8: the variant table, the greens of the same hours, radar.json's block")
    B = CW.Book()
    specs = [(60, False, "ok", 2.0, True), (60, True, "ok", 0.5, False), (75, True, "risky", 0.0, True), (75, True, "ok", 1.2, True),
             (90, None, "trap", 1.1, True), (75, False, "unknown", None, False)]
    hour = CW.utc_hour(T0)
    B.polled(T0)
    for i, (thr, mom, v, x, grad) in enumerate(specs):
        a = mint(100 + i)
        doc = B.hour_doc(T0)
        cl = {"t": T0 + i * MIN, "thr": thr, "via": "trade", "prog": thr + 0.5, "px": 1e-7, "mcs": 100.0, "sol": SOL, "mcu": 15000, "age": 20.0,
              "m5": {"pts": 12.0, "buys": 9, "sells": 3}, "mom": mom, "v": v, "chips": [], "hi": 1.0, "out": {}, "push": None}
        if grad:
            cl["out"].update(grad=T0 + (i + 5) * MIN, gradMin=float(5 + i))
        if x is not None:
            cl["out"].update(x60=x, rug=x <= 0.1, x2=x >= 2.0, eur=CW.paper(x), how="pool")
        else:
            cl["out"]["miss"] = True
        doc["coins"][a] = {"mint": a, "sym": "V%d" % i, "calls": {str(thr): cl}}
        B.call_hour[a] = hour
    rows = {r["id"]: r for r in B.variants()}
    r60, r60m, r75m, r75 = rows["60"], rows["60m"], rows["75m"], rows["75"]
    check(list(rows) == ["60", "60m", "75", "75m", "90", "90m"] and r60["n"] == 2 and r60m["n"] == 1 and r75m["n"] == 2 and r75["n"] == 3 and rows["90m"]["n"] == 0
          and rows["90"]["n"] == 1 and r75["nS"] == 2 and r75["miss"] == 1 and r75m["rug"] == 0.5 and r75m["x2"] == 0.0 and r75m["eur"] == round((CW.paper(0.0) + CW.paper(1.2)) / 2, 2)
          and r60["grad"] == 0.5 and r60["gradMin"] == 5.0 and r75["grad"] == 1.0 and r75["unseen"] == 1 and r60["unseen"] == 0 and r75["gradMin"] == 7.5
          and set(r75["by"]) == {"risky", "ok", "unknown"} and r75["by"]["unknown"]["nS"] == 0
          and r75m["by"]["ok"] == {"n": 1, "nS": 1, "rug": 0.0, "x2": 0.0, "eur": CW.paper(1.2)},
          "six variants (60/75/90, each with and without momentum): n, settled, rugged, doubled, paper result, graduated within the hour and its "
          "minutes (over the calls whose hour was seen: a missing value without a graduation seen is unseen, never 'did not graduate'), missing "
          "values left out; the momentum filter keeps only calls whose momentum held (unknown is not yes); the split by verdict")
    recs = [{"good": T0 + 5 * MIN, "goodPx": 1.0, "later": {"60": {"px": 2.5, "liq": 30000}}, "out": {"rug1h": False, "win1h": True}},
            {"good": T0 + 6 * MIN, "goodPx": 1.0, "later": {"60": {"gone": True}}, "out": {"rug1h": True, "win1h": False}},
            {"good": T0 + 7 * MIN, "goodPx": 1.0, "later": {"60": {"px": 0.9, "liq": 500}}, "out": {"rug1h": True, "win1h": False}},
            {"good": T0 + 8 * MIN, "goodPx": 1.0, "later": {}, "out": None},
            {"good": T0 - 3 * H, "goodPx": 1.0, "later": {"60": {"px": 9.0, "liq": 9e4}}, "out": {"rug1h": False, "win1h": True}},
            {"good": None, "px": 1.0}]
    g = CW.greens_stats(recs, B.active_hours())
    check(g == {"n": 4, "nS": 3, "rug": round(2 / 3, 3), "x2": round(1 / 3, 3), "eur": round((CW.paper(2.5) + CW.paper(0) + CW.paper(0)) / 3, 2), "grad": None},
          "the radar's greens of the same hours (first good in a watched UTC hour; one 3 h earlier is left out): %s" % g)
    d = B.doc(T0 + H, {"state": "on", "why": ""}, g)
    raw = json.dumps(d, separators=(",", ":"), allow_nan=False)
    check(d["hours"] == 1 and d["since"] == CW.hour_ms(hour) and d["calls"] == 6 and len(d["recent"]) == 6 and d["recent"][0]["sym"] == "V5" and d["greens"] == g
          and d["slip"] == 0.05 and d["ticket"] == 3.0 and d["thresholds"] == [60, 75, 90] and d["state"] == "on" and len(raw) <= CW.DOC_MAX
          and set(d["recent"][0]) >= {"mint", "sym", "thr", "t", "prog", "mcu", "age", "mom", "pts", "buys", "sells", "v", "chips", "push", "out"},
          "radar.json's block: since, hours, calls, the newest calls first with their outcome, the variants, the greens, ticket and slippage "
          "(%d bytes)" % len(raw))
    for i in range(400):
        a = mint(1000 + i)
        B.hour_doc(T0)["coins"][a] = {"mint": a, "sym": "Z" * 24, "calls": {"60": {"t": T0 + i, "thr": 60, "prog": 60.1, "px": 1e-7, "v": "risky",
                                                                                    "chips": [["warn", "x" * 60]] * 3, "out": {"x60": 1.0, "eur": -0.34}}}}
        B.call_hour[a] = hour
    d2 = B.doc(T0 + H, {"state": "on"}, g)
    check(len(json.dumps(d2, separators=(",", ":"))) <= CW.DOC_MAX and len(d2["recent"]) <= CW.RECENT_N and d2["calls"] == 406,
          "406 calls: the block stays within %d bytes (%d recent)" % (CW.DOC_MAX, len(d2["recent"])))


def c9_verdict(check, T):
    print("== curve C9: the quick checks' verdict (traps.py's flags and chips)")
    W = T.load_weights()

    def S(**kw):
        s = T.blank_signals()
        s.update({"rcReport": True, "rcDanger": [], "rcWarn": [], "cluster": False, "wmChecked": True, "swAvg": None, "rugHolders": 0, "wmState": "ok",
                  "devN": 2, "devDead": 0, "devGrad": 1, "brand": False, "socN": 2, "x": "https://x.com/dog", "xKind": "account", "xUsed": 0, "tweetShared": 0})
        s.update(kw)
        return s
    cases = {"clean run": S(), "brand": S(brand=True), "RugCheck danger": S(rcDanger=["Mutable metadata"]), "rugger wallets": S(rugHolders=3),
             "holder cluster": S(cluster=True), "creator sold": S(creatorSold=True), "serial dev": S(devN=6, devDead=6), "sniped": S(snip30=0.4, snip30N=3),
             "bundle": S(slotN=4, slotPct=0.2), "x copied": S(xUsed=2), "dev wallet young": S(devAgeH=2.0),
             "no report": S(rcReport=None, rcDanger=None), "memory missing": S(wmChecked=False), "no dev history": S(devN=None, devDead=None)}
    got = {k: CW.verdict(T, s, W) for k, s in cases.items()}
    v = {k: x[0] for k, x in got.items()}
    txt = lambda k: " | ".join(t for _, t in got[k][1])
    check(v == {"clean run": "ok", "brand": "trap", "RugCheck danger": "trap", "rugger wallets": "trap", "holder cluster": "risky", "creator sold": "risky",
                "serial dev": "risky", "sniped": "risky", "bundle": "risky", "x copied": "risky", "dev wallet young": "ok", "no report": "unknown",
                "memory missing": "unknown", "no dev history": "unknown"},
          "ok / trap (a hard trap that applies on the curve: brand, RugCheck danger, rugger wallets) / risky (a soft warning or a measured red "
          "flag) / unknown (report, wallet memory or dev history missing): %s" % v)
    check("no rugger wallets" in txt("clean run") and "brand/celebrity name" in txt("brand") and "dev: 6 launches, 6 dead" in txt("serial dev")
          and "RugCheck pending" in txt("no report") and "dev history unknown" in txt("no dev history") and "dev wallet" in txt("dev wallet young")
          and all(len(c) <= 6 for _, c in got.values()) and not any(ADVICE.search(t) for _, c in got.values() for _, t in c),
          "the chips are traps.chips' words (at most 6, never buy, safe or clean): %r" % txt("serial dev"))


def c10_storage(check, T0):
    print("== curve C10: storage (merge, prune 48 h, JSON)")
    a, b = mint(200), mint(201)
    B = CW.Book()
    B.polled(T0)
    B.rows([row(a, 58, T0), row(b, 70, T0)], T0)
    B.rows([row(a, 61, T0 + MIN), row(b, 76, T0 + MIN)], T0 + MIN)
    h = CW.utc_hour(T0)
    doc = json.loads(json.dumps(B.docs[h], allow_nan=False))
    late = json.loads(json.dumps(doc))
    late["coins"][a]["calls"]["60"]["out"] = {"x60": 1.3, "eur": 0.9}
    B2 = CW.Book()
    B2.load(h, doc)
    B2.load(h, late)
    B2.load(h, doc)
    B2.load("2026-10-10T08", {"coins": {"x": "bad"}})
    check(B2.call(a, 60)["out"]["x60"] == 1.3 and B2.call(b, 75) is not None and B2.counts() == {h: 2} and B2.docs[h]["polls"] == 1
          and B2.entry(a)["sym"] == B.entry(a)["sym"] and "2026-10-10T08" not in B2.docs,
          "an hour doc loads and merges per call (the copy that knows more wins, in any order); a malformed entry is skipped (an hour of nothing "
          "else is no hour); counts per hour")
    B2.prune(T0 + 49 * H)
    check(B2.docs == {} and B2.call_hour == {} and B2.counts() == {}, "hour docs older than 48 hours leave the book (and radar-data with it)")


class FeedStub:
    """The live feed's interface the curve watch uses: follow (the coins asked), take_trades, trade_state, state."""

    def __init__(self, shape=True, state="ok", off=None):
        self.asked, self.trades, self.shape, self.st, self.off = [], [], shape, state, off

    def follow(self, mints):
        self.asked.append(list(mints))
        return [] if self.shape is False else list(mints)[:40]

    def take_trades(self):
        out, self.trades = self.trades, []
        return out

    def trade_state(self):
        return {"shape": self.shape, "off": self.off, "want": len(self.asked[-1]) if self.asked else 0, "subbed": 0, "since": time.time() - 30, "last": time.time() - 5 if self.shape else None, "n": 0}

    def take(self):
        return []

    def lines(self):
        return []

    def info(self, m):
        return None

    def state(self):
        return self.st

    def stats(self):
        return {}

    def stop(self, timeout=3.0):
        return True


class CurveSink:
    """The curve notifications the radar sends (a stand-in for app.notify_curve): their words through app.curve_words."""

    def __init__(self):
        self.got = []

    def __call__(self, c):
        import app as A
        title, body = A.curve_words(c)
        self.got.append({"sym": c.get("sym"), "v": c.get("v"), "thr": c.get("thr"), "title": title, "body": body})
        return {"kind": "curve", "sent": 1}


def unit(T, P, tmp, name, now, url=None, remote=None, extra=()):
    import launch_radar as LR
    SR = sr()
    args = ["loop", "--dir", os.path.join(tmp, name), "--clock", "fake", "--now", str(int(now)), "--cache", os.path.join(tmp, name + "-c"), "--no-github"]
    args += (["--mock", url] if url else []) + (["--remote", remote] if remote else []) + list(extra)
    with SR.env(MEMEBOT_RADAR_CURVE=None, MEMEBOT_RADAR_FAST=None, MEMEBOT_RADAR_ADAPTERS=None, SUPABASE_URL=None, SUPABASE_SECRET_KEY=None):
        R = LR.Radar(LR.args_of(args), log=(lambda s_: None), traps=T, peak=P)
    return R


def push_call(B, a, t, thr=60, mom=None, v="ok"):
    """A call made by hand in the book (a coin on the curve, its verdict now v)."""
    B.rows([row(a, thr - 2, t - MIN)], t - MIN)
    B.rows([row(a, thr + 1, t)], t)
    B.coins[a]["chk"] = {"v": v, "chips": [["ok", "no rugger wallets"], ["ok", "RugCheck report"]], "at": t}
    cl = B.call(a, thr)
    cl["mom"], cl["v"] = mom, v
    return cl


def c11_push(check, T, P, T0, tmp):
    import launch_radar as LR
    print("== curve C11: the push switch (radar_curve.json: off by default)")
    SR = sr()
    cfg_repo = LR.curve_cfg(CW)
    raw = json.load(open(os.path.join(HERE, "radar_curve.json"), encoding="utf-8"))
    p_bad = os.path.join(tmp, "bad_curve.json")
    with open(p_bad, "w") as f_:
        json.dump({"curvePush": "80x", "pushVerdicts": ["trap", "risky", "ok", "ok"], "pushPerH": 99}, f_)
    p_on = os.path.join(tmp, "on_curve.json")
    with open(p_on, "w") as f_:
        json.dump({"curvePush": "75m", "pushVerdicts": ["trap"], "pushPerH": 2}, f_)
    texts = [v for v in raw.values() if isinstance(v, str)]
    p_sp = os.path.join(tmp, "spaced_curve.json")
    with open(p_sp, "w") as f_:
        json.dump({"curvePush": " 75m\n"}, f_)
    spaced = LR.curve_cfg(CW, p_sp)["curvePush"]                 # a stray space in the hand-edited switch: the normalised id, as app.notify_curve wants it
    check(raw.get("curvePush", "x") is None and cfg_repo == {"curvePush": None, "pushVerdicts": ["ok"], "pushPerH": 3}
          and LR.curve_cfg(CW, p_bad) == {"curvePush": None, "pushVerdicts": ["risky", "ok"], "pushPerH": 3}
          and LR.curve_cfg(CW, p_on) == {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 2} and LR.curve_cfg(CW, os.path.join(tmp, "none.json"))["curvePush"] is None
          and LR.curve_cfg(None, p_on)["curvePush"] is None and not any(ADVICE.search(t) or "\u2014" in t for t in texts) and spaced == "75m",
          "radar_curve.json ships curvePush null (off); a variant id that is no variant is off, one with a stray space is kept as its plain id "
          "(app.notify_curve takes only that), a trap verdict is never allowed, pushPerH 0-10 (else 3); a missing file or curve_watch.py is off; "
          "its note never says buy, safe or clean")
    now = T0 + 10 * MIN
    R = unit(T, P, tmp, "rdP", now)
    sink = CurveSink()
    R.cnotifier, R.restore_state = sink, "ok"
    R.last_doc = LR.finish_from({}, "running", now, "", "t", None, None, "manual", (0, 24))
    a1, a2, a3, a4 = mint(300), mint(301), mint(302), mint(303)
    push_call(R.curve, a1, now, thr=75, mom=True, v="ok")
    push_call(R.curve, a2, now, thr=75, mom=True, v="trap")
    push_call(R.curve, a3, now, thr=75, mom=False, v="ok")
    push_call(R.curve, a4, now, thr=75, mom=True, v="risky")
    t_k = now + 100_000
    R.curve_push(now, t_k)
    off_sent = list(sink.got)
    R.ccfg = {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 3}
    R.curve_push(now, t_k)
    R.curve_push(now + 1000, t_k)
    on_sent = list(sink.got)
    cp = json.load(open(os.path.join(R.out, "curvepushed.json"))) if os.path.exists(os.path.join(R.out, "curvepushed.json")) else {}
    check(off_sent == [] and [g["sym"] for g in on_sent] == [R.curve.entry(a1)["sym"]] and R.curve.call(a1, 75)["push"] == now and cp.get(a1) == now
          and R.curve.call(a2, 75)["push"] is None and R.curve.call(a3, 75)["push"] is None and R.curve.call(a4, 75)["push"] is None,
          "curvePush null: nothing is sent (%d); curvePush 75m: one push for the 75 %% call with momentum and verdict ok, marked in curvepushed.json "
          "before it went out; never the trap verdict, not the call without momentum, not a risky one (verdicts ok only), never twice" % len(off_sent))
    body = on_sent[0]["body"] if on_sent else ""
    check(on_sent and "still on the pump.fun curve" in body and "paper test, fake money, nothing is bought." in body and "of its curve sold, no pool yet" in on_sent[0]["title"]
          and not ADVICE.search(body + on_sent[0]["title"]) and "\u2014" not in body,
          "its words: %r / %r" % (on_sent[0]["title"] if on_sent else "", body[:140]))
    R.ccfg = {"curvePush": "75m", "pushVerdicts": ["ok", "risky", "unknown"], "pushPerH": 2}
    a5, a6 = mint(304), mint(305)
    push_call(R.curve, a5, now + 2000, thr=75, mom=True, v="unknown")
    push_call(R.curve, a6, now + 3000, thr=75, mom=True, v="ok")
    for i in range(4):
        R.curve_push(now + 4000 + i, t_k)
    capped = [g["sym"] for g in sink.got[len(on_sent):]]
    check(len(capped) == 1 and R.curve.call(a2, 75)["push"] is None and sum(1 for t in R.cpushed.values() if now + 5000 - t < H) == 2,
          "pushPerH 2: one more push this hour (%s), then none; the trap verdict never, whatever the list allows" % capped)
    late = mint(306)
    push_call(R.curve, late, now - 5 * MIN, thr=75, mom=True, v="ok")
    R.ccfg["pushPerH"] = 10
    R.curve_push(now + 10_000, t_k)
    R.restore_state = "failed"
    a7 = mint(307)
    push_call(R.curve, a7, now + 11_000, thr=75, mom=True, v="ok")
    R.curve_push(now + 11_000, t_k)
    R.restore_state = "ok"
    R.cnotifier = None
    with SR.env(SUPABASE_URL=None, SUPABASE_SECRET_KEY=None):
        R.curve_push(now + 12_000, t_k)
    check(R.curve.call(late, 75)["push"] is None and R.curve.call(a7, 75)["push"] is None and a7 not in R.cpushed,
          "no push for a call older than %d s, none while pushed marks are not restored, none without a channel" % (LR.CURVE_PUSH_WAIT_MS // 1000))
    rem = SR.fresh_remote(T, tmp, "cpush", now)
    Rb = unit(T, P, tmp, "rdPb", now, remote=rem)
    Rb.restore()
    sinkb = CurveSink()
    Rb.cnotifier, Rb.ccfg = sinkb, {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 3}
    Rb.last_doc = LR.finish_from({}, "running", now, "", "t", None, None, "manual", (0, 24))
    push_call(Rb.curve, a1, now, thr=75, mom=True, v="ok")
    Rb.git.remote = os.path.join(tmp, "nowhere.git")
    Rb.curve_push(now, t_k)
    failed = (list(sinkb.got), dict(Rb.cpushed))
    Rb.git.remote = rem
    Rb.curve_push(now + 1000, t_k)
    files = SR.branch_files(rem, "radar-data")
    check(failed == ([], {}) and len(sinkb.got) == 1 and json.loads(files.get("curvepushed.json") or b"{}").get(a1) == now + 1000
          and any(p.startswith("db/memecurve/") for p in files),
          "radar-data cannot be written: the mark is taken back and nothing is sent; once it lands, curvepushed.json and the curve's hour docs "
          "are on radar-data before the push goes out")
    Rg = unit(T, P, tmp, "rdPg", now)
    answers = [{"kind": "curve", "sent": 0, "skipped": "rate guard"}, {"kind": "curve", "sent": 1}]
    tried = []
    Rg.cnotifier = lambda c: (tried.append(c["sym"]), answers[min(len(tried), len(answers)) - 1])[1]
    Rg.restore_state, Rg.ccfg = "ok", {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 3}
    Rg.last_doc = LR.finish_from({}, "running", now, "", "t", None, None, "manual", (0, 24))
    a8 = mint(308)
    push_call(Rg.curve, a8, now, thr=75, mom=True, v="ok")
    call_s, send_s = LR.app_budget()
    near = int((LR.PUBLISH_MIN_S + call_s + send_s + LR.PUSH_MARGIN_S) * 1000) - 1000
    Rg.curve_push(now, now + near)                              # the round too close for radar-data's push and the notification's budget
    close = (list(tried), dict(Rg.cpushed))
    Rg.curve_push(now + 1000, t_k)                             # app's rate guard answers
    guard = (list(tried), a8 in Rg.cpushed, Rg.cpush_hold > time.time(), Rg.curve.call(a8, 75)["push"])
    Rg.curve_push(now + 2000, t_k)                             # inside the gap: not tried
    inside = list(tried)
    Rg.cpush_hold = 0.0
    Rg.curve_push(now + 3000, t_k)
    check(close == ([], {}) and guard[0] == [Rg.curve.entry(a8)["sym"]] and guard[1:] == (False, True, None) and inside == guard[0]
          and len(tried) == 2 and Rg.curve.call(a8, 75)["push"] == now + 3000 and a8 in Rg.cpushed,
          "the round %d s away: nothing is marked or sent (radar-data's push and the notification's %.0f s would run into it); app's rate guard "
          "takes the mark back, nothing is tried while its gap lasts, and the call goes out after it within its %d s" % (near // 1000, call_s + send_s,
                                                                                                                       LR.CURVE_PUSH_WAIT_MS // 1000))


class CurveMock:
    """selftest_radar's mock with coins still on their curve: pump.fun's curve list (complete=false, market cap first), coins-v3, the
    dev's launches, the top holders (the curve's own account first, entered at the mint), launch trades, RugCheck reports (a pool risk
    that must not count on the curve). curve: dicts {a, prog, sym, creator, devN, danger, holders, snipe, gone, rc}."""

    def __init__(self, base_coins, curve):
        SR = sr()
        self.SR = SR
        self.base = SR.RadarMock(base_coins)
        self.curve = {c["a"]: c for c in curve}
        self.bad, self.t0 = False, SR.T0
        base = self.base
        orig = base.route

        def route(method, path, query, body):
            got = self.route(method, path, query, body)
            return got if got is not None else orig(method, path, query, body)
        base.route = route

    def crow(self, c):
        r = row(c["a"], c["prog"], self.t0, symbol=c.get("sym", "CRV"), creator=c.get("creator") or mint(500, ""), last_trade_timestamp=c.get("ltt", self.t0))
        r["created_timestamp"] = c.get("mint", self.t0 - 30 * MIN)
        r["complete"] = bool(c.get("done"))
        return r

    def route(self, method, path, query, body):
        q = urllib.parse.parse_qs(query)
        if path == "/frontend-api-v3.pump.fun/coins" and (q.get("complete") or [""])[0] == "false":
            if self.bad:
                return 200, [{"mint": mint(999), "oops": 1}]
            off = int((q.get("offset") or ["0"])[0])
            rows = sorted(self.curve.values(), key=lambda c: -c["prog"])[off:off + 50]
            return 200, [self.crow(c) for c in rows if not c.get("gone")]
        dev = (q.get("creator") or [""])[0]
        if path == "/frontend-api-v3.pump.fun/coins" and dev and any(c.get("creator") == dev for c in self.curve.values()):
            n = next(c.get("devN", 3) for c in self.curve.values() if c.get("creator") == dev)
            return 200, [{"mint": mint(5000 + i + sum(map(ord, dev)) % 1000), "creator": dev, "complete": i == 0, "usd_market_cap": 90_000 if i == 0 else 3_000,
                          "created_timestamp": self.t0 - (i + 2) * H} for i in range(n)]
        m = re.match(r"^/frontend-api-v3\.pump\.fun/coins-v3/([^/]+)$", path)
        if m and m.group(1) in self.curve:
            c = self.curve[m.group(1)]
            return (404, {"error": "not found"}) if c.get("gone") else (200, self.crow(c))
        m = re.match(r"^/(frontend-api-v3|advanced-api-v2)\.pump\.fun/coins/top-holders/([^/]+)$", path)
        if m and m.group(2) in self.curve:
            c = self.curve[m.group(2)]
            t_m = c.get("mint", self.t0 - 30 * MIN)
            hs = [{"address": mint(700, ""), "amount": CW.curve_left(c["prog"]) * 1e6, "enteredAt": t_m, "isBundler": False}]
            for i, w in enumerate(c.get("holders") or [mint(710 + i, "") for i in range(4)]):
                hs.append({"address": w, "amount": (250_000_000.0 if c.get("snipe") and i == 0 else 10_000_000.0) * 1e6,
                           "enteredAt": t_m + (5_000 if c.get("snipe") and i == 0 else 20 * MIN), "isBundler": False})
            return 200, {"topHolders": hs, "totalHolders": 80}
        m = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/report$", path)
        if m and m.group(1) in self.curve:
            c = self.curve[m.group(1)]
            if c.get("rc") == "404":
                return 404, {"error": "not found"}
            if c.get("rc") == "odd":
                return 200, {"mint": c["a"], "note": "another shape"}
            risks = [{"name": "Low Liquidity", "level": "danger"}, {"name": "Large Amount of LP Unlocked", "level": "danger"}] + \
                [{"name": n, "level": "danger"} for n in c.get("danger") or []]
            hold = c.get("holders") or [mint(710 + i, "") for i in range(4)]
            return 200, {"mint": c["a"], "score": 50, "risks": risks, "graphInsidersDetected": 0, "insiderNetworks": None, "creator": c.get("creator"),
                         "topHolders": [{"owner": h, "pct": 3.0, "insider": False} for h in hold], "token": {"supply": 1e15}, "creatorBalance": 0}
        m = re.match(r"^/swap-api\.pump\.fun/v2/coins/([^/]+)/trades$", path)
        if m and m.group(1) in self.curve:
            c = self.curve[m.group(1)]
            t_m = c.get("mint", self.t0 - 30 * MIN)
            rows = [{"timestamp": t_m + i * 1000, "type": "buy", "userAddress": mint(720 + i, ""), "baseAmount": 250_000_000.0 if c.get("snipe") and i == 0 else 30_000_000.0,
                     "slotIndexId": "%012d%010d" % (400_000_000 + i, 1), "program": "pump"} for i in range(3)]
            return 200, {"trades": rows[::-1], "pagination": {"hasMore": False, "limit": 100, "nextCursor": None}}
        return None


def c12_wiring(check, T, P, T0, tmp):
    import launch_radar as LR
    print("== curve C12: the wiring against the mock (the list, the quick checks and their budgets, the values, radar-data)")
    SR = sr()
    rug = SR.RUG_WALLETS
    cur = [{"a": mint(400), "prog": 55.0, "sym": "OKC", "creator": mint(410, ""), "mint": T0 - 8 * MIN, "snipe": False},
           {"a": mint(401), "prog": 70.0, "sym": "RUGC", "creator": mint(411, ""), "holders": rug + [mint(730, "")]},
           {"a": mint(402), "prog": 50.0, "sym": "DEVC", "creator": mint(412, ""), "devN": 6},
           {"a": mint(403), "prog": 48.0, "sym": "NORC", "creator": mint(413, ""), "rc": "404"},
           {"a": mint(404), "prog": 46.0, "sym": "SNIP", "creator": mint(414, ""), "snipe": True, "mint": T0 - 6 * MIN},
           {"a": mint(405), "prog": 20.0, "sym": "LOW", "creator": mint(415, "")},
           {"a": mint(406), "prog": 35.0, "sym": "OLD", "creator": mint(416, ""), "ltt": T0 - 2 * H}]
    cm = CurveMock(list(SR.FIX.values()), cur)
    srv = SR.serve(cm.base)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        R = unit(T, P, tmp, "rdW", T0, url=url)
        cm.base.clock = R.clock.now
        R.wm = {"v": 1, "t": T0 - 30 * MIN, "nCoins": 500, "common": [], "sw": {}, "rug": rug}
        R.live = FeedStub()
        t_k = R.clock.now() + 110_000
        h0 = len(cm.base.heads)
        R.curve_tick(R.clock.now(), t_k)
        heads = cm.base.heads[h0:]
        lst = [h for h in heads if h["path"] == "/frontend-api-v3.pump.fun/coins" and "creator=" not in h["q"]]
        q = urllib.parse.parse_qs(lst[0]["q"]) if lst else {}
        fol = R.live.asked[-1] if R.live.asked else []
        check(len(lst) == 1 and q.get("sort") == ["market_cap"] and q.get("order") == ["DESC"] and q.get("complete") == ["false"] and q.get("limit") == ["50"]
              and set(R.curve.coins) >= {c["a"] for c in cur} and fol == [mint(401), mint(400), mint(402), mint(403), mint(404)] and R.curve.fol.keys() == set(fol)
              and (R.cache["pf"].get(mint(400)) or {}).get("creator") == mint(410, "") and R.curve.docs[CW.utc_hour(R.clock.now())]["polls"] == 1,
              "a tick: pump.fun's curve list (sort=market_cap, order=DESC, complete=false, 50 a page), the candidates in the book, the 30 %%+ coins "
              "with a trade in the last 15 minutes followed best first (%s), their facts in the radar's pump.fun cache for when the pool opens"
              % [R.curve.entry(a) and R.curve.entry(a)["sym"] or a[:4] for a in fol])
        for i in range(40):
            R.curve_check_step(R.clock.now(), t_k)
        heads = cm.base.heads[h0:]
        v = {c["sym"]: (R.curve.coins[c["a"]].get("chk") or {}).get("v") for c in cur}
        chips = {c["sym"]: [t for _, t in (R.curve.coins[c["a"]].get("chk") or {}).get("chips") or []] for c in cur}
        hold_ok = (R.cchk.get(mint(400)) or {}).get("holders") or {}
        hold_sn = (R.cchk.get(mint(404)) or {}).get("holders") or {}
        check(v == {"OKC": "ok", "RUGC": "trap", "DEVC": "risky", "NORC": "unknown", "SNIP": "risky", "LOW": None, "OLD": None},
              "the quick checks against the mock give the verdicts: a clean coin ok, rugger wallets among its RugCheck holders trap, a serial dev "
              "risky, no RugCheck report unknown, a sniped launch risky; under 45 %% or without a trade for 15 minutes nothing is checked (%s)" % v)
        check(hold_ok.get("snip30") == 0.0 and hold_sn.get("snip30") == 0.25 and hold_sn.get("snip30N") == 1 and not any("Liquidity" in t or "LP" in t for t in chips["OKC"])
              and "no rugger wallets" in chips["OKC"] and any("holders from rugged coins" in t for t in chips["RUGC"]),
              "the curve's own account (about %.0f %% of the supply at 55 %%, entered at the mint) is no sniper; a wallet with 25 %% in 5 s is; "
              "RugCheck's pool risks (low liquidity, LP unlocked) do not count before a pool exists: %s" % (100 * CW.curve_left(55) / CW.SUPPLY, chips["OKC"]))
        pf = [h for h in heads if h["path"].startswith("/frontend-api-v3.pump.fun/")]
        kinds = {"dev": [h for h in pf if "creator=" in h["q"] or "user-created-coins" in h["path"]], "holders": [h for h in heads if "/top-holders/" in h["path"]],
                 "rc": [h for h in heads if h["path"].startswith("/api.rugcheck.xyz/")], "rpc": [h for h in heads if h.get("rpc")],
                 "swap": [h for h in heads if h["path"].startswith("/swap-api.pump.fun/")]}
        check(len(pf) <= LR.CURVE_BUDGET["pf"][1] and kinds["rc"] and kinds["rpc"] and len(kinds["swap"]) == 2
              and all(h.get("origin") == "https://pump.fun" for h in kinds["holders"] + kinds["swap"]) and not any(c["a"] in h["path"] for c in cur[5:] for h in heads),
              "within one minute the watch sends at most %d pump.fun frontend requests (%d: the list, dev launches, holders); RugCheck %d, RPC %d, "
              "launch trades only for the 2 coins minted under 15 minutes ago" % (LR.CURVE_BUDGET["pf"][1], len(pf), len(kinds["rc"]), len(kinds["rpc"])))
        h1 = len(cm.base.heads)
        R.curve_at = 0
        R.curve_tick(R.clock.now(), R.clock.now() + LR.CURVE_LEAD_MS - 1000)
        R.curve_check_step(R.clock.now(), R.clock.now() + LR.CURVE_LEAD_MS - 1000)
        check(len(cm.base.heads) == h1, "8 s or less before the next round the watch sends nothing: a round never waits for it")
        # a crossing from the list, its value from the trades followed, a coin fetch, a graduation's pool value from the cycle's DexScreener
        cm.curve[mint(400)]["prog"] = 61.0
        cm.curve[mint(402)]["prog"] = 62.0
        cm.curve[mint(403)]["gone"] = False
        R.clock.wait(R.clock.now() + 31_000)
        now1 = R.clock.now()
        R.cbud.clear()
        R.curve_tick(now1, now1 + 110_000)
        c_ok, c_dev = R.curve.call(mint(400), 60), R.curve.call(mint(402), 60)
        check(c_ok and c_ok["v"] == "ok" and c_ok["via"] == "list" and c_dev and c_dev["v"] == "risky" and abs(c_ok["sol"] - SOL) < 1e-6,
              "the next poll at 61 and 62 %%: two 60 %% calls with the verdict their checks had (%s, %s)" % (c_ok and c_ok["v"], c_dev and c_dev["v"]))
        R.curve.set_follow([mint(400)], c_ok["t"] - 1000)
        R.curve.migrate(mint(401), now1 - 5 * MIN, "feed")
        R.curve.rows([row(mint(401), 60, now1)], now1)
        T1 = now1 + CW.VALUE_MS
        R.clock.wait(T1)
        cm.curve[mint(402)]["prog"] = 40.0
        h2 = len(cm.base.heads)
        R.cbud.clear()
        for _ in range(3):
            R.curve_value_step(R.clock.now(), R.clock.now() + 110_000)
        fetch = [h for h in cm.base.heads[h2:] if "/coins-v3/" in h["path"]]
        o_ok, o_dev = c_ok["out"], c_dev["out"]
        check(o_ok.get("x60") == 1.0 and o_ok.get("how") == "curve" and o_dev.get("how") == "curve" and abs(o_dev["x60"] - CW.mc_of_prog(40) / CW.mc_of_prog(62)) < 0.01
              and [h["path"].rsplit("/", 1)[1] for h in fetch] == [mint(402)],
              "an hour later: the followed coin's value from its trades (no request: %sx), the other one from one coins-v3 fetch (%.2fx, sold back to 40 %%)"
              % (o_ok.get("x60"), o_dev.get("x60") or 0))
        # a graduated call: DexScreener in the cycle
        a_g = mint(420)
        R.curve.rows([row(a_g, 58, now1 - MIN)], now1 - MIN)
        R.curve.rows([row(a_g, 61, now1)], now1)
        R.curve.migrate(a_g, now1 + 4 * MIN, "feed")
        sb = os.path.join(tmp, "sbW")
        os.makedirs(sb, exist_ok=True)
        with open(os.path.join(sb, "lists.json"), "w") as f_:
            json.dump({}, f_)
        asks = R.ds_asks(sb, R.clock.now())
        cg = R.curve.call(a_g, 60)
        R.curve_pool_values({a_g: {"priceUsd": cg["px"] * SOL * 0.05, "liquidityUsd": 9000.0}}, {a_g}, R.clock.now())
        check(a_g in asks and cg["out"].get("x60") == 0.05 and cg["out"].get("rug") is True and cg["out"].get("how") == "pool" and cg["out"]["gradMin"] == 4.0,
              "a call that graduated within its hour is valued by the cycle's DexScreener read (asked in ds_asks): 0.05x, a rug")
        # the doc block, radar-data and the guard
        rem = SR.fresh_remote(T, tmp, "cwire", T0)
        R.remote = rem
        R.git.remote = rem
        R.restore_state, R.last_ccounts = "ok", {}
        doc = R.build_doc("running", [], [], [], R.clock.now(), R.clock.now() + 120_000, 1.0, 0)
        landed = R.publish(doc)
        files = SR.branch_files(rem, "radar-data")
        on_branch = {p: json.loads(raw) for p, raw in files.items() if p.startswith("db/memecurve/")}
        n_calls = sum(len(e.get("calls") or {}) for d in on_branch.values() for e in d["coins"].values())
        cv = doc.get("curve") or {}
        check(landed and n_calls == len(R.curve.calls()) == 3 and "curvepushed.json" in files and cv.get("state") == "on" and cv.get("follow") == 1
              and cv.get("hosts", {}).get("trades") == "ok" and cv.get("push", {}).get("variant") is None and len(cv.get("variants") or []) == 6
              and len(json.dumps(doc, separators=(",", ":"))) <= LR.DOC_MAX,
              "radar.json's curve block (state %s, push %s) and the hour docs on radar-data (%d calls), curvepushed.json beside them"
              % (cv.get("state"), (cv.get("push") or {}).get("variant"), n_calls))
        h = R.curve.call_hour[mint(400)]
        R.curve.docs[h]["coins"].pop(mint(400))
        R.curve.call_hour.pop(mint(400))
        doc2 = dict(doc, t=doc["t"] + 1000)
        landed2 = R.publish(doc2)
        files2 = SR.branch_files(rem, "radar-data")
        same = {p: raw for p, raw in files.items() if p.startswith("db/memecurve/") or p == "curvepushed.json"} == \
            {p: raw for p, raw in files2.items() if p.startswith("db/memecurve/") or p == "curvepushed.json"}
        check(landed2 is True and R.ckept and same and json.loads(files2["radar.json"])["t"] == doc2["t"] and any("curve calls not pushed" in n_ for n_ in R.notes_run),
              "the never-shrink guard holds for the curve calls too: with one call fewer than the last tree the curve files on radar-data stay as "
              "they were, byte for byte, and the radar's own files still go (%s)" % next((n_ for n_ in R.notes_run if "curve" in n_), ""))
    finally:
        srv.shutdown()
        srv.server_close()


def c13_failopen(check, T, P, T0, tmp):
    import launch_radar as LR
    print("== curve C13: fail-open (a changed list, failing ticks, switched off, a round, refused trades)")
    SR = sr()
    cm = CurveMock(list(SR.FIX.values()), [{"a": mint(450), "prog": 60.0}])
    cm.bad = True
    srv = SR.serve(cm.base)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        R = unit(T, P, tmp, "rdF1", T0, url=url)
        cm.base.clock = R.clock.now
        R.live = FeedStub()
        R.curve_tick(R.clock.now(), R.clock.now() + 110_000)
        R.curve_at = 0
        R.curve_tick(R.clock.now(), R.clock.now() + 110_000)
        d = R.curve_doc(R.clock.now())
        n_list = sum(1 for h in cm.base.heads if h["path"] == "/frontend-api-v3.pump.fun/coins" and "complete=false" in h["q"])
        check(not R.csrc.use("pf_curve") and R.src.use("pf_curve") and R.src.use("pf_graduated") and d["state"] == "limited" and "curve list is off" in d["why"]
              and n_list == 1 and R.curve_on and R.curve.coins == {},
              "pump.fun's curve list in another shape: that adapter is off for the run (asked once), the radar's pump.fun lists stay on, "
              "the block says limited and why (%r)" % d["why"])
        cm.bad = False
        cm.curve[mint(450)].update(rc="odd", creator=mint(451, ""))
        Rr = unit(T, P, tmp, "rdF1r", T0, url=url)
        Rr.live = FeedStub()
        Rr.curve_tick(Rr.clock.now(), Rr.clock.now() + 110_000)
        for _ in range(8):
            Rr.curve_check_step(Rr.clock.now(), Rr.clock.now() + 110_000)
        check(not Rr.csrc.use("rc_report") and Rr.src.use("rc_report") and "rc_report" in Rr.csrc.off_why and not Rr.src.off_why,
              "a curve coin's RugCheck answer in another shape switches RugCheck off for the watch only: the radar's own adapters are never "
              "touched by the watch (its own switches and its own client)")
        R2 = unit(T, P, tmp, "rdF2", T0, url=url)
        R2.live = FeedStub()
        boom = lambda *a: (_ for _ in ()).throw(RuntimeError("planted"))
        R2.curve_poll = boom
        for i in range(LR.CURVE_FAILS):
            R2.curve_at = 0
            R2.curve_tick(R2.clock.now(), R2.clock.now() + 110_000)
        d2 = R2.curve_doc(R2.clock.now())
        check(R2.curve_on is False and d2["state"] == "off" and "failed 5 times" in d2["why"] and R2.live.asked[-1] == [],
              "%d failing ticks in a row: the watch is off for the run, its followed coins dropped, the block says why (%r); the radar goes on"
              % (LR.CURVE_FAILS, d2["why"]))
        with SR.env(MEMEBOT_RADAR_CURVE="off"):
            import launch_radar as LR2
            R3 = LR2.Radar(LR2.args_of(["loop", "--dir", os.path.join(tmp, "rdF3"), "--clock", "fake", "--now", str(T0), "--cache", os.path.join(tmp, "rdF3-c"),
                                        "--no-github", "--mock", url]), log=lambda s_: None, traps=T, peak=P)
        h0 = len(cm.base.heads)
        R3.live = FeedStub()
        R3.curve_tick(R3.clock.now(), R3.clock.now() + 110_000)
        d3 = R3.curve_doc(R3.clock.now())
        R3.one_round = False
        R4 = unit(T, P, tmp, "rdF4", T0, url=url)
        R4.one_round = True
        d4 = R4.curve_doc(R4.clock.now())
        R5 = unit(T, P, tmp, "rdF5", T0, url=url)
        R5.live = FeedStub(shape=False)
        d5 = R5.curve_doc(R5.clock.now())
        R6 = unit(T, P, tmp, "rdF6", T0, url=url)
        d6 = R6.curve_doc(R6.clock.now())
        R7 = unit(T, P, tmp, "rdF7", T0, url=url)
        R7.live = FeedStub(off="the server ended the connection right after a trade subscription")
        d7 = R7.curve_doc(R7.clock.now())
        check(len(cm.base.heads) == h0 and R3.curve is not None and not R3.curve_on and d3["state"] == "off" and "MEMEBOT_RADAR_CURVE=off" in d3["why"]
              and d4["state"] == "off" and "rounds only" in d4["why"] and d5["state"] == "limited" and d5["hosts"]["trades"] == "refused"
              and d6["state"] == "limited" and d6["hosts"]["trades"] == "off" and d7["state"] == "limited" and d7["hosts"]["trades"] == "refused"
              and "refused the trade subscriptions" in d7["why"],
              "MEMEBOT_RADAR_CURVE=off: no request, state off (its hour docs are still kept); a round: off (rounds only); the feed's trades "
              "failing their check or refused by the server: limited, the list alone (%r); no live feed: limited (%r)" % (d7["why"], d6["why"]))
        fin = LR.finish_from({"curve": d}, "hours", T0, "outside", "t", None, None, "manual", (7, 24))
        check(fin["curve"]["state"] == "off" and fin["curve"]["why"] == "the radar is hours" and fin["curve"]["variants"] == d["variants"],
              "outside the hours radar.json keeps the curve test's table, with the watch off")
    finally:
        srv.shutdown()
        srv.server_close()


def c14_words(check, T, P, T0, tmp):
    """The curve push's words (app.curve_words: radar_words' cleaning, limits and no-advice rule) and the switch end to end: with
    radar_curve.json as shipped nothing reaches app.notify, also with the live store set up; app.notify_curve refuses a call without the
    switched-on variant or with a trap verdict."""
    import app as A
    import launch_radar as LR
    print("== curve C14: the curve push's words and the switch end to end (nothing sent while it is off)")
    SR = sr()
    base = {"sym": "H2O", "prog": 82.4, "mcu": 58_250, "age": 14.6, "mom": True, "pts": 12.3, "v": "ok", "variant": "75m",
            "chips": [["ok", "no rugger wallets"], ["ok", "RugCheck report"], ["info", "dev: 3 launches, 1 dead"]]}
    tail = " · paper test, fake money, nothing is bought."
    w = A.curve_words(base)
    check(w == ("H2O: 82% of its curve sold, no pool yet", "still on the pump.fun curve · market cap $58k · 14 min since the mint · curve +12 points in 5 min · "
                "checks passed: no rugger wallets, RugCheck report" + tail),
          "the words: the coin and its curve sold in the title; still on the curve, its market cap, minutes since the mint, the momentum that held and "
          "the first passed checks in the body, then that it is a paper test with fake money (%r)" % (w,))
    forms = {"risky": A.curve_words(dict(base, v="risky", chips=[["ok", "RugCheck report"], ["warn", "creator sold"]], mom=False)),
             "risky, info": A.curve_words(dict(base, v="risky", chips=[["info", "dev: 12 launches, 11 dead"], ["info", "fresh dev wallet"]])),
             "risky, none": A.curve_words(dict(base, v="risky", chips=[])), "unknown": A.curve_words(dict(base, v="unknown", mom=None)),
             "ok, none": A.curve_words(dict(base, chips=[])), "round": A.curve_words(dict(base, prog=74.5, mcu=1_254_000, age=72.9)),
             "advice": A.curve_words(dict(base, sym="\u202eH2O\n\u200bX", chips=[["ok", "safe pool"], ["ok", "b\u200buy now"], ["ok", "CLEAN dev"], ["ok", "\u202eRugCheck report"]])),
             "absurd": A.curve_words(dict(base, prog=1e300, mcu=float("inf"), age=1e300, pts=1e300)), "nan": A.curve_words(dict(base, prog=float("nan"), mcu=-5, age=-1, pts="12")),
             "long": A.curve_words(dict(base, sym="S" * 400, chips=[["ok", "x" * 300], ["ok", "y" * 300], ["warn", "z" * 300]]))}
    bodies = [b for _, b in forms.values()] + [w[1]]
    check(forms["risky"][1].endswith("14 min since the mint · warning: creator sold" + tail) and "points" not in forms["risky"][1]
          and forms["risky, info"][1].endswith("warning: dev: 12 launches, 11 dead" + tail) and forms["risky, none"][1].endswith("warning: a red flag" + tail)
          and forms["unknown"][1].endswith("14 min since the mint · some checks still pending" + tail) and forms["ok, none"][1].endswith("no trap found so far" + tail)
          and forms["round"][0] == "H2O: 75% of its curve sold, no pool yet" and "market cap $1.3M · 72 min since the mint" in forms["round"][1],
          "the quick check in a few words: the first warning (or the first measured red flag, else 'a red flag'), 'some checks still pending', 'no trap "
          "found so far'; no momentum part unless it held; the curve share rounded half up as on the page (74.5 -> 75%)")
    check(forms["advice"][0] == "H2O X: 82% of its curve sold, no pool yet" and forms["advice"][1].endswith("checks passed: RugCheck report" + tail)
          and forms["absurd"] == ("H2O: still on its curve, no pool yet", "still on the pump.fun curve · market cap unknown · checks passed: no rugger wallets, RugCheck report" + tail)
          and forms["nan"] == ("H2O: still on its curve, no pool yet", "still on the pump.fun curve · market cap unknown · checks passed: no rugger wallets, RugCheck report" + tail)
          and len(forms["long"][0]) <= A.TITLE_MAX and all(len(b) <= A.BODY_MAX and b.endswith(tail) for b in bodies)
          and not any(A.NO_ADVICE.search(b) or A.PUSH_CTRL.search(b + t_) or "\u2014" in b + t_ for t_, b in forms.values())
          and A.curve_words(dict(base, v="trap")) is None and A.curve_words(None) is None and A.curve_words("H2O") is None,
          "radar_words' rules: direction marks, controls and zero-width marks gone (the symbol too), chip words that would say buy, safe or clean left "
          "out (also split by a hidden mark), a number out of its range unknown (no 300-digit age), the title within %d and every body within %d with "
          "the paper-test words whole, no em dash; a trap verdict has no words at all" % (A.TITLE_MAX, A.BODY_MAX))
    sent = []
    orig = A.notify
    A.notify = lambda kind, title, body, url=None: (sent.append((kind, title, body, url)), {"kind": kind, "sent": 1})[1]
    try:
        direct = [A.notify_curve(dict(base, variant=None)), A.notify_curve(dict(base, variant="75x")), A.notify_curve(dict(base, variant="75m\n")),
                  A.notify_curve(dict(base, v="trap")), A.notify_curve("x")]
        n_direct = len(sent)
        one = A.notify_curve(base)
        check(n_direct == 0 and [d_.get("skipped") for d_ in direct] == ["curve push switched off"] * 3 + ["trap verdict", "curve push switched off"]
              and one == {"kind": "curve", "sent": 1} and sent == [("curve",) + A.curve_words(base) + ("#tab-radar",)],
              "app.notify_curve, a second lock behind the switch: a call without the switched-on variant (none, 75x, a newline after it) or with a trap verdict "
              "sends nothing; a call of the variant goes out once as kind 'curve' to the New tab (%s)" % [d_.get("skipped") for d_ in direct])
        del sent[:]
        now = T0 + 10 * MIN
        with SR.env(SUPABASE_URL="http://127.0.0.1:9", SUPABASE_SECRET_KEY="sb_secret_selftest_only"):
            R = unit(T, P, tmp, "rdW", now)
            R.restore_state = "ok"
            R.last_doc = LR.finish_from({}, "running", now, "", "t", None, None, "manual", (0, 24))
            R.ccfg = LR.curve_cfg(CW)                       # radar_curve.json as shipped
            store_on = A.enabled() and R.cnotifier is None
            calls = [push_call(R.curve, mint(400 + i), now - i * 1000, thr=thr, mom=mom, v=v) for i, (thr, mom, v) in enumerate(
                ((60, True, "ok"), (75, True, "ok"), (75, False, "ok"), (90, True, "ok"), (75, True, "unknown"), (60, False, "risky")))]
            for i in range(5):
                R.curve_push(now + i * 1000, now + 100_000)
            off = (list(sent), sum(1 for c in calls if c.get("push")), dict(R.cpushed))
            R.ccfg = {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 3}
            R.curve_push(now + 6000, now + 100_000)
            on = list(sent)
    finally:
        A.notify = orig
    check(store_on and off == ([], 0, {}) and len(on) == 1 and on[0][0] == "curve" and on[0][3] == "#tab-radar" and on[0][2].endswith(tail),
          "end to end with the live store set up: radar_curve.json as shipped (curvePush null) sends nothing for six fresh calls of every variant and "
          "marks none as pushed (%d sent); switched on for 75m, the 75 %% call with momentum goes out once through app.notify_curve (%s)" % (
              len(off[0]), on[0][1] if on else "none"))


def refusing(cm, cur, refuse):
    """The curve mock answering refuse["list"] (a status) to the curve list and refuse["rc"] to RugCheck's reports of the curve coins cur."""
    orig = cm.route

    def route(method, path, query, body):
        q = urllib.parse.parse_qs(query)
        if refuse.get("list") and path == "/frontend-api-v3.pump.fun/coins" and (q.get("complete") or [""])[0] == "false":
            return refuse["list"], {"error": "refused"}
        if refuse.get("rc") and path.startswith("/api.rugcheck.xyz/") and any(c["a"] in path for c in cur):
            return refuse["rc"], {"error": "refused"}
        return orig(method, path, query, body)
    cm.route = route


def c15_hosts(check, T, P, T0, tmp):
    """The watch's own client (radar_src.SideHttp): a 429 or three refusals it hears on pump.fun's curve list, or a RugCheck 429 on a curve
    coin, never cool or give up that host for the rounds (the next cycle's discovery and RugCheck still go out); the radar's own cool-down
    stops the watch's requests too (one way); the per-host gaps are shared."""
    import launch_radar as LR
    import radar_src as RS
    print("== curve C15: the watch's own client (nothing it hears blocks a host for the rounds)")
    SR = sr()
    PF, RC = "frontend-api-v3.pump.fun", "api.rugcheck.xyz"
    cur = [{"a": mint(460 + i), "prog": 55.0 + i, "sym": "H%d" % i, "creator": mint(470 + i, ""), "mint": T0 - 8 * MIN} for i in range(3)]
    cm = CurveMock(list(SR.FIX.values()), cur)
    refuse = {}
    refusing(cm, cur, refuse)
    srv = SR.serve(cm.base)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        got = {}
        for name, code, ticks in (("429", 429, 1), ("403x3", 403, 3)):
            R = unit(T, P, tmp, "rdH" + name, T0, url=url)
            cm.base.clock = R.clock.now
            R.live = FeedStub()
            refuse["list"] = code
            for _ in range(ticks):
                R.curve_at = 0
                R.cbud.clear()
                R.curve_tick(R.clock.now(), R.clock.now() + 110_000)
            refuse["list"] = None
            d = R.curve_doc(R.clock.now())
            R.http.new_cycle(time.time() + 60, LR.RPC_CAP)               # the next cycle, as cycle() starts it
            h0 = len(cm.base.heads)
            sb = os.path.join(tmp, "sbH" + name)
            os.makedirs(sb, exist_ok=True)
            n = R.src.discover(sb, R.cache["pf"], R.clock.now(), R.cache["jup"])
            pf = [h for h in cm.base.heads[h0:] if h["path"].startswith("/" + PF + "/")]
            got[name] = {"radar": R.http.blocked(PF), "watch": R.chttp.blocked(PF), "dead": PF in R.chttp.dead, "sent": len(pf),
                         "grad": n.get("pf:graduated"), "host": d["hosts"]["pump.fun"]}
        check(all(g["radar"] is False and g["watch"] is True and g["sent"] >= 2 and (g["grad"] or 0) > 0 for g in got.values())
              and got["429"]["host"] == "limited" and got["403x3"]["dead"] and got["403x3"]["host"] == "down" and not got["429"]["dead"],
              "a 429 and three 403s on pump.fun's curve list cool and give up that host for the watch only: the next cycle's pump.fun discovery "
              "still goes out (%s); the block says limited / down" % {k: (g["sent"], g["grad"], g["host"]) for k, g in got.items()})
        Rr = unit(T, P, tmp, "rdHrc", T0, url=url)
        cm.base.clock = Rr.clock.now
        Rr.live = FeedStub()
        refuse["rc"] = 429
        Rr.curve_tick(Rr.clock.now(), Rr.clock.now() + 110_000)
        h1 = len(cm.base.heads)
        for _ in range(30):
            Rr.curve_check_step(Rr.clock.now(), Rr.clock.now() + 110_000)
        rc_watch = [h for h in cm.base.heads[h1:] if h["path"].startswith("/" + RC + "/")]
        refuse["rc"] = None
        Rr.http.new_cycle(time.time() + 60, LR.RPC_CAP)
        st, rep = Rr.src.rc_report(next(iter(SR.FIX.values()))["a"])
        check(len(rc_watch) == 1 and Rr.chttp.blocked(RC) and not Rr.http.blocked(RC) and st == "ok" and isinstance(rep, dict),
              "a RugCheck 429 on a curve coin's quick check rests RugCheck for the watch (1 request, then none): the next cycle's own RugCheck "
              "report goes out (%s), so a green coin and its push stay possible" % st)
        Ro = unit(T, P, tmp, "rdHone", T0, url=url)
        cm.base.clock = Ro.clock.now
        Ro.live = FeedStub()
        Ro.http._rate429(PF)                                             # the radar's round got a 429 from pump.fun
        h2 = len(cm.base.heads)
        Ro.curve_tick(Ro.clock.now(), Ro.clock.now() + 110_000)
        sent_cool = [h for h in cm.base.heads[h2:] if h["path"].startswith("/" + PF + "/")]
        Ro.http.cool.pop(PF, None)
        Ro.http.dead.add(RC)
        check(sent_cool == [] and Ro.chttp.blocked(RC) and not RS.RadarHttp.blocked(Ro.chttp, RC) and Ro.chttp.last_at is Ro.http.last_at
              and Ro.chttp.rpc_at is Ro.http.rpc_at and Ro.csrc.http is Ro.chttp and Ro.src.http is Ro.http,
              "one way: a host the radar has cooling or has given up gets no request from the watch either; both clients keep one pace per host "
              "(the same gaps), each its own refusals")
    finally:
        srv.shutdown()
        srv.server_close()


def c16_stored(check, T, P, T0, tmp):
    """Curve hour docs on radar-data in another shape (a hand edit, THRESHOLDS changed after this test, a future format): a call load()
    cannot read is left out and counted the same way by the guard, so the radar's own records still reach radar-data with the watch off;
    a call whose outcome is not a dict or whose numbers are text is repaired, so nothing in the cycle raises; a guard that fails keeps
    the last tree's curve files and sends no curve push (its mark did not land)."""
    import launch_radar as LR
    print("== curve C16: stored curve docs in another shape (the radar's own pushes never stop for them)")
    SR = sr()
    rem = SR.fresh_remote(T, tmp, "cstore", T0)
    base = T0 - 70 * MIN                                      # their values come due 10 minutes before T0
    hour = CW.utc_hour(base)
    a1, a2, a3, a4 = mint(480), mint(481), mint(482), mint(483)
    call = lambda thr, t, **kw: dict({"t": t, "thr": thr, "via": "trade", "prog": thr + 0.5, "px": 1e-7, "mcs": 100.0, "sol": 150.0, "mcu": 15000, "age": 20.0,
                                     "m5": {"pts": 5, "buys": 3, "sells": 1}, "mom": False, "v": "unknown", "chips": [], "hi": 1.0, "out": {}, "push": None}, **kw)
    cdoc = {"v": 1, "hour": hour, "t": CW.hour_ms(hour), "upd": T0, "polls": 3,
            "coins": {a1: {"mint": a1, "sym": "A", "calls": {"60": call(60, base + 1000)}},
                      a2: {"mint": a2, "sym": "B", "calls": {"80": call(80, base + 2000)}},                           # a threshold no longer used
                      a3: {"mint": a3, "sym": "C", "calls": {"75": call(75, float(base + 3000))}},                    # a time that is no int
                      a4: {"mint": a4, "sym": "D", "calls": {"90": call(90, base + 4000, out=None, px="1e-7", hi="x", chips="bad", m5=[1], v="great")}}}}
    rhour = CW.utc_hour(T0 - H)
    SR.put_branch(rem, "radar-data", {"db/memecurve/%s.json" % hour: cdoc, "db/memeradar/%s.json" % rhour: {"v": 1, "hour": rhour, "t": CW.hour_ms(rhour), "upd": T0, "coins": {}},
                                      "radar.json": {"v": 1, "kind": "radar", "t": T0 - MIN}}, tmp)
    R = unit(T, P, tmp, "rdSt", T0, remote=rem)
    R.curve_on = False                                        # the watch switched off (MEMEBOT_RADAR_CURVE=off): its docs are still kept
    R.restore()
    a_new = mint(484)
    R.docs.setdefault(CW.utc_hour(T0), {"v": 1, "hour": CW.utc_hour(T0), "t": CW.hour_ms(CW.utc_hour(T0)), "upd": T0, "coins": {}})["coins"][a_new] = \
        {"addr": a_new, "sym": "NEW", "first": T0, "px": 1e-5, "later": {}}
    doc = R.build_doc("running", [], [], [], R.clock.now(), R.clock.now() + 120_000, 1.0, 0)
    landed = R.publish(doc)
    files = SR.branch_files(rem, "radar-data")
    c4 = R.curve.call(a4, 90) or {}
    check(R.restore_state == "ok" and R.tree_ccounts == {hour: 2} == R.curve.counts(0) and landed and not R.ckept and not R.curve_live()
          and any(a_new.encode() in raw for p, raw in files.items() if p.startswith("db/memeradar/")) and R.curve.call(a2, 80) is None and R.curve.call(a3, 75) is None,
          "a tree whose curve doc holds calls load() cannot read (a threshold no longer used, a time that is no int): the guard counts them "
          "as load() does (%s), so with the watch off the radar's own record of this run still reaches radar-data" % R.tree_ccounts)
    sb = os.path.join(tmp, "sbSt")
    os.makedirs(sb, exist_ok=True)
    with open(os.path.join(sb, "lists.json"), "w") as f_:
        json.dump({}, f_)
    R.curve_fails = 0
    due = sorted(R.curve.value_due(R.clock.now()))
    R.ds_asks(sb, R.clock.now())
    check(c4.get("out") == {} and c4.get("px") == 1e-7 and c4.get("hi") is None and c4.get("chips") == [] and c4.get("m5") == {} and c4.get("v") == "unknown"
          and cdoc["coins"][a4]["calls"]["90"]["out"] is None and due == sorted([(a1, 60, "curve"), (a4, 90, "curve")]) and R.curve_fails == 0
          and CW.doc_calls(cdoc) == 2 and CW.doc_calls({"coins": "x"}) == 0 and CW.call_ok("60", call(75, T0)) is None and CW.call_ok("60", call(60, True)) is None,
          "a call whose outcome is not a dict, whose price is text and whose peak, chips, momentum and verdict are in another form is repaired "
          "on load (never read as 0; the stored doc untouched): its value comes due as usual and the cycle's DexScreener asks do not raise")
    Rg = unit(T, P, tmp, "rdSg", T0, remote=rem)
    Rg.restore()
    sink = CurveSink()
    Rg.cnotifier, Rg.ccfg = sink, {"curvePush": "75m", "pushVerdicts": ["ok"], "pushPerH": 3}
    Rg.last_doc = LR.finish_from({}, "running", T0, "", "t", None, None, "manual", (0, 24))
    before = {p: raw for p, raw in SR.branch_files(rem, "radar-data").items() if p.startswith("db/memecurve/") or p == "curvepushed.json"}
    for m_ in (a1, a4):                                       # two calls fewer than the last tree (a fresh one makes up only one): the
        hh = Rg.curve.call_hour.pop(m_)                       # curve guard fails
        Rg.curve.docs[hh]["coins"].pop(m_)
    a5 = mint(485)
    push_call(Rg.curve, a5, T0, thr=75, mom=True, v="ok")
    Rg.curve_push(T0, T0 + 100_000)
    after = {p: raw for p, raw in SR.branch_files(rem, "radar-data").items() if p.startswith("db/memecurve/") or p == "curvepushed.json"}
    check(sink.got == [] and a5 not in Rg.cpushed and before == after and bool(before) and Rg.ckept,
          "the curve guard fails: the commit carries the last tree's curve files byte for byte, and no curve push goes out (its mark did not land)")


def c17_judging(check, T, T0):
    """How the paper test judges (the logic review): a verdict that comes after a call made without one counts at its own moment's price,
    never with what happened after the entry; rugged and doubled by traps.outcome's rules as the greens are; the graduated share only over
    hours someone saw, never a made-up graduation time; the calibration both ways; a call's curve value from the trades only when every
    trade up to the hour was seen."""
    print("== curve C17: judging the calls (late verdicts, the greens' rules, unseen hours, the calibration, unbroken trades)")
    W = T.load_weights()
    cr = mint(510, "")

    def called(a, B=None):
        B = B or CW.Book()
        B.rows([row(a, 50, T0, creator=cr)], T0)
        B.set_follow([a], T0)
        t = T0
        for i in range(20):
            t += 16_000
            B.trade(trade(a, t, 50 + i * 0.5))
        got = B.trade(trade(a, t + 5_000, 61.0))
        return B, got[0][1], t + 5_000

    S_ok = T.blank_signals()
    S_ok.update(rcReport=True, wmChecked=True, devN=0, rcDanger=[], rcWarn=[], rugHolders=0)
    S_sold = dict(S_ok, creatorSold=True)
    a1 = mint(520)
    B1, c1, t1 = called(a1)
    B1.trade(trade(a1, t1 + 40_000, 66.0))
    B1.trade(trade(a1, t1 + 70_000, 55.0, side="sell", who=cr))         # the creator sells 70 s after the call
    B1.set_check(a1, *CW.verdict(T, S_sold, W), t1 + 100_000)           # the checks land 100 s after the call
    a2 = mint(521)
    B2, c2, t2 = called(a2)
    B2.trade(trade(a2, t2 + 20_000, 64.0))
    px_late = B2.coins[a2]["px"]
    B2.set_check(a2, *CW.verdict(T, S_ok, W), t2 + 25_000)              # ok 25 s after the call, the price 1.1x
    B2.trade(trade(a2, t2 + 30 * MIN, 80.0))
    B2.set_value(a2, 60, "curve", t2 + CW.VALUE_MS, px=CW.mc_of_prog(70) / CW.SUPPLY)
    o2 = c2["out"]
    k = c2["px"] / c2["late"]["px"]
    by = {r["id"]: r for r in B2.variants()}["60"]["by"]
    check(c1["v"] == "unknown" and "late" not in c1 and c2["v"] == "unknown" and c2["late"]["v"] == "ok" and c2["late"]["t"] == t2 + 25_000
          and c2["late"]["px"] == CW.sig(px_late) and abs(o2["late"]["x60"] - round(o2["x60"] * k, 4)) < 1e-4 and o2["late"]["eur"] == CW.paper(o2["late"]["x60"])
          and abs(o2["late"]["peak"] - round(CW.mc_of_prog(80) / CW.mc_of_prog(64), 4)) < 2e-3 and list(by) == ["ok"] and by["ok"]["eur"] == o2["late"]["eur"]
          and CW.LATE_MS == 90_000,
          "a call made without a verdict keeps 'unknown' at the call; one that comes within %d s is noted beside it with that moment's price "
          "(%.3fx the call's) and the split counts the call under it entered at that price (%.2fx at 60 min instead of %.2fx); one that comes "
          "after (here 100 s, after the creator sold) changes nothing" % (CW.LATE_MS // 1000, 1 / k, o2["late"]["x60"], o2["x60"]))
    import launch_radar as LR
    check(LR.CURVE_PUSH_WAIT_MS == CW.LATE_MS, "the curve push waits as long as a late verdict counts (%d s): the split and the push judge the same calls"
          % (LR.CURVE_PUSH_WAIT_MS // 1000))
    # the greens' rules
    a3 = mint(522)
    B3, c3, t3 = called(a3)
    B3.trade(trade(a3, t3 + 4 * MIN, 99.5))                              # the run-up on the curve: 4.2x
    B3.migrate(a3, t3 + 5 * MIN, "feed")
    B3.set_value(a3, 60, "gone", t3 + CW.VALUE_MS)
    o3 = c3["out"]
    green = {"addr": a3, "px": 1.0, "liq": 20000, "mc": 60000, "good": T0, "goodPx": 1.0, "later": {"60": {"t": T0 + H, "gone": True}}, "peak60": {"x": o3["peak"], "at": T0}}
    tg = T.outcome(green)
    rules = {(x, pk, how): CW.judged(x, pk, how) for x, pk, how in ((0.5, 3.0, "curve"), (0.31, 1.0, "dead"), (2.5, 2.5, "pool"), (1.0, 45.0, "pool"), (0.08, 1.0, "pool"))}
    check(o3["peak"] > 4 and (o3["rug"], o3["x2"]) == (tg["rug1h"], tg["win1h"]) == (True, False)
          and rules == {(0.5, 3.0, "curve"): (False, True), (0.31, 1.0, "dead"): (True, False), (2.5, 2.5, "pool"): (False, True),
                        (1.0, 45.0, "pool"): (False, False), (0.08, 1.0, "pool"): (True, False)},
          "rugged and doubled by traps.outcome's rules, as the greens' row: a %.1fx run-up on the curve, then gone at 60 min, is a rug and no double "
          "(the greens' rule gives the same); a curve sold back under 5 %% is dead, a rug; a peak over 30x is a bad reading" % o3["peak"])
    # unseen hours, no made-up graduation time
    B4 = CW.Book()
    a4 = [mint(530 + i) for i in range(6)]
    for i, a in enumerate(a4):
        B4.rows([row(a, 70, T0)], T0)
        B4.rows([row(a, 76, T0 + 30_000)], T0 + 30_000)
        if i < 2:
            B4.migrate(a, T0 + 20 * MIN, "feed")
    B4.value_due(T0 + 9 * H)                                              # the next morning: every value is missing
    r75 = {r["id"]: r for r in B4.variants()}["75"]
    a5 = mint(540)
    B4.rows([row(a5, 70, T0)], T0)
    B4.rows([row(a5, 76, T0 + 30_000)], T0 + 30_000)
    B4.graduated(a5, T0 + 2 * H)                                          # pump.fun's coin says complete, no pool time known
    o5 = B4.call(a5, 75)["out"]
    a6 = mint(541)
    B4.rows([row(a6, 70, T0)], T0)
    B4.rows([row(a6, 76, T0 + 30_000)], T0 + 30_000)
    B4.rows([row(a6, 50, T0 + 40 * MIN, complete=True)], T0 + 40 * MIN)   # the list's complete flag 40 minutes after its last reading
    o6 = B4.call(a6, 75)["out"]
    check(r75["n"] == 6 and r75["nS"] == 0 and r75["miss"] == 6 and r75["grad"] == 1.0 and r75["unseen"] == 4 and o5.get("done") and "grad" not in o5
          and "gradMin" not in o5 and CW.grad_seen(B4.call(a5, 75)) is None and o6.get("done") and "grad" not in o6 and B4.coins[a6]["grad"] == T0 + 40 * MIN,
          "calls whose hour nobody saw (the radar stopped before call + 60 min): the 2 graduations the feed saw count, the 4 others are unseen, "
          "never 'did not graduate' (graduated %s, unseen %s); a graduation found only later (a coin fetch, a list's complete flag long after the "
          "last reading) gets no made-up time or minutes" % (r75["grad"], r75["unseen"]))
    # the calibration both ways
    B5 = CW.Book()
    for i in range(6):
        a = mint(550 + i)
        B5.rows([row(a, 50, T0)], T0)
        B5.trade(trade(a, T0 + MIN, 107.0))                               # the constant reads 7 % too high: 107 % raw at the last trade
        B5.migrate(a, T0 + MIN + 5_000, "feed")
    a7 = mint(560)
    B5.rows([row(a7, 50, T0)], T0)
    B5.trade(trade(a7, T0 + MIN, 107.0))
    check(B5.calib()["n"] == 6 and B5.calib()["prog"] == 107.0 and abs(B5.scale - 100 / 107.0) < 1e-3 and abs(B5.coins[a7]["p"] - 100.0) < 0.01
          and CW.prog_vt(vt_of(107)) is None and abs(CW.raw_vt(vt_of(107)) - 107.0) < 1e-6,
          "a constant that reads too high (107 %% at the last trades before graduations): the calibration sees it (median %s %%) and scales "
          "every reading by %.3f, so the curve's end reads 100 %% again (it can no longer only correct readings that are too low)" % (B5.calib()["prog"], B5.scale))
    # a curve value only from unbroken trades
    a8 = mint(570)
    B6 = CW.Book()
    B6.rows([row(a8, 55, T0)], T0)
    B6.set_follow([a8], T0)
    B6.trade(trade(a8, T0 + 10_000, 58.0))
    c8 = B6.trade(trade(a8, T0 + 20_000, 61.0))[0][1]
    B6.trade(trade(a8, T0 + 5 * MIN, 70.0))
    B6.set_follow([], T0 + 6 * MIN)                                       # dropped: its trades are not seen (sold back to 20 % meanwhile)
    B6.set_follow([a8], T0 + 50 * MIN)
    B6.trade(trade(a8, T0 + 62 * MIN, 21.0, side="sell"))
    v_gap = B6.curve_value(a8, 60, T0 + 62 * MIN, True)
    a9 = mint(571)
    B7 = CW.Book()
    B7.rows([row(a9, 55, T0)], T0)
    B7.set_follow([a9], T0)
    B7.trade(trade(a9, T0 + 10_000, 58.0))
    B7.trade(trade(a9, T0 + 20_000, 61.0))
    B7.trade(trade(a9, T0 + 5 * MIN, 70.0))
    B7.feed_gap(T0 + 30 * MIN)                                            # the feed reconnected meanwhile
    B7.trade(trade(a9, T0 + 62 * MIN, 69.0))
    v_feed = (B7.curve_value(a9, 60, T0 + 62 * MIN, True), B7.curve_value(a9, 60, T0 + 62 * MIN, False))
    B8 = CW.Book()
    B8.rows([row(a9, 55, T0)], T0)
    B8.set_follow([a9], T0)
    B8.trade(trade(a9, T0 + 10_000, 58.0))
    c9 = B8.trade(trade(a9, T0 + 20_000, 61.0))[0][1]
    B8.trade(trade(a9, T0 + 5 * MIN, 70.0))
    B8.trade(trade(a9, T0 + 62 * MIN, 69.0))
    v_ok = B8.curve_value(a9, 60, T0 + 62 * MIN, False)
    check(v_gap is None and v_feed == (None, None) and v_ok and abs(v_ok[1] / c9["px"] - CW.mc_of_prog(70) / CW.mc_of_prog(61)) < 1e-3 and c8,
          "a call's value from the trades only when every trade up to the hour was seen: a coin dropped and followed again, or a feed that "
          "reconnected meanwhile, needs a coin fetch (never the stale price before the gap); followed without a break it is the last price "
          "before the hour (%.2fx)" % (v_ok[1] / c9["px"] if v_ok else 0))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d curve checks failed" % len(fails) if fails else "\nCURVE ALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
