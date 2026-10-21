import pickle
rows, scans = pickle.load(open("rows.pkl","rb"))
CUT = 1792022400000
def e(r): return -20.0 if r["gone"] else max(-20, min(60, 20*r["mult"]*0.9801-20))
F = ["jup.devMints","jup.top10Pct","jup.mcPerHolder","jup.holderChg24","jup.organic","jup.holders","jup.netBuyers24","pf.replies","pf.athRatio","rc.top1","rc.top10","rc.insiders","rc.score","dev.pct","dev.txs3h","fl.topBuyer","fl.flip","rc.holders","rc.lp","dev.sold"]
def auc(pos, neg):
    if not pos or not neg: return None
    allv = sorted([(v,1) for v in pos]+[(v,0) for v in neg]); # rank-based
    ranks = {}; i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]: j += 1
        for t in range(i, j): ranks.setdefault(t, (i+j+1)/2)
        i = j
    rs = sum(ranks[t] for t,(v,l) in enumerate(allv) if l == 1)
    return (rs - len(pos)*(len(pos)+1)/2)/(len(pos)*len(neg))
print("3x AUC (>0.5 = 3x coins have higher values)")
for k in F:
    out = []
    for half in (0,1):
        R = [r for r in rows if (r["scan"] >= CUT) == bool(half) and r["f"].get(k) is not None]
        pos = [r["f"][k] for r in R if not r["gone"] and r["mult"] >= 3]; neg = [r["f"][k] for r in R if r["gone"] or r["mult"] < 3]
        a = auc(pos, neg); out.append("n3x=%d auc=%s" % (len(pos), "-" if a is None else "%.2f" % a))
    print(" %-16s disc %s | chk %s" % (k, *out))
P = [r for r in rows if r["pass"] and r["scan"] >= CUT]
def s(R): return "n=%d coins=%d e=%+.2f rug=%.2f x3=%d" % (len(R), len(set(r["a"] for r in R)), sum(map(e,R))/max(1,len(R)), sum(r["gone"] for r in R)/max(1,len(R)), sum(1 for r in R if not r["gone"] and r["mult"]>=3))
print("passers check:", s(P))
for k, th in [("rc.top1",5.463),("dev.txs3h",0),("rc.top10",13.56)]:
    print(" veto %s>%s:" % (k, th), s([r for r in P if not ((r["f"].get(k) is not None) and r["f"][k] > th)]))
