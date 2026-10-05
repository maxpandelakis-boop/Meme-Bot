#!/usr/bin/env python3
"""bot.py: one command runs a whole paper-trading cycle. Fake money only, nothing is ever bought for real.

A cycle:
  1. memebot.py mode      what this run needs (a full scan, a light one, or only prices for the open positions)
  2. fetch.py sources     ~1000 coins from DexScreener, RugCheck, GeckoTerminal, CoinGecko, Jupiter, pump.fun, GMGN, news
  3. memebot.py gather    merge everything; fetch full DexScreener data for the addresses that still lack it; gather again
  4. memebot.py shortlist RugCheck reports (and GMGN top buyers) for the best candidates
  5. memebot.py run       exits on the open positions, then the 2 best clean coins at 20 each out of the 40 bankroll
  6. apply out/*.json into db/ (positions, exits, snapshots, learned weights, state)
  7. report.py        renders mb/report.html, the analysis page (open it in a browser)

Usage:
  python3 bot.py cycle   [--dir mb] [--force] [--offline]   one cycle (--force: pick now even inside the 3h gap; --offline: reuse the files in --dir)
  python3 bot.py cycle --rescan                             full scan of the whole universe now, saved for the big test (buys only if a slot is free)
  python3 bot.py loop    [--every 30]                       cycles forever, every N minutes (Ctrl-C to stop)
  python3 bot.py status                                     bankroll, open positions with their last price, closed trades, last note
  python3 bot.py report                                     render mb/report.html from the current db/ without a cycle
  python3 bot.py sync    [--remote URL] [--branch results]  push mb/report.html and the small db docs to a git branch (default:
                                                            the "results" branch of this repository's origin), so the page and
                                                            the picks can be read elsewhere; cycle/loop --push does it after each cycle
  python3 bot.py reset                                      wipe db/ (positions, history, learned weights) and start again with 40
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "python3"


def log(s):
    print(s, file=sys.stderr, flush=True)


def run(args, d, now=None, expect_json=True):
    cmd = [PY, os.path.join(HERE, args[0])] + args[1:] + ["--dir", d]
    if now and args[0] == "memebot.py":
        cmd += ["--now", str(now)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if p.stderr.strip():
        log(p.stderr.rstrip())
    if p.returncode != 0:
        raise SystemExit("%s failed:\n%s" % (" ".join(cmd[1:3]), p.stdout[-2000:]))
    if not expect_json:
        return p.stdout
    try:
        return json.loads(p.stdout)
    except ValueError:
        raise SystemExit("%s printed no JSON:\n%s" % (args[0], p.stdout[-2000:]))


def apply_out(d):
    """out/manifest.json -> db/<collection>/<doc_id>.json"""
    man = os.path.join(d, "out", "manifest.json")
    if not os.path.exists(man):
        return 0
    n = 0
    for w in json.load(open(man, encoding="utf-8")):
        dst_dir = os.path.join(d, "db", w["collection"])
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(w["file"], os.path.join(dst_dir, w["doc_id"] + ".json"))
        n += 1
    return n


def chunk_addrs(g):
    out = []
    for ch in g.get("chunks") or []:
        out += ch.split(",")
    return [a for a in out if a]


def cycle(d, force=False, offline=False, mock="", now=None, push=False, remote=None, branch="results", rescan=False):
    os.makedirs(d, exist_ok=True)
    extra = (["--force"] if force else []) + (["--snapshot"] if rescan else [])
    mode = run(["memebot.py", "mode"] + extra, d, now)
    log("mode: %s" % json.dumps({k: mode[k] for k in ("pick", "room", "why", "scan", "bigTestSaveDue", "bigTestDue", "open")}))
    fetch = lambda args, expect_json=True: run(["fetch.py"] + args + (["--mock", mock] if mock else []), d, expect_json=expect_json)
    if not offline:
        if mode["scan"] in ("full", "light"):
            fetch(["sources"] + (["--light"] if mode["scan"] == "light" else []), expect_json=False)
        else:
            # only prices: drop the old source files so the gather asks for exactly the open positions and the due big-test coins
            import fetch as F
            F.clear_sources(d, F.SOURCE_DIRS, ("lists.json",))
    g = run(["memebot.py", "gather"], d, now)
    need = chunk_addrs(g)
    if need and not offline:
        log("gather: %d coins, %d still need DexScreener data" % (g["coins"], len(need)))
        fetch(["tokens", "--addrs", ",".join(need)])
        g = run(["memebot.py", "gather"], d, now)
    log("gather: %d coins (%d with full DEX data), coverage %.0f%%, lists %s" % (g["coins"], g["fullData"], 100 * g["coverage"], g["lists"]))
    if mode["pick"] or mode["bigTestSaveDue"]:
        s = run(["memebot.py", "shortlist"] + extra, d, now)
        log("shortlist: %d of %d gated coins get a RugCheck report; best: %s" % (s["n"], s["gated"], ", ".join(str(x) for x in s["pick"][:6])))
        if s["shortlist"] and not offline:
            fetch(["risk", "--addrs", ",".join(s["shortlist"])])
    r = run(["memebot.py", "run", "--mode", "pick" if mode["pick"] else "check"] + extra, d, now)
    n = apply_out(d)
    log("saved %d docs" % n)
    try:
        import report as R
        log("report: %s" % R.build(d, now=now))
    except Exception as e:   # the page must never break a cycle
        log("report failed: %s" % e)
    print(r["note"])
    for p in r["picks"]:
        print("  BUY  %-10s %-6s score %5.1f  %s" % (p["sym"], p["grp"], p["score"], p.get("addr")))
        if p.get("why"):
            print("       " + p["why"])
    for e in r["exits"]:
        print("  SELL %-10s %-6s %-14s %.0f%% at %.2fx -> %.2f back" % (e["sym"], e["grp"], e["why"], 100 * e["frac"], e["mult"], e["eur"]))
    if r["top5"]:
        print("  top 5 gated: " + ", ".join("%s %.0f" % (t["sym"], t["score"]) for t in r["top5"]))
    if push:
        try:
            sync(d, remote, branch)
        except SystemExit as e:   # a failed push must not stop the loop
            log("sync failed: %s" % e)
    return r


SYNC_IGNORE = """# written by bot.py sync: only the page and the small docs travel; the big snapshots stay local
*
!.gitignore
!report.html
!db/
!db/memepos/
!db/memepos/**
!db/memeexit/
!db/memeexit/**
!db/memecurve/
!db/memecurve/**
!db/memeruns/
!db/memeruns/**
!db/memeweights/
!db/memeweights/**
!db/memebot/
!db/memebot/**
"""


def sync(d, remote=None, branch="results"):
    """mb/ keeps its own small git repository (the bot's code repo ignores mb/). Each sync commits report.html and the small
    docs and pushes them to <remote> on <branch>; the default remote is this code repository's origin."""
    mb = os.path.abspath(d)
    os.makedirs(mb, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")

    def git(*a, check=False):
        p = subprocess.run(["git", "-C", mb] + list(a), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if check and p.returncode != 0:
            raise SystemExit("git %s failed: %s" % (a[0], (p.stderr or p.stdout).strip()[-800:]))
        return p

    if not os.path.isdir(os.path.join(mb, ".git")):
        git("init", "-q", check=True)
        git("symbolic-ref", "HEAD", "refs/heads/" + branch, check=True)
    if not remote:
        p = subprocess.run(["git", "-C", HERE, "remote", "get-url", "origin"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        remote = p.stdout.strip()
        if p.returncode != 0 or not remote:
            raise SystemExit("no --remote given and this folder has no git origin to reuse")
    if git("remote", "get-url", "origin").returncode != 0:
        git("remote", "add", "origin", remote, check=True)
    else:
        git("remote", "set-url", "origin", remote, check=True)
    with open(os.path.join(mb, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(SYNC_IGNORE)
    git("add", "-A", check=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c = git("-c", "user.name=memebot", "-c", "user.email=memebot@localhost", "commit", "-q", "-m", "results " + stamp)
    changed = c.returncode == 0
    p = git("push", "-q", "-u", "origin", "HEAD:" + branch)
    if p.returncode != 0:
        # another machine pushed to the same branch: take the remote history and put this state on top of it
        git("fetch", "-q", "origin", branch)
        git("-c", "user.name=memebot", "-c", "user.email=memebot@localhost", "merge", "-q", "-s", "ours", "--allow-unrelated-histories", "-m", "merge results", "FETCH_HEAD")
        git("push", "-q", "-u", "origin", "HEAD:" + branch, check=True)
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    log("sync: %s -> %s %s (%s)" % ("new commit" if changed else "nothing new", remote, branch, head))
    return head


def status(d):
    sys.path.insert(0, HERE)
    import memebot as M
    pos = M.positions(d)
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    cash = M.bankroll(pos)
    print("bankroll: %.2f free of %.0f  (spent %.2f, came back %.2f, %d open)" % (cash["free"], cash["budget"], cash["spent"], cash["back"], cash["open"]))
    equity = cash["free"]
    for pid, p in sorted(pos.items(), key=lambda kv: kv[1].get("t") or 0):
        ticket, entry = M.num(p.get("ticket")) or M.TICKET, M.num(p.get("px"))
        back = sum(M.num(e.get("eur")) or 0 for e in p["_exits"])
        last = M.num((marks.get("px") or {}).get(pid))
        when = dt.datetime.fromtimestamp((M.num(p.get("t")) or 0) / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
        if p["_left"] > 1e-9:
            val = None
            if last and entry:
                gross = (ticket - M.fee(ticket)) * p["_left"] * last / entry
                val = max(0.0, gross - M.fee(gross))
                if p.get("grp") in M.BOT_GROUPS:
                    equity += val
            print("  OPEN   %s %-10s %-5s in %.0f  now %s  %s%s" % (when, p.get("sym"), p.get("grp"), ticket,
                                                                     ("%.2fx" % (last / entry)) if last and entry else "?",
                                                                     ("worth %.2f" % val) if val is not None else "no price yet",
                                                                     (" (+%.2f already sold)" % back) if back else ""))
        else:
            print("  CLOSED %s %-10s %-5s in %.0f  out %.2f  %+.2f  (%s)" % (when, p.get("sym"), p.get("grp"), ticket, back, back - ticket,
                                                                            ", ".join(e.get("why", "?") for e in p["_exits"])))
    print("equity if everything were sold now: %.2f (%+.2f)" % (equity, equity - cash["budget"]))
    if state.get("note"):
        print("last run: " + state["note"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cycle", "loop", "status", "reset", "report", "sync"])
    ap.add_argument("--push", action="store_true", help="after each cycle, push report.html and the small docs to the results branch")
    ap.add_argument("--rescan", action="store_true", help="cycle: scan the whole universe now and save it for the big test, even if the last full scan is recent")
    ap.add_argument("--remote", default=None, help="git URL for sync/--push (default: this repository's origin)")
    ap.add_argument("--branch", default="results", help="branch for sync/--push")
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--every", type=float, default=30.0, help="minutes between cycles in loop mode")
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    ap.add_argument("--now", type=float, default=None, help="fake clock in ms (tests)")
    a = ap.parse_args()
    if a.cmd == "status":
        status(a.dir)
        print("page: %s" % os.path.abspath(os.path.join(a.dir, "report.html")))
    elif a.cmd == "report":
        import report as R
        print(R.build(a.dir, now=a.now))
    elif a.cmd == "reset":
        shutil.rmtree(os.path.join(a.dir, "db"), ignore_errors=True)
        shutil.rmtree(os.path.join(a.dir, "out"), ignore_errors=True)
        print("db/ wiped: fresh bankroll")
    elif a.cmd == "sync":
        print(sync(a.dir, a.remote, a.branch))
    elif a.cmd == "cycle":
        cycle(a.dir, a.force, a.offline, a.mock, a.now, a.push, a.remote, a.branch, a.rescan)
    else:
        while True:
            try:
                cycle(a.dir, a.force, a.offline, a.mock, push=a.push, remote=a.remote, branch=a.branch)
            except SystemExit as e:
                log("cycle failed: %s" % e)
            log("next cycle in %.0f minutes" % a.every)
            time.sleep(a.every * 60)


if __name__ == "__main__":
    main()
