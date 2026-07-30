#!/usr/bin/env python3
"""
build_structure_test.py — challenge the target squad structure (Q1-Q4).
Projection = 2025-26 actual total (tp_2526); Haaland fixed 239, Gabriel fixed 194.
Best available = highest 2025-26 total at that 2026-27 price (nailed: P_start>=0.6).
Captaincy premium = 30 weeks x best captain's pts/start. All comparisons equal-budget.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd
import rotation_pairs as R

M = pd.read_csv(Path(__file__).resolve().parent.parent / "data" / "outputs" / "master_candidates.csv")
M = M[(M.status == "a") | (M.web_name.isin(["Gabriel", "Haaland"]))]   # drop injured/suspended
PROJ = {"Haaland": 239.0, "Gabriel": 194.0}                            # fixed human inputs
CAP_WK = 30


def proj(row):
    return PROJ.get(row.web_name, row.tp_2526)


def best(pos, lo, hi, k=1, exclude=(), pmin=0.0):
    d = M[(M.pos == pos) & (M.price >= lo) & (M.price <= hi) & (M.P_start >= pmin)
          & (~M.web_name.isin(exclude)) & M.tp_2526.notna()].copy()
    d["projection"] = d.apply(proj, axis=1)
    return d.sort_values("projection", ascending=False).head(k)


def show(players):
    return " | ".join(f"{r.web_name}({r.team_name} £{r.price}) {r.projection:.0f}pts P{r.P_start:.2f}"
                      for r in players.itertuples())


def sumproj(*dfs):
    return sum(d.projection.sum() for d in dfs)


def cap_ppg(*dfs):
    return max((d.pts_start.max() if len(d) else 0) for d in dfs)


def main():
    print("Projection = 2025-26 total. Haaland fixed 239, Gabriel fixed 194. Captaincy = 30 x best ppg.")
    print("*** single-season projections -> confidence PRELIMINARY unless noted ***\n")

    # ---------- Q1: Haaland vs 3 premium FWD (£35m, 4 slots) ----------
    print("=== Q1: Haaland (£15.5) vs three premium FWD, £35m over 4 slots ===")
    hf2 = best("FWD", 7.0, 7.9); hf3 = best("FWD", 5.0, 5.9); hm4 = best("MID", 6.3, 6.9)
    haaland = M[M.web_name == "Haaland"].assign(projection=239.0)
    with_base = sumproj(haaland, hf2, hf3, hm4)
    with_cap = CAP_WK * 7.28
    print(f"  WITH Haaland: Haaland(239) + {show(hf2)} + {show(hf3)} + {show(hm4)}")
    print(f"    base {with_base:.0f} + captaincy(Haaland 7.28x30={with_cap:.0f}) = {with_base+with_cap:.0f}")

    wf1 = best("FWD", 9.0, 10.0); wf2 = best("FWD", 8.0, 8.9, 2, exclude=tuple(wf1.web_name))
    wm4 = best("MID", 8.0, 8.9)
    wo_base = sumproj(wf1, wf2, wm4)
    wo_ppg = cap_ppg(wf1, wf2, wm4)
    wo_cap = CAP_WK * wo_ppg
    print(f"  WITHOUT: {show(wf1)} + {show(wf2)} + {show(wm4)}")
    print(f"    base {wo_base:.0f} + captaincy(best {wo_ppg:.2f}x30={wo_cap:.0f}) = {wo_base+wo_cap:.0f}")
    d = (with_base+with_cap) - (wo_base+wo_cap)
    print(f"  --> WITH Haaland {'WINS' if d>0 else 'LOSES'} by {abs(d):.0f} pts (captaincy alone = {with_cap-wo_cap:+.0f})\n")

    # ---------- Q2: Gabriel vs cheaper DEF + MID upgrade (£13.5m, 2 slots) ----------
    print("=== Q2: Gabriel (£8.0) vs £6.5 DEF + MID upgrade, £13.5m over 2 slots ===")
    gab = M[M.web_name == "Gabriel"].assign(projection=194.0)
    gm5 = best("MID", 5.3, 5.9)
    with_g = sumproj(gab, gm5)
    d65 = best("DEF", 6.3, 6.9); m70 = best("MID", 6.8, 7.3)   # skip 6.0 dead zone
    wo_g = sumproj(d65, m70)
    print(f"  WITH Gabriel: Gabriel(194) + {show(gm5)} = {with_g:.0f}")
    print(f"  WITHOUT: {show(d65)} + {show(m70)} = {wo_g:.0f}")
    dg = with_g - wo_g
    print(f"  --> Gabriel {'WINS' if dg>0 else 'LOSES'} by {abs(dg):.0f} pts\n")

    # ---------- Q3: 3-way vs 2-way DEF rotation ----------
    print("=== Q3: three cheap DEF rotating vs two + £4.5 upgrade ===")
    fx, id2sh, imp, mm, clubs, opp, diff = R.load()
    C = R.corr_matrix(clubs, diff)
    cheap = best("DEF", 4.0, 4.5, k=12, pmin=0.85)
    cheap = pd.concat([cheap, pd.DataFrame([{"web_name":"van Ewijk","team_name":"COV","price":4.0,
            "pts_start":3.6,"P_start":0.95,"projection":100.0}])], ignore_index=True)
    print("  nailed cheap DEF pool (P>=0.85):", ", ".join(f"{r.web_name}({r.team_name})" for r in cheap.itertuples()))
    # find a trio with all-negative pairwise correlation
    clubs_pool = list(dict.fromkeys(cheap.team_name))
    best_trio = None
    from itertools import combinations
    for a, b, c in combinations(clubs_pool, 3):
        cs = [C.loc[a, b], C.loc[a, c], C.loc[b, c]]
        if max(cs) < 0:  # all three pairwise negative
            score = sum(cs)
            if best_trio is None or score < best_trio[1]:
                best_trio = ((a, b, c), score, cs)
    if best_trio:
        (a, b, c), sc, cs = best_trio
        print(f"  best all-negative trio: {a}-{b}-{c} corrs {[round(x,2) for x in cs]} "
              f"-> a genuine 3-way rotation EXISTS")
    else:
        print("  NO trio of cheap-DEF clubs is mutually negatively correlated ->")
        print("  3-way rotation collapses: the 3rd cheap DEF adds little over a crash; redeploy £4.5m.")

    # ---------- Q4: MID spread at £37m ----------
    print("\n=== Q4: MID spread at £37m (avoid £6.0 dead zone) ===")
    def midset(prices):
        used, tot, names = [], 0, []
        for p in prices:
            pick = best("MID", p-0.25, p+0.25, exclude=tuple(used))
            if len(pick):
                used.append(pick.iloc[0].web_name); tot += pick.iloc[0].projection
                names.append(f"{pick.iloc[0].web_name}£{p}")
        return tot, names
    for label, spread in [("HYPOTHESIS 9/7.5/7.5/6.5/5.5", [9.5,7.5,7.5,6.5,5.5]),
                          ("Alt A 9/8.5/7.5/6.5/5.5", [9.5,8.5,7.5,6.5,5.5]),
                          ("Alt C 9/7.5/7.5/7.5/5.5", [9.5,7.5,7.5,7.5,5.5])]:
        tot, names = midset(spread)
        print(f"  {label:<32} = {tot:.0f} pts   ({', '.join(names)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
