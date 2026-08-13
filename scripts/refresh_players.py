#!/usr/bin/env python3
"""refresh_players.py — keep the player universe current with the live FPL API.

data/raw/players_2026-27.csv carries two very different kinds of column:

  * IDENTITY / AVAILABILITY — club, price, status, ownership, news. These change constantly
    through a transfer window and must track the live API.
  * LAST SEASON'S PERFORMANCE — minutes, starts, xG, saves and the rest, merged in when the file
    was built. These are the model's prior and must NOT be touched; the bootstrap's same-named
    fields are THIS season's totals (zero in pre-season), so copying them over would wipe the prior.

Nothing refreshed the file, so it sat frozen at the day it was built while the tool fetched the API
daily for deadlines and results. By 2026-08-13 that meant ten players rated against the wrong
club's fixtures (Rushworth had moved Brighton -> Coventry, Bruno G. Newcastle -> Arsenal), wrong
counts against the 3-per-club limit, and 23 signings the engine could not see at all. It would only
get worse — the January window moves far more players than August.

Run before weekly.py. Writes the CSV in place, preserving its exact column order.
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

import fpl_fetch as F

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
CSV = RAW / "players_2026-27.csv"

# Only these come from the live API. Everything else is last season's prior and is left alone.
IDENTITY = ["id", "code", "web_name", "first_name", "second_name", "element_type", "team",
            "team_code", "now_cost", "status", "news", "news_added",
            "chance_of_playing_next_round", "chance_of_playing_this_round",
            "selected_by_percent", "can_transact", "can_select", "removed", "special",
            "squad_number", "photo"]
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def main() -> int:
    if not CSV.exists():
        print(f"FAIL: {CSV} not found"); return 1
    old = pd.read_csv(CSV, low_memory=False)
    cols = list(old.columns)
    old_by_code = {int(c): r for c, r in zip(old.code, old.to_dict("records")) if pd.notna(c)}

    boot = F.fetch_bootstrap()
    short = {t["id"]: t["short_name"] for t in boot["teams"]}

    rows, moved, added = [], [], []
    for el in boot["elements"]:
        code = int(el["code"])
        prev = old_by_code.get(code)
        row = dict(prev) if prev else {c: 0 for c in cols}      # keep last season's prior intact
        if prev is None:
            added.append(el["web_name"])
        for k in IDENTITY:
            if k in cols and k in el:
                row[k] = el[k]
        # derived columns the CSV carries in addition to the raw API fields
        new_team = short.get(el["team"])
        if prev is not None and prev.get("team_name") not in (None, new_team):
            moved.append((el["web_name"], prev.get("team_name"), new_team))
        row["team_name"] = new_team
        row["pos"] = POS.get(int(el["element_type"]))
        row["price"] = el["now_cost"] / 10.0
        rows.append({c: row.get(c) for c in cols})              # preserve exact column order

    new = pd.DataFrame(rows, columns=cols)
    dropped = [old_by_code[c]["web_name"] for c in old_by_code
               if c not in {int(e["code"]) for e in boot["elements"]}]

    new.to_csv(CSV, index=False)
    print(f"players_2026-27.csv refreshed: {len(old)} -> {len(new)} players")
    if moved:
        print(f"  changed club ({len(moved)}):")
        for nm, a, b in moved: print(f"    {nm:<18} {a} -> {b}")
    if added:
        print(f"  new to the game ({len(added)}): {', '.join(added[:12])}"
              + (" ..." if len(added) > 12 else ""))
    if dropped:
        print(f"  no longer listed ({len(dropped)}): {', '.join(dropped[:12])}"
              + (" ..." if len(dropped) > 12 else ""))
    if not (moved or added or dropped):
        print("  no squad changes since the last refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
