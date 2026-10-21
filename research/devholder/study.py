import pickle, random, math, sys, collections
rows, scans = pickle.load(open("rows.pkl","rb"))
CUT = 1792022400000
FEE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.01
def eur(r):
    if r["gone"]: return -20.0
    return max(-20.0, min(60.0, 20*r["mult"]*(1-FEE)**2 - 20))
for r in rows: r["e"] = eur(r); r["x3"] = (not r["gone"]) and r["mult"] >= 3
P1F = [("jup.devMints",1),("jup.top10Pct",1),("jup.mcPerHolder",1),("jup.holderChg24",-1),("jup.organic",-1),("jup.holders",-1),("jup.netBuyers24",-1),("pf.replies",-1),("pf.athRatio",-1)]
P2F = [("rc.top1",1),("rc.top10",1),("rc.insiders",1),("rc.score",1),("dev.pct",1),("dev.txs3h",1),("fl.topBuyer",1),("fl.flip",1),("rc.holders",-1),("rc.lp",-1),("dev.sold",1)]
def mean(xs): return sum(xs)/len(xs) if xs else float("nan")
def bad(r, k, d, th):
    v = r["f"].get(k)
    if v is None: return False
    return v > th if d > 0 else v < th
def summary(R):
    return len(R), mean([r["e"] for r in R]), mean([r["gone"] for r in R]), mean([r["x3"] for r in R])
import numpy as np
def boot_gain(R, k, d, th, n=2000, seed=7):
    idx = {}; S = []; N = []; SK = []; NK = []
    for r in R:
        i = idx.setdefault(r["a"], len(idx))
        if i == len(S): S.append(0.0); N.append(0); SK.append(0.0); NK.append(0)
        S[i] += r["e"]; N[i] += 1
        if not bad(r, k, d, th): SK[i] += r["e"]; NK[i] += 1
    S, N, SK, NK = map(np.array, (S, N, SK, NK))
    rng = np.random.default_rng(seed); m = len(S)
    W = rng.multinomial(m, np.full(m, 1.0/m), size=n).astype(float)
    g = (W @ SK) / np.maximum(W @ NK, 1) - (W @ S) / (W @ N)
    g.sort()
    return g[int(0.025*n)], g[int(0.975*n)], float((g <= 0).mean())
out = []
for pop, feats, sel in [("P1", P1F, lambda r: True), ("P2", P2F, lambda r: r["f"].get("rc.score") is not None)]:
    D = [r for r in rows if sel(r) and r["scan"] < CUT]; C = [r for r in rows if sel(r) and r["scan"] >= CUT]
    print(pop, "base disc", summary(D), "check", summary(C))
    for k, d in feats:
        vals = sorted(r["f"][k] for r in D if r["f"].get(k) is not None)
        if not vals: continue
        cands = [0.5] if k == "dev.sold" else sorted(set(vals[int(q/10*(len(vals)-1))] for q in range(1,10)))
        best = None; bm = mean([r["e"] for r in D])
        for th in cands:
            kept = [r for r in D if not bad(r,k,d,th)]
            fr = 1 - len(kept)/len(D)
            if fr < 0.05 or len(kept)/len(D) < 0.20: continue
            g = mean([r["e"] for r in kept]) - bm
            if best is None or g > best[1]: best = (th, g)
        if best is None: print(" ", k, "no admissible threshold"); continue
        th, gd = best
        kc = [r for r in C if not bad(r,k,d,th)]; vc = [r for r in C if bad(r,k,d,th)]
        vd = [r for r in D if bad(r,k,d,th)]; kd = [r for r in D if not bad(r,k,d,th)]
        lo, hi, p = boot_gain(C, k, d, th)
        nvc = len(set(r["a"] for r in vc))
        out.append((pop,k,d,th,gd,mean([r["e"] for r in kc])-mean([r["e"] for r in C]),lo,hi,p,nvc,summary(kd),summary(vd),summary(kc),summary(vc)))
        print(" %-16s %s th=%.4g discGain=%+.2f | check gain=%+.2f CI[%+.2f,%+.2f] p=%.3f vetoCoins=%d" % (k, ">" if d>0 else "<", th, gd, out[-1][5], lo, hi, p, nvc))
        print("    disc kept n=%d e=%+.2f rug=%.2f x3=%.4f | veto n=%d e=%+.2f rug=%.2f x3=%.4f" % (*summary(kd), *summary(vd)))
        print("    chk  kept n=%d e=%+.2f rug=%.2f x3=%.4f | veto n=%d e=%+.2f rug=%.2f x3=%.4f" % (*summary(kc), *summary(vc)))
# Holm
ps = sorted([(o[8], o[1]) for o in out]); m = len(ps)
print("\nHolm:")
for i,(p,k) in enumerate(ps):
    print(" %-16s p=%.4f thr=%.4f %s" % (k, p, 0.05/(m-i), "PASS" if p < 0.05/(m-i) else ""))
pickle.dump(out, open("study_%s.pkl" % FEE, "wb"))
