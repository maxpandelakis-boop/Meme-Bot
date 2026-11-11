import sys, json; sys.path.insert(0, "/home/user/Meme-Bot/research/mlexit")
import numpy as np, check_mlexit as M
Mt, E, F = M.load(sys.argv[1])
P = Mt["roles"].str.contains("P").to_numpy(); wv = Mt["w"].to_numpy()
out = {}
for w in M.WN:
    r = np.nonzero(P & (wv == w))[0]
    L0 = E["L"][r, 0]
    mult = np.where(L0 <= 0.5, np.minimum(L0, 0.5), E["C"][r, 0])
    mon = M.money_of(mult); v3 = M.money_of(Mt["V3_m"].to_numpy()[r])
    out[w] = {"n": len(r), "sell5": round(float(mon.mean()), 2), "V3": round(float(v3.mean()), 2), "vsV3": M.judge(mon - v3)}
print(json.dumps(out, indent=1))
json.dump(out, open(sys.argv[2], "w"), indent=1)
