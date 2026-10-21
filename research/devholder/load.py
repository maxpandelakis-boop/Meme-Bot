import sys, pickle, collections
sys.path.insert(0, "/home/claude/Meme-Bot/research")
import harness as H
rows, scans = H.load(sys.argv[1], rule="m9-2h")
print(len(rows), len(scans), H.ts(scans[0]), H.ts(scans[-1]))
pickle.dump((rows, scans), open("rows.pkl", "wb"))
cnt = collections.Counter()
for r in rows:
    for k, v in r["f"].items():
        if v is not None: cnt[k] += 1
for k, v in sorted(cnt.items()):
    print(k, v)
