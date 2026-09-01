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
        "assists", "total_points", "clean_sheet", "bonus", "yellow", "opp", "home"]
# Half-life in APPEARANCES. The old setting was xG/xA/saves 8, dc 20 — "form fast, role slow" —
# which has it backwards for the noisy quantities. Defensive contributions run 4-6 a game with
# little spread; xG runs 0 to 2.6 and one shot from six yards is 0.7 of it. The noisier the
# per-game figure, the MORE smoothing it needs, not less.
#
# A half-life of 8 leaves ~12 effective games, and over 12 games a single freak match owns the
# estimate. Mbeumo posted 2.57 xG in one game late last season; that alone lifted his rate 41%
# above his actual season figure and brought him to within 6% of Haaland, whose flat rate is 1.88x
# his (0.777 v 0.413 — the 27-goals-to-10 gap you would expect). At 20 the ratio comes back to 1.42.
#
# PROVISIONAL: 20 is reasoned, not calibrated. backtest.py is the tool to settle it properly and
# this should be re-tuned against it rather than left on judgement.
HALF_LIFE = {"xG": 20, "xA": 20, "saves": 12, "dc": 20}


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
                 dc=float(r.dc), saves=float(r.saves),
                 opp=(getattr(r, "opp", None) if pd.notna(getattr(r, "opp", None)) else None),
                 home=(bool(getattr(r, "home", True)) if pd.notna(getattr(r, "home", None)) else None))
            for r in sub.itertuples()]


def recency_weighted_rates(games, pos, fixture_mult=None):
    """games: appearances oldest→newest, each a dict with minutes/xG/xA/dc/saves. Returns the
    per-90 rate dict ev_v2 expects, recency-weighted per field.

    fixture_mult(game) -> the attacking multiplier that applied in THAT game (opponent defensive
    weakness x home/away), or None where it is unknown. Attacking output is divided by it, so the
    stored rate means "per 90 against a league-average opponent" — which is the only thing
    compute_ev_v2 may legitimately multiply by the NEXT fixture's difficulty.

    Without this the same fixture ease is counted twice. Mbeumo generated 1.76 xG at home to
    Ipswich (defw 1.40 x home 1.05 = 1.47); the raw figure lifted his season xG90 from 0.413 to
    0.698, and the engine then applied 1.47 again for a future home game against Coventry. Over 35
    appearances opponents average out and it hardly matters; over the two games carrying 17% of the
    weight it decides who your captain is.

    Only games that carry an opponent are adjusted. Last season's rows are left alone deliberately:
    the ratings here are THIS season's, so dividing an old game by a current rating would swap one
    error for another — and with 35-odd games the fixtures already average out."""
    games = [g for g in games if g["minutes"] > 0]
    n = len(games)
    if n == 0:
        return dict(xG90=0.0, xA90=0.0, DC90=0.0, sv90=0.0, minutes=0, n60=0, pos=pos,
                    thin=True, dc_history=[], games=0)

    ADJUSTED = {"xG", "xA"}          # attacking output scales with the opponent; dc and saves do not

    def value(g, field):
        v = g[field]
        if field not in ADJUSTED or fixture_mult is None:
            return v
        m = fixture_mult(g)
        return v / m if m and m > 0.01 else v

    def rate(field):
        hl = HALF_LIFE[field]
        w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]
        num = sum(w[i] * value(games[i], field) for i in range(n))
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
