# Player points forecasting — the spec

Jon's architecture, 2026-09-05, with the measured status of each input. This is the design the
model should implement. Evidence for every claim is in `FOOTBALL_RULES.md`; this file says what
to build and in what order.

---

## What this model is for

It predicts **future points by player, by gameweek**. It is the sole input to the strategy layer:
when to transfer, which transfer, whether to roll, chip timing, and planning the XI and bench for
future weeks.

Everything downstream is only as good as this. A session spent improving transfer logic while the
projections are wrong is wasted — that lesson was paid for on 2026-09-04, when wildcard timing was
re-derived three times as the layers beneath it were fixed, and the final answer still rested on
projections that miss by 95 points on a single call.

**Target split, and it governs the whole design:**

    E[points]  =  E[minutes]  x  E[points per 90]

Minutes are a manager's decision. Points per 90 is ability against opposition. A good week is
evidence about one and nearly silent about the other. Keep them apart at every stage — including
in the reporting, so a wrong projection can be attributed to the right half.

---

## The five inputs

### (a) Long-run delivery — points per GAME and points per 90

The dominant signal, confirmed repeatedly. Recent form correlates 0.435 with future points; every
other signal tested is an order of magnitude smaller.

**The distinction matters and is the split above.** Points per GAME already contains minutes and so
answers the decision question directly; points per 90 is the rate and is the only fair way to
compare a rotation player with a nailed one. Carry both. Never rank on points per game without
saying so — it will always favour whoever plays most.

STATUS: implemented, and sound. `HALF_LIFE = 20` measured and confirmed (B3) — the predictive curve
is flat from 6 to 20, so this is NOT a lever and should be left alone.

### (b) Recent swings in points or underlying metrics

Real, at **+0.151** against next-4 points, but ONLY measured relative to the player's own baseline
(B2). A raw form table ranks good players top whatever they are doing.

STATUS: **not implemented.** The model has no explicit form term beyond the recency weighting in
the rates. Worth adding, measured as deviation from the player's own long-run rate.

CAUTION: the first measurement of this said ~0.00 and was wrong — it conditioned on the player
still appearing, which removed everyone whose decline cost them their place. Jon caught it with
Palmer (7.76 -> 4.16 pts/90) and Saka (7.59 -> 3.95).

### (c) Players whose xG/xA "should come good"

**REJECTED (B5).** Under-conversion does not predict future points beyond the baseline (-0.019).
The gap regresses, but the model already projects from xG rather than goals, so average conversion
is assumed the moment you use an xG rate. Adding a "due a goal" term would double-count.

STATUS: correctly absent. Do not add it.

### (d) Upcoming versus past fixture ease

Worth about **43%** on points per 90 between the meanest and leakiest quarter of defences (B1).

STATUS: implemented via team ratings and `att_f`. Note the ratings carry the market's view already
(`fixture_ratings.IMPLIED` is the expected-points adjustment column), so the model is NOT blind to
fixture swings — a claim made and retracted on 2026-09-04. What it lacks is odds beyond GW+1.

### (e) Projected minutes — THE PRIORITY

**38% of the realised edge is lost here** (B4): a projected edge converts at 0.888 when you know
the player appears and 0.547 when you do not. No improvement to scoring rates recovers any of it.

The current model has one hand-set p60 with a prior, against an elaborate scoring model with
clean-sheet Poissons and defensive-contribution thresholds. The complexity is in the wrong half.

Jon's decomposition, which is the build plan:

**e0. Persistence is the base case.** A player consistently doing 80-90 minutes will continue to;
a rotation player will continue to be rotated. Minutes predict minutes — attacking output does NOT
predict minutes (A2, corr +0.02).

**e1. New to the club and suddenly playing 90** — project 90 forward rather than blending with a
thin or absent history. Examples this season: Rogers at Chelsea, probably Delap at Forest.
STATUS: untested, tractable. Distinguish "new signing bedding in" from "rotation risk" — the
current thin-sample shrinkage treats them identically and is wrong for the first.

**e2. Stepped in for an injured or suspended player** — trackable, and **FPL publishes an expected
return date**, so the model can know how long the deputy's minutes are likely to hold.
STATUS: untested, and the API field is not read anywhere. Probably the highest ratio of value to
effort on this list after red cards.

**e3. Managers changing the XI for freshness, form and tactics** — cannot predict WHO starts, but
the UNCERTAINTY ITSELF is predictable, and by a lot.
STATUS: **measured and confirmed (A3).** Start-to-start persistence spans 0.634 to 0.875 across
club-seasons, and a club's habit persists across seasons (within-club sd 0.041 vs between-club
0.055). It is NOT about club strength (+0.109) — it is the club and the manager.
BUILD: a club-level rotation prior on p60, estimated from that club's own recent start-persistence.

**e4. Red cards** — a ban removes the next match, 94% reduction in minutes (A1). Nothing in the
pipeline reads `red_cards`.

---

## Build order

1. **Red cards into the minutes model** (e4). Mechanical, currently missed, smallest correct fix.
2. **Club rotation prior on p60** (e3). Largest measured effect available — a 24-point spread in
   start probability, stable season to season.
3. **Injury-return dates** (e2). The API field exists and is unread.
4. **New-signing handling** (e1). Stop shrinking a new arrival who is playing every minute.
5. **Form term** (b), relative to the player's own baseline.

Everything above is minutes except the last. That is deliberate and it is what the evidence says.

---

## The methodological rule that outranks all of the above

**Check what every test conditioned on before believing it.** Three findings in one session were
distorted by conditioning on the outcome — B2's future appearances, A3's appearance filter, and an
earlier bias measurement that scored only players who actually played. Every one biased towards
"nothing to see here", because the cases that prove an effect are the cases that drop out.

Two of the three were caught by Jon from football knowledge, not by inspection of the code.
