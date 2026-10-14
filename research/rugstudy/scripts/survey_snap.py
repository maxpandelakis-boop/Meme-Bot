import json, os, sys, collections, glob
D = sys.argv[1]
fs = sorted(glob.glob(os.path.join(D, "*.json")))
rules = collections.Counter(); n = 0; young = 0; ylq = 0; fk = collections.Counter(); rck = collections.Counter(); yrc = 0
runs = set(); yruns = collections.Counter(); hz = []
for fn in fs:
    d = json.load(open(fn))
    rules[d.get("rule")] += 1
    rid = os.path.basename(fn).rsplit("-", 1)[0]
    runs.add(rid)
    if d.get("t") and d.get("t0"): hz.append((d["t"] - d["t0"]) / 3.6e6)
    for c in d.get("coins", []):
        n += 1
        f = c.get("f") or {}
        a = f.get("ageH")
        if a is not None and a < 1:
            young += 1
            if (c.get("liq") or 0) >= 5000:
                ylq += 1; yruns[rid] += 1
                fk.update(k for k in f)
                if c.get("rc"):
                    yrc += 1; rck.update(c["rc"].keys())
print("files", len(fs), "runs", len(runs), "rules", rules, "coins", n, "young", young, "young liq>=5k", ylq, "with rc", yrc)
import statistics
print("horizon h: median", statistics.median(hz), "min", min(hz), "max", max(hz))
print("young runs", len(yruns))
print(sorted(fk.items(), key=lambda x: -x[1])[:200])
print(rck)
