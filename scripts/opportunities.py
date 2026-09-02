#!/usr/bin/env python3
"""opportunities.py — find the fixture swings, before anyone points them out.

WHY THIS EXISTS
Jon was doing this by eye: "I want a couple of Chelsea players from week 4 when their fixtures
swing", "I want out of Man Utd when theirs get harder", "Fulham have an easy run weeks 6-8". Every
one of those is mechanical — fixtures and team ratings are both in the model already — and having
the human spot them means the model is only ever reacting to what he happened to notice.

The division of labour this restores: the human supplies facts the data cannot see (a signing, a
suspension, a player hooked at half time). The model supplies strategy. Fixture runs are strategy.

WHAT IT REPORTS
  SWINGS IN     clubs whose run improves materially from some week, and the best routes into them
                that are actually legal and affordable for THIS squad — not a wishlist
  SWINGS OUT    clubs whose run hardens, and exactly which of your players that exposes
  CONCENTRATION where the squad is over-committed to one club's fixtures

METHOD
Each club-gameweek is scored by the attacking multiplier the EV model itself applies — the
opponent's defensive weakness, home/away adjusted — so "easy" here means the same thing it means
everywhere else in the engine. A club's run over a window is the mean of those. A swing is the
difference between the window starting at week w and the window ending just before it, so it
answers "does it get better from here", which is the question a transfer actually asks.

Horizon runs to GW19, the first-half chip expiry, because that is the window any hold-or-spend
decision lives in.

    python opportunities.py            # both teams
    python opportunities.py --gw 5     # pretend it is a different week
"""
from __future__ import annotations

import sys

import weekly as W
import ev_v2 as V
import fixture_ratings as FR

HALF_END = 19
WINDOW = 4              # a "run" is four gameweeks — long enough to be worth a transfer
# Below this a change is not worth acting on. Calibrated against the four swings Jon had already
# spotted by eye — Man Utd hardening, Newcastle and Everton improving, Fulham's GW6-8 run. At 0.12
# it found all four but missed Chelsea's GW4 swing by 0.01, which he had also called. Chelsea is a
# one-week cliff (Arsenal away at 0.50, then Hull at home at 1.57) that a four-week mean flattens,
# so the threshold rather than the window is the thing to relax.
SWING_MIN = 0.10


def club_week_ease(team, gw):
    """The attacking multiplier the EV model would apply to this club in this gameweek.
    None for a blank; the sum of both for a double."""
    fx = W.FIX.get(team, {}).get(gw)
    if not fx:
        return None
    opp, home = fx
    r = FR.RATINGS.get(opp)
    if not r:
        return None
    return r["defw"] * (V.HOME_ADV if home else 2 - V.HOME_ADV)


def run_score(team, start, n=WINDOW):
    vals = [club_week_ease(team, g) for g in range(start, min(start + n, HALF_END + 1))]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def swings(gw):
    """For each club: how its next window compares with the window it is just leaving."""
    out = []
    for team in sorted(W.FIX):
        nxt = run_score(team, gw)
        prev = run_score(team, max(1, gw - WINDOW))
        if nxt is None or prev is None:
            continue
        out.append(dict(team=team, now=nxt, prev=prev, delta=nxt - prev))
    return out


def best_run_ahead(team, gw, until=None):
    """The best four-week stretch this club has left, and when it starts.

    `until` bounds the search. Without it the whole half is searched, and a club whose best stretch
    is in GW14 has that returned — which then fails an actionability filter and hides a perfectly
    good GW4 run behind it. Chelsea was lost exactly this way."""
    best = None
    top = (until if until is not None else HALF_END - WINDOW + 1)
    for w in range(gw, min(top, HALF_END - WINDOW + 1) + 1):
        s = run_score(team, w)
        if s is not None and (best is None or s > best[1]):
            best = (w, s)
    return best


def routes_in(team, gw, squad, itb, n=4):
    """Who to buy for this club's run — filtered to what is legal and affordable for THIS squad.
    A suggestion you cannot execute is noise, and two of the errors in this project came from
    exactly that."""
    club = {}
    for p in squad:
        club[p["team"]] = club.get(p["team"], 0) + 1
    if club.get(team, 0) >= 3:
        return [], "already at the 3-player cap for this club"
    # what a sale could fund: the dearest player you hold in each position, plus the bank
    ceiling = {}
    for p in squad:
        ceiling[p["pos"]] = max(ceiling.get(p["pos"], 0.0), p["price"] + itb)
    rows = []
    for r in V._nxt[(V._nxt.team_name == team) & (V._nxt.status == "a")].itertuples():
        pos = W.POSN.get(int(r.element_type))
        if pos is None or pos == "GK":
            continue
        price = r.now_cost / 10.0
        if price > ceiling.get(pos, 0.0) + 1e-9:
            continue
        if any(p["name"] == r.web_name for p in squad):
            continue
        try:
            code = int(r.code)
            ev = sum(W.ev_gw(code, r.web_name, pos, team, g)
                     for g in range(gw, min(gw + WINDOW, HALF_END + 1)))
        except Exception:
            continue
        p60 = V.get_minutes_probs(code, r.web_name)["p60"]
        if p60 < 0.5:                       # not a route in if he does not play
            continue
        rows.append((ev, r.web_name, pos, price, p60))
    rows.sort(reverse=True)
    return rows[:n], None


def report(team_name, squad_def, itb, gw):
    squad = [dict(name=n, pos=p, team=t, price=pr) for (n, p, t, pr) in squad_def]
    held = {}
    for p in squad:
        held.setdefault(p["team"], []).append(p)
    sw = swings(gw)

    L = ["=" * 74, f"{team_name} — FIXTURE OPPORTUNITIES, GW{gw} to GW{HALF_END}", "=" * 74]

    L.append(f"\nSWINGS IN — clubs getting easier from GW{gw}\n" + "-" * 42)
    ups = [s for s in sorted(sw, key=lambda x: -x["delta"]) if s["delta"] >= SWING_MIN][:5]
    if not ups:
        L.append("  Nothing swinging materially this week.")
    for s in ups:
        n_held = len(held.get(s["team"], []))
        peak = best_run_ahead(s["team"], gw)
        L.append(f"  {s['team']:<5}run {s['prev']:.2f} -> {s['now']:.2f}  ({s['delta']:+.2f})"
                 f"   you hold {n_held}"
                 + (f"   best stretch starts GW{peak[0]} at {peak[1]:.2f}" if peak else ""))
        rows, why = routes_in(s["team"], gw, squad, itb)
        if why:
            L.append(f"        {why}")
        for ev, nm, pos, price, p60 in rows:
            L.append(f"        {pos:<4}{nm:<16}£{price:<6}p60 {p60:.2f}   EV next {WINDOW}: {ev:5.1f}")

    # Runs that have not started yet. The section above compares the window starting NOW against
    # the one just ended, so it cannot see a club whose good stretch begins in three weeks — and
    # those are the ones worth planning for rather than reacting to. "Chelsea from week 4" and
    # "Fulham weeks 6-8" are both of this shape.
    L.append(f"\nSWINGS COMING — runs that start later, worth planning towards\n" + "-" * 42)
    coming = []
    for team in sorted(W.FIX):
        now = run_score(team, gw)
        peak = best_run_ahead(team, gw + 1, until=gw + W.HORIZON)
        if now is None or peak is None:
            continue
        start, val = peak
        # Only runs you can still plan into. A +0.30 swing starting GW16 is a fact, not a decision:
        # by the time it matters the squad, the prices and the injuries will all have moved. Sorted
        # by when you have to act, not by size, because the near ones are the ones with a deadline.
        if gw < start <= gw + W.HORIZON and val - now >= SWING_MIN:
            coming.append((start, -(val - now), val, now, team))
    for start, negd, val, now, team in sorted(coming)[:5]:
        d = -negd
        n_held = len(held.get(team, []))
        L.append(f"  {team:<5}GW{start}-{min(start + WINDOW - 1, HALF_END)}  run {now:.2f} -> "
                 f"{val:.2f}  ({d:+.2f})   you hold {n_held}"
                 f"   act by GW{start - 1}")
        rows, why = routes_in(team, start, squad, itb, n=3)
        if why:
            L.append(f"        {why}")
        for ev, nm, pos, price, p60 in rows:
            L.append(f"        {pos:<4}{nm:<16}£{price:<6}p60 {p60:.2f}   "
                     f"EV GW{start}-{min(start + WINDOW - 1, HALF_END)}: {ev:5.1f}")
    if not coming:
        L.append("  No materially better run starting later in the half.")

    L.append(f"\nSWINGS OUT — clubs getting harder, and what you hold there\n" + "-" * 42)
    downs = [s for s in sorted(sw, key=lambda x: x["delta"]) if s["delta"] <= -SWING_MIN]
    shown = 0
    for s in downs:
        mine = held.get(s["team"], [])
        if not mine:
            continue
        shown += 1
        L.append(f"  {s['team']:<5}run {s['prev']:.2f} -> {s['now']:.2f}  ({s['delta']:+.2f})")
        for p in sorted(mine, key=lambda x: -x["price"]):
            try:
                code = W.code_of(p["name"], p["pos"], p["team"])
                ev = sum(W.ev_gw(code, p["name"], p["pos"], p["team"], g)
                         for g in range(gw, min(gw + WINDOW, HALF_END + 1)))
                L.append(f"        {p['pos']:<4}{p['name']:<16}£{p['price']:<6}"
                         f"EV next {WINDOW}: {ev:5.1f}")
            except Exception:
                L.append(f"        {p['pos']:<4}{p['name']}")
    if not shown:
        L.append("  None of your clubs are hardening materially.")

    L.append(f"\nCONCENTRATION — where the squad is committed\n" + "-" * 42)
    rows = []
    for team, ps in held.items():
        r = run_score(team, gw)
        if r is None:
            continue
        rows.append((len(ps), r, team, ps))
    for n, r, team, ps in sorted(rows, key=lambda x: (-x[0], x[1])):
        flag = "   <- three players into a hardening run" if (n >= 3 and r < 1.0) else ""
        L.append(f"  {team:<5}{n} player{'s' if n > 1 else ' '}  run {r:.2f}   "
                 + ", ".join(p["name"] for p in ps) + flag)
    return "\n".join(L)


def main():
    W.auto_ingest_and_refresh()
    gw = int(sys.argv[sys.argv.index("--gw") + 1]) if "--gw" in sys.argv else W.CURRENT_GW + 1
    # Squads are declared inside weekly.py's __main__ block, so they cannot be imported. Repeated
    # here rather than refactoring weekly.py mid-flight; fetch_squads.py is the source for both and
    # they are re-pasted from it, not hand-maintained.
    SANTA = [("Leno","GK","FUL",4.5),("Sánchez","GK","CHE",4.9),
             ("Van Hecke","DEF","TOT",5.0),("De Cuyper","DEF","BHA",4.7),("Calafiori","DEF","ARS",5.6),
             ("Gvardiol","DEF","MCI",5.6),("Senesi","DEF","TOT",6.0),
             ("Schade","MID","BRE",6.0),("Palmer","MID","CHE",9.6),("Mbeumo","MID","MUN",8.0),
             ("Gomez","MID","BHA",5.0),("Sarr","MID","CRY",6.4),
             ("Haaland","FWD","MCI",15.5),("Calvert-Lewin","FWD","LEE",6.0),("Mateta","FWD","CRY",6.4)]
    HUMAN = [("Kinsky","GK","TOT",4.5),("Verbruggen","GK","BHA",4.5),
             ("Shaw","DEF","MUN",4.5),("Gabriel","DEF","ARS",8.0),("Calafiori","DEF","ARS",5.6),
             ("Ajer","DEF","BRE",4.5),("F.Kadıoğlu","DEF","BHA",4.4),
             ("Schade","MID","BRE",6.0),("Mbeumo","MID","MUN",8.0),("Tzolis","MID","ARS",6.5),
             ("Semenyo","MID","MCI",8.5),("Hinshelwood","MID","BHA",6.0),
             ("João Pedro","FWD","CHE",7.6),("Haaland","FWD","MCI",15.5),("Calvert-Lewin","FWD","LEE",6.0)]
    print(report("JON'S TEAM", HUMAN, 0.0, gw))
    print()
    print(report("SANTA CLAUDE", SANTA, 0.9, gw))


if __name__ == "__main__":
    main()
