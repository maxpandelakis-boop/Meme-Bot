# Pre-registration: the big search for better coin choice (fake money only)

Written on 2026-10-28 at about 14:05 UTC, before any candle, launch fact or wallet of a graduation after 21 Oct 2026 was fetched
or looked at. Nothing below may change after the first look at the sealed data; anything added later is labelled as an
amendment with its time. Research only: nothing is built into the bots, no live rule, account or shadow changes, nothing is
switched on from it.

## Why

The user (28 Oct 13:48-13:52 UTC): "ich will trotzdem dass du alles besser machst so dass die bots bessere coins picken, hör
nicht auf bis du das geschafft hast, wenn's 1 Billion Regeln braucht, teste alles", "teste wirklich alles was geht ohne
Einschränkung", "guck dir Wallets an, geh auf Twitter-Accounts, alles was geht, wirklich jede Variable". He was told before that
every earlier search failed on unseen data (PR #42 ~1.5 M rules over five windows, PR #57 rocket separator, PR #59 big-exchange
memes, councils, ML exits) and that searching longer finds more luck, not more edge.

So the search is as broad as the compute allows, and the one limit that stays is the sealed data: it is fetched only after this
file is pushed, and judged once.

## Which data is still unseen

w5 (9-21 Oct) is NOT sealed any more: PR #42 judged its walk-forward picks on it, PR #57 chose the 12 PREREG-NOV rules partly on it
(positive on w5 was one of their conditions), and the Rocket seeker's backtest scored it. Using it as a holdout again would be
dishonest. The only data no search has touched are the graduations from 22 Oct 2026 on. Therefore:

| part | graduations | role |
|---|---|---|
| w1 | 25 Apr - 24 May 2026 | fit (GeckoTerminal 5-min candles, branch monthsdata) |
| w2 | 25 Jun - 24 Jul 2026 | fit (same) |
| w3 | 10 Aug - 9 Sep 2026 | fit (history2 as 5-min candles, branch monthsh2) |
| w4 | 10 Sep - 8 Oct 2026 | fit (same) |
| w5 | 9 - 21 Oct 2026 | fit (GeckoTerminal, branch monthsdata) |
| **S1** | **22 Oct 00:00 - 26 Oct 12:00 UTC** | **sealed, judged once in this thread** (every coin has its 48 h of candles by 28 Oct 12:00 UTC) |
| **S2** | **22 Oct 00:00 - 21 Nov 23:59 UTC** | **sealed, the full unseen month** (the user's own bar of 24 Oct), built from 24 Nov |

The coordinator's note suggested fit up to 8 Oct and sealed from 9 Oct; for the reason above, w5 is fit data here and the sealed
part starts 22 Oct. The live bots traded in S1 and their results were seen, but no rule search, no model fit and no rule choice
has used S1 data.

S1 is built exactly like w5 by research/bigsearch/bs_fetch.py and .github/workflows/bigsearch-data.yml on this branch (pushed
after this file): the graduation list (pump.fun migration account 39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg, Helius if its free
key answers, else the public Solana RPC) from 21 Oct 00:00 UTC (the day before, for the 24 h counts) to the fetch time; start SOL
side >= 10; GeckoTerminal 5-minute USD candles of the first 48 h (research/months_fetch.py shard, unchanged); the launch facts from
the chain and the metadata files (research/rockets/meta_chain.py shard, unchanged); Wikipedia's top articles of 20-27 Oct
(meta_chain.py wiki); Binance SOL/BTC by hour. The data go to branch `bigsearchdata`. Coverage is reported (graduations per day
against 9-21 Oct's ~1,000, candles found, launch facts found); if candles are missing for more than 15 % of S1's coins, the
judgement says so next to the result.

## The four buy families (one entry per coin: the first entry time at which the rule holds)

Entries and money as research/check_months.py (PR #42): the entry price is the last 5-minute close before the entry time, the
outcome comes from the closes after it, gaps flagged as there.

| family | universe at the entry | entries | money |
|---|---|---|---|
| P (Pick) | the Pick's gates: 6-24 h old, mc $100k-2M, liq >= $15k, 24 h vol >= $15k, the crash/pump blocks, vol/mc <= 8 | hourly | 50 EUR, Pick fees, allowance 0.75 EUR |
| U (wide) | liq >= $15k, 24 h vol >= $15k, mc >= $50k, 1-24 h old | hourly | 50 EUR, Pick fees, allowance 0.75 EUR |
| R (Radar) | up to 12 h old, liq >= $15k, vol >= $15k, mc $100k-5M, 1 h > -10 %, 6 h > -50 % | every 30 min | 20 EUR, Radar fees, allowance 0.60 EUR |
| S (seeker-style) | every graduation with liq >= $10k at 30 or 60 min after the graduation | 30, 60 min | 20 EUR, Radar fees, allowance 0.60 EUR |

## Every variable we have (and what is not testable for free)

Testable on fit and on S1 (allowed in sealed candidates):
- Chart (at the entry, closed candles only): the 17 of PR #42 (age, log mc, liq/mc, vol/mc, last hour's volume share, 5 min /
  1 h / 6 h / 24 h / since-graduation change, distance from the high, hours since the high, 1 h volatility, active candles in the
  last hour, minutes since the last trade, log last-hour volume, share of rising candles) plus 6 more: 30 min change, last hour's
  volume against the hour before, rise from the low since the graduation, share of 5-min candles with a trade since the
  graduation, the first 30 minutes' change and their high (as multiples of the first price).
- Launch facts (PR #55, research/rockets/check_rockets.py launch_facts + media_facts): minutes on the bonding curve, the creator's
  graduations in the 30 days before, same ticker in the 7 days before, Chinese/Japanese/Korean name, graduations in the 24 h
  before, number of links, X link type (none / a post / a profile or community), the X post's age at the launch (from the post id),
  graduations of the 24 h before sharing a name word, picture reused, launched outside pump.fun's page, video, description length,
  name in the day before's top Wikipedia articles.
- Time and market: hour of the entry (UTC), weekend, SOL 1 h and 24 h change, BTC 24 h change.

Searched on fit data only, NOT allowed in sealed candidates (reported as exploration):
- Wallets (w3/w4 only, branch wallets: 20 M wallet-coin pairs from the HF swaps): buyers of >= 0.1 SOL before the entry, their SOL,
  share of first-time wallets, whales (>= 5 SOL first buy), "smart" buyers (3+ earlier coins whose 48 h ended before this coin's
  graduation, mean ROI > 1), the 57 KOL wallets of PR #17. Searched w3 -> w4 (the only two months with wallets). A sealed test
  would need every swap of S1's coins: the free Helius key was used up on 24 Oct and the public RPC cannot page that many swaps;
  the live bots do not keep wallet histories. Said now: a wallet rule that looks good can only be "a lead, not testable for free".
- Pictures (PR #55 CLIP groups, animated, look-alike, name fit; w1-w5 where read): needs the CLIP run on S1's pictures; searched
  walk-forward on fit data only.

Not testable at all for free, named in the report with cost: X followers, likes, views (X API, paid; today's numbers would also
leak which coins rose), Telegram (needs the user's own API key), pump.fun replies (need a login, PR #35), bundles/snipers/every
curve trade (paid RPC/Dune/Bitquery).

## The rules searched

Conditions: per numeric variable, thresholds at its 10/20/30/50 % quantiles ("at most") and 50/70/80/90 % quantiles ("at
least") over the family's w1-w5 rows (no outcomes used); per category variable each level. Missing values never pass.

Filters: the base (no condition), every single condition, every pair of conditions on two different variables, and triples by
beam: the 2,000 best pairs of each family (by the ROBUST score below on w1-w5) each extended by every condition of a third
variable.

Sell rules: the 222 of check_months.py (stop none/10/20/30/50/70 %, target 1.2/1.5/2/3/5/11x/none, 1/2/6/12/24 h; trailing
20/30/50 % over 6/12/24 h; three half-sale rules) plus three Rocket holds on the 5-min closes (0.5x floor, after 2x sell at 0.6x
the best, 24 h; 0.7x / 1.5x / 0.7x; 0.5x / 3x / 0.5x) = 225.

Models: LightGBM per family on all S1-allowed variables, targets = money under rule K, rule A, the family's best base sell rule
and the first Rocket hold; cuts at the top 1 / 2 / 5 / 10 % of the fit scores.

The report states the exact count of (filter, sell rule) pairs and models evaluated.

## Walk-forward (to measure, not to choose)

Steps: fit w1-w2 -> test w3; fit w1-w3 -> test w4; fit w1-w4 -> test w5. For each family and picker: the picked rule's result on
the test window; the share of the top 100 rules positive on the test window against all rules; LightGBM: every (target, cut)
on the three test windows. This shows whether being best on old months carries over at all.

## The sealed candidates (chosen on w1-w5, frozen and pushed before S1 is read)

Per family:
- ROBUST: the (filter, sell rule) with the highest worst-window mean after the allowance, among those with >= 30 trades in each
  of w1-w5.
- SHRUNK: the highest pooled mean after the allowance minus 2 standard errors, among those with >= 100 trades in w1-w5.
- ROBUST-FREQ and SHRUNK-FREQ: the same among rules with >= 8 trades a day in every fit window (so that S1's 4.5 days can reach
  40 trades). Empty if no rule qualifies.
- ML: the LightGBM (target, cut) with the best mean over the three walk-forward test windows, refit on w1-w5, its cut frozen as
  that quantile of its w1-w5 scores, sold by its target's sell rule.

At most 20 candidates (K = their number). They are written with every threshold and sell rule to
research/bigsearch/CANDIDATES-2026-10-28.json and pushed before S1's data are read.

## The bar (research/PREREG-REVIEW-2026-11-04.md, PR #39) and the judgement

A candidate HOLDS on S1 if all four: (1) >= 40 trades; (2) mean per trade after the allowance > 0; (3) the one-sided bootstrap
lower bound at 1 % / K (Bonferroni over the candidates; 20,000 draws) > 0; (4) the total after the allowance without its single
best trade > 0. Holm at 5 % over the K bootstrap p-values is reported too. A candidate with fewer than 40 S1 trades fails point
1 on S1 and is judged on S2 only.

S1 is judged once, by `python3 research/bigsearch/bs_search.py judge`, and the result is reported as it comes out. The best rule
in hindsight on S1 is reported only as the size of luck. Nothing is re-picked after the look.

S2 (the full unseen month, from 24 Nov): every candidate again, the same bar. A rule that holds on S1 must also hold on S2
before it is even offered as a shadow rule; any live use needs the user's explicit yes (a Pick rule change restarts the paper
account; changes are frozen until the 4 Nov review).

## Said now, before the result

Expected: nothing holds. Every earlier search on these windows failed on unseen data (PR #42: 19 of 24 walk-forward picks lost on
the next window; 0 Holm survivors). S1 is short: a rule with ~10 trades a day and the usual spread (about 30-47 EUR per 50 EUR
trade) needs a mean of roughly +8-12 EUR per trade to clear point 3, so a small true edge would also fail. A fail therefore
means "no edge big enough to see in 4.5 days", S2 then has about 6x more data. A pass on S1 would be a surprise and still needs S2.

## Amendment, 28 Oct 2026 ~16:55 UTC (before any S1 data was read; the S1 fetch was still running)

The "size of luck" (`bs_search.py luck`) counts only filters with at least 40 S1 trades (the bar's point 1) and also reports how
many of those have a positive best sell rule. The judgement of the 20 frozen candidates is unchanged. The judge and luck code
were dry-run on w5 (fit data, rows relabelled) to check that they run; the candidates' w5 trade counts matched the frozen
fitTrades.

## Amendment, 28 Oct 2026 ~18:30 UTC (S1 data fetched, no S1 price, outcome or rule result looked at)

The coverage check found the S1 graduation list incomplete: the public RPC was asked for transaction version 0 only, and ~14 % of
the migration account's transactions came back as "rpc -32015" (a newer transaction version). Of the 151 graduations of 21 Oct
00:00-06:00 in w5's Helius list, the new list had 123 (81 %); S1 had ~430 graduations a day with start SOL side >= 10 against
559-852 a day in w5. Only counts were looked at (graduations per day, candles found: 1,895 of 1,895 planned pools, launch facts
found). Because the missing graduations are a newer transaction format, not a random sample, S1 is not judged on the incomplete
list: a repair run of .github/workflows/bigsearch-data.yml asks those transactions again with the version the RPC names and adds
candles and launch facts for the new pools. The coverage after the repair (again against w5's 21 Oct 00:00-06:00) is reported
with the result. The candidates, the bar and the one-time judgement are unchanged.
