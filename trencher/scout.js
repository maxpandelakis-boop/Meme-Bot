// The desk's Scout data, shared by the page (copy.js) and the 24/7 runner (desk-runner.mjs): hot coins from every free source
// (GeckoTerminal trending, DexScreener boosts + new profiles + pair stats, Reddit mentions when a Reddit app ID is set) -> scored.
// No browser APIs: `getJson(url)`, `gt(path)` and `reddit()` are passed in.
import { bestPair } from "./sim.js?v=0.9.6";
import { redditMentions, scoreHot } from "./copy-engine.js?v=0.9.6";

export const DS = "https://api.dexscreener.com";
export const DEX = mints => `${DS}/latest/dex/tokens/${mints.join(",")}`;

// One DexScreener pair -> the fields the desk uses.
export function pairInfo(p) {
  const info = p.info || {}, h1 = (p.txns && p.txns.h1) || {};
  return { symbol: p.baseToken.symbol, pool: p.pairAddress, price: Number(p.priceUsd) || 0, liq: (p.liquidity && p.liquidity.usd) || 0,
           mc: p.marketCap || p.fdv || 0, vol1h: (p.volume && p.volume.h1) || 0, buys1h: h1.buys || 0, sells1h: h1.sells || 0,
           chg1h: (p.priceChange && p.priceChange.h1) || 0,
           chg5m: (p.priceChange && p.priceChange.m5) || 0, buys5m: ((p.txns && p.txns.m5) || {}).buys || 0, sells5m: ((p.txns && p.txns.m5) || {}).sells || 0, img: info.imageUrl || "", url: p.url, created: p.pairCreatedAt || 0,
           socials: (info.socials || []).length + (info.websites || []).length, links: (info.socials || []).map(x => x.type) };
}

// DexScreener prices for many coins (30 per call) -> {mint: pairInfo}.
export async function priceMap(getJson, mints) {
  const out = {};
  mints = [...new Set(mints)].filter(Boolean);
  for (let i = 0; i < mints.length; i += 30) {
    const part = mints.slice(i, i + 30);
    const j = await getJson(DEX(part));
    for (const m of part) { const p = bestPair(j.pairs, m); if (p && Number(p.priceUsd) > 0) out[m] = pairInfo(p); }
  }
  return out;
}

export async function hotCoins({ getJson, gt, reddit, msg = () => {} }) {
  const coins = new Map(), add = (mint, x) => { if (!mint) return; const c = coins.get(mint) || coins.set(mint, { mint, src: [] }).get(mint); Object.assign(c, x); };
  const tag = (mint, s) => { const c = coins.get(mint); if (c && !c.src.includes(s)) c.src.push(s); };
  msg("Hole Trends und frische Coins von GeckoTerminal …");
  // trending pages 1 to 3 (only the top 20 get trend points, so the score of those stays as before) + the newest pools
  const fromPool = d => String(d.relationships?.base_token?.data?.id || "").replace(/^solana_/, "");
  for (const page of [1, 2, 3]) {
    try {
      const tp = await gt(`/trending_pools?page=${page}`);
      (tp.data || []).forEach((d, i) => {
        const rank = (page - 1) * 20 + i, mint = fromPool(d);
        if (coins.has(mint)) return;
        add(mint, { gtRank: rank, pool: d.attributes.address, symbol: String(d.attributes.name || "").split(" / ")[0] }); tag(mint, "GT #" + (rank + 1));
      });
    } catch {}
  }
  for (const page of [1, 2]) {
    try {
      const np = await gt(`/new_pools?page=${page}`);
      for (const d of np.data || []) { const mint = fromPool(d); if (!coins.has(mint)) add(mint, { pool: d.attributes.address }); tag(mint, "Frisch"); }
    } catch {}
  }
  msg("Hole Boosts und neue Coins von DexScreener …");
  for (const [url, label] of [[DS + "/token-boosts/top/v1", "Boost"], [DS + "/token-boosts/latest/v1", "Boost"], [DS + "/token-profiles/latest/v1", "Neu"]]) {
    try {
      const list = await getJson(url);
      for (const t of (Array.isArray(list) ? list : []).filter(t => t.chainId === "solana").slice(0, 30)) {
        add(t.tokenAddress, label === "Boost" ? { boost: Math.max(coins.get(t.tokenAddress)?.boost || 0, t.totalAmount || t.amount || 0) } : {}); tag(t.tokenAddress, label);
      }
    } catch {}
  }
  msg(`Hole Preise und Käufe von ${coins.size} Coins (DexScreener) …`);
  let prices = {};
  try { prices = await priceMap(getJson, [...coins.keys()]); } catch {}
  for (const [m, x] of Object.entries(prices)) add(m, x);
  msg("Lese Reddit …");
  let redditOk = false;
  if (reddit) {
    try {
      const posts = (await reddit()).filter(p => Date.now() / 1000 - p.created_utc < 86400);
      for (const [m, k] of Object.entries(redditMentions([...coins.values()], posts))) { add(m, { reddit: k }); tag(m, "Reddit " + k); }
      redditOk = true;
    } catch (e) { msg(`Reddit übersprungen (${e.message || e})`); }
  }
  return { list: scoreHot([...coins.values()]), prices, redditOk };
}

// ---------- the Scout's verdict on one coin, and the "Prüfer" (re-buy checker) ----------
// A coin the desk sold less than `windowMs` ago is not locked any more (Maxim, 2026-11-11): it may be bought again at once,
// but only when the Prüfer says it is worth it. Its rules, written down before any result and not tuned:
//   1. the coin passes the Scout's normal check again on fresh data (points, rising 1 h, more buys than sells, a pool);
//   2. the last 5 minutes are up as well: price rising and more buys than sells;
//   3. the price is at least REBUY_ABOVE over the price the desk sold at: a round trip costs about 4 % in fees plus slippage,
//      so a re-buy below that is paying twice for the same move;
//   4. at most REBUY_MAX sales of this coin inside the window (no ping-pong in a coin that keeps stopping the desk out).
export const REBUY_ABOVE = 0.05, REBUY_MAX = 2;
function judge(c, acc, P, windowMs, now) {
  if (acc.pos[c.mint]) return { ok: false, text: "schon drin" };
  if (c.score < P.minScore) return { ok: false, text: `wait (unter ${P.minScore} Punkten)` };
  if (!((c.chg1h || 0) > 0)) return { ok: false, text: "wait (Kurs fällt)" };
  if (!((c.buys1h || 0) > (c.sells1h || 0))) return { ok: false, text: "wait (mehr Verkäufe als Käufe)" };
  if (!c.pool) return { ok: false, text: "wait (kein Pool)" };
  const left = acc.closed.filter(x => x.mint === c.mint && now - x.out < windowMs);
  if (!left.length) return { ok: true, text: "size check" };
  const no = why => ({ ok: false, text: `Prüfer: nein, ${why}` });
  const last = left[0];
  if (left.length >= REBUY_MAX) return no(`schon ${left.length}× verkauft in ${Math.round(windowMs / 60e3)} min`);
  if (!(last.px > 0) || !(c.price > 0)) return no("Verkaufspreis unbekannt, Pause 30 min");
  if (!((c.chg5m || 0) > 0)) return no("letzte 5 min fallen");
  if (!((c.buys5m || 0) > (c.sells5m || 0))) return no("letzte 5 min mehr Verkäufe als Käufe");
  const up = c.price / last.px - 1;
  if (up < REBUY_ABOVE) return no(`Preis ${up >= 0 ? "+" : ""}${(up * 100).toFixed(1)}% seit Verkauf, braucht +${REBUY_ABOVE * 100}% (Gebühren)`);
  return { ok: true, text: `Prüfer: ja, +${(up * 100).toFixed(1)}% seit Verkauf und 5 min steigend → size check` };
}
// The Scout's pick among the scored coins: the first one the verdict lets through.
export function scoutPick(list, acc, P, windowMs = 30 * 60e3, now = Date.now()) {
  return list.find(c => judge(c, acc, P, windowMs, now).ok) || null;
}
// The same verdict in the log's words, so the log never says "size check" for a coin the Scout will not buy.
export function scoutVerdict(c, acc, P, windowMs = 30 * 60e3, now = Date.now()) {
  return judge(c, acc, P, windowMs, now).text;
}

// Rug check before a buy (free, no key): RugCheck's report summary. Any risk of level "danger" (mint or freeze authority
// still on, LP not locked, top holders own most of it, ...) blocks the buy. When RugCheck cannot be reached the buy goes on,
// and the log says so. Results are kept 30 minutes per coin.
const rugCache = new Map();
export async function rugCheck(getJson, mint, now = Date.now()) {
  const hit = rugCache.get(mint);
  if (hit && now - hit.t < 30 * 60e3) return hit.r;
  let r;
  try {
    const j = await getJson(`https://api.rugcheck.xyz/v1/tokens/${mint}/report/summary`);
    const danger = (j.risks || []).filter(x => String(x.level).toLowerCase() === "danger").map(x => x.name);
    r = { known: true, bad: danger.length > 0, why: danger.length ? danger.slice(0, 3).join(", ") : `ok (Score ${j.score_normalised ?? j.score ?? "?"})` };
  } catch (e) { r = { known: false, bad: false, why: "RugCheck nicht erreichbar" }; }
  rugCache.set(mint, { t: now, r });
  return r;
}

// ---------- Fresh-coin Scout (the "trencher" way, like the video's ~14k to 28k $ coins): GeckoTerminal's newest pools ----------
// Rules written down before any live result (2026-11-11), not tuned: pool at most 60 min old, market cap 8k to 250k $,
// at least 3k $ liquidity, last 5 minutes: at least 15 different buyers, buys at least 1.5 times the sells, price rising.
// Then RugCheck (danger risks block). The pick is the coin with the most buyers in the last 5 minutes.
export const FRESH = { maxAgeMin: 60, mcMin: 8000, mcMax: 250000, liqMin: 3000, buyersMin: 15, buySellMin: 1.5 };
export function freshInfo(d, now = Date.now()) {
  const a = d.attributes || {}, t5 = (a.transactions && a.transactions.m5) || {}, ch = a.price_change_percentage || {};
  return { mint: String(d.relationships?.base_token?.data?.id || "").replace(/^solana_/, ""), pool: a.address,
           symbol: String(a.name || "").split(" / ")[0], dex: d.relationships?.dex?.data?.id || "",
           ageMin: a.pool_created_at ? (now - Date.parse(a.pool_created_at)) / 60e3 : 1e9,
           mc: Number(a.market_cap_usd) || Number(a.fdv_usd) || 0, liq: Number(a.reserve_in_usd) || 0, price: Number(a.base_token_price_usd) || 0,
           buys5: t5.buys || 0, sells5: t5.sells || 0, buyers5: t5.buyers || 0, chg5: Number(ch.m5) || 0, vol5: Number((a.volume_usd || {}).m5) || 0 };
}
export function freshOk(c, F = FRESH) {
  if (!(c.price > 0) || !c.mint) return "kein Preis";
  if (c.ageMin > F.maxAgeMin) return `zu alt (${Math.round(c.ageMin)} min)`;
  if (c.mc < F.mcMin || c.mc > F.mcMax) return `MC ${Math.round(c.mc / 1000)}k außerhalb ${F.mcMin / 1000}k–${F.mcMax / 1000}k`;
  if (c.liq < F.liqMin) return `Liquidität ${Math.round(c.liq)} $ zu klein`;
  if (c.buyers5 < F.buyersMin) return `nur ${c.buyers5} Käufer in 5 min`;
  if (c.buys5 < F.buySellMin * c.sells5) return `Käufe ${c.buys5} / Verkäufe ${c.sells5} zu schwach`;
  if (!(c.chg5 > 0)) return "Preis fällt";
  return "";
}
export async function freshCoins(gt, now = Date.now()) {
  const out = new Map();
  for (const page of [1, 2, 3]) {
    try { for (const d of (await gt(`/new_pools?page=${page}`)).data || []) { const c = freshInfo(d, now); if (c.mint && !out.has(c.mint)) out.set(c.mint, c); } } catch {}
  }
  const list = [...out.values()].map(c => ({ ...c, why: freshOk(c) }));
  return list.sort((a, b) => (a.why ? 1 : 0) - (b.why ? 1 : 0) || b.buyers5 - a.buyers5);
}

// Fresh-coin veto (free, no key): RugCheck's FULL report gives the danger risks plus two checks that held on hidden days in
// research/filters/FILTERS-2026-11-11.md (51 days of pump.fun trades, 51,324 replayed Scout buys, FOMO fees):
//   - the creator started another coin in the last 24 h: skip (kept coins lost 0.15 less per 20 $, better on 22 of 24 days);
//   - one wallet other than the curve holds 20 % or more: skip (one sale falls far through the -8 % stop; +0.11, 22 of 24 days).
// Together -0.52 instead of -0.80 per 20 $ on the hidden days: a smaller loss, not a profit.
// freshVerdict is pure (tested); freshCheck fetches. When RugCheck cannot be reached the buy goes on and the log says so.
export const FRESH_VETO = { creatorMax24h: 0, whalePct: 20 };
export function freshVerdict(j, mint, now = Date.now(), V = FRESH_VETO) {
  const danger = (j.risks || []).filter(x => String(x.level).toLowerCase() === "danger").map(x => x.name);
  if (danger.length) return { known: true, bad: true, why: danger.slice(0, 3).join(", ") };
  const others = (j.creatorTokens || []).filter(t => t.mint !== mint && now - Date.parse(t.createdAt) < 24 * 3600e3 && now >= Date.parse(t.createdAt)).length;
  if (others > V.creatorMax24h) return { known: true, bad: true, why: `Ersteller hat in 24 h schon ${others}${others >= 50 ? "+" : ""} andere Coins gestartet` };
  const known = j.knownAccounts || {};
  const pool = o => ["AMM", "LOCKER"].includes(String((known[o] || {}).type).toUpperCase());
  const whale = (j.topHolders || []).filter(h => !pool(h.owner)).reduce((m, h) => Math.max(m, Number(h.pct) || 0), 0);
  if (whale >= V.whalePct) return { known: true, bad: true, why: `ein Wallet hält ${whale.toFixed(0)} % (Wal)` };
  return { known: true, bad: false, why: `ok (Score ${j.score_normalised ?? j.score ?? "?"}, größter Halter ${whale.toFixed(1)} %, Ersteller ohne anderen Coin in 24 h)` };
}
const freshSeen = new Map();
export async function freshCheck(getJson, mint, now = Date.now()) {
  const hit = freshSeen.get(mint);
  if (hit && now - hit.t < 60e3) return hit.r;              // holders change fast on a coin minutes old: one minute only
  let r;
  try { r = freshVerdict(await getJson(`https://api.rugcheck.xyz/v1/tokens/${mint}/report`), mint, now); }
  catch (e) { r = { known: false, bad: false, why: "RugCheck nicht erreichbar" }; }
  if (freshSeen.size > 500) freshSeen.clear();
  freshSeen.set(mint, { t: now, r });
  return r;
}

// The Scout card's line when nothing is bought: the reason of the best coin, not a blanket "nothing above N points".
export function scoutNone(list, acc, P, cooldownMs = 30 * 60e3, now = Date.now()) {
  const best = list.find(c => c.score >= P.minScore && !acc.pos[c.mint]);
  return best ? `$${best.symbol} (${best.score}): ${scoutVerdict(best, acc, P, cooldownMs, now)}` : `nichts über ${P.minScore} Punkten`;
}

// The fill of a fresh pick, LATENCY later, on the same pool's fresh numbers. No buy when the price moved more than 25 % in
// those seconds (a spike nobody could have bought into at that price), or the coin left the filter it was picked by.
// Returns "" when the buy may go on, else the reason.
export const FRESH_MAX_GAP = 0.25;
export function freshFillCheck(pick, now, F = FRESH) {
  if (!now || !(now.price > 0) || !(pick.price > 0)) return "kein Preis vom Pool";
  const gap = now.price / pick.price - 1;
  if (Math.abs(gap) > FRESH_MAX_GAP) return `Preis springt (${gap >= 0 ? "+" : ""}${(gap * 100).toFixed(0)}% in Sekunden)`;
  if (!(now.mc >= F.mcMin && now.mc <= F.mcMax)) return `MC ${Math.round((now.mc || 0) / 1000)}k außerhalb ${F.mcMin / 1000}k–${F.mcMax / 1000}k`;
  if (!(now.liq >= F.liqMin)) return `Liquidität ${Math.round(now.liq || 0)} $ zu klein`;
  return "";
}

// The fresh desk lives on ONE price source: the GeckoTerminal pool it picked the coin from. Pick, fill (3 s later) and exits
// all use that pool's price and reserve. (DexScreener often has no liquidity figure and a frozen price for coins minutes old:
// on 2026-11-11 two such positions sat for an hour at their entry price and blocked both slots.)
// pools -> {poolAddress: {price, liq, mc, symbol}}; up to 30 pools in one call.
export async function poolPrices(gt, pools, now = Date.now()) {
  const out = {};
  pools = [...new Set(pools)].filter(Boolean);
  if (!pools.length) return out;
  const j = await gt(`/pools/multi/${pools.slice(0, 30).join(",")}`);
  for (const d of j.data || []) {
    const c = freshInfo(d, now);
    if (c.pool && c.price > 0) out[c.pool] = { price: c.price, liq: c.liq, mc: c.mc, symbol: c.symbol, pool: c.pool };
  }
  return out;
}
// A fresh position whose pool has (almost) no money left cannot be sold: it is closed at what that pool would pay, a near-total loss.
export const DEAD_LIQ = 500;
