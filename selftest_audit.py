#!/usr/bin/env python3
"""selftest_audit.py: one check for each fix of the error audit (WP7; fake money only, nothing is bought).

  python3 selftest_audit.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:              import selftest_audit; selftest_audit.audit_checks(check)

Each check runs against local stand-ins (a fake push library, local git remotes, a stub RPC), never against the network, and fails
when its fix is reverted.
"""
import os
import re
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
ANSWER = {"newcoins": (400, '{"reason":"BadWebPushTopic"}\x1b[31m\n' + "x" * 200), "test": (403, '{"reason":"BadJwtToken"}'),
          "pick": None, "radarhit": (403, '{"reason":"BadJwtToken"}')}       # keyed by the Topic header app.TOPIC sends per kind
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
    # MEMEBOT_PUSH_ALL=1 here, also when this file runs alone: the young and radar pushes are the refused ones this check needs, and
    # app.QUIET skips them otherwise (only buy notifications, Oct 22; selftest_shadow SH8 checks that)
    env.update(SUPABASE_URL="http://127.0.0.1:9", SUPABASE_SECRET_KEY="sb_secret_auditkey123456", PYTHONUTF8="1", MEMEBOT_PUSH_ALL="1")
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


# ---------------------------------------------------------------------------------------------------------------- K3 step A git
def check_import_git_fails(check):
    """K3: scan.yml step A with a local git that fails ls-tree after a good fetch of radar-feed: the mark for the feed step stays
    "failed" (step B fetches the X-link index again), never "none" (which would rebuild the index from this scan alone)."""
    import gzip
    import json
    import shutil
    import selftest_scanside as SS
    try:
        job = SS.load_yaml(SS.SCAN_YML)["jobs"]["scan"]
    except ImportError:
        print("  SKIP K3 step A: PyYAML is not installed here")
        return
    tmp = tempfile.mkdtemp(prefix="memebot-audit-import-")
    try:
        remote = os.path.join(tmp, "r.git")
        SS.git("init", "-q", "--bare", remote)
        now = int(time.time() * 1000)
        doc = lambda d: gzip.compress(json.dumps(d).encode())
        SS.put_branch(remote, "radar-feed", {"walletmem.json.gz": doc({"v": 1, "t": now, "nCoins": 3}), "xlinks.json.gz": doc({"v": 1, "t": now, "links": {}})}, tmp)
        shim = os.path.join(tmp, "shim")
        os.makedirs(shim)
        with open(os.path.join(shim, "git"), "w") as f:
            f.write('#!/bin/bash\ncase " $* " in\n  *" ls-tree "*) echo "fatal: bad object (test)" >&2; exit 128;;\nesac\nexec %s "$@"\n' % shutil.which("git"))
        os.chmod(os.path.join(shim, "git"), 0o755)
        ws = os.path.join(tmp, "ws")
        os.makedirs(os.path.join(ws, "mb"))
        p, _ = SS._import(job, ws, remote, tmp, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
        mark = SS.import_mark(os.path.join(ws, "mb"))
        feed = next((l for l in p.stdout.splitlines() if "radar-feed" in l), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check(p.returncode == 0 and mark == "failed" and "radar-feed stopped (RuntimeError)" in feed,
          "K3 step A: a local git ls-tree that fails after a good fetch leaves the mark 'failed' (%s), so step B fetches the X-link index "
          "itself (%r)" % (mark, feed[-80:]))


# ---------------------------------------------------------------------------------------------------------------- K1 SUPABASE_URL
NODE_STATE = r"""
global.window={};global.document={readyState:'complete',querySelector:function(){return null;}};global.navigator={};
%s
var A=window.MemebotApp,B={sw:true,push:true,notif:true,store:false,key:'k',perm:'default',sub:null,saved:false,error:''};
console.log(JSON.stringify([A.pushState(Object.assign({},B,{why:'url'})),A.pushState(Object.assign({},B,{why:null})),A.pushState(Object.assign({},B,{store:true,why:'url'}))]));
"""


def check_store_url(check):
    """K1: SUPABASE_URL in a wrong form is fixed where it can be (no scheme, a trailing slash, a path, the dashboard's address) and else
    refused with the problem's name, never the value: app.store_url, app.store's one line, bot.py site (data-sb-url fixed, or
    data-sb-why="url") and the Account card's state badurl in place of nostore."""
    import json
    import shutil
    import app as A
    forms = [("https://abcref.supabase.co", "https://abcref.supabase.co", ""), (" abcref.supabase.co/\n", "https://abcref.supabase.co", "no https"),
             ("https://abcref.supabase.co/rest/v1/", "https://abcref.supabase.co", "had a path"),
             ("https://supabase.com/dashboard/project/abcref/settings/api", "https://abcref.supabase.co", "dashboard address"),
             ("http://abcref.supabase.co", None, "plain http"), ("https://user:pw@abcref.supabase.co", None, "not a host"),
             ("ftp://abcref.supabase.co", None, "not https"), ("http://127.0.0.1:5432", "http://127.0.0.1:5432", ""), ("", None, "missing")]
    wrong = [f[0] for f in forms if A.store_url(f[0]) != (f[1], f[2])]
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_")) or k == "MEMEBOT_PUSH_ALL"}
    said = {}
    for u in ("http://abcref.supabase.co", "https://abcref.supabase.co/rest/v1"):
        rc, out, err = run_py("import app\nprint([app.enabled(), app.enabled()])", dict(base, SUPABASE_URL=u, SUPABASE_SECRET_KEY="sb_secret_auditkey123456"))
        said[u] = (out.strip(), [l for l in err.splitlines() if "SUPABASE_URL" in l])
    tmp = tempfile.mkdtemp(prefix="memebot-audit-url-")
    pages = {}
    try:
        d = os.path.join(tmp, "mb")
        os.makedirs(d)
        with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f:
            f.write('<!doctype html><html lang="en"><head><title>Meme-Bot</title></head><body><div class="wrap">fake money</div></body></html>')
        for u in ("https://supabase.com/dashboard/project/abcref", "http://abcref.supabase.co"):
            sd = os.path.join(tmp, "site%d" % len(pages))
            p = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", d, "--out", sd, "--repo", "https://github.com/tester/Meme-Bot"], capture_output=True,
                               text=True, timeout=120, env=dict(base, SUPABASE_URL=u, SUPABASE_PUBLISHABLE_KEY="sb_publishable_OKkey_1234567890"))
            idx = open(os.path.join(sd, "index.html"), encoding="utf-8").read() if os.path.exists(os.path.join(sd, "index.html")) else ""
            pages[u] = (p.returncode, idx.split("<head>")[0], [l for l in p.stderr.splitlines() if "SUPABASE_URL" in l])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    node, states = shutil.which("node"), None
    if node:
        r = subprocess.run([node, "-e", NODE_STATE % A.PAGE_JS], capture_output=True, text=True, timeout=60)
        states = json.loads((r.stdout.strip().splitlines() or ["null"])[-1])
    bad_said, fix_said = said["http://abcref.supabase.co"], said["https://abcref.supabase.co/rest/v1"]
    dash, refused = pages["https://supabase.com/dashboard/project/abcref"], pages["http://abcref.supabase.co"]
    check(not wrong and bad_said[0] == "[False, False]" and len(bad_said[1]) == 1 and bad_said[1][0].endswith("(plain http)") and "abcref" not in bad_said[1][0]
          and fix_said[0] == "[True, True]" and len(fix_said[1]) == 1 and "(had a path)" in fix_said[1][0] and "abcref" not in fix_said[1][0]
          and dash[0] == 0 and 'data-sb-url="https://abcref.supabase.co"' in dash[1] and refused[0] == 0 and 'data-sb-why="url"' in refused[1]
          and "data-sb-url" not in refused[1] and any(l.endswith("(plain http)") for l in refused[2]) and not any("abcref" in l for l in refused[2] + dash[2])
          and states in (None, ["badurl", "nostore", "off"]),
          "K1 SUPABASE_URL: %d forms read as expected (wrong: %s); a refused URL is said once by name (%r), a fixed one too; bot.py site puts the "
          "dashboard address in as https://<ref>.supabase.co and marks a refused one data-sb-why=\"url\"; the Account card reads %s"
          % (len(forms) - len(wrong), wrong, bad_said[1][:1], states if states else "(no node here)"))


def guard(check, fn):
    """fn(check); a check that raises is one FAIL line and the next check still runs."""
    try:
        fn(check)
    except Exception as e:
        check(False, "%s stopped with %s: %s" % (fn.__name__, type(e).__name__, str(e)[-200:]))


def check_push_topic(check):
    """Apple refused the "young" and "radar" pushes with BadWebPushTopic: a Topic must be a whole base64url string (4 or 8 letters)."""
    import app
    tops = [app.TOPIC.get(k) for k in app.KINDS]
    check(all(isinstance(t, str) and re.fullmatch(r"[A-Za-z0-9_-]{4,32}", t) and len(t) % 4 == 0 for t in tops) and len(set(tops)) == len(tops)
          and "TOPIC.get(kind" in open(os.path.join(HERE, "app.py"), encoding="utf-8").read(),
          "push Topic per kind is a whole base64url string Apple accepts, one per kind (%s)" % app.TOPIC)


def audit_checks(check):
    print("== error audit (WP7): one check for each fix")
    for fn in (check_push_reason, check_sync_redact, check_dev_budget, check_radar_saved, check_age_rounding, check_import_git_fails, check_store_url, check_push_topic):
        guard(check, fn)


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
