# GW4 decisions — locked 2026-09-09, deadline Sat 12 Sep 13:30 UK

Both teams. Written after a session that priced the wildcard against transfers, withdrew one
defect and confirmed another. Overrides and the wildcard flag are in `data/state/human_input.json`.

## Village Idiots - ACTIONED 2026-09-10: THREE TRANSFERS, WILDCARD HELD

**The wildcard section below was superseded.** Jon chose transfers, keeping the chip, on the
football view that Chelsea are worth loading up on now. Executed:

    OUT  Gabriel (ARS 8.0)   Semenyo (MCI 8.4)   Hinshelwood (BHA 6.0)
    IN   Konsa (ARS 4.4)     Palmer (CHE 9.6)    Rogers (CHE 7.6)

    GW4 XI (3-4-3): Verbruggen; Calafiori, Konsa, F.Kadioglu; Palmer, Rogers, Mbeumo, Schade;
                    Joao Pedro, Haaland, Calvert-Lewin.
    CAPTAIN Palmer, vice Joao Pedro.  Bench: Ajer, Shaw, Tzolis (GK Kinsky).
    About GBP0.1-0.2m left - sell prices are private, so the app is the authority.

Arsenal and Chelsea are both at the three-club limit. Chips remaining: WILDCARD and FREE HIT.

**What this costs against the model, stated plainly because it was a deliberate choice.** The
optimiser's own three transfers were Hinshelwood, Shaw and Tzolis out for Damsgaard, Tavernier and
Thiaw, scoring 343.8 against this package's 325.9 over six weeks - a gap of 17.6, essentially all
of it selling Gabriel. And strategy.py valued the wildcard at +17.6 over transferring normally,
which is now foregone for this gameweek.

Jon's counter-argument, tested: Chelsea's attack is under-rated and their fixtures turn. The
fixtures do turn for GW4 specifically (Hull at home, attacking multiplier 1.705, by far the best
in the run) but not across it - GW5, GW7, GW8 and GW9 are ordinary to hard, and Spurs at home in
GW8 is the second-best defence in the league. On the attack, fixture-adjusted xG has Chelsea 3rd
at 1.99 per game against the 2.10 the model already implies from the highest attack rating in the
league. So the model is not under-rating them; it declines to rate them above best.

The one finding that did come out of testing it: **Manchester City are the most over-rated attack
in the model** - implied 1.82, delivering 0.83 fixture-adjusted, a gap of -0.99 and the largest
either direction. Village Idiots holds Haaland at GBP15.5m through that. Three games is thin and
City are the last side to write off on it, but it is the largest single position in either squad
and worth watching from GW8, when the team ratings start to weight this season properly.

## The superseded wildcard recommendation for Village Idiots

```
GK   Verbruggen  BHA  4.5     Kinsky      TOT  4.5
DEF  Calafiori   ARS  5.7     Thiaw       NEW  5.0     Gvardiol   MCI  5.6
     Van Hecke   TOT  4.9     Konsa       ARS  4.4                    £25.6m
MID  Palmer      CHE  9.6     Rogers      CHE  7.6     Ødegaard   ARS  6.6
     Anderson    MCI  6.3     Tavernier   BOU  6.0                    £36.1m
FWD  Haaland     MCI 15.5     João Pedro  CHE  7.7     Calvert-Lewin LEE 6.0
                                              (Wissa NEW 6.2 is within 0.1 — free choice)
                                                       £99.9m, objective 348.0
```

At the club limit for Arsenal, Chelsea and Man City. No further assets available at any of them.

### Why the chip rather than transfers

Three free transfers were banked (rolled GW1, GW2, GW3). Jon's plan was four moves —
Gabriel/Semenyo/Hinshelwood/Shaw out, Konsa/Rogers/Palmer/Thiaw in — spread over two weeks.
Decayed XI-plus-captain points over GW4-9:

    do nothing                           292.0
    the four transfers over two weeks    306.0
    a professional manager's WC squad    306.9
    wildcard                             327.7  (unconstrained solve)

The transfer plan fixes FOUR slots; the wildcard fixes SIX, clearing Kadıoğlu (ev6 12.17) and
Tzolis (ev6 8.48, p60 0.42) which no three-transfer package can reach. It also keeps the free
transfers rather than spending four of them.

Robustness: forcing Haaland back into the unconstrained WC squad costs 1.0, so the gain is not an
artefact of the model dropping him.

### What Jon's constraints cost, and they were all cheap

    unconstrained solve                                    360.6
    nine players forced (his convictions)                  345.5   -15.1
    + minutes corrections for Konsa and Wissa              349.0
    + max one Newcastle defender, no £6m+ defender         348.0    -1.1

- **Gabriel out is structural, not a price call.** Konsa + Calafiori + Ødegaard fills Arsenal, so
  he cannot be held alongside them. He is also the most expensive defender in the game at £8.0m,
  £1.5m clear of the next — only 7 of 214 defenders cost £6.0m or more, so £6m is the top 3% of
  the position and £8m is an outlier. Jon's "he's great but £8m" was right.
- **One Newcastle defender, not two.** Newcastle have conceded 1.33 per game and the model gives
  them 2.00 expected clean sheets over GW4-9 against a 1.44 base rate for a mid-table defence
  (measured over 1,905 six-game windows). Concentrating two defenders there was the wrong risk.
  Gvardiol takes the slot. Cost: 0.8.
- **No £6m+ defender.** Dropping Guéhi (£6.0m, 4.54 pts/£m) for Botman/Gvardiol trades almost no
  points for real capital. Guéhi's MINUTES were fine — 270 of 270 — so the objection was price,
  and it was the right one.
- **Ødegaard over Saka, tested three ways and it holds.** Saka is +7.0 ev6 for +£2.9m but the
  funding downgrades cost more: 3.52 pts/£m against Ødegaard's 4.02. Still true after correcting
  the minutes, and still true when the mid-price block is discounted up to 30%.

### The comparison against a professional's squad

Scored on the same basis: pro 299.7 as the model sees it, 306.9 with minutes corrected; ours
315.1 and 315.9. The instructive number is not the gap but its movement — correcting p60 added
**+7.2 to their squad and +0.8 to ours**, because theirs was built on three players the model
cannot price: Muharemović and Slater at 90/90/90 minutes rated p60 0.62, Wissa at 0.79.

That is a direct measurement of the minutes defect, in points, against a human who has the team
news. But only ONE of the three survives correction into our squad: Muharemović corrects to ~21.4
(below Van Hecke's 24.91 at the same money) and Slater to ~16.2 (below Gomez's 24.73). They are
enablers funding a third premium, and on our numbers spreading the money beats that structure.
Wissa is the genuinely borrowable pick.

Their squad also costs £100.3m against a £99.9m budget — not buildable as listed.

## Santa Claude - PLAY THE WILDCARD (reversed 2026-09-10)

**This section reversed the day after it was written.** The original recommendation was one
transfer, Mateta -> Barry, on the argument that only two slots were broken and two weeks of free
transfers would fix both. That argument was never tested against numbers and does not survive
them. Recorded in full because the reasoning failure is more instructive than the answer.

**Why the original argument was wrong.** Mateta is a BENCH player, so replacing him barely touches
the XI - the best single transfer is worth **+2.8** over six weeks. Fixing the two dead slots was
never the issue; the squad underneath them is mediocre. Holding scores 305.7 against 327.7 for a
rebuild. This is the "no cover value" blind spot from the defect list, committed by the model's
operator rather than the model.

### The wildcard survives both stress tests

| test | chip premium before | after |
|---|---|---|
| 196-player minutes correction (63 raised, 133 lowered) | +19.2 | **+21.5** |
| 30% discount on GBP 5.0-7.5m outfielders | +27.1 | **+51.3** |

The second test corrected a mistake running through the whole session. "The model over-rates
mid-price players" was asserted repeatedly, never measured, and used to discount wildcards. For a
squad already stuffed with that band - De Cuyper, Gomez, Schade, Calvert-Lewin, Senesi, Gvardiol,
Szoboszlai, Mateta - the hunch is an argument FOR a wildcard, not against: discounting the band
damages what you hold more than what you would buy, because only a wildcard can restructure away
from it. The sign was backwards.

### Timing: GW4 beats GW7 and GW10, tested properly

A 13-week forecast (GW4-16, `data/processed/_forecast_long_gw4_16.json`) compares wildcarding at
GW4, GW7 and GW10 against a control that never wildcards, with **every path making one free
transfer a week**.

    WC at GW4    +17.2 over never wildcarding      <- play it now
    WC at GW10   +12.0
    WC at GW7     +9.4

GW4 wins under a deliberate handicap: pre-wildcard transfers were allowed to apply from GW4 in the
waiting scenarios, which flatters GW7 and GW10. GW10 coming second matches the earlier backtest
work that identified GW10; GW7 being worst rather than in between is probably noise.

**THE FIRST TWO ATTEMPTS AT THIS TEST WERE BOTH WRONG, IN OPPOSITE DIRECTIONS.** Worth recording
as a class of error:

1. The +19.2 and +21.5 chip-premium figures compared a wildcard against a squad making ONE
   transfer in six weeks. Santa Claude gets one every week. The alternative was under-resourced,
   so the chip was overstated.
2. The first timing run then froze the wildcard squad for thirteen weeks after the rebuild while
   the control kept transferring. By GW16 the control had thirteen transfers and the wildcarded
   team none. That produced a meaningless +6.3 with no decay structure at all.

Both were caught because Jon supplied a prior - a generic wildcard is worth about 20 points,
shaped 8/5/3 then 1 a week - and asked whether the model reproduced its SHAPE, not just its total.
The corrected run gives **+19.8 undecayed against that ~20**, front-loaded at +5.2 and tailing to
zero by GW16 as free transfers let the field converge. A model that produces the right total by
the wrong mechanism is not validated; checking the shape is what found the bug.

`NEXT_SESSION.md` says the model cannot answer wildcard timing and not to try. That was right
about the old approach. This method - two concrete squads on identical projections, both paths
using their transfers - reproduces an independent human prior to within 1% and should replace the
prohibition.

### ACTIONED 2026-09-10. Wildcard played, this squad is live.

    GK   Suzuki       AVL   5.0        Tzolakis      HUL   4.6
    DEF  Gabriel      ARS   8.0        Calafiori     ARS   5.7
         Thiaw        NEW   5.0        De Cuyper     BHA   4.8
         Thomas (Bobby, COV)     4.0
    MID  B.Fernandes  MUN  12.0        Saka          ARS   9.5
         Palmer       CHE   9.6        Tavernier     BOU   6.0
         Anderson     MCI   6.3
    FWD  Joao Pedro   CHE   7.7        Calvert-Lewin LEE   6.0
         Awoniyi      COV   5.5
                                            GBP99.7m, GBP0.20m bank

    GW4 XI: Suzuki; Gabriel, Calafiori, De Cuyper; Palmer, B.Fernandes, Saka, Tavernier,
            Anderson; Joao Pedro, Calvert-Lewin.   CAPTAIN Palmer, vice Joao Pedro.
    Bench: Awoniyi, Thiaw, Thomas (GK Tzolakis).

PALMER WAS FORCED IN AGAINST THE OPTIMISER, and the reason is a defect worth fixing. Left to
itself the solver sold Palmer - a player Santa Claude already OWNED - immediately before Hull at
home, the best attacking fixture any Chelsea player gets in the run (multiplier 1.705, his 6.89 is
the highest single-week EV in either squad). It preferred Saka on a 13-week decayed number by
2.87, while over six weeks the two are a dead heat at 33.26 against 33.48. Forcing Palmer costs
2.0 over thirteen weeks and gains 0.84 in GW4.

Jon spotted it: "you're transferring out Palmer ahead of Hull (h)?"

The defect is that strategy.py picks the post-wildcard squad to maximise the WHOLE remaining
horizon as a block, so a player who is best NOW loses to one who is better on average. On a
wildcard that is backwards - you keep your free transfers either way, so the right play is to take
the near-term squad and transfer into the long-term one. Weighting the rebuild towards the first
two or three gameweeks would fix it. Until then, sanity-check the rebuild against the immediate
fixture list before playing the chip.

Chips remaining: BENCH BOOST and FREE HIT, both deliberately held. The model valued them at +14.5
and +3.7 inside a GW4-16 horizon that contains no blanks or doubles; those cluster in the second
half, so an unplayed chip is being held rather than wasted, and the model cannot see that.

### The squad as first solved (superseded by the above)

    GK   Raya          ARS  6.0      Verbruggen    BHA  4.5
    DEF  Gabriel       ARS  8.0      Calafiori     ARS  5.7    Lacroix  CHE 6.0
         Thiaw         NEW  5.0      Van Hecke     TOT  4.9
    MID  B.Fernandes   MUN 12.0      Palmer        CHE  9.6    Mbeumo   MUN 7.9
         Tavernier     BOU  6.0      Gomez         BHA  5.0
    FWD  Joao Pedro    CHE  7.7      Calvert-Lewin LEE  6.0    Barry    EVE 5.6
                                                   GBP 99.9m, GBP 0.0m bank

**No Haaland, and the captaincy barely suffers.** Bruno Fernandes takes the armband in four of six
weeks; six-week captain value is 32.9 against 33.2 for always captaining Haaland - a difference of
**0.3 points**. Bruno at 12.0 is flatter (5.46-6.94) than Haaland at 15.5 (5.40-7.83), and the
trade banks GBP 3.5m. Two caveats: 0.3 is far inside the model's error, so this is a coin flip
that lands on Bruno rather than a preference; and it assumes perfect captain foresight.
Captaining Bruno blindly every week scores 30.5, which Haaland-every-week beats. The squad's case
rests on what the GBP 3.5m buys, not on the armband.

**Overrides and purity.** With the live Konsa/Wissa overrides active the best single transfer is
Mateta -> Wissa; pure model it is Mateta -> Barry. Moot now the answer is a wildcard, but the
overrides in `human_input.json` are global and do reach Santa Claude, which sits awkwardly with
"entirely model-driven". The squad above is the pure-model version.

**Both teams wildcarding in GW4 makes them converge** - they would share Palmer, Joao Pedro,
Calafiori, Thiaw, Tavernier and Verbruggen. If the point of running two teams is to compare a
human-steered squad against a model-driven one, simultaneous wildcards weaken that test.

## Overrides written, and why

`human_input.json` carries two, both derived from minutes rather than football knowledge, so
both are worth a human check before the deadline:

- **Konsa 0.92 start / 88 mins.** 0, 11, 90 across GW1-3 with status=a. The model reads 1-of-3
  starts and blends to p60 0.57. This is the recency defect, not rotation.
- **Wissa 0.95 / 88.** 90, 81, 90. The model carries 0.79 from last season's share.

## Still unverified at the time of writing

- **Tavernier (£6.0m) and Anderson (£6.3m)** are £12.3m of midfield in a profile the model
  over-rates, and Anderson was overridden to p60 0.49 in GW3 against the model's current 0.97.
  Confirm from team news.
- Selling prices are purchase-plus-half-the-rise and are private to the manager; every figure here
  uses live `now_cost`. Irrelevant on a wildcard, but it mattered to the transfer plan.

## What this session settled about the model

1. **Premium compression does not exist** — the test was wrong. See the commit and the withdrawal
   note in `model_tests.py`. Do not fix the model for it.
2. **Minutes recency is the live defect and it changed a recommendation this week.** Konsa at 0.57
   against a true ~0.90 is the case; 42 players carry the same signature.
3. **Three gameweeks of defensive results carry ~12% predictive weight** (slope 0.116 over 58
   team-seasons; xG conceded correlates better but does not raise the weight). The model applies
   12-20%, so it is right for now. By GW8 the weight rises to 40-58% — revisit then.
