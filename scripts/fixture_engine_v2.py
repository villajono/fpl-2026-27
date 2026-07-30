#!/usr/bin/env python3
"""
fixture_engine_v2.py — separate attack/defence xG fixture engine (Steps 1-6).
Team xG derived from the 2025-26 FPL Opta feed (per-player expected_goals summed to
match level). Attack = xG scored/game; Defence = xG conceded/game (higher = worse).
Uses xG ONLY (not actual goals) so the implied-points step doesn't double-count
finishing variance. Promoted clubs anchored to implied points (HIGH UNCERTAINTY).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
IMPLIED = {  # 2026-27 implied pts, adjustment
 "Arsenal":(78.5,-6.5),"Man City":(75.5,-2.5),"Man Utd":(69.5,-1.5),"Aston Villa":(58.0,-7.0),
 "Liverpool":(71.0,11.0),"Bournemouth":(49.0,-8.0),"Sunderland":(42.5,-11.5),"Brighton":(53.0,0.0),
 "Brentford":(49.0,-4.0),"Chelsea":(68.0,16.0),"Fulham":(44.5,-7.5),"Newcastle":(52.5,3.5),
 "Everton":(49.5,0.5),"Leeds":(46.0,-1.0),"Crystal Palace":(46.0,1.0),"Nott'm Forest":(48.0,4.0),
 "Spurs":(61.0,20.0),"Ipswich":(33.0,None),"Coventry":(33.0,None),"Hull":(24.0,None)}
PROMOTED = {"Ipswich","Coventry","Hull"}


def team_xg():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    t = pd.read_csv(RAW / "teams_2026-27.csv")  # id->name map is stable across the two seasons' shared clubs
    # merged_gw uses full names in 'team'; opponent_team is an id -> map to the SAME name space
    g["xg"] = pd.to_numeric(g["expected_goals"], errors="coerce").fillna(0)
    # build id->name from the 2025-26 fixtures/teams: derive from merged_gw itself
    # (opponent_team id -> the 'team' name that appears with that id as their own team)
    # simplest: map via teams file short, then short->name below
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    sh2name = dict(zip(lt.short, lt.team_fpl))
    id2sh = dict(zip(pd.read_csv(RAW/'teams_2025-26.csv').id, pd.read_csv(RAW/'teams_2025-26.csv').short_name))
    g["opp_name"] = g["opponent_team"].map(lambda i: sh2name.get(id2sh.get(i)))
    m = g.groupby(["GW", "team", "opp_name", "was_home"], as_index=False)["xg"].sum()
    # xGA = opponent's xGF in the same match
    rev = m.rename(columns={"team": "opp_name", "opp_name": "team", "xg": "xga"})[["GW", "team", "opp_name", "xga"]]
    m = m.merge(rev, on=["GW", "team", "opp_name"], how="left")
    agg = m.groupby("team").agg(games=("GW", "size"), xgf=("xg", "sum"), xga=("xga", "sum"))
    agg["xgf_pg"] = agg.xgf / agg.games; agg["xga_pg"] = agg.xga / agg.games
    ha = m.groupby(["team", "was_home"]).agg(xgf=("xg", "mean"), xga=("xga", "mean")).unstack()
    return agg, ha, m


def main():
    agg, ha, matches = team_xg()
    lt = pd.read_csv(RAW / "league_table_2025-26.csv").set_index("team_fpl")
    lg_att = agg.xgf_pg.mean(); lg_def = agg.xga_pg.mean()
    agg["ATT"] = (agg.xgf_pg / lg_att).round(2)          # >1 = better attack
    agg["DEF_weak"] = (agg.xga_pg / lg_def).round(2)     # >1 = weaker defence (concede more xG)

    print(f"=== STEP 1: 2025-26 xG baseline (league avg xGF/game={lg_att:.2f}, xGA/game={lg_def:.2f}) ===")
    print(f"{'club':>14} {'xGF/g':>6} {'xGA/g':>6} {'ATT':>5} {'DEFweak':>7}  {'actGF/g':>7} {'actGA/g':>7}  finishing-gap")
    for c in agg.sort_values("ATT", ascending=False).index:
        if c not in lt.index: continue
        agf = lt.loc[c, "GF"] / 38; aga = lt.loc[c, "GA"] / 38
        gap_att = agg.loc[c, "xgf_pg"] - agf   # neg = overperformed shooting
        gap_def = aga - agg.loc[c, "xga_pg"]   # neg = overperformed defensively (conceded fewer than xGA)
        flag = ""
        if abs(gap_def) > 0.25 or abs(gap_att) > 0.25: flag = "<-- LARGE FINISHING GAP (double-count risk)"
        print(f"{c[:14]:>14} {agg.loc[c,'xgf_pg']:>6.2f} {agg.loc[c,'xga_pg']:>6.2f} {agg.loc[c,'ATT']:>5.2f} "
              f"{agg.loc[c,'DEF_weak']:>7.2f}  {agf:>7.2f} {aga:>7.2f}  att{gap_att:+.2f} def{gap_def:+.2f} {flag}")

    print("\n=== SUNDERLAND SENSE-CHECK ===")
    s = agg.loc["Sunderland"]
    print(f"  Sunderland: ATT {s.ATT} (expect BELOW 1.0), DEFweak {s.DEF_weak} (expect NEAR/ABOVE 1.0 = mediocre)")
    print(f"  actual GA/game {lt.loc['Sunderland','GA']/38:.2f} vs xGA/game {s.xga_pg:.2f} "
          f"-> {'OVERPERFORMED (lucky/keeper) — xGA worse than actual, as hypothesised' if lt.loc['Sunderland','GA']/38 < s.xga_pg else 'CONTRADICTS — flag'}")

    # ---- STEP 2: implied-points adjustment (proportional to att & def) ----
    print("\n=== STEP 2: 2026-27 projected ratings (xG scaled by implied-points) ===")
    # map adjustment (pts) -> multiplicative strength scaler; +11 pts ~ +~14% strength
    proj = {}
    for c in agg.index:
        if c not in IMPLIED: continue
        _, adj = IMPLIED[c]
        if adj is None: continue
        scale = 1 + adj / 80.0                     # ~±0.14 per ±11 pts
        att = agg.loc[c, "ATT"] * scale
        defw = agg.loc[c, "DEF_weak"] / scale      # improving -> concede fewer xG
        proj[c] = (round(att, 2), round(defw, 2), adj)
    print(f"  {'club':>14} {'ATT26':>6} {'DEFweak26':>9} {'adj':>5}  flag")
    for c in sorted(proj, key=lambda k: -proj[k][0]):
        att, defw, adj = proj[c]
        fl = "<-- LARGE ADJ: att/def split may be wrong, HUMAN OVERRIDE" if abs(adj) >= 8 else ""
        print(f"  {c[:14]:>14} {att:>6.2f} {defw:>9.2f} {adj:>+5.0f}  {fl}")

    # ---- STEP 3: promoted ----
    print("\n=== STEP 3: promoted clubs (anchored to implied pts — HIGH UNCERTAINTY) ===")
    # anchor: map implied pts to att/def vs a mid-table reference (~46 pts -> ~1.0)
    for c in ["Ipswich", "Coventry", "Hull"]:
        pts = IMPLIED[c][0]
        att = round(0.55 + (pts - 24) / (78 - 24) * 0.9, 2)   # 24pts->0.55, ~78->1.45
        defw = round(1.55 - (pts - 24) / (78 - 24) * 0.9, 2)  # weak team concedes more xG
        tag = " <-- MUST-TARGET fixture for attackers (weakest)" if c == "Hull" else ""
        print(f"  {c}: implied {pts} -> ATT {att}, DEFweak {defw}  [HIGH UNCERTAINTY, no PL xG]{tag}")
        proj[c] = (att, defw, None)

    # ---- STEP 4: calibrate continuous multiplier curves (2025-26 pts vs opponent xG) ----
    print("\n=== STEP 4: calibrated multiplier curves (pts-per-app vs opponent xG) ===")
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    POS = {1:"GK",2:"DEF",3:"MID",4:"FWD"}; g["pos"] = g["element"].map(dict(zip(pr.id, pr.element_type.map(POS))))
    for c in ["minutes","total_points"]: g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    lt2 = pd.read_csv(RAW / "league_table_2025-26.csv"); id2sh = dict(zip(pd.read_csv(RAW/'teams_2025-26.csv').id, pd.read_csv(RAW/'teams_2025-26.csv').short_name))
    sh2name = dict(zip(lt2.short, lt2.team_fpl))
    g["opp_name"] = g["opponent_team"].map(lambda i: sh2name.get(id2sh.get(i)))
    g["opp_def"] = g["opp_name"].map(agg.DEF_weak.to_dict())   # opponent defensive weakness
    g["opp_att"] = g["opp_name"].map(agg.ATT.to_dict())        # opponent attack strength
    app = g[g.minutes >= 60]
    def fit(sub, xcol):
        x = sub[xcol].values; y = sub["total_points"].values
        b, a = np.polyfit(x, y, 1)                       # y = a + b*x
        base = a + b * 1.0                               # league-avg opponent
        mult = lambda xv: (a + b * xv) / base
        return b, mult
    for label, mask, xcol in [
        ("attackers (FWD)", app.pos == "FWD", "opp_def"),
        ("attackers (creative MID, >=0.15 GA/st)", app.pos == "MID", "opp_def"),
        ("attacking DEF", app.pos == "DEF", "opp_def"),
        ("defenders/GK (DEF+GK)", app.pos.isin(["DEF","GK"]), "opp_att")]:
        sub = app[mask].dropna(subset=[xcol])
        b, mult = fit(sub, xcol)
        # endpoints: Hull-weak-def (proj DEFweak ~1.5) vs Arsenal-strong-def (~0.7) for attackers;
        hull_x = proj["Hull"][1] if xcol == "opp_def" else 0.55
        ars_x = 0.70 if xcol == "opp_def" else agg.loc["Man City","ATT"]
        print(f"  {label:<38} slope {b:+.2f}  mult(easy {hull_x:.2f})={mult(hull_x):.2f}  mult(hard {ars_x:.2f})={mult(ars_x):.2f}")

    # ---- STEP 6: Sunderland multiplier test + old-vs-new ----
    print("\n=== STEP 6: Sunderland multiplier test (attackers vs defenders) ===")
    sub_att = app[app.pos == "FWD"].dropna(subset=["opp_def"]); b_a, mult_a = fit(sub_att, "opp_def")
    sub_def = app[app.pos.isin(["DEF","GK"])].dropna(subset=["opp_att"]); b_d, mult_d = fit(sub_def, "opp_att")
    s_def, s_att = agg.loc["Sunderland","DEF_weak"], agg.loc["Sunderland","ATT"]
    print(f"  creative/FWD vs Sunderland (their DEFweak {s_def}): multiplier {mult_a(s_def):.2f} (expect <1.0 = harder)")
    print(f"  defender/GK vs Sunderland (their ATT {s_att}):     multiplier {mult_d(s_att):.2f} (expect >1.0 = easier)")
    ok = mult_a(s_def) < 1.0 and mult_d(s_att) > 1.0
    print(f"  -> {'PASS — point opposite ways, as required' if ok else 'FAIL — same direction, something wrong'}")
    print("\n  OLD vs NEW multiplier (attackers), sample fixtures:")
    old = {"T1":0.89,"T2":1.0,"T3":1.11}
    for club, tier in [("Hull","T3"),("Sunderland","T3"),("Leeds","T3"),("Everton","T2"),("Arsenal","T1")]:
        dw = proj.get(club,(None,agg.DEF_weak.get(club),None))[1]
        print(f"    attacker vs {club:<12} old({tier})={old[tier]:.2f}  new={mult_a(dw):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
