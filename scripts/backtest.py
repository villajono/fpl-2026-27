#!/usr/bin/env python3
"""
backtest.py — walk-forward backtesting harness for 2025-26.

Purpose: (1) validate the weekly management tool's decisions, (2) extract signal-accuracy
learnings to improve 2026-27 BEFORE GW1. Not a scorecard — a feedback loop.

WALK-FORWARD PRINCIPLE: simulating GW t, the model sees ONLY rows with GW < t. Fixtures
(who plays whom, home/away) are known in advance and are NOT future data; points/minutes are.

Self-contained by necessity: the production ev_v2 reads the whole 2025-26 file and its
team ratings are the 2026-27 set, so this harness recomputes player rates and team strengths
from GW<t only. It reuses V2's *formulas* (imports the pure DC/recency helpers) and ports
weekly.py's decision rules VERBATIM with identical constants, so it validates the real logic.

CAVEATS (printed in every output):
  - One season only; findings are preliminary, not cross-validated (no 2024-25 data exists).
  - V2 was partly calibrated on 2025-26 -> some circularity in the scorecard.
  - Starting squad is a fabricated 'plausible last-year' template (no true pre-season prior).
  - 'Optimal hindsight' is a ceiling to understand headroom, not a fair target.
"""
from __future__ import annotations
from pathlib import Path
import math, numpy as np, pandas as pd
import ev_v2 as V, history as H            # V: pure helpers only (_pois_surv/_nb_surv/DC_THRESHOLD); H: recency fns

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POSN = {"GK": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
CS_C = 1.0                                 # clean-sheet decay constant (~ev_v2's calibrated 1.016; fixed as a method scalar)
MIN_MINUTES = 450
USE_BONUS = True            # A/B switch for the bonus term — see calibrate.py
USE_EXTRA = True            # goals conceded + yellows, A/B'd in calibrate.py
HOME_ADV = 1.10             # attacking multiplier at home; away is 2 - this. Swept in calibrate.py.
FREE_THR = 2.0                             # simulate(): flat control threshold (simulate_chips uses the live graduated rule)
FT_CAP = 5                                 # FPL banks up to FIVE free transfers (since 2024-25). Was 2 —
                                           # which capped `banked` at 2 and made the 3/4/5 threshold tiers unreachable.
HORIZON = 6                                # weekly.py transfer evaluation window
DECAY = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.40, 6: 0.25}

# ---- fabricated 2025-26 pre-season team priors (plausible last-year tiers; att>1 = strong attack, defw>1 = leaky) ----
PRIOR = {  # att, defw
 "LIV":(1.30,0.80),"MCI":(1.32,0.78),"ARS":(1.20,0.75),"CHE":(1.12,0.92),"NEW":(1.10,0.88),
 "TOT":(1.10,1.02),"AVL":(1.06,0.95),"MUN":(1.05,1.00),"BHA":(1.02,1.00),"BOU":(0.98,1.05),
 "CRY":(0.95,0.95),"FUL":(0.95,1.00),"BRE":(1.00,1.08),"EVE":(0.90,0.98),"WHU":(0.98,1.10),
 "WOL":(0.92,1.12),"NFO":(0.95,1.00),"SUN":(0.80,1.15),"LEE":(0.82,1.18),"BUR":(0.78,1.20)}
PRIOR_K = 5.0                              # prior's equivalent games; observed overtakes it after ~5 played


def price_prior(pos, p):
    """Pre-season per-90 belief from price alone. Price is set by FPL from 2024-25, so it's
    legitimate pre-season info (non-leaking). Coefficients are hand-set football priors, NOT fit
    on 2025-26 outcomes. Washes out after ~5 games of real data (see rates() blend)."""
    if pos == "FWD": return dict(xG90=max(0, p - 4.0) * 0.050, xA90=max(0, p - 4.0) * 0.013, DC90=0.0, sv90=0.0)
    if pos == "MID": return dict(xG90=max(0, p - 4.5) * 0.028, xA90=max(0, p - 4.5) * 0.028, DC90=4.0, sv90=0.0)
    if pos == "DEF": return dict(xG90=max(0, p - 4.0) * 0.006, xA90=max(0, p - 4.0) * 0.010, DC90=8.0, sv90=0.0)
    return dict(xG90=0.0, xA90=0.0, DC90=0.0, sv90=3.0)                 # GK


# ============================================================= DATA
class Season:
    def __init__(self):
        g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
        for c in ["minutes","total_points","expected_goals","expected_assists","goals_scored",
                  "assists","bps","bonus","defensive_contribution","saves","clean_sheets","value","starts",
                  "yellow_cards"]:
            g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
        t = pd.read_csv(RAW / "teams_2025-26.csv")
        self.id2sh = dict(zip(t.id, t.short_name)); self.name2sh = dict(zip(t.name, t.short_name))
        g["short"] = g.team.map(self.name2sh); g["opp"] = g.opponent_team.map(self.id2sh)
        self.g = g
        # element metadata (stable)
        meta = g.sort_values("GW").groupby("element").agg(
            name=("name","first"), pos=("position","first"), short=("short","last"))
        self.meta = {int(e): dict(name=r["name"], pos=r["pos"], short=r["short"]) for e, r in meta.iterrows()}
        # per-(element,gw) row for O(1) scoring
        self.rows = {(int(r.element), int(r.GW)): r for r in g.itertuples()}
        # per-element arrays (GW-sorted) for fast walk-forward slicing — avoids re-masking the 29k frame
        self.by_el = {}
        for el, sub in g.groupby("element"):
            sub = sub.sort_values("GW")
            self.by_el[int(el)] = dict(
                gw=sub.GW.to_numpy(), minutes=sub.minutes.to_numpy(), xG=sub.expected_goals.to_numpy(),
                xA=sub.expected_assists.to_numpy(), dc=sub.defensive_contribution.to_numpy(),
                saves=sub.saves.to_numpy(), value=sub.value.to_numpy(), tp=sub.total_points.to_numpy(),
                goals=sub.goals_scored.to_numpy(), assists=sub.assists.to_numpy(),
                bps=sub.bps.to_numpy(), bonus=sub.bonus.to_numpy(),
                yellow=sub.yellow_cards.to_numpy(),
                # who he faced, so past xG can be normalised for fixture ease the same way
                # production now does — otherwise the harness calibrates a different model
                opp=sub.opp.to_numpy(), home=sub.was_home.to_numpy())
        self._min_cache = {}; self._price_cache = {}
        # schedule: sched[short][gw] -> list of (opp_short, home)
        self.sched = {}
        fx = g.groupby(["short","GW","opp","was_home"]).size().reset_index()
        for r in fx.itertuples():
            self.sched.setdefault(r.short, {}).setdefault(int(r.GW), []).append((r.opp, bool(r.was_home)))
        self._rate_cache = {}; self._team_cache = {}; self._posavg_cache = {}; self._pool_cache = {}

    def fixtures(self, short, gw):
        return self.sched.get(short, {}).get(gw, [])

    def actual(self, element, gw, field="total_points"):
        r = self.rows.get((element, gw))
        return float(getattr(r, field)) if r is not None else None       # None = blank (no fixture / didn't exist)

    # ---- walk-forward team strength (games with GW <= cut) ----
    def team_strength(self, cut):
        if cut in self._team_cache: return self._team_cache[cut]
        sub = self.g[self.g.GW <= cut]
        out = {}
        if len(sub):
            m = sub.groupby(["short","GW","opp","was_home"], as_index=False).expected_goals.sum().rename(columns={"expected_goals":"xgf"})
            rev = m.rename(columns={"short":"opp","opp":"short","xgf":"xga"})[["GW","short","opp","xga"]]
            m = m.merge(rev, on=["GW","short","opp"], how="left")
            ag = m.groupby("short").agg(n=("GW","size"), xgf=("xgf","sum"), xga=("xga","sum"))
            lm_f = (ag.xgf/ag.n).mean(); lm_a = (ag.xga/ag.n).mean()
            for sh, r in ag.iterrows():
                att_o = (r.xgf/r.n)/lm_f if lm_f > 0 else 1.0; defw_o = (r.xga/r.n)/lm_a if lm_a > 0 else 1.0
                pa, pd_ = PRIOR.get(sh, (1.0,1.0)); w = r.n/(r.n+PRIOR_K)
                out[sh] = ( (1-w)*pa + w*att_o, (1-w)*pd_ + w*defw_o )
        for sh in self.id2sh.values():
            if sh not in out: out[sh] = PRIOR.get(sh, (1.0,1.0))
        self._team_cache[cut] = out; return out

    # ---- walk-forward position-average rates (players with >=MIN cumulative minutes, GW<=cut) ----
    def pos_avg(self, cut):
        if cut in self._posavg_cache: return self._posavg_cache[cut]
        sub = self.g[(self.g.GW <= cut) & (self.g.minutes > 0)]
        acc = {p: {"xG90":[], "xA90":[], "DC90":[], "sv90":[]} for p in ["GK","DEF","MID","FWD"]}
        for el, s in sub.groupby("element"):
            mins = s.minutes.sum()
            if mins < MIN_MINUTES: continue
            pos = self.meta[int(el)]["pos"]; n90 = mins/90.0
            acc[pos]["xG90"].append(s.expected_goals.sum()/n90); acc[pos]["xA90"].append(s.expected_assists.sum()/n90)
            acc[pos]["DC90"].append(s.defensive_contribution.sum()/n90); acc[pos]["sv90"].append(s.saves.sum()/n90)
        res = {p: {k: (float(np.mean(v)) if v else 0.0) for k,v in d.items()} for p,d in acc.items()}
        self._posavg_cache[cut] = res; return res

    # ---- walk-forward per-90 rates: price-prior (pre-season, non-leaking) blended with observed recency ----
    def rates(self, element, cut):
        key = (element, cut)
        if key in self._rate_cache: return self._rate_cache[key]
        pos = self.meta[element]["pos"]; a = self.by_el[element]
        sel = (a["gw"] <= cut) & (a["minutes"] > 0)
        games = [dict(minutes=float(a["minutes"][i]), xG=float(a["xG"][i]), xA=float(a["xA"][i]),
                      dc=float(a["dc"][i]), saves=float(a["saves"][i]),
                      bonus=float(a["bonus"][i]), yellow=float(a["yellow"][i]),
                      opp=a["opp"][i], home=bool(a["home"][i])) for i in np.nonzero(sel)[0]]
        mins = sum(x["minutes"] for x in games)
        prior = price_prior(pos, self.price(element, cut))                # pre-season belief from price (2024-25 informed)
        # Fixture-normalise past attacking output, exactly as ev_v2._game_fixture_mult does.
        # Ratings are as of `cut`, so this stays walk-forward clean.
        _ts = self.team_strength(cut)
        _fm = lambda gm: (_ts.get(gm["opp"], (1.0, 1.0))[1] * (1.05 if gm["home"] else 0.95))
        obs = H.recency_weighted_rates(games, pos, _fm) if games else None
        w = mins / (mins + 450.0)                                         # ~5 full games to reach 50/50 with the prior
        bl = lambda k: (1 - w) * prior[k] + w * (obs[k] if obs else prior[k])
        # Bonus per APPEARANCE, not per 90: it is awarded for a performance, not accrued by the
        # minute. Recency-weighted on the same half-life as xG so form carries through.
        _bw = [0.5 ** ((len(games) - 1 - i) / H.HALF_LIFE["xG"]) for i in range(len(games))]
        bon = (sum(_bw[i] * games[i]["bonus"] for i in range(len(games))) / sum(_bw)) if games else 0.0
        yel = (sum(_bw[i] * games[i]["yellow"] for i in range(len(games))) / sum(_bw)) if games else 0.0
        r = dict(bonus_app=bon, yellow_app=yel,
                 xG90=bl("xG90"), xA90=bl("xA90"), DC90=bl("DC90"), sv90=bl("sv90"), pos=pos, minutes=mins,
                 thin=mins < MIN_MINUTES, dc_history=[x["dc"] for x in games],
                 n60=sum(1 for x in games if x["minutes"] >= 60), games=len(games))
        self._rate_cache[key] = r; return r

    def price(self, element, cut):
        key = (element, cut)
        if key in self._price_cache: return self._price_cache[key]
        a = self.by_el[element]; sel = a["gw"] <= cut
        v = float(a["value"][sel][-1]) if sel.any() else float(a["value"][0])
        p = v / 10.0; self._price_cache[key] = p; return p

    # ---- walk-forward minutes model (p60 / cameo / partial), recency over 'starts' GW<=cut ----
    def minutes(self, element, cut):
        key = (element, cut)
        if key in self._min_cache: return self._min_cache[key]
        a = self.by_el[element]; sel = a["gw"] <= cut; mins = a["minutes"][sel]
        played = mins[mins > 0]
        if not len(played):
            # No appearance yet — see ev_v2.NO_HISTORY_P60. Was 0.55 on no evidence.
            r = dict(p60=V.NO_HISTORY_P60, p_cameo=V.NO_HISTORY_CAMEO, partial=30.0)
            self._min_cache[key] = r; return r
        starts = [dict(minutes=float(m)) for m in mins]                   # recency_start_prob keys on 'minutes'>=60
        p = H.recency_start_prob(starts, half_life=8)
        cam = played[(played >= 1) & (played < 60)]
        p_cameo = min(len(cam) / max(len(mins), 1), 0.15)
        partial = float(cam.mean()) if len(cam) else 30.0
        r = dict(p60=round(min(max(p if p is not None else V.NO_HISTORY_P60, 0.02), 0.98), 2), p_cameo=p_cameo, partial=partial)
        self._min_cache[key] = r; return r


# ============================================================= EV (mirrors ev_v2.compute_ev_v2, walk-forward inputs)
def _p_dc(rates, expected_minutes):
    pos = rates["pos"]; thr = V.DC_THRESHOLD.get(pos, 99)
    if thr >= 99 or rates["DC90"] <= 0: return 0.0
    mu = rates["DC90"] * expected_minutes/90.0
    hist = [d for d in rates.get("dc_history", []) if d is not None]
    if len(hist) >= 5:
        m, var = float(np.mean(hist)), float(np.var(hist))
        if var > m*1.25 and m > 0: return V._nb_surv(thr, mu, (var/m)*mu)
    return V._pois_surv(thr, mu)


def cs_prob(team_defw, opp_att, home):
    return math.exp(-CS_C * opp_att * team_defw * (0.90 if home else 1.10))


def ev(season, element, cut, opp, home):
    """Expected points for `element` in a fixture vs `opp` (home?), using only GW<=cut data."""
    m = season.meta[element]; pos = m["pos"]; ts = season.team_strength(cut)
    r = season.rates(element, cut); mp = season.minutes(element, cut)
    team_defw = ts.get(m["short"], (1.0,1.0))[1]; opp_att, opp_defw = ts.get(opp, (1.0,1.0))
    csp = cs_prob(team_defw, opp_att, home); cpts = CS_PTS[pos]
    save_pts = 1.0/3.0 if pos == "GK" else 0.0
    att_f = opp_defw * (HOME_ADV if home else 2 - HOME_ADV)
    sv_f = opp_att * ((2 - HOME_ADV) if home else HOME_ADV)
    xg, xa, sv = r["xG90"], r["xA90"], r["sv90"]
    pdf = _p_dc(r, 90); pdp = _p_dc(r, mp["partial"])
    gp = V.GOAL_PTS.get(pos, 5)            # 4 FWD / 5 MID / 6 DEF-GK — was hardcoded 6 here too
    bon = r.get("bonus_app", 0.0) if USE_BONUS else 0.0
    conc = -0.5 * (-math.log(max(csp, 1e-6))) if (USE_EXTRA and pos in ("GK", "DEF")) else 0.0
    yel = -r.get("yellow_app", 0.0) if USE_EXTRA else 0.0
    ev_full = csp*cpts + 2 + xg*gp*att_f + xa*3*att_f + pdf*2 + sv*save_pts*sv_f + bon + conc + yel
    ev_part = (1 + (mp["partial"]/90.0)*(xg*gp*att_f + xa*3*att_f + sv*save_pts*sv_f + conc)
               + pdp*2 + 0.4*bon + 0.5*yel)
    return mp["p60"]*ev_full + mp["p_cameo"]*ev_part


def ev_multi(season, element, cut, gw):
    """EV for a specific future gw (may be blank -> 0, or DGW -> sum of both fixtures)."""
    fx = season.fixtures(season.meta[element]["short"], gw)
    return sum(ev(season, element, cut, opp, home) for opp, home in fx)


def p_start(season, element, cut):
    return season.minutes(element, cut)["p60"]

def p_zero(season, element, cut):
    mp = season.minutes(element, cut); return max(0.0, 1 - mp["p60"] - mp["p_cameo"])


# ============================================================= DECISION ENGINE (ported from weekly.py, identical rules)
def price(season, element, cut): return season.price(element, cut)


def select_xi(els, season, cut, gw):
    e = {x: ev_multi(season, x, cut, gw) for x in els}
    P = {x: season.meta[x]["pos"] for x in els}
    gks = [x for x in els if P[x] == "GK"]
    if not gks: return None
    gk = max(gks, key=lambda x: e[x])
    D = sorted([x for x in els if P[x] == "DEF"], key=lambda x: -e[x])
    M = sorted([x for x in els if P[x] == "MID"], key=lambda x: -e[x])
    F = sorted([x for x in els if P[x] == "FWD"], key=lambda x: -e[x])
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3 and len(D) >= d and len(M) >= m and len(F) >= f:
                xi = [gk] + D[:d] + M[:m] + F[:f]; s = sum(e[x] for x in xi)
                if best is None or s > best[0]: best = (s, xi)
    if best is None: return None
    _, xi = best
    benchout = sorted([x for x in els if P[x] != "GK" and x not in xi], key=lambda x: -e[x])
    benchgk = [x for x in gks if x != gk]
    xi_sorted = sorted(xi, key=lambda x: -e[x])                    # captain/vice = highest-EV players, any position
    return dict(xi=xi, bench=benchgk + benchout, captain=xi_sorted[0], vice=xi_sorted[1], ev=e, xi_ev=best[0])


def _pool(season, cut, gw):
    key = (cut, gw)
    if key in season._pool_cache: return season._pool_cache[key]
    els = []
    for el, a in season.by_el.items():
        if a["minutes"][a["gw"] <= cut].sum() < MIN_MINUTES: continue    # thin filter (mirrors build_pool)
        if any(season.fixtures(season.meta[el]["short"], gw + o) for o in range(1, HORIZON + 1)):
            els.append(el)
    season._pool_cache[key] = els; return els


# Anti-churn: it costs real EV to sell a player you recently bought (you're wasting the earlier
# transfer, usually chasing noise). Backtest showed 50% of transfers reversed a prior buy — incl. a
# 1-GW Xhaka flip. This penalty (subtracted from a transfer's gain) makes the engine commit for a
# holding period. Tunable; 0 reproduces Transfer Engine 1.0.
#
# NOT VALIDATED — default OFF (2026-08-13). Measured over the full 2025-26 season across five
# different starting squads: +46, +48, +1, -3, -6 (positive in 3/5, mean +17). Half the penalty
# scored WORSE than none (-20) while double scored identically to 1x, i.e. the response is
# non-monotonic — the signature of path-dependence, not a mechanism. It does suppress the
# pathological <2-GW flips (1 -> 0), so it survives as a variance guard, but there is no evidence
# it gains points. Enable explicitly with simulate(..., anti_churn=True) if experimenting.
def churn_penalty(held_gws):
    if held_gws >= 6: return 0.0
    if held_gws >= 4: return 2.0
    if held_gws >= 2: return 5.0
    return 10.0                    # <2 GW: effectively blocks flipping a just-bought player


def best_transfer(squad, itb, season, cut, gw, hold=HORIZON, acquired=None):
    held = set(squad); pool = _pool(season, cut, gw)
    club = {}
    for e in squad: club[season.meta[e]["short"]] = club.get(season.meta[e]["short"], 0) + 1
    best = None
    for out in squad:
        po = season.meta[out]; pz = p_zero(season, out, cut)
        pen = churn_penalty(gw - acquired.get(out, gw - 99)) if acquired else 0.0   # cost of selling `out` now
        out_ev = [ev_multi(season, out, cut, gw + o) for o in range(1, hold + 1)]
        same = [q for q in squad if season.meta[q]["pos"] == po["pos"] and q != out]
        bc = min(same, key=lambda q: price(season, q, cut)) if same else None
        bc_ev = [ev_multi(season, bc, cut, gw + o) for o in range(1, hold + 1)] if bc else [0.0] * hold
        eff_out = [out_ev[o] + pz * bc_ev[o] for o in range(hold)]
        opr = price(season, out, cut)
        for c in pool:
            if c in held or season.meta[c]["pos"] != po["pos"]: continue
            cpr = price(season, c, cut)
            if cpr > opr + itb + 1e-9: continue
            csh = season.meta[c]["short"]
            if club.get(csh, 0) + (0 if csh == po["short"] else 1) > 3: continue
            cev = [ev_multi(season, c, cut, gw + o) for o in range(1, hold + 1)]
            diff = [cev[o] - eff_out[o] for o in range(hold)]
            gain = sum(diff) - pen                                                  # churn-adjusted gain
            if best is None or gain > best["gain"]:
                best = dict(out=out, inn=c, gain=gain, gw1=diff[0], gw2=(diff[1] if hold > 1 else 0.0),
                            price_out=opr, price_in=cpr)
    return best


def _has_dgw(season, short, gw): return len(season.fixtures(short, gw)) >= 2


def _can_field_xi(squad, season, cut, gw):
    a = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for e in squad:
        if season.fixtures(season.meta[e]["short"], gw) and p_start(season, e, cut) > 0.5: a[season.meta[e]["pos"]] += 1
    return a["GK"] >= 1 and a["DEF"] >= 3 and a["MID"] >= 2 and a["FWD"] >= 1 and sum(a.values()) >= 11


def should_take_hit(tv, squad, season, cut, gw):
    if tv is None: return False
    if _has_dgw(season, season.meta[tv["inn"]]["short"], gw) and tv["gw1"] > 4.0: return True
    if not _can_field_xi(squad, season, cut, gw): return True
    return tv["gw1"] + tv["gw2"] > 6.0


# ============================================================= FAITHFUL FPL SCORER (actual points + autosubs + captain)
def _played(season, e, gw): return (season.actual(e, gw, "minutes") or 0) > 0
def _pts(season, e, gw): return season.actual(e, gw) or 0.0
MAXF = {"DEF": 5, "MID": 5, "FWD": 3}


def _autosub(season, gw, xi, bench):
    pos = lambda e: season.meta[e]["pos"]
    gk = [e for e in xi if pos(e) == "GK"][0]; bgk = [e for e in bench if pos(e) == "GK"]
    final_gk = gk if _played(season, gk, gw) else (bgk[0] if bgk and _played(season, bgk[0], gw) else gk)
    out_start = [e for e in xi if pos(e) != "GK"]
    final = [e for e in out_start if _played(season, e, gw)]
    def cnt(lst):
        c = {"DEF": 0, "MID": 0, "FWD": 0}
        for e in lst: c[pos(e)] += 1
        return c
    for b in [e for e in bench if pos(e) != "GK"]:
        if len(final) >= 10: break
        if not _played(season, b, gw): continue
        c = cnt(final + [b])
        if all(c[k] <= MAXF[k] for k in c): final.append(b)
    return [final_gk] + final


def score(season, gw, xi, bench, captain, vice):
    final = _autosub(season, gw, xi, bench)
    total = sum(_pts(season, e, gw) for e in final)
    cap = captain if _played(season, captain, gw) else vice
    if _played(season, cap, gw): total += _pts(season, cap, gw)       # captain doubles (points counted twice)
    return total, final


# ============================================================= WALK-FORWARD SIMULATION
def simulate(season, start_squad, gw_from, gw_to, verbose=False, anti_churn=False,
             planned_wc=None, wc_horizon=True):
    """planned_wc: the gameweek the manager intends to wildcard, known in advance.

    wc_horizon controls the behaviour under test. A transfer made the week before a rebuild owns
    only the weeks until that rebuild, because the wildcard replaces the squad regardless. With
    wc_horizon=True the transfer evaluation horizon collapses accordingly; with False it keeps
    judging every move over the full six weeks, which is what weekly.py did before. Running the
    same season both ways is the only honest test of that change."""
    squad = list(start_squad); itb = round(100.0 - sum(price(season, e, 0) for e in start_squad), 1)
    ft = 1; log = []
    acquired = {e: 0 for e in start_squad}                            # el -> gw acquired (for anti-churn)
    for gw in range(gw_from, gw_to + 1):
        cut = gw - 1                                                  # sees only GW < gw
        pre = select_xi(squad, season, cut, gw)
        no_tr_pts, _ = score(season, gw, pre["xi"], pre["bench"], pre["captain"], pre["vice"])
        if planned_wc and gw == planned_wc:
            # Wildcard week: unlimited transfers, no hit, and the free transfer is not consumed.
            squad = wildcard_refit(season, squad, itb, cut, gw)
            itb = round(100.0 - sum(price(season, e, cut) for e in squad), 1)
            for e in squad: acquired.setdefault(e, gw)
            post = select_xi(squad, season, cut, gw)
            pts, _final = score(season, gw, post["xi"], post["bench"], post["captain"], post["vice"])
            ft = min(FT_CAP, ft + 1)
            log.append(dict(gw=gw, squad_pts=pts, raw_pts=pts, hit=0, no_transfer_pts=no_tr_pts,
                            optimal_pts=_optimal_gw(season, squad, itb, gw), made=True, wildcard=True,
                            xi=list(post["xi"]), captain_el=post["captain"], transfer=None,
                            out_el=None, in_el=None, tv_gain_pred=0.0, tv_gain_actual=pts - no_tr_pts,
                            captain=season.meta[post["captain"]]["name"],
                            captain_pts=_pts(season, post["captain"], gw), ft=ft, itb=itb))
            if verbose:
                print(f'GW{gw:>2}: {pts:>5.1f} (WILDCARD) | no-tr {no_tr_pts:>5.1f}')
            continue
        hold = HORIZON
        if wc_horizon and planned_wc and gw < planned_wc:
            hold = max(1, min(HORIZON, planned_wc - gw))
        tv = best_transfer(squad, itb, season, cut, gw, hold=hold,
                           acquired=acquired if anti_churn else None)
        made, hit = False, 0
        if tv is not None:
            # The LIVE graduated threshold, not the flat FREE_THR — weekly.py rejects a marginal
            # move at 4.8 where a flat 2.0 would take it, and the whole question here is whether a
            # short-horizon gain clears the bar. Testing it against a different bar tests nothing.
            wtc = (planned_wc - gw) if (planned_wc and gw < planned_wc) else 99
            thr = transfer_threshold(wtc, ft)
            if ft >= 1 and tv["gain"] > thr: made = True
            elif should_take_hit(tv, squad, season, cut, gw): made, hit = True, 4
        if made:
            squad = [tv["inn"] if e == tv["out"] else e for e in squad]
            acquired[tv["inn"]] = gw
            itb = round(itb + tv["price_out"] - tv["price_in"], 1)
            if hit == 0: ft -= 1
        ft = min(FT_CAP, ft + 1)
        post = select_xi(squad, season, cut, gw)
        pts, final = score(season, gw, post["xi"], post["bench"], post["captain"], post["vice"])
        opt_pts = _optimal_gw(season, squad, itb, gw)
        log.append(dict(gw=gw, squad_pts=pts - hit, raw_pts=pts, hit=hit, no_transfer_pts=no_tr_pts,
                        optimal_pts=opt_pts, made=made, xi=list(post["xi"]), captain_el=post["captain"],
                        transfer=((season.meta[tv["out"]]["name"], season.meta[tv["inn"]]["name"]) if made else None),
                        out_el=(tv["out"] if made else None), in_el=(tv["inn"] if made else None),
                        tv_gain_pred=(tv["gain"] if tv else 0.0), tv_gain_actual=(pts - no_tr_pts) if made else 0.0,
                        captain=season.meta[post["captain"]]["name"], captain_pts=_pts(season, post["captain"], gw),
                        ft=ft, itb=itb))
        if verbose:
            tstr = f'{season.meta[tv["out"]]["name"]}->{season.meta[tv["inn"]]["name"]}(g{tv["gain"]:.1f})' if made else 'bank'
            print(f'GW{gw:>2}: {pts-hit:>5.1f} (hit{hit}) | no-tr {no_tr_pts:>5.1f} | opt {opt_pts:>5.1f} | '
                  f'C:{season.meta[post["captain"]]["name"][:11]:<11}={_pts(season,post["captain"],gw):>3.0f} | {tstr}')
    return log


def _optimal_gw(season, squad, itb, gw):
    """Ceiling: best single legal transfer chosen with hindsight to maximise THIS gw's actual XI score."""
    def sc(sq):
        d = select_xi(sq, season, gw - 1, gw)
        if d is None: return -1
        final = _autosub(season, gw, d["xi"], d["bench"])
        base = sum(_pts(season, e, gw) for e in final)
        cap = max(final, key=lambda e: _pts(season, e, gw)) if final else None
        return base + (_pts(season, cap, gw) if cap else 0)
    best = sc(squad); pool = _pool(season, gw - 1, gw); held = set(squad)
    club = {}
    for e in squad: club[season.meta[e]["short"]] = club.get(season.meta[e]["short"], 0) + 1
    for out in squad:
        opr = price(season, out, gw - 1); po = season.meta[out]
        for c in pool:
            if c in held or season.meta[c]["pos"] != po["pos"]: continue
            if price(season, c, gw - 1) > opr + itb + 1e-9: continue
            csh = season.meta[c]["short"]
            if club.get(csh, 0) + (0 if csh == po["short"] else 1) > 3: continue
            v = sc([c if e == out else e for e in squad])
            if v > best: best = v
    return best


# ============================================================= STARTING SQUAD (fabricated 'plausible last-year' template)
# Explicit 11-man core a good manager would have started 2025-26 with (from 2024-25 form), ~£81m,
# then cheapest-fill the last 4 slots (1 DEF, 2 MID, 1 FWD) under £100m. Deliberately not optimised.
CORE = ["Raya","Dúbravka","Gabriel","Gvardiol","Muñoz","Andersen","M.Salah","Mbeumo","Semenyo","Haaland","Strand Larsen"]
QUOTA = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}


def build_start_squad(season, core=CORE, budget=100.0):
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    name2el = {}
    for r in pr.itertuples():
        if int(r.id) in season.meta: name2el.setdefault(r.web_name, int(r.id))
    els, have, club, spent, missing = [], {p: 0 for p in QUOTA}, {}, 0.0, []
    def add(el):
        nonlocal spent
        m = season.meta[el]; els.append(el); have[m["pos"]] += 1
        club[m["short"]] = club.get(m["short"], 0) + 1; spent += price(season, el, 0)
    for nm in core:
        el = name2el.get(nm)
        if el is None: missing.append(nm)
        else: add(el)
    g1 = season.g[season.g.GW == 1].copy(); g1["pr"] = g1.value / 10.0
    for el, pos, sh, pr_ in sorted([(int(r.element), r.position, r.short, r.pr) for r in g1.itertuples()], key=lambda x: x[3]):
        if len(els) >= 15: break
        if el in els or have[pos] >= QUOTA[pos] or club.get(sh, 0) >= 3: continue
        if spent + pr_ + (15 - len(els) - 1) * 4.0 > budget + 1e-9: continue
        add(el)
    return els, round(spent, 1), missing


# ============================================================= CHIP ENGINE (half-aware FPL strategy, GW1-19 / GW20-38)
CHIP_THRESH = dict(wc=12.0, bb_h1=12.0, bb_h2=14.0, fh_h1=12.0, tc_min=7.0)
TR_BASE = 4.0                              # base free-transfer threshold (raised from 2.0 per backtest learning #1)


def half_of(gw): return 1 if gw <= 19 else 2
def half_end(gw): return 19 if gw <= 19 else 38


def optimal_squad(season, budget, cut, gw, horizon=1):
    """Greedy legal 15 (2/5/5/3, £budget, <=3/club) maximising XI EV summed over `horizon` weeks from gw."""
    pool = _pool(season, cut, gw)
    score = {e: sum(ev_multi(season, e, cut, gw + o) for o in range(horizon)) for e in pool}
    els, have, club, spent = [], {p: 0 for p in QUOTA}, {}, 0.0
    def try_add(order, cap_reserve):
        nonlocal spent
        for e in order:
            if len(els) >= 15: break
            m = season.meta[e]
            if e in els or have[m["pos"]] >= QUOTA[m["pos"]] or club.get(m["short"], 0) >= 3: continue
            c = price(season, e, cut)
            if spent + c + (15 - len(els) - 1) * (4.0 if cap_reserve else 0.0) > budget + 1e-9: continue
            els.append(e); have[m["pos"]] += 1; club[m["short"]] = club.get(m["short"], 0) + 1; spent += c
    try_add(sorted(pool, key=lambda e: -score[e]), True)
    if len(els) < 15:                                              # fill bench with cheap PLAYING enablers, not dead fodder
        playing = [e for e in pool if season.minutes(e, cut)["p60"] > 0.55]
        try_add(sorted(playing, key=lambda e: price(season, e, cut)), False)
    if len(els) < 15: try_add(sorted(pool, key=lambda e: price(season, e, cut)), False)
    return els


def wildcard_refit(season, current, itb, cut, gw, horizon=6, max_swaps=15):
    """A wildcard is unlimited free transfers — hill-climb from the CURRENT squad, applying only
    improving swaps. By construction the result can never be worse than what you started with,
    so a wildcard never loses points. Keeps elite performers unless a strictly-better option exists."""
    squad = list(current)
    pool = _pool(season, cut, gw)
    allp = set(pool) | set(current)
    score = {e: sum(ev_multi(season, e, cut, gw + o) for o in range(horizon)) for e in allp}
    for _ in range(max_swaps):
        club, spent = {}, 0.0
        for e in squad: club[season.meta[e]["short"]] = club.get(season.meta[e]["short"], 0) + 1; spent += price(season, e, cut)
        budget = spent + itb
        best = None
        for out in squad:
            po = season.meta[out]; opr = price(season, out, cut)
            for c in pool:
                if c in squad or season.meta[c]["pos"] != po["pos"]: continue
                if spent - opr + price(season, c, cut) > budget + 1e-9: continue
                csh = season.meta[c]["short"]
                if club.get(csh, 0) + (0 if csh == po["short"] else 1) > 3: continue
                g = score[c] - score[out]
                if g > 0.5 and (best is None or g > best[0]): best = (g, out, c)
        if best is None: break
        squad = [best[2] if e == best[1] else e for e in squad]
    return squad


def _xi_ev(season, squad, cut, gw):
    d = select_xi(squad, season, cut, gw)
    return (d["xi_ev"], d) if d else (0.0, None)


def bench_ev(season, squad, cut, gw):
    d = select_xi(squad, season, cut, gw)
    return sum(d["ev"][b] for b in d["bench"]) if d else 0.0


def swing_present(season, cut):
    ts = season.team_strength(cut)
    for sh in season.sched:
        up = [ts.get(o, (1, 1))[1] for w in range(cut + 1, cut + 5) for o, _ in season.fixtures(sh, w)]
        rec = [ts.get(o, (1, 1))[1] for w in range(cut - 3, cut + 1) for o, _ in season.fixtures(sh, w)]
        if up and rec and np.mean(up) > np.mean(rec) + 0.15: return True
    return False


def cluster_ahead(season, gw, ahead=4):
    """DGW/BGW clusters in the next `ahead` weeks (from the known schedule)."""
    out = []
    for w in range(gw, gw + ahead + 1):
        teams = list(season.sched.keys())
        dgw = sum(1 for t in teams if len(season.fixtures(t, w)) >= 2)
        blank = sum(1 for t in teams if not season.fixtures(t, w))
        if dgw >= 4: out.append((w, "DGW", dgw))
        elif blank >= 6: out.append((w, "BGW", blank))
    return out


def wc_gain(season, squad, itb, cut, gw, horizon=6):
    refit = wildcard_refit(season, squad, itb, cut, gw, horizon)
    g = sum(_xi_ev(season, refit, cut, gw + o)[0] - _xi_ev(season, squad, cut, gw + o)[0] for o in range(horizon))
    return max(0.0, g), refit


def wc_fires(season, squad, itb, cut, gw, used):
    """Half-aware wildcard trigger. Returns (fire, gain, reason, opt_squad)."""
    if used: return False, 0.0, "", None
    h = half_of(gw)
    if h == 1:
        if cut < 3: return False, 0.0, "await 3 GW data", None      # need >=3 completed lineups
        g_now, opt = wc_gain(season, squad, itb, cut, gw)
        # no clearly better week in next 2-3: this week's gain is the local max
        better = any(wc_gain(season, squad, itb, cut, gw + d)[0] > g_now + 1.0 for d in (1, 2, 3))
        fire = g_now > CHIP_THRESH["wc"] and swing_present(season, cut) and not better
        return fire, g_now, f"H1 rebuild +{g_now:.0f}/6wk, swing={swing_present(season,cut)}", opt
    # H2: fire ahead of a blank/double cluster if the optimised squad beats current materially
    cl = cluster_ahead(season, gw + 1, 3)
    g_now, opt = wc_gain(season, squad, itb, cut, gw)
    fire = bool(cl) and g_now > CHIP_THRESH["wc"]
    return fire, g_now, (f"H2 pre-cluster {cl[0][1]}GW{cl[0][0]} +{g_now:.0f}" if cl else "no cluster"), opt


def tc_fires(season, squad, cut, gw, used):
    """Reserve for the standout captain week in the half (or the DGW in H2)."""
    if used: return False, 0.0, ""
    cap_now = _xi_ev(season, squad, cut, gw)[1]
    if cap_now is None: return False, 0.0, ""
    val_now = cap_now["ev"][cap_now["captain"]]
    end = half_end(gw)
    future = [_xi_ev(season, squad, cut, w)[1] for w in range(gw + 1, end + 1)]
    best_future = max((d["ev"][d["captain"]] for d in future if d), default=0.0)
    forced = gw == end                                              # use-or-lose in the final week of the half
    fire = val_now >= CHIP_THRESH["tc_min"] and (val_now >= best_future - 1e-9 or forced)
    return fire, val_now, f"cap EV {val_now:.1f} (best remaining {max(val_now,best_future):.1f})"


def bb_fires(season, squad, cut, gw, used, weeks_since_wc):
    """Reserve Bench Boost for the peak bench-EV week of the half; a double gameweek (bench plays
    twice -> highest bench EV) is the canonical target. Modest floor so it isn't spent on a flat week."""
    if used: return False, 0.0, "", False
    bev = bench_ev(season, squad, cut, gw)
    floor = CHIP_THRESH["bb_h1"] if half_of(gw) == 1 else CHIP_THRESH["bb_h2"]
    is_dgw = sum(1 for e in squad if len(season.fixtures(season.meta[e]["short"], gw)) >= 2) >= 4
    end = half_end(gw)
    best_future = max((bench_ev(season, squad, cut, w) for w in range(gw + 1, end + 1)), default=0.0)
    forced = gw == end
    fire = bev >= floor and (bev >= best_future - 0.5 or forced or is_dgw)
    return fire, bev, f"bench EV {bev:.1f}{' DOUBLE' if is_dgw else ''} (peak remaining {max(bev,best_future):.1f})", is_dgw


def fh_fires(season, squad, itb, cut, gw, used):
    """Free Hit = a one-week wildcard that reverts. Hill-climb from the current squad (1-week EV) so,
    worst case, you keep your whole XI and swap only bad-fixture players -> FH never loses points."""
    if used: return False, 0.0, "", None
    blanks = sum(1 for e in squad if not season.fixtures(season.meta[e]["short"], gw))
    fh = wildcard_refit(season, squad, itb, cut, gw, horizon=1)
    gap = _xi_ev(season, fh, cut, gw)[0] - _xi_ev(season, squad, cut, gw)[0]
    if half_of(gw) == 2 and blanks > 4: return True, gap, f"{blanks} blank -> FH team +{gap:.1f}", fh
    fire = gap > CHIP_THRESH["fh_h1"]
    return fire, gap, f"FH team +{gap:.1f} vs squad, {blanks} blank", fh


BANKED_THRESHOLD = {1: 4.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 0.0}   # mirrors weekly.transfer_threshold_live


def transfer_threshold(weeks_to_wc, banked):
    """Mirror of weekly.transfer_threshold_live so the harness validates the LIVE rule.
    The bar falls as free transfers accumulate (a banked transfer is only worth holding while it
    can still be banked); at the 5 cap the incoming transfer is forfeit, so take any positive gain.
    NB the old `if banked >= 3: t *= 1.1` raised the bar as transfers piled up — backwards."""
    if int(banked) >= 5: return 0.0                            # use it or lose it
    t = BANKED_THRESHOLD.get(int(banked), TR_BASE)
    if weeks_to_wc <= 1: t *= 2.0
    elif weeks_to_wc <= 2: t *= 1.5
    elif weeks_to_wc <= 3: t *= 1.2
    return t


def wtc_est(gw, wc_used, cluster, fires_now):
    if wc_used: return 99
    if fires_now: return 0
    if half_of(gw) == 1: return max(0, 6 - gw) if gw <= 8 else 99   # H1 WC expected ~GW6
    return (cluster[0][0] - gw) if cluster else 99                  # H2: distance to next cluster


def score_bb(season, gw, squad, cap, vice):
    total = sum(_pts(season, e, gw) for e in squad)                # all 15 count, no autosub
    c = cap if _played(season, cap, gw) else vice
    if _played(season, c, gw): total += _pts(season, c, gw)
    return total


def score_tc(season, gw, post):
    base, _ = score(season, gw, post["xi"], post["bench"], post["captain"], post["vice"])  # includes 1 double
    c = post["captain"] if _played(season, post["captain"], gw) else post["vice"]
    if _played(season, c, gw): base += _pts(season, c, gw)          # extra copy -> captain scores x3
    return base


# ============================================================= CHIP-AWARE WALK-FORWARD SIMULATION
def simulate_chips(season, start_squad, gw_from, gw_to, verbose=False):
    squad = list(start_squad); itb = round(100.0 - sum(price(season, e, 0) for e in start_squad), 1)
    ft = 1; log = []
    used = {1: {c: None for c in ("WC", "BB", "TC", "FH")}, 2: {c: None for c in ("WC", "BB", "TC", "FH")}}
    since_wc = None
    for gw in range(gw_from, gw_to + 1):
        cut = gw - 1; h = half_of(gw); U = used[h]
        cluster = cluster_ahead(season, gw + 1, 3)
        # --- evaluate every still-available chip this half ---
        cand = {}
        wf, wg, wr, wopt = wc_fires(season, squad, itb, cut, gw, U["WC"] is not None)
        if wf: cand["WC"] = (wg / CHIP_THRESH["wc"], wg, wr, wopt)
        tf, tv, tr = tc_fires(season, squad, cut, gw, U["TC"] is not None)
        if tf: cand["TC"] = (tv / CHIP_THRESH["tc_min"], tv, tr, None)
        bf, bv, br, bdgw = bb_fires(season, squad, cut, gw, U["BB"] is not None, since_wc)
        if bf: cand["BB"] = (bv / (CHIP_THRESH["bb_h1"] if h == 1 else CHIP_THRESH["bb_h2"]), bv, br, bdgw)
        ff, fv, fr, fopt = fh_fires(season, squad, itb, cut, gw, U["FH"] is not None)
        if ff: cand["FH"] = (fv / CHIP_THRESH["fh_h1"], fv, fr, fopt)
        # --- pick ONE chip (hard rule: never two in a week) ---
        # a double-gameweek Bench Boost is THE canonical DGW chip -> it wins the week; else highest urgency.
        if "BB" in cand and cand["BB"][3]:
            chip = "BB"
        else:
            chip = max(cand, key=lambda k: cand[k][0]) if cand else None
        # use-or-lose: in the final week of a half, burn only BB/TC (can only ADD points).
        # NEVER force FH/WC — they REPLACE the team and can score less than the real squad; better to let them expire.
        if gw == half_end(gw) and chip is None:
            avail = [c for c in ("TC", "BB") if U[c] is None]
            if avail: chip = _forced_chip(season, squad, itb, cut, gw, avail)
        # --- apply wildcard (full rebuild) or a normal transfer with wildcard-proximity threshold ---
        made = False; hit = 0; tv_gain = 0.0; transfer = None
        if chip == "WC":
            budget = sum(price(season, e, cut) for e in squad) + itb
            newsq = wopt if wopt else optimal_squad(season, budget, cut, gw, 6)
            squad = newsq; itb = round(budget - sum(price(season, e, cut) for e in squad), 1)
            ft = 1; since_wc = 0; U["WC"] = gw
        else:
            fires_now = "WC" in cand
            thr = transfer_threshold(wtc_est(gw, U["WC"] is not None, cluster, fires_now), ft)
            tvd = best_transfer(squad, itb, season, cut, gw)
            if tvd is not None and ft >= 1 and tvd["gain"] > thr:
                made = True
            elif tvd is not None and should_take_hit(tvd, squad, season, cut, gw):
                made, hit = True, 4
            if made:
                squad = [tvd["inn"] if e == tvd["out"] else e for e in squad]
                itb = round(itb + tvd["price_out"] - tvd["price_in"], 1)
                if hit == 0: ft -= 1
                transfer = (season.meta[tvd["out"]]["name"], season.meta[tvd["inn"]]["name"]); tv_gain = tvd["gain"]
            ft = min(FT_CAP, ft + 1)
        # --- score the week (chip-dependent) ---
        post = select_xi(squad, season, cut, gw)
        if chip == "FH":
            fhsq = fopt if fopt else optimal_squad(season, 100.0, cut, gw, 1)
            fhd = select_xi(fhsq, season, cut, gw); U["FH"] = gw
            pts, _ = score(season, gw, fhd["xi"], fhd["bench"], fhd["captain"], fhd["vice"])  # squad reverts (unchanged)
        elif chip == "BB":
            U["BB"] = gw; pts = score_bb(season, gw, squad, post["captain"], post["vice"])
        elif chip == "TC":
            U["TC"] = gw; pts = score_tc(season, gw, post)
        else:
            pts, _ = score(season, gw, post["xi"], post["bench"], post["captain"], post["vice"])
        since_wc = None if since_wc is None else since_wc + 1
        reason = cand[chip][2] if (chip and chip in cand) else ("use-or-lose deadline" if chip else "")
        eff_cap = post["captain"] if _played(season, post["captain"], gw) else post["vice"]   # vice inherits if captain blanks
        inherited = eff_cap != post["captain"]
        log.append(dict(gw=gw, half=h, pts=pts - hit, hit=hit, chip=chip, reason=reason, made=made, transfer=transfer,
                        tv_gain=tv_gain, captain=season.meta[eff_cap]["name"], captain_pts=_pts(season, eff_cap, gw),
                        captain_inherited=inherited, ft=ft, itb=itb, diag={k: v[2] for k, v in cand.items()}))
        if verbose:
            cs = f'[{chip}]' if chip else '     '
            ts = f'{transfer[0][:9]}->{transfer[1][:9]}' if transfer else ('WILDCARD rebuild' if chip == "WC" else 'bank')
            print(f'GW{gw:>2} {cs} {pts-hit:>5.1f}pts (hit{hit}) | C:{season.meta[post["captain"]]["name"][:10]:<10}={_pts(season,post["captain"],gw):>3.0f} | {ts}'
                  + (f'  <<{reason}' if chip else ''))
    return log, used


def _forced_chip(season, squad, itb, cut, gw, avail):
    """Use-or-lose deadline: pick the highest-value remaining chip to burn this final week of the half."""
    vals = {}
    if "TC" in avail:
        d = select_xi(squad, season, cut, gw); vals["TC"] = d["ev"][d["captain"]] if d else 0
    if "BB" in avail: vals["BB"] = bench_ev(season, squad, cut, gw) / 3.0
    if "FH" in avail:
        fh = optimal_squad(season, 100.0, cut, gw, 1)
        vals["FH"] = _xi_ev(season, fh, cut, gw)[0] - _xi_ev(season, squad, cut, gw)[0]
    if "WC" in avail: vals["WC"] = wc_gain(season, squad, itb, cut, gw)[0] / 6.0
    return max(vals, key=vals.get) if vals else None


if __name__ == "__main__":
    import sys
    gw_from = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    gw_to = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    S = Season()
    squad, cost, missing = build_start_squad(S)
    print(f"Starting squad: {len(squad)}/15 players, cost £{cost}m, ITB £{round(100-cost,1)}m")
    if missing: print(f"  UNRESOLVED: {missing}")
    byp = {}
    for e in squad: byp.setdefault(S.meta[e]["pos"], []).append(S.meta[e]["name"])
    for p in ["GK","DEF","MID","FWD"]: print(f"  {p}: {', '.join(byp.get(p,[]))}")
    print(f"\nWalk-forward simulation GW{gw_from}-{gw_to} (model sees only GW<t):")
    log = simulate(S, squad, gw_from, gw_to, verbose=True)
    tot = sum(r["squad_pts"] for r in log); notr = sum(r["no_transfer_pts"] for r in log); opt = sum(r["optimal_pts"] for r in log)
    print(f"\n  Managed: {tot:.0f} | No-transfer: {notr:.0f} | Optimal ceiling: {opt:.0f}")
