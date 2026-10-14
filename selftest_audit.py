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


# ---------------------------------------------------------------------------------------------------------------- F3/K2 sync log
def check_sync_redact(check):
    """F3/K2: bot.py sync never logs the credential of its remote: the success line (a token URL rewritten by git's insteadOf to a local
    bare repo) and a failed push's message (a token URL nothing answers at)."""
    tmp = tempfile.mkdtemp(prefix="memebot-audit-sync-")
    bare, mb, mb2 = os.path.join(tmp, "bare.git"), os.path.join(tmp, "mb"), os.path.join(tmp, "mb2")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    for d in (mb, mb2):
        os.makedirs(d)
        with open(os.path.join(d, "report.html"), "w") as f:
            f.write("<p>fake money</p>")
    secret = "s3cretAuditTok"
    url = "https://x-access-token:%s@example.invalid/Meme-Bot.git" % secret
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="url.%s.insteadOf" % bare, GIT_CONFIG_VALUE_0=url, GIT_TERMINAL_PROMPT="0")
    p = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", mb, "--remote", url], capture_output=True, text=True, env=env, timeout=120)
    ok_line = next((l for l in p.stderr.splitlines() if l.startswith("sync: ")), "")
    pushed = subprocess.run(["git", "-C", bare, "ls-tree", "--name-only", "results"], capture_output=True, text=True).stdout.split()
    bad = "https://x-access-token:%s@127.0.0.1:9/Meme-Bot.git" % secret
    q = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", mb2, "--remote", bad], capture_output=True, text=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), timeout=120)
    check(p.returncode == 0 and "report.html" in pushed and ok_line.startswith("sync: new commit -> https://example.invalid/Meme-Bot.git results")
          and secret not in p.stdout + p.stderr and q.returncode != 0 and secret not in q.stdout + q.stderr,
          "F3/K2 sync: the log line names the remote without its credential (%r); a failed push's message carries none either (exit %s)"
          % (ok_line[:90].replace(secret, "<token>"), q.returncode))


# ---------------------------------------------------------------------------------------------------------------- F2/K9 creator check
class StubRpc:
    """The radar's http for fetch.dev_check: Jupiter names each coin's creator, the RPC gives each creator 6 transactions of the last
    minutes (the seller's newest one sells the coin), rpc_left counts as radar_src's post does (None once it is spent)."""

    def __init__(self, creators, seller, now_s):
        self.creators, self.seller, self.now_s = creators, seller, now_s
        self.rpc_left, self.dead, self.limited_by, self.until, self.calls, self.logs = None, set(), {}, 0, [], []

    def get(self, u, *a, **k):
        q = u.rsplit("query=", 1)[-1]
        return [{"id": q, "dev": self.creators.get(q), "audit": {}, "holderCount": 100}]

    def post(self, u, payload, *a, **k):
        if self.rpc_left is not None:
            if self.rpc_left <= 0:
                return None
            self.rpc_left -= 1
        m, p0 = payload["method"], payload["params"][0]
        self.calls.append(m)
        if m == "getSignaturesForAddress":
            return {"result": [{"signature": "%s_%d" % (p0, i), "blockTime": int(self.now_s) - 60 * (i + 1)} for i in range(6)]}
        dev, i = p0.rsplit("_", 1)
        mint = next(a for a, c in self.creators.items() if c == dev)
        bal = lambda x: [{"mint": mint, "owner": dev, "uiTokenAmount": {"uiAmount": x}}]
        sale = mint == self.seller and i == "0"
        return {"result": {"meta": {"preTokenBalances": bal(100.0), "postTokenBalances": bal(0.0 if sale else 100.0)}}}

    def log(self, s):
        self.logs.append(s)


def check_dev_budget(check):
    """F2/K9: the radar's creator check asks only as many coins as its RPC budget reads to the end, so each coin it asks is decided (sold
    or not), and the coins that wait lose no try."""
    import fetch as F
    import selftest_radar as SR
    T, P, _ = SR.modules()
    tmp = tempfile.mkdtemp(prefix="memebot-audit-dev-")
    now = SR.T0
    mints = [SR.addr(7100 + i) for i in range(4)]
    creators = {a: SR.addr(7200 + i, "") for i, a in enumerate(mints)}
    stub = StubRpc(creators, mints[1], now / 1000.0)
    max_tx = F.DEV_MAX_TX
    with SR.memebot_rules():
        R = SR.unit_radar(T, P, tmp, "dev")
        R.http = stub
        R.src.http = stub
        stub.rpc_left = 15
        R.tier2(os.path.join(tmp, "sb"), [{"a": a, "pr": {}, "age": 1.0 + i} for i, a in enumerate(mints)], [], now)
    w = [R.work.get(a) or {} for a in mints]
    sold = [((x.get("devRow") or {}).get("devSold")) for x in w]
    check(len(stub.calls) <= 8 and [x.get("dev") for x in w] == ["ok", "ok", "pending", "pending"] and sold[:2] == [False, True]
          and [x.get("devTries", 0) for x in w] == [1, 1, 0, 0] and F.DEV_MAX_TX == max_tx,
          "F2/K9 radar creator check: with 8 RPC calls it asks 2 of 4 young coins and decides both (sold %s, %d calls), the other 2 wait "
          "without losing a try (dev %s, tries %s); fetch's DEV_MAX_TX is back to %s"
          % (sold[:2], len(stub.calls), [x.get("dev") for x in w], [x.get("devTries", 0) for x in w], F.DEV_MAX_TX))


# ---------------------------------------------------------------------------------------------------------------- K5 radar saved
def check_radar_saved(check):
    """K5: the radar's cycle line says where radar.json went: radar-data pushed (or not) and the app's row written, off or not written."""
    import selftest_radar as SR
    T, P, _ = SR.modules()
    tmp = tempfile.mkdtemp(prefix="memebot-audit-saved-")
    mock = SR.RadarMock(SR.FIX.values())
    srv = SR.serve(mock)
    try:
        remote = SR.fresh_remote(T, tmp, "rem", SR.T0)
        SR.put_branch(remote, "results", {"db/memebot/state.json": {"v": 1}}, tmp)
        code, R, lines, _ = SR.run_radar(T, P, "http://127.0.0.1:%d" % srv.server_address[1], remote, os.path.join(tmp, "rd"), SR.T0, minutes=2.5)
    finally:
        srv.shutdown()
        if mock in SR.MOCKS:
            SR.MOCKS.remove(mock)
    cyc = [l for l in lines if l.startswith("cycle ")]
    check(code == 0 and bool(cyc) and cyc[-1].endswith("; radar-data pushed, app row off") and "refs/heads/radar-data" in SR.refs(remote),
          "K5 radar: the cycle line says where radar.json went (%r)" % (cyc[-1][-70:] if cyc else lines[-3:]))


# ---------------------------------------------------------------------------------------------------------------- K4 rounding
def check_age_rounding(check):
    """K4: traps' rounded ageMin (2.14) against the radar's full float (2.13823...) is no mismatch; a real difference is said once."""
    import types
    import selftest_radar as SR
    T, P, _ = SR.modules()
    tmp = tempfile.mkdtemp(prefix="memebot-audit-age-")
    lines, radar_age = [], [2.1382333333333334]
    with SR.memebot_rules():
        R = SR.unit_radar(T, P, tmp, "age", log=lines.append)
        R.T = types.SimpleNamespace(signals_radar=lambda c: {"ageMin": 2.14})
        R.coin = lambda r, now: {"sym": "AGE", "ageMin": radar_age[0]}
        R.signals({}, SR.T0)
        quiet = [l for l in lines if l.startswith("signal ageMin")]
        radar_age[0] = 3.0
        R.signals({}, SR.T0)
        R.signals({}, SR.T0)
    said = [l for l in lines if l.startswith("signal ageMin")]
    check(not quiet and len(said) == 1 and "3.0" in said[0],
          "K4 radar: ageMin 2.14 (traps) against 2.13823 (the radar) is no mismatch (%d lines); 2.14 against 3.0 is said once (%r)" % (len(quiet), said))


def audit_checks(check):
    print("== error audit (WP7): one check for each fix")
    check_push_reason(check)
    check_sync_redact(check)
    check_dev_budget(check)
    check_radar_saved(check)
    check_age_rounding(check)


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
