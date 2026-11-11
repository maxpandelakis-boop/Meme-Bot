// Copy-trading engine of the Trencher (paper money only): turns a followed wallet's on-chain transactions into its buys and sells,
// and keeps the copy account (cash, positions, activity, equity curve). Pure functions, no browser APIs: node tests them (test_copy.mjs).
import { buy, sell, newBook, liquidationValue } from "./sim.js?v=0.9.5";

export const COPY_DEFAULTS = {
  // the "Trading Desk" of the second video (2026-11-09): $20, 40 % of free cash per buy, max 2 open, no adding to losers,
  // hard stop -8 % only while 2x never printed, at 2x sell enough to get the entry back, the rest trails 10 % off its high
  deposit: 20,        // fake starting balance (USD)
  sizePct: 0.4,       // each buy: this share of the free cash (0 = fixed stake)
  stake: 20,          // fixed stake per buy when sizePct is 0
  maxOpen: 2,         // at most this many open positions
  hardStop: 0.08,     // sell all at -8 % ... while the position never reached halfAt
  halfAt: 2,          // at 2x: sell the share that returns the entry
  trail: 0.10,        // after that: sell the rest 10 % below its highest price
  minScore: 60,       // Scout: buy coins with at least this hot score (0..100; without Reddit and boosts the top is about 85)
  scout: true,        // Scout buys hot coins by itself
  delaySec: 30,       // wallets you follow: copy their buys this long after them
  sameExits: false,   // ... and sell when they sell (otherwise the desk rules decide)
  takeProfitX: 0,     // optional: sell all at this multiple (0 = off; the desk rules trail instead)
  stopLoss: 0,        // optional: plain stop-loss as a fraction (0 = off)
};

const QUOTE_MINTS = new Set([
  "So11111111111111111111111111111111111111112",   // wrapped SOL
  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  // USDC
  "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  // USDT
]);

// A getTransaction (jsonParsed) result -> the trader's buys/sells in it: [{mint, side, tokens, frac, solDelta}].
// A buy is a token balance of the wallet going up, a sell going down; frac is the share of the holding that was sold.
export function walletTrades(tx, wallet) {
  const meta = tx && tx.meta;
  if (!meta || meta.err) return [];
  const pre = new Map(), post = new Map();
  for (const b of meta.preTokenBalances || []) if (b.owner === wallet) pre.set(b.mint, (pre.get(b.mint) || 0) + Number(b.uiTokenAmount.uiAmount || 0));
  for (const b of meta.postTokenBalances || []) if (b.owner === wallet) post.set(b.mint, (post.get(b.mint) || 0) + Number(b.uiTokenAmount.uiAmount || 0));
  const keys = (tx.transaction && tx.transaction.message && tx.transaction.message.accountKeys) || [];
  const idx = keys.findIndex(k => (k.pubkey || k) === wallet);
  const solDelta = idx >= 0 ? ((meta.postBalances[idx] || 0) - (meta.preBalances[idx] || 0)) / 1e9 : 0;
  // what the wallet paid or got in SOL/USDC/USDT: a token arriving with nothing paid is a transfer or airdrop, not a buy (and
  // tokens leaving with nothing received are a transfer, not a sell). SOL and dollars are mixed here; the bar is tiny either way.
  let quoteDelta = solDelta;
  for (const q of QUOTE_MINTS) quoteDelta += (post.get(q) || 0) - (pre.get(q) || 0);
  const out = [];
  for (const mint of new Set([...pre.keys(), ...post.keys()])) {
    if (QUOTE_MINTS.has(mint)) continue;
    const a = pre.get(mint) || 0, b = post.get(mint) || 0, d = b - a;
    if (Math.abs(d) <= 1e-9 * Math.max(a, b, 1)) continue;
    if (d > 0 ? !(quoteDelta < -0.003) : !(quoteDelta > 0.003)) continue;   // 0.003: more than fees and account rent
    out.push(d > 0 ? { mint, side: "buy", tokens: d, frac: 0, solDelta }
                   : { mint, side: "sell", tokens: -d, frac: a > 0 ? Math.min(-d / a, 1) : 1, solDelta });
  }
  return out;
}

export function newAccount(P = COPY_DEFAULTS, now = Date.now()) {
  return { cash: P.deposit, deposit: P.deposit, since: now, pos: {}, closed: [], activity: [], curve: [{ t: now, v: P.deposit }], fees: 0 };
}

// What the account is worth at the given prices ({mint: {price, liq}}), selling every position after slippage and fees.
export function accountValue(acc, prices) {
  let v = acc.cash;
  for (const [mint, p] of Object.entries(acc.pos)) {
    const q = prices[mint] || {};
    v += q.price > 0 ? liquidationValue(p.book, q.price, q.liq) : p.book.cost;   // no price yet: count it at cost
  }
  return v;
}

function log(acc, a) { acc.activity.unshift(a); if (acc.activity.length > 400) acc.activity.length = 400; }

// Copy a buy: stake (capped at cash) into `mint` at `price`. Returns {ok} or {skip: reason}.
export function copyBuy(acc, { mint, symbol, price, liq, mc, trader, lagSec, score, pool, img, now = Date.now() }, P = COPY_DEFAULTS) {
  if (acc.pos[mint]) return { skip: "schon im Coin (kein Nachkaufen)" };
  if (Object.keys(acc.pos).length >= P.maxOpen) return { skip: "max. offene Positionen" };
  const usd = Math.min(P.sizePct > 0 ? acc.cash * P.sizePct : P.stake, acc.cash);
  if (usd < 1) return { skip: "kein Spielgeld mehr" };
  const r = buy({ ...newBook(), cash: usd }, usd, price, liq, now);
  if (r.error) return { skip: r.error };
  r.book.cash = 0;
  acc.cash -= usd; acc.fees += r.fill.fee;
  acc.pos[mint] = { mint, symbol, trader, book: r.book, entry: r.fill.fillPrice, at: now, mcIn: mc || 0, high: price, half: false,
                    score: score || 0, pool: pool || "", img: img || "", usdIn: usd, pctIn: acc.cash + usd > 0 ? usd / (acc.cash + usd) : 0 };
  log(acc, { t: now, kind: trader ? "copy" : "buy", mint, symbol, trader, usd, mc, lagSec, score, price: r.fill.fillPrice, pct: acc.pos[mint].pctIn });
  return { ok: true, fill: r.fill };
}

// Sell `frac` of the copy of `mint` (why: "trader" | "tp" | "sl" | "hand").
export function copySell(acc, { mint, price, liq, mc, frac = 1, why, trader, lagSec, now = Date.now() }) {
  const p = acc.pos[mint];
  if (!p) return { skip: "keine Position" };
  const r = sell(p.book, frac, price, liq, now);
  if (r.error) return { skip: r.error };
  p.book = r.book;
  if (why === "half") p.half = true;
  acc.cash += r.fill.usd; acc.fees += r.fill.fee;
  const multiple = p.entry > 0 ? price / p.entry : 0;
  log(acc, { t: now, kind: ["tp", "sl", "half", "stop", "trail"].includes(why) ? why : "sell", mint, symbol: p.symbol, trader: trader || p.trader,
             usd: r.fill.usd, pnl: r.fill.pnl, multiple, mc, lagSec, frac });
  if (!(p.book.tokens > 0)) {
    acc.closed.unshift({ mint, symbol: p.symbol, trader: p.trader, pnl: p.book.realized, at: p.at, out: now, multiple, why, px: price });
    if (acc.closed.length > 300) acc.closed.length = 300;
    delete acc.pos[mint];
  }
  return { ok: true, fill: r.fill };
}

// The desk rules on the open positions at the current prices -> [{mint, why, frac}]. Keeps each position's high (mutates).
//   not yet 2x:  price <= entry * (1 - hardStop)            -> "stop", sell all
//                price >= entry * halfAt                     -> "half", sell 1/x of it: the entry comes back, the rest rides free
//   after half:  price <= high * (1 - trail)                 -> "trail", sell the rest
export function deskExits(acc, prices, P = COPY_DEFAULTS) {
  const out = [];
  for (const [mint, p] of Object.entries(acc.pos)) {
    const q = prices[mint];
    if (!q || !(q.price > 0) || !(p.entry > 0)) continue;
    p.high = Math.max(p.high || 0, q.price);
    const x = q.price / p.entry;
    if (!p.half) {
      if (P.halfAt > 1 && x >= P.halfAt) out.push({ mint, why: "half", frac: Math.min(1, 1 / x) });
      else if (P.hardStop > 0 && x <= 1 - P.hardStop) out.push({ mint, why: "stop", frac: 1 });
    } else if (P.trail > 0 && q.price <= p.high * (1 - P.trail)) out.push({ mint, why: "trail", frac: 1 });
  }
  return out;
}

// Take-profit / stop-loss checks on the open copies at the current prices -> [{mint, why}].
export function riskExits(acc, prices, P = COPY_DEFAULTS) {
  const out = [];
  for (const [mint, p] of Object.entries(acc.pos)) {
    const q = prices[mint];
    if (!q || !(q.price > 0) || !(p.entry > 0)) continue;
    const x = q.price / p.entry;
    if (P.takeProfitX > 1 && x >= P.takeProfitX) out.push({ mint, why: "tp" });
    else if (P.stopLoss > 0 && x <= 1 - P.stopLoss) out.push({ mint, why: "sl" });
  }
  return out;
}

export function stats(acc) {
  const wins = acc.closed.filter(c => c.pnl > 0).length;
  const best = acc.closed.reduce((m, c) => (c.multiple > (m ? m.multiple : 0) ? c : m), null);
  const copies = acc.activity.filter(a => a.kind === "copy" || a.kind === "buy").length;
  return { copies, closed: acc.closed.length, wins, losses: acc.closed.length - wins, best,
           profit: acc.closed.reduce((x, c) => x + c.pnl, 0) };
}

// "Trader finden": GeckoTerminal trades of several hot pools ([{coin, trades: [attributes...]}]) -> wallets ranked by the profit
// they took in those trades. Per coin, sold tokens are matched against the average buy price inside the window; coins they
// only bought or only sold are not scored. Wallets with very many trades in one pool are bots (MEV, volume bots) and dropped.
export function rankWallets(pools, { maxTradesPerPool = 25, minPnl = 0, top = 12 } = {}) {
  const W = new Map();
  for (const { coin, trades } of pools) {
    const per = new Map();
    for (const a of trades || []) {
      const w = a.tx_from_address; if (!w || (a.kind !== "buy" && a.kind !== "sell")) continue;
      const x = per.get(w) || per.set(w, { n: 0, bt: 0, bu: 0, st: 0, su: 0 }).get(w);
      const usd = Number(a.volume_in_usd) || 0;
      x.n++;
      if (a.kind === "buy") { x.bt += Number(a.to_token_amount) || 0; x.bu += usd; } else { x.st += Number(a.from_token_amount) || 0; x.su += usd; }
    }
    for (const [w, x] of per) {
      const r = W.get(w) || W.set(w, { wallet: w, pnl: 0, wins: 0, losses: 0, coins: [], bot: false, volume: 0 }).get(w);
      if (x.n > maxTradesPerPool) r.bot = true;
      r.volume += x.bu + x.su;
      if (!(x.bt > 0 && x.st > 0)) continue;
      const m = Math.min(x.bt, x.st);
      const pnl = x.su * (m / x.st) - x.bu * (m / x.bt);
      r.pnl += pnl; if (pnl > 0) r.wins++; else r.losses++;
      r.coins.push(coin);
    }
  }
  return [...W.values()].filter(r => !r.bot && r.coins.length && r.pnl > minPnl)
    .sort((a, b) => b.pnl - a.pnl || b.wins - a.wins).slice(0, top);
}

// ---------- hot coins from several free sources ----------
// coins: [{mint, symbol, ...}]; posts: Reddit posts [{title, selftext, created_utc}] -> {mint: count of posts naming the coin
// by its address, its $TICKER, or (for tickers of 4+ letters that are not common words) the bare ticker}.
const COMMON = new Set(["THE", "SOL", "PUMP", "MEME", "COIN", "MOON", "BUY", "SELL", "USDC", "USDT", "JUST", "THIS", "WITH", "LIKE", "WHAT", "HOLD", "BULL", "BEAR", "TOKEN"]);
export function redditMentions(coins, posts) {
  const out = {};
  for (const c of coins) {
    const sym = String(c.symbol || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    const reTicker = sym.length >= 2 ? new RegExp("\\$" + sym + "\\b", "i") : null;
    const reBare = sym.length >= 4 && !COMMON.has(sym) ? new RegExp("\\b" + sym + "\\b") : null;   // case-sensitive: "PONS", not "pons"
    let n = 0;
    for (const p of posts) {
      const t = (p.title || "") + "\n" + (p.selftext || "");
      if ((c.mint && t.includes(c.mint)) || (reTicker && reTicker.test(t)) || (reBare && reBare.test(t))) n++;
    }
    if (n) out[c.mint] = n;
  }
  return out;
}

// One score per coin from what the sources say (each part 0..1, weighted). Higher = hotter. Coins under minLiq are dropped.
export function scoreHot(coins, { minLiq = 10000 } = {}) {
  const max = k => Math.max(1, ...coins.map(c => c[k] || 0));
  const mv = max("vol1h"), mb = max("boost"), mr = max("reddit");
  return coins.filter(c => (c.liq || 0) >= minLiq).map(c => {
    const parts = {
      trend: c.gtRank != null ? Math.max(0, 1 - c.gtRank / 20) : 0,      // GeckoTerminal trending position (top 20 only)
      volume: Math.sqrt((c.vol1h || 0) / mv),                            // DexScreener 1 h volume
      boost: (c.boost || 0) / mb,                                         // DexScreener paid boosts (also a hype signal)
      buyers: c.buys1h + c.sells1h > 0 ? c.buys1h / (c.buys1h + c.sells1h) : 0,
      reddit: (c.reddit || 0) / mr,
      socials: Math.min((c.socials || 0) / 2, 1),                         // has X / Telegram / website
    };
    const score = 30 * parts.trend + 25 * parts.volume + 10 * parts.boost + 15 * parts.buyers + 15 * parts.reddit + 5 * parts.socials;
    return { ...c, score: Math.round(score), parts };
  }).sort((a, b) => b.score - a.score);
}
