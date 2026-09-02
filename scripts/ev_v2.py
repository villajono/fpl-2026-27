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
# FPL pays a goal by position. This was hardcoded to 6 for everyone, which is the DEFENDER rate:
# every forward was paid 1.5x the real value of his goals and every midfielder 1.2x. Clean sheets
# were already position-aware via get_cs_pts, so goals were the one scoring term still flat.
GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
# Attacking multiplier at home; away is 2 - this. 1.10/0.90 gives a ratio of 1.222, matching both
# the measured 1.227 (2025-26 ran 1.555 xG at home against 1.268 away) and get_cs_probability's
# own 0.90/1.10. Sweeping it 1.00-1.15 in calibrate.py moved MAE not at all — kept because it is
# right and internally consistent, not because one season could detect it.
HOME_ADV = 1.10
CONCEDE_POS = {"GK", "DEF"}    # only these lose a point per two goals conceded
# CBIT count for +2 DC points. Defenders need 10 (clearances, blocks, interceptions, tackles);
# midfielders AND forwards need 12, recoveries included. FWD was set to 99, i.e. never — so a
# forward who pressed enough to earn the two points could not be credited with them. Keepers
# genuinely have no DC route, so 99 is right for GK.
DC_THRESHOLD = {"DEF": 10, "MID": 12, "GK": 99, "FWD": 12}

_g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
for c in ["minutes", "expected_goals", "expected_assists", "defensive_contribution", "saves",
          "total_points", "bonus", "yellow_cards"]:
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


def _shrink_thin(rr, pos):
    """Pull a thin sample's per-90 rates towards the position average, in proportion to how thin
    it is.

    The pre-season path already falls back to position averages below MIN_MINUTES. The in-season
    path did not: it set rr["thin"] and returned the raw rates regardless, so a per-90 computed
    over a handful of minutes went straight into EV. Josh Dasilva had TWO minutes of history, from
    which the model derived xG90 3.600 and DC90 45.0 and then ranked him above Mbeumo and Haaland
    as a £5.0m transfer target.

    Weight is minutes/MIN_MINUTES, capped at 1 — so anyone at or above 450 minutes is untouched
    and nothing established moves, while two minutes of data is ~99.6% prior. Same shape as the
    Bayesian team ratings: evidence earns its weight rather than being trusted or binned outright.
    """
    m = rr.get("minutes") or 0
    if m >= MIN_MINUTES:
        return rr
    avg = POS_AVG.get(pos) or POS_AVG.get(rr.get("pos")) or POS_AVG["MID"]
    w = max(0.0, min(1.0, m / float(MIN_MINUTES)))
    for k in ("xG90", "xA90", "DC90", "sv90"):
        if k in rr and k in avg:
            rr[k] = w * float(rr[k]) + (1 - w) * float(avg[k])
    rr["shrunk_to_prior"] = round(1 - w, 3)
    return rr


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
                 dc=float(r.defensive_contribution), saves=float(r.saves),
                 bonus=float(getattr(r, "bonus", 0) or 0),
                 yellow=float(getattr(r, "yellow_cards", 0) or 0)) for r in sub.itertuples()]


def _game_fixture_mult(g):
    """The attacking multiplier that applied in a past game — the same expression compute_ev_v2
    uses for a future one, so dividing by it here and multiplying by it there cancels exactly.
    None when the opponent was not recorded (every row before this was added, and all of last
    season), which leaves that game unadjusted."""
    opp = g.get("opp")
    if not opp or opp not in FR.RATINGS:
        return None
    return FR.RATINGS[opp]["defw"] * (1.05 if g.get("home") else 0.95)


def get_per_90_rates(code, pos_hint=None):
    """Personal per-90 rates. In-season: recency-weighted over combined (prior + in-season) history,
    so recent form dominates and stale/old-club data fades. Pre-season: validated career-average.
    Falls back to position average (THIN DATA) below MIN_MINUTES.
    pos_hint: true position for players with no 2025-26 record (else the fallback defaults to MID,
    inflating a defender's attacking rates and voiding their DC threshold)."""
    el = _code2id.get(code); pos = _id2pos.get(el) or pos_hint
    if H.has_inseason() and code in H.inseason_codes():
        rr = H.recency_weighted_rates(_prior_games(el) + H.inseason_rows(code), pos, _game_fixture_mult)
        rr["thin"] = rr["minutes"] < MIN_MINUTES
        return _shrink_thin(rr, pos)
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


def _ovr_p60(name, default=None):
    """P60_OVR values are EITHER a bare float (p60, the original form) OR a dict carrying the
    whole minutes shape {p60, p_cameo, partial}. Everything that only wants the p60 number goes
    through here so both forms work."""
    v = P60_OVR.get(name, default)
    return float(v["p60"]) if isinstance(v, dict) else v


# Human overrides. A value is P(plays 60+ minutes) — NOT P(starts). The two come apart for exactly
# the players worth overriding: a man who starts every week but is hooked on 57 minutes has a high
# P(start) and a LOW p60, and he collects one appearance point rather than two. Give a dict instead
# of a float when that gap matters:
#     "Tzolis": {"p60": 0.18, "p_cameo": 0.33, "partial": 55}
# p_cameo is P(appears but under 60) and partial is his minutes when that happens; weekly.py builds
# both from a p_start / mins_if_start pair, which is how the football is actually known.
P60_OVR = {"Mosquera": 0.92, "van Ewijk": 0.95, "Walle Egeli": 0.45, "Phillips": 0.60,
           # Spurs keeper, 2026-08-13: Kinsky is regarded as the likely starter but it is not
           # settled. Last season's minutes point the other way (Dubravka 3,150 v Kinsky 630), so
           # the first-choice rule below would hand Spurs to Dubravka on stale evidence — he is
           # behind Kinsky now. Durable here rather than a form override, which is GW-scoped and
           # would have to be re-entered every week from the road.
           "Kinsky": 0.80, "Dubravka": 0.0}


# How many games last season is worth as a prior, once this season is under way. Low on purpose:
# role changes over a summer, so a handful of current starts should dominate.
INSEASON_K = 2.0


def _preseason_p60(el, name, r):
    """The pre-season P(start) estimate — also the prior the in-season update starts from.

    Must match what the pre-season branch of get_minutes_probs returns EXACTLY, cameo cap included,
    or GW1 shifts a player for reasons unrelated to whether he started: a heavy-cameo player is
    capped pre-season, and reading the uncapped value made Sarr jump 0.85 -> 0.95 on one start."""
    if r is None:
        return _ovr_p60(name, 0.65)
    app = _g[(_g.element == el) & (_g.minutes >= 60)]
    mm = app.minutes.mean() if len(app) else 0
    cam = _g[(_g.element == el) & (_g.minutes >= 1) & (_g.minutes < 60)]
    return min(_nailed(mm, r["n60"]), 1 - min(len(cam) / 38.0, 0.15))


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
        ov = P60_OVR[name]
        cam = _g[(_g.element == el) & (_g.minutes >= 1) & (_g.minutes < 60)] if el is not None else []
        partial = float(cam.minutes.mean()) if len(cam) else 30.0
        if isinstance(ov, dict):
            # The full shape. Needed because the flat 0.05 below cannot describe a starter who is
            # routinely substituted before the hour — for him p_cameo is the LARGER term, and
            # forcing it to 0.05 throws away most of the points he actually scores.
            p60 = float(ov["p60"])
            return dict(p60=p60,
                        p_cameo=float(ov.get("p_cameo", 0.05 if p60 > 0 else 0.0)),
                        partial=float(ov.get("partial", partial)))
        p60 = float(ov)
        return dict(p60=p60, p_cameo=(0.05 if p60 > 0 else 0.0), partial=partial)
    if code in BACKUP_GK:
        return dict(p60=0.0, p_cameo=0.0, partial=0.0)      # understudy keeper: no minutes at all
    return _apply_availability(code, _minutes_from_data(code, name, el, r))


def _availability(code):
    """FPL's own injury flag as a multiplier on playing at all.

    chance_of_playing_next_round is 0/25/50/75/100 when a player is doubtful and null when he is
    fine. Nothing read it before: `status == "a"` filtered the TRANSFER POOL, so the engine would
    not buy a doubtful player, but one already in the squad kept his full minutes and could be
    picked in the XI ahead of a fit team-mate. That is how a 50%-doubt scored higher than a fit
    forward on 20 points. A human override still wins — it is checked earlier and never reaches
    here — because a manager who has read the team news knows more than the flag does."""
    try:
        row = _nxt[_nxt.code == code]
        if not len(row):
            return 1.0
        c = row.iloc[0].get("chance_of_playing_next_round")
    except Exception:
        return 1.0
    return 1.0 if c is None or c != c else max(0.0, min(1.0, float(c) / 100.0))


def _apply_availability(code, d):
    f = _availability(code)
    if f >= 1.0:
        return d
    return dict(p60=round(d["p60"] * f, 3), p_cameo=round(d["p_cameo"] * f, 3), partial=d["partial"])


def _minutes_from_data(code, name, el, r):
    if H.has_inseason() and code in H.inseason_codes() and H.inseason_rows(code):
        # THIS season's starts settle the question; last season is only a prior. A player who starts
        # the opening two games is very likely to start the third, whatever he did last year — the
        # manager, the squad and his role may all have changed. So: treat last season's start rate as
        # a Beta prior worth only INSEASON_K games and update it with the actual in-season starts.
        #
        #   p = (prior_rate * K + starts) / (K + games)
        #
        # With K=2, a 0.50 player who starts both openers goes to 0.75 and one who starts neither
        # falls to 0.25 — evidence compounds immediately and symmetrically. The old rule ignored
        # in-season data entirely until FOUR gameweeks were logged and then let ~38 prior games
        # outweigh them, so a player dropped in GW1 still looked nailed in GW3.
        rows = H.inseason_rows(code)
        # The prior is the model's OWN pre-season estimate, so GW1 updates it rather than jolting it
        # onto a different scale. The alternatives were both worse. recency_start_prob over
        # appearances answers P(60+ | he played) — a different quantity from the per-gameweek rate
        # the in-season rows measure. Over all gameweeks it has the right units but records how last
        # season ENDED, which is often a situation that has since changed: it puts Gvardiol at 0.13
        # because he was dropped late last season, though he is expected to start this one. Last
        # season's closing state is precisely the thing a summer can invalidate.
        prior = _preseason_p60(el, name, r)
        starts = sum(1 for g in rows if g["minutes"] >= 60)
        p = (prior * INSEASON_K + starts) / (INSEASON_K + len(rows))
        return dict(p60=round(min(max(p, 0.02), 0.98), 2), p_cameo=0.05, partial=30.0)
    if r is None:
        p60 = _ovr_p60(name, 0.65); return dict(p60=p60, p_cameo=0.10, partial=30.0)
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
        # HOME_ADV rather than a flat 1.05: get_cs_probability already used 0.90/1.10 for the same
        # physical effect, so the attacking side of the model disagreed with its own clean-sheet side.
        att_f = orat["defw"] * (HOME_ADV if home else 2 - HOME_ADV)   # scales with opp defensive weakness
        sv_f = orat["att"] * ((2 - HOME_ADV) if home else HOME_ADV)   # saves scale with opp attack strength
        fsrc = "xG model"
    p_dc_full = get_p_dc_bonus(rates, 90); p_dc_part = get_p_dc_bonus(rates, mp["partial"])
    xg, xa, sv = rates["xG90"], rates["xA90"], rates["sv90"]
    gp = GOAL_PTS.get(pos, 5)          # a goal is NOT worth the same to everyone — see GOAL_PTS
    bon = float(rates.get("bonus_app", 0.0) or 0.0)     # 7% of all points; see history.recency_weighted_rates
    # FPL takes a point off a keeper or defender for every TWO goals conceded. The model priced
    # the clean-sheet upside and none of the downside, which flattered defenders at leaky clubs and
    # is part of why the engine kept wanting to captain one. No new parameter: cs_prob is exp(-λ)
    # under the Poisson the CS model is calibrated on, so λ — expected goals conceded — is just
    # -ln(cs_prob), and works identically whether cs_prob came from odds or the xG model.
    conceded = -math.log(max(cs_prob, 1e-6)) if pos in CONCEDE_POS else 0.0
    concede_pts = -0.5 * conceded
    # A yellow is -1, and falls hardest on the defensive midfielders the DC term rewards.
    yel = -float(rates.get("yellow_app", 0.0) or 0.0)
    ev_full = (cs_prob * cs_pts + 2 + xg * gp * att_f + xa * 3 * att_f + p_dc_full * 2
               + sv * save_pts * sv_f + bon + concede_pts + yel)
    ev_part = (1 + (mp["partial"] / 90.0) * (xg * gp * att_f + xa * 3 * att_f + sv * save_pts * sv_f
                                             + concede_pts) + p_dc_part * 2 + 0.4 * bon + 0.5 * yel)
    ev = mp["p60"] * ev_full + mp["p_cameo"] * ev_part
    if breakdown:
        f = mp["p60"]
        return dict(ev=ev, cs=cs_prob * cs_pts * f, app=2 * f, xg=xg * gp * att_f * f, xa=xa * 3 * att_f * f,
                    dc=p_dc_full * 2 * f, sv=sv * save_pts * sv_f * f, p60=f, cs_prob=cs_prob,
                    p_dc=p_dc_full, att_f=att_f, thin=rates["thin"], fixture_source=fsrc)
    return ev
