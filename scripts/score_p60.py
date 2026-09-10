#!/usr/bin/env python3
"""score_p60.py — score locked p60 predictions against what actually happened.

WHY THIS EXISTS

Six changes were made to the minutes model on 2026-09-10 - recency weighting on in-season
starts, a jointly refitted prior weight, a position/streak prior for players without a prior
season, expiry of stale pre-season overrides, within-club normalisation for goalkeepers, and a
position lookup that stopped going through last season's data. Every one was justified by a
measurement on 2022-25 history. None has yet been tested against a gameweek it did not see.

Two locked forecasts for GW4 exist, one from either side of that work:

    forecast_gw4_locked_2026-09-04.json    before   491 players
    forecast_gw4_locked_2026-09-10.json    after    476 players

Both were written BEFORE GW4 was played, so scoring them against the result is genuinely out of
sample - which is the only kind of evidence that settles whether the changes helped. A model that
improves on the history it was fitted to has proved nothing.

WHAT IT REPORTS

  Brier and log loss over every player in the pool, so a confident wrong answer is punished more
  than a hedged one. Calibration by predicted band, because a model can score well on average
  while being systematically over- or under-confident. And a breakdown by the population each fix
  was aimed at, since the headline can easily be carried by players none of them touched:

    GK              the within-club normalisation
    thin prior      the streak table, gated to players without a prior season
    established     the recency weighting, which is all that reaches them

    python scripts/score_p60.py --gw 4
    python scripts/score_p60.py --gw 4 --locks a.json,b.json
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

API = "https://fantasy.premierleague.com/api"
ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
DEFAULT = ["forecast_gw4_locked_2026-09-04.json", "forecast_gw4_locked_2026-09-10.json"]


def _arg(flag, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def actuals(gw):
    """{web_name|TEAM: 1 if he played 60+ minutes in that gameweek else 0}."""
    live = json.load(urllib.request.urlopen(API + "/event/%d/live/" % gw))
    boot = json.load(urllib.request.urlopen(API + "/bootstrap-static/"))
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_id = {e["id"]: e for e in boot["elements"]}
    out, mins = {}, {}
    for row in live["elements"]:
        e = by_id.get(row["id"])
        if not e:
            continue
        m = row["stats"]["minutes"]
        k = e["web_name"] + "|" + short[e["team"]]
        out[k] = 1 if m >= 60 else 0
        mins[k] = m
    return out, mins


def score(pred, truth):
    """Brier and log loss over the players present in both."""
    n = brier = ll = 0
    for k, p in pred.items():
        if k not in truth:
            continue
        y = truth[k]
        p = min(max(p, 0.01), 0.99)
        brier += (p - y) ** 2
        ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        n += 1
    return (brier / n, ll / n, n) if n else (float("nan"), float("nan"), 0)


def bands(pred, truth):
    edges = [(0.0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
    rows = []
    for lo, hi in edges:
        ks = [k for k, p in pred.items() if lo <= p < hi and k in truth]
        if not ks:
            continue
        rows.append((lo, hi, len(ks),
                     sum(pred[k] for k in ks) / len(ks),
                     sum(truth[k] for k in ks) / len(ks)))
    return rows


def main():
    gw = _arg("--gw", 4, int)
    names = _arg("--locks", ",".join(DEFAULT)).split(",")
    truth, mins = actuals(gw)
    played = sum(truth.values())
    print("\n  GW%d actuals: %d players, %d started 60+ minutes" % (gw, len(truth), played))
    if played == 0:
        print("  Nobody has 60+ minutes yet - the gameweek has not been played. Nothing to score.")
        return 1

    loaded = []
    for nm in names:
        p = PROC / nm.strip()
        if not p.exists():
            print("  missing: %s" % nm)
            continue
        fc = json.load(open(p, encoding="utf-8"))
        pred = {k: v["p60"] for k, v in fc["players"].items()}
        pos = {k: v["pos"] for k, v in fc["players"].items()}
        conf = {k: v.get("confidence", 1.0) for k, v in fc["players"].items()}
        loaded.append((nm.strip(), fc.get("generated", "?"), pred, pos, conf))

    print("\n  OVERALL")
    print("  %-38s %8s %9s %7s" % ("lock", "Brier", "logloss", "n"))
    base = None
    for nm, gen, pred, _, _ in loaded:
        b, l, n = score(pred, truth)
        tag = ""
        if base is None:
            base = (b, l)
        else:
            tag = "   Brier %+.4f  logloss %+.4f" % (b - base[0], l - base[1])
        print("  %-38s %8.4f %9.4f %7d%s" % (nm[:38], b, l, n, tag))

    for nm, gen, pred, pos, conf in loaded:
        print("\n  %s  (generated %s)" % (nm, gen))
        print("    calibration:  %-12s %6s %10s %10s" % ("band", "n", "predicted", "actual"))
        for lo, hi, n, mp, ma in bands(pred, truth):
            flag = "  <-- over" if mp - ma > 0.10 else ("  <-- under" if ma - mp > 0.10 else "")
            print("                  %.1f-%.1f       %6d %10.3f %10.3f%s" % (lo, hi, n, mp, ma, flag))
        groups = {
            "GK (keeper rule)":      [k for k in pred if pos.get(k) == "GK"],
            "thin prior (streak)":   [k for k in pred if conf.get(k, 1.0) < 0.5],
            "established (recency)": [k for k in pred if conf.get(k, 1.0) >= 0.5
                                      and pos.get(k) != "GK"],
        }
        print("    by population targeted:")
        for lab, ks in groups.items():
            sub = {k: pred[k] for k in ks}
            b, l, n = score(sub, truth)
            if n:
                print("      %-24s Brier %.4f  logloss %.4f  n=%d" % (lab, b, l, n))

    if len(loaded) >= 2:
        an, _, ap, apos, _ = loaded[0]
        bn, _, bp, _, _ = loaded[-1]
        moved = sorted(((abs(bp[k] - ap[k]), k) for k in bp if k in ap and k in truth),
                       reverse=True)[:12]
        print("\n  BIGGEST PREDICTION CHANGES, and who was right")
        print("    %-22s %6s %6s %7s   %s" % ("player", "before", "after", "actual", "verdict"))
        for _, k in moved:
            y = truth[k]
            better = "after" if abs(bp[k] - y) < abs(ap[k] - y) else "before"
            print("    %-22s %6.2f %6.2f %7d   %s  (%d mins)"
                  % (k[:22], ap[k], bp[k], y, better, mins.get(k, 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
