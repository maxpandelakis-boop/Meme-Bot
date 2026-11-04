"""Information only: the same four methods with OPTIMISTIC fills (targets before the stop in one candle, stops filled exactly at the stop level)."""
import sys, numpy as np
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import check_platforms as C

def ladder_opt(cl, hi, has, k, p0, ladder, stop_fn):
    left, eur, gross, ti = 1.0, 0.0, 0.0, 0
    tok = C.BUY - C.FEE
    last = p0
    lvl = None
    for j in range(k + 1, min(k + 1 + C.HOLD, C.N)):
        if not has[j]:
            continue
        last = cl[j]
        while ti < len(ladder) and hi[j] >= ladder[ti][0] * p0:
            m, f = ladder[ti]
            eur += C.sale(tok * f * m); gross += f * m; left -= f; ti += 1
        if left <= 1e-9:
            break
        if stop_fn(cl[j], p0):
            # fill at the stop level: find it by bisection on the stop function between close and p0
            a, b = cl[j], max(p0, cl[j])
            for _ in range(40):
                mid = (a + b) / 2
                if stop_fn(mid, p0): a = mid
                else: b = mid
            m = min(a, p0) / p0
            eur += C.sale(tok * left * m); gross += left * m; left = 0.0
            break
    if left > 1e-9:
        m = last / p0
        eur += C.sale(tok * left * m); gross += left * m
    return eur - C.BUY, gross

C.ladder_exit = ladder_opt
C.main(*sys.argv[1:5])
