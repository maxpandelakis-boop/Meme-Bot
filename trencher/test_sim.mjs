// node trencher/test_sim.mjs : checks the paper engine's money math.
import assert from "node:assert/strict";
import * as S from "./sim.js";

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
{
  // real events captured from Solana's public RPC on 2026-11-06 (pump.fun "november", PumpSwap "GTA"); DexScreener priceNative
  // around then: 2.7e-7 to 3.6e-7 SOL for november, 1.96e-8 SOL for GTA after its crash
  const pf = ["vdt/007mYe6eR5oq3x6xCJljhcgTn9jyhiigJXZos7F8EgkX40eXn18iAAAAAAAASTOfAQAAAAABWkD7lz7NOe3deOHJWr37FYhwCWGYn/GWz/dGuiWzBFsloO1qAAAAAI3G18AXAAAAeTCxfPgeAQCNGrTEEAAAAHmYnjBnIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABfAAAAAAAAAFQAAAAAAAAA5LYLbjMOlalEO9yyXJnQUT0gv+q3Xxhps4Il22x6sQMeAAAAAAAAABsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEgAAAGJ1eV9leGFjdF9xdW90ZV9pbgAAAAAAAAAAAAAAAAAAAAAAiBMAAAAAAAAqAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAF8iAAAAAAAAjcbXwBcAAACNGrTEEAAAAB4AAAAAAAAAGwAAAAAAAAAG2QAmAAAAAAAAAAAAAAAA",
"vdt/007mYe6eR5oq3x6xCJljhcgTn9jyhiigJXZos7F8EgkX40eXn4wLUwwAAAAAZdLyl5QAAAAB/CFUJcDWmzIMzG7fsUBIfVtF7uIsGxSx7GOYCVRwi1UloO1qAAAAABnSKs0XAAAAFF6+5GMeAQAZJgfREAAAABTGq5jSHwAA4ATIfOuY+lzkf4A4Bv0seUXSlSSVmuwA3tl4FPOPeEZfAAAAAAAAABL5HQAAAAAA5LYLbjMOlalEO9yyXJnQUT0gv+q3Xxhps4Il22x6sQMeAAAAAAAAABR3CQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEgAAAGJ1eV9leGFjdF9xdW90ZV9pbgAAAAAAAAAAAAAAAAAAAAAAiBMAAAAAAACJ/A4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIwLUwwAAAAAGdIqzRcAAAAZJgfREAAAAB4AAAAAAAAAFHcJAAAAAAAG2QAmAAAAAAAAAAAAAAAA",
"vdt/007mYe6eR5oq3x6xCJljhcgTn9jyhiigJXZos7F8EgkX40eXnyLI3iQAAAAAM3xaV74BAAAAWtxBfB4z/JsaR0oLIfrYBdlOw3W07OU9cqbTt3ujkQcloO1qAAAAAJvwS6gXAAAARwdKPSIgAQCbRCisEAAAAEdvN/GQIQAAjRgaDISfqTem80re0wge+VcAqssMm7PZCaS5FHUnpOtfAAAAAAAAAB+rWQAAAAAA5LYLbjMOlalEO9yyXJnQUT0gv+q3Xxhps4Il22x6sQMeAAAAAAAAAP1QHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAHNlbGwAAAAAAAAAAAAAAAAAAAAAAIgTAAAAAAAAj9UsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAiyN4kAAAAAJvwS6gXAAAAm0QorBAAAAAeAAAAAAAAAP1QHAAAAAAAGtkAJgAAAAAAAAAAAAAAAA=="];
  const ps = ["Z/RSHyz1d3dUoO1qAAAAAJJ6WdB0AAAAwOHkAAAAAAAAAAAAAAAAAFEeg8oDAAAAfGFh1tplAwB7uzZ0AAAAANg0mAAAAAAAAgAAAAAAAADLBwAAAAAAAF0AAAAAAAAAYGoBAAAAAACjPJgAAAAAAOgbmgAAAAAAS6ijfwAh2G9dloON0QHfLI3INVQOBH6zstgaBmRGBJN9+7K69XkxYtI1Nj5TmyuVpuY7pQgq1E9k2tgp4j93EQqcxmcrNx7yeAb+fASaIf0ncwqFeODt5kcJvgUKLl/d11pv+acUNhqH6pnyGGcchd2c9C2iDjhMYR1OZ4/9SHdgjMwd/OlhtDt3nBkVBabi079F1aTbRhitdsgtYXVFNV0OMm1Matf/fY9TP8MJCFS9H+8ykQhAD19V155Lh4BRqY71vJlq9Xt5BnBUtZzcYL7VTkZbaRpBK8Zrtl9DIGQeAAAAAAAAAOV0AAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAknpZ0HQAAAADAAAAYnV5AAAAAAAAAAAAAAAAAAAAAIgTAAAAAAAAMLUAAAAAAAAX5pj4AwAAAAAAAAAAAAAAAX0fXJjBawMAAAAAAAAAAAAAAAAAAAAAAC4AAQAAAAAAAAAAAAAAAAA=",
"Pi83CqUD3CpdoO1qAAAAAPx0bw9YAAAAAAAAAAAAAAD8dG8PWAAAAAAAAAAAAAAA6uYHBmZlAwAe+M50AAAAAH/BcgAAAAAAAgAAAAAAAADhBQAAAAAAAF0AAAAAAAAANhEBAAAAAACeu3IAAAAAAEZScQAAAAAAS6ijfwAh2G9dloON0QHfLI3INVQOBH6zstgaBmRGBJMP8qUmSD+dm9kKgKwzqe7MpbATd11B05yWaqQhiLiEOf6U96VqfKSDI0p6jUMpM22JQECNaxJeoIBRZfOVTiY+BaV6LZqQ+xBauEBz0Psa1rHEBYaWTS7t+0CNGScJz2MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAqY71vJlq9Xt5BnBUtZzcYL7VTkZbaRpBK8Zrtl9DIGQeAAAAAAAAACJYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIgTAAAAAAAAm4gAAAAAAAAX5pj4AwAAAAAAAAAAAAAAAX0fXJjBawMAAAAAAAAAAAAAAAAAAAAAAFBYAQAAAAAAAAAAAAAAAAA="];
  for (const x of pf) { const e = S.parseEvent(x); assert.equal(e.mint, "Berk1mwwwV7obmWfMaEwkh63T1ntLZ5pPN4f4NX6pump"); assert.ok(e.priceSol > 2.5e-7 && e.priceSol < 3.7e-7); }
  assert.deepEqual(pf.map(x => S.parseEvent(x).side), ["buy", "buy", "sell"]);
  const g = ps.map(S.parseEvent);
  assert.deepEqual(g.map(e => e.side), ["buy", "sell"]);
  for (const e of g) { assert.equal(e.pool, "66LitXo66TC7G8kYg52C5kYqNuLosrUL6QoD4DcxCZVt"); assert.ok(e.priceSol > 1.9e-8 && e.priceSol < 2.1e-8); }
  console.log("ok: real chain events");
}
{
  assert.equal(S.parseFomoNumber("$0.0₄2159"), 0.00002159);
  assert.equal(S.parseFomoNumber("$0.0₅6362"), 0.000006362);
  assert.equal(S.parseFomoNumber("$12.5K"), 12500);
  assert.equal(S.parseFomoNumber("$1.2M"), 1200000);
  assert.equal(S.parseFomoNumber("$0.773"), 0.773);
  assert.equal(S.parseFomoNumber("$65.71"), 65.71);
  const pairs = [{ chainId: "solana", baseToken: { address: "M" }, liquidity: { usd: 9 }, volume: { h24: 3 } },
                 { chainId: "solana", baseToken: { address: "M" }, liquidity: {}, volume: { h24: 67000 } }];
  assert.equal(S.bestPair(pairs, "M").volume.h24, 67000);
  const now = 3_000_000_000;
  const ticks = Array.from({ length: 21 }, (_, i) => ({ t: now - 20000 + i * 1000, p: 1 + i * 0.002 }));
  const d = S.decide({ now, price: 1.04, liq: 12500, trades: [], ticks, priceOnly: true, book: S.newBook() });
  assert.equal(d.action, "buy", d.why);
  assert.match(S.decide({ now, price: 1.0, liq: 12500, trades: [], ticks, priceOnly: true, book: S.newBook() }).why, /✗ Kurs/);
  console.log("ok: FOMO numbers, pair choice, price-only bot");
}
