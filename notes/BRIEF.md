# FPL — initial squad budget allocation

*Weekend project. Objective: decide the initial **£ allocation across positions/
slots** for the squad draft — how much to spend where. NOT about predicting or
recommending specific players.*

## The decision
Total budget £100.0m, squad of 15 = 2 GK, 5 DEF, 5 MID, 3 FWD. Output = a target
£ spend per slot (and per position) with a data-backed rationale.

## Governing principles (from the brief)
1. **Discretionary £ is what matters.** Raw price is meaningless — every legal
   squad pays a forced *floor* (cheapest player × slots). Value = points per £
   spent ABOVE the floor. The real lever is the discretionary budget
   (≈ £100m − Σ floors) and where it buys the most extra points.
2. **Slot USAGE varies, and the crash count is an OUTPUT not an input.** 11 play
   each week (starting XI ± a bench sub for injury/suspension). But bench slots
   aren't worthless: ROTATION matters — you start Def #4 the week Def #3 is away to
   Arsenal. So a playable bench option earns points on the weeks it rotates in. The
   model must weigh a bench slot's rotation value (PPG × games it actually plays)
   against the alternative use of that £ (upgrading a starter, where returns
   diminish at the top). How many slots to crash (~£4.0 non-players, ~0 games) vs
   keep playable falls out of where those marginal values cross. User's hunch:
   crash 1–2, keep 2 playable — but that must EMERGE, not be assumed.
3. **Rule tweak → attack.** BPS now favours FWD, GK, attacking MID, attacking DEF;
   penalises centre-backs & defensive mids. So discount last year's CB / def-mid
   points when reading them forward.
4. **Transfers soften pick-risk — value the ARCHITECTURE, not the static pick.**
   ~1 free transfer/week (+ -4 hits) means a dud £4.5 DEF gets cut for a £4.5 DEF
   who's started well. So a cheap slot's achievable value ≈ a HIGH PERCENTILE of the
   band (you migrate toward performers), not the median/bust rate — the £4.5 DEF
   architecture can be right even if the first pick busts. This makes cheap slots
   MORE attractive vs premiums (cheap mistakes are cheap to fix; premiums lock up
   budget). Premium = paying for set-and-forget reliability. Cost of the cheap route
   = hit points + lag (owning the dud a couple of weeks before diagnosing/cutting).

## Data in hand
- `players_raw_2025-26.csv` — season totals, positions, start prices (reconstructed).
- `merged_gw_2025-26.csv` — FULL by-week: 38 GWs, 841 players, per-match points/
  minutes/opponent/home-away (+ DGWs). Enables fixture-swing, appearance rates,
  form-chasing / transfer modelling.
- `teams_2025-26.csv` — FPL attack/defence strength ratings per club.
- `players_2026-27.csv` — upcoming-season price list (558 players; floors GK/DEF 4.0,
  MID/FWD 4.5; forced floor £64m -> £36m discretionary). team_name = SHORT codes.
- `league_table_2025-26.csv` — final table (GF/GA/GD/PTS); enables opponent tiers by
  ATTACK (GF, for GK/DEF fixtures) vs DEFENCE (GA, for MID/FWD fixtures).
- `expected_points_2026-27.csv` — **forward-looking** club projections (the key one).
  Projected TOP6 (hard fix / best assets): ARS MCI LIV MUN CHE TOT. Projected BOTTOM6
  (soft fix / avoid their defence): CRY FUL SUN IPS COV HUL. Big RISERS: Spurs +20,
  Chelsea +16, Liverpool +11. Big FALLERS: Sunderland -12, Bournemouth/Fulham -8, Villa -7.
  Relegated: WHU BUR WOL. Promoted (cold-start, no history): IPS/COV 33, HUL 24.
  **Principle: adjust last-year per-player returns by the team's projected change** —
  Chelsea/Spurs assets UNDERvalued by 25-26 data; Sunderland/Bournemouth/Fulham OVERvalued.

## Findings so far (pre-full-brief)
- Discretionary £ works hardest in MID (steep, sustained); DEF flattens instantly
  (cheap DEF is a floor game, not a discretionary game); GK one playing keeper then
  dead; FWD a barbell (cheap busts, go premium or mid-punt).
- Pick-risk: cheap bands = high ceiling, low floor, many busts; premium = high floor.
- Fixture swing is MODEST (GK 3.1->3.8, DEF 3.3->4.4, MID 3.4->4.5, FWD 3.7->4.3;
  fixture-picking only +3-5%). Rotation value is mostly COVERAGE (starter doesn't
  play) not fixture-picking.
- **Two-axis decomposition (the key mental model):** EV ~= P(start) x pts-per-start x 38.
  Price hides both. At £5m, P(start) DOMINATES: nailed mid-table star (banked ~135)
  > premium-club rotation risk. Score every slot on BOTH axes, not price.
- **Value the SLOT not the player (auto-subs):** a starter's 0-min week is auto-subbed
  (~3 pt bench fill), so raw points OVER-penalise clean rotation. Banked vs raw:
  rotation +41 (73->114), nailed +10 (125->135) — gap halves. Clean rotators (De Ligt,
  Disasi[->CHE]) bank ~120 despite raw ~45. The CAMEO (1-59 min) is the real tax
  (blocks the sub, ~1pt): De Cuyper 17 cameo wks = trap. Cameo history = hard screen.
- **This is the real job of a playable bench** — underwrite clean-rotation upside plays
  (+~40/slot), FAR stronger than fixture-picking. So keep 1-2 benches playable; but the
  auto-sub is a shared/finite resource (~1 cover/week) so carry only 1-2 clean rotators.
  Refined DEF shape: mostly nailed archetype-B (2026-27-quality-adjusted) + 1-2 clean
  archetype-A upside plays under bench cover.
- **Club moves matter:** join last-season perf to 2026-27 club via permanent `code`;
  movers are new-context unknowns (Guehi->MCI, Senesi->TOT, Disasi->CHE).

## DEFERRED (Jon: "come to later")
- Transfers = a SCARCE RESOURCE that must create EV (a -4 hit must buy back >4 pts over
  the hold horizon), NOT free. In-season layer, after the initial-squad allocation.

## Method (planned)
1. Pull last season's per-player data: position, price, total points, minutes.
2. Floors per position = cheapest realistic playing price (verify from data).
3. Per position, build the value curve: baseline points from floor-price players,
   then MARGINAL points per extra £m (efficient frontier = best achievable at each
   price). This answers "where does each discretionary £ go furthest?".
4. Rotation/marginal model: value each slot as PPG × expected games-played for its
   role (nailed starter ≈34 games; rotation option ≈10–20 in its good fixtures;
   crashed fodder ≈0–3). Greedily deploy discretionary £ across starter-upgrades vs
   playable-bench-slots by marginal points/£ — the crash-vs-keep count emerges, with
   sensitivity on the one behavioural unknown (how much you actually rotate).
5. Apply the attack-shift haircut on CB/def-mid value.
6. Translate into a per-slot £ allocation summing to £100m, with rationale + chart.

## Assumptions to confirm
- Budget £100.0m; squad 2/5/5/3. (standard)
- Floors — will read the actual position minimums from the data; working values
  GK £4.0 / DEF £4.0 / MID £4.5 / FWD £5.0.
- **Which season is "last year"?** Folder is 2026-27; user said "start of the
  2025-2026 season". Need to confirm so the right season's data is used.
