#!/usr/bin/env python3
"""
archetypes.py — one price, two players: decompose value into P(start) x pts-when-playing.
=========================================================================================
The user's point: a £5m DEF who is a squad player at a PREMIUM club (great per game,
rotation risk) is a totally different asset from a £5m DEF who is a nailed STAR at a
MID-TABLE club (plays always, fewer clean sheets) — yet price hides it. This splits
last season's ~£5m defenders on the two axes that price conflates:
    expected season points ~= P(start) x E[points | start] x 38
P(start) = 60+ min appearances / 38 ; club defensive quality from last year's GA.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def main():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    ep = pd.read_csv(RAW / "expected_points_2026-27.csv")
    for c in ["minutes", "total_points"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    pr["pos"] = pr["element_type"].map(POS)
    pr["start_price"] = (pr["now_cost"] - pr["cost_change_start"]) / 10.0

    # club defensive tier last season (fewest goals against = strongest defence)
    lt = lt.sort_values("GA").reset_index(drop=True)
    lt["dtier"] = ["strong D"] * 6 + ["mid D"] * 8 + ["weak D"] * 6
    dtier = dict(zip(lt.team_fpl, lt.dtier))
    ga = dict(zip(lt.team_fpl, lt.GA))
    adj = dict(zip(ep.club_fpl, ep.adjustment))

    # per player: appearances, P(start), pts-per-start, total, club
    app = g[g.minutes >= 60]
    per = g.groupby("element").agg(team=("team", lambda s: s.mode().iloc[0])).reset_index()
    q = app.groupby("element").agg(apps60=("minutes", "size"),
                                   pps=("total_points", "mean")).reset_index()
    d = pr[["id", "web_name", "pos", "start_price"]].rename(columns={"id": "element"})
    d = d.merge(per, on="element").merge(q, on="element", how="left")
    d["apps60"] = d["apps60"].fillna(0)
    d["p_start"] = d["apps60"] / 38.0
    d["total"] = pd.to_numeric(pr.set_index("id").loc[d.element, "total_points"].values, errors="coerce")
    d["dtier"] = d["team"].map(dtier)
    d["club_adj_2627"] = d["team"].map(adj)

    # ---- the ~£5m defender split ----
    fivedef = d[(d.pos == "DEF") & (d.start_price.between(4.5, 5.5)) & (d.apps60 >= 10)].copy()
    print("~£5m defenders (£4.5-5.5, 10+ starts) by CLUB DEFENSIVE TIER (last season):\n")
    print(f"  {'club defence':>12} {'n':>3} {'P(start)':>8} {'pts/start':>9} {'total pts':>9}")
    for tier in ["strong D", "mid D", "weak D"]:
        s = fivedef[fivedef.dtier == tier]
        if len(s):
            print(f"  {tier:>12} {len(s):>3} {s.p_start.mean():>8.2f} {s.pps.mean():>9.2f} {s.total.mean():>9.0f}")
    print("\n  -> premium-defence clubs: higher pts/start but LOWER P(start) (rotation);")
    print("     weaker clubs: lower pts/start but their cheap DEF are more NAILED.\n")

    # ---- the two archetypes as quadrants ----
    fivedef["nailed"] = np.where(fivedef.p_start >= 0.75, "nailed (>=0.75)", "rotation (<0.75)")
    fivedef["dgood"] = np.where(fivedef.dtier == "strong D", "premium D club", "mid/weak D club")
    print("ARCHETYPE QUADRANTS (mean season total pts, n):")
    piv = fivedef.pivot_table(index="dgood", columns="nailed", values="total", aggfunc=["mean", "count"])
    print(piv.round(0).to_string())

    # ---- concrete examples of each archetype ----
    print("\nArchetype A — squad DEF at a premium-defence club (high pts/start, minutes risk):")
    A = fivedef[(fivedef.dtier == "strong D") & (fivedef.p_start < 0.75)].nlargest(4, "pps")
    for r in A.itertuples():
        print(f"   {r.web_name:<14} {r.team:<14} £{r.start_price} P(start){r.p_start:.2f} "
              f"pts/start {r.pps:.2f} total {r.total:.0f}  [2026-27 club adj {r.club_adj_2627:+.0f}]")
    print("\nArchetype B — nailed DEF at a mid/weak-defence club (low pts/start, plays always):")
    B = fivedef[(fivedef.dtier != "strong D") & (fivedef.p_start >= 0.85)].nlargest(4, "total")
    for r in B.itertuples():
        print(f"   {r.web_name:<14} {r.team:<14} £{r.start_price} P(start){r.p_start:.2f} "
              f"pts/start {r.pps:.2f} total {r.total:.0f}  [2026-27 club adj {r.club_adj_2627:+.0f}]")

    print("\nEV ~= P(start) x pts/start x 38. Same price, different route to the total —")
    print("and different management need (A: coverage/active; B: set-and-forget).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
