#!/usr/bin/env python3
"""
fpl_fetch.py — live data ingestion for the weekly tool. Single source: the official FPL API,
which now carries xG/xA/defensive_contribution natively (no Understat/FBref scraping needed).

  bootstrap-static/      -> player universe, availability, season yellow totals, cumulative stats
  event/{gw}/live/       -> per-player stats for a completed gameweek (minutes, points, goals,
                            assists, CS, bonus, saves, yellows, expected_goals, expected_assists,
                            defensive_contribution)

Everything is keyed by the FPL `code` (stable across seasons), which is how our models identify
players. This is the single integration that unblocks autonomous weekly operation.
"""
from __future__ import annotations
import json, time, urllib.request, urllib.error
import pandas as pd

BASE = "https://fantasy.premierleague.com/api/"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
_UA = {"User-Agent": "Mozilla/5.0 (weekly-fpl-tool)"}


def _get(path, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE + path, headers=_UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            if i == retries - 1: raise
            time.sleep(2 * (i + 1))


def fetch_bootstrap():
    return _get("bootstrap-static/")


def season_state(bootstrap=None):
    """Which gameweeks are finished / current / next — drives the weekly loop."""
    b = bootstrap or fetch_bootstrap()
    return dict(finished=[e["id"] for e in b["events"] if e["finished"]],
                current=next((e["id"] for e in b["events"] if e["is_current"]), None),
                next=next((e["id"] for e in b["events"] if e["is_next"]), None),
                bootstrap=b)


def fetch_gw_data(completed_gw, bootstrap=None):
    """Per-player stats for one completed gameweek + current availability, keyed by FPL code.
    Returns (gw_df, availability_dict). Raises if the GW isn't finished (no stale reads)."""
    b = bootstrap or fetch_bootstrap()
    ev = next((e for e in b["events"] if e["id"] == completed_gw), None)
    if ev is None or not ev["finished"]:
        raise RuntimeError(f"GW{completed_gw} not finished — refusing to ingest incomplete data")
    id2code = {e["id"]: e["code"] for e in b["elements"]}
    id2pos = {e["id"]: POS[e["element_type"]] for e in b["elements"]}
    # Who each player faced, and where. Without this the rolling store records that a man
    # generated 1.76 xG but not that it was at home to Ipswich, so fixture ease gets baked into
    # his per-90 rate and then multiplied AGAIN by the next fixture's difficulty.
    id2team = {e["id"]: e["team"] for e in b["elements"]}
    short = {t["id"]: t["short_name"] for t in b["teams"]}
    opp_of, home_of = {}, {}
    for f in _get(f"fixtures/?event={completed_gw}"):
        opp_of[f["team_h"]] = short.get(f["team_a"]); home_of[f["team_h"]] = True
        opp_of[f["team_a"]] = short.get(f["team_h"]); home_of[f["team_a"]] = False
    live = _get(f"event/{completed_gw}/live/")
    rows = []
    for el in live["elements"]:
        s = el["stats"]
        _t = id2team.get(el["id"])
        rows.append(dict(opp=opp_of.get(_t), home=home_of.get(_t),
                         code=id2code.get(el["id"]), gw=completed_gw, pos=id2pos.get(el["id"]),
                         minutes=s.get("minutes", 0), total_points=s.get("total_points", 0),
                         goals=s.get("goals_scored", 0), assists=s.get("assists", 0),
                         clean_sheet=s.get("clean_sheets", 0), bonus=s.get("bonus", 0),
                         saves=s.get("saves", 0), yellow=s.get("yellow_cards", 0),
                         xG=float(s.get("expected_goals", 0) or 0), xA=float(s.get("expected_assists", 0) or 0),
                         dc=int(s.get("defensive_contribution", 0) or 0)))
    gw_df = pd.DataFrame(rows)
    avail = {e["code"]: dict(status=e["status"], news=e["news"],
                             chance=e["chance_of_playing_next_round"], yc_season=e["yellow_cards"],
                             web_name=e["web_name"]) for e in b["elements"]}
    return gw_df, avail


def team_xg_for_gw(gw_df, bootstrap):
    """Aggregate per-player xG to team xG scored/conceded for the Bayesian team update (1c)."""
    id2team = {e["code"]: e["team"] for e in bootstrap["elements"]}
    teamname = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    gw_df = gw_df.assign(team=gw_df.code.map(id2team))
    scored = gw_df.groupby("team").xG.sum()
    # conceded requires the fixture map (opponent's scored) — supplied by caller with fixtures
    return {teamname.get(t): float(v) for t, v in scored.items()}


if __name__ == "__main__":
    st = season_state()
    print(f"season_state: {len(st['finished'])} finished, current={st['current']}, next={st['next']}")
    print(f"bootstrap elements: {len(st['bootstrap']['elements'])}")
    if st["finished"]:
        df, av = fetch_gw_data(st["finished"][-1], st["bootstrap"])
        print(f"latest completed GW{st['finished'][-1]}: {len(df)} player rows, "
              f"xG present sum={df.xG.sum():.1f}, DC present sum={df.dc.sum()}")
    else:
        print("no completed gameweeks yet (pre-season) — fetch_gw_data ready for GW1 on 2026-08-21")
