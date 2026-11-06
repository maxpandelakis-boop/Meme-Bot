// Side panel of the Trencher: live data for one coin plus the paper account. Fake money only.
import {
  START_CASH, FILL_DELAY_MS, newBook, buy, sell, equity, liquidationValue, breakEvenMove,
  findMints, bestPair, parsePumpTrade, parseGeckoTrade,
} from "./sim.js";

const $ = id => document.getElementById(id);
const DEX = mint => `https://api.dexscreener.com/latest/dex/tokens/${mint}`;
const GT = pool => `https://api.geckoterminal.com/api/v2/networks/solana/pools/${pool}/trades`;
const PUMP_WS = "wss://pumpportal.fun/api/data";
const PRICE_EVERY_MS = 1000;      // DexScreener allows 300 requests a minute; one a second stays far below
const GT_EVERY_MS = 3000;         // GeckoTerminal allows about 30 a minute
const WS_QUIET_MS = 12000;        // no PumpPortal trade this long: also poll GeckoTerminal for the trade feed
const FEED_MAX = 80, HIST_MS = 5 * 60 * 1000;

let S = null;                     // the loaded coin's live state
let busy = false;

function fresh(mint) {
  return { mint, pair: null, price: 0, liq: 0, solUsd: 0, hist: [], feed: [], seen: new Set(),
           ws: null, wsLast: 0, wsOk: false, timers: [], book: newBook(), lastPriceAt: 0, gtOn: false };
}

const usd = (x, d = 2) => (x < 0 ? "-" : "") + "$" + Math.abs(x).toFixed(d);
const sig = x => (x >= 0 ? "+" : "") + x.toFixed(2);
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
const status = (t, cls = "muted") => { $("status").textContent = t; $("status").className = cls; };

// ---------- storage ----------
async function loadBook(mint) {
  const k = "book:" + mint;
  const r = await chrome.storage.local.get(k);
  return r[k] || newBook();
}
function saveBook() { if (S) chrome.storage.local.set({ ["book:" + S.mint]: S.book, last: S.mint }); }

// ---------- coin detection on the open tab ----------
let pageMint = null;
async function detect() {
  let tab;
  try { [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }); } catch { return; }
  if (!tab || !tab.url) return;
  let mints = findMints(decodeURIComponent(tab.url));
  if (!mints.length && /fomo\.family/.test(tab.url)) {
    // FOMO's coin pages may not carry the address in the URL: read the links and text of the page.
    try {
      const [res] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => [...document.querySelectorAll("a[href]")].map(a => a.href).join(" ") + " " + document.body.innerText.slice(0, 20000),
      });
      mints = findMints(res && res.result);
    } catch { /* page not scriptable */ }
  }
  pageMint = mints[0] || null;
  $("detected").textContent = pageMint ? "Seite: " + short(pageMint) : "Seite: keine Adresse erkannt";
  if (pageMint && $("follow").checked && (!S || S.mint !== pageMint)) load(pageMint);
}
chrome.tabs.onActivated.addListener(() => setTimeout(detect, 200));
chrome.tabs.onUpdated.addListener((id, info) => { if (info.url || info.status === "complete") setTimeout(detect, 300); });

// ---------- loading a coin ----------
async function load(mint) {
  mint = (mint || "").trim();
  if (!findMints(mint).includes(mint)) { status("Ungültige Adresse", "warn"); return; }
  stop();
  S = fresh(mint);
  $("mint").value = mint;
  S.book = await loadBook(mint);
  $("feed").innerHTML = ""; $("mine").innerHTML = "";
  $("name").textContent = short(mint);
  status("lädt…");
  renderMine(); render();
  pollPrice();
  S.timers.push(setInterval(pollPrice, PRICE_EVERY_MS));
  S.timers.push(setInterval(render, 500));
  S.timers.push(setInterval(checkFeed, 2000));
  openWs();
}

function stop() {
  if (!S) return;
  S.timers.forEach(clearInterval);
  if (S.ws) try { S.ws.close(); } catch {}
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
    if (r.status === 429) { status("DexScreener bremst (429)", "warn"); return; }
    const j = await r.json();
    if (me !== S) return;
    const p = bestPair(j.pairs, me.mint);
    if (!p) { if (!me.price) status("Kein Pool bei DexScreener, warte auf Trades…", "warn"); return; }
    me.pair = p;
    me.liq = (p.liquidity && p.liquidity.usd) || 0;
    const pu = Number(p.priceUsd), pn = Number(p.priceNative);
    if (p.quoteToken && /^W?SOL$/i.test(p.quoteToken.symbol) && pu > 0 && pn > 0) me.solUsd = pu / pn;
    $("name").textContent = (p.baseToken.symbol || short(me.mint)) + " · " + (p.dexId || "");
    // a live trade within the last 2 s is fresher than DexScreener's price
    if (pu > 0 && Date.now() - me.lastPriceAt > 2000) setPrice(pu, Date.now());
    if (status && $("status").textContent.startsWith("lädt")) status("live", "pos");
  } catch (e) {
    if (me === S) status("Preis-Abruf fehlgeschlagen", "warn");
  } finally { priceInFlight = false; }
}

function setPrice(p, t) {
  if (!S || !(p > 0)) return;
  S.price = p; S.lastPriceAt = t;
  S.hist.push({ t, p });
  const cut = Date.now() - HIST_MS;
  while (S.hist.length && S.hist[0].t < cut) S.hist.shift();
}

// ---------- trades: PumpPortal websocket (pump.fun / PumpSwap), else GeckoTerminal ----------
function openWs() {
  const me = S;
  let ws;
  try { ws = new WebSocket(PUMP_WS); } catch { return; }
  me.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ method: "subscribeTokenTrade", keys: [me.mint] }));
  ws.onmessage = ev => {
    if (me !== S) return;
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.mint !== me.mint) return;
    const tr = parsePumpTrade(m, me.solUsd);
    if (!tr) return;
    me.wsLast = Date.now(); me.wsOk = true;
    if (tr.price > 0) setPrice(tr.price, tr.t);
    addTrade(tr);
  };
  ws.onclose = () => { if (me === S) setTimeout(() => { if (me === S) openWs(); }, 3000); };
}

function checkFeed() {
  if (!S) return;
  const quiet = Date.now() - (S.wsLast || 0) > WS_QUIET_MS;
  $("src").textContent = S.wsOk && !quiet ? "Trades: PumpPortal (live)" : S.gtOn ? "Trades: GeckoTerminal (~3 s)" : "Trades: warte…";
  if (quiet && S.pair && !S.gtOn) {
    S.gtOn = true;
    pollGt();
    S.timers.push(setInterval(pollGt, GT_EVERY_MS));
  }
}

async function pollGt() {
  const me = S;
  if (!me || !me.pair) return;
  if (Date.now() - (me.wsLast || 0) < WS_QUIET_MS) return;   // the websocket came back
  try {
    const r = await fetch(GT(me.pair.pairAddress), { headers: { accept: "application/json" } });
    if (!r.ok) return;
    const j = await r.json();
    if (me !== S) return;
    const list = (j.data || []).map(parseGeckoTrade).filter(Boolean).reverse();
    for (const tr of list) addTrade(tr);
  } catch {}
}

function addTrade(tr) {
  const key = tr.sig || tr.t + tr.wallet + tr.usd;
  if (S.seen.has(key)) return;
  S.seen.add(key);
  S.feed.unshift(tr);
  if (S.feed.length > FEED_MAX) S.feed.length = FEED_MAX;
  const li = document.createElement("li");
  li.className = tr.side + " new";
  li.innerHTML = `<span class="s">${tr.side === "buy" ? "KAUF" : "VERK"}</span><span>${tr.usd ? usd(tr.usd) : tr.sol.toFixed(3) + " SOL"}</span>` +
                 `<span class="muted">${short(tr.wallet)}</span><span class="r">${hhmmss(tr.t)}</span>`;
  const ol = $("feed");
  ol.prepend(li);
  while (ol.children.length > FEED_MAX) ol.lastChild.remove();
  $("feedn").textContent = S.seen.size;
}

// ---------- paper orders ----------
async function order(side, share) {
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
  const f = res.fill, moved = me.price / clicked - 1;
  $("order").innerHTML = `${side === "buy" ? "Gekauft" : "Verkauft"} bei ${px(f.fillPrice)} (Klick ${px(clicked)}, ` +
    `Bewegung in 1 s ${pct(moved)}, Slippage ${pct(f.slip)}, Gebühr ${usd(f.fee)})` +
    (f.pnl !== undefined ? ` · <b class="${f.pnl >= 0 ? "pos" : "neg"}">${sig(f.pnl)} $</b>` : "");
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
  const b = S.book;
  $("price").textContent = px(S.price);
  const p = S.pair;
  $("mc").textContent = "MC " + big(p && (p.marketCap || p.fdv));
  $("liq").textContent = "Liq " + big(S.liq) + (S.liq ? "" : " (angenommen $5K)");
  const ch = p && p.priceChange; $("chg").textContent = ch ? `5m ${ch.m5 ?? "–"} % · 1h ${ch.h1 ?? "–"} %` : "–";
  const now = Date.now(), last = S.feed.filter(t => now - t.t < 10000);
  const nb = last.filter(t => t.side === "buy"), ns = last.filter(t => t.side === "sell");
  const sum = a => a.reduce((x, t) => x + (t.usd || 0), 0);
  $("flow").innerHTML = `Käufe/Verkäufe (10 s): <span class="pos">${nb.length} · ${usd(sum(nb), 0)}</span> / <span class="neg">${ns.length} · ${usd(sum(ns), 0)}</span>`;

  const eq = equity(b, S.price, S.liq), pnl = eq - START_CASH;
  $("equity").textContent = usd(eq);
  $("pnl").textContent = `${sig(pnl)} $ (${pct(pnl / START_CASH)})`;
  $("pnl").className = pnl >= 0 ? "pos" : "neg";
  $("cash").textContent = usd(b.cash);
  if (b.tokens > 0) {
    const v = liquidationValue(b, S.price, S.liq), u = v - b.cost;
    $("pos").innerHTML = `${usd(v)} <span class="${u >= 0 ? "pos" : "neg"}">(${pct(u / b.cost)})</span>`;
  } else $("pos").textContent = "–";
  $("fees").textContent = usd(b.fees);
  const sells = b.trades.filter(t => t.side === "sell");
  $("ntr").textContent = `${b.trades.length} (${sells.filter(t => t.pnl > 0).length}/${sells.length})`;
  const be = breakEvenMove(Math.max(b.cash, 1), S.liq);
  $("be").textContent = isFinite(be) ? `Damit ein Rein-und-Raus mit ${usd(Math.max(b.cash, 1))} Gewinn macht, muss der Kurs um ${pct(be)} steigen.`
                                     : "Zu wenig Bargeld: die Mindestgebühr frisst den ganzen Kauf.";
  drawChart();
}

function renderMine() {
  const ol = $("mine"); ol.innerHTML = "";
  if (!S) return;
  for (const t of S.book.trades.slice().reverse().slice(0, 50)) {
    const li = document.createElement("li");
    li.className = t.side;
    li.innerHTML = `<span class="s">${t.side === "buy" ? "KAUF" : "VERK"}</span><span>${usd(t.usd)}</span><span class="muted">${px(t.fillPrice)}</span>` +
      (t.pnl !== undefined ? `<span class="${t.pnl >= 0 ? "pos" : "neg"}">${sig(t.pnl)}</span>` : "") + `<span class="r">${hhmmss(t.t)}</span>`;
    ol.append(li);
  }
}

function drawChart() {
  const c = $("chart"), ctx = c.getContext("2d");
  const w = c.clientWidth * devicePixelRatio, h = c.clientHeight * devicePixelRatio;
  if (c.width !== w) { c.width = w; c.height = h; }
  ctx.clearRect(0, 0, w, h);
  const H = S && S.hist;
  if (!H || H.length < 2) return;
  const t1 = Date.now(), t0 = t1 - HIST_MS;
  let lo = Infinity, hi = -Infinity;
  for (const q of H) { lo = Math.min(lo, q.p); hi = Math.max(hi, q.p); }
  if (hi === lo) { hi *= 1.001; lo *= 0.999; }
  const X = t => ((t - t0) / (t1 - t0)) * w, Y = p => h - 4 - ((p - lo) / (hi - lo)) * (h - 8);
  ctx.lineWidth = 1.5 * devicePixelRatio;
  ctx.strokeStyle = H[H.length - 1].p >= H[0].p ? "#16c784" : "#ea3943";
  ctx.beginPath();
  H.forEach((q, i) => (i ? ctx.lineTo(X(q.t), Y(q.p)) : ctx.moveTo(X(q.t), Y(q.p))));
  ctx.stroke();
  for (const t of S.book.trades) {
    if (t.t < t0) continue;
    ctx.fillStyle = t.side === "buy" ? "#16c784" : "#ea3943";
    ctx.beginPath(); ctx.arc(X(t.t), Y(Math.min(Math.max(t.price, lo), hi)), 4 * devicePixelRatio, 0, 7); ctx.fill();
  }
}

// ---------- wiring ----------
$("go").onclick = () => { $("follow").checked = false; load($("mint").value); };
$("mint").onkeydown = e => { if (e.key === "Enter") $("go").click(); };
$("buyAll").onclick = () => order("buy", 1);
$("buyHalf").onclick = () => order("buy", 0.5);
$("sellAll").onclick = () => order("sell", 1);
$("sellHalf").onclick = () => order("sell", 0.5);
$("reset").onclick = () => { if (S && confirm("Diesen Coin auf 20 $ zurücksetzen?")) { S.book = newBook(); saveBook(); renderMine(); render(); } };
$("follow").onchange = () => { if ($("follow").checked) detect(); };
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "b" || e.key === "B") order("buy", 1);
  if (e.key === "s" || e.key === "S") order("sell", 1);
});

(async () => {
  await detect();
  if (!S) { const { last } = await chrome.storage.local.get("last"); if (last) load(last); }
  render();
})();
