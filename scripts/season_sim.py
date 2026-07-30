#!/usr/bin/env python3
"""
season_sim.py — FPL season simulator with per-position scoring variance (engine for Q3-Q6).
===========================================================================================
Each squad = 15 (position, price). Calibrated from 2025-26: a "good pick" at a price
has an achievable points-per-start (ppg), an appearance profile (P start/cameo/zero),
AND a per-position within-player scoring spread (CV) so returns are spiky where the
data says they are (MID/FWD > DEF/GK).

Each simulated GW: draw states + a fixture multiplier + intrinsic scoring noise; pick
the best legal XI on EXPECTED points (variance-neutral, as you must choose pre-deadline);
auto-sub zeroed starters; double a pre-chosen captain (vice if he zeroes).

KEY: mean-preserving variance leaves EXPECTED season points ~unchanged (E[sum]=sum of
means). Its effect is on the DISTRIBUTION — the ceiling (p90) and floor (p10) — which is
what matters for RANK. So sim() returns the full spread, not just the mean.
"""
from __future__ import annotations
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
RNG = np.random.default_rng(7)
N_SEASONS = 300
N_WEEKS = 38
FIX_SD = 0.22
CAMEO_PTS = 1.5


def calibrate():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    for c in ["minutes", "total_points", "GW"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    pr["pos"] = pr["element_type"].map(POS)
    pr["start_price"] = (pr["now_cost"] - pr["cost_change_start"]) / 10.0
    pr["total_points"] = pd.to_numeric(pr["total_points"], errors="coerce").fillna(0)
    posmap = dict(zip(pr.id, pr.pos))
    gw = g.groupby(["element", "GW"]).agg(mins=("minutes", "sum"),
                                          pts=("total_points", "sum")).reset_index()
    prof, cvs = [], {p: [] for p in POS.values()}
    for el, pg in gw.groupby("element"):
        n60 = (pg.mins >= 60).sum(); ncam = ((pg.mins >= 1) & (pg.mins < 60)).sum()
        app = pg[pg.mins >= 60]
        ppg = app.pts.mean()
        prof.append((el, n60, ncam, ppg))
        if len(app) >= 10 and app.pts.mean() > 0.5:
            sd = app.pts.std()
            if not np.isnan(sd):
                cvs[posmap.get(el)].append(sd / app.pts.mean())
    cv_pos = {p: float(np.median(v)) if v else 0.8 for p, v in cvs.items()}
    prof = pd.DataFrame(prof, columns=["element", "n60", "ncam", "ppg"])
    d = pr[["id", "pos", "start_price", "total_points"]].rename(columns={"id": "element"})
    d = d.merge(prof, on="element")
    d = d[d.n60 >= 8]

    def good_pick(pos, price):
        s = d[d.pos == pos]
        for w in (0.25, 0.5, 0.9, 1.5, 3.0, 6.0, 12.0):
            b = s[(s.start_price >= price - w) & (s.start_price <= price + w)]
            if len(b) >= 6 or (w >= 12.0 and len(b) >= 1):
                b = b.sort_values("total_points", ascending=False)
                top = b.head(max(2, round(len(b) / 3)))
                return (float(top.ppg.mean()), float((top.n60 / N_WEEKS).mean()),
                        float((top.ncam / N_WEEKS).mean()))
        return (2.5, 0.6, 0.15)
    return good_pick, cv_pos


class Squad:
    def __init__(self, slots, gp, cv_pos):
        self.pos = [p for p, _ in slots]
        self.price = [pr for _, pr in slots]
        cal = [gp(p, pr) for p, pr in slots]
        self.ppg = np.array([c[0] for c in cal])
        self.pstart = np.array([c[1] for c in cal])
        self.pcam = np.array([c[2] for c in cal])
        self.pzero = np.clip(1 - self.pstart - self.pcam, 0, 1)
        self.cv = np.array([cv_pos[p] for p in self.pos])
        self.k = 1.0 / np.clip(self.cv, 0.25, None) ** 2       # Gamma shape (mean-1 noise)
        self.n = len(slots)
        self.idx = {p: [i for i in range(self.n) if self.pos[i] == p] for p in ["GK", "DEF", "MID", "FWD"]}
        assert abs(sum(self.price) - 100.0) < 1e-6, f"budget {sum(self.price)}"


def _pick_xi(exp, sq):
    gk = max(sq.idx["GK"], key=lambda i: exp[i])
    D = sorted(sq.idx["DEF"], key=lambda i: -exp[i])
    M = sorted(sq.idx["MID"], key=lambda i: -exp[i])
    F = sorted(sq.idx["FWD"], key=lambda i: -exp[i])
    best, sel = -1e9, None
    for d, f in product(range(3, 6), range(1, 4)):
        m = 10 - d - f
        if not (2 <= m <= 5) or d > len(D) or m > len(M) or f > len(F):
            continue
        tot = sum(exp[i] for i in D[:d] + M[:m] + F[:f])
        if tot > best:
            best, sel = tot, (D[:d], M[:m], F[:f])
    return gk, sel


def sim(sq, weeks=N_WEEKS, seasons=N_SEASONS, attribute=False, dist=False):
    slot_pts = np.zeros(sq.n)
    season_totals = np.empty(seasons)
    for s in range(seasons):
        stot = 0.0
        for _w in range(weeks):
            fix = np.clip(RNG.normal(1.0, FIX_SD, sq.n), 0.1, None)
            exp = sq.ppg * fix * sq.pstart
            gk, (Dsel, Msel, Fsel) = _pick_xi(exp, sq)
            xi = [gk] + Dsel + Msel + Fsel
            bench = sorted([i for i in range(sq.n) if i not in xi], key=lambda i: -exp[i])
            capt = max(xi, key=lambda i: exp[i])
            vice = max((i for i in xi if i != capt), key=lambda i: exp[i])
            u = RNG.random(sq.n)
            state = np.where(u < sq.pstart, 2, np.where(u < sq.pstart + sq.pcam, 1, 0))
            noise = RNG.gamma(sq.k, 1.0 / sq.k)                # mean-1 spiky noise
            pts = np.where(state == 2, sq.ppg * fix * noise, np.where(state == 1, CAMEO_PTS, 0.0))
            cnt = {p: sum(sq.pos[i] == p for i in xi if state[i] > 0) for p in ["GK", "DEF", "MID", "FWD"]}
            final = [i for i in xi if state[i] > 0]
            for _z in [i for i in xi if state[i] == 0]:
                for b in list(bench):
                    if state[b] == 0:
                        continue
                    p = sq.pos[b]
                    if p == "GK":
                        if sq.pos[_z] == "GK":
                            final.append(b); bench.remove(b); break
                        continue
                    nc = dict(cnt); nc[p] += 1
                    if nc["DEF"] <= 5 and nc["MID"] <= 5 and nc["FWD"] <= 3 and \
                       nc["DEF"] + nc["MID"] + nc["FWD"] <= 10:
                        cnt[p] += 1; final.append(b); bench.remove(b); break
            cap_used = capt if state[capt] > 0 else (vice if state[vice] > 0 else None)
            wk = sum(pts[i] for i in final) + (pts[cap_used] if cap_used is not None else 0)
            stot += wk
            if attribute:
                for i in final:
                    slot_pts[i] += pts[i] + (pts[i] if i == cap_used else 0)
        season_totals[s] = stot
    mean = season_totals.mean()
    if attribute:
        return mean, slot_pts / seasons
    if dist:
        return mean, season_totals
    return mean


REFERENCE = [("GK", 5.5), ("GK", 4.0),
             ("DEF", 6.5), ("DEF", 5.5), ("DEF", 5.0), ("DEF", 4.5), ("DEF", 4.0),
             ("MID", 14.0), ("MID", 8.5), ("MID", 7.0), ("MID", 5.5), ("MID", 5.0),
             ("FWD", 12.0), ("FWD", 7.5), ("FWD", 5.5)]


def main():
    gp, cv = calibrate()
    print("per-position scoring CV (within-player, game to game):",
          {k: round(v, 2) for k, v in cv.items()})
    sq = Squad(REFERENCE, gp, cv)
    mean, tots = sim(sq, dist=True)
    print(f"reference squad: mean {mean:.0f} | p10 {np.percentile(tots,10):.0f} | "
          f"p90 {np.percentile(tots,90):.0f} | sd {tots.std():.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
