"""Part 3b: PR #53's council with the new views (fake money only; research/rocketsep/PREREG-ROCKETSEP-2026-10-26.md).

  python3 research/rocketsep/rs_council.py <out dir> A|B

Family A: PR #53's ten views x ten plans with the rocket-study facts added to V6, V7 and V8 (100 checkers), fit w1+w2 / choose on w3,
refit w1-w3 / test on w4 and w5. Family B: the same plus V11 Halter-Leser, V12 Wallet-Leser, V13 Raketen-Fakten (130 checkers), fit on
w3 before 30 Aug / choose on w3 from 30 Aug, refit on w3 / test on w4. check_council's functions are used as they are; only its
feature list, views and the worker task (which must read the columns from the shared arrays, since a spawned worker imports the
module fresh) are replaced here."""
import glob, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "council"))
import check_council as CC                                    # noqa: E402
import rs_facts as RF                                         # noqa: E402

BASE_FEATS = list(CC.FEATS)
BASE_VIEWS = [list(v) for v in CC.VIEWS]


def set_views(fam):
    feats = BASE_FEATS + RF.G_F + (RF.L_F + RF.H_F + RF.W_F if fam == "B" else [])
    views = [list(v) for v in BASE_VIEWS]
    for v in views:
        if v[0] in ("V6", "V7", "V8"):
            v[3] = list(v[3]) + RF.G_F
    if fam == "B":
        views += [["V11", "Halter-Leser", "lgb", list(RF.H_F) + ["lmc", "age"]],
                  ["V12", "Wallet-Leser", "lgb", list(RF.W_F) + ["lmc", "age"]],
                  ["V13", "Raketen-Fakten", "lgb", list(RF.G_F) + list(RF.L_F) + ["lmc", "age"]]]
    CC.FEATS = feats
    CC.FI = {f: i for i, f in enumerate(feats)}
    CC.VIEWS = [tuple(v) for v in views]
    CC.NV = len(views)
    width = max(len(CC.vcols(v)) for v in range(CC.NV))
    vc = np.full((CC.NV, width), -1, np.int64)
    for v in range(CC.NV):
        c = CC.vcols(v)
        vc[v, :len(c)] = c
    return vc


VCOLS = None


def lgb_task(t):
    """check_council._lgb_task with the view's columns from the shared array VCOLS"""
    v, j, tr_key, te_key, extra = t
    G = CC.G
    Xf, Y, GT = G["F"], G["Y"], G["gm"]
    tr, te = np.asarray(G[tr_key]), np.asarray(G[te_key])
    vc = np.asarray(G["VCOLS"])[v]
    cols = list(vc[vc >= 0])
    Xtr, Xte = Xf[tr][:, cols], Xf[te][:, cols]
    if extra is not None:
        etr, ete = G[extra + "_tr"][:, j], G[extra + "_te"][:, j]
        str_, ste = G[extra + "_s_tr"], G[extra + "_s_te"]
        Xtr = np.c_[Xtr, etr, str_]
        Xte = np.c_[Xte, ete, ste]
    y = np.clip(Y[tr, j], *CC.CLIP)
    p, it = CC.lgb_fit_pred(Xtr, y, GT[tr], Xte)
    return (v, j, tr_key, te_key, extra), p, it


def run_lgb_tasks(tasks):
    import multiprocessing as mp, tempfile, shutil
    G = CC.G
    G["VCOLS"] = VCOLS
    d = tempfile.mkdtemp(prefix="council_", dir=G.get("_tmp"))
    for k, v in G.items():
        if not k.startswith("_"):
            np.save(os.path.join(d, k + ".npy"), np.asarray(v))
    res = {}
    try:
        with mp.get_context("spawn").Pool(3, initializer=CC._init_worker, initargs=(d,)) as pool:
            for key, p, it in pool.imap_unordered(lgb_task, tasks, chunksize=1):
                res[key] = (p, it)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def main(out, fam):
    global VCOLS
    import check_rs as RS
    VCOLS = set_views(fam)
    CC.run_lgb_tasks = run_lgb_tasks
    Mt, P, D, F, FE, Fx = RS.load(out)
    CC.G["_tmp"] = out
    W = Mt["w"].to_numpy()
    gmv = Mt["gm"].to_numpy()
    res = {"family": fam, "checkers": CC.NV * CC.NPL, "views": [v[:2] for v in CC.VIEWS], "frames": {}}
    for fr in ("A", "B"):
        Fm = CC.Frame(Mt, P, D, F, fr)
        extra = [Fx["G"]] + ([Fx["L"], Fx["H" + fr], Fx["W" + fr]] if fam == "B" else [])
        Fm.F = np.c_[Fm.F, np.concatenate(extra, 1)].astype(np.float32)
        assert Fm.F.shape[1] == len(CC.FEATS)
        roles = ("P", "W1") if fr == "A" else ("L",)
        test_role = ("P",) if fr == "A" else ("L",)
        if fam == "A":
            steps = {"choose": (np.isin(W, ["w1", "w2"]), np.isin(W, ["w3"]), [["w3"]]),
                     "test": (np.isin(W, ["w1", "w2", "w3"]), np.isin(W, ["w4", "w5"]), [["w4"], ["w5"]])}
        else:
            early = (W == "w3") & (gmv < RS.B_SPLIT)
            steps = {"choose": (early, (W == "w3") & ~early, [["w3"]]), "test": (W == "w3", W == "w4", [["w4"]])}
        fres = {}
        tr, te, tws = steps["choose"]
        RS.log("council", fam, fr, "choose", int(tr.sum()), int(te.sum()))
        R = CC.run_step(Fm, tr, te, RS.log)
        rows = CC.step_rows(Fm, te, tws[0], roles)
        table = []
        for cand in CC.CANDS:
            hold, plan = CC.decisions(cand, R)
            j, _, d = CC.judge_rows(Fm, rows, hold, plan, te)
            table.append({"cand": list(cand), "diff": j["vsRule"]["diff"], "held": j["held"], "buys": j["buys"]})
        best = sorted(table, key=lambda r: (-r["diff"], r["held"]))[0]
        ch = (best["cand"][0], float(best["cand"][1]))
        fres["choose"] = {"table": table, "chosen": list(ch)}
        RS.log("council", fam, fr, "chosen", best)
        tr, te, tws = steps["test"]
        R = CC.run_step(Fm, tr, te, RS.log)
        fres["test"] = {}
        for nm, cand in (("chosen", ch), ("majority2", ("R2", 0.50)), ("chair0", ("CH", 0.0))):
            hold, plan = CC.decisions(cand, R)
            for ws in tws:
                rows = CC.step_rows(Fm, te, ws, test_role)
                j, mC, d = CC.judge_rows(Fm, rows, hold, plan, te)
                idx = np.nonzero(te)[0][rows]
                h = hold[rows]
                j["bar"] = RS.paired(d, int(h.sum()))
                j["profit"] = RS.profit(mC)
                fres["test"].setdefault(nm, {})[ws[0]] = j
            RS.log("council", fam, fr, nm, cand, {k: (v["held"], v["bar"]["diff"], v["bar"]["lo1"], v["bar"]["passes"])
                                                 for k, v in fres["test"][nm].items()})
        t = fres["test"]["chosen"]
        t4, t5 = t.get("w4"), t.get("w5")
        w5ok = True if fam == "B" else (t5 is not None and t5["vsRule"]["diff"] >= 0)
        fres["holds"] = bool(t4["bar"]["passes"] and t4["vsRule_level"] >= 0 and w5ok)
        fres["single"] = {}
        for ws in tws:
            rows = CC.step_rows(Fm, te, ws, test_role)
            idx = np.nonzero(te)[0][rows]
            G1 = Fm.gain[idx]
            for v in range(CC.NV):
                for jj in range(CC.NPL):
                    hv = R["P1"][rows, v, jj] > 0
                    fres["single"].setdefault("%s-%s" % (CC.VIEWS[v][0], CC.PN[jj]), {})[ws[0]] = [int(hv.sum()), round(float((G1[:, jj] * hv).mean()), 3)]
        res["frames"][fr] = fres
        json.dump(res, open(os.path.join(out, "council_%s.json" % fam), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
