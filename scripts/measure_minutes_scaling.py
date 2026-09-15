#!/usr/bin/env python3
"""
measure_minutes_scaling.py - should per-90 rates be scaled by expected minutes given a 60+ appearance?

compute_ev_v2 prices a 60+ appearance as xG90 + xA90 (and DefCon at 90 minutes) - i.e. as if every
such appearance lasts 90. Rates are per 90 minutes PLAYED, so a forward who averages 75 minutes when
he plays 60+ is credited 20% too much attacking output in exactly the appearances that carry most of
his points. Given a start, mean minutes run GK 89.9, DEF 87.5, MID 83.2, FWD 81.8.

Walk-forward over 2025-26 (DefCon exists only from 2025-26). At checkpoints GW 8/16/24/32 the history
is 2024-25 (by name, no DefCon) plus 2025-26 up to the checkpoint. Rates use production's own
history.recency_weighted_rates. Targets are the player's 60+ appearances in the next 8 gameweeks:
  - xGI in that appearance            (attacking-points driver)
  - whether DefCon reached threshold  (Brier score, P from ev_v2.get_p_dc_bonus)
Conditioning: only 60+ appearances are scored. That is the quantity ev_full prices (p60 is modelled
separately), so it is the right conditioning here - it says nothing about p60 itself.

Candidates for m = E[minutes | 60+ appearance]:
  90            production
  pos           position mean of 60+ appearances
  player_hl{H}_k{K}  player's recency-weighted mean (half-life H apps), shrunk to position mean
                     with K pseudo-appearances
"""
from pathlib import Path
import sys
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history as H
import ev_v2 as V

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
CHECKPOINTS, AHEAD = (8, 16, 24, 32), 8


def load(path, has_dc):
    d = pd.read_csv(path, low_memory=False)
    d["gw"] = d["GW"] if "GW" in d else d["round"]
    for c in ("minutes", "expected_goals", "expected_assists", "saves", "bonus", "yellow_cards"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    d["dc"] = pd.to_numeric(d["defensive_contribution"], errors="coerce").fillna(0) if has_dc else 0.0
    d["pos"] = d.position.replace({"GKP": "GK"})
    return d[d.minutes > 0].sort_values(["gw", "kickoff_time"] if "kickoff_time" in d else ["gw"])


prev = load(RAW / "history/merged_gw_2024-25.csv", False)
cur = load(RAW / "merged_gw_2025-26.csv", True)


def rows(df):
    return [dict(minutes=float(r.minutes), xG=float(r.expected_goals), xA=float(r.expected_assists),
                 dc=float(r.dc), saves=float(r.saves), bonus=float(r.bonus), yellow=float(r.yellow_cards))
            for r in df.itertuples()]


def wmean(vals, hl):
    n = len(vals)
    if not n: return None, 0.0
    w = [1.0 if hl is None else 0.5 ** ((n - 1 - i) / hl) for i in range(n)]
    return sum(a * b for a, b in zip(w, vals)) / sum(w), sum(w)


VARIANTS = [("90", None, None), ("pos", None, None)] + \
           [(f"player_hl{h}_k{k}", h, k) for h in (None, 8, 20) for k in (0, 3, 8)]
recs = []
for c in CHECKPOINTS:
    past_cur = cur[cur.gw <= c]
    fut = cur[(cur.gw > c) & (cur.gw <= c + AHEAD) & (cur.minutes >= 60)]
    pos_mean = past_cur[past_cur.minutes >= 60].groupby("pos").minutes.mean().to_dict()
    for name, f in fut.groupby("name"):
        pos = f.pos.iloc[0]
        if pos == "GK": continue
        hist = pd.concat([prev[(prev.name == name) & (prev.pos == pos)], past_cur[past_cur.name == name]])
        if len(hist) < 3: continue
        rr = H.recency_weighted_rates(rows(hist), pos)
        # DefCon exists only from 2025-26: last season's rows carry 0, which would drag DC90 down, so
        # the DC rate and its history come from this season's appearances alone.
        cur_hist = past_cur[past_cur.name == name]
        if not len(cur_hist): continue
        rr["DC90"] = H.recency_weighted_rates(rows(cur_hist), pos)["DC90"]
        rr["dc_history"] = cur_hist.dc.tolist()
        mins60 = hist[hist.minutes >= 60].minutes.tolist()
        ms = {}
        for lab, h, k in VARIANTS:
            if lab == "90": ms[lab] = 90.0
            elif lab == "pos": ms[lab] = pos_mean[pos]
            else:
                m, wsum = wmean(mins60, h)
                ms[lab] = pos_mean[pos] if m is None else (m * wsum + pos_mean[pos] * k) / (wsum + k)
        thr = V.DC_THRESHOLD[pos]
        for r in f.itertuples():
            rec = dict(ck=c, name=name, pos=pos, minutes=r.minutes,
                       xgi=r.expected_goals + r.expected_assists, dc_hit=float(r.dc >= thr),
                       rate=rr["xG90"] + rr["xA90"])
            for lab, m in ms.items():
                rec[f"m_{lab}"] = m
                rec[f"xgi_{lab}"] = rec["rate"] * m / 90
                rec[f"pdc_{lab}"] = V.get_p_dc_bonus(rr, m)
            recs.append(rec)

R = pd.DataFrame(recs)
labs = [v[0] for v in VARIANTS]
print(f"60+ appearances scored: {len(R)} ({R.name.nunique()} players, checkpoints {CHECKPOINTS})")
print(f"actual mean minutes in these appearances: {R.minutes.mean():.1f}  by pos: {R.groupby('pos').minutes.mean().round(1).to_dict()}")
print("\nvariant                 | xGI bias (pred/actual)  xGI MSE vs 90 | DefCon Brier vs 90  P(DC) mean vs hit rate | minutes MAE")
b_mse = ((R["xgi_90"] - R.xgi) ** 2).mean(); b_br = ((R["pdc_90"] - R.dc_hit) ** 2).mean()
for lab in labs:
    mse = ((R[f"xgi_{lab}"] - R.xgi) ** 2).mean(); br = ((R[f"pdc_{lab}"] - R.dc_hit) ** 2).mean()
    print(f"  {lab:22s}| {R[f'xgi_{lab}'].sum() / R.xgi.sum():6.3f}                 {mse / b_mse:6.4f}  |"
          f" {br / b_br:6.4f}             {R[f'pdc_{lab}'].mean():.3f} vs {R.dc_hit.mean():.3f}   | {(R[f'm_{lab}'] - R.minutes).abs().mean():5.2f}")
print("\nby position, bias pred/actual (production 90 -> pos -> player_hl20_k3):")
for p, g in R.groupby("pos"):
    print(f"  {p}: xGI {g.xgi_90.sum() / g.xgi.sum():.3f} -> {g.xgi_pos.sum() / g.xgi.sum():.3f} -> {g['xgi_player_hl20_k3'].sum() / g.xgi.sum():.3f}"
          f" | P(DC) {g.pdc_90.mean():.3f} -> {g.pdc_pos.mean():.3f} -> {g['pdc_player_hl20_k3'].mean():.3f}, actual {g.dc_hit.mean():.3f}")
R.to_csv(Path(__file__).resolve().parent.parent / "data" / "processed" / "_minutes_scaling_backtest.csv", index=False)
