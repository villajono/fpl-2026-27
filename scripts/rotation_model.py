#!/usr/bin/env python3
"""
rotation_model.py — should you crash bench slots, or keep them playable?
========================================================================

The crash-vs-keep decision as an OUTPUT, not an input. Each slot is valued by
points-per-game (from 2025-26). A season is simulated week by week: every player
gets a fixture multiplier that week (some weeks easy, some hard), and you play the
best LEGAL XI by expected points. So a playable bench option only earns points on
the weeks its fixture beats a starter's — exactly the rotation the brief describes
(start Def #4 the week Def #3 is away to Arsenal).

We hold a fixed strong XI and GK2 (always crashed — a backup keeper never plays),
then test all 8 combinations of the three outfield bench slots (DEF/MID/FWD) being
PLAYABLE (£5.0m, rotatable) vs CRASHED (£4.0m, ~never plays). Crashing frees £1.0m,
spent upgrading the weakest starting midfielder (the best marginal £ from the value
curves). Same total £100m every time, so it's a fair fight. Run at two fixture-
variance levels because "how much you rotate" is the one real behavioural unknown.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "players_raw_2025-26.csv"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
RNG = np.random.default_rng(42)
N_SEASONS = 400
N_WEEKS = 38


def ppg_frontier(d: pd.DataFrame):
    """achievable_ppg(pos, price) = top-few mean points-per-start in that price band."""
    reg = d[d.starts >= 10].copy()
    reg["ppg"] = reg.total_points / reg.starts
    def f(pos, price):
        s = reg[reg.pos == pos]
        for w in (0.3, 0.5, 0.8, 1.5):
            band = s[(s.start_price >= price - w) & (s.start_price <= price + w)]
            if len(band) >= 2:
                return band.nlargest(min(5, len(band)), "ppg")["ppg"].mean()
        return s["ppg"].max() if len(s) else 2.0
    return f


def best_xi_value(v, pos):
    """Max sum of values for a legal XI: 1 GK + DEF 3-5, MID 2-5, FWD 1-3 (10 outfield)."""
    gk = v[pos == "GK"].max()
    D = np.sort(v[pos == "DEF"])[::-1]
    M = np.sort(v[pos == "MID"])[::-1]
    F = np.sort(v[pos == "FWD"])[::-1]
    best = -1
    for nd in range(3, 6):
        for nf in range(1, 4):
            nm = 10 - nd - nf
            if not (2 <= nm <= 5):
                continue
            if nd > len(D) or nm > len(M) or nf > len(F):
                continue
            best = max(best, D[:nd].sum() + M[:nm].sum() + F[:nf].sum())
    return gk + best


def sim_points(prices, positions, ppg_f, sigma):
    ppg = np.array([ppg_f(p, pr) for p, pr in zip(positions, prices)])
    pos = np.array(positions)
    total = 0.0
    for _ in range(N_SEASONS):
        # fixture multiplier per player per week (known when you pick), clipped >=0
        mult = np.clip(RNG.normal(1.0, sigma, size=(N_WEEKS, len(ppg))), 0.05, None)
        wk_val = mult * ppg                       # expected points you can see each wk
        for w in range(N_WEEKS):
            total += best_xi_value(wk_val[w], pos)
    return total / N_SEASONS


def main() -> int:
    d = pd.read_csv(RAW)
    d["pos"] = d["element_type"].map(POS)
    d["start_price"] = (d["now_cost"] - d["cost_change_start"]) / 10.0
    for c in ["total_points", "starts"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    ppg_f = ppg_frontier(d)

    print("achievable points-per-game by position & price (top-few mean):")
    for p in ["GK", "DEF", "MID", "FWD"]:
        pts = {pr: round(ppg_f(p, pr), 1) for pr in [4.5, 5.0, 6.0, 7.0, 9.0, 12.0]}
        print(f"  {p}: " + "  ".join(f"£{k}->{v}" for k, v in pts.items()))
    print()

    # fixed strong XI (from the value curves) + GK2 crashed; 3 outfield bench vary
    XI = [("GK", 5.5),
          ("DEF", 6.5), ("DEF", 6.0), ("DEF", 5.0), ("DEF", 4.5),
          ("MID", 13.0), ("MID", 9.0), ("MID", 7.0), ("MID", 6.0),
          ("FWD", 10.5), ("FWD", 8.0)]
    GK2 = ("GK", 4.0)
    weak_mid_idx = XI.index(("MID", 6.0))       # freed £ upgrades this slot

    combos = [(dd, mm, ff) for dd in (0, 1) for mm in (0, 1) for ff in (0, 1)]  # 1=crash
    print(f"Base XI £{sum(p for _,p in XI):.1f}m + GK2 £4.0m ; 3 outfield bench @ £5.0 playable / £4.0 crashed")
    print("(freed £ from crashing -> weakest starting MID upgrade). Testing all 8 bench combos.\n")

    for sigma in (0.30, 0.50):
        rows = []
        for (cd, cm, cf) in combos:
            xi = [list(t) for t in XI]
            freed = (cd + cm + cf) * 1.0
            xi[weak_mid_idx][1] += freed
            bench = [("DEF", 4.0 if cd else 5.0), ("MID", 4.0 if cm else 5.0), ("FWD", 4.0 if cf else 5.0)]
            squad = xi + [GK2] + bench
            positions = [p for p, _ in squad]
            prices = [pr for _, pr in squad]
            assert abs(sum(prices) - 100.0) < 1e-6, sum(prices)
            pts = sim_points(prices, positions, ppg_f, sigma)
            kept = "".join(nm for nm, c in zip(["D", "M", "F"], (cd, cm, cf)) if not c) or "none"
            rows.append((pts, cd + cm + cf, kept, cd, cm, cf))
        rows.sort(key=lambda r: -r[0])
        top = rows[0][0]
        print(f"--- fixture variance sigma={sigma} ({'modest' if sigma==0.30 else 'high'} rotation value) ---")
        print(f"  {'playable benches':<18} {'#crashed':>8} {'season pts':>11} {'vs best':>8}")
        for pts, ncrash, kept, cd, cm, cf in rows:
            lab = kept if kept != "none" else "(crash all 3)"
            print(f"  {lab:<18} {ncrash:>8} {pts:>11.0f} {pts-top:>+8.1f}")
        b = rows[0]
        print(f"  => best: keep playable [{b[2]}], crash {b[1]} "
              f"(freed £{b[1]:.1f}m into the £6.0 mid -> £{6.0+b[1]:.1f}m)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
