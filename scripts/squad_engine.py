#!/usr/bin/env python3
"""
squad_engine.py — Santa Claude weekly decision engine (Steps 1-10).
Fundamental unit: EV(player, gameweek). Everything derives from compute_ev.
PRE-SEASON STATE: no 2026-27 games yet, so form=last-season pts/start; the xG/xA,
BPS and yellow-suspension layers are WIRED but return 0 until real data arrives.
"""
from __future__ import annotations
from pathlib import Path
from itertools import product
import pandas as pd, numpy as np
import fixture_ratings as FR

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
BUDGET_CAP = 100.0   # squad budget cap (£m)
DECAY = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.40, 6: 0.25}
MULT_OLD = {  # legacy 3-tier — kept only for before/after comparison
 "DEF defensive": {"T1": 0.83, "T2": 1.0, "T3": 1.17},
 "DEF attacking": {"T1": 0.84, "T2": 1.0, "T3": 1.16},
 "MID creative":  {"T1": 0.88, "T2": 1.0, "T3": 1.12},
 "MID defensive": {"T1": 0.99, "T2": 1.0, "T3": 1.01},
 "FWD":           {"T1": 0.89, "T2": 1.0, "T3": 1.11},
 "GK":            {"T1": 0.91, "T2": 1.0, "T3": 1.09},
}
TIER = {**{c: "T1" for c in ["ARS","MCI","LIV","CHE","TOT"]},
        **{c: "T2" for c in ["MUN","AVL","NEW","BHA","EVE","NFO","CRY","LEE","BRE"]},
        **{c: "T3" for c in ["BOU","FUL","SUN","IPS","COV","HUL"]}}

# ---------- data ----------
FX = pd.read_csv(RAW / "fixtures_2026-27.csv")
T = pd.read_csv(RAW / "teams_2026-27.csv"); ID2SH = dict(zip(T.id, T.short_name))
M = pd.read_csv(RAW.parent / "outputs" / "master_candidates.csv").set_index("web_name")
PR = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
YR = {}
for r in PR.itertuples():
    s = pd.to_numeric(r.starts, errors="coerce"); y = pd.to_numeric(r.yellow_cards, errors="coerce")
    if pd.notna(s) and s >= 10 and pd.notna(y):
        YR[r.web_name] = min(y / s, 0.55)


def opp(team, gw):
    r = FX[(FX.event == gw) & ((FX.team_h == _id(team)) | (FX.team_a == _id(team)))]
    if not len(r): return None, 0
    r = r.iloc[0]; o = r.team_a if r.team_h == _id(team) else r.team_h
    return ID2SH.get(o), len(FX[(FX.event == gw) & ((FX.team_h == _id(team)) | (FX.team_a == _id(team)))])


def _id(short): return next((i for i, s in ID2SH.items() if s == short), None)


def get_home(team, gw):
    return len(FX[(FX.event == gw) & (FX.team_h == _id(team))]) > 0

# ---------- Step 1: squad state ----------
SQUAD = [  # name, pos, position_type, team, price
 ("Leno","GK","GK","FUL",4.5), ("Verbruggen","GK","GK","BHA",4.5),
 ("Virgil","DEF","DEF defensive","LIV",6.5), ("Muñoz","DEF","DEF attacking","CRY",5.5),
 ("Shaw","DEF","DEF attacking","MUN",4.5), ("Mitchell","DEF","DEF attacking","CRY",4.5),
 ("van Ewijk","DEF","DEF attacking","COV",4.0),
 ("B.Fernandes","MID","MID creative","MUN",12.0), ("Semenyo","MID","MID creative","MCI",8.5),
 ("Rogers","MID","MID creative","CHE",7.5), ("Anderson","MID","MID creative","MCI",6.5),
 ("Zubimendi","MID","MID defensive","ARS",5.5),
 ("Haaland","FWD","FWD","MCI",15.5), ("João Pedro","FWD","FWD","CHE",7.5), ("Beto","FWD","FWD","EVE",5.5),
]
OVR = {"van Ewijk": (3.6, 0.95), "Porro": (3.5, 0.82), "Cash": (3.55, 0.87), "Maddison": (4.4, 0.85)}
# WC-delayed availability (Porro rested after World Cup final)
AVAIL_OVR = {"Porro": {1: 0.2, 2: 0.45, 3: 0.75}}


def mk(name, pos, ptype, team, price):
    code = None
    if name in M.index:
        row = M.loc[name]; form = float(row.pts_start) if pd.notna(row.pts_start) else 3.0
        pst = float(row.P_start) if pd.notna(row.P_start) else 0.8
        mm = 82.0; code = int(row.code) if pd.notna(row.code) else None
    else:
        form, pst = OVR.get(name, (3.0, 0.8)); mm = 82.0
    if name in OVR: form, pst = OVR[name]
    return {"name": name, "position": pos, "position_type": ptype, "team": team, "price": price,
            "form_ev": form, "p_start_base": pst, "mean_min": mm, "yellow_cards": 0, "code": code,
            "yellow_card_rate": YR.get(name, 0.10), "is_starter": True, "bench_order": 0}


def build_squad():
    players = [mk(*s) for s in SQUAD]
    total = sum(p["price"] for p in players)
    state = {"team_id": "santa_claude", "gameweek": 1, "players": players,
             "itb": round(BUDGET_CAP - total, 1), "transfers_banked": 1, "budget_total": round(total, 1),
             "chips_available": ["wildcard1","wildcard2","freehit","benchboost","triplecap"], "chips_used": [],
             "planned_transfers": [
                 {"out": "Muñoz", "in": "Porro", "trigger_gw": 3, "trigger": "GW3-4 — Porro rested, available"},
                 {"out": "Shaw", "in": "Cash", "trigger_gw": 6, "trigger": "GW6-7 — Villa fixtures turn"},
                 {"out": "Anderson", "in": "Maddison", "trigger_gw": None, "trigger": "Wildcard — Spurs fixtures turn"}]}
    return state

# ---------- Step 3: yellow-card suspension ----------
def get_p_suspended(player, target_gw, cur_gw):
    y, rate = player["yellow_cards"], player["yellow_card_rate"]
    gb = target_gw - cur_gw
    if y == 4:
        p = rate * (1 - rate) ** (gb - 2) if gb > 1 else rate
        return min(p, 0.5)
    if y == 9:
        p = rate * (1 - rate) ** (gb - 2) if gb > 1 else rate
        return min(p * 1.5, 0.7)
    return 0.0

# ---------- Step 2: EV(player, gameweek) ----------
def get_p_starts(player, target_gw, cur_gw):
    base = player["p_start_base"]
    if player["name"] in AVAIL_OVR:
        base = AVAIL_OVR[player["name"]].get(target_gw, base)
    return base * (1 - get_p_suspended(player, target_gw, cur_gw))


def compute_ev(player, target_gw, state, apply_pstart=True, engine="new"):
    o, cnt = opp(player["team"], target_gw)
    if cnt == 0:
        return 0.0
    if engine == "new":
        mult = FR.get_multiplier(o, player["position"], player.get("code"), get_home(player["team"], target_gw))
    else:
        mult = MULT_OLD[player["position_type"]][TIER.get(o, "T2")]
    bgw = 1.8 if cnt == 2 else 1.0
    underlying_adj = 0.0   # DORMANT pre-season (xG/xA vs goals, last-4 GW) — wires in-season
    bps_adj = 0.0          # DORMANT pre-season (BPS near-miss) — wires in-season
    ev = player["form_ev"] * mult * bgw * (1 + underlying_adj + bps_adj)
    if apply_pstart:
        ev *= get_p_starts(player, target_gw, state["gameweek"])
    return ev

# ---------- Step 4: transfer value with bench cover ----------
def get_p_available(player, target_gw):
    if player["name"] in AVAIL_OVR:
        return AVAIL_OVR[player["name"]].get(target_gw, player["p_start_base"])
    return min(player["p_start_base"] + 0.05, 0.97)


def best_bench_cover(player_out, state, target_gw):
    same = [p for p in state["players"] if p["position"] == player_out["position"] and p is not player_out]
    return max(same, key=lambda p: compute_ev(p, target_gw, state), default=None)


def calc_transfer_value(p_out, p_in, state, horizon=6):
    tv = 0.0
    for off in range(1, horizon + 1):
        gw = state["gameweek"] + off; d = DECAY[off]
        ev_in = compute_ev(p_in, gw, state)
        pa = get_p_available(p_out, gw)
        ev_out = compute_ev(p_out, gw, state, apply_pstart=False)
        bc = best_bench_cover(p_out, state, gw)
        ev_bench = compute_ev(bc, gw, state) if bc else 0
        eff_out = ev_out * pa + ev_bench * (1 - pa)
        tv += (ev_in - eff_out) * d
    return tv

# ---------- Step 5: trajectory ----------
def trajectory(state, n=6):
    warn = []
    for off in range(1, n + 1):
        gw = state["gameweek"] + off
        avail = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for p in state["players"]:
            if get_p_available(p, gw) > 0.5:
                avail[p["position"]] += 1
        if avail["GK"] < 1: warn.append((gw, "CRITICAL", "No GK available"))
        if avail["DEF"] < 3: warn.append((gw, "HIGH", f"Only {avail['DEF']} DEF available (min 3)"))
        if avail["MID"] < 2: warn.append((gw, "HIGH", f"Only {avail['MID']} MID available (min 2)"))
        for p in state["players"]:
            if p["yellow_cards"] >= 4:
                ps = get_p_suspended(p, gw, state["gameweek"])
                if ps > 0.2: warn.append((gw, "MEDIUM", f"{p['name']} {p['yellow_cards']}y P(susp)={ps:.0%}"))
        for tr in state["planned_transfers"]:
            if tr["trigger_gw"] == gw: warn.append((gw, "INFO", f"{tr['out']}->{tr['in']}: {tr['trigger']}"))
    return warn

# ---------- Step 6: transfer vs bank ----------
def should_transfer(best_tv, state, weeks_to_wc=8):
    if state["transfers_banked"] >= 5: return "TRANSFER (at cap)"
    if weeks_to_wc <= 1: return "BANK (week before wildcard)"
    thr = 4.0
    if weeks_to_wc <= 2: thr *= 1.5
    elif weeks_to_wc <= 3: thr *= 1.2
    if [w for w in trajectory(state, 3) if w[1] == "HIGH"]: thr *= 0.8
    return (f"TRANSFER (gain {best_tv:.1f} > {thr:.1f})" if best_tv > thr
            else f"BANK (gain {best_tv:.1f} < threshold {thr:.1f})")

# ---------- Step 7: captain ----------
def select_captain(state, gw):
    out = []
    for p in state["players"]:
        ps = get_p_starts(p, gw, state["gameweek"])
        if ps < 0.85: continue
        rel = 0.90 if p["mean_min"] < 78 else 1.0   # Type-D early-sub discount
        ev = compute_ev(p, gw, state)
        out.append({"name": p["name"], "ev": ev, "score": ev * 2 * rel * ps,
                    "tier": TIER.get(opp(p["team"], gw)[0], "T2"), "team": p["team"],
                    "opp": opp(p["team"], gw)[0], "y_flag": p["yellow_cards"] >= 4})
    return sorted(out, key=lambda x: -x["score"])

# ---------- Step 8: XI selector ----------
def select_xi(state, gw):
    ps = {p["name"]: compute_ev(p, gw, state) for p in state["players"]}
    def top(pos, k): return sorted([p for p in state["players"] if p["position"] == pos],
                                   key=lambda p: -ps[p["name"]])[:k]
    gk = top("GK", 1)
    best, bev = None, -1
    for nd, nm, nf in product([3,4,5], range(2,6), range(1,4)):
        if nd + nm + nf != 10: continue
        xi = gk + top("DEF", nd) + top("MID", nm) + top("FWD", nf)
        if len(xi) != 11: continue
        ev = sum(ps[p["name"]] for p in xi)
        if ev > bev: bev, best = ev, xi
    bench = [p for p in state["players"] if p not in best]
    bench = [p for p in bench if p["position"] == "GK"] + sorted(
        [p for p in bench if p["position"] != "GK"], key=lambda p: -ps[p["name"]])
    return best, bench, ps

# ---------- Step 9: forward projection ----------
def project_forward(state, n=6):
    rows = []
    for off in range(1, n + 1):
        gw = state["gameweek"] + off
        xi, _, ps = select_xi(state, gw)
        rows.append((gw, xi, sum(ps[p["name"]] for p in xi),
                     [p["name"] for p in xi if opp(p["team"], gw)[1] == 0]))
    return rows

# ---------- Step 10: weekly output ----------
def weekly_output(state):
    gw = state["gameweek"]
    print("=" * 60); print(f"SANTA CLAUDE — GW{gw} DECISIONS"); print("=" * 60)
    if state["itb"] < 0:
        print(f"[SQUAD-STATE FLAG] budget £{state['budget_total']}m EXCEEDS £{BUDGET_CAP:.0f} cap by £{-state['itb']}m "
              "-> premium MID at £12 needs a £1.5m trim to be legal.")
    print(f"ITB £{state['itb']}m | transfers banked {state['transfers_banked']} | "
          f"chips: {','.join(state['chips_available'])}")

    print("\nPROJECTED XI EV BY GAMEWEEK\n" + "-" * 26)
    proj = project_forward(state, 6)
    gws = [r[0] for r in proj]
    print("         " + "  ".join(f"GW{g:>2}" for g in gws))
    print("Proj XI  " + "  ".join(f"{r[2]:>4.0f}" for r in proj))

    print("\nSQUAD TRAJECTORY\n" + "-" * 16)
    w = trajectory(state, 6)
    if not w: print("  (no warnings in next 6 GW)")
    for gwk, sev, det in w[:8]: print(f"  [{sev:<8}] GW{gwk}: {det}")

    print("\nTRANSFER DECISION\n" + "-" * 17)
    porro = mk("Porro", "DEF", "DEF attacking", "TOT", 5.5)
    muñoz = next(p for p in state["players"] if p["name"] == "Muñoz")
    tv = calc_transfer_value(muñoz, porro, state, 6)
    print(f"  Planned move under review: Muñoz -> Porro | bench-cover-adjusted 6wk value: {tv:+.1f}")
    print(f"  Bench-cover check: effective_out used (P(avail)-weighted vs best same-pos cover) ✓")
    print(f"  Decision: {should_transfer(max(tv,0), state)}  "
          f"[Porro rested post-WC -> EV suppressed GW1-3, correctly wait to GW3-4]")

    print("\nCAPTAIN RECOMMENDATION\n" + "-" * 21)
    caps = select_captain(state, gw + 1)
    for c in caps[:2]:
        tag = " [YELLOW-FLAG]" if c["y_flag"] else ""
        print(f"  {'Captain' if c is caps[0] else 'Vice   '}: {c['name']:<12} EV {c['ev']:.1f}  "
              f"{c['team']} vs {c['opp']} ({c['tier']}){tag}")

    print("\nSTARTING XI (GW1)\n" + "-" * 17)
    xi, bench, ps = select_xi(state, gw + 1)
    form = f"{sum(1 for p in xi if p['position']=='DEF')}-{sum(1 for p in xi if p['position']=='MID')}-{sum(1 for p in xi if p['position']=='FWD')}"
    for pos in ["GK", "DEF", "MID", "FWD"]:
        names = [f"{p['name']}({ps[p['name']]:.1f})" for p in xi if p["position"] == pos]
        print(f"  {pos}: " + ", ".join(names))
    print(f"  Formation: {form} | Bench: " + ", ".join(p["name"] for p in bench))

    print("\nPLANNED TRANSFERS STATUS\n" + "-" * 24)
    for tr in state["planned_transfers"]:
        due = "TRIGGER NOT YET" if (tr["trigger_gw"] is None or tr["trigger_gw"] > gw) else "DUE"
        print(f"  {tr['out']} -> {tr['in']}: {due} ({tr['trigger']})")
    print("=" * 60)


def engine_report(state, gw):
    print("\n" + "=" * 60); print("NEW xG FIXTURE ENGINE — BEFORE/AFTER"); print("=" * 60)

    def cap(engine):
        best = None
        for p in state["players"]:
            if get_p_starts(p, gw, state["gameweek"]) < 0.85: continue
            ev = compute_ev(p, gw, state, engine=engine)
            if best is None or ev > best[1]: best = (p["name"], ev, opp(p["team"], gw)[0])
        return best
    print(f"\nCAPTAIN (GW{gw}) — old 3-tier vs new continuous:")
    for eng in ["old", "new"]:
        c = cap(eng); print(f"  {eng:>4}: {c[0]:<12} EV {c[1]:.2f}  (vs {c[2]})")

    print("\nTOP TRANSFER TARGET SHIFT — attacker EV vs an extreme fixture:")
    for club in ["HUL", "COV", "IPS", "ARS"]:
        oldm = MULT_OLD["FWD"][TIER.get(club, "T2")]; newm = FR.get_multiplier(club, "FWD", None, True)
        tag = "  <-- MUST-TARGET" if newm >= 1.20 else ("  <-- correctly harder" if newm < 0.9 else "")
        print(f"  FWD vs {club}:  old x{oldm:.2f} -> new x{newm:.2f}{tag}")

    print("\nMUST-TARGET CONFIRM (promoted; player-level profiles):")
    for club in ["HUL", "COV", "IPS"]:
        fwd = FR.get_multiplier(club, "FWD", None, True)
        cm = FR._mult_raw(*FR.SUB_SENS["CM"], club, True)
        cb = FR._mult_raw(*FR.SUB_SENS["CB"], club, True); fb = FR._mult_raw(*FR.SUB_SENS["FB"], club, True)
        print(f"  {club}: FWD x{fwd:.2f} | creative-MID x{cm:.2f} | DEF range CB x{cb:.2f}..attFB x{fb:.2f}"
              + ("  MUST-TARGET ✓" if fwd >= 1.20 else ""))

    print("\nPLAYER-LEVEL FIXTURE CURVES — squad (own data shrunk to role-blended prior):")
    print(f"  {'player':>13} {'pos':>3} {'N':>3} {'w_own':>5} {'w_role':>6} {'s_att':>6} {'s_defw':>6}  flag")
    for p in state["players"]:
        if p["position"] == "GK": continue
        sa, sd, N, wo, po, wr = FR.sens_for(p.get("code"), p["position"])
        wrt = f"{wr:.2f}" if wr is not None else "   -"
        print(f"  {p['name']:>13} {p['position']:>3} {N:>3} {wo:>5.2f} {wrt:>6} {sa:>+6.2f} {sd:>+6.2f}  "
              + ("PRIOR-ONLY (no PL curve)" if po else ""))
        if po and p["position"] == "DEF":
            o, cnt = opp(p["team"], gw)
            if cnt:
                cb, fb = FR.prior_only_range(o, get_home(p["team"], gw))
                print(f"                    -> vs {o}: CB-end x{cb:.2f} <-> attacking-FB-end x{fb:.2f}  (human judgment range)")

    print(f"\nBAYESIAN TEAM RATINGS (GW{state['gameweek']} — 0 games played -> 100% prior):")
    print(f"  {'club':>4} {'ATTprior':>8} {'ATTnow':>7} {'DEFprior':>8} {'DEFnow':>7} {'K':>3} {'prior%':>6} {'data%':>5}")
    for sh, name, ap, an, dp, dn, K, wp, wd in FR.ratings_display(games_played=state["gameweek"] - 1)[:20]:
        print(f"  {sh:>4} {ap:>8.2f} {an:>7.2f} {dp:>8.2f} {dn:>7.2f} {K:>3} {100*wp:>5.0f}% {100*wd:>4.0f}%")
    print("=" * 60)


def main():
    state = build_squad()
    print(f"[STEP 1] loaded {len(state['players'])} players | budget £{state['budget_total']}m | "
          f"ITB £{state['itb']}m | yellow counts all {sum(p['yellow_cards'] for p in state['players'])} (pre-season)")
    print(f"[STEP 2] compute_ev live — NEW xG fixture engine wired in (was 3-tier lookup)")
    weekly_output(state)
    engine_report(state, state["gameweek"] + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
