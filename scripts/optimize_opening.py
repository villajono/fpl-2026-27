#!/usr/bin/env python3
"""
optimize_opening.py — re-optimise the 15 for the GW1-8 pre-wildcard window.
Objective = expected points of the BEST LEGAL XI fieldable each week (rotation /
fixture-flexibility) + auto-sub cover (bench valued by P(a starter blanks)), over
GW1-8, under the £100 cap, 2/5/5/3, max 3 per club. No cheap-bench thumb on the
scale — bench slots earn their place on auto-sub + rotation EV or they don't.
"""
from __future__ import annotations
import math, pandas as pd, numpy as np
import squad_engine as SE, fixture_ratings as FR

FX, ID2SH = SE.FX, SE.ID2SH
GWS = list(range(1, 9))
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(GWS)].itertuples():
    h, a = ID2SH[r.team_h], ID2SH[r.team_a]
    FIX[h][r.event] = (a, True); FIX[a][r.event] = (h, False)

M = SE.M
def mkc(r):
    return dict(name=r.web_name, pos=r.pos, team=r.team_name, price=float(r.price),
                form=float(r.pts_start), pstart=float(r.P_start) if pd.notna(r.P_start) else 0.8,
                code=int(r.code) if pd.notna(r.code) else None)

pool = {}
for r in M.reset_index().itertuples():
    if r.status == "a" and pd.notna(r.pts_start) and r.n60 >= 10:
        pool[r.web_name] = mkc(r)
# ensure every current squad player exists in the pool (van Ewijk has no M row)
for p in SE.build_squad()["players"]:
    if p["name"] not in pool:
        pool[p["name"]] = dict(name=p["name"], pos=p["position"], team=p["team"], price=p["price"],
                               form=p["form_ev"], pstart=p["p_start_base"], code=p.get("code"))

names = list(pool)
IDX = {n: i for i, n in enumerate(names)}
N = len(names)
PR = np.array([pool[n]["price"] for n in names])
POS = [pool[n]["pos"] for n in names]
CLUB = [pool[n]["team"] for n in names]
PTS = np.zeros((N, 8)); PP = np.zeros((N, 8)); EV = np.zeros((N, 8))
for i, n in enumerate(names):
    p = pool[n]
    for gi, gw in enumerate(GWS):
        fx = FIX[p["team"]].get(gw)
        if not fx: PTS[i, gi] = 0; PP[i, gi] = 0; continue
        opp, home = fx
        mult = FR.get_multiplier(opp, p["pos"], p["code"], home)
        pp = SE.AVAIL_OVR.get(p["name"], {}).get(gw, p["pstart"])
        PTS[i, gi] = p["form"] * mult; PP[i, gi] = pp; EV[i, gi] = p["form"] * mult * pp


def week_value(idxs, gw):
    gk = [i for i in idxs if POS[i] == "GK"]
    sg = max(gk, key=lambda i: EV[i, gw]); bg = [i for i in gk if i != sg][0]
    D = sorted([i for i in idxs if POS[i] == "DEF"], key=lambda i: -EV[i, gw])
    Mi = sorted([i for i in idxs if POS[i] == "MID"], key=lambda i: -EV[i, gw])
    Fw = sorted([i for i in idxs if POS[i] == "FWD"], key=lambda i: -EV[i, gw])
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3 and len(D) >= d and len(Mi) >= m and len(Fw) >= f:
                xi = D[:d] + Mi[:m] + Fw[:f]
                s = EV[sg, gw] + sum(EV[i, gw] for i in xi)
                if best is None or s > best[0]: best = (s, set(xi))
    xi_ev, xi = best
    cap = max(EV[i, gw] for i in xi)                          # captain doubles: add one more copy of best XI EV
    bench = sorted([i for i in idxs if POS[i] != "GK" and i not in xi], key=lambda i: -EV[i, gw])
    lam = sum(1 - PP[i, gw] for i in xi)                      # expected blanks among XI outfield
    auto = 0.0
    for j, bi in enumerate(bench[:3]):
        pge = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(j + 1))
        auto += pge * EV[bi, gw]                              # bench player's own EV when activated
    auto += (1 - PP[sg, gw]) * EV[bg, gw]                     # GK auto-sub
    return xi_ev + cap + auto


def raw(idxs):                     # pure GW1-8 expected points, no budget penalty
    return sum(week_value(idxs, g) for g in range(8))


def value(idxs):                   # search objective: raw minus a hard over-budget penalty
    return raw(idxs) - 1000 * max(0, PR[idxs].sum() - 100)


def club_ok(idxs):
    c = {}
    for i in idxs:
        c[CLUB[i]] = c.get(CLUB[i], 0) + 1
        if c[CLUB[i]] > 3: return False
    return True


LOCK = set(); BAN = {IDX["Haaland"]}          # Team Claude: no Haaland, no forced locks


def climb(start):
    b = list(start); bv = value(b)
    for _ in range(60):
        mv = None; bg = bv
        for si, s in enumerate(b):
            if s in LOCK: continue
            for c in range(N):
                if c in b or POS[c] != POS[s] or c in BAN: continue
                trial = b[:si] + [c] + b[si + 1:]
                if PR[trial].sum() > 100 or not club_ok(trial): continue
                v = value(trial)
                if v > bg: bg = v; mv = (si, c)
        if not mv: break
        b[mv[0]] = mv[1]; bv = bg
    return b, bv


cur = [IDX[p["name"]] for p in SE.build_squad()["players"]]
seed = [i for i in cur if i not in BAN]        # drop Haaland, seed a cheap FWD, let the search spend the freed £
seed.append(sorted([c for c in range(N) if POS[c] == "FWD" and c not in seed and c not in BAN], key=lambda i: PR[i])[0])
rng = np.random.default_rng(0)
best, bestval = climb(seed)
for _ in range(12):                # basin-hopping restarts to escape local optima
    pert = list(best)
    for _ in range(3):             # random feasible within-position kicks
        si = int(rng.integers(len(pert)))
        if pert[si] in LOCK: continue
        opts = [c for c in range(N) if c not in pert and POS[c] == POS[pert[si]] and c not in BAN]
        if opts:
            c = int(rng.choice(opts)); trial = pert[:si] + [c] + pert[si + 1:]
            if PR[trial].sum() <= 100 and club_ok(trial): pert = trial
    cand, cv = climb(pert)
    if cv > bestval: best, bestval = cand, cv


def report(idxs, label, legal):
    order = sorted(idxs, key=lambda i: -EV[i].mean())
    xi = set(order[:11])
    print(f"\n{label}: GW1-8 pts {raw(idxs):.1f} | £{PR[idxs].sum():.1f}m {'(LEGAL)' if legal else '(OVER CAP — cannot field)'}")
    for i in order:
        print(f"  {'XI ' if i in xi else 'BEN'} {names[i][:15]:>15} {POS[i]:>3} {CLUB[i]:>4} £{PR[i]:>4.1f}  mean EV {EV[i].mean():.2f}")


report(cur, "CURRENT SQUAD", PR[cur].sum() <= 100)
report(best, "OPTIMISED FOR GW1-8", PR[best].sum() <= 100)
print(f"\nCHANGES: out {[names[i] for i in cur if i not in best]}  ->  in {[names[i] for i in best if i not in cur]}")
print(f"Best LEGAL squad = {raw(best):.1f} pts (£{PR[best].sum():.1f}m) vs current (£{PR[cur].sum():.1f}m, over cap) "
      f"{raw(cur):.1f} pts  ->  re-optimising is worth {raw(best)-raw(cur):+.1f} pts over GW1-8 AND gets legal.")
bo = sorted(best, key=lambda i: EV[i].mean())
benchies = [i for i in bo if POS[i] != "GK"][:3] + [i for i in bo if POS[i] == "GK"][:1]
print("\nOPTIMISED BENCH (does it reproduce the graduated-bench heuristic?):")
for i in sorted(benchies, key=lambda i: -EV[i].mean()):
    tier = "starter-level" if EV[i].mean() >= 4.0 else ("regular" if EV[i].mean() >= 3.0 else "dud/enabler")
    print(f"  {names[i][:15]:>15} {POS[i]:>3} £{PR[i]:>4.1f}  mean EV {EV[i].mean():.2f}  -> {tier}")
