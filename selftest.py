#!/usr/bin/env python3
"""selftest.py: runs the whole bot against a local mock of every API (~1100 synthetic coins) with a fake clock.

  python3 selftest.py            -> prints each cycle's note and PASS/FAIL per check, exit code 1 on any failure

What it proves: the fetch layer parses every source's response shape into the pipe-row files, gather merges them into a 1000+ coin
universe, the scan gates and scores them, exactly two coins get bought for 20 each out of the 40 bankroll, no third buy happens
while the money is deployed, exits (half at 2x, stop at -50%, 3-day time limit) return money to the bankroll, the 24h big test
scores every snapshotted coin and the weights get learned. GMGN is mocked as blocked (403) to exercise the circuit breaker.
"""
import glob, json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
WORDS = "dog cat pepe frog elon trump moon inu wif bonk chad doge baby meme giga degen ape monkey bear bull penguin hat rocket fart goat duck whale pig".split()
T0 = int(time.time() * 1000)
H = 3_600_000


def mk_universe(n=1100, seed=7):
    rng = random.Random(seed)
    coins = []
    for i in range(n):
        a = "".join(rng.choice(ALPH) for _ in range(44))
        w = rng.choice(WORDS)
        sym = (w + str(i % 97)).upper()[:10]
        mc = 10 ** rng.uniform(4.3, 8.3)
        liq = mc * rng.uniform(0.01, 0.6)
        vol = mc * rng.uniform(0.02, 3.0)
        age_h = 10 ** rng.uniform(-1, 3)
        dex = rng.choices(["raydium", "pumpswap", "meteora", "pumpfun", "orca"], [40, 30, 15, 10, 5])[0]
        b24 = int(rng.uniform(50, 5000)); s24 = int(b24 * rng.uniform(0.4, 1.6))
        lp = rng.uniform(0, 100)
        risks = []
        r = rng.random()
        if r < 0.15:
            risks.append({"name": "Low amount of LP Providers", "level": "danger", "score": 5000})
        elif r < 0.35:
            risks.append({"name": rng.choice(["Top 10 holders high ownership", "Mutable metadata", "Creator history of rugged tokens", "Low Liquidity"]), "level": "warn", "score": 1000})
        coins.append({"a": a, "sym": sym, "name": w.title() + (" 🐕 Coin " if i % 3 == 0 else " Coin ") + str(i), "px": 10 ** rng.uniform(-6, -1), "mc": mc, "liq": liq, "vol": vol,
                      "age_h": age_h, "dex": dex, "b24": b24, "s24": s24, "b1": int(b24 / 24 * rng.uniform(0.5, 2)), "s1": int(s24 / 24 * rng.uniform(0.5, 2)),
                      "chg": [rng.uniform(-30, 60) for _ in range(4)], "x": rng.random() < 0.6, "lp": lp, "risks": risks, "kw": w,
                      "holders": [ "".join(rng.choice(ALPH) for _ in range(44)) for _ in range(5)], "mult": 1.0, "gone": False})
    return coins


class Mock:
    def __init__(self):
        self.coins = mk_universe()
        self.by_a = {c["a"]: c for c in self.coins}
        self.now = T0
        self.hits = {}

    def pair(self, c):
        px = 0.0 if c["gone"] else c["px"] * c["mult"]
        liq = 0.0 if c["gone"] else c["liq"]
        socials = [{"type": "twitter", "url": "https://x.com/" + c["sym"].lower()}] if c["x"] else []
        return {"chainId": "solana", "dexId": c["dex"], "pairAddress": c["a"][:20] + "pair", "baseToken": {"address": c["a"], "symbol": c["sym"], "name": c["name"]},
                "priceUsd": "%.10f" % px, "marketCap": c["mc"] * c["mult"], "fdv": c["mc"] * c["mult"] * 1.1, "liquidity": {"usd": liq},
                "volume": {"h24": c["vol"], "h6": c["vol"] / 3, "h1": c["vol"] / 20}, "priceChange": dict(zip(("m5", "h1", "h6", "h24"), c["chg"])),
                "txns": {"h24": {"buys": c["b24"], "sells": c["s24"]}, "h6": {"buys": c["b24"] // 4, "sells": c["s24"] // 4}, "h1": {"buys": c["b1"], "sells": c["s1"]}},
                "pairCreatedAt": int(T0 - c["age_h"] * H), "boosts": {"active": 10}, "info": {"websites": [{"url": "https://e.com"}], "socials": socials}}

    def gt_pool(self, c):
        return {"id": "solana_" + c["a"][:20] + "pool", "type": "pool", "attributes": {"name": c["sym"] + " / SOL", "address": c["a"][:20] + "pool",
                "base_token_price_usd": str(c["px"] * c["mult"]), "fdv_usd": str(c["mc"]), "reserve_in_usd": str(c["liq"]), "volume_usd": {"h24": str(c["vol"])},
                "price_change_percentage": {"h1": "1.5", "h6": "-2", "h24": "10"}, "transactions": {"h24": {"buys": c["b24"], "sells": c["s24"], "buyers": c["b24"] // 3, "sellers": c["s24"] // 3}},
                "pool_created_at": "2025-01-01T00:00:00Z"}, "relationships": {"base_token": {"data": {"id": "solana_" + c["a"], "type": "token"}}, "dex": {"data": {"id": c["dex"]}}}}

    def handle_post(self, path, body):
        """The public Solana RPC: signatures of a creator wallet and the decoded transactions (coin index % 5 == 2: the creator sold)."""
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            return 400, {"error": "bad json"}
        method, params = req.get("method"), req.get("params") or []
        if path.startswith("/streaming.bitquery.io/eap"):
            mint = ((req.get("variables") or {}).get("mint") or "")
            c = self.by_a.get(mint)
            if not c:
                return 200, {"data": {"Solana": {"DEXTradeByTokens": []}}}
            stamp = lambda i: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300 * i))
            trades = [{"Block": {"Time": stamp(i)}, "Trade": {"Side": {"Type": "buy" if i % 3 else "sell"}, "Amount": "1000", "AmountInUSD": str(50 + 10 * i), "PriceInUSD": "0.05",
                                                          "Account": {"Owner": "W%s%s" % (mint[:30], chr(65 + i) * 2)}, "Dex": {"ProtocolName": "pump_amm", "ProtocolFamily": "Pumpswap"}}, "Transaction": {"Signer": "S%s" % mint[:40]}}
                      for i in range(24)]
            return 200, {"data": {"Solana": {"DEXTradeByTokens": trades}}}
        if path.startswith("/api.mainnet-beta.solana.com"):
            if method == "getSignaturesForAddress":
                dev = str(params[0]); sold = any(c["a"][3:] == dev[3:] and self.coins.index(c) % 5 == 2 for c in self.coins if dev.startswith("DEV"))
                return 200, {"jsonrpc": "2.0", "result": [{"signature": "sig%s%d" % (dev[-6:], i), "blockTime": int(self.now / 1000) - 600 * (i + 1)} for i in range(3 if sold else 1)], "id": 1}
            if method == "getTokenSupply":
                return 200, {"jsonrpc": "2.0", "result": {"value": {"amount": "1000000000", "decimals": 0, "uiAmount": 1000000000.0}}, "id": 1}
            if method == "getTokenLargestAccounts":
                return 200, {"jsonrpc": "2.0", "result": {"value": [{"address": "acc%d" % i, "uiAmount": 30000000.0 - 1000000.0 * i} for i in range(20)]}, "id": 1}
            if method == "getTransaction":
                sig = str(params[0]); dev6 = sig[3:9]
                c = next((c for c in self.coins if c["a"][3:][-6:] == dev6), None)
                sold = bool(c) and self.coins.index(c) % 5 == 2 and sig.endswith("0")
                mint = c["a"] if c else "x"; owner = "DEV" + mint[3:]
                return 200, {"jsonrpc": "2.0", "result": {"meta": {"preTokenBalances": [{"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": 1000.0}}],
                                                                   "postTokenBalances": [{"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": 400.0 if sold else 1000.0}}]}}, "id": 1}
            return 200, {"jsonrpc": "2.0", "result": None, "id": 1}
        return 404, {"error": "no post route " + path}

    def handle(self, path, query):
        self.hits[path.split("/")[1]] = self.hits.get(path.split("/")[1], 0) + 1
        q = urllib.parse.parse_qs(query)
        if "/__429" in path:
            self.n429 = getattr(self, "n429", 0) + 1
            return (429, {"err": "slow down"}) if self.n429 <= 2 else (200, {"ok": True})
        if path.startswith("/__mult"):
            c = self.by_a[q["a"][0]]; c["mult"] = float(q["m"][0]); c["gone"] = q.get("gone", ["0"])[0] == "1"
            return 200, {"ok": True}
        if path.startswith("/gmgn.ai/"):
            return 403, {"blocked": True}
        if path.startswith("/api.dexscreener.com/"):
            p = path[len("/api.dexscreener.com"):]
            if p in ("/token-boosts/top/v1", "/token-boosts/latest/v1", "/token-profiles/latest/v1", "/community-takeovers/latest/v1", "/ads/latest/v1"):
                off = {"/token-boosts/top/v1": 0, "/token-boosts/latest/v1": 30, "/token-profiles/latest/v1": 60, "/community-takeovers/latest/v1": 90, "/ads/latest/v1": 120}[p]
                return 200, [{"chainId": "solana", "tokenAddress": c["a"]} for c in self.coins[off:off + 30]] + [{"chainId": "ethereum", "tokenAddress": "0xabc"}]
            if p == "/latest/dex/search":
                kw = q.get("q", [""])[0]
                hits = [c for c in self.coins if c["kw"] == kw][:30]
                if not hits:
                    rng = random.Random(kw); hits = rng.sample(self.coins, 30)
                return 200, {"pairs": [self.pair(c) for c in hits]}
            if p.startswith("/tokens/v1/solana/"):
                out = []
                for a in p.rsplit("/", 1)[1].split(","):
                    if a in self.by_a and not self.by_a[a]["gone"]:
                        out.append(self.pair(self.by_a[a]))
                return 200, out
        if path.startswith("/api.rugcheck.xyz/v1/stats/"):
            off = {"new_tokens": 150, "trending": 1000, "recent": 1030, "verified": 1060}.get(path.rsplit("/", 1)[1], 150)
            return 200, [{"mint": c["a"]} for c in self.coins[off:off + 50]]
        mv = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/votes$", path)
        if mv:
            return 200, {"up": 40, "down": 3, "userVoted": False}
        if path.startswith("/api.gopluslabs.io/api/v1/solana/token_security"):
            res = {}
            for a in q.get("contract_addresses", [""])[0].split(","):
                c = self.by_a.get(a)
                if c:
                    i = self.coins.index(c)
                    res[a] = {"mintable": {"status": "1" if i % 11 == 5 else "0"}, "freezable": {"status": "0"}, "closable": {"status": "0"}, "balance_mutable_authority": {"status": "0"},
                              "metadata_mutable": {"status": "0"}, "transfer_fee": {}, "non_transferable": "0", "trusted_token": 1 if i % 3 == 0 else 0, "holder_count": 1500,
                              "holders": [{"account": "h%d" % k, "percent": "0.02"} for k in range(10)], "dex": [{"dex_name": "raydium", "burn_percent": 100}], "creators": []}
            return 200, {"code": 1, "message": "ok", "result": res}
        if path.startswith("/lite-api.jup.ag/price/v3"):
            out = {}
            for a in q.get("ids", [""])[0].split(","):
                c = self.by_a.get(a)
                if c and not c["gone"]:
                    out[a] = {"usdPrice": c["px"] * c["mult"], "liquidity": c["liq"], "priceChange24h": 1.0}
                elif a.startswith("JUPXFALLBACK"):
                    out[a] = {"usdPrice": 0.000123, "liquidity": 55555.0, "priceChange24h": 1.0}
            return 200, out
        if path.startswith("/api.geckoterminal.com/api/v2/networks/solana/tokens/multi/"):
            addrs = path.rsplit("/", 1)[1].split(",")
            return 200, {"data": [{"id": "solana_" + a, "type": "token", "attributes": {"address": a, "gt_score": 70.5, "holders": {"count": 1800, "distribution_percentage": {"top_10": "18.5"}}, "mint_authority": "no", "freeze_authority": "no"}} for a in addrs if a in self.by_a]}
        if path.startswith("/api.orca.so/v2/solana/pools"):
            return 200, {"data": [{"address": "p%d" % i, "tokenMintA": "So11111111111111111111111111111111111111112", "tokenMintB": c["a"]} for i, c in enumerate(self.coins[700:760])]}
        if path.startswith("/api.alternative.me/fng/"):
            return 200, {"name": "Fear and Greed Index", "data": [{"value": "66", "value_classification": "Greed"}]}
        if path.startswith("/api.coingecko.com/api/v3/simple/price"):
            return 200, {"solana": {"usd": 120.0, "usd_24h_change": -2.5}, "bitcoin": {"usd": 90000.0, "usd_24h_change": -1.0}}
        if path.startswith("/api.coingecko.com/api/v3/coins/solana/contract/"):
            a = path.rsplit("/", 1)[1].split("?")[0]
            if a in self.by_a:
                return 200, {"id": "c-" + a[:6], "watchlist_portfolio_users": 2500, "sentiment_votes_up_percentage": 71.0, "market_cap_rank": 900, "community_data": {"twitter_followers": 12000, "reddit_subscribers": 300}}
            return 404, {"error": "coin not found"}
        if path.startswith("/api.warpcast.com/v2/search-casts"):
            return 200, {"result": {"casts": [{"hash": "0x%d" % i, "text": "ape in %s CA %s $%s" % (c["name"], c["a"], c["sym"]), "timestamp": int(T0 - 600000 * i), "author": {"followerCount": 100}} for i, c in enumerate(self.coins[12:20])]}}
        if path.startswith("/mastodon.social/api/v1/timelines/tag/"):
            return 200, [{"id": str(i), "content": "<p>$%s is moving, ca %s</p>" % (c["sym"], c["a"]), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(T0 / 1000 - 900 * i))} for i, c in enumerate(self.coins[20:26])]
        if path.startswith("/a.4cdn.org/biz/catalog.json"):
            return 200, [{"page": 1, "threads": [{"no": i, "sub": "%s thread" % c["sym"], "com": "buy $%s now<br>%s" % (c["sym"], c["a"]), "time": int(T0 / 1000 - 3600 * i), "last_modified": int(T0 / 1000 - 60 * i)} for i, c in enumerate(self.coins[26:32])]}]
        if path.startswith("/api.stocktwits.com/api/2/streams/symbol/"):
            sym = path.rsplit("/", 1)[1].replace(".X.json", "")
            if any(c["sym"] == sym for c in self.coins):
                return 200, {"symbol": {"symbol": sym + ".X", "watchlist_count": 777}, "messages": [{"id": i, "body": "x", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 / 1000 - 3000 * i))} for i in range(12)]}
            return 404, {"errors": [{"message": "not found"}]}
        if path.startswith("/syndication.twitter.com/srv/timeline-profile/screen-name/"):
            return 200, '<html><script id="__NEXT_DATA__">{"props":{"user":{"followers_count":45678},"entries":[%s]}}</script></html>' % ",".join(
                '{"created_at":"%s"}' % time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(T0 / 1000 - 86400 * i)) for i in range(5))
        if path.startswith("/t.me/s/"):
            return 200, '<html><div class="tgme_header_counter">12 345 members</div>%s</html>' % "".join('<div class="tgme_widget_message"><time datetime="%s"></time></div>' % time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(T0 / 1000 - 7200 * i)) for i in range(6))
        if "/rss/search" in path:
            items = "".join("<item><title>%s coin %s in the news</title><pubDate>%s</pubDate></item>" % (c["name"], c["sym"], time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(T0 / 1000 - 3600 * i))) for i, c in enumerate(self.coins[8:12]))
            return 200, '<?xml version="1.0"?><rss version="2.0"><channel><title>g</title>%s</channel></rss>' % items
        m = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/report$", path)
        if m and m.group(1) in self.by_a:
            c = self.by_a[m.group(1)]
            return 200, {"mint": c["a"], "score": 1500, "score_normalised": 12, "risks": c["risks"], "totalHolders": 1234, "tokenMeta": {"mutable": False},
                         "token": {"supply": 1e15}, "creatorBalance": 1e13, "graphInsidersDetected": 2,
                         "topHolders": [{"owner": h, "pct": 5.0 - i, "insider": i == 0} for i, h in enumerate(c["holders"])],
                         "markets": [{"lp": {"lpLockedPct": c["lp"]}}], "launchpad": {"name": "pump.fun"}}
        if path.startswith("/api.geckoterminal.com/"):
            if path.endswith("/networks/solana/dexes"):
                return 200, {"data": [{"id": x, "type": "dex", "attributes": {"name": x}} for x in ("raydium", "orca", "pumpswap", "meteora", "launchlab")]}
            pg = int(q.get("page", ["1"])[0])
            m2 = re.search(r"/dexes/([^/]+)/pools", path)
            if m2:
                kind, base = "dex", 600 + 40 * (("pumpswap", "raydium", "launchlab", "meteora", "raydium-clmm", "orca").index(m2.group(1)) if m2.group(1) in ("pumpswap", "raydium", "launchlab", "meteora", "raydium-clmm", "orca") else 6)
            else:
                kind = "trending" if "trending" in path else ("new" if "new_pools" in path else "top")
                base = {"trending": 200, "new": 300, "top": 400}[kind] + {"1h": 60, "6h": 120}.get(q.get("duration", ["24h"])[0], 0)
            off = base + (pg - 1) * 20
            sub = self.coins[off:off + 20] if pg <= 3 else []        # a short list: later pages are empty, like the real API past its end
            return 200, {"data": [self.gt_pool(c) for c in sub], "included": [{"id": "solana_" + c["a"], "type": "token", "attributes": {"symbol": c["sym"], "name": c["name"]}} for c in sub]}
        if path.startswith("/api.coingecko.com/api/v3/coins/list"):
            return 200, [{"id": "c%d" % i, "symbol": c["sym"].lower(), "name": c["name"], "platforms": {"solana": c["a"]}} for i, c in enumerate(self.coins[:60])]
        if path.startswith("/api.coingecko.com/api/v3/coins/markets"):
            return 200, [{"id": "c%d" % i, "symbol": c["sym"].lower(), "name": c["name"], "market_cap_rank": 300 + i, "total_volume": 150000 + i,
                          "price_change_percentage_1h_in_currency": 1.5, "price_change_percentage_24h_in_currency": 9.0} for i, c in enumerate(self.coins[:40])]
        if path.startswith("/api.coingecko.com/"):
            return 200, {"coins": [{"item": {"symbol": c["sym"], "name": c["name"], "market_cap_rank": 500 + i, "data": {"price_change_percentage_24h": {"usd": 3.3}}}} for i, c in enumerate(self.coins[:15])]}
        if path.startswith("/www.reddit.com/"):
            stamp = lambda i: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(T0 / 1000 - 1800 * i))
            entries = "".join('<entry><title>%s to the moon? $%s looks ready</title><content type="html">&lt;p&gt;CA: %s  $%s&lt;/p&gt;</content><updated>%s</updated><link href="https://www.reddit.com/r/x/%d"/></entry>' % (
                c["name"], c["sym"], c["a"], c["sym"], stamp(i), i) for i, c in enumerate(self.coins[:12]))
            return 200, '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>r/x</title>%s</feed>' % entries
        if path.startswith("/api.coinmarketcap.com/data-api/v3/topsearch/rank"):
            return 200, {"data": {"cryptoTopSearchRanks": [{"symbol": c["sym"], "name": c["name"], "marketCap": c["mc"], "priceChange": {"priceChange24h": 2.0}} for c in self.coins[:10]]}}
        if path.startswith("/api.coinmarketcap.com/data-api/v3/cryptocurrency/listing"):
            return 200, {"data": {"cryptoCurrencyList": [{"symbol": c["sym"], "name": c["name"], "cmcRank": 2000 + i, "platform": {"token_address": c["a"]}, "quotes": [{"percentChange24h": 40.0, "marketCap": c["mc"]}]} for i, c in enumerate(self.coins[:20])]}}
        if path.startswith("/frontend-api-v3.pump.fun/coins"):
            off = int(q.get("offset", ["0"])[0])
            base = 500 if "market_cap" in q.get("sort", [""])[0] else (650 if "currently-live" in path else (750 if q.get("complete") else 700))
            return 200, [{"mint": c["a"], "symbol": c["sym"], "name": c["name"], "usd_market_cap": c["mc"], "market_cap": 50, "ath_market_cap": c["mc"] * 2, "reply_count": 12,
                          "is_currently_live": False, "complete": True, "created_timestamp": T0 - 5 * H, "twitter": "https://x.com/a", "website": None, "telegram": "https://t.me/" + c["sym"].lower() + "chat"}
                         for c in self.coins[base + off:base + off + 50]]
        if path.startswith("/lite-api.jup.ag/tokens/v2/search") and q.get("query", [""])[0] in self.by_a:
            c = self.by_a[q["query"][0]]
            i = self.coins.index(c)
            return 200, [{"id": c["a"], "symbol": c["sym"], "name": c["name"], "dev": "DEV" + c["a"][3:], "holderCount": 1500, "organicScore": 60.0,
                          "audit": {"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "topHoldersPercentage": 20.0, "devBalancePercentage": 12.0 if i % 7 == 3 else 1.0}}]
        if path.startswith("/launch-mint-v1.raydium.io/get/list"):
            base = {"new": 1060, "lastTrade": 1070, "marketCap": 1080}.get(q.get("sort", ["new"])[0], 1060)
            return 200, {"success": True, "data": {"rows": [{"mint": c["a"], "symbol": c["sym"], "name": c["name"], "creator": "DEV" + c["a"][3:], "marketCap": c["mc"], "volumeU": c["vol"], "createAt": T0 - 4 * H, "poolId": "pool" + c["a"][:10], "finishingRate": 1}
                                                            for c in self.coins[base:base + 20]]}}
        if path.startswith("/api-v3.raydium.io/pools/info/list"):
            return 200, {"success": True, "data": {"count": 20, "data": [{"id": "p" + c["a"][:8], "mintA": {"address": c["a"]}, "mintB": {"address": "So11111111111111111111111111111111111111112"}} for c in self.coins[40:60]]}}
        if path.startswith("/lite-api.jup.ag/tokens/v2/"):
            off = {"toptrending": 800, "toporganicscore": 850, "recent": 900, "toptraded": 950, "tag": 1000, "search": 1050}[path.split("/")[4].split("?")[0]]
            off += {"1h": 20, "6h": 40}.get(path.rstrip("/").rsplit("/", 1)[-1], 0)
            return 200, [{"id": c["a"], "symbol": c["sym"], "name": c["name"], "usdPrice": c["px"] * c["mult"], "mcap": c["mc"] * c["mult"], "fdv": c["mc"] * c["mult"], "liquidity": c["liq"], "holderCount": 900,
                          "organicScore": 55.5, "audit": {"topHoldersPercentage": 22.0}, "isVerified": False, "firstPool": {"createdAt": "2025-03-01T00:00:00Z"},
                          "stats1h": {"priceChange": 1.0, "numBuys": 10, "numSells": 5, "numNetBuyers": 3}, "stats6h": {"priceChange": 2.0},
                          "stats24h": {"priceChange": 5.0, "buyVolume": 1000, "sellVolume": 800, "numBuys": 100, "numSells": 80, "numTraders": 50, "numNetBuyers": 10, "holderChange": 20}}
                         for c in self.coins[off:off + 50]]
        if path.startswith("/lunarcrush.com/api4/public/topic/"):
            return 200, {"data": {"topic": path.split("/")[-2], "interactions_24h": 123456, "num_posts": 321, "num_contributors": 87, "types_sentiment": 71, "trend": "up"}}
        if path.startswith("/lunarcrush.com/"):
            return 200, {"data": [{"symbol": c["sym"], "name": c["name"], "interactions_24h": 50000, "social_volume_24h": 300, "creators_active": 40, "sentiment": 80, "galaxy_score": 60, "alt_rank": 100} for c in self.coins[:50]]}
        if path.endswith(("/rss/", "/rss", "/feed", "/feed/", "/rss.xml")):
            items = "".join("<item><title>%s coin %s pumps as %s season returns</title><pubDate>%s</pubDate></item>" % (
                c["name"], c["sym"], c["kw"], time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(T0 / 1000 - 3600 * i))) for i, c in enumerate(self.coins[:8]))
            return 200, '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>%s</channel></rss>' % items
        return 404, {"error": "no route " + path}


def serve(mock):
    class Hd(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            code, body = mock.handle(u.path, u.query)
            raw = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code); self.send_header("Content-Type", "text/xml" if isinstance(body, str) else "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            code, body = mock.handle_post(u.path, body)
            raw = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    mock = Mock()
    srv = serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    d = tempfile.mkdtemp(prefix="memebot-test-")
    os.environ["LUNARCRUSH_API_KEY"] = "test"
    os.environ["BITQUERY_TOKEN"] = "test"
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)

    def cycle(now, force=False, rescan=False):
        cmd = [PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(now)] + (["--force"] if force else []) + (["--rescan"] if rescan else [])
        p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
        print(p.stdout.rstrip())
        if p.returncode != 0:
            print(p.stderr[-3000:]); check(False, "cycle exited %d" % p.returncode)
        return p.stdout, p.stderr

    def docs(coll):
        import glob
        return {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(d, "db", coll, "*.json"))}

    def cash():
        return json.loads(subprocess.run([PY, os.path.join(HERE, "memebot.py"), "cash", "--dir", d], capture_output=True, text=True).stdout)

    print("== fetch under a non-UTF-8 locale (Windows cp1252 crash)")
    enc_dir = tempfile.mkdtemp(prefix="memebot-enc-")
    r = subprocess.run([PY, os.path.join(HERE, "fetch.py"), "sources", "--dir", enc_dir, "--mock", url, "--light", "--pause", "0"], capture_output=True, text=True,
                       env=dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LANG="C"))
    check(r.returncode == 0 and "Traceback" not in r.stderr, "fetch.py writes coin names with emoji under an ASCII locale")
    shutil.rmtree(enc_dir, ignore_errors=True)

    print("== rate limit: a 429 is waited out, not given up on")
    sys.path.insert(0, HERE); import fetch as F, time as T
    F.time.sleep = lambda s: None                     # no real waiting in the test
    h = F.Http(url, pause=0)
    got = h.get("https://api.dexscreener.com/__429")
    check(got == {"ok": True} and h.limited == 2 and "api.dexscreener.com" not in h.dead, "429 twice, then the answer (%s waits)" % h.limited)

    print("== cycle 1: first full scan, expect 2 buys of 20")
    out, err = cycle(T0)
    g = json.loads(subprocess.run([PY, os.path.join(HERE, "memebot.py"), "gather", "--dir", d, "--now", str(T0)], capture_output=True, text=True).stdout)
    check(g["coins"] >= 1000, "universe has %d coins (>= 1000)" % g["coins"])
    check(g["geckoterminal"] > 0 and g["pumpfun"] > 0 and g["jupiter"] > 0 and g["coingecko"] > 0 and g["news"] > 0, "every mocked source parsed: gt %d pf %d jup %d cg %d news %d" % (g["geckoterminal"], g["pumpfun"], g["jupiter"], g["coingecko"], g["news"]))
    check(g.get("reddit", 0) >= 30 and g.get("cgMeme", 0) >= 40 and g["lists"].get("reddit", 0) >= 30 and g["lists"].get("cmcGain", 0) >= 20 and g["lists"].get("orcaVol", 0) >= 50,
          "publicity sources parsed: %s social mentions (reddit, farcaster, mastodon, 4chan), coingecko meme list %s, cmc gainers %s, orca %s" % (g.get("reddit"), g.get("cgMeme"), g["lists"].get("cmcGain"), g["lists"].get("orcaVol")))
    check("giving up on gmgn.ai" in err, "GMGN 403 trips the circuit breaker")
    devrows = [l for f in glob.glob(os.path.join(d, "dev", "*.txt")) for l in open(f, encoding="utf-8").read().splitlines() if l.strip() and not l.startswith("#")]
    check(devrows and "creator check" in err, "the creator check wrote %d rows (Jupiter facts + RPC transactions)" % len(devrows))
    side = lambda sub: [l for f in glob.glob(os.path.join(d, sub, "*.txt")) for l in open(f, encoding="utf-8").read().splitlines() if l.strip() and not l.startswith("#")]
    gp, gi, cm = side("gp"), side("gi"), side("cm")
    check(gp and gi and cm and "goplus security" in err and "community" in err, "GoPlus (%d), GeckoTerminal info (%d) and community (%d) rows written for the shortlist" % (len(gp), len(gi), len(cm)))
    fv = lambda l, i: float(l.split("|")[i]) if l.split("|")[i] not in ("", "null") else None
    check(cm and all(len(l.split("|")) == 14 for l in cm) and any(fv(l, 1) == 40 for l in cm) and any(fv(l, 3) == 2500 for l in cm) and any(fv(l, 10) == 45678 for l in cm) and any(fv(l, 12) == 12345 for l in cm),
          "community rows carry RugCheck votes, CoinGecko watchlists, X followers and Telegram members (%s)" % (cm[0][:140] if cm else "-"))
    import memebot as MB
    v_gp = MB.risk_view({"lpLocked": 100, "top1Pct": 3, "top10Pct": 20, "insiders": 1, "holders": 2000, "creatorPct": 1, "gp": {"mintable": 1, "freezable": 0}})
    v_gp2 = MB.risk_view({"lpLocked": 100, "top1Pct": 3, "top10Pct": 20, "insiders": 1, "holders": 2000, "creatorPct": 1, "gp": {"mintable": 0, "trusted": 1, "lpBurnPct": 100}, "cm": {"rcUp": 40, "rcDown": 3, "cgWatch": 2500}})
    check(v_gp[0] is False and "minted" in v_gp[1] and v_gp2[0] is True and "GoPlus" in v_gp2[1] and "community votes" in v_gp2[1], "GoPlus mintable blocks a coin; a clean one carries the GoPlus and community facts (%s)" % v_gp2[1][-120:])
    bq, lc = side("bq"), side("lc")
    tbf = glob.glob(os.path.join(d, "tb", "*.txt"))
    check(bq and len(bq) >= 20 and all(len(l.split("|")) == 9 for l in bq) and any(fv(l, 1) and fv(l, 1) >= 12 for l in bq) and "bitquery trades" in err, "Bitquery on-chain trades written for the shortlist (%d coins, e.g. %s)" % (len(bq), bq[0][:70] if bq else "-"))
    check(len(tbf) >= 20 and any("dex:pumpswap" in open(f, encoding="utf-8").read() for f in tbf), "trader wallets from the chain fill the top-buyer files (%d files)" % len(tbf))
    check(lc and len(lc) >= 1 and fv(lc[0], 1) == 123456 and "lunarcrush topics" in err, "LunarCrush topic rows written for the best coins (%s)" % (lc[0][:60] if lc else "-"))
    mk = json.load(open(os.path.join(d, "market.json")))
    check(mk.get("sol24") == -2.5 and mk.get("fng") == 66, "market context saved (SOL %s%%, fear & greed %s)" % (mk.get("sol24"), mk.get("fng")))
    jd = tempfile.mkdtemp(prefix="memebot-jup-")
    r = subprocess.run([PY, os.path.join(HERE, "fetch.py"), "tokens", "--dir", jd, "--mock", url, "--pause", "0", "--addrs", "JUPXFALLBACK" + "2" * 32 + "," + mock.coins[3]["a"]], capture_output=True, text=True)
    jrows = side_j = [l for f in glob.glob(os.path.join(jd, "pairs", "jupx_*.txt")) for l in open(f, encoding="utf-8").read().splitlines() if l.strip() and not l.startswith("#")]
    check(r.returncode == 0 and len(jrows) == 1 and jrows[0].startswith("JUPXFALLBACK") and "jupiter prices: 1 of 1" in r.stderr, "a coin DexScreener does not return is priced through Jupiter (%s)" % (jrows[0][:60] if jrows else r.stderr[-100:]))
    shutil.rmtree(jd, ignore_errors=True)
    import memebot as MB
    v_sold = MB.risk_view({"lpLocked": 100, "top1Pct": 3, "top10Pct": 20, "insiders": 1, "holders": 2000, "creatorPct": 1, "dev": {"devPct": 1.0, "devSold": True, "devSellAgeMin": 25, "mintAuthOff": True, "txs3h": 3}})
    v_ok = MB.risk_view({"lpLocked": 100, "top1Pct": 3, "top10Pct": 20, "insiders": 1, "holders": 2000, "creatorPct": 1, "dev": {"devPct": 1.0, "devSold": False, "mintAuthOff": True, "freezeAuthOff": True, "txs3h": 0}})
    check(v_sold[0] is False and "sold 25 minutes ago" in v_sold[1] and v_ok[0] is True and "no creator sale" in v_ok[1], "a creator sale blocks a coin, a quiet creator is noted (%s)" % v_sold[1])
    pos = docs("memepos")
    picks = [dict(p, _id=pid) for pid, p in pos.items() if p["grp"] == "pick"]
    check(len(picks) == 2, "%d positions opened, all bot picks (%d)" % (len(pos), len(picks)))
    check(all(p["ticket"] == 20 for p in picks), "each ticket is 20")
    check(all(p["risk"] and not p["risk"]["danger"] and p["risk"]["lpLocked"] >= 50 for p in picks), "both picks have a clean RugCheck report with >= 50% LP locked")
    check(all(mock.by_a[p["addr"]]["dex"] != "pumpfun" and mock.by_a[p["addr"]]["liq"] >= 20000 for p in picks), "both picks pass the hard gates")
    c = cash()
    check(c["free"] == 0 and c["slots"] == 0, "bankroll fully deployed: free %.2f, slots %d" % (c["free"], c["slots"]))
    snaps = docs("memesnap")
    check(sum(s["n"] for s in snaps.values()) >= 1000, "big-test snapshot saved %d coins" % sum(s["n"] for s in snaps.values()))

    print("== cycle 2 (+1h, --force): money is deployed, so no third buy even when forced; coin A doubles -> half sold")
    a_pick, b_pick = picks[0], picks[1]
    urllib.request.urlopen(url + "/__mult?a=%s&m=2.2" % a_pick["addr"]).read()
    out, err = cycle(T0 + 1 * H, force=True)
    check("budget is deployed" in err, "mode says the budget is deployed")
    check(len(docs("memepos")) == 2, "still 2 positions")
    ex = docs("memeexit")
    check(len(ex) == 1 and all(e["pos"] == a_pick["_id"] and e["why"] == "target" and abs(e["frac"] - 0.5) < 1e-6 for e in ex.values()), "one exit: half of coin A at the 2x target")
    c = cash()
    check(19 < c["free"] < 22 and c["slots"] == 1, "half the ticket came back: free %.2f -> 1 slot" % c["free"])

    print("== cycle 3 (+4h): one free slot -> one more buy; coin B crashes -> stop")
    urllib.request.urlopen(url + "/__mult?a=%s&m=0.4" % b_pick["addr"]).read()
    out, err = cycle(T0 + 4 * H)
    pos = docs("memepos")
    check(len(pos) == 3, "a third position was opened with the returned money (%d positions)" % len(pos))
    ex = docs("memeexit")
    check(any(e["why"] == "stop" for e in ex.values()), "coin B hit the -50% stop")
    c = cash()
    check(c["free"] < 20, "bankroll after the third buy: free %.2f" % c["free"])

    print("== rescan (+5h): a forced full scan is saved although the last snapshot is recent, and nothing is bought")
    n_snap = len(docs("memesnap"))
    out, err = cycle(T0 + 5 * H, rescan=True)
    check(len(docs("memesnap")) > n_snap and '"scan": "full"' in err, "rescan saved a new snapshot")
    check(len(docs("memepos")) == 3, "rescan did not buy (no free slot)")

    print("== sell by hand (+6h): closes the open positions at the last price, money comes back, next forced cycle buys again")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sell", "--dir", d, "--all", "--now", str(T0 + 6 * H)], capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout.count("SOLD") == 2, "sell --all closed 2 positions: %s" % r.stdout.strip().replace("\n", " | ")[:120])
    c = cash()
    check(c["open"] == 0 and c["slots"] >= 1, "bankroll after the manual sale: free %.2f, %d slots" % (c["free"], c["slots"]))
    out, err = cycle(T0 + 6 * H + 60000, force=True)
    check(len([p for p in docs("memepos").values()]) >= 4, "a forced cycle after the sale bought again (%d positions)" % len(docs("memepos")))

    print("== cycle 4 (+25h): big test scores yesterday's snapshot and learns weights")
    out, err = cycle(T0 + 25 * H)
    res = docs("memesnapres")
    check(sum(r["n"] for r in res.values()) >= 1000, "scored %d snapshot coins 24h later" % sum(r["n"] for r in res.values()))
    check(len(docs("memeweights")) == 1, "weights doc written")
    check("Big test" in out, "note reports the big test")

    print("== cycle 5 (+4 days): the 3-day limit closes what is left, money returns")
    out, err = cycle(T0 + 96 * H)
    pos = docs("memepos"); ex = docs("memeexit")
    open_left = [p for p in pos.values()]
    sys.path.insert(0, HERE); import memebot as M
    P = M.positions(d)
    check(all(p["_left"] <= 1e-9 for p in P.values() if p["t"] <= T0 + 6 * H), "every old position is closed (%s)" % sorted(e["why"] for e in ex.values()))
    c = cash()
    check(c["free"] + c["deployed"] > 20 and c["open"] <= 2, "bankroll recovered: free %.2f, %d open" % (c["free"], c["open"]))
    tot = sum(1 for p in P.values() if p["grp"] == "pick")
    check(all(p["grp"] == "pick" for p in P.values()), "no control-group positions were opened (%d bot picks)" % tot)

    st = subprocess.run([PY, os.path.join(HERE, "bot.py"), "status", "--dir", d], capture_output=True, text=True)
    print(st.stdout.rstrip())
    check(st.returncode == 0 and "bankroll" in st.stdout, "status prints")

    print("== report page")
    page = open(os.path.join(d, "report.html")).read()
    check(len(page) > 20000 and "<title>" in page, "report.html written by the cycle (%d bytes)" % len(page))
    check(all(p["sym"] in page for p in picks) and "Closed trades" in page and "Big test" in page, "page names the bought coins and the results")
    check(("%.2f" % c["free"]) in page, "page shows the bankroll (%.2f)" % c["free"])
    check("<svg" in page and "data-pts" in page and "Factor weights" in page, "equity curve, tooltips and weights rendered")
    check("Table view and glossary" in page and "price unchanged" in page and "sold at" in page and "sells" in page, "glossary, big-test baseline, sale multiples and sell levels on the page")
    check(open(os.path.join(d, "report.html"), "rb").read().decode("utf-8") == page, "report.html is UTF-8")
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", d, "--out", os.path.join(d, "r2.html")], capture_output=True, text=True, env=dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0"))
    check(r.returncode == 0, "report renders under an ASCII locale")
    bad = tempfile.mkdtemp(prefix="memebot-bad-")
    shutil.copytree(os.path.join(d, "db"), os.path.join(bad, "db"))
    import glob as G
    f0 = sorted(G.glob(os.path.join(bad, "db", "memesnapres", "*.json")))[0]
    doc = json.load(open(f0)); doc["coins"].append(None); doc["coins"][0]["rank"] = "7"; json.dump(doc, open(f0, "w"))
    f1 = sorted(G.glob(os.path.join(bad, "db", "memeexit", "*.json")))[0]
    doc = json.load(open(f1)); doc["why"] = None; json.dump(doc, open(f1, "w"))
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", bad], capture_output=True, text=True)
    check(r.returncode == 0 and "could not be rendered" not in open(os.path.join(bad, "report.html")).read(), "malformed docs (null coin, string rank, null exit reason) do not break the page")
    shutil.rmtree(bad, ignore_errors=True)
    empty = tempfile.mkdtemp(prefix="memebot-empty-")
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", empty], capture_output=True, text=True)
    check(r.returncode == 0 and "No open positions" in open(os.path.join(empty, "report.html")).read(), "page renders for an empty db")
    shutil.rmtree(empty, ignore_errors=True)
    print("== recommend mode: a fresh db, full scan, two recommendations, no positions")
    rd = tempfile.mkdtemp(prefix="memebot-rec-")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--mock", url, "--now", str(T0), "--recommend"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json"))) if os.path.exists(os.path.join(rd, "db", "memebot", "recommend.json")) else {}
    check(r.returncode == 0 and len(rec.get("picks", [])) == 2 and r.stdout.count("RECOMMEND") == 2, "recommend cycle wrote 2 recommendations (%s)" % [p["sym"] for p in rec.get("picks", [])])
    fresh_files = glob.glob(os.path.join(rd, "pairs", "fresh_*.txt"))
    check(fresh_files and M.num(rec.get("pricedAt")) and rec.get("refreshed", 0) >= 16 and "refreshed" in (r.stderr or "") and "right before the pick" in open(os.path.join(rd, "report.html"), encoding="utf-8").read(),
          "the candidates' prices were refreshed before the pick (%d files, %s coins) and the page says when" % (len(fresh_files), rec.get("refreshed")))
    md_ = tempfile.mkdtemp(prefix="memebot-merge-")
    os.makedirs(os.path.join(md_, "pairs"))
    a_m = mock.coins[5]["a"]
    open(os.path.join(md_, "pairs", "tokens_000.txt"), "w").write("%s|AAA|Aaa|raydium|%spair|0.001|500000|550000|40000|100000|30000|5000|0|1|2|3|100|80|30|20|10|5|%d|0||1|1\n" % (a_m, a_m[:20], T0 - 5 * H))
    open(os.path.join(md_, "pairs", "fresh_000.txt"), "w").write("%s|AAA|Aaa|raydium|%spair|0.002|900000|950000|20000|120000|40000|9000|0|1|2|3|100|80|30|20|10|5|%d|0||1|1\n" % (a_m, a_m[:20], T0 - 5 * H))
    merged, mtags, _ = M.merge_pairs(md_)
    check(merged.get(a_m, {}).get("priceUsd") == 0.002 and merged[a_m].get("fresh") and merged[a_m].get("nPairs") == 1 and not mtags.get(a_m), "a fresh row overrides the scan's row without counting as another pair or source")
    shutil.rmtree(md_, ignore_errors=True)
    check(not os.path.isdir(os.path.join(rd, "db", "memepos")), "recommend mode opened no position")
    page = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    check("Two recommendations" in page and "dexscreener.com/solana/" in page and 'class="embed"' in page, "page shows the recommendations with embedded charts")
    old_rec = rec
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--now", str(T0 + 120000), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec2 = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json")))
    same = lambda a, b: [c["addr"] for c in a.get("picks", [])] == [c["addr"] for c in b.get("picks", [])]
    check(r.returncode == 0 and same(rec2, old_rec), "an offline rerun with the same files keeps the recommendations (%s -> %s; %s)" % ([c["sym"] for c in old_rec.get("picks", [])], [c["sym"] for c in rec2.get("picks", [])], (r.stderr.strip().splitlines() or ["?"])[-1][:100]))

    print("== training: walk-forward test, zero model and tuned limits on synthetic snapshot results")
    td = tempfile.mkdtemp(prefix="memebot-train-")
    sys.path.insert(0, HERE)
    import memebot as M
    rng = random.Random(3)
    os.makedirs(os.path.join(td, "db", "memesnapres"))
    syn = {}
    for g in range(24):   # 24 scans x 120 coins: a coin whose logMc sits in one zone mostly goes to zero (non-monotone: rank correlation cannot see it, bins can)
        coins = []
        for i in range(120):
            lmc, bs = rng.uniform(5.0, 6.5), rng.random()
            gone = rng.random() < (0.8 if 5.78 < lmc < 6.1 else 0.02)   # the zone sits inside the third of four equal-count bins
            mult = 0.0 if gone else max(0.05, rng.gauss(0.9 + 0.5 * bs, 0.3))
            coins.append({"a": "A%02d-%03d" % (g, i), "s": "S%d" % i, "pass": i % 3 == 0, "sc": 50.0, "why": [] if i % 3 == 0 else ["young"], "mc": 300_000, "liq": 40_000,
                          "f": {"logMc": round(lmc, 4), "buyShare": round(bs, 4), "c1": round(rng.uniform(-30, 80), 2), "ageH": round(rng.uniform(2, 40), 2)},
                          "mult": round(mult, 4), "eur": round(19.9 * mult * 0.995 - 20, 2) if mult else -20.0, "gone": gone})
        syn["syn%02d-1" % g] = {"t": T0 + (g + 1) * 24 * H, "t0": T0 + g * 24 * H, "rule": M.RULE, "n": len(coins), "coins": coins}
        json.dump(syn["syn%02d-1" % g], open(os.path.join(td, "db", "memesnapres", "syn%02d-1.json" % g), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "memebot.py"), "train", "--dir", td, "--now", str(T0 + 25 * 24 * H)], capture_output=True, text=True)
    tr = json.load(open(os.path.join(td, "db", "memebot", "train.json"))) if os.path.exists(os.path.join(td, "db", "memebot", "train.json")) else {}
    wf, zm, tuned = tr.get("walkForward") or {}, tr.get("zeroModel") or {}, tr.get("tuned") or {}
    check(r.returncode == 0 and tr.get("rows") == 2880 and tr.get("tested", 0) >= 10 and wf.get("top2", {}).get("n", 0) >= 30 and wf.get("allPass"),
          "train: %s rows, walk-forward over %s scans, %s top-2 tips (%s)" % (tr.get("rows"), tr.get("tested"), wf.get("top2", {}).get("n"), (r.stderr.strip().splitlines() or [""])[-1][:100]))
    check("logMc" in (zm.get("factors") or {}) and len(zm.get("cal") or []) >= 2, "zero model found the factor behind the zeros (%s)" % sorted((zm.get("factors") or {}).keys()))
    bad, good = M.zero_p(zm, {"logMc": 5.95, "buyShare": 0.5, "c1": 10, "ageH": 5}), M.zero_p(zm, {"logMc": 6.3, "buyShare": 0.5, "c1": 10, "ageH": 5})
    check(bad is not None and good is not None and bad > 0.4 and good < 0.1, "calibrated zero chance: %s for a coin in the zone, %s outside it" % (bad, good))
    z = wf.get("top2zero") or {}
    check(z.get("n", 0) >= 30 and z.get("zero") is not None and z["zero"] < wf["top2"]["zero"] and z.get("coverage", 0) >= 70,
          "with the zero limit the top-2 zero rate fell from %s%% to %s%% at %s%% coverage" % (wf.get("top2", {}).get("zero"), z.get("zero"), z.get("coverage")))
    check(M.ZERO_P_FLOOR <= M.num(tuned.get("MAX_ZERO_P")) <= 0.6 and M.MIN_REC_SCORE - 10 <= M.num(tuned.get("MIN_REC_SCORE")) <= M.MIN_REC_SCORE + 20 and tr.get("tunedWhy"),
          "tuned limits stay in bounds: zero limit %s, score bar %s" % (tuned.get("MAX_ZERO_P"), tuned.get("MIN_REC_SCORE")))
    check(any(x.get("gate") == "pass" for x in tr.get("gates") or []) and any(x.get("gate") == "young" for x in tr.get("gates") or []) and tr.get("factors"),
          "gate audit and factor splits written (%d gates, %d factors)" % (len(tr.get("gates") or []), len(tr.get("factors") or [])))
    ages_ = tr.get("ages") or []
    check(len(ages_) >= 3 and all(a.get("n") >= 10 and a.get("avg") is not None for a in ages_) and sum(a["n"] for a in ages_) == tr.get("rows") and any(a.get("passed") for a in ages_),
          "age record written: %s" % ", ".join("%s %d" % (a.get("age"), a.get("n")) for a in ages_))
    shutil.rmtree(td, ignore_errors=True)
    # the same results in the recommend db: the next cycle trains on them and the run applies the zero model to its picks
    os.makedirs(os.path.join(rd, "db", "memesnapres"), exist_ok=True)
    for k, doc in syn.items():
        json.dump(doc, open(os.path.join(rd, "db", "memesnapres", k + ".json"), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--now", str(T0 + 2 * H), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec4 = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json")))
    st4 = json.load(open(os.path.join(rd, "db", "memebot", "state.json")))
    zps = [c.get("zeroP") for c in rec4.get("picks", [])]
    check(r.returncode == 0 and "training:" in r.stderr and rec4.get("zeroLimit") is not None and rec4.get("trained") == 2880 and zps and all(isinstance(v, float) for v in zps)
          and "Zero model" in (st4.get("note") or ""), "the cycle trained and the run applied the zero model (limit %s, picks' zero chance %s)" % (rec4.get("zeroLimit"), zps))
    page4 = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    check("Walk-forward test" in page4 and "Zero model" in page4 and "Chance of going to zero" in page4 and "Chance of a profit" in page4 and "Why the bot picked it" in page4, "page shows the training section and the odds on the card")
    ups = [c.get("upP") for c in rec4.get("picks", [])]
    check(ups and all(isinstance(v, float) for v in ups) and "chance of a profit" in (rec4["picks"][0].get("safety") or ""), "picks carry the trained profit chance (%s)" % ups)
    # nothing clean at all: a training doc that puts every coin over the zero limit -> the risky tier names the best odds, with its flag
    tr4 = json.load(open(os.path.join(rd, "db", "memebot", "train.json")))
    tr4["zeroModel"] = {"base": 0.5, "n": 1000, "zeros": 500, "factors": {"logMc": {"edges": [1.0], "lo": [0.0, 0.0], "n": 1000}}, "cal": [{"hi": 1e9, "p": 0.9, "n": 1000}]}
    tr4["tuned"] = {"MAX_ZERO_P": 0.05, "MIN_REC_SCORE": 45}
    json.dump(tr4, open(os.path.join(rd, "db", "memebot", "train.json"), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "memebot.py"), "run", "--dir", rd, "--mode", "pick", "--recommend", "--now", str(T0 + 2 * H + 60000)], capture_output=True, text=True)
    rec5 = json.load(open(os.path.join(rd, "out", "memebot__recommend.json"))) if os.path.exists(os.path.join(rd, "out", "memebot__recommend.json")) else {}
    p5 = (rec5.get("picks") or [{}])[0]
    check(r.returncode == 0 and not rec5.get("picks") and "trained odds of a loss" in (rec5.get("reason") or ""), "with every coin over the zero limit no coin is named, not even a risky one (%s)" % (rec5.get("reason") or "")[:80])
    rk_ok = {"lpLocked": 80, "top1Pct": 5, "top10Pct": 30, "insiders": 3, "holders": 900, "warn": "High holder correlation"}
    rk_bad = {"lpLocked": 80, "top1Pct": 5, "top10Pct": 30, "insiders": 3, "holders": 120}
    mk = lambda a, age, mc, fails, up, zp: {"a": a, "pr": {"symbol": a}, "f": {}, "basic": {"price": 1.0, "liq": 50000.0, "mc": mc, "age_h": age}, "fails": fails, "sc": 50.0, "ok": not fails}
    rows_r = [mk("YOUNG", 0.4, 300000, ["young"], 0, 0), mk("OLDOK", 6.0, 300000, ["nobuyers"], 0, 0), mk("NOREP", 7.0, 300000, ["nobuyers"], 0, 0), mk("BIG", 8.0, 50_000_000, ["mc"], 0, 0)]
    pool = M.risky_rows(rows_r, set(), set(), None, None, {"OLDOK": rk_ok, "BIG": rk_ok})
    check([r["a"] for r in pool][:2] == ["OLDOK", "NOREP"] and all(r["a"] != "YOUNG" for r in pool) and M.loose_view(rk_ok)[0] is True and M.loose_view(rk_bad)[0] is False and M.loose_view(None)[0] is None,
          "risky pool: never under the minimum age, reported coins first, the relaxed floor judges reports (%s)" % [r["a"] for r in pool])
    json.dump(tr4 | {"zeroModel": None, "tuned": {"MAX_ZERO_P": 0.35, "MIN_REC_SCORE": 45}}, open(os.path.join(rd, "db", "memebot", "train.json"), "w"))
    rs = subprocess.run([PY, os.path.join(HERE, "bot.py"), "summary", "--dir", rd], capture_output=True, text=True, encoding="utf-8")
    check(rs.returncode == 0 and "Training: Walk-forward" in rs.stdout, "summary carries the training line")
    old_rec = rec4
    import fetch as F2
    F2.clear_sources(rd)                                   # nothing fetched at all -> the scan is tiny -> the old recommendations stay
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--now", str(T0 + 2 * H), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec3 = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json")))
    check(r.returncode == 0 and same(rec3, old_rec) and "SKIPPED" in r.stdout, "a broken (tiny) scan does not replace the recommendations (%s)" % ((r.stderr.strip().splitlines() or ["?"])[-1][:120] if r.returncode else r.stdout.strip().splitlines()[-1][:120]))
    shutil.rmtree(rd, ignore_errors=True)

    print("== 2h profile: early, accelerating coins; recommendations and a 2-hour big test")
    hd = tempfile.mkdtemp(prefix="memebot-2h-")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", hd, "--mock", url, "--now", str(T0), "--recommend", "--horizon", "2h"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec = json.load(open(os.path.join(hd, "db", "memebot", "recommend.json"))) if os.path.exists(os.path.join(hd, "db", "memebot", "recommend.json")) else {}
    ages = [c.get("f", {}).get("ageH") for c in rec.get("picks", [])]
    check(r.returncode == 0 and 1 <= len(rec.get("picks", [])) <= 2 and all(a is not None and 3 <= a <= 12 for a in ages), "2h profile recommended early coins, 3 to 12 hours old (ages %s)" % [round(a, 1) if a else a for a in ages])
    check(all(c.get("tier") in ("strong", "weak", "fallback") for c in rec.get("picks", [])), "each pick carries its tier (%s)" % [c.get("tier") for c in rec.get("picks", [])])
    st = json.load(open(os.path.join(hd, "db", "memebot", "state.json")))
    check(st.get("horizon") == "2h" and st.get("rule") == "m9-2h", "state carries the profile")
    page = open(os.path.join(hd, "report.html"), encoding="utf-8").read()
    check("for the next 2 hours" in page and "Big test: 2 hours later" in page, "page is labelled for the 2-hour horizon")
    young = rec.get("young") or []
    check(young and all(0 <= M.num(y.get("ageMin")) < 60 and y.get("addr") and "upP" in y and "floor" in y and y.get("liq", 0) >= M.YOUNG_MIN_LIQ for y in young)
          and all(y["addr"] not in {c["addr"] for c in rec.get("picks", [])} for y in young) and rec.get("youngOf", 0) >= len(young),
          "new launches under an hour old are listed with odds and safety, none of them picked (%d of %d: %s)" % (len(young), rec.get("youngOf", 0), [(y.get("sym"), y.get("ageMin")) for y in young[:4]]))
    check('id="tab-young"' in page and "New launches &lt;1h" in page and "min old</span>" in page and "The record by age" in page and "new launch · not a pick" in page,
          "page has the new-launches tab with the coins, their cards and the age record")
    rk_young = [y for y in young if isinstance(y.get("risk"), dict) and y["risk"]]
    check(rk_young, "the new launches got safety reports with the shortlist (%d of %d)" % (len(rk_young), len(young)))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", hd, "--mock", url, "--now", str(T0 + 3 * H), "--recommend", "--horizon", "2h"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    res = glob.glob(os.path.join(hd, "db", "memesnapres", "*.json"))
    check(r.returncode == 0 and res and "Big test" in r.stdout, "the snapshot was scored 2 hours later (%d result docs)" % len(res))
    recs = [json.load(open(f)) for f in glob.glob(os.path.join(hd, "db", "memerec", "*.json"))]
    scored = [o for doc in recs for o in (doc.get("out") or {}).get("picks", [])]
    page2 = open(os.path.join(hd, "report.html"), encoding="utf-8").read()
    check(recs and scored and "Track record" in r.stdout and "Track record of the tips" in page2, "the tips were recorded and priced again 2 hours later (%d docs, %d scored)" % (len(recs), len(scored)))
    check(not glob.glob(os.path.join(hd, "db", "memesnap", "*-1.json")) or all(os.path.basename(f)[:-5] not in {os.path.basename(x)[:-5] for x in res} for f in glob.glob(os.path.join(hd, "db", "memesnap", "*.json"))), "scored raw snapshots are removed")
    shutil.rmtree(hd, ignore_errors=True)

    print("== sync: page and small docs to a results branch")
    bare = tempfile.mkdtemp(prefix="memebot-bare-")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", d, "--remote", bare], capture_output=True, text=True)
    check(r.returncode == 0, "bot.py sync pushes (%s)" % (r.stderr.strip().splitlines() or ["?"])[-1][:100])
    ls = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", "results"], capture_output=True, text=True).stdout.split()
    check("report.html" in ls and any(x.startswith("db/memepos/") for x in ls) and any(x.startswith("db/memebot/") for x in ls), "results branch holds report.html and the small docs (%d files)" % len(ls))
    check(not any(x.startswith(("db/memesnap/", "db/memesnapres/")) for x in ls), "the big snapshots stay local")
    r2 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", d, "--remote", bare], capture_output=True, text=True)
    check(r2.returncode == 0 and "nothing new" in r2.stderr, "a second sync with no changes is a no-op push")
    r3 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(T0 + 100 * H), "--push", "--remote", bare], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    check(r3.returncode == 0 and "sync: new commit" in r3.stderr, "cycle --push syncs after the cycle")
    shutil.rmtree(bare, ignore_errors=True)

    print("== site: a folder for GitHub Pages")
    sd = tempfile.mkdtemp(prefix="memebot-site-")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", d, "--out", sd, "--repo", "https://x-access-token:secret@github.com/x/y.git"], capture_output=True, text=True)
    idx = open(os.path.join(sd, "index.html"), encoding="utf-8").read() if os.path.exists(os.path.join(sd, "index.html")) else ""
    check(r.returncode == 0 and 'rel="manifest"' in idx and 'href="https://github.com/x/y/actions/workflows/scan.yml"' in idx and "secret" not in idx
          and "<h1>Meme-Bot Ledger</h1>" in idx and "visibilitychange" in idx, "site/index.html is the page with app tags, auto-refresh and a clean scan link")
    try:
        man = json.load(open(os.path.join(sd, "manifest.webmanifest"), encoding="utf-8"))
        pngs = [open(os.path.join(sd, "icon-%d.png" % n), "rb").read(24) for n in (180, 192, 512)]
    except (OSError, ValueError):
        man, pngs = {}, []
    check(man.get("display") == "standalone" and len(pngs) == 3 and all(b[:8] == b"\x89PNG\r\n\x1a\n" for b in pngs)
          and os.path.exists(os.path.join(sd, ".nojekyll")), "manifest, three PNG icons and .nojekyll are written")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "summary", "--dir", d], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0 and r.stdout.startswith("## Meme-Bot ") and ("](https://dexscreener.com/solana/" in r.stdout or "### Open positions" in r.stdout),
          "bot.py summary prints Markdown (%s)" % (r.stdout.strip().splitlines() or ["?"])[1][:60])
    shutil.rmtree(sd, ignore_errors=True)
    shutil.rmtree(os.path.join(d, ".git"), ignore_errors=True)

    keep = os.environ.get("MEMEBOT_KEEP")
    if keep:
        shutil.rmtree(keep, ignore_errors=True); shutil.copytree(os.path.join(d, "db"), os.path.join(keep, "db")); print("kept db in " + keep)

    shutil.rmtree(d, ignore_errors=True)
    srv.shutdown()
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    import urllib.request
    main()
