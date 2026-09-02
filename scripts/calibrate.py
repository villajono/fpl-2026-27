#!/usr/bin/env python3
"""calibrate.py — tune the model's free constants against 2025-26, walk-forward.

WHY NOT SQUAD POINTS
backtest.py simulates one squad and reports what it scored. That is the right end-to-end check
and the wrong tuning signal: a season is 38 draws from a noisy process and a single captain pick
can swing it by 20. Tuning to it fits the noise.

This measures the thing the constants actually control — how well predicted EV tracks the points a
player then scores. Every player-gameweek is a data point, so a sweep sees tens of thousands of
observations instead of one season total.

    predicted:  ev(element, cut = gw-1, that gw's fixture)     model sees only GW < gw
    actual:     total_points in gw

Reported per setting:
    MAE          mean absolute error, in points. Lower is better.
    Spearman     rank correlation — does it order players correctly? This is what matters for
                 transfers and captaincy, where only the ordering is acted on.
    top-1 hit    of the highest-EV player each gameweek, what did he actually score? A direct
                 read on captaincy.

    python calibrate.py                 # sweep xG/xA half-life
    python calibrate.py --from 8        # start later, more history before the first prediction

CAVEATS, inherited from backtest.py and worth repeating: one season, and V2 was partly calibrated
on it, so this is not out-of-sample. Treat a difference of less than ~2% as noise.
"""
from __future__ import annotations

import sys

import numpy as np

import backtest as B
import history as H


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    ra = ra - ra.mean(); rb = rb - rb.mean()
    d = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / d) if d else 0.0


def evaluate(S, gw_from, gw_to, min_minutes=0):
    """Walk forward, collecting (predicted EV, actual points) for every player with a fixture.

    min_minutes=0 on purpose. Filtering to players who actually featured scores the model on a
    sample selected using the outcome: EV already contains P(he does not play), so conditioning on
    him having played guarantees an apparent under-prediction. Measured that way the model looked
    0.60 points low per observation; that was the filter talking, not the model."""
    pred, act, top_hits = [], [], []
    for gw in range(gw_from, gw_to + 1):
        cut = gw - 1
        rows = []
        for el, m in S.meta.items():
            fx = S.fixtures(m["short"], gw)
            if not fx:
                continue
            a = S.actual(el, gw)
            if a is None:
                continue
            mins = S.actual(el, gw, "minutes") or 0
            if mins < min_minutes:
                continue
            e = sum(B.ev(S, el, cut, o, h) for o, h in fx)
            rows.append((e, a))
        if not rows:
            continue
        pred += [r[0] for r in rows]; act += [r[1] for r in rows]
        top_hits.append(max(rows, key=lambda r: r[0])[1])       # what the model's top pick scored
    p, a = np.array(pred), np.array(act)
    return dict(n=len(p), mae=float(np.abs(p - a).mean()), rho=spearman(p, a),
                top1=float(np.mean(top_hits)) if top_hits else 0.0)


def sweep(S, gw_from, gw_to, values):
    print(f"  {'half-life':>10}{'eff.games':>11}{'n':>9}{'MAE':>8}{'Spearman':>10}{'top-1':>8}")
    print("  " + "-" * 56)
    best = None
    for hl in values:
        H.HALF_LIFE["xG"] = hl; H.HALF_LIFE["xA"] = hl
        S._rate_cache.clear(); S._min_cache.clear(); S._posavg_cache.clear(); S._pool_cache.clear()
        r = evaluate(S, gw_from, gw_to)
        eff = 1 / (1 - 0.5 ** (1 / hl))
        mark = ""
        if best is None or r["rho"] > best[1]["rho"]:
            best = (hl, r); mark = "  <- best rank correlation"
        print(f"  {hl:>10}{eff:>11.1f}{r['n']:>9}{r['mae']:>8.3f}{r['rho']:>10.4f}{r['top1']:>8.2f}{mark}")
    return best


def main():
    gw_from = int(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 6
    gw_to = int(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else 38
    S = B.Season()
    print(f"walk-forward GW{gw_from}-{gw_to}, 2025-26. Each setting re-predicts every "
          f"player-gameweek from GW<t only.\n")
    print("xG / xA HALF_LIFE")
    best = sweep(S, gw_from, gw_to, [4, 6, 8, 12, 16, 20, 25, 30, 40])
    H.HALF_LIFE["xG"] = 20; H.HALF_LIFE["xA"] = 20
    print(f"\n  best rank correlation at half-life {best[0]} "
          f"(rho {best[1]['rho']:.4f}, MAE {best[1]['mae']:.3f})")
    print("  production is currently 20 — see notes/NEXT_SESSION.md item 1")

    # ---- does the bonus term earn its place? ----
    print("\nBONUS TERM (A/B, half-life held at 20)")
    print(f"  {'setting':>10}{'n':>12}{'MAE':>8}{'Spearman':>10}{'top-1':>8}")
    print("  " + "-" * 50)
    res = {}
    for flag in (False, True):
        B.USE_BONUS = flag
        S._rate_cache.clear(); S._min_cache.clear(); S._posavg_cache.clear(); S._pool_cache.clear()
        r = evaluate(S, gw_from, gw_to); res[flag] = r
        print(f"  {('with' if flag else 'without'):>10}{r['n']:>12}{r['mae']:>8.3f}"
              f"{r['rho']:>10.4f}{r['top1']:>8.2f}")
    print(f"\n  bonus changes Spearman {res[True]['rho'] - res[False]['rho']:+.4f}, "
          f"MAE {res[True]['mae'] - res[False]['mae']:+.3f}, "
          f"top-1 {res[True]['top1'] - res[False]['top1']:+.2f}")
    print("  Keep it only if the ranking improves AND the error does not worsen materially;")
    print("  a term that flatters one and not the other is fitting noise.")
    B.USE_BONUS = True


if __name__ == "__main__":
    main()
