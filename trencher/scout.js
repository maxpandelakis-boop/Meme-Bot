// The desk's Scout data, shared by the page (copy.js) and the 24/7 runner (desk-runner.mjs): hot coins from every free source
// (GeckoTerminal trending, DexScreener boosts + new profiles + pair stats, Reddit mentions when a Reddit app ID is set) -> scored.
// No browser APIs: `getJson(url)`, `gt(path)` and `reddit()` are passed in.
import { bestPair } from "./sim.js?v=0.9.3";
import { redditMentions, scoreHot } from "./copy-engine.js?v=0.9.3";

export const DS = "https://api.dexscreener.com";
export const DEX = mints => `${DS}/latest/dex/tokens/${mints.join(",")}`;

// One DexScreener pair -> the fields the desk uses.
export function pairInfo(p) {
  const info = p.info || {}, h1 = (p.txns && p.txns.h1) || {};
  return { symbol: p.baseToken.symbol, pool: p.pairAddress, price: Number(p.priceUsd) || 0, liq: (p.liquidity && p.liquidity.usd) || 0,
           mc: p.marketCap || p.fdv || 0, vol1h: (p.volume && p.volume.h1) || 0, buys1h: h1.buys || 0, sells1h: h1.sells || 0,
           chg1h: (p.priceChange && p.priceChange.h1) || 0, img: info.imageUrl || "", url: p.url, created: p.pairCreatedAt || 0,
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

// The Scout's pick among the scored coins: score, a pool, not held, not just left, rising, more buyers than sellers.
export function scoutPick(list, acc, P, cooldownMs = 30 * 60e3, now = Date.now()) {
  const recent = new Set(acc.closed.filter(c => now - c.out < cooldownMs).map(c => c.mint));
  return list.find(c => c.score >= P.minScore && c.pool && !acc.pos[c.mint] && !recent.has(c.mint)
                        && (c.chg1h || 0) > 0 && (c.buys1h || 0) > (c.sells1h || 0)) || null;
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

// What the Scout says about one coin, in the log's words: the same checks as scoutPick, so the log never says "size check"
// for a coin the Scout will not buy (e.g. one the desk left less than 30 minutes ago).
export function scoutVerdict(c, acc, P, cooldownMs = 30 * 60e3, now = Date.now()) {
  if (acc.pos[c.mint]) return "schon drin";
  const left = acc.closed.find(x => x.mint === c.mint && now - x.out < cooldownMs);
  if (left) return `Pause nach Verkauf, noch ${Math.max(1, Math.ceil((cooldownMs - (now - left.out)) / 60e3))} min`;
  if (c.score < P.minScore) return `wait (unter ${P.minScore} Punkten)`;
  if (!((c.chg1h || 0) > 0)) return "wait (Kurs fällt)";
  if (!((c.buys1h || 0) > (c.sells1h || 0))) return "wait (mehr Verkäufe als Käufe)";
  if (!c.pool) return "wait (kein Pool)";
  return "size check";
}
// The Scout card's line when nothing is bought: the reason of the best coin, not a blanket "nothing above N points".
export function scoutNone(list, acc, P, cooldownMs = 30 * 60e3, now = Date.now()) {
  const best = list.find(c => c.score >= P.minScore && !acc.pos[c.mint]);
  return best ? `$${best.symbol} (${best.score}): ${scoutVerdict(best, acc, P, cooldownMs, now)}` : `nichts über ${P.minScore} Punkten`;
}
