"""The wallet study, one launch day (research/wallets/PREREG-WALLETS-2026-11-11.md). Fake money only: past data, nothing is bought.

usage: python3 research/wallets/wallet_day.py <files.json> <YYYY-MM-DD> <out dir>
Downloads the Pumpfun_v2 create and trade files that cover the coins launched on that UTC day (Slinky21/Pumpfun_v2_dataset,
CC BY 4.0), finds every event (a wallet's first buy of 0.05 SOL or more in a coin) and what a copier would have got from it.
Writes <out>/ev_<day>.npz (one row per event) and <out>/wl_<day>.npz (wallet hash -> address).
"""
import calendar, hashlib, json, os, sys, time, urllib.parse, urllib.request
import numpy as np
from numba import njit

SRC = "Slinky21/Pumpfun_v2_dataset"
UA = {"User-Agent": "memebot-research"}
H, DAY = 3600, 86400                   # seconds
BIG = 50_000_000                       # 0.05 SOL in lamports
TICKET, SLIP = 20.0, 0.01
DELAYS = (30, 5)                       # judged: 30 s; information: 5 s
WINDOW = 24 * H
GRAD = 80e9                            # lamports in the curve: "completed"
TP = 10.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            log("get failed", url[:110], type(e).__name__, str(e)[:100])
            time.sleep(10 * (i + 1))
    raise SystemExit("could not get " + url)


def stamp_s(path):
    s = path.split("_")[-1].split(".")[0]          # 20260924T032055
    return calendar.timegm(time.strptime(s, "%Y%m%dT%H%M%S"))


def files_for(files, table, lo, hi):
    """Files of a table whose stamp (end of the file's ~12 hours) lies in (lo, hi + 13 h]."""
    fs = sorted(p for p, _ in files if "/%s/" % table in p)
    return [p for p in fs if lo < stamp_s(p) <= hi + 13 * H]


def read(path, cols, tmp):
    import pyarrow.parquet as pq
    url = "https://huggingface.co/datasets/%s/resolve/main/%s" % (SRC, urllib.parse.quote(path))
    for i in range(6):
        try:
            urllib.request.urlretrieve(url, tmp)
            break
        except Exception as e:
            log("download failed", path, type(e).__name__, str(e)[:100])
            time.sleep(15 * (i + 1))
    else:
        raise SystemExit("could not download " + path)
    t = pq.read_table(tmp, columns=cols)
    os.remove(tmp)
    return t


def secs(arr):
    import pyarrow as pa, pyarrow.compute as pc
    a = arr.combine_chunks() if hasattr(arr, "combine_chunks") else arr
    v = pc.cast(a, pa.int64()).to_numpy(zero_copy_only=False)
    return v // {"s": 1, "ms": 1000, "us": 1_000_000, "ns": 1_000_000_000}[arr.type.unit]


def solusd(t0, t1):
    out, s = {}, t0 - t0 % H
    while s < t1:
        e = min(t1, s + 290 * H)
        url = "https://api.exchange.coinbase.com/products/SOL-USD/candles?granularity=3600&start=%s&end=%s" % (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s)), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e)))
        for row in get(url):
            out[int(row[0])] = float(row[4])
        s = e
        time.sleep(0.4)
    return out


# ------------------------------------------------------------------------------------------------------------ the copy

@njit(cache=False)
def fee(x):
    """FOMO's Solana fee per buy and per sell, network included."""
    if x < 5.0:
        return 0.10
    if x < 47.5:
        return 0.02 * x
    if x < 190.0:
        return 0.95
    return 0.005 * x


@njit(cache=False)
def lower(t, lo, hi, x):
    """First index in [lo, hi) with t[index] >= x, else hi."""
    while lo < hi:
        mid = (lo + hi) // 2
        if t[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


@njit(cache=False)
def desk(t, p, a, j_end):
    """The video desk's sell rules from the entry at index a to j_end: -8% stop until 2x, stake out at 2x, 10% trail."""
    entry = p[a] * (1 + SLIP)
    tok = TICKET / entry
    cash, fees = 0.0, fee(TICKET)
    half, high = False, 0.0
    for j in range(a + 1, j_end + 1):
        q = p[j] * (1 - SLIP)
        if not half:
            if q <= entry * 0.92:
                v = tok * q; cash += v; fees += fee(v); tok = 0.0
                break
            if q >= 2 * entry:
                sell = TICKET / q; v = sell * q; cash += v; fees += fee(v); tok -= sell
                half, high = True, q
        else:
            high = max(high, q)
            if q <= 0.9 * high:
                v = tok * q; cash += v; fees += fee(v); tok = 0.0
                break
    if tok > 0:
        v = tok * p[j_end] * (1 - SLIP); cash += v; fees += fee(v)
    return cash - TICKET - fees


@njit(cache=False)
def kernel(ev_i, ev_sell, m, t, p, ends, gi, data_end, delay):
    """Per event: the copier's mirror exit (ratio exit/entry after slippage, how, exit time), hold ratio and how, desk result,
    entry index. how: 0 the wallet sold, 1 time or data end, 2 no later trade (last price), 3 curve completed, 4 ten times."""
    n = len(ev_i)
    r = np.full(n, np.nan); how = np.full(n, 255, np.uint8); xt = np.zeros(n, np.int64)
    rh = np.full(n, np.nan); hh = np.full(n, 255, np.uint8); dk = np.full(n, np.nan)
    ent = np.full(n, -1, np.int64)
    for e in range(n):
        b = ev_i[e]
        mm = m[b]
        end = ends[mm]                 # one past the coin's last trade
        a = lower(t, b, end, t[b] + delay)
        if a >= end:
            continue
        ent[e] = a
        last = end - 1
        entry = p[a] * (1 + SLIP)
        end_t = min(t[a] + WINDOW, data_end)
        j_end = lower(t, a, end, end_t) - 1
        if j_end < a:
            j_end = a
        g = gi[mm]
        s = ev_sell[e]
        if s >= 0:
            jx = lower(t, a, end, t[s] + delay)
            if jx > last:
                jx = last
                h = 3 if g >= 0 else 2
            else:
                h = 0
            if jx > j_end:
                jx = j_end; h = 1
        else:
            jx = j_end; h = 1
            if g >= 0:
                h = 3
                if g >= a and g <= j_end:
                    jx = g
        for j in range(a + 1, jx + 1):
            if p[j] * (1 - SLIP) >= TP * entry:
                jx = j; h = 4
                break
        r[e] = p[jx] * (1 - SLIP) / entry
        how[e] = h; xt[e] = t[jx]
        jh = j_end; h2 = 1
        if g >= a and g <= j_end:
            jh = g; h2 = 3
        rh[e] = p[jh] * (1 - SLIP) / entry; hh[e] = h2
        dk[e] = desk(t, p, a, j_end)
    return r, how, xt, rh, hh, dk, ent


def events(m, t, u, buy, sol, tok, price, rs, cr, data_end):
    """All events of trades sorted by (coin code m, slot, tx index). cr: creator's user code per coin code (-1 unknown).
    Returns a dict of arrays, one row per event."""
    N = len(m)
    n_coins = int(m.max()) + 1
    bounds = np.flatnonzero(np.diff(m)) + 1
    starts = np.concatenate([[0], bounds]); ends_seg = np.concatenate([bounds, [N]])
    ends = np.zeros(n_coins, np.int64); ends[m[starts]] = ends_seg
    pos = np.arange(N, dtype=np.int64)
    U = int(u.max()) + 1
    _, pid = np.unique(m.astype(np.int64) * U + u, return_inverse=True)
    n_pairs = int(pid.max()) + 1
    big = buy & (sol >= BIG) & (u != cr[m])
    ib = np.flatnonzero(big)
    ev_pid, first = np.unique(pid[ib], return_index=True)
    ev_i = ib[first]
    first_of = np.full(n_pairs, N, np.int64); first_of[ev_pid] = ev_i
    after = pos >= first_of[pid]
    own_in = np.bincount(pid, weights=np.where(buy & after, sol, 0), minlength=n_pairs) / 1e9
    own_out = np.bincount(pid, weights=np.where(~buy & after, sol, 0), minlength=n_pairs) / 1e9
    net = np.bincount(pid, weights=np.where(after, np.where(buy, tok, -tok), 0.0), minlength=n_pairs) / 1e6
    p_last = np.zeros(n_coins); p_last[m[starts]] = price[ends_seg - 1]
    isl = np.flatnonzero(~buy & after)
    s_pid, s_first = np.unique(pid[isl], return_index=True)
    sell_of = np.full(n_pairs, -1, np.int64); sell_of[s_pid] = isl[s_first]
    ev_sell = sell_of[ev_pid]
    # the first trade of each coin with 80 SOL or more in the curve
    gi = np.full(n_coins, -1, np.int64)
    ig = np.flatnonzero(rs >= GRAD)
    if len(ig):
        gm, gf = np.unique(m[ig], return_index=True)
        gi[gm] = ig[gf]
    order = np.argsort(ev_i, kind="stable")
    ev_i, ev_pid, ev_sell = ev_i[order], ev_pid[order], ev_sell[order]
    out = dict(i=ev_i, m=m[ev_i].astype(np.int32), u=u[ev_i], t=t[ev_i], buy_sol=(sol[ev_i] / 1e9).astype(np.float32),
               hold=np.where(ev_sell >= 0, t[np.maximum(ev_sell, 0)] - t[ev_i], -1).astype(np.int32),
               own_in=own_in[ev_pid].astype(np.float32),
               own_pnl=(own_out[ev_pid] - own_in[ev_pid] + np.maximum(net[ev_pid], 0) * p_last[m[ev_i]]).astype(np.float32),
               grad=(gi[m[ev_i]] >= 0))
    for d in DELAYS:
        r, how, xt, rh, hh, dk, ent = kernel(ev_i, ev_sell, m, t, price, ends, gi, data_end, d)
        k = "" if d == DELAYS[0] else str(d)
        out["r" + k] = r.astype(np.float32); out["how" + k] = how
        if d == DELAYS[0]:
            out.update(xt=xt, rh=rh.astype(np.float32), hh=hh, desk=dk.astype(np.float32), ent=ent)
    return out


# ------------------------------------------------------------------------------------------------------------ main

def main():
    files = [tuple(x) for x in json.load(open(sys.argv[1]))]
    day, out = sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    d0 = calendar.timegm(time.strptime(day, "%Y-%m-%d"))
    d1 = d0 + DAY
    data_end = d1 + DAY + 4 * H
    tmp = os.path.join(out, "tmp_%s.parquet" % day)
    import pyarrow as pa, pyarrow.compute as pc

    launch, supply, creator_of = {}, {}, {}
    for f in files_for(files, "create", d0, d1):
        tb = read(f, ["block_time", "mint", "creator", "is_mayhem_mode", "token_total_supply"], tmp)
        bt = secs(tb.column("block_time"))
        mi, cr = tb.column("mint").to_pylist(), tb.column("creator").to_pylist()
        mm, su = tb.column("is_mayhem_mode").to_pylist(), tb.column("token_total_supply").to_pylist()
        for k in range(len(mi)):
            if d0 <= bt[k] < d1 and not mm[k]:
                launch[mi[k]] = int(bt[k]); supply[mi[k]] = (su[k] or 10 ** 15) / 1e6; creator_of[mi[k]] = cr[k]
        log("create", f.split("/")[-1], "launches so far", len(launch))
    mints = pa.array(sorted(launch))

    parts = []
    cols = ["block_time", "slot", "tx_index", "mint", "trade_user", "ix_name", "sol_amount", "token_amount",
            "virtual_sol_reserves", "virtual_token_reserves", "real_sol_reserves"]
    for f in files_for(files, "trade", d0, data_end - 13 * H):
        tb = read(f, cols, tmp)
        tb = tb.filter(pc.is_in(tb.column("mint"), value_set=mints))
        parts.append(tb)
        log("trade", f.split("/")[-1], "rows kept", tb.num_rows)
    tb = pa.concat_tables(parts)
    del parts
    t_all = secs(tb.column("block_time"))
    keep = t_all < data_end
    tb = tb.filter(pa.array(keep)); t_all = t_all[keep]
    mc_ = pc.dictionary_encode(tb.column("mint")).combine_chunks()
    uc_ = pc.dictionary_encode(tb.column("trade_user")).combine_chunks()
    m_idx = mc_.indices.to_numpy(zero_copy_only=False).astype(np.int64)
    m_names = mc_.dictionary.to_pylist()
    u_idx = uc_.indices.to_numpy(zero_copy_only=False).astype(np.int64)
    u_names = uc_.dictionary.to_pylist()
    u_code = {x: k for k, x in enumerate(u_names)}
    is_buy = (tb.column("ix_name").to_numpy(zero_copy_only=False) != "sell")
    num = lambda c, ty: tb.column(c).to_numpy(zero_copy_only=False).astype(ty)
    slot, txi, sol, tok = num("slot", "int64"), num("tx_index", "int64"), num("sol_amount", "int64"), num("token_amount", "float64")
    vs, vt, rs = num("virtual_sol_reserves", "float64"), num("virtual_token_reserves", "float64"), num("real_sol_reserves", "float64")
    del tb
    price = (vs / 1e9) / np.maximum(vt / 1e6, 1e-9)          # SOL per token, after the trade
    order = np.lexsort((txi, slot, m_idx))
    m_idx, t_all, u_idx, is_buy, sol, tok, price, rs = (a[order] for a in (m_idx, t_all, u_idx, is_buy, sol, tok, price, rs))
    del slot, txi, vs, vt, order
    back = int(np.sum((np.diff(t_all) < 0) & (np.diff(m_idx) == 0)))
    log("trades", len(t_all), "coins", len(m_names), "launches", len(launch), "users", len(u_names), "time steps back", back)
    if back:                                                 # a later slot with an earlier clock: keep the time non-decreasing per coin
        seg = np.concatenate([[0], np.flatnonzero(np.diff(m_idx)) + 1, [len(m_idx)]])
        for s, e in zip(seg[:-1], seg[1:]):
            t_all[s:e] = np.maximum.accumulate(t_all[s:e])
    cr = np.array([u_code.get(creator_of[x], -1) for x in m_names], np.int64)

    ev = events(m_idx, t_all, u_idx, is_buy, sol, tok, price, rs, cr, data_end)
    n = len(ev["i"])
    ok = ev["ent"] >= 0
    log("events", n, "with a copy", int(ok.sum()), "wallet sold", int((ev["hold"] >= 0).sum()))

    sp = solusd(d0 - H, data_end + H)
    hours = np.array(sorted(sp)); closes = np.array([sp[h] for h in hours])
    a = np.maximum(ev["ent"], 0)
    usd = closes[np.clip(np.searchsorted(hours, t_all[a], side="right") - 1, 0, len(hours) - 1)]
    sup = np.array([supply[x] for x in m_names])
    mc = np.where(ok, price[a] * sup[ev["m"]] * usd, np.nan).astype(np.float32)
    L = np.array([launch[x] for x in m_names], np.int64)
    age = (np.where(ok, t_all[a], ev["t"]) - L[ev["m"]]).astype(np.int32)

    uu, inv = np.unique(ev["u"], return_inverse=True)
    addr = [u_names[k] for k in uu]
    hsh = np.array([int.from_bytes(hashlib.blake2b(x.encode(), digest_size=8).digest(), "little") for x in addr], np.uint64)
    np.savez_compressed(os.path.join(out, "ev_%s.npz" % day), w=hsh[inv], m=ev["m"], t=ev["t"], xt=ev["xt"], buy_sol=ev["buy_sol"],
                        hold=ev["hold"], own_in=ev["own_in"], own_pnl=ev["own_pnl"], grad=ev["grad"], r=ev["r"], how=ev["how"],
                        rh=ev["rh"], hh=ev["hh"], desk=ev["desk"], r5=ev["r5"], how5=ev["how5"], mc=mc, age=age,
                        mints=np.array(m_names, dtype="S44"), n_trades=np.int64(len(t_all)))
    np.savez_compressed(os.path.join(out, "wl_%s.npz" % day), h=hsh, a=np.array(addr, dtype="S44"))
    log("done", day, "file MB", round(os.path.getsize(os.path.join(out, "ev_%s.npz" % day)) / 1e6, 1))


if __name__ == "__main__":
    main()
