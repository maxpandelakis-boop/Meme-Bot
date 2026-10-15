#!/usr/bin/env python3
"""radar_src.py: the launch radar's sources (adapters). Fake money only: the radar rates new coins for the page and the phone, it
never buys anything, and the paper trader never reads what it writes.

launch_radar.py asks these sources once a cycle (one cycle per round; a VM's loop every 150 s). Every request runs on RadarHttp,
fetch.py's client with the radar's own rules (the limits measured by the WP0 probe on GitHub's runners, research/probe-radar.md):
  - the request's timeout is what is left of the cycle's step (none starts after it), so a hanging host never holds a cycle up;
  - minimum gaps per host (GAPS: fetch's GeckoTerminal 10 s, pump.fun 0.7 s and X's tweet endpoint 1.5 s, RugCheck 1 s, swap-api 0.2 s,
    advanced-api 1 s) hold,
    but never past the step's end; the Solana RPC also keeps RPC_GAP_S (1.1 s) between two calls of one method, because its real limit
    is 10 calls per method per 10 s (a sliding window per IP; fetch's 0.3 s gap is too fast for more than 10 calls in a row);
  - a 429 skips that host for the rest of the cycle, then for a cool-down of 2.5, 5, then 10 minutes (a good answer resets it); no wait.
    Two hosts have their own ladder (COOL_HOST): GeckoTerminal cools 15, 30, then 60 s and is asked again later in the same cycle (its
    429s are short: retry-after 0), the RPC is skipped for the rest of the cycle only (retry-after 10 s, the block lifts within seconds);
  - no answer (a timeout, a refused connection) rests that host for the rest of the cycle; three refusals in a row (401, 403, 410,
    451) give it up for the run.
Every adapter checks the fields it needs on the first answer of each run. When they are missing (the host changed its answer) the
adapter is off for the run, said once, and every signal it feeds stays unknown, never "no". ADAPTERS holds the defaults, as the WP0
probe set them; MEMEBOT_RADAR_ADAPTERS="swap_trades=0,ll_new=1" switches single adapters for a run.

The probe's other entries are not switches of this package; NOT_HERE says why for each (not built here, or another package's).

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

ADAPTERS = {               # on/off defaults per adapter (names and values from the WP0 probe); an adapter that is off stays in code
    # discovery, every cycle                                                                and self-tests when it is switched on
    "pf_graduated": True,         # pump.fun graduated coins, last traded first, pages 1-4: 17 of 23 fresh pools in the probe, 5 sole
    "pf_new": True,               # pump.fun newest coins, pages 1-2: 8 of 23; also the X-link index and the dev launch log
    "gt_new_pools": True,         # GeckoTerminal new pools, pages 1-2: 7 of 23, 3 sole
    "jup_recent": True,           # Jupiter tokens/v2/recent: 3 of 23, 3 sole, the earliest; carries the mint time (createdAt) and the dev
    "ds_profiles": True,          # DexScreener token-profiles/latest: 3 of 23, none sole; one call, kept for the paid-profile signal
    "ll_new": False,              # Raydium LaunchLab newest: no fresh pool in 8 cycles (its coins are still on the curve)
    "ds_tokens": True,            # DexScreener tokens/v1 (pairs, pool age, later prices): the radar cannot work without it
    # tier 1
    "rc_report": True,            # RugCheck report: 200 on 8 of 8, a report is there for pools 2-10 min old
    "rc_insider_networks": True,  # the report's insiderNetworks[].size, the chip's network size (filled on 3 of 8; 0 or null = none found);
                                  # graphInsidersDetected is read either way (fetch.rc_row, the study's holder_cluster)
    "rc_creator_tokens": False,   # the report's creatorTokens: null in 8 of 8, the dev history comes from pump.fun
    "pf_coin_v3": True,           # pump.fun coins-v3/{mint} for a coin no list carried (coins/{mint} is gone: "Cannot GET")
    "ds_orders": True,            # DexScreener orders/v1: the paid profile (as fetch.py does today)
    # tier 2
    "dev_check": True,            # fetch.dev_check: Jupiter's creator facts + RPC: did the creator sell (as the scan does today)
    "pf_dev_history": True,       # pump.fun coins?creator=<dev> (a strict filter, about a year back) + coins-v2 user-created-coins count
    "pf_top_holders": True,       # pump.fun coins/top-holders (frontend-api-v3, advanced-api-v2 the fallback): enteredAt, amount, isBundler
    "pf_holder_flags": False,     # isSniper / isDev / fundingSource: never filled without a login, so never read (never as "no")
    "swap_trades": True,          # swap-api trades, 100 a page, newest first: the launch only when 3 pages reach it, else not checked
    "swap_candles": True,         # swap-api 1-minute candles from the mint minute (the curve phase included), oldest first
    "rpc_dev_age": True,          # RPC getSignaturesForAddress(dev): the dev wallet's age in one call
    "rpc_holder_age": True,       # one call a top-10 holder: under 1,000 signatures gives the age, 1,000 with an old oldest = not fresh
    "rpc_funding": True,          # getTransaction(oldest signature) of fresh holders only, at most FUND_CAP a cycle: who funded them
    "rpc_mint_time": True,        # the mint's oldest signature: the last fallback for the mint time, at most 3 pages, else unknown
    "gt_candles": True,           # GeckoTerminal minute candles: staircase so far of other pools, the peak within the hour
    "x_tweet": True,              # X's public tweet facts (fetch.viral's syndication endpoint, no key): the likes of the tweet a coin
                                  # launched off (viral_tweet, measured only), launch_radar.TWEET_CAP a cycle; not in the probe (radar only)
}
NOT_HERE = {               # the probe's other ADAPTERS entries: not switches of the radar, and why
    "rc_new_tokens": "not built: RugCheck new_tokens listed 1 of 23 fresh pools, never one nobody else had; RugCheck's budget stays with the reports",
    "pf_wallet_overview": "not built: POST wallet-overview answered 530 on advanced-api-v2 and 404 on frontend-api-v3; holder age and funding come from the RPC",
    "pf_advanced_coin": "not built: advanced-api-v2's coin routes answered 530; coins-v3 and coins-v2 come from frontend-api-v3 (advanced-api-v2 only as "
                        "the top-holders fallback, inside pf_top_holders)",
    "gt_m1_backfill": "peak.py (WP2): the backfill of the peak windows",
    "gh_contents_poll": "the page (WP5b): every request counts against the 60 an hour, a 304 too",
    "raw_fallback": "the page (WP5b): raw.githubusercontent.com is up to 5 minutes old whatever the query",
    "supabase": "the smoke test (WP6); the radar writes its app row whenever the secrets are set",
}
PAGES = {"pf_graduated": 4, "pf_new": 2, "gt_new_pools": 2}
FRESH_MS = 10 * 60_000      # GeckoTerminal's page 2 is asked only when page 1's oldest pool is younger than this (else none there is fresh)
PF_GRAD = "/coins?offset=%d&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false&complete=true"
PF_NEW = "/coins?offset=%d&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false"
PF_COIN = F.PF + "/coins-v3/%s"
PF_BY_CREATOR = F.PF + "/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false&creator=%s"
PF_DEV_COUNT = F.PF + "/coins-v2/user-created-coins/%s?offset=0&limit=50"
ADV = "https://advanced-api-v2.pump.fun"
PF_HOLDERS = (F.PF + "/coins/top-holders/%s", ADV + "/coins/top-holders/%s")
SWAP = "https://swap-api.pump.fun"
PF_TRADES = SWAP + "/v2/coins/%s/trades?limit=100%s"
PF_CANDLES = SWAP + "/v1/coins/%s/candles?interval=1m&limit=100&currency=USD"
PF_WEB = {"Origin": "https://pump.fun", "Referer": "https://pump.fun/"}      # as the probe asked swap-api, top-holders and coins-v2
GH_API = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
REQ_TIMEOUT = 10.0          # s: the most one request waits (less when the step ends sooner)
MIN_LEFT = 0.2              # s: no request starts with less of its step left
ANSWER_MAX = 4_000_000      # bytes of one answer read at most (the rest is not read)
COOL = (150.0, 300.0, 600.0)  # s: a host's cool-down after a 429, growing with each one in a row
RPC_HOST = urllib.parse.urlsplit(F.RPC).netloc
GT_HOST = urllib.parse.urlsplit(F.GT).netloc
GT_429_LADDER_S = (15.0, 30.0, 60.0)
RPC_GAP_S = 1.1             # s between two RPC calls of one method (10 per method per 10 s, sliding)
RPC_RETRY_S = 10.0          # the RPC's retry-after
COOL_HOST = {GT_HOST: GT_429_LADDER_S, RPC_HOST: (RPC_RETRY_S,)}
CYCLE_SKIP = {RPC_HOST}     # hosts with their own ladder that a 429 still skips for the rest of the cycle (GeckoTerminal only cools)
XTW_HOST = urllib.parse.urlsplit(F.XTW).netloc     # cdn.syndication.twimg.com: one tweet's likes by id (fetch.viral's endpoint)
TWEET_ID = re.compile(r"[1-9][0-9]{0,24}")         # a tweet id X can be asked about: ASCII digits only (the first tweet is id 20), no
                                                   # leading zero; traps.norm_x's isdigit() also passes other scripts' digits, which
                                                   # urllib cannot put in a URL (the request would fail unsent and mute the host)
GAPS = dict(F.HOST_GAP, **{"api.rugcheck.xyz": 1.0, "swap-api.pump.fun": 0.2, "advanced-api-v2.pump.fun": 1.0})   # fetch's X tweet gap: 1.5 s
PUMP_SUPPLY = 1e9           # pump.fun's supply in tokens
HOST_LABEL = {"api.dexscreener.com": "dexscreener", "api.rugcheck.xyz": "rugcheck", "frontend-api-v3.pump.fun": "pump.fun",
              "api.geckoterminal.com": "geckoterminal", "api.mainnet-beta.solana.com": "rpc", "lite-api.jup.ag": "jupiter",
              "launch-mint-v1.raydium.io": "launchlab", "swap-api.pump.fun": "pump.fun trades", "advanced-api-v2.pump.fun": "pump.fun holders",
              XTW_HOST: "x tweets"}
ADAPTER_HOST = {"pf_graduated": ("frontend-api-v3.pump.fun",), "pf_new": ("frontend-api-v3.pump.fun",), "pf_coin_v3": ("frontend-api-v3.pump.fun",),
                "pf_dev_history": ("frontend-api-v3.pump.fun",), "pf_top_holders": ("frontend-api-v3.pump.fun", "advanced-api-v2.pump.fun"),
                "gt_new_pools": ("api.geckoterminal.com",), "gt_candles": ("api.geckoterminal.com",),
                "jup_recent": ("lite-api.jup.ag",), "dev_check": ("lite-api.jup.ag",), "ds_profiles": ("api.dexscreener.com",),
                "ds_tokens": ("api.dexscreener.com",), "ds_orders": ("api.dexscreener.com",), "ll_new": ("launch-mint-v1.raydium.io",),
                "rc_report": ("api.rugcheck.xyz",), "rpc_dev_age": (RPC_HOST,), "rpc_holder_age": (RPC_HOST,), "rpc_funding": (RPC_HOST,),
                "rpc_mint_time": (RPC_HOST,), "swap_trades": ("swap-api.pump.fun",), "swap_candles": ("swap-api.pump.fun",), "x_tweet": (XTW_HOST,)}


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


def read_body(r, end):
    """An answer's body a chunk at a time (at most ANSWER_MAX bytes), cut off at end: a host that sends its answer a few bytes at a time
    cannot hold the step past its end (the socket timeout only bounds each wait for data). Past end: TimeoutError, as no answer."""
    out = bytearray()
    while len(out) < ANSWER_MAX:
        if time.time() > end:
            raise TimeoutError("the answer was not done by the step's end")
        b = r.read1(min(65536, ANSWER_MAX - len(out)))
        if not b:
            break
        out += b
    return bytes(out)


class RadarHttp(F.Http):
    """fetch's counters and per-host locks with the radar's request rules (module docstring). Single-threaded use.
    code: the last request's HTTP status (None: no answer; "skip": not sent: the host is cooling down or given up, or the step's time
    is up). heard: the URLs that got a real answer this cycle (JSON, or a 404). The per-cycle budget: rpc_left (Solana RPC calls).
    pace_mock: keep the gaps against a mock too (the selftest's pacing check)."""
    pace_mock = False

    def __init__(self, mock=None, pause=0.0, log=None):
        F.Http.__init__(self, mock, pause, log)
        self.until, self.code, self.heard, self.hit429, self.asked, self.mute = None, None, set(), set(), {}, set()
        self.cool, self.level, self.said, self.seen429, self.rpc_at = {}, {}, set(), set(), {}
        self.rpc_left = None

    def new_cycle(self, until, rpc_cap=None):
        self.until, self.heard, self.hit429, self.asked, self.rpc_left, self.mute, self.seen429 = until, set(), set(), {}, rpc_cap, set(), set()

    def blocked(self, host):
        return host in self.dead or host in self.hit429 or host in self.mute or self.cool.get(host, 0.0) > time.time()

    def state(self, host):
        """ok / limited / down / unused for the page's host list (this cycle)."""
        if host in self.dead or host in self.mute:
            return "down"
        if host in self.hit429 or host in self.seen429 or self.cool.get(host, 0.0) > time.time():
            return "limited"
        return "ok" if self.asked.get(host) else "unused"

    def _say_once(self, key, s):
        if key not in self.said:
            self.said.add(key)
            self.log(s)

    def gap_of(self, host):
        return GAPS.get(host, 0.0) if (not self.mock or self.pace_mock) else 0.0

    def _pace(self, host):
        """The host's minimum gap (GAPS), then the request is counted (fetch's _pace with the radar's gaps; no cool-down wait here)."""
        gap = self.gap_of(host)
        if gap and host in self.last_at:
            time.sleep(max(0.0, self.last_at[host] + gap - time.time()))
        with self.lock:
            self.n += 1
            self.last_at[host] = time.time()

    def _rate429(self, host):
        """A 429: the host's cool-down ladder, and (except GeckoTerminal while its ladder lasts) no more requests this cycle."""
        ladder = COOL_HOST.get(host, COOL)
        lv = self.level.get(host, 0)
        self.level[host] = lv + 1
        wait = ladder[min(lv, len(ladder) - 1)]
        self.cool[host] = time.time() + wait
        self.seen429.add(host)
        if host not in COOL_HOST or host in CYCLE_SKIP or lv + 1 > len(ladder):
            self.hit429.add(host)
            self.log("  ! 429 rate limited by %s: skipped for the rest of the cycle%s" % (host, ", then %s" % fmt_s(wait) if wait > 30 else ""))
        else:
            self.log("  ! 429 rate limited by %s: asked again after %s" % (host, fmt_s(wait)))
        with self.lock:
            self.limited += 1
            self.limited_by[host] = self.limited_by.get(host, 0) + 1

    def _send(self, u, data=None, headers=None, method=None, until=None):
        """One request: (status, body bytes); status None when no answer came (also an answer not done by the step's end), "skip" when
        none was sent."""
        host = urllib.parse.urlsplit(u).netloc
        self.code = "skip"
        if self.blocked(host):
            return "skip", None
        end = until or self.until or (time.time() + REQ_TIMEOUT)
        gap = self.gap_of(host)
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
                raw, status = read_body(r, end), getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            status, raw = e.code, b""
        except Exception as e:                # no answer (a timeout, a refused or reset connection): the host rests for the rest of this cycle
            self.code = None                  # (a timeout may be the step's own end); it is asked again next cycle, never given up for the run
            self._say_once("noanswer:%s" % host, "  ! %s: no answer (%s): skipped for the rest of the cycle" % (host, short(e)))
            self.mute.add(host)
            return None, None
        self.code = status
        if status == 429:
            self._rate429(host)
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
        """JSON-RPC POST. The Solana RPC counts against rpc_left (None: no cap) and keeps RPC_GAP_S between two calls of one method
        (none is sent when that wait would pass the step's end); a 429 inside a 200 is a 429."""
        host = urllib.parse.urlsplit(u).netloc
        meth = str((payload or {}).get("method") or "") if isinstance(payload, dict) else ""
        if host == RPC_HOST:
            if self.rpc_left is not None and self.rpc_left <= 0:
                self.code = "skip"
                return None
            if self.blocked(host):
                self.code = "skip"
                return None
            last = self.rpc_at.get(meth)
            if last is not None and (not self.mock or self.pace_mock):
                wait = last + RPC_GAP_S - time.time()
                end = until or self.until or (time.time() + REQ_TIMEOUT)
                if wait > 0:
                    if time.time() + wait > end - MIN_LEFT - 1.0:
                        self.code = "skip"
                        return None
                    time.sleep(wait)
            if self.rpc_left is not None:
                self.rpc_left -= 1
            self.rpc_at[meth] = time.time()
        _, raw = self._send(u, data=json.dumps(payload).encode("utf-8"), headers=dict({"Content-Type": "application/json"}, **(headers or {})),
                                 method="POST", until=until)
        if raw is None:
            return None
        try:
            out = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None
        if isinstance(out, dict) and isinstance(out.get("error"), dict) and out["error"].get("code") == 429:
            self.code = 429
            self._rate429(host)
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


def fmt_s(s):
    return ("%.1f min" % (s / 60.0)) if s >= 60 else ("%d s" % round(s))


def ms_of(v):
    """Milliseconds from a number (s or ms) or an ISO date (memebot's parse_ms), as an int, else None."""
    x = M.parse_ms(v)
    return int(x) if x else None


def tweet_id(tid):
    """tid as a tweet id the syndication endpoint can be asked about (TWEET_ID), else None: a link whose id cannot be looked up is
    unknown for good, settled without a request (launch_radar.tweet_likes never spends a lookup on it, nor retries it)."""
    tid = str(tid or "")
    return tid if TWEET_ID.fullmatch(tid) else None


def amount_scale(total):
    """pump.fun's holder and trade amounts: tokens (supply 1e9), or raw units with 6 decimals when the sum says so."""
    return PUMP_SUPPLY * (1e6 if total > PUMP_SUPPLY * 10 else 1.0)


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
        PumpSwap pool) into meta. The list row carries everything the radar needs: no per-coin call for a listed coin."""
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

    def gt_new(self, sb, now):
        """GeckoTerminal new pools, newest first, up to PAGES pages: page 2 only when page 1's oldest pool is younger than FRESH_MS
        (otherwise nothing on it can be fresh). -> <sb>/gt/new.txt. Returns the rows written, or None (no answer)."""
        pools, inc = [], []
        for pg in range(1, PAGES["gt_new_pools"] + 1):
            data = self.http.get(F.GT + "/networks/solana/new_pools?include=base_token&page=%d" % pg)
            if data is None or not self.shape("gt_new_pools", isinstance(data, dict) and isinstance(data.get("data"), list), "data list"):
                break
            got = [p for p in data["data"] if isinstance(p, dict)]
            pools += got
            inc += [x for x in (data.get("included") or []) if isinstance(x, dict)]
            ts = [ms_of((p.get("attributes") or {}).get("pool_created_at")) for p in got]
            ts = [t for t in ts if t]
            if not got or (now and ts and now - min(ts) >= FRESH_MS):
                break
        if not pools:
            return None
        return F.write_rows(sb, "gt", "new.txt", F.gt_rows({"data": pools, "included": inc}))

    def discover(self, sb, meta, now=None, jmeta=None):
        """Every discovery list into the sandbox; lists.json with the DexScreener profiles (and LaunchLab's newest when on). Jupiter's
        mint times and devs go into jmeta. Returns {tag: count}."""
        os.makedirs(sb, exist_ok=True)
        h, n, lists = self.http, {}, {}
        jmeta = jmeta if jmeta is not None else {}
        if self.use("pf_graduated"):
            n["pf:graduated"] = self.pf_list(sb, "graduated", PF_GRAD, PAGES["pf_graduated"], meta, now)
        if self.use("pf_new"):
            n["pf:new"] = self.pf_list(sb, "new", PF_NEW, PAGES["pf_new"], meta, now)
        if self.use("gt_new_pools"):
            got = self.gt_new(sb, now)
            if got is not None:
                n["gt:new"] = got
        if self.use("jup_recent"):
            data = h.get(F.JUP + "/recent")
            if data is not None and self.shape("jup_recent", isinstance(data, list) and (not data or (isinstance(data[0], dict) and "id" in data[0])), "list of tokens with id"):
                n["jup:recent"] = F.write_rows(sb, "jup", "recent.txt", [r for r in (jup_row(t) for t in data) if r])
                for t in data:
                    a = F.addr_of((t or {}).get("id")) if isinstance(t, dict) else None
                    if a:
                        f = {k: v for k, v in (("t", ms_of(t.get("createdAt"))), ("dev", F.addr_of(t.get("dev")))) if v}
                        if f:
                            jmeta[a] = dict(jmeta.get(a) or {}, seen=int(now) if now else None, **f)
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
            return "ok", rc_trim(rep, networks=self.use("rc_insider_networks"), creator_tokens=self.use("rc_creator_tokens"))
        if code == 404:
            return "404", None
        if code == 429:
            return "429", None
        return ("skip" if code == "skip" else "err"), None

    # ---------------------------------------------------------------- pump.fun
    def pf_coin(self, mint, meta, now=None):
        """pump.fun coins-v3/{mint}: the coin's mint time, creator and X link into meta (for a coin no list carried). True when it answered."""
        if not self.use("pf_coin_v3"):
            return False
        c = self.http.get(PF_COIN % mint)
        if c is None or not self.shape("pf_coin_v3", isinstance(c, dict) and "mint" in c and "created_timestamp" in c, "mint and created_timestamp"):
            return False
        meta[mint] = pf_facts(c, meta.get(mint), now)
        return True

    def pf_dev(self, creator, now):
        """The dev's pump.fun launches: coins?creator=<dev> (the 50 newest, a strict filter) and, when 50 came back, coins-v2's total
        count. -> {"count": all launches or None, "rows": [[mint, graduated 0/1, dead 0/1], ...]} (dead: never graduated, under $10k
        and older than an hour), or None (no answer). Two frontend-api-v3 calls at most."""
        if not self.use("pf_dev_history"):
            return None
        data = self.http.get(PF_BY_CREATOR % creator)
        if data is None:
            return None
        coins = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else None
        mine = [c for c in coins or [] if c.get("creator") == creator]
        # the probe found the filter strict (28 of 28 rows); a row of another creator means it was ignored: nothing is known
        if not self.shape("pf_dev_history", coins is not None and len(mine) == len(coins), "list of that creator's coins (the creator filter held)"):
            return None
        rows = []
        for c in mine:
            a = F.addr_of(c.get("mint"))
            if not a:
                continue
            t = ms_of(c.get("created_timestamp"))
            done = bool(c.get("complete"))
            dead = (not done) and (F.num(c.get("usd_market_cap")) or 0) < 10_000 and bool(t) and now - t > 3_600_000
            rows.append([a, 1 if done else 0, 1 if dead else 0])
        count = len(rows) if len(data) < 50 else None
        if len(data) >= 50:
            j = self.http.get(PF_DEV_COUNT % creator, headers=PF_WEB)
            if isinstance(j, dict) and F.num(j.get("count")) is not None:
                count = int(F.num(j["count"]))
        return {"count": count, "rows": rows[:50]}

    def pf_holders(self, mint, t_mint, skip=()):
        """pump.fun's top 50 holders (frontend-api-v3, advanced-api-v2 when the first gives no answer): the share and count of holders
        that entered within 30 s of the mint (enteredAt; needs the mint time), and isBundler as info (a count only when some are
        flagged: an unflagged list is never "no bundlers"). isSniper / isDev / fundingSource only when pf_holder_flags is on.
        -> {"snip30", "snip30N", "bundN", "bundPct", "n", "flagSnipN"} or None. skip: addresses that are pools, not buyers."""
        if not self.use("pf_top_holders"):
            return None
        data = None
        for url in PF_HOLDERS:
            data = self.http.get(url % mint, headers=PF_WEB)
            if data is not None or self.http.code == 404:
                break                  # an answer, or the coin is unknown (the fallback host would say the same); a 429, no answer or
                                       # a host that is resting: the other host (its own 60 a minute) is asked
        top = data.get("topHolders") if isinstance(data, dict) else None
        if data is None or not self.shape("pf_top_holders", isinstance(top, list) and (not top or (isinstance(top[0], dict) and "amount" in top[0])),
                                          "topHolders with amount"):
            return None
        hs = [x for x in top if isinstance(x, dict) and F.addr_of(x.get("address")) and x.get("address") not in skip]
        amt = lambda x: F.num(x.get("amount")) or 0.0
        scale = amount_scale(sum(amt(x) for x in top if isinstance(x, dict)))
        out = {"n": len(hs), "snip30": None, "snip30N": None, "bundN": None, "bundPct": None, "flagSnipN": None}
        timed = [x for x in hs if ms_of(x.get("enteredAt"))]
        if t_mint and hs and len(timed) >= 0.8 * len(hs):
            early = [x for x in timed if ms_of(x["enteredAt"]) <= t_mint + 30_000]
            out["snip30"], out["snip30N"] = round(sum(amt(x) for x in early) / scale, 4), len(early)
        bn = [x for x in hs if x.get("isBundler") is True]
        if bn:
            out["bundN"], out["bundPct"] = len(bn), round(sum(amt(x) for x in bn) / scale, 4)
        if self.use("pf_holder_flags"):
            sn = [x for x in hs if x.get("isSniper") is True]
            out["flagSnipN"] = len(sn) or None
        return out

    def pf_trades(self, mint, t_mint, pages=3):
        """The coin's launch trades (swap-api, 100 a page, newest first, at most `pages` pages): {"snip30", "snip30N", "slotN",
        "slotPct", "pages"}; {"many": True, "pages"} when the pages do not reach the launch (the oldest trade must be a curve trade or
        lie within a minute of the mint: a graduated coin's pages may hold its pool trades only); None (no answer)."""
        if not self.use("swap_trades"):
            return None
        rows, cursor, n = [], "", 0
        for _ in range(pages):
            data = self.http.get(PF_TRADES % (mint, ("&cursor=" + urllib.parse.quote(cursor)) if cursor else ""), headers=PF_WEB)
            if data is None or not self.shape("swap_trades", isinstance(data, dict) and isinstance(data.get("trades"), list), "trades"):
                return {"many": True, "pages": n} if rows else None
            n += 1
            rows += [r for r in data["trades"] if isinstance(r, dict)]
            pg = data.get("pagination") or {}
            cursor = pg.get("nextCursor") or ""
            if not pg.get("hasMore") or not cursor:
                break
        else:
            return {"many": True, "pages": n}
        ts = [ms_of(r.get("timestamp")) for r in rows]
        ts = [t for t in ts if t]
        if not ts:
            return None
        curve = any(str(r.get("program") or "").lower() == "pump" for r in rows)
        if not curve and not (t_mint and min(ts) <= t_mint + 60_000):
            return {"many": True, "pages": n}
        t0 = t_mint or min(ts)
        buys = []
        for r in rows:
            t = ms_of(r.get("timestamp"))
            if t and str(r.get("type") or "").lower() == "buy":
                sid = str(r.get("slotIndexId") or "")
                buys.append((t, sid[:12] if sid.isdigit() and len(sid) >= 13 else "", str(r.get("userAddress") or ""), F.num(r.get("baseAmount")) or 0.0))
        if not buys:
            return None
        buys.sort()
        scale = amount_scale(sum(b[3] for b in buys))
        s0 = min((b[1] for b in buys if b[1]), default="")
        first = [b for b in buys if b[0] - t0 <= 30_000]
        slot = [b for b in buys if s0 and b[1] == s0]
        return {"snip30": round(sum(b[3] for b in first) / scale, 4), "snip30N": len({b[2] for b in first}),
                "slotN": len({b[2] for b in slot}) if s0 else None, "slotPct": round(sum(b[3] for b in slot) / scale, 4) if s0 else None, "pages": n}

    def pf_candles(self, mint):
        """swap-api 1-minute candles from the mint minute (oldest first, the curve phase included): [[ms, open, high, low, close,
        volume], ...], or None. One call (100 minutes from the mint)."""
        if not self.use("swap_candles"):
            return None
        j = self.http.get(PF_CANDLES % mint, headers=PF_WEB)
        if j is None or not self.shape("swap_candles", isinstance(j, list) and (not j or (isinstance(j[0], dict) and "close" in j[0] and "timestamp" in j[0])),
                                       "list of candles with timestamp and close"):
            return None
        out = []
        for c in j:
            t = ms_of(c.get("timestamp")) if isinstance(c, dict) else None
            if t and F.num(c.get("close")):
                out.append([t] + [F.num(c.get(k)) for k in ("open", "high", "low", "close", "volume")])
        out.sort(key=lambda c: c[0])
        return out

    # ---------------------------------------------------------------- X (one tweet's public facts, no key)
    def tweet(self, tid, until=None):
        """The likes and replies of one tweet by id (fetch.viral's syndication endpoint and token): {"likes", "replies"}; {"likes": None,
        "replies": None, "gone": True} when X says the tweet is not there or cannot be read (a 404; a 200 that is not a tweet: a deleted
        tweet's tombstone, an unavailable or protected one's other __typename, an empty {}, the answers fetch.viral skips): unknown for
        good, not asked again; None when it cannot be told now (no answer, a 429 or another refusal, the time is up): asked again later.
        Never 0 for unknown. Only an answer that is a tweet goes through shape(), so one odd tweet never switches x_tweet off for the
        run; a tweet without favorite_count (the endpoint changed) does. An id tweet_id() refuses: None and nothing sent (tweet_likes
        settles it first). until: the latest moment the request may end (the caller keeps it short, so a slow X never holds a cycle up)."""
        tid = tweet_id(tid)
        if not self.use("x_tweet") or tid is None:
            return None
        gone = {"likes": None, "replies": None, "gone": True}
        j = self.http.get("%s?id=%s&token=%s&lang=en" % (F.XTW, tid, F.tweet_token(tid)), until=until)
        if j is None:
            return gone if self.http.code == 404 else None
        if isinstance(j, dict) and (j.get("__typename", "Tweet") != "Tweet" or not (j.get("id_str") or j.get("text") is not None)):
            return gone
        if not self.shape("x_tweet", isinstance(j, dict) and F.num(j.get("favorite_count")) is not None, "favorite_count"):
            return None
        likes, replies = F.num(j.get("favorite_count")), F.num(j.get("conversation_count"))
        if likes < 0:
            return gone                      # a count no tweet has: this answer will not get better, unknown for good
        return {"likes": int(likes), "replies": int(replies) if replies is not None and replies >= 0 else None}

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

    def wallet_age(self, wallet, name="rpc_holder_age"):
        """A wallet's oldest signature among its last 1,000: {"first": ms or None, "n": signatures, "full": 1,000 or more, "sig": the oldest},
        or None (no answer)."""
        res = self.rpc(name, "getSignaturesForAddress", [wallet, {"limit": 1000}])
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
        """The mint's oldest signature (its creation, ms) when the last `calls` pages of 1,000 signatures reach back to it; 0 when they
        do not (a busy coin: the mint time stays unknown, the probe's 3,000 did not reach a 34-minute-old one); None when no answer came."""
        before = None
        for _ in range(calls):
            opt = {"limit": 1000}
            if before:
                opt["before"] = before
            res = self.rpc("rpc_mint_time", "getSignaturesForAddress", [mint, opt])
            if not isinstance(res, list):
                return None
            if len(res) < 1000:
                ts = [F.num(x.get("blockTime")) for x in res if isinstance(x, dict) and F.num(x.get("blockTime"))]
                return int(min(ts) * 1000) if ts else 0
            before = (res[-1] or {}).get("signature")
            if not before:
                return 0
        return 0

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


def wallet_fresh(wc, now):
    """A cached wallet (wallet_age's answer) -> True (under a day old or under 10 transactions), False (older), None (cannot tell:
    1,000 signatures that all lie within the last day)."""
    if not isinstance(wc, dict):
        return None
    first = F.num(wc.get("first"))
    if not wc.get("full"):
        return bool((first and now - first < 86_400_000) or (F.num(wc.get("n")) or 0) < 10)
    if first and now - first >= 86_400_000:
        return False
    return None


def pf_facts(c, prev=None, now=None):
    """A pump.fun coin's facts the radar keeps: mint time, creator, X / website / Telegram links, graduated, PumpSwap pool, its replies
    (reply_count, with repAt: when this answer gave it; 0 is a reading, a missing count leaves the last one), and when a list last carried
    it (seen)."""
    out = dict(prev or {})
    if now:
        out["seen"] = int(now)
    for k, v in (("t", ms_of(c.get("created_timestamp"))), ("creator", F.addr_of(c.get("creator"))), ("x", c.get("twitter")), ("web", c.get("website")),
                 ("tg", c.get("telegram")), ("pool", F.addr_of(c.get("pump_swap_pool")) or F.addr_of(c.get("pool_address"))), ("sym", c.get("symbol")),
                 ("name", c.get("name"))):
        if v:
            out[k] = str(v)[:200] if isinstance(v, str) else v
    rep = F.num(c.get("reply_count")) if not isinstance(c.get("reply_count"), bool) else None
    if rep is not None and rep >= 0 and now:
        out["rep"], out["repAt"] = int(rep), int(now)
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


def rc_trim(rep, networks=True, creator_tokens=False):
    """A RugCheck report cut to the fields the radar and fetch.rc_row read (a full report is tens of KB): risks, scores, top holders,
    the insider graph (graphInsidersDetected always, as fetch.rc_row reads it for memebot's scan exactly as in the scan; the networks'
    sizes only when rc_insider_networks is on), creator, the creator's other tokens (only when rc_creator_tokens is on: the probe found
    them null), supply and creator balance, LP lock, holders, mutability, launchpad. The topHolders insider flag was never true in the
    probe: it is kept for rc_row (memebot's own reading) but nothing of the radar reads it."""
    top = []
    for h in (rep.get("topHolders") or [])[:20]:
        if isinstance(h, dict):
            top.append({"owner": h.get("owner") or h.get("address"), "pct": F.num(h.get("pct")), "insider": bool(h.get("insider"))})
    ct, lp = rep.get("creatorTokens"), rep.get("launchpad")
    nets = [{"size": F.num(n.get("size")), "type": str(n.get("type") or "")[:20]} for n in (rep.get("insiderNetworks") or [])
            if isinstance(n, dict) and F.num(n.get("size")) is not None][:10] if networks and isinstance(rep.get("insiderNetworks"), list) else None
    out = {"risks": [{"name": str(r.get("name") or "")[:80], "level": str(r.get("level") or "")[:12]} for r in (rep.get("risks") or []) if isinstance(r, dict)][:30],
           "score": rep.get("score"), "score_normalised": rep.get("score_normalised"), "topHolders": top,
           "graphInsidersDetected": rep.get("graphInsidersDetected"), "insiderNetworks": nets, "creator": F.addr_of(rep.get("creator")),
           "creatorTokens": [{"mint": F.addr_of((t or {}).get("mint")), "marketCap": F.num((t or {}).get("marketCap")), "createdAt": (t or {}).get("createdAt")}
                             for t in ct if isinstance(t, dict)][:50] if creator_tokens and isinstance(ct, list) else None,
           "token": {"supply": F.num((rep.get("token") or {}).get("supply"))} if isinstance(rep.get("token"), dict) else {},
           "creatorBalance": rep.get("creatorBalance"), "totalHolders": rep.get("totalHolders"),
           "tokenMeta": {"mutable": (rep.get("tokenMeta") or {}).get("mutable")} if isinstance(rep.get("tokenMeta"), dict) else {},
           "markets": [{"lp": {"lpLockedPct": F.num(((m or {}).get("lp") or {}).get("lpLockedPct"))}} for m in (rep.get("markets") or []) if isinstance(m, dict)][:6],
           "launchpad": str(lp.get("name") if isinstance(lp, dict) else lp)[:40] if lp else None}
    return out


def net_size(rep):
    """The insider graph's size for the chip "insider network of N": the largest network, or graphInsidersDetected when it is over 50
    (RugCheck's own warning), whichever is larger; None when neither is there."""
    if not isinstance(rep, dict):
        return None
    sizes = [F.num(n.get("size")) for n in (rep.get("insiderNetworks") or []) if isinstance(n, dict) and F.num(n.get("size")) is not None]
    g = F.num(rep.get("graphInsidersDetected"))
    if g and g > 50:
        sizes.append(g)
    return max(sizes) if sizes else None
