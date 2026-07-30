#!/usr/bin/env python3
"""
weekly_report.py — GW1 Santa Claude output under the wired-in continuous xG engine.
compute_ev now routes fixture difficulty through fixture_ratings.get_multiplier
(the old 3-tier lookup survives only as engine='old' for the before/after diff).
"""
from __future__ import annotations
import pandas as pd, numpy as np
import squad_engine as SE, fixture_ratings as FR

GWS = list(range(1, 9))
state = SE.build_squad()
players = state["players"]


def oppcode(team, gw):
    o, cnt = SE.opp(team, gw)
    if not cnt: return "--"
    return ("@" if not SE.get_home(team, gw) else "") + (o or "--")


def ev(p, gw, engine="new"):
    return SE.compute_ev(p, gw, state, engine=engine)


def mkc(r):
    return {"name": r.web_name, "position": r.pos, "team": r.team_name, "price": float(r.price),
            "form_ev": float(r.pts_start), "p_start_base": float(r.P_start) if pd.notna(r.P_start) else 0.8,
            "code": int(r.code) if pd.notna(r.code) else None, "mean_min": 82, "yellow_cards": 0,
            "yellow_card_rate": 0.10, "is_starter": True, "bench_order": 0}


def sec(t): print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)

# ---------------------------------------------------------------- 1. EV table
sec("1. EV(player, GW) — 15 squad players, GW1-8 (NEW engine, p_start applied)")
print(f"  {'player':>13} {'pos':>3} " + " ".join(f"GW{g}" for g in GWS) + "   mean")
for p in sorted(players, key=lambda x: -np.mean([ev(x, g) for g in GWS])):
    row = [ev(p, g) for g in GWS]
    print(f"  {p['name']:>13} {p['position']:>3} " + " ".join(f"{v:4.1f}" for v in row) + f"   {np.mean(row):4.2f}")
print("  fixtures:")
for p in players[:1] + [x for x in players if x["name"] in ("Haaland", "B.Fernandes", "Virgil")]:
    print(f"    {p['name']:>13} ({p['team']}): " + " ".join(f"{oppcode(p['team'], g):>5}" for g in GWS))

# ---------------------------------------------------------------- 2. captain
sec("2. GW1 CAPTAIN RECOMMENDATION (new engine)")
cands = sorted([(p, ev(p, 1)) for p in players if SE.get_p_starts(p, 1, 1) >= 0.85], key=lambda x: -x[1])
for i, (p, e) in enumerate(cands[:4]):
    tag = "  <- CAPTAIN" if i == 0 else ("  <- vice" if i == 1 else "")
    print(f"  {p['name']:>13} EV {e:4.2f}  {p['team']} vs {oppcode(p['team'], 1)}{tag}")

# ---------------------------------------------------------------- 3. transfer candidates
sec("3. TOP 3 TRANSFER CANDIDATES PER POSITION (new engine, sum EV GW1-8)")
M = SE.M.reset_index()
pool = M[(M.status == "a") & (M.pts_start.notna()) & (M.n60 >= 10)].copy()
for pos in ["GK", "DEF", "MID", "FWD"]:
    rows = []
    for r in pool[pool.pos == pos].itertuples():
        c = mkc(r); rows.append((c, sum(ev(c, g) for g in GWS)))
    rows.sort(key=lambda x: -x[1])
    print(f"  {pos}:")
    for c, tot in rows[:3]:
        print(f"    {c['name']:>14} ({c['team']}) £{c['price']:>4.1f}  8-GW EV {tot:5.1f}  ({tot/8:.2f}/gw)")

# ---------------------------------------------------------------- 4. promoted attacking value
sec("4. HULL / COVENTRY / IPSWICH — high-value attacking fixtures? (FWD multiplier, all 20 clubs)")
rank = sorted(FR.RATINGS.keys(), key=lambda c: -FR.get_multiplier(c, "FWD", None, True))
for i, c in enumerate(rank, 1):
    m = FR.get_multiplier(c, "FWD", None, True)
    star = "  <== promoted, MUST-TARGET" if c in ("HUL", "COV", "IPS") else ""
    if i <= 6 or c in ("HUL", "COV", "IPS"):
        print(f"  {i:>2}. {c}  FWD x{m:.2f}{star}")
hci = all(FR.get_multiplier(c, "FWD", None, True) >= 1.20 for c in ("HUL", "COV", "IPS"))
print(f"  -> Hull, Coventry, Ipswich all >=1.20 attacking multiplier: {'CONFIRMED' if hci else 'NO'}")

# ---------------------------------------------------------------- 5. hardest attacking fixture
sec("5. ARSENAL AWAY — hardest attacking fixture? (FWD multiplier, home & away, all clubs)")
allfx = []
for c in FR.RATINGS:
    for h in (True, False):
        allfx.append((c, h, FR.get_multiplier(c, "FWD", None, h)))
allfx.sort(key=lambda x: x[2])
for c, h, m in allfx[:5]:
    where = "away @" if not h else "home vs"
    print(f"  FWD {where} {c}: x{m:.2f}")
hard = allfx[0]
print(f"  -> hardest attacking fixture = {'away @ ' if not hard[1] else 'home vs '}{hard[0]} (x{hard[2]:.2f}): "
      f"{'CONFIRMED Arsenal away' if hard[0]=='ARS' and not hard[1] else 'NOT Arsenal away'}")

# ---------------------------------------------------------------- 6. new vs old, flag deltas
sec("6. SQUAD RE-EVALUATION — mean GW1-8 EV, NEW vs OLD 3-tier (flag |Δ| > 0.3/gw)")
print(f"  {'player':>13} {'pos':>3} {'new':>5} {'old':>5} {'Δ/gw':>6}  flag")
for p in sorted(players, key=lambda x: -abs(np.mean([ev(x, g, 'new') - ev(x, g, 'old') for g in GWS]))):
    new = np.mean([ev(p, g, "new") for g in GWS]); old = np.mean([ev(p, g, "old") for g in GWS])
    d = new - old
    print(f"  {p['name']:>13} {p['position']:>3} {new:>5.2f} {old:>5.2f} {d:>+6.2f}  "
          + ("** MOST-AFFECTED" if abs(d) > 0.3 else ""))

# ---------------------------------------------------------------- 7. validation through EV
sec("7. FOUR VALIDATION MULTIPLIERS -> full EV propagation (GW1)")
konsa = mkc(M[M.web_name == "Konsa"].iloc[0])
munoz = next(p for p in players if p["name"] == "Muñoz")
fdo = next(p for p in players if p["name"] == "B.Fernandes")
zubi = next(p for p in players if p["name"] == "Zubimendi")


def prop(p, opp, home, label, expect):
    m = FR.get_multiplier(opp, p["position"], p.get("code"), home)
    e = p["form_ev"] * m * p["p_start_base"]
    print(f"  {label:<26} mult x{m:.2f}  x form {p['form_ev']:.2f}  x P(st) {p['p_start_base']:.2f}  = EV {e:.2f}   [{expect}]")


prop(konsa, "HUL", True, "Konsa vs Hull", "HIGH mult -> lifted EV")
prop(munoz, "ARS", False, "Muñoz away @ Arsenal", "LOW mult -> suppressed EV")
prop(fdo, "IPS", True, "Fernandes vs Ipswich", "HIGH creative-MID mult")
print("  Zubimendi (fixture immunity) across opponents:")
for o in ["HUL", "EVE", "ARS", "MCI"]:
    m = FR.get_multiplier(o, zubi["position"], zubi.get("code"), True)
    print(f"    vs {o}: x{m:.2f}")
zr = [FR.get_multiplier(o, zubi["position"], zubi.get("code"), True) for o in FR.RATINGS]
print(f"    -> range x{min(zr):.2f}-{max(zr):.2f} (spread {max(zr)-min(zr):.2f}) = {'near-flat, immune CONFIRMED' if max(zr)-min(zr) < 0.6 else 'not flat'}")
