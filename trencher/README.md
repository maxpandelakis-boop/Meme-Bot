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
- Gebühr wie bei FOMO angenommen: 0,5 % pro Trade, mindestens 0,81 $ (dieselben Zahlen wie `memebot.py`). Bei 20 $ sind das ca. 4 % pro Trade.
- Die Order wird **1 Sekunde nach dem Klick** zum dann aktuellen Preis gefüllt.
- Slippage: Preiswirkung am Pool (Betrag ÷ halbe Liquidität) plus 0,3 %. Ohne Liquiditätsangabe wird 5.000 $ angenommen.
- Der Kontowert rechnet die Position so, als würdest du jetzt alles verkaufen (mit Slippage und Gebühr).
- Die gelbe Zeile sagt, wie viel % der Kurs steigen muss, bis ein Rein-und-Raus überhaupt Gewinn macht.

## Datenquellen (kostenlos, ohne Schlüssel)
- Preis: DexScreener, jede Sekunde.
- Trades: GeckoTerminal alle 2,5 s (der letzte Trade gibt auch den frischesten Preis). PumpPortal schickt Trades pro Coin nur mit bezahltem API-Schlüssel; ohne Schlüssel wird es übersprungen.
- DexScreener speichert den Preis einige Sekunden zwischen, deshalb gewinnt ein frischer Trade-Preis.

## Test
`node trencher/test_sim.mjs` prüft die Geldrechnung.
