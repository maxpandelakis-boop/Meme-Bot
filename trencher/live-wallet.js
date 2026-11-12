// Echtgeld-Wallet of the Trencher: a small, separate "burner" wallet made inside the extension.
// - The key is made here (WebCrypto Ed25519), never typed in, never sent anywhere.
// - It is stored only encrypted (AES-GCM, key from the user's password via PBKDF2-SHA256, 600k rounds) in chrome.storage.local.
// - Decrypted, it lives only in this page's memory and is gone on reload / tab close.
// No library: base58, Solana transaction signing and the crypto are written here so nothing third-party ever sees the key.

const subtle = globalThis.crypto.subtle;
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export const PBKDF2_ROUNDS = 600000;

export function b58encode(bytes) {
  bytes = Uint8Array.from(bytes);
  let zeros = 0; while (zeros < bytes.length && bytes[zeros] === 0) zeros++;
  const digits = [];
  for (let i = zeros; i < bytes.length; i++) {
    let carry = bytes[i];
    for (let j = 0; j < digits.length; j++) { carry += digits[j] << 8; digits[j] = carry % 58; carry = (carry / 58) | 0; }
    while (carry) { digits.push(carry % 58); carry = (carry / 58) | 0; }
  }
  return "1".repeat(zeros) + digits.reverse().map(d => B58[d]).join("");
}

export function b58decode(s) {
  let zeros = 0; while (zeros < s.length && s[zeros] === "1") zeros++;
  const bytes = [];
  for (let i = zeros; i < s.length; i++) {
    let carry = B58.indexOf(s[i]);
    if (carry < 0) throw new Error("kein base58");
    for (let j = 0; j < bytes.length; j++) { carry += bytes[j] * 58; bytes[j] = carry & 0xff; carry >>= 8; }
    while (carry) { bytes.push(carry & 0xff); carry >>= 8; }
  }
  return Uint8Array.from([...new Array(zeros).fill(0), ...bytes.reverse()]);
}

export const b64encode = u8 => { let s = ""; for (const b of u8) s += String.fromCharCode(b); return btoa(s); };
export const b64decode = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

// PKCS#8 wrapper of a raw 32-byte Ed25519 seed (RFC 8410), so WebCrypto can import it.
const PKCS8_PREFIX = Uint8Array.from([0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20]);
const seedToPkcs8 = seed => Uint8Array.from([...PKCS8_PREFIX, ...seed]);

async function importSeed(seed) {
  const priv = await subtle.importKey("pkcs8", seedToPkcs8(seed), { name: "Ed25519" }, false, ["sign"]);
  return priv;
}

// A fresh wallet: {seed (32 bytes), pub (32 bytes), address (base58)}.
export async function newWallet() {
  const kp = await subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const pkcs8 = new Uint8Array(await subtle.exportKey("pkcs8", kp.privateKey));
  const seed = pkcs8.slice(pkcs8.length - 32);
  const pub = new Uint8Array(await subtle.exportKey("raw", kp.publicKey));
  return { seed, pub, address: b58encode(pub) };
}

// Unlocked wallet from a seed: can sign, the seed itself stays inside a non-extractable CryptoKey.
export async function unlockFromSeed(seed, pub) {
  const key = await importSeed(seed);
  return { address: b58encode(pub), pub: Uint8Array.from(pub), sign: async msg => new Uint8Array(await subtle.sign({ name: "Ed25519" }, key, msg)) };
}

// Phantom/Solflare "private key" format (base58 of seed||pub), only for the user's paper backup.
export const backupString = (seed, pub) => b58encode(Uint8Array.from([...seed, ...pub]));

async function passKey(password, salt) {
  const base = await subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return subtle.deriveKey({ name: "PBKDF2", salt, iterations: PBKDF2_ROUNDS, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

// -> {v, address, salt, iv, ct} (all strings): safe to store, useless without the password.
export async function encryptWallet(w, password) {
  if (!password || password.length < 10) throw new Error("Passwort zu kurz (mind. 10 Zeichen)");
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv }, await passKey(password, salt), w.seed));
  return { v: 1, address: w.address, salt: b64encode(salt), iv: b64encode(iv), ct: b64encode(ct) };
}

// -> {seed, pub, address}; throws "falsches Passwort".
export async function decryptWallet(box, password) {
  let seed;
  try { seed = new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: b64decode(box.iv) }, await passKey(password, b64decode(box.salt)), b64decode(box.ct))); }
  catch { throw new Error("falsches Passwort"); }
  const pub = b58decode(box.address);
  const w = await unlockFromSeed(seed, pub);
  const probe = crypto.getRandomValues(new Uint8Array(8));      // the stored address must belong to this seed
  const ok = await subtle.verify({ name: "Ed25519" }, await subtle.importKey("raw", pub, { name: "Ed25519" }, false, ["verify"]), await w.sign(probe), probe);
  if (!ok) throw new Error("Wallet-Daten passen nicht zusammen");
  return { seed, pub, address: box.address };
}

// ---------- Solana transaction (legacy or v0) signing ----------
function shortvec(u8, o) { let len = 0, size = 0; for (;;) { const b = u8[o + size]; len |= (b & 0x7f) << (7 * size); size++; if (!(b & 0x80)) break; } return { len, size }; }

// Signer public keys of a serialized transaction, and where its message starts.
export function txLayout(tx) {
  const sig = shortvec(tx, 0);
  const msgStart = sig.size + sig.len * 64;
  let o = msgStart;
  if (tx[o] & 0x80) o++;                       // v0: version prefix byte
  const numSigners = tx[o];
  o += 3;
  const keys = shortvec(tx, o); o += keys.size;
  const signers = [];
  for (let i = 0; i < numSigners; i++) signers.push(b58encode(tx.slice(o + i * 32, o + i * 32 + 32)));
  return { numSigs: sig.len, sigStart: sig.size, msgStart, signers };
}

// Sign a base64 transaction (e.g. from Jupiter) with the unlocked wallet; -> base64 signed transaction.
export async function signTx(b64, wallet) {
  const tx = b64decode(b64);
  const L = txLayout(tx);
  const i = L.signers.indexOf(wallet.address);
  if (i < 0 || i >= L.numSigs) throw new Error("Transaktion ist nicht für diese Wallet");
  const sig = await wallet.sign(tx.slice(L.msgStart));
  tx.set(sig, L.sigStart + i * 64);
  return b64encode(tx);
}
