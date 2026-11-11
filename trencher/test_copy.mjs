// node trencher/test_copy.mjs : checks the copy-trading engine.
import assert from "node:assert/strict";
import * as C from "./copy-engine.js?v=0.9.3";

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
  const S = await import("./scout.js?v=0.9.3");
  const now = Date.now();
  const mk = (id, age, mc, b, s, u, ch) => ({ relationships: { base_token: { data: { id: "solana_" + id } } }, attributes: { address: "P" + id, name: id + " / SOL",
    pool_created_at: new Date(now - age * 60e3).toISOString(), market_cap_usd: String(mc), reserve_in_usd: "9000", base_token_price_usd: "0.00002",
    transactions: { m5: { buys: b, sells: s, buyers: u } }, price_change_percentage: { m5: String(ch) } } });
  const l = await S.freshCoins(async p => ({ data: p.includes("page=1") ? [mk("A", 10, 20000, 60, 20, 40, 12), mk("B", 90, 20000, 60, 20, 40, 5), mk("C", 5, 30000, 30, 25, 20, 3), mk("D", 3, 15000, 80, 10, 70, 30), mk("E", 3, 900000, 80, 10, 70, 30)] : [] }), now);
  const ok = l.filter(c => !c.why).map(c => c.symbol);
  if (ok.join() !== "D,A") throw new Error("fresh filter " + ok.join());
  console.log("ok: fresh scout");
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
  console.log("ok: one version");
}

// the Scout's words match its pick: a coin just sold is on a 30 minute pause, not "size check"
{
  const S = await import("./scout.js?v=0.9.3");
  const now = 1e12, P = { minScore: 60 };
  const acc = { pos: {}, closed: [{ mint: "A", out: now - 10 * 60e3 }] };
  const a = { mint: "A", symbol: "A", score: 61, chg1h: 5, buys1h: 9, sells1h: 3, pool: "p" }, b = { mint: "B", symbol: "B", score: 67, chg1h: 5, buys1h: 3, sells1h: 9, pool: "p" };
  if (S.scoutPick([b, a], acc, P, 30 * 60e3, now)) throw new Error("pick during pause");
  if (S.scoutVerdict(a, acc, P, 30 * 60e3, now) !== "Pause nach Verkauf, noch 20 min") throw new Error(S.scoutVerdict(a, acc, P, 30 * 60e3, now));
  if (!S.scoutVerdict(b, acc, P, 30 * 60e3, now).includes("mehr Verkäufe")) throw new Error("b");
  if (S.scoutVerdict(a, acc, P, 30 * 60e3, now + 21 * 60e3) !== "size check") throw new Error("after pause");
  if (!S.scoutNone([b, a], acc, P, 30 * 60e3, now).startsWith("$B (67)")) throw new Error("none");
  console.log("ok: scout words");
}
