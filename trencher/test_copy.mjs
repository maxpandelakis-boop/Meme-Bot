// node trencher/test_copy.mjs : checks the copy-trading engine.
import assert from "node:assert/strict";
import * as C from "./copy-engine.js";

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
// other owners and WSOL ignored, failed tx ignored
assert.equal(C.walletTrades(tx([tb("x", M, 1)], [tb("x", M, 5)], 0, 0), W).length, 0);
assert.equal(C.walletTrades(tx([], [tb(W, "So11111111111111111111111111111111111111112", 5)], 0, 0), W).length, 0);
assert.equal(C.walletTrades({ meta: { err: {} } }, W).length, 0);

// account: copy a buy, take profit at 10x
const P = { ...C.COPY_DEFAULTS };
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
