#!/usr/bin/env python3
"""
team_priority.py — which clubs to shop at for the initial 2026-27 squad.
========================================================================
Combines, per club:
  * QUALITY   — expected 2026-27 season points (clean sheets for GK/DEF, goals for
                MID/FWD concentrate in good teams).
  * FIXTURES  — the OPENING run (GW1-6, since the squad mostly plays to the GW6
                wildcard), scored by opponents' expected points (weak opp = easy).
  * PRICE     — cheapest entry price per position (where the value slots are).
Priority (for owning a club's assets early) = z(quality) + z(opening ease). Last
season's GA flags genuine defensive solidity for the cheap-defender call.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OPEN_GW = 6


def z(s):
    return (s - s.mean()) / s.std()


def main():
    fx = pd.read_csv(RAW / "fixtures_2026-27.csv")
    t = pd.read_csv(RAW / "teams_2026-27.csv")
    ep = pd.read_csv(RAW / "expected_points_2026-27.csv")
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
    POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    nxt["pos"] = nxt["element_type"].map(POS); nxt["price"] = nxt["now_cost"] / 10.0

    id2sh = dict(zip(t.id, t.short_name))
    exp = dict(zip(ep.short, ep.exp_pts_2026_27))
    ga_last = dict(zip(lt.short, lt.GA))            # last-season goals-against (defensive solidity)

    # opening run (GW1-6) and next block (GW7-12) opponent strength per team
    def window(lo, hi):
        w = fx[(fx.event >= lo) & (fx.event <= hi)]
        r = {sh: [] for sh in id2sh.values()}
        fxs = {sh: [] for sh in id2sh.values()}
        for x in w.itertuples():
            h, a = id2sh[x.team_h], id2sh[x.team_a]
            r[h].append(exp.get(a, 45)); fxs[h].append(f"{a}(H)")
            r[a].append(exp.get(h, 45)); fxs[a].append(f"{h}(A)")
        return r, fxs
    op, opfx = window(1, OPEN_GW)
    mid, _ = window(OPEN_GW + 1, 12)

    data = []
    for sh in id2sh.values():
        oe = np.mean(op[sh]) if op[sh] else 45
        me = np.mean(mid[sh]) if mid[sh] else 45
        n_easy = sum(1 for x in op[sh] if x <= 46)
        cheap = {p: nxt[(nxt.team_name == sh) & (nxt.pos == p)]["price"].min() for p in ["GK", "DEF", "MID", "FWD"]}
        data.append({"team": sh, "exp_pts": exp.get(sh, np.nan), "ga_last": ga_last.get(sh, np.nan),
                     "open_opp_exp": round(oe, 1), "mid_opp_exp": round(me, 1), "swing": round(me - oe, 1),
                     "n_easy_openers": n_easy, "openers": " ".join(opfx[sh]),
                     "cDEF": cheap["DEF"], "cMID": cheap["MID"], "cFWD": cheap["FWD"], "cGK": cheap["GK"]})
    df = pd.DataFrame(data)
    df["priority"] = z(df.exp_pts) + z(-df.open_opp_exp)     # own quality + opening ease
    df = df.sort_values("priority", ascending=False).reset_index(drop=True)

    print("=== TEAM PRIORITY for the initial squad (quality + opening-6 fixture ease) ===\n")
    print(f"  {'team':>5} {'expPts':>6} {'openDiff':>8} {'easy':>4} {'prio':>5}  {'cDEF':>4} {'cMID':>4} {'cFWD':>4}  opening 6")
    for r in df.itertuples():
        print(f"  {r.team:>5} {r.exp_pts:>6.1f} {r.open_opp_exp:>8.1f} {r.n_easy_openers:>4} {r.priority:>5.1f}  "
              f"{r.cDEF:>4.1f} {r.cMID:>4.1f} {r.cFWD:>4.1f}  {r.openers}")

    print("\n--- DEFENSIVE-asset targets (good team + solid last-yr defence + easy openers) ---")
    dfd = df[(df.exp_pts >= 52) | (df.ga_last <= 50)].copy()
    dfd["def_score"] = z(df.exp_pts) + z(-df.open_opp_exp) + z(-df.ga_last.fillna(df.ga_last.mean()))
    for r in dfd.sort_values("def_score", ascending=False).head(6).itertuples():
        print(f"  {r.team}: expPts {r.exp_pts:.0f}, lastGA {r.ga_last:.0f}, opening opp-exp {r.open_opp_exp:.0f}, "
              f"cheapest DEF £{r.cDEF} | {r.n_easy_openers}/6 easy")

    print("\n--- ATTACKING-asset targets (good team + easy openers) ---")
    for r in df.sort_values("priority", ascending=False).head(6).itertuples():
        print(f"  {r.team}: expPts {r.exp_pts:.0f}, opening opp-exp {r.open_opp_exp:.0f}, "
              f"cheapest MID £{r.cMID} / FWD £{r.cFWD} | {r.n_easy_openers}/6 easy")

    print("\n--- FADE early (tough opening run despite quality, or weak team) ---")
    for r in df.sort_values("priority").head(5).itertuples():
        print(f"  {r.team}: expPts {r.exp_pts:.0f}, opening opp-exp {r.open_opp_exp:.0f} (hard), {r.openers}")

    print("\n--- FIXTURE SWINGS (GW1-6 vs GW7-12) — initial-squad vs wildcard timing ---")
    print("  good NOW, harder later (own early, plan to move off at wildcard):")
    for r in df[(df.open_opp_exp <= 50) & (df.swing >= 3)].sort_values("swing", ascending=False).itertuples():
        print(f"    {r.team}: open {r.open_opp_exp:.0f} -> GW7-12 {r.mid_opp_exp:.0f} (+{r.swing:.0f} harder)")
    print("  poor NOW, easier later (WILDCARD target, not initial):")
    for r in df[(df.open_opp_exp >= 52) & (df.swing <= -3)].sort_values("swing").itertuples():
        print(f"    {r.team}: open {r.open_opp_exp:.0f} -> GW7-12 {r.mid_opp_exp:.0f} ({r.swing:.0f} easier)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
