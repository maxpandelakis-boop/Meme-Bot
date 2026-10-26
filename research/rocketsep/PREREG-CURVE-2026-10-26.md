# Pre-registration: buying the launch model's top picks on the bonding curve (26 Oct 2026, ~09:05 UTC)

Fake money only. Research only: nothing here is switched on, no bot, account or rule changes, no shadow in the live bots.
Written and pushed before a single curve price of these coins is fetched.

## Why

The rocket separator study (ROCKETSEP-2026-10-26.md) found nothing that holds after the graduation. One exploration there
(rs_curve_feas.py, curve_feas.json) gave a lead before it: of the 739 w4 launches that the Part 0a launch model ranks highest (top
0.1 %), 216 graduated, 123 of them within a minute of the launch (out of reach) and 93 after a minute or more: 12.6 % against
0.94 % of all launches, 13x. Whether that is worth money depends on the price an outsider pays on the curve, which no data we had
showed. The user (26 Oct 08:41 UTC) asked to keep checking for a way to recognise such coins; the coordinator passed on the go
for this free test (08:53 UTC).

Said plainly: the lead was found on w4 itself, so w4 is not unseen for this question. What is unseen is the money: no curve price
of any of these coins has been looked at. A pass here is a reason for a fresh month, not for switching anything on.

## The coins (frozen in research/rocketsep/curve_targets.csv by rs_curve.py targets)

The launch model of rs_curve_feas.py, unchanged: LightGBM on 14 facts known at the launch (creator's launches and graduations in
the 30 days before, launches in the hour before, CJK name, hour, weekend, name and ticker length, links, X link type, description
length, video, picture group, animated picture), fit on w3 (10 Aug-9 Sep), early stop on w3's last 15 %, seed 7, 93 trees. It
ranks the 739,407 w4 launches (10 Sep-6 Oct, mayhem mode left out).

- Primary set: the top 0.1 % by score, 739 launches (ranks 1-739).
- Secondary set: the top 1 %, 7,394 launches (ranks 1-7,394, including the primary set). Reported, not judged.

Ranking within w4 uses the month's own score order (a live bot would need a fixed score cut); it uses no outcome.

## The data

GeckoTerminal's public API (free, no key), from GitHub Actions because it is closed to this container: one-minute candles of each
coin's pump.fun curve pool (the curve address of the launch data; if that is not a pool there, the pump-fun pool in the coin's
token listing), priced in SOL (currency=token), from the launch up to its graduation plus 2 minutes, or 24 h and 5 minutes after
the launch. 2.2 s between calls, three runners at most, in .github/workflows/rocketsep-curve.yml; the data goes to the branch
rocketscurve.

First a probe on 30 w4 launches outside the top 5 % (15 graduated after 5+ minutes, 15 never graduated; research/rocketsep/
curve_probe.csv, random, seed 26): how many have candles, and whether the prices are in SOL (the first open near the curve's start
price P0 = 30 / 1,073 M = 2.80e-8 SOL, the last high of a graduated coin near the completion price G0 = 4.11e-7 SOL, 14.7 P0).
If fewer than 10 of the 30 have candles, the fetch does not start. G = G0 if the probe's median last high of its graduated coins is
within 25 % of G0, otherwise that median (then the prices are not plain SOL and the result says so).

## The plan (rs_curve.py judge, primary)

- Entry: the first minute that starts 60 s or more after the launch (60-120 s after it: time to read the launch facts and the
  picture). Price: the larger of that candle's open and close; with no trade in that minute, the close of the candle before
  (the curve's standing price); with no candle before it either, no price (counted as missing).
- No buy if the coin graduated before the end of the entry minute (out of reach), or if the entry price is already 0.9 G or more.
- Stake 50 EUR. pump.fun's curve fee 1.25 % on the buy and on the sale, and the 0.75 EUR allowance of PR #39 per trade (impact,
  network fees); the SOL price is taken as constant over the hold.
- Sale, minute by minute after the entry minute, the first that happens:
  1. stop: the candle's low at or under 0.5 x entry, filled at the lower of its open and 0.5 x entry;
  2. curve almost full: the candle's high at or over 0.9 G (about 93 % of the curve sold), filled at the higher of its open and
     0.9 G; this is how a coin that graduates is sold;
  3. time: 24 h after the entry minute, at the last close (a curve can always be sold back at its price).
  A one-trade spike in a candle (a low under half of its lower body end, a high over twice its upper body end) counts as the body.
  The stop is checked before the take in the same minute.
- A note on the curve: its price cannot fall under P0 (everyone selling back returns it there), so the loss of a buy at price P is
  at most 1 - P0 / P plus fees; the stop matters only for buys above 2 P0.

## The bar (the same as everywhere: research/PREREG-REVIEW-2026-11-04.md)

The primary plan on the primary set HOLDS if: (1) 40+ trades, (2) mean per trade after fees and the allowance above 0, (3) the 1st
percentile of 10,000 bootstrap re-draws of the mean above 0, (4) the total without its single best trade above 0.

And the data must be fair to it: GeckoTerminal may list busy curves more often than dead ones, which would leave out losers. If the
share of never-graduated coins with candles is under 0.9 x the share of graduated coins with candles, the test is not answerable
with this source: a pass then does not count (a fail still does, since the gap would favour a pass). The coverage is reported.

## Reported, not judged

- The same plan on the top 1 %.
- Other sales on both sets: sold the minute before completion (cautious), sold at the final curve price (best case), no stop,
  stop 0.7, stop 0.5 with a 2x take, entry at the entry candle's high (worst case).
- For each: trades, the four points, how many graduated while held and what they and the others made, the spread of exit/entry,
  and the primary set's ten best coins.

## What follows from it

Nothing switches on by itself. A pass is reported to the user with the numbers; the next step would be a new month of fresh
launches watched on the curve (a new kind of bot, before the graduation), which needs his explicit yes. A fail closes the lead.

## Run log (no change to the plan)

- Run 1 (26 Oct 09:06 UTC): the probe passed (22 of 30 coins with candles: 11 of 15 graduated, 11 of 15 never graduated; first
  opens at 1.0-3.6 P0, so the prices are in SOL; last highs of the graduated coins at 0.93-1.00 G0, median about 0.996, so G = G0).
  It was stopped at about 09:13 UTC, a minute into the fetch, so that the top 0.1 % is fetched and pushed on its own before the rest of
  the top 1 %; its partial shard files are not used and were not opened.
- Run 2: the same probe, the top 0.1 % in three shards (pushed to rocketscurve as soon as they are in), then the rest of the top 1 %.
