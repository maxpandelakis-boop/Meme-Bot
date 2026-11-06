// node trencher/test_sim.mjs : checks the paper engine's money math.
import assert from "node:assert/strict";
import * as S from "./sim.js";

assert.equal(S.fee(20), 0.5);                  // the minimum bites at 20
assert.equal(S.fee(1000), 5);
let b = S.newBook();
let r = S.buy(b, 20, 1e-5, 50000, 1);
assert.ok(!r.error); b = r.book;
assert.equal(b.cash, 0); assert.ok(b.tokens > 0);
// selling at the same price loses fees and slippage
let s = S.sell(b, 1, 1e-5, 50000, 2);
assert.ok(s.book.cash < 19 && s.book.cash > 18, "flat round trip " + s.book.cash);
assert.ok(Math.abs(s.book.realized - (s.book.cash - 20)) < 1e-9);
assert.equal(s.book.tokens, 0);
// at the break-even move the round trip ends at about 20
const be = S.breakEvenMove(20, 50000);
assert.ok(be > 0.05 && be < 0.08, "break even " + be);
s = S.sell(b, 1, 1e-5 * (1 + be), 50000, 3);
assert.ok(Math.abs(s.book.cash - 20) < 0.05, "at break even " + s.book.cash);
// half sells keep the cost basis right
let h = S.sell(b, 0.5, 2e-5, 50000, 4).book;
assert.ok(Math.abs(h.cost - 10) < 1e-9);
h = S.sell(h, 1, 2e-5, 50000, 5).book;
assert.equal(h.tokens, 0); assert.equal(h.cost, 0);
assert.ok(Math.abs(h.realized - (h.cash - 20)) < 1e-9);
// thin pools cost more
assert.ok(S.breakEvenMove(20, 3000) > S.breakEvenMove(20, 300000));
// a tiny buy is refused when the fee eats it
assert.ok(S.buy(S.newBook(), 0.5, 1, 1e5).error);
// address finding
const m = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", p = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin" + "";
assert.deepEqual(S.findMints("https://fomo.family/token/" + m), [m]);
assert.equal(S.findMints("x 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R Ab12pump" + " HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V9pump")[0].endsWith("pump"), true);
// trade parsing
const t = S.parsePumpTrade({ txType: "buy", solAmount: 0.5, tokenAmount: 1e6, traderPublicKey: "W", mint: m }, 160, 9);
assert.equal(t.usd, 80); assert.equal(t.price, 0.5 / 1e6 * 160);
assert.equal(S.parsePumpTrade({ txType: "create" }, 160), null);
const g = S.parseGeckoTrade({ attributes: { kind: "sell", price_from_in_usd: "0.001", volume_in_usd: "12.5", block_timestamp: "2026-11-06T08:00:00Z", tx_from_address: "W" } });
assert.equal(g.price, 0.001); assert.equal(g.usd, 12.5);
console.log("ok: break-even move for 20 $ at $50K liquidity =", (be * 100).toFixed(1) + "%");
// candles: bad prints dropped, buckets right, gapless opens
const ticks = [1, 1.1, 1.05, 0.0001, 1.2, 1.15, 1.3].map((p, i) => ({ t: 1_000_000 + i * 2000, p, v: 10 }));
const c5 = S.buildCandles(ticks, 5);
assert.ok(c5.every(c => c.low > 0.5), "spike dropped");
assert.equal(c5.reduce((a, c) => a + c.value, 0), 60);
for (let i = 1; i < c5.length; i++) { assert.equal(c5[i].open, c5[i - 1].close); assert.ok(c5[i].time > c5[i - 1].time); }
assert.ok(Math.abs(S.avgEntry({ tokens: 4, cost: 2 }) - 0.5) < 1e-12);
console.log("ok: candles");
// bot rules
{
  const now = 1_000_000_000;
  const up = [0, 3, 6, 9, 12].map((s, i) => ({ t: now - 14000 + s * 1000, side: "buy", usd: 60, price: 1 + i * 0.01 }));
  let d = S.decide({ now, price: 1.04, liq: 20000, trades: up, book: S.newBook() });
  assert.equal(d.action, "buy", d.why);
  d = S.decide({ now, price: 1.04, liq: 2000, trades: up, book: S.newBook() });
  assert.equal(d.action, "wait");
  const sells = up.map(t => ({ ...t, side: "sell" }));
  assert.equal(S.decide({ now, price: 1.04, liq: 20000, trades: sells, book: S.newBook() }).action, "wait");
  let bk = S.buy(S.newBook(), 20, 1, 20000, now).book;
  assert.equal(bk.entryAt, now);
  assert.equal(S.decide({ now: now + 5000, price: 1.0, liq: 20000, trades: [], book: bk }).action, "wait");
  assert.match(S.decide({ now: now + 5000, price: 1.15, liq: 20000, trades: [], book: bk }).why, /Gewinnziel/);
  assert.match(S.decide({ now: now + 5000, price: 0.9, liq: 20000, trades: [], book: bk }).why, /Stop-Loss/);
  assert.match(S.decide({ now: now + 100000, price: 1.0, liq: 20000, trades: [], book: bk }).why, /Haltezeit/);
  assert.equal(S.decide({ now: now + 5000, price: 1.04, liq: 20000, trades: up, book: S.sell(bk, 1, 1, 20000).book, lastExitAt: now + 1000 }).action, "wait");
  console.log("ok: bot rules");
}
{
  // the feed lags: trades 20 s old still count, unknown liquidity is not a reason to skip
  const now = 2_000_000_000;
  const lagged = [0, 4, 8, 12].map((s, i) => ({ t: now - 35000 + s * 1000, side: "buy", usd: 40, price: 1 + i * 0.01 }));
  const d = S.decide({ now, price: 1.03, liq: 0, trades: lagged, book: S.newBook() });
  assert.equal(d.action, "buy", d.why);
  const w = S.decide({ now, price: 1.0, liq: 0, trades: lagged.map(t => ({ ...t, side: "sell" })), book: S.newBook() });
  assert.match(w.why, /✗ Käufe 0 %/);
  console.log("ok: lagged feed");
}
{
  // a synthetic pump.fun TradeEvent round-trips through the parser
  const u = new Uint8Array(129); const v = new DataView(u.buffer);
  u.set([189, 219, 127, 211, 78, 230, 97, 238]);
  const mintBytes = new Uint8Array(32).map((_, i) => i + 1); u.set(mintBytes, 8);
  v.setBigUint64(40, 500_000_000n, true); v.setBigUint64(48, 1_000_000n * 1_000_000n, true); u[56] = 1;
  v.setBigInt64(89, 1_700_000_000n, true);
  const b64 = Buffer.from(u).toString("base64");
  const e = S.parseEvent(b64);
  assert.equal(e.side, "buy"); assert.equal(e.sol, 0.5); assert.equal(e.tok, 1_000_000); assert.equal(e.mint, S.b58(mintBytes));
  const tr = S.tradesFromLogs(["Program log: x", "Program data: " + b64], e.mint, null, 100, "sig", 5);
  assert.equal(tr.length, 1); assert.equal(tr[0].usd, 50); assert.ok(Math.abs(tr[0].price - 0.5 / 1e6 * 100) < 1e-15);
  assert.equal(S.tradesFromLogs(["Program data: " + b64], "other", null, 100, "s").length, 0);
  assert.equal(S.b58(new Uint8Array(32)), "11111111111111111111111111111111");
  console.log("ok: chain events");
}
