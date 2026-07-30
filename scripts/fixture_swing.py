#!/usr/bin/env python3
"""
fixture_swing.py — how much do returns swing with opponent quality? (rotation value)
====================================================================================

Rotation is only worth paying for if points swing with the fixture. This measures,
per position, points-per-appearance vs opponent tier, using 2025-26 gameweek data
and FPL's team strength ratings:
  * GK / DEF  -> split by the OPPONENT'S ATTACK strength (weak attack = clean sheet
                 likely = more points).
  * MID / FWD -> split by the OPPONENT'S DEFENCE strength.
Venue-adjusted (an away team brings its away attack). Big swing (weak >> strong) =>
a rotation option that plays only its good fixtures is valuable. Flat => it isn't.
Restricted to real appearances (>=60 mins) by players who started >=10 games, so
it reflects a startable asset, not fodder.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> int:
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    t = pd.read_csv(RAW / "teams_2025-26.csv")
    atk = {r.id: (r.strength_attack_home + r.strength_attack_away) / 2 for r in t.itertuples()}
    dfn = {r.id: (r.strength_defence_home + r.strength_defence_away) / 2 for r in t.itertuples()}
    # venue-adjusted opponent strength for each fixture
    g["opp_atk"] = [(_t.strength_attack_away if home else _t.strength_attack_home)
                    for home, _t in zip(g.was_home, t.set_index("id").loc[g.opponent_team].itertuples())]
    g["opp_def"] = [(_t.strength_defence_away if home else _t.strength_defence_home)
                    for home, _t in zip(g.was_home, t.set_index("id").loc[g.opponent_team].itertuples())]

    # opponent tiers by average attack / defence (strong=top6, weak=bottom6)
    atk_rank = pd.Series(atk).rank(ascending=False)   # 1 = strongest attack
    def_rank = pd.Series(dfn).rank(ascending=False)    # 1 = strongest defence
    def tier(rank):
        return "strong" if rank <= 6 else ("weak" if rank >= 15 else "mid")
    g["opp_atk_tier"] = g.opponent_team.map(lambda i: tier(atk_rank[i]))
    g["opp_def_tier"] = g.opponent_team.map(lambda i: tier(def_rank[i]))

    # startable assets only: players with >=10 starts across the season
    starts = g.groupby("element")["starts"].sum()
    good = set(starts[starts >= 10].index)
    app = g[(g.minutes >= 60) & (g.element.isin(good))].copy()

    order = ["strong", "mid", "weak"]
    print("Points per appearance (>=60 mins) by OPPONENT tier — startable players only\n")
    for pos, axis, tcol, lab in [("GK", "attack", "opp_atk_tier", "opponent ATTACK"),
                                 ("DEF", "attack", "opp_atk_tier", "opponent ATTACK"),
                                 ("MID", "defence", "opp_def_tier", "opponent DEFENCE"),
                                 ("FWD", "defence", "opp_def_tier", "opponent DEFENCE")]:
        sub = app[app.position == pos]
        m = sub.groupby(tcol)["total_points"].agg(["mean", "count"]).reindex(order)
        strong, mid, weak = (m.loc[o, "mean"] for o in order)
        swing = weak - strong
        ratio = weak / strong if strong else float("nan")
        print(f"{pos}  (vs {lab}):  strong {strong:4.2f}  |  mid {mid:4.2f}  |  weak {weak:4.2f} "
              f"   swing +{swing:.2f} pts/app  ({ratio:.2f}x)")
        print(f"      n appearances: strong {int(m.loc['strong','count'])}, "
              f"mid {int(m.loc['mid','count'])}, weak {int(m.loc['weak','count'])}")
    print("\nBigger swing => a rotation option (played only in its 'weak-opponent' weeks) "
          "captures more, so it is worth keeping playable.")

    # implied rotation uplift: if you only played appearances vs weak+mid (skip strong)
    print("\nImplied uplift from fixture-picking (play only vs mid/weak, bench vs strong):")
    for pos, tcol in [("GK", "opp_atk_tier"), ("DEF", "opp_atk_tier"),
                      ("MID", "opp_def_tier"), ("FWD", "opp_def_tier")]:
        sub = app[app.position == pos]
        allmean = sub["total_points"].mean()
        picked = sub[sub[tcol] != "strong"]["total_points"].mean()
        print(f"  {pos}: every game {allmean:.2f} -> only non-strong fixtures {picked:.2f} "
              f"(+{100*(picked/allmean-1):.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
