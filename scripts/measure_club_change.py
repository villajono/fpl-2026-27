#!/usr/bin/env python3
"""
measure_club_change.py - how much should last season count for a player who has changed club?

The per-90 recency blend (history.recency_weighted_rates, HALF_LIFE 20 appearances) treats last
season's games as the same player in the same role. For a club changer that premise fails: Rogers
had 37 Villa appearances against 4 Chelsea ones at GW5, so his rate was ~90% Villa.

Walk-forward test over three season pairs (2022-23 -> 2023-24, 23-24 -> 24-25, 24-25 -> 25-26).
For each outfield player with prior-season appearances, at checkpoint k (after his first k
appearances of the new season), build the rate exactly as production does but with prior-season
games multiplied by a discount d, and variants that rescale prior attacking output by
new-club / old-club attacking strength (team xG per game LAST season, which is what is known in
real time). Target: his per-90 over his next 10 appearances.

Conditioning: the target needs future appearances (>= 300 minutes). That is right for a RATE model
- ev_v2 multiplies the rate by P(minutes) separately - but it means this says nothing about minutes.
Club change = last-season final club differs from new-season club, with no switch inside the
window (mid-season movers dropped). Promoted new clubs have no last-season Premier League xG, so
the rescaling variant falls back to unscaled for them.
"""
from pathlib import Path
import numpy as np, pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
FILES = {"2022-23": RAW / "history/merged_gw_2022-23.csv", "2023-24": RAW / "history/merged_gw_2023-24.csv",
         "2024-25": RAW / "history/merged_gw_2024-25.csv", "2025-26": RAW / "merged_gw_2025-26.csv"}
HL = 20
CHECKPOINTS = (2, 4, 6, 8, 10)
TARGET_APPS, TARGET_MIN = 10, 300


def load(season):
    d = pd.read_csv(FILES[season], low_memory=False)
    gw = "GW" if "GW" in d else "round"
    for c in ("minutes", "expected_goals", "expected_assists", "defensive_contribution"):
        d[c] = pd.to_numeric(d[c], errors="coerce") if c in d else np.nan
    if season == "2022-23":                      # FPL only published xG from GW16
        d = d[d[gw] >= 16]
    d = d[d.minutes > 0].copy()
    d["gw"] = d[gw]; d["season"] = season
    d["xgi"] = d.expected_goals.fillna(0) + d.expected_assists.fillna(0)
    d["pos"] = d.position.replace({"GKP": "GK", "AM": "MID"})
    return d.sort_values(["gw", "kickoff_time"] if "kickoff_time" in d else ["gw"])


def team_att(d):
    per_fix = d.groupby(["gw", "team"]).expected_goals.sum().groupby("team").mean()
    return per_fix / per_fix.mean()


def blend(prior, cur, field, d, scale=1.0):
    rows = [(v * scale, m, d) for v, m in zip(prior[field], prior.minutes)] + \
           [(v, m, 1.0) for v, m in zip(cur[field], cur.minutes)]
    n = len(rows)
    w = [0.5 ** ((n - 1 - i) / HL) * rows[i][2] for i in range(n)]
    den = sum(w[i] * rows[i][1] / 90 for i in range(n))
    return sum(w[i] * rows[i][0] for i in range(n)) / den if den else np.nan


recs = []
seasons = list(FILES)
data = {s: load(s) for s in seasons}
for s0, s1 in zip(seasons, seasons[1:]):
    a, b = data[s0], data[s1]
    att0 = team_att(a)
    for name, cur_all in b.groupby("name"):
        prior = a[a.name == name]
        if len(prior) < 5: continue
        pos = cur_all.pos.iloc[0]
        if pos == "GK" or prior.pos.iloc[-1] != pos: continue
        old, new = prior.team.iloc[-1], cur_all.team.iloc[0]
        for k in CHECKPOINTS:
            cur, fut = cur_all.iloc[:k], cur_all.iloc[k:k + TARGET_APPS]
            if len(cur) < k or fut.minutes.sum() < TARGET_MIN: continue
            if pd.concat([cur, fut]).team.nunique() > 1: continue
            scale = (att0[new] / att0[old]) if (new in att0 and old in att0) else 1.0
            r = dict(season=s1, name=name, pos=pos, k=k, changer=old != new, promoted=new not in att0,
                     scale=scale, fut_min=fut.minutes.sum(),
                     y_xgi=fut.xgi.sum() * 90 / fut.minutes.sum(),
                     y_dc=(fut.defensive_contribution.sum() * 90 / fut.minutes.sum()) if fut.defensive_contribution.notna().all() else np.nan)
            for dd in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
                r[f"xgi_{dd}"] = blend(prior, cur, "xgi", dd)
                r[f"xgis_{dd}"] = blend(prior, cur, "xgi", dd, scale)
            for al in (0.25, 0.5, 0.75):
                r[f"xgia_{al}"] = blend(prior, cur, "xgi", 1.0, scale ** al)
            recs.append(r)

R = pd.DataFrame(recs)
DS = (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0)


def wmse(df, col, y):
    ok = df[col].notna() & df[y].notna()
    return np.average((df.loc[ok, col] - df.loc[ok, y]) ** 2, weights=df.loc[ok, "fut_min"])


def table(df, label, y, pref):
    out = {dd: wmse(df, f"{pref}_{dd}", y) for dd in DS}
    base = out[1.0]
    best = min(out, key=out.get)
    print(f"  {label:34s} n={len(df):4d} | " + " ".join(f"{dd}:{v / base:5.3f}" for dd, v in out.items()) + f" | best d={best}")


pd.set_option("display.width", 200)
print(f"player-checkpoints: {len(R)}  changers: {R.changer.sum()} ({R[R.changer].name.nunique()} players)")
print("\nMSE relative to production (d=1.0, no rescale). Lower is better.")
# DefCon only exists from 2025-26, so there is no prior season to test a DC discount on.
for y, pref, what in (("y_xgi", "xgi", "xGI/90, no rescale"), ("y_xgi", "xgis", "xGI/90, prior rescaled by club attack")):
    print(f"\n{what}")
    for grp, g in (("changers", R[R.changer]), ("stayers", R[~R.changer])):
        table(g, f"{grp} all k", y, pref)
        for k in CHECKPOINTS:
            table(g[g.k == k], f"{grp} k={k}", y, pref)
    if pref != "dc":
        ch = R[R.changer]
        for p in ("DEF", "MID", "FWD"):
            table(ch[ch.pos == p], f"changers {p}", y, pref)
        table(ch[~ch.promoted], "changers, new club not promoted", y, pref)
        for sname, g in ch.groupby("season"):
            table(g, f"changers {sname}", y, pref)
print("\nAbsolute comparison for changers (MSE relative to production = unscaled, d=1):")
ch = R[R.changer]
base = wmse(ch, "xgi_1.0", "y_xgi")
cands = {"production": "xgi_1.0", "full rescale": "xgis_1.0", "rescale^0.25": "xgia_0.25",
         "rescale^0.5": "xgia_0.5", "rescale^0.75": "xgia_0.75", "discount d=0.5": "xgi_0.5",
         "rescale + d=0.5": "xgis_0.5", "rescale + d=0.3": "xgis_0.3"}
for grp, g in (("all", ch), ("not promoted", ch[~ch.promoted]), ("scale>1.15 (moved up)", ch[ch.scale > 1.15]),
               ("scale<0.87 (moved down)", ch[ch.scale < 0.87])):
    b = wmse(g, "xgi_1.0", "y_xgi")
    print(f"  {grp:26s} n={len(g):3d} " + "  ".join(f"{lab} {wmse(g, c, 'y_xgi') / b:.3f}" for lab, c in cands.items()))
print("\nBias: does production's miss track the change in club strength? (changers, minutes-weighted)")
g = ch[~ch.promoted].copy(); g["res"] = g.y_xgi - g["xgi_1.0"]; g["ls"] = np.log(g.scale)
slope = np.polyfit(g.ls, g.res, 1, w=np.sqrt(g.fut_min))[0]
for lab, gg in (("moved up (scale>1.15)", g[g.scale > 1.15]), ("similar", g[(g.scale >= 0.87) & (g.scale <= 1.15)]), ("moved down (scale<0.87)", g[g.scale < 0.87])):
    print(f"  {lab:24s} n={len(gg):3d} ({gg.name.nunique()} players)  actual {np.average(gg.y_xgi, weights=gg.fut_min):.3f}  production {np.average(gg['xgi_1.0'], weights=gg.fut_min):.3f}  full rescale {np.average(gg['xgis_1.0'], weights=gg.fut_min):.3f}")
print(f"  residual slope on log(scale): {slope:+.3f} xGI/90 per unit log-scale")
R.to_csv(Path(__file__).resolve().parent.parent / "data" / "processed" / "_club_change_backtest.csv", index=False)
