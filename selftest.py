#!/usr/bin/env python3
"""selftest.py: runs the whole bot against a local mock of every API (~1100 synthetic coins) with a fake clock.

  python3 selftest.py            -> prints each cycle's note and PASS/FAIL per check, exit code 1 on any failure

What it proves: the fetch layer parses every source's response shape into the pipe-row files, gather merges them into a 1000+ coin
universe, the scan gates and scores them, exactly two coins get bought for 20 each out of the 40 bankroll, no third buy happens
while the money is deployed, exits (half at 2x, stop at -50%, 3-day time limit) return money to the bankroll, the 24h big test
scores every snapshotted coin and the weights get learned. GMGN is mocked as blocked (403) to exercise the circuit breaker.
In recommend mode the paper account buys the top pick for 50 and the first five new launches for 3 in one cycle, sells them at
+1000% (11x), -30%, after 6 hours or as a rug (never for a failed filter), and its restart closes the old rule's positions once.
The iPhone app (app_tests): the live store against a local stand-in for Supabase's REST API, push notifications against a local push
service (the real pywebpush when it is installed, else a stand-in with the same call), bot.py's live feed and hooks, the site step's key
guard, the page's decisions and sw.js in node, and supabase/setup.sql on PostgreSQL when MEMEBOT_PG=<host or socket folder>:<port> is set.
"""
import contextlib, glob, html, io, json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

SKIPS = []                   # check groups that could not run here (no Playwright, no node, no PostgreSQL): the last line names how many
REAL_SLEEP = time.sleep      # the fetch tests make time.sleep a no-op for the whole process; the slow stand-ins below need a real one

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
                      "holders": [ "".join(rng.choice(ALPH) for _ in range(44)) for _ in range(5)], "mult": 1.0, "gone": False,
                      "tid": (i + 1) if i % 4 == 0 else 0})     # every fourth coin's X link is one tweet (the story launch)
    return coins


class Mock:
    def __init__(self):
        self.coins = mk_universe()
        self.by_a = {c["a"]: c for c in self.coins}
        self.now = T0
        self.hits = {}
        self.log, self.search_n, self.ds429, self.on_rc = [], 30, False, None    # the launch spotter's checks: every path asked, fewer search hits, 429s, a RugCheck hook
        self.wall = None          # a fixed wall clock (s) for the one answer stamped with the time of the request (Bitquery), so runs can be compared
        self.hook = None          # the launch spotter's checks: hook(path) -> (code, body) answers a request instead of the mock (None: the mock answers)

    def pair(self, c):
        px = 0.0 if c["gone"] else c["px"] * c["mult"]
        liq = 0.0 if c["gone"] else c["liq"]
        socials = [{"type": "twitter", "url": ("https://x.com/%s/status/18%018d" % (c["sym"].lower(), c["tid"])) if c.get("tid") else "https://x.com/" + c["sym"].lower()}] if c["x"] else []
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
            stamp = lambda i: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((self.wall or time.time()) - 300 * i))
            trades = [{"Block": {"Time": stamp(i)}, "Trade": {"Side": {"Type": "buy" if i % 3 else "sell"}, "Amount": "1000", "AmountInUSD": str(50 + 10 * i), "PriceInUSD": "0.05",
                                                          "Account": {"Owner": "W%s%s" % (mint[:30], chr(65 + i) * 2)}, "Dex": {"ProtocolName": "pump_amm", "ProtocolFamily": "Pumpswap"}}, "Transaction": {"Signer": "S%s" % mint[:40]}}
                      for i in range(24)]
            return 200, {"data": {"Solana": {"DEXTradeByTokens": trades}}}
        if path.startswith("/api.mainnet-beta.solana.com"):
            if method == "getSignaturesForAddress" and str(params[0]).endswith("pair"):      # a pool: 30 swaps in the last 45 minutes
                pool = str(params[0]); idx = next((i for i, c in enumerate(self.coins) if c["a"][:20] + "pair" == pool), None)
                if idx is None:
                    return 200, {"jsonrpc": "2.0", "result": [], "id": 1}
                return 200, {"jsonrpc": "2.0", "result": [{"signature": "flw%d_%d" % (idx, i), "blockTime": int(self.now / 1000) - 90 * i, "err": None} for i in range(30)], "id": 1}
            if method == "getTransaction" and str(params[0]).startswith("flw"):
                # a swap against the pool's vaults (owner POOL): two of three buy 100 coins for 0.5 SOL, one sells 100 for 0.4 SOL; swap 27 is a
                # liquidity deposit (the trader's coins and SOL both go into the pool), which is not a trade
                idx, i = (int(x) for x in str(params[0])[3:].split("_"))
                c = self.coins[idx]; payer = c["a"][:36] + "Wxab" + "cdefghj"[i % 7]; pool_owner = c["a"][:30] + "PooLvauLtz"; wsol = "So11111111111111111111111111111111111111112"
                buy, lp = i % 3 != 0, i == 27
                v_coin = -100.0 if buy else 100.0; v_sol = 0.5 if buy else (0.5 if lp else -0.4)
                tb = lambda owner, mint, amt: {"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": amt}}
                return 200, {"jsonrpc": "2.0", "result": {"meta": {"err": None, "preBalances": [10_000_000_000], "postBalances": [9_500_000_000 if buy or lp else 10_400_000_000],
                                                                   "preTokenBalances": [tb(payer, c["a"], 1000.0), tb(pool_owner, c["a"], 1_000_000.0), tb(pool_owner, wsol, 500.0)],
                                                                   "postTokenBalances": [tb(payer, c["a"], 1000.0 - v_coin), tb(pool_owner, c["a"], 1_000_000.0 + v_coin), tb(pool_owner, wsol, 500.0 + v_sol)]},
                                                          "transaction": {"message": {"accountKeys": [{"pubkey": payer, "signer": True, "writable": True}]}}}, "id": 1}
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
        self.log.append(path)
        if self.hook:
            got = self.hook(path)
            if got is not None:
                return got
        q = urllib.parse.parse_qs(query)
        if "/__429" in path:
            self.n429 = getattr(self, "n429", 0) + 1
            return (429, {"err": "slow down"}) if self.n429 <= 2 else (200, {"ok": True})
        if path.startswith("/__dsdead"):
            self.ds_dead = q.get("on", ["1"])[0] == "1"
            return 200, {"ok": True}
        if getattr(self, "ds_dead", False) and path.startswith("/api.dexscreener.com/") and ("/latest/dex/search" in path or "/tokens/v1/" in path or "/token-boosts/" in path):
            return 200, ({"pairs": []} if "/latest/dex/search" in path else [])
        if path.startswith("/__spike"):          # the middle candle of a coin's pool closes this many times the price (0: back to +35%)
            self.by_a[q["a"][0]]["spike"] = float(q["x"][0]) or None
            return 200, {"ok": True}
        if path.startswith("/__nocandle"):       # a coin's pool sends no minute candles (on=1) or does again (on=0)
            self.by_a[q["a"][0]]["nocandle"] = q.get("on", ["1"])[0] == "1"
            return 200, {"ok": True}
        if path.startswith("/__chg"):            # a coin's 1-hour price change as DexScreener reports it
            self.by_a[q["a"][0]]["chg"][1] = float(q["h1"][0])
            return 200, {"ok": True}
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
            if p.startswith("/orders/v1/solana/"):
                a = p.rsplit("/", 1)[1]
                i = self.coins.index(self.by_a[a]) if a in self.by_a else 1
                return 200, ([{"type": "tokenProfile", "status": "approved", "paymentTimestamp": T0 - 5 * H}] + ([{"type": "tokenAd", "status": "approved", "paymentTimestamp": T0 - H}] if i % 6 == 0 else [])) if i % 3 == 0 else []
            if p == "/latest/dex/search":
                kw = q.get("q", [""])[0]
                hits = [c for c in self.coins if c["kw"] == kw][:self.search_n]
                if not hits:
                    rng = random.Random(kw); hits = rng.sample(self.coins, self.search_n)
                return 200, {"pairs": [self.pair(c) for c in hits]}
            if p.startswith("/tokens/v1/solana/"):
                if self.ds429:
                    return 429, {"error": "rate limited"}
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
        if "/api.geckoterminal.com/api/v2/networks/solana/pools/" in path and "/ohlcv/" in path:
            pool = path.split("/pools/")[1].split("/")[0]
            c = next((x for x in self.coins if x["a"][:20] + "pair" == pool), None)
            if c and c.get("nocandle"):
                return 200, {"data": {"attributes": {"ohlcv_list": []}}}
            before = int((q.get("before_timestamp") or [str(int(T0 / 1000) + 4500)])[0]); agg = int((q.get("aggregate") or ["1"])[0]); lim = int((q.get("limit") or ["70"])[0])
            px = (c["px"] * c["mult"]) if c else 0.001
            lst = []
            for i in range(lim):
                ts = before - i * 60 * agg
                hi = px * (3.0 if i == lim // 2 else 1.02)
                close = px * (((c or {}).get("spike") or 1.35) if i == lim // 2 else 1.0)    # one candle in the middle closes at +35%: a close-based take-profit sells there up to +30%, not +50%
                lst.append([ts, px, hi, px * 0.9, close, 1000.0])
            return 200, {"data": {"attributes": {"ohlcv_list": lst}}}
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
        if path.startswith("/cdn.syndication.twimg.com/tweet-result"):
            q = urllib.parse.parse_qs(query)
            tid = int((q.get("id") or ["0"])[0][-6:])
            if "token" not in q or tid % 7 == 0:
                return 404, {"error": "not found"}
            return 200, {"__typename": "Tweet", "id_str": (q.get("id") or ["0"])[0], "favorite_count": 1000 * tid, "conversation_count": 50 * tid,
                         "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(T0 / 1000 - 3600 * (tid % 30 + 1))),
                         "text": "A baby monkey hugging a plush toy went viral today" if tid % 2 else "the chart speaks for itself",
                         "user": {"screen_name": "storyteller%d" % tid, "followers_count": 12345, "is_blue_verified": tid % 3 == 0},
                         "mediaDetails": [{"type": "photo"}] if tid % 2 else []}
        if path.startswith("/syndication.twitter.com/srv/timeline-profile/screen-name/"):
            return 200, '<html><script id="__NEXT_DATA__">{"props":{"user":{"followers_count":45678},"entries":[%s]}}</script></html>' % ",".join(
                '{"created_at":"%s"}' % time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(T0 / 1000 - 86400 * i)) for i in range(5))
        if path.startswith("/t.me/s/"):
            return 200, '<html><div class="tgme_header_counter">12 345 members</div>%s</html>' % "".join('<div class="tgme_widget_message"><time datetime="%s"></time></div>' % time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(T0 / 1000 - 7200 * i)) for i in range(6))
        if "/rss/search" in path:
            items = "".join("<item><title>%s coin %s in the news</title><pubDate>%s</pubDate></item>" % (c["name"], c["sym"], time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(T0 / 1000 - 3600 * i))) for i, c in enumerate(self.coins[8:12]))
            return 200, '<?xml version="1.0"?><rss version="2.0"><channel><title>g</title>%s</channel></rss>' % items
        m = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/report$", path)
        if m and self.on_rc:
            self.on_rc(path)
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
                          "stats1h": {"priceChange": 1.0, "numBuys": 10, "numSells": 5, "numNetBuyers": 3, "buyVolume": 120, "sellVolume": 60}, "stats6h": {"priceChange": 2.0},
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


TRADER_COLLS = ("memeyoung", "memerec", "memesnap", "memesnapres", "memepos", "memeexit", "memecurve", "memeruns", "memeweights")
WALL_KEYS = ("pricedAt", "entryAt", "note", "paidAgeH", "tweetAgeH", "vt.ageH")   # fields the scan derives from the wall clock, not the fake one


def trader_files(d):
    """Every file the trader writes or reads back: the docs of check 1 of the spotter's build spec."""
    out = {}
    for coll in TRADER_COLLS:
        for f in glob.glob(os.path.join(d, "db", coll, "*.json")):
            out[os.path.relpath(f, d)] = f
    for f in [os.path.join(d, "db", "memebot", n + ".json") for n in ("recommend", "state", "marks", "train")] + [os.path.join(d, "pairs.json"), os.path.join(d, "universe.json")]:
        if os.path.exists(f):
            out[os.path.relpath(f, d)] = f
    return out


def leaf_diff(a, b):
    """The key names under which two JSON values differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = set()
        for k in set(a) | set(b):
            if a.get(k) != b.get(k):
                sub = leaf_diff(a.get(k), b.get(k))
                out |= {k} if sub == {"<value>"} else sub
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return set().union(*[leaf_diff(x, y) for x, y in zip(a, b)]) if a else set()
    return set() if a == b else {"<value>"}


def masked(v, keys):
    if isinstance(v, dict):
        return {k: masked(x, keys) for k, x in v.items() if k not in keys}
    if isinstance(v, list):
        return [masked(x, keys) for x in v]
    return v


@contextlib.contextmanager
def profile(name):
    """memebot's rules switched to a profile in this process, and back afterwards (apply_profile alone cannot go back to 24h)."""
    import memebot as M
    keys = set(M.PROFILES["2h"]) | {"HORIZON"}
    saved = {k: getattr(M, k) for k in keys if hasattr(M, k)}
    try:
        M.apply_profile(name)
        yield M
    finally:
        for k, v in saved.items():
            setattr(M, k, v)


WALL = T0 / 1000.0 + 300     # the frozen wall clock of the runs compared in check 1


def frozen_env(e, base):
    """The environment of a run whose wall clock (time.time) stands still at WALL: a sitecustomize module on PYTHONPATH (in base/frozen, the test's own
    temporary folder, removed with it) sets it in every Python process
    of the cycle. The mock's answers that depend on the time (creator sales, the on-chain sample, tweet ages, DEX-paid ages, Bitquery) and the features
    computed from them then come out the same in every run, so two runs differ only where their code does (the hash seed is fixed too: some
    weights tie, and their order in a note followed the set order of the process)."""
    d = os.path.join(base, "frozen")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "sitecustomize.py"), "w") as f:
        f.write("import os, time\n_t = float(os.environ.get('MEMEBOT_TEST_WALL') or 0)\nif _t:\n    time.time = lambda: _t\n    time.time_ns = lambda: int(_t * 1e9)\n")
    return dict(e, PYTHONPATH=d + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else ""), MEMEBOT_TEST_WALL=repr(WALL), PYTHONHASHSEED="0")   # and set orders


def spot_cycle(d, env=None, code=HERE, search_n=4, remote=None, frozen=False):
    """One recommend cycle (2h profile, fake clock T0) on a fresh mock whose keyword searches find only search_n coins each, so the price desk
    and the launch spotter both ask DexScreener for hundreds of addresses at the same time; frozen: the wall clock stands still (frozen_env).
    Returns (process, seconds, mock)."""
    mock = Mock()
    mock.search_n = search_n
    srv = serve(mock)
    e = dict(os.environ, MEMEBOT_PAUSE="0")
    e.update(env or {})
    if frozen:
        e = frozen_env(e, os.path.dirname(os.path.abspath(d)))
        mock.wall = WALL
    if remote:
        e.update(MEMEBOT_LIVE="1", RESULTS_URL=remote)
    t = time.time()
    p = subprocess.run([PY, os.path.join(code, "bot.py"), "cycle", "--dir", d, "--mock", "http://127.0.0.1:%d" % srv.server_address[1], "--now", str(T0), "--recommend", "--horizon", "2h"],
                       capture_output=True, text=True, encoding="utf-8", env=e)
    srv.shutdown()
    srv.server_close()
    return p, time.time() - t, mock


def git_live(remote):
    r = subprocess.run(["git", "-C", remote, "show", "live:live.json"], capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def b58(rng, suffix="pump"):
    return "".join(rng.choice(ALPH) for _ in range(44 - len(suffix))) + suffix


def spotter_checks(check):
    """The launch spotter (radar.py) and the early list on the New launches tab: checks 1 to 14 of its build spec."""
    import memebot as M
    import fetch as F
    import bot as B
    import report as R
    import radar as RD
    rid = lambda t: time.strftime("%Y-%m-%dT%H%M", time.gmtime(t / 1000))
    tmp = tempfile.mkdtemp(prefix="memebot-spot-")

    print("== launch spotter 1: the trader's docs are the same with the spotter on and off")
    remote_on, remote_off = os.path.join(tmp, "live-on.git"), os.path.join(tmp, "live-off.git")
    for r_ in (remote_on, remote_off):
        subprocess.run(["git", "init", "-q", "--bare", r_], check=True)
    da, dc, db_ = (os.path.join(tmp, x) for x in ("off-a", "on-c", "off-b"))
    pa, sa, _ = spot_cycle(da, {"MEMEBOT_EARLY": "0"}, frozen=True)
    pc, sc, _ = spot_cycle(dc, {"MEMEBOT_EARLY": "1"}, remote=remote_on, frozen=True)
    os.makedirs(db_, exist_ok=True)       # the second off run starts with a stale early list of an hour ago in its folder
    json.dump({"v": 1, "t": T0 - H, "state": "listed", "rcState": "done", "coins": [{"addr": "StaLe" + "1" * 39, "sym": "STALE"}]}, open(os.path.join(db_, "young_early.json"), "w"))
    pb, sb, _ = spot_cycle(db_, {"MEMEBOT_EARLY": "0"}, remote=remote_off, frozen=True)
    fa, fb, fc = trader_files(da), trader_files(db_), trader_files(dc)
    noise = set()
    for k in set(fa) & set(fb):
        noise |= leaf_diff(json.load(open(fa[k], encoding="utf-8")), json.load(open(fb[k], encoding="utf-8")))
    raw = lambda f: open(f, "rb").read()
    diffs = {k: sorted(leaf_diff(json.load(open(fa[k], encoding="utf-8")), json.load(open(fc[k], encoding="utf-8")))) or ["<bytes>"] for k in set(fa) & set(fc) if raw(fa[k]) != raw(fc[k])}
    print("  noise between two runs without the spotter: %s; cycles %.1f s off, %.1f s on" % (sorted(noise), sa, sc))
    check(pa.returncode == pb.returncode == pc.returncode == 0 and set(fa) == set(fb) == set(fc) and len(fa) > 15 and noise <= set(WALL_KEYS) and not diffs
          and os.path.isfile(os.path.join(tmp, "frozen", "sitecustomize.py")) and not os.path.exists(os.path.join(tempfile.gettempdir(), "memebot-frozen-%d" % os.getpid())),
          "the trader's %d docs (positions, tips, new launches, snapshots, weights, state, pairs.json, universe.json) are byte for byte the same with the"
          " spotter on and off, no field masked %s" % (len(fa), diffs or ""))
    off_c = json.load(open(os.path.join(dc, "db", "memebot", "office.json"), encoding="utf-8"))
    off_a = json.load(open(os.path.join(da, "db", "memebot", "office.json"), encoding="utf-8"))
    spot_a = {a["id"]: a for a in off_c["agents"]}.get("spotter") or {}
    check(spot_a.get("bg") is True and spot_a.get("status") == "done" and "new launch" in (spot_a.get("out") or "") and "spotter" not in {a["id"] for a in off_a["agents"]}
          and glob.glob(os.path.join(dc, "db", "memeearly", "*.json")) and not glob.glob(os.path.join(da, "db", "memeearly", "*.json")) and not os.path.exists(os.path.join(da, "young_early.json")),
          "only the office record (the spotter's desk: %s), spotter.json and db/memeearly differ" % spot_a.get("out"))

    print("== launch spotter 2: fetch.py's two new keyword arguments change nothing for the old callers")
    h_ = F.Http(None, pause=0)
    srv2 = serve(Mock())
    u2 = "http://127.0.0.1:%d" % srv2.server_address[1]
    mk = Mock()
    addrs2 = [c["a"] for c in mk.coins[:40]] + ["JUPXFALLBACK" + "1" * 32]
    dd = [os.path.join(tmp, "ds%d" % i) for i in range(3)]
    F.ds_tokens(F.Http(u2, pause=0), dd[0], addrs2)
    F.ds_tokens(F.Http(u2, pause=0), dd[1], addrs2, 0, "tokens", jup=True)
    hj = F.Http(u2, pause=0)
    F.ds_tokens(hj, dd[2], addrs2, jup=False)
    files = lambda x: {os.path.relpath(f, x): open(f, "rb").read() for f in glob.glob(os.path.join(x, "**", "*"), recursive=True) if os.path.isfile(f)}
    rr = [os.path.join(tmp, "rc%d" % i) for i in range(3)]
    F.rc_reports(F.Http(u2, pause=0), rr[0], addrs2[:5])
    F.rc_reports(F.Http(u2, pause=0), rr[1], addrs2[:5], until=None)
    hr = F.Http(u2, pause=0)
    F.rc_reports(hr, rr[2], addrs2[:5], until=time.time() - 1)
    rows = lambda x: sorted(l for f in glob.glob(os.path.join(x, "risk", "*.txt")) for l in open(f, encoding="utf-8"))
    check(files(dd[0]) == files(dd[1]) and "pairs/jupx_002.txt" in files(dd[0]) and "pairs/jupx_002.txt" not in files(dd[2]) and hj.n == 2
          and rows(rr[0]) == rows(rr[1]) and len(rows(rr[0])) == 5 and hr.n == 0 and not rows(rr[2]),
          "ds_tokens without jup writes the same files as before (the Jupiter fallback included), jup=False asks only DexScreener; rc_reports without until is unchanged,"
          " an until in the past asks nothing")
    srv2.shutdown()
    srv2.server_close()

    print("== launch spotter 3: radar.py uses memebot's own rules, under their own names")
    src = open(os.path.join(HERE, "radar.py"), encoding="utf-8").read()
    pinned = ("apply_profile", "cmd_gather", "load_pairs", "load_side", "load_lists", "merge_pairs", "positions", "scan", "young_rows", "dex_rows", "risk_view",
              "launchpad_of", "x_link", "parse_ms", "num", "B58", "RULE", "PRIOR", "PAPER_GROUPS", "YOUNG_MIN_LIQ", "MIN_SCAN_FOR_REC", "PF_COLS", "GT_COLS", "JUP_COLS")
    used_m = set(re.findall(r"\bM\.([A-Za-z_][A-Za-z0-9_]*)", src))
    used_f = set(re.findall(r"\bF\.([A-Za-z_][A-Za-z0-9_]*)", src))
    check(all("M.%s" % n in src and hasattr(M, n) for n in pinned) and all(hasattr(M, n) for n in used_m) and all(hasattr(F, n) for n in used_f)
          and "blended_weights" not in used_m and not re.search(r"^\s*def (scan|young_rows|cmd_gather|risk_view)\b", src, re.M),
          "radar.py calls %d memebot names (%d pinned) and %d fetch names, every one of them exists, none is copied, and it never calls blended_weights" % (len(used_m), len(pinned), len(used_f)))

    print("== launch spotter 4-9: folder and request isolation, pick, filter parity, held coins, the DexScreener guard, RugCheck")
    rmock = Mock()
    rmock.search_n = 4
    rsrv = serve(rmock)
    ru = "http://127.0.0.1:%d" % rsrv.server_address[1]
    fx = os.path.join(tmp, "fixture")
    os.makedirs(fx)
    subprocess.run([PY, os.path.join(HERE, "fetch.py"), "sources", "--dir", fx, "--mock", ru, "--pause", "0"], capture_output=True, text=True, encoding="utf-8")
    subprocess.run([PY, os.path.join(HERE, "memebot.py"), "gather", "--dir", fx, "--now", str(T0)], capture_output=True, text=True, encoding="utf-8")
    best_fx, _, _ = M.merge_pairs(fx)
    full_fx = {a for a, p in best_fx.items() if not p.get("px_only") and not p.get("dexId") == "jupiter"}
    searched = [c["a"] for c in rmock.coins if c["a"] in full_fx]
    nonfull = [c["a"] for c in rmock.coins if c["a"] not in full_fx]
    prev_addrs = [nonfull[-1], searched[0], nonfull[-2]]     # the second one has a full search pair: never asked

    def snap(x):
        out = {}
        for sub in ("pairs", "risk", "db"):
            for f in glob.glob(os.path.join(x, sub, "**", "*"), recursive=True):
                if os.path.isfile(f):
                    out[os.path.relpath(f, x)] = open(f, "rb").read()
        for n in ("pairs.json", "universe.json"):
            out[n] = open(os.path.join(x, n), "rb").read()
        return out

    def early_run(x, env=None, now=T0, ago=0, url=ru):
        e = dict(os.environ, MEMEBOT_PAUSE="0")
        e.update(env or {})
        t = time.time()
        p = subprocess.run([PY, os.path.join(HERE, "radar.py"), "early", "--dir", x, "--now", str(now), "--t0", str(int(time.time() * 1000) - ago), "--horizon", "2h", "--mock", url],
                           capture_output=True, text=True, encoding="utf-8", env=e)
        try:
            j = json.loads(p.stdout)
        except ValueError:
            j = {}
        doc = json.load(open(os.path.join(x, "young_early.json"), encoding="utf-8")) if os.path.exists(os.path.join(x, "young_early.json")) else {}
        return p, j, doc, time.time() - t

    e0 = os.path.join(tmp, "early0")          # a first run picks two listed coins: one becomes a held new launch, one a pick-mode position
    shutil.copytree(fx, e0)
    _, _, doc0, _ = early_run(e0)
    held_a, pick_a = (doc0.get("coins") or [{}, {}])[0].get("addr"), (doc0.get("coins") or [{}, {}])[1].get("addr")
    os.makedirs(os.path.join(fx, "db", "memepos"))
    os.makedirs(os.path.join(fx, "db", "memeearly"))
    json.dump({"grp": "young", "addr": held_a, "sym": "HELD", "t": T0 - H, "px": 0.001, "ticket": 3.0, "paper": M.PAPER_RULE, "rule": "m9-2h"}, open(os.path.join(fx, "db", "memepos", "y-held.json"), "w"))
    json.dump({"grp": "pick", "addr": pick_a, "sym": "PICK", "t": T0 - H, "px": 0.001, "ticket": 20.0, "rule": "m9-2h"}, open(os.path.join(fx, "db", "memepos", "p-pick.json"), "w"))
    prev_id = rid(T0 - H)
    json.dump({"v": 1, "t": T0 - H, "id": prev_id, "coins": [{"addr": a, "p60": None} for a in prev_addrs]}, open(os.path.join(fx, "db", "memeearly", prev_id + ".json"), "w"))
    ex = os.path.join(tmp, "early")
    shutil.copytree(fx, ex)
    before = snap(ex)
    listed0 = {os.path.relpath(f, ex) for f in glob.glob(os.path.join(ex, "**", "*"), recursive=True) if os.path.isfile(f)}
    seen_rc = []
    rmock.on_rc = lambda path: seen_rc.append(json.load(open(os.path.join(ex, "young_early.json"), encoding="utf-8")) if os.path.exists(os.path.join(ex, "young_early.json")) and not seen_rc else None)
    n0 = len(rmock.log)
    p4, j4, doc4, secs4 = early_run(ex)
    rmock.on_rc = None
    asked = rmock.log[n0:]
    after = snap(ex)
    new = sorted(os.path.relpath(f, ex) for f in glob.glob(os.path.join(ex, "**", "*"), recursive=True) if os.path.isfile(f) and os.path.relpath(f, ex) not in listed0)
    ds_n = sum(1 for x in asked if x.startswith("/api.dexscreener.com/tokens/v1/solana/"))
    print("  spotter: %s in %.1f s; %d requests (%d DexScreener)" % (json.dumps(j4)[:300], secs4, len(asked), ds_n))
    check(p4.returncode == 0 and after == before and all(n == "young_early.json" or n.startswith("radar" + os.sep) for n in new) and "young_early.json" in new
          and all(x.startswith("/api.dexscreener.com/tokens/v1/solana/") or re.match(r"^/api\.rugcheck\.xyz/v1/tokens/[^/]+/report(/summary)?$", x) for x in asked)
          and 0 < ds_n <= 47 and ds_n == j4.get("requests") == -(-doc4.get("asked", 0) // 30),
          "radar.py early leaves pairs/, risk/, pairs.json, universe.json and db/ as they were, writes only radar/ and young_early.json, and asks only DexScreener"
          " tokens/v1 (%d requests for %d addresses) and RugCheck reports" % (ds_n, doc4.get("asked", 0)))
    ind = os.path.join(ex, "radar", "in")
    ep = os.path.join(tmp, "pick")
    shutil.copytree(fx, ep)
    ind0, _ = RD.sandbox(ep)
    with profile("2h"):
        picked, nfull = RD.pick(ind0, prev_addrs)
        cap0 = RD.EARLY_MAX_ADDRS
        RD.EARLY_MAX_ADDRS = 40
        try:
            capped, _ = RD.pick(ind0, prev_addrs)
        finally:
            RD.EARLY_MAX_ADDRS = cap0
        pf_grad = [r["address"] for r in M.pipe_rows(os.path.join(ind0, "pf", "graduated.txt"), M.PF_COLS)]
        sources = {a for sub, cols in (("pf", M.PF_COLS), ("gt", M.GT_COLS), ("jup", M.JUP_COLS)) for a in M.load_side(ind0, sub, cols)[0]} | {a for v in M.load_lists(ind0).values() for a in v}
        first_grad = next(a for a in pf_grad if a not in full_fx and a not in prev_addrs)
    check(picked[:2] == [prev_addrs[0], prev_addrs[2]] and picked[2] == first_grad and not set(picked) & full_fx and set(picked) - set(prev_addrs) <= sources
          and len(capped) == 40 and len(picked) == len(set(picked)) == doc4.get("asked"),
          "pick: the previous early list first (its coin with a full search pair left out), then pump.fun's graduated coins; only source-list addresses, none twice,"
          " none a keyword search already priced; the cap holds (%d asked, %d full search pairs)" % (len(picked), nfull))
    with profile("2h"):
        w4, _ = RD.weights(ex, "2h")
        rows4, _, held4, recent4, risk4 = M.scan(ind, M.positions(ex), M.load_pairs(ind), doc4["at"], w4)
        yr = M.young_rows(rows4, held4, recent4)
        views = {r["a"]: M.risk_view(risk4.get(r["a"])) for r in yr[:20]}
    coins4 = doc4.get("coins") or []
    check(doc4.get("state") == "listed" and [c["addr"] for c in coins4] == [r["a"] for r in yr[:20]] and doc4.get("n") == len(yr) and [c["k"] for c in coins4] == list(range(1, len(coins4) + 1))
          and all(c["ageMin"] == int(60 * r["basic"]["age_h"]) for c, r in zip(coins4, yr)),
          "the early list is memebot's young_rows on the sandbox at the spotter's clock, in the same order (%d of %d shown)" % (len(coins4), len(yr)))
    check(held_a and any(c["addr"] == held_a and c["held"] is True for c in coins4) and pick_a not in {c["addr"] for c in coins4} and all(c["held"] is False for c in coins4 if c["addr"] != held_a),
          "a coin the paper account holds (new launch) is listed and marked held; a pick-mode position's coin is left out, as scan() does")
    check(seen_rc and isinstance(seen_rc[0], dict) and seen_rc[0].get("rcState") == "pending" and all(c.get("rc") is None for c in seen_rc[0].get("coins") or [{"rc": 1}])
          and doc4.get("rcState") == "done" and all((c["rc"]["level"], c["rc"]["text"]) == ((("danger" if "danger" in views[c["addr"]][1].lower() else "warn"), views[c["addr"]][1][:120]) if views[c["addr"]][0] is False
                                                                                         else ("clean", "RugCheck: no danger flags") if views[c["addr"]][0] else ("none", "no RugCheck report")) for c in coins4)
          and glob.glob(os.path.join(ind, "risk", "reports_*.txt")) and not glob.glob(os.path.join(ex, "risk", "*")) and j4.get("rcGot") == len(coins4),
          "v1 is written before the first RugCheck request (all pending), v2 carries memebot's risk_view for each coin; the reports land in radar/in/risk (%s)" % (
              sorted({c["rc"]["level"] for c in coins4})))
    prev_j = json.load(open(os.path.join(ex, "radar", "prev.json"), encoding="utf-8"))
    check(prev_j.get("id") == prev_id and prev_j.get("at") == doc4.get("at") and set(prev_j.get("coins") or {}) == set(prev_addrs)
          and all("px" in v or v.get("gone") for v in prev_j["coins"].values()),
          "the previous early list is priced again at the spotter's clock (radar/prev.json, %d coins)" % len(prev_j.get("coins") or {}))
    # the spotter's own clock end to end: a run that starts 5 minutes after the cycle's start lists its coins at about minute 5, each as old as it is then
    ec = os.path.join(tmp, "eclock")
    shutil.copytree(fx, ec)
    pcl, jcl, doccl, _ = early_run(ec, ago=5 * 60_000)
    ccl, lag = doccl.get("coins") or [], (doccl.get("at") or 0) - T0
    check(pcl.returncode == 0 and 5 * 60_000 <= lag < 6 * 60_000 and ccl and jcl.get("at") == doccl.get("at")
          and all(0 <= (doccl["at"] - c["born"]) / 60_000 - c["ageMin"] < 1.001 for c in ccl),
          "started 5 minutes into the cycle, the spotter lists its coins at minute %.1f of the cycle's clock, each one as old as its pair is then" % (lag / 60_000))
    # one DexScreener error makes no coin gone: a 500 on the request that carries the previous list leaves those coins unknown, and the list partial
    e5 = os.path.join(tmp, "ds500")
    shutil.copytree(fx, e5)
    hit5 = []

    def first500(path):
        if "/tokens/v1/" in path and not hit5:
            hit5.append(path)
            return 500, {"error": "boom"}
    rmock.hook = first500
    p5, j5, doc5, _ = early_run(e5)
    rmock.hook = None
    prev5 = json.load(open(os.path.join(e5, "radar", "prev.json"), encoding="utf-8")) if os.path.exists(os.path.join(e5, "radar", "prev.json")) else {}
    check(p5.returncode == 0 and hit5 and prev_addrs[0] in hit5[0] and doc5.get("state") == "listed" and doc5.get("partial") is True and "without an answer" in (doc5.get("why") or "")
          and set(prev5.get("coins") or {}) == {searched[0]} and "px" in prev5["coins"][searched[0]],
          "a DexScreener 500 on the request with the previous list marks none of its coins gone (they stay unknown: %s), and the list says partial (%s)" % (
              sorted(prev5.get("coins") or {}) == [searched[0]], doc5.get("why")))
    # a coin of the previous list that only a keyword search priced, and whose pair shows no price, is gone (never unknown): it is not asked again
    e5z = os.path.join(tmp, "prevzero")
    shutil.copytree(fx, e5z)
    zeroed = 0
    for f in glob.glob(os.path.join(e5z, "pairs", "search_*.txt")):
        rows_ = open(f, encoding="utf-8").read().split("\n")
        for i_, line in enumerate(rows_):
            cells = line.split("|")
            if cells and cells[0] == searched[0] and len(cells) > 5:
                cells[5] = "0"
                rows_[i_] = "|".join(cells)
                zeroed += 1
        open(f, "w", encoding="utf-8").write("\n".join(rows_))
    n0z = len(rmock.log)
    p5z, _, doc5z, _ = early_run(e5z)
    prev5z = json.load(open(os.path.join(e5z, "radar", "prev.json"), encoding="utf-8")) if os.path.exists(os.path.join(e5z, "radar", "prev.json")) else {}
    check(p5z.returncode == 0 and zeroed and (prev5z.get("coins") or {}).get(searched[0]) == {"gone": True} and not any(searched[0] in x for x in rmock.log[n0z:])
          and all("px" in v or v.get("gone") for v in (prev5z.get("coins") or {}).values()),
          "a coin of the previous list priced only by a keyword search whose pair shows price 0 is recorded gone, not unknown (it is not asked again: %s)" % (
              (prev5z.get("coins") or {}).get(searched[0])))
    # a coin of the previous list known only from a list's stand-in row (GeckoTerminal) without a price, while DexScreener does not answer the
    # request that carries it: unknown, never gone (only DexScreener's answer, or its own pair without a price, makes a coin gone)
    gt_fx = [a for a, p_ in M.load_pairs(fx).items() if p_.get("gt_only") and a not in prev_addrs]
    e5g = os.path.join(tmp, "prevstandin")
    shutil.copytree(fx, e5g)
    blanked, hit5g, prev5g = 0, [], {}
    if gt_fx:
        g_ = gt_fx[0]
        pi_ = M.GT_COLS.index("priceUsd")
        for f in glob.glob(os.path.join(e5g, "gt", "*.txt")):
            rows_ = open(f, encoding="utf-8").read().split("\n")
            for i_, line in enumerate(rows_):
                cells = line.split("|")
                if cells and cells[0] == g_ and len(cells) > pi_:
                    cells[pi_] = ""
                    rows_[i_] = "|".join(cells)
                    blanked += 1
            open(f, "w", encoding="utf-8").write("\n".join(rows_))
        json.dump({"v": 1, "t": T0 - H, "id": prev_id, "coins": [{"addr": g_, "p60": None}]}, open(os.path.join(e5g, "db", "memeearly", prev_id + ".json"), "w"))

        def first500g(path):
            if "/tokens/v1/" in path and not hit5g:
                hit5g.append(path)
                return 500, {"error": "boom"}
        rmock.hook = first500g
        p5g, _, _, _ = early_run(e5g)
        rmock.hook = None
        prev5g = json.load(open(os.path.join(e5g, "radar", "prev.json"), encoding="utf-8")) if os.path.exists(os.path.join(e5g, "radar", "prev.json")) else {}
    check(gt_fx and blanked and p5g.returncode == 0 and hit5g and gt_fx[0] in hit5g[0] and prev5g.get("id") == prev_id and gt_fx[0] not in (prev5g.get("coins") or {})
          and RD.standin({"gt_only": True}) and RD.standin({"dexId": "Jupiter"}) and RD.standin({"gm_only": True}) and RD.standin({"px_only": True}) and not RD.standin({"dexId": "raydium"}),
          "a coin of the previous list known only from a GeckoTerminal row without a price, whose DexScreener request got a 500, stays unknown, never gone (%s)" % (
              (prev5g.get("coins") or {}).get(gt_fx[0] if gt_fx else "", "unknown")))
    # the edge cases, on a sandbox built by hand at an exact clock: 60 minutes old, under $5k, on the curve, list-only, born after the scan started, held
    with profile("2h"):
        ed = os.path.join(tmp, "edge")
        ein = os.path.join(ed, "radar", "in")
        for sub in ("pairs", "pf", "jup"):
            os.makedirs(os.path.join(ein, sub))
        os.makedirs(os.path.join(ed, "db", "memepos"))
        at, now_e = T0 + 7 * 60_000, T0 + 2 * 60_000
        erng = random.Random(11)
        A = {k: b58(erng) for k in ("old", "low", "curve", "nodex", "new", "ok", "held", "pick")}

        def pr(a, sym, born, liq, dex="pumpswap"):
            return F.ds_row({"chainId": "solana", "dexId": dex, "pairAddress": a[:30] + "Pair1", "baseToken": {"address": a, "symbol": sym, "name": sym.title()}, "priceUsd": "0.0001",
                             "marketCap": 90000, "fdv": 90000, "liquidity": {"usd": liq}, "volume": {"h24": 60000, "h6": 50000, "h1": 30000}, "priceChange": {"m5": 5, "h1": 10, "h6": 10, "h24": 10},
                             "txns": {"h24": {"buys": 300, "sells": 200}, "h6": {"buys": 200, "sells": 150}, "h1": {"buys": 100, "sells": 80}}, "pairCreatedAt": born})
        open(os.path.join(ein, "pairs", "search_edge.txt"), "w").write("\n".join([
            pr(A["old"], "OLDE", at - 60 * 60_000, 20000), pr(A["low"], "LOWE", at - 30 * 60_000, 4999), pr(A["curve"], "CURVE", at - 10 * 60_000, 20000, "pumpfun"),
            pr(A["new"], "NEWE", at - 3 * 60_000, 20000), pr(A["ok"], "OKE", at - 20 * 60_000, 20000), pr(A["held"], "HELDE", at - 25 * 60_000, 20000),
            pr(A["pick"], "PICKE", at - 15 * 60_000, 20000)]) + "\n")
        open(os.path.join(ein, "pf", "graduated.txt"), "w").write(F.row(A["ok"], "OKE", "Oke", 90000, 50, 180000, 3, False, True, at - 3 * H, None, None, None) + "\n")
        jrow = [A["nodex"], "NODEX", "Nodex", 0.0001, 90000, 90000, 20000] + [None] * 5 + [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((at - 20 * 60_000) / 1000))] + [None] * 15
        open(os.path.join(ein, "jup", "trending1h.txt"), "w").write(F.row(*jrow) + "\n")
        json.dump({"grp": "young", "addr": A["held"], "t": now_e - H, "px": 0.0001, "ticket": 3.0, "paper": M.PAPER_RULE}, open(os.path.join(ed, "db", "memepos", "y.json"), "w"))
        json.dump({"grp": "pick", "addr": A["pick"], "t": now_e - H, "px": 0.0001, "ticket": 20.0}, open(os.path.join(ed, "db", "memepos", "p.json"), "w"))
        RD.gather(ein, at)
        ecoins, en, _ = RD.listing(ed, ein, at, dict(M.PRIOR))
        erows, _, eheld, erecent, _ = M.scan(ein, M.positions(ed), M.load_pairs(ein), at, dict(M.PRIOR))
        eparity = [r["a"] for r in M.young_rows(erows, eheld, erecent)]
    by = {c["addr"]: c for c in ecoins}
    check(set(by) == {A["new"], A["ok"], A["held"]} and [c["addr"] for c in ecoins] == eparity and by[A["new"]]["ageMin"] == 3 and by[A["new"]]["born"] > now_e
          and by[A["ok"]]["minted"] == at - 3 * H and by[A["ok"]]["launchpad"] == "pump.fun" and by[A["held"]]["held"] is True and by[A["new"]]["minted"] is None,
          "edge cases at an exact clock: a coin born after the scan started is listed %d min old; 60 minutes old, $4,999, on the launch curve, list-only and a"
          " pick-mode coin are not; pump.fun's createdAt fills minted" % by.get(A["new"], {}).get("ageMin", -1))
    # the DexScreener guard: a 429 stops the spotter's DexScreener calls at once (no wait), the list comes from the search pairs
    e8 = os.path.join(tmp, "ds429")
    shutil.copytree(fx, e8)
    rmock.ds429 = True
    n0 = len(rmock.log)
    p8, j8, doc8, secs8 = early_run(e8)
    rmock.ds429 = False
    ds8 = sum(1 for x in rmock.log[n0:] if "/tokens/v1/" in x)
    prev8 = json.load(open(os.path.join(e8, "radar", "prev.json"), encoding="utf-8")) if os.path.exists(os.path.join(e8, "radar", "prev.json")) else {}
    check(p8.returncode == 0 and secs8 < 5 and ds8 == 1 and doc8.get("partial") is True and doc8.get("dsWaits") == 1 and doc8.get("requests") == 1 and doc8.get("state") == "listed"
          and doc8.get("coins") and "rate limit" in (doc8.get("why") or "") and set(prev8.get("coins") or {}) == {searched[0]},
          "the first DexScreener 429 stops the spotter's DexScreener calls with no wait (%.1f s, %d request): partial, listed from the search pairs;"
          " the previous list's coins it never answered for are not marked gone" % (secs8, ds8))
    e8b = os.path.join(tmp, "small")
    shutil.copytree(fx, e8b)
    for f in sorted(glob.glob(os.path.join(e8b, "pairs", "search_*.txt")))[2:]:
        os.remove(f)
    rmock.ds_dead = True
    p8b, j8b, doc8b, _ = early_run(e8b)
    rmock.ds_dead = False
    check(p8b.returncode == 0 and doc8b.get("state") == "small" and doc8b.get("coins") == [] and (doc8b.get("pairs") or 0) < M.MIN_SCAN_FOR_REC,
          "under %d DexScreener pairs there is no early list (state small, %s pairs)" % (M.MIN_SCAN_FOR_REC, doc8b.get("pairs")))
    # RugCheck that never answers: the list keeps its coins, RugCheck ends at its time cap (shortened here)
    from http.server import ThreadingHTTPServer

    class Hang(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path.startswith("/api.rugcheck.xyz/"):
                threading.Event().wait(15)
            code, body = rmock.handle(u.path, u.query)
            raw = (body if isinstance(body, str) else json.dumps(body)).encode()
            try:
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    hsrv = ThreadingHTTPServer(("127.0.0.1", 0), Hang)
    hsrv.daemon_threads = True
    threading.Thread(target=hsrv.serve_forever, daemon=True).start()
    e9 = os.path.join(tmp, "rchang")
    shutil.copytree(fx, e9)
    p9, j9, doc9, secs9 = early_run(e9, {"MEMEBOT_EARLY_RC_S": "2"}, url="http://127.0.0.1:%d" % hsrv.server_address[1])
    hsrv.shutdown()
    t9 = sorted(c["rc"]["text"] for c in doc9.get("coins") or [])
    check(p9.returncode == 0 and doc9.get("rcState") == "down" and doc9.get("state") == "listed" and doc9.get("coins") and all(c["rc"]["level"] == "none" for c in doc9["coins"]) and secs9 < 15
          and t9.count("RugCheck did not answer") == 1 and t9.count("RugCheck: not checked") == len(t9) - 1,
          "RugCheck that never answers ends at the spotter's RugCheck cap: rcState down, the coin asked reads 'RugCheck did not answer', the others"
          " 'RugCheck: not checked', the list stays (%.1f s with a 2 s cap)" % secs9)
    bad_rc = {c["addr"] for c in coins4[:2]}
    rc_runs = []
    for bad in (bad_rc, None):        # RugCheck answers 502 for two coins, then for every coin
        er = os.path.join(tmp, "rc502-%d" % len(rc_runs))
        shutil.copytree(fx, er)
        rmock.hook = lambda path, bad=bad: ((502, {"error": "bad gateway"}) if re.match(r"^/api\.rugcheck\.xyz/v1/tokens/[^/]+/report", path)
                                          and (bad is None or path.split("/")[4] in bad) else None)
        rc_runs.append(early_run(er)[2])
        rmock.hook = None
    r5a, r5b = rc_runs
    unans = lambda doc: {c["addr"] for c in doc.get("coins") or [] if (c.get("rc") or {}).get("text") == "RugCheck did not answer"}
    check(r5a.get("rcState") == "partial" and unans(r5a) == bad_rc and all(c["rc"]["level"] != "none" for c in r5a.get("coins") or [] if c["addr"] not in bad_rc)
          and r5b.get("rcState") == "down" and unans(r5b) == {c["addr"] for c in r5b.get("coins") or []} and r5b.get("coins"),
          "RugCheck answering 502 is not 'no report': two coins read 'RugCheck did not answer' and the list is partial; when every request fails it is down")
    # RugCheck answers that are no answer about the coin (401, 403, 410, 451) read "RugCheck did not answer"; only a 404 is "no RugCheck report"
    rc_codes = {}
    for code_ in (401, 403, 404, 410, 451):
        a_ = coins4[0]["addr"]
        rmock.hook = lambda path, code_=code_: (code_, {"error": "x"}) if re.match(r"^/api\.rugcheck\.xyz/v1/tokens/[^/]+/report", path) else None
        h_ = RD.SpotHttp(ru, 0, 2)        # the spotter's own client (RD.setup would also set the profile and fetch's limits in this process)
        with contextlib.redirect_stderr(io.StringIO()):
            F.rc_reports(h_, os.path.join(tmp, "rcwords-%d" % code_), [a_], until=time.time() + 10)
        rc_codes[code_] = RD.rc_word(h_, a_, None)["text"]
        rmock.hook = None
    check(rc_codes == {401: "RugCheck did not answer", 403: "RugCheck did not answer", 404: "no RugCheck report", 410: "RugCheck did not answer", 451: "RugCheck did not answer"},
          "RugCheck answering 401, 403, 410 or 451 reads 'RugCheck did not answer', only a 404 reads 'no RugCheck report' %s" % rc_codes)

    print("== launch spotter 9b: the spotter's own request rules (SpotHttp): a 429 on any try, the pause after an error, each try inside the deadline")
    plan, seen_q = [], []

    class Seq(BaseHTTPRequestHandler):
        def do_GET(self):
            seen_q.append(self.path)
            act = plan.pop(0) if plan else "200"
            if act == "drop":          # the connection closes with no answer
                self.close_connection = True
                return
            if act == "hang":
                threading.Event().wait(4)
                act = "200"
            raw = b"[]" if act == "200" else b'{"error":"x"}'
            try:
                self.send_response(int(act)); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    qsrv = ThreadingHTTPServer(("127.0.0.1", 0), Seq)
    qsrv.daemon_threads = True
    threading.Thread(target=qsrv.serve_forever, daemon=True).start()
    qu = "http://127.0.0.1:%d" % qsrv.server_address[1]
    dsu = F.DS + "/tokens/v1/solana/" + "1" * 44
    sleeps, sleep0 = [], time.sleep
    time.sleep = sleeps.append            # the pauses are noted, not waited
    try:
        qlog = []
        h1 = RD.SpotHttp(qu, pause=0.3, tries=2)
        h1.log = qlog.append
        plan[:] = ["drop", "429"]
        r1, n1 = h1.get(dsu), len(seen_q)
        r1b = h1.get(dsu)
        ok1 = (r1 is None and r1b is None and n1 == 2 and len(seen_q) == 2 and RD.DS_HOST in h1.dead and h1.limited_by.get(RD.DS_HOST) == 1
               and any("429 rate limited by api.dexscreener.com" in x for x in qlog) and not any("waiting" in x for x in qlog))
        seen_q.clear(); sleeps.clear()
        h2 = RD.SpotHttp(qu, pause=0.3, tries=2)
        h2.log = lambda x: None
        ua, ub, uc = (F.RC + "/tokens/%s/report" % k for k in ("A" * 44, "B" * 44, "C" * 44))
        plan[:] = ["500", "404", "200"]
        r2 = [h2.get(u) for u in (ua, ub, uc)]
        ok2 = r2 == [None, None, []] and len(seen_q) == 3 and sleeps == [0.3, 0.3, 0.3] and h2.tried == {ua, ub, uc} and h2.heard == {ub, uc}
        seen_q.clear()
        h3 = RD.SpotHttp(qu, pause=0, tries=2)
        h3.log = lambda x: None
        plan[:] = ["hang", "hang"]
        h3.until = time.time() + 1.5
        t3 = time.time()
        r3 = h3.get(dsu)
        el3, n3 = time.time() - t3, len(seen_q)
        seen_q.clear()
        h4 = RD.SpotHttp(qu, pause=0, tries=1)
        h4.log = lambda x: None
        plan[:] = ["drop", "200"]
        r4 = h4.get(dsu)
        n4 = len(seen_q)
    finally:
        time.sleep = sleep0
        plan[:] = []
        qsrv.shutdown()
    check(ok1, "a 429 on the second try (after a dropped connection) gives DexScreener up at once and counts: no wait, no 'waiting' in the log, no later request")
    check(ok2, "the pause follows every answer, a 500 and a 404 too; a 404 counts as RugCheck's answer, a 500 as none")
    check(r3 is None and n3 == 1 and 1.2 < el3 < 2.4 and r4 is None and n4 == 1,
          "each try's timeout is what is left of the deadline and no retry starts without time for it (%.1f s for a 1.5 s deadline, %d request);"
          " radar.py check's client tries once (%d request)" % (el3, n3, n4))
    # the request budget at full scale: EARLY_MAX_ADDRS addresses take 45 DexScreener requests of at most 30 addresses
    brng = random.Random(17)
    big = [b58(brng) for _ in range(RD.EARLY_MAX_ADDRS)]
    bdir = os.path.join(tmp, "budget")
    os.makedirs(os.path.join(bdir, "pairs"))
    n0 = len(rmock.log)
    with contextlib.redirect_stderr(io.StringIO()):
        why_b, ans_b = RD.fetch_pairs(RD.SpotHttp(ru, pause=0), bdir, big, time.time() + 120)
    breq = [x for x in rmock.log[n0:] if "/tokens/v1/" in x]
    check(why_b is None and len(breq) == 45 and max(len(x.rsplit("/", 1)[1].split(",")) for x in breq) == 30 and ans_b == set(big),
          "at the cap of %d addresses the spotter asks DexScreener %d times, 30 addresses at most each" % (RD.EARLY_MAX_ADDRS, len(breq)))

    print("== launch spotter 10: bot.py's wiring (a failed, a hanging and a switched-off spotter, a stale early list, early_doc)")
    lb = git_live(remote_off)
    off_b = json.load(open(os.path.join(db_, "db", "memebot", "office.json"), encoding="utf-8"))
    check(not os.path.exists(os.path.join(db_, "young_early.json")) and (lb.get("young") or {}).get("state") == "off" and (lb.get("young") or {}).get("why") == "early list switched off"
          and (lb.get("young") or {}).get("t") == T0 and "STALE" not in json.dumps(lb) and "spotter" not in {a["id"] for a in off_b["agents"]} and "young" not in off_b
          and "radar.py" not in pb.stderr,
          "MEMEBOT_EARLY=0 starts no spotter and the live view says the early list is off; a stale early list of an earlier cycle is deleted at the start and never pushed")
    code = os.path.join(tmp, "code")
    os.makedirs(code)
    for n in ("bot.py", "memebot.py", "fetch.py", "report.py", "page_account.py", "page_radar.py", "page_office.py", "traps.py", "radar_weights.json"):
        shutil.copy(os.path.join(HERE, n), code)
    with open(os.path.join(code, "radar.py"), "w") as f:      # stand-ins for the spotter: one that fails (and whose check fails too), one that never ends
        f.write("import json, os, sys, time\n"
                "a = sys.argv\nd = a[a.index('--dir') + 1]; now = int(a[a.index('--now') + 1])\n"
                "open(os.path.join(d, 'stub.pid'), 'w').write(str(os.getpid()))\n"
                "if os.environ.get('STUB') == 'rcsleep' and a[1] == 'early':\n"     # a listed list written, then stuck in RugCheck until it is killed
                "    cs = [{'addr': x * 40 + 'pump', 'sym': x * 3, 'born': now - 60000, 'ageMin': 1, 'k': i + 1} for i, x in enumerate('AB')]\n"
                "    json.dump({'v': 1, 't': now, 'id': 'stub', 'at': now + 1000, 'state': 'listed', 'rcState': 'pending', 'partial': False, 'n': 2, 'coins': cs},"
                " open(os.path.join(d, 'young_early.json.tmp'), 'w'))\n    os.replace(os.path.join(d, 'young_early.json.tmp'), os.path.join(d, 'young_early.json'))\n"
                "    time.sleep(600)\n"
                "if (os.environ.get('STUB') == 'sleep' and a[1] == 'early') or (os.environ.get('STUB') == 'checksleep' and a[1] == 'check'):\n    time.sleep(600)\n"
                "if a[1] == 'early':\n    json.dump({'v': 1, 't': now, 'state': 'failed', 'why': 'stub failed', 'coins': []}, open(os.path.join(d, 'young_early.json'), 'w'))\n"
                "print('{\"state\": \"failed\", \"why\": \"stub failed\"}')\nsys.stderr.write('stub %s failed\\n' % a[1])\nsys.exit(1)\n")
    df, ds_ = os.path.join(tmp, "stub-fail"), os.path.join(tmp, "stub-sleep")
    pf, sf, _ = spot_cycle(df, {"STUB": "fail"}, code=code, frozen=True)
    psl, ssl, _ = spot_cycle(ds_, {"STUB": "sleep"}, code=code)
    ofs = {a["id"]: a for a in json.load(open(os.path.join(df, "db", "memebot", "office.json"), encoding="utf-8"))["agents"]}
    osl = {a["id"]: a for a in json.load(open(os.path.join(ds_, "db", "memebot", "office.json"), encoding="utf-8"))["agents"]}
    rec_f, rec_a = (json.load(open(os.path.join(x, "db", "memebot", "recommend.json"), encoding="utf-8")) for x in (df, da))
    check(pf.returncode == 0 and ofs["spotter"]["status"] == "failed" and "stub failed" in ofs["spotter"]["out"] and json.load(open(os.path.join(df, "young_early.json")))["state"] == "failed"
          and masked(rec_f, WALL_KEYS) == masked(rec_a, WALL_KEYS) and ofs["trader"]["status"] == "done" and ofs["reporter"]["status"] == "done"
          and "radar.py check failed (exit 1), the cycle goes on" in pf.stderr and set(trader_files(df)) == set(fa),
          "a spotter that exits 1 and a radar.py check that fails leave the cycle as without them (the same recommendations, every trader doc); the office shows the spotter failed")
    pid = int(open(os.path.join(ds_, "stub.pid")).read())
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    gap = osl["trader"]["start"] - osl["spotter"]["end"]
    check(psl.returncode == 0 and osl["spotter"]["status"] == "failed" and osl["spotter"]["out"] == "still running at the trader step" and 0 <= gap < 1000 and not alive
          and osl["trader"]["status"] == "done",
          "a spotter still at work when the trader starts is stopped there: the trader starts %d ms later, the process is gone, the cycle goes on" % gap)
    # a cycle that fails in a foreground step (here memebot.py shortlist, in a copy of the code) stops its spotter too: no process outlives the cycle
    code2 = os.path.join(tmp, "code2")
    shutil.copytree(code, code2)
    msrc = open(os.path.join(code2, "memebot.py"), encoding="utf-8").read()
    with open(os.path.join(code2, "memebot.py"), "w", encoding="utf-8") as f:
        f.write("import os as _o, sys as _s\nif __name__ == '__main__' and _s.argv[1:2] == [_o.environ.get('STUB_STEP_FAIL')]:\n"
                "    print('{\"stub\": \"%s fails\"}' % _s.argv[1]); _s.exit(3)\n" + msrc)
    dor = os.path.join(tmp, "stub-orphan")
    por, sor, _ = spot_cycle(dor, {"STUB": "sleep", "STUB_STEP_FAIL": "shortlist"}, code=code2)
    oor = {a["id"]: a for a in json.load(open(os.path.join(dor, "db", "memebot", "office.json"), encoding="utf-8"))["agents"]}
    pid_o = int(open(os.path.join(dor, "stub.pid")).read()) if os.path.exists(os.path.join(dor, "stub.pid")) else 0

    def gone(pid):
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True
    check(por.returncode != 0 and pid_o and gone(pid_o) and (oor.get("analyst") or {}).get("status") == "failed" and (oor.get("spotter") or {}).get("status") == "failed"
          and (oor.get("spotter") or {}).get("out") == "stopped when the scan stopped" and "trader" not in oor and sor < 120,
          "a cycle that fails in a foreground step (shortlist) kills its spotter before it ends: the process is gone, the office says why (%.0f s)" % sor)
    # a spotter killed while RugCheck is still on its way: the list says RugCheck did not finish, in young_early.json and in the last push,
    # whether the trader step stops it or the cycle fails (the page never shows "checking..." for the rest of the hour)
    rc_out = []
    for name_, env_, code_ in (("trader", {"STUB": "rcsleep"}, code), ("fail", {"STUB": "rcsleep", "STUB_STEP_FAIL": "shortlist"}, code2)):
        dr_, rr_ = os.path.join(tmp, "stub-rc-" + name_), tempfile.mkdtemp(prefix="memebot-rc-live-")
        subprocess.run(["git", "init", "-q", "--bare", rr_], check=True)
        pr_, _, _ = spot_cycle(dr_, env_, code=code_, remote=rr_)
        yr_ = json.load(open(os.path.join(dr_, "young_early.json"), encoding="utf-8")) if os.path.exists(os.path.join(dr_, "young_early.json")) else {}
        lr_ = git_live(rr_)
        rc_out.append((pr_.returncode, yr_.get("rcState"), yr_.get("rcWhy"), (lr_.get("young") or {}).get("rcState"), (lr_.get("young") or {}).get("rcWhy"), lr_.get("live")))
        shutil.rmtree(rr_, ignore_errors=True)
    (rc0, ys0, yw0, ls0, lw0, lv0), (rc1, ys1, yw1, ls1, lw1, lv1) = rc_out
    check(rc0 == 0 and ys0 == ls0 == "partial" and yw0 == lw0 and "RugCheck did not finish" in (yw0 or "") and "scoring began" in yw0 and lv0 is False
          and rc1 != 0 and ys1 == ls1 == "partial" and yw1 == lw1 == B.RC_UNFINISHED and lv1 is False,
          "a spotter killed in the middle of RugCheck leaves no 'checking': young_early.json and the last live push say rcState partial with the reason, when the"
          " trader step stops it (%r) and when the cycle fails (%r)" % (yw0, yw1))
    # radar.py check sits on the scan's critical path: bot.py kills it after its time limit and goes on
    dl = os.path.join(tmp, "limit")
    os.makedirs(dl)
    here0, stub0 = B.HERE, os.environ.get("STUB")
    B.HERE, os.environ["STUB"] = code, "checksleep"
    try:
        t_ = time.time()
        with contextlib.redirect_stderr(io.StringIO()) as er_:
            rl = B.run(["radar.py", "check", "--t0", str(T0), "--horizon", "2h"], dl, T0, soft=True, limit=2)
        el_ = time.time() - t_
    finally:
        B.HERE = here0
        if stub0 is None:
            os.environ.pop("STUB", None)
        else:
            os.environ["STUB"] = stub0
    pid_l = int(open(os.path.join(dl, "stub.pid")).read()) if os.path.exists(os.path.join(dl, "stub.pid")) else 0
    bsrc = open(os.path.join(HERE, "bot.py"), encoding="utf-8").read()
    check(rl is None and el_ < 6 and pid_l and gone(pid_l) and "radar.py check stopped after 2 s, the cycle goes on" in er_.getvalue()
          and "soft=True, limit=CHECK_LIMIT_S)" in bsrc and B.CHECK_LIMIT_S <= 30,
          "a radar.py check that hangs is killed at its time limit (%.1f s for 2 s; %d s in the cycle) and the cycle goes on" % (el_, B.CHECK_LIMIT_S))
    tmpd = os.path.join(tmp, "ed")
    os.makedirs(tmpd)
    pe = os.path.join(tmpd, "young_early.json")
    good = {"v": 1, "t": T0, "id": rid(T0), "at": T0 + 270000, "state": "listed", "rcState": "done", "partial": False, "n": 2, "why": "x" * 300,
            "coins": [{"addr": "A" * 40 + "pump", "sym": "<b>" + "S" * 40, "name": "N" * 90, "pair": "javascript:alert(1)", "x": "javascript:alert(1)", "born": T0, "ageMin": 4, "px": float("nan"),
                       "liq": float("inf"), "mc": 5e4, "src": ["a" * 50] * 9, "held": "yes", "k": 1, "rc": {"level": "danger", "text": "t" * 300, "top1": 5}, "evil": "<script>"},
                      {"addr": "0xBAD", "sym": "BAD"}, {"addr": "B" * 44, "x": "https://x.com/good_one/status/123", "rc": {"level": "pwned"}}]}

    def w_(doc, raw=None):
        with open(pe, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(doc))
        return B.early_doc(pe, T0)
    c1 = w_(good)
    big = dict(good, coins=[dict(good["coins"][2], name="\U0001f438" * 48, sym="\U0001f438" * 24, src=["\U0001f438" * 24] * 6, rc={"level": "warn", "text": "\U0001f438" * 120}) for _ in range(20)])
    cc = (c1 or {}).get("coins") or [{}]
    check(c1 and len(cc) == 2 and cc[0]["sym"] == "<b>" + "S" * 21 and len(cc[0]["name"]) == 48 and cc[0]["pair"] is None and cc[0]["x"] == "" and cc[0]["px"] is None and cc[0]["liq"] is None
          and len(cc[0]["src"]) == 6 and all(len(x) == 24 for x in cc[0]["src"]) and cc[0]["held"] is False and len(cc[0]["rc"]["text"]) == 120 and "evil" not in cc[0] and len(c1["why"]) == 120
          and cc[1]["x"] == "https://x.com/good_one/status/123" and cc[1]["rc"] is None
          and w_(None, "{not json") is None and w_(None, "[]") is None and w_(dict(good, t=T0 - 1)) is None and w_(dict(good, state="weird")) is None and w_(dict(good, v=2)) is None
          and w_(big) is None and B.early_doc(os.path.join(tmpd, "missing.json"), T0) is None,
          "early_doc keeps only known keys, cuts the strings, drops a coin with a bad address, blanks a javascript: link, nulls NaN and infinity, and refuses"
          " a malformed, other-cycle, unknown-state or over-24 KB file")

    print("== launch spotter 11: the live view pushes the early list at once (the kick), and once more at the end")
    ud = os.path.join(tmp, "liveunit")
    os.makedirs(ud)
    lr = os.path.join(tmp, "live-unit.git")
    subprocess.run(["git", "init", "-q", "--bare", lr], check=True)
    B.OFFICE = B.Office(ud, T0, "2h")
    B.OFFICE.begin("spotter", bg=True)
    with B.EARLY_LOCK:
        B.EARLY.update(t=T0, doc=None, rev=B.EARLY["rev"] + 1, sig=None)
    lv = B.Live(ud, lr)
    v1 = dict(good, coins=[good["coins"][0]], rcState="pending", why="")
    head0 = ""

    def wait_young(pred, secs):
        t_ = time.time()
        while time.time() - t_ < secs:
            j = git_live(lr)
            if pred(j):
                return time.time() - t_, j
            threading.Event().wait(0.1)
        return None, git_live(lr)
    json.dump(v1, open(os.path.join(ud, "young_early.json"), "w"))
    k1, l1 = wait_young(lambda j: (j.get("young") or {}).get("rcState") == "pending", 8)
    json.dump(dict(v1, rcState="done"), open(os.path.join(ud, "young_early.json"), "w"))
    k2, l2 = wait_young(lambda j: (j.get("young") or {}).get("rcState") == "done", 12)
    lv.finish()
    l3 = git_live(lr)
    B.OFFICE.save()
    offj = json.load(open(os.path.join(ud, "db", "memebot", "office.json")))
    lc = git_live(remote_on)
    check(k1 is not None and k1 < 3 and l1.get("live") is True and k2 is not None and k2 < B.LIVE_KICK + 3 and l3.get("live") is False and (l3.get("young") or {}).get("rcState") == "done"
          and "young" not in offj and (lc.get("young") or {}).get("state") == "listed" and lc.get("live") is False and (lc.get("young") or {}).get("t") == T0
          and "young" not in off_c,
          "a new early list is pushed %.1f s after the file appears (not 45 s later), its RugCheck update %.1f s later; the last push (live false) carries it, in a real cycle too;"
          " office.json never does" % (k1 or -1, k2 or -1))

    print("== launch spotter 12: the record, db/memeearly")
    dk = os.path.join(tmp, "check")
    os.makedirs(os.path.join(dk, "db", "memebot"))
    os.makedirs(os.path.join(dk, "db", "memeearly"))
    os.makedirs(os.path.join(dk, "radar"))
    cs = [c for c in rmock.coins if not c["gone"]][200:207]
    born = lambda i: T0 - (10 + i) * 60_000
    early_k = [{"addr": c["a"], "sym": c["sym"], "pair": c["a"][:20] + "pair", "born": born(i), "ageMin": 10 + i, "px": c["px"], "liq": c["liq"], "mc": c["mc"], "score": 50 - i, "k": i + 1,
                "held": False, "rc": {"level": "warn", "text": "w"}} for i, c in enumerate(cs[:5] + cs[6:7])]
    early_k[1]["born"] = T0 + 60_000
    json.dump({"v": 1, "t": T0, "id": rid(T0), "at": T0 + 270000, "rcAt": T0 + 300000, "state": "listed", "rcState": "done", "partial": False, "rule": "m9-2h", "horizon": "2h", "n": 6,
               "coins": early_k}, open(os.path.join(dk, "young_early.json"), "w"))
    json.dump({"t": T0, "young": [{"addr": cs[0]["a"], "bought": 3.0}, {"addr": cs[5]["a"], "bought": "held"}]}, open(os.path.join(dk, "db", "memebot", "recommend.json"), "w"))
    json.dump([{"address": cs[2]["a"], "priceUsd": None, "liquidityUsd": None}, {"address": cs[3]["a"], "priceUsd": 0.001, "liquidityUsd": 3000.0},
               {"address": cs[4]["a"], "priceUsd": 0.001, "liquidityUsd": 30000.0}, {"address": cs[6]["a"], "priceUsd": 0.002, "liquidityUsd": 30000.0, "px_only": True}],
              open(os.path.join(dk, "pairs.json"), "w"))
    pid_ = rid(T0 - H)
    p58, p47 = {"t": T0 - H + 58 * 60_000, "px": 9}, {"t": T0 - H + 47 * 60_000, "px": 8}     # already priced 58 and 47 minutes after it was seen
    json.dump({"v": 1, "t": T0 - H, "id": pid_, "coins": [{"addr": cs[0]["a"], "p60": None}, {"addr": cs[1]["a"], "p60": None}, {"addr": cs[2]["a"], "p60": p58},
                                                         {"addr": cs[3]["a"], "p60": p47}]},
              open(os.path.join(dk, "db", "memeearly", pid_ + ".json"), "w"))
    json.dump({"id": pid_, "t": T0 - H, "at": T0 + 260000, "coins": {cs[0]["a"]: {"px": 0.5, "liq": 9000.0}, cs[1]["a"]: {"gone": True}, cs[2]["a"]: {"px": 1.0, "liq": 1.0},
                                                                      cs[3]["a"]: {"px": 2.0, "liq": 2.0}}},
              open(os.path.join(dk, "radar", "prev.json"), "w"))
    urlm = "http://127.0.0.1:%d" % rsrv.server_address[1]
    rmock.by_a[cs[4]["a"]]["gone"] = True
    n0 = len(rmock.log)
    pk = subprocess.run([PY, os.path.join(HERE, "radar.py"), "check", "--dir", dk, "--now", str(T0), "--t0", str(int(time.time() * 1000)), "--horizon", "2h", "--mock", urlm],
                        capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rmock.by_a[cs[4]["a"]]["gone"] = False
    reqs = rmock.log[n0:]
    me = json.load(open(os.path.join(dk, "db", "memeearly", rid(T0) + ".json"), encoding="utf-8")) if os.path.exists(os.path.join(dk, "db", "memeearly", rid(T0) + ".json")) else {}
    mc_ = {c["addr"]: c for c in me.get("coins") or []}
    pv = {c["addr"]: c for c in json.load(open(os.path.join(dk, "db", "memeearly", pid_ + ".json"), encoding="utf-8"))["coins"]}
    check(pk.returncode == 0 and len(reqs) == 1 and "/tokens/v1/" in reqs[0] and me.get("id") == rid(T0) and mc_[cs[0]["a"]]["final"] == 1 and mc_[cs[0]["a"]]["bought"] == 3.0
          and mc_[cs[0]["a"]]["out"] is None and mc_[cs[1]["a"]]["out"] == "born after the scan started" and mc_[cs[2]["a"]]["out"] == "no price at the trader step"
          and mc_[cs[3]["a"]]["out"] == "liquidity under $5k at the trader step" and mc_[cs[4]["a"]]["out"].startswith("not on the scored list")
          and mc_[cs[6]["a"]]["out"] == "no price at the trader step"
          and abs(mc_[cs[0]["a"]]["p2"]["px"] - float("%.10f" % cs[0]["px"])) < 1e-15 and mc_[cs[4]["a"]]["p2"].get("gone") is True and me.get("finalOnly") == [cs[5]["a"]] and mc_[cs[0]["a"]]["rc"] == "warn"
          and pv[cs[0]["a"]]["p60"] == {"px": 0.5, "liq": 9000.0, "t": T0 + 260000} and pv[cs[1]["a"]]["p60"] == {"gone": True, "t": T0 + 260000} and pv[cs[2]["a"]]["p60"] == p58
          and pv[cs[3]["a"]]["p60"] == {"px": 2.0, "liq": 2.0, "t": T0 + 260000},
          "radar.py check: one DexScreener request prices the list again (p2, a gone coin counts), the scored list's place and buy, the reason a coin is not on it"
          " (a price-only row is no price), the coins it missed, and the previous record's price an hour later (p60: one 58 minutes after stays, one 47 minutes"
          " after gives way to this one at 64)")
    # the same check again with a scored list of another scan and a DexScreener that answers 500: no place, no buy, no p2 (unknown, not gone), one request
    json.dump({"t": T0 - 1, "young": [{"addr": cs[0]["a"], "bought": 3.0}, {"addr": cs[5]["a"], "bought": "held"}]}, open(os.path.join(dk, "db", "memebot", "recommend.json"), "w"))
    rmock.hook = lambda path: (500, {"error": "boom"}) if "/tokens/v1/" in path else None
    n0 = len(rmock.log)
    pk2 = subprocess.run([PY, os.path.join(HERE, "radar.py"), "check", "--dir", dk, "--now", str(T0), "--t0", str(int(time.time() * 1000)), "--horizon", "2h", "--mock", urlm],
                         capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rmock.hook = None
    me2 = json.load(open(os.path.join(dk, "db", "memeearly", rid(T0) + ".json"), encoding="utf-8"))
    check(pk2.returncode == 0 and len(rmock.log) - n0 == 1 and all(c["final"] is None and c["bought"] is None and c["p2"] is None for c in me2["coins"]) and me2.get("finalOnly") == []
          and len(me2["coins"]) == 6,
          "a recommend.json of another scan is not this list's fate, and a check whose one DexScreener request fails records no p2 (not gone), with no second try")
    # radar.py check makes exactly one try: a DexScreener that drops the connection without an answer (the kind of failure the early step tries twice)
    drops = []

    class Drop(BaseHTTPRequestHandler):
        def do_GET(self):
            drops.append(self.path)
            self.close_connection = True          # no status line at all: the client sees the connection closed

        def log_message(self, *a):
            pass
    dsrv = HTTPServer(("127.0.0.1", 0), Drop)
    threading.Thread(target=dsrv.serve_forever, daemon=True).start()
    t_ = time.time()
    pk3 = subprocess.run([PY, os.path.join(HERE, "radar.py"), "check", "--dir", dk, "--now", str(T0), "--t0", str(int(time.time() * 1000)), "--horizon", "2h",
                          "--mock", "http://127.0.0.1:%d" % dsrv.server_address[1]], capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, MEMEBOT_PAUSE="0"))
    secs_ = time.time() - t_
    dsrv.shutdown()
    dsrv.server_close()
    me3 = json.load(open(os.path.join(dk, "db", "memeearly", rid(T0) + ".json"), encoding="utf-8"))
    rsrc = open(os.path.join(HERE, "radar.py"), encoding="utf-8").read()
    check(pk3.returncode == 0 and len(drops) == 1 and "/tokens/v1/" in drops[0] and all(c["p2"] is None for c in me3["coins"]) and secs_ < 15
          and "http = setup(horizon, mock, tries=1)" in rsrc,
          "radar.py check itself makes exactly one try: a DexScreener that gives no answer is asked once (%d request%s, %.1f s) and no coin gets a price or 'gone'" % (
              len(drops), "" if len(drops) == 1 else "s", secs_))
    # which earlier record gets its hour price: 45 to 90 minutes old, the one closest to an hour
    pdd = os.path.join(tmp, "prevdoc")
    os.makedirs(os.path.join(pdd, "db", "memeearly"))

    def put(mins):
        t_ = T0 - mins * 60_000
        json.dump({"v": 1, "t": t_, "id": rid(t_), "coins": []}, open(os.path.join(pdd, "db", "memeearly", rid(t_) + ".json"), "w"))
        return t_
    pick_t = lambda: (RD.prev_doc(pdd, T0) or {}).get("t")
    put(30)
    r30 = pick_t()
    put(95)
    r95 = pick_t()
    t50 = put(50)
    r50 = pick_t()
    t62 = put(62)
    r62 = pick_t()
    check(r30 is None and r95 is None and r50 == t50 and r62 == t62,
          "the previous list priced for its hour price is 45 to 90 minutes old (one of 30 or 95 minutes is not), the one closest to an hour (62 over 50)")
    me_c = json.load(open(glob.glob(os.path.join(dc, "db", "memeearly", "*.json"))[0], encoding="utf-8"))
    rec_c = json.load(open(os.path.join(dc, "db", "memebot", "recommend.json"), encoding="utf-8"))
    yaddr = [y["addr"] for y in rec_c.get("young") or []]
    m_s, m_r = re.search(r"^saved \d+ docs", pc.stderr, re.M), re.search(r"^spotter: record ", pc.stderr, re.M)
    gi = (m_s.start() if m_s else -1, m_r.start() if m_r else -1)
    check(me_c.get("id") == rid(T0) and all((c["final"] is None) == (c["addr"] not in yaddr) for c in me_c["coins"]) and all(yaddr[c["final"] - 1] == c["addr"] and c["bought"] == rec_c["young"][c["final"] - 1].get("bought")
                                                                                                                    for c in me_c["coins"] if c["final"])
          and 0 < gi[0] < gi[1] and "!db/memeearly/**" in B.SYNC_IGNORE,
          "in a real cycle the record is written after the trader's docs are saved, with each coin's place on the scored list and its buy; it travels with the results")
    pd = os.path.join(tmp, "prune")
    os.makedirs(os.path.join(pd, "db", "memeearly"))
    for n, age in (("old", 31), ("new", 29)):
        json.dump({"t": T0 - age * 86_400_000}, open(os.path.join(pd, "db", "memeearly", n + ".json"), "w"))
    with contextlib.redirect_stderr(io.StringIO()):
        B.prune(pd, T0)
    gi_ = subprocess.run(["git", "init", "-q", os.path.join(pd, "g")], capture_output=True)
    open(os.path.join(pd, "g", ".gitignore"), "w").write(B.SYNC_IGNORE)
    ign = subprocess.run(["git", "-C", os.path.join(pd, "g"), "check-ignore", "-q", "db/memeearly/2026-10-10T1612.json"]).returncode
    check(sorted(os.listdir(os.path.join(pd, "db", "memeearly"))) == ["new.json"] and ign == 1, "the early-list record is pruned after 30 days and synced to the results branch")

    print("== launch spotter 13: the spotter scores with the last trader's weights")
    sp = json.load(open(os.path.join(dc, "db", "memebot", "spotter.json"), encoding="utf-8"))
    with profile("2h"):
        bw, _ = M.blended_weights(dc)
        w_same, f1 = RD.weights(dc, "2h")
        os.rename(os.path.join(dc, "db", "memebot", "spotter.json"), os.path.join(tmp, "spotter.json"))
        w_none, f2 = RD.weights(dc, "2h")
        json.dump(dict(sp, rule="m9"), open(os.path.join(dc, "db", "memebot", "spotter.json"), "w"))
        w_rule, f3 = RD.weights(dc, "2h")
        prior = dict(M.PRIOR)
        w_x = {k: round(float(v) * 2 + 1, 4) for k, v in prior.items()}        # weights nobody would mistake for the prior
        json.dump({"t": T0, "rule": M.RULE, "horizon": "2h", "w": w_x}, open(os.path.join(dc, "db", "memebot", "spotter.json"), "w"))
        w_xs, fx1 = RD.weights(dc, "2h")
        json.dump({"t": T0, "rule": M.RULE, "horizon": "24h", "w": w_x}, open(os.path.join(dc, "db", "memebot", "spotter.json"), "w"))
        w_xh, _ = RD.weights(dc, "2h")
        json.dump({"t": T0, "rule": "m0-other", "horizon": "2h", "w": w_x}, open(os.path.join(dc, "db", "memebot", "spotter.json"), "w"))
        w_xr, _ = RD.weights(dc, "2h")
    check(sp.get("t") == T0 and sp.get("rule") == "m9-2h" and sp.get("horizon") == "2h" and sp.get("w") == bw and w_same == bw and w_none == prior and w_rule == prior and "last scan" in f1,
          "db/memebot/spotter.json holds the trader's weights (%d factors); without it, or for another rule, the spotter scores with the prior" % len(sp.get("w") or {}))
    check(w_x != prior and w_xs == w_x and "last scan" in fx1 and w_xh == prior and w_xr == prior,
          "weights unlike the prior in spotter.json are the ones the spotter scores with; of another profile or another rule they are not used")

    print("== launch spotter 14: the New launches tab (page, script, browser)")
    out_live, out_plain = os.path.join(tmp, "live.html"), os.path.join(tmp, "plain.html")
    subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", dc, "--out", out_live, "--now", str(T0)], capture_output=True, env=dict(os.environ, GITHUB_REPOSITORY="Some-Owner/Meme-Bot"))
    subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", dc, "--out", out_plain, "--now", str(T0)], capture_output=True)
    pl, pp = open(out_live, encoding="utf-8").read(), open(out_plain, encoding="utf-8").read()
    bare = re.sub(r'<script>\s*\(function\(\)\{\s*var MB=window\.MemebotLive=.*?</script>', "", re.sub(
        r'<p class="note olink" data-lv data-live-link>.*?</p><div class="olive".*?<p class="note" data-lv data-live-off hidden></p></div>', "", pl, flags=re.S), flags=re.S)
    bare = re.sub(r'<p class="note ehint">.*?</p>|<details class="early" data-early.*?</details>', "", bare.replace(R.EARLY_CSS, "", 1), flags=re.S)   # the hint (behind the tab's ⓘ) and the early box
    box = re.search(r'<details class="early" data-early[^>]*>', pl)
    ed_doc = json.loads(html.unescape(re.search(r'data-early-doc="([^"]*)"', box.group(0)).group(1))) if box and "data-early-doc" in box.group(0) else {}
    fin = json.loads(html.unescape(re.search(r'data-final="([^"]*)"', box.group(0)).group(1))) if box and "data-final" in box.group(0) else {}
    check(bare == pp and "data-early" not in pp and "ehint" not in pp and ".ecard" not in pp and "During each scan, the coins it finds under an hour old appear here about 5 minutes after it starts" in pl
          and box and " hidden" in box.group(0) and ed_doc.get("t") == T0 and ed_doc.get("state") == "listed" and fin.get("t") == T0
          and all(fin["coins"][a]["k"] == i for i, a in enumerate(yaddr, 1)) and R.EARLY_LABEL in html.unescape(pl) and "jup.ag" not in box.group(0)
          and 'data-agents="scouts deep spotter"' in pl and "Launch spotter" in pl,
          "without GITHUB_REPOSITORY the page is as before; with it the New launches tab has the hint, the hidden early box with this scan's list and each coin's"
          " place on the scored list, and the office has the Launch spotter's desk")
    js = R.OFFICE_LIVE_JS
    node = shutil.which("node")
    if node:
        jd = tempfile.mkdtemp(prefix="memebot-js-")
        with open(os.path.join(jd, "t.js"), "w", encoding="utf-8") as f:
            f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;}};\n" + js + r"""
var MB=window.MemebotLive,M=60000,h=3600000,s=Date.UTC(2026,9,10,16,10,0),now=s+20*M,pageT=s-60*M,o={};
function Y(t,st,x){var y={v:1,t:t,at:t+5*M,state:st,rcState:'done',partial:false,coins:st==='listed'?[{addr:'A',born:t}]:[]};for(var k in x||{})y[k]=x[k];return y;}
function L(t,live,age,y,ags){var d={t:t,live:live,updated:now-age,agents:ags||[{id:'dispatch',status:'done'},{id:'market',status:'running'}]};if(y)d.young=y;return d;}
var t=s+2*M,rep=[{id:'trader',status:'done'},{id:'reporter',status:'done'}],e=MB.early;
o.s=[e(null,now,pageT,0,null,0,0,null,0),                                  // hide: nothing at all
 e(L(t,true,20000),now,pageT,0,null,0,s,null,now),                           // wait
 e(null,now,pageT,0,null,0,s,null,0),                                        // late: no doc of this hour 20 minutes after the start
 e(L(t,true,20000,Y(t,'listed')),now,pageT,0,null,0,s,null,now),             // listed
 e(L(t,true,20000,Y(t,'listed',{partial:true})),now,pageT,0,null,0,s,null,now),   // partial
 e(L(t,true,6*M,Y(t,'listed')),now,pageT,0,null,0,s,null,now),               // paused: no update for 6 minutes
 e(L(t,true,20000,Y(t,'listed')),now,pageT,2,null,0,s,null,now),             // paused: two failed polls
 e(L(t,true,6*M,Y(t,'listed')),now,pageT,0,0,0,s,null,now),                  // limited: none left and nothing fresh
 e(L(t,false,60000,Y(t,'listed'),rep),now,pageT,0,null,0,s,null,now),        // done
 e(L(t,false,60000,Y(t,'listed'),[{id:'trader',status:'failed'}]),now,pageT,0,null,0,s,null,now),   // stopped
 e(null,now,t,0,null,0,s,Y(t,'listed'),0),                                   // own: this page's scan, from the page
 e(L(t,true,20000,Y(t,'empty')),now,pageT,0,null,0,s,null,now),              // empty
 e(L(t,true,20000,Y(t,'failed',{why:'x'})),now,pageT,0,null,0,s,null,now),   // none
 e(L(t,true,20000,Y(t,'off')),now,pageT,0,null,0,s,null,now),                // none (off)
 e(L(t,true,20000,Y(t,'listed',{at:t-80*M})),now,pageT,0,null,0,s,null,now), // hide: the list is over 75 minutes old
 e(L(t,true,20000,Y(t+1,'listed')),now,pageT,0,null,0,s,null,now),           // wait: a list of another scan is not this one's
 e(L(t,false,60000,Y(t,'listed'),rep.concat([{id:'spotter',status:'failed'}])),now,pageT,0,null,0,s,null,now),   // done: a failed spotter is not a failed scan
 e(L(t,true,20000,Y(t,'listed')),now,pageT,0,0,0,s,null,now),               // listed: fresh data shows even with no requests left
 e(L(pageT,false,60000,Y(pageT,'listed'),rep),now,pageT,0,null,0,s,null,now)];   // own: the page's own scan in the last snapshot
// a phone clock 10 minutes fast (F) or slow (Sl): got is when the snapshot's "updated" was first seen, moved whether it replaced an older one
var D=L(t,true,20000,Y(t,'listed')),D7=L(t,true,7*M,Y(t,'listed')),F=now+10*M,Sl=now-10*M;
o.age=[MB.age(D,now)/1000,MB.age(D,F,F,false)/1000,MB.age(D,F,F,true)/1000,MB.age(D7,Sl,Sl,false)/1000,MB.age(D7,Sl+5*M,Sl,false)/1000];
o.skew=[e(D,F,pageT,0,null,0,s,null,F,false),e(D,F,pageT,0,null,0,s,null,F,true),e(D7,Sl,pageT,0,null,0,s,null,Sl,false),e(D7,Sl+5*M,pageT,0,null,0,s,null,Sl,false),
  MB.state(D,F,pageT,0,F,true),MB.state(D,F,pageT,0)];
o.office=MB.state(L(t,false,0,null,rep.concat([{id:'spotter',status:'failed'}])),now,pageT,0);
var r1={level:'clean'},r2={level:'none',text:'RugCheck did not answer'};
o.rc=[MB.rcChip(null,'pending'),MB.rcChip(null,'partial'),MB.rcChip(null,'done'),MB.rcChip(r1,'partial'),MB.rcChip(r2,'down'),MB.rcChip({level:'none'},'done'),
  MB.rcSum({rcState:'pending'},[{}]),MB.rcSum({rcState:'partial',rcWhy:'RugCheck did not finish: x'},[{rc:null},{rc:null}]),MB.rcSum({rcState:'partial'},[{rc:r1},{rc:null}]),
  MB.rcSum({rcState:'partial'},[{rc:r1},{rc:r2}]),MB.rcSum({rcState:'down'},[{rc:r2}]),MB.rcSum({rcState:'done'},[{rc:r1},{rc:{level:'none'}}])];
function nx(doc,tt,rem,reset,fails){return Math.round((MB.next(doc,tt,s,rem,reset,fails)-tt)/1000);}
var old=L(s-60*M,false,0,null,rep),fin=L(s+M,false,0,null,rep);
o.n=[nx(old,s-3*M,null,0,0),nx(old,s-M,null,0,0),nx(old,s+3*M,null,0,0),nx(old,s+34*M,null,0,0),nx(old,s+36*M,null,0,0),nx(fin,s+26*M,null,0,0),nx(old,s+3*M,15,(s+23*M)/1000,0),nx(old,s+3*M,null,0,1)];
console.log(JSON.stringify(o));
""")
        r_ = subprocess.run([node, os.path.join(jd, "t.js")], capture_output=True, text=True)
        shutil.rmtree(jd, ignore_errors=True)
        try:
            o = json.loads(r_.stdout)
        except ValueError:
            o = {"err": r_.stderr[-400:]}
        check(o.get("s") == ["hide", "wait", "late", "listed", "partial", "paused", "paused", "limited", "done", "stopped", "own", "empty", "none", "none", "hide", "wait", "done", "listed", "own"]
              and o.get("office") == "done",
              "the early box's states (node): hide, wait, late, listed, partial, paused, limited, done, stopped, own, empty, none; a failed spotter never makes a scan look stopped %s" % (o.get("s") or o))
        check(o.get("rc") == ["RugCheck: checking\u2026", "RugCheck did not finish", "RugCheck did not finish", "RugCheck: no danger flags", "RugCheck did not answer",
                              "no RugCheck report", " \u00b7 RugCheck checking\u2026", " \u00b7 RugCheck did not finish", " \u00b7 RugCheck did not finish (reports for 1 of 2)",
                              " \u00b7 RugCheck reports for 1 of 2", " \u00b7 RugCheck did not answer", " \u00b7 RugCheck reports for 1 of 2"],
              "the early box's RugCheck words (node): 'checking' only while the spotter asks; a list whose spotter was stopped says RugCheck did not finish, on the cards"
              " and in the status line %s" % (o.get("rc") or o))
        check(o.get("age") == [20, 620, 120, 0, 300] and o.get("skew") == ["paused", "listed", "listed", "paused", "live", "paused"],
              "a snapshot's age (node): once its 'updated' has moved, the local time since plus at most 2 minutes, so a phone 10 minutes fast reads live;"
              " before that the phone's clock is the first guess, and a phone 10 minutes slow reads a 7-minute-old snapshot as fresh for 5 minutes at most %s %s" % (
                  o.get("age"), o.get("skew")))
        check(o.get("n") == [60, 75, 75, 60, 540, 540, 240, 150],
              "the poll plan in the scan window (node): 75 s from 2 minutes before a scheduled start to 35 after it until that scan's last snapshot, the grid outside it,"
              " stretched by GitHub's remaining requests, longer after a failed poll %s" % (o.get("n") or o))
    else:
        check("early:function(doc,now,pageT,fails,rem,reset,scan,own,got,moved)" in js and "MB.WIN[1]*60000" in js, "the early box's states and the scan window are in the script (node not found)")
    check("innerHTML" not in js and "insertAdjacentHTML" not in js and "jup.ag" not in js and "B58.test(a)" in js and "rel='noopener noreferrer'" in js,
          "the script builds the cards with createElement and textContent only, links only around a checked address, never a swap link")
    check("if(!(same&&+o.updated===+d.updated)||!S.got)" in js and "Math.floor(n/15000)" not in js and "eages(li,li._c,y,ref)" in js and "history.replaceState(" in js
          and "shows it below this list" in js and "goes above this list" not in js and "fate[a].b==='held'" in js and "RugCheck reports for " in js
          and "the launch spotter found" in js and "' at '+hhmm(+y.at)" in js and "min-width:44px" in R.EARLY_CSS and "details.early.dim .ecard.old { opacity:1 }" in R.EARLY_CSS
          and "details.early.nolist .estatus::before { display:none }" in R.EARLY_CSS,
          "the script keeps the time a snapshot was first seen, moves the ages without rebuilding the cards, uses #new once, says the scored list comes below,"
          " says 'already held' once, and the CSS gives the link chips 44 px of width and never dims a card twice")
    browser_checks(check, pl, tmp)
    rsrv.shutdown()
    rsrv.server_close()
    shutil.rmtree(tmp, ignore_errors=True)


def browser_checks(check, page_html, tmp):
    """The early box in Chromium (when Playwright and a Chromium are installed): the page is served at its website address from memory, the GitHub API
    is stubbed, every other request is refused."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        SKIPS.append("the browser checks of the early list (no Playwright)")
        print("  SKIP the browser checks of the early list: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    pages_url, rng = "https://some-owner.github.io/Meme-Bot/", random.Random(3)
    ms = lambda: int(time.time() * 1000)
    now = ms()
    t, prev = now - 6 * 60_000, now - 66 * 60_000
    own_html = re.sub(r'data-run-t="\d+"', 'data-run-t="%d"' % T0, page_html)          # the page of the scan whose early list it carries
    page_html = re.sub(r'data-run-t="\d+"', 'data-run-t="%d"' % prev, page_html)
    win_html = re.sub(r'data-next-scan="\d+"', 'data-next-scan="%d"' % t, page_html)   # a page whose next scheduled scan is the one running now
    adds = [b58(rng) for _ in range(5)]
    born = lambda m: now - 20_000 - m * 60_000 - 30_000        # half a minute into a minute: the ages read the same for a few seconds
    coins = [{"addr": adds[0], "sym": "<script>alert(2)</script>", "name": "<img src=x onerror=alert(1)>", "pair": "javascript:alert(3)", "x": "javascript:alert(4)", "born": born(7),
              "ageMin": 7, "liq": 12400.0, "mc": 48100.0, "k": 2, "rc": {"level": "danger", "text": "RugCheck danger: Large Amount of LP Unlocked"}},
             {"addr": "0xNOT<b>SOLANA", "sym": "BADADDR", "born": born(9), "ageMin": 9, "k": 1, "rc": None},
             {"addr": adds[1], "sym": "GOOD", "name": "Good", "born": born(3), "ageMin": 3, "k": 3, "x": "https://x.com/good", "rc": {"level": "clean", "text": "RugCheck: no danger flags"}}]
    young = {"v": 1, "t": t, "at": t + 276_000, "state": "listed", "rcState": "done", "partial": False, "minLiq": 5000, "coins": coins}
    doc = {"v": 1, "t": t, "live": True, "updated": now - 20_000, "agents": [{"id": "dispatch", "status": "done"}, {"id": "market", "status": "running"}], "young": young}
    stale = dict(doc, updated=now - 7 * 60_000, young=dict(young, coins=coins[:1] + [dict(coins[2], addr=adds[2], sym="OLD", born=now - 7 * 60_000 - 70 * 60_000, ageMin=70)]))
    calls, dialogs, errs = [], [], []
    plain = lambda: (200, doc)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def ctx_page(w=390, skew=0, hash_="#new", html_=None, answer=plain, init=""):
                ctx = br.new_context(viewport={"width": w, "height": 900})
                ctx.add_init_script("(function(){var r=Date.now.bind(Date);window.__skew=%d;Date.now=function(){return r()+window.__skew;};})();%s" % (skew, init))

                def handler(route):
                    u = route.request.url
                    if u.startswith(pages_url):
                        route.fulfill(status=200, body=html_ or page_html, headers={"Content-Type": "text/html; charset=utf-8"})
                    elif u.startswith("https://api.github.com/"):
                        calls.append(u)
                        code_, body_ = answer()
                        route.fulfill(status=code_, body=json.dumps(body_), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
                    else:
                        route.abort()
                ctx.route("**/*", handler)
                pg = ctx.new_page()
                pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
                pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
                pg.goto(pages_url + hash_)
                return ctx, pg

            def status(pg):
                return pg.evaluate("(document.querySelector('[data-early-status]')||{}).textContent||''")

            def wait_status(pg, text, ms_=8000):
                try:
                    pg.wait_for_function("t => ((document.querySelector('[data-early-status]')||{}).textContent||'').indexOf(t) >= 0", arg=text, timeout=ms_)
                    return True
                except Exception:
                    return False
            age_js = "() => Array.from(document.querySelectorAll('[data-early-list] .ehd')).map(e => e.textContent)"
            ctx, pg = ctx_page()
            pg.wait_for_function("document.querySelectorAll('[data-early-list] > li').length === 3", timeout=10000)
            info = pg.evaluate("""() => { const box = document.querySelector('[data-early]'), vis = e => !!e.getClientRects().length, r = e => e.getBoundingClientRect();
              return { young: document.getElementById('tab-young').checked, imgs: box.querySelectorAll('img,script').length, text: box.textContent, hash: location.hash,
                hscroll: document.documentElement.scrollWidth - innerWidth, links: Array.from(box.querySelectorAll('a')).map(a => [a.getAttribute('href'), a.rel, a.target]),
                cardLinks: Object.fromEntries(Array.from(box.querySelectorAll('[data-early-list] > li')).map(li => [li.querySelector('.es').textContent, li.querySelectorAll('a').length])),
                minLink: Math.min(...Array.from(box.querySelectorAll('.lchip')).filter(vis).map(e => r(e).height)), minLinkW: Math.min(...Array.from(box.querySelectorAll('.lchip')).filter(vis).map(e => r(e).width)),
                minPill: Math.min(...Array.from(box.querySelectorAll('.eorder label')).filter(vis).map(e => r(e).height)),
                status: box.querySelector('[data-early-status]').textContent }; }""")
            a1 = pg.evaluate(age_js)
            # a selection in a card and the focus on a link survive the redraws: the ages change in place, the cards are not rebuilt
            pg.evaluate("""() => { const li = document.querySelector('[data-early-list] > li'), r = document.createRange(); window.__li = li;
              r.selectNodeContents(li.querySelector('.es')); getSelection().removeAllRanges(); getSelection().addRange(r); li.querySelector('.lchip').focus(); }""")
            sel0 = pg.evaluate("getSelection().toString()")
            pg.evaluate("window.__skew += 16000")
            pg.wait_for_timeout(1500)
            kept = pg.evaluate("[document.querySelector('[data-early-list] > li') === window.__li, getSelection().toString(), !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('li') === window.__li)]")
            n0 = len(calls)
            pg.evaluate("window.__skew += 180000")      # three minutes of local time pass, and the next poll brings the same snapshot again
            for _ in range(40):
                if len(calls) > n0:
                    break
                pg.wait_for_timeout(150)
            pg.wait_for_timeout(1300)
            a2, polled = pg.evaluate(age_js), len(calls) > n0
            ctx.close()
            ctx, pg = ctx_page(skew=-600_000)            # a phone clock 10 minutes behind
            pg.wait_for_function("document.querySelectorAll('[data-early-list] > li').length === 3", timeout=10000)
            a3 = pg.evaluate(age_js)
            ctx.close()
            n_calls = {}
            for tab in ("tab-pick", "tab-young", "tab-office"):
                calls.clear()
                ctx, pg = ctx_page(hash_="")
                if tab != "tab-pick":
                    pg.click('label[for="%s"]' % tab)
                pg.wait_for_timeout(1500)
                n_calls[tab] = len(calls)
                ctx.close()
            # #new opens the tab once: the reader moves to the office and reloads, the office stays open
            ctx, pg = ctx_page()
            pg.wait_for_timeout(300)
            hash_after = pg.evaluate("location.hash")
            pg.click('label[for="tab-office"]')
            pg.reload()
            pg.wait_for_timeout(500)
            tab_after = pg.evaluate("[document.getElementById('tab-office').checked, document.getElementById('tab-young').checked]")
            ctx.close()
            # a phone 10 minutes fast during a scan that pushes: paused at first sight at most, live once "updated" has moved
            bump = lambda: (200, dict(doc, updated=ms() - 5000))
            ctx, pg = ctx_page(skew=600_000, html_=win_html, answer=bump, init="window.MEMEBOT_LIVE_T={LIVE:1500};")
            fast_ok = wait_status(pg, "Found at", 9000)
            fast = [status(pg), pg.evaluate("document.querySelector('[data-early]').classList.contains('dim')")]
            ctx.close()
            # a phone 10 minutes slow and a snapshot 7 minutes old that never moves: fresh at first sight, paused after 5 minutes of local time
            ctx, pg = ctx_page(skew=-600_000, answer=lambda: (200, stale))
            slow0 = wait_status(pg, "Found at", 8000) and status(pg)
            pg.evaluate("window.__skew += 302000")
            slow_ok = wait_status(pg, "Live view paused", 5000)
            dimmed = pg.evaluate("""() => { const op = e => { let o = 1; for (; e; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
              return [document.querySelector('[data-early]').classList.contains('dim'), Array.from(document.querySelectorAll('[data-early-list] > li')).map(li => [li.classList.contains('old'), op(li)])]; }""")
            ctx.close()
            # a scan that has not listed yet: the box has nothing to fold
            ctx, pg = ctx_page(answer=lambda: (200, dict(doc, young=None)))
            wait_status(pg, "Scan running since", 8000)
            nl = pg.evaluate("""() => { const b = document.querySelector('[data-early]'), o = b.open; b.querySelector('summary').click();
              return [b.classList.contains('nolist'), o === b.open, getComputedStyle(b.querySelector('.estatus'), '::before').display]; }""")
            ctx.close()
            # the page's own list after its scan: no newer snapshot, the label and the ages are of the time the list was made
            ctx, pg = ctx_page(html_=own_html, answer=lambda: (404, {"message": "Not Found"}))
            own_ok = wait_status(pg, "Early list of this scan", 8000)
            own = pg.evaluate("""() => [(document.querySelector('[data-early-label]')||{}).textContent||'', Array.from(document.querySelectorAll('[data-early-list] .ehd .chip')).map(e => e.textContent)]""")
            ctx.close()
            # a launchpad and a DEX name of 24 characters (they come from the sources) on a 12-day-old token at 320 px: the line breaks, nothing sticks out
            wide = dict(doc, young=dict(young, coins=[dict(coins[2], launchpad="Raydium LaunchLab Extras", dex="pumpswap-amm-v2-extended", minted=now - 12 * 86_400_000 - 3_600_000),
                                                      dict(coins[0], launchpad="W" * 24, dex="D" * 24, minted=now - 30 * 86_400_000)]))
            ctx, pg = ctx_page(w=320, answer=lambda: (200, wide))
            pg.wait_for_function("document.querySelectorAll('[data-early-list] > li').length === 2", timeout=10000)
            narrow = pg.evaluate("""() => { const box = document.querySelector('[data-early]'), r = e => e.getBoundingClientRect(), bx = r(box);
              return { hscroll: document.documentElement.scrollWidth - innerWidth, out: Array.from(box.querySelectorAll('[data-early-list] *')).filter(e => r(e).right > bx.right + 0.5).map(e => e.className || e.tagName),
                tok: Array.from(box.querySelectorAll('.eline')).map(e => e.textContent).filter(t => t.indexOf('token') === 0) }; }""")
            ctx.close()
            br.close()
    except Exception as e:
        check(False, "the browser checks of the early list could not run (Playwright is installed; Chromium needs a short TMPDIR path): %s" % str(e)[:200])
        return
    links = info["links"]
    ok = (info["young"] and info["imgs"] == 0 and "<img src=x onerror=alert(1)>" in info["text"] and "<script>alert(2)</scr" in info["text"] and not dialogs
          and info["cardLinks"].get("BADADDR") == 0 and info["cardLinks"].get("GOOD") == 7 and all(u.startswith("https://") and rel == "noopener noreferrer" and tg == "_blank" for u, rel, tg in links)
          and not any("jup.ag" in u or "javascript" in u for u, _, _ in links) and any(u == "https://x.com/good" for u, _, _ in links)
          and any(u == "https://dexscreener.com/solana/" + adds[0] for u, _, _ in links) and "RugCheck reports for 2 of 3" in info["status"])
    check(ok, "browser: #new opens the tab; a coin named <img src=x onerror=alert(1)> renders as text, a bad address gets no link, a javascript: link is dropped, no swap link%s" % ("" if ok else " %s %s" % (dialogs, json.dumps(info)[:600])))
    check(info["hscroll"] <= 0 and info["minLink"] >= 44 and info["minLinkW"] >= 44 and info["minPill"] >= 44,
          "browser at 390 px: no sideways scroll, link chips at least 44 px tall and wide (the X chip too), order pills 44 px tall (%.0f, %.0f, %.0f)" % (info["minLink"], info["minLinkW"], info["minPill"]))
    num_age = lambda xs: [int(m) for m in re.findall(r"pair (\d+) min old", " ".join(xs))]
    check(len(num_age(a1)) == 3 and polled and num_age(a2) == [x + 3 for x in num_age(a1)] and num_age(a3) == num_age(a1),
          "browser: the ages count on with local time across a poll that brings the same snapshot (%s, then %s three minutes later) and ignore a phone clock"
          " 10 minutes off (%s)" % (num_age(a1), num_age(a2), num_age(a3)))
    check(sel0 and kept == [True, sel0, True], "browser: a selected symbol and the focused link survive the redraws (the cards are not rebuilt every 15 s: %s)" % kept)
    check(n_calls["tab-pick"] == 0 and n_calls["tab-young"] >= 1 and n_calls["tab-office"] >= 1 and hash_after == "" and tab_after == [True, False],
          "browser: the page polls on the New launches and Agent office tabs, not on Pick (%s); #new is used once, a reload keeps the tab chosen" % n_calls)
    check(fast_ok and not fast[1] and slow0 and "updated" in slow0 and slow_ok and dimmed[0] and all(o >= 0.79 for _, o in dimmed[1]) and any(old for old, _ in dimmed[1]),
          "browser: a phone 10 minutes fast reads a pushing scan as live (%s); one 10 minutes slow reads a stalled one as paused after 5 minutes; a dimmed list"
          " never dims an old card twice (opacities %s)" % (fast[0][:60], [round(o, 2) for _, o in dimmed[1]]))
    check(nl[0] and nl[1] and nl[2] == "none", "browser: before the list comes the box has no fold arrow and a tap folds nothing (%s)" % nl)
    check(own_ok and own[0].startswith("Fake money · not advice. This was the list before scoring") and "below" in own[0]
          and any(re.search(r"min old at \d\d:\d\d", x) for x in own[1]) and not errs,
          "browser: after its scan the page's own list says it was the list before scoring and gives the ages at the time it was made (%s) %s" % (own[1][:2], errs[:2]))
    check(narrow["hscroll"] <= 0 and not narrow["out"] and len(narrow["tok"]) == 2 and narrow["tok"][0].startswith("token 12 days old (Raydium LaunchLab Extras) · pumpswap-amm-v2-extended"),
          "browser at 320 px: a 24-character launchpad and DEX name on a token 12 days old break inside the card, the page never widens (%s%s)" % (
              narrow["tok"][:1], " out: %s" % narrow["out"][:4] if narrow["out"] else ""))


# ------------------------------------------------------------------------------------------------ the iPhone app (app.py, sw.js, the page)

APP_SECRET = "sb_secret_TESTsecretKEY_0123456789abcdef"     # the test's secret key: it must never show in any output, file or page


class Rest:
    """A local stand-in for Supabase's REST API (PostgREST) with the tables of supabase/setup.sql: it checks the secret key in the apikey
    header, notes every request and can play a paused project (HTTP 540), an error that echoes the key, one that echoes what was sent to
    app_secret (echobody), a slow store (slow<s>: every answer s seconds late; slowpost<s>: only the writes) or a redirect to another
    address (redirect:<url>)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.live, self.secret, self.config, self.subs, self.log = {}, {}, {}, {}, []
        self.mode, self.old_subs = "ok", False         # old_subs: a table from before the delivered and fails columns

    def handle(self, method, path, query, headers, body):
        q = urllib.parse.parse_qs(query)
        eq = lambda k: (q.get(k) or [""])[0][3:] if (q.get(k) or [""])[0].startswith("eq.") else None

        def ins(k):
            """PostgREST's in.("a","b") with quoted values (backslash escapes), or None."""
            v = (q.get(k) or [""])[0]
            if not (v.startswith("in.(") and v.endswith(")")):
                return None
            out_, cur, quoted, esc = [], "", False, False
            for ch in v[4:-1]:
                if esc:
                    cur, esc = cur + ch, False
                elif ch == "\\" and quoted:
                    esc = True
                elif ch == '"':
                    quoted = not quoted
                elif ch == "," and not quoted:
                    out_.append(cur)
                    cur = ""
                else:
                    cur += ch
            return out_ + [cur]
        with self.lock:
            self.log.append({"t": time.time(), "m": method, "p": path, "q": query, "apikey": headers.get("apikey"), "auth": headers.get("Authorization"),
                             "ua": headers.get("User-Agent") or "", "prefer": headers.get("Prefer") or "", "body": body})
            if self.mode == "paused":
                return 540, {"message": "project paused"}
            if self.mode == "echo":
                return 500, {"code": "XX000", "message": "bad apikey %s" % headers.get("apikey")}
            if headers.get("apikey") != APP_SECRET or headers.get("Authorization"):
                return 401, {"code": "PGRST301", "message": "no valid key"}
            j = json.loads(body) if body else None
            if self.mode == "echobody" and method == "POST" and path == "/rest/v1/app_secret":
                return 500, {"code": "XX000", "message": "could not store %s" % body}
            if path == "/rest/v1/live":
                if method == "POST":
                    old = self.live.get(j["id"])
                    now_ms = int(time.time() * 1000)
                    self.live[j["id"]] = {"id": j["id"], "doc": j["doc"], "ver": max(now_ms, old["ver"] + 1) if old else now_ms}
                    return 201, None
                rid = eq("id")
                return 200, [r for k, r in self.live.items() if rid is None or k == rid]
            for name, table, merge in (("app_secret", self.secret, False), ("app_config", self.config, True)):
                if path == "/rest/v1/" + name:
                    if method == "POST":
                        if merge or j["key"] not in table:
                            table[j["key"]] = j["value"]
                        return 201, None
                    k = eq("key")
                    return 200, [{"value": table[k]}] if k in table else []
            if path == "/rest/v1/push_subs":
                eps = ins("endpoint")
                eps = eps if eps is not None else [eq("endpoint")]
                if method == "DELETE":
                    for e_ in eps:
                        self.subs.pop(e_, None)
                    return 204, None
                if method == "PATCH":
                    for e_ in eps:
                        if e_ in self.subs:
                            self.subs[e_].update(j or {})
                    return 204, None
                order = (q.get("order") or [""])[0]
                if self.old_subs and ("delivered" in order or "fails" in (q.get("select") or [""])[0]):
                    return 400, {"code": "42703", "message": "column push_subs.delivered does not exist"}
                rows = [dict(r) for r in self.subs.values()]
                if order.startswith("delivered.desc"):
                    rows.sort(key=lambda r: r.get("delivered") or "", reverse=True)      # stable: the delivered ones first, newest first
                return 200, rows
            return 404, {"message": "no such table"}


class PushSink:
    """A local push service: answers each endpoint with the status set for it (201 by default) and notes what came (decrypted with the
    subscription's key when the real pywebpush encrypted it)."""

    def __init__(self):
        self.codes, self.keys, self.got, self.lock = {}, {}, [], threading.Lock()

    def handle(self, path, headers, body):
        name = path.rsplit("/", 1)[-1]
        data = body
        if name in self.keys and headers.get("Content-Encoding") == "aes128gcm":
            try:
                import http_ece
                data = http_ece.decrypt(body, private_key=self.keys[name][0], auth_secret=self.keys[name][1], version="aes128gcm")
            except Exception as e:
                data = ("undecryptable: %s" % e).encode()
        with self.lock:
            self.got.append({"name": name, "headers": {k.lower(): v for k, v in headers.items()}, "data": data.decode("utf-8", "replace"), "t": time.time()})
        return self.codes.get(name, 201)


def app_browser_checks(check, sd, young):
    """The installed app in Chromium (when Playwright and a Chromium are installed): the website built by bot.py site with the live store is
    served at its address from sd, Supabase's REST API is stubbed with a scan running now that carries young (the spotter's list), GitHub's API
    is counted, every other request is refused. navigator.standalone is true, as in the app opened from the Home Screen."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        SKIPS.append("the browser checks of the installed app (no Playwright)")
        print("  SKIP the browser checks of the installed app: Playwright is not installed")
        return
    exe = os.environ.get("MEMEBOT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    pages_url, sb_url = "https://maxpandelakis-boop.github.io/Meme-Bot/", "https://abcref.supabase.co"
    ms = lambda: int(time.time() * 1000)
    now = ms()
    t = now - 6 * 60_000
    files = {n: open(os.path.join(sd, n), "rb").read() for n in os.listdir(sd) if os.path.isfile(os.path.join(sd, n))}
    files["index.html"] = re.sub(rb'data-run-t="\d+"', b'data-run-t="%d"' % (now - 66 * 60_000), files["index.html"])
    sh = t - young["t"]
    y = dict(young, t=t, at=(young.get("at") or young["t"]) + sh, rcAt=(young["rcAt"] + sh) if young.get("rcAt") else None,
             coins=[dict(c, born=(c["born"] + sh) if c.get("born") else None, minted=(c["minted"] + sh) if c.get("minted") else None) for c in young["coins"]])
    y["coins"][0] = dict(y["coins"][0], launchpad="Raydium LaunchLab Extras", dex="pumpswap-amm-v2-extended", minted=t - 12 * 86_400_000)   # 24 characters each
    n = len(y["coins"])
    ags = [{"id": "dispatch", "status": "done", "lines": ["full scan"]}, {"id": "scouts", "status": "done", "lines": []},
           {"id": "spotter", "status": "done", "bg": True, "lines": ["%d new launches" % n]}, {"id": "market", "status": "running", "lines": ["prices"]}]
    st = {"rows": {}}

    def scan(live, ver, nver=None, listed=True):
        a = ags if live else ags[:3] + [{"id": "market", "status": "done"}, {"id": "trader", "status": "done"}, {"id": "reporter", "status": "done"}]
        cur = {"v": 1, "t": t, "live": live, "updated": ms() - 3000, "horizon": "24h", "mode": "full", "agents": a, "young": y if listed else None, "ver": ver}
        stt = dict(cur, young={"n": n, "newest": min(c.get("ageMin") or 99 for c in y["coins"]), "state": "listed", "at": y["at"], "t": t} if listed else None,
                   nver=ver if nver is None else nver)
        st["rows"] = {"status": stt, "current": cur}
    scan(True, 1)
    calls = {"status": 0, "current": 0, "github": 0, "other": []}
    errs = []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
            ctx.add_init_script("Object.defineProperty(Navigator.prototype,'standalone',{get:function(){return true;}});")
            cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "apikey, content-type, accept, prefer", "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}

            def handler(route):
                u, m = route.request.url, route.request.method
                if u.startswith(pages_url):
                    name = urllib.parse.urlsplit(u).path[len("/Meme-Bot/"):] or "index.html"
                    ct = {"html": "text/html; charset=utf-8", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png", "webmanifest": "application/manifest+json"}
                    if name in files:
                        route.fulfill(status=200, body=files[name], headers={"Content-Type": ct.get(name.rsplit(".", 1)[-1], "application/octet-stream")})
                    else:
                        route.fulfill(status=404, body="")
                elif u.startswith(sb_url + "/rest/v1/"):
                    if m == "OPTIONS":
                        route.fulfill(status=204, headers=cors)
                        return
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
                    rid = (q.get("id") or [""])[0].replace("eq.", "")
                    if "/rest/v1/live" in u and rid in st["rows"]:
                        calls[rid] += 1
                        route.fulfill(status=200, body=json.dumps([{"doc": st["rows"][rid]}]), headers=dict(cors, **{"Content-Type": "application/json"}))
                    else:
                        route.fulfill(status=200, body="[]", headers=dict(cors, **{"Content-Type": "application/json"}))
                elif u.startswith("https://api.github.com/"):
                    calls["github"] += 1
                    route.fulfill(status=404, body="{}", headers={"Access-Control-Allow-Origin": "*"})
                else:
                    calls["other"].append(u[:60])
                    route.abort()
            ctx.route("**/*", handler)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            pg.goto(pages_url)
            pg.wait_for_selector(".appbar", timeout=8000)
            scan_btn = pg.evaluate("(() => { const b = document.querySelector('[data-ss-now]'), l = document.querySelector('.wrap > .live');"
                                   " return b && !b.hidden && b.getClientRects().length && !(l && l.getClientRects().length) ? b.getBoundingClientRect().height : 0; })()")
            got_badge = True
            try:
                pg.wait_for_function("n => ((document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt')||{}).textContent||'') === String(n)", arg=n, timeout=10000)
            except Exception:
                got_badge = False
            pg.click('.appbar button[data-tab="young"]')
            try:
                pg.wait_for_function("n => document.querySelectorAll('[data-early-list] > li').length === n", arg=n, timeout=8000)
            except Exception:
                pass
            info = pg.evaluate("""() => { const b = document.querySelector('[data-early]'), r = e => e.getBoundingClientRect(), pane = document.getElementById('pane-young');
              const scored = pane ? Array.from(pane.querySelectorAll('h3')).find(h => /This scan/.test(h.textContent)) : null;
              return { app: document.documentElement.classList.contains('app'), young: (document.getElementById('tab-young')||{}).checked, hidden: b ? b.hidden : null,
                cards: document.querySelectorAll('[data-early-list] > li').length, status: b ? b.querySelector('[data-early-status]').textContent : '',
                above: !!(b && scored && r(b).bottom <= r(scored).top), dot: !!document.querySelector('.appbar [data-tab="office"] .ab-dot'),
                hscroll: document.documentElement.scrollWidth - innerWidth, hint: (document.querySelector('.ehint')||{}).textContent || '' }; }""")
            aria = pg.evaluate("['young', 'office'].map(t => document.querySelector('.appbar [data-tab=\"' + t + '\"]').getAttribute('aria-label'))")
            pg.click('.appbar button[data-tab="office"]')
            pg.wait_for_timeout(1200)
            office = pg.evaluate("[(document.querySelector('[data-live-badge]')||{}).textContent||'', document.querySelectorAll('[data-agent][data-live]').length]")
            scan(False, 2, nver=1)  # the scan ends: a new ver, but its early list and pick are as before (nver): the page does not read current again
            pg.click('.appbar button[data-tab="young"]')
            done_ok = True
            try:
                pg.wait_for_function("() => ((document.querySelector('[data-early-status]')||{}).textContent||'').indexOf('The scan finished at') === 0", timeout=12000)
            except Exception:
                done_ok = False
            after = pg.evaluate("[((document.querySelector('.appbar [data-tab=\"young\"] .ab-cnt')||{}).textContent||''), !!document.querySelector('.appbar [data-tab=\"office\"] .ab-dot'), document.querySelectorAll('[data-early-list] > li').length]")
            calls_main = dict(calls)
            ctx.close()
            # a tap on the "new coins" notification at 320 x 640: before the list there is no badge; once the list is in, the page scrolls to the early
            # box, so its status line and the first coin are in view above the tab bar
            scan(True, 3, listed=False)
            ctx = br.new_context(viewport={"width": 320, "height": 640}, service_workers="block")
            ctx.add_init_script("Object.defineProperty(Navigator.prototype,'standalone',{get:function(){return true;}});")
            ctx.route("**/*", handler)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            pg.goto(pages_url + "#tab-young")
            wait_ok = True
            try:
                pg.wait_for_function("() => ((document.querySelector('[data-early-status]')||{}).textContent||'').indexOf('Scan running since') === 0", timeout=10000)
            except Exception:
                wait_ok = False
            nobadge = pg.evaluate("[!!document.querySelector('.appbar .ab-cnt'), document.querySelector('.appbar [data-tab=\"young\"]').getAttribute('aria-label')]")
            scan(True, 4)
            try:
                pg.wait_for_function("n => document.querySelectorAll('[data-early-list] > li').length === n && window.scrollY > 0", arg=n, timeout=12000)
            except Exception:
                pass
            pg.wait_for_timeout(300)
            deep = pg.evaluate("""() => { const b = document.querySelector('[data-early]'), c = document.querySelector('[data-early-list] > li'), bar = document.querySelector('.appbar');
              return { y: scrollY, box: b.getBoundingClientRect().top, card: c ? c.getBoundingClientRect().top : 1e9, cardEnd: c ? c.getBoundingClientRect().bottom : 1e9,
                bar: bar.getBoundingClientRect().top, status: (b.querySelector('[data-early-status]')||{}).textContent || '', hscroll: document.documentElement.scrollWidth - innerWidth,
                tok: Array.from(document.querySelectorAll('[data-early-list] .eline')).map(e => e.textContent).filter(t => t.indexOf('LaunchLab Extras') >= 0)[0] || '' }; }""")
            ctx.close()
            # a browser tab (not the installed app): the live store is read only on New launches or Agent office, and the tabs of one browser share one reader
            scan(True, 5)
            ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
            ctx.add_init_script("window.MEMEBOT_LIVE_T={SB_EVERY:1000};")
            ctx.route("**/*", handler)
            pa = ctx.new_page()
            c0 = calls["status"]
            pa.goto(pages_url)
            pa.wait_for_timeout(3000)
            on_pick = calls["status"] - c0
            pa.click('label[for="tab-young"]')
            c0 = calls["status"]
            pa.wait_for_timeout(8000)
            one = calls["status"] - c0
            pb = ctx.new_page()
            pb.goto(pages_url)
            pb.click('label[for="tab-young"]')
            c0 = calls["status"]
            pb.wait_for_timeout(8000)
            two = calls["status"] - c0
            shared = [p_.evaluate("[document.visibilityState, document.querySelectorAll('[data-early-list] > li').length, document.documentElement.classList.contains('app')]") for p_ in (pa, pb)]
            br.close()
    except Exception as e:
        check(False, "the browser checks of the installed app could not run (Playwright is installed; Chromium needs a short TMPDIR path): %s" % str(e)[:200])
        return
    check(got_badge and info["app"] and info["young"] and info["hidden"] is False and info["cards"] == n and info["status"].startswith("Found at") and info["above"]
          and info["dot"] and info["hscroll"] <= 0 and "With notifications on" in info["hint"] and not errs,
          "installed app (Chromium, live store): the New coins tab shows the spotter's early list (%d cards, '%s...') above the scored list, its badge says %d, "
          "the Office tab has its live dot %s" % (info["cards"], info["status"][:24], n, ("" if not errs else errs[:2])))
    check(office[0].startswith("LIVE") and office[1] >= 3 and done_ok and after == [str(n), False, n] and calls_main["current"] == 1 and calls_main["status"] >= 2 and calls_main["github"] == 0,
          "installed app: the same snapshot feeds the office view (%r) and the early box; when the scan ends the box says so and keeps the list, the office dot goes; "
          "one poller only: %d status reads, current only per new nver (%d: not again for the end's new ver), no GitHub poll (%d)%s" % (
              office[0][:20], calls_main["status"], calls_main["current"], calls_main["github"], "" if done_ok and after == [str(n), False, n] else " %s %s %s" % (done_ok, after, office)))
    check(aria == ["New coins, %d listed now" % n, "Office, a scan is running now"] and nobadge == [False, "New coins"] and scan_btn >= 44,
          "installed app: the New coins badge only with a scan's early list (none while the scan has not listed yet), the tabs' badge and dot read out in words"
          " (%s), the full scan's strip has the one Scan now (%d px tall; the Live box with its own button is not shown)" % (aria, scan_btn))
    check(wait_ok and 0 < deep["y"] and -1 <= deep["box"] <= 40 and deep["card"] + 60 <= deep["bar"] and deep["status"].startswith("Found at") and deep["hscroll"] <= 0
          and deep["tok"].startswith("token 12 days old (Raydium LaunchLab Extras) · pumpswap-amm-v2-extended"),
          "installed app at 320 x 640, opened by the new coins notification (#tab-young): once the list is in, the page scrolls to the early box (its top at %.0f px),"
          " the first coin's card starts above the tab bar (at %.0f px, bar at %.0f px); a 24-character launchpad never widens the page%s" % (
              deep["box"], deep["card"], deep["bar"], "" if wait_ok and deep["tok"] and deep["y"] > 0 else " %s %s" % (wait_ok, deep)))
    check(on_pick == 0 and one >= 3 and two <= one + 2 and shared == [["visible", n, False]] * 2,
          "a browser tab reads the live store only on New launches or Agent office (%d reads in 3 s on The pick), and two tabs share one reader through"
          " localStorage (%d reads in 8 s with one tab, %d with two, both showing the list)" % (on_pick, one, two))


def serve_app(rest, sink):
    class Hd(BaseHTTPRequestHandler):
        def _go(self):
            u = urllib.parse.urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if u.path.startswith("/push/"):
                code = sink.handle(u.path, self.headers, body)
                if code == "hang":            # a push service that never answers
                    REAL_SLEEP(40)
                    return
                self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
                return
            if u.path.startswith("/mode/"):   # a test process switches the store's behaviour
                rest.mode = u.path[6:]
                self.send_response(204); self.end_headers()
                return
            if rest.mode.startswith("redirect:"):   # a store address that redirects elsewhere: the secret key must not follow
                with rest.lock:
                    rest.log.append({"t": time.time(), "m": self.command, "p": u.path, "q": u.query, "apikey": self.headers.get("apikey"),
                                     "auth": self.headers.get("Authorization"), "ua": "", "prefer": "", "body": ""})
                self.send_response(302); self.send_header("Location", rest.mode[9:] + self.path); self.send_header("Content-Length", "0"); self.end_headers()
                return
            m_ = re.fullmatch(r"slow(post)?([0-9.]+)", rest.mode)
            if m_ and (not m_.group(1) or self.command in ("POST", "PATCH")):   # a slow store (slowpost: only its writes): each answer this
                REAL_SLEEP(float(m_.group(2)))                                     # many seconds late (each request on its own thread)
            if rest.mode == "dribble":        # a store that answers a byte a second: per-socket timeouts never fire
                with rest.lock:
                    rest.log.append({"t": time.time(), "m": self.command, "p": u.path, "q": u.query, "apikey": self.headers.get("apikey"),
                                     "auth": self.headers.get("Authorization"), "ua": "", "prefer": "", "body": body.decode("utf-8") if body else ""})
                try:
                    self.send_response(200); self.send_header("Content-Length", "100"); self.end_headers(); self.wfile.flush()
                    for _ in range(100):
                        self.wfile.write(b" "); self.wfile.flush(); REAL_SLEEP(1.0)
                except OSError:
                    pass
                return
            code, out = rest.handle(self.command, u.path, u.query, self.headers, body.decode("utf-8") if body else "")
            raw = json.dumps(out).encode() if out is not None else b""
            try:                              # a client that cut its request short (app.end_sink) is gone: nothing to answer
                self.send_response(code)
                if raw:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except OSError:
                pass

        do_GET = do_POST = do_DELETE = do_PATCH = _go

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)      # a slow answer holds up its own request only
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


FAKE_PYWEBPUSH = '''"""A stand-in for pywebpush 2.5.0 (same call, same exception; no encryption): the test's push service reads the JSON as sent."""
import urllib.error, urllib.request


class WebPushException(Exception):
    def __init__(self, message, response=None):
        self.message, self.response = message, response

    @property
    def status_code(self):
        return getattr(self.response, "status_code", None)


class _R:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


def webpush(subscription_info, data=None, vapid_private_key=None, vapid_claims=None, content_encoding="aes128gcm", curl=False, timeout=None,
            ttl=0, verbose=False, headers=None, requests_session=None):
    h = dict(headers or {})
    h["TTL"] = str(ttl or 0)
    h["X-Timeout"] = str(timeout)
    req = urllib.request.Request(subscription_info["endpoint"], data=(data or "").encode("utf-8"), method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout or 5) as r:
            return _R(r.status, "")
    except urllib.error.HTTPError as e:
        raise WebPushException("Push failed: %d" % e.code, response=_R(e.code, ""))
'''


def b64u(b):
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def app_tests(check, mock, url):
    """The iPhone app: app.py against a local PostgREST stand-in and a local push service, bot.py's live feed and hooks, the site step's
    key guard and files, the page's decisions and sw.js in node, and supabase/setup.sql on PostgreSQL when MEMEBOT_PG is set."""
    import importlib.util
    print("== iPhone app: live store, push notifications, the installed app")
    rest, sink = Rest(), PushSink()
    srv = serve_app(rest, sink)
    sb = "http://127.0.0.1:%d" % srv.server_address[1]
    tmp = tempfile.mkdtemp(prefix="memebot-app-")
    fake = os.path.join(tmp, "fakepush")
    os.makedirs(fake)
    with open(os.path.join(fake, "pywebpush.py"), "w") as f:
        f.write(FAKE_PYWEBPUSH)
    nopush = os.path.join(tmp, "nopush")
    os.makedirs(nopush)
    with open(os.path.join(nopush, "pywebpush.py"), "w") as f:
        f.write("raise ImportError('pywebpush is not installed (test)')\n")
    real = importlib.util.find_spec("pywebpush") is not None and importlib.util.find_spec("http_ece") is not None
    has_crypto = importlib.util.find_spec("cryptography") is not None
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "MEMEBOT_"))}
    base.update(PYTHONUTF8="1", MEMEBOT_PAUSE="0")
    env_app = dict(base, SUPABASE_URL=sb, SUPABASE_SECRET_KEY=APP_SECRET, MEMEBOT_PUSH_YOUNG="1")   # the scan's "new coins" push is off unless
    # MEMEBOT_PUSH_YOUNG=1 (selftest_scanside S4 checks the default); these checks test it switched on, exactly as before
    if not real:
        env_app["PYTHONPATH"] = fake + os.pathsep + base.get("PYTHONPATH", "")

    def drive(code, env, timeout=120):
        p = subprocess.run([PY, "-c", "import sys, json, time, os; sys.path.insert(0, %r)\n" % HERE + code], capture_output=True, text=True, env=env, timeout=timeout)
        try:
            out = json.loads((p.stdout.strip().splitlines() or ["null"])[-1])
        except ValueError:
            out = None
        return p, out

    seen_out = []        # every output of a process that had the secret key: none may contain it

    # 1. without the variables: nothing is imported that is not stdlib, nothing goes to the network
    p, out = drive("import app\nprint(json.dumps([app.enabled(), app.sink({'t': 1, 'agents': []}), app.notify('pick', 'a', 'b'), app.prepare()]))",
                   dict(base, SUPABASE_URL=sb))
    check(p.returncode == 0 and out == [False, False, {"kind": "pick", "sent": 0, "gone": 0, "bad": 0, "failed": 0, "skipped": "no live store"}, None] and not rest.log,
          "app.py without SUPABASE_SECRET_KEY: off, no request, no error (%s)" % (out if out is not None else p.stderr[-200:]))
    bare = tempfile.mkdtemp(prefix="memebot-app-bare-")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    d0 = os.path.join(tmp, "plain")
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d0, "--mock", url, "--now", str(mock.now), "--recommend"], capture_output=True, text=True,
                       env=dict(base, MEMEBOT_LIVE="1", RESULTS_URL=bare, SUPABASE_URL=sb, SUPABASE_PUBLISHABLE_KEY="sb_publishable_x1234567890"))
    check(r.returncode == 0 and not rest.log and "app's live store" not in r.stderr and "app:" not in r.stderr and "live view: the office goes to branch live" in r.stderr,
          "a live cycle without the secret key: the git live view as before, not one request to the live store, no app line in the log")

    # 2. the sink: rows status and current, current on its own cadence; the key in the apikey header only
    rec = {"v": 1, "t": 1000, "live": True, "updated": 1, "end": 2, "horizon": "2h", "mode": "full",
           "agents": [{"id": "market", "status": "running", "bg": False, "start": 1, "end": None, "lines": ["l%d" % i for i in range(40)], "out": "x" * 300, "waits": {}, "blocked": []}],
           "young": {"v": 1, "t": 1000, "state": "listed", "coins": [{"sym": "AAA", "ageMin": 5}, {"sym": "BBB", "ageMin": 12}]}}
    code = ("import app, copy\nrec = json.loads(%r)\nt = 5000.0\nout = []\n" % json.dumps(rec) +
            "def w(r, dt):\n    out.append(app.sink(r, now=t + dt))\n" +
            "r2 = copy.deepcopy(rec); r2['updated'] = 2\n"
            "r3 = copy.deepcopy(r2); r3['agents'][0]['lines'].append('new line')\n"
            "r4 = copy.deepcopy(r3); r4['young']['coins'].append({'sym': 'CCC', 'ageMin': 1})\n"
            "r5 = copy.deepcopy(r4); r5['agents'][0]['lines'].append('later')\n"
            "r6 = copy.deepcopy(r5); r6['live'] = False\n"
            "for r, dt in ((rec, 0), (r2, 5), (r3, 10), (r4, 12), (r5, 20), (r5, 45), (r6, 46)):\n    w(r, dt)\n"
            "print(json.dumps(out))\n")
    n0 = len(rest.log)
    p, out = drive(code, env_app)
    seen_out.append(p.stdout + p.stderr)
    writes = [(e["q"].split("on_conflict")[0], json.loads(e["body"])["id"]) for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live"]
    rows = [w[1] for w in writes]
    st, cur = (rest.live.get("status") or {}).get("doc") or {}, (rest.live.get("current") or {}).get("doc") or {}
    check(out == [True] * 7 and rows == ["current", "status", "status", "status", "current", "status", "status", "current", "status", "current", "status"],
          "sink: current at the start, then only when the early list changed, 30 s after the last one, or at the end; status every time (%s)" % ",".join(r[0] for r in rows))
    check(st.get("live") is False and st.get("ver") == cur.get("ver") and isinstance(st.get("ver"), int) and st.get("young") == {"n": 3, "newest": 1, "state": "listed", "at": None, "t": 1000}
          and st["agents"][0]["lines"] == ["later"] and len(st["agents"][0]["out"]) == 120 and len(json.dumps(st)) < 2000
          and cur.get("young", {}).get("coins", [{}])[-1].get("sym") == "CCC" and len(cur["agents"][0]["lines"]) == 12 and cur["agents"][0]["lines"][-1] == "later",
          "status is small (%d bytes: last line, short result, the early list's count and newest age) and names current's ver; current carries young and 12 lines per agent" % len(json.dumps(st)))
    cvers = [json.loads(e["body"])["doc"].get("ver") for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "current"]
    check(len(cvers) == 4 and st.get("nver") == cvers[1] and st.get("nver") != st.get("ver"),
          "status names nver, the version of current whose early list or pick changed last (%s of %s): the page reads current only when that changes, not at"
          " every 30-second write of the agents' lines" % (st.get("nver"), cvers))
    lg = rest.log[n0:]
    check(lg and all(e["apikey"] == APP_SECRET and e["auth"] is None and "Mozilla" not in e["ua"] for e in lg) and all(APP_SECRET not in e["q"] for e in lg)
          and all("resolution=merge-duplicates" in e["prefer"] for e in lg if e["m"] == "POST"),
          "every request carries the secret key in the apikey header only (no Authorization, not in the URL), with a non-browser User-Agent; writes are upserts")
    code = ("import app\nrec = json.loads(%r)\nrec.pop('young')\nout = [app.sink(rec, now=100.0)]\n" % json.dumps(rec) +
            "rec['agents'][0]['lines'].append('trader done')\nout.append(app.sink(rec, now=103.0))\n"
            "rec['pick'] = {'t': 1000, 'sym': 'MOON1', 'name': 'Moon One', 'score': 81.6, 'tier': 'strong'}\nout.append(app.sink(rec, now=105.0))\n"
            "print(json.dumps(out))\n")
    n0 = len(rest.log)
    p, out = drive(code, env_app)
    seen_out.append(p.stdout + p.stderr)
    rows = [json.loads(e["body"])["id"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live"]
    st, cur = (rest.live.get("status") or {}).get("doc") or {}, (rest.live.get("current") or {}).get("doc") or {}
    check(out == [True] * 3 and rows == ["current", "status", "status", "current", "status"] and cur.get("pick", {}).get("sym") == "MOON1"
          and st.get("pick") == {"sym": "MOON1", "t": 1000, "score": 81.6} and st.get("ver") == cur.get("ver"),
          "sink: a new pick writes current at once (not 30 s later), so a tap on the pick notification finds it; status carries the pick with its score (%s)" % ",".join(rows))
    rest.mode = "echo"
    p, out = drive("import app\nprint(json.dumps([app.sink({'t': 7, 'agents': []}), app.sink({'t': 7, 'agents': [{'id': 'x'}]})]))", env_app)
    rest.mode = "paused"
    p2, out2 = drive("import app\nprint(json.dumps([app.sink({'t': 8, 'agents': []}), app.prepare()]))", env_app)
    rest.mode = "ok"
    seen_out += [p.stdout + p.stderr, p2.stdout + p2.stderr]
    check(out == [False, False] and APP_SECRET not in p.stdout + p.stderr and "bad apikey ***" in p.stderr and p.stderr.count("app: live store: writing the row status failed") == 1
          and out2 == [False, None] and "HTTP 540" in p2.stderr and "paused" in p2.stderr,
          "a failing store never raises: an error that echoes the key prints it blanked, once; a paused project (540) says so")
    # a store address that redirects elsewhere: no redirect is followed, so the other address never sees the secret key
    other = []

    class Oth(BaseHTTPRequestHandler):
        def _go(self):
            other.append(dict(self.headers))
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"[]")
        do_GET = do_POST = _go

        def log_message(self, *a):
            pass
    osrv = ThreadingHTTPServer(("127.0.0.1", 0), Oth)
    threading.Thread(target=osrv.serve_forever, daemon=True).start()
    rest.mode = "redirect:http://127.0.0.1:%d" % osrv.server_address[1]
    p, out = drive("import app\nerrs = []\nfor m in ('GET', 'POST'):\n    try:\n        app.call(m, 'live?select=id', {'id': 'x'} if m == 'POST' else None)\n"
                   "        errs.append(None)\n    except app.StoreError as e:\n        errs.append(str(e))\nprint(json.dumps([errs, app.sink({'t': 11, 'live': True, 'agents': []})]))", env_app)
    rest.mode = "ok"
    osrv.shutdown()
    seen_out.append(p.stdout + p.stderr)
    check(out and len(out[0]) == 2 and all(e and "HTTP 302" in e and "redirect, not followed" in e for e in out[0]) and out[1] is False and not other,
          "a store address that answers with a redirect: the request ends there (%s), the other address gets no request and so never the secret key (%d)" % (
              (out or [[None]])[0][0], len(other)))

    rest.mode = "dribble"
    code = ("import app, threading\nt0 = time.time()\nerr = None\ntry:\n    app.call('GET', 'live?select=id')\nexcept app.StoreError as e:\n    err = str(e)\nt1 = time.time() - t0\n"
            "t0 = time.time()\nok1 = app.sink({'t': 9, 'live': True, 'agents': [{'id': 'x'}]})\nt2 = time.time() - t0\n"
            "rest_ok = %r\n" % sb + "import urllib.request\nurllib.request.urlopen(rest_ok + '/mode/ok', timeout=5).read()\n"
            "t0 = time.time()\nok2 = app.sink({'t': 9, 'live': False, 'agents': [{'id': 'x'}]})\nt3 = time.time() - t0\n"
            "print(json.dumps({'err': err, 't1': t1, 'ok1': ok1, 't2': t2, 'ok2': ok2, 't3': t3, 'total': app.CALL_TOTAL}))\n")
    p, out = drive(code, env_app)
    rest.mode = "ok"
    seen_out.append(p.stdout + p.stderr)
    out = out or {}
    ok_ = bool(out.get("err") and "no complete answer within" in out["err"] and out["t1"] < out["total"] + 2 and out.get("ok1") is False and out["t2"] < 2 * out["total"] + 4
               and out.get("ok2") is True and out["t3"] < 2)
    check(ok_, "a store that answers a byte a second: each request is cut off after %s s (%.1f s; a sink %.1f s), the next write goes out at once when the store is back (%.1f s)%s" % (
              out.get("total"), out.get("t1", -1), out.get("t2", -1), out.get("t3", -1), "" if ok_ else " %s %s" % (out, p.stderr[-400:])))

    # 3. VAPID: made once, kept in the store, reused
    if has_crypto:
        n0 = len(rest.log)
        p, out = drive("import app\nprint(json.dumps(app.prepare()))", env_app)
        p2, out2 = drive("import app\nprint(json.dumps(app.prepare()))", env_app)
        seen_out += [p.stdout + p.stderr, p2.stdout + p2.stderr]
        priv = rest.secret.get("vapid_private_key") or ""
        posts = [e for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/app_secret"]
        check(isinstance(out, str) and out == out2 == rest.config.get("vapid_public_key") and len(out) == 87 and out.startswith("B") and len(priv) == 43 and len(posts) == 1
              and "resolution=ignore-duplicates" in posts[0]["prefer"] and "made the VAPID key pair" in p.stderr and "made" not in p2.stderr
              and priv not in p.stdout + p.stderr + p2.stdout + p2.stderr,
              "VAPID: the pair is made on first use (private key in app_secret, public key in app_config), reused by the next run, never printed")
        kept_secret, kept_config = dict(rest.secret), dict(rest.config)
        rest.secret.clear()
        rest.mode = "echobody"
        n0 = len(rest.log)
        p, out = drive("import app\nprint(json.dumps(app.prepare()))", env_app)
        rest.mode = "ok"
        seen_out.append(p.stdout + p.stderr)
        sent_keys = [json.loads(e["body"]).get("value") for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/app_secret" and e["body"]]
        rest.secret.clear(); rest.secret.update(kept_secret); rest.config.clear(); rest.config.update(kept_config)
        check(out is None and sent_keys and len(sent_keys[0] or "") == 43 and sent_keys[0] not in p.stdout + p.stderr and "could not store" in p.stderr and "***" in p.stderr,
              "VAPID: a store error that repeats what it was sent prints the newly made private key blanked (it is hidden from before it is sent, not only once stored)")
    else:
        SKIPS.append("VAPID and push (no cryptography)")
        print("  SKIP VAPID and push checks: cryptography is not installed here (pywebpush brings it on the runner)")

    # 4. push: the right JSON to the right subscriptions, gone ones deleted, settings respected, a rate guard
    if has_crypto:
        def sub(name, base=None):
            """A subscription with real keys (a P-256 point and 16 random bytes): app.py deletes rows whose keys are no keys."""
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            k = ec.generate_private_key(ec.SECP256R1())
            auth = os.urandom(16)
            if real:
                sink.keys[name] = (k, auth)
            p256 = b64u(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
            return {"endpoint": (base or sb) + "/push/" + name, "expirationTime": None, "keys": {"p256dh": p256, "auth": b64u(auth)}}
        for name, prefs in (("both", {"young": True, "pick": True}), ("noPick", {"young": True, "pick": False}), ("noYoung", {"young": False, "pick": True}),
                            ("gone", {"young": True, "pick": True}), ("lost", {"young": True, "pick": True}), ("busy", {"young": True, "pick": True})):
            s_ = sub(name)
            rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": prefs}
        sink.codes.update(gone=410, lost=404, busy=503)
        n0, g0 = len(rest.log), len(sink.got)
        code = ("import app\nr1 = app.notify_pick({'t': 1, 'picks': [{'sym': 'MOON1', 'name': 'Moon One', 'score': 81.6, 'tier': 'strong'}]})\n"
                "r2 = app.notify_pick({'t': 1, 'picks': [{'sym': 'MOON1'}]})\n"
                "r3 = app.notify_young({'state': 'listed', 'coins': [{'sym': 'A1', 'ageMin': 12}, {'sym': 'B2', 'ageMin': 4}, {'sym': 'C3'}, {'sym': 'D4\\n'}]})\n"
                "r4 = app.notify_young({'state': 'listed', 'coins': []})\n"
                "print(json.dumps([r1, r2, r3, r4]))\n")
        t_ = time.time()
        p, out = drive(code, env_app)
        took = time.time() - t_
        seen_out.append(p.stdout + p.stderr)
        got = sink.got[g0:]
        picks = [g for g in got if '"tag":"pick"' in g["data"]]
        youngs = [g for g in got if '"tag":"young"' in g["data"]]
        pj = json.loads(next((g["data"] for g in picks if g["name"] == "both"), "{}") or "{}")
        yj = json.loads(next((g["data"] for g in youngs if g["name"] == "both"), "{}") or "{}")
        home = "https://maxpandelakis-boop.github.io/Meme-Bot/"
        check(pj.get("web_push") == 8030 and pj.get("notification", {}).get("title") == "New pick: MOON1" and pj["notification"].get("navigate") == home + "#tab-pick"
              and "Paper trading only, nothing is bought for real." in pj["notification"].get("body", "") and "score 82" in pj["notification"]["body"]
              and yj.get("notification", {}).get("title") == "4 new coins listed" and yj["notification"].get("navigate") == home + "#tab-young"
              and yj["notification"].get("body", "") == "The newest is 4 min old. On the list: A1, B2, C3 and 1 more, all under an hour old and not scored yet. "
                                                        "Fake money only, nothing is bought for real.",
              "push (%s pywebpush): Declarative Web Push JSON (web_push 8030, a title, a body that says paper only, navigate an absolute URL in /Meme-Bot/); "
              "the new coins one names the count and the newest age, says fake money and opens the New coins tab" % ("real" if real else "a stand-in for"))
        names_p, names_y = sorted(g["name"] for g in picks), sorted(g["name"] for g in youngs)
        check(names_p == ["both", "busy", "busy", "gone", "lost", "noYoung"] and names_y == ["both", "busy", "busy", "noPick"] and out and out[0]["sent"] == 2 and out[0]["gone"] == 2
              and out[0]["failed"] == 1 and out[1]["skipped"] == "rate guard" and out[2]["sent"] == 2 and out[3] == {"skipped": "no coins"}
              and sink.codes and all(sb + "/push/" + n not in rest.subs for n in ("gone", "lost")) and sb + "/push/both" in rest.subs and sb + "/push/busy" in rest.subs
              and len([e for e in rest.log[n0:] if e["m"] == "DELETE"]) == 2,
              "settings respected (no pick for noPick, no young for noYoung, nothing for gone ones now), 404 and 410 deleted, a 503 retried once and kept, a second pick right away held back by the rate guard (%s)" % ", ".join(names_p))
        hp = next((g["headers"] for g in picks if g["name"] == "both"), {})
        hy = next((g["headers"] for g in youngs if g["name"] == "both"), {})
        jwt_ok, claims = False, {}
        try:
            from cryptography.hazmat.primitives.asymmetric import ec, utils
            from cryptography.hazmat.primitives import hashes
            import base64
            dec = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
            m = re.fullmatch(r"vapid t=([\w-]+)\.([\w-]+)\.([\w-]+),k=([\w-]+)", hp.get("authorization", ""))
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), dec(m.group(4)))
            sig = dec(m.group(3))
            pub.verify(utils.encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), (m.group(1) + "." + m.group(2)).encode(), ec.ECDSA(hashes.SHA256()))
            claims = json.loads(dec(m.group(2)))
            jwt_ok = m.group(4) == rest.config.get("vapid_public_key") and json.loads(dec(m.group(1))) == {"typ": "JWT", "alg": "ES256"}
        except Exception as e:
            claims = {"error": str(e)}
        check(jwt_ok and claims.get("aud") == sb and claims.get("sub") == "https://maxpandelakis-boop.github.io" and 0 < claims.get("exp", 0) - time.time() <= 24 * 3600
              and hp.get("ttl") == "3600" and hp.get("urgency") == "high" and hp.get("topic") == "pick" and hy.get("ttl") == "1800" and hy.get("urgency") == "normal"
              and (real or hp.get("x-timeout") == "10"),
              "VAPID header: an ES256 JWT that the stored public key verifies (aud the push service, sub the bare site origin, exp within 24 h); TTL, Urgency and Topic per kind")
        n0 = len(sink.got)
        p, out = drive("import app\nprint(json.dumps(app.notify('pick', 'x', 'y')))", dict(env_app, PYTHONPATH=nopush, MEMEBOT_PUSH_LIB=nopush))
        seen_out.append(p.stdout + p.stderr)
        check(out and out.get("skipped") == "no pywebpush" and len(sink.got) == n0 and "pywebpush is not installed" in p.stderr,
              "without pywebpush nothing is sent and the log says so")

        # junk rows: anyone with the publishable key can save strings that only look like keys (they pass setup.sql's format check)
        kept = dict(rest.subs)
        rest.subs.clear()
        for i in range(24):
            ep = sb + "/push/junk%02d" % i
            rest.subs[ep] = {"endpoint": ep, "sub": {"endpoint": ep, "keys": {"p256dh": "B" + "x" * 86, "auth": "a" * 22}}, "prefs": {"young": True, "pick": True}}
        for name, host in (("valerr", None), ("neterr", "http://127.0.0.1:9"), ("phone", None)):
            s_ = sub(name, host)
            rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": {"young": True, "pick": True}}
        n0, g0 = len(rest.log), len(sink.got)
        t_ = time.time()
        code = ("import app\nw = app._webpush()\n"
                "def wp(sub, *a, **k):\n    if sub['endpoint'].endswith('/valerr'):\n        raise ValueError('Could not deserialize key data')   # as pywebpush does on a key it cannot use\n"
                "    return w[0](sub, *a, **k)\napp._webpush = lambda: (wp, w[1])\n"
                "print(json.dumps(app.notify_pick({'t': 1, 'picks': [{'sym': 'MOON2', 'score': 70}]})))")
        p, out = drive(code, env_app)
        took = time.time() - t_
        seen_out.append(p.stdout + p.stderr)
        got = [g["name"] for g in sink.got[g0:]]
        left = sorted(e.rsplit("/", 1)[-1] for e in rest.subs)
        ph_ep, ne_ep = sb + "/push/phone", "http://127.0.0.1:9/push/neterr"
        gets = [e for e in rest.log[n0:] if e["m"] == "GET" and e["p"] == "/rest/v1/push_subs"]
        check(out and out.get("sent") == 1 and out.get("bad") == 24 and out.get("failed") == 2 and got == ["phone"] and left == ["neterr", "phone", "valerr"] and took < 6
              and len([e for e in rest.log[n0:] if e["m"] == "DELETE"]) == 24 and "24 unusable and deleted" in p.stderr and p.stderr.count("the subscription stays") == 1,
              "24 rows whose keys are no keys ahead of the phone: deleted without a request or a pause, the phone gets the pick in %.1f s; a key pywebpush cannot use"
              " (keys_ok passed) keeps its row and is said once; a network error is not tried again and kept (%s)" % (took, out))
        check(rest.subs.get(ph_ep, {}).get("delivered") and rest.subs[ph_ep].get("fails") == 0 and rest.subs.get(ne_ep, {}).get("fails") == 1
              and not rest.subs.get(sb + "/push/valerr", {}).get("delivered") and gets and "order=delivered.desc.nullslast,seen.desc" in gets[0]["q"],
              "the phone the push reached is marked delivered (the size cap keeps it ahead of strangers' rows) and served first next time; the row whose own host"
              " gave no answer counts one failure (%s)" % {k.rsplit("/", 1)[-1]: {f: v.get(f) for f in ("delivered", "fails")} for k, v in rest.subs.items()})
        # the same row two notifications later: three in a row without an answer from its own host delete it; a row at Apple's shared host is never counted
        res3 = []
        for _ in range(2):
            p, o3 = drive(code, env_app)
            seen_out.append(p.stdout + p.stderr)
            res3.append((o3 or {}).get("sent"))
        code_s = ("import app\ncalls = []\napp.call = lambda m, path, body=None, prefer=None, **k: calls.append([m, path, body])\n"
                  "rows = [{'endpoint': 'https://web.push.apple.com/QAPPLE', 'fails': 2}, {'endpoint': 'https://zz9.notify.windows.com/w/x', 'fails': 0}]\n"
                  "app._settle([], rows, False, time.time() + 9); quiet = list(calls)\n"
                  "app._settle([], rows, True, time.time() + 9)\n"
                  "print(json.dumps([quiet, calls, app.own_host('https://web.push.apple.com/x'), app.own_host('https://fcm.googleapis.com/x'), app.own_host('https://a.b.notify.windows.com/x')]))\n")
        p, os_ = drive(code_s, env_app)
        check(res3 == [1, 1] and ne_ep not in rest.subs and ph_ep in rest.subs and sb + "/push/valerr" in rest.subs and "could not be reached 3 times in a row deleted" in p.stderr + "".join(seen_out[-2:])
              and os_ and os_[0] == [] and len(os_[1]) == 1 and os_[1][0][0] == "PATCH" and "notify.windows.com" in urllib.parse.unquote(os_[1][0][1]) and os_[1][0][2] == {"fails": 1}
              and os_[2:] == [False, False, True],
              "a row whose own push host gives no answer three notifications in a row is deleted; a failure counts only when the same notification reached a push service,"
              " and never at Apple's, Google's or Mozilla's shared host (%s)" % (os_[1] if os_ else p.stderr[-200:]))
        # a table from before the delivered column (setup.sql not run again): the notification still goes out, the log says what to do
        rest.old_subs = True
        p, o4 = drive(code.replace("'MOON2'", "'MOON3'"), env_app)
        rest.old_subs = False
        seen_out.append(p.stdout + p.stderr)
        check(o4 and o4.get("sent") == 1 and "run supabase/setup.sql again" in p.stderr,
              "push_subs without the delivered column (setup.sql not run again yet): the notification still goes out and the log says to run setup.sql again")
        rest.subs.clear()
        for name in ("hung", "ok1", "ok2"):
            s_ = sub(name)
            rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": {"young": True, "pick": True}}
        sink.codes["hung"] = "hang"
        g0 = len(sink.got)
        t_ = time.time()
        p, out = drive("import app\nr = app.notify_young({'state': 'listed', 'coins': [{'sym': 'A1'}]})\nr['budget'] = app.NOTIFY_BUDGET\nprint(json.dumps(r))", env_app)
        took = time.time() - t_
        seen_out.append(p.stdout + p.stderr)
        got = sorted(set(g["name"] for g in sink.got[g0:]))
        ok_ = bool(out and out.get("budget", 99) <= 15 and out.get("sent") == 2 and out.get("failed") == 1 and got == ["hung", "ok1", "ok2"] and took < out["budget"] + 3
                   and ("got no answer within" in p.stderr or "notification failed (net " in p.stderr))
        check(ok_, "a push service that never answers holds up its own push only: the others go out beside it and the notification ends within its %s s budget (%.1f s)%s" % (
                  (out or {}).get("budget"), took, "" if ok_ else " %s %s %s" % (out, got, p.stderr[-400:])))
        # the pushes' own time starts once the keys and the subscriptions are read: a slow store while the keys are made does not use it up
        rest.subs.clear()
        s_ = sub("bud")
        rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": {"young": True, "pick": True}}
        kept_secret, kept_config = dict(rest.secret), dict(rest.config)
        rest.secret.clear(); rest.config.clear()
        rest.mode = "slow1.2"
        g0 = len(sink.got)
        t_ = time.time()
        p, out = drive("import app\napp.NOTIFY_BUDGET = 4\nprint(json.dumps(app.notify_young({'state': 'listed', 'coins': [{'sym': 'A1', 'ageMin': 2}]})))", env_app)
        took = time.time() - t_
        rest.mode = "ok"
        rest.secret.clear(); rest.secret.update(kept_secret); rest.config.clear(); rest.config.update(kept_config)
        seen_out.append(p.stdout + p.stderr)
        check(out and out.get("sent") == 1 and [g["name"] for g in sink.got[g0:]] == ["bud"] and took > 6 and "no answer" not in p.stderr and "not tried" not in p.stderr,
              "a store that takes 1.2 s a request while the VAPID keys are made (%.1f s in all): the push still goes out, its 4 s start after the reads (%s)" % (took, out))
        # failures are said once per kind and kind of failure: a pick failing as the new coins one did is said too
        rest.subs.clear()
        s_ = sub("dup")
        rest.subs[s_["endpoint"]] = {"endpoint": s_["endpoint"], "sub": s_, "prefs": {"young": True, "pick": True}}
        sink.codes["dup"] = 400
        p, out = drive("import app\nprint(json.dumps([app.notify_young({'state': 'listed', 'coins': [{'sym': 'A1'}]}), app.notify_pick({'t': 1, 'picks': [{'sym': 'P1'}]})]))", env_app)
        seen_out.append(p.stdout + p.stderr)
        check(out and [o_.get("failed") for o_ in out] == [1, 1] and "a young notification failed (config 400)" in p.stderr and "a pick notification failed (config 400)" in p.stderr,
              "a failure is said once per notification kind: the pick's 400 after the new coins' 400 is printed too")
        rest.subs.clear()
        rest.subs.update(kept)

    # 5. bot.py: a live cycle feeds the store on its own cadence and sends the pick notification; the hooks for the launch spotter
    d1 = os.path.join(tmp, "live")
    n0, g0 = len(rest.log), len(sink.got)
    t_ = time.time()
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d1, "--mock", url, "--now", str(mock.now), "--recommend"], capture_output=True, text=True,
                       env=dict(env_app, MEMEBOT_LIVE="1", RESULTS_URL=bare, SUPABASE_PUBLISHABLE_KEY="sb_publishable_x1234567890"))
    seen_out.append(r.stdout + r.stderr)
    lw = [e for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live"]
    sts = [(e["t"], json.loads(e["body"])["doc"]) for e in lw if json.loads(e["body"])["id"] == "status"]
    # a write that carries a new early list goes out at once (the kick: right after a current with a changed list); the others are 5 s apart
    kicked, prev_y = set(), None
    for i_, e in enumerate(lw):
        j_ = json.loads(e["body"])
        if j_["id"] == "current":
            ny = json.dumps(j_["doc"].get("young"), sort_keys=True)
            if ny != prev_y and i_ + 1 < len(lw):
                kicked.add(lw[i_ + 1]["t"])
            prev_y = ny
    gaps = [round(b[0] - a[0], 1) for a, b in zip(sts, sts[1:-1]) if b[0] not in kicked]
    last = sts[-1][1] if sts else {}
    curd = (rest.live.get("current") or {}).get("doc") or {}
    off = json.load(open(os.path.join(d1, "db", "memebot", "office.json"), encoding="utf-8")) if os.path.exists(os.path.join(d1, "db", "memebot", "office.json")) else {}
    check(r.returncode == 0 and "live view: the app's live store gets it every 5 s" in r.stderr and len(sts) >= 2 and sts[0][0] - t_ < 6 and all(g >= 4.5 for g in gaps)
          and sts[0][1].get("live") is True and last.get("live") is False and last.get("t") == off.get("t") and {a["id"] for a in last.get("agents") or []} == {a["id"] for a in off.get("agents") or []}
          and curd.get("live") is False and curd.get("pick", {}).get("sym") and last.get("pick", {}).get("sym") == curd["pick"]["sym"],
          "a live cycle writes status about every 5 s (first after %.1f s, gaps %s s, and %d writes at once for a new early list), the last one live false with the"
          " office's agents; current carries the pick" % ((sts[0][0] - t_) if sts else -1, gaps, len(kicked)))
    picks = [g for g in sink.got[g0:] if '"tag":"pick"' in g["data"]]
    rec_doc = json.load(open(os.path.join(d1, "db", "memebot", "recommend.json"), encoding="utf-8")) if os.path.exists(os.path.join(d1, "db", "memebot", "recommend.json")) else {}
    sym = ((rec_doc.get("picks") or [{}])[0]).get("sym")
    check(sym and [g["name"] for g in picks].count("both") == 1 and ("New pick: %s" % sym) in picks[0]["data"] and "push: pick sent to" in r.stderr,
          "the pick notification goes out once after the trader step (%s)" % sym)
    code = ("import bot, app\nd = %r\nbot.OFFICE = bot.Office(d, 4242, '2h'); bot.OFFICE.begin('scouts')\n" % os.path.join(tmp, "hook") +
            "app.prepare = lambda: time.sleep(9)\n"          # a slow store while the VAPID keys are made: the status writes must not wait for it
            "os.makedirs(d, exist_ok=True)\nlive = bot.Live(d, None, app)\ntime.sleep(2.6)\n"
            "y1 = {'v': 1, 't': 4242, 'state': 'listed', 'coins': [{'sym': 'NEW1', 'ageMin': 3}, {'sym': 'NEW2', 'ageMin': 8}]}\n"
            "bot.live_put('young', y1)\ntime.sleep(5.5)\n"
            "bot.live_put('young', dict(y1, rc='done'))\ntime.sleep(5.5)\n"
            "again = bot.young_published(y1)\n"
            "for t in list(bot.APP_JOBS): t.join(20)\n"
            "slow = app.sink\napp.sink = lambda rec, now=None: (time.sleep(30), slow(rec))[1]\n"
            "t0 = time.time(); live.finish(time.time() + 2); took = time.time() - t0\n"
            "print(json.dumps({'again': again, 'took': took}))\n")
    n0, g0 = len(rest.log), len(sink.got)
    p, out = drive(code, env_app)
    seen_out.append(p.stdout + p.stderr)
    ys = [g for g in sink.got[g0:] if '"tag":"young"' in g["data"]]
    stw = [json.loads(e["body"])["doc"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "status"]
    stt = [e["t"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "status"]
    gaps = [round(b - a, 1) for a, b in zip(stt, stt[1:3])]
    check(len(gaps) == 2 and max(gaps) < 6.6, "the VAPID keys are made on a thread of their own: a slow store there does not hold up the status writes (gaps %s s)" % gaps)
    check(out and out["again"] is False and out["took"] < 4 and [g["name"] for g in ys].count("both") == 1 and '"title":"2 new coins listed"' in ys[0]["data"] and "The newest is 3 min old. On the list: NEW1, NEW2, all under an hour old" in ys[0]["data"]
          and any((s.get("young") or {}).get("n") == 2 for s in stw) and ((rest.live.get("current") or {}).get("doc") or {}).get("young", {}).get("rc") == "done",
          "hooks: live_put('young', doc) reaches both rows within seconds, its first listing sends one 'new coins' notification (a second version and "
          "young_published again send none); the end waits for a hung store %.1f s, not more" % (out or {}).get("took", -1))
    # 5a. the early list's way to the app: the file watcher has a thread of its own (a hung git push never holds up the app's copy), the app's
    # rows take a new list at once (the kick), the "new coins" notification waits for them, and the end cuts a slow write short
    import socket as so_
    hang = so_.socket()
    hang.bind(("127.0.0.1", 0))
    hang.listen(16)
    held_conns = []

    def accept_all():
        try:
            while True:
                held_conns.append(hang.accept())
        except OSError:
            pass
    threading.Thread(target=accept_all, daemon=True).start()
    early_code = ("import bot, app\nd, remote = %r, %r\nos.makedirs(d, exist_ok=True)\nbot.OFFICE = bot.Office(d, 4343, '2h'); bot.OFFICE.begin('scouts')\n"
                  "bot.EARLY.update(t=4343, doc=None, sig=None)\napp.prepare = lambda: None\n"
                  "def w(doc):\n    json.dump(doc, open(d + '/young_early.json.tmp', 'w'))\n    os.replace(d + '/young_early.json.tmp', d + '/young_early.json')\n"
                  "live = bot.Live(d, remote, app)\ntime.sleep(1.5)\n"
                  "y = {'v': 1, 't': 4343, 'state': 'listed', 'rcState': 'pending', 'coins': [{'addr': 'A' * 44, 'sym': 'HANG1', 'ageMin': 4}]}\n"
                  "w(y); t1 = time.time(); time.sleep(4)\nw(dict(y, rcState='done')); t2 = time.time(); time.sleep(4)\n"
                  "for t in list(bot.APP_JOBS): t.join(15)\nlive.finish(time.time() + 2)\nprint(json.dumps({'t1': t1, 't2': t2}))\n")
    n0, g0 = len(rest.log), len(sink.got)
    p, out = drive(early_code % (os.path.join(tmp, "hang"), "http://127.0.0.1:%d/live.git" % hang.getsockname()[1]), env_app)
    seen_out.append(p.stdout + p.stderr)
    curw = [(e["t"], (json.loads(e["body"])["doc"].get("young") or {}).get("rcState")) for e in rest.log[n0:]
            if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "current"]
    lag1 = min([t_ for t_, rs in curw if rs == "pending"] or [1e12]) - (out or {}).get("t1", 0)
    lag2 = min([t_ for t_, rs in curw if rs == "done"] or [1e12]) - (out or {}).get("t2", 0)
    check(out and 0 <= lag1 < 3 and 0 <= lag2 < 3 and len(held_conns) >= 1,
          "a git push that hangs (a remote that never answers) holds up neither the early list's watcher nor the app's rows: both versions reach the row current"
          " %.1f s and %.1f s after the file was written" % (lag1, lag2))
    hang.close()
    bare_n = tempfile.mkdtemp(prefix="memebot-app-bare-n-")
    subprocess.run(["git", "init", "-q", "--bare", bare_n], check=True)
    rest.mode = "slowpost1.5"
    n0, g0 = len(rest.log), len(sink.got)
    p, out = drive(early_code % (os.path.join(tmp, "order"), bare_n), env_app)
    rest.mode = "ok"
    seen_out.append(p.stdout + p.stderr)
    cur_y = min([e["t"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "current"
                 and (json.loads(e["body"])["doc"].get("young") or {}).get("coins")] or [1e12])
    ys_n = [g for g in sink.got[g0:] if '"tag":"young"' in g["data"] and g["name"] == "both"]
    lj_n = git_live(bare_n)
    check(out and len(ys_n) == 1 and ys_n[0]["t"] >= cur_y and (lj_n.get("young") or {}).get("coins"),
          "the new coins notification goes out once the app's own row current has the list (%.1f s after it), not when the faster git push has it: a tap finds"
          " the list in the app" % ((ys_n[0]["t"] - cur_y) if ys_n and cur_y < 1e12 else -1))
    shutil.rmtree(bare_n, ignore_errors=True)
    rest.mode = "slow3.5"
    n0 = len(rest.log)
    p, out = drive("import bot, app\nd = %r\nos.makedirs(d, exist_ok=True)\nbot.OFFICE = bot.Office(d, 5151, '2h'); bot.OFFICE.begin('scouts')\n" % os.path.join(tmp, "slowend") +
                   "app.prepare = lambda: None\nlive = bot.Live(d, None, app)\ntime.sleep(4)\n"
                   "t0 = time.time(); live.finish(time.time() + 20); took = time.time() - t0\nprint(json.dumps({'took': took}))\n", env_app)
    rest.mode = "ok"
    seen_out.append(p.stdout + p.stderr)
    stl = [json.loads(e["body"])["doc"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "status"]
    check(out and out["took"] < 10 and stl and stl[-1].get("live") is False and stl[-1].get("t") == 5151 and not any(x_.get("live") is True for x_ in stl)
          and "failed" not in p.stderr,
          "a store that takes 3.5 s a request: the end cuts the write on its way short (its status is never sent) and the last status (live false) is in"
          " within %.1f s (without the cut about 16 s; a store at 8 s a request would miss the 20 s end window)" % (out or {}).get("took", -1))
    # the child processes (fetch.py, memebot.py, radar.py, git) never get the secret key: only bot.py itself (app.py, imported) uses it
    envd = os.path.join(tmp, "envchild")
    os.makedirs(envd)
    with open(os.path.join(envd, "envcheck.py"), "w") as f:
        f.write("import os, json\nprint(json.dumps({'secret': 'SUPABASE_SECRET_KEY' in os.environ, 'url': 'SUPABASE_URL' in os.environ}))\n")
    p, out = drive("import bot\nbot.HERE = %r\na = bot.run(['envcheck.py'], %r)\njob = bot.start_bg(['envcheck.py'], %r, agent='candles')\n"
                   "b = bot.finish_bg(job)\nprint(json.dumps([a, b, sorted(bot.child_env(X='1'))]))\n" % (envd, envd, envd), env_app)
    src_b = open(os.path.join(HERE, "bot.py"), encoding="utf-8").read()
    n_sub = len(re.findall(r"subprocess\.(?:run|Popen)\(", src_b))
    check(out and out[:2] == [{"secret": False, "url": True}] * 2 and "SUPABASE_SECRET_KEY" not in out[2] and "X" in out[2] and "dict(os.environ" not in src_b
          and n_sub == 6 and src_b.count("env=child_env(") + src_b.count("env=env)") == n_sub,
          "child processes get the environment without SUPABASE_SECRET_KEY (run, start_bg, git: all %d subprocess calls of bot.py use child_env)" % n_sub)
    # a launch spotter that ends by itself without a list (it crashed at its start) leaves a failed list, so the early box does not wait all scan
    p, out = drive("import bot, subprocess\nd = %r\nos.makedirs(d, exist_ok=True)\nbot.OFFICE = o = bot.Office(d, 6161, '2h')\n" % os.path.join(tmp, "spotcrash") +
                   "bot.EARLY.update(t=6161, doc=None, sig=None)\nopen(d + '/x.out', 'w').close()\no.begin('spotter', bg=True)\n"
                   "p = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(1)'])\np.wait()\n"
                   "job = {'p': p, 'out': open(d + '/x.out'), 'end': 1}\nbot.spot_done(o, job, 6161)\na = bot.EARLY['doc']\n"
                   "bot.EARLY.update(t=6162, doc={'v': 1, 't': 6162, 'state': 'listed', 'coins': []}, sig=None)\nbot.spot_done(o, job, 6162)\nb = bot.EARLY['doc']['state']\n"
                   "print(json.dumps([a, b, [x.get('status') for x in o.doc()['agents'] if x.get('id') == 'spotter']]))\n", base)
    check(out and (out[0] or {}).get("state") == "failed" and (out[0] or {}).get("t") == 6161 and "stopped without a list (exit 1)" in (out[0] or {}).get("why", "")
          and out[1] == "listed" and out[2] == ["failed"],
          "a launch spotter that exits by itself without a list of this scan (a crash at its start) leaves a failed early list for both live views: the box says"
          " why instead of waiting all scan (%s); a list already taken stays" % ((out or [{}])[0] or {}).get("why"))
    check(src_b.count("APP_FIRST, APP_EVERY, APP_BEAT =") == 1 and src_b.count("YOUNG_SENT = {") == 1 and src_b.count("APP_JOBS = []") == 1,
          "bot.py defines its live-view constants once (no merge leftover)")

    code = ("import bot\ny = {'v': 1, 't': 1, 'state': 'listed', 'coins': [{'sym': 'A'}]}\nok = bot.live_put('young', y)\n"
            "y['coins'].append({'sym': 'B'}); y['state'] = 'changed'\nsig, rec = bot.live_record(True)\n"
            "loop = {}; loop['me'] = loop\nbad = bot.live_put('x', loop)\n"
            "nan = bot.live_put('n', {'px': float('nan')}); inf = bot.live_put('i', [float('inf')]); obj = bot.live_put('o', {'when': time})\n"
            "rec2 = bot.live_record(True)[1]\n"
            "print(json.dumps([ok, rec['young'], bad, 'x' in rec2, nan, inf, obj, [k for k in ('n', 'i', 'o') if k in rec2]]))\n")
    p, out = drive(code, base)
    check(out == [True, {"v": 1, "t": 1, "state": "listed", "coins": [{"sym": "A"}]}, False, False, False, False, False, []],
          "live_put keeps a copy: the caller may change its own dict afterwards; a value that is not strict JSON (a loop, NaN, infinity, an object JSON cannot hold) "
          "is left out, never written as a string (%s)" % (out if out is not None else p.stderr[-200:]))

    # 5b. the launch spotter's early list through both live views and the "new coins" notification (radar.py and app.py together)
    cur_e, yf, nv_e = {}, {}, 0
    if has_crypto:
        de, bare_e = os.path.join(tmp, "early"), tempfile.mkdtemp(prefix="memebot-app-early-")
        subprocess.run(["git", "init", "-q", "--bare", bare_e], check=True)
        n0, g0 = len(rest.log), len(sink.got)
        env_e = {k: v for k, v in env_app.items() if k not in ("MEMEBOT_PAUSE",)}
        p, _, _ = spot_cycle(de, env=dict(env_e, MEMEBOT_EARLY_RC_S="8"), remote=bare_e)
        seen_out.append(p.stdout + p.stderr)
        import bot as B_
        yf = B_.early_doc(os.path.join(de, "young_early.json"), T0) or {}
        lj = git_live(bare_e)
        cur_e = ((rest.live.get("current") or {}).get("doc") or {})
        sts_e = [json.loads(e["body"])["doc"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "status"]
        curs_e = [json.loads(e["body"])["doc"] for e in rest.log[n0:] if e["m"] == "POST" and e["p"] == "/rest/v1/live" and json.loads(e["body"])["id"] == "current"]
        addrs = [c["addr"] for c in yf.get("coins") or []]
        ys_e = [json.loads(g["data"]) for g in sink.got[g0:] if '"tag":"young"' in g["data"] and g["name"] == "both"]
        nv_e = len({s_.get("nver") for s_ in sts_e if s_.get("nver") is not None})        # the reads of current a page makes during this scan
        first = next((c.get("young") for c in curs_e if isinstance(c.get("young"), dict) and c["young"].get("state") == "listed"), None) or {}
        n1 = len(first.get("coins") or [])
        newest = min([c["ageMin"] for c in first.get("coins") or [] if isinstance(c.get("ageMin"), int)] or [-1])
        yn = (ys_e[0].get("notification") or {}) if ys_e else {}
        check(p.returncode == 0 and yf.get("state") == "listed" and len(addrs) >= 2 and [c["addr"] for c in (lj.get("young") or {}).get("coins") or []] == addrs
              and [c["addr"] for c in (cur_e.get("young") or {}).get("coins") or []] == addrs and cur_e.get("young") == lj.get("young") == yf
              and any((s_.get("young") or {}).get("n") == len(addrs) and (s_.get("young") or {}).get("state") == "listed" for s_ in sts_e),
              "the launch spotter's early list reaches both live views through live_put('young', doc): live.json and the live store's row current carry the same "
              "list as young_early.json (%d coins, RugCheck %s), row status its count" % (len(addrs), yf.get("rcState")))
        check(len(ys_e) == 1 and n1 >= 1 and yn.get("title") == "%d new coin%s listed" % (n1, "" if n1 == 1 else "s") and newest >= 0
              and yn.get("body", "").startswith("The newest is %d min old. On the list: " % newest) and "Fake money only, nothing is bought for real." in yn.get("body", "")
              and yn.get("navigate", "").endswith("/Meme-Bot/#tab-young") and "push: young sent to" in p.stderr,
              "young_published sends the new coins notification once per scan when the first listed early list is out (%r, %r), opening the New coins tab" % (
                  yn.get("title"), yn.get("body", "")[:60]))
        seen_out.append(json.dumps(lj))
        shutil.rmtree(bare_e, ignore_errors=True)

    # 6. the site: the publishable-key guard, sw.js, the manifest id, the opaque apple-touch-icon
    sd = os.path.join(tmp, "site")
    guard = []
    jwt = lambda role: "eyJhbGciOiJIUzI1NiJ9." + b64u(json.dumps({"role": role, "iss": "supabase"}).encode()) + ".c2ln"
    for key, u, want, said in (("sb_publishable_OKkey_1234567890", "https://abcref.supabase.co", True, "app live store on"),
                               (APP_SECRET, "https://abcref.supabase.co", False, "NOT put in the page: it is a SECRET key"),
                               (jwt("service_role"), "https://abcref.supabase.co", False, "a JWT with the role service_role"),
                               (jwt("anon"), "https://abcref.supabase.co", False, "a legacy anon key"),
                               ("sb_publishable_OKkey_1234567890", "http://abcref.supabase.co", False, "SUPABASE_URL is not an address like https://<ref>.supabase.co"),
                               ("sb_publishable_OKkey_1234567890", "", False, "SUPABASE_URL is missing"),
                               ("sb_publishable_OKkey_1234567890" + APP_SECRET, "https://abcref.supabase.co", False, "it holds a SECRET key"),   # both keys pasted into one secret
                               ("sb_publishable_OKkey_1234567890" + jwt("service_role").replace(".", ""), "https://abcref.supabase.co", False, "it holds a JWT besides the key"),
                               ("sb_publishable_" + "k" * 70, "https://abcref.supabase.co", False, "longer than a publishable key")):
        shutil.rmtree(sd, ignore_errors=True)
        r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", d1, "--out", sd, "--repo", "https://github.com/maxpandelakis-boop/Meme-Bot"], capture_output=True, text=True,
                           env=dict(base, SUPABASE_URL=u, SUPABASE_PUBLISHABLE_KEY=key, SUPABASE_SECRET_KEY=APP_SECRET))
        seen_out.append(r.stdout + r.stderr)
        idx = open(os.path.join(sd, "index.html"), encoding="utf-8").read() if os.path.exists(os.path.join(sd, "index.html")) else ""
        has = ('data-sb-url="%s" data-sb-key="%s"' % (u, key)) in idx
        guard.append(r.returncode == 0 and has == want and said in r.stderr and (want or ("data-sb-url" not in idx.split("<head>")[0] and key not in idx and key not in r.stderr)))
        if want:
            files = sorted(os.listdir(sd))
            man = json.load(open(os.path.join(sd, "manifest.webmanifest"), encoding="utf-8"))
            sw = open(os.path.join(sd, "sw.js"), encoding="utf-8").read()
            png = open(os.path.join(sd, "icon-180.png"), "rb").read()
            import zlib
            raw = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
            alphas = {raw[i * (180 * 4 + 1) + 1 + x * 4 + 3] for i in range(180) for x in range(180)}
            app_ok = (man.get("id") == "/Meme-Bot/" and man.get("scope") == "./" and "sw.js" in files and "self.addEventListener('push'" in sw and alphas == {255}
                      and '<link rel="apple-touch-icon" sizes="180x180" href="icon-180.png">' in idx and 'http-equiv="refresh"' not in idx and "window.MemebotApp" in idx
                      and "html.app .tabbar" in idx and 'data-app="account"' in idx)
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", d1, "--out", sd, "--repo", "https://github.com/someone/other-repo"], capture_output=True, text=True, env=base)
    man2 = json.load(open(os.path.join(sd, "manifest.webmanifest"), encoding="utf-8")) if r.returncode == 0 else {}
    idx2 = open(os.path.join(sd, "index.html"), encoding="utf-8").read() if r.returncode == 0 else "data-sb-url="
    check('<html lang="en">' in idx2 and 'data-sb-url="' not in idx2 and "app live store off" in r.stderr and "app's live store stays off" not in r.stderr,
          "site without the Supabase variables: no live store in the page, nothing said about it but 'off'")
    import app as A_g
    unit = [A_g.page_key_verdict(k_, secret=sec_)[0] for k_, sec_ in (("sb_publishable_abcdefgh_sb_secret_zzzzzzzz", ""), ("sb_publishable_abcdefghSECRETVALUE1", "SECRETVALUE1"),
                                                                     ("sb_publishable_OKkey_1234567890", "SECRETVALUE1"), ("sb_publishable_" + "k" * 65, ""), ("sb_publishable_" + "k" * 66, ""))]
    check(guard == [True] * 9 and unit == ["refused", "refused", "ok", "ok", "refused"],
          ("%s %s " % (guard, unit) if not all(guard) else "") + "site: only a publishable key (sb_publishable_, at most 80 characters) goes into the page; a secret key, a service_role or anon JWT,"
          " an http address are refused, and so is a publishable key with a secret key, the secret key's value or a JWT stuck to it; the log says why without the key")
    check(app_ok and man2.get("id") == "/other-repo/", "site: sw.js beside index.html, manifest id /Meme-Bot/ (the repository's folder), an opaque apple-touch-icon, no meta refresh, the app's script and style")

    # 6b. the installed app in Chromium: the live store feeds the office view and the early box on the New coins tab, the tab badge follows the list
    if has_crypto and yf.get("coins"):
        sd2 = os.path.join(tmp, "site-app")
        r1 = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", de, "--out", os.path.join(de, "report.html"), "--now", str(T0)], capture_output=True, text=True,
                            env=dict(base, GITHUB_REPOSITORY="maxpandelakis-boop/Meme-Bot"))
        r2 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "site", "--dir", de, "--out", sd2, "--repo", "https://github.com/maxpandelakis-boop/Meme-Bot"], capture_output=True, text=True,
                            env=dict(base, SUPABASE_URL="https://abcref.supabase.co", SUPABASE_PUBLISHABLE_KEY="sb_publishable_OKkey_1234567890", SUPABASE_SECRET_KEY=APP_SECRET))
        seen_out += [r1.stdout + r1.stderr, r2.stdout + r2.stderr]
        if r1.returncode == 0 and r2.returncode == 0:
            app_browser_checks(check, sd2, yf)
        else:
            check(False, "the installed app's page could not be built: %s %s" % (r1.stderr[-200:], r2.stderr[-200:]))

    # 7. the secret key (and the VAPID private key) never in any output, file, page or the live branch
    priv = rest.secret.get("vapid_private_key") or "no-private-key-made"
    blobs = list(seen_out)
    for root_ in (tmp, bare):
        for dp, dn, fn in os.walk(root_):
            for n in fn:
                try:
                    blobs.append(open(os.path.join(dp, n), "rb").read().decode("utf-8", "replace"))
                except OSError:
                    pass
    blobs.append(subprocess.run(["git", "-C", bare, "show", "live:live.json"], capture_output=True, text=True).stdout)
    check(len(blobs) > 50 and not any(APP_SECRET in b or priv in b for b in blobs) and "live" in subprocess.run(["git", "-C", bare, "branch", "--list"], capture_output=True, text=True).stdout,
          "the secret key and the VAPID private key are in no output, no file of the run folders, no page and not on the branch live (%d outputs and files read)" % len(blobs))

    # 8. the page's decisions and sw.js in node
    node = shutil.which("node")
    if node:
        import report as R_
        import app as A_
        jd = os.path.join(tmp, "js")
        os.makedirs(jd)
        with open(os.path.join(jd, "page.js"), "w", encoding="utf-8") as f:
            f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;}};global.navigator={};\n" + R_.OFFICE_LIVE_JS + A_.PAGE_JS + r"""
var MB=window.MemebotLive,A=window.MemebotApp,o={};
var U='https://abcdefghijklmnopqrst.supabase.co',K='sb_publishable_AbC_12-3';
o.transport=[MB.transport(U,K,'gh'),MB.transport(U+'/',K,''),MB.transport(U,'sb_secret_x','gh'),MB.transport(U,'eyJx.y.z','gh'),MB.transport('http://x.supabase.co',K,'gh'),
  MB.transport('https://x.supabase.co/rest/v1',K,'gh'),MB.transport('',K,''),MB.transport(U,K+'"><script>','gh')];
o.fallback=[MB.fallback(200,0),MB.fallback(540,1),MB.fallback(0,1),MB.fallback(0,2),MB.fallback(500,1),MB.fallback(401,2),MB.fallback(404,3)];
var T0=1e12,LV={live:true,updated:T0-2000,t:5,agents:[]},OLD={live:true,updated:T0-MB.STALE-1,t:5,agents:[]},END={live:false,updated:T0-2000,t:5,agents:[]};
o.sbNext=[MB.sbNext(T0,0,LV)-T0,MB.sbNext(T0,1,LV)-T0,MB.sbNext(T0,2,LV)-T0,MB.sbNext(T0,9,LV)-T0,MB.sbNext(T0,0,END)-T0,MB.sbNext(T0,0,OLD)-T0,MB.sbNext(T0,0,null)-T0,
  MB.sbNext(T0,1,END)-T0,MB.sbNext(T0,9,END)-T0];
var ST={t:5,live:true,ver:9,agents:[{id:'a'}],young:{n:2,newest:3,state:'listed'},pick:{sym:'P',t:5,score:70}},
  CUR={t:5,ver:9,agents:[],young:{t:5,state:'listed',coins:[{sym:'A'},{sym:'B'}]},pick:{t:5,sym:'P',name:'Pe',score:70,tier:'strong'}};
var m1=MB.merge(ST,CUR),m2=MB.merge(ST,{t:4,young:{coins:[{sym:'OLD'}]},pick:{sym:'OLD',t:4}}),m3=MB.merge(ST,null);
o.merge=[m1.young.coins.length,m1.pick.name,m1.agents.length,m1.ver,m2.young,m2.pick.sym,m3.young,ST.young.n,MB.merge(null,CUR)];
var mm=function(hit){return function(q){return {matches:hit&&q.indexOf('display-mode: '+hit)>=0};};};
o.installed=[A.installed({standalone:true},null),A.installed({standalone:false},mm(null)),A.installed({},mm('fullscreen')),A.installed({},mm('standalone')),
  A.installed({},function(){throw new Error('x');}),A.installed({},null)];
var B={sw:true,push:true,notif:true,store:true,key:'k',perm:'default',sub:null,saved:false,error:''},S=function(o2){return A.pushState(Object.assign({},B,o2));};
o.push=[S({}),S({sub:{},saved:true}),S({perm:'denied'}),S({push:false}),S({sw:false}),S({notif:false}),S({store:false}),S({key:null}),S({error:'x'}),S({sub:{},saved:false,error:'x'}),A.pushState(null),
  S({sub:{},saved:false,perm:'granted'}),S({sub:{},saved:false,perm:'granted',error:'x'}),S({sub:{},saved:false,perm:'default'})];
o.count=[A.count({coins:[{sym:'A'},{sym:'B'},null]}),A.count({n:6,newest:4}),A.count({state:'listed'}),A.count(null),A.count({coins:[]})];
var Y3={coins:[{sym:'A'},{sym:'B'},{sym:'C'}]};o.badge=['listed','partial','paused','limited','done','stopped','wait','own','hide','empty','none','late',undefined].map(function(e){return A.badge(e,Y3);}).concat([A.badge('listed',null)]);
o.pick=[A.pick({pick:{sym:'S',t:9}},{pick:{sym:'C',t:9}},5).sym,A.pick({pick:null},{pick:{sym:'C',t:9}},5).sym,A.pick({pick:{sym:'S',t:4}},{pick:{sym:'C',t:3}},5),A.pick(null,null,5),
  A.pick({pick:{sym:'',t:9}},null,5)];
o.tab=[A.tab('#tab-young'),A.tab('tab-account'),A.tab('#tab-pick'),A.tab('#tab-x'),A.tab('#pane-young'),A.tab('')];
o.store=[!!A.store(U,K),!!A.store(U,'sb_secret_x'),!!A.store('http://x.co',K)];
console.log(JSON.stringify(o));
""")
        r = subprocess.run([node, os.path.join(jd, "page.js")], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout)
        except ValueError:
            o = {"err": r.stderr[-400:]}
        check(o.get("transport") == ["supabase", "supabase", "github", "github", "github", "github", "none", "github"]
              and o.get("fallback") == ["supabase", "github", "supabase", "github", "supabase", "github", "github"],
              "the page's transport (node): the live store with an https address and a publishable key, else the GitHub poll; a 540 falls back at once, other "
              "failures (network, CORS: no status) after two in a row %s" % ({k: o.get(k) for k in ("transport", "fallback")} if "transport" in o else o))
        # the free plan's 5 GB of egress a month, for one page left open and visible all day with a scan live 41 minutes of every hour (scan.yml:
        # a full scan takes 32 to 41): the status row every 4 s while live and every 30 s otherwise, and the row current each time status names a
        # new nver (as often as this scan's run changed it, at least 6 times a scan), both at the sizes this run wrote, as JSON without compression
        st_b = max(2500, len(json.dumps([{"doc": (rest.live.get("status") or {}).get("doc") or {}}])))
        cur_b = max(12000, len(json.dumps([{"doc": cur_e}])) if cur_e else 21000)
        st_gb = 30 * (24 * 41 * 60 / 4 + 24 * 19 * 60 / 30) * st_b / 1e9
        cur_gb = 30 * 24 * max(6, nv_e) * cur_b / 1e9
        check(o.get("sbNext") == [4000, 8000, 16000, 30000, 30000, 30000, 30000, 60000, 120000] and st_gb + cur_gb < 2.0 and (nv_e <= 8 or not has_crypto),
              "the page polls the live store every 4 s only while a scan is live and fresh, every 30 s otherwise (a finished, stale or missing scan), longer after "
              "failures: one page left open all day with a scan live 41 minutes an hour reads about %.1f GB a month, %.1f GB of status rows (%d bytes) and %.2f GB"
              " of the row current (%d bytes, read %d times a scan: only when its early list or pick changed), inside the free plan's 5 GB %s" % (
                  st_gb + cur_gb, st_gb, st_b, cur_gb, cur_b, nv_e, o.get("sbNext")))
        check(o.get("merge") == [2, "Pe", 1, 9, None, "P", None, 2, None],
              "the page's snapshot from the live store is the status row with current's early list and pick of the same scan (live.json's shape), none of an older scan %s" % o.get("merge"))
        check(o.get("installed") == [True, False, True, True, False, False]
              and o.get("push") == ["off", "on", "denied", "unsupported", "unsupported", "unsupported", "nostore", "nokey", "error", "error", "unsupported", "on", "error", "off"]
              and o.get("tab") == ["young", "account", "pick", None, None, None] and o.get("store") == [True, False, False],
              "the installed app (node): navigator.standalone or a standalone/fullscreen display mode; the notifications control says off, on, denied, not supported, "
              "not set up, not ready or the error; deep links pick a tab %s" % ({k: o.get(k) for k in ("installed", "push")} if "push" in o else o))
        check(o.get("push", [None] * 14)[11:] == ["on", "error", "off"] and o.get("count") == [2, 6, None, None, 0] and o.get("pick") == ["S", "C", None, None, None]
              and o.get("badge") == [3, 3, 3, 3, 3, 3, None, None, None, None, None, None, None, None],
              "the installed app (node): a subscription that exists with the permission granted stays On when only the quiet save at the start failed (a failed tap is "
              "the error); the New coins count from the list's coins or the status brief, on the tab bar only while the early box shows that list (listed, partial, "
              "paused, limited, done, stopped), else no badge at all; the New pick note from the status row as soon as the notification, else current %s" % (
                  {k: o.get(k) for k in ("count", "pick", "badge")}))
        with open(os.path.join(jd, "sw.js"), "w", encoding="utf-8") as f:
            f.write(r"""
var H={},shown=[],posted=[],opened=[],focused=0,store={},deleted=[],netOK=true,wins=[];
global.self={location:new URL('https://maxpandelakis-boop.github.io/Meme-Bot/sw.js'),addEventListener:function(n,f){H[n]=f;},skipWaiting:function(){},
  registration:{showNotification:function(t,o){shown.push([t,o]);return Promise.resolve();}},
  clients:{claim:function(){return Promise.resolve();},matchAll:function(){return Promise.resolve(wins);},openWindow:function(u){opened.push(u);return Promise.resolve();}}};
global.caches={keys:function(){return Promise.resolve(['memebot-page-v0','memebot-page-v1','other-app']);},delete:function(k){deleted.push(k);return Promise.resolve(true);},
  open:function(){return Promise.resolve({put:function(k,r){return r.text().then(function(t){store[k]=t;});}});},
  match:function(k){return Promise.resolve(store[k]!==undefined?new Response(store[k]):undefined);}};
global.fetch=function(u){return netOK?Promise.resolve(new Response('<html lang="en"><body><div class="wrap">NEW</div></body></html>',{status:200})):Promise.reject(new TypeError('offline'));};
""" + A_.SW_JS + r"""
function ev(extra){var p=[];return Object.assign({waitUntil:function(x){p.push(x);},respondWith:function(x){p.push(x);this.res=x;},done:function(){return Promise.all(p);}},extra);}
function data(x){return {json:function(){return JSON.parse(x);},text:function(){return x;}};}
var o={};
(async function(){
  var e=ev({});H.activate(e);await e.done();o.deleted=deleted;
  var push=async function(d){var e=ev({data:d});H.push(e);await e.done();return shown[shown.length-1];};
  o.decl=await push(data(JSON.stringify({web_push:8030,notification:{title:'New pick: MOON1',body:'b',navigate:'https://maxpandelakis-boop.github.io/Meme-Bot/#tab-pick',lang:'en',tag:'pick'}})));
  o.outside=await push(data(JSON.stringify({web_push:8030,notification:{title:'T',navigate:'https://evil.example/#x'}})));
  o.text=await push(data('hello there'));o.none=await push(null);o.nul=await push(data('null'));
  var click=async function(url){var e=ev({notification:{data:{url:url},close:function(){}}});H.notificationclick(e);await e.done();};
  wins=[];await click('https://maxpandelakis-boop.github.io/Meme-Bot/#tab-young');o.opened=opened.slice();
  wins=[{url:'https://maxpandelakis-boop.github.io/Meme-Bot/',focus:function(){focused++;return Promise.resolve(this);},postMessage:function(m){posted.push(m);}}];
  await click('https://evil.example/');o.focused=focused;o.posted=posted;
  var nav=async function(url,mode){var e=ev({request:{url:url,method:'GET',mode:mode||'navigate'}});H.fetch(e);if(!e.res)return null;var r=await e.res;await new Promise(function(r){setTimeout(r,10);});return r?await r.text():'';};
  netOK=true;o.online=await nav('https://maxpandelakis-boop.github.io/Meme-Bot/?x=1');
  netOK=false;o.offline=await nav('https://maxpandelakis-boop.github.io/Meme-Bot/index.html');
  o.other=await nav('https://maxpandelakis-boop.github.io/Meme-Bot/icon-180.png','no-cors');o.otherPage=await nav('https://maxpandelakis-boop.github.io/Other/');
  console.log(JSON.stringify(o));
})().catch(function(e){console.log(JSON.stringify({err:String(e&&e.stack||e)}));});
""")
        r = subprocess.run([node, os.path.join(jd, "sw.js")], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout)
        except ValueError:
            o = {"err": r.stderr[-400:]}
        home = "https://maxpandelakis-boop.github.io/Meme-Bot/"
        check(o.get("deleted") == ["memebot-page-v0"] and o.get("decl", [None, {}])[0] == "New pick: MOON1" and o["decl"][1].get("data", {}).get("url") == home + "#tab-pick"
              and o["decl"][1].get("body") == "b" and o.get("outside", [None, {}])[1].get("data", {}).get("url") == home and o.get("text", [None, {}])[0] == "Meme-Bot"
              and o["text"][1].get("body") == "hello there" and o.get("none", [None])[0] == "Meme-Bot" and o.get("nul", [None])[0] == "Meme-Bot",
              "sw.js (node): every push shows a notification (declarative JSON, plain text, no data, null), its link stays inside /Meme-Bot/; old caches go %s" % (o.get("err") or ""))
        check(o.get("opened") == [home + "#tab-young"] and o.get("focused") == 1 and o.get("posted") == [{"type": "memebot-open", "url": home}]
              and "NEW" in (o.get("online") or "") and 'data-offline="1"' in (o.get("offline") or "") and "Offline." in (o.get("offline") or "") and "not the current one" in (o.get("offline") or "")
              and o.get("other") is None and o.get("otherPage") is None,
              "sw.js (node): a tap opens the app at the link or brings the open app forward and tells it the tab; the page comes from the network, offline the last copy marked as not current")
    else:
        SKIPS.append("the page's decisions in node (no node)")
        print("  SKIP the page's decisions and sw.js in node: node not found")

    # 9a. links stay inside the website; the push library comes after the standard library; the pinned install; setup.sql's guards
    code = ("import app\nh = app.site_url()\nus = ['#tab-young', h + '../evil/', h + '%2e%2e/evil/', h + '%2E%2e/x', h + 'a/./b', h + '..%5cevil', h + 'x\\\\..\\\\y',\n"
            "      'https://evil.example/', 'javascript:alert(1)', '//evil.example/x', h + 'a..b/#tab-x']\nprint(json.dumps([app.in_scope(u) for u in us]))\n")
    p, out = drive(code, base)
    home = "https://maxpandelakis-boop.github.io/Meme-Bot/"
    check(out == [home + "#tab-young"] + [home] * 9 + [home + "a..b/#tab-x"],
          "notification links: a dot segment (.., ., %%2e), a backslash or another site always opens the website itself (%s)" % (out if out is not None else p.stderr[-200:]))
    lib = os.path.join(tmp, "pushlib")
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, "textwrap.py"), "w") as f:
        f.write("raise ImportError('a push library must never shadow the standard library')\n")
    code = ("import sysconfig, app\napp._push_path()\nimport textwrap\nlib = os.environ['MEMEBOT_PUSH_LIB']\ni = sys.path.index(lib)\n"
            "std = [k for k, p_ in enumerate(sys.path) if p_ and os.path.realpath(p_).startswith(os.path.realpath(sysconfig.get_paths()['stdlib']))]\n"
            "import site as S\nsd = {os.path.realpath(x) for x in S.getsitepackages() + [S.getusersitepackages()]}\n"
            "site = [k for k, p_ in enumerate(sys.path) if p_ and os.path.realpath(p_) in sd]\n"
            "print(json.dumps([textwrap.__file__.startswith(os.path.dirname(os.__file__)), i > max(std), all(i < k for k in site if sys.path[k] != lib)]))\n")
    p, out = drive(code, dict(base, MEMEBOT_PUSH_LIB=lib))
    check(out == [True, True, True], "the push library (MEMEBOT_PUSH_LIB) goes right after the standard library: it shadows no standard module and its pinned versions "
          "come before the system's site-packages %s" % (out if out is not None else p.stderr[-200:]))
    wf = open(os.path.join(HERE, ".github", "workflows", "scan.yml"), encoding="utf-8").read()
    step = wf[wf.index("- name: Install the push sender"):wf.index("- name: Scan and recommend")]
    reqf = open(os.path.join(HERE, "supabase", "push-requirements.txt"), encoding="utf-8").read()
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==([^ \n]+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\\n)?)+)", reqf, re.M)
    reqs = [l for l in reqf.splitlines() if l and not l.startswith(("#", " "))]
    ece = re.search(r"http_ece-1\.2\.1\.tar\.gz\s+sha256 ([0-9a-f]{64})", reqf)
    check(all(x in step for x in ("--require-hashes", "--only-binary=:all:", "--no-deps", "-r supabase/push-requirements.txt", "RESULTS_URL: ''", "sha256sum -c", "app._push_path()"))
          and "pip install $opts \"pywebpush" not in step and len(pins) == len(reqs) >= 15 and ("pywebpush", "2.5.0") in [(n, v) for n, v, _ in pins]
          and {"cryptography", "requests", "aiohttp", "py-vapid", "urllib3"} <= {n for n, _, _ in pins} and ece and ece.group(1) in step,
          "the push sender is installed from supabase/push-requirements.txt only: %d packages, each pinned with sha256 hashes, wheels only, no other dependency; "
          "http-ece's sdist checked against its sha256; the GitHub token is not in that step" % len(pins))
    sql = open(os.path.join(HERE, "supabase", "setup.sql"), encoding="utf-8").read()
    check("order by (delivered is not null) desc, seen desc, created desc" in sql and "order by seen asc" not in sql and "interval '1 hour') >= 6" in sql
          and "~ '^B[A-Za-z0-9_-]{86}=?$'" in sql and "~ '^[A-Za-z0-9_-]{22}(==)?$'" in sql
          and re.search(r"if not found then\s+perform pg_advisory_xact_lock\(7316001\);", sql)
          and not os.path.exists(os.path.join(HERE, "supabase", "migrations")) and not os.path.exists(os.path.join(HERE, "supabase", "config.toml")),
          "setup.sql: the 25-row cap keeps rows a notification reached first, then the ones seen most recently (the phone); at most 6 new subscriptions an hour, one at"
          " a time under an advisory lock; keys must look like a P-256 key and 16 bytes; no supabase/migrations and no supabase/config.toml, so Supabase's GitHub"
          " integration applies nothing by itself (the SQL is pasted into the SQL Editor)")
    pj = __import__("app").PAGE_JS
    check("iOS said no" not in pj and "from another browser" in pj and "These two apply once notifications are on." in pj and "applicationServerKey" in pj
          and "select(t,'keep')" in pj and "A.badge(d.early,d.young)" in pj and "visibilitychange',back" in pj and "The app refreshes when you come back to it" in pj
          and "\u2014" not in pj and "Add to Home Screen from Safari first" not in pj,
          "the installed app's texts and habits: neutral subscribe errors, the right advice when push is missing, the switches marked as for later while off, "
          "each tab keeps its scroll position, the subscription's own key compared, the live count only with the live list, no reload promise the app does not keep")
    import report as R_h
    check("A.hold=function(){return !!P.busy||cur==='account';}" in pj and "MemebotApp.hold()" in R_h.OFFICE_LIVE_JS and "&&!hold){" in R_h.OFFICE_LIVE_JS
          and "baseCnt" not in pj and ".live .btn { margin-left:auto; display:inline-flex; align-items:center; min-height:44px;" in R_h.CSS
          and "aria-label',NAMES[t]+(c?', '+c.textContent+' listed now':'')+(d?', a scan is running now':'')" in pj,
          "the installed app is not reloaded under a tap: never while on Account or while the notifications card is at work (it reloads at the next answer"
          " after); the New coins badge only with a scan's early list; Scan now 44 px tall; the tabs' badge and dot read out in words")

    # 9. supabase/setup.sql on PostgreSQL (MEMEBOT_PG=<host or socket folder>:<port>)
    pg = os.environ.get("MEMEBOT_PG")
    if pg and ":" in pg:
        h_, port_ = pg.rsplit(":", 1)
        r = subprocess.run([PY, os.path.join(HERE, "supabase", "test_setup.py"), h_, port_], capture_output=True, text=True, timeout=300)
        n_ok = r.stdout.count("  PASS ")
        check(r.returncode == 0 and "SQL ALL PASS" in r.stdout, "supabase/setup.sql on PostgreSQL: %d checks (anon reads live and app_config, uses only save_push_sub and drop_push_sub, "
              "never reads push_subs or app_secret, never writes live; idempotent; upgrades the first version) %s" % (n_ok, "" if r.returncode == 0 else r.stdout[-600:]))
    else:
        SKIPS.append("setup.sql on PostgreSQL (no MEMEBOT_PG)")
        print("  SKIP supabase/setup.sql on PostgreSQL: set MEMEBOT_PG=<host or socket folder>:<port> to run supabase/test_setup.py")
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(bare, ignore_errors=True)


def main():
    mock = Mock()
    srv = serve(mock)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    d = tempfile.mkdtemp(prefix="memebot-test-")
    os.environ["LUNARCRUSH_API_KEY"] = "test"
    os.environ["BITQUERY_TOKEN"] = "test"
    for k in ("MEMEBOT_LIVE", "RESULTS_URL", "GITHUB_REPOSITORY", "SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY", "MEMEBOT_PUSH_LIB", "MEMEBOT_SITE_URL"):
        os.environ.pop(k, None)     # the test never pushes a live view or writes to a live store, and its pages are built as on a laptop
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)

    spot_modes = []          # each cycle's scan (full, light, none) and whether a launch spotter ran in it: never without --recommend

    def cycle(now, force=False, rescan=False):
        cmd = [PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(now)] + (["--force"] if force else []) + (["--rescan"] if rescan else [])
        p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
        m_ = re.search(r"^mode: (\{.*\})$", p.stderr, re.M)
        spot_modes.append(((json.loads(m_.group(1)).get("scan") if m_ else "?"), "radar.py" in p.stderr or os.path.exists(os.path.join(d, "young_early.json"))))
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

    print("== sources on five workers at once: the same files and the same log as one after another")
    runs = []
    for serial in ("1", "0"):
        src_dir = tempfile.mkdtemp(prefix="memebot-src-")
        r = subprocess.run([PY, os.path.join(HERE, "fetch.py"), "sources", "--dir", src_dir, "--mock", url, "--pause", "0"], capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, MEMEBOT_SERIAL_SOURCES=serial))
        runs.append((r.returncode, r.stderr, {os.path.relpath(f, src_dir): open(f, "rb").read() for f in glob.glob(os.path.join(src_dir, "**", "*"), recursive=True) if os.path.isfile(f)}))
        shutil.rmtree(src_dir, ignore_errors=True)
    check(runs[0][0] == runs[1][0] == 0 and len(runs[0][2]) > 400 and runs[0][2] == runs[1][2] and runs[0][1] == runs[1][1],
          "fetch.py sources: %d files and %d log lines, byte for byte the same on five workers as one after another" % (len(runs[1][2]), len(runs[1][1].splitlines())))

    print("== rate limit: a 429 is waited out, not given up on")
    sys.path.insert(0, HERE); import fetch as F, time as T
    F.time.sleep = lambda s: None                     # no real waiting in the test
    h = F.Http(url, pause=0)
    got = h.get("https://api.dexscreener.com/__429")
    check(got == {"ok": True} and h.limited == 2 and "api.dexscreener.com" not in h.dead, "429 twice, then the answer (%s waits)" % h.limited)

    print("== fetch.py tokens: a second call numbers its files on after the first, never over them")
    tk = tempfile.mkdtemp(prefix="memebot-tokens-")
    os.makedirs(os.path.join(tk, "pairs"))
    first = {"tokens_000.txt": mock.coins[0], "tokens_002.txt": mock.coins[1]}      # the first call's chunk 1 had no pair, so it wrote no file
    for name, c in first.items():
        open(os.path.join(tk, "pairs", name), "w", encoding="utf-8").write(F.ds_row(mock.pair(c)) + "\n")
    open(os.path.join(tk, "pairs", "jupx_003.txt"), "w").write("JUPXFALLBACK111111111111111111111111111111|0.1|1000\n")
    old_files = {n: open(os.path.join(tk, "pairs", n), "rb").read() for n in os.listdir(os.path.join(tk, "pairs"))}
    F.cmd_tokens(F.Http(url, pause=0, log=lambda s: None), tk, [c["a"] for c in mock.coins[40:71]] + ["JUPXFALLBACK" + "2" * 32])
    now_files = {n: open(os.path.join(tk, "pairs", n), "rb").read() for n in os.listdir(os.path.join(tk, "pairs"))}
    check(all(now_files.get(n) == b for n, b in old_files.items()) and {"tokens_004.txt", "tokens_005.txt", "jupx_006.txt"} <= set(now_files) and len(now_files) == 6,
          "fetch.py tokens after an earlier call with an empty chunk writes tokens_004, tokens_005 and jupx_006 and leaves tokens_002 and jupx_003 as they were (%s)" % sorted(now_files))
    shutil.rmtree(tk, ignore_errors=True)

    print("== run_jobs: workers at once, their lines in list order, a failed job stops only its worker")
    lines, ev = [], threading.Event()
    hj = F.Http(url, pause=0, log=lines.append)
    def first():                                      # waits for the other worker's job: only returns True if both ran at once
        hj.log("a1 start"); hj.log("a1 saw b: %s" % ev.wait(5)); return 1
    def second():
        hj.log("b"); ev.set(); return 2
    got = F.run_jobs(hj, [("a", first), ("b", second), ("a", lambda: hj.log("a2") or 3)])
    check(got == [1, 2, 3] and lines == ["a1 start", "a1 saw b: True", "b", "a2"], "two workers ran at once and the log kept the list order (%s)" % "; ".join(lines))
    lines.clear()
    def boom():
        hj.log("x1"); raise ValueError("x")
    try:
        F.run_jobs(hj, [("x", boom), ("y", lambda: hj.log("y1")), ("x", lambda: hj.log("x2"))]); err = None
    except ValueError as e:
        err = e
    check(err is not None and lines == ["x1", "y1"], "a job that raises stops its own worker, the other finishes, the error is raised (%s)" % "; ".join(lines))

    print("== public RPC throttled: the creator check stops at half the waits, a failed call is unknown")
    class Throttled:                                  # every RPC call is a 429 that post() counted; Jupiter answers
        def __init__(s): s.dead, s.limited_by, s.logs, s.posts = set(), {}, [], 0
        def log(s, m): s.logs.append(m)
        def get(s, u, **k):
            a = u.rsplit("=", 1)[1]
            return [{"id": a, "dev": "DEV" + a[3:], "audit": {"devBalancePercentage": 1.0, "mintAuthorityDisabled": True, "freezeAuthorityDisabled": True}}]
        def post(s, u, payload, **k):
            s.posts += 1
            s.limited_by["api.mainnet-beta.solana.com"] = s.limited_by.get("api.mainnet-beta.solana.com", 0) + 1
            return None
    th, th_dir = Throttled(), tempfile.mkdtemp(prefix="memebot-dev-")
    addrs = ["Coin%sxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump" % "ABCDEFGHJKLMNPQRSTUVWXYZabcdef"[i] for i in range(30)]   # base58 only, or the creator wallet is dropped
    F.dev_check(th, th_dir, addrs, now=T.time())
    dev_rows = [l.rstrip("\n").split("|") for fn in glob.glob(os.path.join(th_dir, "dev", "*.txt")) for l in open(fn, encoding="utf-8") if "|" in l and not l.startswith("address")]
    check(th.posts == F.DEV_RPC_429 and "api.mainnet-beta.solana.com" not in th.dead and F.HOST_MAX_429["api.mainnet-beta.solana.com"] > F.DEV_RPC_429,
          "the creator check made %d RPC calls and left the rest of the %d waits to the wallet sample" % (th.posts, F.HOST_MAX_429["api.mainnet-beta.solana.com"]))
    check(len(dev_rows) == 30 and all(r[7] == "null" and r[8] == "null" for r in dev_rows) and "30 unknown" in th.logs[-1],
          "failed RPC calls leave txs3h and devSold unknown, not 'no sale' (%s)" % th.logs[-1].strip())
    shutil.rmtree(th_dir, ignore_errors=True)

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
    fl = side("fl")
    flc = lambda l, i: l.split("|")[i]
    check(fl and all(len(l.split("|")) == 15 for l in fl) and "on-chain flow (public RPC)" in err
          and all(float(flc(l, 3)) == 10 and float(flc(l, 5)) == 5 and float(flc(l, 6)) == 3 and float(flc(l, 7)) == 7 and float(flc(l, 8)) == 3 and abs(float(flc(l, 9)) - 2 / 6) < 0.01
                  and float(flc(l, 2)) == 30 and abs(float(flc(l, 10)) - 120 / 420) < 0.01 and abs(float(flc(l, 11)) - 420.0) < 0.01 and abs(float(flc(l, 12)) - 144.0) < 0.01
                  and flc(l, 13) == "SOL" and len(flc(l, 14).split(";")) == 5 for l in fl),
          "the public-RPC trade sample: %d coins, 10 of 30 swaps decoded, 5 buyers / 3 sellers, 2 of 6 wallets on both sides, $420 in / $144 out at the pool's vault (%s)" % (len(fl), fl[0][:120] if fl else "-"))
    lp_meta = {"err": None, "preBalances": [10 ** 10], "postBalances": [10 ** 10 - 5 * 10 ** 8]}
    lp_tx = F.flow_swap(dict(lp_meta, preTokenBalances=[{"mint": "C" * 40, "owner": "W" * 40, "uiTokenAmount": {"uiAmount": 1000.0}}, {"mint": "C" * 40, "owner": "P" * 40, "uiTokenAmount": {"uiAmount": 1e6}}, {"mint": F.WSOL, "owner": "P" * 40, "uiTokenAmount": {"uiAmount": 500.0}}],
                                          postTokenBalances=[{"mint": "C" * 40, "owner": "W" * 40, "uiTokenAmount": {"uiAmount": 900.0}}, {"mint": "C" * 40, "owner": "P" * 40, "uiTokenAmount": {"uiAmount": 1e6 + 100}}, {"mint": F.WSOL, "owner": "P" * 40, "uiTokenAmount": {"uiAmount": 500.5}}]), "W" * 40, "C" * 40)
    check(lp_tx is None, "a liquidity deposit (coins and SOL both into the pool) is not counted as a trade")
    t9 = 1_800_000_000
    r9, ok9 = F.flow_rate([{"signature": "s%d" % k, "blockTime": t9 - 1.2 * k, "err": {"x": 1} if k == 50 else None} for k in range(100)], t9)
    W1, W2, W3, CO, PV = "W" * 40, "X" * 40, "Y" * 40, "C" * 40, "P" * 40
    tbl = lambda pre, post: {"preTokenBalances": [{"mint": m, "owner": o, "uiTokenAmount": {"uiAmount": a}} for o, m, a in pre],
                             "postTokenBalances": [{"mint": m, "owner": o, "uiTokenAmount": {"uiAmount": a}} for o, m, a in post], "preBalances": [10 ** 10], "postBalances": [10 ** 10 - 5000]}
    relay = F.flow_swap(tbl([(W2, CO, 0.0), (PV, CO, 1e6), (PV, F.WSOL, 100.0)], [(W2, CO, 50.0), (PV, CO, 1e6 - 50), (PV, F.WSOL, 101.0)]), W1, CO)
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    stable = F.flow_swap(tbl([(W1, CO, 50.0), (PV, CO, 1e6), (PV, usdc, 1000.0)], [(W1, CO, 0.0), (PV, CO, 1e6 + 50), (PV, usdc, 900.0)]), W1, CO)
    remove = F.flow_swap(tbl([(W1, CO, 0.0), (PV, CO, 1e6), (PV, F.WSOL, 100.0)], [(W1, CO, 50.0), (PV, CO, 1e6 - 50), (PV, F.WSOL, 99.0)]), W1, CO)
    feeonly = F.flow_swap(tbl([(W1, CO, 0.0)], [(W1, CO, 50.0)]), W1, CO)
    check(abs(r9 - 99 * 3600 / (1.2 * 99)) < 1 and len(ok9) == 99 and relay == (W2, "buy", F.WSOL, 1.0) and stable == (W1, "sell", usdc, 100.0) and remove is None and feeonly is None,
          "flow details: a failed swap among 100 does not cap the rate (%.0f/h), a relayer-paid buy counts for the wallet that got the coins, a USDC pool is sized in USDC, a liquidity removal and a fee-only change are not trades" % r9)
    check(gp and gi and cm and "goplus security" in err and "community" in err, "GoPlus (%d), GeckoTerminal info (%d) and community (%d) rows written for the shortlist" % (len(gp), len(gi), len(cm)))
    fv = lambda l, i: float(l.split("|")[i]) if l.split("|")[i] not in ("", "null") else None
    check(cm and all(len(l.split("|")) == 14 for l in cm) and any(fv(l, 1) == 40 for l in cm) and any(fv(l, 3) == 2500 for l in cm) and (not F.X_PROFILES or any(fv(l, 10) == 45678 for l in cm)) and any(fv(l, 12) == 12345 for l in cm),
          "community rows carry RugCheck votes, CoinGecko watchlists, X followers (when the lookup is on: %s) and Telegram members (%s)" % (F.X_PROFILES, cm[0][:140] if cm else "-"))
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
    v_unk = MB.risk_view({"lpLocked": 100, "top1Pct": 3, "top10Pct": 20, "insiders": 1, "holders": 2000, "creatorPct": 1, "dev": {"devPct": 1.0, "devSold": None, "mintAuthOff": True, "freezeAuthOff": True, "txs3h": 4}})
    check(v_unk[0] is True and "no creator sale" not in v_unk[1], "unread creator transactions are not called 'no creator sale' (%s)" % v_unk[1][-60:])
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
    od = tempfile.mkdtemp(prefix="memebot-office-")     # the agent office tab from a hand-made office.json: the slowest agent's department opens first
    os.makedirs(os.path.join(od, "db", "memebot"))
    json.dump({"t": T0, "rule": M.RULE, "picks": [], "reason": "nothing passed the gates"}, open(os.path.join(od, "db", "memebot", "recommend.json"), "w"))
    json.dump({"v": 1, "t": T0, "end": T0 + 600_000, "mode": "full", "agents": [
        {"id": "trainer", "start": T0, "end": T0 + 300_000, "status": "done", "bg": True, "lines": ["walk-forward"], "out": "train.json"},
        {"id": "scouts", "start": T0, "end": T0 + 500_000, "status": "done", "lines": ["rugcheck reports 3 of 4", "! giving up on gmgn.ai for this run"],
         "waits": {"www.reddit.com": 2}, "blocked": ["gmgn.ai"], "out": "<b>12 coins</b>"},
        {"id": "safety", "start": T0 + 500_000, "end": None, "status": "running", "lines": ["rugcheck reports 3 of 4"], "out": ""},
        {"id": "reporter", "start": T0 + 500_000, "end": None, "status": "failed", "lines": [], "out": ""}]}, open(os.path.join(od, "db", "memebot", "office.json"), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", od], capture_output=True, text=True)
    page_o = open(os.path.join(od, "report.html"), encoding="utf-8").read() if r.returncode == 0 else ""
    check('id="tab-office"' in page_o and 'id="od-scouts" checked' in page_o and "GMGN · blocked" in page_o and "Reddit · 2 rate-limit waits" in page_o
          and "&lt;b&gt;12 coins" in page_o and "<b>12" not in page_o and "never finished" in page_o and "up to 2 at work at once" in page_o and "could not be rendered" not in page_o
          and "At work <b>1</b>" in page_o and "Skipped <b>0</b>" in page_o and not re.search(r"(^|[\s}])\.ok\s*\{", page_o, re.M),
          "agent office tab: floor plan, the slowest department open, tool states, an unfinished and an agent still at work, escaped output, no page-wide style clash")
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", od, "--now", str(T0 + H)], capture_output=True, text=True, env=dict(os.environ))
    page_plain = open(os.path.join(od, "report.html"), encoding="utf-8").read() if r.returncode == 0 else ""
    r = subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", od, "--now", str(T0 + H)], capture_output=True, text=True, env=dict(os.environ, GITHUB_REPOSITORY="Some-Owner/Meme-Bot"))
    page_live = open(os.path.join(od, "report.html"), encoding="utf-8").read() if r.returncode == 0 else ""
    bare_live = re.sub(r'<script>\s*\(function\(\)\{\s*var MB=window\.MemebotLive=.*?</script>', "", re.sub(
        r'<p class="note olink" data-lv data-live-link>.*?</p><div class="olive".*?<p class="note" data-lv data-live-off hidden></p></div>', "", page_live, flags=re.S), flags=re.S)
    import report as R_
    bare_live = re.sub(r'<p class="note ehint">.*?</p>|<details class="early" data-early.*?</details>', "", bare_live.replace(R_.EARLY_CSS, "", 1), flags=re.S)   # the early list (website only)
    check('Live during a scan: <a href="https://some-owner.github.io/Meme-Bot/">' in page_live and "https://api.github.com/repos/Some-Owner/Meme-Bot/contents/live.json?ref=live" in page_live
          and "MEMEBOT_LIVE_SRC" in page_live and 'data-agents="scouts deep"' in page_live and 'data-agent="scouts"' in page_live
          and page_plain and "Live during a scan" not in page_plain and "live.json" not in page_plain and "MEMEBOT_LIVE_SRC" not in page_plain and bare_live == page_plain,
          "the office tab carries the live script and the website line only when GITHUB_REPOSITORY is set; without them the page is the same")
    import report as R_
    js = R_.OFFICE_LIVE_JS
    check("If-None-Match" not in page_live and "Accept:'application/vnd.github.raw+json'" in js and "j.encoding==='base64'" in js and "AbortController" in js and "if(r.status===404)return null;" in js
          and "TIMEOUT:20000" in js and "LIVE:75000" in js and "IDLE:600000" in js and "STALE:300000" in js and "GRID:[-2,5,15,25,35,45]" in js and "localStorage" in js
          and 'data-next-scan="%d"' % R_.next_scan_ms(T0 + H) in page_live and "Live view paused: no update since " in js and "The last scan stopped at " in js
          and js.count("'The last scan finished at '") == 2 and "st==='done'&&newer&&site" in js,
          "the live script asks for the raw file without an ETag (no CORS preflight), times a fetch out after 20 s, polls on the schedule and says paused or stopped")
    node = shutil.which("node")
    if node:      # the script's two decisions, run in node: what the box shows and when the next poll is due
        jd = tempfile.mkdtemp(prefix="memebot-js-")
        with open(os.path.join(jd, "t.js"), "w", encoding="utf-8") as f:
            f.write("global.window={};global.document={readyState:'complete',querySelector:function(){return null;}};\n" + js + r"""
var MB=window.MemebotLive,now=Date.UTC(2026,9,10,12,0,0),scan=Date.UTC(2026,9,10,12,10,0),pageT=now-3600000,M=60000,o={},st=MB.state;
function snap(live,age,ags,t){return {t:t||now-20*M,live:live,updated:now-age,agents:ags||[{id:'dispatch',status:'done'},{id:'market',status:'running'}]};}
var done=[{id:'trader',status:'done'},{id:'reporter',status:'done'}];
o.states=[st(snap(true,30000),now,pageT,0),st(snap(true,200000),now,pageT,0),st(snap(true,301000),now,pageT,0),st(snap(true,30000),now,pageT,1),st(snap(true,30000),now,pageT,2),
  st(snap(false,0,done),now,pageT,0),st(snap(false,0,done),now,pageT,3),st(snap(false,0,[{id:'trader',status:'failed'}]),now,pageT,0),
  st(snap(false,0,[{id:'trader',status:'done'},{id:'reporter',status:'failed'}]),now,pageT,0),st(snap(false,0,[{id:'market',status:'failed'},{id:'reporter',status:'done'}]),now,pageT,0),
  st(snap(false,0,done,pageT-1),now,pageT,0),st(snap(true,30000,null,pageT-1),now,pageT,0),st(null,now,pageT,0),st({t:now,agents:[]},now,pageT,0)];
var seen={};for(var a=0;a<4*3600000;a+=7000)for(var k=0;k<6;k++)seen[st(snap(true,a),now,pageT,k)]=1;o.liveSeen=Object.keys(seen).sort();
function nx(doc,t,sc,rem,reset,fails){var v=MB.next(doc,t,sc,rem,reset,fails);return Math.round((v-t)/1000);}
var off=snap(false,0,done);
o.next=[nx(snap(true,30000),now,scan,null,0,0),nx(off,now,scan,null,0,0),nx(off,now+8.5*M,scan,null,0,0),nx(off,now+14*M,scan,null,0,0),nx(off,now+50*M,scan,null,0,0),
  nx(off,now+3*3600000+55*M,scan,null,0,0),nx(off,now,0,null,0,0),nx(null,now,scan,null,0,0),nx(snap(true,400000),now,scan,null,0,0),nx(snap(true,30000),now,scan,0,now/1000+1200,1),
  nx(snap(true,30000),now,scan,20,now/1000+1800,0),nx(snap(true,30000),now,scan,59,now/1000+3590,0),nx(snap(true,30000),now,scan,null,0,1),nx(off,now,scan,null,0,9)];
console.log(JSON.stringify(o));
""")
        r = subprocess.run([node, os.path.join(jd, "t.js")], capture_output=True, text=True)
        shutil.rmtree(jd, ignore_errors=True)
        try:
            o = json.loads(r.stdout)
        except ValueError:
            o = {"err": r.stderr[-300:]}
        check(o.get("states") == ["live", "live", "paused", "live", "paused", "done", "done", "stopped", "stopped", "stopped", "hide", "hide", "hide", "hide"]
              and o.get("liveSeen") == ["live", "paused"],
              "the page's decision (node): a live snapshot is live, after 5 minutes without an update or two failed polls paused, never finished; live false is finished,"
              " or stopped when the reporter did not finish or an agent failed; a snapshot older than the page or none hides the box %s" % (o.get("states") or o))
        check(o.get("next") == [75, 8 * 60, 75, 60, 5 * 60, 13 * 60, 600, 8 * 60, 8 * 60, 1205, 180, 75, 150, 1800],
              "the page's poll plan (node): 75 s while live and in the scan window (from 2 minutes before a scheduled start to 35 after it); between scans 2 minutes"
              " before the scheduled start, then every 10 minutes (10 without the schedule); after a failed poll longer; GitHub's remaining requests stretch the gap,"
              " none left waits for the reset %s" % (o.get("next") or o))
    else:
        check("state:function(doc,now,pageT,fails)" in js and "doc.live===true)return now-(+doc.updated||0)<MB.STALE&&(+fails||0)<2?'live':'paused'" in js
              and "return rep&&rep.status==='done'&&!bad?'done':'stopped'" in js and "(+doc.t||0)<pageT)return 'hide'" in js,
              "the page's decision (string checks, node not found): live false is finished or stopped, a stale live snapshot paused, an older one hidden")
    shutil.rmtree(od, ignore_errors=True)
    print("== recommend mode: a fresh db, full scan, two recommendations, no positions")
    rd = tempfile.mkdtemp(prefix="memebot-rec-")
    os.makedirs(os.path.join(rd, "db", "memerec"))
    late_c = mock.coins[150]      # a tip from nine hours ago whose 1 h check an older version priced eight hours late as "gone": the candles must price it again
    json.dump({"t": T0 - 9 * H, "rule": M.RULE, "picks": [{"sym": "LATE", "addr": late_c["a"], "pair": late_c["a"][:20] + "pair", "px": late_c["px"], "mc": 300000, "score": 50.0, "tier": "strong"}],
               "outs": {"1": {"t": T0 - H, "h": 8.0, "picks": [{"sym": "LATE", "mult": 0.0, "eur": -20.0, "gone": True}]}}},
              open(os.path.join(rd, "db", "memerec", "late.json"), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--mock", url, "--now", str(T0), "--recommend"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    late_doc = json.load(open(os.path.join(rd, "db", "memerec", "late.json")))
    l1 = (late_doc.get("outs") or {}).get("1") or {}
    lp = (l1.get("picks") or [{}])[0]
    import report as R_
    check(l1.get("late") and lp.get("fromCandles") and abs((M.num(lp.get("mult")) or 0) - late_c["mult"]) < 0.01 and M.num(lp.get("hi")) and "1" not in [k for k, _, _ in M.tip_due(late_doc, T0)]
          and "from candles" in R_.candles_txt(lp) and "priced 8.0 h late" in R_.odd_cell({"h": 8.0, "picks": []}, None, 1.0) and not M.settled({"h": 8.0, "picks": [lp]}, 1.0) and M.settled(l1, 1.0)
          and M.stale_check({"h": 1.0, "late": True, "picks": [{"sym": "G", "mult": 6.9, "eur": 111.0, "hi": 8.6, "lo": 0.02, "fromCandles": True}]}, 1.0) and "unusable" in R_.odd_cell({}, {"missed": True, "glitch": True}, 1.0)
          and lp.get("cv") == M.CANDLE_V and M.stale_check({"h": 1.0, "late": True, "picks": [{"sym": "O", "mult": 1.01, "eur": -1.4, "fromCandles": True}]}, 1.0)
          and not M.stale_check(l1, 1.0),
          "a 1 h check priced 8 h late was priced again from the window's candles (%sx, peak %sx, checked %s h late)" % (lp.get("mult"), lp.get("hi"), l1.get("checkedH")))
    pth = [[0, 1.0, 1.3, 0.95, 1.25], [5, 1.0, 1.1, 0.9, 1.0], [20, 1.0, 1.9, 1.0, 1.05], [21, 1.05, 1.3, 1.0, 1.22], [40, 1.2, 1.6, 1.1, 1.55], [59, 0.5, 0.6, 0.4, 0.45]]
    o_tp = M.with_tp({"sym": "T", "mult": 0.45, "eur": M.tip_net(0.45), "path": pth, "cv": M.CANDLE_V}, 18.0)
    # entry price at minute 18: minute 0's +25% close came before it, the 1.9x at minute 20 is a wick; the close of 1.22 at 21 sells +10% and +20%, 1.55 at 40 sells +30% and +50%
    check(o_tp["tpMin"] == {"10": 21, "20": 21, "30": 40, "50": 40} and o_tp["tpx"]["20"] == M.tip_net(1.2) == 2.22 and o_tp["tpx"]["50"] == M.tip_net(1.5) and o_tp["tpFrom"] == 18.0
          and M.take_profit(pth, 0.45, 0.6, 18.0) == (0.45, None) and M.with_tp({"mult": 1.0, "path": pth}, None).get("tpx") is None
          and M.entry_min({"t": 1000, "pricedAt": 1000 + 23 * 60000}) == 23.0 and M.entry_min({"t": 1000}, {"note": "Prices of 16 candidates refreshed 26 minutes after the scan started, right before the pick."}) == 26.0
          and M.entry_min({"t": 1000}, {"note": "Scanned 900 coins."}) is None and M.entry_min({"t": 1000, "pricedAt": 1000 + 5 * H}) is None,
          "take-profit replay: a close after the entry price sells at the level; wicks and candles before the entry do not (%s)" % o_tp.get("tpMin"))
    spk = M.GATE_SPIKE
    try:      # the 2h profile's spike cap, checked in this process without switching the whole profile
        M.GATE_SPIKE = M.PROFILES["2h"]["GATE_SPIKE"]
        g_base = {"price": 0.001, "mc": 500_000.0, "liq": 60_000.0, "vol24": 400_000.0, "age_h": 10.0}
        g_pr = {"symbol": "HOTX", "name": "Hot", "dexId": "pumpswap", "chgH1": 5.0, "chgH6": 95.0, "chgH24": 300.0}
        g_hot, g_calm = M.gates(g_pr, g_base, {}), M.gates(dict(g_pr, chgH6=40.0), g_base, {})
    finally:
        M.GATE_SPIKE = spk
    check("spike" in g_hot and "spike" not in g_calm and M.PROFILES["2h"]["GATE_SPIKE"]["chgH6"] == 90.0,
          "2h profile: a coin up 95% in 6 hours is still in its pump and fails the spike gate, one up 40% does not")
    bdoc = {"t": 1000, "outs": {"1": {"picks": [{"sym": "T", "mult": 0.45, "eur": M.tip_net(0.45), "path": pth, "cv": M.CANDLE_V}, {"sym": "N", "mult": 1.0, "eur": -1.62}]}}}
    bnew, bch = M.backfill_tp(bdoc, 18.0)
    bo = bnew["outs"]["1"]["picks"]
    check(bch and bo[0]["tpMin"]["20"] == 21 and "tpx" not in bo[1] and "tpx" not in bdoc["outs"]["1"]["picks"][0] and not M.backfill_tp(bnew, 18.0)[1] and not M.backfill_tp(bdoc, None)[1]
          and "sold at +20% after 21 min: +2.22" in R_.peak_txt(dict(bo[0], hi=1.9)) and R_.tp_val(bo[1]) is None and "tpx" not in lp,
          "results priced before the replay get it once from their stored path; a tip whose entry time is unknown gets none")
    rec = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json"))) if os.path.exists(os.path.join(rd, "db", "memebot", "recommend.json")) else {}
    check(r.returncode == 0 and len(rec.get("picks", [])) == 2 and r.stdout.count("RECOMMEND") == 2, "recommend cycle wrote 2 recommendations (%s)" % [p["sym"] for p in rec.get("picks", [])])
    vt_files = glob.glob(os.path.join(rd, "vt", "vt_*.txt"))
    vt_rows = [l for fn in vt_files for l in open(fn, encoding="utf-8") if l.strip()]
    page_r = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    told = [c for c in rec.get("picks", []) + rec.get("runnersUp", []) if "vt.likes" in (c.get("f") or {})]
    check(vt_rows and all(len(l.split("|")) == len(M.VT_COLS) for l in vt_rows) and told and all(isinstance((c.get("risk") or {}).get("vt"), dict) for c in told)
          and any("launched off a tweet" in (c.get("why") or "") for c in told) and "the story: source tweet" in page_r,
          "source tweets read for the story coins (%d rows; %d of the named coins carry one: %s)" % (len(vt_rows), len(told), [(c["sym"], round(10 ** c["f"]["vt.likes"])) for c in told[:3]]))
    check(any(M.num((c.get("f") or {}).get("theme.animal")) for c in rec.get("picks", []) + rec.get("runnersUp", [])) and "animal story" in page_r,
          "the animal theme is a factor and shows on the page")
    lp = [c for c in rec.get("picks", []) + rec.get("runnersUp", []) if "lp.trusted" in (c.get("f") or {})]
    check(lp and all(c.get("launchpad") for c in lp) and ("launched on" in " ".join(c.get("why") or "" for c in lp)) and ">launchpad<" in page_r,
          "the launchpad is known and judged (%s)" % [(c["sym"], c.get("launchpad"), c["f"].get("lp.trusted")) for c in lp[:3]])
    with_fl = [c for c in rec.get("picks", []) + rec.get("runnersUp", []) if "fl.buyers" in (c.get("f") or {})]
    check(with_fl and all(c["f"]["fl.buyers"] == 5 and c["f"]["fl.sellers"] == 3 and abs(c["f"]["fl.buyerRatio"] - 6 / 4) < 1e-6 and abs(c["f"]["fl.netUsd"] - 276.0) < 0.01 for c in with_fl)
          and any("on-chain sample: about 30 swaps in the last hour, 5 buyers vs 3 sellers among 10 decoded, net +$" in (c.get("why") or "") for c in with_fl)
          and all("fl." not in k for k in M.PRIOR),
          "the RPC trade sample becomes fl.* factors with no prior weight and a sentence in the why text (%d named coins carry it)" % len(with_fl))
    lw, _, ldet = M.learn([({"fl.buyers": float(i % 7), "c1": float(i % 7)}, float(i % 7)) for i in range(200)])
    snaps = [c for fn in glob.glob(os.path.join(rd, "db", "memesnap", "*.json")) for c in (json.load(open(fn)).get("coins") or []) if isinstance(c, dict)]
    with_flb = [c for c in snaps if c.get("flb")]
    check("c1" in lw and "fl.buyers" not in lw and "fl.buyers" in ldet and with_flb and all(not set(c["flb"]) & set((c.get("rc") or {}).get("holders") or []) for c in with_flb),
          "fl.* are measure-only: the learner reports them but gives no weight, and the sampled buyers are stored apart from the holders that feed the wallet memory (%d snapshot coins carry them)" % len(with_flb))
    dp_rows = [l for fn in glob.glob(os.path.join(rd, "dp", "dp_*.txt")) for l in open(fn, encoding="utf-8") if l.strip()]
    named = rec.get("picks", []) + rec.get("runnersUp", [])
    with_dp = [c for c in named if "ds.paid" in (c.get("f") or {})]
    check(dp_rows and all(len(l.split("|")) == len(M.DP_COLS) for l in dp_rows) and with_dp and any(c["f"]["ds.paid"] == 1 for c in with_dp)
          and any("DEX paid" in (c.get("why") or "") for c in with_dp) and ">DEX paid<" in page_r,
          "DEX paid read from DexScreener's orders (%d rows; %d named coins carry it, %d paid)" % (len(dp_rows), len(with_dp), sum(1 for c in with_dp if c["f"]["ds.paid"] == 1)))
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
    page = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    load_dir = lambda dd, coll: {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(dd, "db", coll, "*.json"))}
    hp = load_dir(rd, "memepos")
    st_r = json.load(open(os.path.join(rd, "db", "memebot", "state.json")))
    note_r = st_r.get("note") or ""
    tops = {pid: p for pid, p in hp.items() if p.get("grp") == "hold"}
    youngs = {pid: p for pid, p in hp.items() if p.get("grp") == "young"}
    yrec = rec.get("young") or []
    top0 = (list(tops.values()) or [{}])[0]
    check(M.TICKET == 20 and M.BUDGET == 40 and (M.FEE_PCT, M.FEE_MIN) == (0.005, 0.81) and M.fee(20) == 0.81 and M.paper_fee(50) == 0.5 and M.paper_fee(3) == 0.1 and M.paper_fee(0) == 0
          and M.pos_fee({"grp": "young", "paper": M.PAPER_RULE}) is M.paper_fee and M.pos_fee({"grp": "hold"}) is M.fee and M.pos_fee({"grp": "pick", "paper": M.PAPER_RULE}) is M.fee,
          "paper fees 1%, at least 0.10, for the paper account only; the tip record, the big test and pick mode keep 20 a ticket, 0.5% and at least 0.81")
    check(len(tops) == 1 and top0.get("addr") == rec["picks"][0]["addr"] and top0.get("ticket") == M.TOP_TICKET == 50.0 and rec["picks"][0].get("bought") == 50.0
          and all(c.get("bought") is None for c in rec["picks"][1:]) and len(yrec) > M.YOUNG_BUY_N == 5 and len(youngs) == 5
          and sorted(p["addr"] for p in youngs.values()) == sorted(y["addr"] for y in yrec[:5]) and all(p.get("ticket") == M.YOUNG_TICKET == 3.0 for p in youngs.values())
          and [y.get("bought") for y in yrec[:5]] == [3.0] * 5 and all("bought" not in y for y in yrec[5:])
          and all(p.get("paper") == M.PAPER_RULE and M.num(p.get("px")) and p.get("pair") and p.get("t") == T0 for p in hp.values())
          and all(re.match(r"^\d{4}-\d\d-\d\dT\d{6}-[hy]-", pid) for pid in hp) and all(M.num(p.get("ageMin")) is not None for p in youngs.values())
          and st_r.get("paperRule") == M.PAPER_RULE and st_r.get("paperSince") == T0 and (st_r.get("paper") or {}).get("invested") == 65.0 and (st_r.get("paper") or {}).get("nOpen") == 6
          and "bought as a paper position: %s (50\u00a0€)" % rec["picks"][0]["sym"] in note_r and "New launches: bought" in note_r and "for 3\u00a0€ each" in note_r
          and "(1 top pick, 5 new launches)" in note_r,
          "one cycle buys the top pick for 50 and the first 5 new launches for 3 each, the second pick and the other new launches stay tips (%s; %s)" % (
              [(p.get("sym"), p.get("grp"), p.get("ticket")) for p in hp.values()], [(y.get("sym"), y.get("bought")) for y in yrec[:7]]))
    curve_r = sorted(load_dir(rd, "memecurve").values(), key=lambda c: c["t"])
    check("How a coin is sold" in page and "the first minute candle that closes at 11 times the entry price" in page and "Failing a filter sells nothing" in page
          and "bought for 50\u00a0€" in page and "bought for 3\u00a0€" in page and "top pick · 50\u00a0€" in page and "new launch · 3\u00a0€" in page and "profit/loss since the restart" in page
          and "held 0 min of 6h" in page and 'class="tk st"' in page and "sells +1000%" in page and "stop −30%" in page and "paper position" in page and "1 top pick · 5 new launches" in page
          and "sold at the first scan after about" in page and "at the latest" not in page and "sells when a minute candle closes at" in page
          and curve_r and curve_r[-1].get("paper", {}).get("invested") == 65.0 and set(curve_r[-1]["paper"]) == {"invested", "back", "open", "pnl", "n"},
          "page: the paper account, one row per position with its group and ticket, the price bar from the stop to the take-profit, the 6-hour clock, the rule text; the curve doc carries the account")
    check("Two recommendations" in page and "dexscreener.com/solana/" in page and 'class="embed"' in page, "page shows the recommendations with embedded charts")
    old_rec = rec
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", rd, "--now", str(T0 + 120000), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    rec2 = json.load(open(os.path.join(rd, "db", "memebot", "recommend.json")))
    same = lambda a, b: [c["addr"] for c in a.get("picks", [])] == [c["addr"] for c in b.get("picks", [])]
    check(r.returncode == 0 and same(rec2, old_rec), "an offline rerun with the same files keeps the recommendations (%s -> %s; %s)" % ([c["sym"] for c in old_rec.get("picks", [])], [c["sym"] for c in rec2.get("picks", [])], (r.stderr.strip().splitlines() or ["?"])[-1][:100]))
    page2r = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    check(len(load_dir(rd, "memepos")) == 6 and rec2["picks"][0].get("bought") == "held" and [y.get("bought") for y in (rec2.get("young") or [])[:5]] == ["held"] * 5
          and not load_dir(rd, "memeexit") and "already held since" in page2r and "already held</span>" in page2r,
          "a repeat tip of a held coin (top pick or new launch) buys nothing and sells nothing (still 6 positions, %s)" % [c.get("bought") for c in rec2.get("picks", []) + (rec2.get("young") or [])[:5]])
    # the sell rules, in a copy, an hour later: the top pick's pool closes a candle at 11.5x (take-profit +1000%, booked at 11x), a new launch's
    # at 0.5x (stop, booked at 0.5x), one falls 60% in the last hour (fails the crash filter: no sale any more), two pools send no candles
    # while DexScreener prices them at 12x and 0.6x (the run's price decides: take-profit at 11x, stop at 0.6x)
    xd = tempfile.mkdtemp(prefix="memebot-hold-")
    shutil.copytree(rd, xd, dirs_exist_ok=True)
    (top_id, top), = tops.items()
    (y0_id, y0), (y1_id, y1), (y2_id, y2), (y3_id, y3), (y4_id, y4) = [next((pid, p) for pid, p in youngs.items() if p["addr"] == y["addr"]) for y in yrec[:5]]
    chg_1 = mock.by_a[y1["addr"]]["chg"][1]
    ask = lambda path: urllib.request.urlopen(url + path).read()
    ask("/__spike?a=%s&x=11.5" % top["addr"]); ask("/__spike?a=%s&x=0.5" % y0["addr"]); ask("/__chg?a=%s&h1=-60" % y1["addr"])
    for yy, m_ in ((y3, 12), (y4, 0.6)):
        ask("/__nocandle?a=%s&on=1" % yy["addr"]); ask("/__mult?a=%s&m=%s" % (yy["addr"], m_))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", xd, "--mock", url, "--now", str(T0 + H), "--recommend"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    ask("/__spike?a=%s&x=0" % top["addr"]); ask("/__spike?a=%s&x=0" % y0["addr"]); ask("/__chg?a=%s&h1=%s" % (y1["addr"], chg_1))
    for yy in (y3, y4):
        ask("/__nocandle?a=%s&on=0" % yy["addr"]); ask("/__mult?a=%s&m=1" % yy["addr"])
    xe = load_dir(xd, "memeexit")
    ex_of = lambda pid: [e for e in xe.values() if e.get("pos") == pid]
    one = lambda pid: (ex_of(pid) or [{}])[0]
    val = lambda pp, m: round(M.pos_value(pp, 1.0, m), 2)
    near = lambda a_, b_: a_ is not None and b_ is not None and abs(a_ - b_) <= 1e-6 * max(abs(b_), 1e-12)
    px_x = M.load_pairs(xd)
    page_x = open(os.path.join(xd, "report.html"), encoding="utf-8").read() if os.path.exists(os.path.join(xd, "report.html")) else ""
    et, e0, e3, e4 = one(top_id), one(y0_id), one(y3_id), one(y4_id)
    check(r.returncode == 0 and len(ex_of(top_id)) == 1 and et.get("why") == "tp" and near(et.get("px"), 11.0 * top["px"]) and et.get("eur") == val(top, 11.0) == 539.05 and M.num(et.get("at"))
          and len(ex_of(y0_id)) == 1 and e0.get("why") == "stop" and near(e0.get("px"), 0.5 * y0["px"]) and e0.get("eur") == val(y0, 0.5) == 1.35 and M.num(e0.get("at")),
          "candle closes sell: 11.5x is a take-profit booked at exactly 11x (539.05 back for 50 after paper fees), 0.5x a stop booked at the close (1.35 back for 3) (%s; %s)" % (
              [(e.get("why"), e.get("eur")) for e in (et, e0)], (r.stderr.strip().splitlines() or ["ok"])[-1][:100] if r.returncode else "ok"))
    check(e3.get("why") == "tp" and near(e3.get("px"), 11.0 * y3["px"]) and e3.get("eur") == val(y3, 11.0) == 31.58 and "at" not in e3
          and e4.get("why") == "stop" and near(e4.get("px"), M.num(px_x[y4["addr"]]["priceUsd"])) and abs(e4["px"] / y4["px"] - 0.6) < 1e-3 and e4.get("eur") == val(y4, e4["px"] / y4["px"]) == 1.64,
          "no candles this run: the run's own price decides, 12x is a take-profit at 11x (31.58 back for 3), 0.6x a stop at that price (%s)" % [(e.get("why"), e.get("eur")) for e in (e3, e4)])
    check(not ex_of(y1_id) and M.num(px_x[y1["addr"]].get("chgH1")) == -60 and -60 <= M.GATE_CRASH["chgH1"] and not ex_of(y2_id)
          and "take-profit +1000%" in page_x and "stop-loss −30%" in page_x and "Top trades · 4 closed" in page_x,
          "a coin that fails the crash filter is not sold any more; the page names each sale by the paper rules")
    hcd = tempfile.mkdtemp(prefix="memebot-hc-")
    os.makedirs(os.path.join(hcd, "candles"))

    def hc_(closes, chk=None, cpx=None):
        open(os.path.join(hcd, "candles", "UPOOL_hold.txt"), "w").write("".join("%d|1|1|1|%s|1\n" % (T0 + 60000 * i, c) for i, c in enumerate(closes)))
        return M.hold_check(hcd, {"pair": "UPOOL", "t": T0}, chk, cpx)
    h1_, h2_, h3_, h4_, h5_ = hc_([1.0, 1.2, 40.0, 0.69, 11.2]), hc_([1.0, 1.2, 40.0, 11.2, 0.5]), hc_([2.0, 1.5, 1.39]), hc_([1.0, 0.5, 1.0], chk=T0 + 180000), hc_([1.0, 10.9, 0.71, 1.0])
    check(h1_["why"] == "stop" and h1_["hit"] == T0 + 180000 and abs(h1_["mult"] - 0.69) < 1e-9 and h2_["why"] == "tp" and h2_["hit"] == T0 + 180000
          and h3_["why"] == "stop" and h3_["cpx"] == 2.0 and abs(h3_["mult"] - 0.695) < 1e-9 and h4_["fresh"] is False and h4_["hit"] is None and h4_["chk"] == T0 + 180000
          and h5_["hit"] is None and h5_["fresh"] is True and h5_["chk"] == T0 + 240000 and h5_["cpx"] == 1.0,
          "hold_check on closes: a 40x close is a glitch, whichever of the stop and the take-profit closes first sells, 10.9x and 0.71x sell nothing, no candle since the last check is no check")
    shutil.rmtree(hcd, ignore_errors=True)
    hc = M.hold_check(xd, {"pair": "NOPOOL", "t": T0}, None, None)
    check(hc == {"hit": None, "why": None, "mult": None, "chk": None, "cpx": None, "fresh": False}, "no candles for a held coin: no candle sale, the run's price decides, the next check starts where this one would have")
    # the 6-hour limit and the rug: one coin vanishes from every fetched file (no price in the next two runs), the copy runs at +5.5 h and at +6 h
    for f in glob.glob(os.path.join(xd, "**", "*.txt"), recursive=True):
        if os.sep + "db" + os.sep not in f:
            lines = open(f, encoding="utf-8").read().splitlines(True)
            open(f, "w", encoding="utf-8").write("".join(l for l in lines if not l.startswith(y2["addr"])))
    r55 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", xd, "--now", str(T0 + 5.5 * H), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    xe55 = load_dir(xd, "memeexit")
    mk55 = json.load(open(os.path.join(xd, "db", "memebot", "marks.json")))
    r6 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", xd, "--now", str(T0 + 6 * H), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    xe = load_dir(xd, "memeexit")
    P6 = M.positions(xd)
    e1, e2 = one(y1_id), one(y2_id)
    later = [p for p in P6.values() if p["t"] > T0]
    page_6 = open(os.path.join(xd, "report.html"), encoding="utf-8").read()
    check(r55.returncode == 0 and r6.returncode == 0 and len(xe55) == 4 and (mk55.get("miss") or {}).get(y2_id) == 1
          and e1.get("why") == "time" and e1.get("t") == T0 + 6 * H and e1.get("eur") == val(y1, e1["px"] / y1["px"]) and e2.get("why") == "rug" and e2.get("eur") == 0
          and all(p["_left"] <= 1e-9 for p in P6.values() if p["t"] == T0) and all(p["_left"] > 1e-9 for p in later)
          and "6-hour limit" in page_6 and "rug: the price or the liquidity is gone" in page_6,
          "nothing is sold at 5.5 hours; at 6 hours the rest of the first scan's positions are sold at that run's price, a coin without a price twice is a rug, newer ones stay (%s; %d newer open)" % (
              sorted((e.get("why"), e.get("eur")) for e in (e1, e2)), len(later)))
    acct6 = json.load(open(os.path.join(xd, "db", "memebot", "state.json"))).get("paper") or {}
    a6 = M.paper_account(P6, T0, json.load(open(os.path.join(xd, "db", "memebot", "marks.json"))).get("px"))
    check(acct6 == a6 and a6["back"] == round(sum(e["eur"] for e in xe.values()), 2) and a6["invested"] == round(sum(p["ticket"] for p in P6.values()), 2)
          and a6["nClosed"] == 6 and a6["won"] == 2 and a6["lost"] == 4 and a6["nOpen"] == len(later) and abs(a6["pnl"] - (a6["back"] + a6["open"] - a6["invested"])) < 0.011,
          "the paper account adds up: invested %.2f, back %.2f, open %.2f, %+.2f (%d won, %d lost)" % (a6["invested"], a6["back"], a6["open"], a6["pnl"], a6["won"], a6["lost"]))
    shutil.rmtree(xd, ignore_errors=True)
    # the restart: a copy whose state predates the new rules holds old positions: the first run closes the open ones at its price ("reset"),
    # once and only once; the account counts from then on, the old trades sit behind their own fold. The coin of an old position is named
    # again and bought the same day under a new id, so the old position's exits never attach to it
    zd = tempfile.mkdtemp(prefix="memebot-restart-")
    shutil.copytree(rd, zd, dirs_exist_ok=True)
    for coll in ("memepos", "memeexit", "memecurve"):
        shutil.rmtree(os.path.join(zd, "db", coll), ignore_errors=True)
        os.makedirs(os.path.join(zd, "db", coll))
    st_z = json.load(open(os.path.join(zd, "db", "memebot", "state.json")))
    for k in ("paperSince", "paperRule", "paper"):
        st_z.pop(k, None)
    json.dump(st_z, open(os.path.join(zd, "db", "memebot", "state.json"), "w"))
    pz = M.load_pairs(zd)
    tp_c = rec2["picks"][0]
    now_px = M.num(pz[tp_c["addr"]]["priceUsd"])
    day0 = time.strftime("%Y-%m-%d", time.gmtime(T0 / 1000))
    old1 = "%s-h-%s-%s" % (day0, M.slug(tp_c["sym"]), tp_c["addr"][:6])          # the id the old rule gave a coin bought that day
    olds = {old1: {"grp": "hold", "addr": tp_c["addr"], "sym": tp_c["sym"], "pair": tp_c.get("pair"), "t": T0 - 3 * H, "px": now_px / 1.3, "ticket": 20.0, "rule": M.RULE, "tp": 0.4},
            "old-gone": {"grp": "hold", "addr": "1" * 44, "sym": "GONE", "t": T0 - 50 * H, "px": 0.001, "ticket": 20.0, "rule": M.RULE, "tp": 0.4},
            "old-tp": {"grp": "hold", "addr": "2" * 44, "sym": "OLDTP", "t": T0 - 30 * H, "px": 0.001, "ticket": 20.0, "rule": M.RULE, "tp": 0.4},
            "old-flt": {"grp": "hold", "addr": "3" * 44, "sym": "OLDFLT", "t": T0 - 20 * H, "px": 0.001, "ticket": 20.0, "rule": M.RULE, "tp": 0.4},
            "old-time": {"grp": "hold", "addr": "4" * 44, "sym": "OLDTIME", "t": T0 - 60 * H, "px": 0.001, "ticket": 17.27, "rule": M.RULE, "tp": 0.4}}
    for pid, doc in olds.items():
        json.dump(doc, open(os.path.join(zd, "db", "memepos", pid + ".json"), "w"))
    json.dump({"pos": "old-tp", "t": T0 - 29 * H, "px": 0.0014, "frac": 1.0, "why": "tp", "eur": 26.06, "grp": "hold", "at": T0 - 29 * H}, open(os.path.join(zd, "db", "memeexit", "old-tp-1.json"), "w"))
    json.dump({"pos": "old-time", "t": T0 - 12 * H, "px": 0.0011, "frac": 1.0, "why": "time", "eur": 17.37, "grp": "hold"}, open(os.path.join(zd, "db", "memeexit", "old-time-1.json"), "w"))
    json.dump({"pos": "old-flt", "t": T0 - 19 * H, "px": 0.0009, "frac": 1.0, "why": "filters", "gates": ["crash"], "eur": 17.0, "grp": "hold"}, open(os.path.join(zd, "db", "memeexit", "old-flt-1.json"), "w"))
    rz = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", zd, "--now", str(T0 + 3 * 60000), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    ze = load_dir(zd, "memeexit")
    Pz = M.positions(zd)
    st_z = json.load(open(os.path.join(zd, "db", "memebot", "state.json")))
    page_z = open(os.path.join(zd, "report.html"), encoding="utf-8").read()
    resets = sorted((e["pos"], e["eur"]) for e in ze.values() if e.get("why") == "reset")
    again = [pid for pid, p in Pz.items() if p.get("addr") == tp_c["addr"] and pid != old1]
    old_back = round(max(0.0, (20 - M.fee(20)) * 1.3 - M.fee((20 - M.fee(20)) * 1.3)), 2)
    check(rz.returncode == 0 and resets == sorted([(old1, old_back), ("old-gone", 0.0)]) and abs(next(e["px"] for e in ze.values() if e["pos"] == old1) - now_px) < 1e-12
          and st_z.get("paperRule") == M.PAPER_RULE and st_z.get("paperSince") == T0 + 3 * 60000 and "restarted under the new rules (the top pick for 50\u00a0€, new launches for 3\u00a0€, sold at +1000%, \u2212" in (st_z.get("note") or "")
          and len(again) == 1 and Pz[again[0]].get("grp") == "hold" and Pz[again[0]].get("ticket") == 50.0 and not Pz[again[0]]["_exits"] and len(Pz[old1]["_exits"]) == 1
          and sum(1 for p in Pz.values() if p.get("grp") == "young") == 5 and (st_z.get("paper") or {}).get("invested") == 65.0 and (st_z.get("paper") or {}).get("n") == 6,
          "the restart closed the two open old positions at this run's price with the old fees (%s), and the coin of one was bought again under a new id (%s, not %s)" % (resets, again, old1))
    check("Before the restart (5 trades)" in page_z and "Best within 6 h (hindsight): priced after the next scans." in page_z and "closed at the restart" in page_z and "take-profit +40%" in page_z and "failed the filters (crashed)" in page_z
          and "48-hour limit" in page_z and "old rule · 20\u00a0€" in page_z and "old rule · 17.27\u00a0€" in page_z and "Top trades · 0 closed" in page_z and "65.00" in page_z
          and "bought before the paper account restarted on " in page_z and "bought under the rules before" not in page_z
          and "nothing sold yet" in page_z and "−3.1% on 65.00\u00a0€ invested" in page_z,
          "page: the account counts from the restart, the five old trades sit behind the fold with their old rule and reasons")
    rz2 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", zd, "--now", str(T0 + 4 * 60000), "--recommend", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    st_z2 = json.load(open(os.path.join(zd, "db", "memebot", "state.json")))
    check(rz2.returncode == 0 and load_dir(zd, "memeexit") == ze and len(load_dir(zd, "memepos")) == len(Pz) and st_z2.get("paperSince") == T0 + 3 * 60000
          and "restarted" not in (st_z2.get("note") or ""),
          "a second run after the restart closes nothing and buys nothing more: the restart happens once")
    dash0 = R_.dash_section({"paper": {"since": None, "acct": M.paper_account({}, None)}})
    check("nothing held" in dash0 and "nothing bought yet" in dash0 and "nothing sold yet" in dash0 and M.paper_account(M.positions(zd), None)["n"] == 0,
          "an account with nothing in it says so, and without a restart nothing counts in it")
    stz = subprocess.run([PY, os.path.join(HERE, "bot.py"), "status", "--dir", zd], capture_output=True, text=True)
    check(stz.returncode == 0 and "paper account since the restart (%s): invested 65.00" % M.PAPER_RULE in stz.stdout, "status prints the paper account (%s)" % (stz.stdout.splitlines()[1:2] or ["-"])[0][:110])
    shutil.rmtree(zd, ignore_errors=True)

    # without candles the run's own price decides: any price at 11x or more is a take-profit booked at exactly 11x (CANDLE_MAX_X
    # guards against glitch candles only); a restart run without a price for an old position books its last marked price, 0 only
    # when it never had one
    pd_ = tempfile.mkdtemp(prefix="memebot-runpx-")
    for coll in ("memepos", "memeexit", "memebot", "memecurve"):
        os.makedirs(os.path.join(pd_, "db", coll))
    os.makedirs(os.path.join(pd_, "candles"))
    a35, a12, a_old, a_old0 = "5" * 44, "6" * 44, "7" * 44, "8" * 44
    pdocs = {"rp-35": {"grp": "young", "addr": a35, "sym": "RUN35", "t": T0, "px": 1.0, "ticket": 3.0, "rule": M.RULE, "paper": M.PAPER_RULE, "pair": "NOPOOL35"},
             "rp-12": {"grp": "hold", "addr": a12, "sym": "RUN12", "t": T0, "px": 2.0, "ticket": 50.0, "rule": M.RULE, "paper": M.PAPER_RULE, "pair": "NOPOOL12"},
             "rp-old": {"grp": "hold", "addr": a_old, "sym": "OLDMK", "t": T0 - 10 * H, "px": 0.002, "ticket": 20.0, "rule": M.RULE, "tp": 0.4},
             "rp-old0": {"grp": "hold", "addr": a_old0, "sym": "OLDNONE", "t": T0 - 10 * H, "px": 0.002, "ticket": 20.0, "rule": M.RULE, "tp": 0.4}}
    for pid, doc in pdocs.items():
        json.dump(doc, open(os.path.join(pd_, "db", "memepos", pid + ".json"), "w"))
    json.dump({"rule": M.RULE}, open(os.path.join(pd_, "db", "memebot", "state.json"), "w"))
    json.dump({"t": T0, "px": {"rp-35": 1.0, "rp-12": 2.0, "rp-old": 0.0026}, "liq": {}, "miss": {}, "chk": {}, "cpx": {}}, open(os.path.join(pd_, "db", "memebot", "marks.json"), "w"))
    json.dump([{"address": a, "symbol": sym, "name": sym, "dexId": "raydium", "pairAddress": "P" + a[:10], "priceUsd": px_, "liquidityUsd": 50000, "marketCap": 1e6, "volH24": 1e5, "chainId": "solana"}
               for a, sym, px_ in ((a35, "RUN35", 35.0), (a12, "RUN12", 24.0))], open(os.path.join(pd_, "pairs.json"), "w"))
    rp = subprocess.run([PY, os.path.join(HERE, "memebot.py"), "run", "--dir", pd_, "--mode", "pick", "--recommend", "--now", str(T0 + H)], capture_output=True, text=True, cwd=HERE)
    pex = {}
    if rp.returncode == 0:
        for w_ in json.load(open(os.path.join(pd_, "out", "manifest.json"))):
            if w_["collection"] == "memeexit":
                e_ = json.load(open(w_["file"]))
                pex[e_["pos"]] = e_
    e35, e12, e_old, e_old0 = (pex.get(k) or {} for k in ("rp-35", "rp-12", "rp-old", "rp-old0"))
    check(rp.returncode == 0 and e35.get("why") == "tp" and e35.get("px") == 11.0 and e35.get("eur") == round(M.pos_value(pdocs["rp-35"], 1.0, 11.0), 2) == 31.58 and "at" not in e35
          and e12.get("why") == "tp" and e12.get("px") == 22.0 and e12.get("eur") == round(M.pos_value(pdocs["rp-12"], 1.0, 11.0), 2),
          "no candles: a run price of 35x is a take-profit booked at 11x (%s back for 3), 12x as well (%s back for 50) (%s)" % (
              e35.get("eur"), e12.get("eur"), (rp.stderr.strip().splitlines() or ["ok"])[-1][:100] if rp.returncode else "ok"))
    check(e_old.get("why") == "reset" and e_old.get("px") == 0.0026 and e_old.get("eur") == round(M.pos_value(pdocs["rp-old"], 1.0, 1.3), 2) == 24.14
          and e_old0.get("why") == "reset" and e_old0.get("px") == 0 and e_old0.get("eur") == 0,
          "the restart without a price this run books an old position at its last marked price (%s back), and at 0 only when it never had one (%s)" % (
              e_old.get("eur"), e_old0.get("eur")))
    shutil.rmtree(pd_, ignore_errors=True)
    # exits grouped by position once: positions_from and curve_point read the exit docs once instead of once per position and give
    # what a pass per position gave; the closed-trades fold lists the newest CLOSED_SHOWN with the count per reason over all of them
    class CountingDocs(dict):
        n = 0

        def values(self):
            CountingDocs.n += 1
            return dict.values(self)
    whys = ("tp", "stop", "time", "rug")
    many_pos = {"m%04d" % i: {"grp": "young", "addr": "x", "sym": "MANY%d" % i, "t": T0 + i, "px": 1.0, "ticket": 3.0, "rule": M.RULE, "paper": M.PAPER_RULE} for i in range(250)}
    many_ex = CountingDocs({"m%04d-1" % i: {"pos": "m%04d" % i, "t": T0 + H + i, "px": 0.5, "frac": 1.0, "why": whys[i % 4], "eur": 1.0, "grp": "young"} for i in range(250)})
    pf = M.positions_from(many_pos, many_ex)
    n_pf = CountingDocs.n
    cp = M.curve_point(many_pos, many_ex, {}, T0 + 2 * H, T0)
    n_cp = CountingDocs.n - n_pf
    same_ex = all(pf[pid]["_exits"] == sorted([e for e in dict.values(many_ex) if e.get("pos") == pid], key=lambda e: e.get("t", 0)) and pf[pid]["_left"] == 0.0 for pid in many_pos)
    check(n_pf == 1 and n_cp == 2 and same_ex and cp["g"]["young"]["n"] == 250 and cp["g"]["young"]["net"] == -500.0 and cp["paper"]["n"] == 250 and cp["paper"]["pnl"] == -500.0
          and cp["equity"] == M.BUDGET and M.exit_word("manual", "young") == "sold by hand",
          "the exits are grouped by position once (%d pass for positions_from, %d for curve_point, the same exits as a pass per position); the curve's equity is pick mode's bankroll only" % (n_pf, n_cp))
    md2 = tempfile.mkdtemp(prefix="memebot-many-")
    for coll, docs_ in (("memepos", many_pos), ("memeexit", dict(many_ex))):
        os.makedirs(os.path.join(md2, "db", coll))
        for k, v in docs_.items():
            json.dump(v, open(os.path.join(md2, "db", coll, k + ".json"), "w"))
    os.makedirs(os.path.join(md2, "db", "memebot"))
    json.dump({"paperSince": T0, "paperRule": M.PAPER_RULE}, open(os.path.join(md2, "db", "memebot", "state.json"), "w"))
    D_many = R_.collect(md2, T0 + 2 * H)
    fold = R_.closed_fold(D_many["paper"]["closed"])
    check(len(D_many["paper"]["closed"]) == 250 and fold.count("<tr><td>") == R_.CLOSED_SHOWN == 100 and "<strong>MANY249</strong>" in fold and "<strong>MANY149</strong>" not in fold
          and "250 sold, by reason: " in fold and "stop-loss −30% (63)" in fold and "take-profit +1000% (63)" in fold and "6-hour limit (62)" in fold
          and "rug: the price or the liquidity is gone (62)" in fold and "the newest 100 are listed below" in fold,
          "the closed-trades fold lists the newest 100 of 250 and counts all 250 by reason")
    yd = {"rec": {"young": [{"sym": "Y%d" % i, "name": "y", "addr": "Y%d" % i, "ageMin": 10, "score": 50, "bought": 3.0 if i < 5 else None} for i in range(7)]},
          "open": [{"p": {"grp": "young", "addr": "Y6", "paper": M.PAPER_RULE, "t": T0, "ticket": 3.0}, "ticket": 3.0, "pnl": -0.2}], "now": T0, "young_hist": []}
    ysec = R_.young_section(yd)
    check(ysec.count("already held</span>") == 1 and ysec.count("bought for 3\u00a0€</span>") == 5,
          "a held new launch below the first five is marked already held on the tab too")
    shutil.rmtree(md2, ignore_errors=True)

    print("== DexScreener out: Jupiter and GeckoTerminal data stand in, the scan still names a coin")
    sd = tempfile.mkdtemp(prefix="memebot-standin-")
    os.makedirs(os.path.join(sd, "db", "memerec"))
    tip_a = mock.coins[0]["a"]        # a tip from three hours ago whose 1 h and 2 h checks are overdue: an outage must not turn it into "gone"
    json.dump({"t": T0 - 3 * H, "rule": M.RULE, "picks": [{"sym": "OLDTIP", "addr": tip_a, "pair": tip_a[:20] + "pair", "px": 0.001, "mc": 300000, "score": 50.0, "tier": "strong"}]},
              open(os.path.join(sd, "db", "memerec", "oldtip.json"), "w"))
    urllib.request.urlopen(url + "/__dsdead?on=1").read()
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", sd, "--mock", url, "--now", str(T0), "--recommend"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    urllib.request.urlopen(url + "/__dsdead?on=0").read()
    rec_s = json.load(open(os.path.join(sd, "db", "memebot", "recommend.json"))) if os.path.exists(os.path.join(sd, "db", "memebot", "recommend.json")) else {}
    st_s = json.load(open(os.path.join(sd, "db", "memebot", "state.json"))) if os.path.exists(os.path.join(sd, "db", "memebot", "state.json")) else {}
    page_s = open(os.path.join(sd, "report.html"), encoding="utf-8").read() if os.path.exists(os.path.join(sd, "report.html")) else ""
    check(r.returncode == 0 and rec_s.get("picks") and all(c.get("standin") for c in rec_s["picks"]) and "stood in" in (st_s.get("note") or "") and "stood in" in page_s,
          "with DexScreener empty the scan named %s from Jupiter/GeckoTerminal data and said so (%s)" % ([c["sym"] for c in rec_s.get("picks", [])], (r.stderr.strip().splitlines() or [""])[-1][:100] if r.returncode else "ok"))
    tip_doc = json.load(open(os.path.join(sd, "db", "memerec", "oldtip.json")))
    check(not tip_doc.get("out") and not (tip_doc.get("outs") or {}) and "Tip checks postponed" in (st_s.get("note") or ""),
          "with DexScreener empty the overdue tip stayed unpriced instead of counting as gone (%s)" % ((st_s.get("note") or "").split("Tip checks postponed")[-1][:90]))
    shutil.rmtree(sd, ignore_errors=True)

    print("== training: walk-forward test, zero model and tuned limits on synthetic snapshot results")
    td = tempfile.mkdtemp(prefix="memebot-train-")
    sys.path.insert(0, HERE)
    import memebot as M
    import report as R
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
                          "f": {"logMc": round(lmc, 4), "buyShare": round(bs, 4), "c1": round(rng.uniform(-30, 80), 2), "ageH": round(rng.uniform(2, 40), 2),
                                "volMc": round(rng.uniform(0.05, 3.0), 3), "web": float(i % 2), "socN": float(i % 3)},
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
    flt = {g.get("filter"): g for g in (tr.get("filters") or [])}
    mig = next((g for k, g in flt.items() if k and k.startswith("terminal 'migrated play'")), None)
    check(mig and mig.get("n", 0) >= 20 and mig.get("avg") is not None and "the bot's gates (passed every gate)" in flt and flt["all candidate-like coins"]["n"] == tr.get("rows"),
          "outside filter recipes tested on the results (migrated play keeps %s of %s coins)" % (mig.get("n") if mig else None, tr.get("rows")))
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
    prev_rec = open(os.path.join(rd, "db", "memebot", "recommend.json"), encoding="utf-8").read()
    shutil.copy(os.path.join(rd, "out", "memebot__recommend.json"), os.path.join(rd, "db", "memebot", "recommend.json"))
    subprocess.run([PY, os.path.join(HERE, "report.py"), "--dir", rd], capture_output=True, text=True)
    page5 = open(os.path.join(rd, "report.html"), encoding="utf-8").read()
    open(os.path.join(rd, "db", "memebot", "recommend.json"), "w", encoding="utf-8").write(prev_rec)
    check(r.returncode == 0 and len(rec5.get("picks", [])) == 1 and rec5["picks"][0].get("tier") == "watch" and "watch only" in page5 and "No pick, one coin to watch" in page5,
          "with every coin over the zero limit the safest-looking coin is shown as a watch coin, not a pick (%s)" % [(c["sym"], c.get("tier")) for c in rec5.get("picks", [])])
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
    check(r.returncode == 0 and 1 <= len(rec.get("picks", [])) <= 2 and all(a is not None and 6 <= a <= 24 for a in ages), "2h profile recommended early coins, 6 to 24 hours old (ages %s)" % [round(a, 1) if a else a for a in ages])
    check(all(c.get("tier") in ("strong", "weak", "fallback") for c in rec.get("picks", [])), "each pick carries its tier (%s)" % [c.get("tier") for c in rec.get("picks", [])])
    st = json.load(open(os.path.join(hd, "db", "memebot", "state.json")))
    check(st.get("horizon") == "2h" and st.get("rule") == "m9-2h", "state carries the profile")
    page = open(os.path.join(hd, "report.html"), encoding="utf-8").read()
    check("for the next 2 hours" in page and "Big test: 2 hours later" in page, "page is labelled for the 2-hour horizon")
    young = rec.get("young") or []
    check(young and all(0 <= M.num(y.get("ageMin")) < 60 and y.get("addr") and "upP" in y and "floor" in y and y.get("liq", 0) >= M.YOUNG_MIN_LIQ for y in young)
          and all(y["addr"] not in {c["addr"] for c in rec.get("picks", [])} for y in young) and rec.get("youngOf", 0) >= len(young),
          "new launches under an hour old are listed with odds and safety, none of them picked (%d of %d: %s)" % (len(young), rec.get("youngOf", 0), [(y.get("sym"), y.get("ageMin")) for y in young[:4]]))
    check('id="tab-young"' in page and 'New <span class="tl-long">launches </span>&lt;1h' in page and "min old</span>" in page and "The record by age" in page and "new launch · not a pick" in page,
          "page has the new-launches tab with the coins, their cards and the age record")
    rk_young = [y for y in young if isinstance(y.get("risk"), dict) and y["risk"]]
    check(rk_young, "the new launches got safety reports with the shortlist (%d of %d)" % (len(rk_young), len(young)))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", hd, "--mock", url, "--now", str(T0 + 3 * H), "--recommend", "--horizon", "2h"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    res = glob.glob(os.path.join(hd, "db", "memesnapres", "*.json"))
    check(r.returncode == 0 and res and "Big test" in r.stdout, "the snapshot was scored 2 hours later (%d result docs)" % len(res))
    check("candles fetched beside the scan" in r.stderr and "(beside the scan," in r.stderr and not os.path.exists(os.path.join(hd, "train.next.json")),
          "the minute candles and the training ran beside the scan, and the new training doc was swapped in before the pick")
    off_f = os.path.join(hd, "db", "memebot", "office.json")
    off = json.load(open(off_f, encoding="utf-8")) if os.path.exists(off_f) else {}
    ag = {a.get("id"): a for a in off.get("agents") or []}
    check({"dispatch", "scouts", "market", "analyst", "trainer", "trader"} <= set(ag) and all(isinstance(a.get("start"), int) and isinstance(a.get("end"), int) and a["start"] <= a["end"] for a in ag.values())
          and ag["trainer"].get("bg") is True and ag.get("candles", {}).get("bg") is True and ag.get("reporter", {}).get("status") == "done" and off.get("rule") == "m9-2h" and off.get("mode") == "full"
          and "gmgn.ai" in ag["scouts"].get("blocked", []) and all(len(a.get("lines") or []) <= 60 for a in ag.values()) and ag["market"].get("out"),
          "office.json records who did what in the cycle: each step with its times, lines, blocked hosts and result (%s)" % ", ".join("%s %s" % (a.get("id"), a.get("status")) for a in off.get("agents") or []))
    import bot as B_
    ud = tempfile.mkdtemp(prefix="memebot-officeunit-")
    o_ = B_.Office(ud, 1000, "2h")
    o_.begin("scouts")
    for ln in ("! 429 rate limited by www.reddit.com, waiting 5s", "! 403 https://api.rugcheck.xyz/v1/tokens/x/report",
               "! giving up on api.mainnet-beta.solana.com for this run: rate limited 40 times", "! giving up on gmgn.ai for this run"):
        o_.line(ln)
    for i in range(80):
        o_.line("line %d" % i)
    o_.begin("candles", bg=True)
    o_.begin("candles")              # its background run failed: redone in the foreground
    o_.done("scouts")
    o_.fail()
    a_ = {a["id"]: a for a in json.load(open(os.path.join(ud, "db", "memebot", "office.json"))).get("agents") or []}
    check(a_["scouts"]["waits"] == {"www.reddit.com": 1, "api.mainnet-beta.solana.com": 40} and a_["scouts"]["blocked"] == ["gmgn.ai"] and len(a_["scouts"]["lines"]) == 60
          and a_["candles"]["bg"] is False and a_["candles"]["status"] == "failed" and all(a["status"] in ("done", "failed", "skipped", "fallback", "running") for a in a_.values())
          and not os.path.exists(os.path.join(ud, "db", "memebot", "office.json.tmp")),
          "the office recorder counts waits, marks only hosts it gave up on as blocked, keeps 60 lines, records a foreground redo and a stopped cycle")
    import contextlib, io
    go_f, job_f = os.path.join(ud, "go"), os.path.join(ud, "job.py")    # a background job's lines reach the record while it runs, and it ends as read at the end
    with open(job_f, "w") as f:
        f.write("import os, sys, time\nw = sys.stderr.buffer\nw.write(b'first\\n'); w.flush()\nw.write('second \\u00fc\\r\\n'.encode()); w.flush()\nw.write(b'a\\rb\\n\\n  \\n'); w.flush()\n"
                "while not os.path.exists(%r): time.sleep(0.05)\nw.write(b'! 429 rate limited by api.geckoterminal.com, waiting 5s\\nno newline'); w.flush()\nprint('{\"pools\": 3}')\n" % go_f)
    B_.OFFICE = B_.Office(ud, 1000, "2h")
    job = B_.start_bg([job_f, "x"], ud, agent="candles")
    t_ = time.time()
    while time.time() - t_ < 10 and len(B_.OFFICE.agents["candles"]["lines"]) < 4:
        time.sleep(0.05)
    mid = list(B_.OFFICE.agents["candles"]["lines"]) if job["p"].poll() is None else []
    open(go_f, "w").close()
    with contextlib.redirect_stderr(io.StringIO()):      # finish_bg echoes the job's lines into the cycle's log
        got = B_.finish_bg(job)
    ref = B_.Office(ud, 1000, "2h")
    ref.begin("candles", bg=True)
    for ln in open(job["err"].name, encoding="utf-8", errors="replace"):
        ref.line(ln.rstrip(), "candles")
    check(mid == ["first", "second \u00fc", "a", "b"] and got == {"pools": 3} and B_.OFFICE.agents["candles"]["lines"] == ref.agents["candles"]["lines"]
          and len(ref.agents["candles"]["lines"]) == 6 and B_.OFFICE.agents["candles"]["waits"] == {"api.geckoterminal.com": 1},
          "a background job's lines reach the office while it runs (%d before it ended) and the record ends as if read at the end" % len(mid))
    job2_f, job3_f, go3 = os.path.join(ud, "job2.py"), os.path.join(ud, "job3.py"), os.path.join(ud, "go3")
    with open(job2_f, "w") as f:
        f.write("import sys\nsys.stderr.write('one\\ntwo\\n')\nprint('{\"ok\": 1}')\n")
    with open(job3_f, "w") as f:
        f.write("import os, sys, time\nsys.stderr.write('before\\n'); sys.stderr.flush()\nwhile not os.path.exists(%r): time.sleep(0.05)\nsys.stderr.write('after\\n')\n" % go3)
    B_.OFFICE = B_.Office(ud, 1000, "2h")
    job2 = B_.start_bg([job2_f, "x"], ud, agent="trainer")
    job2["p"].wait()
    job2["tail"].join(5)
    ended = not job2["tail"].is_alive()
    with contextlib.redirect_stderr(io.StringIO()):
        got2 = B_.finish_bg(job2)
    job3 = B_.start_bg([job3_f, "x"], ud, agent="candles")
    t_ = time.time()
    while time.time() - t_ < 10 and B_.OFFICE.agents["candles"]["lines"] != ["before"]:
        time.sleep(0.05)
    B_.OFFICE.fail()                 # the step at work failed: the cycle stops, its record is saved, the tails stop filing
    open(go3, "w").close()
    job3["p"].wait()
    time.sleep(1.5)
    saved3 = {a["id"]: a for a in json.load(open(os.path.join(ud, "db", "memebot", "office.json"))).get("agents") or []}
    check(ended and got2 == {"ok": 1} and B_.OFFICE.agents["trainer"]["lines"] == ["one", "two"] and B_.OFFICE.agents["candles"]["lines"] == ["before"]
          and saved3["candles"]["lines"] == ["before"] and saved3["candles"]["status"] == "failed" and not job3["tail"].is_alive() and not B_.BG_JOBS,
          "a background job's tail ends once its process exited and its file is read; a stopped cycle stops the tails, so the record saved is the one it ends with")
    job3["out"].close()
    job3["err"].close()
    B_.OFFICE = B_.Office(ud, 1000, "2h")
    B_.OFFICE.begin("candles", bg=True)
    B_.OFFICE.line("first", "candles")
    lb = os.path.join(ud, "live-remote.git")
    subprocess.run(["git", "init", "-q", "--bare", lb], check=True)
    git_show = lambda: json.loads(subprocess.run(["git", "-C", lb, "show", "live:live.json"], capture_output=True, text=True).stdout or "{}")
    git_head = lambda: subprocess.run(["git", "-C", lb, "rev-parse", "-q", "--verify", "live"], capture_output=True, text=True).stdout.strip()
    def wait_head(other, secs):                            # the branch's commit once it is not `other`, or "" after secs
        t_ = time.time()
        while time.time() - t_ < secs:
            h = git_head()
            if h and h != other:
                return h
            time.sleep(0.02)
        return ""
    every0, beat0, wait0 = B_.LIVE_EVERY, B_.LIVE_BEAT, B_.LIVE_WAIT
    B_.LIVE_EVERY, B_.LIVE_BEAT = 0.2, 1.5                 # the pushing thread at a fast pace: a changed record at once, an unchanged one as a heartbeat
    lv = B_.Live(ud, lb)
    h1 = wait_head("", 10)
    t1, l1 = time.time(), git_show()
    time.sleep(0.6)
    h2 = git_head()                                        # nothing changed and the last push is young: no push
    h3 = wait_head(h1, 5)                                  # nothing changed, the last push is LIVE_BEAT old: the heartbeat
    beat, l3 = time.time() - t1, git_show()
    B_.OFFICE.line("one more", "candles")
    t2 = time.time()
    h4 = wait_head(h3, 5)
    quick, l4 = time.time() - t2, git_show()
    lv.finish()
    l5 = git_show()
    n_commits = subprocess.run(["git", "-C", lb, "rev-list", "--count", "live"], capture_output=True, text=True).stdout.strip()
    B_.LIVE_EVERY, B_.LIVE_BEAT = every0, beat0
    check(l1.get("live") is True and isinstance(l1.get("updated"), int) and [a["id"] for a in l1.get("agents") or []] == ["candles"] and h2 == h1
          and h3 and 1.0 < beat < 4 and l3.get("live") is True and l3.get("updated", 0) - l1["updated"] >= 1300 and l3.get("agents") == l1.get("agents")
          and h4 and quick < 1.0 and l4["agents"][0]["lines"][-1] == "one more" and l5.get("live") is False and l5["agents"][0]["lines"][-1] == "one more" and n_commits == "1",
          "the live view pushes a changed record at once, an unchanged one only as a heartbeat (%.1f s after the last push, the same record with a fresh updated), "
          "ends with live false on a one-commit branch" % beat)
    err_ = io.StringIO()
    fake = os.path.join(ud, "fakebin")
    os.makedirs(fake)
    with open(os.path.join(fake, "git"), "w") as f:
        f.write("#!/bin/sh\nsleep 30\n")
    os.chmod(os.path.join(fake, "git"), 0o755)
    path0 = os.environ["PATH"]
    with contextlib.redirect_stderr(err_):
        lv2 = B_.Live(ud, os.path.join(ud, "no-such-remote.git"))
        lv2.stop.set()
        lv2.push(True); lv2.push(True); lv2.finish()
        os.environ["PATH"], B_.LIVE_WAIT = fake + os.pathsep + path0, 1
        t_ = time.time()
        try:
            lv_h = B_.Live(ud, lb)
            lv_h.stop.set()
            lv_h.push(True)
        finally:
            os.environ["PATH"], B_.LIVE_WAIT = path0, wait0
        hung = time.time() - t_
    check(err_.getvalue().count("live view: push failed") == 2 and hung < 3,
          "a failed or hung push is logged once and given up (%.1f s)" % hung)
    hang = os.path.join(ud, "hang")                        # a push that hangs while the cycle ends: cut short, the last snapshot goes out at once
    fake2 = os.path.join(ud, "fakebin2")
    os.makedirs(fake2)
    with open(os.path.join(fake2, "git"), "w") as f:
        f.write('#!/bin/sh\nif [ "$3" = push ] && [ -e "%s" ]; then sleep 30; fi\nexec "%s" "$@"\n' % (hang, shutil.which("git")))
    os.chmod(os.path.join(fake2, "git"), 0o755)
    open(hang, "w").close()
    err3 = io.StringIO()
    os.environ["PATH"], B_.LIVE_WAIT = fake2 + os.pathsep + path0, 5
    try:
        lv3 = B_.Live(ud, lb)
        lv3.stop.set()
        th_ = threading.Thread(target=lv3.push, args=(True,), daemon=True)
        th_.start()
        t_ = time.time()
        while time.time() - t_ < 5 and not (lv3.proc and lv3.proc.args[3:4] == ["push"]):
            time.sleep(0.02)
        os.remove(hang)
        t_ = time.time()
        with contextlib.redirect_stderr(err3):
            lv3.finish()
        cut = time.time() - t_
        th_.join(5)
    finally:
        os.environ["PATH"], B_.LIVE_WAIT = path0, wait0
    l6 = git_show()
    check(cut < 3 and not th_.is_alive() and l6.get("live") is False and l6.get("updated", 0) > l5.get("updated", 0) and "push failed" not in err3.getvalue(),
          "the end of a cycle kills a push still hanging and sends the last snapshot at once (%.1f s, the wait limit is 5 s)" % cut)
    shutil.rmtree(ud, ignore_errors=True)
    recs = [json.load(open(f)) for f in glob.glob(os.path.join(hd, "db", "memerec", "*.json"))]
    scored = [o for doc in recs for o in (doc.get("out") or {}).get("picks", [])]
    page2 = open(os.path.join(hd, "report.html"), encoding="utf-8").read()
    yd = [json.load(open(f)) for f in glob.glob(os.path.join(hd, "db", "memeyoung", "*.json"))]
    y1 = [o for doc in yd for o in ((doc.get("outs") or {}).get("1") or {}).get("picks", [])]
    check(yd and y1 and "What the earlier new launches did" in page2, "the new launches are recorded and priced again at 1 h too (%d docs, %d results)" % (len(yd), len(y1)))
    with_peak = [o for o in y1 if o.get("hi") is not None]
    okp = lambda pth: (isinstance(pth, list) and len(pth) >= 55 and pth[0][0] <= 1 and all(len(c) == 5 and c[3] <= c[4] <= c[2] and c[3] <= c[1] <= c[2] for c in pth)
                       and all(pth[k][0] < pth[k + 1][0] for k in range(len(pth) - 1)))
    check(with_peak and all(o.get("cv") == M.CANDLE_V and okp(o.get("path")) for o in with_peak),
          "every candle-priced result keeps its window's minute path, oldest first from minute 0, for exit-rule replays (%s candles in the first)" % (len(with_peak[0].get("path") or []) if with_peak else "-"))
    check(with_peak and all(o.get("tp") is not None and o["hi"] >= 2.5 for o in with_peak) and "peak" in page2 and "selling at +20% when reached" in page2,
          "the minute candles give each result its peak and the take-profit outcome (%d of %d with candles)" % (len(with_peak), len(y1)))

    def tp_ok(o):
        if not isinstance(o.get("tpx"), dict) or set(o["tpx"]) != {M.tp_key(lv) for lv in M.TP_LEVELS} or M.num(o.get("tpFrom")) is None:
            return False
        for lv in M.TP_LEVELS:
            m, at = M.take_profit(o["path"], o["mult"], lv, o["tpFrom"])
            if (o.get("tpMin") or {}).get(M.tp_key(lv)) != at or o["tpx"][M.tp_key(lv)] != (M.tip_net(m) if at is not None else o["eur"]):
                return False
        return True
    recs2 = [json.load(open(f)) for f in glob.glob(os.path.join(hd, "db", "memerec", "*.json"))]
    out_c = [o for doc in recs2 for o in (doc.get("out") or {}).get("picks", []) if o.get("path")]
    tp_all = with_peak + out_c + [o for doc in recs2 for o in ((doc.get("outs") or {}).get("1") or {}).get("picks", []) if o.get("path")]
    first = [doc for doc in recs2 + yd if M.num(doc.get("t")) == T0]     # the second cycle's fake clock runs hours ahead of the refresh's real one: no pricedAt there
    check(first and all(M.num(doc.get("pricedAt")) and 0 <= M.num(doc["pricedAt"]) - T0 <= H for doc in first) and tp_all and all(tp_ok(o) for o in tp_all)
          and any("20" in (o.get("tpMin") or {}) and "50" not in o["tpMin"] for o in tp_all) and out_c and len(out_c) == len(scored)
          and "Take-profit levels, 1 h later" in page2 and "sold at +30%" in page2 and "after %d min" % tp_all[0]["tpMin"]["20"] in page2,
          "every result with candles (1 h, and now the horizon too: %d of %d) is replayed at +10/+20/+30/+50%% from the entry price on (%s)" % (len(out_c), len(scored), tp_all[0].get("tpMin") if tp_all else "-"))
    one_h = [o for doc in recs for o in ((doc.get("outs") or {}).get("1") or {}).get("picks", [])]
    check(recs and scored and one_h and "Track record" in r.stdout and "Recommendations, hour by hour" in page2 and "next ≈ " in page2 and "next scan starts about" not in page2
          and "1 h later" in page2 and "24 h later" in page2,
          "the tips were recorded and priced again at 1 h and at the horizon (%d docs, %d scored, %d at 1 h)" % (len(recs), len(scored), len(one_h)))
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", hd, "--now", str(T0 + 25 * H), "--recommend", "--horizon", "2h", "--offline"], capture_output=True, text=True, env=dict(os.environ, MEMEBOT_PAUSE="0"))
    recs = [json.load(open(f)) for f in glob.glob(os.path.join(hd, "db", "memerec", "*.json"))]
    day = [o for doc in recs for o in ((doc.get("outs") or {}).get("24") or {}).get("picks", [])]
    page3 = open(os.path.join(hd, "report.html"), encoding="utf-8").read()
    check(r.returncode == 0 and day and "24 h later: %d tips priced" % len(day) in page3, "a day later the tips carry their 24 h result too (%d)" % len(day))
    one_h3 = [o for doc in recs for o in M.settled((doc.get("outs") or {}).get("1"), 1.0) if M.num(o.get("eur")) is not None]
    m_profit = re.search(r'<p class="verdict (good|bad)"><strong>(Up so far|Down so far)\.</strong> (\d+) tips? priced 1 h later: (\d+) went up, (\d+) went to zero, together <strong>([^<]+)</strong>', page3)
    tot3 = sum(M.num(o["eur"]) for o in one_h3)
    check(m_profit and "Tip record" in page3 and int(m_profit.group(3)) == len(one_h3) and m_profit.group(2) == ("Up so far" if tot3 > 0 else "Down so far")
          and m_profit.group(6).replace("\u2212", "").replace("+", "").replace("-", "") == "%.2f" % abs(tot3) and ('aria-label="Running profit of the tips"' in page3 or len({M.num(doc.get("t")) for doc in recs if M.settled((doc.get("outs") or {}).get("1"), 1.0)}) < 2),
          "the page ends with the tip record's verdict and the running-total chart (%s, %d tips, %+.2f)" % (m_profit.group(2) if m_profit else "missing", len(one_h3), tot3))
    m_chain = re.search(r"one after the other \(sold after 1 h, after fees\) would be ([\d.,]+) now after (\d+) tips", page3)
    check(m_chain and int(m_chain.group(2)) >= 1, "the page says what 20 riding every tip would be now (%s)" % (m_chain.group(0)[-40:] if m_chain else "missing"))
    check(not glob.glob(os.path.join(hd, "db", "memesnap", "*-1.json")) or all(os.path.basename(f)[:-5] not in {os.path.basename(x)[:-5] for x in res} for f in glob.glob(os.path.join(hd, "db", "memesnap", "*.json"))), "scored raw snapshots are removed")
    shutil.rmtree(hd, ignore_errors=True)

    check(spot_modes and not any(on for _, on in spot_modes),
          "the launch spotter starts in no scan without --recommend, light ones included (%s)" % ", ".join(sorted({m for m, _ in spot_modes})))
    spotter_checks(check)
    import selftest_traps                       # the launch radar's rule core and study weights (traps.py)
    selftest_traps.checks(check, {})
    import selftest_radar                       # the launch radar job (launch_radar.py, radar_src.py, radar.yml)
    nosleep, time.sleep = time.sleep, REAL_SLEEP   # the radar's request rules are checked in real time (1.1 s between RPC calls)
    try:
        selftest_radar.checks(check)
    finally:
        time.sleep = nosleep
    SKIPS.extend(selftest_radar.SKIPPED)
    import selftest_peak                        # the peak category: best price within 6 h of every paper position (peak.py)
    selftest_peak.peak_checks(check)
    import app as A_x, launch_radar as LR_x       # cross-review fixes of the 13.10 build
    ry, sy = open(os.path.join(HERE, ".github", "workflows", "radar.yml")).read(), open(os.path.join(HERE, ".github", "workflows", "scan.yml")).read()
    peaks_job = sy[sy.find("\n  peaks:"):]
    check(A_x._sym("AB\u202eCD\u2066E\u200f") == "ABCDE" and A_x._sym("\u202e") == "?"
          and "\\u202a-\\u202e\\u2066-\\u2069" in open(os.path.join(HERE, "page_radar.py"), encoding="utf-8").read()
          and ry.count("persist-credentials: false") == 1 and "persist-credentials: false" in peaks_job[:peaks_job.find("Restore the bot's state")]
          and "/dispatches" not in open(os.path.join(HERE, "launch_radar.py"), encoding="utf-8").read() and not hasattr(LR_x.Radar, "chain")
          and "run: python3 launch_radar.py round --dir rd\n" in ry and '"inputs": {"source": "hourly"}' in sy,
          "build: bidi controls are stripped from push titles and the radar page's text, the radar job and the peaks job check out without "
          "the token in .git/config, a radar run is one round and never starts another (the scan's last step starts one per full scan)")
    check(not re.search(r"vars\.[A-Z_]+ *[!=]=", ry + sy) and ry.count("(vars.MEMEBOT_RADAR || '1') != '0'") == 1
          and sy.count("(vars.MEMEBOT_RADAR || '1') != '0'") == 1 and sy.count("(vars.MEMEBOT_PEAKS || '1') != '0'") == 1,
          "build: a repository variable that is not set counts as on (GitHub skipped the radar job on a bare vars.X != '0')")
    import page_account as PA_x, peak as PK_x       # the trades before the restart get their best within 6 h too, shown apart
    tmpo = tempfile.mkdtemp(prefix="mb-old-")
    os.makedirs(os.path.join(tmpo, "db", "memepeak"))
    with open(os.path.join(tmpo, "db", "memepeak", "o1.json"), "w") as f:
        json.dump({"v": 1, "state": "ok", "src": "m1", "x": 3.0, "x6": 0.5}, f)
    pos_o = {"o1": {"grp": "hold", "t": 1000, "ticket": 20.0, "px": 1.0, "_left": 0, "_exits": [{"eur": 10.0, "t": 2000, "px": 0.5}]},
             "n1": {"grp": "young", "t": 5000, "ticket": 3.0, "px": 1.0, "_left": 1, "_exits": []}}
    A_o = PA_x.load(tmpo, 10 ** 13, pos=pos_o, px={}, since=4000)
    o_ = A_o.get("old") or {}
    check(PK_x.priced(pos_o["o1"]) and PK_x.priced(pos_o["n1"]) and not PK_x.priced({"grp": "watch"}) and o_.get("n") == 1 and o_.get("priced") == 1
          and o_.get("same") == -10.0 and (o_.get("best") or {}).get("pnl", 0) > 0 and A_o["counts"]["M"] == 1,
          "build: the peak job prices the trades bought before the restart too, and the account sums their best within 6 h apart "
          "(not in the account since the restart): %s" % o_)
    shutil.rmtree(tmpo, ignore_errors=True)
    import yaml as Y_x                            # the hand-started peaks backfill: manual only, the scan's group, no token kept, a bigger budget
    pb = Y_x.safe_load(open(os.path.join(HERE, ".github", "workflows", "peaks-backfill.yml")))
    pb_on, pb_job = pb.get(True) or pb.get("on") or {}, (pb.get("jobs") or {}).get("backfill") or {}
    pb_steps = pb_job.get("steps") or []
    pb_run = " ".join(st_.get("run") or "" for st_ in pb_steps)
    import peak as PK_y
    pk_before = PK_y.PEAK_MAX_ITEMS
    tmp_pb = tempfile.mkdtemp(prefix="mb-pb-")
    with contextlib.redirect_stdout(io.StringIO()):
        PK_y.main(["run", "--dir", tmp_pb, "--deadline-s", "1", "--max-items", "280"])
    pk_after = PK_y.PEAK_MAX_ITEMS
    PK_y.PEAK_MAX_ITEMS = pk_before
    shutil.rmtree(tmp_pb, ignore_errors=True)
    check(list(pb_on) == ["workflow_dispatch"] and (pb.get("concurrency") or {}).get("group") == "memebot-scan"
          and (pb.get("concurrency") or {}).get("cancel-in-progress") is False and pb_steps[:1] == [{"uses": "actions/checkout@v4", "with": {"persist-credentials": False}}]
          and "peak.py run --dir mb --deadline-s" in pb_run and "--max-items" in pb_run and "bot.py sync" in pb_run and pk_after == 280 and pk_before == 60,
          "build: the peaks backfill is started by hand only, waits in the scan's group, keeps no token, and may price more windows (--max-items)")
    import page_radar as PR_x, page_office as PO_x
    yh = PR_x.young_head({"a": {"v": "trap"}}, [{"addr": "a"}])
    check("body:has(#tab-radar:checked) .wrap > .live { display:none }" in PR_x.CSS and "the trap check does not stop them (fake money)" in yh
          and '<span class="chip bad">1 with traps or unchecked</span>' in yh and ".fold-lite > summary { min-height:44px" in PO_x.CSS,
          "build: the Radar tab hides the full scan's Scan now box (the radar has its own Start), the New tab says paper buys ignore the "
          "trap check, the daily overview's table fold is a 44 px target")
    import selftest_scanside                    # the scan side of the radar and the peak category (scan.yml, bot.py, app.py)
    selftest_scanside.scanside_checks(check)
    import selftest_audit                       # the error audit's fixes (WP7), one check each
    selftest_audit.audit_checks(check)

    print("== sync: page and small docs to a results branch")
    bare = tempfile.mkdtemp(prefix="memebot-bare-")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    r = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", d, "--remote", bare], capture_output=True, text=True)
    check(r.returncode == 0, "bot.py sync pushes (%s)" % (r.stderr.strip().splitlines() or ["?"])[-1][:100])
    ls = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", "results"], capture_output=True, text=True).stdout.split()
    check("report.html" in ls and any(x.startswith("db/memepos/") for x in ls) and any(x.startswith("db/memebot/") for x in ls) and "db/memebot/office.json" in ls,
          "results branch holds report.html and the small docs, office.json among them (%d files)" % len(ls))
    check(not any(x.startswith(("db/memesnap/", "db/memesnapres/")) for x in ls), "the big snapshots stay local")
    r2 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "sync", "--dir", d, "--remote", bare], capture_output=True, text=True)
    check(r2.returncode == 0 and "nothing new" in r2.stderr, "a second sync with no changes is a no-op push")
    spy = tempfile.mkdtemp(prefix="memebot-gitspy-")       # a git that notes every call, so the test sees what the cycle asked of git
    with open(os.path.join(spy, "git"), "w") as f:
        f.write('#!/bin/sh\necho "$@" >> "%s"\nexec "%s" "$@"\n' % (os.path.join(spy, "calls.log"), shutil.which("git")))
    os.chmod(os.path.join(spy, "git"), 0o755)
    r3 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(T0 + 100 * H), "--push", "--remote", bare], capture_output=True, text=True,
                        env=dict(os.environ, MEMEBOT_PAUSE="0", RESULTS_URL=bare, PATH=spy + os.pathsep + os.environ["PATH"]))
    check(r3.returncode == 0 and "sync: new commit" in r3.stderr, "cycle --push syncs after the cycle")
    calls = open(os.path.join(spy, "calls.log")).read() if os.path.exists(os.path.join(spy, "calls.log")) else ""
    heads = subprocess.run(["git", "-C", bare, "branch", "--list"], capture_output=True, text=True).stdout.split()
    check(calls and not re.search(r"live\.git|refs/heads/live|live\.json", calls) and "live" not in heads and not os.path.exists(os.path.join(d, "live.git")) and "live view" not in r3.stderr,
          "a cycle without MEMEBOT_LIVE never touches git for the live view (%d git calls, all for the sync)" % len(calls.splitlines()))
    r4 = subprocess.run([PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(T0 + 101 * H)], capture_output=True, text=True,
                        env=dict(os.environ, MEMEBOT_PAUSE="0", MEMEBOT_LIVE="1", RESULTS_URL=bare))
    lj = json.loads(subprocess.run(["git", "-C", bare, "show", "live:live.json"], capture_output=True, text=True).stdout or "{}")
    files = subprocess.run(["git", "-C", bare, "ls-tree", "--name-only", "live"], capture_output=True, text=True).stdout.split()
    n_live = subprocess.run(["git", "-C", bare, "rev-list", "--count", "live"], capture_output=True, text=True).stdout.strip()
    off4 = json.load(open(os.path.join(d, "db", "memebot", "office.json"), encoding="utf-8"))
    check(r4.returncode == 0 and "live view: the office goes to branch live" in r4.stderr and "push failed" not in r4.stderr and files == ["live.json"] and n_live == "1"
          and lj.get("live") is False and isinstance(lj.get("updated"), int) and lj.get("t") == off4.get("t") and lj.get("agents") == off4.get("agents")
          and {"dispatch", "trader", "reporter"} <= {a.get("id") for a in lj.get("agents") or []},
          "with MEMEBOT_LIVE=1 a cycle pushes live.json to the branch live of RESULTS_URL, the last one live false with the office's agents (%s)" % ", ".join(a.get("id", "?") for a in lj.get("agents") or []))
    shutil.rmtree(bare, ignore_errors=True)
    shutil.rmtree(spy, ignore_errors=True)

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

    app_tests(check, mock, url)
    import selftest_account                     # the paper account block (page_account.py)
    selftest_account.account_checks(check, SKIPS)
    import selftest_radarui                     # the Radar tab, the trap-check line and the "no good coin" marks (page_radar.py)
    selftest_radarui.checks(check, {"skips": SKIPS})
    import selftest_office                      # the office's agent cards, the radar desk and the daily overview (page_office.py)
    selftest_office.office_checks(check, SKIPS)

    keep = os.environ.get("MEMEBOT_KEEP")
    if keep:
        shutil.rmtree(keep, ignore_errors=True); shutil.copytree(os.path.join(d, "db"), os.path.join(keep, "db")); print("kept db in " + keep)

    shutil.rmtree(d, ignore_errors=True)
    srv.shutdown()
    print("\n%d checks failed" % len(fails) if fails else "\nALL PASS" + (" (%d check group%s skipped: %s)" % (len(SKIPS), "" if len(SKIPS) == 1 else "s", "; ".join(SKIPS)) if SKIPS else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    import urllib.request
    main()
