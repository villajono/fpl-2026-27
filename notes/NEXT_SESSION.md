# Brief — model corrections outstanding

Written 2026-09-01 after a session that fixed nine things and left four known-wrong.
For Jon and whoever picks this up next.

## Where we got to

Both squads are now pulled from the live API (`scripts/fetch_squads.py`, entry ids in
`data/state/entries.json`), chips are tracked per team, and overrides can express minutes
properly. Nine fixes are in and pushed — see `git log` from `4ab2738` to `6edf0b8`, each
message explains one.

**GW3 calls already settled, do not reopen:** Village Idiots Tzolis → Anderson;
Santa Claude Sarr → Anderson. **Captain Haaland on both**, overriding Santa's engine, which
still says Gvardiol — see item 2 for why that is wrong.

## What is still wrong

Ranked by how much it distorts decisions.

### 1. Calibration is guessed, not measured — do this first

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
every fixture multiplier in the model. Same disease as item 1, one layer up.

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
