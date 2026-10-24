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

## Amendment 2 (24 Oct, ~11:15 UTC, before any fact result was read)

pump.fun's single-coin form answered 404 from GitHub's runners (run 1, 08:20-09:08 UTC), so run 1 got names and tickers only, from
GeckoTerminal (85 % of the coins in every window, the same 99.2 % of the time as history2's tickers, and missing about as often for
rockets and zeros). Run 2 found no form; run 3 (from 11:01 UTC) tries more forms and appears to be fetching. The reported result
is the one run on whatever launch facts are on branch rocketsmeta when run 3 ends; no run with real outcomes is made before that.
A fact counts as present in a window when at least 80 % of that window's entries have it (as in check_rockets.py).

## Amendment 3 (24 Oct, ~11:25 UTC, before any fact result was read)

The user asked (11:16 UTC) not to rely on pump.fun alone. A second source reads the launch facts from the chain
(research/rockets/meta_chain.py, branch rocketschain): name and ticker from the mint's own Token-2022 metadata (or a Metaplex
account), the creator wallet stored in pump.fun's bonding-curve account, the creation time from that account's oldest transaction
(for coins without history2's creation time; left empty for curves with more than 8,000 transactions), and the X / Telegram /
website links from the metadata file on IPFS. Each fact is taken from the first source that has it, in this order: history2,
the chain, pump.fun's API, GeckoTerminal (names only). The report says which source gave what. The reported run waits for both
fetches.

## Amendment 4 (24 Oct, ~11:35 UTC, before any fact result was read): media and the coin's picture

The user asked (11:27 and 11:28 UTC) to take media into account and to check whether the pictures matter ("sind ja Meme Coins").
Added facts, each known at the entry, buckets fixed now, tested exactly like F1-F11 (parts A-C, same split, same Holm and
Bonferroni over all facts together):

| # | fact | buckets |
|---|---|---|
| F12 | news of the day: a word of the name or ticker (4+ letters, upper/lower case ignored) is a word of one of the 1,000 most-read English Wikipedia articles of the day before the graduation (Wikimedia's free pageview API; Main_Page, Special: and the like left out) | yes / no |
| F13 | theme heat: graduations in the 24 hours before whose name shares such a word with this coin's name | 0 / 1-4 / 5-19 / 20+ |
| F14 | fresh post: the X link is a post (status), and the post's own time stamp (in its id) is at most 1 h / 1-24 h / older than 24 h before the coin's creation | no post / up to 1 h / 1-24 h / older |
| F15 | the coin's picture was already used: the same image file (same IPFS content id) is the picture of another graduation of the 7 days before | yes / no |
| F16 | how it was launched: the metadata file sits on IPFS and says createdOn pump.fun (pump.fun's own page) / anything else (launch and sniper tools, own hosts) | pump.fun / other |
| F17 | video coin: the metadata file has a video or animation link | yes / no |
| F18 | description length (characters) | 0 / 1-50 / 51-200 / over 200 |

Historic X mention counts, likes or follower numbers at launch need the paid X API (or LunarCrush's paid plan); they are not
tested, and today's counts would be hindsight. Google Trends has no free API reachable from here.

What the picture shows (blind sample, description only, not part of parts A-C): from the unseen windows w4 + w5, 150 rockets at
E = 5 and 150 other coins of the same windows (random, seed 7), pictures fetched from IPFS, shuffled, shown without any label as
numbered contact sheets and sorted by hand into fixed groups before the key is opened: animal / person (photo) / drawn or cartoon
character or known meme / text, logo or symbol / object, scene or other / no picture. Reported: the share of each group among
rockets and others, a chi-square test of the whole table and two-proportion tests per group with Holm. With 150 a side only large
differences (about 12 points or more) can show; a picture group that "matters" here is a lead for a bigger test, not a found rule.

## Amendment 5 (24 Oct, ~11:35 UTC, before any fact result was read): the pictures of all coins, not a sample

The user asked (11:30 and 11:32 UTC) for the picture check on more coins. So every coin whose metadata file names a picture gets
it read by an image model instead of only a hand-sorted sample (research/rockets/images.py, workflow rockets-images.yml, branch
rocketsimages): the picture is downloaded from IPFS, and OpenAI's CLIP model (openai/clip-vit-base-patch32, free, run on GitHub's
machines) scores it against six fixed descriptions. Added facts, tested exactly like F1-F18:

| # | fact | buckets |
|---|---|---|
| F19 | what the picture shows: the best-scoring of "a photo of a real animal" / "a cartoon drawing of an animal" / "a photo of a real person" / "a cartoon drawing of a person or character" / "a logo or text or symbol" / "a photo of an object or a place" | those six |
| F20 | animated picture (a GIF with more than one frame) | yes / no |
| F21 | look-alike picture: a picture of another graduation of the 7 days before is nearly the same (64-bit average hash, at most 4 bits apart) | yes / no |
| F22 | picture fits the name: how CLIP ranks the coin's own name ("a picture of <name>") against 20 other coins' names for this picture, 0 = worst, 1 = best | terciles of the fit windows |

The hand-sorted sample of amendment 4 becomes a check of the model instead: 120 pictures drawn at random (seed 7, no outcome
known or looked up), sorted by hand into the six groups before the model's groups are opened; reported as how often hand and
model agree. All facts F1-F22 share one Holm family in part A and one Bonferroni count in part B.

## Amendment 6 (24 Oct, ~12:20 UTC, before any fact result was read): every launch, not only the graduations

The user asked (11:30-11:35 UTC) for as many coins as possible ("500000+ am besten"). The five windows hold about 72,000
graduations, which is all of them, and only those have the price candles the money test needs. But pump.fun launches far more
coins than graduate: the chain shows 28,000-36,000 launches a day (probe of 24 Oct, research/rockets/launches.py), about 4
million in the windows. So a second universe is added for the launch facts only. There is no money test on it.

**Universe L.** pump.fun launches created in w2, w3, w4 or w5, leaving out each window's last 2 days (a coin needs time to
graduate). The sources are two free datasets on HuggingFace:
- w2 days (25 Jun to 13 Jul, without 3-4 Jul, the dataset's outage) come from Slinky21/Pumpfun_Memecoin_Corpus, tokens.parquet,
  MIT license, 798,430 launches from 5 Jun to 14 Jul.
- w3-w5 days (10 Aug to 19 Oct) come from Slinky21/Pumpfun_v2_dataset, the create events, CC-BY-4.0, read by its author's own
  node.

w1 has no free dataset, and reading its launch transactions on the chain runs at about 5 a second, so w1 is left out of
universe L. Fit windows w2 + w3, unseen windows w4 + w5.

Each dataset is used only if it passes all of these before any fact is computed (`launches.py verify`, result on branch
rocketsprobe):
1. In random hours (seed 7), at least 95 % of the chain's own launches (successful transactions signed by pump.fun's mint
   authority) are in the dataset.
2. Of 300 random rows checked against the chain, at least 98 % have the same name, ticker and creator, where the chain has them.
3. At least 95 % of our graduations of its days are in it.

A dataset that fails is dropped, its window leaves universe L, and the report says so.

**Outcome L1, graduated.** The dataset's own graduation record (v2 graduate events, the corpus's graduated_at) or our
graduation list. From the curve's start price a graduation is about a 15x, so L1 means "went 10x or more from its first price".
For the metadata sample below, the curve account's complete flag is also read from the chain, and any disagreement is reported.

**Outcome L2, took off later (could still be bought).** Graduated at least 10 minutes after the launch. Launches that graduated
within 10 minutes are left out of L2: these are bundled, instant curves that nobody but the launcher could buy cheaply. All
launches that did not graduate are the negatives.

**Facts.** Each is known at the launch and its buckets are fixed now.
- From the dataset rows, for every launch:
  - L-F1: the creator's earlier launches in the 30 days before (0 / 1-2 / 3-20 / over 20).
  - L-F1b: the creator's earlier graduations in the 30 days before (0 / 1-2 / 3+).
  - L-F4: a launch of the 7 days before with the same ticker graduated (yes / no).
  - L-F5: CJK script.
  - L-F6: hour of the launch, UTC.
  - L-F7: weekend.
  - L-F8: launches in the hour before (terciles of the fit windows).
  - L-F9: SOL/USD change over the 24 h before (terciles of the fit windows).
  - L-F13: theme heat, meaning graduations of the 24 h before that share a name word.
  - Counts are made inside universe L. The corpus may miss some launches, so in w2 the counts can come out low; that biases
    towards finding nothing, not towards a false find.
- From the metadata file on IPFS, for a random 600,000 launches of universe L (seed 7):
  - L-F10, L-F11: links and X link type.
  - L-F12: news of the day.
  - L-F14: fresh post.
  - L-F15: picture already used by a graduation of the 7 days before.
  - L-F16: launched on pump.fun's own page.
  - L-F17: video.
  - L-F18: description length.
  - All buckets as F10-F18.
- From the picture, for a random 150,000 of those (seed 7): L-F19 to L-F22, as F19-F22.

**Test.**
- Part A as before: the favoured bucket is picked on w2 + w3 among buckets with at least 200 launches, then a one-sided z test
  on w4 + w5. This is done for L1 and L2, with Holm over all L-facts × {L1, L2}.
- The sample is so large that tiny differences pass, so a launch fact only "matters" if it passes Holm AND its rate ratio on
  the unseen windows has a 95 % interval (bootstrap over days) with a lower end of at least 1.25.
- Part C: the LightGBM of Part C, with the same settings, on all L-facts of the metadata sample. It is trained on w2 + w3 and
  judged on w4 + w5 by AUC (95 % interval, bootstrap over days) and by the L2 rate of its top 1 / 2 / 5 %.

**No money test on universe L.** A buy on the bonding curve before graduation cannot be simulated from our candles. A launch
fact that matters is a lead only. The money test stays on the graduations, where F1-F22 are already registered, and nothing new
is picked for it from universe L.

Not used: Dune, Flipside and Bitquery (they need an account and key), pump.fun's API (it answers 404/403/530 from GitHub's
runners), and the paid datasets (pumpdata.fun, Gumroad).
