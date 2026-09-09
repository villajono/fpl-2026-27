#!/usr/bin/env python3
"""swing.py — fixture swings measured against YOUR squad, which is what triggers a wildcard.

WHY THIS EXISTS
`weekly.py` has two fixture-swing signals and neither answers the question a wildcard asks.

  fixture_swing(team)   mean opponent strength over the next six. A level, not a swing — its own
                        comment concedes there is no 'recent' half to compare against.
  _swing_present(gw)    True if ANY of the twenty clubs has a swing. It gates the wildcard
                        recommendation, is almost always True, and knows nothing about who you own.

A wildcard is not triggered by a swing existing somewhere. It is triggered by a swing landing on
YOUR squad — several of your players' fixtures turning at once, while several clubs you do not own
turn the other way. One free transfer fixes one of those. A wildcard fixes all of them, and that
is the whole of its advantage over just doing the obvious move each week.

So the number that matters is the MOVE COUNT: how many changes the fixture picture implies, against
how many free transfers you will have. When implied moves comfortably exceed free transfers, the
alternative to the chip is a run of -4s, and the chip wins.

    python scripts/swing.py            # your squad, next 6 GWs
    python scripts/swing.py --gw 6     # what the same picture looks like if you wait
"""
from __future__ import annotations

import sys

import numpy as np

import weekly as W

WINDOW = 6
HARD, EASY = -0.06, 0.06          # deviation from league average that counts as a real swing


def ease(team, gw0, window=WINDOW):
    """Two numbers per club, because a swing helps attackers and defenders differently.

    att: mean opponent DEFENSIVE weakness  — higher means your forwards feast.
    cs:  mean opponent ATTACKING weakness  — higher means your defenders keep clean sheets.
    A blank week contributes nothing rather than counting as an easy game."""
    a, c = [], []
    for o in range(window):
        for opp, _home in W._fx(team, gw0 + o):
            r = W.FR.RATINGS.get(opp, {})
            a.append(r.get("defw", 1.0))
            c.append(2.0 - r.get("att", 1.0))
    return (float(np.mean(a)) if a else 1.0, float(np.mean(c)) if c else 1.0)


def main():
    # weekly.py sets CURRENT_GW and the Bayesian team ratings inside its refresh, not at import,
    # so without this the module still holds CURRENT_GW=0 and pure pre-season priors.
    for line in W.auto_ingest_and_refresh():
        print("  " + line)
    print("")
    gw0 = W.CURRENT_GW + 1
    if "--gw" in sys.argv:
        gw0 = int(sys.argv[sys.argv.index("--gw") + 1])

    squad = W.HUMAN if hasattr(W, "HUMAN") else None
    if squad is None:
        print("no squad found in weekly.py"); return
    held = {}
    for (n, pos, team, _pr) in squad:
        held.setdefault(team, []).append((n, pos))

    clubs = [t for t in W.SCHED if W.FR.RATINGS.get(t)]
    sc = {t: ease(t, gw0) for t in clubs}
    la = float(np.mean([v[0] for v in sc.values()]))
    lc = float(np.mean([v[1] for v in sc.values()]))

    print(f"FIXTURE SWING vs YOUR SQUAD — GW{gw0} to GW{gw0 + WINDOW - 1}")
    print(f"  league average ease: attack {la:.2f}, clean sheet {lc:.2f}\n")

    print("  CLUBS YOU OWN")
    print(f"  {'club':<6}{'own':>4}{'att':>7}{'cs':>7}   players")
    move = []
    for t in sorted(held, key=lambda x: sc.get(x, (1, 1))[0]):
        if t not in sc:
            continue
        a, c = sc[t]
        names = ", ".join(f"{n} ({p})" for n, p in held[t])
        flag = ""
        # judge each player on the axis that actually pays him
        bad = [(n, p) for n, p in held[t]
               if (c - lc < HARD if p in ("GK", "DEF") else a - la < HARD)]
        if bad:
            flag = f"   <- {len(bad)} to move"
            move += [(n, p, t) for n, p in bad]
        print(f"  {t:<6}{len(held[t]):>4}{a - la:>+7.2f}{c - lc:>+7.2f}   {names}{flag}")

    print("")
    print("  BEST TARGETS YOU DO NOT OWN  (club strength x fixture ease, not ease alone)")
    print(f"  {'club':<6}{'own att':>9}{'fixt':>7}{'ATTACK':>9}   "
          f"{'own def':>9}{'fixt':>7}{'CLEAN SHEET':>13}{'slots':>7}")

    def idx(t):
        # attacking: how good they are TIMES how weak the defences they meet
        # clean sheet: how solid they are TIMES how blunt the attacks they meet
        r = W.FR.RATINGS.get(t, {})
        a, c = sc[t]
        return r.get("att", 1.0) * a, (2 - r.get("defw", 1.0)) * c

    # Owning one player at a club does not disqualify it. FPL allows three, and "two more"
    # is exactly the shape of a fixture-swing rebuild — so rank on free slots, not on absence.
    room = [x for x in sc if len(held.get(x, [])) < 3]
    for t in sorted(room, key=lambda x: -idx(x)[0])[:7]:
        r = W.FR.RATINGS.get(t, {})
        a, c = sc[t]
        ai, ci = idx(t)
        slots = 3 - len(held.get(t, []))
        print(f"  {t:<6}{r.get('att', 1.0):>9.2f}{a - la:>+7.2f}{ai:>9.2f}   "
              f"{r.get('defw', 1.0):>9.2f}{c - lc:>+7.2f}{ci:>13.2f}{slots:>7}")
    print("  A kind run at a weak club is not a buy. Rank on the product, not the fixture column.")

    ft = 3   # what Jon will hold at GW4 having rolled
    print(f"\n  implied moves: {len(move)}   free transfers available: ~{ft}")
    if len(move) > ft:
        cost = 4 * (len(move) - ft)
        print(f"  Doing this with transfers costs about {cost} points in hits. That is the number")
        print("  the wildcard has to beat, and it is the real argument for the chip — not the")
        print("  rebuild-gain figure, which mostly measures how stale the squad already is.")
    else:
        print("  Free transfers cover the escapes. But this count is a FLOOR, not the answer: it")
        print("  counts players leaving a bad run and not players moved INTO a good one. A squad")
        print("  can be full of average fixtures and still be worth repositioning wholesale, and")
        print("  that case will never show up here.")
    print("  Ratings are ~90% prior after two gameweeks, but the prior is not weak: it is last")
    print("  season scaled by fixture_ratings.IMPLIED, which IS the market's expected-points")
    print("  adjustment (CHE +16, TOT +20, LIV +11, NEW +3.5, FUL -7.5). The fixture columns look")
    print("  small because they average six opponents; the club columns carry the market view.")


if __name__ == "__main__":
    main()
