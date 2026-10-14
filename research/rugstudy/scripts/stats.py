"""Shared statistics for the rug study: run-level (cluster) bootstrap, rates, lifts, BH q-values. numpy only."""
import math
import numpy as np

B = 4000
SEED = 20261013


class Boot:
    """Run-level bootstrap: the runs (scans) are resampled with replacement, all coins of a drawn run come along.
    One draw matrix per cohort, so every signal is judged on the same resamples."""

    def __init__(self, runs, b=B, seed=SEED):
        self.runs = sorted(set(runs))
        self.ix = {r: i for i, r in enumerate(self.runs)}
        rng = np.random.default_rng(seed)
        R = len(self.runs)
        draws = rng.integers(0, R, size=(b, R))
        # weight matrix W[b, r] = how often run r was drawn in resample b
        self.W = np.zeros((b, R), dtype=np.float64)
        for i in range(b):
            self.W[i] = np.bincount(draws[i], minlength=R)

    def per_run(self, rows, mask_fn, y_fn):
        """Per-run counts (n, k) for rows where mask_fn is True and y_fn is not None."""
        n = np.zeros(len(self.runs))
        k = np.zeros(len(self.runs))
        for r in rows:
            if not mask_fn(r):
                continue
            y = y_fn(r)
            if y is None:
                continue
            i = self.ix[r["rid"]]
            n[i] += 1
            k[i] += 1 if y else 0
        return n, k

    def rate(self, n, k):
        """Point rate, 95% CI."""
        N, K = n.sum(), k.sum()
        if N == 0:
            return None
        bn, bk = self.W @ n, self.W @ k
        with np.errstate(invalid="ignore", divide="ignore"):
            br = bk / bn
        br = br[np.isfinite(br)]
        lo, hi = (np.percentile(br, [2.5, 97.5]) if len(br) else (float("nan"), float("nan")))
        return {"n": int(N), "k": int(K), "rate": K / N, "lo": float(lo), "hi": float(hi)}

    def compare(self, n1, k1, n0, k0):
        """Rate with (1) vs without (0): difference and ratio with 95% CI and a two-sided bootstrap p."""
        N1, K1, N0, K0 = n1.sum(), k1.sum(), n0.sum(), k0.sum()
        if N1 == 0 or N0 == 0:
            return None
        r1, r0 = K1 / N1, K0 / N0
        bn1, bk1, bn0, bk0 = self.W @ n1, self.W @ k1, self.W @ n0, self.W @ k0
        with np.errstate(invalid="ignore", divide="ignore"):
            d = bk1 / bn1 - bk0 / bn0
            lr = np.log((bk1 + 0.5) / (bn1 + 1.0)) - np.log((bk0 + 0.5) / (bn0 + 1.0))
        ok = np.isfinite(d)
        d, lr = d[ok], lr[ok]
        p = 2 * min((d <= 0).mean(), (d >= 0).mean()) if len(d) else 1.0
        p = max(p, 1.0 / len(d)) if len(d) else 1.0
        lift = (r1 / r0) if r0 > 0 else float("inf")
        return {"n1": int(N1), "k1": int(K1), "r1": r1, "n0": int(N0), "k0": int(K0), "r0": r0, "diff": r1 - r0,
                "dlo": float(np.percentile(d, 2.5)), "dhi": float(np.percentile(d, 97.5)), "lift": lift,
                "llo": float(math.exp(np.percentile(lr, 2.5))), "lhi": float(math.exp(np.percentile(lr, 97.5))), "p": float(min(1.0, p))}


def bh(ps):
    """Benjamini-Hochberg q-values."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    q = [0.0] * m
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return q


def pct(x, d=1):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else ("%." + str(d) + "f%%") % (100 * x)


def fx(x, d=2):
    if x is None or (isinstance(x, float) and (math.isnan(x))):
        return "-"
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return ("%." + str(d) + "f") % x


def auc(scores, ys):
    """Mann-Whitney AUC (ties count half)."""
    pairs = sorted(zip(scores, ys))
    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        rank_sum += avg_rank * sum(1 for t in range(i, j) if pairs[t][1])
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def ridge_logit(X, y, lam=1.0, iters=60):
    """L2-penalised logistic regression by Newton steps (intercept not penalised). X: n x p numpy, y: 0/1."""
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    w = np.zeros(p + 1)
    P = np.eye(p + 1) * lam
    P[0, 0] = 0.0
    for _ in range(iters):
        z = Xb @ w
        mu = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = Xb.T @ (mu - y) + P @ w
        Hm = (Xb * (mu * (1 - mu))[:, None]).T @ Xb + P
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w
