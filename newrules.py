#!/usr/bin/env python3
"""newrules.py: the "New rules test" (fake money only). Nothing here buys, signs or sends anything, nothing the Pick, the Sell bot, the
Radar, the training or the big test reads comes from here, and nothing here is advice.

The question (the user, 4 Nov 2026 16:14 UTC: "neue regeln suchen aufgrund der neuen daten ... ich will plus sehen"): does any rule
found on the bots' own live data of 22 Oct - 4 Nov still earn on days nobody has seen? The search (research/livesearch, pre-registered in
PREREG-LIVESEARCH-2026-11-04.md before any rule was scored) tried 48,100 rules in three families and froze the candidates below
(CANDIDATES-2026-11-04.json) before they went live. They are FROZEN: another rule is a new test with its own start, never an edit.

  N1-N3  sell rules on the Pick account's real buys: the Sell bot (memebot.chart_hit) with other numbers (the trail arms at 2x, a fall
         of 30 % instead of 15 % sells, up to 12 h), replayed by shadow.replay on the shadow job's 12-hour minute path of each buy
  P1-P3  Pick buys to leave out: only the buys whose buy-time factors (the position's "f") pass both conditions count, each sold by the
         Sell bot replayed (rule X) on its path; the real account on the same buys stands beside it
  B1-B3  buy rules on every coin of every hourly scan (the big test): a coin that passes is bought once per UTC day at the snapshot
         price and sold at the big test's price about 2 h later (1 % fee a side, capped at 11x, a coin without a price counts as 0);
         measured each night by the filter search (filter_search.py build -> doc "newrules"), shown from that doc

Buys from FROM (5 Nov 2026 00:00 UTC) on count; the judgement (22 Nov 2026, the PR #39 bar, judge()) takes the buys up to UNTIL.

  python3 newrules.py summary --dir mb [--now ms]      the Pick part (N, P) as JSON
"""
import argparse, json, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: num, the paper rule
import shadow as SH      # read only: trades, load_doc, replay, money, real_result, RULES (K and X)

V = 1
FROM = 1793836800000       # Thu 5 Nov 2026 00:00 UTC (01:00 Berlin): buys from here on count. Never edit after it has passed.
UNTIL = 1795262400000      # Sat 21 Nov 2026 12:00 UTC: the last buy the judgement of 22 Nov takes (its 12-hour path is in by then)
JUDGE_AT = "Nov 22"
DAY = 86_400_000
ALLOW = {"pick": 1.5, "big": 1.5}       # PR #39: the allowance per 50 EUR trade (fees and fills the paper books may miss)
BOOT, BOOT_Q = 10_000, 0.01

_X = next(r for r in SH.RULES if r["id"] == "X")
_K = next(r for r in SH.RULES if r["id"] == "K")


def _chart(arm, trail, drop, drop_min, hours):
    return {"CHART_STOP": 0.50, "CHART_TRAIL": trail, "CHART_ARM": arm, "CHART_DROP": drop, "CHART_DROP_MIN": drop_min, "HOLD_MAX_H": hours}


SELL = (
    {"id": "N1", "name": "Sell bot, looser", "text": "15% under the high from 2x, −30% in 30 min, −50%, 11x, 12 h",
     "chart": True, "stop": 0.50, "target": 11.0, "hours": 12.0, "cp": _chart(2.0, 0.15, 0.30, 30, 12.0)},
    {"id": "N2", "name": "Sell bot, looser (15 min)", "text": "15% under the high from 2x, −30% in 15 min, −50%, 11x, 12 h",
     "chart": True, "stop": 0.50, "target": 11.0, "hours": 12.0, "cp": _chart(2.0, 0.15, 0.30, 15, 12.0)},
    {"id": "N3", "name": "Sell bot, looser (tight trail)", "text": "10% under the high from 2x, −30% in 30 min, −50%, 11x, 12 h",
     "chart": True, "stop": 0.50, "target": 11.0, "hours": 12.0, "cp": _chart(2.0, 0.10, 0.30, 30, 12.0)},
)
SKIP = (
    {"id": "P1", "name": "More buyers, fewer trades", "text": "only buys with buys/sells 1h ≥ 1.12 and at most 635 buys in the last hour",
     "c": [["buyRatio1h", ">=", 1.11608], ["buys1", "<=", 634.96]]},
    {"id": "P2", "name": "More buyers, spread holders", "text": "only buys with buys/sells 1h ≥ 1.12 and top 10 wallets ≤ 26.9%",
     "c": [["buyRatio1h", ">=", 1.11608], ["rc.top10", "<=", 26.8506]]},
    {"id": "P3", "name": "More buyers, small pool", "text": "only buys with buys/sells 1h ≥ 1.12 and liquidity ≤ $70.4k",
     "c": [["buyRatio1h", ">=", 1.11608], ["logLiq", "<=", 4.847364]]},
)
BUY = (
    {"id": "B1", "name": "Quiet hour, holders growing", "text": "1 h to 3 days old, last hour ≤ 2.8% of the day's volume, holders +4,932 in 24 h",
     "w": "lern", "c": [["vol1Share", "<=", 0.0278], ["jup.holderChg24", ">=", 4931.535]]},
    {"id": "B2", "name": "Young, many net buyers", "text": "1 to 6 h old, buys/sells 1h ≤ 1.42, net buyers 24h ≥ 1,190",
     "w": "1-6h", "c": [["buyRatio1h", "<=", 1.417], ["jup.netBuyers24", ">=", 1189.5]]},
    {"id": "B3", "name": "Quiet hour, organic", "text": "1 h to 3 days old, last hour ≤ 2.8% of the day's volume, organic score ≥ 64.5",
     "w": "lern", "c": [["vol1Share", "<=", 0.0278], ["jup.organic", ">=", 64.465]]},
)
BIG_TICKET, BIG_FEE, BIG_CAP = 50.0, 0.01, 11.0


def num(v):
    return M.num(v)


def passes(f, conds):
    """Every condition [factor, "<=" or ">=", threshold] on the factors f; an unknown factor never passes."""
    for k, op, thr in conds:
        v = num((f or {}).get(k))
        if v is None or not (v <= thr if op == "<=" else v >= thr):
            return False
    return True


def stats(vals):
    """A list of results in EUR -> the account's numbers (without the best trade too: one coin must not carry a rule)."""
    n = len(vals)
    if not n:
        return {"n": 0, "eur": 0.0, "per": None, "won": 0, "best": None, "eurWob": None}
    best = max(vals)
    return {"n": n, "eur": round(sum(vals), 2), "per": round(sum(vals) / n, 2), "won": sum(1 for v in vals if v > 0.004),
            "best": round(best, 2), "eurWob": round(sum(vals) - best, 2)}


# ---------------------------------------------------------------- N and P on the Pick's buys
def pick_test(d, now=None, pos=None):
    """The Pick part: the buys from FROM whose 12-hour path is in, each under K, X and N1-N3, and P1-P3 on the buys they keep ->
    {"from", "until", "n", "open", "out", "real", "accts": [...], "skips": [...], "trades": [...]}. Reads only."""
    now = int(now or time.time() * 1000)
    rows, n_open, n_out = [], 0, 0
    rules = (_K, _X) + SELL
    for pid, p in SH.trades(d, pos, since=FROM):
        doc = SH.load_doc(d, pid) if SH.safe_id(pid) else None
        st = (doc or {}).get("state")
        row = {"pid": pid, "sym": str(p.get("sym") or "?")[:24], "t": SH.entry_of(p), "real": SH.real_result(p), "res": {}, "state": "open",
               "keep": {s["id"]: passes(p.get("f"), s["c"]) for s in SKIP}, "judged": SH.entry_of(p) <= UNTIL}
        if st == "none":
            row["state"] = "none"
            n_out += 1
        elif st == "ok" and row["real"] is not None:
            res = {r["id"]: SH.replay(doc, r) for r in rules}
            if any(v is None for v in res.values()):
                row["state"] = "none"
                n_out += 1
            else:
                row["state"] = "ok"
                row["res"] = {k: {"eur": SH.money(p, v["sales"]), "why": v["why"]} for k, v in res.items()}
        else:
            n_open += 1
        rows.append(row)
    done = [r for r in rows if r["state"] == "ok"]
    real = dict(stats([r["real"] for r in done]), id="real", name="Real Pick account", text="the Sell bot, really booked")
    accts = []
    for r in rules:
        a = dict(stats([x["res"][r["id"]]["eur"] for x in done]), id=r["id"], name=r.get("name") or r["id"], text=r["text"])
        a["vsReal"] = round(a["eur"] - real["eur"], 2) if done else None
        accts.append(a)
    skips = []
    for s in SKIP:
        kept = [x for x in done if x["keep"][s["id"]]]
        a = dict(stats([x["res"]["X"]["eur"] for x in kept]), id=s["id"], name=s["name"], text=s["text"])
        a["real"] = stats([x["real"] for x in kept])["eur"] if kept else None
        a["of"] = len(done)
        skips.append(a)
    return {"v": V, "t": now, "from": FROM, "until": UNTIL, "n": len(done), "open": n_open, "out": n_out, "real": real, "accts": accts,
            "skips": skips, "trades": sorted(rows, key=lambda r: (-r["t"], r["pid"]))}


# ---------------------------------------------------------------- B on the big test (nightly, inside filter_search.build)
def window_ok(w, c):
    f = c.get("f") or {}
    age = num(f.get("ageH"))
    if age is None:
        return False
    if w == "1-6h":
        return 1.0 <= age < 6.0
    if w == "lern":      # the Learning Pick's universe (lernpick.UNIVERSE)
        liq, mc, vm = num(c.get("liq")), num(c.get("mc")), num(f.get("volMc"))
        return (1.0 <= age <= 72.0 and vm is not None and vm >= 0.1 and liq is not None and liq >= 15_000.0 and mc is not None
                and 50_000.0 <= mc <= 2_000_000.0)
    return False


def big_result(c):
    """What 50 EUR in a big-test coin made about 2 h later: 1 % fee a side, capped at 11x, nothing for a coin without a price."""
    m = num(c.get("mult")) or 0.0
    gone = bool(c.get("gone")) or m < 0.02
    return round(BIG_TICKET * (1 - BIG_FEE) ** 2 * (0.0 if gone else min(m, BIG_CAP)) - BIG_TICKET, 4)


class BigSink:
    """Fed by filter_search.load with every big-test coin it keeps (liquidity, market cap, no hard block, a usable result): the coins of
    scans from FROM on that pass a B rule, the first scan per coin and UTC day per rule."""

    def __init__(self):
        self.first = {b["id"]: {} for b in BUY}       # rule -> (coin, day) -> (t0, result, symbol)

    def __call__(self, t0, c):
        t0 = num(t0)
        if not t0 or t0 < FROM or not isinstance(c, dict):
            return
        for b in BUY:
            if window_ok(b["w"], c) and passes(c.get("f"), b["c"]):
                key = (str(c.get("a")), int(t0 // DAY))
                old = self.first[b["id"]].get(key)
                if old is None or t0 < old[0]:
                    self.first[b["id"]][key] = (t0, big_result(c), str(c.get("s") or "?")[:24])

    def doc(self, now):
        out = []
        for b in BUY:
            ent = sorted(self.first[b["id"]].values())
            vals = [e[1] for e in ent]
            judged = [e[1] for e in ent if e[0] <= UNTIL]
            a = dict(stats(vals), id=b["id"], name=b["name"], text=b["text"], days=len({int(e[0] // DAY) for e in ent}))
            a["last"] = [[int(e[0]), e[2], round(e[1], 2)] for e in ent[-8:]]
            a["judged"] = len(judged)
            a["bar"] = bar(judged, ALLOW["big"])
            out.append(a)
        return {"v": V, "t": int(now), "from": FROM, "until": UNTIL, "accts": out, "judge": {a["id"]: a["bar"] for a in out}}


# ---------------------------------------------------------------- the judgement (22 Nov 2026)
def bar(vals, allow, seed=7):
    """The PR #39 bar on results in EUR per 50: >= 40 trades, mean after the allowance > 0, the 1 % point of BOOT bootstrap means > 0,
    total after the allowance > 0 without the best trade -> dict with "holds"."""
    n = len(vals)
    net = [v - allow for v in vals]
    if n < 40:
        return {"n": n, "holds": False, "why": "fewer than 40 trades"}
    mean = sum(net) / n
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(net) for _ in range(n)) / n for _ in range(BOOT))
    lo = means[int(BOOT_Q * BOOT)]
    wob = sum(net) - max(net)
    holds = mean > 0 and lo > 0 and wob > 0
    return {"n": n, "mean": round(mean, 3), "lo1": round(lo, 3), "wob": round(wob, 2), "holds": holds}


def judge(d, big_doc=None, now=None):
    """Every candidate on the judged buys (FROM to UNTIL): the bar, and for N and P the paired difference to the real account on the same
    buys (it has to be above zero too). big_doc: the filter search's "newrules" doc rebuilt on the 22 Nov big test."""
    S = pick_test(d, now)
    done = [r for r in S["trades"] if r["state"] == "ok" and r["judged"]]
    out = {}
    for r in SELL:
        vals = [x["res"][r["id"]]["eur"] for x in done]
        diff = [x["res"][r["id"]]["eur"] - x["real"] for x in done]
        out[r["id"]] = dict(bar(vals, ALLOW["pick"]), vsReal=round(sum(diff), 2))
        out[r["id"]]["holds"] = out[r["id"]]["holds"] and sum(diff) > 0
    for s in SKIP:
        kept = [x for x in done if x["keep"][s["id"]]]
        vals = [x["res"]["X"]["eur"] for x in kept]
        diff = sum(x["res"]["X"]["eur"] - x["real"] for x in kept)
        out[s["id"]] = dict(bar(vals, ALLOW["pick"]), vsReal=round(diff, 2))
        out[s["id"]]["holds"] = out[s["id"]]["holds"] and diff > 0
    return {"pick": out, "big": (big_doc or {}).get("judge")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the New rules test (fake money): the live-data search's frozen candidates")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--dir", required=True)
    s.add_argument("--now", type=int)
    a = ap.parse_args(argv)
    print(json.dumps(pick_test(a.dir, a.now), ensure_ascii=False))


if __name__ == "__main__":
    main()
