"""Would holding longer than 2 h beat the fees? Chain the 2-hour windows of the same coin across scans 2 h apart.
usage: python3 -I research/check_holding.py <data dir with memesnapres/>
"""
import os, sys, statistics, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
rows, scans = H.load(os.path.join(sys.argv[1], 'memesnapres'), rule='m9-2h', only_learnable=False)
by = {}
for r in rows:
    by.setdefault(r['scan'], {})[r['a']] = r
def fee(x): return max(0.81, 0.005 * x)
def net(m):
    inv = 20 - fee(20); g = inv * m
    return round((max(0.0, g - fee(g)) if g > 0 else 0.0) - 20, 2)
def nearest_scan(t):
    i = bisect.bisect_left(scans, t)
    best = min((s for s in scans[max(0, i - 1):i + 1]), key=lambda s: abs(s - t), default=None)
    return best if best is not None and abs(best - t) <= 35 * 60_000 else None
def chain(r0, steps):
    m, r = 1.0, r0
    for k in range(steps):
        m *= r['mult']
        if r['mult'] < 0.02:
            return 0.0
        if k == steps - 1:
            return m
        s = nearest_scan(r['t'])
        nxt = by.get(s, {}).get(r['a']) if s else None
        if nxt is None:
            return None
        r = nxt
    return m
def gate(r):
    a = H.num(r['f'].get('ageH'))
    return all(w == 'old' for w in r['why']) and a is not None and 6 <= a < 24 and (r['mc'] or 0) >= 100_000 and H.learnable(r)
def top1(g):
    p = sorted([r for r in g.values() if gate(r)], key=lambda r: -(r['sc'] or 0))
    return p[:1]
groups = {
    'gate passers (6-24h, mc>=100k)': lambda g: [r for r in g.values() if gate(r)],
    'bot top-1 among them': top1,
}
for name, sel in groups.items():
    print('==', name)
    for steps in (1, 2, 3, 4, 5, 6):
        ms, lost = [], 0
        for s in scans:
            for r in sel(by.get(s, {})):
                m = chain(r, steps)
                if m is None: lost += 1
                else: ms.append(m)
        if not ms: print('  %2d h: no complete chains' % (2 * steps)); continue
        e = [net(m) for m in ms]
        print('  %2d h: n %5d  avg %6.2f per 20  win %5.1f%%  zero %4.1f%%  median mult %.3f  (could not follow %d)' % (2 * steps, len(ms), sum(e) / len(e), 100 * sum(1 for x in e if x > 0) / len(e), 100 * sum(1 for m in ms if m < 0.02) / len(ms), statistics.median(ms), lost))
