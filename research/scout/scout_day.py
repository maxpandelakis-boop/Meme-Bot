"""The scout study, one launch day (research/scout/PREREG-SCOUT-2026-11-11.md). Fake money only: past data, nothing is bought.

usage: python3 research/scout/scout_day.py <files.json> <YYYY-MM-DD> <out dir>
Downloads the Pumpfun_v2 create and trade files that cover the coins launched on that UTC day (Slinky21/Pumpfun_v2_dataset,
CC BY 4.0), finds each rule's first signal per coin, replays the video's sell rules on the coin's later curve trades, and does the
same for one random matched control coin per buy. Writes <out>/trades_<day>.json.
"""
import calendar, json, os, sys, time, urllib.parse, urllib.request
import numpy as np

SRC = "Slinky21/Pumpfun_v2_dataset"
UA = {"User-Agent": "memebot-research"}
MIN, H, DAY = 60_000, 3_600_000, 86_400_000
BIG = 50_000_000                       # 0.05 SOL in lamports: a "real" buyer
BAND = (10_000.0, 60_000.0)            # market cap band, USD
TICKET, SLIP, DELAY = 20.0, 0.01, 30_000
WINDOW = 24 * H
FEES = (0.02, 0.50, 0.81, 0.05)  # 0.02 = FOMO tiers (judged);             # FOMO 0.5% min 0.50; memebot 0.5% min 0.81; Jupiter-like: no platform fee, 0.05 $ network
SCALP = (1.20, 0.90, 10 * MIN)          # quick in and out: +20% take profit, -10% stop, 10 minutes at most
SEED = 20261111


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(url, tries=6, raw=False):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
                b = r.read()
                return b if raw else json.loads(b.decode())
        except Exception as e:
            log("get failed", url[:110], type(e).__name__, str(e)[:100])
            time.sleep(10 * (i + 1))
    raise SystemExit("could not get " + url)


def stamp_ms(path):
    s = path.split("_")[-1].split(".")[0]          # 20260924T032055
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
    return v // {"s": 1 / 1000, "ms": 1, "us": 1000, "ns": 1_000_000}[arr.type.unit] if arr.type.unit != "s" else v * 1000


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

def fee(x, fmin):
    """fmin 0.02: FOMO's real Solana fee per buy and per sell, network included (under 5 $: 0.10 $; 5 to 47.50 $: 2%;
    47.50 to 190 $: 0.95 $; from 190 $: 0.5%; it matches Maxim's screenshots 0.50 $ on 25.22 $ and 0.95 $ on 65.71 $).
    fmin 0.05: a Jupiter-like swap, no platform fee, 0.05 $ network. Otherwise the old model 0.5%, minimum fmin."""
    if fmin == 0.02:
        return 0.10 if x < 5 else 0.02 * x if x < 47.5 else 0.95 if x < 190 else 0.005 * x
    return fmin if fmin < 0.1 else max(0.005 * x, fmin)


def replay_scalp(t, p, i0, end_ms, fmin):
    """Quick in and out: sell all at +20% or -10% (at the trade that crosses), or after 10 minutes, or at the last trade."""
    entry = p[i0] * (1 + SLIP)
    tok = TICKET / entry
    end_ms = min(end_ms, t[i0] + SCALP[2])
    j_end = max(int(np.searchsorted(t, end_ms, side="left")) - 1, i0)
    how, j_out = "time", j_end
    for j in range(i0 + 1, j_end + 1):
        q = p[j] * (1 - SLIP)
        if q >= SCALP[0] * entry:
            how, j_out = "tp", j; break
        if q <= SCALP[1] * entry:
            how, j_out = "sl", j; break
    v = tok * p[j_out] * (1 - SLIP)
    return v - TICKET - fee(TICKET, fmin) - fee(v, fmin), how


def replay(t, p, i0, end_ms, fmin):
    """The video's sell rules from trade index i0 (entry at p[i0] + slippage) to the last trade before end_ms.
    Returns (pnl, hold_pnl, how, exit_ms, total_loss, gross_parts)."""
    entry = p[i0] * (1 + SLIP)
    tok = TICKET / entry
    cash, fees, n_sells = 0.0, fee(TICKET, fmin), 0
    half_done, high, how, exit_ms = False, 0.0, "end", None
    j_end = int(np.searchsorted(t, end_ms, side="left")) - 1
    j_end = max(j_end, i0)
    for j in range(i0 + 1, j_end + 1):
        q = p[j] * (1 - SLIP)
        if not half_done:
            if q <= entry * 0.92:
                v = tok * q; cash += v; fees += fee(v, fmin); tok = 0.0; how, exit_ms = "stop", t[j]; break
            if q >= 2 * entry:
                sell = TICKET / q; v = sell * q; cash += v; fees += fee(v, fmin); tok -= sell
                half_done, high = True, q
                continue
        else:
            high = max(high, q)
            if q <= 0.9 * high:
                v = tok * q; cash += v; fees += fee(v, fmin); tok = 0.0; how, exit_ms = "trail", t[j]; break
    if tok > 0:
        q = p[j_end] * (1 - SLIP)
        v = tok * q; cash += v; fees += fee(v, fmin); exit_ms = t[j_end]
        if how == "end" and half_done:
            how = "2x+end"
    last = p[j_end] * (1 - SLIP)
    hold = TICKET / entry * last - TICKET - fee(TICKET, fmin) - fee(TICKET / entry * last, fmin)
    return cash - TICKET - fees, hold, how, int(exit_ms), last / entry <= 0.02


def hold_g(t, p, rs, i0, end_ms, fmin):
    """Hold until the curve completes (sold at 10% under the last curve price: the move to PumpSwap) or until end_ms
    (sold at the last curve trade before it)."""
    entry = p[i0] * (1 + SLIP)
    j_end = max(int(np.searchsorted(t, end_ms, side="left")) - 1, i0)
    g = np.flatnonzero(rs[i0:j_end + 1] >= 80e9)
    if len(g):
        last, how = p[i0 + g[0]] * (1 - SLIP) * 0.90, "grad"
    else:
        last, how = p[j_end] * (1 - SLIP), "end"
    v = TICKET / entry * last
    return v - TICKET - fee(TICKET, fmin) - fee(v, fmin), how


# ------------------------------------------------------------------------------------------------------------ main

def main():
    files = [tuple(x) for x in json.load(open(sys.argv[1]))]
    day = sys.argv[2]
    out = sys.argv[3]
    os.makedirs(out, exist_ok=True)
    d0 = calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000
    d1 = d0 + DAY
    data_end = d1 + DAY + 4 * H                      # trades up to the D+2 03:xx file
    tmp = os.path.join(out, "tmp_%s.parquet" % day)
    import pyarrow as pa, pyarrow.compute as pc

    # launches of the day (mayhem coins left out: other curve; see the amendment)
    launch, supply, creator_of, sym = {}, {}, {}, {}
    for f in files_for(files, "create", d0, d1):
        tb = read(f, ["block_time", "mint", "creator", "symbol", "is_mayhem_mode", "token_total_supply"], tmp)
        bt = ms(tb.column("block_time"))
        mi, cr, sy = tb.column("mint").to_pylist(), tb.column("creator").to_pylist(), tb.column("symbol").to_pylist()
        mm, su = tb.column("is_mayhem_mode").to_pylist(), tb.column("token_total_supply").to_pylist()
        for k in range(len(mi)):
            if d0 <= bt[k] < d1 and not mm[k]:
                launch[mi[k]] = int(bt[k]); supply[mi[k]] = (su[k] or 10 ** 15) / 1e6
                creator_of[mi[k]] = cr[k]; sym[mi[k]] = sy[k]
        log("create", f.split("/")[-1], "launches so far", len(launch))
    mints = pa.array(sorted(launch))

    parts = []
    cols = ["block_time", "mint", "trade_user", "ix_name", "sol_amount", "token_amount", "virtual_sol_reserves",
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
    m_idx = mint_codes.indices.to_numpy(zero_copy_only=False)
    m_names = mint_codes.dictionary.to_pylist()
    u_idx = user_codes.indices.to_numpy(zero_copy_only=False)
    u_names = user_codes.dictionary.to_pylist()
    u_code = {u: k for k, u in enumerate(u_names)}
    is_buy = (tb.column("ix_name").to_numpy(zero_copy_only=False) != "sell")
    sol = tb.column("sol_amount").to_numpy(zero_copy_only=False).astype("int64")
    tokamt = tb.column("token_amount").to_numpy(zero_copy_only=False).astype("float64")
    vs = tb.column("virtual_sol_reserves").to_numpy(zero_copy_only=False).astype("float64")
    vt = tb.column("virtual_token_reserves").to_numpy(zero_copy_only=False).astype("float64")
    rs = tb.column("real_sol_reserves").to_numpy(zero_copy_only=False).astype("float64")
    del tb
    price = (vs / 1e9) / np.maximum(vt / 1e6, 1e-9)          # SOL per token, after the trade
    order = np.lexsort((t_all, m_idx))
    m_idx, t_all, u_idx, is_buy, sol, tokamt, price, rs = (a[order] for a in (m_idx, t_all, u_idx, is_buy, sol, tokamt, price, rs))
    bounds = np.flatnonzero(np.diff(m_idx)) + 1
    starts = np.concatenate([[0], bounds]); ends = np.concatenate([bounds, [len(m_idx)]])
    log("trades", len(t_all), "coins with trades", len(starts), "launches", len(launch))

    sp = solusd(d0 - H, data_end + H)
    hours = np.array(sorted(sp)); closes = np.array([sp[h] for h in hours])

    def usd(tt):
        k = np.clip(np.searchsorted(hours, tt, side="right") - 1, 0, len(hours) - 1)
        return closes[k]

    coins = []
    for s, e in zip(starts, ends):
        name = m_names[m_idx[s]]
        if name not in launch:
            continue
        c = dict(name=name, t=t_all[s:e], buy=is_buy[s:e], u=u_idx[s:e], sol=sol[s:e], tok=tokamt[s:e], p=price[s:e], rs=rs[s:e])
        c["mc"] = c["p"] * supply[name] * usd(c["t"])
        c["L"] = launch[name]
        c["cr"] = u_code.get(creator_of[name], -1)
        coins.append(c)
    log("coins", len(coins))

    # eligibility of controls: (minute, coin) where the coin is in the band, traded in the last 5 minutes, age >= 5 / 10 min
    elig = {}
    for ci, c in enumerate(coins):
        if len(c["t"]) < 5:
            continue
        m0 = (c["L"] // MIN + 6) * MIN
        m1 = min((c["t"][-1] // MIN + 6) * MIN, data_end)
        for m in range(m0, m1, MIN):
            k = int(np.searchsorted(c["t"], m, side="left")) - 1
            if k < 0 or c["t"][k] < m - 5 * MIN or not (BAND[0] <= c["mc"][k] <= BAND[1]):
                continue
            elig.setdefault(m, []).append((ci, m - c["L"]))
    log("control minutes", len(elig))
    rng = np.random.default_rng(SEED + int(d0 // DAY))

    def trade_at(c, m):
        """Entry at the first trade >= m + 30 s, replay; None when no trade follows."""
        i0 = int(np.searchsorted(c["t"], m + DELAY, side="left"))
        if i0 >= len(c["t"]):
            return None
        end = min(c["t"][i0] + WINDOW, data_end)
        r = {}
        for fmin in FEES:
            pnl, hold, how, xt, zero = replay(c["t"], c["p"], i0, end + 1, fmin)
            r["pnl%d" % round(fmin * 100)] = round(pnl, 4); r["hold%d" % round(fmin * 100)] = round(hold, 4)
            sc, show = replay_scalp(c["t"], c["p"], i0, end + 1, fmin)
            r["scal%d" % round(fmin * 100)] = round(sc, 4); r["show"] = show
            hg, ghow = hold_g(c["t"], c["p"], c["rs"], i0, end + 1, fmin)
            r["holdg%d" % round(fmin * 100)] = round(hg, 4); r["ghow"] = ghow
        r.update(how=how, exit=xt, zero=bool(zero), entry_t=int(c["t"][i0]), entry_mc=round(float(c["mc"][i0]), 1),
                 grad=bool(c["rs"][i0:].max() >= 80e9))
        return r

    def control(ci_self, m, min_age):
        cand = [ci for ci, age in elig.get(m, []) if ci != ci_self and age >= min_age]
        if not cand:
            return None
        ci = int(cand[rng.integers(len(cand))])
        r = trade_at(coins[ci], m)
        if r is None:
            return None
        return dict(mint=coins[ci]["name"], **{k: r[k] for k in r if k.startswith(("pnl", "scal", "hold")) or k in ("how", "zero", "show")})

    def rug_ok(c, k):
        """Creator sold nothing before index k, and the top 10 net holders hold under 35% of the supply."""
        u, b = c["u"][:k], c["buy"][:k]
        if c["cr"] >= 0 and np.any((u == c["cr"]) & ~b):
            return False
        net = {}
        tk = np.where(b, c["tok"][:k], -c["tok"][:k]) / 1e6
        for uu, x in zip(u.tolist(), tk.tolist()):
            net[uu] = net.get(uu, 0.0) + x
        top = sorted((v for v in net.values() if v > 0), reverse=True)[:10]
        return sum(top) / supply[c["name"]] < 0.35

    # the cells: name -> (rule, filter)
    V1 = [("V1", 5, 50), ("V1x3", 3, 50), ("V1x10", 10, 50), ("V1r25", 5, 25), ("V1r100", 5, 100)]
    rows = []
    for ci, c in enumerate(coins):
        t, L = c["t"], c["L"]
        bigbuy = c["buy"] & (c["sol"] >= BIG) & (c["u"] != c["cr"])
        if len(np.unique(c["u"][bigbuy])) < 20:
            continue
        done = set()
        m_last = min((t[-1] // MIN) * MIN, data_end)
        m = (L // MIN + 1) * MIN
        hi_so_far = 0.0
        while m <= m_last:
            age = m - L
            k = int(np.searchsorted(t, m, side="left"))           # trades before m: [0, k)
            if k == 0:
                m += MIN; continue
            mc = c["mc"][k - 1]; pnow = c["p"][k - 1]
            inband = BAND[0] <= mc <= BAND[1]
            k5 = int(np.searchsorted(t, m - 5 * MIN, side="left"))
            if k5 == k and not (5 * MIN <= age < 6 * MIN):
                m += MIN; continue
            real5 = len(np.unique(c["u"][k5:k][bigbuy[k5:k]]))
            hits = []
            if inband and age >= 10 * MIN:
                nb5 = int(c["buy"][k5:k].sum())
                base = max(c["buy"][:k5].sum() / max((m - 5 * MIN - L) / (5 * MIN), 1.0), 2.0)
                ratio = nb5 / base
                for name, x, rmin in V1:
                    if ratio >= x and real5 >= rmin:
                        hits.append((name, dict(ratio=round(ratio, 2), real=real5)))
            if inband and 5 * MIN <= age < 6 * MIN:
                realall = len(np.unique(c["u"][:k][bigbuy[:k]]))
                if realall >= 20:
                    hits.append(("V2", dict(real=realall)))
            if inband and age >= 10 * MIN and real5 >= 20:
                k5p = max(k5 - 1, 0)
                if c["t"][k5p] < m - 5 * MIN and pnow >= 1.3 * c["p"][k5p]:
                    hits.append(("M", dict(up5=round(pnow / c["p"][k5p], 3), real=real5)))
            if inband and age >= 30 * MIN and real5 >= 20:
                high = c["p"][:k].max()
                k30 = int(np.searchsorted(t, m - 30 * MIN, side="left"))
                if k30 < k:
                    seg = c["p"][k30:k]
                    jlow = int(np.argmin(seg)); low = seg[jlow]
                    if pnow <= 0.5 * high and t[k30 + jlow] <= m - 5 * MIN and pnow >= 1.2 * low:
                        hits.append(("V3", dict(down=round(pnow / high, 3), up=round(pnow / low, 3))))
            if hits:
                ok = None
                for name, feat in hits:
                    for cell in (name, name + "+R"):
                        if cell in done:
                            continue
                        if cell.endswith("+R"):
                            if ok is None:
                                ok = rug_ok(c, k)
                            if not ok:
                                continue
                        done.add(cell)
                        r = trade_at(c, m)
                        if r is None:
                            continue
                        ctl = control(ci, m, 5 * MIN if name == "V2" else 10 * MIN)
                        rows.append(dict(cell=cell, day=day, mint=c["name"], sym=sym.get(c["name"]), sig=int(m), age_min=round(age / MIN, 1),
                                         sig_mc=round(float(mc), 1), **feat, **r, ctl=ctl))
            if len(done) >= 16:
                break
            m += MIN
        if ci % 2000 == 0:
            log("coin", ci, "of", len(coins), "rows", len(rows))
    json.dump(dict(day=day, launches=len(launch), coins=len(coins), data_end=data_end, rows=rows),
              open(os.path.join(out, "trades_%s.json" % day), "w"))
    log("done", day, "rows", len(rows))


if __name__ == "__main__":
    main()
