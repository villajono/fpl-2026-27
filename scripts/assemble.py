#!/usr/bin/env python3
"""assemble.py — verify the two candidate 15-man squads (budget, club cap 3,
structure, formation viability). One flex slot per squad pads to exactly £100m."""
from __future__ import annotations
from collections import Counter
import pandas as pd
from pathlib import Path

m = pd.read_csv(Path(__file__).resolve().parent.parent / "data" / "outputs" / "master_candidates.csv")
PS = dict(zip(m.web_name, m.P_start.fillna(0)))
# promoted players have no PL data; per user's real-world read they are nailed starters
PS["van Ewijk"] = 0.95   # Coventry attacking full-back, played every game (user)
PS["Patterson"] = 0.90   # Sunderland #1 keeper (user)

# (name, club, pos, price)  — None price = flex slot (padded to hit £100m)
OPTION_A = [  # Haaland structure
 ("Pickford","EVE","GK",5.5), ("Patterson","SUN","GK",4.0),
 ("Virgil","LIV","DEF",6.5), ("Tarkowski","EVE","DEF",6.0), ("Chalobah","CHE","DEF",5.5),
 ("Shaw","MUN","DEF",4.5), ("van Ewijk","COV","DEF",4.0),
 ("Semenyo","MCI","MID",8.5), ("Mbeumo","MUN","MID",8.0), ("Rice","ARS","MID",7.5),
 ("Zubimendi","ARS","MID",5.5), ("Caicedo","CHE","MID",5.5),
 ("Haaland","MCI","FWD",15.5), ("João Pedro","CHE","FWD",7.5), ("Calvert-Lewin","LEE","FWD",6.0)]

OPTION_B = [  # no Haaland — spread the premium
 ("Pickford","EVE","GK",5.5), ("Patterson","SUN","GK",4.0),
 ("Virgil","LIV","DEF",6.5), ("Guéhi","MCI","DEF",6.0), ("Tarkowski","EVE","DEF",6.0),
 ("Shaw","MUN","DEF",4.5), ("van Ewijk","COV","DEF",4.0),
 ("Semenyo","MCI","MID",8.5), ("Mbeumo","MUN","MID",8.0), ("Rice","ARS","MID",7.5),
 ("Szoboszlai","LIV","MID",7.0), ("Zubimendi","ARS","MID",5.5),
 ("João Pedro","CHE","FWD",7.5), ("Watkins","AVL","FWD",8.0), ("Thiago","BRE","FWD",8.0)]


def check(name, sq):
    fixed = sum(p for *_, p in sq if p is not None)
    flex = [i for i, (*_, p) in enumerate(sq) if p is None]
    if flex:
        sq[flex[0]] = (*sq[flex[0]][:3], round(100 - fixed, 1))
    total = sum(p for *_, p in sq)
    clubs = Counter(c for _, c, _, _ in sq)
    over = {c: n for c, n in clubs.items() if n > 3}
    playable = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for nm, _, pos, _ in sq:
        if PS.get(nm, 0) >= 0.6:
            playable[pos] += 1
    print(f"\n=== {name} ===  total £{total:.1f}m  ITB £{100-total:.1f}m  | club-cap violations: {over or 'none'}")
    print(f"  playable (P_start>=0.6): GK{playable['GK']} DEF{playable['DEF']} MID{playable['MID']} FWD{playable['FWD']}")
    can = lambda d, mi, f: (playable['DEF'] >= d and playable['MID'] >= mi and playable['FWD'] >= f and playable['GK'] >= 1)
    print(f"  4-4-2: {'YES' if can(4,4,2) else 'no'}   3-5-2: {'YES' if can(3,5,2) else 'no'}   "
          f"5-3-2: {'YES' if can(5,3,2) else 'no(needs a 5th playable DEF)'}")
    for pos in ["GK", "DEF", "MID", "FWD"]:
        line = [f"{nm}({c},£{p},P{PS.get(nm,0):.2f})" for nm, c, po, p in sq if po == pos]
        print(f"  {pos}: " + " | ".join(line))


check("OPTION A — HAALAND", OPTION_A)
check("OPTION B — NO HAALAND (spread)", OPTION_B)
