# Methods from other platforms: result (fake money only)

Pre-registration: research/otherplatforms/PREREG-PLATFORMS-2026-11-04.md (commit 40cd66b, pushed before any trade was computed).
Code: research/otherplatforms/check_platforms.py. Results: RESULT-PLATFORMS-2026-11-04.json. Research only: no live rule,
account, shadow or bot changed.

## 1. Which platforms work from the cloud session (2026-11-04)

| Route | Video itself | Text (title, description, transcript, README) |
|---|---|---|
| Container network (curl, yt-dlp) | Blocked for YouTube, TikTok, Vimeo, Rumble, Odysee, Dailymotion, Bitchute, X, Twitch, Kick, Reddit, Instagram, Facebook, Spotify, Apple Podcasts, archive.org, Invidious/Piped mirrors, transcript sites | Only GitHub, PyPI, googleapis |
| Web search | (finds links on Rumble, Odysee, Vimeo, Bitchute, Twitch, Kick) | Works |
| Web page reader | No video file anywhere | Rumble: refused. Vimeo: bot check. Odysee, Bitchute: title / one-line description only. GitHub READMEs, blogs, guides: yes |

So no video on any platform can be watched from here. The video tool (PR #70: .claude/skills/watch + tools/video/speech.py) works
on a video FILE that the user uploads, and on YouTube links only with a GEMINI_API_KEY in the cloud environment (none set).
Possible later: a GitHub Actions job could download Rumble/Odysee videos (Actions runners have open internet) and transcribe them
offline; that needs a new workflow file, which needs the user's explicit yes.

## 2. What the text sources say

Other people's paper-trading bot projects on GitHub, all public, all fake money, all October 2026:

| Project | Their verdict |
|---|---|
| Baruna240/Momo-Quant-Lab | 11 meme strategies, > 4,000 positions: "No meme variant is profitable yet"; costs ~11 % per round trip; ML AUC 0.80 but top picks below 1x after costs |
| tymkow/Memecoin-bot-test | 18+ strategies (filters, ML, copying Cupsey and profitable wallets, wallet groups, arbitrage): all negative after costs, also out of sample |
| apchhui/pump-research | 26,000 tokens, 60/40 time split, bootstrap: "Every strategy family tested loses money out of sample" |
| m3n4ce-dev/meme_traderv1 | early sniper -13.4 % per SOL ("losing, not by bad luck"); graduation plays +0.3 % on 225 trades ("range includes zero"); model picks +11-16 % with instant fills, about nothing with 0.5-2.5 s delay, live -9..-25 % |
| realdoomsman/pump-sniper | completion snipe "roughly flat" (marks, not fills); momentum ladder 397 trades -7 % per round trip |

Other text: arXiv 2602.14860 (655,770 pump.fun tokens, Sep 2025): buy-and-hold on the curve is below break-even at most curve
levels, before fees. CoinGecko "73 % of pump.fun wallets profitable" (Apr 2026) counts realized PnL only and leaves out bag
holders, so it says nothing about a bot that must sell every coin.

## 3. The rules found, and what we did with them

| Rule (source) | Status |
|---|---|
| KOL / call groups, copy wallets, social links (several guides) | already failed: PR #5, #17, #35, #37 |
| Buy the dip after known traders exit (Jekyll Koller) | already failed: PR #51 |
| Opening-range breakout | already failed: PR #69 |
| "Almost bonded" curve buys (GMGN filter) | close to the failed curve test of PR #57; external results flat (m3n4ce, realdoomsman, arXiv) |
| Stops / targets in general | 225 sell rules, PR #42 / #68 |
| Wait 48 h, buy survivors, hold days (notanicecat69 / Wood) | not testable: our candles end at 48 h |
| M1 breakout, pullback, reclaim, buy the retest (cryptorank / Archer) | **tested here: fails** |
| M2 GMGN "Migrated" mc >= $30k + Jekyll exits 2x/3x/4x, stop -35 % | **tested here: fails** |
| M3 Axiom "Trending" mc >= $70k + $30k 5-min volume + same exits | **tested here: fails** |
| M4 DexScreener new pairs liq > $20k, FDV > $85k + ladder 2x/5x/10x | **tested here: fails** |

## 4. Result of the four new rules

70,260 graduations with candles (w1 6,830, w2 10,481, w3 22,085, w4 22,437, w5 8,427). 20 EUR per buy, fees as the Radar account,
allowance 0.60 EUR. Bar of PR #39 with 1 % / 4.

| Method | trades | per trade after allowance | 0.25 % bound | in profit | windows positive | gross multiple (mean / median) | holds |
|---|---:|---:|---:|---:|---:|---|---|
| M1 retest | 6,827 | -6.17 | -6.73 | 22.8 % | 0 of 5 | 0.79 / 0.75 | no |
| M2 GMGN migrated | 45,710 | -8.04 | -8.25 | 22.8 % | 0 of 5 | 0.70 / 0.43 | no |
| M3 Axiom trending | 17,742 | -7.97 | -8.29 | 22.1 % | 0 of 5 | 0.71 / 0.47 | no |
| M4 DexScreener | 33,040 | -9.12 | -9.36 | 17.8 % | 0 of 5 | 0.64 / 0.42 | no |
| B0 every graduation, Jekyll exits (information) | 50,647 | -8.09 | | 22.4 % | 0 of 5 | 0.70 / 0.45 | |

- **All four fail in every window.** Even before fees the average coin returns 0.64-0.79x of the buy.
- The filters from the guides add nothing: M2 and M3 are as bad as buying every graduation (B0); M4 is worse.
- Information only (INFO-OPTIMISTIC-FILLS-2026-11-04.json, info_optimistic.py): with impossible, optimistic fills (every stop
  filled exactly at -35 %, targets before the stop in the same candle) all four still lose (-0.72 to -2.11 per trade; gross
  1.02-1.09x is eaten by the fees).

## Reading it (not deciding)

The guides' rules describe what winners did on their winning coins; on every graduation they lose, before and after costs. Five
independent bot projects on GitHub reach the same verdict as this repo: no retail rule beats pump.fun's costs. Nothing is built.
