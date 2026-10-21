# Meme-Bot: a paper-trading meme coin analyst

Fake money only. The bot never signs a transaction, never touches a wallet and never buys anything for real. Every two
hours (and on a button press) it scans about 12,000 Solana meme coins from some 850 public lists, searches and social
feeds, gates and scores them, checks the survivors against RugCheck, GoPlus and the creator's wallet, and names the best
coin for the next two hours on a phone-friendly page, with its trained chance of a profit and of going to zero. Every
scan is re-priced two hours later and feeds the training that sets the weights, the zero and profit models and the limits.
The original 24-hour paper-trading mode (a 40-unit fake bankroll, two coins at 20) is still there.

## Quick start

On GitHub nothing has to be installed: the workflow in `.github/workflows/scan.yml` does everything (see "Running it on
GitHub"). Locally it needs Python 3.9+ and nothing else (standard library only).

```bash
python3 selftest.py                 # proves the whole pipeline on a local mock of every API (~3 min)
python3 bot.py cycle --recommend --horizon 2h   # one real cycle: scan, train, name the best coin for the next 2 hours, render the page
python3 bot.py cycle                # one real 24h paper-trading cycle: fetch, score, pick, apply the sell rules
python3 bot.py status               # bankroll, open positions, closed trades
python3 bot.py report               # render mb/report.html, the analysis page
python3 bot.py loop --every 30      # keep cycling every 30 minutes (Ctrl-C to stop)
python3 bot.py loop --every 30 --push   # the same, and push the results to the repository's results branch after each cycle
python3 bot.py loop --every 60 --recommend --push   # recommend mode: each cycle rescans, puts the two best clean coins on the page, buys the top pick and 5 new launches as paper positions
python3 bot.py loop --every 30 --recommend --push --horizon 2h   # 2-hour profile: early, small, accelerating coins, re-priced 2 hours later
python3 bot.py cycle --force        # pick now, ignoring the 3-hour gap and the daily cap (the bankroll still caps it)
python3 bot.py cycle --rescan       # scan the whole universe now and save it for the big test (buys only if a slot is free)
python3 bot.py sell --all           # close every open position by hand at the last price (or --coin SYMBOL); the money returns to the bankroll
python3 bot.py reset                # wipe the history and start again with 40
```

Everything lives in `./mb` (`--dir` changes it): the fetched source files, `pairs.json` (the merged universe), and `db/`
(positions, exits, snapshots, learned weights, state).

## How a cycle works

1. **mode** – `memebot.py mode` says what the run needs: a full scan (every ~12 h, for the 24-hour "big test"), a light
   scan (the bankroll has a free slot and the last pick is more than 3 hours old) or only prices for the open positions.
2. **sources** – `fetch.py sources` pulls the coin universe:
   DexScreener boost / profile / community-takeover / ad lists plus 467 keyword searches (about 30 pairs each) and a
   deep search with 368 more, RugCheck's new / trending / recent / verified lists, GeckoTerminal trending / new / top
   pools and the busiest pools per DEX (with distinct buyers and sellers), CoinGecko trending and its Solana meme-coin
   category, CoinMarketCap top searches and Solana gainers, Jupiter trending / organic / recent / verified tokens
   (holders, organic score, traders), Raydium LaunchLab launches (with creator wallets) and Raydium's and Orca's biggest
   pools, pump.fun top / new / graduated / live coins, GMGN smart-money rankings (usually blocked), Reddit, Farcaster,
   Mastodon and 4chan posts, crypto news and Google News headlines, SOL/BTC and the Fear & Greed index. With
   `LUNARCRUSH_API_KEY` set it also pulls LunarCrush social buzz.
3. **gather** – `memebot.py gather` merges everything into one record per coin and lists the addresses that still need
   full DexScreener pair data; `fetch.py tokens` fetches those 30 at a time, then gather runs again.
4. **shortlist** – the best-scored coins that pass the hard gates get a RugCheck report (16 for the pick, 60 to 120 more
   when a big-test snapshot is due), a GoPlus security check, GeckoTerminal token facts, the creator check (Jupiter +
   Solana RPC), the community data (votes, watchlists, X, Telegram, StockTwits) and, when GMGN answers, their top buyers.
5. **refresh** – the market moves during a 15-minute scan, so `fetch.py refresh` pulls fresh pair data for the
   candidates (shortlist, the 150 best gated coins, the fallback pool) right before the decision; the newest row wins
   in the merge without counting as another pair or source, and the page says when the prices were refreshed.
6. **train** – `memebot.py train` runs the training programs on the scored snapshots (see "Training").
7. **run** – `memebot.py run` applies the sell rules to the open positions, then names or buys the best clean coins,
   writes everything to `out/`, and `bot.py` copies it into `db/`.

### Hard gates (a coin must pass all of them)

price known · not on a launch curve (pump.fun, launchlab, …) · has a real DEX pair · not a GMGN honeypot · not a
tokenized stock / wrapped asset / stablecoin · at least 1 hour old · liquidity ≥ $20k · market cap $100k–$50M ·
≥ $20k traded in 24 h · not a copycat of a bigger coin with the same ticker · not crashed (−40% in 1 h, −50% in 6 h or
−70% in 24 h) · not spiked (+150% in 1 h or +400% in 6 h) · 24 h volume at most 8× the market cap · seen on at least one
source that is not a paid DexScreener list.

### Score

Every number the bot knows about a coin becomes a factor (liquidity / market cap, volume / market cap, buy share, 1h
buy ratio, momentum, how many source lists named it, social buzz, RugCheck facts, news mentions and theme heat,
distinct buyers, CoinGecko trending, smart-wallet record, GMGN trader quality, …). Each factor is percentile-ranked
across the scan and summed with a weight. The weights start from a hand-made prior and are replaced by learned ones:
every full scan snapshots all ~1000 coins, prices them again 24 hours later, and each factor's rank correlation with
that result becomes its weight (fully learned after ~600 scored coins). `python3 memebot.py learn` and `analyze` show
what has been learned so far.

### Safety check before a buy

A coin is only bought when its RugCheck report has no danger flag, no holder / ownership / creator / copycat / rug
warning, at least 50% of the liquidity locked, no single wallet above 20%, the top 10 wallets below 50%, at most 15
insider wallets and at least 300 holders. No report means no buy.

### Bankroll and sell rules

| Rule | Value |
|---|---|
| Bankroll | 40 (fake), never more deployed than that |
| Per position | 20 when 40 is free; below that, two coins of half the free money (at least 15 each), else one |
| Fees (simulated) | 0.5%, minimum 0.81 per trade |
| Take profit | sell half at 2×, sell the rest if it falls back to entry |
| Stop loss | sell everything at −50% |
| Time limit | sell after 3 days |
| Rug | sell at 0 when the price vanishes or liquidity drops below $1k |
| Re-pick | the same coin is not bought again for 7 days |
| Pace | at most one pick run every ~3 h and 4 picks per day |

Money from a sale returns to the bankroll and frees a slot for the next pick run.

## Recommend mode

`--recommend` turns the bot into a scanner: every cycle it rescans the whole universe, applies the same gates and safety
check, and writes the two best coins to the top of the page with embedded DexScreener charts, the facts and the links,
plus the runners-up. Nothing is bought or held. The big test (snapshots scored 24 hours later) keeps running, so the
weights keep learning.

There is always a pick, in one of four tiers, and every pick shows its trained odds (chance of a profit after fees and
chance of going to zero within the horizon, from the bot's own scored snapshots): **strong** (clean, score above the
bar), **weak** (clean, below it), **fallback** (clean, but it failed a soft momentum gate, named with it) and **risky**
(no coin passed the strict check: the coin with the best odds among those that still clear the relaxed 24-hour safety
floor, i.e. a RugCheck report without danger flags, half the liquidity locked, no whale, at least 300 holders, no creator
sale, no authority left, and at least the profile's minimum age; shown with what the strict check objected to and its
odds). When nothing clears even that floor, the page says so and names no coin: a 20-minute-old launch without a report
is never a tip, whatever its odds.

### Always a coin, with its odds

The trained profit chance never vetoes a pick: only about 3% of all candidates end a window in profit after fees, so
an absolute bar would name nothing. A pick whose profit chance is under 20% carries a "low odds · X% profit chance"
chip instead. The zero model still vetoes (a clean coin over the tuned zero limit is skipped).

### Always a coin, never a loss called a pick

When no clean coin passes and no risky coin clears the trained odds, the page still names the safest-looking coin as a
**watch** coin: the chip says "watch only · the odds say a loss", the card shows the odds that stopped it, and the
heading reads "No pick, one coin to watch". It is recorded and priced again like a tip, so the record keeps learning
from it, but it is not a recommendation.

### Hour by hour

Under the pick, "Recommendations, hour by hour" lists every scan of the last two days, newest first: the time, the coin
the bot named (tier, score, the odds it gave at the time) and what 20 in it became 1 hour and 24 hours later (every tip
is priced again at both marks by the runs that follow, on top of the profile's own horizon), or "pending" with the time
it is priced again, or "no coin" with the reason. The header says when the next scheduled scan
starts (minute 10 UTC every hour, started through the GitHub API by the hourly routine of the Claude session, because
GitHub's own cron scheduler starts a run 10 to 20 minutes late; the cron in `scan.yml` at :25 is only the safety net
and does nothing when a scan started in the last 45 minutes; a run takes about 20 minutes). A run in which DexScreener
priced under 300 coins is an outage: it postpones every due price check to the next run instead of counting a tip
it cannot price as gone (the note says "Tip checks postponed"). A 1 h or 24 h check that is more than 1.5 hours late
(a missed run, an outage, the backfill after a code change) is not priced at the price of the day either: the window's
minute candles price it (the last close inside the window; the cell says "from candles"), and until the candles are
there the check stays open, for two days at most, after which it reads "not priced". A check that an older version
had priced hours late is treated as open and priced again from the candles.

### The paper account (recommend mode)

The tips are a forecast record: every tip counts a fresh 20 for each window (1 h, the horizon, 24 h), and a coin named
in 15 runs in a row counts 15 times, fees and all. What a trader would have done is buy and hold. So recommend mode also
keeps a paper account, with fake money and no budget (rule v2, `PAPER_RULE`, agreed on 2026-10-10). Every scan buys:

* **the top pick** for 50 (`TOP_TICKET`, `grp: "hold"` in `db/memepos`): the first recommendation, whatever its tier
  (strong, weak, fallback or risky; a watch coin is never bought). The second recommendation stays a tip.
* **the first 5 new launches** for 3 each (`YOUNG_TICKET`, `YOUNG_BUY_N`, `grp: "young"`): the first five coins of the
  "New launches <1h" tab, in the order shown. A held one is skipped; no other coin takes its place. This ends at the switch,
  16 Oct 2026 00:00 UTC (`memebot.SWITCH_AT`, read through `memebot.switch_at()`): from then on no new launch is listed or
  bought and the spotter stays off; the account goes on unchanged (`PAPER_RULE` is its identity key and is never edited), and
  the launch radar's greens take the new launches' place (rule 2 of the radar account below).

A coin with an open paper position (either group) is not bought again; the card and the tab say "already held". Once it is
sold it may be bought again the next time it is named. Every position is sold, all of it, by the first of:

* **take-profit +1000%** (`HOLD_TP`): the first minute candle of its pool that closes at 11 times the entry, booked at
  exactly 11x the entry price at that minute (`at`). The next run reads the pool's minute candles since the last check
  (`candles/<pool>_hold.txt`); the rise is measured on GeckoTerminal's own price at the entry minute (`cpx` in `marks.json`),
  so the gap between DexScreener's entry price and the candles cannot book a sale that never happened. Closes, not wicks;
  a close over 30x is a glitch.
* **stop-loss -30%** (`HOLD_STOP`): the first minute candle that closes at 70% of `cpx` or lower, booked at that close
  (a crash through the level fills worse, never better). Whichever of the two levels closes first wins. A run without
  new candles for the coin checks both levels on its own DexScreener price (any price at 11x or more is a take-profit,
  booked at 11x: the 30x glitch guard is for candles only).
* **time**: the first scan after about 6 hours (`HOLD_MAX_H`, counted from 15 minutes before, like the tip checks), at its price.
* **a rug**: no price in two runs in a row, or the pool's liquidity under $1,000 (sold at 0).

Failing a filter sells nothing any more. Paper trades pay 1% per trade, at least 0.10 (`PAPER_FEE_PCT`, `PAPER_FEE_MIN`);
the tip record, the big test and the training keep 0.5%, at least 0.81, so their history stays comparable. The candles of
every open position are fetched each hour, held coins first (up to 60 pools, beside the scan).

The account restarted from zero with v2: the first run that finds another `paperRule` in `state.json` closes every
position the old rule still held at that run's price (without one, at its last marked price; 0 only when it never had
one; why `reset`, old fees) and writes `paperSince`; from then on the page's
account (invested, returned, open value, profit/loss, the curve from `memecurve` "paper") counts only positions bought at or
after it, and the older trades sit behind a fold "Before the restart". Nothing is deleted, and the restart happens once.
Each closed-trades fold counts its trades by reason and lists the newest 100.

### Is the bot making money?

The last section of the page answers that in one line: every coin the bot named, priced again 1 hour later (and at the
profile's horizon and 24 hours later), summed up as fake money with 20 in each tip after fees: how many went up, how many
went to zero, the total on the money staked and the average per 20, plus what the +20% take-profit would have made
(sold the first minute a candle closed at +20% after the entry price, else held) and a line per window that sets every
take-profit level (+10%, +20%, +30%, +50%) against holding on the same tips.
A chart draws the running total tip by tip against the break-even line, and the summary of each run carries the same
verdict ("Is the bot making money? No, not so far: ...").

### On-chain flow without Bitquery

For the shortlisted coins (about 20 a scan) the bot reads the last hour's trading straight from the chain through the
public Solana RPC (`fetch.py rpc_flow`): the pool's latest 100 signatures give the swap rate, and 10 of the last hour's
successful swaps, spread over it, are decoded. The pool's vault decides: the account whose coin and quote balances moved
in opposite directions is the pool, the pool giving coins is a buy, the size is what crossed its quote vault (SOL at the
run's CoinGecko price, USDC/USDT/USD1 at 1), and a deposit or withdrawal that moves both the same way is not a trade; the
trader is the wallet that received or gave the coins, even when a relayer paid the fee. `fl/<stamp>.txt` holds the swap
rate, the distinct buyers and sellers in the sample, the share of wallets that both bought and sold, the biggest buyer's
share of the buying, buying and selling in USD, the quote token and the buyer wallets. They become the factors `fl.*` and
a sentence in the why text; the buyers are stored with the coin (`flb`) apart from the holders behind the wallet factors.
The `fl.*` factors are measure-only (`MEASURE_ONLY`): no prior and no learned weight, because the 2026-10-08 study found
nothing in price and volume that tells a coin about to rise from one about to crash, and the weekly study decides whether
the wallet sample does before it moves a pick. It is a sample, capped at 150 seconds a run; with a Bitquery token the
`bq.*` factors read every trade.

### Minute paths for exit rules

Every 1 h, 24 h and horizon result priced from candles also keeps its window's candles relative to the entry price, oldest first
(`path`: minutes after the tip, open, high, low, close; glitch wicks replaced by the close, as for the peak; `cv: 2`).
GeckoTerminal sends the newest candle first; until 2026-10-08 13:10 UTC nothing sorted them, so the "last close" of a late
check was the window's first close. Late checks priced that way are priced again by the next run. `research/check_exits.py` replays take-profit,
stop-loss and trailing-stop rules on them for the tips and the new launches, so "sell at +20%, stop at -20%" and the
like are measured on the bot's own coins rather than argued about.

### Peaks and the take-profit (selling early)

For every tip and every listed new launch, the next runs also fetch the minute candles of its pool (GeckoTerminal
OHLCV, `candles/<pool>_<key>.txt`, key `1`, `24` or `out`) for the 1 h, 24 h and horizon windows (the horizon window
runs up to the run that prices it), so each result carries the peak and the trough inside the window (`hi`, `lo`).

The bot looks once an hour, so it cannot sell in between; the candles replay the sale instead (paper only). For every
level in `TP_LEVELS` (+10%, +20%, +30%, +50%) a result gets `tpx` (what 20 made, after fees) and `tpMin` (the minute
after the tip it sold): sold at exactly the level the first minute a candle **closed** there, else held to the check.
Two rules keep it honest. Closes, not highs: one wick in a thin pool is no sale. And only candles after the entry price
count: the tip's price is refreshed 15 to 30 minutes after the scan starts (`pricedAt` with each tip; older tips take the
minutes from their run's note), and a rise before that was nobody's profit. Results priced before this existed get the
replay from their stored path. The page's headline is `TP_RULE` (+20%): "peak 1.6x · sold at +20% after 23 min: +2.22"
next to the plain result, the verdict, a tile, a column and a chart line; the "Is the bot making money?" section adds a
line per window with every level against holding on the same tips, so the record shows which level pays. After the fees
(0.81 a trade at 20) +10% leaves about +0.30, +20% about +2.22, +30% about +4.14 and +50% about +7.98 per 20. The first
version (`tp`: sold at +50% when a candle *high* reached it, from the scan start) stays in the data.

### New launches tab

The page has two tabs. "The pick" is the recommendation. "New launches <1h" lists every coin under an hour old (each listed coin is recorded in `db/memeyoung` and priced again
at 1 h and 24 h, shown under "What the earlier new launches did") that had
a DEX pair and at least $5k of liquidity at the scan, best score first, with the same trained odds, safety report and
numbers as the pick (`young` in `db/memebot/recommend.json`). These coins are shown, never picked: the 2h profile picks
from coins 6 to 24 hours old, and the training's age record (`ages` in `db/memebot/train.json`, shown at the top of the
tab) says how coins of each age did after the horizon, so the question "do the newest coins do better?" is answered by
the record, not by a hunch. The RugCheck/GoPlus reports for them are fetched with the shortlist.

### Early list on the New launches tab

Fake money, not advice. A full scan takes about 26 minutes, so the scored list above shows coins that were found about 22
minutes before the page came out. The early list closes that gap inside the scan: about 5 minutes after each hourly scan
starts, the New launches tab on the website (keep it open, or open it with `#new` at the end of the address) shows the coins under
an hour old that the scan's sources found, newest first (a switch sorts them in score order). RugCheck's words follow about half a
minute later. Each card says how old the DexScreener pair is (for a pump.fun coin that is the time since it graduated) and, when
pump.fun or LaunchLab gives it, how old the token itself is, with links to DexScreener, RugCheck, Solscan, Birdeye, GMGN, pump.fun
and X. There is never a swap link.

How it works: right after the sources step, `bot.py` starts `radar.py early` (the "Launch spotter" in the Agent office) in the
background, next to the price desk. It copies the sources' files into `mb/radar/in`, asks DexScreener for the addresses the keyword
searches did not price (about 31 requests, 0.6 s apart, at most 45), runs memebot's own gather, scan and new-launches filter on that
copy with the ages measured at its own clock, and writes `mb/young_early.json`. The live view pushes it within seconds (as `young` in
`live.json`), then once more with the RugCheck reports (at most 20 coins, 45 seconds at most). The page reads it through the same
poll as the Agent office: while one of the two tabs is open it asks every 75 seconds from 2 minutes before a scheduled start until
35 minutes after it, or until that scan's last push is in. With the iPhone app set up (below), the same list also goes to the app's
live store (`live_put("young", doc)`: one live record for both), the app reads it from there within seconds, and the first listed
list of each scan sends one "new coins" notification.

The early list is not the scored list:
- It is not scored by the full scan: no deep search, no creator check, no on-chain sample, no smart-wallet or zero model, and
  "copy" is judged on a smaller universe. Its score uses the last scan's weights and is comparable only within the list.
- It is only partly safety-checked: RugCheck only. A clean report reads "RugCheck: no danger flags", never "safe".
- The paper account does not buy from it. The trader still buys the first 5 coins of the scored list at about minute 22, at the
  refreshed price, exactly as before; the early list changes no buy, no tip and no record (`PAPER_RULE` is unchanged).
- Its coins can differ from the scored list's. A coin born after the scan started is never on the scored list (that list only takes
  coins older than the scan), and some coins fall under the liquidity floor, lose their price or fail a gate by the trader step.
  After the scan the early list stays folded above the scored one, and each card says whether its coin made the scored list
  (and was bought for 3 €) or why not.

It removes the delay inside the scan, not the hourly rhythm: a coin created right after a scan's sources step is first seen by the
next scan.

Requests: about 31 DexScreener requests a scan (about 10% more than before), at most 20 RugCheck reports, and one DexScreener request
after the trader. The spotter stops at the first DexScreener rate limit (429) without waiting, so the price desk, which shares the
runner's address, keeps its budget; it never calls Jupiter, GeckoTerminal, pump.fun, the Solana RPC or GoPlus. It runs beside the
desk, so the scan takes no longer; if it is still at work when the trader starts, or when the scan stops early, it is stopped there.
A failed spotter costs only the early list. It tries a request at most twice and only when no answer came at all, waits its 0.6 s
after error answers too, and keeps every try inside its time caps. A coin RugCheck did not answer for reads "RugCheck did not answer",
not "no RugCheck report".

The record: after the trader, `radar.py check` prices the early list once more (about minute 24, one request, one try; `bot.py`
stops it after 30 seconds) and writes `db/memeearly/<run id>.json` (synced with the results, pruned after 30 days): each coin's price
when seen, about 20 minutes later and about an hour later (filled by the spotter of the scan 45 to 90 minutes later that is closest
to an hour; a coin counts as gone when DexScreener answered for it without a pair, and stays unknown when the request failed), its
place on the scored list, its buy and why it was not on the list. After a few days it answers "is a coin seen at minute 5 a better
buy than at minute 24?" without leaving out the coins that died in between. `db/memebot/spotter.json` keeps the trader's score weights for the next
scan's spotter.

Switch it off with the repository variable `MEMEBOT_EARLY` = `0` (Settings, Secrets and variables, Actions, Variables), or
`MEMEBOT_EARLY=0` on a laptop. The page needs the website (it is built only when `GITHUB_REPOSITORY` is set); the first scan after an
update has no early box yet, because the polling script comes with the page the scan before built.

### Launch radar (coins under 10 minutes)

A second job beside the hourly scan (`.github/workflows/radar.yml`, `launch_radar.py`, `radar_src.py`). It makes a round
every 2 minutes: each round rates the coins whose DEX pool is under 10 minutes old with the bot's own gates and data
plus the trap checks of `traps.py` (dev history, copied X link, snipers in the first 30 s, same-block bundles, a dev wallet
under a day old, a staircase chart, fresh holder wallets, insider networks, holders funded together; measured only, with no weight:
the coin's replies on pump.fun and the likes of the tweet it launched off), shows the best 5 on the
top of the page's New tab (above the full scan's new launches) and in the app, records every rating, and sends a push only for a coin without a trap found
(it names the first checks the coin passed and, once 20 earlier green coins have their 1 h outcome, how many of them doubled and how many rugged). Fake money only:
the radar buys nothing and the paper trader never reads it.

When it runs: around the clock, night included (pushes too; the iPhone's Sleep focus mutes them). One run makes a round every 2 minutes for 55 minutes, then starts the
next run itself (no cron: GitHub's timed starts come late or not at all). The hourly scan starts the radar at its start when no
run is going (after a run that failed, or with narrower hours set, the first scan inside them), and "Run workflow"
on the radar's Actions page starts one by hand. The page asks for the new list every minute or so; after a tap on Start it says "Waiting for the new round".
The Office tab opens with the radar's desk: its state, the round's sources, checks, verdicts and push; a tap on it opens New.
Under it the desk's chat tells the same round in a few short messages from the radar's own bots (Scout found a coin, Checks names
what it passed, Skeptic its red flags, the Desk its verdict, Record the greens' 1 h results so far, in hindsight: once 20 have
their 1 h outcome the same counts the push says, such as "3 of 26 doubled within 1 h, 6 rugged"), made from radar.json alone: no
extra request, no AI, paper only.

Live feed: pump.fun graduations also come from PumpPortal's free websocket (`radar_feed.py`: one connection, no key, standard
library only). A coin that just moved to its pool gets an extra round about 20 s later (at least 60 s after the last round, at
most 12 extra rounds an hour). When the feed is blocked or silent the radar runs its 2-minute rounds as before. The Office desk
always shows the feed's state ("live feed on", "limited" or "off"); the New tab names it only while it is limited.

Fast lane: a graduation on the live feed no longer waits for that extra round. About 6 seconds after it the radar asks DexScreener
about that one coin (again at 14, 26 and 45 seconds while its pool is not listed yet) and rates it at once with RugCheck, the mint
time and whatever other checks fit in 18 seconds. The record keeps how many seconds after the graduation the coin was first seen
(`feed.lag`) and that the fast lane did it (`feed.via`); the list and a push (the same rules: green only, once per coin, 4 an hour)
follow right away. At most 30 graduations an hour, never within 25 seconds of a round, and it always ends before the round: a push
that would not fit in the time left is left to the round. A push the app holds back because another one went out under a minute ago
is not lost: the coin stays unmarked and a later round pushes it. A coin it cannot rate gets the extra round as before.

Curve watch (a paper test of calling coins before their pool): most of a pump.fun coin's run-up happens while it is still on its
bonding curve (over the radar's 71 graduated coins with curve candles, the last 15 curve minutes rose a median +144%), and the radar
only sees a coin once its pool exists. So between rounds the radar also reads pump.fun's list of coins still on the curve (highest
market cap first, every 15 seconds; `curve_watch.py`). The list is the watch's normal mode: it also asks the live feed for the trades
of the best 40, but PumpPortal sends coin trades only to paid API-key clients (the first live run had 38 subscriptions accepted and
not one trade in 55 minutes), and the radar uses no key. So when no trade has come in 3 minutes of live trade subscriptions (time
without a connection does not count) and they were not refused, the feed stops asking for the rest of the run, and the watch says "on"
with "list only: PumpPortal sends coin trades only to paid clients" (its trades host: unavailable, a plain chip). A feed that does
send trades is still used. When a coin passes 60, 75 or 90 % of its curve sold, it records a call: time, progress, market cap, price,
minutes since the mint and its momentum (points gained in 5 minutes from the list's readings and the feed's create, purchases against
sales when trades are known), with a quick check made before any pool exists (the dev's launches and wallet age, top holders and
launch snipers without the curve's own account, RugCheck without its pool risks, the wallet memory, the X link): ok, risky, trap or
unknown. A check that only comes in after the call (within 90 seconds) is kept beside it, and the split by check counts that call from
the price at that moment, never with what happened after the call. An hour after each call it is judged: graduated or not and when (an
hour nobody watched, say at night, is unseen, never "did not graduate"), the price an hour later and the peak within the hour (on the
list alone both from the list's readings, the price from its first reading after the hour), rugged and doubled by the same rules as
the radar's greens (rugged: gone, dead or worth 0.1x or less at one hour; doubled: 2x to 30x within the hour and not gone or dead at
one hour), and a paper result of 3 € with the paper fees and 5 % slippage. radar.json's `curve` block shows six variants (60, 75 and
90 %, each with and without the momentum filter, split by the check) next to the radar's green coins of the same hours, so the test
can show which one works best. The momentum filter is 10 or more points in 5 minutes and more purchases than sales; without trades
(the list only) the points alone, and each call keeps which form it had (`momBy`: list or trades). Nothing is pushed for it until
`radar_curve.json` names a variant in `curvePush` (null, the default: off); then that variant's calls are pushed once per coin, never
with a trap found, at most 3 an hour, worded as a coin still on its curve and a paper test. The calls are kept on radar-data
(`db/memecurve/`, 48 hours). If pump.fun's list or the trades are refused or change, the watch says so in the block and the rounds go
on exactly as before: the watch asks with its own client, so a refusal or a rate limit it gets never holds up the rounds' requests,
and when PumpPortal refuses the trade subscriptions twice, the live feed drops them for the run and keeps its graduations. pump.fun's
frontend allows about 60 requests a minute; the radar sends at most 40 in any rolling minute, counted where the requests go out for
the rounds, the fast lanes and the watch together (one past it is not sent). The rounds' and fast lanes' coin checks stop at 34, so a
round's 6 list pages stay free, and the watch stops at 28, so a whole round (its 6 list pages and 6 dev and holder checks) stays free;
within that the watch's list takes up to 8 a minute and its own checks up to 8 apart from it, so neither holds the other up (a minute
with a round and the watch: 28). The watch never asks within 8 seconds of a round, so a round never waits for it.

On the page the test shows under the radar's list on the New tab as "About to graduate (paper test)" (`page_radar.py`): whether the
watch is on, how many coins it follows on the feed or that it reads the list only, one plain sentence on what is being tested, whether
a curve push can go out (while the switch is off it says no curve push goes out; when on, which variant), the newest calls by coin
(curve %, minutes since the mint, market cap, the quick check's chips, and now: graduated after N minutes, still on the curve, did not
graduate, dead, or not watched to the end when the watch stopped before the hour was over, with the hour's result once it is known;
each coin opens on pump.fun), and the six variants beside the radar's greens of the same hours (calls, graduated, rugged and doubled
within 1 hour, the paper result per 3 €; rows with under 20 valued calls are grey, too few to tell), with the split by the quick check
in a fold. With no call yet it is one line; without the block it is hidden. The Office desk's chat adds Scout's line for a fresh call
with its quick check ("On the curve: SYM at 82%, 14 min after mint, quick check: no trap found yet"; a call whose check found a trap is
never named), and the radar's panel lists the watch's two hosts (pump.fun's curve list and the trades). Fake money only: the section
reports, it never advises.

Later prices: a record keeps the prices 5, 15, 30 and 60 minutes after the coin was first seen, but only those a later round
catches (at most half the offset late). With a round every 2 minutes all four are usually caught (the 5- and 15-minute ones
at the round after, about 6 and 16 minutes); a field no round caught
(the radar was stopped, or a run handed over to the next) stays empty (shown as "–"), never zero. The 1 h outcome (rugged, doubled) and the record line
need only the 1 h price.

Which trap checks count, and how much, comes from our own rug data (`research/rugstudy/`, `radar_weights.json`): the
signals the study could not confirm stay visible on the page but carry no weight. Once enough rated coins have their 1 h
outcome, the radar retrains its weights by itself (`model.json` on branch `radar-data`, tested walk-forward like the main
model, the study as the starting point).

Momentum and patterns (hindsight, paper only), in the Track record fold: "Rising fast" counts the coins at 1.5x their
first-sight price within 6 minutes with liquidity not lower, or +50% in 5 minutes, next to all new coins since the 2-minute
rounds with the same 1 h label (so far most of them rugged); they are never bought or pushed. "Patterns" compares rugged and
doubled coins (2x with real liquidity at 15, 30 or 60 minutes and no rug by 60) by the signals they had at first sight: at most
3 signals, and up to 3 rugged coins with the flags their hour's doubled coins mostly lacked. Once a win order holds up, a ▲
marks the coins that look like past doubled coins. The rules:
- Hindsight only: nothing here feeds the green rule, the verdicts, the trap points or a push. The win order only orders coins
  with the same verdict and trap points (coins without traps only after liquidity), scored on their first-sight signals.
- Same hours: winners and losers are matched by the UTC hour of first sight, and only hours with both count. Self-priced pools
  (mostly Meteora) count in neither group.
- First sight: only the signals of the first rating are used (stored from this version on; older records are left out).
- Enough data: a signal is tested only with 15 doubled and 15 rugged coins known and at least 5 doubled coins expected with and
  without it; below that the page says "too few".
- A pattern needs q under 0.05 (Cochran-Mantel-Haenszel by hour, Benjamini-Hochberg over the signals) and the same direction in
  both halves of the hours; anything else shown is marked "?" (could be chance). When the shares pooled over all hours point the
  other way than the hours one by one, the row says "more" and "less" from the hours instead.
- The coin lines only describe, with counts ("0 of 3 doubled that hour had it", only doubled coins whose flag is known count), and
  only for hours with 2 or more of them.
- The win order is used only when it holds up on the last 2 days it was not fitted on (30 doubled and 30 rugged coins, AUC at
  least 0.55 with its lower bound over 0.5).
The first patterns can show after about 2 to 4 days, a win order after about 4 to 6.

Nothing to set up. Active around the clock (0-24 Berlin). For a free VM instead, `python3 launch_radar.py loop --no-github --minutes 0
--cadence 120` runs the same loop without an end.
Switches (repository variables, Settings > Secrets and variables > Actions > Variables):
- `MEMEBOT_RADAR=0`: the run going on ends within the hour, then no round runs (the scan starts none, a start by hand is
  skipped). The quick stop: Actions > "Meme-Bot launch radar" > Disable workflow (it ends at the next round).
- `MEMEBOT_RADAR_HOURS=7-24`: narrower active hours (Berlin; the default 0-24 is around the clock).
- `MEMEBOT_RADAR_FEED=off`: no live feed (the 2-minute rounds go on); `pumpportal` (the default) switches it on.
- `MEMEBOT_RADAR_FAST=off`: no fast lane (a graduation gets the extra round as before).
- `MEMEBOT_RADAR_CURVE=off`: no curve watch (its calls of the last 48 hours stay on radar-data).
- `radar_curve.json` (a file, read when a radar run starts): `curvePush` null sends no curve push (the default); a variant such as
  `"75m"` (75 % with momentum) switches them on for that variant, `pushVerdicts` the checks allowed (`ok` by default, never a trap),
  `pushPerH` at most per hour.
- `MEMEBOT_PUSH_YOUNG=1`: the scan's own "new coins" push again (off by default now; the radar's push replaces it).
- `MEMEBOT_PEAKS=0`: no "best within 6 h" pricing job after the scan.
The phone's "New coins" switch also covers the radar's pushes.

### Best price within 6 h (hindsight)

Next to the paper account's real rule (stop-loss -30%, take-profit +1000%, 6 h), the page shows two hindsight
categories for every position since the v2 restart on 10.10.: the best minute-candle close within 6 h of the buy, and
the price at 6 h. They are not trading rules: they show what the rule left on the table. Dead pools and glitches are
filtered out (closes, not wicks; a liquidity floor; self-priced pools), and a cut price says why. A small job after
each scan (`peak.py`, GeckoTerminal minute candles) prices the windows that have ended. GeckoTerminal answers GitHub's
servers only a few times a minute, so after each rate limit the job asks more slowly for the rest of its run (10 s apart,
5 s more per rate limit, at most 30 s) instead of running into the limit until GeckoTerminal is given up for the run.
The block "Without the stop-loss" (`page_account.noloss`, no longer on the page since the three traders) also shows the raw top:
the highest close of all, unfiltered, with what selling there would have given after fees, wherever it differs from the filtered
best, and why it could not be sold there in two words ("one candle", "dust volume", "pool died", "over the cap"). The best-price
trader on the Traders tab reads the same docs but leaves such prints out and counts at most 30x.

### Radar account (bought within minutes)

A second paper account, beside the real one and never touching it: the best 5 coins of the radar's first round each hour
go in for 3 € each, at the price the radar saw, at the round's time, and so does every coin the radar listed as good in any of
its 2-minute rounds (a coin only once; green when the radar rated it good). Every round's best 5 would be about 25 buys an hour,
more than the job after each scan can price. They
are sold by the same rules as the paper account (stop -30%, take-profit +1000% at the confirmed close, else the close at
6 h; a dead pool is a total loss; paper fees), replayed on the pool's GeckoTerminal minute candles with the glitch rules of
"Best price within 6 h". The page no longer shows this block (its two tiles "All 5" and "Green only", the hindsight line, the last
30 coins: `page_radarpaper.py` stays until its code is deleted); the Radar tab sums the 3 € test up in one sentence under the
radar's paper positions, and it is not part of the three traders. `radar_paper.py` prices them inside the peaks job after each scan, before the
windows of "Best price within 6 h": at most 15 windows a run, oldest first, in at most 4 of its ten minutes, and it stops
after 3 of GeckoTerminal's rate limits so the other windows keep the rest. A result shows about an hour after its 6 hours.
One doc per coin in `db/memeradarpaper/` on the results branch; nothing the trader reads changes.

That is rule 1, history from the switch on. Rule 2 (`radar_paper.RADAR_TICKET`): from the switch every coin the radar rates good
and push-worthy while its pool is under 10 minutes old is bought on paper for 10 €, at its first such rating (that rating's time
and price), once; its doc (id ending `-g`, `rule: 2`) keeps the signs the coin had at that moment (`feat`) so they outlive the
radar records, its take-profit is booked at exactly 11x, and rule-2 windows are priced before the rule-1 backlog. The radar's
`radar.json` marks such a coin with `pb: 1`. Every window priced on minute candles also keeps its minute path
(`db/memepath/<id>.json`, written once, never pruned) for exact replays of other exit rules.

### What if the exits were different (hindsight)

The paper trader keeps its rule (-30% stop, 11x take-profit, 6 h). After each scan the peaks job also replays other rules on
the same closed paper trades (`exit_grid.py`, local computation only): stops of none, 20, 30, 40, 50, 60 and 70% against
targets of 2x, 3x, 5x, 11x and none, each with the 6-hour exit, on minute closes (never wicks) and with the paper fees. The
prices come from what the results branch keeps: each trade's 6-hour price record (`db/memepeak`: best, lowest and last
close, a dead pool) and, where kept, the 1-minute and 15-minute candle paths of the same coin and run in the tip record. Where
those show a fall only roughly, the sale price is estimated from the paper trader's own stop sales, and every result also
gets a worst and a best case. The current rule is replayed the same way and set against what it really made (the gap is in
the doc). A rule counts as better only when it did better per trade in the older and in the newer half of the trades and
overall, also with every rough sale at the stop and at the lowest price, with at least 100 trades in each half; a bootstrap
gives the 95% range of the difference. The page no longer shows this block (`page_exits.py` stays until its code is deleted):
the learning trader on the Traders tab does its job, with its own pre-registered bars and frozen daily decisions.
One doc, `db/memebot/exitgrid.json`; nothing the trader, the training or the big test reads changes.

### Three paper traders (`traders.py`)

One buy stream, three ways of selling, fake money only. The stream: the top pick (50 €), the new launches until the switch
(3 €) and the radar's rule-2 greens (10 €). The stop-loss trader is the real paper account plus the radar's rule-2 results. The
best-price trader sells each coin at its highest close within 6 h (looking back, not possible in reality; prints on dust volume
or after the pool died are left out, at most 30x unless peak.py confirmed more). The learning trader starts with the stop-loss
trader's rule and, once a day per group (pick, radar, new launches), may move one notch (stop -20/-30/-40%, target 2x/3x/11x,
hold 6 h or 2 h) or add or drop one skip sign, only when its pre-registered bars hold on trades that finished before the
decision (`T3_V`); every decision is a frozen file in `db/memetrader/v1/`. Its results are the stop-loss trader's plus the
replayed difference of its rule, so it equals the stop-loss trader until it has learned something. The radar group's current
skip signs go to the radar through radar-feed (`t3skip.json`): the radar does not push a green coin with one of them (it still
rates, lists and buys it on paper). `traders.load()` is what the page reads; `python3 traders.py run --dir mb` is the peaks
job's last step; `python3 traders.py summary --dir mb` prints the numbers.

## Publicity

Numbers alone miss what people are talking about, so every scan also reads Reddit (the newest posts of r/CryptoMoonShots,
r/memecoins, r/solana, r/SolanaMemeCoins, r/pumpfun and two searches, through the RSS feeds; every Solana address and
$ticker in a post counts for 48 hours, a ticker only for the biggest coin with that ticker), CoinGecko's Solana meme-coin
category (the 500 biggest by volume and market cap, with their addresses) and CoinMarketCap (top searches, and the Solana
coins with the biggest 24h gains). The coins found there join the scan; the mentions become factors (`rd.*`, `cgm.*`,
`cmc.*`) with small priors, and the learning decides what they are worth. The same post scan covers Farcaster (Warpcast
search), Mastodon tag timelines and 4chan's /biz/ catalog, and Google News searches join the headline feeds. LunarCrush
(X engagement) joins when a `LUNARCRUSH_API_KEY` secret is set.

The story behind a coin counts too. The biggest viral coins were built on one real story that exploded on X within
hours (very often an animal), so when a shortlisted coin's X link points at a single tweet (`x.com/<user>/status/<id>`,
the usual pump.fun pattern), the bot reads that tweet's likes, replies, age, author and text without a key
(`vt/<stamp>.txt`, factors `vt.*`: likes and replies on a log scale, "posted within 48 hours", the author's followers,
verified, picture or video) and names it on the card ("launched off a tweet by @user with 92k likes, posted 5 h before
the scan"). An animal theme in the name, ticker or tweet text is its own factor (`theme.animal`). Both start with small
priors; the learning decides what they are worth. Views are not public without the X API, so likes stand in for them.

The launchpad counts: terminal traders keep only pump.fun, Bonk and Bags coins in their New and Soon columns because
the bundled "fake charts" come from the other launchpads. The bot works out where a coin was launched (RugCheck's and
GMGN's launchpad field, the mint suffix, the pump.fun and LaunchLab lists, the DEX it migrated to) and makes it a factor
(`lp.trusted`, `lp.other`, the latter with a negative prior), names it on the card and tests the launchpad rule in the
filter audit.

"DEX paid" is read too: DexScreener's public orders endpoint says whether the team paid for the coin's DexScreener
profile (and for ads or a community takeover) and when (`dp/<stamp>.txt`, factors `ds.paid`, `ds.paidAgeH`, `ds.ads`,
`ds.cto`). Trading terminals filter on it because it costs real money; here it is a small prior and a row on the card.

For the shortlist (the coins that get a RugCheck report) the bot also pulls: GoPlus token security (mint, freeze, close
and balance authorities, transfer fee, trusted-token flag, holders, top-10 share, LP burn; a coin with any authority left
is skipped), GeckoTerminal token facts (GT score, holders, top-10 share, authorities), RugCheck community votes,
CoinGecko community data (watchlists, X followers, sentiment), StockTwits watchers and messages, the coin's X account
(followers, tweets in 7 days, through the public syndication page) and its Telegram channel (members, messages in 24h,
through the t.me preview). All of it is on the card and in the factors. Jupiter's price API re-prices every coin
DexScreener drops, so the big test and the track record keep their prices; SOL and BTC's 24h change and the Fear & Greed
index are recorded as market context for the models. Orca's busiest pools join the universe lists.

Two more sources switch on with a key, stored as a repository secret (github.com → Settings → Secrets and variables →
Actions → New repository secret), and `probe-keys.yml` (Actions → probe-keys → Run workflow) checks them without printing
them: **`BITQUERY_TOKEN`** (bitquery.io, free tier) reads every DEX trade of a shortlisted coin straight from the chain,
whatever app placed it (Fomo included): trader wallets with hold / sold status feed the top-buyer factors and the wallet
memory, and the last hour's trades, buyers, sellers, net flow and biggest-buyer share become factors (`bq.*`).
**`LUNARCRUSH_API_KEY`** (lunarcrush.com) adds the social-buzz list for every coin and the X/social topic of the best
shortlisted coins (`lct.*`: interactions, posts, contributors, sentiment, trend).

Probed and not usable without a key or at all: Reddit's JSON API, Bluesky search, Birdeye, DexTools, Solscan, Bags,
Believe, Moonshot, pump.fun's detail endpoints, CryptoPanic, fxtwitter, Google Trends.

## Training

Every pick run starts with `memebot.py train`, which puts the scored snapshots of the active profile through five programs
and writes `db/memebot/train.json` (shown on the page under "Training" and in the run summary):

- **Outside filter recipes.** The presets that circulate on TikTok for trading terminals (market cap over $30k, over
  $50k traded, under 10 hours old, "DEX paid"; the "new play" of $6k to $60k coins) are applied to every scored coin of
  the profile next to the bot's own gates: what each keeps, how many went up, how many to zero, the average per 20
  (`filters` in `train.json`, shown in the Training fold). A recipe that beats the gates on the bot's own results is a
  reason to change the gates; a claim in a video is not.
- **Walk-forward test.** The history is split at eight points; at each one the weights and the zero model are fitted on the
  scans before it only, and that model ranks the gate-passing coins of the scans up to the next point. What the top-1, the
  top-2, all passing coins and the two worst-scored coins did is the honest, out-of-sample record of the ranking.
- **Zero model.** Which factor values go with a coin going to zero within the horizon: each factor is cut into four
  equal-count bins, each bin shifts the odds of "gone", and the sum is calibrated against the observed zero rate. In the
  run, a clean coin whose trained zero chance is above the limit is skipped like a RugCheck flag ("training model: 41%
  chance of going to zero"). The chance is printed on the recommendation card.
- **Limit grids.** The zero limit and the score bar for a "strong" pick are tried on a grid against the walk-forward tips;
  the tightest zero limit that still leaves 85% of the scans with a tip and cuts the zero rate is used (never under 1.5x
  the base zero rate, never under 5%), and the score bar with the best win rate (within −10/+20 of the profile's bar).
  Nothing moves without 30 out-of-sample tips behind it.
- **Gate audit.** Coins that failed exactly one gate, by gate, next to the coins that passed all: a gate whose lone
  failers did as well as the passers protects nothing; one whose failers went to zero earns its keep.
- **Factor splits and the real tip record.** Every factor above/below its median, and every tip the bot actually gave
  (priced again after the horizon), as win rate, zero rate and average per 20.

The training needs 400 scored candidate coins and at least 10 zeros before the zero model counts, and 4 scans before the
walk-forward test runs; on GitHub Actions that is about a day of hourly scans. It learns from the scored snapshots of the last
14 days only (`TRAIN_DAYS`; `since` and `days` in `train.json`): on all of them it grew from 17 to 26 minutes between 17 and
21 Oct, toward the scan's 36-minute deadline for it. The big test itself keeps 60 days, and the run's own re-learn of the
weights still reads all of them.

## Two profiles

`--horizon 24h` (default) looks for coins that survive a day: liquidity, holders, no crash, re-priced 24 hours later.
`--horizon 2h` looks for coins that may pump in the next two hours: 6 to 24 hours old, market cap $100k to $2M, at least
$15k of liquidity and of 24h volume, no crash, not up 90% or more in the last 6 hours (or 200% in the last hour), no whale
above 20%, at most 10 insider wallets; buys versus sells
and the last hour's volume share are scored, not gated (the gate audit showed they rejected 11,000 coins a scan while a
high buyer ratio went with going to zero); scored by momentum
and holder growth; every scan is re-priced 2 hours later, so the learned weights target exactly that outcome. Each profile
learns only from its own results. Expect most 2-hour picks to lose and a few to multiply; the big test shows the split.

The 6-hour cap came from the review of the first 50 tips (2026-10-09): 5 of the 7 coins that went to zero or lost most
of it within 2 hours had already risen 95-297% in the 6 hours before the tip; of the winners only ECSTASY had (+0.69).
In the big test, coins 6 to 24 hours old that were up 90% or more in 6 hours fell below half their price within 2 hours
2.6 times as often as the rest (20% against 8%, in both halves of the data). They also multiply more often, so the cap is
proven to cut crashes, not yet to raise the average. A coin that rugs out of a calm climb (CLAUDIA, +44% over 14 hours,
then -99.5% within one hour on 2026-10-09) shows nothing in these numbers beforehand; only an exit rule protects against that.

The loop pulls new code from GitHub before each cycle and restarts itself when something changed (`--no-update` turns it
off), so a running laptop picks up updates without anyone touching it.

## How big the scan is

There is no cap: a full scan takes everything the public sources return, then runs the deep search (another 368 keyword
searches on DexScreener) on top, about 12,000 coins from 850 lists. The sources run as five workers at once, one per group
of hosts (DexScreener, GeckoTerminal, the social feeds and news, CoinGecko, the quick lists), and the keyword searches on three
threads, so the sources step takes about as long as GeckoTerminal's paced pages alone, about four minutes instead of eight one
after another; every host gets the same requests in the same order with at least the same gaps either way (CoinGecko's three
lookups 45 s apart), and `MEMEBOT_SERIAL_SOURCES=1` runs them one after another. Scored snapshot chunks older than 60 days and raw chunks that never got scored are pruned
from the Actions cache. More is not better: of those, roughly
10,000 have under $15k of daily volume and never reach the gates, and the free APIs allow no more requests per minute
(GeckoTerminal about six from GitHub's shared addresses, DexScreener 30 pairs per search).

## Running it on GitHub instead of your laptop

`.github/workflows/scan.yml` runs the whole cycle on GitHub Actions, so no computer of yours has to stay awake:

- every hour at :10 UTC, started through the GitHub API by the hourly routine (run name "Hourly scan"); the cron in the workflow at :25 is the safety net ("Safety-net scan", skips itself when a scan started in the last 45 minutes); and whenever you press **Run workflow** (github.com → Actions → Meme-Bot scan; works from a phone browser);
- each run clones the `results` branch into `mb/`, restores the big-test snapshots from the Actions cache, runs
  `bot.py cycle --recommend --push --horizon 2h`, pushes the new page and docs back to `results`, and prints the two picks
  with links on the run's own page (`bot.py summary`);
- the training runs beside the fetching; the trader waits for it until 36 minutes after the cycle began (`MEMEBOT_TRAIN_WAIT_S`,
  in seconds), then stops it and the runs read the last training, so the scan ends inside the job's 55-minute limit (the Agent
  office shows the trainer amber with the date of the training the runs read; each profile's newest training is also kept as
  `db/memebot/train-<rule>.json`, so a 24h run between 2h runs does not leave the 2h runs on the defaults);
- the scan step has its own limit (48 minutes) and the big-test snapshots are saved to the Actions cache right after it, also
  when it failed or ran out of time, so a scan that does not finish loses only its own report, never the snapshots;
- the **Run workflow** button takes two inputs: the profile (`2h` or `24h`) and `rescan` (force a full scan with a fresh snapshot);
- runs queue behind each other (one running, one waiting): a second press while one waits replaces the waiting one.

### A website for the phone

The same workflow builds `site/` (`bot.py site`): the page as `index.html` with a "Scan now" link to the Actions page, an
auto-refresh (every 15 minutes and whenever the tab comes back to the front), a web-app manifest and icons, so a phone can
put it on the home screen like an app. The `pages` job publishes it with GitHub Pages at
`https://<owner>.github.io/<repo>/`. Two switches on github.com make it live, both on the repository's Settings page:
**Change visibility → Public** (Pages is a paid feature on private repositories) and **Pages → Source: GitHub Actions**.
Until then the `pages` job fails and the run still counts as green.

### Watching a scan live

While a scan runs on GitHub, `bot.py cycle` (with `MEMEBOT_LIVE=1`, which the workflow sets on the scan step only) pushes the
Agent office record to a branch `live` that holds a single commit with a single file, `live.json`: about every 45 seconds when it
changed, at least once a minute even when nothing changed (a heartbeat with a fresh `"updated"`, so a quiet step is not taken
for a dead scan), and once more when the cycle ends (`"live": false`). The training and the candle fetch running beside the scan
report each progress line as it happens. The website's Agent office tab (and the New launches tab, for the early list) reads
`live.json` through GitHub's API while one of them is open and the browser tab is in front, and marks the floor plan: a LIVE badge with the age of the snapshot, the departments at
work pulsing, the finished ones green, the ones still waiting dimmed, the counts, and the newest line of every agent at work.
After the scan it says when the scan finished (or that it stopped, when no report came from it), and the website reloads itself
once the new page is out. A live snapshot that went 5 minutes without an update, or two failed reads in a row, show "Live view
paused, the scan may still be running", never "finished".

The page reads without a token, so every request counts against the 60 an hour GitHub allows one address, an unchanged answer
(304) too. It therefore asks every 75 seconds while the newest snapshot is a live scan and in the scan window, from 2 minutes
before a scheduled start to 35 minutes after it (until that scan's last snapshot is in), so a scan that starts late is caught too;
outside it only 2 minutes before the next scheduled start, then every 10 minutes. One open page costs about 25 to 33 requests an hour. The tabs of one browser share one reader (a reload asks nothing new). Every answer
carries GitHub's remaining count and reset time, and the page stretches its gaps so that 10 requests stay free: two phones or
laptops behind one address (one home Wi-Fi) slow each other down to about one read every 1.5 to 2 minutes each, and in the last
minutes of GitHub's hour a few reads can be up to about 10 minutes apart (the page then says "paused") instead of running out. A push
that fails or takes longer than 20 seconds is given up and the scan goes on. Inside claude.ai the page cannot reach GitHub and
stays as it was, with the website's address; opened from a file it reads GitHub like the website does.

Costs: a public repository has unlimited Actions minutes; a private one has 2000 a month, which a full scan every two
hours (about 10 minutes a run, 12 runs a day) exceeds, so a private repository needs a 4-hour schedule. Never run the
laptop loop and the schedule together: when both push, the later push wins and the other machine's docs are dropped.
The Actions cache keeps the big-test snapshots and results for seven days of inactivity; losing it wipes the big-test
history and the learned weights (the page and the recommendations survive on the results branch).

### iPhone app

The website can live on the iPhone's Home Screen like an app, all on free plans: a bottom tab bar (Pick, Radar, Traders,
Office), the Agent office and the New launches list (until the switch) live within seconds while the hourly scan runs, and push notifications
when the new coins are listed (about five minutes into the scan) and when the pick is made. Fake money only: nothing is bought
for real, and no notification is a trade. In a normal browser tab the page looks and works as before.

Until the switch the Radar tab shows the launch spotter's early list under the radar, in all its states, above the scored list, and its badge
on the tab bar counts the coins of that list while the list is shown (otherwise there is no badge). The "new coins"
notification goes out once a scan, when the first early list with coins is out: "9 new coins listed", "The newest is 4 min old.
On the list: ... Fake money only, nothing is bought for real."; tapping it opens the New coins tab at the early list. It goes out once
the live store has the list, so the app shows it at once.

How it works: a free Supabase project is the live store. While the scan runs, `bot.py` writes a small `status` row every 5 seconds
(and the whole live record, `current`, when it changes) with the secret key; the page reads `status` with the publishable key while
it is open and in front (the app on any of its tabs; a browser tab only on New launches or Agent office, and the tabs of one browser
share one reader), every 4 seconds while a scan is live and every 30 seconds otherwise, and `current` only when its early list or
pick changed (a few times a scan). It falls back to the GitHub live view above when Supabase does not answer. Per open page left
visible all day, with a scan live 32 to 41 minutes of every hour, that is about 1.2 to 1.6 GB a month (almost all of it `status`
rows), inside the free plan's 5 GB of egress for the project: two or three devices left open around the clock fit, more would not. The notification
keys (VAPID) are made by the first scan and kept in Supabase; `sw.js` shows the notifications on older iOS versions. The scan
installs the push sender from `supabase/push-requirements.txt`, where every package is pinned with its sha256 (made by
`supabase/pin_push.py`), so a run gets exactly those files or no notifications that run.

Set it up once (about 15 minutes, all from the phone):

1. **Supabase project:** on supabase.com, sign up (Continue with GitHub works; the Free plan needs no card) and make a new
   project: name `meme-bot`, region Europe, keep **Enable Data API** on, leave **Automatically expose new tables** off.
2. **Tables:** open `supabase/setup.sql` on GitHub, tap **Raw**, select all and copy. In Supabase open **SQL Editor → New
   query**, paste, tap **Run** ("Success. No rows returned"). Supabase may warn that the query has destructive operations (the
   script drops and re-creates its own functions, rules and triggers, and removes malformed rows): tap **Run query**, that is expected.
   Running it again later is harmless, and needed once after an update of that file (it keeps your data). After the update that
   takes new subscriptions from Apple's push service only (with the table `push_sub_log`), run it again in the SQL Editor. The SQL is not in
   `supabase/migrations` and there is no `supabase/config.toml`, so Supabase's GitHub integration never applies anything by itself.
3. **Keys:** in Supabase open **Project Settings → API Keys**. Copy the **publishable key** (`sb_publishable_...`) and, under
   Secret keys, reveal and copy the **secret key** (`sb_secret_...`). The project URL is `https://<ref>.supabase.co`, where
   `<ref>` is the id in the dashboard address (the **Connect** button shows it too).
4. **GitHub secrets:** on github.com open the repository's **Settings → Secrets and variables → Actions → New repository
   secret** (on a phone: **aA → Request Desktop Website** first) and add three: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
   `SUPABASE_SECRET_KEY`. The secret key goes nowhere else: `bot.py` puts only a publishable key into the page and refuses a
   secret one.
5. **One scan:** wait for the next hourly scan or press **Run workflow**. It makes the notification keys and builds the website
   with the live store.
6. **Install:** open `https://maxpandelakis-boop.github.io/Meme-Bot/` in **Safari**, tap **Share → Add to Home Screen** (keep
   **Open as Web App** on; no Share button in view: tap **•••** at the bottom right first), then open **Meme-Bot** from the Home Screen.
7. **Notifications:** in the app open **Account** (or tap the bell), tap **Turn on notifications** and allow them. The two
   switches choose which ones arrive: new coins listed, the pick made.

Limits:

- Notifications need iOS 16.4 or newer and the app opened from the Home Screen; a Safari tab cannot get them. They can only be
  turned on in the iPhone app: the live store takes new subscriptions from Apple's push service only (a script cannot make those
  without Apple devices), so the app installed on Android or a computer says "notifications work only in the iPhone app".
- A **Focus** mode (Do Not Disturb, Sleep) hides them: allow Meme-Bot in that Focus's settings.
- iOS sometimes ends a subscription without a word. If notifications stop arriving, open **Account**, tap **Turn off
  notifications**, then **Turn on notifications** again.
- The pick notification comes a few minutes before the website has the new report (GitHub Pages publishes it after the scan);
  the app shows a "New pick" note in the meantime.
- Supabase pauses a free project after a week without activity; the hourly scans keep it awake. A paused project shows no live
  view in the app (it falls back to GitHub's); resume it in the Supabase dashboard.
- `python3 app.py check` (with the two `SUPABASE_` variables for the URL and the secret key set) says what is set up, without
  printing any key.
- The live store and the "new coins" notification need `MEMEBOT_LIVE=1` (the workflow sets it on the scan step). A laptop run
  with the `SUPABASE_` variables but without it sends only the pick notification and writes nothing to the live store.
- The publishable key is public (it is in the page): anyone can read the live rows, which the public website shows anyway, and
  can save a subscription. The table keeps at most 25 and takes at most 6 new ones an hour (counted in `push_sub_log`), only from
  Apple's push service, also when many calls come at the same moment (`save_push_sub` takes new rows one at a time under a lock).
  When a new row needs room, the rows no notification has ever reached go first (the one seen longest ago first), then, among the
  rows a notification has reached, the newest subscription. The scan marks a row delivered when a push service accepted a notification for it
  (with the secret key; a stranger cannot), so once the phone got its first notification, neither made-up rows nor newer real ones
  can push it out, however often they are saved again. Until its first
  notification the phone counts like any other row, so turn notifications on and keep the app opened now and then. If the app
  says "too many new subscriptions this hour" (someone else used up the 6 an hour), wait an hour and try again, or run
  `delete from push_sub_log; delete from push_subs;` in Supabase's **SQL Editor** and turn notifications on again in the app. The scan deletes
  rows whose keys are no keys and rows whose own push host could not be reached at all three notifications in a row (never for a
  failure at Apple's, Google's or Mozilla's push service, which would be the runner's or theirs); any other error keeps the row and
  the log says it once. Supabase's Security Advisor flags the two functions `save_push_sub` and `drop_push_sub` (security definer,
  callable with the publishable key): that is on purpose, they are the only way in and they check what they store.

## The analysis page

Every cycle ends by rendering `mb/report.html` (also `python3 bot.py report`); on GitHub it becomes the website. In
recommend mode the page has four tabs, the same on the website and in the app: Pick, Radar, Traders, Office.

- **Pick** answers one question: which coin, why, and the numbers behind it. One heading by the pick's tier ("The pick for the next
  2 hours", "Risky pick ...", "No pick this scan"); the card shows the coin with its tier and safety verdict, the market strip, the
  paper line ("Bought on paper: 50 € at 17:21 · now +4.2%"), the safety check (RugCheck, GoPlus, creator, community) and, behind a
  tap, the reason in plain words, every figure behind the pick (first the score and the trained odds, which are about the same for
  every coin right now), the live chart and the links. Below it the runners-up, the hour grid and one "Details" fold with the tip
  record, the training, the coin test, all candidates, the weights and the run log.
- **Radar** (`page_radar.py`): the launch radar's coins without traps (a coin bought on paper says "Bought on paper · 10 €"), the
  radar's paper positions (`page_traders.radar_positions`), and folds for the coins seen with traps, the radar record, why these
  checks and the curve test. Until the switch (`memebot.SWITCH_AT`) the full scan's new launches follow under "New launches (until <its day>)".
- **Traders** (`page_traders.py`, numbers from `traders.load()`): the three paper traders compared on the same finished trades (one
  chart, one table), a card each, the activity (Bought and Sold, no arrows), and folds for the open positions, the finished trades
  (one result per trader), how the learning trader decides (its dated log) and the trades before the restart.
- **Office**: the radar's desk and chat, the agent cards (their lines wrap) and the Details fold.

Light and dark theme, phone-friendly, times in Europe/Berlin.

## Sending the results somewhere else

`python3 bot.py loop --every 30 --push` pushes `mb/report.html` and the small result docs (positions, exits, equity curve,
run log, weights, state) after every cycle to the `results` branch of this repository (the big scan snapshots stay local).
`python3 bot.py sync` does the same once. The `mb/` folder keeps its own small git repository for that, so the code checkout is
never touched. Anyone with access to the repository can then read the page from that branch, and a Claude session can fetch it
to show the picks, the charts and the links in chat.

## Files

| File | Role |
|---|---|
| `bot.py` | the cycle (`cycle`, `loop`, `status`, `reset`) |
| `fetch.py` | the sources: every API → the plain-text files the analyst reads |
| `memebot.py` | the analyst: gates, factors, learned weights, picks, exits, big test |
| `radar.py` | the launch spotter: the early list of new launches about five minutes into each scan, and its record |
| `launch_radar.py`, `radar_src.py`, `radar_feed.py` | the launch radar job: its 2-minute rounds, its sources, the live feed and the fast lane |
| `curve_watch.py`, `radar_curve.json` | the curve watch (coins still on pump.fun's curve, called on paper) and its push switch (off) |
| `radar_paper.py`, `peak.py`, `exit_grid.py` | the radar account, the best price within 6 h (and the minute paths), the exit what-if |
| `traders.py` | the three paper traders and the learning trader's frozen daily decisions |
| `report.py` | the analysis page: renders `mb/report.html` from `db/` |
| `app.py` | the iPhone app: the live store (Supabase), push notifications, the installed app's script and `sw.js` |
| `supabase/setup.sql` | the one-time setup of the Supabase project (tables, access rules); `supabase/test_setup.py` tests it on PostgreSQL; `supabase/push-requirements.txt` pins the push sender with hashes (`supabase/pin_push.py` makes it) |
| `selftest.py` | end-to-end test on a local mock of all APIs with a fake clock |
| `.github/workflows/scan.yml` | the hourly GitHub Actions scan, the results branch and the website |

All source files are plain text, one coin per line, fields separated by `|` (formats in the `memebot.py` docstring), so
any extra source can be added by writing such a file into `mb/`.

## Caveats

- Public APIs rate-limit and change; a source that fails is skipped and the scan continues with what came back.
  `bot.py cycle` logs the coverage per source. GMGN and pump.fun sit behind Cloudflare and often refuse plain clients.
- Paper results ignore slippage and the price impact of a real 20-unit buy in a thin pool.
- The learned weights need a few days of full scans before they mean anything; until then the prior drives the picks.
- No model makes a meme coin safe. The zero model lowers the share of tips that go to zero; it cannot bring it to zero,
  and a walk-forward win rate is a past average, not a promise for the next two hours.
