# Dev and holder checks: results, 2026-10-21 (fake money only)

Pre-registration: research/PREREG-DEVHOLDER-2026-10-21.md (commit 1bd6a89, pushed before the first result). Scripts and raw
output: research/devholder/. Data: big-test export of 21 Oct 06:29 UTC (bigtest branch, research/get_data.sh), 529,930
learnable rows, 341 scans, 7 Oct 11:02 to 21 Oct 04:00 UTC. Fees 1% per side (results with 0.5% and 1.5% give the same
verdicts).

## Answer

No dev or holder factor passed the pre-registered test. Nothing is built into the filter team.

- Two factors passed the profit part: vetoing pump.fun coins with few replies (pf.replies < 909) or a low ATH ratio
  (pf.athRatio < 8316). Gain on the check scans +0.23 and +0.22 EUR per 20, coin-bootstrap intervals [+0.20, +0.27] and
  [+0.18, +0.25]. Both fail the 3x part: the kept rows' 3x rate drops from 0.055% to 0.03% and 0.02%. In practice both act as
  "skip young pump.fun coins", which avoids rugs and big hits alike. The kept rows still lose (-0.71, -0.73 per 20).
- Near misses, failing the Holm correction and the 3x part: dev.sold (creator sold, gain +0.44 [+0.06, +0.85]) and rc.top1
  above 5.5% (gain +1.08 [+0.04, +2.06], only 150 vetoed coins). The bot already blocks a creator sale and one wallet above
  20% (memebot.risk_view). On the bot's own gate passers of the check scans (593 rows, 85 coins, -0.96 per 20, zero 3x) the
  tighter rc.top1 veto gives -0.55 on 32 coins: too few to tell.
- Jupiter holder factors (devMints, top10Pct, mcPerHolder, holderChg24, organic, holders, netBuyers24): no veto gained on
  discovery or on the check.

## The pattern behind it

The same as in research/HISTORY2-2026-10-21.md: what marks danger also marks the big hits. Rows with a creator sale had a
62% (discovery) and 36% (check) rug rate, but also the highest 3x rate (1.8% and 1.4%, against 0.3% and 0% for the kept).

Added later, not pre-registered (research/devholder/deciles_added_later.txt): the 3x coins sit at higher holder growth
(jup.holderChg24, rank AUC 0.70 discovery / 0.82 check), net new buyers (jup.netBuyers24, 0.74 / 0.88) and organic score
(0.73 / 0.77). The top 1% of holder growth had a 3x rate of 0.87% / 1.67% (16 to 30 times the base) but still averaged
-2.54 / -1.73 per 20 with a 2% rug rate. A lottery-ticket signal, not a profitable filter at a 1.7-hour exit. Whether these
coins keep running past 1.7 hours is not in this data.

## What could not be tested here

The research container cannot reach outside APIs (RugCheck, pump.fun, Solana RPC, Solscan answered with a proxy refusal), so
only what the bot stored live at scan time was used. RugCheck, dev and trade-sample factors exist only for the ~20
shortlisted coins per scan (2,098 rows). Sniper count and creator launch history were already tested on the launch radar
(research/STUDY-2026-10-21.md) and failed. Bundled buys and full dev-wallet history would need a Solana indexer with a key
(e.g. Helius free tier).
