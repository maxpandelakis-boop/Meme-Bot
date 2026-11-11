// The Trading Desk around the clock (fake money only): the same engine as the page (copy-engine.js, scout.js, sim.js) run by
// GitHub Actions (.github/workflows/trencher-desk.yml on the default branch). It keeps its state in the one-commit branch
// "desk-data" (desk.json, read by the page's "Server 24/7" view) and its rules in config.json on that branch, which the user may
// edit on GitHub: the runner reads it back every minute before it writes.
//
// usage: node trencher/desk-runner.mjs --data <checkout of desk-data> --minutes 340 [--push]
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { COPY_DEFAULTS, newAccount, accountValue, copyBuy, copySell, deskExits, riskExits, walletTrades, stats } from "./copy-engine.js";
import { hotCoins, priceMap, scoutPick, rugCheck } from "./scout.js";

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i < 0 ? d : (process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : true); };
const DATA = arg("data", "desk-data"), MINUTES = Number(arg("minutes", 340)), PUSH = !!arg("push", false);
const STATE = path.join(DATA, "desk.json"), CONFIG = path.join(DATA, "config.json");
const RPC = "https://solana-rpc.publicnode.com";
const GT = "https://api.geckoterminal.com/api/v2/networks/solana";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const UA = { "User-Agent": "trencher-desk/1.0 (paper trading research)", Accept: "application/json" };

async function getJson(url, opt = {}) {
  const r = await fetch(url, { headers: UA, ...opt });
  if (!r.ok) throw new Error(url.split("/")[2] + " " + r.status);
  return r.json();
}
async function gt(p) {
  for (let i = 0; i < 3; i++) {
    const r = await fetch(GT + p, { headers: UA });
    if (r.status === 429) { await sleep(8000); continue; }
    if (!r.ok) throw new Error("GeckoTerminal " + r.status);
    return r.json();
  }
  throw new Error("GeckoTerminal 429");
}
async function rpc(method, params) {
  const j = await getJson(RPC, { method: "POST", headers: { ...UA, "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  if (j.error) throw new Error(j.error.message || "RPC");
  return j.result;
}

// ---------- state ----------
const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return d; } };
const DEFAULT_CONFIG = { rules: {}, wallets: [], note: "Rules of the 24/7 desk. Edit on GitHub; the desk reads them within a minute. Keys as in trencher/copy-engine.js COPY_DEFAULTS. wallets: [{name, wallet, on}]" };
let config = { ...DEFAULT_CONFIG, ...readJson(CONFIG, {}) };
let P = { ...COPY_DEFAULTS, ...(config.rules || {}) };
const st = readJson(STATE, {});
let acc = st.acc || newAccount(P);
const agent = { checked: 0, top: [], scoutMsg: "", ...(st.agent || {}) };
const log = st.log || [];
const prices = {};
let queue = st.queue || [];
const cursor = st.cursor || {};
const seen = st.seen || {};

const hm = t => new Date(t).toISOString().slice(11, 19);
const money = x => (x < 0 ? "-$" : "$") + Math.abs(x).toFixed(2);
function say(who, text) {
  const line = { t: Date.now(), who, text };
  log.unshift(line); if (log.length > 400) log.length = 400;
  console.log(`${hm(line.t)} ${who.padEnd(7)} ${text}`);
}
function value() { return accountValue(acc, prices); }
function point() {
  const t = Date.now(), c = acc.curve, l = c[c.length - 1];
  if (l && t - l.t < 1000) { l.v = value(); return; }
  c.push({ t, v: value() });
  if (c.length > 8000) acc.curve = c.filter((x, i) => i % 2 === 0 || i > c.length - 1500);
}
const started = Date.now();
function save() {
  const s = stats(acc);
  fs.writeFileSync(STATE, JSON.stringify({ v: 1, updated: Date.now(), runStarted: started, P, acc, agent, log, queue, cursor, seen,
    summary: { value: value(), trades: s.copies, wins: s.wins, losses: s.losses, profit: s.profit, open: Object.keys(acc.pos).length },
    prices: Object.fromEntries(Object.keys(acc.pos).map(m => [m, prices[m]]).filter(([, x]) => x)) }));
}

// ---------- git: read the user's config edits back, write desk.json as the branch's one commit ----------
function git(...a) { return execFileSync("git", ["-C", DATA, ...a], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }); }
function syncConfig() {
  if (!PUSH) return;
  try {
    git("fetch", "-q", "origin", "desk-data");
    const remote = JSON.parse(git("show", "FETCH_HEAD:config.json"));
    if (JSON.stringify(remote) !== JSON.stringify(config)) {
      config = { ...DEFAULT_CONFIG, ...remote };
      const before = JSON.stringify(P);
      P = { ...COPY_DEFAULTS, ...(config.rules || {}) };
      if (JSON.stringify(P) !== before) say("rules", `config.json geändert: ${Object.entries(config.rules || {}).map(([k, v]) => k + "=" + v).join(", ") || "Standard"}`);
    }
  } catch { /* no remote config yet */ }
}
function push() {
  if (!PUSH) return;
  try {
    fs.writeFileSync(CONFIG, JSON.stringify(config, null, 2) + "\n");
    git("add", "-A");
    git("-c", "user.name=trencher-desk", "-c", "user.email=trencher-desk@users.noreply.github.com", "commit", "-q", "--amend", "--allow-empty", "-m", "desk " + new Date().toISOString().slice(0, 16));
    git("push", "-q", "--force", "origin", "HEAD:refs/heads/desk-data");
  } catch (e) { console.log("push failed: " + String(e.message || e).slice(0, 200)); }
}

// ---------- agents ----------
async function scout() {
  if (!P.scout) return;
  const r = await hotCoins({ getJson, gt, reddit: null });
  Object.assign(prices, r.prices);
  agent.checked += r.list.length; agent.top = r.list.slice(0, 3).map(c => ({ mint: c.mint, symbol: c.symbol, score: c.score, chg1h: c.chg1h, img: c.img }));
  for (const c of r.list.slice(0, 4)) {
    const ok = c.score >= P.minScore && (c.chg1h || 0) > 0 && (c.buys1h || 0) > (c.sells1h || 0);
    say("scout", `$${c.symbol} Punkte ${c.score} · ${c.chg1h >= 0 ? "+" : ""}${(c.chg1h || 0).toFixed(0)}% 1h · ${c.buys1h}/${c.sells1h} Käufe → ${acc.pos[c.mint] ? "schon drin" : ok ? "size check" : "wait"}`);
  }
  const pick = scoutPick(r.list, acc, P);
  agent.scoutMsg = pick ? `${pick.symbol} · Punkte ${pick.score}` : `nichts über ${P.minScore} Punkten`;
  if (!pick) return;
  if (Object.keys(acc.pos).length >= P.maxOpen) { say("risk", `max ${P.maxOpen} offen → $${pick.symbol} skip`); return; }
  const rug = await rugCheck(getJson, pick.mint);
  say("risk", `RugCheck $${pick.symbol}: ${rug.bad ? "Gefahr: " + rug.why + " → skip" : rug.why}`);
  if (rug.bad) return;
  const p = prices[pick.mint];
  const free = acc.cash;
  const res = copyBuy(acc, { mint: pick.mint, symbol: pick.symbol, price: p.price, liq: p.liq, mc: p.mc, score: pick.score, pool: pick.pool, img: pick.img }, P);
  if (res.ok) {
    say("size", `${Math.round(P.sizePct * 100)}% von ${money(free)} frei = ${money(acc.activity[0].usd)} → executor`);
    say("exec", `gekauft $${pick.symbol} ${money(acc.activity[0].usd)} bei $${(p.mc / 1000).toFixed(1)}K MC (Spielgeld, Gebühr ${money(res.fill.fee)})`);
  } else say("risk", `$${pick.symbol} → ${res.skip}`);
}

async function risk() {
  const open = Object.keys(acc.pos);
  if (!open.length) return;
  Object.assign(prices, await priceMap(getJson, open));
  const exits = deskExits(acc, prices, P);
  if (P.takeProfitX > 1 || P.stopLoss > 0) for (const x of riskExits(acc, prices, P)) if (!exits.some(e => e.mint === x.mint)) exits.push({ ...x, frac: 1 });
  for (const { mint, why, frac } of exits) {
    const p = prices[mint], pos = acc.pos[mint], x = p.price / pos.entry;
    const r = copySell(acc, { mint, price: p.price, liq: p.liq, mc: p.mc, frac, why });
    if (r.ok) say("exit", `${why === "half" ? "Einsatz zurück bei " + x.toFixed(2) + "×" : why === "stop" ? "Hard Stop −" + Math.round(P.hardStop * 100) + "%" : why === "trail" ? "Trailing " + Math.round(P.trail * 100) + "% vom Hoch, " + x.toFixed(2) + "×" : why} · $${pos.symbol} ${r.fill.pnl >= 0 ? "+" : ""}${money(r.fill.pnl)}`);
  }
}

let wi = 0;
async function wallets() {
  const on = (config.wallets || []).filter(w => w.on !== false && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(w.wallet));
  if (!on.length) return;
  const w = on[wi++ % on.length];
  const sigs = await rpc("getSignaturesForAddress", [w.wallet, { limit: 15 }]);
  if (!sigs || !sigs.length) return;
  if (!cursor[w.wallet]) { cursor[w.wallet] = sigs[0].signature; return; }
  const fresh = [];
  for (const s of sigs) { if (s.signature === cursor[w.wallet]) break; if (!s.err) fresh.push(s); }
  cursor[w.wallet] = sigs[0].signature;
  for (const s of fresh.reverse()) {
    const tx = await rpc("getTransaction", [s.signature, { encoding: "jsonParsed", maxSupportedTransactionVersion: 1, commitment: "confirmed" }]);
    const at = ((tx && tx.blockTime) || s.blockTime || Date.now() / 1000) * 1000;
    for (const t of walletTrades(tx, w.wallet)) {
      queue.push({ due: at + P.delaySec * 1000, at, trader: w.name, mint: t.mint, side: t.side, frac: t.frac });
      seen[w.wallet] = { side: t.side, mint: t.mint, t: at };
      say("wallet", `${w.name} ${t.side === "buy" ? "kauft" : "verkauft"} ${t.mint.slice(0, 6)}… → in ${P.delaySec}s`);
    }
  }
}
async function copyDue() {
  const now = Date.now(), due = queue.filter(q => q.due <= now);
  if (!due.length) return;
  queue = queue.filter(q => q.due > now);
  Object.assign(prices, await priceMap(getJson, due.map(q => q.mint)).catch(() => ({})));
  for (const q of due) {
    const p = prices[q.mint];
    const lagSec = Math.round((Date.now() - q.at) / 1000);
    if (q.side === "buy" && p) {
      const r = copyBuy(acc, { mint: q.mint, symbol: p.symbol, price: p.price, liq: p.liq, mc: p.mc, trader: q.trader, lagSec, pool: p.pool, img: p.img }, P);
      say(r.ok ? "exec" : "risk", r.ok ? `kopiert $${p.symbol} ${money(acc.activity[0].usd)} · ${lagSec}s nach ${q.trader}` : `$${p.symbol} → ${r.skip}`);
    } else if (q.side === "sell" && P.sameExits && acc.pos[q.mint] && p) {
      const r = copySell(acc, { mint: q.mint, price: p.price, liq: p.liq, mc: p.mc, frac: q.frac || 1, why: "trader", trader: q.trader, lagSec });
      if (r.ok) say("exit", `mit ${q.trader} verkauft $${p.symbol} ${money(r.fill.pnl)}`);
    }
  }
}

// ---------- main loop ----------
async function every(ms, last, fn, name) {
  if (Date.now() - last[name] < ms) return;
  last[name] = Date.now();
  try { await fn(); } catch (e) { console.log(`${name}: ${String(e.message || e).slice(0, 160)}`); }
}
(async () => {
  say("report", `Desk startet · ${money(value())} · ${Object.keys(acc.pos).length} offen · Regeln ${Math.round(P.sizePct * 100)}% / max ${P.maxOpen} / −${Math.round(P.hardStop * 100)}% / ${P.halfAt}× / trail ${Math.round(P.trail * 100)}%`);
  const last = { scout: 0, risk: 0, wallets: 0, copy: 0, save: 0, report: Date.now() };
  const end = started + MINUTES * 60e3;
  while (Date.now() < end) {
    await every(5000, last, risk, "risk");
    await every(60000, last, scout, "scout");
    await every(3000, last, wallets, "wallets");
    await every(1000, last, copyDue, "copy");
    await every(3600e3, last, async () => { const s = stats(acc); say("report", `${money(value())} · ${s.copies} Trades · ${s.wins}W ${s.losses}L · Gewinn ${money(s.profit)} · Gebühren ${money(acc.fees)}`); }, "report");
    if (Date.now() - last.save >= 60000) { last.save = Date.now(); syncConfig(); point(); save(); push(); }
    await sleep(1000);
  }
  point(); save(); push();
  console.log("run ends, next run takes over");
})();
