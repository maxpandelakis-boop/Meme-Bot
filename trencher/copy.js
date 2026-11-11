// Trading Desk of the Trencher (paper money only), modelled on the user's second video (2026-11-09):
//   Scout       finds hot coins by itself (GeckoTerminal trends, DexScreener boosts/profiles/pair stats, Reddit mentions -> score)
//   Compounder  sizes each buy at 40 % of the free cash, max 2 open, never adds to a coin it holds
//   Risk        hard stop -8 % while 2x never printed; at 2x sells the entry back; the rest trails 10 % off its high
//   Executor    fills on paper with FOMO-like fees and slippage (sim.js)
// Optional: wallets to follow (their buys are copied `delaySec` later). Data, all free and keyless: PublicNode Solana RPC, DexScreener,
// GeckoTerminal, Reddit (the user's own app ID).
import { COPY_DEFAULTS, rankWallets, redditMentions, scoreHot, walletTrades, newAccount, accountValue, copyBuy, copySell, riskExits, deskExits, stats } from "./copy-engine.js";
import { bestPair } from "./sim.js";
import { hotCoins as scoutHot, scoutPick, rugCheck } from "./scout.js";

const $ = id => document.getElementById(id);
// PublicNode answers browser/extension origins (CORS *), ~150 ms, no 429 at 1 call/s (tested 2026-11-08 on the user's PC);
// api.mainnet-beta.solana.com refuses extension origins with 403, so it is not used.
const RPCS = ["https://solana-rpc.publicnode.com"];
const DEX = mints => `https://api.dexscreener.com/latest/dex/tokens/${mints.join(",")}`;
const WATCH_MS = 1500;      // one trader wallet checked per tick, round robin
const COPY_MS = 1000;       // due copies executed
const RISK_MS = 5000;       // open positions priced, take-profit / stop-loss checked
const CURVE_MS = 10000;     // a point of the balance curve
const SCOUT_MS = 60000;     // the Scout looks for hot coins once a minute (GeckoTerminal allows ~30 calls a minute)
const COOLDOWN_MS = 30 * 60e3;   // a coin the desk just left is not bought again for 30 minutes
const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

// ---------- storage (chrome.storage in the extension, localStorage on a plain web page) ----------
const hasChrome = typeof chrome !== "undefined" && chrome.storage && chrome.storage.local;
async function load(k, dflt) {
  try {
    if (hasChrome) { const v = (await chrome.storage.local.get(k))[k]; return v === undefined ? dflt : v; }
    const v = localStorage.getItem(k); return v == null ? dflt : JSON.parse(v);
  } catch { return dflt; }
}
function save(k, v) {
  try { if (hasChrome) chrome.storage.local.set({ [k]: v }); else localStorage.setItem(k, JSON.stringify(v)); } catch {}
}

// ---------- state ----------
let P = { ...COPY_DEFAULTS };
let traders = [];           // [{name, wallet, on}]
let acc = null;
let queue = [];             // trades waiting for their copy time: {due, wallet, trader, mint, side, frac, at}
let running = false;
const cursor = {};          // wallet -> newest signature already handled
const seen = {};            // wallet -> {text, t} last thing the trader did (for the grid card)
const prices = {};          // mint -> {price, liq, mc, symbol, img, t}
const agent = { w: "aus", c: "–", e: "–", r: "–", rpc: 0, rpcErr: 0, checked: 0, top: [], scoutAt: 0, scoutMsg: "" };
let watchIdx = 0, filter = "all", range = "live", saveTimer = 0;

function persist() { if (serverMode) return; clearTimeout(saveTimer); saveTimer = setTimeout(() => { save("deskAcc", acc); save("deskQueue", queue); }, 300); }

// ---------- formatting ----------
const money = x => (x < 0 ? "-$" : "$") + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = x => (x >= 0 ? "+" : "-") + money(Math.abs(x));
const pct = x => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";
const big = x => !(x > 0) ? "–" : x >= 1e9 ? "$" + (x / 1e9).toFixed(2) + "B" : x >= 1e6 ? "$" + (x / 1e6).toFixed(2) + "M" : x >= 1e3 ? "$" + (x / 1e3).toFixed(1) + "K" : "$" + x.toFixed(0);
const hm = t => new Date(t).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const short = w => w ? w.slice(0, 4) + "…" + w.slice(-4) : "";
const xs = m => !(m > 0) ? "–" : (m >= 10 ? m.toFixed(0) : m.toFixed(1)) + "x";
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function hue(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function avatar(name, img) {
  const inner = img ? `<img src="${esc(img)}" alt="" referrerpolicy="no-referrer">` : esc(String(name || "?").replace(/^\$/, "").slice(0, 2).toUpperCase());
  return `<span class="av" style="background:hsl(${hue(name)} 55% 38%)">${inner}</span>`;
}

// ---------- data ----------
async function rpc(method, params) {
  let last;
  for (let i = 0; i < RPCS.length; i++) {
    const url = RPCS[(agent.rpc + i) % RPCS.length];
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      if (j.error) throw new Error(j.error.message || "RPC-Fehler");
      agent.rpc = (agent.rpc + i) % RPCS.length;
      return j.result;
    } catch (e) { last = e; agent.rpcErr++; }
  }
  throw last;
}

// DexScreener for up to 30 coins per call -> fills `prices`.
async function priceCoins(mints) {
  mints = [...new Set(mints)].filter(Boolean);
  for (let i = 0; i < mints.length; i += 30) {
    const part = mints.slice(i, i + 30);
    const j = await (await fetch(DEX(part), { cache: "no-store" })).json();
    for (const m of part) {
      const p = bestPair(j.pairs, m);
      if (!p || !(Number(p.priceUsd) > 0)) continue;
      prices[m] = { price: Number(p.priceUsd), liq: (p.liquidity && p.liquidity.usd) || 0, mc: p.marketCap || p.fdv || 0,
                    symbol: (p.baseToken && p.baseToken.symbol) || short(m), img: (p.info && p.info.imageUrl) || "", pool: p.pairAddress, url: p.url,
                    created: p.pairCreatedAt || 0, t: Date.now() };
    }
  }
}

// ---------- Watcher: new transactions of the followed wallets ----------
async function watchOne() {
  const on = traders.filter(t => t.on && B58.test(t.wallet));
  if (!on.length) { agent.w = "keine Trader"; return; }
  const tr = on[watchIdx++ % on.length];
  const sigs = await rpc("getSignaturesForAddress", [tr.wallet, { limit: 15 }]);
  agent.w = `${on.length} Wallet${on.length > 1 ? "s" : ""} · ${hm(Date.now())}`;
  if (!sigs || !sigs.length) return;
  if (!cursor[tr.wallet]) { cursor[tr.wallet] = sigs[0].signature; return; }   // first look: old trades are not copied
  const fresh = [];
  for (const s of sigs) { if (s.signature === cursor[tr.wallet]) break; if (!s.err) fresh.push(s); }
  cursor[tr.wallet] = sigs[0].signature;
  for (const s of fresh.reverse()) {
    const tx = await rpc("getTransaction", [s.signature, { encoding: "jsonParsed", maxSupportedTransactionVersion: 1, commitment: "confirmed" }]);
    const at = ((tx && tx.blockTime) || s.blockTime || Date.now() / 1000) * 1000;
    for (const t of walletTrades(tx, tr.wallet)) {
      queue.push({ due: at + P.delaySec * 1000, at, wallet: tr.wallet, trader: tr.name, mint: t.mint, side: t.side, frac: t.frac });
      seen[tr.wallet] = { side: t.side, mint: t.mint, t: at };
      flash(tr.wallet);
    }
  }
  queue.sort((a, b) => a.due - b.due);
  persist(); render();
}

// ---------- Copier + Executor: copy the due trades at the current price ----------
async function copyDue() {
  const now = Date.now();
  const due = queue.filter(q => q.due <= now);
  agent.c = queue.length ? `${queue.length} wartend` : "bereit";
  if (!due.length) return;
  queue = queue.filter(q => q.due > now);
  try { await priceCoins(due.map(q => q.mint)); } catch {}
  for (const q of due) {
    const p = prices[q.mint];
    const lagSec = Math.round((Date.now() - q.at) / 1000);
    if (q.side === "buy") {
      if (!p) { rule(q, "kein Preis bei DexScreener"); continue; }
      const r = copyBuy(acc, { mint: q.mint, symbol: p.symbol, price: p.price, liq: p.liq, mc: p.mc, trader: q.trader, lagSec, pool: p.pool, img: p.img, now: Date.now() }, P);
      if (r.skip && !r.skip.startsWith("schon im Coin")) rule(q, r.skip);
      if (r.ok) say("exec", `kopiert $${p.symbol} ${money(acc.activity[0].usd)} · ${lagSec}s nach ${q.trader}`);
      if (r.ok) notify(`Kopiert: ${p.symbol}`, `${money(acc.activity[0].usd)} · ${lagSec}s nach ${q.trader} · ${big(p.mc)} MC`);
    } else if (P.sameExits && acc.pos[q.mint] && p) {
      copySell(acc, { mint: q.mint, price: p.price, liq: p.liq, mc: p.mc, frac: q.frac || 1, why: "trader", trader: q.trader, lagSec, now: Date.now() });
    }
  }
  agent.e = `${stats(acc).copies} Käufe`;
  point(); persist(); render();
}

function rule(q, why) {
  const p = prices[q.mint] || {};
  say("risk", `$${p.symbol || short(q.mint)} von ${q.trader} → ${why}`);
  acc.activity.unshift({ t: Date.now(), kind: "rule", mint: q.mint, symbol: p.symbol || short(q.mint), trader: q.trader, why });
  if (acc.activity.length > 400) acc.activity.length = 400;
}

// ---------- Scout: hot coins from all free sources -> the best one is bought ----------
async function scout() {
  if (!P.scout || Date.now() - agent.scoutAt < SCOUT_MS) return;
  agent.scoutAt = Date.now();
  const list = await hotCoins(() => {});
  hot = list; agent.checked += list.length; agent.top = list.slice(0, 3);
  const pick = scoutPick(list, acc, P, COOLDOWN_MS);
  agent.scoutMsg = pick ? `${pick.symbol} · Punkte ${pick.score}` : `nichts über ${P.minScore} Punkten`;
  for (const c of list.slice(0, 4)) {
    const ok = c.score >= P.minScore && (c.chg1h || 0) > 0 && (c.buys1h || 0) > (c.sells1h || 0);
    say("scout", `$${c.symbol} Punkte ${c.score} · ${c.chg1h >= 0 ? "+" : ""}${(c.chg1h || 0).toFixed(0)}% 1h · ${c.buys1h}/${c.sells1h} Käufe → ${acc.pos[c.mint] ? "schon drin" : ok ? "size check" : "wait"}`);
  }
  if (pick && Object.keys(acc.pos).length >= P.maxOpen) say("risk", `max ${P.maxOpen} offen → $${pick.symbol} skip`);
  if (!pick || Object.keys(acc.pos).length >= P.maxOpen) { render(); return; }
  const rug = await rugCheck(getJson, pick.mint);
  say("risk", `RugCheck $${pick.symbol}: ${rug.bad ? "Gefahr: " + rug.why + " → skip" : rug.why}`);
  if (rug.bad) { render(); return; }
  const p = prices[pick.mint];
  if (!p || !(p.price > 0)) return;
  const r = copyBuy(acc, { mint: pick.mint, symbol: pick.symbol, price: p.price, liq: p.liq, mc: p.mc, score: pick.score, pool: pick.pool, img: pick.img, now: Date.now() }, P);
  if (r.ok) { say("size", `${Math.round(P.sizePct * 100)}% vom freien Geld = ${money(acc.activity[0].usd)} → executor`); say("exec", `gekauft $${pick.symbol} ${money(acc.activity[0].usd)} bei ${big(p.mc)} MC (Spielgeld, Gebühr ${money(r.fill.fee)})`); }
  else say("risk", `$${pick.symbol} → ${r.skip}`);
  if (r.ok) notify(`Gekauft: ${pick.symbol}`, `${money(acc.activity[0].usd)} (${Math.round(P.sizePct * 100)} % vom freien Geld) bei ${big(p.mc)} MC · Punkte ${pick.score}`);
  point(); persist(); render();
}

// ---------- Risk: the desk rules (and the optional plain take-profit / stop-loss) on the open positions ----------
const EXIT_TEXT = { half: "Einsatz zurück bei 2×", stop: "Hard Stop", trail: "Trailing-Stop", tp: "Take Profit", sl: "Stop-Loss" };
async function riskCheck() {
  const open = Object.keys(acc.pos);
  agent.r = `${open.length} offen`;
  if (!open.length) return;
  try { await priceCoins(open); } catch { return; }
  const exits = deskExits(acc, prices, P);
  if (P.takeProfitX > 1 || P.stopLoss > 0) for (const x of riskExits(acc, prices, P)) if (!exits.some(e => e.mint === x.mint)) exits.push({ ...x, frac: 1 });
  for (const { mint, why, frac } of exits) {
    const p = prices[mint], pos = acc.pos[mint];
    const m = p.price / pos.entry;
    const r = copySell(acc, { mint, price: p.price, liq: p.liq, mc: p.mc, frac, why, now: Date.now() });
    if (!r.ok) continue;
    const pnl = r.fill.pnl;
    say("exit", `${EXIT_TEXT[why] || why} · $${pos.symbol} ${xs(m)} · ${signed(pnl)}`);
    const head = why === "half" ? `SOLD HALF ${xs(m)}` : why === "trail" ? `CLOSED ${xs(m)}` : why === "tp" ? `TOOK PROFIT ${xs(m)}` : `STOPPED ${pct(m - 1)}`;
    toast(head, pnl < 0);
    notify(`${EXIT_TEXT[why] || "Verkauft"}: ${pos.symbol}`, `${signed(pnl)} · ${xs(m)} · ${big(p.mc)} MC`);
  }
  point(); persist(); render();
}

// ---------- notifications (buy / sell, also when the page is in the background) ----------
function notify(title, body) {
  try { if (typeof Notification !== "undefined" && Notification.permission === "granted") new Notification("Trading Desk · " + title, { body, icon: "icons/app-192.png", silent: false }); } catch {}
}

// ---------- balance curve ----------
function value() { return acc ? accountValue(acc, prices) : 0; }
function point() {
  const t = Date.now(), v = value(), c = acc.curve, l = c[c.length - 1];
  if (l && t - l.t < 1000) { l.v = v; return; }
  c.push({ t, v });
  if (c.length > 6000) acc.curve = c.filter((x, i) => i % 2 === 0 || i > c.length - 1000);   // thin out old points
}

// ---------- loops ----------
function loop(fn, ms) {
  let busy = false;
  setInterval(async () => {
    if (!running || serverMode || busy || !acc) return;
    busy = true;
    try { await fn(); } catch (e) { if (fn === watchOne) agent.w = "RPC-Fehler: " + String(e.message || e).slice(0, 40); }
    busy = false;
  }, ms);
}
loop(watchOne, WATCH_MS);
loop(copyDue, COPY_MS);
loop(riskCheck, RISK_MS);
loop(scout, 5000);
loop(async () => { point(); persist(); }, CURVE_MS);
setInterval(() => { if (acc) renderTop(); }, 2000);

// ---------- chart ----------
const LWC = window.LightweightCharts;
const chart = LWC.createChart($("chart"), {
  autoSize: true,
  layout: { background: { color: "transparent" }, textColor: "#8a90a0", fontSize: 10 },
  grid: { vertLines: { visible: false }, horzLines: { visible: false } },
  rightPriceScale: { visible: false }, leftPriceScale: { visible: false },
  timeScale: { visible: false, borderVisible: false },
  crosshair: { mode: 0, vertLine: { color: "#2a3040", labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
  handleScroll: false, handleScale: false,
  localization: { locale: "de-DE", priceFormatter: x => money(x), timeFormatter: t => new Date(t * 1000).toLocaleString("de-DE") },
});
const area = chart.addAreaSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerRadius: 4 });
const RANGE_MS = { live: 15 * 60e3, "1h": 3600e3, "4h": 4 * 3600e3, "1d": 86400e3, "1w": 7 * 86400e3, all: Infinity };

function drawChart() {
  const now = Date.now(), from = now - RANGE_MS[range];
  const pts = acc.curve.filter(p => p.t >= from).concat([{ t: now, v: value() }]);
  if (pts.length === 1) pts.unshift({ t: Math.max(acc.since, from), v: acc.curve.filter(p => p.t < from).pop()?.v ?? acc.deposit });
  else if (pts[0].t > from && acc.curve.some(p => p.t < from)) pts.unshift({ t: from, v: acc.curve.filter(p => p.t < from).pop().v });
  // the chart spans the whole range: a flat start line at the first value, then evenly spaced steps (the chart library spreads bars,
  // not times, so a few points far apart would otherwise sit squeezed on the right)
  const t0 = range === "all" ? Math.min(acc.since, pts[0].t) : from;
  if (pts[0].t > t0) pts.unshift({ t: t0, v: pts[0].v });
  const N = 120, step = Math.max(1000, (now - t0) / N), data = [];
  let j = 0;
  for (let t = t0; t <= now + 1; t += step) {
    while (j + 1 < pts.length && pts[j + 1].t <= t) j++;
    data.push({ time: Math.floor(t / 1000), value: pts[j].v });
  }
  for (const p of pts) {   // keep every real point exactly, so markers and the last value are precise
    const time = Math.floor(p.t / 1000), k = data.findIndex(d => d.time >= time);
    if (k < 0) data.push({ time, value: p.v }); else if (data[k].time === time) data[k].value = p.v; else data.splice(k, 0, { time, value: p.v });
  }
  for (let k = data.length - 1; k > 0; k--) if (data[k].time <= data[k - 1].time) data.splice(k - 1, 1);
  const up = data[data.length - 1].value >= data[0].value;
  const col = up ? "#22c55e" : "#ef4444";
  area.applyOptions({ lineColor: col, topColor: up ? "rgba(34,197,94,.28)" : "rgba(239,68,68,.25)", bottomColor: "rgba(0,0,0,0)" });
  area.setData(data);
  const times = new Set(data.map(d => d.time));
  const marks = acc.activity.filter(a => a.t >= from && BUY_KINDS.has(a.kind) || a.t >= from && EXIT_KINDS.has(a.kind))
    .map(a => {
      let time = Math.floor(a.t / 1000);
      if (!times.has(time)) time = data.reduce((b, d) => Math.abs(d.time - time) < Math.abs(b - time) ? d.time : b, data[0].time);
      return BUY_KINDS.has(a.kind) ? { time, position: "belowBar", color: "#4f5dff", shape: "circle", size: 0.6 }
                               : { time, position: "aboveBar", color: a.pnl >= 0 ? "#22c55e" : "#ef4444", shape: "circle", size: 0.6 };
    }).sort((a, b) => a.time - b.time);
  area.setMarkers(marks);
  chart.timeScale().fitContent();
}

// ---------- rendering ----------
const BUY_KINDS = new Set(["buy", "copy"]), EXIT_KINDS = new Set(["sell", "tp", "sl", "half", "stop", "trail"]);
function renderTop() {
  const v = value(), d = v - acc.deposit, x = acc.deposit > 0 ? v / acc.deposit : 1;
  const [w, c] = money(v).split(".");
  $("bal").innerHTML = `${w}<span class="cents">.${c}</span>`;
  $("bal2").textContent = money(v);
  const sinceTxt = `${d >= 0 ? "▲" : "▼"} ${money(Math.abs(d))} (${pct(d / acc.deposit)})`;
  for (const id of ["since", "since2"]) { $(id).textContent = sinceTxt; $(id).className = (id === "since2" ? "since " : "") + (d >= 0 ? "pos" : "neg"); }
  $("mult").textContent = x.toFixed(2) + "×"; $("mult").classList.toggle("neg", x < 1);
  const open = Object.keys(acc.pos).length;
  $("deskSub").textContent = `Spielgeld · Compounder ${Math.round(P.sizePct * 100)}% · ${open} offen · max ${P.maxOpen}`;
  drawChart();
  // agent cards
  $("agentsInfo").textContent = running || serverMode ? `${P.scout ? 4 : 3} laufen` : "aus";
  $("aScoutSub").textContent = !P.scout ? "aus" : agent.checked ? `${agent.checked.toLocaleString("de-DE")} Coins geprüft` : running ? "sucht …" : "wartet";
  $("aScout").innerHTML = agent.top.map(c => `<li>${avatar(c.symbol, c.img)}<b>${esc(c.symbol)}</b> <span class="${c.chg1h >= 0 ? "pos" : "neg"}">${c.chg1h >= 0 ? "+" : ""}${(c.chg1h || 0).toFixed(0)}%</span><span class="sc">${c.score}</span></li>`).join("")
    || `<li class="muted">${running ? "erste Suche läuft …" : "Bot starten"}</li>`;
  if (agent.scoutMsg) $("aScout").insertAdjacentHTML("beforeend", `<li class="muted">→ ${esc(agent.scoutMsg)}</li>`);
  const ring = Math.min(1, Math.max(0, x / 10));
  $("ringFg").style.strokeDashoffset = String(169.6 * (1 - ring));
  $("aCompSub").textContent = x.toFixed(2) + "× jetzt";
  $("aGoal").textContent = money(acc.deposit * 10).replace(".00", "");
  $("aNext").textContent = "Kauf " + money(Math.min(acc.cash, P.sizePct > 0 ? acc.cash * P.sizePct : P.stake));
  const lastExec = acc.activity.filter(a => BUY_KINDS.has(a.kind) || EXIT_KINDS.has(a.kind)).slice(0, 3);
  $("aExec").innerHTML = lastExec.map(a => `<li>${avatar(a.symbol, (prices[a.mint] || {}).img)}<span>${BUY_KINDS.has(a.kind) ? "kauft" : "verkauft"} ${esc(a.symbol)}</span><span class="st ${BUY_KINDS.has(a.kind) ? "" : "ok"}">${BUY_KINDS.has(a.kind) ? money(a.usd) : signed(a.pnl)}</span></li>`).join("")
    || `<li class="muted">noch keine Fills</li>`;
  $("aRiskSub").textContent = `${open} offen · ${Object.values(acc.pos).filter(p => p.half).length} trailing`;
  const anyHalf = Object.values(acc.pos).some(p => p.half), anyNot = Object.values(acc.pos).some(p => !p.half);
  $("aRisk").innerHTML = `<li>Stop −${Math.round(P.hardStop * 100)}%<span class="st ${anyNot ? "on" : ""}">${anyNot ? "scharf" : "–"}</span></li>
    <li>Einsatz zurück bei ${P.halfAt}×<span class="st">${anyNot ? "wartet" : "–"}</span></li>
    <li>Trail ${Math.round(P.trail * 100)}% vom Hoch<span class="st ${anyHalf ? "ok" : ""}">${anyHalf ? "aktiv" : "–"}</span></li>`;
  if ($("coin").classList.contains("on")) renderCoin();
}

function actRow(a) {
  const p = prices[a.mint] || {};
  const icon = avatar(a.symbol || "?", p.img || (acc.pos[a.mint] || {}).img);
  const li = (title, sub, amt, amtSub, cls = "") => `<li data-mint="${esc(a.mint)}">${icon}<div class="mid"><b>${title}</b><span>${sub} · ${hm(a.t)}</span></div>
            <div class="amt"><b class="${cls}">${amt}</b><span>${amtSub}</span></div></li>`;
  const sym = esc(a.symbol);
  if (a.kind === "buy") return li(`Bought ${sym}`, `${Math.round((a.pct || P.sizePct) * 100)}% of free cash · ${big(a.mc)} MC`, money(a.usd), a.score ? `score ${a.score}` : "");
  if (a.kind === "copy") return li(`Copied ${sym}`, `${a.lagSec}s after ${esc(a.trader)} · ${big(a.mc)} MC`, money(a.usd), "Wallet");
  if (a.kind === "rule") return li(`Skipped ${sym}`, `${esc(a.why)}${a.trader ? " · " + esc(a.trader) : ""}`, "", "Regel");
  const cost = a.usd - a.pnl, cls = a.pnl >= 0 ? "pos" : "neg";
  if (a.kind === "half") return li(`Sold half ${sym}`, `${xs(a.multiple)} · entry back`, signed(a.pnl), "x" + (a.multiple || 0).toFixed(2), cls);
  if (a.kind === "stop") return li(`Stopped ${sym}`, `hard stop −${Math.round(P.hardStop * 100)}%`, signed(a.pnl), cost > 0 ? pct(a.pnl / cost) : "", cls);
  if (a.kind === "trail") return li(`Closed ${sym}`, `trail ${Math.round(P.trail * 100)}% off high`, signed(a.pnl), "x" + (a.multiple || 0).toFixed(2), cls);
  if (a.kind === "tp") return li(`Took profit ${xs(a.multiple)} · ${sym}`, "Take Profit", signed(a.pnl), cost > 0 ? pct(a.pnl / cost) : "", cls);
  if (a.kind === "sl") return li(`Stop-loss ${sym}`, "Stop-Loss", signed(a.pnl), cost > 0 ? pct(a.pnl / cost) : "", cls);
  return li(`Sold ${a.frac < 0.999 ? Math.round(a.frac * 100) + "% " : ""}${sym}`, a.trader && a.lagSec != null ? `same exit as ${esc(a.trader)}` : "von Hand",
            signed(a.pnl), cost > 0 ? pct(a.pnl / cost) : "", cls);
}

let shownTop = "";
function renderActivity() {
  const list = acc.activity;
  const home = list.filter(a => a.kind !== "rule").slice(0, 8).map(actRow).join("") || `<li class="empty">Noch nichts. Bot starten: der Scout sucht dann selbst.</li>`;
  const top = list[0] ? list[0].t + list[0].kind : "";
  $("actHome").innerHTML = home;
  if (top && top !== shownTop && shownTop) $("actHome").firstElementChild?.classList.add("new");
  shownTop = top;
  $("actAll").style.display = filter === "log" ? "none" : ""; $("logBox").style.display = filter === "log" ? "" : "none";
  if (filter === "log") renderLog();
  const f = { log: () => true, all: () => true, copy: a => BUY_KINDS.has(a.kind), exit: a => EXIT_KINDS.has(a.kind), rule: a => a.kind === "rule" }[filter];
  const all = list.filter(f);
  $("actAll").innerHTML = all.slice(0, 200).map(actRow).join("") || `<li class="empty">Keine Einträge.</li>`;
  const s = stats(acc);
  $("actInfo").textContent = `${s.copies} Käufe · ${s.closed} geschlossen`;
  $("actInfo2").textContent = `${all.length} Einträge`;
}

function renderGrid() {
  const on = traders.filter(t => t.on).length;
  $("gridInfo").textContent = `${on} von ${traders.length} aktiv · ${P.delaySec}s behind`;
  const cards = traders.map((t, i) => {
    const s = seen[t.wallet], p = s && prices[s.mint];
    const pnl = acc.closed.filter(c => c.trader === t.name).reduce((x, c) => x + c.pnl, 0);
    const last = s ? `<span class="${s.side === "buy" ? "b" : "s"}">${s.side === "buy" ? "bought" : "sold"}</span> ${esc(p ? p.symbol : short(s.mint))} · ${hm(s.t)}`
                   : `wartet auf Trade · ${short(t.wallet)}`;
    return `<div class="card${t.on ? "" : " off"}" data-i="${i}" data-w="${esc(t.wallet)}" title="Antippen: an/aus">
      <div class="who">${avatar(t.name)}<b>${esc(t.name)}</b><span class="right tiny ${pnl >= 0 ? "pos" : "neg"}">${pnl ? signed(pnl) : ""}</span></div>
      <div class="last">${last}</div></div>`;
  }).join("");
  $("grid").innerHTML = cards + `<div class="card add" id="addCard">+ Trader</div>`;
}
function flash(wallet) {
  setTimeout(() => { const el = document.querySelector(`.card[data-w="${wallet}"]`); if (el) { el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1500); } }, 50);
}

function renderAccount() {
  const s = stats(acc);
  $("sCopies").textContent = `${s.copies} · ${s.wins}W ${s.losses}L`;
  $("sProfit").textContent = signed(s.profit); $("sProfit").className = s.profit >= 0 ? "pos" : "neg";
  $("sBest").textContent = s.best ? `${xs(s.best.multiple)} ${esc(s.best.symbol)}` : "–";
  $("sBehind").textContent = `${Math.round(P.sizePct * 100)}% · max ${P.maxOpen} · −${Math.round(P.hardStop * 100)}% · ${P.halfAt}× · trail ${Math.round(P.trail * 100)}%`;
  $("sCash").textContent = money(acc.cash);
  $("sFees").textContent = money(acc.fees);
  $("depLbl").textContent = money(P.deposit).replace(".00", "");
  const per = {};
  for (const c of acc.closed) { const k = c.trader || "Scout"; const x = per[k] || (per[k] = { n: 0, w: 0, pnl: 0 }); x.n++; x.pnl += c.pnl; if (c.pnl > 0) x.w++; }
  $("perTrader").innerHTML = Object.entries(per).sort((a, b) => b[1].pnl - a[1].pnl).map(([name, x]) =>
    `<li>${avatar(name)}<div class="mid"><b>${esc(name)}</b><span>${x.n} Trades · ${x.w}W ${x.n - x.w}L</span></div>
     <div class="amt"><b class="${x.pnl >= 0 ? "pos" : "neg"}">${signed(x.pnl)}</b></div></li>`).join("") || `<li class="empty">Noch keine abgeschlossenen Trades.</li>`;
  $("openPos").innerHTML = Object.values(acc.pos).map(p => {
    const q = prices[p.mint], m = q ? q.price / p.entry : 1;
    return `<li data-mint="${esc(p.mint)}">${avatar(p.symbol, (q && q.img) || p.img)}<div class="mid"><b>${esc(p.symbol)} · ${xs(m)}${p.half ? " · trailing" : ""}</b><span>${p.trader ? "von " + esc(p.trader) : "Scout · Punkte " + p.score} · seit ${hm(p.at)} · Einsatz ${money(p.book.cost)}</span></div>
      <div class="amt"><button class="link tiny" data-sell="${esc(p.mint)}">Verkaufen</button></div></li>`;
  }).join("") || `<li class="empty">Keine offenen Positionen.</li>`;
}

function renderTraders() {
  $("traderList").innerHTML = traders.map((t, i) => `<li>${avatar(t.name)}<div class="mid"><b>${esc(t.name)}</b><code>${esc(t.wallet)}</code></div>
    <button data-tog="${i}">${t.on ? "An" : "Aus"}</button><button data-del="${i}">✕</button></li>`).join("")
    || `<li class="muted tiny" style="display:block">Noch keine Trader. Oben „Gute Trader finden“ drücken oder eine Wallet unten eintragen.</li>`;
}

const RULES = [
  ["deposit", "Startgeld ($)", 1], ["sizePct", "Kauf: % vom freien Geld", 100], ["maxOpen", "Max. offene Positionen", 1],
  ["hardStop", "Hard Stop (%, solange nie 2×)", 100], ["halfAt", "Einsatz zurück bei (×)", 1], ["trail", "Trailing vom Hoch (%)", 100],
  ["minScore", "Scout: Mindest-Punkte (0–100)", 1], ["delaySec", "Wallets: Sekunden danach", 1],
  ["takeProfitX", "Extra: alles raus bei (×, 0 = aus)", 1], ["stopLoss", "Extra: Stop-Loss (%, 0 = aus)", 100],
];
function renderRules() {
  $("rulesServer").style.display = serverMode ? "" : "none";
  $("rules").classList.toggle("ro", serverMode);
  $("rules").innerHTML = RULES.map(([k, label, f]) => `<label for="r_${k}">${label}</label><input id="r_${k}" data-k="${k}" data-f="${f}" type="number" min="0" step="any" value="${+(P[k] * f).toFixed(4)}">`).join("")
    + `<label for="r_scout">Scout kauft selbst</label><input id="r_scout" type="checkbox" ${P.scout ? "checked" : ""} style="width:auto;justify-self:end">`
    + `<label for="r_same">Mit der Wallet verkaufen</label><input id="r_same" type="checkbox" ${P.sameExits ? "checked" : ""} style="width:auto;justify-self:end">`;
}

function render() { if (!acc) return; renderTop(); renderGrid(); renderActivity(); renderAccount(); if (filter === "log") renderLog(); }

function toast(text, bad = false) {
  const el = $("toast");
  el.textContent = text; el.className = "toast show" + (bad ? " bad" : "");
  if (!bad) document.body.classList.add("won");
  setTimeout(() => { el.className = "toast" + (bad ? " bad" : ""); document.body.classList.remove("won"); }, 2600);
}

function setRunning(on) {
  running = on;
  save("deskRunning", on);
  if (typeof keepAwake === "function") keepAwake(on && !IS_EXT);
  $("runBtn").textContent = serverMode ? "☁ läuft auf GitHub, rund um die Uhr" : on ? "■ Bot stoppen" : "▶ Bot starten";
  $("runBtn").disabled = serverMode;
  $("runBtn").classList.toggle("on", on && !serverMode);
  $("live").textContent = serverMode ? "● Server 24/7 · Spielgeld" : on ? "● Live · Spielgeld" : "● Spielgeld";
  $("live").classList.toggle("live", on || serverMode);
  if (on) { for (const k of Object.keys(cursor)) delete cursor[k]; agent.scoutAt = 0; }   // after a pause: only new trades, the Scout looks at once
  render();
}

// ---------- events ----------
document.querySelector("nav.bottom").addEventListener("click", e => {
  const b = e.target.closest("button[data-p]"); if (!b) return;
  for (const x of document.querySelectorAll("nav.bottom button")) x.classList.toggle("on", x === b);
  for (const s of document.querySelectorAll(".page")) s.classList.toggle("on", s.id === b.dataset.p);
  if (b.dataset.p === "home") requestAnimationFrame(drawChart);
  window.scrollTo(0, 0);
});
const go = p => document.querySelector(`nav.bottom button[data-p="${p}"]`).click();

$("ranges").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  range = b.dataset.r; save("copyRange", range);
  for (const x of $("ranges").children) x.classList.toggle("on", x === b);
  drawChart();
});
$("filters").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  filter = b.dataset.f;
  for (const x of $("filters").children) x.classList.toggle("on", x === b);
  renderActivity();
});
$("runBtn").addEventListener("click", () => {
  if (!running && !P.scout && !traders.some(t => t.on && B58.test(t.wallet))) { go("agents"); $("tMsg").textContent = "Scout ist aus: schalte ihn unter Regeln an oder füge eine Wallet hinzu."; return; }
  setRunning(!running);
});
$("seeAll").addEventListener("click", () => go("activity"));
for (const id of ["actHome", "actAll", "openPos"]) $(id).addEventListener("click", e => {
  if (e.target.closest("button")) return;
  const li = e.target.closest("li[data-mint]"); if (li) openCoin(li.dataset.mint);
});
$("notifBtn").addEventListener("click", async () => {
  try { const r = await Notification.requestPermission(); $("notifBtn").textContent = r === "granted" ? "🔔 Benachrichtigungen sind an" : "🔕 Benachrichtigungen blockiert (Browser-Einstellungen)"; }
  catch { $("notifBtn").textContent = "Benachrichtigungen gehen hier nicht"; }
});
$("grid").addEventListener("click", e => {
  if (e.target.closest("#addCard")) { go("agents"); $("tName").focus(); return; }
  const c = e.target.closest(".card[data-i]"); if (!c) return;
  const t = traders[+c.dataset.i]; t.on = !t.on; save("copyTraders", traders); renderGrid(); renderTraders();
});
$("tAdd").addEventListener("click", () => {
  let wallet = $("tWallet").value.trim();
  const m = wallet.match(/[1-9A-HJ-NP-Za-km-z]{32,44}/); if (m) wallet = m[0];   // a pasted Solscan/FOMO link works too
  const name = $("tName").value.trim().replace(/^@/, "") || short(wallet);
  if (!B58.test(wallet)) { $("tMsg").textContent = "Das ist keine Solana-Wallet-Adresse (32–44 Zeichen)."; return; }
  if (traders.some(t => t.wallet === wallet)) { $("tMsg").textContent = "Diesen Trader gibt es schon."; return; }
  traders.push({ name, wallet, on: true }); save("copyTraders", traders);
  $("tName").value = $("tWallet").value = ""; $("tMsg").textContent = `${name} hinzugefügt.`;
  renderTraders(); renderGrid();
});
$("traderList").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.tog != null) traders[+b.dataset.tog].on = !traders[+b.dataset.tog].on;
  if (b.dataset.del != null) traders.splice(+b.dataset.del, 1);
  save("copyTraders", traders); renderTraders(); renderGrid();
});
$("rules").addEventListener("change", e => {
  const el = e.target;
  if (el.id === "r_same") P.sameExits = el.checked;
  else if (el.id === "r_scout") P.scout = el.checked;
  else if (el.dataset.k) { const v = Number(el.value); if (v >= 0) P[el.dataset.k] = v / Number(el.dataset.f); }
  save("deskRules", P); render();
});
load("redditAppId", "").then(v => { $("redditId").value = v; });
$("redditId").addEventListener("change", () => { save("redditAppId", $("redditId").value.trim()); redditTok = null; $("redditMsg").textContent = "Gespeichert. Wird bei der nächsten Suche benutzt."; });
$("rulesReset").addEventListener("click", () => { P = { ...COPY_DEFAULTS }; save("deskRules", P); renderRules(); render(); });
$("openPos").addEventListener("click", async e => {
  const b = e.target.closest("button[data-sell]"); if (!b) return;
  const mint = b.dataset.sell;
  try { await priceCoins([mint]); } catch {}
  const p = prices[mint];
  if (!p) { alert("Kein Preis für diesen Coin gerade."); return; }
  copySell(acc, { mint, price: p.price, liq: p.liq, mc: p.mc, why: "hand", now: Date.now() });
  point(); persist(); render();
});
$("resetAcc").addEventListener("click", () => {
  if (serverMode) { alert("Das Server-Konto läuft auf GitHub. Zum Neustart dort den Branch desk-data löschen."); return; }
  if (!confirm(`Konto zurücksetzen? Alle Positionen und die Activity werden gelöscht, du startest mit ${money(P.deposit)} Spielgeld.`)) return;
  acc = newAccount(P); queue = []; agent.checked = 0; persist(); render();
});

// ---------- "Gute Trader finden": hot coins on GeckoTerminal -> their recent trades -> wallets that took the most profit ----------
const GT = "https://api.geckoterminal.com/api/v2/networks/solana";
const sleep = ms => new Promise(r => setTimeout(r, ms));
let found = [];
async function gt(path) {
  for (let i = 0; i < 3; i++) {
    const r = await fetch(GT + path, { headers: { Accept: "application/json" }, cache: "no-store" });
    if (r.status === 429) { await sleep(8000); continue; }   // free limit: about 30 calls a minute
    if (!r.ok) throw new Error("GeckoTerminal " + r.status);
    return r.json();
  }
  throw new Error("GeckoTerminal: zu viele Anfragen, gleich nochmal versuchen");
}
// Hot coins from every free source: GeckoTerminal trending, DexScreener boosts + new profiles + pair stats, Reddit mentions.
const DS = "https://api.dexscreener.com";
const SUBS = "solana+memecoins+SolanaMemeCoins+CryptoMoonShots+pumpfun";
// Reddit blocks anonymous .json reads (403, tested 2026-11-08), so it goes through the user's own free Reddit app of type
// "installed app": app-only OAuth with just the app's ID (no secret, no Reddit password), token cached until it expires.
let redditTok = null;
async function redditPosts() {
  const id = (await load("redditAppId", "")).trim();
  if (!id) throw new Error("keine Reddit-App-ID");
  if (!redditTok || redditTok.until < Date.now()) {
    let dev = await load("redditDevice", "");
    if (!dev) { dev = Array.from(crypto.getRandomValues(new Uint8Array(15)), b => b.toString(16).padStart(2, "0")).join(""); save("redditDevice", dev); }
    const r = await fetch("https://www.reddit.com/api/v1/access_token", { method: "POST",
      headers: { Authorization: "Basic " + btoa(id + ":") },   // form body via URLSearchParams: Reddit's CORS allows only Authorization
      body: new URLSearchParams({ grant_type: "https://oauth.reddit.com/grants/installed_client", device_id: dev }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.access_token) throw new Error("Reddit-Anmeldung: " + (j.error || r.status));
    redditTok = { token: j.access_token, until: Date.now() + ((j.expires_in || 3600) - 60) * 1000 };
  }
  const r = await fetch(`https://oauth.reddit.com/r/${SUBS}/new?limit=100&raw_json=1`, { headers: { Authorization: "Bearer " + redditTok.token } });
  if (!r.ok) { if (r.status === 401) redditTok = null; throw new Error("Reddit " + r.status); }
  return ((await r.json()).data?.children || []).map(c => c.data);
}
let hot = [];
async function getJson(url) { const r = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" }); if (!r.ok) throw new Error(r.status); return r.json(); }
async function hotCoins(msg) {
  const id = (await load("redditAppId", "")).trim();
  const r = await scoutHot({ getJson, gt, reddit: id ? redditPosts : null, msg });
  for (const [m, x] of Object.entries(r.prices)) prices[m] = { ...x, t: Date.now() };
  return r.list;
}

async function findTraders() {
  const btn = $("findBtn"), msg = t => { $("findMsg").textContent = t; };
  btn.disabled = true; found = []; renderFound();
  try {
    hot = await hotCoins(msg); renderHot();
    const pools = hot.filter(c => c.pool).slice(0, 8);
    const got = [];
    for (let i = 0; i < pools.length; i++) {
      msg(`Prüfe Trader von ${pools[i].symbol} (${i + 1}/${pools.length}) …`);
      await sleep(2200);
      try { const j = await gt(`/pools/${pools[i].pool}/trades?trade_volume_in_usd_greater_than=20`); got.push({ coin: pools[i].symbol, trades: (j.data || []).map(d => d.attributes) }); } catch {}
    }
    found = rankWallets(got);
    msg(found.length ? `${hot.length} heiße Coins aus 4 Quellen, ${found.length} Wallets mit Gewinn in den Top ${got.length}. Glück oder Können? Erst mit Spielgeld testen.`
                     : "Gerade keine klaren Gewinner gefunden. In ein paar Minuten nochmal versuchen.");
  } catch (e) { msg("Suche fehlgeschlagen: " + (e.message || e)); }
  btn.disabled = false; renderFound();
}
function renderHot() {
  $("hotHead").style.display = hot.length ? "" : "none";
  $("hotList").innerHTML = hot.slice(0, 10).map(c => {
    const soc = (c.links || []).map(x => x === "twitter" ? "𝕏" : x === "telegram" ? "TG" : x === "discord" ? "DC" : "").filter(Boolean).join(" ");
    return `<li>${avatar(c.symbol || "?", c.img)}<div class="mid"><b>${esc(c.symbol || short(c.mint))} <span class="score">${c.score}</span></b>
      <code>${esc(c.src.join(" · "))}${soc ? " · " + soc : ""}</code></div>
      <div class="amt"><b class="${c.chg1h >= 0 ? "pos" : "neg"}">${c.chg1h >= 0 ? "+" : ""}${(c.chg1h || 0).toFixed(0)}%</b><span>${big(c.vol1h)} Vol 1h · ${c.buys1h}/${c.sells1h}</span></div>
      ${c.url ? `<a class="link tiny" href="${esc(c.url)}" target="_blank" rel="noopener">↗</a>` : ""}</li>`;
  }).join("");
}
function renderFound() {
  $("findList").innerHTML = found.map((r, i) => {
    const have = traders.some(t => t.wallet === r.wallet);
    return `<li>${avatar(r.wallet)}<div class="mid"><b>${short(r.wallet)}</b><code>${esc(r.coins.slice(0, 4).join(", "))} · ${r.wins}W ${r.losses}L</code></div>
      <div class="amt"><b class="pos">${signed(r.pnl)}</b><span>Gewinn</span></div>
      <a class="link tiny" href="https://solscan.io/account/${esc(r.wallet)}" target="_blank" rel="noopener">↗</a>
      <button class="follow" data-follow="${i}" ${have ? "disabled" : ""}>${have ? "✓" : "Folgen"}</button></li>`;
  }).join("");
}
$("findBtn").addEventListener("click", findTraders);
$("findList").addEventListener("click", e => {
  const b = e.target.closest("button[data-follow]"); if (!b) return;
  const r = found[+b.dataset.follow];
  if (!traders.some(t => t.wallet === r.wallet)) traders.push({ name: "Top-" + r.wallet.slice(0, 4), wallet: r.wallet, on: true });
  save("copyTraders", traders); renderTraders(); renderGrid(); renderFound();
});

// ---------- coin page: candles with entry / exits, the desk rules for this coin, the position ----------
let coinMint = "", coinChart = null, coinCandles = null, coinVol = null, coinLoadedAt = 0, coinOhlcv = [];
function openCoin(mint) {
  coinMint = mint; coinOhlcv = []; coinLoadedAt = 0;
  for (const x of document.querySelectorAll("nav.bottom button")) x.classList.remove("on");
  for (const sct of document.querySelectorAll(".page")) sct.classList.toggle("on", sct.id === "coin");
  window.scrollTo(0, 0);
  if (!coinChart) {
    coinChart = LWC.createChart($("cChart"), {
      autoSize: true, layout: { background: { color: "transparent" }, textColor: "#8a90a0", fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: "#151924" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.28 } }, timeScale: { borderVisible: false, timeVisible: true },
      localization: { locale: "de-DE", priceFormatter: big }, crosshair: { mode: 0 },
    });
    coinCandles = coinChart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444",
                                                   priceFormat: { type: "custom", formatter: big, minMove: 0.01 } });
    coinVol = coinChart.addHistogramSeries({ priceScaleId: "v", color: "#f59e0b", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    coinChart.priceScale("v").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  }
  coinCandles.setData([]); coinVol.setData([]); coinCandles.setMarkers([]);
  priceCoins([mint]).catch(() => {}).then(() => { loadCoinChart(); renderCoin(); });
  renderCoin();
}
async function loadCoinChart() {
  const p = prices[coinMint] || {}, pos = acc.pos[coinMint];
  const pool = (pos && pos.pool) || p.pool;
  if (!pool) return;
  coinLoadedAt = Date.now();
  try {
    const j = await gt(`/pools/${pool}/ohlcv/minute?aggregate=1&limit=180&currency=usd`);
    coinOhlcv = ((j.data && j.data.attributes && j.data.attributes.ohlcv_list) || []).slice().reverse();
  } catch { coinOhlcv = []; }
  drawCoinChart();
}
function drawCoinChart() {
  const p = prices[coinMint] || {};
  const k = p.price > 0 && p.mc > 0 ? p.mc / p.price : 1;   // price -> market cap (the video shows MC)
  const seenT = new Set(), c = [], v = [];
  for (const [t, o, h, l, cl, vol] of coinOhlcv) { if (seenT.has(t)) continue; seenT.add(t); c.push({ time: t, open: o * k, high: h * k, low: l * k, close: cl * k }); v.push({ time: t, value: vol }); }
  coinCandles.setData(c); coinVol.setData(v);
  if (!c.length) return;
  const nearest = ts => c.reduce((b, d) => Math.abs(d.time - ts) < Math.abs(b - ts) ? d.time : b, c[0].time);
  const marks = acc.activity.filter(a => a.mint === coinMint && (BUY_KINDS.has(a.kind) || EXIT_KINDS.has(a.kind)) && a.t / 1000 >= c[0].time - 60)
    .map(a => BUY_KINDS.has(a.kind) ? { time: nearest(a.t / 1000), position: "belowBar", color: "#60a5fa", shape: "arrowUp", text: "Entry " + money(a.usd) }
      : { time: nearest(a.t / 1000), position: "aboveBar", color: a.pnl >= 0 ? "#22c55e" : "#ef4444", shape: "arrowDown",
          text: a.kind === "half" ? `Sold half · ${xs(a.multiple)}` : a.kind === "stop" ? "Stop" : a.kind === "trail" ? `Closed ${xs(a.multiple)}` : "Sold" })
    .sort((a, b) => a.time - b.time);
  coinCandles.setMarkers(marks);
  coinChart.timeScale().fitContent();
}
function renderCoin() {
  if (!coinMint) return;
  if (Date.now() - coinLoadedAt > 30000) loadCoinChart();
  const p = prices[coinMint] || {}, pos = acc.pos[coinMint];
  const acts = acc.activity.filter(a => a.mint === coinMint);
  const buyA = acts.filter(a => BUY_KINDS.has(a.kind))[0];   // the latest buy of this coin
  const closed = acc.closed.find(c => c.mint === coinMint);
  const sym = p.symbol || (pos && pos.symbol) || (acts[0] && acts[0].symbol) || short(coinMint);
  $("cAv").innerHTML = avatar(sym, p.img || (pos && pos.img));
  $("cName").textContent = sym;
  $("cMeta").textContent = `$${sym} · Solana${p.created ? " · " + ago(p.created) + " alt" : ""}`;
  $("cLink").href = p.url || `https://dexscreener.com/solana/${coinMint}`;
  $("cMc").textContent = big(p.mc);
  const mcIn = (pos && pos.mcIn) || (buyA && buyA.mc) || 0;
  const ch = mcIn > 0 && p.mc > 0 ? p.mc / mcIn - 1 : null;
  $("cSince").textContent = ch == null ? "Der Bot hat diesen Coin nicht gekauft" : `${ch >= 0 ? "▲" : "▼"} ${pct(ch)} seit der Bot gekauft hat`;
  $("cSince").className = "since " + (ch == null ? "muted" : ch >= 0 ? "pos" : "neg");
  $("cRulesHead").textContent = `Desk rules · $${sym}`;
  const x = pos && p.price > 0 ? p.price / pos.entry : 0;
  const k = pos && p.price > 0 && p.mc > 0 ? p.mc / p.price : 0;
  const rows = [];
  if (pos || buyA) {
    const half = acts.find(a => a.kind === "half"), stop = acts.find(a => a.kind === "stop"), trail = acts.find(a => a.kind === "trail");
    const entryMc = pos && k ? pos.entry * k : mcIn;
    rows.push(["Hard stop −" + Math.round(P.hardStop * 100) + "%", `verkauft bei ${big(entryMc * (1 - P.hardStop))} MC, nur wenn ${P.halfAt}× nie kommt`,
               stop ? ["ausgelöst", "armed"] : pos && !pos.half ? ["scharf", "armed"] : ["aus", ""]]);
    rows.push([`Exit bei ${P.halfAt}×`, half ? `${money(half.usd)} zurück · ${signed(half.pnl)}` : `bei ${big(entryMc * P.halfAt)} MC kommt der Einsatz zurück`,
               half ? ["Einsatz zurück", "done"] : pos ? ["wartet", ""] : ["–", ""]]);
    rows.push([`Trailing ${Math.round(P.trail * 100)}%`, pos && pos.half && k ? `Hoch ${big(pos.high * k)} → verkauft unter ${big(pos.high * k * (1 - P.trail))}` : "nach dem Einsatz-zurück folgt der Rest dem Hoch",
               trail ? ["geschlossen", "done"] : pos && pos.half ? ["aktiv", "armed"] : ["wartet", ""]]);
    if (buyA) rows.push(["Compounder", `${Math.round((buyA.pct || P.sizePct) * 100)}% vom freien Geld · ${money(buyA.usd)} · max ${P.maxOpen} offen`, ["sized", "sized"]]);
    if (buyA) rows.push(["Executor", `${buyA.kind === "copy" ? "kopiert von " + esc(buyA.trader) : "Scout · Punkte " + (buyA.score || "–")} · gekauft bei ${big(buyA.mc)} MC (Spielgeld)`, ["gekauft", "bought"]]);
  }
  $("cRules").innerHTML = rows.map(([b, sub, [st, cls]]) => `<li><div class="mid"><b>${b}</b><span>${sub}</span></div><span class="st ${cls}">${st}</span></li>`).join("")
    || `<li><div class="mid"><span>Keine Trades in diesem Coin.</span></div></li>`;
  $("cRulesInfo").textContent = pos ? (pos.half ? "Trailing aktiv" : `${xs(x)} · ${P.halfAt}× steht aus`) : closed ? "geschlossen" : "";
  if (pos) {
    const val = p.price > 0 ? accountValue({ cash: 0, pos: { [pos.mint]: pos } }, { [pos.mint]: p }) : pos.book.cost;
    $("cPosVal").textContent = money(val);
    $("cPosSub").textContent = `${xs(x)} · Einsatz ${money(pos.book.cost)} · schon verkauft: ${signed(pos.book.realized)} · seit ${hm(pos.at)}`;
    $("cSell").style.display = "";
  } else {
    $("cPosVal").textContent = closed ? signed(closed.pnl) : "–";
    $("cPosSub").textContent = closed ? `geschlossen ${hm(closed.out)} · ${xs(closed.multiple)}` : "keine Position";
    $("cSell").style.display = "none";
  }
}
const ago = t => { const m = Math.round((Date.now() - t) / 60000); return m < 60 ? m + " min" : m < 2880 ? Math.floor(m / 60) + " h " + (m % 60) + " min" : Math.floor(m / 1440) + " Tage"; };
$("coinBack").addEventListener("click", () => go("home"));
$("cSell").addEventListener("click", async () => {
  try { await priceCoins([coinMint]); } catch {}
  const p = prices[coinMint];
  if (!p || !acc.pos[coinMint]) return;
  copySell(acc, { mint: coinMint, price: p.price, liq: p.liq, mc: p.mc, why: "hand", now: Date.now() });
  point(); persist(); render(); renderCoin(); drawCoinChart();
});

// ---------- website / phone app (the same page outside the Chrome extension) ----------
const IS_EXT = typeof chrome !== "undefined" && !!(chrome.runtime && chrome.runtime.id);
let wakeLock = null;
async function keepAwake(on) {   // a phone stops the page when the screen goes off: keep it on while the bot runs
  try {
    if (on && !wakeLock && navigator.wakeLock) { wakeLock = await navigator.wakeLock.request("screen"); wakeLock.addEventListener("release", () => { wakeLock = null; }); }
    if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
  } catch {}
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && running) keepAwake(true); });
function webApp() {
  $("panelLink").style.display = "none";
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
  let prompt = null;
  window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); prompt = e; $("installBtn").style.display = ""; });
  $("installBtn").addEventListener("click", async () => { if (!prompt) return; prompt.prompt(); await prompt.userChoice.catch(() => {}); prompt = null; $("installBtn").style.display = "none"; });
  const note = document.createElement("div");
  note.className = "webnote";
  note.textContent = "Web-Version: Der Bot läuft, solange diese Seite offen ist (am Handy bleibt der Bildschirm dafür an). Daten bleiben nur in diesem Browser.";
  $("account").appendChild(note);
}

// ---------- live log (like the terminal in the video): one line per decision of every agent ----------
function say(who, text) {
  if (serverMode || !acc) return;
  if (!acc.log) acc.log = [];
  acc.log.unshift({ t: Date.now(), who, text });
  if (acc.log.length > 300) acc.log.length = 300;
}
function renderLog() {
  const lines = (serverMode ? serverDoc && serverDoc.log : acc.log) || [];
  $("logBox").innerHTML = lines.slice(0, 200).map(l => `<div><span class="lt">${new Date(l.t).toLocaleTimeString("de-DE")}</span> <span class="lw w-${esc(l.who)}">${esc(l.who)}</span> ${esc(l.text)}</div>`).join("")
    || `<div class="muted">Noch keine Einträge. Bot starten.</div>`;
}

// ---------- "Server 24/7": the desk that runs on GitHub (trencher/desk-runner.mjs), read from the branch desk-data ----------
const REPO = "maxpandelakis-boop/Meme-Bot";
const CONFIG_EDIT = `https://github.com/${REPO}/edit/desk-data/config.json`;
let serverMode = false, serverDoc = null, serverTimer = 0, local = null;
async function fetchServer() {
  try {
    const c = await getJson(`https://api.github.com/repos/${REPO}/commits/desk-data`);   // the newest commit: raw files by sha are never stale
    const d = await getJson(`https://raw.githubusercontent.com/${REPO}/${c.sha}/desk.json`);
    serverDoc = d;
    if (!serverMode) return;
    acc = d.acc; P = { ...COPY_DEFAULTS, ...(d.P || {}) };
    Object.assign(agent, { checked: (d.agent || {}).checked || 0, top: (d.agent || {}).top || [], scoutMsg: (d.agent || {}).scoutMsg || "" });
    for (const [m, x] of Object.entries(d.prices || {})) prices[m] = { ...prices[m], ...x };
    $("serverInfo").textContent = `Stand ${hm(d.updated)} · läuft seit ${hm(d.runStarted)} auf GitHub`;
    $("serverInfo").className = "tiny " + (Date.now() - d.updated < 5 * 60e3 ? "pos" : "neg");
    if (Date.now() - d.updated >= 5 * 60e3) $("serverInfo").textContent += " · seit über 5 Minuten kein Stand (startet gerade neu?)";
  } catch (e) {
    $("serverInfo").textContent = String(e.message || e).includes("404") ? "Der Server-Desk hat noch nicht gestartet." : "Server gerade nicht erreichbar (" + (e.message || e) + ")";
    $("serverInfo").className = "tiny neg";
    if (serverMode && !serverDoc) { acc = newAccount(P); }
  }
  if (serverMode) { render(); renderLog(); renderRules(); }
}
function setMode(m) {
  const toServer = m === "server";
  if (toServer === serverMode) return;
  if (toServer) { local = { acc, P }; serverMode = true; }
  else { serverMode = false; if (local) { acc = local.acc; P = local.P; } }
  save("deskMode", m);
  for (const b of $("modes").children) b.classList.toggle("on", b.dataset.m === m);
  document.body.classList.toggle("server", toServer);
  $("serverInfo").textContent = toServer ? "lade …" : "";
  clearInterval(serverTimer);
  if (toServer) { fetchServer(); serverTimer = setInterval(fetchServer, 90000); }   // GitHub allows 60 API calls an hour without login
  setRunning(running);
  renderRules(); render(); renderLog();
}
$("modes").addEventListener("click", e => { const b = e.target.closest("button[data-m]"); if (b) setMode(b.dataset.m); });

// ---------- share (like the video's Share button) ----------
$("shareBtn").addEventListener("click", async () => {
  const v = value(), s = stats(acc);
  const text = `Trading Desk (Spielgeld): ${money(v)} (${pct(v / acc.deposit - 1)} seit Start mit ${money(acc.deposit)}) · ${s.copies} Trades · ${s.wins}W ${s.losses}L`
             + (serverMode ? " · läuft 24/7" : "");
  const url = IS_EXT ? "" : location.href.split("#")[0];
  try {
    if (navigator.share) await navigator.share({ title: "Trading Desk", text, url: url || undefined });
    else { await navigator.clipboard.writeText(text + (url ? " " + url : "")); toast("KOPIERT"); }
  } catch {}
});

// ---------- Chief of Staff: change the desk's rules in plain words ----------
const chat = [];
function bubble(who, text) {
  chat.push({ who, text, t: Date.now() });
  $("chatBox").innerHTML = chat.slice(-30).map(c => `<div class="msg ${c.who}"><div>${esc(c.text).replace(/\n/g, "<br>")}</div><span>${hm(c.t)}</span></div>`).join("");
  $("chatBox").scrollTop = 1e9;
}
const num = s => Number(String(s).replace(",", "."));
// "x %" / "x x" etc. -> rule changes; returns [changes {key: value}, answer] (pure text parsing, nothing is sent anywhere)
function understand(t) {
  const s = t.toLowerCase(), ch = {};
  let m;
  if (/\b(status|wie läuft|wie geht|how)\b/.test(s)) {
    const st = stats(acc);
    return [ch, `${money(value())} (${pct(value() / acc.deposit - 1)}) · ${Object.keys(acc.pos).length} offen · ${st.copies} Trades · ${st.wins}W ${st.losses}L · Gebühren ${money(acc.fees)}.`];
  }
  if (/(klein|small)/.test(s)) Object.assign(ch, { sizePct: COPY_DEFAULTS.sizePct, maxOpen: COPY_DEFAULTS.maxOpen });
  if ((m = s.match(/(\d+(?:[.,]\d+)?)\s*%\s*(?:vom|von|of)\s*(?:freien|free)/)) || (m = s.match(/(?:size|einsatz|kauf)\D{0,12}(\d+(?:[.,]\d+)?)\s*%/))) ch.sizePct = num(m[1]) / 100;
  if ((m = s.match(/(?:max(?:imal)?|höchstens|nur)\s*(\d+)\s*(?:offen|open|coins?|positionen)?/))) ch.maxOpen = Math.max(1, Math.round(num(m[1])));
  if ((m = s.match(/stop\D{0,10}(\d+(?:[.,]\d+)?)\s*%/))) ch.hardStop = num(m[1]) / 100;
  if ((m = s.match(/trail\w*\D{0,10}(\d+(?:[.,]\d+)?)\s*%/))) ch.trail = num(m[1]) / 100;
  if ((m = s.match(/(?:bei|at|half at|hälfte bei)\s*(\d+(?:[.,]\d+)?)\s*[x×]/))) ch.halfAt = num(m[1]);
  if ((m = s.match(/(?:punkte|score)\D{0,8}(\d+)/))) ch.minScore = num(m[1]);
  if ((m = s.match(/(?:budget|startgeld|start mit)\D{0,6}(\d+(?:[.,]\d+)?)/))) ch.deposit = num(m[1]);
  if (/scout\s*(aus|off)/.test(s)) ch.scout = false;
  if (/scout\s*(an|on|ein)/.test(s)) ch.scout = true;
  if (/(nicht mehr nachlegen|not adding|no adding|kein nachkauf)/.test(s) && !Object.keys(ch).length) return [ch, "Nachkaufen in einen Coin, den der Desk schon hält, macht er nie. Das ist fest eingebaut."];
  if (!Object.keys(ch).length) {
    if (/^(start|starte|los|go)\b/.test(s)) return [{ run: true }, "Desk startet."];
    if (/^(stop|stopp|halt|pause)\b/.test(s)) return [{ run: false }, "Desk angehalten."];
    return [ch, "Das habe ich nicht verstanden. Beispiele:\n„40% vom freien Geld, max 2 offen“\n„stop 8%“ · „trail 10%“ · „hälfte bei 2x“ · „punkte 70“\n„halte den desk klein“ · „status“ · „start“ / „stop“"];
  }
  const label = { sizePct: v => `${Math.round(v * 100)}% vom freien Geld`, maxOpen: v => `max ${v} offen`, hardStop: v => `Hard Stop −${Math.round(v * 100)}%`,
                  trail: v => `Trailing ${Math.round(v * 100)}%`, halfAt: v => `Einsatz zurück bei ${v}×`, minScore: v => `Scout ab ${v} Punkten`,
                  deposit: v => `Budget ${money(v)} (gilt beim nächsten Neustart des Kontos)`, scout: v => `Scout ${v ? "an" : "aus"}` };
  return [ch, "Regeln gesetzt: " + Object.entries(ch).map(([k, v]) => label[k](v)).join(", ") + "."];
}
$("chatForm").addEventListener("submit", e => {
  e.preventDefault();
  const t = $("chatIn").value.trim(); if (!t) return;
  $("chatIn").value = "";
  bubble("me", t);
  const [ch, answer] = understand(t);
  if ("run" in ch) {
    if (serverMode) { bubble("bot", "Der Server-Desk läuft immer. Anhalten: auf GitHub unter Actions → Trencher desk → Disable workflow."); return; }
    setRunning(ch.run); bubble("bot", answer); return;
  }
  if (!Object.keys(ch).length) { bubble("bot", answer); return; }
  if (serverMode) {
    const rules = { ...((serverDoc && serverDoc.P) || {}), ...ch };
    const keep = Object.fromEntries(Object.entries(rules).filter(([k, v]) => k in COPY_DEFAULTS && v !== COPY_DEFAULTS[k]));
    navigator.clipboard && navigator.clipboard.writeText(JSON.stringify({ rules: keep }, null, 2)).catch(() => {});
    bubble("bot", answer.replace("Regeln gesetzt", "Für den Server-Desk") + "\nDer Text für config.json ist kopiert. Auf GitHub einfügen und speichern (Link unten), der Desk liest ihn in einer Minute.");
    $("chatLink").href = CONFIG_EDIT; $("chatLink").style.display = "";
    return;
  }
  Object.assign(P, ch); save("deskRules", P); renderRules(); render();
  say("rules", answer);
  bubble("bot", answer + " Gilt ab sofort.");
});

// ---------- start ----------
(async () => {
  try { $("ver").textContent = "v" + chrome.runtime.getManifest().version; } catch { $("ver").textContent = "web"; }
  if (!IS_EXT) webApp();
  P = { ...COPY_DEFAULTS, ...(await load("deskRules", {})) };
  traders = await load("copyTraders", []);
  acc = await load("deskAcc", null) || newAccount(P);   // the desk starts a fresh $20 account (the old copy account stays stored)
  queue = await load("deskQueue", []);
  range = await load("copyRange", "live");
  for (const x of $("ranges").children) x.classList.toggle("on", x.dataset.r === range);
  renderRules(); renderTraders();
  const open = Object.keys(acc.pos);
  if (open.length) priceCoins(open).then(render).catch(() => {});
  try { if (Notification.permission === "granted") $("notifBtn").textContent = "🔔 Benachrichtigungen sind an"; } catch {}
  setRunning(!!(await load("deskRunning", false)));
  bubble("bot", "Hallo, ich bin dein Chief of Staff. Sag mir Regeln in Worten, z. B. „40% vom freien Geld, max 2 offen“, „stop 8%“ oder „status“.");
  if ((await load("deskMode", "local")) === "server") setMode("server");
})();
