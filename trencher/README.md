# Meme Trencher: Chrome-Erweiterung zum Üben mit Spielgeld

Eine Seitenleiste in Chrome neben FOMO (oder DexScreener, pump.fun): Live-Trades eines Solana Meme Coins im Sekundentakt und
Kaufen/Verkaufen mit **Spielgeld**. Keine Wallet, keine Schlüssel, nichts wird echt gekauft.

## Installieren (einmal, 1 Minute)
1. Diesen Ordner `trencher` herunterladen (oder `trencher.zip` entpacken).
2. In Chrome `chrome://extensions` öffnen, oben rechts **Entwicklermodus** einschalten.
3. **Entpackte Erweiterung laden** und den Ordner `trencher` wählen.
4. Das Puzzle-Symbol anklicken, „Meme Trencher" anheften, dann auf das Symbol klicken: die Seitenleiste geht auf.

## Benutzen
- Auf einer Coin-Seite liest die Leiste die Coin-Adresse selbst („Seite folgen"). Sonst die Adresse (CA) einfügen und **Laden**.
- Jeder Coin startet mit **20 $**. Kaufen (alles / 50 %) und Verkaufen (alles / 50 %), oder Taste **B** und **S**.
- „Coin zurücksetzen" setzt nur diesen Coin wieder auf 20 $.

## Wie die Füllung gerechnet wird (damit der Gewinn nicht geschönt ist)
- Gebühr wie bei FOMO: 0,5 % pro Trade, mindestens 0,50 $ (FOMO zeigte 0,50 $ Gebühr bei einem Kauf über 25,22 $). Bei 20 $ sind das 2,5 % pro Trade.
- Die Order wird **1 Sekunde nach dem Klick** zum dann aktuellen Preis gefüllt.
- Slippage: Preiswirkung am Pool (Betrag ÷ halbe Liquidität) plus 0,3 %. Ohne Liquiditätsangabe wird 5.000 $ angenommen.
- Der Kontowert rechnet die Position so, als würdest du jetzt alles verkaufen (mit Slippage und Gebühr).
- Die gelbe Zeile sagt, wie viel % der Kurs steigen muss, bis ein Rein-und-Raus überhaupt Gewinn macht.

## Datenquellen (kostenlos, ohne Schlüssel)
- Trades live (unter 1 s): direkt von der Solana-Blockchain über PublicNodes kostenlosen RPC-Websocket (`logsSubscribe` auf das
  ganze pump.fun- bzw. PumpSwap-Programm, im Panel nach Coin/Pool gefiltert). Der offizielle RPC (api.mainnet-beta.solana.com)
  lehnt Chrome-Erweiterungen mit 403 ab.
- Preis, Liquidität, Market Cap: DexScreener jede Sekunde (dort einige Sekunden zwischengespeichert, ein frischer Trade gewinnt).
- Chart-Verlauf beim Laden und Ersatz, wenn die Blockchain schweigt: GeckoTerminal alle 15 s (30 s zwischengespeichert, bei 429 eine Minute Pause).
- Auf einer FOMO-Coinseite liest `fomo.js` Preis, Liquidität und Market Cap direkt aus FOMOs Kopfzeile (2x pro Sekunde, nur lesen).
  Für Coins auf Raydium, Meteora usw. (ohne Live-Trades von der Blockchain) handelt der Bot dann nur nach FOMOs Preis:
  Volumen- und Käufer-Regeln entfallen, es zählt der Kursanstieg.
- DexScreener-Pool: der mit dem meisten 24-h-Volumen (ein toter Pool mit alter Liquiditätsangabe gewinnt nicht mehr).

## Test
`node trencher/test_sim.mjs` prüft die Geldrechnung.

## Auto-Bot
Auf **▶ Bot starten** klicken: der Bot kauft und verkauft den geladenen Coin allein mit dem Spielgeld, jede Sekunde eine Entscheidung.
Standard-Regeln (unter „Regeln des Bots ändern" einstellbar): kaufen, wenn in den letzten 20 s mind. 60 % des Volumens Käufe
waren (mind. 100 $) und der Kurs um +0,5 bis +25 % stieg, bei mind. 3.000 $ Liquidität (unbekannt zählt nicht dagegen).
Neben dem Start-Knopf steht live, welche Bedingung gerade fehlt (✓/✗). Verkaufen bei +5 % netto, bei -8 % netto,
wenn der Kurs im Gewinn 4 % vom Hoch fällt, bei 70 % Verkaufsdruck in 10 s im Gewinn oder nach 90 s. Danach 10 s Pause.
Jede Entscheidung steht mit Grund im Bot-Log, Bot-Trades im Chart mit 🤖.

## Chart
Kerzen (1 s, 5 s, 15 s, 1 m) aus den echten Trades, mit Volumen. Deine Spielgeld-Käufe (grüner Pfeil „K") und Verkäufe
(Pfeil „V" mit Gewinn/Verlust) stehen direkt im Chart, dein Einstiegspreis als gelbe gestrichelte Linie.
Chart-Bibliothek: TradingView Lightweight Charts™ 4.2.3 (Apache 2.0, `lib/`).

## Copy-Bot (ab v0.5.0, Spielgeld)

Das Seitenfenster öffnet jetzt den Copy-Bot (`copy.html`). Der alte Coin-Trencher ist oben rechts verlinkt.

1. **Agents**: Name und Solana-Wallet eines Traders eintragen (eine Solscan- oder andere Adresse mit Link geht auch).
2. **Home → Bot starten**: Kauft der Trader einen Coin, kauft der Bot 30 s später für 20 $ Spielgeld nach. Verkauft der Trader, verkauft der Bot auch. Spätestens bei 10x nimmt er den Gewinn mit.
3. Regeln (Einsatz, Sekunden, 10x, Stop-Loss, Startgeld) stehen unter **Agents**.

Daten: Trades der Wallets kommen von der Solana-Blockchain (PublicNode, kostenlos), Preise von DexScreener. Der Bot läuft nur, solange das Seitenfenster offen ist. Keine Wallet, keine Schlüssel, kein echtes Geld.

**Reddit (optional):** Reddit sperrt anonyme Abrufe. Unter reddit.com/prefs/apps eine App vom Typ „installed app“ anlegen (Redirect-URI z. B. `http://localhost`) und ihre ID unter **Agents → Reddit** eintragen. Der Bot zählt dann, wie oft die heißen Coins in r/solana, r/memecoins, r/SolanaMemeCoins, r/CryptoMoonShots und r/pumpfun genannt werden.

## Webseite und Handy-App (ab v0.6.0)

Derselbe Copy-Bot läuft auch ohne Chrome-Erweiterung als Webseite:
https://raw.githack.com/maxpandelakis-boop/Meme-Bot/trencher-extension/trencher/copy.html

Am Handy: Seite öffnen → Teilen/Menü → „Zum Startbildschirm hinzufügen“. Dann startet sie wie eine App. Der Bot läuft, solange die Seite offen ist (der Bildschirm bleibt dafür an). Konto und Trader bleiben nur in diesem Browser gespeichert.

## Trading Desk (ab v0.7.0, Spielgeld)

Wie im zweiten Video (2026-11-09), nur ohne echtes Geld:

- **Scout** sucht jede Minute heiße Coins (GeckoTerminal-Trends, DexScreener-Boosts, neue Profile, Käufe/Verkäufe pro Stunde, Reddit) und gibt Punkte (0–100). Ab 60 Punkten, steigendem Kurs und mehr Käufern als Verkäufern kauft er den besten Coin.
- **Compounder:** Start 20 $, jeder Kauf 40 % vom freien Geld, höchstens 2 offen, kein Nachkaufen.
- **Risk:** −8 % = alles raus, solange 2× nie kam. Bei 2× wird der Einsatz zurückverkauft, der Rest verkauft 10 % unter seinem Hoch.
- **Executor:** Spielgeld-Fills mit FOMO-Gebühren (0,5 %, mind. 0,50 $) und Slippage.
- Antippen eines Eintrags öffnet die Coin-Seite: Kerzen-Chart mit Entry / „Sold half“, die Desk-Regeln für diesen Coin und die Position.
- Wallets folgen geht weiter (Agents), die Desk-Regeln gelten auch für kopierte Käufe.

## Rund um die Uhr, Chat, Log, Teilen (ab v0.8.0)

- **Server 24/7:** `.github/workflows/trencher-desk.yml` (auf dem Hauptbranch) startet `trencher/desk-runner.mjs` auf GitHub. Der Desk läuft dort mit Spielgeld weiter, auch wenn kein Gerät an ist, und schreibt seinen Stand in den Branch `desk-data`. In der App oben „☁ Server 24/7“ antippen: dann zeigt sie diesen Desk (Stand alle 90 Sekunden). Regeln des Server-Desks: `config.json` im Branch `desk-data` (auf GitHub bearbeiten oder im Chat schreiben, der Chat kopiert den Text). Stoppen: Actions → „Trencher desk“ → Disable workflow, oder Variable `TRENCHER_DESK=0`.
- **Chief of Staff (Agents):** Regeln in Worten, z. B. „40% vom freien Geld, max 2 offen“, „stop 8%“, „trail 10%“, „hälfte bei 2x“, „punkte 70“, „halte den desk klein“, „status“, „start“, „stop“. Einfache Texterkennung, nichts wird verschickt.
- **Log (Activity → Log):** jede Entscheidung der Agenten als Zeile, wie das Terminal im Video.
- **Teilen:** oben rechts, teilt den Stand als Text.
- Prüfung der Desk-Regeln auf alten Daten: `research/DESK-2026-11-11.md` (Verlust, −2,34 pro 20).

## Echtgeld-Schalter (standardmäßig AUS)
In der Erweiterung oben im Trading Desk auf **Echtgeld ↗**. Nur in der Chrome-Erweiterung, nicht auf der Web-Seite.
- **Eigene Bot-Wallet**: wird in der Erweiterung neu erzeugt, mit deinem Passwort verschlüsselt (AES-GCM, PBKDF2 600.000 Runden)
  und nur in Chrome auf diesem Computer gespeichert. Entsperrt lebt der Schlüssel nur im Speicher der offenen Seite. Nie deine
  Haupt-Wallet oder Phantom-Wörter benutzen. Die Sicherung (Phantom-Format) gehört auf Papier.
- **Schalter**: AUS / Probelauf (echte Jupiter-Anfrage + Solana-Simulation, nichts wird gesendet) / ECHTGELD (Wort `ECHTGELD`
  eintippen). Nach jedem Neuladen wieder AUS und gesperrt.
- **Was er macht**: jeder neue Kauf/Verkauf des Desks (Seitenleiste muss laufen) wird mit der Bot-Wallet über Jupiter (kostenlos, keine
  FOMO-Gebühr) nachgemacht. Signale älter als 2 Minuten werden nicht nachgeholt.
- **Harte Grenzen**: max. 8 $ pro Kauf, keine Käufe unter 12 $ Wallet-Wert, max. 20 Trades/Tag, 5 % Slippage, Priority-Fee max. 0,0002 SOL.
- Nur der lokale Desk im Browser wird nachgemacht, nie der Server-24/7-Desk (dort schaut niemand zu).
- **NOT-AUS**: schaltet aus und verkauft alle Coins der Bot-Wallet zu SOL.
- Test: `node trencher/test_live.mjs` (Schlüssel, Verschlüsselung, Signatur, Grenzen; ohne Netz).
