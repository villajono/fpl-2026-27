# FPL 2026-27 — Weekly Management System

A from-first-principles expected-points engine and weekly decision tool for Fantasy Premier League.

## The weekly loop (`scripts/weekly.py`)
Runs every week before the deadline. Two phases, in order — **refresh first, report second, never on stale data**:

1. **Model refresh** — ingests the just-played gameweek (`fpl_fetch.py`, live FPL API) and updates every
   component: Bayesian team-strength ratings (tiered confidence: promoted K=4, large-adjustment K=5,
   established K=9), recency-weighted per-90 rates, DC distributional model, P(starts), yellow cards.
2. **Decision report** for each team: chip eval, bench-cover-adjusted transfers on forward-looking
   signals, captain, XI, 6-week trajectory, watchlist, and a 2-minute **human-confirmation prompt**
   (flags P(starts) moves >20%; free-text overrides in `data/state/human_input.json`).

## The V2 EV model (`ev_v2.py`)
Builds EV variable-by-variable — nothing hidden in a regression intercept:
`EV = P(start) × [ appearance + P(CS)×CS_pts + xG×6 + xA×3 + P(DC bonus)×2 + saves ]`,
with clean sheets as a **team event** (`P(CS)` from team defence vs opponent attack, Poisson-calibrated)
and personal contributions as recency-weighted **per-90 rates**. Fixes V1's conflation of team clean
sheets with personal output — see the V1-vs-V2 reversal in `ev_v2_compare.py`.

## Key scripts
| File | Purpose |
|---|---|
| `ev_v2.py` | V2 expected-points model (per-90 rates, team CS, DC model) |
| `fixture_ratings.py` | continuous xG fixture engine + Bayesian team ratings |
| `fpl_fetch.py` | live FPL-API ingestion (points, minutes, xG/xA/DC, availability) |
| `weekly.py` | the weekly refresh-then-report tool |
| `optimize_v2.py` | squad selection on the V2 model |
| `final_squad.py` | the locked squad + projection |
| `simulate_gw.py` | dry-run the refresh loop against a mock gameweek |

## Running
```
cd scripts
python weekly.py         # weekly report for both teams
python simulate_gw.py    # dry-run the refresh loop
python fpl_fetch.py      # check live API / season state
```

Season starts GW1 on 2026-08-21. Data in `data/raw` is a development dataset; live operation pulls from the FPL API.
