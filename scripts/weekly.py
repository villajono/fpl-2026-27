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
import odds as ODDS                    # bookmaker fixture inputs (near GWs); off unless key/mock enabled
try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:
    UK = timezone.utc

STATE = Path(__file__).resolve().parent.parent / "data" / "state"
STATE.mkdir(parents=True, exist_ok=True)
OVERRIDES = {}                       # {player_id(code): override}, GW-scoped, loaded at startup from the form file

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


def _load_overrides(next_gw):
    """Load GW-scoped P(starts) overrides written by the phone form. Auto-clears when the stored
    gameweek is stale (a past GW has been ingested) — overrides never persist unnoticed."""
    global OVERRIDES
    f = STATE / "human_input.json"
    d = json.load(open(f, encoding="utf-8")) if f.exists() else {}
    if d.get("gameweek") != next_gw:
        d = {"gameweek": next_gw, "overrides": []}
        json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    OVERRIDES = {int(o["player_id"]): o for o in d.get("overrides", [])}
    # The EV model does NOT read OVERRIDES — compute_ev_v2 -> get_minutes_probs reads V.P60_OVR,
    # keyed by web_name. Without this mirror a form override changed p_start() and bench cover but
    # left the player's EV untouched, so someone marked "won't start" kept full EV and could still
    # be picked in the XI or recommended as a transfer target. players.json writes web_name, so the
    # keys match exactly.
    V.P60_OVR.update({o["player_name"]: _minutes_shape(o) for o in d.get("overrides", [])})


def _minutes_shape(o):
    """Turn one override row into what the EV model needs.

    Two ways to write a row. The original `p_starts_override` is a bare number and — despite the
    name — has always meant P(plays 60+), because that is what get_minutes_probs consumes. Left
    working untouched.

    The better one is the pair a human actually knows: `p_start` (does he get picked) and
    `mins_if_start` (how long does he last). Those are different questions and for rotation players
    they give opposite answers — Tzolis starts about half the time and comes off on 57, so his
    P(start) is 0.50 while his P(60+) is under 0.20 and most of his value sits in appearances that
    the flat 0.05 cameo term used to discard.

    Minutes-when-starting are treated as normal around the stated figure with an 8-minute spread,
    which is roughly how substitution timing scatters. `p_sub` is the chance he appears off the
    bench in the games he does not start (default 0.30 for a squad player, 0 if he is ruled out).
    """
    if "p_start" not in o:
        return float(o["p_starts_override"])
    ps = float(o["p_start"])
    mins = float(o.get("mins_if_start", 90))
    p_sub = float(o.get("p_sub", 0.30 if ps > 0 else 0.0))
    p60_given_start = 0.5 * (1 + math.erf(((mins - 60.0) / 8.0) / math.sqrt(2)))
    p60 = ps * p60_given_start
    started_short = ps * (1 - p60_given_start)
    came_on = (1 - ps) * p_sub
    p_cameo = started_short + came_on
    # Minutes in the appearances that fall short of 60: hooked-before-the-hour if he started,
    # a typical 20-minute run-out if he came off the bench.
    partial = ((started_short * min(mins, 55.0) + came_on * 20.0) / p_cameo) if p_cameo > 0 else 30.0
    return dict(p60=round(p60, 3), p_cameo=round(p_cameo, 3), partial=round(partial, 1))


def _write_players_json(next_gw):
    """Player list for the phone override form — the model's OWN universe, so the form's IDs
    always match what weekly.py looks up (no string matching, no mismatch)."""
    posn = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    rows = [{"id": int(r.code), "name": r.web_name, "club": r.team_name, "pos": posn[int(r.element_type)]}
            for r in V._nxt[V._nxt.status == "a"].itertuples() if pd.notna(r.code)]
    json.dump({"gameweek": next_gw, "players": sorted(rows, key=lambda x: (x["club"], x["name"]))},
              open(STATE / "players.json", "w", encoding="utf-8"), ensure_ascii=False)


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
    next_gw = DL_INFO.get("next_gw") or (CURRENT_GW + 1)
    _load_overrides(next_gw); _write_players_json(next_gw)     # GW-scoped overrides + form player list
    log.append(f"overrides: {len(OVERRIDES)} active for GW{next_gw}; players.json refreshed for the form")
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
    """P(plays 60+ minutes) — the number the EV model actually runs on, and the one that decides
    whether a player collects one appearance point or two. Named p_start for history; the report
    labels it P(60+) so it stops reading as 'does he get picked'."""
    ov = OVERRIDES.get(code)                          # phone-form override wins (nailed-ness model can't derive)
    if ov is not None:
        shape = _minutes_shape(ov)
        return float(shape["p60"] if isinstance(shape, dict) else shape)
    return V.get_minutes_probs(code, name)["p60"]


def human_confirmation(squad):
    """2-min review: flag P(starts) moves >20% since last week + surface/apply free-text human input."""
    last = json.load(open(STATE / "pstarts_last.json", encoding="utf-8")) if (STATE / "pstarts_last.json").exists() else {}
    moves, applied, cur = [], [], {}
    for p in squad:
        model_p = V.get_minutes_probs(p["code"], p["name"])["p60"]; cur[p["name"]] = model_p
        prev = last.get(p["name"])
        if prev is not None and abs(model_p - prev) > 0.20:
            moves.append(f"{p['name']}: P(60+) {prev:.2f} → {model_p:.2f} "
                         f"({'nailed upgrade' if model_p > prev else 'rotation risk emerging'}) — confirm?")
        ov = OVERRIDES.get(p["code"])
        if ov:
            applied.append(f"{ov['player_name']} ({ov['club']}): p60→{p_start(ov['player_id'], ov['player_name']):.2f}"
                           + (f" — {ov['notes']}" if ov.get("notes") else ""))
    json.dump(cur, open(STATE / "pstarts_last.json", "w", encoding="utf-8"))
    return moves, applied


def pstart_review(squad, tv, n=6):
    """The P(start) values the model is actually running on, lowest first.

    You cannot sensibly set P(start) for every player every week, and you don't need to: the numbers
    that change a decision are the shakiest players in the squad and whoever the engine wants to buy.
    Those are what this lists. Disagree with one, set it in the form, re-run the workflow, and the
    revised figure flows through EV, the XI, the captain and the transfer call together."""
    rows = []
    for p in squad:
        src = "YOURS" if OVERRIDES.get(p["code"]) else "model"
        rows.append((p_start(p["code"], p["name"]), p["name"], p["team"], src))
    rows.sort()
    L = [f"  {'player':<16}{'team':<5}{'P(60+)':>8}  source"]
    for v, nm, tm, src in rows[:n]:
        L.append(f"  {nm[:15]:<16}{tm:<5}{v:>8.2f}  {src}")
    if tv:
        i = tv["inn"]
        src = "YOURS" if OVERRIDES.get(i["code"]) else "model"
        L.append(f"  {('→ ' + i['name'][:13]):<16}{i['team']:<5}"
                 f"{p_start(i['code'], i['name']):>8.2f}  {src}  (transfer target)")
    return L


def select_captain(xi):
    """Captain = the single starting-XI player with the highest single-GW EV. Nothing else —
    no reliability discount, no rank, no template. EV already prices minutes and fixture."""
    return sorted([(p, p["e"]) for p in xi], key=lambda x: -x[1])


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


def _p_zero(code, name):
    """P(player plays 0 minutes) — the only case that triggers an auto-sub. A 1-59 min cameo does NOT.
    So this is (1 - p60 - p_cameo), NOT (1 - p60): the latter wrongly counts cameos as blanks."""
    ov = OVERRIDES.get(code)
    if ov is not None:
        # Use the same shape the EV model gets, so a rotation player's cameos are counted as
        # appearances here too — otherwise he looks far likelier to blank than the EV implies.
        sh = _minutes_shape(ov)
        if isinstance(sh, dict):
            return max(0.0, 1 - sh["p60"] - sh["p_cameo"])
        p60 = float(sh)
        return max(0.0, 1 - p60 - (0.05 if p60 > 0 else 0.0))   # overridden-out player: ~certain 0 minutes
    mp = V.get_minutes_probs(code, name)
    return max(0.0, 1 - mp["p60"] - mp["p_cameo"])


def _autosub_ev(xi, bench):
    """Small auto-sub contribution: bench outfielders cover XI blanks. Poisson on expected blanks."""
    lam = sum(_p_zero(p["code"], p["name"]) for p in xi if p["pos"] != "GK")
    bo = sorted([p for p in bench if p["pos"] != "GK"], key=lambda p: -p["e"])
    auto = 0.0
    for j, p in enumerate(bo[:3]):
        pge = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(j + 1))
        auto += pge * p["e"]                                          # bench EV × P(>=j+1 starters blank)
    return auto


def trajectory(squad):
    """Per-GW projected WEEKLY points = XI points + captain bonus (doubled best XI EV) + small auto-sub.
    Never total-squad points."""
    warn = []; table = []
    for off in range(1, HORIZON + 1):
        gw = CURRENT_GW + off
        xi, bench, _ = select_xi(squad, gw)
        xi_ev = sum(p["e"] for p in xi)
        cap_bonus = max((p["e"] for p in xi), default=0.0)          # captain doubles the highest XI EV
        auto = _autosub_ev(xi, bench)
        avail = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for p in squad:
            if FIX[p["team"]].get(gw) and p_start(p["code"], p["name"]) > 0.5: avail[p["pos"]] += 1
        for pos, mn in [("GK", 1), ("DEF", 3), ("MID", 2), ("FWD", 1)]:
            if avail[pos] < mn: warn.append(("HIGH", gw, f"only {avail[pos]} {pos} available"))
        table.append((gw, xi_ev, cap_bonus, auto, xi_ev + cap_bonus + auto))
    return table, warn


POOL = None
def build_pool():
    global POOL
    rows = []
    for r in nxt[nxt.status == "a"].itertuples():
        team = r.team_name
        if team not in FIX: continue
        code = int(r.code); pos = POSN[int(r.element_type)]
        rt = V.get_per_90_rates(code, pos)
        if rt["thin"]: continue
        ev = [ev_gw(code, r.web_name, pos, team, CURRENT_GW + o) for o in range(1, HORIZON + 1)]
        rows.append(dict(code=code, name=r.web_name, pos=pos, team=team, price=r.now_cost / 10,
                         ev=ev, defw=FR.RATINGS.get(team, {}).get("defw", 1)))
    POOL = rows


def fixture_swing(team):
    up = np.mean([FR.RATINGS.get(FIX[team][CURRENT_GW + o][0], {}).get("defw", 1) for o in range(1, HORIZON + 1) if FIX[team].get(CURRENT_GW + o)])
    return up  # higher = easier upcoming attacking fixtures (pre-season: no 'recent' half)


def _has_dgw(team, gw):
    return len(FX[(FX.event == gw) & ((FX.team_h == SE._id(team)) | (FX.team_a == SE._id(team)))]) >= 2


def _can_field_xi(squad, gw):
    a = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for p in squad:
        if FIX[p["team"]].get(gw) and p_start(p["code"], p["name"]) > 0.5: a[p["pos"]] += 1
    return a["GK"] >= 1 and a["DEF"] >= 3 and a["MID"] >= 2 and a["FWD"] >= 1 and sum(a.values()) >= 11


def best_transfer(squad, itb, hold=HORIZON):
    """Best single swap over the realistic HOLDING PERIOD (equal-weighted — points matter equally,
    no discount). effective_out = EV(out) + P(out blanks)·EV(bench cover): the loss is small in weeks
    'out' wouldn't have started anyway. Returns the full-hold gain plus GW+1 / GW+2 gains for the hit
    decision. This is 'materially better for the next {hold} weeks', NOT highest remaining-season EV."""
    if POOL is None: build_pool()
    held = {(p["name"], p["team"]) for p in squad}
    club = {}
    for p in squad: club[p["team"]] = club.get(p["team"], 0) + 1
    # Who would actually start next week. The bench-cover credit below is only real for a player
    # you were going to field: if he is on the bench already, losing him costs you his own EV and
    # nothing more, because the cover stays in the squad either way. Without this test a ruled-out
    # bench player was the most expensive man to sell — Mateta, out until 11 October and worth 0,
    # scored eff_out = 1.0 x bench cover, so the engine preferred selling a fit starter instead.
    _xi_now, _, _ = select_xi(squad, CURRENT_GW + 1)
    starters = {(p["name"], p["team"]) for p in _xi_now}
    best = None
    for out in squad:
        out_ev = [ev_gw(out["code"], out["name"], out["pos"], out["team"], CURRENT_GW + o) for o in range(1, hold + 1)]
        bc = min([q for q in squad if q["pos"] == out["pos"] and q is not out], key=lambda q: q["price"], default=None)
        bc_ev = ([ev_gw(bc["code"], bc["name"], bc["pos"], bc["team"], CURRENT_GW + o) for o in range(1, hold + 1)]
                 if bc else [0.0] * hold)
        pz = _p_zero(out["code"], out["name"])                                  # 0-min prob (autosub trigger), NOT 1-p60
        cover = pz if (out["name"], out["team"]) in starters else 0.0           # only a starter can be auto-subbed for
        eff_out = [out_ev[o] + cover * bc_ev[o] for o in range(hold)]           # bench cover — small when 'out' is nailed
        for c in POOL:
            if c["pos"] != out["pos"] or (c["name"], c["team"]) in held: continue
            if c["price"] > out["price"] + itb + 1e-9: continue
            if club.get(c["team"], 0) + (0 if c["team"] == out["team"] else 1) > 3: continue
            diff = [c["ev"][o] - eff_out[o] for o in range(hold)]               # equal weight, no decay
            gain = sum(diff)
            if best is None or gain > best["gain"]:
                sig = "fixture swing" if fixture_swing(c["team"]) > fixture_swing(out["team"]) + 0.05 else "quality upgrade"
                if c["pos"] == "DEF" and c["defw"] < out["defw"] - 0.1: sig = "better clean-sheet team"
                best = dict(out=out, inn=c, gain=gain, gw1=diff[0], gw2=(diff[1] if hold > 1 else 0.0), signal=sig, hold=hold)
    return best


def should_take_hit(tv, squad, gw):
    """A −4 hit is justified ONLY for: a DGW with immediate gain over 4, an unfieldable XI, or a clear
    2-week gain materially above the cost. Everything else waits for next week's free transfer — a
    long-horizon gain buys only ONE extra week of ownership, almost never worth 4 points."""
    if tv is None: return False, "no improving transfer"
    if _has_dgw(tv["inn"]["team"], gw) and tv["gw1"] > 4.0:
        return True, "DGW — immediate gain clears 4 pts"
    if not _can_field_xi(squad, gw):
        return True, "cannot field a full XI — hit justified"
    if tv["gw1"] + tv["gw2"] > 6.0:
        return True, "clear 2-week gain materially exceeds the 4-pt cost"
    return False, "hit not justified — bank, take it free next week"


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
# ======================================================= CHIP ENGINE (ported from backtest.py → live data)
# Multi-fixture schedule (FIX only holds one fixture/team/GW; DGW/BGW need the full list).
SCHED = {sh: {} for sh in ID2SH.values()}
for _r in FX[FX.event.isin(range(1, 39))].itertuples():
    SCHED[ID2SH[_r.team_h]].setdefault(_r.event, []).append((ID2SH[_r.team_a], True))
    SCHED[ID2SH[_r.team_a]].setdefault(_r.event, []).append((ID2SH[_r.team_h], False))
CHIP_FILE = STATE / "chips.json"
CHIP_THRESH = dict(wc=12.0, bb_h1=12.0, bb_h2=14.0, fh=12.0, tc_min=7.0)


def _fx(team, gw): return SCHED.get(team, {}).get(gw, [])
def _half(gw): return 1 if gw <= 19 else 2
def _half_end(gw): return 19 if gw <= 19 else 38


def ev_multi(code, name, pos, team, gw):
    return sum(V.compute_ev_v2(code, name, pos, team, opp, home) for opp, home in _fx(team, gw))


def load_chip_state():
    if CHIP_FILE.exists(): return json.load(open(CHIP_FILE))
    return {"1": {c: None for c in ("WC", "BB", "TC", "FH")}, "2": {c: None for c in ("WC", "BB", "TC", "FH")}}


def _xi_ev(squad, gw):
    for p in squad: p["e"] = ev_multi(p["code"], p["name"], p["pos"], p["team"], gw)
    xi, bench, _ = select_xi(squad, gw)
    return sum(p["e"] for p in xi), xi, bench


def _wc_refit(squad, itb, gw, horizon=HORIZON, max_swaps=15):
    """Wildcard/Free-Hit as unlimited free transfers: hill-climb from the current squad, only
    improving swaps -> can never lose EV. horizon=1 gives the one-week Free-Hit team."""
    if POOL is None: build_pool()
    sq = [dict(p) for p in squad]
    scr = lambda pl: {id(p): sum(ev_multi(p["code"], p["name"], p["pos"], p["team"], gw + o) for o in range(horizon)) for p in pl}
    pscore = {c["name"] + c["team"]: sum(c["ev"][o] for o in range(min(horizon, len(c["ev"])))) for c in POOL}
    for _ in range(max_swaps):
        held = {(p["name"], p["team"]) for p in sq}
        club = {}; spent = 0.0
        for p in sq: club[p["team"]] = club.get(p["team"], 0) + 1; spent += p["price"]
        budget = spent + itb; ss = scr(sq); best = None
        for p in sq:
            base = ss[id(p)]
            for c in POOL:
                if (c["name"], c["team"]) in held or c["pos"] != p["pos"]: continue
                if spent - p["price"] + c["price"] > budget + 1e-9: continue
                if club.get(c["team"], 0) + (0 if c["team"] == p["team"] else 1) > 3: continue
                g = pscore[c["name"] + c["team"]] - base
                if g > 0.5 and (best is None or g > best[0]): best = (g, p, c)
        if best is None: break
        _, out, c = best
        sq = [dict(name=c["name"], pos=c["pos"], team=c["team"], price=c["price"], code=c["code"]) if x is out else x for x in sq]
    return sq


def _cluster_ahead(gw, ahead=3):
    out = []
    for w in range(gw, gw + ahead + 1):
        dgw = sum(1 for t in SCHED if len(_fx(t, w)) >= 2); blank = sum(1 for t in SCHED if not _fx(t, w))
        if dgw >= 4: out.append((w, "DGW", dgw))
        elif blank >= 6: out.append((w, "BGW", blank))
    return out


def _swing_present(gw):
    for t in SCHED:
        up = [FR.RATINGS.get(o, {}).get("defw", 1.0) for w in range(gw, gw + 4) for o, _ in _fx(t, w)]
        rec = [FR.RATINGS.get(o, {}).get("defw", 1.0) for w in range(max(1, gw - 4), gw) for o, _ in _fx(t, w)]
        if up and rec and (sum(up) / len(up)) > (sum(rec) / len(rec)) + 0.15: return True
    return False


def chip_evaluation(squad, itb, banked, gw, chips=None):
    """Produce the CHIP EVALUATION report block (half-aware, GW1-19 / GW20-38). Recommends, never auto-plays.

    `chips` is THIS team's played chips as {half: {CHIP: gameweek}} — the shape fetch_squads.py
    prints. It has to be per-team: chips.json is one shared file, so reading it alone would mark
    Santa Claude's Bench Boost used the moment Jon played his, and Santa's entire purpose is to be
    the untouched neutral baseline. The file is still honoured underneath as a fallback, so if a
    future run ever writes it nothing here has to change."""
    st = load_chip_state(); h = str(_half(gw)); L = []
    U = dict(st[h]); U.update((chips or {}).get(h, {}))
    cur_ev, xi, bench = _xi_ev(squad, gw)
    cap_ev = max((p["e"] for p in xi), default=0.0)
    bench_ev = sum(p["e"] for p in bench)
    dgw_now = sum(1 for p in squad if len(_fx(p["team"], gw)) >= 2) >= 4
    cluster = _cluster_ahead(gw + 1, 3)

    def status(chip, rec):
        if U[chip] is not None: return f"Used GW{U[chip]}"
        return "RECOMMENDED ✓" if rec else "Monitoring"

    # --- Wildcard ---
    lineup_ok = CURRENT_GW >= 3
    refit = _wc_refit(squad, itb, gw); wgain = sum(_seq_ev(refit, gw + o) - _seq_ev(squad, gw + o) for o in range(HORIZON))
    swing = _swing_present(gw)
    if _half(gw) == 1:
        wc_rec = U["WC"] is None and lineup_ok and wgain > CHIP_THRESH["wc"] and swing
    else:
        wc_rec = U["WC"] is None and bool(cluster) and wgain > CHIP_THRESH["wc"]
    L.append(f"  Wildcard {h}:   {status('WC', wc_rec)}")
    L.append(f"               rebuild value: +{wgain:.0f} pts / {HORIZON} weeks vs current squad")
    L.append(f"               fixture swing next 4: {'Yes' if swing else 'No'}   |   lineup data (3+ GW): {'Yes' if lineup_ok else f'No (GW{CURRENT_GW})'}")
    if _half(gw) == 2: L.append(f"               blank/double cluster ahead: {cluster[0][1]+' GW'+str(cluster[0][0]) if cluster else 'none'}")
    L.append(f"               free transfers banked (roll through WC): {banked}")

    # --- Bench Boost ---
    end = _half_end(gw); best_future_bench = 0.0
    for w in range(gw + 1, end + 1):
        bf = sum(ev_multi(p["code"], p["name"], p["pos"], p["team"], w) for p in bench)
        best_future_bench = max(best_future_bench, bf)
    bb_rec = U["BB"] is None and bench_ev >= (CHIP_THRESH["bb_h1"] if _half(gw) == 1 else CHIP_THRESH["bb_h2"]) and (dgw_now or bench_ev >= best_future_bench - 0.5)
    L.append(f"  Bench Boost: {status('BB', bb_rec)}")
    L.append(f"               bench EV this GW: {bench_ev:.1f}{'  (DOUBLE GW)' if dgw_now else ''}   |   peak remaining this half: {max(bench_ev,best_future_bench):.1f}")

    # --- Triple Captain ---
    best_future_cap = 0.0
    for w in range(gw + 1, end + 1):
        cw = max((ev_multi(p["code"], p["name"], p["pos"], p["team"], w) for p in squad if _fx(p["team"], w)), default=0.0)
        best_future_cap = max(best_future_cap, cw)
    tc_rec = U["TC"] is None and cap_ev >= CHIP_THRESH["tc_min"] and cap_ev >= best_future_cap - 1e-9
    L.append(f"  Triple Cap:  {status('TC', tc_rec)}")
    L.append(f"               captain EV this GW: {cap_ev:.1f}   |   best remaining captain week this half: {max(cap_ev,best_future_cap):.1f}")

    # --- Free Hit ---
    blanks = sum(1 for p in squad if not _fx(p["team"], gw))
    fh_team = _wc_refit(squad, itb, gw, horizon=1); fh_gain = _seq_ev(fh_team, gw) - _seq_ev(squad, gw)
    fh_rec = U["FH"] is None and (fh_gain > CHIP_THRESH["fh"] or (_half(gw) == 2 and blanks > 4))
    L.append(f"  Free Hit:    {status('FH', fh_rec)}")
    L.append(f"               players blanking this GW: {blanks}   |   free-hit team gain: +{fh_gain:.1f} pts vs current XI")
    return L, dict(wc=wc_rec, bb=bb_rec, tc=tc_rec, fh=fh_rec)


def _seq_ev(squad, gw):
    for p in squad: p["e"] = ev_multi(p["code"], p["name"], p["pos"], p["team"], gw)
    xi, _, _ = select_xi(squad, gw)
    return sum(p["e"] for p in xi)


BANKED_THRESHOLD = {1: 4.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 0.0}     # free transfers held -> gain required


def planned_wildcard():
    """When a wildcard might be played, and how likely it is. From human_input.json:

        "planned_wildcard": {"gw": 4, "p": 0.5}     # or just {"planned_wildcard_gw": 4} for p=1

    It matters because on the wildcard week you can field any squad you like, so a transfer made
    beforehand does not shape the post-wildcard team — you would build the same one either way.
    Its value is the points it earns in the weeks you actually hold it, which is however many
    remain until the rebuild.

    But a wildcard is rarely a certainty, and treating a maybe as a fact is its own error: at p=1
    the horizon collapses to a single week and almost nothing clears the bar, which freezes you out
    of moves that are good precisely BECAUSE they might remove the need for the chip. So the
    horizon is the expectation over both branches:

        E[weeks held] = p * (wc_gw - gw) + (1 - p) * HORIZON

    At p=1 that is the full collapse; at p=0 it is the ordinary six weeks; in between it is
    proportionate, which is what "I might wildcard in week 4" actually means."""
    f = STATE / "human_input.json"
    if not f.exists():
        return None, 0.0
    try:
        d = json.load(open(f, encoding="utf-8"))
        w = d.get("planned_wildcard")
        if isinstance(w, dict) and w.get("gw"):
            return int(w["gw"]), max(0.0, min(1.0, float(w.get("p", 1.0))))
        v = d.get("planned_wildcard_gw")
        return (int(v), 1.0) if v else (None, 0.0)
    except Exception:
        return None, 0.0


def transfer_threshold_live(banked, gw, wc_used):
    """Threshold falls as free transfers pile up. Holding a transfer is only worth something while
    you can still bank it: at 1-2 you have plenty of runway, so demand a clear 4.0 gain; by 4 the
    next one is nearly forfeit; at the 5 cap the incoming transfer is lost outright, so ANY positive
    gain beats letting it expire (use it or lose it).

        1-2 banked -> 4.0     3 -> 3.0     4 -> 2.0     5 -> 0.0

    Wildcard proximity still scales that base (hold your moves for the rebuild), except at the cap —
    a 0.0 base multiplies to 0.0 anyway, so use-it-or-lose-it correctly wins."""
    t = BANKED_THRESHOLD.get(int(banked), 4.0); note = ""
    if int(banked) >= 5:
        return 0.0, " (use it or lose it — at the 5-transfer cap, the next one is forfeit)"
    if wc_used is None:
        wtc = max(0, 6 - gw) if _half(gw) == 1 and gw <= 8 else (99 if _half(gw) == 1 else (min((c[0] for c in _cluster_ahead(gw + 1, 3)), default=99) - gw))
        if wtc <= 1: t *= 2.0; note = " (×2 — wildcard imminent, banking transfers)"
        elif wtc <= 2: t *= 1.5; note = " (×1.5 — wildcard ~2 weeks out)"
        elif wtc <= 3: t *= 1.2; note = " (×1.2 — wildcard approaching)"
    if not note and int(banked) >= 3:
        note = f" ({banked} banked — bar lowered, transfers are piling up)"
    return t, note


def fixture_source_lines(next_gw):
    """Per-GW data source for fixture inputs: Pinnacle odds where published (GW+1..+3), else xG model."""
    L = []
    if not ODDS.enabled():
        L.append("  Bookmaker odds OFF — xG model for all fixtures.")
        L.append("    (market-average odds auto-enable in the live tool; set ODDS_API_KEY for Pinnacle instead)")
        return L
    L.append(f"  Bookmaker odds ON — {ODDS.source_label()}, 1X2 + O/U, overround removed ✓  (GW+4+ always xG model)")
    for off in range(1, HORIZON + 1):
        g = next_gw + off - 1
        teams = [sh for sh in FIX if FIX[sh].get(g)]
        if not teams: continue
        priced = sum(1 for sh in teams if ODDS.fixture_inputs(sh, FIX[sh][g][0], FIX[sh][g][1]))
        if priced:
            L.append(f"  GW+{off} (GW{g}): odds — {priced // 2}/{len(teams) // 2} fixtures priced")
        else:
            L.append(f"  GW+{off} (GW{g}): xG model (no odds published)")
    return L


WRAP_COLS = 54                        # matches the report's own ═ rule; fits an iPhone in portrait


def _wrap_report(lines, cols=WRAP_COLS):
    """Wrap over-wide lines so the emailed report reads on a phone without sideways scrolling.

    The report is rendered as 11px monospace in a <pre> (to_html.py), so anything past ~59 chars
    forces horizontal scroll in iPhone Mail — a third of the lines did. Each line keeps its own
    indentation, continuations hang two spaces deeper, and the ═/━ rules are left alone so the
    structure survives."""
    import textwrap
    out = []
    # Many report lines are appended as one string containing embedded newlines ("\nHEADER\n━━━"),
    # so split to PHYSICAL lines first — textwrap collapses newlines and would re-flow a heading
    # into its own underline rule.
    for raw in lines:
        for ln in str(raw).split("\n"):
            if len(ln) <= cols or not ln.strip():
                out.append(ln); continue
            stripped = ln.lstrip()
            if set(stripped) <= set("═━─"):        # structural rule, never wrap
                out.append(ln); continue
            indent = ln[:len(ln) - len(stripped)]
            # Already-deep indents (the chip block sits at 15) have little room left, so don't
            # hang continuations any further — it just shreds the text.
            sub = indent + ("  " if len(indent) <= 6 else "")
            out.extend(textwrap.wrap(stripped, width=cols, initial_indent=indent,
                                     subsequent_indent=sub,
                                     break_long_words=False, break_on_hyphens=False) or [ln])
    return out


def report(team_name, squad_def, itb, banked, chips, planned, planned_wc=None):
    # defw must be present here: best_transfer() compares a candidate's defw against the outgoing
    # player's, and POOL rows carry it — squad rows must have the same shape or that lookup KeyErrors.
    squad = [dict(name=n, pos=po, team=t, price=pr, code=code_of(n, po, t),
                  defw=FR.RATINGS.get(t, {}).get("defw", 1)) for (n, po, t, pr) in squad_def]
    gw = CURRENT_GW + 1
    rf = refresh_models()
    xi, bench, form = select_xi(squad, gw); caps = select_captain(xi)
    table, warn = trajectory(squad)
    # A possible wildcard shortens how long a transfer is yours to keep, in proportion to how
    # likely it is. Per TEAM: it is Jon's intention, and Santa Claude is a neutral benchmark that
    # never chip-shapes, so applying his plan to it would corrupt the comparison.
    _wc, _wc_p = (planned_wc if isinstance(planned_wc, tuple) else (planned_wc, 1.0))
    if _wc and _wc > gw:
        _hold_f = _wc_p * (_wc - gw) + (1 - _wc_p) * HORIZON
        _hold = max(1, min(HORIZON, int(round(_hold_f))))
    else:
        _hold, _hold_f = HORIZON, float(HORIZON)
    tv = best_transfer(squad, itb, hold=_hold)
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
    L.append("\n⚠ HUMAN CONFIRMATION (2-min review — override from the phone form)\n" + "━" * 31)
    if moves:
        L.append("  P(starts) moved >20% since last week — verify against team news:")
        for m in moves: L.append("    • " + m)
    else:
        L.append("  No >20% P(starts) moves since last week.")
    if applied:
        L.append("  Your overrides applied to THIS squad:")
        for a in applied: L.append("    ✓ " + a)
    elif OVERRIDES:
        # Don't report "none": overrides not in this squad still price the transfer pool, and
        # saying none reads as though the form never saved.
        L.append(f"  {len(OVERRIDES)} override(s) live for GW{gw}, none of them in this squad: "
                 + ", ".join(f"{o['player_name']} p60 {p_start(int(o['player_id']), o['player_name']):.2f}"
                             for o in OVERRIDES.values()) + ".")
        L.append("  They still price transfer targets and the wider pool.")
    else:
        L.append("  No overrides set — add one from the form when you know something the model can't.")
    L.append("")
    L.append("  P(START) THE MODEL IS RUNNING ON — shakiest first. Override any you know better")
    L.append("  from the form, then re-run the workflow for a revised call.")
    L.extend(pstart_review(squad, tv))
    L.append("\nFIXTURE INPUTS — DATA SOURCES\n" + "━" * 29)
    L.extend(fixture_source_lines(gw))
    L.append("\nCHIP EVALUATION\n" + "━" * 15)
    chip_lines, chip_rec = chip_evaluation(squad, itb, banked, gw, chips)
    L.extend(chip_lines)
    if any(chip_rec.values()):
        fired = [k.upper() for k, v in chip_rec.items() if v]
        L.append(f"  → RECOMMENDATION: play {', '.join(fired)} this week (confirm via the phone form). One chip per week max.")
    else:
        L.append("  → No chip this week — hold all available chips.")
    tr_thr, tr_note = transfer_threshold_live(banked, gw, load_chip_state()[str(_half(gw))]["WC"])
    L.append(f"  Transfer threshold this week: {tr_thr:.1f} pts{tr_note}")
    if _wc and _wc > gw and _hold < HORIZON:
        L.append(f"  Wildcard possible GW{_wc} at p={_wc_p:.0%}, so a transfer made now is yours "
                 f"for an expected {_hold_f:.1f} gameweeks, not {HORIZON}.")
        L.append(f"  Judged on that horizon. At p=100% it would be {_wc - gw}; the rest is the "
                 f"branch where you do not play it.")
    L.append("\nTRANSFER DECISION\n" + "━" * 17)
    if gw == 1:
        # Before the first deadline FPL gives unlimited free transfers, so the one-in-one-out engine
        # is meaningless here — the whole 15 is editable. Show its best swap as a signal of what the
        # model rates, but never as an instruction.
        L.append("  Unlimited free transfers until the GW1 deadline — the whole squad is editable,")
        L.append("  so the single-swap engine does not apply. Pick the 15 you want.")
        if tv and tv["gain"] > 0:
            L.append(f"  FYI, the biggest single upgrade it can see: {tv['out']['name']} → "
                     f"{tv['inn']['name']} ({tv['inn']['team']} £{tv['inn']['price']}), "
                     f"{tv['gain']:+.1f} over {tv['hold']} GWs — a signal, not a recommendation.")
    elif tv and tv["gain"] > 0:
        o, i = tv["out"], tv["inn"]
        if banked >= 1:
            # Decide on the SAME threshold the report prints above (tr_thr). This used to be a
            # hardcoded 2.0, so the report stated a 4.0 bar and then greenlit transfers clearing 2.0.
            dec = ("TRANSFER ✓ (free)" if tv["gain"] > tr_thr
                   else f"BANK (gain {tv['gain']:+.1f} below the {tr_thr:.1f} threshold)")
        else:
            take, why = should_take_hit(tv, squad, gw)
            dec = f"TAKE −4 HIT ✓ — {why}" if take else f"BANK — {why}"
        L.append(f"  Best target: OUT {o['name']} ({o['pos']} {o['team']}) → IN {i['name']} ({i['team']} £{i['price']})")
        L.append(f"    P(60+) assumed: {o['name']} {p_start(o['code'], o['name']):.2f} → "
                 f"{i['name']} {p_start(i['code'], i['name']):.2f} — if you know better, override "
                 f"in the form and re-run for a revised call")
        L.append(f"    {tv['signal']} · effective-out adjusted for bench cover · {tv['hold']}-GW hold")
        L.append(f"    gain: GW+1 {tv['gw1']:+.1f} · GW+1&2 {tv['gw1']+tv['gw2']:+.1f} · full {tv['hold']}-GW {tv['gain']:+.1f}")
        L.append(f"    → {dec}    (budget after £{itb - (i['price']-o['price']):.1f}m ITB, {banked} banked)")
    else:
        L.append("  No improving transfer available — BANK")
    L.append("\nWATCHLIST (monitor, not acting)\n" + "━" * 31)
    for w in watchlist(squad): L.append("  • " + w)
    L.append("\nCAPTAIN — highest-EV starter (doubles)\n" + "━" * 7)
    if caps:
        c0 = caps[0][0]; c1 = caps[1][0] if len(caps) > 1 else None
        L.append(f"  Captain: {c0['name']} — EV {caps[0][1]:.1f} (×2 = {2*caps[0][1]:.1f}), {c0['team']} vs {FIX[c0['team']].get(gw,('?',))[0]}")
        if c1: L.append(f"  Vice:    {c1['name']} — EV {caps[1][1]:.1f}")
    L.append(f"\nSTARTING XI — {form[0]}-{form[1]}-{form[2]}\n" + "━" * 24)
    for pos in ["GK", "DEF", "MID", "FWD"]:
        L.append(f"  {pos}: " + ", ".join(f"{p['name']}" for p in xi if p["pos"] == pos))
    L.append("  Bench: " + ", ".join(p["name"] for p in bench))
    L.append("\nPROJECTED WEEKLY POINTS (XI + captain + auto-sub)\n" + "━" * 27)
    L.append("  " + "  ".join(f"GW{r[0]}" for r in table))
    L.append("  " + "  ".join(f"{r[4]:4.0f}" for r in table) + f"   (min {min(r[4] for r in table):.0f})")
    L.append(f"  GW{table[0][0]} = XI {table[0][1]:.0f} + captain bonus {table[0][2]:.0f} + auto-sub {table[0][3]:.1f}  (auto-sub small by design)")
    for lvl, g, msg in warn[:3]: L.append(f"  [{lvl}] GW{g}: {msg}")
    L.append("\nPLANNED TRANSFERS\n" + "━" * 17)
    for pt in planned: L.append("  " + pt)
    L.append("═" * 54)
    return "\n".join(_wrap_report(L))


if __name__ == "__main__":
    ODDS.set_source("fd")          # live tool uses market-average odds (no key); a key still wins if set
    print("⟳ Refreshing models from live FPL API (detect → ingest → refresh)...", flush=True)
    # these go straight to stdout rather than through report(), so wrap them here too
    for line in _wrap_report(["   " + l for l in auto_ingest_and_refresh()]): print(line)
    print()
    # LOCKED 2026-08-13, ahead of the GW1 deadline. Chosen by optimize_v2.py on the neutral
    # season-long objective (GW1-8 XI + captain + auto-sub), with the human overrides applied and
    # backup keepers correctly zeroed: £100.0m exactly, GW1-8 EV 534.9 vs the previous squad's 497.3.
    # Deliberately unshaped — no chip tilt — because this team exists to follow the engine's weekly
    # recommendations precisely, so its baseline should reflect the model and nothing else.
    # Both squads pulled from the live API by fetch_squads.py on 2026-09-01, after GW2.
    # Do not hand-edit these again — re-run `python scripts/fetch_squads.py` and paste, or the
    # engine goes back to recommending transfers that have already been made.
    # Santa Claude (entry 4180925): took the GW2 recommendation, Mosquera -> De Cuyper. £0.9m ITB.
    SANTA = [("Leno","GK","FUL",4.5),("Sánchez","GK","CHE",4.9),
             ("Van Hecke","DEF","TOT",5.0),("De Cuyper","DEF","BHA",4.7),("Calafiori","DEF","ARS",5.6),
             ("Gvardiol","DEF","MCI",5.6),("Senesi","DEF","TOT",6.0),
             ("Schade","MID","BRE",6.0),("Palmer","MID","CHE",9.6),("Mbeumo","MID","MUN",8.0),
             ("Gomez","MID","BHA",5.0),("Sarr","MID","CRY",6.4),
             ("Haaland","FWD","MCI",15.5),("Calvert-Lewin","FWD","LEE",6.0),("Mateta","FWD","CRY",6.4)]
    # Village Idiots (entry 1169767). Rebuilt before the GW1 deadline under unlimited transfers, so
    # it bears little resemblance to the 13 August draft; no transfers since, and GW2 was rolled,
    # hence 2 free. Bench Boost was played in GW1 — not GW2 as the old plan here assumed.
    HUMAN = [("Kinsky","GK","TOT",4.5),("Verbruggen","GK","BHA",4.5),
             ("Shaw","DEF","MUN",4.5),("Gabriel","DEF","ARS",8.0),("Calafiori","DEF","ARS",5.6),
             ("Ajer","DEF","BRE",4.5),("F.Kadıoğlu","DEF","BHA",4.4),
             ("Schade","MID","BRE",6.0),("Mbeumo","MID","MUN",8.0),("Tzolis","MID","ARS",6.5),
             ("Semenyo","MID","MCI",8.5),("Hinshelwood","MID","BHA",6.0),
             ("João Pedro","FWD","CHE",7.6),("Haaland","FWD","MCI",15.5),("Calvert-Lewin","FWD","LEE",6.0)]
    print(report("SANTA CLAUDE (AI team)", SANTA, itb=0.9, banked=1,
                 chips={}, planned_wc=None, planned=[
                     "Neutral baseline — follow this engine's weekly call exactly, no chip shaping.",
                     "All four chips still held. 141 pts, overall 3.15m after GW2.",
                     "Spurs pair (Senesi, Van Hecke) held on model EV only: new manager, WC "
                     "returnees and the Spence rumour are invisible to the model. Revisit ~GW5 "
                     "once lineups settle.",
                     "£0.9m ITB from the Mosquera → De Cuyper move."]))
    print()
    print(report("JON'S TEAM", HUMAN, itb=0.0, banked=2,
                 chips={"1": {"BB": 1}}, planned_wc=planned_wildcard(), planned=[
                     "BENCH BOOST PLAYED GW1. 163 pts, overall 846k after GW2 — the whole 22-pt "
                     "lead over Santa Claude came in GW1; GW2 was 87 apiece.",
                     "Remaining first-half chips: Wildcard, Triple Captain, Free Hit. The old plan "
                     "here was a GW3/GW4 Wildcard — still open, and GW3's deadline is Fri 4 Sep.",
                     "Two free transfers: GW2 was rolled.",
                     "£0.0m ITB."]))
