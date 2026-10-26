#!/usr/bin/env python3
"""selftest_gtunit.py: a pool's GeckoTerminal candles are its own coin's price (memebot.UNIT_X). On Oct 26 2026 the Sell bot card showed
LAUNCH "now +8427%": GeckoTerminal's token=base candles of its StonkFun pool were the partner coin (about $0.13, flat) while LAUNCH was at
$0.0015 (DexScreener), so the watch judged it on a flat chart of another coin and the card put that price over LAUNCH's entry. Fake money
only: hand-made candles from the real numbers, nothing is fetched.

  G1 memebot.unit_off / unit_ok: LAUNCH's numbers (entry $0.001465, candles $0.1304) are another coin's; its own candles and the coins'
     real moves (up to 2.5x between the scan's price and the entry) are not; nothing to compare is no verdict
  G2 rocket_watch.pick_candles / check_pick: base candles of the other coin -> the quote side (remembered as "tok"); a cpx, last checked
     minute and high/low/level watched on the other coin are dropped and its own chart starts over, with no phantom stop; neither side
     its own -> no candles (the DexScreener path, no sale on a flat price); a pool whose base is the coin asks once, as before
  G3 fetch.candles: the scan's hold and tip candles take the quote side when the base side is another coin's, write nothing when neither
     is, and ask once when the base side is right
  G4 peak.gt_own (memepeak, the shadow rules, the Learning Pick): the same choice on the peaks job's fetches
  G5 memebot.hold_check / hold_candles: a stored cpx of the other coin is not used; candles of the other coin are no candles
  G6 the page: the Sell bot's plan waits rather than show a price of another coin; the live script drops such a cpx

  python3 selftest_gtunit.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
"""
import contextlib, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MIN, H = 60_000, 3_600_000
LIVE = 1_900_000_000_000          # a made-up switch, far after every real date, so the checks do not depend on the clock
ENTRY, OTHER = 0.001465, 0.1304047436623794     # LAUNCH's entry price (DexScreener) and its pool's token=base candle price (Oct 25-26)


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


def gt(rows):
    return {"data": {"attributes": {"ohlcv_list": [[r[0] // 1000, r[1], r[2], r[3], r[4], 500] for r in rows]}}}


def flat(t0, n, px):
    """n minute candles from t0 at about px (the other coin: no move to speak of)."""
    return [(t0 + i * MIN, px, px * 1.002, px * 0.998, px * (1.0 + 0.001 * (i % 3 - 1))) for i in range(n)]


def g1(check):
    import memebot as M
    print("== gt unit G1: whose price the candles are")
    T = LIVE + H
    check(M.unit_off(OTHER, ENTRY) and M.unit_off(ENTRY, OTHER) and not M.unit_off(0.0015, ENTRY) and not M.unit_off(2.5 * ENTRY, ENTRY)
          and not M.unit_off(ENTRY / 2.5, ENTRY) and not M.unit_off(None, ENTRY) and not M.unit_off(OTHER, None) and not M.unit_off(0, ENTRY),
          "G1 unit_off: $0.1304 against $0.001465 is another coin (89x); 2.5x either way and a missing price are not")
    check(not M.unit_ok(flat(T, 5, OTHER), T, ENTRY) and M.unit_ok(flat(T, 5, 0.0015), T, ENTRY) and M.unit_ok([], T, ENTRY)
          and M.unit_ok(flat(T, 5, OTHER), T, None) and M.unit_ok(flat(T, 5, OTHER), None, ENTRY),
          "G1 unit_ok: the other coin's candles fail, the coin's own pass; no candles, no price or no time is no verdict")
    rows = flat(T, 3, ENTRY) + flat(T + 300 * MIN, 3, 30 * ENTRY)
    check(M.unit_ok(rows, T, ENTRY) and not M.unit_ok(rows, T + 300 * MIN, ENTRY),
          "G1 unit_ok compares the candle nearest the price's time (a coin that went 30x later is still its own chart at the entry)")


class Http:
    """rocket_watch.Http's get(url, key, gap) on fixed answers per side; every url asked is kept."""
    mock = "fixed"          # one page per ask, as rocket_watch reads a mock

    def __init__(self, base, quote):
        self.ans, self.urls = {"base": base, "quote": quote}, []

    def get(self, url, key, gap=0.0):
        self.urls.append(url)
        return self.ans["quote" if "token=quote" in url else "base"]


def g2(check):
    import memebot as M, rocket_watch as RW
    print("== gt unit G2: the minute watch (Sell bot)")
    T = LIVE + H
    t0 = T + 12 * MIN
    with live_at(LIVE):
        def pos(**kw):
            return dict({"sym": "LAUNCH", "addr": "A" * 44, "pair": "pL", "px": ENTRY, "t": T, "entryAt": t0, "ticket": 50.0, "grp": "hold",
                         "paper": M.PAPER_RULE, "left": 1.0}, **kw)
        now = t0 + 90 * MIN
        own = [(t0 - MIN + i * MIN, ENTRY * (1 + 0.004 * i), ENTRY * (1 + 0.004 * i) * 1.01, ENTRY * (1 + 0.004 * i) * 0.99, ENTRY * (1 + 0.004 * i))
               for i in range(90)]
        # the watch of the old code: cpx, last minute, high, low and level all of the other coin
        w = pos(cpx=OTHER, chk=float(t0 + 60 * MIN), now=0.9572, hi=1.0074, lo=0.9413, lvl=0.5)
        st = {"pos": {"p1": w}, "sold": {}}
        http = Http(gt(flat(t0 - MIN, 90, OTHER)), gt(own))
        pairs = {"A" * 44: [{"baseToken": {"address": "A" * 44}, "pairAddress": "pL", "priceUsd": str(ENTRY * 1.35)}]}
        out = RW.check_pick(http, st, pairs, now)
        w = st["pos"]["p1"]
        check(not out and w.get("tok") == "quote" and abs(w["cpx"] - own[0][4]) < 1e-12 and 1.3 < w["now"] < 1.4 and w["hi"] >= w["now"]
              and w["lo"] >= 0.98 and any("token=base" in u for u in http.urls) and any("token=quote" in u for u in http.urls),
              "G2 base candles of the other coin: the quote side is LAUNCH's own (tok quote), cpx starts over at its entry minute, now %.2fx, "
              "no phantom stop (%s, cpx %s)" % (w.get("now") or 0, out, w.get("cpx")))
        http.urls.clear()
        RW.check_pick(http, st, pairs, now + MIN)
        check(http.urls and all("token=quote" in u for u in http.urls), "G2 the next look asks the remembered side first (%d asks, quote only)" % len(http.urls))
        # neither side is the coin's: no candles, judged on DexScreener's price (a flat other coin sells nothing)
        st2 = {"pos": {"p2": pos(cpx=OTHER, chk=float(t0 + 60 * MIN))}, "sold": {}}
        http2 = Http(gt(flat(t0 - MIN, 90, OTHER)), gt(flat(t0 - MIN, 90, 7.0)))
        out2 = RW.check_pick(http2, st2, {"A" * 44: [{"baseToken": {"address": "A" * 44}, "pairAddress": "pL", "priceUsd": str(ENTRY * 1.06)}]}, now)
        w2 = st2["pos"]["p2"]
        check(not out2 and "cpx" not in w2 and "tok" not in w2 and abs(w2.get("dshi") - 1.06) < 1e-9,
              "G2 neither side is LAUNCH's: no candles, no sale on the other coin's flat price, the trail watches DexScreener's (dshi %s)" % w2.get("dshi"))
        # ... and a real fall on DexScreener's price still sells at the floor
        out3 = RW.check_pick(http2, st2, {"A" * 44: [{"baseToken": {"address": "A" * 44}, "pairAddress": "pL", "priceUsd": str(ENTRY * 0.45)}]}, now + MIN)
        check(len(out3) == 1 and out3[0]["why"] == "stop" and abs(out3[0]["mult"] - 0.45) < 1e-9,
              "G2 without candles of its own the floor still sells on DexScreener's price (%s)" % out3)
        # a pool whose base token is the coin: one ask, as before
        st4 = {"pos": {"p4": pos()}, "sold": {}}
        http4 = Http(gt(own), gt(flat(t0 - MIN, 90, OTHER)))
        RW.check_pick(http4, st4, pairs, now)
        check(len(http4.urls) == 1 and "token=base" in http4.urls[0] and st4["pos"]["p4"].get("tok") == "base",
              "G2 a pool priced in its own coin asks once, token=base, as before")
        # the scan's list hands over no cpx of the other coin
        st5 = {"pos": {"p5": pos(cpx=0.0015)}, "sold": {}}
        RW.pick_merge(st5, {"t": now, "open": [dict(pos(), id="p5", cpx=OTHER)]}, now)
        check(st5["pos"]["p5"]["cpx"] == 0.0015, "G2 pick_merge keeps the watch's own cpx over the scan's of the other coin")


def g3(check):
    import fetch as F, memebot as M
    print("== gt unit G3: the scan's candles (fetch.candles)")
    T = LIVE + H
    tmp = tempfile.mkdtemp(prefix="mb-gtunit-")
    try:
        class FHttp:
            mock, dead = None, set()

            def __init__(self, base, quote):
                self.ans, self.urls = {"base": base, "quote": quote}, []

            def get(self, u):
                self.urls.append(u)
                return self.ans["quote" if "token=quote" in u else "base"]

            def log(self, s):
                pass
        own = flat(T, 30, 0.0015)
        it = {"pool": "pL", "since": T, "hours": 0.5, "key": "hold", "px": ENTRY, "t": T}
        h = FHttp(gt(flat(T, 30, OTHER)), gt(own))
        n = F.candles(h, tmp, [it])
        got = M.load_candles(tmp, "pL", "hold")
        check(n == 1 and len(got) == 30 and abs(got[0][4] - own[0][4]) < 1e-12 and len(h.urls) == 2 and "token=quote" in h.urls[1],
              "G3 base side of the other coin: the quote side's candles are written (%d asks)" % len(h.urls))
        shutil.rmtree(os.path.join(tmp, "candles"), ignore_errors=True)
        h2 = FHttp(gt(flat(T, 30, OTHER)), gt(flat(T, 30, 9.0)))
        n2 = F.candles(h2, tmp, [it])
        check(n2 == 0 and not M.load_candles(tmp, "pL", "hold"), "G3 neither side is the coin's: nothing written (a pool without candles)")
        h3 = FHttp(gt(own), None)
        n3 = F.candles(h3, tmp, [dict(it, key="out")])
        check(n3 == 1 and len(h3.urls) == 1 and "token=base" in h3.urls[0], "G3 a pool priced in its own coin: one ask, token=base, as before")
        h4 = FHttp(gt(flat(T, 30, OTHER)), None)
        n4 = F.candles(h4, tmp, [{"pool": "pX", "since": T, "hours": 0.5, "key": "1"}])
        check(n4 == 1 and len(h4.urls) == 1, "G3 an item without a price is written as asked (no verdict)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def g4(check):
    import peak as P
    print("== gt unit G4: the peaks job (memepeak, shadow rules, Learning Pick)")
    T = LIVE + H

    class PHttp:
        def __init__(self):
            self.urls = []

        def log(self, s):
            pass
    calls = []

    def fake_get(http, u, until, stop_at=None):
        calls.append(u)
        return "ok", (gt(flat(T, 30, 0.0015)) if "token=quote" in u else gt(flat(T, 30, OTHER)))
    old = P.gt_get
    P.gt_get = fake_get
    try:
        st, rows = P.gt_own(PHttp(), lambda side: P.gt_url("pL", T + H, 1, side), P.gt_before(T + H), 1, 0, T, ENTRY)
        check(st == "ok" and rows and abs(rows[0][4] - flat(T, 1, 0.0015)[0][4]) < 1e-12 and len(calls) == 2 and "token=quote" in calls[1],
              "G4 gt_own: base side of the other coin -> the quote side's rows")
        calls.clear()
        st2, rows2 = P.gt_own(PHttp(), lambda side: P.gt_url("pL", T + H, 1, side), P.gt_before(T + H), 1, 0, T, OTHER)
        check(st2 == "ok" and rows2 and abs(rows2[0][4] - flat(T, 1, OTHER)[0][4]) < 1e-12 and len(calls) == 1, "G4 gt_own: base side right -> one ask")
        calls.clear()
        st3, rows3 = P.gt_own(PHttp(), lambda side: P.gt_url("pL", T + H, 1, side), P.gt_before(T + H), 1, 0, T, 77.0)
        check(st3 == "ok" and rows3 == [] and len(calls) == 2, "G4 gt_own: neither side -> ('ok', []), as a pool without candles")
    finally:
        P.gt_get = old
    import shadow as SH
    check("token=quote" in SH.gt_url("pL", T, "quote") and "token=base" in SH.gt_url("pL", T) and "token=base" in P.gt_url("pL", T),
          "G4 shadow.gt_url and peak.gt_url ask token=base unless told the side")


def g5(check):
    import memebot as M
    print("== gt unit G5: the scan's own check (hold_check)")
    T = LIVE + H
    t0 = T + 12 * MIN
    tmp = tempfile.mkdtemp(prefix="mb-gtunit-")
    try:
        with live_at(LIVE):
            p = {"pair": "pL", "px": ENTRY, "t": T, "entryAt": t0, "grp": "hold", "paper": M.PAPER_RULE}
            os.makedirs(os.path.join(tmp, "candles"))

            def write(rows):
                with open(os.path.join(tmp, "candles", "pL_hold.txt"), "w") as f:
                    f.write("\n".join("|".join(str(x) for x in r) + "|500" for r in rows) + "\n")
            write(flat(t0 - MIN, 60, OTHER))
            hc = M.hold_check(tmp, p, float(t0 + 30 * MIN), OTHER)
            check(not M.hold_candles(tmp, p) and not hc["fresh"] and not hc["hit"] and hc["cpx"] is None,
                  "G5 candles of the other coin are no candles: the scan's no-candle check decides on its own price (%s)" % hc)
            own = [(t0 - MIN + i * MIN, ENTRY, ENTRY * 1.01, ENTRY * 0.99, ENTRY) for i in range(60)]
            write(own)
            hc2 = M.hold_check(tmp, p, float(t0 + 30 * MIN), OTHER)
            check(hc2["fresh"] and not hc2["hit"] and abs(hc2["cpx"] - ENTRY) < 1e-12,
                  "G5 a stored cpx of the other coin is dropped: the coin's own candles set it again, no phantom stop (%s)" % hc2.get("cpx"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def g6(check):
    import memebot as M, page_home as PH

    class R:
        @staticmethod
        def fmt_px(p):
            return "$%.4g" % p
    print("== gt unit G6: the page")
    check(PH.sb_plan(R, ENTRY, OTHER, 1.0074, 0.5) == "Waiting for this coin's first minute candles."
          and "+8" not in PH.sb_plan(R, ENTRY, OTHER, 1.0074, 0.5) and "Profit lock switches on" in PH.sb_plan(R, ENTRY, 0.0015, 1.01, 0.5),
          "G6 sb_plan: a cpx of the other coin is no chart (no +13252%), the coin's own cpx plans as before")
    check("UX=" + repr(M.UNIT_X) in PH.SB_JS and "cpx/entry>UX||cpx/entry<1/UX" in PH.SB_JS,
          "G6 the live script drops a cpx of the other coin before it writes 'now ...%'")


def checks(check):
    g1(check)
    g2(check)
    g3(check)
    g4(check)
    g5(check)
    g6(check)


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
