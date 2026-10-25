# Pre-registration: the Radar model without its market inputs (research only)

Written 25 Oct 2026 around 23:00 UTC, before the variant is run. Nothing in the bot changes; the live model (rocket_model.json,
cut top 0.5 %) stays.

Why: in the live model the four market inputs btc_24h, btc_1h, sol_24h, sol_1h are 4 of the 7 most used split features (about 16 %
of all splits; btc_24h is the most used one), learned from about 60 market days (history2, 10 Aug - 8 Oct). Its wallet memory is
fixed at 8 Oct. Question: does the model need the market inputs, or did it learn the weather of Aug/Sep?

Run: the grid of the live model rebuilt as before (early_grid.py LIVEHL=1 LIVETR=300, rows from 30 min = grid_live.pkl), then
rocket_model.py's walk-forward stress test (every week 24 Aug - 8 Oct, trained only on coins two days older), seeds 1-5, once as it
is (base) and once with DROP=btc_1h,btc_24h,sol_1h,sol_24h (no-market). Nothing else changes.

Judged at the live cut (top 0.5 %), per 20 EUR, averaged over the 5 seeds:
- "no worse" when the no-market average is at most 0.50 EUR below base and its 10x share at most 0.5 points below base;
- "steadier" when the weekly buy counts vary less (coefficient of variation over the 7 weeks, seed mean) than base.
Only "no worse" AND "steadier" keeps idea 8 on the list as "swap after the user's yes". Otherwise idea 8 is dropped. Profit is not
claimed either way: the corrected Radar loses at every cut (PR #21, #25).
