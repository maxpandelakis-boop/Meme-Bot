#!/usr/bin/env python3
"""radar_feed.py: the launch radar's live pump.fun feed (PumpPortal's free websocket). Fake money only: it only listens; it never signs,
sends or buys anything, and it holds no key.

launch_radar.py's loop (never a round) starts one LiveFeed when MEMEBOT_RADAR_FEED names one (radar.yml: 'pumpportal'; 'off' or unset:
none). A daemon thread owns ONE websocket to wss://pumpportal.fun/api/data and subscribes to new coins (subscribeNewToken) and to
graduations (subscribeMigration) on it. Between its cycles the loop takes the events:
  - a graduation (txType migrate): DexScreener is asked about the mint right after the coins on the radar, and the next cycle may come
    early (launch_radar.Radar.early_due);
  - a new coin (txType create): its mint time (when the feed got it), its creator and the curve's state in it (virtual token reserves,
    the market cap in SOL): the curve watch's first progress reading of the coin;
  - a trade (txType buy or sell) of a coin the curve watch follows (curve_watch.py): follow(mints) names them, the thread subscribes them
    with subscribeTokenTrade {"keys": [...]} on the SAME socket and unsubscribes a coin that drops out (unsubscribeTokenTrade); the loop
    takes the trades with take_trades() and replays them in order (progress on the curve, momentum, the creator selling).
Rules (PumpPortal asks for one connection; a client that opens many may be banned):
  - one socket at a time; a reconnect only after the old one is closed, BACKOFF_S apart, at most MAX_CONNECTS a run;
  - MAX_REFUSED refusals (HTTP 401, 403, 404, 410, 429, 451, or TLS) give the feed up for the run, said once;
  - no message for STALL_S (the new coins are the heartbeat): reconnect; a message over MAX_MSG: close 1009, reconnect;
  - the first message of each kind is shape-checked (a base58 mint); when it fails, that kind is ignored for the run; the first trade
    also needs a SOL amount and the curve's state (virtual token reserves or the market cap in SOL): when it fails, trades are ignored and
    every trade subscription is dropped for the run (the curve watch then reads pump.fun's list only). The field NAMES of the first
    message of each kind are logged once (never a value), so the first live run shows what PumpPortal really sends;
  - trade subscriptions: at most FOLLOW_MAX coins, at most one subscribe and one unsubscribe message every SUB_EVERY_S, all of them again
    after a reconnect; trades of coins not followed are dropped; the trades waiting are bounded (TRADES_MAX, the oldest go first);
  - a server that refuses them: a socket the server closes or drops within TRADE_REFUSE_S of a subscribeTokenTrade with no trade since,
    or an {"errors": ...} answer within that time, counts as one refusal; TRADE_REFUSALS of them turn trades off for the run, said once,
    and later sockets ask for the new coins and graduations only, so a refused trade feed never costs the graduations their connections
    (MAX_CONNECTS);
  - a server that takes them and sends nothing (PumpPortal: the first live run, 15 Oct, had 38 subscriptions accepted and not one trade
    in 55 minutes; it sends coin trades only to paid API-key clients, and this feed holds no key): no trade message at all while trade
    subscriptions were live on open sockets for TRADE_SILENT_S in all (each socket from its own first subscribeTokenTrade: time without
    a socket never counts), and trades not refused, makes trades silent for the run, said once: no subscribe or unsubscribe goes out any
    more (the subscriptions sent end with the socket) and the curve watch reads pump.fun's list only, its normal mode. A refusal below
    TRADE_REFUSALS does not hold it off. A feed that does send trades never gets there; a valid trade that still comes later lifts it
    (the subscriptions go on as before);
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
TRADE_KINDS = ("buy", "sell")
FOLLOW_MAX = 40             # coins whose trades are followed at once (the curve watch's best candidates)
SUB_EVERY_S = 2.0           # at most one subscribe and one unsubscribe message this often (a reconnect subscribes everything at once)
TRADES_MAX = 50_000         # trades not taken yet (a cycle of 100 s with 40 hot coins brings a few thousand)
NAMES_MAX = 40              # field names logged of a kind's first message
TRADE_REFUSE_S = 10.0       # a socket that ends this soon after a subscribeTokenTrade without a trade since, or an error answer this soon ...
TRADE_REFUSALS = 2          # ... this many times a run: trades are off for the run (the migrate feed keeps its connections)
TRADE_SILENT_S = 180.0      # no trade message at all while trade subscriptions were live this long in all, trades not refused: trades are
                            # silent for the run (no more trade subscriptions: PumpPortal sends coin trades to paid clients only)
TRADE_NUMS = (("sol", "solAmount"), ("tok", "tokenAmount"), ("vsol", "vSolInBondingCurve"), ("vtok", "vTokensInBondingCurve"), ("mcs", "marketCapSol"))
CREATE_NUMS = (("vtok", "vTokensInBondingCurve"), ("mcs", "marketCapSol"))     # the curve's state in a create (the first live run's names)
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


def fnum(v):
    """A finite number from a message, else None (never a bool)."""
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


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
        self.n = dict.fromkeys(("connects", "msgs", "creates", "migrations", "dropped", "refused", "trades", "tbad", "tdropped", "subs", "unsubs", "trefused"), 0)
        self.kinds, self.said, self.off, self.up, self.heard = {}, set(), False, False, 0.0
        self.want, self.subbed, self.trades, self.tshape = set(), set(), collections.deque(maxlen=TRADES_MAX), None
        self.sub_at, self.want_at, self.t_last = 0.0, None, None
        self.toff, self.tsub_t, self.tsock, self.terr = None, None, None, False     # trades refused (why); this socket's last trade subscription,
                                                                                    # its last trade, an error answer counted on it
        self.tfirst, self.tlive, self.tsilent = None, 0.0, None     # this socket's first trade subscription (s); the time trade subscriptions
                                                                    # were live on earlier sockets (s); trades silent for the run (why)

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
        """The events since the last take, oldest first: {kind: create|migrate, mint, t: ms on receipt, and a create's creator, vtok, mcs}."""
        with self.lock:
            out = list(self.q)
            self.q.clear()
        return out

    def follow(self, mints):
        """The coins whose trades the curve watch wants (base58 mints, the first FOLLOW_MAX): the thread subscribes the new ones and
        unsubscribes the dropped ones at its next tick. Returns the mints taken (none once the trades failed their shape check, were
        refused or are silent)."""
        ok = [m for m in dict.fromkeys(mints or []) if isinstance(m, str) and B58.fullmatch(m)][:FOLLOW_MAX]
        with self.lock:
            if self.tshape is False or self.toff or self.tsilent:
                ok = []
            if ok and not self.want:
                self.want_at = time.time()
            self.want = set(ok)
        return ok

    def take_trades(self):
        """The trades since the last call, oldest first: {mint, t: ms on receipt, side: buy|sell, sol, tok, vsol, vtok, mcs (numbers or
        None), who: the trader (base58 or None), pool: pump.fun's pool name or None}."""
        with self.lock:
            out = list(self.trades)
            self.trades.clear()
        return out

    def trade_state(self):
        """{shape: the first trade's check (None: none came yet), off: why the server's refusals turned trades off (None: they are not),
        silent: why trades are silent for the run (None: they are not), want, subbed: coins asked and subscribed, since: when the first coin
        was asked (s), last: the last trade (s), n: trades taken in}."""
        with self.lock:
            return {"shape": self.tshape, "off": self.toff, "silent": self.tsilent, "want": len(self.want), "subbed": len(self.subbed), "since": self.want_at,
                    "last": self.t_last, "n": self.n["trades"]}

    def info(self, mint):
        """{t, creator, vtok, mcs} of a new coin the feed saw (this run, the last 2 hours: the curve's virtual token reserves and market cap
        in SOL in its create, numbers or None), else None."""
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
            with self.lock:
                self.subbed = set()              # a new socket has no trade subscription yet: every followed coin is asked again
                self.tsub_t, self.tsock, self.terr = None, None, False
            self.sync(ws, force=True)
            self.heard = time.time()
            while not self.halt.is_set():
                self.sync(ws)
                try:
                    m = ws.recv()
                except socket.timeout:
                    if time.time() - self.heard > STALL_S:
                        self.say("no message for %g s: reconnecting" % STALL_S)
                        break
                    continue
                if m is None:
                    self.say("the server closed the connection")
                    self.closed_after_trades()
                    break
                self.heard, self.up, got = time.time(), True, True
                self.handle(m)
        except TooBig as e:
            ws.close(1009)
            self.say("%s: closed (1009)" % e)
        except Exception as e:
            self.say("connection lost (%s)" % short(e))
            self.closed_after_trades()
        finally:
            self.up = False
            with self.lock:
                self.ws = None
                self.subbed = set()
                if self.tfirst is not None:      # the silence rule counts the time trade subscriptions were live on this socket
                    self.tlive += max(0.0, time.time() - self.tfirst)
                    self.tfirst = None
            ws.close()
        return got

    def closed_after_trades(self):
        """The server closed or dropped this socket: one refusal of trades when that came within TRADE_REFUSE_S of its last
        subscribeTokenTrade with no trade since (trades flowing on it say the close is about something else)."""
        with self.lock:
            t, tr, err = self.tsub_t, self.tsock, self.terr
        if not self.halt.is_set() and not err and t is not None and time.time() - t <= TRADE_REFUSE_S and (tr is None or tr < t):
            self.trade_refused("the server ended the connection right after a trade subscription")

    def trade_refused(self, why):
        """One refusal of the trade subscriptions; at TRADE_REFUSALS trades are off for the run (said once): follow() takes nothing, sync()
        drops what is subscribed, and later sockets ask for the new coins and graduations only."""
        n = self.count("trefused")
        if n < TRADE_REFUSALS:
            return self.say("%s (%d of %d before trades are off)" % (why, n, TRADE_REFUSALS))
        with self.lock:
            first = self.toff is None
            if first:
                self.toff = why
        if first:
            self.say("trade subscriptions refused %d times (%s): trades are off for this run, the new coins and graduations go on" % (n, why))

    def sync(self, ws, force=False):
        """The trade subscriptions brought in line with follow() on this socket: one unsubscribeTokenTrade for the coins dropped and one
        subscribeTokenTrade for the new ones, at most every SUB_EVERY_S (force: right after connecting). Nothing is ever sent but these,
        and nothing at all once trades are silent (silence)."""
        now = time.time()
        if self.silence(now) or (not force and now - self.sub_at < SUB_EVERY_S):
            return
        with self.lock:
            want = set() if self.tshape is False or self.toff else set(self.want)
            drop, add = sorted(self.subbed - want), sorted(want - self.subbed)[:FOLLOW_MAX]
        if not drop and not add:
            return
        self.sub_at = now
        if drop:
            ws.send(0x1, json.dumps({"method": "unsubscribeTokenTrade", "keys": drop}).encode())
            with self.lock:
                self.subbed -= set(drop)
                self.n["unsubs"] += 1
        if add:
            ws.send(0x1, json.dumps({"method": "subscribeTokenTrade", "keys": add}).encode())
            with self.lock:
                self.subbed |= set(add)
                self.n["subs"] += 1
                self.tsub_t = time.time()
                self.tfirst = self.tfirst or self.tsub_t

    def silence(self, now):
        """Whether trades are silent for the run: no trade message at all (none passed or failed the shape check) while trade
        subscriptions were live for TRADE_SILENT_S in all (the earlier sockets' time and this one's since its first subscribeTokenTrade:
        none before the forced sync of a new socket has sent its subscriptions), and trades not refused (TRADE_REFUSALS; a single one
        does not hold it off). Said once when it starts: follow() takes nothing more and sync() sends nothing more, not even an
        unsubscribe (a server that sends no trades is not asked again; the subscriptions end with the socket)."""
        with self.lock:
            if self.tsilent:
                return True
            if self.tfirst is None or self.tshape is not None or self.toff:
                return False
            live = self.tlive + now - self.tfirst
            if live < TRADE_SILENT_S:
                return False
            ref = "%d refused" % self.n["trefused"] if self.n["trefused"] else "none refused"
            self.tsilent = "no trade in %d s of trade subscriptions (%d sent, %s)" % (live, self.n["subs"], ref)
            self.want = set()
        self.say("%s: PumpPortal sends coin trades only to paid clients; no more trade subscriptions this run, the curve watch reads "
                 "pump.fun's list only" % self.tsilent)
        return True

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
        if kind in KINDS + TRADE_KINDS:
            self.once("fields:" + kind, "first %s message: fields %s" % (kind, ", ".join(sorted(clean(k, 40) for k in list(j)[:NAMES_MAX]))))
        if kind in TRADE_KINDS:
            return self.trade(j, kind)
        if kind not in KINDS:
            if isinstance(j, dict) and "errors" in j:
                self.once("errors", "the feed sent an error: %s" % clean(j.get("errors")))
                with self.lock:
                    mine = not self.terr and self.tsub_t is not None and time.time() - self.tsub_t <= TRADE_REFUSE_S
                    self.terr = self.terr or mine
                if mine:                         # an error right after a trade subscription: counted once a socket
                    self.trade_refused("an error answered a trade subscription")
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
            ev.update((k, fnum(j.get(src))) for k, src in CREATE_NUMS)
        with self.lock:
            if kind == "create":
                self.n["creates"] += 1
                if mint not in self.creates:
                    self.creates[mint] = {"t": ev["t"], "creator": ev["creator"], "vtok": ev["vtok"], "mcs": ev["mcs"]}
                while self.creates and (len(self.creates) > CREATES_MAX or ev["t"] - next(iter(self.creates.values()))["t"] > KEEP_MS):
                    self.creates.popitem(last=False)
            else:
                self.n["migrations"] += 1
            if len(self.q) >= QUEUE_MAX:
                self.n["dropped"] += 1
            self.q.append(ev)

    def trade(self, j, kind):
        """One trade message -> the trades queue (take_trades), only for a coin followed. Its numbers are PumpPortal's documented names,
        unverified here: the first trade is shape-checked (a base58 mint, solAmount, and vTokensInBondingCurve or marketCapSol as finite
        numbers); when it fails, trades are ignored and the subscriptions dropped for the run, said once."""
        mint = j.get("mint")
        vals = {k: fnum(j.get(src)) for k, src in TRADE_NUMS}
        ok = isinstance(mint, str) and bool(B58.fullmatch(mint)) and vals["sol"] is not None and (vals["vtok"] is not None or vals["mcs"] is not None)
        with self.lock:
            first = self.tshape is None
            if first:
                self.tshape = ok
            lift = bool(ok and self.tshape and self.tsilent)
            if lift:
                self.tsilent = None          # a valid trade after all: the server sends them; follow() takes the coins again
        if lift:
            self.say("a trade came after all: trade subscriptions go on")
        if first and not ok:
            self.say("the first trade message has no base58 mint, SOL amount or curve state: trades are ignored this run (the curve watch reads "
                     "pump.fun's list only)")
        if not (ok and self.tshape):
            return self.count("tbad")
        who, pool = j.get("traderPublicKey"), j.get("pool")
        ev = dict(vals, mint=mint, t=int(self.clock()), side=kind, who=who if isinstance(who, str) and B58.fullmatch(who) else None,
                  pool=pool if isinstance(pool, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,16}", pool) else None)
        with self.lock:
            self.tsock = time.time()         # a trade on this socket: its trade subscriptions are taken
            if mint not in self.subbed and mint not in self.want:
                return None                  # an unsubscribed coin's late trade
            self.n["trades"] += 1
            if len(self.trades) >= TRADES_MAX:
                self.n["tdropped"] += 1
            self.trades.append(ev)
            self.t_last = time.time()


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
