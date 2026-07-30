#!/usr/bin/env python3
"""fetch_2026_prices.py — pull the upcoming 2026-27 player & price database from the
live FPL API (bootstrap-static) and save it. now_cost = the new-season prices;
total_points/minutes on these rows are LAST season's, carried as reference."""

from __future__ import annotations
import json, urllib.request
from pathlib import Path
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def main() -> int:
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    j = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))

    els = pd.json_normalize(j["elements"])
    teams = pd.json_normalize(j["teams"])
    tname = dict(zip(teams.id, teams.short_name))
    els["pos"] = els["element_type"].map(POS)
    els["team_name"] = els["team"].map(tname)
    els["price"] = els["now_cost"] / 10.0
    els.to_csv(RAW / "players_2026-27.csv", index=False)
    teams.to_csv(RAW / "teams_2026-27.csv", index=False)

    nxt = next((e for e in j["events"] if e.get("is_next")), j["events"][0])
    print(f"2026-27 database saved: {len(els)} players, {len(teams)} clubs")
    print(f"season opens {nxt['name']} — deadline {nxt['deadline_time']}\n")

    print(f"{'pos':>4} {'n':>4} {'floor':>6} {'median':>7} {'max':>5}  (start prices, £m)")
    for p in ["GK", "DEF", "MID", "FWD"]:
        s = els[els.pos == p]["price"]
        print(f"  {p:>2} {len(s):>4} {s.min():>6.1f} {s.median():>7.1f} {s.max():>5.1f}")
    floors = {p: els[els.pos == p]["price"].min() for p in ["GK", "DEF", "MID", "FWD"]}
    forced = 2*floors["GK"] + 5*floors["DEF"] + 5*floors["MID"] + 3*floors["FWD"]
    print(f"\n2026-27 forced floor (2/5/5/3): £{forced:.1f}m -> discretionary £{100-forced:.1f}m")
    print(f"floors: GK £{floors['GK']}  DEF £{floors['DEF']}  MID £{floors['MID']}  FWD £{floors['FWD']}")

    print("\npremium landscape (players >= £9.0m), by position:")
    prem = els[els.price >= 9.0].sort_values("price", ascending=False)
    for p in ["FWD", "MID", "DEF", "GK"]:
        pp = prem[prem.pos == p]
        if len(pp):
            print(f"  {p}: " + ", ".join(f"{r.web_name} £{r.price}" for r in pp.head(6).itertuples()))
    print("\n(note: total_points/minutes columns on this file are LAST season's, for reference)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
