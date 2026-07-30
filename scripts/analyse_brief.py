#!/usr/bin/env python3
"""
analyse_brief.py — the 5-part budget-allocation analysis (position level only).
===============================================================================
Last season = 2025-26 (weekly data); this season = 2026-27 (new price list).
Floors: GK 4.0, DEF 4.0, MID 4.5, FWD 4.5. Qualifying start = 60+ mins.
No player recommendations — position / price-point insight only.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FLOOR = {"GK": 4.0, "DEF": 4.0, "MID": 4.5, "FWD": 4.5}
GW_TOTAL = 38


def load():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    t = pd.read_csv(RAW / "teams_2025-26.csv")
    nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")   # authoritative final table
    for c in ["minutes", "total_points", "value", "opponent_team"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    pr["pos"] = pr["element_type"].map(POS)
    pr["start_price"] = (pr["now_cost"] - pr["cost_change_start"]) / 10.0
    pr["total_points"] = pd.to_numeric(pr["total_points"], errors="coerce").fillna(0)
    nxt["pos"] = nxt["element_type"].map(POS)
    nxt["price"] = nxt["now_cost"] / 10.0
    return g, pr, t, nxt, lt


def per_player(g, pr):
    app60 = g[g.minutes >= 60]
    agg = g.groupby("element").agg(
        avg_price=("value", lambda v: v.mean() / 10.0),
        team=("team", lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0]),
        appearances=("minutes", lambda m: (m >= 1).sum()),
    )
    q = app60.groupby("element").agg(q_starts=("minutes", "size"),
                                     ppg_start=("total_points", "mean"),
                                     ppg_sd=("total_points", "std"))
    pl = pr[["id", "web_name", "pos", "start_price", "total_points"]].rename(columns={"id": "element"})
    pl = pl.merge(agg, on="element", how="left").merge(q, on="element", how="left")
    pl["q_starts"] = pl["q_starts"].fillna(0).astype(int)
    return pl


def sec1(pl):
    print("\n" + "=" * 78 + "\n1) POINTS PER DISCRETIONARY £ BY POSITION  (players with 10+ qualifying starts)\n")
    d = pl[pl.q_starts >= 10].copy()
    d["discr"] = d["avg_price"] - d["pos"].map(FLOOR)
    ok = d[d.discr >= 0.1].copy()
    ok["ppd"] = ok["total_points"] / ok["discr"]
    print(f"{'pos':>4} {'n':>4} {'p25':>6} {'median':>7} {'p75':>6} {'best (player)':>26} {'worst (player)':>26}")
    for p in ["GK", "DEF", "MID", "FWD"]:
        s = ok[ok.pos == p]
        if not len(s):
            continue
        b = s.loc[s.ppd.idxmax()]; w = s.loc[s.ppd.idxmin()]
        nfloor = ((d.pos == p) & (d.discr < 0.1)).sum()
        print(f"{p:>4} {len(s):>4} {s.ppd.quantile(.25):>6.0f} {s.ppd.median():>7.0f} "
              f"{s.ppd.quantile(.75):>6.0f} {(b.web_name+' '+str(round(b.ppd))):>26} "
              f"{(w.web_name+' '+str(round(w.ppd))):>26}   (+{nfloor} near floor)")
    print("  ppd = season points / (avg price - floor). 'at/near floor' players give big points "
          "for ~£0 discretionary -> effectively infinite efficiency.")


def sec2(pl, nxt):
    print("\n" + "=" * 78 + "\n2) POINTS BY EXACT PRICE POINT  (last-season 10+ starts ; + this-season market count)\n")
    d = pl[pl.q_starts >= 10].copy()
    d["pp"] = d["start_price"].round(1)
    for p in ["GK", "DEF", "MID", "FWD"]:
        fl = FLOOR[p]
        s = d[d.pos == p]
        mkt = nxt[nxt.pos == p].groupby(nxt["price"].round(1)).size()
        print(f"--- {p} (floor £{fl}) ---")
        print(f"  {'price':>6} {'n25/26':>7} {'med':>5} {'min':>5} {'max':>5} {'std':>5} "
              f"{'pts/discr£':>10} {'n26/27(mkt)':>11}")
        prices = sorted(set(s.pp.unique()) | set(mkt.index))
        for pp in prices:
            band = s[s.pp == pp]
            m = int(mkt.get(pp, 0))
            if len(band):
                med = band.total_points.median()
                ppd = f"{med/(pp-fl):>10.0f}" if pp - fl >= 0.1 else f"{'floor':>10}"
                print(f"  £{pp:>4.1f} {len(band):>7} {med:>5.0f} {band.total_points.min():>5.0f} "
                      f"{band.total_points.max():>5.0f} {band.total_points.std():>5.0f} {ppd} {m:>11}")
            else:
                print(f"  £{pp:>4.1f} {'-':>7} {'-':>5} {'-':>5} {'-':>5} {'-':>5} {'-':>10} {m:>11}")
        print()


def sec3(g, t, lt):
    print("=" * 78 + "\n3) FIXTURE SENSITIVITY BY POSITION  (avg pts per 60+ appearance vs opponent tier)\n")
    pos_of = dict(zip(pd.read_csv(RAW / "players_raw_2025-26.csv")["id"],
                      pd.read_csv(RAW / "players_raw_2025-26.csv")["element_type"].map(POS)))
    id2short = dict(zip(t.id, t.short_name))                 # opponent id -> short code
    short2pos = dict(zip(lt.short, lt.position))             # short -> final league position
    lp = {i: short2pos.get(id2short.get(i)) for i in t.id}   # authoritative final positions
    def tier(pos_):
        return "top4" if pos_ <= 4 else ("bottom4" if pos_ >= 17 else "mid")
    a = g[g.minutes >= 60].copy()
    a["pos"] = a["element"].map(pos_of)
    a["tier"] = a["opponent_team"].map(lambda i: tier(lp.get(i, 10)))
    print(f"  {'pos':>4} {'vs top4':>8} {'vs mid':>8} {'vs bottom4':>11} {'swing(b4-t4)':>13}")
    for p in ["GK", "DEF", "MID", "FWD"]:
        s = a[a.pos == p]
        mt = s.groupby("tier")["total_points"].mean()
        t4, md, b4 = mt.get("top4", np.nan), mt.get("mid", np.nan), mt.get("bottom4", np.nan)
        print(f"  {p:>4} {t4:>8.2f} {md:>8.2f} {b4:>11.2f} {b4-t4:>+13.2f}")
    print("  (opponent tier by final 2025-26 league position: top4 = 1-4, bottom4 = 17-20)")


def sec4(g):
    print("\n" + "=" * 78 + "\n4) P(STARTS) & MINUTES SHAPE BY CLUB  (squad = players with 900+ mins)\n")
    tot_min = g.groupby("element")["minutes"].sum()
    squad = set(tot_min[tot_min >= 900].index)
    gs = g[g.element.isin(squad)].copy()
    rows = []
    for team, tg in gs.groupby("team"):
        pstart = tg[tg.minutes >= 60].groupby("element").size().reindex(
            tg.element.unique()).fillna(0) / GW_TOTAL
        mg = tg.minutes
        n_pg = len(mg)
        f0 = (mg == 0).mean(); f_cameo = ((mg >= 1) & (mg < 60)).mean(); f60 = (mg >= 60).mean()
        rows.append((team, len(tg.element.unique()), pstart.mean(), f0, f_cameo, f60))
    df = pd.DataFrame(rows, columns=["team", "n_sq", "P_start", "f_0", "f_cameo", "f_60"]).sort_values("P_start")
    print(f"  {'club':>16} {'sqN':>4} {'P(start)':>8} {'%0min':>6} {'%cameo(1-59)':>13} {'%60+':>6}")
    for r in df.itertuples():
        flag = "  <-- ROTATION" if r.P_start < df.P_start.median() - df.P_start.std() else ""
        print(f"  {str(r.team)[:16]:>16} {r.n_sq:>4} {r.P_start:>8.2f} {100*r.f_0:>5.0f}% "
              f"{100*r.f_cameo:>12.0f}% {100*r.f_60:>5.0f}%{flag}")
    print("  High %cameo (1-59) = auto-sub-blocking rotation (worst). NOTE: Man City carries")
    print("  MANAGER-CHANGE uncertainty (Guardiola gone) — treat its history as low-confidence.")


def sec5(pl):
    print("\n" + "=" * 78 + "\n5) CAPTAINCY PREMIUM  (premium pool: start price >= £8.0m, 15+ qualifying starts)\n")
    anchor = (pl[pl.q_starts >= 10].eval("total_points/avg_price")).median()
    pool = pl[(pl.start_price >= 8.0) & (pl.q_starts >= 15)].copy()
    pool = pool.sort_values("ppg_start", ascending=False).reset_index(drop=True)
    print(f"  benchmark value anchor: ~{anchor:.0f} pts per £1m of squad spend\n")
    print(f"  {'rank':>4} {'player':>16} {'pos':>4} {'£':>5} {'pts/start':>9} "
          f"{'consistency(sd)':>15} {'capt.premium(pts)':>17} {'£-equiv':>8}")
    ppg = pool["ppg_start"].tolist()
    for i, r in pool.head(5).iterrows():
        nxt_ppg = ppg[i + 1] if i + 1 < len(ppg) else ppg[i]
        prem_pts = 30 * (r.ppg_start - nxt_ppg)
        print(f"  {i+1:>4} {r.web_name[:16]:>16} {r.pos:>4} {r.start_price:>5.1f} {r.ppg_start:>9.2f} "
              f"{r.ppg_sd:>15.2f} {prem_pts:>17.0f} {prem_pts/anchor:>7.1f}m")
    print("  capt.premium = 30 GWs x (this player's pts/start - the next-best captain's pts/start);")
    print("  £-equiv converts that to squad-budget terms via the value anchor.")


def main():
    g, pr, t, nxt, lt = load()
    pl = per_player(g, pr)
    out = Path(__file__).resolve().parent.parent / "data" / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    pl.to_csv(out / "derived_players_2025-26.csv", index=False)
    sec1(pl); sec2(pl, nxt); sec3(g, t, lt); sec4(g); sec5(pl)
    print(f"\n[saved per-player derived table -> data/outputs/derived_players_2025-26.csv]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
