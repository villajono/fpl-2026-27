# Measured football rules

Derived 2026-09-04 from three real prior seasons — 83,835 player-gameweeks, 2022-23 to 2024-25,
sharing no players with the season being played. See `scripts/fetch_history.py` for why that is
the point: these seasons cannot predict an individual, but they settle structural questions the
model previously answered by argument, on data it has never seen.

Reproduce with `python scripts/theories.py` and `python scripts/structural.py`.

---

## The split everything hangs off

    E[points]  =  E[minutes]  x  E[points per 90]

The two halves have almost nothing in common. Minutes are a manager's decision — selection,
discipline, rotation, injury. Points per 90 is ability against opposition. **A good week is
evidence about one of them and nearly silent about the other**, and treating it as evidence about
both is the single most common way to get a projection wrong.

---

## Group A — MINUTES

### A1. A red card removes the next match. SUPPORTED, strongly.

    minutes in the next match after a red card    4.0   (n=67)
    after any other appearance                   71.5   (n=22,823)      a 94% reduction

Mechanical — a ban is at least one game — and near-total in the data.

**Rule:** a red card forces p60 to ~0 for the following gameweek.
**Model gap:** nothing in the pipeline reads `red_cards` when forecasting the next week's minutes.
Rare (67 in three seasons) but perfectly predictable and catastrophic when missed, which is the
best possible ratio for a fix.

### A2. Attacking output does NOT drive minutes. REJECTED.

Change in xG+xA per 90 against the following four gameweeks' minutes: corr **+0.014**, and
**+0.022** against the part recent minutes cannot explain. 15,988 windows.

The folk theory — attackers who stop producing get dropped — does not survive contact with the
data on this horizon.

**Rule: minutes predict minutes.** Do not let scoring form move p60.

### A3. CORRECTED 2026-09-05 — rotation IS predictable, but by CLUB, not by club STRENGTH.

The first version compared minutes volatility at strong clubs against everyone else, found nothing,
and carried a caveat that it had conditioned on players with 10+ appearances — which quietly
removes the rotated. Re-tested on start-to-start persistence, which is what rotation actually is
and needs no appearance filter:

    P(starts again | started last week), by club-season, 60 club-seasons

    least secure                        most secure
    Chelsea    2022-23   0.634          Arsenal    2022-23   0.875
    Brighton   2023-24   0.639          Brentford  2024-25   0.874
    Liverpool  2022-23   0.666          C. Palace  2023-24   0.872
    Spurs      2024-25   0.684          Newcastle  2024-25   0.856
    Man Utd    2024-25   0.686          Everton    2022-23   0.853

**A spread of 0.241.** A starter at the most rotation-happy club has a 63% chance of starting again;
at the most settled, 88%. For a minutes model that is an enormous effect — larger than most terms
currently in the EV model.

**But NOT by strength.** corr(club season points, start persistence) is **+0.109** — if anything
stronger clubs rotate slightly LESS. The "big clubs rotate more" folk theory is not supported. It is
about the club and its manager, not the size of the squad or European commitments.

**And it persists.** Within-club standard deviation across seasons is **0.041** against a
between-club spread of **0.055** — a club's rotation habit is more stable than the differences
between clubs, so last season's habit forecasts this season's.

**Rule: p60 needs a club-level rotation prior, estimated from that club's own recent
start-persistence.** This is the useful form of "Man City minutes have never been secure": you
cannot predict WHO starts, but you can predict HOW RELIABLY anyone does, and that is stable.

---

## Group B — POINTS PER 90

### B1. Weak opposition is worth about 40%. SUPPORTED.

    vs the meanest quarter of defences   3.01 pts/90
    vs the leakiest quarter              4.30 pts/90        +43%

23,514 appearances; correlation between opponent goals conceded per game and points per 90 is
+0.147.

**Rule:** the honest spread of the fixture effect, best defence to worst, is about 43% on points
per 90. Any fixture multiplier materially wider than that is overstating what a kind run is worth.

### B2. CORRECTED 2026-09-04 — recent form DOES carry information.

**The first version of this rule was wrong, and the error was survivorship.** It required four
future APPEARANCES, so a player who collapsed and was dropped had no outcome and left the sample —
filtering out exactly the cases the rule was supposed to describe. Jon challenged it with Cole
Palmer and Bukayo Saka, and was right.

Re-run counting a non-appearance as ZERO, which is what a manager actually banks:

    form change vs next-4 points per gameweek    corr +0.024   beyond baseline  +0.151
    form change vs next-4 points per 90          corr -0.001   beyond baseline  +0.083
    form change vs next-4 minutes                corr +0.055   beyond baseline  +0.053

**+0.151, not the +0.009 originally reported.** Fifteen times larger.

**Why the raw correlation hides it, and this is the part worth understanding.** By decile of form
change, over 10,234 windows:

    decile   form change   next-4 pts/GW   next-4 mins   vs overall mean
         1         -2.91            3.03          65.1            +0.22
         4         -0.65            2.59          67.1            -0.21
         7          0.48            2.64          67.0            -0.16
        10         +3.25            3.22          70.3            +0.42

Both extremes outscore the middle. **The biggest decliners still beat the average** — 3.03 against
2.80 — because a player who falls a long way is a good player with a long way to fall. Quality and
form change are entangled, and only controlling for the baseline separates them.

**The rule, stated properly:**

> A player in decline still outscores the field, but he underperforms what his own quality would
> predict — and that gap is what selling captures. Palmer at 4.16 points per 90 was still a decent
> footballer; he was no longer a 7.76 player, and he was priced as one.

Verified on the two cases raised:

    Cole Palmer  2024-25   pts/90 first half 7.76 -> second half 4.16
    Bukayo Saka  2024-25   pts/90 first half 7.59 -> second half 3.95

**Consequences for the model:**
- Form belongs in the projection, weighted against the long-run rate rather than ignored.
- It must be measured RELATIVE to the player's own baseline, never as a raw level. A raw form
  screen ranks good players top whatever they are doing.
- The minutes effect (65.1 vs 70.3 minutes across the extremes) partly qualifies A2: attacking
  output does not predict minutes, but POINTS form modestly does — plausibly because points are
  what a manager sees.

### B3. HALF_LIFE is not the lever. RE-TESTED 2026-09-05 and CONFIRMED.

Re-run without the survivorship filter that broke B2, so the target is the next GAMEWEEK's points
with a non-appearance scored as zero:

    half-life    slope    corr        (sound version, 32,877 windows)
         6       0.547   0.149
        12       0.557   0.147
        20       0.553   0.145        <- current setting
      flat       0.537   0.140

Flat from 6 to 20. Correlation peaks at 6, slope peaks at 12, and the two statistics disagree about
where the optimum is — which is what a flat curve looks like. Moving 20 -> 12 gains 0.004 of slope,
about 0.7%.

**Rule: leave `history.HALF_LIFE` at 20.** It is not worth a change on its own, and it is not the
cause of the Haaland/Mbeumo compression. Unlike B2, this finding was ROBUST to the survivorship
flaw — the unsound version picked 6 as well.

### B4. Minutes uncertainty costs 38% of the realised edge. The headline number.

The same sweep, run both ways, is a clean measurement of what not knowing the lineup costs:

    slope of actual on projected, CONDITIONAL on him appearing     0.888
    slope UNCONDITIONAL (non-appearance scored as zero)            0.547

A projected two-point edge delivers about 1.78 when you know he plays and 1.09 when you do not.

**Rule: the scoring model converts a projected edge at 0.888, which is decent. Everything lost
between 0.888 and 0.547 is not knowing whether he plays, and no improvement to xG rates touches
it.** This is the quantified case for spending effort on minutes rather than scoring, and it
matches the decay finding in `hazard.py` from the other direction.

### B5. Under-conversion of xG does NOT mean a player will "come good". REJECTED.

The most popular signal in FPL: a player whose xG+xA is running ahead of his goals and assists is
due a correction, so buy him. 18,258 windows, eight games of evidence against four gameweeks of
outcome:

    quintile of conversion gap    gap now   gap next   next-4 pts/GW
    worst under-conversion          -0.18       0.03            2.32
    middle                           0.00       0.02            2.36
    best over-conversion            +0.39       0.08            2.96

    corr(gap now, next-4 points)                        +0.120
    ...beyond the player's own baseline                 -0.019

**The over-performers score MORE next, not less** — 2.96 against 2.32 — and beyond a player's own
baseline the signal is **-0.019**, indistinguishable from zero.

**Why the theory feels right but is not actionable.** The GAP itself does regress: -0.18 and +0.39
both converge towards ~+0.05. That part is true. But it does not lift the under-performer's POINTS
above his own baseline, because **the model already projects from xG rather than from goals.**
Conversion at the average rate is assumed the moment you use an xG-based rate. The regression edge
is priced in already.

**Rule: do not add a "due a goal" adjustment. It would double-count what the xG rate already
assumes.** The raw +0.120 correlation is just good players over-performing xG, which the baseline
already knows.

## What this says about where the error lives

**Read the corrected B2, not the first version.** The original conclusion here — "scoring form
predicts neither scoring nor minutes, so the error is all in minutes" — rested on a rule that
turned out to be an artefact of survivorship. The corrected picture:

- **Form predicts scoring**, at +0.151 beyond a player's baseline, once dropped players are
  counted rather than discarded.
- **Form predicts minutes weakly** (+0.053), which qualifies A2: attacking OUTPUT does not move
  minutes, but POINTS form modestly does.
- **Minutes remain the larger uncertainty**, from `hazard.py`: a projection conditional on the
  player appearing barely decays over six weeks (0.94) while the unconditional one falls to 0.79.
  That measurement did not condition on future appearances, so it is not affected by the B2 error.

So both halves need work, and the ordering has changed. Scoring is NOT solved.

**The one methodological lesson worth more than any single rule:** three separate findings this
session were distorted by conditioning on the outcome — B2's future appearances, A3's 10-appearance
filter, and an earlier bias measurement that scored only players who actually played. Every one
biased towards "nothing to see here", because the cases that prove the effect are the cases that
drop out of the sample. **Before believing any of these rules, check what the test conditioned on.**

**Concrete work items, in order:**
1. DONE 2026-09-05 — half-life re-run, curve flat, leave HALF_LIFE at 20. See B3.
2. **Build the minutes model.** B4 says 38% of the realised edge is lost there and nothing in the
   scoring model can recover it. Start with red cards (A1), which are mechanical, unmissed by the
   current pipeline, and the cheapest correct fix available.
3. Put form back into the projection, measured RELATIVE to the player's own baseline (B2).
4. Re-test A3 on full squads rather than players with 10+ appearances.
