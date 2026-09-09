#!/usr/bin/env python3
"""wc_build.py — build a wildcard squad around players you insist on.

Differs from weekly.py::_wc_refit in three ways that matter for a wildcard.

  1. It scores all fifteen by SLOT WEIGHT (compare.WEIGHTS), so a bench player is worth what he
     actually banks — not zero, and not full price either. _wc_refit pays full price for everyone.
  2. It takes FORCED picks, so a manager's own read goes in whatever the model thinks. The proxy
     machinery below is now a fallback rather than the norm: build_pool() used to drop every
     thin-rate player, which made summer signings invisible, and that filter has been removed.
  3. It TANKS the two slots that genuinely earn least — the reserve keeper (25%) and the fifth
     defender (40%) — because with Bench Boost gone those are the only places a pound is close
     to wasted. The fifth MIDFIELDER is not one of them: he is weighted 70%.

Objective: discounted by the measured DECAY from scripts/hazard.py, so a GW+6 point is worth about
79% of a GW+1 one. A squad scores as the WEIGHTS-weighted sum of all fifteen, plus a captain term
that is the sum over weeks of the best player IN THAT WEEK. Keeping the per-gameweek vector matters:
an earlier version collapsed each player to one number first and took a maximum afterwards, which
computes max-of-sums, credits a single player for the whole horizon, and discards every week a
different premium would have captained. It was enough to push Haaland out of the squad entirely.

    python scripts/wc_build.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import unicodedata

import compare as C
import weekly as W

GW0, HORIZON, BUDGET = 4, 6, 100.0
QUOTA = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
TOP_N = 30          # candidates per position; beyond this nothing is competitive

FORCED = [("Dedic", "NEW"), ("Konsa", "ARS"), ("Wissa", "NEW"),
          ("Joao Pedro", "CHE"), ("Palmer", "CHE"), ("Rogers", "CHE")]

# A forced player the model cannot price borrows a club-mate's EV, scaled by an assumed starting
# probability. A read, not a measurement, and printed as one.
# Botman, not Burn: Burn has 2,195 minutes but does not survive build_pool()'s filters, and a
# proxy that is not in the pool fails silently and scores the player zero.
PROXY = {("Dedic", "NEW"): (("Botman", "NEW"), 0.70)}

# Bench Boost went in GW1. Under Jon's weights the reserve keeper banks 25% of a season and the
# fifth defender 40%, so those two are bought as cheaply as the rules allow. The fifth midfielder
# is NOT tanked — at 70% he plays more often than not.
TANK = {"GK": 1, "DEF": 1}


def best_xi_value(vals):
    """Best legal XI from {pos: [values, descending]}: minimums first, then the best of the rest."""
    xi, used = [], {}
    for pos, n in XI_MIN.items():
        take = vals.get(pos, [])[:n]
        if len(take) < n:
            return None
        xi += take
        used[pos] = n
    rest = []
    for pos, vs in vals.items():
        lo = used.get(pos, 0)
        rest += [(v, pos) for v in vs[lo:lo + XI_MAX[pos] - lo]]
    rest.sort(reverse=True)
    xi += [v for v, _ in rest[:11 - len(xi)]]
    return sum(xi) + max(xi)              # the captain counts twice


def resolve(name, team, pool_keys):
    """FPL spells names with accents; match on a loose key so FORCED can be written plainly."""
    def norm(s):
        # NFKD splits "ć" into "c" + a combining mark, so dropping the marks leaves plain ASCII.
        # Without this, isalpha() keeps the accent and "Dedic" never matches "Dedić".
        d = unicodedata.normalize("NFKD", s)
        return "".join(ch for ch in d.lower() if ch.isalpha() and not unicodedata.combining(ch))
    want = (norm(name), team)
    for k in pool_keys:
        if (norm(k[0]), k[1]) == want:
            return k
    return None


def main():
    for _ in W.auto_ingest_and_refresh():
        pass
    if W.POOL is None:
        W.build_pool()
    pool = {(c["name"], c["team"]): c for c in W.POOL}
    notes = []

    # every name in the FPL data, so a forced pick can be found even when the pool dropped him
    allnames = {(r.web_name, r.team_name): r for r in W.nxt.itertuples()}

    forced = []
    for nm, tm in FORCED:
        k = resolve(nm, tm, pool.keys())
        if k:
            forced.append(pool[k])
            continue
        k = resolve(nm, tm, allnames.keys())
        if not k:
            print(f"  !! {nm} ({tm}) is not in the FPL data at all")
            return
        r = allnames[k]
        forced.append(dict(code=int(r.code), name=k[0], pos=W.POSN[int(r.element_type)],
                           team=tm, price=r.now_cost / 10, ev=[0.0] * HORIZON,
                           defw=W.FR.RATINGS.get(tm, {}).get("defw", 1)))
        notes.append(f"{k[0]} is absent from the model pool (no minutes) — forced in by hand")

    gws = [GW0 + o for o in range(HORIZON)]
    wsum = sum(W.DECAY[i + 1] for i in range(HORIZON))
    # per-gameweek vectors, not a collapsed scalar: the captain is chosen weekly, so squad_value
    # needs to know who is best in EACH week
    cache = pathlib.Path(f"data/processed/evs_gw{GW0}.json")
    if cache.exists() and "--refresh" not in sys.argv:
        evs = {tuple(k.split("|")): v for k, v in json.load(open(cache, encoding="utf-8")).items()}
        print(f"  reusing {cache.name} (pass --refresh to recompute)")
        _write_cache = False
    else:
        evs = {(c["name"], c["team"]): [
            W.ev_multi(c["code"], c["name"], c["pos"], c["team"], g) for g in gws]
            for c in W.POOL}
        _write_cache = True
    val = {k: C.discounted(v) for k, v in evs.items()}
    for c in forced:
        k = (c["name"], c["team"])
        if k in val:
            continue
        src, p60 = PROXY.get((c["name"], c["team"]), (None, 0.0))
        if src is None:
            for pk, (s, p) in PROXY.items():
                if resolve(pk[0], pk[1], [k]):
                    src, p60 = s, p
        srck = resolve(src[0], src[1], val.keys()) if src else None
        if srck:
            val[k] = val[srck] * p60
            notes.append(f"{k[0]} priced at {p60:.0%} of {srck[0]} — an assumption, not data")
        else:
            val[k] = 0.0
            notes.append(f"{k[0]} has no proxy: scored 0, so he will sit on the bench")

    for c in forced:
        k = (c["name"], c["team"])
        if k not in evs:
            evs[k] = [val.get(k, 0.0) / wsum] * HORIZON     # flat, from the proxy assumption
    if _write_cache:
        # written AFTER the proxy loop on purpose: compare.py reads this same file, and a forced
        # player whose value is an assumption must carry that assumption across, not a silent zero
        C.save_evs(evs)

    def mk(c):
        return dict(name=c["name"], pos=c["pos"], team=c["team"], price=c["price"], code=c["code"])

    def obj(sq):
        # Jon's slot weights, shared with compare.py. Every player counts something: the fifth
        # midfielder plays more often than not, and the model used to score him zero.
        return C.squad_value(sq, evs)

    fkeys = {(c["name"], c["team"]) for c in forced}
    cands = {}
    for pos in QUOTA:
        top = sorted((c for c in W.POOL if c["pos"] == pos),
                     key=lambda c: -val[(c["name"], c["team"])])[:TOP_N]
        cheap = sorted((c for c in W.POOL if c["pos"] == pos), key=lambda c: c["price"])[:8]
        seen = {(c["name"], c["team"]) for c in top}
        cands[pos] = top + [c for c in cheap if (c["name"], c["team"]) not in seen]

    # seed: the forced picks, then the cheapest legal completion
    sq = [mk(c) for c in forced]
    for pos, n in QUOTA.items():
        need = n - sum(1 for p in sq if p["pos"] == pos)
        for c in sorted((x for x in W.POOL if x["pos"] == pos), key=lambda x: x["price"]):
            if need <= 0:
                break
            if (c["name"], c["team"]) in {(p["name"], p["team"]) for p in sq}:
                continue
            if sum(1 for p in sq if p["team"] == c["team"]) >= 3:
                continue
            sq.append(mk(c))
            need -= 1

    # tank the bench slots, then lock them so the climb cannot spend the XI's money there
    tanked = []
    for pos, n in TANK.items():
        for _ in range(n):
            here = {(x["name"], x["team"]) for x in sq}
            repl = max((x for x in sq if x["pos"] == pos
                        and (x["name"], x["team"]) not in fkeys
                        and (x["name"], x["team"]) not in tanked),
                       key=lambda x: x["price"], default=None)
            if repl is None:
                break
            for c in sorted((x for x in W.POOL if x["pos"] == pos),
                            key=lambda x: (x["price"], -val[(x["name"], x["team"])])):
                k = (c["name"], c["team"])
                if k in fkeys or (k in here and k != (repl["name"], repl["team"])):
                    continue
                if c["team"] != repl["team"] and \
                        sum(1 for x in sq if x["team"] == c["team"] and x is not repl) >= 3:
                    continue
                sq = [mk(c) if x is repl else x for x in sq]
                tanked.append(k)
                break

    locked = fkeys | set(tanked)
    best = obj(sq)
    rounds = 0
    for rounds in range(40):
        spend = sum(p["price"] for p in sq)
        club = {}
        for p in sq:
            club[p["team"]] = club.get(p["team"], 0) + 1
        held = {(p["name"], p["team"]) for p in sq}
        move = None
        for p in sq:
            if (p["name"], p["team"]) in locked:
                continue
            for c in cands[p["pos"]]:
                k = (c["name"], c["team"])
                if k in held:
                    continue
                if spend - p["price"] + c["price"] > BUDGET + 1e-9:
                    continue
                if club.get(c["team"], 0) + (0 if c["team"] == p["team"] else 1) > 3:
                    continue
                trial = [mk(c) if x is p else x for x in sq]
                v = obj(trial)
                if v > best + 1e-9 and (move is None or v > move[0]):
                    move = (v, trial)
        if move is None:
            break
        best, sq = move

    spend = sum(p["price"] for p in sq)
    poolkeys = {(c["name"], c["team"]) for c in W.POOL}
    for p in sq:
        k = (p["name"], p["team"])
        p["e"] = (W.ev_multi(p["code"], p["name"], p["pos"], p["team"], GW0)
                  if k in poolkeys else val[k] / wsum)
    # Pick the XI on the SAME number the squad was optimised on. W.select_xi recomputes EV from
    # the model, which scores a forced player it cannot see at zero and benches him regardless of
    # the proxy — so the reported XI would contradict the squad that was built.
    by = {}
    for p in sq:
        by.setdefault(p["pos"], []).append(p)
    for v in by.values():
        v.sort(key=lambda p: -val[(p["name"], p["team"])])
    xi, used = [], {}
    for pos, n in XI_MIN.items():
        xi += by.get(pos, [])[:n]
        used[pos] = n
    rest = []
    for pos, ps in by.items():
        lo = used.get(pos, 0)
        rest += ps[lo:XI_MAX[pos]]
    rest.sort(key=lambda p: -val[(p["name"], p["team"])])
    xi += rest[:11 - len(xi)]
    start = {(p["name"], p["team"]) for p in xi}

    cnt = {}
    for p in xi:
        cnt[p["pos"]] = cnt.get(p["pos"], 0) + 1
    print("")
    print(f"  WILDCARD SQUAD — GW{GW0}, £{spend:.1f}m spent, "
          f"{cnt.get('DEF', 0)}-{cnt.get('MID', 0)}-{cnt.get('FWD', 0)}, {rounds} climb rounds")
    print(f"  {'':4}{'player':<18}{'club':<6}{'pos':<5}{'£':>6}{'GW4 EV':>9}{'6wk val':>10}")
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    for p in sorted(sq, key=lambda x: (order[x["pos"]], -val[(x["name"], x["team"])])):
        k = (p["name"], p["team"])
        mark = "XI " if k in start else "   "
        # only call it tanked if it actually ended up on the bench — the cheap slots the climb
        # bought are sometimes good enough to start, and labelling those "tanked" reads as a bug
        tag = ("  <- your pick" if k in fkeys
               else ("  <- tank slot" if k in tanked and k not in start else ""))
        print(f"  {mark}{p['name'][:17]:<18}{p['team']:<6}{p['pos']:<5}{p['price']:>6.1f}"
              f"{p['e']:>9.2f}{val[k]:>10.1f}{tag}")
    print("")
    print(f"  captain: {max(xi, key=lambda p: p['e'])['name']}   bank: £{BUDGET - spend:.1f}m")
    if notes:
        print("")
        print("  ASSUMPTIONS — reads, not measurements:")
        for n in notes:
            print("    - " + n)


if __name__ == "__main__":
    main()
