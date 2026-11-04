# Pre-registration: the quick-flip bot (sell after 1-10 minutes when in profit), 4 Nov 2026

Written 4 Nov 2026 ~17:30 UTC and pushed before any rule below was scored. Fake money only; nothing live changes.

The user, 4 Nov 2026 17:01 UTC (thread "Schnellen Verkaufs-Bot nach 2-3 Minuten testen"): "du kannst ja auch ein haben der schon
nach zwei drei minuten verkauft so lang er plus macht und man ihn leicht verfolgen kann".

## What earlier searches covered (checked before writing this)

No earlier test held a coin for less than one hour:

- PR #42 / PR #68 (1.5 M and 1.39 B rules): 222 + 3 sell rules on 5-minute candles, time limits 1/2/6/12/24 h, smallest target
  1.2x, smallest stop 10 %. A 1-5 minute hold cannot even be resolved on 5-minute candles.
- PR #71 live search F1: hours {1, 2, 3, 4, 6, 8, 12}; chart-exit drop windows 15-60 min.
- PR #21 early-exit test: time limits 2/6/12/24 h (its 5-20 minute numbers are the first CHECK after the graduation, not holds).
- PR #46 chart exit (the Sell bot): 6 h limit, 30-minute drop window.

So the 1-10 minute family below is new. Seen before writing it: two shadow paths' first rows while checking the file format
(ヤギ 22 Oct, ANONVOYAGE 4 Nov); no rule result.

## Data

Historical: history2 one-minute bars (branch chartbars; every PumpSwap swap of 0.01 SOL or more of the coins that graduated from
pump.fun 10 Aug - 8 Oct 2026, first 25 h; Slink21 Pumpfun dataset, CC BY 4.0), coins with sol0 >= 10 (real graduations), hourly
rows of branch history2 for the entry filters. A minute without a bar keeps the last close, and its high and low are that close
(no forward-filled wicks, the PR #21 lesson). An entry is dropped when a recorder outage minute (gap_minutes.npy) lies within
5 minutes before to 75 minutes after it, or when the coin had no bar in the 5 minutes up to the entry.

- FIT = graduations before 10 Sep 2026 00:00 UTC (1788998400000) (w3), CHECK = from then to 8 Oct (w4).

Live: the Pick account's real buys since 22 Oct 16:00 UTC with the shadow job's 12-hour minute path (db/memeshadow on branch
results: closes "c", minute highs/lows "w"), and the Learning Pick's buys (db/memelern, closes only, cross-check). The Radar account
🚀 and the Rocket seeker 🔭 keep no minute paths of their trades, so their own buys cannot be replayed minute by minute; the
historical R and G universes stand in for them.

## Entries (one per coin)

| key | who it copies | entry |
|---|---|---|
| G0 | "every graduate", as early as possible | the close of the first full minute on PumpSwap (minute 0) |
| G30 | every graduate 30 min later (Rocket seeker 🔭 timing) | the close of minute 29, liquidity >= $10k |
| P | Pick account candidates | first whole hour 1-23 h after the graduation that passes the Pick's gates (memebot GATE_*: liq >= $20k, mc $100k-50M, 24 h vol >= $20k, 1 h > -40 %, 6 h > -50 %, 24 h > -70 %, 1 h < +150 %, 6 h < +400 %, vol/mc <= 8); the close of the minute before that hour |
| R | Radar account 🚀 candidates | first whole hour 1-12 h with liq >= $15k, 24 h vol >= $15k, mc $100k-5M, 1 h > -10 %, 6 h > -50 % |

## Money (both reported; "plus" always means in profit AFTER all costs)

- Pick money: 50 EUR, 1 % fee per side (at least 0.10 EUR, memebot.paper_fee), allowance 0.75 EUR (1.5 points, PR #39 / PR #68).
  About 3.5 % per round trip; break-even multiple ~1.036.
- Radar money: 20 EUR, fee max(0.5 %, 0.81 EUR) per side (memebot.tip_net), allowance 0.60 EUR (3 points). About 11 % per round
  trip; break-even multiple ~1.116. (This is close to the ~11 % other bot projects measured.)

## Rules (35 per entry and money)

Minute k = the close of the k-th whole minute after the entry. H in {1, 2, 3, 5, 10} minutes.

- T_H: sell at the close of minute H, whatever the price (a pure H-minute hold).
- W_H_s_cap: a stop at -s (s in {10, 20, 30} %) on the minute low, booked at that low, active from minute 1. At minute H: if the close
  is "plus", sell at that close. If not, keep the coin and sell at the first later close that is "plus", or at the stop, or at the
  close of minute cap (cap in {15, 60}).

5 T + 30 W = 35 rules.

## Selection, judgement, luck

Per entry and money (8 cells): the rule with the highest FIT mean per trade after the allowance (>= 100 FIT trades) is frozen into
research/quickflip/FROZEN-2026-11-04.json and committed before CHECK is scored. It is judged once on CHECK by the PR #39 bar:
>= 40 trades, mean after the allowance > 0, 1 % point of 10,000 bootstrap means > 0, total after the allowance > 0 without the
best trade. With 8 frozen candidates about one may pass by luck: a pass is a reason to keep testing on paper, never real money.
Reported with it: every rule's FIT and CHECK mean, the share of the 35 rules above zero on CHECK, the gross multiple (no costs),
the share of trades sold in profit, and the biggest loss.

Live: the frozen P rule (both monies) and all 35 rules on the Pick account's buys, paired against the real booked result of the
same buys; the same on the Learning Pick's paths (closes as lows) as a cross-check. Descriptive only (the live paths are few and
were seen in the 4 Nov review).

## Copying by hand (report only)

A person who copies the bot is later on both legs. Modelled: the copier buys at the close of the minute after the bot's entry and
sells at the close of the minute after the bot's sale. Reported for the frozen rules and the T rules, historical and live.

## What happens with the result

The Pick account, its Sell bot and the Radar account 🚀 stay untouched until the 22 Nov review (user's choice of 4 Nov). If a frozen
rule passes on CHECK and is not negative on the live Pick buys, it is proposed as one more paper test next to the "New rules test 🧪"
(on the Pick's real buys, from the next day on, judged on 22 Nov with the same bar); nothing else is built. Expected: nothing holds
(the average graduate falls after the graduation; 1-10 minute moves are small next to a 3.5-11 % round trip).
