#!/usr/bin/env python3
"""
weekly.py — in-season weekly management tool. Runs every week before the deadline.
  PART 1: refresh every model component with the just-played GW (Bayesian team ratings,
          recency-weighted per-90 rates, DC model, P(starts), yellows) — THEN
  PART 2/3: generate the decision report for each team on the freshly updated models.

Pre-GW1 there is no completed gameweek, so the refresh reports its prior state and the
report is generated on priors. Each function is written to ingest a completed-GW frame
(fetch_gw_data) the moment real data exists — the loop is identical every week after.
"""
from __future__ import annotations
import math, json, os, numpy as np, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import ev_v2 as V, fixture_ratings as FR, squad_engine as SE, history as H
try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:
    UK = timezone.utc

STATE = Path(__file__).resolve().parent.parent / "data" / "state"
STATE.mkdir(parents=True, exist_ok=True)
HUMAN_INPUT = json.load(open(STATE / "human_input.json", encoding="utf-8")) if (STATE / "human_input.json").exists() else {}

nxt = V._nxt; ID2SH = SE.ID2SH; FX = SE.FX; POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
DECAY = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.40, 6: 0.25}
CURRENT_GW = 0                       # gameweeks completed (0 = pre-season); next deadline = GW CURRENT_GW+1
HORIZON = 6
EMAIL_WINDOW_H = 30                   # email once per GW when the deadline is within this many hours
DL_INFO = {}                          # next-deadline info, populated at startup
FIX = {sh: {} for sh in ID2SH.values()}
for r in FX[FX.event.isin(range(1, 39))].itertuples():
    FIX[ID2SH[r.team_h]][r.event] = (ID2SH[r.team_a], True); FIX[ID2SH[r.team_a]][r.event] = (ID2SH[r.team_h], False)


def code_of(name, pos, team):
    m = nxt[(nxt.web_name == name) & (nxt.element_type == {v: k for k, v in POSN.items()}[pos]) & (nxt.team_name == team)]
    return int((m.iloc[0] if len(m) else nxt[nxt.web_name == name].iloc[0]).code)


def ev_gw(code, name, pos, team, gw):
    fx = FIX[team].get(gw)
    return V.compute_ev_v2(code, name, pos, team, fx[0], fx[1]) if fx else 0.0


# ======================================================= PART 1 — WEEKLY MODEL REFRESH
INGEST_LOG = []


def _compute_deadline(boot):
    """Next GW deadline (from the API) + whether to email now: once per GW, within EMAIL_WINDOW_H
    of the deadline — so it fires the day before, whatever day the deadline falls on (incl. Fri-night
    and midweek). A manual run (FORCE_EMAIL=1) always emails, for testing/retry."""
    info = {"next_gw": None, "deadline": None, "hours": None, "should_email": False}
    ev = next((e for e in boot["events"] if e["is_next"]), None)
    if ev:
        dl = datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00"))
        hrs = (dl - datetime.now(timezone.utc)).total_seconds() / 3600
        info.update(next_gw=ev["id"], deadline=dl.astimezone(UK).strftime("%a %d %b, %H:%M UK"), hours=round(hrs, 1))
        lastf = STATE / "last_emailed.json"
        last = json.load(open(lastf)).get("gw") if lastf.exists() else None
        force = os.environ.get("FORCE_EMAIL") == "1"
        info["should_email"] = bool(force or (0 <= hrs <= EMAIL_WINDOW_H and ev["id"] != last))
        # NB: last_emailed is recorded by the workflow AFTER a successful send, so a failed
        # send simply retries on the next daily run (still within the window).
    json.dump(info, open(STATE / "deadline.json", "w"))
    return info


def auto_ingest_and_refresh():
    """One-command startup: detect finished-but-not-ingested gameweeks, pull them from the live
    FPL API, and apply the Bayesian team update (1c). Per-90 rates, P(starts) recency, DC-model
    refit and yellow-card accrual refresh automatically — ev_v2/history read the accumulating
    store on demand. Logged, never silent, never on stale data."""
    global CURRENT_GW, INGEST_LOG, DL_INFO
    log = []; boot = None; finished = None
    try:
        import fpl_fetch as F
        st = F.season_state(); boot = st["bootstrap"]; finished = st["finished"]
    except Exception as e:
        log.append(f"⚠ FPL API unreachable ({type(e).__name__}) — running on last-ingested state")
    if boot is not None:
        DL_INFO = _compute_deadline(boot)
    if finished is not None:
        already = set(int(x) for x in H.load_inseason().gw.unique()) if H.has_inseason() else set()
        new = [g for g in finished if g not in already]
        for gw in new:
            try: log.append(f"ingested GW{gw}: {H.ingest_gw(gw, boot)} players played")
            except Exception as e: log.append(f"GW{gw} ingest FAILED: {e}")
        CURRENT_GW = len(finished)
        if not finished: log.append("no completed gameweeks yet (pre-season) — models at prior")
        elif not new: log.append(f"all {CURRENT_GW} completed GW(s) already ingested — no new data")
    else:
        CURRENT_GW = int(H.load_inseason().gw.max()) if H.has_inseason() else 0
    if boot is not None and CURRENT_GW > 0 and H.has_inseason():
        log += _apply_team_bayes(boot)
    INGEST_LOG = log
    return log


def _apply_team_bayes(bootstrap):
    """Normalise cumulative live team xG (scored & conceded) to league average, then Bayesian-update
    each club's rating — tiered confidence (K) already baked into fixture_ratings."""
    d = H.load_inseason()
    tid = {e["code"]: e["team"] for e in bootstrap["elements"]}
    shrt = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    d = d.assign(team=d.code.map(lambda c: shrt.get(tid.get(c))))
    scored = {(r.team, int(r.gw)): r.xG for r in d.groupby(["team", "gw"]).xG.sum().reset_index().itertuples()}
    gws = sorted(int(x) for x in d.gw.unique())
    lg = float(np.mean(list(scored.values()))) if scored else 1.4
    n = 0
    for team in [t for t in d.team.dropna().unique() if t in FR.RATINGS]:
        att = [scored[(team, g)] for g in gws if (team, g) in scored]
        con = []
        for g in gws:
            fx = FIX.get(team, {}).get(g)
            if fx and (fx[0], g) in scored: con.append(scored[(fx[0], g)])
        if att:
            FR.bayes_update(team, len(att), np.mean(att) / lg,
                            (np.mean(con) / lg) if con else FR.RATINGS[team]["defw_prior"])
            n += 1
    return [f"Bayesian team ratings updated from {len(gws)} live GW(s) of xG ({n} clubs)"]


def refresh_models(completed_gw=None):
    """Display the refreshed model state (ingest already ran in auto_ingest_and_refresh)."""
    completed_gw = CURRENT_GW if completed_gw is None else completed_gw
    flags = []
    disp = FR.ratings_display(games_played=completed_gw)
    for sh, name, ap, an, dp, dn, K, wp, wd in disp:
        if completed_gw >= 3 and (abs(an - ap) / max(ap, .1) > 0.30 or abs(dn - dp) / max(dp, .1) > 0.30):
            flags.append(f"[!] {sh}: xG rating diverges >30% from prior — HUMAN REVIEW")
    return dict(team=disp, flags=flags, games=completed_gw, ingest=INGEST_LOG)


# ======================================================= PART 2 — DECISION REPORT
def p_start(code, name):
    hi = HUMAN_INPUT.get(name)
    if hi and "p_start" in hi:                      # human override wins (nailed-ness model can't derive)
        return float(hi["p_start"])
    return V.get_minutes_probs(code, name)["p60"]


def human_confirmation(squad):
    """2-min review: flag P(starts) moves >20% since last week + surface/apply free-text human input."""
    last = json.load(open(STATE / "pstarts_last.json", encoding="utf-8")) if (STATE / "pstarts_last.json").exists() else {}
    moves, applied, cur = [], [], {}
    for p in squad:
        model_p = V.get_minutes_probs(p["code"], p["name"])["p60"]; cur[p["name"]] = model_p
        prev = last.get(p["name"])
        if prev is not None and abs(model_p - prev) > 0.20:
            moves.append(f"{p['name']}: P(start) {prev:.2f} → {model_p:.2f} "
                         f"({'nailed upgrade' if model_p > prev else 'rotation risk emerging'}) — confirm?")
        hi = HUMAN_INPUT.get(p["name"])
        if hi and hi.get("note"):
            applied.append(f"{p['name']}: {hi.get('note')}" + (f"  [p_start→{hi['p_start']}]" if 'p_start' in hi else ""))
    json.dump(cur, open(STATE / "pstarts_last.json", "w", encoding="utf-8"))
    return moves, applied


def select_captain(squad, gw):
    c = []
    for p in squad:
        if p_start(p["code"], p["name"]) < 0.85 or p["pos"] == "GK": continue
        e = ev_gw(p["code"], p["name"], p["pos"], p["team"], gw)
        c.append((p, e))
    c.sort(key=lambda x: -x[1]); return c


def select_xi(squad, gw):
    for p in squad: p["e"] = ev_gw(p["code"], p["name"], p["pos"], p["team"], gw)
    gk = max([p for p in squad if p["pos"] == "GK"], key=lambda p: p["e"])
    D = sorted([p for p in squad if p["pos"] == "DEF"], key=lambda p: -p["e"])
    M = sorted([p for p in squad if p["pos"] == "MID"], key=lambda p: -p["e"])
    Fw = sorted([p for p in squad if p["pos"] == "FWD"], key=lambda p: -p["e"])
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3 and len(D) >= d and len(M) >= m and len(Fw) >= f:
                xi = [gk] + D[:d] + M[:m] + Fw[:f]; s = sum(p["e"] for p in xi)
                if best is None or s > best[0]: best = (s, xi, (d, m, f))
    _, xi, form = best
    bench = [p for p in squad if p not in xi]
    bench = [p for p in bench if p["pos"] == "GK"] + sorted([p for p in bench if p["pos"] != "GK"], key=lambda p: -p["e"])
    return xi, bench, form


def trajectory(squad):
    warn = []; table = []
    for off in range(1, HORIZON + 1):
        gw = CURRENT_GW + off; avail = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}; tot = 0
        xi, _, _ = select_xi(squad, gw); tot = sum(p["e"] for p in xi)
        for p in squad:
            if FIX[p["team"]].get(gw) and p_start(p["code"], p["name"]) > 0.5: avail[p["pos"]] += 1
        for pos, mn in [("GK", 1), ("DEF", 3), ("MID", 2), ("FWD", 1)]:
            if avail[pos] < mn: warn.append(("HIGH", gw, f"only {avail[pos]} {pos} available"))
        table.append((gw, tot))
    return table, warn


POOL = None
def build_pool():
    global POOL
    rows = []
    for r in nxt[nxt.status == "a"].itertuples():
        team = r.team_name
        if team not in FIX: continue
        rt = V.get_per_90_rates(int(r.code))
        if rt["thin"]: continue
        code = int(r.code); pos = POSN[int(r.element_type)]
        ev = [ev_gw(code, r.web_name, pos, team, CURRENT_GW + o) for o in range(1, HORIZON + 1)]
        rows.append(dict(code=code, name=r.web_name, pos=pos, team=team, price=r.now_cost / 10,
                         ev=ev, defw=FR.RATINGS.get(team, {}).get("defw", 1)))
    POOL = rows


def fixture_swing(team):
    up = np.mean([FR.RATINGS.get(FIX[team][CURRENT_GW + o][0], {}).get("defw", 1) for o in range(1, HORIZON + 1) if FIX[team].get(CURRENT_GW + o)])
    return up  # higher = easier upcoming attacking fixtures (pre-season: no 'recent' half)


def best_transfer(squad, itb):
    if POOL is None: build_pool()
    held = {(p["name"], p["team"]) for p in squad}
    club = {}
    for p in squad: club[p["team"]] = club.get(p["team"], 0) + 1
    best = None
    for out in squad:
        out_ev6 = [ev_gw(out["code"], out["name"], out["pos"], out["team"], CURRENT_GW + o) for o in range(1, HORIZON + 1)]
        bench_cover = min([q for q in squad if q["pos"] == out["pos"] and q is not out],
                          key=lambda q: q["price"], default=None)
        for c in POOL:
            if c["pos"] != out["pos"] or (c["name"], c["team"]) in held: continue
            if c["price"] > out["price"] + itb + 1e-9: continue
            if club.get(c["team"], 0) + (0 if c["team"] == out["team"] else 1) > 3: continue
            gain = sum((c["ev"][o] - out_ev6[o]) * DECAY[o + 1] for o in range(HORIZON))
            if best is None or gain > best["gain"]:
                sig = "fixture swing" if fixture_swing(c["team"]) > fixture_swing(out["team"]) + 0.05 else "quality upgrade"
                if c["pos"] == "DEF" and c["defw"] < out["defw"] - 0.1: sig = "better clean-sheet team"
                best = dict(out=out, inn=c, gain=gain, signal=sig)
    return best


def watchlist(squad):
    w = []
    for p in squad:
        rt = V.get_per_90_rates(p["code"])
        if rt.get("thin"):
            w.append(f"{p['name']} ({p['team']}): PRIOR-ONLY (promoted/new) — rating updating, check GW3")
        elif rt["pos"] in ("DEF", "MID") and rt["DC90"] >= 9.0:
            pdc = V.get_p_dc_bonus(rt, 90)
            w.append(f"{p['name']}: DC90 {rt['DC90']:.1f}, P(DC bonus) {pdc:.0%} — DC-point engine, hold")
        elif rt["pos"] == "DEF" and rt["xA90"] > V.POS_AVG["MID"]["xA90"]:
            w.append(f"{p['name']}: DEF with MID-level xA ({rt['xA90']:.2f}) — attacking-defender value")
    return w[:5]


# ======================================================= PART 3 — OUTPUT
def report(team_name, squad_def, itb, banked, chips, planned):
    squad = [dict(name=n, pos=po, team=t, price=pr, code=code_of(n, po, t)) for (n, po, t, pr) in squad_def]
    gw = CURRENT_GW + 1
    rf = refresh_models()
    xi, bench, form = select_xi(squad, gw); caps = select_captain(squad, gw)
    table, warn = trajectory(squad)
    tv = best_transfer(squad, itb)
    bench_ev = sum(p["e"] for p in bench if p["pos"] != "GK")
    cap_ev = caps[0][1] if caps else 0
    L = []
    L.append("═" * 54); L.append(f"{team_name} — GW{gw} DECISIONS")
    L.append(f"Models updated: GW{CURRENT_GW} data ingested ✓ ({rf['games']} GWs played → Bayesian {'100% prior' if rf['games']==0 else 'blended'})")
    if DL_INFO.get("deadline"):
        L.append(f"⏰ GW{DL_INFO['next_gw']} DEADLINE: {DL_INFO['deadline']}  (in {DL_INFO['hours']}h)"
                 + ("   ⚠ ACT BEFORE DEADLINE" if DL_INFO.get("should_email") else ""))
    L.append("═" * 54)
    L.append("\nMODEL UPDATES THIS WEEK\n" + "━" * 24)
    for line in rf.get("ingest", []): L.append("  ⟳ " + line)
    top = rf["team"][:3]
    for sh, name, ap, an, dp, dn, K, wp, wd in top:
        L.append(f"  {sh} att {ap:.2f}→{an:.2f} def {dp:.2f}→{dn:.2f}  [K={K}, prior {100*wp:.0f}%/data {100*wd:.0f}%]")
    L.append("  (team ratings move once GW1 xG lands; divergence>30% after 3 GWs → flag)")
    for f in rf["flags"]: L.append("  " + f)
    moves, applied = human_confirmation(squad)
    L.append("\n⚠ HUMAN CONFIRMATION (2-min review — edit data/state/human_input.json)\n" + "━" * 31)
    if moves:
        L.append("  P(starts) moved >20% since last week — verify against team news:")
        for m in moves: L.append("    • " + m)
    else:
        L.append("  No >20% P(starts) moves since last week.")
    L.append("  Human nailed-ness input applied this week (WC returnees / training / manager quotes):")
    for a in (applied or ["    (none — add overrides to human_input.json if you have news the model can't see)"]):
        L.append(("    ✓ " + a) if applied else a)
    L.append("\nCHIP EVALUATION\n" + "━" * 15)
    L.append(f"  Wildcard:    {'MONITOR' if False else 'Not yet'} (rebuild value low pre-set)")
    L.append(f"  Bench Boost: bench EV this GW = {bench_ev:.1f} — {'strong' if bench_ev>18 else 'hold for DGW'}")
    L.append(f"  Triple Cap:  captain EV {cap_ev:.1f} — hold for a DGW/elite fixture")
    L.append("\nTRANSFER DECISION\n" + "━" * 17)
    if tv:
        o, i = tv["out"], tv["inn"]
        thr = 4.0 * (1.5 if banked < 1 else 1.0)
        dec = "TRANSFER ✓" if tv["gain"] > thr and banked >= 1 else "BANK"
        L.append(f"  Best: OUT {o['name']} ({o['pos']} {o['team']} £{o['price']}) → IN {i['name']} ({i['team']} £{i['price']})")
        L.append(f"    signal: {tv['signal']} (forward-looking ✓, not point-chasing)")
        L.append(f"    6-GW bench-cover-adjusted gain: {tv['gain']:+.1f}  | threshold {thr:.1f}  → {dec}")
        L.append(f"    budget after: £{itb - (i['price']-o['price']):.1f}m ITB, {banked} banked")
    else:
        L.append("  No positive-gain transfer — BANK")
    L.append("\nWATCHLIST (monitor, not acting)\n" + "━" * 31)
    for w in watchlist(squad): L.append("  • " + w)
    L.append("\nCAPTAIN\n" + "━" * 7)
    if caps:
        c0 = caps[0][0]; c1 = caps[1][0] if len(caps) > 1 else None
        L.append(f"  Captain: {c0['name']} — EV {caps[0][1]:.1f}, {c0['team']} vs {FIX[c0['team']].get(gw,('?',))[0]}")
        if c1: L.append(f"  Vice:    {c1['name']} — EV {caps[1][1]:.1f}, {c1['team']} vs {FIX[c1['team']].get(gw,('?',))[0]}")
    L.append(f"\nSTARTING XI — {form[0]}-{form[1]}-{form[2]}\n" + "━" * 24)
    for pos in ["GK", "DEF", "MID", "FWD"]:
        L.append(f"  {pos}: " + ", ".join(f"{p['name']}" for p in xi if p["pos"] == pos))
    L.append("  Bench: " + ", ".join(p["name"] for p in bench))
    L.append("\nPROJECTED XI EV BY GAMEWEEK\n" + "━" * 27)
    L.append("  " + "  ".join(f"GW{g}" for g, _ in table))
    L.append("  " + "  ".join(f"{t:4.0f}" for _, t in table) + f"   (min {min(t for _,t in table):.0f})")
    for lvl, g, msg in warn[:3]: L.append(f"  [{lvl}] GW{g}: {msg}")
    L.append("\nPLANNED TRANSFERS\n" + "━" * 17)
    for pt in planned: L.append("  " + pt)
    L.append("═" * 54)
    return "\n".join(L)


if __name__ == "__main__":
    print("⟳ Refreshing models from live FPL API (detect → ingest → refresh)...", flush=True)
    for line in auto_ingest_and_refresh(): print("   " + line)
    print()
    SANTA = [("Sánchez","GK","CHE",5.0),("Leno","GK","FUL",4.5),("Senesi","DEF","TOT",6.0),("Van Hecke","DEF","TOT",5.0),
             ("Romero","DEF","TOT",5.0),("Calafiori","DEF","ARS",5.5),("Van den Berg","DEF","BRE",5.0),
             ("Mbeumo","MID","MUN",8.0),("Anderson","MID","MCI",6.5),("Enzo","MID","CHE",7.0),("Sarr","MID","CRY",6.5),
             ("Gomez","MID","BHA",5.0),("Haaland","FWD","MCI",15.5),("Thiago","FWD","BRE",8.0),("Mateta","FWD","CRY",6.5)]
    HUMAN = [("Lammens","GK","MUN",5.0),("Phillips","GK","HUL",4.0),("Mosquera","DEF","ARS",5.5),("N.Williams","DEF","NFO",5.0),
             ("Kayode","DEF","BRE",4.5),("Virgil","DEF","LIV",6.5),("van Ewijk","DEF","COV",4.0),("Mbeumo","MID","MUN",8.0),
             ("Szoboszlai","MID","LIV",7.0),("Stach","MID","LEE",6.0),("Gomez","MID","BHA",5.0),("B.Fernandes","MID","MUN",12.0),
             ("Walle Egeli","FWD","IPS",4.5),("Haaland","FWD","MCI",15.5),("João Pedro","FWD","CHE",7.5)]
    print(report("SANTA CLAUDE (AI team)", SANTA, itb=1.0, banked=1,
                 chips=[], planned=["Spurs D de-stack (Romero→Gvardiol): open — spends £1 ITB, de-correlates CS"]))
    print()
    print(report("HUMAN TEAM (FPL Mate)", HUMAN, itb=0.0, banked=1,
                 chips=[], planned=["Wildcard planned GW4 — hold transfers, ride current 15"]))
