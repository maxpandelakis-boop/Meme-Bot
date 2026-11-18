"""Big meme coins on Binance spot: the pre-registered test (research/bigmemes/PREREG-BIGMEMES-2026-10-26.md). Fake money only.

    python3 research/bigmemes/check_bigmemes.py <data dir: a checkout of the bigmemes branch> [--holdout] [--out file.json]

Without --holdout every candle from 2026-07-01 00:00 UTC on is dropped as it is read, so the sealed months stay unseen.
Day d: signals use closes up to the end of day d-1 (00:00 UTC); orders fill at the open of the 08:00 UTC candle of day d.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

HOLDOUT = pd.Timestamp("2026-07-01")
TEST = ("2022-01", "2026-06")
THIRDS = [("2022-01", "2023-06"), ("2023-07", "2024-12"), ("2025-01", "2026-06")]
SEALED = ("2026-07", "2026-10")
MIN_VOL = 5e6
MIN_AGE = 30
VARIANTS = {"base": (0.0025, 8), "stress": (0.005, 14), "nodelay": (0.0025, 0)}
SEED = 7
DRAWS = 10_000


# ---------------------------------------------------------------- data
def read(path, holdout):
    df = pd.read_csv(path, dtype={"t_ms": "int64"})
    df["t"] = pd.to_datetime(df["t_ms"], unit="ms")
    if not holdout:
        df = df[df["t"] < HOLDOUT]
    df = df[df["t"] < pd.Timestamp("2026-10-26")]
    return df.set_index("t").sort_index()


def daily(df, days):
    day = df.index.floor("D")
    hour = df.index.hour
    out = {"C": df["c"].groupby(day).last().reindex(days),
           "qv": df["qv"].groupby(day).sum().reindex(days)}
    for h in (0, 8, 14):
        sub = df[hour >= h]
        out[f"F{h:02d}"] = sub["o"].groupby(sub.index.floor("D")).first().reindex(days)
    return out


def load(data, holdout, universe="research/bigmemes/UNIVERSE.json"):
    uni = json.load(open(universe))["symbols"]
    raw = {s: read(os.path.join(data, "klines", s + ".csv.gz"), holdout) for s in uni + ["BTCUSDT"]}
    raw = {s: d for s, d in raw.items() if len(d)}
    t0 = min(d.index[0] for d in raw.values()).floor("D")
    t1 = max(d.index[-1] for d in raw.values()).floor("D")
    days = pd.date_range(t0, t1, freq="D")
    syms = [s for s in uni if s in raw]
    per = {s: daily(raw[s], days) for s in syms + ["BTCUSDT"]}
    M = {k: np.column_stack([per[s][k].to_numpy(float) for s in syms]) for k in ("C", "qv", "F00", "F08", "F14")}
    btc = per["BTCUSDT"]["C"].to_numpy(float)
    first = np.array([raw[s].index[0].floor("D") for s in syms])
    last = np.array([raw[s].index[-1].floor("D") for s in syms])
    gaps = {s: int((raw[s].index.to_series().diff().dt.total_seconds() / 3600 > 72).sum()) for s in syms}
    return days, syms, M, btc, first, last, gaps


def shift1(a):
    out = np.full_like(a, np.nan)
    out[1:] = a[:-1]
    return out


def roll(a, n, fn):
    """fn over a[d-n..d-1] (the n values before d), per column; NaN until n values exist."""
    s = pd.DataFrame(shift1(a) if a.ndim == 2 else shift1(a[:, None]))
    r = getattr(s.rolling(n, min_periods=n), fn)()
    return r.to_numpy() if a.ndim == 2 else r.to_numpy()[:, 0]


class World:
    def __init__(self, days, syms, M, btc, first, last):
        self.days, self.syms = days, syms
        self.T, self.N = len(days), len(syms)
        C = M["C"]
        self.C, self.Cp = C, shift1(C)
        self.qv = M["qv"]
        self.F = {h: M[f"F{h:02d}"] for h in (0, 8, 14)}
        dix = np.arange(self.T)
        fi = np.array([days.get_loc(f) for f in first])
        self.li = np.array([days.get_loc(x) for x in last])
        qv0 = np.nan_to_num(self.qv)
        med = pd.DataFrame(shift1(qv0)).rolling(30, min_periods=30).median().to_numpy()
        self.elig = ((dix[:, None] - fi[None, :]) >= MIN_AGE) & (med >= MIN_VOL) & ~np.isnan(self.Cp)
        self.nelig = self.elig.sum(1)
        self.cache = {}
        # filters, known at the fill of day d
        bp = shift1(btc)
        g1 = bp > roll(btc, 50, "mean")
        R = C / shift1(C) - 1
        Re = np.where(self.elig & np.isfinite(R), R, np.nan)
        with np.errstate(all="ignore"):
            idx = np.where(np.isfinite(Re).any(1), np.nanmean(Re, 1), 0.0)
        lvl = np.cumprod(1 + idx)
        g2 = shift1(lvl) > roll(lvl, 20, "mean")
        self.G = {0: np.ones(self.T, bool), 1: np.nan_to_num(g1, nan=0).astype(bool), 2: np.nan_to_num(g2, nan=0).astype(bool)}
        self.monday = self.days.weekday == 0
        self.dix = dix

    def sma(self, n):
        k = ("sma", n)
        if k not in self.cache:
            self.cache[k] = roll(self.C, n, "mean")
        return self.cache[k]

    def ret(self, L):
        k = ("ret", L)
        if k not in self.cache:
            past = np.full_like(self.C, np.nan)
            past[L + 1:] = self.C[:-L - 1]
            self.cache[k] = self.Cp / past - 1
        return self.cache[k]

    def hi(self, n):          # highest close of the n days before d-1 (d-1-n .. d-2)
        k = ("hi", n)
        if k not in self.cache:
            self.cache[k] = shift1(roll(self.C, n, "max"))
        return self.cache[k]

    def lo(self, n):
        k = ("lo", n)
        if k not in self.cache:
            self.cache[k] = shift1(roll(self.C, n, "min"))
        return self.cache[k]


# ---------------------------------------------------------------- rules
def rules():
    out = []
    for g in (0, 1, 2):
        out += [dict(f="F1", n=n, g=g) for n in (10, 20, 50, 100, 200)]
        out += [dict(f="F2", n=n, m=m, g=g) for n, m in ((10, 5), (20, 5), (20, 10), (55, 5), (55, 10), (55, 20))]
        out += [dict(f="F3", L=L, K=K, g=g) for L in (7, 14, 30, 60) for K in (1, 3, 5)]
        out += [dict(f="F4", L=L, H=H, K=K, g=g) for L in (1, 3, 7) for H in (1, 3, 7) for K in (1, 3)]
        out += [dict(f="F5", X=X, R=R, H=H, g=g) for X in (3, 5) for R in (0.10, 0.20) for H in (1, 3, 7)]
        out += [dict(f="F6", D=D, H=H, S=S, g=g) for D in (0.15, 0.25, 0.35) for H in (3, 7, 14) for S in (None, 0.20)]
    return out


def name(r):
    return " ".join(f"{k}={v}" for k, v in r.items())


DEFAULTS = [dict(f="F1", n=50, g=0), dict(f="F2", n=20, m=10, g=0), dict(f="F3", L=30, K=3, g=0),
            dict(f="F4", L=3, H=3, K=3, g=0), dict(f="F5", X=5, R=0.20, H=3, g=0), dict(f="F6", D=0.25, H=7, S=None, g=0)]


def desired(w, r, F):
    """Boolean T x N: the coins the rule wants to hold from the fill of day d (before eligibility and the filter)."""
    T, N, Cp = w.T, w.N, w.Cp
    f = r["f"]
    if f == "F1":
        return np.nan_to_num(Cp > w.sma(r["n"]), nan=0).astype(bool)
    D = np.zeros((T, N), bool)
    if f == "F2":
        ent = np.nan_to_num(Cp > w.hi(r["n"]), nan=0).astype(bool)
        ext = np.nan_to_num(Cp < w.lo(r["m"]), nan=0).astype(bool)
        s = np.zeros(N, bool)
        for d in range(T):
            s = np.where(s, ~ext[d], ent[d])
            D[d] = s
        return D
    if f in ("F3", "F4"):
        R = w.ret(r["L"])
        cur = np.zeros(N, bool)
        for d in range(T):
            reb = w.monday[d] if f == "F3" else (d % r["H"] == 0)
            if reb:
                x = np.where(w.elig[d] & np.isfinite(R[d]), R[d], np.nan)
                ok = np.flatnonzero(np.isfinite(x))
                cur = np.zeros(N, bool)
                if len(ok):
                    order = ok[np.argsort(-x[ok] if f == "F3" else x[ok], kind="stable")]
                    cur[order[:r["K"]]] = True
            D[d] = cur
        return D
    if f == "F5":
        qp = shift1(w.qv)
        med = shift1(roll(np.nan_to_num(w.qv), 30, "median"))        # the 30 days before day d-1
        up = w.Cp / shift1(w.Cp) - 1
        sig = np.nan_to_num((qp >= r["X"] * med) & (med > 0) & (up >= r["R"]), nan=0).astype(bool)
        end = np.full(N, -1)
        for d in range(T):
            new = sig[d] & (end <= d)
            end = np.where(new, d + r["H"], end)
            D[d] = end > d
        return D
    if f == "F6":
        top = roll(w.C, 20, "max")                                    # highest close of d-20..d-1
        sig = np.nan_to_num((Cp > w.sma(100)) & (Cp <= (1 - r["D"]) * top), nan=0).astype(bool)
        start = np.full(N, -1)
        ref = np.full(N, np.nan)
        on = np.zeros(N, bool)
        for d in range(T):
            if on.any():
                out = on & ((d >= start + r["H"]) | ((Cp[d] <= ref * (1 - r["S"])) if r["S"] else False))
                on = on & ~np.nan_to_num(out, nan=0).astype(bool)
            new = sig[d] & ~on
            if new.any():
                on = on | new
                start = np.where(new, d, start)
                ref = np.where(new, np.where(np.isfinite(F[d]), F[d], Cp[d]), ref)
            D[d] = on
        return D
    raise ValueError(f)


def simulate(w, r, cost, fill, month_first, pm):
    """The account of one rule. Returns daily move and cost parts, month-start weights and the trades."""
    F = w.F[fill]
    D = desired(w, r, F)
    A = D & w.elig & w.G[r["g"]][:, None]
    T, N = w.T, w.N
    topk = r["f"] in ("F3", "F4")
    units = np.zeros(N)
    held = np.zeros(N, bool)
    entry = {}
    mark = np.full(N, np.nan)
    cash, eq = 1.0, 1.0
    rmove, rcost = np.zeros(T), np.zeros(T)
    wpre, wpost = {}, {}
    trades = []
    held_days = np.zeros(T)
    for d in range(T):
        p = F[d]
        mark = np.where(np.isfinite(p), p, np.where(np.isfinite(w.Cp[d]), w.Cp[d], mark))
        val = cash + np.nansum(units * np.nan_to_num(mark))
        rmove[d] = val / eq - 1 if eq > 0 else 0.0
        if d in month_first:
            wpre[d] = np.nan_to_num(units * mark) / val
        can = np.isfinite(p)
        dead = held & (d > w.li)
        sell = held & ((~A[d] & can) | dead)
        for i in np.flatnonzero(sell):
            px = p[i] if can[i] else mark[i]
            cash += units[i] * px * (1 - cost)
            e_d, e_amt = entry.pop(i)
            trades.append((i, e_d, d, units[i] * px * (1 - cost) / e_amt - 1, False))
            units[i] = 0.0
            held[i] = False
        buy = A[d] & ~held & can
        if buy.any():
            size = val / (r["K"] if topk else max(5, int(w.nelig[d])))
            for i in np.flatnonzero(buy):
                amt = min(size, cash)
                if amt <= 1e-9:
                    break
                cash -= amt
                units[i] = amt * (1 - cost) / p[i]
                held[i] = True
                entry[i] = (d, amt)
        new = cash + np.nansum(units * np.nan_to_num(mark))
        rcost[d] = 1 - new / val if val > 0 else 0.0
        eq = new
        held_days[d] = held.sum()
        if d in month_first:
            wpost[d] = np.nan_to_num(units * mark) / new
    for i, (e_d, e_amt) in entry.items():       # still open at the end: marked with the exit cost
        trades.append((i, e_d, T - 1, units[i] * mark[i] * (1 - cost) / e_amt - 1, True))
    r_day = (1 + rmove) * (1 - rcost) - 1
    entry_m = [int(pm[t[1]]) for t in trades]
    exit_m = np.sort(np.array([pm[t[2]] for t in trades if not t[4]], dtype=np.int64))
    return dict(r=r_day, rmove=rmove, wpre=wpre, wpost=wpost, trades=trades, held=held_days, entry_m=entry_m, exit_m=exit_m)


# ---------------------------------------------------------------- months, walk-forward, statistics
class Cal:
    """Months as integer ordinals (months since 1970-01) so the walk-forward loops stay cheap."""
    def __init__(self, days):
        self.pm = days.to_period("M").asi8
        self.months = sorted(set(self.pm.tolist()))
        self.first = {m: int(np.flatnonzero(self.pm == m)[0]) for m in self.months}
        self.idx = {m: np.flatnonzero(self.pm == m) for m in self.months}

    @staticmethod
    def o(s):
        return pd.Period(s, "M").ordinal

    @staticmethod
    def s(m):
        return str(pd.Period(ordinal=m, freq="M"))


def month_returns(r, cal):
    return {m: float(np.expm1(np.log1p(r[cal.idx[m]]).sum())) for m in cal.months}


def in_range(m, a, b):
    return Cal.o(a) <= m <= Cal.o(b)


def score_window(sim, cal, m, w):
    lo = m - 24
    idx = np.flatnonzero((cal.pm >= lo) & (cal.pm < m))
    if len(idx) == 0 or (w.nelig[idx] > 0).sum() < 180:
        return None
    ex = sim["exit_m"]
    ntr = np.searchsorted(ex, m, "left") - np.searchsorted(ex, lo, "left")
    x = sim["r"][idx]
    sd = x.std()
    if ntr < 20 or sd <= 0:
        return None
    return x.mean() / sd


def chain(sims, sel, cost, cal, w, with_trades=True):
    """Month returns, daily returns and trades of a month-by-month choice (None = cash), switching cost included."""
    mret, daily, trades = {}, [], []
    prev = None
    for m in sel:
        b = sel[m]
        d1 = cal.first[m]
        idx = cal.idx[m]
        rb = sims[b]["r"][idx] if b is not None else np.zeros(len(idx))
        if b != prev:
            move = sims[prev]["rmove"][d1] if prev is not None else 0.0
            wa = sims[prev]["wpre"][d1] if prev is not None else np.zeros(w.N)
            wb = sims[b]["wpost"][d1] if b is not None else np.zeros(w.N)
            rb = rb.copy()
            rb[0] = (1 + move) * (1 - cost * np.abs(wb - wa).sum()) - 1
        mret[m] = float(np.prod(1 + rb) - 1)
        if with_trades:
            daily.append(rb)
            if b is not None:
                trades += [t for t, em in zip(sims[b]["trades"], sims[b]["entry_m"]) if em == m]
        prev = b
    return mret, (np.concatenate(daily) if daily else np.zeros(0)), trades


def boot_p(x, rng):
    x = np.asarray(x, float)
    if len(x) < 2:
        return 1.0, float("nan")
    means = x[rng.integers(0, len(x), size=(DRAWS, len(x)))].mean(1)
    return float(((means <= 0).sum() + 1) / (DRAWS + 1)), float(np.quantile(means, 0.01))


def max_dd(r):
    e = np.cumprod(1 + np.asarray(r))
    return float((e / np.maximum.accumulate(e) - 1).min()) if len(e) else 0.0


def summary(mret, daily, trades, months_used, rng):
    tr = [t[3] for t in trades]
    closed = [t for t in trades if not t[4]]
    mr = [mret[m] for m in months_used]
    p_tr, lb_tr = boot_p(tr, rng)
    p_mo, lb_mo = boot_p(mr, rng)
    out = dict(
        months=len(mr), trades=len(tr), closed=len(closed),
        mean_trade=float(np.mean(tr)) if tr else float("nan"),
        median_trade=float(np.median(tr)) if tr else float("nan"),
        win_share=float(np.mean(np.array(tr) > 0)) if tr else float("nan"),
        mean_trade_wo_best=float(np.mean(sorted(tr)[:-1])) if len(tr) > 1 else float("nan"),
        p_trade=p_tr, lb1_trade=lb_tr,
        mean_month=float(np.mean(mr)) if mr else float("nan"),
        median_month=float(np.median(mr)) if mr else float("nan"),
        mean_month_wo_best=float(np.mean(sorted(mr)[:-1])) if len(mr) > 1 else float("nan"),
        p_month=p_mo, lb1_month=lb_mo,
        total=float(np.prod(1 + np.array(mr)) - 1) if mr else 0.0,
        worst_month=float(min(mr)) if mr else float("nan"),
        best_month=float(max(mr)) if mr else float("nan"),
        pos_months=int(sum(x > 0 for x in mr)),
        max_dd=max_dd(daily),
        thirds=[float(np.mean([mret[m] for m in months_used if in_range(m, a, b)] or [np.nan])) for a, b in THIRDS],
        hold_days=float(np.mean([t[2] - t[1] for t in trades])) if trades else float("nan"),
        trades_per_week=len(tr) / max(1, len(daily) / 7),
    )
    return out


def holm(ps, alpha=0.01):
    order = np.argsort(ps)
    ok = np.zeros(len(ps), bool)
    for k, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - k):
            ok[i] = True
        else:
            break
    return ok


def run_variant(w, rl, variant, cal, sealed):
    cost, fill = VARIANTS[variant]
    mf = set(cal.first.values())
    sims = [simulate(w, r, cost, fill, mf, cal.pm) for r in rl]
    lo, hi = (SEALED if sealed else TEST)
    tm = [m for m in cal.months if in_range(m, lo, hi)]
    sel, qual = {}, {}
    for m in tm:                                   # walk-forward: the best score on the 24 months before m
        sc = [score_window(s, cal, m, w) for s in sims]
        q = [i for i, x in enumerate(sc) if x is not None]
        qual[m] = q
        sel[m] = max(q, key=lambda i: sc[i]) if q else None
    return sims, tm, sel, qual


def bench_basket(w, cost, fill, cal, tm, rng):
    """B1: equal weight of every eligible coin, rebalanced at the first fill of each month."""
    F = w.F[fill]
    units = np.zeros(w.N)
    cash, eq = 1.0, 1.0
    r = np.zeros(w.T)
    mark = np.full(w.N, np.nan)
    fd = set(cal.first.values())
    for d in range(w.T):
        p = F[d]
        mark = np.where(np.isfinite(p), p, np.where(np.isfinite(w.Cp[d]), w.Cp[d], mark))
        dead = (units > 0) & (d > w.li)
        cash += (units[dead] * mark[dead] * (1 - cost)).sum()
        units[dead] = 0.0
        val = cash + np.nansum(units * np.nan_to_num(mark))
        if d in fd:
            tgt = w.elig[d] & np.isfinite(p)
            n = int(tgt.sum())
            have = np.nan_to_num(units * mark)
            want0 = np.where(tgt, val / n, 0.0) if n else np.zeros(w.N)
            tc = cost * np.abs(want0 - have).sum()
            if n:
                units = np.where(tgt, (val - tc) / n / np.where(tgt, p, 1.0), 0.0)
                cash = 0.0
            else:
                units = np.zeros(w.N)
                cash = val - tc
        new = cash + np.nansum(units * np.nan_to_num(mark))
        r[d] = new / eq - 1
        eq = new
    mr = month_returns(r, cal)
    idx = np.isin(cal.pm, tm)
    out = summary(mr, r[idx], [], tm, rng)
    out["by_month"] = {Cal.s(m): mr[m] for m in tm}
    return out


def bench_hold(c, cal, tm):
    s = pd.Series(c).ffill().to_numpy()
    r = np.nan_to_num(s / shift1(s) - 1)
    mr = month_returns(r, cal)
    x = [mr[m] for m in tm]
    return dict(mean_month=float(np.mean(x)), total=float(np.prod(1 + np.array(x)) - 1),
                max_dd=max_dd(r[np.isin(cal.pm, tm)]), worst_month=float(min(x)), by_month={Cal.s(m): mr[m] for m in tm})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--universe", default="research/bigmemes/UNIVERSE.json")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--random", type=int, default=1000)
    ap.add_argument("--out", default="research/bigmemes/RESULT.json")
    a = ap.parse_args()
    days, syms, M, btc, first_day, last_day, gaps = load(a.data, a.holdout, a.universe)
    w = World(days, syms, M, btc, first_day, last_day)
    cal = Cal(days)
    rl = rules()
    res = dict(holdout=a.holdout, coins=len(syms), days=[str(days[0].date()), str(days[-1].date())],
               ever_eligible=[s for s, e in zip(syms, w.elig.any(0)) if e], gaps_over_72h=gaps,
               eligible_at_month_start={Cal.s(m): int(w.elig[cal.first[m]].sum()) for m in cal.months}, variants={})
    for variant in a.variants.split(","):
        rng = np.random.default_rng(SEED)
        cost = VARIANTS[variant][0]
        sims, tm, sel, qual = run_variant(w, rl, variant, cal, a.holdout)
        out = dict(test_months=[Cal.s(m) for m in tm])
        mret, daily_r, trades = chain(sims, sel, cost, cal, w)
        out["WF"] = summary(mret, daily_r, trades, tm, rng)
        out["WF"]["picks"] = {Cal.s(m): (name(rl[sel[m]]) if sel[m] is not None else "cash") for m in tm}
        out["WF"]["by_month"] = {Cal.s(m): mret[m] for m in tm}
        out["WF"]["trade_list"] = [(syms[t[0]], str(days[t[1]].date()), str(days[t[2]].date()), t[3], t[4]) for t in trades]
        for dr in DEFAULTS:
            i = rl.index(dr)
            mr, dl, tr = chain(sims, {m: i for m in tm}, cost, cal, w)
            out[name(dr)] = summary(mr, dl, tr, tm, rng)
            out[name(dr)]["by_month"] = {Cal.s(m): mr[m] for m in tm}
            out[name(dr)]["coins_held"] = float(sims[i]["held"][np.isin(cal.pm, tm)].mean())
        out["B1 basket"] = bench_basket(w, cost, VARIANTS[variant][1], cal, tm, rng)
        out["B2 BTC"] = bench_hold(btc, cal, tm)
        if "DOGEUSDT" in syms:
            out["B3 DOGE"] = bench_hold(w.C[:, syms.index("DOGEUSDT")], cal, tm)
        allr = []
        for i, s in enumerate(sims):            # every rule on its own (information only)
            mr = month_returns(s["r"], cal)
            x = [mr[m] for m in tm]
            allr.append((name(rl[i]), float(np.mean(x)), int(sum(v > 0 for v in x)),
                         int(sum(1 for em in s["entry_m"] if em in set(tm)))))
        out["rules"] = allr
        out["hindsight_best"] = max(allr, key=lambda x: x[1])
        rnd = []
        for k in range(a.random):               # a random qualifying rule each month
            rr = np.random.default_rng(1000 + k)
            ch = {m: (int(rr.choice(qual[m])) if qual[m] else None) for m in tm}
            mr, _, _ = chain(sims, ch, cost, cal, w, with_trades=False)
            rnd.append(float(np.mean([mr[m] for m in tm])))
        if rnd:
            out["random_choice_mean_month"] = dict(
                median=float(np.median(rnd)), p05=float(np.quantile(rnd, 0.05)), p95=float(np.quantile(rnd, 0.95)),
                share_below_wf=float(np.mean(np.array(rnd) < out["WF"]["mean_month"])))
        res["variants"][variant] = out
        print(variant, "WF", fmt(out["WF"]), flush=True)
        for dr in DEFAULTS:
            print(variant, name(dr), fmt(out[name(dr)]), flush=True)
        print(variant, "B1", fmt(out["B1 basket"]), "| BTC", out["B2 BTC"], flush=True)
        print(variant, "hindsight best", out["hindsight_best"], "| random", out.get("random_choice_mean_month"), flush=True)
    if not a.holdout and {"base", "stress"} <= set(res["variants"]):
        b, st = res["variants"]["base"], res["variants"]["stress"]
        cands = ["WF"] + [name(d) for d in DEFAULTS]
        okt = holm([b[c]["p_trade"] for c in cands])
        okm = holm([b[c]["p_month"] for c in cands])
        verdict = {}
        for k, c in enumerate(cands):
            x, y = b[c], st[c]
            crit = {
                "1_closed_trades>=40": bool(x["closed"] >= 40),
                "2_mean_trade>0": bool(x["mean_trade"] > 0),
                "3_holm_1pct_trades_and_months": bool(okt[k] and okm[k]),
                "4_wo_best_trade_and_month>0": bool(x["mean_trade_wo_best"] > 0 and x["mean_month_wo_best"] > 0),
                "5_two_of_three_thirds>0": bool(sum(v > 0 for v in x["thirds"]) >= 2),
                "6_stress>0": bool(y["mean_trade"] > 0 and y["mean_month"] > 0),
            }
            verdict[c] = dict(crit=crit, passes_1_to_6=all(crit.values()))
            print("VERDICT", c, verdict[c]["passes_1_to_6"], crit, flush=True)
        res["verdict"] = verdict
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1, default=str)


def fmt(x):
    keys = ("closed", "mean_trade", "p_trade", "mean_month", "p_month", "total", "max_dd", "worst_month")
    return " ".join(f"{k}={x[k]:.4g}" if isinstance(x.get(k), float) else f"{k}={x.get(k)}" for k in keys if k in x)


if __name__ == "__main__":
    main()
