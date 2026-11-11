"""The filter study, one launch day (research/filters/PREREG-FILTERS-2026-11-11.md). Fake money only: past data, nothing is bought.

usage: python3 research/filters/filters_day.py <files.json> <YYYY-MM-DD> <out dir>
Replays the live fresh-coin Scout's base signal on every pump.fun coin launched that UTC day (Slinky21/Pumpfun_v2_dataset,
CC BY 4.0), and writes one row per coin: the features known at the signal and what the trade made with the desk's exits.
"""
import calendar, json, os, sys, time, urllib.parse, urllib.request
import numpy as np

SRC = "Slinky21/Pumpfun_v2_dataset"
UA = {"User-Agent": "memebot-research"}
MIN, H, DAY = 60_000, 3_600_000, 86_400_000
BIG = 50_000_000                       # 0.05 SOL in lamports
BAND = (8_000.0, 250_000.0)            # the live Scout's market cap band, USD
BUYERS_MIN, BUYSELL_MIN, MAX_AGE_MIN = 15, 1.5, 60
TICKET, SLIP = 20.0, 0.01
DELAY = 30_000
WINDOW = 24 * H
P0 = 30.0 / 1_073_000_000.0            # the curve's start price, SOL per token
SCALP = (1.20, 0.90, 10 * MIN)


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


def stamp_ms(path):
    s = path.split("_")[-1].split(".")[0]
    return calendar.timegm(time.strptime(s, "%Y%m%dT%H%M%S")) * 1000


def files_for(files, table, lo, hi):
    """Files of a table whose stamp (end of the file's ~12 hours) lies in (lo, hi + 13 h]."""
    fs = sorted(p for p, _ in files if "/%s/" % table in p)
    return [p for p in fs if lo < stamp_ms(p) <= hi + 13 * H]


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
    t = pq.read_table(tmp, columns=cols)
    os.remove(tmp)
    return t


def ms(arr):
    import pyarrow as pa, pyarrow.compute as pc
    v = pc.cast(arr.combine_chunks() if hasattr(arr, "combine_chunks") else arr, pa.int64()).to_numpy(zero_copy_only=False)
    u = arr.type.unit
    return v * 1000 if u == "s" else v if u == "ms" else v // 1000 if u == "us" else v // 1_000_000


def solusd(t0, t1):
    out, s = {}, t0 - t0 % H
    while s < t1:
        e = min(t1, s + 290 * H)
        url = "https://api.exchange.coinbase.com/products/SOL-USD/candles?granularity=3600&start=%s&end=%s" % (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s / 1000)), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e / 1000)))
        for row in get(url):
            out[int(row[0]) * 1000] = float(row[4])
        s = e
        time.sleep(0.4)
    return out


# ------------------------------------------------------------------------------------------------------------ the trade

def fee(x, kind):
    """kind 'fomo': FOMO's Solana fee per buy and per sell, network included. kind 'jup': no platform fee, 0.05 $ network."""
    if kind == "jup":
        return 0.05
    return 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x


def replay(t, p, rs, j0, entry_t, kind):
    """Bought at the standing price p[j0] (+slippage) at entry_t; trades j0+1.. are the path. Returns the desk exit, the hold to
    the curve's completion, and the quick in-and-out."""
    entry = p[j0] * (1 + SLIP)
    tok0 = TICKET / entry
    end_ms = entry_t + WINDOW
    j_end = max(int(np.searchsorted(t, end_ms, side="right")) - 1, j0)
    # the desk
    tok, cash, fees = tok0, 0.0, fee(TICKET, kind)
    half, high, how = False, 0.0, "end"
    for j in range(j0 + 1, j_end + 1):
        q = p[j] * (1 - SLIP)
        if not half:
            if q <= entry * 0.92:
                v = tok * q; cash += v; fees += fee(v, kind); tok = 0.0; how = "stop"; break
            if q >= 2 * entry:
                sell = TICKET / q; v = sell * q; cash += v; fees += fee(v, kind); tok -= sell
                half, high = True, q
        else:
            high = max(high, q)
            if q <= 0.9 * high:
                v = tok * q; cash += v; fees += fee(v, kind); tok = 0.0; how = "trail"; break
    if tok > 0:
        v = tok * p[j_end] * (1 - SLIP); cash += v; fees += fee(v, kind)
        if half:
            how = "2x+end"
    desk = cash - TICKET - fees
    # hold to the curve's completion
    g = np.flatnonzero(rs[j0:j_end + 1] >= 80e9)
    if len(g):
        last, ghow = p[j0 + g[0]] * (1 - SLIP) * 0.90, "grad"
    else:
        last, ghow = p[j_end] * (1 - SLIP), "end"
    v = tok0 * last
    hold = v - TICKET - fee(TICKET, kind) - fee(v, kind)
    # quick in and out
    js_end = max(int(np.searchsorted(t, entry_t + SCALP[2], side="right")) - 1, j0)
    show, j_out = "time", js_end
    for j in range(j0 + 1, js_end + 1):
        q = p[j] * (1 - SLIP)
        if q >= SCALP[0] * entry:
            show, j_out = "tp", j; break
        if q <= SCALP[1] * entry:
            show, j_out = "sl", j; break
    v = tok0 * p[j_out] * (1 - SLIP)
    scal = v - TICKET - fee(TICKET, kind) - fee(v, kind)
    return desk, how, hold, ghow, scal, show


def main():
    files = [tuple(x) for x in json.load(open(sys.argv[1]))]
    day, out = sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    d0 = calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000
    d1 = d0 + DAY
    data_end = d1 + DAY + 4 * H
    tmp = os.path.join(out, "tmp_%s.parquet" % day)
    import pyarrow as pa, pyarrow.compute as pc

    # ---- creates of the day and of the 7 days before (creator history, ticker copies)
    c_t, c_slot, c_mint, c_cr, c_sym, c_mm, c_sup = [], [], [], [], [], [], []
    for f in files_for(files, "create", d0 - 7 * DAY, d1):
        tb = read(f, ["block_time", "slot", "mint", "creator", "symbol", "is_mayhem_mode", "token_total_supply"], tmp)
        c_t.append(ms(tb.column("block_time"))); c_slot.append(tb.column("slot").to_numpy(zero_copy_only=False))
        c_mint += tb.column("mint").to_pylist(); c_cr += tb.column("creator").to_pylist()
        c_sym += [(s or "").strip().upper() for s in tb.column("symbol").to_pylist()]
        c_mm += tb.column("is_mayhem_mode").to_pylist(); c_sup += tb.column("token_total_supply").to_pylist()
    c_t = np.concatenate(c_t); c_slot = np.concatenate(c_slot)
    log("creates", len(c_mint), "first", time.strftime("%m-%d %H:%M", time.gmtime(c_t.min() / 1000)))
    seen = set()
    by_creator, by_sym = {}, {}
    launch, supply, creator_of, sym, slot0 = {}, {}, {}, {}, {}
    for k in np.argsort(c_t, kind="stable").tolist():
        m = c_mint[k]
        if m in seen:
            continue
        seen.add(m)
        by_creator.setdefault(c_cr[k], []).append((int(c_t[k]), m))
        by_sym.setdefault(c_sym[k], []).append(int(c_t[k]))
        if d0 <= c_t[k] < d1 and not c_mm[k]:
            launch[m] = int(c_t[k]); supply[m] = (c_sup[k] or 10 ** 15) / 1e6
            creator_of[m] = c_cr[k]; sym[m] = c_sym[k]; slot0[m] = int(c_slot[k])
    grad_t = {}
    for f in files_for(files, "graduate", d0 - 7 * DAY, d1):
        tb = read(f, ["block_time", "mint"], tmp)
        for mm_, tt in zip(tb.column("mint").to_pylist(), ms(tb.column("block_time")).tolist()):
            grad_t.setdefault(mm_, tt)
    log("launches of the day", len(launch), "graduations known", len(grad_t))
    mints = pa.array(sorted(launch))

    # ---- trades of the day's coins
    parts = []
    cols = ["block_time", "slot", "tx_index", "mint", "trade_user", "ix_name", "sol_amount", "token_amount", "virtual_sol_reserves",
            "virtual_token_reserves", "real_sol_reserves"]
    for f in files_for(files, "trade", d0, data_end - 13 * H):
        tb = read(f, cols, tmp)
        tb = tb.filter(pc.is_in(tb.column("mint"), value_set=mints))
        parts.append(tb)
        log("trade", f.split("/")[-1], "rows kept", tb.num_rows)
    tb = pa.concat_tables(parts)
    del parts
    t_all = ms(tb.column("block_time"))
    keep = t_all < data_end
    tb = tb.filter(pa.array(keep)); t_all = t_all[keep]
    mint_codes = pc.dictionary_encode(tb.column("mint")).combine_chunks()
    user_codes = pc.dictionary_encode(tb.column("trade_user")).combine_chunks()
    m_idx = mint_codes.indices.to_numpy(zero_copy_only=False).astype("int64")
    m_names = mint_codes.dictionary.to_pylist()
    u_idx = user_codes.indices.to_numpy(zero_copy_only=False).astype("int64")
    u_code = {u: k for k, u in enumerate(user_codes.dictionary.to_pylist())}
    is_buy = (tb.column("ix_name").to_numpy(zero_copy_only=False) != "sell")
    slot = tb.column("slot").to_numpy(zero_copy_only=False).astype("int64")
    txi = tb.column("tx_index").to_numpy(zero_copy_only=False).astype("int64")
    sol = tb.column("sol_amount").to_numpy(zero_copy_only=False).astype("float64") / 1e9
    tokamt = tb.column("token_amount").to_numpy(zero_copy_only=False).astype("float64") / 1e6
    vs = tb.column("virtual_sol_reserves").to_numpy(zero_copy_only=False).astype("float64")
    vt = tb.column("virtual_token_reserves").to_numpy(zero_copy_only=False).astype("float64")
    rs = tb.column("real_sol_reserves").to_numpy(zero_copy_only=False).astype("float64")
    del tb
    price = (vs / 1e9) / np.maximum(vt / 1e6, 1e-9)
    order = np.lexsort((txi, slot, t_all, m_idx))
    del txi
    m_idx, t_all, u_idx, is_buy, slot, sol, tokamt, price, rs = (a[order] for a in (m_idx, t_all, u_idx, is_buy, slot, sol, tokamt, price, rs))
    # how many coins of the day a wallet had entered before it entered this one (serial wallets)
    key = u_idx * (len(m_names) + 1) + m_idx
    ot = np.argsort(t_all, kind="stable")
    uniq, first = np.unique(key[ot], return_index=True)          # first = position in time order
    pw = uniq // (len(m_names) + 1)
    o2 = np.lexsort((first, pw))
    rank = np.empty(len(uniq), dtype="int64")
    grp_start = np.concatenate([[0], np.flatnonzero(np.diff(pw[o2])) + 1])
    start_of = np.repeat(grp_start, np.diff(np.concatenate([grp_start, [len(uniq)]])))
    rank[o2] = np.arange(len(uniq)) - start_of
    w_exp = rank[np.searchsorted(uniq, key)]
    del key, ot, uniq, first, pw, o2, rank
    bounds = np.flatnonzero(np.diff(m_idx)) + 1
    starts = np.concatenate([[0], bounds]); ends = np.concatenate([bounds, [len(m_idx)]])
    log("trades", len(t_all), "coins with trades", len(starts))

    sp = solusd(d0 - H, data_end + H)
    hours = np.array(sorted(sp)); closes = np.array([sp[h] for h in hours])

    def usd(tt):
        return closes[np.clip(np.searchsorted(hours, tt, side="right") - 1, 0, len(hours) - 1)]

    rows, n_coins = [], 0
    for s, e in zip(starts, ends):
        name = m_names[m_idx[s]]
        if name not in launch or e - s < BUYERS_MIN:
            continue
        n_coins += 1
        L = launch[name]; sup = supply[name]
        t, b, u, so, tk, p, r_, sl, wx = t_all[s:e], is_buy[s:e], u_idx[s:e], sol[s:e], tokamt[s:e], price[s:e], rs[s:e], slot[s:e], w_exp[s:e]
        cr = u_code.get(creator_of[name], -1)
        m = (L // MIN + 1) * MIN
        if m - L < 30_000:
            m += MIN                                   # at least 30 s old at the first check
        m_last = min(L + MAX_AGE_MIN * MIN, (t[-1] // MIN + 1) * MIN, data_end - H)
        hit = None
        while m <= m_last:
            k = int(np.searchsorted(t, m, side="left"))
            k5 = int(np.searchsorted(t, m - 5 * MIN, side="left"))
            if k - k5 >= BUYERS_MIN:
                bb = b[k5:k]
                nb = int(bb.sum()); ns = (k - k5) - nb
                if nb >= BUYERS_MIN and nb >= BUYSELL_MIN * ns:
                    buyers5 = len(np.unique(u[k5:k][bb]))
                    pnow = p[k - 1]; p5 = p[k5 - 1] if k5 > 0 else P0
                    mc = pnow * sup * float(usd(m))
                    if buyers5 >= BUYERS_MIN and pnow > p5 and BAND[0] <= mc <= BAND[1]:
                        hit = (m, k, k5, nb, ns, buyers5, pnow, p5, mc)
                        break
            m += MIN
        if hit is None:
            continue
        m, k, k5, nb, ns, buyers5, pnow, p5, mc = hit
        U, B, SO, TK = u[:k], b[:k], so[:k], tk[:k]
        age = m - L
        notcr = U != cr
        # creator
        hist = [x for x in by_creator.get(creator_of[name], []) if x[0] < L and x[1] != name]
        cr_7d = len(hist); cr_24h = sum(1 for x in hist if x[0] >= L - DAY)
        cr_grad = sum(1 for x in hist if grad_t.get(x[1], 1 << 62) < L)
        dev_b = B & ~notcr; dev_s = ~B & ~notcr
        dev_buy_tok = float(TK[dev_b].sum()); dev_sell_tok = float(TK[dev_s].sum())
        # holders
        net = {}
        for uu, x in zip(U.tolist(), np.where(B, TK, -TK).tolist()):
            net[uu] = net.get(uu, 0.0) + x
        hold = sorted((v for v in net.values() if v > 0), reverse=True)
        # launch
        early = notcr & B & (t[:k] <= L + 10_000)
        s0 = notcr & B & (sl[:k] <= slot0[name])
        s4 = notcr & B & (sl[:k] <= slot0[name] + 4)
        bs_slots = sl[:k][B]; bs_users = U[B]
        if len(bs_slots):
            pair = np.unique(np.stack([bs_slots, bs_users]), axis=1)
            _, cnt = np.unique(pair[0], return_counts=True)
            max_slot_wallets = int(cnt.max())
        else:
            max_slot_wallets = 0
        # buyers
        bu5 = u[k5:k][b[k5:k]]; bs5 = so[k5:k][b[k5:k]]
        agg = {}
        for uu, x in zip(bu5.tolist(), bs5.tolist()):
            agg[uu] = agg.get(uu, 0.0) + x
        top3 = sum(sorted(agg.values(), reverse=True)[:3]) / max(sum(agg.values()), 1e-12)
        buyers_all = set(U[B].tolist()); sellers_all = set(U[~B].tolist())
        wx5 = wx[k5:k][b[k5:k]]
        _, fi = np.unique(bu5, return_index=True)
        wx5u = wx5[fi]
        k60 = int(np.searchsorted(t, L + MIN, side="left"))
        rs_now = float(r_[k - 1]) / 1e9
        feat = dict(
            age_min=round(age / MIN, 2), mc=round(mc, 1), rs_sol=round(rs_now, 3), sol_per_min=round(rs_now / (age / MIN), 4),
            first60_share=round((float(r_[k60 - 1]) / 1e9 if k60 > 0 else 0.0) / max(rs_now, 1e-9), 4),
            chg5=round(pnow / p5 - 1, 4), dd_high=round(pnow / float(p[:k].max()), 4),
            buys5=nb, sells5=ns, buyers5=buyers5, sellers5=len(np.unique(u[k5:k][~b[k5:k]])),
            buys_per_buyer5=round(nb / buyers5, 3), real5=len(np.unique(u[k5:k][b[k5:k] & (so[k5:k] >= 0.05) & (u[k5:k] != cr)])),
            vol5_sol=round(float(so[k5:k].sum()), 3), netflow5_sol=round(float(bs5.sum() - so[k5:k][~b[k5:k]].sum()), 3),
            med_buy5=round(float(np.median(bs5)), 4), top3_share5=round(top3, 4),
            n_trades=k, buyers_all=len(buyers_all), sellers_all=len(sellers_all),
            flip_share=round(len(buyers_all & sellers_all) / max(len(buyers_all), 1), 4),
            top1_pct=round(hold[0] / sup * 100, 3) if hold else 0.0, top10_pct=round(sum(hold[:10]) / sup * 100, 3),
            dev_pct=round(max(net.get(cr, 0.0), 0.0) / sup * 100, 3), dev_buy_sol=round(float(SO[dev_b].sum()), 4),
            dev_bought=bool(dev_buy_tok > 0), dev_sold_frac=round(min(dev_sell_tok / dev_buy_tok, 1.0), 4) if dev_buy_tok > 0 else 0.0,
            dev_sold_any=bool(dev_sell_tok > 0),
            early10_buyers=len(np.unique(U[early])), slot0_buys=int(s0.sum()), slot0_pct=round(float(TK[s0].sum()) / sup * 100, 3),
            snipe4_buys=int(s4.sum()), snipe4_pct=round(float(TK[s4].sum()) / sup * 100, 3), max_slot_wallets=max_slot_wallets,
            cr_24h=cr_24h, cr_7d=cr_7d, cr_grad=cr_grad,
            sym_copies=sum(1 for x in by_sym.get(sym[name], []) if L - DAY <= x < L),
            wexp_med=float(np.median(wx5u)), wexp_new_share=round(float((wx5u == 0).mean()), 4), wexp_5plus_share=round(float((wx5u >= 5).mean()), 4),
            hour=int((m // H) % 24))
        # the trade: bought DELAY after the signal at the standing price
        entry_t = m + DELAY
        j0 = int(np.searchsorted(t, entry_t, side="left")) - 1
        o = {}
        for kind in ("fomo", "jup"):
            desk, how, hd, ghow, scal, show = replay(t, p, r_, j0, entry_t, kind)
            o.update({"desk_" + kind: round(desk, 4), "hold_" + kind: round(hd, 4), "scal_" + kind: round(scal, 4)})
        entry = p[j0] * (1 + SLIP)
        j10 = int(np.searchsorted(t, entry_t + 10 * MIN, side="right")) - 1
        j30 = int(np.searchsorted(t, entry_t + 30 * MIN, side="right")) - 1
        j24 = int(np.searchsorted(t, entry_t + WINDOW, side="right")) - 1
        o.update(how=how, ghow=ghow, show=show, x10=round(float(p[max(j10, j0)] / entry), 4), x30=round(float(p[max(j30, j0)] / entry), 4),
                 xmax=round(float(p[j0:max(j24, j0) + 1].max() / entry), 4), xend=round(float(p[max(j24, j0)] / entry), 4),
                 grad=bool(r_[j0:].max() >= 80e9), later_trades=int(e - s - (j0 + 1)), slip_wait=round(float(p[j0] / pnow), 4))
        rows.append(dict(day=day, mint=name, sym=sym[name], sig=int(m), **feat, **o))
    json.dump(dict(day=day, launches=len(launch), coins=n_coins, data_end=data_end, rows=rows),
              open(os.path.join(out, "rows_%s.json" % day), "w"))
    log("done", day, "coins", n_coins, "rows", len(rows))


if __name__ == "__main__":
    main()
