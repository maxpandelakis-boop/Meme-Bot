"""Rocket study: the tables of research/rockets/ROCKETS-2026-10-24.md from check_rockets.py's result JSON.

  python3 research/rockets/report.py <result.json> > tables.md"""
import json, sys

r = json.load(open(sys.argv[1]))
P = print


def pct(x):
    return "-" if x is None else "%.2f %%" % x


P("### Base: every entry, no filter")
P()
P("| entry | window | entries | rockets | rocket rate | to zero | S1 | S2 | S3 |")
P("|---|---|---|---|---|---|---|---|---|")
for E, ws in r["base"].items():
    for w, b in ws.items():
        P("| %s min | %s | %d | %d | %.2f %% | %.1f %% | %+.2f | %+.2f | %+.2f |" % (E, w, b["entries"], b["rockets"], b["rocketPct"],
                                                                              b["zeroPct"], b["S1"], b["S2"], b["S3"]))
P()
P("### Which facts exist where (share of the 5-minute entries)")
P()
P("| fact | w1 | w2 | w3 | w4 | w5 |")
P("|---|---|---|---|---|---|")
for f, av in r["facts_available"].items():
    P("| %s | %s |" % (f[2:], " | ".join("%.0f %%" % (100 * av.get(w, 0)) for w in ("w1", "w2", "w3", "w4", "w5"))))
P()
P("### Part A: does the fact move the odds? (favoured bucket chosen on the fit windows, judged on the unseen ones)")
P()
P("| fact | entry | fit -> unseen | favoured for rockets | fit: in / rest | unseen: in (n) / rest | ratio 95 % | p | Holm | favoured against zero | unseen zero: in / rest | p | Holm |")
P("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for a in r["partA"]:
    x, z = a["rocket"], a["zero"]
    P("| %s | %d min | %s -> %s | %s | %s / %s | %s (%d) / %s | %s | %.3g | %s | %s | %s / %s | %.3g | %s |" % (
        a["fact"], a["E"], "+".join(a["fit"]), "+".join(a["unseen"]), x["favoured"], pct(x["fit_in"]), pct(x["fit_rest"]),
        pct(x["unseen_in"]), x["unseen_n"], pct(x["unseen_rest"]), x["ratio_ci"], x["p"], "yes" if x["holm"] else "no",
        z["favoured"], pct(z["unseen_in"]), pct(z["unseen_rest"]), z["p"], "yes" if z["holm"] else "no"))
P()
P("### Part B: the best bucket x sell rule of the fit windows, on the unseen windows (20 EUR, Bonferroni over %d)" % r["partB_candidates"])
P()
P("| fact | entry | bucket | sell rule | fit (n) | unseen n | unseen mean | after allowance | 1 %%/%d lower bound | without best | in profit | holds |" % r["partB_candidates"])
P("|---|---|---|---|---|---|---|---|---|---|---|---|")
for b in r["partB"]:
    P("| %s | %d min | %s | %s | %+.2f (%d) | %d | %s | %s | %s | %s | %s | %s |" % (
        b["fact"], b["E"], b["bucket"], b["rule"], b["fit_mean"], b["fit_n"], b["unseen_n"], b["unseen_mean"], b["after_allowance"],
        b["lower_bound"], b["without_best"], b["inProfit"], "yes" if b["holds"] else "no"))
P()
c = r["partC"]
P("### Part C: all facts together (LightGBM, fit %s, unseen %s, %d candidates)" % ("+".join(c["fit"]), "+".join(c["unseen"]), c["candidates"]))
P()
for m in c["models"]:
    P("Entry %d min: AUC on the unseen windows %s (0.5 = no information). Most used facts: %s." % (
        m["E"], m["unseen_auc"], ", ".join("%s" % k[2:] for k in list(m["gain"])[:4])))
    P()
    P("| top | unseen coins | rocket rate (all: %s) | S1 mean / after allowance / bound | S2 | S3 | holds |" % pct(m["cuts"][0]["base_rocketPct"]))
    P("|---|---|---|---|---|---|---|")
    for cut in m["cuts"]:
        cells = []
        for nm in ("S1", "S2", "S3"):
            v = cut[nm]
            cells.append("%s / %s / %s" % (v["mean"], v["after_allowance"], v["lower_bound"]))
        P("| %s | %d | %s | %s | %s |" % (cut["top"], cut["unseen_n"], pct(cut["rocketPct"]), " | ".join(cells),
                                         "yes" if any(cut[nm]["holds"] for nm in ("S1", "S2", "S3")) else "no"))
    P()
P("### What the rockets look like (description, no test)")
P()
for E, d in r["describe"].items():
    P("Entry %s min: %d rockets of %d entries. Market cap at the entry, median: rockets $%s, others $%s. Median minutes to 10x %s; "
      "%s %% fell to half the entry first; %s %% closed below the entry 24 h later." % (
          E, d["rockets"], d["of"], format(d["mcap_at_entry_median"]["rockets"], ","), format(d["mcap_at_entry_median"]["others"], ","),
          d["minutes_to_10x_median"], d["rockets_that_fell_half_first_pct"], d["rockets_close_24h_below_entry_pct"]))
    P()
    P("| fact | rockets median | others median | rockets mean | others mean |")
    P("|---|---|---|---|---|")
    for f, v in d["facts"].items():
        P("| %s | %s | %s | %s | %s |" % (f[2:], v["rockets_median"], v["others_median"], v["rockets_mean"], v["others_mean"]))
    P()
