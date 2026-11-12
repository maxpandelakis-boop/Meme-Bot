// node trencher/test_live.mjs  — checks the Echtgeld wallet (key, encryption, signing) and the mirror limits. No network.
import assert from "node:assert/strict";
import { b58encode, b58decode, newWallet, encryptWallet, decryptWallet, unlockFromSeed, signTx, txLayout, b64encode, b64decode, backupString } from "./live-wallet.js";
import { planMirror, buyUsd, LIVE_DEFAULTS } from "./live-trade.js";

let n = 0; const ok = (name) => { n++; console.log("ok", name); };

// base58
assert.equal(b58encode(new Uint8Array(32)), "11111111111111111111111111111111");
assert.deepEqual([...b58decode(b58encode(Uint8Array.from([0, 0, 7, 255, 1])))], [0, 0, 7, 255, 1]);
assert.equal(b58encode(b58decode("So11111111111111111111111111111111111111112")), "So11111111111111111111111111111111111111112");
ok("base58");

// wallet + encryption
const w = await newWallet();
assert.equal(w.seed.length, 32); assert.equal(w.pub.length, 32); assert.equal(b58decode(w.address).length, 32);
await assert.rejects(encryptWallet(w, "kurz"));
const box = await encryptWallet(w, "ein langes passwort 123");
assert.ok(!JSON.stringify(box).includes(b64encode(w.seed)), "seed not stored in clear");
await assert.rejects(decryptWallet(box, "falsch falsch falsch"), /falsches Passwort/);
const back = await decryptWallet(box, "ein langes passwort 123");
assert.deepEqual([...back.seed], [...w.seed]);
assert.equal(b58decode(backupString(w.seed, w.pub)).length, 64);
ok("wallet encrypt/decrypt");

// signing a minimal legacy transaction: 1 signature slot, header [1,0,1], keys [wallet, program], blockhash, 0 instructions
const program = new Uint8Array(32).fill(9);
const msg = Uint8Array.from([1, 0, 1, 2, ...w.pub, ...program, ...new Uint8Array(32).fill(5), 0]);
const tx = Uint8Array.from([1, ...new Uint8Array(64), ...msg]);
assert.deepEqual(txLayout(tx).signers, [w.address]);
const uw = await unlockFromSeed(w.seed, w.pub);
const signed = b64decode(await signTx(b64encode(tx), uw));
const pubKey = await crypto.subtle.importKey("raw", w.pub, { name: "Ed25519" }, false, ["verify"]);
assert.ok(await crypto.subtle.verify({ name: "Ed25519" }, pubKey, signed.slice(1, 65), msg));
// v0 message (prefix 0x80) works too
const v0 = Uint8Array.from([1, ...new Uint8Array(64), 0x80, ...msg, 0]);
assert.deepEqual(txLayout(v0).signers, [w.address]);
const other = await newWallet();
await assert.rejects(signTx(b64encode(tx), await unlockFromSeed(other.seed, other.pub)), /nicht für diese Wallet/);
ok("sign tx");

// sizing and mirror limits
const S = LIVE_DEFAULTS, now = Date.UTC(2026, 10, 11, 12);
assert.equal(buyUsd(0.4, 20, 150, S), 8);              // 40 % of 20 = 8, cap 8
assert.equal(buyUsd(0.4, 10, 150, S), 4);
assert.equal(buyUsd(0.4, 3.5, 150, S), 0);            // free = 3.5 - 0.02*150 = 0.5 $ -> under 1 $ -> skip
ok("buyUsd");

const st = { seenT: 0, held: {}, day: "2026-11-11", tradesToday: 0 };
const act = [   // newest first, like copy-engine.js
  { t: now - 1000, kind: "trail", mint: "B", frac: 1 },
  { t: now - 2000, kind: "half", mint: "A", frac: 0.5 },
  { t: now - 3000, kind: "copy", mint: "A", symbol: "AAA", pct: 0.4 },
  { t: now - 4000, kind: "sell", mint: "C", frac: 1 },
  { t: now - 300e3, kind: "buy", mint: "OLD", pct: 0.4 },
];
let p = planMirror(act, st, { usd: 20, solUsd: 150 }, S, now);
assert.deepEqual(p.actions.map(a => a.type + a.mint), ["buyA", "sellA"]);
assert.equal(p.actions[0].usd, 8); assert.equal(p.actions[1].frac, 0.5);
assert.equal(p.seenT, now - 1000);
assert.ok(p.skipped.some(s => s.mint === "OLD"));
p = planMirror(act, { ...st, seenT: now - 1000 }, { usd: 20, solUsd: 150 }, S, now);
assert.equal(p.actions.length, 0);                       // nothing twice
p = planMirror([{ t: now, kind: "buy", mint: "X", pct: 0.4 }], st, { usd: 11, solUsd: 150 }, S, now);
assert.equal(p.actions.length, 0); assert.match(p.skipped[0].why, /unter 12/);
p = planMirror([{ t: now, kind: "buy", mint: "X", pct: 0.4 }], { ...st, tradesToday: 20 }, { usd: 20, solUsd: 150 }, S, now);
assert.match(p.skipped[0].why, /Tageslimit/);
p = planMirror([{ t: now, kind: "buy", mint: "X", pct: 0.4 }], { ...st, day: "2026-11-10", tradesToday: 20 }, { usd: 20, solUsd: 150 }, S, now);
assert.equal(p.actions.length, 1);                       // new day, counter reset
ok("planMirror");
console.log(n, "tests ok");
