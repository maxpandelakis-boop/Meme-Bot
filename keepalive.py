#!/usr/bin/env python3
"""keepalive.py: the bots start each other, so none of them waits for GitHub's clock (fake money only: it starts GitHub Actions runs of
this repository, nothing else). GitHub starts scheduled runs late or not at all when it is busy: on 26 Oct 2026 no cron start came
from 11:43 to 13:00 UTC, so the Pick's scan stopped after the one of 11:05, the Rocket seeker ran out at 13:02 and the Radar's rounds
with the Sell bot's minute watch had no next run waiting. rocket.yml calls it after every round (15 minutes), seeker.yml every 10
minutes; each of them keeps all three going:

  scan.yml    started (source hourly, 2h profile) when no scan is waiting or running and the newest one began SCAN_EVERY_MIN minutes
              ago or more (a cancelled run and a safety-net run that skipped itself do not count); its cron at :25 stays the backup
  rocket.yml  started when no run of it is waiting or running but the caller's own: the new run waits in the workflow's group and
  seeker.yml  takes over when the running one ends, as the cron's waiting run does (the seeker only while MEMEBOT_SEEKER is not 0)

A workflow switched off (Actions -> ... -> Disable workflow) is never started: that stays the stop switch. Only on the default branch
and never from a push (a test run on a build branch starts nothing). A few GitHub API calls; the token goes only to GitHub's API. Never
raises: the caller's round goes on whatever GitHub answers. The caller's step carries the run's token only inside REPO_URL
(https://x-access-token:<token>@github.com/..., which the bots themselves run without), so it is read from there (GH_TOKEN when set).

usage: python3 keepalive.py --me rocket.yml
"""
import argparse, datetime as dt, json, os, re, sys, time, urllib.error, urllib.request

SCAN = "scan.yml"
BOTS = ("rocket.yml", "seeker.yml")
SCAN_EVERY_MIN = 55             # a scan an hour: started 55 minutes after the newest one began (one takes 35 to 50); with a look every
                                # 10 to 15 minutes the scans come 55 to 70 minutes apart
QUICK_S = 300                   # a scheduled scan done within 5 minutes skipped itself (the safety net found this hour's scan)
SCAN_INPUTS = {"horizon": "2h", "source": "hourly"}


def ts(s):
    """GitHub's time (2026-10-26T11:05:30Z) in epoch seconds, None when it is not one."""
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def busy(runs, me=None):
    """A run of the workflow waiting or running (queued, pending, waiting, requested, in progress), the caller's own left out."""
    return any(isinstance(r, dict) and r.get("status") != "completed" and str(r.get("id")) != str(me) for r in runs)


def last_scan(runs):
    """When the newest scan began (epoch s), or None: a cancelled run and a scheduled run done within QUICK_S (the safety net that
    skipped itself) left out."""
    best = None
    for r in runs:
        if not isinstance(r, dict):
            continue
        done = r.get("status") == "completed"
        if done and r.get("conclusion") in ("cancelled", "skipped"):
            continue
        t0, t1 = ts(r.get("run_started_at") or r.get("created_at")), ts(r.get("updated_at"))
        if done and r.get("event") == "schedule" and t0 and t1 and t1 - t0 < QUICK_S:
            continue
        c = ts(r.get("created_at"))
        if c and (best is None or c > best):
            best = c
    return best


def plan(now, me, info, seeker_on=True):
    """What to start, from GitHub's answers: info = {workflow file: (state, runs)}, (None, None) where GitHub did not answer. Returns
    ([(file, inputs)], notes). now in epoch seconds, me the caller's run id."""
    go, notes = [], []
    for f in (SCAN,) + BOTS:
        state, runs = info.get(f) or (None, None)
        if f == "seeker.yml" and not seeker_on:
            notes.append("%s: switched off (MEMEBOT_SEEKER=0)" % f)
        elif state != "active" or not isinstance(runs, list):
            notes.append("%s: %s" % (f, "not active (%s)" % re.sub(r"[^a-z_]", "", str(state))[:30] if state else "no answer"))
        elif busy(runs, me):
            notes.append("%s: a run is waiting or running" % f)
        elif f == SCAN:
            t = last_scan(runs)
            if t is not None and now - t < SCAN_EVERY_MIN * 60:
                notes.append("%s: the last scan began %d min ago" % (f, (now - t) // 60))
            else:
                go.append((f, dict(SCAN_INPUTS)))
                notes.append("%s: start, the last scan began %s" % (f, "%d min ago" % ((now - t) // 60) if t is not None else "long ago"))
        else:
            go.append((f, None))
            notes.append("%s: start, no run of it waiting" % f)
    return go, notes


def token():
    m = re.search(r"x-access-token:([^@\s]+)@", os.environ.get("REPO_URL") or "")
    return os.environ.get("GH_TOKEN") or (m.group(1) if m else "")


def call(method, url, tok, body=None):
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "memebot-keepalive", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", required=True, help="the caller's workflow file (its own run is left out)")
    a = ap.parse_args()
    say = lambda s: print("keepalive: " + s, flush=True)
    try:
        if os.environ.get("GITHUB_EVENT_NAME") == "push":
            return say("a test run of a push: nothing started")
        tok, repo = token(), os.environ.get("GITHUB_REPOSITORY") or ""
        if not tok or not repo:
            return say("no token or repository: nothing started")
        api = "%s/repos/%s" % ((os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/"), repo)
        st, r = call("GET", api, tok)
        ref = (r or {}).get("default_branch") if isinstance(r, dict) else None
        if st != 200 or not ref:
            return say("the repository could not be read (HTTP %s): nothing started" % st)
        if os.environ.get("GITHUB_REF_NAME") != ref:
            return say("not the default branch: nothing started")
        info = {}
        for f in (SCAN,) + BOTS:
            st, w = call("GET", "%s/actions/workflows/%s" % (api, f), tok)
            state = w.get("state") if st == 200 and isinstance(w, dict) else None
            st, j = call("GET", "%s/actions/workflows/%s/runs?per_page=20" % (api, f), tok)
            runs = j.get("workflow_runs") if st == 200 and isinstance(j, dict) else None
            info[f] = (state, runs)
        go, notes = plan(time.time(), os.environ.get("GITHUB_RUN_ID"), info, (os.environ.get("MEMEBOT_SEEKER") or "1") != "0")
        for f, inputs in go:
            body = {"ref": ref, "inputs": inputs} if inputs else {"ref": ref}
            st, _ = call("POST", "%s/actions/workflows/%s/dispatches" % (api, f), tok, body)
            if st not in (200, 201, 204):
                notes.append("%s: the start was refused (HTTP %s)" % (f, st))
        say("; ".join(notes))
    except Exception as e:
        say("GitHub did not answer (%s): nothing started" % type(e).__name__)


if __name__ == "__main__":
    main()
