#!/usr/bin/env python3
"""
fixture_sensitivity.py — does fixture difficulty drive returns, by player type?
===============================================================================
Tests the rotation hypotheses against 2025-26 per-match data. Opponent tiers by
2025-26 FINAL standings: T1 = pos 1-4, T2 = 5-12, T3 = 13-20. Analysis on STARTS
(60+ mins) — the rotation decision is about whether to START a player.
Rotation-materiality threshold (brief): T1->T3 swing > 1.5 pts/game => rotation
has value; below => within noise, always start.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GMULT = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}


def load():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    t = pd.read_csv(RAW / "teams_2025-26.csv"); lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    for c in ["minutes", "total_points", "clean_sheets", "saves", "bonus", "goals_scored",
              "assists", "defensive_contribution", "opponent_team"]:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    pos = dict(zip(pr.id, pr.element_type.map(POS)))
    g["pos"] = g["element"].map(pos)
    id2sh = dict(zip(t.id, t.short_name)); sh2pos = dict(zip(lt.short, lt.position))
    def tier(i):
        p = sh2pos.get(id2sh.get(i), 10)
        return "T1" if p <= 4 else ("T2" if p <= 12 else "T3")
    g["tier"] = g["opponent_team"].map(tier)
    a = g[g.minutes >= 60].copy()                    # starts only
    a["cs_pts"] = a["clean_sheets"] * a["pos"].map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0})
    a["save_pts"] = (a["saves"] // 3).where(a.pos == "GK", 0)
    a["att_pts"] = a["goals_scored"] * a["pos"].map(GMULT) + a["assists"] * 3
    return g, a, pr


def by_tier(sub, cols):
    r = sub.groupby("tier").agg(**{c: (c, "mean") for c in cols})
    r["n"] = sub.groupby("tier").size()
    return r.reindex(["T1", "T2", "T3"])


def swingline(sub):
    m = sub.groupby("tier")["total_points"].mean().reindex(["T1", "T2", "T3"])
    sw = m["T3"] - m["T1"]
    verdict = "ROTATE (swing>1.5)" if sw > 1.5 else "always start (<1.5, noise)"
    return m, sw, verdict


def main():
    g, a, pr = load()

    print("=== TASK 1: GK points by opponent tier (GKs with 20+ starts) ===")
    gk = a[a.pos == "GK"]
    keep = gk.groupby("element").size(); gk = gk[gk.element.isin(keep[keep >= 20].index)]
    tb = by_tier(gk, ["total_points", "clean_sheets", "saves", "save_pts", "bonus"])
    print(tb.round(2).to_string())
    m, sw, v = swingline(gk)
    t1 = gk[gk.tier == "T1"].total_points; t3 = gk[gk.tier == "T3"].total_points
    p = stats.ttest_ind(t3, t1, equal_var=False).pvalue
    print(f"  GK swing T1->T3 = {sw:+.2f} pts/app (p={p:.3f}) -> {v}")
    # top-5 GKs
    top5 = pr[pr.element_type == 1].nlargest(5, "total_points").id
    g5 = gk[gk.element.isin(top5)]
    if len(g5):
        m5 = g5.groupby("tier")["total_points"].mean().reindex(["T1", "T2", "T3"])
        print(f"  TOP-5 GKs: T1 {m5['T1']:.2f} | T2 {m5['T2']:.2f} | T3 {m5['T3']:.2f} "
              f"| swing {m5['T3']-m5['T1']:+.2f}")

    print("\n=== TASK 2: outfield points by opponent tier & sub-group ===")
    # per-player attributes for sub-grouping
    st = a.groupby("element").agg(starts=("minutes", "size"), dc=("defensive_contribution", "mean"),
                                  g=("goals_scored", "sum"), asst=("assists", "sum")).reset_index()
    st["ga_per_start"] = (st.g + st.asst) / st.starts
    hi_dc = set(st[(st.dc >= 9)].element); lo_dc = set(st[(st.dc < 9)].element)
    hi_att = set(st[st.ga_per_start >= 0.15].element); lo_att = set(st[st.ga_per_start < 0.15].element)
    groups = {
        "DEF high-DC (CB/def-FB)": a[(a.pos == "DEF") & a.element.isin(hi_dc)],
        "DEF low-DC (attacking FB)": a[(a.pos == "DEF") & a.element.isin(lo_dc)],
        "MID low-attack (DM/box-box)": a[(a.pos == "MID") & a.element.isin(lo_att)],
        "MID high-attack (creative)": a[(a.pos == "MID") & a.element.isin(hi_att)],
        "FWD (all)": a[a.pos == "FWD"],
    }
    print(f"  {'sub-group':<30} {'T1':>5} {'T2':>5} {'T3':>5} {'swing':>6}  verdict")
    for name, sub in groups.items():
        sub = sub[sub.element.isin(st[st.starts >= 10].element)]
        m, sw, v = swingline(sub)
        print(f"  {name:<30} {m['T1']:>5.2f} {m['T2']:>5.2f} {m['T3']:>5.2f} {sw:>+6.2f}  {v}")
        b = by_tier(sub, ["cs_pts", "att_pts", "bonus"])
        print(f"       breakdown att-pts by tier: T1 {b.loc['T1','att_pts']:.2f} "
              f"T2 {b.loc['T2','att_pts']:.2f} T3 {b.loc['T3','att_pts']:.2f}")

    def id_of(nm):
        r = pr[pr.web_name.str.contains(nm, regex=False, na=False)]
        return int(r.id.iloc[0]) if len(r) else None

    print("\n=== TASK 3: Haaland (2025-26) ===")
    hid = id_of("Haaland"); h = g[g.element == hid]
    hs = h[h.minutes >= 60]
    if len(hs):
        m = hs.groupby("tier").agg(pts=("total_points", "mean"), gls=("goals_scored", "mean"),
                                   ast=("assists", "mean"), bon=("bonus", "mean"), n=("total_points", "size")).reindex(["T1","T2","T3"])
        print(m.round(2).to_string())
        print(f"  Haaland swing T1->T3 = {m.loc['T3','pts']-m.loc['T1','pts']:+.2f} pts/app")
        top10 = h.nlargest(10, "total_points")
        print(f"  10 best games: tier counts = {top10.tier.value_counts().to_dict()} "
              f"(share vs strong T1/T2 = {100*top10.tier.isin(['T1','T2']).mean():.0f}%)")
        id2sh = dict(zip(pd.read_csv(RAW/'teams_2025-26.csv').id, pd.read_csv(RAW/'teams_2025-26.csv').short_name))
        bigids = [i for i, s in id2sh.items() if s in ["ARS", "MUN", "LIV", "MCI", "CHE"]]
        bg = h[h.opponent_team.isin(bigids) & (h.minutes >= 60)]
        print(f"  vs big clubs (ARS/MUN/LIV/CHE): {len(bg)} games, avg {bg.total_points.mean():.2f} pts, "
              f"{bg.goals_scored.sum():.0f} goals, {bg.assists.sum():.0f} assists")

    print("\n=== TASK 4: captaincy candidates by tier ===")
    caps = ["Haaland", "B.Fernandes", "Ekitiké", "Saka", "Foden"]
    print(f"  {'player':>12} {'T1':>5} {'T2':>5} {'T3':>5} {'swing':>6} {'sd':>5}  rule")
    for nm in caps:
        cid = id_of(nm)
        p = a[a.element == cid] if cid else a.iloc[0:0]
        if len(p) < 5:
            print(f"  {nm:>12}  (insufficient starts)"); continue
        m = p.groupby("tier")["total_points"].mean().reindex(["T1","T2","T3"])
        sw = m["T3"] - m["T1"]; sd = p["total_points"].std()
        rule = "always" if sw <= 1.5 else ("avoid T1" if sw <= 3 else "rotate")
        print(f"  {nm:>12} {m['T1']:>5.2f} {m['T2']:>5.2f} {m['T3']:>5.2f} {sw:>+6.2f} {sd:>5.2f}  {rule}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
