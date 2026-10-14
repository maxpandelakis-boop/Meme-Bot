#!/usr/bin/env python3
"""radar_feed.py: the launch radar's live pump.fun feed (PumpPortal's free websocket). Fake money only: it only listens; it never signs,
sends or buys anything, and it holds no key.

launch_radar.py's loop (never a round) starts one LiveFeed when MEMEBOT_RADAR_FEED names one (radar.yml: 'pumpportal'; 'off' or unset:
none). A daemon thread owns ONE websocket to wss://pumpportal.fun/api/data and subscribes to new coins (subscribeNewToken) and to
graduations (subscribeMigration) on it. Between its cycles the loop takes the events:
  - a graduation (txType migrate): DexScreener is asked about the mint right after the coins on the radar, and the next cycle may come
    early (launch_radar.Radar.early_due);
  - a new coin (txType create): its mint time (when the feed got it) and its creator.
Rules (PumpPortal asks for one connection; a client that opens many may be banned):
  - one socket at a time; a reconnect only after the old one is closed, BACKOFF_S apart, at most MAX_CONNECTS a run;
  - MAX_REFUSED refusals (HTTP 401, 403, 404, 410, 429, 451, or TLS) give the feed up for the run, said once;
  - no message for STALL_S (the new coins are the heartbeat): reconnect; a message over MAX_MSG: close 1009, reconnect;
  - the first message of each kind is shape-checked (a base58 mint); when it fails, that kind is ignored for the run;
  - a mint must be base58; names, symbols and links are never stored; no HTTP request per event; the queue and the creates are bounded.
The thread never calls the radar and never logs: lines() hands its log lines to the loop. Any failure leaves the radar as it is without
the feed (the page's host list then says limited or off). Standard library only.

  python3 radar_feed.py probe --seconds 60     status, counts, field names and the lag per kind; never an address
"""
import argparse, base64, collections, hashlib, json, os, re, socket, ssl, struct, sys, threading, time, urllib.parse

FEED_URL = "wss://pumpportal.fun/api/data"
SUBS = ({"method": "subscribeNewToken"}, {"method": "subscribeMigration"})     # both on the one socket
MAX_MSG = 1_000_000         # bytes: a bigger message closes the socket (1009) and reconnects
READ_TIMEOUT_S = 1.0        # the thread's tick: it sees the stop flag at least this often
CONNECT_TIMEOUT_S = 10
STALL_S = 90                # no message for this long: reconnect (pump.fun makes a new coin every few seconds)
BACKOFF_S = (15, 30, 60, 120, 300)
MAX_CONNECTS = 8            # a run
MAX_REFUSED = 3             # a run
REFUSED = (401, 403, 404, 410, 429, 451)
QUEUE_MAX = 2000            # events not taken yet (the oldest go first)
CREATES_MAX = 20000         # new coins kept for info()
KEEP_MS = 2 * 3_600_000     # ... at most this long
KINDS = ("create", "migrate")
B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,48}")
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def url_of(v):
    """MEMEBOT_RADAR_FEED -> the feed's URL or None: 'pumpportal', '1' or 'on' PumpPortal; '', '0' or 'off' none; a ws:// URL on
    127.0.0.1 or localhost (the selftests' stand-in) or a wss:// URL as given; anything else none."""
    s = str(v or "").strip()
    if s.lower() in ("pumpportal", "1", "on"):
        return FEED_URL
    if s.lower() in ("", "0", "off"):
        return None
    try:
        u = urllib.parse.urlsplit(s)
        port = u.port
    except ValueError:
        return None
    if (u.scheme == "wss" and u.hostname) or (u.scheme == "ws" and u.hostname in ("127.0.0.1", "localhost") and port):
        return s
    return None


def short(e):
    """An error in a few words: no URL, at most 80 characters."""
    return re.sub(r"\s+", " ", re.sub(r"\w+://\S+", "(address)", "%s %s" % (type(e).__name__, e)))[:80]


def clean(v, n=120):
    """A server's text for the log: printable, without anything that looks like an address."""
    return B58.sub("(address)", re.sub(r"[^\x20-\x7e]", "", str(v)))[:n]


# ---------------------------------------------------------------- the websocket (RFC 6455, client side)
class WsError(Exception):
    """A connection that failed or broke; refused: the server said no (an HTTP refusal or TLS), counted towards MAX_REFUSED."""

    def __init__(self, why, refused=False):
        Exception.__init__(self, why)
        self.refused = refused


class TooBig(WsError):
    pass


class WS:
    """One client connection: the handshake (Sec-WebSocket-Accept checked, no extension taken; TLS with SNI and certificate checks),
    masked frames out, whole frames in. Frames are parsed from a buffer and taken out only once whole, so a read timeout (the thread's
    tick) never loses half a frame."""

    def __init__(self, url, timeout=CONNECT_TIMEOUT_S):
        u = urllib.parse.urlsplit(url)
        host, port = u.hostname, u.port or (443 if u.scheme == "wss" else 80)
        self.buf, self.pos, self.parts, self.size, self.shut = bytearray(), 0, None, 0, False
        self.s = socket.create_connection((host, port), timeout=timeout)
        try:
            if u.scheme == "wss":
                try:
                    self.s = ssl.create_default_context().wrap_socket(self.s, server_hostname=host)
                except ssl.SSLError as e:
                    raise WsError("TLS refused (%s)" % type(e).__name__, refused=True)
            key = base64.b64encode(os.urandom(16))
            hdr = ["GET %s HTTP/1.1" % ((u.path or "/") + ("?" + u.query if u.query else "")), "Host: %s" % (host if port in (80, 443) else "%s:%d" % (host, port)),
                   "Upgrade: websocket", "Connection: Upgrade", "Sec-WebSocket-Key: " + key.decode(), "Sec-WebSocket-Version: 13"]
            self.s.sendall(("\r\n".join(hdr) + "\r\n\r\n").encode())
            while b"\r\n\r\n" not in self.buf:
                chunk = self.s.recv(4096)
                if not chunk or len(self.buf) > 16384:
                    raise WsError("handshake: no answer")
                self.buf += chunk
            head, rest = bytes(self.buf).split(b"\r\n\r\n", 1)
            self.buf = bytearray(rest)
            lines = head.decode("latin-1").split("\r\n")
            m = re.match(r"HTTP/1\.[01] (\d{3})", lines[0])
            code = int(m.group(1)) if m else 0
            if code != 101:
                raise WsError("handshake: HTTP %s" % (code or "?"), refused=code in REFUSED)
            fields = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
            if fields.get("sec-websocket-accept") != base64.b64encode(hashlib.sha1(key + GUID).digest()).decode():
                raise WsError("handshake: bad accept")
            if fields.get("sec-websocket-extensions"):
                raise WsError("handshake: an extension not asked for")
            self.s.settimeout(READ_TIMEOUT_S)
        except BaseException:
            self.s.close()
            raise

    def send(self, op, data=b""):
        n, mask = len(data), os.urandom(4)
        head = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0xFE]) + struct.pack(">H", n) if n < 65536 else bytes([0xFF]) + struct.pack(">Q", n))
        self.shut = self.shut or op == 0x8
        self.s.sendall(head + mask + bytes(b ^ mask[i & 3] for i, b in enumerate(data)))

    def frame(self):
        """(fin, opcode, payload) of the next whole frame, reading more as needed; socket.timeout passes through (the caller's tick)."""
        while True:
            b, p = self.buf, self.pos
            if len(b) - p >= 2:
                if b[p] & 0x70:
                    raise WsError("reserved bits set (no extension was agreed)")
                if b[p + 1] & 0x80:
                    raise WsError("a masked frame from the server")
                n, at = b[p + 1] & 0x7F, p + 2
                if n == 126:
                    n, at = (struct.unpack_from(">H", b, p + 2)[0], p + 4) if len(b) - p >= 4 else (None, at)
                elif n == 127:
                    n, at = (struct.unpack_from(">Q", b, p + 2)[0], p + 10) if len(b) - p >= 10 else (None, at)
                if n is not None and n > MAX_MSG:
                    raise TooBig("a frame of %d bytes" % n)
                if n is not None and len(b) >= at + n:
                    self.pos = at + n
                    return b[p] & 0x80, b[p] & 0x0F, bytes(b[at:at + n])
            chunk = self.s.recv(65536)
            if not chunk:
                raise WsError("closed without a close frame")
            if self.pos:
                del self.buf[:self.pos]
                self.pos = 0
            self.buf += chunk

    def recv(self):
        """The next message (str), answering pings; None when the server closed. socket.timeout passes through; a message in fragments
        is kept across timeouts (control frames may come between its fragments)."""
        while True:
            fin, op, data = self.frame()
            if op >= 0x8 and (not fin or len(data) > 125):
                raise WsError("a bad control frame")
            if op == 0x9:
                self.send(0xA, data)
                continue
            if op == 0xA:
                continue
            if op == 0x8:
                try:
                    self.send(0x8, data[:2])
                except OSError:
                    pass
                return None
            if op in (0x1, 0x2) and self.parts is None:
                self.parts, self.size = [], 0
            elif op != 0x0 or self.parts is None:
                raise WsError("opcode %d out of place" % op)
            self.parts.append(data)
            self.size += len(data)
            if self.size > MAX_MSG:
                raise TooBig("a message over %d bytes" % MAX_MSG)
            if fin:
                out, self.parts = b"".join(self.parts), None
                return out.decode("utf-8", "replace")

    def close(self, code=1000):
        """A close frame (unless one went already), then the socket closed. Never raises."""
        try:
            if not self.shut:
                self.send(0x8, struct.pack(">H", code))
        except (OSError, ValueError):
            pass
        try:
            self.s.close()
        except OSError:
            pass

    def abort(self):
        """Shuts the socket down from another thread: its read ends at once."""
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------- the feed (one daemon thread, one socket)
class LiveFeed:
    """The feed's thread and what it hands over (module docstring). clock_ms: the runner's clock in ms (the radar's): the events' time."""

    def __init__(self, url, clock_ms=None):
        self.url, self.clock = url, clock_ms or (lambda: int(time.time() * 1000))
        self.lock, self.halt, self.th, self.ws = threading.Lock(), threading.Event(), None, None
        self.q, self.creates, self.log = collections.deque(maxlen=QUEUE_MAX), collections.OrderedDict(), collections.deque(maxlen=200)
        self.n = dict.fromkeys(("connects", "msgs", "creates", "migrations", "dropped", "refused"), 0)
        self.kinds, self.said, self.off, self.up, self.heard = {}, set(), False, False, 0.0

    def start(self):
        self.th = threading.Thread(target=self.run, name="radar-feed", daemon=True)
        self.th.start()
        return self

    def stop(self, timeout=3.0):
        """Sets the stop flag; the thread closes its socket at its next tick (a close frame), else the socket is shut down from here.
        Joins; True when the thread has ended."""
        self.halt.set()
        th = self.th
        if th is None:
            return True
        th.join(min(timeout, READ_TIMEOUT_S + 0.5))
        if th.is_alive():
            with self.lock:
                ws = self.ws
            if ws is not None:
                ws.abort()
            th.join(max(0.1, timeout - READ_TIMEOUT_S - 0.5))
        return not th.is_alive()

    def state(self):
        """'ok' (connected, a message within STALL_S), 'limited' (connecting, reconnecting or stalled), 'off' (given up for the run,
        stopped, or every kind failed its shape check)."""
        with self.lock:
            dead = len(self.kinds) == len(KINDS) and not any(self.kinds.values())
        if self.off or self.halt.is_set() or dead:
            return "off"
        return "ok" if self.up and time.time() - self.heard < STALL_S else "limited"

    def take(self):
        """The events since the last take, oldest first: {kind: create|migrate, mint, t: ms on receipt, creator: a create's}."""
        with self.lock:
            out = list(self.q)
            self.q.clear()
        return out

    def info(self, mint):
        """{t, creator} of a new coin the feed saw (this run, the last 2 hours), else None."""
        with self.lock:
            v = self.creates.get(mint)
            return dict(v) if v else None

    def lines(self):
        """The thread's log lines since the last call."""
        with self.lock:
            out = list(self.log)
            self.log.clear()
        return out

    def stats(self):
        with self.lock:
            return dict(self.n)

    def say(self, s):
        with self.lock:
            self.log.append(s)

    def count(self, k):
        with self.lock:
            self.n[k] += 1
            return self.n[k]

    def run(self):
        fails = 0
        try:
            while not self.halt.is_set():
                self.count("connects")
                got = self.session()
                if self.off or self.halt.is_set():
                    return
                if self.n["connects"] >= MAX_CONNECTS:
                    return self.give_up("%d connections this run" % MAX_CONNECTS)
                fails = 0 if got else fails + 1
                wait = BACKOFF_S[min(len(BACKOFF_S) - 1, max(0, fails - 1))]
                self.say("reconnecting in %g s" % wait)
                self.halt.wait(wait)
        except Exception as e:
            self.give_up("the thread failed (%s)" % short(e))

    def give_up(self, why):
        self.off = True
        self.say("given up for this run: %s; the radar goes on without it" % why)

    def session(self):
        """One connection: connect, subscribe, read until stop, a stall, the server's close or an error. True when a message came."""
        try:
            ws = WS(self.url)
        except WsError as e:
            if e.refused and self.count("refused") >= MAX_REFUSED:
                self.give_up("refused %d times (%s)" % (MAX_REFUSED, e))
            else:
                self.say("no connection (%s)" % e)
            return False
        except (OSError, ValueError) as e:
            self.say("no connection (%s)" % short(e))
            return False
        with self.lock:
            self.ws = ws
        got = False
        try:
            if self.halt.is_set():
                return got
            for sub in SUBS:
                ws.send(0x1, json.dumps(sub).encode())
            self.heard = time.time()
            while not self.halt.is_set():
                try:
                    m = ws.recv()
                except socket.timeout:
                    if time.time() - self.heard > STALL_S:
                        self.say("no message for %g s: reconnecting" % STALL_S)
                        break
                    continue
                if m is None:
                    self.say("the server closed the connection")
                    break
                self.heard, self.up, got = time.time(), True, True
                self.handle(m)
        except TooBig as e:
            ws.close(1009)
            self.say("%s: closed (1009)" % e)
        except Exception as e:
            self.say("connection lost (%s)" % short(e))
        finally:
            self.up = False
            with self.lock:
                self.ws = None
            ws.close()
        return got

    def once(self, key, s):
        if key not in self.said:
            self.said.add(key)
            self.say(s)

    def handle(self, raw):
        """One message: an event into the queue (a create also into the creates); anything else is only counted."""
        self.count("msgs")
        try:
            j = json.loads(raw)
        except (ValueError, RecursionError):
            return self.once("json", "a message that is not JSON (counted, skipped)")
        kind = j.get("txType") if isinstance(j, dict) else None
        if kind not in KINDS:
            if isinstance(j, dict) and "errors" in j:
                self.once("errors", "the feed sent an error: %s" % clean(j.get("errors")))
            return
        mint = j.get("mint")
        ok = isinstance(mint, str) and bool(B58.fullmatch(mint))
        if kind not in self.kinds:
            with self.lock:
                self.kinds[kind] = ok
            if not ok:
                self.say("the first %s message has no base58 mint: %s events are ignored this run" % (kind, kind))
        if not (ok and self.kinds[kind]):
            return
        ev = {"kind": kind, "mint": mint, "t": int(self.clock())}
        if kind == "create":
            cr = j.get("traderPublicKey")
            ev["creator"] = cr if isinstance(cr, str) and B58.fullmatch(cr) else None
        with self.lock:
            if kind == "create":
                self.n["creates"] += 1
                if mint not in self.creates:
                    self.creates[mint] = {"t": ev["t"], "creator": ev["creator"]}
                while self.creates and (len(self.creates) > CREATES_MAX or ev["t"] - next(iter(self.creates.values()))["t"] > KEEP_MS):
                    self.creates.popitem(last=False)
            else:
                self.n["migrations"] += 1
            if len(self.q) >= QUEUE_MAX:
                self.n["dropped"] += 1
            self.q.append(ev)


# ---------------------------------------------------------------- the probe (probe-radar.yml, by hand)
class Probe(LiveFeed):
    """The feed with the field names per kind, the seconds to each kind's first message and the delivery lag when a message carries a
    time. Never an address: field names and counts only."""

    def __init__(self, url):
        LiveFeed.__init__(self, url)
        self.fields, self.first, self.lags, self.t0 = {}, {}, {}, time.time()

    def handle(self, raw):
        try:
            j = json.loads(raw)
        except (ValueError, RecursionError):
            j = None
        if isinstance(j, dict):
            tx = j.get("txType")
            kind = tx if isinstance(tx, str) and re.fullmatch(r"[a-zA-Z]{1,20}", tx) else "errors" if "errors" in j else "message" if "message" in j else "other"
            self.fields.setdefault(kind, set()).update(clean(k, 40) for k in list(j)[:60])
            self.first.setdefault(kind, round(time.time() - self.t0, 1))
            ts = next((j[k] for k in ("timestamp", "blockTime", "time") if isinstance(j.get(k), (int, float)) and not isinstance(j.get(k), bool)), None)
            if ts:
                self.lags.setdefault(kind, []).append(time.time() - (ts / 1000.0 if ts > 1e12 else ts))
        LiveFeed.handle(self, raw)


def probe(url, seconds, out=print):
    p = Probe(url).start()
    end = time.time() + max(1.0, seconds)
    while time.time() < end and p.state() != "off":
        time.sleep(1.0)
        for s in p.lines():
            out("feed: " + s)
    p.stop()
    for s in p.lines():
        out("feed: " + s)
    med = lambda xs: round(sorted(xs)[len(xs) // 2], 2) if xs else None
    doc = {"state": "off" if p.off else "ok" if p.n["msgs"] else "silent", "secs": round(time.time() - p.t0, 1), "stats": p.stats(),
           "kinds": {k: {"fields": sorted(v)[:60], "firstS": p.first.get(k), "lagS": med(p.lags.get(k, [])), "n": len(p.lags.get(k, []))} for k, v in sorted(p.fields.items())},
           "shape": dict(p.kinds)}
    out("probe: %s after %.0f s; %s" % (doc["state"], doc["secs"], ", ".join("%s %d" % kv for kv in sorted(doc["stats"].items()))))
    for k, v in doc["kinds"].items():
        out("probe: %s: first after %s s, lag %s s, fields %s" % (k, v["firstS"], v["lagS"] if v["lagS"] is not None else "(no time field)", ", ".join(v["fields"])))
    out("PROBE_FEED " + json.dumps(doc, separators=(",", ":")))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="the launch radar's live pump.fun feed (fake money only)")
    ap.add_argument("cmd", choices=["probe"])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--url", default="pumpportal", help="as MEMEBOT_RADAR_FEED (pumpportal, a wss:// URL, a local ws:// URL)")
    a = ap.parse_args(argv)
    url = url_of(a.url)
    if not url:
        print("probe: no feed (the URL is off or not allowed)")
        return 0
    probe(url, a.seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
