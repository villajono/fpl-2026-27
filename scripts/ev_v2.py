#!/usr/bin/env python3
"""
ev_v2.py — expected-points model V2, built variable-by-variable from first principles.
Each point source modelled separately and summed; nothing hidden in a regression intercept.
V1's single form_ev conflated team events (clean sheets) with personal contributions and
used per-game totals; V2 uses per-90 personal rates + a team-level clean-sheet probability.

Build order (validate each before the next): 1 per-90 rates, 2 team CS prob, 3 EV decomposition,
4 DC-bonus distributional model, 5 DEF validation, 6 roll out, 7 squad comparison.
"""
from __future__ import annotations
from pathlib import Path
import math, numpy as np, pandas as pd
import squad_engine as SE, fixture_ratings as FR
import history as H
import odds as ODDS                         # bookmaker fixture inputs (near GWs); off by default

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
MIN_MINUTES = 450          # below this -> position-average rates, THIN DATA
DC_THRESHOLD = {"DEF": 10, "MID": 12, "GK": 99, "FWD": 99}   # CBIT count for +2 DC points

_g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
for c in ["minutes", "expected_goals", "expected_assists", "defensive_contribution", "saves", "total_points"]:
    _g[c] = pd.to_numeric(_g[c], errors="coerce").fillna(0)
_pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
_nxt = pd.read_csv(RAW / "players_2026-27.csv", low_memory=False)
_code2id = dict(zip(_pr.code, _pr.id))
_id2pos = dict(zip(_pr.id, _pr.element_type.map(POSN)))


# ---------------------------------------------------------------- STEP 1: per-90 rates
def _raw_rates(el):
    sub = _g[(_g.element == el) & (_g.minutes > 0)]
    if not len(sub): return None
    mins = sub.minutes.sum(); n90 = mins / 90.0; games = len(sub)
    return dict(minutes=int(mins), games=games, n60=int((sub.minutes >= 60).sum()),
                xG90=sub.expected_goals.sum() / n90, xA90=sub.expected_assists.sum() / n90,
                DC90=sub.defensive_contribution.sum() / n90, sv90=sub.saves.sum() / n90,
                dc_history=sub.defensive_contribution.tolist(),
                xG_pg=sub.expected_goals.sum() / games, xA_pg=sub.expected_assists.sum() / games,
                DC_pg=sub.defensive_contribution.sum() / games)


def _pos_avg_rates():
    acc = {p: {"xG90": [], "xA90": [], "DC90": [], "sv90": []} for p in POSN.values()}
    for el, pos in _id2pos.items():
        r = _raw_rates(el)
        if r and r["minutes"] >= MIN_MINUTES:
            for k in ("xG90", "xA90", "DC90", "sv90"): acc[pos][k].append(r[k])
    return {p: {k: float(np.mean(v)) if v else 0.0 for k, v in d.items()} for p, d in acc.items()}


POS_AVG = _pos_avg_rates()


def _prior_games(el):
    """2025-26 per-game appearance rows (oldest→newest) for the recency blend."""
    if el is None: return []
    sub = _g[(_g.element == el) & (_g.minutes > 0)].sort_values("GW")
    return [dict(minutes=float(r.minutes), xG=float(r.expected_goals), xA=float(r.expected_assists),
                 dc=float(r.defensive_contribution), saves=float(r.saves)) for r in sub.itertuples()]


def get_per_90_rates(code, pos_hint=None):
    """Personal per-90 rates. In-season: recency-weighted over combined (prior + in-season) history,
    so recent form dominates and stale/old-club data fades. Pre-season: validated career-average.
    Falls back to position average (THIN DATA) below MIN_MINUTES.
    pos_hint: true position for players with no 2025-26 record (else the fallback defaults to MID,
    inflating a defender's attacking rates and voiding their DC threshold)."""
    el = _code2id.get(code); pos = _id2pos.get(el) or pos_hint
    if H.has_inseason() and code in H.inseason_codes():
        rr = H.recency_weighted_rates(_prior_games(el) + H.inseason_rows(code), pos)
        rr["thin"] = rr["minutes"] < MIN_MINUTES
        return rr
    r = _raw_rates(el) if el is not None else None
    if r is None or r["minutes"] < MIN_MINUTES:
        a = dict(POS_AVG.get(pos, POS_AVG["MID"]))
        a.update(pos=pos, minutes=(r["minutes"] if r else 0), thin=True,
                 dc_history=(r["dc_history"] if r else []), n60=(r["n60"] if r else 0), games=(r["games"] if r else 0))
        return a
    r.update(pos=pos, thin=False)
    return r


# ---------------------------------------------------------------- STEP 2: team CS probability
def _calibrate_cs():
    g, att, defw, _n2s, _pr2 = FR._prep()
    g["cs"] = pd.to_numeric(g["clean_sheets"], errors="coerce").fillna(0)
    tm = g[g.minutes >= 60].groupby(["GW", "team", "opp_name", "was_home"]).agg(cs=("cs", "max")).reset_index()
    tm["x"] = tm.opp_name.map(att.to_dict()) * tm.team.map(defw.to_dict()) * np.where(tm.was_home, 0.90, 1.10)
    tm = tm.dropna(subset=["x"]); target = tm.cs.mean(); x = tm.x.values
    lo, hi = 0.1, 5.0
    for _ in range(60):                       # bisection: mean(exp(-C x)) is decreasing in C
        C = (lo + hi) / 2
        if np.mean(np.exp(-C * x)) > target: lo = C
        else: hi = C
    return C


_CS_C = _calibrate_cs()
_CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}


def get_cs_probability(team, opp, home):
    r = FR.RATINGS
    if team not in r or opp not in r: return 0.30
    x = r[opp]["att"] * r[team]["defw"] * (0.90 if home else 1.10)
    return math.exp(-_CS_C * x)


def get_cs_pts(pos):
    return _CS_PTS[pos]


# ---------------------------------------------------------------- STEP 4: DC-bonus distributional model
def _pois_surv(thr, mu):
    if mu <= 0: return 0.0
    cdf = sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(thr))
    return max(0.0, 1.0 - cdf)


def _nb_surv(thr, mu, var):
    if mu <= 0: return 0.0
    if var <= mu * 1.01: return _pois_surv(thr, mu)            # not overdispersed -> Poisson
    r = mu * mu / (var - mu); p = r / (r + mu)
    cdf = 0.0
    for k in range(thr):
        cdf += math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)) * (p ** r) * ((1 - p) ** k)
    return max(0.0, 1.0 - cdf)


def get_p_dc_bonus(rates, expected_minutes):
    """P(DC score >= threshold) from the player's DC distribution, conditioned on minutes.
    Distributional (Poisson/NegBin), NOT historical hit rate."""
    pos = rates["pos"]; thr = DC_THRESHOLD.get(pos, 99)
    if thr >= 99 or rates["DC90"] <= 0: return 0.0
    mu = rates["DC90"] * expected_minutes / 90.0                # expected DC at these minutes
    hist = [h for h, in zip(rates.get("dc_history", []))] if False else rates.get("dc_history", [])
    full = [d for d in hist if d is not None]                  # per-match DC counts (mostly 60+ games)
    if len(full) >= 5:
        m, v = float(np.mean(full)), float(np.var(full))
        if v > m * 1.25 and m > 0:                             # overdispersed -> NegBin, scale variance to minutes
            phi = v / m; return _nb_surv(thr, mu, phi * mu)
    return _pois_surv(thr, mu)


# ---------------------------------------------------------------- STEP 3: EV decomposition
def _nailed(mm, n60):
    p = 0.93 if mm >= 88 else 0.90 if mm >= 82 else 0.84 if mm >= 78 else 0.70 if mm >= 73 else 0.55
    return round(p * (0.85 if n60 < 12 else 1.0), 2)


P60_OVR = {"Mosquera": 0.92, "van Ewijk": 0.95, "Walle Egeli": 0.45, "Phillips": 0.60,
           # Spurs keeper, 2026-08-13: Kinsky is regarded as the likely starter but it is not
           # settled. Last season's minutes point the other way (Dubravka 3,150 v Kinsky 630), so
           # the first-choice rule below would hand Spurs to Dubravka on stale evidence — he is
           # behind Kinsky now. Durable here rather than a form override, which is GW-scoped and
           # would have to be re-entered every week from the road.
           "Kinsky": 0.80, "Dubravka": 0.0}


def _backup_keeper_codes():
    """Codes of every goalkeeper who is NOT his club's first choice.

    Goalkeeper minutes are binary: one keeper per club plays, and he plays all 90. But a backup has
    no rate history, so he falls through to the 0.65 no-data default and gets rated like a starter.
    Liverpool carry six rated keepers; five of them will play no minutes at all. That is harmless in
    a normal week (you would never field them) but not under a Bench Boost, where all fifteen score
    and an optimiser will cheerfully buy two £4.0 keepers at the same club.

    A keeper is rated ONLY if he is unambiguously his club's number one: strictly the dearest AND
    strictly the most-owned of that club's keepers. Everyone else scores zero. The burden of proof
    sits on being startable, not on being a backup, because an uncertain keeper is worth nothing —
    he either plays 90 minutes or none, and buying the wrong one of a pair costs a whole squad slot
    (and, under a Bench Boost, a whole scoring slot).

    Evidence, in order:
      1. LAST SEASON'S MINUTES, where any keeper at the club has some. This is the direct record of
         who actually plays and it settles cases price cannot: Sánchez (3,040 min) and Jörgensen
         (378) are both £5.0, and Verbruggen (3,420) and Rushworth (0) are both £4.5, so a
         price test would have zeroed two of the most nailed keepers in the game.
      2. PRICE AND OWNERSHIP TOGETHER, for a club where nobody has minutes (promoted sides). Both
         are required because either alone misleads — Ipswich price-favours Walton at 0.8% owned
         over Palmer at 6.8%, while ownership goes stale when a keeper has just lost the job.
      3. Otherwise NOBODY at that club is rated. Coventry and Ipswich are genuinely undecided, and
         a coin-flip keeper is worth nothing.

    A club with a single listed keeper qualifies trivially. A human override still wins, because
    P60_OVR is checked first in get_minutes_probs — so a contested job can be resolved from the
    phone form the moment team news lands.
    """
    gks = _nxt[_nxt.element_type == 1]
    non_starters = set()
    for _, grp in gks.groupby("team_name"):
        g = grp.copy()
        # NB no leading underscore: itertuples() renames such columns positionally (_1, _2, ...)
        g["selpct"] = pd.to_numeric(g.selected_by_percent, errors="coerce").fillna(0.0)
        g["mins"] = pd.to_numeric(g.minutes, errors="coerce").fillna(0.0)
        rows = [(int(r.code), float(r.now_cost), float(r.selpct), float(r.mins))
                for r in g.itertuples()]
        by_minutes = any(m > 0 for _, _, _, m in rows)
        for code, cost, sel, mins in rows:
            others = [o for o in rows if o[0] != code]
            if by_minutes:
                first_choice = mins > 0 and all(mins > m2 for _, _, _, m2 in others)
            else:
                first_choice = all(cost > c2 and sel > s2 for _, c2, s2, _ in others)
            if not first_choice:
                non_starters.add(code)
    return non_starters


BACKUP_GK = _backup_keeper_codes()


def get_minutes_probs(code, name=None):
    el = _code2id.get(code); r = _raw_rates(el) if el is not None else None
    if name in P60_OVR:
        # An explicit human override ALWAYS wins — it encodes team news the data cannot see (a sale,
        # a confirmed benching, a returnee). This must be checked BEFORE the in-season branch below,
        # which returns a purely data-derived start rate and would silently ignore the override once
        # four gameweeks are logged. p_cameo goes to zero for a ruled-out player, so "won't start"
        # actually drives EV to ~0 rather than leaving him a cameo's worth of points.
        p60 = float(P60_OVR[name])
        cam = _g[(_g.element == el) & (_g.minutes >= 1) & (_g.minutes < 60)] if el is not None else []
        partial = float(cam.minutes.mean()) if len(cam) else 30.0
        return dict(p60=p60, p_cameo=(0.05 if p60 > 0 else 0.0), partial=partial)
    if code in BACKUP_GK:
        return dict(p60=0.0, p_cameo=0.0, partial=0.0)      # understudy keeper: no minutes at all
    if H.has_inseason() and code in H.inseason_codes() and len(H.inseason_rows(code)) >= 4:
        p = H.recency_start_prob(_prior_games(el) + H.inseason_rows(code))   # actual recent start rate
        return dict(p60=round(min(max(p, 0.05), 0.98), 2), p_cameo=0.05, partial=30.0)
    if r is None:
        p60 = P60_OVR.get(name, 0.65); return dict(p60=p60, p_cameo=0.10, partial=30.0)
    app = _g[(_g.element == el) & (_g.minutes >= 60)]
    mm = app.minutes.mean() if len(app) else 0
    cam = _g[(_g.element == el) & (_g.minutes >= 1) & (_g.minutes < 60)]
    partial = cam.minutes.mean() if len(cam) else 30.0
    # (the P60_OVR override is handled at the top of this function, before the in-season branch)
    p_cameo = min(len(cam) / 38.0, 0.15)
    return dict(p60=min(_nailed(mm, r["n60"]), 1 - p_cameo), p_cameo=p_cameo, partial=float(partial))


def compute_ev_v2(code, name, pos, team, opp, home, breakdown=False):
    rates = get_per_90_rates(code, pos); mp = get_minutes_probs(code, name)
    cs_pts = get_cs_pts(pos)
    save_pts = 1.0 / 3.0 if pos == "GK" else 0.0
    orat = FR.RATINGS.get(opp, {"att": 1.0, "defw": 1.0})
    # --- fixture inputs: bookmaker odds for near, published fixtures; else the xG model ---
    oi = ODDS.fixture_inputs(team, opp, home)                # None unless odds enabled AND fixture published
    if oi:
        cs_prob = oi["cs_prob"]; att_f = oi["att_mult"]; sv_f = oi["sv_mult"]; fsrc = oi["source"]
    else:
        cs_prob = get_cs_probability(team, opp, home)
        att_f = orat["defw"] * (1.05 if home else 0.95)     # attacking returns scale with opp defensive weakness
        sv_f = orat["att"] * (0.95 if home else 1.05)       # saves scale with opp attack strength
        fsrc = "xG model"
    p_dc_full = get_p_dc_bonus(rates, 90); p_dc_part = get_p_dc_bonus(rates, mp["partial"])
    xg, xa, sv = rates["xG90"], rates["xA90"], rates["sv90"]
    ev_full = cs_prob * cs_pts + 2 + xg * 6 * att_f + xa * 3 * att_f + p_dc_full * 2 + sv * save_pts * sv_f
    ev_part = 1 + (mp["partial"] / 90.0) * (xg * 6 * att_f + xa * 3 * att_f + sv * save_pts * sv_f) + p_dc_part * 2
    ev = mp["p60"] * ev_full + mp["p_cameo"] * ev_part
    if breakdown:
        f = mp["p60"]
        return dict(ev=ev, cs=cs_prob * cs_pts * f, app=2 * f, xg=xg * 6 * att_f * f, xa=xa * 3 * att_f * f,
                    dc=p_dc_full * 2 * f, sv=sv * save_pts * sv_f * f, p60=f, cs_prob=cs_prob,
                    p_dc=p_dc_full, att_f=att_f, thin=rates["thin"], fixture_source=fsrc)
    return ev
