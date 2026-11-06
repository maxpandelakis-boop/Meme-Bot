// Side panel of the Trencher: live data for one coin plus the paper account. Fake money only.
import {
  START_CASH, FILL_DELAY_MS, newBook, buy, sell, equity, liquidationValue, breakEvenMove, avgEntry,
  findMints, bestPair, parseGeckoTrade, buildCandles, decide, BOT_DEFAULTS, tradesFromLogs,
} from "./sim.js";

const $ = id => document.getElementById(id);
const DEX = mint => `https://api.dexscreener.com/latest/dex/tokens/${mint}`;
const GT = pool => `https://api.geckoterminal.com/api/v2/networks/solana/pools/${pool}/trades`;
const PRICE_EVERY_MS = 1000;      // DexScreener allows 300 requests a minute; one a second stays far below
const GT_EVERY_MS = 15000;        // GeckoTerminal caches 30 s and answers 429 after a few fast calls (tested 2026-11-06)
const RPC_WS = "wss://api.mainnet-beta.solana.com";   // live trades: Solana's public RPC, logsSubscribe on the coin
const CHAIN_LIVE_MS = 20000;      // chain events this recent: GeckoTerminal is not polled (it only fills the chart's history)
// PumpPortal only sends per-coin trades to connections with a paid API key (tested 2026-11-06), so it is not used.
const TRADE_FRESH_MS = 8000;      // a trade price this young wins over DexScreener's, which is cached for several seconds
const FEED_MAX = 120, TICK_MAX = 4000;

let S = null;                     // the loaded coin's live state
let busy = false;
let tf = 5;                       // candle seconds
try { tf = Number(localStorage.getItem("tf")) || 5; } catch {}

function fresh(mint) {
  return { mint, pair: null, price: 0, liq: 0, ticks: [], feed: [], seen: new Set(), timers: [],
           book: newBook(), lastTradeAt: 0, gtOn: false, solUsd: 0, ws: null, chainAt: 0, gtBackoff: 0, entryLine: null, lastExitAt: 0, log: [] };
}

// ---------- formatting ----------
const usd = (x, d = 2) => (x < 0 ? "-" : "") + "$" + Math.abs(x).toFixed(d);
const sig = x => (x >= 0 ? "+" : "-") + "$" + Math.abs(x).toFixed(2);
const pct = x => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + " %";
function px(p) {
  if (!(p > 0)) return "–";
  if (p >= 1) return "$" + p.toFixed(4);
  const z = Math.floor(-Math.log10(p));
  return "$" + p.toFixed(Math.min(z + 4, 14));
}
const big = x => !(x > 0) ? "–" : x >= 1e6 ? "$" + (x / 1e6).toFixed(2) + "M" : x >= 1e3 ? "$" + (x / 1e3).toFixed(1) + "K" : "$" + x.toFixed(0);
const hhmmss = t => new Date(t).toLocaleTimeString("de-DE");
const short = w => w ? w.slice(0, 4) + "…" + w.slice(-3) : "";
const status = (t, cls = "muted") => { $("status").textContent = t; $("status").className = "dot " + cls; };
const cls = x => (x >= 0 ? "pos" : "neg");

// ---------- chart (TradingView Lightweight Charts, bundled in lib/) ----------
const LWC = window.LightweightCharts;
const chart = LWC.createChart($("chart"), {
  autoSize: true,
  layout: { background: { color: "#141821" }, textColor: "#8b93a3", fontSize: 10 },
  grid: { vertLines: { color: "#1c2130" }, horzLines: { color: "#1c2130" } },
  rightPriceScale: { borderColor: "#232836", scaleMargins: { top: 0.12, bottom: 0.22 } },
  timeScale: { borderColor: "#232836", timeVisible: true, secondsVisible: true, rightOffset: 4, barSpacing: 7,
               tickMarkFormatter: t => new Date(t * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: tf < 60 ? "2-digit" : undefined }) },
  localization: { locale: "de-DE", timeFormatter: t => new Date(t * 1000).toLocaleTimeString("de-DE"), priceFormatter: px },
  crosshair: { mode: 0 },
});
const candles = chart.addCandlestickSeries({
  upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444",
  priceFormat: { type: "custom", formatter: px, minMove: 1e-12 },
});
const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
let fitted = false;

function drawChart() {
  if (!S) { candles.setData([]); volume.setData([]); candles.setMarkers([]); return; }
  const bars = buildCandles(S.ticks, tf);
  candles.setData(bars);
  volume.setData(bars.map(b => ({ time: b.time, value: b.value, color: b.close >= b.open ? "rgba(34,197,94,.35)" : "rgba(239,68,68,.35)" })));
  // my paper trades as markers, each on the bar it happened in (or the last bar before it)
  const times = bars.map(b => b.time);
  const snap = t => { const s = Math.floor(t / 1000 / tf) * tf; let lo = null; for (const x of times) { if (x <= s) lo = x; else break; } return lo; };
  const marks = [];
  for (const f of S.book.trades) {
    const time = snap(f.t);
    if (time === null) continue;
    marks.push(f.side === "buy"
      ? { time, position: "belowBar", color: "#22c55e", shape: "arrowUp", text: "K " + usd(f.usd, 0) }
      : { time, position: "aboveBar", color: f.pnl >= 0 ? "#22c55e" : "#ef4444", shape: "arrowDown", text: "V " + sig(f.pnl) });
    if (f.bot) marks[marks.length - 1].text = "🤖 " + marks[marks.length - 1].text;
  }
  marks.sort((a, b) => a.time - b.time);
  candles.setMarkers(marks);
  // my average entry as a dashed line while I hold the coin
  const e = avgEntry(S.book);
  if (e > 0 && !S.entryLine) S.entryLine = candles.createPriceLine({ price: e, color: "#f5b70a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Einstieg" });
  else if (e > 0) S.entryLine.applyOptions({ price: e });
  else if (S.entryLine) { candles.removePriceLine(S.entryLine); S.entryLine = null; }
  if (!fitted && bars.length > 3) { chart.timeScale().scrollToRealTime(); fitted = true; }
}

for (const b of document.querySelectorAll("#tf button")) {
  b.classList.toggle("on", Number(b.dataset.s) === tf);
  b.onclick = () => {
    tf = Number(b.dataset.s);
    try { localStorage.setItem("tf", tf); } catch {}
    document.querySelectorAll("#tf button").forEach(x => x.classList.toggle("on", x === b));
    chart.applyOptions({ timeScale: { secondsVisible: tf < 60 } });
    fitted = false; drawChart();
  };
}

// ---------- storage ----------
async function loadBook(mint) {
  const k = "book:" + mint;
  const r = await chrome.storage.local.get(k);
  return r[k] || newBook();
}
function saveBook() { if (S) chrome.storage.local.set({ ["book:" + S.mint]: S.book, last: S.mint }); }

// ---------- coin detection on the open tab ----------
async function detect() {
  let tab;
  try { [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }); } catch { return; }
  if (!tab || !tab.url) return;
  let mints = findMints(decodeURIComponent(tab.url));
  if (!mints.length && /fomo\.family/.test(tab.url)) {
    try {
      const [res] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => [...document.querySelectorAll("a[href]")].map(a => a.href).join(" ") + " " + document.body.innerText.slice(0, 20000),
      });
      mints = findMints(res && res.result);
    } catch { /* page not scriptable */ }
  }
  const m = mints[0] || null;
  $("detected").textContent = m ? "Seite: " + short(m) : "Seite: keine Adresse erkannt";
  if (m && $("follow").checked && (!S || S.mint !== m)) load(m);
}
chrome.tabs.onActivated.addListener(() => setTimeout(detect, 200));
chrome.tabs.onUpdated.addListener((id, info) => { if (info.url || info.status === "complete") setTimeout(detect, 300); });

// ---------- loading a coin ----------
async function load(mint) {
  mint = (mint || "").trim();
  if (!findMints(mint).includes(mint)) { status("Ungültige Adresse", "warn"); return; }
  stop();
  botOff("Neuer Coin: Bot gestoppt");
  S = fresh(mint);
  $("mint").value = mint;
  S.book = await loadBook(mint);
  $("feed").innerHTML = "";
  $("name").textContent = short(mint); $("sub").textContent = "–";
  fitted = false;
  status("lädt…", "warn");
  renderMine(); render();
  pollPrice();
  S.timers.push(setInterval(pollPrice, PRICE_EVERY_MS));
  S.timers.push(setInterval(render, 500));
}

function stop() {
  if (!S) return;
  S.timers.forEach(clearInterval);
  if (S.ws) { S.ws.onclose = null; try { S.ws.close(); } catch {} }
  if (S.entryLine) candles.removePriceLine(S.entryLine);
  S = null;
}

// ---------- price: DexScreener every second ----------
let priceInFlight = false;
async function pollPrice() {
  if (!S || priceInFlight) return;
  priceInFlight = true;
  const me = S;
  try {
    const r = await fetch(DEX(me.mint), { cache: "no-store" });
    if (r.status === 429) { status("DexScreener bremst", "warn"); return; }
    const j = await r.json();
    if (me !== S) return;
    const p = bestPair(j.pairs, me.mint);
    if (!p) { if (!me.price) status("Kein Pool gefunden", "warn"); return; }
    me.pair = p;
    me.liq = (p.liquidity && p.liquidity.usd) || 0;
    $("name").textContent = p.baseToken.symbol || short(me.mint);
    const pu = Number(p.priceUsd), pn = Number(p.priceNative);
    if (p.quoteToken && /^W?SOL$/i.test(p.quoteToken.symbol) && pu > 0 && pn > 0) me.solUsd = pu / pn;
    if (!me.ws && me.solUsd) openChain(me);
    if (pu > 0 && Date.now() - me.lastTradeAt > TRADE_FRESH_MS) { me.price = pu; addTick(Date.now(), pu, 0); }
    status("live", "pos");
    if (!me.gtOn) { me.gtOn = true; pollGt(); me.timers.push(setInterval(pollGt, GT_EVERY_MS)); }
  } catch {
    if (me === S) status("Preis-Abruf fehlgeschlagen", "warn");
  } finally { priceInFlight = false; }
}

function addTick(t, p, v) {
  S.ticks.push({ t, p, v });
  if (S.ticks.length > TICK_MAX) S.ticks.splice(0, S.ticks.length - TICK_MAX);
}

// ---------- trades: GeckoTerminal every 2.5 s (its last 300 trades also fill the chart's history at once) ----------
function openChain(me) {
  let ws;
  try { ws = new WebSocket(RPC_WS); } catch { return; }
  me.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "logsSubscribe", params: [{ mentions: [me.mint] }, { commitment: "confirmed" }] }));
  ws.onmessage = ev => {
    if (me !== S) return;
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    const val = m.params && m.params.result && m.params.result.value;
    if (!val || val.err) return;
    const list = tradesFromLogs(val.logs, me.mint, me.pair && me.pair.pairAddress, me.solUsd, val.signature);
    if (!list.length) return;
    me.chainAt = Date.now();
    for (const tr of list) addTrade(tr);
    const last = list[list.length - 1];
    if (last.price > 0) { me.price = last.price; me.lastTradeAt = last.t; }
    $("src").textContent = "Trades: live von Solana · " + hhmmss(Date.now());
  };
  ws.onclose = () => { if (me === S) { me.ws = null; setTimeout(() => { if (me === S && !me.ws) openChain(me); }, 3000); } };
}

async function pollGt() {
  const me = S;
  if (!me || !me.pair) return;
  if (me.feed.length && Date.now() - me.chainAt < CHAIN_LIVE_MS) return;   // live from the chain: no need
  if (Date.now() < me.gtBackoff) return;
  try {
    const r = await fetch(GT(me.pair.pairAddress), { headers: { accept: "application/json" } });
    if (r.status === 429) { me.gtBackoff = Date.now() + 60000; return; }
    if (!r.ok) return;
    const j = await r.json();
    if (me !== S) return;
    const list = (j.data || []).map(parseGeckoTrade).filter(Boolean).sort((a, b) => a.t - b.t);
    let fresh = 0;
    for (const tr of list) if (addTrade(tr)) fresh++;
    const last = list[list.length - 1];
    if (last && last.price > 0 && last.t >= me.lastTradeAt) { me.lastTradeAt = Math.max(last.t, me.lastTradeAt); me.price = last.price; }
    if (fresh && Date.now() - me.chainAt > CHAIN_LIVE_MS) $("src").textContent = "Trades: GeckoTerminal (bis 30 s alt)";
  } catch {}
}

function addTrade(tr) {
  const key = tr.sig ? tr.sig + tr.side + tr.usd : tr.t + tr.wallet + tr.usd;
  if (S.seen.has(key)) return false;
  S.seen.add(key);
  if (tr.price > 0) addTick(tr.t, tr.price, tr.usd);
  S.feed.unshift(tr);
  S.feed.sort((a, b) => b.t - a.t);
  if (S.feed.length > FEED_MAX) S.feed.length = FEED_MAX;
  const li = document.createElement("li");
  li.className = tr.side + " new";
  li.innerHTML = `<span class="s">${tr.side === "buy" ? "KAUF" : "VERK"}</span><span>${usd(tr.usd)}</span>` +
                 `<span class="muted">${short(tr.wallet)}</span><span class="r">${hhmmss(tr.t)}</span>`;
  const ol = $("feed");
  ol.prepend(li);
  while (ol.children.length > FEED_MAX) ol.lastChild.remove();
  $("feedn").textContent = S.seen.size;
  return true;
}

// ---------- paper orders ----------
async function order(side, share, why = "", bot = false) {
  if (!S || busy) return;
  if (!(S.price > 0)) { $("order").textContent = "Noch kein Preis."; return; }
  busy = true; setButtons();
  const me = S, clicked = S.price;
  $("order").textContent = `Order läuft… (Klickpreis ${px(clicked)})`;
  await new Promise(r => setTimeout(r, FILL_DELAY_MS));
  if (me !== S) { busy = false; return; }
  const res = side === "buy" ? buy(me.book, me.book.cash * share, me.price, me.liq) : sell(me.book, share, me.price, me.liq);
  busy = false;
  if (res.error) { $("order").textContent = res.error; setButtons(); return; }
  me.book = res.book; saveBook();
  res.fill.why = why; res.fill.bot = bot;
  if (side === "sell" && !(me.book.tokens > 0)) me.lastExitAt = Date.now();
  logLine(side, (bot ? "" : "Hand: ") + (why || (side === "buy" ? "gekauft" : "verkauft")) + ` · ${usd(res.fill.usd)}` + (res.fill.pnl !== undefined ? ` · ${sig(res.fill.pnl)}` : ""));
  const f = res.fill, moved = me.price / clicked - 1;
  $("order").innerHTML = `<b class="${side === "buy" ? "pos" : "neg"}">${side === "buy" ? "Gekauft" : "Verkauft"}</b> ${usd(f.usd)} bei ${px(f.fillPrice)} · ` +
    `Kurs in 1 s ${pct(moved)} · Slippage ${pct(f.slip)} · Gebühr ${usd(f.fee)}` +
    (f.pnl !== undefined ? ` · <b class="${cls(f.pnl)}">${sig(f.pnl)}</b>` : "");
  renderMine(); render();
}

function setButtons() {
  const has = S && S.price > 0;
  $("buyAll").disabled = $("buyHalf").disabled = busy || !has || !(S.book.cash > 1);
  $("sellAll").disabled = $("sellHalf").disabled = busy || !has || !(S.book.tokens > 0);
}

// ---------- rendering ----------
function render() {
  setButtons();
  if (!S) return;
  const b = S.book, p = S.pair;
  if (b.tokens > 0 && S.price > (b.peak || 0)) b.peak = S.price;
  $("price").textContent = px(S.price);
  $("sub").textContent = `MC ${big(p && (p.marketCap || p.fdv))} · Liq ${big(S.liq)}${S.liq ? "" : " (angen. $5K)"}${p ? " · " + p.dexId : ""}`;
  const ch = p && p.priceChange;
  $("chg").innerHTML = ch ? `<span class="${cls(ch.m5 || 0)}">5m ${ch.m5 ?? "–"} %</span> · <span class="${cls(ch.h1 || 0)}">1h ${ch.h1 ?? "–"} %</span>` : "–";

  const now = Date.now(), last = S.feed.filter(t => now - t.t < 30000);
  const vb = last.filter(t => t.side === "buy").reduce((x, t) => x + t.usd, 0);
  const vs = last.filter(t => t.side === "sell").reduce((x, t) => x + t.usd, 0);
  $("flowB").style.width = (vb + vs ? (100 * vb) / (vb + vs) : 50) + "%";
  $("flow").innerHTML = `30 s: <span class="pos">Käufe ${usd(vb, 0)}</span> / <span class="neg">Verkäufe ${usd(vs, 0)}</span>`;

  const eq = equity(b, S.price, S.liq), pnl = eq - START_CASH;
  $("equity").textContent = usd(eq);
  $("pnl").innerHTML = `${sig(pnl)} <span class="tiny">${pct(pnl / START_CASH)}</span>`;
  $("pnl").className = "big " + cls(pnl);
  if (b.tokens > 0) {
    const v = liquidationValue(b, S.price, S.liq), u = v - b.cost;
    $("posline").innerHTML = `Im Coin: <b>${usd(v)}</b> <b class="${cls(u)}">${pct(u / b.cost)}</b> · Einstieg ${px(avgEntry(b))}`;
  } else $("posline").textContent = "Keine Position";
  $("cash").textContent = usd(b.cash);
  $("fees").textContent = usd(b.fees);
  const sells = b.trades.filter(t => t.side === "sell");
  $("ntr").textContent = b.trades.length;
  $("wins").textContent = sells.length ? `${sells.filter(t => t.pnl > 0).length}/${sells.length}` : "–";
  const amt = b.tokens > 0 ? b.cost : Math.max(b.cash, 1);
  const be = breakEvenMove(amt, S.liq);
  $("be").textContent = isFinite(be) ? `Gewinnschwelle: Der Kurs muss um ${pct(be)} steigen, damit ein Rein-und-Raus mit ${usd(amt)} etwas bringt.`
                                     : "Zu wenig Bargeld: die Mindestgebühr frisst den ganzen Kauf.";
  drawChart();
}

function renderMine() {
  const ol = $("mine"); ol.innerHTML = "";
  if (!S) return;
  if (!S.book.trades.length) { ol.innerHTML = `<li class="empty">Noch keine Trades auf diesem Coin.</li>`; return; }
  for (const t of S.book.trades.slice().reverse().slice(0, 60)) {
    const li = document.createElement("li");
    li.className = t.side;
    li.innerHTML = `<span class="s">${t.side === "buy" ? "KAUF" : "VERK"}</span><span>${usd(t.usd)}</span>` +
      `<span>${t.pnl !== undefined ? `<b class="${cls(t.pnl)}">${sig(t.pnl)}</b>` : `<span class="muted">${px(t.fillPrice)}</span>`}</span><span class="r">${hhmmss(t.t)}</span>`;
    ol.append(li);
  }
}

// ---------- wiring ----------
$("go").onclick = () => { $("follow").checked = false; load($("mint").value); };
$("mint").onkeydown = e => { if (e.key === "Enter") $("go").click(); };
$("buyAll").onclick = () => order("buy", 1);
$("botBtn").onclick = () => (botOn ? botOff("Von dir gestoppt") : botStart());
$("rulesReset").onclick = () => { P = { ...BOT_DEFAULTS }; saveRules(); buildRuleForm(); };
$("buyHalf").onclick = () => order("buy", 0.5);
$("sellAll").onclick = () => order("sell", 1);
$("sellHalf").onclick = () => order("sell", 0.5);
$("reset").onclick = () => { if (S && confirm("Diesen Coin auf 20 $ zurücksetzen?")) { S.book = newBook(); saveBook(); renderMine(); render(); } };
$("follow").onchange = () => { if ($("follow").checked) detect(); };
for (const t of document.querySelectorAll(".tabs [data-tab]")) {
  t.onclick = () => {
    document.querySelectorAll(".tabs [data-tab]").forEach(x => x.classList.toggle("on", x === t));
    $("mine").classList.toggle("hidden", t.dataset.tab !== "mine");
    $("feed").classList.toggle("hidden", t.dataset.tab !== "feed");
    $("log").classList.toggle("hidden", t.dataset.tab !== "log");
  };
}
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "b" || e.key === "B") order("buy", 1);
  if (e.key === "s" || e.key === "S") order("sell", 1);
});

// ---------- the auto bot ----------
let botOn = false, botTimer = null;
let P = { ...BOT_DEFAULTS };
const RULES = [   // [key, label, shown as percent?]
  ["minBuyShare", "Einstieg: Anteil Käufe mind. (%)", true], ["minVolUsd", "Einstieg: Volumen mind. ($)", false],
  ["minMove", "Einstieg: Kursanstieg mind. (%)", true], ["maxMove", "Einstieg: Kursanstieg höchstens (%)", true],
  ["flowSec", "Einstieg: Zeitfenster (s)", false], ["minLiq", "Liquidität mind. ($)", false],
  ["takeProfit", "Verkauf: Gewinnziel netto (%)", true], ["stopLoss", "Verkauf: Stop-Loss netto (%)", true],
  ["trail", "Verkauf: Rückgang vom Hoch (%)", true], ["flipShare", "Verkauf: Verkaufsdruck 10 s (%)", true],
  ["maxHoldSec", "Verkauf: max. Haltezeit (s)", false], ["cooldownSec", "Pause nach Verkauf (s)", false],
];
function buildRuleForm() {
  const box = $("ruleForm"); box.innerHTML = "";
  for (const [k, label, isPct] of RULES) {
    const l = document.createElement("label"); l.textContent = label;
    const i = document.createElement("input"); i.type = "number"; i.step = "any";
    i.value = isPct ? +(P[k] * 100).toFixed(2) : P[k];
    i.onchange = () => { const v = Number(i.value); if (isFinite(v) && v >= 0) { P[k] = isPct ? v / 100 : v; saveRules(); } };
    box.append(l, i);
  }
}
function saveRules() { chrome.storage.local.set({ botRules2: P }); }
chrome.storage.local.get("botRules2").then(r => { if (r.botRules2) P = { ...BOT_DEFAULTS, ...r.botRules2 }; buildRuleForm(); });

function logLine(side, text) {
  if (!S) return;
  const li = document.createElement("li");
  li.className = side + " new";
  li.innerHTML = `<span class="s">${side === "buy" ? "KAUF" : side === "sell" ? "VERK" : "BOT"}</span><span>${text}</span><span class="r">${hhmmss(Date.now())}</span>`;
  $("log").prepend(li);
  while ($("log").children.length > 200) $("log").lastChild.remove();
}

function botStart() {
  if (!S || !(S.price > 0)) { $("botWhy").textContent = "Erst einen Coin laden."; return; }
  botOn = true;
  $("botBtn").textContent = "■ Bot stoppen"; $("botBtn").classList.add("on");
  $("botState").innerHTML = `<b class="pos pulse">Bot läuft</b> auf ${$("name").textContent}`;
  logLine("bot", "Bot gestartet");
  botTimer = setInterval(botTick, 1000);
  botTick();
}
function botOff(why) {
  if (!botOn) return;
  botOn = false; clearInterval(botTimer);
  $("botBtn").textContent = "▶ Bot starten"; $("botBtn").classList.remove("on");
  $("botState").innerHTML = "<b>Bot aus</b>";
  $("botWhy").textContent = why;
  logLine("bot", why);
}
function botTick() {
  if (!botOn || !S || busy) return;
  const d = decide({ now: Date.now(), price: S.price, liq: S.liq, trades: S.feed, book: S.book, lastExitAt: S.lastExitAt }, P);
  $("botWhy").textContent = d.why;
  if (d.action === "buy") order("buy", 1, d.why, true);
  else if (d.action === "sell") order("sell", 1, d.why, true);
  else if (d.why === "kein Bargeld mehr") botOff("Kein Bargeld mehr: Bot gestoppt");
}

(async () => {
  await detect();
  if (!S) { const { last } = await chrome.storage.local.get("last"); if (last) load(last); }
  render();
})();
