#!/usr/bin/env python3
"""
autosub_value.py — value a SLOT, not a player: zeros are auto-subbed, cameos are the tax.
=========================================================================================
Raw total points over-penalises clean rotation. If a starter plays 0 mins you get an
auto-sub (bank the bench player's score, ~BENCH_FILL), so their zero is nearly free.
The real cost is the CAMEO (1-59 mins): it blocks the sub and banks ~1 point.

Banked-slot points per GW:
    60+ mins  -> the player's actual points that GW
    0 mins    -> BENCH_FILL (auto-sub fires)
    1-59 mins -> the player's (low) cameo points (sub BLOCKED)  <-- the tax

Also fixes club attribution: last-season performance is joined to the 2026-27 club via
the permanent player 'code', and movers are flagged (their new context is an unknown).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
BENCH_FILL = 3.0        # a playing bench defender's typical week (cheap DEF ~3.1 pts/app)


def main():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
    for c in ["minutes", "total_points", "GW"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    pr["pos"] = pr["element_type"].map(POS)
    pr["start_price"] = (pr["now_cost"] - pr["cost_change_start"]) / 10.0

    # collapse DGWs to one row per (player, GW)
    gw = g.groupby(["element", "GW"]).agg(mins=("minutes", "sum"),
                                          pts=("total_points", "sum")).reset_index()
    def cat(m):
        return "s60" if m >= 60 else ("cameo" if m >= 1 else "zero")
    gw["cat"] = gw["mins"].map(cat)

    rows = []
    for el, pg in gw.groupby("element"):
        n60 = (pg.cat == "s60").sum(); ncam = (pg.cat == "cameo").sum()
        nzero = 38 - n60 - ncam
        pts60 = pg.loc[pg.cat == "s60", "pts"].sum()
        ptscam = pg.loc[pg.cat == "cameo", "pts"].sum()
        raw = pts60 + ptscam + pg.loc[pg.cat == "zero", "pts"].sum()
        banked = pts60 + ptscam + max(nzero, 0) * BENCH_FILL
        rows.append((el, n60, ncam, max(nzero, 0), raw, banked))
    v = pd.DataFrame(rows, columns=["element", "n60", "ncameo", "nzero", "raw", "banked"])

    # link 2025-26 -> 2026-27 club via permanent code; flag movers
    code26 = dict(zip(nxt["code"], nxt["team_name"]))
    last_team = g.groupby("element")["team"].agg(lambda s: s.mode().iloc[0])
    d = pr[["id", "code", "web_name", "pos", "start_price"]].rename(columns={"id": "element"})
    d = d.merge(v, on="element")
    d["team_last"] = d["element"].map(last_team)
    d["team_2627"] = d["code"].map(code26)
    d["moved"] = d["team_2627"].notna() & (d["team_2627"] != d["team_last"].map(
        {"Man City": "MCI", "Arsenal": "ARS", "Spurs": "TOT", "Man Utd": "MUN", "Liverpool": "LIV",
         "Chelsea": "CHE", "Newcastle": "NEW", "Aston Villa": "AVL", "Brighton": "BHA",
         "Bournemouth": "BOU", "Brentford": "BRE", "Fulham": "FUL", "Crystal Palace": "CRY",
         "Everton": "EVE", "Nott'm Forest": "NFO", "Leeds": "LEE", "Sunderland": "SUN",
         "West Ham": "WHU", "Burnley": "BUR", "Wolves": "WOL"}))

    dd = d[(d.pos == "DEF") & d.start_price.between(4.5, 5.5) & (d.n60 >= 10)].copy()
    dd["autosub_uplift"] = dd["banked"] - dd["raw"]
    dd["p_start"] = dd["n60"] / 38.0

    print(f"~£5m defenders (bench fill = {BENCH_FILL} pts): raw vs auto-sub-BANKED points\n")
    dd["kind"] = np.where(dd.p_start >= 0.75, "nailed", "rotation")
    grp = dd.groupby("kind").agg(n=("element", "size"), raw=("raw", "mean"),
                                 banked=("banked", "mean"), cameo=("ncameo", "mean"),
                                 zero=("nzero", "mean")).round(1)
    print(grp.to_string())
    print("\n  -> rotation slots gain the most from auto-subs (their zeros -> bench fill);")
    print("     the gap to nailed slots shrinks once you value the SLOT not the player.\n")

    print("Biggest auto-sub 'winners' (clean rotators — raw total understates them):")
    for r in dd.nlargest(6, "autosub_uplift").itertuples():
        mv = f" MOVED->{r.team_2627}" if r.moved else ""
        print(f"   {r.web_name:<13} £{r.start_price} P(start){r.p_start:.2f} "
              f"raw {r.raw:.0f} -> banked {r.banked:.0f} (+{r.autosub_uplift:.0f}) "
              f"| cameo wks {r.ncameo}{mv}")

    print("\nThe CAMEO TAX — most 1-59 min weeks (auto-sub blocked, ~1pt banked):")
    for r in dd.nlargest(6, "ncameo").itertuples():
        mv = f" MOVED->{r.team_2627}" if r.moved else ""
        print(f"   {r.web_name:<13} £{r.start_price} cameo wks {r.ncameo:>2} "
              f"(vs {r.nzero} clean zeros) P(start){r.p_start:.2f}{mv}")
    print("\n(Caveat: one bench can only cover ~1 failure/week — auto-sub fill is a shared, "
          "finite resource, so this is an upper bound on rotation's 'free' zeros.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
