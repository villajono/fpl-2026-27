# Brief — model corrections outstanding

## STATE OF PLAY, end of 2026-09-10. Read this first.

Jon's standing objective, restated because it kept having to be: **build a set of models that
RUN an FPL team to maximise season points.** Three components - a player weekly points forecast, a
strategy overlay, and the rules of the game. The model should say "I reckon I should wildcard this
week and bench-boost next, worth X, better than anything else I can see." It should not ask "shall
I play the Bench Boost?" A chip week is an OUTPUT.

    E[points] = E[minutes] x E[points per 90]

Improve BOTH halves every week. Today was almost entirely the minutes half.

### Test suite: 3 of 6 failing (was 5 of 6)

    PASS  cs-calibration        bias -0.013 on 60 team-matches
    PASS  premium-compression   WITHDRAWN as a defect - the test was wrong, see item 5
    PASS  minutes-recency       0 of 177 under p60 0.7, was 42
    FAIL  fixture-spread        +0.79 easiest-to-hardest, needs 1.5   <- biggest open defect
    FAIL  point-chasing         luck premium +0.66, needs <= 0.25
    FAIL  cover                 squad-shape check, not a model defect

### E[MINUTES] - six changes shipped today, all measured

  * Recency weighting on in-season starts. START_HALF_LIFE 0.75, fitted over 76,511
    player-gameweeks. Log loss -14.5%, Brier -18.2%.
  * INSEASON_K 2.0 -> 1.0, refitted JOINTLY with the half-life. Changing one alone made Wissa
    worse. Never tune one without the other.
  * Position/streak prior for players with no prior season, ensembled 50/50 and GATED to thin
    priors. Ungated it broke Gabriel (0.97 -> 0.90).
  * No-prior-season players shrink towards their own in-season rate, not NO_HISTORY_P60 = 0.05.
  * PRESEASON_OVR expires once a player has in-season minutes. Kinsky was pinned at 0.80 having
    played every minute; Phillips at 0.60 having played none.
  * Goalkeeper within-club normalisation - one keeper starts per club, a rule of the game rather
    than a fitted parameter. Now exactly 20 rated keepers across 20 clubs.

  STILL OPEN on minutes, in the order to take them:
  1. Injury-return dates (e2). FPL publishes them - Mateta "expected back 11 Oct" - and nothing
     reads the field. Cheapest remaining win.
  2. Displacement: whether the man who lost his place is FIT or INJURED separates taking a shirt
     from deputising. Suzuki, Hornicek, Lammens and Martinez are all cases where the displaced
     keeper is fit or gone. Needs measuring before the size is trusted.

### E[POINTS PER 90] - barely touched today, so this is where next week should go

  1. **fixture-spread, the biggest open defect.** +0.79 between easiest and hardest fixture
     against a 1.5 requirement. Clean-sheet probability alone should move a defender more than
     that.
  2. **Per-90 rates are applied as though every starter plays 90.** Given a start, mean minutes
     are GK 89.9, DEF 87.5, MID 83.2, FWD 81.8, and only 56% of midfield and 47% of forward
     starts reach 90 - so xG, xA and DefCon are overstated ~8% for midfielders, ~10% for forwards,
     22% for a 74-minute regular. `_minutes_from_data` already computes `mm` and spends it only on
     p60. NOT a flat mm/90: appearance and clean-sheet points do not scale with minutes.
  3. Bonus is a flat per-appearance rate, not fixture-adjusted. ~7% of all points.
  4. Bookmaker odds cover GW+1 only; GW+2 onwards falls back to the xG model.

### NO CONCEPT OF CORRELATED OUTCOMES (found by Jon, 2026-09-10)

`select_xi` maximises the SUM of expected points. That is correct for expectation and completely
blind to covariance, and the model therefore cannot see that two players behind the same defence
are perfectly correlated on the clean-sheet component.

The case: Verbruggen (BHA) and Kadioglu (BHA) both start, so 8 clean-sheet points ride on a single
event at p=0.356 - expected 2.85, standard deviation 3.83. Swapping to Kinsky (TOT, p=0.414)
splits it across two independent fixtures: expected 3.08, standard deviation 2.75. HIGHER expected
points AND lower variance, and the model preferred the double-up because Verbruggen's save points
are worth 0.15 more in isolation.

Jon: "just chase the clean sheet, and avoid doubling up on Brighton def." The model has no way to
express the second half of that sentence.

Worth fixing for two reasons beyond XI selection. Under a BENCH BOOST all fifteen score, so
concentration is at its most dangerous. And when protecting a rank rather than chasing one, the
variance is the thing you actually want to manage - a squad with three players behind one defence
is a different bet from a diversified one with the same expected total.

Cheapest version: when two candidates for the same XI slot are within a small margin, prefer the
one whose club is less represented in the squad. The full version needs a covariance structure -
clean sheets are perfectly correlated within a club, attacking returns partially so.

### Strategy layer - scripts/strategy.py, new today

  Decides the chip week rather than asking for it. Searches every wildcard week against a
  never-wildcard control, then values BB/TC/FH against the squad path that implies.

  ONE KNOWN BUG, hand-overruled three times today, which is the signal it should be code: it will
  spend a Free Hit for +4 because every fixture it can see out to GW16 is a single. Blanks and
  doubles cluster in the SECOND half (Jon), so an unplayed chip is being held, not wasted. Needs a
  full-season horizon or a floor on what a chip may be spent for.

### Out-of-sample test pending

  Two locked GW4 forecasts from either side of today's work, both written before the gameweek.
  After Saturday: `python scripts/score_p60.py --gw 4`. Believe the minutes work if the after-model
  wins on the THIN-PRIOR group specifically - the keeper group is near-deterministic and will look
  spectacular either way.

### The methodological rule, now earned three times over

  Every one of premium-compression, the first wildcard-timing test and the first streak ensemble
  measured something adjacent to the thing it was named for, and each would have shipped a wrong
  conclusion. **Check the units, check what the sample conditions on, and check whether the
  evaluation contains the case you are about to change.** A failing test is a hypothesis.

---


> **GW4 decisions are locked in `notes/GW4_DECISION.md` (2026-09-09).** Village Idiots plays the
> WILDCARD; Santa Claude makes one transfer, Mateta -> Barry, on pure model output. That file also
> records what the session settled about the model: premium compression WITHDRAWN as a defect (the
> test was wrong, see item 5 below), minutes recency confirmed as the live one, and three
> gameweeks of team results measured at ~12% predictive weight. Read it before re-opening any of
> those three.


Written 2026-09-01 after a session that fixed nine things and left six known-wrong.
For Jon and whoever picks this up next.

## Where we got to

Both squads are now pulled from the live API (`scripts/fetch_squads.py`, entry ids in
`data/state/entries.json`), chips are tracked per team, and overrides can express minutes
properly. Nine fixes are in and pushed — see `git log` from `4ab2738` to `6edf0b8`, each
message explains one.

**GW3 is played. What was actually done (the earlier note here was wrong):** Village Idiots made
NO transfer — Jon rolled to carry 3 free into a probable GW4 wildcard, since Tzolis was benched and
the move could wait. Santa Claude did Sarr → Szoboszlai. **Triple Captain played on Haaland, both
teams.** Note the TC recommendation was an artefact — `weekly.py:547` compares an odds-priced
current week against xG-priced future weeks, so it fires almost every week (see item 5). Jon played
it anyway on the judgement that GW3 was at least equal-best and Haaland might not stay fit or in
form. That reasoning stands; the code defect does not.

## THE SIX DEFECTS, AND WHY THE TOOL CANNOT RUN ALONE YET (2026-09-07)

**Read this before anything else in this file.** It supersedes the minutes-first build order
below, which addressed 6% of forecast error while the items here sat underneath it.

Jon, at the end of a session in which he overturned four separate recommendations:

> *"The thing that worries me is that the model / this conversation is spitting out some random
> advice. And when I challenge it, we adjust things. I don't think we've got this to a level —
> yet — where we could run a competitive FPL team standalone."*

That is the correct read, and the process problem is as important as the defects: **every one of
these was found because a human challenged an output, not because the model flagged it.** So each
is now a standing test in `scripts/model_tests.py` that fails loudly and prints its measurement.
All six fail today. Run it weekly; the goal is to turn them green.

    python scripts/model_tests.py

### 1. POINT-CHASING — but only for ATTACKERS (corrected)

Regress the projection on underlying output AND on points already scored. **Attackers only** —
midfielders and forwards, n=52:

    xGI per 90 (underlying)   +0.412
    points per 90 (actual)    +0.412     <- exactly equal weight

    overperforming (lucky)    n=21   xGI/90 0.377  ->  projection 4.51
    underperforming (unlucky) n=17   xGI/90 0.364  ->  projection 3.83

**A +0.67 luck premium for near-identical underlying output.** Finishing luck does not persist,
so the model buys attackers at the top of their variance. Jon: *"classic point chasing that
weaker FPL human managers do, which is a losing strategy."*

**CORRECTION — I first ran this across all positions and reported it as a whole-model defect.**
That was a mis-specified test. Across every position it gives +0.341 on points against +0.039 on
xGI, which looks damning and is not: a defender's points ARE clean-sheet points, so points/90
legitimately proxies his club's defensive strength and xGI is close to irrelevant to him. That
split is the model working. Defender quality is item 2 instead.

### 2. CLEAN SHEETS OVER-PREDICTED BY 10 POINTS — FIXED, and it was the defender defect

Jon's structural specification, 2026-09-07:

> *"I don't think the fundamental unit of projection for keepers and defenders should be historic
> points. It should be projected clean sheets, plus pMins... Goals and assists on historical
> delivery, fixture adjusted. DefCons on historic defcon rate, player-specific."*

**The model is already built exactly that way.** `compute_ev_v2` is

    ev_full = cs_prob*cs_pts + 2 + xG90*gp*att_f + xA90*3*att_f + p_dc*2 + saves + bonus
              + concede_pts + yellow
    ev      = p60*ev_full + p_cameo*ev_part

Clean sheet and appearance both gated on p60, goals and assists on historic per-90 rates with a
fixture multiplier, DefCon from a player-specific rate. The architecture was never the problem.

The NUMBER is. Retro-predicting the clean sheets in the 60 team-matches already played:

    mean predicted 0.373   actual 0.267   bias +0.106
    correlation predicted vs realised  r = +0.281

    predicted 0.3-0.4   n=19   mean 0.353   actual 0.211
    predicted 0.4-1.0   n=25   mean 0.484   actual 0.360

Optimistic in every band above 0.2, and it barely discriminates. Chelsea were given 0.529 having
conceded seven in three with no clean sheet; Man Utd 0.485 with six. **Since the clean sheet IS
the projection for half the squad, this one miscalibration explains the defender problems on its
own** — including why Newcastle's defenders looked better than Arsenal's, which was the thing
that surprised Jon into the whole review.

**FIXED 2026-09-07, and the cause was a definition, not a parameter.** FPL awards a clean sheet
for not conceding WHILE ON THE PITCH given 60+ minutes, so a defender substituted on the hour
whose team concedes in the 75th still records `clean_sheets` = 1. `_calibrate_cs` took the MAX of
that stat across a team's 60-minute players, which answers "did anybody manage a clean sheet"
rather than "did the team keep one". The two differ in **92 of 760 team-matches**, inflating the
calibration target from the true 0.2553 to 0.3763. C is chosen to reproduce that target, so every
clean-sheet probability in the model was scaled to a rate that never happened — and the +0.121
inflation is almost exactly the +0.106 bias measured live.

Now calibrated on `goals_conceded == 0`, which is unambiguous:

    C            1.0158  ->  1.4427
    predicted    0.373   ->  0.254   against an actual 0.267
    bias         +0.106  ->  -0.013     test now PASSES

**What this did NOT fix: discrimination.** Correlation is +0.289, essentially unchanged from
+0.281, and Chelsea are still given 0.405 having conceded seven in three. The LEVEL was wrong and
is now right; the model still cannot tell good defences from bad ones sharply enough. That is the
same underlying weakness as item 3 — the team ratings att/defw are too flat — and fixing it
should lift both. Re-measure after GW6; three gameweeks is a thin sample for the correlation even
though it is ample for the level.

**Everything computed before this fix used the inflated numbers**, including the GW4 transfer
advice given on 2026-09-07 and the wildcard comparisons. Re-lock the forecast before trusting any
of it.

### 3. FIXTURE TERM ABOUT A THIRD OF ITS PROPER SIZE

    difficulty 2 (easiest)  mean projection 4.55
    difficulty 5 (hardest)                  3.26
    spread                                  0.77

Clean-sheet probability alone should move a defender more than a point between the softest home
game and the hardest away one, before any attacking difference; 2.0+ is the right order. At 0.77
the model cannot tell you to sell a good player with a bad run, which is most of what a fixture
model is for. Found when Tavernier's projection fell only 0.54 for Liverpool at home versus
Brentford at home.

**Note what this does and does not change.** Scaling the fixture term preserves each player's
own mean, so four-week totals barely move — Tavernier 19.04 at 1x, 19.03 at 3x. What changes is
the WEEK BY WEEK shape, and therefore every one-to-three-week decision. Corrected to 3x, his run
reads 6.09 / 4.47 / 3.25 / 7.19 instead of 5.53 / 4.99 / 4.58 / 5.90, and over the GW4-6 window
he drops from first to third among the mid-price options.

### 4. NO RECENCY IN THE MINUTES MODEL

p60 is a season average. 44 of 180 players who started 60+ minutes in BOTH of the last two
gameweeks carry p60 below 0.70. Tzolis had started all three games, played 90 in the most recent,
and carried 0.42 — below even the naive 2-of-3 rate. Konsa had just taken Mosquera's place
(0, 11, 90 minutes) and carried 0.57. **This is what made Newcastle's best defender look better
than Arsenal's new starter**, and it is the same defect in both directions.

**One concrete bug found by this test and FIXED (`ev_v2._backup_keeper_codes`).** Six keepers
carried p60 of exactly 0.00 having played 90 minutes in each of the last two gameweeks —
Hornicek (NEW), Martinez (CHE), Rushworth (COV), Scherpen (IPS), Suzuki (AVL), Trafford (LEE).
Cause: the first-choice test read `_nxt.minutes`, which is LAST season's total, because
`refresh_players.py` deliberately preserves the performance columns as the model's prior. A
keeper who won the job this season therefore read as an understudy and was zeroed outright.
Chelsea shows the mechanism plainly — Sanchez left for Como on loan and Martinez inherited the
shirt. Suzuki was projected 0.00 for GW3 and returned 10. Now prefers this season's minutes from
the in-season store where any keeper at that club has played.

### 5. PREMIUM COMPRESSION - WITHDRAWN 2026-09-09. THE TEST WAS WRONG, THE MODEL IS FINE.

**Read this before acting on anything below in this item.** The defect does not exist. Measured
like for like - the model's own per-90 attacking rates against the same players' raw historical
per-90 rates, 187 attackers with 900+ minutes - it keeps **1.02** of the elite-to-mid gap.
Haaland, the player the defect was named for, comes out at 0.93 of his raw rate.

`test_premium_compression` was wrong in two independent ways, both inflating the apparent failure:

1. **Units.** It compared an xGI ratio against an EV ratio. EV is total points and includes ~2
   appearance points, a clean-sheet share and a DefCon share for every attacker whatever his
   attacking output. Over 538 attacker-seasons of 2022-25 a 2.54x gap in xGI/90 converts to a
   1.55x gap in points/90 - a conversion of 0.36, not 1.0. Requiring 0.85 asked for more spread
   than football produces.
2. **Sample.** The xGI came from the live bootstrap over the gameweeks played - three of them.
   The top decile of a three-game xGI table is mostly finishing noise, and regressing it is
   correct. Ranking on the first three gameweeks of 2022-25, the top decile shows 6.69x the
   mid-tier's xGI/90 and then scores 1.70x their points per game.

This is the THIRD test in this project distorted by comparing quantities that answer different
questions, after the two recorded in FORECAST_SPEC.md. The methodological rule stands and should
be applied before any failing test becomes a work item: **check the units, and check what the
sample conditions on.** A failing test is a hypothesis, not a finding.

The optimiser dropping Haaland is therefore NOT evidence of compression. It is a £15.5m price
judgement against a six-week horizon, and forcing him back into the wildcard squad costs 1.0
point of objective - the model is close to indifferent, which is a reasonable view rather than
a broken one.

The original item is kept below for the record.

### 5. PREMIUM COMPRESSION (open since 2026-09-04, now much worse than thought)

Top five attackers by xGI/90 against the mid-tier:

    real gap    3.13x   (xGI/90 0.938 vs 0.299)
    modelled    1.23x   (projection 5.06 vs 4.10)
    share kept  0.11

The earlier estimate was that the model keeps about 75% of the elite gap. Measured this way it
keeps **eleven per cent**. Some of that is that projections include appearance and bonus points
that do not scale with xGI, so 0.11 understates it — but not by enough to explain the gap. This
is why the optimiser drops Haaland, and why it captains Gabriel over him.

### 6. NO COVER VALUE — a dead bench player looks free to hold

Squad metrics score a non-starting player at zero, so holding a player who cannot play costs
nothing on paper. Mateta was out until 11 October and never surfaced as a priority sale, because
he did not appear in the best XI either way — while being one of only three forwards. The test
does not ask what the bench is WORTH; it asks whether it exists, and today reports Santa Claude
has one fit goalkeeper and one that must start.

**Jon has now corrected this same blind spot in two different models.** It is a standing bias in
how I score squads, not a one-off.

### What this means for using the tool

Do not let it pick a squad. It is currently a hypothesis generator whose outputs need a human
football check — which is exactly what happened all through 2026-09-07, where Jon overturned the
Newcastle-over-Arsenal defence call, the Mateta hold, the Tavernier fixture read, and a wildcard
recommendation built on all three. Fix these in the order above. Items 1-3 change every recommendation the tool makes; item 2
alone drives half the squad.

## GW3 SCORED (2026-09-07) — the first real out-of-sample test

Village Idiots 56 (total 219, rank 689k). Santa Claude 59 (total 200, rank 2.3m). GW3 average was
51, so both beat par — but both triple-captained Haaland, who returned 9, worth **+9 over simply
captaining him**. Strip the chip out and both squads scored *below* average, 47 and 50. The chip
turned a poor week into a mediocre one. Not a reason to reopen chip timing, which is settled; it is
on the record as what that call actually cost.

**The forecast held up in the middle and broke at the top.** 491 players scored against actuals.
Read the bias column with care: the only lock on disk was a GW4 forecast, so this compares GW4
projections against GW3 results. That is a fair test of ORDERING — the same players should be good
in both weeks — and not a clean test of the level.

    projected     n    mean proj   mean actual   error
    0-1         161        0.27          0.61    -0.35
    1-2         119        1.47          1.16    +0.31
    2-3          70        2.49          2.07    +0.42
    3-4          74        3.52          3.26    +0.26
    4-5          44        4.36          3.91    +0.45
    5-6          18        5.38          4.00    +1.38
    6+            5        6.56          1.60    +4.96

Correlation 0.441 across the pool, MAE 1.63. **Monotonic all the way up** — a higher projection
really did mean more points, which is the property everything downstream depends on. The top-band
failure is n=5 with two Chelsea players in the same fixture; **hold it loosely.** It points the
opposite way to the standing "model undervalues premiums" finding below, and one gameweek cannot
settle that. Revisit after GW6 or GW7.

### Where the error lived, and the four causes behind it

Minutes calls accounted for **113 of 802 points of absolute error — 14%, from 5.7% of the pool**.
Eleven players were projected 3+ and played zero minutes. Jon's diagnosis, which was right and
replaced a much worse one of mine ("build a club rotation prior"): these are four different
problems and only some are fixable.

    stale snapshot        3   Wieffer (knee), Sanchez (loan to Como), Richarlison (left out)
    doubtful, half-caught 2   Mosquera 75%, O'Reilly 75% — model applied 0.75, they played 0
    European rotation     1   Pau Torres — status "a", no flag exists, no PL signal possible
    pure selection        5   Colwill, Senesi, Frimpong, Gray, McNeil

**A hypothesis I got wrong, recorded so nobody re-runs it:** I proposed that `status` was unread
and that non-available players with a null `chance_of_playing` were slipping through at
availability 1.0. Measured: **0 of 170 flagged players have a null chance.** FPL always sets one.
The mechanism does not exist. `_availability()` reading only `chance_of_playing_next_round` is
fine.

**The real cause was freshness, and it is now fixed.** `data/raw/players_2026-27.csv` carries the
injury flags and is read into `ev_v2._nxt` **at module import time**. It was last written
2026-09-02 15:12; the GW3 forecast locked 2026-09-04 16:53 — **fifty hours stale**.
`auto_ingest_and_refresh()` ingests results and rewrites the form's players.json, and its docstring
promises "never on stale data", but it never touched this CSV. All three of Wieffer, Sanchez and
Richarlison carried `chance_of_playing = 0` live at the time.

Two fixes are in `scripts/forecast.py`:

* `_refresh_availability()` runs `refresh_players.main()` **above the `import weekly` line**. It
  has to be above it: ev_v2 reads the CSV at import, so refreshing afterwards leaves the stale
  frame in memory and changes nothing. The odd-looking import placement is deliberate.
* `_assert_availability_fresh()` refuses to lock a forecast on flags older than 12 hours.

The first run of it found **25 players new to the game and 7 club changes** the model had never
seen — Grealish MCI→EVE, Enzo CHE→MCI, Tosin and Mudryk CHE→TOT among them.

**A second defect found while testing:** `OUT` in forecast.py was `pathlib.Path("data/processed")`,
relative to the working directory. Run from `scripts/`, it wrote
`scripts/data/processed/forecast_gw4.json` — so the file it "locked" and the file every downstream
tool reads were different files, silently. Now anchored to the project root. Worth grepping for
other relative paths.

**Still outstanding from this list:**

* **Recency on minutes.** Senesi played 0 minutes in GW2 and was still projected 4.23. A player who
  did not play last week should not project as a starter. This is catchable from data already held
  and is the cheapest remaining item.
* **GW3 was never locked, so there is no clean calibration record for it.** `forecast_gw4.json`
  is exactly what its name says: a GW4-onwards forecast, built on 2026-09-04 for the wildcard
  planning. `ev_multi(code, name, pos, team, gw)` takes an ABSOLUTE gameweek and looks up that
  week's fixtures, so `ev[0]` is GW4. I briefly claimed an off-by-one on the strength of the GW3
  correlation; that was wrong, and the reasoning is worth recording because it is a trap. A GW4
  projection correlates with GW3 actuals at about the same 0.44 REGARDLESS, because player quality
  persists across a week. Correlation with a week's results does not identify which week a
  forecast was for. Lock a forecast every gameweek so `calibration.py` has a real record.
* Colwill, Frimpong, Gray and McNeil are manager decisions invisible in public data. That is what
  the override form is for. Do not try to model them.

### European fixtures — `scripts/euro_fixtures.py` (new)

**The direction is the counter-intuitive one.** The instinct is post-match fatigue; Jon's read on
the Pau case is that he was rested **ahead** of Club Brugge, protected rather than recovered. The
script therefore records both distances and lets a measurement decide which one matters:

    days_to_next_euro      PL match -> next European tie    (protection ahead of it)
    days_since_last_euro   previous European tie -> PL match (recovery after it)

Source is TheSportsDB's free tier, no key, per-team next/last events. Two traps found: the free
tier throttles and returns an **empty body rather than a 429**, so a throttled lookup is
indistinguishable from "club not in the database" — the first run silently concluded Liverpool and
Manchester City did not exist. There is now backoff plus a persistent id cache at
`data/raw/euro_team_ids.json`. The horizon is short, so **re-run it weekly rather than trusting the
stored file**.

**It is a feature, not an adjustment. Nothing reads it yet and nothing should until the effect is
measured** on European fixture history joined to the player-gameweeks in `data/raw/history`.
Hand-setting a rotation multiplier because the story is persuasive is precisely the failure mode
this project keeps repeating.

## START HERE (2026-09-05)

Read in this order:

1. **`notes/FORECAST_SPEC.md`** — what the forecasting model should be, input by input, with the
   measured status of each and a build order. This is the plan.
2. **`notes/FOOTBALL_RULES.md`** — the evidence, measured on 83,835 player-gameweeks of real
   Premier League football from 2022-23 to 2024-25 (`fetch_history.py`, `theories.py`,
   `structural.py`).
3. The item list below, which is now mostly downstream of both.

**Jon's steer, and it should govern the next several sessions:** at least 75% of effort goes on
player-level points forecasting. Everything else — transfers, chips, wildcard timing — is a
decision layer sitting on those numbers, and improving its logic while the inputs are wrong is
wasted work. That was demonstrated the hard way on 2026-09-04.

**The single most useful measurement:** a projected edge converts at 0.888 when you know the player
appears and 0.547 when you do not. **38% of the realised edge is lost in minutes**, and no
improvement to scoring rates recovers a point of it. The model's complexity is currently in the
wrong half — an elaborate scoring model with clean-sheet Poissons, against one hand-set p60.

**Build order (from FORECAST_SPEC):** red cards -> club rotation prior -> injury-return dates ->
new-signing handling -> a form term. Four of the five are minutes.

**Do not tune wildcard timing, CHIP_THRESH, or HALF_LIFE.** All three were investigated to a
conclusion on 2026-09-04/05: HALF_LIFE is measured and flat (leave at 20), and the chip rules sit
downstream of projections that miss by 95 points on a single call. Items 6 and 7 below record why.

## THE OPEN QUESTION (2026-09-04) — the model undervalues premium players

Jon's read, confirmed by measurement: **the model compresses elite players towards the average.**

    xG90            model     history (2025-26)
    Haaland         0.707     0.777
    Mbeumo          0.500     0.413
    ratio           1.41      1.88     <- the model keeps only 75% of the real gap

Consequence: the optimiser drops Haaland for a cheaper mid-tier player, because his edge is
understated by about a quarter while Mbeumo's is inflated 21%. Jon: *"I am concerned about not
having Haaland for weeks 5, 7 etc when he's obviously captain, could well score 15+ points.
Mbeumo is nowhere near as good."* He is right, and this is the same failure as item 1, which
recorded the ratio at 1.06 when HALF_LIFE was 8. Raising it to 20 got to 1.41 and stopped —
**by argument, never measured**, and still marked PROVISIONAL in history.py.

**This is now checked automatically every week** (`model_review.py`, Stage 2), so it cannot be
forgotten again — the weekly report prints FAIL until it is fixed. The fix is to MEASURE
HALF_LIFE with backtest.py rather than argue it, which is item 1.

Do not tune it by hand to make this one pair pass. That is how the guessed constants got here.

## What the weekly run now does, in order

1. **Refresh** — ingest the completed GW, re-weight rates and Bayesian team ratings (was already there)
2. **Stage 1, RE-CALIBRATION** — report what moved in the inputs and by how much (`model_review.py`)
3. **Stage 2, MODEL IMPROVEMENT** — standing audit against known failure modes (`model_review.py`)
4. **FORECAST ACCURACY** — locked predictions vs what actually happened (`calibration.py`)
5. The decision report, as before

Stages 2-4 are new on 2026-09-04 and exist because every check before them compared the model
against the season its own rates were fit on, which is marking your own homework. Only a LOCKED
forecast compared with a later result is honest, and nothing recorded what the model had believed
at the time until `forecast.py` started writing dated files.

**None of the three changes a number.** Auto-tuning on two gameweeks would chase noise.

## The forecast / optimise separation (Jon's architecture, 2026-09-04)

    FORECASTING   forecast.py — central estimate per player per week from history, form,
                  underlying data, opponent strength and pMins. Uncertainty lives HERE and is
                  recorded as a per-player confidence. Written once to forecast_gwN.json and
                  FROZEN; it refuses to overwrite without --force.
    OPTIMISATION  squad_opt.py — treats that file as rock solid and answers only "given these
                  projections, here is the best squad". Deterministic. Never recomputes EV.

Why it matters: when a recommendation changes you can now tell whether the FORECAST moved or the
SEARCH wandered. Before, those were indistinguishable, and it was usually the search.

## squad_opt.py replaces hill-climbing — and the reason is not cosmetic

The greedy climb returned squads **33-36 points below optimal**, and two runs on the same
objective differed by 3. That is search noise, and it sat underneath `wc_gain` (= refit - current),
which drives wildcard timing, which drives the transfer threshold, which drives every weekly call.
Jon: *"If we can't reliably select a WC team, we can't reliably choose a date to fire the WC.
That in turn undermines all transfer and chip thinking."*

`squad_opt.solve()` is an exact MILP (scipy.optimize.milp / HiGHS, already installed). Rank weights
are linearised as slot assignment — because the weights DECREASE and we maximise, the solver sorts
players into slots by itself. The weekly captain is a per-week binary. Validated three ways: solver
objective equals compare.squad_value on the returned squad; it beats both known hill-climb optima;
and it matches exhaustive brute force on a restricted pool.

**STILL TO DO — the point of the exercise:** `weekly._wc_refit` is still the old greedy climb, so
`wc_gain`, `wc_fires` and chip timing remain on the unreliable search. Until that is swapped for
squad_opt.solve(), the hazard finding in item 7 ("fires GW7, hindsight best GW8") is measured on
sand and must not be relied on.

## What is still wrong

Ranked by how much it distorts decisions.

### 0. Feed the odds path — cheapest win, but it only covers the coming gameweek

Markets aggregate more information than any xG model, so odds are the closest thing to truth we
have for fixture difficulty and scoring probability. `odds.py` already does this properly —
Pinnacle 1X2 + O/U via The Odds API, overround stripped multiplicatively, clean sheets derived by
inverting to implied lambdas. It is not a thing to build; it is a thing to feed.

State as at 2026-09-01:

- **No API key.** `ODDS_API_KEY` unset and `data/state/odds_key.txt` absent, so the Pinnacle path
  is dead. **Jon: a free-tier key at the-odds-api.com unlocks it** — that is the single highest
  value action on this whole list.
- **The keyless fallback has a three-day horizon.** `football-data.co.uk/fixtures.csv` held 48
  rows spanning 01/09–03/09 and **zero** Premier League rows, because no PL game falls in that
  window. GW3 (4–6 Sep) will appear in it around 2–3 September. So "GW+1: xG model (no odds
  published)" was correct reporting, not a bug — and Wednesday's or Thursday's run should pick
  the odds up on its own.
- `FPL_USE_FD_ODDS=1` is set in the workflow but not locally, so local runs silently differ from
  the cloud ones. Worth setting when reproducing a report by hand.

**But odds only ever reach the near fixtures, and that split is already built** —
`weekly.py:599` prints "GW+4+ always xG model" and `fixture_inputs()` returns None past the
published window so the caller falls back. So odds fix captaincy and selection for the coming
gameweek. They do nothing for a six-week transfer hold, which is owned by the xG model and its
team ratings throughout. Items 1 and 3 are the BASIS of transfer planning, not a fallback for it —
do not treat a key as making them optional.

### 1. Calibration is guessed, not measured

`HALF_LIFE` for xG/xA was 8 appearances, which leaves ~12 effective games; one 2.57-xG match
brought Mbeumo (~10 league goals) to within 6% of Haaland (~27). Flat ratio 1.88, model had
1.06. It is now **20**, chosen by argument and marked PROVISIONAL in `history.py`.

`backtest.py` (42KB, walk-forward, already written) is the tool to settle it. Calibrate together:

- `HALF_LIFE` per field — xG/xA/saves/dc
- `INSEASON_K` in `ev_v2.py`, the Beta prior weight on in-season starts
- the team-rating `K` (item 3)

Nothing else in this list should be tuned by judgement once the harness is running.

### 2. Three scoring terms are missing entirely

All three bias the same way — against premium forwards, toward defenders — which is why the
engine currently wants to captain a defender.

| Term | Rule | Rough size |
|---|---|---|
| **Bonus** | 1–3 per match | 0.3–0.8 /game for premium players. Already stored in `gw_history.csv` and never read |
| **Goals conceded** | −1 per 2, GK and DEF | ~−0.7 /game for a defender at a leaky club |
| **Yellow cards** | −1 | −0.1 to −0.2 /game, worse for defensive midfielders |

Bonus wants calibrating from the stored column, not guessing. Defenders currently get
clean-sheet upside with none of the downside.

### 3. Team ratings over-react to two gameweeks

Coventry's `defw` moved **1.40 → 1.20** on two games; the report prints its own weighting as
`[K=5, prior 71%/data 29%]`. Twenty-nine percent on two matches is too much, and it feeds
every fixture multiplier the model still owns. Same disease as item 1, one layer up.

Note this is exactly what odds replace. With a key, `att_f` and `cs_prob` for the near fixtures
come from the market and these ratings stop mattering for them — which is the argument for doing
item 0 before spending long on this.

### 4. Overrides reach minutes but not rates

`P60_OVR` handles p60 / p_cameo / partial. There is no way to say "his role has changed, his
rate is stale". The case that exposed it: Rutter's xG90 of 0.147 was earned playing behind
Welbeck, who has since been sold, so Rutter is now Brighton's man — and the model cannot be
told. Add `xg90` / `xa90` to the override shape, alongside the existing minutes fields in
`weekly.py::_minutes_shape`.

### 5. Minor — Triple Captain tolerance

`tc_rec` fires only at the exact half-season peak (`- 1e-9`) while Bench Boost allows `- 0.5`.
The asymmetry looks unintentional. It did not change this week's answer (7.2 against an 8.6
peak) but it means TC is held on an eleven-week-out projection.

### 6. DECAY — measured 2026-09-04, but still not wired into weekly.py

**Done:** `scripts/hazard.py` measured it walk-forward over 2025-26, 55k player-gameweek
projections. DECAY[k] is the share of a projected EDGE still realised k weeks out — the OLS slope
of actual on projected, normalised to k=1, which is the right quantity because a transfer is a bet
on a projected difference, not an absolute.

    guessed   1.00  0.85  0.70  0.55  0.40  0.25
    measured  1.00  0.92  0.88  0.83  0.80  0.79

The guess was far too steep — it discarded three quarters of a GW+6 gain where four fifths
survives. All three copies now carry the measured numbers.

**The decomposition is the more useful half.** Conditional on the player actually appearing, the
curve is flat: trend -0.009/week, still 0.94 at k=6. Unconditionally it is -0.042/week. So what
decays is knowing WHETHER he plays, not how well he plays when he does. **The lever for horizon
uncertainty is a minutes model, not a bigger discount** — which is also why item 4 (rate overrides)
matters less than it looked, and p_start accuracy matters more.

**Still open:** `squad_engine.py:147` uses DECAY, so its behaviour changed with this commit.
`weekly.py`'s copy is still unreferenced — `best_transfer` remains equal-weighted and documents
that as deliberate. Wiring it in would make far-horizon gains count ~20% less than they do now,
which lifts near-term transfers over fixture-swing ones. That is a real behaviour change on live
recommendations and wants Jon's sign-off, not a silent commit.

### 7. Wildcard timing — BENCHMARK FIXED, but STOP WORKING ON THIS

`hazard.py --wildcard` now runs BOTH arms through `backtest.simulate()`, so each maintains the
squad with free transfers on the live graduated threshold and takes hits under the live rule. The
earlier version froze both squads from GW4, which credited the wildcard with work free transfers
were doing and removed the only real reason to wait.

    best week GW10   986 pts   +57 vs never
    live rule fires  GW7  953  +24 vs never, costing 33
    six of sixteen weeks score BELOW never playing the chip at all

**Do not read that last line as "timing is dangerous".** Jon queried it and was right to: the model
NEVER projects a wildcard as negative — checked, 0 of 16 weeks, the invariant holds because the
current squad is always in the solver's feasible set. The negatives are REALISED, not projected:

    GW10   projected +72.5   realised +57
    GW14   projected +59.0   realised -36     <- a 95-point miss on one decision

That is a FORECAST failure, not a timing failure. The wildcard is simply the decision that exposes
it worst, because it acts on twelve players at once rather than one.

**Therefore: do not tune CHIP_THRESH or the local-max test.** Not because the benchmark is broken
any more — it is sound now — but because the rule sits downstream of projections that miss by 95
points on a single call. Tuning against them fits noise. The rule already identifies GW10 (it fires
GW7, 9, 10 and 18); its flaw is firing early, which is the local-max lookahead `d in (1,2,3)` being
shorter than the three-week gap, not the threshold height. That is a one-line change with an
obvious direction — make it when the forecasts are trustworthy, and test it across several starting
squads (`build_start_squad` takes a `core` argument) rather than the single one used so far.

**Work item 1 and the elite-compression FAIL first.** Everything here is downstream of them.

### 9. Fixture swing is measured against the league, not against your squad

`scripts/swing.py`, added 2026-09-04. The two existing signals do not answer the wildcard question:
`fixture_swing(team)` is a LEVEL not a swing (its own comment concedes there is no 'recent' half),
and `_swing_present(gw)` is True if ANY of the twenty clubs has a swing — it gates the wildcard
recommendation, is almost always True, and knows nothing about who you own.

What matters is the MOVE COUNT: how many changes the fixture picture implies against how many free
transfers you hold. One transfer fixes one player; the wildcard's whole advantage is fixing several
at once.

**Two bugs found and fixed the same day, both worth remembering as a class of error:**
1. It ranked buy targets on FIXTURE EASE ALONE, which put Fulham top — a kind run at a club the
   market expects to get worse (IMPLIED -7.5). What a player is worth is club strength TIMES
   fixture ease. Ranking on the product moved Fulham 1st -> 6th.
2. It excluded any club Jon already owned a player at. FPL allows three, and "two more of these"
   is exactly the shape of a swing rebuild, so it now ranks on FREE SLOTS. That is what surfaced
   Chelsea, which had been silently hidden behind Joao Pedro.

For GW4-9 it then backs Jon's plan clearly: CHE attack index 1.65 (top by a distance, 2 slots),
NEW 1.26 attack and 1.23 clean sheet (best all-round, 3 slots), MUN clean sheet 0.97 — so Shaw is
a stronger sell than Mbeumo, whose 1.24 attack index survives the fixture turn.

**A caveat I got wrong, corrected here so it is not repeated:** the ~90% prior weighting does NOT
mean the model is blind to fixture swings. The prior is last season scaled by
`fixture_ratings.IMPLIED`, which IS the adjustment column of `expected_points_2026-27.csv` — the
market's expected-points view (CHE +16, TOT +20, LIV +11, NEW +3.5). The fixture columns look small
only because they average six opponents. The club columns carry the market.

**The one real weakness:** the move count is a FLOOR. It counts players escaping a bad run, never
players repositioned into a good one, so a wholesale reshape still scores low.

## How to work it

Verify against the live API before defending any model output — three of the six bugs found
on 2026-09-01 were spotted by Jon from football knowledge first and confirmed in the code
after. Two of them I initially argued were correct behaviour.

Re-run `python scripts/weekly.py` after each change and diff the transfer, captain and chip
lines for both teams. Anything that moves a decision wants explaining before it is kept.

## Do not redo

- Squads, chips, entry ids — all live from the API now, `fetch_squads.py`
- The GW1–2 backfill: `gw_history.csv` carries `opp` and `home`
- Anything in the nine commits; each message records what was wrong and what it changed
