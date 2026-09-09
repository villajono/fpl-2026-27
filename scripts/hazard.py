#!/usr/bin/env python3
"""hazard.py — how fast does a projection go stale?

THE QUESTION
`weekly.py` sums a transfer's projected gain over six gameweeks and weights every week the same:
a point it expects in GW+6 counts as much as one in GW+1. That cannot be right — injuries,
suspensions, form and rotation all accumulate between now and then — but the alternative in the
codebase is no better, a guessed table sitting unused in three files:

    DECAY = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.40, 6: 0.25}

Nobody measured that. This does, walk-forward over 2025-26.

THE METHOD
At each cut c (having seen GW<=c and nothing after), project every plausible squad player for
GW c+k, then compare with what he actually scored. Regress actual on projected:

    actual = a + b * projected

b is what matters. It is not accuracy — it is how much of a projected EDGE gets realised. If two
players are projected 2 points apart and b = 0.5, they finish 1 point apart on average. That is
exactly the quantity a transfer decision needs, because a transfer is a bet on a projected
difference, not on an absolute.

    DECAY[k] = b_k / b_1

so the near week is 1.0 by construction and the rest are measured relative to it.

THE DECOMPOSITION
A projection can go stale two ways, and they have different fixes:

  AVAILABILITY  he stops playing — injury, suspension, benching. The projection was fine; the
                player is gone. Measured by rerunning on players who did play 60+ minutes.
  RATE          he plays but scores at a different rate than projected — form, role, tactics.
                Whatever decay survives the 60+ filter is this.

If the decay is mostly availability, the fix is a minutes model, not a smaller horizon.

    python scripts/hazard.py             # full walk-forward, a few minutes
    python scripts/hazard.py --quick     # every third cut, for a fast look
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import backtest as B
from backtest import RAW

HORIZON = 6
MIN_MINS_HISTORY = 270      # 3 full games, so the projection is based on something
FIRST_CUT = 6               # team ratings need a few weeks before they mean anything
LAST_GW = 38


def _slope(x, y):
    """OLS slope of y on x, plus the correlation. Slope is the decision-relevant one."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 30 or x.std() < 1e-9:
        return float("nan"), float("nan"), len(x)
    b = np.cov(x, y, bias=True)[0, 1] / x.var()
    r = np.corrcoef(x, y)[0, 1]
    return float(b), float(r), len(x)


def collect(season, quick=False):
    cuts = list(range(FIRST_CUT, LAST_GW - HORIZON + 1))
    if quick:
        cuts = cuts[::3]
    rows = []
    for ci, cut in enumerate(cuts):
        # the pool a manager could actually pick from at this point: enough history to project
        pool = []
        for el, a in season.by_el.items():
            past = a["gw"] <= cut
            if a["minutes"][past].sum() >= MIN_MINS_HISTORY:
                pool.append(el)
        for k in range(1, HORIZON + 1):
            gw = cut + k
            for el in pool:
                if not season.fixtures(season.meta[el]["short"], gw):
                    continue                      # blank gameweek: no bet to make
                yhat = B.ev_multi(season, el, cut, gw)
                y = season.actual(el, gw)
                mins = season.actual(el, gw, "minutes")
                rows.append((cut, k, el, yhat, 0.0 if y is None else y,
                             0.0 if mins is None else mins))
        print(f"  cut {cut:>2}  ({ci+1}/{len(cuts)})", end="\r", flush=True)
    print(" " * 40, end="\r")
    return pd.DataFrame(rows, columns=["cut", "k", "el", "proj", "actual", "mins"])


def table(df, label):
    print(f"\n{label}")
    print(f"  {'k':>2}{'n':>8}{'mean proj':>11}{'mean actual':>13}{'slope b':>10}"
          f"{'corr':>8}{'DECAY':>8}")
    out = {}
    b1 = None
    for k in range(1, HORIZON + 1):
        d = df[df.k == k]
        b, r, n = _slope(d.proj, d.actual)
        if k == 1:
            b1 = b
        dec = b / b1 if (b1 and b1 > 0) else float("nan")
        out[k] = dec
        print(f"  {k:>2}{n:>8}{d.proj.mean():>11.2f}{d.actual.mean():>13.2f}"
              f"{b:>10.3f}{r:>8.3f}{dec:>8.2f}")
    return out


def main():
    quick = "--quick" in sys.argv
    print("loading 2025-26...")
    season = B.Season()
    print(f"walk-forward projections, cuts {FIRST_CUT}-{LAST_GW - HORIZON}"
          f"{' (every 3rd)' if quick else ''}, lookahead 1-{HORIZON}")
    cache = RAW.parent / "processed" / ("hazard_quick.csv" if quick else "hazard_full.csv")
    if cache.exists() and "--refresh" not in sys.argv:
        df = pd.read_csv(cache)
        print(f"reusing {cache.name} — pass --refresh to recompute")
    else:
        df = collect(season, quick)
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    print(f"{len(df):,} player-gameweek projections")

    all_dec = table(df, "ALL players with a fixture  (availability + rate decay together)")
    played = df[df.mins >= 60]
    play_dec = table(played, "ONLY those who played 60+  (rate decay alone)")

    # The two series cannot be subtracted. Conditioning on 60+ minutes removes the biggest source
    # of spread in the projection — whether he plays at all — so the played-only slope sits on a
    # much lower base and the difference between the two ratios means nothing. What IS readable is
    # whether each series trends with lookahead.
    print("")
    print("DECOMPOSITION — is it availability, or is it rate?")
    ks = np.arange(1, HORIZON + 1, dtype=float)
    for label, dec in (("all players", all_dec), ("played 60+", play_dec)):
        v = np.array([dec[k] for k in ks])
        trend = np.polyfit(ks, v, 1)[0]
        print(f"  {label:<13} trend {trend:+.3f} per extra week of lookahead"
              f"   ({v[0]:.2f} at k=1 to {v[-1]:.2f} at k={HORIZON})")
    print("  If the all-players line falls while played-60+ stays flat, then what decays is")
    print("  knowing WHETHER he plays — not knowing how well he plays when he does.")
    print("")
    print("\nvs the guess currently sitting in the code")
    print(f"  {'k':>2}{'guessed':>10}{'measured':>11}{'difference':>13}")
    for k in range(1, HORIZON + 1):
        g = B.DECAY[k]
        print(f"  {k:>2}{g:>10.2f}{all_dec[k]:>11.2f}{all_dec[k] - g:>+13.2f}")

    print("\n  proportion of a projected edge still realised at each lookahead:")
    print("  " + "  ".join(f"GW+{k} {all_dec[k]:.0%}" for k in range(1, HORIZON + 1)))
    print("\n  CAVEAT: one season, and ev_v2 was partly calibrated on it, so these slopes")
    print("  flatter the model. The SHAPE across k is the finding, not the level.")


if __name__ == "__main__":
    main()


# ===================================================================== WILDCARD TIMING
# Second half of the same question. The decay above says how fast a projection goes stale; this
# says what that costs on the one decision where timing is the whole decision.
#
# The method is a hindsight sweep. Hold a squad from W0, and for each candidate wildcard week w:
#
#     total(w) = actual points held from W0 to w-1  +  actual points of the REBUILT squad w..19
#
# The rebuild is chosen with information available at w-1 only — no hindsight in the squad, just
# in the question of which w we are asking about. So total(w) is what you WOULD have scored had
# you wildcarded in week w and then sat still. Its argmax is the best week, after the fact.
#
# Then the honest test: does the model's own wc_gain, computed at w-1, point at that week?

W0, HALF_END = 4, 19


def wildcard_timing(season):
    """When should the wildcard fire? Measured against a squad that is MAINTAINED, not frozen.

    The first version of this held the GW4 squad untouched to GW19 in both arms. That makes every
    rebuild look enormous and, worse, removes the only real reason to wait: a squad you maintain
    with free transfers fixes its own problems a player at a time, so the wildcard's value is its
    advantage OVER doing that, and that advantage grows as changes pile up. A benchmark without
    free transfers cannot see the mechanism the timing rule is supposed to exploit — and a constant
    fitted to it would be fitted to the wrong thing.

    So both arms now run backtest.simulate(), which makes weekly transfers on the live graduated
    threshold, takes hits under the live rule, and executes the wildcard at `planned_wc` without
    consuming a free transfer.

        arm A   maintain with free transfers, wildcard in week w
        arm B   maintain with free transfers, never wildcard

    The production rule is then tested against the squad as it ACTUALLY stood each week under
    arm B, rather than against a straw squad nobody would have held.
    """
    squad, spent, _ = B.build_start_squad(season)
    itb0 = round(100.0 - spent, 1)

    base_log = B.simulate(season, squad, W0, HALF_END, planned_wc=None)
    never = sum(r["squad_pts"] for r in base_log)
    by_gw = {r["gw"]: r for r in base_log}

    rows = []
    for w in range(W0, HALF_END + 1):
        log = B.simulate(season, squad, W0, HALF_END, planned_wc=w)
        total = sum(r["squad_pts"] for r in log)
        # the live rule, judged on the maintained squad it would really have seen that week
        st = by_gw.get(w)
        fires = False
        if st is not None:
            try:
                fires = B.wc_fires(season, st["squad"], st["itb"], w - 1, w, used=False)[0]
            except Exception:
                fires = False
        rows.append(dict(w=w, total=total, fires=fires))
        print(f"  simulating GW{w} ({w - W0 + 1}/{HALF_END - W0 + 1})", end="\r", flush=True)
    print(" " * 46, end="\r")

    best = max(rows, key=lambda r: r["total"])
    print("")
    print(f"WILDCARD TIMING — both arms maintained with free transfers, GW{W0} to GW{HALF_END}")
    print(f"  {'week':>5}{'rule fires':>12}{'total pts':>12}{'vs never':>10}")
    first_fire = next((r for r in rows if r["fires"]), None)
    for r in rows:
        tag = ""
        if r is best:
            tag += "   <- best in hindsight"
        if first_fire is not None and r is first_fire:
            tag += "   <- the live rule fires HERE"
        print(f"  {r['w']:>5}{('yes' if r['fires'] else '-'):>12}{r['total']:>12.0f}"
              f"{r['total'] - never:>+10.0f}{tag}")
    print(f"  {'never':>5}{'-':>12}{never:>12.0f}{0:>+10.0f}")

    print("")
    span = best["total"] - min(r["total"] for r in rows)
    print(f"  Best week is worth {best['total'] - never:+.0f} against never playing the chip,")
    print(f"  and the spread between the best and worst week to play it is {span:.0f} pts.")
    if first_fire:
        print(f"  The live rule fires GW{first_fire['w']} ({first_fire['total']:.0f}), "
              f"costing {best['total'] - first_fire['total']:.0f} pts against GW{best['w']}.")
    else:
        print("  The live rule never fires across the half.")
    print("")
    print("  CAVEAT: one season and one starting squad, so treat the argmax as indicative. What is")
    print("  now sound is the SHAPE — both arms maintain the squad, so the comparison between weeks")
    print("  reflects the decision a manager actually faces.")


if "--wildcard" in sys.argv or "--all" in sys.argv:
    wildcard_timing(B.Season())
