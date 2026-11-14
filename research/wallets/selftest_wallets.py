"""Selftest of research/wallets/wallet_day.py: the fast event code against a slow, plain replay on random coins."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet_day as wd


def slow(m, t, u, buy, sol, tok, price, rs, cr, data_end, delay):
    out = {}
    N = len(m)
    for c in np.unique(m):
        idx = [i for i in range(N) if m[i] == c]
        g = next((i for i in idx if rs[i] >= wd.GRAD), -1)
        seen = set()
        for b in idx:
            if not (buy[b] and sol[b] >= wd.BIG and u[b] != cr[c]) or u[b] in seen:
                continue
            seen.add(u[b])
            mine = [i for i in idx if i >= b and u[i] == u[b]]
            s = next((i for i in mine if not buy[i]), -1)
            own = sum((-sol[i] if buy[i] else sol[i]) for i in mine) / 1e9
            left = max(sum((tok[i] if buy[i] else -tok[i]) for i in mine), 0) / 1e6
            rec = dict(hold=(t[s] - t[b]) if s >= 0 else -1, own=own + left * price[idx[-1]], r=None)
            a = next((i for i in idx if i >= b and t[i] >= t[b] + delay), None)
            if a is not None:
                entry = price[a] * 1.01
                end_t = min(t[a] + wd.WINDOW, data_end)
                j_end = max([i for i in idx if i >= a and t[i] < end_t] or [a])
                if s >= 0:
                    jx = next((i for i in idx if i >= a and t[i] >= t[s] + delay), None)
                    if jx is None:
                        jx, h = idx[-1], (3 if g >= 0 else 2)
                    else:
                        h = 0
                    if jx > j_end:
                        jx, h = j_end, 1
                else:
                    jx, h = j_end, 1
                    if g >= 0:
                        h = 3
                        if a <= g <= j_end:
                            jx = g
                for j in idx:
                    if a < j <= jx and price[j] * 0.99 >= 10 * entry:
                        jx, h = j, 4
                        break
                rec.update(r=price[jx] * 0.99 / entry, how=h, xt=t[jx])
            out[(int(c), int(u[b]))] = rec
    return out


def case(seed):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(6):
        n = int(rng.integers(1, 120)); tt = 1000 + np.cumsum(rng.integers(0, 40, n)); p = 3e-8; r = 0.0
        if c == 5:
            tt = 1000 + np.cumsum(rng.integers(0, 4000, n))      # a slow coin that runs past the 24 h window
        for k in range(n):
            b = rng.random() < 0.6
            p *= float(np.exp(rng.normal(0.15 if c == 0 else 0, 0.5)))
            r = max(r + (1 if b else -1) * rng.random() * 9e9, 0)
            rows.append((c, int(tt[k]), int(rng.integers(0, 12)), b, int(rng.choice([1e7, 6e7, 3e8])), float(rng.integers(1, 9) * 1e9), p, r))
    m, t, u, buy, sol, tok, price, rs = (np.array(x) for x in zip(*rows))
    m = m.astype(np.int64); t = t.astype(np.int64); u = u.astype(np.int64); sol = sol.astype(np.int64)
    cr = np.array([0, 1, -1, 3, 4, 5], np.int64)
    data_end = int(t.max()) - 500
    for delay in wd.DELAYS:
        ev = wd.events(m, t, u, buy, sol, tok, price, rs, cr, data_end)
        ref = slow(m, t, u, buy, sol, tok, price, rs, cr, data_end, delay)
        k = "" if delay == wd.DELAYS[0] else str(delay)
        assert len(ev["i"]) == len(ref), (len(ev["i"]), len(ref))
        for e in range(len(ev["i"])):
            x = ref[(int(ev["m"][e]), int(ev["u"][e]))]
            assert int(ev["hold"][e]) == x["hold"], (seed, e)
            assert abs(float(ev["own_pnl"][e]) - x["own"]) < 1e-4 * max(1, abs(x["own"])), (seed, e, ev["own_pnl"][e], x["own"])
            if x["r"] is None:
                assert np.isnan(ev["r" + k][e]), (seed, e)
            else:
                assert abs(float(ev["r" + k][e]) - x["r"]) < 1e-5 * max(1, x["r"]), (seed, e, ev["r" + k][e], x["r"])
                assert int(ev["how" + k][e]) == x["how"], (seed, e, ev["how" + k][e], x["how"])
                if not k:
                    assert int(ev["xt"][e]) == x["xt"]
    return len(ref)


def hand():
    """One coin by hand: wallet 7 buys at t=100, sells at t=200; the copier enters at the first trade from t=130, leaves at the
    first trade from t=230."""
    t = np.array([100, 110, 131, 190, 200, 229, 240, 300], np.int64)
    p = np.array([1.0, 1.1, 1.2, 2.0, 1.9, 1.8, 1.5, 0.5]) * 1e-7
    u = np.array([7, 2, 3, 4, 7, 5, 6, 2], np.int64)
    buy = np.array([1, 1, 1, 1, 0, 0, 0, 0], bool)
    z = np.zeros(8, np.int64)
    ev = wd.events(z, t, u, buy, z + 10 ** 8, np.ones(8) * 1e9, p, np.zeros(8), np.array([99], np.int64), 10 ** 9)
    e = list(ev["u"]).index(7)
    assert abs(ev["r"][e] - (1.5 * 0.99) / (1.2 * 1.01)) < 1e-6 and ev["how"][e] == 0 and ev["hold"][e] == 100, (ev["r"][e], ev["how"][e])
    assert abs(float(wd.fee(20.0)) - 0.40) < 1e-9 and wd.fee(4.0) == 0.10 and wd.fee(60.0) == 0.95 and abs(wd.fee(200.0) - 1.0) < 1e-9
    # the desk: entry 1.2 (+1%), next price 2.0 -> not yet 2x after slippage, then falls under -8%: stop
    d = wd.desk(t, p, 2, 7)
    q = 1.5 * 0.99 / (1.2 * 1.01)          # 1.9 and 1.8 stay above the stop, 1.5 too (q = 1.225); 0.5 stops
    v = 20 * 0.5 * 0.99 / (1.2 * 1.01)
    assert abs(d - (v - 20 - 0.40 - 0.02 * v)) < 1e-6, d


def round2():
    """kernel2: the mirror exit equals round 1's kernel; take profit and stop by hand."""
    import wallet_day2 as w2
    t = np.array([100, 110, 131, 190, 200, 229, 240, 300], np.int64)
    p = np.array([1.0, 1.1, 1.2, 2.0, 1.9, 1.8, 0.9, 0.5]) * 1e-7
    u = np.array([7, 2, 3, 4, 2, 5, 6, 7], np.int64)
    buy = np.array([1, 1, 1, 1, 0, 0, 0, 0], bool)
    z = np.zeros(8, np.int64)
    ev = wd.events(z, t, u, buy, z + 10 ** 8, np.ones(8) * 1e9, p, np.zeros(8), np.array([99], np.int64), 10 ** 9)
    r, how, ent = w2.kernel2(ev["i"], ev["sell_i"], z, t, p, np.array([8]), np.array([-1]), 10 ** 9, 30, np.array([1.5, 2.0]), np.array([0.8, 0.7]))
    e = list(ev["u"]).index(7)                     # wallet 7 buys at 100 and sells at 300: entry 1.2, mirror exit at 0.5
    en = 1.2 * 1.01
    assert ent[e] == 2 and abs(r[e, 0] - 0.5 * 0.99 / en) < 1e-6 and how[e, 0] == 2
    assert abs(r[e, 1] - 2.0 * 0.99 / en) < 1e-6 and how[e, 1] == 5          # +50% reached at 2.0
    assert abs(r[e, 2] - 0.5 * 0.99 / en) < 1e-6 and how[e, 2] == 6          # 2.0 is not +100% after slippage; 0.9 is above -30%; 0.5 stops
    assert abs(r[e, 3] - 0.5 * 0.99 / en) < 1e-6 and how[e, 3] == 1
    rng = np.random.default_rng(5)
    for seed in range(20):
        n = 400
        m = np.sort(rng.integers(0, 5, n)).astype(np.int64); tt = np.zeros(n, np.int64)
        for c in range(5):
            k = m == c; tt[k] = 1000 + np.cumsum(rng.integers(0, 30, k.sum()))
        pp = 3e-8 * np.exp(np.cumsum(rng.normal(0, 0.3, n))); uu = rng.integers(0, 15, n).astype(np.int64); bb = rng.random(n) < 0.6
        rs = np.where(rng.random(n) < 0.01, 9e10, 0.0)
        ev = wd.events(m, tt, uu, bb, np.full(n, 10 ** 8, np.int64), np.ones(n) * 1e9, pp, rs, np.full(5, -1, np.int64), int(tt.max()) - 300)
        ends = np.array([np.flatnonzero(m == c)[-1] + 1 for c in range(5)], np.int64)
        gi = np.array([next((i for i in np.flatnonzero(m == c) if rs[i] >= wd.GRAD), -1) for c in range(5)], np.int64)
        r, how, ent = w2.kernel2(ev["i"], ev["sell_i"], m, tt, pp, ends, gi, int(tt.max()) - 300, 30, np.array([1.5, 2.0]), np.array([0.8, 0.7]))
        ok = ent >= 0
        assert np.array_equal(ent, ev["ent"]) and np.allclose(r[ok, 0], ev["r"][ok], rtol=1e-5) and np.array_equal(how[ok, 0], ev["how"][ok])
        assert np.allclose(r[ok, 3], ev["rh"][ok], rtol=1e-5)


if __name__ == "__main__":
    hand()
    round2()
    n = sum(case(s) for s in range(60))
    print("selftest_wallets ok,", n, "events checked")
