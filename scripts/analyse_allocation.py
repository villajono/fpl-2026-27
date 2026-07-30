#!/usr/bin/env python3
"""
analyse_allocation.py — position value curves for the budget-allocation decision.
=================================================================================

NOT player picking. This measures, from 2025-26, how efficiently each position
converts DISCRETIONARY £ (spend above the forced floor) into points, so we can
decide how to split the ~£34m of discretionary budget across positions/slots.

Key ideas:
  * start price (not end price) = what you'd actually have paid.
  * "achievable" points at a price = mean of the TOP FEW players in that price
    band (if you pick well), not the average — you don't buy the duds.
  * discretionary £ = price - position floor; points-per-discretionary-£ is the
    real efficiency, and it DIMINISHES as you climb each position's price range.
  * defensive_contribution share flags CB/def-mid exposure to the BPS tweak.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "players_raw_2025-26.csv"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
TOPN = 8            # "if you pick well" = mean of best N in a price band


def load() -> pd.DataFrame:
    d = pd.read_csv(RAW)
    d["pos"] = d["element_type"].map(POS)
    d["start_price"] = (d["now_cost"] - d["cost_change_start"]) / 10.0
    d["price"] = d["now_cost"] / 10.0
    for c in ["total_points", "minutes", "starts", "defensive_contribution", "bonus", "bps"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    return d


def main() -> int:
    d = load()
    print(f"{len(d)} players | season 2025-26 (start prices reconstructed)\n")

    # ---- diagnostic: is defensive_contribution points or a raw count? ----
    dc = d[d.defensive_contribution > 0].nlargest(3, "defensive_contribution")
    print("defensive_contribution sample (top 3):")
    print(dc[["web_name", "pos", "total_points", "defensive_contribution"]].to_string(index=False))
    print()

    # ---- floors: cheapest START price per position ----
    print("=== position floors (cheapest start price) & squad slots ===")
    floors = {}
    for p in ["GK", "DEF", "MID", "FWD"]:
        fp = d[d.pos == p]["start_price"].min()
        floors[p] = round(fp, 1)
        print(f"  {p}: floor £{fp:.1f}m  x{SQUAD[p]} slots  = £{fp*SQUAD[p]:.1f}m forced")
    forced = sum(floors[p] * SQUAD[p] for p in floors)
    print(f"  --> forced floor total £{forced:.1f}m ; discretionary budget £{100-forced:.1f}m\n")

    # ---- per-position value curve (achievable = top-N mean per £0.5 band) ----
    for p in ["GK", "DEF", "MID", "FWD"]:
        sub = d[d.pos == p].copy()
        fl = floors[p]
        edges = np.arange(fl, sub["start_price"].max() + 0.5, 0.5)
        print(f"=== {p}: value curve (start price band -> best {TOPN} avg points) ===")
        print(f"  {'band':>10} {'n':>4} {'best'+str(TOPN)+'avg':>9} {'median':>7} "
              f"{'pts/totalÂ£':>10} {'pts/discrÂ£':>11}")
        base = None
        for lo in edges:
            hi = lo + 0.5
            band = sub[(sub.start_price >= lo) & (sub.start_price < hi)]
            if len(band) == 0:
                continue
            topn = band.nlargest(min(TOPN, len(band)), "total_points")["total_points"].mean()
            med = band["total_points"].median()
            mid = lo + 0.25
            if base is None:
                base = topn
            discr = mid - fl
            pptot = topn / mid
            ppd = (topn - base) / discr if discr > 0.01 else float("nan")
            ppd_s = f"{ppd:>11.0f}" if discr > 0.01 else f"{'(floor)':>11}"
            print(f"  {lo:>4.1f}-{hi:<4.1f} {len(band):>4} {topn:>9.0f} {med:>7.0f} "
                  f"{pptot:>10.1f} {ppd_s}")
        print()

    # ---- discretionary efficiency at matched spend tiers, cross-position ----
    print("=== cross-position: extra points per +£1m of discretionary spend ===")
    print("    (achievable at price P minus achievable at floor, per £ above floor)\n")
    tiers = [1.0, 2.0, 3.0]     # £m of discretionary spend
    print(f"  {'pos':>4} " + " ".join(f"+£{t:.0f}m/floor->pts/Â£" for t in tiers))
    curve = {}
    for p in ["GK", "DEF", "MID", "FWD"]:
        sub = d[d.pos == p]; fl = floors[p]
        def ach(price):
            band = sub[(sub.start_price >= price - 0.25) & (sub.start_price < price + 0.25)]
            if len(band) == 0:
                band = sub[(sub.start_price >= price - 0.5) & (sub.start_price < price + 0.5)]
            return band.nlargest(min(TOPN, len(band)), "total_points")["total_points"].mean() if len(band) else np.nan
        base = ach(fl)
        row = []
        for t in tiers:
            a = ach(fl + t)
            row.append((a - base) / t if a == a else np.nan)
        curve[p] = (base, row)
        print(f"  {p:>4} floor≈{base:>4.0f}pts | " +
              " ".join(f"{v:>6.0f}" if v == v else f"{'--':>6}" for v in row))
    print()

    # ---- defensive-contribution exposure (BPS-tweak haircut guide) ----
    print("=== defensive_contribution exposure (players who started >=15) ===")
    reg = d[d.starts >= 15]
    for p in ["GK", "DEF", "MID", "FWD"]:
        s = reg[reg.pos == p]
        if len(s) == 0:
            continue
        share = 100 * s["defensive_contribution"].sum() / s["total_points"].sum()
        print(f"  {p}: mean DC {s['defensive_contribution'].mean():.0f} pts/player | "
              f"{share:.0f}% of {p} points came from defensive contribution")
    print("\n(the BPS tweak trims exactly these DC points from CBs/def-mids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
