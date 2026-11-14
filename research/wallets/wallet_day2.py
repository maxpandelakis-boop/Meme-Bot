"""Copy trading round 2, one launch day (research/wallets/PREREG-COPY2-2026-11-13.md). Fake money only.

usage: python3 research/wallets/wallet_day2.py <files.json> <YYYY-MM-DD> <out dir>
As wallet_day.py, but per event: four delays, four exits, and the pool size at the entry. Writes <out>/e2_<day>.npz, wl_<day>.npz.
"""
import calendar, hashlib, json, os, sys, time
import numpy as np
from numba import njit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet_day as wd
from wallet_day import lower, SLIP, WINDOW, TP, GRAD, BIG, H, DAY, log

DELAYS = (1, 2, 5, 30)
TPSL = ((1.5, 0.8), (2.0, 0.7))


@njit(cache=False)
def kernel2(ev_i, ev_sell, m, t, p, ends, gi, data_end, delay, tps, sls):
    """Per event and exit (0 mirror, 1 and 2 mirror with take profit / stop, 3 hold): ratio exit/entry after 1% a side, and how:
    0 the wallet sold, 1 time or data end, 2 no later trade, 3 curve completed, 4 ten times, 5 take profit, 6 stop."""
    n = len(ev_i)
    r = np.full((n, 4), np.nan, np.float32); how = np.full((n, 4), 255, np.uint8)
    ent = np.full(n, -1, np.int64)
    for e in range(n):
        b = ev_i[e]
        mm = m[b]
        end = ends[mm]
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
        r[e, 0] = p[jx] * (1 - SLIP) / entry; how[e, 0] = h
        for k in range(2):
            jk = jx; hk = h
            for j in range(a + 1, jx + 1):
                q = p[j] * (1 - SLIP)
                if q >= tps[k] * entry:
                    jk = j; hk = 5
                    break
                if q <= sls[k] * entry:
                    jk = j; hk = 6
                    break
            r[e, 1 + k] = p[jk] * (1 - SLIP) / entry; how[e, 1 + k] = hk
        jh = j_end; h2 = 1
        if g >= a and g <= j_end:
            jh = g; h2 = 3
        r[e, 3] = p[jh] * (1 - SLIP) / entry; how[e, 3] = h2
    return r, how, ent


def main():
    files = [tuple(x) for x in json.load(open(sys.argv[1]))]
    day, out = sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    d0 = calendar.timegm(time.strptime(day, "%Y-%m-%d"))
    d1 = d0 + DAY
    data_end = d1 + DAY + 4 * H
    tmp = os.path.join(out, "tmp_%s.parquet" % day)
    import pyarrow as pa, pyarrow.compute as pc

    launch, creator_of = {}, {}
    for f in wd.files_for(files, "create", d0, d1):
        tb = wd.read(f, ["block_time", "mint", "creator", "is_mayhem_mode"], tmp)
        bt = wd.secs(tb.column("block_time"))
        mi, cr, mm = tb.column("mint").to_pylist(), tb.column("creator").to_pylist(), tb.column("is_mayhem_mode").to_pylist()
        for k in range(len(mi)):
            if d0 <= bt[k] < d1 and not mm[k]:
                launch[mi[k]] = int(bt[k]); creator_of[mi[k]] = cr[k]
    mints = pa.array(sorted(launch))
    parts = []
    cols = ["block_time", "slot", "tx_index", "mint", "trade_user", "ix_name", "sol_amount", "token_amount",
            "virtual_sol_reserves", "virtual_token_reserves", "real_sol_reserves"]
    for f in wd.files_for(files, "trade", d0, data_end - 13 * H):
        tb = wd.read(f, cols, tmp)
        parts.append(tb.filter(pc.is_in(tb.column("mint"), value_set=mints)))
    tb = pa.concat_tables(parts, promote_options="permissive")
    del parts
    okrow = None
    for c in [c for c in cols if c not in ("slot", "tx_index")]:
        v = pc.is_valid(tb.column(c))
        okrow = v if okrow is None else pc.and_(okrow, v)
    tb = tb.filter(okrow)
    for c in ("slot", "tx_index"):
        tb = tb.set_column(tb.schema.get_field_index(c), c, pc.fill_null(pc.cast(tb.column(c), pa.int64()), 0))
    t_all = wd.secs(tb.column("block_time"))
    keep = t_all < data_end
    tb = tb.filter(pa.array(keep)); t_all = t_all[keep]
    mc_ = pc.dictionary_encode(tb.column("mint")).combine_chunks()
    uc_ = pc.dictionary_encode(tb.column("trade_user")).combine_chunks()
    m_idx = mc_.indices.to_numpy(zero_copy_only=False).astype(np.int64); m_names = mc_.dictionary.to_pylist()
    u_idx = uc_.indices.to_numpy(zero_copy_only=False).astype(np.int64); u_names = uc_.dictionary.to_pylist()
    u_code = {x: k for k, x in enumerate(u_names)}
    is_buy = (tb.column("ix_name").to_numpy(zero_copy_only=False) != "sell")
    num = lambda c, ty: tb.column(c).to_numpy(zero_copy_only=False).astype(ty)
    slot, txi, sol, tok = num("slot", "int64"), num("tx_index", "int64"), num("sol_amount", "int64"), num("token_amount", "float64")
    vs, vt, rs = num("virtual_sol_reserves", "float64"), num("virtual_token_reserves", "float64"), num("real_sol_reserves", "float64")
    del tb
    price = (vs / 1e9) / np.maximum(vt / 1e6, 1e-9)
    order = np.lexsort((txi, slot, t_all, m_idx))
    m_idx, t_all, u_idx, is_buy, sol, tok, price, rs, vs = (a[order] for a in (m_idx, t_all, u_idx, is_buy, sol, tok, price, rs, vs))
    del slot, txi, vt, order
    cr = np.array([u_code.get(creator_of[x], -1) for x in m_names], np.int64)
    log("trades", len(t_all), "coins", len(m_names))

    # the events and the wallet's own numbers: round 1's code; the copies are redone below for every delay
    ev = wd.events(m_idx, t_all, u_idx, is_buy, sol, tok, price, rs, cr, data_end)
    ev_i = ev["i"]
    N = len(m_idx); n_coins = int(m_idx.max()) + 1
    bounds = np.flatnonzero(np.diff(m_idx)) + 1
    starts = np.concatenate([[0], bounds]); ends_seg = np.concatenate([bounds, [N]])
    ends = np.zeros(n_coins, np.int64); ends[m_idx[starts]] = ends_seg
    gi = np.full(n_coins, -1, np.int64)
    ig = np.flatnonzero(rs >= GRAD)
    if len(ig):
        gm, gf = np.unique(m_idx[ig], return_index=True); gi[gm] = ig[gf]
    ev_sell = ev["sell_i"]

    sp = wd.solusd(d0 - H, data_end + H)
    hours = np.array(sorted(sp)); closes = np.array([sp[h] for h in hours])
    usd = closes[np.clip(np.searchsorted(hours, t_all[ev_i], side="right") - 1, 0, len(hours) - 1)].astype(np.float32)
    L = np.array([launch[x] for x in m_names], np.int64)
    save = dict(m=ev["m"], t=ev["t"], buy_sol=ev["buy_sol"], hold=ev["hold"], own_pnl=ev["own_pnl"], usd=usd,
                mints=np.array(m_names, dtype="S44"))
    tps = np.array([x[0] for x in TPSL]); sls = np.array([x[1] for x in TPSL])
    for d in DELAYS:
        r, how, ent = kernel2(ev_i, ev_sell, m_idx, t_all, price, ends, gi, data_end, d, tps, sls)
        a = np.maximum(ent, 0)
        save["r%d" % d] = r; save["how%d" % d] = how
        save["vs%d" % d] = np.where(ent >= 0, vs[a] / 1e9, np.nan).astype(np.float32)
        save["mc%d" % d] = np.where(ent >= 0, price[a] * 1e9 * usd, np.nan).astype(np.float32)
        save["age%d" % d] = (np.where(ent >= 0, t_all[a], ev["t"]) - L[ev["m"]]).astype(np.int32)
        if d == 30:
            ok = ent >= 0
            assert np.allclose(r[ok, 0], ev["r"][ok], rtol=1e-5) and np.array_equal(how[ok, 0], ev["how"][ok])
    uu, inv = np.unique(ev["u"], return_inverse=True)
    addr = [u_names[k] for k in uu]
    hsh = np.array([int.from_bytes(hashlib.blake2b(x.encode(), digest_size=8).digest(), "little") for x in addr], np.uint64)
    np.savez_compressed(os.path.join(out, "e2_%s.npz" % day), w=hsh[inv], **save)
    np.savez_compressed(os.path.join(out, "wl_%s.npz" % day), h=hsh, a=np.array(addr, dtype="S44"))
    log("done", day, "events", len(ev_i), "file MB", round(os.path.getsize(os.path.join(out, "e2_%s.npz" % day)) / 1e6, 1))


if __name__ == "__main__":
    main()
