"""The gate floors: the old 3 h / $50k gate against 6 h / $100k (and a small grid), reconstructed from the why tags plus ageH and mc.
usage: python3 -I research/check_gates.py <data dir with memesnapres/>
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
rows, scans = H.load(os.path.join(sys.argv[1], 'memesnapres'), rule='m9-2h')
half = len(scans) // 2
n = lambda r, k: H.num(r['f'].get(k))
def gate(r, amin=3, mcmin=0):
    a = n(r, 'ageH')
    # 'young' and 'mc' are allowed because a later gate (6 h / $100k from 2026-10-08 12:10 UTC) tags coins the old gate passed;
    # the age and market-cap window is enforced here instead
    return all(w in ('old', 'young', 'mc') for w in r['why']) and a is not None and amin <= a < 24 and max(mcmin, 50_000) <= (r['mc'] or 0) <= 2_000_000
def mk(amin, mcmin):
    return lambda g, hist: sorted([r for r in g if gate(r, amin, mcmin)], key=lambda r: -(r['sc'] or 0))
def line(name, rule, k):
    s, per = H.evaluate(rows, scans, rule, k=k)
    s1, _ = H.evaluate(rows, scans[:half], rule, k=k); s2, _ = H.evaluate(rows, scans[half:], rule, k=k)
    ks = 'all' if k > 100 else k
    print("%-30s k=%-3s n %3d avg %6s win %5s%% zero %4s%% ci %s | halves %s / %s | distinct coins %d" % (name, ks, s['n'], s['avg'], s['win'], s['zero'], H.bootstrap_ci(per), s1['avg'], s2['avg'], len({r['a'] for _, p in per for r in p})))
for k in (1, 3, 10**9):
    line('current (3-24h, mc>=50k)', mk(3, 0), k)
    line('age>=6h & mc>=100k', mk(6, 100_000), k)
    print()
# placebo: how often does a random pair of thresholds do as well? age floor in {3,4,5,6,8,10}, mc floor in {50k,75k,100k,150k,200k,250k}
import itertools
res = []
for a, m in itertools.product((3, 4, 5, 6, 8, 10), (50_000, 75_000, 100_000, 150_000, 200_000, 250_000)):
    s, _ = H.evaluate(rows, scans, mk(a, m), k=10**9)
    res.append((s['avg'], a, m, s['n']))
res.sort(reverse=True)
print("k=all grid (36 combos), best 8:", [(a, m//1000, avg, nn) for avg, a, m, nn in res[:8]])
print("rank of (6,100k):", [i for i, (avg, a, m, nn) in enumerate(res) if a == 6 and m == 100_000][0] + 1, "of", len(res))
