"""Adds the live-gettable wallet numbers (features.wallet_recent) to grid.pkl -> grid_live.pkl (fake money only).
usage: python3 research/winlose/grid_recent.py <scratch>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as FE
import pandas as pd
G = pd.read_pickle(os.path.join(FE.S, "grid.pkl"))
R = FE.wallet_recent(G)
G = pd.concat([G, R], axis=1)
G.to_pickle(os.path.join(FE.S, "grid_live.pkl"))
print(G.shape, R.notna().mean().round(2).to_dict())
