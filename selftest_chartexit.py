#!/usr/bin/env python3
"""selftest_chartexit.py: the Pick's chart exit (memebot.chart_hit, rule v3, the user's go of Oct 24: "Okay dann Bau das"). Fake money only:
the fixtures are hand-made candles and docs, nothing is fetched.

  C1 memebot.chart_hit: the floor on the minute's low (-50 %, booked at that low), the trail once the high reached 1.5x (15 % under the
     highest high, on the low; a close under it right after a new high at that close), the drop (a close 15 % under the close 30 minutes
     before, cpx before then), 11x on the high, the stop first in one minute, glitches, the 6-hour limit first, the last check
  C2 the research replay (research/chartexit/calib_minute.replay_min, the rule as it was tested) and chart_hit decide alike on random
     minute paths
  C3 memebot.live_watch takes a chart sale (trail, drop, a stop never above 0.50x) only when the watch marked it "chart"
  C4 memebot.py run: the new key restarts the account once (the fixed rule's open position closed at the restart), then a chart position
     sells on its own candles since the entry (a drop at its close), the watch's chart sale is booked at its minute, an unmarked one is
     not; the candles of a chart position are asked for from its entry
  C5 rocket_watch.watch judges a chart position by chart_hit and marks its sale; a pool without candles trails on DexScreener's price;
     a sale the watch of older code made by the fixed rule is dropped and the position looked at again; a sale it sees more than
     memebot.LATE_MS after its minute is booked at the last close then (memebot.noticed, the user's "ja" of 26 Oct)
  C6 shadow: K is the fixed rule, X the chart exit replayed on the same clean minutes (chart_hit)
  C7 the words: the rule text, the position card's trailing stop, the stop's words by rule; the constants and the key
  C8 the sell bot (page_home.sell_bot, the user could not find the chart exit in the app on Oct 24): its card on the Pick tab (the trail
     armed or where it arms, the 6-hour minute), its row on the Start tab, nothing before the live chart or for a fixed-rule position

  python3 selftest_chartexit.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
"""
import contextlib, json, os, random, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MIN, H = 60_000, 3_600_000
LIVE = 1_900_000_000_000          # a made-up live chart switch, far after every real date, so the checks do not depend on the clock


@contextlib.contextmanager
def live_at(v):
    old = os.environ.get("MEMEBOT_LIVE_SELL_AT")
    os.environ["MEMEBOT_LIVE_SELL_AT"] = str(v)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MEMEBOT_LIVE_SELL_AT", None)
        else:
            os.environ["MEMEBOT_LIVE_SELL_AT"] = old


def cnd(t, close, hi=None, lo=None):
    return (float(t), float(close), float(hi if hi is not None else close), float(lo if lo is not None else close), float(close))


def flat(t0, n, x=1.0, start=0):
    return [cnd(t0 + i * MIN, x, x * 1.01, x * 0.99) for i in range(start, start + n)]


def c1(check):
    import memebot as M
    print("== chart exit C1: chart_hit")
    t0 = LIVE + H
    with live_at(LIVE):
        floor = M.chart_hit(flat(t0, 10) + [cnd(t0 + 10 * MIN, 0.9, lo=0.45)], t0)
        dip = M.chart_hit(flat(t0, 10) + [cnd(t0 + 10 * MIN, 0.95, lo=0.6)] + flat(t0, 5, 0.95, 11), t0)
        check(floor["why"] == "stop" and floor["hit"] == t0 + 10 * MIN and abs(floor["mult"] - 0.45) < 1e-9 and dip["hit"] is None and dip["fresh"],
              "C1 a low at 0.45x is the floor, booked at that low; a wick to 0.6x with the close at 0.95x sells nothing (%s, %s)" % (floor["why"], dip["why"]))
        up = flat(t0, 5) + [cnd(t0 + (5 + i) * MIN, 1.0 + 0.1 * i, 1.0 + 0.1 * i, 0.99 + 0.1 * i) for i in range(1, 8)]     # up to 1.7x
        trail = M.chart_hit(up + [cnd(t0 + 13 * MIN, 1.6, 1.62, 1.40)], t0)
        early = M.chart_hit(flat(t0, 5) + [cnd(t0 + 5 * MIN, 1.3, 1.4, 1.29), cnd(t0 + 6 * MIN, 1.2, 1.21, 1.15)], t0)
        check(trail["why"] == "trail" and trail["hit"] == t0 + 13 * MIN and abs(trail["mult"] - 1.40) < 1e-9 and abs(trail["hi"] - 1.7) < 1e-9
              and early["hit"] is None and early["lvl"] == 0.5,
              "C1 the trail: from a high of 1.7x a low at 1.40x (under 1.445x) sells at that low; under 1.5x it is not armed yet (%s, %s)" % (trail, early["lvl"]))
        same = M.chart_hit(flat(t0, 5) + [cnd(t0 + 5 * MIN, 1.45, 2.0, 1.45)], t0)
        check(same["why"] == "trail" and abs(same["mult"] - 1.45) < 1e-9 and same["hit"] == t0 + 5 * MIN,
              "C1 a minute that makes a new high of 2x and closes at 1.45x (under 1.7x) sells at its close (%s)" % same)
        fall = flat(t0, 30) + [cnd(t0 + (30 + i) * MIN, 1.0 - 0.006 * i) for i in range(1, 40)]
        drop = M.chart_hit(fall, t0)
        want = next(i for i in range(1, 40) if 1.0 - 0.006 * i <= 0.85 * (1.0 if 30 + i - 30 < 30 else 1.0 - 0.006 * (i - 30)))
        early_drop = M.chart_hit(flat(t0, 3) + [cnd(t0 + 3 * MIN, 0.84)], t0)
        check(drop["why"] == "drop" and drop["hit"] == t0 + (30 + want) * MIN and abs(drop["mult"] - (1.0 - 0.006 * want)) < 1e-9
              and early_drop["why"] == "drop" and abs(early_drop["mult"] - 0.84) < 1e-9,
              "C1 the drop: a close 15%% under the close 30 minutes before sells at that close; in the first 30 minutes against cpx (%s, %s)" % (drop["hit"], early_drop["why"]))
        tp = M.chart_hit(flat(t0, 3) + [cnd(t0 + 3 * MIN, 3.0, 11.5, 2.9)], t0)
        both = M.chart_hit(flat(t0, 3) + [cnd(t0 + 3 * MIN, 2.0, 11.5, 0.45)], t0)
        glitch = M.chart_hit(flat(t0, 3) + [cnd(t0 + 3 * MIN, 45.0, 46.0, 44.0), cnd(t0 + 4 * MIN, 1.0, 1.01, 0.99)], t0)
        check(tp["why"] == "tp" and tp["mult"] == 11.0 and both["why"] == "stop" and abs(both["mult"] - 0.45) < 1e-9 and glitch["hit"] is None and glitch["hi"] < 1.5,
              "C1 11x on the high is a take-profit at exactly 11x; the floor in the same minute first; a close over 30x is a glitch (%s, %s, %s)" % (tp["why"], both["why"], glitch["hi"]))
        late = M.chart_hit(flat(t0, 365) + [cnd(t0 + 365 * MIN, 0.3)], t0)
        seen = M.chart_hit(flat(t0, 10) + [cnd(t0 + 10 * MIN, 0.9, lo=0.45)] + flat(t0, 5, 1.0, 11), t0, t0 + 12 * MIN, 1.0)
        armed = M.chart_hit(up + flat(t0, 3, 1.68, 13) + [cnd(t0 + 16 * MIN, 1.6, 1.62, 1.40)], t0, t0 + 14 * MIN, 1.0)
        check(late["hit"] is None and seen["hit"] is None and armed["why"] == "trail" and armed["hit"] == t0 + 16 * MIN,
              "C1 nothing from entry + 6 h on; the minutes before the last check sell nothing, but their high still arms the trail (%s, %s, %s)" % (
                  late["why"], seen["why"], armed["why"]))
        none = M.chart_hit([], t0)
        check(none["hit"] is None and none["fresh"] is False, "C1 no candles: nothing")


def c2(check):
    import memebot as M
    sys.path.insert(0, os.path.join(HERE, "research", "chartexit"))
    import check_chartexit as X
    print("== chart exit C2: the tested rule and the live code decide alike")
    src = open(os.path.join(HERE, "research", "chartexit", "calib_minute.py"), encoding="utf-8").read()
    ns = {"X": X, "np": __import__("numpy")}
    exec(src[src.index("def replay_min"):src.index("g5 = np.load")], ns)
    rule = [v for v in X.VARIANTS if v == dict(stop=M.CHART_STOP, trail=M.CHART_TRAIL, arm=M.CHART_ARM, lock=0.0, stale_h=0, stale_g=0.0, fade="drop", T=6)]
    P = X.var_array()[X.VARIANTS.index(rule[0])] if rule else None
    rnd, t0, bad, n = random.Random(5), LIVE + H, [], 0
    with live_at(LIVE):
        for k in range(300):
            x, cs = 1.0, []
            vol = rnd.choice((0.01, 0.03, 0.06))
            for i in range(360):
                o = x
                x = max(1e-6, x * __import__("math").exp(rnd.gauss(0.0005, vol)))
                hi, lo = max(o, x) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, x) * (1 - abs(rnd.gauss(0, vol / 2)))
                cs.append((t0 + i * MIN, o, hi, lo, x))
            C, Hh, L, O = (ns["np"].array([c[j] for c in cs]) for j in (4, 2, 3, 1))
            Hh = ns["np"].where(Hh <= 5 * C, Hh, C)
            L = ns["np"].where(L >= C / 5, L, C)
            a, _, why = ns["replay_min"](C, Hh, L, O, ns["np"].zeros(360), 0.0, P)
            hc = M.chart_hit([(t0 - MIN, 1.0, 1.0, 1.0, 1.0)] + cs, t0, None, 1.0)
            mine = (hc["why"], hc["mult"]) if hc["hit"] else ("time", None)
            n += 1
            if mine[0] != why or (mine[1] is not None and abs(mine[1] - a) > 1e-9):
                bad.append((k, why, a, mine))
    check(rule and n == 300 and not bad, "C2 on 300 random minute paths chart_hit sells where the tested replay sells, at the same price (%d differ%s)" % (
        len(bad), (": %s" % (bad[0],)) if bad else ""))


def c3(check):
    import memebot as M
    print("== chart exit C3: what the scan takes from the watch")
    tmp = tempfile.mkdtemp(prefix="mb-chart-")
    try:
        json.dump({"v": 1, "t": LIVE + H, "pos": {}, "sold": {
            "a": {"at": LIVE + MIN, "why": "trail", "mult": 1.4, "rule": "chart"}, "b": {"at": LIVE + MIN, "why": "drop", "mult": 0.8, "rule": "chart"},
            "c": {"at": LIVE + MIN, "why": "stop", "mult": 0.6, "rule": "chart"}, "d": {"at": LIVE + MIN, "why": "trail", "mult": 1.4},
            "e": {"at": LIVE + MIN, "why": "stop", "mult": 0.6}}}, open(os.path.join(tmp, "pickwatch.json"), "w"))
        with live_at(LIVE):
            _, sold = M.live_watch(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check(sorted(sold) == ["a", "b", "c", "e"] and sold["a"] == {"at": LIVE + MIN, "why": "trail", "mult": 1.4, "rule": "chart"} and sold["b"]["mult"] == 0.8
          and sold["c"]["mult"] == 0.5 and sold["e"]["mult"] == 0.6 and "rule" not in sold["e"],
          "C3 a chart sale keeps its reason and price (a stop never above 0.50x) and its mark; a trail without the mark is not a sale; the fixed "
          "rule's stop stays as it was (%s)" % sold)


def scan_dir(d, t, pos, rule):
    import memebot as M
    for sub in ("db/memepos", "db/memeexit", "db/memebot", "candles"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    for k, v in pos.items():
        json.dump(dict(v, grp="hold", ticket=50.0, rule=M.RULE), open(os.path.join(d, "db", "memepos", k + ".json"), "w"))
    json.dump({"paperRule": rule, "paperSince": t - 1, "paperRuleSince": t - 1}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))


def run_scan(d, now, live):
    p = subprocess.run([sys.executable, os.path.join(HERE, "memebot.py"), "run", "--mode", "check", "--dir", d, "--now", str(now), "--horizon", "2h"],
                       capture_output=True, text=True, env=dict(os.environ, MEMEBOT_LIVE_SELL_AT=str(live), PYTHONUTF8="1"))
    out = {}
    for f in os.listdir(os.path.join(d, "out")) if os.path.isdir(os.path.join(d, "out")) else []:
        if f.endswith(".json") and "__" in f:
            out[f[:-5]] = json.load(open(os.path.join(d, "out", f)))
    return p, out


def c4(check):
    import memebot as M
    print("== chart exit C4: the scan")
    T = LIVE + H
    tmp = tempfile.mkdtemp(prefix="mb-chart-")
    try:
        d = os.path.join(tmp, "a")
        scan_dir(d, T, {"old": {"addr": "O" * 44, "sym": "OLD", "pair": "poolO", "t": T, "entryAt": T + 30 * MIN, "px": 1.0, "paper": M.OLD_PAPER_RULE}},
                 M.OLD_PAPER_RULE)
        p, out = run_scan(d, T + 2 * H, LIVE)
        eo, st = out.get("memeexit__old-1") or {}, out.get("memebot__state") or {}
        check(p.returncode == 0 and eo.get("why") == "reset" and st.get("paperRule") == M.PAPER_RULE and st.get("paperSince") == T + 2 * H
              and st.get("paperRuleSince") == T + 2 * H,
              "C4 the new key restarts the account once: the fixed rule's open position closed at the restart, the account counts from this run (%s; %s)" % (
                  eo.get("why"), p.stderr.strip()[-300:]))
        d2 = os.path.join(tmp, "b")
        pos = {"c1": {"addr": "A" * 44, "sym": "AAA", "pair": "poolA", "t": T, "entryAt": T + 30 * MIN, "px": 1.0, "paper": M.PAPER_RULE},
               "c2": {"addr": "B" * 44, "sym": "BBB", "pair": "poolB", "t": T, "entryAt": T + 30 * MIN, "px": 2.0, "paper": M.PAPER_RULE},
               "c3": {"addr": "C" * 44, "sym": "CCC", "pair": "poolC", "t": T, "entryAt": T + 30 * MIN, "px": 3.0, "paper": M.PAPER_RULE}}
        scan_dir(d2, T, pos, M.PAPER_RULE)
        json.dump({"v": 1, "t": T + 2 * H, "pos": {"c3": {"chk": T + 60 * MIN, "cpx": 3.0}},
                   "sold": {"c1": {"at": T + 70 * MIN, "why": "trail", "mult": 1.31, "rule": "chart"}, "c3": {"at": T + 65 * MIN, "why": "stop", "mult": 0.69}}},
                  open(os.path.join(d2, "pickwatch.json"), "w"))
        rows = lambda px, f: "\n".join("%d|%s|%s|%s|%s|500" % (T + i * MIN, px * f(i), px * f(i) * 1.01, px * f(i) * 0.99, px * f(i)) for i in range(29, 110)) + "\n"
        open(os.path.join(d2, "candles", "poolB_hold.txt"), "w").write(rows(2.0, lambda i: 1.0 if i < 80 else 0.8))
        open(os.path.join(d2, "candles", "poolC_hold.txt"), "w").write(rows(3.0, lambda i: 0.95 if i == 65 else 1.0))
        p, out = run_scan(d2, T + 2 * H, LIVE)
        e1, e2, st2 = out.get("memeexit__c1-1") or {}, out.get("memeexit__c2-1") or {}, out.get("memebot__state") or {}
        check(p.returncode == 0 and e1.get("why") == "trail" and e1.get("at") == T + 70 * MIN and e1.get("chart") == "live" and abs(e1["px"] - 1.31) < 1e-9,
              "C4 the watch's chart sale is booked at its minute and price, marked live (%s; %s)" % (e1, p.stderr.strip()[-300:]))
        check(e2.get("why") == "drop" and e2.get("at") == T + 109 * MIN and e2.get("hitAt") == T + 80 * MIN and e2.get("late") is True
              and e2.get("chart") == "scan" and abs(e2["px"] - 1.6) < 1e-9
              and "memeexit__c3-1" not in out and st2.get("paperRule") == M.PAPER_RULE and st2.get("paperSince") == T - 1,
              "C4 the scan's own candles: a fall to 0.8x in one minute is a drop (seen 40 minutes later: at the last close then, still 0.8x, "
              "at that minute, the drop's minute kept); a fixed-rule stop the watch made of a chart position is not booked (its 0.95x close "
              "sells nothing by the chart exit); no restart (%s)" % e2)
        os.makedirs(os.path.join(d2, "db", "memebot"), exist_ok=True)
        json.dump({"chk": {"c3": T + 100 * MIN}}, open(os.path.join(d2, "db", "memebot", "marks.json"), "w"))
        items = {it["pool"]: it for it in M.candle_items(d2, T + 3 * H)}
        check(items.get("poolC", {}).get("since") == T + 29 * MIN, "C4 the candles of a chart position are asked for from its entry, not from the last check (%s)" % items.get("poolC"))
        import fetch as F
        calls = []

        class Http:
            mock, dead = None, set()

            def get(self, u):
                calls.append(u)
                return None

            def log(self, s):
                pass
        F.candles(Http(), tmp, [{"pool": "poolC", "since": T, "hours": 5.5, "key": "hold"}, {"pool": "poolT", "since": T, "hours": 5.5, "key": "out"}])
        check("aggregate=1&limit=" in calls[0] and "aggregate=15&" in calls[1], "C4 a held position's 5.5 hours come as one-minute candles (a tip's window as 15-minute ones)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gt(rows):
    return {"data": {"attributes": {"ohlcv_list": [[r[0] // 1000, r[1], r[2], r[3], r[4], 500] for r in rows]}}}


def c5(check):
    import memebot as M, rocket_watch as RW
    print("== chart exit C5: the minute watch")
    T = LIVE + H
    tmp = tempfile.mkdtemp(prefix="mb-chart-")
    try:
        rk, mock = os.path.join(tmp, "rk"), os.path.join(tmp, "mock")
        os.makedirs(rk); os.makedirs(mock)
        row = lambda pid, a, pool, px: {"id": pid, "sym": pid.upper(), "addr": a, "pair": pool, "px": px, "t": T, "entryAt": T + 30 * MIN, "ticket": 50.0,
                                        "grp": "hold", "paper": M.PAPER_RULE, "left": 1.0, "cpx": None, "chk": None}
        json.dump({"v": 1, "t": T + H, "since": LIVE, "open": [row("pa", "A" * 44, "pA", 1.0), row("pb", "B" * 44, "pB", 2.0)]},
                  open(os.path.join(mock, "pickopen.json"), "w"))
        json.dump([{"baseToken": {"address": "A" * 44}, "pairAddress": "pA", "priceUsd": "1.5"}, {"baseToken": {"address": "B" * 44}, "pairAddress": "pB", "priceUsd": "2.0"}],
                  open(os.path.join(mock, "ds.json"), "w"))
        px = lambda i: 1.0 if i < 40 else (2.0 if i < 88 else 1.6)
        json.dump(gt([(T + i * MIN, px(i), px(i) * 1.01, px(i) * 0.99, px(i)) for i in range(29, 91)]), open(os.path.join(mock, "gt_pA_ohlcv.json"), "w"))
        json.dump(gt([(T + i * MIN, 2.0, 2.02, 1.96, 2.0) for i in range(29, 91)]), open(os.path.join(mock, "gt_pB_ohlcv.json"), "w"))
        json.dump({"pos": {}, "sold": {"pb": {"at": T + 60 * MIN, "why": "stop", "mult": 0.69}}}, open(os.path.join(rk, RW.PICK_FILE), "w"))
        now = [T + 90 * MIN]

        def sleep(x):
            now[0] += x * 1000
        with live_at(LIVE):
            out = RW.watch(rk, T + 92 * MIN, mock, clock=lambda: now[0], sleep=sleep)
            st = json.load(open(os.path.join(rk, RW.PICK_FILE)))
        sa, pb = st["sold"].get("pa") or {}, st["pos"].get("pb") or {}
        check(out.get("pick") == 1 and sa.get("why") == "trail" and sa.get("at") == T + 88 * MIN and abs(sa["mult"] - 1.6 * 0.99) < 1e-9 and sa.get("rule") == "chart"
              and "late" not in sa and "pb" not in st["sold"] and pb.get("lvl") == 0.5 and RW.pick_doc(st, now[0])["pos"]["pb"].get("lvl") == 0.5,
              "C5 a chart position falls from 2x to 1.6x, seen 2 minutes later: a trail at that minute's low, marked chart; the fixed-rule stop an older watch kept for the "
              "other is dropped and it is watched again, its level in the view (%s; %s)" % (sa, pb))
        rk2, mock2 = os.path.join(tmp, "rk2"), os.path.join(tmp, "mock2")
        os.makedirs(rk2); os.makedirs(mock2)
        json.dump({"v": 1, "t": T + H, "since": LIVE, "open": [row("pc", "C" * 44, "pC", 1.0)]}, open(os.path.join(mock2, "pickopen.json"), "w"))
        n5, outs = [T + 2 * H], []

        def sleep5(x):
            n5[0] += x * 1000
        with live_at(LIVE):
            for v in ("1.6", "1.9", "1.6"):
                json.dump([{"baseToken": {"address": "C" * 44}, "pairAddress": "pC", "priceUsd": v}], open(os.path.join(mock2, "ds.json"), "w"))
                outs.append(RW.watch(rk2, n5[0] + 30_000, mock2, clock=lambda: n5[0], sleep=sleep5))
                n5[0] += MIN
            st5 = json.load(open(os.path.join(rk2, RW.PICK_FILE)))
        sc = st5["sold"].get("pc") or {}
        check([o.get("pick", 0) for o in outs] == [0, 0, 1] and sc.get("why") == "trail" and abs(sc["mult"] - 1.6) < 1e-9 and sc.get("rule") == "chart",
              "C5 a pool without candles: the trail on DexScreener's best price (1.9x), 1.6x sells (%s)" % outs)
        # Chop on 26 Oct: the trail's minute came while a Radar round ran; the watch saw it 8 minutes later, the price far lower by then
        rk3, mock3 = os.path.join(tmp, "rk3"), os.path.join(tmp, "mock3")
        os.makedirs(rk3); os.makedirs(mock3)
        json.dump({"v": 1, "t": T + H, "since": LIVE, "open": [row("pd", "D" * 44, "pD", 1.0)]}, open(os.path.join(mock3, "pickopen.json"), "w"))
        json.dump([{"baseToken": {"address": "D" * 44}, "pairAddress": "pD", "priceUsd": "0.3"}], open(os.path.join(mock3, "ds.json"), "w"))
        pd = lambda i: 1.0 if i < 40 else (2.0 if i < 80 else (1.6 if i < 84 else 0.6))
        json.dump(gt([(T + i * MIN, pd(i), pd(i) * 1.01, pd(i) * 0.99, pd(i)) for i in range(29, 89)]), open(os.path.join(mock3, "gt_pD_ohlcv.json"), "w"))
        n3 = [T + 88 * MIN + 20_000]

        def sleep3(x):
            n3[0] += x * 1000
        with live_at(LIVE):
            out3 = RW.watch(rk3, n3[0] + 30_000, mock3, clock=lambda: n3[0], sleep=sleep3)
            st3 = json.load(open(os.path.join(rk3, RW.PICK_FILE)))
            tmpd = os.path.join(tmp, "w3")
            os.makedirs(tmpd)
            json.dump(RW.pick_doc(st3, n3[0]), open(os.path.join(tmpd, "pickwatch.json"), "w"))
            _, ls3 = M.live_watch(tmpd)
        sd = st3["sold"].get("pd") or {}
        check(out3.get("pick") == 1 and sd.get("why") == "trail" and sd.get("at") == T + 88 * MIN and abs(sd["mult"] - 0.6) < 1e-9 and sd.get("late") is True
              and sd.get("hitAt") == T + 80 * MIN and sd.get("rule") == "chart"
              and ls3.get("pd") == {"at": T + 88 * MIN, "why": "trail", "mult": sd["mult"], "late": True, "hitAt": T + 80 * MIN, "rule": "chart"},
              "C5 a trail seen 8 minutes after its minute (a round ran; Chop on 26 Oct): booked at the last close then (0.6x, not the 1.58x low "
              "of its minute), at that minute, the trail's minute kept; the scan takes it so (%s; %s)" % (sd, ls3.get("pd")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c6(check):
    import memebot as M, shadow as SH
    print("== chart exit C6: the shadow rules K and X")
    entry = LIVE + H
    c = [[i * 60, (1.0 if i < 20 else 1.8) if i < 60 else 1.45, 1000] for i in range(0, 360)]
    w = [[i * 60, r[1] * 1.01, r[1] * 0.99] for i, r in enumerate(c)]
    doc = {"entryAt": entry, "cpx": 1.0, "c": c, "w": w, "dead": None}
    rules = {r["id"]: r for r in SH.RULES}
    with live_at(LIVE):
        k, x = SH.replay(doc, rules["K"]), SH.replay(doc, rules["X"])
        hc = M.chart_hit([(entry + r[0] * 1000, r[1], wr[1], wr[2], r[1]) for r, wr in zip(c, w)], entry, None, 1.0)
    check(k["why"] == "time" and abs(k["sales"][0][2] - 1.45) < 1e-9 and x["why"] == "trail" and x["sales"][0][0] == entry + 60 * MIN and abs(x["sales"][0][2] - 1.45 * 0.99) < 1e-9
          and (x["sales"][0][0], x["sales"][0][2]) == (hc["hit"], hc["mult"]) and SH.CONTROL == "K" and rules["K"]["stop"] == M.HOLD_STOP,
          "C6 up to 1.8x, then 1.45x: K (the fixed rule) holds to 6 h, X (the chart exit) trails out at that minute, as chart_hit (%s, %s)" % (k["why"], x["why"]))


def c7(check):
    import memebot as M, report as R, page_home as PH
    print("== chart exit C7: the words, the constants, the key")
    with live_at(LIVE):
        txt = R.hold_rule_text(LIVE + H)
        t0 = LIVE + H
        cands = [(t0 + i * MIN, 1.0, 1.01, 0.99, 1.0) for i in range(0, 5)] + [(t0 + 5 * MIN, 1.7, 1.8, 1.6, 1.7)]
        p = {"sym": "AAA", "grp": "hold", "ticket": 50.0, "px": 1.0, "t": t0, "entryAt": t0, "paper": M.PAPER_RULE, "addr": "A" * 44, "pair": "pA"}
        card = R.hold_card({"p": p, "entry": 1.0, "ticket": 50.0, "mult": 1.7, "pnl": 33.0, "last": 1.7, "value": 83.0, "liq_now": None, "candles": cands, "cpx": 1.0},
                           t0 + 10 * MIN)
        card0 = R.hold_card({"p": dict(p, paper=M.OLD_PAPER_RULE), "entry": 1.0, "ticket": 50.0, "mult": 1.0, "pnl": -1.0, "last": 1.0, "value": 49.0,
                             "liq_now": None, "candles": cands[:5], "cpx": 1.0}, t0 + 10 * MIN)
        words = (M.exit_word("stop", "hold", M.is_chart(p)), M.exit_word("stop", "hold", M.is_chart(dict(p, paper=M.OLD_PAPER_RULE))), M.exit_word("trail", "hold"),
                 M.exit_word("drop", "hold"))
        chart_p = M.is_chart(p) and not M.is_chart(dict(p, entryAt=LIVE - H, t=LIVE - H)) and not M.is_chart(dict(p, paper=M.OLD_PAPER_RULE))
    check("15% under the highest price so far" in txt and "15% or more under its close 30 minutes before" in txt and "reaches 50% of the entry price" in txt
          and "shadow rule" in txt and M.PAPER_LABEL in txt,
          "C7 the rule text names the trail, the drop, the floor and the shadow rule")
    check("trailing stop at" in card and "stop −50%" in card and "trailing stop" not in card0 and "stop −30%" in card0,
          "C7 the position card: a chart position shows its floor and its armed trail, a fixed-rule one its −30% stop")
    check(words == ("stop-loss -50%", "stop-loss -30%", "trailing stop: 15% under its high", "fell 15% within 30 minutes") and chart_p
          and PH.PICK_STOP_CHART == "stop −50%" and PH.PICK_WHY["stop"] == "stop −30%",
          "C7 the stop's words by the position's rule; a position is the chart exit's only with its key and on the live chart (%s)" % (words,))
    check(M.PAPER_RULE == "v3: top 50 / chart exit: -50% floor, trail 15% from 1.5x, -15% in 30 min, 11x, 6h" and M.CHART_RULES == (M.PAPER_RULE,)
          and M.OLD_PAPER_RULE == "v2: top 50 / young 3 / +1000% / -30% / 6h"
          and (M.CHART_STOP, M.CHART_TRAIL, M.CHART_ARM, M.CHART_DROP, M.CHART_DROP_MIN) == (0.50, 0.15, 1.5, 0.15, 30)
          and (M.HOLD_STOP, M.HOLD_TP, M.HOLD_MAX_H) == (0.30, 10.0, 6.0),
          "C7 the key v3 and the chart exit's levels as tested (-50 %, 15 % from 1.5x, -15 % in 30 min); the fixed rule's constants unchanged")


def c8(check):
    import memebot as M, report as R, page_home as PH
    print("== chart exit C8: the sell bot, its card and its Start row")
    with live_at(LIVE):
        t0, now = LIVE + H, LIVE + H + 10 * MIN
        cands = [(t0 + i * MIN, 1.0, 1.01, 0.99, 1.0) for i in range(0, 5)] + [(t0 + 5 * MIN, 1.7, 1.8, 1.6, 1.7)]
        p = {"_id": "p1", "sym": "AAA", "grp": "hold", "ticket": 50.0, "px": 1.0, "t": t0, "entryAt": t0, "paper": M.PAPER_RULE, "addr": "A" * 44, "pair": "pA"}
        r = {"id": "p1", "p": p, "entry": 1.0, "last": 1.7, "candles": cands, "cpx": 1.0}
        armed = PH.sell_bot({"now": now, "dir": ""}, R, [r])
        waiting = PH.sell_bot({"now": now, "dir": ""}, R, [dict(r, candles=cands[:5], last=1.0)])
        empty = PH.sell_bot({"now": now, "dir": ""}, R, [])
        fixed = PH.sell_bot({"now": now, "dir": ""}, R, [dict(r, p=dict(p, paper=M.OLD_PAPER_RULE))])
        row = PH.sell_bot_row({"now": now, "dir": "", "open": [r]}, R)
        before = PH.sell_bot({"now": LIVE - H, "dir": ""}, R, [r]) + PH.sell_bot_row({"now": LIVE - H, "dir": "", "open": [r]}, R)
        end = PH.hhmm(R, t0 + 6 * H)
    check('id="sell-bot"' in armed and 'data-sb-pos="p1"' in armed and "now +70%" in armed
          and "Profit lock ON: sells if the price falls to $1.53 (+53%), 15% under its best price $1.80 (+80%)." in armed
          and "at the latest at %s (after 6 h)" % end in armed,
          "C8 an armed trail: the card names the price it sells at, 15% under the best price, and the 6-hour minute")
    check("Profit lock switches on at $1.50 (+50%)" in waiting and "Best so far +1%." in waiting and "Profit lock ON" not in waiting,
          "C8 before 1.5x: where the trail arms, the best price so far")
    check("Nothing to sell right now" in empty and "data-sb-pos" not in empty and "data-sb-pos" not in fixed and before == "",
          "C8 no position, a fixed-rule position: an empty card; before the live chart neither card nor row")
    check('data-open="sell-bot"' in row and "SELL BOT" in row and "watching AAA every minute" in row and "for the Pick account" in row,
          "C8 the Start row: what it watches, a tap opens its card")
    home = open(os.path.join(HERE, "page_home.py"), encoding="utf-8").read()
    check("eq.%s'" % M.LIVE_WATCH_ROW in PH.SB_JS and "innerHTML" not in PH.SB_JS and "sb = sell_bot(D, R, opn)" in home and "sb + lp" in home,
          "C8 the live script reads the watch's row, text only; the card sits in the Pick account block, the row under the accounts")


def checks(check, skips=None):
    c1(check)
    c2(check)
    c3(check)
    c4(check)
    c5(check)
    c6(check)
    c7(check)
    c8(check)


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
