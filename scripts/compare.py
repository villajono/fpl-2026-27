#!/usr/bin/env python3
"""compare.py — score whole squads against each other on one number.

Built for two jobs wc_build.py cannot do:

  1. Score a squad somebody else picked. A build is only as good as what you compare it to, and
     the most useful comparison is a strong human's team, not another run of the same optimiser.
  2. Test a specific swap you already have in mind, rather than letting the hill-climb roam.

Same objective as wc_build: each player collapses to his DECAY-weighted EV over the horizon, and
a squad scores as the WEIGHTS-weighted sum of all fifteen plus its captain. Every player counts
something — the fifth midfielder plays more often than not, and a bench player covering a one-week
absence saves a transfer worth up to 4 points.

    python scripts/compare.py                       # score every squad in SQUADS
    python scripts/compare.py --swap "Yates,B.Fernandes"   # best replacement pair for those two
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys
import unicodedata

import weekly as W

GW0, HORIZON, BUDGET = 4, 6, 100.0
XI_MIN = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
QUOTA = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}

# Squads to compare. Names are matched loosely, so accents and spacing do not matter.
# Paste a rival's fifteen in here as (name, club) and it scores alongside.
SQUADS = {
    # A strong human's GW4 wildcard draft, supplied by Jon 2026-09-04. Cherki swapped for Rogers,
    # which is the move the expert plans for GW4 and so the fair like-for-like.
    # Costs £100.3m at HIS prices — he has banked price rises Jon has not, so this is not a squad
    # Jon could necessarily buy today. Scored on players, priced separately below.
    # The same builder, two runs, two local optima. Kept side by side deliberately: the greedy
    # single-swap hill-climb cannot reach a two-premium-defender squad from a Haaland one, because
    # no SINGLE swap on the path improves. Which it lands on depends on the seed, not the objective.
    "build: with Haaland": [
        ("Verbruggen", "BHA"), ("Phillips", "HUL"),
        ("Thiaw", "NEW"), ("De Cuyper", "BHA"), ("van Ewijk", "COV"), ("Dedic", "NEW"),
        ("Konsa", "ARS"),
        ("B.Fernandes", "MUN"), ("Palmer", "CHE"), ("Tavernier", "BOU"), ("Rogers", "CHE"),
        ("George Hemmings", "AVL"),
        ("Haaland", "MCI"), ("Joao Pedro", "CHE"), ("Wissa", "NEW"),
    ],
    "build: no Haaland": [
        ("Kelleher", "BRE"), ("Phillips", "HUL"),
        ("Gabriel", "ARS"), ("Thiaw", "NEW"), ("van Ewijk", "COV"), ("Dedic", "NEW"),
        ("Konsa", "ARS"),
        ("B.Fernandes", "MUN"), ("Palmer", "CHE"), ("Saka", "ARS"), ("Rogers", "CHE"),
        ("George Hemmings", "AVL"),
        ("Joao Pedro", "CHE"), ("Thiago", "BRE"), ("Wissa", "NEW"),
    ],
    # Proved optimal for the locked GW4 forecast by scripts/squad_opt.py (MILP, HiGHS).
    "OPTIMAL (solved)": [
        ("Raya", "ARS"), ("Verbruggen", "BHA"),
        ("Gabriel", "ARS"), ("Lacroix", "CHE"), ("Thiaw", "NEW"), ("Botman", "NEW"),
        ("De Cuyper", "BHA"),
        ("B.Fernandes", "MUN"), ("Palmer", "CHE"), ("Mbeumo", "MUN"), ("Tavernier", "BOU"),
        ("Gomez", "BHA"),
        ("Joao Pedro", "CHE"), ("Wissa", "NEW"), ("Calvert-Lewin", "LEE"),
    ],
    "expert GW4": [
        ("Raya", "ARS"), ("McNally", "FUL"),
        ("Calafiori", "ARS"), ("Konsa", "ARS"), ("De Cuyper", "BHA"), ("O'Reilly", "MCI"),
        ("Hall", "NEW"),
        ("Gross", "BHA"), ("Palmer", "CHE"), ("Szoboszlai", "LIV"), ("Rogers", "CHE"),
        ("M.Sangare", "BRE"),
        ("Joao Pedro", "CHE"), ("Haaland", "MCI"), ("Wissa", "NEW"),
    ],
}


# Letters that are not accented forms and so survive NFKD untouched: Turkish dotless i, Polish
# crossed l, the Nordic vowels, the eths and thorns. Without these, "Kadioglu" never matches
# "F.Kadıoğlu" — the g and o decompose, the ı does not.
FOLD = str.maketrans({"ı": "i", "ł": "l", "ø": "o", "æ": "ae", "å": "a",
                      "ð": "d", "þ": "th", "ß": "ss", "đ": "d", "ħ": "h"})


def norm(s):
    d = unicodedata.normalize("NFKD", s.lower().translate(FOLD))
    return "".join(c for c in d if c.isalpha() and not unicodedata.combining(c))


def build_evs(pool):
    """Per-player EV for each gameweek in the horizon, NOT collapsed to one number.

    The vector has to survive, because the captain is chosen weekly. Collapsing first and taking
    a maximum afterwards computes max-of-sums, which credits a single player for all six weeks and
    silently throws away every week a different premium would have worn the armband.
    """
    cache = pathlib.Path(f"data/processed/evs_gw{GW0}.json")
    if cache.exists():
        return {tuple(k.split("|")): v
                for k, v in json.load(open(cache, encoding="utf-8")).items()}
    gws = [GW0 + o for o in range(HORIZON)]
    return {(c["name"], c["team"]): [
        W.ev_multi(c["code"], c["name"], c["pos"], c["team"], g) for g in gws] for c in pool}


def save_evs(evs):
    cache = pathlib.Path(f"data/processed/evs_gw{GW0}.json")
    cache.parent.mkdir(parents=True, exist_ok=True)
    json.dump({f"{k[0]}|{k[1]}": v for k, v in evs.items()}, open(cache, "w", encoding="utf-8"))


def discounted(vec):
    return sum(W.DECAY[i + 1] * v for i, v in enumerate(vec))


def build_val(evs):
    return {k: discounted(v) for k, v in evs.items()}


# Jon's weights, 2026-09-04. Rank within position, then weight by how much of a season that slot
# actually banks. Replaces a best-XI objective that scored every bench player at zero — wrong,
# because 3-5-2 and 3-4-3 are both common, so the fifth midfielder plays more often than not, and
# because a bench player who covers a one-week absence saves a transfer worth up to 4 points.
# Same error the NFL model made with RB4/RB5, corrected the same way and by the same person.
WEIGHTS = {
    "MID": [1.00, 1.00, 1.00, 0.90, 0.70],
    "DEF": [1.00, 1.00, 1.00, 0.70, 0.40],
    "FWD": [1.00, 1.00, 0.90],
    "GK":  [1.00, 0.25],
}


def squad_value(sq, evs):
    """Weighted value of all fifteen, plus the captain, whose points count twice.

    `evs` maps player -> per-gameweek EV vector. The captain term is the sum over weeks of the
    best player THAT WEEK — not the single best player over the whole horizon. The difference is
    real: a squad holding two premiums who peak in different weeks captains both, and the old
    max-of-sums version credited only one of them.
    """
    val = {k: discounted(v) for k, v in evs.items()}
    total = 0.0
    for pos, ws in WEIGHTS.items():
        vs = sorted((val.get((p["name"], p["team"]), 0.0) for p in sq if p["pos"] == pos),
                    reverse=True)
        total += sum(w * v for w, v in zip(ws, vs))
    cap = 0.0
    for i in range(HORIZON):
        wk = [evs.get((p["name"], p["team"]), [0.0] * HORIZON)[i] for p in sq]
        cap += W.DECAY[i + 1] * (max(wk) if wk else 0.0)
    return total + cap


def pick_xi(sq, val):
    """Best legal XI — still used to REPORT a lineup, never to score a squad."""
    by = {}
    for p in sq:
        by.setdefault(p["pos"], []).append(p)
    for v in by.values():
        v.sort(key=lambda p: -val.get((p["name"], p["team"]), 0.0))
    xi, used = [], {}
    for pos, n in XI_MIN.items():
        got = by.get(pos, [])[:n]
        if len(got) < n:
            return None, 0.0
        xi += got
        used[pos] = n
    rest = []
    for pos, ps in by.items():
        rest += ps[used.get(pos, 0):XI_MAX[pos]]
    rest.sort(key=lambda p: -val.get((p["name"], p["team"]), 0.0))
    xi += rest[:11 - len(xi)]
    vs = [val.get((p["name"], p["team"]), 0.0) for p in xi]
    return xi, sum(vs) + max(vs)


def resolve_all(names, pool, extra):
    out, missing = [], []
    keys = {(norm(k[0]), k[1]): v for k, v in pool.items()}
    keys.update({(norm(k[0]), k[1]): v for k, v in extra.items() if (norm(k[0]), k[1]) not in keys})
    for nm, tm in names:
        hit = keys.get((norm(nm), tm))
        if hit is None:
            missing.append(f"{nm} ({tm})")
        else:
            out.append(hit)
    return out, missing


def main():
    for _ in W.auto_ingest_and_refresh():
        pass
    if W.POOL is None:
        W.build_pool()
    pool = {(c["name"], c["team"]): c for c in W.POOL}
    evs = build_evs(W.POOL)
    save_evs(evs)
    val = build_val(evs)

    # players the pool dropped (no minutes) still need a price and a position to be scored;
    # they score 0, which is the honest treatment for someone the model cannot see
    extra = {}
    for r in W.nxt.itertuples():
        k = (r.web_name, r.team_name)
        if k not in pool and r.team_name in W.FIX:
            extra[k] = dict(code=int(r.code), name=r.web_name, pos=W.POSN[int(r.element_type)],
                            team=r.team_name, price=r.now_cost / 10)

    if "--swap" in sys.argv:
        who = [x.strip() for x in sys.argv[sys.argv.index("--swap") + 1].split(",")]
        base_names = SQUADS["wc_build GW4"]
        sq, miss = resolve_all(base_names, pool, extra)
        if miss:
            print("  cannot resolve: " + ", ".join(miss)); return
        outs = [p for p in sq if any(norm(p["name"]) == norm(w) for w in who)]
        if len(outs) != len(who):
            print(f"  matched {len(outs)} of {len(who)} names to swap out"); return
        keep = [p for p in sq if p not in outs]
        freed = sum(p["price"] for p in outs) + (BUDGET - sum(p["price"] for p in sq))
        pos_needed = sorted(p["pos"] for p in outs)
        base = squad_value(sq, evs)
        print(f"  removing {', '.join(p['name'] for p in outs)} frees £{freed:.1f}m")
        print(f"  current objective {base:.1f}\n")
        club = {}
        for p in keep:
            club[p["team"]] = club.get(p["team"], 0) + 1
        # Shortlist PER POSITION. A single global top-70 by value is all midfielders and forwards,
        # so a defender slot silently gets no candidates at all and the search returns nothing.
        heldk = {(p["name"], p["team"]) for p in keep}
        cands = []
        for pos in set(pos_needed):
            byp = sorted((c for c in W.POOL if c["pos"] == pos and
                          (c["name"], c["team"]) not in heldk),
                         key=lambda c: -val[(c["name"], c["team"])])
            # value-ranked alone misses every budget option, and a tight swap can only afford
            # budget options — so carry the cheapest as well
            cheap = sorted(byp, key=lambda c: c["price"])[:25]
            seen = {(c["name"], c["team"]) for c in byp[:45]}
            cands += byp[:45] + [c for c in cheap if (c["name"], c["team"]) not in seen]
        best = []
        for a, b in itertools.combinations(cands, 2):
            if sorted([a["pos"], b["pos"]]) != pos_needed:
                continue
            if a["price"] + b["price"] > freed + 1e-9:
                continue
            cl = dict(club)
            ok = True
            for c in (a, b):
                cl[c["team"]] = cl.get(c["team"], 0) + 1
                if cl[c["team"]] > 3:
                    ok = False
            if not ok:
                continue
            v = squad_value(keep + [a, b], evs)
            best.append((v, a, b))
        best.sort(key=lambda x: -x[0])
        print(f"  {'pair':<34}{'£':>7}{'objective':>11}{'vs now':>9}")
        for v, a, b in best[:10]:
            pair = f"{a['name']} + {b['name']}"
            print(f"  {pair[:33]:<34}{a['price'] + b['price']:>7.1f}{v:>11.1f}{v - base:>+9.1f}")
        return

    print(f"  {'squad':<18}{'£':>7}{'objective':>11}   XI")
    for label, names in SQUADS.items():
        sq, miss = resolve_all(names, pool, extra)
        if miss:
            print(f"  {label:<18}  cannot resolve: {', '.join(miss)}")
            continue
        xi, _ = pick_xi(sq, val)
        v = squad_value(sq, evs)
        cost = sum(p["price"] for p in sq)
        print(f"  {label:<18}{cost:>7.1f}{v:>11.1f}   "
              + ", ".join(p["name"] for p in xi))


if __name__ == "__main__":
    main()
