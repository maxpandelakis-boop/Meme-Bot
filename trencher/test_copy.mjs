// node trencher/test_copy.mjs : checks the copy-trading engine.
import assert from "node:assert/strict";
import * as C from "./copy-engine.js?v=0.9.8";

const W = "Trader1111111111111111111111111111111111111", M = "Coin1111111111111111111111111111111111pump";
const tb = (owner, mint, amt) => ({ owner, mint, uiTokenAmount: { uiAmount: amt } });
const tx = (pre, post, solPre, solPost) => ({ meta: { err: null, preTokenBalances: pre, postTokenBalances: post, preBalances: [solPre], postBalances: [solPost] },
                                               transaction: { message: { accountKeys: [{ pubkey: W }] } } });
// buy: token up, SOL down
let t = C.walletTrades(tx([], [tb(W, M, 1000)], 2e9, 1e9), W);
assert.deepEqual(t.map(x => [x.side, x.mint]), [["buy", M]]); assert.equal(t[0].solDelta, -1);
// partial sell
t = C.walletTrades(tx([tb(W, M, 1000)], [tb(W, M, 250)], 1e9, 2e9), W);
assert.equal(t[0].side, "sell"); assert.equal(t[0].frac, 0.75);
// a transfer in (nothing paid) and a transfer out (nothing received) are not trades
assert.equal(C.walletTrades(tx([], [tb(W, M, 1000)], 1e9, 1e9 - 5000), W).length, 0);
assert.equal(C.walletTrades(tx([tb(W, M, 1000)], [], 1e9, 1e9 + 2039280 - 5000), W).length, 0);   // rent of the closed account back
assert.equal(C.walletTrades(tx([], [tb(W, M, 1000), tb(W, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 0)], 1e9, 1e9), W).length, 0);
assert.equal(C.walletTrades(tx([tb(W, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 50)], [tb(W, M, 1000), tb(W, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 0)], 1e9, 1e9), W)[0].side, "buy");   // paid in USDC
// other owners and WSOL ignored, failed tx ignored
assert.equal(C.walletTrades(tx([tb("x", M, 1)], [tb("x", M, 5)], 0, 0), W).length, 0);
assert.equal(C.walletTrades(tx([], [tb(W, "So11111111111111111111111111111111111111112", 5)], 0, 0), W).length, 0);
assert.equal(C.walletTrades({ meta: { err: {} } }, W).length, 0);

// account: copy a buy, take profit at 10x
const P = { ...C.COPY_DEFAULTS, deposit: 100, sizePct: 0, stake: 20, maxOpen: 6, takeProfitX: 10 };
const acc = C.newAccount(P, 0);
let r = C.copyBuy(acc, { mint: M, symbol: "C", price: 1e-5, liq: 50000, mc: 10000, trader: "aiwass", lagSec: 30, now: 1 }, P);
assert.ok(r.ok); assert.equal(acc.cash, 80);
assert.ok(C.copyBuy(acc, { mint: M, price: 1e-5, liq: 50000, now: 2 }, P).skip);
assert.ok(Math.abs(C.accountValue(acc, { [M]: { price: 1e-5, liq: 50000 } }) - 99) < 1.2);
assert.deepEqual(C.riskExits(acc, { [M]: { price: 1.05e-4, liq: 50000 } }, P), [{ mint: M, why: "tp" }]);
r = C.copySell(acc, { mint: M, price: 1.05e-4, liq: 50000, why: "tp", now: 3 });
assert.ok(r.ok); assert.ok(!acc.pos[M]); assert.ok(acc.cash > 250, "10x of 20 " + acc.cash);
const s = C.stats(acc); assert.equal(s.copies, 1); assert.equal(s.wins, 1); assert.ok(s.best.multiple > 9);
// stake above 20 is not capped by the per-coin book
const a2 = C.newAccount({ ...P, deposit: 500, stake: 100 }, 0);
C.copyBuy(a2, { mint: M, price: 1, liq: 1e6, now: 1 }, { ...P, stake: 100 }); assert.equal(a2.cash, 400);
console.log("ok: copy engine");

// rankWallets: winner first, bots and buy-only wallets dropped
{
  const tr = (w, kind, usd, tok) => ({ tx_from_address: w, kind, volume_in_usd: usd, [kind === "buy" ? "to_token_amount" : "from_token_amount"]: tok });
  const pools = [{ coin: "A", trades: [tr("win", "buy", 10, 100), tr("win", "sell", 30, 100), tr("lose", "buy", 10, 100), tr("lose", "sell", 5, 100),
                                       tr("hold", "buy", 50, 10), ...Array.from({ length: 30 }, () => tr("bot", "sell", 9, 1)), tr("bot", "buy", 1, 1)] },
                 { coin: "B", trades: [tr("win", "buy", 10, 100), tr("win", "sell", 15, 50)] }];
  const r = C.rankWallets(pools);
  assert.deepEqual(r.map(x => x.wallet), ["win"]);
  assert.ok(Math.abs(r[0].pnl - 30) < 1e-9, String(r[0].pnl));   // 20 on A + (15 - 5) on B
  assert.equal(r[0].wins, 2);
  console.log("ok: rank wallets");
}

// hot coins: reddit mentions and score
{
  const coins = [{ mint: "MintA111", symbol: "PONS" }, { mint: "MintB222", symbol: "SOL" }, { mint: "MintC333", symbol: "cat" }];
  const posts = [{ title: "PONS to the moon", selftext: "" }, { title: "just bought $cat", selftext: "" }, { title: "ca: MintA111", selftext: "" },
                 { title: "sol is up", selftext: "" }, { title: "pons lowercase", selftext: "" }];
  assert.deepEqual(C.redditMentions(coins, posts), { MintA111: 2, MintC333: 1 });
  const s = C.scoreHot([{ mint: "a", liq: 50000, gtRank: 0, vol1h: 1e5, buys1h: 80, sells1h: 20, reddit: 3, socials: 2 },
                        { mint: "b", liq: 50000, vol1h: 1e3, buys1h: 10, sells1h: 90 }, { mint: "c", liq: 500, gtRank: 0 }]);
  assert.deepEqual(s.map(x => x.mint), ["a", "b"]); assert.ok(s[0].score > 80, String(s[0].score));
  console.log("ok: hot coins");
}

// desk rules: 40 % of free cash, max 2 open, stop -8 % before 2x, half at 2x (entry back), trail 10 % off the high
{
  const D = { ...C.COPY_DEFAULTS };
  const a = C.newAccount(D, 0), L = 1e6;
  assert.ok(C.copyBuy(a, { mint: "A", symbol: "A", price: 1, liq: L, now: 1 }, D).ok); assert.equal(a.cash, 12);   // 40 % of 20
  assert.ok(C.copyBuy(a, { mint: "B", symbol: "B", price: 1, liq: L, now: 1 }, D).ok); assert.ok(Math.abs(a.cash - 7.2) < 1e-9);
  assert.equal(C.copyBuy(a, { mint: "C", symbol: "C", price: 1, liq: L, now: 1 }, D).skip, "max. offene Positionen");
  const eA = a.pos.A.entry, eB = a.pos.B.entry;
  assert.deepEqual(C.deskExits(a, { A: { price: eA * 0.95 }, B: { price: eB * 0.91 } }, D).map(x => x.why), ["stop"]);
  let ex = C.deskExits(a, { A: { price: eA * 2 } }, D);
  assert.equal(ex[0].why, "half"); assert.equal(ex[0].frac, 0.5);
  C.copySell(a, { mint: "A", price: eA * 2, liq: L, frac: ex[0].frac, why: "half", now: 2 });
  assert.ok(a.pos.A.half && a.pos.A.book.tokens > 0);
  assert.deepEqual(C.deskExits(a, { A: { price: eA * 0.9 } }, D).map(x => x.why), ["trail"]);   // after half: no hard stop, trail from the 2x high
  assert.deepEqual(C.deskExits(a, { A: { price: eA * 3 } }, D), []);                              // new high 3x
  assert.deepEqual(C.deskExits(a, { A: { price: eA * 2.75 } }, D), []);                           // -8 % off the high: still riding
  assert.deepEqual(C.deskExits(a, { A: { price: eA * 2.69 } }, D).map(x => x.why), ["trail"]);   // -10.3 %
  C.copySell(a, { mint: "A", price: eA * 2.69, liq: L, why: "trail", now: 3 });
  assert.ok(!a.pos.A); assert.equal(a.closed[0].why, "trail"); assert.ok(a.closed[0].pnl > 0);
  assert.equal(a.activity[0].kind, "trail"); assert.equal(a.activity.at(-1).kind, "buy");
  console.log("ok: desk rules");
}

// fresh-coin Scout filter
{
  const S = await import("./scout.js?v=0.9.8");
  const now = Date.now();
  const mk = (id, age, mc, b, s, u, ch) => ({ relationships: { base_token: { data: { id: "solana_" + id } }, dex: { data: { id: "pump-fun" } } }, attributes: { address: "P" + id, name: id + " / SOL",
    pool_created_at: new Date(now - age * 60e3).toISOString(), market_cap_usd: String(mc), reserve_in_usd: "9000", base_token_price_usd: "0.00002",
    transactions: { m5: { buys: b, sells: s, buyers: u } }, price_change_percentage: { m5: String(ch) } } });
  const l = await S.freshCoins(async p => ({ data: p.includes("page=1") ? [mk("A", 10, 20000, 60, 20, 40, 12), mk("B", 90, 20000, 60, 20, 40, 5), mk("C", 5, 30000, 30, 25, 20, 3), mk("D", 3, 15000, 80, 10, 70, 30), mk("E", 3, 900000, 80, 10, 70, 30)] : [] }), now);
  const ok = l.filter(c => !c.why).map(c => c.symbol);
  if (ok.join() !== "D,A") throw new Error("fresh filter " + ok.join());
  console.log("ok: fresh scout");
}

// fresh-coin veto: RugCheck dangers, a creator with another coin in 24 h, a whale that is not the curve
{
  const S = await import("./scout.js?v=0.9.8");
  const now = Date.parse("2026-11-11T13:00:00Z");
  const base = { score_normalised: 12, risks: [{ name: "Low Liquidity", level: "warn" }], creatorTokens: [],
    knownAccounts: { CURVE: { name: "Pump Fun", type: "AMM" }, DEV: { name: "Creator", type: "CREATOR" } },
    topHolders: [{ owner: "CURVE", pct: 72.5 }, { owner: "A", pct: 2.4 }, { owner: "DEV", pct: 1.1 }] };
  const v = j => S.freshVerdict(j, "MINT", now);
  if (v(base).bad || !v(base).why.includes("größter Halter 2.4")) throw new Error("clean coin " + v(base).why);
  if (!v({ ...base, risks: [{ name: "Creator history of rugged tokens", level: "danger" }] }).why.includes("Creator history")) throw new Error("danger");
  const ct = h => ({ mint: "X" + h, marketCap: 1, createdAt: new Date(now - h * 3600e3).toISOString() });
  if (!v({ ...base, creatorTokens: [ct(2), ct(30)] }).why.includes("schon 1 andere")) throw new Error("serial creator");
  if (v({ ...base, creatorTokens: [ct(30), { ...ct(1), mint: "MINT" }] }).bad) throw new Error("old coins and the coin itself do not count");
  if (!v({ ...base, topHolders: [{ owner: "CURVE", pct: 60 }, { owner: "DEV", pct: 23.4 }] }).why.includes("23 %")) throw new Error("whale");
  if (v({}).bad || !v({}).known) throw new Error("empty report");
  let url = "";
  const r = await S.freshCheck(async u => { url = u; return base; }, "MINT1", now);
  if (r.bad || !url.endsWith("/tokens/MINT1/report")) throw new Error("fetch");
  if ((await S.freshCheck(async () => { throw new Error("down"); }, "MINT2", now)).known) throw new Error("unreachable");
  console.log("ok: fresh veto");
}

// one version everywhere: every "?v=" in the app's files is the manifest's version (a browser must never mix old and new files)
{
  const fs = await import("node:fs");
  const dir = new URL(".", import.meta.url);
  const ver = JSON.parse(fs.readFileSync(new URL("manifest.json", dir), "utf8")).version;
  for (const f of ["copy.html", "copy.js", "copy-engine.js", "scout.js", "desk-runner.mjs"]) {
    const vs = [...fs.readFileSync(new URL(f, dir), "utf8").matchAll(/\.(?:js|css)\?v=([\d.]+)/g)].map(m => m[1]);
    if (!vs.length || vs.some(v => v !== ver)) throw new Error(`${f}: ?v= ${vs.join(",")} is not ${ver}`);
  }
  if (!fs.readFileSync(new URL("copy.js", dir), "utf8").includes(`const VERSION = "${ver}";`)) throw new Error("copy.js VERSION is not " + ver);
  console.log("ok: one version");
}

// the Scout's words match its pick; a coin just sold is bought again only when the Prüfer says yes
{
  const S = await import("./scout.js?v=0.9.8");
  const now = 1e12, P = { minScore: 60 }, W = 30 * 60e3;
  const acc = { pos: {}, closed: [{ mint: "A", out: now - 10 * 60e3, px: 1.0 }] };
  const a = { mint: "A", symbol: "A", score: 61, chg1h: 5, buys1h: 9, sells1h: 3, pool: "p", price: 1.02, chg5m: 2, buys5m: 5, sells5m: 2 };
  const b = { mint: "B", symbol: "B", score: 67, chg1h: 5, buys1h: 3, sells1h: 9, pool: "p" };
  if (S.scoutPick([b, a], acc, P, W, now)) throw new Error("re-buy only +2 %");
  if (!S.scoutVerdict(a, acc, P, W, now).startsWith("Prüfer: nein, Preis +2.0%")) throw new Error(S.scoutVerdict(a, acc, P, W, now));
  if (!S.scoutVerdict(b, acc, P, W, now).includes("mehr Verkäufe")) throw new Error("b");
  const a2 = { ...a, price: 1.08 };
  if (S.scoutPick([b, a2], acc, P, W, now) !== a2 || !S.scoutVerdict(a2, acc, P, W, now).startsWith("Prüfer: ja, +8.0%")) throw new Error("re-buy +8 %");
  if (!S.scoutVerdict({ ...a2, chg5m: -1 }, acc, P, W, now).includes("5 min fallen")) throw new Error("5 min falling");
  if (!S.scoutVerdict({ ...a2, buys5m: 1 }, acc, P, W, now).includes("5 min mehr Verkäufe")) throw new Error("5 min sells");
  const twice = { pos: {}, closed: [{ mint: "A", out: now - 60e3, px: 1 }, { mint: "A", out: now - 9 * 60e3, px: 1 }] };
  if (!S.scoutVerdict(a2, twice, P, W, now).includes("schon 2× verkauft")) throw new Error("ping-pong");
  if (!S.scoutVerdict(a2, { pos: {}, closed: [{ mint: "A", out: now - 60e3 }] }, P, W, now).includes("Verkaufspreis unbekannt")) throw new Error("old entry");
  if (S.scoutVerdict(a, acc, P, W, now + 21 * 60e3) !== "size check") throw new Error("after the window");
  if (!S.scoutNone([b, a], acc, P, W, now).startsWith("$B (67)")) throw new Error("none");
  console.log("ok: scout words, Prüfer");
}

// fresh desk: one price source (the pool), no buy on a price jump or outside the filter
{
  const S = await import("./scout.js?v=0.9.8");
  const pick = { price: 1e-5 };
  const ok = { price: 1.1e-5, mc: 30000, liq: 9000 };
  if (S.freshFillCheck(pick, ok) !== "") throw new Error("ok fill");
  if (!S.freshFillCheck(pick, { ...ok, price: 3.09e-5 }).includes("+209%")) throw new Error("gap up");
  if (!S.freshFillCheck(pick, { ...ok, price: 0.24e-5 }).includes("-76%")) throw new Error("gap down");
  if (!S.freshFillCheck(pick, { ...ok, mc: 2000 }).includes("MC")) throw new Error("mc");
  if (!S.freshFillCheck(pick, { ...ok, liq: 0 }).includes("Liquidität")) throw new Error("liq");
  if (!S.freshFillCheck(pick, undefined)) throw new Error("none");
  const pool = (addr, price, liq) => ({ relationships: { base_token: { data: { id: "solana_M" + addr } } }, attributes: { address: addr, name: "X / SOL", base_token_price_usd: String(price), reserve_in_usd: String(liq), market_cap_usd: null, fdv_usd: "30000" } });
  let asked = "";
  const by = await S.poolPrices(async p => { asked = p; return { data: [pool("P1", 2e-5, 8000), pool("P2", 0, 5)] }; }, ["P1", "P2", "P1"]);
  if (asked !== "/pools/multi/P1,P2") throw new Error(asked);
  if (by.P1.price !== 2e-5 || by.P1.liq !== 8000 || by.P1.mc !== 30000 || by.P2) throw new Error(JSON.stringify(by));
  console.log("ok: fresh fill check, pool prices");
}

// the strict fresh picker: watch first, buy only what is still strong
{
  const S = await import("./scout.js?v=0.9.8");
  const now = 1e12, w = { seen: now - 12 * 60e3, price0: 1e-5 };
  const good = { price: 1.3e-5, mc: 40000, liq: 12000, buyers5: 40, buys5: 60, sells5: 20, chg5: 12 };
  const v = (c, ww = w) => S.strictVerdict(ww, c, now);
  if (v(good) !== "") throw new Error("good: " + v(good));
  if (!v(good, { ...w, seen: now - 4 * 60e3 }).startsWith("beobachtet, noch 6 min")) throw new Error("wait");
  if (!v({ ...good, price: 0.8e-5 }).includes("unter dem Preis")) throw new Error("dumped");
  if (!v({ ...good, mc: 9000 }).includes("MC")) throw new Error("mc");
  if (!v({ ...good, liq: 3000 }).includes("im Pool")) throw new Error("liq");
  if (!v({ ...good, buyers5: 10 }).includes("Käufer")) throw new Error("buyers");
  if (!v({ ...good, sells5: 50 }).includes("zu schwach")) throw new Error("sells");
  if (!v({ ...good, chg5: -1 }).includes("fallen")) throw new Error("falling");
  if (!v({ ...good, chg5: 90 }).includes("zu steil")) throw new Error("spike");
  if (!v(undefined)) throw new Error("no price");
  const watch = new Map([["OLD", { mint: "OLD", seen: now - 50 * 60e3, buyers0: 99 }]]);
  S.watchUpdate(watch, [{ mint: "A", pool: "PA", symbol: "A", price: 1, buyers5: 20, why: "" }, { mint: "B", pool: "PB", why: "zu alt" }], now);
  if ([...watch.keys()].join() !== "A" || watch.get("A").price0 !== 1) throw new Error("watch " + [...watch.keys()]);
  S.watchUpdate(watch, Array.from({ length: 40 }, (_, i) => ({ mint: "M" + i, pool: "P" + i, price: 1, buyers5: i, why: "" })), now);
  if (watch.size !== 30 || watch.has("M0") || !watch.has("M39")) throw new Error("cap " + watch.size);
  console.log("ok: strict fresh picker");
}

// paying paper money in and out keeps the profit honest
{
  const C = await import("./copy-engine.js?v=0.9.8");
  const acc = C.newAccount({ deposit: 20 }, 1);
  if (!C.payIn(acc, 50).ok || acc.cash !== 70 || acc.deposit !== 70) throw new Error("pay in");
  if (C.accountProfit(acc, 70) !== 0) throw new Error("profit after pay in");
  if (C.payOut(acc, 100).ok) throw new Error("pay out more than free cash");
  if (!C.payOut(acc, 30).ok || acc.cash !== 40 || acc.out !== 30 || acc.deposit !== 70) throw new Error("pay out");
  if (C.accountProfit(acc, 45) !== 5) throw new Error("profit after pay out");
  if (C.payIn(acc, 0).ok || C.payIn(acc, "x").ok) throw new Error("bad amount");
  if (acc.activity[0].kind !== "withdraw" || acc.activity[1].kind !== "deposit") throw new Error("activity");
  const S = await import("./scout.js?v=0.9.8");
  if (!S.freshOk({ mint: "m", price: 1, dex: "meteora", ageMin: 2, mc: 20000, liq: 9000, buyers5: 50, buys5: 60, sells5: 10, chg5: 5 }).includes("nicht pump.fun")) throw new Error("dex");
  console.log("ok: pay in / out, pump.fun pools only");
}
