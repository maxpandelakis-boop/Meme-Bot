# Meme-Bot: a paper-trading meme coin analyst

Fake money only. The bot never signs a transaction, never touches a wallet and never buys anything for real. It scans
roughly a thousand Solana meme coins from public sources, scores them, and "buys" the two best with a 40-unit fake
bankroll (20 per coin). It then follows those positions with fixed sell rules and learns which factors predicted the
next 24 hours from every coin it scanned.

## Quick start

Python 3.9+ and nothing else (standard library only).

```bash
python3 selftest.py                 # proves the whole pipeline on a local mock of every API (~10 s)
python3 bot.py cycle                # one real cycle: fetch ~1000 coins, score, pick, apply the sell rules
python3 bot.py status               # bankroll, open positions, closed trades
python3 bot.py report               # render mb/report.html, the analysis page
python3 bot.py loop --every 30      # keep cycling every 30 minutes (Ctrl-C to stop)
python3 bot.py loop --every 30 --push   # the same, and push the results to the repository's results branch after each cycle
python3 bot.py cycle --force        # pick now, ignoring the 3-hour gap and the daily cap (the bankroll still caps it)
python3 bot.py reset                # wipe the history and start again with 40
```

Everything lives in `./mb` (`--dir` changes it): the fetched source files, `pairs.json` (the merged universe), and `db/`
(positions, exits, snapshots, learned weights, state).

## How a cycle works

1. **mode** – `memebot.py mode` says what the run needs: a full scan (every ~12 h, for the 24-hour "big test"), a light
   scan (the bankroll has a free slot and the last pick is more than 3 hours old) or only prices for the open positions.
2. **sources** – `fetch.py sources` pulls the coin universe:
   DexScreener boost / profile / community-takeover / ad lists plus ~70 keyword searches (about 30 pairs each),
   RugCheck's new-token list, GeckoTerminal trending / new / top pools (with distinct buyers and sellers), CoinGecko
   trending, Jupiter trending / organic / recent tokens (holders, organic score, traders), pump.fun top and new coins,
   GMGN smart-money rankings and wallet leaderboard (usually blocked by Cloudflare, so often empty), and crypto news RSS
   headlines. With `LUNARCRUSH_API_KEY` set it also pulls LunarCrush social buzz.
3. **gather** – `memebot.py gather` merges everything into one record per coin and lists the addresses that still need
   full DexScreener pair data; `fetch.py tokens` fetches those 30 at a time, then gather runs again.
4. **shortlist** – the best-scored coins that pass the hard gates get a RugCheck report (12 for the pick, 120 more when
   a big-test snapshot is due) and, when GMGN answers, their top-70 buyers.
5. **run** – `memebot.py run` applies the sell rules to the open positions, then buys the two best coins whose RugCheck
   report is clean, writes everything to `out/`, and `bot.py` copies it into `db/`.

### Hard gates (a coin must pass all of them)

price known · not on a launch curve (pump.fun, launchlab, …) · has a real DEX pair · not a GMGN honeypot · not a
tokenized stock / wrapped asset / stablecoin · at least 1 hour old · liquidity ≥ $20k · market cap $100k–$50M ·
≥ $20k traded in 24 h · not a copycat of a bigger coin with the same ticker.

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
warning and at least 50% of the liquidity locked. No report means no buy.

### Bankroll and sell rules

| Rule | Value |
|---|---|
| Bankroll | 40 (fake), never more deployed than that |
| Per position | 20, so at most 2 coins at once |
| Fees (simulated) | 0.5%, minimum 0.81 per trade |
| Take profit | sell half at 2×, sell the rest if it falls back to entry |
| Stop loss | sell everything at −50% |
| Time limit | sell after 3 days |
| Rug | sell at 0 when the price vanishes or liquidity drops below $1k |
| Re-pick | the same coin is not bought again for 7 days |
| Pace | at most one pick run every ~3 h and 4 picks per day |

Money from a sale returns to the bankroll and frees a slot for the next pick run.

## The analysis page

Every cycle ends by rendering `mb/report.html` (also `python3 bot.py report`). Open it in any browser; it is a plain file.
It shows the bankroll and equity, the equity curve per run, the bought coins with their last price, sell levels and the
bot's reasons, the closed trades with their result, the 24-hour big test per scan against the "price unchanged" baseline,
the factor weights in use with a glossary, the top candidates of the last full scan and why they were not bought, and the
run log. Light and dark theme, phone-friendly, times in Europe/Berlin. To read it on a phone, serve the folder from the
machine that runs the bot (`cd mb && python3 -m http.server 8000`) and open `http://<that machine>:8000/report.html`.

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

All source files are plain text, one coin per line, fields separated by `|` (formats in the `memebot.py` docstring), so
any extra source can be added by writing such a file into `mb/`.

## Caveats

- Public APIs rate-limit and change; a source that fails is skipped and the scan continues with what came back.
  `bot.py cycle` logs the coverage per source. GMGN and pump.fun sit behind Cloudflare and often refuse plain clients.
- Paper results ignore slippage and the price impact of a real 20-unit buy in a thin pool.
- The learned weights need a few days of full scans before they mean anything; until then the prior drives the picks.
