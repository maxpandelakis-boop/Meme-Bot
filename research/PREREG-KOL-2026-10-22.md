# Pre-registration: copy the known traders (KOLs), the video's "follow a specific investor's disclosed trades" (fake money only)

Written on 2026-10-22 before any outcome of a KOL copy was computed or looked at. Nothing below may change after the first look;
anything added later is labelled as added later. Looked at before writing: only which KOL addresses exist in the wallet table and
how many pairs each has (57 of 62 found, 16,606 pairs), no price, result or outcome column.

## Why this is a new test

The user sent a second video ("Claude becomes an AI trader", TikTok @alex.carterr_, 56 s). Its method: connect Claude to a broker
and to QuiverQuant, which shows insider transactions, politician trades and institutional activity; give it a strategy such as
"watch a specific investor's disclosed trades and check for new activity throughout the day"; Claude compares that with the
portfolio, analyses the trade, sends a recommendation when something changes, keeps checking in a routine, and everything runs on
paper money first.

What the bot already has or has tested:
- routine, push, paper money first: the radar runs every 15 minutes, pushes "Radar 🚀", books paper trades (PR #15, #16)
- "insider transactions": the dev and holder check (research/DEVHOLDER-2026-10-21.md on branch claude/project-thread-t8psn0): no factor holds
- copying wallets chosen by their own past results ("smart wallets", research/WALLETS-2026-10-21.md on branch
  claude/project-thread-8bj1z4): FAILS, -3.90 per 20 on 154 coins; smart-wallet numbers are also inside the rocket hunter already
- "institutional activity" (big buyers, trade sizes): inside the winner/loser study and the rocket hunter (research/winlose/)

Not tested: the video's "politician trades", traders with a public name whose wallets everybody can watch. On Solana these are the
KOLs ("key opinion leaders") that kolscan.io lists with a name and a Twitter account. They are not chosen by this bot from the
data, so the whole history2 period is unseen for them.

## The list (fixed now)

research/kol/kol_wallets.csv: 62 wallets read from the kolscan.io leaderboard on 2026-10-22 at about 12:45 UTC (the views the
page served; the union of three reads). 57 of them are in the history2 wallet table (wallets with 3 or more pairs).

Known bias, in the KOLs' favour: the leaderboard of 22 October ranks traders by their recent profit, and a trader who is still a
listed KOL in late October may have done well before. A FAIL is therefore a strong result; a PASS is only allowed to go into the
radar's paper account as a forward test, never straight into anything else.

## Data

The wallet pairs of branch "wallets" (research/wallet_build.py; 19,950,348 pairs, 50,930 graduated coins, 10 August to 8 October
2026; Slinky21 Pumpfun dataset, CC BY 4.0): one pair = one wallet's first buy of at least 0.1 SOL of a coin within 48 hours after
its graduation (bundled buys left out), and what a copy D minutes later made. history2 hourly rows (branch history2) for the
radar universe and the Pick gates.

## The candidates (three, nothing else is judged)

1. **KOL copy** (the video's method, for the radar account): for every coin, the first KOL pair; the copy buys at the last price
   15 minutes after the KOL's buy (the radar checks every 15 minutes) and sells with rule A (-30% stop on a low, 11x target on a
   high, else after 6 hours; the radar account's rule). One copy per coin.
2. **KOL copy inside the radar's coins**: candidate 1, only the copies where the coin is 30 minutes to 18 hours old at the copy
   and its latest history2 hourly row at or before the copy (at most 60 minutes old) is in rocket.universe: liquidity and 24 h
   volume at least $15k, market cap $100k to $5M, 1 h change above -10%, 6 h change above -50%.
3. **KOL vote on Pick**: the first row per coin that passes the bot's gates (check_history2.bot_gates, as research/winlose/load.py);
   the coins where a KOL pair's buy lies before that row's time. Result: rule A from that row (history2 stop30/tp11/last6), as in load.py.

Copies or rows whose window touches a recorder outage are left out (g6 / gap_pre, gap_6), as in the earlier studies.

## Money

Per 20 after the project's fees, memebot.tip_net (0.5% per side, at least 0.81), not clipped (as the rocket hunter, WINLOSE
addendum 2). Also shown, for information: 2% round trip clipped to -20..60 (the WALLETS convention).

## The test (whole period, coins graduated 10 August to 8 October 2026)

A candidate PASSES when all four hold:
1. at least 100 coins
2. its average per 20 is above 0 and the 1st percentile of 2,000 coin-bootstrap means (seed 7) is above 0 (one-sided 1% per
   candidate, about 3% for the three together)
3. filter_search.simulate (10,000 runs, days drawn again, fee 0.5-2% per side and slippage 0-4% drawn per run): at least 95% of
   the runs in profit
4. the average per 20 is above 0 on both halves (graduated before / from 15 September, the history2 split)

Shown for every candidate: coins, average and interval, in profit of 10, reached 3x, reached 11x (the target), went to zero,
the 10,000 runs, per week. For information only (decides nothing): the base (every coin with a pair, copied at one random pair,
seed 7, same delay and exit), the same KOL coins copied at a random non-KOL pair (does the KOL's timing add anything?), copy
delays 1, 5 and 60 minutes, the second KOL into a coin, exit B and hold, the KOL-free gate coins for candidate 3.

## What follows

- Candidate 1 or 2 passes: before anything is built, the rocket hunter is refit with a KOL number ("KOLs who bought in the last
  hour") added (research/winlose/rocket_model.py, EXTRA); then the radar's paper account, and only that, gets a KOL watch as a
  forward test (live it needs the KOLs' swaps from Helius). Pick's sell rule is never touched.
- Candidate 3 passes: the KOL vote goes into Pick's selection on its own branch, checked by the selftests and the app test.
- None passes: nothing is built; the result goes to research/KOL-2026-10-22.md and the user is told plainly.
