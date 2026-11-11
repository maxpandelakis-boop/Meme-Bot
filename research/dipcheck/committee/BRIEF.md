# The checker committee: hold or sell at the -20 % touch

You are one of three reviewers on a committee that gives a trading bot a second opinion. Fake money only (a research test).

## The situation in every case

The bot bought a Solana meme coin (a pump.fun coin that has left its bonding curve and trades on a DEX) for 50 EUR. Its rule
has a stop at -20 %. The price has just touched -20 % from the buy price, for the first time. Each case card shows everything
known at this moment: the buy numbers, the last 36 five-minute candles (closes in % of the buy price, volumes), the market, the
launch facts. Nothing after this moment. Names, addresses, dates and clock times are removed on purpose.

The committee decides, per case, one of two things:

- **SELL**: the stop sells now (at about -20 %, in fast falls lower).
- **HOLD**: the stop is loosened. The position is then sold at -50 % (floor), at 11x (take profit), or at the latest 6 hours
  after the buy, whichever comes first.

Fees: about 1 % on the buy and 1 % on the sell, so a trade must gain about 2 % to break even. HOLD only pays if the coin's path
from here, under the HOLD rule, ends higher than selling now.

## What older months say (the bot's own Pick-type buys, April to early September, 780 cases of this exact moment)

- 66.6 % came back to the buy price at some point within 24 h.
- 6.7 % reached 2x the buy price within 6 h of the buy; 20.1 % within 24 h; 0.9 % reached 10x within 24 h.
- 37.3 % fell to 10 % of the buy price or lower within 24 h.
- HOLD instead of SELL changed the result by -0.11 EUR per 50-EUR trade on average (HOLD was better in 35.5 % of the cases,
  worse in the rest). Average result after SELL -16.28 EUR, after HOLD -16.39 EUR.

So on average it does not matter; a checker is only useful if it can tell, case by case, which ones are worth holding.

## How to answer

For every case give: `p` = your probability (0 to 1) that HOLD ends with more money than SELL for this case; `vote` = "HOLD" or
"SELL"; `why` = a reason in at most 12 words. Vote HOLD only when you believe HOLD is the better choice for this case.

## Rules

- Judge every case yourself, by reading it. Do not write or run any code, do not use Bash, do not compute with tools.
- Use only the Read tool on the files you are given, and the Write tool for your answer files. Open no other file or folder.
- Answer every case, in the order of the file. Write valid JSON: a list of objects {"id": "....", "p": 0.00, "vote": "...", "why": "..."}.
