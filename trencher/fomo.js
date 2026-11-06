// Content script on fomo.family coin pages: reads the price, liquidity and market cap FOMO shows in its header, twice a second,
// and sends them to the Trencher panel. Read-only: it never clicks, types or touches the wallet.
(() => {
  const B58 = /[1-9A-HJ-NP-Za-km-z]{32,44}/;
  const SUBD = "₀₁₂₃₄₅₆₇₈₉";
  // text of a node with <sub> digits kept as subscript characters ("$0.0<sub>5</sub>5554" -> "$0.0₅5554"), blocks spaced
  function text(node) {
    if (node.nodeType === 3) return node.nodeValue;
    if (node.nodeType !== 1) return "";
    const tag = node.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "svg") return "";
    let s = "";
    for (const c of node.childNodes) s += text(c);
    if (tag === "SUB") s = s.replace(/\d/g, d => SUBD[d]);
    const disp = node.nodeType === 1 && getComputedStyle(node).display;
    return disp && disp !== "inline" ? " " + s + " " : s;
  }
  const VAL = "(\\$\\s*[0-9][0-9.,₀-₉]*\\s*[KMB]?)";
  function stat(label) {
    // a header box: a label element ("Price") and, in the same box, the value ("$0.0₅5554")
    for (const el of document.querySelectorAll("div,span,p,label,dt,th")) {
      if (el.childElementCount || el.textContent.trim() !== label) continue;
      let box = el.parentElement;
      for (let up = 0; box && up < 3; up++, box = box.parentElement) {
        const m = text(box).replace(/\s+/g, " ").match(new RegExp(label + "\\s*" + VAL));
        if (m) return m[1].replace(/\s+/g, "");
      }
    }
    return null;
  }
  function snippet() {
    for (const el of document.querySelectorAll("div,span,p")) {
      if (!el.childElementCount && el.textContent.trim() === "Price" && el.parentElement)
        return el.parentElement.outerHTML.replace(/\s(class|style)="[^"]*"/g, "").slice(0, 300);
    }
    return "kein 'Price' gefunden";
  }
  let last = "", n = 0;
  setInterval(() => {
    const mint = (location.pathname.match(B58) || [])[0];
    if (!mint || !/\/tokens\//.test(location.pathname)) return;
    const price = stat("Price"), liq = stat("Liquidity"), mc = stat("Market cap");
    const key = mint + price + liq + mc;
    const msg = { type: "fomo", mint, price, liq, mc, t: Date.now(), changed: key !== last };
    if (!price && n++ % 10 === 0) msg.debug = snippet();   // so the panel can show what it could not read
    last = key;
    try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch { /* panel closed or extension reloaded */ }
  }, 500);
})();
