#!/usr/bin/env python3
"""filter_team.py: the gates as a team of single bots, each with its own report card (fake money only: nothing here buys, sells or advises).

Each bot owns one job of the hard gates (memebot.gates' why tags). Its report card asks the one question that counts for a gate: the coins
that ONLY this bot threw out of a scan, did they do worse than the coins every bot let through? Counted per coin (the bot buys a coin once:
each coin's mean result over its scans, the lesson of research/HISTORY-2026-10-21.md), in the training's window, with a coin bootstrap of
the difference. The Scorer is the last member: the bot's own pick (its rank 1) against the other gate passers of the same scans.

  light  good   the interval of (thrown out minus let through) lies wholly below zero: the bot earns its place
         bad    it lies wholly above zero: the bot throws away better coins than it keeps
         warn   it crosses zero: not proven either way
         idle   fewer than MIN_COINS coins on one side

report.py feeds every scored chunk it already reads (collect's one pass over memesnapres) into a Team and renders section() in place of the
old coin test on the Pick tab. Standard library only; never raises into the page (report.safe wraps it).
"""
import math, random

TEAM = (   # id, name, job, the why tags it owns
    ("pool", "Pool Inspector", "a real, sellable DEX pool", ("price", "curve", "nodex", "honeypot")),
    ("fake", "Fake Detector", "copycats, non-memes, paid lists only", ("copy", "notmeme", "paid")),
    ("age", "Age Clock", "the profile's age window", ("young", "old")),
    ("size", "Size Gauge", "the market-cap band", ("mc",)),
    ("liq", "Liquidity Guard", "enough liquidity to get out", ("liq", "liqmc")),
    ("vol", "Volume Checker", "real trading, no wash", ("vol", "wash")),
    ("chart", "Chart Scanner", "no crash, no spike right now", ("crash", "spike")),
    ("flow", "Buyer Counter", "buyers and volume in the last hour", ("nobuyers", "novol1h")),
)
OWNER = {t: b[0] for b in TEAM for t in b[3]}
LEARN_FROM = 1791380700000   # 2026-10-07 13:45 UTC: chunks scored before it counted every unpriced coin as gone (harness.LEARN_FROM)
MIN_COINS = 20
BOOT_N, BOOT_SEED = 1000, 7
CLIP = (-20.0, 60.0)
# the long-history check (research/GATES-2026-10-21.md, research/HISTORY-2026-10-21.md, June and July 2026, per coin): one line per gate
HISTORY = {"crash": "June/July, crash: thrown-out coins did better on average (−2.20 vs −3.57 €), but as picks they did worse", "mc": "June/July, market cap: coins under $100k did better on average (−2.02 vs −3.57 €), but as picks they did worse",
           "spike": "June/July, spike: thrown-out coins did worse, not proven (−5.06 vs −3.57 €)", "wash": "June/July, wash: no difference (−3.87 vs −3.57 €)",
           "liqmc": "June/July, liquidity share: no difference per coin (−3.50 vs −3.50 €)"}


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


class Team:
    """Per-coin accumulators: passers, each bot's lone vetoes (per bot and per tag), the Scorer's top 10. Small: one entry per coin."""

    def __init__(self, rule, since=None):
        self.rule, self.since = str(rule or ""), since
        self.passed, self.top, self.rest = {}, {}, {}
        self.alone = {b[0]: {} for b in TEAM}
        self.tag = {}
        self.t0s = set()
        self.last = {"t0": None, "alone": {}}

    @staticmethod
    def _add(acc, a, eur, zero):
        s = acc.get(a)
        if s is None:
            acc[a] = [eur, 1, zero]
        else:
            s[0] += eur
            s[1] += 1
            s[2] = s[2] or zero

    def feed(self, doc):
        """One scored chunk (a memesnapres doc). Chunks of another profile, older than the window or scored before LEARN_FROM are skipped."""
        if not isinstance(doc, dict) or str(doc.get("rule") or "") != self.rule:
            return
        t0, t1 = _num(doc.get("t0")), _num(doc.get("t"))
        if t0 is None or (t1 or 0) < LEARN_FROM or (self.since is not None and t0 < self.since):
            return
        self.t0s.add(t0)
        newest = self.last["t0"] is None or t0 > self.last["t0"]
        if newest:
            self.last = {"t0": t0, "alone": {}}
        for c in doc.get("coins") or []:
            if not isinstance(c, dict):
                continue
            eur, a = _num(c.get("eur")), c.get("a")
            if eur is None or not a:
                continue
            eur = min(max(eur, CLIP[0]), CLIP[1])
            zero = bool(c.get("gone")) or (_num(c.get("mult")) or 0.0) < 0.02
            why = [str(w) for w in (c.get("why") or [])]
            if c.get("pass") and not why:
                self._add(self.passed, a, eur, zero)
                rank = _num(c.get("rank"))
                self._add(self.top if rank == 1 else self.rest, a, eur, zero)
                continue
            owners = {OWNER.get(w) for w in why}
            if len(owners) != 1 or None in owners:
                continue                       # thrown out by several bots (or an unknown tag): nobody's lone call
            b = owners.pop()
            self._add(self.alone[b], a, eur, zero)
            if len(set(why)) == 1:
                self._add(self.tag.setdefault(why[0], {}), a, eur, zero)
            if t0 == self.last["t0"]:
                self.last["alone"][b] = self.last["alone"].get(b, 0) + 1


def _means(acc):
    return [s[0] / s[1] for s in acc.values()], sum(1 for s in acc.values() if s[2])


def boot_diff(a, b, n=BOOT_N, seed=BOOT_SEED):
    """95% interval of mean(a) - mean(b), coins resampled within each side (random.choices: fast enough for a page build)."""
    rng = random.Random(seed)
    la, lb = len(a), len(b)
    d = sorted(sum(rng.choices(a, k=la)) / la - sum(rng.choices(b, k=lb)) / lb for _ in range(n))
    return d[int(0.025 * n)], d[int(0.975 * n) - 1]


def card(acc, base, base_zero):
    """-> dict: coins, avg, zero share, diff, interval, light. base: the passers' per-coin means."""
    m, z = _means(acc)
    out = {"n": len(m), "avg": (sum(m) / len(m)) if m else None, "zero": (z / len(m)) if m else None, "diff": None, "lo": None, "hi": None, "light": "idle"}
    if len(m) < MIN_COINS or len(base) < MIN_COINS:
        return out
    out["diff"] = out["avg"] - sum(base) / len(base)
    out["lo"], out["hi"] = boot_diff(m, base)
    out["light"] = "good" if out["hi"] < 0 else "bad" if out["lo"] > 0 else "warn"
    return out


def active_tags():
    """The why tags the active profile can give (memebot after apply_profile); None when memebot cannot be read (then every bot shows)."""
    try:
        import memebot as M
    except Exception:
        return None
    off = set()
    if M.GATE_MAX_AGE_H is None:
        off.add("old")
    if M.GATE_MIN_BUYRATIO1H is None:
        off.add("nobuyers")
    if M.GATE_MIN_VOL1SHARE is None:
        off.add("novol1h")
    if M.GATE_MAX_LIQMC is None:
        off.add("liqmc")
    return set(OWNER) - off


def report(team, active=None):
    """-> {"scans", "base": {...}, "bots": [...], "scorer": {...}}; each bot's card is (thrown out alone) against (let through). active: the
    why tags the profile gives now (active_tags()); a bot none of whose tags is active is off the team, a tag that is off loses its line."""
    base, bz = _means(team.passed)
    res = {"scans": len(team.t0s), "base": {"n": len(base), "avg": (sum(base) / len(base)) if base else None, "zero": (bz / len(base)) if base else None},
           "bots": [], "lastT0": team.last["t0"]}
    for bid, name, job, tags in TEAM:
        if active is not None:
            tags = tuple(t for t in tags if t in active)
            if not tags:
                continue
        c = card(team.alone[bid], base, bz)
        if not c["n"] and not any(team.tag.get(t) for t in tags):
            continue                           # a bot whose gates are off in this profile (or never fired alone) is not on the team
        c.update({"id": bid, "name": name, "job": job, "last": team.last["alone"].get(bid, 0),
                  "tags": [dict(card(team.tag[t], base, bz), tag=t) for t in tags if team.tag.get(t)],
                  "history": [HISTORY[t] for t in tags if t in HISTORY]})
        res["bots"].append(c)
    # the Scorer: the bot's pick (rank 1) against the other passers of the scans: does the score add anything to the gates?
    rest, _ = _means(team.rest)
    sc = card(team.top, rest, 0)
    sc["light"] = {"good": "bad", "bad": "good"}.get(sc["light"], sc["light"])     # for the Scorer, doing better than the passers is the good side
    sc.update({"id": "score", "name": "Scorer", "job": "picks one of the coins every bot let through", "last": None, "tags": [], "history": []})
    res["scorer"] = sc
    return res


# ---------------------------------------------------------------- the page
LIGHT = {"good": "earns its place", "bad": "throws away better coins", "warn": "not proven", "idle": "too few coins yet"}
SCORER_LIGHT = {"good": "its picks did better", "bad": "its picks did worse", "warn": "not proven", "idle": "too few coins yet"}
# a pixel bot (the team's one figure, 12 x 10 cells), drawn in the card's light colour
BOT = ("M2 1h8v1H2z M1 2h10v5H1z M2 7h2v2H2z M5 7h2v2H5z M8 7h2v2H8z")
EYES = "M3 3h2v2H3z M7 3h2v2H7z"

CSS = """
.ft { display:grid; gap:12px }
.ftc { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px }
@media (max-width:860px) { .ftc { grid-template-columns:repeat(2,minmax(0,1fr)) } }
@media (max-width:520px) { .ftc { grid-template-columns:minmax(0,1fr) } }
.ftb { border:1px solid var(--line); border-radius:10px; background:var(--surface); padding:10px 12px; display:grid; gap:4px; min-width:0; align-content:start }
.ftb .hd { display:flex; gap:8px; align-items:center; min-width:0 } .ftb .hd b { font-weight:600; overflow-wrap:anywhere }
.ftb svg { flex:none; width:24px; height:20px } .ftb svg .bd { fill:currentColor } .ftb svg .ey { fill:var(--surface) }
.ftb.good svg { color:var(--good-mark) } .ftb.bad svg { color:var(--bad-mark) } .ftb.warn svg { color:var(--warn-mark) } .ftb.idle svg { color:var(--muted) }
.ftb .job { color:var(--muted); font-size:var(--fs-xs) } .ftb .v { font-size:18px; font-weight:600; font-variant-numeric:tabular-nums }
.ftb .lt { font-size:var(--fs-xs); font-weight:600 } .ftb.good .lt { color:var(--good) } .ftb.bad .lt { color:var(--bad) } .ftb.warn .lt { color:var(--warn) } .ftb.idle .lt { color:var(--muted) }
.ftb .sub { font-size:var(--fs-xs); color:var(--fg2); font-variant-numeric:tabular-nums } .ftb .hist { font-size:var(--fs-xs); color:var(--fg2) }
"""


def glyph():
    return '<svg viewBox="0 0 12 10" aria-hidden="true"><path class="bd" d="%s"/><path class="ey" d="%s"/></svg>' % (BOT, EYES)


def section(D, R):
    """The filter team on the Pick tab's Details fold, in place of the old coin test. R: report.py (E, fmt_amt, section, horizon_text)."""
    T = D.get("team")
    if not isinstance(T, dict) or not T.get("scans"):
        return R.section("Filter team", "", '<div class="empty">The filter team gets its report cards after the first scan has been priced again %s later.</div>' % R.E(R.horizon_text()))
    E, amt = R.E, lambda v: R.fmt_amt(v, True)
    b = T["base"]
    pct = lambda v: "–" if v is None else "%.0f%%" % (100 * v)

    def box(c, scorer=False):
        word = (SCORER_LIGHT if scorer else LIGHT)[c["light"]]
        diff = ("%s € vs %s" % (amt(c["diff"]), "the other passers" if scorer else "let through")) if c["diff"] is not None else "–"
        rng = (" · 95%%: %s to %s" % (amt(c["lo"]), amt(c["hi"]))) if c["lo"] is not None else ""
        lines = ['<span class="sub">%d coin%s %s · %s per coin · %s to zero</span>' % (
            c["n"], "" if c["n"] == 1 else "s", "picked" if scorer else "thrown out alone", amt(c["avg"]), pct(c["zero"]))]
        for t in c.get("tags") or []:
            if len(c["tags"]) > 1 and t["n"]:
                lines.append('<span class="sub">%s: %d coins, %s</span>' % (E(R.M.fail_text(t["tag"])), t["n"], amt(t["avg"])))
        if c.get("last"):
            lines.append('<span class="sub">last scan: %d thrown out alone</span>' % c["last"])
        lines += ['<span class="hist">%s</span>' % E(h) for h in c.get("history") or []]
        return ('<div class="ftb %s" data-ft="%s"><div class="hd">%s<b>%s</b></div><span class="job">%s</span><span class="v">%s</span>'
                '<span class="lt">%s%s</span>%s</div>') % (c["light"], E(c["id"]), glyph(), E(c["name"]), E(c["job"]), E(diff), E(word), E(rng), "".join(lines))

    cards = "".join(box(c) for c in T["bots"]) + box(T["scorer"], True)
    good = sum(1 for c in T["bots"] if c["light"] == "good")
    sub = "%d of %d bots earn their place · %d scans · let through: %d coins, %s per coin, %s to zero" % (
        good, len(T["bots"]), T["scans"], b["n"], amt(b["avg"]), pct(b["zero"]))
    more = ("<p>Each bot is one job of the hard gates. Its card compares the coins that only this bot threw out of a scan with the coins every bot "
            "let through, per coin (each coin's mean over its scans), %s later and after fees, over the training's window. Green: the thrown-out coins "
            "did worse and the 95%% interval says so. Red: they did better. Amber: not proven. The Scorer compares the bot's pick with the other coins let "
            "through in the same scans. Fake money only.</p>") % E(R.horizon_text())
    body = '<style>%s</style><div class="ft"><div class="ftc">%s</div></div>' % (CSS, cards)
    return R.section("Filter team", sub, body, info=True, more=more)
