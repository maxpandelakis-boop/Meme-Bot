"""Writes supabase/push-requirements.txt: pywebpush and every package it needs, each pinned to one version with the sha256 of its wheels
for Linux x86_64 and CPython 3.11 to 3.14 (the scan runner's system Python: 3.12 on ubuntu 24.04, newer on 26.04). The scan workflow
installs them with pip --require-hashes --only-binary=:all: --no-deps, so a run gets exactly these files or nothing (no notifications
that run): no newer release, no source build, no install-time code. http-ece has no wheel; the workflow takes its one module from the
sdist, checked against the sha256 this script prints. Run it again (network needed) only to move to newer versions on purpose:

  python3 supabase/pin_push.py [pywebpush==2.5.0]

Fake money only: these packages send the app's push notifications and nothing else."""
import json, os, re, sys, urllib.request

from pip._vendor.packaging.markers import Marker            # pip's own copy: nothing to install
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.version import Version

ROOT = sys.argv[1] if len(sys.argv) > 1 else "pywebpush==2.5.0"
PYS = ("3.11", "3.12", "3.13", "3.14")
CPS = {"cp" + v.replace(".", "") for v in PYS}
SDIST_ONLY = {"http-ece"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "push-requirements.txt")


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def pypi(name, version=None):
    url = "https://pypi.org/pypi/%s/%sjson" % (name, (version + "/") if version else "")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def wanted(fn):
    """A wheel the runner may pick: pure Python, or Linux x86_64 manylinux for CPython 3.11 to 3.14 (or the stable ABI)."""
    m = re.fullmatch(r"(.+?)-(.+?)(-\d[^-]*)?-([^-]+)-([^-]+)-([^-]+)\.whl", fn)
    if not m:
        return False
    py, abi, plat = m.group(4), m.group(5), m.group(6)
    if plat == "any":
        return abi == "none" and any(t.startswith("py3") or t in CPS for t in py.split("."))
    if "x86_64" not in plat or "manylinux" not in plat:
        return False
    return abi == "abi3" or abi in CPS


def resolve(envs, extra):
    """One round: the newest release of each package that fits what was asked so far; a clash names a package to narrow."""
    todo, pins, need, meta = [Requirement(ROOT)], {}, {}, {}
    while todo:
        req = todo.pop(0)
        name = norm(req.name)
        need.setdefault(name, SpecifierSet(str(extra.get(name, ""))))
        need[name] &= req.specifier
        if name in pins:
            if pins[name] not in need[name]:
                return pins, need, name
            continue
        info = pypi(name)
        ok = sorted((Version(v) for v, files in info["releases"].items()
                     if files and not Version(v).is_prerelease and not all(f.get("yanked") for f in files) and Version(v) in need[name]), reverse=True)
        if not ok:
            raise SystemExit("no release of %s fits %s" % (name, need[name]))
        pins[name] = ok[0]
        for dep in pypi(name, str(ok[0]))["info"].get("requires_dist") or []:
            r = Requirement(dep)
            if r.marker is None or any(r.marker.evaluate(e) for e in envs):
                todo.append(r)
    return pins, need, None


def main():
    envs = [{"python_version": v, "python_full_version": v + ".0", "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64",
             "os_name": "posix", "implementation_name": "cpython", "platform_python_implementation": "CPython", "extra": ""} for v in PYS]
    extra = {}                          # what an earlier round learned: a later requirement narrowed a package already pinned
    while True:
        pins, need, clash = resolve(envs, extra)
        if not clash:
            break
        extra[clash] = need[clash]
    lines, sdists = [], []
    for name in sorted(pins):
        files = pypi(name, str(pins[name]))["urls"]
        if name in SDIST_ONLY:
            sd = [f for f in files if f["packagetype"] == "sdist"]
            sdists.append("%s==%s  %s  sha256 %s" % (name, pins[name], sd[0]["url"], sd[0]["digests"]["sha256"]))
            continue
        hashes = sorted({f["digests"]["sha256"] for f in files if f["packagetype"] == "bdist_wheel" and wanted(f["filename"])})
        if not hashes:
            raise SystemExit("%s %s has no wheel for Linux x86_64 and CPython %s" % (name, pins[name], "/".join(PYS)))
        lines.append("%s==%s \\\n%s" % (name, pins[name], " \\\n".join("    --hash=sha256:" + h for h in hashes)))
    head = ("# pywebpush for the iPhone app's push notifications, every package pinned with the sha256 of its wheels (Linux x86_64, CPython %s).\n"
            "# Made by supabase/pin_push.py from %s; install: pip install --require-hashes --only-binary=:all: --no-deps -r this file.\n"
            "# Not here (no wheel; the scan workflow checks its sdist's sha256 and copies its one module):\n%s\n"
            % ("/".join(PYS), ROOT, "\n".join("#   " + s for s in sdists)))
    with open(OUT, "w") as f:
        f.write(head + "\n".join(lines) + "\n")
    print("wrote %s: %d packages pinned" % (OUT, len(lines)))
    for s in sdists:
        print("sdist (scan.yml):", s)


main()
