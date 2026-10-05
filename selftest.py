#!/usr/bin/env python3
"""selftest.py: runs the whole bot against a local mock of every API (~1100 synthetic coins) with a fake clock.

  python3 selftest.py            -> prints each cycle's note and PASS/FAIL per check, exit code 1 on any failure

What it proves: the fetch layer parses every source's response shape into the pipe-row files, gather merges them into a 1000+ coin
universe, the scan gates and scores them, exactly two coins get bought for 20 each out of the 40 bankroll, no third buy happens
while the money is deployed, exits (half at 2x, stop at -50%, 3-day time limit) return money to the bankroll, the 24h big test
scores every snapshotted coin and the weights get learned. GMGN is mocked as blocked (403) to exercise the circuit breaker.
"""
import json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse
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

    def handle(self, path, query):
        self.hits[path.split("/")[1]] = self.hits.get(path.split("/")[1], 0) + 1
        q = urllib.parse.parse_qs(query)
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
        if path.startswith("/api.rugcheck.xyz/v1/stats/new_tokens"):
            return 200, [{"mint": c["a"]} for c in self.coins[150:200]]
        m = re.match(r"^/api\.rugcheck\.xyz/v1/tokens/([^/]+)/report$", path)
        if m and m.group(1) in self.by_a:
            c = self.by_a[m.group(1)]
            return 200, {"mint": c["a"], "score": 1500, "score_normalised": 12, "risks": c["risks"], "totalHolders": 1234, "tokenMeta": {"mutable": False},
                         "token": {"supply": 1e15}, "creatorBalance": 1e13, "graphInsidersDetected": 2,
                         "topHolders": [{"owner": h, "pct": 5.0 - i, "insider": i == 0} for i, h in enumerate(c["holders"])],
                         "markets": [{"lp": {"lpLockedPct": c["lp"]}}], "launchpad": {"name": "pump.fun"}}
        if path.startswith("/api.geckoterminal.com/"):
            pg = int(q.get("page", ["1"])[0])
            kind = "trending" if "trending" in path else ("new" if "new_pools" in path else "top")
            off = {"trending": 200, "new": 300, "top": 400}[kind] + (pg - 1) * 20
            sub = self.coins[off:off + 20]
            return 200, {"data": [self.gt_pool(c) for c in sub], "included": [{"id": "solana_" + c["a"], "type": "token", "attributes": {"symbol": c["sym"], "name": c["name"]}} for c in sub]}
        if path.startswith("/api.coingecko.com/"):
            return 200, {"coins": [{"item": {"symbol": c["sym"], "name": c["name"], "market_cap_rank": 500 + i, "data": {"price_change_percentage_24h": {"usd": 3.3}}}} for i, c in enumerate(self.coins[:15])]}
        if path.startswith("/frontend-api-v3.pump.fun/coins"):
            off = int(q.get("offset", ["0"])[0]); base = 500 if "market_cap" in q.get("sort", [""])[0] else 700
            return 200, [{"mint": c["a"], "symbol": c["sym"], "name": c["name"], "usd_market_cap": c["mc"], "market_cap": 50, "ath_market_cap": c["mc"] * 2, "reply_count": 12,
                          "is_currently_live": False, "complete": True, "created_timestamp": T0 - 5 * H, "twitter": "https://x.com/a", "website": None, "telegram": None}
                         for c in self.coins[base + off:base + off + 50]]
        if path.startswith("/lite-api.jup.ag/tokens/v2/"):
            off = {"toptrending": 800, "toporganicscore": 850, "recent": 900}[path.split("/")[4]]
            return 200, [{"id": c["a"], "symbol": c["sym"], "name": c["name"], "usdPrice": c["px"], "mcap": c["mc"], "fdv": c["mc"], "liquidity": c["liq"], "holderCount": 900,
                          "organicScore": 55.5, "audit": {"topHoldersPercentage": 22.0}, "isVerified": False, "firstPool": {"createdAt": "2025-03-01T00:00:00Z"},
                          "stats1h": {"priceChange": 1.0, "numBuys": 10, "numSells": 5, "numNetBuyers": 3}, "stats6h": {"priceChange": 2.0},
                          "stats24h": {"priceChange": 5.0, "buyVolume": 1000, "sellVolume": 800, "numBuys": 100, "numSells": 80, "numTraders": 50, "numNetBuyers": 10, "holderChange": 20}}
                         for c in self.coins[off:off + 50]]
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
    fails = []

    def check(ok, what):
        print(("  PASS " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)

    def cycle(now, force=False):
        cmd = [PY, os.path.join(HERE, "bot.py"), "cycle", "--dir", d, "--mock", url, "--now", str(now)] + (["--force"] if force else [])
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

    print("== cycle 1: first full scan, expect 2 buys of 20")
    out, err = cycle(T0)
    g = json.loads(subprocess.run([PY, os.path.join(HERE, "memebot.py"), "gather", "--dir", d, "--now", str(T0)], capture_output=True, text=True).stdout)
    check(g["coins"] >= 1000, "universe has %d coins (>= 1000)" % g["coins"])
    check(g["geckoterminal"] > 0 and g["pumpfun"] > 0 and g["jupiter"] > 0 and g["coingecko"] > 0 and g["news"] > 0, "every mocked source parsed: gt %d pf %d jup %d cg %d news %d" % (g["geckoterminal"], g["pumpfun"], g["jupiter"], g["coingecko"], g["news"]))
    check("giving up on gmgn.ai" in err, "GMGN 403 trips the circuit breaker")
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
    check(all(p["_left"] <= 1e-9 for p in P.values() if p["t"] <= T0 + 4 * H), "every old position is closed (%s)" % sorted(e["why"] for e in ex.values()))
    c = cash()
    check(c["free"] > 20 and c["open"] <= 2, "bankroll recovered: free %.2f, %d open" % (c["free"], c["open"]))
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
    check("liquidity ÷ market cap" in page and "price unchanged" in page and "sold at" in page and "sells" in page, "glossary, big-test baseline, sale multiples and sell levels on the page")
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
