// Paper-trading engine of the Trencher: pure functions, no browser APIs, so node can test them (test_sim.mjs).
// Fake money only. Nothing here signs, sends or touches a wallet.

export const START_CASH = 20;        // fake USD per coin
// FOMO's fee bands, charged on every buy and every sell (Datawallet's table, matches the screenshots: $0.50 on a $25.22 buy):
// under $5 flat $0.10 · $5 to $47.50 2 % · $47.50 to $190 flat $0.95 · $190 and up 0.5 %
export const FEE_PCT = 0.005;        // the top band (same as memebot.py FEE_PCT)
export const FEE_MIN = 0.10;         // the smallest fee there is
export const BASE_SLIP = 0.003;      // 0.3% on top of the pool's price impact (other bots, price moving within the block)
export const FILL_DELAY_MS = 1000;   // a click fills on the price about one second later, not the price you clicked on
export const FALLBACK_LIQ = 5000;    // USD liquidity assumed when the data source gives none (bonding-curve coins)

export function fee(amountUsd) {
  const x = amountUsd;
  if (!(x > 0)) return 0;
  return x < 5 ? FEE_MIN : x < 47.5 ? 0.02 * x : x < 190 ? 0.95 : FEE_PCT * x;
}

// Price impact of a trade of `usd` against a constant-product pool whose total liquidity is `liqUsd`
// (half of it on the quote side): buying dx against quote reserve R moves the average price by dx/R.
export function impact(usd, liqUsd) {
  const reserve = Math.max((liqUsd > 0 ? liqUsd : FALLBACK_LIQ) / 2, 1);
  return usd / reserve;
}

export function newBook() {
  return { cash: START_CASH, tokens: 0, cost: 0, fees: 0, realized: 0, trades: [] };
}

// Buy for `usd` (capped at the cash) at market price `price` (USD per token). Returns {book, fill} or {error}.
export function buy(book, usd, price, liqUsd, t = Date.now()) {
  usd = Math.min(usd, book.cash);
  if (!(price > 0)) return { error: "Kein Preis" };
  const f = fee(usd);
  const net = usd - f;
  if (net <= 0) return { error: `Zu wenig Geld: die Gebühr (${f.toFixed(2)} $) frisst alles` };
  const slip = impact(net, liqUsd) + BASE_SLIP;
  const fillPrice = price * (1 + slip);
  const qty = net / fillPrice;
  const b = { ...book, trades: book.trades.slice() };
  if (!(b.tokens > 0)) { b.entryAt = t; b.peak = price; }   // a new position: the bot's hold time and trailing stop start here
  b.cash -= usd;
  b.tokens += qty;
  b.cost += usd;                       // what these tokens cost, fee included
  b.fees += f;
  const fill = { t, side: "buy", usd, fee: f, slip, price, fillPrice, qty };
  b.trades.push(fill);
  return { book: b, fill };
}

// Sell `share` (0..1) of the held tokens at market price `price`.
export function sell(book, share, price, liqUsd, t = Date.now()) {
  if (!(book.tokens > 0)) return { error: "Nichts zum Verkaufen" };
  if (!(price > 0)) return { error: "Kein Preis" };
  share = Math.min(Math.max(share, 0), 1);
  const qty = book.tokens * share;
  const gross0 = qty * price;
  const slip = impact(gross0, liqUsd) + BASE_SLIP;
  const fillPrice = price * Math.max(1 - slip, 0);
  const gross = qty * fillPrice;
  const f = Math.min(fee(gross), gross);
  const got = gross - f;
  const costPart = book.cost * share;
  const b = { ...book, trades: book.trades.slice() };
  b.tokens -= qty;
  if (share >= 1 || b.tokens < 1e-12) b.tokens = 0;
  b.cost -= costPart;
  if (b.tokens === 0) b.cost = 0;
  b.cash += got;
  b.fees += f;
  b.realized += got - costPart;
  const fill = { t, side: "sell", usd: got, fee: f, slip, price, fillPrice, qty, pnl: got - costPart };
  b.trades.push(fill);
  return { book: b, fill };
}

// What selling everything now would bring, after impact and fee: the honest value of the position.
export function liquidationValue(book, price, liqUsd) {
  if (!(book.tokens > 0) || !(price > 0)) return 0;
  const gross0 = book.tokens * price;
  const gross = gross0 * Math.max(1 - impact(gross0, liqUsd) - BASE_SLIP, 0);
  return Math.max(gross - fee(gross), 0);
}

export function equity(book, price, liqUsd) {
  return book.cash + liquidationValue(book, price, liqUsd);
}

// The rise a coin needs between buy and sell before a round trip of `usd` breaks even.
export function breakEvenMove(usd, liqUsd) {
  const fb = fee(usd), net = usd - fb;
  if (net <= 0) return Infinity;
  const inSlip = impact(net, liqUsd) + BASE_SLIP;
  // solve: net/(1+inSlip) * m * (1 - outSlip) - fee(out) = usd, outSlip ~ impact(usd) + BASE_SLIP
  const outSlip = impact(usd, liqUsd) + BASE_SLIP;
  const target = usd + fee(usd);
  return (target * (1 + inSlip)) / (net * (1 - outSlip)) - 1;
}

// Solana base58 addresses (32-44 chars) in a string; pump.fun mints end in "pump".
const B58 = /[1-9A-HJ-NP-Za-km-z]{32,44}/g;
export function findMints(text) {
  if (!text) return [];
  const out = [];
  for (const m of String(text).match(B58) || []) {
    if (!out.includes(m) && !/^[0-9]+$/.test(m)) out.push(m);
  }
  out.sort((a, b) => (b.endsWith("pump") ? 1 : 0) - (a.endsWith("pump") ? 1 : 0));
  return out;
}

// Pick the pair to price a coin by: the Solana pair of this token with the most liquidity.
export function bestPair(pairs, mint) {
  const sol = (pairs || []).filter(p => p && p.chainId === "solana" && p.baseToken && p.baseToken.address === mint);
  // most 24 h volume first (a dead pool with a stale liquidity figure must not win), then liquidity
  const vol = p => (p.volume && p.volume.h24) || 0, liq = p => (p.liquidity && p.liquidity.usd) || 0;
  sol.sort((a, b) => vol(b) - vol(a) || liq(b) - liq(a));
  return sol[0] || null;
}

// FOMO's number formats: "$0.0₄2159" (the subscript counts the zeros after the point: 0.00002159), "$12.5K", "$1.2M", "$0.773".
const SUB = "₀₁₂₃₄₅₆₇₈₉";
export function parseFomoNumber(str) {
  if (!str) return 0;
  let t = String(str).replace(/[$,\s]/g, "");
  const m = t.match(/^0\.0([₀-₉]+)(\d+)/);
  if (m) {
    const zeros = Number([...m[1]].map(c => SUB.indexOf(c)).join(""));
    return Number("0." + "0".repeat(zeros) + m[2]);
  }
  const k = t.match(/^(-?[\d.]+)([KMB]?)/i);
  if (!k) return 0;
  return Number(k[1]) * ({ "": 1, K: 1e3, M: 1e6, B: 1e9 }[k[2].toUpperCase()] || 1);
}

// A PumpPortal trade message -> {t, side, usd, sol, price, wallet} (price in USD per token), or null.
export function parsePumpTrade(msg, solUsd, now = Date.now()) {
  if (!msg || (msg.txType !== "buy" && msg.txType !== "sell")) return null;
  const sol = Number(msg.solAmount), tok = Number(msg.tokenAmount);
  if (!(sol > 0) || !(tok > 0)) return null;
  const usdPerSol = solUsd > 0 ? solUsd : 0;
  return {
    t: now, side: msg.txType, sol, usd: sol * usdPerSol,
    price: usdPerSol ? (sol / tok) * usdPerSol : 0,
    wallet: msg.traderPublicKey || "", sig: msg.signature || "",
  };
}

// A GeckoTerminal trade (pools/{pool}/trades) -> the same shape. On a buy the coin is the "to" side, on a sell the "from" side.
export function parseGeckoTrade(item) {
  const a = item && item.attributes;
  if (!a || (a.kind !== "buy" && a.kind !== "sell")) return null;
  const price = Number(a.kind === "buy" ? a.price_to_in_usd : a.price_from_in_usd);
  return {
    t: Date.parse(a.block_timestamp) || 0, side: a.kind, usd: Number(a.volume_in_usd) || 0, sol: 0,
    price: price > 0 ? price : 0, wallet: a.tx_from_address || "", sig: a.tx_hash || "",
  };
}

// Price ticks {t (ms), p, v (USD volume, 0 for a polled price)} -> candles {time (s), open, high, low, close, value} of `sec` seconds.
// A tick under half or over twice the median of the last 9 kept ticks is dropped as a bad print (one wrong trade price would
// otherwise draw a spike to zero across the chart).
export function buildCandles(ticks, sec) {
  const sorted = ticks.filter(k => k.p > 0).sort((a, b) => a.t - b.t);
  const kept = [];
  for (const k of sorted) {
    const w = kept.slice(-9).map(x => x.p).sort((a, b) => a - b);
    const med = w.length >= 3 ? w[w.length >> 1] : 0;
    if (med && (k.p < med / 2 || k.p > med * 2)) continue;
    kept.push(k);
  }
  const out = [];
  for (const k of kept) {
    const time = Math.floor(k.t / 1000 / sec) * sec;
    const c = out[out.length - 1];
    if (c && c.time === time) {
      c.high = Math.max(c.high, k.p); c.low = Math.min(c.low, k.p); c.close = k.p; c.value += k.v || 0;
    } else {
      const open = c ? c.close : k.p;            // gapless: a bar opens where the last one closed
      out.push({ time, open, high: Math.max(open, k.p), low: Math.min(open, k.p), close: k.p, value: k.v || 0 });
    }
  }
  return out;
}

// Average entry price of the open position (what the tokens cost per token, fees included).
export function avgEntry(book) {
  return book.tokens > 0 ? book.cost / book.tokens : 0;
}

// ---------- the auto bot: a simple scalping rule, one decision per second ----------
// Paper money only. Every decision says why, in German, for the bot log.
export const BOT_DEFAULTS = {
  flowSec: 20,        // window for buy pressure and momentum (ending at the newest trade: the feed lags a few seconds)
  minBuyShare: 0.6,   // enter only when at least this share of the window's volume was buys ...
  minVolUsd: 100,     // ... on at least this much volume (USD)
  minMove: 0.005,     // ... and the price rose at least +0.5 % in the window ...
  maxMove: 0.25,      // ... but not more than +25 % (no chasing a spike)
  minLiq: 3000,       // pools under this liquidity are skipped (unknown liquidity, e.g. pump.fun curve coins, is not skipped)
  maxLagSec: 90,      // the newest trade must be at most this old (GeckoTerminal alone can be 75 s behind)
  takeProfit: 0.05,   // sell at +5 % net (after both fees and slippage)
  trail: 0.04,        // or, once in profit, when the price falls 4 % from its high since the buy
  stopLoss: 0.08,     // sell at -8 % net
  maxHoldSec: 90,     // sell after 90 s whatever happens
  flipShare: 0.7,     // sell in profit when 70 % of the last 10 s volume were sells
  cooldownSec: 10,    // wait this long after a sale before buying again
};

// ctx: {now (ms), price, liq, trades: [{t, side, usd, price}], book, lastExitAt}
// -> {action: "buy" | "sell" | "wait", why}
export function decide(ctx, P = BOT_DEFAULTS) {
  const { now, price, liq, trades, book } = ctx;
  if (!(price > 0)) return { action: "wait", why: "kein Preis" };
  // priceOnly: no trade tape for this coin (only the price, e.g. read off the FOMO page): age and momentum come from the ticks,
  // the volume and buy-share checks are skipped
  const priceOnly = !!ctx.priceOnly;
  if (priceOnly) {
    const ticks = (ctx.ticks || []).filter(k => k.p > 0).sort((a, b) => a.t - b.t);
    const lastT = ticks.length ? ticks[ticks.length - 1].t : 0;
    const startP = (ticks.find(k => lastT - k.t <= P.flowSec * 1000) || {}).p;
    ctx = { ...ctx, trades: [], _lag: lastT ? (now - lastT) / 1000 : Infinity, _move: startP ? price / startP - 1 : 0 };
  }
  const newest = trades.reduce((m, t) => Math.max(m, t.t), 0);
  const lag = priceOnly ? ctx._lag : newest ? (now - newest) / 1000 : Infinity;
  const end = Math.min(now, newest || now);
  const win = trades.filter(t => end - t.t <= P.flowSec * 1000);
  const vb = win.filter(t => t.side === "buy").reduce((x, t) => x + t.usd, 0);
  const vs = win.filter(t => t.side === "sell").reduce((x, t) => x + t.usd, 0);
  const share = vb + vs > 0 ? vb / (vb + vs) : 0;
  const old = win.filter(t => t.price > 0).sort((a, b) => a.t - b.t)[0];
  const move = priceOnly ? ctx._move : old ? price / old.price - 1 : 0;
  const f = x => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + " %";

  if (book.tokens > 0) {
    const value = liquidationValue(book, price, liq), net = value / book.cost - 1;
    const held = (now - (book.entryAt || now)) / 1000;
    const fromPeak = book.peak > 0 ? price / book.peak - 1 : 0;
    const last10 = trades.filter(t => now - t.t <= 10000);
    const s10 = last10.filter(t => t.side === "sell").reduce((x, t) => x + t.usd, 0);
    const a10 = last10.reduce((x, t) => x + t.usd, 0);
    if (net >= P.takeProfit) return { action: "sell", why: `Gewinnziel erreicht: ${f(net)} netto` };
    if (net <= -P.stopLoss) return { action: "sell", why: `Stop-Loss: ${f(net)} netto` };
    if (net > 0 && fromPeak <= -P.trail) return { action: "sell", why: `Kurs ${f(fromPeak)} vom Hoch, Gewinn sichern (${f(net)})` };
    if (net > 0 && a10 > 0 && s10 / a10 >= P.flipShare) return { action: "sell", why: `Verkaufsdruck ${Math.round(100 * s10 / a10)} % in 10 s, Gewinn sichern (${f(net)})` };
    if (held >= P.maxHoldSec) return { action: "sell", why: `Haltezeit ${Math.round(held)} s um (${f(net)})` };
    return { action: "wait", why: `halte: ${f(net)} netto, ${Math.round(held)} s` };
  }
  if (!(book.cash > 1)) return { action: "wait", why: "kein Bargeld mehr" };
  if (ctx.lastExitAt && now - ctx.lastExitAt < P.cooldownSec * 1000) return { action: "wait", why: "Pause nach Verkauf" };
  // every entry check at once, so the panel can show which one is missing
  const ok = (c, txt) => (c ? "✓ " : "✗ ") + txt;
  const checks = [
    ok(lag <= P.maxLagSec, `Daten ${isFinite(lag) ? Math.round(lag) + " s" : "keine"}`),
    ok(!(liq > 0) || liq >= P.minLiq, `Liq ${liq > 0 ? Math.round(liq / 1000) + "K" : "?"}`),
    ...(priceOnly ? ["– Vol/Käufe (nur Preis)"] : [
      ok(vb + vs >= P.minVolUsd, `Vol ${Math.round(vb + vs)} $`),
      ok(share >= P.minBuyShare, `Käufe ${Math.round(share * 100)} %`)]),
    ok(move >= P.minMove && move <= P.maxMove, `Kurs ${f(move)}`),
  ];
  if (checks.some(c => c.startsWith("✗"))) return { action: "wait", why: "wartet: " + checks.join(" · ") };
  if (priceOnly) return { action: "buy", why: `Kurs ${f(move)} in ${P.flowSec} s (Preis von FOMO)` };
  return { action: "buy", why: `Käufe ${Math.round(share * 100)} % (${Math.round(vb)} $), Kurs ${f(move)} in ${P.flowSec} s` };
}

// ---------- live trades straight from the chain (Solana RPC logsSubscribe) ----------
// pump.fun (bonding curve) and PumpSwap (graduated) write each trade as an Anchor event into the logs ("Program data: <base64>").
// Discriminator = first 8 bytes of sha256("event:<Name>").
const DISC = {
  trade: [189, 219, 127, 211, 78, 230, 97, 238],   // pump.fun TradeEvent
  buy: [103, 244, 82, 31, 44, 245, 119, 119],      // PumpSwap BuyEvent
  sell: [62, 47, 55, 10, 165, 3, 220, 42],         // PumpSwap SellEvent
};
const B58A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function b58(bytes) {
  let n = 0n;
  for (const b of bytes) n = n * 256n + BigInt(b);
  let s = "";
  while (n > 0n) { s = B58A[Number(n % 58n)] + s; n /= 58n; }
  for (const b of bytes) { if (b === 0) s = "1" + s; else break; }
  return s;
}
function b64bytes(s) {
  const bin = atob(s);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
const isDisc = (u, d) => d.every((x, i) => u[i] === x);
const SOL_DEC = 1e9, TOK_DEC = 1e6;

// One "Program data:" payload -> {side, sol, tok, priceSol, wallet, mint|pool, tChain} or null.
export function parseEvent(b64) {
  let u;
  try { u = b64bytes(b64); } catch { return null; }
  if (u.length < 64) return null;
  const v = new DataView(u.buffer);
  const u64 = o => Number(v.getBigUint64(o, true));
  if (isDisc(u, DISC.trade) && u.length >= 113) {
    const sol = u64(40) / SOL_DEC, tok = u64(48) / TOK_DEC;
    if (!(sol > 0 && tok > 0)) return null;
    return { side: u[56] ? "buy" : "sell", sol, tok, priceSol: sol / tok, mint: b58(u.slice(8, 40)),
             wallet: b58(u.slice(57, 89)), tChain: Number(v.getBigInt64(89, true)) * 1000,
             vsol: u64(97) / SOL_DEC, vtok: u64(105) / TOK_DEC };   // the curve's virtual reserves after the trade
  }
  const buy = isDisc(u, DISC.buy), sell = isDisc(u, DISC.sell);
  if ((buy || sell) && u.length >= 184) {
    const tok = u64(16) / TOK_DEC, sol = u64(64) / SOL_DEC;   // base_amount_out/in, quote_amount_in/out
    if (!(sol > 0 && tok > 0)) return null;
    return { side: buy ? "buy" : "sell", sol, tok, priceSol: sol / tok, pool: b58(u.slice(120, 152)),
             wallet: b58(u.slice(152, 184)), tChain: Number(v.getBigInt64(8, true)) * 1000 };
  }
  return null;
}

// A logsNotification's log lines -> the trades in it that belong to this coin (by mint for pump.fun, by pool for PumpSwap).
export function tradesFromLogs(logs, mint, pool, solUsd, sig, now = Date.now()) {
  const out = [];
  for (const line of logs || []) {
    if (!line.startsWith("Program data: ")) continue;
    const e = parseEvent(line.slice(14).trim());
    if (!e) continue;
    if (e.mint ? e.mint !== mint : !(pool && e.pool === pool)) continue;
    out.push({ t: now, side: e.side, sol: e.sol, usd: e.sol * (solUsd || 0), price: e.priceSol * (solUsd || 0),
               wallet: e.wallet, sig: (sig || "") + ":" + out.length });
  }
  return out;
}
