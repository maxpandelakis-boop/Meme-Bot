#!/usr/bin/env python3
"""selftest_comments.py: the pump.fun comment speed (fetch.pf_comment_speed -> pc/*.txt -> memebot's pc.* factors), measured only.

C1  replies with millisecond stamps ({"replies": [...]}) and with second stamps (a bare list) both count: last hour, last 6 h,
    distinct commenters in the last hour, minutes since the newest; a coin whose address does not end in 'pump' is not asked
C2  a blocked host (403) writes no rows and the run goes on
C3  memebot reads pc/*.txt, feats() turns it into pc.n1h, pc.n6h, pc.users1h, pc.newestMin, and pc.* is MEASURE_ONLY (no weight)
"""
import json, os, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch as F
import memebot as M

NOW = 1_800_000_000
OK_MS = "A" * 40 + "pump"
OK_S = "B" * 40 + "pump"
BLOCKED = "C" * 40 + "pump"
NOT_PF = "D" * 44
FAILS = []
ASKED = []


def check(ok, what):
    print(("  PASS " if ok else "  FAIL ") + what)
    if not ok:
        FAILS.append(what)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        ASKED.append(u.path)
        mint = u.path.rsplit("/", 1)[-1]
        ago = [60, 1800, 1900, 4 * 3600, 20 * 3600]
        users = ["u1", "u2", "u1", "u3", "u4"]
        if mint == OK_MS:
            code, body = 200, {"replies": [{"timestamp": (NOW - s) * 1000, "user": w, "text": "x"} for s, w in zip(ago, users)], "hasMore": False}
        elif mint == OK_S:
            code, body = 200, [{"timestamp": NOW - s, "username": w} for s, w in zip(ago[2:], users[2:])]
        else:
            code, body = 403, {"error": "blocked"}
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mock = "http://127.0.0.1:%d" % srv.server_address[1]
    d = tempfile.mkdtemp()
    log = []
    http = F.Http(mock=mock, pause=0, log=log.append)
    print("== C1/C2: the logger")
    n = F.pf_comment_speed(http, d, [OK_MS, NOT_PF, OK_S, BLOCKED], now=NOW)
    rows, _ = M.load_side(d, "pc", M.PC_COLS)
    a, b = rows.get(OK_MS) or {}, rows.get(OK_S) or {}
    check(n == 2 and (a.get("n1h"), a.get("n6h"), a.get("users1h"), a.get("newestMin"), a.get("read")) == (3.0, 4.0, 2.0, 1.0, 5.0),
          "milliseconds: 3 replies in the last hour from 2 people, 4 in 6 h, newest 1 min ago (%s)" % a)
    check((b.get("n1h"), b.get("n6h"), b.get("users1h"), b.get("newestMin")) == (1.0, 2.0, 1.0, 31.7), "seconds, a bare list: read the same way (%s)" % b)
    check(BLOCKED not in rows and not any(NOT_PF in p for p in ASKED), "a blocked coin writes no row; a coin that is not a pump.fun mint is not asked (%d asked)" % len(ASKED))
    print("== C3: the factors")
    f, _ = M.feats({"address": OK_MS, "symbol": "T", "name": "T", "priceUsd": 1.0, "liquidityUsd": 50000.0, "marketCap": 300000.0, "pc": {k: v for k, v in a.items() if k != "address"}}, NOW * 1000)
    check(f.get("pc.n1h") == 3.0 and f.get("pc.n6h") == 4.0 and f.get("pc.users1h") == 2.0 and f.get("pc.newestMin") == 1.0,
          "feats: pc.n1h, pc.n6h, pc.users1h, pc.newestMin (%s)" % {k: v for k, v in f.items() if k.startswith("pc.")})
    f0, _ = M.feats({"address": NOT_PF, "symbol": "T", "name": "T", "priceUsd": 1.0, "liquidityUsd": 50000.0, "marketCap": 300000.0}, NOW * 1000)
    check(not any(k.startswith("pc.") for k in f0) and "pc." in M.MEASURE_ONLY, "no comment data, no pc.* factor; pc.* is measured only (no weight, no pick moved)")
    srv.shutdown()
    print("selftest_comments: %d failed" % len(FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
