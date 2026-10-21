import pickle
rows, scans = pickle.load(open("rows.pkl","rb"))
CUT = 1792022400000
def e(r): return -20.0 if r["gone"] else max(-20, min(60, 20*r["mult"]*0.9801-20))
for k in ["jup.netBuyers24","jup.holderChg24","jup.organic"]:
    D = sorted(r["f"][k] for r in rows if r["scan"] < CUT and r["f"].get(k) is not None)
    qs = [D[int(q*(len(D)-1))] for q in (0.5,0.8,0.9,0.95,0.99)]
    print(k, "disc cutoffs", [round(x,2) for x in qs])
    for half in (0,1):
        R = [r for r in rows if (r["scan"] >= CUT) == bool(half) and r["f"].get(k) is not None]
        line = []
        for lo, hi, nm in [(-1e18, qs[0], "<p50"), (qs[1], qs[2], "p80-90"), (qs[2], qs[3], "p90-95"), (qs[3], qs[4], "p95-99"), (qs[4], 1e18, ">p99")]:
            S = [r for r in R if lo <= r["f"][k] < hi] if nm != ">p99" else [r for r in R if r["f"][k] >= lo]
            if not S: continue
            line.append("%s n=%d c=%d e=%+.2f rug=%.1f%% 3x=%.2f%%" % (nm, len(S), len(set(r["a"] for r in S)), sum(map(e,S))/len(S), 100*sum(r["gone"] for r in S)/len(S), 100*sum(1 for r in S if not r["gone"] and r["mult"]>=3)/len(S)))
        print("  ", "disc" if half==0 else "chk ", " | ".join(line))
