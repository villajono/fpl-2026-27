#!/usr/bin/env python3
"""andy_compare.py — Andy's (Let's Talk FPL) squad through V2, vs Santa Claude & FPL Mate."""
from __future__ import annotations
import numpy as np, pandas as pd
import ev_v2 as V, fixture_ratings as FR, squad_engine as SE

nxt = V._nxt; ID2SH = SE.ID2SH; FX = SE.FX; POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(range(1, 9))].itertuples():
    FIX[ID2SH[r.team_h]][r.event] = (ID2SH[r.team_a], True); FIX[ID2SH[r.team_a]][r.event] = (ID2SH[r.team_h], False)

# ---- human overrides (player facts, applied globally so all squads are consistent) ----
V.P60_OVR.update({"Mosquera": 0.95, "Lammens": 0.95, "McNally": 0.0, "Bassette": 0.0})

def code_of(nm, pos, team):
    m = nxt[(nxt.web_name == nm) & (nxt.element_type == {v: k for k, v in POSN.items()}[pos]) & (nxt.team_name == team)]
    return int((m.iloc[0] if len(m) else nxt[nxt.web_name == nm].iloc[0]).code)

def ev8(code, nm, pos, team):
    return [V.compute_ev_v2(code, nm, pos, team, *FIX[team][g]) for g in range(1, 9) if FIX[team].get(g)]

def bd8(code, nm, pos, team):
    B = {"cs": 0, "app": 0, "xg": 0, "xa": 0, "dc": 0}
    for g in range(1, 9):
        if not FIX[team].get(g): continue
        b = V.compute_ev_v2(code, nm, pos, team, *FIX[team][g], breakdown=True)
        for k in B: B[k] += b[k]
    return B

def agg(players, weeks=8):
    tot = 0.0; comp = {"GK": 0.0, "DEF": 0.0, "MID": 0.0, "FWD": 0.0, "cap": 0.0}
    for gi in range(weeks):
        gk = [p for p in players if p["pos"] == "GK"]; sg = max(gk, key=lambda p: p["ev"][gi])
        D = sorted([p for p in players if p["pos"] == "DEF"], key=lambda p: -p["ev"][gi])
        M = sorted([p for p in players if p["pos"] == "MID"], key=lambda p: -p["ev"][gi])
        Fw = sorted([p for p in players if p["pos"] == "FWD"], key=lambda p: -p["ev"][gi])
        best = None
        for d in range(3, 6):
            for m in range(2, 6):
                f = 10 - d - m
                if 1 <= f <= 3 and len(D) >= d and len(M) >= m and len(Fw) >= f:
                    xi = [sg] + D[:d] + M[:m] + Fw[:f]; s = sum(p["ev"][gi] for p in xi)
                    if best is None or s > best[0]: best = (s, xi)
        s, xi = best; cap = max([p for p in xi if p["pos"] in ("MID", "FWD")], key=lambda p: p["ev"][gi])
        bench = sorted([p for p in players if p["pos"] != "GK" and p not in xi], key=lambda p: -p["ev"][gi])
        auto = sum(0.15 * bench[j]["ev"][gi] for j in range(min(3, len(bench))))
        tot += s + cap["ev"][gi] + auto
        for p in xi: comp[p["pos"]] += p["ev"][gi]
        comp["cap"] += cap["ev"][gi]
    return tot, comp

def build(defn):
    out = []
    for nm, pos, team in defn:
        c = code_of(nm, pos, team); out.append(dict(name=nm, pos=pos, team=team, code=c, ev=ev8(c, nm, pos, team)))
    return out

ANDY = [("Lammens","GK","MUN"),("McNally","GK","FUL"),("Maguire","DEF","MUN"),("N.Williams","DEF","NFO"),
        ("Mosquera","DEF","ARS"),("van Ewijk","DEF","COV"),("Robinson","DEF","FUL"),("B.Fernandes","MID","MUN"),
        ("Semenyo","MID","MCI"),("Anderson","MID","MCI"),("Szoboszlai","MID","LIV"),("Groß","MID","BHA"),
        ("Haaland","FWD","MCI"),("João Pedro","FWD","CHE"),("Bassette","FWD","COV")]
SANTA = [("Sánchez","GK","CHE"),("Leno","GK","FUL"),("Senesi","DEF","TOT"),("Van Hecke","DEF","TOT"),("Romero","DEF","TOT"),
         ("Calafiori","DEF","ARS"),("Van den Berg","DEF","BRE"),("Mbeumo","MID","MUN"),("Anderson","MID","MCI"),("Enzo","MID","CHE"),
         ("Sarr","MID","CRY"),("Gomez","MID","BHA"),("Haaland","FWD","MCI"),("Thiago","FWD","BRE"),("Mateta","FWD","CRY")]
MATE = [("Lammens","GK","MUN"),("Phillips","GK","HUL"),("Mosquera","DEF","ARS"),("N.Williams","DEF","NFO"),("Kayode","DEF","BRE"),
        ("Virgil","DEF","LIV"),("van Ewijk","DEF","COV"),("Mbeumo","MID","MUN"),("Szoboszlai","MID","LIV"),("Stach","MID","LEE"),
        ("Gomez","MID","BHA"),("B.Fernandes","MID","MUN"),("Walle Egeli","FWD","IPS"),("Haaland","FWD","MCI"),("João Pedro","FWD","CHE")]

andy = build(ANDY)
print("="*78); print("ANDY'S SQUAD — GW1-8 V2 component breakdown (CS · appearance · xG · xA · DC = total)"); print("="*78)
print(f"  {'player':>13} {'pos':>3} {'CS':>5} {'app':>5} {'xG':>5} {'xA':>5} {'DC':>5} {'TOT8':>6}  note")
for nm, pos, team in ANDY:
    if nm in ("McNally", "Bassette"):
        print(f"  {nm:>13} {pos:>3} {'—':>5} {'—':>5} {'—':>5} {'—':>5} {'—':>5} {'~0':>6}  bench filler (P(start)~0, EV negligible)"); continue
    c = code_of(nm, pos, team); B = bd8(c, nm, pos, team); tot = sum(B.values())
    note = ""
    if nm == "Mosquera": note = "P(start) 0.95 (Saliba out) — expect step-DOWN when Saliba returns"
    if nm == "van Ewijk": note = "PRIOR-ONLY (COV, no PL data) — see range below"
    print(f"  {nm:>13} {pos:>3} {B['cs']:>5.1f} {B['app']:>5.1f} {B['xg']:>5.1f} {B['xa']:>5.1f} {B['dc']:>5.1f} {tot:>6.1f}  {note}")

# ---- comparison ----
ta, ca = agg(andy); ts, cs = agg(build(SANTA)); tm, cm = agg(build(MATE))
print("\n" + "="*78); print("COMPARISON — GW1-8 projected points (best XI + captain + auto-sub, V2)"); print("="*78)
print(f"  {'squad':<20} {'GW1-8':>7} {'DEF':>6} {'MID':>6} {'FWD':>6} {'captain':>8}")
for lbl, t, cc in [("Andy (LTFPL)", ta, ca), ("Santa Claude", ts, cs), ("FPL Mate", tm, cm)]:
    print(f"  {lbl:<20} {t:>7.1f} {cc['DEF']:>6.1f} {cc['MID']:>6.1f} {cc['FWD']:>6.1f} {cc['cap']:>8.1f}")
