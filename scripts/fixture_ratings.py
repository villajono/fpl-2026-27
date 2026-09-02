#!/usr/bin/env python3
"""
fixture_ratings.py — xG attack/defence team ratings + PLAYER-LEVEL fixture curves.

No attacking/defensive classification. Each player gets their OWN fixture-sensitivity
curve, fit on their history: points ~ oppATT + oppDEFweak (2 slopes, normalised to
1.0 at a league-average opponent so only the SHAPE matters, not scoring level).
That curve is shrunk toward a pooled position prior (GK/DEF/MID/FWD) by sample size:
  shrunk = (N*own + K*prior)/(N + K),  K=15   (N ~= qualifying starts)
so ~5 starts is mostly prior, ~15 is half-and-half, ~30+ is mostly personal.
The individual fit is recency-weighted with a GENTLE decay (half-life ~20 starts):
role moves slowly, so we don't want form's fast decay here.

Players with no qualifying history (promoted-club players, new signings) fall back
to the pooled position prior and are flagged PRIOR-ONLY. For those we also expose the
neutral-DEF vs attacking-DEF range so the human can see the uncertainty. Plus the
Bayesian team-rating updater for in-season xG.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
IMPLIED = {"Arsenal":-6.5,"Man City":-2.5,"Man Utd":-1.5,"Aston Villa":-7.0,"Liverpool":11.0,
 "Bournemouth":-8.0,"Sunderland":-11.5,"Brighton":0.0,"Brentford":-4.0,"Chelsea":16.0,"Fulham":-7.5,
 "Newcastle":3.5,"Everton":0.5,"Leeds":-1.0,"Crystal Palace":1.0,"Nott'm Forest":4.0,"Spurs":20.0}
PROMOTED_PTS = {"Ipswich":33.0,"Coventry":33.0,"Hull":24.0}
K_SHRINK = 15.0     # prior's equivalent sample size (15 starts -> 50/50)
HALF_LIFE = 20.0    # recency half-life in starts (gentle: role changes slowly)
MIN_OWN = 4         # need this many starts before any personal signal is used


def _prep():
    g = pd.read_csv(RAW / "merged_gw_2025-26.csv", low_memory=False)
    lt = pd.read_csv(RAW / "league_table_2025-26.csv")
    pr = pd.read_csv(RAW / "players_raw_2025-26.csv", low_memory=False)
    sh2name = dict(zip(lt.short, lt.team_fpl)); name2sh = dict(zip(lt.team_fpl, lt.short))
    id2sh = dict(zip(pd.read_csv(RAW/'teams_2025-26.csv').id, pd.read_csv(RAW/'teams_2025-26.csv').short_name))
    for c in ["expected_goals","minutes","total_points","goals_scored","assists"]:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    g["opp_name"] = g["opponent_team"].map(lambda i: sh2name.get(id2sh.get(i)))
    g["pos"] = g["element"].map(dict(zip(pr.id, pr.element_type.map({1:"GK",2:"DEF",3:"MID",4:"FWD"}))))
    g["ga"] = g.goals_scored + g.assists
    m = g.groupby(["GW","team","opp_name","was_home"], as_index=False)["expected_goals"].sum().rename(columns={"expected_goals":"xg"})
    rev = m.rename(columns={"team":"opp_name","opp_name":"team","xg":"xga"})[["GW","team","opp_name","xga"]]
    m = m.merge(rev, on=["GW","team","opp_name"], how="left")
    ag = m.groupby("team").agg(games=("GW","size"), xgf=("xg","sum"), xga=("xga","sum"))
    att = (ag.xgf/ag.games)/((ag.xgf/ag.games).mean()); defw = (ag.xga/ag.games)/((ag.xga/ag.games).mean())
    return g, att, defw, name2sh, pr


def _ols_raw(att, defw, y, w):
    """Weighted OLS -> raw coefficients (c0, c1, c2)."""
    X = np.column_stack([np.ones(len(y)), att, defw]); sw = np.sqrt(w)
    c, *_ = np.linalg.lstsq(X * sw[:, None], np.asarray(y) * sw, rcond=None)
    return c


def _sens(c):
    base = c[0] + c[1] + c[2]
    if not np.isfinite(base) or base <= 0.5: return None
    return (float(c[1] / base), float(c[2] / base))


def _ridge(att, defw, y, w, prior_slopes, k):
    """Ridge toward prior SLOPES (intercept free): regularises the collinear att/defw
    direction so an ill-conditioned per-player fit falls back to the prior there."""
    X = np.column_stack([np.ones(len(y)), att, defw]); W = np.asarray(w)
    XtWX = X.T @ (X * W[:, None]); XtWy = X.T @ (W * np.asarray(y))
    D = np.diag([0.0, 1.0, 1.0]); bp = np.array([0.0, prior_slopes[0], prior_slopes[1]])
    return np.linalg.solve(XtWX + k * D, XtWy + k * (D @ bp))


def _role_ga(seq):
    """Stable goal-involvement rate: recency-weighted (half-life ~20 starts) mean of
    (goals+assists)/start over a player's whole history. Coordinate for the prior blend."""
    n = len(seq); age = (n - 1) - np.arange(n); w = 0.5 ** (age / HALF_LIFE)
    return float(np.average([ga for _, ga in seq], weights=w))


def _lerp(a, b, w):
    return ((1-w)*a[0] + w*b[0], (1-w)*a[1] + w*b[1])


def _build():
    g, att_raw, defw_raw, name2sh, pr = _prep()
    R = {}
    for name in IMPLIED:
        if name not in att_raw.index: continue
        # K is the prior's equivalent sample size: w = games/(games+K). At the old 5 and 9, two
        # gameweeks moved a rating by 29% — Coventry's defensive weakness went 1.40 -> 1.20 on two
        # matches, and that scales every attacking return in every fixture six weeks out.
        # Swept in calibrate.py: MAE and rank correlation are flat from K=2 to K=40, but top-1 —
        # the points scored by the model's best pick each week, i.e. the captaincy — sits at
        # 5.61-5.70 for K<=8 and 5.91 from K=12 up. Slower ratings pick a better captain and cost
        # nothing. Keeping the two-tier structure (a bigger implied adjustment means a less
        # confident prior, so it should still move faster) and scaling both into that plateau.
        adj = IMPLIED[name]; scale = 1 + adj/80.0; K = 12 if abs(adj) >= 8 else 22
        a, d = round(att_raw[name]*scale, 2), round(defw_raw[name]/scale, 2)
        R[name2sh[name]] = {"name":name,"att":a,"defw":d,"K":K,"adj":adj,"att_prior":a,"defw_prior":d}
    for name, pts in PROMOTED_PTS.items():
        sh = {"Ipswich":"IPS","Coventry":"COV","Hull":"HUL"}[name]
        a = round(0.55+(pts-24)/54*0.9, 2); d = round(1.55-(pts-24)/54*0.9, 2)
        # K=8, not 4. Promoted sides keep the FASTEST prior in the model — their Championship-points
        # prior really is the weakest thing here, so the data should overtake it soonest — but 4
        # gave two Premier League games a third of the weight, and two games is a poor basis however
        # weak the prior. Coventry's defensive weakness moved 1.40 -> 1.20 on exactly that.
        R[sh] = {"name":name,"att":a,"defw":d,"K":8,"adj":None,"att_prior":a,"defw_prior":d,"promoted":True}

    g["opp_defw"] = g["opp_name"].map(defw_raw.to_dict()); g["opp_att"] = g["opp_name"].map(att_raw.to_dict())
    app = g[g.minutes >= 60].dropna(subset=["opp_att","opp_defw"]).copy()
    ga_st = app.groupby("element").ga.mean()
    el_pos = app.groupby("element").pos.first().to_dict()
    seqs = {el: list(zip(sub.sort_values("GW").GW, sub.sort_values("GW").ga)) for el, sub in app.groupby("element")}
    role_ga = {el: _role_ga(s) for el, s in seqs.items()}

    def fit(mask):   # -> normalised sensitivities (s_att, s_defw)
        s = app[mask]; return _sens(_ols_raw(s.opp_att.values, s.opp_defw.values, s.total_points.values, np.ones(len(s)))) or (0.0, 0.0)

    # single-profile priors
    POS = {P: fit(app.pos == P) for P in ["GK","DEF","MID","FWD"]}
    POS_YBAR = {P: float(app[app.pos == P].total_points.mean()) for P in ["GK","DEF","MID","FWD"]}
    # sub-profile priors (endpoints of the continuous blend) — classified by season GA only to DEFINE the endpoints
    SUB = {"CB": fit((app.pos=="DEF") & (app.element.map(ga_st)< 0.10)),
           "FB": fit((app.pos=="DEF") & (app.element.map(ga_st)>=0.10)),
           "DM": fit((app.pos=="MID") & (app.element.map(ga_st)< 0.15)),
           "CM": fit((app.pos=="MID") & (app.element.map(ga_st)>=0.15))}
    # blend anchors: role-GA at the 40th pct (defensive endpoint) and 90th pct (attacking endpoint)
    # of the position, so genuine CBs/def-mids clip firmly to the defensive sub-prior.
    rser = pd.Series(role_ga)
    def anc(P): m = rser[[e for e in role_ga if el_pos.get(e) == P]]; return (float(np.percentile(m, 40)), float(np.percentile(m, 90)))
    ANCH = {"DEF": anc("DEF"), "MID": anc("MID")}

    def prior_sens(P, role):
        """Continuous prior: interpolate the two sub-profiles by role-GA (no hard threshold)."""
        if P == "DEF": lo, hi = ANCH["DEF"]; w = _wclip(role, lo, hi); return _lerp(SUB["CB"], SUB["FB"], w), w
        if P == "MID": lo, hi = ANCH["MID"]; w = _wclip(role, lo, hi); return _lerp(SUB["DM"], SUB["CM"], w), w
        return POS.get(P, (0.0, 0.0)), None

    # per-player curves: continuous prior by role-GA, then individual ridge toward it
    PS = {}
    for el, sub in app.groupby("element"):
        sub = sub.sort_values("GW"); n = len(sub); P = el_pos.get(el)
        pri, wrole = prior_sens(P, role_ga.get(el, 0.0))
        if n < MIN_OWN or P not in POS: PS[el] = (pri[0], pri[1], n, 0.0, wrole); continue
        age = (n - 1) - np.arange(n); w = 0.5 ** (age / HALF_LIFE)
        ybar = float(np.average(sub.total_points.values, weights=w))
        pr_slopes = (pri[0]*ybar, pri[1]*ybar)                     # prior sensitivities -> raw slopes at player's level
        beta = _ridge(sub.opp_att.values, sub.opp_defw.values, sub.total_points.values, w, pr_slopes, K_SHRINK)
        s = _sens(beta)
        if s is None: PS[el] = (pri[0], pri[1], n, 0.0, wrole); continue
        PS[el] = (s[0], s[1], n, round(n / (n + K_SHRINK), 2), wrole)

    return R, POS, SUB, PS, dict(zip(pr.code, pr.id))


def _wclip(x, lo, hi):
    return 0.5 if hi <= lo else float(min(max((x - lo) / (hi - lo), 0.0), 1.0))


RATINGS, POS_PRIOR_SENS, SUB_SENS, PLAYER_SENS, _CODE2EL = _build()


def _mult_raw(sa, sd, opp_short, is_home=True):
    r = RATINGS.get(opp_short)
    if r is None: return 1.0
    att = r["att"] * (0.95 if is_home else 1.05); defw = r["defw"] * (1.05 if is_home else 0.95)
    return round(max(1 + sa*(att-1) + sd*(defw-1), 0.3), 3)


def sens_for(code, position):
    """-> (s_att, s_defw, N_starts, w_own, prior_only, w_role)."""
    el = _CODE2EL.get(code) if code is not None else None
    ps = PLAYER_SENS.get(el)
    if ps is None:
        sa, sd = POS_PRIOR_SENS.get(position, (0.0, 0.0)); return (sa, sd, 0, 0.0, True, None)
    return (ps[0], ps[1], ps[2], ps[3], False, ps[4])


def get_multiplier(opp_short, position, code=None, is_home=True):
    sa, sd, *_ = sens_for(code, position)
    return _mult_raw(sa, sd, opp_short, is_home)


def prior_only_range(opp_short, is_home=True):
    """For a PRIOR-ONLY defender: (pure-CB mult, attacking-FB mult) — the visible endpoints."""
    return (_mult_raw(*SUB_SENS["CB"], opp_short, is_home),
            _mult_raw(*SUB_SENS["FB"], opp_short, is_home))


def bayes_update(club_short, games_played, data_att, data_defw):
    r = RATINGS[club_short]; w = games_played/(games_played+r["K"])
    r["att"] = round((1-w)*r["att_prior"]+w*data_att, 2); r["defw"] = round((1-w)*r["defw_prior"]+w*data_defw, 2)
    return w


def ratings_display(games_played=0):
    return [(sh, r["name"], r["att_prior"], r["att"], r["defw_prior"], r["defw"], r["K"],
             round(1-games_played/(games_played+r["K"]),2), round(games_played/(games_played+r["K"]),2))
            for sh, r in sorted(RATINGS.items(), key=lambda kv: -kv[1]["att"])]
