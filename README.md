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
python3 bot.py loop --every 60 --recommend --push   # recommend mode: never buy, each cycle rescans and puts the two best clean coins on the page
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

### New launches tab

The page has two tabs. "The pick" is the recommendation. "New launches <1h" lists every coin under an hour old that had
a DEX pair and at least $5k of liquidity at the scan, best score first, with the same trained odds, safety report and
numbers as the pick (`young` in `db/memebot/recommend.json`). These coins are shown, never picked: the 2h profile picks
from coins 3 to 12 hours old, and the training's age record (`ages` in `db/memebot/train.json`, shown at the top of the
tab) says how coins of each age did after the horizon, so the question "do the newest coins do better?" is answered by
the record, not by a hunch. The RugCheck/GoPlus reports for them are fetched with the shortlist.

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
walk-forward test runs; on GitHub Actions that is about a day of hourly scans. It takes under a minute on 30k rows.

## Two profiles

`--horizon 24h` (default) looks for coins that survive a day: liquidity, holders, no crash, re-priced 24 hours later.
`--horizon 2h` looks for coins that may pump in the next two hours: 1 to 12 hours old, market cap $50k to $2M, buys
outweighing sells in the last hour, volume accelerating, no whale above 15%, at most 10 insider wallets; scored by momentum
and holder growth; every scan is re-priced 2 hours later, so the learned weights target exactly that outcome. Each profile
learns only from its own results. Expect most 2-hour picks to lose and a few to multiply; the big test shows the split.

The loop pulls new code from GitHub before each cycle and restarts itself when something changed (`--no-update` turns it
off), so a running laptop picks up updates without anyone touching it.

## How big the scan is

There is no cap: a full scan takes everything the public sources return, then runs the deep search (another 368 keyword
searches on DexScreener) on top, about 12,000 coins from 850 lists; the keyword searches run on three threads, so a scan
takes about eight minutes. Scored snapshot chunks older than 60 days and raw chunks that never got scored are pruned
from the Actions cache. More is not better: of those, roughly
10,000 have under $15k of daily volume and never reach the gates, and the free APIs allow no more requests per minute
(GeckoTerminal about six from GitHub's shared addresses, DexScreener 30 pairs per search).

## Running it on GitHub instead of your laptop

`.github/workflows/scan.yml` runs the whole cycle on GitHub Actions, so no computer of yours has to stay awake:

- every hour on a schedule, and whenever you press **Run workflow** (github.com → Actions → Meme-Bot scan; works from a phone browser);
- each run clones the `results` branch into `mb/`, restores the big-test snapshots from the Actions cache, runs
  `bot.py cycle --recommend --push --horizon 2h`, pushes the new page and docs back to `results`, and prints the two picks
  with links on the run's own page (`bot.py summary`);
- the **Run workflow** button takes two inputs: the profile (`2h` or `24h`) and `rescan` (force a full scan with a fresh snapshot);
- runs queue behind each other (one running, one waiting): a second press while one waits replaces the waiting one.

### A website for the phone

The same workflow builds `site/` (`bot.py site`): the page as `index.html` with a "Scan now" link to the Actions page, an
auto-refresh (every 15 minutes and whenever the tab comes back to the front), a web-app manifest and icons, so a phone can
put it on the home screen like an app. The `pages` job publishes it with GitHub Pages at
`https://<owner>.github.io/<repo>/`. Two switches on github.com make it live, both on the repository's Settings page:
**Change visibility → Public** (Pages is a paid feature on private repositories) and **Pages → Source: GitHub Actions**.
Until then the `pages` job fails and the run still counts as green.

Costs: a public repository has unlimited Actions minutes; a private one has 2000 a month, which a full scan every two
hours (about 10 minutes a run, 12 runs a day) exceeds, so a private repository needs a 4-hour schedule. Never run the
laptop loop and the schedule together: when both push, the later push wins and the other machine's docs are dropped.
The Actions cache keeps the big-test snapshots and results for seven days of inactivity; losing it wipes the big-test
history and the learned weights (the page and the recommendations survive on the results branch).

## The analysis page

Every cycle ends by rendering `mb/report.html` (also `python3 bot.py report`); on GitHub it becomes the website. In
recommend mode the page answers one question: which coin, why, and the numbers behind it. The card shows the coin with
its tier and safety verdict, the trained chance of a profit and of going to zero, the score and rank, the reason in plain
words, the safety check (RugCheck, GoPlus, creator, community), every figure behind the pick (age, liquidity, volume
pace, buy pressure, holders, top wallets, insiders, locked liquidity, creator share and sales, authorities, sources,
boosts, buyers vs sellers, holder growth, community counts), the sources it was seen on, the live chart and the links.
Below it: the runners-up, the track record of every tip, and one "Details" fold with the training, the big test, the
paper bankroll, all candidates, the weights and the run log. Light and dark theme, phone-friendly, times in Europe/Berlin.

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
| `report.py` | the analysis page: renders `mb/report.html` from `db/` |
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
