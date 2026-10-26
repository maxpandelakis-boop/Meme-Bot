#!/usr/bin/env python3
"""selftest_keepalive.py: the bots start each other (keepalive.py, rocket.yml, seeker.yml, scan.yml's safety net) on made-up GitHub
answers (fake money only; no network but a local stand-in for GitHub's API).

  python3 selftest_keepalive.py

Checks: K1 the plan: a scan 55 minutes after the newest one began (a cancelled run and a safety-net run that skipped itself do not
count), none while one waits or runs; the rocket hunter and the seeker started when no run of theirs waits or runs but the caller's own;
a disabled workflow, MEMEBOT_SEEKER=0 or no answer starts nothing; K2 a run against a stand-in API: the token read from REPO_URL goes
only to it, the starts carry the default branch (the scan: source hourly, 2h), nothing from a push or another branch, never raises when
the API is gone; K3 the workflows: rocket.yml calls it after each round's save and seeker.yml every 10 ticks, both with actions: write
and the bots still run without the token; the scan's safety net counts a scan started in the 55 minutes before it.
"""
import json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import keepalive as K

FAILS = []
NOW = 1_793_020_000                    # 26 Oct 2026 12:26:40 UTC


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def run(rid, created, status="completed", conclusion="success", event="workflow_dispatch", took=2700):
    return {"id": rid, "status": status, "conclusion": conclusion if status == "completed" else None, "event": event,
            "created_at": iso(created), "run_started_at": iso(created), "updated_at": iso(created + (took if status == "completed" else 60))}


def k1(check):
    scan_old = [run(1, NOW - 80 * 60)]
    bots_idle = [run(5, NOW - 70 * 60)]
    me = 9
    info = {"scan.yml": ("active", scan_old), "rocket.yml": ("active", [run(me, NOW - 30 * 60, "in_progress")] + bots_idle),
            "seeker.yml": ("active", bots_idle)}
    go, notes = K.plan(NOW, me, info)
    check(go == [("scan.yml", {"horizon": "2h", "source": "hourly"}), ("rocket.yml", None), ("seeker.yml", None)],
          "K1 nothing waiting: the scan (80 min after the last, source hourly, 2h), the caller's next run and the seeker's are started (%s)" % go)
    info2 = dict(info, **{"scan.yml": ("active", [run(2, NOW - 40 * 60, "in_progress")] + scan_old)})
    info2["rocket.yml"] = ("active", [run(me, NOW - 30 * 60, "in_progress"), run(10, NOW - 5 * 60, "pending")])
    info2["seeker.yml"] = ("active", [run(11, NOW - 20 * 60, "queued")])
    go2, _ = K.plan(NOW, me, info2)
    check(go2 == [], "K1 a scan running, a rocket run waiting behind the caller and a seeker run queued: nothing is started (%s)" % go2)
    recent = [run(3, NOW - 50 * 60)]
    go3, n3 = K.plan(NOW, me, dict(info, **{"scan.yml": ("active", recent)}))
    skipped = [run(4, NOW - 10 * 60, event="schedule", took=20), run(5, NOW - 15 * 60, conclusion="cancelled", took=0)] + scan_old
    go4, _ = K.plan(NOW, me, dict(info, **{"scan.yml": ("active", skipped)}))
    real_sched = [run(6, NOW - 30 * 60, event="schedule", took=2600)] + scan_old
    go5, _ = K.plan(NOW, me, dict(info, **{"scan.yml": ("active", real_sched)}))
    check(("scan.yml", {"horizon": "2h", "source": "hourly"}) not in go3 and any("50 min ago" in x for x in n3)
          and ("scan.yml", {"horizon": "2h", "source": "hourly"}) in go4
          and ("scan.yml", {"horizon": "2h", "source": "hourly"}) not in go5,
          "K1 a scan 50 min ago: none yet; a safety-net run that skipped itself and a cancelled one do not count; a safety-net run that "
          "scanned does")
    go6, _ = K.plan(NOW, me, dict(info, **{"scan.yml": ("active", [])}))
    check(("scan.yml", {"horizon": "2h", "source": "hourly"}) in go6, "K1 no scan in the list: one is started")
    off = dict(info, **{"rocket.yml": ("disabled_manually", bots_idle), "scan.yml": (None, None)})
    go7, n7 = K.plan(NOW, me, off, seeker_on=False)
    check(go7 == [] and any("disabled_manually" in x for x in n7) and any("MEMEBOT_SEEKER=0" in x for x in n7) and any("no answer" in x for x in n7),
          "K1 a disabled workflow, the seeker switched off and a workflow GitHub did not answer for: nothing is started (%s)" % n7)


class API(BaseHTTPRequestHandler):
    calls = []
    runs = {}

    def log_message(self, *a):
        pass

    def answer(self, code, doc=None):
        raw = json.dumps(doc).encode() if doc is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        API.calls.append(("GET", self.path, self.headers.get("Authorization"), None))
        m = re.fullmatch(r"/repos/o/r/actions/workflows/([a-z]+\.yml)(/runs\?per_page=20)?", self.path)
        if self.path == "/repos/o/r":
            return self.answer(200, {"default_branch": "main-branch"})
        if m and m.group(2):
            return self.answer(200, {"workflow_runs": API.runs.get(m.group(1), [])})
        if m:
            return self.answer(200, {"state": "active"})
        return self.answer(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        API.calls.append(("POST", self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n) or b"null")))
        return self.answer(204)


def k2(check):
    srv = HTTPServer(("127.0.0.1", 0), API)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = {"PATH": os.environ.get("PATH", ""), "GITHUB_API_URL": "http://127.0.0.1:%d" % srv.server_port, "GITHUB_REPOSITORY": "o/r",
            "GITHUB_RUN_ID": "77", "GITHUB_REF_NAME": "main-branch", "GITHUB_EVENT_NAME": "schedule",
            "REPO_URL": "https://x-access-token:TOKEN123@github.com/o/r.git"}

    def go(env):
        API.calls = []
        p = subprocess.run([sys.executable, os.path.join(HERE, "keepalive.py"), "--me", "rocket.yml"], env=env, capture_output=True,
                           text=True, timeout=60)
        return p, list(API.calls)

    API.runs = {"scan.yml": [run(1, time.time() - 70 * 60)], "rocket.yml": [run(77, time.time() - 600, "in_progress")],
                "seeker.yml": [run(3, time.time() - 3 * 3600)]}
    p, calls = go(base)
    posts = [c for c in calls if c[0] == "POST"]
    check(p.returncode == 0 and len(posts) == 3 and all(c[2] == "Bearer TOKEN123" for c in calls)
          and posts[0][1].endswith("/scan.yml/dispatches") and posts[0][3] == {"ref": "main-branch", "inputs": {"horizon": "2h", "source": "hourly"}}
          and [c[3] for c in posts[1:]] == [{"ref": "main-branch"}] * 2 and "TOKEN123" not in p.stdout + p.stderr,
          "K2 against a stand-in API: the token from REPO_URL only to it (never printed), the scan, the next rocket run and the seeker "
          "started on the default branch (%s)" % [c[1].rsplit("/", 2)[-2] for c in posts])
    p2, c2 = go(dict(base, GITHUB_EVENT_NAME="push"))
    p3, c3 = go(dict(base, GITHUB_REF_NAME="claude/some-branch"))
    p4, c4 = go(dict(base, MEMEBOT_SEEKER="0"))
    check(not c2 and "push" in p2.stdout and not any(c[0] == "POST" for c in c3) and "default branch" in p3.stdout
          and [c[1].rsplit("/", 2)[-2] for c in c4 if c[0] == "POST"] == ["scan.yml", "rocket.yml"],
          "K2 a push's test run asks nothing, another branch starts nothing, MEMEBOT_SEEKER=0 leaves the seeker out")
    srv.shutdown()
    srv.server_close()
    p5, _ = go(base)
    check(p5.returncode == 0 and "nothing started" in p5.stdout, "K2 the API gone: no error, nothing started (%s)" % p5.stdout.strip()[:80])


def k3(check):
    wf = lambda f: open(os.path.join(HERE, ".github", "workflows", f), encoding="utf-8").read()
    rk, sk, sc = wf("rocket.yml"), wf("seeker.yml"), wf("scan.yml")
    loop = rk[rk.index("- name: Four rounds"):]
    lines = [l.strip() for l in loop.splitlines() if l.strip() and not l.strip().startswith("#")]
    i = lines.index("timeout 60 python3 keepalive.py --me rocket.yml || echo \"keepalive did not answer\"")
    check("actions: write" in rk and lines[i - 2].startswith("env -u REPO_URL timeout 840 python3 rocket_watch.py round") and lines[i - 1] == "save"
          and lines[i + 1].startswith("env -u REPO_URL timeout 900 python3 rocket_watch.py watch") and "MEMEBOT_SEEKER: ${{ vars.MEMEBOT_SEEKER || '1' }}" in loop,
          "K3 rocket.yml: after each round's save it calls keepalive.py (actions: write), before the minute watch; the bots without the token")
    check("actions: write" in sk and 'if [ $((i % 10)) -eq 5 ]; then timeout 60 python3 keepalive.py --me seeker.yml' in sk
          and "env -u REPO_URL timeout 55 python3 seeker_watch.py tick" in sk,
          "K3 seeker.yml: keepalive.py every 10 ticks (actions: write); seeker_watch.py still without the token")
    check('since=$(date -u -d "@$((t - %d))"' % (K.SCAN_EVERY_MIN * 60) in sc,
          "K3 the scan's safety net counts a scan started in the %d minutes before it (keepalive's spacing)" % K.SCAN_EVERY_MIN)


def checks(check):
    k1(check)
    k2(check)
    k3(check)


if __name__ == "__main__":
    checks(check)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)
