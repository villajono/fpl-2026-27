#!/usr/bin/env python3
"""structural.py — learn football relationships from real prior seasons.

Three seasons of real Premier League data (2022-23 to 2024-25, 83,835 player-gameweeks) share no
players with the season being played. They cannot predict Tzolis. What they CAN do is settle the
structural questions the model currently answers by argument, on data it has never seen.

QUESTION 1 — HOW FAR BACK SHOULD FORM LOOK?

`history.HALF_LIFE` is 20 appearances, marked PROVISIONAL, chosen because 8 was visibly too short
(one 2.57-xG match dragged a mid-tier forward to within 6% of Haaland). Nobody measured it. Too
short and the model chases noise; too long and it misses a genuine change in a player's role.

Measured directly: for each half-life, build a recency-weighted xG90/xA90 from a player's PAST
games only, use it to predict his NEXT gameweek's points, and see which weighting predicts best.
The decision-relevant statistic is the regression SLOPE of actual on predicted — how much of a
projected edge between two players is realised — not the correlation.

QUESTION 2 — DOES AN UPTICK IN xA PRECEDE AN UPTICK IN POINTS?

Jon's claim, and the reason it matters: if short-run underlying numbers LEAD scoring, then a player
with two good games is genuinely worth backing, and the model should not shrink him all the way to
his position average. If they do not lead, recent form is noise and the long-run rate is all there
is. That single answer decides how thin-sample players should be treated.

Tested by splitting each player's history into a recent window and a prior baseline, then asking
whether the CHANGE between them predicts the change in points that follows — over and above his
long-run rate. Anything else measures "good players score more", which we already know.

    python scripts/structural.py                # both questions
    python scripts/structural.py --halflife     # just the form window
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

DATA = "data/raw/history/merged_all.csv"
MIN_MINS = 60          # an appearance; rates over cameos are noise about substitution timing
MIN_PRIOR = 6          # games of history before a player is predictable at all


def load():
    d = pd.read_csv(DATA, low_memory=False)
    for c in ("minutes", "total_points", "expected_goals", "expected_assists", "GW"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    d = d[d.position.isin(["GK", "DEF", "MID", "FWD"])]
    d["pid"] = d["name"].astype(str) + "|" + d["season"].astype(str)
    return d.sort_values(["pid", "GW"])


def _series(d, appearances_only):
    """Per player-season, in gameweek order.

    appearances_only=True keeps only 60+ minute games — that was the ORIGINAL behaviour and it is
    survivorship: a player who collapses and is dropped has no future appearance, so he leaves the
    sample, and the sample is then made of players whose decline did not cost them their place.
    That single filter turned a real +0.151 form signal into +0.009 (see notes/FOOTBALL_RULES.md).

    appearances_only=False keeps every gameweek, scoring a non-appearance as zero points. That is
    what a manager actually banks and is the decision-relevant target.
    """
    out = {}
    for pid, g in d.groupby("pid", sort=False):
        if (g.minutes >= MIN_MINS).sum() < MIN_PRIOR + 1:
            continue
        if appearances_only:
            g = g[g.minutes >= MIN_MINS]
        out[pid] = dict(xg=g.expected_goals.to_numpy(float),
                        xa=g.expected_assists.to_numpy(float),
                        pts=g.total_points.to_numpy(float),
                        mins=g.minutes.to_numpy(float))
    return out


def _slope(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 50 or x.std() < 1e-9:
        return float("nan"), float("nan"), len(x)
    b = np.cov(x, y, bias=True)[0, 1] / x.var()
    return float(b), float(np.corrcoef(x, y)[0, 1]), len(x)


def halflife(series, label, lives=(2, 4, 6, 8, 12, 16, 20, 30, 45, 1e6)):
    """Which recency weighting on PAST xG/xA best predicts the next gameweek?"""
    print("")
    print(f"{label}")
    print(f"  {'half-life':>10}{'n':>9}{'slope':>9}{'corr':>8}")
    best = None
    for h in lives:
        px, py = [], []
        for s_ in series.values():
            xg, xa, pts, mins = s_["xg"], s_["xa"], s_["pts"], s_["mins"]
            for t in range(MIN_PRIOR, len(pts)):
                ago = np.arange(t, 0, -1, dtype=float)          # 1 = most recent
                w = np.power(0.5, ago / h) if h < 1e5 else np.ones(t)
                den = (w * mins[:t] / 90.0).sum()
                if den <= 0:
                    continue
                px.append((w * (xg[:t] * 4 + xa[:t] * 3)).sum() / den)
                py.append(pts[t])
        b, r, n = _slope(px, py)
        lab = "flat" if h > 1e5 else f"{h:g}"
        print(f"  {lab:>10}{n:>9,}{b:>9.3f}{r:>8.3f}")
        if not np.isnan(r) and (best is None or r > best[1]):
            best = (h, r, b)
    if best:
        nm = "a flat average" if best[0] > 1e5 else f"{best[0]:g} appearances"
        print(f"  -> best: {nm} (corr {best[1]:.3f})")
    return best


def leading(series, recent=4, base=8, ahead=4):
    """Does a CHANGE in recent xA/xG lead a change in points, beyond the long-run rate?"""
    print(f"\nQUESTION 2 — does an uptick in underlying numbers precede one in points?")
    print(f"  recent window {recent} games vs the {base} before it; outcome = next {ahead} games")
    rows = []
    for s in series.values():
        xg, xa, pts, mins = s["xg"], s["xa"], s["pts"], s["mins"]
        n = len(pts)
        for t in range(base + recent, n - ahead):
            r0, r1 = t - recent, t
            b0, b1 = t - recent - base, t - recent
            mr, mb = mins[r0:r1].sum() / 90.0, mins[b0:b1].sum() / 90.0
            if mr <= 0 or mb <= 0:
                continue
            xa_recent, xa_base = xa[r0:r1].sum() / mr, xa[b0:b1].sum() / mb
            xg_recent, xg_base = xg[r0:r1].sum() / mr, xg[b0:b1].sum() / mb
            long_run = pts[:t].mean()
            future = pts[t:t + ahead].mean()
            rows.append((xa_recent - xa_base, xg_recent - xg_base, long_run, future))
    if len(rows) < 200:
        print("  not enough player-windows to measure")
        return
    a = np.array(rows)
    d_xa, d_xg, long_run, future = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    resid = future - (np.polyval(np.polyfit(long_run, future, 1), long_run))
    print(f"  {len(rows):,} player-windows")
    print(f"  {'signal':<28}{'corr with next-4 pts':>22}{'corr with the part':>21}")
    print(f"  {'':28}{'':>22}{'his rate cannot explain':>24}")
    for lab, sig in (("change in xA per 90", d_xa), ("change in xG per 90", d_xg),
                     ("long-run points per game", long_run)):
        c_raw = np.corrcoef(sig, future)[0, 1]
        c_res = np.corrcoef(sig, resid)[0, 1]
        print(f"  {lab:<28}{c_raw:>22.3f}{c_res:>21.3f}")
    print("\n  The right-hand column is the one that matters: correlation with what remains after")
    print("  a player's long-run scoring rate is taken out. If it is near zero, recent form adds")
    print("  nothing you did not already know from his baseline, and shrinking a thin sample hard")
    print("  towards the position average is correct. If it is positive, form LEADS, and the model")
    print("  is throwing away signal every time it shrinks a player with a genuine uptick.")


def main():
    d = load()
    print("QUESTION 1 — how far back should form look?")
    print("  Run BOTH ways. The original ran only the first and its answer cannot be trusted:")
    print("  conditioning on the target being an appearance is the same survivorship flaw that")
    print("  broke rule B2, and it removes every player whose decline cost him his place.")

    s_app = _series(d, appearances_only=True)
    s_all = _series(d, appearances_only=False)
    print("")
    print(f"{len(s_app):,} player-seasons")

    a = halflife(s_app, "TARGET: next APPEARANCE's points  (survivorship — the original, unsound)")
    b = halflife(s_all, "TARGET: next GAMEWEEK's points, non-appearance = 0  (decision-relevant)")

    print("")
    print("VERDICT")
    if a and b:
        na = "flat" if a[0] > 1e5 else f"{a[0]:g}"
        nb = "flat" if b[0] > 1e5 else f"{b[0]:g}"
        print(f"    survivorship version picks {na}; sound version picks {nb}.")
        print(f"    history.HALF_LIFE is 20, set by argument and marked PROVISIONAL.")
        print("    The sound row is the one to set it from. If the curve is flat across a wide")
        print("    range, say so and leave 20 alone rather than tuning to a rounding error.")
    if "--leading" in sys.argv:
        leading(s_all)


if __name__ == "__main__":
    main()
