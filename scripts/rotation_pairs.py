#!/usr/bin/env python3
"""
rotation_pairs.py — fixture-multiplier EV, GW1-10 correlation matrix, rotation edge.
====================================================================================
Tiers = 2026-27 implied-points groups (named in brief). Fixture multipliers derived
from the 2025-26 tier-average ratios (normalised to T2=1). Rotation edge (Task 4) =
sum over GW1-10 of MAX(A_adjEV, B_adjEV) minus sum of the best SINGLE starter always
playing — the honest test the swing headline can't give.
"""
from __future__ import annotations
from pathlib import Path
from itertools import combinations
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
GW_MAX = 10

TIER = {}
for c in ["ARS", "MCI", "LIV", "CHE", "TOT"]: TIER[c] = "T1"
for c in ["MUN", "AVL", "NEW", "BHA", "EVE", "NFO", "CRY", "LEE", "BRE"]: TIER[c] = "T2"
for c in ["BOU", "FUL", "SUN", "IPS", "COV", "HUL"]: TIER[c] = "T3"

# multipliers by player type & opponent tier (2025-26 tier-avg ratios, T2=1)
MULT = {
 "GK":       {"T1": 0.85, "T2": 1.0, "T3": 1.08},
 "DEF":      {"T1": 0.80, "T2": 1.0, "T3": 1.19},   # CB/FB blended (swing ~1.4-1.5)
 "MID_cre":  {"T1": 0.85, "T2": 1.0, "T3": 1.13},
 "MID_def":  {"T1": 1.0,  "T2": 1.0, "T3": 1.0},    # fixture-immune, no adjustment
 "FWD":      {"T1": 0.82, "T2": 1.0, "T3": 1.07},
}


def load():
    fx = pd.read_csv(RAW / "fixtures_2026-27.csv")
    t = pd.read_csv(RAW / "teams_2026-27.csv")
    ep = pd.read_csv(RAW / "expected_points_2026-27.csv")
    m = pd.read_csv(RAW.parent / "outputs" / "master_candidates.csv")
    id2sh = dict(zip(t.id, t.short_name)); imp = dict(zip(ep.short, ep.exp_pts_2026_27))
    # per club: ordered GW1-10 opponent short + implied difficulty + tier
    clubs = sorted(id2sh.values())
    opp = {c: {} for c in clubs}
    for r in fx[fx.event <= GW_MAX].itertuples():
        h, a = id2sh[r.team_h], id2sh[r.team_a]
        opp[h][int(r.event)] = a; opp[a][int(r.event)] = h
    diff = {c: np.array([imp.get(opp[c].get(g), 45) for g in range(1, GW_MAX + 1)]) for c in clubs}
    return fx, id2sh, imp, m, clubs, opp, diff


def corr_matrix(clubs, diff):
    M = pd.DataFrame(index=clubs, columns=clubs, dtype=float)
    for a in clubs:
        for b in clubs:
            M.loc[a, b] = 1.0 if a == b else np.corrcoef(diff[a], diff[b])[0, 1]
    return M


def adj_ev(pts_start, club, ptype, opp, diff_unused):
    """weekly fixture-adjusted EV vector over GW1-10 for a player."""
    ev = []
    for g in range(1, GW_MAX + 1):
        oc = opp[club].get(g)
        tier = TIER.get(oc, "T2")
        ev.append(pts_start * MULT[ptype][tier])
    return np.array(ev)


def rotation_edge(A, B, single, opp):
    """A,B,single = (pts_start, club, ptype). Edge = Σmax(A,B) - Σ single over GW1-10."""
    a = adj_ev(*A, opp, None); b = adj_ev(*B, opp, None); s = adj_ev(*single, opp, None)
    pair = np.maximum(a, b).sum()
    return pair - s.sum(), pair, s.sum(), np.maximum(a, b), (a > b)


def main():
    fx, id2sh, imp, m, clubs, opp, diff = load()
    m = m.set_index("web_name")
    # inject van Ewijk (promoted, user-confirmed nailed attacking FB)
    ve = {"team_name": "COV", "price": 4.0, "P_start": 0.95, "pts_start": 3.6, "pos": "DEF"}

    print("=== TASK 2: GW1-10 fixture correlation — best ROTATION PAIRS (most negative) ===")
    C = corr_matrix(clubs, diff)
    pairs = [(a, b, C.loc[a, b]) for a, b in combinations(clubs, 2)]
    pairs.sort(key=lambda x: x[2])
    print("  strongest NEGATIVE (fixtures alternate -> good pairs):")
    for a, b, c in pairs[:10]:
        print(f"    {a}-{b}: {c:+.2f}")
    print("  strongest POSITIVE (fixtures move together -> avoid owning both):")
    for a, b, c in pairs[-6:]:
        print(f"    {a}-{b}: {c:+.2f}")

    def nailed(pos, lo, hi, pmin=0.85):
        d = m[(m.pos == pos) & (m.price >= lo) & (m.price <= hi) & (m.P_start >= pmin)]
        return d

    print("\n=== TASK 3-4: DEF rotation — van Ewijk (COV £4.0) + best partner ===")
    defs = nailed("DEF", 4.0, 4.5).reset_index()
    single = (m.loc["Tarkowski", "pts_start"], "EVE", "DEF")   # £6.0 premium-ish single benchmark
    print(f"  benchmark single: Tarkowski EVE £6.0 (pts/st {single[0]:.2f}, always starts)")
    print(f"  {'partner':>12} {'club':>4} {'£':>4} {'corr(COV)':>9} {'rot.edge':>8}  (edge = pair GW1-10 - single)")
    rows = []
    for r in defs.itertuples():
        cc = C.loc["COV", r.team_name]
        edge, pair, sing, _, _ = rotation_edge((ve["pts_start"], "COV", "DEF"),
                                               (r.pts_start, r.team_name, "DEF"), single, opp)
        rows.append((r.web_name, r.team_name, r.price, cc, edge))
    for nm, cl, pr, cc, e in sorted(rows, key=lambda x: -x[4])[:6]:
        print(f"  {nm:>12} {cl:>4} {pr:>4.1f} {cc:>+9.2f} {e:>+8.1f}")

    print("\n=== TASK 3-4: GK rotation — best nailed £4-4.5 pair vs Pickford (£5.5) single ===")
    gks = nailed("GK", 4.0, 4.5).reset_index()
    psingle = (m.loc["Pickford", "pts_start"], "EVE", "GK")
    best = []
    for i in range(len(gks)):
        for j in range(i + 1, len(gks)):
            A = gks.iloc[i]; B = gks.iloc[j]
            cc = C.loc[A.team_name, B.team_name]
            edge, pair, sing, _, _ = rotation_edge((A.pts_start, A.team_name, "GK"),
                                                   (B.pts_start, B.team_name, "GK"), psingle, opp)
            best.append((A.web_name, A.team_name, B.web_name, B.team_name, cc, edge, A.price + B.price))
    print(f"  benchmark single: Pickford EVE £5.5 (pts/st {psingle[0]:.2f})")
    print(f"  {'pair':>26} {'corr':>6} {'rot.edge':>8} {'pairCost':>8}")
    for a, ac, b, bc, cc, e, cost in sorted(best, key=lambda x: -x[5])[:5]:
        print(f"  {a+'('+ac+')/'+b+'('+bc+')':>26} {cc:>+6.2f} {e:>+8.1f} {cost:>7.1f}m")

    print("\n=== TASK 5: week-by-week — van Ewijk + best DEF partner (GW1-10) ===")
    best_partner = max(rows, key=lambda x: x[4])
    pnm, pcl = best_partner[0], best_partner[1]
    pps = defs.set_index("web_name").loc[pnm, "pts_start"]
    a = adj_ev(ve["pts_start"], "COV", "DEF", opp, None)
    b = adj_ev(pps, pcl, "DEF", opp, None)
    print(f"  Pair: van Ewijk (COV £4.0) vs {pnm} ({pcl} £{defs.set_index('web_name').loc[pnm,'price']})")
    print(f"  {'GW':>3} {'COV opp':>10} {'vE EV':>6} {pnm[:8]+' opp':>14} {'part EV':>7}  start")
    for g in range(GW_MAX):
        oc_v = opp["COV"].get(g + 1); oc_p = opp[pcl].get(g + 1)
        start = "van Ewijk" if a[g] >= b[g] else pnm
        print(f"  {g+1:>3} {oc_v+'('+TIER.get(oc_v,'T2')+')':>10} {a[g]:>6.2f} "
              f"{oc_p+'('+TIER.get(oc_p,'T2')+')':>14} {b[g]:>7.2f}  {start}")
    print(f"  pair GW1-10 total: {np.maximum(a,b).sum():.1f} | van Ewijk-only: {a.sum():.1f} | "
          f"{pnm}-only: {b.sum():.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
