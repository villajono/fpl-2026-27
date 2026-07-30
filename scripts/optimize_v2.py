#!/usr/bin/env python3
"""optimize_v2.py — re-run squad selection on the V2 EV model (GW1-8 pre-wildcard window).
Objective: best legal XI each week + captain (best MID/FWD) + auto-sub cover, under £100,
2/5/5/3, max 3 per club. Established players only (>=450 min -> reliable per-90 rates)."""
from __future__ import annotations
import math, numpy as np, pandas as pd
import ev_v2 as V, squad_engine as SE, fixture_ratings as FR

nxt = V._nxt; ID2SH = SE.ID2SH; FX = SE.FX; POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(range(1, 9))].itertuples():
    FIX[ID2SH[r.team_h]][r.event] = (ID2SH[r.team_a], True); FIX[ID2SH[r.team_a]][r.event] = (ID2SH[r.team_h], False)
P60_OVR = V.P60_OVR

# ---- build pool with precomputed V2 EV per GW (established players only) ----
BAN_NAMES = {"Dubravka", "Vicario", "Thiaw", "Botman", "Awoniyi"}   # ruled out on human judgment
names, POS, CLUB, PR, EV = [], [], [], [], []
for r in nxt[nxt.status == "a"].itertuples():
    if r.web_name in BAN_NAMES: continue
    code = int(r.code); pos = POSN[int(r.element_type)]; team = r.team_name
    if team not in FIX: continue
    rates = V.get_per_90_rates(code)
    if rates["thin"]: continue                       # need reliable per-90 rates to select on
    mp = V.get_minutes_probs(code, r.web_name)
    p_dc_f = V.get_p_dc_bonus(rates, 90); p_dc_p = V.get_p_dc_bonus(rates, mp["partial"])
    cs_pts = V.get_cs_pts(pos); save_pts = 1 / 3 if pos == "GK" else 0.0
    xg, xa, sv = rates["xG90"], rates["xA90"], rates["sv90"]
    ev8 = []
    for gw in range(1, 9):
        fx = FIX[team].get(gw)
        if not fx: ev8.append(0.0); continue
        o, h = fx; cs = V.get_cs_probability(team, o, h); orat = FR.RATINGS.get(o, {"att": 1.0, "defw": 1.0})
        af = orat["defw"] * (1.05 if h else 0.95); sf = orat["att"] * (0.95 if h else 1.05)
        full = cs * cs_pts + 2 + xg * 6 * af + xa * 3 * af + p_dc_f * 2 + sv * save_pts * sf
        part = (mp["partial"] / 90) * (xg * 6 * af + xa * 3 * af + p_dc_p * 2 * 0.5 + sv * save_pts * sf)
        ev8.append(mp["p60"] * full + mp["p_cameo"] * part)
    names.append(r.web_name); POS.append(pos); CLUB.append(team); PR.append(r.now_cost / 10); EV.append(ev8)
EV = np.array(EV); PR = np.array(PR); N = len(names)
IDX = {(names[i], POS[i], CLUB[i]): i for i in range(N)}


def week_value(idxs, gw):
    gk = [i for i in idxs if POS[i] == "GK"]; sg = max(gk, key=lambda i: EV[i, gw])
    D = sorted([i for i in idxs if POS[i] == "DEF"], key=lambda i: -EV[i, gw])
    Mi = sorted([i for i in idxs if POS[i] == "MID"], key=lambda i: -EV[i, gw])
    Fw = sorted([i for i in idxs if POS[i] == "FWD"], key=lambda i: -EV[i, gw])
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3 and len(D) >= d and len(Mi) >= m and len(Fw) >= f:
                xi = [sg] + D[:d] + Mi[:m] + Fw[:f]; s = sum(EV[i, gw] for i in xi)
                if best is None or s > best[0]: best = (s, xi)
    s, xi = best
    cap = max([i for i in xi if POS[i] in ("MID", "FWD")], key=lambda i: EV[i, gw])
    bench = sorted([i for i in idxs if POS[i] != "GK" and i not in xi], key=lambda i: -EV[i, gw])
    auto = sum(0.15 * EV[bench[j], gw] for j in range(min(3, len(bench))))  # modest bench cover
    return s + EV[cap, gw] + auto


def raw(idxs): return sum(week_value(idxs, g) for g in range(8))
def value(idxs): return raw(idxs) - 1000 * max(0, PR[idxs].sum() - 100)
def club_ok(idxs):
    c = {}
    for i in idxs:
        c[CLUB[i]] = c.get(CLUB[i], 0) + 1
        if c[CLUB[i]] > 3: return False
    return True


def climb(start):
    b = list(start); bv = value(b)
    for _ in range(80):
        mv = None; bg = bv
        for si, s in enumerate(b):
            for c in range(N):
                if c in b or POS[c] != POS[s]: continue
                t = b[:si] + [c] + b[si + 1:]
                if PR[t].sum() > 100 or not club_ok(t): continue
                v = value(t)
                if v > bg: bg = v; mv = (si, c)
        if not mv: break
        b[mv[0]] = mv[1]; bv = bg
    return b, bv


# seed from Team Claude (all established), then basin-hop
import ev_v2_compare as C
seed = [IDX.get((n, p, t)) for (n, p, t) in C.TEAM]
seed = [i for i in seed if i is not None]
best, bv = climb(seed); rng = np.random.default_rng(0)
for _ in range(15):
    p = list(best)
    for _ in range(3):
        si = int(rng.integers(len(p))); opts = [c for c in range(N) if c not in p and POS[c] == POS[p[si]]]
        if opts:
            c = int(rng.choice(opts)); t = p[:si] + [c] + p[si + 1:]
            if PR[t].sum() <= 100 and club_ok(t): p = t
    cand, cv = climb(p)
    if cv > bv: best, bv = cand, cv


def show(idxs, label):
    order = sorted(idxs, key=lambda i: (["GK", "DEF", "MID", "FWD"].index(POS[i]), -EV[i].mean()))
    print(f"\n{label}: GW1-8 V2 = {raw(idxs):.1f} | £{PR[idxs].sum():.1f}m")
    for i in order:
        print(f"  {POS[i]:>3} {names[i][:15]:>15} {CLUB[i]:>4} £{PR[i]:>4.1f}  8gw EV {EV[i].sum():.1f}")


show(best, "V2-OPTIMAL SQUAD")
tc = [IDX.get((n, p, t)) for (n, p, t) in C.TEAM]; tc = [i for i in tc if i is not None]
print(f"\nV2 GW1-8:  V2-optimal {raw(best):.1f}   |   Team Claude (V1-optimal) {raw(tc):.1f}   |   gain +{raw(best)-raw(tc):.1f}")
print("Haaland in V2-optimal squad?", "Haaland" in [names[i] for i in best])
print("structure:", {p: sum(1 for i in best if POS[i] == p) for p in ["GK", "DEF", "MID", "FWD"]})
