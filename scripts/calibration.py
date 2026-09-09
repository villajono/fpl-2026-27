#!/usr/bin/env python3
"""calibration.py — did last week's locked forecast come true?

WHY THIS RUNS EVERY WEEK RATHER THAN WHEN SOMEBODY REMEMBERS

The model's projections have been doubted, correctly, more than once, and every check we ran was
against the season the rates were FIT on — which is marking your own homework. The only honest
test is comparing a projection made BEFORE a gameweek against what actually happened in it.

That was impossible until forecast.py started locking dated files, because nothing recorded what
the model had believed at the time. Now every lock is a permanent, timestamped prediction, and
this compares it with the outcome. The record accumulates over the season on its own.

WHAT TO LOOK AT, AND WHAT NOT TO

  OVERALL BIAS is the least interesting number. If every player is inflated by the same amount,
  the RANKING is unchanged and so is the squad — it distorts only decisions that use absolute
  points: chip thresholds, hit-or-bank, the wildcard bar.

  BIAS BY POSITION is what corrupts team selection. If defenders are over-predicted relative to
  forwards, the optimiser will build defender-heavy squads for a reason that has nothing to do
  with football. That is the number to watch, and the spread between positions matters more than
  any single row.

Only players the forecast expected to start are scored (p60 >= 0.5). Including everyone measures
the minutes model, which is a separate question and drowns the scoring signal.

    python scripts/calibration.py          # standalone
    (weekly.py calls report_lines() so it prints in the weekly report too)
"""
from __future__ import annotations

import glob
import json
import pathlib
import re

import history as H

STATE = pathlib.Path("data/processed")
P60_FLOOR = 0.5


def _locked():
    out = {}
    for f in glob.glob(str(STATE / "forecast_gw*.json")):
        m = re.search(r"forecast_gw(\d+)\.json", f)
        if m:
            out[int(m.group(1))] = f
    return out


def measure():
    """For each locked forecast, score its FIRST gameweek against the actual result."""
    locks = _locked()
    if not locks:
        return []
    try:
        act = H.load_inseason()
    except Exception:
        return []
    rows = []
    for gw0, path in sorted(locks.items()):
        played = act[act.gw == gw0]
        if played.empty:
            continue                                   # gameweek not played yet
        pts = dict(zip(played.code, played.total_points))
        mins = dict(zip(played.code, played.minutes))
        fc = json.load(open(path, encoding="utf-8"))
        for k, v in fc["players"].items():
            if v["p60"] < P60_FLOOR:
                continue
            c = v["code"]
            if c not in pts:
                continue
            rows.append(dict(gw=gw0, pos=v["pos"], name=k.split("|")[0],
                             pred=v["ev"][0], actual=float(pts[c]),
                             minutes=float(mins.get(c, 0)), confidence=v["confidence"]))
    return rows


def report_lines():
    rows = measure()
    L = ["\nFORECAST ACCURACY (locked predictions vs what happened)\n" + "━" * 30]
    if not rows:
        locks = sorted(_locked())
        if locks:
            L.append(f"  {len(locks)} forecast(s) locked (GW{', GW'.join(map(str, locks))}), none")
            L.append("  of them played yet. First accuracy read lands once one completes.")
        else:
            L.append("  No locked forecasts yet — run scripts/forecast.py to start the record.")
        return L
    n = len(rows)
    bias = sum(r["actual"] - r["pred"] for r in rows) / n
    mae = sum(abs(r["actual"] - r["pred"]) for r in rows) / n
    L.append(f"  {n} expected starters across {len({r['gw'] for r in rows})} gameweek(s)")
    L.append(f"  overall bias {bias:+.2f} pts/player  (negative = model over-predicts) · MAE {mae:.2f}")
    L.append(f"  {'pos':<6}{'n':>5}{'predicted':>11}{'actual':>9}{'bias':>8}")
    by = {}
    for r in rows:
        by.setdefault(r["pos"], []).append(r)
    spread = []
    for pos in ("GK", "DEF", "MID", "FWD"):
        g = by.get(pos)
        if not g:
            continue
        p = sum(x["pred"] for x in g) / len(g)
        a = sum(x["actual"] for x in g) / len(g)
        spread.append(a - p)
        L.append(f"  {pos:<6}{len(g):>5}{p:>11.2f}{a:>9.2f}{a - p:>+8.2f}")
    if len(spread) > 1:
        sp = max(spread) - min(spread)
        L.append(f"  spread between positions: {sp:.2f} pts")
        if sp > 0.5:
            L.append("  ** That is the number that corrupts SELECTION. A uniform bias leaves the")
            L.append("  ** ranking intact; a positional one makes the optimiser prefer a position")
            L.append("  ** for reasons that are not football. Investigate before trusting a build.")
        else:
            L.append("  Positions are biased consistently, so the ranking — and the squad — stands.")
    return L


if __name__ == "__main__":
    for line in report_lines():
        print(line)
