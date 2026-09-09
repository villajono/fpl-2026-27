# GW4 decisions — locked 2026-09-09, deadline Sat 12 Sep 13:30 UK

Both teams. Written after a session that priced the wildcard against transfers, withdrew one
defect and confirmed another. Overrides and the wildcard flag are in `data/state/human_input.json`.

## Village Idiots — PLAY THE WILDCARD

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

## Santa Claude — ONE TRANSFER, PURE MODEL

**Mateta → Barry (EVE £5.6m).** Free, +21.8 over six weeks, leaves £1.0m.

No human input, by design. The model spends its single free transfer on the slot that affects the
XI: Mateta is out to 11 October and Santa Claude has only two other forwards, while Sánchez —
dead all season on loan at Como — is a backup keeper who would never be fielded, so his cost is
tied-up cash rather than points. Sánchez is next week's transfer.

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
