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
import argparse, html, math, email.utils, glob, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request, datetime as dt
import xml.etree.ElementTree as ET
import concurrent.futures

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
RPC = "https://api.mainnet-beta.solana.com"            # Solana's public RPC: ~100 requests per 10 s, 40 per method
LL = "https://launch-mint-v1.raydium.io"               # Raydium LaunchLab (bonk.fun): launches with their creator wallet
RAY = "https://api-v3.raydium.io"
RD = "https://www.reddit.com"                            # Reddit's JSON is blocked for servers, its RSS feeds are not
CMC = "https://api.coinmarketcap.com/data-api/v3"       # CoinMarketCap's site API: top searches and the Solana gainers list
REDDIT_FEEDS = [("CryptoMoonShots", RD + "/r/CryptoMoonShots/new/.rss"), ("search", RD + "/search.rss?q=solana+memecoin&sort=new&limit=100"),
                ("memecoins", RD + "/r/memecoins/new/.rss")]      # Reddit's RSS refuses a server after two quick requests; three feeds 12 s apart get through
B58_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")
CG_MEME_CATEGORY = "solana-meme-coins"
GOPLUS = "https://api.gopluslabs.io/api/v1/solana/token_security"   # GoPlus token security for Solana: authorities, holders, LP burn; no key
JUP_PRICE = "https://lite-api.jup.ag/price/v3"                     # Jupiter's price API: 50 mints per request; the re-pricing fallback
ORCA = "https://api.orca.so/v2/solana/pools"
FNG = "https://api.alternative.me/fng/?limit=1"
FC = "https://api.warpcast.com/v2/search-casts"                    # Farcaster casts (public search)
MASTO = "https://mastodon.social/api/v1/timelines/tag"
CHAN = "https://a.4cdn.org/biz/catalog.json"
ST = "https://api.stocktwits.com/api/2/streams/symbol"
XSYN = "https://syndication.twitter.com/srv/timeline-profile/screen-name"
XTW = "https://cdn.syndication.twimg.com/tweet-result"     # one tweet's public facts (likes, replies, text, author) by id, no key
TG = "https://t.me/s"
BQ = "https://streaming.bitquery.io/eap"                            # Bitquery: every DEX trade of a coin from the chain itself (BITQUERY_TOKEN)
BQ_QUERY = """query ($mint: String!, $since: DateTime) {
  Solana {
    DEXTradeByTokens(limit: {count: 300}, orderBy: {descending: Block_Time},
      where: {Trade: {Currency: {MintAddress: {is: $mint}}}, Transaction: {Result: {Success: true}}, Block: {Time: {since: $since}}}) {
      Block { Time }
      Trade { Side { Type } Amount AmountInUSD PriceInUSD Account { Owner } Dex { ProtocolName ProtocolFamily } }
      Transaction { Signer }
    }
  }
}"""
BQ_COLS = ("address", "trades1h", "buyers1h", "sellers1h", "netUsd1h", "topBuyerShare", "traders", "buyUsd1h", "sellUsd1h")
LCT_COLS = ("address", "interactions24h", "posts24h", "contributors", "sentiment", "trend")
SOCIAL_QUERIES = (("farcaster", FC + "?q=solana%20memecoin&limit=100"), ("farcaster", FC + "?q=pump.fun&limit=100"), ("farcaster", FC + "?q=memecoin&limit=100"),
                  ("mastodon", MASTO + "/solana?limit=40"), ("mastodon", MASTO + "/memecoin?limit=40"), ("mastodon", MASTO + "/memecoins?limit=40"), ("mastodon", MASTO + "/pumpfun?limit=40"))
QUOTE_MINTS = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMGHMnZV5mLn8FXe9f2DoyA8z8K9HnQS7PnZLemAe"}
KEYWORDS = list(dict.fromkeys("""dog cat pepe frog elon trump musk ai agent moon inu wif bonk chad wojak doge shib baby meme giga sigma based degen ape monkey bear bull penguin pengu hat
rocket lambo fart poop gm wen ser anon pnut squirrel goat duck bird fish whale shark cow pig chill guy girl king queen god alien ufo mars pixel retro game
punk ninja pirate zombie ghost skull fire ice gold diamond brain beard mog brainrot cult coin shiba floki mfer neko kitty puppy hamster capybara raccoon
sloth otter seal llama donkey horse unicorn dragon wizard knight robot cyber matrix quantum nuke bomb rocketman banana cookie pizza taco burger beer coffee
tea sushi noodle hotdog candy chocolate bacon mommy daddy uncle grandma karen stacy bro bruh lol lmao cringe ratio cope seethe vibe dank yolo hodl wagmi
ngmi pump fun bonding curve graduated launch stealth fair presale airdrop points season meta trend viral tiktok twitter stream live sol solana jup jupiter
ray raydium orca meteora phantom backpack bags boop moonshot believe launchlab letsbonk zora clanker pepecoin kek frogs toad mochi popcat michi mew gigachad
andy brett landwolf boden tremp maga biden kamala obama putin xi china japan korea india brazil germany france canada mexico africa europe america world
earth planet galaxy star sun cash money rich poor broke bank wall street stonks stock bitcoin btc eth ethereum xrp bnb hype aster fartcoin goatseus act
kitten tabby husky corgi doggo pup bulldog pitbull poodle beagle labrador golden retriever chihuahua wolf fox lion tiger panda koala kangaroo elephant giraffe
hippo rhino gorilla chimp orangutan bat rat mouse mole hedgehog badger beaver moose deer bunny rabbit snake lizard gecko turtle croc dino rex raptor mammoth
dodo pigeon crow parrot owl eagle hawk chicken rooster turkey goose swan pumpkin witch vampire werewolf cyborg android mecha gundam anime waifu husbando
senpai sensei kawaii chibi otaku jesus buddha zeus thor odin loki kratos satoshi vitalik cz sbf anatoly toly raj mert ansem murad cobie hsaka gcr crypto
token tokens dao defi nft memes memecoin shitcoin gem gems moonbag bag wallet fomo fud rekt north south east west left right up down big small tiny micro
mini mega ultra hyper super turbo nitro boost blast red blue green yellow purple pink orange black white gray rainbow neon glow dark light shadow spirit
soul mind heart happy sad angry mad crazy insane wild calm cozy comfy warm cold hot spicy sweet sour salty bitter yummy tasty one two three four five six
seven eight nine ten hundred thousand million billion trillion zero infinity pi phi alpha beta omega new old first last next final ultimate original classic
vintage modern future past present now today tomorrow forever never yes no maybe ok okay sure nope yep wow omg wtf lmfao rofl top kek haha hehe lul xd uwu
owo""".split()))
EXTRA_KEYWORDS = [w for w in list(dict.fromkeys("""wen moon pump dump rug safe scam honest legit real fake test demo alpha beta gamma delta sigma omega
jeet whale shrimp crab fish dolphin octopus squid jelly coral reef ocean sea lake river pond puddle rain snow storm thunder lightning
wind cloud fog mist dust sand rock stone mountain hill valley forest tree leaf flower rose tulip daisy lily lotus cactus mushroom
apple orange lemon lime grape cherry berry melon mango peach pear plum kiwi coconut avocado tomato potato carrot onion garlic pepper
bread butter cheese milk egg honey sugar salt rice bean corn wheat oat soup stew salad sandwich sausage steak ribs wings
car truck bike train plane ship boat rocket jet tank robot drone laser sword shield armor helmet crown ring gem pearl ruby emerald
sapphire opal jade amber ivory marble granite steel iron copper silver platinum uranium plutonium carbon neon argon helium hydrogen
hero villain legend myth saga epic tale story book page word letter sign symbol code secret mystery riddle puzzle maze labyrinth
clock time hour minute second day night dawn dusk noon midnight week month year decade century eon era age epoch
north pole arctic tundra desert jungle savanna prairie island peninsula continent country city town village farm ranch castle tower
church temple shrine altar monk priest nun saint angel demon devil hell heaven paradise utopia dystopia apocalypse zombie plague virus
doctor nurse cop judge lawyer banker trader broker dealer miner farmer baker chef pilot sailor soldier spy agent hacker coder nerd geek
mom dad son kid boy girl man woman baby twin bro sis cousin uncle aunt grandpa grandma family tribe clan gang crew squad team club
love hate joy fear hope faith trust luck fate doom gloom glory honor pride shame guilt envy greed lust wrath sloth gluttony
win lose draw tie fight race chase hunt catch grab steal rob loot raid siege war peace truce deal trade swap flip pump hold sell buy
giga mega ultra max min micro nano pico tiny huge vast epic super duper hyper turbo nitro boost rocket blast bang boom crash smash
ai gpt llm bot agent neural quantum crypto chain block hash node mesh grid net web cloud edge core kernel shell byte bit pixel
sol eth btc bnb xrp ada dot link uni aave comp mkr snx yfi sushi cake bake rune luna atom osmo juno sei sui apt arb op base
cat dog pig cow goat sheep horse donkey mule camel llama yak bison buffalo moose elk deer boar wolf fox bear lion tiger leopard cheetah
hawk eagle owl crow raven parrot pigeon dove swan goose duck hen rooster turkey peacock flamingo pelican penguin puffin kiwi emu ostrich""".split())) if w not in set(KEYWORDS)]   # the deep search: only words the normal scan did not use
NEWS_FEEDS = [("gnews-memecoin", "https://news.google.com/rss/search?q=solana+memecoin&hl=en-US&gl=US&ceid=US:en"),
              ("gnews-pumpfun", "https://news.google.com/rss/search?q=pump.fun+OR+%22meme+coin%22+solana&hl=en-US&gl=US&ceid=US:en"),
              ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("cointelegraph", "https://cointelegraph.com/rss"),
              ("decrypt", "https://decrypt.co/feed"), ("cryptoslate", "https://cryptoslate.com/feed/"), ("theblock", "https://www.theblock.co/rss.xml")]
SOURCE_DIRS = ("pairs", "risk", "gt", "pf", "jup", "gm", "tb", "dev", "ll", "gp", "gi", "cm", "bq", "lc", "hl", "vt", "dp")
SOURCE_FILES = ("lists.json", "cg.json", "news.json", "social.json", "wallets.json", "reddit.json", "cgmeme.json", "cmc.json", "market.json", "fresh.json")
HOST_GAP = {"api.geckoterminal.com": 10.0, "frontend-api-v3.pump.fun": 0.7, "api.mainnet-beta.solana.com": 0.3, "www.reddit.com": 12.0, "api.coinmarketcap.com": 1.0,
            "api.gopluslabs.io": 0.5, "api.coingecko.com": 1.2, "api.stocktwits.com": 0.5, "syndication.twitter.com": 1.0, "cdn.syndication.twimg.com": 1.0, "t.me": 1.0, "api.warpcast.com": 0.5, "mastodon.social": 0.5,
            "streaming.bitquery.io": 0.5, "lunarcrush.com": 1.0}   # minimum seconds between requests to a host (GT allows only ~6/min from GitHub's shared addresses)
MAX_429_PER_HOST = 8          # rate-limit waits per host and run before the host is skipped (the other sources still run)
HOST_429 = {"frontend-api-v3.pump.fun": (2, 5, 15), "api.geckoterminal.com": (20, 40, 60), "www.reddit.com": (5, 10, 15)}   # 429 back-off per host; DexScreener default below


class Http:
    """GET with retries, polite pacing and a circuit breaker per host (3 hard failures -> that host is skipped for the run)."""

    def __init__(self, mock=None, pause=0.25, log=None):
        self.mock, self.pause, self.dead, self.fails, self.n = (mock or "").rstrip("/"), pause, set(), {}, 0
        self.cooldown, self.limited = {}, 0
        self.log = log or (lambda s: print(s, file=sys.stderr, flush=True))
        self.last_progress = 0
        self.last_at = {}
        self.limited_by = {}
        self.nonjson = {}

    def url(self, u):
        if not self.mock:
            return u
        p = urllib.parse.urlsplit(u)
        return "%s/%s%s%s" % (self.mock, p.netloc, p.path, ("?" + p.query) if p.query else "")

    def get(self, u, kind="json", headers=None, tries=4):
        host = urllib.parse.urlsplit(u).netloc
        if host in self.dead:
            return None
        hdr = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
        hdr.update(headers or {})
        wait = 1.0
        for i in range(tries):
            if self.cooldown.get(host, 0) > time.time():      # a rate limit hit a moment ago: wait it out instead of hammering
                time.sleep(max(0.0, self.cooldown[host] - time.time()))
            gap = HOST_GAP.get(host, 0.0) if not self.mock else 0.0
            if gap and host in self.last_at:                     # hosts with a per-minute budget are paced, whatever the global pause
                time.sleep(max(0.0, self.last_at[host] + gap - time.time()))
            try:
                self.n += 1
                self.last_at[host] = time.time()
                with urllib.request.urlopen(urllib.request.Request(self.url(u), headers=hdr), timeout=TIMEOUT) as r:
                    raw = r.read()
                self.fails[host] = 0
                time.sleep(self.pause)
                if kind == "json":
                    try:
                        return json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        self.nonjson[host] = self.nonjson.get(host, 0) + 1
                        if self.nonjson[host] <= 2:      # a 200 that is not JSON (a block page, a maintenance page): say so, with the start of the body
                            self.log("  ! %s answered with something that is not JSON (HTTP %s): %r" % (host, getattr(r, "status", "?"), raw[:100].decode("utf-8", "replace")))
                        return None
                return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 429 and i + 1 < tries:
                    pause = HOST_429.get(host, (10, 30, 60))[min(i, 2)]   # DexScreener's limits are per minute: back off for real
                    self.log("  ! 429 rate limited by %s, waiting %ds" % (host, pause))
                    self.cooldown[host] = time.time() + pause
                    self.limited += 1
                    self.limited_by[host] = self.limited_by.get(host, 0) + 1
                    if self.limited_by[host] >= MAX_429_PER_HOST:
                        self.dead.add(host)
                        self.log("  ! giving up on %s for this run: rate limited %d times" % (host, self.limited_by[host]))
                        return None
                    time.sleep(pause)
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

    def post(self, u, payload, tries=3, headers=None):
        """JSON-RPC style POST with the same pacing, 429 handling and circuit breaker as get()."""
        host = urllib.parse.urlsplit(u).netloc
        if host in self.dead:
            return None
        body = json.dumps(payload).encode("utf-8")
        hdr = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}
        hdr.update(headers or {})
        for i in range(tries):
            if self.cooldown.get(host, 0) > time.time():
                time.sleep(max(0.0, self.cooldown[host] - time.time()))
            gap = HOST_GAP.get(host, 0.0) if not self.mock else 0.0
            if gap and host in self.last_at:
                time.sleep(max(0.0, self.last_at[host] + gap - time.time()))
            try:
                self.n += 1
                self.last_at[host] = time.time()
                with urllib.request.urlopen(urllib.request.Request(self.url(u), data=body, headers=hdr, method="POST"), timeout=TIMEOUT) as r:
                    raw = r.read()
                self.fails[host] = 0
                time.sleep(self.pause)
                try:
                    out = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    return None
                if isinstance(out, dict) and isinstance(out.get("error"), dict) and out["error"].get("code") == 429 and i + 1 < tries:
                    time.sleep(3); continue               # the public RPC answers 200 with a 429 inside for a throttled method
                return out
            except urllib.error.HTTPError as e:
                if e.code == 429 and i + 1 < tries:
                    self.limited += 1
                    time.sleep((3, 8)[min(i, 1)]); continue
                self.log("  ! %s %s" % (e.code, u[:80]))
                if e.code in (401, 403):
                    self._fail(host, hard=True)
                return None
            except Exception as e:
                self.log("  ! %s %s" % (str(e)[:60], u[:80]))
                if i + 1 < tries:
                    time.sleep(1.5); continue
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


SEARCH_THREADS = 3          # DexScreener keyword searches run on this many threads (its search limit is ~300 requests a minute)
SEARCH_PAUSE = 0.65         # ... each thread pausing this long after a request: 3 threads x ~1.1 requests/s stayed under the limit (0.4 did not)


def ds_probe(http):
    """DexScreener answered every search with no pairs: fetch one well-known search raw and log what came back, so the run
    log says whether the API is empty, blocked or changed (a 200 with no pairs is not a rate limit)."""
    raw = http.get(DS + "/latest/dex/search?q=pumpswap", kind="text")
    if raw is None:
        http.log("  ! dexscreener probe: no answer at all")
        return
    head = re.sub(r"\s+", " ", raw[:160])
    http.log("  ! dexscreener probe (%d bytes): %s" % (len(raw), head))


def ds_search(http, d, keywords):
    """DexScreener keyword searches -> pairs/search_<kw>.txt, one file per keyword. Long lists run on SEARCH_THREADS threads, each
    with its own Http (own pacing and breaker); their counters and dead hosts are merged back into `http`."""
    def one(h, kw):
        data = h.get(DS + "/latest/dex/search?q=" + urllib.parse.quote(kw))
        rows = [r for r in (ds_row(p) for p in ((data or {}).get("pairs") or [])) if r]
        return write_rows(d, "pairs", "search_%s.txt" % re.sub(r"[^a-z0-9]", "", kw.lower())[:14], rows)
    total = 0
    if len(keywords) <= 40 or "api.dexscreener.com" in http.dead:
        for i, kw in enumerate(keywords):
            total += one(http, kw)
            if (i + 1) % 20 == 0:
                http.log("  dexscreener search %d/%d keywords, %d pairs so far" % (i + 1, len(keywords), total))
    else:
        workers = [Http(http.mock, http.pause if http.mock else max(http.pause, SEARCH_PAUSE), http.log) for _ in range(SEARCH_THREADS)]
        done = [0]
        def job(i, kw):
            n = one(workers[i % SEARCH_THREADS], kw)
            done[0] += 1
            if done[0] % 100 == 0:
                http.log("  dexscreener search %d/%d keywords" % (done[0], len(keywords)))
            return n
        with concurrent.futures.ThreadPoolExecutor(max_workers=SEARCH_THREADS) as ex:
            total = sum(ex.map(lambda ik: job(*ik), enumerate(keywords)))
        for w in workers:
            http.n += w.n
            http.limited += w.limited
            http.dead |= w.dead
            for host, k in w.limited_by.items():
                http.limited_by[host] = http.limited_by.get(host, 0) + k
    http.log("  dexscreener search: %d pairs from %d keywords%s" % (total, len(keywords), (" on %d threads" % SEARCH_THREADS) if len(keywords) > 40 else ""))
    if total == 0 and len(keywords) >= 20:
        ds_probe(http)
    return total


def ds_tokens(http, d, addrs, start=0, prefix="tokens"):
    """Full pair data for a list of token addresses, 30 per request -> pairs/<prefix>_<k>.txt. Returns rows written."""
    addrs = [a for a in dict.fromkeys(a for a in addrs if addr_of(a))]
    total, k, got = 0, start, set()
    for i in range(0, len(addrs), 30):
        data = http.get(DS + "/tokens/v1/solana/" + ",".join(addrs[i:i + 30]))
        rows = [r for r in (ds_row(p) for p in (data if isinstance(data, list) else (data or {}).get("pairs") or [])) if r]
        total += write_rows(d, "pairs", "%s_%03d.txt" % (prefix, k), rows)
        k += 1
        for r in rows:
            got.add(r.split("|", 1)[0])
    http.log("  dexscreener %s: %d pairs for %d addresses" % (prefix, total, len(addrs)))
    missing = [a for a in addrs if a not in got]
    if missing and "lite-api.jup.ag" not in http.dead:
        jup_prices(http, d, missing, k, prefix)
    return total


def cmd_refresh(http, d, addrs):
    """The last thing before the decision: fresh pair data for the candidates (shortlist and the best gated coins), so the
    pick rests on prices from this minute, not from the start of a 15-minute scan -> pairs/fresh_<k>.txt + fresh.json."""
    n = ds_tokens(http, d, addrs, 0, "fresh")
    write_json(d, "fresh.json", {"t": int(time.time() * 1000), "n": len(addrs), "rows": n})
    http.log("  refreshed the prices of %d candidates before the pick" % len(addrs))
    return n


def jup_prices(http, d, addrs, k=0, prefix="tokens"):
    """Jupiter's price API for coins DexScreener did not return (50 mints per request): price and liquidity only, as
    px-only rows -> pairs/jupx_<k>.txt. The big test and the track record then still get a price when DexScreener drops a
    coin or a chunk fails; a coin Jupiter does not price either is the one that is really gone."""
    rows = []
    for i in range(0, len(addrs), 50):
        data = http.get(JUP_PRICE + "?ids=" + ",".join(addrs[i:i + 50]))
        for a, p in (data or {}).items() if isinstance(data, dict) else []:
            if isinstance(p, dict) and num(p.get("usdPrice")):
                rows.append(row(a, num(p.get("usdPrice")), num(p.get("liquidity"))))
    n = write_rows(d, "pairs", "%sjupx_%03d.txt" % ("fresh_" if prefix == "fresh" else "", k), rows)
    http.log("  jupiter prices: %d of %d coins DexScreener had no pair for" % (n, len(addrs)))
    return n


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
    # "insiders" = top holders RugCheck flags as insiders (what the 10/15 limits were made for); the size of the detected insider
    # network (often thousands of correlated wallets on a launchpad coin) goes into the warnings as information, not as the count
    insiders = float(sum(1 for h in top if h.get("insider"))) if top else num(rep.get("graphInsidersDetected"))
    net = num(rep.get("graphInsidersDetected"))
    supply = num((rep.get("token") or {}).get("supply"))
    creator_pct = (num(rep.get("creatorBalance")) / supply * 100) if supply and num(rep.get("creatorBalance")) is not None else None
    mutable = (rep.get("tokenMeta") or {}).get("mutable")
    lpd = rep.get("launchpad")
    launchpad = (lpd.get("name") if isinstance(lpd, dict) else lpd) or None
    holders = num(rep.get("totalHolders"))
    addrs = [a for a in (addr_of(h.get("owner") or h.get("address")) for h in top[:12]) if a]
    if net and net > 50:
        warn.append("insider network of %d wallets" % int(net))
    return row(mint, score, lp, holders, top1, top10, insiders, creator_pct, bool(mutable) if mutable is not None else None, launchpad,
               ";".join(danger) or None, ";".join(warn) or None, ";".join(addrs) or None)


def rc_reports(http, d, addrs):
    rows = []
    for i, a in enumerate(addrs):
        if i and i % 25 == 0:
            http.log("  rugcheck %d/%d reports" % (i, len(addrs)))
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


GT_DEXES = (("pumpswap", 3), ("raydium", 2), ("launchlab", 2), ("meteora", 1), ("boop-fun", 1), ("moonit", 1))


def gt_pools(http, d, pages=3):
    """GeckoTerminal pool lists -> gt/*.txt. 20 pools a page; from GitHub's shared addresses the host allows only about six
    requests a minute, so Http paces it at 10 s and a full scan spends under three minutes here for some 350 pools."""
    total = 0
    full = pages >= 8
    lists = [("trending", "/networks/solana/trending_pools?include=base_token&duration=24h&page=%d", 1),
             ("new", "/networks/solana/new_pools?include=base_token&page=%d", min(pages, 3)),
             ("top", "/networks/solana/pools?include=base_token&sort=h24_volume_usd_desc&page=%d", min(pages, 3))]
    if full:
        lists += [("trending1h", "/networks/solana/trending_pools?include=base_token&duration=1h&page=%d", 1),
                  ("trending6h", "/networks/solana/trending_pools?include=base_token&duration=6h&page=%d", 1)]
        known = http.get(GT + "/networks/solana/dexes?page=1")
        ids = {str((x or {}).get("id")) for x in ((known or {}).get("data") or []) if isinstance(x, dict)}
        for dex, n in GT_DEXES:
            if not ids or dex in ids:          # only exchanges GeckoTerminal lists, so no request is wasted on a 404
                lists.append(("dex_" + re.sub(r"[^a-z0-9]", "", dex), "/networks/solana/dexes/%s/pools?include=base_token&sort=h24_volume_usd_desc&page=%%d" % dex, n))
    for name, path, n in lists:
        rows = []
        for pg in range(1, n + 1):
            data = http.get(GT + path % pg)
            got = gt_rows(data) if data else []
            if not got:
                break
            rows += got
        total += write_rows(d, "gt", name + ".txt", rows)
        if full:
            http.log("  geckoterminal %s: %d pools" % (name, len(rows)))
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
    """pump.fun lists -> pf/*.txt: the biggest coins by market cap (graduated ones included), the newest, the graduated ones that
    traded most recently, and the live-streaming ones. The host rate-limits hard; Http paces and retries it."""
    total = 0
    lists = [("top", "/coins?offset=%d&limit=50&sort=market_cap&order=DESC&includeNsfw=false", 2 if light else 20),
             ("new", "/coins?offset=%d&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false", 1 if light else 10)]
    if not light:
        lists += [("graduated", "/coins?offset=%d&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false&complete=true", 10),
                  ("live", "/coins/currently-live?offset=%d&limit=50&includeNsfw=false", 4)]
    for name, path, n in lists:
        rows = []
        for pg in range(n):
            data = http.get(PF + path % (pg * 50))
            if not isinstance(data, list) or not data:
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


JUP_VERIFIED_MC = (20_000, 100_000_000)


def jup_tokens(http, d, light=False):
    total = 0
    lists = [("trending", "/toptrending/24h?limit=100"), ("trending1h", "/toptrending/1h?limit=100"), ("trending6h", "/toptrending/6h?limit=100"),
             ("traded", "/toptraded/24h?limit=100"), ("traded1h", "/toptraded/1h?limit=100"), ("traded6h", "/toptraded/6h?limit=100"),
             ("organic", "/toporganicscore/24h?limit=100"), ("organic1h", "/toporganicscore/1h?limit=100"), ("organic6h", "/toporganicscore/6h?limit=100"),
             ("recent", "/recent")] + ([] if light else [("verified", "/tag?query=verified")])
    for name, path in lists:
        data = http.get(JUP + path)
        rows = []
        for t in data if isinstance(data, list) else []:
            if name == "verified" and not (JUP_VERIFIED_MC[0] <= (num((t or {}).get("mcap")) or 0) <= JUP_VERIFIED_MC[1]):
                continue               # the verified list is thousands of established tokens; keep the ones a meme gate could pass
            a = addr_of((t or {}).get("id") or t.get("address"))
            if not a:
                continue
            au, s1, s24 = t.get("audit") or {}, t.get("stats1h") or {}, t.get("stats24h") or {}
            rows.append(row(a, t.get("symbol"), t.get("name"), num(t.get("usdPrice")), num(t.get("mcap")), num(t.get("fdv")), num(t.get("liquidity")),
                            num(t.get("holderCount")), num(t.get("organicScore")), num(au.get("topHoldersPercentage")), num(au.get("devMigrations")),
                            bool(t.get("isVerified")), (t.get("firstPool") or {}).get("createdAt"), num(s1.get("priceChange")), num((t.get("stats6h") or {}).get("priceChange")),
                            num(s24.get("priceChange")), num(s24.get("buyVolume")), num(s24.get("sellVolume")), num(s24.get("numBuys")), num(s24.get("numSells")),
                            num(s24.get("numTraders")), num(s24.get("numNetBuyers")), num(s24.get("holderChange")), num(s1.get("numBuys")), num(s1.get("numSells")),
                            num(s1.get("numNetBuyers")), num(s1.get("buyVolume")), num(s1.get("sellVolume"))))
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


def reddit(http, d):
    """Reddit's newest posts in the meme-coin subreddits and two searches (RSS, the JSON API refuses servers): every Solana
    address and $cashtag in a title or body is recorded with the post's time and subreddit. reddit.json rows:
    [title, sub, ms, [addresses], [cashtags]]. Returns the addresses (they join the universe through lists.json)."""
    A = "{http://www.w3.org/2005/Atom}"
    posts, addrs = [], []
    for sub, url in REDDIT_FEEDS:
        raw = http.get(url, kind="text")
        if not raw:
            continue
        try:
            root = ET.fromstring(raw.encode("utf-8", "replace"))
        except ET.ParseError:
            continue
        for it in root.iter(A + "entry"):
            title = html.unescape((it.findtext(A + "title") or "").strip())
            body = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext(A + "content") or ""))
            ms = None
            at = it.findtext(A + "updated") or it.findtext(A + "published")
            if at:
                try:
                    ms = int(dt.datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    ms = None
            text = title + " " + body
            found = [a for a in dict.fromkeys(B58_RE.findall(text)) if not a.isdigit()][:6]
            tags = [t.upper() for t in dict.fromkeys(CASHTAG_RE.findall(text))][:8]
            if title:
                posts.append([title[:200], sub, ms, found, tags])
                addrs += found
    n_reddit = len(posts)
    for sub, url in SOCIAL_QUERIES:            # Farcaster casts and Mastodon tag timelines, same row shape
        data = http.get(url)
        items = ((data or {}).get("result") or {}).get("casts") if isinstance(data, dict) else data
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            text = html.unescape(re.sub(r"<[^>]+>", " ", str(it.get("text") or it.get("content") or "")))
            ms = num(it.get("timestamp"))
            if ms is None and it.get("created_at"):
                try:
                    ms = int(dt.datetime.fromisoformat(str(it["created_at"]).replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    ms = None
            found = [a for a in dict.fromkeys(B58_RE.findall(text)) if not a.isdigit()][:6]
            tags = [t.upper() for t in dict.fromkeys(CASHTAG_RE.findall(text))][:8]
            if text.strip() and (found or tags):
                posts.append([text[:200], sub, ms, found, tags])
                addrs += found
    data = http.get(CHAN)                       # 4chan /biz/: every thread's subject and opening post
    for page in data if isinstance(data, list) else []:
        for th in (page or {}).get("threads") or []:
            text = html.unescape(re.sub(r"<[^>]+>", " ", "%s %s" % (th.get("sub") or "", th.get("com") or "")))
            found = [a for a in dict.fromkeys(B58_RE.findall(text)) if not a.isdigit()][:6]
            tags = [t.upper() for t in dict.fromkeys(CASHTAG_RE.findall(text))][:8]
            ms = num(th.get("last_modified")) or num(th.get("time"))
            if (found or tags) and ms:
                posts.append([text[:200], "4chan", int(ms * 1000), found, tags])
                addrs += found
    write_json(d, "reddit.json", posts)
    http.log("  social posts %d (reddit %d, farcaster/mastodon/4chan %d), %d addresses, %d cashtags" % (
        len(posts), n_reddit, len(posts) - n_reddit, len(set(addrs)), sum(1 for p in posts for _ in p[4])))
    return sorted(set(addrs))


def market(http, d):
    """The market around the coins: SOL and BTC 24h change (CoinGecko) and the Fear & Greed index -> market.json."""
    out = {}
    px = http.get(CG + "/simple/price?ids=solana,bitcoin&vs_currencies=usd&include_24hr_change=true")
    if isinstance(px, dict):
        out["sol24"] = num((px.get("solana") or {}).get("usd_24h_change"))
        out["btc24"] = num((px.get("bitcoin") or {}).get("usd_24h_change"))
        out["solUsd"] = num((px.get("solana") or {}).get("usd"))
    fg = http.get(FNG)
    try:
        out["fng"] = num(((fg or {}).get("data") or [{}])[0].get("value"))
    except (AttributeError, IndexError, TypeError):
        out["fng"] = None
    write_json(d, "market.json", out)
    http.log("  market: SOL %s%% 24h, BTC %s%%, fear & greed %s" % (out.get("sol24"), out.get("btc24"), out.get("fng")))
    return out


def orca_top(http):
    """Orca's 100 busiest pools -> the non-quote mints in them (list orcaVol)."""
    data = http.get(ORCA + "?limit=100&sort=volume24h&order=desc")
    out = []
    for p in ((data or {}).get("data") or []) if isinstance(data, dict) else []:
        for k in ("tokenMintA", "tokenMintB"):
            a = addr_of((p or {}).get(k))
            if a and a not in QUOTE_MINTS:
                out.append(a)
    http.log("  orca top pools %d mints" % len(set(out)))
    return sorted(set(out))


def cg_meme(http, d):
    """CoinGecko's Solana meme-coin category (the 250 biggest by volume and by market cap) with each coin's Solana address from
    the platform list. cgmeme.json rows: [address, symbol, name, mcRank, volume, chg1h, chg24h]. Returns the addresses."""
    ids = {}
    plat = http.get(CG + "/coins/list?include_platform=true")
    for c in plat if isinstance(plat, list) else []:
        a = ((c or {}).get("platforms") or {}).get("solana")
        if a and c.get("id"):
            ids[c["id"]] = a
    rows, seen = [], set()
    for order in ("volume_desc", "market_cap_desc"):
        data = http.get(CG + "/coins/markets?vs_currency=usd&category=%s&order=%s&per_page=250&page=1&price_change_percentage=1h,24h" % (CG_MEME_CATEGORY, order))
        for c in data if isinstance(data, list) else []:
            a = ids.get((c or {}).get("id"))
            if not a or a in seen:
                continue
            seen.add(a)
            rows.append([a, c.get("symbol"), c.get("name"), num(c.get("market_cap_rank")), num(c.get("total_volume")),
                         num(c.get("price_change_percentage_1h_in_currency")), num(c.get("price_change_percentage_24h_in_currency") or c.get("price_change_percentage_24h"))])
    write_json(d, "cgmeme.json", rows)
    http.log("  coingecko solana meme list %d coins (%d ids with a Solana address)" % (len(rows), len(ids)))
    return [r[0] for r in rows]


def cmc(http, d):
    """CoinMarketCap: the top searches (publicity, by symbol) and the Solana coins with the biggest 24h gains (with address).
    cmc.json: {"search": [[symbol, name, rank, marketCap, chg24h]], "gainers": [[address, symbol, name, cmcRank, chg24h, marketCap]]}."""
    search, gainers = [], []
    data = http.get(CMC + "/topsearch/rank")
    for i, c in enumerate(((data or {}).get("data") or {}).get("cryptoTopSearchRanks") or []):
        pc = (c or {}).get("priceChange") or {}
        search.append([c.get("symbol"), c.get("name"), i + 1, num(c.get("marketCap")) or num(c.get("selfReportedMarketCap")), num(pc.get("priceChange24h"))])
    data = http.get(CMC + "/cryptocurrency/listing?start=1&limit=100&sortBy=percent_change_24h&sortType=desc&convert=USD&cryptoType=all&tagType=all&audited=false&aux=cmc_rank,date_added,platform&platformId=16")
    for c in ((data or {}).get("data") or {}).get("cryptoCurrencyList") or []:
        a = ((c or {}).get("platform") or {}).get("token_address")
        q = ((c.get("quotes") or [{}])[0]) if isinstance(c.get("quotes"), list) and c.get("quotes") else {}
        if a and B58_RE.fullmatch(a):
            gainers.append([a, c.get("symbol"), c.get("name"), num(c.get("cmcRank")), num(q.get("percentChange24h")), num(q.get("marketCap"))])
    write_json(d, "cmc.json", {"search": search, "gainers": gainers})
    http.log("  coinmarketcap %d top searches, %d solana gainers" % (len(search), len(gainers)))
    return [g[0] for g in gainers]


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
def cmd_deep(http, d):
    """The deep search a cycle asks for when few coins passed the gates: more DexScreener keyword searches, added to the files."""
    http.log("deep search: %d extra keywords" % len(EXTRA_KEYWORDS))
    n = ds_search(http, d, EXTRA_KEYWORDS)
    http.log("  %d requests, %d rate-limit waits" % (http.n, http.limited))
    return n


def cmd_sources(http, d, light=False):
    os.makedirs(d, exist_ok=True)
    clear_sources(d)
    http.log("sources (%s):" % ("light" if light else "full"))
    lists = ds_lists(http)
    lists["rcNew"] = rc_new(http)
    lists["rcTrending"] = rc_list(http, "trending")
    lists["rcRecent"] = rc_list(http, "recent")
    lists["rcVerified"] = rc_list(http, "verified")
    lists["rayVol"] = ray_top(http)
    lists["orcaVol"] = orca_top(http)
    lists.update(launchlab(http, d))
    market(http, d)
    lists["reddit"] = reddit(http, d)          # publicity: what people post about, what CoinGecko and CoinMarketCap list
    lists["cgMeme"] = cg_meme(http, d)
    lists["cmcGain"] = cmc(http, d)
    write_json(d, "lists.json", lists)
    ds_search(http, d, KEYWORDS[:60] if light else KEYWORDS)
    gt_pools(http, d, pages=3 if light else 8)
    cg_trending(http, d)
    jup_tokens(http, d, light)
    news(http, d)
    lunarcrush(http, d, os.environ.get("LUNARCRUSH_API_KEY"))
    if not light:
        pf_coins(http, d)
        gm_rank(http, d)
        gm_wallets(http, d)
    http.log("  %d requests, %d rate-limit waits, hosts skipped: %s" % (http.n, http.limited, ", ".join(sorted(http.dead)) or "none"))


def cmd_tokens(http, d, addrs):
    start = len(glob.glob(os.path.join(d, "pairs", "tokens_*.txt")))
    return ds_tokens(http, d, addrs, start)


DEV_COLS = ("address", "devWallet", "devPct", "mintAuthOff", "freezeAuthOff", "jupHolders", "organic", "txs3h", "devSold", "devSellAgeMin", "topHoldersPct")
DEV_WINDOW_H = 3.0          # the creator's transactions of the last three hours are read
DEV_MAX_TX = 12             # at most this many of them are decoded per coin (40 getTransaction calls per 10 s allowed)


def dev_check(http, d, addrs, now=None):
    """For each shortlisted coin: Jupiter's token facts (creator wallet, creator's share, mint/freeze authority, holders) and,
    through the public Solana RPC, whether that creator wallet sold or moved the coin in the last hours -> dev/<stamp>.txt."""
    now = now or time.time()
    rows = []
    for a in addrs:
        data = http.get(JUP + "/search?query=" + a)
        t = next((x for x in (data if isinstance(data, list) else []) if isinstance(x, dict) and str(x.get("id")) == a), None)
        if not t:
            continue
        au = t.get("audit") or {}
        dev = addr_of(t.get("dev"))
        txs, sold, sell_age = None, None, None
        if dev and "api.mainnet-beta.solana.com" not in http.dead:
            sigs = http.post(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [dev, {"limit": 25}]})
            recent = [x for x in ((sigs or {}).get("result") or []) if isinstance(x, dict) and num(x.get("blockTime")) and now - x["blockTime"] <= DEV_WINDOW_H * 3600]
            txs, sold = len(recent), False
            for x in recent[:DEV_MAX_TX]:
                tx = http.post(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [x["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]})
                meta = ((tx or {}).get("result") or {}).get("meta") or {}
                bal = lambda key: sum(num(((b.get("uiTokenAmount") or {}).get("uiAmount"))) or 0 for b in (meta.get(key) or [])
                                      if isinstance(b, dict) and b.get("mint") == a and b.get("owner") == dev)
                if bal("postTokenBalances") < bal("preTokenBalances") - 1e-9:
                    sold = True
                    age = (now - x["blockTime"]) / 60.0
                    sell_age = age if sell_age is None else min(sell_age, age)
        rows.append(row(a, dev, num(au.get("devBalancePercentage")), bool(au.get("mintAuthorityDisabled")), bool(au.get("freezeAuthorityDisabled")),
                        num(t.get("holderCount")), num(t.get("organicScore")), txs, sold, round(sell_age) if sell_age is not None else None,
                        num(au.get("topHoldersPercentage"))))
    n = write_rows(d, "dev", "dev_%d.txt" % int(time.time()), rows)
    http.log("  creator check %d of %d (%d sold recently)" % (n, len(addrs), sum(1 for r in rows if r.split("|")[8] == "1")))
    return n


LL_COLS = ("address", "symbol", "name", "creator", "marketCap", "volume24h", "createdAt", "poolId", "finished")


def launchlab(http, d):
    """Raydium LaunchLab (bonk.fun) launches: newest, most recently traded, biggest -> ll/*.txt (with the creator wallet)
    and lists.json entries, so they count as source lists and get DexScreener data."""
    lists, total = {}, 0
    for name, sort in (("llNew", "new"), ("llHot", "lastTrade"), ("llMc", "marketCap")):
        data = http.get(LL + "/get/list?sort=%s&size=100&mintType=default&includeNsfw=false" % sort)
        rows, addrs = [], []
        for c in ((data or {}).get("data") or {}).get("rows") or []:
            a = addr_of((c or {}).get("mint"))
            if not a:
                continue
            mc = next((num(c.get(k)) for k in ("marketCap", "usdMarketCap", "mcap") if c.get(k) is not None), None)
            vol = next((num(c.get(k)) for k in ("volumeU", "volume24h", "volume") if c.get(k) is not None), None)
            created = next((c.get(k) for k in ("createAt", "createdAt", "createTime") if c.get(k) is not None), None)
            rows.append(row(a, c.get("symbol"), c.get("name"), addr_of(c.get("creator")), mc, vol, created, c.get("poolId"), bool(c.get("finishingRate") == 1 or c.get("migrated"))))
            addrs.append(a)
        total += write_rows(d, "ll", name + ".txt", rows)
        lists[name] = addrs
    http.log("  launchlab %d" % total)
    return lists


def ray_top(http):
    """Raydium's biggest pools by 24h volume: the base mints as one more list."""
    data = http.get(RAY + "/pools/info/list?poolType=all&poolSortField=volume24h&sortType=desc&pageSize=1000&page=1")
    skip = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCdbgHKKaLN"}
    out = []
    for pool in ((data or {}).get("data") or {}).get("data") or []:
        for side in ("mintA", "mintB"):
            a = addr_of(((pool or {}).get(side) or {}).get("address"))
            if a and a not in skip:
                out.append(a)
    http.log("  raydium top pools %d mints" % len(out))
    return out


GP_COLS = ("address", "mintable", "freezable", "closable", "balMutable", "metaMutable", "transferFee", "nonTransferable", "trusted", "holderCount", "top10Pct", "lpBurnPct", "creatorMalicious", "dexN")
GI_COLS = ("address", "gtScore", "holders", "top10Pct", "mintAuth", "freezeAuth")
CM_COLS = ("address", "rcUp", "rcDown", "cgWatch", "cgTwitter", "cgReddit", "cgSentUp", "cgRank", "stWatch", "stMsgs24", "xFollowers", "xTweets7d", "tgSubs", "tgMsgs24")


def ds_orders(http, d, addrs, now=None):
    """'DEX paid': DexScreener's paid orders for a token (token profile, community takeover, ads) -> dp/<stamp>.txt. A team
    that paid for its DexScreener profile spent real money on the coin; trading terminals filter on it. One request per
    coin, paced to the endpoint's 60-per-minute limit, so only the shortlist gets it."""
    now = now or time.time()
    rows = []
    for a in addrs:
        if "api.dexscreener.com" in http.dead:
            break
        j = http.get(DS + "/orders/v1/solana/" + a)
        if not isinstance(j, list):
            continue
        ok = [o for o in j if isinstance(o, dict) and str(o.get("status")) == "approved"]
        prof = [o for o in ok if str(o.get("type")) == "tokenProfile"]
        paid_ms = max((num(o.get("paymentTimestamp")) or 0 for o in prof), default=0)
        rows.append(row(a, bool(prof), round((now - paid_ms / 1000.0) / 3600, 2) if paid_ms > 1e12 else None,
                        sum(1 for o in ok if str(o.get("type")) in ("tokenAd", "trendingBarAd")), any(str(o.get("type")) == "communityTakeover" for o in ok), len(j)))
        if not http.mock:
            time.sleep(1.0)
    n = write_rows(d, "dp", "dp_%d.txt" % int(time.time()), rows)
    http.log("  dex paid %d of %d (%d paid profiles)" % (n, len(addrs), sum(1 for r in rows if r.split("|")[1] == "true")))
    return n


def goplus(http, d, addrs):
    """GoPlus token security for the shortlist (20 mints per request) -> gp/<stamp>.txt: the authorities that can still mint,
    freeze, close or rewrite balances, a transfer fee, whether GoPlus trusts it, holders, the top-10 share and the LP burn."""
    rows = []
    flag = lambda v: (1 if str((v or {}).get("status") if isinstance(v, dict) else v) == "1" else 0) if v is not None else None
    for i in range(0, len(addrs), 20):
        data = http.get(GOPLUS + "?contract_addresses=" + ",".join(addrs[i:i + 20]))
        res = (data or {}).get("result") if isinstance(data, dict) else None
        for a, t in (res or {}).items():
            if not isinstance(t, dict):
                continue
            holders = [h for h in (t.get("holders") or []) if isinstance(h, dict)]
            top10 = sum(num(h.get("percent")) or 0 for h in holders[:10])
            top10 = top10 * 100 if top10 <= 1.0 else top10
            burns = [num(x.get("burn_percent")) for x in (t.get("dex") or []) if isinstance(x, dict) and num(x.get("burn_percent")) is not None]
            fee = t.get("transfer_fee") or {}
            fee_pct = num(fee.get("current_fee_rate") if isinstance(fee, dict) else fee)
            malicious = any(str((c or {}).get("malicious_address")) == "1" for c in (t.get("creators") or []) if isinstance(c, dict))
            rows.append(row(a, flag(t.get("mintable")), flag(t.get("freezable")), flag(t.get("closable")), flag(t.get("balance_mutable_authority")),
                            flag(t.get("metadata_mutable")), fee_pct, flag(t.get("non_transferable")), flag(t.get("trusted_token")),
                            num(t.get("holder_count")), round(top10, 2) if holders else None, max(burns) if burns else None, malicious, len(t.get("dex") or [])))
    n = write_rows(d, "gp", "gp_%d.txt" % int(time.time()), rows)
    http.log("  goplus security %d of %d" % (n, len(addrs)))
    return n


def gt_info(http, d, addrs):
    """GeckoTerminal token facts for the shortlist (30 per request, one request a time) -> gi/<stamp>.txt: GT score, holders,
    top-10 share, mint and freeze authority."""
    rows = []
    for i in range(0, len(addrs), 30):
        data = http.get(GT + "/networks/solana/tokens/multi/" + ",".join(addrs[i:i + 30]))
        for t in ((data or {}).get("data") or []) if isinstance(data, dict) else []:
            at = (t or {}).get("attributes") or {}
            h = at.get("holders") or {}
            dist = h.get("distribution_percentage") or {} if isinstance(h, dict) else {}
            rows.append(row(at.get("address"), num(at.get("gt_score")), num(h.get("count")) if isinstance(h, dict) else None, num(dist.get("top_10")),
                            None if at.get("mint_authority") is None else str(at.get("mint_authority")).lower() == "yes",
                            None if at.get("freeze_authority") is None else str(at.get("freeze_authority")).lower() == "yes"))
    n = write_rows(d, "gi", "gi_%d.txt" % int(time.time()), [r for r in rows if r.split("|", 1)[0]])
    http.log("  geckoterminal token info %d of %d" % (n, len(addrs)))
    return n


def community(http, d, addrs, meta, now=None):
    """What the public does with a shortlisted coin: RugCheck votes, CoinGecko community data (watchlists, followers,
    sentiment), StockTwits watchers and messages, the X account's followers and recent tweets, the Telegram channel's
    subscribers and recent messages -> cm/<stamp>.txt. Every part is optional; a source that fails leaves its fields empty."""
    now = now or time.time()
    rows = []
    for a in addrs:
        m = (meta or {}).get(a) or {}
        v = http.get(RC + "/tokens/%s/votes" % a)
        rc_up, rc_down = (num(v.get("up")), num(v.get("down"))) if isinstance(v, dict) else (None, None)
        cg = http.get(CG + "/coins/solana/contract/%s?localization=false&tickers=false&market_data=false&community_data=true&developer_data=false&sparkline=false" % a)
        cg = cg if isinstance(cg, dict) and cg.get("id") else {}
        cd = cg.get("community_data") or {}
        st_watch = st_msgs = None
        sym = re.sub(r"[^A-Za-z0-9]", "", str(m.get("sym") or ""))
        if sym and "api.stocktwits.com" not in http.dead:
            s = http.get(ST + "/%s.X.json" % sym.upper())
            if isinstance(s, dict) and isinstance(s.get("symbol"), dict):
                st_watch = num(s["symbol"].get("watchlist_count"))
                st_msgs = 0
                for msg in s.get("messages") or []:
                    try:
                        t = email.utils.parsedate_to_datetime(str(msg.get("created_at"))).timestamp() if "," in str(msg.get("created_at")) else dt.datetime.fromisoformat(str(msg.get("created_at")).replace("Z", "+00:00")).timestamp()
                    except (TypeError, ValueError):
                        continue
                    st_msgs += 1 if now - t <= 86400 else 0
        x_fol = x_tw = None
        handle = re.sub(r"^https://(www\.)?(x|twitter)\.com/", "", str(m.get("x") or "")).split("/")[0].split("?")[0]
        if handle and re.fullmatch(r"[A-Za-z0-9_]{1,30}", handle) and handle.lower() not in ("i", "search", "home", "intent") and "syndication.twitter.com" not in http.dead:
            page = http.get(XSYN + "/" + handle, kind="text") or ""
            mf = re.search(r'"followers_count":(\d+)', page)
            x_fol = num(mf.group(1)) if mf else None
            if mf:
                x_tw = 0
                for mt in re.finditer(r'"created_at":"([A-Z][a-z]{2} [A-Z][a-z]{2} \d\d \d\d:\d\d:\d\d \+0000 \d{4})"', page):
                    try:
                        if now - email.utils.parsedate_to_datetime(mt.group(1)).timestamp() <= 7 * 86400:
                            x_tw += 1
                    except (TypeError, ValueError):
                        pass
        tg_subs = tg_msgs = None
        chan = re.sub(r"^https?://(t\.me|telegram\.me)/(s/)?", "", str(m.get("tg") or "")).split("/")[0].split("?")[0]
        if chan and re.fullmatch(r"[A-Za-z0-9_]{3,40}", chan) and "t.me" not in http.dead:
            page = http.get(TG + "/" + chan, kind="text") or ""
            ms_ = re.search(r'<div class="tgme_header_counter">([\d\s.,]+)\s*(subscribers|members)', page) or re.search(r'<div class="tgme_page_extra">([\d\s.,]+)\s*(subscribers|members)', page)
            tg_subs = num(re.sub(r"[^\d]", "", ms_.group(1))) if ms_ else None
            if "tgme_widget_message" in page:
                tg_msgs = 0
                for mt in re.finditer(r'<time datetime="([^"]+)"', page):
                    try:
                        if now - dt.datetime.fromisoformat(mt.group(1).replace("Z", "+00:00")).timestamp() <= 86400:
                            tg_msgs += 1
                    except ValueError:
                        pass
        rows.append(row(a, rc_up, rc_down, num(cg.get("watchlist_portfolio_users")), num(cd.get("twitter_followers")), num(cd.get("reddit_subscribers")),
                        num(cg.get("sentiment_votes_up_percentage")), num(cg.get("market_cap_rank")), st_watch, st_msgs, x_fol, x_tw, tg_subs, tg_msgs))
    n = write_rows(d, "cm", "cm_%d.txt" % int(time.time()), rows)
    has = lambda i: sum(1 for r in rows if r.split("|")[i] not in ("", "null"))
    tried_x = sum(1 for a in addrs if str(((meta or {}).get(a) or {}).get("x") or "").strip())
    tried_tg = sum(1 for a in addrs if str(((meta or {}).get(a) or {}).get("tg") or "").strip())
    if tried_x >= 3 and has(10) == 0:
        http.log("  ! X: %d accounts looked up, no follower count read at all (did the syndication page change?)" % tried_x)
    if tried_tg >= 3 and has(12) == 0:
        http.log("  ! Telegram: %d channels looked up, no member count read at all (did the t.me preview change?)" % tried_tg)
    http.log("  community %d of %d (coingecko %d, stocktwits %d, x %d, telegram %d)" % (n, len(addrs), has(3), has(8), has(10), has(12)))
    return n


def bitquery_trades(http, d, addrs, token, now=None):
    """With a Bitquery token: the last 300 trades of each shortlisted coin straight from the chain (any DEX, any app, Fomo
    included). Every trader wallet goes to tb/<coin>.txt in GMGN's top-buyer format (status hold / sold_part / sold, tag
    dex:<protocol>), so the tb.* factors and the wallet memory work without GMGN; per coin bq/<stamp>.txt holds the last
    hour's trades, distinct buyers and sellers, net USD flow and the biggest buyer's share."""
    if not token:
        return 0
    now = now or time.time()
    since = dt.datetime.fromtimestamp(now - 6 * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, n_tb, first_err = [], 0, None
    for a in addrs:
        data = http.post(BQ, {"query": BQ_QUERY, "variables": {"mint": a, "since": since}}, headers={"Authorization": "Bearer " + token})
        if isinstance(data, dict) and data.get("errors") and first_err is None:
            first_err = str(data["errors"])[:160]
        trades = (((data or {}).get("data") or {}).get("Solana") or {}).get("DEXTradeByTokens") if isinstance(data, dict) else None
        if not isinstance(trades, list):
            if "streaming.bitquery.io" in http.dead:
                break
            continue
        per, dexes = {}, {}
        t1h = b1h = s1h = 0
        buy_usd = sell_usd = 0.0
        buyers_usd = {}
        for t in trades:
            tr, blk = (t or {}).get("Trade") or {}, (t or {}).get("Block") or {}
            w = addr_of((tr.get("Account") or {}).get("Owner")) or addr_of(((t or {}).get("Transaction") or {}).get("Signer"))
            side = str((tr.get("Side") or {}).get("Type") or "").lower()
            usd = num(tr.get("AmountInUSD"))
            if usd is None and num(tr.get("Amount")) is not None and num(tr.get("PriceInUSD")) is not None:
                usd = num(tr["Amount"]) * num(tr["PriceInUSD"])
            usd = usd or 0.0
            try:
                ts = dt.datetime.fromisoformat(str(blk.get("Time") or "").replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
            if not w:
                continue
            p = per.setdefault(w, [0.0, 0.0, set()])
            fam = str((tr.get("Dex") or {}).get("ProtocolFamily") or (tr.get("Dex") or {}).get("ProtocolName") or "").lower()
            if fam:
                p[2].add(fam)
            if side == "buy":
                p[0] += usd
            elif side == "sell":
                p[1] += usd
            if ts is not None and now - ts <= 3600:
                t1h += 1
                if side == "buy":
                    b1h += 1; buy_usd += usd; buyers_usd[w] = buyers_usd.get(w, 0.0) + usd
                elif side == "sell":
                    s1h += 1; sell_usd += usd
        tb_rows = []
        for w, (b, s, fams) in per.items():
            status = "hold" if b > 0 and s <= 0 else ("sold_part" if 0 < s < b else "sold")
            tb_rows.append(row(w, status, ";".join("dex:" + x for x in sorted(fams)) or None, None))
        n_tb += 1 if write_rows(d, "tb", a + ".txt", tb_rows) else 0
        buyers = {w for w, (b, s, _) in per.items() if b > 0}
        sellers = {w for w, (b, s, _) in per.items() if s > 0}
        top_share = (max(buyers_usd.values()) / buy_usd) if buy_usd > 0 and buyers_usd else None
        rows.append(row(a, t1h, len({w for w in buyers_usd}), s1h, round(buy_usd - sell_usd, 2), round(top_share, 4) if top_share is not None else None, len(per), round(buy_usd, 2), round(sell_usd, 2)))
    n = write_rows(d, "bq", "bq_%d.txt" % int(time.time()), rows)
    http.log("  bitquery trades %d of %d coins (%d trader files)%s" % (n, len(addrs), n_tb, (" ! " + first_err) if first_err else ""))
    return n


def lunarcrush_topics(http, d, addrs, meta, key):
    """With a LunarCrush key: the X/social topic of the best shortlisted coins ($TICKER) -> lc/<stamp>.txt: interactions,
    posts and contributors in 24h, sentiment, trend. The free plan allows ~100 requests a day, so only a few coins per run."""
    if not key:
        return 0
    rows = []
    for a in addrs:
        sym = re.sub(r"[^A-Za-z0-9]", "", str(((meta or {}).get(a) or {}).get("sym") or "")).lower()
        if not sym:
            continue
        data = http.get(LC + "/topic/$%s/v1" % sym, headers={"Authorization": "Bearer " + key})
        t = (data or {}).get("data") if isinstance(data, dict) else None
        if isinstance(t, dict):
            rows.append(row(a, num(t.get("interactions_24h")), num(t.get("num_posts")), num(t.get("num_contributors")), num(t.get("types_sentiment") if not isinstance(t.get("types_sentiment"), dict) else None),
                            num(t.get("trend")) if not isinstance(t.get("trend"), str) else {"up": 1.0, "down": -1.0, "flat": 0.0}.get(str(t.get("trend")).lower())))
        if "lunarcrush.com" in http.dead:
            break
    n = write_rows(d, "lc", "lc_%d.txt" % int(time.time()), rows)
    http.log("  lunarcrush topics %d of %d" % (n, len(addrs)))
    return n


HL_COLS = ("address", "top1Pct", "top10Pct", "top20Pct", "largestN", "supply")


def rpc_holders(http, d, addrs, known=()):
    """The chain itself: the 20 largest token accounts of a coin (getTokenLargestAccounts) against its supply -> hl/<stamp>.txt
    with the top-1, top-10 and top-20 shares. Only for shortlisted coins RugCheck had no report for (`known` are the ones it
    had): the public RPC throttles this call hard, so it is paced and gives up quietly."""
    rows = []
    todo = [a for a in addrs if a not in set(known)]
    for a in todo:
        if "api.mainnet-beta.solana.com" in http.dead:
            break
        sup = http.post(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [a]})
        supply = num((((sup or {}).get("result") or {}).get("value") or {}).get("uiAmount"))
        big = http.post(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [a]})
        if isinstance(big, dict) and isinstance(big.get("error"), dict):
            http.log("  ! rpc largest accounts: %s" % str(big["error"].get("message"))[:80])
            break                                     # throttled: the rest of the shortlist would be throttled too
        vals = sorted((num((v or {}).get("uiAmount")) or 0.0 for v in (((big or {}).get("result") or {}).get("value") or [])), reverse=True)
        if not supply or not vals:
            continue
        pct = lambda k: round(100.0 * sum(vals[:k]) / supply, 2)
        rows.append(row(a, pct(1), pct(10), pct(20), len(vals), supply))
        time.sleep(2.0)
    n = write_rows(d, "hl", "hl_%d.txt" % int(time.time()), rows)
    http.log("  chain holders %d of %d coins without a RugCheck report" % (n, len(todo)))
    return n


ANIMALS = re.compile(r"\b(monkey|monkeys|macaque|ape|apes|chimp|gorilla|cat|cats|kitten|kitty|dog|dogs|puppy|pup|doge|shiba|capybara|frog|frogs|toad|pepe|penguin|hamster|squirrel|raccoon|otter|bear|bears|panda|hippo|hippopotamus|moo deng|cow|cows|pig|piglet|duck|duckling|goat|bird|parrot|owl|fish|rat|mouse|seal|sloth|fox|wolf|lion|tiger|elephant|turtle|tortoise|rabbit|bunny|chick|chicken|giraffe|zebra|koala|kangaroo|llama|alpaca|dolphin|shark|octopus|snail|hedgehog|deer|moose|donkey|horse|pony|lamb|sheep|bat|crab|lobster|axolotl|quokka|wombat|lemur|baboon|orangutan)\b", re.I)


def tweet_token(tid):
    """The token the syndication endpoint wants with a tweet id (the same arithmetic the embed code uses)."""
    x = (int(tid) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    ip, fr = int(x), x - int(x)
    s = ""
    while ip:
        s, ip = digits[ip % 36] + s, ip // 36
    f = ""
    for _ in range(11):
        fr *= 36
        f += digits[int(fr)]
        fr -= int(fr)
    return re.sub(r"(0+|\.)", "", (s or "0") + "." + f)


def viral(http, d, addrs, meta, now=None):
    """The story behind a coin: when its X link points at one tweet (x.com/<user>/status/<id>), that tweet's likes, replies,
    age, author and text -> vt/<stamp>.txt. A coin launched off a tweet with tens of thousands of likes posted hours ago is
    the 'viral real story' pattern; the text also says whether the story is about an animal. Coins whose link is only a
    profile are skipped (the profile's followers are read by community())."""
    now = now or time.time()
    rows, tried = [], 0
    for a in addrs:
        m = (meta or {}).get(a) or {}
        mt = re.search(r"^https://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,30})/status/(\d{5,25})", str(m.get("x") or ""))
        if not mt or "cdn.syndication.twimg.com" in http.dead:
            continue
        tried += 1
        tid = mt.group(2)
        j = http.get("%s?id=%s&token=%s&lang=en" % (XTW, tid, tweet_token(tid)))
        if not isinstance(j, dict) or j.get("__typename") == "TweetTombstone" or not (j.get("id_str") or j.get("text") is not None):
            continue
        age_h = None
        try:
            age_h = round((now - dt.datetime.fromisoformat(str(j.get("created_at") or "").replace("Z", "+00:00")).timestamp()) / 3600, 2)
        except (TypeError, ValueError):
            pass
        u = j.get("user") if isinstance(j.get("user"), dict) else {}
        text = re.sub(r"\s+", " ", str(j.get("text") or "")).strip()
        animal = bool(ANIMALS.search(text) or ANIMALS.search(str(m.get("sym") or "")))
        rows.append(row(a, tid, num(j.get("favorite_count")), num(j.get("conversation_count")), age_h, num(u.get("followers_count")),
                        bool(u.get("verified") or u.get("is_blue_verified")), bool(j.get("mediaDetails") or j.get("photos") or j.get("video")),
                        animal, txt(u.get("screen_name") or mt.group(1), 30), txt(text, 160)))
    n = write_rows(d, "vt", "vt_%d.txt" % int(time.time()), rows)
    if tried >= 3 and n == 0:
        http.log("  ! tweets: %d status links looked up, none read (did the syndication endpoint change?)" % tried)
    http.log("  source tweets %d of %d status links (%d coins)" % (n, tried, len(addrs)))
    return n


def cmd_risk(http, d, addrs, meta=None):
    n = rc_reports(http, d, addrs)
    reported = set()
    for fn in glob.glob(os.path.join(d, "risk", "*.txt")):
        for line in open(fn, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                reported.add(line.split("|", 1)[0])
    rpc_holders(http, d, addrs[:16], reported)
    goplus(http, d, addrs)
    gt_info(http, d, addrs[:30])
    dev_check(http, d, addrs[:24])
    community(http, d, addrs[:20], meta)
    viral(http, d, addrs[:60], meta)
    ds_orders(http, d, addrs[:40])
    bitquery_trades(http, d, addrs[:40], os.environ.get("BITQUERY_TOKEN"))
    lunarcrush_topics(http, d, addrs[:4], meta, os.environ.get("LUNARCRUSH_API_KEY"))
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
    ap.add_argument("cmd", choices=["sources", "deep", "tokens", "refresh", "risk", "news"])
    ap.add_argument("--dir", default="mb")
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--addrs", default="")
    ap.add_argument("--from-gather", default="", help="a gather/shortlist JSON file whose chunks/shortlist give the addresses")
    ap.add_argument("--meta", default="", help="risk: a JSON file {address: {sym, x, tg}} for the community lookups")
    ap.add_argument("--mock", default=os.environ.get("MEMEBOT_MOCK", ""))
    ap.add_argument("--pause", type=float, default=float(os.environ.get("MEMEBOT_PAUSE", "0.3")))
    a = ap.parse_args()
    http = Http(a.mock, a.pause)
    os.makedirs(a.dir, exist_ok=True)
    if a.cmd == "sources":
        cmd_sources(http, a.dir, a.light)
    elif a.cmd == "deep":
        print(json.dumps({"pairs": cmd_deep(http, a.dir)}))
    elif a.cmd == "tokens":
        print(json.dumps({"rows": cmd_tokens(http, a.dir, addrs_arg(a))}))
    elif a.cmd == "refresh":
        print(json.dumps({"rows": cmd_refresh(http, a.dir, addrs_arg(a))}))
    elif a.cmd == "risk":
        meta = {}
        if a.meta and os.path.exists(a.meta):
            with open(a.meta, encoding="utf-8") as f:
                meta = json.load(f) or {}
        print(json.dumps({"reports": cmd_risk(http, a.dir, addrs_arg(a), meta if isinstance(meta, dict) else {})}))
    else:
        print(json.dumps({"news": news(http, a.dir)}))


if __name__ == "__main__":
    main()
