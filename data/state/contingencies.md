# Squad contingencies — pre-GW1 (deadline Fri 21 Aug 2026)

Conditional moves that are NOT to be made now. Each fires only if its trigger happens.
Numbers are GW1-3 expected points (starting XI + captain + auto-subs), model V2 (all 5 audit
fixes applied), Maguire override P(start)=0.95.

---

## C1 — IF Enzo (CHE, MID, 7.0m) is sold by Chelsea

**Status as of 2026-07-31:** rumoured only, not done. Do nothing unless/until it actually happens.

**If it happens → replace Enzo with Foden (MCI, MID, 7.0m).** Straight price-for-price swap.

On confirming the move, **set Foden P(start) ≈ 0.92 via the phone form** (World Cup rest —
he didn't play, so he's fresh while City's returnees are leggy; the model's cold rate is 0.85 and
understates his early-season minutes).

### Why Foden, and why the alternatives were rejected

| Plan | GW1-3 | City assets | Verdict |
|---|--:|--:|---|
| Keep Enzo (if not sold) | 201.5 | 2 | Best — do nothing while he stays |
| **Enzo → Foden @ P(start) 0.92** | **201.6** | 3 | **The move.** Freshness override is what lifts it above par |
| Enzo → Foden @ model's cold 0.85 | 201.0 | 3 | Below par — the swap only works *with* the freshness read |
| Enzo → Schade (BRE, 6.0m), bank 1.0m | 200.9 | 2 | Rejected — see below |
| Enzo → Schade + Anderson→Cherki @0.60 | 200.7 | 2 | Rejected — Cherki not nailed |

- **Schade was only ever a route to bank 1.0m and spend it on Cherki.** The best home for that
  1.0m was Cherki (MCI, 7.5m). But Cherki is a real Pep-rotation risk — **manual P(start) = 0.60**
  (user's call, 2026-07-31), which craters his GW1-3 EV from 15.3 to 11.0 and makes the whole
  Schade→Cherki plan (200.7) *worse* than keeping Enzo. With Cherki gone there is no good home for
  the 1.0m, so Schade collapses to a plain downgrade. **Do not take Schade.**

### The one cost of Foden — accept it with eyes open
Foden takes City exposure to **3 starters (Foden + Anderson + Haaland)**. That's genuine
correlation risk: a flat City afternoon dents the XI three ways at once. Judged acceptable *only*
because City's opening run is the softest in the league — **Bournemouth (H), Palace (A),
Coventry (H)**. If City's GW1-3 fixtures were harder, prefer a non-City replacement instead.

---

### Standing manual P(start) overrides referenced above (set via phone form)
- Maguire (MUN): 0.95 — nailed (live in human_input.json)
- Cherki (MCI): 0.60 — rotation risk, keeps him off the "best upgrade" list
- Foden (MCI): set to ~0.92 **only if** C1 fires (freshness)
