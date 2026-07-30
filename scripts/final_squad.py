#!/usr/bin/env python3
"""final_squad.py — the locked V2 squad (human-adjusted). Reproducible projection."""
from __future__ import annotations
import ev_v2_compare as C

FINAL = [("Sánchez","GK","CHE"),("Leno","GK","FUL"),
         ("Senesi","DEF","TOT"),("Van Hecke","DEF","TOT"),("Romero","DEF","TOT"),("Calafiori","DEF","ARS"),("Van den Berg","DEF","BRE"),
         ("Mbeumo","MID","MUN"),("Anderson","MID","MCI"),("Enzo","MID","CHE"),("Sarr","MID","CRY"),("Gomez","MID","BHA"),
         ("Haaland","FWD","MCI"),("Thiago","FWD","BRE"),("Mateta","FWD","CRY")]

pl = [C.mk(*s) for s in FINAL]
price = {p["name"]: p for p in pl}
prices = {("Sánchez",5.0),("Leno",4.5),("Senesi",6.0),("Van Hecke",5.0),("Romero",5.0),("Calafiori",5.5),
          ("Van den Berg",5.0),("Mbeumo",8.0),("Anderson",6.5),("Enzo",7.0),("Sarr",6.5),("Gomez",5.0),
          ("Haaland",15.5),("Thiago",8.0),("Mateta",6.5)}
PRICE = dict(prices); total = sum(PRICE.values())

t8, comp = C.agg(pl, "ev2", 8); t3, _ = C.agg(pl, "ev2", 3)
print(f"LOCKED V2 SQUAD — £{total:.1f}m (ITB £{100-total:.1f}m) | V2 GW1-3 {t3:.1f} | V2 GW1-8 {t8:.1f}")
for pos in ["GK", "DEF", "MID", "FWD"]:
    row = [f"{p['name']} £{PRICE[p['name']]:.1f} ({p['team']})" for p in pl if p["pos"] == pos]
    print(f"  {pos}: " + " · ".join(row))
# GW1 XI + captain
best = None
for d in range(3, 6):
    for m in range(2, 6):
        f = 10 - d - m
        if not (1 <= f <= 3): continue
        gk = max([p for p in pl if p["pos"] == "GK"], key=lambda p: p["ev2"][0])
        D = sorted([p for p in pl if p["pos"] == "DEF"], key=lambda p: -p["ev2"][0])[:d]
        M = sorted([p for p in pl if p["pos"] == "MID"], key=lambda p: -p["ev2"][0])[:m]
        F = sorted([p for p in pl if p["pos"] == "FWD"], key=lambda p: -p["ev2"][0])[:f]
        xi = [gk] + D + M + F
        if len(D) == d and len(M) == m and len(F) == f:
            s = sum(p["ev2"][0] for p in xi)
            if best is None or s > best[0]: best = (s, xi, (d, m, f))
s, xi, form = best
cap = max([p for p in xi if p["pos"] in ("MID", "FWD")], key=lambda p: p["ev2"][0])
print(f"\nGW1: {form[0]}-{form[1]}-{form[2]}  captain {cap['name']} (EV {cap['ev2'][0]:.1f})")
print("  XI: " + ", ".join(p["name"] for p in xi))
print("  Bench: " + ", ".join(p["name"] for p in pl if p not in xi))
