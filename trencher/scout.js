// The desk's Scout data, shared by the page (copy.js) and the 24/7 runner (desk-runner.mjs): hot coins from every free source
// (GeckoTerminal trending, DexScreener boosts + new profiles + pair stats, Reddit mentions when a Reddit app ID is set) -> scored.
// No browser APIs: `getJson(url)`, `gt(path)` and `reddit()` are passed in.
import { bestPair } from "./sim.js";
import { redditMentions, scoreHot } from "./copy-engine.js";

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
  msg("Hole Trends von GeckoTerminal …");
  try {
    const tp = await gt("/trending_pools?page=1");
    (tp.data || []).forEach((d, i) => {
      const mint = String(d.relationships?.base_token?.data?.id || "").replace(/^solana_/, "");
      add(mint, { gtRank: i, pool: d.attributes.address, symbol: String(d.attributes.name || "").split(" / ")[0] }); tag(mint, "GT #" + (i + 1));
    });
  } catch {}
  msg("Hole Boosts und neue Coins von DexScreener …");
  for (const [url, label] of [[DS + "/token-boosts/top/v1", "Boost"], [DS + "/token-profiles/latest/v1", "Neu"]]) {
    try {
      const list = await getJson(url);
      for (const t of (Array.isArray(list) ? list : []).filter(t => t.chainId === "solana").slice(0, 20)) {
        add(t.tokenAddress, label === "Boost" ? { boost: t.totalAmount || t.amount || 0 } : {}); tag(t.tokenAddress, label);
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
