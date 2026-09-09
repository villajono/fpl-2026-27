#!/usr/bin/env python3
"""theories.py — stated football theories, tested against three real prior seasons.

THE SPLIT THIS IS ORGANISED AROUND

Jon's framing, and it is the right primary structure: a player's expected score is

    E[points]  =  E[minutes]  x  E[points per 90]

and those two halves have almost nothing in common. Minutes are decided by a manager — selection,
discipline, rotation, injury. Points per 90 is decided by ability and opposition. Mixing them is
how "he had a good week" ends up moving both, when a good week is evidence about one and nearly
silent about the other.

So the theories are written in two groups, each stated plainly enough to be wrong. Every test
reports a verdict and what it implies for the model. A REJECTED theory is as valuable as a
supported one — more so, if the model currently assumes it.

Data: 83,835 player-gameweeks, 2022-23 to 2024-25, real Premier League, sharing no players with
the season being played. See fetch_history.py for why that is the point rather than a limitation.

    python scripts/theories.py
    python scripts/theories.py --minutes     # just the minutes group
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

DATA = "data/raw/history/merged_all.csv"
APP = 60


def load():
    d = pd.read_csv(DATA, low_memory=False)
    num = ["minutes", "total_points", "expected_goals", "expected_assists", "GW",
           "red_cards", "yellow_cards", "goals_scored", "assists", "goals_conceded",
           "expected_goals_conceded", "bps", "bonus"]
    for c in num:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    d = d[d.position.isin(["GK", "DEF", "MID", "FWD"])].copy()
    d["pid"] = d["name"].astype(str) + "|" + d["season"].astype(str)
    d["tid"] = d["team"].astype(str) + "|" + d["season"].astype(str)
    return d.sort_values(["pid", "GW"])


def verdict(ok, strong=None):
    if strong is not None and strong:
        return "SUPPORTED, strongly"
    return "SUPPORTED" if ok else "REJECTED"


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 100 or a[m].std() < 1e-9 or b[m].std() < 1e-9:
        return float("nan"), int(m.sum())
    return float(np.corrcoef(a[m], b[m])[0, 1]), int(m.sum())


# ============================================================== MINUTES
def m1_red_card(d):
    print("\nM1. A red card collapses the next match's minutes.")
    print("    Mechanical — a ban is at least one game — so this is a sanity check on the data")
    print("    as much as a theory. If it does not show, nothing else here can be trusted.")
    nxt = d.groupby("pid").minutes.shift(-1)
    red = d.red_cards > 0
    played = d.minutes >= APP
    a = d.loc[red & played, "minutes"].index
    after_red = nxt.loc[a].dropna()
    base = nxt.loc[(~red) & played].dropna()
    print(f"    minutes in the NEXT match after a red card: {after_red.mean():.1f} "
          f"(n={len(after_red)})")
    print(f"    after any other appearance:                 {base.mean():.1f} (n={len(base):,})")
    drop = 1 - after_red.mean() / max(base.mean(), 1e-9)
    print(f"    -> {drop:.0%} reduction.  {verdict(drop > 0.4, drop > 0.7)}")
    print("    MODEL: a red card should force p60 towards zero for the following gameweek.")
    print("    Currently nothing in the pipeline reads red_cards for the NEXT week's minutes.")


def m2_output_drives_minutes(d):
    print("\nM2. Attackers who stop producing get dropped: a fall in xG+xA leads a fall in minutes.")
    print("    If true, attacking output is a LEADING indicator of minutes, and the minutes model")
    print("    should read it. If false, minutes must be forecast from minutes alone.")
    att = d[d.position.isin(["MID", "FWD"])]
    rows = []
    for _pid, g in att.groupby("pid", sort=False):
        mins = g.minutes.to_numpy(float)
        xgi = (g.expected_goals + g.expected_assists).to_numpy(float)
        if len(mins) < 14:
            continue
        for t in range(8, len(mins) - 4):
            m_recent = mins[t - 4:t].sum() / 90.0
            m_base = mins[t - 8:t - 4].sum() / 90.0
            if m_recent <= 0 or m_base <= 0:
                continue
            d_xgi = xgi[t - 4:t].sum() / m_recent - xgi[t - 8:t - 4].sum() / m_base
            future_mins = mins[t:t + 4].mean()
            prior_mins = mins[t - 4:t].mean()
            rows.append((d_xgi, future_mins, prior_mins))
    a = np.array(rows)
    c_raw, n = corr(a[:, 0], a[:, 1])
    # what matters is signal BEYOND how much he has been playing lately
    resid = a[:, 1] - np.polyval(np.polyfit(a[:, 2], a[:, 1], 1), a[:, 2])
    c_res, _ = corr(a[:, 0], resid)
    print(f"    {n:,} windows.  change in xG+xA per 90 vs next-4 minutes: corr {c_raw:+.3f}")
    print(f"    vs the part recent minutes cannot explain:                corr {c_res:+.3f}")
    print(f"    -> {verdict(abs(c_res) > 0.05)}")
    print("    MODEL: if rejected, do not let scoring form move p60. Minutes predict minutes.")


def m3_big_club_volatility(d):
    print("\nM3. Minutes at the strongest clubs are more volatile (rotation).")
    print("    Tested by squad strength, since European commitments and squad depth travel")
    print("    together. If true, p60 for a player at a top club needs a wider band.")
    tp = d.groupby("tid").total_points.sum().sort_values(ascending=False)
    top = set(tp.head(18).index)          # ~6 clubs x 3 seasons
    reg = d[d.minutes > 0].groupby(["pid", "tid"]).minutes.agg(["mean", "std", "count"])
    reg = reg[reg["count"] >= 10].reset_index()
    reg["cv"] = reg["std"] / reg["mean"].clip(lower=1)
    a = reg[reg.tid.isin(top)]["cv"]
    b = reg[~reg.tid.isin(top)]["cv"]
    print(f"    minutes coefficient of variation, top clubs:   {a.mean():.3f} (n={len(a)})")
    print(f"    everyone else:                                 {b.mean():.3f} (n={len(b)})")
    diff = a.mean() - b.mean()
    print(f"    -> difference {diff:+.3f}.  {verdict(diff > 0.02)}")
    print("    MODEL: if supported, p60 uncertainty should scale with club strength.")


# ============================================================== POINTS PER 90
def p1_opposition(d):
    print("\nP1. Points per 90 improve against weak opposition.")
    print("    The obvious one, and worth measuring rather than assuming: it sets the SIZE of")
    print("    the fixture multiplier, which the model applies to every projection it makes.")
    conc = d.groupby(["tid", "GW"]).goals_conceded.max().groupby(level=0).mean()
    team_of = d.groupby("tid").first().index
    season_of = {t: t.split("|")[1] for t in team_of}
    opp_key = d.team.astype(str) + "|" + d.season.astype(str)
    _ = opp_key, season_of
    # opponent_team is an id within a season; map it via each season's team list
    idmap = {}
    for season, g in d.groupby("season"):
        names = sorted(g.team.astype(str).unique())
        for i, nm in enumerate(names, start=1):
            idmap[(season, i)] = f"{nm}|{season}"
    d = d.copy()
    d["opp_tid"] = [idmap.get((s, int(o))) for s, o in zip(d.season, d.opponent_team)]
    d["opp_leak"] = d.opp_tid.map(conc)
    app = d[(d.minutes >= APP) & d.opp_leak.notna()].copy()
    app["p90"] = app.total_points / app.minutes * 90
    c, n = corr(app.opp_leak, app.p90)
    lo = app[app.opp_leak <= app.opp_leak.quantile(0.25)].p90.mean()
    hi = app[app.opp_leak >= app.opp_leak.quantile(0.75)].p90.mean()
    print(f"    {n:,} appearances.  corr(opponent goals conceded per game, points per 90) {c:+.3f}")
    print(f"    vs the meanest quarter of defences: {lo:.2f} pts/90")
    print(f"    vs the leakiest quarter:            {hi:.2f} pts/90   ({hi / lo - 1:+.0%})")
    print(f"    -> {verdict(hi > lo)}")
    print("    MODEL: that percentage is the honest size of the fixture effect on ATTACKERS.")


def p2_form_windows(d):
    print("\nP2. A strong week or two does NOT predict improvement; a longer view does.")
    print("    The counter-intuitive one. Tested by window length: does a player's recent")
    print("    points per 90 over the last k games predict his next 4, once his long-run rate")
    print("    is accounted for? If short windows add nothing, chasing form is a mistake.")
    print(f"    {'window':>8}{'n':>9}{'corr, raw':>12}{'corr, beyond his baseline':>28}")
    for k in (1, 2, 4, 6, 10):
        rows = []
        for _pid, g in d.groupby("pid", sort=False):
            mins = g.minutes.to_numpy(float)
            pts = g.total_points.to_numpy(float)
            ok = mins >= APP
            mins, pts = mins[ok], pts[ok]
            if len(pts) < k + 8:
                continue
            for t in range(max(k, 6), len(pts) - 4):
                mw = mins[t - k:t].sum() / 90.0
                if mw <= 0:
                    continue
                rows.append((pts[t - k:t].sum() / mw, pts[:t].mean(), pts[t:t + 4].mean()))
        a = np.array(rows)
        if len(a) < 200:
            continue
        c_raw, n = corr(a[:, 0], a[:, 2])
        resid = a[:, 2] - np.polyval(np.polyfit(a[:, 1], a[:, 2], 1), a[:, 1])
        c_res, _ = corr(a[:, 0], resid)
        print(f"    {k:>8}{n:>9,}{c_raw:>12.3f}{c_res:>28.3f}")
    print("    MODEL: the right-hand column is the only one that matters. If short windows sit")
    print("    near zero and longer ones do not, the long-run rate is the signal and recent form")
    print("    is noise — which makes shrinking a thin sample CORRECT rather than a bug.")


def main():
    d = load()
    print(f"  {len(d):,} player-gameweeks, {d.pid.nunique():,} player-seasons, "
          f"seasons {sorted(d.season.unique())}")
    if "--points" not in sys.argv:
        print("\n" + "=" * 74)
        print("GROUP A — MINUTES (who plays, and for how long)")
        print("=" * 74)
        m1_red_card(d)
        m2_output_drives_minutes(d)
        m3_big_club_volatility(d)
    if "--minutes" not in sys.argv:
        print("\n" + "=" * 74)
        print("GROUP B — POINTS PER 90 (how well he scores when he is on)")
        print("=" * 74)
        p1_opposition(d)
        p2_form_windows(d)


if __name__ == "__main__":
    main()
