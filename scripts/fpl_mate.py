#!/usr/bin/env python3
"""fpl_mate.py — evaluate the FPL Mate squad vs Santa Claude vs Team Claude over GW1-8."""
from __future__ import annotations
import math, pandas as pd, numpy as np
import squad_engine as SE, fixture_ratings as FR

FX, ID2SH = SE.FX, SE.ID2SH
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GWS = list(range(1, 9))
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

# circumstantial / no-PL-data overrides (form=pts/start, pstart=P(start))
OVR = {
    "Walle Egeli": dict(form=2.8, pstart=0.45, flag="PROMOTED(IPS) circumstantial/rotation FWD, no PL data"),
    "Phillips":    dict(form=3.0, pstart=0.60, flag="PROMOTED(HUL) GK, start uncertain, no PL data"),
    "Mosquera":    dict(pstart=0.92, flag="NAILED — Saliba out months (back surgery); starts ARS CB through the window"),
    "van Ewijk":   dict(form=3.6, pstart=0.95, flag="PROMOTED(COV) £4.0 enabler, no PL data"),
}


def data25(code):
    el = code2id.get(code)
    if el is None: return None
    sub = g25[g25.element == el]
    if not len(sub): return None
    app = sub[sub.minutes >= 60]; n60 = len(app)
    return dict(n60=n60, pts_start=(app.total_points.mean() if n60 else 0.0),
                P_start=round(n60 / 38, 2), mean_min=(app.minutes.mean() if n60 else 0.0),
                total25=sub.total_points.sum())


def nailedness(mean_min, n60):
    """P(start) from minutes-per-start (nailed-ness), not game count. High min/start = first
    choice even if games were missed to injury; low min = genuine rotation/cameo."""
    p = 0.93 if mean_min >= 88 else 0.90 if mean_min >= 82 else 0.84 if mean_min >= 78 else 0.70 if mean_min >= 73 else 0.55
    if n60 < 12: p *= 0.85          # chronic-availability haircut for very few starts
    return round(p, 2)


def resolve(web, pos, team):
    m = nxt[(nxt.web_name == web) & (nxt.element_type == {v: k for k, v in POSN.items()}[pos]) & (nxt.team_name == team)]
    if not len(m): m = nxt[nxt.web_name == web]
    return m.iloc[0]


def build(web, pos, team):
    r = resolve(web, pos, team); code = int(r.code)
    d = data25(code); o = OVR.get(web, {})
    form = o.get("form", d["pts_start"] if d and d["pts_start"] else 3.0)
    p_old = d["P_start"] if d else None
    pstart = o.get("pstart", nailedness(d["mean_min"], d["n60"]) if d else 0.65)
    flag = o.get("flag", "")
    if not flag and d and d["mean_min"] < 73: flag = f"GENUINE ROTATION (mean {int(d['mean_min'])}min)"
    if team in ("COV", "HUL", "IPS") and "PROMOTED" not in flag: flag = (flag + " PROMOTED").strip()
    p = dict(name=web, pos=pos, team=team, price=r.now_cost / 10, code=code, form=form, pstart=pstart,
             pts25=int(r.total_points), P_start=(d["P_start"] if d else None), P_old=p_old,
             mean_min=(int(d["mean_min"]) if d else None), flag=flag)
    p["ev"] = []; p["mult"] = []
    for gw in GWS:
        fx = FIX[team].get(gw)
        if not fx: p["ev"].append(0.0); p["mult"].append(0.0); continue
        opp, home = fx; mlt = FR.get_multiplier(opp, pos, code, home)
        p["mult"].append(mlt); p["ev"].append(form * mlt * pstart)
    p["fix8"] = np.mean([m for m in p["mult"] if m])
    return p


def squad_ev(players, weeks=8):
    """best legal XI each week + captain + auto-sub cover; returns (total, xi_by_gw, cap_gw1)."""
    tot = 0.0; xi_by = []; cap1 = None
    for gi, gw in enumerate(GWS[:weeks]):
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
                    if best is None or s > best[0]: best = (s, xi, (d, m, f))
        s, xi, form = best
        cap = max(xi, key=lambda p: p["ev"][gi])
        bench = sorted([p for p in players if p["pos"] != "GK" and p not in xi], key=lambda p: -p["ev"][gi])
        lam = sum(1 - p["pstart"] for p in xi if p["pos"] != "GK")
        auto = sum((1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(j + 1))) * bench[j]["ev"][gi]
                   for j in range(min(3, len(bench))))
        auto += (1 - sg["pstart"]) * bg["ev"][gi]
        tot += s + cap["ev"][gi] + auto
        xi_by.append((gw, form, cap["name"], [p["name"] for p in xi if p["pos"] != "GK"], sg["name"]))
        if gw == 1: cap1 = (cap["name"], cap["ev"][gi], cap["team"])
    return tot, xi_by, cap1


# ---------------- FPL Mate squad ----------------
MATE = [("Lammens","GK","MUN"),("Phillips","GK","HUL"),
        ("Mosquera","DEF","ARS"),("N.Williams","DEF","NFO"),("Kayode","DEF","BRE"),("Virgil","DEF","LIV"),("van Ewijk","DEF","COV"),
        ("Mbeumo","MID","MUN"),("Szoboszlai","MID","LIV"),("Stach","MID","LEE"),("Gomez","MID","BHA"),("B.Fernandes","MID","MUN"),
        ("Walle Egeli","FWD","IPS"),("Haaland","FWD","MCI"),("João Pedro","FWD","CHE")]
mate = [build(*m) for m in MATE]

NEW = ["Lammens","Phillips","Mosquera","N.Williams","Kayode","Mbeumo","Szoboszlai","Stach","Gomez","Walle Egeli"]
print("="*100); print("PLAYER LOOKUP (2026-27)"); print("="*100)
print(f"{'player':>13} {'club':>4} {'pos':>3} {'£':>5} {'pts25':>5} {'P(st)':>5} {'fix8':>5}  flags")
for p in mate:
    if p["name"] in NEW:
        ps = f"{p['P_start']:.2f}" if p["P_start"] is not None else " n/a"
        print(f"{p['name']:>13} {p['team']:>4} {p['pos']:>3} £{p['price']:>4.1f} {p['pts25']:>5} {ps:>5} {p['fix8']:>5.2f}  {p['flag']}")

print("\n" + "="*100); print(f"FPL MATE SQUAD — GW1-8 EV  (total £{sum(p['price'] for p in mate):.1f}m)"); print("="*100)
print(f"{'player':>13} {'pos':>3} " + " ".join(f"GW{g}" for g in GWS) + "  tot")
for p in sorted(mate, key=lambda x: -sum(x["ev"])):
    print(f"{p['name']:>13} {p['pos']:>3} " + " ".join(f"{v:4.1f}" for v in p["ev"]) + f" {sum(p['ev']):5.1f}")
tot_m, xi_m, cap_m = squad_ev(mate)
print(f"\nGW1 CAPTAIN: {cap_m[0]} (EV {cap_m[1]:.2f}, {cap_m[2]} vs {FIX[cap_m[2]].get(1,('?',))[0]})")
print("PROJECTED XI BY GAMEWEEK (formation | captain):")
for gw, form, cap, xi, gk in xi_m:
    print(f"  GW{gw}: {form[0]}-{form[1]}-{form[2]}  C:{cap:<12} GK:{gk:<11} | " + ", ".join(xi))
print(f"\nTOTAL GW1-8 PROJECTED POINTS: {tot_m:.1f}")

# ---------------- comparison ----------------
SANTA = [(p["name"], p["position"], p["team"]) for p in SE.build_squad()["players"]]
santa = [build(n, po, t) if n not in ("Verbruggen","Leno","Beto","Muñoz","Shaw","Mitchell","Rogers","Anderson","Semenyo","Zubimendi","Virgil","van Ewijk","Haaland","João Pedro","B.Fernandes") else build(n, po, t) for (n, po, t) in SANTA]
TEAM = [("Leno","GK","FUL"),("Verbruggen","GK","BHA"),("Gabriel","DEF","ARS"),("Guéhi","DEF","MCI"),("Senesi","DEF","TOT"),
        ("Tarkowski","DEF","EVE"),("Mitchell","DEF","CRY"),("B.Fernandes","MID","MUN"),("Semenyo","MID","MCI"),("Rice","MID","ARS"),
        ("Bruno G.","MID","NEW"),("Anderson","MID","MCI"),("João Pedro","FWD","CHE"),("Calvert-Lewin","FWD","LEE"),("Beto","FWD","EVE")]
team = [build(*t) for t in TEAM]
tot_s, _, cap_s = squad_ev(santa)
tot_t, _, cap_t = squad_ev(team)
print("\n" + "="*100); print("P(START) REBUILD — minutes-per-start nailed-ness vs old n60/38"); print("="*100)
allp = {p["name"]: p for p in mate + santa + team}
print(f"  {'player':>14} {'min/st':>6} {'old P':>6} {'new P':>6}  note")
for p in sorted(allp.values(), key=lambda x: (x['pstart'] - (x['P_old'] or x['pstart']))):
    if p["P_old"] is None or abs(p["pstart"] - p["P_old"]) < 0.05: continue
    d = p["pstart"] - p["P_old"]
    print(f"  {p['name']:>14} {str(p['mean_min'])+'m':>6} {p['P_old']:>6.2f} {p['pstart']:>6.2f}  {'+' if d>0 else ''}{d:.2f} {'(was wrongly suppressed)' if d>0 else '(genuine rotation)'}")

print("\n" + "="*100); print("COMPARISON — projected points (mate WCs at GW4, so GW1-3 is his squad's real lifespan)"); print("="*100)
print(f"  {'squad':<18} {'£':>6} {'GW1-3':>7} {'GW1-8':>7}  {'GW1 captain':>14}")
for lbl, pl in [("FPL Mate", mate), ("Santa Claude", santa), ("Team Claude (you)", team)]:
    t3, _, c1 = squad_ev(pl, weeks=3); t8, _, _ = squad_ev(pl, weeks=8)
    print(f"  {lbl:<18} £{sum(p['price'] for p in pl):>5.1f} {t3:>7.1f} {t8:>7.1f}  {c1[0]:>14}")
