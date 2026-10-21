# Pre-registration: which picks deserve a push to the phone? (fake money only)

Written on 2026-10-21 before the candidates below were split by time. Nothing below may change after the first look; anything
added later is labelled as added later.

## Why

The user: "many bad picks, sometimes an okay one, never a big one", then "just make the best filter that works". The gate review
(research/GATES-2026-10-21.md) found no gate change that finds big winners without many more wipeouts. What is left is to send
fewer, better picks: the bot keeps naming a coin every scan on the page, but the phone only rings for picks that pass a push filter.

## What was already seen (honesty)

Before this was written I saw, over all 310 top picks of the 2h tip record: the average by tier (strong -1.66 per 20 in 33 picks,
weak -3.31, risky -2.11, watch -2.01) and by score (50 or more: -2.23 in 158), and the Time Machine's calibration in five bins
over 363 tips (its lowest fifth: 3% forecast, 1% in profit). So the halves below are not clean; the deciding test is forward.

## Data

The 2h tip record (branch "results", db/memerec, rule m9-2h): each scan's first pick with its tier, score, trained up and zp and
its horizon result (eur per 20 after fees, gone). The Time Machine's profit forecast per tip from research/check_timemachine.py
(the pre-registered forecast, unchanged). Fit: tips before 2026-10-16 00:00 UTC. Check: tips from then on.

## Candidates (fixed now, nothing else is tried)

1. tier is strong
2. score at least S, S from {48, 50, 52} chosen on the fit part
3. trained up at least its median on the fit part
4. Time Machine profit forecast at least Q, Q the fit part's 40th, 50th or 60th percentile (chosen on the fit part)
5. 1 and 4 together is not a candidate (too few picks)

A candidate is chosen on the fit part by its average per 20 among the picks it lets through, with at least 25% of the fit
tips let through.

## Decision on the check part

The chosen candidate goes live as the push filter if on the check part: its pushed picks average better per 20 than all picks,
it lets at least 15% of the picks through, and its pushed picks go to zero at most as often (share) as all picks.

Whatever goes live is judged again forward on the tips of 22 October to 4 November 2026 with the same three conditions; if it
fails there, it is switched off. If no candidate passes, pushes stay as they are and the user is told so.
