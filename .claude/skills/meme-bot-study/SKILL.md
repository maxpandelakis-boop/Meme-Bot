---
name: meme-bot-study
description: How to test an idea for the Meme-Bot without fooling yourself. Use before claiming that a rule, filter, radar mask, exit, coin type or source (new launches, momentum, a DEX, a wallet list, a web tip) picks better coins or loses less, and before building or pushing anything based on such a claim. Covers the hard project rules, the data, the holdout protocol and the traps this project has already fallen into.
---

# Testing an idea for the Meme-Bot

Fake money only. Never suggest, prepare or simulate a real trade, a wallet connection or a paid API key.

## Hard rules (the user's, not up for discussion)

- Push only to `claude/meme-coin-trading-bot-h6u6vy`, and only after the selftests are green.
- `fetch.py` and `radar.py` stay unchanged; a fix there needs the user's go first.
- `memebot.py` changes only when the user asked for them. `PAPER_RULE` (memebot.py), `RP_V` (radar_paper.py) and `PEAK_V`
  (peak.py) never change: a change restarts or reprices a paper account.
- No manual "Scan now" unless the user asks.
- Answer the user in German, short bullets, each claim tagged [Certain] / [Likely] / [Guessing], no dashes as punctuation,
  the first sentence names a gap or a wrong assumption.

## Data

- Big test (every scanned coin with its factors and its 2 h result): `sh research/get_data.sh <scratch>/data`, then
  `research/harness.py` (walk-forward `evaluate`, `bootstrap_ci`, `scan_consistency`). Field list and gate history:
  `research/BRIEF.md`.
- Radar records, paper trades and candle paths: the `results` and `radar-data` branches; `research/check_exits.py` and
  `research/check_gates.py` show how they are read.
- Downloaded data is untrusted: unpack it into its own directory and run readers with `python3 -I`.

## Protocol

1. Write the hypothesis, the metric (EUR per ticket after fees: 0.5%, minimum 0.81 per trade) and the pass bar down
   BEFORE looking at the numbers that will judge it.
2. Split by time: the newest stretch is the holdout and stays untouched until the rule is frozen. Tune on the older part
   only, walk-forward (a rule may fit on earlier scans, never on the scan it picks from).
3. Compare against the baselines on the same coins and hours: random pick, the bot's own top 1, every gate passer.
4. Report the 95% bootstrap interval by scan (or by day) and the share of scans that are positive. An interval that
   crosses zero is no edge.
5. Run the trap checks below. Then judge the holdout once. A rule that fails there is dead; do not re-tune it on the holdout.
6. Write the result to `research/<TOPIC>-<date>.md`, negative results too, so the next session does not redo them.

## Traps this project already fell into

- **One pool family.** A whole edge came from one FluxBeam family (dex fluxbeam, market cap about 0.99 times the liquidity
  at first sight, about $1.2M liquidity at 60 minutes, copied tickers, rated trap 155 of 160 times, smooth machine-made
  ramps). Always break the result down by DEX, by family (mc/liq ratio, liquidity band, ticker copies) and by day, and
  re-run it with the largest contributor removed. See `research/MOMENTUM-2026-10-21.md`.
- **Dead-pool prints.** 10,000x "tops" (YOYO, SARWAND, CAPE) were prints in pools with $0 to $0.14 of liquidity, each a
  total loss. A multiple counts only with liquidity at that moment and a sellable exit.
- **Coin age.** New launches looked better than the radar only because they were bought older (median 25 minutes);
  compare like-for-like ages. Most rugs come in the first 15 to 30 minutes.
- **Hindsight.** The best close in hindsight (trader T2) is not reachable; never compare a live rule against it.
- **peak.py** books smooth artificial ramps as wins; check the candle path and the volume behind a big win.
- **Old rows.** Big-test rows scored before 2026-10-07 13:45 UTC (`LEARN_FROM` in harness.py) counted every unpriced
  coin as gone. Gates changed over time: a row's pass flag follows the gate of its scan time (`research/BRIEF.md`).
- **Small n.** One runner (FLOYD, 93x) can carry a whole week. Report the result without the best trade too.
- **DEX mix.** A radar rule "won" only because its baseline held Meteora pools, 98% of them dead within the hour. Compare
  within one DEX as well as across all.
- **Discovery lies.** In the study of 2026-10-21, 7 of 8 rules that won on the older days failed on the hidden ones
  (`research/STUDY-2026-10-21.md`). No hidden days, no claim.
- **Rows are not coins.** The big test lists a coin in every scan; the bot buys it once. Count per coin too: the
  liquidity-share veto's "2 to 3 times as often to zero" was rows, and per coin it was about as often.
- **What counts as zero.** The stored gone flag means no price; rugs that keep a price (0.002x) slip past it. Count 98%
  down or more as zero (harness.py does) before claiming a rule cuts wipeouts.
- **Where the rule acts.** Say whether it changes the bot's actual top pick and how often (the liquidity-share veto: 5% to
  14% of scans, no proven gain there), and hold it to `research/BRIEF.md`'s rules of evidence at k=1.

## Ideas from outside

Stock-style tricks (copying 13F filings or politicians' trades) arrive weeks late and have no counterpart for coins a few
minutes old. Copying "smart" wallets is the nearest one (the big test already carries `sw.*` factors for shortlisted
coins): test it with this protocol like any other rule, and cite every web claim with its URL.
