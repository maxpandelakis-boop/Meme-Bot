"""Live paper run of the wallet lead (research/wallets/COPY2-2026-11-13.md, round 3). Fake money only: it reads public
Solana websocket logs, nothing is bought, no wallet and no key is used.

What it does, around the clock (one run is about 5 h 40 min, the state lives in a data folder that is a git branch):
1. Records PumpSwap: every pool of a pump.fun coin created while it listens (the graduation), its price by the minute, and every
   wallet's first buy of 0.1 SOL or more within 48 h after the graduation (a "pair", as in research/wallet_build.py).
2. Scores each pair like the test did: a copy at the last price one minute after the buy, exit A (-30% stop at the minute's
   low, 11x target, else sold after 6 hours), as a multiple of the copy's price.
3. Each UTC day builds the list S1 from the pairs of the 21 days before with one day lag: wallets with 10 or more scored
   copies, average above 0 after 1% a side, t of 2 or more, the 300 with the largest t.
4. Paper trades: the first qualifying buy of a listed wallet in a coin is copied one minute late with 20 $ of fake money and
   sold by exit A. Trades made while the list window holds fewer than 21 recorded days are marked warm-up.

usage: python3 recorder.py --data <dir> [--minutes 340] [--push]
"""
import argparse, asyncio, base64, gzip, hashlib, json, os, re, subprocess, sys, time
import numpy as np

AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSS = ["wss://api.mainnet-beta.solana.com", "wss://api.mainnet-beta.solana.com", "wss://solana-rpc.publicnode.com"]   # the second was silent in the probe
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MIN_BUY = 0.1                      # SOL
BUY_H, PATH_MIN, DELAY = 48, 360, 60
STOP, TARGET = 0.70, 11.0
SLIP, TICKET = 0.01, 20.0
WIN_DAYS, LAG, MIN_N, TMIN, TOP = 21, 1, 10, 2.0, 300
DAY = 86400
RULE = "S1 / 1 min / exit A (-30%, 11x, 6 h), round 3 of research/wallets/COPY2-2026-11-13.md"


def b58(b):
    n = int.from_bytes(b, "big"); s = ""
    while n:
        n, r = divmod(n, 58); s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def b58dec(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    return n.to_bytes(32, "big")


WSOL = b58dec("So11111111111111111111111111111111111111112")
disc = lambda n: hashlib.sha256(("event:" + n).encode()).digest()[:8]
D_BUY, D_SELL, D_CREATE = disc("BuyEvent"), disc("SellEvent"), disc("CreatePoolEvent")
PREFIX = {base64.b64encode(d + b"\0")[:10].decode(): k for d, k in ((D_BUY, "b"), (D_SELL, "s"), (D_CREATE, "c"))}
DATA_RE = re.compile(r"Program data: ([A-Za-z0-9+/=]+)")
u64 = lambda b, o: int.from_bytes(b[o:o + 8], "little")
h64 = lambda b: int.from_bytes(hashlib.blake2b(b, digest_size=8).digest(), "little")


def fee(x):
    """FOMO's Solana fee per buy and per sell."""
    return 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x


def money(mult):
    """$ result of a 20 $ ticket at a multiple (1% a side), with FOMO's fee and with a Jupiter-like fee."""
    v = TICKET * mult * (1 - SLIP) / (1 + SLIP)
    return round(v - TICKET - fee(TICKET) - fee(v), 3), round(v - TICKET - 0.10, 3)


def exit_a(closes, lows, highs, entry):
    """Exit A on minute bars after the entry (arrays in time order, NaN = no trade in that minute): the multiple and how.
    A stop sells at the low of the minute that hit it; a stop and a target in one minute count as the stop."""
    last = entry
    for c, lo, hi in zip(closes, lows, highs):
        if c != c:
            continue
        if lo <= STOP * entry:
            return lo / entry, "stop"
        if hi >= TARGET * entry:
            return TARGET, "target"
        last = c
    return last / entry, "time"


def build_list(pairs_by_day, day):
    """S1 for the UTC day number `day`: {wallet hash: (n, mean, t)} from the pairs of days day-22 .. day-2 (21 days, one day lag).
    Returns (list dict, recorded days in the window)."""
    days = [d for d in range(day - WIN_DAYS - LAG, day - LAG) if d in pairs_by_day and len(pairs_by_day[d]["w"])]
    if not days:
        return {}, 0
    w = np.concatenate([pairs_by_day[d]["w"] for d in days]); m = np.concatenate([pairs_by_day[d]["a"] for d in days]).astype(np.float64)
    ok = ~np.isnan(m)
    w, x = w[ok], m[ok] * (1 - SLIP) / (1 + SLIP) - 1
    uw, inv = np.unique(w, return_inverse=True)
    n = np.bincount(inv).astype(np.float64); s = np.bincount(inv, weights=x); ss = np.bincount(inv, weights=x * x)
    mean = s / n
    var = np.maximum(ss / n - mean ** 2, 0) * n / np.maximum(n - 1, 1)
    tv = np.where(var > 0, mean / np.sqrt(np.maximum(var, 1e-30) / n), 0.0)
    c = np.flatnonzero((n >= MIN_N) & (mean > 0) & (tv >= TMIN))
    c = c[np.argsort(-tv[c], kind="stable")[:TOP]]
    return {int(uw[k]): (int(n[k]), round(float(mean[k]), 4), round(float(tv[k]), 2)) for k in c}, len(days)


class Recorder:
    def __init__(self, data):
        self.data = data
        self.pools = {}            # pool key bytes -> dict(mint, t0, last, bars {minute: [close, low, high]})
        self.ignored = set()
        self.creates = []          # (time, event body) of recent CreatePoolEvents
        self.seen = set()          # (wallet hash, pool hash) with a qualifying buy
        self.pending = []          # pairs waiting for their 6 hours: [t, wallet hash, pool key, sol]
        self.pairs = {}            # day -> dict(w, p, t, sol, a) lists, then arrays in files
        self.list, self.list_day, self.list_days = {}, None, 0
        self.bought = set()        # pool hashes the paper account already copied
        self.waiting = []          # paper entries waiting for their minute: [t_entry, pool key, wallet address, t_buy, sol, warm]
        self.open, self.closed = [], []
        self.stat = dict(msgs=0, failed=0, buys=0, sells=0, creates=0, pump_creates=0, tracked_trades=0, pairs=0, reconnects=0,
                         silent_s=0, started=int(time.time()), gaps=[])
        self.first_start = int(time.time())
        self.load()

    # ---------------------------------------------------------------------------------------------------- state on disk
    def path(self, *a):
        return os.path.join(self.data, *a)

    def load(self):
        os.makedirs(self.path("pairs"), exist_ok=True)
        for f in sorted(os.listdir(self.path("pairs"))):
            if f.endswith(".npz"):
                z = np.load(self.path("pairs", f))
                self.pairs[int(f[:-4])] = {k: list(z[k]) for k in ("w", "p", "t", "sol", "a")}
        if not os.path.exists(self.path("state.json.gz")):
            return
        st = json.load(gzip.open(self.path("state.json.gz"), "rt"))
        now = time.time()
        for k, p in st["pools"].items():
            if now - p["t0"] < (BUY_H + 7) * 3600:
                p["bars"] = {int(m): v for m, v in p["bars"].items()}
                self.pools[bytes.fromhex(k)] = p
        self.pending = [[t, w, bytes.fromhex(p), s] for t, w, p, s in st["pending"]]
        self.seen = {(w, h64(p)) for _, w, p, _ in self.pending}
        for d in self.pairs.values():
            self.seen.update(zip((int(x) for x in d["w"]), (int(x) for x in d["p"])))
        self.bought = set(st["bought"]); self.open = st["open"]; self.closed = st["closed"]
        self.waiting = [[a, bytes.fromhex(p), w, b, s, wm] for a, p, w, b, s, wm in st.get("waiting", [])]
        self.first_start = st.get("first_start", self.first_start)
        self.stat["gaps"] = st.get("gaps", [])[-200:]
        if st.get("saved") and now - st["saved"] > 90:
            self.stat["gaps"].append([int(st["saved"]), int(now)])
        print("state loaded: pools %d, pending %d, pair days %d, open %d, closed %d, last save %.0f s ago" % (
            len(self.pools), len(self.pending), len(self.pairs), len(self.open), len(self.closed), now - st.get("saved", now)), flush=True)

    def save(self):
        now = time.time()
        for d, v in self.pairs.items():
            if v.get("dirty"):
                np.savez_compressed(self.path("pairs", "%d.npz" % d), w=np.array(v["w"], np.uint64), p=np.array(v["p"], np.uint64),
                                    t=np.array(v["t"], np.int64), sol=np.array(v["sol"], np.float32), a=np.array(v["a"], np.float32))
                v["dirty"] = False
        for f in os.listdir(self.path("pairs")):                      # pairs older than the list window are dropped
            if f.endswith(".npz") and int(f[:-4]) < int(now // DAY) - WIN_DAYS - LAG - 2:
                os.remove(self.path("pairs", f)); self.pairs.pop(int(f[:-4]), None)
        keep_from = int(now // 60) - PATH_MIN - 5
        pools = {}
        for k, p in list(self.pools.items()):
            if now - p["t0"] > (BUY_H + 7) * 3600 and not any(o["pool"] == k.hex() for o in self.open):
                del self.pools[k]; continue
            pools[k.hex()] = dict(mint=p["mint"], t0=p["t0"], last=p["last"], bars={m: v for m, v in p["bars"].items() if m >= keep_from})
            p["bars"] = pools[k.hex()]["bars"]
        st = dict(saved=now, first_start=self.first_start, pools=pools, pending=[[t, w, p.hex(), s] for t, w, p, s in self.pending],
                  bought=sorted(self.bought), open=self.open, closed=self.closed, gaps=self.stat["gaps"][-200:],
                  waiting=[[a, p.hex(), w, b, s, wm] for a, p, w, b, s, wm in self.waiting])
        with gzip.open(self.path("state.json.gz"), "wt") as f:
            json.dump(st, f)
        self.status(now)

    def status(self, now):
        real = [c for c in self.closed if not c["warm"]]
        tot = lambda rows, k: round(sum(r[k] for r in rows), 2)
        up = max(now - self.stat["started"], 1)
        day = int(now // DAY)
        s = dict(rule=RULE, fake_money_only=True, updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now)),
                 recording_since=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(self.first_start)),
                 recorded_days_in_list_window=self.list_days, list_days_needed=WIN_DAYS, listed_wallets=len(self.list),
                 this_run=dict(minutes=round(up / 60), messages_per_s=round(self.stat["msgs"] / up, 1), **{k: self.stat[k] for k in (
                     "buys", "sells", "creates", "pump_creates", "tracked_trades", "pairs", "reconnects", "silent_s")}),
                 pools_tracked=len(self.pools), pairs_waiting=len(self.pending),
                 pairs_scored_today=len(self.pairs.get(day, {}).get("w", [])), pair_days=len(self.pairs),
                 paper=dict(ticket=TICKET, open=len(self.open), waiting=len(self.waiting),
                            counted=dict(trades=len(real), fomo_fee=tot(real, "fomo"), jupiter_fee=tot(real, "jup"),
                                         in_profit=sum(r["fomo"] > 0 for r in real)),
                            warm_up=dict(trades=len(self.closed) - len(real), fomo_fee=tot([c for c in self.closed if c["warm"]], "fomo"),
                                         jupiter_fee=tot([c for c in self.closed if c["warm"]], "jup"))),
                 open=self.open, closed=self.closed[-300:], gaps_last=self.stat["gaps"][-10:])
        json.dump(s, open(self.path("status.json"), "w"), indent=1)

    # ---------------------------------------------------------------------------------------------------- the events
    def pool_of(self, key, now):
        p = self.pools.get(key)
        if p is not None or key in self.ignored:
            return p
        for t0, body in self.creates:
            if key in body:
                o = body.find(WSOL)
                mint = b58(body[o - 32:o]) if o >= 32 else ""
                if mint.endswith("pump"):
                    p = self.pools[key] = dict(mint=mint, t0=t0, last=0.0, bars={})
                    self.stat["pump_creates"] += 1
                    return p
                break
        self.ignored.add(key)
        return None

    def on_event(self, kind, b, now):
        if kind == "c":
            self.stat["creates"] += 1
            if self.stat["creates"] <= 3:
                print("create event", len(b), base64.b64encode(b).decode(), flush=True)
            ts = u64(b, 8)
            self.creates.append((ts if abs(ts - now) < 3600 else int(now), bytes(b[8:])))
            if len(self.creates) > 4000:
                self.creates = self.creates[-3000:]
            return
        if len(b) < 184:
            return
        self.stat["buys" if kind == "b" else "sells"] += 1
        key = bytes(b[120:152])
        p = self.pool_of(key, now)
        if p is None:
            return
        base, quote = u64(b, 48), u64(b, 56)
        if base <= 0 or quote <= 0:
            return
        self.stat["tracked_trades"] += 1
        t = u64(b, 8)
        if abs(t - now) > 600:
            t = int(now)
        price = (quote / 1e9) / (base / 1e6)
        m = t // 60
        bar = p["bars"].get(m)
        if bar is None:
            p["bars"][m] = [price, price, price]
        else:
            bar[0] = price; bar[1] = min(bar[1], price); bar[2] = max(bar[2], price)
        p["last"] = price
        if kind != "b":
            return
        sol = u64(b, 64) / 1e9
        if sol < MIN_BUY or t > p["t0"] + BUY_H * 3600:
            return
        user = bytes(b[152:184])
        wh, ph = h64(user), h64(key)
        if (wh, ph) in self.seen:
            return
        self.seen.add((wh, ph))
        self.pending.append([t, wh, key, round(sol, 4)])
        self.stat["pairs"] += 1
        if wh in self.list and ph not in self.bought:
            self.bought.add(ph)
            self.waiting.append([t + DELAY, key, b58(user), t, round(sol, 3), self.list_days < WIN_DAYS])

    # ---------------------------------------------------------------------------------------------------- the clock
    def price_at(self, p, t):
        """The last price at or before the minute of t (the bars are the record; the last trade of that minute or earlier)."""
        m = t // 60
        ms = [k for k in p["bars"] if k <= m]
        return p["bars"][max(ms)][0] if ms else None

    def path_after(self, p, t_entry):
        m0 = t_entry // 60 + 1
        arr = [p["bars"].get(m) for m in range(m0, m0 + PATH_MIN)]
        nan = float("nan")
        return [a[0] if a else nan for a in arr], [a[1] if a else nan for a in arr], [a[2] if a else nan for a in arr]

    def tick(self, now):
        day = int(now // DAY)
        if self.list_day != day:
            self.list, self.list_days = build_list({d: dict(w=np.array(v["w"], np.uint64), a=np.array(v["a"], np.float32))
                                                    for d, v in self.pairs.items()}, day)
            self.list_day = day
            print("list for day %d: %d wallets from %d recorded days" % (day, len(self.list), self.list_days), flush=True)
        # pairs whose six hours are over: score them like the test
        keep = []
        for row in self.pending:
            t, wh, key, sol = row
            if now < t + DELAY + PATH_MIN * 60 + 90:
                keep.append(row); continue
            p = self.pools.get(key)
            entry = self.price_at(p, t + DELAY) if p else None
            a = float("nan")
            if entry:
                a, _ = exit_a(*self.path_after(p, t + DELAY), entry)
            d = self.pairs.setdefault(int(t // DAY), dict(w=[], p=[], t=[], sol=[], a=[]))
            d["w"].append(wh); d["p"].append(h64(key)); d["t"].append(t); d["sol"].append(sol); d["a"].append(a); d["dirty"] = True
        self.pending = keep
        # the paper account: entries whose minute has passed, then the open positions
        still = []
        for row in self.waiting:
            t_entry, key, wallet, t_buy, sol, warm = row
            if now < t_entry + 5:
                still.append(row); continue
            p = self.pools.get(key)
            entry = self.price_at(p, t_entry) if p else None
            if entry:
                self.open.append(dict(pool=key.hex(), mint=p["mint"], wallet=wallet, t_buy=t_buy, wallet_sol=sol, t_entry=t_entry,
                                      entry=entry, warm=bool(warm), list_days=self.list_days))
                print("paper buy %s after %s (%.2f SOL)%s" % (p["mint"], wallet, sol, " [warm-up]" if warm else ""), flush=True)
        self.waiting = still
        left = []
        for o in self.open:
            p = self.pools.get(bytes.fromhex(o["pool"]))
            if p is None:
                continue
            closes, lows, highs = self.path_after(p, o["t_entry"])
            upto = int(now // 60) - (o["t_entry"] // 60 + 1)           # whole minutes that are over
            done = now >= o["t_entry"] + PATH_MIN * 60 + 90
            mult, how = exit_a(closes[:max(upto, 0)] if not done else closes, lows[:max(upto, 0)] if not done else lows,
                               highs[:max(upto, 0)] if not done else highs, o["entry"])
            if how == "time" and not done:
                o["now"] = round(p["last"] / o["entry"], 3)
                left.append(o); continue
            f, j = money(mult)
            self.closed.append(dict(o, mult=round(mult, 4), how=how, fomo=f, jup=j, t_exit=int(now)))
            print("paper sell %s x%.3f (%s): %+.2f $ FOMO fee, %+.2f $ Jupiter fee" % (o["mint"], mult, how, f, j), flush=True)
        self.open = left


async def listen(rec, until, push):
    import websockets
    k = 0; last_save = time.time(); last_tick = 0
    while time.time() < until:
        url = WSS[k % len(WSS)]
        try:
            async with websockets.connect(url, max_size=None, ping_interval=20, open_timeout=30) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                          "params": [{"mentions": [AMM]}, {"commitment": "confirmed"}]}))
                print("listening on", url, flush=True)
                quiet = 0
                while time.time() < until:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 15)
                    except asyncio.TimeoutError:
                        quiet += 15; rec.stat["silent_s"] += 15
                        if quiet >= 45:
                            raise RuntimeError("silent for 45 s")
                        continue
                    quiet = 0
                    now = time.time()
                    rec.stat["msgs"] += 1
                    if '"err":null' not in raw:
                        rec.stat["failed"] += 1
                    else:
                        for mm in DATA_RE.finditer(raw):
                            kind = PREFIX.get(mm.group(1)[:10])
                            if kind:
                                try:
                                    rec.on_event(kind, base64.b64decode(mm.group(1)), now)
                                except Exception as e:
                                    print("event error", type(e).__name__, str(e)[:100], flush=True)
                    if now - last_tick >= 5:
                        last_tick = now; rec.tick(now)
                        if now - last_save >= 600:
                            last_save = now; rec.save(); commit(rec.data, push)
        except Exception as e:
            rec.stat["reconnects"] += 1
            print("websocket %s: %s %s; again in 3 s" % (url, type(e).__name__, str(e)[:120]), flush=True)
            k += 1
            await asyncio.sleep(3)


def commit(data, push):
    if not push:
        return
    try:
        g = ["git", "-C", data, "-c", "user.name=wallet-live", "-c", "user.email=wallet-live@users.noreply.github.com"]
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-q", "--amend", "-m", "wallet live run (fake money only) " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())], check=True)
        subprocess.run(g + ["push", "-q", "--force", "origin", "HEAD:walletlive"], check=True, timeout=300)
    except Exception as e:
        print("push failed", type(e).__name__, str(e)[:150], flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--minutes", type=float, default=340); ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    rec = Recorder(a.data)
    asyncio.run(listen(rec, time.time() + a.minutes * 60, a.push))
    rec.tick(time.time()); rec.save(); commit(a.data, a.push)
    print("run over:", json.dumps(rec.stat)[:600], flush=True)


if __name__ == "__main__":
    main()
