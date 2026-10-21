# Pre-registration: dev and holder checks on the big test (fake money only)

Written on 2026-10-21 before any result of the rules below was looked at (only coverage counts were looked at: how many rows
carry each factor). Nothing below may change after the first look; anything added later is labelled as added later.

The question (the user, 21 Oct): bring in as many sources as possible about the developer and the holders, and add more
filter bots. The container cannot reach outside APIs, so the test uses what the bot itself already stored at scan time
(research/BRIEF.md): Jupiter token data (jup.*), pump.fun (pf.*), RugCheck (rc.*), the creator check (dev.*) and the
public-RPC trade sample (fl.*). These were all recorded live, so there is no look-ahead in the factors.

## Data and split

Big test rows (research/harness.py, rule m9-2h, learnable coins), 7 Oct 11:02 to 21 Oct 04:00 UTC.
Discovery: scans before 15 Oct 00:00 UTC (199 scans). Check: scans from 15 Oct 00:00 UTC (142 scans).

## Outcome

What a 20 EUR ticket became at the check (about 1.7 h), with realistic fees of 1% per side instead of the 0.81 EUR placeholder:
eur = 20 * mult * 0.99 * 0.99 - 20, a coin gone to zero (under 2% of entry, or no price) = -20, clipped to -20..+60.
Also reported: share gone to zero ("rug rate") and share at 3x or more ("3x rate"). Sensitivity: 0.5% and 1.5% per side.

## Populations

- P1 (wide factors): every learnable row. Factors: jup.devMints (high = bad), jup.top10Pct (high = bad), jup.mcPerHolder
  (high = bad), jup.holderChg24 (low = bad), jup.organic (low = bad), jup.holders (low = bad), jup.netBuyers24 (low = bad),
  pf.replies (low = bad), pf.athRatio (low = bad).
- P2 (narrow factors, only coins on the shortlist with a RugCheck report): rows with rc.score present. Factors: rc.top1,
  rc.top10, rc.insiders, rc.score, dev.pct, dev.txs3h, fl.topBuyer, fl.flip (high = bad); rc.holders, rc.lp (low = bad);
  dev.sold (1 = bad, fixed threshold).

## Rule per factor (fitted on discovery only)

A veto: drop rows on the bad side of a threshold; rows without the factor are kept. Candidate thresholds: the 10th, 20th, ...,
90th percentile of the factor on discovery rows that carry it. Chosen: the threshold with the largest discovery gain (kept
mean minus population mean) among those that drop at least 5% and keep at least 20% of the rows. The threshold is then
frozen and run once on the check scans.

## Decision (check scans only)

A factor holds if, on the check scans: the gain is positive AND its 95% interval from a coin bootstrap (rows grouped by coin,
2,000 resamples, seed 7) lies above zero after a Holm correction over all factors tested (one-sided p from the bootstrap)
AND the kept rows' 3x rate is not lower than the population's. With fewer than 30 vetoed coins on the check a factor is
undecided.

Every factor that holds becomes its own bot in the filter team (filter_team.py), on this branch, with a pull request.
If none holds, I say so plainly and build nothing.

## Reported beside it, not deciding

- For each factor: rug rate and 3x rate of vetoed vs kept, on both halves; the same with the 0.5% and 1.5% fees.
- The bot's own gate passers on the check with and without each held factor.
- 3x catcher: for each factor, whether rows at 3x or more sit higher or lower than the rest (rank AUC) on both halves.
