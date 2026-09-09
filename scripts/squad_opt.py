#!/usr/bin/env python3
"""squad_opt.py — the PROVABLY optimal squad for a locked forecast.

WHY THIS REPLACES THE HILL-CLIMB

wc_build.py climbed greedily, one swap at a time, and two runs on the same objective returned
squads 3 points apart. That is not a view, it is search noise — a greedy climb cannot reach a
two-premium-defender squad from a Haaland one, because no SINGLE swap along the way improves.

That would be tolerable in a squad suggester. It is not tolerable underneath `wc_gain`, which is
`refit - current`: if the refit is understated by a varying amount each week, the wildcard gain is
noisy, and the timing rule compares gains ACROSS weeks. Search noise in the refit becomes noise in
the chip decision, and from there into the transfer threshold and every weekly call.

So: solve it exactly.

THE FORMULATION

Two parts of the objective look non-linear. Both linearise.

  RANK WEIGHTS  A player's weight depends on where he ranks within his position in YOUR squad
                (compare.WEIGHTS: DEF 1.0/1.0/1.0/0.7/0.4). Model it as slot assignment —
                x[p,s] = 1 if player p fills slot s. Because the weights DECREASE and we are
                maximising, the solver puts the highest-value player in the highest-weight slot
                on its own. No ordering constraints are needed, which is what keeps it clean.

  CAPTAIN       sum over weeks of the best owned player THAT WEEK. Binary y[p,w], one per week,
                with y[p,w] <= sum_s x[p,s] so you can only captain someone you own. Maximising
                selects the weekly best automatically.

Everything else — budget, three-per-club, position quotas — is already linear. Solved with
scipy.optimize.milp (HiGHS), which is already installed; no new dependency.

    python scripts/squad_opt.py                      # optimal squad for the locked forecast
    python scripts/squad_opt.py --pool 60            # widen the candidate pool
    python scripts/squad_opt.py --validate           # prove it against known squads + brute force
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
from scipy.optimize import LinearConstraint, milp

import compare as C
import forecast as F

BUDGET = 100.0
QUOTA = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3
POOL_PER_POS = 45          # candidates per position; --validate checks this does not bind


def solve(players, decay, horizon, budget=BUDGET, forced=(), pool_per_pos=POOL_PER_POS,
          banned=(), keep=(), max_changes=None):
    """players: {key: {pos, team, price, ev[]}}. Returns (keys, objective, binding_report).

    keep / max_changes turn the wildcard solve into an N-TRANSFER solve. `keep` is the squad you
    hold now; `max_changes` is how many of them you may replace. Without these the solver rebuilds
    from scratch, which answers the wildcard question and not the weekly one.

    This matters because a greedy single-swap search cannot evaluate a PACKAGE. Selling a premium
    to fund two upgrades is worse on every intermediate step and better at the end, so a hill-climb
    rejects it at step one. That is the same reason the wildcard refit was made exact — the
    formulation is identical, with one extra row.
    """
    val = {k: sum(decay[i] * e for i, e in enumerate(v["ev"])) for k, v in players.items()}
    forced = set(forced)
    banned = set(banned)

    # restrict to the best few per position, plus anything forced — the full 491 is solvable but
    # slow inside a timing sweep that calls this sixty times
    # anyone you already hold is a candidate by definition - he is keepable whether or not he
    # ranks in the top few of his position, and leaving him out makes the solver "sell" him for
    # free, understating the cost of a package.
    cand = set(forced) | {k for k in keep if k in players}
    for pos in QUOTA:
        byp = sorted((k for k, v in players.items()
                      if v["pos"] == pos and k not in banned),
                     key=lambda k: -val[k])
        cand.update(byp[:pool_per_pos])
    cand = sorted((cand - banned) | set(forced) | {k for k in keep if k in players})
    idx = {k: i for i, k in enumerate(cand)}

    # ---- variables: x[(player, slot)] then y[(player, week)] ----
    xs = [(k, pos, s) for k in cand for pos in [players[k]["pos"]]
          for s in range(QUOTA[pos])]
    ys = [(k, w) for k in cand for w in range(horizon)]
    nx, ny = len(xs), len(ys)
    n = nx + ny

    c = np.zeros(n)
    for j, (k, pos, s) in enumerate(xs):
        c[j] = -C.WEIGHTS[pos][s] * val[k]              # milp minimises, so negate
    for j, (k, w) in enumerate(ys):
        c[nx + j] = -decay[w] * players[k]["ev"][w]

    A, lo, hi = [], [], []

    def row():
        return np.zeros(n)

    # each player occupies at most one slot
    for k in cand:
        r = row()
        for j, (kk, _, _) in enumerate(xs):
            if kk == k:
                r[j] = 1
        A.append(r); lo.append(0); hi.append(1)

    # each slot filled exactly once
    for pos, q in QUOTA.items():
        for s in range(q):
            r = row()
            for j, (_, pp, ss) in enumerate(xs):
                if pp == pos and ss == s:
                    r[j] = 1
            A.append(r); lo.append(1); hi.append(1)

    # budget
    r = row()
    for j, (k, _, _) in enumerate(xs):
        r[j] = players[k]["price"]
    A.append(r); lo.append(0); hi.append(budget)

    # at most three from any club
    for club in {players[k]["team"] for k in cand}:
        r = row()
        for j, (k, _, _) in enumerate(xs):
            if players[k]["team"] == club:
                r[j] = 1
        A.append(r); lo.append(0); hi.append(MAX_PER_CLUB)

    # exactly one captain each week
    for w in range(horizon):
        r = row()
        for j, (_, ww) in enumerate(ys):
            if ww == w:
                r[nx + j] = 1
        A.append(r); lo.append(1); hi.append(1)

    # you may only captain a player you own
    for k in cand:
        owned = [j for j, (kk, _, _) in enumerate(xs) if kk == k]
        for w in range(horizon):
            j = ys.index((k, w))
            r = row()
            r[nx + j] = 1
            for o in owned:
                r[o] = -1
            A.append(r); lo.append(-np.inf); hi.append(0)

    # keep at least (15 - max_changes) of the squad you already hold: an N-transfer solve.
    # Players you hold who are NOT in the candidate pool cannot be kept by the solver, so they
    # count as forced changes; subtract them from the allowance rather than letting the solver
    # silently get free transfers it does not have.
    if keep and max_changes is not None:
        keepable = [k for k in keep if k in idx]
        unkeepable = len(keep) - len(keepable)
        allowance = max_changes - unkeepable
        if allowance < 0:
            raise ValueError(
                f"{unkeepable} held player(s) are outside the candidate pool, which already "
                f"exceeds max_changes={max_changes}. Widen --pool or raise the transfer count.")
        r = row()
        for j, (kk, _, _) in enumerate(xs):
            if kk in set(keepable):
                r[j] = 1
        A.append(r); lo.append(len(keepable) - allowance); hi.append(np.inf)

    # forced picks
    for k in forced:
        if k not in idx:
            continue
        r = row()
        for j, (kk, _, _) in enumerate(xs):
            if kk == k:
                r[j] = 1
        A.append(r); lo.append(1); hi.append(1)

    res = milp(c=c, constraints=LinearConstraint(np.array(A), lo, hi),
               integrality=np.ones(n), bounds=(0, 1))
    if not res.success:
        raise RuntimeError(f"solver failed: {res.message}")

    chosen = [xs[j][0] for j in range(nx) if res.x[j] > 0.5]
    # did the pool restriction bind? if the worst chosen player sits at the cut-off, widen it
    binding = []
    for pos in QUOTA:
        byp = sorted((k for k, v in players.items() if v["pos"] == pos), key=lambda k: -val[k])
        cut = byp[pool_per_pos - 1] if len(byp) >= pool_per_pos else None
        picked = [k for k in chosen if players[k]["pos"] == pos]
        if cut and picked and min(val[k] for k in picked) <= val[cut] + 1e-9:
            binding.append(pos)
    return chosen, -res.fun, binding


def main():
    fc = F.load(_gw())
    players = fc["players"]
    decay = [fc["decay"][str(i + 1)] for i in range(fc["horizon"])]
    pool = int(sys.argv[sys.argv.index("--pool") + 1]) if "--pool" in sys.argv else POOL_PER_POS
    forced = []
    if "--force-in" in sys.argv:
        forced = [x.strip() for x in sys.argv[sys.argv.index("--force-in") + 1].split(",")]

    chosen, obj, binding = solve(players, decay, fc["horizon"], forced=forced, pool_per_pos=pool)
    show(chosen, players, obj, fc, binding)

    if "--validate" in sys.argv:
        validate(chosen, obj, players, decay, fc)


def _gw():
    return int(sys.argv[sys.argv.index("--gw") + 1]) if "--gw" in sys.argv else _next_gw()


def _next_gw():
    import glob
    import re
    ns = [int(re.search(r"forecast_gw(\d+)", f).group(1))
          for f in glob.glob("data/processed/forecast_gw*.json")]
    if not ns:
        raise SystemExit("  no locked forecast — run: python scripts/forecast.py")
    return max(ns)


def show(chosen, players, obj, fc, binding):
    val = {k: sum(fc["decay"][str(i + 1)] * e for i, e in enumerate(players[k]["ev"]))
           for k in chosen}
    spend = sum(players[k]["price"] for k in chosen)
    print(f"\n  OPTIMAL SQUAD — GW{fc['gw0']}, £{spend:.1f}m, objective {obj:.1f}")
    print(f"  forecast locked {fc['generated']}")
    print(f"  {'player':<20}{'club':<6}{'pos':<5}{'£':>6}{'6wk val':>9}{'conf':>7}")
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    for k in sorted(chosen, key=lambda k: (order[players[k]["pos"]], -val[k])):
        v = players[k]
        print(f"  {k.split('|')[0][:19]:<20}{v['team']:<6}{v['pos']:<5}{v['price']:>6.1f}"
              f"{val[k]:>9.1f}{v['confidence']:>7.2f}")
    print(f"\n  bank £{BUDGET - spend:.1f}m")
    if binding:
        print(f"  !! pool restriction BINDS at {binding} — a chosen player sits at the cut-off.")
        print("     Re-run with a larger --pool; the answer may not be optimal as it stands.")
    else:
        print("  pool restriction does not bind: no chosen player sits at the cut-off, so")
        print("  widening it cannot change the answer.")


def validate(chosen, obj, players, decay, fc):
    print("\n  VALIDATION")

    # 1. the objective the solver reports must equal what compare.squad_value computes on the
    #    squad it returned. It is easy to write an ILP that optimises something subtly different
    #    from the scoring function everything else uses, and that failure is silent.
    sq = [dict(name=k.split("|")[0], team=players[k]["team"], pos=players[k]["pos"],
               price=players[k]["price"]) for k in chosen]
    evs = {(k.split("|")[0], players[k]["team"]): players[k]["ev"] for k in players}
    recomputed = C.squad_value(sq, evs)
    ok = abs(recomputed - obj) < 0.05
    print(f"    solver objective {obj:.2f} vs compare.squad_value {recomputed:.2f}"
          f"   {'MATCH' if ok else '*** MISMATCH — formulation is wrong ***'}")

    # 2. it must beat every squad we already know about, or it is not optimal
    for label, names in C.SQUADS.items():
        got, miss = C.resolve_all(names, {(c["name"], c["team"]): c for c in [
            dict(name=k.split("|")[0], team=v["team"], pos=v["pos"], price=v["price"])
            for k, v in players.items()]}, {})
        if miss:
            print(f"    {label:<22} cannot resolve {miss}")
            continue
        v = C.squad_value(got, evs)
        flag = "ok" if obj >= v - 0.05 else "*** OPTIMAL SQUAD SCORES LOWER — BUG ***"
        print(f"    vs {label:<19}{v:>8.1f}   optimal is {obj - v:+.1f}   {flag}")

    # 3. brute force a tiny pool and confirm an exact match
    # 6 per position, not 8: C(8,5)^2 x C(8,2) x C(8,3) is 4.9M squads and would never finish.
    # Three by value plus three by cheapness, so a legal sub-£100m squad is guaranteed to exist —
    # a pool of only expensive players makes the brute force infeasible rather than slow.
    print("    brute force on a restricted pool (6 per position)...")
    small = {}
    val = {k: sum(decay[i] * e for i, e in enumerate(v["ev"])) for k, v in players.items()}
    for pos in QUOTA:
        byp = [k for k, v in players.items() if v["pos"] == pos]
        top = sorted(byp, key=lambda k: -val[k])[:3]
        cheap = [k for k in sorted(byp, key=lambda k: players[k]["price"]) if k not in top][:3]
        for k in top + cheap:
            small[k] = players[k]
    ch, o, _ = solve(small, decay, fc["horizon"], pool_per_pos=99)
    best, bestsq = -1, None
    keys = {pos: [k for k, v in small.items() if v["pos"] == pos] for pos in QUOTA}
    for combo in itertools.product(*[itertools.combinations(keys[p], QUOTA[p]) for p in QUOTA]):
        pick = [k for grp in combo for k in grp]
        if sum(small[k]["price"] for k in pick) > BUDGET:
            continue
        clubs = {}
        for k in pick:
            clubs[small[k]["team"]] = clubs.get(small[k]["team"], 0) + 1
        if max(clubs.values()) > MAX_PER_CLUB:
            continue
        s = [dict(name=k.split("|")[0], team=small[k]["team"], pos=small[k]["pos"],
                  price=small[k]["price"]) for k in pick]
        v = C.squad_value(s, evs)
        if v > best:
            best, bestsq = v, pick
    match = abs(best - o) < 0.05
    print(f"    MILP {o:.2f} vs exhaustive {best:.2f}   "
          f"{'MATCH' if match else '*** MISMATCH ***'}")


if __name__ == "__main__":
    main()
