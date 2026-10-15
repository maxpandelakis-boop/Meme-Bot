#!/usr/bin/env python3
"""selftest_feed.py: the launch radar's live pump.fun feed (radar_feed.py, PumpPortal's websocket) and its hooks in launch_radar.py,
against a local stand-in websocket server (ws://127.0.0.1, threaded, the server's handshake, unmasked frames). Fake money only; nothing
here reaches out.

  python3 selftest_feed.py         runs the checks on their own (PASS/FAIL per check, "FEED ALL PASS" at the end)
  checks(check, sleep=None)        the same from selftest.py's main (sleep: a real time.sleep while these checks run)

F1 events (parsing, frames, shapes), F2 one connection and its limits, F3 bounded memory, F4 Radar.idle and the loop's grid, F5
ds_asks, F6 radar runs with the feed (selftest_radar's mock and helpers), F7 radar.yml, the probe and the imports, F8 the curve watch's
trade subscriptions (subscribeTokenTrade / unsubscribeTokenTrade on the same socket, again after a reconnect, at most FOLLOW_MAX), the
trades' shape check, the field names logged once per kind, the bounded trade queue; F9 Radar.idle with the fast lane; F10 a server that
refuses the trade subscriptions (trades off, the graduations go on).
"""
import ast, base64, contextlib, hashlib, json, os, re, shutil, socket, struct, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import radar_feed as RF          # noqa: E402

MIN, H = 60_000, 3_600_000
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
STDLIB = {"argparse", "base64", "collections", "hashlib", "json", "os", "re", "socket", "ssl", "struct", "sys", "threading", "time", "urllib"}


def mint(i, suffix="pump"):
    import selftest_radar as SR
    return SR.addr(7000 + i, suffix)


def frame(op, data, fin=True):
    n = len(data)
    return bytes([(0x80 if fin else 0) | op]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536
                                                  else bytes([127]) + struct.pack(">Q", n)) + data


def create(m, name="Dog Coin", creator=None, **kw):
    return dict({"signature": "5" * 88, "mint": m, "traderPublicKey": creator or mint(900, ""), "txType": "create", "initialBuy": 3.2e7,
                 "solAmount": 1.0, "bondingCurveKey": mint(901, ""), "vTokensInBondingCurve": 1.04e9, "vSolInBondingCurve": 31.0, "marketCapSol": 30.1,
                 "name": name, "symbol": "DOGC", "uri": "https://ipfs.io/ipfs/QmDogCoinMetadata", "pool": "pump"}, **kw)


def migrate(m, **kw):
    return dict({"signature": "4" * 88, "mint": m, "txType": "migrate", "pool": "pump-amm"}, **kw)


def trade_msg(m, side="buy", **kw):
    """A trade message as PumpPortal documents it (its names unverified until the first live run logs them)."""
    return dict({"signature": "3" * 88, "mint": m, "traderPublicKey": mint(950, ""), "txType": side, "tokenAmount": 1.2e6, "solAmount": 0.4,
                 "newTokenBalance": 1.2e6, "bondingCurveKey": mint(951, ""), "vTokensInBondingCurve": 4.8e8, "vSolInBondingCurve": 67.0,
                 "marketCapSol": 139.6, "pool": "pump"}, **kw)


def raw(tmp, rd, k):
    """A run's last sandbox lists.json (bytes), None when there is none."""
    try:
        with open(os.path.join(tmp, rd, "sb", k, "lists.json"), "rb") as f:
            return f.read()
    except OSError:
        return None


def wait_for(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        threading.Event().wait(0.02)
    return bool(cond())


# ---------------------------------------------------------------- the stand-in server
class Conn:
    """One accepted connection as the scripts see it: send(obj or bytes), frame bytes, wait, and what the client sent."""

    def __init__(self, srv, c):
        self.srv, self.c, self.closed = srv, c, threading.Event()

    def raw(self, b):
        self.c.sendall(b)

    def send(self, obj):
        self.c.sendall(frame(1, obj if isinstance(obj, bytes) else json.dumps(obj).encode()))

    def subs(self, n=2):
        return wait_for(lambda: len([s for s in self.srv.subs if s[0] is self]) >= n, 3)

    def idle(self):
        self.closed.wait(30)


class Stand:
    """The stand-in for PumpPortal's websocket. script(i) -> a function(conn) for the i-th connection (0 first), or "refuse" (HTTP 403).
    now / most: connections open now and at most at once (open from accept until the client's side ends); conns: connections made;
    subs, pongs, closes: the client's subscriptions, pong payloads and close codes."""

    def __init__(self, script):
        self.script, self.lock = script, threading.Lock()
        self.now = self.most = self.conns = 0
        self.subs, self.pongs, self.closes, self.halt = [], [], [], threading.Event()
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(16)
        self.s.settimeout(0.2)
        self.url = "ws://127.0.0.1:%d/api/data" % self.s.getsockname()[1]
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.halt.is_set():
            try:
                c, _ = self.s.accept()
            except (socket.timeout, OSError):
                continue
            with self.lock:
                i = self.conns
                self.conns += 1
                self.now += 1
                self.most = max(self.most, self.now)
            threading.Thread(target=self.handle, args=(c, i), daemon=True).start()

    def reader(self, conn):
        c = conn.c

        def rd(n):
            b = b""
            while len(b) < n:
                x = c.recv(n - len(b))
                if not x:
                    raise EOFError
                b += x
            return b
        try:
            while True:
                b0, b1 = rd(2)
                n = b1 & 0x7F
                n = struct.unpack(">H", rd(2))[0] if n == 126 else struct.unpack(">Q", rd(8))[0] if n == 127 else n
                mask = rd(4) if b1 & 0x80 else None
                data = bytes(x ^ mask[i % 4] for i, x in enumerate(rd(n))) if mask else rd(n)
                op = b0 & 0x0F
                with self.lock:
                    if op == 1:
                        self.subs.append((conn, json.loads(data), bool(mask)))
                    elif op == 0xA:
                        self.pongs.append(data)
                    elif op == 8:
                        self.closes.append(struct.unpack(">H", data[:2])[0] if len(data) >= 2 else None)
        except Exception:
            pass
        finally:
            with self.lock:
                self.now -= 1
            conn.closed.set()

    def handle(self, c, i):
        conn = Conn(self, c)
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                req += c.recv(4096)
            script = self.script(i)
            if script == "refuse":
                c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                with self.lock:
                    self.now -= 1
                conn.closed.set()
                return
            key = [l.split(b":", 1)[1].strip() for l in req.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1(key + GUID).digest())
            c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
            threading.Thread(target=self.reader, args=(conn,), daemon=True).start()
            script(conn)
        except Exception:
            pass
        finally:
            conn.closed.wait(5)
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self.halt.set()
        self.s.close()


def acks(conn):
    conn.subs()
    conn.send({"message": "Successfully subscribed to token creation events."})
    conn.send({"message": "Successfully subscribed to token migration events."})


def events(evs, keep=True):
    def go(conn):
        acks(conn)
        for e in evs:
            conn.send(e)
        if keep:
            conn.idle()
    return go


def every(go):
    """The same script for every connection."""
    return lambda i: go


@contextlib.contextmanager
def patched(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def run_feed(script, until, secs=8.0):
    """A LiveFeed on a new stand-in until until(feed) holds (at most secs): (feed, stand, events taken, log lines)."""
    st = Stand(script)
    f = RF.LiveFeed(st.url).start()
    wait_for(lambda: until(f), secs)
    evs = f.take()
    return f, st, evs, f.lines()


# ---------------------------------------------------------------- stubs for Radar.idle
class StubClock:
    def __init__(self, t, fake=False):
        self.t, self.fake, self.waits, self.step = int(t), fake, [], 6000

    def now(self):
        return self.t

    def wait(self, t):
        self.waits.append(int(t))
        self.t = max(self.t, int(t))


class StubFeed:
    """LiveFeed's interface over fixed events [(ms, kind, mint)]: take() hands those whose time has come on the clock."""

    def __init__(self, evs, clock):
        self.evs, self.clock, self.taken = sorted(evs), clock, 0

    def take(self):
        due = [e for e in self.evs if e[0] <= self.clock.t]
        self.evs = self.evs[len(due):]
        self.taken += len(due)
        return [{"kind": k, "mint": m, "t": t} for t, k, m in due]

    def lines(self):
        return []

    def info(self, m):
        return None

    def state(self):
        return "ok"

    def stats(self):
        return {}

    def stop(self, timeout=3.0):
        return True


# ---------------------------------------------------------------- the checks
def checks(check, sleep=None):
    old_sleep = time.sleep
    if sleep:
        time.sleep = sleep
    tmp = tempfile.mkdtemp(prefix="memebot-feed-")
    try:
        with patched(RF, BACKOFF_S=(0.2, 0.2, 0.3, 0.3, 0.3), READ_TIMEOUT_S=0.2):
            f1_events(check)
            f2_limits(check)
        f3_memory(check)
        f4_idle(check, tmp)
        f5_asks(check, tmp)
        f6_runs(check, tmp)
        f7_static(check)
        with patched(RF, BACKOFF_S=(0.2, 0.2, 0.3, 0.3, 0.3), READ_TIMEOUT_S=0.2, SUB_EVERY_S=0.2):
            f8_trades(check)
            f10_refused(check)
        f9_fast_idle(check, tmp)
    finally:
        time.sleep = old_sleep
        shutil.rmtree(tmp, ignore_errors=True)


def f1_events(check):
    print("== live feed F1: events from the stand-in (creates, graduations, fragments, pings, oversize, garbage, shapes)")
    good = [mint(i) for i in range(4)]
    evs = [create(good[0], name="Dog Coin"), create("0OIl" * 11, name="Bad Mint"), create(good[1], creator="not-an-address"), migrate(good[0]),
           migrate(good[2] + "\n"), {"txType": "buy", "mint": good[3]}, migrate(good[3])]
    f, st, got, lines = run_feed(every(events(evs)), lambda f: f.stats()["migrations"] >= 2)
    stop_t = time.time()
    stopped = f.stop()
    stop_s = time.time() - stop_t
    wait_for(lambda: st.closes, 2)
    mem = json.dumps([list(f.creates.items()), got])
    check([(e["kind"], e["mint"]) for e in got] == [("create", good[0]), ("create", good[1]), ("migrate", good[0]), ("migrate", good[3])]
          and all(set(e) <= {"kind", "mint", "t", "creator"} and isinstance(e["t"], int) for e in got) and f.info(good[0]) == {"t": got[0]["t"], "creator": mint(900, "")}
          and f.info(good[1])["creator"] is None and f.info(good[2]) is None and not re.search(r"Dog Coin|DOGC|ipfs|Bad Mint", mem),
          "creates and graduations become events (base58 mints only: a bad mint, a mint with a newline and a creator that is no address are "
          "dropped, a buy is ignored); info() gives the receipt time and the creator; no name, symbol or link is kept (%d events)" % len(got))
    check([s[1] for s in st.subs] == list(RF.SUBS) and all(s[2] for s in st.subs) and len({id(s[0]) for s in st.subs}) == 1 and st.conns == 1 and st.most == 1,
          "one connection, both subscriptions on it (masked frames): %s" % [s[1]["method"] for s in st.subs])
    check(stopped and stop_s < 3.0 and f.th.daemon and not f.th.is_alive() and st.closes == [1000] and f.state() == "off",
          "stop() closes the socket with a close frame (1000) and joins in %.1f s; the thread is a daemon" % stop_s)
    st.close()

    def frag(conn):
        acks(conn)
        conn.raw(frame(9, b"hi"))
        msg = json.dumps(create(good[1])).encode()
        conn.raw(frame(1, msg[:10], fin=False) + frame(0, msg[10:40], fin=False) + frame(9, b"mid") + frame(0, msg[40:300], fin=False))
        threading.Event().wait(0.5)                                # a read timeout falls between two fragments: nothing is lost
        conn.raw(frame(0, msg[300:], fin=True))
        big = json.dumps(migrate(good[2], pad="z" * 70_000)).encode()
        conn.raw(frame(1, big[:5]))                              # a whole small frame ...
        conn.raw(frame(1, big)[:3])
        threading.Event().wait(0.4)
        conn.raw(frame(1, big)[3:])                              # ... and a 64-bit length split across a timeout
        conn.idle()
    f, st, got, lines = run_feed(every(frag), lambda f: f.stats()["migrations"] >= 1)
    f.stop()
    check([e["mint"] for e in got] == [good[1], good[2]] and b"hi" in st.pongs and b"mid" in st.pongs and st.most == 1,
          "a message in fragments with a ping between them and a read timeout inside is put together; pings get pongs (%s); a 70 KB frame "
          "split across a timeout is read whole" % st.pongs)
    st.close()

    big = json.dumps(create(good[3], pad="z" * 2_000_000)).encode()
    half = json.dumps(create(good[2], pad="z" * 1_200_000)).encode()

    def big_first(i):
        if i == 0:                               # a 2 MB frame's header and its first bytes: closed at the header, the rest never waited for
            return lambda conn: (acks(conn), conn.raw(frame(1, big)[:1000]), conn.idle())
        if i == 1:                               # 1.2 MB in two fragments under the cap each: closed at the second
            return lambda conn: (acks(conn), conn.raw(frame(1, half[:600_000], fin=False) + frame(0, half[600_000:])), conn.idle())
        return events([create(good[0]), migrate(good[0])])
    f, st, got, lines = run_feed(big_first, lambda f: f.stats()["migrations"] >= 1)
    f.stop()
    wait_for(lambda: st.closes.count(1009) >= 2, 2)
    check([e["mint"] for e in got] == [good[0], good[0]] and st.closes.count(1009) == 2 and st.conns == 3 and st.most == 1
          and sum("closed (1009)" in l for l in lines) == 2,
          "a message over 1 MB is never kept: a 2 MB frame is closed (1009) at its header, a 1.2 MB message in fragments at the fragment "
          "that passes 1 MB; each time the feed reconnects (%d connections, at most %d at once) and the next one delivers" % (st.conns, st.most))
    st.close()

    junk = [b"not json {", b"[1, 2]", {"errors": "Invalid message: " + good[3]}, {"errors": "again"}, {"message": "ok"}, create(good[0]), migrate(good[0])]
    f, st, got, lines = run_feed(every(events(junk)), lambda f: f.stats()["migrations"] >= 1)
    f.stop()
    check([e["mint"] for e in got] == [good[0], good[0]] and f.stats()["msgs"] == 9 and sum("error" in l for l in lines) == 1
          and sum("not JSON" in l for l in lines) == 1 and not any(good[3] in l for l in lines) and any("(address)" in l for l in lines),
          "garbage, acks and error messages are only counted (%d messages); an error is said once, without the address in it" % f.stats()["msgs"])
    st.close()

    shape = [create(None), create(good[0]), migrate(good[1]), migrate(good[2])]
    f, st, got, lines = run_feed(every(events(shape)), lambda f: f.stats()["migrations"] >= 2)
    st_ok = f.state()
    f.stop()
    check([(e["kind"], e["mint"]) for e in got] == [("migrate", good[1]), ("migrate", good[2])] and st_ok == "ok" and f.kinds == {"create": False, "migrate": True}
          and any("create events are ignored" in l for l in lines),
          "the first create has no mint: creates are ignored for the run, graduations keep flowing, the feed stays %s" % st_ok)
    st.close()
    f, st, got, lines = run_feed(every(events([create(None), migrate(12345), migrate(good[1])])), lambda f: len(f.kinds) == 2)
    st_off = f.state()
    f.stop()
    check(got == [] and st_off == "off", "both kinds fail their shape check: no event, state off (%s)" % st_off)
    st.close()


def f2_limits(check):
    print("== live feed F2: one connection at a time, refusals, reconnect storms, stalls")
    st = Stand(lambda i: "refuse")
    f = RF.LiveFeed(st.url).start()
    wait_for(lambda: f.state() == "off", 6)
    threading.Event().wait(0.8)
    lines = f.lines()
    check(f.state() == "off" and st.conns == RF.MAX_REFUSED and f.stats()["refused"] == RF.MAX_REFUSED and not f.th.is_alive()
          and sum("given up" in l for l in lines) == 1,
          "HTTP 403 three times: state off for the run, no further connection (%d), said once" % st.conns)
    f.stop()
    st.close()

    def abrupt(conn):
        acks(conn)
        conn.raw(frame(1, json.dumps(create(mint(1))).encode())[:30])          # half a frame, then the connection is gone
        conn.c.shutdown(socket.SHUT_RDWR)
    st = Stand(every(abrupt))
    f = RF.LiveFeed(st.url).start()
    wait_for(lambda: f.state() == "off", 15)
    threading.Event().wait(0.5)
    lines = f.lines()
    check(f.state() == "off" and st.conns == RF.MAX_CONNECTS and st.most == 1 and f.take() == [] and any("%d connections" % RF.MAX_CONNECTS in l for l in lines),
          "a connection that breaks mid-frame every time: reconnects one at a time (at most %d at once), %d connections in all, then off"
          % (st.most, st.conns))
    f.stop()
    st.close()

    with patched(RF, STALL_S=1.0):
        st = Stand(every(lambda conn: conn.idle()))
        f = RF.LiveFeed(st.url).start()
        wait_for(lambda: st.conns >= 2, 6)
        lines = f.lines()
        f.stop()
        wait_for(lambda: 1000 in st.closes, 2)
    check(st.conns >= 2 and st.most == 1 and any("no message for" in l for l in lines) and 1000 in st.closes,
          "a silent connection (no message for STALL_S) is closed and made again, never two at once (%d connections)" % st.conns)
    st.close()
    plain = socket.socket()                     # a wss:// feed whose server does not speak TLS: a TLS refusal each time
    plain.bind(("127.0.0.1", 0))
    plain.listen(8)
    plain.settimeout(0.2)
    tls_n, halt = [0], threading.Event()

    def no_tls():
        while not halt.is_set():
            try:
                c, _ = plain.accept()
            except (socket.timeout, OSError):
                continue
            tls_n[0] += 1
            c.recv(4096)
            c.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            c.close()
    threading.Thread(target=no_tls, daemon=True).start()
    f = RF.LiveFeed("wss://127.0.0.1:%d/api/data" % plain.getsockname()[1]).start()
    wait_for(lambda: f.state() == "off", 6)
    lines = f.lines()
    f.stop()
    halt.set()
    plain.close()
    src = open(os.path.join(HERE, "radar_feed.py"), encoding="utf-8").read()
    check(f.state() == "off" and tls_n[0] == RF.MAX_REFUSED and f.stats()["refused"] == RF.MAX_REFUSED and any("TLS refused" in l for l in lines)
          and "ssl.create_default_context().wrap_socket(self.s, server_hostname=host)" in src and not re.search(r"CERT_NONE|check_hostname|_create_unverified", src),
          "wss:// with certificate checks and SNI (the default context, never loosened); a server that fails the TLS handshake is a refusal: "
          "off after %d" % tls_n[0])
    check(RF.url_of("pumpportal") == RF.FEED_URL == "wss://pumpportal.fun/api/data" and RF.url_of("on") == RF.url_of("1") == RF.FEED_URL
          and RF.url_of("off") is None and RF.url_of("") is None and RF.url_of(None) is None and RF.url_of("0") is None
          and RF.url_of("ws://127.0.0.1:9/x") == "ws://127.0.0.1:9/x" and RF.url_of("ws://localhost:9") == "ws://localhost:9"
          and RF.url_of("ws://example.com:9") is None and RF.url_of("wss://other.example/api") == "wss://other.example/api"
          and RF.url_of("http://127.0.0.1:9") is None and RF.url_of("ws://127.0.0.1:99999") is None and RF.url_of("ws://127.0.0.1") is None,
          "MEMEBOT_RADAR_FEED: pumpportal/on/1 PumpPortal, off/0/empty none, a local ws:// or any wss:// URL as given, anything else none")


def f3_memory(check):
    print("== live feed F3: bounded memory")
    t = [1_000_000]
    f = RF.LiveFeed(None, lambda: t[0])
    alph = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    b58 = lambda i: "".join(alph[(i // 58 ** k) % 58] for k in range(6))
    for i in range(30_000):
        f.handle(json.dumps({"txType": "create", "mint": "Feed" + b58(i) + "1" * 30, "traderPublicKey": "C" * 44, "name": "n%d" % i}))
        t[0] += 1
    n_cr, n_q, st = len(f.creates), len(f.q), f.stats()
    oldest = next(iter(f.creates))
    t[0] += RF.KEEP_MS + 1
    f.handle(json.dumps({"txType": "create", "mint": "Late" + "1" * 40}))
    check(n_cr == RF.CREATES_MAX and n_q == RF.QUEUE_MAX and st["creates"] == 30_000 and st["dropped"] == 30_000 - RF.QUEUE_MAX
          and oldest == "Feed" + b58(10_000) + "1" * 30 and len(f.creates) == 1 and f.th is None,
          "30,000 creates: %d kept for info() (the newest), %d events waiting (the oldest dropped, %d counted), older than 2 h pruned"
          % (n_cr, n_q, st["dropped"]))


def f4_idle(check, tmp):
    import launch_radar as LR
    import selftest_radar as SR
    print("== live feed F4: Radar.idle (a stub wall clock) and the loop's grid after an early cycle")
    T, P, _ = SR.modules()
    B = SR.T0
    m1 = mint(11)

    def idle(evs, start, cyc_at, t_k, early=(), fake=False):
        R = SR.unit_radar(T, P, tmp, "rdI")
        R.clock = StubClock(start, fake)
        R.live = StubFeed(evs, R.clock)
        R.cyc_at, R.early = cyc_at, list(early)
        R.fast_on = R.curve_on = False           # the early cycle on its own (the fast lane and the curve watch: F8)
        return R.idle(t_k), R
    with patched(LR, LIVE_DEBOUNCE_MS=500, LIVE_MIN_GAP_MS=1000, LIVE_LEAD_MS=2000):
        t_a, R_a = idle([(B + 300, "migrate", m1)], B, B, B + 6000)
        t_b, _ = idle([(B + 900, "migrate", m1)], B, B, B + 6000)
        t_c, _ = idle([(B + 1, "migrate", m1)], B + 600, B, B + 6000)
        t_d, R_d = idle([(B + 4500, "migrate", m1)], B + 4500, B, B + 6000)
        t_e, R_e = idle([(B + 300, "migrate", m1)], B, B, B + 6000, early=[B - k * 60_000 for k in range(12)])
        t_e2, _ = idle([(B + 300, "migrate", m1)], B, B, B + 6000, early=[B - H - k * 60_000 for k in range(12)])
        t_f, R_f = idle([], B, B, B + 6000)
        t_g, R_g = idle([(B + 300, "migrate", m1)], B, B, B + 6000, fake=True)
        t_h, _ = idle([(B - 100, "migrate", m1)], B, B, B + 6000)
        gaps_f = [b - a for a, b in zip([B] + R_f.clock.waits, R_f.clock.waits)]
        check(t_a == B + 1000 and R_a.early == [t_a] and R_a.mig == {m1: B + 300} and t_b == B + 2000 and t_b - (B + 900) >= 500
              and t_c == B + 1600 and t_c - B >= 1000,
              "a graduation on the feed starts a cycle early (%+d ms), never before the debounce (%+d ms after it) nor sooner than the "
              "minimum gap after the last cycle (%+d ms)" % (t_a - B, t_b - B - 900, t_c - B))
        check(t_d == B + 6000 and R_d.early == [] and t_e == B + 6000 and len(R_e.early) == 12 and t_e2 == B + 1000 and t_h == B + 6000,
              "no early cycle when the grid point is closer than the lead, with 12 early cycles in the last hour (13 an hour ago: yes), or for "
              "a graduation the last cycle already asked about")
        check(t_f == B + 6000 and R_f.clock.waits[-1] == B + 6000 and max(gaps_f) <= 1000 and t_g == B + 6000 and R_g.clock.waits == [B + 6000]
              and R_g.mig == {m1: B + 300},
              "no events: it waits for the grid point, waking every second or sooner (%d wakes); the fake clock: one plain wait, then the "
              "events are taken" % len(R_f.clock.waits))

        R = SR.unit_radar(T, P, tmp, "rdL", extra=["--minutes", "1"])
        R.clock, R.step, R.hours = StubClock(B), 6000, (0, 24)
        R.fast_on = R.curve_on = False
        cycles = []
        R.start = R.save_cache = lambda: None
        R.cycle = lambda k, t_k, last: cycles.append((k, t_k, R.cyc_at)) or "ok"
        R.live_start = lambda: setattr(R, "live", StubFeed([(B + 6200, "migrate", m1)], R.clock))
        code = R.loop()
        ts = [c[1] for c in cycles]
    check(code == 0 and ts[:4] == [B, B + 6000, B + 7000, B + 13000] and all(b - a == 6000 for a, b in zip(ts[2:], ts[3:])) and ts[-1] < B + 60_000
          and ts[-1] + 6000 >= B + 60_000 and R.run_start == B and R.run_end == B + 60_000 and all(c[2] == c[1] for c in cycles),
          "the loop: after an early cycle the grid restarts there (%s s), the run's start and end stay, each cycle notes its start"
          % [round((t - B) / 1000.0) for t in ts[:5]])


def f5_asks(check, tmp):
    import selftest_radar as SR
    print("== live feed F5: DexScreener asks for the feed's graduations")
    T, P, _ = SR.modules()
    now = SR.T0
    R = SR.unit_radar(T, P, tmp, "rdD")
    fresh, old, bad, live = mint(21), mint(22), "0OIl" * 11, mint(23)
    R.docs = {"h": {"coins": {live: {"addr": live, "pool": now - 2 * MIN, "first": now - MIN, "later": {}}}}}
    R.rec_hour = {live: "h"}
    R.cache["pool"][fresh] = [None, False, now - 10_000]              # DexScreener had no pair for it 10 s ago
    sb = os.path.join(tmp, "sbD")
    os.makedirs(sb)
    with open(os.path.join(sb, "lists.json"), "w") as f_:
        json.dump({"profiles": []}, f_)
    before = open(os.path.join(sb, "lists.json"), "rb").read()
    base = R.ds_asks(sb, now)
    R.mig = {fresh: now - 30_000, old: now - 4 * MIN, bad: now - 10_000}
    asks = R.ds_asks(sb, now)
    check(base == [live] and asks == [live, fresh] and open(os.path.join(sb, "lists.json"), "rb").read() == before
          and R.live_fresh(now) == [bad, fresh] and R.live_fresh(now + 3 * MIN) == [],
          "a graduation of the last 3 minutes is asked right after the coins on the radar, even with a 10 s old 'no pair' entry; an older "
          "one and an invalid mint are not; lists.json is left as it is")


def f6_runs(check, tmp):
    import launch_radar as LR
    import selftest_radar as SR
    print("== live feed F6: radar runs with the feed (the radar's mock, a fake clock)")
    T, P, _ = SR.modules()
    only = SR.fixture("FEEDONLY", 31, pf=False, v3=False, gt=False, jup=False)          # in no list: only the feed names it
    mock = SR.RadarMock(list(SR.FIX.values()) + [only])
    srv = SR.serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    hosts = []
    real_cc = socket.create_connection

    def cc(addr_, *a, **kw):
        hosts.append(addr_[0])
        return real_cc(addr_, *a, **kw)
    socket.create_connection = cc
    try:
        code0, R0, l0, s0 = SR.run_radar(T, P, url, SR.fresh_remote(T, tmp, "f0", SR.T0), os.path.join(tmp, "rf0"), SR.T0, minutes=2.5,
                                         envs={"MEMEBOT_RADAR_FEED": "pumpportal"})
    finally:
        socket.create_connection = real_cc
    rem0 = os.path.join(tmp, "f0.git")
    doc0, recs0 = SR.radar_json(rem0), SR.hour_recs(rem0)
    check(code0 == 0 and R0.live is None and "pumpportal" not in (doc0.get("hosts") or {}) and not any("pumpportal" in str(h) for h in hosts)
          and any("live feed: not started" in l for l in l0) and only["a"] not in recs0,
          "'pumpportal' with --mock and the fake clock: no feed, no connection out (%d connections, all to %s)" % (len(hosts), sorted(set(hosts))))

    s_ = socket.socket()
    s_.bind(("127.0.0.1", 0))
    dead = "ws://127.0.0.1:%d/api/data" % s_.getsockname()[1]
    s_.close()
    with patched(RF, BACKOFF_S=(0.3,) * 5):
        code1, R1, l1, s1 = SR.run_radar(T, P, url, SR.fresh_remote(T, tmp, "f1", SR.T0), os.path.join(tmp, "rf1"), SR.T0, minutes=2.5,
                                         envs={"MEMEBOT_RADAR_FEED": dead})
        R1.live_stop()
    rem1 = os.path.join(tmp, "f1.git")
    doc1, recs1 = SR.radar_json(rem1), SR.hour_recs(rem1)
    check(code1 == 0 and (doc1.get("hosts") or {}).get("pumpportal") in ("off", "limited") and set(recs1) == set(recs0) and recs1
          and raw(tmp, "rf1", "0") == raw(tmp, "rf0", "0") is not None,
          "a feed that cannot connect: exit 0, pumpportal %s, the same %d coins rated as without the feed, lists.json byte for byte the same"
          % ((doc1.get("hosts") or {}).get("pumpportal"), len(recs1)))

    st = Stand(every(events([create(only["a"], creator=only["creator"]), migrate(only["a"]), migrate("0OIl" * 11)])))
    def hold(R):                         # the stand-in's events are in before cycle 0 (its idle takes them)
        start = R.live_start

        def go():
            start()
            wait_for(lambda: R.live is not None and R.live.stats()["migrations"] >= 1, 5)
        R.live_start = go
    code2, R2, l2, s2 = SR.run_radar(T, P, url, SR.fresh_remote(T, tmp, "f2", SR.T0), os.path.join(tmp, "rf2"), SR.T0, minutes=2.5,
                                     envs={"MEMEBOT_RADAR_FEED": st.url}, patch=hold)
    pp = (SR.radar_json(os.path.join(tmp, "f2.git")).get("hosts") or {}).get("pumpportal")
    R2.live_stop()
    wait_for(lambda: 1000 in st.closes, 2)
    recs2 = SR.hour_recs(os.path.join(tmp, "f2.git"))
    ro = recs2.get(only["a"]) or {}
    fd = ro.get("feed") or {}
    feed_t = (R2.mig or {}).get(only["a"])
    check(code2 == 0 and pp == "ok" and fd.get("mig") == feed_t and isinstance(fd.get("lag"), float) and fd["lag"] >= 0 and ro.get("found") == []
          and set(recs2) == set(recs0) | {only["a"]} and not any("feed" in r for a, r in recs2.items() if a != only["a"]) and st.most == 1 and 1000 in st.closes
          and ro.get("mint") and ro["mint"] >= SR.T0 and raw(tmp, "rf2", "0") == raw(tmp, "rf0", "0") is not None and any(l.startswith("live feed: stopped") for l in l2 + R2.lines_log),
          "a run with the feed: pumpportal %s; a coin only the feed named is asked and recorded with feed %s, no scan tag (%s) and the feed's "
          "mint time; the other records carry no feed key; lists.json unchanged; one connection, closed at the end" % (pp, fd, ro.get("found")))
    st.close()
    srv.shutdown()


def f7_static(check):
    import launch_radar as LR
    print("== live feed F7: radar.yml, the probe, the imports")
    wf = open(os.path.join(HERE, ".github", "workflows", "radar.yml"), encoding="utf-8").read()
    pr = open(os.path.join(HERE, ".github", "workflows", "probe-radar.yml"), encoding="utf-8").read()
    job_env = wf.split("    steps:")[0]
    check("      MEMEBOT_RADAR_FEED: ${{ vars.MEMEBOT_RADAR_FEED || 'pumpportal' }}   # the live pump.fun feed (one websocket, free); 'off' switches it off\n" in job_env
          and wf.count("MEMEBOT_RADAR_FEED") == 2 and sorted(int(x) for x in re.findall(r"^        timeout-minutes: (\d+)\b", wf, re.M)) == [1, 2, 3, 4, 62]
          and sum(1 for l in wf.splitlines() if "pip install" in l and not l.strip().startswith("#")) == 2 and "websocket" not in wf.replace("one websocket", "") and LR.LIVE_ENV == "MEMEBOT_RADAR_FEED",
          "radar.yml: the feed's switch in the job env (default pumpportal), the step timeouts still [1,2,3,4,62], no pip step added")
    check("        run: timeout 90 python3 radar_feed.py probe --seconds 60\n" in pr and re.search(r"^on:\n  workflow_dispatch:\n[a-z]", pr, re.M),
          "probe-radar.yml (by hand only): one step probes the feed for 60 s")
    src = open(os.path.join(HERE, "radar_feed.py"), encoding="utf-8").read()
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    methods = set(re.findall(r'"method":\s*"(\w+)"', src))
    check(mods <= STDLIB and [s["method"] for s in RF.SUBS] == ["subscribeNewToken", "subscribeMigration"]
          and methods == {"subscribeNewToken", "subscribeMigration", "subscribeTokenTrade", "unsubscribeTokenTrade"}
          and not re.search(r"subscribeAccountTrade|api/trade|trade-local|sendTransaction|privateKey|api-key|apiKey|secret", src),
          "radar_feed.py imports only the standard library (%s); it subscribes to new coins and graduations, and to the trades of the coins "
          "the curve watch follows (subscribeTokenTrade / unsubscribeTokenTrade, data only): no account feed, no trade API, no key, "
          "nothing signed or sent (%s)" % (", ".join(sorted(mods)), ", ".join(sorted(methods))))
    tree = ast.parse(open(os.path.join(HERE, "launch_radar.py"), encoding="utf-8").read())
    where = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "live_start"]
    stops = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "live_stop"]
    check(where == ["loop"] and stops == ["main"], "the feed starts only in loop (never in a round or the hours gate), main stops it (%s, %s)" % (where, stops))
    good = [mint(i) for i in range(3)]
    st = Stand(every(events([create(good[0]), migrate(good[1], timestamp=int(time.time() * 1000) - 1500), {"message": "ok"}])))
    out = []
    doc = RF.probe(st.url, 1.5, out=out.append)
    st.close()
    text = "\n".join(out)
    check(doc["state"] == "ok" and doc["stats"]["creates"] == 1 and "mint" in doc["kinds"]["create"]["fields"] and doc["kinds"]["migrate"]["lagS"] >= 1.0
          and doc["kinds"]["create"]["lagS"] is None and not any(g in text for g in good + [mint(900, ""), mint(901, "")]) and out[-1].startswith("PROBE_FEED {"),
          "the probe prints the state, the counts, the field names and the lag per kind (%s s for graduations), never an address"
          % doc["kinds"]["migrate"]["lagS"])


def f8_trades(check):
    print("== live feed F8: the curve watch's trade subscriptions on the same socket, the trades' shape check")
    good = [mint(40 + i) for i in range(45)]
    conns = []

    def go(conn):
        acks(conn)
        conns.append(conn)
        conn.idle()
    st = Stand(every(go))
    f = RF.LiveFeed(st.url).start()
    wait_for(lambda: conns and len(st.subs) >= 2, 3)
    took = f.follow([good[0], good[1], "0OIl" * 11, good[0], None])
    wait_for(lambda: any(x[1].get("method") == "subscribeTokenTrade" for x in st.subs), 3)
    conns[0].send(create(good[5]))
    for m in (trade_msg(good[0]), trade_msg(good[44]), trade_msg(good[1], "sell", pool="pump-amm", traderPublicKey="nope"), {"txType": "buy", "mint": good[0], "solAmount": "x"}):
        conns[0].send(m)
    wait_for(lambda: f.stats()["trades"] >= 2 and f.stats()["tbad"] >= 1, 3)
    got = f.take_trades()
    lines = f.lines()
    subs1 = [x[1] for x in st.subs if x[1].get("method", "").endswith("TokenTrade")]
    check(took == [good[0], good[1]] and subs1 == [{"method": "subscribeTokenTrade", "keys": sorted(good[:2])}] and all(x[2] for x in st.subs) and st.conns == 1
          and [(e["mint"], e["side"]) for e in got] == [(good[0], "buy"), (good[1], "sell")]
          and got[0] == {"mint": good[0], "t": got[0]["t"], "side": "buy", "sol": 0.4, "tok": 1.2e6, "vsol": 67.0, "vtok": 4.8e8, "mcs": 139.6, "who": mint(950, ""), "pool": "pump"}
          and got[1]["who"] is None and got[1]["pool"] == "pump-amm" and f.stats()["tbad"] == 1 and f.trade_state()["shape"] is True,
          "follow(): one subscribeTokenTrade with the base58 mints on the SAME socket (masked, no second connection); the trades of a followed coin "
          "come out with their numbers, the trader (base58 or none) and the pool; a coin not followed and a trade without a SOL amount are dropped")
    named = [l for l in lines if l.startswith("first ")]
    check(sorted(l.split(" message")[0] for l in named) == ["first buy", "first create", "first sell"] and any("fields bondingCurveKey, marketCapSol, mint" in l for l in named)
          and not any(m in l for l in lines for m in good + [mint(950, ""), mint(951, "")]) and not any(re.search(r"\b(139\.6|67\.0|0\.4)\b", l) for l in named),
          "the field NAMES of the first message of each kind are logged once, never a value or an address: %s" % named[0][:120])
    f.follow([good[1], good[2]])
    wait_for(lambda: any(x[1].get("method") == "unsubscribeTokenTrade" for x in st.subs), 3)
    f.follow(good)
    wait_for(lambda: f.trade_state()["subbed"] == RF.FOLLOW_MAX, 3)
    subs2 = [x[1] for x in st.subs if x[1].get("method", "").endswith("TokenTrade")][1:]
    now_sub = set(good[:2])
    for x in subs2:
        now_sub = (now_sub | set(x["keys"])) if x["method"] == "subscribeTokenTrade" else (now_sub - set(x["keys"]))
    check(subs2[:2] == [{"method": "unsubscribeTokenTrade", "keys": [good[0]]}, {"method": "subscribeTokenTrade", "keys": [good[2]]}]
          and f.trade_state()["subbed"] == RF.FOLLOW_MAX == 40 and now_sub == set(good[:40]) and len(subs2) == 3,
          "a coin that drops out is unsubscribed (unsubscribeTokenTrade with its mint only), a new one subscribed; 45 coins asked: the first %d "
          "only" % RF.FOLLOW_MAX)
    n_sub = len(st.subs)
    conns[0].c.shutdown(socket.SHUT_RDWR)
    wait_for(lambda: len(conns) >= 2 and len([x for x in st.subs[n_sub:] if x[1].get("method") == "subscribeTokenTrade"]) >= 1, 5)
    again = [x for x in st.subs[n_sub:] if x[0] is (conns[1] if len(conns) > 1 else None)]
    check(len(conns) == 2 and st.most == 1 and [x[1]["method"] for x in again][:3] == ["subscribeNewToken", "subscribeMigration", "subscribeTokenTrade"]
          and len(again[2][1]["keys"]) == 40,
          "after a reconnect (one socket at a time) the new socket gets both feeds and every followed coin again in one subscribeTokenTrade")
    f.stop()
    st.close()

    bad_first = [trade_msg(good[0], vTokensInBondingCurve=None, marketCapSol=None), trade_msg(good[0])]
    conns2 = []

    def go2(conn):
        acks(conn)
        conns2.append(conn)
        wait_for(lambda: any(x[0] is conn and x[1].get("method") == "subscribeTokenTrade" for x in st2.subs), 3)
        for m in bad_first:
            conn.send(m)
        conn.idle()
    st2 = Stand(every(go2))
    f2 = RF.LiveFeed(st2.url).start()
    f2.follow(good[:3])
    wait_for(lambda: any(x[1].get("method") == "unsubscribeTokenTrade" for x in st2.subs), 4)
    lines2 = f2.lines()
    check(f2.take_trades() == [] and f2.trade_state()["shape"] is False and f2.follow(good[:3]) == [] and f2.state() in ("ok", "limited")
          and sum("trades are ignored" in l for l in lines2) == 1 and f2.stats()["tbad"] == 2
          and [x[1] for x in st2.subs if x[1].get("method") == "unsubscribeTokenTrade"] == [{"method": "unsubscribeTokenTrade", "keys": sorted(good[:3])}],
          "the first trade without the curve's state (no virtual token reserves, no market cap in SOL): trades are ignored for the run, said "
          "once, every trade subscription dropped, follow() takes nothing more; graduations and new coins go on (state %s)" % f2.state())
    f2.stop()
    st2.close()
    with patched(RF, TRADES_MAX=100):
        f3 = RF.LiveFeed(None, lambda: 5)
        f3.want = {good[0]}
        for i in range(150):
            f3.handle(json.dumps(trade_msg(good[0], solAmount=float(i))))
        q, n3 = list(f3.trades), f3.stats()
    check(len(q) == 100 and q[0]["sol"] == 50.0 and n3["trades"] == 150 and n3["tdropped"] == 50 and f3.th is None,
          "the trades waiting are bounded (TRADES_MAX): the oldest go first and are counted (%d dropped)" % n3["tdropped"])


def f10_refused(check):
    """A server that refuses the trade subscriptions (whether PumpPortal takes them keyless is unprobed): it drops the socket right after a
    subscribeTokenTrade, or answers it with an error. Two of these turn trades off for the run; later sockets ask for the new coins and the
    graduations only, so the migrate feed keeps its connections (MAX_CONNECTS) and flows on."""
    print("== live feed F10: a server that refuses the trade subscriptions (the graduations go on)")
    good = [mint(80 + i) for i in range(12)]
    conns = []

    def drop_after_sub(i):
        def go(conn):
            acks(conn)
            conns.append(conn)
            if i >= 2:
                conn.send(migrate(good[9]))
                return conn.idle()
            wait_for(lambda: any(x[0] is conn and x[1].get("method") == "subscribeTokenTrade" for x in st.subs), 3)
            conn.send(migrate(good[i]))
            threading.Event().wait(0.05)
            conn.c.shutdown(socket.SHUT_RDWR)        # no close frame, as a server-side drop
        return go
    st = Stand(drop_after_sub)
    f = RF.LiveFeed(st.url).start()
    f.follow(good[1:4])
    wait_for(lambda: len(conns) >= 3 and f.stats()["migrations"] >= 3, 8)
    threading.Event().wait(0.6)                      # a few of the thread's ticks: nothing more is asked on the third socket
    evs, lines, ts = f.take(), f.lines(), f.trade_state()
    third = [x[1] for x in st.subs if len(conns) > 2 and x[0] is conns[2]]
    check(ts["off"] and f.stats()["trefused"] == 2 and st.conns == 3 and not f.off and f.state() == "ok" and f.follow(good[1:4]) == []
          and third == list(RF.SUBS) and sorted(e["mint"] for e in evs if e["kind"] == "migrate") == sorted([good[0], good[1], good[9]])
          and sum("trades are off for this run" in l for l in lines) == 1,
          "the socket dropped right after a subscribeTokenTrade twice: trades are off for the run (said once), the third socket asks for the "
          "new coins and graduations only and the graduations flow on it (%d connections of %d, the feed not given up)" % (st.conns, RF.MAX_CONNECTS))
    f.stop()
    st.close()
    conns2 = []

    def errors_or_trades(i):
        def go(conn):
            acks(conn)
            conns2.append(conn)
            wait_for(lambda: any(x[0] is conn and x[1].get("method") == "subscribeTokenTrade" for x in st2.subs), 3)
            conn.send(trade_msg(good[1]) if i == 0 else {"errors": "Invalid message"})
            if i < 2:
                threading.Event().wait(0.05)
                conn.c.shutdown(socket.SHUT_RDWR)
            else:
                conn.idle()
        return go
    st2 = Stand(errors_or_trades)
    f2 = RF.LiveFeed(st2.url).start()
    f2.follow(good[1:4])
    wait_for(lambda: len(conns2) >= 3 and any(x[0] is conns2[2] and x[1].get("method") == "unsubscribeTokenTrade" for x in st2.subs), 8)
    ts2 = f2.trade_state()
    uns = [x[1] for x in st2.subs if len(conns2) > 2 and x[0] is conns2[2] and x[1].get("method") == "unsubscribeTokenTrade"]
    check(f2.stats()["trefused"] == 2 and ts2["off"] == "an error answered a trade subscription" and st2.conns == 3 and not f2.off
          and uns == [{"method": "unsubscribeTokenTrade", "keys": sorted(good[1:4])}] and ts2["n"] == 1,
          "a socket that carried a trade before it was dropped is no refusal; an error answer right after a subscribeTokenTrade is one (once a "
          "socket, also when the socket is dropped after it); at the second, trades are off and what is subscribed is dropped (%r)" % ts2["off"])
    f2.stop()
    st2.close()


def f9_fast_idle(check, tmp):
    import launch_radar as LR
    import selftest_radar as SR
    print("== live feed F9: Radar.idle with the fast lane (a stub wall clock; the fast lane itself is selftest_radar R15)")
    T, P, _ = SR.modules()
    B = SR.T0
    m1, m2 = mint(61), mint(62)

    def idle(evs, start, t_k, cyc_at=None, pre=None):
        R = SR.unit_radar(T, P, tmp, "rdJ")
        R.clock = StubClock(start)
        R.live = StubFeed(evs, R.clock)
        R.cyc_at, R.curve_on = cyc_at if cyc_at is not None else start, False
        ran = []

        def fake_fast(now, t_k_):
            ran.append((now, t_k_, sorted(R.fastq)))
            for a in list(R.fastq):
                R.fastq[a]["n"] += 1
                if R.fastq[a]["n"] >= len(LR.FAST_TRIES_MS) or (pre and a in pre):
                    R.fastq.pop(a)
                    if pre and a in pre:
                        R.docs.setdefault("h", {"coins": {}})["coins"][a] = {"addr": a}
                        R.rec_hour[a] = "h"
            R.fast_last = now
        R.fast = fake_fast
        return R.idle(t_k), R, ran
    t_a, R_a, ran_a = idle([(B + 300, "migrate", m1)], B, B + 120_000, pre={m1})
    t_b, R_b, ran_b = idle([(B + 300, "migrate", m2)], B, B + 120_000)
    check(t_a == B + 120_000 and [r[0] - B for r in ran_a] == [7_000] and R_a.early == []
          and [r[0] - B for r in ran_b] == [7_000, 15_000, 27_000, 46_000] and t_b == B + 60_000 and R_b.early == [B + 60_000],
          "a graduation on the feed: the fast lane runs at the first wake 6 s after it (%.1f s) and rates the coin, so no early cycle follows; "
          "a coin whose pool is never listed is tried at 6, 14, 26 and 45 s, then the early cycle takes it as before (at %d s)"
          % ((ran_a[0][0] - B - 300) / 1000.0, (t_b - B) // 1000))
    t_c, R_c, ran_c = idle([(B + 300, "migrate", m1)], B, B + 25_000)
    with patched(LR, FAST_PER_H=0):
        t_d, R_d, ran_d = idle([(B + 300, "migrate", m1)], B, B + 120_000)
    R_e = SR.unit_radar(T, P, tmp, "rdJe")
    R_e.fast_on = False
    R_e.live = StubFeed([(B, "migrate", m1)], StubClock(B + 1000))
    R_e.live_take(B + 1000)
    check(ran_c == [] and t_c == B + 25_000 and ran_d == [] and R_d.fastq == {} and len(R_d.early) == 1 and R_e.fastq == {} and R_e.mig == {m1: B},
          "no fast lane when the next round is closer than %d s (the round rates it), none once %d ran this hour (the early cycle does it, "
          "as before), none switched off (MEMEBOT_RADAR_FAST=off)" % (LR.FAST_LEAD_MS // 1000, LR.FAST_PER_H))
    with patched(LR, FAST_PER_H=1):
        t_f, R_f, ran_f = idle([(B + 300, "migrate", m2), (B + 400, "migrate", m1)], B, B + 120_000)
    check([r[0] - B for r in ran_f] == [7_000, 15_000, 27_000, 46_000] and all(r[2] == [m2] for r in ran_f) and t_f == B + 60_000
          and R_f.early == [B + 60_000] and len(R_f.fast_at) == 1,
          "FAST_PER_H counts graduations, not tries: with room for one, the first graduation gets all 4 of its tries (its pool never lists) and "
          "the second one is never queued, so the early cycle takes it as soon as it may (%d s), not after the first one's tries" % ((t_f - B) // 1000))


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    checks(check)
    print("\n%d feed checks failed" % len(fails) if fails else "\nFEED ALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
