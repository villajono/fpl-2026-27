#!/usr/bin/env python3
"""transfer_opt.py — the best N transfers from the squad you actually hold.

THE GAP THIS FILLS

squad_opt.py answers the WILDCARD question: given £100m and no squad, what is optimal? And
weekly.best_transfer answers the ONE-TRANSFER question by trying every single swap. Nothing
answered the question actually faced most weeks: I hold this squad and have N free transfers —
what is the best use of them?

That gap is not cosmetic, because the two-or-three-transfer answer is not reachable by repeating
the one-transfer answer. Selling a premium defender to fund two midfield upgrades is worse after
the first move and better after the third, so a greedy search rejects it at step one and never
sees the package. The same reasoning retired the hill-climb from the wildcard refit; this applies
it to the weekly decision.

BUDGET. The constraint is the squad's SELLING value plus the bank, not £100m. Selling prices are
purchase-plus-half-the-rise and are private to a manager, so this uses live now_cost as a proxy
and states the assumption. Where a player has risen since you bought him the real budget is
slightly lower, so treat a package that clears by less than ~£0.3m as needing a check in the app.

    python scripts/transfer_opt.py --entry 1169767 --transfers 3
    python scripts/transfer_opt.py --entry 1169767 --transfers 3 --force-in "Palmer|CHE"
    python scripts/transfer_opt.py --entry 1169767 --transfers 1 --pool 60
"""
from __future__ import annotations

import json
import sys
import urllib.request

import compare as C
import forecast as F
import squad_opt as SO

API = "https://fantasy.premierleague.com/api"


def _arg(flag, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def live_squad(entry, gw):
    """The 15 you hold, as forecast keys 'Name|TEAM', plus the bank."""
    boot = json.load(urllib.request.urlopen(f"{API}/bootstrap-static/"))
    el = {e["id"]: e for e in boot["elements"]}
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    picks = json.load(urllib.request.urlopen(f"{API}/entry/{entry}/event/{gw}/picks/"))
    POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    keys, spend, meta = [], 0, {}
    for p in picks["picks"]:
        e = el[p["element"]]
        k = f"{e['web_name']}|{short[e['team']]}"
        keys.append(k)
        spend += e["now_cost"] / 10.0
        meta[k] = dict(pos=POS[e["element_type"]], team=short[e["team"]],
                       price=e["now_cost"] / 10.0)
    return keys, picks["entry_history"]["bank"] / 10.0, spend, meta


def main():
    entry = _arg("--entry", 1169767, int)
    n = _arg("--transfers", 1, int)
    pool = _arg("--pool", SO.POOL_PER_POS, int)
    forced = [x.strip() for x in _arg("--force-in", "").split(",") if x.strip()]
    # --ban "Emersonn|IPS" bans players; "NEW:DEF" bans a club's whole position group. For human
    # judgement the model cannot see yet, e.g. a defence conceding far more than its rating says.
    bans = [x.strip() for x in _arg("--ban", "").split(",") if x.strip()]

    fc = F.load(_arg("--gw", None, int) or SO._next_gw())
    players = fc["players"]
    decay = [fc["decay"][str(i + 1)] for i in range(fc["horizon"])]

    held, bank, spend, meta = live_squad(entry, fc["current_gw"])
    budget = spend + bank

    # A held player the forecast dropped (injured, on loan) is still IN YOUR SQUAD. If he is
    # simply absent from `players` the solver cannot represent keeping him and is forced to sell,
    # which silently spends a transfer you did not have to spend, and makes holding an injured
    # bench player look impossible rather than merely worthless. Inject him at EV 0 instead, so
    # selling him is a choice the objective has to justify.
    missing = [k for k in held if k not in players]
    for k in missing:
        players[k] = dict(pos=meta[k]["pos"], team=meta[k]["team"], price=meta[k]["price"],
                          ev=[0.0] * fc["horizon"], p60=0.0, minutes=0, confidence=0.0)
    print(f"\n  ENTRY {entry} — GW{fc['gw0']}, {n} transfer(s)")
    print(f"  squad now_cost £{spend:.1f}m + bank £{bank:.1f}m = budget £{budget:.1f}m")
    if missing:
        print(f"  not in the forecast (unavailable, EV 0): {', '.join(missing)}")

    def value(keys):
        return sum(sum(decay[i] * e for i, e in enumerate(players[k]["ev"]))
                   for k in keys if k in players)

    banned = set()
    for b in bans:
        if ":" in b:
            club, pos = b.split(":", 1)
            banned |= {k for k, v in players.items() if v["team"] == club and v["pos"] == pos and k not in held}
        elif b in players and b not in held:
            banned.add(b)
    if banned:
        print(f"  banned: {len(banned)} player(s) ({', '.join(bans)})")
    chosen, obj, binding = SO.solve(players, decay, fc["horizon"], budget=budget,
                                    forced=forced, pool_per_pos=pool, banned=tuple(banned),
                                    keep=held, max_changes=n)

    out = [k for k in held if k not in set(chosen)]
    inn = [k for k in chosen if k not in set(held)]
    print(f"\n  OUT: {', '.join(out) if out else '(none — holding is optimal)'}")
    print(f"  IN : {', '.join(inn) if inn else '(none)'}")
    for a in out:
        print(f"     - {a:24s} £{players[a]['price']:4.1f}  6wk {value([a]):6.2f}")
    for a in inn:
        print(f"     + {a:24s} £{players[a]['price']:4.1f}  6wk {value([a]):6.2f}")
    spend_new = sum(players[k]["price"] for k in chosen)
    print(f"\n  new squad £{spend_new:.1f}m, £{budget - spend_new:.1f}m left")
    print(f"  squad objective (weighted, captain-aware): {obj:.1f}")
    if binding:
        print(f"  !! pool binds at {binding} — re-run with a larger --pool")


if __name__ == "__main__":
    main()
