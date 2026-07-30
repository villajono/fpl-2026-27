#!/usr/bin/env python3
"""xi_compare.py — GW1-3 head-to-head: Team Claude vs FPL Mate, points attributed per player."""
from __future__ import annotations
import math, pandas as pd, numpy as np
import squad_engine as SE, fixture_ratings as FR

FX, ID2SH = SE.FX, SE.ID2SH
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GWS = [1, 2, 3]
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(GWS)].itertuples():
    h, a = ID2SH[r.team_h], ID2SH[r.team_a]
    FIX[h][r.event] = (a, True); FIX[a][r.event] = (h, False)

nxt = pd.read_csv("../data/raw/players_2026-27.csv", low_memory=False)
pr25 = pd.read_csv("../data/raw/players_raw_2025-26.csv", low_memory=False)
g25 = pd.read_csv("../data/raw/merged_gw_2025-26.csv", low_memory=False)
g25["minutes"] = pd.to_numeric(g25.minutes, errors="coerce").fillna(0)
g25["total_points"] = pd.to_numeric(g25.total_points, errors="coerce").fillna(0)
code2id = dict(zip(pr25.code, pr25.id))
OVR = {"Walle Egeli": dict(form=2.8, pstart=0.45), "Phillips": dict(form=3.0, pstart=0.60),
       "Mosquera": dict(pstart=0.92), "van Ewijk": dict(form=3.6, pstart=0.95)}


def nailed(mm, n60):
    p = 0.93 if mm >= 88 else 0.90 if mm >= 82 else 0.84 if mm >= 78 else 0.70 if mm >= 73 else 0.55
    return round(p * (0.85 if n60 < 12 else 1.0), 2)


def build(web, pos, team):
    m = nxt[(nxt.web_name == web) & (nxt.element_type == {v: k for k, v in POSN.items()}[pos]) & (nxt.team_name == team)]
    r = (m.iloc[0] if len(m) else nxt[nxt.web_name == web].iloc[0]); code = int(r.code)
    el = code2id.get(code); sub = g25[g25.element == el] if el is not None else g25.iloc[0:0]
    app = sub[sub.minutes >= 60]; n60 = len(app); o = OVR.get(web, {})
    form = o.get("form", app.total_points.mean() if n60 else 3.0)
    pstart = o.get("pstart", nailed(app.minutes.mean(), n60) if n60 else 0.65)
    p = dict(name=web, pos=pos, team=team, price=r.now_cost / 10, code=code, form=form, pstart=pstart, ev=[])
    for gw in GWS:
        fx = FIX[team].get(gw)
        p["ev"].append(form * FR.get_multiplier(*(fx[0], pos, code, fx[1])) * pstart if fx else 0.0)
    return p


def attribute(players):
    """GW1-3 points attributed per player: XI EV + captain double (best MID/FWD) + auto-sub share.
    Also returns components: base XI by line, captain premium, auto-sub — captaincy split out."""
    con = {p["name"]: 0.0 for p in players}; started = {p["name"]: 0 for p in players}
    comp = {"GK": 0.0, "DEF": 0.0, "MID": 0.0, "FWD": 0.0, "captain": 0.0, "autosub": 0.0}
    for gi in range(3):
        gks = [p for p in players if p["pos"] == "GK"]
        sg = max(gks, key=lambda p: p["ev"][gi]); bg = [p for p in gks if p is not sg][0]
        D = sorted([p for p in players if p["pos"] == "DEF"], key=lambda p: -p["ev"][gi])
        Mi = sorted([p for p in players if p["pos"] == "MID"], key=lambda p: -p["ev"][gi])
        Fw = sorted([p for p in players if p["pos"] == "FWD"], key=lambda p: -p["ev"][gi])
        best = None
        for d in range(3, 6):
            for m in range(2, 6):
                f = 10 - d - m
                if 1 <= f <= 3 and len(D) >= d and len(Mi) >= m and len(Fw) >= f:
                    xi = [sg] + D[:d] + Mi[:m] + Fw[:f]; s = sum(p["ev"][gi] for p in xi)
                    if best is None or s > best[0]: best = (s, xi)
        _, xi = best
        cap = max([p for p in xi if p["pos"] in ("MID", "FWD")], key=lambda p: p["ev"][gi])
        for p in xi:
            con[p["name"]] += p["ev"][gi]; started[p["name"]] += 1; comp[p["pos"]] += p["ev"][gi]
            if p is cap: con[p["name"]] += p["ev"][gi]; comp["captain"] += p["ev"][gi]
        bench = sorted([p for p in players if p["pos"] != "GK" and p not in xi], key=lambda p: -p["ev"][gi])
        lam = sum(1 - p["pstart"] for p in xi if p["pos"] != "GK")
        for j in range(min(3, len(bench))):
            pge = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(j + 1))
            con[bench[j]["name"]] += pge * bench[j]["ev"][gi]; comp["autosub"] += pge * bench[j]["ev"][gi]
        con[bg["name"]] += (1 - sg["pstart"]) * bg["ev"][gi]; comp["autosub"] += (1 - sg["pstart"]) * bg["ev"][gi]
    return con, started, comp


TEAM = [("Leno","GK","FUL"),("Verbruggen","GK","BHA"),("Gabriel","DEF","ARS"),("Guéhi","DEF","MCI"),("Senesi","DEF","TOT"),
        ("Tarkowski","DEF","EVE"),("Mitchell","DEF","CRY"),("B.Fernandes","MID","MUN"),("Semenyo","MID","MCI"),("Rice","MID","ARS"),
        ("Bruno G.","MID","NEW"),("Anderson","MID","MCI"),("João Pedro","FWD","CHE"),("Calvert-Lewin","FWD","LEE"),("Beto","FWD","EVE")]
MATE = [("Lammens","GK","MUN"),("Phillips","GK","HUL"),("Mosquera","DEF","ARS"),("N.Williams","DEF","NFO"),("Kayode","DEF","BRE"),
        ("Virgil","DEF","LIV"),("van Ewijk","DEF","COV"),("Mbeumo","MID","MUN"),("Szoboszlai","MID","LIV"),("Stach","MID","LEE"),
        ("Gomez","MID","BHA"),("B.Fernandes","MID","MUN"),("Walle Egeli","FWD","IPS"),("Haaland","FWD","MCI"),("João Pedro","FWD","CHE")]


def show(label, squad):
    pl = [build(*s) for s in squad]; con, st, comp = attribute(pl)
    print(f"\n{'='*66}\n{label}  (GW1-3 attributed points)\n{'='*66}")
    print(f"  {'player':>14} {'pos':>3} {'£':>5} {'st':>2} {'GW1-3 pts':>9}")
    for p in sorted(pl, key=lambda x: (["GK","DEF","MID","FWD"].index(x["pos"]), -con[x["name"]])):
        print(f"  {p['name']:>14} {p['pos']:>3} £{p['price']:>4.1f} {st[p['name']]:>2} {con[p['name']]:>9.1f}")
    print(f"  {'TOTAL':>14} {'':>3} {'':>5} {'':>2} {sum(con.values()):>9.1f}")
    return con, comp, sum(con.values())


ct, kt, tt = show("TEAM CLAUDE (yours)", TEAM)
cm, km, tm = show("FPL MATE (his)", MATE)
print(f"\n{'='*66}\nWHERE THE GW1-3 GAP COMES FROM  (captaincy split out)\n{'='*66}")
print(f"  {'component':>16} {'Team':>7} {'Mate':>7} {'diff':>7}")
for k in ["GK", "DEF", "MID", "FWD", "captain", "autosub"]:
    lbl = {"DEF":"DEF (base XI)","MID":"MID (base XI)","FWD":"FWD (base XI)","captain":"captain premium","autosub":"auto-sub cover"}.get(k, k)
    print(f"  {lbl:>16} {kt[k]:>7.1f} {km[k]:>7.1f} {kt[k]-km[k]:>+7.1f}")
print(f"  {'TOTAL':>16} {tt:>7.1f} {tm:>7.1f} {tt-tm:>+7.1f}")
