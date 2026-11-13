# Copy trading, round 2: is any version profitable? Pre-registration (fake money only)

Written on 2026-11-13 before any number of this round was computed. Maxim's order (13 Nov): keep trying until the results are
like the video's (a SIM account copying three FOMO traders 30 s late, "130 $ to 8,603 $ in one night"), and use as many
possibilities as possible. Round 1 (WALLETS-2026-11-11.md) lost with every list at a 30 s delay and 20 $ tickets.

A wide search finds something that looks good on the days it was searched on, by chance alone. So: search wide on the dev days,
name the finalists by a fixed rule, judge them once on the hidden days. Honest numbers either way; real money stays off.

## Data and days

As round 1: every pump.fun curve trade, launch days 10 Aug to 6 Oct 2026 (4 to 7 Sep out). Search days (dev): 2 to 19 Sep.
Hidden days: 20 Sep to 6 Oct. Round 1 already looked at three lists on the hidden days; nothing from those numbers is used to
choose anything here (the grid below is fixed now, the finalists come from the dev days only).

## The levers (all combined: 7,680 cells)

- **Delay** between the wallet's trade and ours: 1, 2, 5, 30 seconds (buy and sell). 1 s is the best case for an own fast bot
  and not possible through FOMO's app; it is shown but cannot become a finalist.
- **Ticket and fee:** FOMO fee tiers with 20, 50, 100 or 200 $ per buy (the fee falls from 2% to about 0.5% a side), and a
  Jupiter-like swap (no platform fee, 0.05 $ network a trade) with 20 or 100 $. New: the own trade's price impact on the curve
  is charged (buy at spot x (1 + ticket/pool), sell the same way), on top of the 1% a side as before.
- **Wallet list** (rebuilt for every test day from earlier launch days only, 2-day lag as in round 1; ranked on the copier's
  return at the same delay, mirror exit, before fees):
  S1 at least 10 events, average above 0, t at least 2, top 300 by t. S2 at least 20 events, t at least 3, top 100.
  S3 "slow": at least 10 events, at least half of its sells 60 s or more after the buy, average above 0, top 100 by average.
  S4 "big": at least 10 events, average first buy 1 SOL or more, average above 0, top 100 by average.
  S5 "winners, no bots": own profit on half its coins or more, half of its sells 60 s or later, top 300 by own profit.
- **List window:** 21 or 7 launch days.
- **Exit:** mirror (sell when the wallet sells, or 10x, 24 h); mirror with +50% take profit and -20% stop; mirror with +100%
  and -30%; hold 24 h or to the graduation.
- **Entry filter:** none; coin age under 2 min, 2 to 15 min, over 15 min; market cap under 10K, 10K to 30K, over 30K $;
  "two agree" (the second listed wallet in the coin).

Each cell buys a coin once (the first event that passes). Per cell: trades, average per trade in $ and in % of the ticket, 95%
bootstrap interval by launch day, days in profit.

## Finalists (fixed rule, from the dev days only)

Cells with a delay of 2 s or more, at least 150 dev trades and a dev interval above 0, ranked by the interval's lower bound in %
of the ticket. Finalists: the best FOMO-fee cell, the best Jupiter-fee cell, then the next best cells that differ from the
chosen ones in list or exit, five in all. If fewer than five qualify, the list is filled with the best dev averages (150+
trades) and marked "did not qualify".

## Judgement on the hidden days (once)

A finalist PASSES only if: at least 100 trades; average above 0; the 99% bootstrap interval by day above 0 (five finalists, so
a stricter interval); above 0 without the best trade and without the best wallet; better than a random wallet's event under the
same delay, fee and exit. A pass on the hidden days after a dev pass is a real lead and goes to a live paper run before
anything else; it is not yet the video's result. Reported with it: what 130 $ would have become over the hidden days with the
cell's trades (40% of the cash per trade, at most 2 open, as in the videos), for passes only.

## Also looked at (information)

- The three traders shown in the video (joecroskey, Ekonomeest, bronbroncore): if their wallet addresses can be found, their
  events in these data and what a copy 30 s late would have made.
- The best the grid has at a 1 s delay.

## Limits

Bonding curve only. A 2 s copy needs an own program listening to the chain, not FOMO's copy button. The price impact model is
the curve's own formula; it ignores other traders reacting to our trade.
