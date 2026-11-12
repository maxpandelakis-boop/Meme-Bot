// node trencher/test_sim.mjs : checks the paper engine's money math.
import assert from "node:assert/strict";
import * as S from "./sim.js?v=0.9.12";

assert.equal(S.fee(20), 0.4);                  // 2 % band
assert.equal(S.fee(3), 0.1);                   // flat under $5
assert.equal(S.fee(100), 0.95);                // flat $47.50 to $190
assert.ok(Math.abs(S.fee(25.22) - 0.5044) < 1e-9);   // FOMO screenshot: $0.50
assert.equal(S.fee(1000), 5);
let b = S.newBook();
let r = S.buy(b, 20, 1e-5, 50000, 1);
assert.ok(!r.error); b = r.book;
assert.equal(b.cash, 0); assert.ok(b.tokens > 0);
// selling at the same price loses fees and slippage
let s = S.sell(b, 1, 1e-5, 50000, 2);
assert.ok(s.book.cash < 19.2 && s.book.cash > 18.5, "flat round trip " + s.book.cash);
assert.ok(Math.abs(s.book.realized - (s.book.cash - 20)) < 1e-9);
assert.equal(s.book.tokens, 0);
// at the break-even move the round trip ends at about 20
const be = S.breakEvenMove(20, 50000);
assert.ok(be > 0.04 && be < 0.07, "break even " + be);
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
assert.ok(S.buy(S.newBook(), 0.1, 1, 1e5).error);
// pair choice: the busy pool, not a dead one with a stale liquidity figure
{
  const pairs = [{ chainId: "solana", baseToken: { address: "M" }, liquidity: { usd: 9 }, volume: { h24: 3 } },
                 { chainId: "solana", baseToken: { address: "M" }, liquidity: {}, volume: { h24: 67000 } }];
  assert.equal(S.bestPair(pairs, "M").volume.h24, 67000);
}
console.log("ok: fees, fills, pair choice");
