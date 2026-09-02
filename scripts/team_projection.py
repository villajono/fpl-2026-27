#!/usr/bin/env python3
"""team_projection.py — market season-points projections -> team attack/defence ratings.

THE PROBLEM THIS SOLVES
Bookmaker odds are the best fixture input we have, but they only exist for the next few days.
A six-week transfer horizon is priced by the xG model instead, whose team ratings are a Bayesian
update over games played — and after two gameweeks that update is violent: Coventry's defensive
weakness moved 1.40 -> 1.20 on two matches, at 29% weight, which then scales every attacking
return in every fixture six weeks out.

A season-long points projection is the market's view of a team over 38 games. It does not lurch
on one result, and it is forward-looking in a way a two-game average cannot be. So:

    ppg_remaining = (projected_final_points - points_earned) / games_remaining

That is one number per team. The model needs two — attacking strength and defensive weakness —
so PPG is mapped onto goals through a relationship fitted on last season's final table, where it
is strong in both directions:

    GF/game = a * ppg + b     r ~ +0.91
    GA/game = c * ppg + d     r ~ -0.90

Coefficients are refitted at runtime from league_table_2025-26.csv rather than hardcoded.

    python team_projection.py --template   # write a season_points.json to fill in
    python team_projection.py              # show the derived ratings
    python team_projection.py --write      # write ratings for fixture_ratings to pick up

INPUT: data/state/season_points.json — {"MCI": 84, "ARS": 80, ...} projected FINAL league points.
Sporting Index quote a season points spread per team; the mid of the buy/sell is the projection.
Absent, nothing happens and the xG ratings stand.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, STATE = ROOT / "data" / "raw", ROOT / "data" / "state"
SRC = STATE / "season_points.json"
OUT = STATE / "team_ratings_market.json"
API = "https://fantasy.premierleague.com/api/"


def _get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fit_ppg_to_goals():
    """GF/game and GA/game as linear functions of points per game, from last season's table."""
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    ppg = lt.PTS / lt.MP
    gf, ga = lt.GF / lt.MP, lt.GA / lt.MP
    (a, b) = np.polyfit(ppg, gf, 1)
    (c, d) = np.polyfit(ppg, ga, 1)
    return dict(gf=(float(a), float(b)), ga=(float(c), float(d)),
                r_gf=float(np.corrcoef(ppg, gf)[0, 1]), r_ga=float(np.corrcoef(ppg, ga)[0, 1]),
                lg_gf=float(gf.mean()), lg_ga=float(ga.mean()))


def standings():
    """Points earned and games played so far, from finished fixtures — the FPL API's own teams
    endpoint reports played=0 and points=0 all season, so it cannot be used for this."""
    b = _get("bootstrap-static/")
    short = {t["id"]: t["short_name"] for t in b["teams"]}
    pts = {s: 0 for s in short.values()}
    played = {s: 0 for s in short.values()}
    for f in _get("fixtures/"):
        if not f.get("finished"):
            continue
        h, a = short.get(f["team_h"]), short.get(f["team_a"])
        hg, ag = f.get("team_h_score"), f.get("team_a_score")
        if h is None or a is None or hg is None or ag is None:
            continue
        played[h] += 1; played[a] += 1
        if hg > ag: pts[h] += 3
        elif ag > hg: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    return pts, played


def home_away_split():
    """Actual home advantage in last season's data, to sanity-check the model's flat 1.05/0.95."""
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    g["expected_goals"] = pd.to_numeric(g["expected_goals"], errors="coerce").fillna(0)
    tm = g.groupby(["team", "GW", "was_home"], as_index=False).expected_goals.sum()
    h = tm[tm.was_home].expected_goals.mean(); a = tm[~tm.was_home].expected_goals.mean()
    return float(h), float(a), float(h / a) if a else 1.0


def derive():
    if not SRC.exists():
        return None
    proj = json.load(open(SRC, encoding="utf-8"))
    proj = {k: float(v) for k, v in proj.items() if not k.startswith("_")}
    fit = fit_ppg_to_goals()
    pts, played = standings()
    rows = {}
    for team, final_pts in proj.items():
        p, mp = pts.get(team, 0), played.get(team, 0)
        left = max(1, 38 - mp)
        ppg = max(0.0, (final_pts - p) / left)
        gf = fit["gf"][0] * ppg + fit["gf"][1]
        ga = fit["ga"][0] * ppg + fit["ga"][1]
        rows[team] = dict(proj=final_pts, earned=p, played=mp, ppg_rem=ppg,
                          gf=max(0.2, gf), ga=max(0.2, ga))
    # normalise so the league averages 1.0 — att>1 is a strong attack, defw>1 is a leaky defence
    mgf = np.mean([r["gf"] for r in rows.values()])
    mga = np.mean([r["ga"] for r in rows.values()])
    for r in rows.values():
        r["att"] = r["gf"] / mgf
        r["defw"] = r["ga"] / mga
    return rows, fit


def template():
    b = _get("bootstrap-static/")
    teams = sorted(t["short_name"] for t in b["teams"])
    d = {"_README": "Projected FINAL league points per team. Sporting Index quote a season points "
                    "spread; use the mid of buy/sell. Re-paste whenever the market moves materially.",
         "_source": "sportingindex.com", "_updated": ""}
    d.update({t: 52 for t in teams})
    SRC.parent.mkdir(parents=True, exist_ok=True)
    json.dump(d, open(SRC, "w", encoding="utf-8"), indent=2)
    print(f"wrote {SRC.relative_to(ROOT)} — fill in the numbers, then re-run without --template")


def main():
    if "--template" in sys.argv:
        return template()
    fit = fit_ppg_to_goals()
    h, a, ratio = home_away_split()
    print(f"PPG -> goals, fitted on 2025-26:")
    print(f"   GF/game = {fit['gf'][0]:+.4f} * ppg {fit['gf'][1]:+.4f}   r {fit['r_gf']:+.3f}")
    print(f"   GA/game = {fit['ga'][0]:+.4f} * ppg {fit['ga'][1]:+.4f}   r {fit['r_ga']:+.3f}")
    print(f"\nhome advantage in the same data: {h:.3f} xG at home vs {a:.3f} away, ratio {ratio:.3f}")
    print(f"   the model applies a flat 1.05 / 0.95 (ratio 1.105) — "
          f"{'consistent' if abs(ratio - 1.105) < 0.06 else 'WORTH REVISITING'}")

    out = derive()
    if out is None:
        print(f"\nno {SRC.relative_to(ROOT)} yet — run with --template to create one.")
        print("Until then the xG-model team ratings stand and nothing changes.")
        return
    rows, _ = out
    print(f"\n{'team':<6}{'proj':>6}{'earned':>8}{'pl':>4}{'ppg_rem':>9}{'att':>7}{'defw':>7}")
    for t, r in sorted(rows.items(), key=lambda x: -x[1]["ppg_rem"]):
        print(f"{t:<6}{r['proj']:>6.0f}{r['earned']:>8}{r['played']:>4}"
              f"{r['ppg_rem']:>9.2f}{r['att']:>7.2f}{r['defw']:>7.2f}")
    if "--write" in sys.argv:
        json.dump({t: {"att": r["att"], "defw": r["defw"]} for t, r in rows.items()},
                  open(OUT, "w", encoding="utf-8"), indent=2)
        print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
