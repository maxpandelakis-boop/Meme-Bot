#!/usr/bin/env python3
"""radar_src.py: the launch radar's sources (adapters). Fake money only: the radar rates new coins for the page and the phone, it
never buys anything, and the paper trader never reads what it writes.

launch_radar.py asks these sources once a cycle (every 150 s). Every request runs on RadarHttp, fetch.py's client with the radar's own
rules:
  - the request's timeout is what is left of the cycle's step (none starts after it), so a hanging host never holds a cycle up;
  - a 429 skips that host for the rest of the cycle, then for a cool-down of 2.5, 5, then 10 minutes (a good answer resets it); no wait;
  - fetch's minimum gaps per host (GeckoTerminal 10 s, pump.fun 0.7 s, RPC 0.3 s) hold, but never past the step's end;
  - no answer (a timeout, a refused connection) rests that host for the rest of the cycle; three refusals in a row (401, 403, 410,
    451) give it up for the run.
Every adapter checks the fields it needs on the first answer of each run. When they are missing (the host changed its answer) the
adapter is off for the run, said once, and every signal it feeds stays unknown, never "no". ADAPTERS holds the defaults (the WP0
probe sets them); MEMEBOT_RADAR_ADAPTERS="pf_trades=1,rpc_funding=0" switches single adapters for a run.

The discovery lists go into the cycle's sandbox with fetch.py's own writers and file names (F.write_rows, F.row, pf/graduated.txt,
pf/new.txt, gt/new.txt, jup/recent.txt, ll/llNew.txt, lists.json), so memebot's load_side and gather tag them exactly as in the scan.
Standard library only.
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M
import fetch as F
import radar as RD

ADAPTERS = {               # on/off defaults per adapter; an adapter whose host failed in the probe stays here, off, and self-tests when on
    "pf_graduated": True,  # pump.fun graduated coins, last traded first (pages PAGES)
    "pf_new": True,        # pump.fun newest coins (also the X-link index and the dev launch log)
    "gt_new": True,        # GeckoTerminal new pools, page 1
    "jup_recent": True,    # Jupiter tokens/v2/recent
    "ds_profiles": True,   # DexScreener token-profiles/latest
    "ll_new": True,        # Raydium LaunchLab newest launches
    "ds_tokens": True,     # DexScreener tokens/v1 (pairs, pool age, later prices)
    "rc_report": True,     # RugCheck full report
    "pf_coin": True,       # pump.fun coins/{mint}: mint time, creator, X link of a coin no list carried
    "ds_orders": True,     # DexScreener orders/v1: the paid profile
    "dev_check": True,     # fetch.dev_check: Jupiter's creator facts + RPC: did the creator sell
    "rpc_wallet": True,    # RPC oldest signature of a wallet: dev wallet age, holder freshness
    "rpc_funding": True,   # RPC first transaction of a holder wallet: who funded it
    "rpc_mint": True,      # RPC oldest signature of the mint: mint time of a coin with no launchpad time
    "pf_dev": True,        # pump.fun coins by creator: the dev's earlier launches
    "pf_holders": False,   # pump.fun top holders with sniper / bundler flags (only if the probe shows it answers without login)
    "pf_trades": False,    # pump.fun swap-api trades from the launch (only if the probe shows it answers)
    "gt_candles": True,    # GeckoTerminal minute candles: staircase so far, peak within the hour
}
PAGES = {"pf_graduated": 4, "pf_new": 2}
PF_GRAD = "/coins?offset=%d&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false&complete=true"
PF_NEW = "/coins?offset=%d&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false"
PF_DEV = F.PF + "/coins/user-created-coins/%s?offset=0&limit=50&includeNsfw=false"     # the probe's choice; coins-v2 on advanced-api-v2 is the other
PF_HOLDERS = "https://advanced-api-v2.pump.fun/coins/top-holders/%s"
PF_TRADES = "https://swap-api.pump.fun/v2/coins/%s/trades?limit=100%s"
GH_API = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
REQ_TIMEOUT = 10.0          # s: the most one request waits (less when the step ends sooner)
MIN_LEFT = 0.2              # s: no request starts with less of its step left
COOL = (150.0, 300.0, 600.0)  # s: a host's cool-down after a 429, growing with each one in a row
PUMP_SUPPLY = 1e9           # pump.fun's supply in tokens
HOST_LABEL = {"api.dexscreener.com": "dexscreener", "api.rugcheck.xyz": "rugcheck", "frontend-api-v3.pump.fun": "pump.fun",
              "api.geckoterminal.com": "geckoterminal", "api.mainnet-beta.solana.com": "rpc", "lite-api.jup.ag": "jupiter",
              "launch-mint-v1.raydium.io": "launchlab", "swap-api.pump.fun": "pump.fun trades", "advanced-api-v2.pump.fun": "pump.fun holders"}
ADAPTER_HOST = {"pf_graduated": "frontend-api-v3.pump.fun", "pf_new": "frontend-api-v3.pump.fun", "pf_coin": "frontend-api-v3.pump.fun",
                "pf_dev": "frontend-api-v3.pump.fun", "gt_new": "api.geckoterminal.com", "gt_candles": "api.geckoterminal.com",
                "jup_recent": "lite-api.jup.ag", "dev_check": "lite-api.jup.ag", "ds_profiles": "api.dexscreener.com", "ds_tokens": "api.dexscreener.com",
                "ds_orders": "api.dexscreener.com", "ll_new": "launch-mint-v1.raydium.io", "rc_report": "api.rugcheck.xyz",
                "rpc_wallet": "api.mainnet-beta.solana.com", "rpc_funding": "api.mainnet-beta.solana.com", "rpc_mint": "api.mainnet-beta.solana.com",
                "pf_holders": "advanced-api-v2.pump.fun", "pf_trades": "swap-api.pump.fun"}


def adapters_from_env(base=None):
    """The adapter switches for this run: the defaults, then MEMEBOT_RADAR_ADAPTERS ("name=0,name=1"; unknown names are ignored)."""
    on = dict(base or ADAPTERS)
    for part in (os.environ.get("MEMEBOT_RADAR_ADAPTERS") or "").split(","):
        k, _, v = part.strip().partition("=")
        if k in on and v.strip() in ("0", "1"):
            on[k] = v.strip() == "1"
    return on


def short(e):
    """An error in a few words for the log: no URL (a remote's credentials never show), at most 80 characters."""
    return re.sub(r"\s+", " ", re.sub(r"\w+://\S+", "(address)", "%s %s" % (type(e).__name__, e)))[:80]


class RadarHttp(F.Http):
    """fetch's pacing, counters and per-host locks with the radar's request rules (module docstring). Single-threaded use.
    code: the last request's HTTP status (None: no answer; "skip": not sent: the host is cooling down or given up, or the step's time
    is up). heard: the URLs that got a real answer this cycle (JSON, or a 404). The per-cycle budgets: rpc_left (Solana RPC calls)."""

    def __init__(self, mock=None, pause=0.0, log=None):
        F.Http.__init__(self, mock, pause, log)
        self.until, self.code, self.heard, self.hit429, self.asked, self.mute = None, None, set(), set(), {}, set()
        self.cool, self.level, self.said = {}, {}, set()
        self.rpc_left = None

    def new_cycle(self, until, rpc_cap=None):
        self.until, self.heard, self.hit429, self.asked, self.rpc_left, self.mute = until, set(), set(), {}, rpc_cap, set()

    def blocked(self, host):
        return host in self.dead or host in self.hit429 or host in self.mute or self.cool.get(host, 0.0) > time.time()

    def state(self, host):
        """ok / limited / down / unused for the page's host list (this cycle)."""
        if host in self.dead or host in self.mute:
            return "down"
        if host in self.hit429 or self.cool.get(host, 0.0) > time.time():
            return "limited"
        return "ok" if self.asked.get(host) else "unused"

    def _say_once(self, key, s):
        if key not in self.said:
            self.said.add(key)
            self.log(s)

    def _send(self, u, data=None, headers=None, method=None, until=None):
        """One request: (status, body bytes); status None when no answer came, "skip" when none was sent."""
        host = urllib.parse.urlsplit(u).netloc
        self.code = "skip"
        if self.blocked(host):
            return "skip", None
        end = until or self.until or (time.time() + REQ_TIMEOUT)
        gap = F.HOST_GAP.get(host, 0.0) if not self.mock else 0.0
        if end - time.time() < MIN_LEFT or (gap and host in self.last_at and self.last_at[host] + gap > end - 1.0):
            return "skip", None              # the step's time is up (a paced host would wait past it): asked again next cycle
        self._pace(host)
        left = end - time.time()
        if left < MIN_LEFT:
            return "skip", None
        self.asked[host] = self.asked.get(host, 0) + 1
        hdr = {"User-Agent": F.UA, "Accept": "application/json, text/xml, */*"}
        hdr.update(headers or {})
        try:
            req = urllib.request.Request(self.url(u), data=data, headers=hdr, method=method)
            with urllib.request.urlopen(req, timeout=min(REQ_TIMEOUT, left)) as r:
                raw, status = r.read(4_000_000), getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            status, raw = e.code, b""
        except Exception as e:                # no answer (a timeout, a refused or reset connection): the host rests for the rest of this cycle
            self.code = None                  # (a timeout may be the step's own end); it is asked again next cycle, never given up for the run
            self._say_once("noanswer:%s" % host, "  ! %s: no answer (%s): skipped for the rest of the cycle" % (host, short(e)))
            self.mute.add(host)
            return None, None
        self.code = status
        if status == 429:
            k = min(self.level.get(host, 0), len(COOL) - 1)
            self.level[host] = k + 1
            self.cool[host] = time.time() + COOL[k]
            self.hit429.add(host)
            with self.lock:
                self.limited += 1
                self.limited_by[host] = self.limited_by.get(host, 0) + 1
            self.log("  ! 429 rate limited by %s: skipped for %.1f min" % (host, COOL[k] / 60.0))
            return 429, None
        if status in (401, 403, 410, 451):
            self._say_once("hard%d:%s" % (status, host), "  ! %s answered %d" % (host, status))
            self._fail(host, hard=True)
            return status, None
        if status >= 400:
            if status == 404:
                self.heard.add(u)
            return status, None
        with self.lock:
            self.fails[host] = 0
        self.level[host] = 0
        if self.pause:
            time.sleep(self.pause)
        return status, raw

    def get(self, u, kind="json", headers=None, tries=1, until=None):
        _, raw = self._send(u, headers=headers, until=until)
        if raw is None:
            return None
        text = raw.decode("utf-8", "replace")
        if kind != "json":
            self.heard.add(u)
            return text
        try:
            out = json.loads(text) if text.strip() else None
        except ValueError:
            self._say_once("nonjson:%s" % urllib.parse.urlsplit(u).netloc, "  ! %s answered with something that is not JSON" % urllib.parse.urlsplit(u).netloc)
            return None
        self.heard.add(u)
        return out

    def post(self, u, payload, tries=1, headers=None, until=None):
        """JSON-RPC POST. The Solana RPC counts against rpc_left (None: no cap); a 429 inside a 200 is a 429."""
        host = urllib.parse.urlsplit(u).netloc
        if host == urllib.parse.urlsplit(F.RPC).netloc and self.rpc_left is not None:
            if self.rpc_left <= 0:
                self.code = "skip"
                return None
            self.rpc_left -= 1
        _, raw = self._send(u, data=json.dumps(payload).encode("utf-8"), headers=dict({"Content-Type": "application/json"}, **(headers or {})),
                                 method="POST", until=until)
        if raw is None:
            return None
        try:
            out = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None
        if isinstance(out, dict) and isinstance(out.get("error"), dict) and out["error"].get("code") == 429:
            k = min(self.level.get(host, 0), len(COOL) - 1)
            self.level[host] = k + 1
            self.cool[host] = time.time() + COOL[k]
            self.hit429.add(host)
            self.code = 429
            self.log("  ! 429 rate limited by %s: skipped for %.1f min" % (host, COOL[k] / 60.0))
            return None
        return out

    def api(self, method, path, body=None, token=None, until=None):
        """One GitHub REST call (GITHUB_API_URL, the token in the Authorization header only, never logged): (status, JSON or None)."""
        hdr = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            hdr["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            hdr["Content-Type"] = "application/json"
        status, raw = self._send(GH_API + path, data=data, headers=hdr, method=method, until=until)
        if raw is None or not raw.strip():
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return status, None


def ms_of(v):
    """Milliseconds from a number (s or ms) or an ISO date (memebot's parse_ms), as an int, else None."""
    x = M.parse_ms(v)
    return int(x) if x else None


class Sources:
    """The adapters of one run: their on/off switches (shape checks), and one method per source. log: a function for progress lines."""

    def __init__(self, http, log, on=None):
        self.http, self.log = http, log
        self.on = dict(on) if on is not None else adapters_from_env()
        self.checked, self.off_why = set(), {}

    def use(self, name):
        return bool(self.on.get(name))

    def shape(self, name, ok, what):
        """The first answer of each run decides: the adapter stays on when its fields are there, else it is off for the run (said once).
        Later answers that miss the fields are only skipped. Returns ok."""
        if ok:
            self.checked.add(name)
            return True
        if name not in self.checked and self.on.get(name):
            self.on[name] = False
            self.off_why[name] = what
            self.log("  ! %s: the answer has no %s: off for this run" % (name, what))
        return False

    # ---------------------------------------------------------------- discovery
    def pf_list(self, sb, name, path, pages, meta, now=None):
        """pump.fun coin lists -> <sb>/pf/<name>.txt (fetch.pf_coins' rows); each coin's facts (mint time, creator, X link, graduated,
        PumpSwap pool) into meta."""
        key = "pf_" + name
        rows, h = [], self.http
        for pg in range(pages):
            data = h.get(F.PF + path % (pg * 50))
            if data is None:
                break
            if not self.shape(key, isinstance(data, list) and (not data or (isinstance(data[0], dict) and "mint" in data[0] and "created_timestamp" in data[0])),
                              "list of coins with mint and created_timestamp"):
                break
            for c in data:
                a = F.addr_of((c or {}).get("mint"))
                if not a:
                    continue
                rows.append(F.row(a, c.get("symbol"), c.get("name"), F.num(c.get("usd_market_cap")), F.num(c.get("market_cap")), F.num(c.get("ath_market_cap")),
                                  F.num(c.get("reply_count")), bool(c.get("is_currently_live")), bool(c.get("complete")), F.num(c.get("created_timestamp")),
                                  F.txt(c.get("twitter"), 100) if c.get("twitter") else None, F.txt(c.get("website"), 100) if c.get("website") else None,
                                  F.txt(c.get("telegram"), 100) if c.get("telegram") else None))
                meta[a] = pf_facts(c, meta.get(a), now)
            if len(data) < 50:
                break
        return F.write_rows(sb, "pf", name + ".txt", rows)

    def discover(self, sb, meta, now=None):
        """Every discovery list into the sandbox; lists.json with the DexScreener profiles and LaunchLab's newest. Returns {tag: count}."""
        os.makedirs(sb, exist_ok=True)
        h, n, lists = self.http, {}, {}
        if self.use("pf_graduated"):
            n["pf:graduated"] = self.pf_list(sb, "graduated", PF_GRAD, PAGES["pf_graduated"], meta, now)
        if self.use("pf_new"):
            n["pf:new"] = self.pf_list(sb, "new", PF_NEW, PAGES["pf_new"], meta, now)
        if self.use("gt_new"):
            data = h.get(F.GT + "/networks/solana/new_pools?include=base_token&page=1")
            if data is not None and self.shape("gt_new", isinstance(data, dict) and isinstance(data.get("data"), list), "data list"):
                n["gt:new"] = F.write_rows(sb, "gt", "new.txt", F.gt_rows(data))
        if self.use("jup_recent"):
            data = h.get(F.JUP + "/recent")
            if data is not None and self.shape("jup_recent", isinstance(data, list) and (not data or (isinstance(data[0], dict) and "id" in data[0])), "list of tokens with id"):
                n["jup:recent"] = F.write_rows(sb, "jup", "recent.txt", [r for r in (jup_row(t) for t in data) if r])
        if self.use("ds_profiles"):
            data = h.get(F.DS + "/token-profiles/latest/v1")
            if isinstance(data, dict):
                data = data.get("items") or data.get("data") or []
            if data is not None and self.shape("ds_profiles", isinstance(data, list), "list"):
                lists["profiles"] = list(dict.fromkeys(a for a in (F.addr_of(it.get("tokenAddress") or it.get("address")) for it in data
                                                                     if isinstance(it, dict) and str(it.get("chainId") or "").lower() == "solana") if a))
                n["list:profiles"] = len(lists["profiles"])
        if self.use("ll_new"):
            data = h.get(F.LL + "/get/list?sort=new&size=100&mintType=default&includeNsfw=false")
            rows_in = ((data or {}).get("data") or {}).get("rows") if isinstance(data, dict) else None
            if data is not None and self.shape("ll_new", isinstance(rows_in, list), "data.rows"):
                rows, addrs = [], []
                for c in rows_in:
                    a = F.addr_of((c or {}).get("mint"))
                    if not a:
                        continue
                    mc = next((F.num(c.get(k)) for k in ("marketCap", "usdMarketCap", "mcap") if c.get(k) is not None), None)
                    vol = next((F.num(c.get(k)) for k in ("volumeU", "volume24h", "volume") if c.get(k) is not None), None)
                    created = next((c.get(k) for k in ("createAt", "createdAt", "createTime") if c.get(k) is not None), None)
                    rows.append(F.row(a, c.get("symbol"), c.get("name"), F.addr_of(c.get("creator")), mc, vol, created, c.get("poolId"),
                                      bool(c.get("finishingRate") == 1 or c.get("migrated"))))
                    addrs.append(a)
                    meta.setdefault(a, {}).update({k: v for k, v in (("t", ms_of(created)), ("creator", F.addr_of(c.get("creator"))), ("lp", "LaunchLab"), ("seen", now)) if v})
                F.write_rows(sb, "ll", "llNew.txt", rows)
                lists["llNew"] = addrs
                n["ll:llNew"] = len(addrs)
        F.write_json(sb, "lists.json", lists)
        return n

    # ---------------------------------------------------------------- DexScreener
    def ds_tokens(self, sb, addrs, max_req, prefix="radar"):
        """DexScreener tokens/v1 for addrs (30 a request, radar.ds_chunk) -> <sb>/pairs/<prefix>_NNN.txt. Returns (answered addresses,
        requests). An address in a request that got no proper answer is not answered: nothing is known about it, not even that it is gone."""
        answered, nreq = set(), 0
        if not self.use("ds_tokens"):
            return answered, nreq
        for i in range(0, len(addrs), 30):
            if nreq >= max_req or self.http.blocked("api.dexscreener.com"):
                break
            chunk = addrs[i:i + 30]
            nreq += 1
            got = RD.ds_chunk(self.http, sb, chunk, "%s_%03d.txt" % (prefix, i // 30))
            if got is not None:
                answered.update(chunk)
            elif self.http.code == 200:
                self.shape("ds_tokens", False, "list of pairs")
        return answered, nreq

    def ds_paid(self, sb, addrs):
        """DexScreener orders/v1 (fetch.ds_orders) -> {addr: paid profile true/false} for the coins it answered."""
        if not addrs or not self.use("ds_orders"):
            return {}
        F.ds_orders(self.http, sb, addrs)
        rows, _ = M.load_side(sb, "dp", M.DP_COLS)
        return {a: bool(r.get("paid")) for a, r in rows.items() if r.get("paid") is not None}

    # ---------------------------------------------------------------- RugCheck
    def rc_report(self, mint):
        """(status, report): "ok" with the report trimmed to what the radar reads, "404" (no report yet), "429", "err" or "skip"."""
        if not self.use("rc_report"):
            return "off", None
        rep = self.http.get(F.RC + "/tokens/%s/report" % mint)
        code = self.http.code
        if isinstance(rep, dict):
            if not self.shape("rc_report", rep.get("risks") is not None or rep.get("score") is not None, "risks or score"):
                return "err", None
            return "ok", rc_trim(rep)
        if code == 404:
            return "404", None
        if code == 429:
            return "429", None
        return ("skip" if code == "skip" else "err"), None

    # ---------------------------------------------------------------- pump.fun
    def pf_coin(self, mint, meta, now=None):
        """pump.fun coins/{mint}: the coin's mint time, creator and X link into meta. True when it answered."""
        if not self.use("pf_coin"):
            return False
        c = self.http.get(F.PF + "/coins/%s" % mint)
        if c is None or not self.shape("pf_coin", isinstance(c, dict) and "mint" in c, "mint"):
            return False
        meta[mint] = pf_facts(c, meta.get(mint), now)
        return True

    def pf_dev(self, creator, now):
        """The dev's earlier pump.fun launches: {"n", "dead", "grad"} (dead: never graduated, under $10k and older than an hour), or None."""
        if not self.use("pf_dev"):
            return None
        data = self.http.get(PF_DEV % creator)
        if isinstance(data, dict):
            data = data.get("coins") if isinstance(data.get("coins"), list) else data.get("data")
        if data is None or not self.shape("pf_dev", isinstance(data, list) and (not data or isinstance(data[0], dict)), "list of coins"):
            return None
        n = dead = grad = 0
        for c in data:
            if not isinstance(c, dict):
                continue
            n += 1
            t = ms_of(c.get("created_timestamp"))
            if c.get("complete"):
                grad += 1
            elif (F.num(c.get("usd_market_cap")) or 0) < 10_000 and t and now - t > 3_600_000:
                dead += 1
        return {"n": n, "dead": dead, "grad": grad}

    def pf_holders(self, mint):
        """pump.fun top holders with its sniper / bundler / dev flags: {"snipN", "snipPct", "bundN", "bundPct"} or None."""
        if not self.use("pf_holders"):
            return None
        data = self.http.get(PF_HOLDERS % mint)
        top = data.get("topHolders") if isinstance(data, dict) else (data if isinstance(data, list) else None)
        if data is None or not self.shape("pf_holders", isinstance(top, list), "topHolders"):
            return None
        amt = lambda h: F.num(h.get("amount")) or 0.0
        tot = sum(amt(h) for h in top if isinstance(h, dict))
        scale = PUMP_SUPPLY * (1e6 if tot > PUMP_SUPPLY * 10 else 1.0)
        sn = [h for h in top if isinstance(h, dict) and h.get("isSniper")]
        bn = [h for h in top if isinstance(h, dict) and h.get("isBundler")]
        return {"snipN": len(sn), "snipPct": sum(amt(h) for h in sn) / scale, "bundN": len(bn), "bundPct": sum(amt(h) for h in bn) / scale}

    def pf_trades(self, mint, pages=3):
        """The coin's first trades (pump.fun swap-api, newest first, at most `pages` pages): {"snip30", "snip30N", "slotN", "slotPct"},
        or {"many": True} when the launch lies further back than the pages reach, or None."""
        if not self.use("pf_trades"):
            return None
        rows, cursor = [], ""
        for _ in range(pages):
            data = self.http.get(PF_TRADES % (mint, ("&cursor=" + urllib.parse.quote(cursor)) if cursor else ""))
            if data is None or not self.shape("pf_trades", isinstance(data, dict) and isinstance(data.get("trades"), list), "trades"):
                return None
            rows += [r for r in data["trades"] if isinstance(r, dict)]
            pg = data.get("pagination") or {}
            cursor = pg.get("nextCursor") or ""
            if not pg.get("hasMore") or not cursor:
                break
        else:
            return {"many": True}
        buys = []
        for r in rows:
            t = ms_of(r.get("timestamp"))
            if t and str(r.get("type") or "").lower() == "buy":
                slot = str(r.get("slotIndexId") or "")[:12]
                buys.append((t, slot, str(r.get("userAddress") or ""), F.num(r.get("baseAmount")) or 0.0))
        if not buys:
            return None
        buys.sort()
        t0, s0 = buys[0][0], min(b[1] for b in buys if b[1]) if any(b[1] for b in buys) else ""
        tot = sum(b[3] for b in buys)
        scale = PUMP_SUPPLY * (1e6 if tot > PUMP_SUPPLY * 10 else 1.0)
        first = [b for b in buys if b[0] - t0 <= 30_000]
        slot = [b for b in buys if s0 and b[1] == s0]
        return {"snip30": sum(b[3] for b in first) / scale, "snip30N": len({b[2] for b in first}),
                "slotN": len({b[2] for b in slot}) if s0 else None, "slotPct": (sum(b[3] for b in slot) / scale) if s0 else None}

    # ---------------------------------------------------------------- Solana RPC (public node, a capped number of calls a cycle)
    def rpc(self, name, method, params):
        if not self.use(name):
            return None
        out = self.http.post(F.RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if out is None:
            return None
        if not self.shape(name, isinstance(out, dict) and "result" in out, "JSON-RPC result"):
            return None
        return out.get("result")

    def wallet_age(self, wallet):
        """A wallet's oldest signature among its last 1,000: {"first": ms or None, "n": signatures, "full": 1,000 or more, "sig": the oldest},
        or None (no answer)."""
        res = self.rpc("rpc_wallet", "getSignaturesForAddress", [wallet, {"limit": 1000}])
        if not isinstance(res, list):
            return None
        ok = [x for x in res if isinstance(x, dict) and F.num(x.get("blockTime"))]
        old = min(ok, key=lambda x: x["blockTime"]) if ok else None
        return {"first": int(old["blockTime"] * 1000) if old else None, "n": len(res), "full": len(res) >= 1000, "sig": old.get("signature") if old else None}

    def funder(self, wallet, sig):
        """Who funded a wallet: the source of a transfer to it in its oldest transaction, else that transaction's fee payer when it is
        another wallet: {"by": wallet or None, "at": ms}, or None (no answer)."""
        if not sig:
            return None
        res = self.rpc("rpc_funding", "getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not isinstance(res, dict):
            return None
        at = int(F.num(res.get("blockTime")) * 1000) if F.num(res.get("blockTime")) else None
        msg = ((res.get("transaction") or {}).get("message") or {}) if isinstance(res.get("transaction"), dict) else {}
        by = None
        for ins in msg.get("instructions") or []:
            p = (ins or {}).get("parsed") if isinstance(ins, dict) else None
            info = (p or {}).get("info") if isinstance(p, dict) else None
            if isinstance(info, dict) and info.get("destination") == wallet and F.addr_of(info.get("source")):
                by = info["source"]
                break
        if not by:
            keys = msg.get("accountKeys") or []
            k0 = keys[0] if keys else None
            k0 = k0.get("pubkey") if isinstance(k0, dict) else k0
            if F.addr_of(k0) and k0 != wallet:
                by = k0
        return {"by": by, "at": at}

    def mint_time(self, mint, calls=3):
        """The mint's oldest signature (its creation) when the last `calls` pages of 1,000 signatures reach back to it, else None."""
        before = None
        for _ in range(calls):
            opt = {"limit": 1000}
            if before:
                opt["before"] = before
            res = self.rpc("rpc_mint", "getSignaturesForAddress", [mint, opt])
            if not isinstance(res, list):
                return None
            if len(res) < 1000:
                ts = [F.num(x.get("blockTime")) for x in res if isinstance(x, dict) and F.num(x.get("blockTime"))]
                return int(min(ts) * 1000) if ts else None
            before = (res[-1] or {}).get("signature")
            if not before:
                return None
        return None

    # ---------------------------------------------------------------- GeckoTerminal minute candles
    def candles(self, pool, since, until_ms):
        """One-minute candles of a pool from since to until_ms (ms): [[ms, open, high, low, close, volume], ...] oldest first, or None."""
        if not self.use("gt_candles") or not pool:
            return None
        lim = max(2, min(100, int((until_ms - since) / 60_000) + 3))
        j = self.http.get(F.GT + "/networks/solana/pools/%s/ohlcv/minute?aggregate=1&limit=%d&before_timestamp=%d&currency=usd&token=base" % (pool, lim, int(until_ms / 1000)))
        lst = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") if isinstance(j, dict) else None
        if j is None or not self.shape("gt_candles", isinstance(lst, list), "data.attributes.ohlcv_list"):
            return None
        out = []
        for c in lst:
            if isinstance(c, list) and len(c) >= 5 and F.num(c[0]) and since - 60_000 <= F.num(c[0]) * 1000 <= until_ms:
                out.append([int(F.num(c[0]) * 1000)] + [F.num(x) for x in c[1:6]] + [None] * (6 - len(c[1:6])))
        out.sort(key=lambda c: c[0])
        return out


def pf_facts(c, prev=None, now=None):
    """A pump.fun coin's facts the radar keeps: mint time, creator, X / website / Telegram links, graduated, PumpSwap pool, and when a
    list last carried it (seen)."""
    out = dict(prev or {})
    if now:
        out["seen"] = int(now)
    for k, v in (("t", ms_of(c.get("created_timestamp"))), ("creator", F.addr_of(c.get("creator"))), ("x", c.get("twitter")), ("web", c.get("website")),
                 ("tg", c.get("telegram")), ("pool", F.addr_of(c.get("pump_swap_pool"))), ("sym", c.get("symbol")), ("name", c.get("name"))):
        if v:
            out[k] = str(v)[:200] if isinstance(v, str) else v
    out["done"] = bool(c.get("complete"))
    out["lp"] = "pump.fun"
    return out


def jup_row(t):
    """A Jupiter token as fetch.jup_tokens writes it (28 fields)."""
    a = F.addr_of((t or {}).get("id") or (t or {}).get("address")) if isinstance(t, dict) else None
    if not a:
        return None
    au, s1, s24 = t.get("audit") or {}, t.get("stats1h") or {}, t.get("stats24h") or {}
    return F.row(a, t.get("symbol"), t.get("name"), F.num(t.get("usdPrice")), F.num(t.get("mcap")), F.num(t.get("fdv")), F.num(t.get("liquidity")),
                 F.num(t.get("holderCount")), F.num(t.get("organicScore")), F.num(au.get("topHoldersPercentage")), F.num(au.get("devMigrations")),
                 bool(t.get("isVerified")), (t.get("firstPool") or {}).get("createdAt"), F.num(s1.get("priceChange")), F.num((t.get("stats6h") or {}).get("priceChange")),
                 F.num(s24.get("priceChange")), F.num(s24.get("buyVolume")), F.num(s24.get("sellVolume")), F.num(s24.get("numBuys")), F.num(s24.get("numSells")),
                 F.num(s24.get("numTraders")), F.num(s24.get("numNetBuyers")), F.num(s24.get("holderChange")), F.num(s1.get("numBuys")), F.num(s1.get("numSells")),
                 F.num(s1.get("numNetBuyers")), F.num(s1.get("buyVolume")), F.num(s1.get("sellVolume")))


def rc_trim(rep):
    """A RugCheck report cut to the fields the radar and fetch.rc_row read (a full report is tens of KB): risks, scores, top holders,
    insider network size, creator, the creator's other tokens, supply and creator balance, LP lock, holders, mutability, launchpad."""
    top = []
    for h in (rep.get("topHolders") or [])[:20]:
        if isinstance(h, dict):
            top.append({"owner": h.get("owner") or h.get("address"), "pct": F.num(h.get("pct")), "insider": bool(h.get("insider"))})
    ct, lp = rep.get("creatorTokens"), rep.get("launchpad")
    out = {"risks": [{"name": str(r.get("name") or "")[:80], "level": str(r.get("level") or "")[:12]} for r in (rep.get("risks") or []) if isinstance(r, dict)][:30],
           "score": rep.get("score"), "score_normalised": rep.get("score_normalised"), "topHolders": top,
           "graphInsidersDetected": rep.get("graphInsidersDetected"), "creator": F.addr_of(rep.get("creator")),
           "creatorTokens": [{"mint": F.addr_of((t or {}).get("mint")), "marketCap": F.num((t or {}).get("marketCap")), "createdAt": (t or {}).get("createdAt")}
                             for t in ct if isinstance(t, dict)][:50] if isinstance(ct, list) else None,
           "token": {"supply": F.num((rep.get("token") or {}).get("supply"))} if isinstance(rep.get("token"), dict) else {},
           "creatorBalance": rep.get("creatorBalance"), "totalHolders": rep.get("totalHolders"),
           "tokenMeta": {"mutable": (rep.get("tokenMeta") or {}).get("mutable")} if isinstance(rep.get("tokenMeta"), dict) else {},
           "markets": [{"lp": {"lpLockedPct": F.num(((m or {}).get("lp") or {}).get("lpLockedPct"))}} for m in (rep.get("markets") or []) if isinstance(m, dict)][:6],
           "launchpad": str(lp.get("name") if isinstance(lp, dict) else lp)[:40] if lp else None}
    return out
