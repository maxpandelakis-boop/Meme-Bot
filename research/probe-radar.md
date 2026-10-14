# WP0 probe: what the launch radar's sources really serve (fake money only)

Two runs of `.github/workflows/probe-radar.yml` (`research/probe_radar.py`) on GitHub's own runners, 2026-10-13, started by hand
(`workflow_dispatch` only, `permissions: contents: read`, read-only everywhere):

| Run | Started (UTC) | Length | Result | Link |
|---|---|---|---|---|
| 1 | 22:40:41 | 564 s | success | https://github.com/maxpandelakis-boop/Meme-Bot/actions/runs/38479363452 |
| 2 | 22:54:55 | 581 s | success | https://github.com/maxpandelakis-boop/Meme-Bot/actions/runs/38480898854 |

Run 2 is the same probe with three script fixes after run 1: the coin's dev taken from the pump.fun list row when the single-coin
route fails, top-holders and RugCheck asked for more coins, and an RPC rate test that measures how long a block lasts.

Adapted from SPEC 5 WP0: no throwaway branch (the workflow sits on the working branch with `workflow_dispatch` only, so nothing runs
on a push); check 9 skipped (it needs a write; a read-only hint is logged); check 8 read-only against the existing branch `live`;
check 10 prints yes/no only. The logs hold only status codes, field names, counts, timings and rate-limit headers; no address, no body
over 160 characters, no credential (checked: the only 32+ character base58 runs in either log are the commit SHA).

---------------------------------------------------------------------------------------------------------------------------

## 1 GeckoTerminal minute history of real paper windows

`/networks/solana/pools/{pair}/ohlcv/minute?aggregate=1&limit=400&before_timestamp=<end+120 s>&currency=usd&token=base`, then
`aggregate=15&limit=30`, 10 s apart. Same four windows in both runs (three paper positions since the restart, plus the oldest stored
position as a depth test).

| Window | Age at probe | m1 status | m1 candles | m1 in the 6 h window | First / last m1 in window (min after entry) | m15 status | m15 in window |
|---|---|---|---|---|---|---|---|
| ~24 h | 23.6-23.9 h | 200, 200 | 105 | 55 | -0.9 / 329.1 | 200, 200 | 17 of 22 |
| ~48 h | 47.7-47.9 h | 200, 200 | 280 | 217 | -0.7 / 359.3 | 200, 200 | 25 of 30 |
| ~75 h | 75.2-75.4 h | 200, 200 | 400 | 328 | -0.2 / 359.8 | 200, 200 | 25 of 30 |
| oldest (before the restart) | 106.0-106.2 h | 200, **429** | 400 (run 1) | 230 | -0.7 / 228.3 | **429**, 200 | 15 of 30 |

- Minute history is there for every window up to 106 h (4.4 days). GT leaves out minutes without trades, so a quiet pool gives fewer
  than 360 candles (55 for the 24 h window, whose trading stopped about 30 min before the end).
- 429s: 1 of 16 GT calls in each run, both on the 7th or 8th call, at a 10 s gap, `retry-after: 0`, no `x-ratelimit-*` headers.
- **Decision (peak.py):** keep the 10 s gap; on a 429 wait 15 s, then 30 s, then 60 s and retry the same window; after that try
  `aggregate=15`; the m1 backfill can wait at least 4 days, so the spec's "est after 48 h past the end" is safe.

## 2 Discovery coverage

4 cycles 150 s apart per run (8 cycles, about 20 minutes of launches with the 10-minute look-back). A pool counts as "fresh" when its
first non-curve DexScreener pair (`tokens/v1`, 30 a request, pool-age cache) was under 10 min old when the source listed it.
"Sole" = no other radar-set source listed it. Extra sources (pf:top, Jupiter trending/traded 1h) were measured for comparison only.

| Source | Calls (both runs) | Status | Candidates per cycle | Fresh pools found | of them liq >= $5k | Sole | First to list | Median pool age when listed (min) |
|---|---|---|---|---|---|---|---|---|
| pf:graduated p1-4 | 32 | all 200 | 144-170 | 17 | 16 | 5 | 16 | 2.08 / 1.70 |
| pf:new p1-2 | 16 | all 200 | 99-100 | 8 | 8 | 0 | 1 | 1.96 / 1.53 |
| gt:new_pools p1-2 | 16 | all 200 | 19-37 | 7 | 6 | 3 | 3 | 1.34 / 3.42 |
| jup:recent | 8 | all 200 | 30 | 3 | 3 | 3 | 3 | 0.60 / 0.78 |
| ds:token-profiles | 8 | all 200 | 24-25 | 3 | 2 | 0 | 0 | 7.54 / 3.45 |
| ll:new (LaunchLab) | 8 | all 200 | 100 | 0 | 0 | 0 | 0 | - |
| rc:new_tokens | 8 | all 200 | 10 | 1 | 1 | 0 | 0 | 0.54 |
| pf:top p1-2 (extra) | 16 | all 200 | 100 | 0 | 0 | - | 0 | - |
| jup:trending1h (extra) | 8 | all 200 | 100 | 3 | 3 | - | 0 | 3.96 |
| jup:traded1h (extra) | 8 | all 200 | 100 | 4 | 4 | - | 0 | 3.48-3.96 |

| Totals | Run 1 | Run 2 |
|---|---|---|
| Fresh pools (liq >= $5k) | 13 (12) | 10 (9) |
| Found by the radar set / only by an extra source | 13 / 0 | 10 / 0 |
| Median pool age at first sight | 2.05 min | 1.70 min |
| DEX of the fresh pools | pumpswap 12, meteora 1 | pumpswap 7, meteora 3 |
| Mint time known from | pf 11, jup 1, unknown 1 | pf 6, jup 2, unknown 2 |
| Mint to pool (s): n, median, under 60 s | 12, 27, 8 | 8, 1.5, 6 |
| Cycle length: first / later | 28.1 s / 19.1-19.5 s | 30.5 s / 20.9-21.6 s |
| DexScreener per cycle: asked, calls | 573 in 20, then 276-293 in 10 | 573 in 20, then 294-324 in 10-11 |

- No extra source found a fresh pool the radar set missed. pf:graduated carries most (17 of 23); gt:new and jup:recent each found 3
  that nobody else listed in time; jup:recent lists earliest.
- LaunchLab new found none in 8 cycles (its coins are still on the curve); rc:new_tokens found one that others also had.
- 14 of the 20 fresh pools with a known mint time opened under 60 s after the mint (the `instant_pool` hard trap), so greens will be
  rare, as VETO-3 expects.
- About 23 fresh pools in 2 x ~17.5 minutes of launches: roughly 40 an hour with liq >= $5k, about twice the spec's "about 20
  records/hour". Budgets that scale per coin (RugCheck, RPC, pump.fun deep calls) must keep their per-cycle caps.
- **Decision (3.2):** discovery = pf graduated p1-4, pf new p1-2, GT new_pools p1-2, Jupiter recent, DS token-profiles (cheap, and it
  carries the paid-profile signal). LaunchLab new and RugCheck new_tokens off by default. Mint time: pf list row first, then
  Jupiter `createdAt`, then `/coins-v3/{mint}`, then RPC (row 7).

## 3 pump.fun coin and dev history

| Call | Status (run 1 / run 2) | ms | Rate-limit headers | Result |
|---|---|---|---|---|
| frontend-api-v3 `/coins/{mint}` | 404 / 404 | 42-60 | none | "Cannot GET /coins/<mint>": **the route is gone**, not a missing coin |
| frontend-api-v3 `/coins-v3/{mint}` | - / 200 | 119 | limit 60, reset 60 | 59 fields: `created_timestamp` (ms), `creator`, `twitter`, `website`, `pump_swap_pool`, `pool_address`, `complete`, `last_trade_timestamp`, `ath_market_cap`, `canonical_pool_liquidity_usd`, `volume_1h_usd`, `security_verdict`, `program`, `protocol`. No graduation time field (no `king_of_the_hill_timestamp`) |
| advanced-api-v2 `/coins-v3/{mint}`, `/coins/metadata/{mint}` | - / 530, 530 | 75-113 | none | Cloudflare error 1016 (origin DNS) |
| pf list rows (`/coins?...`) | 200 | | | the same core fields as coins-v3 (creator, created_timestamp, pump_swap_pool, pool_address, complete, twitter, website, program, protocol) |
| `/coins?creator=<dev>&sort=created_timestamp` | 200 x 3 devs | 84-136 | | strict filter: 28 of 28, 1 of 1, 9 of 9 rows had that creator; history reaches back about a year (8,855 h); serial dev: 28 launches, 3 complete, 28 under $10k mc |
| frontend-api-v3 `/coins-v2/user-created-coins/{dev}` | 200 x 3 | 96-162 | limit 60, reset 60 | `{coins, count, limit, offset}`; `count` = the dev's total (28, 1, 9) |
| frontend-api-v3 `/coins/user-created-coins/{dev}` (v1 path) | 404 x 3 | 63-123 | | route gone |
| advanced-api-v2 `/coins-v2/user-created-coins/{dev}` | 530 x 3 | 51-77 | | Cloudflare 1016 |

**Decision (dev-history adapter):** `/coins?creator=` (one call, 50 newest launches with `complete` and `usd_market_cap`, so "dead"
and "graduated" can be counted) plus `/coins-v2/user-created-coins/{dev}` only for the total `count` when 50 rows come back. Both on
frontend-api-v3, 60 a minute. Single-coin facts from the list row; `/coins-v3/{mint}` only for coins not in a pf list.

## 4 swap-api trades and candles

| Call | Coin | Status | ms | Rate-limit headers | Result |
|---|---|---|---|---|---|
| `/v2/coins/{mint}/trades?limit=100` | graduated, pool 3.6-4.9 min | 200 x 2 | 58-158 a page | limit 1000, reset 60 | 100 rows a page (not 20), newest first, `pagination {hasMore, limit, nextCursor}`, cursor paging works; 4 pages = 400 trades covered only the last 1.4-3.6 min; fields `amountSol, amountUsd, baseAmount, fillPriceSol, fillPriceUsd, priceSol, priceUsd, program, quoteAmount, slotIndexId, timestamp, tx, type, userAddress`; `slotIndexId` 22 digits (12-digit slot + 10-digit index) on every row; `program` `pump_amm`; 198 wallets in 400 trades (run 1) |
| same, `&program=pump` | graduated (run 2) | 200 | 140 | | the filter is ignored: 300 rows, all `pump_amm`; the launch was not reached |
| `/v2/coins/{mint}/trades?limit=100` | on the curve, about 1 min old | 200 x 2 | 76-133 | | 45-58 rows, one page, oldest trade at the mint second; first 30 s: 44 trades, 23 buys, 7 wallets |
| `/v2/coins/{mint}/candles?interval=1m&limit=100&currency=USD&createdTs=<ms>` | both | 200 x 4 | 87-380 | limit 1000 | `{timestamp(ms), open, high, low, close, volume}`, oldest first, the first candle is the mint minute (-0.1 to -0.9 min), so the curve phase is included; 35 candles for a 34-min-old coin |
| `/v1/coins/{mint}/candles?interval=1m&limit=100&currency=USD` | both | 200 x 4 | 76-366 | limit 1000 | identical to v2 |

**Decisions:** staircase-before-pool from swap-api candles (on). Sniper/bundle from launch trades only when the launch is reachable
within 3 pages (coins with at most about 300 trades); otherwise "too many trades, not checked" (unknown, never "no"). The
top-holders `enteredAt` (row 5) gives a second sniper estimate without paging.

## 5 Holders and funding

| Call | Coins | Status | ms | Rate-limit headers | Result |
|---|---|---|---|---|---|
| frontend-api-v3 `/coins/top-holders/{mint}` | 5 coins (fresh x3, curve, one 30-240 min old) | 200 x 5 | 97-195 | limit 60, reset 60 | `{topHolders, totalHolders}`, 50 holders (1 on the curve coin), item fields `address, amount, enteredAt, fundingSource, isBundler, isDev, isSniper`; `enteredAt` filled for 46-50 of 50 (run 2); `isBundler` true on 5 holders of one fresh coin; `isSniper` and `isDev` never true; `fundingSource` null on every holder |
| advanced-api-v2 `/coins/top-holders/{mint}` | the same 5 | 200 x 5 | 128-223 | limit 60, reset 60 | identical answers |
| advanced-api-v2 `/coins/top-holders-and-sol-balance/{mint}` | 1 per run | 200 x 2 | 76-132 | | `{topHolders, totalHolders}` |
| advanced-api-v2 `POST /wallet-overview` (10 wallets) | | 530 x 2 | 33-85 | | Cloudflare 1016 |
| frontend-api-v3 `POST /wallet-overview` | | 404 x 2 | 64-102 | | "Cannot POST /wallet-overview" |

**Decisions:** top-holders on (one host is enough; frontend-api-v3 first, advanced-api-v2 as the fallback; 60 a minute each). Use
`enteredAt` and `amount` for "share bought in the first 30 s" and `isBundler` as info. `isSniper`, `isDev` and `fundingSource` are not
served without a login: never read them as "no". `wallet-overview` off: fresh-holder age and funding come from the RPC (row 7).

## 6 RugCheck report fields

`/v1/tokens/{mint}/report` (and `/report/summary` once per pass), 1-2 s apart.

| Report | Pool age | Status | ms | `creator` | `creatorTokens` | `insiderNetworks` (sizes) | `graphInsidersDetected` | `topHolders` (insider) | Risks |
|---|---|---|---|---|---|---|---|---|---|
| run 1 fresh | 4.96 min | 200 | 353 | yes | null | null | 0 | 20 (0) | warn: High holder correlation |
| run 1 same coin later | 9.73 min | 200 | 1,842 | yes | null | null | 0 | 20 (0) | danger: Low Liquidity |
| run 2 fresh | 3.79 min | 200 | 485 | yes | null | 3 (71, 5, 4) | 80 | 20 (0) | none |
| run 2 fresh | 2.62 min | 200 | 472 | yes | null | null | 0 | 20 (0) | warn: High holder correlation |
| run 2 fresh | 2.25 min | 200 | 471 | yes | null | null | 0 | 20 (0) | warn: High holder correlation |
| run 2 same coin later | 8.45 min | 200 | 469 | yes | null | 3 (71, 5, 4) | 80 | 20 (0) | none |
| run 2 older | 85.9 min | 200 | 458 | yes | null | 1 (4) | 4 | 20 (0) | none |
| run 2 older | 97.4 min | 200 | 433 | yes | null | null | 0 | 9 (0) | danger: Low Liquidity |

- Rate-limit headers `x-rate-limit-limit: 15`, `x-rate-limit-remaining: 14` on every call (no 429 in 20 RugCheck calls over both runs); report summary fields
  `lpLockedPct, risks, score, score_normalised, tokenProgram, tokenType`.
- Report fields: `creator, creatorBalance, creatorTokens, deployPlatform, detectedAt, events, fileMeta, freezeAuthority,
  graphInsidersDetected, insiderNetworks, knownAccounts, launchpad, lockerOwners, lockerScanStatus, lockers, markets, mint,
  mintAuthority, price, risks, rugged, score, score_normalised, token, tokenMeta, tokenProgram, tokenType, token_extensions,
  topHolders, totalHolders, totalLPProviders, totalMarketLiquidity, totalStableLiquidity, transferFee, validation, verification`.
- `insiderNetworks` item fields: `activeAccounts, currentHolding, id, size, tokenAmount, type`.
- **Decisions:** a report is there for pools 2-10 min old (6 of 6 reports, 4 coins). `creatorTokens` was null in 8 of 8, so the dev history comes
  from pump.fun (row 3), not RugCheck. `holder_cluster` reads `graphInsidersDetected` / `insiderNetworks[].size` (filled on 3 of 8);
  null means "no network found", which RugCheck also reports as `graphInsidersDetected: 0`. The topHolders `insider` flag was never
  true (0 of 149 holders): do not use it.

## 7 Solana public RPC

| Call | Status | Time | Result |
|---|---|---|---|
| `getSignaturesForAddress(dev, limit 1000)` | 200 | 3.3 s | 76 signatures, one page, oldest 26.9 h: the dev wallet age in one call |
| `getSignaturesForAddress(mint, limit 1000)`, up to 3 pages | 200 x 6 | 1.6-2.2 s | run 1: 2,717 signatures, reached the mint (7 min old); run 2: 3,000, not reached (coin minted 34 min before) |
| `getSignaturesForAddress(top holder, limit 1000)` | 200 x 2 | 0.9-3.9 s | 1,000 (not exhausted), oldest 264 h and 683 h: one page already shows "not fresh" |
| `getTransaction(oldest signature, v0, json)` | 200 x 2 | 0.3-2.0 s | fields `blockTime, meta, slot, transaction, transactionIndex, version`; 7-15 account keys; fee payer is not the holder (the funder shows) |
| 15 calls at a 1.1 s gap | 15 x 200 | 19.8 s | `x-ratelimit-method-remaining` fell to 2 |
| back-to-back (run 1, fresh budget) | 10 x 200, then 429 | 0.84 s | `retry-after: 10`; 20 more calls at 0.5 s all 429 |
| back-to-back (run 2, after the paced run) | 3 x 200, then 429 | 0.64 s | the next call 2.1 s later was 200 again |

Headers on every answer: `x-ratelimit-tier: free`, `x-ratelimit-method-limit: 10`, `x-ratelimit-rps-limit: 250`,
`x-ratelimit-conn-limit: 40`. **The binding limit is 10 calls per method per 10 s (a sliding window), counted per IP;**
getTransaction has its own 10.

**Decisions:** RPC gap 1.1 s per method (fetch.py's 0.3 s is too fast for more than 10 calls in a row); radar cap 15 calls a cycle
stays; on a 429 skip the RPC for the rest of the cycle. Dev wallet age: one call (on). Fresh holders: one call a holder; under 1,000
signatures gives the age, 1,000 with an oldest older than 1 day means "not fresh" (on, cached forever). Funding: getTransaction of
the oldest signature only for fresh holders (on, at most 5 a cycle). Mint time from the RPC only as the last fallback, at most 3 pages,
unknown when not reached.

## 8 GitHub contents API, unauthenticated (read-only, branch `live`)

`GET /repos/{repo}/contents/live.json?ref=live` with `Accept: application/vnd.github.raw+json`.

| Step | Run 1 status, `x-ratelimit-used` | Run 2 status, `x-ratelimit-used` |
|---|---|---|
| plain | 200, 4 | 200, 14 |
| `If-None-Match: <etag>` | 304, 5 | 304, 15 |
| `If-None-Match: <etag>` | 304, 6 | 304, 16 |
| plain | 200, 7 | 200, 17 |
| `git/matching-refs/heads/live` plain, then conditional | 200 (8), 304 (9) | 200 (18), 304 (19) |

`x-ratelimit-limit: 60`, `x-ratelimit-resource: core`, `cache-control: public, max-age=60, s-maxage=60`, ETag present.

**Every 304 counted** (+1 each time, both endpoints, both runs). **Decision (page poll):** the shared budget counts every GitHub
request, 304 or not; keep the radar poll at `max(doc.next + 15 s, last + 150 s)` (24 an hour on the Radar tab, 12 on Office) inside
the shared 60 an hour with RESERVE 10. A conditional request does not buy extra polls.

## 9 raw.githubusercontent.com freshness (skipped: needs a push)

Read-only hint from the same `live` doc: `cache-control: max-age=300`; the plain URL was `x-cache: MISS`, then the same file with a
fresh `?m=<minute>` was `x-cache: HIT` in both runs, so the CDN seems to ignore the query string. **Decision (fallback label):**
treat raw as up to 5 minutes old whatever the query; the card shows "as of HH:MM" from the doc's own `t` (as SPEC 6.1 already says).

## 10 Supabase

| Secret | Set |
|---|---|
| SUPABASE_URL | yes |
| SUPABASE_PUBLISHABLE_KEY | yes |
| SUPABASE_SECRET_KEY | yes |

**Decision (smoke test plan):** the WP6 radar smoke test checks the Supabase `live` row `radar` and the page's `supabase` transport.

## Calls per host (both runs)

| Host | Calls | Status | Avg ms |
|---|---|---|---|
| api.dexscreener.com | 109 | 109 x 200 | 47-140 |
| frontend-api-v3.pump.fun | 83 | 76 x 200, 7 x 404 (gone routes) | 90-164 |
| api.mainnet-beta.solana.com | 62 | 40 x 200, 22 x 429 (all from the rate tests) | 111-587 |
| api.geckoterminal.com | 32 | 30 x 200, 2 x 429 | 161-191 |
| lite-api.jup.ag | 24 | 24 x 200 | 119-165 |
| swap-api.pump.fun | 21 | 21 x 200 | 115-172 |
| api.rugcheck.xyz | 20 | 20 x 200 | 472-542 |
| advanced-api-v2.pump.fun | 14 | 7 x 200, 7 x 530 | 75-119 |
| api.github.com | 12 | 6 x 200, 6 x 304 | 56-120 |
| launch-mint-v1.raydium.io | 8 | 8 x 200 | 368-473 |
| raw.githubusercontent.com | 4 | 4 x 200 | 63-99 |

---------------------------------------------------------------------------------------------------------------------------

## ADAPTERS (on/off defaults for WP3; an adapter that is off stays in code and still self-tests at run time, SPEC 5.3 / I5)

```python
ADAPTERS = {
    # discovery, every cycle (3.2)
    "pf_graduated":       True,   # frontend-api-v3 /coins complete=true sort=last_trade_timestamp, pages 1-4: 17 of 23 fresh pools, 5 sole
    "pf_new":             True,   # frontend-api-v3 /coins sort=created_timestamp, pages 1-2: 8 of 23; also feeds the X-link index and the dev log
    "gt_new_pools":       True,   # GT new_pools pages 1-2: 7 of 23, 3 sole; shares the 10 s GT gap
    "jup_recent":         True,   # lite-api.jup.ag tokens/v2/recent: 3 of 23, 3 sole, earliest (median 0.6-0.8 min); has createdAt and dev
    "ds_profiles":        True,   # DS token-profiles/latest/v1: 3 of 23, 0 sole, late; kept for the paid-profile signal (1 call)
    "ll_new":             False,  # LaunchLab get/list?sort=new: 0 fresh pools in 8 cycles
    "rc_new_tokens":      False,  # RugCheck stats/new_tokens: 1 of 23, never sole; keeps the RugCheck budget for reports
    # tier 1
    "rc_report":          True,   # RugCheck /tokens/{mint}/report: 200 on 8 of 8 (pools 2-97 min old); creator, topHolders, risks, graphInsidersDetected
    "rc_insider_networks": True,  # insiderNetworks[].size / graphInsidersDetected for holder_cluster (filled on 3 of 8; 0 or null = none found)
    "rc_creator_tokens":  False,  # creatorTokens null in 8 of 8 reports: dev history comes from pump.fun
    "pf_coin_v3":         True,   # frontend-api-v3 /coins-v3/{mint} (59 fields) for coins not in a pf list; /coins/{mint} is gone (404)
    "ds_orders":          True,   # DS orders/v1 (paid), as fetch.py does today (not re-probed)
    # tier 2
    "pf_dev_history":     True,   # frontend-api-v3 /coins?creator=<dev> (strict, 3 of 3 devs) + /coins-v2/user-created-coins/{dev} count; 60/min
    "pf_top_holders":     True,   # frontend-api-v3 /coins/top-holders/{mint} (advanced-api-v2 as fallback): 50 holders with enteredAt; 60/min
    "pf_holder_flags":    False,  # isSniper / isDev never true, fundingSource always null without a login: never read as "no"
    "pf_wallet_overview": False,  # POST wallet-overview: 530 (Cloudflare 1016) on advanced-api-v2, 404 on frontend-api-v3
    "pf_advanced_coin":   False,  # advanced-api-v2 coins-v3 / coins/metadata / coins-v2/user-created-coins: 530
    "swap_trades":        True,   # swap-api /v2/coins/{mint}/trades?limit=100: 100 rows a page, newest first, cursor, slotIndexId;
                                  # launch reached only within 3 pages, else "not checked" (program=pump filter is ignored)
    "swap_candles":       True,   # swap-api /v1 (or /v2) candles interval=1m: oldest first, ms, from the mint minute (curve phase included)
    "rpc_dev_age":        True,   # getSignaturesForAddress(dev): one page gave the wallet age (76 signatures)
    "rpc_holder_age":     True,   # one call a top-10 holder: < 1000 signatures gives the age, 1000 with an old oldest means not fresh
    "rpc_funding":        True,   # getTransaction(oldest signature) for fresh holders only, at most 5 a cycle
    "rpc_mint_time":      True,   # last fallback after pf / Jupiter / coins-v3; at most 3 pages; unknown when not reached (run 2: 3000 not enough)
    # candles, page, other jobs
    "gt_m1_backfill":     True,   # GT minute candles exist for windows up to 106 h old; 1 in 16 calls 429 at a 10 s gap
    "gh_contents_poll":   True,   # every 304 counts against the 60/h: budget every request
    "raw_fallback":       True,   # max-age 300, ?m= does not bust the CDN cache: label by the doc's own t
    "supabase":           True,   # all three secrets are set
}
RPC_GAP_S = 1.1            # 10 calls per method per 10 s (sliding), retry-after 10; fetch.HOST_GAP's 0.3 s is too fast for > 10 calls
GT_429_LADDER_S = (15, 30, 60)   # then aggregate=15
```

## Hand-off notes

- **WP3 (radar):** apply `ADAPTERS` and `RPC_GAP_S`. Expect about 40 fresh pools an hour with liq >= $5k (not 20); keep the
  per-cycle caps. Cycle 0 takes about 30 s because the pool-age cache is empty (20 DexScreener calls for about 570 candidates); later
  cycles about 20 s (10 calls). The pf list row already carries creator, created_timestamp, twitter, website, pump_swap_pool,
  pool_address and complete: no per-coin pump.fun call for listed coins. 70% of fresh pools (14 of 20) are instant pools.
- **WP2 (peak.py):** GT minute history holds for at least 106 h; use `GT_429_LADDER_S` before falling back to aggregate 15.
- **WP5b (page):** the contents API counts 304s; raw ignores the query string; both already fit SPEC 6.1 when every request is
  counted.
- **Not checked here:** raw freshness after a push (check 9, needs a write); whether `swap-api` `createdTs` on trades can page from
  the oldest trade (the sniper adapter would then need one page instead of many); DS orders/v1 (used by fetch.py today, unchanged).
