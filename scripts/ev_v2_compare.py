#!/usr/bin/env python3
"""ev_v2_compare.py — reproducible V1-vs-V2 squad comparison (Step 7).
V1 = form_ev × blended fixture multiplier × P(60+).  V2 = ev_v2 component decomposition.
Shows GW1-3 and GW1-8 totals, and the DEF-line component gap that V1 inflated."""
from __future__ import annotations
import pandas as pd
import ev_v2 as V, squad_engine as SE, fixture_ratings as FR

nxt = V._nxt; ID2SH = SE.ID2SH; FX = SE.FX; POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(range(1, 9))].itertuples():
    FIX[ID2SH[r.team_h]][r.event] = (ID2SH[r.team_a], True); FIX[ID2SH[r.team_a]][r.event] = (ID2SH[r.team_h], False)
OVR_FORM = {"van Ewijk": 3.6, "Walle Egeli": 2.8, "Phillips": 3.0}


def v1_form(code, name):
    el = V._code2id.get(code)
    if name in OVR_FORM: return OVR_FORM[name]
    app = V._g[(V._g.element == el) & (V._g.minutes >= 60)] if el is not None else V._g.iloc[0:0]
    return float(app.total_points.mean()) if len(app) else 3.0


def mk(nm, pos, team):
    row = nxt[(nxt.web_name == nm) & (nxt.element_type == {v: k for k, v in POSN.items()}[pos]) & (nxt.team_name == team)]
    row = (row.iloc[0] if len(row) else nxt[nxt.web_name == nm].iloc[0]); code = int(row.code)
    mp = V.get_minutes_probs(code, nm); form = v1_form(code, nm)
    ev1, ev2 = [], []
    for gw in range(1, 9):
        fx = FIX[team].get(gw)
        if not fx: ev1.append(0.0); ev2.append(0.0); continue
        o, h = fx
        ev1.append(form * FR.get_multiplier(o, pos, code, h) * mp["p60"])
        ev2.append(V.compute_ev_v2(code, nm, pos, team, o, h))
    return dict(name=nm, pos=pos, team=team, ev1=ev1, ev2=ev2)


def agg(pl, which, weeks):
    tot = 0.0; comp = {"GK": 0.0, "DEF": 0.0, "MID": 0.0, "FWD": 0.0, "cap": 0.0}
    for gi in range(weeks):
        gk = [p for p in pl if p["pos"] == "GK"]; sg = max(gk, key=lambda p: p[which][gi])
        D = sorted([p for p in pl if p["pos"] == "DEF"], key=lambda p: -p[which][gi])
        Mi = sorted([p for p in pl if p["pos"] == "MID"], key=lambda p: -p[which][gi])
        Fw = sorted([p for p in pl if p["pos"] == "FWD"], key=lambda p: -p[which][gi])
        best = None
        for d in range(3, 6):
            for m in range(2, 6):
                f = 10 - d - m
                if 1 <= f <= 3 and len(D) >= d and len(Mi) >= m and len(Fw) >= f:
                    xi = [sg] + D[:d] + Mi[:m] + Fw[:f]; s = sum(p[which][gi] for p in xi)
                    if best is None or s > best[0]: best = (s, xi)
        s, xi = best; cap = max([p for p in xi if p["pos"] in ("MID", "FWD")], key=lambda p: p[which][gi])
        for p in xi: comp[p["pos"]] += p[which][gi]
        comp["cap"] += cap[which][gi]; tot += s + cap[which][gi]
    return tot, comp


TEAM = [("Leno","GK","FUL"),("Verbruggen","GK","BHA"),("Gabriel","DEF","ARS"),("Guéhi","DEF","MCI"),("Senesi","DEF","TOT"),
        ("Tarkowski","DEF","EVE"),("Mitchell","DEF","CRY"),("B.Fernandes","MID","MUN"),("Semenyo","MID","MCI"),("Rice","MID","ARS"),
        ("Bruno G.","MID","NEW"),("Anderson","MID","MCI"),("João Pedro","FWD","CHE"),("Calvert-Lewin","FWD","LEE"),("Beto","FWD","EVE")]
MATE = [("Lammens","GK","MUN"),("Phillips","GK","HUL"),("Mosquera","DEF","ARS"),("N.Williams","DEF","NFO"),("Kayode","DEF","BRE"),
        ("Virgil","DEF","LIV"),("van Ewijk","DEF","COV"),("Mbeumo","MID","MUN"),("Szoboszlai","MID","LIV"),("Stach","MID","LEE"),
        ("Gomez","MID","BHA"),("B.Fernandes","MID","MUN"),("Walle Egeli","FWD","IPS"),("Haaland","FWD","MCI"),("João Pedro","FWD","CHE")]

if __name__ == "__main__":
    squads = {"Team Claude": [mk(*s) for s in TEAM], "FPL Mate": [mk(*s) for s in MATE]}
    print("V1 vs V2 — projected points:")
    print(f"  {'squad':<12} {'V1 GW1-3':>9} {'V2 GW1-3':>9} {'V1 GW1-8':>9} {'V2 GW1-8':>9}")
    for lbl, pl in squads.items():
        print(f"  {lbl:<12} {agg(pl,'ev1',3)[0]:>9.1f} {agg(pl,'ev2',3)[0]:>9.1f} {agg(pl,'ev1',8)[0]:>9.1f} {agg(pl,'ev2',8)[0]:>9.1f}")
    print("\nDEF-line component (GW1-3), V1 vs V2 — the gap V1 inflated:")
    for which, lbl in [("ev1", "V1"), ("ev2", "V2")]:
        td = agg(squads["Team Claude"], which, 3)[1]["DEF"]; md = agg(squads["FPL Mate"], which, 3)[1]["DEF"]
        print(f"  {lbl}: Team {td:.1f}  Mate {md:.1f}  gap {td-md:+.1f}")
