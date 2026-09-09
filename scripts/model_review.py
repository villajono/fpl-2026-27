#!/usr/bin/env python3
"""model_review.py — two weekly stages that were missing.

The weekly run already REFRESHED the model with new data. It never asked whether the model is
getting better, or whether its inputs still describe reality. Those are different questions, and
without them a systematic error survives indefinitely — it did: the model has been compressing
elite players towards the average all season, which is why the optimiser kept dropping Haaland
for a cheaper midfielder, and nobody noticed because nothing was looking.

    STAGE 1  RE-CALIBRATION   what moved in the inputs this week, and by how much. A rate or a
                              team rating that jumps is either real news or a bug, and either way
                              somebody should see it the week it happens rather than in April.

    STAGE 2  MODEL IMPROVEMENT   standing checks against KNOWN failure modes. Not a refresh —
                              an audit. Each check states what good looks like, so a regression
                              is visible rather than needing to be remembered.

Neither stage changes any number. They report, so a human decides. That is deliberate: an
auto-tuning loop on two gameweeks of data would chase noise, which is the mistake that produced
the guessed constants these checks exist to catch.

    python scripts/model_review.py
    (weekly.py calls report_lines() so both stages print in the weekly report)
"""
from __future__ import annotations

import pandas as pd

RAW = "data/raw/merged_gw_2025-26.csv"

# Elite compression check. Shrinking a thin sample towards the position average is right; doing it
# to a player with 2,900 minutes is not, and it costs most exactly where it matters — the premium
# players you captain. Pairs are (elite, mid-tier, what their xG90 ratio SHOULD be from history).
COMPRESSION_PAIRS = [("Haaland", "MCI", "Mbeumo", "MUN")]
COMPRESSION_TOL = 0.80          # model ratio must be at least this share of the historical one


def _hist_xg90(names):
    g = pd.read_csv(RAW, low_memory=False)
    for c in ("minutes", "expected_goals"):
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    s = g.groupby("name").agg(mins=("minutes", "sum"), xg=("expected_goals", "sum"))
    s = s[s.mins >= 900]
    out = {}
    for n in names:
        m = s[s.index.str.contains(n, case=False, na=False)]
        if len(m):
            r = m.iloc[0]
            out[n] = r.xg / r.mins * 90
    return out


def report_lines(W, V):
    L = ["\nSTAGE 1 — RE-CALIBRATION (what moved in the inputs)\n" + "━" * 30]
    moved = getattr(W, "INGEST_LOG", None) or []
    if moved:
        for m in list(moved)[:4]:
            L.append("  " + str(m))
    else:
        L.append("  Inputs refreshed from the live API; no unusual movement flagged.")
    L.append("  Team ratings and per-90 rates are re-weighted every run — see MODEL UPDATES above")
    L.append("  for the clubs that moved and the prior/data split behind each.")

    L.append("\nSTAGE 2 — MODEL IMPROVEMENT (standing audit)\n" + "━" * 30)

    # --- check 1: are elite players compressed towards the average? ---
    try:
        if W.POOL is None:
            W.build_pool()
        pool = {(c["name"], c["team"]): c for c in W.POOL}
        hist = _hist_xg90([p[0] for p in COMPRESSION_PAIRS] + [p[2] for p in COMPRESSION_PAIRS])
        for elite, et, mid, mt in COMPRESSION_PAIRS:
            a, b = pool.get((elite, et)), pool.get((mid, mt))
            if not (a and b and elite in hist and mid in hist):
                continue
            ra = V.get_per_90_rates(a["code"], a["pos"])["xG90"]
            rb = V.get_per_90_rates(b["code"], b["pos"])["xG90"]
            if rb <= 0 or hist[mid] <= 0:
                continue
            model_ratio, true_ratio = ra / rb, hist[elite] / hist[mid]
            share = model_ratio / true_ratio
            ok = share >= COMPRESSION_TOL
            L.append(f"  elite compression {elite} vs {mid}: model ratio {model_ratio:.2f}, "
                     f"history {true_ratio:.2f}")
            L.append(f"    the model keeps {share:.0%} of the real gap"
                     f"{'  OK' if ok else '  ** FAIL — premiums are undervalued **'}")
            if not ok:
                L.append("    Effect: the optimiser prefers cheaper mid-tier players and drops the")
                L.append("    premium you would captain. HALF_LIFE in history.py is the lever and is")
                L.append("    still marked PROVISIONAL — it was set by argument, never measured.")
    except Exception as e:
        L.append(f"  elite compression check unavailable: {e}")

    # --- check 2: positional bias, from the locked-forecast record ---
    try:
        import calibration
        rows = calibration.measure()
        if not rows:
            L.append("  positional bias: no completed gameweek with a locked forecast yet.")
        else:
            by = {}
            for r in rows:
                by.setdefault(r["pos"], []).append(r["actual"] - r["pred"])
            sp = [sum(v) / len(v) for v in by.values()]
            L.append(f"  positional bias spread {max(sp) - min(sp):.2f} pts across "
                     f"{len(by)} positions — see FORECAST ACCURACY below")
    except Exception as e:
        L.append(f"  positional bias check unavailable: {e}")

    L.append("  Neither stage changes a number. Auto-tuning on two gameweeks would chase noise,")
    L.append("  which is how the guessed constants these checks exist to catch got there.")
    return L


if __name__ == "__main__":
    import ev_v2 as V
    import weekly as W
    for _ in W.auto_ingest_and_refresh():
        pass
    for line in report_lines(W, V):
        print(line)
