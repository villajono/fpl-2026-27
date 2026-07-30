#!/usr/bin/env python3
"""
history.py — rolling per-90 history persistence. Each completed gameweek is fetched
(fpl_fetch) and appended to data/state/gw_history.csv (deduped). Per-90 rates are then
recomputed from the COMBINED history — prior season (dev data) + all ingested in-season
games — with recency weighting so recent games dominate:

    rate = Σ wᵢ·statᵢ / Σ wᵢ·(minᵢ/90),   wᵢ = 0.5^(games_ago / half_life)

Half-life: 8 games for form (xG/xA/saves, minutes) — moves quickly;
          20 games for DC/role — moves slowly. As in-season games accumulate they
outweigh the stale prior, so a transferred/reroled player self-corrects (Rogers, Mosquera).

ev_v2.get_per_90_rates delegates here once any in-season data exists; pre-season it keeps
the validated career-average path untouched.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

STATE = Path(__file__).resolve().parent.parent / "data" / "state"
STATE.mkdir(parents=True, exist_ok=True)
HIST = STATE / "gw_history.csv"
SEASON = "2026-27"
COLS = ["season", "gw", "code", "pos", "minutes", "xG", "xA", "dc", "saves", "goals",
        "assists", "total_points", "clean_sheet", "bonus", "yellow"]
HALF_LIFE = {"xG": 8, "xA": 8, "saves": 8, "dc": 20}   # form fast, role slow


def _write(df):
    df = df.reindex(columns=COLS)
    if HIST.exists():
        old = pd.read_csv(HIST)
        keep = old[~((old.season == SEASON) & (old.gw.isin(df.gw.unique())))]   # dedup: replace re-ingested GWs
        df = pd.concat([keep, df], ignore_index=True)
    df.sort_values(["season", "gw", "code"]).to_csv(HIST, index=False)


def ingest_gw(completed_gw, bootstrap=None):
    """Fetch a completed gameweek from the live FPL API and append to the rolling store."""
    import fpl_fetch as F
    gw_df, _avail = F.fetch_gw_data(completed_gw, bootstrap)
    gw_df["season"] = SEASON
    gw_df = gw_df.rename(columns={})
    _write(gw_df)
    return int((gw_df.minutes > 0).sum())


def ingest_mock(gw, rows):
    """Test hook: inject mock player rows (list of dicts) for a gameweek, no network."""
    df = pd.DataFrame(rows); df["season"] = SEASON; df["gw"] = gw
    _write(df)


def load_inseason():
    return pd.read_csv(HIST) if HIST.exists() else pd.DataFrame(columns=COLS)


def has_inseason():
    return HIST.exists() and len(load_inseason()) > 0


def inseason_codes():
    d = load_inseason(); return set(d.code.unique()) if len(d) else set()


def inseason_rows(code):
    d = load_inseason()
    if not len(d): return []
    sub = d[d.code == code].sort_values(["season", "gw"])
    return [dict(minutes=float(r.minutes), xG=float(r.xG), xA=float(r.xA),
                 dc=float(r.dc), saves=float(r.saves)) for r in sub.itertuples()]


def recency_weighted_rates(games, pos):
    """games: appearances oldest→newest, each a dict with minutes/xG/xA/dc/saves. Returns the
    per-90 rate dict ev_v2 expects, recency-weighted per field."""
    games = [g for g in games if g["minutes"] > 0]
    n = len(games)
    if n == 0:
        return dict(xG90=0.0, xA90=0.0, DC90=0.0, sv90=0.0, minutes=0, n60=0, pos=pos,
                    thin=True, dc_history=[], games=0)

    def rate(field):
        hl = HALF_LIFE[field]
        w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]
        num = sum(w[i] * games[i][field] for i in range(n))
        den = sum(w[i] * games[i]["minutes"] / 90.0 for i in range(n))
        return num / den if den > 0 else 0.0

    return dict(xG90=rate("xG"), xA90=rate("xA"), DC90=rate("dc"), sv90=rate("saves"),
                minutes=sum(g["minutes"] for g in games), n60=sum(1 for g in games if g["minutes"] >= 60),
                pos=pos, thin=False, dc_history=[g["dc"] for g in games], games=n)


def recency_start_prob(games, half_life=8):
    """P(60+ start) as a recency-weighted fraction of recent appearances. None if no history."""
    games = [g for g in games if "minutes" in g]
    n = len(games)
    if n == 0: return None
    w = [0.5 ** ((n - 1 - i) / half_life) for i in range(n)]
    started = [1.0 if g["minutes"] >= 60 else 0.0 for g in games]
    return sum(w[i] * started[i] for i in range(n)) / sum(w)


if __name__ == "__main__":
    d = load_inseason()
    print(f"gw_history: {len(d)} rows across GWs {sorted(d.gw.unique()) if len(d) else '[]'} "
          f"| in-season players: {len(inseason_codes())}")
