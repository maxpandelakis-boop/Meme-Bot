# Pre-registration: what do the 10x coins depend on? (24 Oct 2026, fake money only, research only)

Written before any outcome was split by any of the facts below. Seen before writing: the number of graduations, rockets and
zeros per window and entry minute (no split), and the spread of the launch facts in history2 (no outcome). Nothing found here is
built into the Pick, the Radar or the Learning Pick; that needs the user's own yes.

## The question

The user (24 Oct, 08:10 UTC): keep going until it is clear what the rockets depend on. Meant: which facts, known at the moment one
could still buy, separate the coins that go 10x from the ones that go to zero, and is any of them good enough to buy on.

## What is already done and is not repeated

Chart and activity rules (213k grid, ~1.5 million rules over five windows, PR #42), the Radar's model with wallet memory (wallets
with earlier 3x wins), earlier entry at 5-20 minutes, 134 exit rules, the AI exit, smart wallets and KOL copying, dev/holder
factors (RugCheck, Jupiter, creator sold), social signals the bot logs, pump.fun comments, 18 call-group variants. All failed.
This study only uses facts none of those used at scale: who launched the coin and how, what it is called, and when.

## Data

Every pump.fun graduation with a start SOL side of 10 or more in the five windows of PR #42: w1 25 Apr-24 May, w2 25 Jun-24 Jul
(GeckoTerminal candles), w3 10 Aug-9 Sep, w4 10 Sep-8 Oct (history2, from every swap), w5 9-21 Oct (GeckoTerminal). Five-minute
USD candles of the first 48 hours (branches monthsdata, monthsh2). Launch facts: history2's create records (ticker, name, creator,
creation time) for w3/w4; pump.fun's public coin data for all windows (research/rockets/meta_fetch.py, branch rocketsmeta), if it
answers from GitHub's runners.

## Entries and outcomes

- Entry at E = 5 and E = 30 minutes after the graduation, at the close of the last five-minute candle closed before then; one
  entry per coin and E. Coins without a trade before the entry are left out. In w3/w4 an entry whose hour before or six hours
  after touches a recorder outage of 10 minutes or more is left out (as PR #42).
- rocket = a five-minute close at 10x the entry price or more within 24 hours. zero = the close 24 hours after the entry at 0.1x
  or less. Closes only, no wicks.
- Money: a 20 EUR paper ticket with the Radar's paper fees (0.81 EUR in, 0.5 % but at least 0.81 EUR out), on five-minute
  closes, three sell rules fixed now: S1 no stop / 10x / 24 h (wait for the rocket), S2 -50 % / 10x / 24 h, S3 -30 % / 11x / 6 h
  (the bots' rule K). A stop fills at the close that crosses it or the stop price, whichever is lower; a target at the target.
  Cost allowance 0.60 EUR per trade (3 points at 20 EUR, PREREG-REVIEW-2026-11-04.md).

## The facts tested (each known at the entry, buckets fixed now)

| # | fact | buckets |
|---|---|---|
| F1 | creator's earlier graduations (same creator wallet, in our data, within the 30 days before) | 0 / 1-2 / 3-9 / 10+ |
| F2 | creator had an earlier rocket (an earlier graduation, at least 24 h 5 min before, that was a rocket at E = 5) | yes / no |
| F3 | bonding curve time: minutes from creation to graduation | up to 1 / 1-10 / 10-60 / 60-360 / over 360 |
| F4 | copycat ticker: earlier graduations with the same ticker (upper case, trimmed) in the 7 days before | 0 / 1-2 / 3-9 / 10+ |
| F5 | ticker or name in Chinese, Japanese or Korean script | yes / no |
| F6 | hour of the graduation, UTC | 0-6 / 6-12 / 12-18 / 18-24 |
| F7 | weekend (Saturday or Sunday, UTC) | yes / no |
| F8 | crowding: graduations in the 24 hours before | terciles of the fit windows |
| F9 | SOL/USD change over the 24 hours before the entry (Binance hourly closes) | terciles of the fit windows |
| F10 | links set at launch (pump.fun data: X, Telegram, website) | 0 / 1 / 2 / 3 links |
| F11 | the X link points to a single post (status) / a profile or community / none | three groups |

F1-F4 count only graduations inside the five windows, so creators and tickers active in the missing months are undercounted at the
start of w1, w2 and w3. F10/F11 only if pump.fun answers; F1-F5 for w1/w2/w5 only from pump.fun as well.

## Split

Fit windows w1, w2, w3; unseen windows w4 + w5 (10 Sep-21 Oct). A fact only available in w3/w4(/w5) is fit on
w3 and judged on w4 (+ w5 where available). Nothing from w4/w5 is used to choose a bucket, a cut, a sell rule or a model.

## Part A: does the fact move the odds of a rocket?

For each fact and E: on the fit windows the bucket with the highest rocket rate among buckets with at least 200 entries is the
favoured bucket. On the unseen windows its rocket rate is compared with all other entries (one-sided two-proportion z test in the
direction found on the fit windows). Holm over all fact x E pairs at 5 %. The same for the zero rate (favoured = lowest zero rate).
A fact "explains rockets" only if it passes Holm on the unseen windows; its size is reported as the rate ratio with a 95 % interval
(bootstrap over days).

## Part B: can one make money with it?

For each fact and E: on the fit windows the bucket x sell rule with the highest mean per trade (at least 200 entries) is the
candidate. On the unseen windows it holds only if all of: at least 40 trades; mean after the 0.60 EUR allowance above 0; the 1 %
one-sided bootstrap lower bound (20,000 draws over trades), divided by the number of candidates (Bonferroni), above 0; still above
0 without its single best trade.

## Part C: all facts together

A LightGBM classifier (fixed settings: 200 trees, learning rate 0.05, 31 leaves, minimum 50 rows per leaf, seed 7) on all facts of
F1-F11 that exist in the windows used, trained on the fit windows to predict a rocket, separately for E = 5 and E = 30. Reported:
the AUC on the unseen windows (does it explain rockets at all), and the money of its top 1 %, 2 % and 5 % on the unseen windows
(cuts from the fit windows' score distribution) under S1-S3, judged by the Part B test with Bonferroni over the 18 candidates.

## Also reported (description, no test)

Every rocket at E = 5 and E = 30 as a list (window, time, ticker, market cap at entry, peak multiple, minutes to 10x, lowest point
before, close after 24 h), and how the rockets differ from the other coins on the facts above.

## If nothing holds

Say so plainly, and name what it would take: data that costs money or a login (bundle and sniper detection per launch from paid
RPC credits, X engagement from the paid X API, Telegram calls with the user's own key, wallet labels from Nansen/Arkham-type
services).

## Amendment 1 (24 Oct, ~08:30 UTC, before any fact result was read)

Checking the rocket list (no split by any fact) showed "rockets" of 400x to 5,800x from a market cap of $1,400-7,700: pools that
were sold down to well under 1 SOL, where a buy of a few hundred dollars makes a 10x and a 20 EUR ticket would move the price
itself. So every entry also needs a pool liquidity of at least $10,000 at the entry (two times the SOL side, from the start
reserves and the price, SOL/USD from Binance, as research/check_months.py). With it: E = 5 50,683 entries, 1,089 rockets (2.15 %);
E = 30 28,279 entries, 423 rockets (1.5 %). The result of a shuffled-outcome null run (no information) was looked at to check the
code; one run with the real outcomes and history2's facts only was made and deleted unread.
