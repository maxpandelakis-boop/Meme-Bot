#!/usr/bin/env python3
"""selftest_livesell.py: the Pick account sells on the live chart from memebot.LIVE_SELL_AT on (the user's go of Oct 24). Fake money only:
the fixtures are hand-made candles and docs, nothing is fetched.

  L1 memebot.hold_hit: before LIVE_SELL_AT a minute counts with its close (a wick sells nothing, as before); from it on the minute's low
     at 0.70x cpx is the stop (booked at that low), its high at 11x the take-profit, both in one minute the stop; a wick more than
     CANDLE_WICK_X beyond its close is a glitch; a high over CANDLE_MAX_X falls back to the close; nothing sells from the live 6-hour
     limit on (hold_end, entry + 6 h; None when that comes before LIVE_SELL_AT); hold_x6 is the price at it
  L2 memebot.live_watch keeps only real sales of the minute watch (from LIVE_SELL_AT on; a take-profit at exactly 11x, a stop never above
     0.70x) and where each watched position's next look starts
  L3 memebot.py run books what the watch sold at its minute ("chart": "live"), judges only the minutes the watch did not see with its
     own candles ("chart": "scan"), sells at the live 6-hour limit at that minute's price, keeps the rule (no restart), and leaves the
     open positions for the watch (db/memebot/pickopen.json)
  L4 rocket_watch.watch looks at the Pick's open positions every minute from LIVE_SELL_AT on (the scan's list), sells on the low, keeps
     the sale for the scan (pick_live.json, picklog), sells at the 6-hour limit at DexScreener's price, drops what the scan booked;
     a pool without candles is judged on DexScreener's price of the minute; before LIVE_SELL_AT it does nothing for the Pick
  L5 shadow.replay: a buy from LIVE_SELL_AT on is replayed on the minute's low and high (the path's "w"), every rule alike; an older one
     on closes as before
  L6 the page: the rule's words (live chart, every minute) and the Pick tab's live line with its script after LIVE_SELL_AT, the old words
     before; bot.py reads the watch's row before the run and hands the open positions over after it; no workflow sets
     MEMEBOT_LIVE_SELL_AT

  python3 selftest_livesell.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
"""
import contextlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MIN, H = 60_000, 3_600_000
LIVE = 1_900_000_000_000          # a made-up switch, far after every real date, so the checks do not depend on the clock


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


def l1(check):
    import memebot as M
    print("== live sell L1: hold_hit on closes before, on lows and highs after")
    t0 = LIVE - 2 * H
    wick = [cnd(t0, 1.0), cnd(t0 + MIN, 1.0, lo=0.5), cnd(t0 + 2 * MIN, 0.69)]
    old = M.hold_hit(wick, t0, None, None, live_at=LIVE + 10 * H)
    new = M.hold_hit(wick, t0, None, None, live_at=t0)
    check(old["why"] == "stop" and old["hit"] == t0 + 2 * MIN and abs(old["mult"] - 0.69) < 1e-9 and new["why"] == "stop" and new["hit"] == t0 + MIN
          and abs(new["mult"] - 0.5) < 1e-9, "L1 a wick to 0.5x: before the switch nothing (the close at 0.69x sells), from it on the stop at that minute and its low (%s, %s)" % (old, new))
    both = M.hold_hit([cnd(t0, 1.0), cnd(t0 + MIN, 2.0, hi=12.0, lo=0.6)], t0, None, None, live_at=t0)
    tp = M.hold_hit([cnd(t0, 1.0), cnd(t0 + MIN, 3.0, hi=11.5)], t0, None, None, live_at=t0)
    check(both["why"] == "stop" and abs(both["mult"] - 0.6) < 1e-9 and tp["why"] == "tp" and tp["hit"] == t0 + MIN,
          "L1 a high at 11x sells, a low at -30%% in the same minute wins (the safe side) (%s, %s)" % (both["why"], tp["why"]))
    glitch = M.hold_hit([cnd(t0, 1.0), cnd(t0 + MIN, 1.0, lo=0.15), cnd(t0 + 2 * MIN, 2.4, hi=40.0)], t0, None, None, live_at=t0)
    check(glitch["hit"] is None and glitch["fresh"] is True and M.hold_wicks(cnd(0, 1.0, hi=6.0, lo=0.1)) == (1.0, 1.0) and M.hold_wicks(cnd(0, 1.0, hi=0.5, lo=2.0)) == (1.0, 1.0),
          "L1 a low more than 5x under its close and a high over 30x are glitches, not sales (%s)" % glitch)
    late = [cnd(t0, 1.0)] + [cnd(t0 + i * MIN, 1.2) for i in range(1, 361)] + [cnd(t0 + 361 * MIN, 0.5)]
    hl = M.hold_hit(late, t0, None, None, live_at=t0)
    with live_at(t0):
        x6, x6n = M.hold_x6(late, t0, 1.0), M.hold_x6(late[:100], t0, 1.0)
        end, end_old = M.hold_end(t0), M.hold_end(t0 - 7 * H)
    check(hl["hit"] is None and end == t0 + 6 * H and end_old is None and abs(x6 - 1.2) < 1e-9 and x6n is None,
          "L1 nothing sells from entry + 6 h on (the limit comes first) and hold_x6 is the close before it; a limit before the switch is the old rule's (%s, %s)" % (end, x6))
    chk = M.hold_hit(wick, t0, t0 + 2 * MIN, 1.0, live_at=t0)
    check(chk["hit"] == t0 + 2 * MIN and chk["cpx"] == 1.0, "L1 the minutes before the last check are not looked at again")


def l2(check):
    import memebot as M
    print("== live sell L2: what the scan takes from the minute watch")
    tmp = tempfile.mkdtemp(prefix="mb-live-")
    try:
        json.dump({"v": 1, "t": LIVE + H, "pos": {"a": {"chk": LIVE + 5 * MIN, "cpx": 2.0}, "b": {"chk": None, "cpx": -1}, "c": "x"},
                   "sold": {"s1": {"at": LIVE + MIN, "why": "stop", "mult": 0.9}, "s2": {"at": LIVE + MIN, "why": "tp", "mult": 25.0},
                            "s3": {"at": LIVE - MIN, "why": "stop", "mult": 0.5}, "s4": {"at": LIVE + MIN, "why": "rug", "mult": 0.5},
                            "s5": {"at": LIVE + MIN, "why": "time", "mult": 1.3}, "s6": {"at": LIVE + MIN, "why": "stop", "mult": 0}}},
                  open(os.path.join(tmp, "pickwatch.json"), "w"))
        with live_at(LIVE):
            seen, sold = M.live_watch(tmp)
        none = M.live_watch(os.path.join(tmp, "nothing"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check(seen == {"a": {"chk": LIVE + 5 * MIN, "cpx": 2.0}, "b": {"chk": None, "cpx": None}} and sorted(sold) == ["s1", "s2", "s5"]
          and sold["s1"]["mult"] == 0.7 and sold["s2"]["mult"] == 11.0 and sold["s5"]["mult"] == 1.3 and none == ({}, {}),
          "L2 only stops, take-profits and time sales from the switch on; a stop never above 0.70x, a take-profit exactly 11x (%s)" % sold)


def scan_dir(d, t, pos):
    import memebot as M
    for sub in ("db/memepos", "db/memeexit", "db/memebot", "candles"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    for k, v in pos.items():
        json.dump(dict(v, grp="hold", ticket=50.0, paper=M.PAPER_RULE, rule=M.RULE), open(os.path.join(d, "db", "memepos", k + ".json"), "w"))
    json.dump({"paperRule": M.PAPER_RULE, "paperSince": t - 1, "paperRuleSince": t - 1}, open(os.path.join(d, "db", "memebot", "state.json"), "w"))


def run_scan(d, now, live):
    p = subprocess.run([sys.executable, os.path.join(HERE, "memebot.py"), "run", "--mode", "check", "--dir", d, "--now", str(now), "--horizon", "2h"],
                       capture_output=True, text=True, env=dict(os.environ, MEMEBOT_LIVE_SELL_AT=str(live), PYTHONUTF8="1"))
    out = {}
    for f in os.listdir(os.path.join(d, "out")) if os.path.isdir(os.path.join(d, "out")) else []:
        if f.endswith(".json") and "__" in f:
            out[f[:-5]] = json.load(open(os.path.join(d, "out", f)))
    return p, out


def l3(check):
    import memebot as M
    print("== live sell L3: the scan books the watch's sales at their minute")
    T = LIVE + H
    tmp = tempfile.mkdtemp(prefix="mb-live-")
    try:
        d = os.path.join(tmp, "a")
        scan_dir(d, T, {"p1": {"addr": "A" * 44, "sym": "AAA", "pair": "poolA", "t": T, "entryAt": T + 30 * MIN, "px": 1.0},
                        "p2": {"addr": "B" * 44, "sym": "BBB", "pair": "poolB", "t": T, "entryAt": T + 30 * MIN, "px": 2.0},
                        "p3": {"addr": "C" * 44, "sym": "CCC", "pair": "poolC", "t": T, "entryAt": T + 30 * MIN, "px": 3.0}})
        json.dump({"v": 1, "t": T + 2 * H, "pos": {"p2": {"chk": T + 80 * MIN, "cpx": 2.0}, "p3": {"chk": T + 100 * MIN, "cpx": 3.0}},
                   "sold": {"p1": {"at": T + 70 * MIN, "why": "stop", "mult": 0.62}}}, open(os.path.join(d, "pickwatch.json"), "w"))
        rows = lambda px, dips: "\n".join("%d|%s|%s|%s|%s|500" % (T + i * MIN, px, px * 1.01, px * (0.6 if i in dips else 0.98), px) for i in range(30, 120)) + "\n"
        open(os.path.join(d, "candles", "poolB_hold.txt"), "w").write(rows(2.0, (75, 95)))
        open(os.path.join(d, "candles", "poolC_hold.txt"), "w").write(rows(3.0, ()))
        p, out = run_scan(d, T + 2 * H, LIVE)
        e1, e2 = out.get("memeexit__p1-1") or {}, out.get("memeexit__p2-1") or {}
        po, st = out.get("memebot__pickopen") or {}, out.get("memebot__state") or {}
        check(p.returncode == 0 and e1.get("why") == "stop" and e1.get("at") == T + 70 * MIN and e1.get("chart") == "live" and abs(e1["px"] - 0.62) < 1e-9
              and e1.get("eur") == round(M.pos_value({"ticket": 50.0, "grp": "hold", "paper": M.PAPER_RULE}, 1.0, 0.62), 2),
              "L3 the watch's stop is booked at its minute and its price, marked live (%s; %s)" % (e1, p.stderr.strip()[-300:]))
        check(e2.get("why") == "stop" and e2.get("at") == T + 95 * MIN and e2.get("chart") == "scan" and abs(e2["px"] - 1.2) < 1e-9 and "memeexit__p3-1" not in out,
              "L3 a dip the watch already saw is not looked at again; one after its last look is the scan's own stop, at that minute's low (%s)" % e2)
        check([r["id"] for r in po.get("open") or []] == ["p3"] and po.get("since") == LIVE and (po["open"][0].get("cpx") == 3.0) and st.get("paperRule") == M.PAPER_RULE
              and st.get("paperSince") == T - 1 and not any((x.get("why") == "reset") for k, x in out.items() if k.startswith("memeexit")),
              "L3 the open position stays for the watch (pickopen: id, cpx), the rule and the account's start unchanged, nothing reset")
        # the live 6-hour limit: the candles reach entry + 6 h, the run comes later: sold at the close before the limit, at that minute
        d2 = os.path.join(tmp, "b")
        scan_dir(d2, T, {"p4": {"addr": "D" * 44, "sym": "DDD", "pair": "poolD", "t": T, "entryAt": T + 30 * MIN, "px": 1.0}})
        open(os.path.join(d2, "candles", "poolD_hold.txt"), "w").write(
            "\n".join("%d|1|1.3|1.0|%s|500" % (T + i * MIN, (1.0 if i < 60 else 1.25) if i < 390 else 0.2) for i in range(30, 420)) + "\n")
        p, out = run_scan(d2, T + 7 * H, LIVE)
        e4 = out.get("memeexit__p4-1") or {}
        check(p.returncode == 0 and e4.get("why") == "time" and e4.get("at") == T + 30 * MIN + 6 * H and abs(e4["px"] - 1.25) < 1e-9 and e4.get("chart") == "scan",
              "L3 the 6-hour limit sells 6 hours after the entry at that minute's price, a crash after it does not count (%s)" % e4)
        # before the switch: the old rule's way (a wick sells nothing, the watch's file is not taken)
        d3 = os.path.join(tmp, "c")
        scan_dir(d3, T, {"p5": {"addr": "E" * 44, "sym": "EEE", "pair": "poolE", "t": T, "entryAt": T + 30 * MIN, "px": 1.0}})
        open(os.path.join(d3, "candles", "poolE_hold.txt"), "w").write(rows(1.0, (75,)))
        json.dump({"v": 1, "sold": {"p5": {"at": T + 40 * MIN, "why": "stop", "mult": 0.5}}}, open(os.path.join(d3, "pickwatch.json"), "w"))
        p, out = run_scan(d3, T + 2 * H, LIVE + 100 * H)
        check(p.returncode == 0 and not any(k.startswith("memeexit") for k in out), "L3 before the switch a wick sells nothing and no watch sale is taken")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gt(rows):
    return {"data": {"attributes": {"ohlcv_list": [[r[0] // 1000, r[1], r[2], r[3], r[4], 500] for r in rows]}}}


def l4(check):
    import memebot as M, rocket_watch as RW
    print("== live sell L4: the minute watch on the Pick account")
    T = LIVE + H
    tmp = tempfile.mkdtemp(prefix="mb-live-")
    try:
        rk, mock = os.path.join(tmp, "rk"), os.path.join(tmp, "mock")
        os.makedirs(rk); os.makedirs(mock)
        row = lambda pid, a, pool, px: {"id": pid, "sym": pid.upper(), "addr": a, "pair": pool, "px": px, "t": T, "entryAt": T + 30 * MIN, "ticket": 50.0,
                                        "grp": "hold", "paper": M.PAPER_RULE, "left": 1.0, "cpx": None, "chk": None}
        json.dump({"v": 1, "t": T + H, "since": LIVE, "open": [row("pa", "A" * 44, "pA", 1.0), row("pb", "B" * 44, "pB", 2.0)]},
                  open(os.path.join(mock, "pickopen.json"), "w"))
        now = [T + 90 * MIN]
        json.dump([{"baseToken": {"address": "A" * 44}, "pairAddress": "pA", "priceUsd": "1.1"}, {"baseToken": {"address": "B" * 44}, "pairAddress": "pB", "priceUsd": "2.4"}],
                  open(os.path.join(mock, "ds.json"), "w"))
        json.dump(gt([(T + i * MIN, 1.0, 1.02, 0.66 if i == 88 else 0.98, 1.0) for i in range(30, 91)]), open(os.path.join(mock, "gt_pA_ohlcv.json"), "w"))
        json.dump(gt([(T + i * MIN, 2.0, 2.02, 1.96, 2.0) for i in range(30, 91)]), open(os.path.join(mock, "gt_pB_ohlcv.json"), "w"))

        def sleep(x):
            now[0] += x * 1000
        with live_at(LIVE):
            out = RW.watch(rk, T + 93 * MIN, mock, clock=lambda: now[0], sleep=sleep)
            st = json.load(open(os.path.join(rk, RW.PICK_FILE)))
            logs = [json.loads(l) for f in os.listdir(os.path.join(rk, RW.PICK_LOG)) for l in open(os.path.join(rk, RW.PICK_LOG, f))]
            sa = st["sold"].get("pa") or {}
            check(out.get("pick") == 1 and out["looks"] == 3 and sa.get("why") == "stop" and sa.get("at") == T + 88 * MIN and abs(sa["mult"] - 0.66) < 1e-9
                  and sa.get("pnl") == round(M.pos_value({"ticket": 50.0, "grp": "hold", "paper": M.PAPER_RULE}, 1.0, 0.66) - 50.0, 2)
                  and [l.get("id") for l in logs] == ["pa"] and not os.path.exists(os.path.join(rk, "rocket.json")),
                  "L4 a dip to 0.66x on a minute's low sells the Pick position at that minute; kept for the scan and logged once (%s)" % out)
            pb = st["pos"].get("pb") or {}
            check("pb" not in st["sold"] and pb.get("cpx") == 2.0 and pb.get("chk") == T + 90 * MIN and pb.get("now") == 1.0 and RW.pick_doc(st, now[0])["pos"].keys() == {"pb"},
                  "L4 the other one is watched on: its candle entry price, where the next look starts, its price now (%s)" % pb)
            # 6 hours after the entry: the next look sells at DexScreener's price; the scan has booked pa meanwhile (no longer listed)
            json.dump({"v": 1, "t": T + 2 * H, "since": LIVE, "open": [row("pb", "B" * 44, "pB", 2.0)]}, open(os.path.join(mock, "pickopen.json"), "w"))
            now[0] = T + 30 * MIN + 6 * H + 20_000
            json.dump(gt([(T + i * MIN, 2.0, 2.02, 1.96, 2.0) for i in range(30, 391)]), open(os.path.join(mock, "gt_pB_ohlcv.json"), "w"))
            out2 = RW.watch(rk, now[0] + 2 * MIN, mock, clock=lambda: now[0], sleep=sleep)
            st2 = json.load(open(os.path.join(rk, RW.PICK_FILE)))
            sb = st2["sold"].get("pb") or {}
            check(out2.get("pick") == 1 and sb.get("why") == "time" and abs(sb["mult"] - 1.2) < 1e-9 and (st2["sold"].get("pa") or {}).get("booked")
                  and list(st2["pos"]) == ["pb"] and RW.pick_doc(st2, now[0])["pos"] == {},
                  "L4 the 6-hour limit sells at the price of that minute; a sale the scan booked stays in the view a day, marked booked (%s)" % out2)
            # pools GeckoTerminal has no candles for: the stop and the take-profit on DexScreener's price of that minute (as the scan
            # judges them on its own price then); one in between stays open
            rk2, mock2 = os.path.join(tmp, "rk2"), os.path.join(tmp, "mock2")
            os.makedirs(rk2); os.makedirs(mock2)
            json.dump({"v": 1, "t": T + H, "since": LIVE, "open": [row("pc", "C" * 44, "pC", 1.0), row("pd", "D" * 44, "pD", 1.0), row("pe", "E" * 44, "pE", 1.0)]},
                      open(os.path.join(mock2, "pickopen.json"), "w"))
            json.dump([{"baseToken": {"address": a * 44}, "pairAddress": "p" + a, "priceUsd": v} for a, v in (("C", "0.65"), ("D", "11.5"), ("E", "0.8"))],
                      open(os.path.join(mock2, "ds.json"), "w"))
            n5 = [T + 2 * H]

            def sleep5(x):
                n5[0] += x * 1000
            out5 = RW.watch(rk2, T + 2 * H + 30_000, mock2, clock=lambda: n5[0], sleep=sleep5)
            st5 = json.load(open(os.path.join(rk2, RW.PICK_FILE)))
            sc, sd = st5["sold"].get("pc") or {}, st5["sold"].get("pd") or {}
            check(out5.get("pick") == 2 and sc.get("why") == "stop" and sc.get("at") == T + 2 * H and abs(sc["mult"] - 0.65) < 1e-9
                  and sd.get("why") == "tp" and sd.get("mult") == 1.0 + M.HOLD_TP and "pe" not in st5["sold"] and RW.pick_doc(st5, n5[0])["pos"].keys() == {"pe"},
                  "L4 a pool without candles: DexScreener's price of the minute at 0.65x is a stop at that price, at 11.5x a take-profit at 11x, "
                  "0.8x stays open (%s)" % out5)
            out3 = RW.watch(rk, now[0] + 2 * MIN, os.path.join(tmp, "none"), clock=lambda: now[0], sleep=sleep)
        with live_at(LIVE + 100 * H):
            os.remove(os.path.join(rk, RW.PICK_FILE))
            out4 = RW.watch(rk, T + 93 * MIN, mock, clock=lambda: T + 90 * MIN, sleep=sleep)
        check(out3 == {"looks": 0, "sold": 0, "why": "no state"} and out4 == {"looks": 0, "sold": 0, "why": "no state"} and not os.path.exists(os.path.join(rk, RW.PICK_FILE)),
              "L4 nothing open in either account: the watch ends at once; before the switch it does nothing for the Pick (%s, %s)" % (out3, out4))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def l5(check):
    import shadow as SH
    print("== live sell L5: the shadow rules on the live chart for new buys")
    entry = LIVE + H
    c = [[i * 60, 1.0 if i != 10 else 0.95, 1000] for i in range(0, 300)]
    w = [[i * 60, 3.1 if i == 20 else 1.02, 0.98 if i != 10 else 0.6] for i in range(0, 300)]
    doc = {"entryAt": entry, "cpx": 1.0, "c": c, "w": w, "dead": None}
    rules = {r["id"]: r for r in SH.RULES}
    with live_at(LIVE):
        k, a, b = SH.replay(doc, rules["K"]), SH.replay(doc, rules["A"]), SH.replay(doc, rules["B"])
        old = SH.replay(dict(doc, entryAt=LIVE - 10 * H), rules["K"])
        now_w = SH.replay(dict(doc, w=None), rules["A"])
    check(k["why"] == "stop" and k["sales"][0][0] == entry + 600_000 and abs(k["sales"][0][2] - 0.6) < 1e-9 and a["why"] == "stop" and a["sales"][0][0] == entry + 600_000
          and b["why"] == "tp" and b["sales"][0][0] == entry + 1_200_000 and old["why"] == "time" and now_w["why"] == "time",
          "L5 a new buy sells on the low (K and A at the 0.6x dip) and the high (B's 2x on the 3.1x wick); an older one and a path without lows stay on closes (%s %s %s %s)" % (
              k["why"], a["why"], b["why"], old["why"]))
    rows = [[entry + i * MIN, 1.0, 1.2, 0.9, 1.0, 100.0] for i in range(-1, 5)]
    check(SH.wicks(rows, entry, entry + 3 * MIN, 1.0) == [[-60, 1.2, 0.9], [0, 1.2, 0.9], [60, 1.2, 0.9], [120, 1.2, 0.9]],
          "L5 each path keeps its minutes' highs and lows over cpx, row for row as its closes")


def l6(check):
    import memebot as M, report as R, page_home as PH, bot as B
    print("== live sell L6: the page, bot.py and the workflows")
    with live_at(LIVE):
        txt_new, txt_old = R.hold_rule_text(LIVE + H), R.hold_rule_text(LIVE - H)
        opn = [{"p": {"_id": "p1", "sym": "AAA", "grp": "hold"}}]
        box, box0 = PH.pick_live(opn, LIVE + H), PH.pick_live(opn, LIVE - H)
    check("on the live chart, looked at every minute" in txt_new and "booked at that low" in txt_new and "first scan after about" not in txt_new
          and "at the first scan after about 6 hours" in txt_old and "minute candle that closes at 11 times" in txt_old,
          "L6 the rule's words: the live chart after the switch, the old ones before")
    check('data-pk-box data-pk-open="[&quot;p1&quot;]" hidden' in box and box0 == "" and "eq.%s'" % M.LIVE_WATCH_ROW in PH.PK_LIVE_JS and "innerHTML" not in PH.PK_LIVE_JS,
          "L6 the Pick tab's live line (the open ids, hidden until the row answers) only after the switch; its script reads the watch's row, text only")
    tmp = tempfile.mkdtemp(prefix="mb-live-")
    calls = []

    class FakeApp:
        @staticmethod
        def get_row(rid):
            calls.append(("get", rid))
            return {"v": 1, "t": LIVE, "pos": {}, "sold": {"x": {"at": LIVE, "why": "stop", "mult": 0.6}}}

        @staticmethod
        def put_row(rid, doc):
            calls.append(("put", rid, doc))
    saved = B.app_mod
    try:
        os.makedirs(os.path.join(tmp, "db", "memebot"))
        json.dump({"v": 1, "open": []}, open(os.path.join(tmp, "db", "memebot", "pickopen.json"), "w"))
        open(os.path.join(tmp, "pickwatch.json"), "w").write("{}")
        B.app_mod = lambda: FakeApp
        with live_at(0):
            got = B.live_watch_in(tmp)
            kept = json.load(open(os.path.join(tmp, "pickwatch.json")))
            put = B.live_open_out(tmp)
        B.app_mod = lambda: None
        open(os.path.join(tmp, "pickwatch.json"), "w").write("{}")
        with live_at(0):
            gone = B.live_watch_in(tmp) is None and not os.path.exists(os.path.join(tmp, "pickwatch.json"))
    finally:
        B.app_mod = saved
        shutil.rmtree(tmp, ignore_errors=True)
    check(got and kept.get("sold", {}).get("x") and put is True and calls == [("get", "pickwatch"), ("put", "pickopen", {"v": 1, "open": []})] and gone,
          "L6 bot.py: the watch's row saved for the run, the open positions handed over after it; without the store the old file goes")
    src = open(os.path.join(HERE, "bot.py"), encoding="utf-8").read()
    i = src.find('r = run(["memebot.py", "run"')
    check(0 < src.rfind("live_watch_in(d)", 0, i) and i - src.rfind("live_watch_in(d)", 0, i) < 300 and 0 < src.find("live_open_out(d)", i) - i < 600,
          "L6 bot.py reads the watch right before the run and hands the open positions over right after it")
    flows = {f: open(os.path.join(HERE, ".github", "workflows", f), encoding="utf-8").read() for f in os.listdir(os.path.join(HERE, ".github", "workflows"))}
    check(flows and not any("MEMEBOT_LIVE_SELL_AT" in t for t in flows.values()), "L6 no workflow sets MEMEBOT_LIVE_SELL_AT (the switch is memebot.LIVE_SELL_AT)")
    import datetime as dt
    check(dt.datetime.fromtimestamp(M.LIVE_SELL_AT / 1000, dt.timezone.utc).minute == 0 and M.PAPER_RULE == "v2: top 50 / young 3 / +1000% / -30% / 6h"
          and (M.HOLD_STOP, M.HOLD_TP, M.HOLD_MAX_H) == (0.30, 10.0, 6.0), "L6 the switch is on the hour; the rule itself (-30%, 11x, 6 h) and its key are unchanged")


def checks(check, skips=None):
    l1(check)
    l2(check)
    l3(check)
    l4(check)
    l5(check)
    l6(check)


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
