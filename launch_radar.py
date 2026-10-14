#!/usr/bin/env python3
"""launch_radar.py: the launch radar, its own job beside the hourly scan. Fake money only: it rates new coins for the page and the
phone, it never buys anything, and the paper trader never reads what it writes.

Every 150 s (a fixed grid from the run's start; an overrun skips grid points, it never bursts) one cycle, one thread, 125 s at most:
  1. kill switch (the radar workflow's state on GitHub) and the active hours (MEMEBOT_RADAR_HOURS, default 7-24 Berlin)
  2. discovery (radar_src, the WP0 probe's set): pump.fun graduated (pages 1-4) and newest coins (pages 1-2), GeckoTerminal new
     pools (pages 1-2), Jupiter recent, DexScreener profiles (LaunchLab newest only when switched on), into the cycle's sandbox
     rd/sb/<k> with fetch.py's writers
  3. DexScreener tokens/v1 for the new addresses (a pool-age cache skips old pools), the live coins and the due later prices
  4. memebot's own gather and scan on the sandbox; eligible = pool under 10 minutes old (pairCreatedAt), a price, liquidity of at
     least YOUNG_MIN_LIQ, none of the gates price/curve/nodex/honeypot/copy, and no bigger coin with its ticker (symmc)
  5. tier 1 per eligible coin: RugCheck report (cached 5 min), pump.fun coins-v3 facts only when no list gave a mint time,
     DexScreener paid profile
  6. tier 2, coins without a hard trap first: did the creator sell (fetch.dev_check, at most DEV_RPC_CAP RPC calls), the mint time from
     the chain as the last fallback (pump.fun list, Jupiter createdAt, coins-v3, then RPC), dev wallet age and earlier launches
     (pump.fun coins?creator=), swap-api candles from the mint (staircase so far, and before the pool), launch trades and the top
     holders' entry times (pump.fun), the top 10 holders' age and the funding of the fresh ones (Solana RPC, capped, 1.1 s per method);
     GeckoTerminal minute candles between them (other pools' staircase so far, the peak within the hour)
  7. traps.rate on traps.signals_radar of every eligible coin; the best 5: good coins by upside, then watch, then trap coins; only
     good coins are listed, the rest go to the fold
  8. every eligible coin is recorded with every rating and its prices 5, 15, 30 and 60 minutes later (db/memeradar/<UTC hour>.json);
     radar.json, the records of the last 48 hours, model.json and pushed.json go to the branch radar-data (one commit, force-pushed,
     never smaller than the last tree), radar.json to the app's live store (row "radar"); a push notification only for a good coin
     without a holder cluster and without anything unknown, once per coin, at most 4 an hour
About 2 minutes before its end the run starts its successor (radar.yml, source chain, 55 minutes) when the workflow is active, the
active hours last at least 10 more minutes and no other radar run is waiting. Disabling the workflow stops it within one cycle (state
off). A run lasts at most 70 minutes (the job stops at 75).

Usage:
  python3 launch_radar.py loop --dir rd --minutes 55 --cadence 150 [--mock URL] [--clock fake --now <ms>] [--no-github] [--remote URL]
  python3 launch_radar.py hours --dir rd [--remote URL]      the job's hours gate: prints inside=true|false (outside: state "hours" once)
--no-github turns off the kill switch and the chaining (a VM); there --minutes 0 runs until stopped and sleeps through the hours outside
the active ones (with GitHub, 0 means the default 55). Further options: --cache (the working
caches, default rdcache), --deadline (s a cycle may take, default 125 at cadence 150), --source, --horizon (the scan's profile, 2h).
Secrets come only from the environment: GITHUB_TOKEN (the API), RADAR_URL (the git remote with its token), SUPABASE_* (app.py); none is
ever printed or written, and git runs without them (child_env). When radar-data exists but cannot be read, nothing is pushed there and
no notification goes out until a later cycle reads it.
"""
import argparse, datetime as dt, glob, gzip, importlib, io, json, math, os, re, shutil, subprocess, sys, tarfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import fetch as F
import radar as RD
import radar_src as RS

CYCLE_S = 150               # s between cycles (the grid); radar.json "next" is the next grid point
DEADLINE_S = 125            # s: a cycle's hard deadline at 150 s cadence (scaled with --cadence); the step ends below are fractions of it
STEP_END = {"discover": 25, "ds": 35, "tier1": 60, "tier2": 95, "rate": 105, "push": 120}
MAX_AGE_MIN = 10.0          # a coin is on the radar while its DEX pool is younger than this
FINISH_MIN = 12.5           # a coin that turned 10 min with a check pending is finished for the record until this age (never pushed)
BEST_N = 5
DS_MAX_REQ = 12             # DexScreener tokens/v1 requests a cycle (30 addresses each; the probe needed 10-11 a cycle, limit 300 a minute)
DS_FIRST_REQ = 20           # ... in a run's first cycle (a cold pool-age cache: the probe asked about 570 addresses in 20 requests)
TIER1_CAP = 12              # tier-1 requests a cycle (RugCheck, pump.fun coins-v3, DexScreener orders)
RPC_CAP = 15                # Solana RPC calls a cycle (the probe: keep it; the public node allows 10 per method per 10 s)
DEV_RPC_CAP = 8             # of them for fetch.dev_check (did the creator sell), so the dev wallet, the mint and the holders keep the rest
FUND_CAP = 5                # of them for the funding of fresh holders (getTransaction)
PF_DEEP_CAP = 6             # frontend-api-v3 calls a cycle for the dev's launches and the top holders
SWAP_CAP = 6                # swap-api calls a cycle (candles from the mint, launch trades: 3 pages a coin at most)
SWAP_STAIR_N = 2            # coins a cycle whose swap-api candles are taken (staircase so far and before the pool)
GT_SLOTS = 3                # GeckoTerminal candle calls a cycle (10 s apart; GeckoTerminal new pools pages 1-2 come first)
RC_TTL = 300_000            # a RugCheck report is asked again after this while its coin is under 10 min
DEV_TTL = 6 * 3_600_000     # a dev's launch history is kept this long
LATER = (5, 15, 30, 60)     # minutes after first sight: the later prices
DUE_SLACK = 2_000           # ms: the clock's jitter between two grid points (first sight is a cycle's start); a price is never taken earlier
LATE_X = 1.5                # a later price the radar missed (it was not running) is taken up to this many times its offset late, marked late
PEAK_AT = 62 * 60_000       # the peak within the hour is priced from this age of the record (one GeckoTerminal call, at most 3 tries)
PAID_RECHECK = 3 * 60_000   # a coin without a paid DexScreener profile is asked again after this while it is on the radar
KEEP_MS = 48 * 3_600_000    # hour docs on radar-data
GUARD_MS = 47 * 3_600_000   # the never-shrink guard counts the hour docs this recent
PUSHED_MS = 7 * 86_400_000  # pushed.json keeps a coin this long
PUSH_PER_H = 4              # radar notifications per rolling hour
WM_MAX_AGE = 3 * 3_600_000  # an older wallet memory checks nothing (no green verdicts); radar_weights.json thresholds.wmMaxAgeH wins
WM_STATES = ("ok", "old", "small", "empty", "missing")   # the wallet memory's own states (traps: "noholders" is the coin's, not the memory's)
WM_MIN_COINS = 500          # a wallet memory built from fewer scored coins is too small to check (thresholds.wmMinCoins wins)
INSTANT_S = 60              # s from mint to pool: under it the pool is instant (thresholds.instantPoolS wins)
MINT_SKEW_S = 120           # s: a pool up to this long "before" its mint is two clocks on one launch, so instant (thresholds.mintSkewS)
TIME_MIN_MS = 1e12          # a time at or below this (2001) is a zero or a seconds value, never a launch time (traps.TIME_MIN_MS)
RES_EVERY = 15 * 60_000     # results (train.json, spotter.json, positions, 30 days of records) fetched again after this
FEED_EVERY = 30 * 60_000    # radar-feed (walletmem, xlinks, symmc) fetched again after this
DOC_MAX = 48_000            # bytes: radar.json; over it the fold (others) is cut first, then recent
FAIL_DEGRADED, FAIL_EXIT = 3, 10
CHAIN_BEFORE = 120_000      # ms before the run's end: the successor is dispatched
CHAIN_ROOM = 10 * 60_000    # ms: a successor starts only when the active hours last at least this long after this run's end
CHAIN_TRIES = 2             # a GitHub hiccup (no answer, a refused dispatch) gets one more try, half a minute later
DEFAULT_MINUTES = 55        # a run's length (radar.yml's default); every successor runs this long, or this run's length when longer
MAX_MINUTES = 70            # the longest run: radar.yml's job stops at 75 minutes, start and cache included
LOG_KEEP = 2_000            # log lines kept in memory (a VM runs for days)
MODEL_NEED = 300            # records with a known 1 h outcome before the radar model is fitted
TICKET = 3.0                # the record line's paper stake per call (the new-launch ticket)
HOUR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}\.json$")
SECRET_ENV = ("GITHUB_TOKEN", "GH_TOKEN", "SUPABASE_SECRET_KEY")
H = 3_600_000


# ---------------------------------------------------------------- small helpers
def redact(s):
    """s without credentials: a URL's user:token@ part and the values of the secret variables."""
    s = re.sub(r"(https?://)[^/@\s]*@", r"\1", str(s))
    for k in SECRET_ENV:
        v = os.environ.get(k) or ""
        if len(v) >= 8:
            s = s.replace(v, "***")
    return re.sub(r"sb_secret_[A-Za-z0-9_-]+", "sb_secret_***", s)


def child_env(**extra):
    """The environment of a child process (git): this one's without the API token and the store's secret key (the git remote carries
    its own token in RADAR_URL), never a prompt for a password."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", **extra)
    return env


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    """Written whole, then swapped in: a reader never sees half a file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    os.replace(path + ".tmp", path)


def num(v):
    return M.num(v) if not isinstance(v, bool) else None


def fin(v, nd=None):
    """A finite number for the docs (rounded to nd places), else None."""
    x = num(v)
    if x is None:
        return None
    return round(x, nd) if nd is not None else x


def utc_hour(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H")


def hour_ms(hour):
    return int(dt.datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def berlin(ms):
    """The Berlin wall time of ms: zoneinfo when the system has it, else the EU summer-time rule."""
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        last_sun = lambda y, m: max(d for d in (dt.datetime(y, m, day, 1, tzinfo=dt.timezone.utc) for day in range(25, 32)) if d.weekday() == 6)
        summer = last_sun(t.year, 3) <= t < last_sun(t.year, 10)
        return (t + dt.timedelta(hours=2 if summer else 1)).replace(tzinfo=None)


def parse_hours(s):
    """MEMEBOT_RADAR_HOURS "a-b" (Berlin hours, b up to 24; "22-6" wraps past midnight) -> (a, b); anything else -> (7, 24)."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", str(s or ""))
    if not m:
        return 7, 24
    a, b = int(m.group(1)), int(m.group(2))
    if not (0 <= a <= 23 and 1 <= b <= 24) or a == b:
        return (0, 24) if a == b and 0 <= a <= 24 else (7, 24)
    return a, b


def run_minutes(m, forever_ok):
    """A run's length in minutes: at most MAX_MINUTES (radar.yml's job stops at 75; a longer run would be cut before it starts its
    successor). 0 = until stopped, only where nothing stops it from outside (forever_ok: no GitHub, a VM); else the default."""
    m = num(m)
    if m is None or m <= 0:
        return 0.0 if forever_ok else float(DEFAULT_MINUTES)
    return min(float(MAX_MINUTES), m)


def in_hours(ms, hw):
    a, b = hw
    t = berlin(ms)
    h = t.hour + t.minute / 60.0
    return a <= h < b if a < b else (h >= a or h < b)


def next_start(ms, hw):
    """The next time (ms) the active hours begin, from ms (a minute-by-minute walk; at most two days)."""
    t = int(ms // 60_000 * 60_000) + 60_000
    for _ in range(2 * 24 * 60):
        if in_hours(t, hw):
            return t
        t += 60_000
    return None


def wilson(k, n):
    """95% interval of a share k/n (Wilson)."""
    if not n:
        return None
    p, z = k / n, 1.96
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def import_opt(name):
    """A module of another work package (traps, peak), or None when it is not there."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# ---------------------------------------------------------------- clocks (I8: the wall clock in production, a fake one in tests)
class WallClock:
    fake = False

    def __init__(self, cadence):
        self.step = int(cadence * 1000)

    def now(self):
        return int(time.time() * 1000)

    def wait(self, t):
        d = (t - self.now()) / 1000.0
        if d > 0:
            time.sleep(d)


class FakeClock:
    """Starts at `start` (ms); each cycle jumps to its grid point (CYCLE_S apart, no real wait), inside a cycle it runs at real speed."""
    fake = True

    def __init__(self, start):
        self.step, self.at, self.real = CYCLE_S * 1000, int(start), time.time()

    def now(self):
        return int(self.at + (time.time() - self.real) * 1000)

    def wait(self, t):
        if t > self.now():
            self.at, self.real = int(t), time.time()


# ---------------------------------------------------------------- git: one-commit branches in a bare folder of its own
class Git:
    def __init__(self, gitdir, remote, log):
        self.dir, self.remote, self.log = gitdir, remote, log

    def run(self, *a, stdin=None, timeout=60, binary=False):
        p = subprocess.Popen(["git", "--git-dir", self.dir] + list(a), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=child_env(), start_new_session=True)
        try:
            out, err = p.communicate(stdin, timeout=max(1.0, timeout))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, 9)
            except Exception:
                p.kill()
            p.communicate()
            raise RuntimeError("git %s took longer than %d s" % (a[0], timeout))
        if p.returncode != 0:
            raise RuntimeError(redact("git %s: %s" % (a[0], (err or out).decode("utf-8", "replace").strip()[-300:])))
        return out if binary else out.decode("utf-8", "replace").strip()

    def init(self):
        if not os.path.isdir(self.dir):
            os.makedirs(os.path.dirname(self.dir) or ".", exist_ok=True)
            self.run("init", "-q", "--bare", self.dir)

    def exists(self, branch, timeout=30):
        """True / False whether the remote has the branch; None when the remote did not answer."""
        try:
            out = self.run("ls-remote", "--heads", self.remote, branch, timeout=timeout)
        except RuntimeError as e:
            self.log("git ls-remote %s failed: %s" % (branch, e))
            return None
        return any(line.endswith("refs/heads/" + branch) for line in out.splitlines())

    def fetch(self, branch, ref, timeout=60):
        self.run("fetch", "-q", "--depth", "1", "--no-tags", self.remote, "+refs/heads/%s:%s" % (branch, ref), timeout=timeout)
        return self.run("rev-parse", ref)

    def paths(self, ref):
        return self.run("ls-tree", "-r", "--name-only", ref).splitlines()

    def files(self, ref, paths, timeout=60):
        """{path: bytes} of these paths (folders included) at ref, through git archive (one process)."""
        if not paths:
            return {}
        raw = self.run("archive", "--format=tar", ref, *paths, timeout=timeout, binary=True)
        out = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
            for m in tf.getmembers():
                if m.isfile():
                    out[m.name] = tf.extractfile(m).read()
        return out

    def push_tree(self, files, branch, msg, timeout=60):
        """One commit whose tree holds `files` ({path in the tree: file on disk}), force-pushed to branch. Returns the commit."""
        self.init()
        names = sorted(files)
        shas = self.run("hash-object", "-w", "--stdin-paths", stdin=("\n".join(files[n] for n in names) + "\n").encode("utf-8"), timeout=timeout).split()
        tree = {}
        for n, s in zip(names, shas):
            parts = n.split("/")
            node = tree
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = s

        def mk(node):
            lines = []
            for k in sorted(node):
                v = node[k]
                lines.append(("040000 tree %s\t%s" % (mk(v), k)) if isinstance(v, dict) else ("100644 blob %s\t%s" % (v, k)))
            return self.run("mktree", stdin=("\n".join(lines) + "\n").encode("utf-8"), timeout=timeout)
        root = mk(tree)
        commit = self.run("-c", "user.name=memebot", "-c", "user.email=memebot@users.noreply.github.com", "commit-tree", root, "-m", msg, timeout=timeout)
        self.run("push", "-q", "--force", self.remote, "%s:refs/heads/%s" % (commit, branch), timeout=timeout)
        return commit


def urllib_host(u):
    return re.sub(r"^\w+://", "", u).split("/", 1)[0]


def safe_path(p):
    """A path from a branch's tree that stays inside the folder it is written to."""
    parts = str(p).split("/")
    return bool(p) and not str(p).startswith("/") and ".." not in parts and "" not in parts


def hour_counts(docs, since):
    """{hour: records} of the hour docs whose hour starts at or after since."""
    out = {}
    for hour, doc in docs.items():
        try:
            if hour_ms(hour) >= since:
                out[hour] = len((doc or {}).get("coins") or {})
        except ValueError:
            continue
    return out


def guard_ok(new, last, since):
    """The never-shrink guard: the records of the hour docs since `since` (the last 47 hours) may not be fewer than the last tree had in
    the same hours (an hour doc that vanished counts with 0). Older hours roll off the tree normally and are not compared."""
    if not last:
        return True, 0, 0
    hours = set(new) | {h for h in last if hour_ms(h) >= since}
    a, b = sum(new.get(h, 0) for h in hours), sum(last.get(h, 0) for h in hours)
    return a >= b, a, b


# ---------------------------------------------------------------- the radar
class Radar:
    def __init__(self, a, log=None, notifier=None, clock=None, traps=None, peak=None):
        self.a, self.d = a, os.path.abspath(a.dir)
        self.cadence = max(0.05, float(a.cadence))
        self.deadline = float(a.deadline) if a.deadline else DEADLINE_S * self.cadence / CYCLE_S
        self.clock = clock or (FakeClock(int(a.now) if a.now else int(time.time() * 1000)) if a.clock == "fake" else WallClock(self.cadence))
        self.step = self.clock.step
        self.lines_log, self.extlog = [], log
        self.http = RS.RadarHttp(a.mock or None, 0.0, log=self.say)
        self.src = RS.Sources(self.http, self.say)
        self.T = traps or import_opt("traps")
        self.P = peak or import_opt("peak")
        if self.T is None:
            raise RuntimeError("traps.py is missing: the radar cannot rate coins")
        self.notifier = notifier
        self.hours = parse_hours(os.environ.get("MEMEBOT_RADAR_HOURS") or "7-24")
        self.repo = os.environ.get("GITHUB_REPOSITORY") or ""
        self.token = os.environ.get("GITHUB_TOKEN") or ""
        self.github = not a.no_github and bool(self.repo and self.token)
        self.run_id = os.environ.get("GITHUB_RUN_ID") or ("local-%d" % int(time.time()))
        self.ref = os.environ.get("GITHUB_REF_NAME") or "main"
        self.source = a.source or os.environ.get("RADAR_SOURCE") or "manual"
        self.remote = a.remote or os.environ.get("RADAR_URL") or ""
        self.git = Git(os.path.join(self.d, "git"), self.remote, self.say)
        self.out, self.res, self.feed_dir = (os.path.join(self.d, x) for x in ("out", "res", "feed"))
        self.cdir = os.path.abspath(a.cache)
        self.horizon = a.horizon
        M.apply_profile(self.horizon)
        self.cache = {k: load_json(os.path.join(self.cdir, k + ".json"), {}) or {} for k in ("pool", "rc", "pf", "jup", "dev", "wallets", "xidx", "peak", "mint", "paid")}
        self.docs, self.rec_hour, self.pushed, self.model = {}, {}, {}, {}
        self.restore_state, self.last_counts, self.last_doc = "none", None, None
        self.res_at = self.feed_at = None
        self.wm, self.xlinks, self.symmc, self.feed_meta = None, {}, {}, {}
        self.res_summary, self.train = [], (None, None)
        self.W_prior = self.T.load_weights()
        self.W = self.W_prior
        self.fails, self.notes_run, self.cycle_lines, self.work, self.closes = 0, [], [], {}, {}
        self.chained, self.chain_tries, self.dispatches, self.publishes, self.out_pk = False, 0, 0, 0, set()
        self.mismatch_said, self.exch, self.pos, self.last_c, self.paid_at = set(), set(), None, {}, {}
        self.run_start = self.run_end = None

    # ---------------------------------------------------------------- log
    def say(self, s):
        s = redact(s)
        self.lines_log.append(s)
        if len(self.lines_log) > LOG_KEEP:
            del self.lines_log[:LOG_KEEP // 2]
        if self.extlog:
            self.extlog(s)
        else:
            print("radar: " + s, file=sys.stderr, flush=True)

    def note(self, s):
        if s not in self.notes_run:
            self.notes_run.append(s)

    # ---------------------------------------------------------------- GitHub (kill switch, successor)
    def gh_fresh(self):
        """api.github.com is asked again whatever it answered before: the kill switch is read every cycle, so three refusals (a 403 of
        GitHub's secondary rate limit) or a 429 never give it up for the run (radar_src's breaker is for the coin hosts)."""
        h, gh = self.http, urllib_host(RS.GH_API)
        h.dead.discard(gh)
        h.fails.pop(gh, None)
        h.mute.discard(gh)
        h.hit429.discard(gh)
        h.cool.pop(gh, None)

    def workflow_state(self):
        self.gh_fresh()
        st, j = self.http.api("GET", "/repos/%s/actions/workflows/radar.yml" % self.repo, token=self.token, until=time.time() + 8)
        if st == 200 and isinstance(j, dict) and isinstance(j.get("state"), str):
            return j["state"]
        return None

    def others_alive(self):
        """Whether another radar run is not completed yet (queued, waiting, pending or running: C4); None when GitHub did not answer."""
        st, j = self.http.api("GET", "/repos/%s/actions/workflows/radar.yml/runs?per_page=20" % self.repo, token=self.token, until=time.time() + 8)
        if st != 200 or not isinstance(j, dict) or not isinstance(j.get("workflow_runs"), list):
            return None
        return any(isinstance(r, dict) and str(r.get("id")) != str(self.run_id) and r.get("status") != "completed" for r in j["workflow_runs"])

    def chain(self):
        """The successor run (source chain; DEFAULT_MINUTES long, or this run's length when longer, at most MAX_MINUTES): only when this
        run was long enough to have one (2 x CHAIN_BEFORE), the workflow is active, the active hours last CHAIN_ROOM after this run's end
        and no other radar run is waiting or running. Those answers are final; a GitHub hiccup (no answer, a refused dispatch) gets one
        more try (CHAIN_TRIES)."""
        if self.chained or not self.github or not self.run_end:
            return False
        if self.run_end - self.run_start < 2 * CHAIN_BEFORE:
            self.chained = True
            self.say("successor: not started (a run of %.1f min starts none)" % ((self.run_end - self.run_start) / 60_000.0))
            return False
        self.chain_tries += 1
        st = self.workflow_state()
        if st is None:
            return self.chain_hiccup("GitHub did not answer about the workflow")
        if st != "active":
            self.chained = True
            self.say("successor: not started (the radar workflow is not active)")
            return False
        if not (in_hours(self.run_end + 60_000, self.hours) and in_hours(self.run_end + CHAIN_ROOM, self.hours)):
            self.chained = True
            self.say("successor: not started (the active hours %d-%d Berlin end within %d min of this run's end)" % (self.hours[0], self.hours[1], CHAIN_ROOM // 60_000))
            return False
        alive = self.others_alive()
        if alive is None:
            return self.chain_hiccup("GitHub did not list the runs")
        if alive:
            self.chained = True
            self.say("successor: not started (another radar run is waiting)")
            return False
        mins = int(max(DEFAULT_MINUTES, min(MAX_MINUTES, math.ceil(self.run_minutes))))
        st, _ = self.http.api("POST", "/repos/%s/actions/workflows/radar.yml/dispatches" % self.repo,
                              {"ref": self.ref, "inputs": {"minutes": str(mins), "source": "chain"}}, token=self.token, until=time.time() + 10)
        self.dispatches += 1
        if st in (200, 201, 204):
            self.chained = True
            self.say("successor: dispatched (%d min)" % mins)
            return True
        return self.chain_hiccup("dispatch refused (HTTP %s)" % st)

    def chain_hiccup(self, why):
        last = self.chain_tries >= CHAIN_TRIES
        if last:
            self.chained = True
        self.say("successor: not started (%s)%s" % (why, "" if last else ", tried once more"))
        return False

    # ---------------------------------------------------------------- stores
    def load_tree(self, files):
        """The files of a radar-data tree (or a local copy) into memory and rd/out: hour docs of the last 48 h, pushed.json, model.json,
        radar.json. model.json is taken unless this run already holds a newer model (one it fitted while radar-data could not be read),
        and its weights are put in use at once (apply_model), at the run's start as at a later cycle's restore."""
        now = self.clock.now()
        docs, model = {}, None
        for path, raw in files.items():
            name = os.path.basename(path)
            try:
                doc = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except ValueError:
                continue
            if path.startswith("db/memeradar/") and HOUR_RE.match(name) and isinstance(doc, dict) and isinstance(doc.get("coins"), dict):
                if hour_ms(name[:-5]) >= now - KEEP_MS:
                    docs[name[:-5]] = doc
            elif path == "pushed.json" and isinstance(doc, dict):
                for a, t in doc.items():
                    if num(t) and now - t < PUSHED_MS:
                        self.pushed[a] = max(int(t), self.pushed.get(a, 0))
            elif path == "model.json" and isinstance(doc, dict):
                model = doc
            elif path == "radar.json" and isinstance(doc, dict):
                self.last_doc = doc
        for hour, doc in docs.items():
            self.merge_doc(hour, doc)
        if model is not None and (not self.model or (num(model.get("at")) or 0) >= (num(self.model.get("at")) or 0)):
            self.model = model
            self.apply_model()
        return docs

    def merge_doc(self, hour, doc):
        mine = self.docs.setdefault(hour, {"v": 1, "hour": hour, "t": hour_ms(hour), "upd": doc.get("upd"), "coins": {}})
        for a, rec in (doc.get("coins") or {}).items():
            if not isinstance(rec, dict):
                continue
            old = mine["coins"].get(a)
            if old is None or rec_weight(rec) > rec_weight(old):
                mine["coins"][a] = rec
            self.rec_hour[a] = hour

    def restore(self, retry=False):
        """radar-data into memory at the run's start (3.5): the branch when it exists (3 tries), else (wiped) the results' copy; when the
        branch exists but cannot be read, nothing is pushed and no notification goes out until a later try works."""
        if not self.remote:
            self.load_tree({os.path.relpath(f, self.out).replace(os.sep, "/"): open(f, "rb").read()
                            for f in glob.glob(os.path.join(self.out, "**", "*.json"), recursive=True)})
            self.restore_state = "ok"
            return
        self.git.init()
        ex = None
        for i in range(1 if retry else 3):
            try:
                if ex is None:
                    ex = self.git.exists("radar-data")            # asked again on every try while the remote does not answer
                if ex is False:
                    self.restore_from_results()
                    self.restore_state = "ok"
                    self.last_counts = hour_counts(self.docs, 0)
                    self.say("radar-data does not exist yet: fresh start (%d records from the results copy)" % sum(len(d["coins"]) for d in self.docs.values()))
                    return
                if ex is None:
                    raise RuntimeError("the remote did not answer")
                self.git.fetch("radar-data", "refs/radar/data")
                files = self.git.files("refs/radar/data", [p for p in self.git.paths("refs/radar/data") if p.endswith(".json")])
                restored = self.load_tree(files)
                self.last_counts = hour_counts(restored, 0)
                if self.restore_state == "failed":
                    self.say("radar-data restored at last: the local records are merged in, pushes and notifications resume")
                self.restore_state = "ok"
                self.say("restored from radar-data: %d records in %d hour docs, %d pushed coins" % (sum(len(d.get("coins") or {}) for d in restored.values()), len(restored), len(self.pushed)))
                return
            except Exception as e:
                self.say("radar-data restore failed (%s)%s" % (RS.short(e), "" if retry else ", try %d of 3" % (i + 1)))
                if not retry and i < 2 and not self.clock.fake:
                    time.sleep(3)
        if self.restore_state != "failed":
            self.restore_from_results()
        self.restore_state = "failed"

    def restore_from_results(self):
        for fn in glob.glob(os.path.join(self.res, "db", "memeradar", "*.json")):
            name = os.path.basename(fn)
            if HOUR_RE.match(name):
                doc = load_json(fn)
                if isinstance(doc, dict) and isinstance(doc.get("coins"), dict) and hour_ms(name[:-5]) >= self.clock.now() - KEEP_MS:
                    self.merge_doc(name[:-5], doc)

    def fetch_results(self, timeout=60):
        """results (depth 1): train.json, spotter.json, the positions and 30 days of radar records into rd/res (I4: read only)."""
        if not self.remote:
            return False
        try:
            self.git.init()
            self.git.fetch("results", "refs/radar/results", timeout=timeout)
            want = ("db/memebot/train.json", "db/memebot/spotter.json", "db/memepos/", "db/memeexit/", "db/memeradar/")
            paths = [p for p in self.git.paths("refs/radar/results") if p.startswith(want)]
            files = {p: raw for p, raw in self.git.files("refs/radar/results", paths, timeout=timeout).items() if safe_path(p)}
            shutil.rmtree(self.res, ignore_errors=True)
            for p, raw in files.items():
                fp = os.path.join(self.res, *p.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "wb") as f:
                    f.write(raw)
            self.res_at, self.pos = self.clock.now(), None
            self.train = M.load_train(self.res)[:2]
            self.res_summary = [r for r in (summ(rec) for doc in (load_json(f) for f in glob.glob(os.path.join(self.res, "db", "memeradar", "*.json")))
                                            if isinstance(doc, dict) for rec in (doc.get("coins") or {}).values() if isinstance(rec, dict)) if r]
            self.say("results read: %d files, %d radar records with an outcome" % (len(files), sum(1 for r in self.res_summary if r["rug"] is not None)))
            return True
        except Exception as e:
            self.res_at = self.clock.now()          # tried: again in RES_EVERY
            self.say("results not read (%s): the last copy stays" % RS.short(e))
            return False

    def fetch_feed(self, timeout=60):
        """radar-feed (the scan's hourly wallet memory, X links and tickers) into rd/feed."""
        self.feed_at = self.clock.now()
        if self.remote:
            try:
                self.git.init()
                if self.git.exists("radar-feed") is False:
                    raise RuntimeError("no radar-feed branch yet")
                self.git.fetch("radar-feed", "refs/radar/feed", timeout=timeout)
                names = [p for p in self.git.paths("refs/radar/feed") if p in ("walletmem.json.gz", "xlinks.json.gz", "symmc.json.gz", "meta.json")]
                for p, raw in self.git.files("refs/radar/feed", names, timeout=timeout).items():
                    os.makedirs(self.feed_dir, exist_ok=True)
                    with open(os.path.join(self.feed_dir, p), "wb") as f:
                        f.write(raw)
            except Exception as e:
                self.say("radar-feed not read (%s)" % RS.short(e))
        gz = lambda n: self.read_gz(os.path.join(self.feed_dir, n))
        wm = gz("walletmem.json.gz")
        self.wm = wm if isinstance(wm, dict) and num(wm.get("t")) else None
        xl = gz("xlinks.json.gz")
        self.xlinks = (xl.get("links") or {}) if isinstance(xl, dict) and isinstance(xl.get("links"), dict) else {}
        sm = gz("symmc.json.gz")
        self.symmc = {str(k).upper(): num(v) for k, v in ((sm.get("sym") or {}) if isinstance(sm, dict) and isinstance(sm.get("sym"), dict) else {}).items() if num(v)}
        self.feed_meta = load_json(os.path.join(self.feed_dir, "meta.json"), {}) or {}

    @staticmethod
    def read_gz(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, EOFError):
            return None

    def thresholds(self):
        """radar_weights.json's thresholds (the learned model's copy when one is in use); {} without them (the module defaults apply)."""
        for w in (self.W, self.W_prior):
            if isinstance(w, dict) and isinstance(w.get("thresholds"), dict):
                return w["thresholds"]
        return {}

    def wm_state(self, now):
        """The wallet memory as traps.walletmem_lookup judges it (WP1), with the same thresholds: missing; old (over wmMaxAgeH, or
        without a time); empty (built from no coin); small (under wmMinCoins scored coins: refilling after a lost cache); ok. Only ok
        checks anything, so only then can a coin be green."""
        if not self.wm:
            return "missing"
        th = self.thresholds()
        t, n = num(self.wm.get("t")), num(self.wm.get("nCoins"))
        if t is None or now - t > (num(th.get("wmMaxAgeH")) * H if num(th.get("wmMaxAgeH")) else WM_MAX_AGE):
            return "old"
        if not n:
            return "empty"
        return "small" if n < (num(th.get("wmMinCoins")) or WM_MIN_COINS) else "ok"

    def gap(self, pool, mint):
        """(seconds from mint to pool, instant) as traps reads them (WP1 _gap, the same thresholds): a pool up to mintSkewS (120 s)
        "before" its mint is two sources' clocks on a launch in the same slot, so it is instant (the study: most instant pools have a
        gap of exactly 0 s); a pool further before its mint, or a time that is no real launch time, is unknown, never "not instant"."""
        if pool is None or mint is None or pool <= TIME_MIN_MS or mint <= TIME_MIN_MS:
            return None, None
        th = self.thresholds()
        s = (pool - mint) / 1000.0
        if s < -(num(th.get("mintSkewS")) or MINT_SKEW_S):
            return None, None
        return s, s < (num(th.get("instantPoolS")) or INSTANT_S)

    def save_cache(self):
        now = self.clock.now()
        c = self.cache
        c["pool"] = {a: v for a, v in c["pool"].items() if isinstance(v, list) and now - (num(v[2]) or 0) < 2 * 86_400_000}
        c["rc"] = {a: v for a, v in c["rc"].items() if isinstance(v, dict) and now - (num(v.get("t")) or 0) < 30 * 60_000}
        c["pf"] = dict(sorted(((a, v) for a, v in c["pf"].items() if isinstance(v, dict)), key=lambda kv: -(num(kv[1].get("seen")) or 0))[:20_000])
        c["jup"] = dict(sorted(((a, v) for a, v in c["jup"].items() if isinstance(v, dict)), key=lambda kv: -(num(kv[1].get("seen")) or 0))[:20_000])
        c["dev"] = {a: v for a, v in c["dev"].items() if isinstance(v, dict) and "rows" in v and now - (num(v.get("t")) or 0) < 7 * 86_400_000}
        c["wallets"] = dict(sorted(((a, v) for a, v in c["wallets"].items() if isinstance(v, dict)), key=lambda kv: -(num(kv[1].get("used")) or 0))[:50_000])
        c["xidx"] = dict(list(c["xidx"].items())[-50_000:])
        c["mint"] = dict(list(c["mint"].items())[-5_000:])
        c["paid"] = dict(list(c["paid"].items())[-5_000:])
        for k, v in c.items():
            try:
                write_json(os.path.join(self.cdir, k + ".json"), v)
            except (OSError, ValueError) as e:
                self.say("cache %s not saved (%s)" % (k, RS.short(e)))

    # ---------------------------------------------------------------- records
    def rec(self, a):
        h = self.rec_hour.get(a)
        return self.docs[h]["coins"].get(a) if h and h in self.docs else None

    def new_rec(self, a, now, row):
        hour = utc_hour(now)
        doc = self.docs.setdefault(hour, {"v": 1, "hour": hour, "t": hour_ms(hour), "upd": now, "coins": {}})
        pr, b = row["pr"], row["basic"]
        pool = int(num(pr.get("pairCreatedAt")))
        rec = {"addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48], "pair": pr.get("pairAddress") or None,
               "dex": str(pr.get("dexId") or "")[:24] or None, "lp": None, "found": found_of(pr), "mint": None, "pool": pool, "first": now,
               "seenAge": round((now - pool) / 60_000.0, 2), "px": fin(b.get("price")), "liq": fin(b.get("liq"), 2), "mc": fin(b.get("mc"), 2),
               "rt": [], "good": None, "goodPx": None, "sig": {}, "chk": {}, "push": None, "later": {}, "peak60": None, "out": None}
        doc["coins"][a] = rec
        self.rec_hour[a] = hour
        return rec

    def touch(self, a, now):
        h = self.rec_hour.get(a)
        if h in self.docs:
            self.docs[h]["upd"] = now

    def write_docs(self):
        """The hour docs of the last 48 hours into rd/out/db/memeradar (older ones leave the tree: results keeps 30 days)."""
        now = self.clock.now()
        dd = os.path.join(self.out, "db", "memeradar")
        os.makedirs(dd, exist_ok=True)
        keep = set()
        for hour, doc in list(self.docs.items()):
            if hour_ms(hour) < now - KEEP_MS:
                for a in list(doc.get("coins") or {}):
                    if self.rec_hour.get(a) == hour:
                        self.rec_hour.pop(a, None)
                self.docs.pop(hour, None)
                continue
            keep.add(hour + ".json")
            write_json(os.path.join(dd, hour + ".json"), doc)
        for fn in os.listdir(dd):
            if fn not in keep:
                os.remove(os.path.join(dd, fn))
        write_json(os.path.join(self.out, "pushed.json"), {a: t for a, t in self.pushed.items() if now - t < PUSHED_MS})
        write_json(os.path.join(self.out, "model.json"), self.model or {"v": 1, "from": "prior", "n": 0, "need": MODEL_NEED})

    def publish(self, doc):
        """radar.json and the records to radar-data (one commit, force): only when the restore worked and the never-shrink guard passes.
        True when it landed."""
        write_json(os.path.join(self.out, "radar.json"), doc)
        self.write_docs()
        if not self.remote:
            return True
        if self.restore_state != "ok":
            self.note("radar-data not restored: records kept on the runner, not pushed")
            return False
        now = self.clock.now()
        new = hour_counts(self.docs, now - GUARD_MS)
        ok, n_new, n_old = guard_ok(new, self.last_counts, now - GUARD_MS)
        if not ok:
            self.note("never-shrink guard: push refused (%d records, the last tree had %d)" % (n_new, n_old))
            self.say("never-shrink guard: %d records in the last 47 h, the last tree had %d: not pushed" % (n_new, n_old))
            return False
        files = {"radar.json": os.path.join(self.out, "radar.json"), "pushed.json": os.path.join(self.out, "pushed.json"),
                 "model.json": os.path.join(self.out, "model.json")}
        for hour in self.docs:
            files["db/memeradar/%s.json" % hour] = os.path.join(self.out, "db", "memeradar", hour + ".json")
        try:
            left = max(5.0, (self.http.until or time.time() + 30) - time.time() + 10)
            self.git.push_tree(files, "radar-data", "launch radar %s (fake money)" % dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                               timeout=left)
            self.last_counts = hour_counts(self.docs, 0)
            self.publishes += 1
            return True
        except Exception as e:
            self.say("radar-data push failed (%s): again next cycle" % RS.short(e))
            self.note("radar-data push failed: the page shows the app copy or an older list")
            return False

    def store_row(self, doc):
        """radar.json to the app's live store (row "radar"), when it is set up. Never raises."""
        try:
            if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY")):
                return False
            import app as A
            if not A.enabled():
                return False
            A.put_row("radar", doc)
            return True
        except Exception as e:
            self.say("app store row not written (%s)" % RS.short(e))
            return False

    def notify(self, coins):
        """One notification for these good coins (kind radar, app.notify_radar when app.py has it). Never raises."""
        try:
            if self.notifier:
                return self.notifier(coins)
            if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY")):
                return {"skipped": "no live store"}
            import app as A
            if not A.enabled():
                return {"skipped": "no live store"}
            fn = getattr(A, "notify_radar", None)
            if fn:
                return fn(coins)
            title, body = push_text(coins)
            return A.notify("radar", title, body, "#tab-radar")
        except Exception as e:
            self.say("notification failed (%s)" % RS.short(e))
            return {"skipped": "error"}

    # ---------------------------------------------------------------- the run
    def start(self):
        os.makedirs(self.d, exist_ok=True)
        self.fetch_results()
        try:
            self.restore()
        except Exception as e:
            self.say("radar-data restore failed (%s): records kept on the runner, not pushed" % RS.short(e))
            self.restore_state = "failed"
        self.fetch_feed()

    def apply_model(self):
        """model.json's learned weights, only when they were fitted on this study prior (radar_weights.json's src, as traps.load_weights
        checks); a model of another prior is dropped and fitted again at the next cycle."""
        if self.model.get("from") == "learned" and isinstance(self.model.get("w"), dict):
            if self.model.get("src") is not None and self.model.get("src") == self.W_prior.get("src"):
                self.W = self.model["w"]
                return True
            self.say("model.json was fitted on another study prior (%s, now %s): the study prior is used and the model is fitted again"
                     % (str(self.model.get("src"))[:40], str(self.W_prior.get("src"))[:40]))
            self.model = {}
        self.W = self.W_prior
        return False

    def loop(self):
        """The cycles of this run. Returns the exit code."""
        self.run_start = self.clock.now()
        mins = self.run_minutes = run_minutes(self.a.minutes, not self.github)
        if num(self.a.minutes) and self.a.minutes > mins:
            self.say("%g minutes asked: a run is at most %d minutes (radar.yml's job stops at 75), so this one runs %d" % (self.a.minutes, MAX_MINUTES, mins))
        self.run_end = self.run_start + int(mins * 60_000) if mins else None
        self.say("run %s (%s): %s, a cycle every %g s, active hours %d-%d Berlin%s" % (
            self.run_id, self.source, ("until %s UTC" % dt.datetime.fromtimestamp(self.run_end / 1000, dt.timezone.utc).strftime("%H:%M")) if self.run_end else "until stopped",
            self.step / 1000.0, self.hours[0], self.hours[1], "" if self.github else ", no kill switch or successor (no GitHub)"))
        self.start()
        k = 0
        while True:
            t_k = self.run_start + k * self.step
            if self.run_end and t_k >= self.run_end:
                break
            self.wait_until(t_k)
            last = bool(self.run_end and t_k + self.step >= self.run_end)
            try:
                res = self.cycle(k, t_k, last)
                self.fails = 0
            except Exception as e:
                self.fails += 1
                self.say("cycle %d failed (%s), %d in a row" % (k, RS.short(e), self.fails))
                res = None
                if self.fails >= FAIL_DEGRADED:
                    self.degraded(t_k, k)
                if self.fails >= FAIL_EXIT:
                    self.say("%d cycles in a row failed: the run ends (the scan's watchdog starts the radar again)" % self.fails)
                    return 1
            if res in ("off", "hours"):
                self.save_cache()
                if res == "hours" and not self.run_end:
                    ns = next_start(self.clock.now(), self.hours)
                    if ns:                          # a VM (--minutes 0) sleeps until the hours begin again and goes on
                        self.say("outside the active hours: sleeping until %s UTC" % dt.datetime.fromtimestamp(ns / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
                        self.clock.wait(ns)
                        self.run_start, k = self.clock.now(), 0
                        continue
                return 0
            if self.clock.fake:
                k += 1
            else:
                k = max(k + 1, int(math.ceil((self.clock.now() - self.run_start) / float(self.step))))
        if self.run_end and not self.chained:
            self.wait_until(self.run_end - CHAIN_BEFORE, chain=False)
            self.chain()
            if not self.chained:                 # a GitHub hiccup: once more, half a minute later
                self.clock.wait(min(self.clock.now() + 30_000, self.run_end - 15_000))
                self.chain()
        self.save_cache()
        return 0

    def degraded(self, t_k, k):
        """radar.json while cycles fail (FAIL_DEGRADED in a row or more): state degraded with the reason, the last list's coins dropped
        (the record line, model and last good coin kept), to radar-data and the app's row. Never raises."""
        try:
            now = self.clock.now()
            doc = finish_from(self.last_doc if isinstance(self.last_doc, dict) else {}, "degraded", now, "%d cycles in a row failed" % self.fails,
                              self.run_id, self.run_start, self.run_end, self.source, self.hours)
            doc["next"], doc["run"]["cycle"] = t_k + self.step, k
            doc["wm"] = {"t": num((self.wm or {}).get("t")), "nCoins": num((self.wm or {}).get("nCoins"))}
            doc["notes"] = ["%d cycles in a row failed: the list is not current" % self.fails]
            self.publish(doc)
            self.store_row(doc)
        except Exception as e:
            self.say("degraded state not written (%s)" % RS.short(e))

    def wait_until(self, t, chain=True):
        """Waits for clock time t; the successor is dispatched on the way when the wait passes the run's end minus CHAIN_BEFORE."""
        if chain and self.run_end and not self.chained and t >= self.run_end - CHAIN_BEFORE:
            self.clock.wait(self.run_end - CHAIN_BEFORE)
            self.chain()
        self.clock.wait(t)

    # ---------------------------------------------------------------- one cycle
    def cycle(self, k, t_k, last):
        T0 = time.time()
        now = self.clock.now()
        end = lambda s: T0 + self.deadline * s / DEADLINE_S
        self.http.new_cycle(end(DEADLINE_S), RPC_CAP)
        self.notes_run = []
        if self.github:
            st = self.workflow_state()
            if st is not None and st != "active":
                self.say("the radar workflow is %s: state off, the run ends" % st)
                self.finish_doc("off", now, "the radar workflow is switched off (%s)" % st)
                return "off"
        if not in_hours(now, self.hours):
            self.say("outside the active hours %d-%d Berlin: state hours, the run ends" % self.hours)
            self.finish_doc("hours", now, "outside the active hours %02d:00-%02d:00 Berlin" % self.hours)
            return "hours"
        if self.restore_state == "failed":
            self.restore(retry=True)
        sb = os.path.join(self.d, "sb", str(k))
        for old in glob.glob(os.path.join(self.d, "sb", "*")):
            shutil.rmtree(old, ignore_errors=True)
        # 2. discovery
        self.http.until = end(STEP_END["discover"])
        self.last_c = {}
        n_disc = self.src.discover(sb, self.cache["pf"], now, self.cache["jup"])
        self.index_x(now)
        # 3. DexScreener
        self.http.until = end(STEP_END["ds"])
        cap = DS_FIRST_REQ if k == 0 else DS_MAX_REQ
        asks = self.ds_asks(sb, now, cap)
        answered, nreq = self.src.ds_tokens(sb, asks, cap)
        self.write_rc_rows(sb)
        # 4. memebot's gather and scan on the sandbox
        rows, pairs = self.run_scan(sb, now)
        self.pool_cache(pairs, answered, now)
        self.later_prices(pairs, answered, now)
        live, finish = self.eligible(rows, now)
        self.http.until = end(STEP_END["tier1"])
        gt_jobs = self.gt_jobs(live, now)
        self.gt_slot(gt_jobs, now)
        # 5. tier 1
        got_rc = self.tier1(live, now)
        if got_rc:
            self.write_rc_rows(sb)
            rows, pairs = self.run_scan(sb, now)
            live, finish = self.eligible(rows, now)
        self.gt_slot(gt_jobs, now)
        # 6. tier 2
        self.http.until = end(STEP_END["tier2"])
        self.exch = self.exchanges()
        self.tier2(sb, live, finish, now)
        self.exch = self.exchanges()
        self.gt_slot(gt_jobs, now)
        # 7. rate, rank, records
        self.http.until = end(STEP_END["rate"])
        rated = [self.rate(r, now) for r in live]
        for r in finish:
            self.rate(r, now, record_only=True)
        top, coins, others = rank(rated)
        for x in top:
            rec = self.rec(x["addr"])
            if rec is not None:
                rec["top"] = 1
        self.outcomes(now)
        # 8. pushes, radar.json, radar-data, the app's row
        self.http.until = end(STEP_END["push"])
        to_push = self.to_push(coins, now)
        for x in to_push:                        # pushed.json (radar-data) holds the coin before anything is sent, so a restart never sends it
            self.pushed[x["addr"]] = now         # twice; the record and radar.json say "pushed" only once the notification went out
        secs = round(time.time() - T0, 1)
        state = "ending" if last else "running"
        line = lambda n: "cycle %d: %d seen, %d without traps, %d pushed (%d s)" % (k, len(rated), len(coins), n, round(secs))
        self.cycle_lines = (self.cycle_lines + [line(0)])[-6:]
        doc = self.build_doc(state, coins, others, rated, now, t_k + self.step, secs, k)
        landed = self.publish(doc)
        if to_push and not landed and self.remote:
            for x in to_push:                    # the mark could not be saved: no notification now, the next cycle tries again
                self.pushed.pop(x["addr"], None)
            to_push = []
        sent = []
        if to_push:
            out = self.notify([dict(x["doc"], push=now) for x in to_push])
            self.say("notification for %s: %s" % (", ".join(x["sym"] for x in to_push), json.dumps(out)[:160] if isinstance(out, dict) else out))
            if went_out(out):
                sent = to_push                   # nothing went out (rate guard, no push sender, no phone): the coin stays marked, never "pushed" on the page
            for x in sent:
                rec = self.rec(x["addr"])
                if rec is not None:
                    rec["push"] = now
        if sent:                                 # radar.json and the records say pushed right after the notification (3.6)
            self.cycle_lines[-1] = line(len(sent))
            doc = self.build_doc(state, coins, others, rated, now, t_k + self.step, secs, k)
            self.publish(doc)
        self.store_row(doc)
        self.say(line(len(sent)) + "; %d DexScreener requests, discovery %s" % (nreq, ", ".join("%s %d" % kv for kv in sorted(n_disc.items()))))
        self.last_doc = doc
        # 9. caches, the model, the periodic reads
        for a in [a for a in list(self.work) + list(self.closes) if now - (num((self.rec(a) or {}).get("pool")) or 0) > 20 * 60_000]:
            self.work.pop(a, None)
            self.closes.pop(a, None)
        self.save_cache()
        self.maybe_fit(now)
        nxt = (t_k + self.step - self.clock.now()) / 1000.0 if not self.clock.fake else 60.0
        if self.res_at is None or now - self.res_at >= RES_EVERY:
            self.fetch_results(timeout=max(10.0, min(60.0, nxt - 5)))
        if self.feed_at is None or now - self.feed_at >= FEED_EVERY:
            self.fetch_feed(timeout=max(10.0, min(60.0, nxt - 5)))
        return "ok"

    # ---------------------------------------------------------------- steps
    def index_x(self, now):
        """The X-link index (account, community and tweet links of pump.fun's coin lists) for x_copied and tweet_shared."""
        for a, f in self.cache["pf"].items():
            if f.get("xi") or not f.get("x"):
                continue
            f["xi"] = 1
            nx = self.norm_x(f.get("x"))
            if nx:
                self.cache["xidx"].setdefault(nx[1], {})[a] = int(f.get("t") or now)

    def norm_x(self, url):
        try:
            out = self.T.norm_x(url) if url else None
            return tuple(out) if out else None
        except Exception:
            return None

    def ds_asks(self, sb, now, cap=DS_MAX_REQ):
        """The addresses DexScreener is asked about (at most cap requests of 30), in this order: due later prices, the coins on the
        radar, then new candidates by source: Jupiter recent and GeckoTerminal new pools first (short lists, and in the WP0 probe each
        found 3 fresh pools nobody else listed, Jupiter the earliest), then pump.fun graduated, pump.fun newest, DexScreener profiles,
        LaunchLab; none whose pool is known to be 10 minutes or older, none still on pump.fun's curve."""
        out, seen = [], set()

        def add(a):
            if a and a not in seen and M.B58.match(a):
                seen.add(a)
                out.append(a)
        for a in self.due_later(now):
            add(a)
        for doc in self.docs.values():
            for a, rec in (doc.get("coins") or {}).items():
                if now - (num(rec.get("pool")) or 0) < FINISH_MIN * 60_000:
                    add(a)
        pf, ptags = M.load_side(sb, "pf", M.PF_COLS)
        gt, _ = M.load_side(sb, "gt", M.GT_COLS)
        jup, _ = M.load_side(sb, "jup", M.JUP_COLS)
        lists = M.load_lists(sb)
        tagged = lambda tag: [a for a in pf if tag in ptags.get(a, ())]
        cand = list(jup) + list(gt) + tagged("pf:graduated") + [a for a in tagged("pf:new") if pf[a].get("complete")] + \
            list(lists.get("profiles", [])) + list(lists.get("llNew", []))
        for a in cand:
            pc = self.cache["pool"].get(a)
            if isinstance(pc, list):
                born, curve, at = pc
                if born and not curve and now - born >= MAX_AGE_MIN * 60_000:
                    continue                 # an old pool: never asked again
                if (curve or not born) and now - at < 120_000:
                    continue                 # on a curve, or no pair: asked again after two minutes
            add(a)
        return out[:cap * 30]

    def pool_cache(self, pairs, answered, now):
        """addr -> [pool opened (ms) or None, a launch curve's pair, when seen]: an old pool is never asked again, a curve pair or no pair
        after two minutes."""
        for a in answered:
            if a not in pairs:
                self.cache["pool"][a] = [None, False, now]
        for a, p in pairs.items():
            if p.get("px_only") or RD.standin(p) or p.get("gt_only"):
                continue
            born = num(p.get("pairCreatedAt"))
            self.cache["pool"][a] = [int(born) if born and born > 1e12 else None, bool(M.CURVE_DEX.search(str(p.get("dexId") or ""))), now]

    def write_rc_rows(self, sb):
        rows = [F.rc_row(a, v["rep"]) for a, v in self.cache["rc"].items() if isinstance(v, dict) and isinstance(v.get("rep"), dict)]
        if rows:
            F.write_rows(sb, "risk", "reports_radar.txt", rows)

    def run_scan(self, sb, now):
        """memebot's gather and scan on the sandbox at the radar's clock (radar.py's path): (rows, pairs)."""
        RD.gather(sb, now)
        pairs = M.load_pairs(sb)
        w, _ = RD.weights(self.res, self.horizon)
        if self.pos is None:
            self.pos = M.positions(self.res) if os.path.isdir(os.path.join(self.res, "db", "memepos")) else {}
        rows, _, _, _, _ = M.scan(sb, self.pos, pairs, now, w)
        return rows, pairs

    def eligible(self, rows, now):
        """(live, finish): the coins on the radar (pool under 10 min, a price, YOUNG_MIN_LIQ, no hard gate, no bigger coin with the
        ticker), and the recorded coins that turned 10 min with a check pending (finished for the record, until FINISH_MIN)."""
        live, finish = [], []
        for r in rows:
            pr, b = r["pr"], r["basic"]
            born = num(pr.get("pairCreatedAt"))
            if not born or born < 1e12:
                continue
            age = (now - born) / 60_000.0
            ok = (b.get("price") or 0) > 0 and (b.get("liq") or 0) >= M.YOUNG_MIN_LIQ and not any(x in ("price", "curve", "nodex", "honeypot", "copy") for x in r["fails"])
            sym = str(pr.get("symbol") or "").upper()
            if ok and b.get("mc") and self.symmc.get(sym) and b["mc"] * 3 <= self.symmc[sym]:
                ok = False                     # a copy of a bigger coin the scan knows (the feed's tickers)
            if not ok:
                continue
            if 0 <= age < MAX_AGE_MIN:
                r["age"] = age
                live.append(r)
            elif age < FINISH_MIN and self.rec(r["a"]) is not None and self.pending(r["a"]):
                r["age"] = age
                finish.append(r)
        return live, finish

    def pending(self, a):
        w = self.work.get(a) or {}
        return any(w.get(k) == "pending" for k in ("rc", "dev", "holders", "devage", "devhist"))

    @staticmethod
    def later_due(first, m, now):
        """Whether the price m minutes after first sight may be taken now: at or after its due time (DUE_SLACK is only the clock's jitter
        between grid points), and at most LATE_X times the offset late (the radar was not running then: marked late)."""
        due = first + m * 60_000
        return due - DUE_SLACK <= now <= due + LATE_X * m * 60_000 + DUE_SLACK

    def due_later(self, now):
        out = []
        for doc in self.docs.values():
            for a, rec in (doc.get("coins") or {}).items():
                first = num(rec.get("first"))
                if first and any(str(m) not in (rec.get("later") or {}) and self.later_due(first, m, now) for m in LATER):
                    out.append(a)
        return out

    def later_prices(self, pairs, answered, now):
        """The prices 5, 15, 30 and 60 minutes after first sight, at the first cycle at or after each; when the radar was not running
        then, up to 1.5x the offset late, marked late (later than one cycle and half a minute after the due time). gone only when
        DexScreener answered for the coin and had no pair."""
        late_ms = self.step + 30_000
        for a in self.due_later(now):
            rec = self.rec(a)
            p = pairs.get(a)
            px = num((p or {}).get("priceUsd"))
            if p and px and px > 0:
                obs = {"t": now, "px": px, "liq": fin(p.get("liquidityUsd"), 2)}
            elif (p is not None and not RD.standin(p)) or a in answered:
                obs = {"t": now, "gone": True}           # DexScreener answered for it with no pair, or its DexScreener pair has no price
            else:
                continue
            for m in LATER:
                due = rec["first"] + m * 60_000
                if str(m) not in rec["later"] and self.later_due(rec["first"], m, now):
                    rec["later"][str(m)] = dict(obs, late=True) if now - due > late_ms else dict(obs)
            self.touch(a, now)

    def gt_jobs(self, live, now):
        """GeckoTerminal's candle calls of this cycle: the peak within the hour of records 62 minutes old (ever good or in the best 5,
        each at most 3 tries), then the staircase so far of up to 2 coins with a pool of 6 minutes or more."""
        peaks = []
        for doc in self.docs.values():
            for a, rec in (doc.get("coins") or {}).items():
                if rec.get("peak60") is None and (rec.get("good") or rec.get("top")) and rec.get("pair") and now - rec["first"] >= PEAK_AT \
                        and int(self.cache["peak"].get(a, 0)) < 3 and now - rec["first"] < 6 * H:
                    peaks.append((0 if rec.get("good") else 1, num(rec.get("first")) or 0, a))
        jobs = [("peak", a) for _, _, a in sorted(peaks)]     # ever-good coins first (the record line's calls), then the best 5's others
        for r in sorted(live, key=lambda r: -r["age"]):
            a = r["a"]
            got = self.closes.get(a)
            if self.swap_stair(r):
                continue                     # swap-api's candles give this pump.fun coin's staircase (tier 2)
            if r["age"] >= 6 and r["pr"].get("pairAddress") and (got is None or (got[0] < 8.0 and r["age"] >= 8.5)):
                jobs.append(("stair", a, r["pr"]["pairAddress"], num(r["pr"].get("pairCreatedAt")), r["age"]))
            if sum(1 for j in jobs if j[0] == "stair") >= 2:
                break
        return jobs[:GT_SLOTS]

    def swap_stair(self, r):
        """Whether swap-api's candles (not GeckoTerminal's) give this coin's staircase: a pump.fun coin, the adapter on, and the candles
        reached its pool (they cover 100 minutes from the mint)."""
        return self.pumpish(r) and self.src.use("swap_candles") and (self.work.get(r["a"]) or {}).get("swapc") != "nopool"

    def gt_slot(self, jobs, now):
        """One GeckoTerminal call (its 10 s gap keeps the other hosts' calls between them). While GeckoTerminal cools down after a 429
        (15, 30, then 60 s) the job waits for a later slot; a peak try counts only when the call was sent."""
        if not jobs or self.http.blocked(RS.GT_HOST):
            return
        j = jobs.pop(0)
        if j[0] == "peak":
            a = j[1]
            rec = self.rec(a)
            cands = self.src.candles(rec["pair"], rec["first"] - 60_000, rec["first"] + H + 120_000)
            if self.http.code != "skip":
                self.cache["peak"][a] = int(self.cache["peak"].get(a, 0)) + 1
            if cands and self.P is not None and rec.get("px"):
                try:
                    pk = self.P.peak_of([c[:6] for c in cands], rec["first"], rec["first"] + H, rec["px"], ds_points=later_points(rec),
                                        liq0=num(rec.get("liq")), mc0=num(rec.get("mc")))
                except Exception as e:
                    self.say("peak of %s not priced (%s)" % (rec.get("sym"), RS.short(e)))
                    pk = None
                if isinstance(pk, dict) and pk.get("state") != "waiting":     # no candle inside the hour yet: tried again (3 tries)
                    rec["peak60"] = {"x": fin(pk.get("x"), 4), "at": pk.get("at"), "res": pk.get("res") or 1, "cut": [str(c)[:60] for c in (pk.get("cut") or [])][:6]}
                    if pk.get("state") == "unit":
                        rec["peak60"]["x"] = None
                    self.touch(a, now)
        else:
            _, a, pool, born, age = j
            cands = self.src.candles(pool, born, self.clock.now())
            if cands is not None:
                self.closes[a] = (age, [c[4] for c in cands if c[4]][:15])

    def tier1(self, live, now):
        """RugCheck report (cached 5 min while the coin is under 10 min), pump.fun's coin facts when no list gave a mint time, DexScreener's
        paid profile: at most TIER1_CAP requests, coins without a report first. Returns whether a new report came."""
        n0, got = self.http.n, False
        order = sorted(live, key=lambda r: (0 if not isinstance((self.cache["rc"].get(r["a"]) or {}).get("rep"), dict) else 1, r["age"]))
        paid_ask = []
        for r in order:
            a = r["a"]
            w = self.work.setdefault(a, {})
            if self.http.n - n0 >= TIER1_CAP:
                break
            c = self.cache["rc"].get(a)
            if not (isinstance(c, dict) and c.get("st") == "ok" and now - (num(c.get("t")) or 0) < RC_TTL):
                st, rep = self.src.rc_report(a)
                if st == "ok":
                    self.cache["rc"][a] = {"t": now, "st": "ok", "rep": rep}
                    got = True
                elif not (isinstance(c, dict) and isinstance(c.get("rep"), dict)) and st in ("404", "429", "err"):
                    self.cache["rc"][a] = {"t": now, "st": st, "rep": None}     # an older report stays when a refresh fails
                w["rc"] = st if st in ("ok", "404", "429", "err") else "pending"
            if not self.mint_of(a, r) and self.pumpish(r) and not w.get("pfcoin") and self.http.n - n0 < TIER1_CAP:
                w["pfcoin"] = 1                  # the mint time: pump.fun's list row, then Jupiter's createdAt, then coins-v3, then the RPC
                self.src.pf_coin(a, self.cache["pf"], now)
            if self.paid_due(a, now):
                paid_ask.append(a)
        room = max(0, TIER1_CAP - (self.http.n - n0))
        if paid_ask and room:
            sb_dp = os.path.join(self.d, "sb", "dp")
            shutil.rmtree(sb_dp, ignore_errors=True)
            asked = paid_ask[:room]
            for a, v in self.src.ds_paid(sb_dp, asked).items():
                self.cache["paid"][a] = v
            for a in asked:
                self.paid_at[a] = now
        return got

    def paid_due(self, a, now):
        """Whether DexScreener's paid profile is asked about this coin now: never asked, or not paid when last asked PAID_RECHECK ago
        (a profile can be paid while the coin is on the radar). A paid one is not asked again."""
        v = self.cache["paid"].get(a)
        return v is None or (v is False and now - self.paid_at.get(a, 0) >= PAID_RECHECK)

    @staticmethod
    def pumpish(r):
        a, dex = r["a"], str(r["pr"].get("dexId") or "").lower()
        return a.endswith("pump") or dex in ("pumpswap", "pumpfun") or bool(r["pr"].get("pf"))

    def creator_of(self, a, r=None):
        meta = self.cache["pf"].get(a) or {}
        rc = (self.cache["rc"].get(a) or {}).get("rep") or {}
        ll = ((r or {}).get("pr") or {}).get("ll") or {}
        w = self.work.get(a) or {}
        return meta.get("creator") or F.addr_of(ll.get("creator")) or (self.cache["jup"].get(a) or {}).get("dev") or rc.get("creator") or w.get("devWallet")

    def tier2(self, sb, live, finish, now):
        """Coins without a hard trap first, each coin's checks once (a check that misses the budget stays pending for the next cycle):
        did the creator sell (fetch.dev_check, at most DEV_RPC_CAP RPC calls), the mint time from the chain for the best coin without
        one (the last fallback, 3 pages at most), the dev wallet's age (one RPC call) and earlier launches (pump.fun coins?creator=),
        swap-api candles from the mint, the launch trades (3 pages at most) and the top holders' entry times (pump.fun), the top 10
        holders' age (one RPC call each) and the funding of the fresh ones (at most FUND_CAP a cycle)."""
        coins = [(r, self.prelim(r, now)) for r in live + finish]
        coins.sort(key=lambda x: (1 if x[1] == "trap" else 0, x[0]["age"]))
        todo = [r for r, _ in coins if (self.work.get(r["a"]) or {}).get("dev") not in ("ok", "skip")]
        if todo and self.src.use("dev_check"):
            left = self.http.rpc_left
            cap = DEV_RPC_CAP if left is None else min(left, DEV_RPC_CAP)
            self.http.rpc_left = cap
            ddir = os.path.join(sb, "dev2")
            try:
                F.dev_check(self.http, ddir, [r["a"] for r in todo[:4]], now / 1000.0)
            finally:
                used = cap - max(0, self.http.rpc_left or 0)
                self.http.rpc_left = None if left is None else max(0, left - used)
            rows, _ = M.load_side(ddir, "dev", M.DEV_COLS)
            for r in todo[:4]:
                w = self.work.setdefault(r["a"], {})
                row = rows.get(r["a"])
                w["devTries"] = w.get("devTries", 0) + 1
                if row is not None:
                    w["devRow"] = row
                    w["devWallet"] = row.get("devWallet")
                w["dev"] = "ok" if row is not None and row.get("devSold") is not None else ("skip" if w["devTries"] >= 3 else "pending")
        pf_deep, swap, fund = PF_DEEP_CAP, self.swap_candles(coins, now, SWAP_CAP), FUND_CAP
        mint_done = False
        wallets = self.cache["wallets"]
        for r, verdict in coins:
            a = r["a"]
            w = self.work.setdefault(a, {})
            if time.time() > (self.http.until or 0):
                break
            mint = self.mint_of(a, r)
            if not mint_done and verdict != "trap" and not mint and a not in self.cache["mint"] and self.src.use("rpc_mint_time") \
                    and (self.http.rpc_left or 0) >= 3:
                mint_done = True
                t = self.src.mint_time(a)
                if t is not None:                 # 0: the pages did not reach the mint (unknown, not asked again); None: no answer (asked again)
                    self.cache["mint"][a] = t
                mint = self.mint_of(a, r)
            creator = self.creator_of(a, r)
            if creator and self.src.use("rpc_dev_age"):
                if creator not in wallets and self.http.rpc_left:
                    res = self.src.wallet_age(creator, "rpc_dev_age")
                    if res is not None:
                        wallets[creator] = dict(res, used=now)
                w["devage"] = "ok" if creator in wallets else "pending"
            if creator and self.src.use("pf_dev_history"):
                dc = self.cache["dev"].get(creator)
                if (not isinstance(dc, dict) or "rows" not in dc or now - (num(dc.get("t")) or 0) > DEV_TTL) and pf_deep > 0:
                    n0 = self.http.n
                    res = self.src.pf_dev(creator, now)
                    pf_deep -= max(1, self.http.n - n0)
                    if res is not None:
                        self.cache["dev"][creator] = dict(res, t=now)
                w["devhist"] = "ok" if "rows" in (self.cache["dev"].get(creator) or {}) else "pending"
            if self.pumpish(r):
                if self.src.use("swap_trades") and "trades" not in w and swap >= 3:
                    n0 = self.http.n
                    tr = self.src.pf_trades(a, mint, pages=3)
                    swap -= max(1, self.http.n - n0)
                    if tr is not None:
                        w["trades"] = tr
                if self.src.use("pf_top_holders") and "pfholders" not in w and mint and pf_deep > 0:
                    n0 = self.http.n
                    ho = self.src.pf_holders(a, mint, skip=self.pools_of(a, r))
                    pf_deep -= max(1, self.http.n - n0)
                    if ho is not None:
                        w["pfholders"] = ho
            holders = self.holders_of(a)
            if holders and self.src.use("rpc_holder_age"):
                for owner, _ in holders:
                    wc = wallets.get(owner)
                    if wc is None:
                        if not self.http.rpc_left:
                            break
                        res = self.src.wallet_age(owner, "rpc_holder_age")
                        if res is None:
                            break
                        wallets[owner] = dict(res, used=now)
                    else:
                        wc["used"] = now
                if self.src.use("rpc_funding"):
                    for owner, _ in holders:
                        wc = wallets.get(owner)
                        if not wc or "by" in wc or RS.wallet_fresh(wc, now) is not True:
                            continue
                        if not wc.get("sig"):
                            wc["by"] = None
                            continue
                        if fund <= 0 or not self.http.rpc_left:
                            break
                        fund -= 1
                        fu = self.src.funder(owner, wc["sig"])
                        if fu is None:
                            break
                        wc.update(by=fu.get("by"), at=fu.get("at"))
                known = all(o in wallets for o, _ in holders)
                funded = not self.src.use("rpc_funding") or all("by" in wallets[o] for o, _ in holders if o in wallets and RS.wallet_fresh(wallets[o], now))
                w["holders"] = "ok" if known and funded else "pending"

    def swap_candles(self, coins, now, budget):
        """swap-api's 1-minute candles from the mint of up to SWAP_STAIR_N pump.fun coins a cycle (oldest pool first): the closes from the
        pool's open (the staircase so far, instead of a GeckoTerminal call) and the curve's last 15 closes before the pool (the staircase
        before the pool, measured only). A coin is asked at first sight, again at 6 and at 8.5 minutes. Returns the budget left."""
        if not self.src.use("swap_candles"):
            return budget
        n = 0
        for r, _ in sorted(coins, key=lambda x: -x[0]["age"]):
            if budget <= 0 or n >= SWAP_STAIR_N or time.time() > (self.http.until or 0):
                break
            a = r["a"]
            w = self.work.setdefault(a, {})
            last = w.get("swapAge")
            if not self.swap_stair(r) or not (last is None or last < 6.0 <= r["age"] or (last < 8.0 and r["age"] >= 8.5)):
                continue
            n0 = self.http.n
            cands = self.src.pf_candles(a)
            budget -= max(1, self.http.n - n0)
            n += 1
            if cands is None:
                continue
            w["swapAge"] = r["age"]
            pool = num(r["pr"].get("pairCreatedAt")) or 0
            pool_c = [c for c in cands if c[0] > pool - 60_000]       # the minute the pool opened in, and later (as GeckoTerminal's)
            curve_c = [c for c in cands if c[0] <= pool - 60_000]     # whole minutes before the pool: the curve
            if not pool_c and len(cands) >= 100:
                w["swapc"] = "nopool"            # the 100 minutes from the mint end before the pool: GeckoTerminal measures it
                continue
            w["swapc"] = "ok"
            self.closes[a] = (r["age"], [c[4] for c in pool_c if c[4]][:15])
            if curve_c:
                w["curve"] = [c[4] for c in curve_c if c[4]][-15:]
        return budget

    def pools_of(self, a, r):
        """The coin's pool accounts (DexScreener's pair, pump.fun's PumpSwap pool): holders, not buyers."""
        return {x for x in (r["pr"].get("pairAddress"), (self.cache["pf"].get(a) or {}).get("pool")) if x}

    def holders_of(self, a):
        """The top 10 holders of RugCheck's report ([owner, pct]), without the wallets the wallet memory calls common (pools, programs)."""
        rep = (self.cache["rc"].get(a) or {}).get("rep") or {}
        common = set((self.wm or {}).get("common") or [])
        out = []
        for h in rep.get("topHolders") or []:
            o = F.addr_of((h or {}).get("owner"))
            if o and o not in common and o != a:
                out.append([o, fin(h.get("pct"), 3)])
        return out[:10]

    def mint_of(self, a, r):
        """The mint time (ms): pump.fun's list row or coins-v3, LaunchLab's createdAt, Jupiter's createdAt, then the RPC's oldest
        signature; None when none is known."""
        meta = self.cache["pf"].get(a) or {}
        ll = (r["pr"].get("ll") or {}) if r else {}
        return num(meta.get("t")) or M.parse_ms(ll.get("createdAt")) or num((self.cache["jup"].get(a) or {}).get("t")) or num(self.cache["mint"].get(a)) or None

    def prelim(self, r, now):
        try:
            S, _ = self.signals(r, now)
            return self.T.rate(S, self.W).get("verdict")
        except Exception:
            return "watch"

    # ---------------------------------------------------------------- signals and rating
    def signals(self, r, now):
        """The radar's merged coin dict for traps.signals_radar: every S key the radar can read itself (module docstring of traps) plus
        the raw parts; S = these, with traps' own reading winning where it knows a value."""
        c = self.coin(r, now)
        try:
            S2 = self.T.signals_radar(c) or {}
        except Exception as e:
            self.say("traps.signals_radar failed on %s (%s): the radar's own reading is used" % (c.get("sym"), RS.short(e)))
            S2 = {}
        S = {k: c.get(k) for k in S_KEYS}
        for k, v in S2.items():
            if v is not None:
                if k in S and S[k] is not None and S[k] != v and k not in self.mismatch_said and not isinstance(v, (dict, list)):
                    self.mismatch_said.add(k)
                    self.say("signal %s: traps reads %r, the radar %r (traps wins)" % (k, v, S[k]))
                S[k] = v
        return S, c

    def coin(self, r, now):
        """The merged coin dict c that traps.signals_radar(c) reads, in the shape traps.py documents for it (WP1):
          - now, addr, sym, name, dex, pool and mint (ms), first (first sight), px, liq, mc, m5, buys, socN, x, paid, lists, rc (RugCheck's
            report, trimmed by radar_src.rc_trim; None without one), wm (walletmem), devSold, creatorPct, dev {"n", "dead", "grad",
            "ageH", "txs"}, xUsed, tweetShared, snip30, snip30N, slotN, slotPct, freshN, freshOf, fundN, fundMin, closes (minute closes
            from the pool's open). The top holders come from rc, so traps' wallet check reads the same holders as the radar's;
          - every other S key at the top level, read by the radar itself (S_KEYS: instantPool, mintToPoolS, swAvg, rugHolders,
            wmChecked, wmState, brand, rcReport, rcDanger, rcWarn, cluster, netSize, creatorSold, ageMin, xKind, tweet, stair, pumpswap,
            devN, devDead, devGrad, devAgeH, devTxs); None = unknown. The record's sig keeps every S_KEYS value (traps.fit reads them);
          - the radar's own parts: pair (memebot's merged pair), f (memebot's factors), rcStatus (ok/404/429/err/pending), pf (pump.fun
            facts), devRow (fetch.dev_check's row), top10 ([owner, pct] of the top 10 without wm.common), funders ([owner, funder, ms]
            of fresh holders), devWallet, devTx (= devTxs), holdersN, stairCurve (the staircase of the curve's last closes before the
            pool, from swap-api's candles: measured, no weight).
        launch_radar takes traps' reading where it knows a value, the radar's own where traps returns None (signals())."""
        a, pr, b, f = r["a"], r["pr"], r["basic"], r["f"]
        rcc = self.cache["rc"].get(a) or {}
        rep = rcc.get("rep") if isinstance(rcc.get("rep"), dict) else None
        st = rcc.get("st") or (self.work.get(a) or {}).get("rc") or "pending"
        pool = num(pr.get("pairCreatedAt"))
        mint = self.mint_of(a, r)        # raw: traps decides what a pool "before" its mint means (thresholds.mintSkewS), and so does gap()
        meta = self.cache["pf"].get(a) or {}
        w = self.work.get(a) or {}
        rec = self.rec(a) or {}
        c = {"addr": a, "sym": str(pr.get("symbol") or "?")[:24], "name": str(pr.get("name") or "")[:48], "now": now, "pool": pool, "mint": mint,
             "dex": str(pr.get("dexId") or "")[:24] or None, "first": num(rec.get("first")) or now, "px": num(b.get("price")),
             "pair": pr, "f": f, "rc": rep, "rcStatus": st, "pf": meta, "devRow": w.get("devRow"), "wm": self.wm, "wmState": self.wm_state(now)}
        c["mintToPoolS"], c["instantPool"] = self.gap(pool, mint)
        top10 = self.holders_of(a)
        c["top10"] = top10
        if c["wmState"] == "ok" and rep is not None:
            wl = self.T.walletmem_lookup([h.get("owner") for h in rep.get("topHolders") or [] if isinstance(h, dict) and h.get("owner")], self.wm, now) or {}
            c["swAvg"], c["rugHolders"], c["wmChecked"] = wl.get("swAvg"), wl.get("rugHolders"), bool(wl.get("checked"))
        else:
            c["swAvg"], c["rugHolders"], c["wmChecked"] = None, None, False
        brand = self.W.get("brand") if isinstance(self.W, dict) else None
        try:
            rx = re.compile(brand, re.I) if isinstance(brand, str) and brand else None
        except re.error:
            rx = None
        # the brand list comes only from radar_weights.json (I7): without one the check is unknown, never passed
        c["brand"] = bool(rx.search("%s %s" % (pr.get("symbol") or "", pr.get("name") or ""))) if rx else None
        c["buys"] = num(pr.get("buysH1"))
        c["rcReport"] = True if rep is not None else (False if st == "404" else None)
        lvl = lambda x: str((x or {}).get("level") or "").lower()
        c["rcDanger"] = [str(x.get("name"))[:60] for x in (rep or {}).get("risks") or [] if lvl(x) == "danger"] if rep is not None else None
        c["rcWarn"] = [str(x.get("name"))[:60] for x in (rep or {}).get("risks") or [] if lvl(x) == "warn"] if rep is not None else None
        net = num((rep or {}).get("graphInsidersDetected"))
        c["netSize"] = RS.net_size(rep)
        c["cluster"] = (bool(net and net > 50) or any("holder correlation" in n.lower() for n in (c["rcWarn"] or []) + (c["rcDanger"] or []))) if rep is not None else None
        drow = w.get("devRow") or {}
        c["creatorSold"] = (bool(drow.get("devSold")) if drow.get("devSold") is not None else None) if drow else None
        c["devSold"] = c["creatorSold"]
        c["m5"] = num(pr.get("chgM5"))
        c["socN"] = num(pr.get("socials"))
        c["ageMin"] = (now - pool) / 60_000.0 if pool else None
        x = M.x_link(pr) or (meta.get("x") if re.match(r"^https://(www\.)?(x|twitter)\.com/", str(meta.get("x") or "")) else "") or ""
        c["x"] = x
        nx = self.norm_x(x)
        c["xKind"] = nx[0] if nx else None
        c["paid"] = self.cache["paid"].get(a)
        c["tweet"] = (c["xKind"] == "tweet") if x else False
        c["lists"] = num(f.get("srcN"))
        cl = self.closes.get(a)
        c["closes"] = list(cl[1]) if cl and cl[1] else None
        try:
            c["stair"] = self.T.staircase(cl[1], n_min=10) if cl and cl[1] else None
        except Exception:
            c["stair"] = None
        cv = w.get("curve")
        try:
            c["stairCurve"] = self.T.staircase(cv, n_min=10) if cv and len(cv) >= 2 else None
        except Exception:
            c["stairCurve"] = None
        c["mc"], c["liq"] = num(b.get("mc")), num(b.get("liq"))
        cp = None
        if rep is not None:
            sup, bal = num((rep.get("token") or {}).get("supply")), num(rep.get("creatorBalance"))
            cp = bal / sup * 100 if sup and bal is not None else None
        c["creatorPct"] = cp if cp is not None else num(drow.get("devPct"))
        c["pumpswap"] = str(pr.get("dexId") or "").lower() == "pumpswap"
        creator = self.creator_of(a, r)
        c["devWallet"] = creator
        dh = self.cache["dev"].get(creator) if creator else None
        rows = [x for x in (dh or {}).get("rows") or [] if isinstance(x, list) and len(x) >= 3 and x[0] != a] if isinstance(dh, dict) and "rows" in dh else None
        cnt = num((dh or {}).get("count")) if rows is not None else None      # all the dev's launches, this coin included
        c["devN"] = (max(len(rows), int(cnt) - 1) if cnt is not None else len(rows)) if rows is not None else None    # earlier launches
        c["devDead"] = sum(1 for x in rows if x[2]) if rows is not None else None
        c["devGrad"] = sum(1 for x in rows if x[1]) if rows is not None else None
        tok = (rep or {}).get("creatorTokens") if self.src.use("rc_creator_tokens") else None
        if isinstance(tok, list):
            rc_n = len([t for t in tok if isinstance(t, dict) and t.get("mint") != a])
            rc_dead = len([t for t in tok if isinstance(t, dict) and t.get("mint") != a and (num(t.get("marketCap")) or 0) < 10_000])
            c["devN"] = max(rc_n, c["devN"] or 0)
            c["devDead"] = max(rc_dead, c["devDead"] or 0)
        wa = self.cache["wallets"].get(creator) if creator else None
        fresh_dev = RS.wallet_fresh(wa, now) if wa else None
        c["devAgeH"] = round((now - wa["first"]) / H, 2) if wa and wa.get("first") and not (wa.get("full") and fresh_dev is None) else None   # full: a lower bound
        c["devTx"] = c["devTxs"] = (wa.get("n") if not wa.get("full") else 1000) if wa else None
        c["dev"] = {"n": c["devN"], "dead": c["devDead"], "grad": c["devGrad"], "ageH": c["devAgeH"], "txs": c["devTx"]}
        c["xUsed"], c["tweetShared"] = self.x_reuse(a, x, nx, mint if mint and mint > TIME_MIN_MS else c["first"])
        tr = w.get("trades") if isinstance(w.get("trades"), dict) and not w["trades"].get("many") else {}
        ho = w.get("pfholders") or {}
        pick = lambda k1, k2: num(tr.get(k1)) if tr.get(k1) is not None else num(ho.get(k2))
        c["snip30"], c["snip30N"] = pick("snip30", "snip30"), pick("snip30N", "snip30N")
        c["slotN"], c["slotPct"] = pick("slotN", "bundN"), pick("slotPct", "bundPct")
        fresh, funders, n_known = 0, [], 0
        exch = self.exch
        for o, _ in top10:
            wc = self.cache["wallets"].get(o)
            fr = RS.wallet_fresh(wc, now) if wc else None
            if fr is None:
                continue
            n_known += 1
            if fr:
                fresh += 1
                if wc.get("by") and wc["by"] not in exch and wc.get("at"):
                    funders.append([o, wc["by"], wc["at"]])
        all_known = bool(top10) and n_known == len(top10)
        c["freshN"] = fresh if (all_known or n_known >= 5) else None
        c["freshOf"] = n_known if c["freshN"] is not None else None
        c["holdersN"] = n_known
        funded = all_known and all("by" in self.cache["wallets"][o] for o, _ in top10 if RS.wallet_fresh(self.cache["wallets"][o], now))
        fn, fmin = fund_cluster(funders) if funders else (0, None)
        c["fundN"] = fn if (funders or funded) else None
        c["fundMin"] = fmin if c["fundN"] else None
        c["funders"] = funders
        return c

    def exchanges(self):
        """Funders behind 25 or more cached wallets: exchanges and dispensers, not one actor."""
        cnt = {}
        for v in self.cache["wallets"].values():
            if isinstance(v, dict) and v.get("by"):
                cnt[v["by"]] = cnt.get(v["by"], 0) + 1
        return {k for k, n in cnt.items() if n >= 25}

    def x_reuse(self, a, url, nx, t):
        """(xUsed, tweetShared) at t (the coin's mint from any source, else its first sighting: traps.x_reuse's reference, WP1): older
        coins, created xGapS (10 min) or more before, with the same account or community link (C10), and other coins off the same tweet.
        The coin's own time is the earlier of t and its own entry in an index (as traps does). Two indexes: the radar's own (pump.fun's
        lists) and the scan's (radar-feed xlinks, counted by traps.x_reuse: never the coin itself, never a younger coin). They overlap,
        so the larger count is taken."""
        if not nx:
            return 0, 0
        kind, key = nx
        gap = num(self.thresholds().get("xGapS"))
        gap = gap if gap is not None else 600.0
        idx = self.cache["xidx"].get(key) or {}
        if num(idx.get(a)):
            t = min(t, num(idx[a]))
        local = {b: tb for b, tb in idx.items() if b != a}
        fe = {}
        if self.xlinks and hasattr(self.T, "x_reuse"):
            try:
                fe = self.T.x_reuse(url, a, t, self.xlinks, gap) or {}
            except Exception as e:
                self.say("traps.x_reuse failed (%s): the radar's own X-link index only" % RS.short(e))
        n = lambda k: int(num(fe.get(k)) or 0) if isinstance(fe, dict) else 0
        if kind == "tweet":
            return 0, max(len(local), n("shared"))
        older = [b for b, tb in local.items() if num(tb) and tb <= t - gap * 1000]
        return max(len(older), n("used")), 0

    def rate(self, r, now, record_only=False):
        """traps.rate on the coin's signals; the record gets the rating (every one, at most 5), its first good moment and its signals."""
        a = r["a"]
        S, c = self.signals(r, now)
        self.last_c[a] = c
        rt = self.T.rate(S, self.W) or {}
        try:
            line = [list(x)[:2] for x in (self.T.chips(rt, S) or [])][:8]
        except Exception:
            line = []
        v = rt.get("verdict") if rt.get("verdict") in ("good", "watch", "trap") else "watch"
        rec = self.rec(a) or self.new_rec(a, now, r)
        rec["sym"] = str(r["pr"].get("symbol") or rec.get("sym") or "?")[:24]
        if len(rec["rt"]) < 5:
            rec["rt"].append([now, v, fin(rt.get("pts")), 1 if rt.get("push") else 0])
        if v == "good" and not rec.get("good") and not record_only:
            rec["good"], rec["goodPx"] = now, fin(r["basic"].get("price"))
        mint = self.mint_of(a, r)
        rec["mint"] = int(mint) if mint else rec.get("mint")
        rec["lp"] = rec.get("lp") or M.launchpad_of(r["pr"], (self.cache["rc"].get(a) or {}).get("rep"))[0]
        rec["sig"] = sig_of(S, self.coin_extra(a, r, S, c))
        rec["chk"] = self.chk(a, S, now, record_only)
        self.touch(a, now)
        zp, up = M.chances(self.train[0], self.train[1], r["f"]) if self.train[0] or self.train[1] else (None, None)
        pr, b = r["pr"], r["basic"]
        d = {k: fin(S.get(k), 3) for k in D_KEYS if fin(S.get(k)) is not None}
        for key, st in (("stair", S.get("stair")), ("stairCurve", c.get("stairCurve"))):
            if isinstance(st, dict):
                d[key] = stair_doc(st)
        if up is not None:                       # the trained odds, info only (the page says: not used on coins under 1 h)
            d["upP"] = fin(up, 3)
        if zp is not None:
            d["zeroP"] = fin(zp, 3)
        d["score"] = fin(r.get("sc"), 1)
        doc = {"addr": a, "sym": rec["sym"], "name": str(pr.get("name") or "")[:48], "pair": pr.get("pairAddress") or None, "dex": str(pr.get("dexId") or "")[:24] or None,
               "lp": rec.get("lp"), "pool": int(num(pr.get("pairCreatedAt"))), "mint": rec.get("mint"), "age": round(r["age"], 1), "px": fin(b.get("price")),
               "mc": fin(b.get("mc"), 2), "liq": fin(b.get("liq"), 2), "m5": fin(pr.get("chgM5"), 2), "buys": fin(pr.get("buysH1")), "sells": fin(pr.get("sellsH1")),
               "x": S.get("x") or "", "v": v, "pts": fin(rt.get("pts"), 2), "up": fin(rt.get("upside"), 2),
               "hard": list(rt.get("hard") or [])[:8], "soft": list(rt.get("soft") or [])[:8], "plus": list(rt.get("plus") or [])[:8],
               "info": list(rt.get("info") or [])[:10], "unknown": list(rt.get("unknown") or [])[:8], "n": rt.get("n"), "line": line, "d": d,
               "first": rec["first"], "push": rec.get("push"), "found": rec.get("found") or found_of(pr)}
        return {"addr": a, "sym": rec["sym"], "v": v, "pts": num(rt.get("pts")) or 0.0, "up": num(rt.get("upside")) or 0.0, "liq": num(b.get("liq")),
                "push_ok": bool(rt.get("push")) and r["age"] < MAX_AGE_MIN and not record_only, "doc": doc, "age": r["age"]}

    def coin_extra(self, a, r, S, c):
        rep = (self.cache["rc"].get(a) or {}).get("rep") or {}
        cl = self.closes.get(a)
        return {"x": S.get("x") or "", "dev": c.get("devWallet"), "holders": c.get("top10") or [],
                "funders": [[o, b, t] for o, b, t in (c.get("funders") or [])][:10],
                "closes": list(cl[1])[:15] if cl else [], "stairCurve": stair_doc(c["stairCurve"]) if isinstance(c.get("stairCurve"), dict) else None,
                "rc": {"danger": list(S.get("rcDanger") or [])[:6], "warn": list(S.get("rcWarn") or [])[:6], "score": fin(rep.get("score_normalised") if rep.get("score_normalised") is not None else rep.get("score"))}}

    def chk(self, a, S, now, record_only):
        w = self.work.get(a) or {}
        st = (self.cache["rc"].get(a) or {}).get("st") or w.get("rc") or "pending"
        wms = S.get("wmState") if S.get("wmState") in WM_STATES else self.wm_state(now)     # traps' reading of the memory wins
        hold = "off" if not self.src.use("rpc_holder_age") else ("ok" if w.get("holders") == "ok" else "skip")
        tr = w.get("trades") if isinstance(w.get("trades"), dict) and not w["trades"].get("many") else None
        trades = "off" if not (self.src.use("swap_trades") or self.src.use("pf_top_holders")) else \
            ("ok" if tr or (w.get("pfholders") or {}).get("snip30") is not None else "skip")
        return {"rc": st if st in ("ok", "404", "429", "err") else "pending", "mint": "ok" if S.get("mintToPoolS") is not None else "unknown",
                "wm": wms, "dev": "ok" if w.get("dev") == "ok" else ("err" if w.get("dev") == "err" else "skip"),
                "holders": hold, "trades": trades, "candles": "ok" if self.closes.get(a) else "skip"}

    def outcomes(self, now):
        """traps.outcome once the 60-minute price is in (again when the peak within the hour comes later)."""
        for doc in self.docs.values():
            for a, rec in (doc.get("coins") or {}).items():
                if "60" in (rec.get("later") or {}) and (rec.get("out") is None or (rec.get("peak60") and a not in self.out_pk)):
                    try:
                        o = self.T.outcome(rec)
                    except Exception as e:
                        self.say("outcome of %s failed (%s)" % (rec.get("sym"), RS.short(e)))
                        continue
                    if isinstance(o, dict):
                        rec["out"] = {"rug1h": o.get("rug1h") if isinstance(o.get("rug1h"), bool) else None,
                                      "win1h": o.get("win1h") if isinstance(o.get("win1h"), bool) else None, "x60": fin(o.get("x60"), 4)}
                        if rec.get("peak60"):
                            self.out_pk.add(a)
                        doc["upd"] = now

    def to_push(self, coins, now):
        """The good coins that get a notification now (3.6): pushable (no holder cluster, nothing unknown), pool under 10 min, never
        pushed before, fewer than 4 radar notifications in the last hour, pushed.json restored."""
        if not (self.notifier or (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY"))):
            return []                            # no app store: no notification channel, nothing is marked
        if self.restore_state != "ok":
            if any(x["push_ok"] for x in coins):
                self.note("pushed list not restored: no notifications this run")
            return []
        recent = {t for t in self.pushed.values() if now - t < H}
        if len(recent) >= PUSH_PER_H:
            return []
        return [x for x in coins if x["push_ok"] and x["addr"] not in self.pushed]

    # ---------------------------------------------------------------- radar.json
    def summary(self, now):
        """The record line (3.4) and the model's data count over results' 30 days and the local 48 hours."""
        by = {r["addr"]: r for r in self.res_summary}
        for doc in self.docs.values():
            for rec in (doc.get("coins") or {}).values():
                s = summ(rec)
                if s:
                    by[s["addr"]] = s
        calls = [s for s in by.values() if s["good"]]
        n60 = [s for s in calls if s["p60"] is not None or s["gone"]]
        rug = [s for s in calls if s["rug"] is not None]
        win = [s for s in calls if s["win"] is not None]
        p = {"ticket": TICKET, "grp": "young", "paper": M.PAPER_RULE}
        eur = sum(M.pos_value(p, 1.0, 0.0 if s["gone"] else (s["p60"] / s["goodPx"])) - TICKET for s in n60 if s["gone"] or (s["goodPx"] and s["p60"]))
        rec = {"calls": len(calls), "n60": len(n60), "rug": round(sum(1 for s in rug if s["rug"]) / len(rug), 3) if rug else None,
               "win": round(sum(1 for s in win if s["win"]) / len(win), 3) if win else None, "eur": round(eur, 2) if n60 else None,
               "ci": {"rug": wilson(sum(1 for s in rug if s["rug"]), len(rug)), "win": wilson(sum(1 for s in win if s["win"]), len(win))}}
        n_out = sum(1 for s in by.values() if s["rug"] is not None)
        return rec, n_out, by

    def build_doc(self, state, coins, others, rated, now, nxt, secs, k):
        record, n_out, _ = self.summary(now)
        hosts = {}
        for host, label in RS.HOST_LABEL.items():
            used = [n for n, hs in RS.ADAPTER_HOST.items() if host in hs]
            if used and not any(self.src.use(n) for n in used):
                hosts[label] = "off"
            else:
                st = self.http.state(host)
                if st != "unused" or label not in hosts:
                    hosts[label] = st
        notes = list(self.notes_run)
        rc_host = "api.rugcheck.xyz"
        miss = sum(1 for x in rated if (self.cache["rc"].get(x["addr"]) or {}).get("st") != "ok")
        if self.http.state(rc_host) == "limited" and miss:
            notes.append("RugCheck limited: %d coin%s not fully checked" % (miss, "" if miss == 1 else "s"))
        elif self.http.state(rc_host) == "down":
            notes.append("RugCheck down: no coin can be without traps")
        wms = self.wm_state(now)
        if wms != "ok":
            why = {"old": "wallet memory older than %g h" % ((num(self.thresholds().get("wmMaxAgeH")) or WM_MAX_AGE / H)),
                   "small": "wallet memory too small: %d of %d coins" % (num((self.wm or {}).get("nCoins")) or 0, num(self.thresholds().get("wmMinCoins")) or WM_MIN_COINS),
                   "empty": "wallet memory empty"}.get(wms, "no wallet memory yet")
            notes.append("wallet check unavailable (%s): no coin can be without traps" % why)
        for n in self.src.off_why:
            notes.append("%s not checked (source down)" % n.replace("_", " "))
        good_recs = [(a, rec) for doc in self.docs.values() for a, rec in (doc.get("coins") or {}).items() if rec.get("good")]
        last_good = None
        for a, rec in good_recs:
            at = max([t for t, v, _, _ in rec.get("rt") or [] if v == "good"] or [rec["good"]])
            if last_good is None or at > last_good["at"]:
                last_good = {"addr": a, "sym": rec.get("sym"), "at": at}
        if last_good is None and isinstance(self.last_doc, dict) and isinstance(self.last_doc.get("lastGood"), dict):
            last_good = self.last_doc["lastGood"]
        recent = []
        for a, rec in sorted(good_recs, key=lambda x: -x[1]["good"]):
            if now - rec["good"] > 3 * H:
                continue
            gp = num(rec.get("goodPx"))
            lt = {}
            for m in LATER:
                o = (rec.get("later") or {}).get(str(m))
                lt[str(m)] = 0.0 if isinstance(o, dict) and o.get("gone") else (round(o["px"] / gp, 3) if isinstance(o, dict) and num(o.get("px")) and gp else None)
            pk = rec.get("peak60") if isinstance(rec.get("peak60"), dict) and fin(rec["peak60"].get("x")) is not None else None
            recent.append({"addr": a, "sym": rec.get("sym"), "good": rec["good"], "push": rec.get("push"), "later": lt,
                           "peak60": {"x": fin(pk.get("x"), 4), "at": pk.get("at")} if pk else None, "out": rec.get("out")})
        seen_ages = sorted(num(rec.get("seenAge")) for doc in self.docs.values() for rec in (doc.get("coins") or {}).values()
                           if num(rec.get("seenAge")) is not None and now - (num(rec.get("first")) or 0) < 3 * H)
        med = seen_ages[len(seen_ages) // 2] if seen_ages else None
        enough = (num(self.model.get("n")) or 0) >= MODEL_NEED       # under it the page says "radar data n of 300 needed" itself
        model = {"from": self.model.get("from") or "prior", "n": n_out, "need": MODEL_NEED, "auc": fin(self.model.get("auc"), 3),
                 "prior": fin(self.model.get("aucPrior"), 3), "at": self.model.get("at"), "why": str(self.model.get("why") or "")[:200] if enough else ""}
        doc = {"v": 1, "kind": "radar", "t": now, "next": nxt, "run": {"id": str(self.run_id)[:40], "start": self.run_start, "end": self.run_end, "cycle": k, "source": self.source},
               "state": state, "why": "", "secs": secs, "model": model,
               "counts": {"seen": len(rated), "good": len(coins), "pushed": sum(1 for x in rated if (self.rec(x["addr"]) or {}).get("push")), "seenAgeMed": fin(med, 1)},
               "wm": {"t": num((self.wm or {}).get("t")), "nCoins": num((self.wm or {}).get("nCoins"))},
               "coins": [dict(x["doc"], push=(self.rec(x["addr"]) or {}).get("push")) for x in coins],
               "others": [{"addr": x["addr"], "sym": x["sym"], "age": x["doc"]["age"], "v": x["v"], "pts": x["doc"]["pts"], "line": x["doc"]["line"]} for x in others[:40]],
               "lastGood": last_good, "recent": recent[:20], "record": record, "hosts": hosts, "notes": notes[:6], "lines": list(self.cycle_lines)}
        return fit_size(doc)

    def finish_doc(self, state, now, why):
        """radar.json in state off or hours (the coins of the last list are dropped, the record line, model and last good coin stay),
        pushed once to radar-data and the app's row."""
        prev = self.last_doc if isinstance(self.last_doc, dict) else {}
        doc = finish_from(prev, state, now, why, self.run_id, self.run_start, self.run_end, self.source, self.hours)
        self.publish(doc)
        self.store_row(doc)
        self.last_doc = doc
        return doc

    def maybe_fit(self, now):
        """traps.fit at the first cycle of a UTC day, and when the records with an outcome pass the next hundred (4.8)."""
        _, n_out, _ = self.summary(now)
        at = num(self.model.get("at"))
        due = (at is None or utc_hour(at)[:10] != utc_hour(now)[:10]) or n_out // 100 > int(num(self.model.get("nOut")) or 0) // 100
        if not due:
            return
        recs = []
        for f in glob.glob(os.path.join(self.res, "db", "memeradar", "*.json")):
            doc = load_json(f)
            for a, rec in ((doc or {}).get("coins") or {}).items() if isinstance(doc, dict) else []:
                if isinstance(rec, dict):
                    recs.append(rec)
        local = {a: rec for doc in self.docs.values() for a, rec in (doc.get("coins") or {}).items()}
        recs = [r for r in recs if r.get("addr") not in local] + list(local.values())
        try:
            W2, rep = self.T.fit(recs, self.W_prior, now)
        except Exception as e:
            self.say("radar model not fitted (%s): the study prior stays" % RS.short(e))
            W2, rep = None, {"why": "fit failed: %s" % RS.short(e)}
        rep = rep if isinstance(rep, dict) else {"why": str(rep)[:200]}
        self.model = {"v": 1, "from": "learned" if isinstance(W2, dict) else "prior", "at": now, "n": n_out, "nOut": n_out, "need": MODEL_NEED, "src": self.W_prior.get("src"),
                      "auc": fin(rep.get("auc"), 4), "aucPrior": fin(rep.get("aucPrior"), 4), "why": str(rep.get("why") or "")[:300],
                      "w": clean_json(W2) if isinstance(W2, dict) else None, "report": clean_json(rep)}
        self.W = self.model["w"] if isinstance(W2, dict) else self.W_prior
        self.say("radar model: %s (%d records with an outcome%s)" % (self.model["from"], n_out, ("; " + self.model["why"]) if self.model["why"] else ""))


S_KEYS = ("instantPool", "mintToPoolS", "swAvg", "rugHolders", "wmChecked", "brand", "buys", "rcReport", "rcDanger", "rcWarn", "cluster", "netSize",
          "creatorSold", "m5", "socN", "ageMin", "x", "xKind", "paid", "tweet", "lists", "stair", "mc", "liq", "creatorPct", "pumpswap",
          "devN", "devDead", "devGrad", "devAgeH", "devTxs", "xUsed", "tweetShared", "snip30", "snip30N", "slotN", "slotPct", "freshN", "freshOf",
          "fundN", "fundMin", "wmState")
D_KEYS = ("mintToPoolS", "swAvg", "rugHolders", "buys", "m5", "socN", "lists", "mc", "liq", "creatorPct", "netSize", "devN", "devDead", "devGrad", "devAgeH",
          "devTxs", "freshOf", "fundMin",
          "xUsed", "tweetShared", "snip30", "snip30N", "slotN", "slotPct", "freshN", "fundN")


def rank(rated, n=BEST_N):
    """The order of 3.2 over the rated coins: good coins by (-upside, pts, -liq), then watch coins by (pts, -liq), then trap coins by
    pts. Returns (top, coins, others): the best n, the good ones among them (the main list) and every coin that is not good (the fold)."""
    liq = lambda x: -(x["liq"] or 0)
    order = sorted([x for x in rated if x["v"] == "good"], key=lambda x: (-x["up"], x["pts"], liq(x))) + \
        sorted([x for x in rated if x["v"] == "watch"], key=lambda x: (x["pts"], liq(x))) + \
        sorted([x for x in rated if x["v"] == "trap"], key=lambda x: x["pts"])
    top = order[:n]
    return top, [x for x in top if x["v"] == "good"], [x for x in order if x["v"] != "good"]


def stair_doc(st):
    """A staircase reading (traps.staircase) in the docs' few numbers."""
    return {k: fin(st.get(k), 3) if not isinstance(st.get(k), bool) else st.get(k) for k in ("n", "rise", "green", "pull", "stair")}


def clean_json(v, depth=0):
    """v as strict JSON: non-finite numbers become None, other objects their text, at most 8 levels deep."""
    if depth > 8:
        return None
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): clean_json(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [clean_json(x, depth + 1) for x in v]
    return str(v)[:200]


def later_points(rec):
    """The record's later DexScreener prices as peak.peak_of's ds_points [(ms, price or None, liquidity or None)]; a pool found gone is
    (ms, None, 0), so the glitch filter cuts a dead pool's prints."""
    out = []
    for o in (rec.get("later") or {}).values() if isinstance(rec.get("later"), dict) else ():
        if isinstance(o, dict) and num(o.get("t")):
            out.append((int(o["t"]), None, 0.0) if o.get("gone") else (int(o["t"]), num(o.get("px")), num(o.get("liq"))))
    return sorted(out)


def rec_weight(rec):
    """Which of two copies of a record knows more (a restore merges the local and the branch copies)."""
    return (len(rec.get("later") or {}), 1 if rec.get("peak60") else 0, 1 if rec.get("out") else 0, len(rec.get("rt") or []), 1 if rec.get("push") else 0)


def found_of(pr):
    return [str(t)[:24] for t in (pr.get("tags") or []) if not str(t).startswith("kw:")][:8]


def fund_cluster(funders):
    """The most top holders funded by one wallet within 15 minutes ([[owner, funder, ms], ...]) and the minutes they span: (n, min)."""
    best, span = 0, None
    by = {}
    for _, f, t in funders:
        by.setdefault(f, []).append(t)
    for ts in by.values():
        ts.sort()
        j = 0
        for i in range(len(ts)):
            while ts[i] - ts[j] > 15 * 60_000:
                j += 1
            if i - j + 1 > best:
                best, span = i - j + 1, round((ts[i] - ts[j]) / 60_000.0, 1)
    return best, span


def sig_of(S, extra):
    """The record's signals: every S value (finite numbers, short lists) plus the X link, dev wallet, holders, funders, closes and the
    RugCheck names."""
    out = {}
    for k in S_KEYS:
        v = S.get(k)
        if isinstance(v, bool) or v is None or isinstance(v, str):
            out[k] = v if not isinstance(v, str) else v[:200]
        elif isinstance(v, (int, float)):
            out[k] = fin(v, 4)
        elif isinstance(v, list):
            out[k] = [str(x)[:60] for x in v][:8]
        elif isinstance(v, dict):
            out[k] = {kk: (vv if isinstance(vv, bool) or vv is None else fin(vv, 4)) for kk, vv in v.items() if isinstance(vv, (int, float, bool)) or vv is None}
    out.update(extra)
    return out


def summ(rec):
    """A record in the few numbers the record line and the model count need."""
    a = rec.get("addr")
    if not a:
        return None
    l60 = (rec.get("later") or {}).get("60") if isinstance(rec.get("later"), dict) else None
    out = rec.get("out") if isinstance(rec.get("out"), dict) else {}
    return {"addr": a, "good": num(rec.get("good")), "goodPx": num(rec.get("goodPx")), "p60": num((l60 or {}).get("px")) if isinstance(l60, dict) else None,
            "gone": bool(isinstance(l60, dict) and l60.get("gone")), "rug": out.get("rug1h") if isinstance(out.get("rug1h"), bool) else None,
            "win": out.get("win1h") if isinstance(out.get("win1h"), bool) else None}


def went_out(out):
    """True when a notification reached at least one phone: app.notify's answer says sent >= 1 and nothing skipped (rate guard, no push
    sender, no live store). sent 0 (no phone subscribed, every send failed) is not "pushed" anywhere."""
    return isinstance(out, dict) and not out.get("skipped") and (num(out.get("sent")) or 0) > 0


def push_text(coins):
    """The notification's words (3.6): title "SYM: no trap found (pool 6 min)", "+1 more" for a second coin; body checks, liquidity and
    that it is fake money. Never "buy", "safe" or "clean"."""
    c = coins[0]
    age = num(c.get("age"))
    title = "%s: no trap found%s%s" % (re.sub(r"[\x00-\x1f\x7f]", "", str(c.get("sym") or "?"))[:16],
                                       (" (pool %s min)" % (int(age) if age >= 1 else "<1")) if age is not None else "",
                                       (" +%d more" % (len(coins) - 1)) if len(coins) > 1 else "")
    liq = num(c.get("liq"))
    body = "%s checks passed · liquidity %s · fake money, nothing is bought." % (c.get("n") if c.get("n") is not None else "All", ("$%dk" % round(liq / 1000)) if liq else "unknown")
    return title, body


def fit_size(doc):
    """radar.json at most DOC_MAX bytes: the fold (others) is cut first, then recent, then the record's lines."""
    size = lambda d: len(json.dumps(d, separators=(",", ":")))
    while size(doc) > DOC_MAX and doc["others"]:
        doc["others"] = doc["others"][:len(doc["others"]) // 2] if len(doc["others"]) > 1 else []
    while size(doc) > DOC_MAX and doc["recent"]:
        doc["recent"] = doc["recent"][:-1]
    while size(doc) > DOC_MAX and doc["coins"]:
        for c in doc["coins"]:
            c["d"] = {}
            c["info"] = c["info"][:3]
        if size(doc) > DOC_MAX:
            doc["coins"] = doc["coins"][:-1]
    return doc


def finish_from(prev, state, now, why, run_id, start, end, source, hw):
    keep = {k: prev.get(k) for k in ("model", "lastGood", "recent", "record", "wm") if prev.get(k) is not None}
    nxt = next_start(now, hw) if state == "hours" else None
    doc = {"v": 1, "kind": "radar", "t": now, "next": nxt, "run": {"id": str(run_id)[:40], "start": start, "end": end, "cycle": None, "source": source},
           "state": state, "why": why, "secs": 0.0, "model": {"from": "prior", "n": 0, "need": MODEL_NEED, "auc": None, "prior": None, "at": None, "why": ""},
           "counts": {"seen": 0, "good": 0, "pushed": 0, "seenAgeMed": None}, "wm": {"t": None, "nCoins": None}, "coins": [], "others": [],
           "lastGood": None, "recent": [], "record": {"calls": 0, "n60": 0, "rug": None, "win": None, "eur": None, "ci": {"rug": None, "win": None}},
           "hosts": {}, "notes": [], "lines": []}
    doc.update(keep)
    return doc


# ---------------------------------------------------------------- the hours gate (radar.yml's first step)
def app_row(doc=None, say=None):
    """The app's live store row "radar": doc is written (upsert); without doc the row's current doc is read ({} when there is none).
    None when the store is not set up or did not answer. Never raises; the secret key stays in app.py's request header."""
    try:
        if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY")):
            return None
        import app as A
        if not A.enabled():
            return None
        if doc is not None:
            A.put_row("radar", doc)
            return doc
        rows = A.call("GET", "live?id=eq.radar&select=doc")
        got = rows[0].get("doc") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        return got if isinstance(got, dict) else {}
    except Exception as e:
        if say:
            say("hours: app store row not %s (%s)" % ("written" if doc is not None else "read", RS.short(e)))
        return None


def cmd_hours(a, log=None):
    """Inside the active hours: inside=true. Outside: radar.json state "hours" with the next start, once (not again when the last doc
    already says hours), pushed to radar-data with every other file of the branch as it is, and to the app's row; inside=false.
    radar-data is written only when it exists and was read: when GitHub does not answer, or the fetch fails, nothing goes there (a
    tree of radar.json alone would wipe the records), and a missing branch is left to the first radar run (it starts it from the
    results copy). The app's row is written either way; when radar-data could not be read, the row's own last doc gives the record
    line, the model and the last good coin that the hours doc keeps."""
    say = log or (lambda s: print("radar: " + redact(s), file=sys.stderr, flush=True))
    now = int(a.now) if a.now else int(time.time() * 1000)
    hw = parse_hours(os.environ.get("MEMEBOT_RADAR_HOURS") or "7-24")
    if in_hours(now, hw):
        print("inside=true")
        return 0
    print("inside=false")
    remote = a.remote or os.environ.get("RADAR_URL") or ""
    d = os.path.abspath(a.dir)
    files, prev, ex, read = {}, {}, None, True
    if remote:
        g = Git(os.path.join(d, "git"), remote, say)
        try:
            g.init()
            ex = g.exists("radar-data")
            if ex is None:
                read = False
                say("hours: GitHub did not answer about radar-data: radar-data not written, the app's row only")
            elif ex:
                g.fetch("radar-data", "refs/radar/data")
                files = g.files("refs/radar/data", g.paths("refs/radar/data"))
                prev = json.loads(files.get("radar.json", b"{}").decode("utf-8") or "{}")
        except Exception as e:
            read, files, prev = False, {}, {}
            say("hours: radar-data not read (%s): radar-data not written, the app's row only" % RS.short(e))
    else:
        prev = load_json(os.path.join(d, "out", "radar.json"), {}) or {}
    if not read:
        prev = app_row(say=say)
        if prev is None:                  # no app store, or it did not answer either: nothing is written anywhere
            say("hours: the app's row not read either: nothing written")
            return 0
    if isinstance(prev, dict) and prev.get("state") == "hours":
        say("outside the active hours %d-%d Berlin: radar.json already says so" % hw)
        return 0
    doc = finish_from(prev if isinstance(prev, dict) else {}, "hours", now, "outside the active hours %02d:00-%02d:00 Berlin" % hw,
                      os.environ.get("GITHUB_RUN_ID") or "local", None, None, os.environ.get("RADAR_SOURCE") or "manual", hw)
    if read:
        out = os.path.join(d, "hours")
        shutil.rmtree(out, ignore_errors=True)
        paths = {}
        for p, raw in files.items():
            if p != "radar.json" and safe_path(p):
                fp = os.path.join(out, *p.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "wb") as f:
                    f.write(raw)
                paths[p] = fp
        write_json(os.path.join(out, "radar.json"), doc)
        paths["radar.json"] = os.path.join(out, "radar.json")
        if remote and ex:
            try:
                Git(os.path.join(d, "git"), remote, say).push_tree(paths, "radar-data", "launch radar: outside the active hours (fake money)")
            except Exception as e:
                say("hours: radar-data push failed (%s)" % RS.short(e))
        elif remote:
            say("hours: radar-data does not exist yet: not made here (the first radar run makes it from the results copy)")
        else:
            write_json(os.path.join(d, "out", "radar.json"), doc)
    app_row(doc, say)
    say("outside the active hours %d-%d Berlin: state hours, next start %s UTC" % (hw[0], hw[1], dt.datetime.fromtimestamp(doc["next"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if doc["next"] else "?"))
    return 0


def args_of(argv=None):
    ap = argparse.ArgumentParser(description="the launch radar (fake money only)")
    ap.add_argument("cmd", choices=["loop", "hours"])
    ap.add_argument("--dir", default="rd")
    ap.add_argument("--minutes", type=float, default=DEFAULT_MINUTES, help="at most %d; 0 = until stopped, only without GitHub (a VM)" % MAX_MINUTES)
    ap.add_argument("--cadence", type=float, default=CYCLE_S)
    ap.add_argument("--deadline", type=float, default=None, help="s a cycle may take (default 125 at cadence 150, scaled)")
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    ap.add_argument("--clock", choices=["wall", "fake"], default="wall")
    ap.add_argument("--now", type=float, default=None, help="the fake clock's start (ms)")
    ap.add_argument("--no-github", action="store_true")
    ap.add_argument("--remote", default=None)
    ap.add_argument("--cache", default="rdcache")
    ap.add_argument("--source", default=None)
    ap.add_argument("--horizon", default=os.environ.get("MEMEBOT_HORIZON") or "2h", choices=sorted(M.PROFILES))
    return ap.parse_args(argv)


def main(argv=None, log=None, notifier=None):
    for stream in (sys.stdout, sys.stderr):      # coin names carry emoji
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    a = args_of(argv)
    if a.cmd == "hours":
        return cmd_hours(a, log)
    return Radar(a, log=log, notifier=notifier).loop()


if __name__ == "__main__":
    sys.exit(main())
