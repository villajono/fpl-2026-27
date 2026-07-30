#!/usr/bin/env python3
"""
optimal_formations.py — Q1/Q2: what did the best XI actually look like, week to week?
=====================================================================================
Assumption-free. For each 2025-26 gameweek, take EVERY player's actual points and
find the highest-scoring legal XI (1 GK + DEF 3-5, MID 2-5, FWD 1-3). This is the
ex-post optimal formation that week — it tells us how often defence-heavy vs
attack-heavy was the right shape, how volatile formation is, and therefore how many
DEF slots the points actually rewarded. (Hindsight ceiling; the sim does the
realistic, owned-squad version.)
"""
from __future__ import annotations
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def best_xi(gw_pts_by_pos):
    """Return (formation tuple D-M-F, total pts) maximising a legal XI."""
    D = sorted(gw_pts_by_pos["DEF"], reverse=True)
    M = sorted(gw_pts_by_pos["MID"], reverse=True)
    F = sorted(gw_pts_by_pos["FWD"], reverse=True)
    gk = max(gw_pts_by_pos["GK"]) if gw_pts_by_pos["GK"] else 0
    best, bf = -1, None
    for d, f in product(range(3, 6), range(1, 4)):
        m = 10 - d - f
        if not (2 <= m <= 5) or d > len(D) or m > len(M) or f > len(F):
            continue
        tot = sum(D[:d]) + sum(M[:m]) + sum(F[:f])
        if tot > best:
            best, bf = tot, (d, m, f)
    return bf, gk + best


def main():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    pos = dict(zip(pr.id, pr.element_type.map(POS)))
    g["pos"] = g["element"].map(pos)
    g["total_points"] = pd.to_numeric(g["total_points"], errors="coerce").fillna(0)
    # collapse DGW to one points figure per player-GW
    pg = g.groupby(["GW", "element", "pos"])["total_points"].sum().reset_index()

    forms, defcounts, scores, prev = [], [], [], None
    changes = 0
    for gwk, sub in pg.groupby("GW"):
        by = {p: sub.loc[sub.pos == p, "total_points"].tolist() for p in ["GK", "DEF", "MID", "FWD"]}
        f, sc = best_xi(by)
        forms.append(f); defcounts.append(f[0]); scores.append(sc)
        if prev is not None and f != prev:
            changes += 1
        prev = f

    fs = pd.Series([f"{d}-{m}-{f}" for d, m, f in forms])
    print("=== Q1: ex-post OPTIMAL formation each week (2025-26, 38 GWs) ===\n")
    print("formation frequency (how often each was the best shape):")
    vc = fs.value_counts()
    for k, v in vc.items():
        print(f"   {k:>7}: {v:>2} weeks ({100*v/38:>3.0f}%)")
    print(f"\nDEF count in the optimal XI:")
    dc = pd.Series(defcounts).value_counts().sort_index()
    for k, v in dc.items():
        print(f"   {k} DEF: {v:>2} weeks ({100*v/38:>3.0f}%)")
    print(f"\nweek-to-week formation CHANGED: {changes}/37 transitions ({100*changes/37:.0f}%)")
    print(f"mean optimal-XI score: {np.mean(scores):.1f} pts")

    # mean score by DEF count (was defence-heavy actually higher-scoring when optimal?)
    df = pd.DataFrame({"def": defcounts, "score": scores})
    print("\nmean optimal-XI score by DEF count (when that was the best shape):")
    for k, gg in df.groupby("def"):
        print(f"   {k} DEF: {gg.score.mean():.1f} pts  (n={len(gg)})")

    # how many DEF appear in optimal XI on average -> Q2 signal
    print(f"\nAVERAGE defenders in the optimal XI: {np.mean(defcounts):.2f}")
    print(f"optimal XI had 5 DEF in {defcounts.count(5)}/38 weeks; "
          f"<=3 DEF in {sum(1 for d in defcounts if d<=3)}/38 weeks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
