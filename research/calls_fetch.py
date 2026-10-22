"""More days for the call-channel test (fake money only; PREREG-CALLS-2026-10-22.md, addendum): the pump.fun graduations of a
period from Helius, and each pool's one-minute candles of its first 1000 minutes from GeckoTerminal (free: the last 6 months).
  grads <from YYYY-MM-DD> <to YYYY-MM-DD> <out.json>   every graduation (mint, PumpSwap pool, time, start reserves) in [from, to)
  plan <out.json> <per_day> <grads files...>           joins the lists; days before 9 Oct keep a random sample of per_day (seed 7)
  shard <plan.json> <i> <n> <out.json.gz>              pools i, i+n, ...: {pool: [[t_ms, o, h, l, c, v_usd], ...]}
Env HK = Helius key (never printed or written), GT_GAP = seconds between GeckoTerminal calls."""
import collections, datetime as dt, gzip, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "winlose"))
import backfill as B

MINUTES = 1000
FULL_FROM = int(dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc).timestamp() * 1000)


def day_s(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


def cmd_grads(t0, t1, out):
    opts = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "filters": {"blockTime": {"gte": t0, "lt": t1}}}
    grads, tok, pages = {}, None, 0
    while pages < 20000:
        o = dict(opts, transactionDetails="full", sortOrder="asc", limit=100)
        if tok:
            o["paginationToken"] = tok
        res = B.helius(B.MIG, o)
        pages += 1
        if not res:
            B.log("grads: no answer at page", pages); break
        data = res.get("data") or []
        if pages == 1 and data and not any(t0 <= (tx.get("blockTime") or 0) < t1 for tx in data):
            B.log("grads: the blockTime filter was not applied"); sys.exit(2)
        for tx in data:
            if t0 <= (tx.get("blockTime") or 0) < t1:
                g = B.migration(tx)
                if g and g["mint"] not in grads:
                    grads[g["mint"]] = g
        tok = res.get("paginationToken")
        if not tok or not data:
            break
        if pages % 50 == 0:
            B.log("grads page", pages, len(grads))
    day = collections.Counter(dt.datetime.fromtimestamp(g["t"] / 1000, dt.timezone.utc).strftime("%m-%d") for g in grads.values())
    B.log("graduations", len(grads), "pages", pages, "per day", dict(sorted(day.items())), "calls", dict(B.calls))
    json.dump({"from": t0, "to": t1, "grads": sorted(grads.values(), key=lambda g: g["t"]), "calls": dict(B.calls),
               "errors": B.ERRORS}, open(out, "w"))


def cmd_plan(out, per_day, *files):
    allg = {}
    for f in files:
        for g in json.load(open(f)).get("grads") or []:
            allg.setdefault(g["mint"], g)
    by_day = collections.defaultdict(list)
    for g in sorted(allg.values(), key=lambda g: g["t"]):
        by_day[g["t"] // 86_400_000].append(g)
    rng = random.Random(7)
    keep = []
    for d in sorted(by_day):
        gs = by_day[d]
        keep += gs if d * 86_400_000 >= FULL_FROM or len(gs) <= per_day else sorted(rng.sample(gs, per_day), key=lambda g: g["t"])
    B.log("graduations", len(allg), "kept", len(keep), "days", len(by_day))
    json.dump({"perDay": per_day, "graduations": len(allg), "grads": keep}, open(out, "w"))


def cmd_shard(plan, i, n, out):
    gs = json.load(open(plan))["grads"][i::n]
    res, miss = {}, 0
    for k, g in enumerate(gs):
        rows = B.gt_ohlcv(g["pool"], "minute", 1, g["t"] // 1000 + MINUTES * 60, MINUTES)
        if rows is None:
            miss += 1
            continue
        res[g["pool"]] = [r for r in rows if r[0] >= g["t"] - 60_000]
        if k % 200 == 0:
            B.log("shard", i, k, "of", len(gs), "missing", miss, dict(B.calls))
    with gzip.open(out, "wt") as fh:
        json.dump({"pools": res, "missing": miss, "calls": dict(B.calls)}, fh)
    B.log("shard", i, "done", len(res), "missing", miss)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "grads":
        cmd_grads(day_s(a[1]), day_s(a[2]), a[3])
    elif a[0] == "plan":
        cmd_plan(a[1], int(a[2]), *a[3:])
    elif a[0] == "shard":
        cmd_shard(a[1], int(a[2]), int(a[3]), a[4])
