#!/usr/bin/env python3
"""euro_fixtures.py — European club fixtures for Premier League sides.

WHY THIS EXISTS

The minutes model is trained entirely on Premier League gameweeks, so it is structurally blind to
the single most common cause of a surprise benching at a big club: a European tie either side of
the league game. Nothing in the FPL API records that Aston Villa play Club Brugge on the Tuesday.

GW3, 2026-09-06: Pau Torres started GW1 and GW2, carried FPL status "a" with no injury flag, was
projected 3.67, and played no minutes. Villa played Club Brugge in the Champions League two days
later. No amount of Premier League history predicts that, because the decision was made about a
fixture the model has no record of.

THE DIRECTION MATTERS, AND IT IS THE LESS OBVIOUS ONE

The instinct is to model fatigue - a player is tired AFTER a midweek European game. Jon's read on
the Pau case is the opposite and is the one that fits: he was rested AHEAD of Brugge, protected
rather than recovered. So this carries both distances and lets the measurement decide which one
does the work:

    days_to_next_euro    PL match -> next European tie   (protection ahead of it)
    days_since_last_euro previous European tie -> PL match (recovery after it)

DELIBERATELY NOT APPLIED YET

This produces the FEATURE only. It does not adjust anybody's p60, and nothing downstream reads it
until the effect has been measured on real data rather than assumed. Hand-setting a rotation
multiplier because the story is persuasive is exactly the failure mode the project keeps hitting.
The measurement needs European fixture history joined to the 83,835 player-gameweeks already in
data/raw/history, and that is a separate job.

SOURCE AND ITS LIMIT

TheSportsDB free tier (no key). The per-team "next events" endpoint carries a short horizon - it
returned exactly one fixture for Villa - so this sees the next European tie reliably and further
ones patchily. Good enough for a one-gameweek decision, not for planning six weeks out. Re-run it
weekly rather than trusting a stored file.

    python scripts/euro_fixtures.py            # refresh and print what is coming
    python scripts/euro_fixtures.py --show     # print the stored file without refetching
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time

import requests

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = RAW / "euro_fixtures.json"
BASE = "https://www.thesportsdb.com/api/v1/json/3"
FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"

# TheSportsDB spells a few clubs differently from the FPL API. Only the differences.
ALIAS = {
    "Man City": "Manchester City", "Man Utd": "Manchester United",
    "Spurs": "Tottenham Hotspur", "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United", "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers", "Brighton": "Brighton and Hove Albion",
    "Sheffield Utd": "Sheffield United", "Leeds": "Leeds United",
    "Leicester": "Leicester City", "Ipswich": "Ipswich Town",
    "Norwich": "Norwich City", "Hull": "Hull City", "Coventry": "Coventry City",
    "Stoke": "Stoke City", "Luton": "Luton Town", "Cardiff": "Cardiff City",
    "Swansea": "Swansea City", "Birmingham": "Birmingham City",
}

# A European tie is any competition run by UEFA. Matching on the governing body rather than on a
# list of competition names means a rebrand or a new competition does not silently drop out.
EURO_MARK = "uefa"


IDS = RAW / "euro_team_ids.json"


def _get(url, tries=4, **params):
    """One call, with backoff. The free tier throttles hard and returns an empty body rather
    than a 429, so a bare failure looks exactly like "club does not exist" — which is how a
    first run silently decided Liverpool and Manchester City were not in the database."""
    delay = 1.0
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params or None, timeout=30)
            if r.status_code == 200:
                body = r.json() or {}
                if any(body.get(k) for k in ("teams", "events", "results")):
                    return body
                if attempt == tries - 1:
                    return body                      # genuinely empty, not throttled
            time.sleep(delay)
            delay *= 2
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return {}


def _load_ids():
    if IDS.exists():
        try:
            return json.load(open(IDS, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_ids(cache):
    json.dump(cache, open(IDS, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def pl_clubs():
    """[(fpl_short, fpl_name)] for this season's twenty, from the FPL API itself.

    Read live rather than hardcoded: three clubs change every summer, and a stale list would
    quietly drop a promoted side out of the European check.
    """
    boot = _get(FPL_BOOTSTRAP)
    return [(t["short_name"], t["name"]) for t in boot["teams"]]


def resolve_team_id(name, cache):
    if name in cache:
        return cache[name]
    q = ALIAS.get(name, name)
    try:
        res = _get(f"{BASE}/searchteams.php", t=q)
        teams = res.get("teams") or []
        # prefer an English top-flight match; the search is fuzzy and returns namesakes abroad
        best = next((t for t in teams if "English" in (t.get("strLeague") or "")), None)
        tid = (best or (teams[0] if teams else {})).get("idTeam")
    except Exception:
        tid = None
    cache[name] = tid
    return tid


def euro_events(tid):
    """Upcoming and recent UEFA fixtures for one club."""
    out = []
    for endpoint, tag in (("eventsnext.php", "next"), ("eventslast.php", "last")):
        try:
            res = _get(f"{BASE}/{endpoint}", id=tid)
        except Exception:
            continue
        for e in (res.get("events") or res.get("results") or []):
            league = (e.get("strLeague") or "")
            if EURO_MARK not in league.lower():
                continue
            out.append(dict(date=e.get("dateEvent"), time=(e.get("strTime") or "")[:5],
                            comp=league, home=e.get("strHomeTeam"), away=e.get("strAwayTeam"),
                            when=tag))
    return sorted(out, key=lambda x: x["date"] or "")


def refresh():
    """Top up the stored file. A run that resolves fewer clubs than last time must NEVER
    replace the better file with the worse one.

    This is not hypothetical. Because the free tier returns an empty body when it throttles
    rather than an error, a heavily-throttled run looks like a complete run in which most clubs
    happen to have no European fixtures. Two overlapping runs on 2026-09-07 took the file from
    ten resolved clubs to five, and the second result was indistinguishable from the truth. So:
    resolve only what is missing, and merge rather than overwrite.
    """
    clubs = pl_clubs()
    cache = _load_ids()
    prev = (load().get("clubs") if OUT.exists() else {}) or {}
    data = dict(prev)
    have = [s for s, c in prev.items() if c.get("team_id")]
    todo = [(s, n) for s, n in clubs if s not in have or "--full" in sys.argv]
    print(f"  {len(have)} of {len(clubs)} clubs already on file; fetching {len(todo)}")

    missing = []
    for short, name in todo:
        tid = resolve_team_id(name, cache)
        if not tid:
            missing.append(short)
            data.setdefault(short, dict(name=name, team_id=None, fixtures=[]))
            continue
        fx = euro_events(tid)
        data[short] = dict(name=name, team_id=tid, fixtures=fx)
        print(f"    {short:<5}{len(fx)} European fixture(s)")
        time.sleep(1.1)                       # free tier throttles well below one call/second
    _save_ids({k: v for k, v in cache.items() if v})
    if missing:
        print(f"  still unresolved ({len(missing)}): {', '.join(missing)}")
        print("  rerun to top up — resolved clubs are kept, nothing is lost")
    blob = dict(generated=dt.datetime.now().isoformat(timespec="seconds"),
                source="thesportsdb free tier, per-team next/last events",
                note=("Feature only. Nothing adjusts p60 from this until the effect is measured. "
                      "Horizon is short — refresh weekly rather than trusting a stored file."),
                clubs=data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(blob, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return blob


def load():
    if not OUT.exists():
        raise FileNotFoundError(f"No {OUT.name}. Run: python scripts/euro_fixtures.py")
    return json.load(open(OUT, encoding="utf-8"))


def congestion(short, pl_date, blob=None):
    """Both distances, in days, between a club's PL match and its European ties.

    days_to_next_euro     >0  a European tie is coming this many days after the league game.
                              Small values are the PROTECTION case - Pau ahead of Brugge.
    days_since_last_euro  >0  the club played in Europe this many days before the league game.
                              Small values are the RECOVERY case.

    Either may be None when nothing is scheduled inside the source's horizon. None means "not
    known", never "no European game" — treat it as missing data, not as a zero.
    """
    blob = blob or load()
    c = (blob.get("clubs") or {}).get(short)
    if not c or not c.get("fixtures"):
        return dict(days_to_next_euro=None, days_since_last_euro=None, next_fixture=None)
    d0 = dt.date.fromisoformat(str(pl_date)[:10])
    after, before = [], []
    for f in c["fixtures"]:
        if not f.get("date"):
            continue
        d = dt.date.fromisoformat(f["date"])
        (after if d >= d0 else before).append((abs((d - d0).days), f))
    nxt = min(after, default=None, key=lambda x: x[0])
    prv = min(before, default=None, key=lambda x: x[0])
    return dict(days_to_next_euro=(nxt[0] if nxt else None),
                days_since_last_euro=(prv[0] if prv else None),
                next_fixture=(f"{nxt[1]['home']} v {nxt[1]['away']} ({nxt[1]['comp']})"
                              if nxt else None))


def main():
    blob = load() if "--show" in sys.argv else refresh()
    rows = []
    for short, c in blob["clubs"].items():
        for f in c["fixtures"]:
            if f["when"] == "next":
                rows.append((f["date"], f["time"], short, f["comp"], f["home"], f["away"]))
    rows.sort()
    print(f"\n  UPCOMING EUROPEAN TIES — {len(rows)} involving Premier League clubs")
    if not rows:
        print("    none inside the source's horizon")
    for date, tm, short, comp, h, a in rows:
        print(f"    {date} {tm:<6}{short:<5}{comp[:26]:<28}{h} v {a}")
    n_euro = sum(1 for c in blob["clubs"].values() if c["fixtures"])
    print(f"\n  {n_euro} of {len(blob['clubs'])} clubs have a European fixture on file")
    print(f"  written to {OUT}")
    print("\n  NOT YET APPLIED — this is a feature, not an adjustment. Measure the effect on"
          "\n  historical minutes before letting it move anyone's p60.")


if __name__ == "__main__":
    main()
