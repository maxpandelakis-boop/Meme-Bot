// Copy-Bot screen of the Trencher (paper money only): follows Solana wallets of traders, buys what they buy `delaySec` later,
// sells when they sell (or at the take-profit), and shows it like the video: balance chart, copy grid, agents, activity, account.
// Data, all free and keyless: PublicNode's Solana JSON-RPC (the traders' transactions) and DexScreener (prices).
import { COPY_DEFAULTS, walletTrades, newAccount, accountValue, copyBuy, copySell, riskExits, stats } from "./copy-engine.js";
import { bestPair } from "./sim.js";

const $ = id => document.getElementById(id);
// PublicNode answers browser/extension origins (CORS *), ~150 ms, no 429 at 1 call/s (tested 2026-11-08 on the user's PC);
// api.mainnet-beta.solana.com refuses extension origins with 403, so it is not used.
const RPCS = ["https://solana-rpc.publicnode.com"];
const DEX = mints => `https://api.dexscreener.com/latest/dex/tokens/${mints.join(",")}`;
const WATCH_MS = 1500;      // one trader wallet checked per tick, round robin
const COPY_MS = 1000;       // due copies executed
const RISK_MS = 5000;       // open positions priced, take-profit / stop-loss checked
const CURVE_MS = 10000;     // a point of the balance curve
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
const agent = { w: "aus", c: "–", e: "–", r: "–", rpc: 0, rpcErr: 0 };
let watchIdx = 0, filter = "all", range = "live", saveTimer = 0;

function persist() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { save("copyAcc", acc); save("copyQueue", queue); }, 300); }

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
                    symbol: (p.baseToken && p.baseToken.symbol) || short(m), img: (p.info && p.info.imageUrl) || "", t: Date.now() };
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
      const r = copyBuy(acc, { mint: q.mint, symbol: p.symbol, price: p.price, liq: p.liq, mc: p.mc, trader: q.trader, lagSec, now: Date.now() }, P);
      if (r.skip && r.skip !== "schon im Coin") rule(q, r.skip);
    } else if (P.sameExits && acc.pos[q.mint] && p) {
      copySell(acc, { mint: q.mint, price: p.price, liq: p.liq, mc: p.mc, frac: q.frac || 1, why: "trader", trader: q.trader, lagSec, now: Date.now() });
    }
  }
  agent.e = `${stats(acc).copies} Käufe`;
  point(); persist(); render();
}

function rule(q, why) {
  const p = prices[q.mint] || {};
  acc.activity.unshift({ t: Date.now(), kind: "rule", mint: q.mint, symbol: p.symbol || short(q.mint), trader: q.trader, why });
  if (acc.activity.length > 400) acc.activity.length = 400;
}

// ---------- Risk: take-profit / stop-loss on the open copies ----------
async function riskCheck() {
  const open = Object.keys(acc.pos);
  agent.r = `TP ${P.takeProfitX}x${P.stopLoss > 0 ? " · SL -" + Math.round(P.stopLoss * 100) + "%" : ""}`;
  if (!open.length) return;
  try { await priceCoins(open); } catch { return; }
  for (const { mint, why } of riskExits(acc, prices, P)) {
    const p = prices[mint], pos = acc.pos[mint];
    const m = p.price / pos.entry;
    const r = copySell(acc, { mint, price: p.price, liq: p.liq, mc: p.mc, why, now: Date.now() });
    if (r.ok) toast(why === "tp" ? `TOOK PROFIT ${xs(m)}` : `STOP-LOSS ${pct(m - 1)}`, why !== "tp");
  }
  point(); persist(); render();
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
    if (!running || busy || !acc) return;
    busy = true;
    try { await fn(); } catch (e) { if (fn === watchOne) agent.w = "RPC-Fehler: " + String(e.message || e).slice(0, 40); }
    busy = false;
  }, ms);
}
loop(watchOne, WATCH_MS);
loop(copyDue, COPY_MS);
loop(riskCheck, RISK_MS);
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
  const data = [];
  for (const p of pts) {
    const time = Math.floor(p.t / 1000);
    if (data.length && data[data.length - 1].time >= time) data[data.length - 1].value = p.v; else data.push({ time, value: p.v });
  }
  const up = data[data.length - 1].value >= data[0].value;
  const col = up ? "#22c55e" : "#ef4444";
  area.applyOptions({ lineColor: col, topColor: up ? "rgba(34,197,94,.28)" : "rgba(239,68,68,.25)", bottomColor: "rgba(0,0,0,0)" });
  area.setData(data);
  const times = new Set(data.map(d => d.time));
  const marks = acc.activity.filter(a => a.t >= from && (a.kind === "copy" || a.kind === "sell" || a.kind === "tp" || a.kind === "sl"))
    .map(a => {
      let time = Math.floor(a.t / 1000);
      if (!times.has(time)) time = data.reduce((b, d) => Math.abs(d.time - time) < Math.abs(b - time) ? d.time : b, data[0].time);
      return a.kind === "copy" ? { time, position: "belowBar", color: "#4f5dff", shape: "circle", size: 0.6 }
                               : { time, position: "aboveBar", color: a.pnl >= 0 ? "#22c55e" : "#ef4444", shape: "circle", size: 0.6 };
    }).sort((a, b) => a.time - b.time);
  area.setMarkers(marks);
  chart.timeScale().fitContent();
}

// ---------- rendering ----------
function renderTop() {
  const v = value(), d = v - acc.deposit;
  const [w, c] = money(v).split(".");
  $("bal").innerHTML = `${w}<span class="cents">.${c}</span>`;
  $("bal2").textContent = money(v);
  const sinceTxt = `${signed(d)} (${pct(d / acc.deposit)}) since deposit`;
  for (const id of ["since", "since2"]) { $(id).textContent = sinceTxt; $(id).className = "since " + (d >= 0 ? "pos" : "neg"); }
  drawChart();
  $("agW").textContent = running ? agent.w : "aus"; $("agC").textContent = running ? agent.c : "aus";
  $("agE").textContent = running ? agent.e : "aus"; $("agR").textContent = running ? agent.r : "aus";
  for (const el of $("agentChips").children) el.classList.toggle("on", running);
}

function actRow(a) {
  const p = prices[a.mint] || {};
  const icon = avatar(a.symbol || "?", p.img);
  if (a.kind === "copy")
    return `<li>${icon}<div class="mid"><b>Copied ${esc(a.symbol)}</b><span>${a.lagSec}s after ${esc(a.trader)} · ${hm(a.t)}</span></div>
            <div class="amt"><b>${money(a.usd)}</b><span>at ${big(a.mc)} MC</span></div></li>`;
  if (a.kind === "rule")
    return `<li>${icon}<div class="mid"><b>Skipped ${esc(a.symbol)}</b><span>${esc(a.why)} · ${esc(a.trader)} · ${hm(a.t)}</span></div>
            <div class="amt"><span>Regel</span></div></li>`;
  const title = a.kind === "tp" ? `Took profit ${xs(a.multiple)} · ${esc(a.symbol)}` : a.kind === "sl" ? `Stop-loss ${esc(a.symbol)}`
              : `Sold ${a.frac < 0.999 ? Math.round(a.frac * 100) + "% " : ""}${esc(a.symbol)}`;
  const sub = a.kind === "sell" ? (a.trader && a.lagSec != null ? `same exit as ${esc(a.trader)} · ${a.lagSec}s · ` : "von Hand · ") : "Risk-Agent · ";
  const cost = a.usd - a.pnl;
  return `<li>${icon}<div class="mid"><b>${title}</b><span>${sub}${hm(a.t)}</span></div>
          <div class="amt"><b class="${a.pnl >= 0 ? "pos" : "neg"}">${signed(a.pnl)}</b><span>${cost > 0 ? pct(a.pnl / cost) : ""} · ${big(a.mc)} MC</span></div></li>`;
}

let shownTop = "";
function renderActivity() {
  const list = acc.activity;
  const home = list.slice(0, 8).map(actRow).join("") || `<li class="empty">Noch nichts. Trader hinzufügen und Bot starten.</li>`;
  const top = list[0] ? list[0].t + list[0].kind : "";
  $("actHome").innerHTML = home;
  if (top && top !== shownTop && shownTop) $("actHome").firstElementChild?.classList.add("new");
  shownTop = top;
  const f = { all: () => true, copy: a => a.kind === "copy", exit: a => ["sell", "tp", "sl"].includes(a.kind), rule: a => a.kind === "rule" }[filter];
  const all = list.filter(f);
  $("actAll").innerHTML = all.slice(0, 200).map(actRow).join("") || `<li class="empty">Keine Einträge.</li>`;
  const s = stats(acc);
  $("actInfo").textContent = `${s.copies} copies · ${s.closed} exits`;
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
  $("sBehind").textContent = `${P.delaySec}s · ${P.sameExits ? "same exits" : "nur TP/SL"}`;
  $("sCash").textContent = money(acc.cash);
  $("sFees").textContent = money(acc.fees);
  $("depLbl").textContent = money(P.deposit).replace(".00", "");
  const per = {};
  for (const c of acc.closed) { const x = per[c.trader] || (per[c.trader] = { n: 0, w: 0, pnl: 0 }); x.n++; x.pnl += c.pnl; if (c.pnl > 0) x.w++; }
  $("perTrader").innerHTML = Object.entries(per).sort((a, b) => b[1].pnl - a[1].pnl).map(([name, x]) =>
    `<li>${avatar(name)}<div class="mid"><b>${esc(name)}</b><span>${x.n} Trades · ${x.w}W ${x.n - x.w}L</span></div>
     <div class="amt"><b class="${x.pnl >= 0 ? "pos" : "neg"}">${signed(x.pnl)}</b></div></li>`).join("") || `<li class="empty">Noch keine abgeschlossenen Trades.</li>`;
  $("openPos").innerHTML = Object.values(acc.pos).map(p => {
    const q = prices[p.mint], m = q ? q.price / p.entry : 1;
    return `<li>${avatar(p.symbol, q && q.img)}<div class="mid"><b>${esc(p.symbol)} · ${xs(m)}</b><span>von ${esc(p.trader)} · seit ${hm(p.at)} · Einsatz ${money(p.book.cost)}</span></div>
      <div class="amt"><button class="link tiny" data-sell="${esc(p.mint)}">Verkaufen</button></div></li>`;
  }).join("") || `<li class="empty">Keine offenen Positionen.</li>`;
}

function renderTraders() {
  $("traderList").innerHTML = traders.map((t, i) => `<li>${avatar(t.name)}<div class="mid"><b>${esc(t.name)}</b><code>${esc(t.wallet)}</code></div>
    <button data-tog="${i}">${t.on ? "An" : "Aus"}</button><button data-del="${i}">✕</button></li>`).join("")
    || `<li class="muted tiny" style="display:block">Noch keine Trader. Wallet-Adresse unten eintragen.</li>`;
}

const RULES = [
  ["deposit", "Startgeld ($)", 1], ["stake", "Einsatz pro Kauf ($)", 1], ["delaySec", "Sekunden nach dem Trader", 1],
  ["takeProfitX", "Gewinn mitnehmen bei (x)", 1], ["stopLoss", "Stop-Loss (%, 0 = aus)", 100], ["maxOpen", "Max. offene Positionen", 1],
];
function renderRules() {
  $("rules").innerHTML = RULES.map(([k, label, f]) => `<label for="r_${k}">${label}</label><input id="r_${k}" data-k="${k}" data-f="${f}" type="number" min="0" step="any" value="${+(P[k] * f).toFixed(4)}">`).join("")
    + `<label for="r_same">Mit dem Trader verkaufen</label><input id="r_same" type="checkbox" ${P.sameExits ? "checked" : ""} style="width:auto;justify-self:end">`;
}

function render() { if (!acc) return; renderTop(); renderGrid(); renderActivity(); renderAccount(); }

function toast(text, bad = false) {
  const el = $("toast");
  el.textContent = text; el.className = "toast show" + (bad ? " bad" : "");
  if (!bad) document.body.classList.add("won");
  setTimeout(() => { el.className = "toast" + (bad ? " bad" : ""); document.body.classList.remove("won"); }, 2600);
}

function setRunning(on) {
  running = on; save("copyRunning", on);
  $("runBtn").textContent = on ? "■ Bot stoppen" : "▶ Bot starten";
  $("runBtn").classList.toggle("on", on);
  $("live").textContent = on ? "● PAPER LIVE" : "● PAPER";
  $("live").classList.toggle("live", on);
  if (on) for (const k of Object.keys(cursor)) delete cursor[k];   // after a pause, only new trades are copied
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
  if (!running && !traders.some(t => t.on && B58.test(t.wallet))) { go("agents"); $("tMsg").textContent = "Füge zuerst einen Trader mit Wallet hinzu."; return; }
  setRunning(!running);
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
  else if (el.dataset.k) { const v = Number(el.value); if (v >= 0) P[el.dataset.k] = v / Number(el.dataset.f); }
  save("copyRules", P); render();
});
$("rulesReset").addEventListener("click", () => { P = { ...COPY_DEFAULTS }; save("copyRules", P); renderRules(); render(); });
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
  if (!confirm(`Konto zurücksetzen? Alle Positionen und die Activity werden gelöscht, du startest mit ${money(P.deposit)} Spielgeld.`)) return;
  acc = newAccount(P); queue = []; persist(); render();
});

// ---------- start ----------
(async () => {
  try { $("ver").textContent = "v" + chrome.runtime.getManifest().version; } catch { $("ver").textContent = "web"; }
  P = { ...COPY_DEFAULTS, ...(await load("copyRules", {})) };
  traders = await load("copyTraders", []);
  acc = await load("copyAcc", null) || newAccount(P);
  queue = await load("copyQueue", []);
  range = await load("copyRange", "live");
  for (const x of $("ranges").children) x.classList.toggle("on", x.dataset.r === range);
  renderRules(); renderTraders();
  const open = Object.keys(acc.pos);
  if (open.length) priceCoins(open).then(render).catch(() => {});
  setRunning(!!(await load("copyRunning", false)));
})();
