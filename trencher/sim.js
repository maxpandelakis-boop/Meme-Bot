// Paper-trading engine of the Trencher: pure functions, no browser APIs, so node can test them (test_sim.mjs).
// Fake money only. Nothing here signs, sends or touches a wallet.

export const START_CASH = 20;        // fake USD per coin
export const FEE_PCT = 0.005;        // FOMO-like fee per trade (same as memebot.py FEE_PCT)
export const FEE_MIN = 0.50;         // ... at least this per trade: FOMO showed "$0.50 fee" on a $25.22 buy (screenshot of 2026-11-06)
export const BASE_SLIP = 0.003;      // 0.3% on top of the pool's price impact (other bots, price moving within the block)
export const FILL_DELAY_MS = 1000;   // a click fills on the price about one second later, not the price you clicked on
export const FALLBACK_LIQ = 5000;    // USD liquidity assumed when the data source gives none (bonding-curve coins)

export function fee(amountUsd) {
  return amountUsd > 0 ? Math.max(FEE_PCT * amountUsd, FEE_MIN) : 0;
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
  sol.sort((a, b) => ((b.liquidity && b.liquidity.usd) || 0) - ((a.liquidity && a.liquidity.usd) || 0));
  return sol[0] || null;
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
  flowSec: 15,        // window for buy pressure and momentum
  minBuyShare: 0.65,  // enter only when at least this share of the window's volume was buys ...
  minVolUsd: 150,     // ... on at least this much volume (USD)
  minMove: 0.015,     // ... and the price rose at least +1.5 % in the window ...
  maxMove: 0.15,      // ... but not more than +15 % (no chasing a spike)
  minLiq: 5000,       // pools under this liquidity are skipped
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
  const win = trades.filter(t => now - t.t <= P.flowSec * 1000);
  const vb = win.filter(t => t.side === "buy").reduce((x, t) => x + t.usd, 0);
  const vs = win.filter(t => t.side === "sell").reduce((x, t) => x + t.usd, 0);
  const share = vb + vs > 0 ? vb / (vb + vs) : 0;
  const old = win.filter(t => t.price > 0).sort((a, b) => a.t - b.t)[0];
  const move = old ? price / old.price - 1 : 0;
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
  if ((liq || 0) < P.minLiq) return { action: "wait", why: `Liquidität zu klein (${Math.round(liq || 0)} $)` };
  if (vb + vs < P.minVolUsd) return { action: "wait", why: `zu wenig Volumen (${Math.round(vb + vs)} $ in ${P.flowSec} s)` };
  if (share < P.minBuyShare) return { action: "wait", why: `Käufe nur ${Math.round(share * 100)} %` };
  if (move < P.minMove) return { action: "wait", why: `Kurs ${f(move)} in ${P.flowSec} s, zu wenig Schwung` };
  if (move > P.maxMove) return { action: "wait", why: `Kurs ${f(move)} in ${P.flowSec} s, zu spät` };
  return { action: "buy", why: `Käufe ${Math.round(share * 100)} % (${Math.round(vb)} $), Kurs ${f(move)} in ${P.flowSec} s` };
}
