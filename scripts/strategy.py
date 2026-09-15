#!/usr/bin/env python3
"""strategy.py — the strategy layer. Decides chips AND transfers, and does not ask.

WHAT THIS IS FOR

The model had a player-points forecast (forecast.py), a squad optimiser (squad_opt.py) and a
transfer optimiser (transfer_opt.py), but nothing that decided WHEN TO PLAY A CHIP. That gap was
being filled by asking a human "should I wildcard this week?" - which is the wrong shape. The
answer depends on the projections, the squad, the free transfers and the rules, all of which the
model holds and the human does not.

So this searches the plan space and returns a recommendation of the form:

    play the WILDCARD in GW4 and the BENCH BOOST in GW11; worth +23.4 over doing neither,
    and better than any other combination it can see.

WHAT IT SEARCHES

  WILDCARD    unlimited transfers in one week. Evaluated at every candidate week: transfer
              normally until then, rebuild, then carry on transferring.
  BENCH BOOST the bench scores that week, so it wants the week where the squad you will
              ACTUALLY HOLD has its best bench.
  TRIPLE CAPT captain scores 3x rather than 2x - worth one extra captain.
  FREE HIT    a one-week squad, discarded after: the best possible XI that week minus the XI you
              would otherwise have fielded.

Chips interact, so the three are valued against the squad path the wildcard decision implies.
Two chips cannot be played in the same week.

BLANKS AND DOUBLES, AND WHY THIS HORIZON IS SAFE

Bench Boost and Free Hit are usually held for double and blank gameweeks. Those come almost
entirely in the SECOND HALF of a season, from the FA Cup and European rearrangements - the first
half is very nearly all single gameweeks (Jon, 2026-09-10). So over a GW4-16 horizon there is
nothing to hold a chip back FOR, and a chip left unplayed here is not being saved for a double,
it is simply idle. The model cannot see this: every fixture it holds out to GW16 is a single, so
it would happily conclude the same thing for the second half, where it would be wrong. Before
using this to plan a chip beyond roughly GW20, teach it what a double gameweek is.

WHAT IT DELIBERATELY DOES NOT DO

It does not read planned_wildcard. Requiring a human to declare a chip week and then optimising
around that declaration is backwards, and weekly.planned_wildcard() makes it worse by collapsing
the horizon to one gameweek when told a chip is coming, which suppresses nearly every transfer.
The chip week is an OUTPUT of this file, not an input to it.

    python scripts/strategy.py --entry 4180925
    python scripts/strategy.py --entry 1169767 --horizon 13
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import squad_opt as SO

API = "https://fantasy.premierleague.com/api"
ROOT = Path(__file__).resolve().parent.parent
MAX_BANK = 5


def _arg(flag, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def live(entry, gw=None):
    """Squad, bank, chips and free transfers, read live.

    The gameweek is derived here rather than taken from the forecast file. Picks are only public
    AFTER a deadline, so asking for the upcoming gameweek returns 404 - it has to be the last
    FINISHED one. A forecast file carrying a stale or zeroed current_gw then fails in a way that
    looks like an API outage rather than a bad field, which is what happened on 2026-09-10.
    """
    boot = json.load(urllib.request.urlopen(API + "/bootstrap-static/"))
    if gw is None or gw < 1:
        gw = max([e["id"] for e in boot["events"] if e.get("finished")], default=1)
    el = {e["id"]: e for e in boot["elements"]}
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    picks = json.load(urllib.request.urlopen(API + "/entry/%d/event/%d/picks/" % (entry, gw)))
    hist = json.load(urllib.request.urlopen(API + "/entry/%d/history/" % entry))
    used = {c["name"] for c in hist.get("chips", [])}
    keys, meta, spend = [], {}, 0.0
    for p in picks["picks"]:
        e = el[p["element"]]
        k = e["web_name"] + "|" + short[e["team"]]
        keys.append(k)
        spend += e["now_cost"] / 10.0
        meta[k] = dict(pos=POS[e["element_type"]], team=short[e["team"]],
                       price=e["now_cost"] / 10.0)
    bank = picks["entry_history"]["bank"] / 10.0
    # Free transfers available for the NEXT gameweek. One arrives each week, banked to MAX_BANK.
    # A Wildcard or Free Hit week leaves the count exactly where it was: the moves made that week
    # use none of it, but the week's new transfer does not arrive either. Checked against the app:
    # Santa Claude had 1 going into its GW4 wildcard and has 1 for GW5, not 2.
    chip_week = {c["event"] for c in hist.get("chips", []) if c["name"] in ("wildcard", "freehit")}
    ft = 1                                            # available for GW2
    for g in hist["current"]:
        e = g["event"]
        if e < 2 or e > gw or e in chip_week:
            continue
        ft = min(max(ft - g["event_transfers"], 0) + 1, MAX_BANK)
    return keys, meta, bank, spend, used, ft


def xi(keys, w, P):
    rows = [(P[k]["ev"][w], P[k]["pos"], k) for k in keys]
    gk = sorted([r for r in rows if r[1] == "GK"], reverse=True)
    out = gk[:1]
    rest = [r for r in rows if r[1] != "GK"]
    for pos, mn in (("DEF", 3), ("MID", 2), ("FWD", 1)):
        out += sorted([r for r in rest if r[1] == pos], reverse=True)[:mn]
    chosen = {r[2] for r in out}
    out += sorted([r for r in rest if r[2] not in chosen], reverse=True)[: 11 - len(out)]
    chosen = {r[2] for r in out}
    bench = gk[1:] + [r for r in rest if r[2] not in chosen]
    return [r[2] for r in out], [r[2] for r in bench], max(r[0] for r in out)


def score_week(keys, w, P):
    x, _, cap = xi(keys, w, P)
    return sum(P[k]["ev"][w] for k in x) + cap


def bench_pts(keys, w, P):
    _, b, _ = xi(keys, w, P)
    return sum(P[k]["ev"][w] for k in b)


def path(P, decay, H, held, budget, wc=None, pool=55, ft=1):
    """The squad held each week: free transfers accruing weekly, plus a wildcard rebuild if given.

    `ft` is how many are BANKED NOW and it matters. Village Idiots came into GW4 having rolled
    three times; assuming one made the no-wildcard path look worse than it is and inflated the
    wildcard by several points. A chip is being compared against what you could do without it, so
    what you could do without it has to be right.
    """
    squads, base = [], list(held)
    for i in range(H):
        sub = {k: dict(v, ev=v["ev"][i:]) for k, v in P.items()}
        if wc is not None and i == wc:
            base, _, _ = SO.solve(sub, decay[i:], H - i, budget=budget, pool_per_pos=pool)
            squads.append(list(base))
            continue
        nt = min(ft + i, MAX_BANK) if (wc is None or i < wc) else min(i - wc, MAX_BANK)
        if nt <= 0:
            squads.append(list(base))
            continue
        keys, _, _ = SO.solve(sub, decay[i:], H - i, budget=budget, pool_per_pos=pool,
                              keep=base, max_changes=nt)
        squads.append(list(keys))
    return squads


def free_hit_gain(P, squads, w, budget, pool=55):
    one = {k: dict(v, ev=[v["ev"][w]]) for k, v in P.items()}
    best, _, _ = SO.solve(one, [1.0], 1, budget=budget, pool_per_pos=pool)
    return score_week(best, 0, one) - score_week(squads[w], w, P)


def main():
    entry = _arg("--entry", 4180925, int)
    fpath = _arg("--forecast", None)
    if fpath is None:                                  # newest long forecast on disk
        import glob, re as _re
        cands = glob.glob(str(ROOT / "data" / "processed" / "_forecast_long_gw*_*.json"))
        fpath = max(cands, key=lambda f: int(_re.search(r"_gw(\d+)_", f).group(1)))
    fc = json.load(open(fpath, encoding="utf-8"))
    print("  forecast:", fpath.split("\\")[-1].split("/")[-1])
    H = min(_arg("--horizon", 13, int), fc["horizon"])
    decay = [fc["decay"][str(i + 1)] for i in range(H)]
    P = {k: dict(v, ev=v["ev"][:H]) for k, v in fc["players"].items()}
    gw0 = fc["gw0"]
    # The forecast knows which gameweek its data runs to; prefer that over the API's "finished" flag,
    # which lags a day or two behind the last match while bonus points are confirmed.
    held, meta, bank, spend, used, ft = live(entry, fc.get("current_gw") or None)
    budget = spend + bank
    for k in held:
        if k not in P:
            P[k] = dict(meta[k], ev=[0.0] * H, p60=0.0, confidence=0.0)
    avail = {"wildcard", "bboost", "3xc", "freehit"} - used
    print("\n  ENTRY %d - planning GW%d-%d" % (entry, gw0, gw0 + H - 1))
    print("  budget %.1f - %d free transfer(s) - chips available: %s"
          % (budget, ft, ", ".join(sorted(avail)) or "none"))

    cands = [None] + (list(range(0, H - 1)) if "wildcard" in avail else [])
    best = None
    print("\n  searching wildcard weeks:")
    for wc in cands:
        sq = path(P, decay, H, held, budget, wc=wc, ft=ft)
        tot = sum(score_week(sq[i], i, P) * decay[i] for i in range(H))
        lab = "none" if wc is None else "GW%d" % (gw0 + wc)
        print("    %-6s %8.1f" % (lab, tot))
        if best is None or tot > best[1]:
            best = (wc, tot, sq)
    wc, base_tot, squads = best
    print("  -> best wildcard: %s (%.1f)" % ("none" if wc is None else "GW%d" % (gw0 + wc),
                                             base_tot))

    opts = {}
    if "bboost" in avail:
        opts["bboost"] = [(i, bench_pts(squads[i], i, P) * decay[i]) for i in range(H)]
    if "3xc" in avail:
        opts["3xc"] = [(i, xi(squads[i], i, P)[2] * decay[i]) for i in range(H)]
    if "freehit" in avail:
        opts["freehit"] = [(i, free_hit_gain(P, squads, i, budget) * decay[i]) for i in range(H)]
    print()
    for name, rows in opts.items():
        rows.sort(key=lambda r: -r[1])
        print("  %-9s best weeks: %s" % (name, ", ".join("GW%d %+.1f" % (gw0 + i, v)
                                                         for i, v in rows[:3])))

    plan, gain, taken = [], 0.0, ({wc} if wc is not None else set())
    for name, rows in sorted(opts.items(), key=lambda kv: -kv[1][0][1]):
        for i, v in rows:
            if i not in taken and v > 0:
                plan.append((name, gw0 + i, v))
                taken.add(i)
                gain += v
                break
    print("\n  ==================== PLAN ====================")
    if wc is not None:
        print("   WILDCARD   GW%d" % (gw0 + wc))
    for name, g, v in plan:
        print("   %-10s GW%-3d worth %+.1f" % (name.upper(), g, v))
    print("   projected GW%d-%d: %.1f  (%.1f squad and transfers, %+.1f remaining chips)"
          % (gw0, gw0 + H - 1, base_tot + gain, base_tot, gain))
    x, b, _ = xi(squads[0], 0, P)
    print("\n   GW%d XI: %s" % (gw0, ", ".join(k.split("|")[0] for k in x)))
    print("   bench:  %s" % ", ".join(k.split("|")[0] for k in b))


if __name__ == "__main__":
    main()
