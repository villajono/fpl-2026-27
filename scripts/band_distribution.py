#!/usr/bin/env python3
"""
band_distribution.py — within-price-band spread = the PICK RISK the ceiling hides.
==================================================================================

"The best £4.5 defenders are as good as premiums" is true only if you pick one.
This shows the FULL distribution of last season's points for every player who
started at a given price, per position per £0.5 band: how many there were, the
spread (p25/median/p75/max), and the hit vs bust rate. Cheap = wide spread, many
busts (hard to pick); premium = high floor (safe). That dispersion is a real cost
of going cheap and must sit next to the "achievable ceiling".
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "players_raw_2025-26.csv"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GEM, BUST = 120, 40          # a "gem" season vs a "bust"


def main() -> int:
    d = pd.read_csv(RAW)
    d["pos"] = d["element_type"].map(POS)
    d["start_price"] = (d["now_cost"] - d["cost_change_start"]) / 10.0
    d["total_points"] = pd.to_numeric(d["total_points"], errors="coerce").fillna(0)
    d["starts"] = pd.to_numeric(d["starts"], errors="coerce").fillna(0)

    for p in ["GK", "DEF", "MID", "FWD"]:
        sub = d[d.pos == p]
        fl = sub["start_price"].min()
        print(f"=== {p}: outcome spread by START price band (all players at that price) ===")
        print(f"  {'band':>10} {'n':>4} {'p25':>4} {'med':>4} {'p75':>4} {'max':>4} "
              f"{'gems':>10} {'busts':>10}")
        edges = np.arange(fl, sub["start_price"].max() + 0.5, 0.5)
        for lo in edges:
            band = sub[(sub.start_price >= lo) & (sub.start_price < lo + 0.5)]
            if len(band) == 0:
                continue
            tp = band["total_points"]
            gems = (tp >= GEM).sum()
            busts = (tp < BUST).sum()
            print(f"  {lo:>4.1f}-{lo+0.5:<4.1f} {len(band):>4} "
                  f"{tp.quantile(.25):>4.0f} {tp.median():>4.0f} {tp.quantile(.75):>4.0f} "
                  f"{tp.max():>4.0f} {gems:>3} ({100*gems/len(band):>3.0f}%) "
                  f"{busts:>3} ({100*busts/len(band):>3.0f}%)")
        print()

    # headline: the £4.5 DEF lottery vs a £6.0 DEF, spelled out
    print("=== the cheap-defender lottery, spelled out ===")
    for price in [4.5, 5.0, 6.0]:
        b = d[(d.pos == "DEF") & (d.start_price >= price - 0.25) & (d.start_price < price + 0.25)]
        played = b[b.starts >= 10]
        print(f"  £{price:.1f}m DEF: {len(b)} existed, {len(played)} were regular starters; "
              f"of ALL {len(b)}: {(b.total_points>=GEM).sum()} gems ({100*(b.total_points>=GEM).mean():.0f}%), "
              f"{(b.total_points<BUST).sum()} busts ({100*(b.total_points<BUST).mean():.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
