#!/usr/bin/env python3
"""
build_shortlist.py — per-slot candidate shortlists + a 15-man squad (Tasks 1-5).
================================================================================
Joins 2026-27 price/club (bootstrap) to 2025-26 nailedness & output via permanent
`code`, adds age, availability (status/news), mover flag, and each club's GW1-6
fixture score. Ranks candidates per budget slot. NAILEDNESS CANNOT BE CONFIRMED
PRE-SEASON — flags are from 2025-26 and every mover/promoted player is uncertain.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SEASON_START = date(2026, 8, 21)


def build_master():
    nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    for c in ["minutes", "total_points", "GW"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    # 2025-26 per-player nailedness/output (via id, mapped to code)
    gw = g.groupby(["element", "GW"]).agg(mins=("minutes", "sum"), pts=("total_points", "sum")).reset_index()
    rows = []
    for el, pg in gw.groupby("element"):
        n60 = int((pg.mins >= 60).sum()); ncam = int(((pg.mins >= 1) & (pg.mins < 60)).sum())
        ppg = pg.loc[pg.mins >= 60, "pts"].mean()
        rows.append((el, n60, ncam, ppg))
    prof = pd.DataFrame(rows, columns=["id", "n60", "ncam", "pts_start"])
    last_club = g.groupby("element")["team"].agg(lambda s: s.mode().iloc[0]).rename("club_2526")
    pr25 = pr[["id", "code", "total_points"]].merge(prof, on="id", how="left").merge(last_club, left_on="id", right_index=True, how="left")
    pr25 = pr25.rename(columns={"total_points": "tp_2526"})

    m = nxt[["code", "web_name", "element_type", "team_name", "now_cost", "status", "news",
             "chance_of_playing_next_round", "birth_date"]].copy()
    m["pos"] = m["element_type"].map(POS)
    m["price"] = m["now_cost"] / 10.0
    def _age(b):
        try:
            return round((SEASON_START - date.fromisoformat(str(b)[:10])).days / 365.25)
        except Exception:
            return np.nan
    m["age"] = m["birth_date"].apply(_age)
    print(f"[diag] birth_date non-null: {m['birth_date'].notna().sum()}/{len(m)}; ages resolved: {m['age'].notna().sum()}")
    m = m.merge(pr25[["code", "tp_2526", "n60", "ncam", "pts_start", "club_2526"]], on="code", how="left")
    m["P_start"] = (m["n60"] / 38).round(2)
    m["cameo_share"] = (m["ncam"] / (m["n60"] + m["ncam"]).replace(0, np.nan)).round(2)
    # map last-season club (full name) -> short code so mover detection is correct
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    name2short = dict(zip(lt.team_fpl, lt.short))
    m["club_2526_sh"] = m["club_2526"].map(name2short)
    m["moved"] = m["club_2526_sh"].notna() & (m["club_2526_sh"] != m["team_name"])
    m["type"] = np.where(m["cameo_share"] >= 0.25, "B-cameo", "A-clean")
    return m


def fixture_scores():
    fx = pd.read_csv(RAW / "fixtures_2026-27.csv"); t = pd.read_csv(RAW / "teams_2026-27.csv")
    ep = pd.read_csv(RAW / "expected_points_2026-27.csv")
    id2sh = dict(zip(t.id, t.short_name)); exp = dict(zip(ep.short, ep.exp_pts_2026_27))
    op = fx[fx.event <= 6]; oe = {sh: [] for sh in id2sh.values()}
    for r in op.itertuples():
        oe[id2sh[r.team_h]].append(exp.get(id2sh[r.team_a], 45))
        oe[id2sh[r.team_a]].append(exp.get(id2sh[r.team_h], 45))
    # 1 (hard) .. 5 (easy)
    return {sh: round(float(np.interp(np.mean(v) if v else 50, [47, 61], [5, 1])), 1) for sh, v in oe.items()}


def flags(r):
    f = []
    if r.status != "a":
        f.append(f"{'INJ' if r.status=='i' else 'DBT' if r.status=='d' else 'SUS' if r.status=='s' else 'UNA'}")
    if r.moved:
        f.append(f"MOVED<-{r.club_2526}")
    if pd.isna(r.pts_start):
        f.append("NO 25-26 DATA")
    if pd.notna(r.age) and r.age >= 32:
        f.append(f"AGE {int(r.age)}")
    if r.type == "B-cameo" and pd.notna(r.cameo_share):
        f.append("CAMEO-RISK")
    return ",".join(f) or "-"


def shortlist(m, fs, pos, lo, hi, clubs=None, n=5, need_starts=0, by_nailed=False):
    d = m[(m.pos == pos) & (m.price >= lo) & (m.price <= hi)].copy()
    if clubs:
        d = d[d.team_name.isin(clubs)]
    if need_starts:
        d = d[d.n60 >= need_starts]
    d["fix"] = d.team_name.map(fs)
    d["score"] = (d.pts_start.fillna(0) * d.P_start.fillna(0))       # expected pts/GW proxy
    d = d.sort_values(["P_start", "score"] if by_nailed else ["score", "P_start"], ascending=False)
    return d.head(n)


def show(title, d):
    print(f"\n### {title}")
    print(f"  {'player':>14} {'club':>4} {'£':>4} {'P(st)':>5} {'fix':>3} {'pts/st':>6} {'age':>3}  flags")
    for r in d.itertuples():
        ps = f"{r.pts_start:.2f}" if pd.notna(r.pts_start) else "  - "
        pst = f"{r.P_start:.2f}" if pd.notna(r.P_start) else "  - "
        ag = f"{int(r.age)}" if pd.notna(r.age) else " - "
        print(f"  {r.web_name[:14]:>14} {r.team_name:>4} {r.price:>4.1f} {pst:>5} {r.fix:>3} {ps:>6} {ag:>3}  {flags(r)}")


def main():
    m = build_master(); fs = fixture_scores()
    PRI = ["MUN", "ARS", "LIV", "CHE", "MCI", "NEW", "EVE"]
    print("FIXTURE score key: 5=easy GW1-6 .. 1=hard.  Flags: INJ/DBT/SUS, MOVED, AGE32+, CAMEO-RISK.\n"
          "*** PRE-SEASON: all nailedness is 2025-26-based; movers & promoted are UNCONFIRMED. ***")

    show("GK — playing keeper £5.0-5.5 (priority/solid clubs)", shortlist(m, fs, "GK", 5.0, 5.5))
    show("GK — £4.0 backup that actually STARTS (ranked by nailedness)", shortlist(m, fs, "GK", 4.0, 4.0, by_nailed=True, n=6))
    show("DEF — attacking £6.0-6.5 (priority clubs)", shortlist(m, fs, "DEF", 6.0, 6.5, clubs=PRI))
    show("DEF — mid £4.5-5.5 (MUN/EVE/CHE/ARS/LIV)", shortlist(m, fs, "DEF", 4.5, 5.5, clubs=["MUN","EVE","CHE","ARS","LIV"], n=6))
    show("DEF — floor £4.0 (ranked by nailedness; is a nailed £4.0 DEF even available?)", shortlist(m, fs, "DEF", 4.0, 4.0, by_nailed=True, n=8))
    show("MID — premium £8.0-9.0", shortlist(m, fs, "MID", 8.0, 9.0))
    show("MID — mid £6.5-7.5 (skip £6.0)", shortlist(m, fs, "MID", 6.5, 7.5))
    show("MID — value £5.0-5.5", shortlist(m, fs, "MID", 5.0, 5.5, n=6))
    show("MID — value £5.0-5.5 MAN UTD only (cheap entry)", shortlist(m, fs, "MID", 4.5, 5.5, clubs=["MUN"]))
    show("FWD — £8 slot (Haaland option / no-Haaland mid)", shortlist(m, fs, "FWD", 7.5, 8.5))
    show("FWD — £6 slot (playing backup)", shortlist(m, fs, "FWD", 5.5, 6.5))
    show("FWD — £9-10 premium (no-Haaland option)", shortlist(m, fs, "FWD", 9.0, 10.5))
    show("FWD — Haaland check", shortlist(m, fs, "FWD", 15.0, 16.0))

    m.to_csv(Path(__file__).resolve().parent.parent / "data" / "outputs" / "master_candidates.csv", index=False)
    print("\n[saved master_candidates.csv]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
