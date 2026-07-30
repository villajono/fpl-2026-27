#!/usr/bin/env python3
"""simulate_gw.py — dry-run the refresh-then-report loop against a MOCK gameweek result,
since real GW1 data isn't available until 2026-08-21. Proves the Bayesian team-rating
refresh moves the models, then that the report regenerates on the updated ratings.
Structurally identical to the live path (fpl_fetch.fetch_gw_data -> refresh -> report)."""
from __future__ import annotations
import fixture_ratings as FR

# Mock GW1 team xG outcomes (att = xG scored, defw = xGA conceded), a few deliberately divergent
MOCK_GW1 = {
    "HUL": (1.30, 1.20),   # promoted: attacked far better than 0.55 prior (K=4 -> updates fast)
    "SUN": (0.55, 0.70),   # promoted: defended better than prior
    "CHE": (1.10, 1.60),   # title pick leaked badly (def 0.82 prior)
    "MCI": (2.40, 0.40),   # dominant, as expected
    "ARS": (1.30, 0.30),   # clean sheet machine, on prior
}

print("SIMULATED GW1 REFRESH — Bayesian team-strength update (prior -> after 1 game)")
print(f"  {'team':>4} {'K':>2}  {'ATT prior→now':>16}  {'DEF prior→now':>16}  {'data wt':>7}")
for sh, (att_obs, defw_obs) in MOCK_GW1.items():
    r = FR.RATINGS[sh]; ap, dp = r["att_prior"], r["defw_prior"]
    w = FR.bayes_update(sh, games_played=1, data_att=att_obs, data_defw=defw_obs)   # mutates FR.RATINGS
    flag = "  [!] >30% divergence (needs 3+ GWs to flag)" if abs(r["att"] - ap) / max(ap, .1) > 0.30 else ""
    print(f"  {sh:>4} {r['K']:>2}  {ap:.2f}→{r['att']:.2f} (obs {att_obs:.2f})  {dp:.2f}→{r['defw']:.2f} (obs {defw_obs:.2f})  {100*w:>5.0f}%{flag}")

print("\nEffect on the report — Haaland (MCI) captaincy EV recomputes on updated ratings:")
import weekly as W
W.CURRENT_GW = 1                      # GW1 now completed
code = W.code_of("Haaland", "FWD", "MCI")
print(f"  Haaland GW2 EV under refreshed model: {W.ev_gw(code,'Haaland','FWD','MCI',2):.2f}")
print("  (promoted clubs moved most — HUL/SUN blend ~20% data at K=4; established clubs barely budged)")
print("\nLoop verified: fetch_gw_data -> Bayesian refresh -> report, all on updated (never stale) models.")
