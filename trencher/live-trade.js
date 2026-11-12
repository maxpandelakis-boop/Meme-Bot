// Echtgeld-Modus of the Trencher: mirrors the paper desk's buys and sells with a small real wallet, inside hard limits.
// Swaps go through Jupiter's free swap API (routes pump.fun, PumpSwap, Raydium, Meteora ...), are signed locally
// (live-wallet.js) and sent through PublicNode's free Solana RPC. No FOMO clicking, no paid key.
// The pure functions (planMirror, buyUsd, guards) are tested in test_live.mjs; the network ones need a real browser.

export const SOL = "So11111111111111111111111111111111111111112";
export const USDC = "EPjFWJd5Wm7SyfgW6bZ8N8SoQ1bq6iKr2ZnxvUuobKw4";
export const RPC = "https://solana-rpc.publicnode.com";
export const JUP = ["https://lite-api.jup.ag/swap/v1", "https://api.jup.ag/swap/v1"];   // second one needs a free key from portal.jup.ag

export const LIVE_DEFAULTS = {
  maxTradeUsd: 8,          // never more than this per buy, whatever the paper desk does
  floorUsd: 12,            // wallet worth less than this: no more buys (sells still run), the switch goes to "nur verkaufen"
  maxTradesDay: 20,        // buys + sells per calendar day
  slippageBps: 500,        // 5 % max price slip per swap (meme coins move fast; lower = more failed swaps)
  maxPrioLamports: 200000, // priority fee cap per swap: 0.0002 SOL (a few cents)
  reserveSol: 0.02,        // always kept for network fees and token-account rent
};

const SELL_KINDS = ["sell", "tp", "sl", "half", "stop", "trail"];
const day = t => new Date(t).toISOString().slice(0, 10);

// Size of a real buy: the paper desk's share of its cash (pct) times the real free money, capped. -> usd (0 = skip)
export function buyUsd(pct, walletUsd, solUsd, S = LIVE_DEFAULTS) {
  const free = walletUsd - S.reserveSol * solUsd;
  const usd = Math.min(S.maxTradeUsd, (pct > 0 ? pct : 0.4) * walletUsd, free);
  return usd >= 1 ? Math.floor(usd * 100) / 100 : 0;
}

// New paper-desk activity (newest first, as copy-engine.js logs it) -> real actions, oldest first.
//   state: {seenT, held: {mint: true}, day, tradesToday}
//   wallet: {usd (SOL + tokens), solUsd}
// Returns {actions: [{type: "buy", mint, symbol, usd} | {type: "sell", mint, symbol, frac, why}], skipped: [{mint, why}], seenT}
export function planMirror(activity, state, wallet, S = LIVE_DEFAULTS, now = Date.now()) {
  const fresh = (activity || []).filter(a => a.t > state.seenT).sort((a, b) => a.t - b.t);
  const out = { actions: [], skipped: [], seenT: fresh.length ? fresh[fresh.length - 1].t : state.seenT };
  let n = state.day === day(now) ? state.tradesToday : 0;
  const held = { ...state.held };
  let usdLeft = wallet.usd;
  for (const a of fresh) {
    if (now - a.t > 120e3) { out.skipped.push({ mint: a.mint, why: "zu alt (Seite war zu)" }); continue; }   // never chase a 2-minute-old signal
    if (n >= S.maxTradesDay) { out.skipped.push({ mint: a.mint, why: "Tageslimit Trades erreicht" }); continue; }
    if (a.kind === "copy" || a.kind === "buy") {
      if (held[a.mint]) { out.skipped.push({ mint: a.mint, why: "schon drin" }); continue; }
      if (usdLeft < S.floorUsd) { out.skipped.push({ mint: a.mint, why: `Wallet unter ${S.floorUsd} $: keine Käufe mehr` }); continue; }
      const usd = buyUsd(a.pct, usdLeft, wallet.solUsd, S);
      if (!usd) { out.skipped.push({ mint: a.mint, why: "zu wenig Geld" }); continue; }
      out.actions.push({ type: "buy", mint: a.mint, symbol: a.symbol, usd });
      held[a.mint] = true; usdLeft -= usd; n++;
    } else if (SELL_KINDS.includes(a.kind)) {
      if (!held[a.mint]) continue;                                // paper sold a coin the real wallet never bought
      const frac = a.frac > 0 && a.frac < 1 ? a.frac : 1;
      out.actions.push({ type: "sell", mint: a.mint, symbol: a.symbol, frac, why: a.kind });
      if (frac >= 1) delete held[a.mint];
      n++;
    }
  }
  return out;
}

// ---------- network ----------
export async function rpc(method, params) {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || JSON.stringify(j.error));
  return j.result;
}

export async function solBalance(addr) { return (await rpc("getBalance", [addr, { commitment: "confirmed" }])).value / 1e9; }

// -> {raw (string), decimals, ui} summed over the wallet's accounts of that mint (Token and Token-2022)
export async function tokenBalance(addr, mint) {
  const r = await rpc("getTokenAccountsByOwner", [addr, { mint }, { encoding: "jsonParsed", commitment: "confirmed" }]);
  let raw = 0n, decimals = 0, ui = 0;
  for (const a of r.value) { const t = a.account.data.parsed.info.tokenAmount; raw += BigInt(t.amount); decimals = t.decimals; ui += t.uiAmount || 0; }
  return { raw: raw.toString(), decimals, ui };
}

async function jup(path, opts = {}, apiKey = "") {
  let last;
  for (const base of JUP) {
    if (base.includes("api.jup.ag") && !base.includes("lite") && !apiKey) continue;
    try {
      const r = await fetch(base + path, { ...opts, headers: { "Content-Type": "application/json", ...(apiKey ? { "x-api-key": apiKey } : {}), ...(opts.headers || {}) } });
      const j = await r.json().catch(() => ({}));
      if (r.ok && !j.error) return j;
      last = new Error(j.error || j.message || `Jupiter ${r.status}`);
    } catch (e) { last = e; }
  }
  throw last || new Error("Jupiter nicht erreichbar");
}

export const quote = (inMint, outMint, amountRaw, slippageBps, apiKey) =>
  jup(`/quote?inputMint=${inMint}&outputMint=${outMint}&amount=${amountRaw}&slippageBps=${slippageBps}&restrictIntermediateTokens=true`, {}, apiKey);

export async function swapTx(q, address, S, apiKey) {
  const j = await jup("/swap", { method: "POST", body: JSON.stringify({
    quoteResponse: q, userPublicKey: address, wrapAndUnwrapSol: true, dynamicComputeUnitLimit: true, dynamicSlippage: false,
    prioritizationFeeLamports: { priorityLevelWithMaxLamports: { maxLamports: S.maxPrioLamports, priorityLevel: "high" } },
  }) }, apiKey);
  if (!j.swapTransaction) throw new Error("Jupiter gab keine Transaktion");
  return j.swapTransaction;
}

export async function solUsd(apiKey) { const q = await quote(SOL, USDC, 1e9, 50, apiKey); return Number(q.outAmount) / 1e6; }

// Probelauf: the network runs the transaction without sending it. -> {ok, err, logs}
export async function simulate(b64) {
  const r = await rpc("simulateTransaction", [b64, { encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }]);
  return { ok: !r.value.err, err: r.value.err, logs: (r.value.logs || []).slice(-6) };
}

export async function send(signedB64) {
  return rpc("sendTransaction", [signedB64, { encoding: "base64", skipPreflight: false, preflightCommitment: "confirmed", maxRetries: 3 }]);
}

export async function confirm(sig, ms = 60000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const s = (await rpc("getSignatureStatuses", [[sig]])).value[0];
    if (s && s.err) throw new Error("Transaktion fehlgeschlagen: " + JSON.stringify(s.err));
    if (s && (s.confirmationStatus === "confirmed" || s.confirmationStatus === "finalized")) return true;
    await new Promise(r => setTimeout(r, 1500));
  }
  throw new Error("nicht bestätigt nach 60 s (Solscan prüfen)");
}
