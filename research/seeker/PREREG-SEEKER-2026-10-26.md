# Pre-registration: the Rocket seeker, a live paper bot that looks for rocket coins (26 Oct 2026, ~10:50 UTC)

Fake money only. Written and pushed before the model below was fitted or any of its scores was looked at. Nothing in the Pick,
the Sell bot, the Radar account or the Learning Pick changes.

## Why

The user (26 Oct 10:15 UTC): "finde einen Bot, der solche Coins sucht und findet, und dann Papertrades damit macht" (a bot that
looks for rocket coins like LAUNCH, finds them and paper-trades them). Every backtest so far says no rule makes money (PR #42,
#53, #55, #57, #59); the honest next step is a forward test on coins nobody has seen yet. The Radar account 🚀 is already a
rocket hunter, but it reads only the chart and wallets from 30 minutes on and keeps its strict line (user, 25 Oct). The rocket
study (PR #55) found launch facts that raise the rocket rate 2-2.4x on unseen months at 30 minutes after the graduation (short
bonding curve, X post link, no name-word crowding); the Radar does not use them. The Rocket seeker uses those that can be read
live, together with the first 30 minutes of the chart.

## What can be read live (checked on radar-data, 2,443 records of 24-26 Oct, 1,694 PumpSwap graduations)

| Fact (PR #55 name) | Training source | Live source | Live coverage |
|---|---|---|---|
| F3 bonding-curve minutes | created_ms to graduation | launch radar record: pool time - mint time | 81 % (mint time known) |
| F1 creator's graduations | creator's graduations in the 30 days before | record sig0.devGrad (pump.fun coins?creator=, 50 newest) | 98.6 % |
| F11 X link type | metadata file's twitter field | record sig0.x / xKind | always (empty = none) |
| F14 X post age | snowflake id of the post vs creation | the same from sig0.x and the mint time | with the mint time |
| F13 theme heat | graduations of the 24 h before sharing a name word | the radar's PumpSwap records of the 24 h before | always |
| F5 CJK name | symbol + name | record sym + name | always |
| chart at 30 min | five-minute candles (GeckoTerminal w1/w2/w5, history2 w3/w4) | GeckoTerminal one-minute candles summed to five-minute clock bars | per coin, one call |

Not live (left out): picture facts F15 and F19-F22 (CLIP), F10 number of links and F18 description (no telegram/website/
description in the record), F4 copycat ticker over 7 days (the radar keeps 48 h), F12 news, F16/F17 metadata fields, the holder
and wallet facts of PR #57 (Helius quota used up), F8 crowding and F6/F7/F9 (did not count in PR #55; F8 depends on coverage).

## The model (fixed now)

- Rows: every graduation of the five windows of PR #55 (research/rockets/build_paths.py + base.py + check_rockets.launch_facts,
  same filters: history2 recorder outages left out on w3/w4, pool liquidity at the entry at least $10,000), entry E = 30 minutes
  after the graduation (close of the last five-minute bar that closed before then).
- Label: rocket = a five-minute close at 10x the entry or more within 24 hours (base.py).
- Features (13): f_curve_min, f_creator_prior, f_xtype, f_post_age, f_theme24, f_cjk (as check_rockets.py computes them), and from
  the bars up to the entry bar: c_ret = ln(entry / first traded close), c_peak = highest high / entry, c_vol = log10(1 + USD volume),
  c_act = share of bars with a trade, c_r5 = ln(entry / close one bar before), c_r15 = ln(entry / close three bars before),
  c_mc = log10(entry x 1e9).
- Missing mint time: for a seeded random 20 % of the training rows (seed 7) f_curve_min and f_post_age are set to missing, so the
  model has learned what an unknown mint time means (live: 19 % unknown).
- LightGBM binary: learning rate 0.03, 15 leaves, at least 100 rows per leaf, feature fraction 0.8, bagging 0.8 every round, L2 10,
  400 rounds, seed 7, no early stop.
- Backtest (shown, not a pass/fail: PR #55 found these facts on the same months, so it is partly seen): fit w1-w3, score w4 and
  w5; cut = the 98th percentile of three blocked-by-time out-of-fold scores within w1-w3; AUC, rocket share of the top 2 % against
  the base, money with the hold rule below on five-minute closes (20 EUR, the Radar's paper fees as PR #55, minus 0.60 EUR).
- Live model: refit on w1-w5 with the same settings; live cut = the 98th percentile of five leave-one-window-out scores (each
  window scored by a model fitted on the other four). Exported as plain JSON trees (like rocket_model.json), scored in plain Python.

## The bot (fixed now)

- Every minute (seeker.yml, its own job and concurrency group, its state on the branch seeker-data): the launch radar's PumpSwap
  records whose pool is 30 to 45 minutes old and not yet scored; DexScreener's pair (liquidity at least $10,000, a price); the
  features as of graduation + 30 minutes; the score; a score at or above the cut buys the coin once, 20 EUR on paper at
  DexScreener's price of that minute. Every score is logged (log/<UTC day>.jsonl) whether it buys or not.
- Hold rule "Rocket hold", on one-minute closes after the buy: a close at or below 0.5x the buy price sells at that close; once a
  close reached 2x, the first close at or below 0.6x the highest close since the buy sells at that close; 24 hours after the buy it
  sells at the last close. No fixed target. Paper fees memebot.tip_net (the Radar's). No push. Shown in the app as "Rocket seeker 🔭
  (test)".

## The judgement (fixed now)

- Forward window: the buys of the first 30 days from the first live round (seeker.json "since"), each closed by its rule.
- Judged once, on 27 Nov 2026 (a reminder in this thread). A look on 22 Nov with the full-month live review is descriptive only.
- It HOLDS only if all of research/PREREG-REVIEW-2026-11-04.md (PR #39): at least 40 closed trades; mean per trade above 0 after a
  0.60 EUR allowance (3 points of 20 EUR); the 1st percentile of 10,000 bootstrap re-draws of the trades above 0; the total without
  its single best trade above 0. Also reported: rocket share of its buys against all scored coins, how many coins were missed.
- Holds: it stays paper; a second unseen month comes before any talk of real money, and only on the user's own word. Fails: it
  says so plainly and stays a test until the user stops it. Other cuts (the log has every score) are exploration only.
