#!/usr/bin/env python3
"""selftest_audit.py: one check for each fix of the error audit (WP7; fake money only, nothing is bought).

  python3 selftest_audit.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:              import selftest_audit; selftest_audit.audit_checks(check)

Each check runs against local stand-ins (a fake push library, local git remotes, a stub RPC), never against the network, and fails
when its fix is reverted.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run_py(code, env=None, timeout=120):
    """python3 -c code in this folder with env (default: this process's); (returncode, stdout, stderr)."""
    p = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r)\n" % HERE + code], capture_output=True, text=True, timeout=timeout,
                       env=env if env is not None else dict(os.environ), cwd=HERE)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------------------------------------------------------- F1 push reason
PUSH_REASON = r'''
import json, app
class WPE(Exception):
    def __init__(self, msg, response=None):
        Exception.__init__(self, msg)
        self.response = response
class Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text
ANSWER = {"young": (400, '{"reason":"BadWebPushTopic"}\x1b[31m\n' + "x" * 200), "test": (403, '{"reason":"BadJwtToken"}'),
          "pick": None, "radar": (403, '{"reason":"BadJwtToken"}')}
def webpush(sub, data, headers=None, ttl=0, timeout=None):
    a = ANSWER[headers["Topic"]]
    if a:
        raise WPE("Push failed: %d" % a[0], response=Resp(*a))
row = {"endpoint": "https://web.push.apple.com/QAudit", "sub": {"endpoint": "https://web.push.apple.com/QAudit", "keys": {"p256dh": "p", "auth": "a"}}, "prefs": {}}
app.call = lambda method, path, *a, **k: [row] if method == "GET" else None
app._webpush = lambda: (webpush, WPE)
app.vapid = lambda: {"pub": "k"}
app.vapid_auth = lambda endpoint: "vapid t=x,k=k"
app.keys_ok = lambda s: True
out = [app.notify(k, "t", "b") for k in ("young", "test", "pick", "radar")]
print(json.dumps([[o["sent"], o["failed"]] for o in out]))
'''


def check_push_reason(check):
    """F1: a refused push names the push service's reason (cut, no control characters), and "check the VAPID keys" only for a 403 while
    no kind has reached a phone in this process."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_"))}
    env.update(SUPABASE_URL="http://127.0.0.1:9", SUPABASE_SECRET_KEY="sb_secret_auditkey123456", PYTHONUTF8="1")
    rc, out, err = run_py(PUSH_REASON, env)
    lines = [l for l in err.splitlines() if "notification failed" in l]
    young = next((l for l in lines if "a young notification" in l), "")
    test = next((l for l in lines if "a test notification" in l), "")
    radar = next((l for l in lines if "a radar notification" in l), "")
    check(rc == 0 and out.strip().splitlines()[-1:] == ["[[0, 1], [0, 1], [1, 0], [0, 1]]"]
          and "(config 400), the push service said \"{\"reason\":\"BadWebPushTopic\"}" in young and "\x1b" not in young and "xxxxxxxxxx" * 7 not in young
          and "VAPID" not in young and test.endswith('said "{"reason":"BadJwtToken"}": check the VAPID keys') and radar and "VAPID" not in radar
          and "sb_secret_auditkey" not in err,
          "F1 push: a refused push names the push service's reason (no control characters, at most 80 characters): %r; 'check the VAPID keys' "
          "only for a 403 while no kind has reached a phone (%r), not after the pick went through (%r)" % (young[:150], test[-40:], radar[-60:]))


def audit_checks(check):
    print("== error audit (WP7): one check for each fix")
    check_push_reason(check)


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    t = time.time()
    audit_checks(check)
    print("\n(%.0f s)" % (time.time() - t))
    print("%d checks failed" % len(fails) if fails else "ALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
