#!/usr/bin/env python3
"""app.py: the iPhone app's live store and its push notifications. Fake money only: nothing is ever bought for real, and no
notification suggests a real trade.

The live store is a free Supabase project (one-time setup: supabase/setup.sql). With SUPABASE_URL and SUPABASE_SECRET_KEY set (two
GitHub Actions secrets) the scan writes two rows of table live while it runs (bot.py, class AppFeed, calls sink):
  status   small: t, live, updated, ver (the version of current), nver (the version of current whose early list or pick changed
           last), per agent its id, status, short result and last line, and the early New launches list's count and newest age;
           every 5 s while it changes, at least every 30 s
  current  the whole live record (the office record plus "young" and "pick" when present, each agent's last 12 lines); when it
           changed, at most every 30 s, at once when the early list or the pick changed, and at the end
The page polls status while it is visible (in a browser tab only on the New launches and Agent office tabs, one poll for all its tabs),
every 4 s while a scan is live and every 30 s otherwise, and fetches current only when nver (the version of current whose early list
or pick changed) changes (report.py, OFFICE_LIVE_JS). Each request to the store is cut off after CALL_TOTAL s in all; the writes go
one after another.

Push notifications go to the app installed from Safari (iOS 16.4 or newer). The VAPID key pair is made on first use and kept in the
store: the private key in app_secret (the secret key only), the public key in app_config (the page subscribes with it). The page saves
its subscription and its two settings (new coins, the pick) with the function save_push_sub. notify reads push_subs with the secret key
and sends one Declarative Web Push message ({"web_push": 8030, "notification": {title, body, navigate}}: iOS 18.4 and newer shows it
by itself, sw.js shows it on older systems) through pywebpush when it can be imported (else nothing is sent and the log says so once),
SEND_THREADS at a time, NOTIFY_BUDGET s at most for the pushes (counted once the subscriptions are read). A subscription the push
service calls gone (404 or 410) is deleted, and so is one whose keys are no keys (anyone with the publishable key can save such a
row): no request, no retry, no pause. A row a push service accepted a notification for is marked delivered (the table's size cap
keeps those first); a row whose own push host gives no answer at all is not tried again and is deleted after NET_FAILS such
notifications in a row; any other error keeps the row.

The secret key travels only in the apikey header of requests to SUPABASE_URL, and no redirect is followed (it would carry the header
elsewhere). No key is ever printed, written to a file or put in the page; every message this module prints passes through clean(),
which blanks both keys (a newly made VAPID private key from before it is sent).

Without SUPABASE_URL and SUPABASE_SECRET_KEY nothing here touches the network. The module imports only the standard library;
pywebpush (and cryptography, which it brings) are imported when a push or the VAPID keys need them, also from MEMEBOT_PUSH_LIB (a
site-packages folder, put right after the standard library: the scan workflow installs supabase/push-requirements.txt there, every
package pinned with its sha256).

Public: enabled(), sink(record), prepare(), notify(kind, title, body, url), notify_young(doc), notify_pick(rec), page_key_verdict(key),
site_url(). The page side lives here too: PAGE_CSS and PAGE_JS (the installed app: bottom tab bar, notifications) and SW_JS (sw.js);
bot.py site writes them into the website.

  python3 app.py check     what is set up (store reachable, VAPID key, subscriptions, pywebpush), without printing any key
  python3 app.py test      sends a test notification to every saved subscription
"""
import base64, hashlib, http.client, json, os, re, socket, sys, sysconfig, threading, time, urllib.error, urllib.parse, urllib.request

DEFAULT_SITE = "https://maxpandelakis-boop.github.io/Meme-Bot/"
TIMEOUT = 4               # s: one network step of a request to the live store (connect, send, each read; the scan never waits on it:
                          # AppFeed runs on its own thread)
CALL_TOTAL = 8            # s: the most one request to the live store takes in all (a store that answers a byte at a time is cut off)
PUSH_TIMEOUT = 10         # s: one network step of a request to a push service (pywebpush has no timeout of its own)
NOTIFY_BUDGET = 15        # s: one notification to every phone, retries included (the end of a cycle waits 20 s at most)
SEND_THREADS = 4          # pushes sent at the same time (a slow push service holds up one of them, not the others)
CURRENT_EVERY = 30        # s: the least gap between two writes of the row current (except a new early list and the last write)
CURRENT_LINES = 12        # lines per agent in the row current
CURRENT_MAX = 150_000     # bytes: a bigger current row goes without the agents' lines
MAX_SUBS = 30             # subscriptions served per notification (the table holds 25)
NET_FAILS = 3             # notifications in a row that could not reach a subscription's own push host (DNS, refused): then it is deleted
SHARED_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")   # every phone's push service: a network
                          # failure there is this runner's or the service's, never one subscription's, and deletes nothing
KINDS = {                 # kind: (TTL s, Urgency, the least gap s between two notifications of this kind in one process)
    "young": (1800, "normal", 300),
    "pick": (3600, "high", 300),
    "test": (600, "normal", 20),
}
PLAINTEXT_MAX = 3993      # bytes: Apple's 4 KB limit after aes128gcm


class StoreError(Exception):
    pass


_sink_lock = threading.Lock()     # the writes of the live rows, one after another (a write never overtakes an older one)
_vapid_lock = threading.Lock()    # making or reading the VAPID keys
_rate_lock = threading.Lock()     # the rate guard of the notifications
_state = {"t": None, "cur_sig": None, "cur_at": 0.0, "ver": None, "nver": None, "news_sig": None, "ending": False}
_sink_on = []                     # the cut-off switch of the sink's request on its way (end_sink)
_said = set()
_last_push = {}
_vapid = {}


def _env(name):
    return (os.environ.get(name) or "").strip()


def store():
    """(url, secret key) of the live store, or None when SUPABASE_URL or SUPABASE_SECRET_KEY is missing or the URL is not https
    (plain http only to this machine, for the tests)."""
    url, key = _env("SUPABASE_URL").rstrip("/"), _env("SUPABASE_SECRET_KEY")
    if not url or not key or re.search(r"\s", key):
        return None
    if not (re.fullmatch(r"https://[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d{1,5})?", url) or re.fullmatch(r"http://(127\.0\.0\.1|localhost):\d{1,5}", url)):
        return None
    return url, key


def enabled():
    """Whether the live store is set up (SUPABASE_URL and SUPABASE_SECRET_KEY)."""
    return store() is not None


def clean(s):
    """s without the secret key or the VAPID private key in it (every message of this module goes through it): the stored one, and a
    newly made one from before it is sent (a store's error message may repeat what it was sent)."""
    s = str(s)
    for k in (_env("SUPABASE_SECRET_KEY"), _vapid.get("raw"), _vapid.get("pending")):
        if k and len(k) >= 8:
            s = s.replace(k, "***")
    return re.sub(r"sb_secret_[A-Za-z0-9_-]+", "sb_secret_***", s)


def say(msg, once=None):
    """A line on stderr (only once per process for a given once key)."""
    if once:
        if once in _said:
            return
        _said.add(once)
    print(clean("app: " + msg), file=sys.stderr, flush=True)


def site_url():
    """The website's address, the scope every notification opens inside: MEMEBOT_SITE_URL, else the GitHub Pages address of
    GITHUB_REPOSITORY, else the Meme-Bot site."""
    u = _env("MEMEBOT_SITE_URL")
    if re.fullmatch(r"https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~-]+)*/", u):
        return u
    r = _env("GITHUB_REPOSITORY")
    if re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", r):
        owner, name = r.split("/")
        host = owner.lower() + ".github.io"
        return "https://%s/" % host if name.lower() == host else "https://%s/%s/" % (host, name)
    return DEFAULT_SITE


def origin(url):
    u = urllib.parse.urlsplit(url)
    return "%s://%s" % (u.scheme, u.netloc)


def in_scope(url):
    """url as an absolute address inside the website (a hash or a relative path is resolved against it); anything else, and any path
    with a dot segment (.. or ., also written %2e) or a backslash that could lead out of it: the website."""
    home = site_url()
    try:
        u = urllib.parse.urljoin(home, str(url or ""))
        path = urllib.parse.urlsplit(u).path
    except ValueError:
        return home
    if re.search(r"(^|/)(\.|%2e){1,2}(/|$)|\\|%5c", path, re.I):
        return home
    return u if u.startswith(home) and not re.search(r"[\s<>\"'\\]", u) else home


# ---------------------------------------------------------------------------------------------------------------- the store (PostgREST)

class _Cut:
    """The connections of one request, so a watchdog can cut them off; after cancel no new connection is made (a request held up in
    a DNS lookup never goes out late, after a newer write)."""

    def __init__(self):
        self.cancel, self.conns, self.done = False, [], threading.Event()    # done: the request ended, or it was cut off

    def shut(self):
        self.cancel = True
        self.done.set()
        for c in list(self.conns):
            s = getattr(c, "sock", None)
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def _opener(cut):
    """urllib's opener (proxies from the environment as usual) whose connections report to cut. It follows no redirect: a 3xx answer
    is a StoreError, so the apikey header never goes to an address other than SUPABASE_URL."""
    def watched(base):
        class C(base):
            def connect(self):
                cut.conns.append(self)
                if cut.cancel:
                    raise OSError("cancelled")
                base.connect(self)
                if cut.cancel:
                    self.close()
                    raise OSError("cancelled")
        return C
    plain, tls = watched(http.client.HTTPConnection), watched(http.client.HTTPSConnection)

    class H(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(plain, req)

    class HS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(tls, req, context=self._context)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None          # never followed (it would carry the secret key to another address): the 3xx is an HTTPError
    return urllib.request.build_opener(H, HS, NoRedirect)


def call(method, path, body=None, prefer=None, timeout=TIMEOUT, total=CALL_TOTAL, track=None):
    """One request to the live store's REST API with the secret key in the apikey header (nothing in Authorization: the new keys are
    not JWTs). The JSON answer (None when empty); a StoreError (with the HTTP status, never a key) otherwise. timeout bounds each
    network step, total the whole request: a store that never finishes its answer is cut off after total s. track: a list that holds
    the request's cut-off switch while it runs (end_sink cuts the sink's request short)."""
    st = store()
    if not st:
        raise StoreError("the live store is not set up")
    url, key = st
    h = {"apikey": key, "Accept": "application/json", "User-Agent": "meme-bot/1.0 Python-urllib"}   # not browser-like: Supabase refuses secret keys from browsers
    data = None
    if body is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(url + "/rest/v1/" + path, data=data, method=method, headers=h)
    cut, box = _Cut(), {}

    def go():
        try:
            with _opener(cut).open(req, timeout=timeout) as r:
                box["raw"] = r.read(4_000_000)
        except urllib.error.HTTPError as e:
            box["code"] = e.code
            try:
                box["body"] = e.read(2000)
            except Exception:
                box["body"] = b""
        except BaseException as e:
            box["err"] = e
        finally:
            cut.done.set()
    t = threading.Thread(target=go, daemon=True)
    if track is not None:
        track.append(cut)
    try:
        t.start()
        cut.done.wait(total)
    finally:
        if track is not None and cut in track:
            track.remove(cut)
    if t.is_alive():
        if cut.cancel:           # cut off by end_sink: the last record of the scan goes out instead
            raise StoreError("cut off by the end of the scan")
        cut.shut()
        t.join(1.0)
        raise StoreError("no complete answer within %d s" % total)
    if "code" in box:
        why = ""
        try:
            j = json.loads(box.get("body") or b"{}")
            why = "".join(" %s" % j.get(k) for k in ("code", "message") if j.get(k))
        except Exception:
            pass
        hint = {401: " (wrong key, or supabase/setup.sql not run)", 403: " (no grant: run supabase/setup.sql)", 404: " (table missing: run supabase/setup.sql)",
                540: " (the project is paused: resume it in the Supabase dashboard)"}.get(box["code"], "")
        if 300 <= box["code"] < 400:
            hint = " (a redirect, not followed: SUPABASE_URL must be the project's own https://<ref>.supabase.co address)"
        raise StoreError(clean("HTTP %d%s%s" % (box["code"], why[:200], hint)))
    if "err" in box:
        e = box["err"]
        if not isinstance(e, Exception):
            raise e
        raise StoreError(clean("%s %s" % (type(e).__name__, getattr(e, "reason", "") or e))[:200])
    raw = box.get("raw") or b""
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise StoreError("the answer is not JSON")


def put_row(row_id, doc, track=None):
    """Upsert one row of table live (ver and updated are set by the table's trigger)."""
    call("POST", "live?on_conflict=id", {"id": row_id, "doc": doc}, prefer="resolution=merge-duplicates,return=minimal", track=track)


def _sig(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def young_brief(y):
    """The early New launches list in a few numbers for the status row: how many coins, the youngest one's age in minutes, its state."""
    if not isinstance(y, dict):
        return None
    coins = [c for c in (y.get("coins") if isinstance(y.get("coins"), list) else []) if isinstance(c, dict)]
    ages = [_num(c.get("ageMin")) for c in coins if _num(c.get("ageMin")) is not None]
    return {"n": len(coins), "newest": min(ages) if ages else None, "state": y.get("state") if isinstance(y.get("state"), str) else None,
            "at": _num(y.get("at")), "t": _num(y.get("t"))}


def status_doc(rec, ver, nver=None):
    """The small row: what the office map and the app's tab bar need every few seconds. ver: the version of the row current; nver: the
    version of current whose early list or pick changed last (the page reads current only when nver changes: it takes only those two)."""
    agents = []
    for a in rec.get("agents") or []:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        lines = a.get("lines") if isinstance(a.get("lines"), list) else []
        agents.append({"id": str(a["id"])[:32], "status": a.get("status") if isinstance(a.get("status"), str) else None, "bg": a.get("bg") is True,
                       "start": _num(a.get("start")), "end": _num(a.get("end")), "out": str(a.get("out") or "")[:120],
                       "lines": [str(lines[-1])[:160]] if lines else []})
    p = rec.get("pick") if isinstance(rec.get("pick"), dict) else None
    return {"v": 1, "t": _num(rec.get("t")), "live": rec.get("live") if isinstance(rec.get("live"), bool) else None, "updated": _num(rec.get("updated")),
            "end": _num(rec.get("end")), "horizon": rec.get("horizon"), "mode": rec.get("mode"), "ver": ver, "nver": nver, "agents": agents,
            "young": young_brief(rec.get("young")), "pick": {"sym": str(p.get("sym") or "")[:24], "t": _num(p.get("t")), "score": _num(p.get("score"))} if p else None}


def current_doc(rec):
    """The whole record for the row current, each agent with its last CURRENT_LINES lines (none when it would grow past CURRENT_MAX)."""
    doc = dict(rec)
    doc["agents"] = [dict(a, lines=list(a.get("lines") or [])[-CURRENT_LINES:]) if isinstance(a, dict) else a for a in rec.get("agents") or []]
    if len(json.dumps(doc, separators=(",", ":"), default=str)) > CURRENT_MAX:
        doc["agents"] = [dict(a, lines=[]) if isinstance(a, dict) else a for a in doc["agents"]]
    return doc


def sink(record, now=None):
    """Write one live record (the office record plus "live", "updated" and any extras such as "young") to the live store: the row
    current first when it is due (changed, and CURRENT_EVERY s since the last one, or news: a new early list or a new pick, or the last
    record of a scan), then the row status, which names current's version. True when the status row was written. It never raises; the
    first failure is printed once. The writes go one after another (a write never overtakes an older one), each cut off after
    CALL_TOTAL s; the notifications and the VAPID keys never wait for them. Once end_sink was called only the scan's last record
    ("live": false) is written."""
    if not isinstance(record, dict) or not enabled():
        return False
    last = record.get("live") is False
    cut = lambda: _state["ending"] and not last and record.get("t") == _state["t"]
    if cut():                                   # the scan is ending (end_sink): only its last record still goes out
        return False
    with _sink_lock:
        now = time.time() if now is None else now
        try:
            if record.get("t") != _state["t"]:          # a new scan: its first record always writes current
                _state.update(t=record.get("t"), cur_sig=None, cur_at=0.0, news_sig=None, nver=None, ending=False)
            cur = current_doc(record)
            sig = _sig({k: v for k, v in cur.items() if k not in ("updated", "end")})
            nsig = _sig([record.get("young"), record.get("pick")])     # news: the app shows them (and a notification names them) at once
            if sig != _state["cur_sig"] and (_state["cur_sig"] is None or nsig != _state["news_sig"] or record.get("live") is False
                                              or now - _state["cur_at"] >= CURRENT_EVERY):
                ver = int(now * 1000)
                if _state["ver"] is not None and ver <= _state["ver"]:
                    ver = _state["ver"] + 1
                put_row("current", dict(cur, ver=ver), track=_sink_on)
                if nsig != _state["news_sig"] or _state["nver"] is None:
                    _state["nver"] = ver
                _state.update(cur_sig=sig, cur_at=now, ver=ver, news_sig=nsig)
        except StoreError as e:
            if not cut():
                say("live store: writing the row current failed, the scan goes on (%s)" % e, once="current")
        except Exception as e:
            say("live store: the row current was not written (%s)" % type(e).__name__, once="current-x")
        if cut():
            return False
        try:
            put_row("status", status_doc(record, _state["ver"], _state["nver"]), track=_sink_on)
            return True
        except StoreError as e:
            if cut():
                return False
            say("live store: writing the row status failed, the scan goes on (%s)" % e, once="status")
        except Exception as e:
            say("live store: the row status was not written (%s)" % type(e).__name__, once="status-x")
        return False


def end_sink():
    """The scan is ending: the sink's request on its way (a live record's) is cut off at once and no live record is written any more, so
    the last record ("live": false) goes out next without waiting for a slow store. A new scan's records write again."""
    _state["ending"] = True
    for c in list(_sink_on):
        c.shut()


# ---------------------------------------------------------------------------------------------------------------- push libraries, VAPID

def _push_path():
    """MEMEBOT_PUSH_LIB (the scan's pinned pywebpush and its dependencies) on sys.path right after the standard library: no standard
    module can be shadowed by it, and its pinned versions come before any older copy in the system's site-packages."""
    lib = _env("MEMEBOT_PUSH_LIB")
    if not lib or not os.path.isdir(lib) or lib in sys.path:
        return
    std = [os.path.realpath(p) for p in {sysconfig.get_paths().get("stdlib"), sysconfig.get_paths().get("platstdlib")} if p]

    def is_std(p):
        r = os.path.realpath(p or ".")
        return any(r == s or r.startswith(s + os.sep) for s in std) or (p or "").endswith(".zip")
    at = max([i for i, p in enumerate(sys.path) if is_std(p)] or [len(sys.path) - 1]) + 1
    sys.path.insert(at, lib)


def _crypto():
    """cryptography's pieces for the VAPID keys and their signatures, or None (pywebpush brings cryptography)."""
    _push_path()
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives import hashes, serialization
        return ec, decode_dss_signature, hashes, serialization
    except Exception:
        return None


def _webpush():
    """(webpush, WebPushException) from pywebpush, or None."""
    _push_path()
    try:
        from pywebpush import webpush, WebPushException
        return webpush, WebPushException
    except Exception:
        return None


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64d(s):
    s = str(s).strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def vapid():
    """The VAPID key pair: {"key": private key object, "pub": public key (base64url, 87 chars)}. Made on first use and kept in the
    store (private key in app_secret, public key in app_config); a key pair already there is reused, so subscriptions stay valid. None
    when cryptography is missing; StoreError when the store fails."""
    if _vapid.get("key"):
        return _vapid
    with _vapid_lock:
        if _vapid.get("key"):
            return _vapid
        C = _crypto()
        if not C:
            return None
        ec, _, _, ser = C
        q = "app_secret?select=value&key=eq.vapid_private_key"
        rows = call("GET", q)
        raw = rows[0].get("value") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        made = False
        if not raw:
            k = ec.generate_private_key(ec.SECP256R1())
            _vapid["pending"] = b64u(k.private_numbers().private_value.to_bytes(32, "big"))    # clean() hides it before it is ever sent
            call("POST", "app_secret?on_conflict=key", {"key": "vapid_private_key", "value": _vapid["pending"]},
                 prefer="resolution=ignore-duplicates,return=minimal")
            rows = call("GET", q)                    # the stored one wins (another run may have made one at the same moment)
            raw = rows[0].get("value") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
            made = True
        try:
            n = int.from_bytes(b64d(raw), "big")
            if len(b64d(raw)) != 32 or not n:
                raise ValueError
            key = ec.derive_private_key(n, ec.SECP256R1())
        except Exception:
            raise StoreError("app_secret holds no usable vapid_private_key (delete that row: the next scan makes a new pair, and the phone turns notifications on again)")
        pub = b64u(key.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint))
        _vapid.update(key=key, pub=pub, raw=raw, auth={})
        cfg = call("GET", "app_config?select=value&key=eq.vapid_public_key")
        if not (isinstance(cfg, list) and cfg and isinstance(cfg[0], dict) and cfg[0].get("value") == pub):
            call("POST", "app_config?on_conflict=key", {"key": "vapid_public_key", "value": pub}, prefer="resolution=merge-duplicates,return=minimal")
        if made:
            say("push: made the VAPID key pair (the private key stays in app_secret, the public key is in app_config for the page)")
        return _vapid


def prepare():
    """Make sure the VAPID public key is in the store, so the app can subscribe before the first notification (the scan calls this
    once at its start). The public key, or None."""
    if not enabled():
        return None
    try:
        v = vapid()
        if v is None:
            say("push: off, pywebpush (and cryptography) not installed here: no notifications this run", once="nopush")
            return None
        return v["pub"]
    except StoreError as e:
        say("push: the VAPID keys are not ready (%s)" % e, once="vapid")
    except Exception as e:
        say("push: the VAPID keys are not ready (%s)" % type(e).__name__, once="vapid-x")
    return None


def vapid_auth(endpoint):
    """The Authorization header for one push service: "vapid t=<ES256 JWT>,k=<public key>" (RFC 8292), aud the endpoint's origin, sub
    the website's origin (Apple wants a URL or mailto; py-vapid's check takes a bare origin only), exp 12 h ahead; one per push service
    per run (Apple: no new JWT more than once an hour)."""
    v = _vapid
    aud = origin(endpoint)
    if aud not in v["auth"]:
        ec, decode_dss_signature, hashes, _ = _crypto()
        head = b64u(b'{"typ":"JWT","alg":"ES256"}')
        claims = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": origin(site_url())}, sort_keys=True, separators=(",", ":")).encode())
        r, s = decode_dss_signature(v["key"].sign((head + "." + claims).encode("ascii"), ec.ECDSA(hashes.SHA256())))
        v["auth"][aud] = "vapid t=%s.%s.%s,k=%s" % (head, claims, b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big")), v["pub"])
    return v["auth"][aud]


# ---------------------------------------------------------------------------------------------------------------- notifications

def message(title, body, url, tag=None):
    """The push payload: Declarative Web Push JSON (iOS 18.4+ shows it without running the service worker; sw.js shows the same
    message on older systems and other browsers). title must not be empty and navigate must be an absolute URL, or iOS drops it."""
    t = " ".join(str(title or "").split())[:120] or "Meme-Bot"
    b = " ".join(str(body or "").split())[:300]
    n = {"title": t, "body": b, "navigate": in_scope(url), "lang": "en"}
    if tag:
        n["tag"] = str(tag)[:32]
    while True:
        data = json.dumps({"web_push": 8030, "notification": n}, separators=(",", ":"), ensure_ascii=False)
        if len(data.encode("utf-8")) <= PLAINTEXT_MAX or not n["body"]:
            return data
        n["body"] = n["body"][:-20]


def _send(wp, sub, data, ttl, urgency, topic, until=None):
    """One push: "ok", "gone" (404/410: delete the row), "retry" (429/5xx: one more try after a pause), "net" (no answer at all: DNS,
    refused, reset, timeout, TLS; no retry and no pause, counted against the row by notify), "config" (400/403/413: our keys or headers
    are wrong; the row stays) or "error" (anything else, e.g. pywebpush could not use the subscription: the row stays and the log says it
    once; only keys_ok decides that a row is unusable); with the HTTP status or the error's name."""
    webpush, WPE = wp
    headers = {"Authorization": vapid_auth(sub["endpoint"]), "Urgency": urgency, "Topic": topic}
    left = PUSH_TIMEOUT if until is None else max(1.0, min(PUSH_TIMEOUT, until - time.time()))
    try:
        webpush(sub, data, headers=headers, ttl=ttl, timeout=left)
        return "ok", 201
    except WPE as e:
        code = getattr(e, "status_code", None)
        if code is None:
            code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):
            return "gone", code
        if code in (429, 500, 502, 503, 504):
            return "retry", code
        return ("config" if code in (400, 403, 413) else "error"), code
    except OSError as e:               # the network (requests' errors are OSErrors too): no answer, no retry
        return "net", type(e).__name__
    except Exception as e:             # ValueError, TypeError, the encryption's errors: kept (keys_ok passed), said once
        return "error", type(e).__name__


def _sub_ok(s):
    return (isinstance(s, dict) and isinstance(s.get("endpoint"), str) and s["endpoint"].startswith(("https://", "http://127.0.0.1:"))
            and isinstance(s.get("keys"), dict) and isinstance(s["keys"].get("p256dh"), str) and isinstance(s["keys"].get("auth"), str))


def keys_ok(s):
    """Whether a subscription's keys can be used at all: p256dh a point on the curve P-256 (65 bytes, base64url), auth 16 bytes. Anyone
    with the publishable key can save strings that only look like keys; those rows are deleted without a request to a push service."""
    try:
        p, a = b64d(s["keys"]["p256dh"]), b64d(s["keys"]["auth"])
        if len(p) != 65 or p[0] != 4 or len(a) != 16:
            return False
        C = _crypto()
        if C:
            C[0].EllipticCurvePublicKey.from_encoded_point(C[0].SECP256R1(), p)
        return True
    except Exception:
        return False


def _drop(endpoint):
    try:
        call("DELETE", "push_subs?endpoint=eq." + urllib.parse.quote(endpoint, safe=""), prefer="return=minimal")
    except StoreError as e:
        say("push: a subscription that cannot be used stays in the store (%s)" % e, once="del")


def _in(endpoints):
    """A PostgREST filter value for these endpoints: in.("a","b") with each one quoted (an endpoint has : / . in it), URL-encoded."""
    q = ",".join('"%s"' % e.replace("\\", "\\\\").replace('"', '\\"') for e in endpoints)
    return urllib.parse.quote("in.(%s)" % q, safe="")


def own_host(endpoint):
    """Whether a network failure can be this subscription's own fault: its push host is not one of SHARED_HOSTS (a made-up host, e.g. a
    random subdomain of notify.windows.com that does not exist)."""
    return (urllib.parse.urlsplit(endpoint).hostname or "") not in SHARED_HOSTS


def _settle(ok_eps, net_rows, heard, until):
    """After a notification, with the secret key: the rows a push reached are marked delivered (now) with no failures (the size cap keeps
    delivered rows first, so strangers' rows never push the phone out once it got a notification); a row whose own push host could not
    be reached counts one more failure when the same notification reached some push service (the runner's network works), and is
    deleted at NET_FAILS in a row. Nothing here waits past until + 4 s; a failure is said once and changes nothing."""
    try:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for i in range(0, len(ok_eps), 10):
            if time.time() > until + 4:
                return
            call("PATCH", "push_subs?endpoint=" + _in(ok_eps[i:i + 10]), {"delivered": now, "fails": 0}, prefer="return=minimal")
        if not heard:
            return
        by = {}
        for row in net_rows:
            if own_host(row["endpoint"]):
                n = (row.get("fails") if isinstance(row.get("fails"), int) else 0) + 1
                by.setdefault(n, []).append(row["endpoint"])
        for n, eps in sorted(by.items()):
            if time.time() > until + 4:
                return
            if n >= NET_FAILS:
                call("DELETE", "push_subs?endpoint=" + _in(eps), prefer="return=minimal")
                say("push: %d subscription%s whose push host could not be reached %d times in a row deleted" % (len(eps), "" if len(eps) == 1 else "s", NET_FAILS))
            else:
                call("PATCH", "push_subs?endpoint=" + _in(eps), {"fails": n}, prefer="return=minimal")
    except StoreError as e:
        say("push: the delivered marks were not saved (%s); run supabase/setup.sql again if it names a column" % e, once="settle")
    except Exception as e:
        say("push: the delivered marks were not saved (%s)" % type(e).__name__, once="settle-x")


def notify(kind, title, body, url=None):
    """One notification of kind ("young": new coins listed, "pick": the pick is made, "test") to every saved subscription whose
    settings want it (prefs[kind] not false). The pushes go out SEND_THREADS at a time and take NOTIFY_BUDGET s at most, counted from
    when the keys and the subscriptions are read (a push still on its way then counts as failed, one not begun says so). A row the push service calls gone (404, 410) or whose keys are no keys
    (keys_ok) is deleted, without a retry; a 429 or 5xx is tried once more after a pause; a push that got no answer at all (DNS, refused)
    is not tried again and counts against its row (_settle: deleted after NET_FAILS in a row at its own host); any other error keeps the
    row and is said once. Rows a push reached are marked delivered. At least the kind's gap between two notifications of one kind (rate
    guard). A summary dict; it never raises."""
    out = {"kind": kind, "sent": 0, "gone": 0, "bad": 0, "failed": 0, "skipped": None}
    if kind not in KINDS:
        out["skipped"] = "unknown kind"
        return out
    if not enabled():
        out["skipped"] = "no live store"
        return out
    ttl, urgency, gap = KINDS[kind]
    with _rate_lock:
        now = time.time()
        if now - _last_push.get(kind, -1e9) < gap:
            out["skipped"] = "rate guard"
            say("push: %s skipped, the last one went out %.0f s ago" % (kind, now - _last_push[kind]))
            return out
        _last_push[kind] = now
    wp = _webpush()
    if wp is None:
        say("push: off, pywebpush is not installed here: no notifications this run", once="nopush")
        out["skipped"] = "no pywebpush"
        return out
    try:
        if vapid() is None:
            raise StoreError("cryptography is missing")
        try:                 # the phones a push has reached first (setup.sql's delivered), then the ones seen most recently
            rows = call("GET", "push_subs?select=endpoint,sub,prefs,fails&order=delivered.desc.nullslast,seen.desc&limit=%d" % MAX_SUBS)
            marks = True
        except StoreError as e:
            if "HTTP 400" not in str(e):
                raise
            say("push: push_subs has no delivered column yet: run supabase/setup.sql again (notifications go out meanwhile)", once="nodelivered")
            rows, marks = call("GET", "push_subs?select=endpoint,sub,prefs&order=seen.desc&limit=%d" % MAX_SUBS), False
    except StoreError as e:
        say("push: %s not sent (%s)" % (kind, e))
        out["skipped"] = "store"
        return out
    until = time.time() + NOTIFY_BUDGET      # the pushes' own time: it starts once the keys and the subscriptions are read (each read is cut off after CALL_TOTAL s)
    data = message(title, body, url, tag=kind)
    targets = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _sub_ok(row.get("sub")):
            continue
        prefs = row.get("prefs") if isinstance(row.get("prefs"), dict) else {}
        if kind != "test" and prefs.get(kind) is False:
            continue
        targets.append(row)
    results, nxt, lk, begun = [None] * len(targets), [0], threading.Lock(), [False] * len(targets)

    def worker():
        while True:
            with lk:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(targets) or time.time() >= until:
                return
            begun[i] = True
            row = targets[i]
            if not keys_ok(row["sub"]):
                res, code = "bad", "keys"
            else:
                res, code = _send(wp, row["sub"], data, ttl, urgency, kind, until)
                if res == "retry" and time.time() + 3 < until:
                    time.sleep(2)
                    res, code = _send(wp, row["sub"], data, ttl, urgency, kind, until)
            results[i] = (res, code)
            if res in ("gone", "bad"):
                _drop(row["endpoint"])
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(SEND_THREADS, len(targets)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, until - time.time()))
    for i, r in enumerate(list(results)):
        if r is None:
            out["failed"] += 1
            if begun[i]:
                say("push: a %s notification got no answer within %d s, the scan goes on" % (kind, NOTIFY_BUDGET), once="late-%s" % kind)
            else:
                say("push: a %s notification was not tried: the %d s for this notification were used up by slower pushes" % (kind, NOTIFY_BUDGET), once="untried-%s" % kind)
            continue
        res, code = r
        if res == "ok":
            out["sent"] += 1
        elif res in ("gone", "bad"):
            out[res] += 1
        else:
            out["failed"] += 1
            say("push: a %s notification failed (%s %s)%s" % (kind, res, code, ": check the VAPID keys" if res == "config" else
                                                            ": the subscription stays" if res == "error" else ""), once="fail-%s-%s-%s" % (kind, res, code))
    if marks:
        _settle([targets[i]["endpoint"] for i, r in enumerate(results) if r and r[0] == "ok"], [targets[i] for i, r in enumerate(results) if r and r[0] == "net"],
                any(r and isinstance(r[1], int) for r in results), until)
    say("push: %s sent to %d of %d subscription%s%s%s%s" % (kind, out["sent"], len(targets), "" if len(targets) == 1 else "s",
                                                           ", %d gone and deleted" % out["gone"] if out["gone"] else "",
                                                           ", %d unusable and deleted" % out["bad"] if out["bad"] else "", ", %d failed" % out["failed"] if out["failed"] else ""))
    return out


def _sym(v):
    s = re.sub(r"[\x00-\x1f\x7f]", "", " ".join(str(v or "").split()))
    return s[:16] or "?"


def notify_young(doc):
    """The "new coins" notification for the early New launches list (the doc the live record carries as "young"): how many coins it lists,
    how old the newest one was when it was found, the first three symbols, and that it is fake money; it opens the New coins tab.
    Nothing when the list is empty."""
    if not isinstance(doc, dict):
        return {"skipped": "no list"}
    coins = [c for c in (doc.get("coins") if isinstance(doc.get("coins"), list) else []) if isinstance(c, dict)]
    if not coins:
        return {"skipped": "no coins"}
    n = len(coins)
    ages = [_num(c.get("ageMin")) for c in coins if _num(c.get("ageMin")) is not None and _num(c.get("ageMin")) >= 0]
    syms = ", ".join(_sym(c.get("sym")) for c in coins[:3]) + (" and %d more" % (n - 3) if n > 3 else "")
    body = "%sOn the list: %s, %sunder an hour old and not scored yet. Fake money only, nothing is bought for real." % (
        ("The newest is %d min old. " % int(min(ages))) if ages else "", syms, "all " if n > 1 else "")
    return notify("young", "%d new coin%s listed" % (n, "" if n == 1 else "s"), body, "#tab-young")


TIER_WORDS = {"weak": "weak pick, the best available", "fallback": "fallback pick, momentum rules relaxed", "risky": "risky, nothing clean this scan"}


def notify_pick(rec):
    """The "pick" notification for this scan's recommendation (db/memebot/recommend.json): the top coin, its score and how sure the
    pick is; it opens the Pick tab. A watch-only coin says it is not a pick. Nothing when the scan named no coin."""
    picks = [p for p in (rec.get("picks") if isinstance(rec, dict) and isinstance(rec.get("picks"), list) else []) if isinstance(p, dict)]
    if not picks:
        return {"skipped": "no pick"}
    p = picks[0]
    sym, name, score = _sym(p.get("sym")), " ".join(str(p.get("name") or "").split())[:40], _num(p.get("score"))
    if p.get("tier") == "watch":
        title = "Watch only: %s" % sym
        lead = "Not a pick: the trained odds say a loss"
    else:
        title = "New pick: %s" % sym
        lead = ", ".join(x for x in [name, ("score %.0f" % score) if score is not None else "", TIER_WORDS.get(p.get("tier"), "")] if x)
    return notify("pick", title, "%s. Paper trading only, nothing is bought for real." % (lead or sym), "#tab-pick")


# ---------------------------------------------------------------------------------------------------------------- the page's key

PAGE_KEY_MAX = 80        # characters: a publishable key has about 46, a publishable key with a secret key or a JWT stuck to it is longer
JWT_HEADS = ("eyJhbGci", "eyJ0eXAi", "eyJraWQi")    # {"alg", {"typ", {"kid": how a JWT starts


def page_key_verdict(key, secret=None):
    """What SUPABASE_PUBLISHABLE_KEY is, for the website: ("ok", "") for a publishable key (sb_publishable_..., at most PAGE_KEY_MAX
    characters), the only kind that goes into the page; else ("refused", why) without the key in the words. A value with a secret key
    (sb_secret_, or SUPABASE_SECRET_KEY's value: secret, else the environment's) or a JWT anywhere in it is refused, also when it starts
    like a publishable key (both keys pasted into one GitHub secret)."""
    k = str(key or "").strip()
    secret = _env("SUPABASE_SECRET_KEY") if secret is None else str(secret or "").strip()
    same = len(secret) >= 8 and secret in k
    jwt = k.startswith("eyJ") or any(h in k for h in JWT_HEADS)
    if not same and not jwt and "sb_secret_" not in k.lower() and re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]{8,%d}" % (PAGE_KEY_MAX - 15), k):
        return "ok", ""
    if "sb_secret_" in k.lower():
        return "refused", ("it %s a SECRET key (sb_secret_...): it must never be in a page. Put only the publishable key (sb_publishable_...) there, and make a new "
                           "secret key in Supabase if this one was shown anywhere") % ("is" if k.startswith("sb_secret_") else "holds")
    if same:
        return "refused", "it holds the value of SUPABASE_SECRET_KEY: that must never be in a page. Put only the publishable key (sb_publishable_...) there"
    if jwt and not k.startswith("eyJ"):
        return "refused", "it holds a JWT besides the key: put only the publishable key (sb_publishable_...) there"
    if k.startswith("sb_publishable_"):
        return "refused", "it is longer than a publishable key or has other characters in it: put only the publishable key (sb_publishable_...) there, nothing else"
    if k.startswith("eyJ"):
        role = "?"
        try:
            role = str(json.loads(b64d(k.split(".")[1])).get("role") or "?")
        except Exception:
            pass
        if role == "anon":
            return "refused", "it is a legacy anon key (a JWT): copy the publishable key (sb_publishable_...) from Project Settings > API Keys instead"
        return "refused", "it is a JWT with the role %s: never put in the page. Copy the publishable key (sb_publishable_...) instead" % re.sub(r"[^A-Za-z0-9_-]", "", role)[:20]
    if not k:
        return "refused", "it is empty"
    return "refused", "it is not a publishable key (those start with sb_publishable_)"


# ---------------------------------------------------------------------------------------------------------------- command line

def check():
    st = store()
    print("live store: %s" % ("set up, %s" % urllib.parse.urlsplit(st[0]).hostname if st else "off (SUPABASE_URL and SUPABASE_SECRET_KEY are needed)"))
    if not st:
        return 1
    print("secret key: %s" % ("a secret key (sb_secret_...)" if st[1].startswith("sb_secret_") else "a publishable key: writes will be refused" if st[1].startswith("sb_publishable_") else "set (not an sb_secret_ key)"))
    try:
        rows = call("GET", "live?select=id,ver")
        print("table live: rows %s" % ", ".join("%s (ver %s)" % (r.get("id"), r.get("ver")) for r in rows or []))
    except StoreError as e:
        print("table live: %s" % e)
        return 1
    print("pywebpush: %s" % ("importable" if _webpush() else "not installed (no notifications)"))
    try:
        v = vapid()
        print("VAPID public key in app_config: %s" % ("yes, %s..." % v["pub"][:12] if v else "not made yet (cryptography missing)"))
        rows = call("GET", "push_subs?select=prefs,seen")
        print("subscriptions: %d%s" % (len(rows or []), "".join("\n  seen %s, settings %s" % (r.get("seen"), json.dumps(r.get("prefs"))) for r in rows or [])))
    except StoreError as e:
        print("push: %s" % e)
        return 1
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        sys.exit(check())
    if cmd == "test":
        r = notify("test", "Meme-Bot test", "Notifications work. Paper trading only, nothing is bought for real.", "#tab-pick")
        print(json.dumps(r))
        sys.exit(0 if r.get("sent") else 1)
    raise SystemExit("usage: python3 app.py check | test")


# ---------------------------------------------------------------------------------------------------------------- the page side

PAGE_CSS = r"""
/* The installed app (html.app, set by PAGE_JS when the page runs from the Home Screen): a bottom tab bar instead of the top one, the
   parts of one tab at a time, the bell and the notifications card. Nothing here applies in a browser tab. */
html.app .tabbar { display:none }
html.app body { padding-bottom:calc(66px + max(10px, env(safe-area-inset-bottom))) }
html.app .wrap { padding-top:max(16px, env(safe-area-inset-top)); padding-left:max(16px, env(safe-area-inset-left)); padding-right:max(16px, env(safe-area-inset-right)) }
html.app .app-off, html.app[data-apptab="account"] .tabs, html.app [data-live-link] { display:none !important }   /* the website's address: the app is it */
.appbar { position:fixed; left:0; right:0; bottom:0; z-index:30; display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
  padding:4px max(6px, env(safe-area-inset-right)) max(10px, env(safe-area-inset-bottom)) max(6px, env(safe-area-inset-left));
  background:color-mix(in srgb,var(--surface) 94%,transparent); -webkit-backdrop-filter:saturate(1.6) blur(14px); backdrop-filter:saturate(1.6) blur(14px);
  border-top:1px solid var(--line) }
.appbar button { appearance:none; -webkit-appearance:none; border:0; background:none; margin:0; font:inherit; color:var(--muted); display:grid; justify-items:center;
  align-content:center; gap:3px; min-height:52px; padding:6px 2px 2px; font-size:11px; font-weight:500; position:relative; cursor:pointer; -webkit-tap-highlight-color:transparent }
.appbar svg { width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round }
.appbar button[aria-selected="true"] { color:var(--accent) }
.appbar button[aria-selected="true"] svg { stroke-width:2.2; fill:color-mix(in srgb,var(--accent) 16%,transparent) }
.appbar button:focus-visible { outline:2px solid var(--accent); outline-offset:-4px; border-radius:10px }
.appbar .ab-dot { position:absolute; top:7px; left:calc(50% + 8px); width:9px; height:9px; border-radius:50%; background:var(--bad-mark); box-shadow:0 0 0 2px var(--surface) }
.appbar .ab-cnt { position:absolute; top:3px; left:calc(50% + 6px); min-width:18px; height:18px; padding:0 5px; border-radius:9px; background:var(--accent); color:#fff;
  font-size:11px; line-height:18px; font-weight:600; box-shadow:0 0 0 2px var(--surface); font-variant-numeric:tabular-nums }
html.app header { position:relative; padding-right:56px }
.appbell { position:absolute; top:-2px; right:0; width:44px; height:44px; border-radius:22px; border:1px solid var(--line); background:var(--surface); color:var(--fg2);
  display:grid; place-items:center; padding:0; cursor:pointer; -webkit-tap-highlight-color:transparent }
.appbell svg { width:22px; height:22px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round }
.appbell[data-on="1"] { color:var(--accent); border-color:color-mix(in srgb,var(--accent) 45%,var(--line)) }
.appbell[data-on="1"] svg { fill:color-mix(in srgb,var(--accent) 22%,transparent) }
.appbell i { position:absolute; top:8px; right:8px; width:9px; height:9px; border-radius:50%; background:var(--good-mark); box-shadow:0 0 0 2px var(--surface) }
.appbell:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
.appnotif .card { gap:14px } .appnotif [hidden] { display:none !important }
.nf-top { display:flex; gap:10px; align-items:center; justify-content:space-between; flex-wrap:wrap }
.nf-top strong { font-size:16px; font-weight:600 }
.nf-note { margin:0; color:var(--fg2); font-size:var(--fs-s); text-wrap:pretty }
.nf-btn { appearance:none; -webkit-appearance:none; border:0; border-radius:12px; min-height:48px; padding:0 18px; font:inherit; font-weight:600; font-size:16px;
  background:var(--accent); color:#fff; cursor:pointer; width:100% }
.nf-btn.quiet { background:var(--chip); color:var(--fg) }
.nf-btn[disabled] { opacity:.6; cursor:default }
.nf-btn:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
.nf-prefs { display:grid; border:1px solid var(--line); border-radius:10px; overflow:hidden }
.nf-row { display:flex; gap:12px; align-items:center; justify-content:space-between; padding:10px 14px; min-height:58px; cursor:pointer }
.nf-row + .nf-row { border-top:1px solid var(--line2) }
.nf-row span { display:grid; gap:2px } .nf-row small { color:var(--muted); font-size:var(--fs-xs) }
.nf-row input { appearance:none; -webkit-appearance:none; flex:none; width:51px; height:31px; border-radius:16px; background:var(--line); position:relative; margin:0; cursor:pointer; transition:background .2s }
.nf-row input::before { content:""; position:absolute; top:2px; left:2px; width:27px; height:27px; border-radius:50%; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.3); transition:transform .2s }
.nf-row input:checked { background:var(--good-mark) }
.nf-row input:checked::before { transform:translateX(20px) }
.nf-row input:disabled { opacity:.5; cursor:default }
.nf-prefs.dim .nf-row { opacity:.55 }   /* not on yet: the switches are a choice for later, not notifications that arrive */
.nf-row input:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
.nf-small { margin:0; color:var(--muted); font-size:var(--fs-xs); text-wrap:pretty }
.applive { margin:0; padding:12px 14px; border-radius:8px; font-size:var(--fs-s); color:var(--fg);
  background:color-mix(in srgb,var(--accent) 9%,var(--surface)); border:1px solid color-mix(in srgb,var(--accent) 30%,var(--line)) }
.appoff { padding:12px 14px; border-radius:8px; font-size:var(--fs-s); color:var(--fg);
  background:color-mix(in srgb,var(--warn-mark) 16%,var(--surface)); border:1px solid color-mix(in srgb,var(--warn-mark) 45%,var(--line)) }
@media (prefers-reduced-motion: reduce) { .nf-row input, .nf-row input::before { transition:none } }
"""

PAGE_JS = r"""
(function(){
// The installed app (Home Screen, from Safari): a bottom tab bar (Pick, New coins, Office, Account) instead of the top one, a bell and a
// notifications card on the Account tab (permission asked from the tap, the subscription saved in the live store through save_push_sub
// with its two settings), deep links (#tab-young ...) from notifications. In a browser tab it does nothing. window.MemebotApp holds its
// decisions for the tests.
var A=window.MemebotApp={TABS:['pick','young','office','account'],
  // an installed web app: Safari's navigator.standalone, or the display mode of an installed app (iOS reports "display": "standalone"
  // as fullscreen, WebKit bug 264218)
  installed:function(nav,mm){try{if(nav&&nav.standalone===true)return true;
    return !!(mm&&mm('(display-mode: standalone), (display-mode: fullscreen), (display-mode: minimal-ui)').matches);}catch(e){return false;}},
  // what the notifications control says: unsupported, nostore (no live store in the page), denied, on, error, nokey (no VAPID key yet), off.
  // on: a subscription that is saved, or one that exists with the permission granted while only the quiet save at the start failed (the
  // store keeps the one saved before); error: a tap that did not turn them on
  pushState:function(o){if(!o||!o.sw||!o.push||!o.notif)return 'unsupported';if(!o.store)return 'nostore';if(o.perm==='denied')return 'denied';
    if(o.sub&&(o.saved||o.perm==='granted'&&!o.error))return 'on';if(o.error)return 'error';if(!o.key)return 'nokey';return 'off';},
  // the early list's count for the New coins tab: its coins (live.json and the merged snapshot) or the status row's brief
  count:function(y){if(!y||typeof y!=='object')return null;if(Array.isArray(y.coins))return y.coins.filter(function(c){return c&&typeof c==='object';}).length;
    return typeof y.n==='number'&&y.n>=0?Math.floor(y.n):null;},
  // the early box shows a scan's early list (report.py's live script, MemebotLive.early: listed, partial, paused, limited, done, stopped)
  listed:function(early){return ['listed','partial','paused','limited','done','stopped'].indexOf(early)>=0;},
  // the New coins tab's badge follows the early box: while it shows a scan's early list the badge is that list's count; else null and no
  // badge at all (a badge reads as new coins: the scored list's count is not one)
  badge:function(early,y){return A.listed(early)?A.count(y):null;},
  // the pick for the "New pick" note: the snapshot's (status, so it is there as soon as the notification) or current's, of a scan newer
  // than this page, with a symbol
  pick:function(st,cur,pageT){var c=[st&&st.pick,cur&&cur.pick];for(var i=0;i<c.length;i++){var p=c[i];
    if(p&&typeof p==='object'&&p.sym&&(+p.t||0)>(+pageT||0))return p;}return null;},
  tab:function(h){var m=/^#?tab-(pick|young|office|account)$/.exec(String(h||''));return m?m[1]:null;},
  store:function(u,k){u=String(u||'').replace(/\/+$/,'');k=String(k||'');
    return /^https:\/\/[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?$/.test(u)&&/^sb_publishable_[A-Za-z0-9_-]+$/.test(k)?{url:u,key:k}:null;}};
if(!A.installed(window.navigator,window.matchMedia?function(q){return window.matchMedia(q);}:null))return;
var root=document.documentElement,doc=document;root.classList.add('app');
var all=function(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));};
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){}return null;}
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);sessionStorage.setItem(k,v);}catch(e){}return null;}
function el(tag,cls,text){var e=doc.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
function svg(d){return '<svg viewBox="0 0 24 24" aria-hidden="true">'+d+'</svg>';}
var ICON={pick:svg('<path d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.6L12 16.5l-5.1 2.7 1-5.6-4.1-4 5.7-.8z"/>'),
  young:svg('<circle cx="12" cy="12" r="8.4"/><path d="M12 8.2v7.6M8.2 12h7.6"/>'),
  office:svg('<circle cx="9" cy="8.2" r="3.1"/><path d="M3.6 19.2c.6-3.2 2.8-5 5.4-5s4.8 1.8 5.4 5"/><circle cx="16.9" cy="9.2" r="2.4"/><path d="M15.6 14.3c2.3.2 4 1.8 4.6 4.9"/>'),
  account:svg('<path d="M4.2 8.2V7.4A2.4 2.4 0 0 1 6.6 5h10.6v3.2"/><rect x="4.2" y="8.2" width="15.6" height="10.8" rx="2.4"/><circle cx="15.9" cy="13.6" r="1.2"/>'),
  bell:svg('<path d="M6.2 16.4V11a5.8 5.8 0 0 1 11.6 0v5.4l1.6 2.1H4.6z"/><path d="M10 20.6a2.1 2.1 0 0 0 4 0"/>')};
var NAMES={pick:'Pick',young:'New coins',office:'Office',account:'Account'},btns={},cur='pick',store=A.store(root.getAttribute('data-sb-url'),root.getAttribute('data-sb-key'));
var box=doc.querySelector('[data-live-src]'),pageT=box?+box.getAttribute('data-run-t')||0:0,pos={},lastEarly=null,toEarly=0,jumped=false;
// a tab: scroll 'top' (a deep link, a tap on the tab already shown), 'keep' (back where this tab was left, as iOS apps do) or nothing
function select(t,scroll){
  if(A.TABS.indexOf(t)<0)t='pick';
  if(t!==cur)pos[cur]=window.scrollY||0;
  cur=t;
  var r=doc.getElementById('tab-'+t);
  if(r&&!r.checked){r.checked=true;try{r.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){}}
  root.setAttribute('data-apptab',t);
  all('[data-app]').forEach(function(e){e.classList.toggle('app-off',(' '+e.getAttribute('data-app')+' ').indexOf(' '+t+' ')<0);});
  Object.keys(btns).forEach(function(k){btns[k].setAttribute('aria-selected',k===t?'true':'false');});
  ss('memebot-apptab',t);
  if(scroll==='top')window.scrollTo(0,0);else if(scroll==='keep')window.scrollTo(0,pos[t]||0);
  toEarly=scroll==='top'&&t==='young'?Date.now():0;jumped=false;if(toEarly)setTimeout(early,0);
  if(t==='account'&&store&&!P.key&&!P.busy&&P.ready)getKey().then(render);   // the key may have come with a scan since the start
}
function checked(){var r=doc.querySelector('input[name="tab"]:checked');return r?A.tab(r.id):null;}
// a deep link to New coins (a tap on the "new coins" notification): once the early box shows the scan's list (within 30 s, and only while
// the reader has not scrolled), the page scrolls to the box, so its status line and the first coins are in view, not the scored list's head
function early(){
  if(!toEarly||cur!=='young')return;
  if(Date.now()-toEarly>30000||(window.scrollY||0)>8){toEarly=0;return;}
  var b=doc.querySelector('[data-early]');if(!b||b.hidden||!A.listed(lastEarly))return;
  var w=doc.querySelector('.wrap'),gap=w?parseFloat(getComputedStyle(w).paddingTop)||16:16;
  window.scrollTo(0,Math.max(0,b.getBoundingClientRect().top+(window.scrollY||0)-gap));toEarly=0;jumped=true;
}
function buildBar(){
  var nav=el('nav','appbar');nav.setAttribute('role','tablist');nav.setAttribute('aria-label','Sections');
  A.TABS.forEach(function(t){var b=el('button');b.type='button';b.setAttribute('role','tab');b.setAttribute('data-tab',t);
    b.innerHTML=ICON[t];b.appendChild(el('span','',NAMES[t]));
    b.addEventListener('click',function(){if(t===cur){try{window.scrollTo({top:0,behavior:'smooth'});}catch(e){window.scrollTo(0,0);}}else select(t,'keep');});btns[t]=b;nav.appendChild(b);});
  return nav;
}
function mark(t,cls,on,text){var b=btns[t];if(!b)return;var e=b.querySelector('.'+cls);
  if(!on){if(e)e.parentNode.removeChild(e);}else{if(!e){e=el('span',cls);e.setAttribute('aria-hidden','true');b.appendChild(e);}if(text!=null)e.textContent=text;}
  label(t);}
// what a screen reader says for a tab: its name, the count on it, the live scan (the badge and the dot themselves are hidden from it)
function label(t){var b=btns[t];if(!b)return;var c=b.querySelector('.ab-cnt'),d=b.querySelector('.ab-dot');
  b.setAttribute('aria-label',NAMES[t]+(c?', '+c.textContent+' listed now':'')+(d?', a scan is running now':''));}
// ---- notifications
var P={reg:null,key:null,sub:null,saved:false,error:'',quiet:'',hint:'',busy:false,ready:false},prefs={young:true,pick:true},ui={};
try{var pp=JSON.parse(ls('memebot-push-prefs')||'null');if(pp&&typeof pp==='object')['young','pick'].forEach(function(k){if(typeof pp[k]==='boolean')prefs[k]=pp[k];});}catch(e){}
function perm(){try{return window.Notification?Notification.permission:'default';}catch(e){return 'default';}}
function state(){return A.pushState({sw:'serviceWorker' in navigator,push:'PushManager' in window,notif:'Notification' in window,store:!!store,key:P.key,perm:perm(),sub:P.sub,saved:P.saved,error:P.error});}
function why(e){return e&&e.message?String(e.message).slice(0,80):String(e&&e.name||e||'unknown error').slice(0,80);}
function sb(path,body){var h={apikey:store.key,Accept:'application/json'};if(body)h['Content-Type']='application/json';
  return fetch(store.url+'/rest/v1/'+path,{method:body?'POST':'GET',headers:h,body:body?JSON.stringify(body):undefined,cache:'no-store'})
    .then(function(r){if(!r.ok)return r.text().catch(function(){return '';}).then(function(t){
      throw new Error(/too many new subscriptions/.test(t)?'too many new subscriptions this hour, try again in an hour':'HTTP '+r.status);});
      return r.text();}).then(function(t){return t?JSON.parse(t):null;});}
// the VAPID public key from the live store; a failure is an error the card shows after a tap, else a note (nothing was tried yet)
function getKey(tap){return sb('app_config?select=value&key=eq.vapid_public_key').then(function(rows){var v=rows&&rows[0]&&rows[0].value;
  P.key=typeof v==='string'&&/^[A-Za-z0-9_-]{80,100}$/.test(v)?v:null;if(!P.sub)P.quiet='';},
  function(e){P.key=null;if(tap)P.error='the live store did not answer ('+why(e)+')';else P.quiet='The live store did not answer just now ('+why(e)+'). Tap Try again, or come back later.';});}
function bytes(s){s=s.replace(/-/g,'+').replace(/_/g,'/');s+='==='.slice((s.length+3)%4);var b=atob(s),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a;}
// save the subscription and its settings; tap: a failure is an error the card shows (the tap did not work), else (the quiet save at every
// start) it only adds a note and is tried again when the app comes back
function save(tap){
  var j=P.sub.toJSON(),old=ls('memebot-push-ep');
  return sb('rpc/save_push_sub',{p_sub:j,p_prefs:prefs}).then(function(){P.saved=true;P.error='';P.quiet='';ls('memebot-push-ep',j.endpoint);ls('memebot-push-key',P.key||'');ls('memebot-push-on','1');
    if(old&&old!==j.endpoint)sb('rpc/drop_push_sub',{p_sub:{endpoint:old}}).catch(function(){});},
    function(e){P.saved=false;if(tap)P.error='the subscription was not saved ('+why(e)+')';
      else P.quiet='Not checked in with the live store just now ('+why(e)+'); the app tries again when you come back to it.';});
}
function subscribe(tap){return P.reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(P.key)}).then(function(s){P.sub=s;return save(tap);});}
// whether a subscription was made with this key (its own record of the key; else what this app noted when it saved it)
function sameKey(s,key){try{var a=s&&s.options&&s.options.applicationServerKey;if(a){a=new Uint8Array(a);var b=bytes(key);if(a.length!==b.length)return false;
  for(var i=0;i<a.length;i++)if(a[i]!==b[i])return false;return true;}}catch(e){}var was=ls('memebot-push-key');return !was||was===key;}
function turnOn(){
  if(P.busy)return;
  if(!P.reg||!P.key){P.busy=true;P.error='';P.hint='';render();
    (store?getKey(true):Promise.resolve()).then(function(){P.busy=false;if(P.key&&P.reg)P.hint='Ready: tap Turn on notifications once more, then allow them.';render();});return;}
  P.busy=true;P.error='';P.hint='';
  var p;try{p=subscribe(true);}catch(e){p=Promise.reject(e);}     // first thing in the tap: iOS asks for the permission only from a user gesture
  render();
  p.catch(function(e){if(perm()!=='denied')P.error=P.error||'the subscription could not be made ('+why(e)+')';}).then(function(){P.busy=false;render();});
}
function turnOff(){
  if(P.busy||!P.sub)return;P.busy=true;render();
  var s=P.sub,j=s.toJSON();
  sb('rpc/drop_push_sub',{p_sub:j}).catch(function(){}).then(function(){return s.unsubscribe();}).catch(function(){})
    .then(function(){P.sub=null;P.saved=false;P.error='';P.quiet='';ls('memebot-push-on','0');P.busy=false;render();});
}
// the app comes back: the key may be there now, a quiet save that failed is tried again
function back(){
  if(doc.hidden||P.busy||!store||!P.ready)return;
  if(!P.key)getKey().then(render);
  else if(P.sub&&!P.saved&&perm()==='granted'){P.busy=true;render();save(false).then(function(){P.busy=false;render();});}
}
var TEXT={off:['Off','','Get a notification when the new coins are listed, about five minutes into each hourly scan, and when the pick is made.','Turn on notifications'],
  on:['On','good','This iPhone gets the notifications switched on below.','Turn off notifications'],
  denied:['Blocked','bad','Notifications are blocked for Meme-Bot. Allow them in Settings > Notifications > Meme-Bot, then open the app again.',''],
  unsupported:['Not supported','warn','Notifications need iOS 16.4 or newer. If Meme-Bot was added to the Home Screen from another browser, add it again from Safari and open it from there.',''],
  nostore:['Not set up','warn','The live store is not connected yet: add the three Supabase settings to the repository (see the README). The next scan builds the page with them.',''],
  nokey:['Not ready yet','warn','The next scan prepares notifications. Open this tab again after it has run.',''],
  error:['Off','bad','','Try again']};
function card(){
  var sec=el('section','appnotif'),head=el('div','sec-head'),c=el('div','card');
  head.appendChild(el('h2','','Notifications'));head.appendChild(el('p','','fake money only: nothing is bought for real'));
  var top=el('div','nf-top');ui.title=el('strong','','On this iPhone');ui.chip=el('span','chip');top.appendChild(ui.title);top.appendChild(ui.chip);
  ui.note=el('p','nf-note');ui.btn=el('button','nf-btn');ui.btn.type='button';
  ui.btn.addEventListener('click',function(){if(state()==='on')turnOff();else turnOn();});
  ui.prefs=el('div','nf-prefs');
  [['young','New coins listed','about five minutes into each scan'],['pick','The pick is made','at the end of each scan']].forEach(function(p){
    var row=el('label','nf-row'),sp=el('span'),inp=el('input');sp.appendChild(el('b','',p[1]));sp.appendChild(el('small','',p[2]));
    inp.type='checkbox';inp.setAttribute('role','switch');inp.checked=prefs[p[0]];inp.setAttribute('data-pref',p[0]);
    inp.addEventListener('change',function(){var was=prefs[p[0]];prefs[p[0]]=inp.checked;ls('memebot-push-prefs',JSON.stringify(prefs));
      if(P.sub&&state()==='on'){P.busy=true;render();save(false).then(function(){P.busy=false;
        if(!P.saved){prefs[p[0]]=was;ls('memebot-push-prefs',JSON.stringify(prefs));P.quiet='That change was not saved: the live store did not answer. Try again in a moment.';}render();});}});   // not saved: the switch goes back
    row.appendChild(sp);row.appendChild(inp);ui.prefs.appendChild(row);});
  ui.pnote=el('p','nf-small','These two apply once notifications are on.');
  ui.small=el('p','nf-small','If notifications stop arriving, turn them off and on again here. A Focus mode can hide them; allow Meme-Bot in its settings.');
  [top,ui.note,ui.btn,ui.prefs,ui.pnote,ui.small].forEach(function(x){c.appendChild(x);});
  sec.appendChild(head);sec.appendChild(c);return sec;
}
function render(){
  if(!ui.btn)return;
  var s=state(),t=TEXT[s]||TEXT.off;
  ui.chip.textContent=P.busy?'Working':t[0];ui.chip.className='chip '+(P.busy?'neutral':t[1]);
  var retry=s==='nokey'&&!!P.quiet;     // no key because the store did not answer (not because no scan made one): a button to try again
  ui.note.textContent=s==='error'?'Could not turn notifications on: '+P.error+'.':(s==='on'||retry)&&P.quiet?(retry?P.quiet:t[2]+' '+P.quiet):s==='off'&&P.hint?P.hint:t[2];
  ui.btn.hidden=!t[3]&&!retry;ui.btn.textContent=P.busy?'One moment':retry?'Try again':t[3];ui.btn.disabled=P.busy||!P.ready&&s!=='unsupported';ui.btn.classList.toggle('quiet',s==='on');
  ui.prefs.hidden=['on','off','error'].indexOf(s)<0;ui.prefs.classList.toggle('dim',s!=='on');ui.pnote.hidden=ui.prefs.hidden||s==='on';
  all('input',ui.prefs).forEach(function(i){i.disabled=P.busy;i.checked=prefs[i.getAttribute('data-pref')];});
  ui.small.hidden=s!=='on';
  if(ui.bell){ui.bell.setAttribute('data-on',s==='on'?'1':'0');ui.bell.setAttribute('aria-label','Notifications: '+t[0]);var i=ui.bell.querySelector('i');
    if(s==='on'&&!i)ui.bell.appendChild(el('i'));if(s!=='on'&&i)ui.bell.removeChild(i);}
}
function startPush(){
  if(!('serviceWorker' in navigator)){P.ready=true;render();return;}
  navigator.serviceWorker.addEventListener('message',function(e){var d=e.data;if(d&&d.type==='memebot-open'){var t=null;try{t=A.tab(new URL(d.url,location.href).hash);}catch(x){}if(t)select(t,'top');}});
  navigator.serviceWorker.register('./sw.js',{scope:'./',updateViaCache:'none'}).then(function(){return navigator.serviceWorker.ready;}).then(function(reg){
    P.reg=reg;
    if(state()==='unsupported'||!store)return;
    return getKey().then(function(){return reg.pushManager.getSubscription();}).then(function(s){
      P.sub=s;
      if(s&&P.key&&!sameKey(s,P.key))return s.unsubscribe().then(function(){P.sub=null;if(perm()==='granted')return subscribe(false);});   // made with an older key
      if(s)return save(false);                  // saved again at every start: the store learns it is alive, the endpoint may have changed
      if(perm()==='granted'&&P.key&&ls('memebot-push-on')==='1')return subscribe(false);   // the subscription died without a word (iOS): renew it
    });
  }).catch(function(e){P.error=P.error||why(e);}).then(function(){P.ready=true;render();});
}
// ---- the live news (report.py's live script sends it after every answer of either transport, and whenever the early box changes what it
// shows): the office's live dot (the office view's own state), the New coins count, a new pick. The count on New coins is the early list's
// while the early box shows it (A.badge), else there is none, so the badge never says more than the tab shows.
function onLive(e){
  var d=e&&e.detail||{},st=d.status,c=d.current,MB=window.MemebotLive,live=false;
  try{live=typeof d.state==='string'?d.state==='live':!!(st&&MB&&MB.state(st,Date.now(),pageT,0)==='live');}catch(x){}
  mark('office','ab-dot',live);
  var k=A.badge(d.early,d.young);mark('young','ab-cnt',!!k,k!=null?String(k):null);
  lastEarly=d.early;setTimeout(early,0);      // after the live script has drawn the box
  var pk=A.pick(st,c,pageT),pane=doc.getElementById('pane-pick'),ban=doc.querySelector('.applive');
  if(pk&&pane){if(!ban){ban=el('p','applive');pane.insertBefore(ban,pane.firstChild);}
    ban.textContent='New pick from the scan that just ran: '+String(pk.sym).slice(0,24)+(typeof pk.score==='number'?', score '+Math.round(pk.score):'')+'. The full report follows in a few minutes. Paper trading only.';}
  else if(ban)ban.parentNode.removeChild(ban);
}
function init(){
  var tabs=doc.querySelector('.tabs'),hdr=doc.querySelector('header');
  if(tabs){
    if(!doc.getElementById('tab-account')){var acc=el('input');acc.type='radio';acc.name='tab';acc.id='tab-account';acc.tabIndex=-1;acc.setAttribute('aria-hidden','true');tabs.insertBefore(acc,tabs.querySelector('.tabbar'));}
    var notice=doc.querySelector('.wrap > .live');if(notice){notice.setAttribute('data-app','pick');
      var sm=notice.querySelector('small');if(sm)sm.textContent='The app refreshes when you come back to it after a few minutes. Scan now opens GitHub: tap \u201cRun workflow\u201d there and come back in about ten minutes.';}
    doc.body.appendChild(buildBar());A.TABS.forEach(label);
  }
  all('[data-app-only]').forEach(function(e){e.hidden=false;});
  var eh=doc.querySelector('.ehint');if(eh&&store)eh.textContent=eh.textContent.replace(/ Keep this tab open\.$/,' With notifications on, this iPhone tells you when they are here.');
  var sec=card();if(tabs)sec.setAttribute('data-app','account');
  var spot=doc.querySelector('[data-app~="account"]')||doc.querySelector('.wrap > footer');if(spot)spot.parentNode.insertBefore(sec,spot);
  if(hdr){ui.bell=el('button','appbell');ui.bell.type='button';ui.bell.innerHTML=ICON.bell;hdr.appendChild(ui.bell);
    ui.bell.addEventListener('click',function(){if(tabs)select('account',false);sec.scrollIntoView({block:'start'});if(ui.btn&&!ui.btn.hidden)ui.btn.focus({preventScroll:true});});}
  // a deep link (#tab-young from a notification) picks the tab; the hash is dropped again (the next link with the same hash still counts) and the
  // page stays at the top instead of the browser's jump to the radio of that name
  function link(){var t=A.tab(location.hash);if(!t)return null;try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}return t;}
  var first=link();
  select(first||(tabs?ss('memebot-apptab'):null)||checked()||'pick',first?'top':null);
  if(first)window.addEventListener('load',function(){if(!jumped)window.scrollTo(0,0);});
  window.addEventListener('hashchange',function(){var t=link();if(t)select(t,'top');});
  window.addEventListener('memebot-live',onLive);
  doc.addEventListener('visibilitychange',back);
  A.hold=function(){return !!P.busy||cur==='account';};      // report.py's live script does not reload the app now (a tap on Account at work)
  render();startPush();
}
if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',function(){try{init();}catch(e){}});else try{init();}catch(e){}
})();
"""

SW_JS = r"""// sw.js: the Meme-Bot app's service worker, next to index.html so its scope is the website's folder. Fake money only.
// It shows every push as a notification (Safari takes the permission back after a push without one), opens the app on a tap, and keeps
// the last copy of the page for a start without network: that copy is marked offline, so it never passes for the current report.
var CACHE='memebot-page-v1',HOME=new URL('./',self.location).href;
var OFFLINE='<div class="appoff" role="status"><strong>Offline.</strong> This is the last report this app saw, not the current one. It updates when the connection is back.</div>';
function inScope(u){try{var x=new URL(u||'./',HOME).href;return x.indexOf(HOME)===0?x:HOME;}catch(e){return HOME;}}
self.addEventListener('install',function(){self.skipWaiting();});
self.addEventListener('activate',function(e){
  e.waitUntil(caches.keys().then(function(ks){return Promise.all(ks.filter(function(k){return k.indexOf('memebot-')===0&&k!==CACHE;}).map(function(k){return caches.delete(k);}));})
    .catch(function(){}).then(function(){return self.clients.claim();}));
});
// the app page only (other files load as usual): the network first, revalidated (GitHub Pages' 10-minute cache never shows an old
// report); without network the last good copy, marked offline
self.addEventListener('fetch',function(e){
  var r=e.request;if(r.method!=='GET'||r.mode!=='navigate')return;
  var u=r.url.split('#')[0].split('?')[0];if(u!==HOME&&u!==HOME+'index.html')return;
  function cached(){return caches.match(HOME).then(function(res){if(!res)return null;return res.text().then(function(t){
    t=t.replace('<html lang="en"','<html lang="en" data-offline="1"').replace('<div class="wrap">','<div class="wrap">'+OFFLINE);
    return new Response(t,{headers:{'Content-Type':'text/html; charset=utf-8'}});});}).catch(function(){return null;});}
  e.respondWith(fetch(r.url,{cache:'no-cache',credentials:'same-origin'}).then(function(res){
    if(res.ok){var c=res.clone();caches.open(CACHE).then(function(k){return k.put(HOME,c);}).catch(function(){});return res;}
    return cached().then(function(x){return x||res;});
  },function(){return cached().then(function(x){return x||Response.error();});}));
});
// a push: Declarative Web Push JSON ({"web_push":8030,"notification":{title,body,navigate}}; iOS 18.4+ shows those itself) or plain
// text: always a notification, whatever arrives
self.addEventListener('push',function(e){
  var d=null,n;
  try{d=e.data?e.data.json():null;}catch(x){d={notification:{title:'Meme-Bot',body:e.data?String(e.data.text()).slice(0,300):''}};}
  if(!d||typeof d!=='object')d={};
  n=d.notification&&typeof d.notification==='object'?d.notification:d;
  var title=String(n.title||'Meme-Bot').slice(0,120),opts={body:String(n.body||'').slice(0,400),lang:n.lang||'en',icon:'./icon-192.png',
    data:{url:inScope(n.navigate||(n.data&&n.data.url))}};
  if(n.tag)opts.tag=String(n.tag);
  e.waitUntil(self.registration.showNotification(title,opts).catch(function(){return self.registration.showNotification('Meme-Bot',{body:opts.body,data:opts.data});}));
});
// a tap: the open app is brought forward and told which tab to show (navigating an open iOS app from here is unreliable); else the
// app opens at the notification's address, always inside its own scope
self.addEventListener('notificationclick',function(e){
  e.notification.close();
  var url=inScope(e.notification.data&&e.notification.data.url);
  e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(function(ws){
    var w=ws.filter(function(c){return c.url.indexOf(HOME)===0;})[0];
    if(!w)return self.clients.openWindow(url);
    return Promise.resolve(w.focus()).then(function(c){(c||w).postMessage({type:'memebot-open',url:url});},function(){return self.clients.openWindow(url);});
  }));
});
"""

if __name__ == "__main__":
    main()
