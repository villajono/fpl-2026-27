#!/usr/bin/env python3
"""fetch_squads.py — pull the REAL squads, chips and scores for both teams from the FPL API.

WHY THIS EXISTS
Squads were hardcoded in weekly.py because Jon was travelling for GW1-2 and phone-editable
squads were not worth building. That reason expired when he got back, and by GW3 the cost was
visible: the engine was recommending a transfer Santa Claude had already made, and had no idea
Jon had played his Bench Boost. Chips in particular were never tracked at all — chips.json is
read by weekly.py but nothing has ever written it.

The FPL API gives all of it for free, given an entry id:

    /api/entry/{id}/                    name, overall points and rank, bank, squad value
    /api/entry/{id}/history/            chips played (name + gameweek) and per-GW points/rank
    /api/entry/{id}/event/{gw}/picks/   the 15 players, bench order, captain, that GW's bank

Entry ids come from the URL when you view a team: fantasy.premierleague.com/entry/<id>/event/2

    python fetch_squads.py 1234567 7654321        # Jon's id, Santa's id
    python fetch_squads.py --gw 2 1234567 7654321

Prints each squad as a paste-ready Python list for weekly.py, the chips mapping for the
`chips=` argument, and the real bank so `itb=` stops being a guess. Writes
data/state/entries.json so the ids only have to be typed once, and
data/state/team_scores.csv so the AI-vs-human benchmark finally has a record.
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://fantasy.premierleague.com/api/"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state"
ENTRIES = STATE / "entries.json"
SCORES = STATE / "team_scores.csv"
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# FPL's internal chip codes -> the codes weekly.py's chip_evaluation uses.
CHIP_CODE = {"bboost": "BB", "3xc": "TC", "freehit": "FH", "wildcard": "WC"}


def get(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def bootstrap():
    b = get("bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in b["teams"]}
    els = {e["id"]: dict(name=e["web_name"], pos=POSN[e["element_type"]],
                         team=teams[e["team"]], price=e["now_cost"] / 10.0,
                         code=e["code"]) for e in b["elements"]}
    finished = [e["id"] for e in b["events"] if e["finished"]]
    return els, finished


def half(gw: int) -> str:
    return "1" if gw <= 19 else "2"


def one_entry(eid: int, gw: int, els: dict) -> dict:
    info = get(f"entry/{eid}/")
    hist = get(f"entry/{eid}/history/")
    picks = get(f"entry/{eid}/event/{gw}/picks/")

    # chips -> {half: {CHIP: gameweek}}, the shape weekly.py's status() prints as "Used GWn"
    chips: dict[str, dict[str, int]] = {"1": {}, "2": {}}
    for c in hist.get("chips", []):
        code = CHIP_CODE.get(c["name"])
        if code:
            chips[half(c["event"])][code] = c["event"]

    squad = []
    for p in sorted(picks["picks"], key=lambda x: x["position"]):
        e = els[p["element"]]
        squad.append(dict(**e, order=p["position"], captain=p["is_captain"],
                          vice=p["is_vice_captain"]))

    eh = picks.get("entry_history", {})
    return dict(
        id=eid,
        name=info.get("name", "?"),
        manager=f"{info.get('player_first_name','')} {info.get('player_last_name','')}".strip(),
        points=info.get("summary_overall_points"),
        rank=info.get("summary_overall_rank"),
        bank=eh.get("bank", 0) / 10.0,
        value=eh.get("value", 0) / 10.0,
        transfers_this_gw=eh.get("event_transfers", 0),
        chips=chips,
        squad=squad,
        history=hist.get("current", []),
    )


def as_python_list(squad: list[dict]) -> str:
    """The exact literal weekly.py wants: (name, pos, team, price), starters then bench."""
    lines, buf = [], []
    for i, p in enumerate(squad):
        buf.append(f'("{p["name"]}","{p["pos"]}","{p["team"]}",{p["price"]:.1f})')
        # 3 per line keeps it readable and diffable, and breaks after the XI
        if len(buf) == 3 or i == 10 or i == len(squad) - 1:
            lines.append("             " + ",".join(buf) + ",")
            buf = []
    out = "\n".join(lines).rstrip(",")
    return out[13:] if out.startswith(" " * 13) else out


def show(t: dict, gw: int) -> None:
    print("=" * 78)
    print(f'{t["name"]}  (entry {t["id"]}, {t["manager"]})')
    print(f'  {t["points"]} pts · overall rank {t["rank"]:,}' if t["rank"] else f'  {t["points"]} pts')
    print(f'  squad value £{t["value"]:.1f}m · bank £{t["bank"]:.1f}m · '
          f'{t["transfers_this_gw"]} transfer(s) made for GW{gw}')
    played = {h: v for h, v in t["chips"].items() if v}
    print(f'  chips played: {played if played else "none"}')
    print()
    print("  per-gameweek:")
    for h in t["history"]:
        print(f'    GW{h["event"]:<3} {h["points"]:>4} pts   rank {h["rank"]:>9,}   '
              f'overall {h["overall_rank"]:>9,}   bench {h["points_on_bench"]:>3}')
    print()
    cap = next((p["name"] for p in t["squad"] if p["captain"]), "?")
    print(f'  captain GW{gw}: {cap}')
    print(f'  XI then bench (bench order {", ".join(p["name"] for p in t["squad"][11:])}):')
    print()
    print("    SQUAD = [" + as_python_list(t["squad"]) + "]")
    print()
    print(f'    itb={t["bank"]:.1f}, chips={json.dumps(played) if played else "{}"}')
    print()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gw = None
    if "--gw" in sys.argv:
        gw = int(sys.argv[sys.argv.index("--gw") + 1])
        args = [a for a in args if a != str(gw)]

    ids = [int(a) for a in args]
    if not ids and ENTRIES.exists():
        ids = json.load(open(ENTRIES))["ids"]
    if not ids:
        sys.exit("usage: python fetch_squads.py <entry_id> [<entry_id> ...]   "
                 "(find the id in the FPL url: /entry/<id>/event/2)")

    els, finished = bootstrap()
    if gw is None:
        if not finished:
            sys.exit("no finished gameweeks yet — picks are not public until a deadline passes")
        gw = finished[-1]
    print(f"reading GW{gw} picks (the last completed gameweek — picks for the upcoming "
          f"gameweek are not public until its deadline)\n")

    teams = [one_entry(i, gw, els) for i in ids]
    for t in teams:
        show(t, gw)

    STATE.mkdir(parents=True, exist_ok=True)
    json.dump({"ids": ids}, open(ENTRIES, "w"), indent=2)

    with open(SCORES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry", "team", "gw", "points", "gw_rank", "overall_rank", "bench_points"])
        for t in teams:
            for h in t["history"]:
                w.writerow([t["id"], t["name"], h["event"], h["points"], h["rank"],
                            h["overall_rank"], h["points_on_bench"]])
    print(f"wrote {ENTRIES.relative_to(ROOT)} and {SCORES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
