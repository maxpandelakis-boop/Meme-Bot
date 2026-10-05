#!/usr/bin/env python3
"""fetch.py: the sourcing layer of the meme bot. Pulls public data and writes the plain-text files memebot.py reads.

Nothing here needs an API key. Everything is best effort: a source that is down, rate-limited or blocked by Cloudflare is skipped
and the scan goes on with what came back (memebot.py's `gather` prints the coverage). Standard library only.

Sources (what it writes into --dir):
  DexScreener   lists.json (boostTop, boostLatest, profiles, cto, ads), pairs/search_<kw>.txt (~60 keyword searches, ~30 pairs each),
                pairs/tokens_<k>.txt (full pair data for addresses the other sources named, 30 per request)
  RugCheck      lists.json["rcNew"] (new tokens) and risk/reports.txt (13-field rows for the shortlist)
  GeckoTerminal gt/trending.txt, gt/new.txt, gt/top.txt (pool pages, with distinct buyers/sellers)
  CoinGecko     cg.json (trending coins)
  pump.fun      pf/top.txt, pf/new.txt (address source + pf.* factors; often behind Cloudflare, so often empty)
  Jupiter       jup/trending.txt, jup/organic.txt, jup/recent.txt (holders, organic score, traders)
  GMGN          gm/smart1h.txt, gm/smart24h.txt, tb/<addr>.txt (top buyers of shortlisted coins), wallets.json (profitable wallets);
                GMGN sits behind Cloudflare and usually refuses plain HTTP clients, so these are often empty
  news          news.json from public crypto RSS feeds (CoinDesk, Cointelegraph, Decrypt, CryptoSlate, The Block)
  LunarCrush    social.json, only when LUNARCRUSH_API_KEY is set

Usage:
  python3 fetch.py sources --dir mb [--light]      -> clears the source dirs and refetches every source (light: fewer pages)
  python3 fetch.py tokens  --dir mb --addrs a,b,c  -> pairs/tokens_<k>.txt for those addresses (or --from-gather gather.json)
  python3 fetch.py risk    --dir mb --addrs a,b,c  -> risk/reports.txt (+ tb/<addr>.txt from GMGN) for those addresses
  python3 fetch.py news    --dir mb                -> news.json only
  --mock http://127.0.0.1:8765  rewrites every URL to <mock>/<host>/<path> (used by selftest.py)
"""
import argparse, email.utils, glob, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 memebot-paper/1.0"
TIMEOUT = 25
DS = "https://api.dexscreener.com"
RC = "https://api.rugcheck.xyz/v1"
GT = "https://api.geckoterminal.com/api/v2"
CG = "https://api.coingecko.com/api/v3"
PF = "https://frontend-api-v3.pump.fun"
JUP = "https://lite-api.jup.ag/tokens/v2"
GM = "https://gmgn.ai/defi/quotation/v1"
LC = "https://lunarcrush.com/api4/public"
KEYWORDS = """dog cat pepe frog elon trump musk ai agent moon inu wif bonk chad wojak doge shib baby meme giga sigma based degen ape monkey
bear bull penguin pengu hat rocket lambo fart poop gm wen ser anon pnut squirrel goat duck bird fish whale shark cow pig chill guy girl
king queen god alien ufo mars pixel retro game punk ninja pirate zombie ghost skull fire ice gold diamond brain beard mog brainrot
cult coin shiba floki wojak mfer neko kitty puppy hamster capybara raccoon sloth otter seal llama donkey horse unicorn dragon wizard knight
robot cyber matrix quantum nuke bomb rocketman banana cookie pizza taco burger beer coffee tea sushi noodle hotdog candy chocolate bacon
mommy daddy uncle grandma karen chad stacy giga gm bro bruh lol lmao based cringe ratio cope seethe vibe dank yolo hodl wagmi ngmi""".split()
NEWS_FEEDS = [("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("cointelegraph", "https://cointelegraph.com/rss"),
              ("decrypt", "https://decrypt.co/feed"), ("cryptoslate", "https://cryptoslate.com/feed/"), ("theblock", "https://www.theblock.co/rss.xml")]
SOURCE_DIRS = ("pairs", "risk", "gt", "pf", "jup", "gm", "tb")
SOURCE_FILES = ("lists.json", "cg.json", "news.json", "social.json", "wallets.json")


class Http:
    """GET with retries, polite pacing and a circuit breaker per host (3 hard failures -> that host is skipped for the run)."""

    def __init__(self, mock=None, pause=0.25, log=None):
        self.mock, self.pause, self.dead, self.fails, self.n = (mock or "").rstrip("/"), pause, set(), {}, 0
        self.log = log or (lambda s: print(s, file=sys.stderr, flush=True))

    def url(self, u):
        if not self.mock:
            return u
        p = urllib.parse.urlsplit(u)
        return "%s/%s%s%s" % (self.mock, p.netloc, p.path, ("?" + p.query) if p.query else "")

    def get(self, u, kind="json", headers=None, tries=3):
        host = urllib.parse.urlsplit(u).netloc
        if host in self.dead:
            return None
        hdr = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
        hdr.update(headers or {})
        wait = 1.0
        for i in range(tries):
            try:
                self.n += 1
                with urllib.request.urlopen(urllib.request.Request(self.url(u), headers=hdr), timeout=TIMEOUT) as r:
                    raw = r.read()
                self.fails[host] = 0
                time.sleep(self.pause)
                if kind == "json":
                    try:
                        return json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        return None
                return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 429 and i + 1 < tries:
                    time.sleep(wait); wait *= 3
                    continue
                self.log("  ! %s %s" % (e.code, u[:110]))
                if e.code in (401, 403, 404, 410, 451):
                    self._fail(host, hard=e.code != 404)
                    return None
                return None
            except Exception as e:  # URLError, timeout, remote disconnect, proxy refusals
                self.log("  ! %s %s" % (str(e)[:60], u[:110]))
                if i + 1 < tries:
                    time.sleep(wait); wait *= 2
                    continue
                self._fail(host, hard=True)
                return None
        return None

    def _fail(self, host, hard):
        if hard:
            self.fails[host] = self.fails.get(host, 0) + 1
            if self.fails[host] >= 3:
                self.dead.add(host)
                self.log("  ! giving up on %s for this run" % host)


# ---------------------------------------------------------------- helpers
def num(v):
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def txt(v, n=40):
    """A text field for a pipe row: no pipes, no newlines, 'null' when empty."""
    s = re.sub(r"[|\r\n\t]+", " ", str(v if v is not None else "")).strip()[:n]
    return s or "null"


def cell(v):
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return txt(v, 600)


def row(*fields):
    return "|".join(cell(v) for v in fields)


def write_rows(d, sub, name, rows):
    if not rows:
        return 0
    os.makedirs(os.path.join(d, sub), exist_ok=True)
    with open(os.path.join(d, sub, name), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return len(rows)


def write_json(d, name, data):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def clear_sources(d, dirs=SOURCE_DIRS, files=SOURCE_FILES):
    for sub in dirs:
        shutil.rmtree(os.path.join(d, sub), ignore_errors=True)
    for fn in files:
        try:
            os.remove(os.path.join(d, fn))
        except OSError:
            pass


def addr_of(v):
    v = str(v or "").strip()
    return v if B58.match(v) else None


# ---------------------------------------------------------------- DexScreener
def ds_row(p):
    """A DexScreener pair object -> 27-field row (Solana only)."""
    if not isinstance(p, dict) or str(p.get("chainId") or "").lower() != "solana":
        return None
    bt = p.get("baseToken") or {}
    a = addr_of(bt.get("address"))
    if not a:
        return None
    tx, vol, chg, info = p.get("txns") or {}, p.get("volume") or {}, p.get("priceChange") or {}, p.get("info") or {}
    socials, websites = info.get("socials") or [], info.get("websites") or []
    t = lambda w, k: ((tx.get(w) or {}).get(k))
    x = next((s.get("url") for s in socials if isinstance(s, dict) and str(s.get("type") or "").lower() in ("twitter", "x")), None)
    boosts = (p.get("boosts") or {}).get("active") if isinstance(p.get("boosts"), dict) else None
    return row(a, bt.get("symbol"), bt.get("name"), p.get("dexId"), p.get("pairAddress"), num(p.get("priceUsd")), num(p.get("marketCap")), num(p.get("fdv")),
               num((p.get("liquidity") or {}).get("usd")), num(vol.get("h24")), num(vol.get("h6")), num(vol.get("h1")),
               num(chg.get("m5")), num(chg.get("h1")), num(chg.get("h6")), num(chg.get("h24")),
               num(t("h24", "buys")), num(t("h24", "sells")), num(t("h6", "buys")), num(t("h6", "sells")), num(t("h1", "buys")), num(t("h1", "sells")),
               num(p.get("pairCreatedAt")), num(boosts), txt(x, 120) if x else None, len(websites), len(socials))


def ds_lists(http):
    """Address lists from DexScreener's boost, profile, community-takeover and ad feeds (Solana only)."""
    out = {}
    for name, path in (("boostTop", "/token-boosts/top/v1"), ("boostLatest", "/token-boosts/latest/v1"), ("profiles", "/token-profiles/latest/v1"),
                       ("cto", "/community-takeovers/latest/v1"), ("ads", "/ads/latest/v1")):
        data = http.get(DS + path)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        addrs = []
        for it in data if isinstance(data, list) else []:
            if isinstance(it, dict) and str(it.get("chainId") or "").lower() == "solana":
                a = addr_of(it.get("tokenAddress") or it.get("address"))
                if a and a not in addrs:
                    addrs.append(a)
        out[name] = addrs
        http.log("  dexscreener %-11s %4d" % (name, len(addrs)))
    return out


def ds_search(http, d, keywords):
    total = 0
    for kw in keywords:
        data = http.get(DS + "/latest/dex/search?q=" + urllib.parse.quote(kw))
        rows = [r for r in (ds_row(p) for p in ((data or {}).get("pairs") or [])) if r]
        total += write_rows(d, "pairs", "search_%s.txt" % re.sub(r"[^a-z0-9]", "", kw.lower())[:14], rows)
    http.log("  dexscreener search: %d pairs from %d keywords" % (total, len(keywords)))
    return total


def ds_tokens(http, d, addrs, start=0):
    """Full pair data for a list of token addresses, 30 per request -> pairs/tokens_<k>.txt. Returns rows written."""
    addrs = [a for a in dict.fromkeys(a for a in addrs if addr_of(a))]
    total, k = 0, start
    for i in range(0, len(addrs), 30):
        data = http.get(DS + "/tokens/v1/solana/" + ",".join(addrs[i:i + 30]))
        rows = [r for r in (ds_row(p) for p in (data if isinstance(data, list) else (data or {}).get("pairs") or [])) if r]
        total += write_rows(d, "pairs", "tokens_%03d.txt" % k, rows)
        k += 1
    http.log("  dexscreener tokens: %d pairs for %d addresses" % (total, len(addrs)))
    return total


# ---------------------------------------------------------------- RugCheck
def rc_list(http, what):
    data = http.get(RC + "/stats/" + what)
    addrs = [a for a in (addr_of(it.get("mint")) for it in (data if isinstance(data, list) else []) if isinstance(it, dict)) if a]
    http.log("  rugcheck %s %d" % (what, len(addrs)))
    return addrs


def rc_new(http):
    return rc_list(http, "new_tokens")


def rc_row(mint, rep):
    """A RugCheck report (full /report, or the /report/summary) -> 13-field row."""
    rep = rep if isinstance(rep, dict) else {}
    risks = rep.get("risks") or []
    lvl = lambda r: str(r.get("level") or "").lower()
    danger = [txt(r.get("name"), 60) for r in risks if isinstance(r, dict) and lvl(r) == "danger"]
    warn = [txt(r.get("name"), 60) for r in risks if isinstance(r, dict) and lvl(r) == "warn"]
    score = num(rep.get("score_normalised")) if rep.get("score_normalised") is not None else num(rep.get("score"))
    lps = [num((m.get("lp") or {}).get("lpLockedPct")) for m in (rep.get("markets") or []) if isinstance(m, dict)]
    lps = [x for x in lps if x is not None]
    lp = max(lps) if lps else None
    top = [h for h in (rep.get("topHolders") or []) if isinstance(h, dict)]
    pcts = [num(h.get("pct")) or 0 for h in top]
    top1 = pcts[0] if pcts else None
    top10 = sum(pcts[:10]) if pcts else None
    insiders = num(rep.get("graphInsidersDetected"))
    if insiders is None and top:
        insiders = float(sum(1 for h in top if h.get("insider")))
    supply = num((rep.get("token") or {}).get("supply"))
    creator_pct = (num(rep.get("creatorBalance")) / supply * 100) if supply and num(rep.get("creatorBalance")) is not None else None
    mutable = (rep.get("tokenMeta") or {}).get("mutable")
    lpd = rep.get("launchpad")
    launchpad = (lpd.get("name") if isinstance(lpd, dict) else lpd) or None
    holders = num(rep.get("totalHolders"))
    addrs = [a for a in (addr_of(h.get("owner") or h.get("address")) for h in top[:12]) if a]
    return row(mint, score, lp, holders, top1, top10, insiders, creator_pct, bool(mutable) if mutable is not None else None, launchpad,
               ";".join(danger) or None, ";".join(warn) or None, ";".join(addrs) or None)


def rc_reports(http, d, addrs):
    rows = []
    for a in addrs:
        rep = http.get(RC + "/tokens/%s/report" % a)
        if not isinstance(rep, dict):
            rep = http.get(RC + "/tokens/%s/report/summary" % a)
        if isinstance(rep, dict) and (rep.get("risks") is not None or rep.get("score") is not None):
            rows.append(rc_row(a, rep))
    n = write_rows(d, "risk", "reports_%d.txt" % int(time.time()), rows)
    http.log("  rugcheck reports %d of %d" % (n, len(addrs)))
    return n


# ---------------------------------------------------------------- GeckoTerminal
def gt_rows(data):
    inc = {}
    for it in (data or {}).get("included") or []:
        if isinstance(it, dict) and it.get("type") == "token":
            inc[it.get("id")] = it.get("attributes") or {}
    rows = []
    for pool in (data or {}).get("data") or []:
        if not isinstance(pool, dict):
            continue
        at, rel = pool.get("attributes") or {}, pool.get("relationships") or {}
        tid = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
        a = addr_of(tid.split("_", 1)[1] if "_" in tid else tid)
        if not a:
            continue
        tok = inc.get(tid) or {}
        name = str(at.get("name") or "")
        sym = tok.get("symbol") or name.split(" / ")[0]
        dex = ((rel.get("dex") or {}).get("data") or {}).get("id")
        tx = (at.get("transactions") or {}).get("h24") or {}
        chg = at.get("price_change_percentage") or {}
        rows.append(row(a, sym, tok.get("name") or sym, pool.get("attributes", {}).get("address"), dex, num(at.get("base_token_price_usd")), num(at.get("fdv_usd")),
                        num(at.get("reserve_in_usd")), num((at.get("volume_usd") or {}).get("h24")), num(chg.get("h1")), num(chg.get("h6")), num(chg.get("h24")),
                        num(tx.get("buys")), num(tx.get("sells")), num(tx.get("buyers")), num(tx.get("sellers")), at.get("pool_created_at")))
    return rows


def gt_pools(http, d, pages=3):
    total = 0
    for name, path in (("trending", "/networks/solana/trending_pools?include=base_token&page=%d"), ("new", "/networks/solana/new_pools?include=base_token&page=%d"),
                       ("top", "/networks/solana/pools?include=base_token&sort=h24_volume_usd_desc&page=%d")):
        rows = []
        for pg in range(1, pages + 1):
            data = http.get(GT + path % pg)
            if not data:
                break
            rows += gt_rows(data)
        total += write_rows(d, "gt", name + ".txt", rows)
    http.log("  geckoterminal pools %d" % total)
    return total


# ---------------------------------------------------------------- CoinGecko, pump.fun, Jupiter, GMGN, news, LunarCrush
def cg_trending(http, d):
    data = http.get(CG + "/search/trending")
    rows = []
    for i, c in enumerate((data or {}).get("coins") or []):
        it = (c or {}).get("item") or {}
        chg = ((it.get("data") or {}).get("price_change_percentage_24h") or {}).get("usd")
        rows.append([it.get("symbol"), it.get("name"), i + 1, num(chg), num(it.get("market_cap_rank"))])
    write_json(d, "cg.json", rows)
    http.log("  coingecko trending %d" % len(rows))
    return len(rows)


def pf_coins(http, d, light=False):
    total = 0
    for name, q in (("top", "sort=market_cap&order=DESC"), ("new", "sort=created_timestamp&order=DESC")):
        rows = []
        for off in range(0, 50 if light else 150, 50):
            data = http.get(PF + "/coins?offset=%d&limit=50&%s&includeNsfw=false" % (off, q))
            if not isinstance(data, list):
                break
            for c in data:
                a = addr_of((c or {}).get("mint"))
                if a:
                    rows.append(row(a, c.get("symbol"), c.get("name"), num(c.get("usd_market_cap")), num(c.get("market_cap")), num(c.get("ath_market_cap")),
                                    num(c.get("reply_count")), bool(c.get("is_currently_live")), bool(c.get("complete")), num(c.get("created_timestamp")),
                                    txt(c.get("twitter"), 100) if c.get("twitter") else None, txt(c.get("website"), 100) if c.get("website") else None,
                                    txt(c.get("telegram"), 100) if c.get("telegram") else None))
        total += write_rows(d, "pf", name + ".txt", rows)
    http.log("  pump.fun %d" % total)
    return total


def jup_tokens(http, d):
    total = 0
    for name, path in (("trending", "/toptrending/24h"), ("trending1h", "/toptrending/1h"), ("traded", "/toptraded/24h"), ("organic", "/toporganicscore/24h"), ("recent", "/recent")):
        data = http.get(JUP + path)
        rows = []
        for t in data if isinstance(data, list) else []:
            a = addr_of((t or {}).get("id") or t.get("address"))
            if not a:
                continue
            au, s1, s24 = t.get("audit") or {}, t.get("stats1h") or {}, t.get("stats24h") or {}
            rows.append(row(a, t.get("symbol"), t.get("name"), num(t.get("usdPrice")), num(t.get("mcap")), num(t.get("fdv")), num(t.get("liquidity")),
                            num(t.get("holderCount")), num(t.get("organicScore")), num(au.get("topHoldersPercentage")), num(au.get("devMigrations")),
                            bool(t.get("isVerified")), (t.get("firstPool") or {}).get("createdAt"), num(s1.get("priceChange")), num((t.get("stats6h") or {}).get("priceChange")),
                            num(s24.get("priceChange")), num(s24.get("buyVolume")), num(s24.get("sellVolume")), num(s24.get("numBuys")), num(s24.get("numSells")),
                            num(s24.get("numTraders")), num(s24.get("numNetBuyers")), num(s24.get("holderChange")), num(s1.get("numBuys")), num(s1.get("numSells")),
                            num(s1.get("numNetBuyers"))))
        total += write_rows(d, "jup", name + ".txt", rows)
    http.log("  jupiter %d" % total)
    return total


GM_KEYS = ("address", "symbol", "name", "price", "market_cap", "liquidity", "volume", "holder_count", "top_10_holder_rate", "smart_degen_count",
           "renowned_count", "sniper_count", "bundler_rate", "rat_trader_amount_rate", "bluechip_owner_percentage", "rug_ratio", "is_wash_trading",
           "hot_level", "dev_team_hold_rate", "top70_sniper_hold_rate", "bot_degen_count", "is_honeypot", "creator_token_status", "twitter_rename_count",
           "open_timestamp", "launchpad")


def gm_rank(http, d):
    total = 0
    for name, path in (("smart1h", "/rank/sol/swaps/1h?orderby=smartmoney&direction=desc"), ("smart24h", "/rank/sol/swaps/24h?orderby=smartmoney&direction=desc")):
        data = http.get(GM + path)
        rows = []
        for t in ((data or {}).get("data") or {}).get("rank") or []:
            a = addr_of((t or {}).get("address"))
            if a:
                vals = [t.get(k) for k in GM_KEYS]
                vals[0] = a
                rows.append(row(*[(bool(v) if k in ("is_wash_trading", "is_honeypot") and v is not None else v) for k, v in zip(GM_KEYS, vals)]))
        total += write_rows(d, "gm", name + ".txt", rows)
    http.log("  gmgn rank %d" % total)
    return total


def gm_top_buyers(http, d, addrs):
    n = 0
    for a in addrs:
        data = http.get(GM + "/tokens/top_buyers/sol/" + a)
        info = (((data or {}).get("data") or {}).get("holders") or {}).get("holderInfo") or []
        rows = []
        for h in info:
            w = addr_of((h or {}).get("wallet_address"))
            if w:
                tags = h.get("tags") if isinstance(h.get("tags"), list) else []
                mk = h.get("maker_token_tags") if isinstance(h.get("maker_token_tags"), list) else []
                rows.append(row(w, h.get("status"), ";".join(map(str, tags)) or None, ";".join(map(str, mk)) or None))
        n += 1 if write_rows(d, "tb", a + ".txt", rows) else 0
        if "gmgn.ai" in http.dead:
            break
    http.log("  gmgn top buyers %d of %d" % (n, len(addrs)))
    return n


def gm_wallets(http, d):
    data = http.get(GM + "/rank/sol/wallets/7d?orderby=pnl_7d&direction=desc")
    rows = [[w.get("wallet_address"), num(w.get("pnl_7d")), num(w.get("winrate_7d")), ";".join(map(str, w.get("tags") or []))]
            for w in ((data or {}).get("data") or {}).get("rank") or [] if addr_of((w or {}).get("wallet_address"))]
    if rows:
        write_json(d, "wallets.json", rows)
    http.log("  gmgn wallets %d" % len(rows))
    return len(rows)


def news(http, d):
    items = []
    for src, url in NEWS_FEEDS:
        raw = http.get(url, kind="text")
        if not raw:
            continue
        try:
            root = ET.fromstring(raw.encode("utf-8", "replace"))
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            at = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
            ms = None
            if at:
                try:
                    ms = int(email.utils.parsedate_to_datetime(at).timestamp() * 1000)
                except (TypeError, ValueError):
                    ms = at
            if title:
                items.append([title[:300], src, ms])
        for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            if title:
                items.append([title[:300], src, it.findtext("{http://www.w3.org/2005/Atom}updated")])
    write_json(d, "news.json", items)
    http.log("  news %d headlines" % len(items))
    return len(items)


def lunarcrush(http, d, key):
    if not key:
        return 0
    data = http.get(LC + "/coins/list/v1?sort=interactions_24h&limit=500", headers={"Authorization": "Bearer " + key})
    rows = [[c.get("symbol"), c.get("name"), num(c.get("interactions_24h")), num(c.get("social_volume_24h") or c.get("posts_active")),
             num(c.get("creators_active") or c.get("social_contributors")), num(c.get("sentiment")), num(c.get("galaxy_score")), num(c.get("alt_rank"))]
            for c in (data or {}).get("data") or [] if isinstance(c, dict) and c.get("symbol")]
    if rows:
        write_json(d, "social.json", rows)
    http.log("  lunarcrush %d" % len(rows))
    return len(rows)


# ---------------------------------------------------------------- commands
def cmd_sources(http, d, light=False):
    os.makedirs(d, exist_ok=True)
    clear_sources(d)
    http.log("sources (%s):" % ("light" if light else "full"))
    lists = ds_lists(http)
    lists["rcNew"] = rc_new(http)
    lists["rcTrending"] = rc_list(http, "trending")
    lists["rcRecent"] = rc_list(http, "recent")
    write_json(d, "lists.json", lists)
    ds_search(http, d, KEYWORDS[:60] if light else KEYWORDS)
    gt_pools(http, d, pages=3 if light else 8)
    cg_trending(http, d)
    jup_tokens(http, d)
    news(http, d)
    lunarcrush(http, d, os.environ.get("LUNARCRUSH_API_KEY"))
    if not light:
        pf_coins(http, d)
        gm_rank(http, d)
        gm_wallets(http, d)
    http.log("  %d requests, hosts skipped: %s" % (http.n, ", ".join(sorted(http.dead)) or "none"))


def cmd_tokens(http, d, addrs):
    start = len(glob.glob(os.path.join(d, "pairs", "tokens_*.txt")))
    return ds_tokens(http, d, addrs, start)


def cmd_risk(http, d, addrs):
    n = rc_reports(http, d, addrs)
    if "gmgn.ai" not in http.dead:
        gm_top_buyers(http, d, addrs[:40])
    return n


def addrs_arg(a):
    out = []
    if a.addrs:
        out += a.addrs.split(",")
    if a.from_gather:
        g = json.load(open(a.from_gather, encoding="utf-8"))
        for ch in g.get("chunks") or g.get("shortlist") or []:
            out += ch.split(",") if isinstance(ch, str) else []
    return [x.strip() for x in out if addr_of(x.strip())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sources", "tokens", "risk", "news"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--addrs", default="")
    ap.add_argument("--from-gather", default="", help="a gather/shortlist JSON file whose chunks/shortlist give the addresses")
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    ap.add_argument("--pause", type=float, default=float(os.environ.get("MEMEBOT_PAUSE", "0.25")))
    a = ap.parse_args()
    http = Http(a.mock, a.pause)
    os.makedirs(a.dir, exist_ok=True)
    if a.cmd == "sources":
        cmd_sources(http, a.dir, a.light)
    elif a.cmd == "tokens":
        print(json.dumps({"rows": cmd_tokens(http, a.dir, addrs_arg(a))}))
    elif a.cmd == "risk":
        print(json.dumps({"reports": cmd_risk(http, a.dir, addrs_arg(a))}))
    else:
        print(json.dumps({"news": news(http, a.dir)}))


if __name__ == "__main__":
    main()
