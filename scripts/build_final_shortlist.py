#!/usr/bin/env python3
"""
build_final_shortlist.py — independent, data-first shortlist per slot (final brief).
Percentile-achievable discipline, full flag set, thin-tier warnings, GW1-8 fixtures.
No external consensus — 2025-26 data + 2026-27 prices/fixtures only.
"""
from __future__ import annotations
from pathlib import Path
from itertools import combinations
import numpy as np, pandas as pd
import rotation_pairs as R

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
PROMOTED = {"COV", "HUL", "IPS"}


def build():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
    for c in ["minutes", "total_points"]:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    st = g[g.minutes >= 60]
    agg = st.groupby("element").agg(n60=("minutes", "size"), pts_start=("total_points", "mean"),
                                    sd=("total_points", "std"), mean_min=("minutes", "mean")).reset_index()
    cam = g[(g.minutes >= 1) & (g.minutes < 60)].groupby("element").size().rename("ncam")
    tot = g.groupby("element")["total_points"].sum().rename("tp")
    p = pr[["id", "code", "element_type", "penalties_order"]].rename(columns={"id": "element"})
    d = p.merge(agg, on="element", how="left").merge(cam, on="element", how="left").merge(tot, on="element", how="left")
    d["pos"] = d.element_type.map(POS); d["ncam"] = d.ncam.fillna(0); d["n60"] = d.n60.fillna(0)
    d = d.merge(nxt[["code", "web_name", "team_name", "now_cost", "status"]], on="code", how="right")
    d["price"] = d.now_cost / 10.0
    d["P_start"] = (d.n60 / 38).round(2)
    d["cameo_sh"] = (d.ncam / (d.n60 + d.ncam)).round(2)
    d["pen"] = pd.to_numeric(d.penalties_order, errors="coerce") <= 1
    return d[d.status == "a"]


def flags(r):
    f = []
    if r.pen: f.append("PEN")
    if pd.notna(r.P_start) and r.P_start < 0.75: f.append("ROT-RISK")
    if pd.notna(r.cameo_sh) and r.cameo_sh >= 0.25: f.append("TYPE-B-CAMEO")
    if pd.notna(r.mean_min) and r.mean_min < 78 and r.n60 >= 8: f.append("TYPE-D-EARLYSUB")
    if r.team_name in PROMOTED: f.append("PROMOTED")
    if (pd.notna(r.P_start) and r.P_start >= 0.85 and pd.notna(r.mean_min) and r.mean_min >= 80
            and pd.notna(r.pts_start) and r.pts_start >= 5.0): f.append("CAPT-CAND")
    return ",".join(f) or "-"


def fixture_scores(gwmax=8):
    fx = pd.read_csv(RAW / "fixtures_2026-27.csv"); t = pd.read_csv(RAW / "teams_2026-27.csv")
    ep = pd.read_csv(RAW / "expected_points_2026-27.csv")
    id2sh = dict(zip(t.id, t.short_name)); imp = dict(zip(ep.short, ep.exp_pts_2026_27))
    oe = {s: [] for s in id2sh.values()}
    for r in fx[fx.event <= gwmax].itertuples():
        oe[id2sh[r.team_h]].append(imp.get(id2sh[r.team_a], 45))
        oe[id2sh[r.team_a]].append(imp.get(id2sh[r.team_h], 45))
    return {s: round(float(np.interp(np.mean(v) if v else 50, [47, 61], [5, 1])), 1) for s, v in oe.items()}


def slot(d, fs, pos, lo, hi, pct, n=4, title=""):
    band = d[(d.pos == pos) & (d.price >= lo) & (d.price <= hi) & (d.n60 >= 10)].copy()
    thin = len(band) < 5
    band["fx"] = band.team_name.map(fs)
    band = band.sort_values("tp", ascending=False)
    pctile = np.percentile(band.tp, pct) if len(band) else np.nan
    print(f"\n### {title}  [achievable {pct}th pct ~= {pctile:.0f} pts{' | THIN TIER <5' if thin else ''}]")
    print(f"  {'#':>2} {'player':>14} {'club':>4} {'£':>4} {'25-26':>5} {'P(st)':>5} {'fx':>3}  flags")
    for i, r in enumerate(band.head(n).itertuples(), 1):
        print(f"  {i:>2} {str(r.web_name)[:14]:>14} {r.team_name:>4} {r.price:>4.1f} {r.tp:>5.0f} "
              f"{r.P_start:>5.2f} {r.fx:>3}  {flags(r)}")
    return band.head(n)


def main():
    d = build(); fs = fixture_scores(8)
    print("Independent data-first shortlist. Flags: PEN, ROT-RISK(<0.75), TYPE-B-CAMEO,")
    print("TYPE-D-EARLYSUB(mean<78min), PROMOTED, CAPT-CAND. AGE unavailable (birth_date 5/558).")

    slot(d, fs, "GK", 4.5, 4.5, 55, title="GK #1/#2  (£4.5)")
    slot(d, fs, "DEF", 6.3, 6.7, 65, title="DEF anchor (£6.5)")
    slot(d, fs, "DEF", 5.3, 5.7, 60, title="DEF attacking (£5.5)")
    slot(d, fs, "DEF", 4.3, 4.7, 55, title="DEF rotation (£4.5)")
    slot(d, fs, "DEF", 3.9, 4.1, 50, title="DEF £4.0 (need genuine starter)")
    slot(d, fs, "MID", 9.0, 12.0, 75, title="MID PREMIUM (£9-12, price follows)")
    slot(d, fs, "MID", 8.3, 8.7, 70, title="MID (£8.5)")
    slot(d, fs, "MID", 7.3, 7.7, 68, title="MID (£7.5)")
    slot(d, fs, "MID", 6.3, 6.7, 65, title="MID value (£6.5, skip 6.0)")
    slot(d, fs, "MID", 5.3, 5.7, 58, title="MID enabler (£5.5)")
    slot(d, fs, "FWD", 7.3, 7.7, 68, title="FWD (£7.5)")
    slot(d, fs, "FWD", 5.3, 5.7, 58, title="FWD (£5.5)")

    # GK rotation correlation (top nailed £4.5 pairs)
    print("\n### GK ROTATION — nailed £4.5 pairs, GW1-10 fixture correlation")
    fx, id2sh, imp, mm, clubs, opp, diff = R.load(); C = R.corr_matrix(clubs, diff)
    gk = d[(d.pos == "GK") & (d.price <= 4.5) & (d.P_start >= 0.90)]
    gkc = list(dict.fromkeys(gk.team_name))
    prs = sorted([(a, b, C.loc[a, b]) for a, b in combinations(gkc, 2)], key=lambda x: x[2])[:3]
    for a, b, c in prs:
        print(f"    {a}-{b}: corr {c:+.2f}")
    # DEF trio correlation
    print("### DEF £4.0-4.5 rotation — best all-negative trio (GW1-10)")
    defc = list(dict.fromkeys(d[(d.pos == "DEF") & (d.price <= 4.5) & (d.P_start >= 0.85)].team_name)) + ["COV"]
    best = None
    for a, b, c in combinations(defc, 3):
        try:
            cs = [C.loc[a, b], C.loc[a, c], C.loc[b, c]]
        except Exception:
            continue
        if max(cs) < 0 and (best is None or sum(cs) < best[1]):
            best = ((a, b, c), sum(cs), cs)
    print(f"    {best[0] if best else 'NONE all-negative -> use 2 rotators + 1 playing £4.0'}"
          + (f"  corrs {[round(x,2) for x in best[2]]}" if best else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
