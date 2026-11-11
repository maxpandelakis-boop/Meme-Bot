# Trencher Trading Desk (nur Spielgeld)

Ein Bot für Solana Meme Coins wie im „Trading Desk“-Video, aber nur mit **Spielgeld**: keine Wallet, keine Schlüssel,
nichts wird echt gekauft. Läuft als Chrome-Seitenleiste, als Webseite / Handy-App und rund um die Uhr auf GitHub.

## Öffnen
- **Webseite / Handy:** https://raw.githack.com/maxpandelakis-boop/Meme-Bot/trencher-extension/trencher/copy.html
  Am Handy: Teilen/Menü → „Zum Startbildschirm hinzufügen“.
- **Chrome-Erweiterung:** Ordner `trencher` herunterladen, `chrome://extensions` → Entwicklermodus → „Entpackte Erweiterung laden“.
  Ein Klick aufs Symbol öffnet die Seitenleiste.

Oben wählt man, welchen Desk man sieht:
- **Dieser Browser:** läuft nur, solange die Seite offen ist (▶ Bot starten).
- **☁ Große 24/7:** der Server-Desk auf GitHub, kauft die heißesten Coins (Scout-Punkte).
- **☁ Frisch 24/7:** zweites Server-Konto, kauft nur ganz neue Coins (siehe unten).

## Die Agents
- **Scout** prüft jede Minute rund 70 Coins: GeckoTerminal-Trends (Seite 1–3) und neue Pools, DexScreener-Boosts und neue
  Profile, Käufe/Verkäufe pro Stunde, Reddit (optional). Punkte 0–100. Ab 60 Punkten, steigendem Kurs und mehr Käufern als
  Verkäufern kauft er den besten Coin, wenn **RugCheck** keine Gefahr meldet.
- **Prüfer:** einen Coin, den der Desk in den letzten 30 min verkauft hat, kauft er nur wieder, wenn der Coin die Scout-Prüfung neu besteht, die letzten 5 min steigen (mehr Käufe als Verkäufe), der Preis mindestens 5 % über dem Verkaufspreis liegt (Gebühren) und er ihn in der Zeit nicht schon 2× verkauft hat. Der Grund steht im Log.
- **Compounder:** Start 20 $, jeder Kauf 40 % vom freien Geld, höchstens 2 offen, kein Nachkaufen.
- **Risk:** −8 % = alles raus, solange 2× nie kam. Bei 2× wird der Einsatz zurückverkauft, der Rest verkauft 10 % unter seinem Hoch.
- **Executor:** Spielgeld-Fills mit FOMO-Gebühren und Slippage.
- **Chief of Staff** (Agents-Seite): Regeln in Worten, z. B. „40% vom freien Geld, max 2 offen“, „stop 8%“, „trail 10%“,
  „hälfte bei 2x“, „punkte 70“, „halte den desk klein“, „status“, „start“, „stop“. Einfache Texterkennung, nichts wird verschickt.
- **Wallets folgen** (optional, Agents-Seite): kauft eine Wallet, kauft der Desk nach; die Desk-Regeln gelten auch hier.
- **Live-Log** (Home und Activity → Log): jede Entscheidung als Zeile, wie das Terminal im Video. **Teilen** oben rechts.

## Frisch-Desk
Eigene 20 $, gleiche Verkaufsregeln. Kauft nur Coins mit Pool höchstens 60 min alt, Marktwert 8k bis 250k $, in den letzten
5 min mindestens 15 Käufer, 1,5× mehr Käufe als Verkäufe und steigendem Preis; dann die Prüfung (die besten drei der Reihe nach): RugCheck-Gefahren, Ersteller mit einem anderen Coin in den letzten 24 h, ein Wallet mit 20 % oder mehr. Die zwei letzten Regeln stammen aus `research/filters/FILTERS-2026-11-11.md`: kleinerer Verlust, kein Gewinn.
Gekauft wird erst **3 Sekunden** nach der Entscheidung zum Preis von dann, wie bei einem echten Bot. Weichen die Preise von GeckoTerminal und DexScreener dabei um mehr als 25 % ab, oder liegt der Coin bei DexScreener außerhalb des Filters, wird nicht gekauft.

## Frische Coins im Browser-Desk
„Dieser Browser“ kauft frische Coins nach denselben Regeln wie „Frisch 24/7“: nur pump.fun-Pools, Frisch-Filter beim ersten
Blick, dann die Prüfung (keine RugCheck-Gefahr, Ersteller ohne anderen Coin in 24 h, kein Wallet mit 20 % oder mehr; im
Browser gilt: RugCheck nicht erreichbar = kein Kauf), Kauf 3 Sekunden später zum Preis von dann. Abschaltbar unter
Agents → Regeln. Ein strengerer Picker („erst 10 Minuten beobachten“) wurde getestet und ist durchgefallen (−1,20 und −0,91
pro 20 $ statt −0,78 und −0,52). Auch die beste Frisch-Regel verliert im Test (`research/filters/FILTERS-2026-11-11.md`).

## Wie gerechnet wird (damit der Gewinn nicht geschönt ist)
- FOMO-Gebühr bei Kauf und Verkauf: unter 5 $ pauschal 0,10 $, 5 bis 47,50 $ 2 %, 47,50 bis 190 $ pauschal 0,95 $,
  ab 190 $ 0,5 %. Bei 8 bis 20 $ sind das rund 4 % hin und zurück.
- Slippage: Preiswirkung am Pool (Betrag ÷ halbe Liquidität) plus 0,3 %. Ohne Liquiditätsangabe gelten 5.000 $.
- Der Kontowert rechnet offene Positionen so, als würde jetzt alles verkauft (mit Slippage und Gebühr).
- Prüfung der Desk-Regeln auf alten Daten: `research/DESK-2026-11-11.md` (Verlust, −2,34 $ pro 20 $).

## Server 24/7
`.github/workflows/trencher-desk.yml` (Hauptbranch) startet `trencher/desk-runner.mjs` auf GitHub, etwa 5 h 40 min pro Lauf,
der nächste Lauf startet sich selbst. Der Stand steht im Branch `desk-data` (`desk.json`), die Regeln in `config.json`
(auf GitHub bearbeiten; der Chat kopiert den passenden Text). Stoppen: Actions → „Trencher desk“ → Disable workflow,
oder Repository-Variable `TRENCHER_DESK=0`.

## Dateien
| Datei | Was |
|---|---|
| `copy.html`, `copy.css`, `copy.js` | die App (Seitenleiste, Webseite, Handy) |
| `copy-engine.js` | Konto, Kauf/Verkauf, Desk-Regeln, Punkte, Wallet-Trades |
| `scout.js` | Coin-Quellen, Scout-Auswahl, Frisch-Filter, RugCheck (App und Server) |
| `sim.js` | Gebühren, Slippage, Fills |
| `desk-runner.mjs` | der 24/7-Desk für GitHub (beide Konten) |
| `test_sim.mjs`, `test_copy.mjs` | Tests: `node trencher/test_sim.mjs && node trencher/test_copy.mjs` |
| `manifest.json`, `background.js` | Chrome-Erweiterung |
| `app-manifest.json`, `sw.js`, `index.html`, `icons/` | Web-App |
| `lib/` | TradingView Lightweight Charts™ 4.2.3 (Apache 2.0) |

Daten (alle kostenlos, ohne Schlüssel): DexScreener, GeckoTerminal, RugCheck, PublicNode (Solana RPC), Reddit (eigene App-ID).
