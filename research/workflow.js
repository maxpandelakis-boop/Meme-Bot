export const meta = {
  name: 'pick-rule-research',
  description: 'Test families of pick rules walk-forward on the big-test rows, then adversarially check the winners',
  phases: [
    { title: 'Explore', detail: 'one agent per rule family on the same data and harness' },
    { title: 'Verify', detail: 'skeptics re-run every candidate rule from its definition' },
  ],
}

// args: {research: absolute path of the repo's research/ directory, data: absolute path the data was unpacked to (get_data.sh)}
const RESEARCH = (args && args.research) || '/home/user/Meme-Bot/research'
const DATA = (args && args.data) || (RESEARCH + '/data')

const RULE = {
  type: 'object',
  properties: {
    name: { type: 'string' },
    definition: { type: 'string', description: 'the exact Python of the rule function over the row fields, runnable as is with the harness' },
    params: { type: 'number', description: 'how many free parameters or thresholds it has' },
    tried: { type: 'number', description: 'how many rule variants you evaluated before choosing this one' },
    k1: { type: 'object', properties: { n: { type: 'number' }, avg: { type: 'number' }, win: { type: 'number' }, zero: { type: 'number' }, ci_lo: { type: 'number' }, ci_hi: { type: 'number' }, positive_scans: { type: 'string' }, covered: { type: 'string' }, first_half_avg: { type: 'number' }, second_half_avg: { type: 'number' } }, required: ['n', 'avg', 'win', 'zero'] },
    k3: { type: 'object', properties: { n: { type: 'number' }, avg: { type: 'number' }, win: { type: 'number' }, zero: { type: 'number' }, ci_lo: { type: 'number' }, ci_hi: { type: 'number' }, positive_scans: { type: 'string' }, first_half_avg: { type: 'number' }, second_half_avg: { type: 'number' } }, required: ['n', 'avg', 'win', 'zero'] },
    verdict: { type: 'string', enum: ['adopt', 'maybe', 'noise'] },
    why: { type: 'string' },
  },
  required: ['name', 'definition', 'params', 'tried', 'k1', 'k3', 'verdict', 'why'],
}
const EXPLORE = {
  type: 'object',
  properties: {
    baselines: { type: 'string', description: 'the harness report lines for the baselines on this data' },
    rules: { type: 'array', items: RULE },
    observations: { type: 'array', items: { type: 'string' }, description: 'what the data says about this family even where no rule survives' },
  },
  required: ['baselines', 'rules', 'observations'],
}
const VERDICT = {
  type: 'object',
  properties: {
    name: { type: 'string' },
    reproduced: { type: 'boolean' },
    k1_avg: { type: 'number' }, k1_zero: { type: 'number' }, k1_ci_lo: { type: 'number' }, k1_ci_hi: { type: 'number' },
    bot_top1_avg: { type: 'number' }, bot_top1_zero: { type: 'number' },
    first_half_avg: { type: 'number' }, second_half_avg: { type: 'number' },
    leak_or_flaw: { type: 'string', description: 'any look-ahead, fitting on the evaluated scan, survivorship, or a definition that silently differs from what was reported; empty if none' },
    holds: { type: 'boolean', description: 'true only if the rule beats the bot top-1 on avg with zero rate not higher, the ci excludes the bot top-1 avg or both halves are positive, and no flaw was found' },
    note: { type: 'string' },
  },
  required: ['name', 'reproduced', 'holds', 'note'],
}

const FAMILIES = [
  { key: 'gates', prompt: 'Family: the GATES, i.e. hard filters before any ranking. The bot keeps market cap 50k..2M, liquidity >= 15k, 24h volume >= 15k, age 3..24 h, and drops crash/spike/copy/notmeme coins (row field why lists the fails). Test narrower and shifted windows (market cap bands, age bands such as 3-6, 6-12, 12-24 h, liquidity/mc ratio bands, volume/mc bands) as filters on the learnable rows, each as "all coins that pass this filter" (k = all) and as the top-1/top-3 by the bot score among them. Also test whether dropping a gate (e.g. letting 24-48 h coins in) helps. Keep the number of combinations small and state it.' },
  { key: 'momentum', prompt: 'Family: MOMENTUM and FLOW as the ranking among the gate passers (and among all learnable rows). Rank by one factor at a time: c1, c6, c24, m5, buyRatio1h, buyRatio6h, buyShare, vol1Share, vol6Share, buys1, buys24, gt.buyerRatio, gt.sellers24, jup.netBuyers1, jup.netBuyers24, jup.holderChg24, volMc, liqMc, both directions (highest first and lowest first). Then the best two-factor rank averages. Say for each whether it is "buy strength" or "fade" and whether the sign is stable across the two halves.' },
  { key: 'zero', prompt: 'Family: AVOIDING ZEROS. Find the factors and thresholds that separate coins that went to zero (gone) from those that did not, on the gate passers and on all learnable rows: liqMc, rc.top10, rc.top1, rc.insiders, rc.lp, dev.sold, dev.pct, jup.top10Pct, jup.organic, gt.sellers24, ageH, lp.other, ds.paid. Build a veto (fit thresholds on history only, walk-forward) and combine it with the bot score ranking; report what the veto costs in coverage and what it gains in avg and zero rate. Also test the current zero model idea: a simple logistic-free bin model fitted on history.' },
  { key: 'weights', prompt: 'Family: the SCORE. The bot ranks by a weighted sum of normalised factors with priors (liqMc +0.35, srcN +0.25, dev.sold -0.25, gp.risk -0.2, c6 -0.2, sw.lb +0.2, buyRatio1h +0.15, ...) blended with learned weights. Test: (a) the bot score as stored in row sc, (b) a rank-average of the 3 to 5 factors with the best walk-forward Spearman correlation to eur fitted on history only, (c) a simple ridge-like linear fit on history (stdlib only: normalise, solve small normal equations), (d) the sign-flipped score (worst score first) as a sanity check. Report whether any fitted model beats the stored score walk-forward.' },
  { key: 'value', prompt: 'Family: EXPECTED VALUE and "can it move". A pick needs about +8.5% to profit after fees, so a coin that cannot move (tiny volMc, tiny |c1|, |c6|) can only lose the fee. Test: require volMc above thresholds, require recent movement (|c6| or |c1| above thresholds), then rank by an expected value fitted on history: for bins of one or two factors, E[eur] on history, pick the bin with the highest history mean that has at least 30 history rows, walk-forward. Also test "pick the coin with the highest history win rate bin". Report coverage, because a strict rule may pick nothing in many scans.' },
]

phase('Explore')
const explored = await parallel(FAMILIES.map(fam => () => agent(
`You are a quantitative researcher testing pick rules for a Solana meme-coin paper-trading bot (fake money; the bot names one coin per hourly scan and buys nothing). Read ${RESEARCH}/BRIEF.md and ${RESEARCH}/RESULTS-2026-10-08.md first (replace RESEARCH_DIR with ${RESEARCH} and DATA_DIR with ${DATA}); it describes the data, the harness and the rules of evidence. The data is at ${DATA}/memesnapres (one JSON per scored snapshot chunk). Work with Python 3 (stdlib only) through Bash: start with \`python3 -I -c "import sys; sys.path.insert(0, '${RESEARCH}'); import harness as H; rows, scans = H.load('${DATA}/memesnapres', rule='m9-2h'); H.report(rows, scans)"\` and quote those baseline lines in your result.

${fam.prompt}

Method: write small scripts in ${DATA}/../work_${fam.key}/ (create it; never inside the repository), never modify harness.py or the data. For every rule you report, give its exact Python definition as a function rule(g, hist) over the row fields, its stats for k=1 and k=3 from H.evaluate plus H.bootstrap_ci and H.scan_consistency, and a split check (first half of scans vs second half: evaluate on each half separately with the same walk-forward). Be adversarial with yourself: say how many variants you tried, mark anything that is positive on one half only as noise, and never fit on the scan you evaluate. Report at most 5 rules, best first, and your observations. Return the structured result.`,
  { label: `explore:${fam.key}`, phase: 'Explore', schema: EXPLORE }
)))

const candidates = explored.filter(Boolean).flatMap(e => (e.rules || []).filter(r => r.verdict !== 'noise'))
log(`${candidates.length} candidate rules from ${explored.filter(Boolean).length} families`)

phase('Verify')
const verified = await parallel(candidates.map(r => () => agent(
`You are a skeptic. A researcher claims this pick rule beats the bot on the big-test data of a Solana meme-coin paper-trading bot (fake money). Your job is to REFUTE it. Read ${RESEARCH}/BRIEF.md (replace RESEARCH_DIR with ${RESEARCH}, DATA_DIR with ${DATA}), load the data with the harness (python3 -I, stdlib only, work in ${DATA}/../verify_${r.name.replace(/[^a-zA-Z0-9]+/g, '_').slice(0, 40)}/, never modify harness.py or the data), re-implement the rule EXACTLY from its definition below, and evaluate it walk-forward with H.evaluate (k=1 and k=3), H.bootstrap_ci, H.scan_consistency, and separately on the first and the second half of the scans. Compare with the bot's own top-1 (H.rule_bot_top, k=1) on the same scans. Look for look-ahead (anything using the evaluated scan's eur or mult), fitting on the evaluated scan, survivorship (rows dropped by the rule in a way that correlates with the outcome), thresholds tuned on the whole data, and definitions that differ from the reported stats. Default to holds=false when in doubt.

Rule name: ${r.name}
Claimed k=1: ${JSON.stringify(r.k1)}
Claimed k=3: ${JSON.stringify(r.k3)}
Parameters: ${r.params}, variants tried by the researcher: ${r.tried}
Definition:
${r.definition}

Return the structured result.`,
  { label: `verify:${r.name.slice(0, 30)}`, phase: 'Verify', schema: VERDICT }
)))

return { explored, candidates, verified: verified.filter(Boolean) }
