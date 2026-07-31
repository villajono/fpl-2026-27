#!/usr/bin/env python3
"""Definitive GW1-3 pre-season squad comparison: per-player weekly EV + role, weekly totals
with auto-sub broken out. All model corrections + human overrides applied. Outputs JSON."""
from __future__ import annotations
import json, math, sys
import ev_v2 as V, squad_engine as SE

nxt = V._nxt; ID2SH = SE.ID2SH; FX = SE.FX
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}; INV = {v: k for k, v in POSN.items()}
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(range(1, 4))].itertuples():
    FIX[ID2SH[r.team_h]][r.event] = (ID2SH[r.team_a], True)
    FIX[ID2SH[r.team_a]][r.event] = (ID2SH[r.team_h], False)

# human overrides (nailed-ness the data can't derive), incl. your live Maguire 0.95
V.P60_OVR.update({"Mosquera": 0.95, "Lammens": 0.95, "Maguire": 0.95, "McNally": 0.0, "Bassette": 0.0})


def code(nm, pos, team):
    m = nxt[(nxt.web_name == nm) & (nxt.element_type == INV[pos]) & (nxt.team_name == team)]
    return int((m.iloc[0] if len(m) else nxt[nxt.web_name == nm].iloc[0]).code)


def build(defn):
    pl = []
    for nm, pos, team in defn:
        c = code(nm, pos, team); mp = V.get_minutes_probs(c, nm)
        ev = [round(V.compute_ev_v2(c, nm, pos, team, *FIX[team][g]), 2) if FIX[team].get(g) else None
              for g in range(1, 4)]
        opp = [(f"{FIX[team][g][0]} ({'H' if FIX[team][g][1] else 'A'})" if FIX[team].get(g) else "-")
               for g in range(1, 4)]
        pl.append(dict(name=nm, pos=pos, team=team, ev=ev, opp=opp,
                       pstart=round(mp["p60"], 2), pzero=max(0.0, 1 - mp["p60"] - mp["p_cameo"])))
    return pl


def analyse(pl):
    for p in pl:
        p["role"] = [None, None, None]
    weekly = []
    for gi in range(3):
        gk = max([p for p in pl if p["pos"] == "GK"], key=lambda p: p["ev"][gi])
        D = sorted([p for p in pl if p["pos"] == "DEF"], key=lambda p: -p["ev"][gi])
        M = sorted([p for p in pl if p["pos"] == "MID"], key=lambda p: -p["ev"][gi])
        Fw = sorted([p for p in pl if p["pos"] == "FWD"], key=lambda p: -p["ev"][gi])
        best = None
        for d in range(3, 6):
            for m in range(2, 6):
                f = 10 - d - m
                if 1 <= f <= 3 and len(D) >= d and len(M) >= m and len(Fw) >= f:
                    xi = [gk] + D[:d] + M[:m] + Fw[:f]; s = sum(p["ev"][gi] for p in xi)
                    if best is None or s > best[0]: best = (s, xi)
        xi_ev, xi = best
        capt = max(xi, key=lambda p: p["ev"][gi])
        for p in xi: p["role"][gi] = "S"
        capt["role"][gi] = "C"
        bench = sorted([p for p in pl if p["pos"] != "GK" and p not in xi], key=lambda p: -p["ev"][gi])
        for p in bench: p["role"][gi] = "B"
        lam = sum(p["pzero"] for p in xi if p["pos"] != "GK")
        auto = 0.0
        for j, p in enumerate(bench[:3]):
            pge = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(j + 1))
            auto += pge * p["ev"][gi]
        weekly.append(dict(gw=gi + 1, xi=round(xi_ev, 1), cap=round(capt["ev"][gi], 1),
                           captain=capt["name"], auto=round(auto, 1),
                           total=round(xi_ev + capt["ev"][gi] + auto, 1)))
    return weekly


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

out = {"squads": {}}
for lbl, defn in [("Santa Claude", SANTA), ("FPL Mate", MATE), ("Andy (LTFPL)", ANDY)]:
    pl = build(defn); weekly = analyse(pl)
    out["squads"][lbl] = dict(
        players=[dict(name=p["name"], pos=p["pos"], team=p["team"], ev=p["ev"],
                      opp=p["opp"], role=p["role"], pstart=p["pstart"]) for p in pl],
        weekly=weekly, total=round(sum(w["total"] for w in weekly), 1))

json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for lbl, s in out["squads"].items():
    print(f'{lbl:<16} GW1-3 total {s["total"]:.1f}  ' +
          "  ".join(f'GW{w["gw"]}:{w["total"]:.1f}(xi{w["xi"]:.0f}+c{w["cap"]:.0f}+a{w["auto"]:.1f})' for w in s["weekly"]))
