// Content script on fomo.family coin pages: reads the price, liquidity and market cap FOMO shows in its header, twice a second,
// and sends them to the Trencher panel. Read-only: it never clicks, types or touches the wallet.
(() => {
  const B58 = /[1-9A-HJ-NP-Za-km-z]{32,44}/;
  function stat(label) {
    // a header box is a label ("Price") with the value right under it ("$0.0₄2159")
    for (const el of document.querySelectorAll("div,span,p")) {
      if (el.childElementCount || el.textContent.trim() !== label) continue;
      const box = el.parentElement;
      if (!box) continue;
      const m = box.innerText.match(new RegExp("^\\s*" + label + "\\s*\\n\\s*(\\$[^\\n]+)"));
      if (m) return m[1].trim();
    }
    return null;
  }
  let last = "";
  setInterval(() => {
    const mint = (location.pathname.match(B58) || [])[0];
    if (!mint || !/\/tokens\//.test(location.pathname)) return;
    const price = stat("Price"), liq = stat("Liquidity"), mc = stat("Market cap");
    if (!price) return;
    const key = mint + price + liq + mc;
    const msg = { type: "fomo", mint, price, liq, mc, t: Date.now(), changed: key !== last };
    last = key;
    try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch { /* panel closed or extension reloaded */ }
  }, 500);
})();
