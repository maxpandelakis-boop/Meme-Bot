"""WP0 API probe for the launch radar (SPEC 13.10, section 5 WP0). Fake money only: nothing is bought, nothing is signed, and
every request is a public read without a key.

Run by .github/workflows/probe-radar.yml (Run workflow, by hand only):
    python3 research/probe_radar.py --res res --repo owner/name
res = a depth-1 clone of the results branch (the paper positions for check 1).

Output rules: only status codes, field names, counts, timings and rate-limit headers are printed. No response body longer than
300 characters (error bodies are cut to 160, with coin and wallet addresses masked), no credential, no coin or wallet address.
The last line is `PROBE_JSON {...}` with every number, for research/probe-radar.md.

Checks (the WP0 table):
  1  GeckoTerminal minute candles for 3 paper windows (about 24 h, 48 h, 75 h old) and the oldest stored position, plus aggregate 15
  2  discovery coverage: 4 cycles 150 s apart; per source the candidates, the pools under 10 minutes and the pool age at first sight
  3  pump.fun single-coin routes (coins/{mint}, coins-v3/{mint}, coins/metadata/{mint}) and the list-row fields; coins?creator=;
     user-created-coins (v1 path and coins-v2 on both hosts)
  4  swap-api trades (order, slotIndexId, cursor, rows per page) and candles (v2 and v1)
  5  coins/top-holders on frontend-api-v3 and advanced-api-v2 for up to 4 coins (fresh, curve, older); POST wallet-overview
  6  RugCheck report fields (creator, creatorTokens, insiderNetworks, graphInsidersDetected, topHolders) on pools 2-9 min old,
     the same coin again 5 minutes later, and pools 30-240 min old
  7  Solana public RPC: signature depth for a dev wallet and a fresh mint; one getTransaction; a paced run, the burst size before
     a 429 and how long the block lasts
  8  api.github.com contents API on the existing branch "live", unauthenticated: x-ratelimit-used around a 304 (read-only)
  9  skipped (raw freshness needs a write); a read-only comparison of raw.githubusercontent.com with the contents API is logged
  10 Supabase: whether the secrets exist (yes/no only)
"""
import argparse, datetime, glob, json, os, re, statistics, sys, time, traceback, urllib.error, urllib.parse, urllib.request
from collections import Counter

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 memebot-paper/1.0"
PF = "https://frontend-api-v3.pump.fun"
SWAP = "https://swap-api.pump.fun"
ADV = "https://advanced-api-v2.pump.fun"
DS = "https://api.dexscreener.com"
GT = "https://api.geckoterminal.com/api/v2"
JUP = "https://lite-api.jup.ag/tokens/v2"
LL = "https://launch-mint-v1.raydium.io"
RC = "https://api.rugcheck.xyz/v1"
RPC = "https://api.mainnet-beta.solana.com"
GH = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
PF_WEB = {"Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
GAP = {"api.geckoterminal.com": 10.0, "frontend-api-v3.pump.fun": 0.7, "api.mainnet-beta.solana.com": 0.3, "advanced-api-v2.pump.fun": 1.0,
       "swap-api.pump.fun": 0.2, "api.rugcheck.xyz": 2.0, "api.dexscreener.com": 0.25, "lite-api.jup.ag": 0.2, "launch-mint-v1.raydium.io": 0.2}
CURVE_DEX = re.compile(r"pumpfun|dbc|launchlab|boop|moonit|curve", re.I)      # memebot.CURVE_DEX: a bonding curve is not a DEX pool
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
B58_ANY = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,90}")
MIN = 60_000
FRESH_MIN = 10
CADENCE = 150
CYCLES = 4
R = {"v": 1}


def say(*a):
    print(" ".join(str(x) for x in a), flush=True)


def now_ms():
    return int(time.time() * 1000)


def addr(v):
    v = str(v or "").strip()
    return v if B58.match(v) else None


def num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def ts_ms(v):
    """A timestamp as epoch ms: numbers in s or ms, ISO strings."""
    x = num(v)
    if x is not None:
        return int(x * 1000) if x < 1e11 else int(x)
    if isinstance(v, str) and v:
        try:
            return int(datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def keys(o, n=80):
    return sorted(str(k) for k in o)[:n] if isinstance(o, dict) else type(o).__name__


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def mask(s, n=160):
    s = B58_ANY.sub("<addr>", str(s))
    return re.sub(r"\s+", " ", s)[:n]


class Resp:
    def __init__(self, code, h, js, raw, secs):
        self.code, self.h, self.js, self.raw, self.secs = code, h, js, raw, secs

    def rl(self):
        return {k: v for k, v in self.h.items() if "ratelimit" in k or "rate-limit" in k or k == "retry-after"}

    def brief(self):
        out = {"code": self.code, "ms": int(self.secs * 1000)}
        if self.rl():
            out["rl"] = self.rl()
        if self.code not in (200, 201, 204, 304) and self.raw:
            out["body"] = mask(self.raw[:400].decode("utf-8", "replace"))
        return out


class Http:
    """One request per call, no retries (the probe counts 429s), a minimum gap per host, stats per host."""

    def __init__(self):
        self.last, self.stats = {}, {}

    def req(self, url, method="GET", body=None, headers=None, timeout=20, gap=None):
        host = urllib.parse.urlsplit(url).hostname
        g = GAP.get(host, 0.0) if gap is None else gap
        wait = self.last.get(host, 0) + g - time.time()
        if wait > 0:
            time.sleep(wait)
        hdr = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
        hdr.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdr["Content-Type"] = "application/json"
        t0, code, hd, raw = time.time(), None, {}, b""
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr, method=method), timeout=timeout) as r:
                code, hd, raw = r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            code, hd = e.code, {k.lower(): v for k, v in (e.headers or {}).items()}
            try:
                raw = e.read()
            except Exception:
                raw = b""
        except Exception as e:  # timeout, refused, reset
            code = "ERR:" + type(e).__name__
        secs = time.time() - t0
        self.last[host] = time.time()
        js = None
        if raw:
            try:
                js = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                js = None
        st = self.stats.setdefault(host, {"n": 0, "codes": Counter(), "secs": 0.0})
        st["n"] += 1
        st["codes"][str(code)] += 1
        st["secs"] += secs
        return Resp(code, hd, js, raw, secs)

    def rpc(self, method, params, gap=None):
        return self.req(RPC, "POST", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, gap=gap)


def guarded(name):
    """Run one check; an exception is logged as its type and line only (never its text, which could hold an address)."""
    def wrap(f):
        def run(*a, **k):
            t0 = time.time()
            try:
                return f(*a, **k)
            except Exception as e:
                tb = traceback.extract_tb(e.__traceback__)
                where = tb[-1].lineno if tb else "?"
                say("[%s] SCRIPT ERROR %s at line %s" % (name, type(e).__name__, where))
                R.setdefault("errors", []).append({"check": name, "error": type(e).__name__, "line": where})
            finally:
                say("[%s] done in %.1fs" % (name, time.time() - t0))
        return run
    return wrap


# ---------------------------------------------------------------- check 10, check 8 (and the read-only part of 9)
@guarded("c10")
def check10():
    out = {}
    for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY"):
        out[k] = "yes" if os.environ.get("HAS_" + k, "").strip().lower() == "true" else "no"
    R["c10"] = out
    say("[c10] secrets set:", json.dumps(out))


def gh_used(r):
    return {k.replace("x-ratelimit-", ""): r.h.get(k) for k in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-used", "x-ratelimit-resource")}


@guarded("c8")
def check8(h, repo, tag="c8"):
    """Unauthenticated, like the page: plain GET, conditional GET with the ETag (twice), plain GET again."""
    url = GH + "/repos/%s/contents/live.json?ref=live" % repo
    acc = {"Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"}
    seq, etag, doc_t = [], None, None
    for step in ("plain", "if-none-match", "if-none-match", "plain"):
        hdr = dict(acc)
        if step == "if-none-match" and etag:
            hdr["If-None-Match"] = etag
        r = h.req(url, headers=hdr)
        if r.code == 200:
            etag = r.h.get("etag") or etag
            try:
                doc_t = num(json.loads(r.raw.decode("utf-8")).get("t"))
            except Exception:
                pass
        row = {"step": step, "code": r.code, "ms": int(r.secs * 1000), "etag": bool(r.h.get("etag")), "bytes": len(r.raw),
               "cacheControl": r.h.get("cache-control"), **gh_used(r)}
        seq.append(row)
        say("[%s] contents %s -> %s used=%s remaining=%s etag=%s %dms" % (tag, step, r.code, row["used"], row["remaining"], row["etag"], row["ms"]))
    used = [num(x["used"]) for x in seq]
    delta304 = None
    if all(u is not None for u in used[:3]):
        delta304 = used[2] - used[0]        # two conditional calls after the first plain one
    # the same with the refs endpoint (speed-first's idea: refs + raw by SHA)
    ref_url = GH + "/repos/%s/git/matching-refs/heads/live" % repo
    r1 = h.req(ref_url, headers={"Accept": "application/vnd.github+json"})
    r2 = h.req(ref_url, headers={"Accept": "application/vnd.github+json", "If-None-Match": r1.h.get("etag") or ""})
    refs = {"plain": r1.code, "cond": r2.code, "usedPlain": r1.h.get("x-ratelimit-used"), "usedCond": r2.h.get("x-ratelimit-used")}
    say("[%s] matching-refs plain %s used=%s, conditional %s used=%s" % (tag, r1.code, refs["usedPlain"], r2.code, refs["usedCond"]))
    R[tag] = {"seq": seq, "usedDeltaOverTwo304": delta304, "refs": refs, "docT": doc_t}
    return doc_t


@guarded("c9ro")
def check9_readonly(h, repo, doc_t_api, tag="c9ro"):
    """Check 9 itself is skipped (it needs a push). Read-only: raw.githubusercontent.com for the live doc with and without ?m=,
    its cache headers, and how far its doc time lags the contents API's doc time (the live branch moves only during a scan)."""
    out = {"skipped": "raw freshness after a push needs a write; not run"}
    for q in ("", "?m=%d" % (now_ms() // MIN)):
        r = h.req(RAW + "/%s/live/live.json%s" % (repo, q))
        t = None
        try:
            t = num(json.loads(r.raw.decode("utf-8")).get("t"))
        except Exception:
            pass
        row = {"code": r.code, "ms": int(r.secs * 1000), "cacheControl": r.h.get("cache-control"), "age": r.h.get("age"),
               "xCache": r.h.get("x-cache"), "lagS": round((doc_t_api - t) / 1000, 1) if (doc_t_api and t) else None}
        out["query" if q else "plain"] = row
        say("[%s] raw %s -> %s cache-control=%s age=%s x-cache=%s lag-vs-contents=%ss" % (tag, "with ?m=" if q else "plain", r.code, row["cacheControl"], row["age"], row["xCache"], row["lagS"]))
    R[tag] = out


# ---------------------------------------------------------------- check 1
def pick_windows(res, now):
    st = {}
    try:
        with open(os.path.join(res, "db", "memebot", "state.json"), encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        pass
    since = num(st.get("paperSince"))
    pos = []
    for fn in glob.glob(os.path.join(res, "db", "memepos", "*.json")):
        try:
            with open(fn, encoding="utf-8") as f:
                p = json.load(f)
        except Exception:
            continue
        e = num(p.get("entryAt")) or num(p.get("t"))
        if not addr(p.get("pair")) or not e:
            continue
        paper = p.get("grp") in ("hold", "young") and since is not None and (num(p.get("t")) or 0) >= since
        pos.append((p, e, paper))
    out, used = [], set()
    for target in (24, 48, 75):
        c = [(abs((now - e) / 3.6e6 - target), p, e) for p, e, ok in pos if ok and now - e > 6 * 3600e3 + 2 * MIN and p["pair"] not in used]
        if c:
            _, p, e = min(c, key=lambda x: x[0])
            used.add(p["pair"])
            out.append(("%dh" % target, p, e))
    old = [(e, p) for p, e, ok in pos if p["pair"] not in used]
    if old:
        e, p = min(old, key=lambda x: x[0])
        out.append(("oldest", p, e))
    return since, len(pos), sum(1 for x in pos if x[2]), out


def gt_ohlcv(h, pair, end_ms, agg, limit):
    url = GT + "/networks/solana/pools/%s/ohlcv/minute?aggregate=%d&limit=%d&before_timestamp=%d&currency=usd&token=base" % (pair, agg, limit, end_ms // 1000 + 120)
    r = h.req(url)
    rows = (((r.js or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(r.js, dict) else None
    return r, [c for c in (rows or []) if isinstance(c, list) and len(c) >= 5 and num(c[0])]


@guarded("c1")
def check1(h, res):
    now = now_ms()
    since, n_pos, n_paper, wins = pick_windows(res, now)
    say("[c1] positions with a pair: %d, paper since restart: %d, windows probed: %d" % (n_pos, n_paper, len(wins)))
    out, n429 = [], 0
    for label, p, entry in wins:
        end = int(entry + 6 * 3600e3)
        row = {"label": label, "ageH": round((now - entry) / 3.6e6, 1), "dex": p.get("dex"), "grp": p.get("grp")}
        for agg, limit in ((1, 400), (15, 30)):
            r, rows = gt_ohlcv(h, p["pair"], end, agg, limit)
            n429 += r.code == 429
            ts = sorted(int(num(c[0]) * 1000) for c in rows)
            inwin = [t for t in ts if entry - MIN <= t <= end]
            key = "m%d" % agg
            row[key] = {**r.brief(), "n": len(rows), "inWindow": len(inwin),
                        "firstVsEntryMin": round((ts[0] - entry) / MIN, 1) if ts else None,
                        "lastVsEndMin": round((ts[-1] - end) / MIN, 1) if ts else None,
                        "firstInWindowMin": round((inwin[0] - entry) / MIN, 1) if inwin else None,
                        "lastInWindowMin": round((inwin[-1] - entry) / MIN, 1) if inwin else None,
                        "newestFirst": (num(rows[0][0]) > num(rows[-1][0])) if len(rows) > 1 else None,
                        "volField": bool(rows and len(rows[0]) > 5)}
            say("[c1] %s window (%.1f h old, %s) aggregate=%d -> %s n=%d inWindow=%d first=%s min after entry, last=%s min vs end, %dms rl=%s"
                % (label, row["ageH"], row["dex"], agg, r.code, len(rows), len(inwin), row[key]["firstVsEntryMin"], row[key]["lastVsEndMin"],
                   row[key]["ms"], json.dumps(r.rl())))
        out.append(row)
    R["c1"] = {"windows": out, "n429": n429, "gapS": GAP["api.geckoterminal.com"]}


# ---------------------------------------------------------------- check 2 (discovery)
class Discovery:
    RADAR = ["pf:graduated", "pf:new", "gt:new", "jup:recent", "ds:profiles", "ll:new", "rc:new_tokens"]
    EXTRA = ["pf:top", "jup:trending1h", "jup:traded1h"]          # comparison only, not in the radar's list

    def __init__(self, h):
        self.h = h
        self.cache = {}        # mint -> {"pool": ms, "liq", "dex"} | {"nopool": True, "curve": bool}
        self.info = {}         # mint -> {"pf": coin dict, "llCreated": ms, "jupCreated": ms, "gtPool": ms}
        self.fresh = {}        # mint -> {"cycle", "age0", "liq0", "dex", "pool", "src": {source: age at first listing}}
        self.cycles = []
        self.fields = {}
        self.src_stats = {s: {"calls": 0, "codes": Counter(), "secs": 0.0, "cands": []} for s in self.RADAR + self.EXTRA}

    def _get(self, src, url, headers=None):
        r = self.h.req(url, headers=headers)
        st = self.src_stats[src]
        st["calls"] += 1
        st["codes"][str(r.code)] += 1
        st["secs"] += r.secs
        if r.code != 200:
            say("[c2] %s -> %s %s" % (src, r.code, json.dumps(r.brief())))
        return r

    def _pf(self, src, path, pages):
        mints = []
        for pg in range(pages):
            r = self._get(src, PF + path % (pg * 50))
            if not isinstance(r.js, list) or not r.js:
                break
            for c in r.js:
                a = addr((c or {}).get("mint")) if isinstance(c, dict) else None
                if a:
                    mints.append(a)
                    self.info.setdefault(a, {})["pf"] = c
                    self.fields.setdefault(src, keys(c))
        return mints

    def _jup(self, src, path):
        r = self._get(src, JUP + path)
        mints = []
        for t in r.js if isinstance(r.js, list) else []:
            a = addr((t or {}).get("id")) if isinstance(t, dict) else None
            if a:
                mints.append(a)
                self.fields.setdefault(src, keys(t))
                fp = ts_ms((t.get("firstPool") or {}).get("createdAt")) if isinstance(t.get("firstPool"), dict) else None
                if fp:
                    self.info.setdefault(a, {})["jupPool"] = fp
                cr = ts_ms(t.get("createdAt"))
                if cr:
                    self.info.setdefault(a, {})["jupCreated"] = cr
        return mints

    def fetch_sources(self):
        lists, at = {}, {}
        jobs = [("pf:graduated", lambda: self._pf("pf:graduated", "/coins?offset=%d&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false&complete=true", 4)),
                ("pf:new", lambda: self._pf("pf:new", "/coins?offset=%d&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false", 2)),
                ("gt:new", self._gt_new),
                ("jup:recent", lambda: self._jup("jup:recent", "/recent")),
                ("ds:profiles", self._ds_profiles),
                ("ll:new", self._ll_new),
                ("rc:new_tokens", self._rc_new),
                ("pf:top", lambda: self._pf("pf:top", "/coins?offset=%d&limit=50&sort=market_cap&order=DESC&includeNsfw=false", 2)),
                ("jup:trending1h", lambda: self._jup("jup:trending1h", "/toptrending/1h?limit=100")),
                ("jup:traded1h", lambda: self._jup("jup:traded1h", "/toptraded/1h?limit=100"))]
        for src, f in jobs:
            t0 = now_ms()
            try:
                lists[src] = list(dict.fromkeys(f()))
            except Exception as e:
                tb = traceback.extract_tb(e.__traceback__)
                say("[c2] %s SCRIPT ERROR %s at line %s" % (src, type(e).__name__, tb[-1].lineno if tb else "?"))
                lists[src] = []
            at[src] = (t0 + now_ms()) // 2
            self.src_stats[src]["cands"].append(len(lists[src]))
        return lists, at

    def _gt_new(self):
        mints = []
        for pg in (1, 2):
            r = self._get("gt:new", GT + "/networks/solana/new_pools?include=base_token&page=%d" % pg)
            for pool in ((r.js or {}).get("data") or []) if isinstance(r.js, dict) else []:
                if not isinstance(pool, dict):
                    continue
                self.fields.setdefault("gt:new", keys(pool.get("attributes") or {}))
                tid = str((((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id") or "")
                a = addr(tid.split("_", 1)[1]) if "_" in tid else None
                if a:
                    mints.append(a)
                    pc = ts_ms((pool.get("attributes") or {}).get("pool_created_at"))
                    if pc:
                        self.info.setdefault(a, {})["gtPool"] = pc
        return mints

    def _ds_profiles(self):
        r = self._get("ds:profiles", DS + "/token-profiles/latest/v1")
        out = []
        for t in r.js if isinstance(r.js, list) else []:
            if isinstance(t, dict) and t.get("chainId") == "solana":
                self.fields.setdefault("ds:profiles", keys(t))
                a = addr(t.get("tokenAddress"))
                if a:
                    out.append(a)
        return out

    def _ll_new(self):
        r = self._get("ll:new", LL + "/get/list?sort=new&size=100&mintType=default&includeNsfw=false")
        out = []
        for c in (((r.js or {}).get("data") or {}).get("rows") or []) if isinstance(r.js, dict) else []:
            if not isinstance(c, dict):
                continue
            self.fields.setdefault("ll:new", keys(c))
            a = addr(c.get("mint"))
            if a:
                out.append(a)
                cr = next((ts_ms(c.get(k)) for k in ("createAt", "createdAt", "createTime") if c.get(k) is not None), None)
                if cr:
                    self.info.setdefault(a, {})["llCreated"] = cr
        return out

    def _rc_new(self):
        r = self._get("rc:new_tokens", RC + "/stats/new_tokens")
        out = []
        for t in r.js if isinstance(r.js, list) else []:
            if isinstance(t, dict):
                self.fields.setdefault("rc:new_tokens", keys(t))
                a = addr(t.get("mint"))
                if a:
                    out.append(a)
        return out

    def ds_lookup(self, mints):
        """DexScreener tokens/v1, 30 a request; a pool-age cache skips every mint whose first DEX pool is already known."""
        ask = [a for a in dict.fromkeys(mints) if "pool" not in self.cache.get(a, {})]
        calls, codes, t0 = 0, Counter(), time.time()
        for i in range(0, len(ask), 30):
            part = ask[i:i + 30]
            r = self.h.req(DS + "/tokens/v1/solana/" + ",".join(part))
            calls += 1
            codes[str(r.code)] += 1
            if r.code != 200 or not isinstance(r.js, list):
                if r.code != 200:
                    say("[c2] ds tokens/v1 -> %s %s" % (r.code, json.dumps(r.brief())))
                continue
            seen = {}
            for p in r.js:
                if not isinstance(p, dict) or p.get("chainId") != "solana":
                    continue
                self.fields.setdefault("ds:tokens/v1", keys(p))
                b = addr((p.get("baseToken") or {}).get("address"))
                if b not in part:
                    continue
                s = seen.setdefault(b, {"pool": None, "liq": 0.0, "dex": None, "curve": False})
                if CURVE_DEX.search(str(p.get("dexId") or "")):
                    s["curve"] = True
                    continue
                pc = num(p.get("pairCreatedAt"))
                if pc and (s["pool"] is None or pc < s["pool"]):
                    s["pool"], s["dex"] = pc, p.get("dexId")
                s["liq"] = max(s["liq"], num((p.get("liquidity") or {}).get("usd")) or 0.0)
            for a in part:
                s = seen.get(a)
                if s and s["pool"]:
                    self.cache[a] = {"pool": s["pool"], "liq": s["liq"], "dex": s["dex"]}
                else:
                    self.cache[a] = {"nopool": True, "curve": bool(s and s["curve"])}
        return {"asked": len(ask), "calls": calls, "codes": dict(codes), "secs": round(time.time() - t0, 1)}

    def run(self, k):
        t0 = time.time()
        lists, at = self.fetch_sources()
        ds = self.ds_lookup([a for src in lists for a in lists[src]])
        new_fresh, row = 0, {"cycle": k, "cands": {s: len(v) for s, v in lists.items()}, "ds": ds}
        per_src_fresh = {}
        for src, mints in lists.items():
            n = 0
            for a in mints:
                c = self.cache.get(a) or {}
                if not c.get("pool"):
                    continue
                age = (at[src] - c["pool"]) / MIN
                if age < 0 or age >= FRESH_MIN:
                    continue
                n += 1
                f = self.fresh.get(a)
                if not f:
                    f = self.fresh[a] = {"cycle": k, "age0": round(age, 2), "liq0": c.get("liq") or 0.0, "dex": c.get("dex"), "pool": c["pool"], "src": {}}
                    new_fresh += 1
                f["src"].setdefault(src, round(age, 2))
            per_src_fresh[src] = n
        row.update(fresh=per_src_fresh, newFresh=new_fresh, secs=round(time.time() - t0, 1),
                   curveOnly=sum(1 for v in self.cache.values() if v.get("curve")), noPool=sum(1 for v in self.cache.values() if v.get("nopool")))
        self.cycles.append(row)
        say("[c2] cycle %d: %.1fs, DS asked %d in %d calls %s, new pools <10 min: %d, per source: %s"
            % (k, row["secs"], ds["asked"], ds["calls"], json.dumps(ds["codes"]), new_fresh, json.dumps(per_src_fresh)))
        say("[c2] cycle %d candidates: %s" % (k, json.dumps(row["cands"])))

    def mint_time(self, a):
        i = self.info.get(a) or {}
        pf = i.get("pf") or {}
        for src, v in (("pf", ts_ms(pf.get("created_timestamp"))), ("ll", i.get("llCreated")), ("jup", i.get("jupCreated"))):
            if v:
                return src, v
        return None, None

    def summary(self):
        F = self.fresh
        radar = set(self.RADAR)
        allsrc = self.RADAR + self.EXTRA
        out = {"cycles": self.cycles, "freshTotal": len(F), "fresh5k": sum(1 for f in F.values() if f["liq0"] >= 5000),
               "freshByRadarSet": sum(1 for f in F.values() if radar & set(f["src"])),
               "fresh5kByRadarSet": sum(1 for f in F.values() if f["liq0"] >= 5000 and radar & set(f["src"])),
               "onlyExtra": sum(1 for f in F.values() if not radar & set(f["src"])),
               "seenAgeMedian": med([min(f["src"].values()) for f in F.values()]),
               "dex": dict(Counter(str(f["dex"]) for f in F.values())), "sources": {}, "fields": self.fields}
        mt = Counter()
        m2p = []
        for a, f in F.items():
            src, v = self.mint_time(a)
            mt[src or "unknown"] += 1
            if v:
                m2p.append((f["pool"] - v) / 1000)
        out["mintTimeFrom"] = dict(mt)
        out["mintToPoolS"] = {"n": len(m2p), "median": med(m2p), "under60s": sum(1 for x in m2p if x < 60), "negative": sum(1 for x in m2p if x < 0)}
        for s in allsrc:
            got = [f for f in F.values() if s in f["src"]]
            others = (radar - {s})
            st = self.src_stats[s]
            out["sources"][s] = {
                "set": "radar" if s in radar else "extra",
                "calls": st["calls"], "codes": dict(st["codes"]), "secs": round(st["secs"], 1),
                "candsPerCycle": st["cands"], "found": len(got), "found5k": sum(1 for f in got if f["liq0"] >= 5000),
                "sole": sum(1 for f in got if not (others & set(f["src"])) and s in radar),
                "medSeenAge": med([f["src"][s] for f in got]),
                "firstToList": sum(1 for f in got if f["src"][s] <= min(f["src"].values()) + 0.01)}
        R["c2"] = out
        say("[c2] fresh pools seen: %d (liq >= $5k: %d); by the radar set: %d (%d); only by the extra sources: %d; median age at first sight %s min"
            % (out["freshTotal"], out["fresh5k"], out["freshByRadarSet"], out["fresh5kByRadarSet"], out["onlyExtra"], out["seenAgeMedian"]))
        for s, v in out["sources"].items():
            say("[c2] source %-15s %-5s calls=%d codes=%s cands/cycle=%s found=%d (5k: %d) sole=%d first=%d median age %s min"
                % (s, v["set"], v["calls"], json.dumps(v["codes"]), v["candsPerCycle"], v["found"], v["found5k"], v["sole"], v["firstToList"], v["medSeenAge"]))
        say("[c2] mint time known from: %s; mint to pool: %s" % (json.dumps(out["mintTimeFrom"]), json.dumps(out["mintToPoolS"])))
        for s, f in sorted(self.fields.items()):
            say("[c2] fields %s: %s" % (s, ",".join(f) if isinstance(f, list) else f))

    def target(self, want_min=4.0):
        """The fresh pump.fun pool closest to want_min minutes old now (liq >= $5k preferred), else the youngest graduated pf coin."""
        now = now_ms()
        c = [(abs((now - f["pool"]) / MIN - want_min) + (0 if f["liq0"] >= 5000 else 5), a) for a, f in self.fresh.items()
             if a.endswith("pump") or (self.info.get(a) or {}).get("pf")]
        if c:
            a = min(c)[1]
            return a, True
        grads = [(now - self.cache[a]["pool"], a) for a, i in self.info.items() if (i.get("pf") or {}).get("complete") and self.cache.get(a, {}).get("pool")]
        return (min(grads)[1], False) if grads else (None, False)

    def pick(self, lo, hi, n, want=None, skip=()):
        """Up to n pump.fun coins (liq >= $5k) whose first DEX pool is lo..hi minutes old now, closest to want (default: the middle)."""
        now, want = now_ms(), (lo + hi) / 2 if want is None else want
        c = []
        for a, v in self.cache.items():
            if a in skip or not v.get("pool") or (v.get("liq") or 0) < 5000 or not (a.endswith("pump") or (self.info.get(a) or {}).get("pf")):
                continue
            age = (now - v["pool"]) / MIN
            if lo <= age <= hi:
                c.append((abs(age - want), a))
        return [a for _, a in sorted(c)[:n]]

    def curve_coin(self):
        """A pf:new coin still on its bonding curve (no DEX pool), the youngest."""
        c = [(-(ts_ms((i.get("pf") or {}).get("created_timestamp")) or 0), a) for a, i in self.info.items()
             if i.get("pf") and not (i["pf"].get("complete")) and self.cache.get(a, {}).get("nopool")]
        return min(c)[1] if c else None


# ---------------------------------------------------------------- checks 3-6 (pump.fun, swap-api, holders, RugCheck)
def pool_age_min(disc, a):
    p = (disc.cache.get(a) or {}).get("pool")
    return round((now_ms() - p) / MIN, 2) if p else None


@guarded("c3")
def check3(h, disc, mint, fresh):
    out = {"targetFresh": fresh, "poolAgeMin": pool_age_min(disc, mint), "coinCalls": {}}
    # run 1: frontend-api-v3 /coins/{mint} answered "Cannot GET" (the route is gone); the captures name /coins-v3/{mint}
    c, r = {}, None
    for name, url in (("v3 coins/{mint}", PF + "/coins/" + mint), ("v3 coins-v3/{mint}", PF + "/coins-v3/" + mint),
                      ("adv coins-v3/{mint}", ADV + "/coins-v3/" + mint), ("adv coins/metadata/{mint}", ADV + "/coins/metadata/" + mint)):
        rr = h.req(url, headers=PF_WEB if url.startswith(ADV) else None)
        js = rr.js if isinstance(rr.js, dict) else {}
        out["coinCalls"][name] = {**rr.brief(), "nFields": len(js), "mint": bool(addr(js.get("mint"))),
                                  "created": js.get("created_timestamp") is not None, "creator": bool(addr(js.get("creator")))}
        say("[c3] %s -> %s %dms rl=%s fields=%d mint=%s created=%s creator=%s %s"
            % (name, rr.code, int(rr.secs * 1000), json.dumps(rr.rl()), len(js), out["coinCalls"][name]["mint"], out["coinCalls"][name]["created"],
               out["coinCalls"][name]["creator"], json.dumps(rr.brief().get("body", ""))))
        if rr.code == 200 and addr(js.get("mint")) and not c:
            c, r = js, rr
    row = (disc.info.get(mint) or {}).get("pf") or {}
    out["coinSource"] = "endpoint" if c else ("pf list row" if row else "none")
    out["listRow"] = {"fields": keys(row, 120), "gradLike": sorted(k for k in row if re.search(r"grad|migrat|complete|king|pool|bond|curve|program|protocol", k, re.I))}
    if not c:
        c = row
    r = r or Resp(None, {}, None, b"", 0.0)
    created = ts_ms(c.get("created_timestamp"))
    pool = (disc.cache.get(mint) or {}).get("pool")
    out["coin"] = {**r.brief(), "nFields": len(c), "fields": keys(c, 120),
                   "has": {k: c.get(k) not in (None, "") for k in ("created_timestamp", "creator", "twitter", "website", "telegram", "pump_swap_pool",
                                                                   "raydium_pool", "complete", "king_of_the_hill_timestamp", "last_trade_timestamp", "usd_market_cap", "ath_market_cap")},
                   "gradLike": sorted(k for k in c if re.search(r"grad|migrat|complete|king|pool|bond|curve", k, re.I)),
                   "createdUnit": ("ms" if num(c.get("created_timestamp")) and num(c.get("created_timestamp")) > 1e11 else "s") if c.get("created_timestamp") is not None else None,
                   "mintToPoolS": round((pool - created) / 1000, 1) if (pool and created) else None}
    say("[c3] coin from %s: fields=%d has=%s gradLike=%s mintToPool=%ss"
        % (out["coinSource"], len(c), json.dumps(out["coin"]["has"]), out["coin"]["gradLike"], out["coin"]["mintToPoolS"]))
    say("[c3] coin fields: %s" % ",".join(out["coin"]["fields"]) if isinstance(out["coin"]["fields"], list) else "[c3] coin fields: none")
    dev = addr(c.get("creator"))
    devs = [d for d in [dev, addr(((disc.info.get(disc.curve_coin() or "") or {}).get("pf") or {}).get("creator"))] if d]
    out["dev"] = []
    for i, d in enumerate(dict.fromkeys(devs)):
        row = {"which": "target coin's dev" if i == 0 and dev else "curve coin's dev"}
        r = h.req(PF + "/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false&creator=" + d)
        rows = [x for x in r.js if isinstance(x, dict)] if isinstance(r.js, list) else []
        now = now_ms()
        row["byCreator"] = {**r.brief(), "n": len(rows), "sameCreator": sum(1 for x in rows if x.get("creator") == d),
                            "complete": sum(1 for x in rows if x.get("complete")),
                            "under10kMc": sum(1 for x in rows if (num(x.get("usd_market_cap")) or 0) < 10_000),
                            "oldestAgeH": round(max([(now - (ts_ms(x.get("created_timestamp")) or now)) / 3.6e6 for x in rows] or [0]), 1)}
        say("[c3] coins?creator= (%s) -> %s n=%d sameCreator=%d complete=%d under10kMc=%d oldest=%sh %dms"
            % (row["which"], r.code, len(rows), row["byCreator"]["sameCreator"], row["byCreator"]["complete"], row["byCreator"]["under10kMc"],
               row["byCreator"]["oldestAgeH"], row["byCreator"]["ms"]))
        r = h.req(PF + "/coins/user-created-coins/%s?offset=0&limit=50&includeNsfw=false" % d)
        js = r.js
        row["v1UserCreated"] = {**r.brief(), "type": type(js).__name__, "n": len(js) if isinstance(js, list) else (len(js.get("coins") or []) if isinstance(js, dict) else None),
                                "topFields": keys(js) if isinstance(js, dict) else None}
        say("[c3] frontend-api-v3 coins/user-created-coins -> %s n=%s %dms" % (r.code, row["v1UserCreated"]["n"], row["v1UserCreated"]["ms"]))
        for host, name in ((PF, "v3"), (ADV, "adv")):
            r = h.req(host + "/coins-v2/user-created-coins/%s?offset=0&limit=50" % d, headers=PF_WEB)
            js = r.js if isinstance(r.js, dict) else {}
            coins = [x for x in (js.get("coins") or []) if isinstance(x, dict)]
            row["v2UserCreated_" + name] = {**r.brief(), "topFields": keys(js), "count": js.get("count") if isinstance(js.get("count"), (int, float)) else None,
                                            "n": len(coins), "coinFields": keys(coins[0]) if coins else None,
                                            "complete": sum(1 for x in coins if x.get("complete"))}
            say("[c3] %s coins-v2/user-created-coins -> %s count=%s n=%d fields=%s %dms rl=%s"
                % (name, r.code, row["v2UserCreated_" + name]["count"], len(coins), row["v2UserCreated_" + name]["topFields"], row["v2UserCreated_" + name]["ms"], json.dumps(r.rl())))
        out["dev"].append(row)
    R["c3"] = out
    return c, dev


def trade_ts(t):
    return ts_ms(t.get("timestamp")) if isinstance(t, dict) else None


def launch_stats(rows, created):
    """Trades in the first 30 s after the mint and buyers in the launch slot (slotIndexId = 12-digit slot + 10-digit index)."""
    if not rows or not created:
        return None
    early = [t for t in rows if (trade_ts(t) or 0) <= created + 30_000]
    slots = [int(str(t.get("slotIndexId"))[:12]) for t in rows if str(t.get("slotIndexId") or "").isdigit() and len(str(t.get("slotIndexId"))) >= 13]
    first = min(slots) if slots else None
    return {"in30s": len(early), "buys30s": sum(1 for t in early if t.get("type") == "buy"), "wallets30s": len({t.get("userAddress") for t in early}),
            "firstSlotRows": sum(1 for s in slots if s == first) if first else None, "reachedMint": bool(early)}


@guarded("c4")
def check4(h, mint, coin, label="target", pool=None):
    out = {"label": label}
    created = ts_ms((coin or {}).get("created_timestamp"))
    variants = [("plain", "?limit=100"), ("browser", "?chainId=solana&cursor=&limit=100&program=pump")]
    r, js, used = None, None, None
    for name, q in variants:
        r = h.req(SWAP + "/v2/coins/%s/trades%s" % (mint, q), headers=PF_WEB)
        say("[c4] %s swap-api v2 trades (%s) -> %s %dms rl=%s %s" % (label, name, r.code, int(r.secs * 1000), json.dumps(r.rl()), json.dumps(r.brief().get("body", ""))))
        out.setdefault("variants", {})[name] = r.brief()
        if r.code == 200 and isinstance(r.js, dict):
            js, used = r.js, (name, q)
            break
    if js is not None:
        pages, allrows, cur = [], [], None
        for pg in range(4):
            if pg:
                if not cur:
                    break
                r = h.req(SWAP + "/v2/coins/%s/trades%s&cursor=%s" % (mint, used[1].replace("&cursor=", ""), urllib.parse.quote(cur)), headers=PF_WEB)
                js = r.js if isinstance(r.js, dict) else {}
            rows = [t for t in (js.get("trades") or []) if isinstance(t, dict)]
            pag = js.get("pagination") or {}
            cur = pag.get("nextCursor") if pag.get("hasMore") else None
            ts = [trade_ts(t) for t in rows if trade_ts(t)]
            pages.append({"code": r.code, "rows": len(rows), "hasMore": pag.get("hasMore"), "cursor": bool(pag.get("nextCursor")),
                          "newestFirst": (ts[0] > ts[-1]) if len(ts) > 1 else None, "ms": int(r.secs * 1000)})
            allrows += rows
        ts = [trade_ts(t) for t in allrows if trade_ts(t)]
        slots = [str(t.get("slotIndexId") or "") for t in allrows]
        out["trades"] = {"variant": used[0], "pages": pages, "rowFields": keys(allrows[0]) if allrows else None, "paginationFields": keys(js.get("pagination") or {}),
                         "topFields": keys(js), "n": len(allrows), "slotIndexId": sum(1 for s in slots if s), "slotLen": dict(Counter(len(s) for s in slots if s)),
                         "slotDigits": all(s.isdigit() for s in slots if s), "types": dict(Counter(str(t.get("type")) for t in allrows)),
                         "programs": dict(Counter(mask(t.get("program"), 20) for t in allrows)), "wallets": len({t.get("userAddress") for t in allrows}),
                         "oldestVsMintS": round((min(ts) - created) / 1000, 1) if (ts and created) else None,
                         "spanMin": round((max(ts) - min(ts)) / MIN, 1) if ts else None}
        out["trades"]["launch"] = launch_stats(allrows, created)
        say("[c4] %s trades: pages=%s rowFields=%s slotIndexId=%d lens=%s types=%s programs=%s wallets=%d oldest-vs-mint=%ss span=%smin launch=%s"
            % (label, json.dumps(pages), out["trades"]["rowFields"], out["trades"]["slotIndexId"], out["trades"]["slotLen"], out["trades"]["types"],
               out["trades"]["programs"], out["trades"]["wallets"], out["trades"]["oldestVsMintS"], out["trades"]["spanMin"], json.dumps(out["trades"]["launch"])))
    if label != "curve":
        # a graduated coin: its bonding-curve trades (the launch, the first 30 s) through the program filter, newest first
        allrows, cur, pages = [], None, []
        for pg in range(3):
            if pg and not cur:
                break
            r = h.req(SWAP + "/v2/coins/%s/trades?limit=100&program=pump%s" % (mint, ("&cursor=" + urllib.parse.quote(cur)) if cur else ""), headers=PF_WEB)
            js = r.js if isinstance(r.js, dict) else {}
            rows = [t for t in (js.get("trades") or []) if isinstance(t, dict)]
            pag = js.get("pagination") or {}
            cur = pag.get("nextCursor") if pag.get("hasMore") else None
            pages.append({"code": r.code, "rows": len(rows), "hasMore": pag.get("hasMore"), "ms": int(r.secs * 1000)})
            allrows += rows
        ts = [trade_ts(t) for t in allrows if trade_ts(t)]
        out["curvePhase"] = {"pages": pages, "n": len(allrows), "programs": dict(Counter(mask(t.get("program"), 20) for t in allrows)),
                             "oldestVsMintS": round((min(ts) - created) / 1000, 1) if (ts and created) else None,
                             "newestVsPoolS": round((max(ts) - pool) / 1000, 1) if (ts and pool) else None, "launch": launch_stats(allrows, created)}
        say("[c4] %s curve-phase trades (program=pump): %s" % (label, json.dumps(out["curvePhase"])))
    for name, url in (("v2", SWAP + "/v2/coins/%s/candles?interval=1m&limit=100&currency=USD&createdTs=%d" % (mint, created or 0)),
                      ("v1", SWAP + "/v1/coins/%s/candles?interval=1m&limit=100&currency=USD" % mint)):
        r = h.req(url, headers=PF_WEB)
        rows = [c for c in r.js if isinstance(c, dict)] if isinstance(r.js, list) else []
        ts = [ts_ms(c.get("timestamp")) for c in rows if ts_ms(c.get("timestamp"))]
        raw_ts = num(rows[0].get("timestamp")) if rows else None
        out["candles_" + name] = {**r.brief(), "n": len(rows), "fields": keys(rows[0]) if rows else (keys(r.js) if isinstance(r.js, dict) else None),
                                  "tsUnit": ("ms" if raw_ts and raw_ts > 1e11 else "s") if raw_ts else None,
                                  "newestFirst": (ts[0] > ts[-1]) if len(ts) > 1 else None,
                                  "firstVsMintMin": round((min(ts) - created) / MIN, 1) if (ts and created) else None,
                                  "lastAgeMin": round((now_ms() - max(ts)) / MIN, 1) if ts else None}
        say("[c4] %s swap-api %s candles 1m -> %s n=%d fields=%s unit=%s first-vs-mint=%smin last-age=%smin %dms rl=%s"
            % (label, name, r.code, len(rows), out["candles_" + name]["fields"], out["candles_" + name]["tsUnit"], out["candles_" + name]["firstVsMintMin"],
               out["candles_" + name]["lastAgeMin"], out["candles_" + name]["ms"], json.dumps(r.rl())))
    R.setdefault("c4", {})[label] = out


def check5_holders(h, label, mint, holders):
    out = {}
    for host, name in ((PF, "v3"), (ADV, "adv")):
        r = h.req(host + "/coins/top-holders/%s" % mint, headers=PF_WEB)
        js = r.js if isinstance(r.js, dict) else {}
        th = [x for x in (js.get("topHolders") or []) if isinstance(x, dict)]
        fs = [x.get("fundingSource") for x in th if isinstance(x.get("fundingSource"), dict)]
        out[name] = {**r.brief(), "topFields": keys(js), "n": len(th), "itemFields": keys(th[0]) if th else None,
                     "isSniper": sum(1 for x in th if x.get("isSniper")), "isBundler": sum(1 for x in th if x.get("isBundler")),
                     "isDev": sum(1 for x in th if x.get("isDev")), "enteredAt": sum(1 for x in th if num(x.get("enteredAt"))),
                     "fundingSource": len(fs), "fundingFields": keys(fs[0]) if fs else None,
                     "funderType": dict(Counter(mask(f.get("funderType"), 24) for f in fs)),
                     "sameFunder": max(Counter(f.get("funder") for f in fs).values()) if fs else 0,
                     "totalHolders": isinstance(js.get("totalHolders"), (int, float))}
        o = out[name]
        say("[c5] %s %s top-holders -> %s n=%d fields=%s sniper=%d bundler=%d dev=%d enteredAt=%d fundingSource=%d fundingFields=%s maxSameFunder=%d %dms rl=%s %s"
            % (label, name, r.code, len(th), o["itemFields"], o["isSniper"], o["isBundler"], o["isDev"], o["enteredAt"], len(fs), o["fundingFields"],
               o["sameFunder"], o["ms"], json.dumps(r.rl()), json.dumps(r.brief().get("body", ""))))
        if not holders:
            holders += [a for a in (addr(x.get("address")) for x in th) if a]
    return out


@guarded("c5")
def check5(h, coins, rc_owners):
    """top-holders on both hosts for each (label, mint): are isSniper / isBundler / isDev / fundingSource ever filled without a login?"""
    out = {"coins": {}}
    holders = []
    for label, mint in coins:
        out["coins"][label] = check5_holders(h, label, mint, holders)
    mint = coins[0][1]
    r = h.req(ADV + "/coins/top-holders-and-sol-balance/%s" % mint, headers=PF_WEB)
    out["topHoldersSol_adv"] = {**r.brief(), "topFields": keys(r.js) if isinstance(r.js, dict) else type(r.js).__name__}
    say("[c5] adv top-holders-and-sol-balance -> %s fields=%s %dms" % (r.code, out["topHoldersSol_adv"]["topFields"], out["topHoldersSol_adv"]["ms"]))
    ws = (holders or rc_owners)[:10]
    out["walletsFrom"] = "top-holders" if holders else ("rugcheck" if rc_owners else "none")
    for host, name in ((ADV, "adv"), (PF, "v3")):
        if not ws:
            break
        r = h.req(host + "/wallet-overview", "POST", {"wallets": ws}, headers=PF_WEB)
        w = (r.js or {}).get("wallets") if isinstance(r.js, dict) else None
        w = w if isinstance(w, dict) else {}
        vals = [v for v in w.values() if isinstance(v, dict)]
        first = [ts_ms(v.get("first_tx_timestamp")) for v in vals if ts_ms(v.get("first_tx_timestamp"))]
        now = now_ms()
        out["walletOverview_" + name] = {**r.brief(), "asked": len(ws), "n": len(vals), "fields": keys(vals[0]) if vals else (keys(r.js) if isinstance(r.js, dict) else None),
                                         "firstTx": len(first), "under1d": sum(1 for t in first if now - t < 86_400_000),
                                         "rawUnit": ("ms" if num(vals[0].get("first_tx_timestamp")) and num(vals[0].get("first_tx_timestamp")) > 1e11 else "s") if vals and vals[0].get("first_tx_timestamp") is not None else None}
        say("[c5] %s POST wallet-overview (%d wallets) -> %s n=%d fields=%s firstTx=%d under1d=%d %dms rl=%s %s"
            % (name, len(ws), r.code, len(vals), out["walletOverview_" + name]["fields"], len(first), out["walletOverview_" + name]["under1d"],
               out["walletOverview_" + name]["ms"], json.dumps(r.rl()), json.dumps(r.brief().get("body", ""))))
        if r.code == 200 and vals:
            break
    R["c5"] = out
    return ws


@guarded("c6")
def check6(h, disc, coins, tag):
    """RugCheck reports for each (label, mint); returns the first coin's top-holder owners."""
    owners = None
    for label, mint in coins:
        got = check6_one(h, disc, mint, tag, label, summary=owners is None)
        if owners is None:
            owners = got
    return owners or []


def check6_one(h, disc, mint, tag, label, summary):
    age = pool_age_min(disc, mint)
    r = h.req(RC + "/tokens/%s/report" % mint)
    rep = r.js if isinstance(r.js, dict) else {}
    ct = rep.get("creatorTokens")
    inet = rep.get("insiderNetworks")
    th = [x for x in (rep.get("topHolders") or []) if isinstance(x, dict)]
    risks = [x for x in (rep.get("risks") or []) if isinstance(x, dict)]
    nets = [x for x in inet if isinstance(x, dict)] if isinstance(inet, list) else []
    out = {**r.brief(), "poolAgeMin": age, "fields": keys(rep, 120), "creator": bool(addr(rep.get("creator"))),
           "creatorTokens": {"type": type(ct).__name__, "n": len(ct) if isinstance(ct, (list, dict)) else None,
                             "itemFields": keys(ct[0]) if isinstance(ct, list) and ct and isinstance(ct[0], dict) else None},
           "insiderNetworks": {"type": type(inet).__name__, "n": len(nets), "itemFields": keys(nets[0]) if nets else None,
                               "sizes": sorted([int(num(x.get("size")) or 0) for x in nets], reverse=True)[:5]},
           "graphInsidersDetected": num(rep.get("graphInsidersDetected")),
           "topHolders": {"n": len(th), "itemFields": keys(th[0]) if th else None, "insider": sum(1 for x in th if x.get("insider")),
                          "owner": sum(1 for x in th if addr(x.get("owner")))},
           "risks": {"n": len(risks), "levels": dict(Counter(str(x.get("level")) for x in risks)), "names": [mask(x.get("name"), 50) for x in risks][:12]},
           "creatorBalance": rep.get("creatorBalance") is not None, "markets": len(rep.get("markets") or []) if isinstance(rep.get("markets"), list) else None,
           "launchpad": rep.get("launchpad") is not None, "score": num(rep.get("score_normalised"))}
    say("[c6] %s/%s report (pool %s min old) -> %s %dms rl=%s creator=%s creatorTokens=%s insiderNetworks=%s graphInsidersDetected=%s topHolders=%s risks=%s"
        % (tag, label, age, r.code, out["ms"], json.dumps(r.rl()), out["creator"], json.dumps(out["creatorTokens"]), json.dumps(out["insiderNetworks"]),
           out["graphInsidersDetected"], json.dumps(out["topHolders"]), json.dumps(out["risks"])))
    if summary:
        say("[c6] %s report fields: %s" % (tag, ",".join(out["fields"]) if isinstance(out["fields"], list) else out["fields"]))
        r2 = h.req(RC + "/tokens/%s/report/summary" % mint)
        out["summary"] = {**r2.brief(), "fields": keys(r2.js) if isinstance(r2.js, dict) else None}
        say("[c6] %s summary -> %s fields=%s %dms" % (tag, r2.code, out["summary"]["fields"], out["summary"]["ms"]))
    R.setdefault("c6", {}).setdefault(tag, {})[label] = out
    return [a for a in (addr(x.get("owner")) for x in th) if a]


# ---------------------------------------------------------------- check 7 (Solana public RPC)
def rpc_rl(r):
    """The public RPC's own limit headers: per-method and per-second budgets left."""
    return {k.replace("x-ratelimit-", ""): v for k, v in r.h.items() if k.startswith("x-ratelimit-") and k.split("-")[2] in ("method", "rps", "tier")}


def sig_depth(h, who, max_pages=3):
    pages, sigs, before, codes, rl = 0, [], None, Counter(), None
    t0 = time.time()
    for _ in range(max_pages):
        opt = {"limit": 1000}
        if before:
            opt["before"] = before
        r = h.rpc("getSignaturesForAddress", [who, opt])
        pages += 1
        codes[str(r.code)] += 1
        rl = rl or rpc_rl(r)
        res = (r.js or {}).get("result") if isinstance(r.js, dict) else None
        if isinstance(r.js, dict) and r.js.get("error"):
            codes["rpcError:%s" % (r.js["error"] or {}).get("code")] += 1
        if not isinstance(res, list):
            break
        sigs += res
        if len(res) < 1000:
            break
        before = res[-1].get("signature")
    bt = [num(s.get("blockTime")) for s in sigs if num(s.get("blockTime"))]
    return {"pages": pages, "n": len(sigs), "exhausted": len(sigs) < pages * 1000, "codes": dict(codes), "secs": round(time.time() - t0, 2),
            "oldestAgeH": round((time.time() - min(bt)) / 3600, 2) if bt else None, "newestAgeMin": round((time.time() - max(bt)) / 60, 1) if bt else None,
            "rl": rl, "_oldest": sigs[-1].get("signature") if sigs else None, "_oldestT": min(bt) if bt else None}


@guarded("c7")
def check7_depth(h, dev, mint, coin, holders):
    out = {}
    created = ts_ms((coin or {}).get("created_timestamp"))
    if dev:
        d = sig_depth(h, dev)
        out["devWallet"] = {k: v for k, v in d.items() if not k.startswith("_")}
        say("[c7] dev wallet getSignaturesForAddress: %s" % json.dumps(out["devWallet"]))
    if mint:
        d = sig_depth(h, mint)
        out["mint"] = {k: v for k, v in d.items() if not k.startswith("_")}
        out["mint"]["oldestVsPfCreatedS"] = round(d["_oldestT"] - created / 1000, 1) if (d["_oldestT"] and created and d["exhausted"]) else None
        say("[c7] mint getSignaturesForAddress: %s" % json.dumps(out["mint"]))
    if holders:
        d = sig_depth(h, holders[0], max_pages=1)
        out["holder"] = {k: v for k, v in d.items() if not k.startswith("_")}
        if d["_oldest"]:
            r = h.rpc("getTransaction", [d["_oldest"], {"maxSupportedTransactionVersion": 0, "encoding": "json"}])
            res = (r.js or {}).get("result") if isinstance(r.js, dict) else None
            msg = ((res or {}).get("transaction") or {}).get("message") or {}
            ak = msg.get("accountKeys") or []
            out["holderOldestTx"] = {**r.brief(), "result": isinstance(res, dict), "fields": keys(res) if isinstance(res, dict) else None,
                                     "accountKeys": len(ak), "feePayerIsHolder": (ak[0] == holders[0]) if ak else None,
                                     "balances": len((res or {}).get("meta", {}).get("preBalances") or []) if isinstance(res, dict) else None}
        say("[c7] holder oldest signature: %s; getTransaction: %s" % (json.dumps(out["holder"]), json.dumps(out.get("holderOldestTx"))))
    R["c7"] = out


@guarded("c7rate")
def check7_rate(h, addrs):
    """Run 1: 10 back-to-back calls passed, the 11th got 429 (retry-after 10) and then every call at a 0.5 s gap for 10 s did too.
    Here: after a 15 s rest, 15 calls at 1.1 s; then back-to-back until the first 429 (at most 30); then one call every 2 s until
    the first 200 (at most 60 s), which measures how long the block lasts."""
    out = {}
    if not addrs:
        R.setdefault("c7", {})["rate"] = {"skipped": "no addresses"}
        return
    call = lambda i, gap: h.rpc("getSignaturesForAddress", [addrs[i % len(addrs)], {"limit": 5}], gap=gap)
    time.sleep(15)
    codes, t0, last = Counter(), time.time(), None
    for i in range(15):
        r = call(i, 1.1)
        codes[str(r.code)] += 1
        last = r
    out["paced11"] = {"calls": 15, "codes": dict(codes), "secs": round(time.time() - t0, 2), "rlLast": rpc_rl(last)}
    say("[c7] paced 1.1 s: %s" % json.dumps(out["paced11"]))
    t0, ok, first429, ra, codes, rls = time.time(), 0, None, None, Counter(), []
    for i in range(30):
        r = call(i, 0.0)
        codes[str(r.code)] += 1
        rls.append(rpc_rl(r).get("method-remaining"))
        if r.code == 429:
            first429, ra = i + 1, r.h.get("retry-after")
            break
        ok += r.code == 200
    secs = time.time() - t0
    out["burst"] = {"calls": sum(codes.values()), "ok": ok, "first429At": first429, "retryAfter": ra, "secs": round(secs, 2),
                    "perSec": round(sum(codes.values()) / secs, 2) if secs else None, "codes": dict(codes), "methodRemaining": rls}
    say("[c7] burst: %s" % json.dumps(out["burst"]))
    if first429:
        t0, n, rec = time.time(), 0, None
        while time.time() - t0 < 60:
            r = call(n, 2.0)
            n += 1
            if r.code == 200:
                rec = round(time.time() - t0, 1)
                break
        out["recovery"] = {"probes": n, "recoveredAfterS": rec, "rl": rpc_rl(r)}
        say("[c7] recovery: %s" % json.dumps(out["recovery"]))
    R.setdefault("c7", {})["rate"] = out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="res")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--cycles", type=int, default=CYCLES)
    ap.add_argument("--cadence", type=float, default=CADENCE)
    ap.add_argument("--budget-s", type=float, default=12.5 * 60)
    a = ap.parse_args()
    start = time.time()
    deadline = start + a.budget_s
    h = Http()
    say("probe-radar: fake money only, public reads only; start", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    check10()
    doc_t = check8(h, a.repo) if a.repo else None
    check1(h, a.res)
    disc = Discovery(h)
    T0 = time.time()
    tgt, fresh, coin, dev, holders, rc_owners, cc = None, False, {}, None, [], [], None
    for k in range(a.cycles):
        t = T0 + k * a.cadence
        if t > deadline - 60:
            say("[c2] cycle %d skipped: run budget" % k)
            break
        time.sleep(max(0.0, t - time.time()))
        disc.run(k)
        if k == 0:
            tgt, fresh = disc.target(4.0)
            say("[c3-6] target: %s, pool age %s min" % ("a pool under 10 min" if fresh else ("a graduated coin (no fresh pool seen)" if tgt else "none"), pool_age_min(disc, tgt) if tgt else None))
            if tgt:
                res3 = check3(h, disc, tgt, fresh)
                if res3:
                    coin, dev = res3
                check4(h, tgt, coin, "target", pool=(disc.cache.get(tgt) or {}).get("pool"))
                cc = disc.curve_coin()
                if cc:
                    check4(h, cc, (disc.info.get(cc) or {}).get("pf"), "curve")
                more = disc.pick(2, 9, 2, want=4.0, skip={tgt})
                rc_owners = check6(h, disc, [("target", tgt)] + [("fresh%d" % (i + 1), a) for i, a in enumerate(more)], "first") or []
        elif k == 1 and tgt:
            coins = [("target", tgt)] + [("curve", cc)] * bool(cc) + [("older", a) for a in disc.pick(30, 240, 1, want=60)] \
                + [("fresh2", a) for a in disc.pick(2, 9, 1, want=4.0, skip={tgt})]
            holders = check5(h, coins, rc_owners) or []
            if not dev and cc:
                dev = addr(((disc.info.get(cc) or {}).get("pf") or {}).get("creator"))
                say("[c7] dev wallet: the curve coin's creator (the target's creator is unknown)")
            check7_depth(h, dev, tgt, coin, holders)
        elif k == 2 and tgt:
            check6(h, disc, [("target", tgt)] + [("older%d" % (i + 1), a) for i, a in enumerate(disc.pick(30, 240, 2, want=90))], "later")
    disc.summary()
    check7_rate(h, [x for x in [dev, tgt] + list(holders) if x])
    if a.repo:
        check9_readonly(h, a.repo, doc_t)
    R["hosts"] = {host: {"n": st["n"], "codes": dict(st["codes"]), "avgMs": int(st["secs"] / st["n"] * 1000) if st["n"] else None} for host, st in sorted(h.stats.items())}
    for host, st in R["hosts"].items():
        say("[hosts] %-28s calls=%d codes=%s avg=%sms" % (host, st["n"], json.dumps(st["codes"]), st["avgMs"]))
    R["secs"] = round(time.time() - start, 1)
    say("PROBE_JSON " + B58_ANY.sub("<addr>", json.dumps(R, separators=(",", ":"), default=str)))


if __name__ == "__main__":
    main()
