// Echtgeld page: the switch (AUS / Probelauf / ECHTGELD), the bot wallet and the hard limits.
// It watches the paper desk's account (chrome.storage "deskAcc") and mirrors each new buy/sell with real money, inside the limits.
// It never runs on the web version (raw.githack.com is shared by every repo there, so a stored key would not be private).
import { newWallet, encryptWallet, decryptWallet, unlockFromSeed, signTx, backupString } from "./live-wallet.js";
import { LIVE_DEFAULTS, SOL, planMirror, solBalance, tokenBalance, quote, swapTx, solUsd as getSolUsd, simulate, send, confirm as confirmTx, rpc } from "./live-trade.js";

const $ = id => document.getElementById(id);
const isExt = location.protocol === "chrome-extension:" && typeof chrome !== "undefined" && chrome.storage && chrome.storage.local;
const get = async (k, d) => { const v = (await chrome.storage.local.get(k))[k]; return v === undefined ? d : v; };
const put = (k, v) => chrome.storage.local.set({ [k]: v });
const today = () => new Date().toISOString().slice(0, 10);

let box = null;            // encrypted wallet {address, salt, iv, ct}
let wallet = null;         // unlocked: {address, sign}, memory only
let mode = "off";          // never stored: every reload starts at AUS
let S = { ...LIVE_DEFAULTS };
let state = { seenT: 0, held: {}, day: today(), tradesToday: 0 };
let logLines = [];
let solUsd = 0, walletUsd = 0;
let chain = Promise.resolve();   // one swap at a time
let probeHeld = {};        // coins the Probelauf pretends to hold, so its sells get tested too

function log(text, cls = "") {
  logLines.unshift({ t: Date.now(), text, cls }); logLines.length = Math.min(logLines.length, 200);
  put("liveLog", logLines); renderLog();
}
function renderLog() {
  $("log").innerHTML = logLines.length ? logLines.map(l => `<div class="${l.cls}"><span class="muted">${new Date(l.t).toLocaleTimeString("de-DE")}</span> ${l.text}</div>`).join("") : '<div class="muted">noch nichts</div>';
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const scan = sig => `<a class="link" target="_blank" href="https://solscan.io/tx/${sig}">Solscan</a>`;

function renderWallet() {
  $("noWallet").style.display = box ? "none" : "";
  $("hasWallet").style.display = box ? "" : "none";
  if (box) $("addr").textContent = box.address;
  $("lockState").textContent = wallet ? "✅ Entsperrt (nur bis die Seite neu lädt)." : "Gesperrt. Nach jedem Neuladen der Seite ist die Wallet wieder gesperrt.";
  $("lockState").className = "tiny " + (wallet ? "pos" : "muted");
}
function renderMode() {
  document.querySelectorAll(".modes button").forEach(b => b.classList.toggle("on", b.dataset.m === mode));
  const pill = $("modePill");
  pill.textContent = { off: "● AUS", probe: "● PROBELAUF", live: "● ECHTGELD AN" }[mode];
  pill.style.color = { off: "", probe: "var(--gold)", live: "var(--dn)" }[mode];
  document.title = mode === "live" ? "🔴 ECHTGELD AN" : "Trencher Echtgeld";
}
function renderSettings() {
  $("maxTradeUsd").value = S.maxTradeUsd; $("floorUsd").value = S.floorUsd; $("maxTradesDay").value = S.maxTradesDay; $("slip").value = S.slippageBps / 100;
}

async function refresh() {
  if (!box) return;
  try {
    solUsd = await getSolUsd(S.jupKey);
    const sol = await solBalance(box.address);
    let tokUsd = 0; const parts = [];
    for (const mint of Object.keys(state.held)) {
      const tb = await tokenBalance(box.address, mint);
      if (tb.raw === "0") continue;
      try { const q = await quote(mint, SOL, tb.raw, S.slippageBps, S.jupKey); const u = Number(q.outAmount) / 1e9 * solUsd; tokUsd += u; parts.push(`${mint.slice(0, 4)}… ${u.toFixed(2)} $`); } catch {}
    }
    walletUsd = sol * solUsd + tokUsd;
    $("usd").textContent = walletUsd.toFixed(2) + " $";
    $("bal2").textContent = `${sol.toFixed(4)} SOL (1 SOL = ${solUsd.toFixed(2)} $)` + (parts.length ? " · Coins: " + parts.join(", ") : "");
    if (mode === "live" && walletUsd < S.floorUsd) $("bal2").textContent += ` · unter ${S.floorUsd} $: keine neuen Käufe`;
  } catch (e) { $("bal2").textContent = "Kontostand nicht lesbar: " + e.message; }
}

// ---------- one swap ----------
// real: send it (else only simulate). force: the Not-Aus sells while the switch is already AUS.
async function swap(a, real, force = false) {
  const tag = real ? "ECHT" : "Probe";
  let q;
  if (a.type === "buy") {
    const lamports = Math.floor(a.usd / solUsd * 1e9);
    q = await quote(SOL, a.mint, lamports, S.slippageBps, S.jupKey);
  } else {
    const tb = await tokenBalance(box.address, a.mint);
    if (tb.raw === "0") { if (!real) log(`${tag}: Verkauf ${esc(a.symbol || a.mint.slice(0, 6))} (${Math.round(a.frac * 100)} %) übersprungen, die Wallet hält keine echten Token.`, "muted"); if (a.frac >= 1) delete state.held[a.mint]; return; }
    const raw = a.frac >= 1 ? BigInt(tb.raw) : BigInt(tb.raw) * BigInt(Math.round(a.frac * 1e6)) / 1000000n;
    q = await quote(a.mint, SOL, raw.toString(), S.slippageBps, S.jupKey);
  }
  const tx = await swapTx(q, box.address, S, S.jupKey);
  const what = a.type === "buy" ? `Kauf ${esc(a.symbol || a.mint.slice(0, 6))} für ${a.usd.toFixed(2)} $` : `Verkauf ${esc(a.symbol || a.mint.slice(0, 6))} ${Math.round(a.frac * 100)} % (${a.why})`;
  if (!real) {
    const sim = await simulate(tx);
    log(`Probe: ${what}: ${sim.ok ? "würde klappen" : "würde scheitern: " + esc(JSON.stringify(sim.err))}`, sim.ok ? "" : "neg");
    return;
  }
  if ((!force && mode !== "live") || !wallet) throw new Error("Schalter nicht mehr auf ECHTGELD");
  const sig = await send(await signTx(tx, wallet));
  log(`ECHT: ${what} gesendet … ${scan(sig)}`);
  await confirmTx(sig);
  log(`ECHT: ${what} ✅ bestätigt ${scan(sig)}`, "pos");
}

async function mirror(acc) {
  if (mode === "off" || !acc || !box) return;
  if (state.day !== today()) { state.day = today(); state.tradesToday = 0; }
  const real = mode === "live";
  const plan = planMirror(acc.activity, real ? state : { ...state, held: probeHeld }, { usd: real ? walletUsd : Math.max(walletUsd, 20), solUsd }, S);
  state.seenT = plan.seenT;
  for (const s of plan.skipped) log(`übersprungen ${esc(s.mint?.slice(0, 6))}: ${esc(s.why)}`, "muted");
  for (const a of plan.actions) {
    try {
      const held = real ? state.held : probeHeld;
      if (a.type === "buy") held[a.mint] = true; else if (a.frac >= 1) delete held[a.mint];
      await swap(a, real);
      if (real) state.tradesToday++;
    } catch (e) {
      if (a.type === "buy" && !/nicht bestätigt/.test(e.message)) delete (real ? state.held : probeHeld)[a.mint];   // nothing bought: may buy it again later
      log(`Fehler bei ${a.type === "buy" ? "Kauf" : "Verkauf"} ${esc(a.symbol || a.mint.slice(0, 6))}: ${esc(e.message)}`, "neg");
    }
  }
  put("liveState", state);
  if (plan.actions.length) refresh();
}

async function setMode(m) {
  if (m === mode) return;
  if (m !== "off" && !box) { alert("Zuerst die Bot-Wallet erstellen."); return; }
  if (m === "live") {
    if (!wallet) { alert("Zuerst die Wallet mit dem Passwort entsperren."); return; }
    await refresh();
    const t = prompt(`ECHTES GELD. Der Bot kauft und verkauft jetzt selbst mit dieser Wallet (${walletUsd.toFixed(2)} $), höchstens ${S.maxTradeUsd} $ pro Kauf, keine Käufe unter ${S.floorUsd} $.\n\nIm Test haben diese Regeln im Schnitt Geld verloren.\n\nZum Einschalten ECHTGELD eintippen:`);
    if (t !== "ECHTGELD") { log("ECHTGELD nicht eingeschaltet (Wort nicht eingetippt).", "muted"); return; }
  }
  mode = m;
  const acc = await get("deskAcc", null);   // start fresh: only the desk's NEW trades from now on are mirrored
  state.seenT = Math.max(state.seenT, ...((acc && acc.activity) || []).map(a => a.t), Date.now() - 1000);
  put("liveState", state);
  renderMode();
  log({ off: "Schalter: AUS", probe: "Schalter: Probelauf (nichts wird gesendet)", live: "🔴 Schalter: ECHTGELD AN" }[m], m === "live" ? "neg" : "");
  if (m !== "off") refresh();
}

async function killAll() {
  const was = mode;
  mode = "off"; renderMode();
  log("NOT-AUS gedrückt: Schalter AUS.", "neg");
  if (!box) return;
  if (!wallet) { log("Wallet gesperrt: zum Verkaufen erst entsperren und NOT-AUS nochmal drücken.", "neg"); return; }
  const r = await rpc("getTokenAccountsByOwner", [box.address, { programId: "TokenkegQfeZyiNwAJbNbGqPXbJ7Hj8vR2iXnn" }, { encoding: "jsonParsed" }]).catch(() => ({ value: [] }));
  const r2 = await rpc("getTokenAccountsByOwner", [box.address, { programId: "TokenzQdBNbLqP5VEhdkAS6EPFLSuuhxx6ZtvQkmDWo" }, { encoding: "jsonParsed" }]).catch(() => ({ value: [] }));
  const mints = [...r.value, ...r2.value].map(a => a.account.data.parsed.info).filter(i => i.tokenAmount.amount !== "0").map(i => i.mint);
  if (!mints.length) { log("Keine Coins in der Wallet, nichts zu verkaufen."); return; }
  if (!window.confirm(`${mints.length} Coin(s) jetzt mit echtem Geld zu SOL verkaufen?`)) return;
  for (const mint of mints) {
    try { await swap({ type: "sell", mint, frac: 1, why: "Not-Aus" }, true, true); delete state.held[mint]; }
    catch (e) { log(`Not-Aus Verkauf ${mint.slice(0, 6)} fehlgeschlagen: ${esc(e.message)}`, "neg");
    }
  }
  put("liveState", state); refresh();
  if (was === "live") log("Alles verkauft (soweit möglich). Schalter bleibt AUS.");
}

// ---------- UI ----------
async function init() {
  renderMode();
  if (!isExt) {
    $("noExt").style.display = "";
    document.querySelectorAll("button, input").forEach(e => e.disabled = true);
    return;
  }
  box = await get("liveBox", null);
  S = { ...LIVE_DEFAULTS, ...(await get("liveSettings", {})) };
  state = { ...state, ...(await get("liveState", {})) };
  logLines = await get("liveLog", []);
  renderWallet(); renderSettings(); renderLog(); refresh();

  $("create").onclick = async () => {
    if ($("pw1").value !== $("pw2").value) return alert("Die Passwörter sind nicht gleich.");
    try {
      const w = await newWallet().catch(() => { throw new Error("Dieses Chrome kann keine Solana-Schlüssel erzeugen (Ed25519). Bitte Chrome aktualisieren."); });
      box = await encryptWallet(w, $("pw1").value);
      await put("liveBox", box);
      wallet = await unlockFromSeed(w.seed, w.pub);
      $("pw1").value = $("pw2").value = "";
      renderWallet();
      $("backupStr").textContent = backupString(w.seed, w.pub); $("backup").style.display = "block";
      log("Neue Bot-Wallet erstellt: " + box.address);
    } catch (e) { alert(e.message); }
  };
  $("unlock").onclick = async () => {
    try { const w = await decryptWallet(box, $("pw").value); wallet = await unlockFromSeed(w.seed, w.pub); $("pw").value = ""; renderWallet(); log("Wallet entsperrt."); }
    catch (e) { alert(e.message); }
  };
  $("showBackup").onclick = async () => {
    if ($("backup").style.display === "block") { $("backup").style.display = "none"; $("backupStr").textContent = ""; return; }
    const pw = prompt("Passwort für die Sicherung:"); if (!pw) return;
    try { const w = await decryptWallet(box, pw); $("backupStr").textContent = backupString(w.seed, w.pub); $("backup").style.display = "block"; }
    catch (e) { alert(e.message); }
  };
  $("delWallet").onclick = async () => {
    if (prompt("Die Wallet wird gelöscht. Geld darauf ist dann nur noch mit der Papier-Sicherung zu retten. Zum Löschen LÖSCHEN eintippen:") !== "LÖSCHEN") return;
    await setMode("off"); await chrome.storage.local.remove(["liveBox", "liveState"]);
    box = null; wallet = null; state = { seenT: 0, held: {}, day: today(), tradesToday: 0 }; renderWallet(); log("Wallet gelöscht.");
  };
  $("copyAddr").onclick = () => navigator.clipboard.writeText(box.address);
  $("refresh").onclick = refresh;
  document.querySelectorAll(".modes button").forEach(b => b.onclick = () => setMode(b.dataset.m));
  $("kill").onclick = killAll;
  for (const [id, key, f] of [["maxTradeUsd", "maxTradeUsd", Number], ["floorUsd", "floorUsd", Number], ["maxTradesDay", "maxTradesDay", Number], ["slip", "slippageBps", v => Math.round(Number(v) * 100)]]) {
    $(id).onchange = () => { const v = f($(id).value); if (v >= 0) { S[key] = v; put("liveSettings", S); log(`Grenze geändert: ${key} = ${v}`); } };
  }
  $("jupKey").value = S.jupKey || "";
  $("jupKey").onchange = () => { S.jupKey = $("jupKey").value.trim(); put("liveSettings", S); };

  chrome.storage.onChanged.addListener((ch, area) => {
    if (area === "local" && ch.deskAcc && mode !== "off") chain = chain.then(() => mirror(ch.deskAcc.newValue)).catch(() => {});
  });
  setInterval(() => { if (mode !== "off") refresh(); }, 30000);
  window.addEventListener("beforeunload", e => { if (mode === "live") { e.preventDefault(); e.returnValue = ""; } });
}
init();
