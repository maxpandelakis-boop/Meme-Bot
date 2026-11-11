// Paper fills of the Trencher desk (fees, slippage, liquidation value): pure functions, no browser APIs, node tests them (test_sim.mjs).
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

// Pick the pair to price a coin by: the Solana pair of this token with the most liquidity.
export function bestPair(pairs, mint) {
  const sol = (pairs || []).filter(p => p && p.chainId === "solana" && p.baseToken && p.baseToken.address === mint);
  // most 24 h volume first (a dead pool with a stale liquidity figure must not win), then liquidity
  const vol = p => (p.volume && p.volume.h24) || 0, liq = p => (p.liquidity && p.liquidity.usd) || 0;
  sol.sort((a, b) => vol(b) - vol(a) || liq(b) - liq(a));
  return sol[0] || null;
}
