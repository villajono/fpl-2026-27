#!/usr/bin/env python3
"""fetch_history.py — pull real prior Premier League seasons for STRUCTURAL calibration.

WHAT THESE SEASONS ARE FOR, AND WHAT THEY ARE NOT FOR

They share no players or clubs with the season being played, so they cannot predict any individual.
That is not the point. What transfers is the FOOTBALL — relationships that hold across every
season and therefore apply to a player with two games of history:

    "a player who plays regularly and creates good xA does not get dropped, and an uptick in his
     match-by-match xA nearly always precedes an improvement in his FPL points"

That is learnable from thousands of player-seasons and applicable to Tzolis. Every structural
constant in this model — the form half-life, how xG converts to points, how fast team strength
should update, how much to shrink a thin sample — is currently set by ARGUMENT on a single season
that the model was partly calibrated on. These seasons make them measurable, on data the model has
never seen.

Source: github.com/vaastav/Fantasy-Premier-League, the standard public archive of FPL gameweek
data. xG and xA exist from 2022-23 onward, which sets the earliest useful season.

Schemas differ between seasons (2024-25 drops `starts`, column counts run 34-36), so everything is
normalised to the intersection plus a `season` label, and missing columns are recorded rather than
silently filled.

    python scripts/fetch_history.py
    python scripts/fetch_history.py --force     # re-download
"""
from __future__ import annotations

import io
import pathlib
import sys
import urllib.request

import pandas as pd

BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/"
SEASONS = ["2022-23", "2023-24", "2024-25"]
OUT = pathlib.Path("data/raw/history")

# The columns structural work needs. Anything absent in a season is reported, not filled.
WANT = ["name", "position", "team", "GW", "minutes", "starts", "total_points",
        "goals_scored", "assists", "clean_sheets", "goals_conceded", "saves", "bonus", "bps",
        "expected_goals", "expected_assists", "expected_goals_conceded",
        "yellow_cards", "red_cards", "influence", "creativity", "threat", "ict_index",
        "opponent_team", "was_home", "value", "selected", "element"]


def fetch(season):
    url = f"{BASE}{season}/gws/merged_gw.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    df["season"] = season
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    combined, report = [], []
    for s in SEASONS:
        f = OUT / f"merged_gw_{s}.csv"
        if f.exists() and "--force" not in sys.argv:
            df = pd.read_csv(f, low_memory=False)
            src = "cached"
        else:
            df = fetch(s)
            df.to_csv(f, index=False)
            src = "downloaded"
        missing = [c for c in WANT if c not in df.columns]
        keep = [c for c in WANT if c in df.columns] + ["season"]
        combined.append(df[keep])
        report.append((s, src, len(df), df.GW.nunique(), missing))

    print(f"  {'season':<10}{'source':<12}{'rows':>9}{'GWs':>6}   missing columns")
    for s, src, n, gws, missing in report:
        print(f"  {s:<10}{src:<12}{n:>9,}{gws:>6}   {missing if missing else '-'}")

    all_df = pd.concat(combined, ignore_index=True)
    dest = OUT / "merged_all.csv"
    all_df.to_csv(dest, index=False)
    print(f"\n  wrote {dest} — {len(all_df):,} player-gameweeks across {len(SEASONS)} seasons")

    n = pd.to_numeric(all_df.get("minutes"), errors="coerce").fillna(0)
    print(f"  of which {int((n >= 60).sum()):,} are appearances of 60+ minutes, which is the")
    print("  population any structural relationship should be fitted on — a rate computed over")
    print("  cameos is mostly noise about substitution timing.")
    print("\n  These seasons share no players with the current one. They are for calibrating")
    print("  RELATIONSHIPS — form half-life, xG-to-points conversion, how fast team strength")
    print("  should move — never for predicting an individual.")


if __name__ == "__main__":
    main()
