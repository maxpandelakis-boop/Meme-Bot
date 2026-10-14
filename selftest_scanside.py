#!/usr/bin/env python3
"""selftest_scanside.py: checks S1 to S7 of the scan side of the launch radar and the peak category (fake money only, nothing is bought).

  python3 selftest_scanside.py      -> PASS/FAIL per check, "ALL PASS" at the end, exit code 1 on any failure
  from selftest.main:                 import selftest_scanside; selftest_scanside.scanside_checks(check)

The workflow steps are tested as they are written: each step's script is read from .github/workflows/scan.yml (parsed as YAML) and run
with bash -e against local git remotes and a local stand-in for GitHub's API, never against the network.

S1  step A "Import the launch radar's records": radar-feed's walletmem/xlinks and radar-data's hour docs and radar.json (as
    mb/radar_live.json) reach mb/, added or overwritten, never deleted; junk (other names, symlinks, not a JSON object, no time) is left
    out; missing branches or a dead remote change nothing and print one line each; no credential in the output; each branch on its own
    (a radar-data fetch that fails still brings radar-feed, a radar-feed fetch that hangs still brings radar-data, inside the minute);
    the mark mb/.radar_feed_import says ok, none or failed for the feed step
S2  launch spotter check 1, extended: the trader's docs are byte for byte the same with and without mb/radar_live.json, mb/db/memeradar,
    mb/walletmem.json.gz (and mb/xlinks.json.gz, mb/.radar_feed_import, mb/db/memepeak) present; the cycle leaves those files as they
    were (old radar docs pruned)
S3  bot.py SYNC_IGNORE carries memepeak and memeradar; prune removes memeradar docs older than 30 days and never a memepeak doc; sync
    carries both to the results branch (a pruned doc leaves it) and never the page-only inputs (radar_live.json, walletmem, xlinks, the
    import mark)
S4  young_published sends nothing by default (MEMEBOT_PUSH_YOUNG unset or not "1"); with MEMEBOT_PUSH_YOUNG=1 it sends as before, once
    per cycle; scan.yml passes the repository variable with the default 0
S5  app.KINDS["radar"] == (600, "high", 60), PREF_OF radar -> young: a phone with "New coins" off gets no radar push; the rate guard;
    notify_radar's words say fake money and never buy, safe or clean, and open the Radar tab; an infinite age, count or liquidity reads
    as unknown
S6  scan.yml lint: the cache step is unchanged (I9), steps A/B/D are soft with their timeouts and places, C exports memeradar, job
    peaks needs scan with timeout <= 12, the token only in its restore and push steps, and, run as written (with a stand-in pricing
    step), adds its docs to results as one commit on top of the scan's; no step pushes radar-data; step D (the radar's safety net)
    against a stand-in GitHub API: it starts radar.yml (source hourly) after each full scan, only when the workflow is active, inside
    the hours and no radar run is running or waiting (any status but completed), never when MEMEBOT_RADAR is 0; radar.yml (when on this
    branch): group memebot-radar, no schedule, a round every 5 minutes for 55 minutes (timeout 70), never pushes results, live or
    radar-feed; its last step starts the next run (source auto) only after a loop that ended well, inside the hours, never counting
    itself as another run
S7  step B "Feed the launch radar": traps.py feed on a mock db in < 60 s writes the four files, which go to radar-feed as one orphan
    commit (force-pushed, all four or none: a feed that fails or writes three pushes nothing) at the scan's clock (a run doc dated hours
    ahead is ignored); the X-link history survives a step A that could not fetch radar-feed (step B fetches it itself, else leaves
    radar-feed as it is); the next scan's step A imports the feed
A check group that stops with an exception is one FAIL line; the other groups still run.
"""
import contextlib, glob, gzip, json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
H, D = 3_600_000, 86_400_000
FAKE_TOKEN = "ghs_FAKEtokenFORtheSCANSIDEtest0123456789"     # must never show in any output
SCAN_YML = os.path.join(HERE, ".github", "workflows", "scan.yml")
RADAR_YML = os.path.join(HERE, ".github", "workflows", "radar.yml")
CACHE_STEP = {"name": "Keep the big-test snapshots between runs", "if": "steps.recent.outputs.skip != 'true'", "uses": "actions/cache@v4",
              "with": {"path": "mb/db/memesnap\nmb/db/memesnapres\n", "key": "memebot-snaps-${{ github.run_id }}", "restore-keys": "memebot-snaps-"}}
BASE_STEPS = ["Safety net only - skip when this hour's scan was started", "actions/checkout@v4", "Restore the bot's state from the results branch",
              "Keep the big-test snapshots between runs", "Install the push sender for the iPhone app", "Scan and recommend",
              "Export the big-test results to the bigtest branch", "Push the page and the small docs to the results branch", "Show the picks on this run's page",
              "Build the website folder", "actions/upload-pages-artifact@v3", "Tidy the run list"]
WP4_IGNORE = ("!db/memepeak/", "!db/memepeak/**", "!db/memeradar/", "!db/memeradar/**")
FEED_FILES = ("walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz", "meta.json")
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
NO_WORDS = re.compile(r"\bbuy\b|\bbuying\b|\bsafe\b|\bclean\b|guaranteed|\u2014", re.I)
SKIPS_HERE = []


# ---------------------------------------------------------------- helpers
def skip(what):
    """A check group that cannot run here (the other package is not merged yet, or no PyYAML/cryptography): selftest's SKIPS when it is
    the caller, else this module's own list (named in the last line)."""
    print("  SKIP " + what)
    for name in ("__main__", "selftest"):          # from selftest.main the running copy is __main__ (an import of selftest is a second copy)
        m = sys.modules.get(name)
        if m is not None and isinstance(getattr(m, "SKIPS", None), list) and hasattr(m, "spotter_checks"):
            m.SKIPS.append(what)
            break
    SKIPS_HERE.append(what)


def load_yaml(path):
    """A workflow file parsed (PyYAML); None when the file is missing; raises ImportError without PyYAML."""
    import yaml
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def on_keys(wf):
    """A workflow's triggers (YAML 1.1 reads the key `on` as True)."""
    on = wf.get("on", wf.get(True))
    return set(on) if isinstance(on, dict) else ({on} if isinstance(on, str) else set(on or []))


def step(job, prefix):
    for s in job.get("steps") or []:
        if (s.get("name") or s.get("uses") or "").startswith(prefix):
            return s
    return None


def step_index(job, prefix):
    for i, s in enumerate(job.get("steps") or []):
        if (s.get("name") or s.get("uses") or "").startswith(prefix):
            return i
    return -1


def git(*a, cwd=None, check=True, inp=None):
    p = subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, input=inp, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if check and p.returncode != 0:
        raise RuntimeError("git %s: %s" % (a[0], p.stderr.decode("utf-8", "replace")[-300:]))
    return p.stdout.decode("utf-8", "replace")


def put_branch(remote, branch, files, tmp, links=None):
    """One orphan commit with these files ({path: bytes}) and symlinks ({path: target}) force-pushed to remote's branch."""
    w = tempfile.mkdtemp(prefix="wp4-branch-", dir=tmp)
    git("init", "-q", w)
    for path, raw in files.items():
        os.makedirs(os.path.dirname(os.path.join(w, path)) or w, exist_ok=True)
        with open(os.path.join(w, path), "wb") as f:
            f.write(raw)
    for path, target in (links or {}).items():
        os.makedirs(os.path.dirname(os.path.join(w, path)) or w, exist_ok=True)
        os.symlink(target, os.path.join(w, path))
    git("add", "-A", cwd=w)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", branch, cwd=w)
    git("push", "-q", "--force", remote, "HEAD:refs/heads/" + branch, cwd=w)
    shutil.rmtree(w, ignore_errors=True)


def run_script(script, cwd, env, timeout=120):
    """A workflow step's run script the way the runner runs it (bash -e), in cwd, with env on top of a clean environment."""
    path = os.path.join(cwd, ".step.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_", "GITHUB_", "GH_", "RESULTS_URL", "RUNNER_"))}
    t = time.time()
    p = subprocess.run(["bash", "--noprofile", "--norc", "-e", path], cwd=cwd, capture_output=True, text=True, env=dict(base, **env), timeout=timeout)
    os.remove(path)
    return p, time.time() - t


def tree_bytes(d, skip_git=True):
    out = {}
    for f in glob.glob(os.path.join(d, "**", "*"), recursive=True) + glob.glob(os.path.join(d, "**", ".*"), recursive=True):
        if os.path.isfile(f) and not (skip_git and (os.sep + ".git" + os.sep) in f):
            out[os.path.relpath(f, d)] = open(f, "rb").read()
    return out


def b58(rng, n=44):
    return "".join(rng.choice(ALPH) for _ in range(n))


def gz(obj):
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), mtime=0)


def hour_id(ms):
    return time.strftime("%Y-%m-%dT%H", time.gmtime(ms / 1000))


def radar_hour_doc(hour_ms, n, rng, tag="v"):
    coins = {}
    for i in range(n):
        a = b58(rng)
        coins[a] = {"addr": a, "sym": "R%d%s" % (i, tag), "first": hour_ms + i * 60_000, "pool": hour_ms + i * 60_000 - 180_000, "rt": [[hour_ms + i * 60_000, "watch", 2, 0]]}
    return {"v": 1, "hour": hour_id(hour_ms), "t": hour_ms, "upd": hour_ms + 50 * 60_000, "coins": coins}


def jbytes(obj):
    return json.dumps(obj, separators=(",", ":")).encode()


# ---------------------------------------------------------------- the checks
def scanside_checks(check):
    """S1 to S7 (each prints its own heading). A group that raises is one FAIL line and the next group still runs (selftest.main has no
    guard of its own around a check group)."""
    tmp = tempfile.mkdtemp(prefix="memebot-scanside-")

    def guard(label, fn, *a):
        try:
            fn(check, *a)
        except Exception as e:
            check(False, "%s stopped with %s: %s (the other groups still run)" % (label, type(e).__name__, str(e).replace(FAKE_TOKEN, "<token>")[-300:]))
    try:
        try:
            scan = load_yaml(SCAN_YML)
        except ImportError:
            scan = None
            skip("S1, S6 and S7: the workflow steps (PyYAML is not installed here)")
        job = (scan or {}).get("jobs", {}).get("scan") or {}
        if scan:
            guard("S1", _s1, job, tmp)
        guard("S2", _s2, tmp)
        guard("S3", _s3, tmp)
        guard("S4", _s4, scan, tmp)
        guard("S5", _s5, tmp)
        if scan:
            guard("S6", _s6, scan, tmp)
            guard("S7", _s7, job, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def git_shim(tmp):
    """{PATH: ...} with a git in front that fails (SHIM_FAIL) or hangs (SHIM_HANG) a fetch whose arguments hold that text, like a remote
    that refuses or never answers for one branch; every other git call is the real git."""
    d = os.path.join(tmp, "gitshim")
    if not os.path.isdir(d):
        os.makedirs(d)
        with open(os.path.join(d, "git"), "w") as f:
            f.write('#!/bin/bash\ncase " $* " in\n  *" fetch "*)\n'
                    '    if [ -n "$SHIM_FAIL" ] && [[ " $* " == *"$SHIM_FAIL"* ]]; then echo "fatal: unable to access the remote (test)" >&2; exit 128; fi\n'
                    '    if [ -n "$SHIM_HANG" ] && [[ " $* " == *"$SHIM_HANG"* ]]; then exec sleep 120; fi;;\n'
                    'esac\nexec %s "$@"\n' % shutil.which("git"))
        os.chmod(os.path.join(d, "git"), 0o755)
    return {"PATH": d + os.pathsep + os.environ.get("PATH", "")}


def runner_temp(tmp):
    rt = os.path.join(tmp, "runner-temp")
    os.makedirs(rt, exist_ok=True)
    return rt


def _import(job, ws, remote, tmp, **extra):
    """Step A run in workspace ws (its mb/) against remote (extra: more environment, e.g. the git stand-in)."""
    st = step(job, "Import the launch radar's records")
    return run_script(st["run"], ws, dict(st.get("env") or {}, RESULTS_URL=remote, RUNNER_TEMP=runner_temp(tmp), **extra), timeout=90)


def _feed(job, ws, remote, tmp, **extra):
    """Step B run in workspace ws against remote."""
    st = step(job, "Feed the launch radar")
    return run_script(st["run"], ws, dict(st.get("env") or {}, RESULTS_URL=remote, RUNNER_TEMP=runner_temp(tmp), **extra), timeout=180)


def import_mark(mb):
    """What step A left for step B in mb/.radar_feed_import (None: no mark)."""
    try:
        return open(os.path.join(mb, ".radar_feed_import"), "rb").read().decode()
    except OSError:
        return None


def _s1(check, job, tmp):
    print("== scan side S1: step A imports the launch radar's records, adding or overwriting, never deleting; each branch on its own")
    rng = random.Random(41)
    now = int(time.time() * 1000) // H * H
    remote = os.path.join(tmp, "s1.git")
    git("init", "-q", "--bare", remote)
    h20, h21, h_old = now - 3 * H, now - 2 * H, now - 20 * D
    new20, new21 = radar_hour_doc(h20, 4, rng, "new"), radar_hour_doc(h21, 2, rng)
    radar_json = {"v": 1, "kind": "radar", "t": now - 60_000, "state": "running", "coins": [], "others": [], "counts": {"seen": 3, "good": 0}}
    data = {"radar.json": jbytes(radar_json), "model.json": b'{"from":"prior"}', "pushed.json": b"{}",
            "db/memeradar/%s.json" % hour_id(h20): jbytes(new20), "db/memeradar/%s.json" % hour_id(h21): jbytes(new21),
            "db/memeradar/notes.txt": b"not an hour doc", "db/memeradar/%s.json" % hour_id(now - 4 * H): b"[1, 2]",
            "db/memeradar/%s.json" % hour_id(now - 5 * H): jbytes({"v": 1, "t": "soon", "coins": {}}),
            "db/memeradar/%s.json" % hour_id(now - 6 * H): b"{not json", "db/memeradar/x/%s.json" % hour_id(now - 7 * H): jbytes(radar_hour_doc(now - 7 * H, 1, rng))}
    links = {"db/memeradar/%s.json" % hour_id(now - 8 * H): "../../radar.json"}
    wm = {"v": 1, "t": now - H, "nCoins": 1234, "common": [], "sw": {b58(rng): -8.0}, "rug": [b58(rng)]}
    xl = {"v": 1, "t": now - H, "links": {"x.com/somecoin": [b58(rng), now - 5 * H, 1, "account", now - 5 * H, []]}}
    feed = {"walletmem.json.gz": gz(wm), "xlinks.json.gz": gz(xl), "symmc.json.gz": gz({"v": 1, "t": now, "sym": {"A": 1}}), "meta.json": b'{"v":1}'}
    put_branch(remote, "radar-data", data, tmp, links)
    put_branch(remote, "radar-feed", feed, tmp)
    put_branch(remote, "results", {"report.html": b"<html></html>"}, tmp)
    old20 = radar_hour_doc(h20, 2, rng, "old")
    keep_old = radar_hour_doc(h_old, 3, rng)

    def workspace(name):
        ws = os.path.join(tmp, name)
        for rel, obj in (("db/memeradar/%s.json" % hour_id(h20), old20), ("db/memeradar/%s.json" % hour_id(h_old), keep_old),
                         ("db/memepos/p1.json", {"grp": "young", "sym": "KEEP"})):
            os.makedirs(os.path.dirname(os.path.join(ws, "mb", rel)), exist_ok=True)
            with open(os.path.join(ws, "mb", rel), "wb") as f:
                f.write(jbytes(obj))
        return ws, os.path.join(ws, "mb")
    ws, mb = workspace("s1ws")
    before = tree_bytes(mb)
    p, secs = _import(job, ws, remote, tmp)
    after = tree_bytes(mb)
    lines = [l for l in p.stdout.splitlines() if l.strip()]
    dl = next((l for l in lines if "radar-data:" in l), "")
    print("  " + "\n  ".join(lines))
    mr = sorted(k for k in after if k.startswith("db" + os.sep + "memeradar"))
    want = sorted(os.path.join("db", "memeradar", "%s.json" % hour_id(x)) for x in (h20, h21, h_old))
    check(p.returncode == 0 and mr == want and after.get(os.path.join("db", "memeradar", "%s.json" % hour_id(h_old))) == jbytes(keep_old)
          and after[os.path.join("db", "memeradar", "%s.json" % hour_id(h20))] == jbytes(new20) and after[os.path.join("db", "memeradar", "%s.json" % hour_id(h21))] == jbytes(new21)
          and after.get("radar_live.json") == jbytes(radar_json) and after.get(os.path.join("db", "memepos", "p1.json")) == before[os.path.join("db", "memepos", "p1.json")],
          "radar-data's hour docs are copied into mb/db/memeradar (a newer copy overwrites the older one, a doc only results has stays: %s), radar.json"
          " lands as mb/radar_live.json, other folders untouched" % ", ".join(os.path.basename(x) for x in mr))
    check(after.get("walletmem.json.gz") == feed["walletmem.json.gz"] and after.get("xlinks.json.gz") == feed["xlinks.json.gz"]
          and not {"symmc.json.gz", "meta.json", "model.json", "pushed.json", "radar.json"} & set(after) and not [k for k in after if k.startswith(".radartmp")]
          and not [k for k in after if "notes" in k or (os.sep + "x" + os.sep) in k] and len(lines) == 2 and "radar-feed:" in lines[0] and "(3 skipped" in dl
          and import_mark(mb) == "ok",
          "radar-feed's walletmem.json.gz and xlinks.json.gz reach mb/ byte for byte (first: its X-link history exists nowhere else) and the mark"
          " says ok; model, pushed, symmc and meta stay out; another name, a symlink, a JSON list, a doc without its time and broken JSON are"
          " left out (%s)" % ((re.search(r"\(\d+ skipped[^)]*\)", dl) or [None])[0]))
    # missing branches: one line each, nothing changes; a dead remote: one line, nothing changes, no credential printed
    empty = os.path.join(tmp, "s1-empty.git")
    git("init", "-q", "--bare", empty)
    strip = lambda t: {k: v for k, v in t.items() if k != ".radar_feed_import"}
    before = strip(tree_bytes(mb))
    p2, _ = _import(job, ws, empty, tmp)
    m2, same2 = import_mark(mb), strip(tree_bytes(mb)) == before
    p3, secs3 = _import(job, ws, "https://x-access-token:%s@127.0.0.1:9/nothing.git" % FAKE_TOKEN, tmp)
    m3, same3 = import_mark(mb), strip(tree_bytes(mb)) == before
    l2, l3 = [l for l in p2.stdout.splitlines() if l.strip()], [l for l in p3.stdout.splitlines() if l.strip()]
    print("  " + "\n  ".join(l2 + l3))
    check(p2.returncode == 0 and p3.returncode == 0 and same2 and same3 and len(l2) == 2 and "no branch radar-feed yet" in l2[0] and "no branch radar-data yet" in l2[1]
          and len(l3) == 1 and "did not answer" in l3[0] and secs3 < 30 and FAKE_TOKEN not in p3.stdout + p3.stderr + p2.stdout + p2.stderr
          and (m2, m3) == ("none", "failed"),
          "no radar branches: one line each, mb/ byte for byte as before (the cycle sees what it would without the step) and the mark says none"
          " (nothing to keep); a dead remote: one line after %.1f s, nothing changed, the mark says failed, the credential never printed" % secs3)
    # each branch on its own: radar-data refused still brings radar-feed; radar-feed hanging still brings radar-data, inside the minute
    shim = git_shim(tmp)
    wsf, mbf = workspace("s1-datafail")
    pf, _ = _import(job, wsf, remote, tmp, SHIM_FAIL="refs/heads/radar-data", **shim)
    gotf = tree_bytes(mbf)
    wsh, mbh = workspace("s1-feedhang")
    ph, secs_h = _import(job, wsh, remote, tmp, SHIM_HANG="refs/heads/radar-feed", **shim)
    goth = tree_bytes(mbh)
    lf, lh = [l for l in pf.stdout.splitlines() if l.strip()], [l for l in ph.stdout.splitlines() if l.strip()]
    print("  " + "\n  ".join(lf + lh) + "  (%.1f s)" % secs_h)
    check(pf.returncode == 0 and len(lf) == 2 and lf[0].endswith("radar-feed: walletmem.json.gz, xlinks.json.gz into mb/") and "radar-data could not be fetched" in lf[1]
          and gotf.get("xlinks.json.gz") == feed["xlinks.json.gz"] and "radar_live.json" not in gotf and import_mark(mbf) == "ok"
          and gotf.get(os.path.join("db", "memeradar", "%s.json" % hour_id(h20))) == jbytes(old20),
          "a radar-data fetch that fails: one line, the records keep the results branch's copy, radar-feed still comes (the mark says ok)")
    check(ph.returncode == 0 and len(lh) == 2 and "radar-feed took too long" in lh[0] and "radar-data: 2 hour docs" in lh[1]
          and goth.get(os.path.join("db", "memeradar", "%s.json" % hour_id(h21))) == jbytes(new21) and goth.get("radar_live.json") == jbytes(radar_json)
          and "walletmem.json.gz" not in goth and "xlinks.json.gz" not in goth and import_mark(mbh) == "failed" and secs_h < 30
          and not [k for k in goth if k.startswith(".radartmp")],
          "a radar-feed fetch that never answers: it gives up after its own limit, the mark says failed (the feed step then fetches the X-link"
          " index itself), radar-data's docs still come, and the step ends in %.1f s, inside its minute" % secs_h)


def _with_radar_files(d, now, rng):
    """The radar's files as step A leaves them (plus memepeak docs): returns {relpath: bytes} of what was put there."""
    put = {}
    files = {"radar_live.json": jbytes({"v": 1, "kind": "radar", "t": now - 90_000, "state": "running", "coins": [], "others": []}),
             "walletmem.json.gz": gz({"v": 1, "t": now - H, "nCoins": 99, "common": [], "sw": {b58(rng): -9.5}, "rug": [b58(rng)]}),
             "xlinks.json.gz": gz({"v": 1, "t": now - H, "links": {}}), ".radar_feed_import": b"ok"}
    for k in (now - 2 * H, now - 29 * D):
        files["db/memeradar/%s.json" % hour_id(k)] = jbytes(radar_hour_doc(k // H * H, 3, rng))
    files["db/memeradar/%s.json" % hour_id(now - 31 * D)] = jbytes(radar_hour_doc((now - 31 * D) // H * H, 2, rng))
    files["db/memepeak/p-old.json"] = jbytes({"v": 1, "pos": "p-old", "t": now - 400 * D, "state": "ok", "x": 2.5})
    for rel, raw in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        with open(os.path.join(d, rel), "wb") as f:
            f.write(raw)
        put[rel] = raw
    return put


def _s2(check, tmp):
    print("== scan side S2: the trader's docs are the same with and without the radar's files in mb/ (launch spotter check 1, extended)")
    import selftest as S
    rng = random.Random(43)
    da, db_ = os.path.join(tmp, "s2-plain"), os.path.join(tmp, "s2-radar")
    os.makedirs(db_, exist_ok=True)
    put = _with_radar_files(db_, S.T0, rng)
    pa, sa, _ = S.spot_cycle(da, {"MEMEBOT_EARLY": "1"}, frozen=True)
    pb, sb, _ = S.spot_cycle(db_, {"MEMEBOT_EARLY": "1"}, frozen=True)
    fa, fb = S.trader_files(da), S.trader_files(db_)
    raw = lambda f: open(f, "rb").read()
    diffs = {k: sorted(S.leaf_diff(json.load(open(fa[k], encoding="utf-8")), json.load(open(fb[k], encoding="utf-8")))) or ["<bytes>"]
             for k in set(fa) & set(fb) if raw(fa[k]) != raw(fb[k])}
    print("  cycles %.1f s without, %.1f s with the radar's files; %d trader docs" % (sa, sb, len(fa)))
    check(pa.returncode == pb.returncode == 0 and set(fa) == set(fb) and len(fa) > 15 and not diffs,
          "the trader's %d docs (positions, tips, new launches, snapshots, weights, state, recommend, marks, pairs.json, universe.json) are byte for byte"
          " the same with mb/radar_live.json, mb/db/memeradar, mb/walletmem.json.gz, mb/xlinks.json.gz, mb/.radar_feed_import and mb/db/memepeak"
          " present %s" % (len(fa), diffs or ""))
    pruned = "db/memeradar/%s.json" % hour_id(S.T0 - 31 * D)
    left = {rel: os.path.exists(os.path.join(db_, rel)) and raw(os.path.join(db_, rel)) == b for rel, b in put.items()}
    check(pb.returncode == 0 and not os.path.exists(os.path.join(db_, pruned)) and all(ok for rel, ok in left.items() if rel != pruned)
          and os.path.exists(os.path.join(da, "report.html")) and os.path.exists(os.path.join(db_, "report.html")),
          "the cycle leaves the radar's files as they were (the page's inputs), prunes the radar doc older than 30 days and keeps the 400-day-old"
          " peak doc; both cycles build the page")


def _s3(check, tmp):
    print("== scan side S3: memepeak and memeradar travel to the results branch; the radar docs leave it after 30 days, the peak docs never")
    import bot as B
    lines = B.SYNC_IGNORE.splitlines()
    check(all(l in lines for l in WP4_IGNORE) and lines.index("!db/memeradar/") < lines.index("!db/memeradar/**") and B.KEEP_RADAR_DAYS == 30
          and not any(l in lines for l in ("!radar_live.json", "!walletmem.json.gz", "!xlinks.json.gz")),
          "SYNC_IGNORE lets db/memepeak and db/memeradar through (and not the page-only inputs radar_live.json, walletmem, xlinks)")
    rng = random.Random(47)
    now = int(time.time() * 1000)
    d = os.path.join(tmp, "s3")
    docs = {"db/memeradar/a-29d.json": {"v": 1, "t": now - 29 * D}, "db/memeradar/b-31d.json": {"v": 1, "t": now - 31 * D},
            "db/memepeak/c-400d.json": {"v": 1, "t": now - 400 * D}, "db/memepeak/d-new.json": {"v": 1, "t": now - H},
            "db/memeearly/e-31d.json": {"v": 1, "t": now - 31 * D}}
    for rel, obj in docs.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
        json.dump(obj, open(os.path.join(d, rel), "w"))
    for rel, raw in (("radar_live.json", b"{}"), ("walletmem.json.gz", gz({"v": 1})), ("xlinks.json.gz", gz({"v": 1})), (".radartmp/x.json", b"{}"),
                     (".radar_feed_import", b"ok"), ("report.html", b"<html>page</html>"), ("db/memebot/state.json", b"{}")):
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        open(os.path.join(d, rel), "wb").write(raw)
    bare = os.path.join(tmp, "s3.git")
    git("init", "-q", "--bare", bare)
    with contextlib.redirect_stderr(open(os.devnull, "w")):
        B.sync(d, remote=bare)
    ls1 = set(git("-C", bare, "ls-tree", "-r", "--name-only", "results").split())
    with contextlib.redirect_stderr(open(os.devnull, "w")):
        gone = B.prune(d, now)
        B.sync(d, remote=bare)
    ls2 = set(git("-C", bare, "ls-tree", "-r", "--name-only", "results").split())
    left = {rel for rel in docs if os.path.exists(os.path.join(d, rel))}
    check(gone == 2 and left == {"db/memeradar/a-29d.json", "db/memepeak/c-400d.json", "db/memepeak/d-new.json"},
          "prune removes the radar doc of 31 days (and the early doc of 31 days, as before), keeps the one of 29 days and both peak docs, a"
          " 400-day-old one too (%d removed)" % gone)
    page_only = {"radar_live.json", "walletmem.json.gz", "xlinks.json.gz", ".radartmp/x.json", ".radar_feed_import"}
    check({"db/memeradar/a-29d.json", "db/memeradar/b-31d.json", "db/memepeak/c-400d.json", "db/memepeak/d-new.json", "report.html"} <= ls1 and not ls1 & page_only
          and "db/memeradar/b-31d.json" not in ls2 and {"db/memeradar/a-29d.json", "db/memepeak/c-400d.json"} <= ls2 and not ls2 & page_only,
          "sync carries memepeak and memeradar to the results branch and never the page-only inputs (nor step A's mark); the pruned radar doc"
          " leaves the branch at the"
          " next sync (%d files, then %d)" % (len(ls1), len(ls2)))


def _app_env(tmp):
    """(env for a process with the app's live store, Rest, PushSink, server, sub maker) or None without cryptography."""
    import importlib.util
    if importlib.util.find_spec("cryptography") is None:
        return None
    import selftest as S
    rest, sink = S.Rest(), S.PushSink()
    srv = S.serve_app(rest, sink)
    sb = "http://127.0.0.1:%d" % srv.server_address[1]
    fake = os.path.join(tmp, "fakepush")
    os.makedirs(fake, exist_ok=True)
    with open(os.path.join(fake, "pywebpush.py"), "w") as f:
        f.write(S.FAKE_PYWEBPUSH)
    real = importlib.util.find_spec("pywebpush") is not None and importlib.util.find_spec("http_ece") is not None
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_"))}
    base.update(PYTHONUTF8="1", MEMEBOT_PAUSE="0")
    env = dict(base, SUPABASE_URL=sb, SUPABASE_SECRET_KEY=S.APP_SECRET)
    if not real:
        env["PYTHONPATH"] = fake + os.pathsep + base.get("PYTHONPATH", "")

    def sub(name):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        k = ec.generate_private_key(ec.SECP256R1())
        auth = os.urandom(16)
        if real:
            sink.keys[name] = (k, auth)
        p256 = S.b64u(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        return {"endpoint": sb + "/push/" + name, "expirationTime": None, "keys": {"p256dh": p256, "auth": S.b64u(auth)}}
    return env, rest, sink, srv, sub


def _drive(code, env, timeout=120):
    p = subprocess.run([sys.executable, "-c", "import sys, json, time, os; sys.path.insert(0, %r)\n" % HERE + code], capture_output=True, text=True, env=env, timeout=timeout)
    try:
        out = json.loads((p.stdout.strip().splitlines() or ["null"])[-1])
    except ValueError:
        out = None
    return p, out


def _s4(check, scan, tmp):
    print("== scan side S4: the scan's \"new coins\" push is off unless MEMEBOT_PUSH_YOUNG=1")
    code = ("import bot\ncalls = []\nbot.app_bg = lambda name, *a: calls.append([name] + [x.get('t') for x in a]) or True\n"
            "bot.OFFICE = bot.Office(None, 777)\ny = {'v': 1, 't': 777, 'state': 'listed', 'coins': [{'sym': 'NEW1', 'ageMin': 3}]}\n"
            "out = []\nfor v in (None, '0', 'true', 'yes', '1', '1'):\n"
            "    if v is None:\n        os.environ.pop('MEMEBOT_PUSH_YOUNG', None)\n    else:\n        os.environ['MEMEBOT_PUSH_YOUNG'] = v\n"
            "    out.append(bot.young_published(y))\n"
            "bot.YOUNG_SENT['t'] = None\nos.environ['MEMEBOT_PUSH_YOUNG'] = '1'\nempty = bot.young_published(dict(y, coins=[]))\n"
            "print(json.dumps([out, calls, empty]))\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_"))}
    p, out = _drive(code, env)
    check(out == [[False, False, False, False, True, False], [["notify_young", 777]], False],
          "young_published: unset, 0, true or yes send nothing; 1 sends the notification once per cycle as before (a second call and an empty list"
          " send none) (%s)" % (out if out is not None else p.stderr[-300:]))
    a = _app_env(tmp)
    if a is None:
        skip("S4 end to end through app.py (cryptography is not installed here)")
    else:
        env_app, rest, sink, srv, sub = a
        s_ = sub("phone")
        rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": {"young": True, "pick": True}}
        code = ("import bot\nbot.OFFICE = bot.Office(None, 4242)\ny = {'v': 1, 't': 4242, 'state': 'listed', 'coins': [{'sym': 'NEW1', 'ageMin': 3}]}\n"
                "r = bot.young_published(y)\nfor t in list(bot.APP_JOBS): t.join(30)\nprint(json.dumps(r))\n")
        got = []
        for flag in (None, "1"):
            g0 = len(sink.got)
            p, out = _drive(code, dict(env_app, **({"MEMEBOT_PUSH_YOUNG": flag} if flag else {})))
            got.append((out, len([g for g in sink.got[g0:] if '"tag":"young"' in g["data"]])))
        srv.shutdown()
        srv.server_close()
        check(got == [(False, 0), (True, 1)],
              "end to end with the app's live store and a phone that wants new coins: no push by default, one push with MEMEBOT_PUSH_YOUNG=1 (%s)" % got)
    if scan:
        env_ = (step(scan["jobs"]["scan"], "Scan and recommend") or {}).get("env") or {}
        check(env_.get("MEMEBOT_PUSH_YOUNG") == "${{ vars.MEMEBOT_PUSH_YOUNG || '0' }}",
              "scan.yml passes MEMEBOT_PUSH_YOUNG to the scan step from the repository variable, 0 when it is not set (%s)" % env_.get("MEMEBOT_PUSH_YOUNG"))


def _s5(check, tmp):
    print("== scan side S5: the radar's push kind, the New coins switch covers it, its words")
    import app as A
    coin = {"addr": "HiRE" + "1" * 40, "sym": "HIRE", "age": 6.1, "liq": 23_400, "n": 9, "v": "good"}
    texts = []
    saved = A.notify
    try:
        A.notify = lambda kind, title, body, url=None: texts.append((kind, title, body, url)) or {"kind": kind}
        inf = float("inf")
        variants = [[coin], [coin, dict(coin, sym="TWO")], [dict(coin, age=0.3, liq=1_234_567, n=None, sym="X\x07<b>Y")], [dict(coin, age=None, liq=None, sym=None)],
                    [dict(coin, sym="Buy Safe Clean")], [dict(coin, age=inf, n=inf, liq=inf)], [dict(coin, age=-inf, n=float("nan"), liq=-inf)]]
        for v in variants:
            A.notify_radar(v)
        empty = [A.notify_radar([]), A.notify_radar(None), A.notify_radar(["x", 3])]
    finally:
        A.notify = saved
    words = [t + " " + b for _, t, b, _ in texts[:4]]
    check(A.KINDS.get("radar") == (600, "high", 60) and A.PREF_OF == {"radar": "young"} and all(A.KINDS.get(k) == v for k, v in (("young", (1800, "normal", 300)), ("pick", (3600, "high", 300)))),
          "app.KINDS['radar'] = (600 s TTL, high urgency, 60 s gap); PREF_OF maps radar to the phone's young switch; young and pick unchanged")
    check(len(texts) == 7 and texts[0][1:] == ("HIRE: no trap found (pool 6 min)", "9 checks passed · liquidity $23k · fake money, nothing is bought.", "#tab-radar")
          and texts[1][1] == "HIRE: no trap found (pool 6 min) +1 more" and texts[2][1] == "X<b>Y: no trap found (pool <1 min)"
          and texts[2][2] == "All checks passed · liquidity $1.2M · fake money, nothing is bought." and texts[3][1] == "?: no trap found"
          and all(k == "radar" and u == "#tab-radar" and b.endswith("fake money, nothing is bought.") for k, _, b, u in texts)
          and not any(NO_WORDS.search(w) for w in words) and empty == [{"skipped": "no coins"}] * 3,
          "notify_radar: \"%s\" / \"%s\"; a second coin is \"+1 more\"; every body ends \"fake money, nothing is bought.\", no buy, safe, clean"
          " or em dash in our words; an empty list sends nothing" % texts[0][1:3])
    unknown = ("radar", "HIRE: no trap found", "All checks passed · liquidity unknown · fake money, nothing is bought.", "#tab-radar")
    check(texts[5:] == [unknown, unknown],
          "notify_radar: an infinite or NaN age, check count or liquidity reads as unknown (no pool age, \"All checks passed\", liquidity unknown),"
          " never an error or \"$infM\" (%s)" % [t[1:3] for t in texts[5:]])
    a = _app_env(tmp)
    if a is None:
        skip("S5 pushes through app.py (cryptography is not installed here)")
        return
    env_app, rest, sink, srv, sub = a
    for name, prefs in (("both", {"young": True, "pick": True}), ("noYoung", {"young": False, "pick": True}), ("legacy", {}), ("noPick", {"young": True, "pick": False})):
        s_ = sub(name)
        rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": prefs}
    code = ("import app\nc = json.loads(%r)\n" % json.dumps(coin) +
            "r1 = app.notify_radar([c, dict(c, sym='TWO')])\nr2 = app.notify_radar([c])\nr3 = app.notify('radar', 'x', 'y')\nprint(json.dumps([r1, r2, r3]))\n")
    g0 = len(sink.got)
    p, out = _drive(code, env_app)
    srv.shutdown()
    srv.server_close()
    got = [g for g in sink.got[g0:] if '"tag":"radar"' in g["data"]]
    names = sorted(g["name"] for g in got)
    j = json.loads(next((g["data"] for g in got if g["name"] == "both"), "{}") or "{}")
    n_ = j.get("notification") or {}
    hd = next((g["headers"] for g in got if g["name"] == "both"), {})
    check(out and names == ["both", "legacy", "noPick"] and out[0].get("sent") == 3 and out[1].get("skipped") == "rate guard" and out[2].get("skipped") == "rate guard"
          and A.KINDS["radar"][2] == 60,
          "through app.py to a local push service: a phone with New coins off gets no radar push, one without settings and one with pick off do;"
          " a second radar push within 60 s is held back by the rate guard (%s)" % names)
    check(n_.get("title") == "HIRE: no trap found (pool 6 min) +1 more" and n_.get("body") == "9 checks passed · liquidity $23k · fake money, nothing is bought."
          and str(n_.get("navigate", "")).endswith("/Meme-Bot/#tab-radar") and hd.get("ttl") == "600" and hd.get("urgency") == "high" and hd.get("topic") == "radarhit"
          and not NO_WORDS.search(n_.get("title", "") + " " + n_.get("body", "")) and _app_secret() not in p.stdout + p.stderr,
          "the radar push: Declarative Web Push with the words above, TTL 600, Urgency high, Topic radarhit, opening the Radar tab; no key in the output")


def _app_secret():
    import selftest as S
    return S.APP_SECRET


class GH:
    """A stand-in for GitHub's API as step D uses it: the radar workflow's state, its runs, the dispatch."""

    def __init__(self):
        self.state, self.wf_code, self.runs, self.dispatch_code, self.log, self.lock = "active", 200, [], 204, [], threading.Lock()

    def handle(self, method, path, headers, body):
        with self.lock:
            self.log.append({"m": method, "p": path, "auth": headers.get("Authorization"), "body": body})
        base = "/repos/own/repo/actions/workflows/radar.yml"
        u = urllib.parse.urlsplit(path)
        if method == "GET" and u.path == base:
            return self.wf_code, ({"id": 7, "path": ".github/workflows/radar.yml", "state": self.state} if self.wf_code == 200 else {"message": "Not Found"})
        if method == "GET" and u.path == base + "/runs":
            return 200, {"total_count": len(self.runs), "workflow_runs": self.runs}
        if method == "POST" and u.path == base + "/dispatches":
            return self.dispatch_code, None
        return 404, {"message": "Not Found"}


def serve_gh(gh):
    class Hd(BaseHTTPRequestHandler):
        def _go(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            code, out = gh.handle(self.command, self.path, self.headers, body.decode("utf-8") if body else "")
            raw = json.dumps(out).encode() if out is not None else b""
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        do_GET = do_POST = _go

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


STANDIN_PEAK = '''"""A stand-in for peak.py run (the peak category's own package; its pricing is checked by P1 to P7): one settled doc, one candle file;
it says whether the token reached its environment."""
import json, os, sys
d = sys.argv[sys.argv.index("--dir") + 1]
os.makedirs(os.path.join(d, "db", "memepeak"), exist_ok=True)
os.makedirs(os.path.join(d, "candles"), exist_ok=True)
json.dump({"v": 1, "pos": "y-1", "state": "ok", "x": 3.2}, open(os.path.join(d, "db", "memepeak", "y-1.json"), "w"))
open(os.path.join(d, "candles", "Pool_pk1.txt"), "w").write("1|1|1|1|1|30\\n")
print(json.dumps({"items": 1, "ok": 1, "deadline": sys.argv[sys.argv.index("--deadline-s") + 1],
                  "token": "RESULTS_URL" in os.environ or any("x-access-token" in v for v in os.environ.values())}))
'''


def _peaks_job(check, scan, tmp):
    """Job peaks as written (its restore, a stand-in pricing step, its sync) against a local results remote."""
    import bot as B
    pk = scan["jobs"]["peaks"]
    remote = os.path.join(tmp, "s6-peaks.git")
    git("init", "-q", "--bare", remote)
    url = "file://" + remote
    src = os.path.join(tmp, "s6-scan-mb")           # what the scan job pushed a minute before
    for rel, raw in (("report.html", b"<html>scan</html>"), ("db/memepos/y-1.json", b'{"grp":"young","t":1}'), ("db/memepeak/y-0.json", b'{"v":1,"pos":"y-0"}')):
        os.makedirs(os.path.dirname(os.path.join(src, rel)) or src, exist_ok=True)
        open(os.path.join(src, rel), "wb").write(raw)
    with contextlib.redirect_stderr(open(os.devnull, "w")):
        B.sync(src, remote=url)
    scan_head = git("-C", remote, "rev-parse", "refs/heads/results").strip()
    ws = os.path.join(tmp, "s6-peaks-ws")
    os.makedirs(ws)
    os.symlink(os.path.join(HERE, "bot.py"), os.path.join(ws, "bot.py"))
    open(os.path.join(ws, "peak.py"), "w").write(STANDIN_PEAK)
    outf = os.path.join(tmp, "s6-peaks-output")
    open(outf, "w").close()
    logs, codes, priced = [], [], {}
    for st in pk["steps"][1:]:
        if "steps.restore.outputs.ok == 'true'" in str(st.get("if")) and "ok=true" not in open(outf).read():
            continue
        env = dict(pk.get("env") or {}, **(st.get("env") or {}))
        if "RESULTS_URL" in env:                     # the token's address, only where the workflow gives it (the restore and the push)
            env["RESULTS_URL"] = url
        p, _ = run_script(st["run"], ws, dict(env, GITHUB_OUTPUT=outf, PYTHONUTF8="1"))
        codes.append(p.returncode)
        logs.append((p.stdout + p.stderr).strip().splitlines()[-1:] or [""])
        if "peak.py run" in st["run"]:
            try:
                priced = json.loads(logs[-1][0])
            except ValueError:
                priced = {}
    head = git("-C", remote, "rev-parse", "-q", "--verify", "refs/heads/results", check=False).strip()
    parent = git("-C", remote, "rev-parse", "-q", "--verify", "refs/heads/results^", check=False).strip()     # none when the job added no commit
    ls = set(git("-C", remote, "ls-tree", "-r", "--name-only", "results", check=False).split())
    print("  " + "\n  ".join(l[0][:160] for l in logs))
    empty = os.path.join(tmp, "s6-peaks-empty.git")
    git("init", "-q", "--bare", empty)
    ws2 = os.path.join(tmp, "s6-peaks-ws2")
    os.makedirs(ws2)
    out2 = os.path.join(tmp, "s6-peaks-output2")
    open(out2, "w").close()
    p2, _ = run_script(pk["steps"][1]["run"], ws2, dict(RESULTS_URL="file://" + empty, GITHUB_OUTPUT=out2))
    check(codes == [0, 0, 0] and bool(parent) and parent == scan_head and head != scan_head
          and {"db/memepeak/y-0.json", "db/memepeak/y-1.json", "db/memepos/y-1.json", "report.html"} <= ls
          and not any(x.startswith("candles/") for x in ls) and p2.returncode == 0 and "ok=true" not in open(out2).read() and not os.path.exists(os.path.join(ws2, "mb")),
          "job peaks as written: it clones the results the scan just pushed, prices (a stand-in here), and its sync adds the peak doc as one commit on"
          " top of the scan's (the candle files stay on the runner); without a results branch it prices nothing and pushes nothing")
    check(priced.get("items") == 1 and priced.get("token") is False and "RESULTS_URL" not in (pk.get("env") or {})
          and [bool((s.get("env") or {}).get("RESULTS_URL")) for s in pk["steps"]] == [False, True, False, True],
          "job peaks: the token's address is only in the restore and the push step; the pricing step (GeckoTerminal only) runs without it")


def berlin_hour():
    from zoneinfo import ZoneInfo
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo("Europe/Berlin")).hour


def _round_start(check, job, tmp):
    st = step(job, "Start one launch radar round")
    gh = GH()
    srv = serve_gh(gh)
    api = "http://127.0.0.1:%d" % srv.server_address[1]
    ws = os.path.join(tmp, "s6ws")
    os.makedirs(ws, exist_ok=True)
    h = berlin_hour()
    inside = "%d-%d" % (h, h + 2) if h + 2 <= 24 else "%d-%d" % (h, (h + 2) % 24)
    outside = "%d-%d" % ((h + 2) % 24, ((h + 3) % 24) or 24)
    env0 = dict(st.get("env") or {}, GH_TOKEN=FAKE_TOKEN, GITHUB_API_URL=api, GITHUB_REPOSITORY="own/repo", RADAR_REF="main", MEMEBOT_RADAR_HOURS=inside)
    cases = []

    def go(label, **kw):
        n0 = len(gh.log)
        env = dict(env0, **{k: v for k, v in kw.items() if k.isupper()})
        p, secs = run_script(st["run"], ws, env, timeout=60)
        calls = gh.log[n0:]
        cases.append((label, p, calls, secs))
        return p, calls
    gh.runs = [{"id": 1, "status": "completed", "conclusion": "success"}, {"id": 2, "status": "completed", "conclusion": "cancelled"}]
    p1, c1 = go("idle")
    alive = {}
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        gh.runs = [{"id": 3, "status": status}, {"id": 1, "status": "completed", "conclusion": "success"}]
        alive[status] = go(status)
    gh.runs = []
    gh.state = "disabled_manually"
    p3, c3 = go("disabled")
    gh.state, gh.wf_code = "active", 404
    p4, c4 = go("missing")
    gh.wf_code = 200
    p5, c5 = go("outside", MEMEBOT_RADAR_HOURS=outside)
    wrap = "%d-1" % h if h >= 2 else "23-%d" % (h + 2)      # a window that wraps past midnight and holds now (and the next hour)
    p6, c6 = go("wrap", MEMEBOT_RADAR_HOURS=wrap)
    gh.dispatch_code = 422
    p7, c7 = go("refused")
    gh.dispatch_code = 204
    srv.shutdown()
    srv.server_close()
    p8, _ = go("down", GITHUB_API_URL="http://127.0.0.1:9")
    for label, p, calls, secs in cases:
        print("  %-11s %s" % (label, (p.stdout.strip() or p.stderr.strip()[-200:])))
    disp = [c for c in c1 if c["m"] == "POST"]
    body = json.loads(disp[0]["body"]) if disp else {}
    check(p1.returncode == 0 and [c["m"] for c in c1] == ["GET", "GET", "POST"] and c1[1]["p"].endswith("/runs?per_page=20") and body == {"ref": "main", "inputs": {"source": "hourly"}}
          and all(c["auth"] == "Bearer " + FAKE_TOKEN for c in c1) and "started the radar (source hourly" in p1.stdout and len(disp) == 1,
          "step D: with the radar workflow active, inside the hours (%s Berlin) and every radar run completed, it starts ONE run of radar.yml"
          " on this branch, source hourly, no minutes (3 API calls, the token in the Authorization header only)" % inside)
    check(all(p.returncode == 0 and not [c for c in calls if c["m"] == "POST"] and len(calls) == 2 and ("still going (%s): no second one" % s_) in p.stdout for s_, (p, calls) in alive.items()),
          "a radar run that is queued, in progress, waiting, pending or requested is still going: no second round (C4)")
    check(p3.returncode == 0 and len(c3) == 1 and "disabled_manually" in p3.stdout and p4.returncode == 0 and len(c4) == 1 and "not on this branch" in p4.stdout
          and p5.returncode == 0 and not c5 and "outside the active hours" in p5.stdout and p6.returncode == 0 and [c["m"] for c in c6] == ["GET", "GET", "POST"]
          and p7.returncode == 0 and "refused (HTTP 422)" in p7.stdout and p8.returncode == 0 and "did not answer" in p8.stdout,
          "a disabled workflow (Disable workflow, the stop switch) or a missing radar.yml: no start after one call; outside the hours (%s): no call at all;"
          " a window wrapping past midnight (%s) starts it; a refused start or GitHub down: one line, exit 0" % (outside, wrap))
    check(all(FAKE_TOKEN not in p.stdout + p.stderr for _, p, _, _ in cases) and all(secs < 30 for _, _, _, secs in cases),
          "step D never prints the token and ends within its minute in every case (slowest %.1f s)" % max(secs for _, _, _, secs in cases))
    # step D's hours rule is the radar's own (launch_radar.parse_hours), when that module is on this branch
    m = re.search(r"(def hours\(s\):.*?return a, b\n)", st["run"], re.S)
    ns = {"re": re}
    exec(compile(m.group(1) if m else "", "step-d-hours", "exec"), ns)
    samples = ["7-24", "0-24", "22-6", "5-5", "24-24", "25-3", "abc", "", None, " 8 - 23 ", "0-0", "23-24", "7-25", "-1-4"]
    mine = [ns["hours"](x) for x in samples] if "hours" in ns else []
    want = [(7, 24), (0, 24), (22, 6), (0, 24), (0, 24), (7, 24), (7, 24), (7, 24), (7, 24), (8, 23), (0, 24), (23, 24), (7, 24), (7, 24)]
    if os.path.exists(os.path.join(HERE, "launch_radar.py")):
        import importlib
        LR = importlib.import_module("launch_radar")
        theirs = [LR.parse_hours(x) for x in samples]
        check(mine == theirs == want, "step D reads MEMEBOT_RADAR_HOURS exactly as the radar does (launch_radar.parse_hours): %s" % list(zip(samples, mine))[:6])
    else:
        check(mine == want, "step D reads MEMEBOT_RADAR_HOURS as the radar's spec says (a-b Berlin, wrap past midnight, a-a all day, else 7-24)")
        skip("S6 parity of the hours rule with launch_radar.parse_hours (launch_radar.py of WP3 is not on this branch)")


def _s6(check, scan, tmp):
    print("== scan side S6: scan.yml and radar.yml, parsed as YAML; step D (one radar round) against a stand-in GitHub API")
    job = scan["jobs"]["scan"]
    cache = step(job, "Keep the big-test snapshots between runs")
    check(cache == CACHE_STEP, "the cache step is unchanged: the same paths, key and restore-keys, so the old caches stay restorable (I9)")
    names = [s.get("name") or s.get("uses") or "" for s in job["steps"]]
    pos = [step_index(job, n) for n in BASE_STEPS]
    a, b, d_ = (step_index(job, n) for n in ("Import the launch radar's records", "Feed the launch radar", "Start one launch radar round"))
    sa, sb, sd = (job["steps"][i] if i >= 0 else {} for i in (a, b, d_))
    check(scan.get("concurrency") == {"group": "memebot-scan", "cancel-in-progress": False} and scan.get("permissions") == {"contents": "write", "actions": "write"}
          and all(x >= 0 for x in pos) and pos == sorted(pos) and len(names) == len(BASE_STEPS) + 3 and job.get("timeout-minutes") == 55,
          "every step of the scan job from before is still there, in its order, plus three new ones; the workflow-level group and permissions are unchanged")
    check(pos[2] < a < pos[3] and b == pos[7] + 1 and d_ == len(names) - 1
          and sa.get("continue-on-error") is True and sa.get("timeout-minutes") == 1 and sa.get("if") == "steps.recent.outputs.skip != 'true'"
          and sb.get("continue-on-error") is True and sb.get("timeout-minutes") == 3 and sb.get("if") == "steps.recent.outputs.skip != 'true'"
          and sd.get("continue-on-error") is True and sd.get("timeout-minutes") == 1
          and sd.get("if") == "always() && steps.recent.outputs.skip != 'true' && (vars.MEMEBOT_RADAR || '1') != '0'"
          and (step(job, "Scan and recommend") or {}).get("run", "").strip() == 'python3 bot.py cycle --recommend --horizon "$HORIZON" $RESCAN',
          "step A sits after the restore and before the cache step, B right after the results push, D last; each is continue-on-error with a"
          " timeout (1, 3, 1 min); D runs even after a failed scan, never when MEMEBOT_RADAR is 0 (an unset variable counts as on); none is inside bot.py cycle")
    bt = step(job, "Export the big-test results to the bigtest branch") or {}
    check("tar -C mb/db -czf bt/memeradar.tgz memeradar" in (bt.get("run") or "") and "if [ -d mb/db/memeradar ]" in (bt.get("run") or ""),
          "step C: the daily bigtest export also packs db/memeradar (when there is one)")
    pk = scan["jobs"].get("peaks") or {}
    pst = pk.get("steps") or []
    restore_scan = (step(job, "Restore the bot's state from the results branch") or {}).get("run", "")
    restore_pk = (step(pk, "Restore the bot's state from the results branch") or {}).get("run", "")
    clone = next((l.strip() for l in restore_scan.splitlines() if "git clone" in l), "?")
    runs_pk = [s.get("run") or "" for s in pst]
    check(pk.get("needs") == "scan" and "needs.scan.outputs.skipped != 'true'" in str(pk.get("if")) and "needs.scan.result == 'success'" in str(pk.get("if"))
          and pk.get("continue-on-error") is True and isinstance(pk.get("timeout-minutes"), int) and pk["timeout-minutes"] <= 12 and pk.get("permissions") == {"contents": "write"}
          and (pst[:1] == [{"uses": "actions/checkout@v4", "with": {"persist-credentials": False}}]) and clone in restore_pk
          and any(r.strip() == "python3 peak.py run --dir mb --deadline-s 600" for r in runs_pk) and runs_pk[-1].strip() == 'python3 bot.py sync --remote "$RESULTS_URL"'
          and [i for i, r in enumerate(runs_pk) if "peak.py run" in r] == [len(runs_pk) - 2],
          "job peaks: needs scan (not after a skipped or failed scan), continue-on-error, %s min at most, contents write only; checkout (no token kept), the scan's"
          " results clone, peak.py run --deadline-s 600, then bot.py sync" % pk.get("timeout-minutes"))
    pushes = [(s.get("name") or s.get("uses"), l.strip()) for j in scan["jobs"].values() for s in j.get("steps") or [] for l in (s.get("run") or "").splitlines() if "git push" in l]
    check(len(pushes) == 2 and not any("radar-data" in l for _, l in pushes) and all(re.search(r"\b(bigtest|radar-feed)\b", l) for _, l in pushes),
          "no step of scan.yml pushes radar-data (the radar job is its only writer); the git pushes go to bigtest and radar-feed (%d), results via bot.py sync" % len(pushes))
    _peaks_job(check, scan, tmp)
    _round_start(check, job, tmp)
    try:
        radar = load_yaml(RADAR_YML)
    except ImportError:
        radar = None
    if radar is None:
        skip("S6 radar.yml lint (radar.yml of WP3 is not on this branch)")
        return
    rjobs = radar.get("jobs") or {}
    rj = rjobs.get("radar") or {}
    text = open(RADAR_YML, encoding="utf-8").read()
    code = [l.split(" #")[0] for l in text.splitlines() if not l.strip().startswith("#")]        # the workflow without its comments
    push_lines = [l for l in code if re.search(r"\bgit\b.*\bpush\b", l) or re.search(r"refs/heads/", l)]
    steps_ = rj.get("steps") or []
    lp = [s_ for s_ in steps_ if (s_.get("run") or "").strip() == "python3 launch_radar.py loop --dir rd --cadence 300 --deadline 125 --minutes 55"]
    nx = [s_ for s_ in steps_ if "/dispatches" in (s_.get("run") or "")]
    check((radar.get("concurrency") or {}).get("group") == "memebot-radar" and (radar.get("concurrency") or {}).get("cancel-in-progress") is False
          and on_keys(radar) == {"workflow_dispatch"} and "schedule" not in text.split("jobs:")[0] and rj.get("timeout-minutes") == 70
          and set(((radar.get("on") or radar.get(True) or {}).get("workflow_dispatch") or {}).get("inputs") or {}) == {"source"}
          and len(lp) == 1 and lp[0].get("id") == "loop" and lp[0].get("timeout-minutes") == 62
          and len(nx) == 1 and nx[0].get("if") == "steps.loop.outcome == 'success'" and nx[0].get("continue-on-error") is True and nx[0].get("timeout-minutes") == 1
          and steps_.index(nx[0]) > steps_.index(lp[0]) and "secrets." not in json.dumps(nx[0].get("env") or {})
          and not any(re.search(r"\b(results|live|radar-feed)\b", l) for l in push_lines)
          and "memebot-scan" not in json.dumps(radar.get("concurrency")),
          "radar.yml: group memebot-radar (never memebot-scan), started by workflow_dispatch only (no schedule, input source only), a round every"
          " 5 minutes for 55 minutes (launch_radar.py loop, step timeout 62, job 70), then one soft step that starts the next run (only after a loop"
          " that ended well, the job's own token, no secret), no push to results, live or radar-feed")
    if nx:
        _chain_start(check, rj, nx[0], tmp)


def _chain_start(check, rj, st, tmp):
    """radar.yml's last step against the stand-in GitHub API: the next run (source auto) when only this run is going, none while another
    waits, none outside the hours, none when the workflow is disabled, one line and exit 0 when GitHub is down; never the token."""
    gh = GH()
    srv = serve_gh(gh)
    api = "http://127.0.0.1:%d" % srv.server_address[1]
    h = berlin_hour()
    inside = "%d-%d" % (h, h + 2) if h + 2 <= 24 else "%d-%d" % (h, (h + 2) % 24)
    outside = "%d-%d" % ((h + 2) % 24, ((h + 3) % 24) or 24)
    env0 = dict(rj.get("env") or {}, **(st.get("env") or {}))
    env0.update(GH_TOKEN=FAKE_TOKEN, GITHUB_API_URL=api, GITHUB_REPOSITORY="own/repo", RADAR_REF="main", MEMEBOT_RADAR_HOURS=inside, GITHUB_RUN_ID="30")
    res = {}

    def go(label, **kw):
        n0 = len(gh.log)
        p, secs = run_script(st["run"], HERE, dict(env0, **kw), timeout=60)      # the checkout: the step reads the hours rule from launch_radar.py
        res[label] = (p, gh.log[n0:], secs)
    gh.runs = [{"id": 30, "status": "in_progress"}, {"id": 29, "status": "completed", "conclusion": "success"}]
    go("alone")
    gh.runs = [{"id": 30, "status": "in_progress"}, {"id": 31, "status": "pending"}]
    go("waiting")
    gh.runs = [{"id": 30, "status": "in_progress"}]
    go("outside", MEMEBOT_RADAR_HOURS=outside)
    gh.state = "disabled_manually"
    go("disabled")
    gh.state = "active"
    srv.shutdown()
    srv.server_close()
    go("down", GITHUB_API_URL="http://127.0.0.1:9")
    for label, (p, calls, secs) in res.items():
        print("  next run %-9s %s" % (label, (p.stdout.strip() or p.stderr.strip()[-200:])))
    p, calls, _ = res["alone"]
    disp = [c for c in calls if c["m"] == "POST"]
    body = json.loads(disp[0]["body"]) if disp else {}
    check(p.returncode == 0 and [c["m"] for c in calls] == ["GET", "GET", "POST"] and body == {"ref": "main", "inputs": {"source": "auto"}}
          and "started (source auto)" in p.stdout and all(c["auth"] == "Bearer " + FAKE_TOKEN for c in calls),
          "radar.yml's last step: with only this run going (its own run in progress is not 'another run'), inside the hours and the workflow"
          " active, it starts the next run (source auto) on this branch (3 API calls)")
    pw, cw, _ = res["waiting"]
    po, co, _ = res["outside"]
    pd, cd, _ = res["disabled"]
    pn, _, _ = res["down"]
    check(pw.returncode == 0 and not [c for c in cw if c["m"] == "POST"] and "another radar run" in pw.stdout and po.returncode == 0 and not co
          and "hours" in po.stdout and pd.returncode == 0 and len(cd) == 1 and "not active" in pd.stdout and pn.returncode == 0 and "did not answer" in pn.stdout
          and all(FAKE_TOKEN not in p_.stdout + p_.stderr for p_, _, _ in res.values()) and all(s_ < 30 for _, _, s_ in res.values()),
          "radar.yml's last step: no second run while another waits (a start by hand goes on as the next run), no call outside the hours, one call"
          " when the workflow is disabled (the stop switch), one line and exit 0 when GitHub is down; never the token, within its minute")


def _mock_mb(d, now, rng, n_docs=60, per_doc=200):
    """A mock db for traps.feed: scored snapshot chunks with holder lists, outcomes and euros, pump.fun rows with X links, pairs.json, run docs."""
    wallets = [b58(rng) for _ in range(3000)]
    common = wallets[:3]
    os.makedirs(os.path.join(d, "db", "memesnapres"), exist_ok=True)
    os.makedirs(os.path.join(d, "db", "memeruns"), exist_ok=True)
    os.makedirs(os.path.join(d, "pf"), exist_ok=True)
    for i in range(n_docs):
        t0 = now - (n_docs - i) * 2 * H
        coins = []
        for _ in range(per_doc):
            mult = rng.choice([0.02, 0.05, 0.4, 0.9, 1.1, 2.5, 6.0])
            coins.append({"a": b58(rng), "mult": mult, "gone": mult < 0.03, "eur": round((mult - 1) * 20, 2),
                          "rc": {"holders": [rng.choice(common)] + rng.sample(wallets, 9)}})
        json.dump({"t0": t0, "t": t0 + 2 * H, "coins": coins}, open(os.path.join(d, "db", "memesnapres", "s%03d.json" % i), "w"))
    for k in range(3):                       # the newest run doc's time is the scan's clock (a run doc whose time is no number is ignored)
        json.dump({"t": now - (2 - k) * H, "mode": "full"}, open(os.path.join(d, "db", "memeruns", "r%d.json" % k), "w"))
    json.dump({"t": "later", "mode": "x"}, open(os.path.join(d, "db", "memeruns", "zz-bad.json"), "w"))
    import fetch as F
    rows = [F.row(b58(rng, 40) + "pump", "S%d" % j, "Coin %d" % j, 90000, 50, 180000, 3, False, True, now - j * 600_000, "https://x.com/coin%d" % (j % 7), None, None)
            for j in range(40)]
    open(os.path.join(d, "pf", "graduated.txt"), "w").write("\n".join(rows) + "\n")
    json.dump([], open(os.path.join(d, "pairs.json"), "w"))
    return now


STANDIN_TRAPS = '''"""A stand-in for traps.py feed (the rule core of another package, not on this branch): the four files, the scan's clock in meta.json,
the X-link index merged with the previous <dir>/xlinks.json.gz (as the real feed does)."""
import gzip, json, os, sys
a = sys.argv
d, out, now = a[a.index("--dir") + 1], a[a.index("--out") + 1], int(a[a.index("--now") + 1])
if os.environ.get("STANDIN_FAIL"):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "walletmem.json.gz"), "wb").write(gzip.compress(b"{}"))
    sys.exit(1)
try:
    prev = json.loads(gzip.decompress(open(os.path.join(d, "xlinks.json.gz"), "rb").read()))
except (OSError, EOFError, ValueError):
    prev = None
links = prev["links"] if isinstance(prev, dict) and prev.get("v") == 1 and isinstance(prev.get("links"), dict) else {}
os.makedirs(out, exist_ok=True)
for n, doc in (("walletmem.json.gz", {"v": 1, "t": now, "nCoins": 0, "common": [], "sw": {}, "rug": []}), ("xlinks.json.gz", {"v": 1, "t": now, "links": links}),
               ("symmc.json.gz", {"v": 1, "t": now, "sym": {}})):
    open(os.path.join(out, n), "wb").write(gzip.compress(json.dumps(doc).encode(), mtime=0))
if not os.environ.get("STANDIN_THREE"):        # STANDIN_THREE: a feed that ends well but wrote only three of the four files
    json.dump({"v": 1, "t": now, "files": {}}, open(os.path.join(out, "meta.json"), "w"))
print(json.dumps({"t": now}))
'''


def _xlink_keys(remote):
    raw = subprocess.run(["git", "-C", remote, "show", "radar-feed:xlinks.json.gz"], capture_output=True).stdout
    try:
        return set((json.loads(gzip.decompress(raw)) or {}).get("links") or {})
    except (OSError, EOFError, ValueError, AttributeError):
        return set()


def _s7(check, job, tmp):
    print("== scan side S7: step B feeds the launch radar: traps.py feed on the mock db, one orphan commit on radar-feed")
    rng = random.Random(53)
    wall = int(time.time() * 1000) // 60_000 * 60_000
    now = wall - 2 * H                       # the newest run doc two hours back, so the next scan's (one hour later) is still in the past
    ws = os.path.join(tmp, "s7ws")
    mb = os.path.join(ws, "mb")
    clock = _mock_mb(mb, now, rng)
    real = os.path.exists(os.path.join(HERE, "traps.py"))
    if real:
        for f in glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "*.json")):
            os.symlink(f, os.path.join(ws, os.path.basename(f)))
    else:
        open(os.path.join(ws, "traps.py"), "w").write(STANDIN_TRAPS)
        skip("S7 timing of the real traps.py feed (traps.py of WP1 is not on this branch): step B ran with a stand-in feed")
    remote = os.path.join(tmp, "s7.git")
    git("init", "-q", "--bare", remote)
    put_branch(remote, "results", {"report.html": b"<html>results</html>"}, tmp)
    res0 = git("-C", remote, "rev-parse", "refs/heads/results").strip()
    tip = lambda: git("-C", remote, "rev-parse", "-q", "--verify", "refs/heads/radar-feed", check=False).strip()
    pa0, _ = _import(job, ws, remote, tmp)                   # the first scan: no radar-feed yet, so step A's mark says none
    m0 = import_mark(mb)
    p, secs = _feed(job, ws, remote, tmp)
    print("  " + "\n  ".join((p.stdout.strip().splitlines() or ["-"])[-2:]) + ("" if p.returncode == 0 else "\n  " + p.stderr[-600:]))
    files = sorted(git("-C", remote, "ls-tree", "--name-only", "radar-feed", check=False).split())
    n_commits = git("-C", remote, "rev-list", "--count", "refs/heads/radar-feed", check=False).strip()
    meta = json.loads(git("-C", remote, "show", "radar-feed:meta.json", check=False) or "{}")
    local = {n: open(os.path.join(ws, "feed", n), "rb").read() for n in FEED_FILES if os.path.exists(os.path.join(ws, "feed", n))}
    pushed = {n: subprocess.run(["git", "-C", remote, "show", "radar-feed:" + n], capture_output=True).stdout for n in FEED_FILES}
    wm = json.loads(gzip.decompress(pushed["walletmem.json.gz"])) if pushed.get("walletmem.json.gz") else {}
    check(m0 == "none" and p.returncode == 0 and files == sorted(FEED_FILES) and n_commits == "1" and local == pushed and meta.get("t") == clock and wm.get("v") == 1
          and wm.get("t") == clock and "step A did not import" not in p.stderr and (not real or (wm.get("nCoins") == 60 * 200 and secs < 60)),
          "traps.py feed%s writes the four files in %.1f s (budget 60 s) at the scan's clock (the newest run doc's time), and radar-feed holds exactly them"
          " in one commit (step A's mark: none, a first feed)%s" % ("" if real else " (stand-in)", secs, " (walletmem from %d coins)" % wm.get("nCoins", 0) if real else ""))
    # the next scan: step A brings the index back (mark ok); a second orphan commit replaces the first; a run doc dated 5 h ahead is ignored
    first, k1 = tip(), _xlink_keys(remote)
    json.dump({"t": clock + H, "mode": "full"}, open(os.path.join(mb, "db", "memeruns", "r9.json"), "w"))
    json.dump({"t": wall + 5 * H, "mode": "full"}, open(os.path.join(mb, "db", "memeruns", "r9-ahead.json"), "w"))
    pa1, _ = _import(job, ws, remote, tmp)
    m1 = import_mark(mb)
    p2, _ = _feed(job, ws, remote, tmp)
    second, k2 = tip(), _xlink_keys(remote)
    meta2 = json.loads(git("-C", remote, "show", "radar-feed:meta.json", check=False) or "{}")
    n2 = git("-C", remote, "rev-list", "--count", "refs/heads/radar-feed", check=False).strip()
    check(m1 == "ok" and p2.returncode == 0 and second != first and n2 == "1" and meta2.get("t") == clock + H and k1 <= k2 and "step A did not import" not in p2.stderr,
          "the next scan (step A's mark ok) replaces it with one new commit (force-pushed, still 1 commit) at its clock (%+d min; a run doc dated"
          " 5 h ahead of the wall clock is ignored)" % ((meta2.get("t", 0) - clock) // 60_000))
    # step A could not fetch radar-feed (fresh runner, no index in mb/): step B fetches the index itself, so 30 days of X links survive
    planted = {"x.com/oldacct%d" % i: [b58(rng), clock - 3 * D, 1, "account", clock - 2 * D, []] for i in range(50)}
    put_branch(remote, "radar-feed", {"walletmem.json.gz": gz({"v": 1, "t": clock, "nCoins": 1, "common": [], "sw": {}, "rug": []}),
                                      "xlinks.json.gz": gz({"v": 1, "t": clock, "links": planted}), "symmc.json.gz": gz({"v": 1, "t": clock, "sym": {}}),
                                      "meta.json": b'{"v":1}'}, tmp)
    held = tip()
    shim = git_shim(tmp)
    with contextlib.suppress(FileNotFoundError):            # a fresh runner: no index in mb/ (gone already when step B wrote none)
        os.remove(os.path.join(mb, "xlinks.json.gz"))
    pa3, _ = _import(job, ws, remote, tmp, SHIM_FAIL="refs/heads/radar-feed", **shim)
    m3 = import_mark(mb)
    p4, _ = _feed(job, ws, remote, tmp)
    k4, after4 = _xlink_keys(remote), tip()
    print("  " + "\n  ".join(l for l in (p4.stderr.strip().splitlines()[:1] + p4.stdout.strip().splitlines()[-1:])))
    check(m3 == "failed" and p4.returncode == 0 and after4 != held and set(planted) <= k4 and "fetched it here instead" in p4.stderr,
          "step A could not fetch radar-feed (mark failed): step B fetches the X-link index itself and the new feed keeps all %d old links"
          " (%d of %d)" % (len(planted), len(set(planted) & k4), len(planted)))
    # step B cannot fetch it either: radar-feed is left as it is (one line, the step ends well)
    with contextlib.suppress(FileNotFoundError):            # a fresh runner: no index in mb/ (gone already when step B wrote none)
        os.remove(os.path.join(mb, "xlinks.json.gz"))
    pa5, _ = _import(job, ws, remote, tmp, SHIM_FAIL="refs/heads/radar-feed", **shim)
    p5, _ = _feed(job, ws, remote, tmp, SHIM_FAIL="refs/heads/radar-feed", **shim)
    print("  " + "\n  ".join(p5.stderr.strip().splitlines()[:1] + p5.stdout.strip().splitlines()[-1:]))
    check(import_mark(mb) == "failed" and p5.returncode == 0 and tip() == after4 and set(planted) <= _xlink_keys(remote)
          and "radar-feed left as it is" in p5.stdout and "could not be fetched here either" in p5.stderr and not os.path.exists(os.path.join(mb, "xlinks.json.gz")),
          "neither step A nor step B can fetch radar-feed: no feed from this scan alone, radar-feed keeps its last commit and its X links (one line)")
    # a feed that fails, or ends well with three of the four files: nothing is pushed; results is never touched
    kept = tip()
    bad_ws = os.path.join(tmp, "s7bad")
    os.makedirs(bad_ws)
    os.symlink(mb, os.path.join(bad_ws, "mb"))
    open(os.path.join(bad_ws, "traps.py"), "w").write(STANDIN_TRAPS)
    open(os.path.join(mb, ".radar_feed_import"), "w").write("ok")
    p6, _ = _feed(job, bad_ws, remote, tmp, STANDIN_FAIL="1")
    p7, _ = _feed(job, bad_ws, remote, tmp, STANDIN_THREE="1")
    heads = sorted(git("-C", remote, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    check(p6.returncode != 0 and p7.returncode != 0 and "did not write meta.json" in p7.stdout and tip() == kept
          and git("-C", remote, "rev-parse", "refs/heads/results").strip() == res0 and heads == ["radar-feed", "results"],
          "all four or none: a feed that fails, or ends well having written three of the four files, pushes nothing (the branch keeps the last"
          " good feed); results is untouched and no other branch appears %s" % heads)
    # the next scan's step A brings the wallet memory and the X-link index back into mb/
    ws2 = os.path.join(tmp, "s7next")
    os.makedirs(os.path.join(ws2, "mb"))
    pa, _ = _import(job, ws2, remote, tmp)
    got = {n: open(os.path.join(ws2, "mb", n), "rb").read() for n in ("walletmem.json.gz", "xlinks.json.gz") if os.path.exists(os.path.join(ws2, "mb", n))}
    want = {n: subprocess.run(["git", "-C", remote, "show", "radar-feed:" + n], capture_output=True).stdout for n in ("walletmem.json.gz", "xlinks.json.gz")}
    check(pa.returncode == 0 and got == want and len(got) == 2 and "no branch radar-data yet" in pa.stdout and import_mark(os.path.join(ws2, "mb")) == "ok",
          "the next scan's step A imports the feed it pushed (walletmem.json.gz, xlinks.json.gz into mb/, mark ok) and says radar-data is not there yet")


def main():
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)
    for k in ("MEMEBOT_LIVE", "RESULTS_URL", "GITHUB_REPOSITORY", "SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY", "MEMEBOT_PUSH_LIB",
              "MEMEBOT_SITE_URL", "MEMEBOT_PUSH_YOUNG"):
        os.environ.pop(k, None)
    os.environ.setdefault("LUNARCRUSH_API_KEY", "test")
    os.environ.setdefault("BITQUERY_TOKEN", "test")
    t = time.time()
    scanside_checks(check)
    print("\n(%.0f s)" % (time.time() - t))
    print("%d checks failed" % len(fails) if fails else "ALL PASS" + (" (%d skipped: %s)" % (len(SKIPS_HERE), "; ".join(SKIPS_HERE)) if SKIPS_HERE else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
