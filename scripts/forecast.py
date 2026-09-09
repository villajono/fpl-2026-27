#!/usr/bin/env python3
"""forecast.py — produce and LOCK a central estimate of points, per player per gameweek.

THE SEPARATION THIS ENFORCES

Two jobs were tangled together, and tangling them is why squad selection kept moving under its
own feet:

  FORECASTING   given history, form, underlying data, opponent strength and expected minutes,
                what will each player score in each of the next few gameweeks? This is genuinely
                uncertain, and more uncertain for players with less history. That uncertainty is
                recorded here, as a confidence band.

  OPTIMISATION  given those numbers, what is the best squad? This must be DETERMINISTIC. It
                treats the forecast as rock solid, and answers only "given these projections,
                here is what you go with."

So the forecast is written once, to a dated file, and then frozen. Every downstream tool reads
that file rather than recomputing, which means two runs of the optimiser on the same forecast
give the same squad — and when the answer does change, it changed because the FORECAST changed,
which is a thing you can inspect.

The confidence band is carried for the reader, and deliberately NOT used by the optimiser. A
player with 90 minutes of history and one with 3,000 both get a central estimate; the thin one's
is shrunk hard towards his position average by ev_v2._shrink_thin, which is where his uncertainty
is already expressed. Down-weighting him a second time in the objective would double-count it.

    python scripts/forecast.py                 # build and lock for the next gameweek
    python scripts/forecast.py --gw 4          # lock a specific starting gameweek
    python scripts/forecast.py --force         # overwrite an existing lock
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
AVAIL = RAW / "players_2026-27.csv"
STALE_HOURS = 12.0


def _refresh_availability():
    """Pull live injury flags BEFORE anything imports ev_v2. Returns a log line.

    WHY THIS RUNS FIRST, ABOVE THE IMPORTS

    ev_v2 reads players_2026-27.csv into `_nxt` at module import time, and `_availability()`
    reads the injury flags out of that frame. Refreshing the file after the import therefore
    changes nothing for the current process - the stale frame is already in memory. The refresh
    has to happen before `import weekly`, which is why this sits above it and why the import
    below is deliberately not at the top of the file.

    WHAT IT COST TO LEARN THIS

    On 2026-09-04 the GW3 forecast was locked at 16:53 against an availability file last written
    on 2026-09-02 at 15:12 - fifty hours stale. auto_ingest_and_refresh() ingests results and
    rewrites the form's players.json, and its docstring promises "never on stale data", but it
    never touched this CSV. Three players were projected to start who could not: Sanchez (on loan
    at Como), Richarlison (left out of the squad) and Wieffer (knee). All three carried a
    chance_of_playing of 0 in the live API at the time. The model had no way to see it.
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import refresh_players
        rc = refresh_players.main()
        return f"availability refreshed from the live API (rc={rc})"
    except Exception as e:                                   # never block a lock on a flaky API
        age = ((time.time() - os.path.getmtime(AVAIL)) / 3600.0
               if AVAIL.exists() else float("inf"))
        return (f"WARNING: availability refresh failed ({type(e).__name__}: {e}); "
                f"players_2026-27.csv is {age:.1f}h old")


def _assert_availability_fresh():
    """Refuse to lock a forecast against injury flags older than STALE_HOURS.

    A lock is a promise that the numbers were the best available at the moment it was taken. A
    lock built on two-day-old team news is not that, and because everything downstream reads the
    file rather than recomputing, the staleness propagates silently into the XI, the captain and
    the transfer call. Better to stop.
    """
    if not AVAIL.exists():
        raise SystemExit(f"  NO AVAILABILITY FILE at {AVAIL}. Run: python scripts/refresh_players.py")
    age = (time.time() - os.path.getmtime(AVAIL)) / 3600.0
    if age > STALE_HOURS:
        raise SystemExit(
            f"  STALE AVAILABILITY: {AVAIL.name} is {age:.1f} hours old (limit {STALE_HOURS:.0f}h).\n"
            f"  Injury flags and squad changes move daily; a forecast locked on these would carry\n"
            f"  players who are injured, sold or left out. Run: python scripts/refresh_players.py")
    return age


_REFRESH_LOG = _refresh_availability()      # must precede the weekly/ev_v2 import below

import weekly as W                          # noqa: E402  - see _refresh_availability

HORIZON = 6
# Anchored to the project root, not the working directory. A relative path here silently
# wrote scripts/data/processed/forecast_gw4.json when the script was run from scripts/,
# so the "locked" file and the one every downstream tool reads were different files.
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"


def path_for(gw):
    return OUT / f"forecast_gw{gw}.json"


def build(gw0):
    gws = [gw0 + o for o in range(HORIZON)]
    players = {}
    for c in W.POOL:
        code, name, pos, team = c["code"], c["name"], c["pos"], c["team"]
        ev = [W.ev_multi(code, name, pos, team, g) for g in gws]
        rates = W.V.get_per_90_rates(code, pos)
        # confidence: how much of the rate is his own data rather than the position prior.
        # ev_v2 records shrunk_to_prior when it pulls a thin sample in; 0 means untouched.
        conf = round(1.0 - float(rates.get("shrunk_to_prior", 0.0) or 0.0), 3)
        players[f"{name}|{team}"] = dict(
            code=code, pos=pos, team=team, price=c["price"],
            ev=[round(v, 4) for v in ev],
            p60=round(W.p_start(code, name), 3),
            minutes=int(rates.get("minutes") or 0),
            confidence=conf)
    return dict(
        generated=dt.datetime.now().isoformat(timespec="seconds"),
        gw0=gw0, horizon=HORIZON,
        decay={str(k): v for k, v in W.DECAY.items()},
        current_gw=W.CURRENT_GW,
        n_players=len(players),
        note=("Central estimates, locked. Downstream tools must read this file and must not "
              "recompute EV. Confidence is the share of each rate that is the player's own data "
              "rather than his position prior; it is information for the reader, not an input to "
              "the optimiser."),
        players=players)


def load(gw0):
    p = path_for(gw0)
    if not p.exists():
        raise FileNotFoundError(
            f"No locked forecast at {p}. Run: python scripts/forecast.py --gw {gw0}")
    return json.load(open(p, encoding="utf-8"))


def main():
    gw0 = W.CURRENT_GW + 1
    if "--gw" in sys.argv:
        gw0 = int(sys.argv[sys.argv.index("--gw") + 1])
    print("  " + _REFRESH_LOG)
    age = _assert_availability_fresh()
    print(f"  availability flags are {age:.1f}h old — within the {STALE_HOURS:.0f}h limit")
    for line in W.auto_ingest_and_refresh():
        print("  " + line)
    if W.POOL is None:
        W.build_pool()
    gw0 = gw0 if "--gw" in sys.argv else W.CURRENT_GW + 1

    p = path_for(gw0)
    if p.exists() and "--force" not in sys.argv:
        old = json.load(open(p, encoding="utf-8"))
        print(f"\n  Already locked: {p.name}, generated {old['generated']}, "
              f"{old['n_players']} players.")
        print("  Refusing to overwrite. A lock that silently moves is not a lock — pass --force")
        print("  if the underlying data has genuinely changed and you want a new one.")
        return

    fc = build(gw0)
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(fc, open(p, "w", encoding="utf-8"), indent=1)
    print(f"\n  LOCKED {p.name}: {fc['n_players']} players, GW{gw0}-{gw0 + HORIZON - 1}")

    thin = [(v["confidence"], k, v["minutes"]) for k, v in fc["players"].items()
            if v["confidence"] < 0.5]
    thin.sort()
    print(f"  {len(thin)} players are majority-prior (confidence < 0.5). The least-known who are"
          f" still expected to start:")
    shown = 0
    for conf, k, mins in sorted(thin, key=lambda x: -fc["players"][x[1]]["p60"]):
        if shown >= 6:
            break
        v = fc["players"][k]
        if v["p60"] < 0.5:
            continue
        print(f"    {k.split('|')[0][:20]:<21}{v['team']:<5}{v['pos']:<5}"
              f"p60 {v['p60']:.2f}  mins {mins:>4}  confidence {conf:.2f}")
        shown += 1
    print("\n  These are the picks most likely to be wrong in either direction. The optimiser")
    print("  will treat their numbers as certain, which is the point — but you should not.")


if __name__ == "__main__":
    main()
