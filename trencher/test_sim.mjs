// node trencher/test_sim.mjs : checks the paper engine's money math.
import assert from "node:assert/strict";
import * as S from "./sim.js";

assert.equal(S.fee(20), 0.81);                 // the minimum bites at 20
assert.equal(S.fee(1000), 5);
let b = S.newBook();
let r = S.buy(b, 20, 1e-5, 50000, 1);
assert.ok(!r.error); b = r.book;
assert.equal(b.cash, 0); assert.ok(b.tokens > 0);
// selling at the same price loses fees and slippage
let s = S.sell(b, 1, 1e-5, 50000, 2);
assert.ok(s.book.cash < 20 - 1.62 && s.book.cash > 17.5, "flat round trip " + s.book.cash);
assert.ok(Math.abs(s.book.realized - (s.book.cash - 20)) < 1e-9);
assert.equal(s.book.tokens, 0);
// at the break-even move the round trip ends at about 20
const be = S.breakEvenMove(20, 50000);
assert.ok(be > 0.08 && be < 0.10, "break even " + be);
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
