#!/usr/bin/env python3
"""
experiments.py — Q3-Q6 with per-position variance. Reports MEAN (expected-points
objective) and p90/sd (ceiling — the rank objective). Every squad £100m, 2/5/5/3.
"""
from __future__ import annotations
import numpy as np
import season_sim as S

GP, CV = S.calibrate()
SEAS = 400


def squad(gk, dfs, mids, fwds, flex=("MID", 1)):
    slots = ([("GK", p) for p in gk] + [("DEF", p) for p in dfs]
             + [("MID", p) for p in mids] + [("FWD", p) for p in fwds])
    tot = sum(p for _, p in slots)
    pos, n = flex
    idxs = [i for i, (pp, _) in enumerate(slots) if pp == pos]
    slots[idxs[n]] = (pos, round(slots[idxs[n]][1] + (100 - tot), 1))
    return slots


def dist(sl, seasons=SEAS, weeks=S.N_WEEKS):
    sq = S.Squad(sl, GP, CV)
    m, tots = S.sim(sq, weeks=weeks, seasons=seasons, dist=True)
    return sq, m, np.percentile(tots, 90), tots.std()


CANDIDATES = {
 "A balanced":      squad([5.5,4.0],[6.5,5.5,5.0,4.5,4.0],[14.0,8.5,7.0,5.5,5.0],[12.0,7.5,5.5]),
 "B attack (4DEF)": squad([5.5,4.0],[6.0,5.0,4.5,4.0,4.0],[14.0,9.0,7.5,6.0,5.0],[12.0,8.0,5.5]),
 "C flex (5DEF)":   squad([6.0,4.0],[7.0,5.5,5.5,5.0,4.5],[13.0,7.5,6.5,6.0,5.0],[11.5,7.5,5.5]),
 "D Haaland+8+6":   squad([5.5,4.0],[6.0,5.0,4.5,4.5,4.0],[10.5,9.5,6.5,5.5,5.0],[15.5,8.0,6.0]),
 "E 2x prem MID":   squad([5.5,4.0],[6.0,5.0,4.5,4.5,4.0],[13.0,9.5,7.0,5.5,5.0],[8.5,6.5,5.5]),
}


def main():
    print("=== Q4: STRUCTURE — expected pts (MEAN) vs ceiling (p90) ; £100m each ===\n")
    print(f"  {'structure':<16} {'mean':>6} {'p90':>6} {'sd':>5}  {'formation played (top)':>28}")
    res = {}
    for name, sl in CANDIDATES.items():
        sq, m, p90, sd = dist(sl)
        res[name] = (sq, m, p90, sd, sl)
        fm = formation_mix(sq)
        top = ", ".join(f"{k} {v:.0f}%" for k, v in sorted(fm.items(), key=lambda x: -x[1])[:3])
        print(f"  {name:<16} {m:>6.0f} {p90:>6.0f} {sd:>5.0f}  {top:>28}")
    best_mean = max(res, key=lambda k: res[k][1])
    best_p90 = max(res, key=lambda k: res[k][2])
    print(f"\n  highest EXPECTED pts: {best_mean}   |   highest CEILING (p90): {best_p90}")

    print("\n=== Q3: MARGINAL SLOT VALUE (best-mean squad) ===\n")
    sq = S.Squad(res[best_mean][4], GP, CV)
    _, slot = S.sim(sq, seasons=SEAS, attribute=True)
    order = np.argsort(-slot); cum = 0
    print(f"  {'rank':>4} {'slot':>10} {'pts':>6} {'cum%':>6}")
    for r, i in enumerate(order, 1):
        cum += slot[i]
        print(f"  {r:>4} {sq.pos[i]+' £'+str(sq.price[i]):>10} {slot[i]:>6.0f} {100*cum/slot.sum():>5.0f}%")

    print("\n=== Q5: BENCH PRICING (mean | p90) ===\n")
    for label, dfs, mids, fwds in [
        ("playable bench", [6.0,5.0,4.5,4.5,4.5], [14.0,8.5,7.0,5.5,5.0], [12.0,7.5,5.0]),
        ("crashed bench",  [6.5,5.5,5.0,4.5,4.0], [14.5,9.0,7.0,5.5,5.0], [12.0,7.5,4.5])]:
        sq, m, p90, sd = dist(squad([5.0,4.0], dfs, mids, fwds))
        print(f"  {label:<16} mean {m:.0f} | p90 {p90:.0f}")

    print("\n=== Q6: FIRST 6 GW vs FULL SEASON ===\n")
    for name, sl in [("aggressive/thin", squad([5.0,4.0],[6.5,5.5,5.0,4.5,4.0],[14.5,9.0,7.0,5.5,5.0],[13.0,7.5,4.5])),
                     ("deep-bench",       squad([5.0,4.5],[6.0,5.0,5.0,4.5,4.5],[13.5,8.5,7.0,5.5,5.0],[11.5,7.5,5.5]))]:
        _, m6, p6, _ = dist(sl, seasons=800, weeks=6)
        _, mF, pF, _ = dist(sl, weeks=38)
        print(f"  {name:<16} 6GW mean {m6:.0f} p90 {p6:.0f}  | full mean {mF:.0f} p90 {pF:.0f}")
    return 0


def formation_mix(sq, seasons=120):
    from collections import Counter
    c = Counter()
    for _ in range(seasons):
        for _w in range(S.N_WEEKS):
            fix = np.clip(S.RNG.normal(1, S.FIX_SD, sq.n), .1, None)
            gk, (D, M, F) = S._pick_xi(sq.ppg * fix * sq.pstart, sq)
            c[f"{len(D)}-{len(M)}-{len(F)}"] += 1
    n = sum(c.values())
    return {k: 100 * v / n for k, v in c.items()}


if __name__ == "__main__":
    raise SystemExit(main())
